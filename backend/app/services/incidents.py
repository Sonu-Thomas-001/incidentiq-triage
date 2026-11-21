import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
    StaleVersionError,
    ValidationFailure,
)
from app.db.base import utcnow
from app.models import (
    Assignment,
    AuditEvent,
    FeedbackLabel,
    Incident,
    ModelVersion,
    Team,
    TriagePrediction,
    User,
)
from app.models.enums import (
    AssignmentStatus,
    IncidentStatus,
    LabelType,
    PredictionStatus,
    Priority,
    Role,
)
from app.services import audit, ml_service
from app.services.lifecycle import ensure_transition

STAFF_ROLES = {Role.TRIAGE_ANALYST, Role.SUPPORT_ENGINEER, Role.ADMIN}
OPEN_QUEUE_STATUSES = (
    IncidentStatus.ASSIGNED,
    IncidentStatus.REASSIGNED,
    IncidentStatus.ACCEPTED,
)

NOT_READY_MESSAGE = (
    "No trained model is available. No category or team prediction was generated; "
    "the incident needs human review."
)
DEMO_MESSAGE = (
    "DEMO: at least one output comes from a model trained on SYNTHETIC data and says nothing "
    "about real-world accuracy. Recommendations only; a human must approve."
)
MODEL_MESSAGE = "Recommendations from trained models; a human must approve any assignment."


@dataclass
class IncidentFilters:
    status: IncidentStatus | None = None
    priority: Priority | None = None
    team_id: uuid.UUID | None = None
    reporter_id: uuid.UUID | None = None
    q: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


def _get_incident(db: Session, incident_id: uuid.UUID, actor: User | None = None) -> Incident:
    incident = db.get(Incident, incident_id)
    # Reporters can only see their own incidents; hide existence of others.
    if incident is None or (
        actor is not None and actor.role == Role.REPORTER and incident.reporter_id != actor.id
    ):
        raise NotFoundError("Incident not found")
    return incident


def get_incident(db: Session, incident_id: uuid.UUID, actor: User) -> Incident:
    return _get_incident(db, incident_id, actor)


def _check_version(incident: Incident, expected: int) -> None:
    if incident.version != expected:
        raise StaleVersionError(
            "Incident was modified by someone else; reload and retry",
            {"expected_version": expected, "current_version": incident.version},
        )


def current_assignment(db: Session, incident_id: uuid.UUID) -> Assignment | None:
    return db.scalar(
        select(Assignment).where(Assignment.incident_id == incident_id, Assignment.is_current)
    )


def latest_prediction(db: Session, incident_id: uuid.UUID) -> TriagePrediction | None:
    return db.scalar(
        select(TriagePrediction)
        .where(TriagePrediction.incident_id == incident_id)
        .order_by(TriagePrediction.created_at.desc(), TriagePrediction.id)
        .limit(1)
    )


def _require_team(db: Session, team_id: uuid.UUID) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise ValidationFailure("Unknown team_id", {"team_id": str(team_id)})
    return team


def create_incident(db: Session, actor: User, title: str, description: str) -> Incident:
    incident = Incident(title=title, description=description, reporter_id=actor.id)
    db.add(incident)
    db.flush()
    audit.record(
        db,
        event_type="INCIDENT_CREATED",
        actor_id=actor.id,
        incident_id=incident.id,
        to_status=IncidentStatus.NEW,
    )
    db.commit()
    return incident


def _apply_filters(stmt: Select, f: IncidentFilters, actor: User) -> Select:
    if actor.role == Role.REPORTER:
        stmt = stmt.where(Incident.reporter_id == actor.id)
    elif f.reporter_id:
        stmt = stmt.where(Incident.reporter_id == f.reporter_id)
    if f.status:
        stmt = stmt.where(Incident.status == f.status)
    if f.priority:
        stmt = stmt.where(Incident.approved_priority == f.priority)
    if f.team_id:
        stmt = stmt.where(
            Incident.id.in_(
                select(Assignment.incident_id).where(
                    Assignment.team_id == f.team_id, Assignment.is_current
                )
            )
        )
    if f.q:
        escaped = f.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Incident.title.ilike(f"%{escaped}%", escape="\\"))
    if f.created_from:
        stmt = stmt.where(Incident.created_at >= f.created_from)
    if f.created_to:
        stmt = stmt.where(Incident.created_at <= f.created_to)
    return stmt


def _paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[list[Incident], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Incident.created_at.desc(), Incident.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def list_incidents(
    db: Session, actor: User, f: IncidentFilters, page: int, page_size: int
) -> tuple[list[Incident], int]:
    return _paginate(db, _apply_filters(select(Incident), f, actor), page, page_size)


def team_queue(
    db: Session,
    actor: User,
    team_id: uuid.UUID,
    status: IncidentStatus | None,
    page: int,
    page_size: int,
) -> tuple[list[Incident], int]:
    if db.get(Team, team_id) is None:
        raise NotFoundError("Team not found")
    if actor.role == Role.SUPPORT_ENGINEER and actor.team_id != team_id:
        raise PermissionDeniedError("Support engineers can only view their own team's queue")
    statuses = (status,) if status else OPEN_QUEUE_STATUSES
    if status and status not in OPEN_QUEUE_STATUSES:
        raise ValidationFailure(
            "Queue only contains assigned incidents",
            {"allowed": [s.value for s in OPEN_QUEUE_STATUSES]},
        )
    stmt = (
        select(Incident)
        .join(Assignment, Assignment.incident_id == Incident.id)
        .where(
            Assignment.team_id == team_id,
            Assignment.is_current,
            Incident.status.in_(statuses),
        )
    )
    return _paginate(db, stmt, page, page_size)


def sync_model_versions(db: Session) -> dict[str, ModelVersion]:
    """Mirror artifact manifest entries into model_versions (idempotent); metrics are as measured."""
    out: dict[str, ModelVersion] = {}
    for e in ml_service.manifest_entries():
        mv = db.scalar(
            select(ModelVersion).where(
                ModelVersion.name == e["key"],
                ModelVersion.version == e["model_version"],
            )
        )
        if mv is None:
            mv = ModelVersion(
                name=e["key"],
                version=e["model_version"],
                status="DEMO" if e.get("is_demo") else "ACTIVE",
                metrics={
                    "provenance": e["provenance"],
                    "is_demo": bool(e.get("is_demo")),
                    "test_metrics": e.get("metrics"),
                    "split": e.get("split"),
                    "dataset_fingerprint": e.get("dataset_fingerprint"),
                    "training_config": e.get("training_config"),
                    "library_versions": e.get("library_versions"),
                    "class_mapping": e.get("class_mapping"),
                    "sha256": e.get("sha256"),
                },
                artifact_path=e.get("file"),
                trained_at=(
                    datetime.fromisoformat(e["trained_at"]) if e.get("trained_at") else None
                ),
            )
            db.add(mv)
            db.flush()
        out[e["key"]] = mv
    return out


def request_triage(
    db: Session,
    actor: User,
    incident_id: uuid.UUID,
    expected_version: int,
    impact: int | None = None,
    urgency: int | None = None,
) -> tuple[Incident, TriagePrediction, dict]:
    """Run the trained models (or record NOT_READY) and route the incident to human review.

    The result is a recommendation only; no assignment or approved value is changed here.
    """
    incident = _get_incident(db, incident_id)
    _check_version(incident, expected_version)
    original = incident.status
    ensure_transition(original, IncidentStatus.TRIAGE_PENDING)
    audit.record(
        db,
        event_type="TRIAGE_REQUESTED",
        actor_id=actor.id,
        incident_id=incident.id,
        from_status=original,
        to_status=IncidentStatus.TRIAGE_PENDING,
    )
    ensure_transition(IncidentStatus.TRIAGE_PENDING, IncidentStatus.NEEDS_REVIEW)
    result = ml_service.predict(incident.title, incident.description, impact, urgency)
    status = PredictionStatus(result["status"])
    versions = sync_model_versions(db)
    outs = result["outputs"]
    category = outs["category"].get("label") if outs["category"].get("available") else None
    team_id = None
    if outs["team"].get("available"):
        team_id = db.scalar(select(Team.id).where(Team.name == outs["team"]["label"]))
    priority = Priority(outs["priority"]["label"]) if outs["priority"].get("available") else None
    primary = (
        ml_service.CATEGORY_KEY
        if outs["category"].get("available")
        else ml_service.TEAM_KEY if outs["team"].get("available") else None
    )
    prediction = TriagePrediction(
        incident_id=incident.id,
        status=status,
        predicted_category=category,
        predicted_priority=priority,
        predicted_team_id=team_id,
        confidence=result["confidence"],
        explanation={
            "outputs": outs,
            "decision_evidence": result["decision_evidence"],
            "model_versions": result["model_versions"],
            "disclaimer": result["disclaimer"],
            **({} if status != PredictionStatus.NOT_READY else {"reason": "no_trained_model"}),
        },
        model_version_id=versions[primary].id if primary in versions else None,
        requested_by=actor.id,
    )
    db.add(prediction)
    incident.status = IncidentStatus.NEEDS_REVIEW
    db.flush()
    audit.record(
        db,
        event_type=(
            "TRIAGE_NOT_READY" if status == PredictionStatus.NOT_READY else "TRIAGE_RECOMMENDED"
        ),
        actor_id=actor.id,
        incident_id=incident.id,
        from_status=IncidentStatus.TRIAGE_PENDING,
        to_status=IncidentStatus.NEEDS_REVIEW,
        details={
            "prediction_id": str(prediction.id),
            "prediction_status": status.value,
            "model_versions": result["model_versions"],
        },
    )
    db.commit()
    return incident, prediction, result


def _record_labels(
    db: Session,
    actor: User,
    incident: Incident,
    assignment: Assignment,
    priority: Priority | None,
    category: str | None,
) -> None:
    labels = [(LabelType.TEAM, str(assignment.team_id))]
    if priority:
        labels.append((LabelType.PRIORITY, priority.value))
    if category:
        labels.append((LabelType.CATEGORY, category))
    for label_type, value in labels:
        db.add(
            FeedbackLabel(
                incident_id=incident.id,
                assignment_id=assignment.id,
                label_type=label_type,
                value=value,
                labeled_by=actor.id,
            )
        )


def _new_assignment(
    db: Session,
    actor: User,
    incident: Incident,
    team_id: uuid.UUID,
    reason: str | None,
    is_override: bool,
    prediction_id: uuid.UUID | None = None,
) -> Assignment:
    assignment = Assignment(
        incident_id=incident.id,
        team_id=team_id,
        assigned_by=actor.id,
        prediction_id=prediction_id,
        status=AssignmentStatus.ASSIGNED,
        is_current=True,
        is_override=is_override,
        reason=reason,
    )
    db.add(assignment)
    db.flush()
    return assignment


def assign_incident(
    db: Session,
    actor: User,
    incident_id: uuid.UUID,
    *,
    expected_version: int,
    team_id: uuid.UUID,
    priority: Priority | None,
    category: str | None,
    reason: str | None,
    prediction_id: uuid.UUID | None,
) -> Incident:
    incident = _get_incident(db, incident_id)
    _check_version(incident, expected_version)
    original = incident.status
    if original in (
        IncidentStatus.ASSIGNED,
        IncidentStatus.ACCEPTED,
        IncidentStatus.REASSIGNED,
    ):
        raise InvalidTransitionError(
            "Incident is already assigned; use the override endpoint to reassign",
            {"from": original.value, "to": IncidentStatus.ASSIGNED.value},
        )
    ensure_transition(original, IncidentStatus.ASSIGNED)
    _require_team(db, team_id)
    if prediction_id is not None:
        prediction = db.get(TriagePrediction, prediction_id)
        if prediction is None or prediction.incident_id != incident.id:
            raise ValidationFailure("prediction_id does not belong to this incident")

    assignment = _new_assignment(db, actor, incident, team_id, reason, False, prediction_id)
    incident.status = IncidentStatus.ASSIGNED
    if priority:
        incident.approved_priority = priority
    if category:
        incident.approved_category = category
    _record_labels(db, actor, incident, assignment, priority, category)
    audit.record(
        db,
        event_type="INCIDENT_ASSIGNED",
        actor_id=actor.id,
        incident_id=incident.id,
        from_status=original,
        to_status=IncidentStatus.ASSIGNED,
        details={
            "assignment_id": str(assignment.id),
            "team_id": str(team_id),
            "priority": priority.value if priority else None,
            "category": category,
            "reason": reason,
        },
    )
    db.commit()
    return incident


def override_assignment(
    db: Session,
    actor: User,
    incident_id: uuid.UUID,
    *,
    expected_version: int,
    team_id: uuid.UUID,
    priority: Priority | None,
    category: str | None,
    reason: str,
) -> Incident:
    incident = _get_incident(db, incident_id)
    _check_version(incident, expected_version)
    original = incident.status
    ensure_transition(original, IncidentStatus.REASSIGNED)
    _require_team(db, team_id)
    previous = current_assignment(db, incident.id)
    if previous is None:
        raise InvalidTransitionError("Incident has no current assignment to override")
    if previous.team_id == team_id:
        raise ValidationFailure("Override must target a different team", {"team_id": str(team_id)})

    previous.is_current = False
    previous.status = AssignmentStatus.SUPERSEDED
    db.flush()  # free the one-current-per-incident unique index before inserting
    assignment = _new_assignment(db, actor, incident, team_id, reason, True)
    incident.status = IncidentStatus.REASSIGNED
    if priority:
        incident.approved_priority = priority
    if category:
        incident.approved_category = category
    _record_labels(db, actor, incident, assignment, priority, category)
    audit.record(
        db,
        event_type="ASSIGNMENT_OVERRIDDEN",
        actor_id=actor.id,
        incident_id=incident.id,
        from_status=original,
        to_status=IncidentStatus.REASSIGNED,
        details={
            "assignment_id": str(assignment.id),
            "previous_team_id": str(previous.team_id),
            "team_id": str(team_id),
            "priority": priority.value if priority else None,
            "category": category,
            "reason": reason,
        },
    )
    db.commit()
    return incident


def accept_incident(
    db: Session, actor: User, incident_id: uuid.UUID, expected_version: int
) -> Incident:
    incident = _get_incident(db, incident_id)
    _check_version(incident, expected_version)
    original = incident.status
    ensure_transition(original, IncidentStatus.ACCEPTED)
    assignment = current_assignment(db, incident.id)
    if assignment is None:
        raise InvalidTransitionError("Incident has no current assignment")
    if actor.role != Role.ADMIN and actor.team_id != assignment.team_id:
        raise PermissionDeniedError("Only a member of the assigned team can accept this incident")

    assignment.status = AssignmentStatus.ACCEPTED
    assignment.accepted_by = actor.id
    assignment.accepted_at = utcnow()
    incident.status = IncidentStatus.ACCEPTED
    audit.record(
        db,
        event_type="INCIDENT_ACCEPTED",
        actor_id=actor.id,
        incident_id=incident.id,
        from_status=original,
        to_status=IncidentStatus.ACCEPTED,
        details={
            "assignment_id": str(assignment.id),
            "team_id": str(assignment.team_id),
        },
    )
    db.commit()
    return incident


def list_audit(db: Session, incident_id: uuid.UUID, page: int, page_size: int):
    if db.get(Incident, incident_id) is None:
        raise NotFoundError("Incident not found")
    stmt = select(AuditEvent).where(AuditEvent.incident_id == incident_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditEvent.created_at, AuditEvent.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def analytics_overview(db: Session) -> dict:
    statuses = Counter({s.value: 0 for s in IncidentStatus})
    for status, count in db.execute(
        select(Incident.status, func.count()).group_by(Incident.status)
    ):
        statuses[status.value] = count
    priorities = {
        p.value if p else "UNSET": c
        for p, c in db.execute(
            select(Incident.approved_priority, func.count()).group_by(Incident.approved_priority)
        )
    }
    teams = {
        name: c
        for name, c in db.execute(
            select(Team.name, func.count())
            .join(Assignment, Assignment.team_id == Team.id)
            .where(Assignment.is_current)
            .group_by(Team.name)
        )
    }
    total = sum(statuses.values())
    synthetic = db.scalar(select(func.count()).where(Incident.is_synthetic)) or 0
    has_model = db.scalar(select(func.count()).select_from(ModelVersion)) or 0
    return {
        "total_incidents": total,
        "synthetic_incidents": synthetic,
        "by_status": dict(statuses),
        "by_approved_priority": priorities,
        "by_assigned_team": teams,
        "unassigned": sum(
            statuses[s.value]
            for s in (
                IncidentStatus.NEW,
                IncidentStatus.TRIAGE_PENDING,
                IncidentStatus.NEEDS_REVIEW,
            )
        ),
        "model_status": ("AVAILABLE" if (has_model or ml_service.available()) else "NOT_READY"),
        "note": "Counts are of recorded human decisions only; no model predictions are included.",
    }


def model_metrics(db: Session) -> dict:
    sync_model_versions(db)
    db.commit()
    models = db.scalars(select(ModelVersion).order_by(ModelVersion.created_at)).all()
    if not models:
        return {
            "status": "NOT_READY",
            "message": "No trained model has been registered. No metrics are available.",
            "models": [],
        }
    return {
        "status": "AVAILABLE",
        "message": "Metrics were measured offline on a held-out test split at training time; "
        "models with is_demo=true were trained on SYNTHETIC data.",
        "models": [
            {
                "id": str(m.id),
                "name": m.name,
                "version": m.version,
                "status": m.status,
                "metrics": m.metrics,
                "trained_at": m.trained_at.isoformat() if m.trained_at else None,
            }
            for m in models
        ],
    }
