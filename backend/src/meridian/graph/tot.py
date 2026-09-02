"""The bounded Tree-of-Thought subgraph (plan section 15.2 to 15.6).

This runs only when the deterministic gate in `meridian.graph.conflict` fires.
Tree-of-Thought is a conditional subgraph here, never a default reasoning
mode, and the cost is the reason: four
candidates, a critic pass, and up to two stress tests are several times the work
of a linear adjudication.

The search is bounded by construction rather than by a counter someone
remembers to check:

* **Depth two.** `_stress_test` is called once, on the survivors, and never
  recurses. There is no loop that could go deeper.
* **Beam two.** `TOT_BEAM_WIDTH` slices the ranked list once.
* **One consistency vote.** `_consistency_vote` is called at most once, from a
  single `if`.

What a language model may contribute is one rationale per candidate. It cannot
choose an outcome -- the four canonical classes are supplied, one per candidate
-- and it cannot score anything: the critic is deterministic, for the same
reason the retrieval grader is (see D-018). Every number in a branch summary is
computed here from verified evidence.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from meridian.agents.forecast_adjudicator import (
    PROSE_SAFE_FIELD_NAMES,
    allowed_numbers,
    is_verified,
    written_numbers,
)
from meridian.contracts import (
    ADVERSE_OUTCOMES,
    MAX_TOT_DEPTH,
    TOT_BEAM_WIDTH,
    CandidateHypothesis,
    Citation,
    EvidenceBundle,
)
from meridian.retrieval.documents import forbidden_field_mentions
from meridian.tools.contracts import assert_safe_text

#: The frozen soft-scoring rubric of section 15.4. Section 15.4 names the five
#: dimensions but not their weights, so they are equal: any other split would be
#: a number chosen to no criterion, and section 22.7 requires thresholds to be
#: frozen before held-out execution rather than tuned toward an outcome.
RUBRIC_WEIGHTS: dict[str, float] = {
    "qualitative_grounding": 0.20,
    "conflict_resolution": 0.20,
    "baseline_plausibility": 0.20,
    "counterevidence_completeness": 0.20,
    "actionability_without_overreach": 0.20,
}

#: A winner must clear this score, and lead the runner-up by more than the tie
#: band, before the system will release a label at a conflict (section 15.6).
MINIMUM_WINNING_SCORE = 0.55
TIE_BAND = 0.10

#: Language that claims more certainty than an advisory system has. A candidate
#: using it loses actionability points rather than being rejected: it is a tone
#: problem, not a factual one, and the hard checks own the factual ones.
_OVERREACH_TERMS: tuple[str, ...] = (
    "guarantee",
    "guaranteed",
    "certainly",
    "definitely",
    "will churn",
    "will renew",
    "no doubt",
    "without question",
    "must approve",
    "i have approved",
)

#: Seed for the order-permuted consistency vote. Fixed so a tie resolves the
#: same way twice: section 22.7 requires runs to be reproducible, and a vote
#: decided by an unseeded shuffle is not.
CONSISTENCY_VOTE_SEED = 20260721


@dataclass(frozen=True)
class ToTResult:
    """The outcome of one bounded search, with every branch it considered."""

    winner: CandidateHypothesis | None
    branches: tuple[CandidateHypothesis, ...] = ()
    survivors: tuple[CandidateHypothesis, ...] = ()
    pruned: tuple[CandidateHypothesis, ...] = ()
    tie_broken_by_vote: bool = False
    abstained: bool = False
    abstain_reason: str = ""
    generations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    source: str = "deterministic"

    @property
    def margin(self) -> float:
        """Return how far the winner led the runner-up."""

        ranked = sorted((branch.score for branch in self.survivors), reverse=True)
        return ranked[0] - ranked[1] if len(ranked) > 1 else 1.0

    @property
    def total_tokens(self) -> int:
        """Return the tokens this search spent."""

        return self.prompt_tokens + self.completion_tokens


def _outcome_is_adverse(outcome: str) -> bool:
    """Return whether an outcome sits on the adverse side."""

    return outcome in ADVERSE_OUTCOMES


def _agreeing_citations(bundle: EvidenceBundle, outcome: str) -> tuple[Citation, ...]:
    """Return citations whose signal points the same way as `outcome`."""

    adverse = _outcome_is_adverse(outcome)
    return tuple(
        citation
        for citation in bundle.retrieval.citations
        if citation.signal != "neutral" and (citation.signal == "adverse") == adverse
    )


def _opposing_citations(bundle: EvidenceBundle, outcome: str) -> tuple[Citation, ...]:
    """Return citations whose signal contradicts `outcome`."""

    adverse = _outcome_is_adverse(outcome)
    return tuple(
        citation
        for citation in bundle.retrieval.citations
        if citation.signal != "neutral" and (citation.signal == "adverse") != adverse
    )


def hard_checks(candidate: CandidateHypothesis, bundle: EvidenceBundle) -> tuple[str, ...]:
    """Return every section 15.3 rule this candidate violates.

    The six rules are checked in the order the plan lists them. A candidate
    failing any of them is rejected outright rather than scored down: section
    15.3 says "immediately reject", and a hard-invalid branch that could still
    win on a strong soft score would make the hard checks decorative.
    """

    failures: list[str] = []
    text = f"{candidate.rationale} {candidate.strongest_counterevidence}"

    unverified = [
        value for value in written_numbers(text) if not is_verified(value, allowed_numbers(bundle))
    ]
    if unverified:
        failures.append(
            "contradicts exact metrics: "
            + ", ".join(f"{value:g}" for value in sorted(set(unverified))[:3])
        )

    leaked = set(forbidden_field_mentions(text)) - PROSE_SAFE_FIELD_NAMES
    if leaked:
        failures.append(f"uses a forbidden latent field: {sorted(leaked)}")

    by_id = {citation.doc_id: citation for citation in bundle.retrieval.citations}
    by_id.update({citation.doc_id: citation for citation in bundle.guidance})
    claimed = (*candidate.supporting_citation_ids, *candidate.counterevidence_citation_ids)
    unknown = sorted(set(claimed) - set(by_id))
    if unknown:
        failures.append(f"makes an unsupported factual claim, citing {unknown[:3]}")
    for doc_id in claimed:
        citation = by_id.get(doc_id)
        if citation is None:
            continue
        if citation.account_id is not None and citation.account_id != bundle.account_id:
            failures.append(f"cites {doc_id} from another account")
        if citation.doc_date is not None and citation.doc_date > bundle.cutoff:
            failures.append(f"cites {doc_id} from after the cutoff")

    opposing = _opposing_citations(bundle, candidate.outcome)
    if opposing and not candidate.counterevidence_citation_ids:
        failures.append(
            f"omits material disconfirming evidence: {len(opposing)} verified item(s) "
            "point the other way"
        )

    try:
        assert_safe_text(text, "rationale")
    except ValueError as error:
        failures.append(str(error))

    return tuple(dict.fromkeys(failures))


def score_candidate(candidate: CandidateHypothesis, bundle: EvidenceBundle) -> dict[str, float]:
    """Score one candidate on the frozen rubric of section 15.4.

    Every dimension is computed from verified evidence, so the critic has no
    position to be biased from. Section 15.4 asks for order randomisation or a
    fixed canonical order to control critic position bias; a deterministic
    scorer is immune to it, and the canonical order is fixed anyway so a reader
    sees the same branch table twice.
    """

    opposing = _opposing_citations(bundle, candidate.outcome)
    agreeing = _agreeing_citations(bundle, candidate.outcome)

    cited = set(candidate.supporting_citation_ids)
    available = {citation.doc_id for citation in agreeing}
    grounding = len(cited & available) / len(available) if available else 0.0
    if not available and cited:
        grounding = 0.0

    named = set(candidate.counterevidence_citation_ids)
    opposing_ids = {citation.doc_id for citation in opposing}
    completeness = len(named & opposing_ids) / len(opposing_ids) if opposing_ids else 1.0

    resolution = 1.0 if candidate.strongest_counterevidence and named else 0.0
    if not opposing_ids and candidate.strongest_counterevidence:
        # Nothing contradicts this outcome, and the candidate said so plainly.
        resolution = 1.0

    overreach = any(term in candidate.rationale.lower() for term in _OVERREACH_TERMS)
    actionability = 0.0 if overreach else 1.0

    # Plausibility is measured against the most likely outcome rather than in
    # absolute terms. Four priors that sum to one compress into a narrow band,
    # and an absolute reading left this dimension unable to separate the model's
    # clear favourite from an also-ran -- which made every branch pair look tied.
    best_prior = max(bundle.quantitative.distribution.values(), default=0.0)
    plausibility = candidate.model_prior / best_prior if best_prior > 0 else 0.0

    return {
        "qualitative_grounding": round(min(1.0, grounding), 6),
        "conflict_resolution": round(resolution, 6),
        "baseline_plausibility": round(min(1.0, plausibility), 6),
        "counterevidence_completeness": round(min(1.0, completeness), 6),
        "actionability_without_overreach": round(actionability, 6),
    }


def weighted_score(scores: dict[str, float]) -> float:
    """Return the rubric total for one candidate."""

    return round(sum(RUBRIC_WEIGHTS[name] * scores.get(name, 0.0) for name in RUBRIC_WEIGHTS), 6)


def evaluate(candidate: CandidateHypothesis, bundle: EvidenceBundle) -> CandidateHypothesis:
    """Return the candidate with its hard checks and rubric scores attached."""

    failures = hard_checks(candidate, bundle)
    scores = score_candidate(candidate, bundle)
    return candidate.model_copy(
        update={
            "hard_check_passed": not failures,
            "hard_check_failures": failures,
            "soft_scores": scores,
            # A hard-invalid branch scores zero, not merely low. Section 15.3
            # rejects it outright, and leaving it a positive score would let a
            # sufficiently fluent invalid branch outrank a valid one.
            "score": 0.0 if failures else weighted_score(scores),
        }
    )


def _rank(candidates: Sequence[CandidateHypothesis]) -> tuple[CandidateHypothesis, ...]:
    """Return candidates best first, with a stable tie-break on outcome name.

    The secondary key matters: two branches with identical scores must order the
    same way on every run, or a reported winner would depend on dictionary order.
    """

    return tuple(sorted(candidates, key=lambda item: (-item.score, item.outcome)))


def _consistency_vote(
    survivors: Sequence[CandidateHypothesis], bundle: EvidenceBundle
) -> CandidateHypothesis | None:
    """Run the one permitted order-permuted re-score (section 15.6).

    Section 15.4 asks for order randomisation to control critic position bias,
    and section 15.6 spends it here: re-score the tied branches in a different
    order and release a winner only if the gap opens past the tie band.

    Worth stating plainly rather than hiding: the deterministic critic is
    order-invariant, so with it this vote always reproduces the same scores and
    therefore always confirms the tie. It is not decorative -- it is the seam
    where a model-backed critic would change the answer, and the ablation
    reports how often it fires -- but with no provider configured, a tie here
    always becomes an abstention.
    """

    shuffled = list(survivors)
    random.Random(CONSISTENCY_VOTE_SEED).shuffle(shuffled)
    rescored = _rank([evaluate(candidate, bundle) for candidate in shuffled])
    if len(rescored) < 2:
        return rescored[0] if rescored else None
    if rescored[0].score - rescored[1].score > TIE_BAND:
        return rescored[0]
    return None


def _stress_child(candidate: CandidateHypothesis, bundle: EvidenceBundle) -> CandidateHypothesis:
    """Return the depth-two refinement of one survivor (section 15.5).

    The question the child answers is fixed: "what is the strongest verified
    reason this hypothesis could be wrong?" The answer is the highest-scoring
    verified item pointing the other way, named explicitly, so a branch that
    survives has already been made to confront its best counterargument.
    """

    opposing = _opposing_citations(bundle, candidate.outcome)
    strongest = max(opposing, key=lambda item: item.retrieval_score, default=None)
    if strongest is None:
        drivers = [
            driver for driver in bundle.quantitative.drivers if driver.direction == "opposes"
        ]
        detail = (
            f"the strongest verified reason this could be wrong is {drivers[0].feature}, "
            f"which opposes it at {drivers[0].value:g}"
            if drivers
            else "no verified evidence points the other way"
        )
        counterevidence_ids: tuple[str, ...] = candidate.counterevidence_citation_ids
        strongest_label = drivers[0].feature if drivers else "none"
    else:
        detail = (
            f"the strongest verified reason this could be wrong is {strongest.doc_id}, "
            f"a {strongest.source_type} pointing {strongest.signal}"
        )
        counterevidence_ids = tuple(
            dict.fromkeys((*candidate.counterevidence_citation_ids, strongest.doc_id))
        )
        strongest_label = strongest.doc_id

    return candidate.model_copy(
        update={
            "rationale": f"{candidate.rationale} Stress test: {detail}.",
            "counterevidence_citation_ids": counterevidence_ids,
            "strongest_counterevidence": strongest_label,
            "depth": MAX_TOT_DEPTH,
        }
    )


def search(candidates: Sequence[CandidateHypothesis], bundle: EvidenceBundle) -> ToTResult:
    """Run the bounded search over already-generated candidates.

    Args:
        candidates: One hypothesis per canonical outcome (section 15.2).
        bundle: The verified evidence every check replays against.

    Returns:
        The winner and every branch considered, or an abstention when the top
        two remain within the tie band after the one permitted vote.
    """

    depth_one = _rank([evaluate(candidate, bundle) for candidate in candidates])
    valid = tuple(candidate for candidate in depth_one if candidate.survived)
    pruned = tuple(candidate for candidate in depth_one if not candidate.survived)

    if not valid:
        return ToTResult(
            winner=None,
            branches=depth_one,
            pruned=pruned,
            abstained=True,
            abstain_reason="every candidate failed a hard check",
        )

    beam = valid[:TOT_BEAM_WIDTH]
    survivors = _rank([evaluate(_stress_child(candidate, bundle), bundle) for candidate in beam])
    branches = (*depth_one, *survivors)

    still_valid = tuple(candidate for candidate in survivors if candidate.survived)
    if not still_valid:
        return ToTResult(
            winner=None,
            branches=branches,
            survivors=survivors,
            pruned=(*pruned, *survivors),
            abstained=True,
            abstain_reason="every survivor failed its stress test",
        )

    leader = still_valid[0]
    runner_up = still_valid[1] if len(still_valid) > 1 else None

    if leader.score < MINIMUM_WINNING_SCORE:
        return ToTResult(
            winner=None,
            branches=branches,
            survivors=survivors,
            pruned=pruned,
            abstained=True,
            abstain_reason=(
                f"the best branch scored {leader.score:.2f}, below the "
                f"{MINIMUM_WINNING_SCORE:.2f} release bar"
            ),
        )

    if runner_up is not None and leader.score - runner_up.score <= TIE_BAND:
        voted = _consistency_vote(still_valid, bundle)
        if voted is None:
            return ToTResult(
                winner=None,
                branches=branches,
                survivors=survivors,
                pruned=pruned,
                tie_broken_by_vote=True,
                abstained=True,
                abstain_reason=(
                    f"{leader.outcome} and {runner_up.outcome} stayed within "
                    f"{TIE_BAND:.2f} after the consistency vote"
                ),
            )
        return ToTResult(
            winner=voted,
            branches=branches,
            survivors=survivors,
            pruned=pruned,
            tie_broken_by_vote=True,
        )

    return ToTResult(winner=leader, branches=branches, survivors=survivors, pruned=pruned)


__all__ = [
    "CONSISTENCY_VOTE_SEED",
    "MINIMUM_WINNING_SCORE",
    "RUBRIC_WEIGHTS",
    "TIE_BAND",
    "ToTResult",
    "evaluate",
    "hard_checks",
    "score_candidate",
    "search",
    "weighted_score",
]
