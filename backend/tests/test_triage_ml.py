"""Triage integration with trained models. Models here are tiny fixtures built on the fly."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.services import ml_service
from tests.conftest import PASSWORD  # noqa: F401  (ensures fixtures module import)

DOCS = {
    "Network": [
        "vpn connection drops",
        "wifi network slow",
        "lan outage switch",
        "dns network down",
    ]
    * 2,
    "Software": [
        "application crashes on save",
        "software error 500",
        "app login blank",
        "program freezes",
    ]
    * 2,
}


def _fit(label_map: dict[str, list[str]]):
    texts = [t for ts in label_map.values() for t in ts]
    labels = [lab for lab, ts in label_map.items() for _ in ts]
    frame = pd.DataFrame({"text": texts})

    def pipe():
        return Pipeline(
            [
                ("features", ColumnTransformer([("word", TfidfVectorizer(), "text")])),
                ("clf", LogisticRegression(max_iter=500)),
            ]
        )

    explainer = pipe().fit(frame, labels)
    cal = CalibratedClassifierCV(pipe(), method="sigmoid", cv=2).fit(frame, labels)
    return cal, explainer


def build_artifact(model_dir: Path, key: str, labels: dict, *, demo: bool, template: str) -> dict:
    model_dir.mkdir(parents=True, exist_ok=True)
    cal, explainer = _fit(labels)
    path = model_dir / f"{key}.joblib"
    joblib.dump(
        {
            "model": cal,
            "explainer": explainer,
            "classes": [str(c) for c in cal.classes_],
        },
        path,
    )
    entry = {
        "task": key,
        "key": key,
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "provenance": "synthetic-demo" if demo else "real",
        "is_demo": demo,
        "model_version": f"{key}-test0001",
        "dataset_fingerprint": "test",
        "text_template": template,
        "class_mapping": {str(i): str(c) for i, c in enumerate(cal.classes_)},
        "training_config": {"calibration": "sigmoid", "seed": 1},
        "split": {"strategy": "test"},
        "metrics": {"test_macro_f1": 0.5},
        "library_versions": {
            "scikit-learn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "trained_at": datetime.now(UTC).isoformat(),
    }
    mpath = model_dir / "manifest.json"
    manifest = (
        json.loads(mpath.read_text()) if mpath.exists() else {"schema_version": 1, "models": {}}
    )
    manifest["models"][key] = entry
    mpath.write_text(json.dumps(manifest))
    ml_service.clear_cache()
    return entry


@pytest.fixture
def both_models(model_dir):
    build_artifact(model_dir, "category_real", DOCS, demo=False, template="description")
    team_docs = {"Network": DOCS["Network"], "Apps": DOCS["Software"]}
    build_artifact(model_dir, "team_synthetic", team_docs, demo=True, template="title_description")
    return model_dir


def _new_incident(
    api,
    title="VPN connection drops",
    description="vpn connection drops every few minutes",
):
    r = api.post("/incidents", "reporter", {"title": title, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


def _triage(api, inc, **extra):
    return api.post(
        f"/incidents/{inc['id']}/triage",
        "analyst",
        {"expected_version": inc["version"], **extra},
    )


def test_demo_triage_returns_labelled_outputs_and_stays_a_recommendation(api, world, both_models):
    inc = _new_incident(api)
    r = _triage(api, inc, impact=1, urgency=2)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DEMO" and body["is_demo"] is True and "SYNTHETIC" in body["message"]
    cat, team, prio = (
        body["outputs"]["category"],
        body["outputs"]["team"],
        body["outputs"]["priority"],
    )
    assert cat["label"] == "Network" and cat["provenance"] == "real" and 0 < cat["confidence"] <= 1
    assert (
        team["label"] == "Network"
        and team["provenance"] == "synthetic-demo"
        and team["is_demo"] is True
    )
    assert cat["explanation_features"] and all(
        f["contribution"] > 0 for f in cat["explanation_features"]
    )
    assert prio["label"] == "P2" and prio["source"] == "policy"
    assert body["model_versions"]["category"] == "category_real-test0001"
    assert 0 < body["confidence"] <= 1 and body["decision_evidence"]
    inc2 = body["incident"]
    assert inc2["status"] == "NEEDS_REVIEW"
    assert inc2["current_assignment"] is None and inc2["approved_priority"] is None
    pred = inc2["latest_prediction"]
    assert pred["status"] == "DEMO" and pred["predicted_category"] == "Network"
    assert pred["predicted_priority"] == "P2" and pred["predicted_team_id"] == str(
        world["teams"]["net"]
    )
    events = api.get(f"/incidents/{inc['id']}/audit", "analyst").json()["items"]
    assert "TRIAGE_RECOMMENDED" in [e["event_type"] for e in events]


def test_metrics_endpoint_reports_recorded_provenance(api, both_models):
    r = api.get("/models/metrics", "analyst").json()
    assert r["status"] == "AVAILABLE"
    by_name = {m["name"]: m for m in r["models"]}
    assert by_name["category_real"]["metrics"]["provenance"] == "real"
    assert by_name["team_synthetic"]["metrics"]["is_demo"] is True
    assert by_name["team_synthetic"]["metrics"]["test_metrics"] == {"test_macro_f1": 0.5}


def test_real_model_only_is_model_status_and_team_unavailable(api, model_dir):
    build_artifact(model_dir, "category_real", DOCS, demo=False, template="description")
    body = _triage(api, _new_incident(api)).json()
    assert body["status"] == "MODEL" and body["is_demo"] is False
    assert body["outputs"]["team"]["available"] is False
    assert "model_unavailable" in body["outputs"]["team"]["reason"]
    assert body["outputs"]["priority"]["available"] is False  # no impact/urgency supplied


def test_unknown_vocabulary_yields_unavailable_not_a_guess(api, both_models):
    inc = _new_incident(api, "zzqx wvvk plorb", "qqqq xxxxzz yyyyww unknownwordsonly")
    body = _triage(api, inc).json()
    assert body["status"] == "NOT_READY"
    assert body["outputs"]["category"]["available"] is False
    assert "no_known_terms" in body["outputs"]["category"]["reason"]
    assert body["incident"]["latest_prediction"]["predicted_category"] is None
    assert body["confidence"] is None


def test_tampered_artifact_is_refused(api, both_models):
    p = both_models / "category_real.joblib"
    p.write_bytes(p.read_bytes() + b"x")
    ml_service.clear_cache()
    body = _triage(api, _new_incident(api)).json()
    assert body["outputs"]["category"]["available"] is False
    assert "SHA-256" in body["outputs"]["category"]["reason"]
    assert body["outputs"]["team"]["available"] is True  # the other model is unaffected


def test_manifest_path_traversal_is_refused(api, both_models):
    mpath = both_models / "manifest.json"
    m = json.loads(mpath.read_text())
    m["models"]["category_real"]["file"] = "../evil.joblib"
    mpath.write_text(json.dumps(m))
    ml_service.clear_cache()
    reg = ml_service.get_registry()
    assert "category_real" not in reg.models and "plain file name" in reg.problems["category_real"]


def test_library_version_mismatch_is_refused(api, both_models):
    mpath = both_models / "manifest.json"
    m = json.loads(mpath.read_text())
    m["models"]["team_synthetic"]["library_versions"]["scikit-learn"] = "0.1.0"
    mpath.write_text(json.dumps(m))
    ml_service.clear_cache()
    assert "library mismatch" in ml_service.get_registry().problems["team_synthetic"]


def test_priority_policy_edges(api, both_models):
    inc = _new_incident(api)
    assert _triage(api, inc, impact=9, urgency=1).status_code == 422
    r = _triage(api, inc, impact=1, urgency=3).json()
    assert r["outputs"]["priority"]["available"] is False
    assert "not defined" in r["outputs"]["priority"]["reason"]


def test_reporter_cannot_trigger_triage(api, both_models):
    inc = _new_incident(api)
    r = api.post(
        f"/incidents/{inc['id']}/triage",
        "reporter",
        {"expected_version": inc["version"]},
    )
    assert r.status_code == 403


def test_policy_table_matches_ml_package():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml" / "src"))
    from incidentiq_ml.policy import PRIORITY_POLICY as ml_policy

    to_p = {
        "1 - Critical": "P1",
        "2 - High": "P2",
        "3 - Moderate": "P3",
        "4 - Low": "P4",
    }
    assert {k: to_p[v] for k, v in ml_policy.items()} == ml_service.PRIORITY_POLICY
