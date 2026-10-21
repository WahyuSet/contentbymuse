#!/usr/bin/env bash
# Menjalankan API, worker, dan web di VM Linux ini (uv tidak tersedia di sini,
# jadi backend memakai venv; di Windows gunakan dev.ps1).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q fastapi 'uvicorn[standard]' 'sqlalchemy[asyncio]' \
    aiosqlite alembic pydantic pydantic-settings httpx jinja2 pillow cryptography
fi
if [ ! -f backend/.env ]; then
  echo "backend/.env belum ada — salin dari backend/.env.example dan isi APP_SECRET_KEY." >&2
  exit 1
fi

(cd backend && .venv/bin/python -m alembic upgrade head)
(cd backend && .venv/bin/uvicorn app.main:serve --factory --host 127.0.0.1 --port 8010) &
(cd backend && .venv/bin/python -m app.worker) &
if command -v pnpm >/dev/null; then (cd frontend && pnpm dev); else (cd frontend && npm run dev); fi
trap 'kill %1 %2 2>/dev/null || true' EXIT
