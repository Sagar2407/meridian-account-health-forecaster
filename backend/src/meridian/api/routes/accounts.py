"""Sanitized account browsing (plan section 19.1).

Two endpoints, both read-only, both serving the same `AccountProfile` the graph
reads. That is the point: the list a person picks from and the profile an
assessment runs against cannot disagree, because there is one source and it is
already stripped of every latent field by `meridian.data.repository`.

The historical summaries come from application memory rather than the dataset.
Section 17.2 is explicit that prior assessments are context, not truth, so they
are served under their own key and never merged into the profile.
"""

from datetime import date
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Query
from pydantic import BaseModel

from meridian.api.dependencies import RuntimeDependency
from meridian.api.errors import ApiError
from meridian.data.repository import AccountProfile, RuntimeRepository, UnknownAccountError
from meridian.tools.contracts import EvidenceSignal

router = APIRouter(tags=["accounts"])

MAX_PAGE_SIZE = 200

#: Weeks of telemetry the account page charts (plan section 20.2).
USAGE_WEEKS = 104

#: How many recent notes, tickets, and events the page lists. Enough to show
#: the shape of the account's recent history without turning a profile request
#: into a bulk export.
RECENT_ITEMS = 8

#: Ticket and note body text is not served. The page shows subjects, types, and
#: dates; the excerpts a reader may see are the ones retrieval selected and the
#: decision cited, which travel with the decision card and are already scoped.
MAX_SUBJECT_CHARACTERS = 160


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


class UsagePoint(BaseModel):
    """One week of telemetry, aggregated across the account's products."""

    week_start: str
    active_users: int
    sessions: int
    feature_events: int
    advanced_feature_adoption_pct: float


class RecentItem(BaseModel):
    """One dated item from the account's recent history.

    `signal` uses `EvidenceSignal`, the same vocabulary a citation carries.
    Two spellings of "this points the wrong way" in one API is one more thing a
    reader has to hold in their head, and the browser has already got it wrong
    once.
    """

    kind: Literal["ticket", "note", "event"]
    item_date: str
    label: str
    detail: str
    signal: EvidenceSignal = "neutral"


class AccountIndicators(BaseModel):
    """The at-a-glance signals section 20.2 asks the account page to show."""

    weeks_observed: int
    active_users_last_week: int
    adoption_trend_13w: float
    open_tickets: int
    escalations_26w: int
    average_ticket_sentiment: float | None
    external_events_26w: int
    sponsor_status: str
    onboarding_completed: bool


class AccountDetail(BaseModel):
    """A sanitized profile and everything the account page draws.

    One request rather than five. Every part is bounded by the same effective
    cutoff, so a page cannot accidentally render a chart from one point in time
    beside indicators from another.
    """

    profile: dict[str, object]
    effective_cutoff: str
    high_value: bool
    high_value_reason: str
    indicators: AccountIndicators
    usage: list[UsagePoint]
    recent: list[RecentItem]
    prior_assessments: list[PriorAssessmentView]


def _usage_series(repository: RuntimeRepository, account_id: str) -> list[UsagePoint]:
    """Return the last `USAGE_WEEKS` weeks of telemetry, summed across products.

    The repository has already filtered to the account's effective cutoff, so
    the chart cannot show a week the assessment could not have seen. Products
    are summed because the page charts one trajectory; the per-product split is
    a tool call, not a page.
    """

    frame = repository.usage(account_id)
    if frame.empty:
        return []
    weekly = (
        frame.groupby("week_start")
        .agg(
            active_users=("active_users", "sum"),
            sessions=("sessions", "sum"),
            feature_events=("feature_events", "sum"),
            advanced_feature_adoption_pct=("advanced_feature_adoption_pct", "mean"),
        )
        .sort_index()
        .tail(USAGE_WEEKS)
    )
    return [
        UsagePoint(
            week_start=pd.Timestamp(str(week)).date().isoformat(),
            active_users=int(row.active_users),
            sessions=int(row.sessions),
            feature_events=int(row.feature_events),
            advanced_feature_adoption_pct=round(float(row.advanced_feature_adoption_pct), 2),
        )
        for week, row in weekly.iterrows()
    ]


def _sentiment_signal(value: object) -> EvidenceSignal:
    """Classify a stored sentiment score. Structured metadata, never free text."""

    if value is None:
        return "neutral"
    try:
        score = float(str(value))
    except ValueError:
        return "neutral"
    if score != score:  # NaN, which the archive uses for a missing score
        return "neutral"
    if score > 0.15:
        return "favorable"
    if score < -0.15:
        return "adverse"
    return "neutral"


def _recent(repository: RuntimeRepository, account_id: str) -> list[RecentItem]:
    """Return the account's most recent notes, tickets, and events.

    Subjects and headlines only. Ticket and note bodies stay out of this
    response: the excerpts a reader is meant to see are the ones retrieval
    selected and a decision cited, which arrive with the decision card already
    scoped to the account and the cutoff.
    """

    items: list[RecentItem] = []

    tickets = repository.tickets(account_id).sort_values("created_date").tail(RECENT_ITEMS)
    for row in tickets.to_dict("records"):
        items.append(
            RecentItem(
                kind="ticket",
                item_date=pd.Timestamp(row["created_date"]).date().isoformat(),
                label=str(row["subject"])[:MAX_SUBJECT_CHARACTERS],
                detail=f"{row['category']} · {row['priority']} · {row['status']}",
                signal=_sentiment_signal(row.get("sentiment")),
            )
        )

    notes = repository.notes(account_id).sort_values("note_date").tail(RECENT_ITEMS)
    for row in notes.to_dict("records"):
        items.append(
            RecentItem(
                kind="note",
                item_date=pd.Timestamp(row["note_date"]).date().isoformat(),
                label=str(row["note_type"]),
                detail=f"logged by {row['author']}",
                signal=_sentiment_signal(row.get("sentiment")),
            )
        )

    events = repository.events(account_id).sort_values("event_date").tail(RECENT_ITEMS)
    for row in events.to_dict("records"):
        polarity = int(row["polarity"])
        items.append(
            RecentItem(
                kind="event",
                item_date=pd.Timestamp(row["event_date"]).date().isoformat(),
                label=str(row["headline"])[:MAX_SUBJECT_CHARACTERS],
                detail=f"{row['event_type']} · {row['source']}",
                signal=("favorable" if polarity > 0 else "adverse" if polarity < 0 else "neutral"),
            )
        )

    items.sort(key=lambda item: item.item_date, reverse=True)
    return items[: RECENT_ITEMS * 2]


def _indicators(
    repository: RuntimeRepository,
    profile: AccountProfile,
    usage: list[UsagePoint],
    cutoff: date,
) -> AccountIndicators:
    """Return the at-a-glance signals, all measured at the same cutoff."""

    trend = 0.0
    if len(usage) >= 26:
        recent = sum(point.active_users for point in usage[-13:]) / 13
        prior = sum(point.active_users for point in usage[-26:-13]) / 13
        trend = round(recent - prior, 2)

    tickets = repository.tickets(profile.account_id)
    window = pd.Timestamp(cutoff) - pd.Timedelta(weeks=26)
    recent_tickets = tickets.loc[pd.to_datetime(tickets["created_date"]) >= window]
    sentiment = recent_tickets["sentiment"].dropna()
    events = repository.events(profile.account_id)
    recent_events = events.loc[pd.to_datetime(events["event_date"]) >= window]

    return AccountIndicators(
        weeks_observed=len(usage),
        active_users_last_week=usage[-1].active_users if usage else 0,
        adoption_trend_13w=trend,
        open_tickets=int((tickets["status"] != "Closed").sum()),
        escalations_26w=int((recent_tickets["priority"] == "Urgent").sum()),
        average_ticket_sentiment=(
            round(float(sentiment.mean()), 3) if not sentiment.empty else None
        ),
        external_events_26w=len(recent_events),
        sponsor_status=profile.sponsor_status,
        onboarding_completed=profile.onboarding_completed,
    )


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

    usage = _usage_series(runtime.repository, account_id)
    return AccountDetail(
        profile=profile.model_dump(mode="json"),
        effective_cutoff=profile.effective_cutoff.isoformat(),
        high_value=runtime.high_value.is_high_value(profile),
        high_value_reason=runtime.high_value.reason(profile),
        indicators=_indicators(runtime.repository, profile, usage, profile.effective_cutoff),
        usage=usage,
        recent=_recent(runtime.repository, account_id),
        prior_assessments=priors,
    )


__all__ = [
    "AccountDetail",
    "AccountIndicators",
    "AccountPage",
    "AccountSummary",
    "RecentItem",
    "UsagePoint",
    "router",
]
