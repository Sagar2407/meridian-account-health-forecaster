"""Parent-child chunking (plan section 11.2).

Children are embedded for precision; the parent is returned for usable context.
Notes and knowledge-base articles split on headings and blank-line sections;
tickets and events stay whole because they are already short.

Child identifiers are derived deterministically from the parent id and ordinal,
so rebuilding the index produces identical ids and citations stay stable.
"""

import re
from dataclasses import dataclass
from datetime import date

from meridian.retrieval.documents import (
    EVENT_TYPE,
    KNOWLEDGE_TYPE,
    NOTE_TYPE,
    ParentDocument,
)

MIN_CHUNK_CHARACTERS = 80
MAX_CHUNK_CHARACTERS = 1200
DEFAULT_FIXED_SIZE = 600
DEFAULT_FIXED_OVERLAP = 120

_SPLITTABLE_TYPES = (NOTE_TYPE, KNOWLEDGE_TYPE)
_SECTION_PATTERN = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class ChildChunk:
    """An embedded fragment that points back at its parent document."""

    child_id: str
    parent_id: str
    doc_type: str
    subtype: str
    text: str
    ordinal: int
    account_id: str | None = None
    doc_date: date | None = None
    segment: str | None = None
    product: str | None = None
    source_severity: str | None = None

    @property
    def is_account_scoped(self) -> bool:
        """Return whether this chunk belongs to a single account."""

        return self.account_id is not None


def _merge_short_sections(sections: list[str]) -> list[str]:
    """Merge fragments below the minimum length into their neighbour.

    A one-line heading or a short action item is not independently retrievable,
    so it is attached to the following section rather than embedded alone.
    """

    merged: list[str] = []
    pending = ""
    for section in sections:
        candidate = f"{pending}\n\n{section}".strip() if pending else section.strip()
        if len(candidate) < MIN_CHUNK_CHARACTERS:
            pending = candidate
            continue
        merged.append(candidate)
        pending = ""
    if pending:
        if merged:
            merged[-1] = f"{merged[-1]}\n\n{pending}".strip()
        else:
            merged.append(pending)
    return merged


def _split_long_section(section: str) -> list[str]:
    """Split an oversized section on sentence boundaries."""

    if len(section) <= MAX_CHUNK_CHARACTERS:
        return [section]
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", section):
        # A source can contain a long URL, table row, or malformed paragraph
        # with no sentence boundary. Split that deterministically as a final
        # guard so the advertised maximum is real rather than aspirational.
        sentence_parts = [
            sentence[start : start + MAX_CHUNK_CHARACTERS]
            for start in range(0, len(sentence), MAX_CHUNK_CHARACTERS)
        ]
        for sentence_part in sentence_parts:
            if len(current) + len(sentence_part) + 1 > MAX_CHUNK_CHARACTERS and current:
                pieces.append(current.strip())
                current = sentence_part
            else:
                current = f"{current} {sentence_part}".strip()
    if current:
        pieces.append(current.strip())
    return pieces


def chunk_parent(parent: ParentDocument) -> list[ChildChunk]:
    """Return the child chunks for one parent document."""

    if parent.doc_type not in _SPLITTABLE_TYPES or parent.doc_type == EVENT_TYPE:
        sections = [parent.text.strip()]
    else:
        raw = [piece for piece in _SECTION_PATTERN.split(parent.text) if piece.strip()]
        sections = _merge_short_sections(raw) or [parent.text.strip()]

    expanded: list[str] = []
    for section in sections:
        expanded.extend(_split_long_section(section))

    return [
        ChildChunk(
            child_id=f"{parent.doc_id}#c{ordinal:03d}",
            parent_id=parent.doc_id,
            doc_type=parent.doc_type,
            subtype=parent.subtype,
            text=text,
            ordinal=ordinal,
            account_id=parent.account_id,
            doc_date=parent.doc_date,
            segment=parent.metadata.get("segment") or None,
            product=(
                parent.metadata.get("product") or parent.metadata.get("primary_product") or None
            ),
            source_severity=parent.metadata.get("source_severity") or None,
        )
        for ordinal, text in enumerate(expanded)
        if text.strip()
    ]


def chunk_documents(documents: list[ParentDocument]) -> list[ChildChunk]:
    """Return every child chunk across `documents`, in deterministic order."""

    chunks: list[ChildChunk] = []
    for parent in documents:
        chunks.extend(chunk_parent(parent))
    return chunks


def fixed_length_chunks(
    documents: list[ParentDocument],
    size: int = DEFAULT_FIXED_SIZE,
    overlap: int = DEFAULT_FIXED_OVERLAP,
) -> list[ChildChunk]:
    """Return fixed-length overlapping chunks, for the section 11.6 ablation.

    This is the comparison arm only. It deliberately ignores document structure
    so the ablation isolates the effect of structural chunking while corpus,
    encoder, filters, top-k, and queries stay constant.
    """

    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be non-negative and smaller than size")
    chunks: list[ChildChunk] = []
    for parent in documents:
        text = parent.text.strip()
        start = 0
        ordinal = 0
        while start < len(text):
            piece = text[start : start + size].strip()
            if piece:
                chunks.append(
                    ChildChunk(
                        child_id=f"{parent.doc_id}#f{ordinal:03d}",
                        parent_id=parent.doc_id,
                        doc_type=parent.doc_type,
                        subtype=parent.subtype,
                        text=piece,
                        ordinal=ordinal,
                        account_id=parent.account_id,
                        doc_date=parent.doc_date,
                        segment=parent.metadata.get("segment") or None,
                        product=(
                            parent.metadata.get("product")
                            or parent.metadata.get("primary_product")
                            or None
                        ),
                        source_severity=parent.metadata.get("source_severity") or None,
                    )
                )
                ordinal += 1
            if start + size >= len(text):
                break
            start += size - overlap
    return chunks
