FROM ghcr.io/astral-sh/uv:0.12.7 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY backend ./backend
# The evaluation package holds labels and ground truth. It is present because the
# quality gate type-checks and tests it; `test_import_boundary.py` guarantees no
# runtime module can import it. The Phase 11 production image will omit it.
COPY evaluation ./evaluation
# The curated demo runs, so the development stack behaves like production.
COPY config ./config
# The command-line entry points. They are here so the quality gate can lint and
# format them: `scripts/` is fifteen files of shipped code that went unchecked
# for exactly this reason -- ruff cannot check a directory the image does not
# contain, so `ruff check backend evaluation` was the whole scope by default
# rather than by decision. They are not importable by anything served.
COPY scripts ./scripts

RUN uv sync --locked --extra dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "meridian.api.main:app", "--app-dir", "backend/src", "--host", "0.0.0.0", "--port", "8000"]
