# Phase 5 status: four agents and the LangGraph fast path

Status: **Complete; exit gate passed on 2026-08-31**

This is the phase where the parts built so far become a system. A request now
enters through intake guardrails, loads sanitized context, is decomposed into
typed sub-goals, runs the quantitative and retrieval lanes in parallel, merges
into one evidence bundle, passes a coverage gate, is adjudicated, verified,
routed to a human-review band, and persisted -- with a safe trace of every step.

It still runs with no API key. The graph completes offline with a deterministic
narrative and says so in its own limitations, which is what makes the whole
suite runnable in CI at no cost.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Typed state and reducers | PASS | `meridian.graph.state`; every list field annotated, including the ones that replace |
| Intake, context load, planner | PASS | `validate_request`, `load_context`, `plan_sub_goals` |
| Parallel Quantitative Analyst and Evidence Retriever | PASS | `quantitative_lane` and `retrieval_lane`; overlap asserted, not assumed |
| Fan-in and coverage gate | PASS | `merge_evidence` then `coverage_verdict`: sufficient, recoverable, critical |
| Fast adjudication, verification, routing | PASS | `fast_adjudication` → `verify_output` → `assign_route` |
| SQLite checkpointer | PASS | `sqlite_checkpointer`; a finished run reads back with its full trace |
| Safe graph events streamed | PASS | `run_assessment(..., on_event=...)`; 21 event types, redacted at the recorder and re-checked at the model |
| Degraded retrieval behaviour | PASS | `degraded_result`: verified telemetry, gap notice, targeted data request, impact-aware escalation |
| End-to-end CLI run | PASS | `make assess ACCOUNT=ACC-1042 OFFLINE=1` |
| Retrieval-exhaustion run | PASS | `test_exhausted_retrieval_never_emits_a_categorical_label` |
| Persisted trace and decision | PASS | `AssessmentStore` snapshot plus a review case on every red route |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Parallel lanes confirmed in trace | PASS | `test_the_two_evidence_lanes_run_concurrently` |
| No unbounded cycle | PASS | `test_the_evidence_cycle_runs_at_most_twice` |
| Exhausted retrieval never emits an unsupported categorical label | PASS | `test_exhausted_retrieval_never_emits_a_categorical_label` |

391 tests passing at 96% coverage, ruff and mypy strict clean across 99 files.
156 of those tests are new in this phase.

### How each gate criterion is actually shown

**Parallel lanes.** Two trace events in sequence prove nothing about
concurrency: nodes run one after another produce the same ordering. So both
lanes are wrapped to record when they enter and leave, and the test asserts the
intervals overlap. A measured overlap of 0.6 s was observed on a run where the
lanes took 0.6 s and 3.6 s.

**No unbounded cycle.** The graph has exactly one cycle,
`merge_evidence → targeted_retry → merge_evidence`. The test drives it with a
retriever that never succeeds, so the run would loop forever if the budget were
advisory. It is not: `coverage_verdict` stops returning `recoverable` once the
rounds are spent, and the router therefore has no edge back to the retry node.

**No label without evidence.** `InsufficientEvidenceDecision` has no `outcome`,
`distribution`, or `confidence` field. The degraded path cannot emit a
categorical forecast because the label is unrepresentable, not because the code
remembers not to fill it in.

## The four agents, and which of them think

| Agent | Uses a model | Why |
| --- | :---: | --- |
| Orchestrator / Planner | optional | Suggests sub-goals from a closed six-item vocabulary; falls back to a deterministic plan derived from the profile |
| Quantitative Analyst | no | Section 13.2: an LLM is not required, and one near the arithmetic would put an unverifiable number in front of a user |
| Evidence Retriever | no | Ranking is semantic, but every safety property -- account scope, cutoff, source family -- is deterministic |
| Forecast Adjudicator | optional | Writes the rationale, limitations, and action. It never chooses the outcome |

## Three decisions worth recording

### The model cannot produce the label

The outcome and the four-class distribution come from the calibrated
forecaster. `AdjudicationDraft` -- the only structure a model may return here --
has no outcome, distribution, or confidence field, so the label is not reachable
from a generated reply even if a prompt asked for one. What the adjudicator
genuinely decides is whether the evidence supports releasing that label, and a
"no" is recorded as a stated disagreement rather than silently overriding the
model.

### Supporting and counterevidence are split on metadata, never on text

A citation is counterevidence when its structured signal disagrees with the
direction of the prediction. The signal comes from the ticket's category and
priority, the note's type, and the dataset's own recorded event polarity. Using
a sentiment model over retrieved text would put a second, unvalidated
classifier inside a safety control, and the dataset already records the answer
exactly for the one source family where polarity is unambiguous.

The consequence is worth stating plainly: most retrieved evidence is neither
supporting nor contradicting. It is carried as `context` and shown on the
decision card rather than discarded, because evidence a reader never sees is
evidence nobody can check.

### The graph calls the registry, not a protocol

Phase 4 wrapped the eight services in the official MCP SDK and built a client
for them. Phase 5's agents nevertheless call `ToolRegistry` directly. The
allowlist, the argument validation, the timeout, and the audit line all live in
the registry, so a protocol round trip to ourselves would add a hop without
adding a control, and would turn every node async for nothing.

That is only safe while the two paths agree, so
`test_the_protocol_and_the_registry_return_the_same_answer` compares them on a
real call rather than assuming it.

## Two defects this phase found in its own work

**Output verification was checking the wrong citations.** The verifier compared
the decision's citation list against the evidence bundle -- but that list *was*
the bundle, so the check could never fail. A model citing a document nobody
retrieved would have passed. `ForecastDecision.cited_doc_ids` now records what
the narrative actually claimed, and that is what gets replayed.

**The verifier rejected the word "outcome".** The knowledge-base sanitiser
strips evaluation-only field names, and `outcome` is one of them. Applying the
same rule to a rationale rejected the sentence "the renewal outcome depends on
the escalation", which is ordinary English. Only the bare word is now exempt;
`outcome_date` and `outcome_reason` are still refused, and the values behind
those fields are not reachable from this layer at all.

Both were found by running the graph against a live provider once, which is the
argument for doing that before declaring a phase finished.

## Guardrails implemented here

Section 16.2's nine intake categories are implemented deterministically, with
reason codes drawn from the same vocabulary the packaged guardrail evaluation
set uses for its expected behaviours -- so Phase 7 can compare a decision with
an expected behaviour directly instead of through a translation table that could
quietly disagree with both.

Three categories are advisory rather than blocking. A request that supplies a
rumour, or that demands a definitive one-word answer, is answerable; what must
not happen is that the system complies with the framing. Those pass through
carrying a reason code, and the adjudicator turns each into a stated limitation.

The packaged 36-case evaluation set has **not** been run. It is Phase 7's exit
gate, and rules tuned against the sentences they will be scored on would measure
nothing.

## Known limitations

- **The conflict gate does not detect conflicts yet.** It runs, and reports
  `evaluated=False` with the reason, because section 15.1's deterministic
  triggers are Phase 6's deliverable. A bare `triggered=False` would read as
  "checked, and the evidence agrees", which is a claim this system has not made.
  The router already names the `tot_adjudication` branch; Phase 6 supplies it.
- **The numeric replay checks numerals, not number words.** "Five of six
  drivers" is not verified; "5 of 6" would be. It also accepts a fabricated
  figure that happens to land within tolerance of a real one. It bounds
  fabrication rather than eliminating it, which is why the citation, forbidden
  field, and injection checks run alongside rather than instead.
- **Staleness is only measured where a source carries dates.** Usage weeks and
  retrieved documents have them; the support summary does not expose ticket
  dates, so a support source is reported as missing rather than stale.
- **A run with a real provider is slow and not free.** One observed live run
  took 55 s and two model calls: 11 s to plan and 15 s to adjudicate, plus 25 s
  for the one regeneration verification demanded. The offline path takes about
  3 s and costs nothing.
- **Only one graph interrupt point exists implicitly.** Section 16.6's
  `LangGraph interrupt` for cases that must pause is Phase 7's task; today a red
  route completes and creates a review case rather than pausing.
