"""Tests for AD-506b: Peer Repetition Detection & Tier Credits."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from probos.cognitive.llm_client import BaseLLMClient
from probos.events import EventType


# ---------------------------------------------------------------------------
# Part 0a: BF-098 — _save_profile_and_assessment() awaits
# ---------------------------------------------------------------------------


class TestBF098SaveProfileAwait:
    """Verify _save_profile_and_assessment() actually persists via await."""

    @pytest.mark.asyncio
    async def test_save_profile_awaited(self) -> None:
        """Profile store save_profile is awaited (not fire-and-forget)."""
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment, CognitiveProfile

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        store = MagicMock()
        store.save_profile = AsyncMock()
        store.save_assessment = AsyncMock()
        agent._profile_store = store

        profile = CognitiveProfile(agent_id="a1", agent_type="test")
        agent._cognitive_profiles["a1"] = profile

        assessment = CounselorAssessment(agent_id="a1", timestamp=time.time())
        await agent._save_profile_and_assessment("a1", assessment)

        store.save_profile.assert_awaited_once()
        store.save_assessment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_assessment_awaited(self) -> None:
        """Assessment store save_assessment is awaited."""
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment, CognitiveProfile

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        store = MagicMock()
        store.save_profile = AsyncMock()
        store.save_assessment = AsyncMock()
        agent._profile_store = store

        profile = CognitiveProfile(agent_id="a2")
        agent._cognitive_profiles["a2"] = profile

        a = CounselorAssessment(agent_id="a2", timestamp=1.0)
        await agent._save_profile_and_assessment("a2", a)

        # Verify the assessment was the one we passed
        call_args = store.save_assessment.call_args
        assert call_args[0][0].agent_id == "a2"


# ---------------------------------------------------------------------------
# Part 0b: Zone recovery event
# ---------------------------------------------------------------------------


class TestZoneRecovery:
    """Verify zone transition tracking and ZONE_RECOVERY event."""

    def test_zone_transition_tracked(self) -> None:
        """get_last_zone_transition() returns (old, new) after zone change."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker

        cb = CognitiveCircuitBreaker(
            velocity_threshold=20,  # High to avoid velocity trip
            similarity_threshold=0.6,
            amber_similarity_ratio=0.2,
            amber_velocity_ratio=0.5,
            amber_decay_seconds=0.01,  # Fast decay for testing
        )
        aid = "agent-1"

        # Mix similar and unique events to get amber (not trip)
        # 3 similar + 2 unique = 5 events, 3 similar pairs out of 10 total = 0.3 > 0.2
        cb.record_event(aid, "proactive_think", "repetitive content about the same topic here")
        cb.record_event(aid, "proactive_think", "repetitive content about the same topic here")
        cb.record_event(aid, "proactive_think", "repetitive content about the same topic here")
        cb.record_event(aid, "proactive_think", "completely unique alpha bravo charlie delta")
        cb.record_event(aid, "proactive_think", "another different echo foxtrot golf hotel")
        cb.check_and_trip(aid)
        assert cb.get_zone(aid) == "amber"

        transition = cb.get_last_zone_transition(aid)
        assert transition is not None
        assert transition == ("green", "amber")

    def test_zone_transition_none_when_unchanged(self) -> None:
        """get_last_zone_transition() returns None when zone didn't change."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker

        cb = CognitiveCircuitBreaker()
        aid = "agent-2"

        # Single unique event — still green
        cb.record_event(aid, "proactive_think", "unique content xyz")
        cb.check_and_trip(aid)
        assert cb.get_zone(aid) == "green"

        transition = cb.get_last_zone_transition(aid)
        assert transition is None

    def test_zone_recovery_event_emitted(self) -> None:
        """ZONE_RECOVERY event emitted when zone improves (amber→green)."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker

        cb = CognitiveCircuitBreaker(
            velocity_threshold=20,  # High to avoid velocity trip
            amber_similarity_ratio=0.2,
            amber_decay_seconds=0.01,  # Fast decay
        )
        aid = "agent-3"

        # Enter amber with 3 similar + 2 unique (ratio 3/10 = 0.3 > 0.2, < 0.5)
        cb.record_event(aid, "proactive_think", "repetitive content about same topic here")
        cb.record_event(aid, "proactive_think", "repetitive content about same topic here")
        cb.record_event(aid, "proactive_think", "repetitive content about same topic here")
        cb.record_event(aid, "proactive_think", "completely unique alpha bravo charlie delta")
        cb.record_event(aid, "proactive_think", "another different echo foxtrot golf hotel")
        cb.check_and_trip(aid)
        assert cb.get_zone(aid) == "amber"

        # Wait for decay and check with unique content
        time.sleep(0.02)
        cb.record_event(aid, "proactive_think", "completely different unique topic india juliet")
        cb.check_and_trip(aid)

        transition = cb.get_last_zone_transition(aid)
        assert transition == ("amber", "green")

    def test_zone_recovery_event_type_exists(self) -> None:
        """ZONE_RECOVERY event type is in the EventType enum."""
        assert hasattr(EventType, "ZONE_RECOVERY")
        assert EventType.ZONE_RECOVERY.value == "zone_recovery"

    def test_zone_recovery_event_dataclass(self) -> None:
        """ZoneRecoveryEvent dataclass exists and serializes correctly."""
        from probos.events import ZoneRecoveryEvent
        evt = ZoneRecoveryEvent(agent_id="a1", old_zone="amber", new_zone="green")
        d = evt.to_dict()
        assert d["type"] == "zone_recovery"
        assert d["data"]["old_zone"] == "amber"
        assert d["data"]["new_zone"] == "green"


# ---------------------------------------------------------------------------
# Part 1: Peer repetition detection
# ---------------------------------------------------------------------------


class TestPeerSimilarityFunction:
    """Tests for the check_peer_similarity() standalone function."""

    @pytest_asyncio.fixture
    async def db(self, tmp_path):
        """Create an in-memory DB with ward room schema."""
        import aiosqlite
        from probos.ward_room.models import _SCHEMA
        db = await aiosqlite.connect(":memory:")
        await db.executescript(_SCHEMA)
        await db.commit()
        yield db
        await db.close()

    @pytest.mark.asyncio
    async def test_no_recent_posts(self, db) -> None:
        """Empty channel returns no matches."""
        from probos.ward_room.threads import check_peer_similarity

        # Create a channel
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ch1", "test", "department", "system", time.time()),
        )
        await db.commit()

        result = await check_peer_similarity(db, "ch1", "author1", "some content")
        assert result == []

    @pytest.mark.asyncio
    async def test_only_self_posts_ignored(self, db) -> None:
        """Posts by the same author return no matches."""
        from probos.ward_room.threads import check_peer_similarity

        now = time.time()
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ch1", "test", "department", "system", now),
        )
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "ch1", "author1", "Title", "this is my test content about topic alpha", now, now, "Alpha"),
        )
        await db.commit()

        result = await check_peer_similarity(
            db, "ch1", "author1", "this is my test content about topic alpha",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_different_author_similar_content(self, db) -> None:
        """Similar content by different authors returns a match."""
        from probos.ward_room.threads import check_peer_similarity

        now = time.time()
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ch1", "test", "department", "system", now),
        )
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "ch1", "agent-b", "Topic", "the system latency is elevated and response times are slow", now, now, "Bravo"),
        )
        await db.commit()

        result = await check_peer_similarity(
            db, "ch1", "agent-a",
            "the system latency is elevated and response times are slow",
        )
        assert len(result) >= 1
        assert result[0]["author_id"] == "agent-b"
        assert result[0]["similarity"] >= 0.5

    @pytest.mark.asyncio
    async def test_below_threshold_no_match(self, db) -> None:
        """Content below similarity threshold returns no matches."""
        from probos.ward_room.threads import check_peer_similarity

        now = time.time()
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ch1", "test", "department", "system", now),
        )
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "ch1", "agent-b", "Topic", "apples oranges bananas grapes", now, now, "Bravo"),
        )
        await db.commit()

        result = await check_peer_similarity(
            db, "ch1", "agent-a",
            "quantum physics molecular biology chemistry",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_window_respected(self, db) -> None:
        """Posts outside window are ignored."""
        from probos.ward_room.threads import check_peer_similarity

        old_time = time.time() - 1200  # 20 min ago
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("ch1", "test", "department", "system", old_time),
        )
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "ch1", "agent-b", "Topic", "the system latency is elevated", old_time, old_time, "Bravo"),
        )
        await db.commit()

        # Default window is 600s (10 min), post is 20 min ago
        result = await check_peer_similarity(
            db, "ch1", "agent-a", "the system latency is elevated",
        )
        assert result == []


class TestPeerDetectionInCreateThread:
    """Tests for peer detection wired into create_thread()."""

    @pytest_asyncio.fixture
    async def ward_room(self, tmp_path):
        events = []

        def capture_event(event_type, data):
            events.append({"type": event_type, "data": data})

        from probos.ward_room import WardRoomService
        svc = WardRoomService(db_path=str(tmp_path / "wr.db"), emit_event=capture_event)
        await svc.start()
        svc._captured_events = events
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_thread_created_despite_similarity(self, ward_room) -> None:
        """Thread is still created even when peer similarity detected."""
        # Create channel
        ch = await ward_room.create_channel("test", "department", "system")

        # First agent posts
        t1 = await ward_room.create_thread(
            ch.id, "agent-a", "Latency Analysis",
            "the system latency is elevated and response times are very slow today",
            author_callsign="Alpha",
        )
        assert t1 is not None

        # Second agent posts similar content — thread should still be created
        t2 = await ward_room.create_thread(
            ch.id, "agent-b", "Performance Issues",
            "the system latency is elevated and response times are very slow today",
            author_callsign="Bravo",
        )
        assert t2 is not None
        assert t2.id != t1.id  # Different threads

    @pytest.mark.asyncio
    async def test_peer_repetition_event_emitted_on_thread(self, ward_room) -> None:
        """PEER_REPETITION_DETECTED event emitted when thread has peer similarity."""
        ch = await ward_room.create_channel("test", "department", "system")

        await ward_room.create_thread(
            ch.id, "agent-a", "Latency",
            "the system latency is elevated and response times are very slow today",
            author_callsign="Alpha",
        )

        await ward_room.create_thread(
            ch.id, "agent-b", "Latency Too",
            "the system latency is elevated and response times are very slow today",
            author_callsign="Bravo",
        )

        peer_events = [
            e for e in ward_room._captured_events
            if e["type"] == EventType.PEER_REPETITION_DETECTED
        ]
        assert len(peer_events) >= 1
        assert peer_events[0]["data"]["author_id"] == "agent-b"
        assert peer_events[0]["data"]["post_type"] == "thread"


class TestPeerDetectionInCreatePost:
    """Tests for peer detection in create_post()."""

    @pytest_asyncio.fixture
    async def ward_room(self, tmp_path):
        events = []

        def capture_event(event_type, data):
            events.append({"type": event_type, "data": data})

        from probos.ward_room import WardRoomService
        svc = WardRoomService(db_path=str(tmp_path / "wr.db"), emit_event=capture_event)
        await svc.start()
        svc._captured_events = events
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_peer_repetition_event_emitted_on_reply(self, ward_room) -> None:
        """PEER_REPETITION_DETECTED event emitted on similar reply."""
        ch = await ward_room.create_channel("test", "department", "system")
        t = await ward_room.create_thread(
            ch.id, "agent-a", "Topic",
            "the system latency is elevated and response times slow",
            author_callsign="Alpha",
        )

        # Clear events from thread creation
        ward_room._captured_events.clear()

        # Reply with similar content from different agent
        await ward_room.create_post(
            t.id, "agent-b",
            "the system latency is elevated and response times slow",
            author_callsign="Bravo",
        )

        peer_events = [
            e for e in ward_room._captured_events
            if e["type"] == EventType.PEER_REPETITION_DETECTED
        ]
        assert len(peer_events) >= 1
        assert peer_events[0]["data"]["post_type"] == "reply"


class TestPeerRepetitionEventType:
    """Verify PEER_REPETITION_DETECTED event type and dataclass."""

    def test_event_type_exists(self) -> None:
        assert hasattr(EventType, "PEER_REPETITION_DETECTED")
        assert EventType.PEER_REPETITION_DETECTED.value == "peer_repetition_detected"

    def test_event_dataclass(self) -> None:
        from probos.events import PeerRepetitionDetectedEvent
        evt = PeerRepetitionDetectedEvent(
            channel_id="ch1", author_id="a1", match_count=2,
            top_similarity=0.85, post_type="thread",
        )
        d = evt.to_dict()
        assert d["type"] == "peer_repetition_detected"
        assert d["data"]["match_count"] == 2


# ---------------------------------------------------------------------------
# Part 2: Tier credits
# ---------------------------------------------------------------------------


class TestTierCreditFields:
    """Verify tier credit fields on CognitiveProfile and CounselorAssessment."""

    def test_profile_self_corrections_default(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile
        p = CognitiveProfile()
        assert p.self_corrections == 0
        assert p.peer_catches == 0

    def test_assessment_tier_credit_default(self) -> None:
        from probos.cognitive.counselor import CounselorAssessment
        a = CounselorAssessment()
        assert a.tier_credit == ""

    def test_add_assessment_increments_self_corrections(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        p = CognitiveProfile(agent_id="a1")
        a = CounselorAssessment(
            agent_id="a1", timestamp=time.time(),
            wellness_score=0.9, tier_credit="self_correction",
        )
        p.add_assessment(a)
        assert p.self_corrections == 1

    def test_sustained_self_corrections_recover_yellow_to_green(self) -> None:
        """Sustained self-corrections can recover yellow -> green alert level."""
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment

        p = CognitiveProfile(agent_id="a1")

        # First, push into yellow with a concerning assessment
        bad = CounselorAssessment(
            agent_id="a1", timestamp=1.0,
            wellness_score=0.4,  # Below yellow threshold
            concerns=["concern1", "concern2", "concern3"],
        )
        p.add_assessment(bad)
        assert p.alert_level == "yellow"

        # Now add 3+ self-correction credits
        for i in range(3):
            a = CounselorAssessment(
                agent_id="a1", timestamp=2.0 + i,
                wellness_score=0.9, tier_credit="self_correction",
            )
            p.add_assessment(a)

        assert p.self_corrections == 3
        assert p.alert_level == "green"

    def test_self_corrections_cannot_override_red(self) -> None:
        """Self-corrections cannot override red (not fit_for_duty)."""
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment

        p = CognitiveProfile(agent_id="a1")

        # Push into red
        bad = CounselorAssessment(
            agent_id="a1", timestamp=1.0,
            wellness_score=0.1, fit_for_duty=False,
        )
        p.add_assessment(bad)
        assert p.alert_level == "red"

        # Add self-correction credits — should NOT override red
        for i in range(5):
            a = CounselorAssessment(
                agent_id="a1", timestamp=2.0 + i,
                wellness_score=0.9, fit_for_duty=False,
                tier_credit="self_correction",
            )
            p.add_assessment(a)

        assert p.alert_level == "red"

    def test_peer_catch_increments(self) -> None:
        from probos.cognitive.counselor import CognitiveProfile, CounselorAssessment
        p = CognitiveProfile(agent_id="a1")
        a = CounselorAssessment(
            agent_id="a1", timestamp=time.time(),
            wellness_score=0.9, tier_credit="peer_catch",
        )
        p.add_assessment(a)
        assert p.peer_catches == 1


class TestCounselorEventSubscriptions:
    """Verify Counselor subscribes to new event types."""

    @pytest.mark.asyncio
    async def test_subscribes_to_zone_recovery_and_peer_repetition(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))

        subscribed_types = []

        def mock_listener(handler, event_types=None):
            if event_types:
                subscribed_types.extend(event_types)

        await agent.initialize(add_event_listener_fn=mock_listener)

        assert EventType.ZONE_RECOVERY in subscribed_types
        assert EventType.PEER_REPETITION_DETECTED in subscribed_types


class TestZoneRecoveryHandler:
    """Test _on_zone_recovery() credits only amber->green."""

    @pytest.mark.asyncio
    async def test_amber_to_green_gets_credit(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._trust_network = MagicMock()
        agent._trust_network.score = MagicMock(return_value=0.7)
        agent._hebbian_router = None
        agent._registry = None
        agent._crew_profiles = None
        agent._save_profile_and_assessment = AsyncMock()

        await agent._on_zone_recovery({
            "agent_id": "agent-x",
            "old_zone": "amber",
            "new_zone": "green",
        })

        profile = agent.get_profile("agent-x")
        assert profile is not None
        assert profile.self_corrections == 1

    @pytest.mark.asyncio
    async def test_red_to_amber_no_credit(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._trust_network = MagicMock()
        agent._trust_network.score = MagicMock(return_value=0.7)
        agent._hebbian_router = None
        agent._registry = None
        agent._crew_profiles = None
        agent._save_profile_and_assessment = AsyncMock()

        await agent._on_zone_recovery({
            "agent_id": "agent-x",
            "old_zone": "red",
            "new_zone": "amber",
        })

        profile = agent.get_profile("agent-x")
        # Profile should not exist or have 0 self_corrections
        # (handler returns early for non-amber→green transitions)
        assert profile is None or profile.self_corrections == 0


class TestPeerRepetitionHandler:
    """Test _on_peer_repetition_detected() updates peer_catches."""

    @pytest.mark.asyncio
    async def test_peer_catches_incremented(self) -> None:
        from probos.cognitive.counselor import CounselorAgent

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._trust_network = MagicMock()
        agent._trust_network.score = MagicMock(return_value=0.7)
        agent._hebbian_router = None
        agent._registry = None
        agent._crew_profiles = None
        agent._save_profile_and_assessment = AsyncMock()

        await agent._on_peer_repetition_detected({
            "author_id": "agent-y",
            "author_callsign": "Yankee",
            "match_count": 2,
        })

        profile = agent.get_profile("agent-y")
        assert profile is not None
        assert profile.peer_catches == 1


# ---------------------------------------------------------------------------
# Part 3: Peer repetition episode
# ---------------------------------------------------------------------------


class TestPeerRepetitionEpisode:
    """Verify peer repetition episode stored for the repeating agent."""

    @pytest_asyncio.fixture
    async def ward_room_with_memory(self, tmp_path):
        events = []
        episodes = []

        def capture_event(event_type, data):
            events.append({"type": event_type, "data": data})

        mem = AsyncMock()
        mem.store = AsyncMock(side_effect=lambda ep: episodes.append(ep))

        from probos.ward_room import WardRoomService
        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=capture_event,
            episodic_memory=mem,
        )
        await svc.start()
        svc._captured_events = events
        svc._captured_episodes = episodes
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_peer_repetition_episode_stored(self, ward_room_with_memory) -> None:
        """Peer repetition episode has intent='peer_repetition'."""
        svc = ward_room_with_memory
        ch = await svc.create_channel("test", "department", "system")

        await svc.create_thread(
            ch.id, "agent-a", "Latency",
            "the system latency is elevated and response times are very slow today",
            author_callsign="Alpha",
        )
        await svc.create_thread(
            ch.id, "agent-b", "Also Latency",
            "the system latency is elevated and response times are very slow today",
            author_callsign="Bravo",
        )

        peer_episodes = [
            ep for ep in svc._captured_episodes
            if any(o.get("intent") == "peer_repetition" for o in getattr(ep, "outcomes", []))
        ]
        assert len(peer_episodes) >= 1

    @pytest.mark.asyncio
    async def test_peer_episode_agent_ids(self, ward_room_with_memory) -> None:
        """Peer repetition episode is stored for the repeating agent."""
        svc = ward_room_with_memory
        ch = await svc.create_channel("test", "department", "system")

        await svc.create_thread(
            ch.id, "agent-a", "Topic",
            "the system latency is elevated and response times slow today",
            author_callsign="Alpha",
        )
        await svc.create_thread(
            ch.id, "agent-b", "Topic",
            "the system latency is elevated and response times slow today",
            author_callsign="Bravo",
        )

        peer_episodes = [
            ep for ep in svc._captured_episodes
            if any(o.get("intent") == "peer_repetition" for o in getattr(ep, "outcomes", []))
        ]
        assert len(peer_episodes) >= 1
        # The repeating agent (agent-b) should get the episode
        assert "agent-b" in peer_episodes[0].agent_ids

    @pytest.mark.asyncio
    async def test_peer_episode_source_direct(self, ward_room_with_memory) -> None:
        """Peer repetition episode source is 'direct'."""
        svc = ward_room_with_memory
        ch = await svc.create_channel("test", "department", "system")

        await svc.create_thread(
            ch.id, "agent-a", "Topic",
            "the system latency is elevated and response times are very slow",
            author_callsign="Alpha",
        )
        await svc.create_thread(
            ch.id, "agent-b", "Topic",
            "the system latency is elevated and response times are very slow",
            author_callsign="Bravo",
        )

        peer_episodes = [
            ep for ep in svc._captured_episodes
            if any(o.get("intent") == "peer_repetition" for o in getattr(ep, "outcomes", []))
        ]
        assert len(peer_episodes) >= 1
        assert peer_episodes[0].source == "direct"


# ---------------------------------------------------------------------------
# Part 4: Profile store persistence
# ---------------------------------------------------------------------------


class TestProfileStorePersistence:
    """Verify new fields persist through save/load cycle."""

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        from probos.cognitive.counselor import CounselorProfileStore
        s = CounselorProfileStore(data_dir=tmp_path)
        await s.start()
        yield s
        await s.stop()

    @pytest.mark.asyncio
    async def test_profile_persists_tier_credit_fields(self, store) -> None:
        """save_profile() persists self_corrections and peer_catches."""
        from probos.cognitive.counselor import CognitiveProfile
        p = CognitiveProfile(
            agent_id="a1", agent_type="test",
            self_corrections=5, peer_catches=3,
            last_self_correction=123.0,
            last_peer_catch=456.0,
        )
        await store.save_profile(p)

        loaded = await store.load_profile("a1")
        assert loaded is not None
        assert loaded.self_corrections == 5
        assert loaded.peer_catches == 3
        assert loaded.last_self_correction == 123.0
        assert loaded.last_peer_catch == 456.0

    @pytest.mark.asyncio
    async def test_assessment_persists_tier_credit(self, store) -> None:
        """save_assessment() persists tier_credit field."""
        from probos.cognitive.counselor import CounselorAssessment, CognitiveProfile

        # Must create profile first (FK)
        p = CognitiveProfile(agent_id="a1", agent_type="test")
        await store.save_profile(p)

        a = CounselorAssessment(
            agent_id="a1", timestamp=time.time(),
            wellness_score=0.9, tier_credit="self_correction",
        )
        await store.save_assessment(a)

        history = await store.get_assessment_history("a1")
        assert len(history) >= 1
        assert history[0].tier_credit == "self_correction"
