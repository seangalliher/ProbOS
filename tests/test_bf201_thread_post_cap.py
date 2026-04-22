"""BF-201: Simplify Thread Caps — Tests.

Remove per-agent & department gate, add thread post cap (50),
raise agent-only round depth 3→5.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.config import WardRoomConfig, SystemConfig
from probos.ward_room_router import WardRoomRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router(**overrides) -> WardRoomRouter:
    config = overrides.pop("config", SystemConfig())
    ward_room = overrides.pop("ward_room", AsyncMock())
    registry = overrides.pop("registry", None)
    if registry is None:
        registry = MagicMock()
        registry.get = MagicMock(return_value=None)

    return WardRoomRouter(
        ward_room=ward_room,
        registry=registry,
        intent_bus=overrides.pop("intent_bus", AsyncMock()),
        trust_network=overrides.pop("trust_network", MagicMock()),
        ontology=None,
        callsign_registry=overrides.pop("callsign_registry", MagicMock()),
        episodic_memory=None,
        event_emitter=overrides.pop("event_emitter", MagicMock()),
        event_log=overrides.pop("event_log", AsyncMock()),
        config=config,
    )


def _make_channel(channel_type="department"):
    ch = MagicMock()
    ch.channel_type = channel_type
    ch.name = "test-channel"
    return ch


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_max_thread_posts_default_50(self):
        """Test 1: max_thread_posts defaults to 50."""
        assert WardRoomConfig().max_thread_posts == 50

    def test_max_agent_responses_per_thread_removed(self):
        """Test 2: WardRoomConfig no longer has max_agent_responses_per_thread."""
        assert not hasattr(WardRoomConfig(), 'max_agent_responses_per_thread')

    def test_max_agent_rounds_default_5(self):
        """Test 15: max_agent_rounds raised to 5."""
        assert WardRoomConfig().max_agent_rounds == 5


# ---------------------------------------------------------------------------
# Thread post cap enforcement
# ---------------------------------------------------------------------------

class TestThreadPostCap:
    @pytest.mark.asyncio
    async def test_thread_under_cap_routes_normally(self):
        """Test 3: Thread with 10 posts → agents receive intents."""
        router = _make_router()
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)

        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(10)]}

        await router._route_to_agents(
            target_agent_ids=["agent-1"],
            is_captain=True, is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1", channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test", author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello", cooldown=30,
            current_round=0, round_participants=set(),
            thread_detail=thread_detail,
        )
        assert router._intent_bus.dispatch_async.call_count == 1

    @pytest.mark.asyncio
    async def test_thread_at_cap_blocks_all_agents(self):
        """Test 4: Thread with 50 posts → no agents receive intents."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)

        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(50)]}

        await router._route_to_agents(
            target_agent_ids=["agent-1", "agent-2"],
            is_captain=True, is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1", channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test", author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello", cooldown=30,
            current_round=0, round_participants=set(),
            thread_detail=thread_detail,
        )
        assert router._intent_bus.dispatch_async.call_count == 0

    @pytest.mark.asyncio
    async def test_thread_post_cap_posts_notification(self):
        """Test 5: When cap hit, system notification posted with 'reached 50 posts'."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)

        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(50)]}

        await router._route_to_agents(
            target_agent_ids=["agent-1"],
            is_captain=True, is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1", channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test", author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello", cooldown=30,
            current_round=0, round_participants=set(),
            thread_detail=thread_detail,
        )
        ward_room.create_post.assert_called_once()
        body = ward_room.create_post.call_args[1]["body"]
        assert "50 posts" in body

    @pytest.mark.asyncio
    async def test_thread_post_cap_notification_deduplicated(self):
        """Test 6: Second event on same capped thread → no duplicate notification."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)

        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(50)]}

        for _ in range(2):
            await router._route_to_agents(
                target_agent_ids=["agent-1"],
                is_captain=True, is_agent_post=False,
                mentioned_agent_ids=set(),
                channel=_make_channel(),
                thread_id="t-1", channel_id="ch-1",
                event_type="ward_room_post_created",
                title="Test", author_id="captain",
                data={"author_callsign": "Captain"},
                thread_context="Hello", cooldown=30,
                current_round=0, round_participants=set(),
                thread_detail=thread_detail,
            )
        assert ward_room.create_post.call_count == 1

    @pytest.mark.asyncio
    async def test_thread_post_cap_suggests_new_thread(self):
        """Test 7: Notification body contains 'start a new thread'."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)

        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(50)]}

        await router._route_to_agents(
            target_agent_ids=["agent-1"],
            is_captain=True, is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1", channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test", author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello", cooldown=30,
            current_round=0, round_participants=set(),
            thread_detail=thread_detail,
        )
        body = ward_room.create_post.call_args[1]["body"]
        assert "start a new thread" in body


# ---------------------------------------------------------------------------
# DM exemption
# ---------------------------------------------------------------------------

class TestDMExemption:
    @pytest.mark.asyncio
    async def test_dm_channel_ignores_thread_post_cap(self):
        """Test 8: DM thread with 60 posts → agents still receive intents."""
        router = _make_router()
        # DM channel bypasses thread post cap — but still subject to dm_exchange_limit
        # Mock count_posts_by_author to return 0 so DM exchange limit doesn't block
        router._ward_room.count_posts_by_author = AsyncMock(return_value=0)
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)

        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(60)]}

        await router._route_to_agents(
            target_agent_ids=["agent-1"],
            is_captain=True, is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(channel_type="dm"),
            thread_id="t-1", channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test", author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello", cooldown=30,
            current_round=0, round_participants=set(),
            thread_detail=thread_detail,
        )
        assert router._intent_bus.dispatch_async.call_count == 1


# ---------------------------------------------------------------------------
# Removal verification
# ---------------------------------------------------------------------------

class TestRemoval:
    def test_no_check_and_increment_reply_cap(self):
        """Test 9: WardRoomRouter no longer has check_and_increment_reply_cap."""
        assert not hasattr(WardRoomRouter, 'check_and_increment_reply_cap')

    def test_no_dept_thread_responses(self):
        """Test 10: WardRoomRouter no longer has _dept_thread_responses."""
        router = _make_router()
        assert not hasattr(router, '_dept_thread_responses')

    def test_no_agent_thread_responses(self):
        """Test 11: WardRoomRouter no longer has _agent_thread_responses."""
        router = _make_router()
        assert not hasattr(router, '_agent_thread_responses')


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_tracking_no_agent_or_dept_state(self):
        """Test 12: cleanup_tracking works without agent/dept tracking."""
        router = _make_router()
        router._thread_rounds["thread-1"] = 3
        router._round_participants["thread-1:0"] = {"agent-1"}

        router.cleanup_tracking({"thread-1"})

        assert "thread-1" not in router._thread_rounds
        assert "thread-1:0" not in router._round_participants

    def test_cleanup_tracking_prunes_cap_notices(self):
        """Test 13: cleanup_tracking removes _cap_notices_posted for pruned threads."""
        router = _make_router()
        router._cap_notices_posted.add(("thread-1", "thread_post_limit"))
        router._cap_notices_posted.add(("thread-2", "agent_round_limit"))

        router.cleanup_tracking({"thread-1"})

        assert ("thread-1", "thread_post_limit") not in router._cap_notices_posted
        assert ("thread-2", "agent_round_limit") in router._cap_notices_posted


# ---------------------------------------------------------------------------
# CommGateOverrides
# ---------------------------------------------------------------------------

class TestCommGateOverrides:
    def test_comm_gate_overrides_no_max_responses(self):
        """Test 14: CommGateOverrides has no max_responses_per_thread."""
        from probos.cognitive.comm_proficiency import CommGateOverrides
        assert not hasattr(CommGateOverrides, 'max_responses_per_thread') or \
            'max_responses_per_thread' not in CommGateOverrides.__dataclass_fields__


# ---------------------------------------------------------------------------
# Proactive path cap check
# ---------------------------------------------------------------------------

class TestProactiveCapCheck:
    @pytest.mark.asyncio
    async def test_proactive_reply_skips_capped_thread(self):
        """Test 16: Proactive [REPLY] path skips reply when thread has >= 50 posts."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = MagicMock(spec=ProactiveCognitiveLoop)
        loop._runtime = MagicMock()
        loop._reply_cooldowns = {}

        wr_router = MagicMock()
        loop._runtime.ward_room_router = wr_router
        loop._runtime.ward_room = AsyncMock()
        loop._runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"locked": False, "channel_id": "ch-1"},
            "posts": [{"id": f"p-{i}"} for i in range(50)],
        })
        loop._runtime.ward_room.create_post = AsyncMock()
        loop._runtime.config.ward_room.max_thread_posts = 50
        loop._runtime.callsign_registry = MagicMock()
        loop._runtime.callsign_registry.get_callsign.return_value = "Scotty"

        agent = MagicMock()
        agent.id = "agent-scotty"
        agent.agent_type = "scotty"

        text = "[REPLY thread-abc] Engines are nominal. [/REPLY]"

        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")
        loop._is_similar_to_recent_posts = AsyncMock(return_value=False)
        loop._extract_commands_from_reply = AsyncMock(return_value=("Engines are nominal.", []))
        loop._get_comm_gate_overrides = MagicMock(return_value=None)

        real_method = ProactiveCognitiveLoop._extract_and_execute_replies
        cleaned, actions = await real_method(loop, agent, text)

        # Post should NOT have been created — thread is at cap
        loop._runtime.ward_room.create_post.assert_not_called()
