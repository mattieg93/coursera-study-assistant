#!/usr/bin/env bash
# launch_v2.sh — Start the UI v2 (FastAPI + Vite dev server)
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$REPO_ROOT/.venv-1/bin/python3"
WEB_DIR="$REPO_ROOT/src/ui_v2/web"

# Default port; can override with PORT env var
API_PORT="${PORT:-8000}"
VITE_PORT="${VITE_PORT:-5173}"

echo "Starting FastAPI backend on port $API_PORT..."
DEV_MODE=true "$VENV_PYTHON" -m uvicorn src.ui_v2.api.main:app \
  --host 0.0.0.0 \
  --port "$API_PORT" \
  --reload \
  --reload-dir src/ui_v2 \
  --reload-dir src/ui \
  --reload-dir src/study_system &
API_PID=$!

echo "Starting Vite dev server on port $VITE_PORT..."
cd "$WEB_DIR"
VITE_API_PORT="$API_PORT" npm run dev -- --port "$VITE_PORT" &
VITE_PID=$!

trap "kill $API_PID $VITE_PID 2>/dev/null; exit" INT TERM
echo ""
echo "  API:  http://localhost:$API_PORT"
echo "  App:  http://localhost:$VITE_PORT"
echo ""
echo "Press Ctrl+C to stop both servers."
wait
