"""Autopilot: pick up new, unassigned ServiceNow tickets, triage them, and (optionally) assign locally.

Safety properties:
- Read-only toward ServiceNow. It never PATCHes the remote record; writing the group back still
  requires the separate preview + typed-host confirmation flow.
- Only tickets that are in state New and have no assignment group are considered.
- Idempotent: import is per sys_id and each incident is triaged once.
- Local auto-assignment happens only when AUTOPILOT_AUTO_ASSIGN=true AND routing is enabled AND the
  routing policy returns PROPOSE_ASSIGNMENT (calibrated confidence >= both thresholds, models trained
  on ServiceNow data, team maps to a local team, impact/urgency present). Otherwise the incident
  stays in NEEDS_REVIEW for an analyst.
- Every automatic decision is attributed to a dedicated inactive system user and audited.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.integrations.servicenow import service as sn
from app.models import Incident, User
from app.models.enums import Role
from app.services import audit
from app.workflow import service as workflow

logger = logging.getLogger("app.autopilot")

AUTOPILOT_EMAIL = "autopilot@system.local"
AUTO_REASON = "Auto-assigned by policy: calibrated confidence met the configured thresholds"

_lock = threading.Lock()
_status: dict[str, Any] = {"last_run_at": None, "last_result": None, "running": False}


def status() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": s.autopilot_enabled,
        "auto_assign": s.autopilot_auto_assign,
        "routing_enabled": s.routing_enabled,
        "interval_seconds": s.autopilot_interval_seconds,
        "max_per_cycle": s.autopilot_max_per_cycle,
        **_status,
    }


def _autopilot_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == AUTOPILOT_EMAIL))
    if user is None:
        # Inactive with an unusable hash: it can act through the workflow but never log in.
        user = User(
            email=AUTOPILOT_EMAIL,
            full_name="IncidentIQ autopilot (system)",
            password_hash="!",
            role=Role.TRIAGE_ANALYST,
            is_active=False,
            is_synthetic=False,
        )
        db.add(user)
        db.commit()
    return user


def _process(db: Session, actor: User, rec: dict[str, Any], settings: Settings) -> dict[str, Any]:
    imported = sn.import_incident(db, actor, rec["sys_id"])
    if not imported["created"]:
        return {"number": rec["number"], "action": "already_imported"}
    incident = db.get(Incident, imported["incident_id"])
    assert incident is not None
    data = workflow.run_triage(
        db,
        actor,
        incident.id,
        expected_version=incident.version,
        impact=rec["impact"],
        urgency=rec["urgency"],
        use_gemini=False,  # never sends ticket text to an external API automatically
        external_data_consent=False,
    )
    routing = data.get("routing") or {}
    out = {
        "number": rec["number"],
        "action": "triaged",
        "decision": routing.get("decision"),
        "reasons": routing.get("reasons"),
    }
    review = data.get("review") or {}
    if (
        not settings.autopilot_auto_assign
        or routing.get("decision") != "PROPOSE_ASSIGNMENT"
        or not review.get("recommended_team_id")
    ):
        return out
    db.refresh(incident)
    category = ((data.get("ml") or {}).get("outputs", {}).get("category") or {}).get("label")
    approved = workflow.approve(
        db,
        actor,
        incident.id,
        expected_version=incident.version,
        team_id=uuid.UUID(review["recommended_team_id"]),
        priority=review.get("recommended_priority"),
        category=category,
        reason=AUTO_REASON,
        run_id=data["run_id"],
    )
    audit.record(
        db,
        event_type="AUTOPILOT_AUTO_ASSIGNED",
        actor_id=actor.id,
        incident_id=incident.id,
        details={
            "workflow_run_id": str(approved["run_id"]),
            "thresholds": routing.get("thresholds"),
            "checks": routing.get("checks"),
            "writes_to_servicenow": False,
        },
    )
    db.commit()
    return {**out, "action": "auto_assigned"}


def run_cycle(db: Session, settings: Settings | None = None) -> dict[str, Any]:
    """One polling pass. Never raises: failures are reported in the result."""
    settings = settings or get_settings()
    if not _lock.acquire(blocking=False):
        return {"skipped": "a cycle is already running"}
    _status["running"] = True
    result: dict[str, Any] = {"processed": [], "errors": []}
    try:
        if not settings.servicenow_enabled:
            result["skipped"] = "ServiceNow integration is disabled"
            return result
        actor = _autopilot_user(db)
        page = sn.list_remote_incidents(1, 100, state="1", query=None, group=None)
        candidates = [r for r in page["items"] if not r["assignment_group_sys_id"]]
        for rec in candidates[: settings.autopilot_max_per_cycle]:
            try:
                result["processed"].append(_process(db, actor, rec, settings))
            except Exception as exc:  # one bad ticket must not stop the cycle
                db.rollback()
                logger.warning("autopilot failed for %s: %s", rec.get("number"), type(exc).__name__)
                result["errors"].append({"number": rec.get("number"), "error": type(exc).__name__})
        result["candidates"] = len(candidates)
    except Exception as exc:
        db.rollback()
        logger.warning("autopilot cycle failed: %s", type(exc).__name__)
        result["errors"].append({"error": type(exc).__name__, "message": str(exc)[:200]})
    finally:
        _status.update(
            running=False,
            last_run_at=datetime.now(UTC).isoformat(),
            last_result={
                "processed": len(result["processed"]),
                "auto_assigned": sum(p["action"] == "auto_assigned" for p in result["processed"]),
                "errors": len(result["errors"]),
            },
        )
        _lock.release()
    return result


def _cycle_in_new_session() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        run_cycle(db)


async def poll_forever(interval: float) -> None:
    while True:
        await asyncio.to_thread(_cycle_in_new_session)
        await asyncio.sleep(interval)
