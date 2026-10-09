"""AD-1324 amendment 2 (finding 5): every armed terminal has one closed audit record; writes are bounded."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pytest

from probos.cognitive import tier_audit
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.tier_audit import TierAuditSink
from tests.test_ad1324_audit import _EventLog
from tests.test_ad1324_loop_tier_choice import Client, Resp, Tools, controller

KEYS = {
    "event", "agent_id", "work_item_id", "thread_id", "step", "requested_tier", "effective_tier", "floor",
    "outcome", "evidence", "model_reason", "exact", "request_id", "error_kind", "cause", "ask_request_id", "parked",
}


class _GatedLog:
    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.calls: list[dict[str, Any]] = []

    async def log(self, category: str, event: str, agent_id: str | None = None, **kw: Any) -> None:
        await self.gate.wait()
        self.calls.append(kw["data"])


async def _run(responses: list[Any], sink: TierAuditSink) -> Any:
    ctl = controller("severe", audit=sink.emit)
    ctl.audit_sink = sink
    loop = AgenticLoop(llm_client=Client(responses), tool_executor=Tools(), tier="fast", max_iterations=3, tier_controller=ctl)
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    await sink.drain()
    return result


@pytest.mark.asyncio
async def test_floor_unmet_terminal_is_one_closed_record() -> None:
    log = _EventLog()
    sink = TierAuditSink(log, agent_id="ezri", thread_id="t1")
    result = await _run([Resp([], error_kind="tier_floor_unmet")], sink)
    assert result.stopped_reason == "tier_floor_unavailable"
    records = [c["data"] for c in log.calls]
    terminal = [r for r in records if r["outcome"] == "refused"]
    assert len(terminal) == 1 and set(terminal[0]) == KEYS
    assert terminal[0]["error_kind"] == "tier_floor_unmet" and terminal[0]["floor"] == "deep"
    assert terminal[0]["cause"] is None or terminal[0]["cause"] == "floor_unmet"


@pytest.mark.asyncio
async def test_unverifiable_route_under_a_floor_is_an_ask_stop_and_a_faulted_record() -> None:
    log = _EventLog()
    sink = TierAuditSink(log, agent_id="ezri", thread_id="t1")
    result = await _run([Resp([], error_kind="tier_route_unverifiable")], sink)
    assert result.stopped_reason == "tier_floor_unavailable", "a floor exists, so dispatch files the ask"
    terminal = [c["data"] for c in log.calls if c["data"]["outcome"] == "faulted"]
    assert len(terminal) == 1 and terminal[0]["cause"] == "route_unverifiable"


def test_free_text_never_reaches_a_record() -> None:
    sink = TierAuditSink(None, agent_id="a", thread_id="t")
    sink.emit_terminal(outcome="refused", step=1, floor="deep", request_id="r", evidence="SECRET text here", cause="Bad Cause!")
    sink.emit_terminal(outcome="refused", step=1, floor="deep", request_id="r", error_kind="x" * 80)


@pytest.mark.asyncio
async def test_held_writer_does_not_block_past_the_drain_bound_and_lands_once(caplog: pytest.LogCaptureFixture) -> None:
    log = _GatedLog()
    sink = TierAuditSink(log, agent_id="ezri", thread_id="t1")
    sink.emit_terminal(outcome="refused", step=1, floor="deep", request_id="r1")
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger=tier_audit.logger.name):
        await asyncio.wait_for(sink.drain(), 3)  # a drain with no bound fails here instead of hanging
    assert time.monotonic() - started < 0.75
    assert log.calls == [] and "did not finish" in caplog.text
    log.gate.set()
    await asyncio.sleep(0.05)
    assert len(log.calls) == 1 and not tier_audit._RETAINED


@pytest.mark.asyncio
async def test_cap_overflow_drops_with_a_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    log = _GatedLog()
    monkeypatch.setattr(tier_audit, "AUDIT_MAX_INFLIGHT", 2)
    sink = TierAuditSink(log, agent_id="ezri", thread_id="t1")
    with caplog.at_level(logging.WARNING, logger=tier_audit.logger.name):
        for i in range(4):
            sink.emit_terminal(outcome="refused", step=i, floor="deep", request_id=f"r{i}")
    assert len(tier_audit._RETAINED) == 2 and "logged only" in caplog.text
    log.gate.set()
    await asyncio.sleep(0.05)
    assert len(log.calls) == 2


@pytest.mark.asyncio
async def test_cancelled_drain_propagates_and_the_write_survives() -> None:
    log = _GatedLog()
    sink = TierAuditSink(log, agent_id="ezri", thread_id="t1")
    sink.emit_terminal(outcome="refused", step=1, floor="deep", request_id="r1")
    waiter = asyncio.create_task(sink.drain())
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    log.gate.set()
    await asyncio.sleep(0.05)
    assert len(log.calls) == 1


@pytest.mark.asyncio
async def test_writer_failure_never_reaches_the_caller() -> None:
    sink = TierAuditSink(_EventLog(fail=True), agent_id="ezri", thread_id="t1")
    sink.emit_terminal(outcome="faulted", step=1, floor=None, request_id=None)
    await sink.drain()

@pytest.mark.asyncio
async def test_floor_unmet_terminal_carries_work_item_and_effective_tier_in_a_real_event_log(tmp_path: Any) -> None:
    from probos.substrate.event_log import EventLog

    log = EventLog(tmp_path / "e.db")
    await log.start()
    try:
        sink = TierAuditSink(log, agent_id="ezri", thread_id="t1")
        result = await _run([Resp([], error_kind="tier_floor_unmet")], sink)
        await sink.drain()
        assert result.stopped_reason == "tier_floor_unavailable"
        rows = [r["data"] for r in await log.query(category="cognitive", limit=50) if r["event"] == tier_audit.EVENT_NAME]
        terminal = [r for r in rows if r["outcome"] == "refused"]
        assert len(terminal) == 1, "premise: one terminal record reached the real log"
        assert terminal[0]["work_item_id"] == "w-1" and terminal[0]["effective_tier"] == "deep"
        assert terminal[0]["requested_tier"] == "fast"
    finally:
        await log.stop()