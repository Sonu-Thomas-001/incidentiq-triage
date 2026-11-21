import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ANALYST_OR_ADMIN, STAFF, DbSession, require_roles
from app.api.v1.incidents import _detail
from app.models import User
from app.schemas.workflow import WorkflowApproveRequest, WorkflowRunOut, WorkflowRunRequest
from app.services import incidents as svc
from app.workflow import service

router = APIRouter(prefix="/workflow", tags=["workflow"])
Analyst = Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))]


def _out(db: Session, actor: User, incident_id: uuid.UUID, data: dict[str, Any]) -> WorkflowRunOut:
    out = WorkflowRunOut.model_validate(data)
    out.incident = _detail(db, svc.get_incident(db, incident_id, actor), actor)
    return out


@router.post("/incidents/{incident_id}/run", response_model=WorkflowRunOut)
def run_workflow(
    incident_id: uuid.UUID, body: WorkflowRunRequest, db: DbSession, user: Analyst
) -> WorkflowRunOut:
    """Run the LangGraph triage workflow: validate -> ML -> priority policy -> explanation ->
    optional Gemini -> routing policy -> NEEDS_REVIEW. Recommendation only; nothing is assigned.

    Replaying an identical request returns the stored run (`reused: true`) without new side effects.
    """
    data = service.run_triage(
        db,
        user,
        incident_id,
        expected_version=body.expected_version,
        impact=body.impact,
        urgency=body.urgency,
        use_gemini=body.use_gemini,
        external_data_consent=body.external_data_consent,
    )
    return _out(db, user, incident_id, data)


@router.post("/incidents/{incident_id}/approve", response_model=WorkflowRunOut)
def approve_workflow(
    incident_id: uuid.UUID, body: WorkflowApproveRequest, db: DbSession, user: Analyst
) -> WorkflowRunOut:
    """Analyst approval of the final assignment after human review (NEEDS_REVIEW -> ASSIGNED).

    A `reason` is mandatory when the team/priority differs from the recommendation or none exists.
    This never writes to ServiceNow; use the explicit sync endpoints for that.
    """
    data = service.approve(
        db,
        user,
        incident_id,
        expected_version=body.expected_version,
        team_id=body.team_id,
        priority=body.priority.value if body.priority else None,
        category=body.category,
        reason=body.reason,
        run_id=body.run_id,
    )
    return _out(db, user, incident_id, data)


@router.get("/incidents/{incident_id}/runs", response_model=list[WorkflowRunOut])
def list_runs(
    incident_id: uuid.UUID, db: DbSession, user: Annotated[User, Depends(require_roles(*STAFF))]
):
    return service.list_runs(db, incident_id)


@router.get("/config")
def workflow_config(user: Analyst) -> dict[str, Any]:
    """Effective routing thresholds and Gemini flags (no secrets)."""
    return service.effective_config()
