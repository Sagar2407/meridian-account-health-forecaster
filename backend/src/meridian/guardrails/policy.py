"""What counts as a high-value account (plan section 16.5).

Section 16.5 defines it as `segment == Strategic` or `acv_usd` at or above the
portfolio's 90th percentile, "matching the synthetic policy used by the
guardrail generator". The percentile is a property of the portfolio rather than
a constant, so it is measured from the repository once and then frozen for the
life of the policy object: a threshold that drifts between two runs would make
two identical assessments route differently.
"""

from dataclasses import dataclass

import numpy as np

from meridian.data.repository import AccountProfile, RuntimeRepository

#: Segments that are high value regardless of contract size.
HIGH_VALUE_SEGMENTS: frozenset[str] = frozenset({"Strategic"})

#: The percentile of annual contract value above which an account is high value.
HIGH_VALUE_ACV_PERCENTILE = 90.0


@dataclass(frozen=True)
class HighValuePolicy:
    """A frozen definition of high value for one portfolio."""

    acv_threshold: float
    segments: frozenset[str] = HIGH_VALUE_SEGMENTS
    percentile: float = HIGH_VALUE_ACV_PERCENTILE
    accounts_measured: int = 0

    @classmethod
    def from_repository(cls, repository: RuntimeRepository) -> "HighValuePolicy":
        """Measure the portfolio's ACV percentile and return a frozen policy."""

        values = [repository.profile(account_id).acv_usd for account_id in repository.account_ids()]
        if not values:
            raise ValueError("cannot define high value over an empty portfolio")
        threshold = float(np.percentile(np.asarray(values, dtype=float), HIGH_VALUE_ACV_PERCENTILE))
        return cls(acv_threshold=threshold, accounts_measured=len(values))

    def is_high_value(self, profile: AccountProfile) -> bool:
        """Return whether an adverse call on this account needs extra care."""

        return profile.segment in self.segments or profile.acv_usd >= self.acv_threshold

    def reason(self, profile: AccountProfile) -> str:
        """Return why this account is or is not high value, for the trace."""

        if profile.segment in self.segments:
            return f"segment {profile.segment}"
        if profile.acv_usd >= self.acv_threshold:
            return (
                f"ACV {profile.acv_usd:,.0f} at or above the portfolio "
                f"{self.percentile:.0f}th percentile {self.acv_threshold:,.0f}"
            )
        return "standard value"


__all__ = ["HIGH_VALUE_ACV_PERCENTILE", "HIGH_VALUE_SEGMENTS", "HighValuePolicy"]
