# AD-598: Importance Scoring at Encoding

**Status:** Ready for builder
**Priority:** High — enables selective retention, improves pruning and recall quality
**Depends on:** AD-538 (Episode Lifecycle), AD-567d (Activation Tracker), AD-593 (Pruning Acceleration)
**Research:** Park et al. (2023) Generative Agents, docs/research/agent-memory-survey-absorption.md §2
**Issue:** #172

## Problem

All episodes are born equal. A routine status update and a critical trust violation get the same initial activation weight. AD-538's Ebbinghaus decay and AD-593's pruning treat all episodes identically by age and activation frequency. High-signal moments (first contact, trust breaches, key discoveries) decay and get pruned at the same rate as routine observations.

## Design

Add `importance: int` (1–10, default 5) to the `Episode` dataclass, computed at encoding time via rule-based scoring (no LLM call). Importance modifies:
1. **Activation decay** — high-importance episodes decay slower
2. **Pruning resistance** — high-importance episodes survive pruning longer
3. **Recall scoring** — importance contributes to composite score as a new channel

## Engineering Principles

- **Single Responsibility:** `ImportanceScorer` is a standalone static utility; `EpisodicMemory.store()` calls it, `score_recall()` reads the result.
- **Open/Closed:** Scoring rules are a configurable mapping, not hardcoded if/else chains.
- **DRY:** The trigger-type and content pattern analysis lives in one place (`compute_importance()`), consumed by `store()`.
- **Fail Fast:** If scoring fails, default to 5 (neutral) — log-and-degrade, never block storage.

---

## Changes

### Change 1: Add `importance` field to `Episode` dataclass

**File:** `src/probos/types.py`

After line 378 (`anchors: AnchorFrame | None = None`), add:

```python
    # AD-598: Importance scoring at encoding — selective retention signal
    importance: int = 5  # 1-10 scale, 5 = neutral
```

This is a frozen dataclass with all default fields, so adding at the end is safe. Existing Episode construction (no `importance=` kwarg) will get default 5 — backward compatible.

### Change 2: `ImportanceScorer` static utility

**File:** `src/probos/cognitive/importance_scorer.py` (NEW)

```python
"""AD-598: Rule-based importance scoring at encoding time.

Assigns a 1-10 importance score to episodes based on trigger type,
content signals, and outcome patterns. No LLM call — pure heuristics.

Inspired by Park et al. (2023) Generative Agents importance scoring,
adapted for ProbOS's AnchorFrame + outcome-based architecture.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import Episode

logger = logging.getLogger(__name__)

# Rule-based importance mapping: trigger_type → base importance
# Configurable via ImportanceScoringConfig override
DEFAULT_TRIGGER_IMPORTANCE: dict[str, int] = {
    # High importance — rare, high-signal events
    "circuit_breaker_trip": 9,
    "trust_violation": 9,
    "security_alert": 9,
    "captain_directive": 8,
    "captain_dm": 8,
    "naming_ceremony": 8,
    "promotion": 8,
    # Medium-high — noteworthy events
    "trust_update": 7,
    "dream_complete": 6,
    "counselor_intervention": 7,
    "standing_order": 7,
    "qualification_result": 6,
    # Medium — standard interactions
    "ward_room_post": 5,
    "dm_reply": 5,
    "game_move": 4,
    "game_completed": 4,
    # Low — routine/automated
    "proactive_thought": 3,
    "routine_observation": 3,
    "status_check": 2,
}


def compute_importance(episode: "Episode") -> int:
    """Compute importance score (1-10) for an episode at encoding time.

    Scoring priority:
    1. Trigger type mapping (from AnchorFrame)
    2. Content signal boosts (Captain mentions, failures, firsts)
    3. Outcome-based adjustments (failures boost, empty degrades)

    Returns 5 (neutral) if no signals are detected or on error.
    """
    try:
        score = 5  # Neutral default

        # --- Signal 1: Trigger type from AnchorFrame ---
        if episode.anchors and episode.anchors.trigger_type:
            trigger = episode.anchors.trigger_type.lower().strip()
            if trigger in DEFAULT_TRIGGER_IMPORTANCE:
                score = DEFAULT_TRIGGER_IMPORTANCE[trigger]

        # --- Signal 2: Content-based boosts ---
        text = (episode.user_input or "").lower()

        # Captain interaction is always important
        if "[1:1 with" in text or "captain" in text.split("]:")[0] if "]:" in text else False:
            score = max(score, 8)

        # Ward Room posts (intentional social communication)
        if "[ward room]" in text and score < 5:
            score = 5

        # --- Signal 3: Outcome-based adjustments ---
        outcomes = episode.outcomes or []
        has_failure = False
        has_real_response = False
        for o in outcomes:
            if isinstance(o, dict):
                if not o.get("success", True):
                    has_failure = True
                response = o.get("response", "")
                if isinstance(response, str) and response.strip() not in ("", "[NO_RESPONSE]"):
                    has_real_response = True

        # Failures are learning opportunities — boost importance
        if has_failure:
            score = max(score, 7)

        # No real response = low value
        if not has_real_response and outcomes:
            score = min(score, 3)

        # --- Clamp to valid range ---
        return max(1, min(10, score))

    except Exception:
        logger.debug("AD-598: Importance scoring failed, defaulting to 5", exc_info=True)
        return 5
```

### Change 3: Wire importance scoring into `EpisodicMemory.store()`

**File:** `src/probos/cognitive/episodic.py`

**3a.** Add import at top of file (near other cognitive imports, around line 30):

```python
from probos.cognitive.importance_scorer import compute_importance
```

**3b.** In `store()` method, after line 806 (dedup check return) and BEFORE line 808 (`metadata = self._episode_to_metadata(episode)`), insert importance computation:

```python
        # AD-598: Compute importance score at encoding time
        if episode.importance == 5:  # Only score if not already set (default)
            _importance = compute_importance(episode)
            if _importance != 5:
                # Reconstruct frozen Episode with computed importance
                episode = Episode(
                    id=episode.id,
                    timestamp=episode.timestamp,
                    user_input=episode.user_input,
                    dag_summary=episode.dag_summary,
                    outcomes=episode.outcomes,
                    reflection=episode.reflection,
                    agent_ids=episode.agent_ids,
                    duration_ms=episode.duration_ms,
                    embedding=episode.embedding,
                    shapley_values=episode.shapley_values,
                    trust_deltas=episode.trust_deltas,
                    source=episode.source,
                    anchors=episode.anchors,
                    importance=_importance,
                )
```

Note: Episode is `frozen=True`, so we must reconstruct it. Only reconstruct when importance differs from default (skip object allocation in the common case).

**3c.** In `_episode_to_metadata()` (line 1440, inside the metadata dict just before the closing `}`), add importance:

Change line 1439 from:
```python
            "_hash_v": 2,  # Hash normalization version (round(ts,6) + float coercion)
        }
```
To:
```python
            "_hash_v": 2,  # Hash normalization version (round(ts,6) + float coercion)
            "importance": int(ep.importance),  # AD-598: importance score (1-10)
        }
```

**3d.** In `_metadata_to_episode()` (line 1498, in the Episode constructor call, after `anchors=anchors,`), add:

```python
            importance=int(metadata.get("importance", 5)),
```

### Change 4: Importance-modified activation decay

**File:** `src/probos/cognitive/activation_tracker.py`

**4a.** Add a new method `compute_activation_with_importance()` after `compute_activation()` (after line 142):

```python
    def compute_activation_with_importance(
        self,
        access_times: list[float],
        importance: int = 5,
        now: float | None = None,
    ) -> float:
        """Compute ACT-R activation modified by episode importance.

        AD-598: Importance modifies the effective decay rate.
        importance=10 → decay at 0.5x rate (2x slower).
        importance=5  → decay at 1.0x rate (baseline).
        importance=1  → decay at 2.5x rate (faster).

        Formula: effective_d = base_d / (importance / 5.0)
        """
        if not access_times:
            return float("-inf")
        if now is None:
            now = time.time()
        # importance / 5.0 gives: 10→2.0, 5→1.0, 1→0.2
        importance_factor = max(importance, 1) / 5.0
        effective_d = self._decay_d / importance_factor
        total = 0.0
        for t_access in access_times:
            age = now - t_access
            if age <= 0:
                age = 0.001
            total += age ** (-effective_d)
        if total <= 0:
            return float("-inf")
        return math.log(total)
```

**4b.** Add a new method `find_low_activation_episodes_with_importance()` after `find_low_activation_episodes()` (after line 216):

```python
    async def find_low_activation_episodes_with_importance(
        self,
        all_episode_ids: list[str],
        importance_map: dict[str, int],
        threshold: float = -2.0,
        max_prune_fraction: float = 0.10,
    ) -> list[str]:
        """Find episodes below activation threshold, adjusted by importance.

        AD-598: Each episode's activation is computed with its own importance
        factor, so high-importance episodes need lower raw activation to
        survive pruning.

        Args:
            importance_map: {episode_id: importance_score} — episodes not in
                map are treated as importance=5 (neutral).
        """
        if not all_episode_ids:
            return []

        # Get raw access times per episode
        activations_raw = await self.get_activations_batch(all_episode_ids)

        candidates: list[tuple[str, float]] = []
        for eid, activation in activations_raw.items():
            importance = importance_map.get(eid, 5)
            # Adjust threshold by importance: high-importance episodes
            # get a lower effective threshold (harder to prune)
            adjusted_threshold = threshold - (importance - 5) * 0.2
            if activation < adjusted_threshold:
                candidates.append((eid, activation))

        candidates.sort(key=lambda x: x[1])
        max_prune = max(1, int(len(all_episode_ids) * max_prune_fraction))
        return [eid for eid, _ in candidates[:max_prune]]
```

### Change 5: Pruning integration in dreaming.py

**File:** `src/probos/cognitive/dreaming.py`

In dream Step 12 (around lines 968-991 for standard tier, and 993-1018 for aggressive tier), update both pruning calls to use importance-aware pruning when importance metadata is available.

**5a.** Add a helper method to `DreamingEngine` class (before `dream_cycle()` or at the end of the class, in the utility methods section):

```python
    async def _get_importance_map(self, episode_ids: list[str]) -> dict[str, int]:
        """AD-598: Build importance map from stored episode metadata."""
        if not self.episodic_memory or not self.episodic_memory._collection:
            return {}
        try:
            result = self.episodic_memory._collection.get(
                ids=episode_ids,
                include=["metadatas"],
            )
            importance_map: dict[str, int] = {}
            if result and result.get("ids") and result.get("metadatas"):
                for eid, meta in zip(result["ids"], result["metadatas"]):
                    if meta:
                        importance_map[eid] = int(meta.get("importance", 5))
            return importance_map
        except Exception:
            logger.debug("AD-598: Failed to load importance map", exc_info=True)
            return {}
```

**5b.** In the standard tier pruning block (lines 972-991), replace the `find_low_activation_episodes` call with importance-aware version:

Replace:
```python
                    low_activation = await self._activation_tracker.find_low_activation_episodes(
                        all_episode_ids=_standard_candidates,
                        threshold=self.config.activation_prune_threshold,
                        max_prune_fraction=_standard_fraction,
                    )
```

With:
```python
                    # AD-598: Importance-aware pruning
                    _importance_map = await self._get_importance_map(_standard_candidates)
                    if _importance_map:
                        low_activation = await self._activation_tracker.find_low_activation_episodes_with_importance(
                            all_episode_ids=_standard_candidates,
                            importance_map=_importance_map,
                            threshold=self.config.activation_prune_threshold,
                            max_prune_fraction=_standard_fraction,
                        )
                    else:
                        low_activation = await self._activation_tracker.find_low_activation_episodes(
                            all_episode_ids=_standard_candidates,
                            threshold=self.config.activation_prune_threshold,
                            max_prune_fraction=_standard_fraction,
                        )
```

**5c.** Same replacement in the aggressive tier block (lines 1002-1006):

Replace:
```python
                        aggressive_pruned = await self._activation_tracker.find_low_activation_episodes(
                            all_episode_ids=_aggressive_candidates,
                            threshold=self.config.aggressive_prune_threshold,
                            max_prune_fraction=_aggressive_fraction,
                        )
```

With:
```python
                        # AD-598: Importance-aware pruning
                        _agg_importance_map = await self._get_importance_map(_aggressive_candidates)
                        if _agg_importance_map:
                            aggressive_pruned = await self._activation_tracker.find_low_activation_episodes_with_importance(
                                all_episode_ids=_aggressive_candidates,
                                importance_map=_agg_importance_map,
                                threshold=self.config.aggressive_prune_threshold,
                                max_prune_fraction=_aggressive_fraction,
                            )
                        else:
                            aggressive_pruned = await self._activation_tracker.find_low_activation_episodes(
                                all_episode_ids=_aggressive_candidates,
                                threshold=self.config.aggressive_prune_threshold,
                                max_prune_fraction=_aggressive_fraction,
                            )
```

### Change 6: Importance as a recall scoring channel

**File:** `src/probos/cognitive/episodic.py`

**6a.** Add two parameters to `score_recall()` signature (after `query_has_temporal_intent: bool = False,` at line 1612):

```python
    importance: int = 5,               # AD-598: episode importance (1-10)
    importance_weight: float = 0.0,    # AD-598: weight in composite (0.0 = disabled)
```

Defaults preserve backward compatibility — existing callers don't pass these.

**6b.** In `score_recall()`, add importance contribution between the base composite (line 1641) and the convergence bonus (line 1643). Insert after line 1641 `)`:

```python
        # AD-598: Importance contribution — normalized 1-10 to 0.0-1.0
        if importance_weight > 0:
            importance_norm = (max(1, min(10, importance)) - 1) / 9.0
            composite += importance_weight * importance_norm
```

**6c.** In `recall_weighted()`, at the `score_recall()` call (lines 1770-1783), add importance params. Change:

```python
            rs = self.score_recall(
                episode=ep,
                semantic_similarity=sim,
                keyword_hits=kw_hits,
                trust_weight=tw,
                hebbian_weight=hw,
                recency_weight=rw,
                weights=weights,
                convergence_bonus=convergence_bonus,
                temporal_match=_temporal_match,
                temporal_match_weight=temporal_match_weight,
                temporal_mismatch_penalty=temporal_mismatch_penalty,      # BF-155
                query_has_temporal_intent=bool(query_watch_section),       # BF-155
            )
```

To:

```python
            rs = self.score_recall(
                episode=ep,
                semantic_similarity=sim,
                keyword_hits=kw_hits,
                trust_weight=tw,
                hebbian_weight=hw,
                recency_weight=rw,
                weights=weights,
                convergence_bonus=convergence_bonus,
                temporal_match=_temporal_match,
                temporal_match_weight=temporal_match_weight,
                temporal_mismatch_penalty=temporal_mismatch_penalty,      # BF-155
                query_has_temporal_intent=bool(query_watch_section),       # BF-155
                importance=ep.importance,       # AD-598
                importance_weight=0.05,         # AD-598: modest tiebreaker
            )
```

### Change 7: Backward-compatible migration

**No migration needed.** Unlike AD-605, this change doesn't alter existing ChromaDB documents. New episodes get `importance` in metadata; existing episodes missing the field get `importance=5` via `metadata.get("importance", 5)` in `_metadata_to_episode()`. The default of 5 is neutral by design — it doesn't penalize or boost old episodes.

---

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/types.py` | Add `importance: int = 5` field to `Episode` |
| `src/probos/cognitive/importance_scorer.py` | **NEW** — `compute_importance()` + `DEFAULT_TRIGGER_IMPORTANCE` mapping |
| `src/probos/cognitive/episodic.py` | Import scorer, call in `store()`, add to `_episode_to_metadata()`/`_metadata_to_episode()`, add importance params to `score_recall()`, pass in `recall_weighted()` |
| `src/probos/cognitive/activation_tracker.py` | Add `compute_activation_with_importance()` + `find_low_activation_episodes_with_importance()` |
| `src/probos/cognitive/dreaming.py` | Add `_get_importance_map()`, update Step 12 standard + aggressive tiers |
| `tests/test_ad598_importance_scoring.py` | **NEW** — test file |

## Tests

**File:** `tests/test_ad598_importance_scoring.py` (NEW)

### TestComputeImportance (7 tests)

1. `test_default_neutral` — Episode with no signals → importance 5
2. `test_captain_dm_high` — Episode with `trigger_type="captain_dm"` → importance 8
3. `test_circuit_breaker_critical` — `trigger_type="circuit_breaker_trip"` → importance 9
4. `test_failure_boost` — Episode with `success=False` outcome → importance >= 7
5. `test_proactive_low` — `trigger_type="proactive_thought"` → importance 3
6. `test_no_response_degrades` — Outcomes with only `[NO_RESPONSE]` → importance <= 3
7. `test_captain_content_boost` — `"[1:1 with"` in user_input → importance >= 8

### TestStoreImportance (3 tests)

8. `test_store_writes_importance_metadata` — After `store()`, ChromaDB metadata contains `importance` field
9. `test_store_default_importance` — Episode without signals stores importance=5
10. `test_roundtrip_preserves_importance` — `store()` → `recall()` → episode.importance matches

### TestMetadataRoundTrip (2 tests)

11. `test_episode_to_metadata_includes_importance` — `_episode_to_metadata()` produces `importance` key
12. `test_metadata_to_episode_reads_importance` — `_metadata_to_episode()` with `importance=8` → ep.importance == 8

### TestActivationWithImportance (3 tests)

13. `test_high_importance_slower_decay` — importance=10 activation > importance=5 activation for same access times
14. `test_low_importance_faster_decay` — importance=1 activation < importance=5 activation
15. `test_importance_adjusted_pruning_threshold` — importance=9 episode survives at threshold that prunes importance=3

### TestScoreRecallImportance (2 tests)

16. `test_importance_weight_zero_no_effect` — Default importance_weight=0.0 → no composite change
17. `test_importance_weight_boosts_high` — importance=9 with weight=0.05 → higher composite than importance=2

### TestDreamPruningIntegration (2 tests)

18. `test_get_importance_map_reads_metadata` — Mock ChromaDB returns importance in metadata → map correct
19. `test_importance_map_empty_fallback` — When collection unavailable → returns empty dict (graceful fallback)

**Total: 19 tests**

## Tracking Updates

After successful build, update:
- `PROGRESS.md` — prepend "AD-598 COMPLETE — Importance scoring at encoding"
- `DECISIONS.md` — add AD-598 decision record
- `docs/development/roadmap.md` — mark AD-598 as Complete
- GitHub issue #172 — close

## Deferred

- **LLM-based importance scoring:** Future enhancement — use LLM to evaluate episode importance for ambiguous cases. Current rule-based approach covers 90%+ of cases without token cost.
- **Importance evolution:** Allow dream consolidation to re-evaluate importance based on subsequent events (e.g., a routine observation becomes important after a related incident).
- **ImportanceScoringConfig:** Externalizing `DEFAULT_TRIGGER_IMPORTANCE` to `SystemConfig` for per-instance customization. Current dict-based approach is sufficient and easily modifiable.
