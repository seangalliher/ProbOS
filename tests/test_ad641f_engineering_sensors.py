"""AD-641f: Engineering Sensor Service tests."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.engineering_sensors import (
    EngineeringSensorBundle,
    EngineeringSensorService,
)
from probos.config import EngineeringSensorsConfig
from probos.events import EventType


def test_event_type_engineering_sensor_report_exists():
    assert EventType.ENGINEERING_SENSOR_REPORT.value == "engineering_sensor_report"


def test_engineering_sensors_config_defaults():
    cfg = EngineeringSensorsConfig()
    assert cfg.enabled is True
    assert cfg.report_interval_seconds == 60.0
    assert cfg.auto_start_periodic_report is False


def test_bundle_is_frozen_dataclass():
    bundle = EngineeringSensorBundle(captured_at=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.captured_at = 2.0  # type: ignore[misc]
    new = dataclasses.replace(bundle, captured_at=3.0)
    assert new.captured_at == 3.0


def test_take_snapshot_with_no_runtime_state_returns_empty_dicts():
    runtime = SimpleNamespace()
    service = EngineeringSensorService(runtime=runtime)
    snap = service.take_snapshot()
    assert snap.pool_summary == {}
    assert snap.capability_summary == {"agent_count": 0, "intents": []}
    assert snap.gossip_summary == {"view_size": 0, "peer_count": 0}
    assert snap.captured_at > 0


def test_collect_pools_reads_current_and_target_size():
    pool_a = SimpleNamespace(current_size=4, target_size=4)
    pool_b = SimpleNamespace(current_size=2, target_size=3)
    spawner = SimpleNamespace(pools={"alpha": pool_a, "beta": pool_b})
    runtime = SimpleNamespace(spawner=spawner)
    service = EngineeringSensorService(runtime=runtime)
    snap = service.take_snapshot()
    assert snap.pool_summary == {
        "alpha": {"current_size": 4, "target_size": 4},
        "beta": {"current_size": 2, "target_size": 3},
    }


def test_collect_capabilities_returns_agent_count_and_sorted_intents():
    cap_a = SimpleNamespace(can="run_command")
    cap_b = SimpleNamespace(can="read_file")
    cap_c = SimpleNamespace(can="run_command")  # duplicate -- dedup
    registry = MagicMock()
    registry.agent_count = 2
    registry.get_all_capabilities.return_value = {
        "agent-1": [cap_a, cap_b],
        "agent-2": [cap_c],
    }
    runtime = SimpleNamespace(capability_registry=registry)
    service = EngineeringSensorService(runtime=runtime)
    snap = service.take_snapshot()
    assert snap.capability_summary["agent_count"] == 2
    assert snap.capability_summary["intents"] == ["read_file", "run_command"]


def test_collect_gossip_returns_view_size_and_peer_count():
    gossip = MagicMock()
    gossip.view_size = 3
    gossip.get_view.return_value = {"a": object(), "b": object(), "c": object()}
    runtime = SimpleNamespace(gossip=gossip)
    service = EngineeringSensorService(runtime=runtime)
    snap = service.take_snapshot()
    assert snap.gossip_summary == {"view_size": 3, "peer_count": 3}


def test_report_emits_engineering_sensor_report():
    pool_a = SimpleNamespace(current_size=2, target_size=2)
    spawner = SimpleNamespace(pools={"alpha": pool_a})
    registry = MagicMock()
    registry.agent_count = 5
    registry.get_all_capabilities.return_value = {}
    gossip = MagicMock()
    gossip.view_size = 7
    gossip.get_view.return_value = {}
    runtime = SimpleNamespace(spawner=spawner, capability_registry=registry, gossip=gossip)
    emitted: list[tuple[EventType, dict]] = []
    service = EngineeringSensorService(
        runtime=runtime,
        emit_event=lambda et, payload: emitted.append((et, payload)),
    )
    service.report()
    assert len(emitted) == 1
    et, payload = emitted[0]
    assert et == EventType.ENGINEERING_SENSOR_REPORT
    assert payload["pools"] == ["alpha"]
    assert payload["capability_agents"] == 5
    assert payload["gossip_view_size"] == 7
    assert "captured_at" in payload


def test_report_no_emit_when_emit_event_none():
    runtime = SimpleNamespace()
    service = EngineeringSensorService(runtime=runtime, emit_event=None)
    # Should be a no-op; no exception.
    service.report()


@pytest.mark.asyncio
async def test_start_creates_named_task():
    runtime = SimpleNamespace()
    service = EngineeringSensorService(
        runtime=runtime, report_interval_seconds=10.0,
    )
    try:
        await service.start()
        assert service._task is not None
        assert service._task.get_name() == "engineering_sensor_report"
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task_and_resets_to_none():
    runtime = SimpleNamespace()
    service = EngineeringSensorService(
        runtime=runtime, report_interval_seconds=10.0,
    )
    await service.start()
    task = service._task
    assert task is not None
    await service.stop()
    assert service._task is None
    assert task.cancelled() or task.done()


def test_report_interval_minimum_enforced():
    runtime = SimpleNamespace()
    service_zero = EngineeringSensorService(runtime=runtime, report_interval_seconds=0.0)
    assert service_zero._interval == 1.0
    service_neg = EngineeringSensorService(runtime=runtime, report_interval_seconds=-5.0)
    assert service_neg._interval == 1.0


def test_report_swallows_emit_exceptions():
    runtime = SimpleNamespace()

    def bad_emit(et, payload):
        raise RuntimeError("emit failed")

    service = EngineeringSensorService(runtime=runtime, emit_event=bad_emit)
    # Must not raise.
    service.report()
