"""AD-632f: Sub-Task Chain Activation Triggers — unit tests.

Tests cover: gate logic, chain construction, decide() integration,
skill injection, SubTaskExecutor.enabled, and config defaults.

Target: 25-35 tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    _CHAIN_ELIGIBLE_INTENTS,
    _DECISION_CACHES,
)
from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskExecutor,
    SubTaskSpec,
    SubTaskType,
)
from probos.config import SubTaskConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(**overrides: Any) -> CognitiveAgent:
    """Create a minimal CognitiveAgent for testing with decide() gates mocked."""
    kwargs = {
        "agent_type": "science_officer",
        "instructions": "Test instructions.",
        "llm_client": MagicMock(),
    }
    kwargs.update(overrides)
    agent = CognitiveAgent(**kwargs)
    # Mock procedural memory so decide() doesn't short-circuit at Level 1
    agent._check_procedural_memory = AsyncMock(return_value=None)
    return agent


def _make_executor(enabled: bool = True) -> MagicMock:
    """Mock SubTaskExecutor with configurable enabled state."""
    executor = MagicMock(spec=SubTaskExecutor)
    executor.enabled = enabled
    executor.can_execute.return_value = True
    return executor


# ===========================================================================
# _should_activate_chain() gate logic
# ===========================================================================


class TestShouldActivateChain:
    """Gate evaluation in _should_activate_chain()."""

    def test_gate_disabled_config(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=False)
        assert agent._should_activate_chain({"intent": "ward_room_notification"}) is False

    def test_gate_no_executor(self):
        agent = _make_agent()
        agent._sub_task_executor = None
        assert agent._should_activate_chain({"intent": "ward_room_notification"}) is False

    def test_gate_ward_room_eligible(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        assert agent._should_activate_chain({"intent": "ward_room_notification"}) is True

    def test_gate_proactive_eligible(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        assert agent._should_activate_chain({"intent": "proactive_think"}) is True

    def test_gate_dm_not_eligible(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        assert agent._should_activate_chain({"intent": "direct_message"}) is False

    def test_gate_unknown_intent(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        assert agent._should_activate_chain({"intent": "scout_search"}) is False

    def test_gate_empty_intent(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        assert agent._should_activate_chain({}) is False


# ===========================================================================
# _build_chain_for_intent() chain construction
# ===========================================================================


class TestBuildChainForIntent:
    """Chain construction based on intent type."""

    def test_ward_room_chain_structure(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "ward_room_notification"})
        assert chain is not None
        assert len(chain.steps) == 5  # AD-632e: Q→A→C→E→R
        assert chain.steps[0].sub_task_type == SubTaskType.QUERY
        assert chain.steps[1].sub_task_type == SubTaskType.ANALYZE
        assert chain.steps[2].sub_task_type == SubTaskType.COMPOSE
        assert chain.steps[3].sub_task_type == SubTaskType.EVALUATE
        assert chain.steps[4].sub_task_type == SubTaskType.REFLECT

    def test_ward_room_chain_query_keys(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "ward_room_notification"})
        assert "thread_metadata" in chain.steps[0].context_keys
        assert "credibility" in chain.steps[0].context_keys

    def test_ward_room_chain_analyze_mode(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "ward_room_notification"})
        assert chain.steps[1].prompt_template == "thread_analysis"

    def test_ward_room_chain_compose_mode(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "ward_room_notification"})
        assert chain.steps[2].prompt_template == "ward_room_response"

    def test_ward_room_chain_source(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "ward_room_notification"})
        assert "ward_room_notification" in chain.source

    def test_proactive_chain_structure(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "proactive_think"})
        assert chain is not None
        assert len(chain.steps) == 5  # AD-632e: Q→A→C→E→R
        assert chain.steps[0].sub_task_type == SubTaskType.QUERY
        assert chain.steps[1].sub_task_type == SubTaskType.ANALYZE
        assert chain.steps[2].sub_task_type == SubTaskType.COMPOSE
        assert chain.steps[3].sub_task_type == SubTaskType.EVALUATE
        assert chain.steps[4].sub_task_type == SubTaskType.REFLECT

    def test_proactive_chain_query_keys(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "proactive_think"})
        assert "unread_counts" in chain.steps[0].context_keys
        assert "trust_score" in chain.steps[0].context_keys

    def test_proactive_chain_analyze_mode(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "proactive_think"})
        assert chain.steps[1].prompt_template == "situation_review"

    def test_proactive_chain_compose_mode(self):
        agent = _make_agent()
        chain = agent._build_chain_for_intent({"intent": "proactive_think"})
        assert chain.steps[2].prompt_template == "proactive_observation"

    def test_unknown_intent_returns_none(self):
        agent = _make_agent()
        result = agent._build_chain_for_intent({"intent": "direct_message"})
        assert result is None

    def test_empty_intent_returns_none(self):
        agent = _make_agent()
        result = agent._build_chain_for_intent({})
        assert result is None


# ===========================================================================
# Integration with decide()
# ===========================================================================


class TestDecideIntegration:
    """Chain activation within decide() flow."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear module-level decision cache between tests."""
        _DECISION_CACHES.clear()
        yield
        _DECISION_CACHES.clear()

    @pytest.mark.asyncio
    async def test_decide_activates_chain_for_ward_room(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        chain_decision = {
            "action": "execute",
            "llm_output": "test",
            "tier_used": "standard",
            "sub_task_chain": True,
        }
        agent._execute_sub_task_chain = AsyncMock(return_value=chain_decision)
        agent._load_augmentation_skills = MagicMock(return_value="")
        agent._decide_via_llm = AsyncMock()

        obs = {"intent": "ward_room_notification", "context": "test"}
        result = await agent.decide(obs)

        agent._execute_sub_task_chain.assert_awaited_once()
        agent._decide_via_llm.assert_not_awaited()
        assert result["sub_task_chain"] is True

    @pytest.mark.asyncio
    async def test_decide_falls_through_on_chain_failure(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        agent._execute_sub_task_chain = AsyncMock(return_value=None)
        agent._load_augmentation_skills = MagicMock(return_value="")
        fallback = {"action": "wait", "llm_output": "fallback"}
        agent._decide_via_llm = AsyncMock(return_value=fallback)

        obs = {"intent": "ward_room_notification", "context": "test"}
        result = await agent.decide(obs)

        agent._execute_sub_task_chain.assert_awaited_once()
        agent._decide_via_llm.assert_awaited_once()
        assert result["llm_output"] == "fallback"

    @pytest.mark.asyncio
    async def test_decide_prefers_external_chain(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        external_chain = SubTaskChain(
            steps=[
                SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="ext-query"),
            ],
            source="external",
        )
        agent._pending_sub_task_chain = external_chain
        chain_decision = {"action": "execute", "sub_task_chain": True}
        agent._execute_sub_task_chain = AsyncMock(return_value=chain_decision)
        agent._load_augmentation_skills = MagicMock(return_value="")

        obs = {"intent": "ward_room_notification", "context": "test"}
        result = await agent.decide(obs)

        # External chain should have been consumed
        assert agent._pending_sub_task_chain is None
        # The chain passed to execute should be the external one
        call_args = agent._execute_sub_task_chain.call_args
        passed_chain = call_args[0][0]
        assert passed_chain.source == "external"

    @pytest.mark.asyncio
    async def test_decide_single_call_when_disabled(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=False)
        fallback = {"action": "wait", "llm_output": "single"}
        agent._decide_via_llm = AsyncMock(return_value=fallback)

        obs = {"intent": "ward_room_notification", "context": "test"}
        result = await agent.decide(obs)

        agent._decide_via_llm.assert_awaited_once()
        assert result["llm_output"] == "single"

    @pytest.mark.asyncio
    async def test_decide_single_call_for_dm(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        agent._execute_sub_task_chain = AsyncMock()
        fallback = {"action": "wait", "llm_output": "dm-reply"}
        agent._decide_via_llm = AsyncMock(return_value=fallback)

        obs = {"intent": "direct_message", "context": "test"}
        result = await agent.decide(obs)

        agent._execute_sub_task_chain.assert_not_awaited()
        assert result["llm_output"] == "dm-reply"


# ===========================================================================
# Skill injection
# ===========================================================================


class TestSkillInjection:
    """Skills loaded before chain activation for Compose handler."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _DECISION_CACHES.clear()
        yield
        _DECISION_CACHES.clear()

    @pytest.mark.asyncio
    async def test_skills_loaded_before_chain(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        agent._load_augmentation_skills = MagicMock(return_value="Skill instructions here.")
        chain_decision = {"action": "execute", "sub_task_chain": True}
        agent._execute_sub_task_chain = AsyncMock(return_value=chain_decision)

        obs = {"intent": "ward_room_notification", "context": "test"}
        await agent.decide(obs)

        agent._load_augmentation_skills.assert_called_once()
        # The observation passed to chain should have skill instructions
        call_args = agent._execute_sub_task_chain.call_args
        passed_obs = call_args[0][1]
        assert passed_obs.get("_augmentation_skill_instructions") == "Skill instructions here."

    @pytest.mark.asyncio
    async def test_no_skill_loading_for_ineligible_intent(self):
        agent = _make_agent()
        agent._sub_task_executor = _make_executor(enabled=True)
        agent._load_augmentation_skills = MagicMock(return_value="")
        fallback = {"action": "wait"}
        agent._decide_via_llm = AsyncMock(return_value=fallback)

        obs = {"intent": "direct_message", "context": "test"}
        await agent.decide(obs)

        # _load_augmentation_skills should NOT be called for chain preload
        # (it may still be called inside _decide_via_llm, but we mocked that)
        # The key check: observation should NOT have _augmentation_skill_instructions
        # from the chain preload path
        assert "_augmentation_skill_instructions" not in obs


# ===========================================================================
# SubTaskExecutor.enabled property
# ===========================================================================


class TestExecutorEnabled:
    """SubTaskExecutor.enabled property."""

    def test_executor_enabled_default(self):
        config = SubTaskConfig()  # enabled=True after AD-632f
        executor = SubTaskExecutor(config=config)
        assert executor.enabled is True

    def test_executor_enabled_false(self):
        config = SubTaskConfig(enabled=False)
        executor = SubTaskExecutor(config=config)
        assert executor.enabled is False

    def test_executor_enabled_no_config(self):
        executor = SubTaskExecutor(config=None)
        assert executor.enabled is False


# ===========================================================================
# Config
# ===========================================================================


class TestConfig:
    """SubTaskConfig defaults after AD-632f."""

    def test_subtask_config_default_enabled(self):
        config = SubTaskConfig()
        assert config.enabled is True

    def test_subtask_config_explicit_false(self):
        config = SubTaskConfig(enabled=False)
        assert config.enabled is False


# ===========================================================================
# Module-level frozenset
# ===========================================================================


class TestChainEligibleIntents:
    """Verify _CHAIN_ELIGIBLE_INTENTS contents."""

    def test_contains_ward_room(self):
        assert "ward_room_notification" in _CHAIN_ELIGIBLE_INTENTS

    def test_contains_proactive(self):
        assert "proactive_think" in _CHAIN_ELIGIBLE_INTENTS

    def test_does_not_contain_dm(self):
        assert "direct_message" not in _CHAIN_ELIGIBLE_INTENTS

    def test_is_frozenset(self):
        assert isinstance(_CHAIN_ELIGIBLE_INTENTS, frozenset)
