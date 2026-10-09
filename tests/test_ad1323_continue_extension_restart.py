"""AD-1323 (#1478): durable recovery across a restart. Every case closes every store and reopens the same files."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.cognitive.promoted_turn_recovery import recover_continue_permits
from probos.routers.capability_requests import decide_capability_request
from tests.test_ad1323_continue_extension_e2e import (
    AGENT,
    Rig,
    ask,
    approve,
    close_rig,
    open_rig,
    promoted_item,
    rig,  # noqa: F401  (pytest fixture)
)


async def _settle(rig: Rig) -> None:
    await rig.bus.drain()
    held = set(rig.agent._promoted_turn_tasks)
    if held:
        await asyncio.gather(*held, return_exceptions=True)


async def _crash_after_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Ask, then approve with the driver unable to run: the approval is durable, nothing else is."""
    rig = await open_rig(tmp_path, monkeypatch)
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    rig.bus._listeners.clear()  # the process dies before the listener acts
    await decide_capability_request(
        request_id, CapabilityRequestDecideRequest(approve=True), runtime=rig.runtime,
    )
    assert rig.runs == []
    await close_rig(rig)
    return item.id, request_id


@pytest.mark.asyncio
async def test_restart_after_approval_before_consumption_recovers_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id, request_id = await _crash_after_approval(tmp_path, monkeypatch)
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        premise = await rig.permits.get(request_id)
        assert premise is not None and premise.state == "active"
        report = await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert (report.examined, report.redelivered) == (1, 1)
        assert len(rig.runs) == 1 and rig.runs[0]["token_budget"] == 1024
        again = await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert again.examined == 0 and len(rig.runs) == 1
        permit = await rig.permits.get(request_id)
        assert permit is not None and permit.state == "consumed"
        assert item_id
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_restart_after_cas_before_consume_recovers_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    await rig.requests.mark_fulfilled(request_id)
    rig.bus._listeners.clear()
    moved = await rig.items.transition_work_item(
        item.id, "in_progress", source="capability_gap_driver", expected_status="blocked",
        expected={"capability_request_id": request_id},
    )
    assert moved is not None
    await close_rig(rig)
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        report = await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert report.resumed == 1
        assert len(rig.runs) == 1
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_restart_after_consumption_no_second_use_no_duplicate_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await approve(rig, request_id)
    assert len(rig.runs) == 1
    await close_rig(rig)
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        report = await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert report.examined == 0  # consumed permits are not listed active
        assert rig.runs == []
        permit = await rig.permits.get(request_id)
        assert permit is not None and permit.state == "consumed"
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_startup_sweep_leaves_consumed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        item = await promoted_item(rig)
        request_id = await ask(rig, item)
        await approve(rig, request_id)
        before = await rig.permits.get(request_id)
        await recover_continue_permits(rig.runtime)
        assert await rig.permits.get(request_id) == before
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_restart_before_approval_then_approve_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await close_rig(rig)
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        report = await recover_continue_permits(rig.runtime)
        assert (report.examined, report.voided, report.resumed) == (0, 0, 0)  # requested: left alone
        await approve(rig, request_id)
        assert len(rig.runs) == 1 and rig.runs[0]["token_budget"] == 1024
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_startup_sweep_voids_denied_or_gone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        gone_item = await promoted_item(rig)
        gone_req = await ask(rig, gone_item)
        await rig.permits.activate(gone_req, decided_by="captain")
        await rig.items.transition_work_item(gone_item.id, "cancelled", source="captain")
        report = await recover_continue_permits(rig.runtime)
        assert report.voided == 1
        permit = await rig.permits.get(gone_req)
        assert permit is not None and permit.state == "voided"
        assert rig.runs == []
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_expired_permit_is_voided_by_the_sweep_and_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await open_rig(tmp_path, monkeypatch, ttl=60)
    try:
        item = await promoted_item(rig)
        request_id = await ask(rig, item)
        await rig.permits.activate(request_id, decided_by="captain")
        clock = rig.permits._clock
        rig.permits._clock = lambda: clock() + 120
        report = await recover_continue_permits(rig.runtime)
        assert report.expired_voided == 1
        assert rig.runs == []
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_restart_e2e_approval_to_resumed_pass_single_store_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id, request_id = await _crash_after_approval(tmp_path, monkeypatch)
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert len(rig.runs) == 1
        assert rig.starts[0]["work_item_id"] == item_id
        assert rig.starts[0]["settle_expected"] == {"capability_request_id": request_id}
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_flag_off_byte_identical_promotion_and_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from probos.cognitive.costed_continue_ask import continue_extension_armed
    from probos.config import DmAgenticConfig
    from probos.startup.communication import _start_continue_extension_permit_store

    default = DmAgenticConfig()
    assert continue_extension_armed(
        default, promote_after_seconds=default.promote_to_task_after_seconds, token_budget=default.token_budget,
    ) is False
    system = type("S", (), {"dm_agentic": default})()
    assert await _start_continue_extension_permit_store(system, tmp_path) is None  # type: ignore[arg-type]
    assert not (tmp_path / "continue_extension_permits.db").exists()
    other = tmp_path / "unarmed"
    other.mkdir()
    rig = await open_rig(other, monkeypatch, permits=False)
    try:
        assert await recover_continue_permits(rig.runtime) is not None
        assert rig.runs == []
    finally:
        await close_rig(rig)


# ---- AD-1323 amendment 2: unbound rows, mid-filing approvals, start-claim reclaim


async def _reopen_with_reconciler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> Rig:
    from probos.startup.finalize import _wire_continue_extension_reconciler

    rig = await open_rig(tmp_path, monkeypatch, **kw)
    assert _wire_continue_extension_reconciler(runtime=rig.runtime) is True
    return rig


@pytest.mark.asyncio
async def test_sweep_voids_unbound_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        assert await rig.permits.reserve_filing(
            agent_id="a", work_item_id="wi-x", thread_id="t", cap_tokens=1, stop_text="s",
            plan_mode=False, configured_budget=10,
        )
        report = await recover_continue_permits(rig.runtime)
        assert report.unbound_voided == 1
        assert await rig.permits.list_unbound() == []
        row = await rig.permits.get("filing:wi-x")
        assert row is not None and row.state == "voided"
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_sweep_reconciles_approved_unfulfilled_requested_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    rig.bus._listeners.clear()
    await rig.requests.decide(request_id, True)  # approved, never fulfilled, permit still requested
    await close_rig(rig)
    rig = await _reopen_with_reconciler(tmp_path, monkeypatch)
    try:
        premise = await rig.permits.get(request_id)
        assert premise is not None and premise.state == "requested"
        report = await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert report.reconciled == 1
        assert len(rig.runs) == 1
        permit = await rig.permits.get(request_id)
        assert permit is not None and permit.state == "consumed"
        again = await recover_continue_permits(rig.runtime)
        await _settle(rig)
        assert again.reconciled == 0 and len(rig.runs) == 1
    finally:
        await close_rig(rig)


async def _consumed_unstarted(rig: Rig) -> str:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    assert await rig.permits.consume(
        request_id, agent_id=AGENT, work_item_id=item.id, thread_id="thread-1",
    ) is not None
    return request_id


@pytest.mark.asyncio
async def test_sweep_reclaims_consumed_unstarted_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        request_id = await _consumed_unstarted(rig)
        report = await recover_continue_permits(rig.runtime)
        assert report.reclaimed == 1
        permit = await rig.permits.get(request_id)
        assert permit is not None and permit.reclaims == 1 and permit.state == "active"
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_sweep_leaves_consumed_started_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        request_id = await _consumed_unstarted(rig)
        assert await rig.permits.begin_pass(request_id) is True
        report = await recover_continue_permits(rig.runtime)
        assert report.reclaimed == 0
        permit = await rig.permits.get(request_id)
        assert permit is not None and permit.state == "consumed" and permit.reclaims == 0
        assert rig.runs == []
    finally:
        await close_rig(rig)


@pytest.mark.asyncio
async def test_sweep_does_not_reclaim_twice_or_expired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await open_rig(tmp_path, monkeypatch)
    try:
        request_id = await _consumed_unstarted(rig)
        assert (await recover_continue_permits(rig.runtime)).reclaimed == 1
        item = await rig.items.get_work_item(
            (await rig.permits.get(request_id)).work_item_id,
        )
        assert await rig.permits.consume(
            request_id, agent_id=AGENT, work_item_id=item.id, thread_id="thread-1",
        ) is not None
        assert (await recover_continue_permits(rig.runtime)).reclaimed == 0
    finally:
        await close_rig(rig)
    (tmp_path / "x").mkdir()
    expired = await open_rig(tmp_path / "x", monkeypatch)
    try:
        request_id = await _consumed_unstarted(expired)
        with sqlite3.connect(tmp_path / "x" / "permits.db") as con:  # the TTL floor is 60s
            con.execute("UPDATE continue_extension_permits SET expires_at = 1.0")
        assert (await recover_continue_permits(expired.runtime)).reclaimed == 0
    finally:
        await close_rig(expired)


async def _fulfilled_active(rig: Rig) -> tuple[Any, str]:
    item = await promoted_item(rig)
    request_id = await ask(rig, item)
    await rig.permits.activate(request_id, decided_by="captain")
    return item, request_id


@pytest.mark.asyncio
async def test_recovered_pass_does_not_run_when_begin_pass_refused(rig: Rig) -> None:
    item, request_id = await _fulfilled_active(rig)

    async def _refuse(_rid: str) -> bool:
        return False

    rig.permits.begin_pass = _refuse  # type: ignore[method-assign]
    await rig.agent.recover_promoted_turn(item, request_id)
    await _settle(rig)
    assert rig.runs == []


@pytest.mark.asyncio
async def test_recovered_pass_calls_begin_pass_inside_background_slot_before_executor(rig: Rig) -> None:
    """begin_pass is the first act of the recovered pass, before executor.run.

    Measured: ``start_resumed_run`` creates the work task immediately and only the
    *reporter* waits for the BF-732 slot, so the pass does not itself sit behind the
    slot (the amendment assumed it did). The recoverable window is therefore the
    consume -> task-start gap; the ordering asserted here is what matters.
    """
    item, request_id = await _fulfilled_active(rig)
    events: list[str] = []

    class _Slot:
        async def __aenter__(self) -> None:
            events.append("slot_enter")

        async def __aexit__(self, *_a: Any) -> None:
            events.append("slot_exit")

    class _Cm:
        def slot(self, *_a: Any) -> Any:
            return _Slot()

    real = rig.permits.begin_pass

    async def _spy(rid: str) -> bool:
        events.append(f"begin_pass(runs={len(rig.runs)})")
        return await real(rid)

    rig.permits.begin_pass = _spy  # type: ignore[method-assign]
    rig.agent._concurrency_manager = _Cm()
    await rig.agent.recover_promoted_turn(item, request_id)
    await _settle(rig)
    assert events[:1] == ["begin_pass(runs=0)"] or events[1:2] == ["begin_pass(runs=0)"]
    assert [e for e in events if e.startswith("begin_pass")] == ["begin_pass(runs=0)"]
    assert len(rig.runs) == 1