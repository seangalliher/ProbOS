"""AD-531: Episode clustering tests.

Tests cover:
- Clustering algorithm (empty, min, threshold, groups)
- Cluster metadata (ID, centroid, variance, success_rate, agents, intents, timestamps)
- EpisodeCluster dataclass
- Helper functions (_cosine_similarity, _compute_centroid)
- EpisodicMemory.get_embeddings()
- Dream cycle integration
- Dead code removal verification
"""

from __future__ import annotations

import inspect
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import Episode, DreamReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    episode_id: str,
    user_input: str = "test",
    outcomes: list[dict] | None = None,
    agent_ids: list[str] | None = None,
    timestamp: float = 0.0,
) -> Episode:
    """Build a minimal Episode for testing."""
    return Episode(
        id=episode_id,
        user_input=user_input,
        outcomes=outcomes or [],
        agent_ids=agent_ids or [],
        timestamp=timestamp,
    )


def _make_embedding(base: list[float], noise: float = 0.0) -> list[float]:
    """Create an embedding vector with optional perturbation."""
    import random

    if noise == 0.0:
        return list(base)
    return [v + random.uniform(-noise, noise) for v in base]


# ---------------------------------------------------------------------------
# Clustering algorithm tests
# ---------------------------------------------------------------------------

class TestClusteringAlgorithm:
    """Tests for the cluster_episodes() function."""

    def test_cluster_empty_episodes(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        result = cluster_episodes([], {})
        assert result == []

    def test_cluster_no_embeddings(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(5)]
        result = cluster_episodes(eps, {})
        assert result == []

    def test_cluster_below_min_episodes(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode("e1"), _make_episode("e2")]
        embs = {"e1": [1.0, 0.0], "e2": [1.0, 0.0]}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result == []

    def test_cluster_identical_embeddings(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(5)]
        embs = {f"e{i}": [1.0, 0.0, 0.0, 0.0, 0.0] for i in range(5)}
        result = cluster_episodes(eps, embs, distance_threshold=0.15, min_episodes=3)
        assert len(result) == 1
        assert result[0].episode_count == 5

    def test_cluster_two_distinct_groups(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(6)]
        # Group A: first 3 episodes with similar embeddings
        # Group B: last 3 episodes with different similar embeddings
        embs = {
            "e0": [1.0, 0.0, 0.0, 0.0, 0.0],
            "e1": [0.98, 0.02, 0.0, 0.0, 0.0],
            "e2": [0.99, 0.01, 0.0, 0.0, 0.0],
            "e3": [0.0, 0.0, 0.0, 0.0, 1.0],
            "e4": [0.0, 0.0, 0.0, 0.02, 0.98],
            "e5": [0.0, 0.0, 0.0, 0.01, 0.99],
        }
        result = cluster_episodes(eps, embs, distance_threshold=0.15, min_episodes=3)
        assert len(result) == 2

    def test_cluster_scattered_episodes(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(4)]
        # All orthogonal — distance ~ 1.0
        embs = {
            "e0": [1.0, 0.0, 0.0, 0.0],
            "e1": [0.0, 1.0, 0.0, 0.0],
            "e2": [0.0, 0.0, 1.0, 0.0],
            "e3": [0.0, 0.0, 0.0, 1.0],
        }
        result = cluster_episodes(eps, embs, distance_threshold=0.15, min_episodes=3)
        assert result == []

    def test_cluster_min_episodes_filtering(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(4)]
        # 3 similar + 1 outlier
        embs = {
            "e0": [1.0, 0.0, 0.0, 0.0],
            "e1": [0.99, 0.01, 0.0, 0.0],
            "e2": [0.98, 0.02, 0.0, 0.0],
            "e3": [0.0, 0.0, 0.0, 1.0],  # outlier
        }
        result = cluster_episodes(eps, embs, distance_threshold=0.15, min_episodes=3)
        assert len(result) == 1
        assert result[0].episode_count == 3
        assert "e3" not in result[0].episode_ids

    def test_cluster_respects_distance_threshold_tight(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(4)]
        embs = {
            "e0": [1.0, 0.0, 0.0, 0.0],
            "e1": [0.9, 0.1, 0.0, 0.0],
            "e2": [0.95, 0.05, 0.0, 0.0],
            "e3": [0.92, 0.08, 0.0, 0.0],
        }
        # Very tight threshold — even somewhat similar episodes won't cluster
        result = cluster_episodes(eps, embs, distance_threshold=0.001, min_episodes=3)
        assert result == []

    def test_cluster_respects_distance_threshold_loose(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(4)]
        # Moderately different vectors
        embs = {
            "e0": [1.0, 0.0, 0.0, 0.0],
            "e1": [0.7, 0.3, 0.0, 0.0],
            "e2": [0.6, 0.4, 0.0, 0.0],
            "e3": [0.5, 0.5, 0.0, 0.0],
        }
        # Very loose threshold — these should cluster
        result = cluster_episodes(eps, embs, distance_threshold=0.5, min_episodes=3)
        assert len(result) >= 1

    def test_cluster_single_large_cluster(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(10)]
        embs = {f"e{i}": [1.0, 0.0, 0.0, 0.0, 0.0] for i in range(10)}
        result = cluster_episodes(eps, embs, distance_threshold=0.15, min_episodes=3)
        assert len(result) == 1
        assert result[0].episode_count == 10


# ---------------------------------------------------------------------------
# Cluster metadata tests
# ---------------------------------------------------------------------------

class TestClusterMetadata:
    """Tests for cluster metadata computation."""

    def test_cluster_id_deterministic(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(3)]
        embs = {f"e{i}": [1.0, 0.0, 0.0] for i in range(3)}
        r1 = cluster_episodes(eps, embs, min_episodes=3)
        r2 = cluster_episodes(eps, embs, min_episodes=3)
        assert r1[0].cluster_id == r2[0].cluster_id

    def test_cluster_id_order_independent(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps_fwd = [_make_episode("e0"), _make_episode("e1"), _make_episode("e2")]
        eps_rev = [_make_episode("e2"), _make_episode("e1"), _make_episode("e0")]
        embs = {f"e{i}": [1.0, 0.0, 0.0] for i in range(3)}
        r1 = cluster_episodes(eps_fwd, embs, min_episodes=3)
        r2 = cluster_episodes(eps_rev, embs, min_episodes=3)
        assert r1[0].cluster_id == r2[0].cluster_id

    def test_cluster_centroid_is_mean(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(3)]
        embs = {
            "e0": [1.0, 0.0],
            "e1": [0.0, 1.0],
            "e2": [1.0, 1.0],
        }
        # Loose threshold to ensure they cluster
        result = cluster_episodes(eps, embs, distance_threshold=0.8, min_episodes=3)
        assert len(result) == 1
        centroid = result[0].centroid
        assert abs(centroid[0] - (1.0 + 0.0 + 1.0) / 3) < 0.01
        assert abs(centroid[1] - (0.0 + 1.0 + 1.0) / 3) < 0.01

    def test_cluster_variance_computed(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [_make_episode(f"e{i}") for i in range(3)]
        # All identical → variance should be 0
        embs = {f"e{i}": [1.0, 0.0, 0.0] for i in range(3)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result[0].variance == 0.0

    def test_cluster_success_rate_all_success(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [
            _make_episode("e0", outcomes=[{"intent": "a", "success": True}]),
            _make_episode("e1", outcomes=[{"intent": "a", "success": True}]),
            _make_episode("e2", outcomes=[{"intent": "a", "success": True}]),
        ]
        embs = {f"e{i}": [1.0, 0.0] for i in range(3)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result[0].success_rate == 1.0
        assert result[0].is_success_dominant is True

    def test_cluster_success_rate_all_failure(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [
            _make_episode("e0", outcomes=[{"intent": "a", "success": False}]),
            _make_episode("e1", outcomes=[{"intent": "a", "success": False}]),
            _make_episode("e2", outcomes=[{"intent": "a", "success": False}]),
        ]
        embs = {f"e{i}": [1.0, 0.0] for i in range(3)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result[0].success_rate == 0.0
        assert result[0].is_failure_dominant is True

    def test_cluster_success_rate_mixed(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [
            _make_episode("e0", outcomes=[{"intent": "a", "success": True}]),
            _make_episode("e1", outcomes=[{"intent": "a", "success": True}]),
            _make_episode("e2", outcomes=[{"intent": "a", "success": False}]),
            _make_episode("e3", outcomes=[{"intent": "a", "success": False}]),
            _make_episode("e4", outcomes=[{"intent": "a", "success": True}]),
        ]
        embs = {f"e{i}": [1.0, 0.0] for i in range(5)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        # 3/5 = 0.60
        assert 0.55 < result[0].success_rate < 0.65
        assert result[0].is_success_dominant is False
        assert result[0].is_failure_dominant is False

    def test_cluster_participating_agents(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [
            _make_episode("e0", agent_ids=["agent-a", "agent-b"]),
            _make_episode("e1", agent_ids=["agent-b", "agent-c"]),
            _make_episode("e2", agent_ids=["agent-a"]),
        ]
        embs = {f"e{i}": [1.0, 0.0] for i in range(3)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result[0].participating_agents == ["agent-a", "agent-b", "agent-c"]

    def test_cluster_intent_types(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [
            _make_episode("e0", outcomes=[{"intent": "read_file", "success": True}]),
            _make_episode("e1", outcomes=[{"intent": "write_file", "success": True}]),
            _make_episode("e2", outcomes=[{"intent": "read_file", "success": True}]),
        ]
        embs = {f"e{i}": [1.0, 0.0] for i in range(3)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result[0].intent_types == ["read_file", "write_file"]

    def test_cluster_timestamps(self) -> None:
        from probos.cognitive.episode_clustering import cluster_episodes

        eps = [
            _make_episode("e0", timestamp=100.0),
            _make_episode("e1", timestamp=200.0),
            _make_episode("e2", timestamp=300.0),
        ]
        embs = {f"e{i}": [1.0, 0.0] for i in range(3)}
        result = cluster_episodes(eps, embs, min_episodes=3)
        assert result[0].first_occurrence == 100.0
        assert result[0].last_occurrence == 300.0


# ---------------------------------------------------------------------------
# EpisodeCluster dataclass tests
# ---------------------------------------------------------------------------

class TestEpisodeClusterDataclass:
    """Tests for EpisodeCluster serialization."""

    def test_episode_cluster_to_dict(self) -> None:
        from probos.cognitive.episode_clustering import EpisodeCluster

        cluster = EpisodeCluster(
            cluster_id="abc123",
            episode_ids=["e1", "e2", "e3"],
            episode_count=3,
            centroid=[1.0, 0.0, 0.0],
            variance=0.05,
            success_rate=0.8,
            is_success_dominant=False,
            is_failure_dominant=False,
            participating_agents=["a1"],
            intent_types=["read"],
            first_occurrence=100.0,
            last_occurrence=300.0,
        )
        d = cluster.to_dict()
        assert "centroid" not in d
        assert d["cluster_id"] == "abc123"
        assert d["episode_count"] == 3
        assert d["episode_ids"] == ["e1", "e2", "e3"]

    def test_episode_cluster_to_dict_rounding(self) -> None:
        from probos.cognitive.episode_clustering import EpisodeCluster

        cluster = EpisodeCluster(
            cluster_id="x",
            episode_ids=["e1", "e2", "e3"],
            episode_count=3,
            centroid=[],
            variance=0.123456789,
            success_rate=0.666666666,
            is_success_dominant=False,
            is_failure_dominant=False,
            participating_agents=[],
            intent_types=[],
            first_occurrence=0.0,
            last_occurrence=0.0,
        )
        d = cluster.to_dict()
        assert d["variance"] == 0.1235  # 4 decimals
        assert d["success_rate"] == 0.667  # 3 decimals


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Tests for private helper functions."""

    def test_cosine_similarity_identical(self) -> None:
        from probos.cognitive.episode_clustering import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0

    def test_cosine_similarity_orthogonal(self) -> None:
        from probos.cognitive.episode_clustering import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_cosine_similarity_opposite(self) -> None:
        from probos.cognitive.episode_clustering import _cosine_similarity

        # Clamped to 0.0
        result = _cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert result == 0.0

    def test_cosine_similarity_empty(self) -> None:
        from probos.cognitive.episode_clustering import _cosine_similarity

        assert _cosine_similarity([], []) == 0.0

    def test_cosine_similarity_different_lengths(self) -> None:
        from probos.cognitive.episode_clustering import _cosine_similarity

        assert _cosine_similarity([1.0, 0.0], [1.0]) == 0.0

    def test_compute_centroid(self) -> None:
        from probos.cognitive.episode_clustering import _compute_centroid

        centroid = _compute_centroid([[1.0, 0.0], [0.0, 1.0]])
        assert abs(centroid[0] - 0.5) < 0.001
        assert abs(centroid[1] - 0.5) < 0.001


# ---------------------------------------------------------------------------
# EpisodicMemory.get_embeddings() tests
# ---------------------------------------------------------------------------

class TestGetEmbeddings:
    """Tests for the get_embeddings() method on EpisodicMemory."""

    @pytest.mark.asyncio
    async def test_get_embeddings_returns_vectors(self) -> None:
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory.__new__(EpisodicMemory)
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": ["e1", "e2"],
            "embeddings": [[1.0, 0.0], [0.0, 1.0]],
        }
        mem._collection = mock_collection

        result = await mem.get_embeddings(["e1", "e2"])
        assert "e1" in result
        assert "e2" in result
        assert result["e1"] == [1.0, 0.0]

    @pytest.mark.asyncio
    async def test_get_embeddings_missing_ids(self) -> None:
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory.__new__(EpisodicMemory)
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "ids": [],
            "embeddings": [],
        }
        mem._collection = mock_collection

        result = await mem.get_embeddings(["nonexistent"])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_embeddings_empty_collection(self) -> None:
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory.__new__(EpisodicMemory)
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": [], "embeddings": []}
        mem._collection = mock_collection

        result = await mem.get_embeddings([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_embeddings_no_collection(self) -> None:
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory.__new__(EpisodicMemory)
        mem._collection = None

        result = await mem.get_embeddings(["e1"])
        assert result == {}


# ---------------------------------------------------------------------------
# Dream cycle integration tests
# ---------------------------------------------------------------------------

class TestDreamCycleIntegration:
    """Tests for clustering within the dream cycle."""

    @pytest.mark.asyncio
    async def test_dream_cycle_produces_clusters(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.5
        mock_router.decay_all.return_value = None
        mock_router._weights = {}
        mock_router._compat_weights = {}

        mock_trust = MagicMock()
        mock_trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}])
            for i in range(5)
        ]
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = episodes
        mock_mem.get_stats.return_value = {"total": 5}
        mock_mem.get_embeddings.return_value = {
            f"e{i}": [1.0, 0.0, 0.0] for i in range(5)
        }

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_mem,
            config=DreamingConfig(),
        )

        report = await engine.dream_cycle()
        assert report.clusters_found > 0
        assert len(report.clusters) > 0

    @pytest.mark.asyncio
    async def test_dream_cycle_no_embeddings_graceful(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.5
        mock_router.decay_all.return_value = None
        mock_router._weights = {}
        mock_router._compat_weights = {}

        mock_trust = MagicMock()
        mock_trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

        episodes = [_make_episode(f"e{i}") for i in range(3)]
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = episodes
        mock_mem.get_stats.return_value = {"total": 3}
        mock_mem.get_embeddings.return_value = {}

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_mem,
            config=DreamingConfig(),
        )

        report = await engine.dream_cycle()
        assert report.clusters_found == 0

    @pytest.mark.asyncio
    async def test_dream_cycle_clustering_failure_graceful(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.5
        mock_router.decay_all.return_value = None
        mock_router._weights = {}
        mock_router._compat_weights = {}

        mock_trust = MagicMock()
        mock_trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

        episodes = [_make_episode(f"e{i}") for i in range(3)]
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = episodes
        mock_mem.get_stats.return_value = {"total": 3}
        mock_mem.get_embeddings.side_effect = RuntimeError("ChromaDB down")

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_mem,
            config=DreamingConfig(),
        )

        # Should not raise — log-and-degrade
        report = await engine.dream_cycle()
        assert report.clusters_found == 0

    def test_dream_report_no_strategies_field(self) -> None:
        r = DreamReport()
        assert not hasattr(r, "strategies_extracted")
        assert hasattr(r, "clusters_found")
        assert hasattr(r, "clusters")

    @pytest.mark.asyncio
    async def test_last_clusters_property(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.5
        mock_router.decay_all.return_value = None
        mock_router._weights = {}
        mock_router._compat_weights = {}

        mock_trust = MagicMock()
        mock_trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}])
            for i in range(5)
        ]
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = episodes
        mock_mem.get_stats.return_value = {"total": 5}
        mock_mem.get_embeddings.return_value = {
            f"e{i}": [1.0, 0.0, 0.0] for i in range(5)
        }

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_mem,
            config=DreamingConfig(),
        )

        assert engine.last_clusters == []
        await engine.dream_cycle()
        assert len(engine.last_clusters) > 0

    @pytest.mark.asyncio
    async def test_dream_report_clusters_field(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine
        from probos.cognitive.episode_clustering import EpisodeCluster
        from probos.config import DreamingConfig

        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.5
        mock_router.decay_all.return_value = None
        mock_router._weights = {}
        mock_router._compat_weights = {}

        mock_trust = MagicMock()
        mock_trust.get_or_create.return_value = MagicMock(alpha=1.0, beta=1.0)

        episodes = [
            _make_episode(f"e{i}", outcomes=[{"intent": "read", "success": True}])
            for i in range(5)
        ]
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = episodes
        mock_mem.get_stats.return_value = {"total": 5}
        mock_mem.get_embeddings.return_value = {
            f"e{i}": [1.0, 0.0, 0.0] for i in range(5)
        }

        engine = DreamingEngine(
            router=mock_router,
            trust_network=mock_trust,
            episodic_memory=mock_mem,
            config=DreamingConfig(),
        )

        report = await engine.dream_cycle()
        assert all(isinstance(c, EpisodeCluster) for c in report.clusters)


# ---------------------------------------------------------------------------
# Dead code removal verification
# ---------------------------------------------------------------------------

class TestDeadCodeRemoval:
    """Verify strategy extraction is fully removed."""

    def test_no_strategy_extraction_import(self) -> None:
        import probos.cognitive.dreaming as mod

        source = inspect.getsource(mod)
        assert "strategy_extraction" not in source

    def test_no_strategy_store_fn(self) -> None:
        from probos.cognitive.dreaming import DreamingEngine

        sig = inspect.signature(DreamingEngine.__init__)
        assert "strategy_store_fn" not in sig.parameters
