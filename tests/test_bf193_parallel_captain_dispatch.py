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
    async def test_captain_dispatch_is_parallel(self):
        """Captain dispatch with delay per call should complete faster than sequential."""
        router = _make_router()

        async def _slow_send(intent):
            await asyncio.sleep(0.05)  # 50ms per agent
            return _make_result("Acknowledged, Captain.")

        router._intent_bus.send = _slow_send
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

        # 14 agents × 50ms sequential = 700ms. Parallel should be ~50-100ms.
        assert elapsed < 0.5, f"Captain dispatch took {elapsed:.2f}s, expected < 0.5s (parallel)"

    @pytest.mark.asyncio
    async def test_captain_dispatch_all_agents_receive(self):
        """All 14 agents receive intents and responses are posted."""
        router = _make_router()
        router._intent_bus.send = AsyncMock(return_value=_make_result("Aye aye, Captain."))
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
        assert router._intent_bus.send.call_count == 14
        # All 14 responses posted
        assert router._ward_room.create_post.call_count == 14

    @pytest.mark.asyncio
    async def test_agent_dispatch_stays_sequential(self):
        """Non-Captain dispatch is sequential — agents start in order."""
        router = _make_router()
        call_order = []

        async def _tracking_send(intent):
            call_order.append(intent.target_agent_id)
            await asyncio.sleep(0.01)
            return _make_result("Response")

        router._intent_bus.send = _tracking_send
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
    async def test_captain_dispatch_handles_individual_failure(self):
        """One agent failing doesn't prevent others from responding."""
        router = _make_router()

        call_count = 0

        async def _failing_send(intent):
            nonlocal call_count
            call_count += 1
            if intent.target_agent_id == "agent-03":
                raise RuntimeError("LLM timeout")
            return _make_result("Acknowledged.")

        router._intent_bus.send = _failing_send
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

        # All 14 dispatched, 13 posted (agent-03 failed)
        assert call_count == 14
        assert router._ward_room.create_post.call_count == 13

    @pytest.mark.asyncio
    async def test_captain_dispatch_respects_thread_post_cap(self):
        """BF-201: Thread at post cap → no agents dispatched."""
        router = _make_router()
        router._intent_bus.send = AsyncMock(return_value=_make_result("Response"))
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
        assert router._intent_bus.send.call_count == 0

    @pytest.mark.asyncio
    async def test_captain_dispatch_post_ordering(self):
        """Responses posted in agent_ids order, not completion order."""
        router = _make_router()
        post_order = []

        async def _varied_send(intent):
            # Reverse delay — later agents finish faster
            idx = int(intent.target_agent_id.split("-")[1])
            await asyncio.sleep(0.01 * (14 - idx))
            return _make_result(f"Response from {intent.target_agent_id}")

        router._intent_bus.send = _varied_send
        router._registry.get = MagicMock(return_value=MagicMock(agent_type="test"))
        router._callsign_registry.get_callsign = MagicMock(return_value="Test")

        original_create_post = router._ward_room.create_post

        async def _tracking_post(**kwargs):
            post_order.append(kwargs["author_id"])

        router._ward_room.create_post = _tracking_post

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

        # Posts should be in original agent ID order
        assert post_order == AGENT_IDS

    @pytest.mark.asyncio
    async def test_captain_dispatch_cooldown_updated(self):
        """After dispatch, all responding agents have cooldown timestamps."""
        router = _make_router()
        router._intent_bus.send = AsyncMock(return_value=_make_result("Aye."))
        router._registry.get = MagicMock(return_value=MagicMock(agent_type="test"))
        router._callsign_registry.get_callsign = MagicMock(return_value="Test")

        agents = AGENT_IDS[:5]
        await router._route_to_agents(
            target_agent_ids=agents,
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

        # All 5 agents should have cooldown entries
        for aid in agents:
            assert aid in router._cooldowns, f"{aid} missing cooldown entry"
