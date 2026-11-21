import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Priority, WorkflowKind, WorkflowRunStatus
from app.schemas.incident import IncidentDetail, TriageRequest, _Versioned


class WorkflowRunRequest(TriageRequest):
    use_gemini: bool = Field(
        default=False,
        description="Opt in to optional Gemini summary/extraction (needs GEMINI_ENABLED and a key).",
    )
    external_data_consent: bool = Field(
        default=False,
        description="Authorises sending the redacted text of a NON-synthetic incident to Gemini.",
    )


class WorkflowApproveRequest(_Versioned):
    team_id: uuid.UUID
    priority: Priority | None = None
    category: str | None = Field(default=None, min_length=2, max_length=64)
    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Required when the decision deviates from (or lacks) the recommendation.",
    )
    run_id: uuid.UUID | None = Field(default=None, description="Defaults to the latest triage run.")


class WorkflowRunOut(BaseModel):
    run_id: uuid.UUID
    kind: WorkflowKind
    status: WorkflowRunStatus
    reused: bool = Field(description="True when an identical earlier request was replayed.")
    outcome: str | None
    prediction_id: uuid.UUID | None
    input_issues: list[str]
    priority_inputs: dict[str, Any]
    ml: dict[str, Any] | None
    explanation: dict[str, Any] | None
    assist: dict[str, Any] | None
    routing: dict[str, Any] | None
    review: dict[str, Any] | None
    approved: dict[str, Any] | None
    trace: list[dict[str, Any]]
    created_at: datetime
    incident: IncidentDetail | None = None
