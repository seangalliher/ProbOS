# AD-608: Retroactive Memory Evolution

**Status:** Ready for builder
**Scope:** New file + config edits + integration edits (~250 lines new, ~50 lines edits)
**Depends on:** AD-567a (AnchorFrame), AD-567b (recall_weighted), AD-598 (importance scoring)

**Acceptance Criteria:**
- All 12 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

Episodes in EpisodicMemory are write-once after storage. Anchor metadata established at storage time is never updated even when new information provides additional context. Relational links between episodes (cause-to-effect, question-to-answer, topic continuation) are never explicitly recorded.

This AD adds a `RetroactiveEvolver` that runs after each successful store, finding semantically similar recent episodes and propagating metadata (relational links, missing anchor fields) between them. This creates a web of explicit inter-episode relationships that improves recall relevance.

## Architecture

```
EpisodicMemory.store(new_episode)
    |
    +-- persist to ChromaDB
    +-- RetroactiveEvolver.evolve_on_store(new_episode)
            |
            +-- _find_neighbors(episode, k=5)
            |       |
            |       v
            |   EpisodicMemory.recall_weighted() or collection.query()
            |
            +-- for each neighbor above similarity_threshold:
            |       +-- _propagate_metadata(source, target, "relates_to")
            |       +-- _update_anchor_fields(target, missing fields)
            |
            v
        EvolutionReport(episodes_updated, relations_added, anchor_fields_propagated)
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/retroactive_evolver.py` | **NEW** -- RetroactiveEvolver, EvolutionReport |
| `src/probos/config.py` | Add RetroactiveConfig + wire into SystemConfig |
| `src/probos/cognitive/episodic.py` | Add setter, add update_episode_metadata(), call evolver in store() |
| `tests/test_ad608_retroactive_evolution.py` | **NEW** -- 12 tests |

---

## Implementation

### Section 1: RetroactiveConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `StorageGateConfig` (or after `MetabolismConfig` if AD-610 is not yet built):

```python
class RetroactiveConfig(BaseModel):
    """AD-608: Retroactive memory evolution — store-time metadata propagation."""

    enabled: bool = True
    neighbor_k: int = 5
    similarity_threshold: float = 0.7
    max_relations_per_episode: int = 10
    propagate_watch_section: bool = True
    propagate_department: bool = True
```

Wire into `SystemConfig`. SEARCH for the last field in SystemConfig. ADD after it:

```python
    retroactive: RetroactiveConfig = RetroactiveConfig()  # AD-608
```

### Section 2: EvolutionReport and RetroactiveEvolver

**File:** `src/probos/cognitive/retroactive_evolver.py` (NEW)

```python
"""AD-608: Retroactive Memory Evolution.

Store-time metadata propagation: when a new episode is stored, find
semantically similar recent episodes and propagate relational links
and missing anchor fields between them.

Creates a web of explicit inter-episode relationships stored as
``relations_json`` in ChromaDB metadata.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvolutionReport:
    """Summary of retroactive evolution for a single store operation."""

    episodes_updated: int = 0
    relations_added: int = 0
    anchor_fields_propagated: int = 0


class RetroactiveEvolver:
    """Evolves existing episode metadata when new episodes are stored.

    After each store, finds semantically similar recent episodes and:
    1. Adds relational links (``relates_to``, ``follows``, ``contradicts``).
    2. Propagates missing anchor fields from newer to older episodes
       (e.g., filling in ``watch_section`` or ``department`` for older
       episodes that lacked that context).

    Parameters
    ----------
    config : RetroactiveConfig-like or None
        Configuration. If None, uses hardcoded defaults.
    episodic_memory : EpisodicMemory-like or None
        Reference to episodic memory for neighbor lookup and metadata updates.
    """

    def __init__(
        self,
        config: Any = None,
        episodic_memory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory

        if config is not None:
            self._enabled: bool = config.enabled
            self._neighbor_k: int = config.neighbor_k
            self._similarity_threshold: float = config.similarity_threshold
            self._max_relations: int = config.max_relations_per_episode
            self._propagate_watch_section: bool = config.propagate_watch_section
            self._propagate_department: bool = config.propagate_department
        else:
            self._enabled = True
            self._neighbor_k = 5
            self._similarity_threshold = 0.7
            self._max_relations = 10
            self._propagate_watch_section = True
            self._propagate_department = True

    def set_episodic_memory(self, memory: Any) -> None:
        """Late-bind episodic memory reference."""
        self._episodic_memory = memory

    async def evolve_on_store(self, new_episode: Any) -> EvolutionReport:
        """Called after each successful store to evolve related episodes.

        Finds semantically similar neighbors, adds relational links,
        and propagates missing anchor fields.

        Parameters
        ----------
        new_episode : Episode
            The newly stored episode.

        Returns
        -------
        EvolutionReport
            Summary of changes made.
        """
        report = EvolutionReport()

        if not self._enabled:
            return report

        if not self._episodic_memory:
            return report

        # Find neighbors
        neighbors = await self._find_neighbors(new_episode)

        for neighbor in neighbors:
            neighbor_episode = neighbor.episode if hasattr(neighbor, 'episode') else neighbor
            neighbor_id = neighbor_episode.id if hasattr(neighbor_episode, 'id') else str(neighbor_episode)

            # Skip self-relation
            if neighbor_id == new_episode.id:
                continue

            similarity = neighbor.composite_score if hasattr(neighbor, 'composite_score') else 0.0
            if hasattr(neighbor, 'semantic_similarity'):
                similarity = max(similarity, neighbor.semantic_similarity)

            if similarity < self._similarity_threshold:
                continue

            # Determine relation type
            relation = self._classify_relation(new_episode, neighbor_episode)

            # Add bidirectional relations
            added_fwd = await self._propagate_metadata(
                new_episode, neighbor_id, relation,
            )
            added_rev = await self._propagate_metadata_reverse(
                neighbor_id, new_episode.id, relation,
            )

            if added_fwd or added_rev:
                report.relations_added += (1 if added_fwd else 0) + (1 if added_rev else 0)
                report.episodes_updated += 1

            # Propagate anchor fields from new episode to neighbor
            propagated = await self._update_anchor_fields(
                target_id=neighbor_id,
                source_episode=new_episode,
            )
            report.anchor_fields_propagated += propagated

        if report.episodes_updated > 0:
            logger.info(
                "AD-608: Evolved %d episodes — %d relations added, %d anchor fields propagated",
                report.episodes_updated, report.relations_added,
                report.anchor_fields_propagated,
            )

        return report

    async def _find_neighbors(
        self,
        episode: Any,
        k: int | None = None,
    ) -> list[Any]:
        """Retrieve semantically similar recent episodes.

        Uses EpisodicMemory's query capabilities to find similar episodes.
        Falls back gracefully if recall methods are unavailable.

        Parameters
        ----------
        episode : Episode
            The source episode to find neighbors for.
        k : int or None
            Number of neighbors to retrieve. Uses config default if None.

        Returns
        -------
        list[RecallScore]
            Neighbor episodes with similarity scores.
        """
        if not self._episodic_memory:
            return []

        k = k or self._neighbor_k
        query = episode.user_input or ""
        if episode.reflection:
            query += " " + episode.reflection

        if not query.strip():
            return []

        # Use the collection's query method directly for lightweight lookup
        collection = getattr(self._episodic_memory, '_collection', None)
        if collection is None:
            return []

        try:
            results = collection.query(
                query_texts=[query],
                n_results=k + 1,  # +1 to account for self-match
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            logger.debug("AD-608: Neighbor query failed", exc_info=True)
            return []

        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        # Convert to lightweight neighbor objects
        neighbors: list[Any] = []
        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        documents = results.get("documents", [[]])[0]

        for i, ep_id in enumerate(ids):
            if ep_id == episode.id:
                continue  # Skip self

            # ChromaDB returns L2 distance; convert to similarity
            distance = distances[i] if i < len(distances) else 1.0
            similarity = max(0.0, 1.0 - distance)

            _NeighborResult = type('_NeighborResult', (), {
                'episode': type('_Episode', (), {
                    'id': ep_id,
                    'anchors': None,
                })(),
                'composite_score': similarity,
                'semantic_similarity': similarity,
            })
            neighbors.append(_NeighborResult())

        return neighbors

    def _classify_relation(
        self,
        source: Any,
        target: Any,
    ) -> str:
        """Classify the relationship between two episodes.

        Simple heuristic classification based on temporal ordering
        and content overlap. Returns one of the standard relation types.
        """
        source_ts = getattr(source, 'timestamp', 0.0) or 0.0
        target_ts = getattr(target, 'timestamp', 0.0) or 0.0

        # If the new episode follows the target chronologically
        if source_ts > target_ts:
            return "follows"

        return "relates_to"

    async def _propagate_metadata(
        self,
        source_episode: Any,
        target_id: str,
        relation: str,
    ) -> bool:
        """Add a relational tag from source to target episode.

        Updates the target episode's ``relations_json`` metadata in ChromaDB.
        Respects max_relations_per_episode cap.

        Returns True if a relation was added, False if skipped.
        """
        if not self._episodic_memory:
            return False

        return await self._add_relation(
            episode_id=source_episode.id,
            related_id=target_id,
            relation=relation,
        )

    async def _propagate_metadata_reverse(
        self,
        target_id: str,
        source_id: str,
        relation: str,
    ) -> bool:
        """Add a reverse relational tag from target back to source.

        Creates the reverse direction of the relationship.
        """
        if not self._episodic_memory:
            return False

        # Reverse relation mapping
        reverse_map = {
            "follows": "followed_by",
            "caused_by": "causes",
            "answers": "answered_by",
            "contradicts": "contradicts",  # symmetric
            "relates_to": "relates_to",    # symmetric
        }
        reverse_relation = reverse_map.get(relation, "relates_to")

        return await self._add_relation(
            episode_id=target_id,
            related_id=source_id,
            relation=reverse_relation,
        )

    async def _add_relation(
        self,
        episode_id: str,
        related_id: str,
        relation: str,
    ) -> bool:
        """Add a single relation to an episode's relations_json metadata.

        Returns True if the relation was added, False if it already exists
        or the cap was reached.
        """
        mem = self._episodic_memory
        if not mem:
            return False

        collection = getattr(mem, '_collection', None)
        if collection is None:
            return False

        try:
            result = collection.get(ids=[episode_id], include=["metadatas"])
        except Exception:
            return False

        if not result or not result.get("ids"):
            return False

        meta = result["metadatas"][0] if result.get("metadatas") else {}
        relations_json = meta.get("relations_json", "[]")

        try:
            relations = json.loads(relations_json)
        except (json.JSONDecodeError, TypeError):
            relations = []

        # Check cap
        if len(relations) >= self._max_relations:
            return False

        # Check for duplicate relation
        for rel in relations:
            if (
                rel.get("related_episode_id") == related_id
                and rel.get("relation_type") == relation
            ):
                return False  # Already exists

        # Add relation
        relations.append({
            "related_episode_id": related_id,
            "relation_type": relation,
            "timestamp": time.time(),
        })

        meta["relations_json"] = json.dumps(relations)

        try:
            # Use update_episode_metadata if available, otherwise upsert
            update_fn = getattr(mem, 'update_episode_metadata', None)
            if update_fn:
                await update_fn(episode_id, {"relations_json": meta["relations_json"]})
            else:
                collection.update(ids=[episode_id], metadatas=[meta])
        except Exception:
            logger.debug(
                "AD-608: Failed to update relations for %s", episode_id, exc_info=True,
            )
            return False

        return True

    async def _update_anchor_fields(
        self,
        target_id: str,
        source_episode: Any,
    ) -> int:
        """Propagate missing anchor fields from source to target episode.

        Only propagates fields that are non-empty in the source and
        empty/missing in the target. Returns count of fields propagated.
        """
        if not self._episodic_memory:
            return 0

        source_anchors = getattr(source_episode, 'anchors', None)
        if source_anchors is None:
            return 0

        collection = getattr(self._episodic_memory, '_collection', None)
        if collection is None:
            return 0

        try:
            result = collection.get(ids=[target_id], include=["metadatas"])
        except Exception:
            return 0

        if not result or not result.get("ids"):
            return 0

        meta = result["metadatas"][0] if result.get("metadatas") else {}
        updates: dict[str, str] = {}
        propagated = 0

        # Propagate watch_section
        if self._propagate_watch_section and source_anchors.watch_section:
            current = meta.get("anchor_watch_section", "")
            if not current:
                updates["anchor_watch_section"] = source_anchors.watch_section
                propagated += 1

        # Propagate department
        if self._propagate_department and source_anchors.department:
            current = meta.get("anchor_department", "")
            if not current:
                updates["anchor_department"] = source_anchors.department
                propagated += 1

        if updates and propagated > 0:
            meta.update(updates)
            try:
                update_fn = getattr(self._episodic_memory, 'update_episode_metadata', None)
                if update_fn:
                    await update_fn(target_id, updates)
                else:
                    collection.update(ids=[target_id], metadatas=[meta])
            except Exception:
                logger.debug(
                    "AD-608: Failed to propagate anchor fields to %s",
                    target_id, exc_info=True,
                )
                return 0

        return propagated

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        return {
            "enabled": self._enabled,
            "neighbor_k": self._neighbor_k,
            "similarity_threshold": self._similarity_threshold,
            "max_relations": self._max_relations,
        }
```

### Section 3: EpisodicMemory Integration

**File:** `src/probos/cognitive/episodic.py`

#### 3a: Instance variable

In `__init__`, add after the `self._storage_gate` line (or after `self._activation_tracker` if earlier ADs are not built):

```python
        self._retroactive_evolver: Any = None  # AD-608
```

#### 3b: Setter method

After the `set_storage_gate` method (or after `set_activation_tracker`), add:

```python
    def set_retroactive_evolver(self, evolver: Any) -> None:
        """AD-608: Wire the retroactive evolver for store-time evolution."""
        self._retroactive_evolver = evolver
```

#### 3c: update_episode_metadata method

Add a new public method to EpisodicMemory. Place it after the `store()` method:

```python
    async def update_episode_metadata(
        self,
        episode_id: str,
        metadata_updates: dict[str, Any],
    ) -> bool:
        """AD-608: Update metadata fields on an existing episode.

        Used by RetroactiveEvolver to propagate relational links and
        anchor fields to existing episodes after new episodes are stored.

        Parameters
        ----------
        episode_id : str
            The episode to update.
        metadata_updates : dict[str, Any]
            Key-value pairs to merge into the episode's metadata.

        Returns
        -------
        bool
            True if the update succeeded, False otherwise.
        """
        if not self._collection:
            return False

        try:
            result = self._collection.get(ids=[episode_id], include=["metadatas"])
            if not result or not result.get("ids"):
                return False

            meta = result["metadatas"][0] if result.get("metadatas") else {}
            meta.update(metadata_updates)
            self._collection.update(ids=[episode_id], metadatas=[meta])
            return True
        except Exception:
            logger.debug(
                "AD-608: Failed to update metadata for episode %s",
                episode_id, exc_info=True,
            )
            return False
```

#### 3d: Call evolver in store()

In `async def store()`, after the episode is successfully persisted (after the AD-574 reconsolidation block if it exists, or after the `self._collection.add(...)` call, but before `await self._evict()`), add:

```python
        # AD-608: Retroactive evolution — propagate metadata to related episodes
        if self._retroactive_evolver is not None:
            try:
                await self._retroactive_evolver.evolve_on_store(episode)
            except Exception:
                logger.debug(
                    "AD-608: Retroactive evolution failed for episode %s",
                    episode.id, exc_info=True,
                )
```

**Builder:** Find the exact location by searching for `await self._evict()` in the `store()` method. Insert the evolver block before the `_evict()` call.

### Section 4: Startup Wiring

**File:** `src/probos/startup/cognitive_services.py`

After the StorageGate wiring (or after episodic memory initialization), create and wire the RetroactiveEvolver:

```python
    # AD-608: Retroactive evolver for episodic memory
    retroactive_evolver = None
    if config.retroactive.enabled and episodic_memory:
        try:
            from probos.cognitive.retroactive_evolver import RetroactiveEvolver as _RetroactiveEvolver

            retroactive_evolver = _RetroactiveEvolver(
                config=config.retroactive,
                episodic_memory=episodic_memory,
            )
            episodic_memory.set_retroactive_evolver(retroactive_evolver)
            logger.info("AD-608: RetroactiveEvolver initialized and wired to EpisodicMemory")
        except Exception as e:
            logger.warning("AD-608: RetroactiveEvolver failed to start: %s — continuing without", e)
```

**Builder:** Follow the same pattern as AD-610 StorageGate wiring or the activation_tracker wiring.

---

## Tests

**File:** `tests/test_ad608_retroactive_evolution.py` (NEW)

All tests use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mock chains. Each test is isolated with its own fixtures.

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_evolve_finds_neighbors` | evolve_on_store calls _find_neighbors and processes results |
| 2 | `test_relate_to_similar` | Similar episodes get "relates_to" or "follows" relations added |
| 3 | `test_propagate_watch_section` | Missing watch_section is propagated from source to target |
| 4 | `test_propagate_department` | Missing department is propagated from source to target |
| 5 | `test_max_relations_cap` | After max_relations_per_episode, no more relations are added |
| 6 | `test_no_self_relation` | An episode never creates a relation to itself |
| 7 | `test_bidirectional_relations` | Both forward and reverse relations are created |
| 8 | `test_evolution_report_counts` | EvolutionReport accurately counts updated episodes, relations, and fields |
| 9 | `test_similarity_threshold_filter` | Neighbors below similarity_threshold are not linked |
| 10 | `test_disabled_config` | When enabled=False, evolve_on_store returns empty report |
| 11 | `test_update_episode_metadata` | EpisodicMemory.update_episode_metadata updates ChromaDB metadata |
| 12 | `test_integration_with_store` | RetroactiveEvolver is called when an episode is stored in EpisodicMemory |

### Test Pattern

```python
import json
import pytest
import time

from probos.cognitive.retroactive_evolver import RetroactiveEvolver, EvolutionReport
from probos.types import Episode, AnchorFrame


class _FakeRetroactiveConfig:
    """Stub config for tests."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        neighbor_k: int = 5,
        similarity_threshold: float = 0.7,
        max_relations_per_episode: int = 10,
        propagate_watch_section: bool = True,
        propagate_department: bool = True,
    ):
        self.enabled = enabled
        self.neighbor_k = neighbor_k
        self.similarity_threshold = similarity_threshold
        self.max_relations_per_episode = max_relations_per_episode
        self.propagate_watch_section = propagate_watch_section
        self.propagate_department = propagate_department


class _FakeCollection:
    """Stub ChromaDB collection for metadata tests."""

    def __init__(self):
        self._store: dict[str, dict] = {}  # id -> metadata

    def get(self, ids, include=None):
        found_ids = [i for i in ids if i in self._store]
        if not found_ids:
            return {"ids": [], "metadatas": [], "documents": []}
        return {
            "ids": found_ids,
            "metadatas": [self._store[i] for i in found_ids],
            "documents": ["" for _ in found_ids],
        }

    def update(self, ids, metadatas):
        for i, eid in enumerate(ids):
            self._store[eid] = metadatas[i]

    def query(self, query_texts, n_results, include=None):
        # Return all stored episodes as neighbors with low distance
        all_ids = list(self._store.keys())[:n_results]
        return {
            "ids": [all_ids],
            "distances": [[0.2 for _ in all_ids]],  # low distance = high similarity
            "metadatas": [[self._store.get(i, {}) for i in all_ids]],
            "documents": [["" for _ in all_ids]],
        }


class _FakeEpisodicMemory:
    """Stub episodic memory for evolver tests."""

    def __init__(self):
        self._collection = _FakeCollection()

    async def update_episode_metadata(self, episode_id, metadata_updates):
        result = self._collection.get(ids=[episode_id])
        if result["ids"]:
            meta = result["metadatas"][0]
            meta.update(metadata_updates)
            self._collection.update(ids=[episode_id], metadatas=[meta])
            return True
        return False


@pytest.fixture
def fake_memory():
    return _FakeEpisodicMemory()


@pytest.fixture
def evolver(fake_memory):
    return RetroactiveEvolver(
        config=_FakeRetroactiveConfig(),
        episodic_memory=fake_memory,
    )


def _make_episode(
    *,
    episode_id: str = "",
    user_input: str = "test observation",
    anchors: AnchorFrame | None = None,
    timestamp: float = 0.0,
) -> Episode:
    """Helper to create Episode instances for testing."""
    import uuid
    return Episode(
        id=episode_id or uuid.uuid4().hex,
        timestamp=timestamp or time.time(),
        user_input=user_input,
        anchors=anchors,
    )
```

---

## Targeted Test Commands

After Section 1 (Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad608_retroactive_evolution.py::test_disabled_config -v
```

After Section 2 (RetroactiveEvolver class):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad608_retroactive_evolution.py -v
```

After Section 3 (EpisodicMemory integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad608_retroactive_evolution.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_episodic_memory.py -v -x
```

After Section 4 (Startup wiring):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad608_retroactive_evolution.py -v
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-608 Retroactive Memory Evolution — CLOSED`
- **docs/development/roadmap.md:** Update the AD-608 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-608: Retroactive Memory Evolution. Store-time metadata propagation via
  RetroactiveEvolver. After each store, finds k=5 semantic neighbors (ChromaDB
  query), adds bidirectional relational links (relates_to, follows, contradicts,
  answers, caused_by) stored as relations_json metadata. Propagates missing
  anchor fields (watch_section, department) from newer to older episodes.
  Max 10 relations per episode. Similarity threshold 0.7. Adds
  update_episode_metadata() public method to EpisodicMemory.
  ```

---

## Scope Boundaries

**DO:**
- Create `retroactive_evolver.py` with RetroactiveEvolver and EvolutionReport.
- Add RetroactiveConfig to config.py and wire into SystemConfig.
- Add `set_retroactive_evolver` setter to EpisodicMemory.
- Add `update_episode_metadata()` public method to EpisodicMemory.
- Call evolver.evolve_on_store() in store() after persistence.
- Wire evolver creation in startup/cognitive_services.py.
- Write all 12 tests.

**DO NOT:**
- Implement LLM-based relation classification (use heuristic temporal ordering only).
- Add retroactive embedding re-computation for existing episodes.
- Add cross-agent relation propagation (single-agent scope only).
- Modify existing recall_weighted() or score_recall() methods.
- Modify existing tests.
- Add docstrings/comments to code you did not change.
- Add `numpy`, `scipy`, or other heavy dependencies.
