#!/usr/bin/env bash
# Run a uv command inside the pinned Python image against this project.
#
# There is no host Python toolchain on the supported development machine, so
# data builds and the data-safety gate run in the same image the Phase 0
# verifier uses. Caches go to the ignored .phase0-cache/ directory because /tmp
# is not writable by the mapped host UID inside the image.
#
# Output is unbuffered: index builds and evaluations run for minutes, and with
# Python's default block buffering on a pipe their progress lines only appear
# at exit, which reads as a hang.
set -Eeuo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "$script_directory/.." && pwd)"
cache_directory="$project_directory/.phase0-cache"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Start Docker Desktop and open a new terminal." >&2
  exit 1
fi

mkdir -p "$cache_directory/uv" "$cache_directory/mpl" "$cache_directory/hf"

# Model configuration is forwarded so one run can name its own provider and
# model without editing `.env` -- which is what makes "swap the model" a command
# rather than a file edit.
#
# Only variables that are actually set are passed. `--env NAME=` sets the
# variable to the empty string inside the container, and pydantic-settings reads
# an empty string as a value rather than as absent, so an unset variable
# forwarded this way fails validation on every `Literal` field instead of
# falling back to `.env`.
llm_environment=()
for name in MERIDIAN_LLM_PROVIDER MERIDIAN_LLM_MODEL MERIDIAN_LLM_BASE_URL \
            MERIDIAN_LLM_STRUCTURED_OUTPUT MERIDIAN_LLM_API_KEY; do
  if [[ -n "${!name:-}" ]]; then
    llm_environment+=(--env "$name=${!name}")
  fi
done

exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env UV_CACHE_DIR=/workspace/.phase0-cache/uv \
  --env UV_PROJECT_ENVIRONMENT=/workspace/.phase0-cache/python-env \
  --env UV_PYTHON=/usr/local/bin/python3.12 \
  --env UV_PYTHON_DOWNLOADS=0 \
  --env MPLCONFIGDIR=/workspace/.phase0-cache/mpl \
  --env PYTHONUNBUFFERED=1 \
  --env HF_HOME=/workspace/.phase0-cache/hf \
  --env FASTEMBED_CACHE_PATH=/workspace/.phase0-cache/hf \
  --env MYPY_CACHE_DIR=/workspace/.phase0-cache/mypy \
  --env MERIDIAN_REQUIRE_DATASET="${MERIDIAN_REQUIRE_DATASET:-}" \
  `# Expanded so that an empty array is nothing rather than an unbound` \
  `# variable, which "set -u" would otherwise treat as an error.` \
  ${llm_environment[@]+"${llm_environment[@]}"} \
  --mount "type=bind,src=$project_directory,dst=/workspace" \
  --workdir /workspace \
  ghcr.io/astral-sh/uv:0.12.7-python3.12-trixie-slim \
  uv run --locked --extra dev "$@"
