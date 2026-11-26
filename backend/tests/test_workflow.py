"""LangGraph workflow, routing policy and Gemini assistance. Fully offline; Gemini is faked."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import AuditEvent, TriagePrediction, WorkflowRun
from app.services import llm_assist, routing_policy


def _run(api, inc, who="analyst", **extra):
    return api.post(
        f"/workflow/incidents/{inc['id']}/run",
        who,
        {"expected_version": inc["version"], "impact": 2, "urgency": 2, **extra},
    )


def test_run_without_models_is_not_ready_and_moves_to_review(api, world):
    inc = api.create()
    r = _run(api, inc)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "NEEDS_REVIEW"
    assert body["ml"]["status"] == "NOT_READY"
    assert body["routing"]["decision"] == "NEEDS_REVIEW"
    assert body["routing"]["auto_assign"] is False
    assert "routing_disabled" in body["routing"]["reasons"]
    assert body["incident"]["status"] == "NEEDS_REVIEW"
    assert [t["node"] for t in body["trace"]][0] == "intake"
    # priority comes from the deterministic policy, never a model
    assert body["ml"]["outputs"]["priority"]["label"] == "P3"


def test_run_is_idempotent(api, world, session_factory):
    inc = api.create()
    first = _run(api, inc).json()
    second = _run(api, inc)
    assert second.status_code == 200, second.text
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == first["run_id"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(WorkflowRun)) == 1
        assert db.scalar(select(func.count()).select_from(TriagePrediction)) == 1


def test_stale_version_rejected(api, world):
    inc = api.create()
    r = api.post(f"/workflow/incidents/{inc['id']}/run", "analyst", {"expected_version": 99})
    assert r.status_code == 409


@pytest.mark.parametrize("who", ["reporter", "eng_net"])
def test_run_and_approve_forbidden_for_non_analysts(api, world, who):
    inc = api.create()
    assert _run(api, inc, who).status_code == 403
    body = {"expected_version": inc["version"], "team_id": str(world["teams"]["net"])}
    assert api.post(f"/workflow/incidents/{inc['id']}/approve", who, body).status_code == 403


def test_approval_requires_review_and_reason_without_recommendation(api, world):
    inc = api.create()
    team = str(world["teams"]["net"])
    # not yet reviewed: lifecycle forbids assigning straight from this path
    ran = _run(api, inc).json()
    version = ran["incident"]["version"]
    no_reason = api.post(
        f"/workflow/incidents/{inc['id']}/approve",
        "analyst",
        {"expected_version": version, "team_id": team},
    )
    assert no_reason.status_code == 422
    ok = api.post(
        f"/workflow/incidents/{inc['id']}/approve",
        "analyst",
        {"expected_version": version, "team_id": team, "reason": "Clearly a network fault"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["incident"]["status"] == "ASSIGNED"
    assert ok.json()["approved"]["team_id"] == team


def test_approval_replay_does_not_duplicate(api, world, session_factory):
    inc = api.create()
    ran = _run(api, inc).json()
    body = {
        "expected_version": ran["incident"]["version"],
        "team_id": str(world["teams"]["net"]),
        "reason": "manual",
    }
    a = api.post(f"/workflow/incidents/{inc['id']}/approve", "analyst", body)
    b = api.post(f"/workflow/incidents/{inc['id']}/approve", "analyst", body)
    assert a.status_code == 200 and b.status_code == 200, b.text
    assert b.json()["reused"] is True
    with session_factory() as db:
        kinds = db.scalars(select(AuditEvent.event_type)).all()
        assert [str(k) for k in kinds].count("WORKFLOW_APPROVAL_COMPLETED") == 1


def test_audit_trail_records_workflow(api, world):
    inc = api.create()
    _run(api, inc)
    events = api.get(f"/incidents/{inc['id']}/audit", "analyst").json()
    text = str(events)
    assert "WORKFLOW_TRIAGE_COMPLETED" in text


def test_runs_listing_and_config(api, world):
    inc = api.create()
    _run(api, inc)
    assert len(api.get(f"/workflow/incidents/{inc['id']}/runs", "eng_net").json()) == 1
    assert api.get(f"/workflow/incidents/{inc['id']}/runs", "reporter").status_code == 403
    cfg = api.get("/workflow/config", "analyst").json()
    assert cfg["routing"]["enabled"] is False
    assert cfg["gemini"]["enabled"] is False
    assert "google_api_key" not in str(cfg).lower()


def _eligible_ml():
    def out(label, conf):
        return {
            "status": "OK",
            "available": True,
            "label": label,
            "confidence": conf,
            "confidence_kind": "retrieval_agreement",
            "provenance": "real",
            "is_demo": False,
        }

    return {
        "status": "OK",
        "is_demo": False,
        "outputs": {
            "category": out("Network", 0.97),
            "team": out("Network", 0.95),
            "priority": {"status": "OK", "available": True, "label": "P2"},
        },
    }


def test_routing_threshold_gate(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    get_settings.cache_clear()
    cfg = routing_policy.RoutingConfig.from_settings(get_settings())
    ok = routing_policy.evaluate(_eligible_ml(), cfg, team_resolvable=True, input_issues=[])
    assert ok["decision"] == "PROPOSE_ASSIGNMENT"
    assert ok["auto_assign"] is False and ok["human_approval_required"] is True

    low = _eligible_ml()
    low["outputs"]["team"]["confidence"] = 0.4
    r = routing_policy.evaluate(low, cfg, team_resolvable=True, input_issues=[])
    assert r["decision"] == "NEEDS_REVIEW"

    uncal = _eligible_ml()
    uncal["outputs"]["team"]["confidence_kind"] = "raw_margin"
    assert (
        routing_policy.evaluate(uncal, cfg, team_resolvable=True, input_issues=[])["decision"]
        == "NEEDS_REVIEW"
    )
    assert (
        routing_policy.evaluate(_eligible_ml(), cfg, team_resolvable=False, input_issues=[])[
            "decision"
        ]
        == "NEEDS_REVIEW"
    )
    get_settings.cache_clear()


def test_routing_disabled_by_default():
    get_settings.cache_clear()
    cfg = routing_policy.RoutingConfig.from_settings(get_settings())
    r = routing_policy.evaluate(_eligible_ml(), cfg, team_resolvable=True, input_issues=[])
    assert r["decision"] == "NEEDS_REVIEW" and "routing_disabled" in r["reasons"]


# ---- Gemini -------------------------------------------------------------------------------


class FakeClient:
    model_name = "fake-model"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
        self.sent = []

    def extract(self, system_prompt, user_content):
        self.calls += 1
        self.sent.append(user_content)
        o = self.outputs.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


@pytest.fixture(autouse=True)
def _reset_factory():
    yield
    llm_assist.set_client_factory(None)
    get_settings.cache_clear()


def _settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return get_settings()


def _assist(settings, **kw):
    args = dict(
        requested=True,
        consent=False,
        is_synthetic=True,
        settings=settings,
        sleep=lambda s: None,
    )
    args.update(kw)
    return llm_assist.assist("VPN down", "vpn fails for jane@corp.example", **args)


def test_gemini_not_requested_and_disabled(monkeypatch):
    s = _settings(monkeypatch)
    assert _assist(s, requested=False)["status"] == "NOT_REQUESTED"
    assert _assist(s)["status"] == "DISABLED"


def test_gemini_no_credentials_and_consent(monkeypatch):
    s = _settings(monkeypatch, GEMINI_ENABLED="true")
    assert _assist(s)["status"] == "NO_CREDENTIALS"
    s = _settings(monkeypatch, GEMINI_ENABLED="true", GOOGLE_API_KEY="dummy")
    assert _assist(s, is_synthetic=False, consent=False)["status"] == "CONSENT_REQUIRED"


def test_redaction_masks_sensitive_tokens():
    red, counts = llm_assist.redact("mail jane@corp.example from 10.1.2.3 see https://x.example/a")
    assert "jane@corp.example" not in red and "10.1.2.3" not in red and "https://" not in red
    assert sum(counts.values()) >= 3


def _use(client):
    llm_assist.set_client_factory(lambda settings: client)


def test_gemini_ok_redacts_and_labels_output(monkeypatch):
    s = _settings(monkeypatch, GEMINI_ENABLED="true", GOOGLE_API_KEY="dummy")
    client = FakeClient(
        [llm_assist.IncidentAssist(summary="VPN fails", missing_information=["OS"])]
    )
    _use(client)
    env = _assist(s)
    assert env["status"] == "OK" and env["source"] == "LLM"
    assert env["output"]["summary"] == "VPN fails"
    assert "jane@corp.example" not in client.sent[0]
    assert "confidence" not in env["output"]


def test_gemini_retries_then_succeeds_then_falls_back(monkeypatch):
    s = _settings(monkeypatch, GEMINI_ENABLED="true", GOOGLE_API_KEY="dummy")
    _use(FakeClient([RuntimeError("boom"), llm_assist.IncidentAssist(summary="ok")]))
    env = _assist(s)
    assert env["status"] == "OK" and env["attempts"] == 2
    _use(FakeClient([RuntimeError("a")] * 5))
    env = _assist(s)
    assert env["status"] == "ERROR" and env["output"] is None


def test_workflow_survives_gemini_failure_and_routing_ignores_it(api, world, monkeypatch):
    _settings(monkeypatch, GEMINI_ENABLED="true", GOOGLE_API_KEY="dummy")
    _use(FakeClient([RuntimeError("x")] * 5))
    inc = api.create()
    with_g = _run(api, inc, use_gemini=True, external_data_consent=True)
    assert with_g.status_code == 200, with_g.text
    assert with_g.json()["assist"]["status"] == "ERROR"
    inc2 = api.create(title="Other")
    plain = _run(api, inc2).json()
    assert with_g.json()["routing"]["decision"] == plain["routing"]["decision"]
    assert with_g.json()["routing"]["reasons"] == plain["routing"]["reasons"]
