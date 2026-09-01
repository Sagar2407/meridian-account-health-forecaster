"""The bounded Tree-of-Thought search (plan sections 15.2 to 15.6).

Phase 6's exit gate is three claims, and each one is shown here rather than
argued:

1. **Beam width and depth are provably bounded.** The search is driven with more
   candidates than the beam and asked how many branches it produced, and every
   branch's recorded depth is checked against the limit.
2. **Hard-invalid branches cannot win.** A branch that fabricates a number is
   given an otherwise perfect rubric profile and must still lose to a weaker
   valid one.
3. **Persistent ties route to review.** Two indistinguishable branches must
   produce an abstention with no outcome, not a coin flip.
"""

from datetime import date

import pytest

from meridian.agents.forecast_adjudicator import (
    CandidateSet,
    ForecastAdjudicator,
    candidate_brief,
    deterministic_candidate,
)
from meridian.contracts import (
    MAX_CANDIDATE_DRIVERS,
    MAX_TOT_DEPTH,
    OUTCOME_CLASSES,
    TOT_BEAM_WIDTH,
    CandidateHypothesis,
    Citation,
    CoverageReport,
    Driver,
    EvidenceBundle,
    MetricObservation,
    QuantitativeEvidence,
    RetrievalEvidence,
    RetrievalObservation,
)
from meridian.graph.tot import (
    MINIMUM_WINNING_SCORE,
    RUBRIC_WEIGHTS,
    TIE_BAND,
    evaluate,
    hard_checks,
    score_candidate,
    search,
    weighted_score,
)
from meridian.llm.base import GenerationError
from meridian.llm.fake import ScriptedGenerator

CUTOFF = date(2026, 3, 1)
DISTRIBUTION = {"Churned": 0.55, "Contracted": 0.20, "Renewed": 0.18, "Expanded": 0.07}


def _citation(doc_id: str, signal: str, score: float = 0.8, **overrides: object) -> Citation:
    payload: dict[str, object] = {
        "doc_id": doc_id,
        "parent_id": doc_id,
        "source_type": "support_ticket",
        "subtype": "Escalation",
        "account_id": "ACC-1042",
        "doc_date": date(2026, 1, 1),
        "excerpt": "text",
        "retrieval_score": score,
        "signal": signal,
    }
    return Citation(**{**payload, **overrides})


def _bundle(citations: tuple[Citation, ...] | None = None) -> EvidenceBundle:
    """Return a bundle with adverse and favourable evidence on the record."""

    items = (
        citations
        if citations is not None
        else (_citation("TCK-1", "adverse", 0.9), _citation("EVT-1", "favorable", 0.7))
    )
    quantitative = QuantitativeEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        metrics=(
            MetricObservation(
                name="adoption_level_last_q",
                value=42.5,
                window="last 13 observed weeks",
                source="usage_weekly",
                coverage=13,
                calculation_version="features-1.0.0",
            ),
        ),
        distribution=dict(DISTRIBUTION),
        predicted_outcome="Churned",
        model_probability=0.55,
        drivers=(
            Driver(
                feature="adoption_level_last_q",
                value=42.5,
                contribution=-0.31,
                direction="supports",
            ),
            Driver(
                feature="open_high_priority_count",
                value=1.0,
                contribution=0.12,
                direction="opposes",
            ),
        ),
        coverage=CoverageReport(expected_weeks=13, observed_weeks=13),
    )
    retrieval = RetrievalEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        observations=(RetrievalObservation(sub_goal="support", query="support", citations=items),),
    )
    return EvidenceBundle(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        quantitative=quantitative,
        retrieval=retrieval,
        coverage=quantitative.coverage,
        supporting=tuple(item for item in items if item.signal == "adverse"),
        counterevidence=tuple(item for item in items if item.signal == "favorable"),
    )


def _candidates(bundle: EvidenceBundle) -> tuple[CandidateHypothesis, ...]:
    """Return one deterministic candidate per canonical outcome."""

    return tuple(deterministic_candidate(bundle, outcome) for outcome in DISTRIBUTION)


# -- Section 15.2: depth-one generation --------------------------------------


def test_one_candidate_is_argued_for_every_canonical_outcome() -> None:
    """Section 15.2: generate one candidate for each canonical outcome."""

    bundle = _bundle()
    generation = ForecastAdjudicator().generate_candidates(bundle)
    assert [item.outcome for item in generation.candidates] == list(DISTRIBUTION)
    assert generation.source == "deterministic"
    assert set(DISTRIBUTION) == set(OUTCOME_CLASSES)


def test_each_candidate_carries_what_section_15_2_requires() -> None:
    """Outcome, prior, at most two drivers, citations, and a falsifiable line."""

    bundle = _bundle()
    for candidate in _candidates(bundle):
        assert candidate.model_prior == pytest.approx(DISTRIBUTION[candidate.outcome])
        assert len(candidate.key_drivers) <= MAX_CANDIDATE_DRIVERS
        assert candidate.rationale
        assert candidate.strongest_counterevidence
        assert candidate.depth == 1


def test_a_model_may_argue_a_case_but_cannot_change_the_outcome_set() -> None:
    """The four branches are fixed here; a model supplies rationales only."""

    bundle = _bundle()
    reply = (
        '{"candidates": [{"outcome": "Renewed", "rationale": "Usage is holding at 42.5.", '
        '"supporting_citation_ids": ["EVT-1"], "counterevidence_citation_ids": ["TCK-1"], '
        '"strongest_counterevidence": "TCK-1", "key_drivers": ["adoption_level_last_q"]}, '
        '{"outcome": "Liquidated", "rationale": "An outcome that does not exist.", '
        '"supporting_citation_ids": [], "counterevidence_citation_ids": [], '
        '"strongest_counterevidence": "", "key_drivers": []}]}'
    )
    generation = ForecastAdjudicator(ScriptedGenerator([reply])).generate_candidates(bundle)

    assert [item.outcome for item in generation.candidates] == list(DISTRIBUTION)
    renewed = next(item for item in generation.candidates if item.outcome == "Renewed")
    assert renewed.rationale == "Usage is holding at 42.5."
    assert renewed.source == "model"
    # The invented outcome is dropped, and its neighbours keep their priors.
    assert all(
        item.model_prior == pytest.approx(DISTRIBUTION[item.outcome])
        for item in generation.candidates
    )


def test_a_provider_failure_still_argues_every_outcome() -> None:
    """A search that cannot start because a model failed would be worse than one
    that starts from templated arguments."""

    generation = ForecastAdjudicator(
        ScriptedGenerator([GenerationError("down")])
    ).generate_candidates(_bundle())
    assert len(generation.candidates) == len(DISTRIBUTION)
    assert generation.source == "deterministic"
    assert generation.fallback_reason is not None


def test_the_candidate_brief_names_the_outcomes_and_the_drivers() -> None:
    """A model can only argue what it was shown."""

    brief = candidate_brief(_bundle(), tuple(DISTRIBUTION))
    for outcome in DISTRIBUTION:
        assert outcome in brief
    assert "adoption_level_last_q" in brief
    assert "Citable document ids" in brief
    assert set(CandidateSet.model_fields) == {"candidates"}


# -- Section 15.3: hard pruning ----------------------------------------------


def test_a_fabricated_number_is_hard_pruned() -> None:
    """Section 15.3: a candidate that contradicts exact metrics is rejected."""

    bundle = _bundle()
    candidate = deterministic_candidate(bundle, "Churned").model_copy(
        update={"rationale": "Adoption collapsed to 3.14159 index points."}
    )
    failures = hard_checks(candidate, bundle)
    assert any("contradicts exact metrics" in failure for failure in failures)


def test_a_latent_field_is_hard_pruned() -> None:
    """Section 15.3: a candidate using a forbidden target or latent label."""

    bundle = _bundle()
    candidate = deterministic_candidate(bundle, "Churned").model_copy(
        update={"rationale": "The health_archetype field says this account is failing."}
    )
    assert any("forbidden latent field" in failure for failure in hard_checks(candidate, bundle))


def test_a_citation_from_another_account_is_hard_pruned() -> None:
    """Section 15.3: a candidate containing a citation from another account."""

    stolen = _citation("TCK-9", "adverse", account_id="ACC-9999")
    bundle = _bundle((stolen, _citation("EVT-1", "favorable")))
    candidate = deterministic_candidate(bundle, "Churned").model_copy(
        update={"supporting_citation_ids": ("TCK-9",)}
    )
    assert any("another account" in failure for failure in hard_checks(candidate, bundle))


def test_a_post_cutoff_citation_is_hard_pruned() -> None:
    """Section 15.3: a candidate using evidence from after the cutoff."""

    future = _citation("TCK-F", "adverse", doc_date=date(2026, 12, 1))
    bundle = _bundle((future, _citation("EVT-1", "favorable")))
    candidate = deterministic_candidate(bundle, "Churned").model_copy(
        update={"supporting_citation_ids": ("TCK-F",)}
    )
    assert any("after the cutoff" in failure for failure in hard_checks(candidate, bundle))


def test_an_invented_citation_is_hard_pruned() -> None:
    """Section 15.3: a candidate making an unsupported factual claim."""

    bundle = _bundle()
    candidate = deterministic_candidate(bundle, "Churned").model_copy(
        update={"supporting_citation_ids": ("TCK-000000",)}
    )
    assert any("unsupported factual claim" in f for f in hard_checks(candidate, bundle))


def test_ignoring_the_evidence_against_a_candidate_is_hard_pruned() -> None:
    """Section 15.3: a candidate that omits material disconfirming evidence."""

    bundle = _bundle()
    candidate = deterministic_candidate(bundle, "Churned").model_copy(
        update={"counterevidence_citation_ids": ()}
    )
    assert any("omits material disconfirming" in f for f in hard_checks(candidate, bundle))


def test_a_clean_candidate_passes_every_hard_check() -> None:
    """The checks must be passable, or the search would always abstain."""

    bundle = _bundle()
    assert hard_checks(deterministic_candidate(bundle, "Churned"), bundle) == ()


# -- Section 15.4: soft scoring ----------------------------------------------


def test_the_rubric_is_the_five_dimensions_the_plan_names() -> None:
    """Section 15.4's rubric, weighted equally because it names no weights."""

    assert set(RUBRIC_WEIGHTS) == {
        "qualitative_grounding",
        "conflict_resolution",
        "baseline_plausibility",
        "counterevidence_completeness",
        "actionability_without_overreach",
    }
    assert sum(RUBRIC_WEIGHTS.values()) == pytest.approx(1.0)
    assert len(set(RUBRIC_WEIGHTS.values())) == 1


def test_plausibility_is_measured_against_the_most_likely_outcome() -> None:
    """Four priors summing to one compress; a relative reading separates them."""

    bundle = _bundle()
    leader = score_candidate(deterministic_candidate(bundle, "Churned"), bundle)
    follower = score_candidate(deterministic_candidate(bundle, "Expanded"), bundle)
    assert leader["baseline_plausibility"] == pytest.approx(1.0)
    assert follower["baseline_plausibility"] == pytest.approx(0.07 / 0.55, abs=1e-4)


def test_claiming_certainty_costs_a_candidate_its_actionability_score() -> None:
    """An advisory system arguing a case must not announce a result."""

    bundle = _bundle()
    overreaching = deterministic_candidate(bundle, "Churned").model_copy(
        update={"rationale": "This account will churn, guaranteed."}
    )
    assert score_candidate(overreaching, bundle)["actionability_without_overreach"] == 0.0


def test_a_hard_invalid_branch_scores_zero_however_well_it_argues() -> None:
    """The Phase 6 exit gate: hard-invalid branches cannot win.

    The invalid branch here is given the model's own favourite outcome and its
    full prior, so on the rubric alone it would outrank everything. The hard
    check has to override that completely, not merely dock it.
    """

    bundle = _bundle()
    invalid = deterministic_candidate(bundle, "Churned").model_copy(
        update={"rationale": "Adoption is 999.99 and the health_band is red."}
    )
    weak_but_valid = deterministic_candidate(bundle, "Expanded")

    scored_invalid = evaluate(invalid, bundle)
    scored_valid = evaluate(weak_but_valid, bundle)

    assert scored_invalid.hard_check_passed is False
    assert scored_invalid.score == 0.0
    assert weighted_score(scored_invalid.soft_scores) > 0.0, "the rubric alone would have ranked it"
    assert scored_valid.score > scored_invalid.score


# -- Sections 15.5 and 15.6: bounds and termination --------------------------


def test_the_search_is_bounded_in_width_and_depth() -> None:
    """The Phase 6 exit gate: beam width and depth are provably bounded."""

    bundle = _bundle()
    result = search(_candidates(bundle), bundle)

    assert len(result.survivors) <= TOT_BEAM_WIDTH
    assert all(branch.depth <= MAX_TOT_DEPTH for branch in result.branches)
    assert {branch.depth for branch in result.branches} == {1, MAX_TOT_DEPTH}
    # Four depth-one branches plus at most `beam` depth-two children, and no
    # path that could produce more.
    assert len(result.branches) <= len(DISTRIBUTION) + TOT_BEAM_WIDTH


def test_every_survivor_is_made_to_confront_its_best_counterargument() -> None:
    """Section 15.5: one refined child per survivor, and it names the reason."""

    bundle = _bundle()
    result = search(_candidates(bundle), bundle)
    for branch in result.survivors:
        assert branch.depth == MAX_TOT_DEPTH
        assert "Stress test:" in branch.rationale
        assert "strongest verified reason this could be wrong" in branch.rationale


def test_a_clear_leader_is_released_with_its_branch_summaries() -> None:
    """Section 15.6: select the winner when it clears the bar and the tie band."""

    bundle = _bundle()
    result = search(_candidates(bundle), bundle)

    assert result.abstained is False
    assert result.winner is not None
    assert result.winner.score >= MINIMUM_WINNING_SCORE
    assert result.margin > TIE_BAND
    assert result.branches, "branch summaries are stored, not discarded"


def test_two_indistinguishable_branches_abstain_rather_than_choose() -> None:
    """The Phase 6 exit gate: persistent ties route to review.

    The deterministic critic is order-invariant, so the one permitted
    consistency vote reproduces the same scores and confirms the tie. That is
    the honest outcome: nothing in the run separates these two branches.
    """

    bundle = _bundle()
    tied = tuple(
        deterministic_candidate(bundle, outcome).model_copy(
            update={"model_prior": 0.5, "outcome": outcome}
        )
        for outcome in ("Churned", "Contracted")
    )
    result = search(tied, bundle)

    assert result.abstained is True
    assert result.winner is None
    assert result.tie_broken_by_vote is True
    assert "stayed within" in result.abstain_reason


def test_a_search_where_every_branch_is_invalid_abstains() -> None:
    """A tree with no valid leaf has no winner to promote."""

    bundle = _bundle()
    invalid = tuple(
        deterministic_candidate(bundle, outcome).model_copy(
            update={"rationale": "Adoption is 999.99."}
        )
        for outcome in DISTRIBUTION
    )
    result = search(invalid, bundle)

    assert result.abstained is True
    assert result.winner is None
    assert result.abstain_reason == "every candidate failed a hard check"
    assert len(result.pruned) == len(DISTRIBUTION)


def test_a_branch_below_the_quality_bar_is_not_released() -> None:
    """Section 15.6: a winner must clear the minimum quality score."""

    bundle = _bundle()
    poor = (
        deterministic_candidate(bundle, "Expanded").model_copy(
            update={
                "model_prior": 0.0,
                "supporting_citation_ids": (),
                "rationale": "Expanded is possible, guaranteed to be worth checking.",
            }
        ),
    )
    result = search(poor, bundle)
    assert result.abstained is True
    assert "release bar" in result.abstain_reason


def test_the_search_is_reproducible() -> None:
    """Section 22.7: a run decided by an unseeded shuffle is not reproducible."""

    bundle = _bundle()
    first = search(_candidates(bundle), bundle)
    second = search(_candidates(bundle), bundle)
    assert first.winner is not None and second.winner is not None
    assert first.winner.outcome == second.winner.outcome
    assert [branch.score for branch in first.branches] == [
        branch.score for branch in second.branches
    ]
