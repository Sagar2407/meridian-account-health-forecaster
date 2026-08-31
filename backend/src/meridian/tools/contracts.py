"""Typed request and response contracts for the read-only tool layer (plan section 12).

Every tool argument is validated here before any service runs, and every result
is validated again on the way out. The plan calls for tools that hold their
guarantees "even when called with malicious arguments", which means the contract
cannot be a formality: an account id is a pattern, a window is a bounded
integer, and the one free-text argument a caller controls is checked for the
shapes that would signal an attempt to reach a path, a database, or a URL.

Nothing here reaches the network or the filesystem. These are pure schemas.
"""

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from meridian.data.constants import DATASET_AS_OF_DATE, FORBIDDEN_RUNTIME_FIELDS

#: The four agents of plan section 13. Roles are part of the contract because
#: section 12.3 allowlists tools per role, so a call is only meaningful when it
#: says who is making it.
RequesterRole = Literal[
    "orchestrator",
    "quantitative_analyst",
    "evidence_retriever",
    "forecast_adjudicator",
]

ACCOUNT_ID_PATTERN = r"^ACC-\d{1,8}$"
MAX_SUB_GOAL_CHARACTERS = 400
MAX_USAGE_ROWS = 520
DEFAULT_WINDOW_WEEKS = 26
MAX_WINDOW_WEEKS = 260

#: Shapes that have no business in a natural-language sub-goal and that would
#: signal an attempt to reach something the tool layer does not expose. This is
#: a rejection rule, not a sanitizer: a matching argument is refused outright
#: rather than silently cleaned, so a caller cannot probe for what gets through.
_UNSAFE_SUB_GOAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a URL or network scheme", re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)),
    ("a filesystem path", re.compile(r"(?:\.\./|\.\.\\|^~|^/|\b[A-Za-z]:\\)")),
    # Bare metacharacters are not enough to reject on: business prose really
    # does contain "R&D", "adoption < 50%", and "sponsor change; low usage".
    # What has no innocent reading is a substitution, or a separator followed
    # by a command name.
    ("a shell substitution", re.compile(r"[`]|\$\(|\$\{")),
    (
        "a shell command chain",
        re.compile(
            r"[;&|]{1,2}\s*(?:rm|cat|curl|wget|sh|bash|zsh|python\d?|perl|ruby|nc|ncat"
            r"|chmod|chown|mv|cp|dd|eval|exec|export|sudo|kill|shutdown)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SQL",
        re.compile(
            r"\b(?:select|insert|update|delete|drop|alter|union|exec|truncate)\b\s+"
            r"(?:\*|all|distinct|into|from|table|set|values|top|\w+\s*\()",
            re.IGNORECASE,
        ),
    ),
    ("a control character", re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")),
)


def assert_safe_text(value: str, field: str) -> str:
    """Return `value` unchanged, or raise if it carries an injection shape.

    Raises:
        ValueError: If the text looks like a path, URL, shell fragment, SQL, or
            carries control characters.
    """

    for label, pattern in _UNSAFE_SUB_GOAL_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{field} must be plain language; it contains {label}")
    return value


AccountId = Annotated[str, Field(pattern=ACCOUNT_ID_PATTERN, max_length=32)]


class ToolRequest(BaseModel):
    """Common base: who is asking. Extra fields are refused, never ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: RequesterRole


class AccountRequest(ToolRequest):
    """A request scoped to exactly one account."""

    account_id: AccountId


class PointInTimeRequest(AccountRequest):
    """An account request that may tighten, but never widen, the cutoff.

    `as_of` is a request, not a grant. Services clamp it against the account's
    own effective cutoff, so a caller passing a later date sees no more than it
    would have seen anyway.
    """

    as_of: date | None = None

    @field_validator("as_of")
    @classmethod
    def reject_dates_beyond_the_dataset(cls, value: date | None) -> date | None:
        """Refuse an as-of date past the dataset horizon rather than clamping it.

        Clamping would be safe but silent. A caller asking for 2027 has made a
        mistake worth surfacing.
        """

        if value is not None and value > DATASET_AS_OF_DATE:
            raise ValueError(f"as_of must not exceed the dataset horizon {DATASET_AS_OF_DATE}")
        return value


class WindowedRequest(PointInTimeRequest):
    """A point-in-time request over a bounded trailing window."""

    window_weeks: int = Field(default=DEFAULT_WINDOW_WEEKS, ge=1, le=MAX_WINDOW_WEEKS)


class EvidenceRequest(PointInTimeRequest):
    """A retrieval request carrying the one free-text argument in the layer."""

    sub_goal: str = Field(min_length=3, max_length=MAX_SUB_GOAL_CHARACTERS)
    source_families: tuple[Literal["csm_note", "support_ticket", "external_event"], ...] | None = (
        None
    )

    @field_validator("sub_goal")
    @classmethod
    def sub_goal_must_be_plain_language(cls, value: str) -> str:
        """Reject a sub-goal that carries an injection shape."""

        return assert_safe_text(" ".join(value.split()), "sub_goal")


class KnowledgeRequest(ToolRequest):
    """Knowledge-base guidance is not account scoped, so it carries no account id."""

    sub_goal: str = Field(min_length=3, max_length=MAX_SUB_GOAL_CHARACTERS)

    @field_validator("sub_goal")
    @classmethod
    def sub_goal_must_be_plain_language(cls, value: str) -> str:
        """Reject a sub-goal that carries an injection shape."""

        return assert_safe_text(" ".join(value.split()), "sub_goal")


class ToolResponse(BaseModel):
    """Common base for every tool result.

    `cutoff` is on every response on purpose: it is the single fact a reviewer
    needs to check that an answer was point-in-time safe, so it travels with the
    answer rather than living only in a log.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cutoff: date


class AccountProfileResponse(ToolResponse):
    """Sanitized identity and commercial terms for one account."""

    account_id: AccountId
    profile: dict[str, object]

    @field_validator("profile")
    @classmethod
    def profile_must_not_carry_a_forbidden_field(
        cls, value: dict[str, object]
    ) -> dict[str, object]:
        """Re-check the allowlist at the boundary, not only at the repository."""

        leaked = sorted(set(value) & FORBIDDEN_RUNTIME_FIELDS)
        if leaked:
            raise ValueError(f"profile leaks forbidden fields: {leaked}")
        return value


class AccountMetricsResponse(ToolResponse):
    """Exact features plus the coverage they were computed from."""

    account_id: AccountId
    metrics: dict[str, float]
    coverage: dict[str, int]
    thin_families: tuple[str, ...]

    @field_validator("metrics")
    @classmethod
    def metrics_must_not_carry_a_forbidden_field(cls, value: dict[str, float]) -> dict[str, float]:
        """A latent target must never reach an agent as a metric."""

        leaked = sorted(set(value) & FORBIDDEN_RUNTIME_FIELDS)
        if leaked:
            raise ValueError(f"metrics leak forbidden fields: {leaked}")
        return value


class UsagePoint(BaseModel):
    """One week of aggregated telemetry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    week_start: date
    active_users: int
    sessions: int
    feature_events: int
    api_calls: int
    storage_gb: float
    advanced_feature_adoption_pct: float


class UsageSeriesResponse(ToolResponse):
    """A bounded weekly series, aggregated across products."""

    account_id: AccountId
    window_weeks: int
    points: tuple[UsagePoint, ...] = Field(max_length=MAX_USAGE_ROWS)
    licensed_seats: int

    @field_validator("points")
    @classmethod
    def points_must_be_ordered(cls, value: tuple[UsagePoint, ...]) -> tuple[UsagePoint, ...]:
        """A series a caller has to sort itself invites off-by-one reasoning."""

        weeks = [point.week_start for point in value]
        if weeks != sorted(weeks):
            raise ValueError("usage points must be in ascending week order")
        return value


class SeverityCount(BaseModel):
    """Ticket volume at one priority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    priority: str
    tickets: int


class SupportSummaryResponse(ToolResponse):
    """Counts, severity mix, sentiment, and CSAT over the window."""

    account_id: AccountId
    window_weeks: int
    tickets: int
    unresolved_tickets: int
    escalations: int
    by_priority: tuple[SeverityCount, ...]
    mean_sentiment: float | None
    mean_csat: float | None
    responses_with_csat: int
    ticket_ids: tuple[str, ...]


class ExternalEvent(BaseModel):
    """One verified external event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_date: date
    event_type: str
    polarity: int = Field(ge=-1, le=1)
    source: str
    headline: str


class ExternalEventsResponse(ToolResponse):
    """External events inside the window, capped at the dataset horizon."""

    account_id: AccountId
    window_weeks: int
    events: tuple[ExternalEvent, ...]


#: Which way a piece of evidence points. Derived only from structured source
#: metadata -- the ticket's category and priority, the note's type, the event's
#: recorded polarity -- and never by reading the excerpt. A sentiment model over
#: retrieved text would be a second, unvalidated classifier deciding which
#: evidence counts as contradicting a forecast, and the dataset already records
#: the polarity of every external event exactly.
EvidenceSignal = Literal["adverse", "favorable", "neutral"]

ADVERSE_TICKET_CATEGORIES: frozenset[str] = frozenset(
    {"Escalation", "Bug / Defect", "Performance / Outage"}
)
ADVERSE_TICKET_PRIORITIES: frozenset[str] = frozenset({"P1", "P2"})
ADVERSE_NOTE_TYPES: frozenset[str] = frozenset({"Escalation / Save Play"})
FAVORABLE_NOTE_TYPES: frozenset[str] = frozenset({"Expansion Discussion"})


def evidence_signal(source_type: str, subtype: str, source_severity: str | None) -> EvidenceSignal:
    """Return the direction a source document points, from its metadata alone.

    Args:
        source_type: The source family, for example `support_ticket`.
        subtype: The ticket category, note type, or event type.
        source_severity: Ticket priority for tickets, recorded polarity for
            external events, empty for notes and knowledge articles.

    Returns:
        `adverse`, `favorable`, or `neutral`.
    """

    severity = (source_severity or "").strip()
    if source_type == "external_event":
        # The document builder already renders the dataset's +1/0/-1 polarity
        # into these words, so this is the generator's own label, not a guess.
        if severity in ("adverse", "favorable"):
            return "adverse" if severity == "adverse" else "favorable"
        return "neutral"
    if source_type == "support_ticket":
        if subtype in ADVERSE_TICKET_CATEGORIES or severity in ADVERSE_TICKET_PRIORITIES:
            return "adverse"
        return "neutral"
    if source_type == "csm_note":
        if subtype in ADVERSE_NOTE_TYPES:
            return "adverse"
        if subtype in FAVORABLE_NOTE_TYPES:
            return "favorable"
    return "neutral"


class EvidenceCitation(BaseModel):
    """A citation flattened for transport, with its provenance intact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    source_type: str
    subtype: str
    doc_date: date | None
    score: float
    excerpt: str
    signal: EvidenceSignal = "neutral"


class AccountEvidenceResponse(ToolResponse):
    """Account-scoped citations plus the coverage that produced them."""

    account_id: AccountId
    sub_goal: str
    citations: tuple[EvidenceCitation, ...] = Field(max_length=5)
    source_coverage: dict[str, int]
    attempted_queries: tuple[str, ...]
    insufficient_evidence: bool
    insufficiency_reason: str | None = None

    @field_validator("citations")
    @classmethod
    def citations_must_be_dated(
        cls, value: tuple[EvidenceCitation, ...]
    ) -> tuple[EvidenceCitation, ...]:
        """Undated account evidence cannot be shown to be point-in-time safe."""

        if any(citation.doc_date is None for citation in value):
            raise ValueError("account evidence must be dated")
        return value


class KnowledgeResponse(ToolResponse):
    """Knowledge-base guidance, which is general and carries no account scope."""

    sub_goal: str
    citations: tuple[EvidenceCitation, ...] = Field(max_length=2)

    @field_validator("citations")
    @classmethod
    def guidance_must_be_undated(
        cls, value: tuple[EvidenceCitation, ...]
    ) -> tuple[EvidenceCitation, ...]:
        """A dated knowledge article would be account evidence in disguise."""

        if any(citation.doc_date is not None for citation in value):
            raise ValueError("knowledge citations must not carry a document date")
        return value


class PriorAssessment(BaseModel):
    """One previously recorded advisory decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment_id: str
    account_id: AccountId
    created_at: str
    cutoff: date
    predicted_outcome: str
    confidence: float = Field(ge=0.0, le=1.0)
    decision: str
    summary: str


class PriorAssessmentsResponse(ToolResponse):
    """Prior assessments for one account, newest first."""

    account_id: AccountId
    assessments: tuple[PriorAssessment, ...]
