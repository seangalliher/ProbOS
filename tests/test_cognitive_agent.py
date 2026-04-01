"""Tests for CognitiveAgent base class (Phase 15a, AD-191, AD-192)."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.llm_client import MockLLMClient
from probos.crew_profile import CallsignRegistry
from probos.ontology import VesselOntologyService
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


# ---------------------------------------------------------------------------
# AD-430c: Memory recall + act-store lifecycle hooks
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, AsyncMock

from probos.runtime import ProbOSRuntime


class TestMemoryRecall:
    """AD-430c Pillar 4: Memory recall in handle_intent()."""

    def _make_crew_runtime(self, *, has_memory=True, recall_result=None, recall_side_effect=None):
        """Create a mock runtime with episodic memory for crew agents."""
        rt = MagicMock(spec=ProbOSRuntime)
        # is_crew_agent checks ontology.get_crew_agent_types() — include test agent type
        rt.ontology = MagicMock(spec=VesselOntologyService)
        rt.ontology.get_crew_agent_types.return_value = {"test_cognitive", "custom_act", "custom_perceive", "custom_tier"}
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign.return_value = "Wesley"
        if has_memory:
            rt.episodic_memory = MagicMock(spec=EpisodicMemory)
            if recall_side_effect:
                rt.episodic_memory.recall_for_agent = AsyncMock(side_effect=recall_side_effect)
            else:
                rt.episodic_memory.recall_for_agent = AsyncMock(return_value=recall_result or [])
            rt.episodic_memory.store = AsyncMock()
        else:
            rt.episodic_memory = None
        return rt

    @pytest.mark.asyncio
    async def test_memory_recall_injects_recent_memories(self):
        """Memory recall injects recent_memories into observation."""
        ep1 = MagicMock()
        ep1.user_input = "[1:1 with Wesley] Captain: status?"
        ep1.reflection = "Captain asked about status."
        ep1.timestamp = 0
        ep2 = MagicMock()
        ep2.user_input = "[Proactive thought] checked systems"
        ep2.reflection = "Systems nominal."
        ep2.timestamp = 0

        rt = self._make_crew_runtime(recall_result=[ep1, ep2])
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "How are you?", "from": "test"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)

        rt.episodic_memory.recall_for_agent.assert_called_once()
        assert result.success is True
        # Verify _build_user_message got the memories (check LLM call content)
        prompt = llm.last_request.prompt
        assert "=== SHIP MEMORY" in prompt
        # BF-029: input is now preferred over reflection
        assert "[1:1 with Wesley] Captain: status?" in prompt

    @pytest.mark.asyncio
    async def test_memory_recall_skips_proactive_think(self):
        """Memory recall skips proactive_think (avoids duplication)."""
        rt = self._make_crew_runtime()
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="proactive_think",
            params={"text": "review", "context_parts": {}},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.recall_for_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_recall_skips_non_crew(self):
        """Memory recall skips non-crew agents."""
        rt = self._make_crew_runtime()
        # Exclude test_cognitive from crew types so is_crew_agent returns False
        rt.ontology.get_crew_agent_types.return_value = set()
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "hello", "from": "test"},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.recall_for_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_recall_failure_doesnt_block(self):
        """Memory recall failure doesn't block decide()."""
        rt = self._make_crew_runtime(recall_side_effect=RuntimeError("ChromaDB down"))
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "hello", "from": "test"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_memory_recall_no_runtime_no_crash(self):
        """Memory recall with _runtime=None doesn't crash."""
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=None)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "hello", "from": "test"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)

        assert result.success is True


class TestActStoreHook:
    """AD-430c Pillar 5: Act-store lifecycle hook."""

    def _make_crew_runtime(self, *, store_side_effect=None):
        """Create a mock runtime with episodic memory for crew agents."""
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ontology = MagicMock(spec=VesselOntologyService)
        rt.ontology.get_crew_agent_types.return_value = {"analyzer", "test_cognitive"}
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign.return_value = "Wesley"
        rt.episodic_memory = MagicMock(spec=EpisodicMemory)
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])
        if store_side_effect:
            rt.episodic_memory.store = AsyncMock(side_effect=store_side_effect)
        else:
            rt.episodic_memory.store = AsyncMock()
        return rt

    @pytest.mark.asyncio
    async def test_act_store_stores_episode_for_uncovered_intents(self):
        """Act-store stores episode for intents without dedicated storage."""
        rt = self._make_crew_runtime()
        llm = MockLLMClient()

        class AnalyzeAgent(CognitiveAgent):
            agent_type = "analyzer"
            _handled_intents = {"analyze"}
            instructions = "You analyze things."
            intent_descriptors = [
                IntentDescriptor(name="analyze", params={}, description="Analyze", tier="domain")
            ]

        agent = AnalyzeAgent(llm_client=llm, runtime=rt)
        intent = IntentMessage(intent="analyze", params={"text": "check this"})
        result = await agent.handle_intent(intent)

        assert result.success is True
        rt.episodic_memory.store.assert_called_once()
        episode = rt.episodic_memory.store.call_args[0][0]
        assert "[Action: analyze]" in episode.user_input
        assert episode.agent_ids == [agent.id]
        assert episode.outcomes[0]["intent"] == "analyze"

    @pytest.mark.asyncio
    async def test_act_store_skips_proactive_think(self):
        """Act-store skips proactive_think (dedup with AD-430a)."""
        rt = self._make_crew_runtime()
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="proactive_think",
            params={"text": "review", "context_parts": {}},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_act_store_skips_ward_room_notification(self):
        """Act-store skips ward_room_notification (dedup with AD-430a)."""
        rt = self._make_crew_runtime()
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="ward_room_notification",
            params={"title": "Test", "channel_name": "All Hands", "author_callsign": "Bones", "author_id": "bones-1"},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_act_store_skips_hxi_profile_dm(self):
        """Act-store skips direct_message from hxi_profile (dedup with AD-430b)."""
        rt = self._make_crew_runtime()
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "hello", "from": "hxi_profile"},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_act_store_skips_captain_dm(self):
        """Act-store skips direct_message from captain (dedup with shell)."""
        rt = self._make_crew_runtime()
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "report", "from": "captain"},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_act_store_failure_doesnt_block(self):
        """Act-store failure doesn't block response."""
        rt = self._make_crew_runtime(store_side_effect=RuntimeError("ChromaDB down"))
        llm = MockLLMClient()

        class AnalyzeAgent(CognitiveAgent):
            agent_type = "analyzer"
            _handled_intents = {"analyze"}
            instructions = "You analyze things."
            intent_descriptors = [
                IntentDescriptor(name="analyze", params={}, description="Analyze", tier="domain")
            ]

        agent = AnalyzeAgent(llm_client=llm, runtime=rt)
        intent = IntentMessage(intent="analyze", params={"text": "check"})
        result = await agent.handle_intent(intent)

        assert isinstance(result, IntentResult)
        assert result.success is True


class TestBuildUserMessageMemories:
    """AD-430c: _build_user_message renders memory context."""

    def test_direct_message_includes_memories(self):
        """Direct message _build_user_message includes memory context."""
        agent = SampleCogAgent()
        obs = {
            "intent": "direct_message",
            "params": {"text": "Status report"},
            "recent_memories": [
                {"input": "Asked about power grid", "reflection": "Captain asked about power grid status."},
                {"input": "Reviewed EPS", "reflection": "EPS conduits nominal."},
            ],
        }
        msg = agent._build_user_message(obs)
        assert "=== SHIP MEMORY" in msg
        # BF-029: input is now preferred over reflection
        assert "Asked about power grid" in msg
        assert "Reviewed EPS" in msg
        assert "Captain says: Status report" in msg

    def test_ward_room_notification_includes_memories(self):
        """Ward room notification _build_user_message includes memory context."""
        agent = SampleCogAgent()
        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "Engineering",
                "author_callsign": "LaForge",
                "title": "EPS Report",
                "author_id": "laforge-1",
            },
            "context": "Previous discussion here...",
            "recent_memories": [
                {"input": "Prior EPS review", "reflection": "Reviewed EPS conduits last shift."},
            ],
        }
        msg = agent._build_user_message(obs)
        assert "=== SHIP MEMORY" in msg
        # BF-029: input is now preferred over reflection
        assert "Prior EPS review" in msg
        assert "[Ward Room — #Engineering]" in msg


# ---------------------------------------------------------------------------
# BF-027: Memory recall threshold fallback + mock gap
# ---------------------------------------------------------------------------


class TestMockEpisodicMemoryAgentMethods:
    """BF-027: MockEpisodicMemory recall_for_agent and recent_for_agent."""

    @pytest.mark.asyncio
    async def test_recall_for_agent_filters_by_agent_id(self):
        """Test 1: recall_for_agent only returns episodes for the target agent."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.types import Episode

        mem = MockEpisodicMemory()
        await mem.store(Episode(user_input="task alpha", agent_ids=["agent-A"], reflection="did alpha"))
        await mem.store(Episode(user_input="task beta", agent_ids=["agent-A"], reflection="did beta"))
        await mem.store(Episode(user_input="task gamma", agent_ids=["agent-B"], reflection="did gamma"))

        results = await mem.recall_for_agent("agent-A", "task", k=5)
        assert len(results) == 2
        for ep in results:
            assert "agent-A" in ep.agent_ids

    @pytest.mark.asyncio
    async def test_recent_for_agent_returns_most_recent(self):
        """Test 2: recent_for_agent returns most recent episodes by insertion order."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.types import Episode

        mem = MockEpisodicMemory()
        for i in range(5):
            await mem.store(Episode(
                user_input=f"episode-{i}",
                agent_ids=["agent-A"],
                timestamp=float(i),
            ))

        results = await mem.recent_for_agent("agent-A", k=2)
        assert len(results) == 2
        # Most recent first
        assert results[0].user_input == "episode-4"
        assert results[1].user_input == "episode-3"

    @pytest.mark.asyncio
    async def test_recent_for_agent_filters_by_agent_id(self):
        """Test 3: recent_for_agent only returns episodes for the target agent."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.types import Episode

        mem = MockEpisodicMemory()
        await mem.store(Episode(user_input="ep-A1", agent_ids=["agent-A"]))
        await mem.store(Episode(user_input="ep-B1", agent_ids=["agent-B"]))
        await mem.store(Episode(user_input="ep-A2", agent_ids=["agent-A"]))

        results = await mem.recent_for_agent("agent-A", k=5)
        assert len(results) == 2
        for ep in results:
            assert "agent-A" in ep.agent_ids


class TestMemoryRecallFallback:
    """BF-027: Recall fallback to recent_for_agent when semantic recall returns empty."""

    def _make_crew_runtime_with_fallback(self, *, recall_result=None, recent_result=None):
        """Create mock runtime with both recall_for_agent and recent_for_agent."""
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ontology = MagicMock(spec=VesselOntologyService)
        rt.ontology.get_crew_agent_types.return_value = {"test_cognitive", "analyzer"}
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign.return_value = "Wesley"
        rt.episodic_memory = MagicMock(spec=EpisodicMemory)
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=recall_result or [])
        rt.episodic_memory.recent_for_agent = AsyncMock(return_value=recent_result or [])
        rt.episodic_memory.store = AsyncMock()
        return rt

    @pytest.mark.asyncio
    async def test_fallback_fires_when_semantic_recall_empty(self):
        """Test 4: Fallback to recent_for_agent fires when recall_for_agent returns []."""
        ep1 = MagicMock()
        ep1.user_input = "Recent action 1"
        ep1.reflection = "Did something recently."
        ep1.timestamp = 0
        ep2 = MagicMock()
        ep2.user_input = "Recent action 2"
        ep2.reflection = "Did another thing."
        ep2.timestamp = 0

        rt = self._make_crew_runtime_with_fallback(
            recall_result=[],
            recent_result=[ep1, ep2],
        )
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "What have you been doing?", "from": "test"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)

        rt.episodic_memory.recent_for_agent.assert_called_once()
        assert result.success is True
        # Verify memories were injected
        prompt = llm.last_request.prompt
        assert "=== SHIP MEMORY" in prompt
        # BF-029: input is now preferred over reflection
        assert "Recent action 1" in prompt

    @pytest.mark.asyncio
    async def test_fallback_does_not_fire_when_semantic_returns_results(self):
        """Test 5: recent_for_agent NOT called when recall_for_agent returns results."""
        ep = MagicMock()
        ep.user_input = "Semantic match"
        ep.reflection = "Found via semantics."

        rt = self._make_crew_runtime_with_fallback(recall_result=[ep])
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "Tell me about systems", "from": "test"},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        rt.episodic_memory.recent_for_agent.assert_not_called()


# ---------------------------------------------------------------------------
# BF-029: Ward Room recall quality
# ---------------------------------------------------------------------------


class TestRecallQueryEnrichment:
    """BF-029: Tests 1-2 — recall query enrichment with Ward Room + callsign."""

    def _make_crew_runtime(self, *, callsign=None, has_registry=True, recall_result=None, recent_result=None):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ontology = MagicMock(spec=VesselOntologyService)
        rt.ontology.get_crew_agent_types.return_value = {"test_cognitive", "analyzer"}
        rt.episodic_memory = MagicMock(spec=EpisodicMemory)
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=recall_result or [])
        rt.episodic_memory.recent_for_agent = AsyncMock(return_value=recent_result or [])
        rt.episodic_memory.store = AsyncMock()
        if has_registry:
            rt.callsign_registry = MagicMock(spec=CallsignRegistry)
            rt.callsign_registry.get_callsign.return_value = callsign or ""
        else:
            rt.callsign_registry = MagicMock(spec=CallsignRegistry)  # set first so del works on spec'd mock
            del rt.callsign_registry  # ensure hasattr returns False
        return rt

    @pytest.mark.asyncio
    async def test_recall_query_includes_ward_room_and_callsign(self):
        """Test 1: direct_message recall query starts with 'Ward Room Counselor'."""
        rt = self._make_crew_runtime(callsign="Counselor")
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "What did you post?", "from": "captain"},
            target_agent_id=agent.id,
        )
        obs = await agent.perceive(intent)
        obs = await agent._recall_relevant_memories(intent, obs)

        # Verify the query passed to recall_for_agent
        call_args = rt.episodic_memory.recall_for_agent.call_args
        query = call_args[0][1]  # second positional arg
        assert query.startswith("Ward Room Counselor")
        assert "What did you post?" in query

    @pytest.mark.asyncio
    async def test_recall_query_works_without_callsign_registry(self):
        """Test 2: recall works without callsign_registry (no crash)."""
        rt = self._make_crew_runtime(has_registry=False)
        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "Any updates?", "from": "captain"},
            target_agent_id=agent.id,
        )
        obs = await agent.perceive(intent)
        obs = await agent._recall_relevant_memories(intent, obs)

        rt.episodic_memory.recall_for_agent.assert_called_once()
        call_args = rt.episodic_memory.recall_for_agent.call_args
        query = call_args[0][1]
        assert query.startswith("Ward Room")


class TestMemoryPresentationPreference:
    """BF-029: Tests 3-5 — input preferred over reflection in prompt."""

    def test_dm_prefers_input_over_reflection(self):
        """Test 3: direct_message prompt shows input, not reflection."""
        agent = SampleCogAgent()
        obs = {
            "intent": "direct_message",
            "params": {"text": "What have you been doing?"},
            "recent_memories": [
                {
                    "input": "[Ward Room reply] Counselor: Trust variance noted",
                    "reflection": "Counselor replied in thread 'Status Update'.",
                },
            ],
        }
        msg = agent._build_user_message(obs)
        assert "[Ward Room reply] Counselor: Trust variance noted" in msg
        assert "replied in thread" not in msg

    def test_dm_falls_back_to_reflection_when_input_empty(self):
        """Test 4: Falls back to reflection when input is empty."""
        agent = SampleCogAgent()
        obs = {
            "intent": "direct_message",
            "params": {"text": "Status?"},
            "recent_memories": [
                {"input": "", "reflection": "Counselor observed something."},
            ],
        }
        msg = agent._build_user_message(obs)
        assert "Counselor observed something." in msg

    def test_wr_notification_also_prefers_input(self):
        """Test 5: ward_room_notification prompt also prefers input."""
        agent = SampleCogAgent()
        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "Engineering",
                "author_callsign": "LaForge",
                "title": "EPS Report",
                "author_id": "laforge-1",
            },
            "context": "",
            "recent_memories": [
                {
                    "input": "[Ward Room reply] Counselor: previous EPS insight",
                    "reflection": "Counselor replied in thread 'EPS'.",
                },
            ],
        }
        msg = agent._build_user_message(obs)
        assert "previous EPS insight" in msg
        assert "replied in thread" not in msg


class TestEndToEndWardRoomRecall:
    """BF-029: Tests 9-10 — integration tests."""

    @pytest.mark.asyncio
    async def test_ward_room_episode_recalled_in_dm(self):
        """Test 9: MockEpisodicMemory returns Ward Room episodes in 1:1 recall."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.types import Episode

        mem = MockEpisodicMemory()
        ep = Episode(
            user_input="[Ward Room reply] All Hands — Counselor: I've noticed increased trust variance",
            agent_ids=["counselor-1"],
            reflection="Counselor replied in thread 'Trust Review': I've noticed increased trust variance",
        )
        await mem.store(ep)

        rt = MagicMock(spec=ProbOSRuntime)
        rt.ontology = None  # "counselor" is in legacy crew set
        rt.episodic_memory = mem
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign.return_value = "Counselor"

        llm = MockLLMClient()

        class TestCounselor(CognitiveAgent):
            agent_type = "counselor"
            _handled_intents = {"direct_message"}
            instructions = "You are Counselor."
            intent_descriptors = [
                IntentDescriptor(name="direct_message", params={}, description="DM", tier="domain")
            ]

        agent = TestCounselor(llm_client=llm, runtime=rt)
        # Override id to match the stored episode
        agent.id = "counselor-1"

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "What have you posted in the Ward Room?", "from": "captain"},
            target_agent_id="counselor-1",
        )
        obs = await agent.perceive(intent)
        obs = await agent._recall_relevant_memories(intent, obs)

        assert "recent_memories" in obs
        assert len(obs["recent_memories"]) >= 1
        found = any("trust variance" in m.get("input", "") for m in obs["recent_memories"])
        assert found, f"Expected Ward Room episode in memories, got: {obs['recent_memories']}"

    @pytest.mark.asyncio
    async def test_fallback_still_works_with_enriched_query(self):
        """Test 10: Fallback fires even when enriched query also misses."""
        ep1 = MagicMock()
        ep1.user_input = "Fallback episode"
        ep1.reflection = "Fallback reflection."
        ep1.timestamp = 0
        ep2 = MagicMock()
        ep2.user_input = "Another fallback"
        ep2.reflection = "Another reflection."
        ep2.timestamp = 0

        rt = MagicMock(spec=ProbOSRuntime)
        rt.ontology = MagicMock(spec=VesselOntologyService)
        rt.ontology.get_crew_agent_types.return_value = {"test_cognitive"}
        rt.callsign_registry = MagicMock(spec=CallsignRegistry)
        rt.callsign_registry.get_callsign.return_value = "Bones"
        rt.episodic_memory = MagicMock(spec=EpisodicMemory)
        rt.episodic_memory.recall_for_agent = AsyncMock(return_value=[])
        rt.episodic_memory.recent_for_agent = AsyncMock(return_value=[ep1, ep2])
        rt.episodic_memory.store = AsyncMock()

        llm = MockLLMClient()
        agent = SampleCogAgent(llm_client=llm, runtime=rt)

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "Tell me about your Ward Room posts", "from": "captain"},
            target_agent_id=agent.id,
        )
        obs = await agent.perceive(intent)
        obs = await agent._recall_relevant_memories(intent, obs)

        rt.episodic_memory.recent_for_agent.assert_called_once()
        assert "recent_memories" in obs
        assert len(obs["recent_memories"]) == 2
