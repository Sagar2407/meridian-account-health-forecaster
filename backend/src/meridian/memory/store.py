"""Application memory: assessments, review cases, and regression records.

Plan sections 12.2, 17.2, and 21.4. These are the system's own records of what
it decided and what a human said about it, not writes to Meridian source data.
That distinction is the whole point of the module, so it is enforced rather than
documented: the store refuses to open a database anywhere under the raw archive.

Section 21.4 asks that reviewer overrides become "versioned regression cases",
and that is the reason the review tables are shaped the way they are. A resolved
case records the action, the reason code, and the note; an action that
contradicts what the system released also writes a regression row, in the same
transaction, so a released answer a human corrected cannot exist without the
record that would let a later change be tested against it.

SQLite behind a typed interface, per ADR 0006. Callers get dataclasses; no SQL
text and no connection object escapes this module.
"""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.data.paths import application_directory, raw_dataset_directory

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    # `meridian.contracts` reaches this module through the tool package, so a
    # runtime import here would close the cycle. The store only reads a
    # reviewer decision's attributes; it never constructs one.
    from meridian.contracts import ReviewerDecision

STORE_FILENAME = "assessments.sqlite"
DEFAULT_HISTORY_LIMIT = 5
MAX_HISTORY_LIMIT = 50
DEFAULT_QUEUE_LIMIT = 50
MAX_QUEUE_LIMIT = 500

#: Where a regression case came from (plan section 21.4). Every one of these is
#: a case the system got wrong or could not answer, which is what a regression
#: suite is built from -- an approval is not one of them.
REGRESSION_ORIGINS: frozenset[str] = frozenset(
    {
        "reviewer_override",
        "reviewer_data_request",
        "reviewer_escalation",
        "verification_failure",
        "retrieval_exhausted",
        "model_error",
        "guardrail_false_pass",
    }
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id     TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL,
    sequence          INTEGER NOT NULL,
    created_at        TEXT NOT NULL,
    cutoff            TEXT NOT NULL,
    predicted_outcome TEXT NOT NULL,
    confidence        REAL NOT NULL,
    decision          TEXT NOT NULL,
    summary           TEXT NOT NULL,
    UNIQUE (account_id, sequence)
);
CREATE INDEX IF NOT EXISTS assessments_account ON assessments(account_id, sequence DESC);
CREATE TABLE IF NOT EXISTS review_cases (
    case_id       TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id),
    account_id    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    reason        TEXT NOT NULL,
    status        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS review_cases_account ON review_cases(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS review_cases_status ON review_cases(status, created_at DESC);
CREATE TABLE IF NOT EXISTS regression_cases (
    regression_id    TEXT PRIMARY KEY,
    case_id          TEXT,
    assessment_id    TEXT,
    account_id       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    origin           TEXT NOT NULL,
    cutoff           TEXT NOT NULL,
    question         TEXT NOT NULL,
    system_outcome   TEXT NOT NULL,
    reviewer_outcome TEXT,
    reason_code      TEXT NOT NULL,
    note             TEXT NOT NULL,
    confidence       REAL NOT NULL,
    route            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS regression_origin ON regression_cases(origin, created_at DESC);
"""

#: Columns added after the Phase 5 schema shipped. They are applied by
#: `ALTER TABLE` rather than by recreating the table, so a database written by
#: an earlier phase keeps its rows.
_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "assessments": (
        ("question", "TEXT NOT NULL DEFAULT ''"),
        ("kind", "TEXT NOT NULL DEFAULT 'forecast'"),
        ("card", "TEXT NOT NULL DEFAULT ''"),
    ),
    "review_cases": (
        ("route", "TEXT NOT NULL DEFAULT 'red'"),
        ("reason_codes", "TEXT NOT NULL DEFAULT ''"),
        ("resolved_at", "TEXT"),
        ("reviewer", "TEXT"),
        ("action", "TEXT"),
        ("reason_code", "TEXT"),
        ("note", "TEXT"),
        ("corrected_outcome", "TEXT"),
        ("requested_data", "TEXT NOT NULL DEFAULT '[]'"),
    ),
}


class AssessmentStoreError(RuntimeError):
    """Raised when the store is misconfigured or asked for something impossible."""


@dataclass(frozen=True)
class AssessmentRecord:
    """One recorded advisory decision."""

    assessment_id: str
    account_id: str
    created_at: str
    cutoff: date
    predicted_outcome: str
    confidence: float
    decision: str
    summary: str
    question: str = ""
    kind: str = "forecast"
    card: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewCase:
    """One case routed to a human reviewer (plan section 16.6)."""

    case_id: str
    assessment_id: str
    account_id: str
    created_at: str
    reason: str
    status: str
    route: str = "red"
    reason_codes: tuple[str, ...] = ()
    resolved_at: str | None = None
    reviewer: str | None = None
    action: str | None = None
    reason_code: str | None = None
    note: str | None = None
    corrected_outcome: str | None = None
    requested_data: tuple[dict[str, str], ...] = ()

    @property
    def open(self) -> bool:
        """Return whether this case is still waiting for a reviewer."""

        return self.status == "open"


@dataclass(frozen=True)
class RegressionCase:
    """One versioned regression record (plan section 21.4)."""

    regression_id: str
    case_id: str | None
    assessment_id: str | None
    account_id: str
    created_at: str
    origin: str
    cutoff: date
    question: str
    system_outcome: str
    reviewer_outcome: str | None
    reason_code: str
    note: str
    confidence: float
    route: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view for the export artifact."""

        payload = asdict(self)
        payload["cutoff"] = self.cutoff.isoformat()
        return payload


def _now() -> str:
    """Return the current UTC timestamp in ISO form."""

    return datetime.now(UTC).isoformat(timespec="seconds")


def _codes(raw: object) -> tuple[str, ...]:
    """Return a stored comma-separated reason-code list as a tuple."""

    text = str(raw or "")
    return tuple(code for code in (part.strip() for part in text.split(",")) if code)


def _requested_data(raw: object) -> tuple[dict[str, str], ...]:
    """Return the stored JSON request list, failing closed on an old bad row."""

    try:
        decoded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(
        {str(key): str(value) for key, value in item.items()}
        for item in decoded
        if isinstance(item, dict)
    )


class AssessmentStore:
    """Read and write the system's own advisory history."""

    def __init__(self, path: Path | None = None) -> None:
        target = path if path is not None else application_directory() / STORE_FILENAME
        resolved = target.expanduser().resolve()
        archive = raw_dataset_directory().resolve()
        # Source data is immutable by policy. Making that a constructor error
        # means a misconfigured path fails at startup rather than after a write.
        if resolved == archive or archive in resolved.parents:
            raise AssessmentStoreError(
                f"application state must not be written inside the raw archive: {resolved}"
            )
        self.path = resolved

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection with foreign keys on and row access by name."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection

    def initialise(self) -> None:
        """Create the schema if it does not already exist, and migrate it if it does."""

        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            for table, columns in _ADDED_COLUMNS.items():
                present = {
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for name, definition in columns:
                    if name not in present:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            connection.commit()

    # -- Assessments ---------------------------------------------------------

    def record_assessment(
        self,
        account_id: str,
        cutoff: date,
        predicted_outcome: str,
        confidence: float,
        decision: str,
        summary: str,
        created_at: str | None = None,
        question: str = "",
        kind: str = "forecast",
        card: dict[str, object] | None = None,
    ) -> AssessmentRecord:
        """Append one assessment and return it.

        The identifier is derived from the account and a per-account sequence
        rather than a random value, so a test can assert on it and a reviewer
        can see the order at a glance.

        Args:
            account_id: The account assessed.
            cutoff: The effective point-in-time cutoff.
            predicted_outcome: The released label, or `insufficient_evidence`.
            confidence: The evidence-aware confidence, in [0, 1].
            decision: The human-review band this run was assigned.
            summary: A short human-readable line for a list view.
            created_at: Overrides the timestamp, for deterministic tests.
            question: The question that was asked, kept so a regression case
                can be replayed rather than guessed at.
            kind: `forecast` or `insufficient_evidence`.
            card: The full decision card, stored so the review queue can show a
                reviewer what they are being asked about (section 16.6).

        Raises:
            AssessmentStoreError: If `confidence` is outside [0, 1].
        """

        if not 0.0 <= confidence <= 1.0:
            raise AssessmentStoreError("confidence must be between 0 and 1")
        self.initialise()
        stamp = created_at if created_at is not None else _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM assessments "
                "WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            sequence = int(row["next"])
            assessment_id = f"ASMT-{account_id}-{sequence:04d}"
            connection.execute(
                "INSERT INTO assessments (assessment_id, account_id, sequence, created_at, "
                "cutoff, predicted_outcome, confidence, decision, summary, question, kind, card) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    assessment_id,
                    account_id,
                    sequence,
                    stamp,
                    cutoff.isoformat(),
                    predicted_outcome,
                    float(confidence),
                    decision,
                    summary,
                    question,
                    kind,
                    json.dumps(card or {}, sort_keys=True, default=str),
                ),
            )
            connection.commit()
        return AssessmentRecord(
            assessment_id=assessment_id,
            account_id=account_id,
            created_at=stamp,
            cutoff=cutoff,
            predicted_outcome=predicted_outcome,
            confidence=float(confidence),
            decision=decision,
            summary=summary,
            question=question,
            kind=kind,
            card=dict(card or {}),
        )

    @staticmethod
    def _assessment(row: sqlite3.Row) -> AssessmentRecord:
        """Return one assessment row as a record."""

        keys = row.keys()
        raw_card = str(row["card"]) if "card" in keys else ""
        try:
            card = json.loads(raw_card) if raw_card else {}
        except json.JSONDecodeError:
            card = {}
        return AssessmentRecord(
            assessment_id=str(row["assessment_id"]),
            account_id=str(row["account_id"]),
            created_at=str(row["created_at"]),
            cutoff=date.fromisoformat(str(row["cutoff"])),
            predicted_outcome=str(row["predicted_outcome"]),
            confidence=float(row["confidence"]),
            decision=str(row["decision"]),
            summary=str(row["summary"]),
            question=str(row["question"]) if "question" in keys else "",
            kind=str(row["kind"]) if "kind" in keys else "forecast",
            card=card if isinstance(card, dict) else {},
        )

    def recent_assessments(
        self, account_id: str, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> tuple[AssessmentRecord, ...]:
        """Return this account's assessments, newest first.

        Raises:
            AssessmentStoreError: If `limit` is not between 1 and the cap.
        """

        if not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise AssessmentStoreError(f"limit must be between 1 and {MAX_HISTORY_LIMIT}")
        if not self.path.is_file():
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM assessments WHERE account_id = ? ORDER BY sequence DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        return tuple(self._assessment(row) for row in rows)

    def assessment(self, assessment_id: str) -> AssessmentRecord | None:
        """Return one recorded assessment, or None if it was never written."""

        if not self.path.is_file():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assessments WHERE assessment_id = ?", (assessment_id,)
            ).fetchone()
        return self._assessment(row) if row is not None else None

    # -- Review cases --------------------------------------------------------

    def open_review_case(
        self,
        assessment_id: str,
        reason: str,
        created_at: str | None = None,
        route: str = "red",
        reason_codes: Sequence[str] = (),
    ) -> ReviewCase:
        """Route one recorded assessment to human review.

        Raises:
            AssessmentStoreError: If `assessment_id` was never recorded.
        """

        self.initialise()
        stamp = created_at if created_at is not None else _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            owner = connection.execute(
                "SELECT account_id FROM assessments WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
            if owner is None:
                raise AssessmentStoreError(f"unknown assessment {assessment_id}")
            account_id = str(owner["account_id"])
            existing = connection.execute(
                "SELECT case_id FROM review_cases WHERE assessment_id = ? "
                "ORDER BY case_id DESC LIMIT 1",
                (assessment_id,),
            ).fetchone()
            next_sequence = (
                int(str(existing["case_id"]).rsplit("-", 1)[1]) + 1 if existing is not None else 1
            )
            case_id = f"CASE-{assessment_id.removeprefix('ASMT-')}-{next_sequence:02d}"
            connection.execute(
                "INSERT INTO review_cases (case_id, assessment_id, account_id, created_at, "
                "reason, status, route, reason_codes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    assessment_id,
                    account_id,
                    stamp,
                    reason,
                    "open",
                    route,
                    ",".join(reason_codes),
                ),
            )
            connection.commit()
        return ReviewCase(
            case_id=case_id,
            assessment_id=assessment_id,
            account_id=account_id,
            created_at=stamp,
            reason=reason,
            status="open",
            route=route,
            reason_codes=tuple(reason_codes),
        )

    @staticmethod
    def _case(row: sqlite3.Row) -> ReviewCase:
        """Return one review-case row as a record."""

        keys = row.keys()

        def optional(name: str) -> str | None:
            value = row[name] if name in keys else None
            return str(value) if value is not None else None

        return ReviewCase(
            case_id=str(row["case_id"]),
            assessment_id=str(row["assessment_id"]),
            account_id=str(row["account_id"]),
            created_at=str(row["created_at"]),
            reason=str(row["reason"]),
            status=str(row["status"]),
            route=str(row["route"]) if "route" in keys else "red",
            reason_codes=_codes(row["reason_codes"]) if "reason_codes" in keys else (),
            resolved_at=optional("resolved_at"),
            reviewer=optional("reviewer"),
            action=optional("action"),
            reason_code=optional("reason_code"),
            note=optional("note"),
            corrected_outcome=optional("corrected_outcome"),
            requested_data=(
                _requested_data(row["requested_data"]) if "requested_data" in keys else ()
            ),
        )

    def review_cases(self, account_id: str) -> tuple[ReviewCase, ...]:
        """Return open and closed review cases for one account, newest first."""

        if not self.path.is_file():
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM review_cases WHERE account_id = ? "
                "ORDER BY created_at DESC, case_id DESC",
                (account_id,),
            ).fetchall()
        return tuple(self._case(row) for row in rows)

    def review_queue(
        self, status: str = "open", limit: int = DEFAULT_QUEUE_LIMIT
    ) -> tuple[ReviewCase, ...]:
        """Return the review queue across every account, newest first.

        Args:
            status: `open`, `resolved`, or `all`.
            limit: How many cases to return.

        Raises:
            AssessmentStoreError: If `status` or `limit` is outside its bounds.
        """

        if status not in {"open", "resolved", "all"}:
            raise AssessmentStoreError("status must be open, resolved, or all")
        if not 1 <= limit <= MAX_QUEUE_LIMIT:
            raise AssessmentStoreError(f"limit must be between 1 and {MAX_QUEUE_LIMIT}")
        if not self.path.is_file():
            return ()
        query = "SELECT * FROM review_cases"
        parameters: tuple[object, ...] = ()
        if status != "all":
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY created_at DESC, case_id DESC LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (*parameters, limit)).fetchall()
        return tuple(self._case(row) for row in rows)

    def review_case(self, case_id: str) -> ReviewCase | None:
        """Return one review case, or None if there is no such case."""

        if not self.path.is_file():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM review_cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return self._case(row) if row is not None else None

    def resolve_review_case(
        self,
        decision: "ReviewerDecision",
        resolved_at: str | None = None,
    ) -> tuple[ReviewCase, RegressionCase | None]:
        """Apply a reviewer's typed decision and record the regression it implies.

        This is the single place a case is closed, whichever path the reviewer
        arrived by: the paused-run resume and the review API both call it. That
        is deliberate -- the Phase 7 exit gate is that an override leaves a
        traceable regression record, and a second closing path would be a second
        place for that to be forgotten.

        Args:
            decision: The reviewer's typed action.
            resolved_at: Overrides the timestamp, for deterministic tests.

        Returns:
            The resolved case, and the regression record when one was required.

        Raises:
            AssessmentStoreError: If the case does not exist or is already resolved.
        """

        self.initialise()
        stamp = resolved_at if resolved_at is not None else _now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT r.*, a.cutoff AS assessment_cutoff, a.question AS assessment_question, "
                "a.predicted_outcome AS assessment_outcome, "
                "a.confidence AS assessment_confidence "
                "FROM review_cases AS r JOIN assessments AS a "
                "ON a.assessment_id = r.assessment_id WHERE r.case_id = ?",
                (decision.case_id,),
            ).fetchone()
            if row is None:
                raise AssessmentStoreError(f"unknown review case {decision.case_id}")
            existing = self._case(row)
            if not existing.open:
                raise AssessmentStoreError(
                    f"review case {decision.case_id} was already resolved by {existing.reviewer}"
                )
            requested = json.dumps(
                [item.model_dump(mode="json") for item in decision.requested_data],
                sort_keys=True,
            )
            connection.execute(
                "UPDATE review_cases SET status = ?, resolved_at = ?, reviewer = ?, action = ?, "
                "reason_code = ?, note = ?, corrected_outcome = ?, requested_data = ? "
                "WHERE case_id = ? AND status = 'open'",
                (
                    "resolved",
                    stamp,
                    decision.reviewer,
                    decision.action,
                    decision.reason_code,
                    decision.note,
                    decision.corrected_outcome,
                    requested,
                    decision.case_id,
                ),
            )
            regression: RegressionCase | None = None
            if decision.creates_regression_case:
                origin = {
                    "override": "reviewer_override",
                    "request_data": "reviewer_data_request",
                    "escalate": "reviewer_escalation",
                }[decision.action]
                regression = self._insert_regression(
                    connection=connection,
                    account_id=existing.account_id,
                    origin=origin,
                    cutoff=date.fromisoformat(str(row["assessment_cutoff"])),
                    question=str(row["assessment_question"]),
                    system_outcome=str(row["assessment_outcome"]),
                    reviewer_outcome=decision.corrected_outcome,
                    reason_code=decision.reason_code,
                    note=decision.note or f"reviewer {decision.action} with no note",
                    confidence=float(row["assessment_confidence"]),
                    route=existing.route,
                    case_id=existing.case_id,
                    assessment_id=existing.assessment_id,
                    created_at=stamp,
                )
            resolved_row = connection.execute(
                "SELECT * FROM review_cases WHERE case_id = ?", (decision.case_id,)
            ).fetchone()
            assert resolved_row is not None
            resolved = self._case(resolved_row)
            connection.commit()
        return resolved, regression

    # -- Regression cases ----------------------------------------------------

    def record_regression(
        self,
        account_id: str,
        origin: str,
        cutoff: date,
        question: str,
        system_outcome: str,
        reason_code: str,
        note: str,
        confidence: float,
        route: str,
        reviewer_outcome: str | None = None,
        case_id: str | None = None,
        assessment_id: str | None = None,
        created_at: str | None = None,
    ) -> RegressionCase:
        """Append one regression record (plan section 21.4).

        `case_id` is nullable because not every regression comes from a review
        case: section 21.4 also names guardrail false passes, which are found by
        the offline safety evaluation and have no run behind them.

        Raises:
            AssessmentStoreError: If `origin` is not one of the known origins.
        """

        if origin not in REGRESSION_ORIGINS:
            raise AssessmentStoreError(
                f"unknown regression origin {origin!r}; "
                f"expected one of {sorted(REGRESSION_ORIGINS)}"
            )
        if not 0.0 <= confidence <= 1.0:
            raise AssessmentStoreError("confidence must be between 0 and 1")
        self.initialise()
        stamp = created_at if created_at is not None else _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            regression = self._insert_regression(
                connection=connection,
                account_id=account_id,
                origin=origin,
                cutoff=cutoff,
                question=question,
                system_outcome=system_outcome,
                reviewer_outcome=reviewer_outcome,
                reason_code=reason_code,
                note=note,
                confidence=confidence,
                route=route,
                case_id=case_id,
                assessment_id=assessment_id,
                created_at=stamp,
            )
            connection.commit()
        return regression

    @staticmethod
    def _insert_regression(
        connection: sqlite3.Connection,
        account_id: str,
        origin: str,
        cutoff: date,
        question: str,
        system_outcome: str,
        reviewer_outcome: str | None,
        reason_code: str,
        note: str,
        confidence: float,
        route: str,
        case_id: str | None,
        assessment_id: str | None,
        created_at: str,
    ) -> RegressionCase:
        """Insert a regression on the caller's transaction and return it."""

        latest = connection.execute(
            "SELECT regression_id FROM regression_cases ORDER BY regression_id DESC LIMIT 1"
        ).fetchone()
        sequence = int(str(latest["regression_id"]).removeprefix("REG-")) + 1 if latest else 1
        regression_id = f"REG-{sequence:05d}"
        connection.execute(
            "INSERT INTO regression_cases (regression_id, case_id, assessment_id, account_id, "
            "created_at, origin, cutoff, question, system_outcome, reviewer_outcome, "
            "reason_code, note, confidence, route) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                regression_id,
                case_id,
                assessment_id,
                account_id,
                created_at,
                origin,
                cutoff.isoformat(),
                question,
                system_outcome,
                reviewer_outcome,
                reason_code,
                note,
                float(confidence),
                route,
            ),
        )
        return RegressionCase(
            regression_id=regression_id,
            case_id=case_id,
            assessment_id=assessment_id,
            account_id=account_id,
            created_at=created_at,
            origin=origin,
            cutoff=cutoff,
            question=question,
            system_outcome=system_outcome,
            reviewer_outcome=reviewer_outcome,
            reason_code=reason_code,
            note=note,
            confidence=float(confidence),
            route=route,
        )

    def regression_cases(self, origin: str | None = None) -> tuple[RegressionCase, ...]:
        """Return every regression record, newest first."""

        if not self.path.is_file():
            return ()
        query = "SELECT * FROM regression_cases"
        parameters: tuple[object, ...] = ()
        if origin is not None:
            query += " WHERE origin = ?"
            parameters = (origin,)
        query += " ORDER BY created_at DESC, regression_id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(
            RegressionCase(
                regression_id=str(row["regression_id"]),
                case_id=str(row["case_id"]) if row["case_id"] is not None else None,
                assessment_id=(
                    str(row["assessment_id"]) if row["assessment_id"] is not None else None
                ),
                account_id=str(row["account_id"]),
                created_at=str(row["created_at"]),
                origin=str(row["origin"]),
                cutoff=date.fromisoformat(str(row["cutoff"])),
                question=str(row["question"]),
                system_outcome=str(row["system_outcome"]),
                reviewer_outcome=(
                    str(row["reviewer_outcome"]) if row["reviewer_outcome"] is not None else None
                ),
                reason_code=str(row["reason_code"]),
                note=str(row["note"]),
                confidence=float(row["confidence"]),
                route=str(row["route"]),
            )
            for row in rows
        )

    def export_regression_cases(self, path: Path) -> int:
        """Write every regression record to a JSON Lines file and return the count.

        JSON Lines rather than JSON because this file grows: appending a run's
        worth of records to a list means rewriting and re-parsing the whole
        thing, and a truncated write would lose every earlier case with it.
        """

        cases = self.regression_cases()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(case.as_dict(), sort_keys=True) for case in reversed(cases)]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return len(cases)


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_QUEUE_LIMIT",
    "MAX_HISTORY_LIMIT",
    "MAX_QUEUE_LIMIT",
    "REGRESSION_ORIGINS",
    "STORE_FILENAME",
    "AssessmentRecord",
    "AssessmentStore",
    "AssessmentStoreError",
    "RegressionCase",
    "ReviewCase",
]
