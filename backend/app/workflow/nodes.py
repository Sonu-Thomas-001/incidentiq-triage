"""LangGraph nodes. Every node returns (state_update, status, detail); `traced` adds a trace entry.

Side effects are confined to `human_review` (persist the recommendation + move to NEEDS_REVIEW),
`approved_assignment` (apply an analyst-approved assignment) and `audit_log` (final audit event +
run record, one commit). Nothing here ever writes to ServiceNow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import InvalidTransitionError, PermissionDeniedError, ValidationFailure
from app.db.base import new_uuid
from app.models import Team, TriagePrediction, User, WorkflowRun
from app.models.enums import (
    IncidentStatus,
    Priority,
    Role,
    WorkflowKind,
    WorkflowRunStatus,
)
from app.services import audit, llm_assist, ml_service, routing_policy
from app.services import incidents as svc
from app.services.lifecycle import ensure_transition
from app.workflow.state import TraceEntry, WorkflowState

logger = logging.getLogger(__name__)

NodeResult = tuple[dict[str, Any], str, dict[str, Any]]
MIN_TEXT_CHARS = 20


@dataclass
class WorkflowDeps:
    db: Session
    actor: User
    settings: Settings
    sleep: Callable[[float], None] = field(default=time.sleep)


def deps_of(config: RunnableConfig) -> WorkflowDeps:
    return config["configurable"]["deps"]


def _entry(node: str, status: str, started: float, detail: dict[str, Any]) -> TraceEntry:
    return {
        "node": node,
        "status": status,  # type: ignore[typeddict-item]
        "at": datetime.now(UTC).isoformat(),
        "ms": round((time.perf_counter() - started) * 1000, 2),
        "detail": detail,
    }


def traced(name: str):
    def deco(fn: Callable[[WorkflowState, WorkflowDeps], NodeResult]):
        def wrapper(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
            started = time.perf_counter()
            update, status, detail = fn(state, deps_of(config))
            return {**update, "trace": [_entry(name, status, started, detail)]}

        wrapper.__name__ = name
        return wrapper

    return deco


def _digest(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _incident(state: WorkflowState, deps: WorkflowDeps):
    return svc._get_incident(deps.db, uuid.UUID(state["incident_id"]))


def triage_key(state: WorkflowState, incident, settings: Settings) -> str:
    """Same incident text + inputs + models + routing config => same run (idempotent replay)."""
    versions = sorted(e["model_version"] for e in ml_service.manifest_entries())
    text_hash = hashlib.sha256(f"{incident.title}\n{incident.description}".encode()).hexdigest()
    return _digest(
        "triage",
        str(incident.id),
        text_hash,
        state.get("impact"),
        state.get("urgency"),
        bool(state.get("use_gemini")),
        bool(state.get("external_data_consent")),
        versions,
        routing_policy.RoutingConfig.from_settings(settings).as_dict(),
        settings.gemini_enabled,
    )


# ----------------------------------------------------------------------------- triage path


@traced("intake")
def intake(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    incident = _incident(state, deps)
    key = triage_key(state, incident, deps.settings)
    existing = deps.db.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == key))
    if existing is not None:
        return (
            {"idempotency_key": key, "reused": True, "run_id": str(existing.id)},
            "skipped",
            {"reason": "idempotent_replay", "run_id": str(existing.id)},
        )
    svc._check_version(incident, state["expected_version"])
    ensure_transition(incident.status, IncidentStatus.TRIAGE_PENDING)
    return (
        {"idempotency_key": key, "reused": False, "run_id": str(new_uuid())},
        "ok",
        {
            "incident_status": incident.status.value,
            "incident_version": incident.version,
            "external_reference": incident.external_number,
        },
    )


@traced("validate_input")
def validate_input(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    incident = _incident(state, deps)
    issues: list[str] = []
    if len(incident.title) + len(incident.description) < MIN_TEXT_CHARS:
        issues.append("text_too_short_for_reliable_prediction")
    snapshot = incident.external_snapshot or {}
    inputs: dict[str, Any] = {}
    for name in ("impact", "urgency"):
        value, source = state.get(name), "request"
        if value is None and snapshot.get(name) is not None:
            value, source = snapshot[name], "servicenow_snapshot"
        if value is not None and value not in (1, 2, 3):
            issues.append(f"invalid_{name}_in_{source}")
            value = None
        inputs[name] = {"value": value, "source": source if value is not None else None}
    return {"input_issues": issues, "priority_inputs": inputs}, "ok", {"issues": issues}


def _fallback_ml(reason: str, impact: int | None, urgency: int | None) -> dict[str, Any]:
    unavailable = {"available": False, "reason": reason}
    return {
        "status": "NOT_READY",
        "is_demo": False,
        "outputs": {
            "category": {**unavailable, "model_key": ml_service.CATEGORY_KEY},
            "team": {**unavailable, "model_key": ml_service.TEAM_KEY},
            "priority": ml_service.priority_from_policy(impact, urgency),
        },
        "confidence": None,
        "decision_evidence": [f"models unavailable: {reason}"],
        "model_versions": {},
        "disclaimer": "Recommendation only. A human must approve any assignment or priority.",
    }


@traced("ml_prediction")
def ml_prediction(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    if state.get("ml"):  # resumed run: do not recompute
        return {}, "skipped", {"reason": "already_computed"}
    incident = _incident(state, deps)
    pi = state["priority_inputs"]
    impact, urgency = pi["impact"]["value"], pi["urgency"]["value"]
    try:
        result = ml_service.predict(incident.title, incident.description, impact, urgency)
    except OSError:
        raise  # transient file errors are retried by the node's RetryPolicy
    except Exception as exc:  # a model fault must degrade to NOT_READY, never to invented output
        logger.exception("ml inference failed")
        return (
            {"ml": _fallback_ml(f"inference_error: {type(exc).__name__}", impact, urgency)},
            "fallback",
            {"reason": type(exc).__name__},
        )
    return (
        {"ml": result},
        "ok",
        {"status": result["status"], "model_versions": result["model_versions"]},
    )


@traced("priority_policy")
def priority_policy(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    pi = state["priority_inputs"]
    policy = ml_service.priority_from_policy(pi["impact"]["value"], pi["urgency"]["value"])
    ml = state["ml"]
    ml = {**ml, "outputs": {**ml["outputs"], "priority": policy}}
    detail = {"available": policy["available"], "label": policy.get("label")}
    return {"priority": policy, "ml": ml}, "ok" if policy["available"] else "fallback", detail


@traced("explanation_retrieval")
def explanation_retrieval(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    outputs = state["ml"]["outputs"]
    explanation: dict[str, Any] = {}
    for task in ("category", "team"):
        o = outputs[task]
        if not o.get("available"):
            explanation[task] = {"available": False, "reason": o.get("reason")}
            continue
        explanation[task] = {
            "available": True,
            "model_version": o["model_version"],
            "provenance": o["provenance"],
            "is_demo": o["is_demo"],
            "confidence_kind": o["confidence_kind"],
            "method": o["explanation_method"],
            "top_features": o["explanation_features"],
            "alternatives": o["alternatives"],
            "offline_test_metrics": o["test_metrics"],
        }
    explanation["priority"] = {
        "available": bool(state["priority"].get("available")),
        "source": "policy",
        "evidence": state["priority"].get("evidence") or state["priority"].get("reason"),
    }
    explanation["note"] = (
        "Feature contributions come from an uncalibrated linear surrogate with the same "
        "configuration as the deployed model. They are retrieved from the supervised models, "
        "not generated by an LLM."
    )
    return (
        {"explanation": explanation},
        "ok",
        {
            "tasks": [
                k for k, v in explanation.items() if isinstance(v, dict) and v.get("available")
            ]
        },
    )


@traced("gemini_assist")
def gemini_assist(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    incident = _incident(state, deps)
    envelope = llm_assist.assist(
        incident.title,
        incident.description,
        requested=bool(state.get("use_gemini")),
        consent=bool(state.get("external_data_consent")),
        is_synthetic=incident.is_synthetic,
        settings=deps.settings,
        sleep=deps.sleep,
    )
    status = {"OK": "ok", "NOT_REQUESTED": "skipped", "DISABLED": "skipped"}.get(
        envelope["status"], "fallback"
    )
    detail = {
        "status": envelope["status"],
        "model": envelope["model"],
        "attempts": envelope["attempts"],
    }
    return {"assist": envelope}, status, detail


@traced("routing_policy")
def routing(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    # Deliberately reads only ML outputs and input checks: LLM assistance cannot influence routing.
    team_out = state["ml"]["outputs"]["team"]
    resolvable = bool(
        team_out.get("available")
        and deps.db.scalar(select(Team.id).where(Team.name == team_out.get("label")))
    )
    decision = routing_policy.evaluate(
        state["ml"],
        routing_policy.RoutingConfig.from_settings(deps.settings),
        team_resolvable=resolvable,
        input_issues=state.get("input_issues", []),
    )
    return (
        {"routing": decision},
        "ok",
        {"decision": decision["decision"], "reasons": decision["reasons"]},
    )


@traced("human_review")
def human_review(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    """Persist the recommendation and park the incident in NEEDS_REVIEW for an analyst."""
    incident = _incident(state, deps)
    original = incident.status
    ensure_transition(original, IncidentStatus.TRIAGE_PENDING)
    audit.record(
        deps.db,
        event_type="TRIAGE_REQUESTED",
        actor_id=deps.actor.id,
        incident_id=incident.id,
        from_status=original,
        to_status=IncidentStatus.TRIAGE_PENDING,
        details={"workflow_run_id": state["run_id"]},
    )
    ensure_transition(IncidentStatus.TRIAGE_PENDING, IncidentStatus.NEEDS_REVIEW)
    prediction = svc.record_prediction(
        deps.db,
        deps.actor,
        incident,
        state["ml"],
        extra_audit={
            "workflow_run_id": state["run_id"],
            "routing_decision": state["routing"]["decision"],
            "routing_reasons": state["routing"]["reasons"],
        },
    )
    review = {
        "required": True,
        "queue": state["routing"]["queue"],
        "recommended_team_id": (
            str(prediction.predicted_team_id) if prediction.predicted_team_id else None
        ),
        "recommended_priority": (
            prediction.predicted_priority.value if prediction.predicted_priority else None
        ),
        "next_step": f"POST /api/v1/workflow/incidents/{incident.id}/approve",
    }
    return {"prediction_id": str(prediction.id), "review": review}, "ok", {"queue": review["queue"]}


# ----------------------------------------------------------------------------- approval path


def _require_analyst(actor: User) -> None:
    if actor.role not in (Role.TRIAGE_ANALYST, Role.ADMIN):
        raise PermissionDeniedError("Only triage analysts or admins can approve assignments")


@traced("approval_gate")
def approval_gate(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    _require_analyst(deps.actor)
    db, inp = deps.db, state["approval"]
    incident = _incident(state, deps)
    run = (
        db.get(WorkflowRun, uuid.UUID(inp["run_id"]))
        if inp.get("run_id")
        else db.scalar(
            select(WorkflowRun)
            .where(
                WorkflowRun.incident_id == incident.id,
                WorkflowRun.kind == WorkflowKind.TRIAGE,
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
    )
    key = _digest(
        "approve",
        str(incident.id),
        str(run.id) if run else None,
        inp["team_id"],
        inp.get("priority"),
        inp.get("category"),
    )
    replay = db.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == key))
    if replay is not None:
        return (
            {"idempotency_key": key, "reused": True, "run_id": str(replay.id)},
            "skipped",
            {"reason": "idempotent_replay"},
        )
    if run is None or run.incident_id != incident.id or run.kind != WorkflowKind.TRIAGE:
        raise InvalidTransitionError("No workflow run for this incident is awaiting human review")
    if run.status != WorkflowRunStatus.AWAITING_HUMAN_REVIEW:
        raise InvalidTransitionError(
            "This workflow run is no longer awaiting human review", {"run_status": run.status.value}
        )
    svc._check_version(incident, state["expected_version"])
    prediction = db.get(TriagePrediction, run.prediction_id) if run.prediction_id else None
    team_id = uuid.UUID(inp["team_id"])
    deviations: list[str] = []
    if prediction is None or prediction.predicted_team_id is None:
        deviations.append("no_team_recommendation")
    elif prediction.predicted_team_id != team_id:
        deviations.append("team_differs_from_recommendation")
    if (
        inp.get("priority")
        and prediction
        and prediction.predicted_priority
        and Priority(inp["priority"]) != prediction.predicted_priority
    ):
        deviations.append("priority_differs_from_policy")
    if deviations and not (inp.get("reason") or "").strip():
        raise ValidationFailure(
            "A reason is required when the decision deviates from, or lacks, a recommendation",
            {"deviations": deviations},
        )
    return (
        {
            "idempotency_key": key,
            "reused": False,
            "run_id": str(new_uuid()),
            "prediction_id": str(run.prediction_id) if run.prediction_id else "",
            "approval": {**inp, "triage_run_id": str(run.id), "deviations": deviations},
        },
        "ok",
        {"triage_run_id": str(run.id), "deviations": deviations},
    )


@traced("approved_assignment")
def approved_assignment(state: WorkflowState, deps: WorkflowDeps) -> NodeResult:
    inp = state["approval"]
    incident = svc.assign_incident(
        deps.db,
        deps.actor,
        uuid.UUID(state["incident_id"]),
        expected_version=state["expected_version"],
        team_id=uuid.UUID(inp["team_id"]),
        priority=Priority(inp["priority"]) if inp.get("priority") else None,
        category=inp.get("category"),
        reason=inp.get("reason"),
        prediction_id=uuid.UUID(state["prediction_id"]) if state.get("prediction_id") else None,
        commit=False,
    )
    assignment = svc.current_assignment(deps.db, incident.id)
    approved = {
        "assignment_id": str(assignment.id) if assignment else None,
        "team_id": inp["team_id"],
        "priority": inp.get("priority"),
        "category": inp.get("category"),
        "deviations": inp["deviations"],
        "approved_by": str(deps.actor.id),
    }
    return {"approved": approved}, "ok", {"deviations": inp["deviations"]}


# ----------------------------------------------------------------------------- final node


def audit_log(state: WorkflowState, config: RunnableConfig) -> dict[str, Any]:
    """Write the run record and the final audit event, then commit everything atomically."""
    started = time.perf_counter()
    deps = deps_of(config)
    db = deps.db
    approving = state["action"] == "approve"
    incident_id = uuid.UUID(state["incident_id"])
    outcome = "ASSIGNMENT_APPROVED" if approving else state["routing"]["decision"]
    entry = _entry("audit_log", "ok", started, {"outcome": outcome})
    trace = [*state.get("trace", []), entry]

    saved = {
        k: state[k]
        for k in (
            "input_issues",
            "priority_inputs",
            "ml",
            "priority",
            "explanation",
            "assist",
            "routing",
            "review",
            "approved",
            "approval",
            "outcome",
        )
        if k in state
    }
    saved["outcome"] = outcome
    run = WorkflowRun(
        id=uuid.UUID(state["run_id"]),
        incident_id=incident_id,
        kind=WorkflowKind.APPROVAL if approving else WorkflowKind.TRIAGE,
        status=(
            WorkflowRunStatus.COMPLETED if approving else WorkflowRunStatus.AWAITING_HUMAN_REVIEW
        ),
        idempotency_key=state["idempotency_key"],
        prediction_id=uuid.UUID(state["prediction_id"]) if state.get("prediction_id") else None,
        actor_id=deps.actor.id,
        state=saved,
        trace=trace,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent identical request won the race: discard our side effects, return its run.
        db.rollback()
        existing = db.scalar(
            select(WorkflowRun).where(WorkflowRun.idempotency_key == state["idempotency_key"])
        )
        if existing is None:
            raise
        return {
            "reused": True,
            "run_id": str(existing.id),
            "outcome": existing.state.get("outcome", ""),
            "trace": [entry],
        }
    if approving:
        triage_run = db.get(WorkflowRun, uuid.UUID(state["approval"]["triage_run_id"]))
        if triage_run is not None:
            triage_run.status = WorkflowRunStatus.APPROVED
        details: dict[str, Any] = {
            "workflow_run_id": state["run_id"],
            "triage_run_id": state["approval"]["triage_run_id"],
            "deviations": state["approval"]["deviations"],
            "reason": state["approval"].get("reason"),
        }
        event = "WORKFLOW_APPROVAL_COMPLETED"
    else:
        assist = state.get("assist") or {}
        details = {
            "workflow_run_id": state["run_id"],
            "routing_decision": state["routing"]["decision"],
            "routing_reasons": state["routing"]["reasons"],
            "gemini": {
                "status": assist.get("status"),
                "model": assist.get("model"),
                "attempts": assist.get("attempts"),
                "data_sent": assist.get("data_sent"),  # sizes/redaction counts only, never content
            },
            "nodes": [t["node"] for t in trace],
        }
        event = "WORKFLOW_TRIAGE_COMPLETED"
    audit.record(
        db, event_type=event, actor_id=deps.actor.id, incident_id=incident_id, details=details
    )
    db.commit()
    return {"outcome": outcome, "trace": [entry]}
