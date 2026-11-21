import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent, Incident
from tests.conftest import new_id


def _assign(api, inc, team, who="analyst", **extra):
    body = {"expected_version": inc["version"], "team_id": str(team), **extra}
    return api.post(f"/incidents/{inc['id']}/assign", who, body)


def test_full_lifecycle_with_audit_trail(api, world):
    net, apps = world["teams"]["net"], world["teams"]["apps"]
    inc = api.create()
    assert inc["status"] == "NEW" and inc["version"] == 1

    r = api.post(f"/incidents/{inc['id']}/triage", "analyst", {"expected_version": 1})
    assert r.status_code == 200
    triage = r.json()
    assert triage["status"] == "NOT_READY" and triage["is_demo"] is False
    assert triage["incident"]["status"] == "NEEDS_REVIEW"
    pred = triage["incident"]["latest_prediction"]
    assert pred["status"] == "NOT_READY"
    assert pred["predicted_team_id"] is None and pred["confidence"] is None
    assert pred["predicted_category"] is None and pred["predicted_priority"] is None
    # a recommendation is not an approved decision
    assert triage["incident"]["current_assignment"] is None
    assert triage["incident"]["approved_priority"] is None

    r = _assign(api, triage["incident"], net, priority="P2", category="Network")
    assert r.status_code == 200, r.text
    assigned = r.json()
    assert assigned["status"] == "ASSIGNED"
    assert assigned["approved_priority"] == "P2"
    assert assigned["current_assignment"]["team_id"] == str(net)

    r = api.post(
        f"/incidents/{inc['id']}/accept", "eng_net", {"expected_version": assigned["version"]}
    )
    assert r.status_code == 200 and r.json()["status"] == "ACCEPTED"
    accepted = r.json()
    assert accepted["current_assignment"]["accepted_by"] == str(world["users"]["eng_net"])

    r = api.post(
        f"/incidents/{inc['id']}/override",
        "analyst",
        {
            "expected_version": accepted["version"],
            "team_id": str(apps),
            "reason": "Actually an application bug",
        },
    )
    assert r.status_code == 200, r.text
    over = r.json()
    assert over["status"] == "REASSIGNED"
    assert over["current_assignment"]["team_id"] == str(apps)
    assert over["current_assignment"]["is_override"] is True

    r = api.post(
        f"/incidents/{inc['id']}/accept", "eng_apps", {"expected_version": over["version"]}
    )
    assert r.status_code == 200 and r.json()["status"] == "ACCEPTED"

    events = api.get(f"/incidents/{inc['id']}/audit", "analyst").json()["items"]
    assert [e["event_type"] for e in events] == [
        "INCIDENT_CREATED",
        "TRIAGE_REQUESTED",
        "TRIAGE_NOT_READY",
        "INCIDENT_ASSIGNED",
        "INCIDENT_ACCEPTED",
        "ASSIGNMENT_OVERRIDDEN",
        "INCIDENT_ACCEPTED",
    ]
    override_event = events[5]
    assert override_event["actor_id"] == str(world["users"]["analyst"])
    assert override_event["details"]["reason"] == "Actually an application bug"
    assert (
        override_event["from_status"] == "ACCEPTED" and override_event["to_status"] == "REASSIGNED"
    )


def test_assign_directly_from_new(api, world):
    inc = api.create()
    r = _assign(api, inc, world["teams"]["net"])
    assert r.status_code == 200 and r.json()["status"] == "ASSIGNED"


@pytest.mark.parametrize("who", ["analyst", "admin"])
def test_invalid_transitions_rejected(api, world, who):
    net, apps = world["teams"]["net"], world["teams"]["apps"]
    inc = api.create()
    # cannot accept or override before assignment
    r = api.post(f"/incidents/{inc['id']}/accept", "admin", {"expected_version": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    r = api.post(
        f"/incidents/{inc['id']}/override",
        who,
        {"expected_version": 1, "team_id": str(net), "reason": "because"},
    )
    assert r.status_code == 409

    cur = _assign(api, inc, net, who=who).json()
    # cannot re-assign (must override), re-triage, or accept twice
    assert _assign(api, cur, apps, who=who).status_code == 409
    r = api.post(f"/incidents/{inc['id']}/triage", who, {"expected_version": cur["version"]})
    assert r.status_code == 409
    acc = api.post(
        f"/incidents/{inc['id']}/accept", "admin", {"expected_version": cur["version"]}
    ).json()
    r = api.post(f"/incidents/{inc['id']}/accept", "admin", {"expected_version": acc["version"]})
    assert r.status_code == 409


def test_override_must_change_team_and_have_reason(api, world):
    net = world["teams"]["net"]
    cur = _assign(api, api.create(), net).json()
    path = f"/incidents/{cur['id']}/override"
    r = api.post(
        path,
        "analyst",
        {"expected_version": cur["version"], "team_id": str(net), "reason": "same team"},
    )
    assert r.status_code == 422
    r = api.post(
        path,
        "analyst",
        {"expected_version": cur["version"], "team_id": str(world["teams"]["apps"])},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_team_rejected(api):
    r = _assign(api, api.create(), new_id())
    assert r.status_code == 422


def test_stale_version_rejected_and_state_unchanged(api, world):
    inc = api.create()
    net, apps = world["teams"]["net"], world["teams"]["apps"]
    assert _assign(api, inc, net).status_code == 200
    # second analyst action based on the original (stale) version
    r = _assign(api, inc, apps, who="admin")
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "STALE_VERSION"
    assert body["details"] == {"expected_version": 1, "current_version": 2}
    now = api.get(f"/incidents/{inc['id']}", "analyst").json()
    assert now["current_assignment"]["team_id"] == str(net)
    # stale accept too
    r = api.post(f"/incidents/{inc['id']}/accept", "eng_net", {"expected_version": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"


def test_concurrent_update_blocked_by_db_version_check(session_factory, api, world):
    """Two sessions load the same row; the second flush must fail (version_id_col)."""
    from sqlalchemy.orm.exc import StaleDataError

    inc = api.create()
    with session_factory() as a, session_factory() as b:
        ia, ib = a.get(Incident, __import__("uuid").UUID(inc["id"])), b.get(
            Incident, __import__("uuid").UUID(inc["id"])
        )
        ia.approved_category = "A"
        a.commit()
        ib.approved_category = "B"
        with pytest.raises(StaleDataError):
            b.commit()


def test_original_text_is_immutable(session_factory, api):
    inc = api.create(title="Original title", description="Original description text.")
    import uuid

    with session_factory() as db:
        row = db.get(Incident, uuid.UUID(inc["id"]))
        row.description = "tampered"
        with pytest.raises(ValueError, match="immutable"):
            db.commit()
    # raw SQL bypassing the ORM is blocked by the DB trigger
    with session_factory() as db, pytest.raises(DBAPIError):
        db.execute(
            text("UPDATE incidents SET title='x' WHERE id=:i"), {"i": inc["id"].replace("-", "")}
        )
        db.commit()
    stored = api.get(f"/incidents/{inc['id']}", "reporter").json()
    assert stored["title"] == "Original title"


def test_audit_events_are_append_only(session_factory, api):
    api.create()
    with session_factory() as db:
        ev = db.query(AuditEvent).first()
        ev.event_type = "X"
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
    with session_factory() as db, pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_events"))
        db.commit()


def test_feedback_labels_recorded_for_human_decisions(session_factory, api, world):
    from app.models import FeedbackLabel

    _assign(api, api.create(), world["teams"]["net"], priority="P1", category="Network")
    with session_factory() as db:
        labels = {(lb.label_type.value, lb.value) for lb in db.query(FeedbackLabel)}
    assert labels == {
        ("TEAM", str(world["teams"]["net"])),
        ("PRIORITY", "P1"),
        ("CATEGORY", "Network"),
    }


def test_model_metrics_not_ready_and_no_invented_numbers(api):
    r = api.get("/models/metrics", "analyst")
    assert r.status_code == 200
    assert r.json() == {
        "status": "NOT_READY",
        "message": "No trained model has been registered (Phase 1). No metrics are available.",
        "models": [],
    }
    overview = api.get("/analytics/overview", "analyst").json()
    assert overview["model_status"] == "NOT_READY"


def test_analytics_counts(api, world):
    a, _ = api.create(), api.create()
    _assign(api, a, world["teams"]["net"], priority="P2")
    o = api.get("/analytics/overview", "admin").json()
    assert o["total_incidents"] == 2
    assert o["by_status"]["ASSIGNED"] == 1 and o["by_status"]["NEW"] == 1
    assert o["by_assigned_team"] == {"Network": 1}
    assert o["unassigned"] == 1
