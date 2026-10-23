"""AD-1347 S3 (#1627): the Ship's Computer runs agent-created work, parks it on the Captain's decision and reports it.

Real objects: ``WorkItemStore``, ``CapabilityRequestStore``, ``WardRoomService``, ``EventLog``, ``ToolRegistry`` with
``event_log_query`` and the work pull tools registered by their production functions, ``ToolPermissionStore``,
``AgentStopService``, ``VesselOntologyService``, ``AgentRegistry``, ``TrustNetwork``, AD-855's ``CapabilityGapDriver``,
the approval route's ``decide_capability_request``, the real ``WardRoomPostPipeline`` and extractor, and the real
``WorkItemAgenticExecutor`` driven by a scripted model. The stores' events are captured and delivered by ``_pump`` as
the runtime's listeners deliver them. On today's tree every test fails at import (``probos.agent_work_runner``).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import itertools
import json
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import probos.capability_request as request_module
import probos.routers.capability_requests as route_module
from probos.agent_stop import AgentStopService
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkService, open_agent_work_service
from probos.agent_work_runner import AGENT_WORK_READ_TOOL_IDS, AgentWorkRunner
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest, CapabilityRequestStore, agent_work_call
from probos.cognitive import agentic_dispatch
from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_FILED,
    CONFINED_CALL_NOT_FILED,
    ToolCallConfinement,
    WorkItemAgenticExecutor,
    classify_tool_fault_error,
)
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.crew_directory import RuntimeCrewDirectory
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.capability_request import can_fulfil_request
from probos.config import AgentWorkConfig, HybridDispatchConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.department_dispatcher import DepartmentDispatcher
from probos.mesh.work_item_router import WorkItemRouter
from probos.ontology import VesselOntologyService
from probos.proactive import ProactiveCognitiveLoop
from probos.routers.capability_requests import decide_capability_request, list_actionable_capability_requests
from probos.runtime import ProbOSRuntime
from probos.startup.communication import _register_event_log_query_tool, _register_work_item_pull_tools
from probos.substrate.event_log import EventLog
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolResultPresentation, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from probos.workforce import BookableResource, WorkItemStore
from tests.test_ad1347_s1_agent_work import CREW, ENSIGNS, LIFT_REASON, RANKS, REASON, STOP_REASON, WIRED, _SlotIdentities
from tests.test_ad1347_s2_chain_tags import REQUEST, _loop_runtime, _posts
from tests.test_ad864_crew_assignment import _make_registry
from tests.test_ad1154_approval_inbox import _TIER_3_URL, _armed, _invoke, _open_session
from tests.test_ad706_browser_tool import _FakePage
from tests.test_bf887_continue_resumes_the_promoted_turn import _Dispatcher

_REPO = Path(__file__).resolve().parents[1]
CALLSIGNS = {
    "laforge-1": "LaForge", "forge-1": "Forge", "forge-2": "Rookie", "worf-1": "Worf", "rahda-1": "Rahda",
    "bones-1": "Bones", "pulaski-1": "Pulaski", "ogawa-1": "Ogawa", "numberone-1": "Riker",
}
WINDOW = {"start_time": "2026-10-23T00:00:00Z", "end_time": "2026-10-23T01:00:00Z", "category": "agent_stop"}
ANSWER = "Two stop orders in the window, both lifted."
PRESENTATION = ToolResultPresentation(render_complete=repr)


class _ScriptedClient:
    """The model, scripted: a response, or an async callable that returns one (as tests/test_ad1187_agent_work_pull.py)."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        response = self.responses[len(self.requests) - 1]
        return await response(request) if callable(response) else response


def _call(tool_id: str, params: dict[str, Any], call_id: str = "c1") -> LLMResponse:
    return LLMResponse(content="", tokens_used=1, content_blocks=[ToolUseBlock(ToolCallRequest(name=tool_id, arguments=params, id=call_id))])


def _final(text: str = ANSWER) -> LLMResponse:
    return LLMResponse(content=text, tokens_used=1, content_blocks=[TextBlock(text)])


class _Survey:
    """A tool outside the read set that counts its runs (hull_survey, engineering)."""

    tool_id = "hull_survey"
    name = "Hull survey"
    tool_type = ToolType.INFRA_SERVICE
    description = "Reads the hull sensors and writes a survey record."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output="Hull integrity 98 percent; survey record written.")


@dataclass
class _Rig:
    service: AgentWorkService
    store: WorkItemStore
    tools: ToolRegistry
    permissions: ToolPermissionStore
    stops: AgentStopService
    agents: dict[str, Any]
    wr: Any
    requests: Any
    driver: Any
    runner: AgentWorkRunner
    llm: _ScriptedClient
    survey: _Survey
    runtime: Any
    pipeline: Any
    work_events: list[tuple[Any, dict[str, Any]]]
    request_events: list[tuple[Any, dict[str, Any]]]
    data: Path


@contextlib.asynccontextmanager
async def _rig(
    tmp_path: Path, script: list[Any], *, section: AgentWorkConfig | None = None,
    clock: Callable[[], float] | None = None, max_pending: int = 20,
) -> AsyncIterator[_Rig]:
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(_REPO / "config" / "ontology", ontology_dir)
    (tmp_path / "ontology-data").mkdir()
    ontology = VesselOntologyService(ontology_dir, data_dir=tmp_path / "ontology-data")
    await ontology.initialize()
    for agent_type, slot in WIRED:
        ontology.wire_agent(agent_type, slot)
    registry = await _make_registry(list(CREW))
    agents = {agent.id: agent for agent in registry.all()}
    trust = TrustNetwork()
    for slot in ENSIGNS:
        trust.create_with_prior(slot, 1.0, 3.0)
    work_events: list[tuple[Any, dict[str, Any]]] = []
    request_events: list[tuple[Any, dict[str, Any]]] = []
    permissions = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    stops = AgentStopService(data_dir=tmp_path / "stops")
    event_log = EventLog(tmp_path / "events.db")
    requests = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"), emit_event=lambda kind, data: request_events.append((kind, data)))
    wr = WardRoomService(db_path=str(tmp_path / "wr.db"))
    runtime = object.__new__(ProbOSRuntime)  # the attributes the pull authority and the run read, as S1's _ship does
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"), tick_interval=1000.0,
        pull_resource_resolver=runtime.resolve_workforce_pull_resource,
        emit_event=lambda kind, data: work_events.append((kind, data)),
    )
    tools = ToolRegistry()
    survey = _Survey()
    started: list[Any] = []
    runner: AgentWorkRunner | None = None
    try:
        for agent in agents.values():
            await agent.start()
        for component in (permissions, stops, event_log, requests, wr):
            await component.start()
            started.append(component)
        tools.set_permission_store(permissions)
        tools.set_stop_gate(stops)
        _register_event_log_query_tool(tool_registry=tools, enabled=True, event_log_reader=event_log, event_log_audit_sink=event_log)
        tools.register(survey, allowed_departments=("engineering",), default_permissions=dict.fromkeys(RANKS, "read"))
        await permissions.issue_grant("forge-1", "hull_survey", ToolPermission.READ)
        runtime.config = SystemConfig()
        runtime.registry = registry
        runtime.ontology = ontology
        runtime.trust_network = trust
        runtime.tool_registry = tools
        runtime.tool_permission_store = permissions
        runtime.work_item_store = store
        runtime.event_log = event_log
        runtime.capability_request_store = requests
        runtime.intent_bus = None
        for slot, agent in agents.items():
            store.register_resource(BookableResource(resource_id=slot, agent_type=agent.agent_type, department="", capacity=5, characteristics=[]))
        await store.start()
        started.append(store)
        _register_work_item_pull_tools(tool_registry=tools, work_item_store=store, pull_resource_resolver=runtime.resolve_workforce_pull_resource)
        directory = RuntimeCrewDirectory(agent_registry=registry, ontology=ontology, trust_network=trust)
        service = await open_agent_work_service(
            config=section or AgentWorkConfig(enabled=True), store=store, tools=tools,
            identities=_SlotIdentities(agents), directory=directory, stop_gate=stops, clock=clock or time.time,
        )
        assert isinstance(service, AgentWorkService)
        runtime.agent_work = service
        driver = CapabilityGapDriver(runtime=runtime, work_item_store=store, capability_request_store=requests)
        runtime.capability_gap_driver = driver
        llm = _ScriptedClient(script)
        runner = AgentWorkRunner(
            service=service, store=store, ward_room=wr, tools=tools, requests=requests, parking=driver,
            executor=WorkItemAgenticExecutor(llm_client=llm), runtime=runtime, agents=registry,
            callsign_of=lambda slot: CALLSIGNS.get(slot, slot), max_pending=max_pending,
            ttl_seconds=(section or AgentWorkConfig(enabled=True)).ttl_seconds,
        )
        runtime.agent_work_runner = runner
        loop_runtime = _loop_runtime(service, trust)
        loop_runtime.ward_room = wr
        loop_runtime.agent_work_runner = runner
        loop = ProactiveCognitiveLoop(cooldown=0)
        loop.set_runtime(loop_runtime)
        router = MagicMock(spec=WardRoomRouter)
        router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, callsign: text)
        pipeline = WardRoomPostPipeline(
            ward_room=wr, ward_room_router=router, proactive_loop=loop, trust_network=None,
            callsign_registry=None, config=MagicMock(),
        )
        yield _Rig(
            service, store, tools, permissions, stops, agents, wr, requests, driver, runner, llm, survey, runtime,
            pipeline, work_events, request_events, tmp_path,
        )
    finally:
        if runner is not None:
            await runner.stop()
        for component in reversed(started):
            await component.stop()
        for agent in agents.values():
            if agent.is_alive:
                await agent.stop()


async def _pump(rig: _Rig) -> None:
    """Deliver the stores' events as the runtime's listeners do, and wait for every run, until nothing is left."""
    for _ in range(20):
        work = list(rig.work_events)
        rig.work_events.clear()
        asked = list(rig.request_events)
        rig.request_events.clear()
        for kind, data in work:
            await rig.runner.on_store_event({"type": getattr(kind, "value", kind), "data": data})
        for kind, data in asked:
            await rig.driver.on_capability_event({"type": getattr(kind, "value", kind), "data": data})
        await asyncio.gather(*rig.runner.running)
        idle = all(task.done() for task in rig.runner.running)  # A1 (F2): a run's end can start the next
        if not work and not asked and not rig.work_events and not rig.request_events and idle:
            return
    raise AssertionError("the stores kept emitting")


async def _thread_in(rig: _Rig, department: str, author: str) -> Any:
    channel = await rig.wr.get_channel_by_department(department)
    return await rig.wr.create_thread(channel.id, author, "Relay drift", "The relay drifted twice.", author_callsign=CALLSIGNS[author])


def _system_posts(rig: _Rig, thread_id: str) -> list[str]:
    return [body for author, body in _posts(rig.data / "wr.db", thread_id) if author == "system"]


def _events(rig: _Rig, category: str, event: str) -> list[tuple[str, dict[str, Any]]]:
    with contextlib.closing(sqlite3.connect(rig.data / "events.db")) as raw:
        rows = raw.execute("SELECT agent_id, data FROM events WHERE category = ? AND event = ?", (category, event)).fetchall()
    return [(agent_id, json.loads(data) if data else {}) for agent_id, data in rows]


def _seen(rig: _Rig, text: str) -> bool:
    """Whether the model was shown ``text`` (in the plain or the structured transcript)."""
    for request in rig.llm.requests:
        if text in (request.prompt or "") or any(text in str(message.get("content", "")) for message in (request.messages or [])):
            return True
    return False


async def _with_tool(rig: _Rig, slot: str, tool_id: str, params: dict[str, Any]) -> Any:
    member = rig.service.crew_member(slot)
    assert member is not None, slot
    required = ToolPermission.READ if tool_id == "discover_work_items" else ToolPermission.WRITE
    return await rig.tools.check_and_invoke(
        slot, tool_id, params, required=required, agent_department=member.department, agent_rank=member.rank,
        agent_types=[member.agent_type], context={"agent_id": slot, "_tool_result_presentation": PRESENTATION},
    )


async def _request(rig: _Rig, requester: str, thread_id: str) -> str:
    created = await rig.service.request_work(
        requester, title="Read the EventLog window", description="", reason=REASON,
        origin=AgentWorkOrigin("ward_room", thread_id=thread_id), tool_id="event_log_query",
    )
    assert isinstance(created, AgentWorkCreated), created
    return created.work_item.id


def _watch_runs(
    monkeypatch: pytest.MonkeyPatch,
    then: Callable[[dict[str, Any], Any], Awaitable[Any]] | None = None,
) -> list[dict[str, Any]]:
    """A1: wrap ``WorkItemAgenticExecutor.run``; each entry is recorded before the run and its outcome after it.
    ``then`` stands in for what the executor itself does after its loop (AD-1324's own parking, X16)."""
    runs: list[dict[str, Any]] = []
    original = WorkItemAgenticExecutor.run

    async def _run(self: Any, **kwargs: Any) -> Any:
        entry: dict[str, Any] = {"agent_id": kwargs.get("agent_id"), "outcome": None}
        runs.append(entry)
        outcome = await original(self, **kwargs)
        if then is not None:
            outcome = await then(kwargs, outcome)
        entry["outcome"] = outcome
        return outcome

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", _run)
    return runs


# X1
async def test_a_chain_request_is_announced_claimed_run_and_reported_in_its_origin_thread(tmp_path: Path) -> None:
    """Acceptance 2: the chain tag, the item, the notice, the claim, the run with event_log_query, the post in the thread."""
    async with _rig(tmp_path, [_call("event_log_query", WINDOW), _final()]) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["pulaski-1"], response_text=f"I need the event log for that window.\n{REQUEST}",
            thread_id=origin.id, event_type="ward_room_thread_created",
        )
        [item] = await rig.store.list_agent_work(False, None, 10)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert notice.author_id == "system" and item.id in notice.body and notice.max_responders == 2
        assert "@Forge" in notice.body and "@LaForge" in notice.body
        assert "@Rookie" not in notice.body and "@Worf" not in notice.body and "@Rahda" not in notice.body
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"Taking it.\n[CLAIM_WORK {item.id}]",
            thread_id=notice.id, event_type="ward_room_thread_created",
        )
        await asyncio.gather(*rig.runner.running)  # the chain's claim starts the run itself
        done = await rig.store.get_work_item(item.id)
        assert done is not None and (done.status, done.assigned_to, done.created_by) == ("done", "forge-1", "pulaski-1")
        await _pump(rig)
        [booking] = await rig.store.list_bookings(work_item_id=item.id)
        assert (booking.resource_id, booking.status) == ("forge-1", "completed")
        assert any(agent == "forge-1" and data.get("outcome") == "success" for agent, data in _events(rig, "audit", "event_log_query"))
        assert any(data.get("work_item_id") == item.id and data.get("is_error") is False for _, data in _events(rig, "tool", "tool_invoked"))
        [report] = _system_posts(rig, origin.id)
        assert ANSWER in report and item.id in report and "@Pulaski" in report and "check it against the record" in report
        acks = [body for author, body in _posts(rig.data / "wr.db", notice.id) if author == "forge-1"]
        assert len(acks) == 1 and "you claimed work item" in acks[0]
        assert len(rig.llm.requests) == 2


# X2
async def test_a_call_outside_the_read_set_parks_the_item_and_an_approval_runs_it_exactly_once(tmp_path: Path) -> None:
    """Acceptance 4: filed, nothing run; approved, the item resumes and the call runs once; a repeat is filed; denied,
    the item ends and the Captain's reason reaches the origin thread."""
    script = [
        _call("hull_survey", {}), _final("Waiting for the Captain."),
        _call("hull_survey", {}, "c1"), _call("hull_survey", {}, "c2"), _final("Surveyed once."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey the hull", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        item_id = created.work_item.id
        await _pump(rig)
        parked = await rig.store.get_work_item(item_id)
        assert parked is not None and parked.status == "blocked" and rig.survey.calls == 0
        first_id = parked.metadata["capability_request_id"]
        first = await rig.requests.get(first_id)
        assert (first.kind, first.status, first.agent_id, first.work_item_id) == ("action", "pending", "forge-1", item_id)
        assert (first.payload["tool_id"], first.payload["action"], first.payload["scope_key"]) == (
            "hull_survey", "agent_work_call", f"agent_work:{item_id}",
        )
        assert _seen(rig, CONFINED_CALL_FILED)
        captain = SimpleNamespace(capability_request_store=rig.requests)
        approved = await decide_capability_request(first_id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert approved["fulfilled"] is True
        await _pump(rig)
        again = await rig.store.get_work_item(item_id)
        assert rig.survey.calls == 1, "the approval admits the call it was asked for, once"
        assert again is not None and again.status == "blocked"
        second_id = again.metadata["capability_request_id"]
        assert second_id != first_id and (await rig.requests.get(second_id)).status == "pending"
        denied = await decide_capability_request(
            second_id, CapabilityRequestDecideRequest(approve=False, reason="once is enough"), runtime=captain,
        )
        assert denied["fulfilled"] is False
        await _pump(rig)
        ended = await rig.store.get_work_item(item_id)
        assert ended is not None and ended.status == "cancelled" and rig.survey.calls == 1
        [report] = _system_posts(rig, origin.id)
        assert "once is enough" in report and "@Forge" in report


# X3
@pytest.mark.parametrize("cause", ["stop_before_run", "restricted_before_run", "stop_during_run"])
async def test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str,
) -> None:
    """Acceptance 5 and blind spot 7: never failed; the booking is cancelled; the member may claim it again once allowed.
    A1 (F14): a refusal before the run is made before the executor is entered, not by the run entry's own stop check."""
    holder: dict[str, Any] = {}
    runs = _watch_runs(monkeypatch)

    async def _stop_then_read(request: LLMRequest) -> LLMResponse:
        await holder["rig"].stops.issue_stop("forge-1", reason=STOP_REASON)
        return _call("event_log_query", WINDOW)

    script = [_stop_then_read, _final("partial")] if cause == "stop_during_run" else []
    async with _rig(tmp_path, script) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        claim = await _with_tool(rig, "forge-1", "claim_work_item", {"work_item_id": item_id})
        assert ast.literal_eval(claim.output)["owned"] is True
        restriction = None
        if cause == "stop_before_run":
            await rig.stops.issue_stop("forge-1", reason=STOP_REASON)
        elif cause == "restricted_before_run":
            restriction = await rig.permissions.issue_grant("forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True)
        await _pump(rig)  # WORK_ITEM_CLAIMED starts the run
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["cancelled"]
        assert _system_posts(rig, origin.id) == []
        if cause == "stop_during_run":
            [stop] = rig.stops.active()
            assert rig.stops.refused_counts(stop.stop_id) == {"tool": 1}
            assert [run["agent_id"] for run in runs] == ["forge-1"]
        else:
            assert rig.llm.requests == [] and runs == []  # refused before the executor was entered (A1, F14)
        if restriction is not None:
            await rig.permissions.revoke_grant(restriction.id)
        else:
            await rig.stops.lift_stop("forge-1", reason=LIFT_REASON)
        discovered = await _with_tool(rig, "forge-1", "discover_work_items", {})
        assert item_id in [entry["id"] for entry in ast.literal_eval(discovered.output)["items"]]


# X4
async def test_every_watcher_of_a_deduplicated_request_gets_the_report(tmp_path: Path) -> None:
    """Blind spot 6: dedup must not drop a watcher's answer."""
    async with _rig(tmp_path, [_call("event_log_query", WINDOW), _final()]) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        other = await _thread_in(rig, "medical", "ogawa-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", other.id) == item_id
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        [report] = _system_posts(rig, origin.id)
        assert "@Pulaski" in report and "@Ogawa" in report and ANSWER in report
        assert await rig.service.terminal_notices_due() == ()


# X5
async def test_an_expired_request_tells_each_recipient_once_across_two_overlapping_deliveries(tmp_path: Path) -> None:
    section = AgentWorkConfig(enabled=True, ttl_seconds=60)
    async with _rig(tmp_path, [], section=section, clock=lambda: time.time() - 120) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", origin.id) == item_id
        assert await rig.store.transition_work_item(item_id, "cancelled", source="ttl_expiry") is not None  # as the sweep does
        told = await asyncio.gather(rig.runner.deliver_due_notices(), rig.runner.deliver_due_notices())
        assert sorted(told) == [0, 2]
        await _pump(rig)
        [notice] = _system_posts(rig, origin.id)
        assert "expired before anyone produced a result" in notice and "@Pulaski" in notice and "@Ogawa" in notice
        engineering = await rig.wr.get_channel_by_department("engineering")
        assert await rig.wr.list_threads(engineering.id) == []  # an ended request is not announced


# X6
async def test_two_overlapping_starts_run_an_item_once(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_final()]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await asyncio.gather(rig.runner.resume(created.work_item.id), rig.runner.resume(created.work_item.id))
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done"
        assert len(rig.llm.requests) == 1 and len(_system_posts(rig, origin.id)) == 1


# X7
async def test_a_decline_is_recorded_once_and_its_reason_reaches_the_requester(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", origin.id) == item_id  # a watcher (A1, F8)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"[DECLINE_WORK {item_id}]\nOn the warp core all shift.\n[/DECLINE_WORK]",
            thread_id=notice.id, event_type="ward_room_thread_created",
        )
        assert (await rig.runner.decline("forge-1", item_id, "again"))[0] == "repeated"
        assert (await rig.runner.decline("worf-1", item_id, "not mine"))[0] == "refused"
        [relay] = _system_posts(rig, origin.id)
        assert "declined" in relay and "warp core" in relay and "@Pulaski" in relay and "@Ogawa" in relay
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)


# X8
async def test_an_ensign_or_another_department_cannot_claim_through_the_chain(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        for slot in ("forge-2", "worf-1"):
            await rig.pipeline.process_and_post(
                agent=rig.agents[slot], response_text=f"Mine.\n[CLAIM_WORK {item_id}]",
                thread_id=notice.id, event_type="ward_room_thread_created",
            )
        posts = dict(_posts(rig.data / "wr.db", notice.id))
        assert "was not claimed by you" in posts["worf-1"]
        assert "Ship's Computer" not in posts.get("forge-2", "")  # an ensign's tag is stripped and nothing is done
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert rig.runner.running == ()


# X9
@pytest.mark.parametrize(("verdict", "expected"), [
    ("admit", None), ("filed", CONFINED_CALL_FILED), ("refused", CONFINED_CALL_NOT_FILED), ("anything", CONFINED_CALL_NOT_FILED),
])
async def test_the_confinement_gate_decides_every_call_outside_its_set(verdict: str, expected: str | None) -> None:
    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        return verdict

    result = await ToolCallConfinement(frozenset({"event_log_query"}), gate).refuse_or_admit("forge-1", "hull_survey", {})
    assert (result.error if result is not None else None) == expected


async def test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome() -> None:
    async def broken(agent_id: str, tool_id: Any, params: Any) -> str:
        raise RuntimeError("store down")

    result = await ToolCallConfinement(frozenset({"event_log_query"}), broken).refuse_or_admit("forge-1", "hull_survey", {})
    assert result is not None and result.error == CONFINED_CALL_NOT_FILED
    for text in (CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED):
        assert text in agentic_dispatch._NEVER_RAN_REFUSALS
        assert not is_capability_gap(text)
        assert classify_tool_fault_error(text) == "permission_denied"
    for tool_ids, gate in ((frozenset(), broken), ({"x"}, broken), (frozenset({"x"}), "not callable")):
        with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
            ToolCallConfinement(tool_ids, gate)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
        await WorkItemAgenticExecutor(llm_client=_ScriptedClient([])).run(
            agent_id="forge-1", instructions="", task_text="x", runtime=SimpleNamespace(),
            plan_mode_tool_ids=frozenset({"event_log_query"}), confinement=ToolCallConfinement(frozenset({"x"}), broken),
        )
    assert AGENT_WORK_READ_TOOL_IDS <= PLAN_MODE_TOOL_IDS
    assert not AGENT_WORK_READ_TOOL_IDS & {"web_search", "read_page", "http_fetch", "discover_work_items"}


# X10
async def test_a_full_approval_inbox_refuses_the_call_without_filing_it(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_call("hull_survey", {}), _final()], max_pending=0) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done" and rig.survey.calls == 0
        assert rig.requests.count_pending_sync("forge-1") == 0
        assert _seen(rig, CONFINED_CALL_NOT_FILED)


# X11
async def test_recover_runs_work_a_previous_start_left_unfinished(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_final()]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        rig.work_events.clear()  # the created event was lost with the previous start
        assert await rig.runner.recover() == 1
        await asyncio.gather(*rig.runner.running)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done"


# X12
async def test_an_ordinary_item_still_resumes_through_the_work_item_router(tmp_path: Path) -> None:
    """Regression, through the real ``WorkItemRouter`` (A1, F14): a dispatchable item resumes into one admission at the
    activation queue (the dispatcher records it); a tagless item is the negative control the router declines."""
    async with _rig(tmp_path, []) as rig:
        queue = _Dispatcher()
        hybrid = HybridDispatchConfig()
        rig.runtime.work_item_router = WorkItemRouter(
            dispatcher=queue, department_dispatcher=DepartmentDispatcher(hebbian_router=None, ontology=None, config=hybrid),
            registry=rig.runtime.registry, config=hybrid,
        )
        for title, tags, admitted in (("Consult", ["consultation"], 1), ("Plain task", [], 0)):
            plain = await rig.store.create_work_item(title=title, assigned_to="forge-1", tags=tags)
            asked = await rig.requests.file_request(agent_id="forge-1", kind="continue", target="continue", work_item_id=plain.id)
            assert await rig.driver.block_on_request(work_item_id=plain.id, request_id=asked.id, reason="waiting")
            await rig.requests.decide(asked.id, True)
            await rig.requests.mark_fulfilled(asked.id)
            await _pump(rig)
            assert [event.source_id for event in queue.events].count(plain.id) == admitted, title
        assert rig.llm.requests == [] and rig.runner.running == ()


_WIRE = _REPO / "ui" / "e2e" / "fixtures" / "ad1347-agent-work-approvals.json"


# X13
async def test_an_agent_work_approval_crosses_the_hxi_wire_fulfilled_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F1): the route's real envelopes are the shared fixture the HXI decoder test reads
    (``ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts``); only the call bound to its own item is fulfillable."""
    from probos.agent_work_runner import approval_payload

    ids = itertools.count(1)
    monkeypatch.setattr(request_module, "uuid", SimpleNamespace(uuid4=lambda: f"00000000-0000-0000-0000-{next(ids):012d}"))
    monkeypatch.setattr(request_module, "time", SimpleNamespace(time=lambda: 1000.0))
    wire = json.loads(_WIRE.read_text(encoding="utf-8"))
    requests = CapabilityRequestStore(db_path=str(tmp_path / "requests.db"))
    await requests.start()
    try:
        captain = SimpleNamespace(capability_request_store=requests)
        rationale = "agent work wi-agent called hull_survey, outside the read-only set"
        first = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 2}, "wi-agent-work-1"), rationale=rationale,
            work_item_id="wi-agent-work-1",
        )
        assert await list_actionable_capability_requests(captain) == wire["pending"]
        assert await decide_capability_request(first.id, CapabilityRequestDecideRequest(approve=True), runtime=captain) == wire["fulfilled"]
        second = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 3}, "wi-agent-work-1"), rationale=rationale,
            work_item_id="wi-agent-work-1",
        )
        await requests.decide(second.id, True)  # approved; its fulfilment has not happened yet
        assert await list_actionable_capability_requests(captain) == wire["approved"]
        retried = await decide_capability_request(second.id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert retried["fulfilled"] is True and (await list_actionable_capability_requests(captain))["requests"] == []
        stored = await requests.get(second.id)
        assert stored is not None
        bound = replace(stored, status="approved")
        assert can_fulfil_request(bound)
        for unbound in (
            replace(bound, work_item_id="wi-other"), replace(bound, work_item_id=None),
            replace(bound, payload={**bound.payload, "action": "click"}),
        ):
            assert not can_fulfil_request(unbound)
    finally:
        await requests.stop()


# X14
async def test_an_approval_that_settles_before_the_run_parks_still_runs_the_call_once(tmp_path: Path) -> None:
    """A1 (F2): the Captain approves while the run that filed the call is still finishing; BF-878 resumes the item at
    the park, and that start, made during the run, runs after it."""
    holder: dict[str, Any] = {}

    async def _approve_then_answer(request: LLMRequest) -> LLMResponse:
        rig = holder["rig"]
        [asked] = await rig.requests.list_pending()
        captain = SimpleNamespace(capability_request_store=rig.requests)
        assert (await decide_capability_request(asked.id, CapabilityRequestDecideRequest(approve=True), runtime=captain))["fulfilled"]
        settled = list(rig.request_events)
        rig.request_events.clear()
        for kind, data in settled:  # the driver hears both events now, while the item is not yet parked
            await rig.driver.on_capability_event({"type": getattr(kind, "value", kind), "data": data})
        return _final("Waiting for the Captain.")

    script = [_call("hull_survey", {}), _approve_then_answer, _call("hull_survey", {}), _final("Surveyed once.")]
    async with _rig(tmp_path, script) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey the hull", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done" and rig.survey.calls == 1
        assert len(rig.llm.requests) == 4
        [report] = _system_posts(rig, origin.id)
        assert "Surveyed once." in report


# X15
async def test_an_admitted_confined_call_is_not_parked_again_by_the_approval_inbox(tmp_path: Path) -> None:
    """A1 (F3): with AD-1154's inbox armed (the live configuration), the one call a confinement admits runs; credential
    entry stays refused; a call the confinement files never reaches the inbox."""
    executor, tool, store = await _armed(tmp_path, page=_FakePage(list_elements=[{"role": "button", "text": "Pay now"}]))
    verdict = {"now": "admit"}

    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        return verdict["now"]

    try:
        session_id = await _open_session(executor, tool, _TIER_3_URL)
        executor.confine_calls(ToolCallConfinement(AGENT_WORK_READ_TOOL_IDS, gate))
        await _invoke(executor, {"action": "click", "index": 0, "session_id": session_id})
        assert len(tool.invocations) == 1 and await store.list_pending() == []
        credential = await _invoke(executor, {"action": "fill_credential", "session_id": session_id})
        assert agentic_dispatch._APPROVAL_CREDENTIAL_REFUSAL in (credential.error or "") and len(tool.invocations) == 1
        verdict["now"] = "filed"
        filed = await _invoke(executor, {"action": "click", "index": 0, "session_id": session_id})
        assert CONFINED_CALL_FILED in (filed.error or "") and len(tool.invocations) == 1
        assert await store.list_pending() == []
    finally:
        await store.stop()
        await tool.stop()


# X16
async def test_an_item_the_executor_parked_itself_stays_parked_with_its_booking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F3's remaining parking outcome): a run AD-1324 parked on its own tier-floor ask (``parked_request_id``) is
    neither done nor released; its claimant keeps the booking until the ask is decided."""
    holder: dict[str, Any] = {}

    async def _tier_floor_parks(kwargs: dict[str, Any], outcome: Any) -> Any:
        rig = holder["rig"]
        item_id = kwargs["work_item_id_provider"]()
        ask = await rig.requests.file_request(agent_id=kwargs["agent_id"], kind="continue", target="continue", work_item_id=item_id)
        # as file_tier_floor_request(park=True) does from inside the executor
        assert await rig.driver.block_on_request(work_item_id=item_id, request_id=ask.id, reason="tier floor")
        holder["ask"] = ask.id
        outcome.stopped_reason, outcome.parked_request_id = "tier_floor_unavailable", ask.id
        return outcome

    _watch_runs(monkeypatch, then=_tier_floor_parks)
    async with _rig(tmp_path, [_final()]) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("blocked", "forge-1")
        assert item.metadata["capability_request_id"] == holder["ask"]
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["active"]
        assert _system_posts(rig, origin.id) == []


# X17
@pytest.mark.parametrize("stop", ["error", "empty"])
async def test_a_run_that_stops_without_a_finished_answer_fails_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str,
) -> None:
    """A1 (F4): only a run that completed with an answer is done; an error (as the step limit or the token budget) and
    an empty answer fail, and the report names the stop instead of saying "is done"."""
    async def _provider_down(request: LLMRequest) -> LLMResponse:
        raise RuntimeError("provider down")

    runs = _watch_runs(monkeypatch)
    async with _rig(tmp_path, [_provider_down] if stop == "error" else [_final("")]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        expected = "error" if stop == "error" else "complete"
        assert [run["outcome"].stopped_reason for run in runs] == [expected]  # the premise: the executor's own stop
        ended = await rig.store.get_work_item(created.work_item.id)
        assert ended is not None and ended.status == "failed"
        assert ended.metadata["agent_work_result"]["stopped"] == expected
        [report] = _system_posts(rig, origin.id)
        assert "is done" not in report and "ended as failed: the run " in report


# X18
async def test_a_claimant_stopped_after_it_filed_a_call_returns_the_request_to_the_board(tmp_path: Path) -> None:
    """A1 (F5): the stop lands after the call was filed and before the run returns; the request goes back to the board
    unclaimed with its booking cancelled, never parked; the filed call stays on the Captain's queue, inert."""
    holder: dict[str, Any] = {}

    async def _stop_then_answer(request: LLMRequest) -> LLMResponse:
        await holder["rig"].stops.issue_stop("forge-1", reason=STOP_REASON)
        return _final("Waiting for the Captain.")

    async with _rig(tmp_path, [_call("hull_survey", {}), _stop_then_answer]) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert "capability_request_id" not in item.metadata and rig.survey.calls == 0
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["cancelled"]
        [filed] = await rig.requests.list_pending()
        assert (filed.work_item_id, filed.payload["tool_id"]) == (item_id, "hull_survey")


# X19
async def test_a_decline_whose_notice_cannot_be_posted_does_not_say_it_was_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F9's literal): the decliner is told the truth when neither the thread nor the channel took the post."""
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)

        async def _down(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("the Ward Room is down")

        monkeypatch.setattr(rig.wr, "create_post", _down)
        monkeypatch.setattr(rig.wr, "create_thread", _down)
        outcome, said = await rig.runner.decline("forge-1", item_id, "On the warp core.")
        assert outcome == "declined" and "could not be posted" in said and "told" not in said


# X20
async def test_the_activation_notice_states_the_configured_ttl(tmp_path: Path) -> None:
    """A1 (F13): the notice names the TTL the store applies, never rounded up to an hour."""
    from probos.agent_work_runner import ttl_words

    assert [ttl_words(seconds) for seconds in (60, 90, 5_400, 86_400)] == ["1 min", "90 s", "90 min", "24 h"]
    async with _rig(tmp_path, [], section=AgentWorkConfig(enabled=True, ttl_seconds=60)) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert "it expires 1 min after it was asked" in notice.body


# X21
def test_a_confirmation_token_is_never_recorded_in_an_approval() -> None:
    """A1 (F15): AD-1154 strips a browser confirmation token before filing (BF-682); the agent-work gate does the same,
    and the approved call's identity does not depend on the token."""
    from probos.agent_work_runner import APPROVAL_UNRECORDED_PARAMS, approval_payload

    assert APPROVAL_UNRECORDED_PARAMS == agentic_dispatch._APPROVAL_PARAM_STRIP_KEYS
    with_token = approval_payload("browser", {"action": "click", "index": 0, "confirmation_token": "tok-1"}, "wi-1")
    assert with_token is not None and "confirmation_token" not in with_token["params"]
    assert with_token == approval_payload("browser", {"action": "click", "index": 0}, "wi-1")


_ROWS = _REPO / "ui" / "e2e" / "fixtures" / "ad1347-action-payload-rows.json"
#: A2 (F19), A2d, A2f (F26): the rows end on 11 of the 13 exits of ``validate_action_payload`` and reach each
#: refusal of the item binding. The other two exits have no row. A params key that is not a string
#: (``capability_request.py:220-221``) is unreachable from JSON, whose object keys are strings. A payload
#: ``_canonical_json`` refuses (``:233-234``) is reachable from JSON text, since ``1e400`` decodes to an infinite
#: float, but Python owns canonical admission and the HXI's size check is a lower bound that does not refuse an
#: infinite number (register R12), so the rows claim no agreement there. The store never writes such a payload.
_REFUSALS = frozenset({
    "missing_key", "extra_key", "tool_id_number", "tool_id_grammar", "action_number", "action_grammar", "tool_id_65",
    "params_array", "params_text", "params_21_keys", "scope_254", "thread_65", "thread_null", "session_65",
    "session_number", "lone_surrogate", "size_4047", "other_item", "unlinked", "empty_item",
})


def _row_request(row: dict[str, Any]) -> CapabilityRequest:
    """The approved request a shared row describes, its ``fill`` applied as the HXI test applies it."""
    payload = copy.deepcopy(row["payload"])
    work_item_id = row["work_item_id"]
    fill = row.get("fill")
    if fill is not None:
        text = "x" * fill["chars"]
        if fill["field"] == "work_item_id":
            work_item_id, payload["scope_key"] = text, "agent_work:" + text
        elif fill["field"] == "note":
            payload["params"]["note"] = text
        else:
            payload[fill["field"]] = text
    return CapabilityRequest(
        id="00000000-0000-0000-0000-000000000009", agent_id="forge-1", kind=row["kind"], target="hull_survey",
        work_item_id=work_item_id, status="approved", created_at=1000.0, payload=payload,
    )


# X22
def test_both_fulfilment_predicates_read_every_shared_payload_row_alike() -> None:
    """A2 (F19): the Python oracle of ``ui/e2e/fixtures/ad1347-action-payload-rows.json``. Each row's answers are
    Python's, through the real ``can_fulfil_request`` and ``agent_work_call``, and
    ``ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts`` requires the HXI's ``canFulfil`` and decoder to give
    the same ones. A2d, A2f (F26): the rows end on 11 of the 13 exits of ``validate_action_payload`` and reach
    each refusal of the item binding; ``_REFUSALS``'s comment names the other two and why neither has a row. The test
    reads the answers, not which refusal gave them: the two action rows are also refused by
    ``agent_work_call``'s action check."""
    rows = json.loads(_ROWS.read_text(encoding="utf-8"))["rows"]
    names = [row["name"] for row in rows]
    assert len(set(names)) == len(names) and _REFUSALS <= set(names)
    for row in rows:
        request = _row_request(row)
        assert (row["name"], can_fulfil_request(request)) == (row["name"], row["fulfillable"])
        assert (row["name"], agent_work_call(request) is not None) == (row["name"], row["agent_work_call"])
    assert [row["name"] for row in rows if row["name"] in _REFUSALS and row["fulfillable"]] == []


# X23
async def test_a_fulfilment_store_fault_on_an_agent_work_approval_returns_the_approval_as_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (F20): the approval route degrades honestly: the decision is recorded and the response says it is approved,
    not fulfilled, and retryable (HTTP 200, not 500); the retry then fulfils it."""
    from probos.agent_work_runner import approval_payload

    requests = CapabilityRequestStore(db_path=str(tmp_path / "requests.db"))
    await requests.start()
    try:
        captain = SimpleNamespace(capability_request_store=requests)
        filed = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 2}, "wi-agent-work-1"), rationale="r",
            work_item_id="wi-agent-work-1",
        )
        real_mark = requests.mark_fulfilled

        async def _readonly(request_id: str) -> Any:
            raise OSError("attempt to write a readonly database")

        monkeypatch.setattr(requests, "mark_fulfilled", _readonly)
        decided = await decide_capability_request(filed.id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert decided["fulfilled"] is False
        assert (decided["request"]["status"], decided["request"]["can_retry_fulfilment"]) == ("approved", True)
        monkeypatch.setattr(requests, "mark_fulfilled", real_mark)
        retried = await decide_capability_request(filed.id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert (retried["fulfilled"], retried["request"]["status"]) == (True, "fulfilled")
    finally:
        await requests.stop()


# X24
async def test_an_agent_work_approval_issues_no_standing_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A2: the confinement admits one exact call per approval and never reads a standing rule, so the route issues
    none for an agent-work approval, with standing rules on and the item's value confirmed, as for repair and AD-1328
    command approvals; the HXI does not offer one (``CapabilityRequestCard.ad1347.test.tsx``)."""
    from probos.agent_work_runner import approval_payload

    issued: list[Any] = []

    async def _confirmed(*args: Any) -> bool:
        return True

    async def _issue(*args: Any, **kwargs: Any) -> Any:
        issued.append(args)
        raise OSError("a standing rule was issued")

    monkeypatch.setattr(route_module, "_work_item_value_confirmed", _confirmed)
    requests = CapabilityRequestStore(db_path=str(tmp_path / "requests.db"))
    await requests.start()
    try:
        inbox = SimpleNamespace(standing_rules_enabled=True, standing_rule_max_ttl_hours=12, standing_rule_default_ttl_hours=4)
        runtime = SimpleNamespace(
            capability_request_store=requests, action_approval_store=SimpleNamespace(issue_approval=_issue),
            config=SimpleNamespace(approval_inbox=inbox),
        )
        filed = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 2}, "wi-agent-work-1"), rationale="r",
            work_item_id="wi-agent-work-1",
        )
        body = CapabilityRequestDecideRequest(approve=True, grant_standing=True, standing_ttl_hours=2)
        decided = await decide_capability_request(filed.id, body, runtime=runtime)
        assert (decided["standing_rule"], decided["fulfilled"], issued) == (None, True, [])
    finally:
        await requests.stop()
