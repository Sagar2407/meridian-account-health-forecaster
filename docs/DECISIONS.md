# Decisions

This file summarizes accepted architectural decisions and unresolved choices. Detailed implementation belongs in the implementation plan. New material decisions should be recorded as ADRs during Phase 0.

## Accepted decisions

| ID | Decision | Status | Rationale / source |
| --- | --- | --- | --- |
| D-001 | Build an Enterprise Account Health Forecaster for fictional Meridian | Accepted | Checkpoint 1.1 and all later sources |
| D-002 | Use only synthetic data and keep source data read-only | Accepted | Checkpoint 1.1, Checkpoint 6.1, Module 7 |
| D-003 | Predict four canonical outcomes: `Churned`, `Contracted`, `Renewed`, `Expanded` | Accepted | Dataset and implementation plan |
| D-004 | Separate deterministic quantitative computation from semantic qualitative retrieval | Accepted | Checkpoints 2.1–3.1 |
| D-005 | Use exactly four logical agents | Accepted | Checkpoint 5.1 |
| D-006 | Use LangGraph as the sole orchestration framework for version 1 | Accepted | Checkpoint 5.1 and implementation-plan clarification |
| D-007 | Use MCP-compatible typed tools/resources, not MCP as implicit graph state transport | Accepted | Implementation-plan clarification |
| D-008 | Do not require CrewAI in version 1 | Accepted / supersedes Checkpoint 4.1 mapping | Avoid competing orchestration frameworks while preserving generator/critic roles |
| D-009 | Use conflict-gated, bounded Tree-of-Thought | Accepted | Checkpoint 4.1 and implementation plan |
| D-010 | Use a local FAISS prototype with a vector-store adapter | Accepted | Checkpoint 3.1 and implementation plan |
| D-011 | Use React/TypeScript frontend and FastAPI/Python backend | Accepted | Final planning decisions |
| D-012 | Use a provider-neutral LLM adapter with OpenAI as the default | Accepted | Final planning decisions |
| D-013 | Use local Docker as the reproducible primary environment | Accepted | Final planning decisions |
| D-014 | Return degraded verified telemetry without a categorical label after exhausted retrieval | Accepted | Instructor feedback after Checkpoint 5.1 and Checkpoint 6.1 |
| D-015 | Never expose or persist hidden chain-of-thought | Accepted | Implementation-plan clarification and safety policy |
| D-016 | Treat autonomy as analysis, verification, routing, and review-case creation—not consequential external action | Accepted | Checkpoints 1.1 and 6.1 |
| D-017 | Use SQLite locally behind repository interfaces, with a PostgreSQL adapter path | Accepted | [ADR 0006](adr/0006-persistence-boundary.md) |
| D-018 | Grade retrieval relevance and rewrite the one permitted retry deterministically, behind `RetrievalGrader` and `QueryRewriter` protocols | Accepted | Every plan section 11.5 trigger is decidable from the retrieval result; keeps Phase 3 runnable and measurable with no API key, and leaves a model-backed grader a drop-in |
| D-019 | Derive the per-role tool allowlist from the section 13 agent definitions, giving the Forecast Adjudicator an empty one | Accepted | Section 13.4 prohibits new tool calls; an empty allowlist enforces it instead of documenting it ([Phase 4](PHASE_4_STATUS.md)) |
| D-020 | Reach Anthropic models through an OpenAI-compatible endpoint rather than a native adapter | Accepted | The wire format is identical, so only the base URL and model slug differ; one adapter covers OpenRouter, Azure, vLLM, and Ollama ([ADR 0004](adr/0004-provider-adapter.md)) |
| D-021 | Omit `role` from every advertised tool schema | Accepted | A client that can name its own role makes the section 12.3 allowlist advisory; the session is authoritative ([Phase 4](PHASE_4_STATUS.md)) |

## Decisions settled by measurement

| ID | Decision | Outcome |
| --- | --- | --- |
| P-001 | Default embedding model `BAAI/bge-small-en-v1.5` | Retained; Recall@5 0.942 over 139 graded benchmark queries, served through ONNX rather than PyTorch ([Phase 3](PHASE_3_STATUS.md)) |
| P-002 | Candidate depth 20, MMR/reranking to 5 | Retained; zero duplicate-parent citations across 243 queries, though MMR does not diversify on polarity ([Phase 3](PHASE_3_STATUS.md)) |
| P-003 | Logistic regression plus tree-based candidate models | Logistic regression selected by a one-standard-error rule, isotonic calibration ([Phase 2](PHASE_2_STATUS.md)) |

## Provisional decisions requiring measurement

| ID | Decision | Validation needed |
| --- | --- | --- |
| P-004 | Confidence formula weights 0.70/0.15/0.15 | Tune only on development/calibration data, then freeze |
| P-005 | Green ≥0.85, amber 0.70–0.84, red <0.70 | Validate routing trade-offs and freeze before held-out evaluation |
| P-006 | Render as public deployment host | Confirm current plan, cost, cold-start, and demo constraints during deployment phase |

## Open decisions

| ID | Decision needed | Blocking point |
| --- | --- | --- |
| O-003 | Select repository license | Before public GitHub publication |
| O-004 | Confirm public repository name and URL | Before report and presentation finalization |
| O-005 | Confirm September 7 deadline year and timezone in Canvas | Immediately |

## Deferred decisions

The user has deferred the official report template, presentation outline, and any separate detailed grading rubric. Do not treat them as open decisions or blockers until explicitly reactivated.

## Decision-recording rule

Phase 0 ADRs exist under `docs/adr/` for LangGraph, MCP, FAISS, provider adapters, persistence, and deployment. Every new ADR must record context, decision, alternatives, consequences, and status.
