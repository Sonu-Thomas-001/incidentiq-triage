import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import triggers
from app.db.base import Base, UTCDateTime, new_uuid, utcnow
from app.models.enums import (
    AssignmentStatus,
    IncidentStatus,
    LabelType,
    PredictionStatus,
    Priority,
    Role,
)


def _enum(e: type) -> Enum:
    return Enum(e, native_enum=False, length=32, validate_strings=True, create_constraint=True)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role), index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    team: Mapped[Team | None] = relationship()


class Incident(Base):
    """`title`/`description` are the original reporter text and are immutable."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[IncidentStatus] = mapped_column(
        _enum(IncidentStatus), index=True, default=IncidentStatus.NEW
    )
    # Approved (human-decided) values; model recommendations live in triage_predictions.
    approved_priority: Mapped[Priority | None] = mapped_column(_enum(Priority), index=True)
    approved_category: Mapped[str | None] = mapped_column(String(64), index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    reporter: Mapped[User] = relationship(foreign_keys=[reporter_id])

    __mapper_args__ = {"version_id_col": version}


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="REGISTERED")
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    artifact_path: Mapped[str | None] = mapped_column(String(500))
    trained_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TriagePrediction(Base):
    """A *recommendation*. Never an approved decision."""

    __tablename__ = "triage_predictions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"))
    status: Mapped[PredictionStatus] = mapped_column(_enum(PredictionStatus))
    predicted_category: Mapped[str | None] = mapped_column(String(64))
    predicted_priority: Mapped[Priority | None] = mapped_column(_enum(Priority))
    predicted_team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    confidence: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Assignment(Base):
    """An approved human decision to route an incident to a team."""

    __tablename__ = "assignments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("triage_predictions.id"))
    status: Mapped[AssignmentStatus] = mapped_column(
        _enum(AssignmentStatus), default=AssignmentStatus.ASSIGNED
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String(1000))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    keyword_pattern: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[Priority | None] = mapped_column(_enum(Priority))
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    """Append-only."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class FeedbackLabel(Base):
    """Human-confirmed labels, reserved as future training data."""

    __tablename__ = "feedback_labels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assignments.id"))
    label_type: Mapped[LabelType] = mapped_column(_enum(LabelType))
    value: Mapped[str] = mapped_column(String(100))
    labeled_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# One current assignment per incident (partial unique index).
Index(
    "uq_assignments_one_current",
    Assignment.incident_id,
    unique=True,
    sqlite_where=Assignment.is_current == true(),
)

for _stmt, _table in (
    (triggers.INCIDENT_TEXT_IMMUTABLE, Incident.__table__),
    (triggers.AUDIT_NO_UPDATE, AuditEvent.__table__),
    (triggers.AUDIT_NO_DELETE, AuditEvent.__table__),
):
    event.listen(_table, "after_create", DDL(_stmt).execute_if(dialect="sqlite"))


@event.listens_for(Incident, "before_update")
def _guard_incident_text(_mapper, _conn, target: Incident) -> None:
    state = inspect(target)
    for attr in ("title", "description", "reporter_id", "created_at"):
        if state.attrs[attr].history.has_changes():
            raise ValueError(f"incident.{attr} is immutable")


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def _guard_audit(*_args) -> None:
    raise ValueError("audit events are append-only")
