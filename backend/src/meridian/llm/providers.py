"""Provider selection and the skeletons that are not implemented yet (ADR 0004).

Plan section 12 asks for "optional adapter skeletons that fail clearly when not
configured". Clearly is the operative word: a caller that selects Azure should
be told the adapter does not exist, not handed a `KeyError`, and a caller with
no API key should be told which variable to set rather than watching a request
fail with a 401 somewhere deeper.

Selecting a provider never performs I/O. Construction is cheap and offline;
only the first generation reaches the network.
"""

from dataclasses import dataclass

from meridian.llm.base import ProviderNotConfiguredError, StructuredGenerator
from meridian.llm.openai_compatible import OpenAICompatibleGenerator
from meridian.settings import LlmProvider, Settings, get_settings

#: Why each unimplemented provider is unavailable, and what to do instead. A
#: message that only says "not supported" makes the reader go and read the code.
_SKELETONS: dict[str, str] = {
    "anthropic": (
        "the native Anthropic adapter is not implemented. Claude is already "
        "reachable through the OpenAI-compatible endpoint: set "
        "MERIDIAN_LLM_PROVIDER=openai_compatible with an OpenRouter base URL "
        "and an anthropic/* model slug."
    ),
    "azure_openai": (
        "the Azure OpenAI adapter is not implemented. Azure serves the same "
        "wire format, so MERIDIAN_LLM_PROVIDER=openai_compatible with your "
        "deployment's base URL is likely to work today."
    ),
    "ollama": (
        "the Ollama adapter is not implemented. Ollama exposes an "
        "OpenAI-compatible endpoint, so MERIDIAN_LLM_PROVIDER=openai_compatible "
        "with MERIDIAN_LLM_BASE_URL=http://localhost:11434/v1 works today; from "
        "inside a container use http://host.docker.internal:11434/v1. Ollama "
        "ignores the api key, so set MERIDIAN_LLM_API_KEY to any non-empty "
        "string. MERIDIAN_LLM_STRUCTURED_OUTPUT defaults to auto, which steps "
        "down to a weaker JSON mode if the server rejects strict schemas."
    ),
    "disabled": (
        "language-model features are switched off (MERIDIAN_LLM_PROVIDER=disabled). "
        "Every deterministic feature -- data, metrics, forecasting, retrieval -- "
        "runs without one."
    ),
}


@dataclass(frozen=True)
class ProviderStatus:
    """What is configured, safe to log and safe to show in a health endpoint."""

    provider: LlmProvider
    model: str
    base_url: str
    configured: bool
    detail: str

    @property
    def summary(self) -> str:
        """Return a one-line description that never contains a credential."""

        state = "ready" if self.configured else "unavailable"
        return f"{self.provider}/{self.model} [{state}] {self.detail}".strip()


def describe_provider(settings: Settings | None = None) -> ProviderStatus:
    """Return the current provider configuration without touching the network.

    The API key is never included, not even truncated: a prefix is still a
    credential fragment, and nothing here needs one to be useful.
    """

    active = settings if settings is not None else get_settings()
    if active.llm_provider in _SKELETONS:
        return ProviderStatus(
            provider=active.llm_provider,
            model=active.llm_model,
            base_url=active.llm_base_url,
            configured=False,
            detail=_SKELETONS[active.llm_provider],
        )
    if not active.llm_api_key:
        return ProviderStatus(
            provider=active.llm_provider,
            model=active.llm_model,
            base_url=active.llm_base_url,
            configured=False,
            detail="no API key configured; set MERIDIAN_LLM_API_KEY to enable it",
        )
    return ProviderStatus(
        provider=active.llm_provider,
        model=active.llm_model,
        base_url=active.llm_base_url,
        configured=True,
        detail="credentials present",
    )


def build_generator(settings: Settings | None = None) -> StructuredGenerator:
    """Return the configured structured generator.

    Raises:
        ProviderNotConfiguredError: If the provider is a skeleton, is switched
            off, or has no credentials.
    """

    active = settings if settings is not None else get_settings()
    skeleton = _SKELETONS.get(active.llm_provider)
    if skeleton is not None:
        raise ProviderNotConfiguredError(skeleton)
    return OpenAICompatibleGenerator(
        api_key=active.llm_api_key,
        model=active.llm_model,
        base_url=active.llm_base_url,
        timeout_seconds=active.llm_timeout_seconds,
        structured_output=active.llm_structured_output,
    )
