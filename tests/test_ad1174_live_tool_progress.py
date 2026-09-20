"""AD-1174: existing producer -> real runtime -> bounded live hub observations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.config import DmAgenticConfig, SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
from probos.ws_event_stream import WSEventStreamHub
from tests import test_ad1133_live_crew_session_refresh as live
from tests import test_ad1152_agentic_correlation as correlation
from tests import test_ad1224_durable_tool_start as durable
from tests.test_ad1224_durable_tool_start import conversation_stores, open_log  # noqa: F401


@pytest.fixture(scope="module", autouse=True)
def _candidate_origins() -> None:
    import probos.cognitive.swe_harness.agentic_loop as producer
    import probos.runtime as runtime
    import probos.ws_event_stream as transport

    root = Path(__file__).resolve().parents[1]
    assert Path.cwd().resolve() == root
    for module in (producer, runtime, transport):
        assert Path(module.__file__).resolve().is_relative_to(root / "src")


class _StringSubclass(str):
    pass


class _ProgressRuntime(ProbOSRuntime):
    def __init__(self) -> None:
        self._event_listeners = []
        self._live_event_listeners = []
        self._event_listener_tasks = set()
        self._nats_events_wired = False
        self.nats_bus = None

    @property
    def attachment_store(self) -> None:
        return None


@pytest.mark.parametrize("thread_id,expected", [
    (None, None), ("", None), (" \t\n", None), ("\x1c\u0085", None),
    (123, None), (b"thread", None), ({}, None),
    (_StringSubclass("thread"), None), ("a" * 129, None),
    ("\u00e9" * 65, None), ("\ud800", None),
    ("a" * 128, "a" * 128), ("\u00e9" * 64, "\u00e9" * 64),
    ("\U0001f600" * 32, "\U0001f600" * 32),
    ("\ufeff", "\ufeff"), (" room exact ", " room exact "),
])
async def test_on_thread_identity_is_exact_strict_bounded(
    thread_id: Any, expected: str | None,
) -> None:
    tools = correlation._ToolRecorder()
    loop, _, events = correlation._listened_loop(
        correlation._ScriptedClient([
            correlation._tool_turn("first"), LLMResponse(content="done", tokens_used=1),
        ]), tools,
    )
    context = {"agent_id": "agent", "thread_id": thread_id}
    await loop.run(system_prompt="sys", user_message="task", tools=[], context=context)
    tool_events = [event["data"] for event in events if event["type"] in correlation.LOOP_EVENTS[1:]]
    assert len(tool_events) == 2
    assert all(data.get("thread_id") == expected for data in tool_events)
    assert all(("thread_id" in data) is (expected is not None) for data in tool_events)
    assert tools.calls[0]["context"]["thread_id"] == correlation._snapshot(thread_id)
    assert context["thread_id"] is thread_id


async def test_off_valid_thread_does_not_change_payload_or_cardinality() -> None:
    runtime = correlation._local_runtime()
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(events.append, correlation.LOOP_EVENTS)
    loop = AgenticLoop(
        llm_client=correlation._ScriptedClient([
            correlation._tool_turn("first"), LLMResponse(content="done", tokens_used=1),
        ]),
        tool_executor=correlation._ToolRecorder(), event_emit_fn=runtime.emit_event,
    )
    await loop.run(
        system_prompt="sys", user_message="task", tools=[],
        context={"agent_id": "agent", "thread_id": "authoritative"},
    )
    assert len(events) == 4
    start, end = [event["data"] for event in events if event["type"] in correlation.LOOP_EVENTS[1:]]
    assert set(start) == {"agent_id", "tool_id", "iteration"}
    assert set(end) == {"agent_id", "tool_id", "iteration", "is_error", "duration_ms"}
    assert all("run_id" not in event["data"] and "thread_id" not in event["data"] for event in events)


async def test_overlapping_runs_capture_thread_before_delayed_emission() -> None:
    release = asyncio.Event()
    runtime = correlation._local_runtime()
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(events.append, correlation.LOOP_EVENTS)
    emitted: list[asyncio.Task[None]] = []

    def delayed_emit(event: EventType, data: dict[str, Any]) -> None:
        async def deliver() -> None:
            await release.wait()
            runtime.emit_event(event, data)
        emitted.append(asyncio.create_task(deliver()))

    loop = AgenticLoop(
        llm_client=correlation._PerRunClient(), tool_executor=correlation._ToolRecorder(),
        event_emit_fn=delayed_emit, event_correlation_enabled=True,
    )
    contexts = [{"agent_id": "same", "thread_id": name} for name in ("first", "second")]
    tasks = [asyncio.create_task(loop.run(
        system_prompt=context["thread_id"], user_message="task", tools=[], context=context,
    )) for context in contexts]
    try:
        await asyncio.gather(*tasks)
        assert not events and len(emitted) == 12
        for context in contexts:
            context["thread_id"] = "not-the-invocation"
        release.set()
        await asyncio.gather(*emitted)
        by_run: dict[str, set[str]] = {}
        for event in events:
            if event["type"] in correlation.LOOP_EVENTS[1:]:
                data = event["data"]
                by_run.setdefault(data["run_id"], set()).add(data["thread_id"])
                assert data["tool_call_id"] == " provider/duplicate "
        assert sorted(by_run.values(), key=str) == [{"first"}, {"second"}]
        correlation._assert_paired(events)
    finally:
        release.set()
        await asyncio.gather(*tasks, *emitted, return_exceptions=True)


@pytest.mark.parametrize("promoted", [False, True])
@pytest.mark.parametrize("error", [None, "private-error-marker"])
async def test_real_conversation_live_start_precedes_completion_and_matches_durable_run(
    tmp_path: Path, open_log: Any, conversation_stores: Any,
    promoted: bool, error: str | None,
) -> None:
    log = await open_log()
    work_items, threads = conversation_stores
    thread = threads.create_thread(title="Live test", participants=["conversation-agent"])
    release = asyncio.Event()
    entered = asyncio.Event()

    async def hold_tool() -> None:
        entered.set()
        await release.wait()

    registry = ToolRegistry()
    tool = durable._DispatchTool(
        "dispatch_probe", entered=asyncio.Event(), hang=False,
        on_invoke=hold_tool, error=error,
    )
    registry.register(tool)
    runtime = _ProgressRuntime()
    runtime.config = SystemConfig()
    runtime.config.agentic_dispatch.enabled = True
    runtime.config.agentic_loop.event_correlation_enabled = True
    runtime.config.dm_agentic = DmAgenticConfig(
        enabled=True, promote_to_task_after_seconds=0.01 if promoted else 0,
    )
    runtime.tool_registry = registry
    runtime.tool_permission_store = ToolPermissionStore()
    runtime.capability_gap_driver = None
    runtime.intent_bus = None
    runtime.event_log = log
    runtime.work_item_store = work_items
    runtime.chat_thread_store = threads
    runtime.build_bounded_hxi_snapshot_base = live._Runtime(tmp_path).build_bounded_hxi_snapshot_base
    hub = WSEventStreamHub(runtime)
    await hub.start()
    listener = await runtime.register_live_event_listener(hub.ingress)
    socket = live._FakeWebSocket()
    connection = asyncio.create_task(hub.serve(socket))
    agent = durable._conversational_agent(runtime, durable._DispatchLLM("dispatch_probe"))
    turn: asyncio.Task[Any] | None = None
    try:
        await live._wait_until(lambda: len(socket.sent) == 1)
        turn = asyncio.create_task(durable._conversation(agent, thread.id))
        await asyncio.wait_for(entered.wait(), 10)
        await live._wait_until(lambda: any(
            json.loads(frame)["type"] == "agentic_tool_call_started" for frame in socket.sent
        ))
        frames = [json.loads(frame) for frame in socket.sent]
        started = next(frame for frame in frames if frame["type"] == "agentic_tool_call_started")
        assert started["data"]["thread_id"] == thread.id
        assert started["data"]["agent_id"] in threads.get_thread(thread.id).participants
        assert not any(frame["type"] == "agentic_tool_call_completed" for frame in frames)
        records = await durable._rows(log, EventType.TOOL_STARTED.value)
        assert len(records) == tool.calls == 1
        assert records[0]["data"]["run_id"] == started["data"]["run_id"]
        assert records[0]["data"]["thread_id"] == thread.id
        if promoted:
            acknowledgement = await asyncio.wait_for(turn, 10)
            items = await work_items.list_work_items()
            assert len(items) == 1 and items[0].id in acknowledgement
            assert items[0].metadata["promoted_agentic_run_id"] == started["data"]["run_id"]
            assert items[0].metadata["thread_id"] == thread.id
        else:
            assert not turn.done()
        release.set()
        await asyncio.wait_for(turn, 10)
        await durable._drain_owned_tasks(agent._promoted_turn_tasks)
        await live._wait_until(lambda: any(
            json.loads(frame)["type"] == "agentic_tool_call_completed" for frame in socket.sent
        ))
        completed = next(json.loads(frame) for frame in socket.sent
                         if json.loads(frame)["type"] == "agentic_tool_call_completed")
        assert {key: completed["data"][key] for key in started["data"]} == started["data"]
        assert completed["data"]["is_error"] is (error is not None)
        assert completed["stream"]["generation"] == started["stream"]["generation"]
        assert completed["stream"]["sequence"] > started["stream"]["sequence"]
        assert tool.calls == 1
        assert "private-error-marker" not in "".join(socket.sent)
    finally:
        release.set()
        if turn is not None and not turn.done():
            turn.cancel()
        if turn is not None:
            await asyncio.gather(turn, return_exceptions=True)
        await durable._cancel_owned_tasks(agent._promoted_turn_tasks)
        await listener.stop()
        await hub.stop()
        await asyncio.gather(connection, return_exceptions=True)


async def test_cancellation_retains_only_started_observation() -> None:
    entered = asyncio.Event()

    class _HeldTool:
        async def invoke(self, **kwargs: Any) -> Any:
            entered.set()
            await asyncio.Event().wait()

    loop, _, events = correlation._listened_loop(
        correlation._ScriptedClient([correlation._tool_turn("first")]), _HeldTool(),
    )
    task = asyncio.create_task(loop.run(
        system_prompt="sys", user_message="task", tools=[],
        context={"agent_id": "a", "thread_id": "cancel-room"},
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        tools = [event for event in events if event["type"] in correlation.LOOP_EVENTS[1:]]
        assert len(tools) == 1
        assert tools[0]["type"] == "agentic_tool_call_started"
        assert tools[0]["data"]["thread_id"] == "cancel-room"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
