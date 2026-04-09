"""AD-569: Behavioral Metrics Tests — Observation-Grounded Crew Intelligence.

Tests across 11 test classes covering:
- Config (3)
- Snapshot (3)
- Engine lifecycle (4)
- Frame Diversity (4)
- Synthesis Detection (3)
- Cross-Dept Triggers (3)
- Convergence Correctness (3)
- Anchor-Grounded Emergence (3)
- Full computation integration (3)
- Probes (5)
- API routes (2)
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.behavioral_metrics import (
    BehavioralMetricsEngine,
    BehavioralSnapshot,
)
from probos.config import BehavioralMetricsConfig, SystemConfig
from probos.events import EventType


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockThread:
    def __init__(
        self,
        thread_id: str,
        channel_id: str = "ch-1",
        channel_name: str = "engineering",
        title: str = "Test Thread",
    ):
        self.id = thread_id
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.title = title


class MockWardRoom:
    def __init__(self, threads_data: list[dict]):
        self._threads = threads_data

    async def browse_threads(self, agent_id="", channels=None, limit=50, since=0.0):
        return [td["thread"] for td in self._threads]

    async def get_thread(self, thread_id: str):
        for td in self._threads:
            if td["thread"].id == thread_id:
                return {"posts": td["posts"]}
        return None


def _make_post(
    author_id: str,
    body: str,
    post_id: str = "",
    created_at: float = 0.0,
    author_callsign: str = "",
) -> dict:
    return {
        "id": post_id or f"post-{author_id}",
        "author_id": author_id,
        "author_callsign": author_callsign or author_id,
        "body": body,
        "created_at": created_at or time.time(),
    }


def _make_thread_data(
    thread_id: str,
    posts: list[dict],
    channel_name: str = "engineering",
    title: str = "Test Thread",
) -> dict:
    return {
        "thread": MockThread(thread_id, channel_name=channel_name, title=title),
        "posts": posts,
    }


def _dept_fn(author_id: str) -> str | None:
    """Simple department lookup by author prefix."""
    dept_map = {
        "eng-": "engineering",
        "sci-": "science",
        "sec-": "security",
        "med-": "medical",
        "ops-": "operations",
    }
    for prefix, dept in dept_map.items():
        if author_id.startswith(prefix):
            return dept
    return None


# ---------------------------------------------------------------------------
# Test Class 1: BehavioralMetricsConfig
# ---------------------------------------------------------------------------

class TestBehavioralMetricsConfig:

    def test_default_config(self):
        cfg = BehavioralMetricsConfig()
        assert cfg.thread_lookback_hours == 72.0
        assert cfg.min_thread_contributors == 2
        assert cfg.min_thread_posts == 3
        assert cfg.synthesis_novelty_threshold == 0.35
        assert cfg.max_snapshots == 100

    def test_custom_config(self):
        cfg = BehavioralMetricsConfig(
            thread_lookback_hours=48.0,
            synthesis_novelty_threshold=0.5,
            max_snapshots=50,
        )
        assert cfg.thread_lookback_hours == 48.0
        assert cfg.synthesis_novelty_threshold == 0.5
        assert cfg.max_snapshots == 50

    def test_config_on_system_config(self):
        sc = SystemConfig()
        assert isinstance(sc.behavioral_metrics, BehavioralMetricsConfig)
        assert sc.behavioral_metrics.thread_lookback_hours == 72.0


# ---------------------------------------------------------------------------
# Test Class 2: BehavioralSnapshot
# ---------------------------------------------------------------------------

class TestBehavioralSnapshot:

    def test_default_snapshot(self):
        s = BehavioralSnapshot()
        assert s.timestamp == 0.0
        assert s.behavioral_quality_score == 0.0
        assert s.frame_diversity_score == 0.0
        assert s.synthesis_rate == 0.0
        assert s.convergence_correctness_rate is None
        assert s.threads_analyzed == 0

    def test_to_dict(self):
        s = BehavioralSnapshot(timestamp=1000.0, threads_analyzed=5)
        d = s.to_dict()
        assert isinstance(d, dict)
        assert d["timestamp"] == 1000.0
        assert d["threads_analyzed"] == 5
        assert "behavioral_quality_score" in d
        assert "frame_diversity_score" in d

    def test_snapshot_with_data(self):
        s = BehavioralSnapshot(
            timestamp=time.time(),
            frame_diversity_score=0.45,
            synthesis_rate=0.3,
            cross_dept_trigger_rate=0.1,
            convergence_events=5,
            anchor_grounded_rate=0.6,
            behavioral_quality_score=0.35,
            threads_analyzed=10,
        )
        assert s.frame_diversity_score == 0.45
        assert s.synthesis_rate == 0.3
        assert s.behavioral_quality_score == 0.35


# ---------------------------------------------------------------------------
# Test Class 3: BehavioralMetricsEngine lifecycle
# ---------------------------------------------------------------------------

class TestBehavioralMetricsEngine:

    def test_engine_init(self):
        cfg = BehavioralMetricsConfig(max_snapshots=50)
        engine = BehavioralMetricsEngine(cfg)
        assert engine._config.max_snapshots == 50

    def test_latest_snapshot_none(self):
        engine = BehavioralMetricsEngine()
        assert engine.latest_snapshot is None

    def test_snapshots_empty(self):
        engine = BehavioralMetricsEngine()
        assert engine.snapshots == []

    def test_snapshot_history_limit(self):
        cfg = BehavioralMetricsConfig(max_snapshots=3)
        engine = BehavioralMetricsEngine(cfg)
        for i in range(5):
            engine._snapshots.append(BehavioralSnapshot(timestamp=float(i)))
        assert len(engine.snapshots) == 3
        assert engine.latest_snapshot.timestamp == 4.0


# ---------------------------------------------------------------------------
# Test Class 4: Frame Diversity (Metric 1)
# ---------------------------------------------------------------------------

class TestFrameDiversity:

    def test_frame_diversity_multi_dept(self):
        """Two departments with different content -> positive diversity."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "eng-1", "body": "The warp core efficiency has dropped 12 percent"},
                {"author_id": "sci-1", "body": "Quantum resonance patterns indicate tachyon interference"},
                {"author_id": "eng-2", "body": "Plasma conduits show thermal variance in section 14"},
            ],
            "unique_authors": {"eng-1", "sci-1", "eng-2"},
            "channel_id": "ch-1",
            "channel_name": "engineering",
            "title": "Test",
        }]

        with patch("probos.cognitive.behavioral_metrics.embed_text") as mock_embed, \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity") as mock_sim:
            # Different embeddings for different departments
            mock_embed.side_effect = lambda t: [0.1, 0.2] if "warp" in t or "plasma" in t else [0.8, 0.9]
            mock_sim.return_value = 0.3  # Low similarity = high diversity

            result = engine._compute_frame_diversity(threads, _dept_fn)
            assert result["score"] > 0.0
            assert result["threads"] == 1

    def test_frame_diversity_single_dept(self):
        """Only one department -> no diversity analysis."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "eng-1", "body": "Engineering report"},
                {"author_id": "eng-2", "body": "Engineering follow-up"},
            ],
            "unique_authors": {"eng-1", "eng-2"},
            "channel_id": "ch-1",
            "channel_name": "engineering",
            "title": "Test",
        }]

        result = engine._compute_frame_diversity(threads, _dept_fn)
        assert result["score"] == 0.0

    def test_frame_diversity_no_department_fn(self):
        """No get_department function -> score 0."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [{"author_id": "a1", "body": "test"}],
            "unique_authors": {"a1"},
            "channel_id": "ch-1",
            "channel_name": "ch",
            "title": "Test",
        }]

        result = engine._compute_frame_diversity(threads, None)
        assert result["score"] == 0.0

    def test_frame_diversity_identical_posts(self):
        """Same content from different departments -> low diversity."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "eng-1", "body": "Identical report content"},
                {"author_id": "sci-1", "body": "Identical report content"},
            ],
            "unique_authors": {"eng-1", "sci-1"},
            "channel_id": "ch-1",
            "channel_name": "cross",
            "title": "Test",
        }]

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5, 0.5]), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.99):
            result = engine._compute_frame_diversity(threads, _dept_fn)
            # 1 - 0.99 = 0.01 diversity
            assert result["score"] < 0.1
            assert result["threads"] == 1


# ---------------------------------------------------------------------------
# Test Class 5: Synthesis Detection (Metric 2)
# ---------------------------------------------------------------------------

class TestSynthesisDetection:

    def test_synthesis_detected(self):
        """Diverse thread -> synthesis rate > 0."""
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(synthesis_min_thread_posts=3))
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Analysis of warp field dynamics"},
                {"author_id": "a2", "body": "Plasma flow rates in the EPS grid"},
                {"author_id": "a3", "body": "Subspace interference at the dilithium matrix"},
                {"author_id": "a4", "body": "Cross-referencing quantum signatures"},
            ],
            "unique_authors": {"a1", "a2", "a3", "a4"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Analysis",
        }]

        call_count = 0

        def fake_embed(text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [0.1, 0.2, 0.3]  # Thread embedding (combined)
            return [0.9, 0.8, 0.7]  # Individual posts (all similar to each other)

        with patch("probos.cognitive.behavioral_metrics.embed_text", side_effect=fake_embed), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.4):
            result = engine._compute_synthesis_detection(threads)
            # 1 - 0.4 = 0.6 novelty > 0.35 threshold
            assert result["rate"] > 0.0
            assert result["threads_with_synthesis"] >= 1

    def test_no_synthesis_similar_posts(self):
        """Thread embedding very similar to individual posts -> no synthesis."""
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(synthesis_min_thread_posts=3))
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Test content A"},
                {"author_id": "a2", "body": "Test content B"},
                {"author_id": "a3", "body": "Test content C"},
                {"author_id": "a4", "body": "Test content D"},
            ],
            "unique_authors": {"a1", "a2", "a3", "a4"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Test",
        }]

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.95):
            result = engine._compute_synthesis_detection(threads)
            assert result["rate"] == 0.0

    def test_synthesis_below_min_posts(self):
        """Too few posts -> not eligible."""
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(synthesis_min_thread_posts=4))
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Post A"},
                {"author_id": "a2", "body": "Post B"},
                {"author_id": "a3", "body": "Post C"},
            ],
            "unique_authors": {"a1", "a2", "a3"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Test",
        }]

        result = engine._compute_synthesis_detection(threads)
        assert result["rate"] == 0.0
        assert result["threads_with_synthesis"] == 0


# ---------------------------------------------------------------------------
# Test Class 6: Cross-Dept Triggers (Metric 3)
# ---------------------------------------------------------------------------

class TestCrossDeptTriggers:

    def test_trigger_detected(self):
        """Sequential cross-dept similar topics -> triggers."""
        engine = BehavioralMetricsEngine()
        now = time.time()
        threads = [
            {
                "thread_id": "t1",
                "posts": [
                    {"author_id": "eng-1", "body": "Warp core anomaly detected", "created_at": now - 3600},
                    {"author_id": "eng-2", "body": "Confirming anomaly", "created_at": now - 3500},
                ],
                "unique_authors": {"eng-1", "eng-2"},
                "channel_id": "ch-1",
                "channel_name": "engineering",
                "title": "Warp Core Anomaly",
            },
            {
                "thread_id": "t2",
                "posts": [
                    {"author_id": "sci-1", "body": "Investigating warp core anomaly signature", "created_at": now - 1800},
                    {"author_id": "sci-2", "body": "Running analysis", "created_at": now - 1700},
                ],
                "unique_authors": {"sci-1", "sci-2"},
                "channel_id": "ch-2",
                "channel_name": "science",
                "title": "Anomaly Investigation",
            },
        ]

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.8):
            result = engine._compute_cross_dept_triggers(threads, _dept_fn)
            assert result["events"] > 0
            assert result["rate"] > 0.0

    def test_no_trigger_single_dept(self):
        """Same department -> no cross-dept triggers."""
        engine = BehavioralMetricsEngine()
        now = time.time()
        threads = [
            {
                "thread_id": "t1",
                "posts": [
                    {"author_id": "eng-1", "body": "Report A", "created_at": now - 3600},
                    {"author_id": "eng-2", "body": "Report B", "created_at": now - 3500},
                ],
                "unique_authors": {"eng-1", "eng-2"},
                "channel_id": "ch-1",
                "channel_name": "engineering",
                "title": "Eng Report",
            },
        ]

        result = engine._compute_cross_dept_triggers(threads, _dept_fn)
        assert result["rate"] == 0.0
        assert result["events"] == 0

    def test_no_trigger_dissimilar_topics(self):
        """Cross-dept but different topics -> no triggers."""
        engine = BehavioralMetricsEngine()
        now = time.time()
        threads = [
            {
                "thread_id": "t1",
                "posts": [
                    {"author_id": "eng-1", "body": "Warp core efficiency", "created_at": now - 3600},
                    {"author_id": "eng-2", "body": "Confirming", "created_at": now - 3500},
                ],
                "unique_authors": {"eng-1", "eng-2"},
                "channel_id": "ch-1",
                "channel_name": "engineering",
                "title": "Warp",
            },
            {
                "thread_id": "t2",
                "posts": [
                    {"author_id": "sci-1", "body": "Biological samples from the planet surface", "created_at": now - 1800},
                    {"author_id": "sci-2", "body": "Analysis results", "created_at": now - 1700},
                ],
                "unique_authors": {"sci-1", "sci-2"},
                "channel_id": "ch-2",
                "channel_name": "science",
                "title": "Bio Samples",
            },
        ]

        with patch("probos.cognitive.behavioral_metrics.embed_text") as mock_embed, \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.1):
            mock_embed.return_value = [0.5] * 10
            result = engine._compute_cross_dept_triggers(threads, _dept_fn)
            assert result["events"] == 0


# ---------------------------------------------------------------------------
# Test Class 7: Convergence Correctness (Metric 4)
# ---------------------------------------------------------------------------

class TestConvergenceCorrectness:

    def test_convergence_detected(self):
        """Similar posts from multiple agents -> convergence event."""
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(convergence_min_agreeing=2))
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "The anomaly source is in sector 7"},
                {"author_id": "a2", "body": "Confirmed: the anomaly originates from sector 7"},
                {"author_id": "a3", "body": "My analysis also points to sector 7 as the source"},
            ],
            "unique_authors": {"a1", "a2", "a3"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Anomaly",
        }]

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.9):
            result = asyncio.get_event_loop().run_until_complete(
                engine._compute_convergence_correctness(threads)
            )
            assert result["total"] > 0
            assert result["unverified"] == result["total"]

    def test_convergence_unverified(self):
        """All convergence events are unverified (no ground truth yet)."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Same conclusion A"},
                {"author_id": "a2", "body": "Same conclusion B"},
                {"author_id": "a3", "body": "Same conclusion C"},
            ],
            "unique_authors": {"a1", "a2", "a3"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Test",
        }]

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.9):
            result = asyncio.get_event_loop().run_until_complete(
                engine._compute_convergence_correctness(threads)
            )
            assert result["correctness_rate"] is None
            assert result["correct"] == 0
            assert result["incorrect"] == 0

    def test_no_convergence_diverse_posts(self):
        """Very different posts -> no convergence."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Topic A about engineering"},
                {"author_id": "a2", "body": "Topic B about science"},
                {"author_id": "a3", "body": "Topic C about medicine"},
            ],
            "unique_authors": {"a1", "a2", "a3"},
            "channel_id": "ch-1",
            "channel_name": "cross",
            "title": "Test",
        }]

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.2):
            result = asyncio.get_event_loop().run_until_complete(
                engine._compute_convergence_correctness(threads)
            )
            assert result["total"] == 0


# ---------------------------------------------------------------------------
# Test Class 8: Anchor-Grounded Emergence (Metric 5)
# ---------------------------------------------------------------------------

class TestAnchorGroundedEmergence:

    @pytest.mark.asyncio
    async def test_anchor_analysis_with_memory(self):
        """Mock episodic memory + social_verification -> positive score."""
        engine = BehavioralMetricsEngine(
            BehavioralMetricsConfig(anchor_independence_min_episodes=2)
        )
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Analysis A"},
                {"author_id": "a2", "body": "Analysis B"},
            ],
            "unique_authors": {"a1", "a2"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Analysis",
        }]

        mock_memory = AsyncMock()
        mock_ep = MagicMock()
        mock_memory.recall = AsyncMock(return_value=[mock_ep, mock_ep])

        with patch(
            "probos.cognitive.social_verification.compute_anchor_independence",
            return_value=0.6,
        ):
            result = await engine._compute_anchor_grounded_emergence(threads, mock_memory)
            assert result["analyzed_threads"] == 1
            assert result["independence_score"] == 0.6
            assert result["grounded_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_anchor_no_memory(self):
        """No episodic memory -> zeros."""
        engine = BehavioralMetricsEngine()
        threads = [{
            "thread_id": "t1",
            "posts": [{"author_id": "a1", "body": "Test"}],
            "unique_authors": {"a1"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Test",
        }]

        result = await engine._compute_anchor_grounded_emergence(threads, None)
        assert result["grounded_rate"] == 0.0
        assert result["analyzed_threads"] == 0

    @pytest.mark.asyncio
    async def test_anchor_insufficient_episodes(self):
        """Fewer than min_episodes -> skipped."""
        engine = BehavioralMetricsEngine(
            BehavioralMetricsConfig(anchor_independence_min_episodes=5)
        )
        threads = [{
            "thread_id": "t1",
            "posts": [
                {"author_id": "a1", "body": "Analysis A"},
                {"author_id": "a2", "body": "Analysis B"},
            ],
            "unique_authors": {"a1", "a2"},
            "channel_id": "ch-1",
            "channel_name": "science",
            "title": "Analysis",
        }]

        mock_memory = AsyncMock()
        mock_memory.recall = AsyncMock(return_value=[MagicMock()])  # Only 1 episode per agent = 2 total < 5

        result = await engine._compute_anchor_grounded_emergence(threads, mock_memory)
        assert result["analyzed_threads"] == 0


# ---------------------------------------------------------------------------
# Test Class 9: Full computation integration
# ---------------------------------------------------------------------------

class TestComputeBehavioralMetrics:

    @pytest.mark.asyncio
    async def test_full_computation(self):
        """Mock ward_room with qualifying threads -> all metrics populated."""
        now = time.time()
        wr = MockWardRoom([
            _make_thread_data("t1", [
                _make_post("eng-1", "Warp core anomaly report", created_at=now - 100),
                _make_post("sci-1", "Scientific analysis of anomaly", created_at=now - 50),
                _make_post("eng-2", "Engineering follow-up", created_at=now - 30),
                _make_post("sci-2", "Additional data points", created_at=now - 10),
            ]),
        ])

        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(
            min_thread_contributors=2,
            min_thread_posts=3,
            synthesis_min_thread_posts=3,
        ))

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.5):
            snapshot = await engine.compute_behavioral_metrics(
                ward_room=wr,
                get_department=_dept_fn,
            )

        assert snapshot.threads_analyzed == 1
        assert snapshot.timestamp > 0
        assert engine.latest_snapshot is snapshot

    @pytest.mark.asyncio
    async def test_empty_threads(self):
        """No qualifying threads -> snapshot with zeros."""
        wr = MockWardRoom([])
        engine = BehavioralMetricsEngine()

        snapshot = await engine.compute_behavioral_metrics(ward_room=wr)
        assert snapshot.threads_analyzed == 0
        assert snapshot.behavioral_quality_score == 0.0
        assert engine.latest_snapshot is snapshot

    @pytest.mark.asyncio
    async def test_event_emission(self):
        """Verify BEHAVIORAL_METRICS_UPDATED event emitted."""
        now = time.time()
        wr = MockWardRoom([
            _make_thread_data("t1", [
                _make_post("eng-1", "Report A", created_at=now - 100),
                _make_post("sci-1", "Report B", created_at=now - 50),
                _make_post("eng-2", "Report C", created_at=now - 30),
            ]),
        ])

        engine = BehavioralMetricsEngine()
        emit_fn = AsyncMock()

        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
             patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.5):
            await engine.compute_behavioral_metrics(
                ward_room=wr,
                get_department=_dept_fn,
                emit_event_fn=emit_fn,
            )

        emit_fn.assert_called_once()
        call_args = emit_fn.call_args
        assert call_args[0][0] == EventType.BEHAVIORAL_METRICS_UPDATED


# ---------------------------------------------------------------------------
# Test Class 10: Probes
# ---------------------------------------------------------------------------

class TestBehavioralProbes:

    def _make_runtime_with_snapshot(self, **snapshot_kwargs) -> MagicMock:
        from probos.cognitive.behavioral_metrics import BehavioralSnapshot
        engine = BehavioralMetricsEngine()
        engine._snapshots.append(BehavioralSnapshot(
            timestamp=time.time(),
            frame_diversity_score=0.4,
            synthesis_rate=0.3,
            cross_dept_trigger_rate=0.2,
            convergence_events=5,
            convergence_correctness_rate=None,
            anchor_grounded_rate=0.5,
            anchor_independence_score=0.4,
            anchor_analyzed_threads=3,
            behavioral_quality_score=0.35,
            threads_analyzed=10,
            **snapshot_kwargs,
        ))
        runtime = MagicMock()
        runtime._behavioral_metrics_engine = engine
        return runtime

    @pytest.mark.asyncio
    async def test_frame_diversity_probe(self):
        from probos.cognitive.behavioral_probes import FrameDiversityProbe
        probe = FrameDiversityProbe()
        runtime = self._make_runtime_with_snapshot()
        result = await probe.run("__crew__", runtime)
        assert result.passed
        assert result.score == 0.4
        assert result.test_name == "frame_diversity"

    @pytest.mark.asyncio
    async def test_synthesis_probe(self):
        from probos.cognitive.behavioral_probes import SynthesisDetectionProbe
        probe = SynthesisDetectionProbe()
        runtime = self._make_runtime_with_snapshot()
        result = await probe.run("__crew__", runtime)
        assert result.passed
        assert result.score == 0.3

    @pytest.mark.asyncio
    async def test_cross_dept_trigger_probe(self):
        from probos.cognitive.behavioral_probes import CrossDeptTriggerProbe
        probe = CrossDeptTriggerProbe()
        runtime = self._make_runtime_with_snapshot()
        result = await probe.run("__crew__", runtime)
        assert result.passed
        assert result.score == 0.2

    @pytest.mark.asyncio
    async def test_convergence_correctness_probe(self):
        from probos.cognitive.behavioral_probes import ConvergenceCorrectnessProbe
        probe = ConvergenceCorrectnessProbe()
        runtime = self._make_runtime_with_snapshot()
        result = await probe.run("__crew__", runtime)
        assert result.passed
        assert result.score == 0.0  # correctness_rate is None -> 0.0

    @pytest.mark.asyncio
    async def test_anchor_grounded_probe(self):
        from probos.cognitive.behavioral_probes import AnchorGroundedEmergenceProbe
        probe = AnchorGroundedEmergenceProbe()
        runtime = self._make_runtime_with_snapshot()
        result = await probe.run("__crew__", runtime)
        assert result.passed
        assert result.score == 0.5


# ---------------------------------------------------------------------------
# Test Class 11: API Routes
# ---------------------------------------------------------------------------

class TestAPIRoutes:

    @pytest.mark.asyncio
    async def test_behavioral_metrics_endpoint(self):
        from probos.routers.system import get_behavioral_metrics
        engine = BehavioralMetricsEngine()
        engine._snapshots.append(BehavioralSnapshot(
            timestamp=1000.0,
            behavioral_quality_score=0.42,
            threads_analyzed=5,
        ))
        runtime = MagicMock()
        runtime._behavioral_metrics_engine = engine

        result = await get_behavioral_metrics(runtime=runtime)
        assert result["status"] == "ok"
        assert result["behavioral_quality_score"] == 0.42

    @pytest.mark.asyncio
    async def test_behavioral_metrics_history(self):
        from probos.routers.system import get_behavioral_metrics_history
        engine = BehavioralMetricsEngine()
        for i in range(3):
            engine._snapshots.append(BehavioralSnapshot(timestamp=float(i)))
        runtime = MagicMock()
        runtime._behavioral_metrics_engine = engine

        result = await get_behavioral_metrics_history(limit=20, runtime=runtime)
        assert result["status"] == "ok"
        assert result["count"] == 3
        assert len(result["snapshots"]) == 3
