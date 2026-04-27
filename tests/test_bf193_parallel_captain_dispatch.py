"""BF-193: Parallel Captain Message Dispatch — tests."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router():
    """Build a minimal WardRoomRouter with mocked dependencies."""
    from probos.ward_room_router import WardRoomRouter

    config = MagicMock()
    config.ward_room.dm_exchange_limit = 6
    config.ward_room.agent_cooldown_seconds = 45
    config.ward_room.max_thread_posts = 50
    config.communications = MagicMock()
    config.communications.recreation_min_rank = "ensign"

    router = WardRoomRouter.__new__(WardRoomRouter)
    router._config = config
    router._intent_bus = AsyncMock()
    router._ward_room = AsyncMock()
    router._registry = MagicMock()
    router._callsign_registry = MagicMock()
    router._proactive_loop = None
    router._trust_network = None
    router._cooldowns = {}
    router._thread_rounds = {}
    router._round_participants = {}
    router._responded_threads = {}  # BF-198
    router._last_responded_eviction = time.time()  # BF-198
    router._captain_delivery_done = asyncio.Event()
    router._captain_delivery_done.set()
    router._WARD_ROOM_COOLDOWN_SECONDS = 30
    router._cap_notices_posted = set()
    router._posted_in_round = {}
    router._last_posted_in_round_eviction = time.time()

    # extract_endorsements returns text unchanged, no endorsements
    router.extract_endorsements = MagicMock(side_effect=lambda t: (t, []))

    return router


def _make_result(text: str):
    """Make a fake intent result with .result = text."""
    return MagicMock(result=text)


def _make_channel(name="bridge", channel_type="public"):
    return SimpleNamespace(name=name, channel_type=channel_type, id="ch-1")


AGENT_IDS = [f"agent-{i:02d}" for i in range(14)]


# ===========================================================================
# Tests
# ===========================================================================


class TestCaptainParallelDispatch:
    """BF-193: Captain messages dispatch concurrently."""

    @pytest.mark.asyncio
    async def test_captain_dispatch_is_fast(self):
        """AD-654a: Captain dispatch with dispatch_async is fast (no LLM wait)."""
        router = _make_router()
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)
        router._registry.get = MagicMock(return_value=None)

        start = time.monotonic()
        await router._route_to_agents(
            target_agent_ids=AGENT_IDS,
            is_captain=True,
            is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1",
            channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test",
            author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello crew",
            cooldown=30,
            current_round=0,
            round_participants=set(),
        )
        elapsed = time.monotonic() - start

        # AD-654a: dispatch_async is fire-and-forget, should be very fast
        assert elapsed < 0.5, f"Captain dispatch took {elapsed:.2f}s, expected < 0.5s"

    @pytest.mark.asyncio
    async def test_captain_dispatch_all_agents_receive(self):
        """All 14 agents receive intents and responses are posted."""
        router = _make_router()
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)
        router._registry.get = MagicMock(return_value=MagicMock(agent_type="test"))
        router._callsign_registry.get_callsign = MagicMock(return_value="TestAgent")

        await router._route_to_agents(
            target_agent_ids=AGENT_IDS,
            is_captain=True,
            is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1",
            channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test",
            author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello crew",
            cooldown=30,
            current_round=0,
            round_participants=set(),
        )

        # All 14 agents should have had intents dispatched
        assert router._intent_bus.dispatch_async.call_count == 14
        # AD-654a: Router no longer posts on behalf of agents (agents self-post)

    @pytest.mark.asyncio
    async def test_agent_dispatch_stays_sequential(self):
        """Non-Captain dispatch is sequential — agents start in order."""
        router = _make_router()
        call_order = []

        async def _tracking_dispatch(intent):
            call_order.append(intent.target_agent_id)
            await asyncio.sleep(0.01)

        router._intent_bus.dispatch_async = _tracking_dispatch
        router._registry.get = MagicMock(return_value=None)

        agents = AGENT_IDS[:3]
        await router._route_to_agents(
            target_agent_ids=agents,
            is_captain=False,
            is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1",
            channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test",
            author_id="agent-99",
            data={"author_callsign": "Agent99"},
            thread_context="Thread content",
            cooldown=30,
            current_round=0,
            round_participants=set(),
        )

        # Sequential: order matches input order
        assert call_order == agents

    @pytest.mark.asyncio
    async def test_captain_dispatch_fires_all(self):
        """AD-654a: All agents receive dispatch_async calls (fire-and-forget)."""
        router = _make_router()
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)
        router._registry.get = MagicMock(return_value=MagicMock(agent_type="test"))
        router._callsign_registry.get_callsign = MagicMock(return_value="Test")

        await router._route_to_agents(
            target_agent_ids=AGENT_IDS,
            is_captain=True,
            is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1",
            channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test",
            author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello crew",
            cooldown=30,
            current_round=0,
            round_participants=set(),
        )

        # All 14 dispatched via fire-and-forget
        assert router._intent_bus.dispatch_async.call_count == 14

    @pytest.mark.asyncio
    async def test_captain_dispatch_respects_thread_post_cap(self):
        """BF-201: Thread at post cap → no agents dispatched."""
        router = _make_router()
        router._intent_bus.dispatch_async = AsyncMock(return_value=None)
        router._registry.get = MagicMock(return_value=None)

        # Simulate thread at 50 posts
        thread_detail = {"posts": [{"id": f"p-{i}"} for i in range(50)]}

        await router._route_to_agents(
            target_agent_ids=AGENT_IDS,
            is_captain=True,
            is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1",
            channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test",
            author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello crew",
            cooldown=30,
            current_round=0,
            round_participants=set(),
            thread_detail=thread_detail,
        )

        # No agents dispatched — thread is full
        assert router._intent_bus.dispatch_async.call_count == 0

    @pytest.mark.asyncio
    async def test_captain_dispatch_ordering(self):
        """AD-654a: Dispatches fire in agent_ids order."""
        router = _make_router()
        dispatch_order = []

        async def _tracking_dispatch(intent):
            dispatch_order.append(intent.target_agent_id)

        router._intent_bus.dispatch_async = _tracking_dispatch
        router._registry.get = MagicMock(return_value=MagicMock(agent_type="test"))
        router._callsign_registry.get_callsign = MagicMock(return_value="Test")

        await router._route_to_agents(
            target_agent_ids=AGENT_IDS,
            is_captain=True,
            is_agent_post=False,
            mentioned_agent_ids=set(),
            channel=_make_channel(),
            thread_id="t-1",
            channel_id="ch-1",
            event_type="ward_room_post_created",
            title="Test",
            author_id="captain",
            data={"author_callsign": "Captain"},
            thread_context="Hello crew",
            cooldown=30,
            current_round=0,
            round_participants=set(),
        )

        # Dispatches should be in original agent ID order
        assert dispatch_order == AGENT_IDS

    @pytest.mark.asyncio
    async def test_captain_dispatch_cooldown_api_exists(self):
        """AD-654a: Router has update_cooldown() API for post-dispatch cooldown tracking."""
        router = _make_router()
        router.update_cooldown("agent-00")
        assert "agent-00" in router._cooldowns
