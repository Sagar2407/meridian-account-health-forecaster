"""The four agents, offline (plan section 13).

Every test here runs without a provider, without an index, and without the
dataset, using the deterministic fakes ADR 0004 promised. What is under test is
each agent's contract with the rest of the graph: what the Orchestrator is
allowed to plan, how the Retriever merges a second round into a first, and --
the one that carries the most weight -- exactly which claims output verification
rejects.
"""

from datetime import date
from typing import cast

import pytest

from meridian.agents.evidence_retriever import SUB_GOAL_SOURCES, merge_evidence, to_citation
from meridian.agents.forecast_adjudicator import (
    AdjudicationDraft,
    ForecastAdjudicator,
    allowed_numbers,
    deterministic_draft,
    evidence_brief,
    split_evidence,
    verify_output,
)
from meridian.agents.orchestrator import DEFAULT_QUERIES, Orchestrator, deterministic_plan
from meridian.contracts import (
    MAX_SUB_GOALS,
    MIN_SUB_GOALS,
    AssessmentRequest,
    Citation,
    CoverageReport,
    Driver,
    EvidenceBundle,
    MetricObservation,
    QuantitativeEvidence,
    RetrievalEvidence,
    RetrievalObservation,
    SubGoalKind,
)
from meridian.data.repository import AccountProfile
from meridian.llm.base import GenerationError
from meridian.llm.fake import ScriptedGenerator
from meridian.tools.contracts import EvidenceCitation, evidence_signal
from meridian.tools.registry import ToolRegistry

CUTOFF = date(2026, 3, 1)


def _profile(**overrides: object) -> AccountProfile:
    defaults: dict[str, object] = {
        "account_id": "ACC-1042",
        "account_name": "Example Holdings",
        "segment": "Mid-Market",
        "industry": "Software",
        "region": "AMER",
        "country": "United States",
        "employees": 900,
        "licensed_seats": 250,
        "acv_usd": 180_000.0,
        "contract_term_months": 12,
        "contract_start_date": date(2025, 6, 1),
        "renewal_date": date(2026, 6, 1),
        "forecast_as_of_date": date(2026, 3, 1),
        "products_owned": ("Core",),
        "num_products": 1,
        "primary_product": "Core",
        "csm_name": "A. Person",
        "exec_sponsor_name": "B. Person",
        "sponsor_status": "stable",
        "onboarding_completed": True,
    }
    return AccountProfile.model_validate({**defaults, **overrides})


def _citation(doc_id: str, signal: str = "neutral", source: str = "csm_note") -> Citation:
    return Citation(
        doc_id=doc_id,
        parent_id=doc_id,
        source_type=source,
        subtype="Monthly Touchpoint",
        account_id="ACC-1042",
        doc_date=date(2026, 1, 10),
        excerpt="Usage has been steady since the last review.",
        retrieval_score=0.72,
        signal=signal,
    )


def _bundle(**overrides: object) -> EvidenceBundle:
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
        distribution={"Churned": 0.6, "Contracted": 0.2, "Renewed": 0.15, "Expanded": 0.05},
        predicted_outcome="Churned",
        model_probability=0.6,
        drivers=(
            Driver(
                feature="adoption_level_last_q",
                value=42.5,
                contribution=-0.31,
                direction="opposes",
                description="Mean weekly adoption index.",
            ),
        ),
        coverage=CoverageReport(
            expected_weeks=13, observed_weeks=13, source_counts={"tickets": 7, "notes": 4}
        ),
    )
    defaults: dict[str, object] = {
        "account_id": "ACC-1042",
        "cutoff": CUTOFF,
        "quantitative": quantitative,
        "retrieval": RetrievalEvidence(account_id="ACC-1042", cutoff=CUTOFF),
        "coverage": quantitative.coverage,
        "supporting": (_citation("TCK-1", "adverse", "support_ticket"),),
        "counterevidence": (),
        "context": (_citation("NOTE-1"),),
        "guidance": (
            Citation(
                doc_id="KB-012",
                parent_id="KB-012",
                source_type="knowledge_base",
                subtype="playbook",
                account_id=None,
                doc_date=None,
                excerpt="Escalate to the sponsor early.",
                retrieval_score=0.6,
            ),
        ),
    }
    return EvidenceBundle(**{**defaults, **overrides})


# -- Orchestrator ------------------------------------------------------------


def test_the_deterministic_plan_always_covers_adoption_support_and_guidance() -> None:
    """A decision card with no adoption or support evidence cannot explain itself."""

    plan = deterministic_plan(_profile())
    kinds = [sub_goal.kind for sub_goal in plan]
    assert MIN_SUB_GOALS <= len(plan) <= MAX_SUB_GOALS
    assert kinds[:2] == ["adoption", "support"]
    assert kinds[-1] == "playbook_guidance"


def test_the_third_sub_goal_follows_the_profile() -> None:
    """A lost sponsor or unfinished onboarding is a relationship question."""

    assert "relationship" in [s.kind for s in deterministic_plan(_profile(sponsor_status="lost"))]
    assert "relationship" in [
        s.kind for s in deterministic_plan(_profile(onboarding_completed=False))
    ]
    assert "external_context" in [s.kind for s in deterministic_plan(_profile())]


def test_a_model_plan_is_used_and_guidance_is_appended_regardless() -> None:
    """Section 13.4 needs a knowledge-grounded action, so guidance is not optional."""

    reply = (
        '{"sub_goals": [{"kind": "support", "query": "escalations and unresolved tickets", '
        '"rationale": "ticket volume rose"}], "focus": "renewal save play"}'
    )
    result = Orchestrator(_registry_stub(), ScriptedGenerator([reply])).plan(
        AssessmentRequest(account_id="ACC-1042", question="Why is this account at risk?"),
        _profile(),
    )
    assert result.source == "model"
    assert [s.kind for s in result.plan] == ["support", "playbook_guidance"]
    assert result.plan[0].query == "escalations and unresolved tickets"
    assert result.usage.total_tokens > 0


@pytest.mark.parametrize(
    "reply",
    [
        '{"sub_goals": [{"kind": "adoption", "query": "x"}], "focus": ""}',
        '{"sub_goals": [{"kind": "adoption", "query": "usage `whoami`"}], "focus": ""}',
    ],
)
def test_an_unusable_model_query_is_replaced_not_sanitised(reply: str) -> None:
    """A too-short or hostile query is swapped for the default, so the sub-goal survives."""

    result = Orchestrator(_registry_stub(), ScriptedGenerator([reply])).plan(
        AssessmentRequest(account_id="ACC-1042", question="Assess renewal risk"), _profile()
    )
    assert result.plan[0].query == DEFAULT_QUERIES["adoption"]


def test_a_model_cannot_plan_the_same_sub_goal_twice() -> None:
    """Two searches for one question spend the budget without adding evidence."""

    reply = (
        '{"sub_goals": [{"kind": "adoption", "query": "adoption trend and usage"}, '
        '{"kind": "adoption", "query": "adoption again please"}], "focus": ""}'
    )
    result = Orchestrator(_registry_stub(), ScriptedGenerator([reply])).plan(
        AssessmentRequest(account_id="ACC-1042", question="Assess renewal risk"), _profile()
    )
    assert [s.kind for s in result.plan] == ["adoption", "playbook_guidance"]


def test_a_model_that_plans_only_guidance_falls_back() -> None:
    """Guidance alone is not an assessment of this account."""

    reply = '{"sub_goals": [{"kind": "playbook_guidance", "query": "playbooks"}], "focus": ""}'
    result = Orchestrator(_registry_stub(), ScriptedGenerator([reply])).plan(
        AssessmentRequest(account_id="ACC-1042", question="Assess renewal risk"), _profile()
    )
    assert result.source == "deterministic"
    assert result.fallback_reason == "the planner selected no usable sub-goal"


def test_a_provider_failure_still_produces_a_plan() -> None:
    """A planner that can fail closed is worth more than one that stops the run."""

    failing = ScriptedGenerator([GenerationError("provider down")])
    result = Orchestrator(_registry_stub(), failing).plan(
        AssessmentRequest(account_id="ACC-1042", question="Assess renewal risk"), _profile()
    )
    assert result.source == "deterministic"
    assert result.fallback_reason is not None
    assert "generation failed" in result.fallback_reason


def test_with_no_provider_the_plan_is_deterministic_and_says_so() -> None:
    """Every phase through this one runs without credentials."""

    result = Orchestrator(_registry_stub()).plan(
        AssessmentRequest(account_id="ACC-1042", question="Assess renewal risk"), _profile()
    )
    assert result.source == "deterministic"
    assert result.fallback_reason == "no language-model provider is configured"
    assert result.usage.total_tokens == 0


def _registry_stub() -> ToolRegistry:
    """Return a placeholder registry; the planner tests never reach a tool.

    `Orchestrator.plan` reads the profile and priors it is handed and calls no
    tool, so a stand-in is honest here: a real registry would need a dataset
    these tests deliberately do not load.
    """

    return cast("ToolRegistry", object())


# -- Evidence Retriever ------------------------------------------------------


def test_every_sub_goal_maps_to_source_families_it_can_be_answered_from() -> None:
    """Restricting the search is a safety control, not only a relevance one."""

    for kind, families in SUB_GOAL_SOURCES.items():
        if kind == "playbook_guidance":
            assert families == ()
        else:
            assert families, f"{kind} has no source families"


def test_a_transported_citation_keeps_its_account_and_signal() -> None:
    """The tool envelope proves ownership; the citation has to carry it forward."""

    transported = EvidenceCitation(
        doc_id="TCK-9",
        source_type="support_ticket",
        subtype="Escalation",
        doc_date=date(2026, 2, 2),
        score=0.81,
        excerpt="Escalated to engineering.",
        signal="adverse",
    )
    citation = to_citation(transported, "ACC-1042", "support")
    assert citation.account_id == "ACC-1042"
    assert citation.parent_id == citation.doc_id == "TCK-9"
    assert citation.signal == "adverse"
    assert citation.sub_goal == "support"


def test_a_retry_replaces_its_own_sub_goal_and_leaves_the_others_alone() -> None:
    """Concatenating would double-count the evidence the first round already found."""

    first = RetrievalEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        observations=(
            RetrievalObservation(sub_goal="adoption", query="a", citations=(_citation("NOTE-1"),)),
            RetrievalObservation(sub_goal="support", query="b", insufficient_evidence=True),
        ),
        guidance=(),
    )
    retry = RetrievalEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        observations=(
            RetrievalObservation(
                sub_goal="support",
                query="b rewritten",
                citations=(_citation("TCK-2", "adverse", "support_ticket"),),
                retry_count=1,
            ),
        ),
    )
    merged = merge_evidence(first, retry)
    assert [item.sub_goal for item in merged.observations] == ["adoption", "support"]
    assert merged.covered_sub_goals == ("adoption", "support")
    assert len(merged.citations) == 2


def test_an_unavailable_retry_leaves_the_first_round_intact() -> None:
    """Losing verified evidence because a second search failed would be worse than the gap."""

    first = RetrievalEvidence(
        account_id="ACC-1042",
        cutoff=CUTOFF,
        observations=(
            RetrievalObservation(sub_goal="adoption", query="a", citations=(_citation("N"),)),
        ),
    )
    unavailable = RetrievalEvidence(
        account_id="ACC-1042", cutoff=CUTOFF, available=False, unavailable_reason="no index"
    )
    assert merge_evidence(first, unavailable) is first


# -- Evidence signal ---------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "subtype", "severity", "expected"),
    [
        ("external_event", "Layoffs / restructuring", "adverse", "adverse"),
        ("external_event", "Earnings beat", "favorable", "favorable"),
        ("external_event", "Partnership announcement", "neutral", "neutral"),
        ("support_ticket", "Escalation", "P3", "adverse"),
        ("support_ticket", "How-to / Usage", "P1", "adverse"),
        ("support_ticket", "How-to / Usage", "P4", "neutral"),
        ("csm_note", "Escalation / Save Play", "", "adverse"),
        ("csm_note", "Expansion Discussion", "", "favorable"),
        ("csm_note", "Monthly Touchpoint", "", "neutral"),
        ("knowledge_base", "playbook", None, "neutral"),
    ],
)
def test_the_evidence_signal_comes_from_metadata_alone(
    source: str, subtype: str, severity: str | None, expected: str
) -> None:
    """No text classifier sits inside the split between support and counterevidence."""

    assert evidence_signal(source, subtype, severity) == expected


def test_evidence_is_split_three_ways_and_nothing_is_discarded() -> None:
    """Neutral evidence is most of what retrieval returns."""

    citations = (
        _citation("A", "adverse"),
        _citation("B", "favorable"),
        _citation("C"),
    )
    supporting, against, neutral = split_evidence(citations, "Churned")
    assert [c.doc_id for c in supporting] == ["A"]
    assert [c.doc_id for c in against] == ["B"]
    assert [c.doc_id for c in neutral] == ["C"]

    supporting, against, _ = split_evidence(citations, "Renewed")
    assert [c.doc_id for c in supporting] == ["B"]
    assert [c.doc_id for c in against] == ["A"]


# -- Forecast Adjudicator and output verification ----------------------------


def test_a_model_cannot_supply_the_outcome_or_the_distribution() -> None:
    """Section 13.4: the label comes from the calibrated forecaster, never the narrative."""

    for forbidden in ("outcome", "distribution", "confidence", "probability"):
        assert forbidden not in AdjudicationDraft.model_fields


def test_the_deterministic_narrative_passes_its_own_verification() -> None:
    """The fallback has to be usable, so it states only verified values."""

    bundle = _bundle()
    draft = deterministic_draft(bundle)
    verification = verify_output(
        draft.rationale, draft.recommended_action, draft.limitations, draft.cited_doc_ids, bundle
    )
    assert verification.passed, verification.failures
    assert verification.checked_numeric_claims > 0
    assert "deterministically" in " ".join(draft.limitations)


def test_a_fabricated_number_is_rejected() -> None:
    """Section 16.4: numeric claims are replayed against tool output."""

    bundle = _bundle()
    verification = verify_output(
        "Adoption fell to 12.5 over the quarter and churn risk is 91.4%.",
        "Escalate to the sponsor.",
        (),
        ["TCK-1"],
        bundle,
    )
    assert not verification.passed
    assert any("not in the verified evidence" in failure for failure in verification.failures)


def test_a_verified_number_written_as_a_percentage_is_accepted() -> None:
    """A probability may honestly be written either way."""

    verification = verify_output(
        "The forecaster puts Churned at 60.0% with adoption at 42.5.",
        "Review with the account team.",
        (),
        ["TCK-1"],
        _bundle(),
    )
    assert verification.passed, verification.failures


def test_identifiers_and_dates_are_not_read_as_numeric_claims() -> None:
    """`ACC-1042`, `KB-012`, `P1`, and 2026-01-10 are names, not measurements."""

    verification = verify_output(
        "Ticket TCK-1 for ACC-1042 on 2026-01-10 was a P1 issue; see KB-012.",
        "Follow KB-012.",
        (),
        ["TCK-1", "KB-012"],
        _bundle(),
    )
    assert verification.passed, verification.failures
    assert verification.checked_numeric_claims == 0


def test_a_citation_that_was_never_retrieved_is_rejected() -> None:
    """A plausible-looking document id is the easiest thing for a model to invent."""

    verification = verify_output(
        "Adoption is 42.5 at the cutoff.", "Escalate.", (), ["TCK-9999"], _bundle()
    )
    assert not verification.passed
    assert any("not retrieved" in failure for failure in verification.failures)


def test_a_narrative_that_cites_nothing_while_evidence_exists_is_rejected() -> None:
    """Grounding is the point; an ungrounded rationale is a fluent guess."""

    verification = verify_output("Adoption is 42.5 at the cutoff.", "Escalate.", (), [], _bundle())
    assert not verification.passed
    assert any("cites no evidence" in failure for failure in verification.failures)


def test_an_evaluation_only_field_name_is_rejected_but_the_word_outcome_is_not() -> None:
    """ "The renewal outcome" is English; `outcome_reason` is a schema token.

    The knowledge-base sanitiser strips both, which is right for an indexed
    article. Applying the same rule to a rationale rejected ordinary business
    prose, so only the bare word is exempt here.
    """

    bundle = _bundle()
    ok = verify_output(
        "The renewal outcome depends on the escalation in TCK-1.",
        "Escalate to the sponsor.",
        (),
        ["TCK-1"],
        bundle,
    )
    assert ok.passed, ok.failures

    leaked = verify_output(
        "The health_band field says this account is at risk.",
        "Escalate.",
        (),
        ["TCK-1"],
        bundle,
    )
    assert not leaked.passed
    assert any("evaluation-only" in failure for failure in leaked.failures)


def test_a_url_in_a_narrative_is_rejected() -> None:
    """Nothing in this system can reach the web, so a link is a fabricated source."""

    verification = verify_output(
        "See https://example.com/report for details.", "Escalate.", (), ["TCK-1"], _bundle()
    )
    assert not verification.passed


def test_an_empty_rationale_or_action_is_rejected() -> None:
    """Section 16.4 requires both, so an empty one is a verification failure."""

    assert not verify_output("", "Escalate.", (), ["TCK-1"], _bundle()).passed
    assert not verify_output("Adoption is 42.5.", "", (), ["TCK-1"], _bundle()).passed


def test_a_citation_from_another_account_fails_verification() -> None:
    """Section 16.4 verifies citation ownership as well as the numbers."""

    stolen = _citation("TCK-X", "adverse", "support_ticket").model_copy(
        update={"account_id": "ACC-9999"}
    )
    bundle = _bundle(supporting=(stolen,))
    verification = verify_output("Adoption is 42.5.", "Escalate.", (), ["TCK-X"], bundle)
    assert not verification.passed
    assert any("another account" in failure for failure in verification.failures)


def test_a_citation_after_the_cutoff_fails_verification() -> None:
    """A post-cutoff citation is the leak this whole system is built to prevent."""

    future = _citation("NOTE-F").model_copy(
        update={"doc_date": date(2026, 12, 1), "signal": "adverse"}
    )
    bundle = _bundle(supporting=(future,))
    verification = verify_output("Adoption is 42.5.", "Escalate.", (), ["NOTE-F"], bundle)
    assert not verification.passed
    assert any("postdates the cutoff" in failure for failure in verification.failures)


def test_the_brief_offers_every_group_and_names_the_citable_ids() -> None:
    """A model can only cite what it was shown."""

    brief = evidence_brief(_bundle())
    assert "Supporting evidence" in brief
    assert "Other retrieved evidence" in brief
    assert "Playbook guidance" in brief
    assert "TCK-1" in brief and "NOTE-1" in brief and "KB-012" in brief
    assert "Citable document ids" in brief
    assert "60.0%" in brief


def test_allowed_numbers_covers_metrics_probabilities_and_counts() -> None:
    """The permitted set is what makes the numeric check meaningful."""

    numbers = allowed_numbers(_bundle())
    assert 42.5 in numbers
    assert 0.6 in numbers
    assert 60.0 in numbers
    assert 13.0 in numbers


def test_the_adjudicator_without_a_provider_returns_a_deterministic_draft() -> None:
    """Section 14.3: an unavailable model produces a notice, not a failed run."""

    result = ForecastAdjudicator().draft(_bundle())
    assert result.source == "deterministic"
    assert result.fallback_reason == "no language-model provider is configured"
    assert result.draft.rationale
    assert ForecastAdjudicator().has_model is False


def test_a_provider_failure_falls_back_rather_than_ending_the_run() -> None:
    """One bad provider call must not lose the verified evidence behind it."""

    result = ForecastAdjudicator(ScriptedGenerator([GenerationError("down")])).draft(_bundle())
    assert result.source == "deterministic"
    assert result.fallback_reason is not None
    assert "generation failed" in result.fallback_reason


def test_a_repair_note_is_passed_back_to_the_model() -> None:
    """Regenerating without saying what was wrong mostly repeats the failure."""

    reply = (
        '{"rationale": "Adoption is 42.5 at the cutoff.", "limitations": [], '
        '"recommended_action": "Escalate to the sponsor.", "cited_doc_ids": ["TCK-1"], '
        '"evidence_supports_outcome": true, "disagreement_note": ""}'
    )
    generator = ScriptedGenerator([reply])
    ForecastAdjudicator(generator).draft(_bundle(), repair_note="states an unverified number")
    assert "output verification" in generator.requests[0].input_text
    assert "states an unverified number" in generator.requests[0].input_text


def test_a_disagreeing_model_is_recorded_rather_than_overruled() -> None:
    """Section 13.4 lets the adjudicator dissent; the label still comes from the model."""

    reply = (
        '{"rationale": "Adoption is 42.5 but the escalation in TCK-1 is being resolved.", '
        '"limitations": [], "recommended_action": "Escalate to the sponsor.", '
        '"cited_doc_ids": ["TCK-1"], "evidence_supports_outcome": false, '
        '"disagreement_note": "The open ticket shows active engagement."}'
    )
    result = ForecastAdjudicator(ScriptedGenerator([reply])).draft(_bundle())
    assert result.source == "model"
    assert result.draft.evidence_supports_outcome is False
    assert result.draft.disagreement_note


def test_a_kind_that_is_not_in_the_vocabulary_cannot_be_planned() -> None:
    """The closed sub-goal vocabulary is what bounds an LLM planner."""

    kinds: set[SubGoalKind] = set(SUB_GOAL_SOURCES)
    assert kinds == set(DEFAULT_QUERIES)


def test_a_tool_returning_the_wrong_shape_is_a_loud_failure() -> None:
    """A tool table and a caller that have drifted must not half-work."""

    from meridian.agents.base import call_tool
    from meridian.contracts import CoverageReport as _Coverage
    from meridian.tools.contracts import AccountProfileResponse, ToolResponse

    class WrongRegistry:
        @staticmethod
        def call(role: str, tool: str, arguments: object) -> ToolResponse:
            return ToolResponse(cutoff=CUTOFF)

    del _Coverage
    with pytest.raises(TypeError, match="expected AccountProfileResponse"):
        call_tool(
            cast("ToolRegistry", WrongRegistry()),
            "orchestrator",
            "get_account_profile",
            {},
            AccountProfileResponse,
        )


def test_the_deterministic_narrative_can_argue_a_selected_outcome() -> None:
    """A fallback for a Tree-of-Thought winner must argue that winner.

    Defaulting to the model's own label would produce a decision whose outcome
    field and whose prose name different outcomes.
    """

    bundle = _bundle()
    assert bundle.quantitative.predicted_outcome == "Churned"

    selected = deterministic_draft(bundle, outcome="Renewed")
    assert "Renewed" in selected.rationale
    assert "Churned" not in selected.rationale
    verification = verify_output(
        selected.rationale,
        selected.recommended_action,
        selected.limitations,
        selected.cited_doc_ids,
        bundle,
    )
    assert verification.passed, verification.failures
