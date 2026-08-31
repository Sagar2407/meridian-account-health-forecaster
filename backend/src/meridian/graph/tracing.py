"""Safe structured tracing for every run (plan sections 19.2, 21.1, and 21.3).

Section 21.1 makes local tracing mandatory and lists what an event must carry.
Section 21.3 lists what it must not: no secrets, no raw private reasoning, only
the evidence excerpts an audit needs, and arbitrary user text hashed or
truncated rather than stored whole.

Both rules live here. `redact` is the single place a payload is made safe, and
`TraceEvent` re-checks the result, so a node that builds an event by hand still
cannot publish a prompt.
"""

import hashlib
import itertools
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from meridian.contracts import FORBIDDEN_TRACE_KEYS, TraceEvent

#: The event vocabulary. The first twelve are named in plan section 19.2; the
#: rest are the nodes section 14's flowchart requires that section 19.2 does not
#: happen to list, and they follow the same naming.
GraphEvent = Literal[
    "run_started",
    "request_validated",
    "plan_created",
    "quantitative_completed",
    "retrieval_attempted",
    "retrieval_retried",
    "evidence_merged",
    "conflict_detected",
    "conflict_evaluated",
    "tot_started",
    "output_verified",
    "review_required",
    "run_completed",
    "request_blocked",
    "context_loaded",
    "coverage_evaluated",
    "evidence_round_started",
    "degraded_result",
    "decision_drafted",
    "decision_routed",
    "decision_persisted",
    "node_failed",
]

MAX_TRACE_TEXT_CHARACTERS = 200
MAX_TRACE_LIST_ITEMS = 12

#: Keys whose values are arbitrary user text. They are truncated and fingerprinted
#: rather than dropped: an operator needs to correlate runs about the same
#: question without the metric store holding the whole of it (section 21.3).
FINGERPRINTED_KEYS: frozenset[str] = frozenset({"question", "query", "sub_goal"})

_sequence = itertools.count(1)
_sequence_lock = threading.Lock()


def next_sequence() -> int:
    """Return a process-wide monotonic event ordinal.

    A per-run counter would need a lock the checkpointer cannot restore and
    could not be shared safely by the two parallel lanes. A monotonic ordinal
    gives every event a total order within a run, which is what a trace reader
    actually needs, and survives a resume.
    """

    with _sequence_lock:
        return next(_sequence)


def text_fingerprint(value: str) -> str:
    """Return a short stable digest of arbitrary user text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _safe_scalar(value: Any) -> Any | None:
    """Return `value` if it is safe to publish, otherwise None."""

    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, str):
        return value[:MAX_TRACE_TEXT_CHARACTERS]
    return None


def redact(payload: Mapping[str, Any]) -> dict[str, object]:
    """Return a payload safe to store and stream.

    Scalars pass through, strings are truncated, short lists of scalars are
    kept, and everything else is dropped. Dropped key *names* are recorded so a
    reviewer can see that something was removed without seeing what it was.
    """

    safe: dict[str, object] = {}
    dropped: list[str] = []
    for key, value in payload.items():
        if key in FORBIDDEN_TRACE_KEYS:
            dropped.append(key)
            continue
        if key in FINGERPRINTED_KEYS and isinstance(value, str):
            safe[key] = value[:MAX_TRACE_TEXT_CHARACTERS]
            safe[f"{key}_digest"] = text_fingerprint(value)
            continue
        scalar = _safe_scalar(value)
        if scalar is not None or value is None:
            safe[key] = scalar
            continue
        if isinstance(value, list | tuple):
            items = [_safe_scalar(item) for item in list(value)[:MAX_TRACE_LIST_ITEMS]]
            safe[key] = [item for item in items if item is not None]
            continue
        dropped.append(key)
    if dropped:
        safe["redacted_keys"] = sorted(dropped)
    return safe


class TraceRecorder:
    """Build trace events for one run.

    Instances are cheap and stateless apart from their identifiers, so a node
    creates one, emits, and returns the events in its state update. Nothing is
    accumulated here: the state's `trace_summary` reducer owns accumulation, so
    a resumed run does not replay events it already recorded.
    """

    def __init__(self, run_id: str, thread_id: str) -> None:
        self.run_id = run_id
        self.thread_id = thread_id

    def event(
        self,
        node: str,
        event: GraphEvent,
        payload: Mapping[str, Any] | None = None,
        latency_ms: float = 0.0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> TraceEvent:
        """Return one redacted trace event."""

        return TraceEvent(
            run_id=self.run_id,
            thread_id=self.thread_id,
            sequence=next_sequence(),
            timestamp=datetime.now(UTC).isoformat(timespec="milliseconds"),
            node=node,
            event=event,
            payload=redact(payload or {}),
            latency_ms=round(max(latency_ms, 0.0), 3),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def ordered(events: Iterable[TraceEvent]) -> tuple[TraceEvent, ...]:
    """Return events in the order they were emitted."""

    return tuple(sorted(events, key=lambda item: item.sequence))


__all__ = [
    "FINGERPRINTED_KEYS",
    "MAX_TRACE_TEXT_CHARACTERS",
    "GraphEvent",
    "TraceRecorder",
    "next_sequence",
    "ordered",
    "redact",
    "text_fingerprint",
]
