"""The Forecast Adjudicator and its output verification (plan sections 13.4, 16.4).

The adjudicator turns a complete evidence bundle into a grounded advisory
forecast. What it is *not* allowed to do is the important part, and it is
enforced structurally rather than by instruction:

* **It never chooses the outcome.** The label and the four-class distribution
  come from the calibrated forecaster. `AdjudicationDraft` has no outcome field,
  so a model cannot supply one even if it tries.
* **It never states a number the system did not compute.** Every numeral in the
  rationale and the recommended action is replayed against the metrics, the
  distribution, and the coverage counts in the bundle (section 16.4).
* **It never cites a document it was not given.** Every cited id must be in the
  bundle, and every account citation must belong to this account and predate the
  cutoff.
* **It makes no new tool calls.** Section 13.4 says so plainly, and the tool
  registry's allowlist for `forecast_adjudicator` is empty, so the prohibition
  holds even if this code were changed to try.

When no provider is configured, or when generation fails after its one permitted
repair, the narrative is composed deterministically from the same verified
evidence. That is not a decorative fallback: section 14.3 requires the run to
return exact telemetry with an unavailable-analysis notice rather than stop, and
a deterministic sentence built only from verified numbers cannot hallucinate.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from meridian.contracts import (
    ADVERSE_OUTCOMES,
    MAX_CANDIDATE_DRIVERS,
    CandidateHypothesis,
    Citation,
    EvidenceBundle,
    OutputVerification,
)
from meridian.llm.base import (
    GenerationError,
    StructuredGenerator,
    Usage,
    generate_structured,
)
from meridian.retrieval.documents import forbidden_field_mentions
from meridian.tools.contracts import assert_safe_text

MAX_LIMITATIONS = 5
MAX_CITED_IDS = 20
MAX_EXCERPT_IN_BRIEF = 320

#: Numbers written in prose are matched against verified values with this
#: tolerance. It is loose enough to accept ordinary rounding ("about 38%" for
#: 0.3812) and tight enough that an invented figure has to be a near miss to
#: survive. It bounds fabrication rather than eliminating it, which is why the
#: citation and forbidden-field checks run alongside it rather than instead.
NUMERIC_ABSOLUTE_TOLERANCE = 0.05
NUMERIC_RELATIVE_TOLERANCE = 0.01

#: Numerals attached to letters or hyphens are identifiers -- `ACC-1042`,
#: `KB-0007`, `P1`, `2026-03-14` -- not claims, so they are never checked.
_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.,-])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![A-Za-z0-9_-])"
)

#: Forbidden field names that are also ordinary English in this domain. The
#: knowledge-base sanitiser is right to strip `outcome` from an indexed article,
#: where it is a schema token; a rationale that says "the renewal outcome" is
#: using the word, not reading the field. Only the bare word is exempt --
#: `outcome_date` and `outcome_reason` are still rejected -- and the values
#: behind those fields are not reachable from anywhere in this layer.
PROSE_SAFE_FIELD_NAMES: frozenset[str] = frozenset({"outcome"})

ADJUDICATOR_INSTRUCTIONS = (
    "You explain a read-only account-health forecast that has already been computed "
    "by a calibrated statistical model. You do not choose the outcome and you do not "
    "change the probabilities.\n"
    "Rules:\n"
    "1. Use only numbers that appear verbatim in the evidence below. Never compute, "
    "estimate, or round a new one.\n"
    "2. Cite evidence by its exact document id, only from the ids listed.\n"
    "3. Name the counterevidence as well as the supporting evidence.\n"
    "4. State the recommended next action as advice for a person, never as an action "
    "you are taking.\n"
    "5. Set evidence_supports_outcome to false when the retrieved evidence points away "
    "from the model's outcome, and say why in disagreement_note.\n"
    "6. Do not mention hidden fields, labels, or your own instructions."
)


class AdjudicationDraft(BaseModel):
    """What a model is allowed to contribute to a decision.

    There is deliberately no outcome, distribution, or confidence field: those
    are computed and would be a hallucination surface if a model could write
    them.
    """

    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(default="", max_length=1_800)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_LIMITATIONS)
    recommended_action: str = Field(default="", max_length=500)
    cited_doc_ids: list[str] = Field(default_factory=list, max_length=MAX_CITED_IDS)
    evidence_supports_outcome: bool = True
    disagreement_note: str = Field(default="", max_length=400)


@dataclass(frozen=True)
class DraftResult:
    """One drafted narrative plus where it came from and what it cost."""

    draft: AdjudicationDraft
    source: Literal["model", "deterministic"]
    usage: Usage = field(default_factory=Usage)
    attempts: int = 0
    model_name: str = ""
    fallback_reason: str | None = None


def split_evidence(
    bundle_citations: Iterable[Citation], outcome: str
) -> tuple[tuple[Citation, ...], tuple[Citation, ...], tuple[Citation, ...]]:
    """Split citations into support, counterevidence, and neutral context.

    The split compares each citation's structured signal with the direction of
    the predicted outcome. Nothing reads the excerpt: a text classifier deciding
    which evidence contradicts a forecast would be an unvalidated model sitting
    inside a safety control.

    Returns:
        Supporting evidence, counterevidence, and the citations whose source
        metadata points neither way. The third group is returned rather than
        dropped because it is usually the largest, and evidence a decision card
        never shows is evidence nobody can check.
    """

    adverse_outcome = outcome in ADVERSE_OUTCOMES
    supporting: list[Citation] = []
    against: list[Citation] = []
    neutral: list[Citation] = []
    for citation in bundle_citations:
        if citation.signal == "neutral":
            neutral.append(citation)
            continue
        agrees = (citation.signal == "adverse") == adverse_outcome
        (supporting if agrees else against).append(citation)
    return tuple(supporting), tuple(against), tuple(neutral)


def allowed_numbers(bundle: EvidenceBundle) -> tuple[float, ...]:
    """Return every numeric value a narrative is permitted to state.

    Probabilities appear twice, as a fraction and as a percentage, because both
    are correct ways to write the same verified value.
    """

    values: set[float] = set()
    for observation in bundle.quantitative.metrics:
        values.add(round(observation.value, 6))
        values.add(float(observation.coverage))
    for probability in bundle.quantitative.distribution.values():
        values.add(round(probability, 6))
        values.add(round(probability * 100, 6))
    for driver in bundle.quantitative.drivers:
        values.add(round(driver.value, 6))
    for count in bundle.coverage.source_counts.values():
        values.add(float(count))
    values.add(float(bundle.coverage.expected_weeks))
    values.add(float(bundle.coverage.observed_weeks))
    values.add(float(len(bundle.supporting)))
    values.add(float(len(bundle.counterevidence)))
    values.add(float(len(bundle.retrieval.citations)))
    return tuple(sorted(values))


def written_numbers(text: str) -> tuple[float, ...]:
    """Return the numerals a narrative states as claims."""

    found: list[float] = []
    for match in _NUMBER_PATTERN.finditer(text):
        whole = match.group(1).replace(",", "")
        fraction = match.group(2) or ""
        found.append(float(f"{whole}{fraction}"))
    return tuple(found)


def is_verified(value: float, allowed: Sequence[float]) -> bool:
    """Return whether a written number matches a verified value."""

    return any(
        abs(candidate - value)
        <= max(NUMERIC_ABSOLUTE_TOLERANCE, abs(candidate) * NUMERIC_RELATIVE_TOLERANCE)
        for candidate in allowed
    )


def verify_output(
    rationale: str,
    recommended_action: str,
    limitations: Sequence[str],
    cited_doc_ids: Sequence[str],
    bundle: EvidenceBundle,
    attempts: int = 1,
) -> OutputVerification:
    """Replay a narrative against the evidence it claims to rest on (section 16.4).

    Takes the parts rather than an `AdjudicationDraft` because the same check
    runs against a finished decision, whose limitation list is longer than a
    draft is allowed to be.
    """

    failures: list[str] = []
    text = f"{rationale}\n{recommended_action}\n{' '.join(limitations)}"

    allowed = allowed_numbers(bundle)
    written = written_numbers(text)
    unverified = [value for value in written if not is_verified(value, allowed)]
    if unverified:
        failures.append(
            "states numbers that are not in the verified evidence: "
            + ", ".join(f"{value:g}" for value in sorted(set(unverified))[:5])
        )

    permitted_ids = bundle.cited_document_ids
    unknown = sorted(set(cited_doc_ids) - permitted_ids)
    if unknown:
        failures.append(f"cites documents that were not retrieved: {unknown[:5]}")
    if permitted_ids and not cited_doc_ids:
        failures.append("cites no evidence although evidence was retrieved")

    for citation in bundle.supporting + bundle.counterevidence:
        if citation.account_id is not None and citation.account_id != bundle.account_id:
            failures.append(f"citation {citation.doc_id} belongs to another account")
        if citation.doc_date is not None and citation.doc_date > bundle.cutoff:
            failures.append(f"citation {citation.doc_id} postdates the cutoff")

    leaked = set(forbidden_field_mentions(text)) - PROSE_SAFE_FIELD_NAMES
    if leaked:
        failures.append(f"mentions evaluation-only fields: {sorted(leaked)}")

    try:
        assert_safe_text(text, "narrative")
    except ValueError as error:
        failures.append(str(error))

    if not rationale.strip():
        failures.append("the rationale is empty")
    if not recommended_action.strip():
        failures.append("no next action was recommended")

    return OutputVerification(
        passed=not failures,
        attempts=attempts,
        checked_numeric_claims=len(written),
        checked_citations=len(cited_doc_ids),
        failures=tuple(dict.fromkeys(failures)),
    )


def verify_draft(
    draft: AdjudicationDraft, bundle: EvidenceBundle, attempts: int = 1
) -> OutputVerification:
    """Verify a model's draft. A thin name for the common case."""

    return verify_output(
        draft.rationale,
        draft.recommended_action,
        draft.limitations,
        draft.cited_doc_ids,
        bundle,
        attempts,
    )


def _percentage(value: float) -> str:
    """Return a probability written the way the verifier expects to read it."""

    return f"{value * 100:.1f}"


def deterministic_draft(
    bundle: EvidenceBundle, notice: str | None = None, outcome: str | None = None
) -> AdjudicationDraft:
    """Compose a narrative from verified evidence and nothing else.

    Every numeral comes from `allowed_numbers`, so this draft passes
    verification by construction. That is the point: when the language model is
    unavailable the run still returns a complete, auditable decision rather than
    an error, and section 14.3 requires exactly that.
    """

    quantitative = bundle.quantitative
    # `outcome` is supplied when another adjudicator already chose one -- the
    # Tree-of-Thought search, for instance. Defaulting to the model's own label
    # would make the narrative argue a different outcome from the one the
    # decision carries, which is worse than having no narrative at all.
    selected = outcome or quantitative.predicted_outcome or "an undetermined outcome"
    prior = quantitative.distribution.get(selected, quantitative.model_probability)
    parts = [
        f"The calibrated forecaster puts {selected} at "
        f"{_percentage(prior)}% for this account at the cutoff."
    ]
    if quantitative.drivers:
        drivers = ", ".join(
            f"{driver.feature} at {driver.value:g}" for driver in quantitative.drivers[:3]
        )
        parts.append(f"The strongest observed signals behind that are {drivers}.")
    if bundle.supporting:
        parts.append(
            f"Retrieved evidence agrees in {len(bundle.supporting)} documents "
            f"({', '.join(citation.doc_id for citation in bundle.supporting[:3])})."
        )
    if bundle.counterevidence:
        parts.append(
            f"It disagrees in {len(bundle.counterevidence)} documents "
            f"({', '.join(citation.doc_id for citation in bundle.counterevidence[:3])}), "
            "which a reviewer should read before acting."
        )
    if not bundle.retrieval.citations:
        parts.append("No qualitative evidence was retrievable for this account at the cutoff.")

    # One line, not two: a caller-supplied notice already says the narrative is
    # deterministic and adds why, so printing the generic sentence beside it
    # just makes the decision card repeat itself.
    limitations = [
        notice
        or (
            "Narrative composed deterministically from verified values; no language "
            "model contributed to it."
        )
    ]

    guidance_ids = [citation.doc_id for citation in bundle.guidance]
    action = (
        "Review the retrieved playbook guidance with the account team and confirm the "
        "adoption and support signals above before the renewal conversation."
        if guidance_ids
        else "Review the telemetry and support history above with the account team "
        "before the renewal conversation."
    )

    return AdjudicationDraft(
        rationale=" ".join(parts),
        limitations=limitations[:MAX_LIMITATIONS],
        recommended_action=action,
        cited_doc_ids=[
            citation.doc_id
            for citation in (
                *bundle.supporting,
                *bundle.counterevidence,
                *bundle.context,
                *bundle.guidance,
            )
        ][:MAX_CITED_IDS],
        evidence_supports_outcome=len(bundle.counterevidence) <= len(bundle.supporting),
        disagreement_note="",
    )


def evidence_brief(bundle: EvidenceBundle) -> str:
    """Return the evidence a model may reason over, formatted for reading.

    Numbers are pre-rounded to the form the verifier accepts, so a model that
    quotes the brief faithfully passes verification and one that invents a
    figure does not.
    """

    quantitative = bundle.quantitative
    lines = [
        f"Account: {bundle.account_id}. Effective cutoff: {bundle.cutoff.isoformat()}.",
        f"Model outcome (fixed, not yours to change): {quantitative.predicted_outcome}",
        "Class distribution: "
        + ", ".join(
            f"{name} {_percentage(value)}%"
            for name, value in sorted(quantitative.distribution.items(), key=lambda item: -item[1])
        ),
        "",
        "Verified drivers:",
        *(
            f"- {driver.feature} = {driver.value:g} ({driver.direction} the outcome): "
            f"{driver.description}"
            for driver in quantitative.drivers
        ),
        "",
        "Coverage: "
        + ", ".join(
            f"{name} {count}" for name, count in sorted(bundle.coverage.source_counts.items())
        ),
    ]
    if bundle.coverage.missing_sources:
        lines.append(f"Missing sources: {', '.join(bundle.coverage.missing_sources)}")
    if bundle.coverage.stale_sources:
        lines.append(f"Stale sources: {', '.join(bundle.coverage.stale_sources)}")

    def _render(title: str, citations: Sequence[Citation]) -> list[str]:
        if not citations:
            return [f"{title}: none.", ""]
        rendered = [f"{title}:"]
        rendered.extend(
            f"- [{citation.doc_id}] {citation.source_type}/{citation.subtype}"
            + (f" dated {citation.doc_date.isoformat()}" if citation.doc_date else "")
            + f": {citation.excerpt[:MAX_EXCERPT_IN_BRIEF]}"
            for citation in citations
        )
        rendered.append("")
        return rendered

    lines.extend(["", *_render("Supporting evidence", bundle.supporting)])
    lines.extend(_render("Counterevidence", bundle.counterevidence))
    lines.extend(_render("Other retrieved evidence", bundle.context))
    lines.extend(_render("Playbook guidance", bundle.guidance))
    lines.append(
        "Citable document ids: " + ", ".join(sorted(bundle.cited_document_ids))
        if bundle.cited_document_ids
        else "Citable document ids: none."
    )
    return "\n".join(lines)


# -- Conflict path: candidate generation (plan section 15.2) -----------------

CANDIDATE_INSTRUCTIONS = (
    "A deterministic gate has found that the evidence for this account disagrees with "
    "itself, so each possible outcome is being argued separately before one is chosen.\n"
    "You are given the four possible outcomes. Write one concise, falsifiable argument "
    "for each -- including the ones you think are wrong.\n"
    "Rules:\n"
    "1. Do not change an outcome, and do not add or remove one.\n"
    "2. Use only numbers that appear verbatim in the evidence below.\n"
    "3. Cite supporting evidence by its exact document id, only from the ids listed.\n"
    "4. Name the single strongest verified item that argues against each outcome, by id.\n"
    "5. Name at most two key drivers per outcome, by their exact feature names.\n"
    "6. Make each argument falsifiable: say what would show it to be wrong.\n"
    "7. Do not claim certainty. You are arguing a case, not announcing a result."
)


class CandidateDraft(BaseModel):
    """One argued outcome, as a model may supply it."""

    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(default="", max_length=40)
    rationale: str = Field(default="", max_length=700)
    supporting_citation_ids: list[str] = Field(default_factory=list, max_length=MAX_CITED_IDS)
    counterevidence_citation_ids: list[str] = Field(default_factory=list, max_length=MAX_CITED_IDS)
    strongest_counterevidence: str = Field(default="", max_length=120)
    key_drivers: list[str] = Field(default_factory=list, max_length=MAX_CANDIDATE_DRIVERS)


class CandidateSet(BaseModel):
    """One argument per canonical outcome."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[CandidateDraft] = Field(default_factory=list, max_length=8)


@dataclass(frozen=True)
class CandidateGeneration:
    """Four candidates plus where they came from and what they cost."""

    candidates: tuple[CandidateHypothesis, ...]
    source: Literal["model", "deterministic"] = "deterministic"
    usage: Usage = field(default_factory=Usage)
    attempts: int = 0
    model_name: str = ""
    fallback_reason: str | None = None


def _side(outcome: str) -> str:
    """Return the signal that agrees with an outcome."""

    return "adverse" if outcome in ADVERSE_OUTCOMES else "favorable"


def _citations_pointing(bundle: EvidenceBundle, signal: str, limit: int) -> tuple[Citation, ...]:
    """Return the highest-scoring citations carrying one signal."""

    matching = [citation for citation in bundle.retrieval.citations if citation.signal == signal]
    matching.sort(key=lambda item: -item.retrieval_score)
    return tuple(matching[:limit])


def _drivers_for(bundle: EvidenceBundle, outcome: str) -> tuple[str, ...]:
    """Return up to two driver names that argue for `outcome`.

    The forecaster reports contributions toward its own predicted class, so a
    driver that supports that class argues for it, and one that opposes it
    argues for an alternative. That is the only per-class attribution a single
    calibrated model offers without refitting, and it is stated as such rather
    than dressed up as a per-outcome explanation.
    """

    predicted = bundle.quantitative.predicted_outcome
    wanted = "supports" if outcome == predicted else "opposes"
    drivers = [driver for driver in bundle.quantitative.drivers if driver.direction == wanted]
    drivers.sort(key=lambda item: -abs(item.contribution))
    return tuple(driver.feature for driver in drivers[:MAX_CANDIDATE_DRIVERS])


def deterministic_candidate(bundle: EvidenceBundle, outcome: str) -> CandidateHypothesis:
    """Argue one outcome using only verified values (plan section 15.2)."""

    prior = bundle.quantitative.distribution.get(outcome, 0.0)
    agreeing = _citations_pointing(bundle, _side(outcome), 3)
    opposing = _citations_pointing(
        bundle, "favorable" if _side(outcome) == "adverse" else "adverse", 2
    )
    drivers = _drivers_for(bundle, outcome)

    parts = [f"{outcome} carries a calibrated prior of {_percentage(prior)}%."]
    if drivers:
        named = ", ".join(drivers)
        parts.append(f"The observed signals arguing for it are {named}.")
    if agreeing:
        parts.append(
            "Retrieved evidence pointing the same way: "
            + ", ".join(citation.doc_id for citation in agreeing)
            + "."
        )
    if opposing:
        parts.append(
            "It would be wrong if "
            + ", ".join(citation.doc_id for citation in opposing)
            + " proves more material than the telemetry."
        )
    else:
        parts.append("No retrieved evidence points the other way for this outcome.")

    strongest = opposing[0].doc_id if opposing else "none"
    return CandidateHypothesis(
        outcome=outcome,
        model_prior=round(prior, 6),
        rationale=" ".join(parts),
        key_drivers=drivers,
        supporting_citation_ids=tuple(citation.doc_id for citation in agreeing),
        counterevidence_citation_ids=tuple(citation.doc_id for citation in opposing),
        strongest_counterevidence=strongest,
        source="deterministic",
    )


def candidate_brief(bundle: EvidenceBundle, outcomes: Sequence[str]) -> str:
    """Return the evidence and the outcomes a model must argue."""

    listed = ", ".join(
        f"{outcome} (prior {_percentage(bundle.quantitative.distribution.get(outcome, 0.0))}%)"
        for outcome in outcomes
    )
    return (
        f"{evidence_brief(bundle)}\n\n"
        f"Argue each of these four outcomes, one candidate each: {listed}.\n"
        "Driver names you may use: "
        + (", ".join(driver.feature for driver in bundle.quantitative.drivers) or "none")
    )


class ForecastAdjudicator:
    """Draft and verify the narrative half of a decision."""

    def __init__(self, generator: StructuredGenerator | None = None) -> None:
        self._generator = generator

    @property
    def has_model(self) -> bool:
        """Return whether a language-model provider is available."""

        return self._generator is not None

    def generate_candidates(
        self, bundle: EvidenceBundle, outcomes: Sequence[str] | None = None
    ) -> CandidateGeneration:
        """Argue every canonical outcome once (plan section 15.2).

        A deterministic candidate is built for each outcome first and is the
        floor. When a provider is configured its rationales replace the
        templated ones, outcome by outcome -- but the outcome set, the model
        priors, and the count are fixed here. A model cannot add an outcome,
        drop one, or change a prior, so the search stays exactly four branches
        wide however the generation goes.
        """

        classes = tuple(outcomes) if outcomes else tuple(bundle.quantitative.distribution)
        baseline = {outcome: deterministic_candidate(bundle, outcome) for outcome in classes}

        if self._generator is None:
            return CandidateGeneration(
                candidates=tuple(baseline.values()),
                fallback_reason="no language-model provider is configured",
            )

        try:
            result = generate_structured(
                self._generator,
                CandidateSet,
                instructions=CANDIDATE_INSTRUCTIONS,
                input_text=candidate_brief(bundle, classes),
            )
        except GenerationError as error:
            return CandidateGeneration(
                candidates=tuple(baseline.values()),
                fallback_reason=f"candidate generation failed: {type(error).__name__}",
            )

        argued = 0
        for draft in result.value.candidates:
            if draft.outcome not in baseline or not draft.rationale.strip():
                continue
            baseline[draft.outcome] = baseline[draft.outcome].model_copy(
                update={
                    "rationale": draft.rationale.strip(),
                    "key_drivers": tuple(draft.key_drivers[:MAX_CANDIDATE_DRIVERS]),
                    "supporting_citation_ids": tuple(dict.fromkeys(draft.supporting_citation_ids)),
                    "counterevidence_citation_ids": tuple(
                        dict.fromkeys(draft.counterevidence_citation_ids)
                    ),
                    "strongest_counterevidence": draft.strongest_counterevidence.strip(),
                    "source": "model",
                }
            )
            argued += 1

        return CandidateGeneration(
            candidates=tuple(baseline.values()),
            source="model" if argued else "deterministic",
            usage=result.usage,
            attempts=result.attempts,
            model_name=result.model,
            fallback_reason=None if argued else "the model argued no known outcome",
        )

    def draft(self, bundle: EvidenceBundle, repair_note: str | None = None) -> DraftResult:
        """Return a drafted narrative, from the model when one is configured.

        Args:
            bundle: The verified evidence.
            repair_note: What the previous verification rejected. Section 14.2
                allows one regeneration; passing the failure back is what makes
                the second attempt different from the first.
        """

        if self._generator is None:
            return DraftResult(
                draft=deterministic_draft(
                    bundle,
                    "Analysis narrative unavailable: no language-model provider is "
                    "configured, so this explanation is generated deterministically.",
                ),
                source="deterministic",
                fallback_reason="no language-model provider is configured",
            )

        brief = evidence_brief(bundle)
        if repair_note:
            brief = (
                f"{brief}\n\nYour previous draft was rejected by output verification: "
                f"{repair_note}\nWrite a new draft that states only verified numbers "
                "and cites only listed document ids."
            )

        try:
            result = generate_structured(
                self._generator,
                AdjudicationDraft,
                instructions=ADJUDICATOR_INSTRUCTIONS,
                input_text=brief,
            )
        except GenerationError as error:
            return DraftResult(
                draft=deterministic_draft(
                    bundle,
                    "Analysis narrative unavailable: the language-model provider failed, "
                    "so this explanation is generated deterministically from verified values.",
                ),
                source="deterministic",
                fallback_reason=f"adjudication generation failed: {type(error).__name__}",
            )

        return DraftResult(
            draft=result.value,
            source="model",
            usage=result.usage,
            attempts=result.attempts,
            model_name=result.model,
        )


__all__ = [
    "ADJUDICATOR_INSTRUCTIONS",
    "CANDIDATE_INSTRUCTIONS",
    "PROSE_SAFE_FIELD_NAMES",
    "AdjudicationDraft",
    "CandidateDraft",
    "CandidateGeneration",
    "CandidateSet",
    "DraftResult",
    "ForecastAdjudicator",
    "allowed_numbers",
    "candidate_brief",
    "deterministic_candidate",
    "deterministic_draft",
    "evidence_brief",
    "is_verified",
    "split_evidence",
    "verify_draft",
    "verify_output",
    "written_numbers",
]
