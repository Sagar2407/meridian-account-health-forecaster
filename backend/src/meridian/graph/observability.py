"""Where a run's trace goes, and what a run cost (plan section 21).

Section 21.1 makes local tracing mandatory and lists what every event must
carry. `meridian.graph.tracing` already builds those events and guarantees they
are safe to publish; this module is the other half -- where they are written,
and the two fields section 21.1 asks for that an event cannot know on its own:
the estimated model cost, and the run's final disposition.

Section 21.2 allows mirroring to LangSmith when `LANGSMITH_TRACING=true`, and
requires the application to stay fully functional when it is off. That is why
LangSmith is reached through the same `TraceSink` interface as a local file: the
graph writes events to a sink and never asks which kind it is.

Nothing here can publish a prompt. The events are `TraceEvent`s, redacted where
they were built, and this module only routes them.
"""

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from meridian.contracts import TraceEvent
from meridian.data.paths import application_directory

#: Where run traces are written when no path is given.
TRACE_FILENAME = "runs.jsonl"

#: Estimated cost per million tokens, by model family. Deliberately coarse and
#: labelled an estimate everywhere it surfaces: an exact bill comes from the
#: provider, and a number this file invents must never be mistaken for one.
#:
#: Prices are USD per million tokens as published for the listed models. They go
#: stale; the cost field is an order-of-magnitude aid for "did this run cost
#: cents or dollars", not an accounting record.
TOKEN_PRICES: dict[str, tuple[float, float]] = {
    # family prefix: (prompt, completion)
    "anthropic/claude-sonnet": (3.00, 15.00),
    "anthropic/claude-haiku": (0.80, 4.00),
    "anthropic/claude-opus": (15.00, 75.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
}

#: Used when the configured model matches no known family. Zero rather than a
#: guess: an unknown price is unknown, and a plausible-looking invented number
#: is worse than an obvious blank.
UNKNOWN_PRICE = (0.0, 0.0)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Return the estimated USD cost of one run, or None for an unknown model.

    Args:
        model: The configured model identifier.
        prompt_tokens: Tokens sent.
        completion_tokens: Tokens returned.

    Returns:
        The estimate, or None when the model matches no known price. None is
        deliberate: a caller can render "unknown" but cannot accidentally sum a
        fabricated zero into a total.
    """

    if not model or (prompt_tokens == 0 and completion_tokens == 0):
        return 0.0
    for prefix, (prompt_price, completion_price) in TOKEN_PRICES.items():
        if model.startswith(prefix):
            return round(
                prompt_tokens / 1_000_000 * prompt_price
                + completion_tokens / 1_000_000 * completion_price,
                6,
            )
    return None


class TraceSink(Protocol):
    """Somewhere a run's events go."""

    def write(self, event: TraceEvent) -> None:
        """Record one event."""

    def close(self) -> None:
        """Release whatever the sink holds."""


@dataclass
class JsonlTraceSink:
    """Append every event to a JSON Lines file (plan section 21.1).

    One line per event, appended immediately. A trace that only reached disk at
    the end of a run would be missing for exactly the runs worth investigating:
    the ones that crashed.
    """

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)
    written: int = 0

    def write(self, event: TraceEvent) -> None:
        """Append one event as a single JSON line."""

        line = json.dumps(event.model_dump(mode="json"), sort_keys=True, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self.written += 1

    def close(self) -> None:
        """Nothing is held open between writes."""


@dataclass
class MemoryTraceSink:
    """Collect events in memory. For tests and for a caller that wants both."""

    events: list[TraceEvent] = field(default_factory=list)

    def write(self, event: TraceEvent) -> None:
        """Record one event."""

        self.events.append(event)

    def close(self) -> None:
        """Nothing to release."""


@dataclass
class FanOutTraceSink:
    """Write to several sinks, and never let one failure lose the others.

    A LangSmith outage must not take the local trace with it (section 21.2
    requires the application to be fully functional without LangSmith), so a
    sink that raises is dropped from the fan-out rather than propagated.
    """

    sinks: list[TraceSink] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)

    def write(self, event: TraceEvent) -> None:
        """Write to every healthy sink."""

        for sink in list(self.sinks):
            try:
                sink.write(event)
            except Exception as error:  # one sink must not take the others down
                self.failures[type(sink).__name__] = f"{type(error).__name__}: {error}"
                self.sinks.remove(sink)

    def close(self) -> None:
        """Close every sink, ignoring failures on the way out."""

        for sink in self.sinks:
            # Closing is best-effort: a sink that fails on the way out must not
            # turn a completed run into an exception.
            with suppress(Exception):
                sink.close()


def langsmith_is_enabled() -> bool:
    """Return whether section 21.2's optional mirroring was asked for."""

    return os.environ.get("LANGSMITH_TRACING", "").strip().lower() in {"1", "true", "yes"}


@dataclass
class LangSmithTraceSink:
    """Mirror events to LangSmith when it is configured and importable.

    Constructed only through `build_sink`, which checks `LANGSMITH_TRACING`
    first. If the package is absent or the client cannot be built, `available`
    is False and the sink does nothing -- the run still completes, still writes
    its local trace, and still returns the same answer.
    """

    project: str = "meridian"
    available: bool = False
    unavailable_reason: str | None = None
    _client: Any = None

    def __post_init__(self) -> None:
        """Try to build a client, and record plainly why if it cannot."""

        try:
            from langsmith import Client
        except ImportError as error:
            self.unavailable_reason = f"langsmith is not installed ({error})"
            return
        try:
            self._client = Client()
            self.available = True
        except Exception as error:  # a misconfigured client must not end a run
            self.unavailable_reason = f"{type(error).__name__}: {error}"

    def write(self, event: TraceEvent) -> None:
        """Mirror one event, ignoring a transport failure."""

        if not self.available or self._client is None:
            return
        try:
            self._client.create_run(
                name=f"{event.node}.{event.event}",
                run_type="chain",
                project_name=self.project,
                inputs={"node": event.node, "sequence": event.sequence},
                outputs=dict(event.payload),
                extra={
                    "latency_ms": event.latency_ms,
                    "prompt_tokens": event.prompt_tokens,
                    "completion_tokens": event.completion_tokens,
                    "thread_id": event.thread_id,
                },
            )
        except Exception as error:  # section 21.2: never let mirroring fail a run
            self.available = False
            self.unavailable_reason = f"{type(error).__name__}: {error}"

    def close(self) -> None:
        """The client holds no resource this module owns."""


@contextmanager
def build_sink(path: Path | None = None, project: str = "meridian") -> Iterator[FanOutTraceSink]:
    """Yield the sink a run should write to.

    Always a local JSON Lines file (section 21.1 makes it mandatory), plus
    LangSmith when `LANGSMITH_TRACING` asks for it and the package is present.

    Args:
        path: Where to append. Defaults to the application directory.
        project: The LangSmith project name, when mirroring.
    """

    target = path or (application_directory() / TRACE_FILENAME)
    sink = FanOutTraceSink(sinks=[JsonlTraceSink(path=target)])
    if langsmith_is_enabled():
        mirror = LangSmithTraceSink(project=project)
        if mirror.available:
            sink.sinks.append(mirror)
        else:
            sink.failures["LangSmithTraceSink"] = mirror.unavailable_reason or "unavailable"
    try:
        yield sink
    finally:
        sink.close()


def run_summary(
    run_id: str,
    thread_id: str,
    account_id: str,
    disposition: str,
    route: str | None,
    events: tuple[TraceEvent, ...],
    model: str = "",
    guardrail_rule_ids: tuple[str, ...] = (),
    confidence_breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the one-line run record section 21.1 asks each run to emit.

    The events carry the per-node detail; this is the run-level view a metric
    store aggregates: what it decided, what it cost, and which rules fired.
    """

    prompt_tokens = sum(event.prompt_tokens for event in events)
    completion_tokens = sum(event.completion_tokens for event in events)
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "account_id": account_id,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "disposition": disposition,
        "route": route,
        "events": len(events),
        "latency_ms": round(sum(event.latency_ms for event in events), 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
        "estimated_cost_note": ("an estimate from a static price table, not a provider bill"),
        "model": model,
        "guardrail_rule_ids": list(guardrail_rule_ids),
        "confidence_breakdown": confidence_breakdown,
    }


__all__ = [
    "TOKEN_PRICES",
    "TRACE_FILENAME",
    "FanOutTraceSink",
    "JsonlTraceSink",
    "LangSmithTraceSink",
    "MemoryTraceSink",
    "TraceSink",
    "build_sink",
    "estimate_cost",
    "langsmith_is_enabled",
    "run_summary",
]
