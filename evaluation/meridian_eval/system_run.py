"""One pass over a split, recording everything the five dimensions need.

Plan section 22 asks for five kinds of measurement, and three of them --
grounded explanation, calibration-at-the-band, and operational reliability --
are properties of *runs*, not of the model. Running the graph once per
dimension would mean four passes over the split for the same runs, so this
takes one pass and records enough for each dimension to compute from.

What is recorded is deliberately structured, not prose: rule codes rather than
sentences, citation ids rather than excerpts, counts rather than judgements. A
dimension that needed to parse a message would be measuring the message.

This module reads outcome labels. Nothing in `meridian` imports it, and
`test_import_boundary.py` fails the build if that changes.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from meridian.contracts import (
    AssessmentRequest,
    ForecastDecision,
    InsufficientEvidenceDecision,
)
from meridian.graph import AssessmentRun, build_graph, run_assessment
from meridian.graph.confidence import top_two_margin
from meridian.graph.runtime import GraphRuntime
from meridian_eval.repository import EvaluationRepository

#: The question every evaluated run asks. Held constant so a difference between
#: two runs is a difference in the account, not in what was asked.
EVALUATION_QUESTION = "What is the renewal outlook for this account, and what drives it?"

#: Ground-truth driver names the runtime computes under a different name. The
#: archive predates the recomputation of section 8.3, so one metric moved.
DRIVER_ALIASES: dict[str, str] = {"avg_csat": "avg_closed_csat_26w"}


@dataclass(frozen=True)
class SystemRun:
    """One account's complete run, reduced to what the report measures."""

    account_id: str
    label: str
    segment: str
    region: str

    # -- Disposition -------------------------------------------------------
    released: bool
    abstained: bool
    blocked: bool
    outcome: str | None
    route: str
    route_codes: tuple[str, ...]

    # -- Calibration -------------------------------------------------------
    confidence: float
    margin: float
    distribution: dict[str, float]

    # -- Grounded explanation ---------------------------------------------
    verification_passed: bool
    verification_attempts: int
    unsupported_numeric_claims: int
    cited_doc_ids: tuple[str, ...]
    retrieved_doc_ids: tuple[str, ...]
    wrong_account_citations: int
    post_cutoff_citations: int
    counterevidence_count: int
    driver_names: tuple[str, ...]
    truth_driver_names: tuple[str, ...]

    # -- Conflict and path -------------------------------------------------
    conflict_triggered: bool
    tot_ran: bool
    retrieval_retried: bool

    # -- Operational -------------------------------------------------------
    latency_ms: float
    node_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    model_calls: int
    errors: int

    @property
    def correct(self) -> bool | None:
        """Return whether the released label matched the realized outcome."""

        return None if self.outcome is None else self.outcome == self.label

    @property
    def citation_precision(self) -> float | None:
        """Return the share of cited documents that were actually retrieved."""

        if not self.cited_doc_ids:
            return None
        retrieved = set(self.retrieved_doc_ids)
        hits = sum(1 for doc in self.cited_doc_ids if doc in retrieved)
        return hits / len(self.cited_doc_ids)

    @property
    def driver_overlap(self) -> float | None:
        """Return the overlap between named drivers and ground-truth drivers."""

        if not self.truth_driver_names:
            return None
        truth = {DRIVER_ALIASES.get(name, name) for name in self.truth_driver_names}
        if not self.driver_names:
            return 0.0
        hits = sum(1 for name in self.driver_names if name in truth)
        return hits / len(self.driver_names)

    @property
    def total_tokens(self) -> int:
        """Return the tokens this run billed."""

        return self.prompt_tokens + self.completion_tokens

    @property
    def path(self) -> str:
        """Return which adjudication path this run took."""

        if self.blocked:
            return "blocked"
        if self.abstained:
            return "abstained"
        return "tree_of_thought" if self.tot_ran else "fast"

    def as_row(self) -> dict[str, Any]:
        """Return a flat CSV row."""

        return {
            "account_id": self.account_id,
            "label": self.label,
            "segment": self.segment,
            "region": self.region,
            "released": self.released,
            "abstained": self.abstained,
            "blocked": self.blocked,
            "outcome": self.outcome,
            "correct": self.correct,
            "route": self.route,
            "route_codes": ";".join(self.route_codes),
            "confidence": round(self.confidence, 6),
            "margin": round(self.margin, 6),
            "path": self.path,
            "verification_passed": self.verification_passed,
            "verification_attempts": self.verification_attempts,
            "unsupported_numeric_claims": self.unsupported_numeric_claims,
            "cited_documents": len(self.cited_doc_ids),
            "citation_precision": self.citation_precision,
            "wrong_account_citations": self.wrong_account_citations,
            "post_cutoff_citations": self.post_cutoff_citations,
            "counterevidence": self.counterevidence_count,
            "driver_overlap": self.driver_overlap,
            "conflict_triggered": self.conflict_triggered,
            "tot_ran": self.tot_ran,
            "retrieval_retried": self.retrieval_retried,
            "latency_ms": round(self.latency_ms, 1),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "model_calls": self.model_calls,
            "errors": self.errors,
        }


@dataclass
class RunCollection:
    """Every run in one pass, with the split it came from."""

    runs: list[SystemRun] = field(default_factory=list)
    split: str = "development"
    #: The provider model these runs used, for the cost estimate ER-006 asks
    #: for. Empty when none was configured, which is the offline default.
    model_name: str = ""

    def frame(self) -> pd.DataFrame:
        """Return every run as a row."""

        return pd.DataFrame([run.as_row() for run in self.runs])

    @property
    def released(self) -> list[SystemRun]:
        """Return only the runs that released a categorical outcome."""

        return [run for run in self.runs if run.released]


def truth_driver_names(
    evaluation: EvaluationRepository,
) -> dict[str, tuple[str, ...]]:
    """Return each account's ground-truth driver names.

    The archive stores positive and negative drivers separately, each as a list
    of `{driver, contribution}` records. Section 22.2 asks for driver-attribution
    overlap, which is about *which* features the answer named, so the two lists
    are merged and the contributions dropped.
    """

    frame = evaluation.ground_truth_drivers()
    names: dict[str, tuple[str, ...]] = {}
    for record in frame.to_dict("records"):
        account_id = str(record["account_id"])
        found: list[str] = []
        for column in ("top_negative_drivers", "top_positive_drivers"):
            for entry in record.get(column) or ():
                if isinstance(entry, dict) and "driver" in entry:
                    found.append(DRIVER_ALIASES.get(str(entry["driver"]), str(entry["driver"])))
        names[account_id] = tuple(dict.fromkeys(found))
    return names


def _routing_codes(run: AssessmentRun) -> tuple[str, ...]:
    """Return the routing rule codes, without the band prefix."""

    routing = run.guardrail("routing")
    if routing is None:
        return ()
    return tuple(rule for rule in routing.rule_ids if not rule.startswith("ROUTE-"))


def _verification(run: AssessmentRun) -> tuple[bool, int, int]:
    """Return whether output verification passed, its attempts, and its misses.

    Read from the trace rather than from the decision: the decision carries the
    narrative that survived, and what this needs to know is whether anything had
    to be replaced to get there.
    """

    events = run.events("output_verified")
    if not events:
        return True, 0, 0
    last = events[-1]
    passed = bool(last.payload.get("passed", False))
    attempts = int(str(last.payload.get("attempts") or 1))
    failures = last.payload.get("failures")
    unsupported = 0
    if isinstance(failures, list):
        unsupported = sum(1 for failure in failures if "numbers that are not in" in str(failure))
    return passed, attempts, unsupported


def collect_runs(
    runtime: GraphRuntime,
    evaluation: EvaluationRepository,
    account_ids: Sequence[str],
    split: str = "development",
    on_progress: Callable[[int, int, str], None] | None = None,
) -> RunCollection:
    """Run every account once and record what the five dimensions measure.

    Args:
        runtime: The assembled graph runtime. Offline unless a provider is set.
        evaluation: The label and ground-truth-driver source.
        account_ids: The accounts to run.
        split: Which split these accounts came from, recorded in the result.
        on_progress: Called with `(done, total, account_id)` after each run.

    Returns:
        Every run, ready for the dimension modules to compute from.
    """

    graph = build_graph(runtime)
    labels = evaluation.labels()
    truth_drivers = truth_driver_names(evaluation)
    collection = RunCollection(
        split=split,
        model_name=runtime.generator.model_name if runtime.generator is not None else "",
    )
    total = len(account_ids)

    for index, account_id in enumerate(account_ids, start=1):
        if account_id not in labels.index:
            continue
        profile = runtime.repository.profile(account_id)
        started = time.perf_counter()
        run = run_assessment(
            graph,
            AssessmentRequest(account_id=account_id, question=EVALUATION_QUESTION, mode="backtest"),
            run_id=f"EVAL-{account_id}",
        )
        elapsed = (time.perf_counter() - started) * 1000

        forecast = run.result if isinstance(run.result, ForecastDecision) else None
        abstention = run.result if isinstance(run.result, InsufficientEvidenceDecision) else None
        citations = (
            forecast.citations + forecast.counterevidence
            if forecast
            else (abstention.citations if abstention else ())
        )
        cutoff = run.result.cutoff if run.result else profile.effective_cutoff
        passed, attempts, unsupported = _verification(run)

        truth: tuple[str, ...] = truth_drivers.get(account_id, ())

        collection.runs.append(
            SystemRun(
                account_id=account_id,
                label=str(labels.loc[account_id]),
                segment=profile.segment,
                region=profile.region,
                released=forecast is not None,
                abstained=run.abstained,
                blocked=run.blocked is not None,
                outcome=forecast.outcome if forecast else None,
                route=str(run.route),
                route_codes=_routing_codes(run),
                confidence=forecast.confidence if forecast else 0.0,
                margin=top_two_margin(forecast.distribution) if forecast else 0.0,
                distribution=dict(forecast.distribution) if forecast else {},
                verification_passed=passed,
                verification_attempts=attempts,
                unsupported_numeric_claims=unsupported,
                cited_doc_ids=tuple(forecast.cited_doc_ids) if forecast else (),
                retrieved_doc_ids=tuple(citation.doc_id for citation in citations),
                wrong_account_citations=sum(
                    1
                    for citation in citations
                    if citation.account_id is not None and citation.account_id != account_id
                ),
                post_cutoff_citations=sum(
                    1
                    for citation in citations
                    if citation.doc_date is not None and citation.doc_date > cutoff
                ),
                counterevidence_count=len(forecast.counterevidence) if forecast else 0,
                driver_names=tuple(driver.feature for driver in forecast.drivers)
                if forecast
                else (),
                truth_driver_names=truth,
                conflict_triggered=bool(run.events("conflict_detected")),
                tot_ran=bool(run.events("tot_started")),
                retrieval_retried=bool(run.events("retrieval_retried")),
                latency_ms=elapsed,
                node_latency_ms=sum(event.latency_ms for event in run.trace),
                prompt_tokens=sum(event.prompt_tokens for event in run.trace),
                completion_tokens=sum(event.completion_tokens for event in run.trace),
                model_calls=run.model_calls,
                errors=len(run.errors),
            )
        )
        if on_progress is not None:
            on_progress(index, total, account_id)

    return collection


__all__ = [
    "DRIVER_ALIASES",
    "EVALUATION_QUESTION",
    "RunCollection",
    "SystemRun",
    "collect_runs",
    "truth_driver_names",
]
