"""Process-wide serving dependencies (plan sections 18, 19, and 24.3).

One graph runtime, one run manager, one rate limiter, and one scan registry per
process. They are built lazily and cached, because assembling a runtime loads
the forecaster and can build the retrieval index, which is seconds of work no
health check should pay for and no import should trigger.

Every one is exposed as a FastAPI dependency rather than as a module global that
routes reach for directly, so a test can replace any of them through
`app.dependency_overrides` without touching process state.
"""

import threading
from collections import OrderedDict
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from meridian.api.errors import ApiError
from meridian.graph.runtime import GraphRuntime
from meridian.serving.limits import RateLimiter, RateLimitExceededError
from meridian.serving.runs import RunManager
from meridian.serving.scan import PortfolioScan
from meridian.settings import Settings, get_settings

#: How many finished scans stay readable. A scan summary is small, and a demo
#: needs only the recent ones; the assessments themselves are in the store.
MAX_RETAINED_SCANS = 50

_scan_lock = threading.Lock()
_scans: OrderedDict[str, PortfolioScan] = OrderedDict()


@lru_cache(maxsize=1)
def get_runtime() -> GraphRuntime:
    """Return the process's graph runtime, assembling it on first use."""

    return GraphRuntime.build()


@lru_cache(maxsize=1)
def get_run_manager() -> RunManager:
    """Return the process's run manager."""

    return RunManager(get_runtime(), max_workers=get_settings().scan_concurrency)


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    """Return the process's rate limiter."""

    return RateLimiter.from_settings(get_settings())


def register_scan(scan: PortfolioScan) -> None:
    """Keep a finished or running scan readable, evicting the oldest."""

    with _scan_lock:
        _scans[scan.scan_id] = scan
        while len(_scans) > MAX_RETAINED_SCANS:
            _scans.popitem(last=False)


def get_scan(scan_id: str) -> PortfolioScan | None:
    """Return one registered scan, or None."""

    with _scan_lock:
        return _scans.get(scan_id)


def client_key(request: Request) -> str:
    """Return a stable identifier for the caller.

    The peer address, which behind a proxy is the proxy. That is a known
    weakness of counting this way and is not papered over with a
    `X-Forwarded-For` header, because an unauthenticated caller can set that
    header to anything and would then have an unlimited allowance.
    """

    return request.client.host if request.client is not None else "unknown"


def enforce_rate_limit(
    request: Request, limiter: Annotated[RateLimiter, Depends(get_rate_limiter)]
) -> None:
    """Charge one run against the caller's allowance, or refuse it.

    The limiter arrives as a dependency rather than being read from the module
    cache, so `app.dependency_overrides` can reach it. A control that cannot be
    substituted cannot be tested, and an untested rate limit is an assumption.

    Raises:
        ApiError: `REQUEST_BLOCKED` with a `Retry-After` hint in the detail.
    """

    try:
        limiter.check(client_key(request))
    except RateLimitExceededError as error:
        raise ApiError(
            "REQUEST_BLOCKED",
            str(error),
            http_status=429,
            detail={"retry_after_seconds": round(error.retry_after_seconds, 1)},
        ) from error


SettingsDependency = Annotated[Settings, Depends(get_settings)]
RuntimeDependency = Annotated[GraphRuntime, Depends(get_runtime)]
RunManagerDependency = Annotated[RunManager, Depends(get_run_manager)]
RateLimited = Annotated[None, Depends(enforce_rate_limit)]


__all__ = [
    "MAX_RETAINED_SCANS",
    "RateLimited",
    "RunManagerDependency",
    "RuntimeDependency",
    "SettingsDependency",
    "client_key",
    "enforce_rate_limit",
    "get_rate_limiter",
    "get_run_manager",
    "get_runtime",
    "get_scan",
    "register_scan",
]
