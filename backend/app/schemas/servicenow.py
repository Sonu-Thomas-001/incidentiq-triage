import uuid

from pydantic import BaseModel, Field


class ServiceNowImportRequest(BaseModel):
    sys_id: str = Field(min_length=32, max_length=32, description="ServiceNow incident sys_id")


class TeamMappingRequest(BaseModel):
    team_id: uuid.UUID
    servicenow_group_sys_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=32,
        description="sys_user_group sys_id; null clears the mapping",
    )


class SyncApproveRequest(BaseModel):
    preview_id: uuid.UUID
    confirm: bool = Field(description="Must be true: the analyst has reviewed the previewed change")
    confirm_instance_host: str = Field(
        min_length=3,
        max_length=255,
        description="Must equal the target_instance_host shown in the preview",
    )
