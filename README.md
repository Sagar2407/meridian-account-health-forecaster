# Meridian Enterprise Account Health Forecaster

Meridian is a CMU Agentic AI Program capstone project for a read-only autonomous decision-support system. Given a fictional B2B SaaS customer account, it will forecast `Churned`, `Contracted`, `Renewed`, or `Expanded`; explain the result with exact metrics and point-in-time evidence; recommend an appropriate next step; and decide whether the advisory result can be released or requires human review.

> All account, company, person, usage, ticket, note, event, and outcome data in this repository is synthetic. The system is decision support and must not make customer-facing or commercial commitments.

## Current status

Source onboarding is complete and the Phase 0 engineering foundation is implemented. The repository
now contains a typed FastAPI service, a React/TypeScript health UI, validated environment settings,
Docker Compose, local quality commands, CI, pre-commit hooks, and architecture decision records.

The user-confirmed Docker health page passes. The remaining automated checks and lockfile generation
are consolidated in `make phase0-verify`; see `docs/PHASE_0_STATUS.md` for the exact evidence. Phase 1
has not started.

## Quick start

Prerequisites for native development: Python 3.11 or 3.12, uv 0.12, Node.js 22.12 or newer, pnpm 11,
and GNU Make. Docker Compose v2 is the recommended self-contained path.

```bash
cp .env.example .env
make setup
make dev
```

Open the UI at `http://localhost:5173`, the API health endpoint at
`http://localhost:8000/api/health`, and interactive API documentation at
`http://localhost:8000/docs`. `make dev` is the documented one-command startup after setup.

To run the same foundation in containers:

```bash
cp .env.example .env
docker compose up --build
```

Both containers have explicit health checks, and the frontend waits for a healthy API.

To generate both dependency lockfiles and run the complete Phase 0 acceptance suite through Docker:

```bash
make phase0-verify
```

The command leaves the verified application running so the UI remains available.

## Quality gates

```bash
make format     # apply source formatting
make lint       # Python and TypeScript linting
make typecheck  # strict Python and TypeScript checks
make test       # backend and frontend tests with coverage
make check      # all non-formatting local gates
```

GitHub Actions applies locked installs, format checks, linting, typing, tests, coverage thresholds,
the frontend production build, the repository policy scan, and both Docker builds. Dependency ranges
are declared in `pyproject.toml` and `frontend/package.json`; `uv.lock` and `pnpm-lock.yaml` record the
resolved environments.

## Phase 0 API contract

`GET /api/health` is intentionally the only application endpoint in this phase:

```json
{
  "status": "ok",
  "service": "meridian-api",
  "version": "0.1.0",
  "environment": "development",
  "data_mode": "synthetic"
}
```

No dataset access, retrieval, model, forecast, agent, or review behavior is present yet.

## Verified dataset snapshot

- 260 accounts
- 67,223 usage rows
- 6,408 support tickets
- 6,420 CSM notes and QBRs
- 595 external events
- 12,860 account and knowledge-base corpus records
- 32 knowledge-base documents
- 23 golden evaluation questions
- 36 guardrail cases
- Deterministic seed: `20260721`
- Dataset as-of date: `2026-06-28`
- Forecast horizon: 90 days

The raw package contains records after some accounts' effective forecast cutoffs. Runtime ingestion must therefore sanitize data before any model or retrieval work.

## Final architecture

The system uses four logical agents coordinated by LangGraph:

1. **Orchestrator / Planner** — decomposes the assessment, checks evidence coverage, and routes the workflow.
2. **Quantitative Analyst** — runs deterministic metrics and the calibrated predictive model.
3. **Evidence Retriever** — performs account-scoped semantic retrieval and one bounded grade/rewrite/retry cycle.
4. **Forecast Adjudicator** — uses a linear fast path for aligned evidence and bounded Tree-of-Thought only for material conflicts.

MCP-compatible interfaces expose typed, read-only tools and resources. A safety boundary validates inputs, enforces point-in-time access, verifies outputs, computes confidence, and routes green, amber, red, or blocked cases.

## Documentation map

- `AGENTS.md` — repository operating instructions
- `docs/PROJECT_CONTEXT.md` — problem, users, course story, and design evolution
- `docs/REQUIREMENTS.md` — numbered requirements and acceptance conditions
- `docs/ARCHITECTURE.md` — final architecture and control flow
- `docs/DATA_SAFETY.md` — cutoff, leakage, immutability, and validation policy
- `docs/DECISIONS.md` — accepted and open architectural decisions
- `docs/SOURCE_INVENTORY.md` — source artifacts and hashes
- `docs/VERIFICATION_MATRIX.md` — verified claims, evidence, and unresolved items
- `docs/Meridian_Autonomous_System_Implementation_Plan.md` — full phased build specification
- `docs/adr/` — accepted architecture decision records
- `docs/PHASE_0_STATUS.md` — exit-gate evidence and remaining validation
- `docs/ENVIRONMENT.md` — observed and supported development environments

## Repository boundaries

- `backend/` — FastAPI application and Python tests
- `frontend/` — React/TypeScript application and Vitest tests
- `graph/` — LangGraph orchestration in later phases
- `tools/` — typed business services and MCP adapters in later phases
- `retrieval/` — sanitized indexing and retrieval in later phases
- `evaluation/` — deterministic evaluation harness in later phases
- `config/` — non-secret configuration examples
- `data/` — immutable raw inputs and ignored generated artifacts

## Dataset location

The unchanged source archive remains at the repository root. Its extracted contents are available under:

```text
data/raw/meridian-account-health/
```

Raw data must remain immutable. Processed runtime-safe data, indexes, splits, models, and evaluation results will be generated into separate directories during later phases.

The source archive and extracted raw dataset are intentionally ignored by Git. A later data phase
will preserve the supplied deterministic generator in the public repository and document dataset
regeneration without publishing redundant generated artifacts.

## Module 7 deliverables

The completed capstone must include:

- A final report submitted as PDF or DOCX.
- A public GitHub repository with architecture, setup, usage, code, examples, and evaluation artifacts.
- An 8–10 minute recorded presentation for a technical audience.
- A document containing the video link and a two-to-three-sentence summary.
- Optionally, a 90-second elevator pitch.

The report template, presentation outline, and any separate detailed grading rubric are intentionally deferred and are not active project blockers.
