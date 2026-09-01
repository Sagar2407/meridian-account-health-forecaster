"""The autonomous portfolio scan over HTTP (plan sections 18 and 19.1).

Two endpoints. `POST` selects eligible accounts, caps what was asked for, and
runs the scan on a background thread; `GET` returns the summary section 18.1
specifies. The scan itself lives in `meridian.serving.scan`, so the CLI and the
optional scheduled worker drive exactly this code path rather than a parallel
one that could bound concurrency differently.

Section 24.3 disables unattended spending in a public deployment, and demo mode
therefore refuses to start a scan at all: a scan is the one request here that
can cost many model calls from a single unauthenticated click.
"""

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from meridian.api.dependencies import (
    RateLimited,
    RuntimeDependency,
    SettingsDependency,
    get_scan,
    register_scan,
)
from meridian.api.errors import ApiError
from meridian.serving.scan import (
    PortfolioScan,
    ScanRequest,
    eligible_accounts,
    run_portfolio_scan,
)

router = APIRouter(tags=["portfolio"])


class StartScanRequest(BaseModel):
    """What a scan may be asked to cover."""

    #: Explicit accounts to scan. When empty, eligibility is computed from the
    #: renewal horizon, which is the autonomous behaviour section 18.1 describes.
    account_ids: tuple[str, ...] = ()
    renewal_horizon_days: int | None = Field(default=None, ge=1, le=730)
    max_accounts: int | None = Field(default=None, ge=1, le=500)
    concurrency: int | None = Field(default=None, ge=1, le=32)


class ScanRunView(BaseModel):
    """One account's outcome inside a scan."""

    account_id: str
    status: str
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


class ScanView(BaseModel):
    """A scan's status, summary, and per-account results."""

    scan_id: str
    status: str
    started_at: str
    finished_at: str | None
    requested_accounts: int
    concurrency_limit: int
    model_call_budget: int
    summary: dict[str, Any]
    runs: list[ScanRunView]
    skipped: list[str]
    error: str | None = None


def _view(scan: PortfolioScan) -> ScanView:
    """Project a scan into the response contract."""

    return ScanView(
        scan_id=scan.scan_id,
        status=scan.status,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        requested_accounts=len(scan.request.account_ids),
        concurrency_limit=scan.request.concurrency,
        model_call_budget=scan.request.model_call_budget,
        summary=scan.summary().as_dict(),
        runs=[ScanRunView(**record.__dict__) for record in scan.runs],
        skipped=list(scan.skipped),
        error=scan.error,
    )


@router.post(
    "/portfolio-scans",
    response_model=ScanView,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a bounded portfolio scan",
)
def start_scan(
    body: StartScanRequest,
    runtime: RuntimeDependency,
    settings: SettingsDependency,
    _: RateLimited,
) -> ScanView:
    """Select eligible accounts and scan them under fixed bounds.

    Raises:
        ApiError: `REQUEST_BLOCKED` in demo mode, or when nothing is eligible.
    """

    if settings.demo_mode:
        raise ApiError(
            "REQUEST_BLOCKED",
            "The public demo does not start portfolio scans. A scan can spend many "
            "model calls from one click, so it is an operator action.",
        )

    horizon = body.renewal_horizon_days or settings.scan_renewal_horizon_days
    cap = min(body.max_accounts or settings.scan_max_accounts, settings.scan_max_accounts)

    if body.account_ids:
        known = frozenset(runtime.repository.account_ids())
        unknown = sorted(set(body.account_ids) - known)
        if unknown:
            raise ApiError(
                "ACCOUNT_NOT_FOUND",
                f"These accounts are not in the portfolio: {unknown[:5]}",
            )
        selected = tuple(body.account_ids)[:cap]
    else:
        selected = eligible_accounts(runtime.repository, horizon, limit=cap)

    if not selected:
        raise ApiError(
            "REQUEST_BLOCKED",
            f"No account renews within {horizon} days, so there is nothing to scan.",
        )

    concurrency = body.concurrency or settings.scan_concurrency
    pending = PortfolioScan(
        scan_id=f"SCAN-{uuid.uuid4().hex[:12]}",
        request=ScanRequest(
            account_ids=selected,
            concurrency=concurrency,
            model_call_budget=settings.scan_model_call_budget,
            renewal_horizon_days=horizon,
        ),
        started_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    register_scan(pending)

    def execute() -> None:
        """Run the scan, replacing the pending record with the finished one.

        The pending record is registered first so that a `GET` issued
        immediately after the `POST` finds a running scan rather than a 404.
        Re-registering under the same id is what makes the two records one scan
        from a caller's point of view.
        """

        finished = run_portfolio_scan(
            runtime,
            selected,
            settings=settings,
            scan_id=pending.scan_id,
            concurrency=body.concurrency,
        )
        register_scan(finished)

    threading.Thread(target=execute, name=f"scan-{pending.scan_id}", daemon=True).start()
    return _view(pending)


@router.get(
    "/portfolio-scans/{scan_id}",
    response_model=ScanView,
    summary="Scan summary and per-account statuses",
)
def read_scan(scan_id: str) -> ScanView:
    """Return one scan.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` when the scan id is unknown or evicted.
    """

    scan = get_scan(scan_id)
    if scan is None:
        raise ApiError(
            "ACCOUNT_NOT_FOUND",
            f"No scan {scan_id} is being tracked.",
            http_status=status.HTTP_404_NOT_FOUND,
        )
    return _view(scan)


__all__ = ["ScanRunView", "ScanView", "StartScanRequest", "router"]
