"""Tests for HXI event emission (AD-261, Phase 23).

Validates the enriched WebSocket event stream:
- state_snapshot on connect
- trust_update, hebbian_update, system_mode, consensus, agent_state events
- Event listener lifecycle (register, remove, error isolation)
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime


@pytest.fixture
def runtime(tmp_path):
    """Create a minimal runtime for event testing."""
    cfg = SystemConfig()
    rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
    return rt


class TestEventListenerLifecycle:
    """Tests for add_event_listener / remove_event_listener / _emit_event."""

    def test_add_event_listener(self, runtime):
        """Event listener is registered."""
        fn = MagicMock()
        runtime.add_event_listener(fn)
        assert fn in runtime._event_listeners

    def test_remove_event_listener(self, runtime):
        """Event listener can be removed."""
        fn = MagicMock()
        runtime.add_event_listener(fn)
        runtime.remove_event_listener(fn)
        assert fn not in runtime._event_listeners

    def test_remove_nonexistent_listener(self, runtime):
        """Removing a non-registered listener doesn't crash."""
        fn = MagicMock()
        runtime.remove_event_listener(fn)  # Should not raise

    def test_emit_event_calls_listeners(self, runtime):
        """_emit_event delivers to all registered listeners."""
        fn1 = MagicMock()
        fn2 = MagicMock()
        runtime.add_event_listener(fn1)
        runtime.add_event_listener(fn2)

        runtime._emit_event("test_type", {"key": "value"})

        assert fn1.call_count == 1
        assert fn2.call_count == 1
        event = fn1.call_args[0][0]
        assert event["type"] == "test_type"
        assert event["data"] == {"key": "value"}
        assert "timestamp" in event

    def test_emit_no_listeners(self, runtime):
        """Emitting with no listeners doesn't crash."""
        runtime._emit_event("orphan_event", {"x": 1})  # Should not raise

    def test_failing_listener_doesnt_crash_others(self, runtime):
        """A failing listener doesn't prevent other listeners from firing."""
        failing = MagicMock(side_effect=RuntimeError("boom"))
        healthy = MagicMock()
        runtime.add_event_listener(failing)
        runtime.add_event_listener(healthy)

        runtime._emit_event("test", {})

        assert failing.call_count == 1
        assert healthy.call_count == 1  # Still called despite previous listener failure

    def test_event_timestamps_increasing(self, runtime):
        """Event timestamps are monotonically increasing."""
        events = []
        runtime.add_event_listener(events.append)

        runtime._emit_event("a", {})
        runtime._emit_event("b", {})

        assert len(events) == 2
        assert events[1]["timestamp"] >= events[0]["timestamp"]


class TestStateSnapshot:
    """Tests for build_state_snapshot."""

    @pytest.mark.asyncio
    async def test_state_snapshot_structure(self, tmp_path):
        """state_snapshot contains agents, connections, pools, system_mode."""
        cfg = SystemConfig()
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            snapshot = rt.build_state_snapshot()
            assert "agents" in snapshot
            assert "connections" in snapshot
            assert "pools" in snapshot
            assert "system_mode" in snapshot
            assert "tc_n" in snapshot
            assert "routing_entropy" in snapshot
            assert isinstance(snapshot["agents"], list)
            assert isinstance(snapshot["connections"], list)
            assert isinstance(snapshot["pools"], list)
            assert snapshot["system_mode"] in ("active", "idle", "dreaming")
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_state_snapshot_json_serializable(self, tmp_path):
        """state_snapshot is JSON-serializable."""
        import json

        cfg = SystemConfig()
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            snapshot = rt.build_state_snapshot()
            # Should not raise
            json_str = json.dumps(snapshot)
            assert len(json_str) > 10
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_state_snapshot_has_agents(self, tmp_path):
        """state_snapshot includes agents with expected fields."""
        cfg = SystemConfig()
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            snapshot = rt.build_state_snapshot()
            assert len(snapshot["agents"]) > 0
            agent = snapshot["agents"][0]
            assert "id" in agent
            assert "agent_type" in agent
            assert "pool" in agent
            assert "state" in agent
            assert "confidence" in agent
            assert "trust" in agent
            assert "tier" in agent
        finally:
            await rt.stop()


class TestEventEmission:
    """Tests for event emission at instrumentation points."""

    @pytest.mark.asyncio
    async def test_agent_state_emitted_on_wire(self, tmp_path):
        """agent_state events are emitted when agents are wired."""
        cfg = SystemConfig()
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)

        events = []
        rt.add_event_listener(events.append)

        await rt.start()
        try:
            agent_events = [e for e in events if e["type"] == "agent_state"]
            assert len(agent_events) > 0
            ev = agent_events[0]
            assert "agent_id" in ev["data"]
            assert "pool" in ev["data"]
            assert "state" in ev["data"]
            assert "confidence" in ev["data"]
            assert "trust" in ev["data"]
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_system_mode_event_on_dream(self, tmp_path):
        """system_mode event is emitted when dreaming starts."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        cfg = SystemConfig()
        rt = ProbOSRuntime(
            config=cfg, data_dir=tmp_path,
            episodic_memory=MockEpisodicMemory(),
        )

        events = []
        rt.add_event_listener(events.append)

        await rt.start()
        try:
            # Force a dream — should emit system_mode "dreaming" then "idle"
            if rt.dream_scheduler:
                report = await rt.dream_scheduler.force_dream()
                mode_events = [e for e in events if e["type"] == "system_mode"]
                assert len(mode_events) >= 2
                assert mode_events[0]["data"]["mode"] == "dreaming"
                assert mode_events[1]["data"]["mode"] == "idle"
        finally:
            await rt.stop()
