"""AD-623: DM Convergence Gate + DM Self-Monitoring.

Tests the convergence detection function, router convergence gate,
and DM self-monitoring injection in the cognitive agent WR notification path.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import aiosqlite
import pytest

from probos.events import EventType
from probos.ward_room.models import _SCHEMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_db() -> aiosqlite.Connection:
    """Create an in-memory WardRoom DB with schema."""
    db = await aiosqlite.connect(":memory:")
    await db.executescript(_SCHEMA)
    return db


async def _insert_thread(db: aiosqlite.Connection, thread_id: str, channel_id: str = "ch1") -> None:
    await db.execute(
        "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (thread_id, channel_id, "author_a", "Test Thread", "", time.time(), time.time()),
    )
    await db.commit()


async def _insert_post(
    db: aiosqlite.Connection, thread_id: str, author_id: str, body: str, ts: float,
    author_callsign: str = "",
) -> None:
    import uuid
    await db.execute(
        "INSERT INTO posts (id, thread_id, author_id, body, created_at, author_callsign) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4())[:8], thread_id, author_id, body, ts, author_callsign),
    )
    await db.commit()


def _make_channel(name: str, ch_type: str = "dm") -> SimpleNamespace:
    return SimpleNamespace(
        id=f"ch_{name}", name=name, channel_type=ch_type,
        department="", created_by="system", created_at=0.0,
        archived=False, description="",
    )


def _make_router(
    agents: list | None = None,
    ward_room: MagicMock | None = None,
) -> MagicMock:
    """Build a minimal WardRoomRouter for testing."""
    from probos.ward_room_router import WardRoomRouter

    registry = MagicMock()
    registry.all.return_value = agents or []

    config = MagicMock()
    config.earned_agency.enabled = False
    config.ward_room.event_coalesce_ms = 200
    config.ward_room.dm_exchange_limit = 6
    config.ward_room.agent_cooldown_seconds = 45
    config.ward_room.max_thread_posts = 50
    config.ward_room.max_agent_rounds = 5

    return WardRoomRouter(
        ward_room=ward_room or MagicMock(),
        registry=registry,
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=None,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=config,
    )


# ---------------------------------------------------------------------------
# 1. Convergence detection — dissimilar posts
# ---------------------------------------------------------------------------

class TestConvergenceDetection:
    @pytest.mark.asyncio
    async def test_no_convergence_dissimilar_posts(self) -> None:
        """Two agents with different post content -> returns None."""
        from probos.ward_room.threads import check_dm_convergence

        db = await _make_db()
        await _insert_thread(db, "t1")

        # Posts with very different content
        await _insert_post(db, "t1", "agent_a", "I think the warp drive needs recalibration", 1.0)
        await _insert_post(db, "t1", "agent_b", "The holodeck is experiencing strange anomalies", 2.0)
        await _insert_post(db, "t1", "agent_a", "Engineering reports shield harmonics fluctuating", 3.0)
        await _insert_post(db, "t1", "agent_b", "Medical bay reports increased crew fatigue levels", 4.0)

        result = await check_dm_convergence(db, "t1")
        assert result is None
        await db.close()

    # 2. Convergence detected — mutual echo
    @pytest.mark.asyncio
    async def test_convergence_detected_mutual_echo(self) -> None:
        """Both agents repeating similar content -> returns converged result."""
        from probos.ward_room.threads import check_dm_convergence

        db = await _make_db()
        await _insert_thread(db, "t1")

        # Both agents saying very similar things
        await _insert_post(db, "t1", "agent_a", "I agree the analysis shows positive results for the crew", 1.0)
        await _insert_post(db, "t1", "agent_b", "Yes I agree the analysis shows very positive results for the crew", 2.0)
        await _insert_post(db, "t1", "agent_a", "The analysis results are indeed positive for all crew members", 3.0)
        await _insert_post(db, "t1", "agent_b", "Indeed the analysis results are very positive for all crew members", 4.0)
        await _insert_post(db, "t1", "agent_a", "Positive results for crew confirmed by the analysis data", 5.0)
        await _insert_post(db, "t1", "agent_b", "Confirmed the analysis shows positive results for all crew", 6.0)

        result = await check_dm_convergence(db, "t1")
        assert result is not None
        assert result["converged"] is True
        assert result["similarity"] >= 0.55
        assert result["exchange_count"] >= 2
        await db.close()

    # 3. Insufficient posts
    @pytest.mark.asyncio
    async def test_insufficient_posts(self) -> None:
        """Thread with <4 posts -> returns None."""
        from probos.ward_room.threads import check_dm_convergence

        db = await _make_db()
        await _insert_thread(db, "t1")

        await _insert_post(db, "t1", "agent_a", "Hello there", 1.0)
        await _insert_post(db, "t1", "agent_b", "Hi how are you", 2.0)

        result = await check_dm_convergence(db, "t1")
        assert result is None
        await db.close()

    # 4. Mixed similarity
    @pytest.mark.asyncio
    async def test_mixed_similarity_below_threshold(self) -> None:
        """Some pairs similar, some not -> below threshold -> returns None."""
        from probos.ward_room.threads import check_dm_convergence

        db = await _make_db()
        await _insert_thread(db, "t1")

        # First pair: similar
        await _insert_post(db, "t1", "agent_a", "The shields need full recalibration immediately", 1.0)
        await _insert_post(db, "t1", "agent_b", "Yes shields need full recalibration right away", 2.0)
        # Second pair: different
        await _insert_post(db, "t1", "agent_a", "Also we should check the phaser array alignment", 3.0)
        await _insert_post(db, "t1", "agent_b", "Unrelated topic but crew morale reports look excellent", 4.0)

        result = await check_dm_convergence(db, "t1")
        assert result is None
        await db.close()

    # 5. Same author consecutive
    @pytest.mark.asyncio
    async def test_same_author_consecutive_skipped(self) -> None:
        """Posts by same author in a row -> skipped as exchange pairs."""
        from probos.ward_room.threads import check_dm_convergence

        db = await _make_db()
        await _insert_thread(db, "t1")

        # Same author posts in a row — these should not form exchange pairs
        await _insert_post(db, "t1", "agent_a", "First point about the topic", 1.0)
        await _insert_post(db, "t1", "agent_a", "Second point about the topic", 2.0)
        await _insert_post(db, "t1", "agent_b", "I see your point", 3.0)
        await _insert_post(db, "t1", "agent_b", "Let me add to that", 4.0)

        # Only 1 cross-author pair possible (a->b), need at least 2
        result = await check_dm_convergence(db, "t1")
        assert result is None
        await db.close()


# ---------------------------------------------------------------------------
# 6-10. Router convergence gate
# ---------------------------------------------------------------------------

class TestRouterConvergenceGate:
    @pytest.mark.asyncio
    async def test_router_stops_on_convergence(self) -> None:
        """DM thread converged -> route_event() returns without sending intents."""
        ward_room = MagicMock()
        ward_room.check_dm_convergence = AsyncMock(
            return_value={"converged": True, "similarity": 0.7, "exchange_count": 3}
        )
        ward_room.get_thread = AsyncMock(return_value={
            "thread": {"channel_id": "ch1", "thread_mode": "discuss", "title": "Test", "body": ""},
            "posts": [],
        })
        ward_room.get_channel = AsyncMock(return_value=SimpleNamespace(
            id="ch1", name="dm-agent_a-couns_001", channel_type="dm",
            department="", created_by="system",
        ))
        ward_room.count_posts_by_author = AsyncMock(return_value=0)

        agent = MagicMock()
        agent.agent_type = "counselor"
        agent.id = "couns_001"
        agent.is_alive = True

        router = _make_router([agent], ward_room=ward_room)

        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            router.find_targets = MagicMock(return_value=["couns_001"])
            router.find_targets_for_agent = MagicMock(return_value=["couns_001"])

            await router.route_event(
                "ward_room_post_created",
                {"thread_id": "t1", "author_id": "agent_a", "author_callsign": "Alpha"},
            )

        # Intent bus should NOT have been called (convergence gate stopped it)
        router._intent_bus.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_router_continues_on_non_convergence(self) -> None:
        """DM thread not converged -> intents sent normally."""
        ward_room = MagicMock()
        ward_room.check_dm_convergence = AsyncMock(return_value=None)
        ward_room.get_thread = AsyncMock(return_value={
            "thread": {"channel_id": "ch1", "thread_mode": "discuss", "title": "Test", "body": ""},
            "posts": [],
        })
        ward_room.get_channel = AsyncMock(return_value=SimpleNamespace(
            id="ch1", name="dm-agent_a-couns_001", channel_type="dm",
            department="", created_by="system",
        ))
        ward_room.count_posts_by_author = AsyncMock(return_value=0)

        agent = MagicMock()
        agent.agent_type = "counselor"
        agent.id = "couns_001"
        agent.is_alive = True

        router = _make_router([agent], ward_room=ward_room)
        router._intent_bus.send = AsyncMock(return_value=MagicMock(result="[NO_RESPONSE]"))

        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            router.find_targets = MagicMock(return_value=["couns_001"])
            router.find_targets_for_agent = MagicMock(return_value=["couns_001"])

            await router.route_event(
                "ward_room_post_created",
                {"thread_id": "t1", "author_id": "agent_a", "author_callsign": "Alpha"},
            )

        # Intent bus SHOULD have been called (no convergence)
        router._intent_bus.send.assert_called()

    @pytest.mark.asyncio
    async def test_event_emitted_on_convergence(self) -> None:
        """DM_CONVERGENCE_DETECTED event emitted with thread data."""
        ward_room = MagicMock()
        ward_room.check_dm_convergence = AsyncMock(
            return_value={"converged": True, "similarity": 0.65, "exchange_count": 3}
        )
        ward_room.get_thread = AsyncMock(return_value={
            "thread": {"channel_id": "ch1", "thread_mode": "discuss", "title": "Test", "body": ""},
            "posts": [],
        })
        ward_room.get_channel = AsyncMock(return_value=SimpleNamespace(
            id="ch1", name="dm-agent_a-couns_001", channel_type="dm",
            department="", created_by="system",
        ))

        agent = MagicMock()
        agent.id = "couns_001"
        agent.is_alive = True

        router = _make_router([agent], ward_room=ward_room)

        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            router.find_targets = MagicMock(return_value=["couns_001"])

            await router.route_event(
                "ward_room_post_created",
                {"thread_id": "t1", "author_id": "agent_a", "author_callsign": "Alpha"},
            )

        # Event emitter should have been called with convergence data
        router._event_emitter.assert_called_once()
        call_args = router._event_emitter.call_args
        assert call_args[0][0] == "dm_convergence_detected"
        event_data = call_args[0][1]
        assert event_data["thread_id"] == "t1"
        assert event_data["similarity"] == 0.65
        assert event_data["exchange_count"] == 3

    @pytest.mark.asyncio
    async def test_non_dm_channels_skip_convergence(self) -> None:
        """Department channel posts -> convergence check NOT called."""
        ward_room = MagicMock()
        ward_room.check_dm_convergence = AsyncMock(return_value=None)
        ward_room.get_thread = AsyncMock(return_value={
            "thread": {"channel_id": "ch1", "thread_mode": "discuss", "title": "Test", "body": ""},
            "posts": [],
        })
        ward_room.get_channel = AsyncMock(return_value=SimpleNamespace(
            id="ch1", name="Engineering", channel_type="department",
            department="engineering", created_by="system",
        ))
        ward_room.get_all_channel_members = AsyncMock(return_value={"ch1": {"eng_001"}})

        agent = MagicMock()
        agent.agent_type = "chief_engineer"
        agent.id = "eng_001"
        agent.is_alive = True

        router = _make_router([agent], ward_room=ward_room)
        router._channel_members = {"ch1": {"eng_001"}}

        router._intent_bus.send = AsyncMock(return_value=MagicMock(result="[NO_RESPONSE]"))

        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            await router.route_event(
                "ward_room_post_created",
                {"thread_id": "t1", "author_id": "captain", "author_callsign": "Captain"},
            )

        # Convergence check should NOT have been called for department channel
        ward_room.check_dm_convergence.assert_not_called()

    @pytest.mark.asyncio
    async def test_convergence_check_failure_continues(self) -> None:
        """If check_dm_convergence() raises -> fail open, continue routing."""
        ward_room = MagicMock()
        ward_room.check_dm_convergence = AsyncMock(side_effect=RuntimeError("DB error"))
        ward_room.get_thread = AsyncMock(return_value={
            "thread": {"channel_id": "ch1", "thread_mode": "discuss", "title": "Test", "body": ""},
            "posts": [],
        })
        ward_room.get_channel = AsyncMock(return_value=SimpleNamespace(
            id="ch1", name="dm-agent_a-couns_001", channel_type="dm",
            department="", created_by="system",
        ))
        ward_room.count_posts_by_author = AsyncMock(return_value=0)

        agent = MagicMock()
        agent.id = "couns_001"
        agent.is_alive = True

        router = _make_router([agent], ward_room=ward_room)
        router._intent_bus.send = AsyncMock(return_value=MagicMock(result="[NO_RESPONSE]"))

        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            router.find_targets = MagicMock(return_value=["couns_001"])

            # Should not crash
            await router.route_event(
                "ward_room_post_created",
                {"thread_id": "t1", "author_id": "agent_a", "author_callsign": "Alpha"},
            )

        # Intent bus SHOULD have been called (fail open)
        router._intent_bus.send.assert_called()


# ---------------------------------------------------------------------------
# 11-14. Self-monitoring
# ---------------------------------------------------------------------------

class TestDMSelfMonitoring:
    @pytest.mark.asyncio
    async def test_self_monitoring_injected_for_dm(self) -> None:
        """Agent responding to DM gets self-monitoring when self-similarity is high."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "test_001"
        agent.callsign = "TestAgent"
        agent.agent_type = "counselor"

        rt = MagicMock()
        rt.ward_room = MagicMock()
        # Return similar posts
        rt.ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "I recommend we proceed with the analysis plan immediately"},
            {"body": "We should proceed with the analysis plan right away"},
            {"body": "Let us proceed with the analysis plan as soon as possible"},
        ])
        agent._runtime = rt

        result = await agent._build_dm_self_monitoring("t1")
        assert result is not None
        assert "Self-monitoring" in result
        assert "self-similarity" in result
        assert "[NO_RESPONSE]" in result

    @pytest.mark.asyncio
    async def test_no_self_monitoring_low_similarity(self) -> None:
        """Agent's posts are diverse -> no warning injected."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "test_001"
        agent.callsign = "TestAgent"

        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "The warp core is operating within normal parameters"},
            {"body": "Crew rotation schedule needs to be updated for delta shift"},
            {"body": "Stellar cartography reports a new nebula formation"},
        ])
        agent._runtime = rt

        result = await agent._build_dm_self_monitoring("t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_self_monitoring_insufficient_posts(self) -> None:
        """Fewer than 2 posts -> no self-monitoring."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "test_001"
        agent.callsign = "TestAgent"

        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "Hello there"},
        ])
        agent._runtime = rt

        result = await agent._build_dm_self_monitoring("t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_self_monitoring_failure_degrades(self) -> None:
        """If get_posts_by_author() fails -> no crash, returns None."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "test_001"
        agent.callsign = "TestAgent"

        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.ward_room.get_posts_by_author = AsyncMock(side_effect=RuntimeError("DB error"))
        agent._runtime = rt

        result = await agent._build_dm_self_monitoring("t1")
        assert result is None


# ---------------------------------------------------------------------------
# 15-16. Integration / ordering
# ---------------------------------------------------------------------------

class TestIntegration:
    @pytest.mark.asyncio
    async def test_exchange_limit_before_convergence(self) -> None:
        """Agent over exchange limit -> blocked before convergence check runs.

        Convergence gate is thread-level (before per-agent loop), while
        exchange limit is per-agent (inside loop). If convergence fires first,
        the thread is locked regardless of exchange limits.
        """
        ward_room = MagicMock()
        # Thread is converged
        ward_room.check_dm_convergence = AsyncMock(
            return_value={"converged": True, "similarity": 0.7, "exchange_count": 3}
        )
        ward_room.get_thread = AsyncMock(return_value={
            "thread": {"channel_id": "ch1", "thread_mode": "discuss", "title": "Test", "body": ""},
            "posts": [],
        })
        ward_room.get_channel = AsyncMock(return_value=SimpleNamespace(
            id="ch1", name="dm-agent_a-couns_001", channel_type="dm",
            department="", created_by="system",
        ))

        agent = MagicMock()
        agent.id = "couns_001"
        agent.is_alive = True

        router = _make_router([agent], ward_room=ward_room)

        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            router.find_targets = MagicMock(return_value=["couns_001"])

            await router.route_event(
                "ward_room_post_created",
                {"thread_id": "t1", "author_id": "agent_a", "author_callsign": "Alpha"},
            )

        # Convergence gate should have stopped all routing
        router._intent_bus.send.assert_not_called()
        # Exchange limit check should NOT have been reached
        ward_room.count_posts_by_author.assert_not_called()

    def test_event_type_exists(self) -> None:
        """DM_CONVERGENCE_DETECTED event type is defined."""
        assert hasattr(EventType, "DM_CONVERGENCE_DETECTED")
        assert EventType.DM_CONVERGENCE_DETECTED.value == "dm_convergence_detected"


# ---------------------------------------------------------------------------
# Counselor handler
# ---------------------------------------------------------------------------

class TestCounselorHandler:
    @pytest.mark.asyncio
    async def test_counselor_handles_convergence_event(self) -> None:
        """Counselor's _on_dm_convergence_detected doesn't crash."""
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor_001"

        # Should not raise
        await counselor._on_dm_convergence_detected({
            "thread_id": "t1",
            "similarity": 0.65,
        })

    def test_counselor_subscribes_to_convergence(self) -> None:
        """DM_CONVERGENCE_DETECTED is in the Counselor's event subscription list."""
        import inspect
        from probos.cognitive.counselor import CounselorAgent

        source = inspect.getsource(CounselorAgent.initialize)
        assert "DM_CONVERGENCE_DETECTED" in source
