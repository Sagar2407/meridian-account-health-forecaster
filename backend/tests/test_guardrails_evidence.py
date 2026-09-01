"""Evidence-boundary guardrails (plan section 16.3)."""

from datetime import date, timedelta

from meridian.contracts import (
    Citation,
    CoverageReport,
    MetricObservation,
    QuantitativeEvidence,
    RetrievalEvidence,
    RetrievalObservation,
)
from meridian.guardrails.evidence import citation_violation, metric_violation, screen_evidence

CUTOFF = date(2026, 3, 1)
ACCOUNT = "ACC-1042"


def _citation(**overrides: object) -> Citation:
    values: dict[str, object] = {
        "doc_id": "NOTE-1",
        "parent_id": "NOTE-1",
        "source_type": "csm_note",
        "subtype": "Quarterly Business Review",
        "account_id": ACCOUNT,
        "doc_date": CUTOFF,
        "excerpt": "The sponsor remains engaged.",
        "retrieval_score": 0.9,
    }
    return Citation(**{**values, **overrides})


def _metric(**overrides: object) -> MetricObservation:
    values: dict[str, object] = {
        "name": "adoption_trend_13w",
        "value": 1.25,
        "window": "13 weeks through 2026-03-01",
        "source": "usage_weekly",
        "coverage": 13,
        "calculation_version": "features-v1",
    }
    return MetricObservation(**{**values, **overrides})


def _quantitative(**overrides: object) -> QuantitativeEvidence:
    values: dict[str, object] = {
        "account_id": ACCOUNT,
        "cutoff": CUTOFF,
        "metrics": (_metric(),),
        "distribution": {
            "Churned": 0.1,
            "Contracted": 0.1,
            "Renewed": 0.7,
            "Expanded": 0.1,
        },
        "predicted_outcome": "Renewed",
        "model_probability": 0.7,
        "coverage": CoverageReport(expected_weeks=13, observed_weeks=13),
    }
    return QuantitativeEvidence(**{**values, **overrides})


def _retrieval(
    citation: Citation | None = None,
    guidance: tuple[Citation, ...] = (),
    **overrides: object,
) -> RetrievalEvidence:
    evidence = citation or _citation()
    values: dict[str, object] = {
        "account_id": ACCOUNT,
        "cutoff": CUTOFF,
        "observations": (
            RetrievalObservation(
                sub_goal="relationship",
                query="sponsor status",
                citations=(evidence,),
            ),
        ),
        "guidance": guidance,
    }
    return RetrievalEvidence(**{**values, **overrides})


def test_clean_lane_envelopes_metrics_and_citations_pass() -> None:
    guidance = _citation(
        doc_id="KB-001",
        parent_id="KB-001",
        source_type="knowledge_base",
        subtype="playbook",
        account_id=None,
        doc_date=None,
    )
    screened = screen_evidence(_quantitative(), _retrieval(guidance=(guidance,)), ACCOUNT, CUTOFF)

    assert screened.clean is True
    assert screened.quantitative_valid is True
    assert screened.retrieval_valid is True
    assert screened.metrics == (_metric(),)
    assert screened.citations[0].account_id == ACCOUNT
    assert screened.guidance == (guidance,)
    assert screened.decision.outcome == "pass"


def test_account_and_guidance_lanes_cannot_be_swapped() -> None:
    accountless_note = _citation(account_id=None)
    account_violation = citation_violation(accountless_note, ACCOUNT, CUTOFF, "account")
    assert account_violation is not None and account_violation[0] == "EVID-ACCOUNT"

    account_owned_guidance = _citation(
        source_type="knowledge_base", subtype="playbook", account_id=ACCOUNT, doc_date=None
    )
    guidance_violation = citation_violation(account_owned_guidance, ACCOUNT, CUTOFF, "guidance")
    assert guidance_violation is not None and guidance_violation[0] == "EVID-ACCOUNT"

    wrong_source = _citation(account_id=None, doc_date=None)
    source_violation = citation_violation(wrong_source, ACCOUNT, CUTOFF, "guidance")
    assert source_violation is not None and source_violation[0] == "EVID-SOURCE"


def test_wrong_account_future_and_latent_citations_are_quarantined() -> None:
    poisoned = (
        _citation(doc_id="WRONG", parent_id="WRONG", account_id="ACC-9999"),
        _citation(
            doc_id="FUTURE",
            parent_id="FUTURE",
            doc_date=CUTOFF + timedelta(days=1),
        ),
        _citation(
            doc_id="LEAK",
            parent_id="LEAK",
            excerpt="The health_archetype says this account is stable.",
        ),
    )
    retrieval = _retrieval().model_copy(
        update={
            "observations": (
                RetrievalObservation(sub_goal="relationship", query="sponsor", citations=poisoned),
            )
        }
    )

    screened = screen_evidence(_quantitative(), retrieval, ACCOUNT, CUTOFF)

    assert screened.citations == ()
    assert set(screened.rule_ids) == {"EVID-ACCOUNT", "EVID-CUTOFF", "EVID-LEAK"}
    assert screened.decision.outcome == "review"


def test_bad_numeric_provenance_invalidates_the_quantitative_lane() -> None:
    bad = _metric(value=5.0, coverage=0, calculation_version=" ")
    assert metric_violation(bad) is not None
    screened = screen_evidence(_quantitative(metrics=(bad,)), _retrieval(), ACCOUNT, CUTOFF)

    assert screened.quantitative_valid is False
    assert screened.metrics == ()
    assert "EVID-PROVENANCE" in screened.rule_ids


def test_a_mismatched_lane_envelope_fails_closed() -> None:
    screened = screen_evidence(
        _quantitative(account_id="ACC-9999"),
        _retrieval(cutoff=CUTOFF - timedelta(days=1)),
        ACCOUNT,
        CUTOFF,
    )

    assert screened.quantitative_valid is False
    assert screened.retrieval_valid is False
    assert screened.metrics == ()
    assert screened.citations == ()
    assert screened.guidance == ()
    assert "EVID-ENVELOPE" in screened.rule_ids
