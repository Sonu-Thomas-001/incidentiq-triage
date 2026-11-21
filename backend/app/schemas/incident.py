import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AssignmentStatus,
    IncidentStatus,
    PredictionStatus,
    Priority,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class IncidentCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=10000)

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class _Versioned(BaseModel):
    expected_version: int = Field(
        ge=1,
        description="Incident version the client last saw (optimistic concurrency).",
    )


class TriageRequest(_Versioned):
    impact: int | None = Field(
        default=None,
        ge=1,
        le=3,
        description="1 = High ... 3 = Low. Needed for the priority policy.",
    )
    urgency: int | None = Field(default=None, ge=1, le=3, description="1 = High ... 3 = Low.")


class AcceptRequest(_Versioned):
    pass


class AssignRequest(_Versioned):
    team_id: uuid.UUID
    priority: Priority | None = None
    category: str | None = Field(default=None, min_length=2, max_length=64)
    reason: str | None = Field(default=None, max_length=1000)
    prediction_id: uuid.UUID | None = None


class OverrideRequest(_Versioned):
    team_id: uuid.UUID
    priority: Priority | None = None
    category: str | None = Field(default=None, min_length=2, max_length=64)
    reason: str = Field(min_length=5, max_length=1000)


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    reporter_id: uuid.UUID
    status: IncidentStatus
    approved_priority: Priority | None
    approved_category: str | None
    is_synthetic: bool
    external_system: str | None = None
    external_number: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: uuid.UUID
    assigned_by: uuid.UUID
    status: AssignmentStatus
    is_override: bool
    reason: str | None
    accepted_by: uuid.UUID | None
    accepted_at: datetime | None
    created_at: datetime


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: PredictionStatus
    predicted_category: str | None
    predicted_priority: Priority | None
    predicted_team_id: uuid.UUID | None
    confidence: float | None
    explanation: dict[str, Any] | None
    created_at: datetime


class IncidentDetail(IncidentOut):
    current_assignment: AssignmentOut | None = None
    latest_prediction: PredictionOut | None = None


class TriageResult(BaseModel):
    status: PredictionStatus
    is_demo: bool
    message: str
    prediction_id: uuid.UUID
    confidence: float | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    decision_evidence: list[str] = Field(default_factory=list)
    model_versions: dict[str, str] = Field(default_factory=dict)
    incident: IncidentDetail


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    event_type: str
    from_status: str | None
    to_status: str | None
    details: dict[str, Any] | None
    created_at: datetime


class AnalyticsOverview(BaseModel):
    total_incidents: int
    synthetic_incidents: int
    by_status: dict[str, int]
    by_approved_priority: dict[str, int]
    by_assigned_team: dict[str, int]
    unassigned: int
    model_status: str
    note: str
    by_approved_category: dict[str, int] = Field(default_factory=dict)
    incidents_per_day: dict[str, int] = Field(default_factory=dict)
    assignments_total: int = 0
    overrides_total: int = 0
    override_rate: float | None = Field(default=None, description="null when no assignments exist")
    predictions_total: int = 0
    confidence_histogram: list[dict[str, Any]] = Field(
        default_factory=list, description="Recorded prediction confidences only; empty if none."
    )


class ModelMetricsOut(BaseModel):
    status: str
    message: str
    models: list[dict[str, Any]]
