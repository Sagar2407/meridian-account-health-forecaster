"""Build indexable parent documents from sanitized sources (plan section 11.1).

Four source families are indexed: CSM notes, support tickets, external events
rendered as short evidence documents, and the knowledge base. Telemetry is never
indexed, and every document is drawn from the runtime repository, so it is
already filtered to its account's effective cutoff.
"""

import hashlib
import json
import re
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from meridian.data.constants import FORBIDDEN_RUNTIME_FIELDS
from meridian.data.paths import raw_dataset_directory
from meridian.data.repository import RuntimeRepository

NOTE_TYPE = "csm_note"
TICKET_TYPE = "support_ticket"
EVENT_TYPE = "external_event"
KNOWLEDGE_TYPE = "knowledge_base"

POLARITY_WORDS = {1: "favorable", 0: "neutral", -1: "adverse"}

# The supplied KB is useful, but four articles name evaluation-only schema
# fields while explaining why they must not be used.  Putting those literal
# names in the vector store still makes them retrievable, which violates the
# runtime boundary.  Keep the guidance while replacing the schema vocabulary
# before it reaches a parent document, child chunk, embedding, or SQLite row.
_KNOWLEDGE_REPLACEMENTS = {
    "health_index_noised": "restricted evaluation score",
    "advanced_adoption_target": "restricted generative adoption parameter",
    "top_negative_drivers": "evaluation-only negative-driver list",
    "top_positive_drivers": "evaluation-only positive-driver list",
    "churn_probability": "calibrated renewal-risk estimate",
    "health_archetype": "restricted latent category",
    "usage_cliff_date": "computed usage-change date",
    "outcome_reason": "renewal-result rationale",
    "outcome_date": "renewal-result date",
    "health_index": "restricted evaluation score",
    "health_band": "restricted latent category",
    "outcome": "renewal result",
}
_KNOWLEDGE_PHRASE_REPLACEMENTS = {
    "renewal_outcomes": "evaluation-only renewal results",
    "health index": "observable health assessment",
    "churn probability": "calibrated renewal-risk estimate",
}


@dataclass(frozen=True)
class ParentDocument:
    """One retrievable source document, returned whole as context."""

    doc_id: str
    doc_type: str
    subtype: str
    text: str
    account_id: str | None = None
    doc_date: date | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_account_scoped(self) -> bool:
        """Return whether this document belongs to a single account."""

        return self.account_id is not None


def _account_metadata(repository: RuntimeRepository, account_id: str) -> dict[str, str]:
    """Return filterable, non-latent account metadata for a document."""

    profile = repository.profile(account_id)
    return {
        "account_name": profile.account_name,
        "segment": profile.segment,
        "industry": profile.industry,
        "primary_product": profile.primary_product,
    }


def _replace_case_insensitive(text: str, needle: str, replacement: str) -> str:
    """Replace one whole schema token without depending on source casing."""

    pattern = rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])"
    return re.sub(pattern, replacement, text, flags=re.IGNORECASE)


def sanitize_knowledge_text(text: str) -> str:
    """Return KB text with evaluation-only field vocabulary removed.

    This changes only the generated runtime representation.  The source JSONL
    and Markdown articles remain immutable under ``data/raw``.
    """

    sanitized = text
    for phrase, replacement in _KNOWLEDGE_PHRASE_REPLACEMENTS.items():
        sanitized = _replace_case_insensitive(sanitized, phrase, replacement)
    # Longest first prevents a shorter token (for example ``outcome``) from
    # partially consuming a compound field name.
    for field_name in sorted(_KNOWLEDGE_REPLACEMENTS, key=len, reverse=True):
        sanitized = _replace_case_insensitive(
            sanitized, field_name, _KNOWLEDGE_REPLACEMENTS[field_name]
        )
    return sanitized


def forbidden_field_mentions(text: str) -> tuple[str, ...]:
    """Return exact evaluation-only schema tokens found in arbitrary text."""

    lowered = text.lower()
    return tuple(
        sorted(
            field
            for field in FORBIDDEN_RUNTIME_FIELDS
            if re.search(
                rf"(?<![a-z0-9_]){re.escape(field)}(?![a-z0-9_])",
                lowered,
            )
        )
    )


def _render_event(row: dict[Hashable, object], event_date: date) -> str:
    """Render one external event as a short evidence document.

    Plan section 8.3 notes the packaged corpus contains no event documents, so
    they are synthesised here rather than left unavailable to retrieval.
    """

    polarity = POLARITY_WORDS.get(int(str(row["polarity"])), "neutral")
    return (
        f"[External event] {row['headline']}\n"
        f"Type: {row['event_type']}. Signal: {polarity}. Source: {row['source']}. "
        f"Date: {event_date.isoformat()}."
    )


def _account_documents(repository: RuntimeRepository, account_id: str) -> list[ParentDocument]:
    """Return every indexable document for one account, already cutoff-filtered."""

    metadata = _account_metadata(repository, account_id)
    documents: list[ParentDocument] = []

    for note in repository.notes(account_id).to_dict("records"):
        documents.append(
            ParentDocument(
                doc_id=str(note["note_id"]),
                doc_type=NOTE_TYPE,
                subtype=str(note["note_type"]),
                text=f"[{note['note_type']}] {metadata['account_name']}\n\n{note['body']}",
                account_id=account_id,
                doc_date=pd.Timestamp(note["note_date"]).date(),
                metadata={
                    **metadata,
                    "product": metadata["primary_product"],
                    "source_severity": "",
                },
            )
        )

    for ticket in repository.tickets(account_id).to_dict("records"):
        documents.append(
            ParentDocument(
                doc_id=str(ticket["ticket_id"]),
                doc_type=TICKET_TYPE,
                subtype=str(ticket["category"]),
                text=(
                    f"[{ticket['category']} / {ticket['priority']}] {ticket['subject']}\n\n"
                    f"{ticket['body']}"
                ),
                account_id=account_id,
                doc_date=pd.Timestamp(ticket["created_date"]).date(),
                metadata={
                    **metadata,
                    "product": str(ticket["product"]),
                    "source_severity": str(ticket["priority"]),
                },
            )
        )

    events = repository.events(account_id).reset_index(drop=True)
    for ordinal, event in enumerate(events.to_dict("records")):
        event_date = pd.Timestamp(event["event_date"]).date()
        identity = "\x1f".join(
            (
                account_id,
                event_date.isoformat(),
                str(event["event_type"]),
                str(event["source"]),
                str(event["headline"]),
            )
        )
        event_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
        documents.append(
            ParentDocument(
                doc_id=f"EVT-{account_id}-{event_date.isoformat()}-{event_digest}",
                doc_type=EVENT_TYPE,
                subtype=str(event["event_type"]),
                text=_render_event(event, event_date),
                account_id=account_id,
                doc_date=event_date,
                metadata={
                    **metadata,
                    "product": metadata["primary_product"],
                    "source_severity": POLARITY_WORDS.get(int(str(event["polarity"])), "neutral"),
                    "source_ordinal": str(ordinal),
                },
            )
        )

    return documents


def load_knowledge_base(archive: Path | None = None) -> list[ParentDocument]:
    """Return the knowledge-base articles, which are not account scoped."""

    source = archive if archive is not None else raw_dataset_directory()
    path = source / "rag_corpus" / "knowledge_base.jsonl"
    documents: list[ParentDocument] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("account_id") is not None:
            raise ValueError(f"knowledge document {record.get('doc_id')} is account scoped")
        if record.get("doc_type") not in (None, KNOWLEDGE_TYPE):
            raise ValueError(f"knowledge document {record.get('doc_id')} has an invalid type")
        tags = [sanitize_knowledge_text(str(tag)) for tag in (record.get("tags") or [])]
        documents.append(
            ParentDocument(
                doc_id=str(record["doc_id"]),
                doc_type=KNOWLEDGE_TYPE,
                subtype=str(record.get("subtype") or "reference"),
                text=sanitize_knowledge_text(str(record["text"])),
                account_id=None,
                doc_date=None,
                metadata={
                    "tags": ", ".join(tags),
                    "product": "",
                    "source_severity": "",
                },
            )
        )
    return documents


def assert_no_latent_text(documents: list[ParentDocument]) -> None:
    """Raise if a document leaks a latent or outcome field name.

    Plan section 11.3 step 3 requires asserting forbidden-field absence before
    indexing. This applies to the knowledge base too: policy guidance is kept,
    but :func:`load_knowledge_base` removes the forbidden schema vocabulary.

    Raises:
        ValueError: If an account-scoped document mentions a forbidden field.
    """

    offenders: list[str] = []
    for document in documents:
        searchable = "\n".join(
            (document.text, json.dumps(document.metadata, sort_keys=True))
        ).lower()
        leaked = forbidden_field_mentions(searchable)
        if leaked:
            offenders.append(f"{document.doc_id}: {leaked}")
    if offenders:
        raise ValueError(f"documents leak forbidden fields: {offenders[:5]}")


def build_parent_documents(
    repository: RuntimeRepository,
    account_ids: tuple[str, ...] | None = None,
    include_knowledge_base: bool = True,
    archive: Path | None = None,
) -> list[ParentDocument]:
    """Return every parent document to be indexed, in deterministic order."""

    ids = account_ids if account_ids is not None else repository.account_ids()
    documents: list[ParentDocument] = []
    for account_id in ids:
        documents.extend(_account_documents(repository, account_id))
    if include_knowledge_base:
        documents.extend(load_knowledge_base(archive))
    assert_no_latent_text(documents)
    return documents
