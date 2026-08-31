"""Feature definitions and which of them may reach a model (plan section 10.1).

`model_input=False` marks a value that is computed and displayed but excluded
from training and inference. Keeping that decision in data, rather than in the
training script, means the exclusion is testable.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class FeatureSpec:
    """One computed feature, its provenance, and whether a model may use it."""

    name: str
    family: str
    window: str
    description: str
    model_input: bool = True


ADOPTION_WINDOW_WEEKS: Final[int] = 13
SUPPORT_WINDOW_WEEKS: Final[int] = 26
EVENT_WINDOW_WEEKS: Final[int] = 26
SHORT_DELTA_WEEKS: Final[int] = 6
LONG_DELTA_WEEKS: Final[int] = 13

FEATURE_SPECS: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec(
        "adoption_trend_13w",
        "adoption",
        "last 13 observed weeks",
        "Ordinary least squares slope of the weekly adoption index.",
    ),
    FeatureSpec(
        "adoption_level_last_q",
        "adoption",
        "last 13 observed weeks",
        "Mean weekly adoption index, 100 x mean active users per licensed seat.",
    ),
    FeatureSpec(
        "advanced_feature_depth",
        "adoption",
        "last 13 observed weeks",
        "Mean advanced_feature_adoption_pct from telemetry. Recomputed from "
        "observations rather than the archive's latent target (plan section 8.3).",
    ),
    FeatureSpec(
        "product_breadth",
        "account",
        "contract",
        "Number of licensed products, a stickiness signal.",
    ),
    FeatureSpec(
        "active_users_delta_6w",
        "adoption",
        "6 weeks against the preceding 6",
        "Relative change in mean weekly active users.",
    ),
    FeatureSpec(
        "active_users_delta_13w",
        "adoption",
        "13 weeks against the preceding 13",
        "Relative change in mean weekly active users.",
    ),
    FeatureSpec(
        "sessions_delta_6w",
        "adoption",
        "6 weeks against the preceding 6",
        "Relative change in mean weekly sessions.",
    ),
    FeatureSpec(
        "sessions_delta_13w",
        "adoption",
        "13 weeks against the preceding 13",
        "Relative change in mean weekly sessions.",
    ),
    FeatureSpec(
        "ticket_count_26w",
        "support",
        "last 26 weeks",
        "Support tickets opened in the window.",
    ),
    FeatureSpec(
        "support_escalation_rate",
        "support",
        "last 26 weeks",
        "Escalations divided by observed active weeks inside the 26-week window. "
        "The archive divides by the whole observed history (plan section 8.3).",
    ),
    FeatureSpec(
        "high_priority_share_26w",
        "support",
        "last 26 weeks",
        "Share of window tickets raised at P1 or P2.",
    ),
    FeatureSpec(
        "open_high_priority_count",
        "support",
        "as at cutoff",
        "P1 or P2 tickets still Open or Pending Customer at the cutoff.",
    ),
    FeatureSpec(
        "avg_ticket_sentiment_26w",
        "support",
        "last 26 weeks",
        "Mean ticket sentiment. Named explicitly because the archive's "
        "avg_sentiment is ticket-only despite ambiguous wording (section 8.3).",
    ),
    FeatureSpec(
        "avg_note_sentiment_26w",
        "support",
        "last 26 weeks",
        "Mean CSM note sentiment, kept separate from ticket sentiment.",
    ),
    FeatureSpec(
        "avg_closed_csat_26w",
        "support",
        "last 26 weeks",
        "Mean CSAT across closed tickets; 3.5 when the window has none.",
    ),
    FeatureSpec(
        "adverse_events_2q",
        "external",
        "last 26 weeks",
        "Count of headwind external events.",
    ),
    FeatureSpec(
        "favorable_events_2q",
        "external",
        "last 26 weeks",
        "Count of tailwind external events.",
    ),
    FeatureSpec(
        "sponsor_change",
        "relationship",
        "as at cutoff",
        "Executive sponsor is new or lost.",
    ),
    FeatureSpec(
        "sponsor_lost",
        "relationship",
        "as at cutoff",
        "Executive sponsor is lost.",
    ),
    FeatureSpec(
        "onboarding_incomplete",
        "relationship",
        "as at cutoff",
        "Onboarding was not completed.",
    ),
    FeatureSpec(
        "days_to_renewal",
        "account",
        "cutoff to renewal",
        "Days from the forecast date to renewal. Display only: this dataset "
        "holds it constant at 90, so it carries no signal (plan section 8.3).",
        model_input=False,
    ),
)

MODEL_INPUT_FEATURES: Final[tuple[str, ...]] = tuple(
    spec.name for spec in FEATURE_SPECS if spec.model_input
)
"""Ordered feature names a model may consume. Order is part of the contract."""

DISPLAY_ONLY_FEATURES: Final[tuple[str, ...]] = tuple(
    spec.name for spec in FEATURE_SPECS if not spec.model_input
)

FEATURE_FAMILIES: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(spec.family for spec in FEATURE_SPECS)
)
