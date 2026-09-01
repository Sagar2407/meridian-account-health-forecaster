"""The curated demo runs (plan sections 24.3 and 24.5).

Section 24.5 asks the landing page to offer three curated demo buttons, and
section 24.3 says that when the live budget is unavailable the demo must "show a
clearly labeled cached run rather than pretending it is live".

Both endpoints here return recorded runs and say so in the payload itself:
`is_cached` is always true and `cached_note` explains what a visitor is looking
at. There is deliberately no flag that turns the label off. A demo that can be
made to look live is a demo that will eventually be shown as live.
"""

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from meridian.api.errors import ApiError
from meridian.serving.demo import CURATED_KINDS, load_cache

router = APIRouter(tags=["demo"])


class CuratedRunSummary(BaseModel):
    """One curated run, without its full state."""

    kind: str
    label: str
    account_id: str
    question: str
    route: str
    recorded_at: str
    commit: str
    is_cached: bool = True


class CuratedRun(BaseModel):
    """One curated run and the recorded state a page renders."""

    kind: str
    label: str
    account_id: str
    question: str
    route: str
    recorded_at: str
    commit: str
    is_cached: bool = True
    cached_note: str
    state: dict[str, Any]


@router.get(
    "/demo-runs",
    response_model=list[CuratedRunSummary],
    summary="The curated runs this deployment can replay",
)
def list_demo_runs() -> list[CuratedRunSummary]:
    """Return what is cached, in the order a visitor should meet it.

    An empty list is a valid answer and means this deployment has no cache, so
    the page should offer live runs instead. It is not an error: a missing
    cache degrades to the real thing, which is the better failure.
    """

    cache = load_cache()
    return [
        CuratedRunSummary(
            kind=run.kind,
            label=run.label,
            account_id=run.account_id,
            question=run.question,
            route=run.route,
            recorded_at=run.recorded_at,
            commit=run.commit,
        )
        for kind in CURATED_KINDS
        if (run := cache.get(kind)) is not None
    ]


@router.get(
    "/demo-runs/{kind}",
    response_model=CuratedRun,
    summary="One curated run, clearly marked as recorded",
)
def read_demo_run(kind: str) -> CuratedRun:
    """Return one recorded run.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` when this deployment has no run of that
            kind cached.
    """

    run = load_cache().get(kind)
    if run is None:
        raise ApiError(
            "ACCOUNT_NOT_FOUND",
            f"No curated run of kind {kind!r} is cached in this deployment. "
            f"Cached kinds: {sorted(load_cache())}.",
            http_status=status.HTTP_404_NOT_FOUND,
        )
    return CuratedRun(**run.as_dict())


__all__ = ["CuratedRun", "CuratedRunSummary", "router"]
