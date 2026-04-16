"""BF-198: Router/Proactive Response Dedup — Responded-To Thread Tracker.

Tests for the shared ``_responded_threads`` tracker on WardRoomRouter,
which prevents the same agent from posting to the same thread twice
(once via the router event path, once via the proactive poll path).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


def _make_config(max_per_thread: int = 3):
    cfg = MagicMock()
    cfg.ward_room.max_agent_responses_per_thread = max_per_thread
    cfg.ward_room.event_coalesce_ms = 200
    return cfg


def _make_router():
    from probos.ward_room_router import WardRoomRouter

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


# ══════════════════════════════════════════════════════════════════════
# Unit tests — tracker primitives
# ══════════════════════════════════════════════════════════════════════


class TestRespondedTracker:
    def test_record_then_has_responded_true(self):
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        assert router.has_agent_responded("agent-a", "thread-1") is True

    def test_different_agent_false(self):
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        assert router.has_agent_responded("agent-b", "thread-1") is False

    def test_different_thread_false(self):
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        assert router.has_agent_responded("agent-a", "thread-2") is False

    def test_empty_identifiers_no_record(self):
        """Empty agent_id or thread_id should be a safe no-op."""
        router = _make_router()
        router.record_agent_response("", "thread-1")
        router.record_agent_response("agent-a", "")
        assert router.has_agent_responded("", "thread-1") is False
        assert router.has_agent_responded("agent-a", "") is False
        assert len(router._responded_threads) == 0

    def test_eviction_removes_stale(self):
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        # Force timestamp into the past
        router._responded_threads[("agent-a", "thread-1")] = time.time() - 1000.0
        router._evict_stale_responses(max_age=600.0)
        assert router.has_agent_responded("agent-a", "thread-1") is False

    def test_eviction_keeps_fresh(self):
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        router._evict_stale_responses(max_age=600.0)
        assert router.has_agent_responded("agent-a", "thread-1") is True

    def test_maybe_evict_throttled(self):
        """_maybe_evict_stale_responses shouldn't run every call."""
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        # Make the entry stale
        router._responded_threads[("agent-a", "thread-1")] = time.time() - 1000.0
        # Set last eviction to recent — throttle should prevent eviction
        router._last_responded_eviction = time.time()
        router._maybe_evict_stale_responses(interval=60.0)
        # Entry should still be present (eviction was throttled)
        assert ("agent-a", "thread-1") in router._responded_threads

    def test_maybe_evict_runs_after_interval(self):
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        router._responded_threads[("agent-a", "thread-1")] = time.time() - 1000.0
        # Set last eviction far in the past
        router._last_responded_eviction = time.time() - 120.0
        router._maybe_evict_stale_responses(interval=60.0)
        assert ("agent-a", "thread-1") not in router._responded_threads


# ══════════════════════════════════════════════════════════════════════
# Integration — proactive loop filtering
# ══════════════════════════════════════════════════════════════════════


class TestProactiveSkipsRespondedThreads:
    """Proactive ward_room_activity comprehension must filter responded threads."""

    def test_filter_comprehension_excludes_responded(self):
        """The filter expression used in proactive.py should drop responded threads."""
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")

        activity = [
            {"author_id": "other", "thread_id": "thread-1", "body": "x"},
            {"author_id": "other", "thread_id": "thread-2", "body": "y"},
        ]
        self_ids = {"agent-a"}
        agent_id = "agent-a"
        wr_router = router

        filtered = [
            a for a in activity
            if (a.get("author_id", "") or a.get("author", "")) not in self_ids
            and not (wr_router and wr_router.has_agent_responded(agent_id, a.get("thread_id", "")))
        ]
        assert len(filtered) == 1
        assert filtered[0]["thread_id"] == "thread-2"

    def test_filter_no_router_still_works(self):
        """When no router available, filter must not raise."""
        activity = [
            {"author_id": "other", "thread_id": "thread-1", "body": "x"},
        ]
        self_ids = {"agent-a"}
        agent_id = "agent-a"
        wr_router = None

        filtered = [
            a for a in activity
            if (a.get("author_id", "") or a.get("author", "")) not in self_ids
            and not (wr_router and wr_router.has_agent_responded(agent_id, a.get("thread_id", "")))
        ]
        assert len(filtered) == 1


# ══════════════════════════════════════════════════════════════════════
# Integration — proactive post records to tracker
# ══════════════════════════════════════════════════════════════════════


class TestProactivePostRecords:
    """After proactive loop posts a thread or reply, record it on the router."""

    @pytest.mark.asyncio
    async def test_post_observation_thread_records_response(self):
        """_post_proactive_thread should record response after create_thread."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)

        rt = MagicMock()
        rt.ward_room = AsyncMock()
        # create_thread returns an object with .id
        thread_obj = MagicMock()
        thread_obj.id = "thread-xyz"
        rt.ward_room.create_thread = AsyncMock(return_value=thread_obj)
        channel = MagicMock()
        channel.id = "chan-1"
        channel.channel_type = "ship"
        rt.ward_room.list_channels = AsyncMock(return_value=[channel])

        wr_router = _make_router()
        rt.ward_room_router = wr_router

        # callsign registry
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_callsign = MagicMock(return_value="ALPHA")

        loop._runtime = rt

        agent = MagicMock()
        agent.id = "agent-a"
        agent.agent_type = "alpha"

        await loop._post_to_ward_room(agent, "Hello crew")

        assert wr_router.has_agent_responded("agent-a", "thread-xyz") is True


# ══════════════════════════════════════════════════════════════════════
# Integration — router records after create_post
# ══════════════════════════════════════════════════════════════════════


class TestRouterRecordsResponse:
    """When router path posts a reply, it should record the response."""

    def test_record_agent_response_is_public_api(self):
        """Verify record_agent_response is callable on the router instance."""
        router = _make_router()
        # Simulates what the router code does right after create_post() succeeds
        router.record_agent_response("agent-sentinel", "thread-welcome")
        assert router.has_agent_responded("agent-sentinel", "thread-welcome") is True

    def test_double_record_idempotent(self):
        """Recording twice doesn't break — just refreshes timestamp."""
        router = _make_router()
        router.record_agent_response("agent-a", "thread-1")
        first_ts = router._responded_threads[("agent-a", "thread-1")]
        time.sleep(0.01)
        router.record_agent_response("agent-a", "thread-1")
        second_ts = router._responded_threads[("agent-a", "thread-1")]
        assert second_ts >= first_ts
        assert len(router._responded_threads) == 1
