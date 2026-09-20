"""Owned local producer-to-HTTP fixture for the AD-1243 Python and UI jobs.

The scripted model and inert tool use owned runtime wiring. The agent lifecycle,
intent bus, trace producer, promotion, stores, reply append, and routes are production.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib
import json
import logging
import os
import socket
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

import httpx
import uvicorn

from probos.api import create_app
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.promoted_report_delivery import PromotedReportDeliveryService
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock
from probos.cognitive.turn_promotion import PROMOTION_SOURCE
from probos.config import DmAgenticConfig, SystemConfig
from probos.events import EventType
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThreadMessage, ChatThreadStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItemStore

SENSITIVE_SENTINEL = "AD1243_SYNTHETIC_SECRET_DoNotRender"
OUTPUT_SENTINEL = "AD1243_PRIVATE_OUTPUT_DoNotRender"
REPOSITORY = "langchain-ai/langchain"
REPLY_BODY = "Consulted the requested repository notes."


@dataclasses.dataclass
class _Turn:
    id: str
    mode: str
    agent: str
    thread_id: str
    query: str
    entered: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    release: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    llm_calls: int = 0
    tool_calls: int = 0
    response: dict[str, Any] | None = None
    task: asyncio.Task[httpx.Response] | None = None


class _ProbeTool:
    tool_id = "consulted_probe"
    name = tool_id
    description = "Read inert local repository notes in the owned test fixture."
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    input_schema = {
        "type": "object", "properties": {
            name: {"type": "string"}
            for name in ("control", "repoName", "query", "apiToken", "url")
        },
    }
    output_schema = {"type": "object"}

    def __init__(self, turns: dict[str, _Turn]) -> None:
        self.turns = turns

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        turn = self.turns[params["control"]]
        turn.tool_calls += 1
        turn.entered.set()
        await turn.release.wait()
        return ToolResult(output=OUTPUT_SENTINEL)


class _ScriptedLLM:
    def __init__(self) -> None:
        self.turn: _Turn | None = None

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        turn = self.turn
        assert turn is not None
        turn.llm_calls += 1
        if turn.llm_calls == 1:
            return LLMResponse(content="", tokens_used=1, content_blocks=[
                ToolUseBlock(tool_call=ToolCallRequest(
                    id=f"request-{turn.id}", name=_ProbeTool.tool_id, arguments={
                        "control": turn.id, "repoName": REPOSITORY, "query": turn.query,
                        "apiToken": SENSITIVE_SENTINEL,
                        "url": (
                            "https://fixture-user:" + SENSITIVE_SENTINEL
                            + "@example.test/repos/langchain?token=" + SENSITIVE_SENTINEL
                            + "#" + SENSITIVE_SENTINEL
                        ),
                    },
                )),
            ])
        assert turn.llm_calls == 2, "The evidence surface must not add model calls"
        return LLMResponse(content=REPLY_BODY, content_blocks=[], tokens_used=1)


class _ReceiptAgent(CognitiveAgent):
    agent_type = "research_specialist"
    instructions = "Use the inert consulted_probe once and report the requested repository notes."
    callsign = "Yeo"
    department = "science"
    rank = "lieutenant"

    async def finish_reports(self) -> None:
        async with asyncio.timeout(12):
            while self._promoted_turn_tasks:
                await asyncio.gather(*tuple(self._promoted_turn_tasks))
                await asyncio.sleep(0)

    async def cancel_reports(self) -> None:
        tasks = tuple(self._promoted_turn_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class _OwnedConnection(sqlite3.Connection):
    def __exit__(
        self, kind: type[BaseException] | None, value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            return super().__exit__(kind, value, traceback)
        finally:
            self.close()


class _ReceiptThreads(ChatThreadStore):
    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.fault_mode = ""
        self.report_attempts: list[dict[str, Any]] = []

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._db_path), isolation_level=None, factory=_OwnedConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def append_message_once(
        self, thread_id: str, *, message_id: str, author_id: str, role: str,
        body: str, created_at: float, metadata: dict | None = None,
        convergence_evidence: Any = None,
    ) -> Any:
        arguments = {
            "message_id": message_id, "author_id": author_id, "role": role,
            "body": body, "created_at": created_at, "metadata": metadata,
            "convergence_evidence": convergence_evidence,
        }
        promoted = (metadata or {}).get("source") == PROMOTION_SOURCE
        if promoted:
            self.report_attempts.append({"thread_id": thread_id, **arguments})
            if self.fault_mode == "outbox":
                raise sqlite3.OperationalError("owned fixture append unavailable")
        result = super().append_message_once(thread_id, **arguments)
        if promoted and self.fault_mode == "lost_ack":
            raise sqlite3.OperationalError("owned fixture acknowledgement lost")
        return result


class _FixtureOntology:
    def get_agent_department(self, agent_type: str) -> str | None:
        return "science" if agent_type == "research_specialist" else None

    def get_crew_agent_types(self) -> set[str]:
        return {"research_specialist"}


class _FixtureTrust:
    def get_score(self, agent_id: str) -> float:
        return 0.8


class _FixtureRuntime(ProbOSRuntime):
    def __init__(
        self, threads: _ReceiptThreads, work: WorkItemStore,
        attachments: FilesystemAttachmentStore, tool: _ProbeTool, data_dir: Path,
    ) -> None:
        self._event_listeners = []
        self._live_event_listeners = []
        self._event_listener_tasks = set()
        self._dispatch_loop = None
        self._nats_events_wired = False
        self.nats_bus = None
        self.config = SystemConfig()
        self._data_dir = data_dir
        self.config.agentic_dispatch.enabled = True
        self.config.dm_agentic = DmAgenticConfig(enabled=True)
        self.config.perception.enabled = False
        self.registry = AgentRegistry()
        self.ontology = _FixtureOntology()
        self.trust_network = _FixtureTrust()
        self.signal_manager = SignalManager()
        self.intent_bus = IntentBus(self.signal_manager)
        self.tool_registry = ToolRegistry()
        self.tool_registry.register(tool)
        self.tool_permission_store = ToolPermissionStore()
        self.capability_gap_driver = None
        self.event_log = None
        self.work_item_store = work
        self.chat_thread_store = threads
        self.attachments = attachments
        self.receipts_available = True
        self.episodic_memory = None
        self.promoted_report_delivery_service = None

    @property
    def attachment_store(self) -> FilesystemAttachmentStore | None:
        return self.attachments if self.receipts_available else None

    def bind_thread_events(self) -> None:
        self._dispatch_loop = asyncio.get_running_loop()
        self.chat_thread_store.set_message_committed_callback(self.message_committed)

    def message_committed(self, message: ChatThreadMessage) -> None:
        self._emit_from_any_thread(EventType.CHAT_THREAD_MESSAGE_APPENDED, {
            "thread_id": message.thread_id, "message_id": message.id,
            "author_id": message.author_id, "role": message.role,
            "created_at": message.created_at,
        })

    async def close_fixture_events(self) -> None:
        tasks = tuple(self._event_listener_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def build_bounded_hxi_snapshot_base(self) -> dict[str, Any]:
        return {
            "agents": [
                {
                    "id": agent.id, "agent_type": agent.agent_type,
                    "callsign": agent.callsign, "display_name": agent.callsign,
                    "pool": "science", "state": "active", "confidence": 1.0,
                    "trust": 0.5, "tier": "domain", "isCrew": True,
                }
                for agent in self.registry.all()
            ],
            "connections": [], "pools": [], "system_mode": "active",
            "tc_n": 0.0, "routing_entropy": 0.0, "fresh_boot": False,
        }


class ConsultedEvidenceFixture:
    """Own one bounded local runtime, real stores, and the production HTTP app."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.turns: dict[str, _Turn] = {}
        self.threads = _ReceiptThreads(data_dir / "threads.db")
        self.work = WorkItemStore(db_path=str(data_dir / "workforce.db"), tick_interval=1000.0)
        self.attachments = FilesystemAttachmentStore(data_dir / "attachments")
        self.runtime = _FixtureRuntime(
            self.threads, self.work, self.attachments, _ProbeTool(self.turns), data_dir,
        )
        self.agents: dict[str, _ReceiptAgent] = {}
        self.llms: dict[str, _ScriptedLLM] = {}
        self.app = create_app(self.runtime)
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[None] | None = None
        self.socket: socket.socket | None = None
        self.client: httpx.AsyncClient | None = None
        self.origin = ""

    async def start(self) -> None:
        await self.work.start()
        self.runtime.bind_thread_events()
        for identity, callsign in (("yeo", "Yeo"), ("other", "Other")):
            llm = _ScriptedLLM()
            agent = _ReceiptAgent(agent_id=identity, runtime=self.runtime, llm_client=llm)
            agent.callsign = callsign
            await self.runtime.registry.register(agent)
            self.runtime.intent_bus.subscribe(
                identity, agent.handle_intent, ["direct_message"],
                latency_class=agent.handler_latency_class,
            )
            self.agents[identity] = agent
            self.llms[identity] = llm
            self.threads.get_or_create_default_for_agent(identity, callsign)
        self.threads.create_thread(title="Other room", participants=["other"])
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.origin = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host="127.0.0.1", port=0, log_config=None, access_log=False,
            lifespan="on",
        ))
        self.server_task = asyncio.create_task(self.server.serve(sockets=[self.socket]))
        async with asyncio.timeout(10):
            while not self.server.started:
                if self.server_task.done():
                    await self.server_task
                    raise RuntimeError("Owned HTTP fixture stopped before startup")
                await asyncio.sleep(0.01)
        self.client = httpx.AsyncClient(base_url=self.origin, timeout=15, trust_env=False)

    async def stop(self) -> None:
        for turn in self.turns.values():
            turn.release.set()
            if turn.task is not None and not turn.task.done():
                turn.task.cancel()
        await asyncio.gather(
            *(turn.task for turn in self.turns.values() if turn.task is not None),
            return_exceptions=True,
        )
        for agent in self.agents.values():
            await agent.cancel_reports()
        if self.client is not None:
            await self.client.aclose()
        if self.server is not None:
            self.server.should_exit = True
        if self.server_task is not None:
            try:
                await asyncio.wait_for(self.server_task, timeout=8)
            finally:
                if not self.server_task.done():
                    self.server_task.cancel()
                    await asyncio.gather(self.server_task, return_exceptions=True)
        if self.socket is not None:
            self.socket.close()
        await self.runtime.close_fixture_events()
        await self.work.stop()

    async def start_turn(
        self, *, mode: str, agent: str = "yeo", thread_id: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"inline", "promoted", "outbox", "lost_ack"} or agent not in self.agents:
            raise ValueError("fixture_turn_invalid")
        await self.agents[agent].finish_reports()
        thread = (
            self.threads.get_thread(thread_id) if thread_id
            else self.threads.get_or_create_default_for_agent(agent, self.agents[agent].callsign)
        )
        if thread is None or agent not in thread.participants:
            raise ValueError("fixture_thread_invalid")
        previous_ids = {message.id for message in self.threads.list_messages(thread.id, limit=200)}
        turn = _Turn(uuid.uuid4().hex, mode, agent, thread.id, query or f"{mode}-{agent}-notes-café")
        self.turns[turn.id] = turn
        self.llms[agent].turn = turn
        self.runtime.config.dm_agentic.promote_to_task_after_seconds = 0.0 if mode == "inline" else 0.01
        self.threads.fault_mode = mode if mode in {"outbox", "lost_ack"} else ""
        if mode == "inline":
            turn.release.set()
        assert self.client is not None
        turn.task = asyncio.create_task(self.client.post(
            f"/api/agent/{agent}/chat",
            json={"message": "Read the requested local repository notes.", "thread_id": thread.id},
        ))
        async with asyncio.timeout(12):
            entered = asyncio.create_task(turn.entered.wait())
            try:
                done, _ = await asyncio.wait({entered, turn.task}, return_when=asyncio.FIRST_COMPLETED)
                if turn.task in done:
                    response = turn.task.result()
                    assert turn.entered.is_set(), f"Real tool not reached: {response.status_code} {response.text}"
                await entered
            finally:
                if not entered.done():
                    entered.cancel()
                await asyncio.gather(entered, return_exceptions=True)
            response = await turn.task
        assert response.status_code == 200, response.text
        turn.response = response.json()
        if mode != "inline":
            assert not turn.release.is_set() and turn.llm_calls == 1
            assert "I'm working it in the background" in turn.response["response"]
            assert not any(
                message.metadata.get("tool_trace_ref")
                for message in self.threads.list_messages(thread.id, limit=200)
                if message.id not in previous_ids
            )
        return await self.snapshot(turn.id)

    async def release_turn(self, turn_id: str) -> dict[str, Any]:
        turn = self.turns[turn_id]
        turn.release.set()
        await self.agents[turn.agent].finish_reports()
        assert turn.llm_calls == 2 and turn.tool_calls == 1
        return await self.snapshot(turn_id)

    async def snapshot(self, turn_id: str) -> dict[str, Any]:
        turn = self.turns[turn_id]
        return {
            "turn": turn.id, "mode": turn.mode, "agent": turn.agent,
            "thread": self.threads.get_thread(turn.thread_id).to_dict(),
            "messages": [message.to_dict() for message in self.threads.list_messages(turn.thread_id, limit=200)],
            "pending": [dataclasses.asdict(entry) for entry in await self.work.list_pending_promoted_reports(limit=50)],
            "reply": turn.response, "llm_calls": turn.llm_calls, "tool_calls": turn.tool_calls,
            "query": turn.query, "body": REPLY_BODY, "repo": REPOSITORY,
            "released": turn.release.is_set(),
            "attempts": list(self.threads.report_attempts),
        }

    async def recover(self, turn_id: str) -> dict[str, Any]:
        turn = self.turns[turn_id]
        await self.agents[turn.agent].finish_reports()
        before = await self.work.list_pending_promoted_reports(limit=50)
        assert len(before) == 1 and before[0].tool_trace_ref is not None
        await self.work.stop()
        self.work = WorkItemStore(db_path=str(self.data_dir / "workforce.db"), tick_interval=1000.0)
        await self.work.start()
        self.runtime.work_item_store = self.work
        assert await self.work.list_pending_promoted_reports(limit=50) == before
        self.threads.fault_mode = ""
        service = PromotedReportDeliveryService(outbox=self.work, threads=self.threads)
        assert await service.drain_pending() == 1
        assert await service.drain_pending() == 0
        result = await self.snapshot(turn_id)
        result["recovered"] = dataclasses.asdict(before[0])
        return result

    async def command(self, request: dict[str, Any]) -> Any:
        operation = request.get("op")
        if operation == "start":
            return await self.start_turn(
                mode=request["mode"], agent=request.get("agent", "yeo"),
                thread_id=request.get("thread"), query=request.get("query"),
            )
        if operation == "release":
            return await self.release_turn(request["turn"])
        if operation == "snapshot":
            return await self.snapshot(request["turn"])
        if operation == "recover":
            return await self.recover(request["turn"])
        if operation == "threads":
            return [thread.to_dict() for thread in self.threads.list_threads(limit=50)]
        if operation == "state":
            return self.runtime.build_bounded_hxi_snapshot_base()
        if operation == "auth":
            self.runtime.config.auth.crew_scope_token = request.get("token", "")
            return {"configured": bool(self.runtime.config.auth.crew_scope_token)}
        if operation == "receipt_store":
            self.runtime.receipts_available = request.get("available") is True
            return {"available": self.runtime.receipts_available}
        if operation == "stop":
            return {"stopping": True}
        raise ValueError("fixture_command_invalid")


def fixture_origins(root: Path) -> dict[str, str]:
    root = root.resolve()
    fixture = Path(__file__).resolve()
    if fixture != root / "tests" / "fixtures" / "consulted_evidence_bridge.py":
        raise ValueError("fixture_origin_mismatch")
    result = {"root": str(root), "python": sys.executable, "fixture": str(fixture)}
    for name, module in (
        ("producer", "probos.cognitive.agentic_dispatch"),
        ("agent", "probos.cognitive.cognitive_agent"),
        ("promotion", "probos.cognitive.turn_promotion"),
        ("delivery", "probos.cognitive.promoted_report_delivery"),
        ("workforce", "probos.workforce"), ("api", "probos.api"),
        ("traces", "probos.routers.traces"),
    ):
        source = Path(importlib.import_module(module).__file__).resolve()
        if not source.is_relative_to(root / "src"):
            raise ValueError("candidate_module_origin_mismatch")
        result[name] = str(source)
    return result


def _send(protocol: TextIO, value: dict[str, Any]) -> None:
    protocol.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")
    protocol.flush()


async def _serve(root: Path, protocol: TextIO, data_dir: Path | None = None) -> None:
    origins = fixture_origins(root)
    directory = (
        contextlib.nullcontext(str(data_dir.resolve())) if data_dir is not None
        else tempfile.TemporaryDirectory(prefix="probos-ad1243-owned-")
    )
    with directory as data:
        fixture = ConsultedEvidenceFixture(Path(data))
        try:
            await fixture.start()
            _send(protocol, {"kind": "ready", **origins, "origin": fixture.origin})
            async with asyncio.timeout(180):
                while True:
                    line = await asyncio.to_thread(sys.stdin.readline, 65_537)
                    if not line:
                        break
                    if len(line) > 65_536:
                        raise ValueError("fixture_command_too_large")
                    request = json.loads(line)
                    try:
                        data = await fixture.command(request)
                    except Exception as error:
                        logging.getLogger(__name__).exception(
                            "Owned consulted fixture command failed; the test must fail and cleanup follows",
                        )
                        _send(protocol, {
                            "kind": "response", "id": request["id"], "error": type(error).__name__,
                        })
                        break
                    _send(protocol, {"kind": "response", "id": request["id"], "data": data})
                    if request.get("op") == "stop":
                        break
        finally:
            await fixture.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    with os.fdopen(os.dup(1), "w", encoding="utf-8") as protocol:
        os.dup2(2, 1)
        with contextlib.redirect_stdout(sys.stderr):
            asyncio.run(_serve(
                Path(sys.argv[1]), protocol,
                Path(sys.argv[2]) if len(sys.argv) > 2 else None,
            ))
