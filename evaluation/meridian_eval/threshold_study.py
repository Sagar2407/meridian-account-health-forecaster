"""What the review bands would release at other thresholds (plan section 22.6).

Three separate measurements have now said the same thing: the routing bands
auto-release almost nothing. Phase 7 released 2 of 21 answerable guardrail
cases; Phase 8's portfolio scan released 0 of 6. Section 22.6 says thresholds
may be adjusted "only with documented rationale, then freeze before the
held-out run", and section 22.7 forbids doing that on held-out outcomes.

So this measures the trade-off on the **development split only**, and it
measures it rather than arguing about it: for a grid of candidate bands, how
many answers would be auto-released, and how many of those would be wrong.

**Replaying is exact, not approximate.** Only three routing rules read a
threshold -- the two confidence comparisons and the tie margin. Every other
rule (missing coverage, failed verification, an adverse call on a high-value
account, and so on) is threshold-independent, so its verdict is recorded once
from the real run and reused. That is why a full sweep costs one pass over the
split instead of one pass per candidate.

This module reads outcome labels. Nothing in `meridian` imports it, and
`test_import_boundary.py` fails the build if that changes.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from meridian.graph.thresholds import THRESHOLDS, DecisionThresholds
from meridian_eval.system_run import SystemRun

#: Red-route rules that do not read a threshold. Their verdict is recorded from
#: the real run and reused for every candidate.
FIXED_RED_CODES: frozenset[str] = frozenset(
    {
        "critical_coverage_missing",
        "unresolved_severe_conflict",
        "verification_failed",
        "high_value_adverse",
        "intake_escalation",
        "evidence_quarantined",
    }
)

#: Amber-route rules that do not read a threshold.
FIXED_AMBER_CODES: frozenset[str] = frozenset(
    {"retrieval_gap", "output_regenerated", "stale_sources", "budget_exhausted"}
)

#: The candidate bands swept. The frozen pair (0.85 / 0.70) is inside the grid
#: so the table shows the status quo beside its alternatives rather than
#: implying the alternatives are better by omitting it.
GREEN_CANDIDATES: tuple[float, ...] = (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
AMBER_CANDIDATES: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70)


def band_at(run: SystemRun, thresholds: DecisionThresholds) -> str:
    """Return the band `run` would have been assigned at `thresholds`.

    Exact rather than a re-run: the rules that do not read a threshold were
    already evaluated once by the real run, and their answer cannot change.
    """

    if run.confidence < thresholds.amber_minimum_confidence:
        return "red"
    if run.margin < thresholds.tie_margin:
        return "red"
    if FIXED_RED_CODES.intersection(run.route_codes):
        return "red"
    if run.confidence < thresholds.green_minimum_confidence:
        return "amber"
    if FIXED_AMBER_CODES.intersection(run.route_codes):
        return "amber"
    return "green"


@dataclass(frozen=True)
class BandOutcome:
    """What one candidate pair of bands would have done to the whole split."""

    green_minimum: float
    amber_minimum: float
    released: int
    auto_released: int
    amber: int
    red: int
    auto_release_rate: float
    auto_released_errors: int
    auto_released_error_rate: float | None
    review_load: int
    review_load_rate: float

    def as_row(self) -> dict[str, Any]:
        """Return a CSV row."""

        return {
            "green_minimum": self.green_minimum,
            "amber_minimum": self.amber_minimum,
            "released": self.released,
            "auto_released": self.auto_released,
            "amber": self.amber,
            "red": self.red,
            "auto_release_rate": round(self.auto_release_rate, 4),
            "auto_released_errors": self.auto_released_errors,
            "auto_released_error_rate": (
                None
                if self.auto_released_error_rate is None
                else round(self.auto_released_error_rate, 4)
            ),
            "review_load": self.review_load,
            "review_load_rate": round(self.review_load_rate, 4),
        }


@dataclass
class ThresholdStudy:
    """The runs a sweep is computed over, and the sweep itself."""

    runs: list[SystemRun] = field(default_factory=list)
    split: str = "development"

    def outcome_at(self, thresholds: DecisionThresholds) -> BandOutcome:
        """Return what one candidate pair would have done."""

        released = [run for run in self.runs if run.released]
        bands = [(run, band_at(run, thresholds)) for run in released]
        green = [run for run, band in bands if band == "green"]
        amber = sum(1 for _, band in bands if band == "amber")
        red = sum(1 for _, band in bands if band == "red")
        errors = sum(1 for run in green if run.correct is False)
        total = len(self.runs)
        return BandOutcome(
            green_minimum=thresholds.green_minimum_confidence,
            amber_minimum=thresholds.amber_minimum_confidence,
            released=len(released),
            auto_released=len(green),
            amber=amber,
            red=red,
            auto_release_rate=(len(green) / total) if total else 0.0,
            auto_released_errors=errors,
            auto_released_error_rate=(errors / len(green)) if green else None,
            review_load=amber + red + (total - len(released)),
            review_load_rate=((amber + red + total - len(released)) / total) if total else 0.0,
        )

    def sweep(self) -> list[BandOutcome]:
        """Return the outcome for every candidate pair where amber <= green.

        Section 16.1's caps are defined against section 16.5's bands -- each
        sits one hundredth below the band it holds a run under -- so a
        candidate pair moves them too. Holding them fixed would measure
        configurations the system refuses to construct: with green at 0.80 and
        `cap_exhausted_retrieval_gap` left at 0.84, the cap is above the band
        and every run it caps auto-releases, which is the opposite of what the
        cap is for. `DecisionThresholds.__post_init__` rejects that set, so the
        sweep would not merely be misleading, it would raise.
        """

        outcomes: list[BandOutcome] = []
        for green in GREEN_CANDIDATES:
            for amber in AMBER_CANDIDATES:
                if amber >= green:
                    continue
                outcomes.append(
                    self.outcome_at(
                        DecisionThresholds(
                            green_minimum_confidence=green,
                            amber_minimum_confidence=amber,
                            cap_exhausted_retrieval_gap=round(green - 0.01, 2),
                            cap_repaired_verification=round(green - 0.01, 2),
                            cap_critical_source_missing=round(amber - 0.01, 2),
                            cap_unresolved_conflict=round(amber - 0.01, 2),
                        )
                    )
                )
        return outcomes

    def frame(self) -> pd.DataFrame:
        """Return the sweep as a frame, for the CSV artifact."""

        return pd.DataFrame([outcome.as_row() for outcome in self.sweep()])

    def summary(self) -> dict[str, Any]:
        """Return the frozen position and the sweep's headline alternatives."""

        frozen = self.outcome_at(THRESHOLDS)
        alternatives = sorted(
            (outcome for outcome in self.sweep() if outcome.auto_released > 0),
            key=lambda outcome: outcome.auto_release_rate,
            reverse=True,
        )
        released = [run for run in self.runs if run.released]
        correct = [run for run in released if run.correct is True]
        return {
            "split": self.split,
            "accounts": len(self.runs),
            "released": len(released),
            "abstained": sum(1 for run in self.runs if run.abstained),
            "accuracy_on_released": (round(len(correct) / len(released), 4) if released else None),
            "frozen": {
                "digest": THRESHOLDS.digest(),
                "version": THRESHOLDS.version,
                **frozen.as_row(),
            },
            "most_permissive_measured": alternatives[0].as_row() if alternatives else None,
            "candidates": len(self.sweep()),
        }


__all__ = [
    "AMBER_CANDIDATES",
    "FIXED_AMBER_CODES",
    "FIXED_RED_CODES",
    "GREEN_CANDIDATES",
    "BandOutcome",
    "ThresholdStudy",
    "band_at",
]
