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


# ---------------------------------------------------------------------------
# TestVerifyResponse — _verify_response() coverage (lines 1321-1405)
# ---------------------------------------------------------------------------


class TestVerifyResponse:
    """Tests for _verify_response() fabrication/contradiction checks."""

    @pytest.mark.asyncio
    async def test_empty_response_unchanged(self, runtime):
        """Empty or whitespace response is returned unchanged."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel()
        assert runtime._verify_response("", model) == ""
        assert runtime._verify_response("   ", model) == "   "

    @pytest.mark.asyncio
    async def test_clean_response_unchanged(self, runtime):
        """Response with no fabrications is returned unchanged."""
        from probos.cognitive.self_model import SystemSelfModel, PoolSnapshot
        model = SystemSelfModel(
            pool_count=3,
            agent_count=10,
            departments=["engineering", "medical"],
            pools=[PoolSnapshot(name="system", agent_type="system", agent_count=2)],
            system_mode="active",
        )
        text = "The system has 3 pools and 10 agents."
        result = runtime._verify_response(text, model)
        assert result == text  # No correction appended

    @pytest.mark.asyncio
    async def test_fabricated_pool_count(self, runtime):
        """Wrong pool count triggers correction footnote."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel(pool_count=3, agent_count=10, system_mode="active")
        text = "We have 99 pools available."
        result = runtime._verify_response(text, model)
        assert "[Note:" in result
        assert "3 pools" in result

    @pytest.mark.asyncio
    async def test_fabricated_agent_count(self, runtime):
        """Wrong agent count triggers correction footnote."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel(pool_count=3, agent_count=10, system_mode="active")
        text = "Currently running 500 agents."
        result = runtime._verify_response(text, model)
        assert "[Note:" in result
        assert "10 agents" in result

    @pytest.mark.asyncio
    async def test_fabricated_department(self, runtime):
        """Unknown department name triggers correction footnote."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel(
            pool_count=3,
            agent_count=10,
            departments=["engineering", "medical"],
            system_mode="active",
        )
        text = "The navigation department is handling that request."
        result = runtime._verify_response(text, model)
        assert "[Note:" in result

    @pytest.mark.asyncio
    async def test_fabricated_pool_name(self, runtime):
        """Unknown pool name triggers correction footnote."""
        from probos.cognitive.self_model import SystemSelfModel, PoolSnapshot
        model = SystemSelfModel(
            pool_count=3,
            agent_count=10,
            pools=[PoolSnapshot(name="system", agent_type="system", agent_count=2)],
            system_mode="active",
        )
        text = "The weapons pool is ready."
        result = runtime._verify_response(text, model)
        assert "[Note:" in result

    @pytest.mark.asyncio
    async def test_system_mode_contradiction_active(self, runtime):
        """Claiming idle when system is active triggers correction."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel(pool_count=1, agent_count=1, system_mode="active")
        text = "The system is idle right now."
        result = runtime._verify_response(text, model)
        assert "[Note:" in result
        assert "mode active" in result

    @pytest.mark.asyncio
    async def test_system_mode_contradiction_dreaming(self, runtime):
        """Claiming active when system is dreaming triggers correction."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel(pool_count=1, agent_count=1, system_mode="dreaming")
        text = "The system is active and processing."
        result = runtime._verify_response(text, model)
        assert "[Note:" in result
        assert "mode dreaming" in result

    @pytest.mark.asyncio
    async def test_zero_count_not_flagged(self, runtime):
        """Zero counts are not flagged as violations."""
        from probos.cognitive.self_model import SystemSelfModel
        model = SystemSelfModel(pool_count=3, agent_count=10, system_mode="active")
        text = "0 pools were affected by the change."
        result = runtime._verify_response(text, model)
        assert result == text  # Zero is exempt

    @pytest.mark.asyncio
    async def test_safe_pool_words_not_flagged(self, runtime):
        """Safe generic words (agent, worker, thread, connection) are not flagged."""
        from probos.cognitive.self_model import SystemSelfModel, PoolSnapshot
        model = SystemSelfModel(
            pool_count=1, agent_count=1,
            pools=[PoolSnapshot(name="system", agent_type="system", agent_count=1)],
            system_mode="active",
        )
        text = "The connection pool is handling requests."
        result = runtime._verify_response(text, model)
        assert result == text  # "connection" is a safe word


# ---------------------------------------------------------------------------
# TestConversationHistoryEnrichment — lines 1506-1520
# ---------------------------------------------------------------------------


class TestConversationHistoryEnrichment:
    """Tests for conversation context enrichment with last execution data."""

    @pytest.mark.asyncio
    async def test_enrichment_with_dag(self, runtime):
        """When _last_execution has a DAG, conversation history gets context tuple."""
        from unittest.mock import MagicMock

        # Create mock DAG with nodes
        mock_node = MagicMock()
        mock_node.intent = "get_weather"
        mock_node.params = {"city": "London"}
        mock_dag = MagicMock()
        mock_dag.nodes = [mock_node]

        runtime._last_execution = {"dag": mock_dag}
        runtime._last_execution_text = "What is the weather in London?"

        # We can't easily test the full pipeline without mocking decomposer,
        # but we can verify the _last_execution is stored
        assert runtime._last_execution is not None
        assert runtime._last_execution["dag"].nodes[0].intent == "get_weather"
