from functools import lru_cache
from pathlib import Path
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
    #: How to ask for JSON.
    #:
    #: Hosted frontier models enforce a JSON Schema server-side, which is the
    #: strongest option and the default. Small open-weight models and the
    #: servers that host them often support only `json_object`, or nothing at
    #: all, and reject the stricter request outright -- which used to fail the
    #: whole call rather than degrade.
    #:
    #: `auto` asks for the strongest and steps down when the server refuses,
    #: remembering what worked. Correctness does not depend on the choice:
    #: `generate_structured` validates every reply against the Pydantic model
    #: whatever the server promised, so a weaker mode loses server-side
    #: enforcement, not verification.
    llm_structured_output: Literal["auto", "json_schema", "json_object", "prompt"] = "auto"
    # `OPENAI_API_KEY` is accepted as a second name for historical reasons: it
    # is what this project's .env has always used, and in it that variable
    # holds an OpenRouter key rather than an OpenAI one. The base URL, not the
    # variable name, decides which service is called.
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MERIDIAN_LLM_API_KEY", "OPENAI_API_KEY"),
    )

    # -- Phase 8: serving, scanning, and demo cost control -------------------
    # Plan sections 18.2 and 24.3. Every one of these has a safe default: a
    # deployment that sets nothing gets bounded concurrency, no scheduler, and
    # no unattended spending.

    #: How many account runs a portfolio scan may execute at once (section 18.1).
    scan_concurrency: int = Field(default=4, ge=1, le=32)
    #: The largest portfolio scan a caller may request in one request.
    scan_max_accounts: int = Field(default=50, ge=1, le=500)
    #: Days ahead of an account's renewal date that make it eligible for a scan
    #: (section 18.1's "configurable renewal horizon").
    scan_renewal_horizon_days: int = Field(default=120, ge=1, le=730)
    #: Provider calls one whole scan may make, across every account in it. This
    #: is the scan-level companion to the per-run budget in
    #: `meridian.guardrails.runtime`, and it is what the Phase 8 exit gate is
    #: measured against.
    scan_model_call_budget: int = Field(default=200, ge=0, le=100_000)

    #: Section 24.3. Demo mode restricts assessments to the synthetic portfolio,
    #: caps run rates, and refuses unattended spending. It is off locally and
    #: expected to be on in the public deployment.
    demo_mode: bool = False
    #: Runs one client address may start per hour. 0 disables the limit.
    rate_limit_runs_per_hour: int = Field(default=60, ge=0, le=100_000)
    #: Runs the whole service may start per day. 0 disables the limit.
    rate_limit_daily_runs: int = Field(default=500, ge=0, le=1_000_000)

    #: Where the compiled browser bundle lives, when one has been built into
    #: the image (plan section 24.2). Empty in development, where Vite serves
    #: the frontend on its own port; set by the production image.
    static_directory: str = ""

    #: Section 18.2. The scheduled worker is opt-in and stays off by default,
    #: because a schedule that spends money without a person present is the one
    #: autonomous behaviour this system must not have.
    enable_scheduler: bool = False
    #: Minutes between scheduled scans when the scheduler is enabled.
    scheduler_interval_minutes: int = Field(default=1_440, ge=5, le=44_640)

    @property
    def static_root(self) -> Path | None:
        """Return the compiled frontend directory, if one was built in.

        Returns None rather than a missing path, so the application mounts the
        SPA only when there is one to mount. A development container has no
        bundle and must not answer `/` with a 404 that looks like a broken
        deployment.
        """

        if not self.static_directory:
            return None
        candidate = Path(self.static_directory)
        return candidate if (candidate / "index.html").is_file() else None

    @property
    def scheduler_is_permitted(self) -> bool:
        """Return whether a scheduled scan may run unattended (sections 18.2, 24.3).

        Demo mode refuses it outright. "Disable unattended scheduled LLM
        spending in the public deployment by default" is a rule about money, so
        it is answered here rather than by remembering to unset a flag.
        """

        return self.enable_scheduler and not self.demo_mode

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
