from app.core.errors import InvalidTransitionError
from app.models.enums import IncidentStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.NEW: frozenset({S.TRIAGE_PENDING, S.ASSIGNED}),
    S.TRIAGE_PENDING: frozenset({S.NEEDS_REVIEW, S.ASSIGNED}),
    S.NEEDS_REVIEW: frozenset({S.ASSIGNED}),
    S.ASSIGNED: frozenset({S.ACCEPTED, S.REASSIGNED}),
    S.ACCEPTED: frozenset({S.REASSIGNED}),
    S.REASSIGNED: frozenset({S.ACCEPTED, S.REASSIGNED}),
}


def ensure_transition(current: S, target: S) -> None:
    if target not in TRANSITIONS[current]:
        allowed = sorted(s.value for s in TRANSITIONS[current])
        raise InvalidTransitionError(
            f"Cannot move incident from {current.value} to {target.value}",
            {"from": current.value, "to": target.value, "allowed": allowed},
        )
