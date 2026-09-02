# Architecture

## System boundary

Meridian is a modular-monolith backend plus a React frontend. It uses immutable synthetic source data, generated runtime-safe artifacts, typed service functions, MCP-compatible tool interfaces, LangGraph orchestration, a provider-neutral LLM adapter, and local persistence.

The system is read-only with respect to Meridian source data. It may persist internal assessments, traces, review cases, and reviewer feedback.

## End-to-end flow

```mermaid
flowchart TD
    UI[React application] --> API[FastAPI intake]
    API --> IG{validate_request}
    IG -->|Blocked or clarify| BLOCK[safe_refusal]
    IG -->|Allowed| LOAD[load_context]
    LOAD --> PLAN[plan_sub_goals]
    PLAN --> QUANT[quantitative_lane]
    PLAN --> RETRIEVE[retrieval_lane]
    QUANT --> MERGE[merge_evidence]
    RETRIEVE --> MERGE
    MERGE --> COVER{Coverage verdict}
    COVER -->|Recoverable| RETRY[targeted_retry]
    RETRY --> MERGE
    COVER -->|Critical gap| DEGRADED[degraded_result]
    COVER -->|Sufficient| CONFLICT{Conflict gate}
    CONFLICT -->|No| FAST[fast_adjudication]
    CONFLICT -->|Yes| TOT[tot_adjudication]
    FAST --> VERIFY[verify_output]
    TOT -->|Winner selected| VERIFY
    TOT -->|Search abstained| PERSIST
    VERIFY -->|Passed| ROUTE[assign_route]
    VERIFY -->|Repairable| FAST
    VERIFY -->|Failed twice| FALLBACK[safe_fallback]
    FALLBACK --> ROUTE
    ROUTE --> PERSIST[persist]
    DEGRADED --> PERSIST
    PERSIST -->|Green or amber, or a scan| DONE[Advisory result and queue entry]
    PERSIST -->|Red, interactive| PAUSE[await_review: LangGraph interrupt]
    PAUSE --> DECIDE[Typed reviewer decision]
    DECIDE --> RESUME[Resume and persist regression]
```

Node names are the graph's own, so the diagram and `backend/src/meridian/graph/builder.py`
can be compared line by line. Two edges are easy to draw wrongly and are drawn
as built here: **every** route persists, not only red -- a green assessment is
still recorded -- and the interrupt sits *after* persistence, so a run abandoned
at the pause leaves an open review case rather than nothing. The captured node
paths in `artifacts/traces/TRACES.md` are the same edges observed at runtime.

Structural transitions are deterministic. LLMs may propose typed sub-goals, summarize evidence, generate candidate hypotheses, and score qualitative rubric dimensions, but they do not decide policy edges through unrestricted prose.

## Four logical agents

### Orchestrator / Planner

- Validates the assessment objective after intake.
- Produces two to four typed sub-goals.
- Dispatches quantitative and retrieval work.
- Checks evidence sufficiency after fan-in.
- Requests at most one additional evidence round.
- Does not compute metrics, retrieve documents directly, or make the final forecast.

### Quantitative Analyst

- Deterministic node; no LLM is required.
- Computes point-in-time metrics, coverage, calibrated probabilities, and observable drivers.
- Returns exact windows, row counts, and provenance.
- Returns a typed critical gap instead of estimating missing numbers.

### Evidence Retriever

- Searches account-scoped qualitative sources and the general knowledge base separately.
- Enforces account, cutoff, date, source, and authorization filters.
- Preserves parent/child citation metadata.
- Grades relevance and coverage.
- Rewrites and retries once when evidence is thin, stale, off-topic, or duplicate-heavy.

### Forecast Adjudicator

- Uses a linear fast path when evidence agrees.
- Runs bounded candidate comparison only when the deterministic conflict gate fires.
- Produces a typed forecast or abstention from the existing evidence bundle.
- Cannot introduce new facts, perform new unrestricted retrieval, or override hard policy.

## Evidence lanes

### Deterministic lane

Consumes structured account attributes, weekly usage, support aggregates, external-event aggregates, and a runtime-safe feature set. It produces exact metrics, coverage, calibrated class probabilities, and non-causal feature contributions.

### Semantic lane

Indexes CSM notes/QBRs, ticket text, sanitized external-event documents, and the 32-document knowledge base. It uses local embeddings and FAISS, hard metadata filters, parent-child retrieval, candidate depth 20, and bounded MMR/reranking to return no more than five account citations and two knowledge citations per sub-goal.

Numeric telemetry and target/latent fields never enter the semantic index.

## Shared state

LangGraph owns a typed state containing request, account profile, plan, quantitative evidence, retrieval evidence, coverage, retries, conflict assessment, candidates, draft, verification, final result, route, review case, errors, and safe trace summaries.

Parallel nodes write distinct keys. An explicit fan-in node constructs the shared evidence bundle.

MCP receives validated run, account, requester, and cutoff context for each tool call. It exposes tools/resources; it is not used as an implicit graph-memory bus.

## Conflict-gated Tree-of-Thought

- Triggered only by material disagreement, near-tied model probabilities, or opposing verified evidence.
- Missing evidence alone does not trigger ToT.
- Generates one candidate for each of four outcomes.
- Hard-prunes candidates that violate metrics, cutoff, account, target-leakage, citation, or counterevidence rules.
- Keeps the top two soft-scored candidates.
- Stress-tests each survivor once against its strongest verified disconfirming evidence.
- Selects only when quality and margin thresholds pass; otherwise abstains and routes to review.
- Stores structured candidate summaries and scores, never hidden free-form reasoning.

## Safety boundary

Safety spans:

- Input validation and policy blocking
- Runtime/evaluation data separation
- Tool allowlists and typed arguments
- Account and point-in-time retrieval enforcement
- Quantitative provenance and account/knowledge evidence isolation
- Provider-attempt, token, and elapsed-time budgets
- Evidence and output verification
- Deterministic confidence and impact routing
- Human interrupt/resume
- Structured tracing and regression capture

## Persistence

- SQLite-backed LangGraph checkpointer for resumable local runs
- Assessment and review repositories for application memory
- SQLite parent-document and metadata store for retrieval
- FAISS vector index for local embeddings
- Versioned model, data, index, evaluation, and trace manifests

Prior assessments are context, not truth. Every new assessment must re-query point-in-time evidence.

## As built, after Phase 10

| Concern | Module |
| --- | --- |
| Section 9.1 typed contracts | `meridian.contracts` |
| Shared state and budgets | `meridian.graph.state` |
| Node implementations | `meridian.graph.nodes` |
| Deterministic edges and review bands | `meridian.graph.routing` |
| Section 15.1 conflict triggers | `meridian.graph.conflict` |
| The bounded Tree-of-Thought search | `meridian.graph.tot` |
| Portfolio baselines for the relative rules | `meridian.features.baselines` |
| Evidence-aware confidence | `meridian.graph.confidence` |
| Topology, checkpointer, run API | `meridian.graph.builder` |
| Safe trace events | `meridian.graph.tracing` |
| The four agents | `meridian.agents.*` |
| Intake rules and the high-value policy | `meridian.guardrails.intake`, `meridian.guardrails.policy` |
| Evidence boundary and provenance screening | `meridian.guardrails.evidence` |
| Spending and tool-surface guards | `meridian.guardrails.runtime` |
| Assessment, review, and regression persistence | `meridian.memory.store` |
| Human-review HTTP surface | `meridian.api.routes.review` |
| The 36-case safety evaluation | `meridian_eval.guardrail_eval` |
| Served run registry and SSE streaming | `meridian.serving.runs` |
| Bounded autonomous portfolio scan | `meridian.serving.scan` |
| Optional scheduled worker | `meridian.serving.scheduler` |
| Demo mode and run rate limits | `meridian.serving.limits` |
| HTTP surface, dependencies, and error contract | `meridian.api.*` |
| Typed browser client and the SSE subscription | `frontend/src/api.ts` |
| Portfolio, account, run, review, and evaluation pages | `frontend/src/pages/*` |
| Decision card, evidence drawer, timeline, and charts | `frontend/src/components/*` |
| Browser journeys and screenshot capture | `frontend/e2e/*` |
| Frozen decision thresholds and their digest | `meridian.graph.thresholds` |
| Trace sinks, cost estimation, optional LangSmith | `meridian.graph.observability` |
| One evaluation pass over a split | `meridian_eval.system_run` |
| The five evaluation dimensions | `meridian_eval.dimensions` |
| Threshold sweep and the result directory | `meridian_eval.threshold_study`, `meridian_eval.report` |

The contracts sit at the package root rather than inside `meridian.graph`
because the agents, the guardrails, and the graph all depend on them: an agent
that had to import the graph package to name its own return type would make the
graph a dependency of the agents it is built from.

One deviation from the description above is worth stating plainly. The graph's
agents call `ToolRegistry` directly rather than the in-process MCP client. The
per-role allowlist, the argument validation, the timeout, and the audit line all
live in the registry, so a protocol round trip to ourselves would add a hop
without adding a control -- and would make every node async to do it. MCP
remains the external tool surface, and a contract test compares the two paths on
a real call so the shortcut cannot quietly diverge.

## Superseded implementation details

An earlier design mapped generator and critic roles to CrewAI and LangChain and described MCP as a state manager. The implementation plan supersedes that mapping:

- No CrewAI dependency is required for version 1.
- LangGraph implements the generator/critic subgraph and all orchestration.
- MCP exposes typed tools and resources.
- LangGraph state and checkpointers hold per-run state.

This preserves the submitted capabilities while avoiding multiple competing orchestration frameworks.
