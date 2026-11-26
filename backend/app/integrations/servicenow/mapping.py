"""Explicit mapping between ServiceNow incident fields and the local schema."""

from __future__ import annotations

from typing import Any

# ServiceNow incident.state -> label. Only open states are importable as local NEW incidents.
SN_STATE_LABELS = {
    "1": "New",
    "2": "In Progress",
    "3": "On Hold",
    "6": "Resolved",
    "7": "Closed",
    "8": "Canceled",
}
IMPORTABLE_STATES = {"1", "2", "3"}
# ServiceNow priority 1..5 -> local label. Snapshot only: never an approved local priority.
SN_PRIORITY_TO_LOCAL = {"1": "P1", "2": "P2", "3": "P3", "4": "P4", "5": "P4"}
SN_SCALE = {"1", "2", "3"}  # impact/urgency, same scale as the local priority policy


def ref_value(raw: Any) -> str | None:
    """Reference fields arrive as '' / 'sys_id' / {'value': 'sys_id', 'link': ...}."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    raw = (str(raw).strip() if raw is not None else "") or None
    return raw


def _scale(raw: Any) -> int | None:
    v = str(raw).strip() if raw is not None else ""
    return int(v) if v in SN_SCALE else None


def to_local(record: dict[str, Any]) -> dict[str, Any]:
    state = str(record.get("state") or "").strip()
    sn_priority = str(record.get("priority") or "").strip()
    return {
        "sys_id": str(record.get("sys_id") or "").lower(),
        "number": record.get("number") or None,
        "title": (record.get("short_description") or "").strip(),
        "description": (record.get("description") or "").strip(),
        "state": state,
        "state_label": SN_STATE_LABELS.get(state, "Unknown"),
        "importable": state in IMPORTABLE_STATES,
        "snapshot_priority": SN_PRIORITY_TO_LOCAL.get(sn_priority),
        "impact": _scale(record.get("impact")),
        "urgency": _scale(record.get("urgency")),
        "category": record.get("category") or None,
        "assignment_group_sys_id": ref_value(record.get("assignment_group")),
        # Tickets created by `servicenow-seed` carry correlation_id=incidentiq-seed-NNNN.
        "origin": (
            "seed_script"
            if str(record.get("correlation_id") or "").startswith("incidentiq-seed-")
            else "native"
        ),
        "created_on": record.get("sys_created_on") or None,
        "updated_on": record.get("sys_updated_on") or None,
    }


def snapshot(mapped: dict[str, Any]) -> dict[str, Any]:
    """What is stored on the local incident; a record of the source, not a decision."""
    keep = (
        "number",
        "state",
        "state_label",
        "snapshot_priority",
        "impact",
        "urgency",
        "category",
        "assignment_group_sys_id",
        "created_on",
        "updated_on",
    )
    return {k: mapped[k] for k in keep}
