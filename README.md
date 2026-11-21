# IncidentIQ-Triage

![backend-ci](https://github.com/Sonu-Thomas-001/incidentiq-triage/actions/workflows/backend-ci.yml/badge.svg)

An explainable machine learning framework for automated IT incident classification, priority prediction and team assignment (IIT Guwahati, DA377).

## Status

- **Phase 1 (backend):** schema + migrations, local auth with RBAC, incident lifecycle with audit trail and optimistic concurrency, REST API, synthetic seed data, tests.
- **Phase 2 (ML pipeline):** dataset provenance, validation, EDA, leakage-aware splits, baselines, TF-IDF + Logistic Regression / Linear SVM, ablation, calibration, explainability, joblib artifacts, and `POST /incidents/{id}/triage` backed by the trained models. See [Phase 2](#phase-2-data-science-and-ml-pipeline) and [docs/report/](docs/report/).

If no model artifacts are present, triage returns `status: NOT_READY` (nothing is invented). All seeded incidents are **synthetic** (`is_synthetic = true`, titles prefixed `[SYNTHETIC]`).

## Layout

```
backend/   FastAPI app (app/{api,db,models,schemas,services,core}), alembic/, tests/
frontend/  React + TypeScript + Vite UI (Phase 4)
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
| `POST /incidents/{id}/triage` | TRIAGE_ANALYST, ADMIN | optional `impact`, `urgency` (1-3); `NOT_READY` / `DEMO` / `MODEL`; `NEW -> TRIAGE_PENDING -> NEEDS_REVIEW`; recommendation only |
| `POST /incidents/{id}/assign` | TRIAGE_ANALYST, ADMIN | from `NEW/TRIAGE_PENDING/NEEDS_REVIEW` -> `ASSIGNED` |
| `POST /incidents/{id}/accept` | SUPPORT_ENGINEER (assigned team), ADMIN | `ASSIGNED/REASSIGNED -> ACCEPTED` |
| `POST /incidents/{id}/override` | TRIAGE_ANALYST, ADMIN | requires `reason` and a different team -> `REASSIGNED` |
| `GET /incidents/{id}/audit` | staff roles | append-only trail |
| `GET /teams/{id}/queue` | staff (engineers: own team) | open assigned incidents |
| `GET /analytics/overview` | TRIAGE_ANALYST, ADMIN | counts of recorded decisions only |
| `GET /models/metrics` | TRIAGE_ANALYST, ADMIN | manifest metrics with provenance; `NOT_READY` if no artifacts |

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

## Phase 2: data science and ML pipeline

Full methodology, provenance, limitations and tables: [docs/report/methodology.md](docs/report/methodology.md), [docs/report/evaluation_tables.md](docs/report/evaluation_tables.md); figures in `docs/report/figures/`, raw metrics in `docs/report/results/*.json`.

### Run the pipeline

Raw/processed data and model artifacts are git-ignored. Run from `ml/` (the backend venv already has the ML dependencies; otherwise `pip install -r ml/requirements.txt`).

Windows PowerShell:

```powershell
cd ml
$env:PYTHONPATH = "src"
..\backend\.venv\Scripts\python -m incidentiq_ml download   # fetch public datasets, verify pinned SHA-256
..\backend\.venv\Scripts\python -m incidentiq_ml all        # prepare + validate + eda + train (add --fast for a quick run)
..\backend\.venv\Scripts\python -m pytest                   # ML tests
```

POSIX:

```bash
cd ml
export PYTHONPATH=src
python -m incidentiq_ml download
python -m incidentiq_ml all
python -m pytest
```

Individual stages: `prepare`, `validate`, `eda`, `train`. Artifacts go to `ml/artifacts/` (`manifest.json` + `*.joblib`).

### Datasets

| Dataset | Use | License |
| --- | --- | --- |
| Zenodo tickets ([10.5281/zenodo.7648117](https://doi.org/10.5281/zenodo.7648117)), 2,229 rows | category (REAL) | CC BY 4.0 |
| UCI Incident Management Process Event Log ([10.24432/C57S4H](https://doi.org/10.24432/C57S4H)), 141,712 events / 24,918 incidents | group from structured fields; priority policy (REAL) | CC BY 4.0 |
| Synthetic generator (`ml/src/incidentiq_ml/synthetic.py`) | text/team demo only (SYNTHETIC) | n/a |

### Serving models in the API

The backend loads artifacts from `MODEL_DIR` (default `<repo>/ml/artifacts`). **joblib files can execute code when loaded: only use artifacts you produced yourself.** The loader checks the path, the SHA-256 in `manifest.json` and scikit-learn/numpy versions, and otherwise reports the model as unavailable.

Triage `status`: `NOT_READY` (no usable model), `DEMO` (at least one output comes from a model trained on synthetic data; the team model currently is), `MODEL` (only real-data models). Priority is a deterministic impact x urgency **policy**, returned only when `impact` and `urgency` are supplied. Results are recommendations; the incident goes to `NEEDS_REVIEW` and a human approves.

### Headline measured results (single held-out test evaluation)

- Real tickets category, grouped split, test macro-F1: majority 0.067, keyword 0.548, TF-IDF+LogReg 0.800, TF-IDF+LinearSVC 0.849 (LogReg was selected on validation and deployed).
- Real UCI assignment group from structured fields, chronological split, 44 classes: majority 0.016, category map 0.174, best (all structured fields, LinearSVC) macro-F1 0.650, top-1 0.797, top-3 0.870.
- Priority is a deterministic function of impact x urgency (0 violations in 141,712 events), so it is a policy, not a learned result.
- Synthetic-demo results exist but reflect generator design and must not be read as real accuracy.

## Phase 3: LangGraph workflow, Gemini assistance, ServiceNow adapter

Supervised ML stays the core prediction engine; Phase 3 adds a controlled, auditable workflow and
optional integrations, **all off by default and fully functional offline**. Details, state diagram and
privacy limits: [docs/architecture/phase3-workflow.md](docs/architecture/phase3-workflow.md).

| Endpoint (under `/api/v1`) | Role | Purpose |
|---|---|---|
| `POST /workflow/incidents/{id}/run` | analyst, admin | Run the LangGraph triage workflow; ends in `NEEDS_REVIEW`; idempotent |
| `POST /workflow/incidents/{id}/approve` | analyst, admin | Approve assignment (reason required when deviating) |
| `GET /workflow/incidents/{id}/runs` | staff | Stored runs with node trace |
| `GET /workflow/config` | analyst, admin | Effective thresholds/flags, no secrets |
| `GET /integrations/servicenow/health` | analyst, admin | State and reachability |
| `GET /integrations/servicenow/incidents[/{sys_id}]`, `/assignment-groups` | analyst, admin | Paginated read-only remote views |
| `POST /integrations/servicenow/import` | analyst, admin | Idempotent import of an open record |
| `GET/POST /integrations/servicenow/team-mappings` | analyst+ / admin | Team to assignment-group sys_id |
| `POST /integrations/servicenow/incidents/{id}/sync/preview` | analyst, admin | Exact intended change, no write |
| `POST /integrations/servicenow/incidents/{id}/sync/approve` | analyst, admin | Only write path (PATCH `assignment_group`) |
| `GET /integrations/servicenow/incidents/{id}/sync` | staff | Sync history |

Configuration variables (all in `.env.example`): `ROUTING_*`, `GEMINI_*`, `GOOGLE_API_KEY`,
`SERVICENOW_*`. Routing is disabled by default and never auto-assigns. ServiceNow writes need
`SERVICENOW_MODE=live` (or `mock`), a preview, explicit confirmation and the instance host. The
ServiceNow client has been tested only against mocks, not a live instance.

## Phase 4: React frontend

`frontend/` is a light-theme React 19 + TypeScript + Vite app with eight pages (overview, explorer,
create, AI triage workspace, team queues, analytics, audit timeline, admin) on the real API. See
[frontend/README.md](frontend/README.md) for setup, roles, the demo flow and limitations.
Backend additions: `GET /models/evaluations` (analyst/admin; summarises committed
`docs/report/results/*.json`, DEMO experiments flagged) and extra `/analytics/overview` fields
(`by_approved_category`, `incidents_per_day`, `override_rate`, `confidence_histogram`, ...), which are
empty or null when there is no data. CI: `frontend-ci` runs typecheck, lint, tests and build.

## Remaining work

Validate routing thresholds on real held-out data and train a real-data team model (current team model is synthetic); live-instance verification of the ServiceNow adapter; ServiceNow sync UI; retraining from `feedback_labels`. Also: login rate limiting, refresh tokens/password change, user admin endpoints, PostgreSQL option.