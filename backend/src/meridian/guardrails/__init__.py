"""Safety rules applied at the boundaries of a run (plan section 16).

Section 16 names five guardrail stages, and all five are here or are enforced
by the module named beside them:

* **Intake** (16.2) -- `meridian.guardrails.intake`: nine rules over the request.
* **Execution** (16.3) -- the tool registry's per-role allowlist, argument
  validation, and timeouts, plus `meridian.guardrails.runtime` for the model
  call, token, and wall-clock budgets and the assertion that no general-purpose
  tool is ever advertised to a model.
* **Evidence** (16.3) -- `meridian.guardrails.evidence`: the account, cutoff,
  and provenance screen applied to the assembled bundle.
* **Output** (16.4) -- `meridian.agents.forecast_adjudicator.verify_output`,
  which replays every numeric claim and citation against the evidence.
* **Routing** (16.5) -- `meridian.graph.routing.human_route`, over the
  deterministic confidence in `meridian.graph.confidence`.

`meridian.guardrails.policy` supplies the high-value definition the routing
bands depend on. Every stage produces the same `GuardrailDecision` type, and a
run accumulates them in `state["guardrails"]`, which is what the safety report
is built from.
"""

from meridian.guardrails.evidence import EvidenceScreening, screen_evidence
from meridian.guardrails.intake import INTAKE_RULES, evaluate_intake
from meridian.guardrails.policy import HighValuePolicy
from meridian.guardrails.runtime import (
    DangerousToolError,
    RunBudget,
    assert_no_dangerous_tools,
)

__all__ = [
    "INTAKE_RULES",
    "DangerousToolError",
    "EvidenceScreening",
    "HighValuePolicy",
    "RunBudget",
    "assert_no_dangerous_tools",
    "evaluate_intake",
    "screen_evidence",
]
