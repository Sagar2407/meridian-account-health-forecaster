"""SQLite metadata and parent-document store (ADR 0003).

FAISS holds vectors and nothing else. Everything governance depends on --
account scope, document date, provenance, and the parent text returned as
context -- lives here, where it can be filtered before a vector is ever
consulted.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from meridian.retrieval.chunking import ChildChunk
from meridian.retrieval.documents import ParentDocument

STORE_FILENAME = "metadata.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS parents (
    doc_id      TEXT PRIMARY KEY,
    doc_type    TEXT NOT NULL,
    subtype     TEXT NOT NULL,
    account_id  TEXT,
    doc_date    TEXT,
    text        TEXT NOT NULL,
    metadata    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    child_id    TEXT PRIMARY KEY,
    parent_id   TEXT NOT NULL REFERENCES parents(doc_id),
    doc_type    TEXT NOT NULL,
    subtype     TEXT NOT NULL,
    account_id  TEXT,
    doc_date    TEXT,
    segment     TEXT,
    product     TEXT,
    source_severity TEXT,
    ordinal     INTEGER NOT NULL,
    row_index   INTEGER NOT NULL UNIQUE,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_account_date ON chunks(account_id, doc_date);
CREATE INDEX IF NOT EXISTS chunks_doc_type ON chunks(doc_type);
"""


@dataclass(frozen=True)
class ChunkRecord:
    """One indexed chunk as stored, including its FAISS row."""

    child_id: str
    parent_id: str
    doc_type: str
    subtype: str
    account_id: str | None
    doc_date: date | None
    segment: str | None
    product: str | None
    source_severity: str | None
    ordinal: int
    row_index: int
    text: str


def _as_date(value: str | None) -> date | None:
    """Return a date from an ISO string, or None."""

    return date.fromisoformat(value) if value else None


class MetadataStore:
    """Read and write the retrieval metadata database."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        """Return a connection with row access by name."""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialise(self) -> None:
        """Create the schema, replacing any previous contents."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            # Generated stores are rebuilt as a unit. Dropping the tables also
            # makes schema upgrades deterministic instead of leaving an older
            # CREATE IF NOT EXISTS layout in place.
            connection.executescript("DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS parents;")
            connection.executescript(_SCHEMA)
            connection.commit()

    def write(self, parents: Sequence[ParentDocument], chunks: Sequence[ChildChunk]) -> None:
        """Persist parents and chunks, assigning each chunk its FAISS row."""

        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO parents VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        parent.doc_id,
                        parent.doc_type,
                        parent.subtype,
                        parent.account_id,
                        parent.doc_date.isoformat() if parent.doc_date else None,
                        parent.text,
                        json.dumps(parent.metadata, sort_keys=True),
                    )
                    for parent in parents
                ],
            )
            connection.executemany(
                "INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        chunk.child_id,
                        chunk.parent_id,
                        chunk.doc_type,
                        chunk.subtype,
                        chunk.account_id,
                        chunk.doc_date.isoformat() if chunk.doc_date else None,
                        chunk.segment,
                        chunk.product,
                        chunk.source_severity,
                        chunk.ordinal,
                        row_index,
                        chunk.text,
                    )
                    for row_index, chunk in enumerate(chunks)
                ],
            )
            connection.commit()

    def candidate_rows(
        self,
        account_id: str | None,
        cutoff: date | None,
        knowledge_base_only: bool = False,
        allowed_doc_types: Sequence[str] | None = None,
    ) -> list[int]:
        """Return FAISS rows allowed by the hard metadata filters.

        Filtering happens before search rather than after, so an out-of-scope or
        post-cutoff chunk can never be a candidate in the first place.
        """

        clauses: list[str] = []
        parameters: list[object] = []
        if knowledge_base_only:
            clauses.append("account_id IS NULL")
        else:
            if account_id is None:
                return []
            clauses.append("account_id = ?")
            parameters.append(account_id)
            if cutoff is not None:
                clauses.append("(doc_date IS NULL OR doc_date <= ?)")
                parameters.append(cutoff.isoformat())
        if allowed_doc_types is not None:
            source_types = tuple(dict.fromkeys(allowed_doc_types))
            if not source_types:
                return []
            placeholders = ",".join("?" for _ in source_types)
            clauses.append(f"doc_type IN ({placeholders})")
            parameters.extend(source_types)
        query = f"SELECT row_index FROM chunks WHERE {' AND '.join(clauses)} ORDER BY row_index"
        with closing(self._connect()) as connection:
            return [int(row["row_index"]) for row in connection.execute(query, parameters)]

    def chunks_by_rows(self, rows: Iterable[int]) -> dict[int, ChunkRecord]:
        """Return chunk records keyed by FAISS row."""

        row_list = list(rows)
        if not row_list:
            return {}
        placeholders = ",".join("?" for _ in row_list)
        query = f"SELECT * FROM chunks WHERE row_index IN ({placeholders})"
        with closing(self._connect()) as connection:
            return {
                int(row["row_index"]): ChunkRecord(
                    child_id=row["child_id"],
                    parent_id=row["parent_id"],
                    doc_type=row["doc_type"],
                    subtype=row["subtype"],
                    account_id=row["account_id"],
                    doc_date=_as_date(row["doc_date"]),
                    segment=row["segment"],
                    product=row["product"],
                    source_severity=row["source_severity"],
                    ordinal=int(row["ordinal"]),
                    row_index=int(row["row_index"]),
                    text=row["text"],
                )
                for row in connection.execute(query, row_list)
            }

    def parent(self, doc_id: str) -> ParentDocument | None:
        """Return one parent document, or None when absent."""

        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM parents WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            return None
        return ParentDocument(
            doc_id=row["doc_id"],
            doc_type=row["doc_type"],
            subtype=row["subtype"],
            text=row["text"],
            account_id=row["account_id"],
            doc_date=_as_date(row["doc_date"]),
            metadata=json.loads(row["metadata"]),
        )

    def counts(self) -> dict[str, int]:
        """Return row counts for parents and chunks."""

        with closing(self._connect()) as connection:
            parents = connection.execute("SELECT COUNT(*) FROM parents").fetchone()[0]
            chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"parents": int(parents), "chunks": int(chunks)}
