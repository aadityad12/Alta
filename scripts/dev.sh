#!/usr/bin/env bash
# Start the server (:8000) and the web app (:5173) together. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

command -v uv >/dev/null || { echo "Need uv: https://docs.astral.sh/uv/ (brew install uv)"; exit 1; }
command -v npm >/dev/null || { echo "Need Node.js 20+ (brew install node)"; exit 1; }
[ -f "$ROOT/.env" ] || echo "Note: no .env yet. cp .env.example .env and fill in keys (fine to skip for now)."

(cd "$ROOT/server" && uv sync --quiet)
[ -d "$ROOT/web/node_modules" ] || (cd "$ROOT/web" && npm install --silent)

# Stop the whole process group (uvicorn reloader, npm, vite) on Ctrl-C or exit.
cleanup() { trap - INT TERM EXIT; kill 0 2>/dev/null; }
trap cleanup INT TERM EXIT

(cd "$ROOT/server" && uv run uvicorn bench.main:app --reload --port 8000) &
(cd "$ROOT/web" && npm run dev) &

wait
