"""AD-672: Tests for Agent Concurrency Management."""

from __future__ import annotations

import asyncio
import logging

import pytest

from probos.cognitive.cognitive_agent import _classify_concurrency_priority
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.config import ConcurrencyConfig
from probos.events import EventType
from probos.types import IntentMessage


class _FakeEventCollector:
    """Collect emitted events for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict]] = []

    def __call__(self, event_type: EventType, data: dict) -> None:
        self.events.append((event_type, data))


@pytest.fixture
def manager() -> ConcurrencyManager:
    return ConcurrencyManager(
        agent_id="test-agent",
        max_concurrent=2,
        queue_max_size=3,
        capacity_warning_ratio=0.5,
    )


@pytest.fixture
def manager_with_events() -> tuple[ConcurrencyManager, _FakeEventCollector]:
    collector = _FakeEventCollector()
    managed = ConcurrencyManager(
        agent_id="test-agent",
        max_concurrent=2,
        queue_max_size=3,
        capacity_warning_ratio=0.5,
        emit_event_fn=collector,
    )
    return managed, collector


@pytest.mark.asyncio
async def test_acquire_returns_thread_id(manager: ConcurrencyManager) -> None:
    thread_id = await manager.acquire("test_intent")

    assert thread_id
    assert isinstance(thread_id, str)

    await manager.release(thread_id)


@pytest.mark.asyncio
async def test_acquire_within_ceiling(manager: ConcurrencyManager) -> None:
    first_thread = await manager.acquire("test_intent")
    second_thread = await manager.acquire("test_intent")

    assert manager.active_count == 2
    assert manager.at_capacity is True

    await manager.release(first_thread)
    await manager.release(second_thread)


@pytest.mark.asyncio
async def test_release_frees_slot(manager: ConcurrencyManager) -> None:
    first_thread = await manager.acquire("test_intent")
    second_thread = await manager.acquire("test_intent")

    await manager.release(first_thread)
    third_thread = await manager.acquire("test_intent")

    assert manager.active_count == 2

    await manager.release(second_thread)
    await manager.release(third_thread)


@pytest.mark.asyncio
async def test_queue_when_at_capacity() -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=2)
    active_thread = await managed.acquire("active")
    queued_task = asyncio.create_task(managed.acquire("queued"))
    await asyncio.sleep(0)

    assert managed.queue_depth == 1
    assert queued_task.done() is False

    await managed.release(active_thread)
    queued_thread = await queued_task

    assert queued_thread
    assert managed.active_count == 1

    await managed.release(queued_thread)


@pytest.mark.asyncio
async def test_queue_priority_ordering() -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=3)
    active_thread = await managed.acquire("active")
    low_priority_task = asyncio.create_task(managed.acquire("low", priority=1))
    high_priority_task = asyncio.create_task(managed.acquire("high", priority=9))
    await asyncio.sleep(0)

    await managed.release(active_thread)
    high_priority_thread = await high_priority_task

    assert high_priority_thread
    assert low_priority_task.done() is False

    await managed.release(high_priority_thread)
    low_priority_thread = await low_priority_task
    await managed.release(low_priority_thread)


@pytest.mark.asyncio
async def test_queue_fifo_within_same_priority() -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=3)
    active_thread = await managed.acquire("active")
    first_task = asyncio.create_task(managed.acquire("first", priority=5))
    await asyncio.sleep(0)
    second_task = asyncio.create_task(managed.acquire("second", priority=5))
    await asyncio.sleep(0)

    await managed.release(active_thread)
    first_thread = await first_task

    assert second_task.done() is False

    await managed.release(first_thread)
    second_thread = await second_task
    await managed.release(second_thread)


@pytest.mark.asyncio
async def test_queue_full_raises_valueerror() -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=1)
    active_thread = await managed.acquire("active")
    queued_task = asyncio.create_task(managed.acquire("queued"))
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="queue full"):
        await managed.acquire("overflow")

    await managed.release(active_thread)
    queued_thread = await queued_task
    await managed.release(queued_thread)


@pytest.mark.asyncio
async def test_capacity_warning_event_emitted(
    manager_with_events: tuple[ConcurrencyManager, _FakeEventCollector],
) -> None:
    managed, collector = manager_with_events
    first_thread = await managed.acquire("first")
    second_thread = await managed.acquire("second")

    assert collector.events == [(
        EventType.AGENT_CAPACITY_APPROACHING,
        {
            "agent_id": "test-agent",
            "active_count": 1,
            "max_concurrent": 2,
            "queue_depth": 0,
        },
    )]

    await managed.release(first_thread)
    await managed.release(second_thread)


@pytest.mark.asyncio
async def test_capacity_warning_not_emitted_below_threshold() -> None:
    collector = _FakeEventCollector()
    managed = ConcurrencyManager(
        "test-agent",
        max_concurrent=2,
        capacity_warning_ratio=1.0,
        emit_event_fn=collector,
    )

    thread_id = await managed.acquire("first")

    assert collector.events == []

    await managed.release(thread_id)


@pytest.mark.asyncio
async def test_arbitrate_returns_lower_priority_thread() -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=2)
    low_thread = await managed.acquire("low", priority=1, resource_key="thread-a")
    high_thread = await managed.acquire("high", priority=9, resource_key="thread-a")

    yielding_thread = await managed.arbitrate("thread-a")

    assert yielding_thread == low_thread

    await managed.release(low_thread)
    await managed.release(high_thread)


@pytest.mark.asyncio
async def test_arbitrate_no_conflict() -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=2)
    thread_id = await managed.acquire("solo", priority=5, resource_key="thread-a")

    yielding_thread = await managed.arbitrate("thread-a")

    assert yielding_thread is None

    await managed.release(thread_id)


@pytest.mark.asyncio
async def test_slot_context_manager(manager: ConcurrencyManager) -> None:
    async with manager.slot("test_intent") as thread_id:
        assert thread_id
        assert manager.active_count == 1

    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_slot_releases_on_exception(manager: ConcurrencyManager) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with manager.slot("test_intent"):
            raise RuntimeError("boom")

    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_snapshot_diagnostic(manager: ConcurrencyManager) -> None:
    thread_id = await manager.acquire("test_intent", priority=7)

    snapshot = manager.snapshot()

    assert snapshot["agent_id"] == "test-agent"
    assert snapshot["max_concurrent"] == 2
    assert snapshot["active_count"] == 1
    assert snapshot["queue_depth"] == 0
    assert snapshot["active_threads"][0]["thread_id"] == thread_id
    assert snapshot["active_threads"][0]["intent_type"] == "test_intent"
    assert snapshot["active_threads"][0]["priority"] == 7

    await manager.release(thread_id)


@pytest.mark.asyncio
async def test_properties(manager: ConcurrencyManager) -> None:
    assert manager.active_count == 0
    assert manager.queue_depth == 0
    assert manager.max_concurrent == 2
    assert manager.at_capacity is False

    first_thread = await manager.acquire("first")
    second_thread = await manager.acquire("second")

    assert manager.active_count == 2
    assert manager.at_capacity is True

    await manager.release(first_thread)
    await manager.release(second_thread)


@pytest.mark.asyncio
async def test_release_unknown_thread_id(caplog: pytest.LogCaptureFixture) -> None:
    managed = ConcurrencyManager("test-agent", max_concurrent=1)

    with caplog.at_level(logging.WARNING):
        await managed.release("missing-thread")

    assert "unknown thread_id" in caplog.text
    assert managed.active_count == 0


def test_classify_concurrency_priority() -> None:
    assert _classify_concurrency_priority(
        IntentMessage("ward_room_notification", params={"is_captain": True})
    ) == 10
    assert _classify_concurrency_priority(
        IntentMessage("ward_room_notification", params={"was_mentioned": True})
    ) == 10
    assert _classify_concurrency_priority(IntentMessage("direct_message")) == 8
    assert _classify_concurrency_priority(IntentMessage("ward_room_notification")) == 5
    assert _classify_concurrency_priority(IntentMessage("proactive_think")) == 2
    assert _classify_concurrency_priority(IntentMessage("unknown")) == 5


def test_config_defaults() -> None:
    config = ConcurrencyConfig()

    assert config.enabled is True
    assert config.default_max_concurrent == 4
    assert config.queue_max_size == 10
    assert config.capacity_warning_ratio == 0.75
    assert config.role_overrides["bridge"] == 3
    assert config.role_overrides["operations"] == 6
