# Verification Matrix

This matrix separates verified facts from provisional design choices and open questions.

## Verified facts

| Claim | Evidence | Status |
| --- | --- | --- |
| Dataset is fully synthetic | Dataset README and the generator in `dataset/` | Verified |
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
| The final logical architecture has four agents | Implementation plan section 13 | Verified |
| ToT is conflict-only, depth 2, beam width 2, with four root outcomes | Implementation plan section 15 | Verified |
| LangGraph owns orchestration; MCP exposes tools/resources | Implementation-plan Section 2.2 | Verified; resolves older wording |
| CrewAI is not required for version 1 | Implementation-plan Section 2.2 | Verified; supersedes the earlier tool mapping |
| Exhausted retrieval must not produce an unsupported categorical label | Design review recorded in the implementation plan | Verified |
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
| A portfolio scan never exceeds its configured concurrency | Peak counted inside the worker pool; asserted at 3, 2, and exactly 1 | Verified in Phase 8 |
| A portfolio scan never exceeds its model-call budget | A zero budget scans nothing; an offline scan spends 0 of 200 | Verified in Phase 8 |
| The served API is exactly section 19.1's endpoint table | `test_openapi_is_section_19s_endpoint_table` compares the OpenAPI path set | Verified in Phase 8 |
| No served response carries a prompt, a model reply, or a latent field | Whole-payload scan of a completed run against `FORBIDDEN_TRACE_KEYS` and the latent-field list | Verified in Phase 8 |
| No response the browser receives carries a latent field or a prompt key | A Playwright response listener over the portfolio, an assessment, the review queue, a decision card, and the evaluation page | Verified in Phase 9 |
| Every core user journey works end to end in a browser | 24 Playwright tests, desktop and tablet, against the real stack, 0 skipped | Verified in Phase 9 |
| A reviewer override in the UI files a traceable regression record | The override journey reads the regression id back from the page | Verified in Phase 9 |
| Macro F1 on the held-out split is 0.7490, against a 0.4595 majority baseline | 53 test accounts, thresholds frozen at `5e23d7f9d9fef896` | Verified in Phase 10 |
| Supported-claim rate and exact numeric agreement are both 1.0000 on both splits | 137 development and 37 held-out released runs | Verified in Phase 10 |
| No wrong-account or post-cutoff citation on either split | 260 runs across both splits | Verified in Phase 10 |
| Error rate rises monotonically green to amber to red | 0.000 / 0.029 / 0.127 on the development split | Verified in Phase 10 |
| Every claim in the evaluation report comes from its result file | `render()` formats the result and holds no literal; a test asserts every named artifact exists | Verified in Phase 10 |
| The browser's types match the models the API sends | `test_browser_contract.py` compares field names and literal unions against the Pydantic models | Verified in Phase 10 |
| An abstention carries rule codes like any other route | Section 22.6's safe-fallback target now measures 1.0000 over the development run that reaches it | Verified in Phase 10 |
| Every page passes an automated WCAG 2.0/2.1 A and AA audit | axe-core over six routes on two viewports; it found `--ink-faint` at 4.09:1 and the green status pill at 4.43:1 against a 4.5:1 requirement, and both were darkened | Verified by `frontend/e2e/accessibility.spec.ts` |
| The layout does not change without someone deciding it should | Committed pixel baselines for the portfolio, a curated demo run, and the not-found page, on both viewports | Verified by `frontend/e2e/layout.spec.ts` |
| Corpus size does not change retrieval results, because account filtering precedes ranking | The chunking ablation over 10,459 documents from 260 accounts returns metrics identical to four decimals to the 853-document run | Verified by `artifacts/retrieval/full_corpus/` |
| The review queue is ordered by all four of section 20.5's keys | Route, then ACV, then renewal proximity, then age, applied before `limit` rather than after | Verified by `backend/tests/test_review_queue_priority.py` |
| Numeric replay reads number words as well as numerals | "five of six" and "5 of 6" replay identically; `one` and `zero` count only inside a ratio | Verified by `backend/tests/test_numeric_replay_words.py` |
| The production image serves the API and the browser bundle from one process | `make prod-up`, then the shell at `/`, a client route at `/review`, a hashed asset, and `/api/health` all answered correctly | Verified in Phase 11 |
| Demo mode replaces free text and refuses scans in the production image | A poem request came back as the curated question; a scan returned `REQUEST_BLOCKED` | Verified in Phase 11 |
| Every curated demo run is marked as a recording | Four cached runs, each carrying `is_cached` and a note naming the commit and moment | Verified in Phase 11 |
| Every API failure carries a stable code | FastAPI's own 404s now render in the documented shape too | Verified in Phase 11 |
| The published architecture diagram matches the compiled graph | Diagram rewritten with the graph's own node names; two wrong edges corrected against `graph/builder.py` | Verified in Phase 12 |
| Four representative graph paths are captured from real runs | `artifacts/traces/`; fast, ToT, degraded, and human-review, all offline at 0 tokens | Verified in Phase 12 |
| Every offline artifact regenerates at the current commit | `evaluate-tot`, `evaluate-guardrails`, `evaluate-retrieval`, and a scan re-run; the ToT ablation was found stale and refreshed | Verified in Phase 12 |
| Evaluation artifacts are tracked, not gitignored | `artifacts/` (676 KB) is committed; `models/` and `data/indexes/` remain ignored | Verified in Phase 12 |

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
| Render hosting | Portfolio recommendation, not a course mandate | Deployment feasibility and cost review |

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
| Confidence weights and route thresholds | Frozen in `meridian.graph.thresholds` before the held-out split was evaluated, with a content digest a test pins | `5e23d7f9d9fef896` (v1); the sweep that informed them runs on development data only; see `docs/PHASE_10_STATUS.md` |
| Tool timeout of 20 seconds, and the fast-path latency target | Measured across every assessed account on both splits | Offline, p50 is 160 ms (held out) and 165 ms (development); p95 is 261 ms and 313 ms -- roughly two orders below the 20 s timeout. Reported per path in each `results.json` |
| Whether a portfolio scan produces usable output at current thresholds | One offline scan of 6 eligible accounts, repeated over 12 in Phase 12 | **No.** 0 auto-released at either size; 6 of 6 and then 12 of 12 queued for review. The routing is correct per section 16.5, and a queue containing everything saves no work; see `docs/PHASE_8_STATUS.md` |
| What loosening the review bands would buy | 29 candidate band pairs replayed over 207 development runs | Twelve times the release rate (6 to 70 of 207) at a 5.7% unreviewed error rate. No threshold was changed: the trade is a business decision; see `docs/PHASE_10_STATUS.md` |
| Whether the confidence score ranks correctly | Error rate inside each review band, 207 development runs | Yes: 0.000 green, 0.029 amber, 0.127 red, and all 8 errors landed in red. ECE says the absolute scale is over-confident even though the ranking is sound |

## Unresolved inputs

| Item | Consequence | Next action |
| --- | --- | --- |
| The production image is self-contained | `make prod-up` runs it with zero mounts: `/api/health` reports `ok` with all four data subsystems ready, 15 endpoint checks pass, and assessments complete and open review cases | Verified locally; see `docs/DEPLOYMENT.md` |
| A deploy was attempted and the service does not answer | Phase 11's exit gate cannot be evaluated, and cold-start behaviour on the target stays unmeasured; local timings are in `docs/DEPLOYMENT.md` | Seven probes of `meridian-125g.onrender.com/api/health` returned `HTTP 000` with TLS completing. Memory is ruled out: the production container peaks at 226 MB against a 512 MB cap. Read the Render build log; see `docs/PHASE_11_STATUS.md` |
| The serving image is 1.55 GB | Cold-start and disk pressure on the deployment target | 2.2 GB before discarding uv's build cache in the layer that creates it, then +80 MB to carry the runtime data and the embedding model so the image needs no mounts. The development image is still 2.75 GB because it installs the dev extra. Re-measure on Render once deployed |
| The model-backed path has run against a real provider | One complete assessment on `liquid/lfm-2.5-2.6b:free`, planner and adjudicator both `source: model`, output verification passed first attempt, 7,382 tokens, 0.00 USD | Verified by `artifacts/provider/open_weight_run.json` |
| The provider arm of the ToT ablation is unrun | The measured verdict covers only the deterministic configuration | Run `scripts/evaluate_tot.py --use-provider`; it costs money and about an hour |
| Expected calibration error is 0.1712 held out, against a 0.10 target | The release bands sit on an over-confident probability scale | Refit calibration on development data and re-freeze; section 22.7 forbids recalibrating on the held-out result now measured |
| Auto-release rate is 0.0000 on the held-out split | The system produces only review load | The measured trade-off is recorded; choosing a band is the owner's decision |
| `Contracted` has two held-out examples | Its per-class F1 of 0.2857 is not a measurement | Report it, do not read it |
| The portfolio scan has not been run with a provider | Scan cost and latency are measured only for the deterministic path | Run `scripts/scan_portfolio.py --use-provider`; it costs money per account |
| Serving state is per process and in memory | Live runs, scans, and rate-limit windows do not survive a restart or a second replica | Correct for the single-container target; a scaled deployment needs a shared store |
| The review-decision endpoint is unauthenticated and demo mode does not cover it | Anyone who can reach a public deployment can resolve review cases, and other visitors see them resolved until the container is replaced | Mitigated, not fixed: `data/app` lives in the container layer, so state resets whenever the container is replaced — measured as surviving a restart and gone in a fresh container. Add authentication before attaching any persistent disk (`docs/DEPLOYMENT.md` blocker 2) |

## Readiness

Eleven of the twelve phases are complete. Phase 11 is not: its exit gate needs a
public link that completes the curated demo paths, and no deployment answers, so
the phase is open and `docs/PHASE_11_STATUS.md` records where it stands.

The latest `make phase0-verify` rebuilt both locked images and passed formatting
over 152 files, lint, strict typing over 151 source files, 658 backend tests with
40 expected skips at 94.86% coverage, 98 frontend tests, the production frontend
build, the repository policy scan over 343 files, and both live container health
checks.

The gate mounts the extracted archive, so those 40 skips are not data-layer
tests. Run with the archive absent -- the backend image excludes it -- 377 pass
and 321 skip; `MERIDIAN_REQUIRE_DATASET=1` turns that absence into an error so
neither configuration can go green vacuously. `make validate-data` is the
with-archive run: 697 pass, 1 skips, 94.85% coverage.

The safety suite passes all 36 cases without a provider, the portfolio scan holds
its concurrency and budget bounds, the browser suite passes 42 tests with none
skipped -- 24 journeys, 12 WCAG audits, and 6 visual-regression comparisons --
and the held-out evaluation ran against frozen thresholds. What remains open is
listed above; none of it blocks the system from running.
