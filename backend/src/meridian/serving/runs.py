"""Running assessments for a caller, and streaming what they are doing.

Plan sections 19.1 and 19.2. `POST /api/assessments` has to return before the
run finishes -- a graph run takes seconds, and the point of the streaming
endpoint is to watch it happen -- so a run needs somewhere to live between the
request that starts it and the requests that read it.

That is this module. It is a bounded in-memory registry with a worker pool, and
it is deliberately not a job queue: the plan's deployment target is one small
container, the runs are seconds long, and results that matter are already
persisted to application memory by the graph's own `persist` node. What is kept
here is the *live* view -- progress events and the in-flight state -- which is
worthless after the fact and is evicted accordingly.

Nothing streamed from here can carry a prompt or private reasoning: the events
are `TraceEvent`s, which are redacted at construction (section 21.3).
"""

import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, Queue
from typing import Any, Literal

from meridian.contracts import AssessmentRequest, TraceEvent
from meridian.graph import AssessmentRun, build_graph, run_assessment
from meridian.graph.runtime import GraphRuntime

RunStatus = Literal["queued", "running", "completed", "failed"]

#: How many finished runs stay readable before the oldest is evicted. Sized for
#: a demo: enough that a person can page back through what they just did, small
#: enough that an unattended service cannot grow without bound.
MAX_RETAINED_RUNS = 200

#: How long a streaming client waits for the next event before the server sends
#: a keep-alive comment. Without one, an idle proxy closes the connection.
STREAM_POLL_SECONDS = 1.0

#: Sentinel pushed onto a run's queue when it finishes, so a subscriber can end
#: its stream instead of waiting for an event that will never arrive.
_DONE = object()


@dataclass
class ServedRun:
    """One assessment being run on a caller's behalf."""

    run_id: str
    request: AssessmentRequest
    status: RunStatus = "queued"
    started_at: str = ""
    finished_at: str | None = None
    events: list[TraceEvent] = field(default_factory=list)
    result: AssessmentRun | None = None
    error: str | None = None
    _subscribers: list[Queue[object]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def publish(self, event: TraceEvent) -> None:
        """Record an event and hand it to every live subscriber."""

        with self._lock:
            self.events.append(event)
            subscribers = list(self._subscribers)
        for queue in subscribers:
            queue.put(event)

    def finish(self) -> None:
        """Tell every subscriber the run is over."""

        with self._lock:
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for queue in subscribers:
            queue.put(_DONE)

    def subscribe(self) -> Queue[object]:
        """Return a queue seeded with the events already emitted.

        Seeding matters: a client that connects to the stream a moment after
        starting the run would otherwise miss `run_started` and every event up
        to the moment it arrived, and a progress view that begins in the middle
        is worse than no progress view.
        """

        queue: Queue[object] = Queue()
        with self._lock:
            for event in self.events:
                queue.put(event)
            if self.status in {"completed", "failed"}:
                queue.put(_DONE)
            else:
                self._subscribers.append(queue)
        return queue

    def snapshot(self) -> dict[str, Any]:
        """Return the state projection section 19.1 serves for a run."""

        with self._lock:
            events = list(self.events)
        return {
            "run_id": self.run_id,
            "account_id": self.request.account_id,
            "question": self.request.question,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "events_emitted": len(events),
            "last_event": events[-1].event if events else None,
            "error": self.error,
        }


class RunManager:
    """Start assessments, track them, and stream their progress."""

    def __init__(self, runtime: GraphRuntime, max_workers: int = 4) -> None:
        self._runtime = runtime
        self._graph = build_graph(runtime)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="run")
        self._runs: OrderedDict[str, ServedRun] = OrderedDict()
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    def start(self, request: AssessmentRequest, run_id: str | None = None) -> ServedRun:
        """Begin one assessment and return its live record immediately."""

        identifier = run_id or f"RUN-{uuid.uuid4().hex[:12]}"
        served = ServedRun(
            run_id=identifier,
            request=request,
            status="running",
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        with self._lock:
            self._runs[identifier] = served
            while len(self._runs) > MAX_RETAINED_RUNS:
                evicted, _ = self._runs.popitem(last=False)
                self._futures.pop(evicted, None)
            self._futures[identifier] = self._pool.submit(self._execute, served)
        return served

    def _execute(self, served: ServedRun) -> None:
        """Run the graph, publishing events as they happen."""

        try:
            served.result = run_assessment(
                self._graph,
                served.request,
                run_id=served.run_id,
                on_event=served.publish,
            )
            served.status = "completed"
        except Exception as error:  # a failed run is data, not a dead worker
            served.status = "failed"
            served.error = f"{type(error).__name__}: {error}"
        finally:
            served.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
            served.finish()

    def get(self, run_id: str) -> ServedRun | None:
        """Return one run, or None if it never existed or was evicted."""

        with self._lock:
            return self._runs.get(run_id)

    def stream(self, run_id: str) -> Iterator[TraceEvent | None]:
        """Yield each event as it happens, then stop when the run ends.

        Yields None whenever the wait times out, so the caller can emit a
        keep-alive without this module knowing anything about SSE framing.
        """

        served = self.get(run_id)
        if served is None:
            return
        queue = served.subscribe()
        while True:
            try:
                item = queue.get(timeout=STREAM_POLL_SECONDS)
            except Empty:
                yield None
                continue
            if item is _DONE:
                return
            assert isinstance(item, TraceEvent)
            yield item

    def wait(self, run_id: str, timeout: float | None = None) -> ServedRun | None:
        """Block until one run finishes. For tests and the CLI, not for a route."""

        with self._lock:
            future = self._futures.get(run_id)
        if future is not None:
            future.result(timeout=timeout)
        return self.get(run_id)

    def shutdown(self) -> None:
        """Stop the worker pool. Called when the application shuts down."""

        self._pool.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "MAX_RETAINED_RUNS",
    "STREAM_POLL_SECONDS",
    "RunManager",
    "RunStatus",
    "ServedRun",
]
