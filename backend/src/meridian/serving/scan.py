"""The autonomous portfolio scan (plan section 18).

Section 18 is careful about what "autonomous" means here, and so is this module:
the system chooses which accounts to assess and runs the whole graph on each
without a person picking tools or routes, and it takes **no action** on any
customer. Every scan output is advisory, and anything that is not green is
queued for a human rather than released.

Three bounds make the scan safe to run unattended, and the Phase 8 exit gate is
that none of them is exceeded:

* **Concurrency.** A fixed worker pool, sized by `scan_concurrency`. The graph
  is synchronous and its two evidence lanes already use threads, so the pool is
  the only place scan-level parallelism is introduced.
* **Model calls.** One budget shared across the whole scan, checked before each
  account starts. A scan that would exceed it stops starting new work rather
  than finishing at any price.
* **Size.** `scan_max_accounts` caps what a single request may ask for.

The budget is deliberately checked *before* dispatch and never mid-run: a run
that has already begun is allowed to finish, because abandoning it halfway
would leave a half-written assessment and no review case.
"""

import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from meridian.contracts import (
    AssessmentRequest,
    ForecastDecision,
    TraceEvent,
)
from meridian.data.repository import RuntimeRepository
from meridian.graph import AssessmentRun, build_graph, run_assessment
from meridian.graph.runtime import GraphRuntime
from meridian.guardrails.runtime import MAX_MODEL_CALLS
from meridian.settings import Settings, get_settings

#: The question every scanned account is assessed against. Held constant so a
#: scan summary compares like with like; an operator asking a different question
#: is doing an interactive assessment, not a scan.
SCAN_QUESTION = "What is the renewal outlook for this account, and what drives it?"

#: Outcomes that make an account a risk in the summary (section 18.1).
RISK_OUTCOMES: frozenset[str] = frozenset({"Churned", "Contracted"})

#: Outcomes that make an account an expansion candidate.
EXPANSION_OUTCOMES: frozenset[str] = frozenset({"Expanded"})

#: Routes that reach a user without a person looking first.
AUTO_RELEASED_ROUTES: frozenset[str] = frozenset({"green"})

ScanStatus = Literal["running", "completed", "failed"]


@dataclass(frozen=True)
class ScanRequest:
    """What one scan was asked to do."""

    account_ids: tuple[str, ...]
    concurrency: int
    model_call_budget: int
    renewal_horizon_days: int
    requester_role: str = "cs_leader"


@dataclass(frozen=True)
class ScanRunRecord:
    """One account's result, reduced to what a portfolio summary needs."""

    account_id: str
    status: Literal["completed", "blocked", "failed"]
    route: str | None
    outcome: str | None
    confidence: float | None
    abstained: bool
    review_case_id: str | None
    assessment_id: str | None
    model_calls: int
    tokens: int
    latency_ms: float
    error: str | None = None

    @property
    def auto_released(self) -> bool:
        """Return whether this answer reached a user without human review."""

        return self.status == "completed" and self.route in AUTO_RELEASED_ROUTES


@dataclass(frozen=True)
class ScanSummary:
    """The portfolio picture section 18.1 asks a scan to produce."""

    scanned: int
    completed: int
    failed: int
    blocked: int
    auto_released: int
    queued_for_review: int
    abstentions: int
    risk_accounts: tuple[str, ...]
    expansion_candidates: tuple[str, ...]
    review_load: dict[str, int]
    total_model_calls: int
    total_tokens: int
    budget_exhausted: bool
    concurrency_observed: int

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""

        return {
            "scanned": self.scanned,
            "completed": self.completed,
            "failed": self.failed,
            "blocked": self.blocked,
            "auto_released": self.auto_released,
            "queued_for_review": self.queued_for_review,
            "abstentions": self.abstentions,
            "risk_accounts": list(self.risk_accounts),
            "expansion_candidates": list(self.expansion_candidates),
            "review_load": dict(self.review_load),
            "total_model_calls": self.total_model_calls,
            "total_tokens": self.total_tokens,
            "budget_exhausted": self.budget_exhausted,
            "concurrency_observed": self.concurrency_observed,
        }


@dataclass
class PortfolioScan:
    """One scan: what it was asked for, what it has done, and what it found."""

    scan_id: str
    request: ScanRequest
    status: ScanStatus = "running"
    started_at: str = ""
    finished_at: str | None = None
    runs: list[ScanRunRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    budget_exhausted: bool = False
    peak_concurrency: int = 0
    error: str | None = None

    def summary(self) -> ScanSummary:
        """Return the portfolio summary over the runs completed so far."""

        completed = [record for record in self.runs if record.status == "completed"]
        review_load: dict[str, int] = {}
        for record in self.runs:
            if record.route is not None and record.route not in AUTO_RELEASED_ROUTES:
                review_load[record.route] = review_load.get(record.route, 0) + 1
        return ScanSummary(
            scanned=len(self.runs),
            completed=len(completed),
            failed=sum(1 for record in self.runs if record.status == "failed"),
            blocked=sum(1 for record in self.runs if record.status == "blocked"),
            auto_released=sum(1 for record in self.runs if record.auto_released),
            queued_for_review=sum(record.review_case_id is not None for record in self.runs),
            abstentions=sum(1 for record in completed if record.abstained),
            risk_accounts=tuple(
                record.account_id for record in completed if record.outcome in RISK_OUTCOMES
            ),
            expansion_candidates=tuple(
                record.account_id for record in completed if record.outcome in EXPANSION_OUTCOMES
            ),
            review_load=dict(sorted(review_load.items())),
            total_model_calls=sum(record.model_calls for record in self.runs),
            total_tokens=sum(record.tokens for record in self.runs),
            budget_exhausted=self.budget_exhausted,
            concurrency_observed=self.peak_concurrency,
        )


def eligible_accounts(
    repository: RuntimeRepository,
    horizon_days: int,
    as_of: date | None = None,
    limit: int | None = None,
) -> tuple[str, ...]:
    """Return accounts whose renewal falls inside the horizon (section 18.1).

    Args:
        repository: The runtime repository.
        horizon_days: How far ahead of the reference date to look.
        as_of: The reference date. Defaults to each account's own forecast date,
            which is what makes a scan reproducible on a fixed synthetic
            dataset: a wall-clock "today" would select a different portfolio
            every day against data that never moves.
        limit: Cap on how many accounts to return, applied after sorting.

    Returns:
        Eligible account ids, ordered by renewal date then id, so two scans of
        the same portfolio queue the same work in the same order.
    """

    eligible: list[tuple[date, str]] = []
    for account_id in repository.account_ids():
        profile = repository.profile(account_id)
        reference = as_of if as_of is not None else profile.forecast_as_of_date
        days_out = (profile.renewal_date - reference).days
        if 0 <= days_out <= horizon_days:
            eligible.append((profile.renewal_date, account_id))
    ordered = tuple(account_id for _, account_id in sorted(eligible))
    return ordered[:limit] if limit is not None else ordered


def _record(account_id: str, run: AssessmentRun, latency_ms: float) -> ScanRunRecord:
    """Reduce one finished run to a scan record."""

    if run.blocked is not None:
        return ScanRunRecord(
            account_id=account_id,
            status="blocked",
            route="blocked",
            outcome=None,
            confidence=None,
            abstained=False,
            review_case_id=None,
            assessment_id=None,
            model_calls=run.model_calls,
            tokens=run.total_tokens,
            latency_ms=latency_ms,
        )
    forecast = run.result if isinstance(run.result, ForecastDecision) else None
    return ScanRunRecord(
        account_id=account_id,
        status="completed" if run.result is not None else "failed",
        route=str(run.route) if run.route is not None else None,
        outcome=forecast.outcome if forecast is not None else None,
        confidence=forecast.confidence if forecast is not None else None,
        abstained=run.abstained,
        review_case_id=run.review_case_id,
        assessment_id=run.assessment_id,
        model_calls=run.model_calls,
        tokens=run.total_tokens,
        latency_ms=latency_ms,
        error=None if run.result is not None else "the run produced no result",
    )


class _ConcurrencyMeter:
    """Count how many runs are actually in flight at once.

    The exit gate is that a scan does not exceed its configured concurrency, and
    the honest way to show that is to measure it rather than to point at the
    pool's `max_workers`. A pool could be resized, or work could be dispatched
    outside it; a counter incremented by the work itself cannot be fooled by
    either.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self.peak = 0

    def __enter__(self) -> "_ConcurrencyMeter":
        with self._lock:
            self._active += 1
            self.peak = max(self.peak, self._active)
        return self

    def __exit__(self, *_: object) -> None:
        with self._lock:
            self._active -= 1


def run_portfolio_scan(
    runtime: GraphRuntime,
    account_ids: Sequence[str],
    settings: Settings | None = None,
    scan_id: str | None = None,
    on_event: Callable[[str, TraceEvent], None] | None = None,
    concurrency: int | None = None,
    model_call_budget: int | None = None,
) -> PortfolioScan:
    """Assess many accounts under fixed concurrency and a shared spend budget.

    Args:
        runtime: The assembled graph runtime.
        account_ids: The accounts to scan, already selected and capped.
        settings: Runtime configuration; read from the environment when absent.
        scan_id: Identifier for this scan; generated when omitted.
        on_event: Called with `(account_id, event)` for every trace event any
            run produces, so a caller can stream a scan the way it streams a
            single assessment.
        concurrency: Overrides `settings.scan_concurrency`.
        model_call_budget: Overrides `settings.scan_model_call_budget`.

    Returns:
        The finished scan, including every account's record and the summary.
    """

    resolved = settings if settings is not None else get_settings()
    workers = concurrency if concurrency is not None else resolved.scan_concurrency
    budget = model_call_budget if model_call_budget is not None else resolved.scan_model_call_budget
    scan = PortfolioScan(
        scan_id=scan_id or f"SCAN-{uuid.uuid4().hex[:12]}",
        request=ScanRequest(
            account_ids=tuple(account_ids),
            concurrency=workers,
            model_call_budget=budget,
            renewal_horizon_days=resolved.scan_renewal_horizon_days,
        ),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    graph = build_graph(runtime)
    meter = _ConcurrencyMeter()
    spend_lock = threading.Lock()
    spent = 0

    def assess(account_id: str) -> ScanRunRecord:
        """Run one account, measuring how many run at once."""

        with meter:
            started = time.perf_counter()
            request = AssessmentRequest(
                account_id=account_id,
                question=SCAN_QUESTION,
                requester_role="cs_leader",
                mode="portfolio_scan",
            )
            run = run_assessment(
                graph,
                request,
                run_id=f"{scan.scan_id}-{account_id}",
                on_event=(
                    (lambda event: on_event(account_id, event)) if on_event is not None else None
                ),
            )
            return _record(account_id, run, (time.perf_counter() - started) * 1000)

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scan") as pool:
            pending: list[tuple[str, Future[ScanRunRecord]]] = []
            for account_id in scan.request.account_ids:
                with spend_lock:
                    if spent >= budget:
                        scan.budget_exhausted = True
                        scan.skipped.append(account_id)
                        continue
                    # Reserve the largest a single run may cost before starting
                    # it. Reserving after the fact would let every worker pass
                    # the check at once and overspend by the pool's width.
                    spent += MAX_MODEL_CALLS
                pending.append((account_id, pool.submit(assess, account_id)))

            for account_id, future in pending:
                try:
                    record = future.result()
                except Exception as error:  # one account must not end the scan
                    record = ScanRunRecord(
                        account_id=account_id,
                        status="failed",
                        route=None,
                        outcome=None,
                        confidence=None,
                        abstained=False,
                        review_case_id=None,
                        assessment_id=None,
                        model_calls=0,
                        tokens=0,
                        latency_ms=0.0,
                        error=f"{type(error).__name__}: {error}",
                    )
                scan.runs.append(record)
                with spend_lock:
                    # Give back what this run did not spend, so a scan of cheap
                    # deterministic runs is not throttled by a reservation the
                    # runs never used.
                    spent -= MAX_MODEL_CALLS - min(record.model_calls, MAX_MODEL_CALLS)
    except Exception as error:  # pragma: no cover - pool failures are not reachable in tests
        scan.status = "failed"
        scan.error = f"{type(error).__name__}: {error}"
        scan.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        return scan

    scan.peak_concurrency = meter.peak
    scan.status = "completed"
    scan.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    return scan


__all__ = [
    "AUTO_RELEASED_ROUTES",
    "EXPANSION_OUTCOMES",
    "RISK_OUTCOMES",
    "SCAN_QUESTION",
    "PortfolioScan",
    "ScanRequest",
    "ScanRunRecord",
    "ScanSummary",
    "eligible_accounts",
    "run_portfolio_scan",
]
