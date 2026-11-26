"""Retrieval-augmented triage (Chroma + Gemini decision). Fully offline: embeddings and the LLM are fakes."""

from app.core.config import get_settings
from app.services import rag_service
from tests.fake_rag import LABELLED, rag, records  # noqa: F401
from tests.test_servicenow import BASE, mock_mode  # noqa: F401

QUERY = {"title": "VPN connection drops", "description": "vpn wifi router connection drops often"}


def _triage(api, inc, who="analyst", **extra):
    return api.post(
        f"/incidents/{inc['id']}/triage", who, {"expected_version": inc["version"], **extra}
    )


def test_without_index_triage_is_not_ready_but_priority_policy_still_applies(api):
    inc = api.create(**QUERY)
    body = _triage(api, inc, impact=1, urgency=2).json()
    assert body["status"] == "NOT_READY"
    assert body["outputs"]["team"]["available"] is False
    assert "gemini_disabled_or_not_configured" in body["outputs"]["team"]["reason"]
    assert body["outputs"]["priority"]["label"] == "P2"
    assert body["incident"]["status"] == "NEEDS_REVIEW"


def test_index_too_small_is_unavailable(api, monkeypatch):
    from tests.fake_rag import FakeEmbedder

    rag_service.set_factories(lambda s: FakeEmbedder(), lambda s: None)
    rag_service.build_index(records()[:5])
    body = _triage(api, api.create(**QUERY)).json()
    assert body["status"] == "NOT_READY"
    assert "index_too_small" in body["outputs"]["team"]["reason"]


def test_recommendation_comes_from_retrieval_and_stays_a_recommendation(
    api, world, rag
):  # noqa: F811
    inc = api.create(**QUERY)
    body = _triage(api, inc, impact=2, urgency=2).json()
    assert body["status"] == "MODEL" and body["is_demo"] is False
    team, cat = body["outputs"]["team"], body["outputs"]["category"]
    assert team["label"] == "Network" and cat["label"] == "network"
    assert team["confidence_kind"] == "retrieval_agreement"
    assert 0 < team["confidence"] <= 1
    assert team["decided_by"] == "gemini" and team["rationale"]
    assert team["similar_incidents"] and all(n["team"] for n in team["similar_incidents"])
    assert body["outputs"]["priority"]["label"] == "P3"
    after = body["incident"]
    assert after["status"] == "NEEDS_REVIEW" and after["current_assignment"] is None
    assert after["latest_prediction"]["predicted_team_id"] == str(world["teams"]["net"])
    kinds = [
        e["event_type"] for e in api.get(f"/incidents/{inc['id']}/audit", "analyst").json()["items"]
    ]
    assert "TRIAGE_RECOMMENDED" in kinds


def test_gemini_failure_falls_back_to_neighbour_vote(api, rag):  # noqa: F811
    rag["decider"].fail = True
    team = _triage(api, api.create(**QUERY)).json()["outputs"]["team"]
    assert team["available"] and team["label"] == "Network"
    assert team["decided_by"] == "retrieval_vote"
    assert "unavailable" in team["rationale"]


def test_llm_answer_outside_the_indexed_labels_is_ignored(api, rag):  # noqa: F811
    rag["decider"].team = "Made Up Team"
    team = _triage(api, api.create(**QUERY)).json()["outputs"]["team"]
    assert team["label"] == "Network" and team["decided_by"] == "retrieval_vote"


def test_text_unlike_the_index_gives_no_answer(api, rag):  # noqa: F811
    inc = api.create(title="zzqx wvvk plorb", description="qqqq xxxxzz yyyyww unknown words only")
    body = _triage(api, inc).json()
    assert body["status"] == "NOT_READY"
    assert "no_sufficiently_similar_incidents" in body["outputs"]["team"]["reason"]
    assert body["confidence"] is None


def test_only_redacted_text_leaves_the_system(api, rag):  # noqa: F811
    inc = api.create(
        title="VPN connection drops",
        description="vpn wifi router connection drops, contact jane.doe@corp.example from 10.1.2.3",
    )
    _triage(api, inc)
    sent = " ".join(rag["decider"].seen)
    assert "jane.doe@corp.example" not in sent and "10.1.2.3" not in sent
    assert "[EMAIL]" in sent


def test_ticket_is_never_its_own_neighbour(rag):  # noqa: F811
    first = records()[0]
    res = rag_service.predict(
        first["title"], first["description"], exclude_id=first["sys_id"], settings=get_settings()
    )
    numbers = [n["number"] for n in res["outputs"]["team"]["similar_incidents"]]
    assert first["number"] not in numbers


def test_reporter_cannot_trigger_triage_and_bad_inputs_rejected(api, rag):  # noqa: F811
    inc = api.create(**QUERY)
    assert _triage(api, inc, who="reporter").status_code == 403
    assert _triage(api, inc, impact=9, urgency=1).status_code == 422
    undefined = _triage(api, inc, impact=1, urgency=3).json()
    assert undefined["outputs"]["priority"]["available"] is False


def test_metrics_reports_the_registered_retrieval_version(api, rag):  # noqa: F811
    body = api.get("/models/metrics", "analyst").json()
    assert body["status"] == "AVAILABLE"
    assert body["models"][0]["name"] == rag_service.RAG_KEY
    assert body["models"][0]["version"].endswith(f"@n{len(LABELLED)}")


def test_index_is_idempotent(rag):  # noqa: F811
    again = rag_service.build_index(records())
    assert again["index_size"] == len(LABELLED)


def test_rag_endpoints_are_role_restricted_and_index_from_servicenow(
    api, world, mock_mode, rag
):  # noqa: F811
    assert api.get(f"{BASE}/rag", "analyst").json()["index_size"] == len(LABELLED)
    assert api.get(f"{BASE}/rag", "reporter").status_code == 403
    assert api.post(f"{BASE}/rag/index", "analyst", {}).status_code == 403
    done = api.post(f"{BASE}/rag/index", "admin", {})
    assert done.status_code == 200, done.text
    assert done.json()["source_incidents"] == 3  # fake instance: only one record has a group
    assert mock_mode.patch_calls == []


def test_routing_proposes_only_above_threshold(api, world, rag, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    get_settings.cache_clear()
    inc = api.create(**QUERY)
    r = api.post(
        f"/workflow/incidents/{inc['id']}/run",
        "analyst",
        {"expected_version": inc["version"], "impact": 2, "urgency": 2},
    ).json()
    assert r["routing"]["decision"] == "PROPOSE_ASSIGNMENT", r["routing"]
    assert r["routing"]["auto_assign"] is False

    monkeypatch.setenv("ROUTING_THRESHOLD_TEAM", "1.0")
    monkeypatch.setenv("ROUTING_THRESHOLD_CATEGORY", "1.0")
    get_settings.cache_clear()
    rag["decider"].team = "Apps"  # disagrees with the neighbourhood -> low agreement
    inc2 = api.create(title="VPN connection drops again", description=QUERY["description"])
    r2 = api.post(
        f"/workflow/incidents/{inc2['id']}/run",
        "analyst",
        {"expected_version": inc2["version"], "impact": 2, "urgency": 2},
    ).json()
    assert r2["routing"]["decision"] == "NEEDS_REVIEW"
    assert any("below_threshold" in x for x in r2["routing"]["reasons"])
    stored = api.get(f"/incidents/{inc2['id']}", "analyst").json()
    assert stored["current_assignment"] is None
