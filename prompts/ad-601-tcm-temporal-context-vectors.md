# AD-601: TCM Temporal Context Vectors

**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-567a (Anchor System — COMPLETE), AD-570 (Anchor-Indexed Recall — COMPLETE), AD-584d (Enriched Embedding — COMPLETE)
**Files:** `src/probos/types.py` (EDIT), `src/probos/config.py` (EDIT), `src/probos/cognitive/temporal_context.py` (NEW), `src/probos/cognitive/episodic.py` (EDIT), `tests/test_ad601_tcm_temporal_context.py` (NEW)

## Problem

ProbOS encodes temporal context as discrete `watch_section` labels (7 naval watches: mid, morning, forenoon, afternoon, first_dog, second_dog, first). The recall scoring in `score_recall()` applies a binary temporal match bonus:

- Episode in same watch section as query: `+0.25` bonus (BF-147)
- Episode in different watch section: `-0.15` penalty (BF-155)
- No gradient between "5 minutes ago in the same watch" and "3.5 hours ago in the same watch"

This produces a step-function temporal proximity signal. Two episodes from the same forenoon watch but 3 hours apart score identically to two episodes 5 minutes apart. Conversely, an episode from 1 minute before a watch boundary gets the full mismatch penalty even though it is temporally adjacent.

Howard & Kahana's (2002) Temporal Context Model (TCM) solves this with a continuously drifting context vector. Each encoded episode captures a snapshot of the context vector at encoding time. At recall, cosine similarity between the current context vector and stored context vectors provides a smooth temporal proximity gradient. Nearby episodes are more similar than distant ones, regardless of watch boundaries.

**What this does NOT include:**
- Replacing `watch_section` (kept as secondary discrete signal for anchor-indexed recall and backward compatibility)
- Modifying the anchor confidence scoring in `anchor_quality.py` (TCM is orthogonal)
- Any numpy/scipy dependencies (pure Python math, matching ProbOS convention)
- Retroactive migration of existing episodes (new episodes get TCM vectors; old episodes have `None` and fall back to watch_section scoring)

---

## Section 1: TemporalContextModel Engine

**File:** `src/probos/cognitive/temporal_context.py` (NEW)

Implement the TCM engine as a standalone module. Pure Python, no external dependencies beyond stdlib.

### Design

The TCM maintains a single context vector `c` of dimensionality `d` (default 16). On each new episode encoding:

```
c(t+1) = rho * c(t) + (1 - rho) * input_signal(t)
```

Where:
- `rho` (drift rate, default 0.95) controls how slowly the context drifts. Higher values = longer temporal memory, slower drift.
- `input_signal(t)` is a low-dimensional summary derived from the episode. NOT the full ChromaDB embedding (which is 384-dim for MiniLM). Instead, a deterministic hash-based projection of the episode content into the TCM dimension space.

At recall time, temporal similarity between current context `c_now` and a stored context `c_stored` is computed via cosine similarity.

### Implementation

```python
"""AD-601: Temporal Context Model — Howard & Kahana (2002).

Maintains a slowly drifting context vector that enables graded temporal
similarity between episodes. Replaces binary watch_section matching with
a continuous proximity gradient while keeping watch_section as a secondary
signal for backward compatibility.

Pure Python — no numpy/scipy (ProbOS convention).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["TemporalContextModel", "TCMConfig"]


@dataclass
class TCMConfig:
    """Configuration for the Temporal Context Model."""
    dimension: int = 16           # Context vector dimensionality
    drift_rate: float = 0.95      # rho — exponential decay (0.0–1.0)
    tcm_weight: float = 0.15      # Weight of TCM similarity in score_recall composite
    fallback_watch_weight: float = 0.05  # Residual weight for legacy watch_section match (was 0.10)


class TemporalContextModel:
    """Temporal Context Model engine.

    Maintains a drifting context vector and provides:
    - update(episode) — evolve context after encoding a new episode
    - get_context_vector() — snapshot of the current context
    - compute_similarity(stored_vector) — cosine similarity to current context
    - project_episode(episode) — hash-based projection into TCM space
    """

    def __init__(self, config: TCMConfig | None = None) -> None:
        self._config = config or TCMConfig()
        self._dim = self._config.dimension
        self._rho = self._config.drift_rate
        # Initialize context vector to zeros — first update will set it to the
        # first episode's projection (since 0.95 * zeros + 0.05 * signal ≈ signal * 0.05).
        self._context: list[float] = [0.0] * self._dim
        self._initialized = False  # Track whether any episode has been encoded

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def drift_rate(self) -> float:
        return self._rho

    def get_context_vector(self) -> list[float]:
        """Return a copy of the current context vector."""
        return list(self._context)

    def set_context_vector(self, vector: list[float]) -> None:
        """Restore context vector from a stored snapshot.

        Used during warm boot to resume from the last stored context.
        """
        if len(vector) != self._dim:
            raise ValueError(
                f"Vector dimension mismatch: expected {self._dim}, got {len(vector)}"
            )
        self._context = list(vector)
        self._initialized = True

    def update(self, episode_content: str, timestamp: float = 0.0) -> list[float]:
        """Evolve context vector with a new episode's input signal.

        Returns the context vector snapshot AFTER the update (this is
        what gets stored alongside the episode).

        TCM update rule: c(t+1) = rho * c(t) + (1 - rho) * e(t)
        where e(t) is the hash-based projection of the episode content.
        """
        signal = self._project(episode_content, timestamp)

        if not self._initialized:
            # First episode: set context directly to the signal (no decay from zeros)
            self._context = list(signal)
            self._initialized = True
        else:
            for i in range(self._dim):
                self._context[i] = self._rho * self._context[i] + (1.0 - self._rho) * signal[i]

        # Normalize to unit length to keep cosine similarity meaningful
        self._context = _normalize(self._context)

        return list(self._context)

    def compute_similarity(self, stored_vector: list[float]) -> float:
        """Cosine similarity between current context and a stored context vector.

        Returns 0.0–1.0 (clamped). 1.0 = identical temporal context.
        """
        if not stored_vector or len(stored_vector) != self._dim:
            return 0.0
        if not self._initialized:
            return 0.0
        return max(0.0, min(1.0, _cosine_similarity(self._context, stored_vector)))

    def _project(self, content: str, timestamp: float = 0.0) -> list[float]:
        """Hash-based deterministic projection into TCM dimension space.

        Uses SHA-256 of the content to generate a reproducible unit vector.
        Incorporates timestamp fractional component to add temporal texture
        (two identical messages sent seconds apart get slightly different projections).
        """
        # Combine content + timestamp for projection uniqueness
        material = f"{content}|{timestamp:.6f}"
        digest = hashlib.sha256(material.encode("utf-8")).digest()

        # Unpack digest bytes as floats: take pairs of bytes, map to [-1, 1]
        raw: list[float] = []
        for i in range(self._dim):
            # Use 2 bytes per dimension (16 dims * 2 bytes = 32 bytes = SHA-256 output)
            idx = (i * 2) % len(digest)
            val = (digest[idx] * 256 + digest[(idx + 1) % len(digest)]) / 65535.0
            raw.append(val * 2.0 - 1.0)  # Map [0,1] to [-1,1]

        return _normalize(raw)


# ---- Pure Python vector math ------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Returns -1.0 to 1.0."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(len(a)):
        dot += a[i] * b[i]
        norm_a += a[i] * a[i]
        norm_b += b[i] * b[i]
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom < 1e-12:
        return 0.0
    return dot / denom


def _normalize(v: list[float]) -> list[float]:
    """Normalize a vector to unit length."""
    mag = math.sqrt(sum(x * x for x in v))
    if mag < 1e-12:
        return v  # Zero vector — can't normalize
    return [x / mag for x in v]


def serialize_tcm_vector(vector: list[float]) -> str:
    """Serialize a TCM context vector to a compact JSON string for ChromaDB metadata.

    Rounds to 6 decimal places to keep metadata compact while preserving
    sufficient precision for cosine similarity (IEEE 754 double has ~15 sig digits).
    """
    return json.dumps([round(x, 6) for x in vector])


def deserialize_tcm_vector(raw: str) -> list[float] | None:
    """Deserialize a TCM context vector from ChromaDB metadata.

    Returns None if the string is empty or malformed (legacy episodes
    without TCM vectors).
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
            return [float(x) for x in data]
    except (json.JSONDecodeError, TypeError):
        pass
    return None
```

### Key design decisions

1. **Hash-based projection, not embedding truncation.** ChromaDB embeddings are 384-dim (MiniLM). Truncating to 16 dims would lose most information. A hash-based projection into a separate 16-dim space is deterministic, fast, and produces orthogonal dimensions — the signal captures *identity* of the content, not its semantic meaning. TCM doesn't need semantic meaning; it needs a unique fingerprint that drifts the context.

2. **Normalization after update.** Without normalization, the context vector magnitude grows unboundedly over many updates. Normalizing to unit length after each update ensures cosine similarity stays in [0,1] and the drift rate `rho` controls temporal memory span rather than vector scale.

3. **First-episode initialization.** Setting context directly to the first signal (instead of `0.95 * zeros + 0.05 * signal`) avoids the cold-start problem where the first few episodes all have near-identical context vectors because the zero-initialized context dominates.

4. **Compact serialization.** Context vectors stored as JSON arrays in ChromaDB metadata. At d=16 with 6 decimal places, each vector serializes to ~180 bytes — well within ChromaDB's metadata limits.

---

## Section 2: Add TCM Config to MemoryConfig

**File:** `src/probos/config.py` (EDIT)

Add TCM configuration fields to the `MemoryConfig` class. Place after the `recall_temporal_mismatch_penalty` field (line 367).

### Current code (lines 366-368):
```python
    recall_temporal_match_weight: float = 0.25       # BF-147→BF-155: bonus for temporal cue match in score_recall()
    recall_temporal_mismatch_penalty: float = 0.15   # BF-155: penalty when query watch differs from episode watch
    recall_context_budget_chars: int = 4000  # ~4K char memory budget
```

### New code:
```python
    recall_temporal_match_weight: float = 0.25       # BF-147→BF-155: bonus for temporal cue match in score_recall()
    recall_temporal_mismatch_penalty: float = 0.15   # BF-155: penalty when query watch differs from episode watch
    # AD-601: TCM Temporal Context Model
    tcm_enabled: bool = True               # Enable TCM context vectors on store/recall
    tcm_dimension: int = 16                # Context vector dimensionality
    tcm_drift_rate: float = 0.95           # rho — higher = slower drift, longer temporal memory
    tcm_weight: float = 0.15              # Weight of TCM similarity in score_recall composite
    tcm_fallback_watch_weight: float = 0.05  # Residual watch_section weight when TCM active (was 0.10 for match, 0.15 for mismatch)
    recall_context_budget_chars: int = 4000  # ~4K char memory budget
```

**Why these defaults:**
- `tcm_weight=0.15` replaces most of the binary temporal bonus (0.25 match / 0.15 penalty) with a smooth gradient. The remaining `tcm_fallback_watch_weight=0.05` keeps a small discrete signal for backward compatibility.
- `tcm_drift_rate=0.95` means ~95% of the previous context is retained per episode. After ~20 episodes, the context has drifted to ~36% of its original value (`0.95^20 ≈ 0.36`), giving a reasonable temporal horizon for agent recall.
- `tcm_dimension=16` is sufficient for temporal identity (not semantic meaning) while keeping serialization compact.

---

## Section 3: Store TCM Context Vector with Episodes

**File:** `src/probos/cognitive/episodic.py` (EDIT)

### Step 3a: Add TCM engine to EpisodicMemory

Add a `_tcm` attribute to `EpisodicMemory.__init__`. Place after `self._participant_index` (line 582):

```python
        self._tcm: Any = None  # AD-601: Temporal Context Model engine
```

Add a setter method after `set_participant_index` (line 590):

```python
    def set_tcm(self, tcm: Any) -> None:
        """AD-601: Wire the Temporal Context Model after construction."""
        self._tcm = tcm
```

### Step 3b: Update context vector on store

In the `store()` method, after the importance scoring block (after line 844: `episode = Episode(...)`) and before `metadata = self._episode_to_metadata(episode)` (line 846), add TCM context vector capture:

```python
        # AD-601: Capture TCM context vector snapshot at encoding time
        _tcm_vector: list[float] | None = None
        if self._tcm is not None:
            try:
                _tcm_vector = self._tcm.update(
                    episode.user_input or "",
                    timestamp=episode.timestamp,
                )
            except Exception:
                logger.debug("AD-601: TCM update failed", exc_info=True)
```

### Step 3c: Store TCM vector in metadata

In `_episode_to_metadata()` (static method at line 1440), add the TCM vector serialization. Place after the `"importance"` field (line 1478):

**This requires passing the TCM vector into `_episode_to_metadata`.** Since it is a `@staticmethod`, the TCM vector cannot be read from `self`. Two options:

**Option A (chosen): Store TCM vector via a transient Episode attribute.**

The `Episode` dataclass is frozen, so we cannot set an attribute on it. Instead, pass the TCM vector separately. Change `_episode_to_metadata` from a `@staticmethod` to accept an optional `tcm_vector` parameter:

In `_episode_to_metadata` signature, change:
```python
    @staticmethod
    def _episode_to_metadata(ep: Episode) -> dict:
```
to:
```python
    @staticmethod
    def _episode_to_metadata(ep: Episode, *, tcm_vector: list[float] | None = None) -> dict:
```

At the end of the metadata dict construction, before the `return metadata` (line 1493), add:

```python
        # AD-601: TCM temporal context vector
        if tcm_vector is not None:
            from probos.cognitive.temporal_context import serialize_tcm_vector
            metadata["tcm_vector_json"] = serialize_tcm_vector(tcm_vector)
        else:
            metadata["tcm_vector_json"] = ""
```

### Step 3d: Update store() call to pass TCM vector

In `store()`, update the `metadata = self._episode_to_metadata(episode)` call (line 846) to:

```python
        metadata = self._episode_to_metadata(episode, tcm_vector=_tcm_vector)
```

### Step 3e: Update all other callers of `_episode_to_metadata`

Search for all callers of `_episode_to_metadata` in the codebase. The new `tcm_vector` parameter is keyword-only with a default of `None`, so existing callers that don't pass it will continue to work — they just won't store a TCM vector. This is correct: `_force_update()`, `seed()`, and migration code should preserve existing metadata rather than generating new TCM vectors.

**Builder verification:** Grep for `_episode_to_metadata(` across all files. Verify each caller either:
1. Already passes no `tcm_vector` (correct — uses default `None`)
2. Is `store()`, which now passes `_tcm_vector`

### Step 3f: Deserialize TCM vector on recall

In `_metadata_to_episode()` (line 1572), the TCM vector is stored in metadata, not in the Episode dataclass. No change needed to `_metadata_to_episode` itself — the vector is accessed directly from metadata in `score_recall()` (Section 4).

However, for the `recall_weighted()` method to access TCM vectors, each candidate's metadata must be preserved alongside the episode. Currently, `recall_for_agent_scored()` returns `list[tuple[Episode, float]]` — no metadata. Rather than changing that return type (which would break callers), the TCM similarity will be computed in `recall_weighted()` by reading the TCM vector from the episode's metadata at the point where the episode is fetched from ChromaDB.

**The approach:** In `recall_weighted()`, after building `ep_map`, also build a parallel `meta_map` that carries each episode's raw metadata dict. Then pass the TCM vector to `score_recall()`.

---

## Section 4: TCM-Aware Recall Scoring

**File:** `src/probos/cognitive/episodic.py` (EDIT)

### Step 4a: Add TCM similarity parameter to `score_recall()`

In `score_recall()` (line 1694), add a new parameter after `importance_weight`:

```python
        tcm_similarity: float = 0.0,       # AD-601: TCM temporal context similarity (0.0–1.0)
        tcm_weight: float = 0.0,           # AD-601: weight in composite (0.0 = disabled)
        tcm_fallback_watch_weight: float = 0.05,  # AD-601: residual watch_section weight when TCM active
```

### Step 4b: Add TCM contribution to composite score

In the composite score computation (after the convergence bonus block, around line 1747), **replace** the existing BF-147/BF-155 temporal match/mismatch block with TCM-aware logic:

**Current code (lines 1749-1762):**
```python
        # BF-147: temporal match bonus — query temporal cue matches episode anchor
        if temporal_match:
            composite += max(0.0, temporal_match_weight)
        # BF-155: temporal mismatch suppression — penalize episodes from wrong watch
        # when query has explicit temporal intent. Only penalize when the episode
        # HAS a watch_section that DIFFERS from the query — don't penalize episodes
        # with no temporal context.
        elif query_has_temporal_intent and not temporal_match:
            _ep_watch = (
                getattr(episode, "anchors", None)
                and getattr(episode.anchors, "watch_section", "")
            )
            if _ep_watch:
                composite -= min(temporal_mismatch_penalty, composite)  # clamp: don't go below 0
```

**New code:**
```python
        # AD-601: TCM temporal context gradient (replaces binary watch_section matching)
        if tcm_weight > 0.0 and tcm_similarity > 0.0:
            # TCM provides smooth temporal proximity — primary temporal signal
            composite += tcm_weight * tcm_similarity
            # Residual watch_section match — small discrete bonus on top of TCM
            if temporal_match:
                composite += max(0.0, tcm_fallback_watch_weight)
        else:
            # Fallback: no TCM vector available (legacy episodes) — use original BF-147/BF-155 logic
            if temporal_match:
                composite += max(0.0, temporal_match_weight)
            elif query_has_temporal_intent and not temporal_match:
                _ep_watch = (
                    getattr(episode, "anchors", None)
                    and getattr(episode.anchors, "watch_section", "")
                )
                if _ep_watch:
                    composite -= min(temporal_mismatch_penalty, composite)
```

**Why this design:**
- Episodes WITH TCM vectors get the smooth gradient (`tcm_weight * tcm_similarity`) plus a small residual watch_section match bonus (`tcm_fallback_watch_weight`). No mismatch penalty — the TCM gradient already demotes distant episodes smoothly.
- Episodes WITHOUT TCM vectors (pre-AD-601) fall back to the existing BF-147/BF-155 binary logic. No behavioral change for legacy episodes.

### Step 4c: Add TCM similarity to RecallScore

**File:** `src/probos/types.py` (EDIT)

Add a `tcm_similarity` field to `RecallScore` (after `anchor_confidence`, line 401):

```python
    tcm_similarity: float = 0.0        # AD-601: TCM temporal context similarity (0.0–1.0)
```

### Step 4d: Pass TCM similarity in RecallScore construction

In `score_recall()`, update the `return RecallScore(...)` (line 1764) to include:

```python
            tcm_similarity=tcm_similarity,
```

---

## Section 5: Wire TCM into `recall_weighted()`

**File:** `src/probos/cognitive/episodic.py` (EDIT)

### Step 5a: Preserve metadata alongside episodes

In `recall_weighted()`, the `ep_map` currently stores `dict[str, tuple[Episode, float]]`. We need to also carry metadata for TCM vector access. Change the map and population logic.

After line 1809 (`ep_map: dict[str, tuple[Episode, float]] = {`), change:

**Current code (lines 1809-1811):**
```python
        ep_map: dict[str, tuple[Episode, float]] = {
            ep.id: (ep, sim) for ep, sim in scored_eps
        }
```

**New code:**
```python
        ep_map: dict[str, tuple[Episode, float]] = {
            ep.id: (ep, sim) for ep, sim in scored_eps
        }
        # AD-601: Parallel metadata map for TCM vector access.
        # recall_for_agent_scored doesn't return metadata, so we fetch it lazily
        # in the scoring loop below (only for episodes that need TCM scoring).
        _meta_cache: dict[str, dict] = {}
```

### Step 5b: Compute TCM similarity in the scoring loop

In the scoring loop (line 1841: `for ep_id, (ep, sim) in ep_map.items():`), after the existing `kw_hits` computation (line 1864) and temporal_match computation (line 1865-1869), add TCM similarity:

```python
            # AD-601: TCM temporal context similarity
            _tcm_sim = 0.0
            _tcm_wt = 0.0
            _tcm_fallback_watch_wt = 0.05
            if self._tcm is not None:
                # Read config
                _tcm_wt = getattr(self, '_tcm_weight', 0.15)
                _tcm_fallback_watch_wt = getattr(self, '_tcm_fallback_watch_weight', 0.05)
                # Get stored TCM vector from metadata
                if ep_id not in _meta_cache:
                    try:
                        _meta_result = self._collection.get(ids=[ep_id], include=["metadatas"])
                        if _meta_result and _meta_result["ids"] and _meta_result["metadatas"]:
                            _meta_cache[ep_id] = _meta_result["metadatas"][0]
                    except Exception:
                        pass
                _ep_meta = _meta_cache.get(ep_id, {})
                _tcm_raw = _ep_meta.get("tcm_vector_json", "")
                if _tcm_raw:
                    from probos.cognitive.temporal_context import deserialize_tcm_vector
                    _stored_vec = deserialize_tcm_vector(_tcm_raw)
                    if _stored_vec:
                        _tcm_sim = self._tcm.compute_similarity(_stored_vec)
```

Then update the `self.score_recall(...)` call to pass TCM parameters:

In the existing `score_recall()` call (lines 1871-1886), add after `importance_weight=0.05`:

```python
                tcm_similarity=_tcm_sim,
                tcm_weight=_tcm_wt,
                tcm_fallback_watch_weight=_tcm_fallback_watch_wt,
```

### Step 5c: Expose TCM config on EpisodicMemory

Add config attributes to `__init__` (after `self._tcm`, from Step 3a):

```python
        self._tcm_weight: float = 0.15            # AD-601: from TCMConfig/MemoryConfig
        self._tcm_fallback_watch_weight: float = 0.05  # AD-601: residual watch_section weight
```

Add a configuration method after `set_tcm`:

```python
    def configure_tcm(self, weight: float, fallback_watch_weight: float) -> None:
        """AD-601: Set TCM scoring weights from config."""
        self._tcm_weight = weight
        self._tcm_fallback_watch_weight = fallback_watch_weight
```

---

## Section 6: Startup Wiring

**No new startup module changes required.** The TCM engine is wired into EpisodicMemory via `set_tcm()`, following the same late-binding pattern as `set_activation_tracker()` and `set_participant_index()`.

**Builder must find the startup code that calls `set_activation_tracker()` and add TCM wiring after it.** 

Grep for `set_activation_tracker` to find the exact startup file and location. Add:

```python
    # AD-601: Wire Temporal Context Model
    if getattr(config, 'memory', None) and config.memory.tcm_enabled:
        from probos.cognitive.temporal_context import TemporalContextModel, TCMConfig
        _tcm_config = TCMConfig(
            dimension=config.memory.tcm_dimension,
            drift_rate=config.memory.tcm_drift_rate,
            tcm_weight=config.memory.tcm_weight,
            fallback_watch_weight=config.memory.tcm_fallback_watch_weight,
        )
        _tcm = TemporalContextModel(config=_tcm_config)
        episodic_memory.set_tcm(_tcm)
        episodic_memory.configure_tcm(
            weight=config.memory.tcm_weight,
            fallback_watch_weight=config.memory.tcm_fallback_watch_weight,
        )
        logger.info("AD-601: TCM wired (d=%d, rho=%.3f, w=%.2f)",
                     config.memory.tcm_dimension, config.memory.tcm_drift_rate,
                     config.memory.tcm_weight)
```

**Builder verification:** Grep for `set_activation_tracker` and `set_participant_index` across `src/probos/startup/` to find the exact module. Add the TCM wiring in the same function, immediately after the activation tracker wiring.

---

## Section 7: Tests

**File:** `tests/test_ad601_tcm_temporal_context.py` (NEW)

### Test categories (20 tests):

**TemporalContextModel engine (8 tests):**

1. `test_tcm_init_zeros` — New TCM has zero context vector, `initialized=False`.
2. `test_tcm_first_update_sets_context` — First `update()` sets context directly (no zero-decay), returns normalized vector.
3. `test_tcm_drift_rate_controls_decay` — Two updates with `rho=0.95`: second context is `0.95 * first_context + 0.05 * second_signal`, normalized. Verify intermediate value is between the two signals.
4. `test_tcm_similarity_nearby_episodes` — Store episode A's context. Update with episode B immediately after. Compute similarity between current context and A's stored context. Should be high (> 0.8).
5. `test_tcm_similarity_decays_over_many_episodes` — Store episode A's context. Update 20 times with different episodes. Similarity between current context and A's stored context should be low (< 0.5).
6. `test_tcm_similarity_gradient` — Store context at episodes 0, 5, 10, 15, 20. Compute similarity of each to context at episode 20. Verify monotonically decreasing: sim(20,20) > sim(15,20) > sim(10,20) > sim(5,20) > sim(0,20).
7. `test_tcm_set_context_vector` — `set_context_vector()` restores state. Subsequent `compute_similarity()` uses restored vector.
8. `test_tcm_dimension_mismatch` — `set_context_vector()` with wrong dimension raises `ValueError`. `compute_similarity()` with wrong dimension returns 0.0.

**Serialization (3 tests):**

9. `test_serialize_deserialize_roundtrip` — `deserialize_tcm_vector(serialize_tcm_vector(vec))` returns original values within floating-point tolerance.
10. `test_deserialize_empty_string` — Returns `None`.
11. `test_deserialize_malformed` — Returns `None` for `"not json"`, `"[1, 'foo']"`, `"42"`.

**Integration with EpisodicMemory (5 tests):**

12. `test_store_captures_tcm_vector` — Store an episode with TCM wired. Verify `tcm_vector_json` metadata is non-empty and deserializes to a list of correct dimension.
13. `test_store_without_tcm_no_vector` — Store without TCM wired. Verify `tcm_vector_json` metadata is empty string.
14. `test_score_recall_tcm_smooth_gradient` — Call `score_recall()` with `tcm_similarity=0.9, tcm_weight=0.15` vs `tcm_similarity=0.3, tcm_weight=0.15`. Verify the first produces a higher composite score. Verify the difference equals approximately `0.15 * (0.9 - 0.3) = 0.09`.
15. `test_score_recall_tcm_fallback_for_legacy` — Call `score_recall()` with `tcm_similarity=0.0, tcm_weight=0.15` (no TCM vector). Verify it falls back to BF-147 binary `temporal_match` logic. A `temporal_match=True` episode should get the full `temporal_match_weight` bonus.
16. `test_score_recall_tcm_no_mismatch_penalty` — When TCM is active (`tcm_similarity > 0`), verify no mismatch penalty is applied even when `query_has_temporal_intent=True` and `temporal_match=False`. The TCM gradient already demotes distant episodes.

**RecallScore dataclass (1 test):**

17. `test_recall_score_has_tcm_similarity_field` — `RecallScore` has `tcm_similarity` field defaulting to 0.0.

**Config (3 tests):**

18. `test_memory_config_tcm_defaults` — `MemoryConfig()` has `tcm_enabled=True`, `tcm_dimension=16`, `tcm_drift_rate=0.95`, `tcm_weight=0.15`.
19. `test_tcm_config_dataclass` — `TCMConfig()` defaults match `MemoryConfig` defaults.
20. `test_tcm_disabled_skips_wiring` — When `tcm_enabled=False`, verify `set_tcm()` is not called (mock the startup wiring path).

---

## Engineering Principles Compliance

- **SOLID/S** — `TemporalContextModel` owns only TCM state and math. `EpisodicMemory` delegates to it. `score_recall()` is the only compositor.
- **SOLID/O** — TCM is additive: new module, new metadata field, new `score_recall` parameter. No existing behavior changes when TCM is disabled (default `tcm_weight=0.0` in `score_recall` parameters).
- **SOLID/D** — `EpisodicMemory` depends on `_tcm: Any` via setter injection, not direct construction. Config flows from `MemoryConfig` → `TCMConfig` → `TemporalContextModel`.
- **Law of Demeter** — `recall_weighted` calls `self._tcm.compute_similarity()` (one level). No reaching through TCM internals.
- **Fail Fast** — `set_context_vector()` raises on dimension mismatch. `compute_similarity()` returns 0.0 on bad input (graceful degradation for recall — don't crash the whole pipeline). TCM update failures are caught and logged.
- **DRY** — Vector math (`_cosine_similarity`, `_normalize`) is defined once in `temporal_context.py`. Serialization/deserialization is a single pair of functions.
- **Defense in Depth** — Legacy episodes without TCM vectors fall back to BF-147/BF-155 binary logic. TCM can be disabled via config. Dimension mismatches are caught at both storage and recall boundaries.
- **Cloud-Ready Storage** — TCM vectors stored as JSON strings in ChromaDB metadata (portable). No new database connections.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   AD-601 COMPLETE. TCM Temporal Context Vectors — Howard & Kahana (2002) Temporal Context Model for episodic memory. Drifting context vector (d=16, rho=0.95) stored alongside each episode. Cosine similarity between current and stored context provides smooth temporal proximity gradient, replacing binary watch_section matching for new episodes. Legacy episodes fall back to BF-147/BF-155 logic. Pure Python, no numpy/scipy. 20 tests.
   ```

2. **docs/development/roadmap.md** — Update the AD-601 row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ### AD-601 — TCM Temporal Context Vectors (2026-04-26)
   **Context:** Temporal context was encoded as discrete watch_section labels (7 naval watches), producing binary match/mismatch scoring with no proximity gradient. Two episodes 5 minutes apart scored identically to two episodes 3 hours apart within the same watch.
   **Decision:** Implemented Howard & Kahana (2002) Temporal Context Model. A d=16 context vector drifts via exponential decay (rho=0.95) on each episode encoding. Cosine similarity between current and stored context vectors provides smooth temporal proximity in score_recall(). Legacy episodes (no TCM vector) fall back to BF-147/BF-155 binary watch_section logic. Hash-based projection (not embedding truncation) generates deterministic episode fingerprints. TCM weight=0.15 in composite score replaces most of the 0.25 match / 0.15 penalty binary temporal signal, with residual 0.05 watch_section match for backward compatibility. No migration of existing episodes — gradual adoption as new episodes are stored.
   **Consequences:** Temporal recall quality improves for agents with 10+ episodes. Watch boundaries no longer create artificial discontinuities. Config-driven: tcm_enabled, tcm_dimension, tcm_drift_rate, tcm_weight, tcm_fallback_watch_weight all tunable in MemoryConfig.
   ```
