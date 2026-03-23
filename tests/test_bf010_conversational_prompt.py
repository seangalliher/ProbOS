"""Tests for BF-010: Conversational system prompt for 1:1 sessions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentDescriptor, IntentMessage, IntentResult


class _TestCrewAgent(CognitiveAgent):
    """Test agent with domain-specific instructions containing structured format."""
    agent_type = "test_crew"
    tier = "domain"
    instructions = (
        "You are a test agent. "
        "ALWAYS format your response as:\n"
        "===REPORT===\n"
        "findings: ...\n"
        "===END REPORT==="
    )
    intent_descriptors = [
        IntentDescriptor(
            name="test_task",
            params={"data": "data to process"},
            description="Process test data",
        ),
    ]
    _handled_intents = {"test_task"}

    def __init__(self, **kwargs):
        kwargs.setdefault("pool", "test_crew")
        super().__init__(**kwargs)


# ---------------------------------------------------------------------------
# 1. Conversational system prompt excludes domain instructions
# ---------------------------------------------------------------------------

class TestConversationalSystemPrompt:
    """BF-010: direct_message intents get conversational system prompt."""

    @pytest.mark.asyncio
    async def test_conversation_excludes_domain_instructions(self):
        """direct_message → system prompt should NOT contain ===REPORT===."""
        llm = MockLLMClient()
        agent = _TestCrewAgent(llm_client=llm)

        observation = {
            "intent": "direct_message",
            "params": {"text": "Hello, how are you?"},
        }
        await agent.decide(observation)

        assert llm.call_count == 1
        system_prompt = llm.last_request.system_prompt
        assert "===REPORT===" not in system_prompt
        assert "===END REPORT===" not in system_prompt
        assert "ALWAYS format" not in system_prompt

    @pytest.mark.asyncio
    async def test_conversation_includes_conversational_directive(self):
        """direct_message → system prompt should include conversational directive."""
        llm = MockLLMClient()
        agent = _TestCrewAgent(llm_client=llm)

        observation = {
            "intent": "direct_message",
            "params": {"text": "Tell me about yourself."},
        }
        await agent.decide(observation)

        system_prompt = llm.last_request.system_prompt
        assert "1:1 conversation with the Captain" in system_prompt
        assert "Respond naturally" in system_prompt
        assert "Do NOT use any structured output formats" in system_prompt


# ---------------------------------------------------------------------------
# 2. Task intents still use full domain instructions
# ---------------------------------------------------------------------------

class TestTaskInstructionsPreserved:
    """BF-010: Non-conversation intents still get full domain instructions."""

    @pytest.mark.asyncio
    async def test_task_includes_domain_instructions(self):
        """test_task → system prompt SHOULD contain ===REPORT=== format."""
        llm = MockLLMClient()
        agent = _TestCrewAgent(llm_client=llm)

        observation = {
            "intent": "test_task",
            "params": {"data": "some test data"},
        }
        await agent.decide(observation)

        system_prompt = llm.last_request.system_prompt
        assert "===REPORT===" in system_prompt
        assert "ALWAYS format" in system_prompt

    @pytest.mark.asyncio
    async def test_task_does_not_include_conversational_directive(self):
        """test_task → system prompt should NOT include conversational directive."""
        llm = MockLLMClient()
        agent = _TestCrewAgent(llm_client=llm)

        observation = {
            "intent": "test_task",
            "params": {"data": "different test data for directive check"},
        }
        await agent.decide(observation)

        system_prompt = llm.last_request.system_prompt
        assert "1:1 conversation with the Captain" not in system_prompt


# ---------------------------------------------------------------------------
# 3. Regression: intent propagation and act() guard still work
# ---------------------------------------------------------------------------

class TestBF010Regression:
    """BF-010: Existing AD-398 mechanisms still function with the new prompt logic."""

    @pytest.mark.asyncio
    async def test_handle_intent_propagates_intent_field(self):
        """decision dict still has 'intent' key from AD-398."""
        llm = MockLLMClient()
        agent = _TestCrewAgent(llm_client=llm)

        captured = []
        original_act = agent.act

        async def capture(decision):
            captured.append(decision)
            return await original_act(decision)

        agent.act = capture

        intent = IntentMessage(
            intent="direct_message",
            params={"message": "hi"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)

        assert len(captured) == 1
        assert captured[0]["intent"] == "direct_message"
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_base_act_returns_llm_output_for_conversation(self):
        """Base act() returns raw LLM output for direct_message."""
        llm = MockLLMClient()
        agent = _TestCrewAgent(llm_client=llm)

        decision = {
            "intent": "direct_message",
            "action": "execute",
            "llm_output": "Hello Captain, how can I help?",
            "tier_used": "standard",
        }
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Hello Captain, how can I help?"
