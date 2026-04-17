"""BF-200: Thread Cap Awareness & DM Cap Raise — Tests.

BF-201: Per-agent reply cap removed. Tests updated to use thread_post_limit.
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
        intent_bus=overrides.pop("intent_bus", MagicMock()),
        trust_network=overrides.pop("trust_network", MagicMock()),
        ontology=None,
        callsign_registry=overrides.pop("callsign_registry", MagicMock()),
        episodic_memory=None,
        event_emitter=overrides.pop("event_emitter", MagicMock()),
        event_log=overrides.pop("event_log", AsyncMock()),
        config=config,
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_dm_exchange_limit_default_40(self):
        """Test 1: DM exchange limit raised to 40."""
        assert WardRoomConfig().dm_exchange_limit == 40


# ---------------------------------------------------------------------------
# Cap notification posting
# ---------------------------------------------------------------------------

class TestCapNotification:
    @pytest.mark.asyncio
    async def test_cap_notification_posted_on_thread_post_limit(self):
        """Test 2: Thread post limit hit → system post created."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-1", "", "thread_post_limit")
        ward_room.create_post.assert_called_once()
        call_kwargs = ward_room.create_post.call_args[1]
        assert call_kwargs["thread_id"] == "thread-1"
        assert call_kwargs["author_id"] == "system"
        assert call_kwargs["author_callsign"] == "System"
        assert "50 posts" in call_kwargs["body"]

    @pytest.mark.asyncio
    async def test_cap_notification_posted_on_dm_exchange_limit(self):
        """Test 3: DM exchange limit hit → system post created."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-2", "agent-2", "dm_exchange_limit")
        ward_room.create_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_cap_notification_posted_on_thread_depth(self):
        """Test 4: Agent round limit hit → system post created."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-3", "", "agent_round_limit")
        ward_room.create_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_cap_notification_posted_on_dm_convergence(self):
        """Test 5: DM convergence gate → system post created."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-4", "", "dm_convergence")
        ward_room.create_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_cap_notification_deduplicated(self):
        """Test 6: Second hit on same (thread, cap) → no duplicate post."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-5", "", "thread_post_limit")
        await router._post_cap_notification("thread-5", "", "thread_post_limit")
        assert ward_room.create_post.call_count == 1

    @pytest.mark.asyncio
    async def test_cap_notification_thread_post_limit_suggests_new_thread(self):
        """Test 7: Thread post limit body contains guidance to start a new thread."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-7", "", "thread_post_limit")

        body = ward_room.create_post.call_args[1]["body"]
        assert "start a new thread" in body

    @pytest.mark.asyncio
    async def test_cap_notification_different_caps_same_thread(self):
        """Different cap types on same thread → both post."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-8", "", "thread_post_limit")
        await router._post_cap_notification("thread-8", "agent-1", "dm_exchange_limit")
        assert ward_room.create_post.call_count == 2

    @pytest.mark.asyncio
    async def test_cap_notification_no_ward_room(self):
        """No ward_room → no-op, no error."""
        router = _make_router()
        router._ward_room = None
        # Should not raise
        await router._post_cap_notification("thread-9", "", "thread_post_limit")

    @pytest.mark.asyncio
    async def test_cap_notification_no_agent_id(self):
        """No agent_id (thread-level cap) → generic message."""
        ward_room = AsyncMock()
        router = _make_router(ward_room=ward_room)
        await router._post_cap_notification("thread-10", "", "agent_round_limit")

        body = ward_room.create_post.call_args[1]["body"]
        assert "[System]" in body
        assert "start a new thread" in body
