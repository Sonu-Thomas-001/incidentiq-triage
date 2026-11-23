"""ServiceNow integration service: gating, import, team mapping and approved synchronization.

Safety rules enforced here (not in the router):
* Nothing is written to ServiceNow except via `approve_sync`, which needs a prior preview, an
  explicit confirmation and the exact instance host.
* Writes are impossible in `read_only` mode and when the integration is disabled.
* One logical write per (instance, record, assignment, group): replays are no-ops.
* A failed sync never alters the local assignment or its approval history.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import (
    ConflictError,
    IntegrationDisabledError,
    NotFoundError,
    UpstreamError,
    ValidationFailure,
    WriteDisabledError,
)
from app.integrations.servicenow import mapping
from app.integrations.servicenow.client import (
    HttpServiceNowClient,
    ServiceNowClient,
    validate_sys_id,
)
from app.models import Assignment, Incident, SyncRecord, Team, User
from app.models.enums import IncidentStatus, Role, SyncStatus
from app.services import audit
from app.services import incidents as svc

SYSTEM = "servicenow"
IMPORT_USER_EMAIL = "servicenow-import@system.local"
STALE_CLAIM = timedelta(minutes=5)
WRITE_MODES = {"live"}

_client_override: Callable[[Settings], ServiceNowClient] | None = None


def set_client_factory(factory: Callable[[Settings], ServiceNowClient] | None) -> None:
    """Test hook: inject a client (for example one built on httpx.MockTransport)."""
    global _client_override
    _client_override = factory


def get_client(settings: Settings | None = None) -> ServiceNowClient:
    settings = settings or get_settings()
    if not settings.servicenow_enabled:
        raise IntegrationDisabledError(
            "ServiceNow integration is disabled (SERVICENOW_ENABLED=false)"
        )
    if _client_override is not None:
        return _client_override(settings)
    return _http_client(settings)


_http_cache: tuple[Settings, HttpServiceNowClient] | None = None


def _http_client(settings: Settings) -> HttpServiceNowClient:
    """Reuse one connection pool per settings object instead of leaking a client per call."""
    global _http_cache
    if _http_cache is not None and _http_cache[0] is settings:
        return _http_cache[1]
    if _http_cache is not None:
        _http_cache[1].close()
    client = HttpServiceNowClient(settings)
    _http_cache = (settings, client)
    return client


def _writes_allowed(settings: Settings) -> bool:
    return settings.servicenow_enabled and settings.servicenow_mode in WRITE_MODES


def health(settings: Settings | None = None) -> dict[str, Any]:
    """Never raises; reports configuration state and (when enabled) a light reachability probe."""
    s = settings or get_settings()
    out: dict[str, Any] = {
        "enabled": s.servicenow_enabled,
        "mode": s.servicenow_mode,
        "auth": s.servicenow_auth,
        "credentials_configured": bool(
            s.servicenow_username
            and s.servicenow_password
            and s.servicenow_password.get_secret_value()
        ),
        "writes_allowed": _writes_allowed(s),
        "instance_host": None,
        "reachable": None,
        "detail": None,
    }
    if not s.servicenow_enabled:
        out["detail"] = "Integration disabled; the application runs fully offline."
        return out
    try:
        client = get_client(s)
        out["instance_host"] = client.host
        client.list_groups(limit=1, offset=0)
        out["reachable"] = True
    except (UpstreamError, IntegrationDisabledError, ValidationFailure) as exc:
        out["reachable"] = False
        out["detail"] = exc.message
        out["error_code"] = getattr(exc, "code", None)
    return out


# ---- reads --------------------------------------------------------------------------------


def _page(total: int | None, items: list, page: int, size: int) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page, "page_size": size}


def list_remote_incidents(
    page: int, page_size: int, *, state: str | None, query: str | None, group: str | None
) -> dict[str, Any]:
    s = get_settings()
    size = min(page_size, s.servicenow_page_size_max)
    rows, total = get_client(s).list_incidents(
        limit=size, offset=(page - 1) * size, state=state, query=query, group=group
    )
    return _page(total, [mapping.to_local(r) for r in rows], page, size)


def get_remote_incident(sys_id: str) -> dict[str, Any]:
    return mapping.to_local(get_client().get_incident(validate_sys_id(sys_id)))


def list_remote_groups(page: int, page_size: int) -> dict[str, Any]:
    s = get_settings()
    size = min(page_size, s.servicenow_page_size_max)
    rows, total = get_client(s).list_groups(limit=size, offset=(page - 1) * size)
    items = [
        {
            "sys_id": r.get("sys_id"),
            "name": r.get("name"),
            "description": r.get("description"),
            "active": str(r.get("active")).lower() == "true",
        }
        for r in rows
    ]
    return _page(total, items, page, size)


# ---- team mapping -------------------------------------------------------------------------


def list_team_mappings(db: Session) -> list[dict[str, Any]]:
    teams = db.scalars(select(Team).order_by(Team.name)).all()
    return [
        {"team_id": t.id, "team_name": t.name, "servicenow_group_sys_id": t.servicenow_group_sys_id}
        for t in teams
    ]


def set_team_mapping(
    db: Session, actor: User, team_id: uuid.UUID, group_sys_id: str | None
) -> dict:
    team = db.get(Team, team_id)
    if team is None:
        raise NotFoundError("Team not found")
    new = validate_sys_id(group_sys_id) if group_sys_id else None
    old = team.servicenow_group_sys_id
    team.servicenow_group_sys_id = new
    audit.record(
        db,
        event_type="SERVICENOW_TEAM_MAPPING_CHANGED",
        actor_id=actor.id,
        details={"team_id": str(team.id), "from": old, "to": new},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("That ServiceNow group is already mapped to another team") from exc
    return {"team_id": team.id, "team_name": team.name, "servicenow_group_sys_id": new}


MAX_GROUP_IMPORT = 500


def import_groups_as_teams(db: Session, actor: User) -> dict[str, Any]:
    """Create one local team per active ServiceNow assignment group (idempotent, read-only remote)."""
    s = get_settings()
    client = get_client(s)
    created: list[str] = []
    skipped: list[dict[str, str]] = []
    seen = 0
    offset = 0
    while seen < MAX_GROUP_IMPORT:
        rows, _total = client.list_groups(limit=100, offset=offset)
        if not rows:
            break
        for r in rows:
            seen += 1
            sys_id, name = r.get("sys_id"), (r.get("name") or "").strip()
            if str(r.get("active")).lower() != "true" or not sys_id or not name:
                continue
            if db.scalar(select(Team).where(Team.servicenow_group_sys_id == sys_id)):
                continue
            if db.scalar(select(Team).where(Team.name == name[:100])):
                skipped.append({"name": name, "reason": "a local team with this name exists"})
                continue
            db.add(
                Team(
                    name=name[:100],
                    description=(r.get("description") or None) and str(r["description"])[:500],
                    servicenow_group_sys_id=sys_id,
                    is_synthetic=False,
                )
            )
            created.append(name)
        offset += len(rows)
        if len(rows) < 100:
            break
    audit.record(
        db,
        event_type="SERVICENOW_GROUPS_IMPORTED",
        actor_id=actor.id,
        details={"instance_host": client.host, "created": created, "skipped": skipped},
    )
    db.commit()
    return {"created": created, "skipped": skipped}


# ---- import -------------------------------------------------------------------------------


def _import_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == IMPORT_USER_EMAIL))
    if user is None:
        # Inactive with an unusable hash: it owns imported rows but can never log in.
        user = User(
            email=IMPORT_USER_EMAIL,
            full_name="ServiceNow import (system)",
            password_hash="!",
            role=Role.REPORTER,
            is_active=False,
            is_synthetic=False,
        )
        db.add(user)
        db.flush()
    return user


def import_incident(db: Session, actor: User, sys_id: str) -> dict[str, Any]:
    """Import one open ServiceNow incident as a local NEW incident. Idempotent per sys_id."""
    s = get_settings()
    sys_id = validate_sys_id(sys_id)
    client = get_client(s)
    existing = db.scalar(
        select(Incident).where(
            Incident.external_system == SYSTEM, Incident.external_sys_id == sys_id
        )
    )
    if existing is not None:
        return {
            "created": False,
            "incident_id": existing.id,
            "external_number": existing.external_number,
        }
    mapped = mapping.to_local(client.get_incident(sys_id))
    if not mapped["importable"]:
        raise ConflictError(
            f"ServiceNow state '{mapped['state_label']}' is not importable (only New, In Progress, On Hold)",
            {"state": mapped["state"]},
        )
    title = (mapped["title"] or mapped["number"] or "ServiceNow incident")[:200]
    description = mapped["description"] or mapped["title"] or "(no description in source record)"
    incident = Incident(
        title=title,
        description=description,
        reporter_id=_import_user(db).id,
        is_synthetic=False,
        external_system=SYSTEM,
        external_sys_id=sys_id,
        external_number=mapped["number"],
        external_snapshot=mapping.snapshot(mapped),
    )
    db.add(incident)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        dup = db.scalar(
            select(Incident).where(
                Incident.external_system == SYSTEM, Incident.external_sys_id == sys_id
            )
        )
        if dup is None:
            raise
        return {"created": False, "incident_id": dup.id, "external_number": dup.external_number}
    audit.record(
        db,
        event_type="SERVICENOW_INCIDENT_IMPORTED",
        actor_id=actor.id,
        incident_id=incident.id,
        to_status=IncidentStatus.NEW,
        details={
            "instance_host": client.host,
            "sys_id": sys_id,
            "number": mapped["number"],
            "source_state": mapped["state_label"],
            "read_only_import": True,
        },
    )
    db.commit()
    return {
        "created": True,
        "incident_id": incident.id,
        "external_number": incident.external_number,
    }


# ---- approved synchronization -------------------------------------------------------------


def _idem_key(host: str, sys_id: str, assignment_id: uuid.UUID, group: str) -> str:
    raw = "|".join([SYSTEM, host, sys_id, str(assignment_id), group])
    return hashlib.sha256(raw.encode()).hexdigest()


def _sync_incident(db: Session, incident_id: uuid.UUID) -> tuple[Incident, Assignment, Team]:
    incident = svc._get_incident(db, incident_id)
    if incident.external_system != SYSTEM or not incident.external_sys_id:
        raise ValidationFailure("This incident has no ServiceNow reference; import it first")
    assignment = svc.current_assignment(db, incident_id)
    if assignment is None:
        raise ConflictError("No approved assignment to synchronize; approve an assignment first")
    team = db.get(Team, assignment.team_id)
    if team is None or not team.servicenow_group_sys_id:
        raise ConflictError(
            "The assigned team has no ServiceNow group mapping", {"code": "TEAM_NOT_MAPPED"}
        )
    return incident, assignment, team


def _present(rec: SyncRecord, team: Team | None, settings: Settings) -> dict[str, Any]:
    return {
        "sync_id": rec.id,
        "incident_id": rec.incident_id,
        "assignment_id": rec.assignment_id,
        "status": rec.status,
        "target_instance_host": rec.instance_host,
        "external_sys_id": rec.external_sys_id,
        "external_number": rec.external_number,
        "target_team": team.name if team else None,
        "field_changes": rec.field_changes,
        "remote_updated_on": rec.remote_updated_on,
        "attempts": rec.attempts,
        "result": rec.result,
        "last_error": rec.last_error,
        "mode": settings.servicenow_mode,
        "writes_allowed": _writes_allowed(settings),
        "requires": {"confirm": True, "confirm_instance_host": rec.instance_host},
        "created_at": rec.created_at,
        "completed_at": rec.completed_at,
    }


def preview_sync(db: Session, actor: User, incident_id: uuid.UUID) -> dict[str, Any]:
    """Read the remote record and show exactly what an approved sync would change. No write."""
    s = get_settings()
    incident, assignment, team = _sync_incident(db, incident_id)
    client = get_client(s)
    remote = mapping.to_local(client.get_incident(incident.external_sys_id))
    target = team.servicenow_group_sys_id
    key = _idem_key(client.host, incident.external_sys_id, assignment.id, target)
    changes = {
        "assignment_group": {"from": remote["assignment_group_sys_id"], "to": target},
    }
    rec = db.scalar(select(SyncRecord).where(SyncRecord.idempotency_key == key))
    if rec is None:
        rec = SyncRecord(
            incident_id=incident.id,
            assignment_id=assignment.id,
            system=SYSTEM,
            instance_host=client.host,
            external_sys_id=incident.external_sys_id,
            external_number=incident.external_number,
            target_group_sys_id=target,
            field_changes=changes,
            remote_updated_on=remote["updated_on"],
            idempotency_key=key,
            status=SyncStatus.PREVIEWED,
            requested_by=actor.id,
        )
        db.add(rec)
    elif rec.status in (SyncStatus.PREVIEWED, SyncStatus.FAILED):
        # Re-preview refreshes the baseline, which is how a stale/failed sync is re-armed.
        rec.field_changes = changes
        rec.remote_updated_on = remote["updated_on"]
        rec.status = SyncStatus.PREVIEWED
        rec.last_error = None
    audit.record(
        db,
        event_type="SERVICENOW_SYNC_PREVIEWED",
        actor_id=actor.id,
        incident_id=incident.id,
        details={"instance_host": client.host, "sys_id": rec.external_sys_id, "fields": changes},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        rec = db.scalar(select(SyncRecord).where(SyncRecord.idempotency_key == key))
        if rec is None:
            raise
    return _present(rec, team, s)


def _finish(
    db: Session,
    rec: SyncRecord,
    actor: User,
    status: SyncStatus,
    event: str,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    rec.status = status
    rec.result = result
    rec.last_error = error[:500] if error else None
    if status == SyncStatus.SUCCEEDED:
        rec.completed_at = datetime.now(UTC)
    audit.record(
        db,
        event_type=event,
        actor_id=actor.id,
        incident_id=rec.incident_id,
        details={
            "sync_id": str(rec.id),
            "instance_host": rec.instance_host,
            "sys_id": rec.external_sys_id,
            "fields": rec.field_changes,
            "error": rec.last_error,
            "result": result,
        },
    )
    db.commit()


def approve_sync(
    db: Session,
    actor: User,
    incident_id: uuid.UUID,
    *,
    sync_id: uuid.UUID,
    confirm: bool,
    confirm_instance_host: str,
) -> dict[str, Any]:
    s = get_settings()
    client = get_client(s)
    if not _writes_allowed(s):
        raise WriteDisabledError(
            f"ServiceNow writes are disabled in '{s.servicenow_mode}' mode; set SERVICENOW_MODE=live"
        )
    rec = db.get(SyncRecord, sync_id)
    if rec is None or rec.incident_id != incident_id:
        raise NotFoundError("Sync preview not found for this incident")
    team = db.scalar(select(Team).where(Team.servicenow_group_sys_id == rec.target_group_sys_id))
    if not confirm:
        raise ValidationFailure("Explicit confirmation (confirm=true) is required")
    if (
        confirm_instance_host.strip().lower() != client.host.lower()
        or rec.instance_host != client.host
    ):
        raise ValidationFailure(
            "confirm_instance_host does not match the target instance",
            {"target_instance_host": client.host},
        )
    if rec.status == SyncStatus.SUCCEEDED:
        return _present(rec, team, s)  # replay: no second write
    assignment = db.get(Assignment, rec.assignment_id)
    if assignment is None or not assignment.is_current:
        raise ConflictError("The assignment changed after this preview; create a new preview")

    now = datetime.now(UTC)
    claimed = db.execute(
        update(SyncRecord)
        .where(
            SyncRecord.id == rec.id,
            (SyncRecord.status.in_((SyncStatus.PREVIEWED, SyncStatus.FAILED)))
            | (
                (SyncRecord.status == SyncStatus.IN_PROGRESS)
                & (SyncRecord.updated_at < now - STALE_CLAIM)
            ),
        )
        .values(
            status=SyncStatus.IN_PROGRESS,
            attempts=SyncRecord.attempts + 1,
            approved_by=actor.id,
            approved_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if claimed.rowcount != 1:
        db.refresh(rec)
        raise ConflictError(
            "This synchronization is already in progress", {"status": rec.status.value}
        )
    db.refresh(rec)

    target = rec.target_group_sys_id
    try:
        remote = mapping.to_local(client.get_incident(rec.external_sys_id))
        if remote["assignment_group_sys_id"] == target:
            _finish(
                db,
                rec,
                actor,
                SyncStatus.SUCCEEDED,
                "SERVICENOW_SYNC_ALREADY_APPLIED",
                result={"already_applied": True, "remote_updated_on": remote["updated_on"]},
            )
            return _present(rec, team, s)
        if remote["updated_on"] != rec.remote_updated_on:
            rec.status = SyncStatus.PREVIEWED  # nothing was written; require a fresh preview
            rec.last_error = "remote_record_changed_since_preview"
            db.commit()
            raise ConflictError(
                "The ServiceNow record changed since the preview; create a new preview",
                {
                    "code": "REMOTE_CHANGED",
                    "previewed": rec.remote_updated_on,
                    "now": remote["updated_on"],
                },
            )
        updated = mapping.to_local(client.update_assignment_group(rec.external_sys_id, target))
        if updated["assignment_group_sys_id"] != target:
            raise UpstreamError(
                "ServiceNow did not apply the assignment group (verification failed)",
                code="UPSTREAM_VERIFY_FAILED",
            )
        _finish(
            db,
            rec,
            actor,
            SyncStatus.SUCCEEDED,
            "SERVICENOW_SYNC_SUCCEEDED",
            result={"already_applied": False, "remote_updated_on": updated["updated_on"]},
        )
    except UpstreamError as exc:
        _finish(
            db,
            rec,
            actor,
            SyncStatus.FAILED,
            "SERVICENOW_SYNC_FAILED",
            error=f"{exc.code}: {exc.message}",
        )
        raise
    return _present(rec, team, s)


def list_syncs(db: Session, incident_id: uuid.UUID) -> list[dict[str, Any]]:
    if db.get(Incident, incident_id) is None:
        raise NotFoundError("Incident not found")
    s = get_settings()
    rows = db.scalars(
        select(SyncRecord)
        .where(SyncRecord.incident_id == incident_id)
        .order_by(SyncRecord.created_at)
    ).all()
    teams = {t.servicenow_group_sys_id: t for t in db.scalars(select(Team)).all()}
    return [_present(r, teams.get(r.target_group_sys_id), s) for r in rows]
