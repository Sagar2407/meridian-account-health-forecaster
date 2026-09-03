# The single-container production image (plan section 24.2).
#
# Five things, in the order the plan lists them: build the React frontend,
# install the Python backend, copy the compiled frontend into the backend's
# static directory, serve `/api/*` through FastAPI with an SPA fallback for
# everything else, and bind to Render's `PORT`.
#
# It is deliberately not the development image. `backend/Dockerfile` installs
# the dev extra so the quality gate can run inside it; this one does not, and
# it omits the evaluation package entirely -- that code reads outcome labels,
# and a served container has no business being able to import it.

# --- 1. Build the browser bundle --------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build
RUN corepack enable

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile

COPY frontend ./frontend
# The browser calls the same origin it was served from, so the base URL is
# empty rather than a hostname baked in at build time. That is what lets one
# image run on localhost, on Render, and anywhere else without a rebuild.
ENV VITE_API_BASE_URL=""
RUN pnpm --dir frontend build

# --- 2. Install the Python runtime ------------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.7 AS uv

FROM python:3.12-slim AS pydeps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend

# No `--extra dev`: the serving image needs neither pytest nor the linters.
# The uv cache is discarded in the same layer that fills it. Removing it in a
# later layer would not shrink the image -- the bytes would still be in this
# one -- and it is 640 MB of a 2.2 GB image.
RUN uv sync --locked --no-dev && rm -rf /root/.cache/uv

# The embedding model is the one runtime dependency this project does not build
# and does not commit: `fastembed` fetches it from the HuggingFace Hub the first
# time anything retrieves. Left to run time that is a 65 MB download inside the
# request that triggers it, it needs outbound network access from the serving
# container, and it is subject to the Hub's anonymous rate limit. Baking it in
# costs 65 MB and removes all three. `FASTEMBED_CACHE_PATH` is read by
# `define_cache_dir`, which is what the application hits because it passes no
# explicit `cache_dir`.
#
# It lives in this shared stage because the index build needs it too: without
# it, `build_index.py` would download the same model again during the build.
#
# The venv is not on PATH yet -- that happens below -- so this calls its
# interpreter directly.
ENV FASTEMBED_CACHE_PATH=/app/.model-cache
RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; \
    TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/.model-cache')"

# --- 2b. Build the runtime data from the committed archive -------------------
#
# The served application reads source tables, a retrieval index, derived
# tables, a split, and a calibrated forecaster. None of those are in the
# repository: they are build outputs, and `.gitignore` keeps them out, so a
# fresh clone -- which is exactly what a hosting platform builds from -- has
# only `meridian-account-health.zip` and `data/splits`.
#
# So the image builds them, from the one committed input. That is what makes it
# self-contained: `docker build` on a clean checkout produces a container that
# needs no mounts, which a hosting platform has no way of providing anyway.
#
# This stage exists separately for one reason beyond tidiness: `build_data.py`
# and `train_model.py` import `meridian_eval`, which reads outcome labels, and
# D-056 says no served process may be able to import it. Building here and
# copying only the outputs keeps that true.
#
# Cost, measured locally: about seven minutes, effectively all of it embedding
# 17,140 chunks. The data build is 2.8s and training is 15s. It is one Docker
# layer, so it is rebuilt only when the archive or the build code changes.
FROM pydeps AS databuild

COPY evaluation ./evaluation
COPY scripts ./scripts
COPY meridian-account-health.zip ./

# The build tools, which the serving image does not get. `meridian_eval.training`
# imports matplotlib to draw the calibration plot, and matplotlib is in the dev
# extra, so `--no-dev` inherited from the shared stage cannot run the training
# step. This stage is discarded once its outputs are copied, so what it installs
# never reaches the served container.
RUN uv sync --locked --extra dev && rm -rf /root/.cache/uv

# `unzip` is not in the slim image and Python already reads zip files, so this
# avoids an apt layer for one command.
# `mkdir docs` is not incidental: training writes `docs/MODEL_CARD.md` as a side
# effect, and that directory is not in this stage's context. The card is a
# repository document regenerated by `make train` on a developer machine, so the
# copy written here is discarded with the stage; only the directory needs to
# exist for the write not to fail.
RUN mkdir -p docs \
 && /app/.venv/bin/python -c "\
import zipfile; zipfile.ZipFile('meridian-account-health.zip').extractall('data/raw')" \
 && /app/.venv/bin/python scripts/build_data.py \
 && /app/.venv/bin/python scripts/train_model.py \
 && /app/.venv/bin/python scripts/build_index.py

# --- 3. The serving image ----------------------------------------------------
FROM pydeps AS runtime

# The curated demo runs (section 24.3). Committed and small, and the demo
# endpoints degrade to live runs without them -- but a deployment that
# silently lost its cache would spend a model budget nobody expected.
COPY config ./config

# The published evaluation results. `GET /api/evaluations/{name}` reads these,
# so without them the deployed evaluation page reports every evaluation as
# never run. Text and plots, well under a megabyte.
COPY artifacts ./artifacts

# The runtime data slice: the source tables the repository loads, the retrieval
# index, the derived tables, the split, and the calibrated forecaster. About
# 51 MB, and `.dockerignore` explains what is left out and why.
#
# This is what makes the image self-contained. Without it the container starts
# with three subsystems absent and forecasts nothing, and the only reason
# `make prod-up` worked was that it bind-mounted these paths from the host --
# which a hosting platform has no equivalent of.
#
# `data/app` is deliberately absent, so a deployment starts with an empty
# assessment history and writes it into the container's own layer. That is
# what makes the unauthenticated review queue self-healing, and the precise
# claim is worth stating precisely: the state survives a restart of the same
# container and is gone whenever the container is *replaced*. On a platform
# that spins an idle service down and starts a fresh container on the next
# request, and on every deploy, that is the same thing in practice. Mounting a
# persistent disk here would remove the property and put blocker 2 in
# docs/DEPLOYMENT.md back on the table.
COPY --from=databuild /app/data/raw/meridian-account-health/data \
                     ./data/raw/meridian-account-health/data
# The knowledge base is read at *serve* time, not only at build time, so it has
# to ship. `load_verified_index` rebuilds the parent documents on every search
# to check the index digest against the corpus this code produces today, and
# building parents calls `load_knowledge_base`. Without this file every search
# raises FileNotFoundError, every assessment degrades to telemetry with no
# forecast, and `/api/health` still says the index is ready -- which is how it
# reached a deployment unnoticed. Only this one 47 KB file is served: the rest
# of rag_corpus (28 MB of ticket, note, and combined corpora) is consumed by
# `build_index.py` in the databuild stage and never read again.
COPY --from=databuild /app/data/raw/meridian-account-health/rag_corpus/knowledge_base.jsonl \
                     ./data/raw/meridian-account-health/rag_corpus/knowledge_base.jsonl
COPY --from=databuild /app/data/indexes ./data/indexes
COPY --from=databuild /app/data/processed ./data/processed
COPY --from=databuild /app/data/splits ./data/splits
COPY --from=databuild /app/models ./models

# The compiled frontend, where the API serves it from.
COPY --from=frontend /build/frontend/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH" \
    MERIDIAN_STATIC_DIRECTORY=/app/frontend/dist

# Render sets PORT. 8080 is only the local default.
ENV PORT=8080
EXPOSE 8080

# A read-only filesystem is not assumed: the application writes its own
# assessment history under data/app. Everything else it reads is mounted or
# baked in.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f\"http://localhost:{os.environ.get('PORT','8080')}/api/health\", timeout=4)"

# A shell is needed so ${PORT} expands at start-up, and `exec` is needed so
# uvicorn replaces that shell as PID 1. Without `exec`, the shell holds PID 1,
# SIGTERM never reaches uvicorn, and every deploy waits out the platform's kill
# timeout instead of shutting down cleanly.
CMD ["sh", "-c", "exec uvicorn meridian.api.main:app --app-dir backend/src --host 0.0.0.0 --port ${PORT}"]
