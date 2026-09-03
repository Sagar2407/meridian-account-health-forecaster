#!/usr/bin/env bash
set -Eeuo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
docker_user="$(id -u):$(id -g)"
phase0_cache_directory="$project_directory/.phase0-cache"

cd "$project_directory"

mkdir -p \
  "$phase0_cache_directory/corepack" \
  "$phase0_cache_directory/home" \
  "$phase0_cache_directory/npm" \
  "$phase0_cache_directory/pnpm-store" \
  "$phase0_cache_directory/uv" \
  "$phase0_cache_directory/xdg-cache"

if [ ! -f "$project_directory/data/raw/meridian-account-health/data/accounts.csv" ]; then
  echo "Raw dataset missing. Extract meridian-account-health.zip into data/raw/ first." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Start Docker Desktop and open a new terminal." >&2
  exit 1
fi

echo "[1/6] Checking Docker"
docker version >/dev/null
docker compose version

echo "[2/6] Resolving and locking Python dependencies"
docker run --rm \
  --user "$docker_user" \
  --env UV_CACHE_DIR=/workspace/.phase0-cache/uv \
  --env UV_PROJECT_ENVIRONMENT=/workspace/.phase0-cache/python-env \
  --env UV_PYTHON=/usr/local/bin/python3.12 \
  --env UV_PYTHON_DOWNLOADS=0 \
  --mount "type=bind,src=$project_directory,dst=/workspace" \
  --workdir /workspace \
  ghcr.io/astral-sh/uv:0.12.7-python3.12-trixie-slim \
  uv \
  lock

echo "[3/6] Resolving and locking frontend dependencies"
docker run --rm \
  --user "$docker_user" \
  --env COREPACK_HOME=/workspace/.phase0-cache/corepack \
  --env HOME=/workspace/.phase0-cache/home \
  --env XDG_CACHE_HOME=/workspace/.phase0-cache/xdg-cache \
  --env npm_config_cache=/workspace/.phase0-cache/npm \
  --mount "type=bind,src=$project_directory,dst=/workspace" \
  --workdir /workspace \
  node:22-alpine \
  sh -c 'corepack pnpm install --lockfile-only --store-dir /workspace/.phase0-cache/pnpm-store'

test -s uv.lock
test -s pnpm-lock.yaml

echo "[4/6] Building the locked application images"
docker compose build

echo "[5/6] Running backend and frontend quality gates"
# The raw archive is git-ignored and excluded from the image, so it is mounted
# read-only for the test run. MERIDIAN_REQUIRE_DATASET=1 turns a missing archive
# into an error instead of silently skipping the data-safety tests.
docker compose run --rm --no-deps \
  --volume "$project_directory/data:/app/data:ro" \
  --env MERIDIAN_REQUIRE_DATASET=1 \
  backend sh -c '
  uv run --locked ruff check backend evaluation &&
  uv run --locked ruff format --check backend evaluation &&
  uv run --locked mypy &&
  uv run --locked pytest
'
docker compose run --rm --no-deps frontend sh -c '
  pnpm format:check &&
  pnpm lint &&
  pnpm typecheck &&
  pnpm test &&
  pnpm build
'
python3 scripts/check_repository.py

echo "[6/6] Starting the stack and waiting for both health checks"
docker compose up --detach --wait --wait-timeout 120
curl --fail --silent --show-error http://localhost:8000/api/health
curl --fail --silent --show-error http://localhost:5173 >/dev/null

echo
echo "Phase 0 verification passed."
echo
# This stack is the quality gate, not a demo. Compose mounts no data by design
# (`.dockerignore` excludes `data/` and `models/`), so every subsystem reports
# absent and the UI shows a "Degraded" banner. Saying only "UI: localhost:5173"
# here sent people to a deliberately empty application and left them debugging
# a health warning that was working correctly.
echo "The stack now running is the gate's own: no dataset, no model, no index,"
echo "so /api/health reports \"degraded\" and the UI shows a Degraded banner."
echo "That is expected here and is not a failure."
echo
echo "  Gate stack (degraded by design)   http://localhost:5173"
echo "  API docs                          http://localhost:8000/docs"
echo
echo "For a working application with the data mounted, run:"
echo "  make prod-build && make prod-up   http://localhost:8080"
