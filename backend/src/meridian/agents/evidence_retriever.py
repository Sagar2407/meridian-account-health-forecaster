"""The Evidence Retriever (plan section 13.3).

One search per sub-goal, each with the source families that sub-goal is about,
each graded and retried at most once by the retrieval service itself. The
retriever's own contribution is the mapping from a typed sub-goal to a filtered
search, and an honest account of what came back.

Its failure behaviour matters as much as its success. Section 13.3 says that
after retry exhaustion it returns "the verified evidence that exists and a
precise gap report" -- not an empty result that a later node might read as "no
risks found". So an exhausted sub-goal is recorded with its reason, and
`RetrievalEvidence.exhausted` tells the coverage gate that the run has to
degrade rather than forecast on qualitative silence.
"""

from collections.abc import Sequence
from datetime import date

from meridian.agents.base import call_tool
from meridian.contracts import (
    Citation,
    RetrievalEvidence,
    RetrievalObservation,
    SubGoal,
    SubGoalKind,
)
from meridian.retrieval.contracts import AccountSourceFamily
from meridian.tools.contracts import (
    AccountEvidenceResponse,
    EvidenceCitation,
    KnowledgeResponse,
    RequesterRole,
)
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolUnavailableError

ROLE: RequesterRole = "evidence_retriever"

#: Which source families answer which sub-goal (plan section 13.1's vocabulary
#: against section 11.1's sources). Restricting the search is a safety control
#: as well as a relevance one: a support question that ranks a CSM note above a
#: ticket has quietly changed what the answer is about.
SUB_GOAL_SOURCES: dict[SubGoalKind, tuple[AccountSourceFamily, ...]] = {
    "adoption": ("csm_note", "support_ticket"),
    "support": ("support_ticket", "csm_note"),
    "relationship": ("csm_note",),
    "external_context": ("external_event", "csm_note"),
    "renewal_history": ("csm_note", "support_ticket"),
    "playbook_guidance": (),
}

#: The sub-goal answered from the knowledge base rather than from account
#: records. It carries no account scope, so it is never filtered by cutoff.
GUIDANCE_SUB_GOAL: SubGoalKind = "playbook_guidance"


def to_citation(
    citation: EvidenceCitation, account_id: str | None, sub_goal: SubGoalKind
) -> Citation:
    """Convert a transported tool citation into the graph's typed citation.

    `account_id` comes from the tool response envelope rather than the citation
    because the retrieval layer already proved ownership; carrying it on each
    citation makes a decision card self-describing.
    """

    return Citation(
        doc_id=citation.doc_id,
        parent_id=citation.doc_id,
        source_type=citation.source_type,
        subtype=citation.subtype,
        account_id=account_id,
        doc_date=citation.doc_date,
        excerpt=citation.excerpt,
        retrieval_score=citation.score,
        signal=citation.signal,
        sub_goal=sub_goal,
    )


class EvidenceRetriever:
    """Search, filter, and grade qualitative evidence for a plan's sub-goals."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def _account_search(
        self, account_id: str, sub_goal: SubGoal, as_of: date | None
    ) -> RetrievalObservation:
        """Run one account-scoped search and record what it produced."""

        arguments: dict[str, object] = {
            "account_id": account_id,
            "sub_goal": sub_goal.query,
            "source_families": SUB_GOAL_SOURCES[sub_goal.kind],
        }
        if as_of is not None:
            arguments["as_of"] = as_of
        response = call_tool(
            self._registry,
            ROLE,
            "retrieve_account_evidence",
            arguments,
            AccountEvidenceResponse,
        )
        return RetrievalObservation(
            sub_goal=sub_goal.kind,
            query=sub_goal.query,
            attempted_queries=response.attempted_queries,
            citations=tuple(
                to_citation(citation, account_id, sub_goal.kind) for citation in response.citations
            ),
            retry_count=max(len(response.attempted_queries) - 1, 0),
            source_coverage=dict(response.source_coverage),
            insufficient_evidence=response.insufficient_evidence,
            insufficiency_reason=response.insufficiency_reason,
        )

    def _guidance_search(self, sub_goal: SubGoal) -> tuple[Citation, ...]:
        """Return knowledge-base guidance for the playbook sub-goal."""

        response = call_tool(
            self._registry,
            ROLE,
            "retrieve_knowledge",
            {"sub_goal": sub_goal.query},
            KnowledgeResponse,
        )
        return tuple(
            to_citation(citation, None, GUIDANCE_SUB_GOAL) for citation in response.citations
        )

    def gather(
        self,
        account_id: str,
        cutoff: date,
        plan: Sequence[SubGoal],
        as_of: date | None = None,
        only: Sequence[SubGoalKind] | None = None,
    ) -> RetrievalEvidence:
        """Retrieve evidence for a plan, or for one targeted retry.

        Args:
            account_id: The account under assessment.
            cutoff: The effective cutoff, recorded on the result.
            plan: The Orchestrator's sub-goals.
            as_of: An optional earlier cutoff passed to the tool layer.
            only: When given, retrieve just these sub-goals. This is the
                targeted second evidence round of section 13.1, not a second
                full sweep: repeating the searches that already succeeded would
                spend the budget on evidence the run already has.

        Returns:
            Evidence with one observation per attempted sub-goal, or
            `available=False` when retrieval itself is not configured.
        """

        selected = [item for item in plan if only is None or item.kind in set(only)]
        observations: list[RetrievalObservation] = []
        guidance: tuple[Citation, ...] = ()

        try:
            for sub_goal in selected:
                if sub_goal.kind == GUIDANCE_SUB_GOAL:
                    guidance = self._guidance_search(sub_goal)
                    continue
                observations.append(self._account_search(account_id, sub_goal, as_of))
        except ToolUnavailableError as error:
            # Section 14.3: a permanent retrieval failure uses degraded mode.
            # Saying so precisely is the difference between "the index is not
            # built" and "this account has no evidence", which mean opposite
            # things for a forecast.
            return RetrievalEvidence(
                account_id=account_id,
                cutoff=cutoff,
                available=False,
                unavailable_reason=str(error),
            )

        return RetrievalEvidence(
            account_id=account_id,
            cutoff=cutoff,
            observations=tuple(observations),
            guidance=guidance,
            rejected=tuple(
                reason
                for observation in observations
                if observation.insufficiency_reason
                for reason in (f"{observation.sub_goal}: {observation.insufficiency_reason}",)
            ),
            available=True,
        )


def merge_evidence(previous: RetrievalEvidence, retry: RetrievalEvidence) -> RetrievalEvidence:
    """Return the first round's evidence updated by a targeted second round.

    A retried sub-goal replaces its earlier observation; a sub-goal that was not
    retried keeps the evidence it already had. Concatenating instead would leave
    two observations for one sub-goal and double-count its citations in coverage.
    """

    if not retry.available:
        return previous
    replaced = {observation.sub_goal: observation for observation in retry.observations}
    observations = tuple(
        replaced.pop(observation.sub_goal, observation) for observation in previous.observations
    )
    return RetrievalEvidence(
        account_id=previous.account_id,
        cutoff=previous.cutoff,
        observations=(*observations, *replaced.values()),
        guidance=retry.guidance or previous.guidance,
        rejected=(*previous.rejected, *retry.rejected),
        available=True,
    )


__all__ = [
    "GUIDANCE_SUB_GOAL",
    "SUB_GOAL_SOURCES",
    "EvidenceRetriever",
    "merge_evidence",
    "to_citation",
]
