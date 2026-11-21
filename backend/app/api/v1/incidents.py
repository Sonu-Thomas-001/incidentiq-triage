import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    ANALYST_OR_ADMIN,
    STAFF,
    CurrentUser,
    DbSession,
    Paging,
    require_roles,
)
from app.models import Incident, User
from app.models.enums import IncidentStatus, Priority, Role
from app.schemas.incident import (
    AcceptRequest,
    AnalyticsOverview,
    AssignRequest,
    AuditEventOut,
    IncidentCreate,
    IncidentDetail,
    IncidentOut,
    ModelMetricsOut,
    OverrideRequest,
    Page,
    TriageRequest,
    TriageResult,
)
from app.services import incidents as svc

router = APIRouter()


def _detail(db: Session, incident: Incident, actor: User) -> IncidentDetail:
    detail = IncidentDetail.model_validate(incident)
    detail.current_assignment = svc.current_assignment(db, incident.id)  # type: ignore[assignment]
    if actor.role != Role.REPORTER:
        detail.latest_prediction = svc.latest_prediction(db, incident.id)  # type: ignore[assignment]
    return detail


@router.post("/incidents", response_model=IncidentDetail, status_code=201, tags=["incidents"])
def create_incident(body: IncidentCreate, db: DbSession, user: CurrentUser) -> IncidentDetail:
    """Any authenticated user may report an incident. Original text is stored immutably."""
    incident = svc.create_incident(db, user, body.title, body.description)
    return _detail(db, incident, user)


@router.get("/incidents", response_model=Page[IncidentOut], tags=["incidents"])
def list_incidents(
    db: DbSession,
    user: CurrentUser,
    paging: Paging,
    status: IncidentStatus | None = None,
    priority: Priority | None = None,
    team_id: uuid.UUID | None = None,
    reporter_id: uuid.UUID | None = None,
    q: Annotated[
        str | None, Query(min_length=1, max_length=100, description="Title contains")
    ] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Page[IncidentOut]:
    filters = svc.IncidentFilters(
        status, priority, team_id, reporter_id, q, created_from, created_to
    )
    items, total = svc.list_incidents(db, user, filters, paging.page, paging.page_size)
    return Page[IncidentOut](
        items=[IncidentOut.model_validate(i) for i in items],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail, tags=["incidents"])
def get_incident(incident_id: uuid.UUID, db: DbSession, user: CurrentUser) -> IncidentDetail:
    return _detail(db, svc.get_incident(db, incident_id, user), user)


@router.post("/incidents/{incident_id}/triage", response_model=TriageResult, tags=["workflow"])
def triage_incident(
    incident_id: uuid.UUID,
    body: TriageRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))],
) -> TriageResult:
    """Phase 1: always returns NOT_READY (no trained model); routes incident to NEEDS_REVIEW."""
    incident, prediction = svc.request_triage(db, user, incident_id, body.expected_version)
    return TriageResult(
        status=prediction.status,
        is_demo=False,
        message=svc.NOT_READY_MESSAGE,
        prediction_id=prediction.id,
        incident=_detail(db, incident, user),
    )


@router.post("/incidents/{incident_id}/assign", response_model=IncidentDetail, tags=["workflow"])
def assign_incident(
    incident_id: uuid.UUID,
    body: AssignRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))],
) -> IncidentDetail:
    incident = svc.assign_incident(
        db,
        user,
        incident_id,
        expected_version=body.expected_version,
        team_id=body.team_id,
        priority=body.priority,
        category=body.category,
        reason=body.reason,
        prediction_id=body.prediction_id,
    )
    return _detail(db, incident, user)


@router.post("/incidents/{incident_id}/accept", response_model=IncidentDetail, tags=["workflow"])
def accept_incident(
    incident_id: uuid.UUID,
    body: AcceptRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPPORT_ENGINEER, Role.ADMIN))],
) -> IncidentDetail:
    return _detail(db, svc.accept_incident(db, user, incident_id, body.expected_version), user)


@router.post("/incidents/{incident_id}/override", response_model=IncidentDetail, tags=["workflow"])
def override_incident(
    incident_id: uuid.UUID,
    body: OverrideRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))],
) -> IncidentDetail:
    incident = svc.override_assignment(
        db,
        user,
        incident_id,
        expected_version=body.expected_version,
        team_id=body.team_id,
        priority=body.priority,
        category=body.category,
        reason=body.reason,
    )
    return _detail(db, incident, user)


@router.get("/incidents/{incident_id}/audit", response_model=Page[AuditEventOut], tags=["audit"])
def incident_audit(
    incident_id: uuid.UUID,
    db: DbSession,
    paging: Paging,
    _: Annotated[User, Depends(require_roles(*STAFF))],
) -> Page[AuditEventOut]:
    events, total = svc.list_audit(db, incident_id, paging.page, paging.page_size)
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(e) for e in events],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/teams/{team_id}/queue", response_model=Page[IncidentOut], tags=["teams"])
def team_queue(
    team_id: uuid.UUID,
    db: DbSession,
    paging: Paging,
    user: Annotated[User, Depends(require_roles(*STAFF))],
    status: IncidentStatus | None = None,
) -> Page[IncidentOut]:
    items, total = svc.team_queue(db, user, team_id, status, paging.page, paging.page_size)
    return Page[IncidentOut](
        items=[IncidentOut.model_validate(i) for i in items],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
    )


@router.get("/analytics/overview", response_model=AnalyticsOverview, tags=["analytics"])
def analytics_overview(
    db: DbSession, _: Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))]
) -> dict:
    return svc.analytics_overview(db)


@router.get("/models/metrics", response_model=ModelMetricsOut, tags=["models"])
def models_metrics(
    db: DbSession, _: Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))]
) -> dict:
    return svc.model_metrics(db)
