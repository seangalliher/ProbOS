"""Tests for CognitiveAgent base class (Phase 15a, AD-191, AD-192)."""

from __future__ import annotations

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------

class SampleCogAgent(CognitiveAgent):
    """Minimal concrete CognitiveAgent for testing."""

    agent_type = "test_cognitive"
    _handled_intents = {"test_intent"}
    instructions = "You are a test agent. Respond concisely."
    intent_descriptors = [
        IntentDescriptor(
            name="test_intent",
            params={"text": "input"},
            description="Test intent",
            tier="domain",
        )
    ]


class CustomActAgent(CognitiveAgent):
    """CognitiveAgent with custom act() override."""

    agent_type = "custom_act"
    _handled_intents = {"custom"}
    instructions = "You are a custom agent. Return JSON with key 'answer'."
    intent_descriptors = [
        IntentDescriptor(name="custom", params={}, description="Custom intent", tier="domain")
    ]

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        output = decision.get("llm_output", "")
        return {"success": True, "result": f"PARSED: {output}"}


class CustomTierAgent(CognitiveAgent):
    """CognitiveAgent with custom _resolve_tier() override."""

    agent_type = "custom_tier"
    _handled_intents = {"tier_test"}
    instructions = "You are a deep-tier agent."
    intent_descriptors = [
        IntentDescriptor(name="tier_test", params={}, description="Tier test", tier="domain")
    ]

    def _resolve_tier(self) -> str:
        return "deep"


class CustomPerceiveAgent(CognitiveAgent):
    """CognitiveAgent with custom perceive() override."""

    agent_type = "custom_perceive"
    _handled_intents = {"perceive_test"}
    instructions = "You are a perceive-override agent."
    intent_descriptors = [
        IntentDescriptor(name="perceive_test", params={}, description="Perceive test", tier="domain")
    ]

    async def perceive(self, intent) -> dict:
        base = await super().perceive(intent)
        base["extra"] = "custom_field"
        return base


# ===========================================================================
# Test cases
# ===========================================================================

class TestCognitiveAgentInit:
    """Test CognitiveAgent __init__ and validation."""

    def test_raises_without_instructions(self):
        """CognitiveAgent raises ValueError without instructions."""
        class NoInstructions(CognitiveAgent):
            agent_type = "no_inst"
            _handled_intents = {"x"}
            intent_descriptors = []

        with pytest.raises(ValueError, match="requires non-empty instructions"):
            NoInstructions()

    def test_raises_with_empty_instructions(self):
        """CognitiveAgent raises ValueError with empty string instructions."""
        class EmptyInstructions(CognitiveAgent):
            agent_type = "empty"
            _handled_intents = {"x"}
            instructions = ""
            intent_descriptors = []

        with pytest.raises(ValueError, match="requires non-empty instructions"):
            EmptyInstructions()

    def test_accepts_class_attribute_instructions(self):
        """CognitiveAgent accepts instructions via class attribute."""
        agent = SampleCogAgent()
        assert agent.instructions == "You are a test agent. Respond concisely."

    def test_accepts_kwarg_instructions(self):
        """CognitiveAgent accepts instructions via __init__ kwarg (overrides class attr)."""
        agent = SampleCogAgent(instructions="Override instructions")
        assert agent.instructions == "Override instructions"

    def test_tier_defaults_to_domain(self):
        """CognitiveAgent tier defaults to 'domain'."""
        agent = SampleCogAgent()
        assert agent.tier == "domain"

    def test_llm_client_from_kwargs(self):
        """CognitiveAgent gets _llm_client from kwargs."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm)
        assert agent._llm_client is llm

    def test_runtime_from_kwargs(self):
        """CognitiveAgent gets _runtime from kwargs."""
        mock_runtime = object()
        agent = SampleCogAgent(runtime=mock_runtime)
        assert agent._runtime is mock_runtime

    def test_is_base_agent_subclass(self):
        """CognitiveAgent is a BaseAgent subclass."""
        assert issubclass(CognitiveAgent, BaseAgent)
        agent = SampleCogAgent()
        assert isinstance(agent, BaseAgent)

    def test_base_agent_instructions_is_none(self):
        """BaseAgent.instructions is None by default."""
        assert BaseAgent.instructions is None

    def test_existing_tool_agents_unaffected(self):
        """Existing tool agents ignore the instructions field."""
        from probos.agents.file_reader import FileReaderAgent
        agent = FileReaderAgent()
        assert agent.instructions is None


class TestCognitiveAgentLifecycle:
    """Test the perceive/decide/act/report lifecycle."""

    @pytest.mark.asyncio
    async def test_perceive_packages_intent_message(self):
        """perceive() packages IntentMessage correctly."""
        agent = SampleCogAgent()
        intent = IntentMessage(intent="test_intent", params={"text": "hello"}, context="ctx")
        obs = await agent.perceive(intent)
        assert obs["intent"] == "test_intent"
        assert obs["params"] == {"text": "hello"}
        assert obs["context"] == "ctx"

    @pytest.mark.asyncio
    async def test_decide_error_without_llm(self):
        """decide() returns error dict when no LLM client."""
        agent = SampleCogAgent()
        obs = {"intent": "test", "params": {}, "context": ""}
        decision = await agent.decide(obs)
        assert decision["action"] == "error"
        assert "No LLM client" in decision["reason"]

    @pytest.mark.asyncio
    async def test_decide_calls_llm(self):
        """decide() calls LLM with instructions as system prompt."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm)
        obs = {"intent": "test_intent", "params": {"text": "hello"}, "context": ""}
        decision = await agent.decide(obs)
        assert decision["action"] == "execute"
        assert "llm_output" in decision
        assert decision["llm_output"]  # non-empty
        # Verify the LLM was called with instructions as system_prompt
        assert llm.last_request is not None
        assert llm.last_request.system_prompt == agent.instructions

    @pytest.mark.asyncio
    async def test_act_returns_success_with_output(self):
        """act() returns success with LLM output."""
        agent = SampleCogAgent()
        decision = {"action": "execute", "llm_output": "response text", "tier_used": "standard"}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "response text"

    @pytest.mark.asyncio
    async def test_act_returns_error_on_error_decision(self):
        """act() returns error on error decision."""
        agent = SampleCogAgent()
        decision = {"action": "error", "reason": "No LLM client available"}
        result = await agent.act(decision)
        assert result["success"] is False
        assert result["error"] == "No LLM client available"

    @pytest.mark.asyncio
    async def test_report_returns_result(self):
        """report() returns the result dict."""
        agent = SampleCogAgent()
        result = {"success": True, "result": "done"}
        report = await agent.report(result)
        assert report is result

    @pytest.mark.asyncio
    async def test_handle_intent_full_lifecycle(self):
        """handle_intent() runs full lifecycle end-to-end."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm)
        intent = IntentMessage(intent="test_intent", params={"text": "hello"})

        result = await agent.handle_intent(intent)

        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.agent_id == agent.id
        assert result.intent_id == intent.id
        assert result.result  # non-empty
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_handle_intent_updates_confidence(self):
        """handle_intent() updates agent confidence on success."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm)
        initial_confidence = agent.confidence
        intent = IntentMessage(intent="test_intent", params={"text": "hello"})

        await agent.handle_intent(intent)

        # Confidence should increase on success
        assert agent.confidence > initial_confidence


class TestCognitiveAgentFormatting:
    """Test helper methods."""

    def test_build_user_message(self):
        """_build_user_message() formats observation correctly."""
        agent = SampleCogAgent()
        obs = {"intent": "test", "params": {"x": 1}, "context": "some context"}
        msg = agent._build_user_message(obs)
        assert "Intent: test" in msg
        assert "Parameters:" in msg
        assert "Context: some context" in msg

    def test_build_user_message_no_params(self):
        """_build_user_message() omits params when empty."""
        agent = SampleCogAgent()
        obs = {"intent": "test", "params": {}, "context": ""}
        msg = agent._build_user_message(obs)
        assert "Intent: test" in msg
        assert "Parameters" not in msg
        assert "Context" not in msg

    def test_resolve_tier_default(self):
        """_resolve_tier() returns 'standard' by default."""
        agent = SampleCogAgent()
        assert agent._resolve_tier() == "standard"


class TestCognitiveAgentOverrides:
    """Test subclass overrides."""

    @pytest.mark.asyncio
    async def test_custom_act_override(self):
        """Subclass with custom act() override works."""
        llm = MockLLMClient()
        agent = CustomActAgent(llm_client=llm)
        intent = IntentMessage(intent="custom", params={})
        result = await agent.handle_intent(intent)
        assert result.success is True
        assert result.result.startswith("PARSED:")

    @pytest.mark.asyncio
    async def test_custom_resolve_tier(self):
        """Subclass with custom _resolve_tier() override works."""
        llm = MockLLMClient()
        agent = CustomTierAgent(llm_client=llm)
        assert agent._resolve_tier() == "deep"
        # Verify the LLM request uses the override tier
        intent = IntentMessage(intent="tier_test", params={})
        await agent.handle_intent(intent)
        assert llm.last_request.tier == "deep"

    @pytest.mark.asyncio
    async def test_custom_perceive_override(self):
        """Subclass with custom perceive() override works."""
        agent = CustomPerceiveAgent()
        intent = IntentMessage(intent="perceive_test", params={"a": 1})
        obs = await agent.perceive(intent)
        assert obs["extra"] == "custom_field"
        assert obs["intent"] == "perceive_test"
