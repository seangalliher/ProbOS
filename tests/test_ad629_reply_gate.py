"""AD-629: Ward Room Reply Gate Enforcement + Post ID Context.

Tests for unified reply cap (check_and_increment_reply_cap),
per-department gate, proactive [REPLY] path enforcement,
post IDs in thread context, post IDs in proactive activity,
and department cleanup.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _make_config(max_per_thread: int = 3):
    """Build a minimal config with ward_room settings."""
    cfg = MagicMock()
    cfg.ward_room.max_agent_responses_per_thread = max_per_thread
    return cfg


def _make_router(
    config=None,
    ontology=None,
    registry=None,
):
    """Build a WardRoomRouter with minimal mocks."""
    from probos.ward_room_router import WardRoomRouter

    config = config or _make_config()
    registry = registry or MagicMock()
    if ontology is None:
        ontology = MagicMock()
        # Default: no department gate (return None so dept gate is transparent)
        ontology.get_agent_department.return_value = None

    router = WardRoomRouter(
        ward_room=MagicMock(),
        registry=registry,
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=ontology,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=config,
        proactive_loop=None,
    )
    return router


# ══════════════════════════════════════════════════════════════════════
# TestCheckAndIncrementReplyCap
# ══════════════════════════════════════════════════════════════════════


class TestCheckAndIncrementReplyCap:
    """Unified reply cap: per-agent + per-department gate."""

    def test_first_reply_allowed(self):
        router = _make_router()
        # First reply to a thread should be allowed
        assert router.check_and_increment_reply_cap("thread-1", "agent-a") is True
        # Counter should be incremented
        assert router._agent_thread_responses["thread-1:agent-a"] == 1

    def test_at_cap_blocked(self):
        router = _make_router(config=_make_config(max_per_thread=2))
        # Use up the cap
        assert router.check_and_increment_reply_cap("thread-1", "agent-a") is True
        assert router.check_and_increment_reply_cap("thread-1", "agent-a") is True
        # Third attempt should be blocked
        assert router.check_and_increment_reply_cap("thread-1", "agent-a") is False
        # Counter should stay at 2 (not incremented on block)
        assert router._agent_thread_responses["thread-1:agent-a"] == 2

    def test_proficiency_override_changes_cap(self):
        """Proficiency override raises/lowers per-agent cap."""
        router = _make_router(config=_make_config(max_per_thread=3))
        # Set up a novice override (cap=1)
        overrides = MagicMock()
        overrides.max_responses_per_thread = 1
        with patch.object(router, '_get_comm_gate_overrides', return_value=overrides):
            assert router.check_and_increment_reply_cap("thread-1", "agent-a") is True
            assert router.check_and_increment_reply_cap("thread-1", "agent-a") is False

    def test_mentioned_agent_still_capped(self):
        """@mention bypasses cooldown but NOT the per-thread cap (AD-629 fix)."""
        router = _make_router(config=_make_config(max_per_thread=2))
        # Use up the cap
        router.check_and_increment_reply_cap("thread-1", "agent-mentioned")
        router.check_and_increment_reply_cap("thread-1", "agent-mentioned")
        # Even though this agent would be @mentioned, cap is enforced
        assert router.check_and_increment_reply_cap("thread-1", "agent-mentioned") is False

    def test_department_gate_first_agent_allowed(self):
        """First agent from a department passes department gate."""
        ontology = MagicMock()
        ontology.get_agent_department.return_value = "engineering"
        registry = MagicMock()
        agent_obj = MagicMock()
        agent_obj.agent_type = "scotty"
        registry.get.return_value = agent_obj

        router = _make_router(ontology=ontology, registry=registry)
        # BF-194: Department gate only fires on department channels.
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=True,
        ) is True
        assert "engineering" in router._dept_thread_responses.get("thread-1", set())

    def test_department_gate_second_agent_blocked(self):
        """Second agent from same department is blocked (first responder wins)."""
        ontology = MagicMock()
        ontology.get_agent_department.return_value = "engineering"
        registry = MagicMock()
        agent_a = MagicMock()
        agent_a.agent_type = "scotty"
        agent_b = MagicMock()
        agent_b.agent_type = "laforge"
        registry.get.side_effect = lambda aid: agent_a if aid == "agent-scotty" else agent_b

        router = _make_router(ontology=ontology, registry=registry)
        # BF-194: Department gate only fires on department channels.
        # First agent from engineering
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-scotty", is_department_channel=True,
        ) is True
        # Second agent from engineering — blocked by department gate
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-laforge", is_department_channel=True,
        ) is False

    def test_different_departments_both_allowed(self):
        """Agents from different departments both pass."""
        ontology = MagicMock()
        registry = MagicMock()

        agent_eng = MagicMock()
        agent_eng.agent_type = "scotty"
        agent_sci = MagicMock()
        agent_sci.agent_type = "dax"

        def dept_lookup(agent_type):
            return {"scotty": "engineering", "dax": "science"}.get(agent_type)

        ontology.get_agent_department.side_effect = dept_lookup
        registry.get.side_effect = lambda aid: agent_eng if aid == "agent-eng" else agent_sci

        router = _make_router(ontology=ontology, registry=registry)
        # BF-194: Department gate only fires on department channels.
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-eng", is_department_channel=True,
        ) is True
        assert router.check_and_increment_reply_cap(
            "thread-1", "agent-sci", is_department_channel=True,
        ) is True

    def test_counter_survives_across_calls(self):
        """Multiple calls accumulate the counter."""
        router = _make_router(config=_make_config(max_per_thread=5))
        for i in range(5):
            assert router.check_and_increment_reply_cap("thread-1", "agent-a") is True
        assert router._agent_thread_responses["thread-1:agent-a"] == 5
        assert router.check_and_increment_reply_cap("thread-1", "agent-a") is False


# ══════════════════════════════════════════════════════════════════════
# TestProactiveReplyCapIntegration
# ══════════════════════════════════════════════════════════════════════


class TestProactiveReplyCapIntegration:
    """Proactive [REPLY] path calls unified cap."""

    @pytest.mark.asyncio
    async def test_proactive_reply_checks_cap(self):
        """[REPLY] path should call check_and_increment_reply_cap."""
        # Build a minimal proactive loop mock
        from probos.proactive import ProactiveCognitiveLoop

        loop = MagicMock(spec=ProactiveCognitiveLoop)
        loop._runtime = MagicMock()
        loop._reply_cooldowns = {}

        # Mock ward_room_router on runtime
        wr_router = MagicMock()
        wr_router.check_and_increment_reply_cap.return_value = True
        loop._runtime.ward_room_router = wr_router
        loop._runtime.ward_room = AsyncMock()
        loop._runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"locked": False, "channel_id": "ch-1"},
            "posts": [],
        })
        loop._runtime.ward_room.create_post = AsyncMock()
        loop._runtime.callsign_registry = MagicMock()
        loop._runtime.callsign_registry.get_callsign.return_value = "Scotty"

        agent = MagicMock()
        agent.id = "agent-scotty"
        agent.agent_type = "scotty"

        text = "[REPLY thread-abc] Engines are nominal. [/REPLY]"

        # Call the real method
        real_method = ProactiveCognitiveLoop._extract_and_execute_replies
        # We need to mock _resolve_thread_id and _is_similar_to_recent_posts
        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")
        loop._is_similar_to_recent_posts = AsyncMock(return_value=False)
        loop._extract_commands_from_reply = AsyncMock(return_value=("Engines are nominal.", []))
        loop._get_comm_gate_overrides = MagicMock(return_value=None)

        cleaned, actions = await real_method(loop, agent, text)

        # Cap check should have been called (BF-194: with channel-type kwarg)
        wr_router.check_and_increment_reply_cap.assert_called_once()
        _args, _kwargs = wr_router.check_and_increment_reply_cap.call_args
        assert _args == ("thread-abc", "agent-scotty")
        assert "is_department_channel" in _kwargs

    @pytest.mark.asyncio
    async def test_proactive_reply_blocked_at_cap(self):
        """Reply is suppressed when cap check returns False."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = MagicMock(spec=ProactiveCognitiveLoop)
        loop._runtime = MagicMock()
        loop._reply_cooldowns = {}

        wr_router = MagicMock()
        wr_router.check_and_increment_reply_cap.return_value = False  # CAP HIT
        loop._runtime.ward_room_router = wr_router
        loop._runtime.ward_room = AsyncMock()
        loop._runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"locked": False, "channel_id": "ch-1"},
            "posts": [],
        })
        loop._runtime.ward_room.create_post = AsyncMock()

        agent = MagicMock()
        agent.id = "agent-scotty"
        agent.agent_type = "scotty"

        text = "[REPLY thread-abc] Engines are nominal. [/REPLY]"
        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")
        loop._is_similar_to_recent_posts = AsyncMock(return_value=False)
        loop._get_comm_gate_overrides = MagicMock(return_value=None)

        real_method = ProactiveCognitiveLoop._extract_and_execute_replies
        cleaned, actions = await real_method(loop, agent, text)

        # Post should NOT have been created
        loop._runtime.ward_room.create_post.assert_not_called()
        # No reply actions
        assert not any(a.get("type") == "reply" for a in actions)


# ══════════════════════════════════════════════════════════════════════
# TestPostIdInContext
# ══════════════════════════════════════════════════════════════════════


class TestPostIdInContext:
    """Post IDs in thread context and proactive activity."""

    @pytest.mark.asyncio
    async def test_thread_context_includes_post_ids(self):
        """Thread context format: [id[:8]] callsign: body."""
        router = _make_router()
        # Build thread detail with posts that have IDs
        thread_detail = {
            "thread": {
                "title": "Test Thread",
                "body": "Root post body",
            },
            "posts": [
                {
                    "id": "abcdef12-3456-7890-abcd-ef1234567890",
                    "author_callsign": "Scotty",
                    "body": "Engines nominal",
                },
                {
                    "id": "12345678-abcd-ef12-3456-7890abcdef12",
                    "author_callsign": "LaForge",
                    "body": "Confirmed",
                },
            ],
        }

        # Simulate the thread context building logic
        posts = thread_detail["posts"]
        thread_context = f"Thread: {thread_detail['thread']['title']}\n{thread_detail['thread']['body']}"
        recent_posts = posts[-5:] if len(posts) > 5 else posts
        for p in recent_posts:
            p_id = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
            p_callsign = p.get("author_callsign", "") if isinstance(p, dict) else getattr(p, "author_callsign", "")
            p_body = p.get("body", "") if isinstance(p, dict) else getattr(p, "body", "")
            _id_prefix = f"[{p_id[:8]}] " if p_id else ""
            thread_context += f"\n{_id_prefix}{p_callsign}: {p_body}"

        assert "[abcdef12] Scotty: Engines nominal" in thread_context
        assert "[12345678] LaForge: Confirmed" in thread_context

    def test_proactive_activity_includes_post_ids(self):
        """Ward Room activity body field includes [post_id[:8]] prefix."""
        activity = [
            {
                "type": "post",
                "author": "Scotty",
                "title": "Status update",
                "body": "Engines nominal",
                "net_score": 2,
                "post_id": "abcdef12-3456-7890-abcd-ef1234567890",
                "thread_id": "thread-1",
                "created_at": 1000.0,
            },
        ]

        # Simulate the AD-629 body formatting
        formatted = []
        for a in activity:
            pid = a.get("post_id", a.get("id", "")) or ""
            body = (f"[{pid[:8]}] " if pid else "") + (a.get("title", a.get("body", ""))[:500])
            formatted.append(body)

        assert formatted[0] == "[abcdef12] Status update"

    def test_activity_without_post_id_no_prefix(self):
        """Activity items without post_id get no prefix."""
        activity = [
            {
                "type": "post",
                "author": "Scotty",
                "body": "Engines nominal",
                "net_score": 0,
                "post_id": "",
                "thread_id": "thread-1",
                "created_at": 1000.0,
            },
        ]

        pid = activity[0].get("post_id", activity[0].get("id", "")) or ""
        body = (f"[{pid[:8]}] " if pid else "") + (activity[0].get("body", "")[:500])
        assert body == "Engines nominal"


# ══════════════════════════════════════════════════════════════════════
# TestDepartmentCleanup
# ══════════════════════════════════════════════════════════════════════


class TestDepartmentCleanup:
    """Cleanup method clears department tracking state."""

    def test_dept_responses_cleaned_with_thread(self):
        """cleanup_tracking removes _dept_thread_responses for pruned threads."""
        router = _make_router()
        # Pre-populate tracking state
        router._dept_thread_responses["thread-1"] = {"engineering", "science"}
        router._dept_thread_responses["thread-2"] = {"medical"}
        router._agent_thread_responses["thread-1:agent-a"] = 2
        router._agent_thread_responses["thread-2:agent-b"] = 1
        router._thread_rounds["thread-1"] = 3

        # Prune thread-1
        router.cleanup_tracking({"thread-1"})

        # thread-1 state should be gone
        assert "thread-1" not in router._dept_thread_responses
        assert "thread-1:agent-a" not in router._agent_thread_responses
        assert "thread-1" not in router._thread_rounds
        # thread-2 state should remain
        assert "thread-2" in router._dept_thread_responses
        assert "thread-2:agent-b" in router._agent_thread_responses
