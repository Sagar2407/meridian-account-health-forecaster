#!/usr/bin/env bash
# Run the Playwright journeys against the real stack (plan section 23.5).
#
# Brings up the backend and frontend with the dataset, model, and artifacts
# mounted, waits for both health checks, and runs the browser suite in its own
# container. Everything is torn down afterwards, pass or fail.
#
# The suite needs the extracted dataset and a trained forecaster. Both are
# checked here rather than left to fail as a confusing empty portfolio.

set -euo pipefail

project_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_directory"

compose=(docker compose -f docker-compose.yml -f docker-compose.e2e.yml)

if [[ ! -f data/raw/meridian-account-health/data/accounts.csv ]]; then
  echo "The extracted dataset is missing. Run 'make data' first." >&2
  exit 1
fi

if [[ ! -f models/forecaster.joblib ]]; then
  echo "No trained forecaster. Run 'make train' first." >&2
  exit 1
fi

if ! compgen -G "data/indexes/*" > /dev/null; then
  echo "No retrieval index. Run 'make index' first." >&2
  exit 1
fi

cleanup() {
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[1/3] Building the stack with the E2E API base URL"
"${compose[@]}" build backend frontend

echo "[2/3] Starting the stack and waiting for both health checks"
"${compose[@]}" up -d --wait backend frontend

echo "[3/3] Running the browser journeys"
# Arguments are forwarded to Playwright, so an intended visual change can be
# accepted with `./scripts/run_e2e.sh --update-snapshots` rather than by hand-
# editing baselines or deleting them and hoping the next run is right.
"${compose[@]}" run --rm e2e sh -c "corepack enable &&
  cd /workspace &&
  corepack pnpm install --frozen-lockfile --store-dir /workspace/.phase0-cache/pnpm-store &&
  cd frontend &&
  pnpm exec playwright test $*"

echo "End-to-end journeys passed."
