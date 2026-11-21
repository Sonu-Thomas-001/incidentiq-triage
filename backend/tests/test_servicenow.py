"""ServiceNow adapter: offline behaviour, HTTP client failure modes, import and approved sync."""

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.errors import UpstreamError, ValidationFailure
from app.integrations.servicenow import service as sn
from app.integrations.servicenow.client import (
    HttpServiceNowClient,
    normalize_instance_url,
    sanitize_query_text,
)
from app.integrations.servicenow.mock import GROUPS, INCIDENTS
from app.models import AuditEvent, Incident, SyncRecord

INC1 = INCIDENTS[0]["sys_id"]  # state New
INC_CLOSED = INCIDENTS[2]["sys_id"]
GRP_NET = GROUPS[0]["sys_id"]
BASE = "/integrations/servicenow"


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    monkeypatch.setenv("SERVICENOW_MODE", "mock")
    get_settings.cache_clear()
    client = sn.reset_mock()
    yield client
    sn.set_client_factory(None)
    get_settings.cache_clear()


def _set_mode(monkeypatch, mode):
    monkeypatch.setenv("SERVICENOW_MODE", mode)
    get_settings.cache_clear()


def _import(api, sys_id=INC1, who="analyst"):
    return api.post(f"{BASE}/import", who, {"sys_id": sys_id})


def _assigned_imported(api, world, group=GRP_NET):
    """Import, map the net team, then approve an assignment through the workflow."""
    imp = _import(api)
    assert imp.status_code == 200, imp.text
    iid = imp.json()["incident_id"]
    team = str(world["teams"]["net"])
    assert (
        api.post(
            f"{BASE}/team-mappings", "admin", {"team_id": team, "servicenow_group_sys_id": group}
        ).status_code
        == 200
    )
    inc = api.get(f"/incidents/{iid}", "analyst").json()
    ran = api.post(
        f"/workflow/incidents/{iid}/run", "analyst", {"expected_version": inc["version"]}
    ).json()
    done = api.post(
        f"/workflow/incidents/{iid}/approve",
        "analyst",
        {
            "expected_version": ran["incident"]["version"],
            "team_id": team,
            "reason": "network fault",
        },
    )
    assert done.status_code == 200, done.text
    return iid


def _preview(api, iid):
    r = api.post(f"{BASE}/incidents/{iid}/sync/preview", "analyst", {})
    assert r.status_code == 200, r.text
    return r.json()


def _approve(api, iid, pv, **over):
    body = {
        "preview_id": pv["sync_id"],
        "confirm": True,
        "confirm_instance_host": pv["target_instance_host"],
    }
    body.update(over)
    return api.post(f"{BASE}/incidents/{iid}/sync/approve", "analyst", body)


# ---- offline / disabled ----------------------------------------------------------------


def test_disabled_by_default_runs_offline(api, world):
    h = api.get(f"{BASE}/health", "analyst")
    assert h.status_code == 200
    assert h.json()["enabled"] is False and h.json()["reachable"] is None
    for path in ("/incidents", "/assignment-groups"):
        r = api.get(BASE + path, "analyst")
        assert r.status_code == 503 and r.json()["error"]["code"] == "INTEGRATION_DISABLED"
    assert _import(api).status_code == 503
    # the rest of the application is unaffected
    assert api.create()["status"] == "NEW"


def test_enabled_without_credentials_reports_unreachable_not_crash(api, world, monkeypatch):
    monkeypatch.setenv("SERVICENOW_ENABLED", "true")
    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://dev1.service-now.com")
    get_settings.cache_clear()
    h = api.get(f"{BASE}/health", "analyst").json()
    assert h["enabled"] is True and h["credentials_configured"] is False
    assert h["reachable"] is False
    assert "password" not in str(h).lower().replace("credentials", "")
    get_settings.cache_clear()


@pytest.mark.parametrize("who", ["reporter", "eng_net"])
def test_integration_endpoints_are_role_restricted(api, world, who):
    assert api.get(f"{BASE}/health", who).status_code == 403
    assert _import(api, who=who).status_code == 403
    iid = api.create()["id"]
    assert api.post(f"{BASE}/incidents/{iid}/sync/preview", who, {}).status_code == 403


def test_team_mapping_is_admin_only(api, world):
    body = {"team_id": str(world["teams"]["net"]), "servicenow_group_sys_id": GRP_NET}
    assert api.post(f"{BASE}/team-mappings", "analyst", body).status_code == 403
    assert api.post(f"{BASE}/team-mappings", "admin", body).status_code == 200
    other = {"team_id": str(world["teams"]["apps"]), "servicenow_group_sys_id": GRP_NET}
    assert api.post(f"{BASE}/team-mappings", "admin", other).status_code == 409
    bad = {"team_id": str(world["teams"]["apps"]), "servicenow_group_sys_id": "z" * 32}
    assert api.post(f"{BASE}/team-mappings", "admin", bad).status_code == 422


# ---- reads / import --------------------------------------------------------------------


def test_list_get_and_pagination(api, world, mock_mode):
    page = api.get(f"{BASE}/incidents", "analyst", page=1, page_size=2).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["state_label"] == "New"
    assert page["items"][1]["assignment_group_sys_id"] == GROUPS[2]["sys_id"]
    assert len(api.get(f"{BASE}/incidents", "analyst", page=2, page_size=2).json()["items"]) == 1
    assert api.get(f"{BASE}/incidents", "analyst", state="1").json()["total"] == 1
    assert api.get(f"{BASE}/incidents/{INC1}", "analyst").json()["number"] == "INC9000001"
    assert api.get(f"{BASE}/incidents/not-a-sys-id", "analyst").status_code == 422
    missing = api.get(f"{BASE}/incidents/{'0' * 32}", "analyst")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "UPSTREAM_NOT_FOUND"
    assert api.get(f"{BASE}/assignment-groups", "analyst").json()["total"] == 3
    assert api.get(f"{BASE}/health", "analyst").json()["reachable"] is True


def test_import_is_idempotent_and_keeps_snapshot_separate_from_decisions(
    api, world, mock_mode, session_factory
):
    first = _import(api).json()
    second = _import(api).json()
    assert first["created"] is True and second["created"] is False
    assert first["incident_id"] == second["incident_id"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == 1
        inc = db.scalar(select(Incident))
        assert inc.status.value == "NEW" and inc.is_synthetic is True
        assert inc.approved_priority is None  # SN priority is a snapshot, not a decision
        assert inc.external_snapshot["snapshot_priority"] == "P3"
        events = [e.event_type for e in db.scalars(select(AuditEvent))]
        assert events.count("SERVICENOW_INCIDENT_IMPORTED") == 1


def test_incident_response_exposes_external_reference(api, world, mock_mode):
    inc_id = _import(api).json()["incident_id"]
    body = api.get(f"/incidents/{inc_id}", "analyst").json()
    assert body["external_system"] == "servicenow"
    assert body["external_number"] == "INC9000001"


def test_http_client_is_reused_for_same_settings(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("SERVICENOW_INSTANCE_URL", "https://dev1.service-now.com")
    monkeypatch.setenv("SERVICENOW_MODE", "read_only")
    monkeypatch.setenv("SERVICENOW_USERNAME", "svc-test")
    monkeypatch.setenv("SERVICENOW_PASSWORD", "not-a-real-secret")
    get_settings.cache_clear()
    settings = get_settings()
    assert sn._http_client(settings) is sn._http_client(settings)
    get_settings.cache_clear()


def test_import_refuses_closed_records(api, world, mock_mode):
    r = _import(api, INC_CLOSED)
    assert r.status_code == 409 and "not importable" in r.json()["error"]["message"]


def test_imported_impact_urgency_feed_priority_policy(api, world, mock_mode):
    iid = _import(api).json()["incident_id"]
    inc = api.get(f"/incidents/{iid}", "analyst").json()
    run = api.post(
        f"/workflow/incidents/{iid}/run", "analyst", {"expected_version": inc["version"]}
    ).json()
    assert run["priority_inputs"]["impact"]["value"] == 2
    assert run["ml"]["outputs"]["priority"]["label"] == "P3"


# ---- sync gates ------------------------------------------------------------------------


def test_preview_requires_mapping_and_assignment(api, world, mock_mode):
    iid = _import(api).json()["incident_id"]
    assert api.post(f"{BASE}/incidents/{iid}/sync/preview", "analyst", {}).status_code == 409
    local = api.create()["id"]  # not a ServiceNow incident
    assert api.post(f"{BASE}/incidents/{local}/sync/preview", "analyst", {}).status_code == 422


def test_preview_does_not_write_and_shows_exact_change(api, world, mock_mode):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    assert mock_mode.patch_calls == []
    assert pv["status"] == "PREVIEWED"
    assert pv["target_instance_host"] == "mock.service-now.com"
    assert pv["external_number"] == "INC9000001"
    assert pv["field_changes"] == {"assignment_group": {"from": None, "to": GRP_NET}}
    assert pv["requires"]["confirm"] is True
    assert _preview(api, iid)["sync_id"] == pv["sync_id"]  # re-preview reuses the record


def test_approve_requires_confirmation_and_matching_host(api, world, mock_mode):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    assert _approve(api, iid, pv, confirm=False).status_code == 422
    assert _approve(api, iid, pv, confirm_instance_host="other.service-now.com").status_code == 422
    assert mock_mode.patch_calls == []


def test_read_only_mode_blocks_writes(api, world, mock_mode, monkeypatch):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)  # previews are reads and remain allowed
    _set_mode(monkeypatch, "read_only")
    sn.set_client_factory(lambda s: mock_mode)
    r = _approve(api, iid, pv)
    assert r.status_code == 409 and r.json()["error"]["code"] == "WRITE_DISABLED"
    assert mock_mode.patch_calls == []


def test_approved_sync_writes_once_and_replays_safely(api, world, mock_mode, session_factory):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    ok = _approve(api, iid, pv)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "SUCCEEDED" and ok.json()["result"]["already_applied"] is False
    again = _approve(api, iid, pv)
    assert again.status_code == 200 and again.json()["status"] == "SUCCEEDED"
    assert len(mock_mode.patch_calls) == 1  # duplicate prevented
    assert mock_mode.patch_calls[0] == (INC1, GRP_NET)
    hist = api.get(f"{BASE}/incidents/{iid}/sync", "eng_net").json()
    assert len(hist) == 1 and hist[0]["status"] == "SUCCEEDED"
    with session_factory() as db:
        events = [e.event_type for e in db.scalars(select(AuditEvent))]
        assert events.count("SERVICENOW_SYNC_SUCCEEDED") == 1
        assert db.scalar(select(func.count()).select_from(SyncRecord)) == 1


def test_inference_never_writes_to_servicenow(api, world, mock_mode):
    iid = _import(api).json()["incident_id"]
    inc = api.get(f"/incidents/{iid}", "analyst").json()
    api.post(f"/workflow/incidents/{iid}/run", "analyst", {"expected_version": inc["version"]})
    api.post(f"/incidents/{iid}/triage", "analyst", {"expected_version": inc["version"]})
    assert mock_mode.patch_calls == []


def test_failed_sync_keeps_local_approval_and_can_be_retried(api, world, mock_mode):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    mock_mode.fail_next_patch = UpstreamError(
        "ServiceNow request timed out", status_code=504, code="UPSTREAM_TIMEOUT"
    )
    r = _approve(api, iid, pv)
    assert r.status_code == 504 and r.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    inc = api.get(f"/incidents/{iid}", "analyst").json()
    assert inc["status"] == "ASSIGNED" and inc["current_assignment"]["status"] == "ASSIGNED"
    hist = api.get(f"{BASE}/incidents/{iid}/sync", "analyst").json()
    assert hist[0]["status"] == "FAILED" and "UPSTREAM_TIMEOUT" in hist[0]["last_error"]
    retry = _approve(api, iid, pv)
    assert retry.status_code == 200 and retry.json()["status"] == "SUCCEEDED"
    assert retry.json()["attempts"] == 2
    assert len(mock_mode.patch_calls) == 1


def test_remote_change_since_preview_blocks_write(api, world, mock_mode):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    mock_mode.incidents[0]["sys_updated_on"] = "2026-03-03 03:03:03"  # edited remotely
    r = _approve(api, iid, pv)
    assert r.status_code == 409 and r.json()["error"]["details"]["code"] == "REMOTE_CHANGED"
    assert mock_mode.patch_calls == []
    pv2 = _preview(api, iid)
    assert pv2["sync_id"] == pv["sync_id"] and pv2["status"] == "PREVIEWED"
    assert _approve(api, iid, pv2).status_code == 200


def test_already_applied_group_skips_patch(api, world, mock_mode):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    mock_mode.incidents[0]["assignment_group"] = {"value": GRP_NET}
    r = _approve(api, iid, pv)
    assert r.status_code == 200 and r.json()["result"]["already_applied"] is True
    assert mock_mode.patch_calls == []


def test_new_assignment_needs_new_sync(api, world, mock_mode):
    iid = _assigned_imported(api, world)
    pv = _preview(api, iid)
    inc = api.get(f"/incidents/{iid}", "analyst").json()
    api.post(
        f"/incidents/{iid}/override",
        "analyst",
        {
            "expected_version": inc["version"],
            "team_id": str(world["teams"]["apps"]),
            "reason": "actually an application issue",
        },
    )
    r = _approve(api, iid, pv)
    assert r.status_code == 409  # preview belongs to a superseded assignment
    assert mock_mode.patch_calls == []


# ---- HTTP client (httpx.MockTransport) --------------------------------------------------


def _http(handler, **env):
    s = Settings(
        servicenow_enabled=True,
        servicenow_instance_url="https://dev1.service-now.com",
        servicenow_username="svc_iiq",
        servicenow_password="not-a-real-secret",
        servicenow_max_retries=2,
        **env,
    )
    sleeps: list[float] = []
    c = HttpServiceNowClient(s, transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return c, sleeps


def test_http_client_pagination_params_and_total():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(dict(req.url.params))
        assert req.headers["authorization"].startswith("Basic ")
        return httpx.Response(
            200, json={"result": [{"sys_id": "a" * 32}]}, headers={"X-Total-Count": "41"}
        )

    c, _ = _http(handler)
    rows, total = c.list_incidents(limit=10, offset=20, state="1", query="vpn^evil", group=None)
    assert total == 41 and rows[0]["sys_id"] == "a" * 32
    assert seen["sysparm_limit"] == "10" and seen["sysparm_offset"] == "20"
    assert "vpn evil" in seen["sysparm_query"] and "^evil" not in seen["sysparm_query"]


@pytest.mark.parametrize(
    ("status", "code", "http"),
    [
        (401, "UPSTREAM_AUTH_FAILED", 502),
        (403, "UPSTREAM_FORBIDDEN", 502),
        (404, "UPSTREAM_NOT_FOUND", 404),
        (500, "UPSTREAM_ERROR", 502),
    ],
)
def test_http_client_maps_errors(status, code, http):
    c, sleeps = _http(lambda req: httpx.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(UpstreamError) as ei:
        c.get_incident("b" * 32)
    assert ei.value.code == code and ei.value.status_code == http and sleeps == []


def test_http_client_retries_transient_then_succeeds():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"result": {"sys_id": "c" * 32}})

    c, sleeps = _http(handler)
    assert c.get_incident("c" * 32)["sys_id"] == "c" * 32
    assert len(calls) == 3 and len(sleeps) == 2


def test_http_client_rate_limit_and_timeout():
    c, sleeps = _http(lambda r: httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(UpstreamError) as ei:
        c.get_incident("d" * 32)
    assert ei.value.status_code == 429 and ei.value.retry_after == 120 and sleeps == []

    short = []

    def limited(req):
        short.append(1)
        if len(short) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"result": {}})

    c, sleeps = _http(limited)
    c.get_incident("d" * 32)
    assert sleeps == [2.0]

    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)

    c, sleeps = _http(boom)
    with pytest.raises(UpstreamError) as ei:
        c.get_incident("e" * 32)
    assert ei.value.status_code == 504 and len(sleeps) == 2


def test_http_patch_sends_only_assignment_group():
    sent = {}

    def handler(req: httpx.Request):
        sent["method"], sent["body"] = req.method, req.content
        return httpx.Response(200, json={"result": {"assignment_group": {"value": "f" * 32}}})

    c, _ = _http(handler)
    out = c.update_assignment_group("a" * 32, "f" * 32)
    assert (
        sent["method"] == "PATCH" and sent["body"] == b'{"assignment_group":"' + b"f" * 32 + b'"}'
    )
    assert out["assignment_group"]["value"] == "f" * 32


def test_instance_url_guard():
    assert normalize_instance_url("https://Dev1.service-now.com/") == "https://dev1.service-now.com"
    for bad in (
        "http://dev1.service-now.com",
        "https://evil.example.com",
        "https://u:p@dev1.service-now.com",
        "https://dev1.service-now.com.evil.io",
    ):
        with pytest.raises(ValidationFailure):
            normalize_instance_url(bad)
    assert sanitize_query_text("a^b\nc") == "a b c"
