#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Backend dependencies are missing. Run 'make setup' first." >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is missing. Install it or set PATH, then run 'make setup'." >&2
  exit 1
fi

backend_pid=""
frontend_pid=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  [[ -z "$backend_pid" ]] || kill "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || kill "$frontend_pid" 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

.venv/bin/uvicorn meridian.api.main:app \
  --app-dir backend/src \
  --reload \
  --host 0.0.0.0 \
  --port "${MERIDIAN_API_PORT:-8000}" &
backend_pid=$!

pnpm --dir frontend dev --host 0.0.0.0 &
frontend_pid=$!

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

echo "A development process stopped; shutting down the remaining process." >&2
exit 1
