# IncidentIQ-Triage frontend (Phase 4)

React 19 + TypeScript + Vite + Tailwind CSS 4, Radix-based shadcn-style components, Lucide icons,
Recharts, TanStack Query, React Hook Form + Zod, React Router. Light theme only.
All data comes from the real FastAPI backend; nothing is mocked in the app (tests stub `fetch`).

## Setup

Start the backend first (see the root README), seeded with a demo password:

```powershell
# Windows PowerShell, from backend/
$env:DEMO_PASSWORD = "choose-a-password"
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m app.db.seed
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

```bash
# POSIX, from backend/
DEMO_PASSWORD=choose-a-password python -m alembic upgrade head
DEMO_PASSWORD=choose-a-password python -m app.db.seed
python -m uvicorn app.main:app --port 8000
```

Then the frontend:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

`VITE_API_BASE_URL` (default `http://localhost:8000/api/v1`) selects the backend. The backend's
`CORS_ORIGINS` must include the frontend origin (`http://localhost:5173` is the default).
Optional mock ServiceNow for the Admin page: `SERVICENOW_ENABLED=true SERVICENOW_MODE=mock`.

Sign in with a synthetic account (`reporter@`, `analyst@`, `engineer@`, `admin@synthetic.example`)
and the `DEMO_PASSWORD` you seeded. No API keys or ServiceNow credentials are ever in browser code.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | ESLint |
| `npm test` | Vitest + React Testing Library |
| `npm run build` | Typecheck + production build |

## Pages and roles

Role gating in the UI is cosmetic; the backend enforces authorization.

| Page | Route | Roles |
|---|---|---|
| Overview | `/` | all |
| Incident Explorer | `/incidents` | all |
| Create Incident | `/incidents/new` | all |
| Triage Workspace | `/incidents/:id` | all (decisions: analyst, admin) |
| Team Queues | `/queues` | staff |
| Analytics | `/analytics` | analyst, admin |
| Audit Timeline | `/incidents/:id/audit` | staff |
| Admin Settings | `/admin` | admin (read-only view for analyst) |

The workspace separates three visual panels: **ML prediction** (sky; DEMO banner when the model is a
synthetic demo), **deterministic priority policy** (teal) and **optional Gemini summary** (violet,
never used for routing).

## End-to-end demo flow

1. Sign in as `reporter`, create an incident (Create Incident). It is stored as `NEW`.
2. Sign in as `analyst`, open it, run triage. Review the ML output, policy priority, evidence
   and routing rationale; low confidence or demo models land in `NEEDS_REVIEW`.
3. Approve the recommendation, or override with a reason (at least 5 characters).
4. Sign in as `engineer`, open Team Queues and accept the assignment (or reassign with a reason).
5. Open the Audit Timeline, Overview and Analytics to see the resulting events and metrics.

## Screenshots

With backend and `npm run dev` running, capture each page at about 1440 px wide and at a mobile
width (390 px) and save under `docs/presentation/screenshots/`. Synthetic data is labelled in the UI.

## Limitations

- "Request review" is implemented as run triage, which moves the incident to `NEEDS_REVIEW`.
- The Explorer has no team column or category filter (not in the incident API).
- Assignment trends per day are shown as unavailable.
- The ServiceNow sync preview/approve UI is not built; the API client functions exist. Admin shows
  connection health only.
- Evaluation tables come from the committed `docs/report/results/*.json`; DEMO (synthetic)
  experiments are labelled and kept separate from real-data results.
