#!/usr/bin/env bash
# One-shot local setup (POSIX). Run from anywhere:
#   DEMO_PASSWORD=choose-one ./scripts/setup.sh [--train] [--skip-frontend]
# --train downloads the public datasets and trains the models (several minutes).
set -euo pipefail
cd "$(dirname "$0")/.."
TRAIN=0; FRONT=1
for a in "$@"; do
  case "$a" in
    --train) TRAIN=1 ;;
    --skip-frontend) FRONT=0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

[ -d backend/.venv ] || python3 -m venv backend/.venv
PY="$PWD/backend/.venv/bin/python"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements-lock.txt

[ -f backend/.env ] || cp .env.example backend/.env

(cd backend && "$PY" -m alembic upgrade head && "$PY" -m app.db.seed)

if [ "$TRAIN" = 1 ]; then
  (cd ml && PYTHONPATH=src "$PY" -m incidentiq_ml all)
fi
if [ "$FRONT" = 1 ]; then
  (cd frontend && npm ci)
fi
echo "Setup done. Start the app with ./scripts/dev.sh"
