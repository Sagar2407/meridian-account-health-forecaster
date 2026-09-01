"""The Orchestrator / Planner (plan section 13.1).

It decides which evidence the run needs and nothing else. Section 13.1's
prohibitions are the shape of this class: no outcome prediction, no arithmetic,
no direct retrieval, no unbounded planning. Its tool allowlist enforces the
first three -- it may read identity and its own history and nothing else -- and
the typed sub-goal vocabulary enforces the fourth.

A language model may suggest the sub-goals. It cannot invent one: `SubGoalKind`
is a closed vocabulary, so the worst a bad suggestion can do is pick a less
useful sub-goal from a list the system already supports. When no model is
configured, or when generation fails, a deterministic plan derived from the
profile takes over, because a planner that can fail closed is worth more than
one that stops the run.
"""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from meridian.agents.base import call_tool
from meridian.contracts import (
    MAX_SUB_GOALS,
    AssessmentRequest,
    SubGoal,
    SubGoalKind,
)
from meridian.data.repository import AccountProfile
from meridian.llm.base import (
    GenerationError,
    StructuredGenerator,
    Usage,
    generate_structured,
    spent_on_failure,
)
from meridian.tools.contracts import (
    AccountProfileResponse,
    PriorAssessment,
    PriorAssessmentsResponse,
    RequesterRole,
)
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolUnavailableError

ROLE: RequesterRole = "orchestrator"

#: The retrieval query used for each sub-goal when the planner does not supply
#: a usable one. They are written as evidence descriptions rather than as
#: questions because that is what the embedding index was built from.
DEFAULT_QUERIES: dict[SubGoalKind, str] = {
    "adoption": "product adoption trend, active usage, and engagement depth",
    "support": "support escalations, unresolved tickets, and customer satisfaction",
    "relationship": "executive sponsor change, champion risk, and onboarding status",
    "external_context": "external company events affecting this account",
    "renewal_history": "prior renewal discussions, contract history, and expansion talks",
    "playbook_guidance": "renewal risk playbook, save actions, and account health guidance",
}

MIN_USABLE_QUERY_CHARACTERS = 8

PLANNER_INSTRUCTIONS = (
    "You plan which evidence a read-only account-health assessment should gather. "
    "Choose one to three evidence sub-goals from the allowed list, in priority order, "
    "based on the account profile and the question. "
    "You must not predict an outcome, compute a number, estimate a probability, or "
    "state a conclusion: another component does that from verified data. "
    "For each sub-goal write a short search query describing the evidence to look for, "
    "in plain business language with no punctuation beyond commas."
)


class DraftSubGoal(BaseModel):
    """One sub-goal as suggested by a model, before validation."""

    model_config = ConfigDict(extra="forbid")

    kind: SubGoalKind
    query: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=400)


class SubGoalPlanDraft(BaseModel):
    """The planner's structured reply (plan section 13.1).

    Bounded at three because knowledge-base guidance is always retrieved as a
    fourth, and section 13.1 caps a plan at four sub-goals.
    """

    model_config = ConfigDict(extra="forbid")

    sub_goals: list[DraftSubGoal] = Field(min_length=1, max_length=MAX_SUB_GOALS - 1)
    focus: str = Field(default="", max_length=200)


@dataclass(frozen=True)
class PlanResult:
    """A plan plus an honest account of where it came from."""

    plan: tuple[SubGoal, ...]
    source: Literal["model", "deterministic"]
    usage: Usage = field(default_factory=Usage)
    attempts: int = 0
    model_name: str = ""
    fallback_reason: str | None = None


def _sub_goal(kind: SubGoalKind, query: str = "", rationale: str = "") -> SubGoal:
    """Return a validated sub-goal, replacing unusable model text with a default."""

    cleaned = " ".join(query.split())
    if len(cleaned) < MIN_USABLE_QUERY_CHARACTERS:
        cleaned = DEFAULT_QUERIES[kind]
    reason = " ".join(rationale.split()) or f"Standard {kind.replace('_', ' ')} evidence."
    try:
        return SubGoal(kind=kind, query=cleaned, rationale=reason)
    except ValueError:
        # A model-supplied query that fails the injection check is replaced, not
        # sanitised: the sub-goal still has to happen, and the default asks the
        # same question in language the tool layer accepts.
        return SubGoal(kind=kind, query=DEFAULT_QUERIES[kind], rationale=reason)


def deterministic_plan(profile: AccountProfile) -> tuple[SubGoal, ...]:
    """Return a plan derived from the profile alone.

    Adoption and support are always present: they are the two families the
    calibrated forecaster leans on hardest, so a decision card without evidence
    from either cannot explain itself. The third slot goes to whichever of
    relationship or external context the profile suggests is live.
    """

    kinds: list[SubGoalKind] = ["adoption", "support"]
    if profile.sponsor_status in ("new", "lost") or not profile.onboarding_completed:
        kinds.append("relationship")
    else:
        kinds.append("external_context")
    kinds.append("playbook_guidance")
    return tuple(_sub_goal(kind) for kind in kinds)


def _profile_summary(profile: AccountProfile, priors: tuple[PriorAssessment, ...]) -> str:
    """Return the sanitized context a planner is allowed to see.

    Prior assessments are context, not truth (section 17.2). They are shown so
    the planner can notice what was already examined, and are labelled so it
    cannot mistake an earlier call for a fact about the account.
    """

    lines = [
        f"Account: {profile.account_name} ({profile.account_id})",
        f"Segment: {profile.segment}; industry: {profile.industry}; region: {profile.region}",
        f"Seats: {profile.licensed_seats}; products: {profile.num_products}; "
        f"ACV: {profile.acv_usd:,.0f}",
        f"Renewal date: {profile.renewal_date.isoformat()}; "
        f"sponsor status: {profile.sponsor_status}; "
        f"onboarding complete: {profile.onboarding_completed}",
    ]
    if priors:
        lines.append("Earlier advisory assessments by this system (context, not truth):")
        lines.extend(
            f"- {item.created_at} at cutoff {item.cutoff.isoformat()}: "
            f"{item.predicted_outcome} ({item.decision})"
            for item in priors
        )
    return "\n".join(lines)


class Orchestrator:
    """Load context and decide which evidence the run needs."""

    def __init__(
        self, registry: ToolRegistry, generator: StructuredGenerator | None = None
    ) -> None:
        self._registry = registry
        self._generator = generator

    def load_context(self, account_id: str) -> tuple[AccountProfile, tuple[PriorAssessment, ...]]:
        """Return the sanitized profile and this system's own prior decisions.

        Application memory is optional: a deployment without it still assesses
        accounts, it just has no history to consider, so an unavailable store is
        an empty history rather than a failed run.
        """

        response = call_tool(
            self._registry,
            ROLE,
            "get_account_profile",
            {"account_id": account_id},
            AccountProfileResponse,
        )
        profile = AccountProfile.model_validate(response.profile)
        try:
            priors = call_tool(
                self._registry,
                ROLE,
                "get_prior_assessments",
                {"account_id": account_id},
                PriorAssessmentsResponse,
            ).assessments
        except ToolUnavailableError:
            priors = ()
        return profile, priors

    def plan(
        self,
        request: AssessmentRequest,
        profile: AccountProfile,
        priors: tuple[PriorAssessment, ...] = (),
        use_model: bool = True,
    ) -> PlanResult:
        """Return the sub-goals this assessment should gather evidence for.

        ``use_model`` is false after the run reaches a Phase 7 runtime budget.
        The deterministic plan is the normal no-provider path, so declining a
        further model call does not prevent the assessment from completing.
        """

        fallback = deterministic_plan(profile)
        if self._generator is None or not use_model:
            return PlanResult(
                plan=fallback,
                source="deterministic",
                fallback_reason=(
                    "no language-model provider is configured"
                    if self._generator is None
                    else "the run's model-call budget is spent"
                ),
            )

        try:
            result = generate_structured(
                self._generator,
                SubGoalPlanDraft,
                instructions=PLANNER_INSTRUCTIONS,
                input_text=(
                    f"{_profile_summary(profile, priors)}\n\n"
                    f"Question from a {request.requester_role}: {request.question}"
                ),
            )
        except GenerationError as error:
            spent, attempts = spent_on_failure(error)
            return PlanResult(
                plan=fallback,
                source="deterministic",
                usage=spent,
                attempts=attempts,
                fallback_reason=f"planner generation failed: {type(error).__name__}",
            )

        chosen: list[SubGoal] = []
        seen: set[SubGoalKind] = set()
        for draft in result.value.sub_goals:
            if draft.kind in seen or draft.kind == "playbook_guidance":
                continue
            seen.add(draft.kind)
            chosen.append(_sub_goal(draft.kind, draft.query, draft.rationale))

        if not chosen:
            return PlanResult(
                plan=fallback,
                source="deterministic",
                usage=result.usage,
                attempts=result.attempts,
                model_name=result.model,
                fallback_reason="the planner selected no usable sub-goal",
            )

        # Guidance is not optional and is therefore not the planner's to drop:
        # section 13.4 requires the fast path to recommend a knowledge-grounded
        # action, and it cannot ground one in an article nobody retrieved.
        guidance = _sub_goal("playbook_guidance", result.value.focus)
        return PlanResult(
            plan=(*chosen[: MAX_SUB_GOALS - 1], guidance),
            source="model",
            usage=result.usage,
            attempts=result.attempts,
            model_name=result.model,
        )


__all__ = [
    "DEFAULT_QUERIES",
    "PLANNER_INSTRUCTIONS",
    "DraftSubGoal",
    "Orchestrator",
    "PlanResult",
    "SubGoalPlanDraft",
    "deterministic_plan",
]
