"""What a graph run needs to reach data and models (plan section 14).

The graph is compiled once and run many times, so its dependencies live in one
frozen container rather than being rebuilt per run or reached through module
globals. Two of them are optional by design:

* **The forecaster artifact.** Without it there is no calibrated distribution,
  so the run degrades to verified telemetry instead of failing.
* **The language-model provider.** Every phase through 4 runs with no
  credential, and Phase 5 keeps that property: the graph completes without one,
  with a deterministic narrative and a stated limitation.

Retrieval is built lazily because loading the index rebuilds the corpus to check
its digest, which is seconds of work no run without a retrieval sub-goal should
pay for.
"""

from dataclasses import dataclass

from meridian.agents.evidence_retriever import EvidenceRetriever
from meridian.agents.forecast_adjudicator import ForecastAdjudicator
from meridian.agents.orchestrator import Orchestrator
from meridian.agents.quantitative_analyst import QuantitativeAnalyst
from meridian.data.repository import RuntimeRepository
from meridian.features.baselines import BaselineProvider
from meridian.guardrails.policy import HighValuePolicy
from meridian.llm.base import ProviderNotConfiguredError, StructuredGenerator
from meridian.llm.providers import build_generator
from meridian.memory.store import AssessmentStore
from meridian.model.artifacts import ModelArtifact, load_artifact
from meridian.retrieval.index import load_verified_index
from meridian.retrieval.search import RetrievalService
from meridian.settings import Settings, get_settings
from meridian.tools.registry import ToolRegistry
from meridian.tools.services import ToolServices, ToolUnavailableError


def _retrieval_factory(repository: RuntimeRepository) -> RetrievalService:
    """Return a retrieval service, or say precisely why there is not one.

    Every failure becomes `ToolUnavailableError` because that is the one the
    retrieval lane treats as "degrade, do not crash". A bare `FileNotFoundError`
    from three layers down would escape that handling and end the run.
    """

    try:
        index = load_verified_index(repository)
    except Exception as error:  # a broad catch, narrowed into one typed failure below
        raise ToolUnavailableError(
            f"the retrieval index is unavailable ({type(error).__name__}: {error}); "
            "build it with `make index`"
        ) from error
    return RetrievalService(index, repository)


@dataclass(frozen=True)
class GraphRuntime:
    """Everything the nodes need, assembled once."""

    repository: RuntimeRepository
    registry: ToolRegistry
    high_value: HighValuePolicy
    orchestrator: Orchestrator
    analyst: QuantitativeAnalyst
    retriever: EvidenceRetriever
    adjudicator: ForecastAdjudicator
    store: AssessmentStore | None = None
    artifact: ModelArtifact | None = None
    generator: StructuredGenerator | None = None
    #: Portfolio medians for the two relative conflict rules (section 15.1).
    #: Deferred rather than eager: the sweep costs about two seconds, and a
    #: run that is blocked or degrades on coverage never reaches the gate.
    baselines: BaselineProvider | None = None

    @property
    def has_model(self) -> bool:
        """Return whether a language-model provider is configured."""

        return self.generator is not None

    @property
    def has_forecaster(self) -> bool:
        """Return whether the calibrated forecaster artifact is loaded."""

        return self.artifact is not None

    @classmethod
    def assemble(
        cls,
        repository: RuntimeRepository,
        registry: ToolRegistry,
        artifact: ModelArtifact | None = None,
        generator: StructuredGenerator | None = None,
        store: AssessmentStore | None = None,
        high_value: HighValuePolicy | None = None,
        baselines: BaselineProvider | None = None,
    ) -> "GraphRuntime":
        """Build a runtime from parts, for tests and for `build`."""

        return cls(
            repository=repository,
            registry=registry,
            high_value=high_value or HighValuePolicy.from_repository(repository),
            orchestrator=Orchestrator(registry, generator),
            analyst=QuantitativeAnalyst(registry, artifact),
            retriever=EvidenceRetriever(registry),
            adjudicator=ForecastAdjudicator(generator),
            store=store,
            artifact=artifact,
            generator=generator,
            baselines=baselines if baselines is not None else BaselineProvider.over(repository),
        )

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        repository: RuntimeRepository | None = None,
    ) -> "GraphRuntime":
        """Assemble a runtime from the environment, degrading where it must."""

        resolved = settings if settings is not None else get_settings()
        data = repository if repository is not None else RuntimeRepository()

        store = AssessmentStore()
        services = ToolServices(
            data,
            retrieval=lambda: _retrieval_factory(data),
            store=store,
        )

        try:
            artifact: ModelArtifact | None = load_artifact()
        except (FileNotFoundError, OSError, ValueError):
            artifact = None

        try:
            generator: StructuredGenerator | None = build_generator(resolved)
        except ProviderNotConfiguredError:
            generator = None

        return cls.assemble(
            repository=data,
            registry=ToolRegistry(services),
            artifact=artifact,
            generator=generator,
            store=store,
        )


__all__ = ["GraphRuntime"]
