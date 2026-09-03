"""The review queue is ordered by priority, not by arrival (plan section 20.5).

Section 20.5 asks for "priority ordering by route, ACV, renewal proximity, and
age". Only route and age live on a review case; ACV and renewal date are the
account's commercial terms, so the queue is joined against the repository and
ordered in the route.

The ordering is only worth anything if `limit` is applied after it. These tests
exist mainly to hold that: the queue used to return the newest `limit` cases and
let the browser sort those, which meant the oldest untouched red case on the
largest account -- the one the ordering exists to surface -- could not appear at
all.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meridian.api import dependencies
from meridian.api.main import create_app
from meridian.api.routes.review import ReviewCaseSummary, _priority, get_store
from meridian.data.repository import RuntimeRepository
from meridian.memory.store import AssessmentStore

pytestmark = pytest.mark.requires_dataset


def _open_case(
    store: AssessmentStore,
    account_id: str,
    route: str = "red",
    opened_at: str = "2026-06-28T00:00:00+00:00",
) -> str:
    """Record one assessment on `account_id` and open a case against it.

    `opened_at` is passed rather than left to the clock: age is one of the four
    sort keys, and cases opened in the same millisecond would make the tests
    that depend on it decide by tie-break instead.
    """

    assessment = store.record_assessment(
        account_id=account_id,
        cutoff=date(2026, 6, 28),
        predicted_outcome="Contracted",
        confidence=0.61,
        decision=route,
        summary="Recorded for the queue-ordering tests.",
        question="What is the renewal outlook?",
        card={"outcome": "Contracted", "confidence": 0.61},
    )
    case = store.open_review_case(
        assessment.assessment_id,
        "an unresolved severe conflict",
        created_at=opened_at,
        route=route,
        reason_codes=("evidence_conflict",),
    )
    return case.case_id


@pytest.fixture
def queue_client(
    runtime: RuntimeRepository, tmp_path: Path
) -> Iterator[tuple[TestClient, AssessmentStore]]:
    """Return a client whose review queue reads a temporary store."""

    store = AssessmentStore(tmp_path / "assessments.sqlite")
    application = create_app()
    application.dependency_overrides[get_store] = lambda: store
    # The route reads account profiles, exactly as the portfolio route does.
    # Only the repository is used, so a bare object carrying one is enough and
    # avoids assembling a graph the queue never runs.
    application.dependency_overrides[dependencies.get_runtime] = lambda: _RepositoryOnly(runtime)
    with TestClient(application) as client:
        yield client, store


class _RepositoryOnly:
    """The one attribute of the runtime the review queue touches."""

    def __init__(self, repository: RuntimeRepository) -> None:
        self.repository = repository


def _accounts_by_acv(runtime: RuntimeRepository, count: int) -> list[str]:
    """Return `count` account ids, largest contract first."""

    profiles = [runtime.profile(account_id) for account_id in runtime.account_ids()]
    profiles.sort(key=lambda profile: (-profile.acv_usd, profile.account_id))
    return [profile.account_id for profile in profiles[:count]]


def test_route_outranks_every_commercial_signal(
    queue_client: tuple[TestClient, AssessmentStore], runtime: RuntimeRepository
) -> None:
    """An amber case on the largest account still sits below any red case."""

    client, store = queue_client
    largest, smallest = _accounts_by_acv(runtime, 1)[0], _accounts_by_acv(runtime, 260)[-1]
    amber = _open_case(store, largest, "amber")
    red = _open_case(store, smallest, "red")

    rows = client.get("/api/review-cases").json()
    assert [row["case_id"] for row in rows] == [red, amber]
    assert rows[0]["route"] == "red"


def test_within_one_route_the_larger_contract_comes_first(
    queue_client: tuple[TestClient, AssessmentStore], runtime: RuntimeRepository
) -> None:
    """ACV is the second key, so it decides between two red cases."""

    client, store = queue_client
    ranked = _accounts_by_acv(runtime, 260)
    largest, smallest = ranked[0], ranked[-1]
    # Opened in the order that would win on age alone, so a queue that ignored
    # ACV would return them the other way round.
    small_case = _open_case(store, smallest, "red", opened_at="2026-06-27T00:00:00+00:00")
    large_case = _open_case(store, largest, "red")

    rows = client.get("/api/review-cases").json()
    assert [row["case_id"] for row in rows] == [large_case, small_case]
    assert rows[0]["acv_usd"] > rows[1]["acv_usd"]


def test_the_queue_carries_the_terms_it_was_ordered_by(
    queue_client: tuple[TestClient, AssessmentStore], runtime: RuntimeRepository
) -> None:
    """A reviewer can see why a case is where it is."""

    client, store = queue_client
    account = _accounts_by_acv(runtime, 1)[0]
    _open_case(store, account, "red")

    row = client.get("/api/review-cases").json()[0]
    profile = runtime.profile(account)
    assert row["acv_usd"] == pytest.approx(profile.acv_usd)
    assert row["renewal_date"] == profile.renewal_date.isoformat()
    assert row["days_to_renewal"] == (profile.renewal_date - profile.forecast_as_of_date).days


def test_a_case_outlives_its_account_and_still_appears_last(
    queue_client: tuple[TestClient, AssessmentStore], runtime: RuntimeRepository
) -> None:
    """A case on an account no longer in the portfolio is listed, not hidden."""

    client, store = queue_client
    present = _accounts_by_acv(runtime, 260)[-1]
    orphan = _open_case(store, "ACC-000000", "red", opened_at="2026-06-27T00:00:00+00:00")
    kept = _open_case(store, present, "red")

    rows = client.get("/api/review-cases").json()
    assert [row["case_id"] for row in rows] == [kept, orphan]
    assert rows[-1]["acv_usd"] is None
    assert rows[-1]["days_to_renewal"] is None


def test_limit_selects_the_most_urgent_not_the_newest(
    queue_client: tuple[TestClient, AssessmentStore], runtime: RuntimeRepository
) -> None:
    """The regression this ordering exists to prevent.

    The urgent case is opened first, so it is the oldest. A queue that applied
    `limit` before ordering would return only the newest row and the reviewer
    would never see it.
    """

    client, store = queue_client
    ranked = _accounts_by_acv(runtime, 260)
    urgent = _open_case(store, ranked[0], "red", opened_at="2026-06-20T00:00:00+00:00")
    for account in ranked[1:6]:
        _open_case(store, account, "amber")

    rows = client.get("/api/review-cases?limit=1").json()
    assert [row["case_id"] for row in rows] == [urgent]


def _row(
    case_id: str = "CASE-ACC-1000-0001-01",
    route: str = "red",
    acv_usd: float | None = 100_000.0,
    days_to_renewal: int | None = 90,
    created_at: str = "2026-06-28T00:00:00+00:00",
) -> ReviewCaseSummary:
    """Return a queue row with the four priority fields set and the rest inert.

    Named parameters rather than `**overrides`, so a typo in a test is a type
    error here instead of a silently ignored keyword that leaves the default in
    place and makes the assertion pass for the wrong reason.
    """

    return ReviewCaseSummary(
        case_id=case_id,
        assessment_id="ASMT-ACC-1000-0001",
        account_id="ACC-1000",
        created_at=created_at,
        reason="an unresolved severe conflict",
        status="open",
        route=route,
        acv_usd=acv_usd,
        days_to_renewal=days_to_renewal,
    )


def test_renewal_proximity_breaks_a_tie_on_route_and_contract_value() -> None:
    """The third key: with the same route and ACV, the sooner renewal is first."""

    sooner = _row(case_id="CASE-A", days_to_renewal=10)
    later = _row(case_id="CASE-B", days_to_renewal=200)
    assert sorted([later, sooner], key=_priority) == [sooner, later]


def test_a_renewal_already_past_is_the_most_urgent_of_all() -> None:
    """Negative proximity means the renewal date has gone by; it sorts first."""

    overdue = _row(case_id="CASE-A", days_to_renewal=-5)
    upcoming = _row(case_id="CASE-B", days_to_renewal=1)
    assert sorted([upcoming, overdue], key=_priority) == [overdue, upcoming]


def test_age_breaks_a_tie_on_everything_else_oldest_first() -> None:
    """The fourth key: the case that has waited longest goes first."""

    older = _row(case_id="CASE-A", created_at="2026-06-01T00:00:00+00:00")
    newer = _row(case_id="CASE-B", created_at="2026-06-28T00:00:00+00:00")
    assert sorted([newer, older], key=_priority) == [older, newer]


def test_an_unrecognised_route_sorts_after_every_known_one() -> None:
    """A route this code has not been taught is not silently treated as red."""

    known = _row(case_id="CASE-A", route="green")
    unknown = _row(case_id="CASE-B", route="chartreuse")
    assert sorted([unknown, known], key=_priority) == [known, unknown]
