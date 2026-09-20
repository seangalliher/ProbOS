"""AD-1205: counting, retention, publication and cancellation contracts."""

from __future__ import annotations

import asyncio
import gc
import sqlite3
import weakref
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.fault_detection import (
    MAX_FAULT_CANDIDATES,
    FaultObservationResult,
    ToolFaultAdapterKind,
    ToolFaultBatch,
    ToolFaultCapture,
    ToolFaultEvidence,
    ToolFaultObserver,
    ToolFaultTurn,
    collect_tool_fault_batch,
    observe_completed_tool_run,
)
from probos.fault_report import FaultReport, FaultReportStore, ToolDefect, resolve_tool_defect
from probos.tools.executor import classify_tool_error
from probos.tools.protocol import ToolResult
from tests.test_ad1205_fault_paths import _owned_environment  # noqa: F401

ERROR = "fixture subsystem unavailable"


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


class _Publisher:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.error: Exception | None = None
        self.entered: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def __call__(self, **kwargs) -> FaultReport:
        self.calls.append(kwargs)
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return FaultReport(id=f"fault-{len(self.calls)}")


def _batch(tool: str = "fixture", error: str = ERROR, *, repeated: bool = False) -> ToolFaultBatch:
    defect = ToolDefect(tool_id=tool, error_text=error, count=2 if repeated else 1)
    return ToolFaultBatch(
        (ToolFaultEvidence(tool, defect),), defect if repeated else None,
    )


async def _observe(sink, batch=None, turn=None, **kwargs) -> FaultObservationResult:
    return await sink.observe_tool_run(
        turn=turn if turn is not None else ToolFaultTurn(),
        batch=batch if batch is not None else _batch(),
        agent_id=kwargs.pop("agent_id", "agent"),
        **kwargs,
    )


def _pairs(*errors: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        tool_calls=[
            ToolCallRequest(name="fixture", arguments={"not_retained": "secret"}, id=f"c{i}")
            for i in range(len(errors))
        ],
        tool_results=[
            ToolCallResult(id=f"c{i}", output=error or "", is_error=error is not None)
            for i, error in enumerate(errors)
        ],
    )


def _collect(outcome, **kwargs) -> ToolFaultBatch:
    return collect_tool_fault_batch(outcome, classify_error=classify_tool_error, **kwargs)


async def test_three_distinct_turns_publish_only_qualifying_context() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher, clock=_Clock())
    assert (await _observe(observer)).attempts == ()
    assert (await _observe(observer, agent_id="second")).attempts == ()
    result = await _observe(
        observer, agent_id="qualifier", thread_id="thread", attempted="raw ask",
        tool_trace_ref="actual-trace",
    )
    assert len(publisher.calls) == 1
    assert publisher.calls[0]["agent_id"] == "qualifier"
    assert publisher.calls[0]["attempted"] == "raw ask"
    assert publisher.calls[0]["tool_trace_ref"] == "actual-trace"
    assert result.fault_id(_batch().tools[0].defect.signature) == "fault-1"
    await _observe(observer)
    assert len(publisher.calls) == 2


async def test_repeated_passes_and_duplicate_callbacks_are_one_logical_turn() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    first = ToolFaultTurn()
    for _ in range(5):
        await _observe(observer, turn=first)
    await _observe(observer)
    assert publisher.calls == []
    third = ToolFaultTurn()
    result = await _observe(observer, turn=third)
    for _ in range(3):
        assert await _observe(observer, turn=third) == result
    assert len(publisher.calls) == 1


async def test_same_run_and_cross_turn_union_reserves_once() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer)
    await _observe(observer)
    turn = ToolFaultTurn()
    await _observe(observer, _batch(repeated=True), turn)
    await _observe(observer, _batch(repeated=True), turn)
    assert len(publisher.calls) == 1


@pytest.mark.parametrize("noise", [
    "permission denied", "not authorized", "forbidden", "operation cancelled",
    "Tool name is ambiguous and was not invoked", "invalid parameter",
    "missing required field", "pre-hook aborted",
])
async def test_policy_noise_is_not_a_cross_turn_vote(noise: str) -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    for _ in range(3):
        await _observe(observer, _collect(_pairs(noise)))
    assert publisher.calls == []
    # The old same-run threshold is intentionally not a new capability policy.
    legacy = _collect(_pairs(noise, noise))
    assert legacy.same_run is not None and legacy.same_run.count == 2


async def test_denied_aliases_never_contribute_false_success_or_failure() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    for _ in range(3):
        batch = _collect(
            _pairs(ERROR), denied_tools=("canonical",),
            resolve_tool_id=lambda name: "canonical",
        )
        assert batch.tools == ()
        await _observe(observer, batch)
    assert publisher.calls == []


@pytest.mark.parametrize("interruption", [
    (None,), (ERROR, "a different failure"), (None, ERROR),
])
async def test_success_or_mixed_batch_resets_pending_streak(interruption) -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer)
    await _observe(observer)
    await _observe(observer, _collect(_pairs(*interruption)))
    await _observe(observer)
    await _observe(observer)
    assert publisher.calls == []
    await _observe(observer)
    assert len(publisher.calls) == 1


async def test_success_with_repeated_failure_still_keeps_legacy_verdict() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    batch = _collect(_pairs(ERROR, None, ERROR))
    assert batch.tools[0].succeeded and batch.same_run.count == 2
    await _observe(observer, batch)
    assert len(publisher.calls) == 1


async def test_different_error_starts_fresh_and_other_tools_are_neutral() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer)
    await _observe(observer)
    await _observe(observer, _batch(error="new defect"))
    await _observe(observer, _batch(tool="other"))
    await _observe(observer, ToolFaultBatch())
    await _observe(observer, _batch(error="new defect"))
    assert publisher.calls == []
    await _observe(observer, _batch(error="new defect"))
    assert len(publisher.calls) == 1
    assert publisher.calls[0]["error_text"] == "new defect"


async def test_different_errors_or_success_across_passes_do_not_revote() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    turn = ToolFaultTurn()
    await _observe(observer)
    await _observe(observer, turn=turn)
    await _observe(observer, _batch(error="other"), turn)
    await _observe(observer, turn=turn)
    await _observe(observer)
    await _observe(observer)
    assert publisher.calls == []
    await _observe(observer)
    assert len(publisher.calls) == 1


@pytest.mark.parametrize(("elapsed", "reports"), [(3599.999, 1), (3600.0, 0), (3600.001, 0)])
async def test_rolling_window_expires_at_exact_boundary(elapsed: float, reports: int) -> None:
    publisher, clock = _Publisher(), _Clock()
    observer = ToolFaultObserver(publish=publisher, clock=clock)
    await _observe(observer)
    clock.now = 1800.0
    await _observe(observer)
    clock.now = elapsed
    await _observe(observer)
    assert len(publisher.calls) == reports


async def test_empty_batch_expires_candidates_without_refreshing_a_turn() -> None:
    publisher, clock = _Publisher(), _Clock()
    observer = ToolFaultObserver(publish=publisher, clock=clock)
    turn = ToolFaultTurn()
    await _observe(observer, turn=turn)
    clock.now = 3600.0
    await _observe(observer, ToolFaultBatch())
    await _observe(observer, turn=turn)
    await _observe(observer)
    await _observe(observer)
    assert publisher.calls == []
    await _observe(observer)
    assert len(publisher.calls) == 1


async def test_candidate_limit_evicts_least_recently_observed_tool() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer, _batch(tool="recent"))
    await _observe(observer, _batch(tool="oldest"))
    await _observe(observer, _batch(tool="recent"))
    for index in range(MAX_FAULT_CANDIDATES - 1):
        await _observe(observer, _batch(tool=f"other-{index}"))
    await _observe(observer, _batch(tool="recent"))
    assert [call["tool_id"] for call in publisher.calls] == ["recent"]
    await _observe(observer, _batch(tool="oldest"))
    await _observe(observer, _batch(tool="oldest"))
    assert len(publisher.calls) == 1
    await _observe(observer, _batch(tool="oldest"))
    assert [call["tool_id"] for call in publisher.calls] == ["recent", "oldest"]


async def test_turn_budget_preserves_reservations_and_warns_once(caplog) -> None:
    publisher, turn = _Publisher(), ToolFaultTurn()
    observer = ToolFaultObserver(publish=publisher)
    initial = await _observe(observer, _batch(repeated=True), turn)
    for index in range(MAX_FAULT_CANDIDATES + 2):
        await _observe(observer, _batch(tool=f"other-{index}"), turn)
    result = await _observe(observer, _batch(repeated=True), turn)
    await _observe(observer, _batch(tool="over-budget", repeated=True), turn)
    assert initial == result and len(publisher.calls) == 1
    assert sum("logical-turn diagnostic budget exhausted" in r.message for r in caplog.records) == 1


@pytest.mark.parametrize("status", ["repaired", "dismissed"])
async def test_closure_requires_three_fresh_turns(tmp_path, status: str) -> None:
    path = tmp_path / "faults.db"
    store = FaultReportStore(str(path))
    assert path.is_relative_to(tmp_path)
    await store.start()
    try:
        for _ in range(3):
            await _observe(store)
        old = store.list_open()[0]
        await store.resolve(old.id, status=status)
        await _observe(store)
        await _observe(store)
        assert store.list_open() == []
        await _observe(store)
        fresh = store.list_open()[0]
        assert fresh.id != old.id and fresh.occurrences == 1
    finally:
        await store.stop()


async def test_restart_discards_subthreshold_candidates_not_durable_reports(tmp_path) -> None:
    path = tmp_path / "restart.db"
    store = FaultReportStore(str(path))
    await store.start()
    try:
        await _observe(store)
        await _observe(store)
        assert store.list_open() == []
    finally:
        await store.stop()
    store = FaultReportStore(str(path))
    await store.start()
    try:
        await _observe(store)
        await _observe(store)
        assert store.list_open() == []
        await _observe(store)
        assert store.list_open()[0].occurrences == 1
    finally:
        await store.stop()
    reopened = FaultReportStore(str(path))
    await reopened.start()
    try:
        assert len(reopened.list_open()) == 1
        with sqlite3.connect(path) as connection:
            # AD-1206 adds filing metadata, not durable candidate observations.
            assert set(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()) == {("fault_reports",), ("fault_issue_filings",)}
            assert connection.execute("SELECT COUNT(*) FROM fault_issue_filings").fetchone() == (0,)
            assert len(connection.execute("PRAGMA table_info(fault_reports)").fetchall()) == 16
    finally:
        await reopened.stop()


async def test_overlapping_distinct_turns_and_duplicate_callbacks_count_once() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    turns = [ToolFaultTurn() for _ in range(3)]
    await asyncio.gather(*(_observe(observer, turn=turn) for turn in turns for _ in range(2)))
    assert len(publisher.calls) == 1


async def test_report_failure_is_handled_and_the_same_token_never_retries() -> None:
    publisher, turn = _Publisher(), ToolFaultTurn()
    publisher.error = RuntimeError("unavailable reporting")
    observer = ToolFaultObserver(publish=publisher)
    result = await _observe(observer, _batch(repeated=True), turn)
    assert result.failed and result.attempts[0][1] == ""
    publisher.error = None
    assert await _observe(observer, _batch(repeated=True), turn) == result
    assert len(publisher.calls) == 1
    await _observe(observer, _batch(repeated=True))
    assert len(publisher.calls) == 2


async def test_publication_cancel_releases_lock_but_keeps_reservation() -> None:
    publisher, turn = _Publisher(), ToolFaultTurn()
    publisher.entered, publisher.release = asyncio.Event(), asyncio.Event()
    observer = ToolFaultObserver(publish=publisher)
    task = asyncio.create_task(_observe(observer, _batch(repeated=True), turn))
    try:
        await asyncio.wait_for(publisher.entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        publisher.release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    result = await asyncio.wait_for(_observe(observer, _batch(repeated=True), turn), 2)
    assert result.failed and len(publisher.calls) == 1
    await asyncio.wait_for(_observe(observer, _batch(repeated=True)), 2)
    assert len(publisher.calls) == 2


async def test_cancelled_lock_waiter_does_not_publish_or_poison_next_run() -> None:
    publisher = _Publisher()
    publisher.entered, publisher.release = asyncio.Event(), asyncio.Event()
    observer = ToolFaultObserver(publish=publisher)
    holder = asyncio.create_task(_observe(observer, _batch(repeated=True)))
    waiter = None
    try:
        await asyncio.wait_for(publisher.entered.wait(), 2)
        waiter = asyncio.create_task(_observe(observer, _batch(repeated=True)))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert len(publisher.calls) == 1
    finally:
        publisher.release.set()
        await asyncio.wait_for(holder, 2)
        if waiter is not None and not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    await asyncio.wait_for(_observe(observer, _batch(repeated=True)), 2)
    assert len(publisher.calls) == 2


@pytest.mark.parametrize("malformation", [
    "missing_id", "duplicate_calls", "duplicate_results", "unmatched",
    "wrong_name", "not_boolean", "non_text", "empty_error",
])
def test_malformed_outcomes_are_not_success_or_fault_evidence(malformation: str, caplog) -> None:
    outcome = _pairs(ERROR)
    result = SimpleNamespace(id="c0", output=ERROR, is_error=True)
    outcome.tool_results[0] = result
    if malformation == "missing_id":
        result.id = None
    elif malformation == "duplicate_calls":
        outcome.tool_calls.append(outcome.tool_calls[0])
    elif malformation == "duplicate_results":
        outcome.tool_results.append(result)
    elif malformation == "unmatched":
        result.id = "not-called"
    elif malformation == "wrong_name":
        result.name = "different"
    elif malformation == "not_boolean":
        result.is_error = 0
    elif malformation == "non_text":
        result.output = {"error": ERROR}
    else:
        result.output = "  "
    batch = _collect(outcome)
    assert batch.tools == () and batch.same_run is None
    assert caplog.records


def test_count_one_is_not_a_legacy_verdict() -> None:
    batch = _collect(_pairs(ERROR))
    assert batch.tools[0].defect.count == 1 and batch.same_run is None
    assert resolve_tool_defect(SimpleNamespace(
        tool_defect_evaluated=True, tool_defect=batch.tools[0].defect,
    )) is None


@pytest.mark.parametrize("attempts", [
    [], (("bad", ""),), (("a" * 64, "x" * 129),),
    (("a" * 64, ""), ("a" * 64, "")),
    tuple((f"{index:064x}", "") for index in range(MAX_FAULT_CANDIDATES + 1)),
])
def test_result_rejects_unbounded_or_forged_attempts(attempts) -> None:
    with pytest.raises(ValueError):
        FaultObservationResult(attempts=attempts)


def test_carriers_revalidate_mutation_and_reject_mismatched_defects() -> None:
    result = FaultObservationResult()
    object.__setattr__(result, "failed", 1)
    with pytest.raises(ValueError):
        result.validate()
    with pytest.raises(ValueError):
        ToolFaultBatch((ToolFaultEvidence("other", _batch().tools[0].defect),))
    with pytest.raises(ValueError):
        ToolFaultBatch(same_run=_batch().tools[0].defect)
    with pytest.raises(ValueError):
        ToolFaultBatch((_batch().tools[0], _batch().tools[0]))
    forged = replace(_batch())
    object.__setattr__(forged, "tools", [])
    with pytest.raises(ValueError):
        forged.validate()


def test_turn_public_boundaries_and_empty_result() -> None:
    turn = ToolFaultTurn()
    assert turn.result() == FaultObservationResult()
    assert len(turn.identity) == 32 and turn.identity != ToolFaultTurn().identity
    with pytest.raises(ValueError):
        turn.note("", None)
    with pytest.raises(ValueError):
        turn.reserve("not-a-signature")
    with pytest.raises(ValueError):
        turn.finish("a" * 64, "never-reserved")
    assert turn.reserve("a" * 64)
    with pytest.raises(ValueError):
        turn.finish("a" * 64, "x" * 129)
    turn.finish("a" * 64, "actual-id")
    assert turn.result().fault_id("a" * 64) == "actual-id"


async def test_store_and_observer_reject_invalid_batches_and_clock() -> None:
    store = FaultReportStore()
    with pytest.raises(ValueError, match="fault_turn_invalid"):
        await store.observe_tool_run(turn=None, batch=ToolFaultBatch(), agent_id="agent")
    with pytest.raises(ValueError, match="fault_batch_invalid"):
        await _observe(store, object())
    observer = ToolFaultObserver(publish=_Publisher(), clock=lambda: float("nan"))
    with pytest.raises(ValueError, match="fault_clock_invalid"):
        await _observe(observer)
    assert store.list_open() == []


@pytest.mark.parametrize("attribute", ["tool_calls", "tool_results"])
@pytest.mark.parametrize("value", [None, {}, 1])
def test_collector_rejects_non_sequence_pairs(attribute: str, value: Any) -> None:
    outcome = _pairs(ERROR)
    setattr(outcome, attribute, value)
    with pytest.raises(ValueError, match="fault_run_pairs_invalid"):
        _collect(outcome)


def test_batch_rejects_untyped_evidence_and_collector_keeps_first_1024(caplog) -> None:
    with pytest.raises(ValueError, match="fault_run_evidence_invalid"):
        ToolFaultBatch((object(),))
    outcome = SimpleNamespace(
        tool_calls=[
            ToolCallRequest(name=f"tool-{index}", arguments={}, id=f"call-{index}")
            for index in range(MAX_FAULT_CANDIDATES + 2)
        ],
        tool_results=[
            ToolCallResult(id=f"call-{index}", output=ERROR, is_error=True)
            for index in range(MAX_FAULT_CANDIDATES + 2)
        ],
    )
    batch = _collect(outcome)
    assert [item.tool_id for item in batch.tools] == [
        f"tool-{index}" for index in range(MAX_FAULT_CANDIDATES)
    ]
    assert batch.same_run is None
    assert sum("run evidence reached its tool bound" in r.message for r in caplog.records) == 1


async def test_policy_noise_mixed_with_fault_keeps_original_third_vote() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer, _collect(_pairs(ERROR)))
    await _observe(observer, _collect(_pairs(ERROR)))
    mixed = _collect(_pairs(ERROR, "permission denied"))
    # R1: the old assertion made a non-invocation erase a genuine fault vote.
    assert not mixed.tools[0].mixed and mixed.same_run is None
    await _observe(observer, mixed)
    assert len(publisher.calls) == 1


async def test_closure_forgets_only_matching_signature_and_unknown_resolution_is_neutral() -> None:
    store = FaultReportStore()
    for _ in range(2):
        await _observe(store, _batch(tool="first"))
        await _observe(store, _batch(tool="second"))
    await _observe(store, _batch(tool="first"))
    assert await store.resolve("not-a-report", status="dismissed") is None
    first = store.get_by_tool("first")[0]
    await store.resolve(first.id, status="dismissed")
    await _observe(store, _batch(tool="second"))
    assert [report.tool_id for report in store.list_open()] == ["second"]
    for _ in range(2):
        await _observe(store, _batch(tool="first"))
    assert [report.tool_id for report in store.list_open()] == ["second"]
    await _observe(store, _batch(tool="first"))
    assert {report.tool_id for report in store.list_open()} == {"first", "second"}


@pytest.mark.parametrize("value", [None, "", 3, "x" * 129])
async def test_invalid_publisher_id_is_failed_once_without_fabricated_durability(value: Any) -> None:
    calls = []

    async def publish(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(id=value)

    observer = ToolFaultObserver(publish=publish)
    turn = ToolFaultTurn()
    result = await _observe(observer, _batch(repeated=True), turn)
    assert result.failed and result.attempts == ((_batch().tools[0].defect.signature, ""),)
    assert await _observe(observer, _batch(repeated=True), turn) == result
    assert len(calls) == 1


async def test_completed_observation_invalid_turn_fails_without_success_or_id(caplog) -> None:
    result = await observe_completed_tool_run(
        FaultReportStore(), outcome=_pairs(ERROR), turn=None,
        classify_error=classify_tool_error, agent_id="agent",
    )
    assert result == FaultObservationResult(failed=True)
    assert any("legacy publication is suppressed" in r.message for r in caplog.records)


async def test_surrogate_error_preserves_existing_total_signature_without_raw_arguments() -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    error = "fixture \ud800 diagnostic"
    for _ in range(3):
        batch = _collect(_pairs(error))
        assert batch.same_run is None and batch.tools[0].defect.error_text == error
        await _observe(observer, batch)
    assert len(publisher.calls) == 1
    defect = publisher.calls[0]["defect"]
    assert defect.signature == ToolDefect(tool_id="fixture", error_text=error, count=2).signature
    assert "not_retained" not in publisher.calls[0] and "secret" not in repr(batch)


def _intervention() -> ToolResult:
    return ToolResult(
        output={"intervention_required": True, "tier": 3, "session_id": "owned"},
        metadata={"tier": 3, "session_id": "owned"},
    )


@pytest.mark.parametrize("kind", [None, ToolFaultAdapterKind.MCP, ToolFaultAdapterKind.BROWSER])
def test_capture_uses_adapter_kind_and_retains_no_raw_result(kind) -> None:
    capture = ToolFaultCapture(adapter_kind=lambda _name: kind)
    raw = _intervention()
    raw_ref = weakref.ref(raw)
    capture.record("call", "fixture", raw)
    assert capture.is_neutral("call", "fixture") is (kind is ToolFaultAdapterKind.BROWSER)
    del raw
    gc.collect()
    assert raw_ref() is None
    capture.validate()
    assert capture.is_neutral("exception-without-raw-result", "fixture") is False


@pytest.mark.parametrize("raw", [
    ToolResult(error="requires_confirmation"),
    ToolResult(error="requires_confirmation", metadata={"mcp_tier": "open"}),
    ToolResult(error="other", metadata={"mcp_tier": "confirm", "outcome": "requires_confirmation"}),
    ToolResult(output={"intervention_required": True}),
])
def test_capture_incomplete_mcp_shape_is_ordinary(raw: ToolResult) -> None:
    capture = ToolFaultCapture(adapter_kind=lambda _name: ToolFaultAdapterKind.MCP)
    capture.record("call", "fixture", raw)
    assert not capture.is_neutral("call", "fixture")


@pytest.mark.parametrize(("field", "value"), [
    ("intervention_required", 1), ("intervention_required", False),
    ("tier", True), ("tier", 2), ("session_id", ""), ("session_id", None),
])
def test_capture_incomplete_browser_shape_is_ordinary(field: str, value: Any) -> None:
    raw = _intervention()
    raw.output[field] = value
    capture = ToolFaultCapture(adapter_kind=lambda _name: ToolFaultAdapterKind.BROWSER)
    capture.record("call", "fixture", raw)
    assert not capture.is_neutral("call", "fixture")


@pytest.mark.parametrize(("request_id", "name"), [
    ("", "fixture"), (None, "fixture"), ("x" * 129, "fixture"),
    ("call", ""), ("call", None), ("call", "x" * 129),
])
def test_capture_rejects_invalid_or_oversized_identity_without_truncation(request_id, name, caplog) -> None:
    capture = ToolFaultCapture(adapter_kind=lambda _name: None)
    capture.record(request_id, name, ToolResult(output="healthy"))
    capture.record("later", "fixture", ToolResult(output="healthy"))
    with pytest.raises(ValueError, match="fault_capture_unavailable"):
        capture.validate()
    assert sum("raw tool disposition capture is unavailable" in r.message for r in caplog.records) == 1


@pytest.mark.parametrize("second_name", ["fixture", "other"])
def test_capture_duplicate_request_id_invalidates_run(second_name: str) -> None:
    capture = ToolFaultCapture(adapter_kind=lambda _name: ToolFaultAdapterKind.BROWSER)
    capture.record("call", "fixture", _intervention())
    capture.record("call", second_name, ToolResult(output="healthy"))
    with pytest.raises(ValueError, match="fault_capture_unavailable"):
        capture.validate()


def test_capture_bounds_and_constructor_and_result_validation(caplog) -> None:
    with pytest.raises(TypeError, match="fault_capture_adapter_query_invalid"):
        ToolFaultCapture(adapter_kind=None)
    capture = ToolFaultCapture(adapter_kind=lambda _name: None)
    for index in range(MAX_FAULT_CANDIDATES):
        capture.record(f"call-{index}", "fixture", ToolResult(output="healthy"))
    capture.validate()
    capture.record("overflow", "fixture", ToolResult(output="healthy"))
    capture.record("more-overflow", "fixture", ToolResult(output="healthy"))
    with pytest.raises(ValueError, match="fault_capture_unavailable"):
        capture.validate()
    assert sum("raw tool disposition capture is unavailable" in r.message for r in caplog.records) == 1
    invalid = ToolFaultCapture(adapter_kind=lambda _name: None)
    invalid.record("call", "fixture", SimpleNamespace(output={}, error=None))
    with pytest.raises(ValueError, match="fault_capture_unavailable"):
        invalid.validate()


@pytest.mark.parametrize("failure", ["query", "kind", "correlation", "forged"])
async def test_capture_failure_cannot_reset_health_or_reopen_legacy_filing(failure: str) -> None:
    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer)
    await _observe(observer)

    def query(_name):
        if failure == "query":
            raise RuntimeError("fixture diagnostic collaborator failed")
        return "browser" if failure == "kind" else None

    capture = ToolFaultCapture(adapter_kind=query)
    capture.record("c0", "other" if failure == "correlation" else "fixture", ToolResult(error=ERROR))
    result = await observe_completed_tool_run(
        observer, outcome=_pairs(ERROR, ERROR, None), turn=ToolFaultTurn(),
        classify_error=classify_tool_error, agent_id="agent",
        fault_capture=SimpleNamespace() if failure == "forged" else capture,
    )
    assert result == FaultObservationResult(failed=True)
    assert publisher.calls == [], "invalid capture cannot fall back to the legacy two-hit lane"
    await _observe(observer)
    assert len(publisher.calls) == 1, "unavailable capture did not erase the two earlier votes"


def test_capture_query_cancellation_propagates() -> None:
    def cancelled(_name):
        raise asyncio.CancelledError

    capture = ToolFaultCapture(adapter_kind=cancelled)
    with pytest.raises(asyncio.CancelledError):
        capture.record("call", "fixture", ToolResult(output="healthy"))


async def test_capture_neutral_and_failure_same_batch_keeps_third_vote_and_legacy_minimum() -> None:
    from probos.cognitive.agentic_dispatch import classify_tool_fault_error

    publisher = _Publisher()
    observer = ToolFaultObserver(publish=publisher)
    await _observe(observer)
    await _observe(observer)
    capture = ToolFaultCapture(adapter_kind=lambda _name: ToolFaultAdapterKind.BROWSER)
    capture.record("c0", "fixture", ToolResult(error=ERROR))
    capture.record("c1", "fixture", _intervention())
    batch = _collect(_pairs(ERROR, None), fault_capture=capture)
    assert not batch.tools[0].mixed and not batch.tools[0].succeeded
    await _observe(observer, batch)
    assert len(publisher.calls) == 1

    refusal = ToolResult(
        error="requires_confirmation",
        metadata={"mcp_tier": "confirm", "outcome": "requires_confirmation"},
    )
    capture = ToolFaultCapture(adapter_kind=lambda _name: ToolFaultAdapterKind.MCP)
    for ident in ("c0", "c1"):
        capture.record(ident, "fixture", refusal)
    legacy = collect_tool_fault_batch(
        _pairs(refusal.error, refusal.error), classify_error=classify_tool_fault_error,
        fault_capture=capture,
    )
    assert legacy.tools == () and legacy.same_run.count == 2
    assert classify_tool_fault_error(" requires_confirmation") == "other"
