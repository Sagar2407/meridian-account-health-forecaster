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
| BGE small embedding model | Reasonable design, not yet benchmarked in this repository | Retrieval evaluation |
| FAISS configuration and MMR parameters | Submitted design but performance unknown | Chunking/retrieval ablation |
| Predictive model family | Dataset is small and class-imbalanced | Repeated stratified CV and calibration |
| Confidence weights and route thresholds | Initial policy values only | Development calibration and route-cost analysis |
| Render hosting | Portfolio recommendation, not a course mandate | Deployment feasibility and cost review |
| Fast-path latency target | Provisional target | Measure after implementation |

## Unresolved inputs

| Item | Consequence | Next action |
| --- | --- | --- |
| Deadline year/timezone absent from pasted text | Submission scheduling risk | Verify Canvas deadline directly |
| Repository license not selected | Public-release blocker | Choose license before publication |
| Public repository and live-demo URLs absent | Final report/presentation incomplete | Create during Phase 11 |

## Deferred inputs

The official report template, presentation outline, and any separate detailed grading rubric are intentionally out of scope for now. Do not raise them as unresolved inputs until the user reactivates them.

## Readiness decision

Context onboarding is complete and Phase 0 implementation is present. Static source, configuration,
shell, repository-policy, and documentation checks pass. Dependency-backed checks, lockfile
generation, and the Docker health-page test remain open because package registry access and Docker
are unavailable in the current workspace. Data/model/RAG implementation must not begin until those
Phase 0 exit criteria pass or the user explicitly changes scope. Deferred deliverable artifacts do
not affect Phase 0 readiness.
