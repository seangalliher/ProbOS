"""Owned loopback approval fixture: real authority, routing and transcript stores.

Only the final agent/tool execution bodies are inert. No runtime startup,
provider, browser, credentials, filesystem database or external service is used.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sqlite3
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, cast

import aiosqlite
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, model_validator

from probos.activation.dispatcher import Dispatcher
from probos.capability_request import (
    CapabilityRequestStore, can_fulfil_request, validate_action_payload,
)
from probos.cognitive.agentic_dispatch import DispatchToolExecutor, WorkItemAgenticOutcome
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.continue_or_ask import resolve_exhausted_turn
from probos.cognitive.queue import AgentCognitiveQueue
from probos.cognitive.repair_issue import IssueAttempt, RepairIssueFulfiller
from probos.config import ApprovalInboxConfig, DmAgenticConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.fault_issue_filings import IssueReceipt
from probos.fault_report import FaultReport, FaultReportStore
from probos.mesh.department_dispatcher import DepartmentDispatcher
from probos.mesh.work_item_router import WorkItemRouter
from probos.protocols import DatabaseConnection
from probos.routers import capability_requests, config as config_routes, threads
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThreadMessage, ChatThreadStore
from probos.tools.action_approvals import ActionApprovalStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage
from probos.workforce import WorkItem, WorkItemStore

CANDIDATE = Path(__file__).resolve().parents[2]
AGENT_ID = "approval-ui-agent"
TASK_TEXT = "Finish the isolated approval fixture task."
PARTIAL_TEXT = "The first fixture step is complete; the second step remains."
PRODUCTION_MODULES = (
    "probos.capability_request", "probos.tools.action_approvals", "probos.workforce",
    "probos.threads", "probos.cognitive.continue_or_ask",
    "probos.cognitive.capability_gap_driver", "probos.mesh.work_item_router",
    "probos.mesh.department_dispatcher", "probos.activation.dispatcher",
    "probos.cognitive.queue", "probos.cognitive.agentic_dispatch",
    "probos.routers.capability_requests", "probos.routers.threads",
    "probos.routers.config", "probos.runtime", "probos.consensus.trust",
    "probos.tools.registry",
    "probos.cognitive.repair_issue", "probos.fault_report", "probos.fault_issue_filings",
)


def module_origins() -> dict[str, str]:
    origins = {
        name: str(Path(importlib.import_module(name).__file__).resolve())
        for name in PRODUCTION_MODULES
    }
    if not all(Path(origin).is_relative_to(CANDIDATE / "src") for origin in origins.values()):
        raise RuntimeError("Approval fixture imported production code outside its candidate")
    return origins


def _numeric_boundary_payload(payload: dict[str, Any], characters: int) -> dict[str, Any]:
    bounded = deepcopy(payload)
    bounded["params"].update(x=1e-6, padding="")
    overhead = len(json.dumps(
        bounded, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ))
    bounded["params"]["padding"] = "x" * (characters - overhead)
    if validate_action_payload(bounded) is not bounded:
        raise AssertionError("Real backend validation refused the numeric boundary fixture")
    return bounded


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["continue", "action"]
    partial: bool = False
    approved_retry: bool = False
    numeric_boundary: bool = False
    numeric_overflow: Literal["positive", "negative"] | None = None

    @model_validator(mode="after")
    def validate_continue_options(self) -> ScenarioRequest:
        if self.kind != "continue" and (self.partial or self.approved_retry):
            raise ValueError("partial and approved_retry apply only to continue")
        if self.numeric_boundary and self.kind != "action":
            raise ValueError("numeric_boundary applies only to action")
        if self.numeric_overflow is not None and not self.numeric_boundary:
            raise ValueError("numeric_overflow requires numeric_boundary")
        return self


class FutureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    params: dict[str, Any] | None = None
    scope_key: str | None = Field(default=None, max_length=253, pattern=r"^[a-z0-9.-]*$")
    expired: bool = False
    agent_id: str | None = Field(default=None, min_length=1, max_length=64)
    action: Literal["compute_use_click", "upload_file"] | None = None


class MemoryDatabases:
    """Keep real shared SQLite memory databases alive across independent readers."""

    def __init__(self) -> None:
        self.connections: dict[str, sqlite3.Connection] = {}
        self.uris: dict[str, str] = {}
        self.readers: list[sqlite3.Connection] = []

    def open(self, name: str) -> str:
        if name in self.connections:
            raise ValueError("Memory database name is already owned")
        uri = f"file:approval-ui-{uuid.uuid4().hex}?mode=memory&cache=shared"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
        self.connections[name], self.uris[name] = connection, uri
        return uri

    def reader(self, name: str) -> sqlite3.Connection:
        connection = sqlite3.connect(self.uris[name], uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self.readers.append(connection)
        return connection

    def expire_actions(self) -> None:
        # Move the persisted lifetime, not the admission answer. Reloading the
        # real store below makes its SQL hydration and read-time expiry decide.
        expired_at = time.time() - 1
        self.connections["actions"].execute(
            "UPDATE action_approvals SET issued_at = issued_at - (expires_at - ?), "
            "expires_at = ?",
            (expired_at, expired_at),
        )

    def close(self) -> None:
        for connection in (*self.readers, *self.connections.values()):
            connection.close()
        self.readers.clear()
        self.connections.clear()


class _MemoryConnectionFactory:
    async def connect(self, db_path: str) -> DatabaseConnection:
        return cast(DatabaseConnection, await aiosqlite.connect(db_path, uri=True))


class _MemoryThreadStore(ChatThreadStore):
    """Only connection selection differs; every thread/message method is real."""

    def __init__(self, databases: MemoryDatabases) -> None:
        self.databases = databases
        databases.open("threads")
        super().__init__(Path(":memory:"))

    def _connect(self) -> sqlite3.Connection:
        return self.databases.reader("threads")


class _ExecutionAgent(BaseAgent):
    agent_type = "approval_ui_fixture"

    def __init__(self, work_items: WorkItemStore) -> None:
        super().__init__(agent_id=AGENT_ID)
        self.work_items = work_items
        self.calls: list[dict[str, Any]] = []

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return intent

    async def decide(self, observation: Any) -> Any:
        return observation

    async def act(self, plan: Any) -> Any:
        item = await self.work_items.get_work_item(plan["params"]["work_item_id"])
        if item is None or item.status != "in_progress":
            raise AssertionError("Execution reached a missing or still-blocked work item")
        call = {**deepcopy(plan), "agent_id": self.id, "work_status": item.status}
        self.calls.append(call)
        return {"executed": True, "work_item_id": item.id}

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    async def handle_intent(self, intent: IntentMessage) -> dict[str, Any]:
        observation = await self.perceive({"intent": intent.intent, "params": intent.params})
        return await self.report(await self.act(await self.decide(observation)))


class _BrowserExecutionSink:
    tool_id = "browser"
    name = "Isolated browser execution sink"
    tool_type = ToolType.BROWSER
    description = "Records admitted fixture calls without opening a browser."
    input_schema: dict[str, Any] = {"type": "object"}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.calls.append({"params": deepcopy(params), "context": deepcopy(context or {})})
        return ToolResult(output={"executed": True})


class _IssueExecutionSink:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create(self, repository: str, fault: FaultReport) -> IssueAttempt:
        self.calls.append(fault.id)
        if len(self.calls) == 1:
            return IssueAttempt(disposition="retryable_failure", failure_code="pre_send_failure")
        return IssueAttempt(
            disposition="filed",
            receipt=IssueReceipt(17, f"https://github.com/{repository}/issues/17"),
        )

    async def reconcile(self, repository: str, signature: str) -> IssueAttempt:
        raise AssertionError("Proven non-dispatch should permit explicit retry, not reconciliation")


class ApprovalUiBridge(ProbOSRuntime):
    """Minimal test wiring; inherited production event delivery, never vessel boot."""

    def __init__(self) -> None:
        self._event_listeners = []
        self._live_event_listeners = []
        self._event_listener_tasks: set[asyncio.Task[Any]] = set()
        self._nats_events_wired = False
        self.nats_bus = None
        self.config = SystemConfig(
            approval_inbox=ApprovalInboxConfig(enabled=True, standing_rules_enabled=True),
            dm_agentic=DmAgenticConfig(
                enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=2,
            ),
        )
        self.origins = module_origins()
        self.databases = MemoryDatabases()
        self.resources = AsyncExitStack()
        self.events: list[dict[str, Any]] = []
        self.decision_posts: list[dict[str, Any]] = []
        self.continuation_calls: list[dict[str, Any]] = []
        self.request_id: str | None = None
        self.work_item_id: str | None = None
        self.message: ChatThreadMessage | None = None
        self.notice = ""
        self.setup: dict[str, Any] = {}
        self.numeric_boundary: dict[str, Any] | None = None
        self.fault_store: FaultReportStore | None = None
        self.issue_sink: _IssueExecutionSink | None = None
        self.closed = False

    async def start(self) -> None:
        self.resources.callback(self.databases.close)
        try:
            self.trust_network = TrustNetwork()
            self.connection_factory = _MemoryConnectionFactory()
            self.capability_request_store = CapabilityRequestStore(
                self.databases.open("requests"), emit_event=self.emit_event,
                trust_network=self.trust_network, connection_factory=self.connection_factory,
            )
            self.action_approval_store = ActionApprovalStore(
                self.databases.open("actions"), connection_factory=self.connection_factory,
            )
            self.work_item_store = WorkItemStore(
                self.databases.open("work"), emit_event=self.emit_event, tick_interval=3600,
                connection_factory=self.connection_factory,
            )
            for store in (
                self.capability_request_store, self.action_approval_store, self.work_item_store,
            ):
                self.resources.push_async_callback(store.stop)
                await store.start()
            self.chat_thread_store = _MemoryThreadStore(self.databases)
            self.chat_thread_store.set_message_committed_callback(self.message_committed)
            self.resources.callback(self.chat_thread_store.set_message_committed_callback, None)
            self.registry = AgentRegistry()
            self.execution_agent = _ExecutionAgent(self.work_item_store)
            await self.registry.register(self.execution_agent)
            self.queue = AgentCognitiveQueue(
                agent_id=AGENT_ID, handler=self.execution_agent.handle_intent,
                emit_event=self.emit_event,
            )
            self.resources.push_async_callback(self.queue.shutdown)
            await self.queue.start()
            self.dispatcher = Dispatcher(
                registry=self.registry, ontology=None,
                get_queue=lambda agent_id: self.queue if agent_id == AGENT_ID else None,
                emit_event=self.emit_event,
            )
            self.work_item_router = WorkItemRouter(
                dispatcher=self.dispatcher, registry=self.registry,
                department_dispatcher=DepartmentDispatcher(
                    hebbian_router=None, ontology=None, config=self.config.hybrid_dispatch,
                ),
                config=self.config.hybrid_dispatch, emit_event=self.emit_event,
            )
            self.capability_gap_driver = CapabilityGapDriver(
                runtime=self, work_item_store=self.work_item_store,
                capability_request_store=self.capability_request_store,
            )
            self.add_event_listener(self.record_event)
            self.add_event_listener(
                self.capability_gap_driver.on_capability_event,
                event_types=(
                    EventType.CAPABILITY_REQUEST_DECIDED.value,
                    EventType.CAPABILITY_REQUEST_FULFILLED.value,
                ),
            )
            self.browser_sink = _BrowserExecutionSink()
            self.tool_registry = ToolRegistry()
            self.tool_registry.register(
                self.browser_sink, default_permissions={"commander": "full"},
            )
        except BaseException:
            await self.resources.aclose()
            self.closed = True
            raise

    def record_event(self, event: dict[str, Any]) -> None:
        self.events.append(deepcopy(event))

    def message_committed(self, message: ChatThreadMessage) -> None:
        self.emit_event(EventType.CHAT_THREAD_MESSAGE_APPENDED, {
            "thread_id": message.thread_id, "message_id": message.id,
            "author_id": message.author_id, "role": message.role,
            "created_at": message.created_at,
        })

    async def drain(self) -> None:
        async with asyncio.timeout(5):
            while self._event_listener_tasks or self.queue.pending_count() or self.queue.is_processing():
                if self._event_listener_tasks:
                    await asyncio.gather(*tuple(self._event_listener_tasks))
                await asyncio.sleep(0.001)

    async def stop(self) -> None:
        if self.closed:
            return
        try:
            await self.drain()
        finally:
            for task in tuple(self._event_listener_tasks):
                task.cancel()
            if self._event_listener_tasks:
                await asyncio.gather(*tuple(self._event_listener_tasks), return_exceptions=True)
            async with asyncio.timeout(10):
                await self.resources.aclose()
            self.closed = True

    async def _work_item(self, thread_id: str, agent_id: str = AGENT_ID) -> WorkItem:
        item = await self.work_item_store.create_work_item(
            title=TASK_TEXT, description=TASK_TEXT, work_type="task",
            assigned_to=agent_id, created_by="captain", tags=["conversational-turn"],
            metadata={"source": "dm_agentic_promotion", "thread_id": thread_id, "dispatchable": True},
        )
        updated = await self.work_item_store.transition_work_item(
            item.id, "in_progress", source=agent_id,
        )
        if updated is None:
            raise AssertionError("Fixture work item did not enter in_progress")
        return updated

    async def _numeric_boundary_rows(
        self, ordinary_id: str, thread_id: str, overflow_value: int | None = None,
    ) -> dict[str, Any]:
        faults = FaultReportStore(
            self.databases.open("faults"), connection_factory=self.connection_factory,
            emit_event=self.emit_event,
        )
        self.fault_store = faults
        self.resources.push_async_callback(faults.stop)
        await faults.start()
        for _ in range(2):
            fault = await faults.file_fault(
                tool_id="browser", error_text="unknown action: fixture_action",
                attempted="Perform an isolated fixture action", agent_id=AGENT_ID, thread_id=thread_id,
            )
        params: dict[str, Any] = {"fault_id": fault.id, "signature": fault.signature}
        if overflow_value is not None:
            params["value"] = overflow_value
        payload = _numeric_boundary_payload({
            "tool_id": "repair", "action": "dispatch", "scope_key": "browser",
            "params": params,
            "session_id": None, "thread_id": thread_id,
        }, 4000)
        repair = await self.capability_request_store.file_action_request(
            AGENT_ID, payload, rationale="Retry the isolated numeric-boundary repair.",
        )
        if repair is None or not can_fulfil_request(repair):
            raise AssertionError("Real repair subtype validation refused the boundary request")
        self.issue_sink = _IssueExecutionSink()
        self.repair_issue_fulfiller = RepairIssueFulfiller(
            requests=self.capability_request_store, filings=faults.issue_filings, client=self.issue_sink,
            repository="fixture/fixture", enabled=True, notify=lambda *args, **kwargs: None,
        )
        await self.capability_request_store.decide(
            repair.id, True, reason="Fixture repair approval awaiting explicit fulfilment retry",
        )
        if await self.repair_issue_fulfiller.fulfil(repair.id) is not None:
            raise AssertionError("Initial isolated filing must leave a real retryable failure")
        approved = await self.capability_request_store.get(repair.id, durable=True)
        filing = await faults.issue_filings.get(fault.signature)
        if (
            approved is None or approved.status != "approved" or not can_fulfil_request(approved)
            or filing is None or filing.disposition != "retryable_failure"
            or filing.failure_code != "pre_send_failure" or len(self.issue_sink.calls) != 1
        ):
            raise AssertionError("Boundary repair did not reach real approved Retry eligibility")
        unrelated_ids = []
        for number in (1, 2):
            unrelated = await self.capability_request_store.file_action_request(AGENT_ID, {
                "tool_id": "browser", "action": "compute_use_click", "params": {"x": number},
                "scope_key": f"unrelated-{number}.example", "session_id": None, "thread_id": thread_id,
            }, rationale=f"Unrelated actionable request {number}")
            if unrelated is None:
                raise AssertionError("Real request store refused an unrelated fixture row")
            unrelated_ids.append(unrelated.id)
        # Measure the production store's canonical strings, not a JS-derived boundary.
        stored = dict(self.databases.connections["requests"].execute(
            "SELECT id, payload FROM capability_requests WHERE id IN (?, ?)",
            (ordinary_id, repair.id),
        ))
        lengths = {request_id: len(encoded) for request_id, encoded in stored.items()}
        if lengths != {ordinary_id: 3998, repair.id: 4000}:
            raise AssertionError(f"Persisted Python canonical boundaries changed: {lengths}")
        await self.drain()
        return {
            "ordinary": {"request_id": ordinary_id, "python_characters": lengths[ordinary_id]},
            "repair": {"request_id": repair.id, "python_characters": lengths[repair.id],
                       "can_fulfil": can_fulfil_request(approved), "signature": fault.signature},
            "unrelated_request_ids": unrelated_ids,
        }

    async def scenario(self, options: ScenarioRequest) -> dict[str, Any]:
        overflow_value = None
        if options.numeric_overflow is not None:
            overflow_value = 10**309 if options.numeric_overflow == "positive" else -(10**309)
        thread = self.chat_thread_store.create_thread(
            title=TASK_TEXT, participants=["captain", AGENT_ID],
        )
        item = await self._work_item(thread.id)
        if options.kind == "continue":
            async def unexpected_reinvoke(_text: str) -> Any:
                raise AssertionError("An initial unapproved turn must not execute")

            self.notice = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text=PARTIAL_TEXT if options.partial else "", stopped_reason="max_iterations",
                ),
                reinvoke=unexpected_reinvoke, runtime=self, agent_id=AGENT_ID,
                base_task_text=TASK_TEXT, thread_id=thread.id,
                work_item_id=item.id, config=self.config.dm_agentic,
            )
            pending = await self.capability_request_store.list_pending()
            if len(pending) != 1:
                raise AssertionError("Real continue producer did not file exactly one request")
            request = pending[0]
            if f"(Request {request.id}.)" not in self.notice or len(request.id) != 36:
                raise AssertionError("Real continue notice lost its full request UUID")
        else:
            payload = {
                "tool_id": "browser", "action": "compute_use_click",
                "params": {"x": 12, "y": 24, "url": "https://approval.example/transfer"},
                "scope_key": "approval.example", "session_id": "original-session",
                "thread_id": thread.id,
            }
            if overflow_value is not None:
                payload["params"]["value"] = overflow_value
            if options.numeric_boundary:
                payload = _numeric_boundary_payload(payload, 3998)
            request = await self.capability_request_store.file_action_request(
                AGENT_ID, payload, rationale="Review the isolated consequential browser action.",
                work_item_id=item.id,
            )
            if request is None:
                raise AssertionError("Real action store refused the fixture payload")
            if not await self.capability_gap_driver.block_on_request(
                work_item_id=item.id, request_id=request.id, reason="Waiting for action review",
            ):
                raise AssertionError("Real driver did not block the fixture item")
            self.notice = request.rationale
        self.request_id, self.work_item_id = request.id, item.id
        self.message = self.chat_thread_store.append_message(
            thread.id, author_id=AGENT_ID, role="agent", body=self.notice,
        )
        if self.message is None or self.message.body != self.notice:
            raise AssertionError("Canonical thread storage did not retain the real notice")
        await self.drain()
        blocked = await self.work_item_store.get_work_item(item.id)
        if (
            request.status != "pending" or request.work_item_id != item.id
            or blocked is None or blocked.status != "blocked"
            or blocked.metadata.get("capability_request_id") != request.id
            or not self.work_item_router.is_dispatchable(blocked.to_dict())
            or self.execution_agent.calls or self.browser_sink.calls
        ):
            raise AssertionError("Approval setup did not reach the intended blocked, dispatchable seam")
        self.setup = {
            "request_status": request.status, "request_id": request.id, "work_item_id": item.id,
            "work_status": blocked.status, "router_predispatchable": True,
            "execution_count": 0, "author_id": self.message.author_id,
            "thread_id": self.message.thread_id,
        }
        if options.approved_retry:
            # A real recorded decision with fulfilment still outstanding. The
            # browser must exercise the existing retry route, never re-decide.
            await self.capability_request_store.decide(
                request.id, True, reason="Fixture approval awaiting explicit fulfilment retry",
            )
            await self.drain()
        if options.numeric_boundary:
            self.numeric_boundary = await self._numeric_boundary_rows(request.id, thread.id, overflow_value)
        return {
            "request_id": request.id, "work_item_id": item.id, "agent_id": AGENT_ID,
            "thread_id": thread.id, "notice": self.notice, "message": self.message.to_dict(),
            "setup": deepcopy(self.setup),
            "numeric_boundary": deepcopy(self.numeric_boundary),
        }

    async def future(self, options: FutureRequest) -> dict[str, Any]:
        request = await self.capability_request_store.get(self.request_id or "")
        if request is None:
            raise HTTPException(409, "Create a scenario before exercising a later run")
        if request.kind == "continue" and (
            options.params is not None or options.action is not None or options.scope_key not in (None, "")
        ):
            raise HTTPException(422, "Continue has exact empty scope and no action parameters")
        if options.expired:
            await self.action_approval_store.stop()
            self.databases.expire_actions()
            await self.action_approval_store.start()
        agent_id = options.agent_id or request.agent_id
        thread = self.chat_thread_store.create_thread(
            title="Later isolated run", participants=["captain", agent_id],
        )
        before = {row.id for row in await self.capability_request_store.list_pending()}
        if request.kind == "continue":
            item = await self._work_item(thread.id, agent_id)
            start = len(self.continuation_calls)

            async def reinvoke(text: str) -> WorkItemAgenticOutcome:
                self.continuation_calls.append({
                    "agent_id": agent_id, "thread_id": thread.id, "task_text": text,
                })
                return WorkItemAgenticOutcome(final_text="Later fixture turn completed.", stopped_reason="complete")

            result = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(final_text=PARTIAL_TEXT, stopped_reason="max_iterations"),
                reinvoke=reinvoke, runtime=self, agent_id=agent_id, base_task_text=TASK_TEXT,
                thread_id=thread.id, work_item_id=item.id, config=self.config.dm_agentic,
            )
            admitted = len(self.continuation_calls) == start + 1
            wire_result: Any = result
        else:
            payload = request.payload
            assert payload is not None
            scope = payload["scope_key"] if options.scope_key is None else options.scope_key
            params = {
                **deepcopy(payload["params"]), "session_id": f"future-{uuid.uuid4().hex}",
                "thread_id": thread.id, **(options.params or {}),
                "action": options.action or payload["action"],
                "url": f"https://{scope}/transfer" if scope else "",
            }
            executor = DispatchToolExecutor(registry=self.tool_registry)
            executor.arm_approval_inbox(
                request_store=self.capability_request_store, approval_store=self.action_approval_store,
                config=self.config.approval_inbox,
            )
            start = len(self.browser_sink.calls)
            tool_result = await executor.invoke(
                agent_id, payload["tool_id"], params,
                agent_department="engineering", agent_rank="commander",
            )
            admitted = len(self.browser_sink.calls) == start + 1
            wire_result = asdict(tool_result)
        await self.drain()
        new_requests = [
            asdict(row) for row in await self.capability_request_store.list_pending()
            if row.id not in before
        ]
        return {
            "admitted": admitted, "result": wire_result, "requests": new_requests,
            "thread_id": thread.id, "agent_id": agent_id,
        }

    async def state(self) -> dict[str, Any]:
        await self.drain()
        request = await self.capability_request_store.get(self.request_id or "", durable=True)
        item = await self.work_item_store.get_work_item(self.work_item_id or "")
        trust = self.trust_network.get_record(AGENT_ID)
        repair = None
        if self.numeric_boundary is not None:
            assert self.fault_store is not None and self.issue_sink is not None
            identity = self.numeric_boundary["repair"]
            repair_request = await self.capability_request_store.get(identity["request_id"], durable=True)
            filing = await self.fault_store.issue_filings.get(identity["signature"])
            repair = {
                "request": asdict(repair_request) if repair_request else None,
                "filing": asdict(filing) if filing else None,
                "issue_calls": deepcopy(self.issue_sink.calls),
            }
        return {
            "request": asdict(request) if request else None,
            "work_item": item.to_dict() if item else None,
            "action": {
                "approvals": [asdict(row) for row in await self.action_approval_store.list_approvals(False)],
                "active_approvals": [asdict(row) for row in await self.action_approval_store.list_approvals()],
            },
            "decision_posts": deepcopy(self.decision_posts), "decision_post_count": len(self.decision_posts),
            "events": deepcopy(self.events), "event_counts": dict(Counter(e["type"] for e in self.events)),
            "execution_calls": deepcopy(self.execution_agent.calls),
            "tool_calls": deepcopy(self.browser_sink.calls),
            "continuation_calls": deepcopy(self.continuation_calls),
            "router_predispatchable": self.work_item_router.is_dispatchable(item.to_dict()) if item else False,
            "message": self.message.to_dict() if self.message else None, "setup": deepcopy(self.setup),
            "trust": {"alpha": trust.alpha, "beta": trust.beta} if trust else None,
            "trust_outcomes": [asdict(event) for event in self.trust_network.get_events_for_agent(AGENT_ID)],
            "module_origins": self.origins, "candidate": str(CANDIDATE),
            "numeric_boundary": deepcopy(self.numeric_boundary), "repair": repair,
            "sqlite_files": {
                name: connection.execute("PRAGMA database_list").fetchone()[2]
                for name, connection in self.databases.connections.items()
            },
        }


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = ApprovalUiBridge()
        await app.state.runtime.start()
        try:
            yield
        finally:
            await app.state.runtime.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.server_id = uuid.uuid4().hex
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?",
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )
    app.include_router(capability_requests.router)
    # Mount actual APIRoutes, not lookalike fixture routes or a live API app.
    for owner, paths in (
        (threads.router, {"/api/threads/{thread_id}", "/api/threads/{thread_id}/messages"}),
        (config_routes.router, {"/api/config"}),
    ):
        app.router.routes.extend(
            route for route in owner.routes
            if route.path in paths and route.methods == {"GET"}
        )

    @app.middleware("http")
    async def record_decisions(request: Request, call_next: Any) -> Response:
        record = None
        if (
            request.method == "POST"
            and request.url.path.startswith("/api/capability-requests/")
            and request.url.path.endswith("/decide")
        ):
            try:
                body = await request.json()
            except ValueError:
                body = None
            record = {"path": request.url.path, "body": body}
            request.app.state.runtime.decision_posts.append(record)
        response = await call_next(request)
        if record is not None:
            record["status_code"] = response.status_code
        return response

    @app.get("/__approval_ui__/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": not app.state.runtime.closed, "service": "approval-ui-test-bridge",
            "server_id": app.state.server_id, "pid": os.getpid(), "parent_pid": os.getppid(),
            "candidate": str(CANDIDATE),
            "module_origins": app.state.runtime.origins,
        }

    @app.post("/__approval_ui__/scenario")
    async def scenario(options: ScenarioRequest) -> dict[str, Any]:
        await app.state.runtime.stop()
        app.state.runtime = ApprovalUiBridge()
        await app.state.runtime.start()
        return await app.state.runtime.scenario(options)

    @app.get("/__approval_ui__/state")
    async def state() -> dict[str, Any]:
        return await app.state.runtime.state()

    @app.post("/__approval_ui__/future")
    async def future(options: FutureRequest) -> dict[str, Any]:
        return await app.state.runtime.future(options)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    import uvicorn

    uvicorn.run(
        create_app(), host="127.0.0.1", port=args.port, access_log=False,
        log_level="warning", timeout_graceful_shutdown=5, proxy_headers=False,
    )


if __name__ == "__main__":
    main()
