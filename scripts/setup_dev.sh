#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit secrets before production use."
fi

python3 -m venv "$ROOT/backend/.venv"
source "$ROOT/backend/.venv/bin/activate"
pip install -r "$ROOT/backend/requirements.txt"

mkdir -p "$ROOT/backend/data" "$ROOT/backend/uploads"
cd "$ROOT/backend"
python -c "from app.bootstrap import init_db; init_db(); print('DB initialized')"

echo ""
echo "Dev setup done."
echo "  API:    cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000"
echo "  Worker: cd backend && source .venv/bin/activate && rq worker messenger --url redis://localhost:6379/0"
echo "  Webhook tunnel: ngrok http 8000"
echo "  Frontend: cd frontend && npm install && npm run dev"
