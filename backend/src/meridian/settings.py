from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Providers the repository knows about. Only `openai_compatible` is
#: implemented; the rest are declared so a misconfiguration fails with a
#: specific message rather than a KeyError (plan section 12, ADR 0004).
LlmProvider = Literal["openai_compatible", "anthropic", "azure_openai", "ollama", "disabled"]


class Settings(BaseSettings):
    """Validated runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MERIDIAN_",
        extra="ignore",
        # `llm_api_key` carries a validation alias so it can also be read from
        # OPENAI_API_KEY. Without this, the field could only ever be set by one
        # of its alias names, which would make it awkward to construct Settings
        # directly in a test or a script.
        populate_by_name=True,
    )

    app_name: str = "Meridian Enterprise Account Health Forecaster"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = "http://localhost:5173"

    # Language-model configuration (ADR 0004). Every phase through 4 runs with
    # `llm_api_key` empty; only model-backed features need it.
    llm_provider: LlmProvider = "openai_compatible"
    llm_model: str = "anthropic/claude-sonnet-4.5"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # `OPENAI_API_KEY` is accepted as a second name for historical reasons: it
    # is what this project's .env has always used, and in it that variable
    # holds an OpenRouter key rather than an OpenAI one. The base URL, not the
    # variable name, decides which service is called.
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MERIDIAN_LLM_API_KEY", "OPENAI_API_KEY"),
    )

    @property
    def llm_is_configured(self) -> bool:
        """Return whether a model-backed feature can run at all."""

        return self.llm_provider != "disabled" and bool(self.llm_api_key)

    @property
    def allowed_origins(self) -> list[str]:
        """Return normalized, non-empty browser origins."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()
