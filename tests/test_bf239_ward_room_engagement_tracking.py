"""BF-239: Ward Room thread engagement tracking via working memory.

Tests that agents use ActiveEngagement in working memory to track
in-flight ward room replies and suppress duplicate dispatch for
the same thread. Verifies engagement lifecycle (add/check/remove),
gate bypasses (@mention, DM), and try/finally cleanup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.agent_working_memory import (
    ActiveEngagement,
    AgentWorkingMemory,
)
from probos.types import IntentMessage, IntentResult


# ── Helpers ──────────────────────────────────────────────────────────


def _make_agent(callsign: str = "TestAgent") -> "CognitiveAgent":
    """Create a CognitiveAgent with enough state for handle_intent."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = "agent-test-1"
    agent.agent_type = "test_agent"
    agent._callsign = callsign
    agent.callsign = callsign
    agent._model_id = "test"
    agent._system_prompt_base = ""
    agent._max_tokens = 1000
    agent._runtime = None
    agent.confidence = 0.5
    agent._handled_intents = {"ward_room_notification", "direct_message"}
    agent._skills = {}
    agent._cognitive_skill_catalog = None
    agent._skill_bridge = None
    agent._skill_profile = None
    agent._working_memory = AgentWorkingMemory()
    agent._recent_compounds = {}  # AD-618b
    agent._billet_registry = None  # AD-618b
    return agent


def _make_ward_room_intent(
    thread_id: str = "thread-1",
    was_mentioned: bool = False,
    is_dm_channel: bool = False,
    channel_name: str = "general",
) -> IntentMessage:
    """Build a ward_room_notification IntentMessage."""
    return IntentMessage(
        intent="ward_room_notification",
        params={
            "thread_id": thread_id,
            "channel_name": channel_name,
            "event_type": "ward_room_post_created",
            "was_mentioned": was_mentioned,
            "is_dm_channel": is_dm_channel,
        },
        target_agent_id="agent-test-1",
    )


def _make_dm_intent() -> IntentMessage:
    return IntentMessage(
        intent="direct_message",
        params={"text": "hello", "thread_id": "dm-thread-1"},
        target_agent_id="agent-test-1",
    )


async def _mock_lifecycle(self, intent, csi=None, se=None) -> IntentResult:
    """Replacement for _run_cognitive_lifecycle that returns a normal result."""
    return IntentResult(
        intent_id=intent.id,
        agent_id=self.id,
        success=True,
        result="Test response",
        confidence=0.5,
    )


async def _mock_lifecycle_no_response(self, intent, csi=None, se=None) -> IntentResult:
    """Lifecycle that returns [NO_RESPONSE] (agent chose silence)."""
    return IntentResult(
        intent_id=intent.id,
        agent_id=self.id,
        success=True,
        result="[NO_RESPONSE]",
        confidence=0.5,
    )


async def _mock_lifecycle_raises(self, intent, csi=None, se=None) -> IntentResult:
    """Lifecycle that raises an exception (simulates perceive/decide failure)."""
    raise RuntimeError("simulated lifecycle failure")


# ── Unit tests on AgentWorkingMemory ──────────────────────────────


class TestHasThreadEngagement:
    """Tests 9, 10, 10b — unit tests on AgentWorkingMemory."""

    def test_returns_true_for_matching_thread(self):
        """Test 10b: namespaced engagement_id accepted by add/remove."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying to thread",
            state={"thread_id": "thread-1"},
        ))
        assert wm.has_thread_engagement("thread-1")

    def test_returns_false_for_wrong_thread(self):
        """Test 9: engagement for thread-1 doesn't match thread-2."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying to thread",
            state={"thread_id": "thread-1"},
        ))
        assert not wm.has_thread_engagement("thread-2")

    def test_returns_false_for_wrong_type(self):
        """Test 10: game engagement with same key doesn't match."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="game",
            engagement_id="ward_room:thread-1",
            summary="Playing game",
            state={},
        ))
        assert not wm.has_thread_engagement("thread-1")

    def test_returns_false_when_empty(self):
        wm = AgentWorkingMemory()
        assert not wm.has_thread_engagement("thread-1")

    def test_remove_clears_engagement(self):
        """Test 10b continued: remove_engagement clears has_thread_engagement."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying",
            state={"thread_id": "thread-1"},
        ))
        assert wm.has_thread_engagement("thread-1")
        wm.remove_engagement("ward_room:thread-1")
        assert not wm.has_thread_engagement("thread-1")


# ── Integration tests on handle_intent ────────────────────────────


class TestEngagementGate:
    """Tests 1-8, 11, 12 — full handle_intent integration."""

    @pytest.mark.asyncio
    async def test_first_notification_proceeds(self):
        """Test 1: first notification for thread proceeds normally."""
        agent = _make_agent()
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            result = await agent.handle_intent(_make_ward_room_intent())
        assert result is not None
        assert result.success
        assert result.result == "Test response"

    @pytest.mark.asyncio
    async def test_second_notification_returns_no_response(self):
        """Test 2: second notification for same thread returns [NO_RESPONSE].

        Simulates the serial queue: first call completes (engagement
        registered+removed), then we manually add the engagement back
        to simulate it being present when the second call arrives.
        """
        agent = _make_agent()
        # Pre-register engagement (simulates agent currently processing thread-1)
        agent._working_memory.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying",
            state={"thread_id": "thread-1"},
        ))
        result = await agent.handle_intent(_make_ward_room_intent("thread-1"))
        assert result is not None
        assert result.success
        assert result.result == "[NO_RESPONSE]"

    @pytest.mark.asyncio
    async def test_second_notification_skips_perceive(self):
        """Test 2 (continued): perceive() is NOT called on the gated path."""
        agent = _make_agent()
        agent.perceive = AsyncMock()
        agent._working_memory.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying",
            state={"thread_id": "thread-1"},
        ))
        await agent.handle_intent(_make_ward_room_intent("thread-1"))
        agent.perceive.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_thread_proceeds(self):
        """Test 3: different thread_id proceeds normally."""
        agent = _make_agent()
        agent._working_memory.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying",
            state={"thread_id": "thread-1"},
        ))
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            result = await agent.handle_intent(_make_ward_room_intent("thread-2"))
        assert result is not None
        assert result.result == "Test response"

    @pytest.mark.asyncio
    async def test_mentioned_bypasses_gate(self):
        """Test 4: @mentioned agent bypasses engagement gate."""
        agent = _make_agent()
        agent._working_memory.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying",
            state={"thread_id": "thread-1"},
        ))
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            result = await agent.handle_intent(
                _make_ward_room_intent("thread-1", was_mentioned=True)
            )
        assert result is not None
        assert result.result == "Test response"

    @pytest.mark.asyncio
    async def test_dm_channel_bypasses_gate(self):
        """Test 5: DM channel bypasses engagement gate."""
        agent = _make_agent()
        agent._working_memory.add_engagement(ActiveEngagement(
            engagement_type="ward_room_reply",
            engagement_id="ward_room:thread-1",
            summary="Replying",
            state={"thread_id": "thread-1"},
        ))
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            result = await agent.handle_intent(
                _make_ward_room_intent("thread-1", is_dm_channel=True)
            )
        assert result is not None
        assert result.result == "Test response"

    @pytest.mark.asyncio
    async def test_engagement_removed_after_success(self):
        """Test 6: engagement removed after successful post."""
        agent = _make_agent()
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            await agent.handle_intent(_make_ward_room_intent("thread-1"))
        assert not agent._working_memory.has_thread_engagement("thread-1")

    @pytest.mark.asyncio
    async def test_engagement_removed_after_no_response(self):
        """Test 7: engagement removed after [NO_RESPONSE] decision."""
        agent = _make_agent()
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle_no_response):
            await agent.handle_intent(_make_ward_room_intent("thread-1"))
        assert not agent._working_memory.has_thread_engagement("thread-1")

    @pytest.mark.asyncio
    async def test_engagement_removed_on_exception(self):
        """Test 7b: engagement removed on lifecycle exception (finally path)."""
        agent = _make_agent()
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle_raises):
            with pytest.raises(RuntimeError, match="simulated lifecycle failure"):
                await agent.handle_intent(_make_ward_room_intent("thread-1"))
        assert not agent._working_memory.has_thread_engagement("thread-1")

    @pytest.mark.asyncio
    async def test_non_ward_room_no_engagement(self):
        """Test 8: direct_message doesn't create engagement."""
        agent = _make_agent()
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            await agent.handle_intent(_make_dm_intent())
        assert not agent._working_memory.has_engagement("ward_room_reply")
        assert len(agent._working_memory._active_engagements) == 0

    @pytest.mark.asyncio
    async def test_subsequent_dispatch_after_cleanup(self):
        """Test 11: after lifecycle exit, same thread proceeds again."""
        agent = _make_agent()
        with patch.object(type(agent), "_run_cognitive_lifecycle", _mock_lifecycle):
            # First dispatch
            r1 = await agent.handle_intent(_make_ward_room_intent("thread-1"))
            assert r1.result == "Test response"
            # Engagement should be cleared
            assert not agent._working_memory.has_thread_engagement("thread-1")
            # Second dispatch for same thread should proceed
            r2 = await agent.handle_intent(_make_ward_room_intent("thread-1"))
            assert r2.result == "Test response"

    @pytest.mark.asyncio
    async def test_engagement_exists_during_lifecycle(self):
        """Test 12: engagement is live during perceive/decide."""
        agent = _make_agent()
        engagement_checks: list[bool] = []

        async def _check_engagement_lifecycle(self_inner, intent, csi=None, se=None):
            engagement_checks.append(
                self_inner._working_memory.has_thread_engagement("thread-1")
            )
            return IntentResult(
                intent_id=intent.id,
                agent_id=self_inner.id,
                success=True,
                result="Test response",
                confidence=0.5,
            )

        with patch.object(type(agent), "_run_cognitive_lifecycle", _check_engagement_lifecycle):
            await agent.handle_intent(_make_ward_room_intent("thread-1"))

        assert engagement_checks == [True]
        # But cleaned up after
        assert not agent._working_memory.has_thread_engagement("thread-1")


# ── _summarize_action tests ──────────────────────────────────────


class TestSummarizeActionThreadId:
    """Section 5: _summarize_action includes thread_id."""

    def test_includes_thread_id(self):
        agent = _make_agent()
        intent = _make_ward_room_intent("abcdef123456")
        decision = {"llm_output": "My analysis is..."}
        result = agent._summarize_action(intent, decision, {"success": True})
        assert "(thread abcdef12)" in result
        assert "#general" in result

    def test_no_thread_id_no_tag(self):
        agent = _make_agent()
        intent = _make_ward_room_intent("")
        decision = {"llm_output": "My response"}
        result = agent._summarize_action(intent, decision, {"success": True})
        assert "(thread" not in result
        assert "#general" in result
