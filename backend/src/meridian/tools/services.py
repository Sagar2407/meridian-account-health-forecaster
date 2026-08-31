"""The eight read-only services of plan section 12.1.

Plan section 12 is explicit that business logic is ordinary typed Python first
and MCP second. Everything here is a plain method that takes a validated request
and returns a validated response, so the whole tool surface is unit-testable
with no transport, no server, and no event loop.

The cutoff rule is the same in every service and is applied in one place:
`_cutoff_for` takes the account's own effective cutoff and lets a caller's
`as_of` tighten it, never widen it. A window is then measured backwards from
that cutoff, so no window can reach past it however large it is.
"""

from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd

from meridian.data.constants import DATASET_AS_OF_DATE
from meridian.data.repository import RuntimeRepository
from meridian.features.builder import UNRESOLVED_STATUSES, build_features
from meridian.memory.store import AssessmentStore
from meridian.retrieval.contracts import AccountSourceFamily, Citation
from meridian.retrieval.search import RetrievalService
from meridian.tools.contracts import (
    MAX_USAGE_ROWS,
    AccountEvidenceResponse,
    AccountMetricsResponse,
    AccountProfileResponse,
    AccountRequest,
    EvidenceCitation,
    EvidenceRequest,
    ExternalEvent,
    ExternalEventsResponse,
    KnowledgeRequest,
    KnowledgeResponse,
    PointInTimeRequest,
    PriorAssessment,
    PriorAssessmentsResponse,
    SeverityCount,
    SupportSummaryResponse,
    UsagePoint,
    UsageSeriesResponse,
    WindowedRequest,
    evidence_signal,
)

ESCALATION_CATEGORY = "Escalation"
MAX_EXCERPT_CHARACTERS = 1_200


class ToolUnavailableError(RuntimeError):
    """Raised when a tool needs a collaborator this instance was not given.

    Retrieval needs a built FAISS index and application memory needs a database.
    Neither is required to exercise the deterministic services, so both are
    supplied lazily and their absence is a precise error rather than an
    ``AttributeError`` deep inside a call.
    """


def _to_evidence(citation: Citation) -> EvidenceCitation:
    """Flatten a retrieval citation for transport across the tool boundary."""

    return EvidenceCitation(
        doc_id=citation.parent_id,
        source_type=citation.doc_type,
        subtype=citation.subtype,
        doc_date=citation.doc_date,
        score=round(citation.score, 6),
        excerpt=citation.excerpt[:MAX_EXCERPT_CHARACTERS],
        signal=evidence_signal(citation.doc_type, citation.subtype, citation.source_severity),
    )


class ToolServices:
    """Read-only account services, each enforcing scope and cutoff itself."""

    def __init__(
        self,
        repository: RuntimeRepository,
        retrieval: RetrievalService | Callable[[], RetrievalService] | None = None,
        store: AssessmentStore | Callable[[], AssessmentStore] | None = None,
    ) -> None:
        self._repository = repository
        self._retrieval = retrieval
        self._store = store

    @property
    def repository(self) -> RuntimeRepository:
        """Return the sanitized, cutoff-enforcing repository."""

        return self._repository

    def _retrieval_service(self) -> RetrievalService:
        """Return the retrieval service, building it on first use.

        Raises:
            ToolUnavailableError: If no retrieval service was supplied.
        """

        if self._retrieval is None:
            raise ToolUnavailableError(
                "retrieval is not configured; build the index with `make index`"
            )
        if callable(self._retrieval):
            self._retrieval = self._retrieval()
        return self._retrieval

    def _assessment_store(self) -> AssessmentStore:
        """Return the assessment store, building it on first use.

        Raises:
            ToolUnavailableError: If no assessment store was supplied.
        """

        if self._store is None:
            raise ToolUnavailableError("application memory is not configured")
        if callable(self._store):
            self._store = self._store()
        return self._store

    def _cutoff_for(self, request: AccountRequest) -> date:
        """Return the effective cutoff, which a caller may tighten but not widen.

        Raises:
            UnknownAccountError: If the account is not in the dataset.
        """

        canonical = self._repository.cutoff_for(request.account_id)
        requested = getattr(request, "as_of", None)
        return min(canonical, requested) if requested is not None else canonical

    @staticmethod
    def _window_start(cutoff: date, window_weeks: int) -> date:
        """Return the inclusive start of a trailing window ending at `cutoff`."""

        return cutoff - timedelta(weeks=window_weeks)

    @staticmethod
    def _within(frame: pd.DataFrame, column: str, start: date, cutoff: date) -> pd.DataFrame:
        """Return rows whose date sits inside the closed window."""

        if frame.empty:
            return frame
        dates = pd.to_datetime(frame[column]).dt.date
        return frame.loc[(dates > start) & (dates <= cutoff)]

    def get_account_profile(self, request: AccountRequest) -> AccountProfileResponse:
        """Return sanitized identity and commercial terms for one account."""

        profile = self._repository.profile(request.account_id)
        payload = profile.model_dump(mode="json")
        return AccountProfileResponse(
            cutoff=profile.effective_cutoff,
            account_id=request.account_id,
            profile=payload,
        )

    def compute_account_metrics(self, request: PointInTimeRequest) -> AccountMetricsResponse:
        """Return exact features and the coverage they were computed from."""

        cutoff = self._cutoff_for(request)
        features = build_features(self._repository, request.account_id, cutoff)
        coverage = features.coverage
        return AccountMetricsResponse(
            cutoff=features.cutoff,
            account_id=request.account_id,
            metrics=dict(features.values),
            coverage=coverage.model_dump(),
            thin_families=coverage.thin_families,
        )

    def get_usage_series(self, request: WindowedRequest) -> UsageSeriesResponse:
        """Return a bounded weekly telemetry series, aggregated across products.

        The archive stores one row per product per week. An agent reasoning
        about adoption wants the account's week, so the products are summed
        here rather than leaving each caller to do it differently.
        """

        cutoff = self._cutoff_for(request)
        start = self._window_start(cutoff, request.window_weeks)
        usage = self._within(
            self._repository.usage(request.account_id), "week_start", start, cutoff
        )

        points: list[UsagePoint] = []
        if not usage.empty:
            frame = usage.copy()
            frame["week_start"] = pd.to_datetime(frame["week_start"]).dt.date
            grouped = frame.groupby("week_start", as_index=False).agg(
                active_users=("active_users", "sum"),
                sessions=("sessions", "sum"),
                feature_events=("feature_events", "sum"),
                api_calls=("api_calls", "sum"),
                storage_gb=("storage_gb", "sum"),
                advanced_feature_adoption_pct=("advanced_feature_adoption_pct", "mean"),
            )
            # Keep the most recent weeks when a caller asks for more than the
            # transport cap: recency is what every downstream question needs.
            grouped = grouped.sort_values("week_start").tail(MAX_USAGE_ROWS)
            points = [
                UsagePoint(
                    week_start=row["week_start"],
                    active_users=int(row["active_users"]),
                    sessions=int(row["sessions"]),
                    feature_events=int(row["feature_events"]),
                    api_calls=int(row["api_calls"]),
                    storage_gb=round(float(row["storage_gb"]), 4),
                    advanced_feature_adoption_pct=round(
                        float(row["advanced_feature_adoption_pct"]), 4
                    ),
                )
                for row in grouped.to_dict("records")
            ]

        return UsageSeriesResponse(
            cutoff=cutoff,
            account_id=request.account_id,
            window_weeks=request.window_weeks,
            points=tuple(points),
            licensed_seats=self._repository.profile(request.account_id).licensed_seats,
        )

    def get_support_summary(self, request: WindowedRequest) -> SupportSummaryResponse:
        """Return ticket counts, severity mix, sentiment, and CSAT for the window."""

        cutoff = self._cutoff_for(request)
        start = self._window_start(cutoff, request.window_weeks)
        tickets = self._within(
            self._repository.tickets(request.account_id), "created_date", start, cutoff
        )

        if tickets.empty:
            return SupportSummaryResponse(
                cutoff=cutoff,
                account_id=request.account_id,
                window_weeks=request.window_weeks,
                tickets=0,
                unresolved_tickets=0,
                escalations=0,
                by_priority=(),
                mean_sentiment=None,
                mean_csat=None,
                responses_with_csat=0,
                ticket_ids=(),
            )

        sentiment = pd.to_numeric(tickets["sentiment"], errors="coerce").dropna()
        csat = pd.to_numeric(tickets["csat"], errors="coerce").dropna()
        priorities = tickets["priority"].value_counts().sort_index()
        return SupportSummaryResponse(
            cutoff=cutoff,
            account_id=request.account_id,
            window_weeks=request.window_weeks,
            tickets=len(tickets),
            unresolved_tickets=int(tickets["status"].isin(UNRESOLVED_STATUSES).sum()),
            escalations=int((tickets["category"] == ESCALATION_CATEGORY).sum()),
            by_priority=tuple(
                SeverityCount(priority=str(name), tickets=int(count))
                for name, count in priorities.items()
            ),
            mean_sentiment=round(float(sentiment.mean()), 4) if not sentiment.empty else None,
            mean_csat=round(float(csat.mean()), 4) if not csat.empty else None,
            responses_with_csat=len(csat),
            ticket_ids=tuple(str(value) for value in tickets["ticket_id"]),
        )

    def get_external_events(self, request: WindowedRequest) -> ExternalEventsResponse:
        """Return external events inside the window, capped at the dataset horizon."""

        cutoff = self._cutoff_for(request)
        start = self._window_start(cutoff, request.window_weeks)
        events = self._within(
            self._repository.events(request.account_id), "event_date", start, cutoff
        )
        return ExternalEventsResponse(
            cutoff=cutoff,
            account_id=request.account_id,
            window_weeks=request.window_weeks,
            events=tuple(
                ExternalEvent(
                    event_date=pd.Timestamp(row["event_date"]).date(),
                    event_type=str(row["event_type"]),
                    polarity=int(str(row["polarity"])),
                    source=str(row["source"]),
                    headline=str(row["headline"]),
                )
                for row in events.to_dict("records")
            ),
        )

    def retrieve_account_evidence(self, request: EvidenceRequest) -> AccountEvidenceResponse:
        """Return graded, account-scoped citations for one sub-goal."""

        cutoff = self._cutoff_for(request)
        families: tuple[AccountSourceFamily, ...] | None = request.source_families
        result = self._retrieval_service().retrieve(
            request.account_id,
            request.sub_goal,
            requested_as_of=cutoff,
            allowed_source_families=families,
            include_knowledge_base=False,
        )
        return AccountEvidenceResponse(
            cutoff=result.cutoff,
            account_id=request.account_id,
            sub_goal=request.sub_goal,
            citations=tuple(_to_evidence(citation) for citation in result.account_citations),
            source_coverage=dict(result.source_coverage),
            attempted_queries=result.attempted_queries,
            insufficient_evidence=result.insufficient_evidence,
            insufficiency_reason=result.insufficiency_reason,
        )

    def retrieve_knowledge(self, request: KnowledgeRequest) -> KnowledgeResponse:
        """Return knowledge-base guidance, which carries no account scope."""

        citations = self._retrieval_service().search_knowledge(request.sub_goal)
        return KnowledgeResponse(
            # Guidance is undated, so the dataset horizon is the honest cutoff
            # to report: nothing here was filtered by an account's own date.
            cutoff=DATASET_AS_OF_DATE,
            sub_goal=request.sub_goal,
            citations=tuple(_to_evidence(citation) for citation in citations),
        )

    def get_prior_assessments(self, request: AccountRequest) -> PriorAssessmentsResponse:
        """Return this system's own previous decisions for one account."""

        # Touch the repository so an unknown account fails the same way here as
        # in every other tool, rather than returning an empty history.
        cutoff = self._repository.cutoff_for(request.account_id)
        records = self._assessment_store().recent_assessments(request.account_id)
        return PriorAssessmentsResponse(
            cutoff=cutoff,
            account_id=request.account_id,
            assessments=tuple(
                PriorAssessment(
                    assessment_id=record.assessment_id,
                    account_id=record.account_id,
                    created_at=record.created_at,
                    cutoff=record.cutoff,
                    predicted_outcome=record.predicted_outcome,
                    confidence=record.confidence,
                    decision=record.decision,
                    summary=record.summary,
                )
                for record in records
            ),
        )
