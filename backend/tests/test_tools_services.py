"""The eight read-only services against the real dataset (plan section 12.1).

`test_tools_registry.py` covers policy: who may call what, and what happens to a
hostile argument. This file covers the answers themselves -- that a service
returns the same numbers the underlying layer would, aggregated the way it
claims, and never reaching past the cutoff.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

from meridian.data.constants import DATASET_AS_OF_DATE
from meridian.data.repository import RuntimeRepository
from meridian.features.builder import build_features
from meridian.memory.store import AssessmentStore, AssessmentStoreError
from meridian.retrieval.documents import build_parent_documents
from meridian.tools.contracts import (
    AccountRequest,
    EvidenceRequest,
    KnowledgeRequest,
    PointInTimeRequest,
    WindowedRequest,
)
from meridian.tools.services import ToolServices
from stub_encoder import build_stub_service

pytestmark = pytest.mark.requires_dataset

ANALYST = "quantitative_analyst"


@pytest.fixture(scope="module")
def services(runtime: RuntimeRepository) -> ToolServices:
    """Return services over the real dataset, without retrieval or memory."""

    return ToolServices(runtime)


@pytest.fixture(scope="module")
def account_id(runtime: RuntimeRepository) -> str:
    """Return an account with enough history for the window assertions."""

    return max(runtime.account_ids(), key=lambda item: len(runtime.tickets(item)))


def test_the_profile_matches_the_repository(
    services: ToolServices, runtime: RuntimeRepository, account_id: str
) -> None:
    """The tool must not restate identity differently from the data layer."""

    profile = runtime.profile(account_id)
    response = services.get_account_profile(AccountRequest(role=ANALYST, account_id=account_id))
    assert response.account_id == account_id
    assert response.cutoff == profile.effective_cutoff
    assert response.profile["account_name"] == profile.account_name
    assert response.profile["licensed_seats"] == profile.licensed_seats


def test_metrics_match_the_feature_builder(
    services: ToolServices, runtime: RuntimeRepository, account_id: str
) -> None:
    """The tool is a boundary, not a second implementation."""

    expected = build_features(runtime, account_id)
    response = services.compute_account_metrics(
        PointInTimeRequest(role=ANALYST, account_id=account_id)
    )
    assert response.metrics == pytest.approx(expected.values)
    assert response.cutoff == expected.cutoff
    assert response.coverage["tickets_in_window"] == expected.coverage.tickets_in_window
    assert response.thin_families == expected.coverage.thin_families


def test_an_earlier_as_of_can_only_narrow_the_metrics_window(
    services: ToolServices, runtime: RuntimeRepository, account_id: str
) -> None:
    """Point-in-time backtesting has to actually move the cutoff."""

    canonical = runtime.cutoff_for(account_id)
    earlier = canonical - timedelta(days=180)
    response = services.compute_account_metrics(
        PointInTimeRequest(role=ANALYST, account_id=account_id, as_of=earlier)
    )
    assert response.cutoff == earlier
    assert response.cutoff < canonical


def test_the_usage_series_is_one_row_per_week_and_sums_products(
    services: ToolServices, runtime: RuntimeRepository, account_id: str
) -> None:
    """The archive stores one row per product per week; callers want the week."""

    response = services.get_usage_series(
        WindowedRequest(role=ANALYST, account_id=account_id, window_weeks=13)
    )
    assert response.points, "no telemetry returned; the assertions below would be vacuous"

    weeks = [point.week_start for point in response.points]
    assert len(weeks) == len(set(weeks))
    assert weeks == sorted(weeks)
    assert max(weeks) <= response.cutoff

    raw = runtime.usage(account_id)
    raw_dates = pd.to_datetime(raw["week_start"]).dt.date
    window_start = response.cutoff - timedelta(weeks=13)
    in_window = raw.loc[(raw_dates > window_start) & (raw_dates <= response.cutoff)]
    assert sum(point.active_users for point in response.points) == int(
        in_window["active_users"].sum()
    )


def test_the_support_summary_counts_the_same_rows_the_repository_returns(
    services: ToolServices, runtime: RuntimeRepository, account_id: str
) -> None:
    """Counts a caller cannot reconcile against source rows are not auditable."""

    response = services.get_support_summary(
        WindowedRequest(role=ANALYST, account_id=account_id, window_weeks=26)
    )
    assert response.tickets > 0, "chose an account with no tickets; assertions would be vacuous"
    assert len(response.ticket_ids) == response.tickets
    assert sum(item.tickets for item in response.by_priority) == response.tickets
    assert response.unresolved_tickets <= response.tickets
    assert response.escalations <= response.tickets
    assert response.responses_with_csat <= response.tickets

    tickets = runtime.tickets(account_id)
    known = set(tickets["ticket_id"])
    assert set(response.ticket_ids) <= known


def test_external_events_stay_inside_the_window_and_the_horizon(
    services: ToolServices, runtime: RuntimeRepository, account_id: str
) -> None:
    """Section 8.3: post-horizon events must never reach a caller."""

    response = services.get_external_events(
        WindowedRequest(role=ANALYST, account_id=account_id, window_weeks=104)
    )
    window_start = response.cutoff - timedelta(weeks=104)
    for event in response.events:
        assert window_start < event.event_date <= response.cutoff
        assert event.event_date <= DATASET_AS_OF_DATE
        assert -1 <= event.polarity <= 1


def test_a_narrow_window_returns_no_more_than_a_wide_one(
    services: ToolServices, account_id: str
) -> None:
    """A window argument that did nothing would pass every other test here."""

    wide = services.get_support_summary(
        WindowedRequest(role=ANALYST, account_id=account_id, window_weeks=104)
    )
    narrow = services.get_support_summary(
        WindowedRequest(role=ANALYST, account_id=account_id, window_weeks=4)
    )
    assert narrow.tickets <= wide.tickets
    assert set(narrow.ticket_ids) <= set(wide.ticket_ids)
    assert wide.tickets > narrow.tickets, "window made no difference; pick a busier account"


def test_prior_assessments_round_trip_through_application_memory(
    runtime: RuntimeRepository, account_id: str, tmp_path: object
) -> None:
    """`get_prior_assessments` reads what the system itself recorded."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")  # type: ignore[operator]
    services = ToolServices(runtime, store=store)

    empty = services.get_prior_assessments(
        AccountRequest(role="orchestrator", account_id=account_id)
    )
    assert empty.assessments == ()

    store.record_assessment(
        account_id=account_id,
        cutoff=date(2026, 6, 1),
        predicted_outcome="Churned",
        confidence=0.81,
        decision="release",
        summary="Adoption fell and the sponsor left.",
    )
    store.record_assessment(
        account_id=account_id,
        cutoff=date(2026, 6, 28),
        predicted_outcome="Contracted",
        confidence=0.55,
        decision="human_review",
        summary="Signals disagree.",
    )

    response = services.get_prior_assessments(
        AccountRequest(role="orchestrator", account_id=account_id)
    )
    assert [item.assessment_id for item in response.assessments] == [
        f"ASMT-{account_id}-0002",
        f"ASMT-{account_id}-0001",
    ]
    assert response.assessments[0].decision == "human_review"


def test_application_memory_refuses_to_write_inside_the_raw_archive() -> None:
    """Source data is immutable; a misconfigured path must fail at construction."""

    from meridian.data.paths import raw_dataset_directory

    with pytest.raises(AssessmentStoreError, match="raw archive"):
        AssessmentStore(raw_dataset_directory() / "assessments.sqlite")


def test_application_memory_rejects_an_impossible_confidence(tmp_path: object) -> None:
    """A confidence outside [0, 1] would corrupt every downstream routing rule."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")  # type: ignore[operator]
    with pytest.raises(AssessmentStoreError, match="confidence"):
        store.record_assessment(
            account_id="ACC-1042",
            cutoff=date(2026, 6, 28),
            predicted_outcome="Renewed",
            confidence=1.4,
            decision="release",
            summary="impossible",
        )


def test_a_review_case_must_reference_a_recorded_assessment(tmp_path: object) -> None:
    """A case pointing at nothing cannot be reviewed."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")  # type: ignore[operator]
    with pytest.raises(AssessmentStoreError, match="unknown assessment"):
        store.open_review_case("ASMT-ACC-1042-0001", "no such assessment")

    recorded = store.record_assessment(
        account_id="ACC-1042",
        cutoff=date(2026, 6, 28),
        predicted_outcome="Contracted",
        confidence=0.42,
        decision="human_review",
        summary="Low confidence.",
    )
    case = store.open_review_case(recorded.assessment_id, "confidence below the release band")
    assert case.status == "open"
    assert case.account_id == "ACC-1042"
    assert store.review_cases("ACC-1042") == (case,)


@pytest.fixture(scope="module")
def retrieval_services(
    runtime: RuntimeRepository, tmp_path_factory: pytest.TempPathFactory
) -> ToolServices:
    """Return services backed by a small offline index over a few accounts."""

    accounts = runtime.account_ids()[:6]
    service = build_stub_service(runtime, tmp_path_factory.mktemp("tool-index"), accounts)
    return ToolServices(runtime, retrieval=service)


@pytest.fixture(scope="module")
def indexed_account(runtime: RuntimeRepository) -> str:
    """Return an account that is inside the small index above."""

    return runtime.account_ids()[0]


def test_account_evidence_is_scoped_dated_and_graded(
    retrieval_services: ToolServices, runtime: RuntimeRepository, indexed_account: str
) -> None:
    """The retrieval tool must carry Phase 3's guarantees across the boundary."""

    response = retrieval_services.retrieve_account_evidence(
        EvidenceRequest(
            role="evidence_retriever",
            account_id=indexed_account,
            sub_goal="renewal risk and sponsor change",
        )
    )
    assert response.citations, "no citations; every assertion below would be vacuous"
    assert response.cutoff == runtime.cutoff_for(indexed_account)
    for citation in response.citations:
        assert citation.doc_date is not None
        assert citation.doc_date <= response.cutoff
        assert citation.source_type != "knowledge_base"
        assert citation.excerpt.strip()
    assert sum(response.source_coverage.values()) == len(response.citations)
    assert response.attempted_queries[0] == "renewal risk and sponsor change"


def test_account_evidence_respects_a_source_family_restriction(
    retrieval_services: ToolServices, indexed_account: str
) -> None:
    """An agent that asked only for tickets must not be handed notes."""

    response = retrieval_services.retrieve_account_evidence(
        EvidenceRequest(
            role="evidence_retriever",
            account_id=indexed_account,
            sub_goal="support escalations",
            source_families=("support_ticket",),
        )
    )
    assert response.citations
    assert {citation.source_type for citation in response.citations} == {"support_ticket"}


def test_account_evidence_never_returns_another_accounts_document(
    retrieval_services: ToolServices, runtime: RuntimeRepository
) -> None:
    """The account filter has to survive the tool layer too."""

    for account_id in runtime.account_ids()[:6]:
        response = retrieval_services.retrieve_account_evidence(
            EvidenceRequest(
                role="evidence_retriever",
                account_id=account_id,
                sub_goal="renewal outlook",
            )
        )
        visible = {
            document.doc_id
            for document in build_parent_documents(
                runtime, (account_id,), include_knowledge_base=False
            )
        }
        assert {citation.doc_id for citation in response.citations} <= visible


def test_knowledge_guidance_is_undated_and_not_account_scoped(
    retrieval_services: ToolServices,
) -> None:
    """Guidance is shared, so it carries no account and no document date."""

    response = retrieval_services.retrieve_knowledge(
        KnowledgeRequest(role="evidence_retriever", sub_goal="how do I run a save play")
    )
    assert response.citations, "no guidance returned; the assertions would be vacuous"
    assert len(response.citations) <= 2
    for citation in response.citations:
        assert citation.source_type == "knowledge_base"
        assert citation.doc_date is None
        assert citation.doc_id.startswith("KB-")


def test_knowledge_retrieval_does_not_need_an_account(
    retrieval_services: ToolServices,
) -> None:
    """`KnowledgeRequest` has no account field at all, by construction."""

    assert "account_id" not in KnowledgeRequest.model_fields
