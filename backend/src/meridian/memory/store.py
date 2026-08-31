"""Application memory: prior assessments and human-review cases (plan section 12.2).

These are the system's own records of what it decided, not writes to Meridian
source data. That distinction is the whole point of the module, so it is
enforced rather than documented: the store refuses to open a database anywhere
under the raw archive.

SQLite behind a typed interface, per ADR 0006. Callers get dataclasses; no SQL
text and no connection object escapes this module.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from meridian.data.paths import application_directory, raw_dataset_directory

STORE_FILENAME = "assessments.sqlite"
DEFAULT_HISTORY_LIMIT = 5
MAX_HISTORY_LIMIT = 50

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
"""


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


@dataclass(frozen=True)
class ReviewCase:
    """One case routed to a human reviewer."""

    case_id: str
    assessment_id: str
    account_id: str
    created_at: str
    reason: str
    status: str


def _now() -> str:
    """Return the current UTC timestamp in ISO form."""

    return datetime.now(UTC).isoformat(timespec="seconds")


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
        """Create the schema if it does not already exist."""

        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.commit()

    def record_assessment(
        self,
        account_id: str,
        cutoff: date,
        predicted_outcome: str,
        confidence: float,
        decision: str,
        summary: str,
        created_at: str | None = None,
    ) -> AssessmentRecord:
        """Append one assessment and return it.

        The identifier is derived from the account and a per-account sequence
        rather than a random value, so a test can assert on it and a reviewer
        can see the order at a glance.

        Raises:
            AssessmentStoreError: If `confidence` is outside [0, 1].
        """

        if not 0.0 <= confidence <= 1.0:
            raise AssessmentStoreError("confidence must be between 0 and 1")
        self.initialise()
        stamp = created_at if created_at is not None else _now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM assessments "
                "WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            sequence = int(row["next"])
            assessment_id = f"ASMT-{account_id}-{sequence:04d}"
            connection.execute(
                "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        return tuple(
            AssessmentRecord(
                assessment_id=row["assessment_id"],
                account_id=row["account_id"],
                created_at=row["created_at"],
                cutoff=date.fromisoformat(row["cutoff"]),
                predicted_outcome=row["predicted_outcome"],
                confidence=float(row["confidence"]),
                decision=row["decision"],
                summary=row["summary"],
            )
            for row in rows
        )

    def open_review_case(
        self, assessment_id: str, reason: str, created_at: str | None = None
    ) -> ReviewCase:
        """Route one recorded assessment to human review.

        Raises:
            AssessmentStoreError: If `assessment_id` was never recorded.
        """

        self.initialise()
        stamp = created_at if created_at is not None else _now()
        with self._connect() as connection:
            owner = connection.execute(
                "SELECT account_id FROM assessments WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
            if owner is None:
                raise AssessmentStoreError(f"unknown assessment {assessment_id}")
            account_id = str(owner["account_id"])
            existing = connection.execute(
                "SELECT COUNT(*) AS total FROM review_cases WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
            case_id = f"CASE-{assessment_id.removeprefix('ASMT-')}-{int(existing['total']) + 1:02d}"
            connection.execute(
                "INSERT INTO review_cases VALUES (?, ?, ?, ?, ?, ?)",
                (case_id, assessment_id, account_id, stamp, reason, "open"),
            )
            connection.commit()
        return ReviewCase(
            case_id=case_id,
            assessment_id=assessment_id,
            account_id=account_id,
            created_at=stamp,
            reason=reason,
            status="open",
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
        return tuple(
            ReviewCase(
                case_id=row["case_id"],
                assessment_id=row["assessment_id"],
                account_id=row["account_id"],
                created_at=row["created_at"],
                reason=row["reason"],
                status=row["status"],
            )
            for row in rows
        )
