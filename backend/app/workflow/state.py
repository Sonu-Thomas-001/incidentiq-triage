"""Typed state for the LangGraph triage/approval workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict


class TraceEntry(TypedDict):
    node: str
    status: Literal["ok", "skipped", "fallback", "error"]
    at: str
    ms: float
    detail: dict[str, Any]


class WorkflowState(TypedDict, total=False):
    # --- inputs
    action: Literal["triage", "approve"]
    incident_id: str
    actor_id: str
    expected_version: int
    impact: int | None
    urgency: int | None
    use_gemini: bool
    external_data_consent: bool
    approval: dict[str, Any]  # team_id, priority, category, reason, run_id (approve only)
    # --- derived (never contains the original incident text)
    idempotency_key: str
    reused: bool
    run_id: str
    input_issues: list[str]
    priority_inputs: dict[str, Any]
    ml: dict[str, Any]
    priority: dict[str, Any]
    explanation: dict[str, Any]
    assist: dict[str, Any]
    routing: dict[str, Any]
    prediction_id: str
    review: dict[str, Any]
    approved: dict[str, Any]
    outcome: str
    # appended by every node; the reducer concatenates partial updates
    trace: Annotated[list[TraceEntry], operator.add]
