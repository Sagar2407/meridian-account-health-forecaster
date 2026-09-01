# Phase 10 status: observability and the full evaluation

Status: **Complete; exit gate passed on 2026-09-01**

Every earlier phase measured one thing at a time. This phase measures the
system: five dimensions in one pass over a split, thresholds frozen and
digested before the held-out run, and a result directory that ties every
reported number to the commit that produced it.

The headline is honest rather than flattering. On the held-out split the
forecaster beats its majority baseline by a wide margin, cites nothing it
should not, and never claims a number it cannot support — and it
**auto-releases nothing at all**, and its calibration misses the target.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Local structured tracing | PASS | `meridian.graph.observability`; JSON Lines per run, with estimated cost and disposition |
| Optional LangSmith | PASS | `LANGSMITH_TRACING=true` mirrors; a broken mirror is recorded and the run completes |
| All five evaluation dimensions | PASS | `meridian_eval.dimensions`; 22.1, 22.2, 22.3, 22.5 computed, 22.4 read from the safety artifact |
| Freeze thresholds before the held-out run | PASS | `meridian.graph.thresholds`, digest `5e23d7f9d9fef896` (v1), enforced by `test_thresholds.py` |
| Markdown, JSON, CSV, PNG artifacts | PASS | `REPORT.md`, `results.json`, `runs.csv`, `threshold_study.csv`, two PNGs per run |
| Reproducible directory tied to commit SHA | PASS | `artifacts/evaluation/<commit>-<timestamp>/` |
| Document limitations honestly | PASS | Below, and in every report the harness writes |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Every final-report claim is traceable to an artifact | PASS | `render()` reads only from `results.json`; a test asserts the report contains no number the result does not, and that every file the report names exists |

The gate is structural, not a promise. `meridian_eval.report.render` takes the
result dictionary and formats it; there is no literal in that function a reader
could mistake for a measurement. `test_every_file_the_report_names_is_written`
fails if the report advertises an artifact the directory lacks.

## Results

Both splits, offline (no provider), thresholds `5e23d7f9d9fef896`.

| Measure | Development (207) | **Held-out test (53)** | Target |
| --- | ---: | ---: | --- |
| Released / abstained | 137 / 70 | 37 / 16 | — |
| Macro F1 | 0.8468 | **0.7490** | ≥ 0.70 ✅ |
| Accuracy | 0.9197 | 0.8649 | — |
| Majority baseline | 0.4891 | 0.4595 | beat it ✅ |
| Supported-claim rate | 1.0000 | **1.0000** | ≥ 0.95 ✅ |
| Exact numeric agreement | 1.0000 | **1.0000** | 1.00 ✅ |
| Citation precision | 1.0000 | 1.0000 | — |
| Wrong-account citations | 0 | **0** | 0 ✅ |
| Post-cutoff citations | 0 | **0** | 0 ✅ |
| Expected calibration error | 0.1568 | **0.1712** | ≤ 0.10 ❌ |
| Completion rate | 1.0000 | 1.0000 | — |
| Auto-release rate | 0.0290 | **0.0000** | — |
| Exhausted-retrieval safe fallback | 1.0000 (1 run) | no such run | 1.00 ✅ |
| p50 / p95 latency | 162 / 251 ms | 167 / 261 ms | p95 < 20 s ✅ |

### The routing works; the release rate does not

Error rate inside each band, development split:

| Band | Runs | Errors | Error rate |
| --- | ---: | ---: | ---: |
| green (auto-released) | 6 | 0 | 0.000 |
| amber | 68 | 2 | 0.029 |
| red | 63 | 8 | 0.127 |

That is what a working router looks like: the error rate rises monotonically as
the band gets more cautious, and every one of the eight errors on the
development split landed in red. The confidence score is ranking correctly.

And on the held-out split **zero of 53 accounts were auto-released**. A system
whose entire output is review load does not save a CS team any work, however
well it ranks.

### What the thresholds would buy, measured

Development split only — section 22.7 forbids sweeping on held-out outcomes.

| Bands | Auto-released | Wrong | Error rate among auto-released |
| --- | ---: | ---: | ---: |
| **0.85 / 0.70 (frozen)** | 6 of 207 | 0 | 0.000 |
| 0.60 / 0.50 (most permissive measured) | 70 of 207 | 4 | 0.057 |

Loosening the bands would release **twelve times more** answers, and about one
in eighteen of them would be wrong with nobody checking. The full sweep over 29
candidate pairs is in `threshold_study.csv`.

**No threshold was changed.** That trade — a 5.7% unreviewed error rate for a
usable release rate — is a business decision about how much a wrong advisory
call costs, and there is nothing in the data that settles it. It is recorded
here so the choice can be made deliberately rather than inherited from a
default.

### Calibration misses its target

ECE is 0.1712 held out against a target of at most 0.10. Section 22.6 allows
"or clear improvement over uncalibrated model" as an alternative; Phase 2
measured 0.1481 uncalibrated against 0.1346 calibrated, an improvement of
0.0135. That is an improvement, but calling it *clear* would be generous, so
**this target is reported as not met on either reading.**

The Brier score (0.0671) and the band table above say the ranking is sound; ECE
says the absolute probabilities are over-confident. That is the specific,
useful version of the finding, and it is the one that matters for the release
bands: a threshold on a mis-scaled probability is a threshold on the wrong
quantity.

## Verification

621 tests pass on the host at 94.86% coverage; 66 are new in this phase,
including the post-phase audit below.

`make phase0-verify` passed on the locked images: formatting over 139 files,
ruff, strict mypy over 138 source files, **591 backend container tests with 6
expected skips at 94.78% coverage**, 87 frontend tests, the production frontend
build, the repository policy scan over 292 files, and both application health
checks.

The first attempt at that gate failed, usefully: Prettier had no ignore file, so
it checked a generated `coverage/coverage-summary.json` that earlier local runs
had written into the mounted directory. `frontend/.prettierignore` now excludes
generated output.

## A defect the evaluation found

The development run reported a supported-claim rate of 0.9708, and every one of
the seven failures across both splits was a Tree-of-Thought run. None was a
numeric-claim failure. The cause was specific:

**A Tree-of-Thought candidate cited nothing when every retrieved citation was
directionally neutral.** `deterministic_candidate` selects citations that agree
or disagree with the outcome it is arguing. On an account whose evidence is all
routine — a how-to ticket, a monthly touchpoint — both lists come back empty, so
the candidate's narrative named no document, and output verification failed it
with "cites no evidence although evidence was retrieved". The run then fell
back to a deterministic narrative and routed red.

Nothing unsafe was released: the control did exactly what it exists to do. But
it meant the Tree-of-Thought path failed verification on every such account and
was routed red on the strength of a defect rather than of the evidence. The
candidate now names the neutral evidence it read and says why it is neutral,
which is both true and what the verifier was asking for. Supported-claim rate
went to **1.0000 on both splits**, and the three named accounts moved from red
to amber.

**The held-out split was run twice**: once before this fix and once after. No
threshold changed between them, and the pre-fix held-out numbers were macro F1
0.7490 (identical — the fix touches narratives, not outcomes) with a
supported-claim rate of 0.9189. Both runs are recorded; this is stated rather
than quietly presenting the second as the only one.

## Two frontend defects found at the same time

The evaluation compared the API's vocabularies against the browser's and found
two that did not match:

- `Citation.signal` is `adverse | favorable | neutral`. The browser typed it
  `positive | negative | neutral`, so the evidence drawer's signal label
  rendered blank and every citation landed in the "other context" column.
- `Driver.direction` is `supports | opposes`. The browser compared against
  `positive`, so **every driver rendered as "raises risk"**, including the ones
  supporting renewal.

Both were type-level lies that TypeScript could not catch, because nothing
checked the browser's types against the server's. Both are fixed and pinned by
tests.

## Post-phase audit

A sweep for inconsistencies after the phase closed found five things, all fixed
in the same commit as this note.

**An abstention carried no rule codes, so section 22.6's safe-fallback target
measured nothing.** `human_route` returns structured codes; `abstention_route`
returned only a band and a sentence. Every run that abstained -- 70 of 207 on
development, 16 of 53 held out -- therefore carried no codes at all, and the
`exhausted_retrieval_fallback` block looked for `critical_coverage_missing`
among them and always found zero. Both evaluations reported that target as "not
measured" and it read like an absent input rather than a broken query. Fixed:
`abstention_route` returns the same `RouteVerdict`, and the metric now reports
1.0000 over the one development run that reached it.

**The browser knew nothing about `requested_data`.** The API sends it on every
review case; the client type omitted it, so a resolved data request showed a
reviewer no record of what had been asked for. Fixed, and the queue now shows it.

**Two vocabularies for "signal" in one API.** A citation's was
`adverse | favorable | neutral`; a recent-activity item's was
`positive | negative | neutral`. Both are now the tool layer's `EvidenceSignal`.
The browser's guardrail chip was named after the signal classes despite meaning
pass/fail, which is why renaming them silently unstyled it; it is now
`chip--pass` / `chip--fail`.

**Two dead public names.** `verify_draft` and `reset_serving_state` were
defined, exported, and called by nothing. Removed.

**Three tests whose assertions all sat inside a loop over a runtime
collection.** They would have passed over an empty list. Each now asserts the
collection is non-empty first.

### The test that should have caught three of these earlier

`backend/tests/test_browser_contract.py` compares the browser's declared types
against the Pydantic models they mirror -- field names and literal unions. It
exists because the decision card is served as `dict[str, Any]` and therefore has
no OpenAPI schema, which is how `Citation.signal`, `Driver.direction`, and
`Driver.feature` all drifted without either type-checker noticing.

Writing it also produced a small lesson in its own right: the first parser used
a lazy `\{(.*?)\n\}`, which runs past a type written on one line and into the
next declaration. It reported `RequestedData` as declaring eighteen fields
belonging to `ForecastDecision`. The parser is brace-matched now.

It **skips inside the backend container**, which excludes `frontend/` by design,
exactly as `test_dataset_source.py` skips without the archive. That takes the
container's skip count from 6 to 30. The tests run on a developer checkout and
in CI, which is where a drifting client would be introduced; a reader comparing
the two counts should know why they differ.

## Decisions worth recording

### Thresholds are frozen source, not settings

There is no environment variable that moves a review band. A threshold an
operator can change between two runs is not a calibration, and a held-out
result measured against a movable threshold means nothing. Changing one is a
source edit, a version bump, and a new digest — and `test_thresholds.py` fails
if the digest moves without the version, so the change cannot reach a held-out
run unnoticed.

### One pass feeds every dimension

Three of the five dimensions are properties of runs rather than of the model.
Running the graph once per dimension would mean four passes over the same
accounts. `collect_runs` records enough structure — rule codes, citation ids,
counts — for each dimension to compute from, so a full evaluation of the
development split is one seven-minute pass.

The threshold sweep is exact rather than approximate for the same reason: only
three routing rules read a threshold, so the other rules' verdicts are recorded
once from the real run and reused across all 29 candidates.

### The report cannot say what the result does not

`render()` formats the result dictionary and nothing else. This is the exit
gate expressed as a function signature.

## Known limitations

- **Calibration misses its target and is not fixed here.** Recalibrating the
  model after seeing held-out ECE is exactly what section 22.7 forbids. The
  measurement is recorded; the remedy belongs to a future round that refits on
  development data and re-freezes before touching the test split again.
- **`Contracted` is barely measurable on the held-out split.** Two accounts
  carry that label, and its per-class F1 of 0.2857 rests on them. It is
  reported because omitting a weak class would flatter the average, but it
  should not be read as a measurement.
- **No LLM-judge metric.** Section 22.2 permits one only after validation
  against a double-reviewed human sample. No such sample exists, so the
  grounded-explanation block reports `judge_metrics: null` with the reason
  rather than a number nobody validated.
- **Everything here is the offline configuration.** No provider was configured,
  so narratives are deterministic and token cost is zero. A provider-backed run
  would change the wording that output verification checks, not the outcomes,
  the routing, or the citations — but that is an argument, not a measurement,
  and it has not been made.
- **Estimated cost is an estimate.** `TOKEN_PRICES` is a static table that goes
  stale. It answers "cents or dollars", not "what was I billed", and every
  surface that shows it says so.
- **LangSmith mirroring has never run against a live project.** The disabled
  path, the missing-package path, and the broken-client path are all tested;
  the working path needs an API key and has not been exercised.
- **The exhausted-retrieval fallback rests on one development run.** One
  account in 207 reached the cutoff with critical coverage missing, and it
  abstained rather than forecasting. No held-out account did, so that split
  reports the target as not measured. One observation is a demonstration that
  the path works, not a rate.
- **The result directory is not committed.** `artifacts/` is git-ignored, so
  the numbers above are reproducible from this commit rather than stored with
  it: `make evaluate-system SPLIT=test`.
