import pytest

from tests.conftest import new_id


@pytest.fixture
def assigned(api, world):
    inc = api.create()
    r = api.post(
        f"/incidents/{inc['id']}/assign",
        "analyst",
        {"expected_version": 1, "team_id": str(world["teams"]["net"])},
    )
    return r.json()


@pytest.mark.parametrize("who", ["reporter", "eng_net"])
def test_only_analyst_or_admin_can_triage_assign_override(api, world, assigned, who):
    inc = api.create()
    base = {"expected_version": 1}
    team = {"team_id": str(world["teams"]["apps"])}
    assert api.post(f"/incidents/{inc['id']}/triage", who, base).status_code == 403
    assert api.post(f"/incidents/{inc['id']}/assign", who, {**base, **team}).status_code == 403
    r = api.post(
        f"/incidents/{assigned['id']}/override",
        who,
        {"expected_version": assigned["version"], **team, "reason": "nope nope"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"
    # unchanged
    assert api.get(f"/incidents/{assigned['id']}", "admin").json()["status"] == "ASSIGNED"


@pytest.mark.parametrize("who", ["reporter", "analyst"])
def test_accept_requires_support_engineer_or_admin(api, assigned, who):
    r = api.post(
        f"/incidents/{assigned['id']}/accept", who, {"expected_version": assigned["version"]}
    )
    assert r.status_code == 403


def test_engineer_of_other_team_cannot_accept(api, assigned):
    r = api.post(
        f"/incidents/{assigned['id']}/accept", "eng_apps", {"expected_version": assigned["version"]}
    )
    assert r.status_code == 403
    assert api.get(f"/incidents/{assigned['id']}", "admin").json()["status"] == "ASSIGNED"


def test_admin_can_accept_any_team(api, assigned):
    r = api.post(
        f"/incidents/{assigned['id']}/accept", "admin", {"expected_version": assigned["version"]}
    )
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/analytics/overview", "/models/metrics"])
def test_analytics_and_metrics_restricted(api, path):
    assert api.get(path, "reporter").status_code == 403
    assert api.get(path, "eng_net").status_code == 403
    assert api.get(path, "analyst").status_code == 200
    assert api.get(path, "admin").status_code == 200


def test_audit_trail_restricted_to_staff(api, assigned):
    p = f"/incidents/{assigned['id']}/audit"
    assert api.get(p, "reporter").status_code == 403
    assert api.get(p, "eng_net").status_code == 200
    assert api.get(f"/incidents/{new_id()}/audit", "analyst").status_code == 404


def test_reporter_sees_only_own_incidents(api):
    mine = api.create("reporter")
    theirs = api.create("reporter2", title="Printer is broken")
    ids = [i["id"] for i in api.get("/incidents", "reporter").json()["items"]]
    assert ids == [mine["id"]]
    assert api.get(f"/incidents/{theirs['id']}", "reporter").status_code == 404
    # reporter cannot widen scope via filters
    r = api.get("/incidents", "reporter", reporter_id=theirs["reporter_id"])
    assert [i["id"] for i in r.json()["items"]] == [mine["id"]]
    assert len(api.get("/incidents", "analyst").json()["items"]) == 2


def test_reporter_does_not_see_predictions(api, world):
    inc = api.create()
    api.post(f"/incidents/{inc['id']}/triage", "analyst", {"expected_version": 1})
    assert api.get(f"/incidents/{inc['id']}", "reporter").json()["latest_prediction"] is None
    assert api.get(f"/incidents/{inc['id']}", "analyst").json()["latest_prediction"] is not None


def test_team_queue_scoping(api, world, assigned):
    net, apps = world["teams"]["net"], world["teams"]["apps"]
    q = api.get(f"/teams/{net}/queue", "eng_net")
    assert q.status_code == 200 and q.json()["total"] == 1
    assert api.get(f"/teams/{net}/queue", "eng_apps").status_code == 403
    assert api.get(f"/teams/{apps}/queue", "eng_apps").json()["total"] == 0
    assert api.get(f"/teams/{net}/queue", "analyst").json()["total"] == 1
    assert api.get(f"/teams/{net}/queue", "reporter").status_code == 403
    assert api.get(f"/teams/{new_id()}/queue", "admin").status_code == 404


def test_queue_follows_override(api, world, assigned):
    net, apps = world["teams"]["net"], world["teams"]["apps"]
    api.post(
        f"/incidents/{assigned['id']}/override",
        "analyst",
        {"expected_version": assigned["version"], "team_id": str(apps), "reason": "wrong team"},
    )
    assert api.get(f"/teams/{net}/queue", "eng_net").json()["total"] == 0
    assert api.get(f"/teams/{apps}/queue", "eng_apps").json()["total"] == 1


def test_missing_incident_404(api):
    assert api.get(f"/incidents/{new_id()}", "analyst").status_code == 404
    r = api.post(f"/incidents/{new_id()}/triage", "analyst", {"expected_version": 1})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
