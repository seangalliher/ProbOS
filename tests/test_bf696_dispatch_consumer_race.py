"""BF-696: ``create_dispatch_consumers`` crashed the boot on a concurrent subscribe.

``IntentBus.create_dispatch_consumers`` iterated ``self._subscribers.items()``
while awaiting ``_js_subscribe_agent_dispatch`` inside the loop. Every await
yields to the event loop, so a concurrent ``subscribe()`` mutated the dict
mid-iteration and raised ``RuntimeError: dictionary changed size during
iteration``. That propagates out of ``finalize_startup`` and takes the entire
boot down -- observed live at ``finalize.py:4507``.

The live producer of the concurrent subscribe is the JetStream retry loop
(``perception.vision_aggregator`` re-subscribing on timeout), which is why the
crash presented intermittently rather than on every boot.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager


class _FakeNats:
    """Connected-looking bus so ``create_dispatch_consumers`` proceeds."""

    connected = True


def _make_bus() -> IntentBus:
    bus = IntentBus(SignalManager(reap_interval=1.0))
    bus._nats_bus = _FakeNats()  # type: ignore[assignment]
    return bus


async def _noop_handler(intent: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_a_concurrent_subscribe_during_the_drain_does_not_crash() -> None:
    """The headline regression. Fails with RuntimeError before the fix."""
    bus = _make_bus()
    for i in range(4):
        bus._subscribers[f"agent-{i}"] = _noop_handler

    seen: list[str] = []

    async def _slow_subscribe(agent_id: str, handler: Any) -> None:
        seen.append(agent_id)
        # The yield point that lets a concurrent subscriber in.
        await asyncio.sleep(0)
        if agent_id == "agent-1":
            # Exactly what the JetStream retry loop does mid-drain.
            bus._subscribers["agent-late"] = _noop_handler

    bus._js_subscribe_agent_dispatch = _slow_subscribe  # type: ignore[assignment]

    await bus.create_dispatch_consumers()

    # Every agent present at snapshot time was served...
    assert set(seen) == {"agent-0", "agent-1", "agent-2", "agent-3"}
    # ...and the late arrival is NOT double-created here; it gets its consumer
    # through the normal subscribe() path, since the defer flag is already off.
    assert "agent-late" not in seen
    assert bus._defer_dispatch_consumers is False


@pytest.mark.asyncio
async def test_a_concurrent_unsubscribe_during_the_drain_does_not_crash() -> None:
    """Removal mutates the dict just as insertion does."""
    bus = _make_bus()
    for i in range(4):
        bus._subscribers[f"agent-{i}"] = _noop_handler

    async def _slow_subscribe(agent_id: str, handler: Any) -> None:
        await asyncio.sleep(0)
        if agent_id == "agent-0":
            bus._subscribers.pop("agent-3", None)

    bus._js_subscribe_agent_dispatch = _slow_subscribe  # type: ignore[assignment]
    await bus.create_dispatch_consumers()  # must not raise


@pytest.mark.asyncio
async def test_the_defer_flag_clears_before_any_await() -> None:
    """Load-bearing for snapshot COMPLETENESS: an agent subscribing during the
    drain must self-create, which only holds if the flag is already off."""
    bus = _make_bus()
    bus._subscribers["agent-0"] = _noop_handler
    observed: list[bool] = []

    async def _record(agent_id: str, handler: Any) -> None:
        observed.append(bus._defer_dispatch_consumers)
        await asyncio.sleep(0)

    bus._js_subscribe_agent_dispatch = _record  # type: ignore[assignment]
    await bus.create_dispatch_consumers()
    assert observed == [False]


@pytest.mark.asyncio
async def test_a_failing_consumer_does_not_abort_the_remaining_agents() -> None:
    """Pre-existing per-agent honest-degrade must survive the fix."""
    bus = _make_bus()
    for i in range(3):
        bus._subscribers[f"agent-{i}"] = _noop_handler
    served: list[str] = []

    async def _flaky(agent_id: str, handler: Any) -> None:
        if agent_id == "agent-1":
            raise RuntimeError("nats: timeout")
        served.append(agent_id)

    bus._js_subscribe_agent_dispatch = _flaky  # type: ignore[assignment]
    await bus.create_dispatch_consumers()
    assert served == ["agent-0", "agent-2"]


@pytest.mark.asyncio
async def test_no_subscribers_is_a_clean_no_op() -> None:
    bus = _make_bus()
    await bus.create_dispatch_consumers()
    assert bus._defer_dispatch_consumers is False


@pytest.mark.asyncio
async def test_a_disconnected_bus_skips_without_clearing_nothing() -> None:
    """Disconnected returns early -- but the flag must still have been cleared,
    or agents created later would silently never get dispatch consumers."""
    bus = IntentBus(SignalManager(reap_interval=1.0))
    bus._nats_bus = None
    await bus.create_dispatch_consumers()
    assert bus._defer_dispatch_consumers is False
