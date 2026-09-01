"""The human-review queue (plan section 16.6).

Section 16.6 asks for a decision card, four reviewer actions, and reason codes
stored as regression metadata. This router is the HTTP face of exactly that and
of nothing else: it reads and writes application memory, never the source data,
and it cannot run an assessment. A reviewer changing a released answer is a
consequential write, so it goes through `ReviewerDecision`, whose validators
refuse an override with no reason code or note before a row is touched.

Phase 8 owns the rest of the API. This is here in Phase 7 because the review
queue is a Phase 7 deliverable and because the exit gate -- "reviewer override
creates a traceable regression record" -- is only demonstrable end to end if a
reviewer has somewhere to act.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from meridian.contracts import RequestedData, ReviewAction, ReviewerDecision, ReviewReasonCode
from meridian.memory.store import (
    MAX_QUEUE_LIMIT,
    AssessmentStore,
    AssessmentStoreError,
    RegressionCase,
    ReviewCase,
)

router = APIRouter(tags=["review"])


def get_store() -> AssessmentStore:
    """Return the application-memory store.

    A dependency rather than a module global so a test can point the queue at a
    temporary database with `app.dependency_overrides`, and so a future phase
    can swap the backing store without touching the routes.
    """

    return AssessmentStore()


StoreDependency = Annotated[AssessmentStore, Depends(get_store)]


class ReviewCaseSummary(BaseModel):
    """One row of the queue."""

    case_id: str
    assessment_id: str
    account_id: str
    created_at: str
    reason: str
    status: str
    route: str
    reason_codes: tuple[str, ...] = ()
    resolved_at: str | None = None
    reviewer: str | None = None
    action: str | None = None
    reason_code: str | None = None
    note: str | None = None
    corrected_outcome: str | None = None
    requested_data: tuple[RequestedData, ...] = ()

    @classmethod
    def of(cls, case: ReviewCase) -> "ReviewCaseSummary":
        """Return the API view of a stored case."""

        return cls(
            case_id=case.case_id,
            assessment_id=case.assessment_id,
            account_id=case.account_id,
            created_at=case.created_at,
            reason=case.reason,
            status=case.status,
            route=case.route,
            reason_codes=case.reason_codes,
            resolved_at=case.resolved_at,
            reviewer=case.reviewer,
            action=case.action,
            reason_code=case.reason_code,
            note=case.note,
            corrected_outcome=case.corrected_outcome,
            requested_data=case.requested_data,
        )


class ReviewCard(BaseModel):
    """What a reviewer is shown before they decide (plan section 16.6).

    The card is the stored decision, not a re-derivation of it. A queue that
    recomputed the answer would show the reviewer something the system never
    released, which is the one thing a review record must not do.
    """

    case: ReviewCaseSummary
    question: str
    cutoff: str
    kind: str
    proposed_outcome: str
    confidence: float
    decision: dict[str, object] = Field(default_factory=dict)


class RegressionCaseView(BaseModel):
    """One exported regression record (plan section 21.4)."""

    regression_id: str
    case_id: str | None
    assessment_id: str | None
    account_id: str
    created_at: str
    origin: str
    cutoff: str
    question: str
    system_outcome: str
    reviewer_outcome: str | None
    reason_code: str
    note: str
    confidence: float
    route: str

    @classmethod
    def of(cls, case: RegressionCase) -> "RegressionCaseView":
        """Return the API view of a stored regression record."""

        return cls(**case.as_dict())


class ReviewDecisionRequest(BaseModel):
    """A reviewer's action, as it arrives over HTTP.

    The case id comes from the path, so it is deliberately absent here: a body
    that could name a different case than the URL is a way to resolve the wrong
    one by accident.
    """

    reviewer: str = Field(min_length=1, max_length=120)
    action: ReviewAction
    reason_code: ReviewReasonCode = "other"
    note: str = Field(default="", max_length=1_000)
    corrected_outcome: str | None = None
    requested_data: tuple[RequestedData, ...] = ()


class ReviewDecisionResponse(BaseModel):
    """What the queue returns once a case is resolved."""

    case: ReviewCaseSummary
    regression: RegressionCaseView | None = None


@router.get(
    "/review-cases",
    response_model=list[ReviewCaseSummary],
    summary="The human-review queue",
)
def list_cases(
    store: StoreDependency,
    case_status: Annotated[Literal["open", "resolved", "all"], Query(alias="status")] = "open",
    limit: Annotated[int, Query(ge=1, le=MAX_QUEUE_LIMIT)] = 50,
) -> list[ReviewCaseSummary]:
    """Return red cases waiting for a person, newest first."""

    return [ReviewCaseSummary.of(case) for case in store.review_queue(case_status, limit)]


@router.get(
    "/review-cases/{case_id}",
    response_model=ReviewCard,
    summary="One decision card",
)
def read_case(case_id: str, store: StoreDependency) -> ReviewCard:
    """Return the decision a reviewer is being asked about."""

    case = store.review_case(case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no review case {case_id}")
    record = store.assessment(case.assessment_id)
    if record is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"review case {case_id} refers to assessment {case.assessment_id}, which is missing",
        )
    return ReviewCard(
        case=ReviewCaseSummary.of(case),
        question=record.question,
        cutoff=record.cutoff.isoformat(),
        kind=record.kind,
        proposed_outcome=record.predicted_outcome,
        confidence=record.confidence,
        decision=record.card,
    )


@router.post(
    "/review-cases/{case_id}/decision",
    response_model=ReviewDecisionResponse,
    summary="Resolve one case with a typed reviewer action",
)
def decide(
    case_id: str, request: ReviewDecisionRequest, store: StoreDependency
) -> ReviewDecisionResponse:
    """Apply a reviewer's action and return the regression record it created.

    Raises:
        HTTPException: 404 if the case does not exist, 409 if it is already
            resolved, and 422 if the action is not a valid one.
    """

    try:
        decision = ReviewerDecision(
            case_id=case_id,
            reviewer=request.reviewer,
            action=request.action,
            reason_code=request.reason_code,
            note=request.note,
            corrected_outcome=request.corrected_outcome,
            requested_data=request.requested_data,
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error

    try:
        case, regression = store.resolve_review_case(decision)
    except AssessmentStoreError as error:
        code = (
            status.HTTP_404_NOT_FOUND
            if "unknown review case" in str(error)
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(code, str(error)) from error

    return ReviewDecisionResponse(
        case=ReviewCaseSummary.of(case),
        regression=RegressionCaseView.of(regression) if regression is not None else None,
    )


@router.get(
    "/review-regressions",
    response_model=list[RegressionCaseView],
    summary="Exported regression records",
)
def list_regressions(
    store: StoreDependency,
    origin: str | None = None,
) -> list[RegressionCaseView]:
    """Return every versioned regression case (plan section 21.4)."""

    return [RegressionCaseView.of(case) for case in store.regression_cases(origin)]


__all__ = ["ReviewCard", "ReviewCaseSummary", "get_store", "router"]
