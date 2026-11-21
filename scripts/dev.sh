#!/usr/bin/env bash
# Start backend (8000) and frontend (5173); Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="$PWD/backend/.venv/bin/python"
(cd backend && "$PY" -m uvicorn app.main:app --port 8000) &
API=$!
trap 'kill $API 2>/dev/null' EXIT
echo "Backend http://localhost:8000/docs  Frontend http://localhost:5173"
cd frontend && npm run dev
