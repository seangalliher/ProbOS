"""Tests for BF-102: Newly commissioned agents don't know they're new.

Validates:
- Temporal context includes commissioning note for young agents (< 300s)
- Temporal context omits commissioning note for older agents (> 300s)
- Commissioning note includes self-awareness language
- Cold-start system note appears in ward_room_notification
- Cold-start system note absent when not cold start
- No crash when _birth_timestamp is missing
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    """Clear CognitiveAgent decision cache between tests to prevent pollution."""
    from probos.cognitive.cognitive_agent import _DECISION_CACHES

    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()


def _make_agent(**overrides) -> CognitiveAgent:
    """Create a bare CognitiveAgent for testing temporal context."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._runtime = None
    agent.callsign = ""
    agent.agent_type = "data_analyst"
    agent.id = "sci_data_analyst_0_abc12345"
    agent.meta = SimpleNamespace(last_active=None)
    agent._birth_timestamp = None
    agent._system_start_time = None
    agent._recent_post_count = None
    for k, v in overrides.items():
        setattr(agent, k, v)
    return agent


# -----------------------------------------------------------------------
# Temporal context commissioning awareness
# -----------------------------------------------------------------------


class TestCommissioningAwareness:
    """BF-102: Temporal context includes commissioning note for new crew."""

    def test_includes_commissioning_note(self):
        """Agent with birth < 300s ago gets commissioning awareness line."""
        agent = _make_agent(_birth_timestamp=time.time() - 60)  # 60s old
        ctx = agent._build_temporal_context()
        assert "You were commissioned" in ctx
        assert "newly arrived crew member" in ctx

    def test_no_commissioning_after_threshold(self):
        """Agent with birth > 300s ago does NOT get commissioning line."""
        agent = _make_agent(_birth_timestamp=time.time() - 600)  # 10 min old
        ctx = agent._build_temporal_context()
        assert "You were commissioned" not in ctx
        assert "newly arrived crew member" not in ctx

    def test_commissioning_note_mentions_self_awareness(self):
        """The commissioning line includes language about recognizing one's own name."""
        agent = _make_agent(_birth_timestamp=time.time() - 30)  # 30s old
        ctx = agent._build_temporal_context()
        assert "respond as yourself" in ctx

    def test_no_birth_timestamp(self):
        """Agent without _birth_timestamp skips commissioning check entirely."""
        agent = _make_agent()  # _birth_timestamp=None by default
        ctx = agent._build_temporal_context()
        assert "You were commissioned" not in ctx
        # Should not crash
        assert "Current time:" in ctx

    def test_exact_threshold_boundary(self):
        """Agent at exactly 300s should NOT get commissioning line (age >= 300)."""
        # Use 301 to avoid race: time.time() drift during execution
        # can make age < 300 when set to exactly 300.
        agent = _make_agent(_birth_timestamp=time.time() - 301)
        ctx = agent._build_temporal_context()
        assert "You were commissioned" not in ctx


# -----------------------------------------------------------------------
# Cold-start system note in ward_room_notification
# -----------------------------------------------------------------------


class TestColdStartNoteInWardRoom:
    """BF-102: Ward Room notification includes cold-start system note."""

    @pytest.mark.asyncio
    async def test_cold_start_note_present(self):
        """When runtime.is_cold_start is True, ward_room message includes system note."""
        rt = SimpleNamespace(is_cold_start=True)
        agent = _make_agent(_runtime=rt)
        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "All Hands",
                "author_callsign": "Captain",
                "title": "Welcome Aboard",
                "author_id": "captain",
            },
        }
        msg = await agent._build_user_message(obs)
        assert "SYSTEM NOTE" in msg
        assert "fresh start" in msg
        assert "Do not reference or invent past experiences" in msg

    @pytest.mark.asyncio
    async def test_cold_start_note_absent(self):
        """When runtime.is_cold_start is False, no system note in ward_room message."""
        rt = SimpleNamespace(is_cold_start=False)
        agent = _make_agent(_runtime=rt)
        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "All Hands",
                "author_callsign": "Captain",
                "title": "Welcome Aboard",
                "author_id": "captain",
            },
        }
        msg = await agent._build_user_message(obs)
        assert "SYSTEM NOTE" not in msg

    @pytest.mark.asyncio
    async def test_cold_start_note_absent_no_runtime(self):
        """When _runtime is None, no system note in ward_room message (no crash)."""
        agent = _make_agent(_runtime=None)
        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "All Hands",
                "author_callsign": "Captain",
                "title": "Welcome Aboard",
                "author_id": "captain",
            },
        }
        msg = await agent._build_user_message(obs)
        assert "SYSTEM NOTE" not in msg


# -----------------------------------------------------------------------
# Integration: new agent ward room context
# -----------------------------------------------------------------------


class TestNewAgentWardRoomContext:
    """Integration: new agent with commissioning context in ward room notification."""

    @pytest.mark.asyncio
    async def test_new_agent_gets_both_contexts(self):
        """New agent (birth < 300s, cold start) gets commissioning + system note."""
        rt = SimpleNamespace(is_cold_start=True)
        agent = _make_agent(
            _birth_timestamp=time.time() - 60,
            _runtime=rt,
        )
        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "All Hands",
                "author_callsign": "Captain",
                "title": "Welcome New Crew",
                "author_id": "captain",
            },
        }
        msg = await agent._build_user_message(obs)
        # Should have commissioning awareness (from temporal context)
        assert "You were commissioned" in msg
        assert "respond as yourself" in msg
        # Should have cold-start note
        assert "SYSTEM NOTE" in msg
