"""BF-236: Semantic duplicate dispatch — round-scoped post tracker."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.ward_room_router import WardRoomRouter


def _make_config():
    cfg = MagicMock()
    cfg.ward_room.event_coalesce_ms = 200
    cfg.ward_room.max_thread_posts = 50
    return cfg


def _make_router():
    ontology = MagicMock()
    ontology.get_agent_department.return_value = None

    return WardRoomRouter(
        ward_room=MagicMock(),
        registry=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=ontology,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=_make_config(),
        proactive_loop=None,
    )


def _route_args(router, **overrides):
    """Build default _route_to_agents() kwargs, applying overrides."""
    channel = MagicMock()
    channel.channel_type = overrides.pop("channel_type", "ship")
    channel.name = "general"
    defaults = dict(
        target_agent_ids=["agent-a"],
        is_captain=True,
        is_agent_post=False,
        mentioned_agent_ids=set(),
        channel=channel,
        thread_id="thread-1",
        channel_id="chan-1",
        event_type="new_post",
        title="Test",
        author_id="captain-1",
        data={},
        thread_context="context",
        cooldown=0,
        current_round=0,
        round_participants=set(),
    )
    defaults.update(overrides)
    return defaults


# ── Test 1 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_skips_agent_that_already_posted():
    """Agent that posted in this round is skipped by dispatch."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(**_route_args(router))
    router._intent_bus.dispatch_async.assert_not_called()


# ── Test 2 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_allows_agent_without_prior_post():
    """Agent without prior post in this round is dispatched normally."""
    router = _make_router()
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(**_route_args(router))
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 3 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_bypassed_for_mentioned_agent():
    """@mentioned agent bypasses the round-post gate."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(
        **_route_args(router, mentioned_agent_ids={"agent-a"})
    )
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 4 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_bypassed_for_dm_channel():
    """DM channel sets is_direct_target, bypassing the round-post gate."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router._ward_room.count_posts_by_author = AsyncMock(return_value=0)
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(
        **_route_args(router, channel_type="dm")
    )
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 5 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("is_captain,is_agent_post", [
    (True, False),
    (False, True),
])
@pytest.mark.asyncio
async def test_gate_fires_for_both_captain_and_agent_posts(is_captain, is_agent_post):
    """Gate fires regardless of whether the triggering post is from Captain or agent."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(
        **_route_args(router, is_captain=is_captain, is_agent_post=is_agent_post)
    )
    router._intent_bus.dispatch_async.assert_not_called()


# ── Test 6 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_no_crash_on_empty_thread_id():
    """Empty thread_id doesn't crash; dispatch proceeds."""
    router = _make_router()
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(
        **_route_args(router, thread_id="")
    )
    # has_posted_in_round returns False for empty thread_id
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 7 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_allows_different_thread():
    """Agent posted in thread-1 is still eligible for thread-2."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(
        **_route_args(router, thread_id="thread-2")
    )
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 8 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_allows_different_agent_same_thread():
    """Different agent is eligible even if agent-a already posted."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(
        **_route_args(router, target_agent_ids=["agent-b"])
    )
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 9 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_captain_repost_clears_tracker_agent_eligible_again():
    """Captain repost clears round-post tracker; agent becomes eligible again."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    assert router.has_posted_in_round("agent-a", "thread-1") is True

    router._clear_round_posts_for_thread("thread-1")
    assert router.has_posted_in_round("agent-a", "thread-1") is False

    router._intent_bus.dispatch_async = AsyncMock()
    await router._route_to_agents(**_route_args(router))
    router._intent_bus.dispatch_async.assert_called_once()


# ── Test 9b ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_captain_repost_clears_tracker_via_route_event():
    """route_event() Captain path calls _clear_round_posts_for_thread()."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    assert router.has_posted_in_round("agent-a", "thread-1") is True

    router._ward_room.get_thread = AsyncMock(return_value={
        "thread": {"channel_id": "chan-1", "thread_mode": "discuss"},
    })
    router._ward_room.get_channel = AsyncMock(return_value=MagicMock(
        channel_type="ship", name="general",
    ))
    router._ward_room.count_posts_in_thread = AsyncMock(return_value=1)

    await router.route_event("ward_room_post_created", {
        "author_id": "captain",
        "thread_id": "thread-1",
        "channel_id": "chan-1",
    })

    assert router.has_posted_in_round("agent-a", "thread-1") is False


# ── Test 10 ───────────────────────────────────────────────────────────

def test_clear_does_not_affect_other_threads():
    """Clearing one thread's records leaves other threads intact."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router.record_round_post("agent-a", "thread-2")

    router._clear_round_posts_for_thread("thread-1")

    assert router.has_posted_in_round("agent-a", "thread-1") is False
    assert router.has_posted_in_round("agent-a", "thread-2") is True


# ── Test 11 ───────────────────────────────────────────────────────────

def test_eviction_removes_stale_entries():
    """Eviction removes entries older than max_age, keeps recent ones."""
    router = _make_router()
    now = time.time()

    # 2 stale entries
    router._posted_in_round[("agent-a", "thread-1")] = now - 200.0
    router._posted_in_round[("agent-b", "thread-2")] = now - 200.0
    # 1 fresh entry
    router._posted_in_round[("agent-c", "thread-3")] = now

    router._evict_stale_round_posts(max_age=120.0)
    assert len(router._posted_in_round) == 1
    assert ("agent-c", "thread-3") in router._posted_in_round


# ── Test 12 ───────────────────────────────────────────────────────────

def test_cleanup_tracking_removes_pruned_threads():
    """cleanup_tracking() removes round-post records for pruned threads."""
    router = _make_router()
    router.record_round_post("agent-a", "thread-1")
    router.record_round_post("agent-a", "thread-2")

    router.cleanup_tracking({"thread-1"})

    assert router.has_posted_in_round("agent-a", "thread-1") is False
    assert router.has_posted_in_round("agent-a", "thread-2") is True
