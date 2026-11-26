"""Routing policy: decides which review path an incident takes. Assignment itself needs approval.

- Uses only retrieval agreement from the local incident index (never LLM self-reported confidence).
- Per-task thresholds are configuration (ROUTING_THRESHOLD_CATEGORY / _TEAM).
- Disabled by default: with ROUTING_ENABLED=false every incident takes the standard review path.
- Even when enabled, the best outcome is PROPOSE_ASSIGNMENT: a pre-filled suggestion for one-click
  analyst approval. `auto_assign` stays False here; the opt-in autopilot (AUTOPILOT_AUTO_ASSIGN) is
  the only component that may act on a proposal, and it records an audited system approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings

NEEDS_REVIEW = "NEEDS_REVIEW"
PROPOSE_ASSIGNMENT = "PROPOSE_ASSIGNMENT"


@dataclass(frozen=True)
class RoutingConfig:
    enabled: bool
    threshold_category: float
    threshold_team: float

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RoutingConfig:
        s = settings or get_settings()
        return cls(s.routing_enabled, s.routing_threshold_category, s.routing_threshold_team)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "thresholds": {"category": self.threshold_category, "team": self.threshold_team},
        }


def _check_task(task: str, out: dict[str, Any], threshold: float) -> dict[str, Any]:
    check: dict[str, Any] = {"task": task, "passed": False, "threshold": threshold}
    if not out.get("available"):
        check["reason"] = f"{task}_prediction_unavailable"
    elif out.get("is_demo") or out.get("provenance") != "real":
        check["reason"] = f"{task}_not_based_on_servicenow_data"
    elif out.get("confidence_kind") != "retrieval_agreement":
        check["reason"] = f"{task}_confidence_not_retrieval_agreement"
    elif out.get("confidence") is None or out["confidence"] < threshold:
        check["confidence"] = out.get("confidence")
        check["reason"] = f"{task}_confidence_below_threshold"
    else:
        check.update(passed=True, confidence=out["confidence"], reason=None)
    return check


def evaluate(
    ml_result: dict[str, Any],
    cfg: RoutingConfig,
    *,
    team_resolvable: bool,
    input_issues: list[str] | None = None,
) -> dict[str, Any]:
    outputs = ml_result.get("outputs", {})
    checks = [
        _check_task("category", outputs.get("category", {}), cfg.threshold_category),
        _check_task("team", outputs.get("team", {}), cfg.threshold_team),
    ]
    if checks[1]["passed"] and not team_resolvable:
        checks[1].update(passed=False, reason="team_label_not_mapped_to_local_team")
    priority_ok = bool(outputs.get("priority", {}).get("available"))
    checks.append(
        {
            "task": "priority",
            "passed": priority_ok,
            "reason": None if priority_ok else "priority_policy_inputs_missing",
        }
    )
    reasons = [c["reason"] for c in checks if not c["passed"]]
    reasons += list(input_issues or [])
    if not cfg.enabled:
        reasons.insert(0, "routing_disabled")
    proposed = cfg.enabled and not reasons
    return {
        "decision": PROPOSE_ASSIGNMENT if proposed else NEEDS_REVIEW,
        "queue": "fast_approval" if proposed else "standard_review",
        "auto_assign": False,
        "human_approval_required": True,
        "routing_enabled": cfg.enabled,
        "reasons": reasons,
        "checks": checks,
        "thresholds": cfg.as_dict()["thresholds"],
        "note": "Thresholds are configuration, not validated guarantees; a human must approve.",
    }
