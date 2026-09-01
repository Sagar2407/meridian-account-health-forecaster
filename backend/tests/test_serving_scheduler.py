"""The optional scheduled scan worker (plan sections 18.2 and 24.3).

The rule these tests exist for is not "does the timer fire" -- it is that the
worker will not spend money unattended where the plan forbids it, and that it
refuses loudly rather than starting in a quiet reduced form.
"""

import pytest

from meridian.data.repository import RuntimeRepository
from meridian.graph.runtime import GraphRuntime
from meridian.memory.store import AssessmentStore
from meridian.model.artifacts import ModelArtifact
from meridian.serving.scan import PortfolioScan
from meridian.serving.scheduler import ScanScheduler, SchedulerNotPermittedError
from meridian.settings import Settings
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolServices
from stub_encoder import build_stub_service

pytestmark = pytest.mark.requires_dataset


@pytest.fixture(scope="module")
def scheduled_runtime(
    runtime: RuntimeRepository,
    forecaster_artifact: ModelArtifact,
    tmp_path_factory: pytest.TempPathFactory,
) -> GraphRuntime:
    """Assemble an offline runtime over a small indexed slice."""

    accounts = runtime.account_ids()[:4]
    directory = tmp_path_factory.mktemp("sched-index")
    service = build_stub_service(runtime, directory, accounts)
    store = AssessmentStore(tmp_path_factory.mktemp("sched-memory") / "assessments.sqlite")
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


def test_the_scheduler_is_off_unless_it_is_switched_on(
    scheduled_runtime: GraphRuntime,
) -> None:
    """Unattended spending is opt-in, and the default is off."""

    scheduler = ScanScheduler(scheduled_runtime, _settings())

    with pytest.raises(SchedulerNotPermittedError):
        scheduler.start()
    with pytest.raises(SchedulerNotPermittedError):
        scheduler.run_once()
    assert scheduler.scans_run == 0


def test_demo_mode_overrides_the_flag_rather_than_being_overridden(
    scheduled_runtime: GraphRuntime,
) -> None:
    """Section 24.3: no unattended scheduled spending in the public deployment.

    Setting the flag must not be enough. A deployment that turned the scheduler
    on and forgot demo mode would otherwise scan the whole portfolio on a timer
    against a public budget.
    """

    scheduler = ScanScheduler(scheduled_runtime, _settings(enable_scheduler=True, demo_mode=True))

    with pytest.raises(SchedulerNotPermittedError, match="demo_mode"):
        scheduler.start()


def test_a_permitted_scheduler_runs_a_bounded_scan(
    scheduled_runtime: GraphRuntime,
) -> None:
    """One tick, run directly, so the test does not wait on a timer."""

    scans: list[PortfolioScan] = []
    scheduler = ScanScheduler(
        scheduled_runtime,
        _settings(enable_scheduler=True, scan_max_accounts=3, scan_concurrency=2),
        on_scan=scans.append,
    )

    scan = scheduler.run_once()

    assert scan.status == "completed"
    assert scheduler.scans_run == 1
    assert scheduler.last_started_at
    assert scans == [scan]
    assert 0 < scan.peak_concurrency <= 2
    assert scan.summary().total_model_calls == 0


def test_the_interval_is_configuration_not_a_constant(
    scheduled_runtime: GraphRuntime,
) -> None:
    """An operator has to be able to slow an unattended job down."""

    scheduler = ScanScheduler(scheduled_runtime, _settings(scheduler_interval_minutes=90))

    assert scheduler.interval_seconds == 5_400.0
