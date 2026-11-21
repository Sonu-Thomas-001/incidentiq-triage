"""Priority policy for Task C.

On the UCI ServiceNow log priority is a deterministic function of (impact, urgency): all
141,712 events obey the 8 combinations below with zero exceptions. We therefore implement and
document the policy instead of claiming ML discovered it. The (impact=1, urgency=3) cell never
occurs in the data, so it is deliberately left undefined (returns None) rather than invented.
Keep this table in sync with backend/app/services/ml_service.py (a test enforces equality).
"""

from __future__ import annotations

PRIORITY_POLICY: dict[tuple[int, int], str] = {
    (1, 1): "1 - Critical",
    (1, 2): "2 - High",
    (2, 1): "2 - High",
    (2, 2): "3 - Moderate",
    (2, 3): "4 - Low",
    (3, 1): "3 - Moderate",
    (3, 2): "4 - Low",
    (3, 3): "4 - Low",
}


def priority_from_impact_urgency(impact: int, urgency: int) -> str | None:
    return PRIORITY_POLICY.get((int(impact), int(urgency)))
