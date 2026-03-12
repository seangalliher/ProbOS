"""Tests for CognitiveAgent skill attachment (Phase 15b, AD-199)."""

from __future__ import annotations

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentDescriptor, IntentMessage, IntentResult, Skill


# ---------------------------------------------------------------------------
# Concrete CognitiveAgent subclass for testing
# ---------------------------------------------------------------------------

class DataAnalyzerAgent(CognitiveAgent):
    """Sample cognitive agent for testing skill attachment."""

    agent_type = "data_analyzer"
    _handled_intents = {"analyze_data"}
    instructions = (
        "You are a data analysis specialist. "
        "Given data, produce structured insights."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="analyze_data",
            params={"data": "input data"},
            description="Analyze data and return insights",
            tier="domain",
        )
    ]

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        return {"success": True, "result": f"Analysis: {decision.get('llm_output', '')}"}


# ---------------------------------------------------------------------------
# Helper: create a mock skill
# ---------------------------------------------------------------------------

def _make_skill(name: str, description: str = "test skill") -> Skill:
    """Create a mock Skill with a simple async handler."""
    async def handler(intent: IntentMessage, **kwargs) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id="test",
            success=True,
            result=f"skill_result_for_{name}",
            confidence=0.9,
        )

    descriptor = IntentDescriptor(
        name=name,
        params={"input": "text"},
        description=description,
        tier="domain",
    )
    return Skill(
        name=name,
        descriptor=descriptor,
        source_code="# mock",
        handler=handler,
    )


# ===========================================================================
# Test cases
# ===========================================================================

class TestCognitiveAgentSkillsInit:
    """Test CognitiveAgent starts with empty skills."""

    def test_starts_with_empty_skills(self):
        """CognitiveAgent._skills is an empty dict on init."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        assert agent._skills == {}

    def test_has_add_skill_method(self):
        """CognitiveAgent has add_skill method."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        assert hasattr(agent, "add_skill")
        assert callable(agent.add_skill)

    def test_has_remove_skill_method(self):
        """CognitiveAgent has remove_skill method."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        assert hasattr(agent, "remove_skill")
        assert callable(agent.remove_skill)


class TestCognitiveAgentAddSkill:
    """Test add_skill() behavior."""

    def test_add_skill_stores_in_skills_dict(self):
        """add_skill() stores skill in _skills dict."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)
        assert "analyze_csv" in agent._skills
        assert agent._skills["analyze_csv"] is skill

    def test_add_skill_updates_handled_intents(self):
        """add_skill() adds intent to _handled_intents."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)
        assert "analyze_csv" in agent._handled_intents

    def test_add_skill_updates_intent_descriptors(self):
        """add_skill() adds descriptor to intent_descriptors."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill = _make_skill("analyze_csv", "Analyze CSV files")
        agent.add_skill(skill)
        names = [d.name for d in agent.intent_descriptors]
        assert "analyze_csv" in names

    def test_add_skill_updates_class_level_descriptors(self):
        """add_skill() updates class-level descriptors for decomposer discovery."""
        # Use a fresh subclass to avoid cross-test pollution
        class FreshAgent(DataAnalyzerAgent):
            agent_type = "fresh_test"
            _handled_intents = {"analyze_data"}
            intent_descriptors = list(DataAnalyzerAgent.intent_descriptors)

        agent = FreshAgent(llm_client=MockLLMClient())
        skill = _make_skill("new_skill")
        agent.add_skill(skill)

        # Class-level should be updated
        cls_names = [d.name for d in FreshAgent.intent_descriptors]
        assert "new_skill" in cls_names
        assert "new_skill" in FreshAgent._handled_intents

    def test_add_duplicate_skill_replaces(self):
        """Adding a skill with the same intent name replaces the previous one."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill1 = _make_skill("analyze_csv", "First version")
        skill2 = _make_skill("analyze_csv", "Second version")

        agent.add_skill(skill1)
        agent.add_skill(skill2)

        assert agent._skills["analyze_csv"] is skill2

    def test_add_multiple_skills(self):
        """Multiple skills can coexist on one cognitive agent."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill1 = _make_skill("analyze_csv")
        skill2 = _make_skill("parse_excel")

        agent.add_skill(skill1)
        agent.add_skill(skill2)

        assert len(agent._skills) == 2
        assert "analyze_csv" in agent._skills
        assert "parse_excel" in agent._skills


class TestCognitiveAgentRemoveSkill:
    """Test remove_skill() behavior."""

    def test_remove_skill_from_skills_dict(self):
        """remove_skill() removes from _skills dict."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)
        agent.remove_skill("analyze_csv")
        assert "analyze_csv" not in agent._skills

    def test_remove_skill_from_handled_intents(self):
        """remove_skill() removes from _handled_intents."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)
        agent.remove_skill("analyze_csv")
        assert "analyze_csv" not in agent._handled_intents

    def test_remove_skill_from_intent_descriptors(self):
        """remove_skill() removes descriptor from intent_descriptors."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)
        agent.remove_skill("analyze_csv")
        names = [d.name for d in agent.intent_descriptors]
        assert "analyze_csv" not in names

    def test_remove_nonexistent_skill_is_noop(self):
        """remove_skill() for non-existent intent is a no-op."""
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        # Should not raise
        agent.remove_skill("doesnt_exist")


class TestCognitiveAgentSkillDispatch:
    """Test handle_intent() with skills."""

    @pytest.mark.asyncio
    async def test_dispatches_to_skill_handler(self):
        """handle_intent() dispatches to skill handler when intent matches."""
        llm = MockLLMClient()
        agent = DataAnalyzerAgent(llm_client=llm)
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)

        intent = IntentMessage(intent="analyze_csv", params={"input": "data"})
        result = await agent.handle_intent(intent)

        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result == "skill_result_for_analyze_csv"

    @pytest.mark.asyncio
    async def test_falls_through_to_cognitive_lifecycle(self):
        """handle_intent() falls through to cognitive lifecycle when no skill matches."""
        llm = MockLLMClient()
        agent = DataAnalyzerAgent(llm_client=llm)
        skill = _make_skill("analyze_csv")
        agent.add_skill(skill)

        # Use the original intent that goes through cognitive lifecycle
        intent = IntentMessage(intent="analyze_data", params={"data": "test"})
        result = await agent.handle_intent(intent)

        assert isinstance(result, IntentResult)
        assert result.success is True
        # Should come from the cognitive act() which prepends "Analysis: "
        assert "Analysis:" in result.result

    @pytest.mark.asyncio
    async def test_passes_llm_client_to_skill_handler(self):
        """handle_intent() passes llm_client to skill handler."""
        llm = MockLLMClient()
        received_kwargs = {}

        async def capturing_handler(intent: IntentMessage, **kwargs) -> IntentResult:
            received_kwargs.update(kwargs)
            return IntentResult(
                intent_id=intent.id, agent_id="test",
                success=True, result="done", confidence=0.9,
            )

        skill = Skill(
            name="test_skill",
            descriptor=IntentDescriptor(name="test_skill", params={}, description="Test"),
            source_code="# mock",
            handler=capturing_handler,
        )
        agent = DataAnalyzerAgent(llm_client=llm)
        agent.add_skill(skill)

        intent = IntentMessage(intent="test_skill", params={})
        await agent.handle_intent(intent)

        assert "llm_client" in received_kwargs
        assert received_kwargs["llm_client"] is llm

    @pytest.mark.asyncio
    async def test_skill_receives_correct_intent(self):
        """Skill handler receives the correct IntentMessage."""
        received_intents = []

        async def tracking_handler(intent: IntentMessage, **kwargs) -> IntentResult:
            received_intents.append(intent)
            return IntentResult(
                intent_id=intent.id, agent_id="test",
                success=True, result="ok", confidence=0.9,
            )

        skill = Skill(
            name="track_skill",
            descriptor=IntentDescriptor(name="track_skill", params={}, description="Track"),
            source_code="# mock",
            handler=tracking_handler,
        )
        agent = DataAnalyzerAgent(llm_client=MockLLMClient())
        agent.add_skill(skill)

        intent = IntentMessage(intent="track_skill", params={"key": "value"})
        await agent.handle_intent(intent)

        assert len(received_intents) == 1
        assert received_intents[0].intent == "track_skill"
        assert received_intents[0].params == {"key": "value"}
