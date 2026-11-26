import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import build_engine, get_db
from app.main import app
from app.models import Team, User
from app.models.enums import Role
from app.services import rag_service

PASSWORD = "test-only-Passw0rd!"
_HASH = hash_password(PASSWORD)  # hashed once; scrypt is deliberately slow
Settings.model_config["env_file"] = None  # tests must never read a developer's real backend/.env


@pytest.fixture(autouse=True)
def chroma_dir(tmp_path, monkeypatch):
    """Every test gets an empty Chroma index (=> NOT_READY) and no real Gemini client."""
    d = tmp_path / "chroma"
    monkeypatch.setenv("CHROMA_DIR", str(d))
    get_settings.cache_clear()
    rag_service.reset_cache()
    rag_service.set_factories(lambda s: None, lambda s: None)
    yield d
    rag_service.set_factories(None, None)
    get_settings.cache_clear()
    rag_service.reset_cache()


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def world(session_factory) -> dict:
    """Two teams and one user per role (plus a second reporter and a second-team engineer)."""
    with session_factory() as db:
        net = Team(name="Network", is_synthetic=True)
        apps = Team(name="Apps", is_synthetic=True)
        db.add_all([net, apps])
        db.flush()
        specs = {
            "reporter": (Role.REPORTER, None),
            "reporter2": (Role.REPORTER, None),
            "analyst": (Role.TRIAGE_ANALYST, None),
            "eng_net": (Role.SUPPORT_ENGINEER, net.id),
            "eng_apps": (Role.SUPPORT_ENGINEER, apps.id),
            "admin": (Role.ADMIN, None),
        }
        users = {}
        for key, (role, team_id) in specs.items():
            user = User(
                email=f"{key}@test.example",
                full_name=key,
                role=role,
                team_id=team_id,
                password_hash=_HASH,
                is_synthetic=True,
            )
            db.add(user)
            users[key] = user
        db.commit()
        return {
            "users": {k: u.id for k, u in users.items()},
            "teams": {"net": net.id, "apps": apps.id},
        }


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self._tokens: dict[str, dict[str, str]] = {}

    def as_(self, key: str) -> dict[str, str]:
        if key not in self._tokens:
            r = self.client.post(
                "/api/v1/auth/login",
                json={"email": f"{key}@test.example", "password": PASSWORD},
            )
            assert r.status_code == 200, r.text
            self._tokens[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self._tokens[key]

    def create(self, who: str = "reporter", title: str = "VPN keeps dropping", **kw) -> dict:
        body = {
            "title": title,
            "description": "The VPN client disconnects every few minutes.",
        }
        body.update(kw)
        r = self.client.post("/api/v1/incidents", json=body, headers=self.as_(who))
        assert r.status_code == 201, r.text
        return r.json()

    def post(self, path: str, who: str, body: dict):
        return self.client.post(f"/api/v1{path}", json=body, headers=self.as_(who))

    def get(self, path: str, who: str, **params):
        return self.client.get(f"/api/v1{path}", headers=self.as_(who), params=params)


@pytest.fixture
def api(client, world) -> Api:
    return Api(client)


def new_id() -> str:
    return str(uuid.uuid4())
