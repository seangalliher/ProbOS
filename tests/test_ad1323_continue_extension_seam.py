"""AD-1323 (#1478): the whole chain, with nothing between the model and the Captain stubbed.

A real DM turn runs the real ``AgenticLoop`` through the real ``WorkItemAgenticExecutor``
against a scripted model client, spends its token budget, is promoted on demand, files the
costed ask, is approved through the real router entry, is fulfilled by the real fulfiller,
resumed by the real ``CapabilityGapDriver`` and runs ONE extended pass. Only the LLM client
(the real ``complete()`` signature, returning ``LLMResponse``) is scripted; the clock is the
real one. Stores are the real SQLite implementations on ``tmp_path``.

Measured placement notes recorded for the reviewer:

* ``start_resumed_run`` creates the work task immediately and only its reporter waits for the
  BF-732 slot, so ``begin_pass`` runs at task start, not behind the slot (the amendment
  assumed the work sat behind it). The recoverable window is consume -> task start.
* A promoted turn carries no work item until promotion, so the first pass cannot read value
  from one: the ask is armed here with ``ask_when_value_unrecorded``.
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.promoted_turn_recovery import recover_continue_permits
from probos.cognitive.swe_harness.tool_call import ToolCallRequest
from probos.config import DmAgenticConfig
from probos.continue_extension_permits import SqliteContinueExtensionPermitStore
from probos.routers.capability_requests import decide_capability_request
from probos.startup.finalize import (
    _wire_capability_gap_driver,
    _wire_continue_extension_reconciler,
)
from probos.substrate.registry import AgentRegistry
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
from probos.workforce import WorkItemStore
from tests.test_ad1204_approval_resumes_the_turn import _EventBus, _RecordingRouter

AGENT = "ezri_seam"
BUDGET = 1024
EXTENSION = 600
USER_MESSAGE = "Fetch the ledger pages one at a time and reconcile them."


def _tool_use(index: int) -> Any:
    from probos.cognitive.swe_harness.agentic_loop import TextBlock, ToolUseBlock

    return [
        TextBlock(text=f"Fetching page {index}."),
        ToolUseBlock(
            tool_call=ToolCallRequest(
                id=f"c{index}", name="http_fetch", arguments={"url": f"https://example.test/{index}"},
            )
        ),
    ]


class ScriptedLLM:
    """The real client's ``complete(request, **kwargs) -> LLMResponse``, scripted per call."""

    def __init__(self, plan: list[Any]) -> None:
        self.plan = list(plan)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        step = self.plan.pop(0) if self.plan else {"text": "done", "tokens": 10}
        if isinstance(step, BaseException):
            raise step
        if "tools" in step:
            return LLMResponse(
                content=f"step {step['tools']}", tokens_used=step["tokens"],
                content_blocks=_tool_use(step["tools"]), stop_reason="tool_use",
            )
        return LLMResponse(
            content=step["text"], tokens_used=step["tokens"],
            content_blocks=[__import__("probos.cognitive.swe_harness.agentic_loop", fromlist=["x"]).TextBlock(text=step["text"])],
        )


class _Fetch:
    tool_id = "http_fetch"
    name = "http_fetch"
    tool_type = ToolType.UTILITY_AGENT
    description = "Perform an HTTP request against a URL and return the response."
    input_schema = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
    output_schema = {"type": "object"}

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        return ToolResult(output="<html>" + "x" * 200)


class _Bus(_EventBus):
    """The runtime's event dispatch with ``add_event_listener(fn, event_types=...)``."""

    def emit_event(self, event_type: Any, data: dict[str, Any]) -> None:
        self.seen.append((str(getattr(event_type, "value", event_type)), dict(data or {})))
        super().emit_event(event_type, data)

    @property
    def seen(self) -> list[tuple[str, dict[str, Any]]]:
        return self.__dict__.setdefault("_seen", [])

    def add_event_listener(self, fn: Any, event_types: Any = None) -> None:
        wanted = set(event_types or [])

        async def _filtered(event: dict[str, Any]) -> None:
            if not wanted or event["type"] in wanted:
                await fn(event)

        super().add_event_listener(_filtered)


class Ship(SimpleNamespace):
    """One booted vessel over the files in ``root``; ``board`` again for a restart."""


def _config(**extra: Any) -> DmAgenticConfig:
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, token_budget=BUDGET, max_iterations=20,
        promote_to_task_after_seconds=60.0,
        economic_judgment={
            "enabled": True,
            "continue_extension": {
                "enabled": True, "max_extension_tokens": EXTENSION,
                "ask_when_value_unrecorded": True, **extra,
            },
        },
    )


async def board(root: Path, llm: ScriptedLLM, *, config: DmAgenticConfig | None = None) -> Ship:
    from probos.config import SystemConfig

    bus = _Bus()
    items = WorkItemStore(db_path=str(root / "wis.db"), tick_interval=1000)
    await items.start()
    requests = CapabilityRequestStore(db_path=str(root / "cap.db"), emit_event=bus.emit_event)
    await requests.start()
    permits = SqliteContinueExtensionPermitStore(str(root / "permits.db"))
    await permits.start()
    tools = ToolRegistry()
    tools.register(_Fetch(), provider="seam", default_permissions={r: "read" for r in ("ensign", "lieutenant", "commander", "senior")})
    system = SystemConfig(dm_agentic=config or _config())
    runtime = SimpleNamespace(
        config=system,
        work_item_router=_RecordingRouter(),
        work_item_store=items,
        capability_request_store=requests,
        continue_extension_permit_store=permits,
        add_event_listener=bus.add_event_listener,
        tool_registry=tools,
        tool_permission_store=ToolPermissionStore(),
        ontology=SimpleNamespace(get_agent_department=lambda _t: "science"),
        trust_network=SimpleNamespace(get_score=lambda _i: 0.8, get_record=lambda _i: None),
        intent_bus=None, attachment_store=None, emit_event=None, action_approval_store=None,
        fault_report_store=None, chat_thread_store=None, event_log=None, episodic_memory=None,
    )
    agent = CognitiveAgent(agent_id=AGENT, instructions="You are Ezri.")
    agent._runtime = runtime
    agent._llm_client = llm
    agent.callsign = "Ezri"
    agent.agent_type = "seam_agent"
    registry = AgentRegistry()
    await registry.register(agent)
    runtime.registry = registry
    assert _wire_capability_gap_driver(runtime=runtime, config=system) is True
    assert _wire_continue_extension_reconciler(runtime=runtime) is True
    return Ship(runtime=runtime, bus=bus, items=items, requests=requests, permits=permits,
                agent=agent, llm=llm)


async def settle(ship: Ship) -> None:
    while True:
        await ship.bus.drain()
        held = set(ship.agent._promoted_turn_tasks)
        if not held:
            return
        await asyncio.gather(*held, return_exceptions=True)
        await asyncio.sleep(0)


async def shutdown(ship: Ship) -> None:
    await settle(ship)
    await ship.requests.stop()
    await ship.items.stop()
    await ship.permits.stop()


async def dm_turn(ship: Ship) -> str | None:
    return await ship.agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}, "thread_id": "thread-seam"},
        system_prompt="You are Ezri.",
        user_message=USER_MESSAGE,
    )


async def approve(ship: Ship, request_id: str, *, approve_it: bool = True) -> Any:
    out = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=approve_it), runtime=ship.runtime,
    )
    await settle(ship)
    return out


def spending_plan() -> list[Any]:
    # Two tool steps that cost 600 tokens each exhaust the 1024-token budget mid-turn.
    return [{"tools": 1, "tokens": 600}, {"tools": 2, "tokens": 600}]


def _request_count(root: Path) -> int:
    with closing(sqlite3.connect(str(root / "cap.db"))) as db:
        return db.execute("SELECT COUNT(*) FROM capability_requests").fetchone()[0]


async def filed(ship: Ship) -> tuple[Any, Any, Any]:
    """Run the turn to its ask; return (request, work item, permit)."""
    await dm_turn(ship)
    await settle(ship)
    pending = await ship.requests.list_pending()
    assert [r.kind for r in pending] == ["continue"]
    request = pending[0]
    permit = await ship.permits.get_for_request(request.id, request.work_item_id)
    item = await ship.items.get_work_item(request.work_item_id)
    return request, item, permit


@pytest.mark.asyncio
async def test_seam_promote_file_approve_fulfil_resume_runs_one_extended_pass(tmp_path: Path) -> None:
    llm = ScriptedLLM(spending_plan() + [{"text": "Reconciled all pages.", "tokens": 100}])
    ship = await board(tmp_path, llm)
    try:
        request, item, permit = await filed(ship)
        assert item.status == "blocked"
        assert permit.bound == 1 and permit.state == "requested"
        calls_at_ask = len(llm.requests)
        assert calls_at_ask == 2

        out = await approve(ship, request.id)
        assert out.get("fulfilled") is True, out
        with pytest.raises(HTTPException):
            await approve(ship, request.id)
        fulfilled = [e for e in ship.bus.seen if e[0].endswith("fulfilled")]
        assert fulfilled, ship.bus.seen
        ship.bus.emit_event(*fulfilled[-1])
        await settle(ship)

        assert len(llm.requests) == calls_at_ask + 1
        permit = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert permit.state == "consumed" and permit.started_at is not None
        assert (await ship.requests.get(request.id)).status == "fulfilled"
        item = await ship.items.get_work_item(request.work_item_id)
        assert item.status in ("done", "completed", "closed"), item.status
        assert _request_count(tmp_path) == 1
        assert ship.runtime.config.dm_agentic.token_budget == BUDGET
    finally:
        await shutdown(ship)

async def _reboot(root: Path, old: Ship, llm: ScriptedLLM) -> Ship:
    """A restart: every store closed, a new runtime/registry/driver/agent over the same files."""
    await shutdown(old)
    return await board(root, llm)


@pytest.mark.asyncio
async def test_seam_restart_after_approval_recovers_via_sweep_and_real_executor(tmp_path: Path) -> None:
    ship = await board(tmp_path, ScriptedLLM(spending_plan()))
    llm2 = ScriptedLLM([{"text": "Recovered and reconciled.", "tokens": 100}])
    try:
        request, item, _ = await filed(ship)
        ship.bus._listeners.clear()  # the process dies before the driver can resume the turn
        out = await approve(ship, request.id)
        assert out.get("fulfilled") is True
        assert (await ship.permits.get_for_request(request.id, request.work_item_id)).state == "active"
        assert not ship.llm.plan and len(ship.llm.requests) == 2

        ship = await _reboot(tmp_path, ship, llm2)
        report = await recover_continue_permits(ship.runtime)
        await settle(ship)

        assert report.reconciled == 0
        assert len(llm2.requests) == 1
        permit = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert permit.state == "consumed" and permit.started_at is not None
        item = await ship.items.get_work_item(request.work_item_id)
        assert item.status in ("done", "completed", "closed"), item.status
        assert _request_count(tmp_path) == 1

        again = await recover_continue_permits(ship.runtime)
        await settle(ship)
        assert len(llm2.requests) == 1
        assert (again.unbound_voided, again.reclaimed, again.reconciled) == (0, 0, 0)
    finally:
        await shutdown(ship)


class _InWindow:
    """Delegates to the real request store; decides inside ``file_request``'s window."""

    def __init__(self, real: Any, ship_ref: dict[str, Any], approve_it: bool) -> None:
        self._real = real
        self._ref = ship_ref
        self._approve = approve_it
        self.outcome: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    async def file_request(self, *args: Any, **kwargs: Any) -> Any:
        request = await self._real.file_request(*args, **kwargs)
        ship = self._ref["ship"]
        self.outcome = await decide_capability_request(
            request.id, CapabilityRequestDecideRequest(approve=self._approve, reason="not now"), runtime=ship.runtime,
        )
        self.seen_before_return = list(ship.bus.seen)
        permit = await ship.permits.get_for_request(request.id, request.work_item_id)
        self.unbound_state = (permit.bound, permit.state) if permit else None
        return request


async def _in_window(tmp_path: Path, *, approve_it: bool) -> tuple[Ship, _InWindow, Any]:
    llm = ScriptedLLM(spending_plan() + [{"text": "Reconciled all pages.", "tokens": 100}])
    ship = await board(tmp_path, llm)
    proxy = _InWindow(ship.requests, {"ship": ship}, approve_it)
    ship.runtime.capability_request_store = proxy
    await dm_turn(ship)
    await settle(ship)
    return ship, proxy, None


@pytest.mark.asyncio
async def test_seam_approval_in_unbound_window_is_reconciled(tmp_path: Path) -> None:
    ship, proxy, _ = await _in_window(tmp_path, approve_it=True)
    try:
        assert proxy.outcome.get("fulfilled") is False, proxy.outcome
        assert proxy.unbound_state == (False, "requested")
        assert not [e for e in proxy.seen_before_return if e[0].endswith("fulfilled")]
        with closing(sqlite3.connect(str(tmp_path / "cap.db"))) as db:
            rid, status = db.execute("SELECT id, status FROM capability_requests").fetchone()
        assert status == "fulfilled"
        permit = (await ship.permits.list_requested())  # no longer requested: reconciled to active/consumed
        assert permit == []
        row = await ship.permits.get_for_request(rid, (await ship.requests.get(rid)).work_item_id)
        assert row.bound is True and row.state == "consumed" and row.started_at is not None
        assert len(ship.llm.requests) == 3
        assert len([e for e in ship.bus.seen if e[0].endswith("fulfilled")]) == 1
        item = await ship.items.get_work_item(row.work_item_id)
        assert item.status in ("done", "completed", "closed"), item.status
        assert _request_count(tmp_path) == 1
    finally:
        await shutdown(ship)


@pytest.mark.asyncio
async def test_seam_denial_in_unbound_window_voids_and_cancels(tmp_path: Path) -> None:
    ship, proxy, _ = await _in_window(tmp_path, approve_it=False)
    try:
        with closing(sqlite3.connect(str(tmp_path / "cap.db"))) as db:
            rid, status = db.execute("SELECT id, status FROM capability_requests").fetchone()
        assert status == "denied"
        request = await ship.requests.get(rid)
        row = await ship.permits.get_for_request(rid, request.work_item_id)
        assert row.state == "voided"
        item = await ship.items.get_work_item(row.work_item_id)
        assert item.status in ("cancelled", "canceled"), item.status
        assert len(ship.llm.requests) == 2
    finally:
        await shutdown(ship)

def _crash_before_begin_pass(ship: Ship) -> None:
    async def _dies(_request_id: str) -> bool:
        raise asyncio.CancelledError()

    ship.permits.begin_pass = _dies  # the process stops between consume and the first-pass mark


@pytest.mark.asyncio
async def test_seam_crash_before_first_model_call_is_reclaimed_once_and_after_is_not(tmp_path: Path) -> None:
    # (i) a crash before begin_pass leaves a consumed, unstarted permit: one reclaim, one pass.
    ship = await board(tmp_path, ScriptedLLM(spending_plan()))
    request, _, _ = await filed(ship)
    _crash_before_begin_pass(ship)
    await approve(ship, request.id)
    row = await ship.permits.get_for_request(request.id, request.work_item_id)
    assert row.state == "consumed" and row.started_at is None and len(ship.llm.requests) == 2

    llm2 = ScriptedLLM([{"text": "Recovered.", "tokens": 100}])
    ship = await _reboot(tmp_path, ship, llm2)
    _crash_before_begin_pass(ship)  # (iii) and it stops again before the mark
    first = await recover_continue_permits(ship.runtime)
    await settle(ship)
    assert first.reclaimed == 1 and len(llm2.requests) == 0
    assert (await ship.permits.get_for_request(request.id, request.work_item_id)).reclaims == 1

    llm3 = ScriptedLLM([{"text": "Must not run.", "tokens": 100}])
    ship = await _reboot(tmp_path, ship, llm3)
    try:
        second = await recover_continue_permits(ship.runtime)
        await settle(ship)
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert second.reclaimed == 0 and len(llm3.requests) == 0
        assert row.reclaims == 1 and row.state != "active"
    finally:
        await shutdown(ship)


@pytest.mark.asyncio
async def test_seam_crash_before_begin_pass_single_reclaim_runs_one_pass(tmp_path: Path) -> None:
    ship = await board(tmp_path, ScriptedLLM(spending_plan()))
    request, _, _ = await filed(ship)
    _crash_before_begin_pass(ship)
    await approve(ship, request.id)
    llm2 = ScriptedLLM([{"text": "Recovered.", "tokens": 100}])
    ship = await _reboot(tmp_path, ship, llm2)
    try:
        report = await recover_continue_permits(ship.runtime)
        await settle(ship)
        assert report.reclaimed == 1 and len(llm2.requests) == 1
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.state == "consumed" and row.started_at is not None
        item = await ship.items.get_work_item(request.work_item_id)
        assert item.status in ("done", "completed", "closed"), item.status
    finally:
        await shutdown(ship)


@pytest.mark.asyncio
async def test_seam_crash_after_first_model_call_is_not_reclaimed(tmp_path: Path) -> None:
    ship = await board(tmp_path, ScriptedLLM(spending_plan() + [asyncio.CancelledError()]))
    request, _, _ = await filed(ship)
    await approve(ship, request.id)
    row = await ship.permits.get_for_request(request.id, request.work_item_id)
    assert row.state == "consumed" and row.started_at is not None

    llm2 = ScriptedLLM([{"text": "Must not run.", "tokens": 100}])
    ship = await _reboot(tmp_path, ship, llm2)
    try:
        report = await recover_continue_permits(ship.runtime)
        await settle(ship)
        assert report.reclaimed == 0 and len(llm2.requests) == 0
        assert (await ship.permits.get_for_request(request.id, request.work_item_id)).state == "consumed"
        assert _request_count(tmp_path) == 1
    finally:
        await shutdown(ship)

# ---- AD-1323 amendment 3: extension-necessary seam, queued admission, claim loss


def _cm(*, slots: int = 1, queue: int = 10) -> Any:
    from probos.cognitive.concurrency_manager import ConcurrencyManager

    return ConcurrencyManager("seam", max_concurrent=slots, queue_max_size=queue)


async def _quiet_approval(ship: Ship, request_id: str) -> Any:
    """Approve through the real router entry without waiting for the resumed run to finish."""
    out = await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True), runtime=ship.runtime,
    )
    await ship.bus.drain()
    await asyncio.sleep(0.5)  # sqlite hops run on threads: let a mis-ordered pass show itself
    return out


@pytest.mark.asyncio
async def test_seam_extension_applies_to_the_live_budget_and_the_pass_finishes_beyond_standing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.turn_cost import TurnCostBudget

    # After pass one 1200 tokens are spent against 1024. The resumed pass can only take its
    # second and third model calls if the live ceiling really rose to 1024 + 600.
    plan = spending_plan() + [
        {"tools": 3, "tokens": 150}, {"tools": 4, "tokens": 150}, {"text": "Reconciled all pages.", "tokens": 50},
    ]
    llm = ScriptedLLM(plan)
    ship = await board(tmp_path, llm)
    seen: list[tuple[Any, int]] = []
    original = TurnCostBudget.extend

    def _spy(self: Any, tokens: int) -> int:  # delegating: behaviour is the real extend
        granted = original(self, tokens)
        seen.append((self, granted))
        return granted

    monkeypatch.setattr(TurnCostBudget, "extend", _spy)
    try:
        request, _, _ = await filed(ship)
        before = len(llm.requests)
        await approve(ship, request.id)
        assert [g for _, g in seen] == [EXTENSION]
        live = seen[0][0]
        assert live.extended is True
        assert live.configured_budget == BUDGET and live.budget == BUDGET + EXTENSION
        assert len(llm.requests) == before + 3  # impossible on the standing remainder of one
        item = await ship.items.get_work_item(request.work_item_id)
        assert item.status in ("done", "completed", "closed"), item.status
        assert ship.runtime.config.dm_agentic.token_budget == BUDGET
    finally:
        await shutdown(ship)


@pytest.mark.asyncio
async def test_seam_queued_pass_cancelled_leaves_a_reclaimable_unstarted_permit(tmp_path: Path) -> None:
    llm = ScriptedLLM(spending_plan())
    ship = await board(tmp_path, llm)
    ship.agent._concurrency_manager = manager = _cm(slots=1)
    holder_release = asyncio.Event()
    holder_in = asyncio.Event()

    async def _holder() -> None:
        async with manager.slot("other", 1):
            holder_in.set()
            await holder_release.wait()

    holder = asyncio.create_task(_holder())
    await holder_in.wait()
    try:
        request, _, _ = await filed(ship)
        calls = len(llm.requests)
        await _quiet_approval(ship, request.id)
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.state == "consumed" and row.started_at is None  # queued: nothing was started
        assert len(llm.requests) == calls and manager.queue_depth == 1
        for task in list(ship.agent._promoted_turn_tasks):
            task.cancel()
        await asyncio.gather(*list(ship.agent._promoted_turn_tasks), return_exceptions=True)
        for _ in range(20):
            await asyncio.sleep(0)
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.state == "consumed" and row.started_at is None and len(llm.requests) == calls
    finally:
        holder_release.set()
        await holder

    llm2 = ScriptedLLM([{"text": "Recovered.", "tokens": 100}])
    ship = await _reboot(tmp_path, ship, llm2)
    try:
        report = await recover_continue_permits(ship.runtime)
        await settle(ship)
        assert report.reclaimed == 1 and len(llm2.requests) == 1
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.state == "consumed" and row.started_at is not None and row.reclaims == 1
        again = await recover_continue_permits(ship.runtime)
        await settle(ship)
        assert again.reclaimed == 0 and len(llm2.requests) == 1
    finally:
        await shutdown(ship)


@pytest.mark.asyncio
async def test_seam_pass_begins_only_once_its_slot_is_held_and_takes_exactly_one_slot(tmp_path: Path) -> None:
    llm = ScriptedLLM(spending_plan() + [{"text": "Reconciled all pages.", "tokens": 100}])
    ship = await board(tmp_path, llm)
    ship.agent._concurrency_manager = manager = _cm(slots=1)
    acquired: list[str] = []
    real_slot = manager.slot

    def _counting(intent: str, priority: int) -> Any:  # delegating spy
        acquired.append(intent)
        return real_slot(intent, priority)

    manager.slot = _counting
    release = asyncio.Event()
    holder_in = asyncio.Event()

    async def _holder() -> None:
        async with real_slot("other", 1):
            holder_in.set()
            await release.wait()

    holder = asyncio.create_task(_holder())
    await holder_in.wait()
    try:
        request, _, _ = await filed(ship)
        calls = len(llm.requests)
        acquired.clear()
        await _quiet_approval(ship, request.id)
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.started_at is None and len(llm.requests) == calls
        release.set()
        await holder
        await settle(ship)
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.state == "consumed" and row.started_at is not None
        assert len(llm.requests) == calls + 1
        assert acquired.count("direct_message_promoted") == 1
    finally:
        release.set()
        await shutdown(ship)


@pytest.mark.asyncio
async def test_seam_queue_full_denies_admission_leaves_permit_unstarted_and_fails_the_item_visibly(
    tmp_path: Path,
) -> None:
    llm = ScriptedLLM(spending_plan() + [{"text": "Must not run.", "tokens": 100}])
    ship = await board(tmp_path, llm)
    ship.agent._concurrency_manager = _cm(slots=1, queue=1)
    release = asyncio.Event()
    holder_in = asyncio.Event()
    manager = ship.agent._concurrency_manager

    async def _holder() -> None:
        async with manager.slot("other", 1):
            holder_in.set()
            await release.wait()

    async def _queued() -> None:
        async with manager.slot("other2", 1):
            pass

    holder = asyncio.create_task(_holder())
    await holder_in.wait()
    waiter = asyncio.create_task(_queued())
    for _ in range(5):
        await asyncio.sleep(0)
    try:
        request, _, _ = await filed(ship)
        calls = len(llm.requests)
        await approve(ship, request.id)
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.state == "consumed" and row.started_at is None
        assert len(llm.requests) == calls
        item = await ship.items.get_work_item(request.work_item_id)
        assert item.status in ("failed", "blocked", "cancelled"), item.status
        assert item.status != "in_progress"
    finally:
        release.set()
        await holder
        await waiter
        await shutdown(ship)


@pytest.mark.asyncio
async def test_resumed_segment_claim_lost_runs_no_model_and_posts_no_report(tmp_path: Path) -> None:
    llm = ScriptedLLM(spending_plan() + [{"text": "Must not run.", "tokens": 100}])
    ship = await board(tmp_path, llm)
    try:
        request, _, permit = await filed(ship)
        calls = len(llm.requests)
        ship.bus._listeners.clear()  # nothing resumes the turn on approval
        await approve(ship, request.id)
        # another process already holds the claim
        other = SqliteContinueExtensionPermitStore(str(tmp_path / "permits.db"))
        await other.start()
        try:
            won = await other.consume(
                request.id, agent_id=AGENT, work_item_id=request.work_item_id, thread_id=permit.thread_id,
            )
            assert won is not None
        finally:
            await other.stop()
        fulfilled = [e for e in ship.bus.seen if e[0].endswith("fulfilled")]
        ship.bus._listeners.clear()
        await ship.runtime.capability_gap_driver.on_capability_event(
            {"type": "capability_request_fulfilled", "data": {"id": request.id}},
        )
        await settle(ship)
        assert fulfilled
        assert len(llm.requests) == calls  # the claim was lost: no model call
        item = await ship.items.get_work_item(request.work_item_id)
        assert item.status == "in_progress"
        assert "stranded_reason" not in (item.metadata or {})
        row = await ship.permits.get_for_request(request.id, request.work_item_id)
        assert row.started_at is None
    finally:
        await shutdown(ship)
