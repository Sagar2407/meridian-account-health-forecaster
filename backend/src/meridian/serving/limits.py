"""Demo-mode restrictions and run rate limits (plan section 24.3).

Section 24.3 lists the controls a public deployment needs, and the ones that
belong to the request boundary are here: who may start a run, how often, and
whether free text is allowed at all. The rest live where they can actually be
enforced -- per-run model and token budgets in `meridian.guardrails.runtime`,
tool argument validation in the registry, and secret handling in settings.

Everything is in-process and in-memory. That is the right size for a single
free-tier container and is stated rather than hidden: a horizontally scaled
deployment would need a shared counter, and the docstring on `RateLimiter` says
so instead of leaving a reader to discover it under load.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from meridian.settings import Settings

#: The window a per-client limit is measured over.
CLIENT_WINDOW_SECONDS = 3_600.0

#: The window the service-wide limit is measured over.
DAILY_WINDOW_SECONDS = 86_400.0

#: What a demo-mode caller may ask. Section 24.3 asks to "restrict arbitrary
#: free-text to the account-health domain"; the intake guardrail already refuses
#: out-of-domain *shapes*, and this refuses free text outright in favour of the
#: curated question, which is the stronger control for an unauthenticated page.
DEMO_QUESTION = "What is the renewal outlook for this account, and what drives it?"


class RateLimitExceededError(RuntimeError):
    """Raised when a caller has started more runs than its allowance."""

    def __init__(self, message: str, retry_after_seconds: float) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class DemoModeError(RuntimeError):
    """Raised when a request asks for something demo mode does not allow."""


@dataclass
class RateLimiter:
    """Sliding-window run limits, per client and for the service as a whole.

    In-memory and per-process: correct for the single container this system is
    deployed as, and deliberately not presented as more than that. A limit of
    zero disables that window rather than blocking everything, so a local
    developer does not have to think about rate limits at all.
    """

    per_client_hourly: int
    daily_total: int
    _clients: dict[str, deque[float]] = field(default_factory=dict)
    _global: deque[float] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RateLimiter":
        """Build a limiter from configuration."""

        return cls(
            per_client_hourly=settings.rate_limit_runs_per_hour,
            daily_total=settings.rate_limit_daily_runs,
        )

    @staticmethod
    def _prune(stamps: deque[float], now: float, window: float) -> None:
        """Drop timestamps that have fallen out of the window."""

        while stamps and now - stamps[0] >= window:
            stamps.popleft()

    def check(self, client: str, now: float | None = None) -> None:
        """Record one run for `client`, or refuse it.

        Args:
            client: A stable identifier for the caller, usually its address.
            now: The current time; injectable so a test does not have to sleep.

        Raises:
            RateLimitExceededError: If either window is full. Nothing is
                recorded when the call is refused, so a client that is over its
                limit does not push its own reset further away with every retry.
        """

        moment = now if now is not None else time.monotonic()
        with self._lock:
            self._prune(self._global, moment, DAILY_WINDOW_SECONDS)
            if self.daily_total and len(self._global) >= self.daily_total:
                oldest = self._global[0]
                raise RateLimitExceededError(
                    f"the service has started its {self.daily_total} runs for today",
                    retry_after_seconds=max(0.0, DAILY_WINDOW_SECONDS - (moment - oldest)),
                )

            stamps = self._clients.setdefault(client, deque())
            self._prune(stamps, moment, CLIENT_WINDOW_SECONDS)
            if self.per_client_hourly and len(stamps) >= self.per_client_hourly:
                oldest = stamps[0]
                raise RateLimitExceededError(
                    f"this client has started its {self.per_client_hourly} runs for this hour",
                    retry_after_seconds=max(0.0, CLIENT_WINDOW_SECONDS - (moment - oldest)),
                )

            stamps.append(moment)
            self._global.append(moment)

    def remaining(self, client: str, now: float | None = None) -> dict[str, int | None]:
        """Return how much allowance is left, for a response header or a page."""

        moment = now if now is not None else time.monotonic()
        with self._lock:
            self._prune(self._global, moment, DAILY_WINDOW_SECONDS)
            stamps = self._clients.get(client, deque())
            self._prune(stamps, moment, CLIENT_WINDOW_SECONDS)
            return {
                "client_hourly": (
                    None
                    if not self.per_client_hourly
                    else max(0, self.per_client_hourly - len(stamps))
                ),
                "service_daily": (
                    None if not self.daily_total else max(0, self.daily_total - len(self._global))
                ),
            }


def enforce_demo_mode(
    settings: Settings, account_id: str, question: str, known_accounts: frozenset[str]
) -> str:
    """Return the question a demo-mode run may ask, or refuse the request.

    Section 24.3 asks demo mode to "restrict assessments to a dropdown of
    synthetic accounts" and to keep free text inside the domain. Both are
    enforced here rather than trusted to the browser, because a dropdown is a
    convenience for a person and no obstacle at all to anyone using the API
    directly.

    Raises:
        DemoModeError: If the account is not one of the synthetic portfolio's.
    """

    if not settings.demo_mode:
        return question
    if account_id not in known_accounts:
        raise DemoModeError(
            f"{account_id} is not in the synthetic demo portfolio; "
            "the public demo assesses only its own accounts"
        )
    # The question is replaced rather than validated. A free-text field on an
    # unauthenticated public page is a prompt-injection surface whose only
    # defence would be the intake guardrail, and the demo does not need one.
    return DEMO_QUESTION


__all__ = [
    "CLIENT_WINDOW_SECONDS",
    "DAILY_WINDOW_SECONDS",
    "DEMO_QUESTION",
    "DemoModeError",
    "RateLimitExceededError",
    "RateLimiter",
    "enforce_demo_mode",
]
