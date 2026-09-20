"""Interactive, in-memory browser fixture; only model/tool bodies are inert.

JSON lines on owned stdio carry commands and finalized WSEventStreamHub frames.
No socket, vessel, provider, profile, credentials or filesystem database is used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

from starlette.websockets import WebSocketDisconnect

from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock
from probos.config import DmAgenticConfig, SystemConfig
from probos.runtime import ProbOSRuntime
from probos.threads import ChatThreadStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItemStore
from probos.ws_event_stream import WSEventStreamHub
from tests.test_ad1224_durable_tool_start import (
    _cancel_owned_tasks, _conversation, _conversational_agent, _drain_owned_tasks,
)

logger = logging.getLogger(__name__)


def _send(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class _MemoryThreads(ChatThreadStore):
    def __init__(self) -> None:
        self._uri = f"file:ad1174-{uuid.uuid4().hex}?mode=memory&cache=shared"
        self._keeper = sqlite3.connect(self._uri, uri=True)
        super().__init__(Path(":memory:"))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._uri, uri=True, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def close(self) -> None:
        self._keeper.close()


class _ProbeTool:
    tool_id = "progress_probe"
    name = "progress_probe"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "Inert local progress fixture"
    input_schema = {"type": "object", "properties": {"control": {"type": "string"}}}
    output_schema = {"type": "object"}

    def __init__(self) -> None:
        self.turns: dict[str, dict[str, Any]] = {}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        turn = self.turns[params["control"]]
        turn["calls"] += 1
        turn["contexts"].append(dict(context or {}))
        turn["entered"].set()
        await turn["release"].wait()
        # Allow the real bounded hub and the browser to consume each observation.
        await asyncio.sleep(0.005)
        return ToolResult(output="private-fixture-result", error="private-fixture-error" if turn["error"] else None)


class _ProbeLLM:
    def __init__(self, control: str, calls: int) -> None:
        self.control = control
        self.count = calls
        self.responses = 0

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.responses += 1
        if self.responses == 1:
            return LLMResponse(content="", tokens_used=1, content_blocks=[
                ToolUseBlock(tool_call=ToolCallRequest(
                    name="progress_probe", arguments={"control": self.control}, id="provider-duplicate",
                )) for _ in range(self.count)
            ])
        return LLMResponse(content="Local fixture reply.", content_blocks=[], tokens_used=1)


class _FixtureRuntime(ProbOSRuntime):
    def __init__(self, threads: ChatThreadStore, work_items: WorkItemStore, tool: _ProbeTool) -> None:
        self._event_listeners = []
        self._live_event_listeners = []
        self._event_listener_tasks = set()
        self._nats_events_wired = False
        self.nats_bus = None
        self.config = SystemConfig()
        self.config.agentic_dispatch.enabled = True
        self.config.agentic_loop.event_correlation_enabled = True
        self.config.dm_agentic = DmAgenticConfig(enabled=True)
        self.tool_registry = ToolRegistry()
        self.tool_registry.register(tool)
        self.tool_permission_store = ToolPermissionStore()
        self.capability_gap_driver = None
        self.intent_bus = None
        self.event_log = None
        self.work_item_store = work_items
        self.chat_thread_store = threads

    @property
    def attachment_store(self) -> None:
        return None

    def build_bounded_hxi_snapshot_base(self) -> dict[str, Any]:
        return {
            "agents": [
                {
                    "id": agent_id, "agent_type": "crew", "callsign": callsign,
                    "display_name": callsign, "pool": "bridge", "state": "active",
                    "confidence": 1.0, "trust": 0.5, "tier": "domain", "isCrew": True,
                }
                for agent_id, callsign in (("yeo", "Yeo"), ("other", "Other"))
            ],
            "connections": [], "pools": [], "system_mode": "active",
            "tc_n": 0.0, "routing_entropy": 0.0, "fresh_boot": False,
        }


class _StdioSocket:
    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()

    async def accept(self) -> None:
        self.accepted.set()

    async def send_text(self, payload: str) -> None:
        _send({"kind": "frame", "socket": self.identity, "frame": json.loads(payload)})

    async def receive_text(self) -> str:
        await self.closed.wait()
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if not self.closed.is_set():
            self.closed.set()
            _send({"kind": "socket_closed", "socket": self.identity, "code": code})


class ProgressBridge:
    def __init__(self) -> None:
        self.threads = _MemoryThreads()
        self.work_items = WorkItemStore(db_path=":memory:")
        self.tool = _ProbeTool()
        self.runtime = _FixtureRuntime(self.threads, self.work_items, self.tool)
        self.hub = WSEventStreamHub(self.runtime)
        self.listener: Any = None
        self.sockets: dict[str, _StdioSocket] = {}
        self.connections: list[asyncio.Task[None]] = []
        self.room = self.threads.create_thread(title="Other room", participants=["other"])

    async def start(self) -> None:
        await self.work_items.start()
        await self.hub.start()
        self.listener = await self.runtime.register_live_event_listener(self.hub.ingress)

    async def _start_turn(self, request: dict[str, Any]) -> dict[str, Any]:
        agent_id = request.get("agent", "yeo")
        if agent_id not in {"yeo", "other"}:
            raise ValueError("fixture_agent_invalid")
        thread_id = request.get("thread")
        thread = self.threads.get_thread(thread_id) if thread_id else self.threads.get_or_create_default_for_agent(
            agent_id, agent_id,
        )
        if thread is None or agent_id not in thread.participants:
            raise ValueError("fixture_thread_invalid")
        count = request.get("calls", 1)
        if type(count) is not int or not 1 <= count <= 65:
            raise ValueError("fixture_call_count_invalid")
        control = uuid.uuid4().hex
        turn: dict[str, Any] = {
            "entered": asyncio.Event(), "release": asyncio.Event(), "calls": 0,
            "contexts": [], "error": request.get("error") is True, "thread": thread.id,
        }
        self.tool.turns[control] = turn
        promoted = request.get("promoted") is True
        self.runtime.config.dm_agentic = DmAgenticConfig(
            enabled=True, promote_to_task_after_seconds=0.01 if promoted else 0,
        )
        agent = _conversational_agent(self.runtime, _ProbeLLM(control, count))
        agent.id = agent_id
        turn["agent"] = agent

        async def execute() -> str | None:
            result = await _conversation(agent, thread.id)
            _send({"kind": "chat_reply", "turn": control, "data": {"response": result, "thread_id": thread.id}})
            return result

        turn["task"] = asyncio.create_task(execute())
        await asyncio.wait_for(turn["entered"].wait(), 10)
        if promoted:
            await asyncio.wait_for(asyncio.shield(turn["task"]), 10)
        return {"turn": control, "thread": thread.to_dict(), "calls": turn["calls"], "promoted": promoted}

    async def command(self, request: dict[str, Any]) -> Any:
        operation = request["op"]
        if operation == "connect":
            identity = request["socket"]
            socket = _StdioSocket(identity)
            self.sockets[identity] = socket
            self.connections.append(asyncio.create_task(self.hub.serve(socket)))
            await asyncio.wait_for(socket.accepted.wait(), 5)
            return {"generation": self.hub.generation}
        if operation == "disconnect":
            await self.sockets[request["socket"]].close()
            return None
        if operation == "associate":
            if request["agent"] not in {"yeo", "other"}:
                raise ValueError("fixture_agent_invalid")
            return self.threads.get_or_create_default_for_agent(request["agent"], request["agent"]).to_dict()
        if operation == "thread":
            thread = self.threads.get_thread(request["thread"])
            return thread.to_dict() if thread else None
        if operation == "threads":
            return [thread.to_dict() for thread in self.threads.list_threads()]
        if operation == "messages":
            return [message.to_dict() for message in self.threads.list_messages(request["thread"])]
        if operation == "config":
            self.runtime.config.agentic_loop.event_correlation_enabled = request["enabled"] is True
            return None
        if operation == "start":
            return await self._start_turn(request)
        if operation == "release":
            turn = self.tool.turns[request["turn"]]
            turn["release"].set()
            await asyncio.wait_for(turn["task"], 10)
            await _drain_owned_tasks(turn["agent"]._promoted_turn_tasks)
            return {"calls": turn["calls"], "thread": turn["thread"]}
        if operation == "cancel":
            turn = self.tool.turns[request["turn"]]
            turn["task"].cancel()
            await asyncio.gather(turn["task"], return_exceptions=True)
            await _cancel_owned_tasks(turn["agent"]._promoted_turn_tasks)
            return {"calls": turn["calls"]}
        if operation == "resync":
            self.hub.request_resync()
            return None
        if operation == "room":
            return self.room.to_dict()
        raise ValueError("fixture_command_invalid")

    async def stop(self) -> None:
        for turn in self.tool.turns.values():
            turn["task"].cancel()
            await asyncio.gather(turn["task"], return_exceptions=True)
            await _cancel_owned_tasks(turn["agent"]._promoted_turn_tasks)
        if self.listener is not None:
            await self.listener.stop()
        await self.hub.stop()
        await asyncio.gather(*self.connections, return_exceptions=True)
        await self.work_items.stop()
        self.threads.close()


async def main() -> None:
    import probos.cognitive.swe_harness.agentic_loop as producer
    import probos.runtime as runtime
    import probos.ws_event_stream as wire

    root = Path(__file__).resolve().parents[2]
    assert Path(sys.argv[1]).resolve() == Path.cwd().resolve() == root
    assert Path(sys.executable).resolve() == Path(r"D:\ProbOS\.venv\Scripts\python.exe").resolve()
    for module in (producer, runtime, wire):
        assert Path(module.__file__).resolve().is_relative_to(root / "src")
    bridge = ProgressBridge()
    try:
        await bridge.start()
        _send({"kind": "ready", "root": str(root), "python": sys.executable,
               "producer": producer.__file__, "runtime": runtime.__file__, "hub": wire.__file__})
        while True:
            line = await asyncio.to_thread(sys.stdin.readline, 16_385)
            if not line:
                break
            if len(line) > 16_384:
                raise ValueError("fixture_command_too_large")
            request = json.loads(line)
            if request.get("op") == "stop":
                _send({"kind": "response", "id": request["id"], "data": None})
                break
            try:
                result = await bridge.command(request)
                _send({"kind": "response", "id": request["id"], "data": result})
            except Exception as exc:
                logger.exception("Isolated progress command failed; browser evidence is invalid and this command is rejected")
                _send({"kind": "response", "id": request["id"], "error": type(exc).__name__})
    except asyncio.CancelledError:
        raise
    finally:
        await bridge.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
