# AD-493: Novelty Gate — Semantic Observation Dedup

**Issue:** AD-493
**Status:** Ready for builder
**Priority:** Medium
**Depends:** BF-032 (Jaccard similarity — complete), AD-584 (QA-trained embeddings — complete), AD-632e (Evaluate sub-task — complete)
**Files:** `src/probos/cognitive/novelty_gate.py` (NEW), `src/probos/proactive.py` (EDIT — wire gate into `_think_for_agent`), `src/probos/ward_room_pipeline.py` (EDIT — wire gate into `process_and_post`), `src/probos/config.py` (EDIT — add `NoveltyGateConfig`), `src/probos/startup/finalize.py` (EDIT — instantiate gate after proactive loop), `src/probos/runtime.py` (EDIT — pass gate to WardRoomPostPipeline), `tests/test_ad493_novelty_gate.py` (NEW)

## Problem

Agents post repetitive observations about the same topics. The existing dedup guards are surface-level text matching that can be defeated by rephrasing:

1. **BF-032 `_is_similar_to_recent_posts()`** (proactive.py:1873) — Jaccard similarity on raw word sets + bigram overlap + containment check. Threshold 0.5. Only catches near-identical wording. An agent can say "trust scores are stable" and "the trust landscape shows no changes" and both pass.

2. **BF-197 similarity guard** (ward_room_pipeline.py:110) — Same `_is_similar_to_recent_posts()` called from the post pipeline. Same Jaccard limitation.

3. **AD-632e Evaluate sub-task** (evaluate.py) — LLM-based quality scoring with a "Novelty" criterion. But this compares the draft against the *current thread* only, not the agent's *historical observation corpus*. An agent can post the same observation to different threads and pass every time.

4. **AD-550 notebook dedup** (proactive.py:2084) — Notebook-specific dedup with `check_notebook_similarity()`. Only applies to notebook writes, not Ward Room posts.

None of these track *what topics an agent has already covered* across their full posting history. AD-493 fills this gap with semantic novelty detection that uses the existing embedding infrastructure (ChromaDB + `multi-qa-MiniLM-L6-cos-v1` from AD-584).

**What this does NOT replace:**
- BF-032's Jaccard check stays — it's a fast, zero-cost first gate that catches verbatim/near-verbatim duplicates
- AD-632e's Evaluate novelty criterion stays — it catches thread-level redundancy
- AD-493 adds a *third layer*: semantic topic-level novelty across the agent's full posting history

**Architectural principle:** The novelty gate is a **stateful filter**, not a controller. It maintains a per-agent observation fingerprint log, computes semantic similarity against it, and returns a pass/block verdict. It does not modify the observation text, the cognitive chain, or the posting pipeline. Pure gate — yes/no with a reason.

**What this does NOT include:**
- Cross-agent novelty (suppressing agent B because agent A already said it) — future, requires fleet-wide topic index
- Topic taxonomy or classification — we use raw embeddings, not category labels
- LLM-based novelty judgment — too expensive for a gate that runs on every post
- Modifying the cognitive chain to inject novelty awareness — future (AD-493b)

---

## Section 1: NoveltyGateConfig

**File:** `src/probos/config.py` (EDIT)

Add a new config dataclass. Place it after `EmergentDetectorConfig` (line ~737 area, after the `FirewallConfig` block).

```python
class NoveltyGateConfig(BaseModel):
    """AD-493: Semantic novelty gate — suppress rehashed observations."""
    enabled: bool = True
    # Cosine similarity threshold — observations above this vs any recent
    # fingerprint are considered "not novel" and suppressed.
    # MiniLM cosine: 0.85+ = near-paraphrase, 0.70-0.85 = same topic/different angle,
    # 0.50-0.70 = related topic, <0.50 = different topic.
    similarity_threshold: float = 0.82
    # How many recent observation fingerprints to retain per agent.
    max_fingerprints_per_agent: int = 50
    # Decay: fingerprints older than this (hours) are evicted, making
    # the topic "novel again." 0 = no decay (fingerprints persist until
    # max_fingerprints_per_agent pushes them out).
    decay_hours: float = 24.0
    # Minimum text length to gate. Very short responses (acknowledgments,
    # social replies) skip the novelty check.
    min_text_length: int = 80
```

Add `novelty_gate` field to `SystemConfig` (line ~1061). Find the existing fields `firewall` and `emergent_detector` (lines ~1082-1083) and add alongside them:

```python
    novelty_gate: NoveltyGateConfig = NoveltyGateConfig()
```

---

## Section 2: NoveltyGate — Core Engine

**File:** `src/probos/cognitive/novelty_gate.py` (NEW)

```python
"""AD-493: Semantic novelty gate — suppress rehashed agent observations.

Maintains per-agent observation fingerprints (embedding vectors) and
checks new observations against them using cosine similarity. Operates
on the existing ChromaDB embedding infrastructure (multi-qa-MiniLM-L6-cos-v1).

Three-layer dedup stack:
  Layer 1: BF-032 Jaccard (fast, word-level, catches verbatim copies)
  Layer 2: AD-493 NoveltyGate (semantic, topic-level, catches rephrased rehash) ← THIS
  Layer 3: AD-632e Evaluate (LLM, thread-level, catches in-thread redundancy)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ObservationFingerprint:
    """A single observation's semantic fingerprint."""
    embedding: list[float]        # Dense vector from embedding model
    text_preview: str             # First 100 chars for debugging
    timestamp: float              # time.time() when recorded
    agent_id: str


@dataclass
class NoveltyVerdict:
    """Result of a novelty check."""
    is_novel: bool
    similarity: float             # Highest cosine similarity to any fingerprint
    reason: str                   # Human-readable reason
    matched_preview: str = ""     # Preview of the matched fingerprint (if not novel)


class NoveltyGate:
    """Semantic novelty gate for agent observations.

    Maintains a ring buffer of per-agent observation fingerprints
    (embedding vectors). On each check, computes cosine similarity
    between the candidate text and all stored fingerprints for that
    agent. If any fingerprint exceeds the similarity threshold, the
    observation is flagged as "not novel."

    Uses the shared embedding infrastructure from
    ``probos.knowledge.embeddings`` (ChromaDB ONNX MiniLM).
    Falls back to keyword-overlap embeddings when semantic embeddings
    are unavailable — same graceful degradation as EpisodicMemory.

    When ChromaDB embeddings are unavailable, ``embed_text()`` falls back
    to keyword embeddings. The similarity threshold (0.82) is calibrated
    for MiniLM cosine; in keyword-fallback mode, behavior approximates
    a stricter Jaccard. This is acceptable degradation — the gate
    collapses to roughly the same behavior as BF-032 in fallback mode.

    Thread-safe for single-event-loop asyncio (no locks needed —
    all mutations happen in the same coroutine context).

    Consider ``asyncio.to_thread(embed_text, text)`` if profiling shows
    event loop stalls from ONNX inference under high agent counts.

    Parameters
    ----------
    similarity_threshold : float
        Cosine similarity above which an observation is "not novel."
    max_fingerprints_per_agent : int
        Ring buffer size per agent. Oldest fingerprints are evicted
        when the buffer is full.
    decay_hours : float
        Fingerprints older than this are evicted on access.
        0 = no time-based decay.
    min_text_length : int
        Texts shorter than this skip the novelty check (always novel).
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.82,
        max_fingerprints_per_agent: int = 50,
        decay_hours: float = 24.0,
        min_text_length: int = 80,
    ) -> None:
        self._threshold = similarity_threshold
        self._max_per_agent = max_fingerprints_per_agent
        self._decay_seconds = decay_hours * 3600.0
        self._min_length = min_text_length
        # Per-agent ring buffer: agent_id -> list[ObservationFingerprint]
        self._fingerprints: dict[str, list[ObservationFingerprint]] = {}
        # Stats
        self._checks: int = 0
        self._blocks: int = 0
        self._bypasses: int = 0

    @classmethod
    def from_config(cls, config: Any) -> "NoveltyGate":
        """Create from NoveltyGateConfig."""
        return cls(
            similarity_threshold=getattr(config, 'similarity_threshold', 0.82),
            max_fingerprints_per_agent=getattr(config, 'max_fingerprints_per_agent', 50),
            decay_hours=getattr(config, 'decay_hours', 24.0),
            min_text_length=getattr(config, 'min_text_length', 80),
        )

    def check(self, agent_id: str, text: str) -> NoveltyVerdict:
        """Check whether an observation is novel for this agent.

        Returns a NoveltyVerdict. Does NOT record the fingerprint —
        call ``record()`` after the observation is actually posted
        (to avoid recording suppressed observations).

        This is a synchronous method — embedding computation is CPU-bound
        and runs in the event loop (same as EpisodicMemory's ChromaDB calls).
        """
        self._checks += 1

        # Short text bypass
        if len(text.strip()) < self._min_length:
            self._bypasses += 1
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="below_min_length",
            )

        # Compute embedding
        try:
            from probos.knowledge.embeddings import embed_text
            candidate_embedding = embed_text(text)
        except Exception:
            logger.debug("AD-493: Embedding failed, passing as novel", exc_info=True)
            self._bypasses += 1
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="embedding_failed",
            )

        if not candidate_embedding:
            self._bypasses += 1
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="empty_embedding",
            )

        # Evict stale fingerprints
        self._evict_stale(agent_id)

        # Compare against stored fingerprints
        agent_fps = self._fingerprints.get(agent_id, [])
        if not agent_fps:
            return NoveltyVerdict(
                is_novel=True,
                similarity=0.0,
                reason="no_prior_observations",
            )

        max_sim = 0.0
        matched_preview = ""
        for fp in agent_fps:
            sim = self._cosine_similarity(candidate_embedding, fp.embedding)
            if sim > max_sim:
                max_sim = sim
                matched_preview = fp.text_preview

        if max_sim >= self._threshold:
            self._blocks += 1
            return NoveltyVerdict(
                is_novel=False,
                similarity=round(max_sim, 3),
                reason="semantic_duplicate",
                matched_preview=matched_preview,
            )

        return NoveltyVerdict(
            is_novel=True,
            similarity=round(max_sim, 3),
            reason="novel",
        )

    def record(self, agent_id: str, text: str) -> None:
        """Record an observation fingerprint after successful posting.

        Call this AFTER the observation passes the gate and is posted.
        Do NOT call for suppressed observations.
        """
        if len(text.strip()) < self._min_length:
            return  # Don't fingerprint very short texts

        try:
            from probos.knowledge.embeddings import embed_text
            embedding = embed_text(text)
        except Exception:
            logger.debug("AD-493: Recording embedding failed", exc_info=True)
            return

        if not embedding:
            return

        fp = ObservationFingerprint(
            embedding=embedding,
            text_preview=text[:100],
            timestamp=time.time(),
            agent_id=agent_id,
        )

        if agent_id not in self._fingerprints:
            self._fingerprints[agent_id] = []

        fps = self._fingerprints[agent_id]
        fps.append(fp)

        # Ring buffer eviction
        if len(fps) > self._max_per_agent:
            self._fingerprints[agent_id] = fps[-self._max_per_agent:]

    def _evict_stale(self, agent_id: str) -> None:
        """Remove fingerprints older than decay_seconds for this agent."""
        if self._decay_seconds <= 0:
            return  # No time-based decay
        fps = self._fingerprints.get(agent_id)
        if not fps:
            return
        cutoff = time.time() - self._decay_seconds
        self._fingerprints[agent_id] = [
            fp for fp in fps if fp.timestamp > cutoff
        ]

    def clear_agent(self, agent_id: str) -> None:
        """Clear all fingerprints for an agent (e.g., on reset)."""
        self._fingerprints.pop(agent_id, None)

    def clear_all(self) -> None:
        """Clear all fingerprints (e.g., on system reset)."""
        self._fingerprints.clear()
        self._checks = 0
        self._blocks = 0
        self._bypasses = 0

    def get_stats(self) -> dict[str, Any]:
        """Return diagnostic stats."""
        total_fps = sum(len(fps) for fps in self._fingerprints.values())
        return {
            "checks": self._checks,
            "blocks": self._blocks,
            "bypasses": self._bypasses,
            "agents_tracked": len(self._fingerprints),
            "total_fingerprints": total_fps,
            "threshold": self._threshold,
            "decay_hours": self._decay_seconds / 3600.0 if self._decay_seconds > 0 else 0,
        }

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine similarity between two dense vectors.

        Duplicates embeddings._cosine_similarity to avoid import coupling
        for a 4-line function. Both implementations are identical.
        """
        if len(vec_a) != len(vec_b) or not vec_a:
            return 0.0
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = 0.0
        mag_b = 0.0
        for a, b in zip(vec_a, vec_b):
            mag_a += a * a
            mag_b += b * b
        mag_a = mag_a ** 0.5
        mag_b = mag_b ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (mag_a * mag_b)))
```

**Design notes:**

- **Why not use ChromaDB collection directly?** ChromaDB collections are designed for search (query top-K), not for "is anything above threshold?" checks. We'd need a collection per agent, or complex metadata filtering. A simple in-memory ring buffer of embeddings is cheaper, faster, and has no persistence overhead. Fingerprints are ephemeral — they reset on restart, which is fine (the decay_hours window is short enough that a restart effectively provides a clean slate).

- **Why cosine similarity duplicated?** The function in `embeddings.py` is `_cosine_similarity` (private). Rather than making it public and adding an import dependency for a 4-line function, we inline it. DRY exception: the cost of the coupling exceeds the cost of the duplication.

- **Why synchronous `check()`?** `embed_text()` is synchronous (ONNX inference is CPU-bound, same as EpisodicMemory). No async needed. The proactive loop and post pipeline can call it directly.

---

## Section 3: Wire into Proactive Loop

**File:** `src/probos/proactive.py` (EDIT)

### 3a: Add NoveltyGate attribute to ProactiveCognitiveLoop.__init__

Find the `__init__` method of `ProactiveCognitiveLoop` (line ~161). Add after the existing `_orientation_service` attribute (line ~191):

```python
        self._novelty_gate: "NoveltyGate | None" = None  # AD-493: Set via set_novelty_gate()
```

Add to the existing `TYPE_CHECKING` imports block at the top of the file (if one exists, otherwise add):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.novelty_gate import NoveltyGate
```

### 3b: Add setter

Add after the existing `set_orientation_service` method (line ~193):

```python
    def set_novelty_gate(self, gate: "NoveltyGate") -> None:
        """AD-493: Set novelty gate (public setter for LoD)."""
        self._novelty_gate = gate
```

### 3c: Wire into _think_for_agent

Find the BF-032 similarity check in `_think_for_agent` (line ~671-680):

```python
        # BF-032: Skip if too similar to agent's recent posts
        if await self._is_similar_to_recent_posts(agent, response_text):
            logger.debug(
                "BF-032: Suppressed similar proactive post from %s",
                agent.agent_type,
            )
            # Still record duty execution if applicable
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return
```

Add the AD-493 novelty gate check **immediately after** the BF-032 block (after the `return` on line ~680). The novelty gate runs second because it's more expensive (embedding computation):

```python
        # AD-493: Semantic novelty gate — suppress rehashed observations
        if self._novelty_gate:
            try:
                verdict = self._novelty_gate.check(agent.id, response_text)
                if not verdict.is_novel:
                    logger.info(
                        "AD-493: Suppressed rehashed observation from %s (sim=%.3f, matched='%s')",
                        agent.agent_type, verdict.similarity, verdict.matched_preview[:60],
                    )
                    if duty and self._duty_tracker:
                        self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
                    return
            except Exception:
                logger.debug("AD-493: Novelty gate check failed, allowing post", exc_info=True)
```

### 3d: Record fingerprint after successful posting

Find `_post_to_ward_room` method (line ~1945). The method ends around line 1998 with the BF-198 response tracking block:

```python
        # BF-198: Record own thread so router won't double-respond on event fan-out
        if rt.ward_room_router and _obs_thread is not None:
            _obs_tid = getattr(_obs_thread, 'id', '') or ''
            if _obs_tid:
                rt.ward_room_router.record_agent_response(agent.id, _obs_tid)
```

Add the fingerprint recording **immediately after** this block (at the very end of the method):

```python
        # AD-493: Record observation fingerprint after successful posting
        if self._novelty_gate:
            try:
                self._novelty_gate.record(agent.id, text)
            except Exception:
                logger.debug("AD-493: Fingerprint recording failed", exc_info=True)
```

---

## Section 4: Wire into Ward Room Post Pipeline

**File:** `src/probos/ward_room_pipeline.py` (EDIT)

### 4a: Add novelty_gate parameter

Find `WardRoomPostPipeline.__init__` (line ~38). Add `novelty_gate` as an optional parameter:

```python
    def __init__(
        self,
        *,
        ward_room: "WardRoomService",
        ward_room_router: Any,
        proactive_loop: Any | None,
        trust_network: Any | None,
        callsign_registry: Any | None,
        config: Any,
        runtime: Any | None = None,
        novelty_gate: "NoveltyGate | None" = None,  # AD-493
    ) -> None:
```

Add to the existing `TYPE_CHECKING` imports block at the top of the file (if one exists, otherwise add):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.novelty_gate import NoveltyGate
```

Store it:
```python
        self._novelty_gate = novelty_gate
```

### 4b: Add novelty check in process_and_post

Find Step 4 (Similarity guard, BF-197) in `process_and_post` (line ~109-116). Add the AD-493 novelty gate check **immediately after** the BF-197 block:

```python
        # Step 4b: Semantic novelty gate (AD-493)
        if self._novelty_gate and agent:
            try:
                verdict = self._novelty_gate.check(agent.id, response_text)
                if not verdict.is_novel:
                    logger.info(
                        "AD-493: Pipeline suppressed rehashed post from %s (sim=%.3f)",
                        agent.agent_type, verdict.similarity,
                    )
                    return False
            except Exception:
                logger.debug("AD-493: Pipeline novelty check failed, allowing post", exc_info=True)
```

### 4c: Record fingerprint after successful posting

Find Step 7 (Post to Ward Room, line ~133) — the `if budget.spent:` / `else:` block where the Ward Room post is created. The fingerprint must cover **both** posting paths (action extractor already posted vs. `create_post`). Place the recording **after** the if/else block, at the same indentation level as `if budget.spent:`:

```python
        # AD-493: Record observation fingerprint (covers both posting paths)
        if self._novelty_gate and agent:
            try:
                self._novelty_gate.record(agent.id, response_text)
            except Exception:
                logger.debug("AD-493: Pipeline fingerprint recording failed", exc_info=True)
```

**Why outside the if/else:** If the fingerprint is only recorded on the `create_post` path, observations posted via the action extractor (BF-237 `budget.spent` path) bypass fingerprinting. An agent can repeat the same observation through the action extractor freely. Matching AD-492 Section 6a's pattern: instrumentation that covers both posting paths goes after the if/else.

---

## Section 5: Wire in Startup and Runtime

### 5a: Create NoveltyGate in finalize.py

**File:** `src/probos/startup/finalize.py` (EDIT)

The proactive loop is created in `finalize.py` at line ~72 (`ProactiveCognitiveLoop(...)`). The novelty gate must be created and wired AFTER the proactive loop exists.

Find the block where `proactive_loop.set_config(...)` is called (line ~78), and after the orientation service wiring (line ~87: `proactive_loop.set_orientation_service(...)`), add:

```python
        # --- AD-493: Novelty Gate ---
        # Initialize unconditionally so runtime.py:1601 always has the attribute
        # (getattr default is a safety net, but explicit > implicit).
        runtime._novelty_gate = None
        if config.novelty_gate.enabled:
            from probos.cognitive.novelty_gate import NoveltyGate
            _novelty_gate = NoveltyGate.from_config(config.novelty_gate)
            proactive_loop.set_novelty_gate(_novelty_gate)
            runtime._novelty_gate = _novelty_gate
            logger.info("AD-493: NoveltyGate enabled (threshold=%.2f, decay=%.1fh)",
                         config.novelty_gate.similarity_threshold,
                         config.novelty_gate.decay_hours)
```

**Order constraint:** `runtime._novelty_gate` is set here in `finalize.py` (Phase 8). `WardRoomPostPipeline` is constructed in `runtime.py:1601` AFTER `finalize()` returns. The `getattr(self, '_novelty_gate', None)` in `runtime.py:1601` reads the attribute set above. Verified by code reading: `finalize.py` returns before `runtime.py:1601` runs.

**Important:** This must be inside the `if config.proactive_cognitive.enabled:` block (line ~69), because the novelty gate is only useful when the proactive loop is running. The unconditional `runtime._novelty_gate = None` goes BEFORE the `if config.novelty_gate.enabled:` check but still INSIDE the proactive-cognitive block. If `proactive_cognitive` is disabled entirely, the attribute is never set and the `getattr` default in `runtime.py:1601` handles it.

### 5b: Pass novelty_gate to WardRoomPostPipeline

**File:** `src/probos/runtime.py` (EDIT)

`WardRoomPostPipeline` is instantiated in `runtime.py` at line ~1601. Add `novelty_gate` to the constructor call:

Find:
```python
            self.ward_room_post_pipeline = WardRoomPostPipeline(
                ward_room=self.ward_room,
                ward_room_router=self.ward_room_router,
                proactive_loop=self.proactive_loop,
                trust_network=self.trust_network,
                callsign_registry=getattr(self, 'callsign_registry', None),
                config=self.config,
                runtime=self,
            )
```

Replace with:
```python
            self.ward_room_post_pipeline = WardRoomPostPipeline(
                ward_room=self.ward_room,
                ward_room_router=self.ward_room_router,
                proactive_loop=self.proactive_loop,
                trust_network=self.trust_network,
                callsign_registry=getattr(self, 'callsign_registry', None),
                config=self.config,
                runtime=self,
                novelty_gate=getattr(self, '_novelty_gate', None),  # AD-493
            )
```

**Builder note:** `_novelty_gate` is set by `finalize.py` during Phase 8. The `WardRoomPostPipeline` is also created in Phase 8 (after `finalize` returns). Use `getattr` with default `None` for safe access in case the proactive loop is disabled and `_novelty_gate` was never set.

---

## Section 6: Tests

**File:** `tests/test_ad493_novelty_gate.py` (NEW)

### Test infrastructure

Use `unittest.mock.patch` to mock `probos.knowledge.embeddings.embed_text`. Create test embeddings as simple normalized vectors — for cosine similarity testing, use known vectors:

```python
# Helper: create a normalized vector pointing in a given direction
def _make_vec(angle_degrees: float, dims: int = 10) -> list[float]:
    """Create a simple test embedding vector."""
    import math
    # Use first two dimensions for angle, rest are zero
    vec = [0.0] * dims
    vec[0] = math.cos(math.radians(angle_degrees))
    vec[1] = math.sin(math.radians(angle_degrees))
    return vec
```

This gives us control over cosine similarity: `cos(0) = 1.0` (identical), `cos(10) ≈ 0.985` (very similar), `cos(30) ≈ 0.866` (similar), `cos(60) ≈ 0.5` (different), `cos(90) = 0` (orthogonal).

**Time-mocking pattern for decay tests:** Instead of sleeping, mutate the fingerprint timestamp directly:

```python
# Record, then age the fingerprint past decay_hours
gate.record("agent-1", "long enough text " * 10)
gate._fingerprints["agent-1"][0].timestamp -= (25 * 3600)  # 25h ago
verdict = gate.check("agent-1", "long enough text " * 10)
assert verdict.is_novel  # decayed away
```

### Test categories (21 tests):

**Core novelty detection (6 tests):**
1. `test_first_observation_always_novel` — No prior fingerprints → novel
2. `test_identical_observation_blocked` — Same embedding twice → not novel (sim=1.0)
3. `test_similar_observation_above_threshold_blocked` — Embedding with sim > 0.82 → not novel
4. `test_different_observation_below_threshold_passes` — Embedding with sim < 0.82 → novel
5. `test_multiple_fingerprints_checks_all` — Third observation similar to first (not second) → blocked
6. `test_verdict_includes_matched_preview` — Non-novel verdict has `matched_preview` from the matching fingerprint

**Per-agent isolation (2 tests):**
7. `test_different_agents_independent` — Agent A's fingerprint does not block Agent B
8. `test_same_agent_accumulates` — Multiple observations build up agent's fingerprint set

**Decay (3 tests):**
9. `test_old_fingerprints_evicted` — Fingerprint older than decay_hours is evicted, same topic becomes novel again
10. `test_decay_zero_no_eviction` — With `decay_hours=0`, old fingerprints persist
11. `test_recent_fingerprints_survive_eviction` — Only stale fingerprints are evicted, recent ones remain

**Ring buffer (2 tests):**
12. `test_ring_buffer_evicts_oldest` — After max_fingerprints_per_agent, oldest is evicted
13. `test_evicted_topic_becomes_novel_again` — After ring buffer eviction, the evicted topic is novel again

**Bypass conditions (3 tests):**
14. `test_short_text_bypasses_gate` — Text shorter than min_text_length is always novel
15. `test_embedding_failure_passes_as_novel` — If `embed_text` raises, observation passes (fail-open)
16. `test_empty_embedding_passes_as_novel` — If `embed_text` returns empty list, observation passes

**Record/check separation (2 tests):**
17. `test_check_does_not_record` — Calling `check()` alone does not add a fingerprint
18. `test_record_then_similar_check_blocks` — `record()` with text A, then `check()` with semantically similar (but not identical) text B using a near-angle embedding → blocked. Distinct from Test 2: Test 2 uses identical text/embedding, Test 18 uses similar-but-different text with embeddings above threshold.

**Stats and management (2 tests):**
19. `test_get_stats` — Returns correct counts after checks/blocks/bypasses
20. `test_clear_agent` — `clear_agent()` removes fingerprints, same topic becomes novel again

**Pipeline wiring (1 test):**
21. `test_pipeline_records_fingerprint_after_post` — Mock `_ward_room.create_post`, mock `_novelty_gate.record`, run `process_and_post`, assert `record` was called with `(agent.id, response_text)`. Pins the Section 4c wiring.

**Notes for builder:**
- **Stats surfacing deferred to AD-493b.** `get_stats()` is implemented but not wired to any telemetry, health endpoint, or debug command. Accessible via `runtime._novelty_gate.get_stats()` for ad-hoc inspection.
- **Threshold calibration:** 0.82 sits in the "same topic/different angle" range — this blocks an agent posting two different angles on the same topic. That's intentional (rehashed observations are the primary failure mode). Tune downward to 0.85 if false-positive rate is high (legitimate observations blocked). Initial value 0.82 errs toward suppression.
- **Section 3c placement clarity:** Place the AD-493 check after the closing `return` of the BF-032 `if`-block, at the same indentation as the `if await self._is_similar_to_recent_posts(...)` test. Do not place inside the BF-032 block.
- **Section 3d early-return audit:** If `_post_to_ward_room` has any early-return paths between the BF-198 block and end-of-method, those paths skip fingerprinting. This is intentional: only fingerprint successful posts. Builder should verify no early returns exist in that range that represent successful posts.

---

## Engineering Principles Compliance

- **SOLID/S** — NoveltyGate has one job: semantic novelty filtering. It doesn't modify text, doesn't post, doesn't manage the cognitive chain.
- **SOLID/O** — Threshold, decay, buffer size are all configurable. New similarity strategies can be added without modifying existing code.
- **SOLID/D** — Uses `embed_text()` from the shared embedding module (dependency on abstraction, not on ChromaDB directly). Constructor injection via `from_config()`. Wired through public setter `set_novelty_gate()`.
- **Fail Fast** — Embedding failures → fail-open (pass as novel). Gate is non-critical — a missed suppression is better than blocking a legitimate observation. Log-and-degrade on all errors.
- **Law of Demeter** — NoveltyGate accesses only its own state. Callers pass `agent.id` and `text`, not the agent object. No reaching into runtime internals.
- **DRY** — Reuses `probos.knowledge.embeddings.embed_text()` for embedding computation. Cosine similarity is inlined (4 lines) rather than importing a private function — justified exception.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   | AD-493 | Novelty Gate | Semantic observation dedup — per-agent embedding fingerprints with cosine similarity, time decay, ring buffer. Three-layer dedup stack (Jaccard → Semantic → LLM). 21 tests. | CLOSED |
   ```

2. **docs/development/roadmap.md** — Update the AD-493 row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ## AD-493: Novelty Gate — Semantic Observation Dedup

   **Decision:** Per-agent observation fingerprinting using embedding cosine similarity. In-memory ring buffer (50 fingerprints/agent) with 24h time decay. Threshold 0.82 (MiniLM cosine). Three-layer dedup stack: BF-032 Jaccard (fast/word-level) → AD-493 NoveltyGate (semantic/topic-level) → AD-632e Evaluate (LLM/thread-level).

   **Rationale:** Jaccard similarity is defeated by rephrasing. An agent can say "trust is stable" and "the trust landscape is unchanged" with only ~0.3 Jaccard overlap. MiniLM cosine similarity catches semantic equivalence regardless of wording. In-memory ring buffer avoids persistence overhead — fingerprints are ephemeral and reset on restart, which aligns with the 24h decay window. 0.82 threshold is calibrated to block near-paraphrases while allowing genuinely different observations about related topics.

   **Alternative considered:** ChromaDB collection per agent for persistent fingerprints. Rejected — persistence overhead for an ephemeral gate, and ChromaDB's top-K query API doesn't naturally express "is anything above threshold?" without scanning all results. Simple list + cosine is O(N) with N ≤ 50, which is fast enough.
   ```
