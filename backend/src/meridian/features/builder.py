"""Compute account features at an arbitrary valid cutoff (plan section 10.1).

Every value here is derived from observations the runtime repository is allowed
to see. Nothing is read from the archive's precomputed `account_features.csv`,
because three of its columns are defective or leak latent state (plan section
8.3), and because a runtime forecast must be reproducible at any cutoff rather
than only at the one the archive happened to use.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from meridian.data.repository import RuntimeRepository
from meridian.features.spec import (
    ADOPTION_WINDOW_WEEKS,
    EVENT_WINDOW_WEEKS,
    LONG_DELTA_WEEKS,
    MODEL_INPUT_FEATURES,
    SHORT_DELTA_WEEKS,
    SUPPORT_WINDOW_WEEKS,
)

DEFAULT_CSAT = 3.5
"""Neutral CSAT used when a window contains no closed ticket, matching the archive."""

HIGH_PRIORITIES = ("P1", "P2")
UNRESOLVED_STATUSES = ("Open", "Pending Customer")


class FeatureCoverage(BaseModel):
    """How much evidence each feature family was computed from.

    Plan section 10.1 requires every metric to carry its window and source row
    count, so a thin forecast can be recognised as thin.
    """

    model_config = ConfigDict(frozen=True)

    observed_weeks_total: int
    observed_weeks_adoption_window: int
    tickets_in_window: int
    notes_in_window: int
    events_in_window: int
    closed_tickets_with_csat: int

    @property
    def has_adoption_evidence(self) -> bool:
        """Return whether enough weeks exist to fit a trend."""

        return self.observed_weeks_adoption_window >= 4

    @property
    def thin_families(self) -> tuple[str, ...]:
        """Return families that had no source rows at all."""

        empty: list[str] = []
        if self.observed_weeks_adoption_window == 0:
            empty.append("adoption")
        if self.tickets_in_window == 0:
            empty.append("support")
        if self.events_in_window == 0:
            empty.append("external")
        return tuple(empty)


class AccountFeatures(BaseModel):
    """Immutable feature vector for one account at one cutoff."""

    model_config = ConfigDict(frozen=True)

    account_id: str
    cutoff: date
    values: dict[str, float]
    coverage: FeatureCoverage

    def vector(self) -> list[float]:
        """Return model input features in the canonical order."""

        return [self.values[name] for name in MODEL_INPUT_FEATURES]


def _weekly_adoption(usage: pd.DataFrame, licensed_seats: int) -> pd.DataFrame:
    """Return one row per week with adoption index, users, sessions, and depth.

    The adoption index is `100 * mean over products of active_users /
    licensed_seats`. It is an observable proxy for engagement depth and can
    exceed 100 when a product is used by more accounts than seats imply.
    """

    if usage.empty:
        return pd.DataFrame(
            columns=["week_start", "adoption_index", "active_users", "sessions", "advanced_pct"]
        )
    frame = usage.copy()
    frame["seat_ratio"] = frame["active_users"] / max(licensed_seats, 1)
    weekly = (
        frame.groupby("week_start")
        .agg(
            seat_ratio=("seat_ratio", "mean"),
            active_users=("active_users", "sum"),
            sessions=("sessions", "sum"),
            advanced_pct=("advanced_feature_adoption_pct", "mean"),
        )
        .reset_index()
        .sort_values("week_start")
    )
    weekly["adoption_index"] = 100.0 * weekly["seat_ratio"]
    return weekly


def _slope(values: "pd.Series[float]") -> float:
    """Return the OLS slope of `values` against its position index."""

    if len(values) < 2:
        return 0.0
    positions = np.arange(len(values), dtype=float)
    return float(np.polyfit(positions, values.to_numpy(dtype=float), 1)[0])


def _relative_delta(weekly: pd.DataFrame, column: str, weeks: int) -> float:
    """Return the relative change in `column` against the preceding equal window.

    Returns 0.0 when there is not enough history, or when the earlier window
    averaged zero, so an undefined ratio never becomes an infinity.
    """

    if len(weekly) < weeks * 2:
        return 0.0
    series = weekly[column].to_numpy(dtype=float)
    recent = float(np.mean(series[-weeks:]))
    prior = float(np.mean(series[-weeks * 2 : -weeks]))
    if prior == 0.0:
        return 0.0
    return (recent - prior) / prior


def build_features(
    repository: RuntimeRepository,
    account_id: str,
    cutoff: date | None = None,
) -> AccountFeatures:
    """Compute every feature for one account as at `cutoff`.

    Args:
        repository: Sanitized, cutoff-enforcing data access.
        account_id: Account to compute for.
        cutoff: Optional earlier cutoff, for point-in-time backtesting. It is
            clamped to the account's effective cutoff, so passing a later date
            can never widen what is visible.

    Returns:
        An immutable :class:`AccountFeatures`.
    """

    profile = repository.profile(account_id)
    effective = profile.effective_cutoff
    as_at = min(cutoff, effective) if cutoff is not None else effective

    usage = repository.usage(account_id)
    tickets = repository.tickets(account_id)
    notes = repository.notes(account_id)
    events = repository.events(account_id)

    boundary = pd.Timestamp(as_at)
    usage = usage.loc[usage["week_start"] <= boundary]
    support_start = pd.Timestamp(as_at - timedelta(weeks=SUPPORT_WINDOW_WEEKS))
    event_start = pd.Timestamp(as_at - timedelta(weeks=EVENT_WINDOW_WEEKS))

    tickets = tickets.loc[tickets["created_date"].between(support_start, boundary)]
    notes = notes.loc[notes["note_date"].between(support_start, boundary)]
    events = events.loc[events["event_date"].between(event_start, boundary)]

    weekly = _weekly_adoption(usage, profile.licensed_seats)
    adoption_window = weekly.tail(ADOPTION_WINDOW_WEEKS)
    weeks_in_support_window = (
        int((weekly["week_start"] >= support_start).sum()) if len(weekly) else 0
    )

    adoption_trend = _slope(adoption_window["adoption_index"]) if len(adoption_window) >= 2 else 0.0
    adoption_level = (
        float(adoption_window["adoption_index"].mean()) if len(adoption_window) else 0.0
    )
    advanced_depth = float(adoption_window["advanced_pct"].mean()) if len(adoption_window) else 0.0

    escalations = int((tickets["category"] == "Escalation").sum())
    # Plan section 8.3: divide by active weeks inside the 26-week window, not by
    # the whole observed history as the archive does.
    escalation_rate = escalations / max(weeks_in_support_window, 1)

    high_priority = int(tickets["priority"].isin(HIGH_PRIORITIES).sum())
    ticket_count = len(tickets)
    csat_values = tickets["csat"].dropna()

    values: dict[str, float] = {
        "adoption_trend_13w": adoption_trend,
        "adoption_level_last_q": adoption_level,
        "advanced_feature_depth": advanced_depth,
        "product_breadth": float(profile.num_products),
        "active_users_delta_6w": _relative_delta(weekly, "active_users", SHORT_DELTA_WEEKS),
        "active_users_delta_13w": _relative_delta(weekly, "active_users", LONG_DELTA_WEEKS),
        "sessions_delta_6w": _relative_delta(weekly, "sessions", SHORT_DELTA_WEEKS),
        "sessions_delta_13w": _relative_delta(weekly, "sessions", LONG_DELTA_WEEKS),
        "ticket_count_26w": float(ticket_count),
        "support_escalation_rate": escalation_rate,
        "high_priority_share_26w": (high_priority / ticket_count) if ticket_count else 0.0,
        "open_high_priority_count": float(
            (
                tickets["priority"].isin(HIGH_PRIORITIES)
                & tickets["status"].isin(UNRESOLVED_STATUSES)
            ).sum()
        ),
        "avg_ticket_sentiment_26w": float(tickets["sentiment"].mean()) if ticket_count else 0.0,
        "avg_note_sentiment_26w": float(notes["sentiment"].mean()) if len(notes) else 0.0,
        "avg_closed_csat_26w": float(csat_values.mean()) if len(csat_values) else DEFAULT_CSAT,
        "adverse_events_2q": float((events["polarity"] < 0).sum()),
        "favorable_events_2q": float((events["polarity"] > 0).sum()),
        "sponsor_change": float(profile.sponsor_status in ("new", "lost")),
        "sponsor_lost": float(profile.sponsor_status == "lost"),
        "onboarding_incomplete": float(not profile.onboarding_completed),
        "days_to_renewal": float((profile.renewal_date - profile.forecast_as_of_date).days),
    }

    coverage = FeatureCoverage(
        observed_weeks_total=len(weekly),
        observed_weeks_adoption_window=len(adoption_window),
        tickets_in_window=ticket_count,
        notes_in_window=len(notes),
        events_in_window=len(events),
        closed_tickets_with_csat=len(csat_values),
    )
    return AccountFeatures(account_id=account_id, cutoff=as_at, values=values, coverage=coverage)


def build_feature_frame(
    repository: RuntimeRepository,
    account_ids: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Return a frame of model input features indexed by account id."""

    ids = account_ids if account_ids is not None else repository.account_ids()
    records = [build_features(repository, account_id) for account_id in ids]
    frame = pd.DataFrame(
        [record.vector() for record in records],
        columns=list(MODEL_INPUT_FEATURES),
        index=pd.Index([record.account_id for record in records], name="account_id"),
    )
    return frame
