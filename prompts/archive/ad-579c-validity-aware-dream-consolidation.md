# AD-579c: Validity-Aware Dream Consolidation

**Status:** Ready for builder
**Depends on:** AD-579b (provides `valid_from`, `valid_until` fields on `Episode` and `AnchorFrame`)
**Issue:** #37

## Problem Statement

Dream consolidation merges episodes without considering temporal validity. When Step 7 creates merged or evolved procedures from episode clusters, the resulting entries have no validity span derived from their source episodes. Superseded entries are not marked as expired. This means stale consolidated knowledge persists indefinitely in recall.

After AD-579b adds `valid_from` and `valid_until` to `Episode`, dream consolidation should:
1. Compute a validity span for merged clusters (earliest `valid_from` to latest `valid_until`).
2. Set `valid_until = now` on superseded episodes when a procedure evolves to replace them.
3. Propagate validity metadata through `EpisodeCluster`.

## Implementation

### Add Validity Fields to EpisodeCluster

File: `src/probos/cognitive/episode_clustering.py`

`EpisodeCluster` is `@dataclass` at line 19. Add two new fields **after** `participating_agents`:

```python
# AD-579c: Temporal validity span of the cluster
valid_from: float = 0.0    # min(valid_from or timestamp) across member episodes
valid_until: float = 0.0   # max(valid_until) across members; 0.0 = open-ended
```

### Add compute_cluster_validity() Helper

File: `src/probos/cognitive/episode_clustering.py`

Add a module-level function after the `EpisodeCluster` dataclass:

```python
def compute_cluster_validity(episodes: list[Any]) -> tuple[float, float]:
    """AD-579c: Compute the temporal validity span for a cluster of episodes.

    Args:
        episodes: Episode objects from the cluster.

    Returns:
        (valid_from, valid_until) tuple:
        - valid_from: earliest valid_from (or timestamp if valid_from == 0.0) across all episodes
        - valid_until: latest valid_until across all episodes; 0.0 if any episode has no expiry
    """
```

Logic:
- For each episode: `start = ep.valid_from if ep.valid_from > 0 else ep.timestamp`
- `valid_from = min(all starts)`
- If any episode has `valid_until == 0.0`, the cluster is open-ended: `valid_until = 0.0`
- Otherwise: `valid_until = max(all valid_until values)`

### Wire Validity into cluster_episodes()

File: `src/probos/cognitive/episode_clustering.py`

In `cluster_episodes()` (line 61), after constructing each `EpisodeCluster`, compute and assign validity:

```python
vf, vu = compute_cluster_validity(cluster_episodes_list)
# Pass to EpisodeCluster constructor
```

This requires that `cluster_episodes()` has access to the actual `Episode` objects for the cluster members, not just embeddings. Verify that `episodes` parameter (line 62: `episodes: list[Any]`) provides the Episode objects. The function already accesses `ep.id`, `ep.outcomes`, and `ep.agent_ids` on the episode objects, so Episode objects are available.

### Add update_episode_validity() to EpisodicMemory

File: `src/probos/cognitive/episodic.py`

Add a new method to `EpisodicMemory`:

```python
async def update_episode_validity(self, episode_id: str, valid_until: float) -> bool:
    """AD-579c: Update the valid_until metadata for an existing episode.

    Used by dream consolidation to mark superseded episodes as expired.
    Only updates ChromaDB metadata — does not modify the episode document.

    Returns True if the episode was found and updated, False otherwise.
    """
```

Implementation:
1. `self._collection.get(ids=[episode_id])` — check exists
2. If found, `self._collection.update(ids=[episode_id], metadatas=[{...existing metadata..., "valid_until": valid_until}])`
3. Return True/False

Important: ChromaDB `update()` requires the full metadata dict. Get existing metadata first, update the `valid_until` field, then pass the full dict.

### Wire into Dream Consolidation Step 7

File: `src/probos/cognitive/dreaming.py`

Modify Step 7 (procedure extraction, line 349) in `dream_cycle()`:

**7a: Procedure extraction from success clusters (existing)**

After a procedure is extracted from a cluster, if the cluster has validity data, set `valid_from` on the created episode (if one is stored). This is informational — procedures themselves are not episodes, but if the dream creates a summary episode for the consolidated procedure, use `cluster.valid_from`.

**7b: Procedure evolution (existing)**

When a procedure evolves to replace an older version (the `evolve_fix_procedure` or `evolve_derived_procedure` path), mark the superseded procedure's source episodes with `valid_until = time.time()`:

```python
# AD-579c: Mark superseded episodes as expired
if evolved and cluster.episode_ids:
    now = time.time()
    for ep_id in cluster.episode_ids:
        try:
            await self._episodic_memory.update_episode_validity(ep_id, valid_until=now)
        except Exception:
            logger.debug("AD-579c: Failed to expire episode %s", ep_id[:8])
```

Add this after the existing evolution success path. The `self._episodic_memory` reference is already available (constructor parameter, line 61: `episodic_memory: Any`). Store as `self._episodic_memory` — verify the existing attribute name:

Check: The DreamingEngine constructor stores `episodic_memory` as `self.episodic_memory` (no underscore prefix). Use `self.episodic_memory`.

### Wire Validity into micro_dream()

File: `src/probos/cognitive/dreaming.py`

In `micro_dream()`, if clusters are computed (micro dreams may skip clustering), propagate cluster validity to any stored episodes. micro_dream is lighter weight — only add validity if clustering actually runs.

Locate `micro_dream()` and check if it calls `cluster_episodes()`. If yes, apply the same `compute_cluster_validity()` call. If micro_dream does not cluster, skip this section (no change needed).

### Ensure cluster_episodes() Returns Validity

File: `src/probos/cognitive/episode_clustering.py`

After modifying `cluster_episodes()` to compute validity, verify the return type includes the new fields. Since `EpisodeCluster` is a dataclass with defaults, existing callers that don't use the fields are unaffected.

## Acceptance Criteria

1. `EpisodeCluster` has `valid_from` and `valid_until` fields.
2. `compute_cluster_validity()` correctly computes span from member episodes.
3. `cluster_episodes()` populates validity fields on returned clusters.
4. `update_episode_validity()` updates ChromaDB metadata for an episode.
5. Dream Step 7 evolution marks superseded episode sources with `valid_until = now`.
6. Open-ended validity (any member has `valid_until == 0`) propagates correctly.
7. All changes are backward compatible — clusters without validity data default to `0.0`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Test Plan

File: `tests/test_ad579c_validity_dream.py`

8 tests:

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_compute_cluster_validity_basic` | Computes min valid_from and max valid_until from episodes |
| 2 | `test_compute_cluster_validity_open_ended` | If any episode has `valid_until=0.0`, cluster validity is open-ended |
| 3 | `test_compute_cluster_validity_uses_timestamp_fallback` | When `valid_from=0.0`, uses `episode.timestamp` instead |
| 4 | `test_episode_cluster_has_validity_fields` | `EpisodeCluster` dataclass includes `valid_from` and `valid_until` with defaults |
| 5 | `test_cluster_episodes_populates_validity` | `cluster_episodes()` output has non-default validity when input episodes have validity |
| 6 | `test_update_episode_validity_succeeds` | `update_episode_validity()` updates ChromaDB metadata and returns True |
| 7 | `test_update_episode_validity_not_found` | Returns False for non-existent episode ID |
| 8 | `test_superseded_episodes_get_valid_until` | After dream evolution step, superseded episodes have `valid_until` set |

For tests 6-8, use real `EpisodicMemory` with `tmp_path` ChromaDB or a `_FakeEpisodicMemory` with an in-memory collection. For test 8, construct a minimal `DreamingEngine` with fakes for router/trust/etc. and invoke the evolution path directly.

Run targeted: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad579c_validity_dream.py -v`

## Do Not Build

- No LLM-based validity inference from episode content.
- No validity UI or API endpoints.
- No retroactive validity propagation on existing stored episodes.
- No validity-aware micro_dream changes unless micro_dream already calls `cluster_episodes()`.
- No changes to recall_weighted (already handled by AD-579b).

## Tracker Updates

- `PROGRESS.md`: Add `AD-579c Validity-Aware Dream Consolidation — CLOSED` under Memory Architecture
- `DECISIONS.md`: Add entry: "AD-579c: Dream consolidation now computes temporal validity for episode clusters and marks superseded episodes as expired via valid_until. EpisodeCluster gains valid_from/valid_until fields. update_episode_validity() added to EpisodicMemory."
- `docs/development/roadmap.md`: Update AD-579c row to COMPLETE
- Issue: #37
