# Design evolution: what was specified, and what was built

The design was specified in six stages before any code existed. This document is
the honest reconciliation: which commitments survived contact with a working
system, which changed, which were dropped, and why.

It exists because a design document that quietly reprints itself is
unfalsifiable. The interesting claims are the ones where the build disagreed with
the plan, and there are five of them.

Three outcomes appear throughout:

- **Held** — built as designed, and there is code or an artifact to check.
- **Changed** — built differently, for a reason recorded here.
- **Not built** — designed, not implemented. Stated rather than quietly dropped.

## Summary

| Commitment | Stage | Outcome | Where |
| --- | --- | --- | --- |
| Four renewal outcomes, driver-attributed, with an "I cannot answer" path | 1 | Held | `OUTCOME_CLASSES`, `InsufficientEvidenceDecision` |
| Read-only, advisory; never contacts a customer or changes a record | 1 | Held | Eight read-only tools; `assert_no_dangerous_tools` |
| Numbers computed deterministically, never generated | 2 | Held | `QuantitativeAnalyst`; exact numeric agreement 1.0000 |
| Retrieval for qualitative evidence only; telemetry never retrieved | 3 | Held | `docs/DATA_LINEAGE.md`; index excludes usage tables |
| ReAct loop drives control flow | 2 | **Changed** | Compiled LangGraph; deterministic edges |
| Parent-child chunking, top-k 5 per sub-goal, account filter, MMR | 3 | Held | `retrieval/chunking.py`, `retrieval/search.py` |
| Conflict-gated ToT: 4 roots, depth 2, beam 2, hybrid evaluator | 4 | Held | `graph/tot.py` |
| CrewAI for ToT roles, LangChain for control, MCP for shared state | 4 | **Changed** | LangGraph owns both; MCP is the tool boundary |
| Four specialised agents, parallel evidence lanes | 5 | Held | `graph/builder.py` fan-out |
| Shared state carried across agents via MCP | 5 | **Changed** | Typed `ForecasterState` with explicit reducers |
| Five guardrail stages; hard rules before probabilistic scorers | 6 | Held | `state["guardrails"]`, five stages per run |
| Bands 0.85 / 0.70, tie band 0.10, frozen before held-out testing | 6 | Changed in v2 | Green moved to 0.80 on development evidence; amber and the tie band held. `graph/thresholds.py`, digest `cbf44c84e4501881` |
| Four reviewer actions; reason codes become regression cases | 6 | Held | `ReviewerDecision`, `artifacts/traces/human_review.json` |
| LangSmith as the observability layer | 6 | **Changed** | Local tracing mandatory; LangSmith optional |
| LLM judge for driver fidelity, validated against human review | 6 | **Not built** | No double-reviewed sample exists; no judge metric reported |
| Guardrail-stack ablation (none / input / +execution / full) | 6 | Held | `artifacts/safety/guardrail_stack.json`; execution stage is structural, see below |

## Stage 1 — scoping

Stage 1 committed to a forecaster over synthetic B2B SaaS data that predicts one of
four renewal outcomes, explains the drivers, and has "the honesty to say when it
lacks enough information to answer."

That last clause turned out to be the load-bearing one. It is the reason the
system has a second result type rather than a confidence field that can go low:
`InsufficientEvidenceDecision` has **no outcome field at all**, so the degraded
path cannot emit a categorical forecast even by mistake. A design that expressed
the same idea as "low confidence" would have let one careless branch publish a
label anyway.

The scoping also holds in a negative sense worth stating plainly: the built
system reads and never writes to source data, has no customer-facing action, and
makes no commercial commitment. Autonomy here means analysis and routing, not
consequence.

## Stage 2 — reasoning loop, memory, tools

**Held.** The separation that stage 2 made its central principle — probabilistic
reasoning kept away from arithmetic — is the backbone of the built system. The
Quantitative Analyst runs a deterministic tool and returns exact numbers with
coverage flags; the model never computes. Exact numeric agreement is 1.0000 on
both splits, which is the measurement of that principle rather than a restatement
of it.

**Changed: the ReAct loop became a compiled graph.** stage 2 described a Thought /
Action / Observation loop where the model chooses the next action. The built
system plans sub-goals with the model and then runs a compiled LangGraph whose
transitions — is coverage sufficient, do the signals conflict, does this route to
a human — are deterministic edges the model cannot influence.

Stage 5 had already begun this move; the implementation completed it. The
reason is auditability under cost: a forecast that drives revenue decisions needs
a control flow a reviewer can read, and a model that re-decides at every hop
gives neither a bounded cost nor a reproducible path. What survives of ReAct is
the shape — plan, gather in parallel, check sufficiency, iterate once if thin —
without the model holding the steering wheel.

**Changed: the file names.** stage 2's table listed `weekly_usage.csv`,
`support_tickets.jsonl`, and `csm_notes.jsonl`. The generated dataset is
`usage_weekly.csv`, `support_tickets.csv`, and `csm_notes.csv`. The specification
described them as representative; `docs/VERIFICATION_MATRIX.md` records the
actual names as superseding.

**Added: point-in-time enforcement, at a strength stage 2 did not anticipate.** 2.1
treated coverage as a quality flag. The build made the account cutoff a hard
boundary enforced in the loader, in every tool, and in a test: sanitising the
runtime tables removes **17,927 fact rows** that postdate their account's
effective cutoff. This is the difference between a system that reports coverage
and one that cannot see the future.

## Stage 3 — retrieval

**Held, and measured.** Parent-child chunking, a top-k of five account citations
per sub-goal, an `account_id` hard filter applied before similarity, MMR
reranking, and a citation on every claim — all built as designed
(`MAX_ACCOUNT_CITATIONS = 5`, `MMR_LAMBDA = 0.7`, plus two knowledge-base
citations for guidance).

Stage 3 proposed the chunking question as a controlled ablation, and it was run.
Holding corpus, encoder, filters, top-k, and queries constant:

| Strategy | Chunks | Recall@5 | MRR | nDCG |
| --- | ---: | ---: | ---: | ---: |
| parent-child | 1,464 | 0.9424 | 0.7317 | 0.6793 |
| fixed-length | 1,029 | 0.9281 | 0.7944 | 0.7217 |

**The ablation does not vindicate the choice that shipped.** Fixed-length ranks
better on both ordering metrics; parent-child recalls slightly better. Parent-child
was retained on two grounds the ranking metrics do not capture — a parent section
is quotable where a fixed-length cut is often mid-sentence, and everything
downstream sees all five citations, so membership matters more than position.
That is a judgement call on a small difference, and `docs/PHASE_3_STATUS.md` says
so rather than presenting it as a result.

**Changed: the recency filter became a cutoff filter.** stage 3 described recency as
a way to stop stale quarters dominating. The build made it a correctness
boundary: every retrieval is filtered to the account's effective cutoff, and
post-cutoff citations are measured at **0** on both splits. Staleness is still
tracked, but as a confidence input, not as the leakage control.

## Stage 4 — Tree-of-Thought

**Held, structurally.** The scoped-ToT decision — linear everywhere, branch only
at adjudication — is exactly what was built. Four root branches capped by the
four outcomes, depth 2, beam width 2, a hybrid evaluator where deterministic
checks prune hard-constraint violations regardless of critic score, a tie band
that triggers one self-consistency vote and then escalates rather than forcing a
pick. The gate is deterministic, so most accounts never pay for the search.

**Changed: the tool mapping.** stage 4's Table 2 assigned the four ToT roles to
CrewAI (thought generator, critic), LangChain (controller), and MCP (state
manager). None of that mapping survived. LangGraph owns orchestration and the
search controller; MCP is the read-only tool boundary and nothing else; CrewAI is
absent from the dependency set entirely.

The reason is that the mapping assigned three libraries to one job. A compiled
graph already expresses branch expansion, pruning, and termination as edges and
state, so a second orchestration library would have meant two control-flow
systems disagreeing about who owns a retry. MCP is a tool protocol, not a state
manager; using it as one would have put the evidence bundle on a wire that exists
to carry tool calls. `docs/adr/0001-langgraph-orchestration.md` and
`docs/adr/0002-mcp-boundary.md` record the decisions.

**Measured.** The ToT ablation compares linear adjudication against the
conflict-gated search on the accounts where the gate actually fires; results are
in `artifacts/tot/tot_ablation.json` and summarised in `docs/PHASE_6_STATUS.md`.

## Stage 5 — multi-agent coordination

**Held.** Four agents — Orchestrator, Quantitative Analyst, Evidence Retriever,
Forecast Adjudicator — with the two evidence lanes running in parallel from one
fan-out and converging on one fan-in, exactly as the design figure showed.
The count did not grow.

**Changed: shared state is LangGraph's, not MCP's.** stage 5 said the state object is
"carried across roles via MCP". The built system uses a typed `ForecasterState`
TypedDict with explicit reducers — `operator.add` for channels that accumulate,
`keep_last` for channels that replace — so two parallel lanes writing at once have
defined semantics instead of a last-writer-wins race. MCP carries tool calls.

**Added: the per-role tool allowlist.** stage 5 described specialisation as a
property of prompts and tools. The build made it enforceable: each role has an
allowlist derived from stage 5's own agent definitions, injected by the registry
rather than supplied by the caller, and the advertised MCP schema omits `role`
entirely so a client cannot name its own. The Adjudicator's allowlist is **empty**
— stage 5 said "no new tool calls", so its session advertises nothing at all.

## Stage 6 — guardrails, evaluation, human review

**Held.** Five stages — intake, execution, evidence, output, routing — accumulate
on every run, and every captured trace in `artifacts/traces/` shows all five. The
review bands are the specified numbers: green at 0.85, amber from 0.70,
tie band 0.10. The four reviewer actions are built, an override requires a
specific reason code and a note (enforced in the contract, not the API layer), and
resolving a case creates a linked regression record in one transaction.

The specified "thresholds are frozen before held-out testing" became a
mechanism rather than a promise: `graph/thresholds.py` is the single frozen
source, its numeric fields hash to digest `cbf44c84e4501881`, a test pins that
digest, and there is no runtime override.

**Changed: observability.** stage 6 named LangSmith as the tracing layer. The build
makes *local* structured tracing mandatory and LangSmith optional, enabled by
environment. A safety property that only holds when a third-party service is
reachable is not a safety property; the trace a reviewer needs must exist on the
machine that produced the run.

**Not built: the LLM judge.** stage 6 specified a judge for driver fidelity and
related soft dimensions, "validated against a double-reviewed human sample".
No such sample exists, so no judge metric is reported anywhere. Every published
grounding measure is deterministic. Reporting an unvalidated judge score would
have been the exact overclaim the specification was guarding against.

**Held, with a caveat stage 6 could not have known.** The second ablation was built:
four arms over the same 36 cases, in `artifacts/safety/guardrail_stack.json`.
Removing intake takes the hard false-pass rate from 0.0000 to **0.7333**; the
other two layers are indistinguishable from the full stack on this suite.

The caveat is stage 6's third arm. "Input plus execution" assumes execution-stage
controls are a layer you can switch off. In the built system they are
structural -- argument validation, an injected role allowlist, and a refusal at
assembly -- so there is no arm to run, and the comparison holds them fixed and
says so. The same turns out to be true of leakage: post-cutoff and wrong-account
citations are zero even with evidence screening removed, because the cutoff
lives in the loader rather than in a guardrail.

## What the specification did not anticipate

Three things the build needed that no stage named:

**A confidence formula.** stage 6 said confidence derives from "evidence quality,
coverage, agreement, and calibration" without saying how. The build makes it
explicit and frozen: `0.70 x calibrated + 0.15 x coverage + 0.15 x agreement`,
with four caps that hold confidence down when a critical source is missing, a
conflict is unresolved, retrieval was exhausted, or verification needed a repair.
A reviewer sees the arithmetic on the decision card.

**Abstention needed its own routing.** The specification treated escalation as one
mechanism. Two were needed: a forecast routes on confidence and impact, while a
no-label result has no confidence to route on and instead routes on what was
missing. `abstention_route` and `human_route` both return a typed verdict with
reason codes, which is what makes the safe-fallback metric measurable at all.

**Calibration is the commitment that did not survive measurement.** Expected
calibration error is **0.1712** on the held-out split against a target of 0.10 —
the one release target that is not met. It is reported as not met rather than
softened, and `docs/PHASE_10_STATUS.md` records why the fix must happen on
development data and re-freeze before the test split is touched again.
