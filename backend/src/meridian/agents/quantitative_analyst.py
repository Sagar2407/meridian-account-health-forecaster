"""The Quantitative Analyst (plan section 13.2).

A deterministic graph node calling the analytics and model services. There is no
language model anywhere in this file, and `test_import_boundary.py` would fail
the build if one appeared.

Its failure behaviour is the part worth reading carefully. Section 13.2 says
that when required telemetry cannot be computed the lane returns a typed
critical gap and "never substitutes an LLM estimate". So this lane has exactly
two shapes: a complete answer, or an explicit `available=False` with the gap
named. There is no partial forecast, and `QuantitativeEvidence` refuses at
construction to hold a prediction while marked unavailable.
"""

from datetime import date, timedelta

from meridian.agents.base import call_tool
from meridian.contracts import (
    CoverageReport,
    Driver,
    MetricObservation,
    QuantitativeEvidence,
)
from meridian.data.constants import DATASET_AS_OF_DATE
from meridian.features.builder import AccountFeatures, FeatureCoverage
from meridian.features.spec import ADOPTION_WINDOW_WEEKS, CALCULATION_VERSION, FEATURE_SPECS
from meridian.model.artifacts import ModelArtifact
from meridian.model.predict import predict_from_features
from meridian.tools.contracts import (
    AccountMetricsResponse,
    ExternalEventsResponse,
    RequesterRole,
    SupportSummaryResponse,
    UsageSeriesResponse,
)
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolUnavailableError

ROLE: RequesterRole = "quantitative_analyst"

#: Trailing windows the lane reads, in weeks. The support and event windows
#: match the feature definitions so the coverage counts describe the same rows
#: the metrics were computed from.
USAGE_WINDOW_WEEKS = 26
SUPPORT_WINDOW_WEEKS = 26
EVENT_WINDOW_WEEKS = 26

#: Telemetry older than this at the cutoff is reported as stale. Usage is weekly
#: by construction, so a gap of a quarter means collection stopped rather than
#: that the account went quiet.
STALE_USAGE_DAYS = 90

#: How many drivers reach the decision card. Section 16.4 asks for top positive
#: and negative drivers, not for every coefficient.
MAX_DRIVERS = 6

_METRIC_SOURCE = {
    "adoption": "usage_weekly",
    "support": "support_tickets and csm_notes",
    "external": "external_events",
    "relationship": "accounts",
    "account": "accounts",
}


class QuantitativeAnalyst:
    """Compute exact metrics, coverage, and the calibrated distribution."""

    def __init__(self, registry: ToolRegistry, artifact: ModelArtifact | None = None) -> None:
        self._registry = registry
        self._artifact = artifact

    def _coverage_for(self, family: str, coverage: FeatureCoverage) -> int:
        """Return the source-row count behind one feature family."""

        counts = {
            "adoption": coverage.observed_weeks_adoption_window,
            "support": coverage.tickets_in_window + coverage.notes_in_window,
            "external": coverage.events_in_window,
            "relationship": 1,
            "account": 1,
        }
        return counts.get(family, 0)

    def _observations(
        self, metrics: dict[str, float], coverage: FeatureCoverage
    ) -> tuple[MetricObservation, ...]:
        """Return one typed observation per feature, with its provenance."""

        return tuple(
            MetricObservation(
                name=spec.name,
                value=round(float(metrics[spec.name]), 6),
                window=spec.window,
                source=_METRIC_SOURCE.get(spec.family, spec.family),
                coverage=self._coverage_for(spec.family, coverage),
                calculation_version=CALCULATION_VERSION,
            )
            for spec in FEATURE_SPECS
            if spec.name in metrics
        )

    def _coverage_report(
        self,
        coverage: FeatureCoverage,
        usage: UsageSeriesResponse,
        support: SupportSummaryResponse,
        events: ExternalEventsResponse,
        cutoff: date,
        model_available: bool,
    ) -> CoverageReport:
        """Return what the lane actually had to work with."""

        latest_week = usage.points[-1].week_start if usage.points else None
        stale: list[str] = []
        if latest_week is not None and (cutoff - latest_week) > timedelta(days=STALE_USAGE_DAYS):
            stale.append("usage_weekly")

        critical: list[str] = []
        if coverage.observed_weeks_adoption_window == 0:
            # Every adoption feature would be zero, which a model reads as a
            # confident statement about a flat account rather than as silence.
            critical.append("no usage telemetry in the adoption window")
        if not model_available:
            critical.append("the calibrated forecaster artifact is unavailable")

        return CoverageReport(
            expected_weeks=ADOPTION_WINDOW_WEEKS,
            observed_weeks=coverage.observed_weeks_adoption_window,
            source_counts={
                "usage_weeks": len(usage.points),
                "usage_weeks_observed_total": coverage.observed_weeks_total,
                "tickets": support.tickets,
                "notes": coverage.notes_in_window,
                "events": len(events.events),
                "closed_tickets_with_csat": coverage.closed_tickets_with_csat,
            },
            missing_sources=coverage.thin_families,
            stale_sources=tuple(stale),
            critical_gaps=tuple(critical),
        )

    def analyse(self, account_id: str, as_of: date | None = None) -> QuantitativeEvidence:
        """Return the deterministic lane's evidence for one account.

        Args:
            account_id: The account to analyse.
            as_of: An optional earlier cutoff. It can only tighten what is
                visible; the tool layer clamps it.

        Returns:
            Complete evidence, or `available=False` with the gap named.
        """

        window: dict[str, object] = {
            "account_id": account_id,
            "window_weeks": USAGE_WINDOW_WEEKS,
        }
        if as_of is not None:
            window["as_of"] = as_of

        try:
            metrics_response = call_tool(
                self._registry,
                ROLE,
                "compute_account_metrics",
                {k: v for k, v in window.items() if k != "window_weeks"},
                AccountMetricsResponse,
            )
            usage = call_tool(self._registry, ROLE, "get_usage_series", window, UsageSeriesResponse)
            support = call_tool(
                self._registry,
                ROLE,
                "get_support_summary",
                {**window, "window_weeks": SUPPORT_WINDOW_WEEKS},
                SupportSummaryResponse,
            )
            events = call_tool(
                self._registry,
                ROLE,
                "get_external_events",
                {**window, "window_weeks": EVENT_WINDOW_WEEKS},
                ExternalEventsResponse,
            )
        except (ToolUnavailableError, TimeoutError) as error:
            return QuantitativeEvidence(
                account_id=account_id,
                # No tool answered, so the account's own cutoff is unknown here.
                # The dataset horizon is the honest placeholder: nothing is
                # attached to it, and it cannot understate what was visible.
                cutoff=as_of if as_of is not None else DATASET_AS_OF_DATE,
                coverage=CoverageReport(
                    expected_weeks=ADOPTION_WINDOW_WEEKS,
                    observed_weeks=0,
                    critical_gaps=(f"telemetry could not be computed: {error}",),
                ),
                available=False,
            )

        coverage = FeatureCoverage.model_validate(metrics_response.coverage)
        cutoff = metrics_response.cutoff
        report = self._coverage_report(
            coverage, usage, support, events, cutoff, self._artifact is not None
        )

        if self._artifact is None or report.has_critical_gap:
            return QuantitativeEvidence(
                account_id=account_id,
                cutoff=cutoff,
                metrics=self._observations(metrics_response.metrics, coverage),
                coverage=report,
                available=False,
            )

        features = AccountFeatures(
            account_id=account_id,
            cutoff=cutoff,
            values=dict(metrics_response.metrics),
            coverage=coverage,
        )
        forecast = predict_from_features(self._artifact, features)
        drivers = tuple(
            Driver(
                feature=contribution.feature,
                value=round(contribution.value, 6),
                contribution=round(contribution.contribution, 6),
                direction="supports" if contribution.contribution >= 0 else "opposes",
                description=contribution.description,
            )
            for contribution in forecast.top_contributions(MAX_DRIVERS)
        )

        return QuantitativeEvidence(
            account_id=account_id,
            cutoff=cutoff,
            metrics=self._observations(metrics_response.metrics, coverage),
            distribution={name: round(value, 6) for name, value in forecast.probabilities.items()},
            predicted_outcome=forecast.predicted_outcome,
            model_probability=round(forecast.confidence, 6),
            model_name=forecast.model_name,
            drivers=drivers,
            coverage=report,
            available=True,
        )


__all__ = ["MAX_DRIVERS", "STALE_USAGE_DAYS", "QuantitativeAnalyst"]
