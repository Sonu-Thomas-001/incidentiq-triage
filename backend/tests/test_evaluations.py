def test_evaluations_endpoint_serves_measured_results_with_provenance(api):
    r = api.get("/models/evaluations", "analyst")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"AVAILABLE", "NOT_READY"}
    for exp in body["experiments"]:
        assert exp["is_demo"] == (exp["provenance"] != "real")


def test_evaluations_missing_dir_is_not_ready(api, monkeypatch, tmp_path):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "evaluation_dir", str(tmp_path))
    body = api.get("/models/evaluations", "analyst").json()
    assert body["status"] == "NOT_READY" and body["experiments"] == []


def test_evaluations_forbidden_for_reporter(api):
    assert api.get("/models/evaluations", "reporter").status_code == 403


def test_overview_has_no_fabricated_confidence_or_override_rate(api):
    api.create()
    o = api.get("/analytics/overview", "analyst").json()
    assert o["confidence_histogram"] == []
    assert o["override_rate"] is None
    assert sum(o["incidents_per_day"].values()) == 1
