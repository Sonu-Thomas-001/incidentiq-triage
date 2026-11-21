"""Read-only summaries of offline evaluation results written by the ML pipeline.

The source files (`docs/report/results/*.json`) are measured outputs of `ml/`; nothing is computed
or invented here. Files are parsed defensively and malformed ones are skipped.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TASK_BY_PREFIX = {"category": "category", "group": "assignment_group", "team": "assignment_group"}
MAX_CONFUSION_LABELS = 50


def _metrics(test: dict[str, Any] | None) -> dict[str, Any] | None:
    if not test:
        return None
    topk = test.get("topk") or {}
    return {
        "n": test.get("n"),
        "accuracy": test.get("accuracy"),
        "macro_f1": (test.get("macro") or {}).get("f1"),
        "macro_precision": (test.get("macro") or {}).get("precision"),
        "macro_recall": (test.get("macro") or {}).get("recall"),
        "weighted_f1": (test.get("weighted") or {}).get("f1"),
        "top1": topk.get("1"),
        "top3": topk.get("3"),
        "high_priority_recall": test.get("high_priority_recall"),
    }


def _detail(test: dict[str, Any]) -> dict[str, Any]:
    cm = test.get("confusion_matrix") or {}
    labels = cm.get("labels") or []
    per_class = [
        {"label": k, **{m: v.get(m) for m in ("precision", "recall", "f1", "support")}}
        for k, v in (test.get("per_class") or {}).items()
    ]
    return {
        "per_class": per_class,
        "confusion": (
            {"labels": labels, "matrix": cm.get("matrix")}
            if cm and len(labels) <= MAX_CONFUSION_LABELS
            else None
        ),
    }


def _summarise(data: dict[str, Any]) -> dict[str, Any] | None:
    name = str(data.get("experiment", ""))
    dataset = data.get("dataset") or {}
    provenance = dataset.get("provenance", "unknown")
    base = {
        "experiment": name,
        "task": next((t for p, t in TASK_BY_PREFIX.items() if p in name), "priority"),
        "provenance": provenance,
        "is_demo": provenance != "real",
        "dataset": dataset,
        "split": data.get("split"),
        "seed": data.get("seed"),
        "protocol": data.get("protocol"),
    }
    if "policy_test" in data:  # priority: a deterministic policy, not an ML discovery
        rows = [
            {
                "name": "impact x urgency policy",
                "kind": "policy",
                "test": _metrics(data["policy_test"]),
            },
            {
                "name": "majority baseline",
                "kind": "baseline",
                "test": _metrics(data.get("majority_baseline_test")),
            },
            {
                "name": "decision tree on impact, urgency",
                "kind": "model",
                "test": _metrics(data.get("decision_tree_on_impact_urgency_test")),
            },
        ]
        return {
            **base,
            "task": "priority",
            "finding": data.get("finding"),
            "policy_table": data.get("policy_table"),
            "rows": rows,
            "selected": "impact x urgency policy",
            "selected_detail": _detail(data["policy_test"]),
        }
    models = data.get("models") or {}
    rows = [
        {
            "name": k,
            "kind": "baseline",
            "val_macro_f1": v.get("val_macro_f1"),
            "test": _metrics(v.get("test")),
        }
        for k, v in (data.get("baselines") or {}).items()
    ] + [
        {
            "name": k,
            "kind": "model",
            "feature_set": v.get("feature_set"),
            "algorithm": v.get("algorithm"),
            "val_macro_f1": v.get("val_macro_f1"),
            "test": _metrics(v.get("test")),
        }
        for k, v in models.items()
    ]
    selected = data.get("deploy_choice") or data.get("selected_by_validation")
    sel_test = (models.get(selected) or {}).get("test")
    calibration = data.get("calibration") or {}
    cal_test = calibration.get("calibrated_test")
    return {
        **base,
        "rows": rows,
        "selected": data.get("selected_by_validation"),
        "deploy_choice": data.get("deploy_choice"),
        "selected_detail": _detail(sel_test) if sel_test else None,
        "calibration": (
            {
                "method": calibration.get("method_selected_on_validation"),
                "ece_top_label": cal_test.get("ece_top_label"),
                "brier": cal_test.get("brier_multiclass"),
                "reliability_bins": cal_test.get("reliability_bins"),
                "threshold_tradeoff": calibration.get("confidence_threshold_tradeoff"),
            }
            if cal_test
            else None
        ),
        "leakage_diagnostic_macro_f1": data.get("leakage_diagnostic_macro_f1"),
        "class_support": (
            {p["label"]: p["support"] for p in _detail(sel_test)["per_class"]} if sel_test else None
        ),
    }


def list_evaluations() -> dict[str, Any]:
    directory = Path(get_settings().evaluation_dir)
    experiments: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            if path.name.startswith(("validation_", "eda_")):
                continue
            try:
                summary = _summarise(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                logger.warning("skipping evaluation file %s: %s", path.name, type(exc).__name__)
                continue
            if summary:
                experiments.append(summary)
    return {
        "status": "AVAILABLE" if experiments else "NOT_READY",
        "message": (
            "Measured offline on held-out test splits. Experiments with is_demo=true use SYNTHETIC "
            "data and are not evidence of real-world performance."
            if experiments
            else "No evaluation result files were found; no metrics are available."
        ),
        "experiments": experiments,
    }
