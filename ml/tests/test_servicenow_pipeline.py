"""ServiceNow-sourced pipeline: pull mapping, insufficient-data refusal and end-to-end training.

The frames below are test fixtures for exercising code paths; they are not application data.
"""

import json

import numpy as np
import pandas as pd
import pytest

from incidentiq_ml import config as C
from incidentiq_ml import servicenow_data as SD
from incidentiq_ml import servicenow_tasks as ST


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(C, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(C, "FIGURES_DIR", tmp_path / "figures")
    monkeypatch.setattr(C, "SN_RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(C, "SN_FIGURES_DIR", tmp_path / "figures")
    monkeypatch.setattr(SD, "SN_RAW_DIR", tmp_path / "raw")
    return tmp_path


def _fixture_frame(n: int) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    bank = {
        "network": ["vpn", "wifi", "router", "switch", "latency", "packet", "dns", "gateway", "firewall", "bandwidth"],
        "software": [
            "install",
            "license",
            "crash",
            "update",
            "patch",
            "application",
            "error",
            "reinstall",
            "plugin",
            "upgrade",
        ],
        "hardware": [
            "laptop",
            "monitor",
            "keyboard",
            "battery",
            "printer",
            "dock",
            "mouse",
            "screen",
            "fan",
            "charger",
        ],
    }
    team = {"network": "Network", "software": "Apps", "hardware": "Desk"}
    filler = [f"word{i}" for i in range(60)]
    rows = []
    for i in range(n):
        cat = list(bank)[i % 3]
        words = list(rng.choice(bank[cat], 5)) + list(rng.choice(filler, 6))
        imp, urg = int(rng.integers(1, 4)), int(rng.integers(1, 4))
        rows.append(
            {
                "incident_id": f"INC{i:07d}", "sys_id": f"{i:032x}",
                "short_description": " ".join(words[:3]), "description": " ".join(words),
                "category": cat, "priority": str(min(imp + urg - 1, 5)), "impact": str(imp), "urgency": str(urg),
                "assignment_group": team[cat], "assignment_group_sys_id": None,
                "created_at": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=i),
                "service": None, "state": "1", "provenance": C.PROV_REAL, "source": "servicenow",
            }
        )  # fmt: skip
    return pd.DataFrame(rows)


def test_to_frame_maps_reference_fields_in_both_shapes():
    rows = [
        {
            "number": "INC1",
            "sys_id": "a" * 32,
            "short_description": " x ",
            "assignment_group": "g" * 32,
            "opened_at": "2026-01-01 10:00:00",
        },
        {"number": "INC2", "sys_id": "b" * 32, "assignment_group": {"value": "h" * 32, "link": "x"}, "category": ""},
    ]
    df = SD.to_frame(rows, {"g" * 32: "Network", "h" * 32: "Apps"})
    assert list(df["assignment_group"]) == ["Network", "Apps"]
    assert df["short_description"].iloc[0] == "x" and df["category"].isna().all()
    assert (df["provenance"] == C.PROV_REAL).all() and (df["source"] == "servicenow").all()


def test_requested_fields_exclude_post_triage_columns():
    fields = set(SD.INCIDENT_FIELDS.split(","))
    for leaked in (
        "close_notes",
        "close_code",
        "resolved_at",
        "closed_at",
        "reassignment_count",
        "work_notes",
        "subcategory",
    ):
        assert leaked not in fields


def test_pull_uses_get_only_and_stores_processed_frame(dirs, monkeypatch):
    calls = []

    class FakeSession:
        headers: dict = {}
        auth = None

        def get(self, url, params=None, **kw):
            calls.append((url, dict(params)))
            table = url.rsplit("/", 1)[-1]
            body = (
                [{"sys_id": "g" * 32, "name": "Network"}]
                if table == "sys_user_group"
                else [{"number": "INC1", "sys_id": "a" * 32, "short_description": "vpn", "assignment_group": "g" * 32}]
            )
            return type("R", (), {"status_code": 200, "headers": {}, "json": lambda self: {"result": body}})()

    import requests

    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://dev1.service-now.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "svc")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "x")
    meta = SD.pull()
    assert meta["incident_rows"] == 1 and meta["instance_host"] == "dev1.service-now.com"
    assert {c[0].rsplit("/", 1)[-1] for c in calls} == {"incident", "sys_user_group"}
    assert pd.read_parquet(SD.processed_path())["assignment_group"].tolist() == ["Network"]


def test_pull_refuses_non_servicenow_host(monkeypatch):
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://evil.example.com")
    monkeypatch.setenv("SERVICENOW_USERNAME", "svc")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "x")
    with pytest.raises(SD.ServiceNowPullError):
        SD.pull()


def test_too_little_data_skips_training_and_writes_no_model(dirs):
    (dirs / "processed").mkdir(parents=True, exist_ok=True)
    _fixture_frame(30).to_parquet(SD.processed_path(), index=False)
    out = ST.run_all(fast=True, model_dir=dirs / "models")
    assert {t["status"] for t in out["tasks"].values()} == {"SKIPPED_INSUFFICIENT_DATA"}
    assert not (dirs / "models" / "manifest.json").exists()


def test_end_to_end_training_writes_servicenow_artifacts(dirs):
    (dirs / "processed").mkdir(parents=True, exist_ok=True)
    _fixture_frame(450).to_parquet(SD.processed_path(), index=False)
    out = ST.run_all(fast=True, model_dir=dirs / "models")
    assert out["tasks"]["category"]["status"] == "TRAINED_AND_EVALUATED"
    assert out["tasks"]["team"]["status"] == "TRAINED_AND_EVALUATED"
    manifest = json.loads((dirs / "models" / "manifest.json").read_text())["models"]
    assert set(manifest) == {"category_servicenow", "team_servicenow"}
    for entry in manifest.values():
        assert entry["provenance"] == "real" and entry["is_demo"] is False and entry["data_source"] == "servicenow"
        assert entry["text_template"] == "title_description"
    result = json.loads((dirs / "results" / "servicenow_team.json").read_text())
    assert result["dataset"]["source"] == "servicenow"
    prio = json.loads((dirs / "results" / "servicenow_priority.json").read_text())
    assert "policy_test" in prio and prio["dataset"]["source"] == "servicenow"
