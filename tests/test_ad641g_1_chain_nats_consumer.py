"""AD-641g-1: tests for ``ChainNATSConsumer``."""
from __future__ import annotations

import asyncio
import pytest

from probos.cognitive.chain_nats_consumer import ChainNATSConsumer
from probos.cognitive.chain_subjects import chain_subject
from probos.cognitive.sub_task import SubTaskType
from probos.config import SubTaskConfig
from probos.mesh.nats_bus import MockNATSBus


def _connected_bus() -> MockNATSBus:
    bus = MockNATSBus(subject_prefix="probos.test")
    bus._connected = True
    return bus


def _enabled_consumer() -> tuple[ChainNATSConsumer, MockNATSBus]:
    cfg = SubTaskConfig(nats_publish_enabled=True)
    bus = _connected_bus()
    return ChainNATSConsumer(nats_bus=bus, config=cfg), bus


def test_disabled_when_flag_false() -> None:
    cfg = SubTaskConfig(nats_publish_enabled=False)
    bus = _connected_bus()
    c = ChainNATSConsumer(nats_bus=bus, config=cfg)
    assert c.enabled is False


def test_disabled_when_nats_disconnected() -> None:
    cfg = SubTaskConfig(nats_publish_enabled=True)
    bus = MockNATSBus(subject_prefix="probos.test")
    # _connected stays False
    c = ChainNATSConsumer(nats_bus=bus, config=cfg)
    assert c.enabled is False


@pytest.mark.asyncio
async def test_register_and_start_subscribes_to_subject() -> None:
    consumer, bus = _enabled_consumer()
    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, phase="complete",
        handler=lambda payload: None,
    )
    await consumer.start()
    # MockNATSBus tracks subscriptions in _subs; subject prefixed.
    assert any(
        s.endswith("chain.alice.analyze.complete") for s in bus._subs.keys()
    )


@pytest.mark.asyncio
async def test_start_is_noop_when_disabled() -> None:
    cfg = SubTaskConfig(nats_publish_enabled=False)
    bus = MockNATSBus(subject_prefix="probos.test")
    consumer = ChainNATSConsumer(nats_bus=bus, config=cfg)
    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, handler=lambda p: None,
    )
    await consumer.start()
    assert bus._subs == {}


@pytest.mark.asyncio
async def test_inbound_message_dispatches_to_registered_handler() -> None:
    consumer, bus = _enabled_consumer()
    received: list[dict] = []

    async def h(payload):
        received.append(payload)

    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, phase="complete", handler=h,
    )
    await consumer.start()
    await bus.js_publish(
        chain_subject("alice", SubTaskType.ANALYZE, "complete"),
        {"agent_id": "alice", "step": "analyze", "phase": "complete", "ok": True},
    )
    await asyncio.gather(*list(consumer._dispatch_tasks), return_exceptions=True)
    assert len(received) == 1
    assert received[0]["agent_id"] == "alice"


@pytest.mark.asyncio
async def test_wildcard_agent_id_receives_all_agents() -> None:
    consumer, bus = _enabled_consumer()
    seen: list[str] = []

    async def h(payload):
        seen.append(payload["agent_id"])

    consumer.register_handler(
        agent_id="*", step=SubTaskType.ANALYZE, phase="complete", handler=h,
    )
    await consumer.start()
    await bus.js_publish(
        chain_subject("alice", SubTaskType.ANALYZE), {"agent_id": "alice", "step": "analyze", "phase": "complete"},
    )
    await bus.js_publish(
        chain_subject("bob", SubTaskType.ANALYZE), {"agent_id": "bob", "step": "analyze", "phase": "complete"},
    )
    await asyncio.gather(*list(consumer._dispatch_tasks), return_exceptions=True)
    assert sorted(seen) == ["alice", "bob"]


@pytest.mark.asyncio
async def test_handler_exception_does_not_propagate() -> None:
    consumer, bus = _enabled_consumer()

    def boom(_payload):
        raise RuntimeError("nope")

    async def works(_payload):
        works.calls += 1  # type: ignore[attr-defined]

    works.calls = 0  # type: ignore[attr-defined]
    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, phase="complete", handler=boom,
    )
    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, phase="complete", handler=works,
    )
    await consumer.start()
    await bus.js_publish(
        chain_subject("alice", SubTaskType.ANALYZE),
        {"agent_id": "alice", "step": "analyze", "phase": "complete"},
    )
    await asyncio.gather(*list(consumer._dispatch_tasks), return_exceptions=True)
    assert works.calls == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_phase_filter_excludes_other_phases() -> None:
    consumer, bus = _enabled_consumer()
    received: list[str] = []

    async def h(payload):
        received.append(payload.get("phase", ""))

    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, phase="error", handler=h,
    )
    await consumer.start()
    # Publish a "complete" — should NOT dispatch since handler only wants error.
    await bus.js_publish(
        chain_subject("alice", SubTaskType.ANALYZE, "complete"),
        {"agent_id": "alice", "step": "analyze", "phase": "complete"},
    )
    await asyncio.gather(*list(consumer._dispatch_tasks), return_exceptions=True)
    assert received == []


@pytest.mark.asyncio
async def test_start_idempotent() -> None:
    consumer, bus = _enabled_consumer()
    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, handler=lambda p: None,
    )
    await consumer.start()
    sub_count_after_first = sum(len(v) for v in bus._subs.values())
    await consumer.start()
    sub_count_after_second = sum(len(v) for v in bus._subs.values())
    assert sub_count_after_first == sub_count_after_second


@pytest.mark.asyncio
async def test_stop_drains_in_flight_tasks() -> None:
    consumer, bus = _enabled_consumer()

    started = asyncio.Event()
    finish = asyncio.Event()

    async def slow(_payload):
        started.set()
        await finish.wait()

    consumer.register_handler(
        agent_id="alice", step=SubTaskType.ANALYZE, handler=slow,
    )
    await consumer.start()
    await bus.js_publish(
        chain_subject("alice", SubTaskType.ANALYZE),
        {"agent_id": "alice", "step": "analyze", "phase": "complete"},
    )
    await started.wait()
    finish.set()
    await consumer.stop()
    assert consumer._dispatch_tasks == set() or all(t.done() for t in consumer._dispatch_tasks)
