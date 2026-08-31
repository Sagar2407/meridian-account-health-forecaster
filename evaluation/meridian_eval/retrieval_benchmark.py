"""Curated retrieval benchmark and metrics (plan section 11.6).

The benchmark is derived from the corpus rather than hand-written, so it stays
consistent when the archive is rebuilt. Three query families are covered:

1. One query per knowledge-base article, from its title.
2. Account-specific queries for the golden assessment accounts.
3. Conflicting-signal cases for accounts whose own record disagrees with
   itself, scored on whether both sides survive ranking.
4. Point-in-time cases, whose whole purpose is to confirm that evidence dated
   after an account's cutoff is never returned.

Account queries are graded against labels derived from structured metadata --
note type, ticket category, ticket priority, document family -- rather than
hand annotation, so the gold set is reproducible and moves with the archive.
The label is weak in one specific way worth stating: a document renders its own
type and category into its opening line, so a category-derived label rewards a
retriever that can connect a paraphrased question to that header as well as to
the body. Three probes (`risk`, `adoption`, `sponsor`) have no defensible
structural label and stay deliberately ungraded; they still contribute to the
safety and empty-result counts.

Reported metrics include the safety rates that matter more than ranking quality
here: wrong-account and post-cutoff citations must both be zero.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from meridian.data.loader import RawDataset, load_raw_dataset
from meridian.data.paths import raw_dataset_directory
from meridian.data.repository import RuntimeRepository
from meridian.retrieval.contracts import RetrievalResult
from meridian.retrieval.documents import (
    EVENT_TYPE,
    NOTE_TYPE,
    TICKET_TYPE,
    ParentDocument,
    build_parent_documents,
)
from meridian.retrieval.search import RetrievalService

KB_TITLE_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class BenchmarkQuery:
    """One benchmark query and the parent documents that should be found."""

    query_id: str
    query: str
    family: str
    account_id: str | None = None
    expected_parents: tuple[str, ...] = field(default_factory=tuple)
    expects_knowledge_base: bool = False
    forbidden_parents: tuple[str, ...] = field(default_factory=tuple)
    contrasting_parents: tuple[str, ...] = field(default_factory=tuple)


def _knowledge_base_queries(archive: Path | None = None) -> list[BenchmarkQuery]:
    """Return one query per knowledge-base article, taken from its title."""

    source = archive if archive is not None else raw_dataset_directory()
    path = source / "rag_corpus" / "knowledge_base.jsonl"
    queries: list[BenchmarkQuery] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        match = KB_TITLE_PATTERN.search(str(record["text"]))
        title = match.group(1).strip() if match else str(record["doc_id"])
        queries.append(
            BenchmarkQuery(
                query_id=f"kb_{record['doc_id']}",
                query=title,
                family="knowledge_base",
                expected_parents=(str(record["doc_id"]),),
                expects_knowledge_base=True,
            )
        )
    return queries


@dataclass(frozen=True)
class AccountProbe:
    """One account question and the structural rule that defines its gold set."""

    name: str
    question: str
    note_types: tuple[str, ...] = ()
    ticket_categories: tuple[str, ...] = ()
    ticket_priorities: tuple[str, ...] = ()
    include_events: bool = False

    @property
    def is_graded(self) -> bool:
        """Return whether this probe has a structural gold set at all."""

        return bool(
            self.note_types
            or self.ticket_categories
            or self.ticket_priorities
            or self.include_events
        )


ACCOUNT_PROBES: tuple[AccountProbe, ...] = (
    AccountProbe("risk", "Why is this account at risk of churning before renewal?"),
    AccountProbe("adoption", "How has product adoption and usage changed recently?"),
    AccountProbe("sponsor", "What happened with the executive sponsor or champion?"),
    AccountProbe(
        "renewal_prep",
        "What has the team recorded while preparing for renewal or running a save play?",
        note_types=("Renewal Prep", "Escalation / Save Play"),
    ),
    AccountProbe(
        "onboarding",
        "How did onboarding and enablement go for this account?",
        note_types=("Onboarding Kickoff",),
        ticket_categories=("Onboarding / Enablement",),
    ),
    AccountProbe(
        "escalation",
        "What support escalations or unresolved issues are outstanding?",
        ticket_categories=("Escalation",),
        ticket_priorities=("P1",),
    ),
    AccountProbe(
        "integration",
        "What integration or API problems has this account reported?",
        ticket_categories=("Integration / API",),
    ),
    AccountProbe(
        "outage",
        "Has this account reported outages or performance problems?",
        ticket_categories=("Performance / Outage",),
    ),
    AccountProbe(
        "billing",
        "Are there billing, licensing, or invoicing problems on this account?",
        ticket_categories=("Billing / Licensing",),
    ),
    AccountProbe(
        "external",
        "What external events affected this company recently?",
        include_events=True,
    ),
)


def _expected_parents(probe: AccountProbe, documents: list[ParentDocument]) -> tuple[str, ...]:
    """Return the parent ids a probe should surface, from structural metadata.

    `documents` comes from the cutoff-filtered runtime repository, so a gold
    parent is always something retrieval was allowed to see.
    """

    if not probe.is_graded:
        return ()
    expected: list[str] = []
    for document in documents:
        if (
            (document.doc_type == NOTE_TYPE and document.subtype in probe.note_types)
            or (
                document.doc_type == TICKET_TYPE
                and (
                    document.subtype in probe.ticket_categories
                    or document.metadata.get("source_severity") in probe.ticket_priorities
                )
            )
            or (document.doc_type == EVENT_TYPE and probe.include_events)
        ):
            expected.append(document.doc_id)
    return tuple(expected)


def _account_queries(
    account_ids: tuple[str, ...], documents: dict[str, list[ParentDocument]]
) -> list[BenchmarkQuery]:
    """Return the account-specific query set, graded where a gold set exists."""

    queries: list[BenchmarkQuery] = []
    for account_id in account_ids:
        for probe in ACCOUNT_PROBES:
            queries.append(
                BenchmarkQuery(
                    query_id=f"acc_{account_id}_{probe.name}",
                    query=probe.question,
                    family="account",
                    account_id=account_id,
                    expected_parents=_expected_parents(probe, documents[account_id]),
                )
            )
    return queries


CONFLICT_NOTES_PER_SIDE = 5
CONFLICT_QUERY = (
    "Summarise both the encouraging and the concerning signals on this account "
    "ahead of its renewal."
)


def _conflicting_signal_queries(
    account_ids: tuple[str, ...],
    repository: RuntimeRepository,
    documents: dict[str, list[ParentDocument]],
) -> list[BenchmarkQuery]:
    """Return queries for accounts whose evidence disagrees with itself.

    A similarity-ranked retriever can let one polarity crowd out the other,
    leaving whatever summarises the evidence with half the story. Each query
    here targets an account where the two sides genuinely exist, and is scored
    on whether the top five span both.

    The conflict is defined across sources rather than inside the notes.
    Splitting one account's notes by sentiment quantile does not work on this
    cohort: within-account sentiment is tightly clustered, with a median
    interquartile spread of 0.09, so a quantile split manufactures a contrast
    that is not there. What is real is the relationship record disagreeing with
    the outside world -- consistently warm notes beside adverse market news, or
    a favourable event beside a consistently poor quarter.
    """

    queries: list[BenchmarkQuery] = []
    for account_id in account_ids:
        favourable_events: list[str] = []
        adverse_events: list[str] = []
        for document in documents[account_id]:
            if document.doc_type != EVENT_TYPE:
                continue
            polarity = document.metadata.get("source_severity")
            if polarity == "favorable":
                favourable_events.append(document.doc_id)
            elif polarity == "adverse":
                adverse_events.append(document.doc_id)

        notes = repository.notes(account_id)
        sentiment = pd.to_numeric(notes["sentiment"], errors="coerce").dropna()
        if sentiment.empty:
            continue
        ranked = notes.loc[sentiment.sort_values(ascending=False).index, "note_id"]
        mean_sentiment = float(sentiment.mean())

        if mean_sentiment > 0 and adverse_events:
            supporting = tuple(str(value) for value in ranked.head(CONFLICT_NOTES_PER_SIDE))
            contrasting = tuple(adverse_events)
        elif mean_sentiment < 0 and favourable_events:
            supporting = tuple(favourable_events)
            contrasting = tuple(str(value) for value in ranked.tail(CONFLICT_NOTES_PER_SIDE))
        else:
            continue

        queries.append(
            BenchmarkQuery(
                query_id=f"conflict_{account_id}",
                query=CONFLICT_QUERY,
                family="conflicting_signal",
                account_id=account_id,
                expected_parents=supporting + contrasting,
                contrasting_parents=contrasting,
            )
        )
    return queries


POINT_IN_TIME_EXCERPT_CHARACTERS = 240


def _latest_after_cutoff(
    frame: pd.DataFrame, account_id: str, date_column: str, cutoff: date
) -> pd.Series | None:
    """Return the newest row for one account dated strictly after `cutoff`."""

    rows = frame.loc[frame["account_id"] == account_id].copy()
    rows["_ordering_date"] = pd.to_datetime(rows[date_column]).dt.date
    future = rows.loc[rows["_ordering_date"] > cutoff].sort_values("_ordering_date")
    if future.empty:
        return None
    return future.iloc[-1]


def _point_in_time_queries(
    account_ids: tuple[str, ...],
    repository: RuntimeRepository | None = None,
    dataset: RawDataset | None = None,
) -> list[BenchmarkQuery]:
    """Return queries written from evidence that postdates each account's cutoff.

    The other two families ask whether the right passage comes back. This one
    asks the opposite question. Each query is lifted verbatim from a document
    the system must never surface, which is the strongest possible probe: were
    that document reachable, a query equal to its own text would rank it first.
    A hit here is a point-in-time leak, not a ranking miss.
    """

    facts = dataset if dataset is not None else load_raw_dataset()
    store = repository if repository is not None else RuntimeRepository(facts)
    sources = (
        ("note", facts.csm_notes, "note_date", "note_id", "body"),
        ("ticket", facts.support_tickets, "created_date", "ticket_id", "body"),
    )
    queries: list[BenchmarkQuery] = []
    for account_id in account_ids:
        cutoff = store.cutoff_for(account_id)
        for name, frame, date_column, id_column, text_column in sources:
            row = _latest_after_cutoff(frame, account_id, date_column, cutoff)
            if row is None:
                continue
            excerpt = " ".join(str(row[text_column]).split())[:POINT_IN_TIME_EXCERPT_CHARACTERS]
            if not excerpt:
                continue
            queries.append(
                BenchmarkQuery(
                    query_id=f"pit_{account_id}_{name}",
                    query=excerpt,
                    family="point_in_time",
                    account_id=account_id,
                    forbidden_parents=(str(row[id_column]),),
                )
            )
    return queries


def golden_assessment_accounts(archive: Path | None = None) -> tuple[str, ...]:
    """Return account ids named by the packaged golden question set."""

    source = archive if archive is not None else raw_dataset_directory()
    path = source / "eval" / "golden_qa.jsonl"
    accounts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        match = re.search(r"(ACC-\d+)", str(record.get("id", "")))
        if match:
            accounts.append(match.group(1))
    return tuple(dict.fromkeys(accounts))


def build_benchmark(
    account_ids: tuple[str, ...] | None = None,
    archive: Path | None = None,
    repository: RuntimeRepository | None = None,
) -> list[BenchmarkQuery]:
    """Return the full curated benchmark."""

    accounts = account_ids if account_ids is not None else golden_assessment_accounts(archive)
    store = repository if repository is not None else RuntimeRepository()
    documents = {
        account_id: build_parent_documents(store, (account_id,), include_knowledge_base=False)
        for account_id in accounts
    }
    return (
        _knowledge_base_queries(archive)
        + _account_queries(accounts, documents)
        + _conflicting_signal_queries(accounts, store, documents)
        + _point_in_time_queries(accounts, store)
    )


def _reciprocal_rank(ranked: list[str], expected: set[str]) -> float:
    """Return the reciprocal rank of the first expected item."""

    for position, item in enumerate(ranked, start=1):
        if item in expected:
            return 1.0 / position
    return 0.0


def _ndcg(ranked: list[str], expected: set[str]) -> float:
    """Return normalised discounted cumulative gain with binary relevance."""

    if not expected:
        return float("nan")
    gains = [1.0 if item in expected else 0.0 for item in ranked]
    discounted = sum(gain / np.log2(position + 1) for position, gain in enumerate(gains, start=1))
    ideal_count = min(len(expected), len(ranked)) or 1
    ideal = sum(1.0 / np.log2(position + 1) for position in range(1, ideal_count + 1))
    return float(discounted / ideal) if ideal else float("nan")


@dataclass(frozen=True)
class QueryOutcome:
    """Per-query measurements, including safety violations."""

    query_id: str
    family: str
    returned: int
    recall_at_5: float
    precision_at_5: float
    reciprocal_rank: float
    ndcg: float
    wrong_account: int
    post_cutoff: int
    duplicate_parents: int
    forbidden_parents: int
    conflict_covered: float


def score_result(query: BenchmarkQuery, result: RetrievalResult) -> QueryOutcome:
    """Measure one retrieval result against its expectations."""

    citations = (
        list(result.knowledge_citations)
        if query.expects_knowledge_base
        else list(result.account_citations)
    )
    ranked_parents = [citation.parent_id for citation in citations]
    expected = set(query.expected_parents)

    wrong_account = sum(
        1 for citation in result.account_citations if citation.account_id != result.account_id
    )
    post_cutoff = sum(
        1
        for citation in result.account_citations
        if citation.doc_date is not None and citation.doc_date > result.cutoff
    )
    duplicates = len(ranked_parents) - len(set(ranked_parents))
    forbidden = sum(
        1
        for citation in (*result.account_citations, *result.knowledge_citations)
        if citation.parent_id in query.forbidden_parents
    )

    if query.contrasting_parents:
        top_parents = set(ranked_parents[:5])
        contrasting = set(query.contrasting_parents)
        conflict = float(
            bool(top_parents & (expected - contrasting)) and bool(top_parents & contrasting)
        )
    else:
        conflict = float("nan")

    if expected:
        top = ranked_parents[:5]
        recall = float(bool(expected & set(top)))
        # Several probes have large gold sets, so "did anything relevant come
        # back" is easy. Precision says how much of the returned evidence was
        # on topic, which is what separates the chunking arms.
        precision = (
            float(len([item for item in top if item in expected]) / len(top)) if top else 0.0
        )
        reciprocal = _reciprocal_rank(ranked_parents, expected)
        gain = _ndcg(ranked_parents, expected)
    else:
        recall = float("nan")
        precision = float("nan")
        reciprocal = float("nan")
        gain = float("nan")

    return QueryOutcome(
        query_id=query.query_id,
        family=query.family,
        returned=len(citations),
        recall_at_5=recall,
        precision_at_5=precision,
        reciprocal_rank=reciprocal,
        ndcg=gain,
        wrong_account=wrong_account,
        post_cutoff=post_cutoff,
        duplicate_parents=duplicates,
        forbidden_parents=forbidden,
        conflict_covered=conflict,
    )


def run_benchmark(service: RetrievalService, queries: list[BenchmarkQuery]) -> pd.DataFrame:
    """Execute every benchmark query and return per-query measurements."""

    outcomes: list[QueryOutcome] = []
    for query in queries:
        account_id = query.account_id or _any_account(service)
        result = service.search(account_id, query.query)
        outcomes.append(score_result(query, result))
    return pd.DataFrame([vars(outcome) for outcome in outcomes])


def _any_account(service: RetrievalService) -> str:
    """Return an arbitrary account for knowledge-base queries.

    KB retrieval is not account scoped, but the service still requires a valid
    account to resolve a cutoff for the account lane.
    """

    return service.repository.account_ids()[0]


def summarise(outcomes: pd.DataFrame) -> dict[str, float]:
    """Return headline benchmark metrics."""

    graded = outcomes.dropna(subset=["recall_at_5"])
    conflicts = outcomes.dropna(subset=["conflict_covered"])
    return {
        "queries": float(len(outcomes)),
        "graded_queries": float(len(graded)),
        "recall_at_5": float(graded["recall_at_5"].mean()) if len(graded) else float("nan"),
        "precision_at_5": float(graded["precision_at_5"].mean()) if len(graded) else float("nan"),
        "mrr": float(graded["reciprocal_rank"].mean()) if len(graded) else float("nan"),
        "ndcg": float(graded["ndcg"].mean()) if len(graded) else float("nan"),
        "mean_returned": float(outcomes["returned"].mean()),
        "empty_results": float((outcomes["returned"] == 0).sum()),
        "wrong_account_citations": float(outcomes["wrong_account"].sum()),
        "post_cutoff_citations": float(outcomes["post_cutoff"].sum()),
        "duplicate_parent_citations": float(outcomes["duplicate_parents"].sum()),
        "forbidden_parent_citations": float(outcomes["forbidden_parents"].sum()),
        "conflict_coverage": (
            float(conflicts["conflict_covered"].mean()) if len(conflicts) else float("nan")
        ),
    }
