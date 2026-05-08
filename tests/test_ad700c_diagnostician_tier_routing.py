"""AD-700c: Diagnostician per-call LLM tier override from level_llm_tier.

Tests the _resolve_tier_for_observation helper and the L4/L5 short-circuit
in CognitiveAgent._decide_via_llm.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_cognitive_agent():
    from probos.cognitive.cognitive_agent import CognitiveAgent

    class TestAgent(CognitiveAgent):
        agent_type = "test_agent"
        instructions = "Test agent for AD-700c."

    agent = TestAgent.__new__(TestAgent)
    agent.instructions = "Test agent for AD-700c."
    agent.agent_type = "test_agent"
    agent.id = "test-agent-001"
    agent.callsign = "TestBot"
    agent.confidence = 0.8
    agent._llm_client = None
    agent._runtime = None
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    agent.tool_context = None
    agent._sub_task_executor = None
    agent._pending_sub_task_chain = None

    from probos.cognitive.agent_working_memory import AgentWorkingMemory

    agent._working_memory = AgentWorkingMemory()
    return agent


def _make_fake_llm_client(captured: dict):
    """Create a fake LLM client that records the tier from each LLMRequest."""

    async def _complete(request, priority=None):
        captured["called"] = True
        captured["tier"] = request.tier
        return MagicMock(
            content="ACTION: respond\nRESPONSE: ok",
            tokens_used=10,
            prompt_tokens=5,
            completion_tokens=5,
            tier=request.tier,
            model="test-model",
            error=None,
        )

    client = MagicMock()
    client.complete = _complete
    return client


# ── _resolve_tier_for_observation unit tests ─────────────────────────


def test_resolve_tier_for_observation_uses_override_string():
    agent = _make_cognitive_agent()
    obs = {"level_llm_tier": "deep", "intent": "diagnose_system"}
    assert agent._resolve_tier_for_observation(obs) == "deep"


def test_resolve_tier_for_observation_explicit_none_returns_empty():
    agent = _make_cognitive_agent()
    obs = {"level_llm_tier": None, "intent": "diagnose_system"}
    assert agent._resolve_tier_for_observation(obs) == ""


def test_resolve_tier_for_observation_missing_falls_back_to_static():
    agent = _make_cognitive_agent()
    obs = {"intent": "medical_alert"}
    assert agent._resolve_tier_for_observation(obs) == "standard"


# ── _decide_via_llm integration ──────────────────────────────────────


@pytest.mark.asyncio
async def test_l1_uses_deep_tier():
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {
        "intent": "diagnose_system",
        "params": {},
        "level_llm_tier": "deep",
        "level": "L1",
        "level_rank": 1,
    }
    result = await agent._decide_via_llm(observation=obs)
    assert captured.get("called") is True
    assert captured.get("tier") == "deep"
    assert result["action"] == "execute"


@pytest.mark.asyncio
async def test_l2_uses_fast_tier():
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {
        "intent": "diagnose_system",
        "params": {},
        "level_llm_tier": "fast",
        "level": "L2",
        "level_rank": 2,
    }
    await agent._decide_via_llm(observation=obs)
    assert captured.get("tier") == "fast"


@pytest.mark.asyncio
async def test_l3_uses_fast_tier():
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {
        "intent": "diagnose_system",
        "params": {},
        "level_llm_tier": "fast",
        "level": "L3",
        "level_rank": 3,
    }
    await agent._decide_via_llm(observation=obs)
    assert captured.get("tier") == "fast"


@pytest.mark.asyncio
async def test_l4_short_circuits_no_llm():
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {
        "intent": "diagnose_system",
        "params": {},
        "level_llm_tier": None,
        "level": "L4",
        "level_rank": 4,
    }
    result = await agent._decide_via_llm(observation=obs)
    assert captured.get("called") is None  # LLM not called
    assert result["action"] == "execute"
    assert result["tier_used"] == "none"
    assert result["short_circuit_reason"] == "ad-700c-no-llm-tier"
    assert result["level"] == "L4"
    assert result["level_rank"] == 4


@pytest.mark.asyncio
async def test_l5_short_circuits_no_llm():
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {
        "intent": "diagnose_system",
        "params": {},
        "level_llm_tier": None,
        "level": "L5",
        "level_rank": 5,
    }
    result = await agent._decide_via_llm(observation=obs)
    assert captured.get("called") is None
    assert result["tier_used"] == "none"
    assert result["level"] == "L5"
    assert result["level_rank"] == 5


@pytest.mark.asyncio
async def test_non_diagnose_intent_uses_static_resolve_tier():
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {"intent": "medical_alert", "params": {}}
    await agent._decide_via_llm(observation=obs)
    assert captured.get("called") is True
    assert captured.get("tier") == "standard"


@pytest.mark.asyncio
async def test_non_diagnose_intent_with_none_tier_still_uses_llm():
    """Defensive scoping: short-circuit only fires for diagnose_system."""
    agent = _make_cognitive_agent()
    captured: dict = {}
    agent._llm_client = _make_fake_llm_client(captured)
    obs = {
        "intent": "medical_alert",
        "params": {},
        "level_llm_tier": None,
    }
    await agent._decide_via_llm(observation=obs)
    assert captured.get("called") is True
    # Static fallback used because override was empty/None
    assert captured.get("tier") == "standard"
