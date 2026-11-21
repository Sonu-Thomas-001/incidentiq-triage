"""Orchestration around the compiled graph: build state, invoke, present the stored run."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models import Incident, User, WorkflowRun
from app.services import routing_policy
from app.workflow.graph import build_graph
from app.workflow.nodes import WorkflowDeps


def _invoke(
    db: Session, actor: User, state: dict[str, Any], deps: WorkflowDeps | None = None
) -> dict[str, Any]:
    deps = deps or WorkflowDeps(db=db, actor=actor, settings=get_settings())
    final = build_graph().invoke({**state, "trace": []}, config={"configurable": {"deps": deps}})
    run = db.get(WorkflowRun, uuid.UUID(final["run_id"]))
    if run is None:  # pragma: no cover - the graph always persists or replays a run
        raise NotFoundError("Workflow run not found")
    return present(run, reused=bool(final.get("reused")))


def present(run: WorkflowRun, reused: bool = False) -> dict[str, Any]:
    s = run.state
    return {
        "run_id": run.id,
        "kind": run.kind,
        "status": run.status,
        "reused": reused,
        "outcome": s.get("outcome"),
        "prediction_id": run.prediction_id,
        "input_issues": s.get("input_issues", []),
        "priority_inputs": s.get("priority_inputs", {}),
        "ml": s.get("ml"),
        "explanation": s.get("explanation"),
        "assist": s.get("assist"),
        "routing": s.get("routing"),
        "review": s.get("review"),
        "approved": s.get("approved"),
        "trace": run.trace,
        "created_at": run.created_at,
    }


def run_triage(
    db: Session,
    actor: User,
    incident_id: uuid.UUID,
    *,
    expected_version: int,
    impact: int | None,
    urgency: int | None,
    use_gemini: bool,
    external_data_consent: bool,
    deps: WorkflowDeps | None = None,
) -> dict[str, Any]:
    return _invoke(
        db,
        actor,
        {
            "action": "triage",
            "incident_id": str(incident_id),
            "actor_id": str(actor.id),
            "expected_version": expected_version,
            "impact": impact,
            "urgency": urgency,
            "use_gemini": use_gemini,
            "external_data_consent": external_data_consent,
        },
        deps,
    )


def approve(
    db: Session,
    actor: User,
    incident_id: uuid.UUID,
    *,
    expected_version: int,
    team_id: uuid.UUID,
    priority: str | None,
    category: str | None,
    reason: str | None,
    run_id: uuid.UUID | None,
) -> dict[str, Any]:
    return _invoke(
        db,
        actor,
        {
            "action": "approve",
            "incident_id": str(incident_id),
            "actor_id": str(actor.id),
            "expected_version": expected_version,
            "approval": {
                "team_id": str(team_id),
                "priority": priority,
                "category": category,
                "reason": reason,
                "run_id": str(run_id) if run_id else None,
            },
        },
    )


def list_runs(db: Session, incident_id: uuid.UUID) -> list[dict[str, Any]]:
    if db.get(Incident, incident_id) is None:
        raise NotFoundError("Incident not found")
    runs = db.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.incident_id == incident_id)
        .order_by(WorkflowRun.created_at, WorkflowRun.id)
    ).all()
    return [present(r) for r in runs]


def effective_config() -> dict[str, Any]:
    s = get_settings()
    return {
        "routing": routing_policy.RoutingConfig.from_settings(s).as_dict(),
        "gemini": {
            "enabled": s.gemini_enabled,
            "credentials_configured": bool(
                s.google_api_key and s.google_api_key.get_secret_value().strip()
            ),
            "model": s.gemini_model,
            "timeout_seconds": s.gemini_timeout_seconds,
            "max_retries": s.gemini_max_retries,
            "max_input_chars": s.gemini_max_input_chars,
        },
        "note": "Routing never auto-assigns. Secrets are never returned.",
    }
