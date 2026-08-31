"""The four agents of plan section 13.

Two of them are deterministic code and two use a language model, which is a
deliberate split rather than an implementation shortcut:

* The **Quantitative Analyst** computes; section 13.2 says an LLM is not
  required, and letting one near the arithmetic would put an unverifiable
  number in front of a user.
* The **Evidence Retriever** searches, filters, and grades; the ranking is
  semantic but every safety property it must hold -- account scope, cutoff,
  source family -- is deterministic.
* The **Orchestrator** may use a model to suggest sub-goals, bounded by a typed
  vocabulary, and falls back to a deterministic plan.
* The **Forecast Adjudicator** may use a model to write the rationale, the
  limitations, and the recommended action. It never chooses the outcome label:
  that comes from the calibrated forecaster.
"""

from meridian.agents.evidence_retriever import EvidenceRetriever
from meridian.agents.forecast_adjudicator import AdjudicationDraft, ForecastAdjudicator
from meridian.agents.orchestrator import Orchestrator, PlanResult
from meridian.agents.quantitative_analyst import QuantitativeAnalyst

__all__ = [
    "AdjudicationDraft",
    "EvidenceRetriever",
    "ForecastAdjudicator",
    "Orchestrator",
    "PlanResult",
    "QuantitativeAnalyst",
]
