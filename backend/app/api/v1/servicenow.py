import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import ANALYST_OR_ADMIN, STAFF, DbSession, Paging, require_roles
from app.integrations.servicenow import service
from app.models import User
from app.models.enums import Role
from app.schemas.servicenow import (
    ServiceNowImportRequest,
    SyncApproveRequest,
    TeamMappingRequest,
)

router = APIRouter(prefix="/integrations/servicenow", tags=["servicenow"])
Analyst = Annotated[User, Depends(require_roles(*ANALYST_OR_ADMIN))]
Admin = Annotated[User, Depends(require_roles(Role.ADMIN))]
Staff = Annotated[User, Depends(require_roles(*STAFF))]


@router.get("/health")
def health(user: Analyst) -> dict[str, Any]:
    """Configuration and reachability. Reports `enabled:false` offline; never exposes secrets."""
    return service.health()


@router.get("/incidents")
def list_incidents(
    user: Analyst,
    paging: Paging,
    state: Annotated[
        str | None, Query(pattern=r"^[0-9]{1,2}$", description="ServiceNow state code")
    ] = None,
    q: Annotated[
        str | None, Query(max_length=100, description="short_description contains")
    ] = None,
    assignment_group: Annotated[str | None, Query(min_length=32, max_length=32)] = None,
) -> dict[str, Any]:
    """Read-only, paginated view of remote incidents mapped to local fields."""
    return service.list_remote_incidents(
        paging.page, paging.page_size, state=state, query=q, group=assignment_group
    )


@router.get("/incidents/{sys_id}")
def get_incident(sys_id: str, user: Analyst) -> dict[str, Any]:
    return service.get_remote_incident(sys_id)


@router.get("/assignment-groups")
def assignment_groups(user: Analyst, paging: Paging) -> dict[str, Any]:
    return service.list_remote_groups(paging.page, paging.page_size)


@router.post("/assignment-groups/import")
def import_groups(db: DbSession, user: Admin) -> dict[str, Any]:
    """ADMIN: create a local team (mapped by sys_id) for each active ServiceNow assignment group."""
    return service.import_groups_as_teams(db, user)


@router.post("/import")
def import_incident(body: ServiceNowImportRequest, db: DbSession, user: Analyst) -> dict[str, Any]:
    """Import one open ServiceNow incident as a local NEW incident (read-only toward ServiceNow).

    Idempotent per sys_id. Imported records are not a validated training dataset.
    """
    return service.import_incident(db, user, body.sys_id)


@router.get("/team-mappings")
def team_mappings(db: DbSession, user: Analyst) -> list[dict[str, Any]]:
    return service.list_team_mappings(db)


@router.post("/team-mappings")
def set_team_mapping(body: TeamMappingRequest, db: DbSession, user: Admin) -> dict[str, Any]:
    """ADMIN: map a local team to a ServiceNow assignment group sys_id."""
    return service.set_team_mapping(db, user, body.team_id, body.servicenow_group_sys_id)


@router.post("/incidents/{incident_id}/sync/preview")
def sync_preview(incident_id: uuid.UUID, db: DbSession, user: Analyst) -> dict[str, Any]:
    """Show target instance, incident number/sys_id, intended group and exact fields. No write."""
    return service.preview_sync(db, user, incident_id)


@router.post("/incidents/{incident_id}/sync/approve")
def sync_approve(
    incident_id: uuid.UUID, body: SyncApproveRequest, db: DbSession, user: Analyst
) -> dict[str, Any]:
    """The only endpoint that writes to ServiceNow (PATCH assignment_group). Needs a preview,
    `confirm: true` and the exact instance host; blocked unless the mode allows writes."""
    return service.approve_sync(
        db,
        user,
        incident_id,
        sync_id=body.preview_id,
        confirm=body.confirm,
        confirm_instance_host=body.confirm_instance_host,
    )


@router.get("/incidents/{incident_id}/sync")
def sync_history(incident_id: uuid.UUID, db: DbSession, user: Staff) -> list[dict[str, Any]]:
    return service.list_syncs(db, incident_id)
