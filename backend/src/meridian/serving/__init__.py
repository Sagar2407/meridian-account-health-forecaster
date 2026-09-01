"""Serving concerns: running assessments for callers, and scanning a portfolio.

Plan sections 18 and 19. The graph itself knows nothing about HTTP, threads, or
rate limits; this package is where one run becomes a served run and where many
runs become a bounded scan. Keeping it separate from `meridian.api` means the
CLI and the scheduled worker drive exactly the same code the HTTP routes do.
"""

from meridian.serving.limits import RateLimiter, enforce_demo_mode
from meridian.serving.runs import RunManager, ServedRun
from meridian.serving.scan import (
    PortfolioScan,
    ScanRequest,
    ScanSummary,
    eligible_accounts,
    run_portfolio_scan,
)
from meridian.serving.scheduler import ScanScheduler, SchedulerNotPermittedError

__all__ = [
    "PortfolioScan",
    "RateLimiter",
    "RunManager",
    "ScanRequest",
    "ScanScheduler",
    "ScanSummary",
    "SchedulerNotPermittedError",
    "ServedRun",
    "eligible_accounts",
    "enforce_demo_mode",
    "run_portfolio_scan",
]
