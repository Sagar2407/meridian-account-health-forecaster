"""Safety rules applied at the boundaries of a run (plan section 16).

Phase 5 implements the intake stage and the high-value policy the routing bands
depend on. The execution stage already exists as the tool registry's role
allowlist and argument validation (section 16.3), and the output stage lives
with the adjudicator that produces the draft it verifies. Phase 7 completes the
set and runs the packaged guardrail cases against it.
"""

from meridian.guardrails.intake import INTAKE_RULES, evaluate_intake
from meridian.guardrails.policy import HighValuePolicy

__all__ = ["INTAKE_RULES", "HighValuePolicy", "evaluate_intake"]
