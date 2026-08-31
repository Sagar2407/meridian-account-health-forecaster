"""The curated retrieval benchmark's own construction (plan section 11.6).

The benchmark is the Phase 3 exit gate, so its query families have to be real.
A family that silently builds zero queries would report a perfect safety score
while measuring nothing.
"""

import pytest

from meridian.data.repository import RuntimeRepository
from meridian.retrieval.documents import build_parent_documents
from meridian_eval.retrieval_benchmark import (
    ACCOUNT_PROBES,
    build_benchmark,
    golden_assessment_accounts,
)

pytestmark = pytest.mark.requires_dataset


def test_the_benchmark_covers_all_four_documented_families(
    runtime: RuntimeRepository,
) -> None:
    """Every family the module documents must actually produce queries."""

    families = {query.family for query in build_benchmark(repository=runtime)}
    assert families == {
        "knowledge_base",
        "account",
        "conflicting_signal",
        "point_in_time",
    }


def test_point_in_time_queries_name_evidence_the_cutoff_must_hide(
    runtime: RuntimeRepository,
) -> None:
    """Each probe must quote a real document dated after that account's cutoff."""

    accounts = golden_assessment_accounts()
    probes = [
        query for query in build_benchmark(repository=runtime) if query.family == "point_in_time"
    ]
    assert probes, "no point-in-time probe was built; the safety family is vacuous"
    assert {query.account_id for query in probes} <= set(accounts)
    for query in probes:
        assert query.query.strip()
        assert len(query.forbidden_parents) == 1
        forbidden = query.forbidden_parents[0]
        assert query.account_id is not None
        visible = {
            *runtime.notes(query.account_id)["note_id"],
            *runtime.tickets(query.account_id)["ticket_id"],
        }
        # The document is real but postdates the cutoff, so the cutoff-filtered
        # runtime repository must not be able to see it.
        assert forbidden not in visible


def test_account_probes_are_graded_against_real_documents(
    runtime: RuntimeRepository,
) -> None:
    """A gold set that resolves to nothing would make the account family vacuous."""

    accounts = golden_assessment_accounts()
    account_queries = [
        query for query in build_benchmark(repository=runtime) if query.family == "account"
    ]
    graded = [query for query in account_queries if query.expected_parents]
    assert len(account_queries) == len(accounts) * len(ACCOUNT_PROBES)
    assert graded, "no account probe resolved a gold set"

    for query in graded:
        assert query.account_id is not None
        visible = {
            document.doc_id
            for document in build_parent_documents(
                runtime, (query.account_id,), include_knowledge_base=False
            )
        }
        # Every gold parent must be something retrieval is allowed to return.
        assert set(query.expected_parents) <= visible


def test_ungraded_probes_are_the_three_subjective_ones() -> None:
    """Only questions with no defensible structural label may go ungraded."""

    ungraded = {probe.name for probe in ACCOUNT_PROBES if not probe.is_graded}
    assert ungraded == {"risk", "adoption", "sponsor"}


def test_conflicting_signal_queries_hold_both_polarities(
    runtime: RuntimeRepository,
) -> None:
    """A conflict case with only one side would not test ranking diversity."""

    conflicts = [
        query
        for query in build_benchmark(repository=runtime)
        if query.family == "conflicting_signal"
    ]
    assert conflicts, "no account produced a conflicting-signal case"
    for query in conflicts:
        contrasting = set(query.contrasting_parents)
        supporting = set(query.expected_parents) - contrasting
        assert contrasting and supporting
        assert contrasting <= set(query.expected_parents)
