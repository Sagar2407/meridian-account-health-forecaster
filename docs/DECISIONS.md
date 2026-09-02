# Decisions

This file summarizes accepted architectural decisions and unresolved choices. Detailed implementation belongs in the implementation plan. New material decisions should be recorded as ADRs during Phase 0.

## Accepted decisions

| ID | Decision | Status | Rationale / source |
| --- | --- | --- | --- |
| D-001 | Build an Enterprise Account Health Forecaster for fictional Meridian | Accepted | Stage 1, and unchanged since |
| D-002 | Use only synthetic data and keep source data read-only | Accepted | Stages 1 and 6 |
| D-003 | Predict four canonical outcomes: `Churned`, `Contracted`, `Renewed`, `Expanded` | Accepted | Dataset and implementation plan |
| D-004 | Separate deterministic quantitative computation from semantic qualitative retrieval | Accepted | Stages 2 and 3 |
| D-005 | Use exactly four logical agents | Accepted | Stage 5 |
| D-006 | Use LangGraph as the sole orchestration framework for version 1 | Accepted | Stage 5, and the implementation plan's clarification |
| D-007 | Use MCP-compatible typed tools/resources, not MCP as implicit graph state transport | Accepted | Implementation-plan clarification |
| D-008 | Do not require CrewAI in version 1 | Accepted / supersedes the stage 4 mapping | Avoid competing orchestration frameworks while preserving generator/critic roles |
| D-009 | Use conflict-gated, bounded Tree-of-Thought | Accepted | Stage 4 and the implementation plan |
| D-010 | Use a local FAISS prototype with a vector-store adapter | Accepted | Stage 3 and the implementation plan |
| D-011 | Use React/TypeScript frontend and FastAPI/Python backend | Accepted | Final planning decisions |
| D-012 | Use a provider-neutral LLM adapter with OpenAI as the default | Accepted | Final planning decisions |
| D-013 | Use local Docker as the reproducible primary environment | Accepted | Final planning decisions |
| D-014 | Return degraded verified telemetry without a categorical label after exhausted retrieval | Accepted | A design review after stage 5, confirmed in stage 6 |
| D-015 | Never expose or persist hidden chain-of-thought | Accepted | Implementation-plan clarification and safety policy |
| D-016 | Treat autonomy as analysis, verification, routing, and review-case creation—not consequential external action | Accepted | Stages 1 and 6 |
| D-017 | Use SQLite locally behind repository interfaces, with a PostgreSQL adapter path | Accepted | [ADR 0006](adr/0006-persistence-boundary.md) |
| D-018 | Grade retrieval relevance and rewrite the one permitted retry deterministically, behind `RetrievalGrader` and `QueryRewriter` protocols | Accepted | Every plan section 11.5 trigger is decidable from the retrieval result; keeps Phase 3 runnable and measurable with no API key, and leaves a model-backed grader a drop-in |
| D-019 | Derive the per-role tool allowlist from the section 13 agent definitions, giving the Forecast Adjudicator an empty one | Accepted | Section 13.4 prohibits new tool calls; an empty allowlist enforces it instead of documenting it ([Phase 4](PHASE_4_STATUS.md)) |
| D-020 | Reach Anthropic models through an OpenAI-compatible endpoint rather than a native adapter | Accepted | The wire format is identical, so only the base URL and model slug differ; one adapter covers OpenRouter, Azure, vLLM, and Ollama ([ADR 0004](adr/0004-provider-adapter.md)) |
| D-021 | Omit `role` from every advertised tool schema | Accepted | A client that can name its own role makes the section 12.3 allowlist advisory; the session is authoritative ([Phase 4](PHASE_4_STATUS.md)) |
| D-022 | The language model never chooses the outcome label; it writes the rationale, limitations, and action | Accepted | The calibrated forecaster produces the class distribution, and `AdjudicationDraft` has no outcome field, so the label is unreachable from a generated reply ([Phase 5](PHASE_5_STATUS.md)) |
| D-023 | Split supporting evidence from counterevidence using structured source metadata only | Accepted | Ticket category and priority, note type, and the dataset's own event polarity decide it; a text classifier inside a safety control would be a second unvalidated model ([Phase 5](PHASE_5_STATUS.md)) |
| D-024 | The graph calls `ToolRegistry` directly; MCP remains the external transport | Accepted | Section 12.3's allowlist, validation, and audit all live in the registry, so a protocol round trip to ourselves would add a hop without adding a control; `test_the_protocol_and_the_registry_return_the_same_answer` keeps the two paths honest ([Phase 5](PHASE_5_STATUS.md)) |
| D-025 | A run with no provider completes with a deterministic narrative rather than failing | Accepted | Section 14.3 requires exact telemetry with an unavailable-analysis notice; a sentence built only from verified values cannot hallucinate, and it caps the route at amber ([Phase 5](PHASE_5_STATUS.md)) |
| D-026 | Shared section 9.1 contracts live at `meridian.contracts`, not inside `meridian.graph` | Accepted | Agents, guardrails, and the graph all depend on them; importing the graph package to name an agent's return type made the graph a dependency of the agents it is built from ([Phase 5](PHASE_5_STATUS.md)) |
| D-027 | Add `prior_assessments` and `ForecastDecision.cited_doc_ids` to the section 9.2 field list | Accepted | The planner needs its own history as context, and output verification has to replay the citations a narrative *claimed* rather than the evidence set it was given ([Phase 5](PHASE_5_STATUS.md)) |
| D-028 | At a conflict the outcome is selected from the four canonical classes by a deterministic score, never generated | Accepted | The four candidates are supplied one per outcome and the critic is deterministic, so a model may argue a case but cannot add an outcome, change a prior, or award a point ([Phase 6](PHASE_6_STATUS.md)) |
| D-029 | Weight section 15.4's five rubric dimensions equally | Accepted | The plan names the dimensions and no weights; any other split would be a number chosen to no criterion. Frozen before evaluation per section 22.7 ([Phase 6](PHASE_6_STATUS.md)) |
| D-030 | Measure `baseline_plausibility` against the most likely outcome rather than in absolute terms | Accepted | Four priors summing to one compress into a narrow band, and an absolute reading could not separate the model's clear favourite from an also-ran ([Phase 6](PHASE_6_STATUS.md)) |
| D-031 | Skip a relative conflict rule when no portfolio baseline is available | Accepted | Comparing against a default of zero would classify every account as above median and fire the rule on the whole portfolio ([Phase 6](PHASE_6_STATUS.md)) |
| D-032 | Run the ToT ablation on the development split only | Accepted | Section 22.7 forbids tuning against held-out outcomes, and the comparison exists to inform a threshold ([Phase 6](PHASE_6_STATUS.md)) |
| D-033 | Send a failed Tree-of-Thought draft to the safe fallback rather than to linear regeneration | Accepted | `fast_adjudication` rebuilds the decision around the model's argmax, so regenerating a search winner there would return a different outcome under the same run id ([Phase 6](PHASE_6_STATUS.md)) |
| D-034 | Treat intake, execution, evidence, output, and routing as typed guardrail stages on every non-blocked run | Accepted | One accumulated contract makes a missing control observable in traces and tests instead of relying on which path happened to execute ([Phase 7](PHASE_7_STATUS.md)) |
| D-035 | Quarantine an evidence boundary violation for the rest of the run, even if a later retry is clean | Accepted | A retry may recover coverage, but it cannot prove that wrong-account, post-cutoff, or invalid-provenance evidence did not influence earlier state; the final route is therefore red ([Phase 7](PHASE_7_STATUS.md)) |
| D-036 | Pause only interactive red runs, and only when a checkpointer and stored review case exist | Accepted | Portfolio scans must not block, while an uncheckpointed or unpersisted pause would strand a run no reviewer can resume ([Phase 7](PHASE_7_STATUS.md)) |
| D-037 | Resolve a reviewer correction and insert its regression record in one transaction | Accepted | A human-corrected released answer without the linked replay case would make the Phase 7 audit trail incomplete ([Phase 7](PHASE_7_STATUS.md)) |
| D-038 | Refuse to run any evaluation harness over HTTP; serve its published artifact instead | Accepted | Every harness reads outcome labels, and section 8.4 forbids a served module importing `meridian_eval`; a lazy import would hide the leak rather than prevent it ([Phase 8](PHASE_8_STATUS.md)) |
| D-039 | Measure a scan's peak concurrency from inside the work rather than reporting the configured limit | Accepted | The exit gate is that the bound held, and a scan that echoed its own settings would pass it whatever it did ([Phase 8](PHASE_8_STATUS.md)) |
| D-040 | Reserve the per-run model-call ceiling before dispatch and refund the unused remainder | Accepted | Charging after a run completes lets every worker pass the same check at once and overspend by the pool's width ([Phase 8](PHASE_8_STATUS.md)) |
| D-041 | Select scan eligibility against each account's own forecast date, not wall-clock today | Accepted | The synthetic dataset never moves, so a today-based horizon would select a different portfolio daily from identical data ([Phase 8](PHASE_8_STATUS.md)) |
| D-042 | Require both `enable_scheduler` and the absence of `demo_mode`, and refuse rather than degrade | Accepted | Section 24.3 disables unattended spending in public deployment; a scheduler that silently downgrades leaves an operator believing scans are running ([Phase 8](PHASE_8_STATUS.md)) |
| D-043 | Draw every chart as hand-written SVG rather than adding a charting library | Accepted | Each figure is a line, a bar, or an arc; a library would outweigh the whole application on a target where image size affects cold start, and the accessible names matter more than the drawing ([Phase 9](PHASE_9_STATUS.md)) |
| D-044 | Serve the account page's chart, indicators, and recent activity from the single account endpoint | Accepted | Five requests would let one page render a chart from one point in time beside indicators from another; one request at one cutoff cannot, and the served surface stays equal to section 19.1's table ([Phase 9](PHASE_9_STATUS.md)) |
| D-045 | Show an abstention the evidence it retrieved before declining to label | Accepted | A reviewer deciding whether the system was right to withhold a label needs to see what it read; the card previously dropped it on exactly those runs ([Phase 9](PHASE_9_STATUS.md)) |
| D-046 | Forbid `test.skip(true, ...)` on a condition the test itself creates | Accepted | The review-override journey skipped whenever the queue was empty, so the exit gate could pass without ever exercising an override ([Phase 9](PHASE_9_STATUS.md)) |
| D-047 | Freeze decision thresholds as digested source with no runtime override | Accepted | A threshold an operator can move between runs is not a calibration, and a held-out result measured against a movable threshold means nothing (section 22.7, [Phase 10](PHASE_10_STATUS.md)) |
| D-048 | Keep the frozen bands despite a 2.9% auto-release rate | Accepted | Loosening to 0.60/0.50 would release twelve times more at a measured 5.7% unreviewed error rate; that trade is a business decision about the cost of a wrong advisory call, not one the data settles ([Phase 10](PHASE_10_STATUS.md)) |
| D-049 | Collect every dimension from one pass over a split | Accepted | Three of the five dimensions are properties of runs, and one pass with structured records replays exactly what four passes would have measured ([Phase 10](PHASE_10_STATUS.md)) |
| D-050 | Render the report only from the result dictionary | Accepted | The exit gate is that every claim is traceable to an artifact; a formatter with no literals in it makes that structural rather than promised ([Phase 10](PHASE_10_STATUS.md)) |
| D-051 | Report a Tree-of-Thought candidate's neutral evidence rather than citing nothing | Accepted | An account whose citations are all directionally neutral left both candidate lists empty, failing output verification on every such run ([Phase 10](PHASE_10_STATUS.md)) |
| D-052 | Return the same structured `RouteVerdict` from `abstention_route` as from `human_route` | Accepted | Abstentions were the only runs carrying no rule codes, and section 22.6's safe-fallback target measures exactly those runs, so the metric silently counted nothing ([Phase 10](PHASE_10_STATUS.md)) |
| D-053 | Pin the browser's declared types against the Pydantic models they mirror | Accepted | The decision card is served as `dict[str, Any]` and has no schema; three defects drifted through that seam without either type-checker noticing ([Phase 10](PHASE_10_STATUS.md)) |
| D-054 | Use one `EvidenceSignal` vocabulary across the whole API | Accepted | A citation said `adverse/favorable` and a recent item said `positive/negative`; one API with two spellings of the same idea is one more thing to get wrong, and the browser already had ([Phase 10](PHASE_10_STATUS.md)) |
| D-055 | Licence the repository under Apache-2.0 | Accepted | Permissive, with an explicit patent grant and contributor terms; closes O-003 ([Phase 11](DEPLOYMENT.md)) |
| D-056 | Ship one production image that omits `meridian_eval` entirely | Accepted | The evaluation package reads outcome labels; a served process should not be able to import it even by mistake ([Phase 11](DEPLOYMENT.md)) |
| D-057 | Make every cached demo run carry an unremovable `is_cached` marker | Accepted | Section 24.3 forbids showing a cached run as live; a label that a flag can turn off is a label that will eventually be off ([Phase 11](DEPLOYMENT.md)) |
| D-058 | Render FastAPI's own 404s and 405s in the documented error shape | Accepted | Section 19.3 promises a stable code on every failure, and an unmatched route returned `{"detail": ...}` — the shape a client hits most while being written ([Phase 11](DEPLOYMENT.md)) |

## Decisions settled by measurement

| ID | Decision | Outcome |
| --- | --- | --- |
| P-001 | Default embedding model `BAAI/bge-small-en-v1.5` | Retained; Recall@5 0.942 over 139 graded benchmark queries, served through ONNX rather than PyTorch ([Phase 3](PHASE_3_STATUS.md)) |
| P-007 | Conflict-gated Tree-of-Thought over linear adjudication | Measured offline on the development split: the search agrees with the linear path on 86.5% of shared cases and declines 69 answers to catch 12 errors. Not yet earning its place; the provider arm is unrun ([Phase 6](PHASE_6_STATUS.md)) |
| P-002 | Candidate depth 20, MMR/reranking to 5 | Retained; zero duplicate-parent citations across 243 queries, though MMR does not diversify on polarity ([Phase 3](PHASE_3_STATUS.md)) |
| P-003 | Logistic regression plus tree-based candidate models | Logistic regression selected by a one-standard-error rule, isotonic calibration ([Phase 2](PHASE_2_STATUS.md)) |

## Provisional decisions requiring measurement

| ID | Decision | Validation needed |
| --- | --- | --- |
| P-004 | Confidence formula weights 0.70/0.15/0.15 | Implemented unchanged in `meridian.graph.confidence` ([Phase 5](PHASE_5_STATUS.md)); still to be tuned on development/calibration data and frozen before held-out testing |
| P-005 | Green ≥0.85, amber 0.70–0.84, red <0.70 | Implemented with every section 16.5 condition ([Phase 5](PHASE_5_STATUS.md)); routing trade-offs still to be validated and frozen before held-out evaluation |
| P-006 | Render as public deployment host | Confirm current plan, cost, cold-start, and demo constraints during deployment phase |

## Open decisions

| ID | Decision needed | Blocking point |
| --- | --- | --- |
| ~~O-003~~ | ~~Select repository license~~ | **Closed: Apache-2.0, see D-055** |
| O-004 | How the dataset, model, and retrieval index reach the production image | Before any public deployment; see `docs/DEPLOYMENT.md` |
| O-005 | Whether to loosen the release bands, given that auto-release is near zero | The measured trade-off is recorded; the choice is a business one |

## Decision-recording rule

Phase 0 ADRs exist under `docs/adr/` for LangGraph, MCP, FAISS, provider adapters, persistence, and deployment. Every new ADR must record context, decision, alternatives, consequences, and status.
