"""AD-531: Episode clustering — group episodes by semantic similarity during dream cycles.

Replaces the dead extract_strategies() pipeline (AD-383). Produces EpisodeCluster
objects consumed by AD-532 (Procedure Extraction).
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EpisodeCluster:
    """A group of semantically similar episodes discovered during dream consolidation.

    Success-dominant clusters (>80% positive) feed procedure extraction (AD-532).
    Failure-dominant clusters (>50% negative) feed gap identification (AD-539).
    """

    cluster_id: str  # deterministic hash of sorted episode IDs
    episode_ids: list[str]  # member episode IDs
    episode_count: int  # len(episode_ids)
    centroid: list[float]  # average embedding vector
    variance: float  # mean cosine distance from centroid (tightness)
    success_rate: float  # fraction of outcomes with success=True
    is_success_dominant: bool  # success_rate > 0.80
    is_failure_dominant: bool  # (1 - success_rate) > 0.50
    participating_agents: list[str]  # unique agent IDs across all episodes
    intent_types: list[str]  # unique intent types across all episodes
    first_occurrence: float  # earliest episode timestamp
    last_occurrence: float  # latest episode timestamp
    # AD-567d: Anchor provenance summary aggregated from source episodes
    anchor_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging/storage. Omit centroid (large)."""
        d = {
            "cluster_id": self.cluster_id,
            "episode_ids": self.episode_ids,
            "episode_count": self.episode_count,
            "variance": round(self.variance, 4),
            "success_rate": round(self.success_rate, 3),
            "is_success_dominant": self.is_success_dominant,
            "is_failure_dominant": self.is_failure_dominant,
            "participating_agents": self.participating_agents,
            "intent_types": self.intent_types,
            "first_occurrence": self.first_occurrence,
            "last_occurrence": self.last_occurrence,
        }
        if self.anchor_summary:
            d["anchor_summary"] = self.anchor_summary
        return d


def cluster_episodes(
    episodes: list[Any],
    embeddings: dict[str, list[float]],
    distance_threshold: float = 0.15,
    min_episodes: int = 3,
) -> list[EpisodeCluster]:
    """Group episodes by embedding similarity using agglomerative clustering.

    Args:
        episodes: Episode objects from EpisodicMemory.recent()
        embeddings: mapping of episode_id -> embedding vector from ChromaDB
        distance_threshold: max cosine distance for merging (0.15 = 85% similar)
        min_episodes: minimum cluster size to be actionable

    Returns:
        List of EpisodeCluster objects with >= min_episodes members.
        Clusters below min_episodes are discarded (prevents overfitting to one-offs).
    """
    # Step 1: Filter to episodes with valid embeddings
    valid_episodes: list[Any] = []
    valid_embeddings: list[list[float]] = []
    dim: int | None = None

    for ep in episodes:
        emb = embeddings.get(ep.id)
        if emb and len(emb) > 0:
            if dim is None:
                dim = len(emb)
            if len(emb) == dim:
                valid_episodes.append(ep)
                valid_embeddings.append(emb)

    if len(valid_episodes) < min_episodes:
        return []

    n = len(valid_episodes)

    # Step 2: Compute pairwise cosine distances
    distance_matrix: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            dist = 1.0 - _cosine_similarity(valid_embeddings[i], valid_embeddings[j])
            distance_matrix[(i, j)] = dist

    # Step 3: Initialize each episode as its own cluster
    clusters: list[list[int]] = [[i] for i in range(n)]

    # Step 4: Merge loop — average-linkage agglomerative
    while len(clusters) > 1:
        best_dist = float("inf")
        best_pair: tuple[int, int] | None = None

        for ci in range(len(clusters)):
            for cj in range(ci + 1, len(clusters)):
                dist = _compute_cluster_distance(clusters[ci], clusters[cj], distance_matrix)
                if dist < best_dist:
                    best_dist = dist
                    best_pair = (ci, cj)

        if best_pair is None or best_dist >= distance_threshold:
            break

        # Merge the two closest clusters
        ci, cj = best_pair
        clusters[ci] = clusters[ci] + clusters[cj]
        del clusters[cj]

    # Step 5: Filter to clusters with >= min_episodes members
    surviving = [c for c in clusters if len(c) >= min_episodes]

    # Step 6: Build EpisodeCluster objects
    result: list[EpisodeCluster] = []
    for member_indices in surviving:
        member_episodes = [valid_episodes[i] for i in member_indices]
        member_embeddings = [valid_embeddings[i] for i in member_indices]
        member_ids = [ep.id for ep in member_episodes]

        # cluster_id: SHA-256 of sorted episode IDs, truncated to 16 chars
        sorted_ids = sorted(member_ids)
        cluster_id = hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()[:16]

        # centroid: element-wise mean
        centroid = _compute_centroid(member_embeddings)

        # variance: mean cosine distance from each member to centroid
        distances_to_centroid = [
            1.0 - _cosine_similarity(emb, centroid)
            for emb in member_embeddings
        ]
        variance = sum(distances_to_centroid) / len(distances_to_centroid) if distances_to_centroid else 0.0

        # success_rate from outcomes
        total_outcomes = 0
        success_outcomes = 0
        agents: set[str] = set()
        intents: set[str] = set()
        timestamps: list[float] = []

        for ep in member_episodes:
            for outcome in getattr(ep, "outcomes", []):
                total_outcomes += 1
                if outcome.get("success", False):
                    success_outcomes += 1
                intent = outcome.get("intent", "")
                if intent:
                    intents.add(intent)
            for aid in getattr(ep, "agent_ids", []):
                agents.add(aid)
            ts = getattr(ep, "timestamp", 0.0)
            if ts:
                timestamps.append(ts)

        success_rate = success_outcomes / total_outcomes if total_outcomes > 0 else 0.0

        result.append(EpisodeCluster(
            cluster_id=cluster_id,
            episode_ids=member_ids,
            episode_count=len(member_ids),
            centroid=centroid,
            variance=variance,
            success_rate=success_rate,
            is_success_dominant=success_rate > 0.80,
            is_failure_dominant=(1.0 - success_rate) > 0.50,
            participating_agents=sorted(agents),
            intent_types=sorted(intents),
            first_occurrence=min(timestamps) if timestamps else 0.0,
            last_occurrence=max(timestamps) if timestamps else 0.0,
        ))

    # Sort by episode_count descending
    result.sort(key=lambda c: c.episode_count, reverse=True)
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity between two dense vectors. Returns 0.0-1.0.

    Copied from knowledge/embeddings.py to avoid cross-package dependency
    (cognitive should not import knowledge.embeddings).
    """
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def _compute_cluster_distance(
    cluster_a: list[int],
    cluster_b: list[int],
    distance_matrix: dict[tuple[int, int], float],
) -> float:
    """Average-linkage: mean pairwise distance between all cross-cluster pairs."""
    total = 0.0
    count = 0
    for i in cluster_a:
        for j in cluster_b:
            key = (min(i, j), max(i, j))
            total += distance_matrix.get(key, 1.0)
            count += 1
    return total / count if count > 0 else 1.0


def _compute_centroid(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of embedding vectors."""
    if not vectors:
        return []
    dim = len(vectors[0])
    centroid = [0.0] * dim
    for vec in vectors:
        for i in range(dim):
            centroid[i] += vec[i]
    n = len(vectors)
    return [c / n for c in centroid]
