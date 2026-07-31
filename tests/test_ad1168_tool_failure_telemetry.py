"""AD-1168: per-tool failure telemetry.

`unknown browser action: 'key_type'` fired twice inside one turn and recurred
across four sessions. Nothing counted it, once.

The two aggregators that look like they should have caught it cannot:
`OperationalStatusTracker` keys on the AGENT, so a tool broken for everyone
reads as several agents having a bad day, and `FailureDistiller` clusters
episodes, which is a different altitude. Neither can answer "is this tool
behaving as advertised?" because neither is keyed on the tool.
"""

from __future__ import annotations

import pytest

from probos.events import EventType
from probos.tools.failure_telemetry import (
    DEFAULT_PATTERN_THRESHOLD,
    ToolFailureTelemetry,
    make_failure_telemetry_hook,
)
from probos.tools.protocol import ToolResult


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _telemetry(**kwargs):
    events: list[tuple] = []
    clock = _Clock()
    tel = ToolFailureTelemetry(
        emit_fn=lambda et, data: events.append((et, data)),
        clock=clock,
        **kwargs,
    )
    return tel, events, clock


# ── the headline ──────────────────────────────────────────────────


def test_a_repeated_failure_raises_a_pattern() -> None:
    """THE AD-1168 regression, on the error that went uncounted for a day."""
    tel, events, _ = _telemetry()
    err = "unknown browser action: 'key_type'"

    assert tel.record_failure(tool_id="browser", error_text=err) == 1
    assert events == [], "one failure is a transient, not a pattern"

    assert tel.record_failure(tool_id="browser", error_text=err) == 2
    assert len(events) == 1
    event_type, data = events[0]
    assert event_type is EventType.TOOL_FAILURE_PATTERN
    assert data["tool_id"] == "browser"
    assert data["occurrences"] == 2
    assert "key_type" in data["error"]


def test_a_forming_pattern_announces_once() -> None:
    """Ten failures raise one hand, not eight."""
    tel, events, _ = _telemetry()
    for _ in range(10):
        tel.record_failure(tool_id="browser", error_text="boom")
    assert len(events) == 1


def test_the_same_failure_from_different_agents_is_one_pattern() -> None:
    """This is the whole point: the signature is agent-independent, so a tool
    broken for everyone reads as one broken tool."""
    tel, events, _ = _telemetry()
    # Agent identity never enters record_failure; two callers, one signal.
    tel.record_failure(tool_id="browser", error_text="denied")
    tel.record_failure(tool_id="browser", error_text="denied")
    assert len(events) == 1
    assert events[0][1]["occurrences"] == 2


def test_different_tools_do_not_merge() -> None:
    tel, events, _ = _telemetry()
    tel.record_failure(tool_id="browser", error_text="denied")
    tel.record_failure(tool_id="run_python", error_text="denied")
    assert events == []


def test_different_errors_do_not_merge() -> None:
    tel, events, _ = _telemetry()
    tel.record_failure(tool_id="browser", error_text="unknown action: 'a'")
    tel.record_failure(tool_id="browser", error_text="unknown action: 'b'")
    assert events == []


def test_a_varying_duration_still_counts_as_one_pattern() -> None:
    """Two timeouts are the same fault even at different durations."""
    tel, events, _ = _telemetry()
    tel.record_failure(tool_id="browser", error_text="Timeout 30000ms exceeded")
    tel.record_failure(tool_id="browser", error_text="Timeout 45000ms exceeded")
    assert len(events) == 1


# ── the window ────────────────────────────────────────────────────


def test_failures_outside_the_window_stop_counting() -> None:
    """Twice in a week is not the signal that twice in a minute is."""
    tel, events, clock = _telemetry(window_seconds=100.0)
    tel.record_failure(tool_id="browser", error_text="boom")
    clock.advance(500.0)
    assert tel.record_failure(tool_id="browser", error_text="boom") == 1
    assert events == []


def test_a_zero_window_never_expires() -> None:
    tel, events, clock = _telemetry(window_seconds=0.0)
    tel.record_failure(tool_id="browser", error_text="boom")
    clock.advance(1_000_000.0)
    assert tel.record_failure(tool_id="browser", error_text="boom") == 2
    assert len(events) == 1


# ── bounds ────────────────────────────────────────────────────────


def test_distinct_signatures_are_bounded() -> None:
    """Error text is LLM- and attacker-influenced. A tool failing with a unique
    message every call must not grow this without limit."""
    tel, _, _ = _telemetry(max_signatures=8)
    for i in range(200):
        tel.record_failure(tool_id="browser", error_text=f"unique failure {i!r}")
    assert len(tel.snapshot()) <= 8


def test_eviction_is_least_recently_seen() -> None:
    tel, _, _ = _telemetry(max_signatures=2)
    tel.record_failure(tool_id="t", error_text="'oldest'")
    tel.record_failure(tool_id="t", error_text="'middle'")
    tel.record_failure(tool_id="t", error_text="'oldest'")  # refresh it
    tel.record_failure(tool_id="t", error_text="'newest'")  # evicts 'middle'
    tools = {row["occurrences"] for row in tel.snapshot()}
    assert len(tel.snapshot()) == 2
    assert 2 in tools, "the refreshed signature should have survived"


def test_snapshot_is_ordered_by_frequency() -> None:
    tel, _, _ = _telemetry()
    for _ in range(3):
        tel.record_failure(tool_id="browser", error_text="'common'")
    tel.record_failure(tool_id="browser", error_text="'rare'")
    rows = tel.snapshot()
    assert rows[0]["occurrences"] == 3
    assert rows[0]["announced"] is True
    assert rows[-1]["occurrences"] == 1


def test_count_for_reports_the_window_count() -> None:
    tel, _, _ = _telemetry()
    assert tel.count_for(tool_id="browser", error_text="x") == 0
    tel.record_failure(tool_id="browser", error_text="x")
    assert tel.count_for(tool_id="browser", error_text="x") == 1


def test_the_threshold_default_matches_the_defect_detector() -> None:
    """AD-1170 uses the same "twice is a pattern" rule. They must not drift."""
    from probos.cognitive.continue_or_ask import _DEFECT_MIN_OCCURRENCES

    assert DEFAULT_PATTERN_THRESHOLD == _DEFECT_MIN_OCCURRENCES


# ── the post-hook ─────────────────────────────────────────────────


def test_the_hook_records_only_failures() -> None:
    tel, events, _ = _telemetry()
    hook = make_failure_telemetry_hook(tel)
    ctx = {"tool_id": "browser", "agent_id": "ezri"}

    hook(ctx, ToolResult(output="fine"))
    hook(ctx, ToolResult(output="fine"))
    assert tel.snapshot() == [], "successes must not be counted"

    hook(ctx, ToolResult(error="unknown browser action: 'key_type'"))
    hook(ctx, ToolResult(error="unknown browser action: 'key_type'"))
    assert len(events) == 1


def test_the_hook_never_raises_into_the_caller() -> None:
    """It runs inline on every tool invocation. A fault here must degrade to
    "no telemetry", never to a failed tool call."""

    class _Exploding(ToolFailureTelemetry):
        def record_failure(self, **_kwargs) -> int:
            raise RuntimeError("counter exploded")

    hook = make_failure_telemetry_hook(_Exploding())
    hook({"tool_id": "browser"}, ToolResult(error="boom"))  # must not raise


@pytest.mark.parametrize(
    "ctx", [{}, {"tool_id": None}, {"tool_id": 42}], ids=["empty", "none", "int"],
)
def test_a_malformed_context_is_tolerated(ctx) -> None:
    tel, _, _ = _telemetry()
    hook = make_failure_telemetry_hook(tel)
    hook(ctx, ToolResult(error="boom"))


def test_a_broken_emit_does_not_break_recording() -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("bus down")

    tel = ToolFailureTelemetry(emit_fn=_boom)
    tel.record_failure(tool_id="browser", error_text="x")
    assert tel.record_failure(tool_id="browser", error_text="x") == 2


def test_the_event_type_exists_and_is_distinct() -> None:
    assert EventType.TOOL_FAILURE_PATTERN.value == "tool_failure_pattern"
    assert EventType.TOOL_FAILURE_PATTERN is not EventType.TOOL_INVOKED
