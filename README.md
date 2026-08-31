# Meridian Enterprise Account Health Forecaster

Meridian is a CMU Agentic AI Program capstone project for a read-only autonomous decision-support system. Given a fictional B2B SaaS customer account, it will forecast `Churned`, `Contracted`, `Renewed`, or `Expanded`; explain the result with exact metrics and point-in-time evidence; recommend an appropriate next step; and decide whether the advisory result can be released or requires human review.

> All account, company, person, usage, ticket, note, event, and outcome data in this repository is synthetic. The system is decision support and must not make customer-facing or commercial commitments.

## Current status

**Phases 0 through 4 are complete.** Every exit gate passes. None of them needs an API key: the
first four involve no language model at all, and Phase 4 adds the interface to one rather than a
dependency on it.

Phase 0 delivered the engineering foundation: a typed FastAPI service, a React/TypeScript health UI,
validated environment settings, Docker Compose, quality commands, CI, pre-commit hooks, and
architecture decision records. Verify it with `make phase0-verify`; evidence is in
`docs/PHASE_0_STATUS.md`.

Phase 1 delivered the point-in-time-safe data layer: a central validating loader, enforced per-account
cutoffs, a sanitized runtime boundary separated from evaluation labels, deterministic splits, and a
provenance manifest. Verify it with `make validate-data`; evidence is in `docs/PHASE_1_STATUS.md` and
`docs/DATA_LINEAGE.md`.

Phase 2 delivered the calibrated forecaster: features recomputed from observable telemetry at an
arbitrary cutoff, five candidates including two documented baselines, one-standard-error selection,
and isotonic calibration. Train with `make train` and forecast one account with
`make predict ACCOUNT=ACC-1042`; evidence is in `docs/PHASE_2_STATUS.md` and `docs/MODEL_CARD.md`.

Phase 3 delivered point-in-time-safe semantic retrieval: parent-child chunking over sanitized text,
a local FAISS index governed by a SQLite metadata store, dual-lane account and knowledge-base search
with MMR reranking, deterministic relevance grading with one bounded rewrite and retry, and a
four-family retrieval benchmark with a chunking ablation. Build the index with `make index`, query it
with `make retrieve ACCOUNT=ACC-1089 QUERY="renewal risk"`, and reproduce every number with
`make evaluate-retrieval`; evidence is in `docs/PHASE_3_STATUS.md`.

Phase 4 delivered the tool and provider boundary: eight read-only services with a per-role
allowlist, Pydantic validation, bounded retries and an audit trail, exposed over the official MCP
SDK with an in-process client; plus a provider-neutral structured-generation interface with an
OpenAI-compatible adapter, deterministic fakes, and skeletons that say exactly what to configure.
Evidence is in `docs/PHASE_4_STATUS.md`.

Phase 5, the four agents and the LangGraph fast path, is next.

## Quick start

**Docker Compose v2 and GNU Make are the only hard prerequisites.** Every gate runs in containers,
so no host Python or Node toolchain is required.

First extract the committed synthetic dataset (see [The dataset](#the-dataset) for what it is):

```bash
unzip meridian-account-health.zip -d data/raw/
```

Then start the application:

```bash
cp .env.example .env
docker compose up --build
```

Native development additionally needs Python 3.11 or 3.12, uv 0.12, Node.js 22.12 or newer, and
pnpm 11. With those installed:

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
make data              # build sanitized tables, manifest, and the account split (Docker)
make validate-data     # the complete data-safety gate, including reproducibility (Docker)
make phase0-verify     # the complete Phase 0 acceptance suite (Docker)

make train             # train, calibrate, and persist the forecaster (Docker)
make predict ACCOUNT=ACC-1042            # forecast one account (Docker)
make index             # build the FAISS retrieval index (Docker, several minutes)
make retrieve ACCOUNT=ACC-1089 QUERY="renewal risk"   # retrieve evidence as JSON (Docker)
make evaluate-retrieval  # retrieval benchmark and chunking ablation (Docker, ~20 minutes)

make format         # apply source formatting          (needs a host toolchain)
make lint           # Python and TypeScript linting    (needs a host toolchain)
make typecheck      # strict Python and TypeScript     (needs a host toolchain)
make test           # backend and frontend tests       (needs a host toolchain)
make check          # all non-formatting local gates   (needs a host toolchain)
```

Every Docker-marked target runs through `scripts/python_in_docker.sh`, so they work without a host
Python. `make validate-data` sets `MERIDIAN_REQUIRE_DATASET=1`, which turns a missing dataset
into an error rather than silently skipping the data-safety tests.

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
- `docs/PHASE_1_STATUS.md` — data-layer exit-gate evidence
- `docs/PHASE_2_STATUS.md` — model exit-gate evidence and the two documented departures from the plan
- `docs/PHASE_3_STATUS.md` — retrieval exit-gate evidence, benchmark, and chunking ablation
- `docs/PHASE_4_STATUS.md` — tool-layer and provider-adapter exit-gate evidence
- `docs/DATA_LINEAGE.md` — archive provenance and byte-exact reproduction
- `docs/MODEL_CARD.md` — generated card for the served forecaster
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

## The dataset

Every account, company, person, usage record, ticket, note, event, and outcome in this project is
synthetic and was written for it. Nothing here describes a real company or a real person.

`meridian-account-health.zip` (4.2 MB) is committed, so a fresh clone can run every gate after one
command:

```bash
unzip meridian-account-health.zip -d data/raw/
```

The extracted tree under `data/raw/` is git-ignored: it is 38 MB, and 27.5 MB of that is
re-serialized JSONL that no code in this repository reads. Raw data is immutable by policy —
`meridian.data.paths` writes only to `data/processed/`, `data/splits/`, `data/indexes/`, `models/`,
and `artifacts/`.

`dataset/` holds the generator source, data dictionary, validation report, and all 32 knowledge-base
articles as ordinary files, so how the data was produced is readable on GitHub without downloading
anything:

```text
dataset/
  build_dataset.py          entry point
  generators.py             account, usage, ticket, note, and event synthesis
  config.py                 seed 20260721, the 2026-06-28 as-of date, distributions
  text_banks.py             the phrase banks behind note and ticket prose
  build_knowledge_base.py   the 32 KB articles
  build_guardrail_eval.py   the 36 packaged guardrail cases
  DATA_DICTIONARY.md        column-level reference
  eval/validation_report.md the generator's own validation summary
  knowledge_base/           KB-001 … KB-032
```

Those files are byte-exact copies of what is inside the archive, and
`backend/tests/test_dataset_source.py` fails the build if the two ever diverge.

The generator is deterministic: `test_every_table_reproduces_the_shipped_archive` re-runs it at seed
`20260721` and asserts every table reproduces the committed archive byte for byte. That requires
`numpy < 2.5` — 2.5 alters one generated note body — which is why `pyproject.toml` caps it. See
`docs/DATA_LINEAGE.md`.

## Module 7 deliverables

The completed capstone must include:

- A final report submitted as PDF or DOCX.
- A public GitHub repository with architecture, setup, usage, code, examples, and evaluation artifacts.
- An 8–10 minute recorded presentation for a technical audience.
- A document containing the video link and a two-to-three-sentence summary.
- Optionally, a 90-second elevator pitch.

The report template, presentation outline, and any separate detailed grading rubric are intentionally deferred and are not active project blockers.
