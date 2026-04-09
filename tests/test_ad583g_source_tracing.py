"""Tests for AD-583g: Ward Room thread echo detection and source tracing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_posts(entries: list[tuple[str, str, str, float]]) -> list[dict]:
    """Build flat temporal post list.

    entries: [(post_id, author_id, body, created_at), ...]
    First entry is treated as the thread body (parent_id=None).
    """
    posts = []
    for i, (pid, author, body, ts) in enumerate(entries):
        posts.append({
            "id": pid,
            "thread_id": "thread-1",
            "parent_id": None if i == 0 else entries[0][0],
            "author_id": author,
            "author_callsign": author.title(),
            "body": body,
            "created_at": ts,
        })
    return posts


class FakeThreadManager:
    """Test double implementing ThreadManagerProtocol."""

    def __init__(self, posts: list[dict] | None = None):
        self._posts = posts or []

    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict]:
        return list(self._posts)


# ---------------------------------------------------------------------------
# ThreadEchoAnalyzer tests
# ---------------------------------------------------------------------------


class TestThreadEchoAnalyzerConstruction:
    def test_accepts_protocol_and_config(self):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        tm = FakeThreadManager()
        analyzer = ThreadEchoAnalyzer(tm, min_chain_length=2, similarity_threshold=0.5)
        assert analyzer._min_chain_length == 2
        assert analyzer._similarity_threshold == 0.5

    def test_config_defaults(self):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager())
        assert analyzer._min_chain_length == 3
        assert analyzer._similarity_threshold == 0.4


class TestSourceTracingConfig:
    def test_config_exists(self):
        from probos.config import SourceTracingConfig
        cfg = SourceTracingConfig()
        assert cfg.echo_min_chain_length == 3
        assert cfg.echo_similarity_threshold == 0.4
        assert cfg.echo_analysis_enabled is True

    def test_in_system_config(self):
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "source_tracing")
        assert cfg.source_tracing.echo_analysis_enabled is True


class TestGetThreadPostsTemporal:
    def test_returns_flat_list(self):
        posts = _make_posts([
            ("p1", "alice", "hi", 1.0),
            ("p2", "bob", "hello", 2.0),
        ])
        tm = FakeThreadManager(posts)
        result = asyncio.get_event_loop().run_until_complete(
            tm.get_thread_posts_temporal("t1")
        )
        # Flat list, no nesting
        assert len(result) == 2
        for p in result:
            assert "children" not in p

    def test_includes_thread_body_first(self):
        posts = _make_posts([
            ("p1", "alice", "thread body here", 1.0),
            ("p2", "bob", "reply", 2.0),
        ])
        tm = FakeThreadManager(posts)
        result = asyncio.get_event_loop().run_until_complete(
            tm.get_thread_posts_temporal("t1")
        )
        assert result[0]["body"] == "thread body here"
        assert result[0]["parent_id"] is None

    def test_includes_parent_id(self):
        posts = _make_posts([
            ("p1", "alice", "root", 1.0),
            ("p2", "bob", "reply to root", 2.0),
        ])
        tm = FakeThreadManager(posts)
        result = asyncio.get_event_loop().run_until_complete(
            tm.get_thread_posts_temporal("t1")
        )
        assert result[1]["parent_id"] == "p1"


class TestEchoChainDetection:
    """Test echo chain detection with 3+ agents echoing same content."""

    @pytest.fixture
    def echo_posts(self):
        """3 agents all saying roughly the same thing."""
        return _make_posts([
            ("p1", "alice", "the game state is broken and stale", 1.0),
            ("p2", "bob", "I agree the game state is broken stale", 2.0),
            ("p3", "carol", "yes the game state appears broken and stale", 3.0),
        ])

    @pytest.fixture
    def echo_posts_4(self):
        """4 agents echoing."""
        return _make_posts([
            ("p1", "alice", "system health is critical failure detected", 1.0),
            ("p2", "bob", "I confirm system health critical failure", 2.0),
            ("p3", "carol", "system health shows critical failure state", 3.0),
            ("p4", "dave", "critical failure in system health detected", 4.0),
        ])

    def test_echo_chain_detected_three_agents(self, echo_posts):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(echo_posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        assert result.echo_detected is True

    def test_echo_chain_detected_four_agents(self, echo_posts_4):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(echo_posts_4), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        assert result.echo_detected is True
        assert result.chain_length >= 4

    def test_source_identification(self, echo_posts):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(echo_posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        assert result.source_callsign == "Alice"
        assert result.source_post_id == "p1"

    def test_propagation_order(self, echo_posts):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(echo_posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        timestamps = [step.timestamp for step in result.propagation_chain]
        assert timestamps == sorted(timestamps)

    def test_similarity_scores(self, echo_posts):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(echo_posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        for step in result.propagation_chain:
            assert step.similarity_to_source > 0

    def test_independence_score_low_same_thread(self, echo_posts):
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(echo_posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        # All posts in same thread → independence should be low
        assert result.anchor_independence_score < 0.5


class TestNoEchoDetection:
    def test_short_thread(self):
        """< min_chain_length unique authors → no echo."""
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        posts = _make_posts([
            ("p1", "alice", "hello world", 1.0),
            ("p2", "bob", "hello world echo", 2.0),
        ])
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        assert result.echo_detected is False

    def test_dissimilar_posts(self):
        """Posts below similarity threshold → no echo."""
        from probos.ward_room.thread_echo import ThreadEchoAnalyzer
        posts = _make_posts([
            ("p1", "alice", "the weather is nice today sunshine", 1.0),
            ("p2", "bob", "database migration script failed badly", 2.0),
            ("p3", "carol", "quantum physics entanglement research paper", 3.0),
        ])
        analyzer = ThreadEchoAnalyzer(FakeThreadManager(posts), min_chain_length=3)
        result = asyncio.get_event_loop().run_until_complete(
            analyzer.analyze("thread-1")
        )
        assert result.echo_detected is False


class TestDataclassFields:
    def test_echo_result_fields(self):
        from probos.ward_room.thread_echo import ThreadEchoResult
        result = ThreadEchoResult(
            echo_detected=True,
            thread_id="t1",
            source_post_id="p1",
            source_callsign="Alice",
            source_timestamp=1.0,
            chain_length=3,
            anchor_independence_score=0.1,
        )
        assert result.echo_detected is True
        assert result.thread_id == "t1"
        assert result.source_post_id == "p1"
        assert result.source_callsign == "Alice"
        assert result.chain_length == 3
        assert result.anchor_independence_score == 0.1

    def test_propagation_step_fields(self):
        from probos.ward_room.thread_echo import PropagationStep
        step = PropagationStep(
            callsign="Bob",
            post_id="p2",
            timestamp=2.0,
            similarity_to_source=0.8,
        )
        assert step.callsign == "Bob"
        assert step.post_id == "p2"
        assert step.timestamp == 2.0
        assert step.similarity_to_source == 0.8


class TestWardRoomEchoEvent:
    def test_event_type_exists(self):
        from probos.events import EventType
        assert hasattr(EventType, "WARD_ROOM_ECHO_DETECTED")
        assert EventType.WARD_ROOM_ECHO_DETECTED.value == "ward_room_echo_detected"

    def test_event_serialization(self):
        from probos.events import WardRoomEchoDetectedEvent
        event = WardRoomEchoDetectedEvent(
            thread_id="t1",
            channel_id="c1",
            source_callsign="Alice",
            chain_length=3,
            independence_score=0.1,
            affected_callsigns=["Bob", "Carol"],
        )
        d = event.to_dict()
        assert d["thread_id"] == "t1"
        assert d["chain_length"] == 3
        assert d["source_callsign"] == "Alice"
        assert d["affected_callsigns"] == ["Bob", "Carol"]
        assert d["source"] == "ward_room_echo"


class TestBridgeAlertEcho:
    def _make_service(self):
        from probos.bridge_alerts import BridgeAlertService
        svc = BridgeAlertService.__new__(BridgeAlertService)
        svc._recent = {}
        svc._alert_log = []
        svc._max_log = 200
        svc._cooldown = 300.0
        svc._resolve_clean_period = 3600.0
        svc._default_dismiss_duration = 14400.0
        # AD-580 attributes
        svc._dismissed = {}
        svc._resolved = {}
        svc._muted = set()
        svc._last_detected = {}
        return svc

    def test_fires_on_echo(self):
        svc = self._make_service()
        alerts = svc.check_ward_room_echo({
            "echo_detected": True,
            "chain_length": 3,
            "anchor_independence_score": 0.1,
            "source_callsign": "Alice",
            "thread_id": "t1",
            "affected_callsigns": ["Bob", "Carol"],
        })
        assert len(alerts) == 1
        assert alerts[0].alert_type == "ward_room_echo_detected"

    def test_dedup_echo(self):
        svc = self._make_service()
        data = {
            "echo_detected": True,
            "chain_length": 3,
            "anchor_independence_score": 0.1,
            "source_callsign": "Alice",
            "thread_id": "t1",
            "affected_callsigns": ["Bob", "Carol"],
        }
        svc.check_ward_room_echo(data)
        second = svc.check_ward_room_echo(data)
        assert len(second) == 0  # Dedup suppressed
