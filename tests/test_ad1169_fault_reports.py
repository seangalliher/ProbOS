"""AD-1169 + AD-1170: the crew can report a broken tool.

The system could already say "I need a capability I don't have". It could not
say "what I have is broken", so a stalled turn had exactly one verdict
available: *I need more room to keep trying*.

BF-701 is the case these tests are built from. The agent asked the browser tool
for ``key_type`` at step 2, was told ``unknown browser action: 'key_type'``,
asked again at step 15, got the identical answer, and filed a continue request
— because that was the only thing it could file. The diagnosis was in its own
results the whole time.
"""

from __future__ import annotations

import pytest

from probos.cognitive.continue_or_ask import (
    _DEFECT_MIN_OCCURRENCES,
    detect_tool_defect,
    file_fault_from_turn,
)
from probos.fault_report import (
    FaultReport,
    FaultReportStore,
    error_signature,
    normalise_error,
)


# ── fakes shaped like the real loop output ────────────────────────


class _Call:
    def __init__(self, call_id: str, name: str) -> None:
        self.id = call_id
        self.name = name


class _Result:
    def __init__(self, call_id: str, output: str, is_error: bool) -> None:
        self.id = call_id
        self.output = output
        self.is_error = is_error


class _Outcome:
    def __init__(self, calls, results) -> None:
        self.tool_calls = calls
        self.tool_results = results
        self.final_text = ""
        self.stopped_reason = "max_iterations"


def _bf701_outcome() -> _Outcome:
    """The real BF-701 shape: the same refusal twice, workarounds between."""
    return _Outcome(
        calls=[
            _Call("c0", "browser"),
            _Call("c1", "browser"),
            _Call("c2", "browser"),
            _Call("c3", "browser"),
        ],
        results=[
            _Result("c0", "{'elements': [...]}", False),
            _Result("c1", "unknown browser action: 'key_type'", True),
            _Result("c2", "Page.click: Timeout 30000ms exceeded.", True),
            _Result("c3", "unknown browser action: 'key_type'", True),
        ],
    )


# ── AD-1169: the signature ────────────────────────────────────────


def test_the_same_fault_normalises_to_one_signature() -> None:
    a = error_signature(tool_id="browser", error_text="unknown browser action: 'key_type'")
    b = error_signature(tool_id="browser", error_text="unknown browser action: 'key_type'")
    assert a == b


def test_a_varying_duration_does_not_split_a_fault() -> None:
    """`Timeout 30000ms` and `Timeout 45000ms` are the same fault."""
    a = error_signature(tool_id="browser", error_text="Page.click: Timeout 30000ms exceeded.")
    b = error_signature(tool_id="browser", error_text="Page.click: Timeout 45000ms exceeded.")
    assert a == b


def test_a_varying_session_id_does_not_split_a_fault() -> None:
    a = error_signature(tool_id="browser", error_text="session b32d9eb147cd42da failed")
    b = error_signature(tool_id="browser", error_text="session 97618a3f0a014ee8 failed")
    assert a == b


def test_the_quoted_action_name_IS_the_signal() -> None:
    """`key_type` and `key_combo` are different faults and must not merge."""
    a = error_signature(tool_id="browser", error_text="unknown browser action: 'key_type'")
    b = error_signature(tool_id="browser", error_text="unknown browser action: 'key_combo'")
    assert a != b


def test_the_same_error_from_different_tools_is_different() -> None:
    a = error_signature(tool_id="browser", error_text="not permitted")
    b = error_signature(tool_id="run_python", error_text="not permitted")
    assert a != b


def test_normalise_is_bounded_and_never_raises() -> None:
    assert normalise_error(None) == ""
    assert normalise_error(object()) != ""
    assert len(normalise_error("x" * 9000)) <= 2000


# ── AD-1169: the store ────────────────────────────────────────────


async def test_a_fault_is_filed_and_readable() -> None:
    store = FaultReportStore()
    report = await store.file_fault(
        tool_id="browser",
        error_text="unknown browser action: 'key_type'",
        attempted="type Hello into the document",
        agent_id="counselor-ezri",
        thread_id="thread-1",
    )
    assert isinstance(report, FaultReport)
    assert report.status == "open"
    assert report.occurrences == 1
    assert store.list_open() == [report]
    assert store.get(report.id) is report


async def test_the_same_fault_coalesces_rather_than_piling_up() -> None:
    """An agent that retries five times files ONE fault. This is what makes
    filing safe without a Captain round-trip."""
    store = FaultReportStore()
    for _ in range(5):
        await store.file_fault(
            tool_id="browser", error_text="unknown browser action: 'key_type'",
        )
    open_faults = store.list_open()
    assert len(open_faults) == 1
    assert open_faults[0].occurrences == 5


async def test_different_faults_stay_separate() -> None:
    store = FaultReportStore()
    await store.file_fault(tool_id="browser", error_text="unknown action: 'a'")
    await store.file_fault(tool_id="browser", error_text="unknown action: 'b'")
    assert len(store.list_open()) == 2


async def test_a_repaired_fault_that_recurs_is_a_new_fault() -> None:
    """Silently incrementing the old row would hide a failed repair."""
    store = FaultReportStore()
    first = await store.file_fault(tool_id="browser", error_text="boom")
    await store.resolve(first.id, status="repaired", resolution="BF-701")
    second = await store.file_fault(tool_id="browser", error_text="boom")

    assert second.id != first.id
    assert second.occurrences == 1
    assert first.status == "repaired"


async def test_resolve_returns_none_for_an_unknown_fault() -> None:
    store = FaultReportStore()
    assert await store.resolve("nope", status="repaired") is None


async def test_get_by_tool_filters() -> None:
    store = FaultReportStore()
    await store.file_fault(tool_id="browser", error_text="a")
    await store.file_fault(tool_id="run_python", error_text="b")
    assert len(store.get_by_tool("browser")) == 1


async def test_real_db_roundtrip_reloads_every_field(tmp_path) -> None:
    """House rule: a cache-only store test cannot exercise the column mapping.

    `db_path=""` no-ops every DB branch, so `_row_to_report` and the INSERT
    column alignment would never run. This is the only test that proves them.
    """
    db = str(tmp_path / "faults.db")
    store = FaultReportStore(db_path=db)
    await store.start()
    filed = await store.file_fault(
        tool_id="browser",
        error_text="unknown browser action: 'key_type'",
        attempted="type Hello",
        agent_id="ezri",
        thread_id="thread-1",
        work_item_id="wi-1",
        tool_trace_ref="sha-1",
    )
    await store.file_fault(
        tool_id="browser", error_text="unknown browser action: 'key_type'",
    )
    await store.stop()

    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        loaded = reopened.get(filed.id)
        assert loaded is not None
        assert loaded.tool_id == "browser"
        assert loaded.attempted == "type Hello"
        assert loaded.agent_id == "ezri"
        assert loaded.thread_id == "thread-1"
        assert loaded.work_item_id == "wi-1"
        assert loaded.tool_trace_ref == "sha-1"
        assert loaded.status == "open"
        assert loaded.occurrences == 2, "the second occurrence did not persist"
        assert loaded.first_seen_at > 0
        assert loaded.last_seen_at >= loaded.first_seen_at
    finally:
        await reopened.stop()


async def test_a_resolution_survives_a_restart(tmp_path) -> None:
    db = str(tmp_path / "faults.db")
    store = FaultReportStore(db_path=db)
    await store.start()
    filed = await store.file_fault(tool_id="browser", error_text="boom")
    await store.resolve(filed.id, status="repaired", resolution="fixed in BF-701")
    await store.stop()

    reopened = FaultReportStore(db_path=db)
    await reopened.start()
    try:
        loaded = reopened.get(filed.id)
        assert loaded is not None
        assert loaded.status == "repaired"
        assert loaded.resolution == "fixed in BF-701"
        assert loaded.resolved_at is not None
        assert reopened.list_open() == []
    finally:
        await reopened.stop()


async def test_a_broken_emit_does_not_break_filing() -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("event bus down")

    store = FaultReportStore(emit_event=_boom)
    report = await store.file_fault(tool_id="browser", error_text="x")
    assert report.status == "open"


# ── AD-1170: the detector ─────────────────────────────────────────


def test_a_repeated_tool_failure_is_detected() -> None:
    """THE AD-1170 regression, on the real BF-701 shape."""
    found = detect_tool_defect(_bf701_outcome())
    assert found is not None
    tool_id, error_text, count = found
    assert tool_id == "browser"
    assert "key_type" in error_text
    assert count == 2


def test_a_single_failure_is_not_a_defect() -> None:
    """Once is a transient -- a timeout, a race, a page that had not settled.
    Retrying is the correct response, so this must NOT divert."""
    outcome = _Outcome(
        calls=[_Call("c0", "browser")],
        results=[_Result("c0", "Timeout 30000ms exceeded", True)],
    )
    assert detect_tool_defect(outcome) is None


def test_successes_are_not_counted() -> None:
    outcome = _Outcome(
        calls=[_Call("c0", "browser"), _Call("c1", "browser")],
        results=[
            _Result("c0", "fine", False),
            _Result("c1", "fine", False),
        ],
    )
    assert detect_tool_defect(outcome) is None


def test_two_different_errors_are_not_one_defect() -> None:
    outcome = _Outcome(
        calls=[_Call("c0", "browser"), _Call("c1", "browser")],
        results=[
            _Result("c0", "unknown action: 'a'", True),
            _Result("c1", "unknown action: 'b'", True),
        ],
    )
    assert detect_tool_defect(outcome) is None


def test_the_same_error_from_two_tools_is_not_one_defect() -> None:
    outcome = _Outcome(
        calls=[_Call("c0", "browser"), _Call("c1", "run_python")],
        results=[
            _Result("c0", "denied", True),
            _Result("c1", "denied", True),
        ],
    )
    assert detect_tool_defect(outcome) is None


def test_the_most_repeated_failure_wins() -> None:
    outcome = _Outcome(
        calls=[_Call(f"c{i}", "browser") for i in range(5)],
        results=[
            _Result("c0", "rare failure", True),
            _Result("c1", "rare failure", True),
            _Result("c2", "common failure", True),
            _Result("c3", "common failure", True),
            _Result("c4", "common failure", True),
        ],
    )
    found = detect_tool_defect(outcome)
    assert found is not None
    assert found[1] == "common failure"
    assert found[2] == 3


@pytest.mark.parametrize(
    "outcome",
    [None, object(), _Outcome([], []), _Outcome(None, None)],
    ids=["none", "bare-object", "empty-lists", "none-lists"],
)
def test_a_malformed_outcome_yields_no_defect(outcome) -> None:
    """Detection must never raise -- the turn falls back to today's path."""
    assert detect_tool_defect(outcome) is None


def test_the_threshold_is_two() -> None:
    assert _DEFECT_MIN_OCCURRENCES == 2


# ── AD-1170: filing from a turn ───────────────────────────────────


class _Runtime:
    def __init__(self, store=None) -> None:
        self.fault_report_store = store


async def test_a_defect_from_a_turn_reaches_the_store() -> None:
    store = FaultReportStore()
    fault_id = await file_fault_from_turn(
        _Runtime(store),
        agent_id="ezri",
        thread_id="thread-1",
        tool_id="browser",
        error_text="unknown browser action: 'key_type'",
        attempted="type Hello into the document",
    )
    assert fault_id
    open_faults = store.list_open()
    assert len(open_faults) == 1
    assert open_faults[0].tool_id == "browser"
    assert open_faults[0].agent_id == "ezri"
    assert open_faults[0].attempted == "type Hello into the document"


async def test_no_store_degrades_to_empty_string() -> None:
    assert await file_fault_from_turn(
        _Runtime(None),
        agent_id="ezri", thread_id="t", tool_id="browser",
        error_text="x", attempted="y",
    ) == ""


async def test_a_raising_store_does_not_break_the_turn() -> None:
    class _Broken:
        async def file_fault(self, **_kwargs):
            raise RuntimeError("db gone")

    assert await file_fault_from_turn(
        _Runtime(_Broken()),
        agent_id="ezri", thread_id="t", tool_id="browser",
        error_text="x", attempted="y",
    ) == ""
