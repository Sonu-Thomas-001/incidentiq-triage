import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_list_pagination_and_filters(api, world):
    for n in range(5):
        api.create(title=f"Issue number {n}")
    inc = api.create(title="VPN special case")
    api.post(
        f"/incidents/{inc['id']}/assign",
        "analyst",
        {"expected_version": 1, "team_id": str(world["teams"]["net"]), "priority": "P1"},
    )
    page = api.get("/incidents", "analyst", page=1, page_size=4).json()
    assert page["total"] == 6 and len(page["items"]) == 4 and page["page_size"] == 4
    assert len(api.get("/incidents", "analyst", page=2, page_size=4).json()["items"]) == 2
    assert api.get("/incidents", "analyst", status="ASSIGNED").json()["total"] == 1
    assert api.get("/incidents", "analyst", priority="P1").json()["total"] == 1
    assert api.get("/incidents", "analyst", team_id=str(world["teams"]["net"])).json()["total"] == 1
    assert api.get("/incidents", "analyst", q="vpn").json()["total"] == 1
    assert api.get("/incidents", "analyst", q="100%").json()["total"] == 0
    assert (
        api.get("/incidents", "analyst", created_from="2999-01-01T00:00:00Z").json()["total"] == 0
    )


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 1000}, {"status": "BOGUS"}, {"team_id": "not-a-uuid"}],
)
def test_invalid_query_params_give_structured_422(api, params):
    r = api.get("/incidents", "analyst", **params)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["details"] and err["request_id"]


@pytest.mark.parametrize(
    "body",
    [
        {"title": "ab", "description": "long enough description"},
        {"title": "valid title", "description": "short"},
        {"title": "   ", "description": "long enough description"},
        {"title": "valid title"},
    ],
)
def test_create_validation(api, client, body):
    r = client.post("/api/v1/incidents", json=body, headers=api.as_("reporter"))
    assert r.status_code == 422


def test_request_id_header_and_cors(client):
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    r = client.options(
        "/api/v1/incidents",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = client.options(
        "/api/v1/incidents",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in r.headers


def test_alembic_migration_creates_schema_and_triggers(tmp_path):
    db = tmp_path / "mig.db"
    env = {"DATABASE_URL": f"sqlite:///{db.as_posix()}", "PATH": ""}
    import os

    env = {**os.environ, **env}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {
        "users",
        "teams",
        "incidents",
        "assignments",
        "triage_predictions",
        "model_versions",
        "routing_rules",
        "audit_events",
        "feedback_labels",
    } <= tables
    triggers = {r[0] for r in con.execute("select name from sqlite_master where type='trigger'")}
    assert {"trg_incidents_text_immutable", "trg_audit_events_no_update"} <= triggers
    con.close()


def test_seed_is_idempotent_and_synthetic(tmp_path):
    import os

    db = tmp_path / "seed.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db.as_posix()}",
        "DEMO_PASSWORD": "seed-test-pw-123",
    }
    for cmd in (["-m", "alembic", "upgrade", "head"], ["-m", "app.db.seed"], ["-m", "app.db.seed"]):
        subprocess.run(
            [sys.executable, *cmd], cwd=BACKEND, env=env, check=True, capture_output=True
        )
    con = sqlite3.connect(db)
    assert con.execute("select count(*) from incidents").fetchone()[0] == 12
    assert con.execute("select count(*) from incidents where is_synthetic=0").fetchone()[0] == 0
    assert con.execute("select count(*) from users where is_synthetic=0").fetchone()[0] == 0
    assert con.execute("select count(*) from users").fetchone()[0] == 5
    assert con.execute("select count(*) from model_versions").fetchone()[0] == 0
    hashes = [r[0] for r in con.execute("select password_hash from users")]
    assert all(h.startswith("scrypt$") and "seed-test-pw-123" not in h for h in hashes)
    con.close()
