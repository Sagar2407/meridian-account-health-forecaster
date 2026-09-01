"""The optional scheduled scan worker (plan section 18.2).

Section 18.2 allows "an optional scheduled worker controlled by
`ENABLE_SCHEDULER` and cron configuration", and then adds the sentence that
matters more: "Disable unattended scheduled LLM spending in the public
deployment by default."

So the worker is off unless two independent conditions hold -- the flag is on
*and* demo mode is off -- and it refuses to start rather than starting quietly
in a reduced form. A scheduler that silently downgrades itself is worse than one
that will not start: the operator believes scans are happening.

It is a plain daemon thread on an interval, not cron and not a task queue. The
deployment is one small container, the job is idempotent, and a missed tick
costs nothing: the next one reassesses the same portfolio from the same
immutable data.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from meridian.graph.runtime import GraphRuntime
from meridian.serving.scan import PortfolioScan, eligible_accounts, run_portfolio_scan
from meridian.settings import Settings

logger = logging.getLogger("meridian.scheduler")


class SchedulerNotPermittedError(RuntimeError):
    """Raised when a scheduled scan is asked for where it must not run."""


@dataclass
class ScanScheduler:
    """Run a bounded portfolio scan on an interval, or refuse to.

    Attributes:
        runtime: The assembled graph runtime.
        settings: Runtime configuration. Both `enable_scheduler` and the absence
            of `demo_mode` are required.
        on_scan: Called with each finished scan, so a caller can record it.
    """

    runtime: GraphRuntime
    settings: Settings
    on_scan: Callable[[PortfolioScan], None] | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    scans_run: int = 0
    last_started_at: str | None = None

    @property
    def interval_seconds(self) -> float:
        """Return the configured interval, in seconds."""

        return self.settings.scheduler_interval_minutes * 60.0

    def run_once(self) -> PortfolioScan:
        """Run one scheduled scan now.

        Raises:
            SchedulerNotPermittedError: If unattended spending is not permitted
                here. The check is repeated per tick rather than only at start,
                so a configuration reload cannot leave a running scheduler
                spending in a mode that forbids it.
        """

        if not self.settings.scheduler_is_permitted:
            raise SchedulerNotPermittedError(
                "a scheduled scan needs enable_scheduler=true and demo_mode=false; "
                "section 24.3 disables unattended spending in the public deployment"
            )
        selected = eligible_accounts(
            self.runtime.repository,
            self.settings.scan_renewal_horizon_days,
            limit=self.settings.scan_max_accounts,
        )
        self.last_started_at = datetime.now(UTC).isoformat(timespec="seconds")
        logger.info("scheduled scan starting over %d accounts", len(selected))
        scan = run_portfolio_scan(self.runtime, selected, settings=self.settings)
        self.scans_run += 1
        if self.on_scan is not None:
            self.on_scan(scan)
        summary = scan.summary()
        logger.info(
            "scheduled scan %s finished: %d scanned, %d queued for review, %d model calls",
            scan.scan_id,
            summary.scanned,
            summary.queued_for_review,
            summary.total_model_calls,
        )
        return scan

    def start(self) -> None:
        """Start the interval thread.

        Raises:
            SchedulerNotPermittedError: If unattended spending is not permitted.
        """

        if not self.settings.scheduler_is_permitted:
            # Naming both settings, because "disabled" alone leaves an operator
            # guessing which of the two is holding it off.
            raise SchedulerNotPermittedError(
                "the scheduler will not start: enable_scheduler="
                f"{self.settings.enable_scheduler}, demo_mode={self.settings.demo_mode}; "
                "it needs enable_scheduler=true and demo_mode=false (plan section 24.3)"
            )
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scan-scheduler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        """Scan on the interval until stopped."""

        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                # An unattended worker that dies on one bad tick stops scanning
                # silently, which is the failure mode a schedule exists to avoid.
                logger.exception("scheduled scan failed; the next tick will retry")
            self._stop.wait(self.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the interval thread."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None


__all__ = ["ScanScheduler", "SchedulerNotPermittedError"]
