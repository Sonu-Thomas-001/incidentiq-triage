import pytest
from sqlalchemy import text

from tests.conftest import PASSWORD


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_and_me(api):
    r = api.get("/auth/me", "analyst")
    assert r.status_code == 200
    assert r.json()["role"] == "TRIAGE_ANALYST"
    assert "password" not in r.text


def test_login_rejects_bad_credentials(client, world):
    for email, pw in [("analyst@test.example", "wrong"), ("nobody@test.example", PASSWORD)]:
        r = client.post("/api/v1/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_inactive_user_cannot_login_or_use_token(api, session_factory, client, world):
    headers = api.as_("reporter")
    with session_factory() as db:
        db.execute(text("UPDATE users SET is_active = 0"))
        db.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    r = client.post(
        "/api/v1/auth/login", json={"email": "reporter@test.example", "password": PASSWORD}
    )
    assert r.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/incidents"),
        ("post", "/incidents"),
        ("get", "/incidents/{id}"),
        ("post", "/incidents/{id}/triage"),
        ("post", "/incidents/{id}/assign"),
        ("post", "/incidents/{id}/accept"),
        ("post", "/incidents/{id}/override"),
        ("get", "/incidents/{id}/audit"),
        ("get", "/teams/{id}/queue"),
        ("get", "/analytics/overview"),
        ("get", "/models/metrics"),
    ],
)
def test_every_endpoint_requires_auth(client, method, path):
    url = "/api/v1" + path.replace("{id}", "00000000-0000-0000-0000-000000000000")
    r = getattr(client, method)(url)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_garbage_token_rejected(client):
    r = client.get("/api/v1/incidents", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_alias_path_without_version(api, client):
    r = client.get("/api/incidents", headers=api.as_("analyst"))
    assert r.status_code == 200
