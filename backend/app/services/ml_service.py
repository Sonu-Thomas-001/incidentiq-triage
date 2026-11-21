"""Inference service for trained triage models (loaded from MODEL_DIR).

Safety rules:
- Artifacts are joblib files and can run code when loaded; only trusted, locally produced files may be
  placed in MODEL_DIR. Before loading we verify (a) the path stays inside MODEL_DIR, (b) the SHA-256 recorded in
  manifest.json, and (c) matching scikit-learn/numpy major.minor versions.
- Nothing is fabricated: any problem makes the corresponding output "unavailable" with a reason.
- Output is a recommendation only; humans approve assignments.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Keep identical to ml/src/incidentiq_ml/policy.py (a test enforces equality).
PRIORITY_POLICY: dict[tuple[int, int], str] = {
    (1, 1): "P1",
    (1, 2): "P2",
    (2, 1): "P2",
    (2, 2): "P3",
    (2, 3): "P4",
    (3, 1): "P3",
    (3, 2): "P4",
    (3, 3): "P4",
}
POLICY_LABELS = {
    "P1": "1 - Critical",
    "P2": "2 - High",
    "P3": "3 - Moderate",
    "P4": "4 - Low",
}

CATEGORY_KEY = "category_real"
TEAM_KEY = "team_synthetic"
TOP_ALTERNATIVES = 3
TOP_FEATURES = 8


@dataclass
class LoadedModel:
    key: str
    entry: dict[str, Any]
    model: Any
    explainer: Any
    classes: list[str]


@dataclass
class Registry:
    model_dir: Path
    models: dict[str, LoadedModel] = field(default_factory=dict)
    problems: dict[str, str] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)


_lock = threading.Lock()
_registry: Registry | None = None


def model_dir() -> Path:
    configured = get_settings().model_dir
    return Path(configured).expanduser().resolve()


def clear_cache() -> None:
    global _registry
    with _lock:
        _registry = None


def _minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def _load_one(base: Path, key: str, entry: dict[str, Any]) -> LoadedModel:
    import joblib
    import numpy
    import sklearn

    name = entry.get("file", "")
    if not name or Path(name).name != name:
        raise ValueError("manifest file name must be a plain file name")
    path = (base / name).resolve()
    if base not in path.parents:
        raise ValueError("artifact path escapes MODEL_DIR")
    if not path.is_file():
        raise FileNotFoundError(f"artifact file {name} not found")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise ValueError("SHA-256 mismatch: artifact was modified or does not match manifest")
    libs = entry.get("library_versions", {})
    if _minor(libs.get("scikit-learn", "")) != _minor(sklearn.__version__) or _minor(
        libs.get("numpy", "")
    ) != _minor(numpy.__version__):
        raise ValueError(
            f"library mismatch (trained sklearn {libs.get('scikit-learn')}, numpy "
            f"{libs.get('numpy')}; runtime sklearn {sklearn.__version__}, numpy {numpy.__version__})"
        )
    bundle = joblib.load(path)  # trusted, hash-verified local artifact
    return LoadedModel(key, entry, bundle["model"], bundle["explainer"], list(bundle["classes"]))


def get_registry() -> Registry:
    global _registry
    with _lock:
        base = model_dir()
        if _registry is not None and _registry.model_dir == base:
            return _registry
        reg = Registry(model_dir=base)
        manifest_path = base / "manifest.json"
        if not manifest_path.is_file():
            reg.problems["*"] = f"no manifest.json in model directory ({base.name})"
        else:
            try:
                reg.manifest = json.loads(manifest_path.read_text())
                entries = reg.manifest.get("models", {})
            except (OSError, ValueError) as exc:
                entries = {}
                reg.problems["*"] = f"unreadable manifest: {exc}"
            for key in (CATEGORY_KEY, TEAM_KEY):
                if key not in entries:
                    reg.problems.setdefault(key, "model not present in manifest")
                    continue
                try:
                    reg.models[key] = _load_one(base, key, entries[key])
                except Exception as exc:  # noqa: BLE001 - any failure means "unavailable"
                    logger.warning("model %s unavailable: %s", key, exc)
                    reg.problems[key] = str(exc)
        _registry = reg
        return reg


def available() -> bool:
    return bool(get_registry().models)


def _contributions(loaded: LoadedModel, frame, label: str) -> list[dict[str, Any]]:
    pipe = loaded.explainer
    clf = pipe.named_steps["clf"]
    x = pipe.named_steps["features"].transform(frame).tocsr()
    idx = list(clf.classes_).index(label)
    # binary classifiers store a single coefficient row for the positive (second) class
    row = clf.coef_[idx] if clf.coef_.shape[0] > 1 else clf.coef_[0] * (1 if idx == 1 else -1)
    contrib = x.data * row[x.indices]
    names = pipe.named_steps["features"].get_feature_names_out()
    order = contrib.argsort()[::-1][:TOP_FEATURES]
    return [
        {
            "feature": str(names[x.indices[i]]).split("__", 1)[-1],
            "contribution": round(float(contrib[i]), 4),
        }
        for i in order
        if contrib[i] > 0
    ]


def _text_for(loaded: LoadedModel, title: str, description: str) -> str:
    if loaded.entry.get("text_template") == "title_description":
        return f"{title.strip()}. {description.strip()}"
    return description.strip()


def _predict_text(loaded: LoadedModel, title: str, description: str) -> dict[str, Any]:
    import pandas as pd

    frame = pd.DataFrame({"text": [_text_for(loaded, title, description)]})
    entry = loaded.entry
    base = {
        "model_key": loaded.key,
        "model_version": entry["model_version"],
        "provenance": entry["provenance"],
        "is_demo": bool(entry.get("is_demo")),
    }
    if loaded.explainer.named_steps["features"].transform(frame).nnz == 0:
        return {
            **base,
            "available": False,
            "reason": "no_known_terms: none of the input terms appear in the model vocabulary",
        }
    proba = loaded.model.predict_proba(frame)[0]
    classes = [str(c) for c in loaded.model.classes_]
    order = proba.argsort()[::-1]
    label = classes[order[0]]
    return {
        **base,
        "available": True,
        "label": label,
        "confidence": round(float(proba[order[0]]), 4),
        "confidence_kind": "calibrated probability (cross-validated "
        f"{entry['training_config']['calibration']} calibration)",
        "alternatives": [
            {"label": classes[i], "probability": round(float(proba[i]), 4)}
            for i in order[1 : 1 + TOP_ALTERNATIVES]
        ],
        "explanation_features": _contributions(loaded, frame, label),
        "explanation_method": "linear coefficient x TF-IDF value of an uncalibrated linear "
        "model with the same configuration",
        "test_metrics": entry.get("metrics"),
    }


def priority_from_policy(impact: int | None, urgency: int | None) -> dict[str, Any]:
    if impact is None or urgency is None:
        return {
            "available": False,
            "reason": "impact and urgency are required to apply the priority policy",
            "source": "policy",
        }
    p = PRIORITY_POLICY.get((impact, urgency))
    if p is None:
        return {
            "available": False,
            "reason": "impact/urgency combination is not defined by the policy (never observed)",
            "source": "policy",
        }
    return {
        "available": True,
        "label": p,
        "policy_label": POLICY_LABELS[p],
        "source": "policy",
        "provenance": "real",
        "evidence": f"impact={impact}, urgency={urgency} -> {p} (deterministic ServiceNow policy "
        "verified on 141,712 events with 0 exceptions); not an ML prediction",
    }


def predict(
    title: str, description: str, impact: int | None = None, urgency: int | None = None
) -> dict[str, Any]:
    """Return per-output recommendations plus an overall status (NOT_READY | DEMO | MODEL)."""
    reg = get_registry()
    outputs: dict[str, Any] = {}
    for out_name, key in (("category", CATEGORY_KEY), ("team", TEAM_KEY)):
        loaded = reg.models.get(key)
        if loaded is None:
            outputs[out_name] = {
                "available": False,
                "reason": f"model_unavailable: {reg.problems.get(key) or reg.problems.get('*', 'unknown')}",
                "model_key": key,
            }
        else:
            outputs[out_name] = _predict_text(loaded, title, description)
    outputs["priority"] = priority_from_policy(impact, urgency)

    model_outputs = [outputs["category"], outputs["team"]]
    produced = [o for o in model_outputs if o.get("available")]
    if not produced:
        status = "NOT_READY"
    elif any(o.get("is_demo") for o in produced):
        status = "DEMO"
    else:
        status = "MODEL"
    confs = [o["confidence"] for o in produced]
    evidence = []
    for name, o in outputs.items():
        if o.get("available"):
            src = o.get("provenance", "")
            if name == "priority":
                evidence.append(f"priority: {o['evidence']}")
            else:
                evidence.append(
                    f"{name}: '{o['label']}' (confidence {o['confidence']:.2f}, model "
                    f"{o['model_version']}, trained on {src} data)"
                )
        else:
            evidence.append(f"{name}: unavailable - {o.get('reason')}")
    return {
        "status": status,
        "is_demo": status == "DEMO",
        "outputs": outputs,
        "confidence": min(confs) if confs else None,
        "decision_evidence": evidence,
        "model_versions": {
            n: o["model_version"] for n, o in outputs.items() if o.get("model_version")
        },
        "disclaimer": "Recommendation only. A human must approve any assignment or priority.",
    }


def manifest_entries() -> list[dict[str, Any]]:
    reg = get_registry()
    return [e for e in reg.manifest.get("models", {}).values()]
