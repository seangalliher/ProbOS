"""AD-1171: the flight recorder can be read.

Every agentic run has persisted a complete tool trace since AD-1151. Nothing
ever read one back. Reading a single trace by hand gave the root cause of BF-701
in about thirty seconds, after three sessions of inference from the agent's own
prose — so the fixture below is that real trace, trimmed.
"""

from __future__ import annotations

import json

import pytest

from probos.cognitive.trace_analysis import (
    REPEAT_THRESHOLD,
    TraceSummary,
    analyse_trace,
    load_trace,
    summarise_trace_ref,
)


def _entry(name: str, args: dict, output: str = "", is_error: bool | None = None):
    entry: dict = {
        "name": name, "arguments": args, "id": f"c{abs(hash(str(args))) % 9999}",
        "timestamp": 1.0,
    }
    if is_error is not None:
        entry["output"] = output
        entry["is_error"] = is_error
        entry["output_chars"] = len(output)
        entry["output_truncated"] = False
    return entry


# The real BF-701 run, trimmed to its shape: reach the target, be refused the
# verb for using it, then flail.
_BF701_TRACE = [
    _entry("browser", {"action": "state"}, "{'elements': [...]}", False),
    _entry("browser", {"action": "click", "index": 90}, "{'url': '...'}", False),
    _entry("browser", {"action": "key_type", "text": "Hello"},
           "unknown browser action: 'key_type'", True),
    _entry("browser", {"action": "type", "text": "Hello"},
           "click/type requires 'index' or 'selector'", True),
    _entry("browser", {"action": "click", "selector": "canvas"},
           "Page.click: Timeout 30000ms exceeded.", True),
    _entry("browser", {"action": "key_type", "text": "Hello", "delay_ms": 80},
           "unknown browser action: 'key_type'", True),
]


# ── the headline ──────────────────────────────────────────────────


def test_the_real_bf701_trace_names_its_own_root_cause() -> None:
    """THE AD-1171 regression.

    The agent said "the document is canvas-based". The trace says the browser
    tool refused `key_type` twice. The trace is right.
    """
    summary = analyse_trace(_BF701_TRACE)

    primary = summary.primary_failure
    assert primary is not None
    assert primary.tool_id == "browser"
    assert "key_type" in primary.error_text
    assert primary.count == 2
    assert primary.first_index == 2
    assert primary.last_index == 5


def test_the_summary_reads_as_a_finding_not_statistics() -> None:
    rendered = analyse_trace(_BF701_TRACE).render()
    assert "browser" in rendered
    assert "key_type" in rendered
    assert "2 times" in rendered
    # The finding leads; the counts follow.
    assert rendered.index("key_type") < rendered.index("tool calls")


def test_it_finds_where_progress_stopped() -> None:
    """Everything after the last success is an agent working around something
    rather than with it."""
    summary = analyse_trace(_BF701_TRACE)
    assert summary.last_success_index == 1
    assert summary.trailing_failure_count == 4
    assert summary.stalled is True


def test_counts_and_tools() -> None:
    summary = analyse_trace(_BF701_TRACE)
    assert summary.total_calls == 6
    assert summary.failed_calls == 4
    assert summary.tools_used == ("browser",)


# ── what must NOT be called a pattern ─────────────────────────────


def test_a_single_failure_is_not_a_repeat() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "ok", False),
        _entry("browser", {"a": 2}, "Timeout 30000ms exceeded", True),
    ])
    assert summary.repeated_failures == ()
    assert summary.primary_failure is None
    assert summary.failed_calls == 1


def test_two_different_errors_are_not_one_pattern() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "unknown action: 'a'", True),
        _entry("browser", {"a": 2}, "unknown action: 'b'", True),
    ])
    assert summary.repeated_failures == ()


def test_the_same_error_from_two_tools_is_not_one_pattern() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "denied", True),
        _entry("run_python", {"a": 2}, "denied", True),
    ])
    assert summary.repeated_failures == ()


def test_a_varying_duration_still_reads_as_one_pattern() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "Timeout 30000ms exceeded", True),
        _entry("browser", {"a": 2}, "Timeout 45000ms exceeded", True),
    ])
    assert summary.primary_failure is not None
    assert summary.primary_failure.count == 2


def test_a_successful_run_is_not_stalled() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "ok", False),
        _entry("browser", {"a": 2}, "ok", False),
    ])
    assert summary.stalled is False
    assert summary.failed_calls == 0
    assert summary.last_success_index == 1


def test_an_unrecorded_outcome_is_neither_success_nor_failure() -> None:
    """AD-1151 readers version by key presence. A call with no `is_error`
    predates output persistence or had no matching result."""
    summary = analyse_trace([
        _entry("browser", {"a": 1}),  # no is_error key
        _entry("browser", {"a": 2}, "boom", True),
    ])
    assert summary.failed_calls == 1
    assert summary.last_success_index == -1
    assert summary.total_calls == 2


def test_the_most_repeated_failure_is_primary() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "'rare'", True),
        _entry("browser", {"a": 2}, "'rare'", True),
        _entry("browser", {"a": 3}, "'common'", True),
        _entry("browser", {"a": 4}, "'common'", True),
        _entry("browser", {"a": 5}, "'common'", True),
    ])
    assert summary.primary_failure is not None
    assert "common" in summary.primary_failure.error_text
    assert len(summary.repeated_failures) == 2


def test_the_threshold_matches_its_siblings() -> None:
    """AD-1168 and AD-1170 use the same rule; drift would be confusing."""
    from probos.cognitive.continue_or_ask import _DEFECT_MIN_OCCURRENCES
    from probos.tools.failure_telemetry import DEFAULT_PATTERN_THRESHOLD

    assert REPEAT_THRESHOLD == _DEFECT_MIN_OCCURRENCES == DEFAULT_PATTERN_THRESHOLD


# ── never raises ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [None, "", 42, {}, [], [None, 1, "x"], [{"no": "keys"}]],
    ids=["none", "empty-str", "int", "dict", "empty-list", "junk", "keyless"],
)
def test_a_malformed_trace_yields_an_empty_or_safe_summary(bad) -> None:
    summary = analyse_trace(bad)
    assert isinstance(summary, TraceSummary)
    assert summary.repeated_failures == ()


def test_an_empty_trace_renders_honestly() -> None:
    assert "No tool calls" in analyse_trace([]).render()


# ── the loader ────────────────────────────────────────────────────


class _Store:
    def __init__(self, blob) -> None:
        self.blob = blob
        self.asked: list[str] = []

    async def read(self, ref):
        self.asked.append(ref)
        if isinstance(self.blob, Exception):
            raise self.blob
        return self.blob


async def test_a_persisted_trace_round_trips() -> None:
    store = _Store(json.dumps(_BF701_TRACE).encode("utf-8"))
    summary = await summarise_trace_ref(store, "sha-1")
    assert summary is not None
    assert summary.primary_failure is not None
    assert "key_type" in summary.primary_failure.error_text
    assert store.asked == ["sha-1"]


async def test_a_missing_store_degrades_to_none() -> None:
    assert await load_trace(None, "sha-1") is None
    assert await summarise_trace_ref(None, "sha-1") is None


async def test_an_empty_ref_degrades_to_none() -> None:
    assert await load_trace(_Store(b"[]"), "") is None


async def test_a_raising_store_degrades_to_none() -> None:
    assert await load_trace(_Store(RuntimeError("gone")), "sha-1") is None


async def test_undecodable_bytes_degrade_to_none() -> None:
    assert await load_trace(_Store(b"not json at all"), "sha-1") is None


async def test_a_non_list_payload_degrades_to_none() -> None:
    assert await load_trace(_Store(b'{"not": "a list"}'), "sha-1") is None


async def test_a_string_blob_is_accepted() -> None:
    """Some stores hand back str rather than bytes."""
    assert await load_trace(_Store('[{"name": "browser"}]'), "sha-1") == [
        {"name": "browser"}
    ]
