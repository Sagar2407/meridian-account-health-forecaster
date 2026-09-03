# Evidence map

Every claim this project makes about itself, mapped to the code, test, or
artifact that backs it. One rule governs the document:

> No claimed feature lacks code or evidence. No claimed result lacks a
> reproducible metric artifact.

So the last section lists what the system **does not** do. A map that only
records successes cannot fail, and a rule that cannot fail is decoration.

## Claims

### Problem and intended user


| Claim | Evidence |
| --- | --- |
| CSMs triage large portfolios by hand and inconsistently | `docs/PROJECT_CONTEXT.md` |
| The system forecasts one of four renewal outcomes and explains drivers | `OUTCOME_CLASSES` in `backend/src/meridian/contracts.py`; any trace in `artifacts/traces/` |
| It is decision support, not action: read-only, advisory | Eight read-only tools; `assert_no_dangerous_tools` refuses at assembly |
| The portfolio view is the actual user surface | `docs/screenshots/portfolio.png`, `frontend/src/pages/PortfolioPage.tsx` |

### System goal and scope

| Claim | Evidence |
| --- | --- |
| Forecast, driver attribution, citation, recommended action, honest abstention | `ForecastDecision` and `InsufficientEvidenceDecision` |
| The abstention path structurally cannot emit a label | `InsufficientEvidenceDecision` has no outcome field |
| Scope excludes customer contact, record changes, commitments | `docs/DATA_SAFETY.md`; guardrail category `commercial_commit` |
| Data is fully synthetic, seed `20260721`, as-of `2026-06-28`, 90-day horizon | `docs/DATA_LINEAGE.md`; `dataset/config.py` |

### Final architecture and major components

| Claim | Evidence |
| --- | --- |
| Four agents coordinated by a compiled LangGraph | `backend/src/meridian/graph/builder.py`; `docs/ARCHITECTURE.md` diagram |
| Evidence lanes run in parallel and converge on one fan-in | One superstep in `builder.py`; two `*_completed` events per trace |
| Control flow is deterministic edges, not model choice | `route_intake`, `route_coverage`, `route_conflict`, `route_verification`, `route_human_review` |
| Tools are read-only and exposed over MCP with a per-role allowlist | `backend/src/meridian/tools/`; `docs/PHASE_4_STATUS.md` allowlist table |
| The Adjudicator advertises no tools at all | Empty allowlist; `backend/tests/test_tools_mcp.py` |
| The provider is an interface, not a compiled-in vendor | `test_only_the_named_adapter_may_import_a_provider_sdk` |
| Four representative paths through the graph | `artifacts/traces/TRACES.md` — node path per run |

### Design evolution

| Claim | Evidence |
| --- | --- |
| Which design commitments held, changed, or were not built | `docs/DESIGN_EVOLUTION.md` |
| ReAct loop became a compiled graph, and why | `docs/DESIGN_EVOLUTION.md`; `docs/adr/0001-langgraph-orchestration.md` |
| CrewAI and the MCP-as-state-manager mapping were dropped | `docs/adr/0002-mcp-boundary.md`; CrewAI absent from `pyproject.toml` |
| Per-stage decisions and their reasons | `docs/DECISIONS.md`; `docs/PHASE_*_STATUS.md` |

### Implementation overview

| Claim | Evidence |
| --- | --- |
| Stack, repository layout, how to run it | `README.md` quick start; `Makefile` targets |
| Everything runs through Docker; one authoritative gate | `make phase0-verify`; `scripts/python_in_docker.sh` |
| Dependencies are locked | `uv.lock`, `pnpm-lock.yaml`; `uv run --locked` |
| The archive reproduces byte for byte from the generator | `test_every_table_reproduces_the_shipped_archive` |
| Single-container production image | `Dockerfile`; `docs/DEPLOYMENT.md` |

### Evaluation methods and results

Every number below is read from an artifact, and every artifact has a command
that regenerates it. Nothing in the report should be typed by hand.

Result directories are named `<commit>-<timestamp>`, so no fixed path points at
the current one. `artifacts/evaluation/summary.json` does: every run republishes
it with the headline for each split and the directory that produced it, and it
is what the application's evaluation page reads. Cite the summary; use the
directory it names for the full report, per-account rows, and plots.

| Result | Value | Artifact | Command |
| --- | ---: | --- | --- |
| Macro F1, held-out (53 accounts) | 0.7490 | `artifacts/evaluation/summary.json` | `make evaluate-system SPLIT=test` |
| Majority baseline it beats | 0.4595 | same | same |
| Macro F1, development (207) | 0.8468 | `artifacts/evaluation/summary.json` | `make evaluate-system` |
| Supported-claim rate | 1.0000 | both result directories | same |
| Exact numeric agreement | 1.0000 | both | same |
| Wrong-account citations | 0 | both | same |
| Post-cutoff citations | 0 | both | same |
| Expected calibration error, held-out | 0.1712 | test `results.json` | same |
| Band error rates (green / amber / red), development | 0.000 / 0.029 / 0.127 | development `results.json` | same |
| Threshold sweep | 6 of 207 released, 0 wrong | `threshold_study.csv` | same |
| Hard-category false-pass rate | 0.0000 | `artifacts/safety/guardrail_eval.json` | `make evaluate-guardrails` |
| Answerable false-block rate | 0.0000 | same | same |
| Within-policy disposition accuracy | 1.0000 | same | same |
| Exact-disposition match (stricter reading) | 0.6944 | same | same |
| Retrieval chunking ablation | see table | `artifacts/retrieval/chunking_ablation.csv` | `make evaluate-retrieval` |
| ToT vs linear adjudication | see file | `artifacts/tot/tot_ablation.json` | `make evaluate-tot` |
| Guardrail stack: removing intake | 0.0000 → 0.7333 hard false pass | `artifacts/safety/guardrail_stack.json` | `make evaluate-guardrail-stack` |
| Bounded portfolio scan, 12 accounts | see file | `artifacts/portfolio/portfolio_scan.json` | `make scan LIMIT=12` |
| Resume behaviour: paused runs that finish (ER-006) | 1.0000 over 4 actions | `results.json` → `operational_reliability.resume` | `make evaluate-system` |
| Downstream correctness by retrieval health (ER-005) | 0.8438 clean vs 0.8000 retried, held out | `results.json` → `grounded_explanation.downstream_correctness` | same |
| Prompt versions tied to every result (ER-007) | digest per prompt, 4 registered | `results.json` → `manifest.prompts` | same |
| Estimated cost (ER-006) | 0.0000 USD — every run is offline | `results.json` → `operational_reliability.tokens` | same |
| Portfolio concurrency (ER-006) | peak 3 of 3, counted by the runs themselves | `artifacts/portfolio/portfolio_scan.json` | `make scan LIMIT=6 CONCURRENCY=3` |

Two properties of the evaluation are worth claiming explicitly, because they are
unusual and both are enforced by code:

- **The report is generated, not written.** `evaluation/meridian_eval/report.py`
  formats only from the result dictionary; there are no literal numbers in it.
  A metric that is not computed cannot appear.
- **Thresholds were frozen before the held-out split was touched.**
  `graph/thresholds.py` hashes to `cbf44c84e4501881` (v2), a test pins that digest,
  and the threshold sweep runs on development data only (plan §22.7).

### Safety, reliability, and human oversight

| Claim | Evidence |
| --- | --- |
| Five guardrail stages run on every assessment | `intake, execution, evidence, output, routing` in every `artifacts/traces/*.json` |
| Hard categories refuse: privacy, HR, leakage, out-of-domain, commitments | `artifacts/safety/SAFETY_REPORT.md` per-category table |
| Tools refuse hostile arguments before any service runs | 48 tests in `backend/tests/test_tools_registry.py` |
| A subsystem outage degrades rather than fails | `artifacts/traces/degraded.json` — retrieval unavailable, 21 verified metrics, no label |
| Red routes pause for a person and resume on a typed decision | `artifacts/traces/human_review.json` — pause, override, linked case |
| An override requires a reason code and a note | `ReviewerDecision` validator; enforced in the contract, not the API |
| Confidence is arithmetic a reviewer can check | `confidence_breakdown` on every decision card |
| Traces carry no prompts or raw reasoning | `FORBIDDEN_TRACE_KEYS`; `redact` in `graph/tracing.py` |

### Current limitations and future improvements

State these as limitations, with the evidence that they are measured rather than
guessed:

| Limitation | Evidence |
| --- | --- |
| Calibration misses its target: ECE 0.1712 against 0.10 | test `results.json`; reported as **not met** |
| At the frozen bands, auto-release is near zero — 6 of 207 on development, 0 of 53 held out | `results.json`; `threshold_study.csv` |
| Driver overlap with ground truth is 0.4526 (dev) / 0.4279 (test) | `results.json` |
| No LLM judge, so no judge-scored dimension is reported | `docs/DESIGN_EVOLUTION.md`; §22.2 note in every report |
| Evidence screening and output verification are not separable from the full stack on the 36-case suite | `artifacts/safety/guardrail_stack.json`; reported as a negative result |
| Every published result is from the deterministic path: 0 tokens, 0 model calls | `total_tokens: 0` in every artifact |
| Synthetic narratives may inflate retrieval and explanation scores | plan §27 risk register; `docs/PHASE_3_STATUS.md` |
| The ablation corpus is 853 documents, not the full 12,860 | `docs/PHASE_3_STATUS.md` |
| The production image ships without data, model, or index | `docs/DEPLOYMENT.md` |

## What this system does not do

Listed so the report cannot overclaim by omission:

- It **does not act.** No customer contact, no record write, no commercial
  commitment. Application memory holds assessments and review cases; source data
  is immutable and a store refuses at construction to open a database under
  `data/raw/`.
- It **does not run on live data.** Everything is synthetic, seeded, and
  point-in-time filtered.
- It **is not calibrated to target.** See the limitations table.
- It **has not been run against a live provider at evaluation scale.** All
  published metrics come from the deterministic narrative path. The provider
  adapter has one opt-in live test.
- It **is not deployed publicly** at the time of writing. See
  `docs/DEPLOYMENT.md` for what remains.
- It **has no human-validated judge**, so no soft-dimension score is claimed.

## Regenerating the evidence

```bash
make phase0-verify                 # the authoritative gate: lint, types, tests, policy
make traces                        # the four representative traces
make evaluate-guardrails           # the 36-case safety suite
make evaluate-guardrail-stack      # what each guardrail layer is worth
make evaluate-retrieval            # retrieval benchmark and chunking ablation
make evaluate-tot                  # linear vs conflict-gated adjudication
make evaluate-system               # development split
make evaluate-system SPLIT=test    # held-out split, frozen thresholds
make scan LIMIT=12                 # a bounded autonomous portfolio scan
make screenshots                   # the UI captures in docs/screenshots/
```

All of these run offline and spend nothing: every artifact in this repository
was produced with `total_tokens: 0`.
