"""Tests for CognitiveAgent base class (Phase 15a, AD-191, AD-192)."""

from __future__ import annotations

import time

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
        # compose_instructions() prepends agent.instructions, then appends Standing Orders
        assert llm.last_request is not None
        assert llm.last_request.system_prompt.startswith(agent.instructions)

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


# ---------------------------------------------------------------------------
# Decision Distillation (AD-272)
# ---------------------------------------------------------------------------

class TestDecisionCache:
    """Tests for the decision cache in CognitiveAgent.decide()."""

    @pytest.fixture(autouse=True)
    def clear_caches(self):
        from probos.cognitive.cognitive_agent import _DECISION_CACHES, _CACHE_HITS, _CACHE_MISSES
        _DECISION_CACHES.clear()
        _CACHE_HITS.clear()
        _CACHE_MISSES.clear()

    @pytest.mark.asyncio
    async def test_decision_cache_hit(self):
        """Second call with same observation returns cached result (no LLM call)."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, pool="test")
        obs = {"intent": "test_intent", "params": {"q": "hello"}, "context": ""}

        result1 = await agent.decide(obs)
        result2 = await agent.decide(obs)

        assert result1["action"] == "execute"
        assert result2["cached"] is True
        assert llm.call_count == 1  # LLM called only once

    @pytest.mark.asyncio
    async def test_decision_cache_miss_different_observation(self):
        """Different observations produce different cache entries."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, pool="test")
        obs1 = {"intent": "test_intent", "params": {"q": "hello"}, "context": ""}
        obs2 = {"intent": "test_intent", "params": {"q": "world"}, "context": ""}

        await agent.decide(obs1)
        await agent.decide(obs2)

        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_decision_cache_ttl_expiry(self, monkeypatch):
        """Expired cache entries trigger a new LLM call."""
        import probos.cognitive.cognitive_agent as ca

        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, pool="test")
        obs = {"intent": "test_intent", "params": {"q": "hello"}, "context": ""}

        await agent.decide(obs)
        assert llm.call_count == 1

        # Expire the entry by rewinding created_at
        cache = ca._DECISION_CACHES[agent.agent_type]
        key = list(cache.keys())[0]
        decision, _, ttl = cache[key]
        cache[key] = (decision, time.monotonic() - ttl - 1, ttl)  # force expired

        await agent.decide(obs)
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_decision_cache_key_includes_instructions(self):
        """Two agents with different instructions get different cache entries."""
        from probos.cognitive.cognitive_agent import _DECISION_CACHES

        class AgentA(CognitiveAgent):
            agent_type = "agent_a"
            _handled_intents = {"test"}
            instructions = "You translate text."
            intent_descriptors = []

        class AgentB(CognitiveAgent):
            agent_type = "agent_b"
            _handled_intents = {"test"}
            instructions = "You summarize text."
            intent_descriptors = []

        llm = MockLLMClient()
        a = AgentA(llm_client=llm, pool="test")
        b = AgentB(llm_client=llm, pool="test")
        obs = {"intent": "test", "params": {"q": "same"}, "context": ""}

        await a.decide(obs)
        await b.decide(obs)

        assert llm.call_count == 2
        assert "agent_a" in _DECISION_CACHES
        assert "agent_b" in _DECISION_CACHES

    def test_cache_stats_reports_hits_misses(self):
        """cache_stats() reflects correct counts after operations."""
        from probos.cognitive.cognitive_agent import _DECISION_CACHES, _CACHE_HITS, _CACHE_MISSES

        _DECISION_CACHES["test_type"] = {"k1": ({}, 0.0, 300.0)}
        _CACHE_HITS["test_type"] = 5
        _CACHE_MISSES["test_type"] = 3

        stats = CognitiveAgent.cache_stats()
        assert stats["test_type"]["entries"] == 1
        assert stats["test_type"]["hits"] == 5
        assert stats["test_type"]["misses"] == 3

    @pytest.mark.asyncio
    async def test_cache_eviction_on_overflow(self):
        """Cache evicts oldest entry when exceeding 1000 entries."""
        import time as _time
        from probos.cognitive.cognitive_agent import _DECISION_CACHES

        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, pool="test")

        # Pre-fill cache with 1000 entries, oldest at created_at=1.0
        cache = _DECISION_CACHES.setdefault(agent.agent_type, {})
        for i in range(1000):
            cache[f"key_{i}"] = ({"action": "execute"}, 1.0 + i, 9999.0)

        assert len(cache) == 1000

        # Next decide() should add one and evict the oldest
        obs = {"intent": "test_intent", "params": {"q": "overflow"}, "context": ""}
        await agent.decide(obs)

        assert len(cache) == 1000  # Still 1000 after eviction
        assert "key_0" not in cache  # oldest (created_at=1.0) evicted

    @pytest.mark.asyncio
    async def test_cached_response_has_cached_flag(self):
        """Cache hits include 'cached': True in the decision dict."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, pool="test")
        obs = {"intent": "test_intent", "params": {"q": "flag"}, "context": ""}

        result1 = await agent.decide(obs)
        assert "cached" not in result1

        result2 = await agent.decide(obs)
        assert result2["cached"] is True
        assert result2["action"] == "execute"
