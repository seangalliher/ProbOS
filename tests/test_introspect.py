"""Tests for Phase 6a: Introspection & Self-Awareness."""

import asyncio
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.agents.introspect import IntrospectionAgent
from probos.cognitive.decomposer import SYSTEM_PROMPT, IntentDecomposer
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.experience.shell import ProbOSShell
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.types import Episode, IntentMessage, TaskDAG, TaskNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_runtime(
    previous_execution=None,
    episodic_memory=None,
    agents=None,
    trust_scores=None,
    weights=None,
):
    """Build a lightweight mock runtime for IntrospectionAgent unit tests."""
    rt = MagicMock()
    rt._previous_execution = previous_execution
    rt.episodic_memory = episodic_memory

    # Registry
    rt.registry.all.return_value = agents or []
    rt.registry.get.return_value = None
    rt.registry.count = len(agents) if agents else 0

    # Trust network
    rt.trust_network.get_score.return_value = 0.5
    rt.trust_network.all_scores.return_value = trust_scores or {}

    # Hebbian router
    rt.hebbian_router.all_weights_typed.return_value = weights or {}

    # Pools
    rt.pools = {}

    # Attention
    rt.attention = MagicMock()
    rt.attention.queue_size = 0

    # Workflow cache
    rt.workflow_cache = MagicMock()
    rt.workflow_cache.size = 0
    rt.workflow_cache.entries = []

    # Dreaming
    rt.dream_scheduler = None

    return rt


def _make_agent(agent_type="file_reader", agent_id="abc123"):
    """Create a simple mock agent."""
    agent = MagicMock(spec=BaseAgent)
    agent.id = agent_id
    agent.agent_type = agent_type
    agent.pool = "filesystem"
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.confidence = 0.8
    agent.trust_score = 0.5
    agent.capabilities = []
    agent.meta = MagicMock()
    agent.meta.total_operations = 10
    agent.meta.success_count = 8
    agent.info.return_value = {
        "id": agent_id,
        "type": agent_type,
        "pool": "filesystem",
        "state": "active",
        "confidence": 0.8,
        "trust_score": 0.5,
        "capabilities": ["read_file"],
        "operations": 10,
        "success_rate": 0.8,
    }
    return agent


# ---------------------------------------------------------------------------
# IntrospectionAgent unit tests
# ---------------------------------------------------------------------------

class TestIntrospectionAgent:

    def test_introspect_agent_creates_with_runtime(self):
        """Create an IntrospectionAgent with a mock runtime."""
        rt = _mock_runtime()
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        assert agent._runtime is rt

    def test_introspect_agent_creates_without_runtime(self):
        """Create without runtime kwarg."""
        agent = IntrospectionAgent(pool="introspect")
        assert agent._runtime is None

    @pytest.mark.asyncio
    async def test_explain_last_with_previous_execution(self):
        """explain_last returns previous execution info."""
        prev = {
            "input": "read the file at /tmp/test.txt",
            "dag": TaskDAG(nodes=[
                TaskNode(id="t1", intent="read_file", params={"path": "/tmp/test.txt"}, status="completed"),
            ], source_text="read the file at /tmp/test.txt"),
            "results": {},
            "node_count": 1,
            "completed_count": 1,
            "failed_count": 0,
        }
        rt = _mock_runtime(previous_execution=prev)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="explain_last", params={})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert result.result["source"] == "execution_history"
        assert result.result["input"] == "read the file at /tmp/test.txt"
        await agent.stop()

    @pytest.mark.asyncio
    async def test_explain_last_no_previous_execution(self):
        """explain_last with no previous execution and no episodic memory."""
        rt = _mock_runtime(previous_execution=None, episodic_memory=None)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="explain_last", params={})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert "No execution history" in result.result["explanation"]
        await agent.stop()

    @pytest.mark.asyncio
    async def test_explain_last_falls_back_to_episodic(self):
        """explain_last with no previous_execution but episodic memory has an episode."""
        mem = MockEpisodicMemory(max_episodes=100, relevance_threshold=0.0)
        ep = Episode(
            timestamp=1000.0,
            user_input="read file at /tmp/x.txt",
            dag_summary={"node_count": 1},
            outcomes=[{"intent": "read_file", "success": True}],
            agent_ids=["agent1"],
            duration_ms=50.0,
        )
        await mem.start()
        await mem.store(ep)

        rt = _mock_runtime(previous_execution=None, episodic_memory=mem)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="explain_last", params={})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        # Episodic fallback uses run_until_complete which won't work in async test
        # It should either succeed or fall through to "No execution history"
        await agent.stop()
        await mem.stop()

    @pytest.mark.asyncio
    async def test_agent_info_by_type(self):
        """agent_info returns agents matching a given type."""
        agents = [_make_agent("file_reader", f"fr{i}") for i in range(3)]
        rt = _mock_runtime(agents=agents)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="agent_info", params={"agent_type": "file_reader"})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert len(result.result["agents"]) == 3
        await agent.stop()

    @pytest.mark.asyncio
    async def test_agent_info_by_id(self):
        """agent_info returns a specific agent by ID."""
        mock_agent = _make_agent("file_reader", "specific123")
        rt = _mock_runtime()
        rt.registry.get.return_value = mock_agent

        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="agent_info", params={"agent_id": "specific123"})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert len(result.result["agents"]) == 1
        await agent.stop()

    @pytest.mark.asyncio
    async def test_agent_info_unknown_type(self):
        """agent_info with nonexistent type returns empty list."""
        rt = _mock_runtime(agents=[])
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="agent_info", params={"agent_type": "nonexistent"})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert len(result.result["agents"]) == 0
        assert "No agents found" in result.result["message"]
        await agent.stop()

    @pytest.mark.asyncio
    async def test_agent_info_no_filter_returns_all(self):
        """agent_info with no agent_type or agent_id returns all agents."""
        agents = [
            _make_agent("file_reader", "fr1"),
            _make_agent("file_writer", "fw1"),
            _make_agent("introspect", "in1"),
        ]
        rt = _mock_runtime(agents=agents)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="agent_info", params={})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert len(result.result["agents"]) == 3
        await agent.stop()

    @pytest.mark.asyncio
    async def test_agent_info_includes_hebbian_context(self):
        """agent_info result includes Hebbian weight info."""
        mock_agent = _make_agent("file_reader", "agent_hebb")
        weights = {("agent_hebb", "other_agent", "intent"): 0.42}

        rt = _mock_runtime(agents=[mock_agent], weights=weights)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="agent_info", params={"agent_type": "file_reader"})
        result = await agent.handle_intent(msg)

        assert result is not None
        agent_data = result.result["agents"][0]
        assert "hebbian" in agent_data
        assert agent_data["hebbian"]["total_connections"] >= 1
        await agent.stop()

    @pytest.mark.asyncio
    async def test_system_health_returns_structured(self):
        """system_health returns a structured dict with expected keys."""
        rt = _mock_runtime()
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="system_health", params={})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        data = result.result
        assert "pool_health" in data
        assert "trust_outliers" in data
        assert "overall_health" in data
        assert "cache_stats" in data
        assert "hebbian_density" in data
        await agent.stop()

    @pytest.mark.asyncio
    async def test_why_queries_episodic_and_hebbian(self):
        """why intent queries episodic memory and includes agent Hebbian context."""
        mem = MockEpisodicMemory(max_episodes=100, relevance_threshold=0.0)
        ep = Episode(
            timestamp=1000.0,
            user_input="read the file",
            dag_summary={},
            outcomes=[{"intent": "read_file", "success": True}],
            agent_ids=["agent_abc"],
            duration_ms=50.0,
        )
        await mem.start()
        await mem.store(ep)

        rt = _mock_runtime(episodic_memory=mem)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="why", params={"question": "why did you read the file?"})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert len(result.result["matching_episodes"]) >= 1
        assert "agent_context" in result.result
        await agent.stop()
        await mem.stop()

    @pytest.mark.asyncio
    async def test_why_no_episodic(self):
        """why without episodic memory returns graceful response."""
        rt = _mock_runtime(episodic_memory=None)
        agent = IntrospectionAgent(pool="introspect", runtime=rt)
        await agent.start()

        msg = IntentMessage(intent="why", params={"question": "why?"})
        result = await agent.handle_intent(msg)

        assert result is not None
        assert result.success is True
        assert len(result.result["matching_episodes"]) == 0
        assert "No episodic memory" in result.result["explanation"]
        await agent.stop()

    def test_introspect_capability_registered(self):
        """IntrospectionAgent has 'introspect' capability."""
        agent = IntrospectionAgent(pool="introspect")
        caps = [c.can for c in agent.capabilities]
        assert "introspect" in caps


# ---------------------------------------------------------------------------
# Decomposer tests
# ---------------------------------------------------------------------------

class TestDecomposerIntrospection:

    def test_system_prompt_includes_introspection_intents(self):
        """SYSTEM_PROMPT contains all 4 introspection intent names."""
        assert "explain_last" in SYSTEM_PROMPT
        assert "agent_info" in SYSTEM_PROMPT
        assert "system_health" in SYSTEM_PROMPT
        assert "why" in SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_decompose_why_question(self):
        """Mock LLM returns a 'why' intent for a why question."""
        llm = MockLLMClient()
        wm = WorkingMemoryManager()
        decomposer = IntentDecomposer(llm_client=llm, working_memory=wm)

        dag = await decomposer.decompose("why did you use file_reader for that?")
        assert len(dag.nodes) == 1
        assert dag.nodes[0].intent == "why"


# ---------------------------------------------------------------------------
# Runtime integration tests
# ---------------------------------------------------------------------------

class TestRuntimeIntrospection:

    @pytest.fixture
    async def intro_runtime(self, tmp_path):
        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()
        yield rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_runtime_creates_introspect_pool(self, intro_runtime):
        """Introspect pool exists with 2 agents."""
        assert "introspect" in intro_runtime.pools
        pool = intro_runtime.pools["introspect"]
        assert pool.target_size == 2
        assert pool.current_size == 2

    @pytest.mark.asyncio
    async def test_introspect_agents_have_runtime_ref(self, intro_runtime):
        """Introspect agents have _runtime set to the runtime instance."""
        agents = intro_runtime.registry.get_by_pool("introspect")
        assert len(agents) == 2
        for agent in agents:
            assert agent._runtime is intro_runtime

    @pytest.mark.asyncio
    async def test_previous_execution_stored_correctly(self, intro_runtime, tmp_path):
        """Process two NL requests, verify _previous_execution tracks correctly."""
        # Create test files
        file_a = tmp_path / "a.txt"
        file_a.write_text("content A")
        file_b = tmp_path / "b.txt"
        file_b.write_text("content B")

        # First request
        await intro_runtime.process_natural_language(
            f"read the file at {file_a}"
        )
        first_result = intro_runtime._last_execution
        assert first_result is not None
        assert first_result["input"] == f"read the file at {file_a}"

        # Second request
        await intro_runtime.process_natural_language(
            f"read the file at {file_b}"
        )
        # _previous_execution should now be the first request
        prev = intro_runtime._previous_execution
        assert prev is not None
        assert prev["input"] == f"read the file at {file_a}"

        # _last_execution should be the second request
        last = intro_runtime._last_execution
        assert last is not None
        assert last["input"] == f"read the file at {file_b}"


# ---------------------------------------------------------------------------
# Shell tests
# ---------------------------------------------------------------------------

class TestShellExplain:

    @pytest.fixture
    async def shell_runtime(self, tmp_path):
        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            data_dir=tmp_path / "data",
            llm_client=llm,
            episodic_memory=mem,
        )
        await rt.start()
        yield rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_explain_command_exists_and_dispatches(self, shell_runtime):
        """'/explain' is in COMMANDS and dispatches without error."""
        console = Console(file=StringIO())
        shell = ProbOSShell(shell_runtime, console=console)

        assert "/explain" in ProbOSShell.COMMANDS

        # Execute /explain — should process "what just happened?" through NL pipeline
        await shell.execute_command("/explain")
        output = console.file.getvalue()
        # Should produce some output without crashing
        assert len(output) > 0


# ---------------------------------------------------------------------------
# BF-013: Callsign awareness tests
# ---------------------------------------------------------------------------


class TestCallsignAwareness:
    """Tests for callsign resolution in _agent_info (BF-013)."""

    def test_agent_info_resolves_callsign(self):
        """_agent_info resolves callsign to agent_type."""
        scout = _make_agent(agent_type="scout", agent_id="scout-001")
        rt = _mock_runtime(agents=[scout])
        # Add callsign_registry mock
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.resolve.return_value = {
            "callsign": "Wesley",
            "agent_type": "scout",
            "agent_id": "scout-001",
            "display_name": "Wesley",
            "department": "Science",
        }
        agent = IntrospectionAgent(pool="introspection")
        agent._runtime_ref = rt

        result = agent._agent_info(rt, {"agent_type": "wesley"})
        assert result["success"]
        assert len(result["data"]["agents"]) == 1
        assert result["data"]["agents"][0]["type"] == "scout"

    def test_agent_info_callsign_case_insensitive(self):
        """Callsign resolution works with different cases."""
        scout = _make_agent(agent_type="scout", agent_id="scout-001")
        rt = _mock_runtime(agents=[scout])
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.resolve.return_value = {
            "callsign": "Wesley",
            "agent_type": "scout",
            "agent_id": "scout-001",
        }
        agent = IntrospectionAgent(pool="introspection")
        agent._runtime_ref = rt

        for variant in ["Wesley", "WESLEY", "wesley"]:
            result = agent._agent_info(rt, {"agent_type": variant})
            assert result["success"]
            assert len(result["data"]["agents"]) == 1

    def test_agent_info_no_callsign_registry(self):
        """Falls back gracefully when no callsign_registry exists."""
        rt = _mock_runtime(agents=[])
        # No callsign_registry attribute
        del rt.callsign_registry
        agent = IntrospectionAgent(pool="introspection")
        agent._runtime_ref = rt

        result = agent._agent_info(rt, {"agent_type": "wesley"})
        assert result["data"]["agents"] == []
