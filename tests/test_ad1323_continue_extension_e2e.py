"""AD-1323 (#1478): the real chain, ask -> approve -> activate -> fulfil -> resume -> extended pass.

Real stores (work items, capability requests, permits), the real router entry, the real
``CapabilityGapDriver`` and the real ``CognitiveAgent.recover_promoted_turn``. Only the
model-calling executor and the reporter are replaced, and they record what they were given.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.continue_or_ask import file_continue_request
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.costed_continue_ask import file_costed_continue
from probos.cognitive.economic_judgment_organ import CostedCase
from probos.cognitive.promoted_turn_recovery import recover_continue_permits
from probos.cognitive.turn_promotion import (
    RESUME_ALREADY_ADMITTED,
    RESUME_NO_CONTINUATION,
    RESUME_STARTED,
    resume_promoted_turn,
)
from probos.config import DmAgenticConfig
from probos.continue_extension_permits import SqliteContinueExtensionPermitStore
from probos.routers.capability_requests import _fulfil_by_approval_itself, decide_capability_request
from probos.workforce import WorkItemStore
from tests.test_ad1204_approval_resumes_the_turn import _EventBus, _RecordingRouter
from tests.test_ad1211_approval_fulfils_every_kind import _AgentRegistry

AGENT = "ezri_0"
THREAD = "thread-1"
TASK = "Reconcile the ledger against the statement"
STOP = "I reconciled the first forty lines and found two mismatches."


def _config(**extra: Any) -> DmAgenticConfig:
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, token_budget=1024,
        economic_judgment={"enabled": True, "continue_extension": {"enabled": True, **extra}},
    )


def _case() -> CostedCase:
    return CostedCase(
        spent=950, budget=1024, value_band="critical", stakes="high", verified=True,
        signals=(), recent_step_deltas=(100, 100, 100),
    )


class Rig(SimpleNamespace):
    """One booted ship's worth of stores. ``open`` can be called again on the same paths."""

    runs: list[dict[str, Any]]
    starts: list[dict[str, Any]]


async def open_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, config: DmAgenticConfig | None = None,
                   permits: bool = True, ttl: int = 3600, real_start: bool = False) -> Rig:
    config = config or _config()
    bus = _EventBus()
    items = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await items.start()
    requests = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"), emit_event=bus.emit_event)
    await requests.start()
    store = None
    if permits:
        store = SqliteContinueExtensionPermitStore(str(tmp_path / "permits.db"), ttl_seconds=ttl)
        await store.start()
    runtime = SimpleNamespace(
        config=SimpleNamespace(dm_agentic=config),
        work_item_router=_RecordingRouter(),
        work_item_store=items,
        capability_request_store=requests,
        continue_extension_permit_store=store,
        chat_thread_store=None,
        event_log=None,
        episodic_memory=None,
    )
    agent = CognitiveAgent(agent_id=AGENT, instructions="You are Ezri.")
    agent._runtime = runtime
    agent._llm_client = object()
    agent.callsign = "Ezri"
    runtime.registry = _AgentRegistry(agent)
    driver = CapabilityGapDriver(runtime=runtime, work_item_store=items, capability_request_store=requests)
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    rig = Rig(runtime=runtime, bus=bus, items=items, requests=requests, permits=store, agent=agent,
              driver=driver, runs=[], starts=[])

    async def _run(self: Any, **kw: Any) -> Any:
        rig.runs.append(kw)
        return SimpleNamespace(final_text="done", stopped_reason="completed")

    def _start(work: Any, **kw: Any) -> Any:
        rig.starts.append(kw)
        # Amendment 3: this stand-in runs no reporter, so it plays the reporter's one job -- the
        # slot is held -- which is what releases a pass waiting for admission.
        if kw.get("admission") is not None:
            kw["admission"].settle("admitted")
        task = asyncio.create_task(work())
        kw["hold"].add(task)
        task.add_done_callback(kw["hold"].discard)
        return task

    monkeypatch.setattr("probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor.run", _run)
    if not real_start:
        monkeypatch.setattr("probos.cognitive.turn_promotion.start_resumed_run", _start)
    return rig


async def close_rig(rig: Rig) -> None:
    await rig.bus.drain()
    held = set(rig.agent._promoted_turn_tasks)
    if held:
        await asyncio.gather(*held, return_exceptions=True)
    await rig.requests.stop()
    await rig.items.stop()
    if rig.permits is not None:
        await rig.permits.stop()


async def promoted_item(rig: Rig) -> Any:
    item = await rig.items.create_work_item(
        title=TASK, description=TASK, work_type="task", assigned_to=AGENT, created_by="captain",
        tags=["conversational-turn"],
        metadata={"source": "dm_agentic_promotion", "thread_id": THREAD, "agent_id": AGENT},
    )
    await rig.items.transition_work_item(item.id, "in_progress", source=AGENT)
    return item


async def ask(rig: Rig, item: Any, *, stop_text: str = STOP, plan_mode: bool = False,
              config: DmAgenticConfig | None = None) -> str:
    async def _promote() -> str | None:
        return item.id

    request_id = await file_costed_continue(
        rig.runtime, agent_id=AGENT, thread_id=THREAD, base_task_text=TASK, display_task_text=TASK,
        case=_case(), config=config or _config(), promote=_promote, work_item_id=None, passes=1,
        stop_text=stop_text, plan_mode=plan_mode, configured_budget=1024, parked={},
    )
    assert request_id, "premise: the costed ask must have been filed"
    return request_id


async def approve(rig: Rig, request_id: str) -> None:
    await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
    )
    await rig.bus.drain()
    held = set(rig.agent._promoted_turn_tasks)
    if held:
        await asyncio.gather(*held, return_exceptions=True)


@pytest.fixture
async def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    built = await open_rig(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        await close_rig(built)


@pytest.mark.asyncio
async def test_valuable_token_stop_promotes_then_files_linked_request(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    req = await rig.requests.get(request_id)
    assert req is not None and req.kind == "continue" and req.work_item_id == item.id
    parked = await rig.items.get_work_item(item.id)
    assert parked is not None and parked.status == "blocked"
    assert parked.metadata.get("capability_request_id") == request_id
    permit = await rig.permits.get(request_id)
    assert permit is not None and permit.state == "requested"
    assert permit.cap_tokens == 1024 and permit.configured_budget == 1024


@pytest.mark.asyncio
async def test_filed_request_serialises_through_existing_surface(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    req = await rig.requests.get(request_id)
    assert req is not None
    assert "Token budget spent 950/1024" in req.rationale
    assert len(req.rationale) <= 280
    assert req.payload is not None and len(req.payload) == 6
    reloaded = await rig.requests.get(request_id)
    assert reloaded is not None and reloaded.payload == req.payload
    assert [r.id for r in await rig.requests.list_pending()] == [request_id]


@pytest.mark.asyncio
async def test_approval_resumes_with_budget_equal_to_extension_not_standing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await open_rig(tmp_path, monkeypatch, config=_config(max_extension_tokens=300))
    try:
        item = await promoted_item(rig)
        request_id = await ask(rig, item, config=_config(max_extension_tokens=300))
        await approve(rig, request_id)
        assert len(rig.runs) == 1
        assert rig.runs[0]["token_budget"] == 300  # the extension, not the standing 1024
        assert rig.runs[0]["task_text"].startswith(TASK) or STOP in rig.runs[0]["task_text"]
        assert rig.starts[0]["settle_expected"] == {"capability_request_id": request_id}
        permit = await rig.permits.get(request_id)
        assert permit is not None and permit.state == "consumed" and permit.decided_by == "captain"
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_recovery_pass_budget_equals_extension_not_standing(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    assert [r["token_budget"] for r in rig.runs] == [1024]
    assert rig.runs[0]["failure_scope"] == item.id


@pytest.mark.asyncio
async def test_replayed_fulfilled_event_no_second_extension(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    event = {"type": "capability_request_fulfilled", "data": {"id": request_id}}
    await rig.driver.on_capability_event(event)
    await rig.driver.on_capability_event(event)
    await rig.bus.drain()
    assert len(rig.runs) == 1


@pytest.mark.asyncio
async def test_duplicate_approval_single_permit_single_pass(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    with pytest.raises(Exception):
        await decide_capability_request(
            request_id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
        )
    await rig.bus.drain()
    assert len(rig.runs) == 1
    assert len(await rig.permits.list_active()) == 0


@pytest.mark.asyncio
async def test_no_approval_keeps_token_budget_binding(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    assert await rig.agent.recover_promoted_turn(item, request_id) == RESUME_NO_CONTINUATION
    assert rig.runs == []
    permit = await rig.permits.get(request_id)
    assert permit is not None and permit.state == "requested"


@pytest.mark.asyncio
async def test_denied_request_no_permit_no_resume(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=False, reason="not worth it"),
        runtime=rig.runtime,
    )
    await rig.bus.drain()
    assert rig.runs == []
    assert await rig.permits.list_active() == []
    assert await rig.agent.recover_promoted_turn(item, request_id) == RESUME_NO_CONTINUATION


@pytest.mark.asyncio
async def test_agent_cannot_activate_own_permit(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    self_decided = SimpleNamespace(id=request_id, decided_by=AGENT)
    fulfilled: list[str] = []

    class _Store:
        async def mark_fulfilled(self, rid: str) -> Any:
            fulfilled.append(rid)
            return object()

    assert await _fulfil_by_approval_itself(rig.runtime, _Store(), self_decided) is None
    assert fulfilled == []
    permit = await rig.permits.get(request_id)
    assert permit is not None and permit.state == "requested"


@pytest.mark.asyncio
async def test_delegated_own_requisition_refused(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    for decider in ("", "   ", AGENT):
        decided = SimpleNamespace(id=request_id, decided_by=decider)

        class _Store:
            async def mark_fulfilled(self, rid: str) -> Any:
                raise AssertionError("must not fulfil")

        assert await _fulfil_by_approval_itself(rig.runtime, _Store(), decided) is None


@pytest.mark.asyncio
async def test_unreserved_request_fulfils_exactly_as_before(rig: Rig) -> None:
    calls: list[str] = []

    class _Store:
        async def mark_fulfilled(self, rid: str) -> Any:
            calls.append(rid)
            return "ok"

    assert await _fulfil_by_approval_itself(
        rig.runtime, _Store(), SimpleNamespace(id="plain", decided_by="captain"),
    ) == "ok"
    no_permits = SimpleNamespace(continue_extension_permit_store=None)
    assert await _fulfil_by_approval_itself(
        no_permits, _Store(), SimpleNamespace(id="plain2", decided_by="captain"),
    ) == "ok"
    assert calls == ["plain", "plain2"]


@pytest.mark.asyncio
async def test_ordinary_ad1164_request_mints_no_permit(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await file_continue_request(
        rig.runtime, agent_id=AGENT, thread_id=THREAD, base_task_text=TASK, passes=1, work_item_id=item.id,
    )
    assert request_id
    assert await rig.permits.get(request_id) is None
    assert await rig.permits.has_work_item(item.id) is False
    await approve(rig, request_id)
    assert rig.runs == []  # no permit, no extended pass


@pytest.mark.asyncio
async def test_recovery_without_active_permit_never_extends(rig: Rig) -> None:
    item = await promoted_item(rig)
    assert await rig.agent.recover_promoted_turn(item, "no-such-request") == RESUME_NO_CONTINUATION
    assert rig.runs == [] and rig.starts == []


@pytest.mark.asyncio
async def test_consumed_permit_cannot_be_reused(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    # Amendment 3: a consumed permit is no longer "no continuation" (which closes the item);
    # it is already admitted by its winner, which owns the item.
    assert await rig.agent.recover_promoted_turn(item, request_id) == RESUME_ALREADY_ADMITTED
    assert len(rig.runs) == 1


@pytest.mark.asyncio
async def test_concurrent_recovery_attempts_start_one_pass(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    outcomes = await asyncio.gather(*[rig.agent.recover_promoted_turn(item, request_id) for _ in range(8)])
    held = set(rig.agent._promoted_turn_tasks)
    if held:
        await asyncio.gather(*held)
    assert outcomes.count(RESUME_STARTED) == 1
    assert len(rig.runs) == 1


@pytest.mark.asyncio
async def test_recovery_cancellation_and_drain_hold_set(rig: Rig) -> None:
    gate = asyncio.Event()

    async def _slow(self: Any, **kw: Any) -> Any:
        rig.runs.append(kw)
        await gate.wait()
        return SimpleNamespace(final_text="", stopped_reason="completed")

    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    import probos.cognitive.agentic_dispatch as dispatch

    original = dispatch.WorkItemAgenticExecutor.run
    dispatch.WorkItemAgenticExecutor.run = _slow  # restored by monkeypatch teardown of the fixture
    try:
        assert await rig.agent.recover_promoted_turn(item, request_id) == RESUME_STARTED
        await asyncio.sleep(0)
        held = set(rig.agent._promoted_turn_tasks)
        assert len(held) == 1
        for task in held:
            task.cancel()
        results = await asyncio.gather(*held, return_exceptions=True)
        assert all(isinstance(r, asyncio.CancelledError) for r in results)
        await asyncio.sleep(0)
        assert rig.agent._promoted_turn_tasks == set()
    finally:
        dispatch.WorkItemAgenticExecutor.run = original


@pytest.mark.asyncio
async def test_recovery_respects_plan_mode_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, token_budget=1024, agent_modes_enabled=True,
        economic_judgment={"enabled": True, "continue_extension": {"enabled": True}},
    )
    rig = await open_rig(tmp_path, monkeypatch, config=config)
    try:
        from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS

        item = await promoted_item(rig)
        request_id = await ask(rig, item, plan_mode=True, config=config)
        await approve(rig, request_id)
        assert rig.starts[0]["plan_mode"] is True
        assert rig.runs[0]["plan_mode_tool_ids"] == PLAN_MODE_TOOL_IDS
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_recovery_without_plan_mode_adds_no_plan_restriction(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    assert "plan_mode_tool_ids" not in rig.runs[0]
    assert rig.starts[0]["plan_mode"] is False


@pytest.mark.asyncio
async def test_tier3_consensus_gating_unchanged_under_recovery(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    allowed = {
        "agent_id", "instructions", "task_text", "runtime", "thread_id", "max_iterations", "tier",
        "compose_disposition", "failure_scope", "token_budget", "plan_mode_tool_ids",
    }
    assert set(rig.runs[0]) <= allowed
    assert rig.runs[0]["runtime"] is rig.runtime


@pytest.mark.asyncio
async def test_recovery_without_snapshot_fails_closed(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    blank = SimpleNamespace(id=item.id, description=TASK, metadata={})
    assert await rig.agent.recover_promoted_turn(blank, request_id) == RESUME_NO_CONTINUATION
    assert rig.runs == []

@pytest.mark.asyncio
async def test_restart_recovery_seam_starts_one_pass(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    # The crash point: the driver's compare-and-set moved the item, nothing started a pass.
    moved = await rig.items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver", expected_status="blocked",
        expected={"capability_request_id": request_id},
    )
    assert moved is not None
    outcome = await resume_promoted_turn(rig.runtime, moved, request_id)
    held = set(rig.agent._promoted_turn_tasks)
    if held:
        await asyncio.gather(*held)
    assert outcome == RESUME_STARTED
    assert len(rig.runs) == 1

@pytest.mark.asyncio
async def test_startup_sweep_never_raises(rig: Rig) -> None:
    class _Broken:
        async def void_expired(self) -> int:
            raise RuntimeError("disk gone")

    rig.runtime.continue_extension_permit_store = _Broken()
    report = await recover_continue_permits(rig.runtime)
    assert report.failed == 1
    rig.runtime.continue_extension_permit_store = None
    assert (await recover_continue_permits(rig.runtime)).examined == 0


# ---- AD-1323 amendment 2: the fulfiller gate on unbound permits


class _MarkStore:
    def __init__(self) -> None:
        self.fulfilled: list[str] = []

    async def mark_fulfilled(self, rid: str) -> Any:
        self.fulfilled.append(rid)
        return "ok"


async def _unbound(rig: Rig, work_item_id: str = "wi-gate") -> str:
    placeholder = await rig.permits.reserve_filing(
        agent_id=AGENT, work_item_id=work_item_id, thread_id=THREAD, cap_tokens=300,
        stop_text=STOP, plan_mode=False, configured_budget=1024,
    )
    assert placeholder, "premise: an unbound permit must exist"
    return placeholder


@pytest.mark.asyncio
async def test_fulfiller_refuses_unbound_permit_without_marking_fulfilled(rig: Rig) -> None:
    await _unbound(rig)
    store = _MarkStore()
    decided = SimpleNamespace(id="req-gate", work_item_id="wi-gate", decided_by="captain")
    assert await _fulfil_by_approval_itself(rig.runtime, store, decided) is None
    assert store.fulfilled == []  # not fulfilled: the sweep/reconciler retries once bound
    assert [p.state for p in await rig.permits.list_unbound()] == ["requested"]


@pytest.mark.asyncio
async def test_fulfiller_ordinary_continue_unchanged_when_no_permit_row(rig: Rig) -> None:
    store = _MarkStore()
    decided = SimpleNamespace(id="req-plain", work_item_id="wi-none", decided_by="captain")
    assert await _fulfil_by_approval_itself(rig.runtime, store, decided) == "ok"
    assert store.fulfilled == ["req-plain"]


@pytest.mark.asyncio
async def test_fulfiller_voided_placeholder_fulfils_as_ordinary_continue_no_extension(rig: Rig) -> None:
    await _unbound(rig)
    assert await rig.permits.void_unbound("wi-gate") is True
    store = _MarkStore()
    decided = SimpleNamespace(id="req-gate", work_item_id="wi-gate", decided_by="captain")
    assert await _fulfil_by_approval_itself(rig.runtime, store, decided) == "ok"
    assert store.fulfilled == ["req-gate"]
    assert await rig.permits.list_active() == []


@pytest.mark.asyncio
async def test_delegated_approval_path_also_refuses_unbound_permit(rig: Rig) -> None:
    await _unbound(rig)
    store = _MarkStore()
    for decider in ("captain", "first_officer"):
        decided = SimpleNamespace(id="req-gate", work_item_id="wi-gate", decided_by=decider)
        assert await _fulfil_by_approval_itself(rig.runtime, store, decided) is None
    assert store.fulfilled == []


@pytest.mark.asyncio
async def test_agent_still_cannot_activate_own_permit_when_unbound(rig: Rig) -> None:
    await _unbound(rig)
    store = _MarkStore()
    decided = SimpleNamespace(id="req-gate", work_item_id="wi-gate", decided_by=AGENT)
    assert await _fulfil_by_approval_itself(rig.runtime, store, decided) is None
    assert store.fulfilled == []
    assert await rig.permits.list_active() == []

# ---- AD-1323 amendment 3: claim outcomes, persisted plan floor, strict snapshot, admission


def _sql(tmp_path: Path, statement: str) -> None:
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(str(tmp_path / "permits.db"))) as db:
        db.execute(statement)
        db.commit()


@pytest.mark.asyncio
async def test_consumed_permit_recovery_is_already_admitted_and_changes_nothing(rig: Rig) -> None:
    from probos.cognitive.turn_promotion import RESUME_ALREADY_ADMITTED

    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    assert len(rig.runs) == 1
    assert await rig.agent.recover_promoted_turn(item, request_id) == RESUME_ALREADY_ADMITTED
    assert len(rig.runs) == 1
    after = await rig.permits.get(request_id)
    assert after is not None and after.state == "consumed"


@pytest.mark.asyncio
async def test_resume_promoted_turn_already_admitted_no_close_no_notify(rig: Rig) -> None:
    from probos.cognitive.turn_promotion import RESUME_ALREADY_ADMITTED, RESUME_LOST_REASONS

    assert RESUME_ALREADY_ADMITTED not in RESUME_LOST_REASONS
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    moved = await rig.items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver", expected_status="blocked",
        expected={"capability_request_id": request_id},
    )
    assert moved is not None
    # another process already holds the claim
    won = await rig.permits.consume(request_id, agent_id=AGENT, work_item_id=item.id, thread_id=THREAD)
    assert won is not None
    posted: list[Any] = []
    rig.runtime.chat_thread_store = SimpleNamespace(
        add_post=lambda *a, **k: posted.append((a, k)), create_thread=lambda *a, **k: None,
    )
    assert await resume_promoted_turn(rig.runtime, moved, request_id) == RESUME_ALREADY_ADMITTED
    current = await rig.items.get_work_item(item.id)
    assert current is not None and current.status == "in_progress"
    assert "stranded_reason" not in (current.metadata or {})
    assert posted == [] and rig.runs == []


@pytest.mark.asyncio
async def test_two_resumers_one_real_run_loser_leaves_the_item_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.turn_promotion import RESUME_ALREADY_ADMITTED

    rig = await open_rig(tmp_path, monkeypatch, real_start=True)
    try:
        gate = asyncio.Event()

        async def _held(self: Any, **kw: Any) -> Any:
            rig.runs.append(kw)
            await gate.wait()
            return SimpleNamespace(final_text="done", stopped_reason="completed")

        monkeypatch.setattr("probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor.run", _held)
        item = await promoted_item(rig)
        request_id = await ask(rig, item)
        await rig.permits.activate(request_id, decided_by="captain")
        moved = await rig.items.transition_work_item(
            item.id, "in_progress", source="capability_gap_driver", expected_status="blocked",
            expected={"capability_request_id": request_id},
        )
        outcomes = await asyncio.gather(
            resume_promoted_turn(rig.runtime, moved, request_id),
            resume_promoted_turn(rig.runtime, moved, request_id),
        )
        assert sorted(outcomes) == sorted([RESUME_STARTED, RESUME_ALREADY_ADMITTED])
        for _ in range(20):
            await asyncio.sleep(0)
        mid = await rig.items.get_work_item(item.id)
        assert mid is not None and mid.status == "in_progress"
        assert "stranded_reason" not in (mid.metadata or {})
        gate.set()
        held = set(rig.agent._promoted_turn_tasks)
        if held:
            await asyncio.gather(*held, return_exceptions=True)
        assert len(rig.runs) == 1
        final = await rig.items.get_work_item(item.id)
        assert final is not None and final.status == "done"
        assert "stranded_reason" not in (final.metadata or {})
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_recovered_pass_begin_pass_refused_raises_pass_not_admitted_and_item_untouched(
    rig: Rig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.turn_promotion import PassNotAdmitted

    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")

    async def _refused(_rid: str) -> bool:
        return False

    monkeypatch.setattr(rig.permits, "begin_pass", _refused)
    assert await rig.agent.recover_promoted_turn(item, request_id) == RESUME_STARTED
    task = next(iter(rig.agent._promoted_turn_tasks))
    kw = rig.starts[0]
    results = await asyncio.gather(task, return_exceptions=True)  # the rig's start runs the work task bare
    assert any(isinstance(r, PassNotAdmitted) for r in results), results
    assert rig.runs == [] and kw["settle_expected"] == {"capability_request_id": request_id}


@pytest.mark.asyncio
async def test_recovered_pass_persisted_plan_floor_applies_with_flag_off(rig: Rig) -> None:
    from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS

    assert rig.runtime.config.dm_agentic.agent_modes_enabled is False  # premise: flag off
    item = await promoted_item(rig)
    request_id = await ask(rig, item, plan_mode=True)
    await approve(rig, request_id)
    assert rig.starts[0]["plan_mode"] is True
    assert rig.runs[0]["plan_mode_tool_ids"] == PLAN_MODE_TOOL_IDS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE continue_extension_permits SET stop_text = NULL",
        "UPDATE continue_extension_permits SET stop_text = '   '",
        "UPDATE continue_extension_permits SET plan_mode = NULL",
        "UPDATE continue_extension_permits SET plan_mode = ''",
        "UPDATE continue_extension_permits SET plan_mode = 'not-a-boolean'",
        "UPDATE continue_extension_permits SET plan_mode = 2",
        "UPDATE continue_extension_permits SET plan_mode = 0.5",
        "UPDATE continue_extension_permits SET configured_budget = NULL",
    ],
)
async def test_recovery_with_invalid_snapshot_voids_before_claim_and_runs_nothing(
    rig: Rig, tmp_path: Path, statement: str,
) -> None:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    _sql(tmp_path, statement)
    outcome = await rig.agent.recover_promoted_turn(item, request_id)
    assert outcome == RESUME_NO_CONTINUATION
    assert rig.runs == [] and rig.starts == []
    row = await rig.permits.get(request_id)
    assert row is not None and row.state == "voided" and row.started_at is None


# ---- AD-1323 amendment 5: state-aware fulfiller and the cancelled-filing approval chain


async def _bound(rig: Rig, request_id: str, work_item_id: str) -> str:
    await _unbound(rig, work_item_id)
    assert await rig.permits.bind(work_item_id, request_id) is True
    return request_id


def _decided(request_id: str, work_item_id: str, by: str = "captain") -> Any:
    return SimpleNamespace(id=request_id, work_item_id=work_item_id, decided_by=by)


async def _cancel_after_bind_commit(rig: Rig, item: Any) -> str:
    original = rig.permits.bind

    async def _bind(work_item_id: str, request_id: str) -> bool:
        await original(work_item_id, request_id)  # the bind is durable...
        raise asyncio.CancelledError  # ...and the cancel lands right after it

    rig.permits.bind = _bind  # type: ignore[method-assign]

    async def _promote() -> str | None:
        return item.id

    with pytest.raises(asyncio.CancelledError):
        await file_costed_continue(
            rig.runtime, agent_id=AGENT, thread_id=THREAD, base_task_text=TASK, display_task_text=TASK,
            case=_case(), config=_config(), promote=_promote, work_item_id=None, passes=1,
            stop_text=STOP, plan_mode=False, configured_budget=1024, parked={},
        )
    rig.permits.bind = original  # type: ignore[method-assign]
    pending = await rig.requests.list_pending()
    assert len(pending) == 1, "premise: the cancelled filing left its request filed"
    row = await rig.permits.get(pending[0].id)
    assert row is not None and row.bound is True, "premise: the permit was bound before the cancel"
    return pending[0].id


@pytest.mark.asyncio
async def test_cancelled_bound_permit_then_real_captain_approval_fulfils_ordinary_continue_with_no_extension(
    rig: Rig,
) -> None:
    item = await promoted_item(rig)
    request_id = await _cancel_after_bind_commit(rig, item)
    await approve(rig, request_id)
    req = await rig.requests.get(request_id)
    assert req is not None and req.status == "fulfilled"
    permit = await rig.permits.get(request_id)
    assert permit is not None and permit.state == "voided"
    assert await rig.permits.list_active() == []
    # The cancelled filer never registered a continuation, so no pass runs at all (and so none
    # can run extended); the ordinary AD-855 stranded-turn path settles the item instead.
    assert rig.runs == []
    stranded = await rig.items.get_work_item(item.id)
    assert stranded is not None and stranded.status != "blocked"


@pytest.mark.asyncio
async def test_voided_bound_permit_fulfilment_is_idempotent_on_repeat_approval(rig: Rig) -> None:
    item = await promoted_item(rig)
    request_id = await _cancel_after_bind_commit(rig, item)
    marked: list[str] = []
    original = rig.requests.mark_fulfilled

    async def _counting(rid: str) -> Any:
        marked.append(rid)
        return await original(rid)

    rig.requests.mark_fulfilled = _counting  # type: ignore[method-assign]
    await approve(rig, request_id)
    with pytest.raises(Exception):
        await decide_capability_request(
            request_id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
        )
    event = {"type": "capability_request_fulfilled", "data": {"id": request_id}}
    await rig.driver.on_capability_event(event)
    await rig.bus.drain()
    assert marked == [request_id]
    assert rig.runs == []
    assert await rig.permits.list_active() == []
    permit = await rig.permits.get(request_id)
    assert permit is not None and permit.state == "voided"


@pytest.mark.asyncio
async def test_fulfiller_voided_bound_row_fulfils_as_ordinary_continue(rig: Rig) -> None:
    await _bound(rig, "req-b", "wi-b")
    assert await rig.permits.void_reservation("wi-b", "req-b") is True
    store = _MarkStore()
    assert await _fulfil_by_approval_itself(rig.runtime, store, _decided("req-b", "wi-b")) == "ok"
    assert store.fulfilled == ["req-b"]
    assert await rig.permits.list_active() == []
    row = await rig.permits.get("req-b")
    assert row is not None and row.state == "voided"


@pytest.mark.asyncio
async def test_fulfiller_still_blocks_requested_unbound_and_bound_not_ready_rows(rig: Rig) -> None:
    await _unbound(rig, "wi-u")
    await _bound(rig, "req-b", "wi-b")
    store = _MarkStore()
    assert await _fulfil_by_approval_itself(rig.runtime, store, _decided("req-u", "wi-u")) is None
    for decider in (AGENT, "", "   "):
        assert await _fulfil_by_approval_itself(rig.runtime, store, _decided("req-b", "wi-b", decider)) is None
    assert store.fulfilled == []
    row = await rig.permits.get("req-b")
    assert row is not None and row.state == "requested"
    assert await rig.permits.list_active() == []


@pytest.mark.asyncio
async def test_fulfiller_active_and_consumed_rows_are_idempotent(rig: Rig) -> None:
    await _bound(rig, "req-a", "wi-a")
    assert await rig.permits.activate("req-a", decided_by="captain") is not None
    store = _MarkStore()
    assert await _fulfil_by_approval_itself(rig.runtime, store, _decided("req-a", "wi-a")) == "ok"
    assert await _fulfil_by_approval_itself(rig.runtime, store, _decided("req-a", "wi-a", "first_officer")) is None
    assert store.fulfilled == ["req-a"]

    await _bound(rig, "req-c", "wi-c")
    await rig.permits.activate("req-c", decided_by="captain")
    assert await rig.permits.consume("req-c", agent_id=AGENT, work_item_id="wi-c", thread_id=THREAD) is not None
    activations: list[str] = []
    original = rig.permits.activate

    async def _spy(rid: str, *, decided_by: str) -> Any:
        activations.append(rid)
        return await original(rid, decided_by=decided_by)

    rig.permits.activate = _spy  # type: ignore[method-assign]
    assert await _fulfil_by_approval_itself(rig.runtime, store, _decided("req-c", "wi-c")) == "ok"
    assert store.fulfilled == ["req-a", "req-c"]
    assert activations == []
    row = await rig.permits.get("req-c")
    assert row is not None and row.state == "consumed"


class _BarrierStore(SqliteContinueExtensionPermitStore):
    """Real store whose two competing writes each park at a gate the test opens in a chosen order."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.arrived = {"activate": asyncio.Event(), "void": asyncio.Event()}
        self.gates = {"activate": asyncio.Event(), "void": asyncio.Event()}

    async def _write(self, sql: str, params: tuple[Any, ...]) -> int:
        which = "activate" if "SET state = 'active'" in sql else "void" if "SET state = 'voided'" in sql else ""
        if which and not self.gates[which].is_set():
            self.arrived[which].set()
            await self.gates[which].wait()
        return await super()._write(sql, params)


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["activate", "void"])
async def test_activation_racing_void_reservation_never_extends_a_voided_permit(
    tmp_path: Path, first: str,
) -> None:
    store = _BarrierStore(str(tmp_path / "race.db"))
    await store.start()
    try:
        await store.reserve_filing(
            agent_id=AGENT, work_item_id="wi-r", thread_id=THREAD, cap_tokens=300,
            stop_text=STOP, plan_mode=False, configured_budget=1024,
        )
        await store.bind("wi-r", "req-r")
        activate = asyncio.create_task(store.activate("req-r", decided_by="captain"))
        void = asyncio.create_task(store.void_reservation("wi-r", "req-r"))
        await asyncio.wait_for(store.arrived["activate"].wait(), 5)
        await asyncio.wait_for(store.arrived["void"].wait(), 5)  # both are in flight: a real race
        second = "void" if first == "activate" else "activate"
        store.gates[first].set()
        await (activate if first == "activate" else void)
        store.gates[second].set()
        activated, voided = await activate, await void
        row = await store.get("req-r")
        assert row is not None
        runtime = SimpleNamespace(continue_extension_permit_store=store)
        marks = _MarkStore()
        assert await _fulfil_by_approval_itself(runtime, marks, _decided("req-r", "wi-r")) == "ok"
        assert marks.fulfilled == ["req-r"]
        if first == "activate":
            assert (row.state, activated is not None, voided) == ("active", True, False)
            assert [p.request_id for p in await store.list_active()] == ["req-r"]
        else:
            assert (row.state, activated, voided) == ("voided", None, True)
            assert await store.list_active() == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_fulfiller_reread_distinguishes_lost_void_race_from_self_approval(tmp_path: Path) -> None:
    class _LosesToVoid(SqliteContinueExtensionPermitStore):
        async def activate(self, request_id: str, *, decided_by: str) -> Any:
            await self.void_reservation("wi-x", request_id)  # a concurrent cleanup wins first
            return await super().activate(request_id, decided_by=decided_by)

    store = _LosesToVoid(str(tmp_path / "reread.db"))
    await store.start()
    try:
        runtime = SimpleNamespace(continue_extension_permit_store=store)
        for rid, wi in (("req-x", "wi-x"), ("req-y", "wi-y")):
            await store.reserve_filing(
                agent_id=AGENT, work_item_id=wi, thread_id=THREAD, cap_tokens=300,
                stop_text=STOP, plan_mode=False, configured_budget=1024,
            )
            await store.bind(wi, rid)
        marks = _MarkStore()
        assert await _fulfil_by_approval_itself(runtime, marks, _decided("req-x", "wi-x")) == "ok"
        assert marks.fulfilled == ["req-x"]
        # the asker approving its own still-requested permit is refused: nothing fulfilled
        plain = SqliteContinueExtensionPermitStore(str(tmp_path / "reread2.db"))
        await plain.start()
        try:
            await plain.reserve_filing(
                agent_id=AGENT, work_item_id="wi-z", thread_id=THREAD, cap_tokens=300,
                stop_text=STOP, plan_mode=False, configured_budget=1024,
            )
            await plain.bind("wi-z", "req-z")
            marks2 = _MarkStore()
            own = SimpleNamespace(continue_extension_permit_store=plain)
            assert await _fulfil_by_approval_itself(own, marks2, _decided("req-z", "wi-z", AGENT)) is None
            assert marks2.fulfilled == []
            row = await plain.get("req-z")
            assert row is not None and row.state == "requested"
        finally:
            await plain.stop()
    finally:
        await store.stop()
