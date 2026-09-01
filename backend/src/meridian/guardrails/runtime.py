"""Runtime guardrails: what one run may spend, and what a model may reach.

Section 16.3's last two bullets are the ones an offline test suite is least
likely to notice going wrong: "retry budgets and timeouts", and "no arbitrary
web, shell, SQL, filesystem, or code-execution tool exposed to the LLM".

The retry budgets in `meridian.graph.state` bound the *shape* of a run -- how
many evidence rounds, how many regenerations. They do not bound its *cost*: a
provider that returns slowly, or a prompt that grows, can spend far more than
expected inside a perfectly legal path. So this module adds the three bounds a
bill is actually measured in -- model calls, tokens, and wall-clock -- and the
graph consults them before every discretionary model call.

Exhausting a budget is not an error. The run continues with the deterministic
narrative it would have used had no provider been configured at all, which is a
path Phases 4 through 6 already exercise on every offline test.
"""

import re
from dataclasses import dataclass

from meridian.contracts import GuardrailDecision
from meridian.tools.registry import TOOLS, ToolRegistry

#: Provider attempts one assessment may make. The four logical generations on
#: the largest path -- plan, candidates, narrative, one regeneration -- may
#: each consume the single allowed schema-repair attempt, so eight is the hard
#: ceiling a correct run stays under rather than a limit it negotiates with.
MAX_MODEL_CALLS = 8

#: Tokens one assessment may bill. Sized from the observed cost of a
#: conflict-gated run with four candidates, roughly doubled.
MAX_RUN_TOKENS = 60_000

#: Wall-clock seconds one assessment may take before it stops spending. It does
#: not cancel work in flight -- Python cannot safely kill a running thread --
#: it stops the run from *starting* anything else, which is the failure a
#: request timeout actually needs bounded.
MAX_RUN_SECONDS = 180.0

#: Tool-name shapes that would give a model a general-purpose capability. This
#: is a shape check, not a list of known-bad names: a tool called
#: `run_sql_query` is refused because of what it is, not because someone
#: remembered to add it. Names are split on underscores first, because `_` is a
#: word character to a regular expression and `\bsql\b` would otherwise never
#: fire on `run_sql_query` -- the one name the rule most obviously exists for.
DANGEROUS_TOOL_PATTERNS: tuple[str, ...] = (
    r"\b(?:shell|bash|sh|zsh|exec|execute|eval|subprocess|command|spawn)\b",
    r"\b(?:sql|query|database|db|cursor|table)\b",
    r"\b(?:http|https|web|browse|browser|fetch|curl|url|request|api)\b",
    r"\b(?:file|files|filesystem|fs|path|dir|directory|glob|read|write|open)\b",
    r"\b(?:python|code|script|interpreter|notebook|repl)\b",
    r"\b(?:delete|drop|update|insert|patch|upload|send|email)\b",
)


def _separated(name: str) -> str:
    """Return a tool name with its separators turned into spaces."""

    return re.sub(r"[^a-z0-9]+", " ", name.lower())


#: The eight read-only tools of section 12.1. Frozen here as well as in the
#: registry so that adding a ninth is a deliberate, visible change to a safety
#: control rather than a side effect of adding a tool.
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_account_profile",
        "get_prior_assessments",
        "compute_account_metrics",
        "get_usage_series",
        "get_support_summary",
        "get_external_events",
        "retrieve_account_evidence",
        "retrieve_knowledge",
    }
)


class DangerousToolError(RuntimeError):
    """Raised when the tool surface would give a model a general capability."""


@dataclass(frozen=True)
class RunBudget:
    """What one run has spent so far, against what it is allowed."""

    model_calls: int = 0
    tokens: int = 0
    elapsed_seconds: float = 0.0
    max_model_calls: int = MAX_MODEL_CALLS
    max_tokens: int = MAX_RUN_TOKENS
    max_seconds: float = MAX_RUN_SECONDS

    @property
    def exceeded(self) -> tuple[str, ...]:
        """Return the names of every budget this run has spent."""

        spent: list[str] = []
        if self.model_calls >= self.max_model_calls:
            spent.append("model_calls")
        if self.tokens >= self.max_tokens:
            spent.append("tokens")
        if self.elapsed_seconds >= self.max_seconds:
            spent.append("wall_clock")
        return tuple(spent)

    @property
    def may_spend(self) -> bool:
        """Return whether this run may make another model call."""

        return not self.exceeded

    def verdict(self) -> GuardrailDecision:
        """Return the runtime-stage guardrail decision for this budget."""

        spent = self.exceeded
        if not spent:
            return GuardrailDecision(
                stage="execution",
                outcome="pass",
                message=(
                    f"{self.model_calls}/{self.max_model_calls} model calls and "
                    f"{self.tokens}/{self.max_tokens} tokens spent."
                ),
            )
        return GuardrailDecision(
            stage="execution",
            outcome="review",
            rule_ids=tuple(f"RUNTIME-{name.upper()}" for name in spent),
            reason_codes=("budget_exhausted",),
            message=(
                f"The run reached its {', '.join(spent)} budget and completed without "
                "further model calls; the narrative is composed from verified values."
            ),
        )


def assert_no_dangerous_tools(registry: ToolRegistry | None = None) -> tuple[str, ...]:
    """Return the advertised tool names, having proved none is general-purpose.

    Args:
        registry: The registry whose advertised surface is checked. When
            omitted the module-level tool table is checked instead, which is
            what a static test wants.

    Returns:
        The advertised names, sorted.

    Raises:
        DangerousToolError: If a tool is advertised that is not one of the eight
            read-only tools, or whose name has the shape of a general capability.
    """

    names = sorted(tool.name for tool in (registry.describe() if registry is not None else TOOLS))
    unexpected = sorted(set(names) - ALLOWED_TOOL_NAMES)
    if unexpected:
        raise DangerousToolError(
            f"tools outside the read-only set are advertised to the model: {unexpected}"
        )
    for name in names:
        for pattern in DANGEROUS_TOOL_PATTERNS:
            if re.search(pattern, _separated(name)):
                raise DangerousToolError(
                    f"tool {name!r} matches the general-capability shape {pattern!r}"
                )
    return tuple(names)


__all__ = [
    "ALLOWED_TOOL_NAMES",
    "DANGEROUS_TOOL_PATTERNS",
    "MAX_MODEL_CALLS",
    "MAX_RUN_SECONDS",
    "MAX_RUN_TOKENS",
    "DangerousToolError",
    "RunBudget",
    "assert_no_dangerous_tools",
]
