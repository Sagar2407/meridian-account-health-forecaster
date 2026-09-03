# Phase 7 status: safety and human review

Status: **Complete; exit gate passed on 2026-09-01**

Phase 7 turns the controls around the forecasting graph into one enforced,
observable chain. Every released or abstained result now carries typed verdicts
for intake, execution, evidence, output, and routing. Red interactive runs can
pause at a LangGraph interrupt, appear in the persisted review queue, and resume
with one of four validated reviewer actions. No API key is needed for any of it.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Intake guardrail | PASS | Existing deterministic policy rules remain the first graph node and stop blocked requests before tools run |
| Execution guardrail | PASS | `RunBudget` caps provider attempts, tokens, and elapsed time; graph assembly rejects any tool outside the frozen read-only surface |
| Evidence guardrail | PASS | `meridian.guardrails.evidence` validates quantitative provenance and keeps account citations separate from accountless knowledge guidance |
| Output guardrail | PASS | Numeric and citation replay produces a typed output verdict; failed prose gets one repair and then a deterministic safe fallback |
| Deterministic confidence and routing | PASS | The graph records the confidence/routing decision as the fifth guardrail stage; evidence quarantine always forces red |
| Interrupt and resume | PASS | Red interactive runs pause only with a SQLite checkpointer and resume with a typed `ReviewerDecision` |
| Review queue API | PASS | `GET /api/review-cases`, `GET /api/review-cases/{case_id}`, `POST /api/review-cases/{case_id}/decision`, and `GET /api/review-regressions` |
| Review persistence | PASS | Approve, override, request-data, and escalate actions are stored; requested sources survive a database round trip |
| Regression export | PASS | Reviewer corrections and recoverable run failures become versioned records exportable as JSON Lines or through the API |
| Safety report | PASS | `make evaluate-guardrails` writes JSON, CSV, and Markdown under ignored `artifacts/safety/` |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| All 36 packaged guardrail cases ran | PASS | 36/36 through the real offline graph |
| Zero hard-category false passes | PASS | 0/15; false-pass rate 0.0000 |
| No answerable case was falsely blocked | PASS | 0/21; false-block rate 0.0000 |
| No target, wrong-account, or post-cutoff leakage | PASS | 0 findings across every released evidence surface |
| Reviewer override creates a traceable regression | PASS | Store and HTTP integration tests assert case, assessment, system outcome, reviewer outcome, reason, and note |
| Review and regression write atomically | PASS | A forced regression-insert failure rolls the review case back to open |
| Pause/resume is traceable and non-duplicating | PASS | The paused trace has no `run_completed`; the resumed trace records one `review_resumed` and one `run_completed` |

The full suite passes with **490 tests passed, 1 intentionally skipped, and
95.19% coverage**. Ruff and strict mypy pass across 114 source files. The
guardrail evaluation spent **0 tokens** and made no provider call.

The mandatory locked-image gate also passes: `make phase0-verify` rebuilt both
images, ran 485 backend container tests with 6 expected skips at 95.24%
coverage, ran 7 frontend tests, built the production UI, passed the repository
policy scan on 242 files, and observed both application health checks become
healthy.

## Safety evaluation

The packaged set contains 15 hard refusal cases and 21 answerable behavioural
cases. Every hard case was blocked with its expected policy code, and every soft
case passed its named behavioural check.

| Measure | Result |
| --- | ---: |
| Hard false-pass rate | 0.0000 |
| False-block rate | 0.0000 |
| Behaviour pass rate | 1.0000 |
| Pass/block/escalate accuracy (within policy) | 1.0000 |
| Exact expected-disposition match | 0.6944 |
| Leakage findings | 0 |
| Tokens | 0 |

Observed dispositions: 15 blocked, 15 escalated, 6 auto-released.

**These are the numbers at the current commit, not the ones this phase first
measured.** Phase 7 recorded 0.5833 with 19 escalations and 2 auto-releases.
Four behavioural cases -- GE-020, GE-023, GE-024, and GE-026 -- now verify and
release where they previously failed verification and routed red, a consequence
of the Tree-of-Thought citation fix made in the post-phase audit. The superseded
figures are stated here rather than overwritten silently.

**The two disposition rows differ, and the gap is the finding rather than a
rounding detail.** Eleven behavioural cases -- GE-016 to GE-019, GE-021,
GE-022, GE-025, GE-027, and GE-034 to GE-036 -- were answered *and* routed red
to a person.

Section 22.4 asks for "pass/block/escalate accuracy", and for a behavioural case
two of those three are both correct. The packaged data says so itself: GE-025's
ideal response is to "report the probability ... and recommend human review",
and GE-034's is to "recommend waiting/monitoring or human review". Scoring only
an auto-released answer as correct would mark the packaged expectation wrong, so
the first row counts an escalation as within policy, and
`allowed_dispositions` in the artifact names exactly which dispositions each
case permits.

The second row is the stricter reading -- only an exact match with the single
nominal disposition counts -- and it is printed beside the first so the
escalation rate cannot be hidden by the looser number. Nothing was out of policy
on either reading: no answerable case was refused and no hard case was answered.

What the gap does show is that **only 6 of 21 answerable cases are released
without a human** -- 2 of 21 when this phase ran -- which is a heavily
conservative posture either way. That is safe, and it is not obviously useful: a
queue that receives three of every four answers is a queue nobody will read.
Phase 10 froze thresholds against the development split, and this is the number
that informed that choice.

Reproduce the report with:

```bash
make evaluate-guardrails
```

## Controls added in this phase

### Evidence is validated at the typed envelope

Account id and cutoff are checked on both lane envelopes, not only on nested
citations. Account evidence must name the requested account and may not come
from the knowledge base; knowledge guidance must be accountless and from the
knowledge base. Invalid metrics or citations are quarantined before merge. A
later clean retrieval round cannot erase an earlier boundary violation from the
routing decision.

### Provider cost has a hard stop

The largest legal path may consume eight provider attempts when each of four
logical generations needs its one schema repair. The runtime also caps a run at
60,000 tokens and 180 seconds before another model call may start. Exhaustion
does not invent an answer: the graph switches to verified deterministic prose
and records a review verdict.

### Review decisions are one auditable transaction

The review case is locked, resolved, and—when the action is override,
request-data, or escalate—the regression record is inserted on the same SQLite
transaction. An approval remains audit history but is not treated as a model
failure. A second decision on the same case returns a conflict rather than
silently overwriting the first reviewer.

## What each guardrail layer is worth

The layered guardrail design is only worth its cost if the layers do something.
The way to find out is to remove them, which is what `make evaluate-guardrail-stack`
does: no guardrails, intake only, intake plus evidence screening, and the full
stack. The arms are in `artifacts/safety/guardrail_stack.json`.

The same 36 cases go through four stacks, differing only in how many layers run.
Nothing else changes: same accounts, same questions, offline, zero tokens.

| Arm | Hard false pass | False block | Answered | Escalated | Errored | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| none | **0.7333** | 0.0000 | 9 | 17 | 1 | 281.6 ms |
| intake | 0.0000 | 0.0000 | 6 | 9 | 0 | 87.9 ms |
| intake + evidence | 0.0000 | 0.0000 | 6 | 9 | 0 | 84.8 ms |
| full | 0.0000 | 0.0000 | 6 | 9 | 0 | 92.6 ms |

**Intake is carrying the safety property.** Remove it and 11 of 15 hard cases
are answered or escalated instead of refused, one crashes outright -- a
non-existent account reaches the loader, because nothing checked it existed --
and mean latency triples, since a refused request otherwise costs nothing.

**The other two layers are indistinguishable from the full stack on this
suite**, on every measure. That is a negative result and it is reported as one.
It does not show that evidence screening and output verification do nothing: it
shows that these 36 cases do not exercise them, which is consistent with the
system evaluation, where output regeneration is 0.0000 because no draft has yet
failed verification. A suite that cannot separate two arms is evidence about the
suite as much as about the arms.

**Execution-stage controls are not an arm, and that is the third finding.** In
this system they are structural: the registry validates every tool argument, the
per-role allowlist is injected rather than supplied, and `assert_no_dangerous_tools`
refuses at assembly. There is no configuration that removes them, so the honest
comparison holds them fixed and says so rather than inventing a fourth arm that
would really be a different system.

The same is true of leakage. **Post-cutoff and wrong-account citations are zero
in every arm, including the one with evidence screening removed**, because the
cutoff is enforced in the loader and in retrieval rather than by a guardrail
stage. Point-in-time safety is not a layer that can be ablated here; it is where
the data comes from.

### The weakening lives outside the served system

An ablation needs the graph to run with a guardrail absent, and building that as
a configuration switch would have put a way to disable safety checks into the
production builder. It is not built that way. `meridian.graph.nodes` exposes
three seams -- `validate_intake`, `screen`, and `verify` -- each of which calls
the real check. The only subclass that overrides them is in
`meridian_eval.guardrail_ablation`, and `test_import_boundary.py` fails the
build if any served module imports that package. `build_graph` gained one
optional `nodes` argument; nothing reachable from the API or the CLI passes it.

## Known limitations

- The evaluation is deterministic and offline. That is the configuration whose
  policy controls are being measured; provider-generated wording remains
  covered by output replay and the opt-in live test, but was not billed here.
- **The routing thresholds escalate almost everything answerable.** Only 2 of
  21 answerable cases were auto-released; the other 19 went to a person. No case
  was refused that should have been answered, so this is conservatism rather
  than a safety failure, but a queue holding nineteen of twenty-one answers is
  not a workable review load. Threshold tuning is a development-split
  measurement task (section 22.7) and must be frozen before held-out evaluation,
  so it is recorded here rather than adjusted now.
- Numeric output replay recognizes numerals, not number words. A sentence such
  as “five of six drivers” does not receive the same exact numeric replay as
  “5 of 6”; model prompts avoid that form, but the verifier should eventually
  normalize a small number-word vocabulary.

  **Resolved.** `written_numbers` now reads a bounded vocabulary -- units,
  teens, tens, and hyphenated compounds up to ninety-nine -- so both forms
  replay identically. `one` and `zero` are read only inside an explicit `N of M`
  ratio: every occurrence of those two words in this project's own generated
  text is idiomatic (“quick one for the support team”, “roughly one quarter
  out”, “stuck near zero”), so counting them everywhere would fail sound
  narratives on English usage rather than on arithmetic. The guardrail suite is
  byte-identical after the change apart from its timestamp.
- The FastAPI review surface has no authentication yet. It is a local Phase 7
  workflow; deployment security belongs to the later API/deployment phases.
