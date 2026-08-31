#!/usr/bin/env bash
# Run a uv command inside the pinned Python image against this project.
#
# There is no host Python toolchain on the supported development machine, so
# data builds and the data-safety gate run in the same image the Phase 0
# verifier uses. Caches go to the ignored .phase0-cache/ directory because /tmp
# is not writable by the mapped host UID inside the image.
set -Eeuo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
cache_directory="$project_directory/.phase0-cache"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Start Docker Desktop and open a new terminal." >&2
  exit 1
fi

mkdir -p "$cache_directory/uv" "$cache_directory/mpl"

exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env UV_CACHE_DIR=/workspace/.phase0-cache/uv \
  --env UV_PROJECT_ENVIRONMENT=/workspace/.phase0-cache/python-env \
  --env UV_PYTHON=/usr/local/bin/python3.12 \
  --env UV_PYTHON_DOWNLOADS=0 \
  --env MPLCONFIGDIR=/workspace/.phase0-cache/mpl \
  --env MYPY_CACHE_DIR=/workspace/.phase0-cache/mypy \
  --env MERIDIAN_REQUIRE_DATASET="${MERIDIAN_REQUIRE_DATASET:-}" \
  --mount "type=bind,src=$project_directory,dst=/workspace" \
  --workdir /workspace \
  ghcr.io/astral-sh/uv:0.12.7-python3.12-trixie-slim \
  uv run --locked --extra dev "$@"
