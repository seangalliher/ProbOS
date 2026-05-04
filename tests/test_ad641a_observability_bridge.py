"""AD-641a: Observability Bridge tests."""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.observability import (
    ObservabilityBridge,
    ObservabilityBridgeSnapshot,
)
from probos.config import ObservabilityBridgeConfig
from probos.events import EventType
from probos.ward_room.service import WardRoomService


def _make_runtime(
    *,
    event_log: object | None = None,
    spawner: object | None = None,
    attention: object | None = None,
) -> object:
    rt = MagicMock(spec=[])  # bare object with no attrs
    if event_log is not None:
        rt.event_log = event_log
    if spawner is not None:
        rt.spawner = spawner
    if attention is not None:
        rt.attention = attention
    return rt


def test_event_type_observability_snapshot_published_exists():
    assert EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED.value == "observability_snapshot_published"


def test_event_type_observability_bridge_failed_exists():
    assert EventType.OBSERVABILITY_BRIDGE_FAILED.value == "observability_bridge_failed"


def test_observability_bridge_config_defaults():
    cfg = ObservabilityBridgeConfig()
    assert cfg.enabled is True
    assert cfg.publish_interval_seconds == 60.0
    assert cfg.system_channel == "system_observability"


def test_snapshot_is_frozen_dataclass():
    snap = ObservabilityBridgeSnapshot(captured_at=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.captured_at = 2.0  # type: ignore[misc]
    new = dataclasses.replace(snap, captured_at=3.0)
    assert new.captured_at == 3.0
    assert snap.captured_at == 1.0


@pytest.mark.asyncio
async def test_take_snapshot_with_no_runtime_state_returns_empty_collections():
    runtime = MagicMock(spec=[])
    bridge = ObservabilityBridge(
        runtime=runtime, ward_room=None, emit_event=None,
    )
    snap = await bridge.take_snapshot()
    assert snap.vitals_summary == {}
    assert snap.pool_health == {}
    assert snap.attention_priorities == []
    assert snap.captured_at > 0


@pytest.mark.asyncio
async def test_collect_vitals_picks_latest_vitals_monitor_state():
    event_log = AsyncMock()
    event_log.query_structured = AsyncMock(return_value=[
        {"agent_type": "other_agent", "data": {"foo": "bar"}},
        {"agent_type": "vitals_monitor", "data": {"cpu": 55.0, "load": 0.7}},
        {"agent_type": "vitals_monitor", "data": {"cpu": 99.0}},
    ])
    runtime = _make_runtime(event_log=event_log)
    bridge = ObservabilityBridge(runtime=runtime, ward_room=None)
    snap = await bridge.take_snapshot()
    # First matching row wins (most recent due to DESC ordering).
    assert snap.vitals_summary == {"cpu": 55.0, "load": 0.7}
    event_log.query_structured.assert_awaited_once_with(
        event=EventType.AGENT_STATE.value, limit=20,
    )


@pytest.mark.asyncio
async def test_collect_pool_health_reads_current_and_target_size():
    pool_a = MagicMock(current_size=3, target_size=5)
    pool_b = MagicMock(current_size=1, target_size=2)
    spawner = MagicMock()
    spawner.pools = {"alpha": pool_a, "beta": pool_b}
    runtime = _make_runtime(spawner=spawner)
    bridge = ObservabilityBridge(runtime=runtime, ward_room=None)
    snap = await bridge.take_snapshot()
    assert snap.pool_health == {
        "alpha": {"current_size": 3, "target_size": 5},
        "beta": {"current_size": 1, "target_size": 2},
    }


@pytest.mark.asyncio
async def test_collect_attention_returns_top_5_by_score_desc():
    attn = MagicMock()
    attn._queue = {
        f"task-{i}": MagicMock(score=float(i)) for i in range(7)
    }
    runtime = _make_runtime(attention=attn)
    bridge = ObservabilityBridge(runtime=runtime, ward_room=None)
    snap = await bridge.take_snapshot()
    assert len(snap.attention_priorities) == 5
    scores = [item["score"] for item in snap.attention_priorities]
    assert scores == [6.0, 5.0, 4.0, 3.0, 2.0]


@pytest.mark.asyncio
async def test_publish_once_does_not_post_to_ward_room():
    """BF-258: Ward Room posting disabled — telemetry is not discourse."""
    ward_room = AsyncMock(spec=WardRoomService)
    runtime = _make_runtime()
    bridge = ObservabilityBridge(
        runtime=runtime, ward_room=ward_room,
        system_channel="sys_obs_test",
    )
    await bridge._publish_once()
    ward_room.create_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_once_emits_observability_snapshot_published():
    ward_room = AsyncMock(spec=WardRoomService)
    pool = MagicMock(current_size=2, target_size=2)
    spawner = MagicMock()
    spawner.pools = {"core": pool}
    runtime = _make_runtime(spawner=spawner)
    emitted: list[tuple[EventType, dict]] = []
    bridge = ObservabilityBridge(
        runtime=runtime,
        ward_room=ward_room,
        emit_event=lambda et, payload: emitted.append((et, payload)),
    )
    await bridge._publish_once()
    assert len(emitted) == 1
    et, payload = emitted[0]
    assert et == EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED
    assert "captured_at" in payload
    assert payload["pools"] == ["core"]
    assert payload["attention_count"] == 0


@pytest.mark.asyncio
async def test_publish_once_no_failure_event_without_ward_room_posting():
    """BF-258: With Ward Room posting removed, no BRIDGE_FAILED events emitted."""
    ward_room = AsyncMock(spec=WardRoomService)
    runtime = _make_runtime()
    emitted: list[tuple[EventType, dict]] = []
    bridge = ObservabilityBridge(
        runtime=runtime,
        ward_room=ward_room,
        emit_event=lambda et, payload: emitted.append((et, payload)),
    )
    await bridge._publish_once()
    assert not any(et == EventType.OBSERVABILITY_BRIDGE_FAILED for et, _ in emitted)


@pytest.mark.asyncio
async def test_start_creates_named_task():
    runtime = _make_runtime()
    bridge = ObservabilityBridge(
        runtime=runtime, ward_room=None, publish_interval_seconds=10.0,
    )
    try:
        await bridge.start()
        assert bridge._task is not None
        assert bridge._task.get_name() == "observability_bridge"
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task_cleanly():
    runtime = _make_runtime()
    bridge = ObservabilityBridge(
        runtime=runtime, ward_room=None, publish_interval_seconds=10.0,
    )
    await bridge.start()
    task = bridge._task
    assert task is not None
    await bridge.stop()
    assert bridge._task is None
    assert task.cancelled() or task.done()


def test_publish_interval_minimum_enforced():
    runtime = _make_runtime()
    bridge = ObservabilityBridge(
        runtime=runtime, ward_room=None, publish_interval_seconds=0.0,
    )
    assert bridge._interval == 1.0
    bridge2 = ObservabilityBridge(
        runtime=runtime, ward_room=None, publish_interval_seconds=-5.0,
    )
    assert bridge2._interval == 1.0
