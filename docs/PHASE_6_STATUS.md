# Phase 6 status: conflict gate and bounded Tree-of-Thought

Status: **Complete; exit gate passed on 2026-08-31**

Phase 5 always adjudicated linearly. Phase 6 adds the branch the plan calls for:
a deterministic gate decides whether the evidence for an account materially
disagrees with itself, and only then does the run spend four candidate
arguments, a critic pass, and two stress tests on it.

It also does the thing that makes the branch worth having: it measures whether
the branch is worth having. Section 15.7 asks the final report to "show whether
the added complexity earned its place", and on the evidence collected here the
honest answer is **not yet** -- for a reason that is understood and stated below
rather than smoothed over.

## Deliverables

| Plan task | Status | Evidence |
| --- | --- | --- |
| Conflict features and rules | PASS | `meridian.graph.conflict`; eight triggers, one per section 15.1 bullet |
| Generate four candidates | PASS | `ForecastAdjudicator.generate_candidates`; one per canonical outcome, always |
| Hard checks | PASS | `hard_checks`; the six section 15.3 rules, each with a test |
| Critic rubric | PASS | `score_candidate`; section 15.4's five dimensions, weighted equally |
| Beam pruning | PASS | `TOT_BEAM_WIDTH = 2`, applied by a single slice |
| Stress test | PASS | `_stress_child`; one depth-two child per survivor, re-checked and re-scored |
| Tie vote | PASS | `_consistency_vote`; called from one `if`, at most once |
| Escalation | PASS | A persistent tie abstains with `UNRESOLVED_CONFLICT` and a red review case |
| Structured branch summaries | PASS | `CandidateHypothesis` with scores; no reasoning prose is stored |
| Linear versus ToT ablation | PASS | `meridian_eval.tot_ablation`, `make evaluate-tot` |

## Exit gate

| Criterion | Result | Evidence |
| --- | --- | --- |
| Beam width and depth are provably bounded | PASS | `test_the_search_is_bounded_in_width_and_depth`, and again on real runs |
| Hard-invalid branches cannot win | PASS | `test_a_hard_invalid_branch_scores_zero_however_well_it_argues` |
| Persistent ties route to review | PASS | `test_two_indistinguishable_branches_abstain_rather_than_choose` |

457 tests passing at 95.9% coverage, ruff and mypy strict clean across 106 files.
66 of those tests are new in this phase.

### How the bounds are shown

The search has no loop that could deepen it. `_stress_child` is called once per
survivor and never recurses; `TOT_BEAM_WIDTH` slices the ranked list once;
`_consistency_vote` is reached from a single `if`. So the branch count is
`4 + beam` by construction, and the test asserts that on generated fixtures and
again on every conflicting account in the index.

Hard invalidity is enforced by score, not by rank: a branch that fails any
section 15.3 check is set to **zero**, not merely marked. The test gives an
invalid branch the model's own favourite outcome and its full prior -- so on the
rubric alone it would outrank everything -- and requires it to lose to a weaker
valid one anyway.

## The ablation, and what it says

`make evaluate-tot` runs both arms over the **development split only**. Section
22.7 forbids tuning against held-out outcomes, and a comparison whose purpose is
to inform a threshold must not be measured on the test set.

207 development accounts scanned; **106 (51.2%) triggered the gate**. Both arms
then ran over those 106 with identical evidence, differing only in where the
gate routed. No provider was configured, so both arms cost zero tokens.

| Metric | Linear | Conflict-gated |
| --- | ---: | ---: |
| Released a label | 106 | 37 |
| Abstained | 0 | 69 |
| Accuracy on what it released | 0.849 | 0.919 |
| Escalation rate | 0.915 | 0.943 |
| Supported-claim rate | 1.000 | 1.000 |
| Driver fidelity | 0.467 | 0.495 |
| Tokens | 0 | 0 |

The escalation rates were 0.623 and 0.840 until the ablation's definition of
"auto-released" was corrected: it counted **green and amber**, while
`meridian.serving.scan` -- the running system -- counts green alone. Section
16.5 puts amber in asynchronous review, so an amber answer is reviewed, and
including it overstated what reaches a user unchecked. Auto-release under the
corrected definition is 9 and 6, not 40 and 17. The two constants share a name
and a test now asserts they are equal.

**These are the numbers at the current commit, not the ones this phase first
measured.** When Phase 6 shipped, the gated arm scored 0.892 on supported claims
and escalated 0.877; a later fix -- a Tree-of-Thought candidate that cited
nothing when all of its evidence was neutral, corrected in the post-phase audit
-- moved both. The paired comparison below is unchanged by it. The stale figures
are recorded here rather than overwritten silently, because a table that quietly
acquires better numbers is exactly what an evaluation section should not do.

Those two accuracy figures are not comparable, which is why the ablation also
reports the paired view. The gated arm abstains on what it finds hardest, so
whatever it releases is an easier set by construction.

**On the 37 accounts both arms answered:**

| | Linear | Conflict-gated |
| --- | ---: | ---: |
| Accuracy | 0.892 | 0.919 |

They agree on 86.5% of those. Of the 5 disagreements, the search was right on 2
and the linear path on 1.

**On the 69 accounts the gated arm declined and the linear arm answered:** the
linear answer was wrong on 12. That is a 17.4% hit rate against a 15.1% base
error rate on the same subset -- so the abstentions identify errors at close to
the rate that declining 69 answers at random would have.

### The verdict, and the reason for it

On this evidence the conflict-gated search **does not earn its place in the
deterministic configuration**. It blocks 57 correct answers to catch 12 wrong
ones, and its accuracy advantage on the shared set rests on five disagreements.

The mechanism is understood. With deterministic candidates, four of the five
rubric dimensions take the same value on every branch: the templated generator
always cites the available evidence, always names the counterevidence, and never
overreaches. Only `baseline_plausibility` varies, and it is a monotone transform
of the calibrated prior. So the search's ranking *is* the model's ranking -- which
is exactly what an 86.5% agreement rate with zero-token runs looks like -- and
the only thing the search adds is a stricter abstention rule.

The rubric's discriminating power depends on the candidates being genuinely
argued, which needs a provider. **That run has not been done.** It costs money
and takes roughly an hour, so it is offered rather than assumed:

```bash
make evaluate-tot          # offline, free, the numbers above
./scripts/python_in_docker.sh python scripts/evaluate_tot.py --use-provider --limit 20
```

Until it is, the honest position is that Phase 6 delivers the structure the plan
specifies and a measurement showing the structure alone is not enough.

## Three decisions worth recording

### The outcome is selected from a closed set, never generated

Phase 5 recorded that the language model cannot choose the label. The search
changes how a label is chosen at a conflict but not that rule: the four
candidates are the four canonical outcomes, supplied one per branch, and the
winner is picked by a deterministic score. A model may argue each case. It
cannot add an outcome, drop one, change a prior, or award a point.

### The critic is deterministic, for the same reason the retrieval grader is

Section 15.4 asks for order randomisation to control critic position bias. A
deterministic critic has no position to be biased from, and every dimension it
scores is computable from evidence the run already verified. This mirrors D-018.

One consequence is worth stating rather than hiding: the order-permuted
consistency vote of section 15.6 is order-invariant under this critic, so it
always reproduces the same scores and therefore always *confirms* a tie rather
than breaking one. It is the seam where a model-backed critic would change the
answer, and the ablation reports how often it fires -- but with no provider
configured, a tie always becomes an abstention.

### The relative rules skip rather than guess

Two of section 15.1's triggers -- "weak adoption", "above-median adoption" --
need a portfolio baseline. `PortfolioBaseline` measures the medians once from
the runtime repository, which holds no labels, and carries the dataset and
calculation versions with it. Without one, the two rules are **skipped and
recorded as skipped**. Comparing against a default of zero would classify every
account as above median and fire the rule on the whole portfolio.

The sweep costs about two seconds, so `BaselineProvider` defers it until a run
actually reaches the gate. A blocked request, or one that degrades on coverage,
never pays for it.

## A defect the ablation found

The gated arm's supported-claim rate came back below 1.0, which led to reading
the recovery path. A Tree-of-Thought winner whose narrative failed output
verification was being routed to `fast_adjudication` for its one permitted
regeneration -- and `fast_adjudication` rebuilds the decision around the
calibrated model's most likely outcome. A search that had selected `Renewed`
would have silently returned `Churned` under the same run id, reported as the
search's choice.

`ForecastDecision.selected_by` now records which adjudicator chose the outcome,
and a failed Tree-of-Thought draft goes straight to the safe fallback, which
rewrites only the prose and argues the outcome the decision actually carries.

That fix stopped the search's choice being replaced, but it did not take the
supported-claim rate to 1.0. The remaining shortfall was a second, narrower
defect found later: a candidate whose retrieved evidence was *entirely neutral*
cited nothing at all, so output verification failed on every such run. Naming the
neutral evidence closed it, and the gated arm now scores 1.000 -- the same as the
linear arm, which is what it should always have been, since both read the same
bundle.

## Known limitations

- **The provider arm of the ablation is unrun.** See above. Everything reported
  here is the deterministic configuration.
- **The rubric weights are equal because section 15.4 names no weights.** Any
  other split would be a number chosen to no criterion. They are frozen; Phase
  10 may tune them, and must do so on the development split only.
- **The tie band is the plan's 0.10 applied to a rubric score, not to a
  probability.** Because four of five dimensions are often identical, the
  effective band in probability terms is roughly five times tighter, which is
  most of why the abstention rate is 65%. This is recorded rather than tuned:
  section 22.7 forbids adjusting a threshold against these numbers, since the
  scan includes accounts that will appear in later evaluation.
- **Conflict severity does not yet feed back into how hard the search tries.**
  A `low` conflict and a `severe` one get the same four branches and the same
  beam. Section 15 does not ask for more, but a budget proportional to severity
  is the obvious next economy.
- **`avg_csat` is aliased to `avg_closed_csat_26w` for driver fidelity.** The
  archive's ground-truth drivers predate the recomputation in section 8.3, so
  one metric name moved. The alias is declared in `DRIVER_ALIASES`.
