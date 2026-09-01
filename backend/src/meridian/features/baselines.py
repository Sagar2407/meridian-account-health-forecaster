"""Portfolio baselines for the deterministic conflict rules (plan section 17.3).

Two of section 15.1's conflict triggers are relative: "weak adoption" and
"above-median adoption" only mean something against a reference. Section 17.3
requires those baselines to be versioned deterministic values rather than
something inferred ad hoc, so they are computed once from the immutable dataset
and carry the dataset version and the feature calculation version with them.

Nothing here reads a label. The medians come from the same runtime repository
the forecaster sees, so a baseline can never smuggle outcome data into a rule.

The sweep costs about two seconds over the whole portfolio, which is why
`BaselineProvider` defers it until a run actually reaches the conflict gate: a
blocked request, or one that degrades on coverage, never pays for it.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from meridian.data.constants import DATASET_VERSION
from meridian.data.repository import RuntimeRepository
from meridian.features.builder import build_features
from meridian.features.spec import CALCULATION_VERSION

#: The features a conflict rule compares an account against. Kept short on
#: purpose: every entry is a portfolio-wide sweep, and a baseline nothing reads
#: is a cost with no reader.
BASELINE_FEATURES: tuple[str, ...] = (
    "adoption_level_last_q",
    "adoption_trend_13w",
    "avg_ticket_sentiment_26w",
)


@dataclass(frozen=True)
class PortfolioBaseline:
    """Median feature values across the portfolio, frozen for the process."""

    medians: dict[str, float] = field(default_factory=dict)
    accounts_measured: int = 0
    dataset_version: str = DATASET_VERSION
    calculation_version: str = CALCULATION_VERSION

    @classmethod
    def from_repository(
        cls, repository: RuntimeRepository, features: tuple[str, ...] = BASELINE_FEATURES
    ) -> "PortfolioBaseline":
        """Measure the portfolio's medians for `features`."""

        account_ids = repository.account_ids()
        if not account_ids:
            raise ValueError("cannot measure a baseline over an empty portfolio")
        collected: dict[str, list[float]] = {name: [] for name in features}
        for account_id in account_ids:
            values = build_features(repository, account_id).values
            for name in features:
                collected[name].append(float(values[name]))
        return cls(
            medians={
                name: float(np.median(np.asarray(series, dtype=float)))
                for name, series in collected.items()
            },
            accounts_measured=len(account_ids),
        )

    def median(self, feature: str) -> float | None:
        """Return the portfolio median for `feature`, or None if unmeasured.

        A rule that needs a baseline this instance does not carry must not fire
        on a default. Returning None makes the caller skip the rule and say so,
        rather than compare against zero and call the result a conflict.
        """

        return self.medians.get(feature)


class BaselineProvider:
    """Compute the portfolio baseline once, on first use.

    `GraphRuntime` is frozen, so the memo lives here rather than on the runtime.
    This mirrors how `ToolServices` defers building the retrieval index: the
    expensive collaborator is a callable until something needs it.
    """

    def __init__(self, factory: Callable[[], PortfolioBaseline]) -> None:
        self._factory = factory
        self._value: PortfolioBaseline | None = None

    @classmethod
    def over(cls, repository: RuntimeRepository) -> "BaselineProvider":
        """Return a provider that measures `repository` when first asked."""

        return cls(lambda: PortfolioBaseline.from_repository(repository))

    @classmethod
    def fixed(cls, baseline: PortfolioBaseline) -> "BaselineProvider":
        """Return a provider for an already-measured baseline."""

        return cls(lambda: baseline)

    @property
    def measured(self) -> bool:
        """Return whether the sweep has already run in this process."""

        return self._value is not None

    def get(self) -> PortfolioBaseline:
        """Return the baseline, measuring it on the first call."""

        if self._value is None:
            self._value = self._factory()
        return self._value


__all__ = ["BASELINE_FEATURES", "BaselineProvider", "PortfolioBaseline"]
