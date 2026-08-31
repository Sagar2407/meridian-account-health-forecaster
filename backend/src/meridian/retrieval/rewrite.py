"""Bounded, filter-preserving query rewrite for the one retrieval retry."""

import re
from typing import Protocol

from meridian.retrieval.contracts import RetrievalGrade

MAX_REWRITTEN_QUERY_CHARACTERS = 800

_SOURCE_EXPANSIONS = {
    "csm_note": "QBR CSM note renewal outlook adoption sponsor champion action items",
    "support_ticket": "support ticket escalation unresolved issue incident defect outage priority",
    "external_event": (
        "external event company news market leadership layoffs funding acquisition earnings "
        "headwind tailwind"
    ),
}


class QueryRewriter(Protocol):
    """Provider-neutral rewrite interface used by the bounded retriever."""

    def rewrite(self, query: str, grade: RetrievalGrade) -> str:
        """Return one bounded query that does not alter hard metadata filters."""


class DeterministicQueryRewriter:
    """Expand a thin query with standard Meridian evidence vocabulary."""

    def rewrite(self, query: str, grade: RetrievalGrade) -> str:
        """Return the original intent plus terms targeted at the diagnosed gap."""

        additions: list[str] = []
        for family in grade.missing_required_sources:
            additions.append(_SOURCE_EXPANSIONS[family])

        joined_reasons = " ".join(grade.reasons)
        if "two independent" in joined_reasons or "duplicate-heavy" in joined_reasons:
            additions.append("independent corroborating qualitative evidence from separate records")
        if "older than" in joined_reasons:
            additions.append("most recent dated evidence available before the forecast cutoff")
        if "no account passage" in joined_reasons:
            additions.append(
                "account renewal evidence adoption relationship support external signals"
            )

        if not additions:
            additions.append("specific account evidence and supporting domain guidance")

        rewritten = re.sub(r"\s+", " ", f"{query.strip()} {' '.join(additions)}").strip()
        return rewritten[:MAX_REWRITTEN_QUERY_CHARACTERS].rstrip()
