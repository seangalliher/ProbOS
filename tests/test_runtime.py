"""Tests for the ProbOS runtime — integration tests for substrate + mesh."""

import asyncio

import pytest

from probos.runtime import ProbOSRuntime
from probos.types import AgentState


@pytest.fixture
async def runtime(tmp_path):
    """Create a runtime with temp data dir, start it, yield, stop."""
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    await rt.start()
    yield rt
    await rt.stop()


class TestRuntimeSubstrate:
    @pytest.mark.asyncio
    async def test_start_and_stop(self, tmp_path):
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        await rt.start()

        assert rt._started
        assert rt.registry.count > 0
        assert "system" in rt.pools
        assert "filesystem" in rt.pools

        await rt.stop()
        assert not rt._started
        assert rt.registry.count == 0

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, tmp_path):
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        await rt.start()
        count_after_first = rt.registry.count
        await rt.start()  # Should not double-spawn
        assert rt.registry.count == count_after_first
        await rt.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_agents_are_active(self, runtime):
        agents = runtime.registry.get_by_pool("system")
        assert len(agents) == 2
        for a in agents:
            assert a.state == AgentState.ACTIVE
            assert a.agent_type == "system_heartbeat"

    @pytest.mark.asyncio
    async def test_filesystem_pool_created(self, runtime):
        agents = runtime.registry.get_by_pool("filesystem")
        assert len(agents) == 3
        for a in agents:
            assert a.agent_type == "file_reader"
            assert a.state == AgentState.ACTIVE

    @pytest.mark.asyncio
    async def test_pool_recovery_after_degradation(self, runtime):
        agents = runtime.registry.get_by_pool("system")
        victim = agents[0]
        for _ in range(30):
            victim.update_confidence(False)
        assert victim.state == AgentState.DEGRADED

        pool = runtime.pools["system"]
        await pool.check_health()
        assert pool.current_size == 2


class TestRuntimeMesh:
    @pytest.mark.asyncio
    async def test_file_reader_agents_on_intent_bus(self, runtime):
        assert runtime.intent_bus.subscriber_count >= 3  # 3 file readers

    @pytest.mark.asyncio
    async def test_capabilities_registered(self, runtime):
        matches = runtime.capability_registry.query("read_file")
        assert len(matches) >= 3

    @pytest.mark.asyncio
    async def test_gossip_view_populated(self, runtime):
        # All agents should be in gossip view
        assert runtime.gossip.view_size >= 5  # 2 heartbeat + 3 file readers

    @pytest.mark.asyncio
    async def test_submit_intent_read_file(self, runtime, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello from probos")

        results = await runtime.submit_intent(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        # All 3 file_reader agents should respond
        assert len(results) == 3
        for r in results:
            assert r.success
            assert r.result == "hello from probos"

    @pytest.mark.asyncio
    async def test_submit_intent_missing_file(self, runtime, tmp_path):
        results = await runtime.submit_intent(
            "read_file",
            params={"path": str(tmp_path / "missing.txt")},
            timeout=5.0,
        )

        assert len(results) == 3
        for r in results:
            assert not r.success
            assert r.error is not None

    @pytest.mark.asyncio
    async def test_submit_intent_unknown_is_empty(self, runtime):
        """Intents nobody handles return empty results."""
        results = await runtime.submit_intent(
            "send_email",
            params={"to": "test@test.com"},
            timeout=2.0,
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_hebbian_weights_after_intent(self, runtime, tmp_path):
        test_file = tmp_path / "weights.txt"
        test_file.write_text("data")

        await runtime.submit_intent(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        assert runtime.hebbian_router.weight_count > 0

    @pytest.mark.asyncio
    async def test_status_includes_mesh(self, runtime):
        status = runtime.status()
        assert "mesh" in status
        assert status["mesh"]["intent_subscribers"] >= 3
        assert status["mesh"]["capability_agents"] >= 3
        assert status["mesh"]["gossip_view_size"] >= 5


class TestRuntimeEventLog:
    @pytest.mark.asyncio
    async def test_events_recorded_on_start(self, runtime):
        count = await runtime.event_log.count()
        assert count > 0

        system_events = await runtime.event_log.query(category="system")
        event_types = {e["event"] for e in system_events}
        assert "started" in event_types

    @pytest.mark.asyncio
    async def test_lifecycle_events_recorded(self, runtime):
        events = await runtime.event_log.query(category="lifecycle")
        assert len(events) > 0
        assert any(e["event"] == "agent_wired" for e in events)

    @pytest.mark.asyncio
    async def test_mesh_events_recorded(self, runtime, tmp_path):
        test_file = tmp_path / "log_test.txt"
        test_file.write_text("log test")

        await runtime.submit_intent(
            "read_file",
            params={"path": str(test_file)},
            timeout=5.0,
        )

        events = await runtime.event_log.query(category="mesh")
        event_types = {e["event"] for e in events}
        assert "intent_broadcast" in event_types
        assert "intent_resolved" in event_types
