"""Tests for runtime skill routing to cognitive agents (Phase 15b, AD-202)."""

from __future__ import annotations

import asyncio

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig, SelfModConfig
from probos.runtime import ProbOSRuntime
from probos.substrate.skill_agent import SkillBasedAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult, Skill


# ---------------------------------------------------------------------------
# Concrete CognitiveAgent for testing
# ---------------------------------------------------------------------------

class RoutingTestAgent(CognitiveAgent):
    """CognitiveAgent for runtime routing tests."""
    agent_type = "routing_test"
    _handled_intents = {"route_test"}
    instructions = "You are a routing test agent."
    intent_descriptors = [
        IntentDescriptor(
            name="route_test",
            params={},
            description="Routing test intent",
            tier="domain",
        )
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_skill(name: str) -> Skill:
    """Create a test skill."""
    async def handler(intent: IntentMessage, **kwargs) -> IntentResult:
        return IntentResult(
            intent_id=intent.id, agent_id="test",
            success=True, result=f"routed_{name}", confidence=0.9,
        )

    return Skill(
        name=name,
        descriptor=IntentDescriptor(name=name, params={}, description=f"Test skill {name}"),
        source_code="# mock",
        handler=handler,
    )


# ===========================================================================
# Test cases
# ===========================================================================

class TestRuntimeSkillRouting:
    """Test _add_skill_to_agents routing."""

    @pytest.fixture
    def config(self, tmp_path):
        return SystemConfig(
            self_mod=SelfModConfig(enabled=True, require_user_approval=False),
        )

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_add_skill_default_targets_skill_agent(self, config, llm, tmp_path):
        """_add_skill_to_agents with default target adds to SkillBasedAgent."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()

        skill = _make_skill("test_default")
        await rt._add_skill_to_agents(skill)

        # Check skill was added to SkillBasedAgent instances
        pool = rt.pools.get("skills")
        assert pool is not None
        for agent_id in pool.healthy_agents:
            agent = rt.registry.get(agent_id)
            if isinstance(agent, SkillBasedAgent):
                names = [s.name for s in agent.skills]
                assert "test_default" in names

        await rt.stop()

    @pytest.mark.asyncio
    async def test_add_skill_to_cognitive_agent_type(self, config, llm, tmp_path):
        """_add_skill_to_agents with cognitive target adds to correct agent."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()

        # Register a cognitive agent
        rt.register_agent_type("routing_test", RoutingTestAgent)
        await rt.create_pool("routing_test_pool", "routing_test",
                             target_size=1, llm_client=rt.llm_client)

        skill = _make_skill("attached_skill")
        await rt._add_skill_to_agents(skill, target_agent_type="routing_test")

        # Verify skill was attached to the routing_test agent
        pool = rt.pools.get("routing_test_pool")
        assert pool is not None
        for agent_id in pool.healthy_agents:
            agent = rt.registry.get(agent_id)
            if isinstance(agent, RoutingTestAgent):
                assert "attached_skill" in agent._skills

        await rt.stop()

    @pytest.mark.asyncio
    async def test_add_skill_falls_back_when_target_not_found(self, config, llm, tmp_path):
        """_add_skill_to_agents falls back to SkillBasedAgent when target type missing."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()

        skill = _make_skill("fallback_skill")
        await rt._add_skill_to_agents(skill, target_agent_type="nonexistent_type")

        # Should fall back to SkillBasedAgent
        pool = rt.pools.get("skills")
        assert pool is not None
        for agent_id in pool.healthy_agents:
            agent = rt.registry.get(agent_id)
            if isinstance(agent, SkillBasedAgent):
                names = [s.name for s in agent.skills]
                assert "fallback_skill" in names

        await rt.stop()

    @pytest.mark.asyncio
    async def test_get_llm_equipped_types_includes_cognitive(self, config, llm, tmp_path):
        """_get_llm_equipped_types includes CognitiveAgent subclasses."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()

        # Register a cognitive agent
        rt.register_agent_type("routing_test", RoutingTestAgent)
        await rt.create_pool("routing_test_pool", "routing_test",
                             target_size=1, llm_client=rt.llm_client)

        types = rt._get_llm_equipped_types()
        assert "routing_test" in types
        assert "skill_agent" in types

        await rt.stop()

    @pytest.mark.asyncio
    async def test_get_agent_classes_returns_registered_types(self, config, llm, tmp_path):
        """_get_agent_classes returns mapping of agent_type to class."""
        rt = ProbOSRuntime(config=config, llm_client=llm, data_dir=tmp_path)
        await rt.start()

        rt.register_agent_type("routing_test", RoutingTestAgent)
        await rt.create_pool("routing_test_pool", "routing_test",
                             target_size=1, llm_client=rt.llm_client)

        classes = rt._get_agent_classes()
        assert "routing_test" in classes
        assert classes["routing_test"] is RoutingTestAgent

        await rt.stop()
