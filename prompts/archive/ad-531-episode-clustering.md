# AD-531: Episode Clustering & Pattern Detection

**Context:** Dream cycles currently replay episodes linearly — strengthening Hebbian weights, consolidating trust, predicting gaps. There is no cross-episode structural analysis. The `extract_strategies()` code path (AD-383) is dead code: it expects Episode fields that don't exist (`agent_type`, `intent`, `outcome`, `error`) and always returns an empty list. The `StrategyAdvisor` consumer is wired up but has zero data. AD-531 replaces this dead pipeline with embedding-based episode clustering.

**Problem:** Episodes are stored individually with no grouping. The crew has no "we've seen this N times" capability. Success and failure patterns are invisible. The dead strategy extraction code wastes cycles every dream cycle. AD-532 (Procedure Extraction, immediate follow-on) needs clusters as input.

**Principles:** SOLID (single new module, pure functions where possible), DRY (reuse existing `_cosine_similarity` from embeddings.py), Law of Demeter (access ChromaDB through EpisodicMemory, not directly), Fail Fast (log-and-degrade — clustering failure should not break dream cycles).

---

## Part 0: Dead Code Cleanup

Remove the dead strategy extraction pipeline. Keep `StrategyAdvisor` alive (AD-534 replaces it).

### 0a. Delete files

- **Delete** `src/probos/cognitive/strategy_extraction.py` (229 lines, dead code)
- **Delete** `tests/test_strategy_extraction.py` (dead tests against wrong Episode schema)

### 0b. `src/probos/cognitive/dreaming.py` — remove strategy import and callback

**Remove import** (line 19):
```python
# DELETE this line:
from probos.cognitive.strategy_extraction import extract_strategies
```

**Remove `strategy_store_fn` from constructor** (lines 38, 48):

Before:
```python
def __init__(
    self,
    router: HebbianRouter,
    trust_network: TrustNetwork,
    episodic_memory: Any,
    config: DreamingConfig,
    idle_scale_down_fn: Any = None,
    strategy_store_fn: Any = None,
    gap_prediction_fn: Any = None,
    contradiction_resolve_fn: Any = None,  # AD-403
) -> None:
    ...
    self._strategy_store_fn = strategy_store_fn
```

After:
```python
def __init__(
    self,
    router: HebbianRouter,
    trust_network: TrustNetwork,
    episodic_memory: Any,
    config: DreamingConfig,
    idle_scale_down_fn: Any = None,
    gap_prediction_fn: Any = None,
    contradiction_resolve_fn: Any = None,  # AD-403
) -> None:
    ...
    # (no _strategy_store_fn attribute)
```

**Remove Step 6 strategy extraction** (lines 139-146) — this block will be replaced in Part 3 with clustering.

### 0c. `src/probos/dream_adapter.py` — remove `store_strategies()`

**Delete** the `store_strategies()` method (lines 179-190):
```python
# DELETE this entire method:
def store_strategies(self, strategies: list[Any]) -> None:
    ...
```

### 0d. `src/probos/startup/dreaming.py` — remove strategy wiring

**Remove `store_strategies_fn` parameter** from `init_dreaming()` signature (line 39):
```python
# DELETE this parameter:
store_strategies_fn: Callable[..., Any] | None,
```

**Remove strategy wiring** from DreamingEngine construction (lines 71-73):
```python
# DELETE these lines:
strategy_store_fn=(
    store_strategies_fn if knowledge_store else None
),
```

### 0e. `src/probos/runtime.py` — remove strategy lambda

**Remove the `store_strategies_fn` kwarg** from the `init_dreaming()` call (line 1101):
```python
# DELETE this line:
store_strategies_fn=lambda s: self.dream_adapter.store_strategies(s) if self.dream_adapter else None,
```

### 0f. `src/probos/types.py` — replace `strategies_extracted` field

In `DreamReport` (line 374), replace `strategies_extracted` with cluster fields:

Before:
```python
@dataclass
class DreamReport:
    """Result of a single dream cycle."""
    episodes_replayed: int = 0
    weights_strengthened: int = 0
    weights_pruned: int = 0
    trust_adjustments: int = 0
    pre_warm_intents: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    strategies_extracted: int = 0
    gaps_predicted: int = 0
    contradictions_found: int = 0  # AD-403
```

After:
```python
@dataclass
class DreamReport:
    """Result of a single dream cycle."""
    episodes_replayed: int = 0
    weights_strengthened: int = 0
    weights_pruned: int = 0
    trust_adjustments: int = 0
    pre_warm_intents: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    clusters_found: int = 0  # AD-531 (replaces strategies_extracted)
    clusters: list[Any] = field(default_factory=list)  # AD-531: EpisodeCluster objects
    gaps_predicted: int = 0
    contradictions_found: int = 0  # AD-403
```

**Important:** Search the entire codebase for `strategies_extracted` and update all references to `clusters_found`. Check at minimum:
- `dreaming.py` lines 166, 178 (DreamReport construction and log line)
- `tests/test_dreaming.py` or any test referencing `strategies_extracted`
- `dream_adapter.py` if it reads the field
- Any dashboard or logging that displays strategy counts

---

## Part 1: EpisodeCluster Dataclass + Clustering Algorithm

### 1a. Create `src/probos/cognitive/episode_clustering.py`

New module replacing `strategy_extraction.py`.

```python
"""AD-531: Episode clustering — group episodes by semantic similarity during dream cycles.

Replaces the dead extract_strategies() pipeline (AD-383). Produces EpisodeCluster
objects consumed by AD-532 (Procedure Extraction).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)
```

### 1b. `EpisodeCluster` dataclass

```python
@dataclass
class EpisodeCluster:
    """A group of semantically similar episodes discovered during dream consolidation.

    Success-dominant clusters (>80% positive) feed procedure extraction (AD-532).
    Failure-dominant clusters (>50% negative) feed gap identification (AD-539).
    """
    cluster_id: str                          # deterministic hash of sorted episode IDs
    episode_ids: list[str]                   # member episode IDs
    episode_count: int                       # len(episode_ids)
    centroid: list[float]                    # average embedding vector
    variance: float                          # mean cosine distance from centroid (tightness)
    success_rate: float                      # fraction of outcomes with success=True
    is_success_dominant: bool                # success_rate > 0.80
    is_failure_dominant: bool                # (1 - success_rate) > 0.50
    participating_agents: list[str]          # unique agent IDs across all episodes
    intent_types: list[str]                  # unique intent types across all episodes
    first_occurrence: float                  # earliest episode timestamp
    last_occurrence: float                   # latest episode timestamp

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging/storage. Omit centroid (large)."""
        return {
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
```

### 1c. Clustering function

```python
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
```

**Algorithm (average-linkage agglomerative, no scipy):**

1. Filter episodes to those with valid embeddings (same dimensionality, non-empty). If fewer than `min_episodes` valid episodes, return `[]`.
2. Compute pairwise cosine distances: `distance = 1.0 - cosine_similarity(a, b)`. Store in a flat structure (dict or list of tuples). Use a private `_cosine_similarity()` function (copy the 8-line implementation from `knowledge/embeddings.py:150-159` — avoids cross-package import into cognitive module).
3. Initialize each episode as its own cluster (list of indices).
4. **Merge loop:** Find the pair of clusters with the smallest average inter-cluster distance. If that distance < `distance_threshold`, merge them. Repeat until no mergeable pair remains.
5. Filter to clusters with `len >= min_episodes`.
6. For each surviving cluster, compute metadata:
   - `cluster_id`: SHA-256 hash of sorted episode IDs, truncated to 16 chars
   - `centroid`: element-wise mean of member embeddings
   - `variance`: mean cosine distance from each member to the centroid
   - `success_rate`: count outcomes with `success=True` / total outcomes across all member episodes. Access via `episode.outcomes` (list of dicts, each has `"success"` key).
   - `is_success_dominant`: `success_rate > 0.80`
   - `is_failure_dominant`: `(1 - success_rate) > 0.50`
   - `participating_agents`: sorted unique agent IDs from all member episodes' `agent_ids` lists
   - `intent_types`: sorted unique intent types from `outcome["intent"]` across all member episode outcomes
   - `first_occurrence` / `last_occurrence`: min/max of member episode `timestamp` fields
7. Return list of `EpisodeCluster` objects, sorted by `episode_count` descending.

**Performance note:** n=50 episodes max (from `replay_episode_count`). O(n²) pairwise distances = 1,225 comparisons. O(n³) worst-case merge iterations. Both trivial for n=50.

### 1d. Private helper functions

```python
def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity between two dense vectors. Returns 0.0-1.0."""
    # Same implementation as knowledge/embeddings.py:150-159
    # Copied here to avoid cross-package dependency (cognitive should not import knowledge.embeddings)

def _compute_cluster_distance(
    cluster_a: list[int],
    cluster_b: list[int],
    distance_matrix: dict[tuple[int, int], float],
) -> float:
    """Average-linkage: mean pairwise distance between all cross-cluster pairs."""

def _compute_centroid(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of embedding vectors."""
```

---

## Part 2: EpisodicMemory Embedding Retrieval

### 2a. `src/probos/cognitive/episodic.py` — add `get_embeddings()` method

Add a new public method after `recent()` (after line 456):

```python
async def get_embeddings(self, episode_ids: list[str]) -> dict[str, list[float]]:
    """Retrieve stored embeddings for the given episode IDs.

    Returns a dict mapping episode_id -> embedding vector.
    Episodes without embeddings (or if ChromaDB is unavailable) are omitted.
    Used by AD-531 episode clustering during dream cycles.
    """
    if not self._collection or not episode_ids:
        return {}

    try:
        result = self._collection.get(
            ids=episode_ids,
            include=["embeddings"],
        )
        if not result or not result["ids"] or not result["embeddings"]:
            return {}

        embeddings: dict[str, list[float]] = {}
        for i, doc_id in enumerate(result["ids"]):
            emb = result["embeddings"][i]
            if emb and len(emb) > 0:
                embeddings[doc_id] = list(emb)
        return embeddings

    except Exception:
        logger.debug("Failed to retrieve embeddings", exc_info=True)
        return {}
```

---

## Part 3: Dream Cycle Integration

### 3a. `src/probos/cognitive/dreaming.py` — add clustering import

Add at top (replacing the deleted `strategy_extraction` import):
```python
from probos.cognitive.episode_clustering import cluster_episodes
```

### 3b. `src/probos/cognitive/dreaming.py` — add cluster storage

Add to `__init__()`:
```python
self._last_clusters: list[Any] = []  # AD-531: most recent dream cycle clusters
```

Add a public property:
```python
@property
def last_clusters(self) -> list[Any]:
    """Most recent episode clusters from the last dream cycle (AD-531)."""
    return self._last_clusters
```

### 3c. `src/probos/cognitive/dreaming.py` — replace Step 6

Replace the deleted Step 6 (strategy extraction) with:

```python
# Step 6: Episode clustering (AD-531, replaces dead extract_strategies)
clusters_found = 0
clusters: list = []
try:
    episode_ids = [ep.id for ep in episodes]
    embeddings = await self.episodic_memory.get_embeddings(episode_ids)
    if embeddings:
        clusters = cluster_episodes(
            episodes=episodes,
            embeddings=embeddings,
            distance_threshold=0.15,
            min_episodes=3,
        )
        clusters_found = len(clusters)
        self._last_clusters = clusters
        if clusters_found > 0:
            logger.info(
                "Episode clustering: %d clusters found (%d success-dominant, %d failure-dominant)",
                clusters_found,
                sum(1 for c in clusters if c.is_success_dominant),
                sum(1 for c in clusters if c.is_failure_dominant),
            )
    else:
        logger.debug("Episode clustering skipped: no embeddings available")
except Exception as e:
    logger.debug("Episode clustering failed (non-critical): %s", e)
```

### 3d. Update DreamReport construction

In the `DreamReport(...)` construction (line 159), replace `strategies_extracted=strategies_extracted` with:
```python
clusters_found=clusters_found,
clusters=clusters,
```

### 3e. Update log line

Replace the log line (line 171-181) format string — change `strategies=%d` to `clusters=%d` and update the corresponding argument from `report.strategies_extracted` to `report.clusters_found`.

### 3f. Update dream_complete event payload

If the `DreamScheduler` emits `dream_complete` events with payload dict, add `clusters_found` to the full-dream payload. Search for where `dream_type: "full"` events are emitted and add:
```python
"clusters_found": dream_report.clusters_found,
```

---

## Part 4: Tests

### Create `tests/test_episode_clustering.py`

**Test structure:** Use `@pytest.mark.asyncio` where needed. Create helper functions for building test episodes and fake embeddings.

#### Helper fixtures

```python
def _make_episode(episode_id, user_input, outcomes, agent_ids, timestamp=0.0):
    """Build a minimal Episode for testing."""
    return Episode(
        id=episode_id,
        user_input=user_input,
        outcomes=outcomes,
        agent_ids=agent_ids,
        timestamp=timestamp,
    )

def _make_embedding(base, noise=0.0):
    """Create a 10-dim embedding vector with optional noise.
    Use low dimensionality for test readability.
    base: list of 10 floats near 0-1
    noise: random perturbation magnitude
    """
```

#### Test cases (target: ~30 tests)

**Clustering algorithm tests:**

1. `test_cluster_empty_episodes` — empty input returns `[]`
2. `test_cluster_no_embeddings` — episodes exist but embeddings dict is empty, returns `[]`
3. `test_cluster_below_min_episodes` — 2 episodes (below threshold of 3), returns `[]`
4. `test_cluster_identical_embeddings` — 5 episodes with identical embeddings form one cluster
5. `test_cluster_two_distinct_groups` — 6 episodes: 3 with similar embeddings + 3 with different similar embeddings → 2 clusters
6. `test_cluster_scattered_episodes` — all episodes have very different embeddings (distance > threshold), returns `[]` (no cluster meets min_episodes)
7. `test_cluster_min_episodes_filtering` — 4 episodes: 3 similar + 1 outlier → 1 cluster with 3 members
8. `test_cluster_respects_distance_threshold` — set threshold very tight (0.01), verify even somewhat-similar episodes don't cluster
9. `test_cluster_respects_distance_threshold_loose` — set threshold very loose (0.5), verify distinct episodes now cluster
10. `test_cluster_single_large_cluster` — 10 nearly identical episodes → 1 cluster with 10 members

**Cluster metadata tests:**

11. `test_cluster_id_deterministic` — same set of episode IDs always produces the same cluster_id
12. `test_cluster_id_order_independent` — shuffled episode IDs produce the same cluster_id (sorted before hashing)
13. `test_cluster_centroid_is_mean` — centroid equals element-wise mean of member embeddings
14. `test_cluster_variance_computed` — variance = mean cosine distance from members to centroid
15. `test_cluster_success_rate_all_success` — all outcomes have `success: True` → rate = 1.0, `is_success_dominant = True`
16. `test_cluster_success_rate_all_failure` — all outcomes have `success: False` → rate = 0.0, `is_failure_dominant = True`
17. `test_cluster_success_rate_mixed` — 60% success → `is_success_dominant = False`, `is_failure_dominant = False`
18. `test_cluster_participating_agents` — agents collected from all member episodes' `agent_ids` lists, deduplicated and sorted
19. `test_cluster_intent_types` — intents collected from all member episode outcomes, deduplicated and sorted
20. `test_cluster_timestamps` — `first_occurrence` = min timestamp, `last_occurrence` = max timestamp

**EpisodeCluster dataclass tests:**

21. `test_episode_cluster_to_dict` — `to_dict()` produces correct keys, omits `centroid`
22. `test_episode_cluster_to_dict_rounding` — variance rounded to 4 decimals, success_rate to 3

**Helper function tests:**

23. `test_cosine_similarity_identical` — identical vectors → 1.0
24. `test_cosine_similarity_orthogonal` — orthogonal vectors → 0.0
25. `test_cosine_similarity_opposite` — negated vectors → 0.0 (clamped)
26. `test_cosine_similarity_empty` — empty vectors → 0.0
27. `test_cosine_similarity_different_lengths` — mismatched dimensions → 0.0
28. `test_compute_centroid` — mean of [[1,0],[0,1]] = [0.5, 0.5]

**EpisodicMemory.get_embeddings() tests:**

29. `test_get_embeddings_returns_vectors` — store episodes, retrieve embeddings, verify non-empty vectors returned for each ID
30. `test_get_embeddings_missing_ids` — request IDs that don't exist, returns empty dict (or omits missing)
31. `test_get_embeddings_empty_collection` — no episodes stored, returns `{}`
32. `test_get_embeddings_no_collection` — episodic memory not started, returns `{}`

**Dream cycle integration tests:**

33. `test_dream_cycle_produces_clusters` — mock EpisodicMemory with `recent()` and `get_embeddings()`, run `dream_cycle()`, verify `DreamReport.clusters_found > 0` and `DreamReport.clusters` is non-empty
34. `test_dream_cycle_no_embeddings_graceful` — `get_embeddings()` returns `{}`, dream cycle completes with `clusters_found = 0` (no crash)
35. `test_dream_cycle_clustering_failure_graceful` — `get_embeddings()` raises `Exception`, dream cycle completes normally (log-and-degrade)
36. `test_dream_report_no_strategies_field` — verify `DreamReport` has no `strategies_extracted` attribute (dead field removed)
37. `test_last_clusters_property` — after dream cycle, `engine.last_clusters` returns the clusters from the most recent cycle
38. `test_dream_report_clusters_field` — verify `DreamReport.clusters` contains actual `EpisodeCluster` objects

**Dead code removal verification:**

39. `test_no_strategy_extraction_import` — verify `strategy_extraction` is not imported anywhere in `dreaming.py` (grep/import check)
40. `test_no_strategy_store_fn` — verify `DreamingEngine.__init__` does not accept `strategy_store_fn` parameter

---

## Validation Checklist

After implementation, verify:

- [ ] `src/probos/cognitive/strategy_extraction.py` deleted
- [ ] `tests/test_strategy_extraction.py` deleted
- [ ] `src/probos/cognitive/episode_clustering.py` created with `EpisodeCluster` + `cluster_episodes()`
- [ ] No `strategy_extraction` imports remain anywhere in codebase (search: `from probos.cognitive.strategy_extraction`)
- [ ] No `strategy_store_fn` parameter on `DreamingEngine.__init__()`
- [ ] No `strategy_store_fn` in `init_dreaming()` signature
- [ ] No `store_strategies_fn` lambda in `runtime.py`
- [ ] `DreamAdapter.store_strategies()` method removed
- [ ] `DreamReport.strategies_extracted` field removed
- [ ] `DreamReport.clusters_found` field exists (int, default 0)
- [ ] `DreamReport.clusters` field exists (list, default [])
- [ ] All codebase references to `strategies_extracted` updated to `clusters_found`
- [ ] `EpisodicMemory.get_embeddings()` method added
- [ ] `DreamingEngine._last_clusters` attribute initialized in `__init__`
- [ ] `DreamingEngine.last_clusters` property exists
- [ ] Dream cycle Step 6 calls `cluster_episodes()` with try/except (log-and-degrade)
- [ ] Dream cycle Step 6 calls `episodic_memory.get_embeddings()` with episode IDs
- [ ] Clustering failure does not crash dream cycle
- [ ] Missing embeddings does not crash dream cycle
- [ ] `StrategyAdvisor` class still exists (untouched — AD-534 replaces it)
- [ ] `strategies/` directory creation in startup still exists (StrategyAdvisor reads from it)
- [ ] All new tests pass: `uv run pytest tests/test_episode_clustering.py -v`
- [ ] No regressions in dream-related tests: `uv run pytest tests/test_dreaming.py tests/test_dream_scheduler.py -v`
- [ ] Full targeted suite passes: `uv run pytest tests/test_episode_clustering.py tests/test_dreaming.py tests/test_dream_scheduler.py tests/test_cognitive_agent.py -v`
