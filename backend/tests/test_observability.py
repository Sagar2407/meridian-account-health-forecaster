"""Trace sinks, cost estimation, and optional LangSmith (plan section 21).

Section 21.2's requirement is the one worth testing hardest: "the application
must remain fully functional when LangSmith is disabled". Several tests below
are therefore about what happens when the optional path is missing or broken.
"""

import json
from pathlib import Path

import pytest

from meridian.contracts import TraceEvent
from meridian.graph.observability import (
    TOKEN_PRICES,
    FanOutTraceSink,
    JsonlTraceSink,
    MemoryTraceSink,
    build_sink,
    estimate_cost,
    langsmith_is_enabled,
    run_summary,
)


def _event(sequence: int = 1, prompt: int = 0, completion: int = 0) -> TraceEvent:
    """Return one safe trace event."""

    return TraceEvent(
        run_id="RUN-1",
        thread_id="RUN-1",
        sequence=sequence,
        timestamp="2026-09-01T10:00:00.000Z",
        node="plan_sub_goals",
        event="plan_created",
        payload={"sub_goals": ["adoption", "support"], "source": "deterministic"},
        latency_ms=12.5,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


class _ExplodingSink:
    """A sink that always fails, standing in for an outage."""

    def __init__(self) -> None:
        self.attempts = 0

    def write(self, event: TraceEvent) -> None:
        """Fail, every time."""

        self.attempts += 1
        raise RuntimeError("the collector is unreachable")

    def close(self) -> None:
        """Fail on the way out too."""

        raise RuntimeError("still unreachable")


class TestJsonlSink:
    def test_each_event_lands_as_one_parseable_line(self, tmp_path: Path) -> None:
        """A trace is read line by line; one bad line must not lose the rest."""

        sink = JsonlTraceSink(path=tmp_path / "runs.jsonl")
        sink.write(_event(1))
        sink.write(_event(2))
        sink.close()

        lines = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert [json.loads(line)["sequence"] for line in lines] == [1, 2]

    def test_events_are_appended_as_they_happen(self, tmp_path: Path) -> None:
        """A trace written only at the end is missing for the runs worth reading.

        The runs worth investigating are the ones that crashed, and those never
        reach an end-of-run flush.
        """

        target = tmp_path / "runs.jsonl"
        sink = JsonlTraceSink(path=target)
        sink.write(_event(1))

        assert target.is_file()
        assert len(target.read_text(encoding="utf-8").splitlines()) == 1

    def test_the_written_line_carries_no_prompt(self, tmp_path: Path) -> None:
        """Section 21.3, checked where the trace actually reaches disk."""

        sink = JsonlTraceSink(path=tmp_path / "runs.jsonl")
        sink.write(_event())

        body = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").lower()
        for key in ("prompt", "chain_of_thought", "messages", "api_key"):
            assert f'"{key}"' not in body


class TestFanOut:
    def test_one_failing_sink_does_not_stop_the_others(self, tmp_path: Path) -> None:
        """A LangSmith outage must not take the mandatory local trace with it."""

        good = MemoryTraceSink()
        bad = _ExplodingSink()
        fan = FanOutTraceSink(sinks=[bad, good])

        fan.write(_event(1))
        fan.write(_event(2))

        assert [event.sequence for event in good.events] == [1, 2]
        # The broken sink is dropped rather than retried on every event.
        assert bad.attempts == 1
        assert "_ExplodingSink" in fan.failures
        assert "unreachable" in fan.failures["_ExplodingSink"]

    def test_closing_survives_a_sink_that_fails_on_the_way_out(self) -> None:
        """A completed run must not become an exception at teardown."""

        fan = FanOutTraceSink(sinks=[_ExplodingSink()])
        fan.close()


class TestCostEstimate:
    @pytest.mark.parametrize("model", sorted(TOKEN_PRICES))
    def test_a_known_model_produces_a_positive_estimate(self, model: str) -> None:
        """Every priced family has to actually price."""

        cost = estimate_cost(model, prompt_tokens=1_000_000, completion_tokens=0)
        assert cost is not None and cost > 0

    def test_an_unknown_model_returns_none_rather_than_zero(self) -> None:
        """A fabricated zero would sum into a total as though it were free."""

        assert estimate_cost("some/unlisted-model", 1_000, 1_000) is None

    def test_a_run_that_spent_nothing_costs_nothing(self) -> None:
        """The offline path is free, and should say so rather than 'unknown'."""

        assert estimate_cost("anthropic/claude-sonnet-4.5", 0, 0) == 0.0

    def test_the_estimate_scales_with_both_token_kinds(self) -> None:
        """Completion tokens cost more than prompt tokens on every listed model."""

        prompt_only = estimate_cost("anthropic/claude-sonnet-4.5", 1_000_000, 0)
        completion_only = estimate_cost("anthropic/claude-sonnet-4.5", 0, 1_000_000)
        assert prompt_only is not None and completion_only is not None
        assert completion_only > prompt_only


class TestLangSmith:
    def test_it_is_off_unless_explicitly_asked_for(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Section 21.2 makes mirroring opt-in."""

        monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
        assert langsmith_is_enabled() is False

        monkeypatch.setenv("LANGSMITH_TRACING", "false")
        assert langsmith_is_enabled() is False

        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        assert langsmith_is_enabled() is True

    def test_the_local_trace_is_written_whether_or_not_mirroring_is_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local tracing is mandatory (21.1); mirroring is optional (21.2)."""

        monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
        target = tmp_path / "runs.jsonl"
        with build_sink(path=target) as sink:
            sink.write(_event())
        assert target.read_text(encoding="utf-8").count("\n") == 1

    def test_a_broken_mirror_is_recorded_and_does_not_break_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asking for LangSmith without a working client must still trace locally."""

        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGSMITH_API_KEY", "")
        target = tmp_path / "runs.jsonl"

        with build_sink(path=target) as sink:
            sink.write(_event())

        assert target.is_file()
        assert len(target.read_text(encoding="utf-8").splitlines()) == 1


class TestRunSummary:
    def test_it_carries_what_section_21_1_lists(self) -> None:
        """Run ids, route, disposition, latency, tokens, cost, and rule ids."""

        summary = run_summary(
            run_id="RUN-1",
            thread_id="RUN-1",
            account_id="ACC-1042",
            disposition="released",
            route="amber",
            events=(_event(1, prompt=500, completion=200),),
            model="anthropic/claude-sonnet-4.5",
            guardrail_rule_ids=("ROUTE-AMBER", "confidence_below_green"),
            confidence_breakdown={"confidence": 0.78},
        )

        assert summary["account_id"] == "ACC-1042"
        assert summary["route"] == "amber"
        assert summary["disposition"] == "released"
        assert summary["prompt_tokens"] == 500
        assert summary["completion_tokens"] == 200
        assert summary["estimated_cost_usd"] is not None
        assert "estimate" in summary["estimated_cost_note"]
        assert summary["guardrail_rule_ids"] == ["ROUTE-AMBER", "confidence_below_green"]
        assert summary["confidence_breakdown"] == {"confidence": 0.78}

    def test_an_unpriced_model_reports_an_unknown_cost(self) -> None:
        """Better a null a reader must interpret than a zero they will not."""

        summary = run_summary(
            run_id="RUN-1",
            thread_id="RUN-1",
            account_id="ACC-1042",
            disposition="released",
            route="green",
            events=(_event(1, prompt=100, completion=50),),
            model="private/in-house-model",
        )

        assert summary["estimated_cost_usd"] is None
