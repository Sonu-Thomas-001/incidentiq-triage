import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.models.enums import IncidentStatus


def record(
    db: Session,
    *,
    event_type: str,
    actor_id: uuid.UUID | None,
    incident_id: uuid.UUID | None = None,
    from_status: IncidentStatus | None = None,
    to_status: IncidentStatus | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        actor_id=actor_id,
        incident_id=incident_id,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value if to_status else None,
        details=details,
    )
    db.add(event)
    return event
