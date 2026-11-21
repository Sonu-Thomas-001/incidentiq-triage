# IncidentIQ-Triage

![backend-ci](https://github.com/Sonu-Thomas-001/incidentiq-triage/actions/workflows/backend-ci.yml/badge.svg)

An explainable machine learning framework for automated IT incident classification, priority prediction and team assignment (IIT Guwahati, DA377).

## Phase 1 status (backend foundation)

Implemented: schema + migrations, local auth with RBAC, incident lifecycle with audit trail and optimistic concurrency, REST API, synthetic seed data, tests.

**Not implemented yet: any ML model.** `POST /incidents/{id}/triage` returns `status: NOT_READY` with `is_demo: false`; no category, priority, team, probability or metric is ever invented. `GET /models/metrics` returns `NOT_READY` until a model is registered in `model_versions`. All seeded data is **synthetic** (`is_synthetic = true`, titles prefixed `[SYNTHETIC]`).

## Layout

```
backend/   FastAPI app (app/{api,db,models,schemas,services,core}), alembic/, tests/
frontend/  React + TypeScript (planned, Phase 4)
ml/        data/{raw,processed}, src, artifacts, experiments, notebooks (Phase 2+)
docs/      architecture, report, presentation
```

## Setup

Requires Python 3.11+. Run all commands from `backend/`.

### Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item ..\.env.example .env      # then edit; see "Configuration"
alembic upgrade head
python -m app.db.seed               # prints a generated demo password once
uvicorn app.main:app --reload
```

### macOS / Linux (POSIX)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload
```

API docs: <http://127.0.0.1:8000/docs> (Swagger) and `/redoc`. Health: `GET /health`.

### Configuration (`backend/.env`, never committed)

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | JWT signing key. Required unless `APP_ENV=development` (then an ephemeral random key is used and tokens die on restart). |
| `DATABASE_URL` | Default `sqlite:///./incidentiq.db` |
| `CORS_ORIGINS` | JSON list of allowed origins |
| `DEMO_PASSWORD` | Optional password for seeded demo users; if empty the seed script generates one and prints it once |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `LOG_LEVEL`, `APP_ENV` | Self-explanatory |

### Demo access

`python -m app.db.seed` is idempotent and creates synthetic users (password = `DEMO_PASSWORD` or the printed generated one; stored only as scrypt hashes):

| Email | Role | Team |
| --- | --- | --- |
| reporter@synthetic.example | REPORTER | - |
| analyst@synthetic.example | TRIAGE_ANALYST | - |
| engineer.network@synthetic.example | SUPPORT_ENGINEER | Network Operations |
| engineer.apps@synthetic.example | SUPPORT_ENGINEER | Application Support |
| admin@synthetic.example | ADMIN | - |

Log in: `POST /api/v1/auth/login` with `{"email","password"}`, then send `Authorization: Bearer <token>`. Do not use the seed users outside local demos.

### Tests and quality

```bash
python -m pytest          # 56 tests: lifecycle, permissions, validation, migrations, seed
ruff check .
black --check . --exclude ".venv|alembic/versions"
```

## API

Canonical prefix `/api/v1`; `/api/...` is an unversioned alias. All endpoints except `/health` and `/auth/login` need a bearer token.

| Method & path | Roles | Notes |
| --- | --- | --- |
| `POST /auth/login`, `GET /auth/me`, `GET /teams` | any | |
| `POST /incidents` | any authenticated | creates `NEW`; text immutable |
| `GET /incidents` | any (reporters: own only) | filters `status, priority, team_id, reporter_id, q, created_from, created_to`; `page`, `page_size` (1-100) |
| `GET /incidents/{id}` | any (reporters: own only) | includes current assignment; predictions hidden from reporters |
| `POST /incidents/{id}/triage` | TRIAGE_ANALYST, ADMIN | Phase 1: `NOT_READY`; `NEW -> TRIAGE_PENDING -> NEEDS_REVIEW` |
| `POST /incidents/{id}/assign` | TRIAGE_ANALYST, ADMIN | from `NEW/TRIAGE_PENDING/NEEDS_REVIEW` -> `ASSIGNED` |
| `POST /incidents/{id}/accept` | SUPPORT_ENGINEER (assigned team), ADMIN | `ASSIGNED/REASSIGNED -> ACCEPTED` |
| `POST /incidents/{id}/override` | TRIAGE_ANALYST, ADMIN | requires `reason` and a different team -> `REASSIGNED` |
| `GET /incidents/{id}/audit` | staff roles | append-only trail |
| `GET /teams/{id}/queue` | staff (engineers: own team) | open assigned incidents |
| `GET /analytics/overview` | TRIAGE_ANALYST, ADMIN | counts of recorded decisions only |
| `GET /models/metrics` | TRIAGE_ANALYST, ADMIN | `NOT_READY` until a model is registered |

### Lifecycle

```
NEW -> TRIAGE_PENDING -> NEEDS_REVIEW -> ASSIGNED -> ACCEPTED
 \________________________________/          \-> REASSIGNED <-> ACCEPTED
```
Valid transitions are enforced server-side (`app/services/lifecycle.py`); invalid ones return `409 INVALID_TRANSITION`.

### Concurrency

Every mutation body carries `expected_version`. A mismatch returns `409 STALE_VERSION` (with `current_version`); the DB row is also guarded by SQLAlchemy `version_id_col`.

### Errors

```json
{"error": {"code": "FORBIDDEN", "message": "...", "details": null, "request_id": "..."}}
```
Codes: `VALIDATION_ERROR` (422), `UNAUTHENTICATED` (401), `FORBIDDEN` (403), `NOT_FOUND` (404), `INVALID_TRANSITION` / `STALE_VERSION` (409), `INTERNAL_ERROR` (500).

## Data design notes

- `triage_predictions` hold *recommendations*; `assignments` hold *approved human decisions*; `incidents.approved_*` hold approved priority/category. They never share columns.
- `incidents.title/description` are immutable (ORM guard + SQLite trigger); `audit_events` are append-only (ORM guard + triggers).
- Human assignments/overrides are also written to `feedback_labels` as future training labels.
- UUID keys, UTC timestamps, indexes, FKs (enforced via `PRAGMA foreign_keys=ON`), one current assignment per incident (partial unique index).
- `routing_rules` is seeded (synthetic) but not yet consumed by any endpoint.

## Remaining work

Phase 2+: dataset, feature pipeline, model training/registration, real triage + explanations, model metrics; Phase 4: React UI. Also: login rate limiting, refresh tokens/password change, user admin endpoints, PostgreSQL option.
