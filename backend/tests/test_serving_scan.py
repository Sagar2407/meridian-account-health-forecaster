"""The autonomous portfolio scan and its bounds (plan section 18).

The Phase 8 exit gate is that a scan "completes without exceeding configured
concurrency or model-call budget". Both are asserted here against measurements
the scan takes of itself while it runs, not against the values it was
configured with -- a scan that reported back its own settings would pass this
gate no matter what it actually did.
"""

import threading

import pytest

from meridian.data.repository import RuntimeRepository
from meridian.graph.runtime import GraphRuntime
from meridian.memory.store import AssessmentStore
from meridian.model.artifacts import ModelArtifact
from meridian.serving.scan import (
    AUTO_RELEASED_ROUTES,
    PortfolioScan,
    ScanRequest,
    ScanRunRecord,
    eligible_accounts,
    run_portfolio_scan,
)
from meridian.settings import Settings
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolServices
from stub_encoder import build_stub_service

pytestmark = pytest.mark.requires_dataset


@pytest.fixture(scope="module")
def scan_accounts(runtime: RuntimeRepository) -> tuple[str, ...]:
    """Return a small, stable slice of the portfolio to index."""

    return runtime.account_ids()[:8]


@pytest.fixture(scope="module")
def scan_runtime(
    runtime: RuntimeRepository,
    forecaster_artifact: ModelArtifact,
    scan_accounts: tuple[str, ...],
    tmp_path_factory: pytest.TempPathFactory,
) -> GraphRuntime:
    """Assemble a complete offline runtime over the indexed slice."""

    directory = tmp_path_factory.mktemp("scan-index")
    service = build_stub_service(runtime, directory, scan_accounts)
    store = AssessmentStore(tmp_path_factory.mktemp("scan-memory") / "assessments.sqlite")
    return GraphRuntime.assemble(
        repository=runtime,
        registry=ToolRegistry(ToolServices(runtime, retrieval=service, store=store)),
        artifact=forecaster_artifact,
        generator=None,
        store=store,
    )


def _settings(**overrides: object) -> Settings:
    """Return settings that ignore the developer's own .env file."""

    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_eligibility_is_the_renewal_horizon_and_nothing_else(
    runtime: RuntimeRepository,
) -> None:
    """Section 18.1 selects on a configurable horizon, measured per account."""

    near = eligible_accounts(runtime, horizon_days=30)
    far = eligible_accounts(runtime, horizon_days=365)

    assert set(near) <= set(far)
    for account_id in far:
        profile = runtime.profile(account_id)
        days = (profile.renewal_date - profile.forecast_as_of_date).days
        assert 0 <= days <= 365


def test_eligibility_is_stable_and_ordered(runtime: RuntimeRepository) -> None:
    """Two scans of one portfolio must queue the same work in the same order."""

    first = eligible_accounts(runtime, horizon_days=180, limit=10)
    second = eligible_accounts(runtime, horizon_days=180, limit=10)
    assert first == second
    dates = [runtime.profile(account).renewal_date for account in first]
    assert dates == sorted(dates)


def test_a_scan_never_exceeds_its_configured_concurrency(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """The Phase 8 exit gate, measured while the scan runs.

    `concurrency_observed` is a peak recorded by the work itself, so it cannot
    be satisfied by a scan that dispatches outside its pool or resizes it.
    """

    scan = run_portfolio_scan(
        scan_runtime, scan_accounts, settings=_settings(), concurrency=3, model_call_budget=1_000
    )

    assert scan.status == "completed"
    assert scan.summary().scanned == len(scan_accounts)
    assert 0 < scan.peak_concurrency <= 3


def test_a_serial_scan_really_is_serial(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """Concurrency 1 is the strongest form of the bound, so it is asserted exactly."""

    scan = run_portfolio_scan(scan_runtime, scan_accounts[:3], settings=_settings(), concurrency=1)
    assert scan.peak_concurrency == 1
    assert scan.status == "completed"


def test_a_spent_budget_stops_dispatch_rather_than_overspending(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """A budget of zero must scan nothing at all, not 'nearly nothing'."""

    scan = run_portfolio_scan(
        scan_runtime, scan_accounts, settings=_settings(), concurrency=2, model_call_budget=0
    )

    assert scan.budget_exhausted is True
    assert scan.runs == []
    assert list(scan.skipped) == list(scan_accounts)
    assert scan.summary().total_model_calls == 0


def test_an_offline_scan_spends_nothing_and_says_so(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """No provider is configured, so the whole scan must cost zero."""

    scan = run_portfolio_scan(scan_runtime, scan_accounts, settings=_settings(), concurrency=2)
    summary = scan.summary()

    assert summary.total_model_calls == 0
    assert summary.total_tokens == 0
    assert summary.budget_exhausted is False


def test_every_scanned_account_lands_in_exactly_one_disposition(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """A scan summary that loses or double-counts an account is not a summary."""

    scan = run_portfolio_scan(scan_runtime, scan_accounts, settings=_settings(), concurrency=2)
    summary = scan.summary()

    assert summary.completed + summary.failed + summary.blocked == summary.scanned
    assert summary.scanned == len(scan_accounts)
    assert len(scan.runs) == len(scan_accounts)
    assert {record.account_id for record in scan.runs} == set(scan_accounts)


def test_only_green_runs_are_auto_released(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """Section 18.1 auto-releases green and queues amber and red.

    This is the line between "advisory output a person may read without review"
    and "work in a queue", so it is asserted rather than assumed.
    """

    scan = run_portfolio_scan(scan_runtime, scan_accounts, settings=_settings(), concurrency=2)

    for record in scan.runs:
        if record.route in AUTO_RELEASED_ROUTES:
            assert record.auto_released is True
        else:
            assert record.auto_released is False
    summary = scan.summary()
    assert summary.auto_released + sum(summary.review_load.values()) <= summary.scanned


def test_the_summary_separates_risk_from_expansion(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """Section 18.1 asks for risk, expansion candidates, abstentions, and load."""

    scan = run_portfolio_scan(scan_runtime, scan_accounts, settings=_settings(), concurrency=2)
    summary = scan.summary()

    assert not set(summary.risk_accounts) & set(summary.expansion_candidates)
    for account_id in summary.risk_accounts:
        record = next(item for item in scan.runs if item.account_id == account_id)
        assert record.outcome in {"Churned", "Contracted"}
    for account_id in summary.expansion_candidates:
        record = next(item for item in scan.runs if item.account_id == account_id)
        assert record.outcome == "Expanded"


def test_an_unknown_account_is_refused_without_ending_the_scan(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """An unattended scan that dies on its third account is worse than useless.

    A well-formed id that names no account reaches the intake guardrail, which
    refuses it as `state_no_such_account`. That makes it a *blocked* run rather
    than a failed one -- a cleaner outcome than an exception, and the reason
    this test asserts `blocked`: an unknown account is a refusal the system
    has an answer for, not a crash it survived.
    """

    scan = run_portfolio_scan(
        scan_runtime,
        (*scan_accounts[:2], "ACC-0000", *scan_accounts[2:4]),
        settings=_settings(),
        concurrency=2,
    )

    assert scan.status == "completed"
    summary = scan.summary()
    assert summary.scanned == 5
    blocked = [record for record in scan.runs if record.status == "blocked"]
    assert [record.account_id for record in blocked] == ["ACC-0000"]
    assert summary.blocked == 1
    assert summary.completed == 4
    # A refusal is never released and never queued for review.
    assert blocked[0].auto_released is False
    assert blocked[0].review_case_id is None


def test_the_event_callback_names_the_account_it_came_from(
    scan_runtime: GraphRuntime, scan_accounts: tuple[str, ...]
) -> None:
    """A scan stream is useless if events from parallel runs are not attributable."""

    seen: list[tuple[str, str]] = []
    lock = threading.Lock()

    def record(account_id: str, event: object) -> None:
        with lock:
            seen.append((account_id, getattr(event, "event", "?")))

    run_portfolio_scan(
        scan_runtime, scan_accounts[:3], settings=_settings(), concurrency=2, on_event=record
    )

    assert seen
    assert {account for account, _ in seen} == set(scan_accounts[:3])
    for account_id in scan_accounts[:3]:
        assert "run_started" in [name for owner, name in seen if owner == account_id]


def test_an_empty_scan_summarises_to_zero() -> None:
    """The summary must not divide by, or index into, nothing."""

    scan = PortfolioScan(
        scan_id="SCAN-empty",
        request=ScanRequest(
            account_ids=(), concurrency=1, model_call_budget=0, renewal_horizon_days=90
        ),
    )
    summary = scan.summary()
    assert summary.scanned == 0
    assert summary.risk_accounts == ()
    assert summary.review_load == {}


def test_a_blocked_run_is_not_counted_as_an_answer() -> None:
    """A refusal is a disposition of its own, not a completed assessment."""

    scan = PortfolioScan(
        scan_id="SCAN-blocked",
        request=ScanRequest(
            account_ids=("ACC-1042",), concurrency=1, model_call_budget=8, renewal_horizon_days=90
        ),
        runs=[
            ScanRunRecord(
                account_id="ACC-1042",
                status="blocked",
                route="blocked",
                outcome=None,
                confidence=None,
                abstained=False,
                review_case_id=None,
                assessment_id=None,
                model_calls=0,
                tokens=0,
                latency_ms=1.0,
            )
        ],
    )
    summary = scan.summary()
    assert summary.blocked == 1
    assert summary.completed == 0
    assert summary.auto_released == 0
