"""AD-1224: bounded tool lifecycle records across execution and retention sinks.

An unmatched start establishes an incomplete recorded attempt. Cancellation,
process death, and completion-write failure can all leave one; it is not proof
that a tool is still running. Recovered WIP regressions retain their diagnostic
intent while correcting the rejected privacy, pairing and budget contracts.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from probos.events import EventType
from probos.substrate.event_log import EventLog
from probos.tools.executor import (
    DEFAULT_MAX_RECORDS_PER_RUN,
    ERROR_CATEGORIES,
    ToolExecutor,
    ToolRecordBudget,
    classify_tool_error,
    digest_params,
    make_audit_hook,
    make_start_hook,
    recording_identity,
    sample_recording_identity,
    tool_record_identity,
    tool_recording_scope,
    wire_durable_tool_records,
    wire_tool_invocation_hooks,
)
from probos.tools.protocol import ToolResult

_SECRET = "sk-live-511dd0ec-DO-NOT-LOG-THIS-VALUE"
_ERROR_MARKER = "CONSUMER_VISIBLE_SECRET_71c4"
_LogFactory = Callable[..., Awaitable[EventLog]]


@pytest.fixture(scope="module", autouse=True)
def _assert_tested_source_matches_worktree() -> None:
    import probos.substrate.event_log as event_log_module
    import probos.tools.executor as executor_module

    source = Path(__file__).resolve().parents[1] / "src"
    assert Path(executor_module.__file__).resolve().is_relative_to(source)
    assert Path(event_log_module.__file__).resolve().is_relative_to(source)


@pytest_asyncio.fixture
async def open_log(tmp_path: Path) -> AsyncIterator[_LogFactory]:
    """Close every connection even when a regression fails."""
    opened: list[EventLog] = []

    async def _open(name: str = "events.db") -> EventLog:
        log = EventLog(db_path=tmp_path / name)
        await log.start()
        opened.append(log)
        return log

    try:
        yield _open
    finally:
        for log in opened:
            await log.stop()


class _FakeRegistry:
    """Explicit catalog and a body that can inspect committed starts."""

    def __init__(
        self,
        *,
        on_invoke: Callable[[], Awaitable[None]] | None = None,
        raises: BaseException | None = None,
        error: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._on_invoke = on_invoke
        self._raises = raises
        self._error = error

    def list_ids(self) -> list[str]:
        return [
            "tool-1", "http_fetch", "run_command", "browser", "read_file",
            "write_file", "oracle_query", "t",
        ]

    async def check_and_invoke(
        self, agent_id: str, tool_id: str, params: dict[str, Any], **kwargs: Any,
    ) -> ToolResult:
        self.calls.append((agent_id, tool_id, params))
        if self._on_invoke is not None:
            await self._on_invoke()
        if self._raises is not None:
            raise self._raises
        if self._error is not None:
            return ToolResult(error=self._error)
        return ToolResult(output={"ok": True})


async def _rows(log: EventLog, event: str) -> list[dict[str, Any]]:
    return [row for row in await log.query(category="tool", limit=1000) if row["event"] == event]


def _paired(
    executor: ToolExecutor,
    log: Any,
    *,
    max_records_per_run: int = DEFAULT_MAX_RECORDS_PER_RUN,
) -> None:
    executor.add_pre_hook(
        make_start_hook(event_log=log, max_records_per_run=max_records_per_run),
    )
    audit = make_audit_hook(event_log=log)
    executor.add_post_hook(audit)
    executor.add_terminal_hook(audit)


class _HostileRepr:
    def __repr__(self) -> str:
        raise RuntimeError("repr() was called on caller-supplied data")

    def __str__(self) -> str:
        raise RuntimeError("str() was called on caller-supplied data")

    def __hash__(self) -> int:
        return 4711


class _HostileLen:
    def __len__(self) -> int:
        raise RuntimeError("len() was called on caller-supplied data")


async def test_start_record_is_durable_before_the_tool_body_runs(open_log: _LogFactory) -> None:
    log = await open_log()
    observed: list[list[dict[str, Any]]] = []

    async def _mid_call() -> None:
        reader = await open_log()
        observed.append(await _rows(reader, EventType.TOOL_STARTED.value))

    executor = ToolExecutor(registry=_FakeRegistry(on_invoke=_mid_call))
    executor.add_pre_hook(make_start_hook(event_log=log))

    await executor.invoke("agent-1", "http_fetch", {"url": "https://example.com"})

    assert observed, "the tool body never ran"
    assert len(observed[0]) == 1, "the start was not committed before entry"
    assert observed[0][0]["detail"] == "http_fetch"


async def test_start_record_precedes_the_registry_call_in_order(open_log: _LogFactory) -> None:
    log = await open_log()
    order: list[str] = []

    async def _mid_call() -> None:
        order.append("tool")

    executor = ToolExecutor(registry=_FakeRegistry(on_invoke=_mid_call))
    executor.add_pre_hook(
        make_start_hook(emit_fn=lambda *_: order.append("start"), event_log=log),
    )

    await executor.invoke("agent-1", "run_command", {})

    assert order == ["start", "tool"]


async def test_cancelled_mid_tool_leaves_an_unpaired_start_readable_after_restart(
    open_log: _LogFactory,
) -> None:
    """Cancellation is a control for the separate hard-kill regression below."""
    log = await open_log()
    entered = asyncio.Event()

    async def _hang() -> None:
        entered.set()
        await asyncio.Event().wait()

    executor = ToolExecutor(registry=_FakeRegistry(on_invoke=_hang))
    _paired(executor, log)
    task = asyncio.create_task(executor.invoke("agent-7", "browser", {"action": "read_page"}))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await log.stop()

    restarted = await open_log()
    starts = await _rows(restarted, EventType.TOOL_STARTED.value)
    completions = await _rows(restarted, EventType.TOOL_INVOKED.value)

    assert len(starts) == 1
    assert starts[0]["detail"] == "browser"
    assert starts[0]["agent_id"] == "agent-7"
    assert starts[0]["correlation_id"]
    assert {row["correlation_id"] for row in starts} - {
        row["correlation_id"] for row in completions
    } == {starts[0]["correlation_id"]}


async def test_completed_call_leaves_no_unpaired_start_after_restart(open_log: _LogFactory) -> None:
    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    _paired(executor, log)

    await executor.invoke("agent-7", "read_file", {"path": "README.md"})
    await log.stop()

    restarted = await open_log()
    starts = await _rows(restarted, EventType.TOOL_STARTED.value)
    completions = await _rows(restarted, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] is not None
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]


async def test_permission_denial_closes_the_pairing(open_log: _LogFactory) -> None:
    """Classify the exception itself, without formatting its possibly secret prose."""
    log = await open_log()
    failure = PermissionError("agent lacks write on tool-1 " + _ERROR_MARKER)
    executor = ToolExecutor(registry=_FakeRegistry(raises=failure))
    _paired(executor, log)

    with pytest.raises(PermissionError) as raised:
        await executor.invoke("agent-2", "write_file", {"path": "x"})

    assert raised.value is failure
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]
    data = completions[0]["data"]
    assert data["is_error"] is True
    assert data["error_category"] == "permission_denied"
    assert "error" not in data
    assert _ERROR_MARKER not in json.dumps(completions)


async def test_pre_hook_abort_closes_the_pairing(open_log: _LogFactory) -> None:
    log = await open_log()
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    executor.add_pre_hook(lambda _ctx: False)

    result = await executor.invoke("agent-3", "run_command", {"command": "rm -rf /"})

    assert result.error is not None and registry.calls == []
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]
    assert completions[0]["data"]["error_category"] == "aborted_by_hook"


async def test_terminal_hook_does_not_fire_on_the_normal_path() -> None:
    seen: list[str] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_terminal_hook(lambda _ctx, _result: seen.append("terminal"))
    await executor.invoke("agent-1", "tool-1", {})
    assert seen == []


async def test_secret_parameter_is_not_recoverable_from_the_durable_record(
    open_log: _LogFactory,
) -> None:
    log = await open_log()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_pre_hook(make_start_hook(
        emit_fn=lambda event, payload: emitted.append((event, payload)), event_log=log,
    ))

    await executor.invoke("agent-1", "http_fetch", {
        "url": "https://api.example.com",
        "headers": {"Authorization": f"Bearer {_SECRET}"}, "api_key": _SECRET,
    })

    rows = await _rows(log, EventType.TOOL_STARTED.value)
    assert len(rows) == len(emitted) == 1
    assert _SECRET not in json.dumps(rows)
    assert _SECRET not in json.dumps(emitted[0][1])
    assert rows[0]["detail"] == "http_fetch"
    assert {field["key"] for field in rows[0]["data"]["params"]["fields"]} == {
        "url", "headers", "api_key",
    }


def test_digest_records_shape_and_never_a_value() -> None:
    """The WIP size=7 assertion disclosed password length; scalars have no size."""
    digest = digest_params({"password": "hunter2", "limit": 3})
    assert "hunter2" not in json.dumps(digest)
    assert digest["key_count"] == 2
    by_key = {field["key"]: field for field in digest["fields"]}
    assert by_key["password"]["value"] == {"type": "str", "size": None}
    assert by_key["limit"]["value"] == {"type": "int", "size": None}


def test_digest_never_hashes_a_value() -> None:
    assert digest_params({"a": 1})["shape_sha256"] == digest_params({"a": 2})["shape_sha256"]
    assert digest_params({"api_key": "x" * 8}) == digest_params({"api_key": "y" * 8000})
    assert digest_params({"body": b"x"}) == digest_params({"body": b"y" * 8000})
    assert digest_params({"data": bytearray(b"x")}) == digest_params({"data": bytearray(b"y" * 8000)})


def test_digest_is_stable_and_discriminates_shape() -> None:
    assert digest_params({"a": 1})["shape_sha256"] == digest_params({"a": 1})["shape_sha256"]
    assert digest_params({"limit": 1, "path": "ab"}) == digest_params({"path": "ab", "limit": 1})
    assert digest_params({"limit": 1})["shape_sha256"] != digest_params({"limit": 1, "path": "ab"})["shape_sha256"]


def test_digest_hashes_key_names_outside_the_fixed_vocabulary() -> None:
    credential_key = f"sk-live-{_SECRET}"
    digest = digest_params({credential_key: 1, "path": "a"})
    assert _SECRET not in json.dumps(digest)
    by_key = {field["key"]: field for field in digest["fields"]}
    assert by_key["path"]["key_hash"] is None
    hashed = [field for field in digest["fields"] if field["key"] is None]
    assert len(hashed) == 1
    assert len(hashed[0]["key_hash"]) == 12
    assert hashed[0]["key_type"] == "str"
    assert digest_params({credential_key: 1})["fields"][0]["key_hash"] == hashed[0]["key_hash"]
    assert digest_params({credential_key + "!": 1})["fields"][0]["key_hash"] != hashed[0]["key_hash"]


def test_digest_bounds_key_count() -> None:
    digest = digest_params({f"{'k' * 500}{index}": index for index in range(80)})
    assert len(digest["fields"]) == 16
    assert digest["key_count"] == 80
    assert digest["keys_omitted"] == 64
    assert all(field["key"] is None for field in digest["fields"])
    assert len(json.dumps(digest).encode("utf-8")) <= 2048


def test_digest_does_not_copy_a_large_blob() -> None:
    """A blob's scalar length is secret too, not just its bytes."""
    digest = digest_params({"body": "x" * 5_000_000})
    assert len(json.dumps(digest)) < 1024
    assert digest["fields"][0]["value"]["size"] is None


def test_digest_bounds_nesting_depth_and_item_count() -> None:
    deep: Any = {"leaf": _SECRET}
    for _ in range(20):
        deep = {"nested": deep}
    digest = digest_params({"data": deep, "urls": list(range(500))})
    assert _SECRET not in json.dumps(digest)
    assert len(json.dumps(digest).encode("utf-8")) <= 2048
    by_key = {field["key"]: field for field in digest["fields"]}
    assert by_key["urls"]["value"]["size"] == 500
    assert len(by_key["urls"]["value"]["items"]) == 8
    assert by_key["urls"]["value"]["items_omitted"] == 492
    assert by_key["data"]["value"]["type"] == "dict"


def test_digest_labels_bytes_and_non_string_keys() -> None:
    digest = digest_params({b"raw": b"\x00" * 9, 7: 1, (1, 2): 2, "path": None})
    by_type = {(field["key"], field["key_type"]): field for field in digest["fields"]}
    assert ("path", "str") in by_type
    assert by_type[("path", "str")]["value"]["type"] == "null"
    bytes_key = [field for field in digest["fields"] if field["key_type"] == "bytes"][0]
    assert bytes_key["key"] is None and len(bytes_key["key_hash"]) == 12
    assert bytes_key["value"] == {"type": "bytes", "size": None}
    int_key = [field for field in digest["fields"] if field["key_type"] == "int"][0]
    assert int_key["key"] is None and int_key["key_hash"] is None
    tuple_key = [field for field in digest["fields"] if field["key_type"] == "list"][0]
    assert tuple_key["key"] is None and tuple_key["key_hash"] is None


def test_digest_never_calls_a_caller_dunder() -> None:
    digest = digest_params({"a": _HostileRepr(), "b": _HostileLen(), "c": [_HostileRepr()]})
    assert {field["value"]["type"] for field in digest["fields"]} == {"other", "list"}
    assert "_Hostile" not in json.dumps(digest)
    assert digest.get("degraded") is not True


@pytest.mark.parametrize("params", [
    None, ["a"], "raw-string", _HostileRepr(), {"k": _HostileLen()},
    {_HostileRepr(): 1}, {"nested": {"deeper": [_HostileRepr(), _HostileLen()]}},
], ids=["none", "list", "str", "hostile-repr", "hostile-len-value", "hostile-key", "hostile-nested"])
def test_digest_handles_supported_and_opaque_inputs(params: Any) -> None:
    digest = digest_params(params)
    assert type(digest["shape_sha256"]) is str
    assert type(digest["fields"]) is list


def test_digest_tolerates_non_dict_params() -> None:
    assert digest_params(None)["key_count"] == 0
    assert digest_params(None)["non_dict"] == {"type": "null", "size": None}
    assert digest_params(["a"])["non_dict"] == {
        "type": "list", "size": 1,
        "items": [{"type": "str", "size": None}], "items_omitted": 0,
    }


async def test_a_hostile_parameter_object_still_leaves_a_start_record(open_log: _LogFactory) -> None:
    log = await open_log()
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    await executor.invoke("agent-1", "run_command", {"command": _HostileLen(), "args": _HostileRepr()})
    assert len(registry.calls) == 1, "the tool never ran; absence proves nothing"
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]


def test_budget_allows_exactly_max_per_run() -> None:
    budget = ToolRecordBudget(max_per_run=3)
    spent = [budget.spend("run-a") for _ in range(5)]
    assert [allowed for allowed, _ in spent] == [True, True, True, False, False]
    assert [announce for _, announce in spent] == [False, False, False, True, False]
    assert budget.spend("run-b") == (True, False)


def test_budget_of_zero_admits_nothing() -> None:
    """Replace WIP silence with one explicit disabled marker, never one per call."""
    budget = ToolRecordBudget(max_per_run=0)
    assert budget.spend("run-a") == (False, True)
    assert budget.spend("run-a") == (False, False)


def test_budget_bounds_the_run_map_itself(caplog: pytest.LogCaptureFixture) -> None:
    """The WIP required eviction; saturation must instead preserve spent counts."""
    budget = ToolRecordBudget(max_per_run=1, max_tracked_runs=2)
    assert budget.spend("run-a") == (True, False)
    assert budget.spend("run-b") == (True, False)
    assert budget.spend("run-c") == (False, False)
    assert budget.spend("run-a") == (False, True)
    assert budget.spend("run-c") == (False, False)
    assert caplog.text.count("standalone recording scope exhausted") == 1


async def test_budget_drops_pairs_not_just_starts(open_log: _LogFactory) -> None:
    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    _paired(executor, log, max_records_per_run=2)
    for _ in range(5):
        await executor.invoke("agent-1", "read_file", {}, context={"thread_id": "thread-9"})
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    exhausted = await _rows(log, EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value)
    assert len(starts) == len(completions) == 2
    assert {row["correlation_id"] for row in starts} == {row["correlation_id"] for row in completions}
    assert len(exhausted) == 1
    assert exhausted[0]["data"]["run_key"] == "thread-9"
    assert exhausted[0]["data"]["max_records_per_run"] == 2


async def test_a_hang_past_the_budget_is_explained_not_silently_zero(open_log: _LogFactory) -> None:
    log = await open_log()
    entered: list[int] = []
    hanging = asyncio.Event()

    async def _hang_on_third() -> None:
        entered.append(len(entered) + 1)
        if len(entered) >= 3:
            hanging.set()
            await asyncio.Event().wait()

    executor = ToolExecutor(registry=_FakeRegistry(on_invoke=_hang_on_third))
    _paired(executor, log, max_records_per_run=2)
    for _ in range(2):
        await executor.invoke("a", "read_file", {}, context={"thread_id": "t-9"})
    task = asyncio.create_task(executor.invoke("a", "browser", {}, context={"thread_id": "t-9"}))
    try:
        await asyncio.wait_for(hanging.wait(), timeout=10)
        assert len(entered) == 3 and not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    exhausted = await _rows(log, EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value)
    assert len(starts) == len(completions) == 2
    assert {row["correlation_id"] for row in starts} - {row["correlation_id"] for row in completions} == set()
    assert len(exhausted) == 1
    assert exhausted[0]["data"]["run_key"] == "t-9"


async def test_budget_is_keyed_per_run_not_globally(open_log: _LogFactory) -> None:
    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    _paired(executor, log, max_records_per_run=1)
    await executor.invoke("a", "t", {}, context={"thread_id": "thread-1"})
    await executor.invoke("a", "t", {}, context={"thread_id": "thread-1"})
    await executor.invoke("a", "t", {}, context={"thread_id": "thread-2"})
    rows = await _rows(log, EventType.TOOL_STARTED.value)
    assert sorted(row["data"]["thread_id"] for row in rows) == ["thread-1", "thread-2"]
    assert len(await _rows(log, EventType.TOOL_INVOKED.value)) == 2


async def test_budget_is_keyed_by_run_id_when_there_is_no_thread(open_log: _LogFactory) -> None:
    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    _paired(executor, log, max_records_per_run=1)
    await executor.invoke("swe", "read_file", {}, context={"_agentic_run_id": "r1"})
    await executor.invoke("swe", "read_file", {}, context={"_agentic_run_id": "r1"})
    await executor.invoke("swe", "read_file", {}, context={"_agentic_run_id": "r2"})
    rows = await _rows(log, EventType.TOOL_STARTED.value)
    assert sorted(row["data"]["run_id"] for row in rows) == ["r1", "r2"]


async def test_agentic_loop_mints_a_run_id_per_run(open_log: _LogFactory) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_pre_hook(make_start_hook(event_log=log))
    llm = _DispatchLLM("read_file")
    loop = AgenticLoop(llm_client=llm, tool_executor=executor)
    caller_context = {"agent_id": "swe", "department": "engineering"}
    await loop.run(system_prompt="s", user_message="u", tools=[], context=caller_context)
    llm.calls = 0
    await loop.run(system_prompt="s", user_message="u", tools=[], context=caller_context)
    rows = await _rows(log, EventType.TOOL_STARTED.value)
    run_ids = {row["data"]["run_id"] for row in rows}
    assert len(rows) == 2
    assert None not in run_ids
    assert len(run_ids) == 2
    assert "_agentic_run_id" not in caller_context
    assert "iteration" not in caller_context


def test_default_budget_is_a_real_bound() -> None:
    assert DEFAULT_MAX_RECORDS_PER_RUN == 500
    assert 0 < DEFAULT_MAX_RECORDS_PER_RUN < 10_000


async def test_start_record_carries_run_provenance(open_log: _LogFactory) -> None:
    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_pre_hook(make_start_hook(event_log=log))
    await executor.invoke("agent-5", "oracle_query", {"q": "x"}, context={
        "thread_id": "thread-42", "_crew_work_item_id": "wi-7", "iteration": 3,
    })
    data = (await _rows(log, EventType.TOOL_STARTED.value))[0]["data"]
    assert data["agent_id"] == "agent-5"
    assert data["tool_id"] == "oracle_query"
    assert data["thread_id"] == "thread-42"
    assert data["work_item_id"] == "wi-7"
    assert data["iteration"] == 3
    assert data["invocation_id"]


async def test_start_record_omits_absent_provenance(open_log: _LogFactory) -> None:
    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_pre_hook(make_start_hook(event_log=log))
    await executor.invoke("agent-5", "read_file", {})
    data = (await _rows(log, EventType.TOOL_STARTED.value))[0]["data"]
    assert data["thread_id"] is None
    assert data["work_item_id"] is None
    assert data["iteration"] is None


async def test_start_hook_never_blocks_the_call_when_the_log_fails() -> None:
    class _BrokenLog:
        async def log(self, **_kwargs: Any) -> int:
            raise OSError("disk full")

    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    executor.add_pre_hook(make_start_hook(event_log=_BrokenLog()))
    result = await executor.invoke("agent-1", "read_file", {})
    assert result.error is None and len(registry.calls) == 1


async def test_start_hook_works_without_an_event_log() -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_pre_hook(make_start_hook(emit_fn=lambda event, payload: emitted.append((event, payload))))
    await executor.invoke("agent-1", "read_file", {})
    assert len(emitted) == 1
    assert emitted[0][0] is EventType.TOOL_STARTED


def test_tool_started_event_type_exists() -> None:
    assert EventType.TOOL_STARTED.value == "tool_started"
    assert EventType.TOOL_STARTED is not EventType.TOOL_INVOKED
    assert EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value == "tool_record_budget_exhausted"


class _AcceptingAuditSink:
    async def audit_governed_query(self, audit: Any) -> bool:
        return True


async def _read_through_governed_reader(log: EventLog) -> dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    from probos.tools.event_log_query_tool import EventLogQueryTool

    now = datetime.now(timezone.utc)
    result = await EventLogQueryTool(reader=log, audit_sink=_AcceptingAuditSink()).invoke(
        {
            "start_time": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "end_time": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "category": "tool", "limit": 200,
        },
        {
            "agent_id": "laforge-1", "agent_department": "engineering",
            "agent_rank": "lieutenant", "permission": "read",
        },
    )
    assert result.error is None, f"the governed reader refused: {result.error}"
    assert result.output["returned_count"] > 0, "the governed reader saw no tool rows"
    return result.output


async def test_tool_error_text_reaches_neither_the_durable_row_nor_a_reader(open_log: _LogFactory) -> None:
    log = await open_log()
    echoed = f"Unsupported action: {_ERROR_MARKER}. Try read_page. " + "z" * 4096
    executor = ToolExecutor(registry=_FakeRegistry(error=echoed))
    _paired(executor, log)
    result = await executor.invoke("agent-1", "browser", {"action": _ERROR_MARKER})
    assert result.error is not None and _ERROR_MARKER in result.error
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(completions) == 1
    assert _ERROR_MARKER not in json.dumps(completions)
    assert completions[0]["data"]["is_error"] is True
    assert completions[0]["data"]["error_category"] in ERROR_CATEGORIES
    assert len(json.dumps(completions[0]["data"])) < 1024
    output = await _read_through_governed_reader(log)
    assert output["returned_count"] >= 1
    assert _ERROR_MARKER not in json.dumps(output)


@pytest.mark.parametrize("failed", [False, True])
async def test_runtime_nats_and_governed_reader_retain_only_safe_outcomes(
    open_log: _LogFactory, failed: bool,
) -> None:
    """Replace the WIP raw bus-error assertion: SYSTEM_EVENTS is retained too."""
    from probos.runtime import ProbOSRuntime

    class _RecordingNats:
        connected = True

        def __init__(self) -> None:
            self.published: list[tuple[str, dict[str, Any]]] = []

        async def js_publish(self, subject: str, event: dict[str, Any], **kwargs: Any) -> None:
            self.published.append((subject, json.loads(json.dumps(event))))

    class _Runtime(ProbOSRuntime):
        def __init__(self, bus: _RecordingNats) -> None:
            self.nats_bus = bus
            self._nats_publish_tasks: set[asyncio.Task[Any]] = set()

        def _check_night_order_escalation(self, event_type: str, data: dict[str, Any]) -> None:
            pass

        async def drain_events(self) -> None:
            if self._nats_publish_tasks:
                await asyncio.wait_for(asyncio.gather(*tuple(self._nats_publish_tasks)), timeout=10)

        async def close_events(self) -> None:
            tasks = tuple(self._nats_publish_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    log = await open_log()
    bus = _RecordingNats()
    runtime = _Runtime(bus)
    echoed = f"network failure {_ERROR_MARKER}" + "z" * 2_000_000 if failed else None
    executor = ToolExecutor(registry=_FakeRegistry(error=echoed))
    wire_tool_invocation_hooks(executor, event_log=log, emit_fn=runtime.emit_event)
    seen: list[ToolResult] = []
    executor.add_post_hook(lambda _ctx, result: seen.append(result))
    try:
        result = await executor.invoke("agent-1", "browser", {"action": _ERROR_MARKER})
        await runtime.drain_events()
        captured = [event for subject, event in bus.published if subject == "system.events.tool_invoked"]
        assert len(captured) == 1, "the actual runtime never published TOOL_INVOKED"
        assert seen == [result] and seen[0] is result
        assert result.error is echoed
        completions = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(completions) == 1
        bus_data = captured[0]["data"]
        durable_data = completions[0]["data"]
        assert bus_data["error"] == ("network" if failed else None)
        for payload in (bus_data, durable_data):
            assert payload["is_error"] is failed
            assert payload["error_category"] == bus_data["error"]
            assert payload["tool_id"] == "browser"
        assert bus_data["invocation_id"] == completions[0]["correlation_id"]
        assert _ERROR_MARKER not in json.dumps(bus.published)
        assert _ERROR_MARKER not in json.dumps(completions)
        output = await _read_through_governed_reader(log)
        assert _ERROR_MARKER not in json.dumps(output)
    finally:
        await runtime.close_events()


@pytest.mark.parametrize(("error", "expected"), [
    (None, None), ("Pre-hook aborted invocation of run_command", "aborted_by_hook"),
    ("RuntimeError: permission denied for tool-1", "permission_denied"),
    ("Read timed out after 30s", "timeout"),
    ("FileNotFoundError: no such file or directory", "not_found"),
    ("Rate limit exceeded, retry in 60s", "rate_limited"),
    ("Connection reset by peer", "network"), ("invalid argument 'depth'", "invalid_params"),
    ("\U0001f600 nothing recognisable here", "other"), (12345, "other"),
])
def test_error_categories_are_a_closed_vocabulary(error: Any, expected: Any) -> None:
    category = classify_tool_error(error)
    assert category == expected
    assert category is None or category in ERROR_CATEGORIES


def test_error_category_never_carries_a_byte_of_the_error() -> None:
    for category in ERROR_CATEGORIES:
        assert classify_tool_error(f"{_ERROR_MARKER} {category}") in ERROR_CATEGORIES
    assert classify_tool_error(_ERROR_MARKER * 10_000) == "other"


def test_wiring_is_inert_without_an_event_log() -> None:
    executor = ToolExecutor(registry=_FakeRegistry())
    assert wire_tool_invocation_hooks(executor, emit_fn=lambda *_: None) is False
    assert executor.hook_count == 1
    durable_only = ToolExecutor(registry=_FakeRegistry())
    assert wire_durable_tool_records(durable_only, event_log=None) is False
    assert durable_only.hook_count == 0


def test_wiring_adds_the_pair_when_an_event_log_exists() -> None:
    executor = ToolExecutor(registry=_FakeRegistry())
    assert wire_tool_invocation_hooks(executor, emit_fn=lambda *_: None, event_log=object()) is True
    assert executor.hook_count == 4


async def test_a_blocked_call_emits_no_live_tool_invoked(open_log: _LogFactory) -> None:
    log = await open_log()
    emitted: list[Any] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    wire_tool_invocation_hooks(executor, emit_fn=lambda event, _payload: emitted.append(event), event_log=log)
    executor.add_pre_hook(lambda _ctx: False)
    result = await executor.invoke("agent-3", "run_command", {"command": "rm -rf /"})
    assert result.error is not None
    assert EventType.TOOL_INVOKED not in emitted
    assert len(await _rows(log, EventType.TOOL_STARTED.value)) == 1
    assert len(await _rows(log, EventType.TOOL_INVOKED.value)) == 1


async def test_durable_completion_survives_a_broken_live_emitter(open_log: _LogFactory) -> None:
    log = await open_log()

    def _broken(_event: Any, _payload: dict[str, Any]) -> None:
        raise RuntimeError("the bus is down " + _ERROR_MARKER)

    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    executor.add_pre_hook(make_start_hook(emit_fn=_broken, event_log=log))
    executor.add_post_hook(make_audit_hook(_broken, event_log=log))
    result = await executor.invoke("agent-1", "read_file", {"path": "a"})
    assert result.error is None and len(registry.calls) == 1
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]


async def test_agentic_loop_tool_call_reaches_the_durable_start_record(open_log: _LogFactory) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    log = await open_log()
    executor = ToolExecutor(registry=_FakeRegistry())
    executor.add_pre_hook(make_start_hook(event_log=log))
    loop = AgenticLoop(llm_client=object(), tool_executor=executor)
    caller_context = {"agent_id": "agent-9", "thread_id": "thread-3"}
    await loop._execute_one_tool(
        ToolUseBlock(tool_call=ToolCallRequest(id="c1", name="read_file", arguments={"path": "a"})),
        agent_id="agent-9", iteration=4, context=caller_context,
    )
    data = (await _rows(log, EventType.TOOL_STARTED.value))[0]["data"]
    assert data["tool_id"] == "read_file"
    assert data["thread_id"] == "thread-3"
    assert data["iteration"] == 4
    assert "iteration" not in caller_context


class _DispatchTool:
    def __init__(
        self, tool_id: str, *, entered: asyncio.Event, hang: bool,
        on_invoke: Callable[[], Awaitable[None]] | None = None,
        error: str | None = None,
    ) -> None:
        self._tid = tool_id
        self.entered = entered
        self._hang = hang
        self._on_invoke = on_invoke
        self._error = error
        self.calls = 0
        self.contexts: list[dict[str, Any]] = []

    @property
    def tool_id(self) -> str:
        return self._tid

    @property
    def name(self) -> str:
        return self._tid

    @property
    def tool_type(self) -> Any:
        from probos.tools.protocol import ToolType

        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"Dispatch-path tool {self._tid}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        self.contexts.append(dict(context or {}))
        if self._on_invoke is not None:
            await self._on_invoke()
        self.entered.set()
        if self._hang:
            await asyncio.Event().wait()
        return ToolResult(output="ok", error=self._error)


class _DispatchLLM:
    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id
        self.calls = 0

    async def complete(self, req: Any, **_kwargs: Any) -> Any:
        from types import SimpleNamespace

        from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

        self.calls += 1
        if self.calls == 1:
            block = ToolUseBlock(tool_call=ToolCallRequest(name=self._tool_id, arguments={}))
            return SimpleNamespace(content_blocks=[block], content="", tokens_used=1)
        return SimpleNamespace(content_blocks=[], content="done", tokens_used=1)


def _dispatch_runtime(*, registry: Any, event_log: Any, perm_store: Any = None) -> Any:
    from types import SimpleNamespace

    from probos.tools.permissions import ToolPermissionStore

    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        tool_registry=registry, tool_permission_store=perm_store or ToolPermissionStore(),
        capability_gap_driver=None, intent_bus=None, attachment_store=None,
        emit_event=None, event_log=event_log,
    )


async def _run_dispatch(*, log: Any, hang: bool) -> tuple[asyncio.Task[Any], _DispatchTool]:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.tools.registry import ToolRegistry

    entered = asyncio.Event()
    tool = _DispatchTool("dispatch_probe", entered=entered, hang=hang)
    registry = ToolRegistry()
    registry.register(tool, provider="test")
    task = asyncio.create_task(WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
        agent_id="counselor-001", instructions="Test instructions.", task_text="use the probe",
        runtime=_dispatch_runtime(registry=registry, event_log=log),
        department="counseling", rank="ensign", thread_id="thread-bf731",
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
    except BaseException:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    return task, tool


async def test_dispatch_run_cancelled_mid_tool_leaves_a_durable_unpaired_start(open_log: _LogFactory) -> None:
    log = await open_log()
    task, tool = await _run_dispatch(log=log, hang=True)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await log.stop()
    restarted = await open_log()
    starts = await _rows(restarted, EventType.TOOL_STARTED.value)
    completions = await _rows(restarted, EventType.TOOL_INVOKED.value)
    assert tool.entered.is_set()
    assert len(starts) == 1
    assert starts[0]["detail"] == "dispatch_probe"
    assert starts[0]["agent_id"] == "counselor-001"
    assert starts[0]["data"]["thread_id"] == "thread-bf731"
    assert starts[0]["correlation_id"]
    assert completions == []
    assert {row["correlation_id"] for row in starts} - {row["correlation_id"] for row in completions} == {
        starts[0]["correlation_id"],
    }


async def test_dispatch_run_that_completes_leaves_no_unpaired_start(open_log: _LogFactory) -> None:
    log = await open_log()
    task, tool = await _run_dispatch(log=log, hang=False)
    await asyncio.wait_for(task, timeout=10)
    await log.stop()
    restarted = await open_log()
    starts = await _rows(restarted, EventType.TOOL_STARTED.value)
    completions = await _rows(restarted, EventType.TOOL_INVOKED.value)
    assert tool.entered.is_set()
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]


async def test_dispatch_run_denied_tool_closes_its_own_pairing(open_log: _LogFactory) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.tools.permissions import ToolPermissionStore
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    entered = asyncio.Event()
    tool = _DispatchTool("dispatch_probe", entered=entered, hang=False)
    registry = ToolRegistry()
    registry.register(tool, provider="test", default_permissions={"captain": "full"})
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    outcome = await WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
        agent_id="counselor-001", instructions="Test instructions.", task_text="use the probe",
        runtime=_dispatch_runtime(registry=registry, event_log=log, perm_store=perm_store),
        department="counseling", rank="ensign",
    )
    assert outcome.denied_tools == ["dispatch_probe"]
    assert not entered.is_set()
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]


@pytest.mark.parametrize("durable", [False, True])
async def test_dispatch_executor_preserves_hook_set_and_bus_frequency(
    open_log: _LogFactory, monkeypatch: pytest.MonkeyPatch, durable: bool,
) -> None:
    import probos.cognitive.agentic_dispatch as dispatch_module
    from probos.tools.registry import ToolRegistry

    log = await open_log() if durable else None
    seen: list[int] = []
    emitted: list[Any] = []
    entered = asyncio.Event()
    registry = ToolRegistry()
    registry.register(_DispatchTool("dispatch_probe", entered=entered, hang=False), provider="test")
    original = dispatch_module.DispatchToolExecutor

    class _Counting(original):
        async def invoke(self, *args: Any, **kwargs: Any) -> ToolResult:
            seen.append(self.hook_count)
            return await super().invoke(*args, **kwargs)

    monkeypatch.setattr(dispatch_module, "DispatchToolExecutor", _Counting)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.emit_event = lambda event, _payload: emitted.append(event)
    await dispatch_module.WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
        agent_id="counselor-001", instructions="Test instructions.", task_text="use the probe",
        runtime=runtime, department="counseling", rank="ensign",
    )
    assert entered.is_set()
    assert seen == ([4] if durable else [1])
    lifecycle = {EventType.TOOL_STARTED.value, EventType.TOOL_INVOKED.value, EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value}
    assert all(getattr(event, "value", event) not in lifecycle for event in emitted)


class _RepresentationTrap(BaseException):
    pass


@pytest.fixture(params=["hash", "equality"])
def hostile_parameters(request: pytest.FixtureRequest) -> Iterator[tuple[dict[Any, Any], list[Any], list[str]]]:
    state: dict[str, Any] = {"armed": False, "calls": []}

    def _trap(name: str) -> None:
        if state["armed"]:
            state["calls"].append(name)
            raise _RepresentationTrap(name)

    class _Metaclass(type):
        def __hash__(cls) -> int:
            if request.param == "hash":
                _trap("metaclass hash")
            elif state["armed"]:
                state["calls"].append("metaclass hash")
            return hash(str)

        def __eq__(cls, other: object) -> bool:
            _trap("metaclass equality")
            return cls is other

    class _Opaque(metaclass=_Metaclass):
        def __hash__(self) -> int:
            _trap("instance hash")
            return 17

        def __eq__(self, other: object) -> bool:
            _trap("instance equality")
            return self is other

        def __len__(self) -> int:
            _trap("instance length")
            return 0

        def __str__(self) -> str:
            _trap("instance string")
            return _SECRET

        def __repr__(self) -> str:
            _trap("instance repr")
            return _SECRET

    class _String(str, metaclass=_Metaclass):
        def __hash__(self) -> int:
            _trap("string hash")
            return str.__hash__(self)

        def __eq__(self, other: object) -> bool:
            _trap("string equality")
            return str.__eq__(self, other)

        def __len__(self) -> int:
            _trap("string length")
            return str.__len__(self)

        def __str__(self) -> str:
            _trap("string coercion")
            return _SECRET

        def __repr__(self) -> str:
            _trap("string repr")
            return _SECRET

    class _List(list, metaclass=_Metaclass):
        def __len__(self) -> int:
            _trap("list length")
            return list.__len__(self)

        def __iter__(self) -> Iterator[Any]:
            _trap("list iteration")
            return list.__iter__(self)

    class _Dict(dict, metaclass=_Metaclass):
        def items(self) -> Any:
            _trap("dict items")
            return dict.items(self)

        def __len__(self) -> int:
            _trap("dict length")
            return dict.__len__(self)

    opaque = _Opaque()
    string = _String(_SECRET)
    opaque_list = _List([_SECRET])
    opaque_dict = _Dict({"password": _SECRET})
    objects = [opaque, string, opaque_list, opaque_dict, _Opaque, _String, str]
    params = {
        "path": opaque, "values": [opaque_list, opaque_dict, _Opaque],
        "data": string, opaque: _SECRET, _Opaque: 1,
    }
    state["calls"].clear()
    state["armed"] = True
    try:
        yield params, objects, state["calls"]
    finally:
        state["armed"] = False


def test_digest_uses_identity_not_metaclass_hash_or_equality(hostile_parameters: Any) -> None:
    params, objects, calls = hostile_parameters
    digest = digest_params(params)
    assert digest["key_count"] == 5
    assert digest.get("degraded") is not True
    for opaque in objects:
        shape = digest_params(opaque)
        assert shape["non_dict"] == {"type": "other", "size": None}
    assert _SECRET not in json.dumps(digest)
    assert calls == [], "representation invoked caller code"


async def test_hostile_metaclass_parameters_reach_a_committed_start_and_registry(
    open_log: _LogFactory, hostile_parameters: Any,
) -> None:
    params, _objects, calls = hostile_parameters
    log = await open_log()
    observed: list[dict[str, Any]] = []

    async def _inside_registry() -> None:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))

    registry = _FakeRegistry(on_invoke=_inside_registry)
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    result = await executor.invoke("agent-1", "read_file", params)

    assert result.error is None
    assert len(registry.calls) == 1 and registry.calls[0][2] is params
    assert len(observed) == 1, "a hostile object suppressed the committed start"
    assert observed[0]["correlation_id"]
    assert len(await _rows(log, EventType.TOOL_INVOKED.value)) == 1
    assert calls == []


@pytest.mark.parametrize(("value", "label", "size"), [
    (None, "null", None), (True, "bool", None), (1, "int", None),
    (1.5, "float", None), ("", "str", None), (b"", "bytes", None),
    (bytearray(), "bytes", None), ([], "list", 0), ((), "list", 0),
    (set(), "set", 0), (frozenset(), "set", 0), ({}, "dict", 0),
])
def test_digest_exact_builtin_vocabulary(value: Any, label: str, size: int | None) -> None:
    shape = digest_params({"data": value})["fields"][0]["value"]
    assert shape["type"] == label
    assert shape["size"] == size


def test_digest_cycles_branching_and_empty_inputs_remain_bounded() -> None:
    cyclic_list: list[Any] = []
    cyclic_list.append(cyclic_list)
    cyclic_dict: dict[str, Any] = {}
    cyclic_dict["data"] = cyclic_dict
    branching: Any = [_SECRET] * 8
    for _ in range(30):
        branching = [branching] * 8
    inputs = [None, {}, cyclic_list, cyclic_dict, {f"key-{index}": branching for index in range(1000)}]
    for params in inputs:
        digest = digest_params(params)
        assert digest.get("degraded") is not True
        assert len(json.dumps(digest).encode("utf-8")) <= 2048
        assert _SECRET not in json.dumps(digest)
    assert digest_params({})["fields"] == []
    assert digest_params({})["key_count"] == 0


@pytest.mark.parametrize("oversized", [False, True])
async def test_unknown_tool_identity_is_keyed_and_bounded_at_all_retention_sinks(
    open_log: _LogFactory, caplog: pytest.LogCaptureFixture, oversized: bool,
) -> None:
    from probos.tools.registry import ToolRegistry

    unknown = "provider_valid_secret_name"
    if oversized:
        unknown += "x" * (20027 - len(unknown))
        assert len(unknown) == 20027
    else:
        assert unknown.replace("_", "").isalnum() and len(unknown) < 64
    log = await open_log()
    registry = ToolRegistry()
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor = ToolExecutor(registry=registry)
    emitter = lambda event, payload: emitted.append((event, payload))
    executor.add_pre_hook(make_start_hook(emitter, event_log=log, max_records_per_run=1))
    executor.add_post_hook(make_audit_hook(emitter, event_log=log))
    executor.add_terminal_hook(make_audit_hook(event_log=log))
    expected = tool_record_identity(unknown, catalog=registry)

    with tool_recording_scope():
        first = await executor.invoke("agent-1", unknown, {})
        second = await executor.invoke("agent-1", unknown, {})

    assert first.error == second.error == f"Tool '{unknown}' not found"
    rows = await log.query(category="tool", limit=100)
    assert len(rows) == 3
    assert {row["event"] for row in rows} == {
        EventType.TOOL_STARTED.value, EventType.TOOL_INVOKED.value,
        EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value,
    }
    assert expected.startswith("unknown-tool:")
    assert len(expected.encode("utf-8")) <= 128
    for row in rows:
        assert row["detail"] == row["data"]["tool_id"] == expected
        assert len(json.dumps(row).encode("utf-8")) <= 4096
    assert emitted
    assert all(payload["tool_id"] == expected for _event, payload in emitted)
    assert "provider_valid_secret_name" not in json.dumps(rows)
    assert "provider_valid_secret_name" not in json.dumps(emitted)
    assert "provider_valid_secret_name" not in caplog.text
    completions = [payload for event, payload in emitted if event is EventType.TOOL_INVOKED]
    assert completions and all(payload["error"] == "not_found" for payload in completions)


@pytest.mark.parametrize("enabled", [False, True])
async def test_verified_alias_keeps_canonical_identity_and_registry_policy(
    open_log: _LogFactory, enabled: bool,
) -> None:
    from probos.cognitive.swe_harness.tool_call import llm_function_name
    from probos.tools.registry import ToolPermissionDenied, ToolRegistry

    log = await open_log()
    canonical = "mcp:server:probe"
    alias = llm_function_name(canonical)
    assert alias != canonical
    tool = _DispatchTool(canonical, entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(tool, enabled=enabled)
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    if enabled:
        result = await executor.invoke("agent-1", alias, {})
        assert result.error is None and tool.calls == 1
    else:
        with pytest.raises(ToolPermissionDenied):
            await executor.invoke("agent-1", alias, {})
        assert tool.calls == 0
    rows = await log.query(category="tool", limit=100)
    assert len(rows) == 2
    assert all(row["detail"] == row["data"]["tool_id"] == canonical for row in rows)
    assert tool_record_identity(canonical, catalog=registry) == canonical
    assert tool_record_identity(alias, catalog=registry) == canonical


async def test_exact_id_alias_ambiguity_invokes_neither_tool(open_log: _LogFactory) -> None:
    from probos.cognitive.swe_harness.tool_call import llm_function_name
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    canonical = "mcp:server:probe"
    alias = llm_function_name(canonical)
    registry = ToolRegistry()
    tools = [_DispatchTool(name, entered=asyncio.Event(), hang=False) for name in (canonical, alias)]
    for tool in tools:
        registry.register(tool)
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    result = await executor.invoke("agent-1", alias, {})
    assert result.error is not None and "ambiguous" in result.error
    assert all(tool.calls == 0 for tool in tools)
    assert tool_record_identity(alias, catalog=registry).startswith("unknown-tool:")
    assert await log.query(category="tool", limit=100) == []


def test_identity_process_secret_separates_unknown_names_and_key_hashes(monkeypatch: pytest.MonkeyPatch) -> None:
    import probos.tools.executor as executor_module

    unknown = "short_provider_valid_secret"
    monkeypatch.setattr(executor_module, "_DIGEST_KEY_SECRET", b"a" * 32)
    first = tool_record_identity(unknown)
    first_key = digest_params({unknown: 1})["fields"][0]["key_hash"]
    assert first == tool_record_identity(unknown)
    assert first != tool_record_identity(unknown + "_other")
    monkeypatch.setattr(executor_module, "_DIGEST_KEY_SECRET", b"b" * 32)
    assert first != tool_record_identity(unknown)
    assert first_key != digest_params({unknown: 1})["fields"][0]["key_hash"]


@pytest.mark.parametrize("catalog_mode", ["absent", "missing", "failed", "wrong_shape"])
def test_standalone_identity_requires_a_working_trusted_catalog(catalog_mode: str) -> None:
    class _FailedCatalog:
        def list_ids(self) -> list[str]:
            raise RuntimeError(_SECRET)

    class _WrongCatalog:
        def list_ids(self) -> Any:
            return {"read_file": True}

    catalogs = {"absent": None, "missing": object(), "failed": _FailedCatalog(), "wrong_shape": _WrongCatalog()}
    identity = tool_record_identity("read_file", catalog=catalogs[catalog_mode])
    assert identity == tool_record_identity("read_file")
    assert identity.startswith("unknown-tool:")
    emitted: list[dict[str, Any]] = []
    hook = make_audit_hook(lambda _event, payload: emitted.append(payload))
    assert hook({
        "agent_id": "agent-1", "tool_id": "read_file", "known": True,
        "registered": True, "tool_id_known": True, "invocation": None,
    }, ToolResult()) is None
    assert len(emitted) == 1 and emitted[0]["tool_id"] == identity


def test_standalone_audit_accepts_explicit_catalog_and_empty_context() -> None:
    emitted: list[dict[str, Any]] = []
    hook = make_audit_hook(lambda _event, payload: emitted.append(payload), catalog=_FakeRegistry())
    hook({"agent_id": "agent-1", "tool_id": "read_file"}, ToolResult())
    hook({}, ToolResult())
    assert emitted[0]["tool_id"] == "read_file"
    assert emitted[1]["tool_id"].startswith("unknown-tool:")
    assert emitted[1]["agent_id"] is None


def test_identity_does_not_coerce_hostile_subclasses(hostile_parameters: Any) -> None:
    _params, objects, calls = hostile_parameters
    for opaque in objects:
        identity = tool_record_identity(opaque, catalog=_FakeRegistry())
        assert identity.startswith("unknown-tool:")
        assert len(identity.encode("utf-8")) <= 128
        assert classify_tool_error(opaque) == "other"
    assert calls == []


async def test_oversized_verified_identity_and_branching_records_are_bounded(open_log: _LogFactory) -> None:
    from probos.cognitive.swe_harness.tool_call import llm_function_name
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    canonical = "registered_" + "\u00e9" * 128
    tool = _DispatchTool(canonical, entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(tool)
    identity = tool_record_identity(canonical, catalog=registry)
    assert len(canonical.encode("utf-8")) > 128
    assert identity.startswith("registered-tool:opaque:")
    assert identity == tool_record_identity(llm_function_name(canonical), catalog=registry)
    assert len(identity.encode("utf-8")) <= 128
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    branching: Any = [_SECRET] * 8
    for _ in range(10):
        branching = {"data": [branching] * 8}
    result = await executor.invoke("\x01" * 1000, canonical, {f"key-{index}": branching for index in range(256)}, context={
        "thread_id": "\x02" * 1000, "_crew_work_item_id": "\x03" * 1000,
        "_agentic_run_id": "\x04" * 1000, "iteration": 10**1000,
    })
    assert result.error is None and tool.calls == 1
    rows = await log.query(category="tool", limit=100)
    assert len(rows) == 2
    assert all(row["detail"] == row["data"]["tool_id"] == identity for row in rows)
    assert all(len(json.dumps(row).encode("utf-8")) <= 4096 for row in rows)
    start = next(row for row in rows if row["event"] == EventType.TOOL_STARTED.value)
    assert len(json.dumps(start["data"]["params"]).encode("utf-8")) <= 2048
    assert start["data"]["iteration"] is None
    assert _SECRET not in json.dumps(rows)


@pytest.mark.parametrize("failure", ["none", "raise"])
async def test_unacknowledged_start_cannot_create_completion_after_sink_recovers(
    open_log: _LogFactory, caplog: pytest.LogCaptureFixture, failure: str,
) -> None:
    log = await open_log()

    class _RecoveringSink:
        def __init__(self) -> None:
            self.available = False
            self.attempts: list[str] = []

        async def log(self, **kwargs: Any) -> int | None:
            self.attempts.append(kwargs["event"])
            if not self.available:
                if failure == "raise":
                    raise OSError(_ERROR_MARKER)
                return None
            return await log.log(**kwargs)

    sink = _RecoveringSink()

    async def _recover() -> None:
        sink.available = True

    registry = _FakeRegistry(on_invoke=_recover)
    executor = ToolExecutor(registry=registry)
    _paired(executor, sink)
    first = await executor.invoke("agent-1", "read_file", {})
    assert first.error is None and len(registry.calls) == 1
    assert sink.available is True
    assert sink.attempts == [EventType.TOOL_STARTED.value]
    assert await log.query(category="tool", limit=100) == []
    second = await executor.invoke("agent-1", "read_file", {})
    assert second.error is None and len(registry.calls) == 2
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]
    assert _ERROR_MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records if record.name == "probos.tools.executor")


async def test_unavailable_real_event_log_cannot_recover_into_completion_only(open_log: _LogFactory) -> None:
    log = await open_log()
    await log.stop()

    async def _recover() -> None:
        await log.start()

    registry = _FakeRegistry(on_invoke=_recover)
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    result = await executor.invoke("agent-1", "read_file", {})
    assert result.error is None and len(registry.calls) == 1
    assert await log.query(category="tool", limit=100) == []


async def test_completion_failure_leaves_start_and_preserves_result(
    open_log: _LogFactory, caplog: pytest.LogCaptureFixture,
) -> None:
    log = await open_log()

    class _FailedCompletion:
        async def log(self, **kwargs: Any) -> int | None:
            if kwargs["event"] == EventType.TOOL_INVOKED.value:
                raise OSError(_ERROR_MARKER)
            return await log.log(**kwargs)

    seen: list[ToolResult] = []
    executor = ToolExecutor(registry=_FakeRegistry())
    _paired(executor, _FailedCompletion())
    executor.add_post_hook(lambda _ctx, result: seen.append(result))
    result = await executor.invoke("agent-1", "read_file", {})
    assert seen[0] is result and result.error is None
    assert len(await _rows(log, EventType.TOOL_STARTED.value)) == 1
    assert await _rows(log, EventType.TOOL_INVOKED.value) == []
    await log.stop()
    reopened = await open_log()
    assert len(await _rows(reopened, EventType.TOOL_STARTED.value)) == 1
    assert await _rows(reopened, EventType.TOOL_INVOKED.value) == []
    assert _ERROR_MARKER not in caplog.text


def test_nested_recording_scopes_restore_parent_budget_and_isolate_fallback() -> None:
    budget = ToolRecordBudget(max_per_run=2)
    with tool_recording_scope():
        assert budget.spend("parent") == (True, False)
        with tool_recording_scope():
            assert budget.spend("parent") == (True, False)
            assert budget.spend("parent") == (True, False)
            assert budget.spend("parent") == (False, True)
        assert budget.spend("parent") == (True, False)
        assert budget.spend("parent") == (False, True)
    assert budget.spend("parent") == (True, False)


def test_recording_scope_restores_on_exception_and_shares_stricter_cap() -> None:
    generous = ToolRecordBudget(max_per_run=5)
    strict = ToolRecordBudget(max_per_run=1)
    with pytest.raises(RuntimeError, match="scope exit"):
        with tool_recording_scope():
            assert generous.spend("run") == (True, False)
            assert strict.spend("run") == (False, True)
            assert generous.spend("run") == (False, False)
            assert generous.max_per_run == 1
            raise RuntimeError("scope exit")
    assert generous.spend("run") == (True, False)
    assert generous.max_per_run == 5


@pytest.mark.parametrize("limit", [0, 1, 3])
async def test_scoped_concurrent_spending_respects_pair_and_notice_cap(open_log: _LogFactory, limit: int) -> None:
    log = await open_log()
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    _paired(executor, log, max_records_per_run=limit)
    with tool_recording_scope():
        tasks = [asyncio.create_task(executor.invoke("agent-1", "read_file", {})) for _ in range(12)]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert len(results) == len(registry.calls) == 12
    rows = await log.query(category="tool", limit=100)
    starts = [row for row in rows if row["event"] == EventType.TOOL_STARTED.value]
    completions = [row for row in rows if row["event"] == EventType.TOOL_INVOKED.value]
    exhausted = [row for row in rows if row["event"] == EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value]
    assert len(starts) == len(completions) == limit
    assert len(exhausted) == 1 and len(rows) == 2 * limit + 1
    assert exhausted[0]["data"]["reason"] == ("disabled" if limit == 0 else "exhausted")
    assert {row["correlation_id"] for row in starts} == {row["correlation_id"] for row in completions}


async def test_active_exhausted_loop_is_not_readmitted_after_257_other_runs(open_log: _LogFactory) -> None:
    from types import SimpleNamespace

    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    log = await open_log()
    registry = _FakeRegistry()
    executor = ToolExecutor(registry=registry)
    _paired(executor, log, max_records_per_run=1)
    parked = asyncio.Event()
    resume = asyncio.Event()

    class _ParentLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, req: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 3:
                parked.set()
                await resume.wait()
            blocks = [] if self.calls > 3 else [ToolUseBlock(tool_call=ToolCallRequest(name="read_file", arguments={}))]
            return SimpleNamespace(content_blocks=blocks, content="done" if not blocks else "", tokens_used=1)

    parent = asyncio.create_task(AgenticLoop(llm_client=_ParentLLM(), tool_executor=executor).run(
        system_prompt="s", user_message="u", tools=[], context={"agent_id": "parent"},
    ))
    try:
        await asyncio.wait_for(parked.wait(), timeout=10)
        assert not parent.done()
        before = [row for row in await log.query(category="tool", limit=1000) if row["agent_id"] == "parent"]
        assert len(before) == 3
        assert sum(row["event"] == EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value for row in before) == 1
        for index in range(257):
            outcome = await AgenticLoop(llm_client=_DispatchLLM("read_file"), tool_executor=executor).run(
                system_prompt="s", user_message="u", tools=[], context={"agent_id": f"other-{index}"},
            )
            assert outcome.error == ""
        resume.set()
        await asyncio.wait_for(parent, timeout=10)
    finally:
        if not parent.done():
            parent.cancel()
        await asyncio.gather(parent, return_exceptions=True)
    rows = await log.query(category="tool", limit=1000)
    parent_rows = [row for row in rows if row["agent_id"] == "parent"]
    assert len([call for call in registry.calls if call[0] == "parent"]) == 3
    assert len(parent_rows) == 3
    assert len(rows) == 3 + 2 * 257


@pytest.mark.parametrize("invalid", [None, True, 1.5, "3", 2**64])
def test_budget_rejects_invalid_limits(invalid: Any) -> None:
    with pytest.raises(ValueError):
        ToolRecordBudget(max_per_run=invalid)


@pytest.mark.parametrize("invalid", [None, True, 0, -1])
def test_budget_rejects_invalid_fallback_capacity(invalid: Any) -> None:
    with pytest.raises(ValueError):
        ToolRecordBudget(max_per_run=1, max_tracked_runs=invalid)


def test_budget_missing_key_and_negative_cap_are_conservative() -> None:
    budget = ToolRecordBudget(max_per_run=-1)
    assert budget.spend(None) == (False, True)
    assert budget.spend("") == (False, False)


def _hard_kill_child(database: str, expected_source: str, handshake: Connection) -> None:
    """Test child deliberately has no EventLog.stop on its interrupted path."""
    import probos.substrate.event_log as event_log_module
    import probos.tools.executor as executor_module
    from probos.tools.registry import ToolRegistry

    source = Path(expected_source).resolve()
    assert Path(executor_module.__file__).resolve().is_relative_to(source)
    assert Path(event_log_module.__file__).resolve().is_relative_to(source)

    async def _run() -> None:
        log = EventLog(db_path=Path(database))
        await log.start()
        registry = ToolRegistry()
        control = _DispatchTool("completed_control", entered=asyncio.Event(), hang=False)
        registry.register(control)
        executor = ToolExecutor(registry=registry)
        _paired(executor, log)
        result = await executor.invoke("child-agent", "completed_control", {})
        assert result.error is None and control.calls == 1

        async def _entered_after_commit() -> None:
            reader = EventLog(db_path=Path(database))
            await reader.start()
            try:
                starts = await _rows(reader, EventType.TOOL_STARTED.value)
                completions = await _rows(reader, EventType.TOOL_INVOKED.value)
                started = [row for row in starts if row["detail"] == "hard_kill_probe"]
                assert len(started) == 1 and len(completions) == 1
                assert started[0]["correlation_id"]
                handshake.send({
                    "entered": True, "tool_id": "hard_kill_probe",
                    "invocation_id": started[0]["correlation_id"],
                    "source": str(source), "control_completed": True,
                })
            finally:
                await reader.stop()

        registry.register(_DispatchTool(
            "hard_kill_probe", entered=asyncio.Event(), hang=True,
            on_invoke=_entered_after_commit,
        ))
        await executor.invoke("child-agent", "hard_kill_probe", {}, context={
            "thread_id": "child-thread", "_crew_work_item_id": "child-work-item",
            "_agentic_run_id": "child-run", "iteration": 2,
        })
        raise AssertionError("the interrupted tool unexpectedly completed")

    asyncio.run(_run())


async def test_hard_killed_process_keeps_committed_start_and_completed_control(
    tmp_path: Path, open_log: _LogFactory,
) -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    source = Path(__file__).resolve().parents[1] / "src"
    child = context.Process(target=_hard_kill_child, args=(
        str(tmp_path / "hard-kill.db"), str(source), sender,
    ))
    started = False
    try:
        child.start()
        started = True
        sender.close()
        assert await asyncio.to_thread(receiver.poll, 30), "child never acknowledged committed tool entry"
        entry = receiver.recv()
        assert entry["entered"] is True and entry["control_completed"] is True
        assert Path(entry["source"]).resolve() == source.resolve()
        assert child.is_alive(), "the child exited before the forced termination"
        reader = await open_log("hard-kill.db")
        before = await reader.query(category="tool", limit=100)
        assert len(before) == 3
        target = [row for row in before if row["detail"] == "hard_kill_probe"]
        assert len(target) == 1
        assert target[0]["event"] == EventType.TOOL_STARTED.value
        assert target[0]["correlation_id"] == entry["invocation_id"]
        child.kill()
        await asyncio.to_thread(child.join, 10)
        assert not child.is_alive() and child.exitcode is not None
        await reader.stop()
        reopened = await open_log("hard-kill.db")
        starts = await _rows(reopened, EventType.TOOL_STARTED.value)
        completions = await _rows(reopened, EventType.TOOL_INVOKED.value)
        assert len(starts) == 2 and len(completions) == 1
        unpaired = {row["correlation_id"] for row in starts} - {row["correlation_id"] for row in completions}
        assert unpaired == {entry["invocation_id"]}
        incomplete = next(row for row in starts if row["correlation_id"] == entry["invocation_id"])
        assert incomplete["detail"] == incomplete["data"]["tool_id"] == "hard_kill_probe"
        assert incomplete["data"]["work_item_id"] == "child-work-item"
        assert incomplete["data"]["run_id"] == "child-run"
        assert completions[0]["detail"] == "completed_control"
        assert await reopened.verify_chain() == (True, None)
    finally:
        if started:
            if child.is_alive():
                child.kill()
            await asyncio.to_thread(child.join, 10)
            assert not child.is_alive(), "test child could not be reaped"
            child.close()
        receiver.close()
        sender.close()


class _BatchLLM:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.calls = 0

    async def complete(self, request: Any, **kwargs: Any) -> Any:
        from types import SimpleNamespace

        from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

        self.calls += 1
        blocks = [] if self.calls > 1 else [
            ToolUseBlock(tool_call=ToolCallRequest(id=f"call-{index}", name=name, arguments={}))
            for index, name in enumerate(self.names)
        ]
        return SimpleNamespace(content_blocks=blocks, content="done" if not blocks else "", tokens_used=1)


@pytest.mark.parametrize("separate_connections", [False, True])
async def test_overlapping_parallel_bodies_keep_durable_chain_and_pairing(
    open_log: _LogFactory, separate_connections: bool,
) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.tools.registry import ToolRegistry

    first_log = await open_log()
    second_log = await open_log() if separate_connections else first_log
    registry = ToolRegistry()
    both_entered = asyncio.Event()
    entered: set[str] = set()
    active = 0
    peak = 0
    independently_observed: list[str] = []

    async def _body(name: str) -> None:
        nonlocal active, peak
        reader = await open_log()
        starts = await _rows(reader, EventType.TOOL_STARTED.value)
        assert any(row["detail"] == name and row["correlation_id"] for row in starts)
        independently_observed.append(name)
        active += 1
        peak = max(peak, active)
        entered.add(name)
        if len(entered) == 2:
            both_entered.set()
        try:
            await asyncio.wait_for(both_entered.wait(), timeout=10)
        finally:
            active -= 1

    names = ["http_fetch", "event_log_query"]
    tools = [
        _DispatchTool(name, entered=asyncio.Event(), hang=False, on_invoke=lambda name=name: _body(name))
        for name in names
    ]
    for tool in tools:
        registry.register(tool)
    first_executor = ToolExecutor(registry=registry)
    _paired(first_executor, first_log)
    if separate_connections:
        second_executor = ToolExecutor(registry=registry)
        _paired(second_executor, second_log)
        with tool_recording_scope():
            tasks = [
                asyncio.create_task(executor.invoke("parallel-agent", name, {}))
                for executor, name in zip((first_executor, second_executor), names)
            ]
            try:
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
                assert all(result.error is None for result in results)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    else:
        result = await asyncio.wait_for(AgenticLoop(
            llm_client=_BatchLLM(names), tool_executor=first_executor,
            parallel_tool_calls_enabled=True, max_parallel_tool_calls=2,
        ).run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "parallel-agent"}), timeout=15)
        assert result.error == ""
        assert len(result.tool_calls) == len(result.tool_results) == 2
        assert all(not tool_result.is_error for tool_result in result.tool_results)
    assert peak == 2, "tool bodies were serialized; the chain check did not discriminate"
    assert entered == set(names) and sorted(independently_observed) == sorted(names)
    assert all(tool.calls == 1 for tool in tools)
    starts = await _rows(first_log, EventType.TOOL_STARTED.value)
    completions = await _rows(first_log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 2
    assert len({row["correlation_id"] for row in starts}) == 2
    assert {row["correlation_id"] for row in starts} == {row["correlation_id"] for row in completions}
    for start in starts:
        completion = next(row for row in completions if row["correlation_id"] == start["correlation_id"])
        assert start["detail"] == completion["detail"]
        assert completion["parent_event_id"] == start["id"]
    assert await first_log.verify_chain() == (True, None)
    assert await second_log.verify_chain() == (True, None)
    await first_log.stop()
    if separate_connections:
        await second_log.stop()
    reopened = await open_log()
    assert len(await reopened.query(category="tool", limit=100)) == 4
    assert await reopened.verify_chain() == (True, None)


@pytest.mark.parametrize("outcome", ["success", "error", "denied", "loto", "cancelled"])
async def test_native_harness_real_registry_records_terminal_and_interrupted_attempts(
    open_log: _LogFactory, tmp_path: Path, outcome: str,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.builder import BuildSpec
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_native_swe_harness
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    observed: list[dict[str, Any]] = []

    async def _inside_tool() -> None:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed) == 1 and observed[0]["detail"] == "read_file"

    entered = asyncio.Event()
    tool = _DispatchTool(
        "read_file", entered=entered, hang=outcome == "cancelled", on_invoke=_inside_tool,
        error="network failure " + _ERROR_MARKER if outcome == "error" else None,
    )
    registry = ToolRegistry()
    emitted: list[Any] = []
    config = SystemConfig()
    runtime = SimpleNamespace(
        emit_event=lambda event, _payload: emitted.append(event),
        tool_registry=registry, llm_client=_DispatchLLM("read_file"), config=config,
    )
    executor = ToolExecutor(registry=registry)
    wire_tool_invocation_hooks(executor, event_log=log, emit_fn=runtime.emit_event)
    assert _wire_native_swe_harness(runtime=runtime, config=config, tool_executor=executor)
    registry.register(tool, concurrency="exclusive", default_permissions={"captain": "full"} if outcome == "denied" else {})
    if outcome == "loto":
        assert registry.acquire_lock("read_file", "other-agent", reason="test lock")
    harness = runtime.native_builder_harness
    task = asyncio.create_task(harness.run_build(BuildSpec(title="probe", description="probe"), work_dir=str(tmp_path)))
    try:
        if outcome == "cancelled":
            await asyncio.wait_for(entered.wait(), timeout=10)
            assert len(observed) == 1 and not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, timeout=10)
            assert result["builder_source"] == "native_harness"
            assert result["metadata"]["tools_used"] == ["read_file"]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert tool.calls == (0 if outcome in {"denied", "loto"} else 1)
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == 1
    data = starts[0]["data"]
    assert data["agent_id"] == "swe" and data["run_id"]
    assert data["thread_id"] is None and data["work_item_id"] is None
    assert data["iteration"] == 1
    if outcome == "cancelled":
        assert completions == []
    else:
        assert len(completions) == 1
        assert completions[0]["correlation_id"] == starts[0]["correlation_id"]
        for key in ("agent_id", "tool_id", "thread_id", "work_item_id", "run_id", "iteration"):
            assert completions[0]["data"][key] == data[key]
        assert completions[0]["data"]["is_error"] is (outcome != "success")
        expected = {"success": None, "error": "network", "denied": "permission_denied", "loto": "other"}
        assert completions[0]["data"]["error_category"] == expected[outcome]
    assert _ERROR_MARKER not in json.dumps(starts + completions)


@pytest_asyncio.fixture
async def conversation_stores(tmp_path: Path) -> AsyncIterator[tuple[Any, Any]]:
    from probos.threads import ChatThreadStore
    from probos.workforce import WorkItemStore

    work_items = WorkItemStore(db_path=str(tmp_path / "work-items.db"))
    await work_items.start()
    threads = ChatThreadStore(tmp_path / "threads.db")
    try:
        yield work_items, threads
    finally:
        await work_items.stop()


def _conversational_agent(runtime: Any, llm: Any) -> Any:
    from types import SimpleNamespace

    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = SimpleNamespace(
        _runtime=runtime, _llm_client=llm, id="conversation-agent",
        callsign="Probe", agent_type="counselor", department="science",
        rank="lieutenant", _promoted_turn_tasks=set(),
    )
    agent._conversational_agentic_will_run = (
        lambda observation: CognitiveAgent._conversational_agentic_will_run(agent, observation)
    )
    return agent


async def _conversation(agent: Any, thread_id: str) -> str | None:
    from probos.cognitive.cognitive_agent import CognitiveAgent

    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent, {
            "intent": "direct_message", "thread_id": thread_id,
            "params": {"author_id": "captain", "captain_message": "use the inert probes"},
        },
        system_prompt="Test instructions.", user_message="Use the inert probes.",
    )


async def _drain_owned_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    async def _drain() -> None:
        while tasks:
            await asyncio.gather(*tuple(tasks))
            await asyncio.sleep(0)

    await asyncio.wait_for(_drain(), timeout=15)


async def _cancel_owned_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    pending = tuple(tasks)
    for task in pending:
        if not task.done():
            task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.parametrize("tool_error", [None, "network failure " + _ERROR_MARKER])
async def test_conversational_agent_uses_real_dispatch_registry_and_durable_log(
    open_log: _LogFactory, conversation_stores: Any, tool_error: str | None,
) -> None:
    from probos.config import DmAgenticConfig
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Probe", participants=["conversation-agent"])
    registry = ToolRegistry()
    observed: list[dict[str, Any]] = []

    async def _inside_tool() -> None:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed) == 1

    tool = _DispatchTool(
        "dispatch_probe", entered=asyncio.Event(), hang=False,
        on_invoke=_inside_tool, error=tool_error,
    )
    registry.register(tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.config.dm_agentic = DmAgenticConfig(enabled=True)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    agent = _conversational_agent(runtime, _DispatchLLM("dispatch_probe"))
    try:
        result = await asyncio.wait_for(_conversation(agent, thread.id), timeout=15)
        assert result == "done"
        assert tool.calls == 1 and len(observed) == 1
        assert not agent._promoted_turn_tasks
        assert await store.list_work_items() == []
        starts = await _rows(log, EventType.TOOL_STARTED.value)
        completions = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(starts) == len(completions) == 1
        assert starts[0]["correlation_id"] == completions[0]["correlation_id"]
        assert starts[0]["data"]["agent_id"] == agent.id
        assert starts[0]["data"]["thread_id"] == thread.id
        assert starts[0]["data"]["run_id"]
        assert starts[0]["data"]["work_item_id"] is None
        assert completions[0]["data"]["is_error"] is (tool_error is not None)
        assert _ERROR_MARKER not in json.dumps(starts + completions)
    finally:
        await _cancel_owned_tasks(agent._promoted_turn_tasks)


async def test_crew_outer_loop_passes_real_work_item_provenance_to_dispatch(
    open_log: _LogFactory, conversation_stores: Any,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.crew_executor import CrewTaskExecutor
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Crew probe", participants=["crew-agent"])
    parent = await store.create_work_item(
        title="Parent", description="Parent probe", work_type="task", created_by="captain",
    )
    child = await store.create_work_item(
        title="Child", description="Child probe", work_type="task",
        assigned_to="crew-agent", created_by="captain",
    )
    registry = ToolRegistry()
    tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False)
    registry.register(tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    crew = CrewTaskExecutor(
        work_item_store=store, agent_registry=SimpleNamespace(), runtime=runtime,
        agentic_executor=WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")),
    )
    outcome = await crew._run_agentic_with_outer_loop(
        agent=SimpleNamespace(id="crew-agent", instructions="Test instructions."),
        task_text="use the inert probe", thread_id=thread.id,
        parent_id=parent.id, child_id=child.id,
    )
    assert outcome.final_text == "done" and tool.calls == 1
    rows = await log.query(category="tool", limit=100)
    assert len(rows) == 2
    assert all(row["data"]["work_item_id"] == child.id for row in rows)
    assert all(row["data"]["thread_id"] == thread.id for row in rows)
    assert len({row["data"]["run_id"] for row in rows}) == 1
    assert rows[0]["data"]["run_id"]
    assert len({row["correlation_id"] for row in rows}) == 1
    assert tool.contexts[0]["_crew_work_item_id"] == child.id
    assert tool.contexts[0]["_crew_session_id"] == parent.id


async def test_promoted_conversational_continuation_links_late_work_item(
    open_log: _LogFactory, conversation_stores: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late publication links new observations without rewriting the first start."""
    from probos.cognitive.turn_promotion import PROMOTION_SOURCE
    from probos.config import DmAgenticConfig
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Promotion probe", participants=["conversation-agent"])
    prior = await store.create_work_item(
        title="Prior turn", description="A different turn on this thread", work_type="task",
        assigned_to="conversation-agent", created_by="captain",
        metadata={"source": PROMOTION_SOURCE, "thread_id": thread.id, "agent_id": "conversation-agent"},
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    observed: list[dict[str, Any]] = []

    async def _block_inside_tool() -> None:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed) == 1 and observed[0]["detail"] == "dispatch_probe"
        entered.set()
        await release.wait()

    original_create = store.create_work_item

    async def _create_after_entry(**kwargs: Any) -> Any:
        await asyncio.wait_for(entered.wait(), timeout=10)
        assert len(observed) == 1 and not release.is_set()
        return await original_create(**kwargs)

    monkeypatch.setattr(store, "create_work_item", _create_after_entry)
    first_tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False, on_invoke=_block_inside_tool)
    later_tool = _DispatchTool("post_promotion_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(first_tool)
    registry.register(later_tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.config.dm_agentic = DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.01)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    agent = _conversational_agent(runtime, _BatchLLM(["dispatch_probe", "post_promotion_probe"]))
    turn = asyncio.create_task(_conversation(agent, thread.id))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        acknowledgement = await asyncio.wait_for(turn, timeout=10)
        items = await store.list_work_items()
        created = [item for item in items if item.id != prior.id]
        assert len(created) == 1
        promoted = created[0]
        assert acknowledgement and promoted.id in acknowledgement
        assert promoted.metadata["source"] == PROMOTION_SOURCE
        assert promoted.metadata["thread_id"] == prior.metadata["thread_id"] == thread.id
        assert promoted.metadata["promoted_agentic_run_id"] == observed[0]["data"]["run_id"]
        assert observed[0]["data"]["work_item_id"] is None
        assert first_tool.calls == 1 and later_tool.calls == 0
        assert (await store.get_work_item(promoted.id)).status == "in_progress"
        release.set()
        await _drain_owned_tasks(agent._promoted_turn_tasks)
        assert first_tool.calls == later_tool.calls == 1, "promotion replayed or lost a tool call"
        assert (await store.get_work_item(promoted.id)).status == "done"
        messages = threads.list_messages(thread.id)
        assert any(message.metadata.get("work_item_id") == promoted.id for message in messages)
        await log.stop()
        reopened = await open_log()
        starts = await _rows(reopened, EventType.TOOL_STARTED.value)
        completions = await _rows(reopened, EventType.TOOL_INVOKED.value)
        assert len(starts) == len(completions) == 2
        assert {row["correlation_id"] for row in starts} == {row["correlation_id"] for row in completions}
        assert len({row["data"]["run_id"] for row in starts + completions}) == 1
        assert starts[0]["data"]["run_id"]
        assert all(row["data"]["thread_id"] == thread.id for row in starts + completions)
        first_start = next(row for row in starts if row["detail"] == "dispatch_probe")
        assert first_start == observed[0]
        assert first_start["data"]["work_item_id"] is None
        assert all(row["data"]["work_item_id"] == promoted.id for row in completions)
        later_start = next(row for row in starts if row["detail"] == "post_promotion_probe")
        assert later_start["data"]["work_item_id"] == promoted.id, (
            "The turn's published work item must reach later starts through the "
            "diagnostic provider, without adding it to execution authority context."
        )
        for start in starts:
            completion = next(row for row in completions if row["correlation_id"] == start["correlation_id"])
            assert completion["parent_event_id"] == start["id"]
            assert completion["data"]["run_id"] == start["data"]["run_id"]
            assert completion["data"]["iteration"] == start["data"]["iteration"]
        assert all("_crew_work_item_id" not in context for tool in (first_tool, later_tool) for context in tool.contexts)
        await store.stop()
        await store.start()
        linked = [item for item in await store.list_work_items() if (
            item.metadata.get("promoted_agentic_run_id") == first_start["data"]["run_id"]
            and item.metadata.get("thread_id") == first_start["data"]["thread_id"]
            and item.metadata.get("agent_id") == first_start["data"]["agent_id"]
        )]
        assert [item.id for item in linked] == [promoted.id]
        assert prior.id not in {item.id for item in linked}
        assert linked[0].status == "done"
        assert await reopened.verify_chain() == (True, None)
    finally:
        release.set()
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await _cancel_owned_tasks(agent._promoted_turn_tasks)


async def test_promoted_interrupted_tool_reopens_with_unique_run_link(
    open_log: _LogFactory, conversation_stores: Any, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aiosqlite

    from probos.cognitive.turn_promotion import PROMOTION_SOURCE
    from probos.config import DmAgenticConfig
    from probos.tools.registry import ToolRegistry
    from probos.workforce import WorkItemStore

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Interrupted promotion", participants=["conversation-agent"])
    prior = await store.create_work_item(
        title="Prior turn", description="Unrelated turn", work_type="task",
        assigned_to="conversation-agent", created_by="captain",
        metadata={"source": PROMOTION_SOURCE, "thread_id": thread.id, "agent_id": "conversation-agent"},
    )
    entered = asyncio.Event()
    observed: list[dict[str, Any]] = []
    observed_hashes: list[str] = []

    async def _stored_hash(event_id: int) -> str:
        async with aiosqlite.connect(tmp_path / "events.db") as connection:
            rows = await connection.execute_fetchall(
                "SELECT row_hash FROM events WHERE id = ?", (event_id,),
            )
        assert len(rows) == 1 and rows[0][0]
        return rows[0][0]

    async def _observe_start() -> None:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed) == 1 and observed[0]["detail"] == "dispatch_probe"
        assert observed[0]["data"]["work_item_id"] is None
        assert observed[0]["data"]["run_id"]
        observed_hashes.append(await _stored_hash(observed[0]["id"]))
        entered.set()

    original_create = store.create_work_item

    async def _create_after_entry(**kwargs: Any) -> Any:
        await asyncio.wait_for(entered.wait(), timeout=10)
        return await original_create(**kwargs)

    monkeypatch.setattr(store, "create_work_item", _create_after_entry)
    first_tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=True, on_invoke=_observe_start)
    later_tool = _DispatchTool("post_promotion_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(first_tool)
    registry.register(later_tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.config.dm_agentic = DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.01)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    agent = _conversational_agent(runtime, _BatchLLM(["dispatch_probe", "post_promotion_probe"]))
    turn = asyncio.create_task(_conversation(agent, thread.id))
    independent_store = WorkItemStore(db_path=str(tmp_path / "work-items.db"))
    try:
        await independent_store.start()
        await asyncio.wait_for(entered.wait(), timeout=10)
        acknowledgement = await asyncio.wait_for(turn, timeout=10)
        items = await independent_store.list_work_items()
        created = [item for item in items if item.id != prior.id]
        assert len(created) == 1
        promoted = created[0]
        assert acknowledgement and promoted.id in acknowledgement
        assert promoted.metadata["promoted_agentic_run_id"] == observed[0]["data"]["run_id"]
        assert "promoted_agentic_run_id" not in (await independent_store.get_work_item(prior.id)).metadata
        owned_runs = [task for task in agent._promoted_turn_tasks if task.get_name().startswith("ad1165-turn-")]
        assert len(owned_runs) == 1 and not owned_runs[0].done()
        assert first_tool.calls == 1 and later_tool.calls == 0
        assert await _rows(log, EventType.TOOL_INVOKED.value) == []
        owned_runs[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await owned_runs[0]
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await independent_store.stop()
        await store.stop()
        await log.stop()
        reopened = await open_log()
        await independent_store.start()
        starts = await _rows(reopened, EventType.TOOL_STARTED.value)
        assert starts == observed
        assert await _stored_hash(starts[0]["id"]) == observed_hashes[0]
        assert starts[0]["data"]["work_item_id"] is None
        assert await _rows(reopened, EventType.TOOL_INVOKED.value) == []
        assert first_tool.calls == 1 and later_tool.calls == 0
        linked = [item for item in await independent_store.list_work_items() if (
            item.metadata.get("promoted_agentic_run_id") == starts[0]["data"]["run_id"]
            and item.metadata.get("thread_id") == starts[0]["data"]["thread_id"]
            and item.metadata.get("agent_id") == starts[0]["data"]["agent_id"]
        )]
        assert [item.id for item in linked] == [promoted.id]
        assert prior.id not in {item.id for item in linked}
        assert await reopened.verify_chain() == (True, None)
    finally:
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await independent_store.stop()


@pytest.mark.parametrize("outcome", ["success", "error", "denied", "abort"])
async def test_late_work_item_provider_refreshes_completion_without_mutating_start(
    open_log: _LogFactory, outcome: str,
) -> None:
    from probos.tools.registry import ToolPermissionDenied, ToolRegistry

    log = await open_log()
    registry = ToolRegistry()
    tool = _DispatchTool(
        "dispatch_probe", entered=asyncio.Event(), hang=False,
        error="network failure" if outcome == "error" else None,
    )
    registry.register(tool, default_permissions={"captain": "full"} if outcome == "denied" else {})
    current: list[str | None] = [None]
    observed: list[dict[str, Any]] = []
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor = ToolExecutor(registry=registry)
    wire_tool_invocation_hooks(
        executor, event_log=log, work_item_id_provider=lambda: current[0],
        emit_fn=lambda event, payload: emitted.append((event, payload)),
    )

    async def _publish(_context: dict[str, Any]) -> bool:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed) == 1 and observed[0]["data"]["work_item_id"] is None
        current[0] = "promoted-item"
        return outcome != "abort"

    executor.add_pre_hook(_publish)
    context = {"thread_id": "thread-1", "_agentic_run_id": "run-1", "iteration": 3}
    original_context = dict(context)
    if outcome == "denied":
        with pytest.raises(ToolPermissionDenied):
            await executor.invoke("agent-1", "dispatch_probe", {}, context=context)
    else:
        result = await executor.invoke("agent-1", "dispatch_probe", {}, context=context)
        assert (result.error is None) is (outcome == "success")
    assert tool.calls == (0 if outcome in {"denied", "abort"} else 1)
    assert context == original_context
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert starts == observed
    assert len(completions) == 1
    assert completions[0]["data"]["work_item_id"] == "promoted-item"
    assert completions[0]["correlation_id"] == starts[0]["correlation_id"]
    assert completions[0]["parent_event_id"] == starts[0]["id"]
    for key in ("agent_id", "thread_id", "run_id", "iteration", "tool_id", "invocation_id"):
        assert completions[0]["data"][key] == starts[0]["data"][key]
    live_completions = [payload for event, payload in emitted if event is EventType.TOOL_INVOKED]
    if outcome in {"denied", "abort"}:
        assert live_completions == []
    else:
        assert len(live_completions) == 1
        assert live_completions[0]["work_item_id"] == "promoted-item"


def _diagnostic_provider(
    case: str, identity: str, calls: list[str],
) -> Callable[[], Any] | None:
    if case in {"omitted", "none"}:
        return None

    class _StringSubclass(str):
        pass

    async def _async_value() -> str:
        calls.append("awaited")
        return identity

    def _provide() -> Any:
        calls.append("provider")
        if case == "raises":
            raise RuntimeError(_ERROR_MARKER)
        if case == "cancelled":
            raise asyncio.CancelledError()
        if case == "async":
            return _async_value()
        values = {
            "valid": identity, "unavailable": None, "empty": "",
            "integer": 3, "boolean": True, "subclass": _StringSubclass(identity),
            "opaque": _HostileRepr(), "oversized": "x" * 129,
            "utf8_oversized": "\u00e9" * 100,
            "json_oversized": "\x01" * 30, "surrogate": "\ud800",
        }
        assert case in values, "the diagnostic boundary case was not exercised"
        return values[case]

    return _provide


@pytest.mark.parametrize("case", [
    "omitted", "none", "valid", "unavailable", "empty", "integer", "boolean",
    "subclass", "opaque", "oversized", "utf8_oversized", "json_oversized",
    "surrogate", "raises", "async",
])
def test_recording_identity_provider_accepts_only_exact_bounded_synchronous_values(
    case: str, caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    value = sample_recording_identity(_diagnostic_provider(case, "actual-run", calls))
    assert value == ("actual-run" if case == "valid" else None)
    assert calls == ([] if case in {"omitted", "none"} else ["provider"])
    assert _ERROR_MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_recording_identity_never_truncates_or_coerces_a_join_key(hostile_parameters: Any) -> None:
    _params, objects, calls = hostile_parameters
    assert recording_identity(None) is None
    assert recording_identity("") is None
    assert recording_identity("x" * 126) == "x" * 126
    assert recording_identity("x" * 127) is None
    assert recording_identity("\u00e9" * 21) == "\u00e9" * 21
    assert recording_identity("\u00e9" * 22) is None
    for opaque in objects:
        assert recording_identity(opaque) is None
    assert calls == []


def test_recording_identity_provider_propagates_lifecycle_cancellation() -> None:
    calls: list[str] = []
    with pytest.raises(asyncio.CancelledError):
        sample_recording_identity(_diagnostic_provider("cancelled", "run", calls))
    assert calls == ["provider"]


@pytest.mark.parametrize(("diagnostic", "outcome"), [
    *[(case, "success") for case in (
        "omitted", "none", "valid", "unavailable", "empty", "integer",
        "boolean", "subclass", "opaque", "oversized", "utf8_oversized",
        "json_oversized", "surrogate", "raises", "async", "conflict",
        "observer_raises", "observer_invalid", "observer_async",
    )],
    ("raises", "error"), ("raises", "denied"), ("raises", "loto"),
    ("observer_raises", "denied"), ("observer_raises", "loto"),
])
async def test_promotion_diagnostic_failures_preserve_registry_chain(
    open_log: _LogFactory, caplog: pytest.LogCaptureFixture,
    diagnostic: str, outcome: str,
) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.tools.registry import ToolRegistry

    class _RecordingRegistry(ToolRegistry):
        def __init__(self) -> None:
            super().__init__()
            self.invocations: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

        async def check_and_invoke(
            self, agent_id: str, tool_id: str, params: dict[str, Any], **kwargs: Any,
        ) -> ToolResult:
            self.invocations.append((agent_id, tool_id, params, kwargs))
            return await super().check_and_invoke(agent_id, tool_id, params, **kwargs)

    log = await open_log()
    observed_starts: list[dict[str, Any]] = []

    async def _inside_tool() -> None:
        reader = await open_log()
        observed_starts.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed_starts) == 1 and observed_starts[0]["correlation_id"]

    tool = _DispatchTool(
        "dispatch_probe", entered=asyncio.Event(), hang=False, on_invoke=_inside_tool,
        error="network failure" if outcome == "error" else None,
    )
    registry = _RecordingRegistry()
    registry.register(
        tool, concurrency="exclusive",
        default_permissions={"captain": "full"} if outcome == "denied" else {},
    )
    if outcome == "loto":
        assert registry.acquire_lock("dispatch_probe", "other-agent", reason="test lock")
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    provider_calls: list[str] = []
    runs: list[str] = []
    observer_awaited: list[str] = []

    async def _async_observer() -> None:
        observer_awaited.append("awaited")

    def _observe(run_id: str) -> Any:
        runs.append(run_id)
        if diagnostic == "observer_raises":
            raise RuntimeError(_ERROR_MARKER)
        if diagnostic == "observer_invalid":
            return _HostileRepr()
        if diagnostic == "observer_async":
            return _async_observer()
        return None

    provider_case = "unavailable" if diagnostic.startswith("observer_") else diagnostic
    if diagnostic == "conflict":
        provider_case = "valid"
    diagnostics: dict[str, Any] = {"on_run_started": _observe}
    if diagnostic != "omitted":
        diagnostics["work_item_id_provider"] = _diagnostic_provider(provider_case, "promoted-item", provider_calls)
    context = {"_crew_work_item_id": "existing-item"} if diagnostic == "conflict" else {}
    original_context = dict(context)
    result = await WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
        agent_id="diagnostic-agent", instructions="Test instructions.", task_text="use the probe",
        runtime=runtime, thread_id="diagnostic-thread", extra_context=context, **diagnostics,
    )
    assert result.final_text == "done"
    assert len(registry.invocations) == 1
    assert registry.invocations[0][:3] == ("diagnostic-agent", "dispatch_probe", {})
    assert tool.calls == (0 if outcome in {"denied", "loto"} else 1)
    assert result.denied_tools == (["dispatch_probe"] if outcome == "denied" else [])
    assert context == original_context
    execution_context = registry.invocations[0][3]["context"]
    assert execution_context.get("_crew_work_item_id") == original_context.get("_crew_work_item_id")
    assert "work_item_id_provider" not in execution_context and "on_run_started" not in execution_context
    assert "promoted_agentic_run_id" not in execution_context
    assert not any(callable(value) for value in execution_context.values())
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]
    assert runs == [starts[0]["data"]["run_id"]]
    assert observer_awaited == []
    assert provider_calls == ([] if diagnostic in {"omitted", "none"} else ["provider", "provider"])
    expected_item = "existing-item" if diagnostic == "conflict" else "promoted-item" if diagnostic == "valid" else None
    assert starts[0]["data"]["work_item_id"] == completions[0]["data"]["work_item_id"] == expected_item
    assert completions[0]["data"]["is_error"] is (outcome != "success")
    if tool.calls:
        assert observed_starts == starts
    assert _ERROR_MARKER not in json.dumps(starts + completions)
    assert _ERROR_MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records if record.getMessage().startswith("AD-1224:"))


@pytest.mark.parametrize("callback", ["provider", "completion_provider", "observer"])
async def test_diagnostic_cancellation_propagates_without_a_synthetic_completion(
    open_log: _LogFactory, callback: str,
) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(tool)
    calls: list[str] = []

    def _cancel_observer(run_id: str) -> None:
        calls.append("observer")
        raise asyncio.CancelledError()

    def _cancel_completion() -> str | None:
        calls.append("provider")
        if len(calls) == 1:
            return None
        raise asyncio.CancelledError()

    if callback == "observer":
        kwargs = {"on_run_started": _cancel_observer}
    else:
        kwargs = {"work_item_id_provider": (
            _cancel_completion if callback == "completion_provider"
            else _diagnostic_provider("cancelled", "run", calls)
        )}
    with pytest.raises(asyncio.CancelledError):
        await WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
            agent_id="agent-1", instructions="Test instructions.", task_text="use the probe",
            runtime=_dispatch_runtime(registry=registry, event_log=log), **kwargs,
        )
    assert calls == (["provider", "provider"] if callback == "completion_provider" else [callback])
    assert tool.calls == int(callback == "completion_provider")
    assert len(await _rows(log, EventType.TOOL_STARTED.value)) == int(callback == "completion_provider")
    assert await _rows(log, EventType.TOOL_INVOKED.value) == []


@pytest.mark.parametrize("case", [
    "valid", "missing_merge", "merge_raises", "merge_cancelled", "unacknowledged", "invalid_ack",
    "existing_link", "source_conflict", "thread_conflict", "agent_conflict",
    "assignee_conflict", "provider_omitted", "provider_none", "provider_unavailable",
    "provider_empty", "provider_integer", "provider_subclass", "provider_oversized",
    "provider_raises", "provider_async", "publication_raises", "publication_invalid",
    "publication_async",
])
async def test_promotion_link_diagnostic_boundaries_preserve_execution_and_reporting(
    open_log: _LogFactory, conversation_stores: Any,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, case: str,
) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.turn_promotion import PROMOTION_SOURCE, run_with_promotion
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Diagnostic promotion", participants=["diagnostic-agent"])
    entered = asyncio.Event()
    release = asyncio.Event()
    merge_entered = asyncio.Event()
    merge_release = asyncio.Event()
    observed: list[dict[str, Any]] = []
    current: dict[str, str | None] = {"run_id": None, "work_item_id": None}
    publications: list[str] = []
    publication_awaited: list[str] = []
    provider_calls: list[str] = []
    merge_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    held: set[asyncio.Task[Any]] = set()

    async def _block() -> None:
        reader = await open_log()
        observed.extend(await _rows(reader, EventType.TOOL_STARTED.value))
        assert len(observed) == 1 and observed[0]["data"]["run_id"] == current["run_id"]
        entered.set()
        await release.wait()

    tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False, on_invoke=_block)
    registry = ToolRegistry()
    registry.register(tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    original_create = store.create_work_item
    original_merge = store.merge_work_item_metadata

    async def _create(**kwargs: Any) -> Any:
        await asyncio.wait_for(entered.wait(), timeout=10)
        kwargs["metadata"]["preserved"] = {"value": "unchanged"}
        if case == "existing_link":
            kwargs["metadata"]["promoted_agentic_run_id"] = "different-run"
        elif case in {"source_conflict", "thread_conflict", "agent_conflict"}:
            key = {"source_conflict": "source", "thread_conflict": "thread_id", "agent_conflict": "agent_id"}[case]
            kwargs["metadata"][key] = "different-value"
        elif case == "assignee_conflict":
            kwargs["assigned_to"] = "different-agent"
        return await original_create(**kwargs)

    async def _merge(work_item_id: str, patch: dict[str, Any], **kwargs: Any) -> Any:
        merge_calls.append((work_item_id, dict(patch), dict(kwargs)))
        merge_entered.set()
        if case == "valid":
            await merge_release.wait()
        if case == "merge_raises":
            raise OSError(_ERROR_MARKER)
        if case == "merge_cancelled":
            raise asyncio.CancelledError()
        if case == "unacknowledged":
            return None
        if case == "invalid_ack":
            return False
        before = await store.get_work_item(work_item_id)
        updated = await original_merge(work_item_id, patch, **kwargs)
        assert updated is not None
        assert updated.metadata == {**before.metadata, **patch}
        assert updated.status == before.status
        assert updated.assigned_to == before.assigned_to
        assert updated.work_type == before.work_type
        assert updated.actual_tokens == before.actual_tokens
        return updated

    monkeypatch.setattr(store, "create_work_item", _create)
    monkeypatch.setattr(store, "merge_work_item_metadata", None if case == "missing_merge" else _merge)

    def _started(run_id: str) -> None:
        current["run_id"] = run_id

    async def _work() -> str:
        outcome = await WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
            agent_id="diagnostic-agent", instructions="Test instructions.", task_text="use the probe",
            runtime=runtime, thread_id=thread.id, on_run_started=_started,
            work_item_id_provider=lambda: current["work_item_id"],
        )
        return outcome.final_text

    async def _async_publication() -> None:
        publication_awaited.append("awaited")

    def _published(work_item_id: str) -> Any:
        publications.append(work_item_id)
        if case == "publication_raises":
            raise RuntimeError(_ERROR_MARKER)
        current["work_item_id"] = work_item_id
        if case == "publication_invalid":
            return _HostileRepr()
        if case == "publication_async":
            return _async_publication()
        return None

    def _run_id() -> str | None:
        provider_calls.append("provider")
        assert len(publications) == 1
        assert current["run_id"] == observed[0]["data"]["run_id"]
        return current["run_id"]

    diagnostics: dict[str, Any] = {"run_id_provider": _run_id}
    if case.startswith("provider_"):
        provider_case = case.removeprefix("provider_")
        diagnostics = {} if provider_case == "omitted" else {
            "run_id_provider": _diagnostic_provider(provider_case, "unused", provider_calls),
        }
    turn = asyncio.create_task(run_with_promotion(
        _work, promote_after_seconds=0.01, runtime=runtime, agent_id="diagnostic-agent",
        thread_id=thread.id, request_text="Use the probe", hold=held,
        on_promoted=_published, **diagnostics,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        if case == "valid":
            await asyncio.wait_for(merge_entered.wait(), timeout=10)
            assert not turn.done(), "acknowledgement escaped before the checked merge"
            assert tool.calls == 1 and not release.is_set()
            assert len(held) == 2, "the run and reporter must already have an owner"
            merge_release.set()
        if case == "merge_cancelled":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(turn, timeout=10)
            acknowledgement = None
            assert len(held) == 2 and all(not task.done() for task in held)
        else:
            acknowledgement = await asyncio.wait_for(turn, timeout=10)
        items = await store.list_work_items()
        assert len(items) == 1 and len(publications) == 1
        item = items[0]
        if case == "merge_cancelled":
            assert turn.cancelled() and acknowledgement is None
        else:
            assert acknowledgement and item.id in acknowledgement
        assert item.metadata["preserved"] == {"value": "unchanged"}
        assert publication_awaited == []
        assert provider_calls == ([] if case in {"provider_omitted", "provider_none"} else ["provider"])
        expected_merge = not case.startswith("provider_") and case != "missing_merge"
        assert len(merge_calls) == int(expected_merge)
        if merge_calls:
            item_id, patch, expected = merge_calls[0]
            assert item_id == item.id
            assert patch == {"promoted_agentic_run_id": observed[0]["data"]["run_id"]}
            assert expected == {
                "expected": {"source": PROMOTION_SOURCE, "thread_id": thread.id, "agent_id": "diagnostic-agent"},
                "expected_absent_keys": frozenset({"promoted_agentic_run_id"}),
                "expected_work_type": "task", "expected_assigned_to": "diagnostic-agent",
            }
        linked = case in {"valid", "publication_raises", "publication_invalid", "publication_async"}
        if linked:
            assert item.metadata["promoted_agentic_run_id"] == observed[0]["data"]["run_id"]
        elif case == "existing_link":
            assert item.metadata["promoted_agentic_run_id"] == "different-run"
        else:
            assert "promoted_agentic_run_id" not in item.metadata
        assert tool.calls == 1
        release.set()
        await _drain_owned_tasks(held)
        assert tool.calls == 1
        assert (await store.get_work_item(item.id)).status == "done"
        assert any(message.metadata.get("work_item_id") == item.id for message in threads.list_messages(thread.id))
        assert await _rows(log, EventType.TOOL_STARTED.value) == observed
        completions = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(completions) == 1 and completions[0]["data"]["is_error"] is False
        assert completions[0]["data"]["work_item_id"] == (None if case == "publication_raises" else item.id)
        assert _ERROR_MARKER not in json.dumps(await log.query(category="tool", limit=100))
        assert _ERROR_MARKER not in caplog.text
        assert all(record.exc_info is None for record in caplog.records if record.getMessage().startswith(("AD-1224:", "AD-1204:")))
    finally:
        merge_release.set()
        release.set()
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await _cancel_owned_tasks(held)


@pytest.mark.parametrize("route", [
    "factories", "durable_wiring", "legacy_wiring", "dispatch", "promotion", "conversation",
])
async def test_promotion_provenance_is_inert_without_event_log(
    conversation_stores: Any, monkeypatch: pytest.MonkeyPatch, route: str,
) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.turn_promotion import run_with_promotion
    from probos.config import DmAgenticConfig
    from probos.tools.registry import ToolRegistry

    store, threads = conversation_stores
    thread = threads.create_thread(title="No diagnostic log", participants=["conversation-agent"])
    calls: list[str] = []
    emitted: list[Any] = []
    merge_calls: list[dict[str, Any]] = []
    original_merge = store.merge_work_item_metadata

    def _provider() -> str | None:
        calls.append("provider")
        raise RuntimeError(_ERROR_MARKER)

    def _observer(run_id: str) -> None:
        calls.append("observer")
        raise RuntimeError(_ERROR_MARKER)

    async def _merge(work_item_id: str, patch: dict[str, Any], **kwargs: Any) -> Any:
        merge_calls.append(dict(patch))
        return await original_merge(work_item_id, patch, **kwargs)

    monkeypatch.setattr(store, "merge_work_item_metadata", _merge)
    registry = ToolRegistry()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _body() -> None:
        entered.set()
        if route in {"promotion", "conversation"}:
            await release.wait()

    tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False, on_invoke=_body)
    registry.register(tool)
    runtime = _dispatch_runtime(registry=registry, event_log=None)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    if route in {"factories", "durable_wiring", "legacy_wiring"}:
        executor = ToolExecutor(registry=registry)
        emitter = lambda event, _payload: emitted.append(event)
        if route == "factories":
            executor.add_pre_hook(make_start_hook(emitter, work_item_id_provider=_provider))
            executor.add_post_hook(make_audit_hook(emitter, work_item_id_provider=_provider))
            expected_events = [EventType.TOOL_STARTED, EventType.TOOL_INVOKED]
        elif route == "durable_wiring":
            assert not wire_durable_tool_records(
                executor, event_log=None, emit_fn=emitter, work_item_id_provider=_provider,
            )
            expected_events = []
        else:
            assert not wire_tool_invocation_hooks(
                executor, event_log=None, emit_fn=emitter, work_item_id_provider=_provider,
            )
            expected_events = [EventType.TOOL_INVOKED]
        result = await executor.invoke("conversation-agent", "dispatch_probe", {})
        assert result.error is None and tool.calls == 1
        assert emitted == expected_events
        assert executor.hook_count == len(expected_events)
    elif route == "dispatch":
        result = await WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
            agent_id="conversation-agent", instructions="Test instructions.", task_text="use the probe",
            runtime=runtime, work_item_id_provider=_provider, on_run_started=_observer,
        )
        assert result.final_text == "done" and tool.calls == 1
    else:
        original_create = store.create_work_item

        async def _create(**kwargs: Any) -> Any:
            await asyncio.wait_for(entered.wait(), timeout=10)
            return await original_create(**kwargs)

        monkeypatch.setattr(store, "create_work_item", _create)
        held: set[asyncio.Task[Any]] = set()
        captured: list[dict[str, Any]] = []
        original_run = WorkItemAgenticExecutor.run

        async def _capture(self: Any, **kwargs: Any) -> Any:
            captured.append(dict(kwargs))
            return await original_run(self, **kwargs)

        if route == "conversation":
            monkeypatch.setattr(WorkItemAgenticExecutor, "run", _capture)
            runtime.config.dm_agentic = DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.01)
            agent = _conversational_agent(runtime, _DispatchLLM("dispatch_probe"))
            held = agent._promoted_turn_tasks
            turn = asyncio.create_task(_conversation(agent, thread.id))
        else:
            async def _work() -> str:
                result = await WorkItemAgenticExecutor(llm_client=_DispatchLLM("dispatch_probe")).run(
                    agent_id="conversation-agent", instructions="Test instructions.", task_text="use the probe",
                    runtime=runtime, thread_id=thread.id,
                    work_item_id_provider=_provider, on_run_started=_observer,
                )
                return result.final_text

            turn = asyncio.create_task(run_with_promotion(
                _work, promote_after_seconds=0.01, runtime=runtime,
                agent_id="conversation-agent", thread_id=thread.id,
                request_text="Use the probe", hold=held, run_id_provider=_provider,
            ))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            acknowledgement = await asyncio.wait_for(turn, timeout=10)
            items = await store.list_work_items()
            assert len(items) == 1 and acknowledgement and items[0].id in acknowledgement
            assert tool.calls == 1 and not release.is_set()
            assert "promoted_agentic_run_id" not in items[0].metadata
            assert merge_calls == []
            release.set()
            await _drain_owned_tasks(held)
            assert tool.calls == 1 and (await store.get_work_item(items[0].id)).status == "done"
            assert any(message.metadata.get("work_item_id") == items[0].id for message in threads.list_messages(thread.id))
            if route == "conversation":
                assert len(captured) == 1
                assert "work_item_id_provider" not in captured[0]
                assert "on_run_started" not in captured[0]
        finally:
            release.set()
            if not turn.done():
                turn.cancel()
            await asyncio.gather(turn, return_exceptions=True)
            await _cancel_owned_tasks(held)
    assert entered.is_set() and tool.calls == 1
    assert calls == []
    assert not any("promoted_agentic_run_id" in patch for patch in merge_calls)
    assert "_crew_work_item_id" not in tool.contexts[0]


@pytest_asyncio.fixture
async def continuation_approvals(tmp_path: Path) -> AsyncIterator[Any]:
    from probos.cognitive.continue_or_ask import CONTINUE_ACTION, CONTINUE_SCOPE_KEY, CONTINUE_TOOL_ID
    from probos.tools.action_approvals import ActionApprovalStore

    approvals = ActionApprovalStore(db_path=str(tmp_path / "continuation-approvals.db"))
    await approvals.start()
    try:
        await approvals.issue_approval(
            "conversation-agent", CONTINUE_TOOL_ID, CONTINUE_ACTION,
            scope_key=CONTINUE_SCOPE_KEY, ttl_seconds=3600,
        )
        yield approvals
    finally:
        await approvals.stop()


async def test_promotion_provenance_isolated_between_turns_and_passes(
    open_log: _LogFactory, conversation_stores: Any, continuation_approvals: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
    from probos.config import DmAgenticConfig
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Overlapping turns", participants=["conversation-agent"])
    labels = ("turn-alpha", "turn-bravo")
    names = {label: [f"probe_{index}_first", f"probe_{index}_checkpoint", f"probe_{index}_continued"] for index, label in enumerate(labels)}
    first_release = {label: asyncio.Event() for label in labels}
    continuation_release = {label: asyncio.Event() for label in labels}
    continuation_entered = {label: asyncio.Event() for label in labels}
    both_first_entered = asyncio.Event()
    first_starts: dict[str, dict[str, Any]] = {}
    continuation_starts: dict[str, dict[str, Any]] = {}
    registry = ToolRegistry()
    tools: dict[str, _DispatchTool] = {}

    async def _first(label: str) -> None:
        reader = await open_log()
        starts = [row for row in await _rows(reader, EventType.TOOL_STARTED.value) if row["detail"] == names[label][0]]
        assert len(starts) == 1 and starts[0]["data"]["work_item_id"] is None
        first_starts[label] = starts[0]
        if len(first_starts) == 2:
            both_first_entered.set()
        await first_release[label].wait()

    async def _continued(label: str) -> None:
        reader = await open_log()
        starts = [row for row in await _rows(reader, EventType.TOOL_STARTED.value) if row["detail"] == names[label][2]]
        assert len(starts) == 1
        continuation_starts[label] = starts[0]
        continuation_entered[label].set()
        await continuation_release[label].wait()

    for label in labels:
        for index, name in enumerate(names[label]):
            callback = None
            if index == 0:
                callback = lambda label=label: _first(label)
            elif index == 2:
                callback = lambda label=label: _continued(label)
            tool = _DispatchTool(name, entered=asyncio.Event(), hang=False, on_invoke=callback)
            tools[name] = tool
            registry.register(tool)

    class _OverlappingLLM:
        def __init__(self) -> None:
            self.calls = {label: 0 for label in labels}
            self.prompts: dict[str, list[str]] = {label: [] for label in labels}

        async def complete(self, request: Any, **kwargs: Any) -> Any:
            matches = [label for label in labels if request.prompt.startswith(f"[user] {label}")]
            assert len(matches) == 1, "the overlapped turn's prompt lost its identity"
            label = matches[0]
            self.calls[label] += 1
            self.prompts[label].append(request.prompt)
            count = self.calls[label]
            assert count <= 4, "a turn was replayed or did not complete its second pass"
            text = f"Working {label}." if count <= 3 else f"finished {label}"
            blocks: list[Any] = [TextBlock(text=text)]
            if count <= 3:
                blocks.append(ToolUseBlock(tool_call=ToolCallRequest(name=names[label][count - 1], arguments={})))
            return SimpleNamespace(content_blocks=blocks, content=text, tokens_used=1)

    original_create = store.create_work_item

    async def _create_after_overlap(**kwargs: Any) -> Any:
        await asyncio.wait_for(both_first_entered.wait(), timeout=10)
        assert len(first_starts) == 2
        assert not any(event.is_set() for event in first_release.values())
        return await original_create(**kwargs)

    monkeypatch.setattr(store, "create_work_item", _create_after_overlap)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, max_iterations=2, continue_or_ask_enabled=True,
        continue_or_ask_max_passes=2, promote_to_task_after_seconds=0.01,
    )
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    runtime.action_approval_store = continuation_approvals
    llm = _OverlappingLLM()
    agent = _conversational_agent(runtime, llm)

    async def _turn(label: str) -> str | None:
        return await CognitiveAgent._maybe_run_conversational_agentic(
            agent, {
                "intent": "direct_message", "thread_id": thread.id, "correlation_id": label,
                "params": {"author_id": "captain", "captain_message": label},
            },
            system_prompt="Test instructions.", user_message=label,
        )

    turns = [asyncio.create_task(_turn(label)) for label in labels]
    try:
        await asyncio.wait_for(both_first_entered.wait(), timeout=10)
        assert all(tools[names[label][0]].calls == 1 for label in labels)
        assert len({start["data"]["run_id"] for start in first_starts.values()}) == 2
        acknowledgements = await asyncio.wait_for(asyncio.gather(*turns), timeout=10)
        items = await store.list_work_items()
        assert len(items) == 2
        promoted: dict[str, Any] = {}
        for label, acknowledgement in zip(labels, acknowledgements):
            matches = [item for item in items if item.metadata.get("promoted_agentic_run_id") == first_starts[label]["data"]["run_id"]]
            assert len(matches) == 1
            promoted[label] = matches[0]
            assert acknowledgement and matches[0].id in acknowledgement
            assert matches[0].metadata["thread_id"] == thread.id
            assert matches[0].metadata["agent_id"] == agent.id
        assert promoted[labels[0]].id != promoted[labels[1]].id
        first_release[labels[0]].set()
        await asyncio.wait_for(continuation_entered[labels[0]].wait(), timeout=10)
        assert not first_release[labels[1]].is_set()
        assert tools[names[labels[1]][1]].calls == tools[names[labels[1]][2]].calls == 0
        first_release[labels[1]].set()
        await asyncio.wait_for(continuation_entered[labels[1]].wait(), timeout=10)
        all_runs = {row["data"]["run_id"] for row in [*first_starts.values(), *continuation_starts.values()]}
        assert None not in all_runs and len(all_runs) == 4
        for label in labels:
            assert continuation_starts[label]["data"]["work_item_id"] == promoted[label].id
            assert continuation_starts[label]["data"]["iteration"] == 1
            assert llm.calls[label] == 3
            assert llm.prompts[label][2].startswith(f"[user] {label}")
            continuation_release[label].set()
        await _drain_owned_tasks(agent._promoted_turn_tasks)
        assert all(tool.calls == 1 for tool in tools.values())
        assert all(count == 4 for count in llm.calls.values())
        starts = await _rows(log, EventType.TOOL_STARTED.value)
        completions = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(starts) == len(completions) == 6
        assert len({row["correlation_id"] for row in starts}) == 6
        for label in labels:
            own_starts = [row for row in starts if row["detail"] in names[label]]
            own_completions = [row for row in completions if row["detail"] in names[label]]
            assert len(own_starts) == len(own_completions) == 3
            assert next(row for row in own_starts if row["detail"] == names[label][0]) == first_starts[label]
            assert all(row["data"]["work_item_id"] == promoted[label].id for row in own_completions)
            assert all(row["data"]["work_item_id"] == promoted[label].id for row in own_starts if row["detail"] != names[label][0])
            assert next(row for row in own_starts if row["detail"] == names[label][1])["data"]["run_id"] == first_starts[label]["data"]["run_id"]
            for start in own_starts:
                completion = next(row for row in own_completions if row["correlation_id"] == start["correlation_id"])
                assert completion["parent_event_id"] == start["id"]
                assert completion["data"]["run_id"] == start["data"]["run_id"]
            assert (await store.get_work_item(promoted[label].id)).status == "done"
            reports = [message for message in threads.list_messages(thread.id) if message.metadata.get("work_item_id") == promoted[label].id]
            assert len(reports) == 1
        assert all("_crew_work_item_id" not in context for tool in tools.values() for context in tool.contexts)
        assert await log.verify_chain() == (True, None)
    finally:
        for event in [*first_release.values(), *continuation_release.values()]:
            event.set()
        for turn in turns:
            if not turn.done():
                turn.cancel()
        await asyncio.gather(*turns, return_exceptions=True)
        await _cancel_owned_tasks(agent._promoted_turn_tasks)


async def test_promotion_link_samples_run_at_publication(
    open_log: _LogFactory, conversation_stores: Any, continuation_approvals: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
    from probos.cognitive.turn_promotion import PROMOTION_SOURCE
    from probos.config import DmAgenticConfig
    from probos.tools.registry import ToolRegistry

    log = await open_log()
    store, threads = conversation_stores
    thread = threads.create_thread(title="Publication race", participants=["conversation-agent"])
    prior = await store.create_work_item(
        title="Prior turn", description="Different turn on the same thread", work_type="task",
        assigned_to="conversation-agent", created_by="captain",
        metadata={"source": PROMOTION_SOURCE, "thread_id": thread.id, "agent_id": "conversation-agent"},
    )
    first_entered = asyncio.Event()
    first_release = asyncio.Event()
    creation_entered = asyncio.Event()
    creation_release = asyncio.Event()
    second_run_entered = asyncio.Event()
    second_run_release = asyncio.Event()
    observed: dict[str, dict[str, Any]] = {}

    async def _first() -> None:
        reader = await open_log()
        starts = await _rows(reader, EventType.TOOL_STARTED.value)
        assert len(starts) == 1 and starts[0]["detail"] == "first_probe"
        observed["first"] = starts[0]
        first_entered.set()
        await first_release.wait()

    async def _second_run() -> None:
        reader = await open_log()
        starts = [row for row in await _rows(reader, EventType.TOOL_STARTED.value) if row["detail"] == "publication_probe"]
        assert len(starts) == 1
        observed["publication"] = starts[0]
        assert starts[0]["data"]["run_id"] != observed["first"]["data"]["run_id"]
        assert starts[0]["data"]["work_item_id"] is None
        assert creation_entered.is_set() and not creation_release.is_set()
        second_run_entered.set()
        await second_run_release.wait()

    registry = ToolRegistry()
    tools = {
        "first_probe": _DispatchTool("first_probe", entered=asyncio.Event(), hang=False, on_invoke=_first),
        "checkpoint_probe": _DispatchTool("checkpoint_probe", entered=asyncio.Event(), hang=False),
        "publication_probe": _DispatchTool("publication_probe", entered=asyncio.Event(), hang=False, on_invoke=_second_run),
        "after_publication_probe": _DispatchTool("after_publication_probe", entered=asyncio.Event(), hang=False),
    }
    for tool in tools.values():
        registry.register(tool)

    class _PublicationLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, request: Any, **kwargs: Any) -> Any:
            self.calls += 1
            assert self.calls <= 4
            names = {
                1: ["first_probe"], 2: ["checkpoint_probe"],
                3: ["publication_probe", "after_publication_probe"], 4: [],
            }[self.calls]
            text = "Working on the probes." if names else "done"
            blocks: list[Any] = [TextBlock(text=text)]
            blocks.extend(ToolUseBlock(tool_call=ToolCallRequest(name=name, arguments={})) for name in names)
            return SimpleNamespace(content_blocks=blocks, content=text, tokens_used=1)

    original_create = store.create_work_item

    async def _create_during_continuation(**kwargs: Any) -> Any:
        await asyncio.wait_for(first_entered.wait(), timeout=10)
        creation_entered.set()
        await creation_release.wait()
        assert second_run_entered.is_set()
        assert observed["publication"]["data"]["run_id"] != observed["first"]["data"]["run_id"]
        return await original_create(**kwargs)

    monkeypatch.setattr(store, "create_work_item", _create_during_continuation)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, max_iterations=2, continue_or_ask_enabled=True,
        continue_or_ask_max_passes=2, promote_to_task_after_seconds=0.01,
    )
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    runtime.action_approval_store = continuation_approvals
    llm = _PublicationLLM()
    agent = _conversational_agent(runtime, llm)
    turn = asyncio.create_task(_conversation(agent, thread.id))
    try:
        await asyncio.wait_for(creation_entered.wait(), timeout=10)
        assert tools["first_probe"].calls == 1 and not turn.done()
        assert observed["first"]["data"]["work_item_id"] is None
        assert [item.id for item in await store.list_work_items()] == [prior.id]
        first_release.set()
        await asyncio.wait_for(second_run_entered.wait(), timeout=10)
        assert llm.calls == 3 and not turn.done()
        assert tools["checkpoint_probe"].calls == tools["publication_probe"].calls == 1
        assert tools["after_publication_probe"].calls == 0
        assert not creation_release.is_set()
        assert len(await _rows(log, EventType.TOOL_INVOKED.value)) == 2
        creation_release.set()
        acknowledgement = await asyncio.wait_for(turn, timeout=10)
        created = [item for item in await store.list_work_items() if item.id != prior.id]
        assert len(created) == 1 and acknowledgement and created[0].id in acknowledgement
        promoted = created[0]
        active_run = observed["publication"]["data"]["run_id"]
        assert promoted.metadata["promoted_agentic_run_id"] == active_run
        assert active_run != observed["first"]["data"]["run_id"]
        assert not second_run_release.is_set()
        second_run_release.set()
        await _drain_owned_tasks(agent._promoted_turn_tasks)
        assert llm.calls == 4 and all(tool.calls == 1 for tool in tools.values())
        assert (await store.get_work_item(promoted.id)).status == "done"
        await log.stop()
        await store.stop()
        reopened = await open_log()
        await store.start()
        starts = await _rows(reopened, EventType.TOOL_STARTED.value)
        completions = await _rows(reopened, EventType.TOOL_INVOKED.value)
        assert len(starts) == len(completions) == 4
        assert next(row for row in starts if row["detail"] == "first_probe") == observed["first"]
        assert next(row for row in starts if row["detail"] == "publication_probe") == observed["publication"]
        assert all(row["data"]["work_item_id"] is None for row in starts if row["detail"] != "after_publication_probe")
        after_start = next(row for row in starts if row["detail"] == "after_publication_probe")
        assert after_start["data"]["work_item_id"] == promoted.id
        assert after_start["data"]["run_id"] == active_run
        for start in starts:
            completion = next(row for row in completions if row["correlation_id"] == start["correlation_id"])
            assert completion["parent_event_id"] == start["id"]
            assert completion["data"]["run_id"] == start["data"]["run_id"]
            expected_item = promoted.id if start["data"]["run_id"] == active_run else None
            assert completion["data"]["work_item_id"] == expected_item
        linked = [item for item in await store.list_work_items() if (
            item.metadata.get("promoted_agentic_run_id") == active_run
            and item.metadata.get("thread_id") == thread.id
            and item.metadata.get("agent_id") == agent.id
        )]
        assert [item.id for item in linked] == [promoted.id]
        assert "promoted_agentic_run_id" not in (await store.get_work_item(prior.id)).metadata
        assert any(message.metadata.get("work_item_id") == promoted.id for message in threads.list_messages(thread.id))
        assert await reopened.verify_chain() == (True, None)
    finally:
        first_release.set()
        creation_release.set()
        second_run_release.set()
        if not turn.done():
            turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)
        await _cancel_owned_tasks(agent._promoted_turn_tasks)


@pytest.mark.parametrize("case", [
    "omitted_observer", "none_observer", "valid", "none_run", "empty_run",
    "invalid_run", "oversized_run", "subclass_run",
])
async def test_loop_run_observer_receives_only_actual_valid_identity_before_execution(
    open_log: _LogFactory, case: str,
) -> None:
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
    from probos.tools.registry import ToolRegistry

    class _StringSubclass(str):
        pass

    phases: list[str] = []
    observed: list[str] = []

    class _ObservedLLM(_DispatchLLM):
        async def complete(self, req: Any, **kwargs: Any) -> Any:
            phases.append("llm")
            return await super().complete(req, **kwargs)

    def _observe(run_id: str) -> None:
        phases.append("observer")
        observed.append(run_id)

    supplied: Any = {
        "none_run": None, "empty_run": "", "invalid_run": 12,
        "oversized_run": "x" * 129, "subclass_run": _StringSubclass("run"),
    }.get(case, "actual-run")
    context = {"agent_id": "agent-1", "_agentic_run_id": supplied}
    log = await open_log()
    registry = ToolRegistry()
    tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False)
    registry.register(tool)
    executor = ToolExecutor(registry=registry)
    _paired(executor, log)
    kwargs: dict[str, Any] = {}
    if case != "omitted_observer":
        kwargs["on_run_started"] = None if case == "none_observer" else _observe
    result = await AgenticLoop(llm_client=_ObservedLLM("dispatch_probe"), tool_executor=executor).run(
        system_prompt="Test instructions.", user_message="Use the probe", tools=[], context=context,
        **kwargs,
    )
    assert result.error == "" and result.final_text == "done" and tool.calls == 1
    assert context["_agentic_run_id"] is supplied
    assert "iteration" not in context
    starts = await _rows(log, EventType.TOOL_STARTED.value)
    completions = await _rows(log, EventType.TOOL_INVOKED.value)
    assert len(starts) == len(completions) == 1
    assert starts[0]["correlation_id"] == completions[0]["correlation_id"]
    if case in {"valid", "none_run", "empty_run"}:
        assert phases == ["observer", "llm", "llm"]
        assert observed == [starts[0]["data"]["run_id"]]
        assert type(observed[0]) is str and observed[0]
        if case == "valid":
            assert observed == [supplied]
    else:
        assert phases == ["llm", "llm"]
        assert observed == []