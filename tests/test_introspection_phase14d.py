"""Phase 14d — Self-Introspection intent tests."""

from __future__ import annotations

import pytest

from probos.agents.introspect import IntrospectionAgent
from probos.types import IntentMessage, IntentResult


# ===================================================================
# Fixtures
# ===================================================================


class _MockEpisodicMemory:
    """Minimal mock for episodic memory stats."""

    def __init__(self, stats: dict | None = None):
        self._stats = stats or {
            "total": 42,
            "intent_distribution": {"read_file": 20, "write_file": 10, "list_directory": 8, "run_command": 3, "http_fetch": 1},
            "avg_success_rate": 0.89,
            "most_used_agents": {"file_reader-0": 20},
        }

    async def get_stats(self) -> dict:
        return self._stats


class _MockTrustNetwork:
    def all_scores(self) -> dict[str, float]:
        return {"agent_1": 0.8, "agent_2": 0.6, "agent_3": 0.9}

    def get_score(self, agent_id: str) -> float:
        return self.all_scores().get(agent_id, 0.5)


class _MockHebbianRouter:
    weight_count = 5

    def all_weights_typed(self):
        return {}


class _MockRegistry:
    def __init__(self, agents=None):
        self._agents = agents or []

    def all(self):
        return self._agents

    @property
    def count(self):
        return len(self._agents)


class _MockPool:
    def __init__(self, healthy=3, target=3):
        self._healthy = healthy
        self.target_size = target

    @property
    def healthy_agents(self):
        return list(range(self._healthy))


class _FakeAgent:
    """Fake agent for registry."""
    def __init__(self, tier="core"):
        self.tier = tier


class _MockRuntime:
    """Minimal mock of ProbOSRuntime for introspection tests."""

    def __init__(self, episodic_memory=None, knowledge_store=None):
        self.episodic_memory = episodic_memory
        self.trust_network = _MockTrustNetwork()
        self.hebbian_router = _MockHebbianRouter()
        self.registry = _MockRegistry([
            _FakeAgent("core"), _FakeAgent("core"), _FakeAgent("core"),
            _FakeAgent("utility"),
            _FakeAgent("domain"), _FakeAgent("domain"),
        ])
        self.pools = {"filesystem": _MockPool(), "system": _MockPool(2, 2)}
        self._knowledge_store = knowledge_store
        self.dream_scheduler = None


@pytest.fixture
def introspect_agent():
    """Create an IntrospectionAgent with a mock runtime."""
    agent = IntrospectionAgent(pool="introspection")
    agent._runtime = _MockRuntime(episodic_memory=_MockEpisodicMemory())
    return agent


@pytest.fixture
def introspect_agent_no_memory():
    """Create an IntrospectionAgent with no episodic memory."""
    agent = IntrospectionAgent(pool="introspection")
    agent._runtime = _MockRuntime(episodic_memory=None)
    return agent


# ===================================================================
# 1. introspect_memory tests
# ===================================================================


class TestIntrospectMemory:
    """Tests for the introspect_memory intent handler."""

    @pytest.mark.asyncio
    async def test_returns_stats_when_enabled(self, introspect_agent):
        intent = IntentMessage(intent="introspect_memory", params={})
        result = await introspect_agent.handle_intent(intent)
        assert isinstance(result, IntentResult)
        assert result.success is True
        data = result.result
        assert data["enabled"] is True
        assert data["total_episodes"] == 42
        assert data["unique_intents"] == 5
        assert data["success_rate"] == 0.89
        assert "intent_distribution" in data

    @pytest.mark.asyncio
    async def test_returns_not_enabled_when_disabled(self, introspect_agent_no_memory):
        intent = IntentMessage(intent="introspect_memory", params={})
        result = await introspect_agent_no_memory.handle_intent(intent)
        assert isinstance(result, IntentResult)
        assert result.success is True
        data = result.result
        assert data["enabled"] is False
        assert "message" in data


# ===================================================================
# 2. introspect_system tests
# ===================================================================


class TestIntrospectSystem:
    """Tests for the introspect_system intent handler."""

    @pytest.mark.asyncio
    async def test_returns_agent_count_by_tier(self, introspect_agent):
        intent = IntentMessage(intent="introspect_system", params={})
        result = await introspect_agent.handle_intent(intent)
        assert isinstance(result, IntentResult)
        assert result.success is True
        data = result.result
        tiers = data["agents_by_tier"]
        assert tiers["core"] == 3
        assert tiers["utility"] == 1
        assert tiers["domain"] == 2

    @pytest.mark.asyncio
    async def test_returns_trust_summary(self, introspect_agent):
        intent = IntentMessage(intent="introspect_system", params={})
        result = await introspect_agent.handle_intent(intent)
        data = result.result
        trust = data["trust_summary"]
        assert trust["agent_count"] == 3
        assert "mean" in trust
        assert "min" in trust
        assert "max" in trust
        assert trust["min"] <= trust["mean"] <= trust["max"]

    @pytest.mark.asyncio
    async def test_returns_hebbian_weight_count(self, introspect_agent):
        intent = IntentMessage(intent="introspect_system", params={})
        result = await introspect_agent.handle_intent(intent)
        data = result.result
        assert data["hebbian_weight_count"] == 5

    @pytest.mark.asyncio
    async def test_includes_knowledge_status(self):
        """Knowledge store info appears when available."""

        class _FakeKnowledge:
            repo_path = "/tmp/knowledge"

        agent = IntrospectionAgent(pool="introspection")
        agent._runtime = _MockRuntime(knowledge_store=_FakeKnowledge())
        intent = IntentMessage(intent="introspect_system", params={})
        result = await agent.handle_intent(intent)
        data = result.result
        assert data["knowledge"]["enabled"] is True
        assert data["knowledge"]["repo_path"] == "/tmp/knowledge"

    @pytest.mark.asyncio
    async def test_knowledge_disabled(self, introspect_agent):
        intent = IntentMessage(intent="introspect_system", params={})
        result = await introspect_agent.handle_intent(intent)
        data = result.result
        assert data["knowledge"]["enabled"] is False


# ===================================================================
# 3. Descriptor validation
# ===================================================================


class TestIntrospectionDescriptors:
    """New intents have correct descriptor metadata."""

    def test_both_intents_in_descriptors(self):
        names = [d.name for d in IntrospectionAgent.intent_descriptors]
        assert "introspect_memory" in names
        assert "introspect_system" in names

    def test_both_require_reflect(self):
        desc_map = {d.name: d for d in IntrospectionAgent.intent_descriptors}
        assert desc_map["introspect_memory"].requires_reflect is True
        assert desc_map["introspect_system"].requires_reflect is True


# ===================================================================
# 4. MockLLMClient pattern tests
# ===================================================================


class TestMockLLMPatterns:
    """MockLLMClient routes introspection patterns correctly."""

    @pytest.mark.asyncio
    async def test_memory_pattern(self):
        import json
        from probos.cognitive.llm_client import MockLLMClient
        from probos.types import LLMRequest

        client = MockLLMClient()
        request = LLMRequest(prompt="do you have memory?", system_prompt="")
        response = await client.complete(request)
        data = json.loads(response.content)
        intents = data.get("intents", [])
        assert len(intents) == 1
        assert intents[0]["intent"] == "introspect_memory"

    @pytest.mark.asyncio
    async def test_system_pattern(self):
        import json
        from probos.cognitive.llm_client import MockLLMClient
        from probos.types import LLMRequest

        client = MockLLMClient()
        request = LLMRequest(prompt="how is the system?", system_prompt="")
        response = await client.complete(request)
        data = json.loads(response.content)
        intents = data.get("intents", [])
        assert len(intents) == 1
        assert intents[0]["intent"] == "introspect_system"
