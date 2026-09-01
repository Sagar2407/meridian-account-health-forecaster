"""Sanitized account browsing (plan section 19.1).

Two endpoints, both read-only, both serving the same `AccountProfile` the graph
reads. That is the point: the list a person picks from and the profile an
assessment runs against cannot disagree, because there is one source and it is
already stripped of every latent field by `meridian.data.repository`.

The historical summaries come from application memory rather than the dataset.
Section 17.2 is explicit that prior assessments are context, not truth, so they
are served under their own key and never merged into the profile.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from meridian.api.dependencies import RuntimeDependency
from meridian.api.errors import ApiError
from meridian.data.repository import AccountProfile, UnknownAccountError

router = APIRouter(tags=["accounts"])

MAX_PAGE_SIZE = 200


class AccountSummary(BaseModel):
    """One row of the portfolio list."""

    account_id: str
    account_name: str
    segment: str
    industry: str
    region: str
    acv_usd: float
    renewal_date: str
    days_to_renewal: int
    sponsor_status: str
    onboarding_completed: bool
    high_value: bool

    @classmethod
    def of(cls, profile: AccountProfile, high_value: bool) -> "AccountSummary":
        """Return the list view of a sanitized profile."""

        return cls(
            account_id=profile.account_id,
            account_name=profile.account_name,
            segment=profile.segment,
            industry=profile.industry,
            region=profile.region,
            acv_usd=profile.acv_usd,
            renewal_date=profile.renewal_date.isoformat(),
            days_to_renewal=(profile.renewal_date - profile.forecast_as_of_date).days,
            sponsor_status=profile.sponsor_status,
            onboarding_completed=profile.onboarding_completed,
            high_value=high_value,
        )


class AccountPage(BaseModel):
    """One page of the portfolio."""

    items: list[AccountSummary]
    total: int
    offset: int
    limit: int


class PriorAssessmentView(BaseModel):
    """One of this system's own earlier advisory decisions."""

    assessment_id: str
    created_at: str
    cutoff: str
    predicted_outcome: str
    confidence: float
    route: str
    summary: str


class AccountDetail(BaseModel):
    """A sanitized profile and what this system has said about it before."""

    profile: dict[str, object]
    effective_cutoff: str
    high_value: bool
    high_value_reason: str
    prior_assessments: list[PriorAssessmentView]


@router.get("/accounts", response_model=AccountPage, summary="Browse the portfolio")
def list_accounts(
    runtime: RuntimeDependency,
    segment: str | None = None,
    region: str | None = None,
    renews_within_days: Annotated[int | None, Query(ge=0, le=3_650)] = None,
    sort: Literal["renewal_date", "acv_usd", "account_id"] = "renewal_date",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> AccountPage:
    """Return a filtered, sorted, paginated slice of the portfolio."""

    policy = runtime.high_value
    profiles = [runtime.repository.profile(account) for account in runtime.repository.account_ids()]

    if segment:
        profiles = [profile for profile in profiles if profile.segment == segment]
    if region:
        profiles = [profile for profile in profiles if profile.region == region]
    if renews_within_days is not None:
        profiles = [
            profile
            for profile in profiles
            if 0 <= (profile.renewal_date - profile.forecast_as_of_date).days <= renews_within_days
        ]

    if sort == "acv_usd":
        profiles.sort(key=lambda profile: (-profile.acv_usd, profile.account_id))
    elif sort == "account_id":
        profiles.sort(key=lambda profile: profile.account_id)
    else:
        profiles.sort(key=lambda profile: (profile.renewal_date, profile.account_id))

    page = profiles[offset : offset + limit]
    return AccountPage(
        items=[AccountSummary.of(profile, policy.is_high_value(profile)) for profile in page],
        total=len(profiles),
        offset=offset,
        limit=limit,
    )


@router.get(
    "/accounts/{account_id}",
    response_model=AccountDetail,
    summary="One sanitized profile and its advisory history",
)
def read_account(account_id: str, runtime: RuntimeDependency) -> AccountDetail:
    """Return one account, or say plainly that there is no such account.

    Raises:
        ApiError: `ACCOUNT_NOT_FOUND` when the id is not in the portfolio.
    """

    try:
        profile = runtime.repository.profile(account_id)
    except UnknownAccountError as error:
        raise ApiError(
            "ACCOUNT_NOT_FOUND", f"There is no account {account_id} in this portfolio."
        ) from error

    priors: list[PriorAssessmentView] = []
    if runtime.store is not None:
        priors = [
            PriorAssessmentView(
                assessment_id=record.assessment_id,
                created_at=record.created_at,
                cutoff=record.cutoff.isoformat(),
                predicted_outcome=record.predicted_outcome,
                confidence=record.confidence,
                route=record.decision,
                summary=record.summary,
            )
            for record in runtime.store.recent_assessments(account_id)
        ]

    return AccountDetail(
        profile=profile.model_dump(mode="json"),
        effective_cutoff=profile.effective_cutoff.isoformat(),
        high_value=runtime.high_value.is_high_value(profile),
        high_value_reason=runtime.high_value.reason(profile),
        prior_assessments=priors,
    )


__all__ = ["AccountDetail", "AccountPage", "AccountSummary", "router"]
