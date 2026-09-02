# Requirements

These requirements consolidate the six design stages, the implementation plan, and the dataset documentation. The implementation plan resolves conflicts in earlier implementation details.

## Product requirements

- **PR-001 — Account assessment:** Given a valid synthetic Meridian account and a permitted account-health question, the system shall produce an evidence-grounded assessment.
- **PR-002 — Outcomes:** When evidence is sufficient, the outcome shall be one of `Churned`, `Contracted`, `Renewed`, or `Expanded`.
- **PR-003 — Abstention:** When critical evidence is missing or verification fails, the system shall omit the categorical label and return a typed insufficient-evidence result.
- **PR-004 — Explanation:** Every result shall include drivers, metric windows, supporting evidence, counterevidence, limitations, and a bounded next action.
- **PR-005 — Human routing:** The system shall route results as green, amber, red, or blocked using deterministic confidence, coverage, impact, and policy rules.
- **PR-006 — Review workflow:** Reviewers shall be able to approve, override with a reason, request data and rerun, or escalate.
- **PR-007 — Portfolio scan:** The system shall support a bounded portfolio assessment workflow with concurrency and model-call limits.

## Architecture requirements

- **AR-001 — Four agents:** Use exactly four logical agents: Orchestrator/Planner, Quantitative Analyst, Evidence Retriever, Forecast Adjudicator.
- **AR-002 — Orchestration:** Use a typed LangGraph `StateGraph` with explicit nodes, deterministic structural edges, fan-out/fan-in, bounded cycles, checkpointing, and interrupts.
- **AR-003 — Tool boundary:** Implement business logic as typed Python services and expose required read-only capabilities through MCP-compatible interfaces.
- **AR-004 — Shared state:** LangGraph state is the per-run source of truth; MCP does not transport graph state implicitly.
- **AR-005 — Parallel lanes:** Quantitative computation and semantic retrieval shall run independently in parallel and merge into a typed evidence bundle.
- **AR-006 — Provider adapter:** Graph code shall depend on an internal provider interface, with OpenAI as the default adapter rather than importing provider SDKs directly.
- **AR-007 — No hidden reasoning exposure:** Persist only structured plans, observations, candidate summaries, scores, citations, and route reasons.

## Data and evidence requirements

- **DR-001 — Immutable source:** Raw packaged data shall never be mutated at runtime.
- **DR-002 — Effective cutoff:** Every data query shall enforce `min(forecast_as_of_date, 2026-06-28)`.
- **DR-003 — Runtime/evaluation separation:** Latent, target, generated-truth, and evaluation-only fields shall be isolated from runtime code.
- **DR-004 — Deterministic numbers:** Every displayed quantitative claim shall exactly match deterministic tool output.
- **DR-005 — Retrieval scope:** Semantic retrieval shall cover qualitative notes, QBRs, ticket text, external-event documents, and knowledge-base documents—not numeric telemetry or target labels.
- **DR-006 — Citation verification:** Account citations shall match the requested account and occur on or before the effective cutoff.
- **DR-007 — Bounded retrieval:** The Retriever may rewrite and retry once; exhaustion shall produce a typed gap report.
- **DR-008 — Coverage:** Every metric and retrieval observation shall carry source, window/date, row or document count, and coverage status.

## Reasoning requirements

- **RR-001 — ReAct loop:** The Orchestrator shall use bounded iterative evidence gathering with a maximum of two evidence rounds.
- **RR-002 — Conflict gate:** A deterministic gate shall decide whether evidence is materially conflicting.
- **RR-003 — Bounded ToT:** Tree-of-Thought shall run only after the conflict gate, with four root outcomes, depth two, and beam width two.
- **RR-004 — Hard pruning:** Candidates contradicting exact metrics, cutoff rules, account ownership, target-leakage policy, or verified evidence shall be eliminated deterministically.
- **RR-005 — Tie behavior:** Persistent ties or candidates below the minimum score shall result in abstention and human review.

## Safety and reliability requirements

- **SR-001 — Read-only behavior:** No customer contact, source-record mutation, commercial commitment, or HR decision is permitted.
- **SR-002 — Intake policy:** Block privacy, target-leakage, prompt-injection, clearly unrelated, and consequential-action requests.
- **SR-003 — Tool safety:** Allowlist tools by agent role and validate arguments, timeouts, retries, row limits, and cutoff enforcement.
- **SR-004 — Output verification:** Replay numeric claims and verify qualitative citations; allow at most one regeneration before safe fallback.
- **SR-005 — Confidence:** Confidence shall be derived from calibrated model probability, coverage, evidence agreement, and deterministic penalties—not an LLM's self-report.
- **SR-006 — Failure visibility:** Represent validation, tool, model, policy, and evidence failures explicitly and preserve a safe trace.
- **SR-007 — Secret safety:** No secret may appear in source, logs, browser responses, or committed environment files.

## Evaluation requirements

- **ER-001 — Forecast:** Report macro F1, per-class metrics, confusion matrix, slices, and baseline comparisons.
- **ER-002 — Grounding:** Report supported-claim rate, citation precision, numeric agreement, driver overlap, and counterevidence inclusion.
- **ER-003 — Calibration:** Report ECE, multiclass Brier score, log loss, reliability diagrams, and confidence-band errors.
- **ER-004 — Safety:** Run all 36 guardrail cases and report hard-category false passes, route accuracy, and false blocks.
- **ER-005 — Retrieval:** Evaluate Recall@5, MRR, nDCG, wrong-account rate, post-cutoff rate, duplicate rate, and downstream correctness.
- **ER-006 — Reliability:** Evaluate exhausted-retrieval behavior, completion, latency, retries, escalations, cost, resume behavior, and portfolio concurrency.
- **ER-007 — Integrity:** Freeze thresholds before the held-out run and tie every claimed result to an immutable artifact containing commit, data, model, prompt, and environment versions.

## Phase 0 acceptance criteria

Phase 0 is complete only when:

- The backend and frontend are empty but runnable.
- One documented command starts the local application.
- Docker Compose builds and health checks pass.
- Formatting, linting, typing, unit tests, and CI pass.
- Secret-safe configuration and `.env.example` exist.
- Architecture decisions for LangGraph, MCP, FAISS, provider adapters, and deployment are recorded.
- No machine-specific absolute path or secret is required.
- No later-phase model, retrieval, or agent intelligence has been implemented prematurely.
