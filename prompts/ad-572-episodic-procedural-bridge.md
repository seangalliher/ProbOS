# AD-572: Episodic -> Procedural Bridge — Dream Step 7h

**Status:** Ready for builder
**Issue:** #359
**Dependencies:** AD-532 (procedure extraction), AD-533 (ProcedureStore), AD-531 (episode clustering)
**Estimated tests:** 10

---

## Problem

Dream Step 7 extracts procedures from success-dominant clusters (AD-532). But extraction only runs on episodes from the latest dream cycle. Episodic clusters that span multiple dream cycles or accumulate gradually over time never reach the success threshold in a single cycle. Patterns that emerge slowly across many dream cycles are missed.

Additionally, existing procedures are never re-evaluated against new cluster evidence. A procedure extracted 10 dream cycles ago may have new relevant episodes that could refine it, but there is no bridge between the latest clusters and existing procedures.

## Solution

Add an `EpisodicProceduralBridge` that scans current dream clusters against existing procedures in the ProcedureStore. It identifies (a) clusters that represent novel patterns not covered by existing procedures, and (b) clusters that match existing procedure intent_types but with new evidence that could evolve them. Wire as Dream Step 7h (after Step 7g notebook consolidation).

---

## Implementation

### 1. EpisodicProceduralBridge

**New file:** `src/probos/cognitive/episodic_procedural_bridge.py`

```python
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from probos.cognitive.episode_clustering import EpisodeCluster
from probos.cognitive.procedures import Procedure

logger = logging.getLogger(__name__)


class EpisodicProceduralBridge:
    """Bridges episodic clusters to procedural memory across dream cycles (AD-572)."""

    def __init__(
        self,
        config: "BridgeConfig",
        procedure_store: Any = None,
        episodic_memory: Any = None,
    ) -> None:
        self._config = config
        self._procedure_store = procedure_store
        self._episodic_memory = episodic_memory
```

Methods:

**`scan_for_procedures(clusters: list[EpisodeCluster], existing_procedures: list[Procedure]) -> list[Procedure]`**

For each success-dominant cluster (`cluster.is_success_dominant == True`):
1. Check if `cluster.episode_count >= config.min_cross_cycle_episodes`. Skip if too few episodes.
2. Check if the cluster's intent pattern (derived from `cluster.participating_agents` or episode intent types — use the centroid's closest match) is covered by an existing procedure via `_is_novel_pattern()`.
3. If novel: create a new `Procedure` with:
   - `id`: `uuid.uuid4().hex`
   - `name`: `f"Bridge: {cluster.cluster_id[:16]}"`
   - `intent_types`: extracted from the cluster's episodes (if accessible via episodic_memory). If not accessible, use empty list.
   - `origin_cluster_id`: `cluster.cluster_id`
   - `origin_agent_ids`: `cluster.participating_agents`
   - `provenance`: `cluster.episode_ids`
   - `extraction_date`: current timestamp
   - `evolution_type`: `"BRIDGED"`
   - `description`: `f"Cross-cycle pattern from {cluster.episode_count} episodes"`
4. If not novel but matches existing procedure: call `_merge_cross_cycle()` to update the existing procedure with new evidence.

Return the list of newly created procedures (not merged ones).

**`bridge_episodes_to_procedures(episodes: list, clusters: list[EpisodeCluster]) -> list[Procedure]`**

Convenience method that:
1. Loads existing procedures from `self._procedure_store.list_all()` if procedure_store is available.
2. Calls `scan_for_procedures(clusters, existing_procedures)`.
3. Returns newly bridged procedures.

If procedure_store is None or not available, return empty list.

**`_is_novel_pattern(cluster: EpisodeCluster, existing: list[Procedure]) -> bool`**

A cluster is novel if NO existing procedure has an `origin_cluster_id` matching this cluster AND no existing procedure has overlapping `intent_types` (check overlap of cluster episode_ids with procedure provenance). Use a simple heuristic:
- Compute overlap ratio: `len(set(cluster.episode_ids) & set(proc.provenance)) / len(cluster.episode_ids)` for each existing procedure.
- If any procedure has overlap ratio >= `(1.0 - config.novelty_threshold)`, the cluster is NOT novel.
- If no procedure exceeds the overlap threshold, the cluster IS novel.

**`_merge_cross_cycle(cluster: EpisodeCluster, existing_procedure: Procedure) -> Procedure`**

Update the existing procedure's provenance with new episode IDs:
- Merge `cluster.episode_ids` into `existing_procedure.provenance` (dedup).
- Increment the procedure's `success_count` by the cluster's success episode count (approximated as `int(cluster.success_rate * cluster.episode_count)`).
- Return the updated procedure.

Note: Since `Procedure` is a regular dataclass (not frozen), direct mutation is fine.

### 2. BridgeConfig

**File:** `src/probos/config.py`

Add `BridgeConfig(BaseModel)`:
```python
class BridgeConfig(BaseModel):
    """Episodic-procedural bridge configuration (AD-572)."""
    enabled: bool = True
    min_cross_cycle_episodes: int = 5
    novelty_threshold: float = 0.3
```

Add to `SystemConfig`:
```python
procedural_bridge: BridgeConfig = BridgeConfig()
```

### 3. Wire into DreamingEngine as Step 7h

**File:** `src/probos/cognitive/dreaming.py`

Add constructor parameter:
```python
episodic_procedural_bridge: Any = None,  # AD-572: cross-cycle procedural bridge
```

Store as:
```python
self._episodic_procedural_bridge = episodic_procedural_bridge
```

In the `dream_cycle()` method, after Step 7g (notebook consolidation, ends around line ~900) and before Step 8 (gap detection, starts around line ~902), insert:

```python
# Step 7h: Cross-cycle episodic-procedural bridge (AD-572)
bridged_procedures = 0
if self._episodic_procedural_bridge and clusters:
    try:
        bridged = self._episodic_procedural_bridge.bridge_episodes_to_procedures(
            episodes, clusters
        )
        bridged_procedures = len(bridged)
        if bridged_procedures > 0:
            # Store bridged procedures
            if self._procedure_store:
                for proc in bridged:
                    try:
                        await self._procedure_store.save(proc)
                    except Exception as e:
                        logger.debug("Step 7h: Failed to save bridged procedure: %s", e)
            procedures.extend(bridged)
            logger.debug("Step 7h: Bridged %d cross-cycle procedures", bridged_procedures)
    except Exception as e:
        logger.debug("Step 7h episodic-procedural bridge failed: %s", e)
```

### 4. Add to DreamReport

**File:** `src/probos/types.py`

Add field to `DreamReport` (after `wm_entries_flushed`):
```python
bridged_procedures: int = 0  # AD-572: cross-cycle procedural bridge
```

Update the DreamReport construction at the end of `dream_cycle()` to include:
```python
bridged_procedures=bridged_procedures,
```

### 5. Wire During Startup

**File:** `src/probos/startup/dreaming.py` (where DreamingEngine is constructed)

When building the DreamingEngine, pass the bridge:

```python
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
```

Create the bridge instance:
```python
bridge = None
if config.procedural_bridge.enabled:
    bridge = EpisodicProceduralBridge(
        config=config.procedural_bridge,
        procedure_store=procedure_store,
        episodic_memory=episodic_memory,
    )
```

Pass `episodic_procedural_bridge=bridge` to the DreamingEngine constructor.

**Locate the exact construction site:** In `dreaming.py`, find where `DreamingEngine(...)` is instantiated and add the parameter. Check the existing constructor call to identify all current parameters.

---

## Tests

**File:** `tests/test_ad572_procedural_bridge.py`

10 tests:

1. `test_scan_for_procedures` — provide clusters with enough episodes and no existing procedures, verify new procedures returned
2. `test_novel_pattern_detection` — cluster with episode IDs not in any procedure's provenance is detected as novel
3. `test_existing_pattern_skipped` — cluster whose episode IDs overlap heavily with an existing procedure's provenance is NOT novel
4. `test_bridge_episodes` — bridge_episodes_to_procedures with mock procedure_store returns bridged procedures
5. `test_merge_cross_cycle` — _merge_cross_cycle adds new episode IDs to provenance and increments success_count
6. `test_min_episode_threshold` — cluster with fewer than min_cross_cycle_episodes is skipped
7. `test_novelty_threshold` — adjust novelty_threshold and verify boundary behavior
8. `test_config_disabled` — when config.enabled is False, bridge returns empty list (test at startup wiring level)
9. `test_dream_step_integration` — create DreamingEngine with bridge, run dream_cycle with mock data, verify bridged_procedures count in DreamReport
10. `test_dream_report_field` — DreamReport has bridged_procedures field with default 0

Use `_Fake*` stubs for ProcedureStore and EpisodicMemory. Create test EpisodeCluster instances with known episode_ids and success rates.

---

## What This Does NOT Change

- No LLM-based procedure synthesis — bridge uses cluster metadata and heuristic overlap
- No cross-agent procedure merging — only single-agent procedure bridging
- No procedure versioning or version history tracking
- No changes to Step 7 (original procedure extraction) — Step 7h is additive
- No changes to existing Procedure fields except using existing `evolution_type` with new value "BRIDGED"
- No changes to ProcedureStore.save() — uses existing interface
- No changes to episode clustering logic

---

## Tracking

- `PROGRESS.md`: Add AD-572 as CLOSED
- `DECISIONS.md`: Add entry — "AD-572: EpisodicProceduralBridge as Dream Step 7h. Scans dream clusters against existing procedures for novel cross-cycle patterns. Novelty detected via episode provenance overlap (default 0.3 threshold). Minimum 5 episodes per cluster. New procedures get evolution_type='BRIDGED'."
- `docs/development/roadmap.md`: Update AD-572 row status
