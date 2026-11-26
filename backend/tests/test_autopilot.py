"""Autopilot: pickup of new unassigned ServiceNow tickets. Offline, fake ServiceNow client."""

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditEvent, Incident
from app.services import autopilot
from tests.test_servicenow import BASE, INC1, mock_mode  # noqa: F401


@pytest.fixture
def cycle(session_factory):
    def run():
        with session_factory() as db:
            return autopilot.run_cycle(db)

    return run


def test_skipped_when_servicenow_disabled(cycle):
    assert "disabled" in cycle()["skipped"]


def test_picks_up_only_new_unassigned_and_never_writes(
    cycle, mock_mode, session_factory
):  # noqa: F811
    res = cycle()
    # fake data: INC1 is New+unassigned; others are assigned or closed
    assert [p["number"] for p in res["processed"]] == ["INC9000001"]
    assert res["processed"][0]["action"] == "triaged"
    assert res["errors"] == []
    assert mock_mode.patch_calls == []
    with session_factory() as db:
        inc = db.scalar(select(Incident).where(Incident.external_sys_id == INC1))
        assert inc is not None and str(inc.status) in {
            "NEEDS_REVIEW",
            "IncidentStatus.NEEDS_REVIEW",
        }
    again = cycle()
    assert again["processed"][0]["action"] == "already_imported"


def test_auto_assign_only_when_enabled_and_policy_passes(
    cycle, mock_mode, world, session_factory, monkeypatch  # noqa: F811
):
    from app.workflow import service as workflow

    real = workflow.run_triage
    team = str(world["teams"]["net"])

    def fake_run(*a, **k):
        data = real(*a, **k)
        data["routing"] = {"decision": "PROPOSE_ASSIGNMENT", "thresholds": {}, "checks": {}}
        data["review"] = {"recommended_team_id": team, "recommended_priority": "P3"}
        return data

    monkeypatch.setattr(workflow, "run_triage", fake_run)

    # auto-assign off: stays for human review
    assert cycle()["processed"][0]["action"] == "triaged"

    # on: assigned locally, audited, still no ServiceNow write
    monkeypatch.setenv("AUTOPILOT_AUTO_ASSIGN", "true")
    get_settings.cache_clear()
    mock_mode.incidents[0]["sys_id"] = "c" * 32
    mock_mode.incidents[0]["number"] = "INC9000099"
    res = cycle()
    assert res["errors"] == [], res
    assert res["processed"][0]["action"] == "auto_assigned"
    assert mock_mode.patch_calls == []
    with session_factory() as db:
        inc = db.scalar(select(Incident).where(Incident.external_sys_id == "c" * 32))
        assert str(inc.status).endswith("ASSIGNED")
        kinds = [str(e.event_type) for e in db.scalars(select(AuditEvent))]
        assert any("AUTOPILOT_AUTO_ASSIGNED" in k for k in kinds)


def test_status_and_run_endpoints_are_role_restricted(api, world, mock_mode):  # noqa: F811
    assert api.get(f"{BASE}/autopilot", "analyst").status_code == 200
    assert api.get(f"{BASE}/autopilot", "reporter").status_code == 403
    assert api.post(f"{BASE}/autopilot/run", "analyst", {}).status_code == 403
    assert api.post(f"{BASE}/autopilot/run", "admin", {}).status_code == 200
