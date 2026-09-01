"""Starting one assessment and watching it run (plan sections 19.1 and 19.2).

Three endpoints and one rule that shapes all of them: **nothing hidden is
served**. The stream carries `TraceEvent`s, which are redacted where they are
built (section 21.3), and the result projection carries the decision the graph
released -- outcome, distribution, confidence and its breakdown, drivers,
citations, counterevidence, limitations, and the human route with its reason.
There is no field here that a prompt or a chain of thought could reach.

`POST` returns as soon as the run is queued, because a run takes seconds and the
point of `GET .../events` is to watch it happen. A caller that only wants the
answer can poll `GET /api/assessments/{run_id}` instead; both read the same
record.
"""

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from meridian.api.dependencies import (
    RateLimited,
    RunManagerDependency,
    RuntimeDependency,
    SettingsDependency,
)
from meridian.api.errors import ApiError
from meridian.contracts import (
    MAX_QUESTION_CHARACTERS,
    AssessmentRequest,
    ForecastDecision,
    InsufficientEvidenceDecision,
    RequesterKind,
)
from meridian.data.repository import UnknownAccountError
from meridian.serving.limits import DemoModeError, enforce_demo_mode
from meridian.serving.runs import ServedRun

router = APIRouter(tags=["assessments"])

#: The default question, used when a caller supplies none and in demo mode.
DEFAULT_QUESTION = "What is the renewal outlook for this account, and what drives it?"


class StartAssessmentRequest(BaseModel):
    """What a caller may ask for."""

    account_id: str = Field(min_length=1, max_length=32)
    question: str = Field(default=DEFAULT_QUESTION, max_length=MAX_QUESTION_CHARACTERS)
    #: Typed as the contract's own literal, so an unknown role is a 422 from
    #: the request model rather than a cast that hides it until the graph runs.
    requester_role: RequesterKind = "csm"


class StartAssessmentResponse(BaseModel):
    """Where to watch the run that was just started."""

    run_id: str
    status: str
    account_id: str
    question: str
    events_url: str
    result_url: str


class AssessmentState(BaseModel):
    """A run's current or final projection (section 19.1)."""

    run_id: str
    account_id: str
    question: str
    status: str
    started_at: str
    finished_at: str | None = None
    events_emitted: int = 0
    last_event: str | None = None
    route: str | None = None
    error: str | None = None
    blocked: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    guardrails: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    assessment_id: str | None = None
    review_case_id: str | None = None
    total_tokens: int = 0
    model_calls: int = 0


def _state(served: ServedRun) -> AssessmentState:
    """Project one served run into the response contract."""

    state = AssessmentState(**served.snapshot())
    run = served.result
    if run is None:
        return state

    state.route = str(run.route) if run.route is not None else None
    state.assessment_id = run.assessment_id
    state.review_case_id = run.review_case_id
    state.total_tokens = run.total_tokens
    state.model_calls = run.model_calls
    state.guardrails = [decision.model_dump(mode="json") for decision in run.guardrails]
    state.trace = [event.model_dump(mode="json") for event in run.trace]
    if run.blocked is not None:
        state.blocked = run.blocked.model_dump(mode="json")
    if isinstance(run.result, ForecastDecision | InsufficientEvidenceDecision):
        state.decision = run.result.model_dump(mode="json")
    return state


@router.post(
    "/assessments",
    response_model=StartAssessmentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start one assessment",
)
def start_assessment(
    body: StartAssessmentRequest,
    runtime: RuntimeDependency,
    manager: RunManagerDependency,
    settings: SettingsDependency,
    _: RateLimited,
) -> StartAssessmentResponse:
    """Queue one graph run and return immediately.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` for an unknown account, or
            `REQUEST_BLOCKED` when demo mode or the request contract refuses it.
    """

    known = frozenset(runtime.repository.account_ids())
    try:
        question = enforce_demo_mode(settings, body.account_id, body.question, known)
    except DemoModeError as error:
        raise ApiError("REQUEST_BLOCKED", str(error)) from error

    try:
        runtime.repository.profile(body.account_id)
    except UnknownAccountError as error:
        raise ApiError(
            "ACCOUNT_NOT_FOUND", f"There is no account {body.account_id} in this portfolio."
        ) from error

    try:
        assessment = AssessmentRequest(
            account_id=body.account_id,
            question=question,
            requester_role=body.requester_role,
            mode="interactive",
        )
    except ValueError as error:
        # The request contract refuses path, URL, shell, and SQL shapes in the
        # one free-text field a caller controls. That is a blocked request, not
        # a server fault, and the caller is told which field.
        raise ApiError(
            "REQUEST_BLOCKED", "The request could not be accepted.", detail={"reason": str(error)}
        ) from error

    served = manager.start(assessment)
    return StartAssessmentResponse(
        run_id=served.run_id,
        status=served.status,
        account_id=assessment.account_id,
        question=assessment.question,
        events_url=f"/api/assessments/{served.run_id}/events",
        result_url=f"/api/assessments/{served.run_id}",
    )


@router.get(
    "/assessments/{run_id}",
    response_model=AssessmentState,
    summary="Current or final state of one run",
)
def read_assessment(run_id: str, manager: RunManagerDependency) -> AssessmentState:
    """Return one run's projection.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` when the run id is unknown or evicted.
    """

    served = manager.get(run_id)
    if served is None:
        raise ApiError(
            "ACCOUNT_NOT_FOUND",
            f"No run {run_id} is being tracked. Live runs are kept in memory and "
            "the oldest are evicted; a completed assessment is still in the account's history.",
            http_status=status.HTTP_404_NOT_FOUND,
        )
    return _state(served)


def _sse(event: str, payload: dict[str, Any]) -> str:
    """Frame one Server-Sent Event."""

    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.get(
    "/assessments/{run_id}/events",
    summary="Stream safe progress events for one run",
    response_class=StreamingResponse,
)
def stream_assessment(run_id: str, manager: RunManagerDependency) -> StreamingResponse:
    """Stream this run's trace events as SSE until it finishes.

    Every event is a `TraceEvent`, redacted at construction, so section 19.2's
    "do not stream hidden prompts or chain-of-thought" is a property of the type
    rather than of this function remembering to filter.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` when the run id is unknown.
    """

    served = manager.get(run_id)
    if served is None:
        raise ApiError(
            "ACCOUNT_NOT_FOUND",
            f"No run {run_id} is being tracked.",
            http_status=status.HTTP_404_NOT_FOUND,
        )

    def publish() -> Iterator[str]:
        """Yield SSE frames, with a keep-alive whenever the run goes quiet."""

        for event in manager.stream(run_id):
            if event is None:
                yield ": keep-alive\n\n"
                continue
            yield _sse(event.event, event.model_dump(mode="json"))
        final = manager.get(run_id)
        if final is not None:
            yield _sse("run_finished", _state(final).model_dump(mode="json"))

    return StreamingResponse(
        publish(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


__all__ = [
    "DEFAULT_QUESTION",
    "AssessmentState",
    "StartAssessmentRequest",
    "StartAssessmentResponse",
    "router",
]
