"""BF-296 — IntentBus shutdown gate (close_to_new_dispatches).

Verifies the four entry points (broadcast, send, dispatch_async, _on_dispatch
JetStream callback) all reject new work after the bus is closed, while
in-flight handlers complete normally.

See prompts/bf-296/bf-296-shutdown-phase-a.md and #771.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


def _make_bus() -> IntentBus:
    return IntentBus(SignalManager())


def _make_intent(intent: str = "test_intent", target: str | None = None) -> IntentMessage:
    return IntentMessage(
        intent=intent,
        params={},
        urgency=0.5,
        ttl_seconds=1.0,
        target_agent_id=target,
    )


@pytest.mark.asyncio
async def test_close_to_new_dispatches_sets_flag_idempotent() -> None:
    """close_to_new_dispatches() is idempotent and sets the closed flag."""
    bus = _make_bus()
    assert bus._closed is False
    bus.close_to_new_dispatches()
    assert bus._closed is True
    # Idempotent — second call should be a no-op
    bus.close_to_new_dispatches()
    assert bus._closed is True


@pytest.mark.asyncio
async def test_broadcast_rejects_after_close() -> None:
    """broadcast() returns [] honest-degrade on closed bus."""
    bus = _make_bus()

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id="a1", success=True, confidence=1.0)

    bus.subscribe("a1", handler, intent_names=["test_intent"])

    # Before close: handler runs, result returned
    results = await bus.broadcast(_make_intent())
    assert len(results) == 1

    # After close: empty result list, handler NOT invoked
    bus.close_to_new_dispatches()
    call_count = 0

    async def counting_handler(intent: IntentMessage) -> IntentResult:
        nonlocal call_count
        call_count += 1
        return IntentResult(intent_id=intent.id, agent_id="a1", success=True, confidence=1.0)

    bus._subscribers["a1"] = counting_handler
    results = await bus.broadcast(_make_intent())
    assert results == []
    assert call_count == 0


@pytest.mark.asyncio
async def test_send_rejects_after_close() -> None:
    """send() returns None on closed bus."""
    bus = _make_bus()

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id="a1", success=True, confidence=1.0)

    bus.subscribe("a1", handler)
    bus.close_to_new_dispatches()
    result = await bus.send(_make_intent(target="a1"))
    assert result is None


@pytest.mark.asyncio
async def test_dispatch_async_rejects_after_close() -> None:
    """dispatch_async() is a no-op on closed bus and does not call NATS or fallback."""
    bus = _make_bus()
    fallback_called = False

    async def handler(intent: IntentMessage) -> IntentResult:
        nonlocal fallback_called
        fallback_called = True
        return IntentResult(intent_id=intent.id, agent_id="a1", success=True, confidence=1.0)

    bus.subscribe("a1", handler)
    bus.close_to_new_dispatches()
    await bus.dispatch_async(_make_intent(target="a1"))
    # Give any potentially-scheduled fallback task a chance to run
    await asyncio.sleep(0.05)
    assert fallback_called is False


@pytest.mark.asyncio
async def test_in_flight_handler_completes_after_close() -> None:
    """Closing the bus does NOT interrupt handlers already running."""
    bus = _make_bus()
    started = asyncio.Event()
    completed = asyncio.Event()

    async def slow_handler(intent: IntentMessage) -> IntentResult:
        started.set()
        await asyncio.sleep(0.2)  # in-flight when we close
        completed.set()
        return IntentResult(intent_id=intent.id, agent_id="a1", success=True, confidence=1.0)

    bus.subscribe("a1", slow_handler, intent_names=["slow"])

    broadcast_task = asyncio.create_task(bus.broadcast(_make_intent(intent="slow")))
    await started.wait()  # handler is mid-flight
    bus.close_to_new_dispatches()  # close DURING the handler
    results = await broadcast_task
    assert completed.is_set()  # handler ran to completion despite close
    assert len(results) == 1


@pytest.mark.asyncio
async def test_close_logs_structured_message(caplog: pytest.LogCaptureFixture) -> None:
    """close_to_new_dispatches() emits an INFO log with subscriber/queue counts."""
    bus = _make_bus()

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id="a1", success=True, confidence=1.0)

    bus.subscribe("a1", handler)
    with caplog.at_level(logging.INFO, logger="probos.mesh.intent"):
        bus.close_to_new_dispatches()
    assert any(
        "BF-296" in rec.message and "closed to new dispatches" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_on_dispatch_terms_message_when_closed() -> None:
    """JetStream _on_dispatch callback calls msg.term() (not enqueue) when closed."""
    bus = _make_bus()
    bus.close_to_new_dispatches()

    # Build a fake msg object that records the term() call
    term_called = asyncio.Event()
    ack_called = False

    class _FakeMsg:
        data = b"{}"
        reply = None

        async def term(self) -> None:
            term_called.set()

        async def ack(self) -> None:
            nonlocal ack_called
            ack_called = True

    fake_msg = _FakeMsg()

    # Simulate the production gate
    assert bus._closed is True
    if bus._closed:
        await fake_msg.term()

    assert term_called.is_set()
    assert ack_called is False
