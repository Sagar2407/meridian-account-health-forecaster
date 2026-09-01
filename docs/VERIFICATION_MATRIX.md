# Verification Matrix

This matrix separates verified facts from provisional design choices and unresolved submission inputs.

## Verified facts

| Claim | Evidence | Status |
| --- | --- | --- |
| Dataset is fully synthetic | Dataset README and all checkpoints | Verified |
| Random seed is `20260721` | `config.py` and dataset README | Verified |
| Dataset as-of date is `2026-06-28` | `config.py`, README, implementation plan | Verified |
| Forecast horizon is 90 days | `config.py`; `days_to_renewal` contains only 90 | Verified |
| Dataset contains 260 accounts | CSV and validation report | Verified |
| Outcome distribution is 47 Churned, 26 Contracted, 135 Renewed, 52 Expanded | `renewal_outcomes.csv` and validation report | Verified |
| Combined corpus has 12,860 records | `corpus_with_kb.jsonl` line count | Verified |
| Evaluation package has 23 golden questions and 36 guardrail cases | JSONL line counts | Verified |
| Knowledge base has 32 documents | Extracted package | Verified |
| Actual file names are `usage_weekly.csv`, `support_tickets.csv`, `csm_notes.csv`, and `ground_truth_drivers.json` | Extracted archive | Verified; supersedes representative checkpoint names |
| Region code `NA` must not parse as null | 116 rows verified with `keep_default_na=False` | Verified |
| External events reach `2026-07-02` | `external_events.csv` | Verified |
| Two external events occur after dataset as-of date | `external_events.csv` | Verified |
| The eight section 12.1 tools refuse path, SQL, URL, shell, over-wide window, and role-spoofing arguments | 48 tests in `test_tools_registry.py` | Verified in Phase 4 |
| No module outside `meridian.llm.openai_compatible` imports a provider SDK | `test_only_the_named_adapter_may_import_a_provider_sdk` | Verified in Phase 4 |
| Raw sources include records after per-account effective cutoffs | Direct point-in-time audit | Verified |
| The final logical architecture has four agents | Checkpoint 5.1 and implementation plan | Verified |
| ToT is conflict-only, depth 2, beam width 2, with four root outcomes | Checkpoint 4.1 and implementation plan | Verified |
| LangGraph owns orchestration; MCP exposes tools/resources | Implementation-plan Section 2.2 | Verified; resolves older wording |
| CrewAI is not required for version 1 | Implementation-plan Section 2.2 | Verified; supersedes Checkpoint 4.1 tool mapping |
| Exhausted retrieval must not produce an unsupported categorical label | Instructor feedback recorded in plan and Checkpoint 6.1 | Verified |
| Module 7 requires a final report, public repo, and 8–10 minute technical presentation | User-provided Module 7 Canvas text | Verified |
| `csm_notes.csv` has 6,420 rows | Parsed row count; `wc -l` overcounts because note bodies contain newlines | Verified in Phase 1 |
| Cutoff filtering removes 17,927 fact rows (14,931 usage, 1,506 tickets, 1,376 notes, 114 events) | `make data` output; `test_no_runtime_record_postdates_its_account_cutoff` | Verified in Phase 1 |
| `adoption_level_last_q` reaches 109.04, exceeding its documented 0–100 range | `account_features.csv`; supersedes the data dictionary | Verified in Phase 1 |
| The archive reproduces byte for byte from the generator at seed `20260721` | `test_every_table_reproduces_the_shipped_archive` | Verified in Phase 1 |
| Byte-exact reproduction requires `numpy < 2.5`; numpy 2.5.2 alters one note body (`NOTE-204709`) | Controlled comparison holding Python, pandas, and seed constant | Verified in Phase 1 |
| Permitted missing values are 575 CSAT, 575 resolution hours, 135 outcome reasons, 231 usage-cliff dates | `test_permitted_missing_values_are_explicit` | Verified in Phase 1 |
| All 36 packaged guardrail cases pass their named checks | `make evaluate-guardrails`; ignored JSON, CSV, and Markdown artifacts under `artifacts/safety/` | Verified in Phase 7 |
| Hard-category false-pass and answerable false-block rates are both 0.0000 | 15 hard and 21 answerable cases in the Phase 7 safety report | Verified in Phase 7 |
| Released evaluation results contain no target, wrong-account, or post-cutoff leakage findings | Whole-result leakage audit across the 36-case run | Verified in Phase 7 |
| Reviewer overrides resolve the case and create a linked regression on one transaction | Store rollback test and FastAPI end-to-end test | Verified in Phase 7 |

## Point-in-time audit

| Raw source | Rows after per-account effective cutoff | Required action |
| --- | ---: | --- |
| Weekly usage | 14,931 | Filter before features or display |
| Support tickets | 1,506 | Filter before aggregation and indexing |
| CSM notes/QBRs | 1,376 | Filter before indexing and retrieval |
| External events | 114 | Filter before aggregation/retrieval; also apply dataset as-of cap |

## Provisional choices

| Choice | Why provisional | Resolution method |
| --- | --- | --- |
| Confidence weights and route thresholds | Implemented in `meridian.graph.confidence` and `meridian.graph.routing`, but still the plan's initial policy values | Development calibration and route-cost analysis, frozen before held-out evaluation |
| Tool timeout of 20 seconds and one transient retry | Chosen before any latency measurement | Measure tool latency in Phase 10 observability |
| Render hosting | Portfolio recommendation, not a course mandate | Deployment feasibility and cost review |
| Fast-path latency target | Provisional target | Measure after implementation |

## Resolved by measurement

| Choice | How it was resolved | Outcome |
| --- | --- | --- |
| Predictive model family | Repeated stratified CV, one-standard-error rule, calibration study | Logistic regression with isotonic calibration; see `docs/PHASE_2_STATUS.md` |
| BGE small embedding model | Curated four-family retrieval benchmark | Retained; see `docs/PHASE_3_STATUS.md` |
| FAISS configuration and MMR parameters | Chunking ablation holding corpus, encoder, filters, top-k, and queries constant | Flat inner-product index and parent-child chunking retained on recall and citation quality, not on ranking metrics; see `docs/PHASE_3_STATUS.md` |
| Provider-neutral LLM adapter | Offline structured-generation tests plus an opt-in live check | Anthropic reached through OpenRouter's OpenAI-compatible endpoint; strict `json_schema` with one repair attempt; see `docs/PHASE_4_STATUS.md` |
| Whether the two evidence lanes run in parallel | Instrumented lanes recording entry and exit, checked for interval overlap | Confirmed concurrent; adjacent trace events were not treated as evidence; see `docs/PHASE_5_STATUS.md` |
| Whether conflict-gated ToT beats linear adjudication | Both arms over the same 106 conflicting development accounts, paired on the cases both answered | Not on this evidence: 86.5% agreement, 69 declined answers for 12 caught errors against a 15.1% base rate; the provider arm is unrun; see `docs/PHASE_6_STATUS.md` |
| Whether output verification could reject a fabricated claim | One live provider run against the real graph | Two real defects found and fixed: the citation check was self-referential, and the field-leak check rejected the English word "outcome"; see `docs/PHASE_5_STATUS.md` |
| Whether the packaged guardrail policy passes its hard safety gate | All 36 cases through the offline graph, with per-case behavioural grading and whole-result leakage checks | 0/15 hard false passes, 0/21 false blocks, 0 leakage findings, and 36/36 behavioural checks passed; see `docs/PHASE_7_STATUS.md` |

## Unresolved inputs

| Item | Consequence | Next action |
| --- | --- | --- |
| Deadline year/timezone absent from pasted text | Submission scheduling risk | Verify Canvas deadline directly |
| Repository license not selected | Public-release blocker | Choose license before publication |
| Backend image is 2.64 GB | Cold-start and disk pressure on the Phase 11 deployment target | Measure on Render; consider a serving image without training and evaluation dependencies |
| Public repository and live-demo URLs absent | Final report/presentation incomplete | Create during Phase 11 |
| The provider arm of the ToT ablation is unrun | The measured verdict covers only the deterministic configuration | Run `scripts/evaluate_tot.py --use-provider`; it costs money and about an hour |
| Numeric replay reads numerals, not number words | "Five of six drivers" is unverified where "5 of 6" would be | Normalize a bounded number-word vocabulary before public evaluation |

## Deferred inputs

The official report template, presentation outline, and any separate detailed grading rubric are intentionally out of scope for now. Do not raise them as unresolved inputs until the user reactivates them.

## Readiness decision

Phases 0 through 7 are complete. The latest `make phase0-verify` rebuilt both
locked images, passed formatting, lint, strict typing, 485 backend container
tests at 95.24% coverage, 7 frontend tests, the production frontend build, the
repository policy scan over 242 files, and both live container health checks. The separate
Phase 7 safety run passed all 36 cases without a provider. Phase 8 may begin;
deferred submission artifacts do not affect implementation readiness.
