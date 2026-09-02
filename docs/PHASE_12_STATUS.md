# Phase 12 status: the evidence package

Status: **Complete; exit gate passed on 2026-09-01**

This phase built no new feature. Its job was to make every claim in the final
report checkable, and the interesting part of doing that was discovering where
the repository could not back a claim it was about to make. Three small code
changes came out of that: a duplicated gap on the degraded decision card, a
published evaluation whose artifact no command wrote, and the test that would
have caught the second.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Map every claim to repository evidence | PASS | `docs/EVIDENCE_MAP.md` |
| Capture final architecture diagram and UI screenshots | PASS | `docs/ARCHITECTURE.md` (corrected); `docs/screenshots/` |
| Select representative traces: fast, ToT, degraded, human review | PASS | `artifacts/traces/`; `make traces` |
| Summarise development evolution from Modules 1 through 6 | PASS | `docs/DESIGN_EVOLUTION.md` |
| Record actual evaluation results, limitations, and next steps | PASS | `docs/EVIDENCE_MAP.md`; results table with a command per row |
| Public deployment link | BLOCKED | Nothing is deployed yet; see `docs/DEPLOYMENT.md` |

## Exit gate

| Criterion | Result | How it was checked |
| --- | --- | --- |
| No claimed feature lacks code or evidence | PASS | Every row of `docs/EVIDENCE_MAP.md` names a file, test, or artifact |
| No claimed result lacks a reproducible metric artifact | PASS | Every result row names the artifact and the command that regenerates it |

## Five things this phase found

### The evaluation artifacts were not in the repository

`artifacts/` was gitignored in its entirety, so a reviewer cloning the repository
would have found no evaluation results at all — while `docs/EVIDENCE_MAP.md`
was about to cite thirty files inside it. A citation to a path no clone contains
is not evidence.

The whole tree is 676 KB of text and plots. The two things the ignore rule was
really protecting against — the trained model and the FAISS index — live under
`models/` and `data/indexes/` and are still ignored. So `artifacts/` is now
tracked, and the ignore rule says why.

### One committed artifact was reporting a superseded result

`artifacts/tot/tot_ablation.json` predated the audit commit that fixed the
Tree-of-Thought citation bug. It reported a supported-claim rate of **0.8919** for
the conflict-gated arm; re-running it at the current commit gives **1.0000**. Its
auto-release count moved 13 → 17 and its escalation rate 0.877 → 0.840.

Nothing had gone wrong at the time it was written — it was simply a measurement of
older code sitting in a directory that looked current. Every offline artifact was
re-run at this commit for the same reason: `evaluate-tot`, `evaluate-guardrails`,
`evaluate-retrieval`, and a bounded portfolio scan.

The 12-account portfolio scan run during the refresh confirmed Phase 8's finding
at twice the sample: **0 auto-released of 12**, 2 abstentions, everything else
queued. The committed artifact was then restored to the 6-account scan that
`docs/PHASE_8_STATUS.md` documents and analyses, so each phase document stays
true to the run it describes.

The system evaluation was re-run on both splits, at the final commit, and the
result is the strongest single piece of evidence in this package: comparing 359
values against the Phase 10 run, **every release-target metric is identical** --
macro F1 0.8468 and 0.7490, ECE 0.1568 and 0.1712, supported-claim 1.0000,
exact numeric agreement 1.0000, zero wrong-account and zero post-cutoff
citations.

Two groups moved. Latency percentiles, which are wall-clock diagnostics rather
than targets; and the embedded safety-routing block, where exact-disposition
match went 0.5833 to 0.6944 because four behavioural cases began verifying and
releasing instead of routing red -- the same Tree-of-Thought citation fix again,
which Phase 10's run predated. The Phase 10 directories therefore carried a
superseded block and were replaced rather than kept beside the new ones;
`docs/PHASE_7_STATUS.md` now records the same movement.

This was a reproducibility check, not tuning: the thresholds were frozen
throughout, their digest is unchanged, and no number was used to adjust
anything. Plan section 22.7 forbids tuning against held-out outcomes, and
nothing here reads one to make a decision.

### The architecture diagram had two edges the graph does not have

The published flowchart routed the degraded result through the shared routing
node, and showed only red routes reaching persistence. The compiled graph does
neither: `degraded_result` computes its own route and goes straight to `persist`,
and **every** route persists before the interrupt is even considered — which is
the whole point of placing the pause after persistence, so an abandoned review
leaves an open case rather than nothing.

The diagram now uses the graph's own node names, so it can be read against
`backend/src/meridian/graph/builder.py` line by line, and the captured traces
show the same edges at runtime.

### A reviewer was shown the same gap twice

Capturing the degraded trace surfaced a small defect in `nodes.degraded`: when
retrieval is unavailable, the merged coverage report already records that gap, and
the node appended a second copy differing only in capitalisation. `dict.fromkeys`
deduplicates exact strings, so both survived onto the decision card. The node now
appends only when no existing gap already names the reason.

This is minor, and it is the kind of thing only a captured artifact finds — the
tests asserted that a gap was recorded, not that it was recorded once.

### The deployed app reported an evaluation it had run as never run

`GET /api/evaluations/retrieval` reads
`artifacts/retrieval/retrieval_benchmark.json`. `scripts/evaluate_retrieval.py`
writes three CSVs and never wrote that file, so the endpoint answered `not_run`
permanently — for an evaluation whose numbers `docs/PHASE_3_STATUS.md`
publishes. The script now writes the headline summary alongside the CSVs, with
NaN rendered as null so an ungraded run cannot produce a file the endpoint
reports as unreadable.

`artifacts/` was also excluded from the production image, so even a correct
summary would not have reached a deployment. It is now copied in: it is
committed, under a megabyte, and the endpoint that reads it is part of the
served application.

### Three numbered requirements had unmet clauses

Reading `docs/REQUIREMENTS.md` against what the artifacts actually contain found
three requirements that were listed as satisfied while a clause of each was not
measured at all:

- **ER-005** asks for retrieval metrics "and downstream correctness". Passage
  quality was measured; what the answer did with the passage was not. It is now
  read off runs that already happened, so it costs nothing: on the held-out
  split, accuracy is **0.8438** when retrieval was satisfied on the first round
  and **0.8000** when it had to be rewritten and retried. Small samples, and the
  direction is the one you would expect.
- **ER-006** lists "resume behaviour" beside completion and latency, and nothing
  measured it. Four red-routed runs are now paused on the interrupt and resumed,
  one per reviewer action: **4 of 4 resume, finish, and resolve their case**, at
  a mean of about 8 ms.
- **ER-007** requires each result tied to an artifact naming the commit, data,
  model, **prompt**, and environment versions. Four of five were recorded. The
  manifest now carries a digest per prompt and one version across them.
- **ER-006 again**, on a second reading: it also lists **cost**. `estimate_cost`
  existed and the run metrics used it; the evaluation artifact did not record
  it. It does now, and reports 0.0000 USD because every published run is
  offline. `None` is carried through for an unpriced model rather than softened
  to zero -- an unpriced run is unknown, not free.

ER-006's last clause, portfolio concurrency, was already measured, in
`artifacts/portfolio/portfolio_scan.json` rather than in the system evaluation.
The evidence map points at it there rather than measuring it twice.

Registering the prompts found a fourth instruction nobody had counted: the MCP
server's own `instructions` field. This system never puts it in a prompt -- its
client is in-process -- but any other MCP client would read it into a model's
context, so it is versioned with the rest rather than excluded by a rule nobody
would revisit. `test_prompt_registry.py` scans the source for
`*_INSTRUCTIONS` constants and fails if one is not registered, which is how that
one was found.

## The traces

Four runs, one per path, captured by `make traces` offline at zero tokens. The
accounts are found by scanning rather than pinned, so a trace labelled *conflict*
is one the gate actually fired on:

| Path | Account | Route | Outcome | Confidence |
| --- | --- | --- | --- | ---: |
| fast_path | ACC-1001 | amber | Churned | 0.8363 |
| tot | ACC-1002 | amber | Renewed | 0.9207 |
| degraded | ACC-1000 | red | none | — |
| human_review | ACC-1000 | red | Renewed, overridden to Churned | 0.6395 |

The degraded run is **caused, not hunted for**: the retrieval service is made
genuinely unavailable and the graph is left to do whatever it does. Waiting for an
account whose coverage happened to collapse would have made the most important
failure path the least reproducible one.

The human-review run pauses on the interrupt, is resumed with a typed override,
and the correction is chosen to differ from what the run proposed. An override to
the same label is not an override, and a trace captioned "the reviewer disagreed"
that shows agreement would be worse than no trace at all.

## Known limitations

- **The deployment link cannot be produced here.** It needs a running
  deployment, which needs a decision about how the dataset, model, and index
  reach the image. Listed as blocked rather than quietly dropped.
- **No cold-start or warm-start timings.** Nothing is deployed, so there is
  nothing to measure. `docs/DEPLOYMENT.md` says what to measure once there is.
- **The evidence map is a map, not a report.** It says where each claim is
  backed; it does not write the prose. That is deliberate — a generated report
  section would be one more thing to keep in sync.
- **The traces are offline.** They exercise every node and cost nothing, but the
  narratives in them are the deterministic ones, not model-written. This is the
  same limitation every published metric in this repository carries.
