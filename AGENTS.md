# Meridian Autonomous Agent — Repository Instructions

## Purpose

This repository contains the CMU Agentic AI Program capstone: a read-only Enterprise Account Health Forecaster for the fictional B2B SaaS vendor Meridian. It predicts one of four renewal outcomes, explains the drivers with verifiable evidence, recommends a bounded next action, and routes uncertain or consequential cases to human review.

## Source-of-truth order

When sources disagree, use this precedence:

1. `docs/source/MODULE_7_CAPSTONE_REQUIREMENTS.md` for final submission requirements.
2. `docs/Meridian_Autonomous_System_Implementation_Plan.md` for the current build specification and explicit resolutions of earlier design conflicts.
3. Checkpoints 1.1–6.1 for design history, with later checkpoints superseding earlier details.
4. The extracted dataset `README.md`, `DATA_DICTIONARY.md`, `config.py`, and actual packaged artifacts for schema and data facts.
5. Generated documentation and code, which must remain consistent with the sources above.

Do not treat old representative filenames or framework mappings as current requirements.

## Mandatory reading

Before architectural or implementation changes, read:

- `README.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/REQUIREMENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_SAFETY.md`
- `docs/DECISIONS.md`
- The relevant phase in `docs/Meridian_Autonomous_System_Implementation_Plan.md`
- `data/raw/meridian-account-health/README.md`
- `data/raw/meridian-account-health/DATA_DICTIONARY.md`

Check `docs/VERIFICATION_MATRIX.md` before relying on a numeric or architectural claim.

## Locked invariants

- Source data is synthetic and immutable at runtime.
- Enforce `effective_cutoff = min(account.forecast_as_of_date, 2026-06-28)` for every runtime query and retrieval.
- Never expose or use latent, target, or evaluation-only fields in runtime features, prompts, tools, indexes, traces, or APIs.
- Numbers come from deterministic code, never LLM arithmetic.
- Qualitative account claims require verified, account-scoped, point-in-time citations.
- Exactly four logical agents: Orchestrator/Planner, Quantitative Analyst, Evidence Retriever, Forecast Adjudicator.
- LangGraph owns orchestration and per-run shared state. MCP exposes typed tools/resources; it is not the graph state transport.
- Tree-of-Thought is bounded and conflict-gated: four root outcomes, depth two, beam width two.
- Retrieval rewrite/retry is bounded to one. Exhaustion must not produce an unsupported categorical label.
- Never expose hidden chain-of-thought. Store structured summaries, evidence, scores, and route reasons only.
- The system is decision support. It must not contact customers, mutate source records, or make commercial commitments.

## Development workflow

Implement one numbered phase at a time. Before starting a phase:

1. Read its requirements and exit gate.
2. Inspect existing implementation and tests.
3. Identify dependencies and unresolved decisions.
4. Implement the smallest coherent phase deliverable.
5. Add failure-path tests as well as happy-path tests.
6. Run the phase validation commands.
7. Report every exit criterion as `PASS`, `FAIL`, or `NOT TESTED`.

Do not proceed to the next phase until the current exit gate passes or the user explicitly changes scope.

## Engineering rules

- Use typed schemas at state, tool, API, provider, forecast, review, and persistence boundaries.
- Bound retries, loops, model calls, concurrency, and public-demo spending.
- Represent failure states explicitly; never swallow exceptions or fabricate missing evidence.
- Keep runtime and evaluation repositories physically separate.
- Do not commit secrets or machine-specific absolute paths.
- Keep documentation synchronized with material architectural changes.
- Do not claim an evaluation result until a reproducible artifact exists.

## Current status

Phases 0 through 10 are complete and every exit gate passes; evidence is in `docs/PHASE_<n>_STATUS.md`. The raw dataset is extracted under `data/raw/meridian-account-health/`. Decision thresholds are frozen at digest `5e23d7f9d9fef896` (v1) and the held-out split has been run against them: do not change a threshold without bumping `THRESHOLD_VERSION` and recording development-split evidence. Phase 11's configuration is built and verified against the local production image; the deploy itself is not done, and `docs/DEPLOYMENT.md` records the two blockers. The repository is licensed Apache-2.0 and is deliberately still private. Do not start it without closing the current gate or receiving an explicit user scope change.

Run `make phase0-verify` before declaring any phase finished: it is the only check that builds the locked images and runs the suite the way CI does. A host-only run has passed while the container run failed more than once.

Nothing in the repository requires an API key. When one is configured in `.env`, `GraphRuntime.build()` will use it and bill the account, so pass `--offline` (or `OFFLINE=1` to `make assess`) unless a live call is what you intend.

The user has intentionally deferred the official report template, presentation outline, and any separate detailed grading rubric. Do not raise, search for, or treat those items as blockers unless the user reactivates them.
