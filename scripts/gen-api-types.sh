#!/usr/bin/env bash
# scripts/gen-api-types.sh
# Spin up the backend, fetch openapi.json, then generate TypeScript types.
# Run from any directory — uses paths relative to the repo root.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
OPENAPI_OUT="$FRONTEND_DIR/src/api/openapi.json"
TYPES_OUT="$FRONTEND_DIR/src/api/types.ts"
PORT=8765

echo "Starting uvicorn on port $PORT..."
cd "$BACKEND_DIR"
# Use python3.11 directly (uv may not be installed in all environments)
# --loop asyncio: 2026-05-26 uvloop+subprocess hang dogfood — stdlib loop is safer.
python3.11 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --loop asyncio &
UVICORN_PID=$!

# Poll until /openapi.json is ready (up to 15 seconds)
DEADLINE=$(( $(date +%s) + 15 ))
while true; do
  if curl -sf "http://127.0.0.1:${PORT}/openapi.json" -o /dev/null 2>/dev/null; then
    echo "Backend ready."
    break
  fi
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "ERROR: backend did not become ready within 15 seconds" >&2
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

echo "Fetching openapi.json..."
curl -sf "http://127.0.0.1:${PORT}/openapi.json" -o "$OPENAPI_OUT"

echo "Stopping uvicorn (PID $UVICORN_PID)..."
kill "$UVICORN_PID"
wait "$UVICORN_PID" 2>/dev/null || true

echo "Generating TypeScript types..."
cd "$FRONTEND_DIR"
npx openapi-typescript "$OPENAPI_OUT" -o "$TYPES_OUT"

echo "OK: generated frontend/src/api/types.ts"
