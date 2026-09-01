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

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend
# The curated demo runs (section 24.3). Committed and small, and the demo
# endpoints degrade to live runs without them -- but a deployment that
# silently lost its cache would spend a model budget nobody expected.
COPY config ./config

# No `--extra dev`: the serving image needs neither pytest nor the linters.
RUN uv sync --locked --no-dev

# --- 3. The compiled frontend, where the API serves it from ------------------
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
