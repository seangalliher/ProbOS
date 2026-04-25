# AD-403: Memory Contradiction Resolution — Dream Consolidation Phase

## Context

ProbOS's episodic memory system (ChromaDB) and KnowledgeStore (git-backed JSON) both accept episodes via append/upsert with **zero contradiction detection**. If episode A records "agent_x succeeded at intent_y with high confidence" and episode B records "agent_x failed at intent_y" for equivalent inputs, nothing notices or reconciles this. Over time, contradictory memories accumulate and pollute the `recall()` results that feed every decomposition.

The dream consolidation engine (`dreaming.py`) is the natural home for this — it already replays episodes during idle periods, has access to episodic memory and trust, and produces a `DreamReport`. Adding contradiction detection as a new dream step is architecturally clean.

**Current dream_cycle steps:** micro_dream flush → prune → trust consolidation → pre-warm → idle scale-down → strategy extraction → gap prediction.

**This AD adds:** a new Step 3.5 between trust consolidation and pre-warm — **memory contradiction resolution**.

## Design Principles

1. **No LLM calls.** Phase 1 uses deterministic heuristics, not LLM-as-judge. Fast, predictable, testable.
2. **Non-destructive.** Contradictions are flagged with metadata, not deleted. The `DreamReport` records what was found.
3. **Conservative matching.** Two episodes contradict if they have similar inputs but opposite outcomes for the same intent+agent pair. "Similar" = high cosine similarity on the user_input embeddings.
4. **Recency wins.** When contradictions are detected, the more recent episode is kept as-is; the older one gets a `superseded_by` metadata annotation.
5. **Fits existing patterns.** Same style as `extract_strategies()` and `predict_gaps()` — pure function that takes episodes, returns structured results.

## Part 1: Contradiction Detector

### Create `src/probos/cognitive/contradiction_detector.py`

```python
"""Detect contradictory episodes in episodic memory (AD-403).

Two episodes contradict when they have semantically similar inputs
but opposite outcomes for the same intent+agent pair. Contradictions
indicate stale or outdated memories that should be superseded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from probos.types import Episode

logger = logging.getLogger(__name__)


@dataclass
class Contradiction:
    """A detected contradiction between two episodes."""

    older_episode_id: str
    newer_episode_id: str
    intent: str
    agent_id: str
    older_outcome: str  # "success" or "failure"
    newer_outcome: str  # "success" or "failure"
    similarity: float  # cosine similarity of user_input embeddings
    description: str = ""

    @property
    def id(self) -> str:
        return f"contradiction:{self.older_episode_id}:{self.newer_episode_id}"


def detect_contradictions(
    episodes: list[Episode],
    similarity_threshold: float = 0.85,
) -> list[Contradiction]:
    """Detect contradictory episodes based on outcome disagreement.

    Two episodes contradict when:
    1. Their user_inputs are highly similar (cosine >= similarity_threshold)
    2. They share at least one intent+agent_id pair
    3. The outcomes for that pair disagree (one success, one failure)

    Since we don't have embeddings available in this pure function (ChromaDB
    manages them internally), we use a word-overlap Jaccard similarity as a
    proxy. This avoids coupling to ChromaDB internals.

    Args:
        episodes: Recent episodes to analyze (typically from dream_cycle's
                  episodic_memory.recent() call).
        similarity_threshold: Minimum Jaccard similarity to consider two
                              inputs as "about the same thing". Default 0.85.

    Returns:
        List of detected contradictions, sorted by similarity descending.
    """
    contradictions: list[Contradiction] = []

    # Build per-episode outcome maps: {(intent, agent_id): "success"|"failure"}
    episode_outcomes: list[dict[tuple[str, str], str]] = []
    for ep in episodes:
        outcome_map: dict[tuple[str, str], str] = {}
        for outcome in ep.outcomes:
            intent = outcome.get("intent", "")
            status = outcome.get("status", outcome.get("success", ""))
            if not intent:
                continue
            # Normalize status to "success" or "failure"
            if isinstance(status, bool):
                normalized = "success" if status else "failure"
            elif isinstance(status, str):
                normalized = "success" if status.lower() in ("success", "completed", "true") else "failure"
            else:
                continue

            for agent_id in ep.agent_ids:
                outcome_map[(intent, agent_id)] = normalized
        episode_outcomes.append(outcome_map)

    # Compare all pairs (O(n^2) but n is bounded by replay_episode_count, typically 50)
    for i in range(len(episodes)):
        for j in range(i + 1, len(episodes)):
            ep_a = episodes[i]
            ep_b = episodes[j]

            # Compute word-overlap similarity
            sim = _jaccard_similarity(ep_a.user_input, ep_b.user_input)
            if sim < similarity_threshold:
                continue

            # Find shared intent+agent pairs with disagreeing outcomes
            outcomes_a = episode_outcomes[i]
            outcomes_b = episode_outcomes[j]
            shared_keys = set(outcomes_a.keys()) & set(outcomes_b.keys())

            for key in shared_keys:
                if outcomes_a[key] != outcomes_b[key]:
                    # Determine which is older/newer
                    if ep_a.timestamp <= ep_b.timestamp:
                        older, newer = ep_a, ep_b
                        older_out, newer_out = outcomes_a[key], outcomes_b[key]
                    else:
                        older, newer = ep_b, ep_a
                        older_out, newer_out = outcomes_b[key], outcomes_a[key]

                    contradictions.append(Contradiction(
                        older_episode_id=older.id,
                        newer_episode_id=newer.id,
                        intent=key[0],
                        agent_id=key[1],
                        older_outcome=older_out,
                        newer_outcome=newer_out,
                        similarity=sim,
                        description=(
                            f"Episodes disagree on {key[0]}+{key[1]}: "
                            f"older={older_out}, newer={newer_out} "
                            f"(input similarity={sim:.2f})"
                        ),
                    ))

    # Sort by similarity descending (most confident contradictions first)
    contradictions.sort(key=lambda c: c.similarity, reverse=True)
    return contradictions


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two texts.

    Returns a value in [0.0, 1.0]. Used as a proxy for semantic similarity
    when embeddings aren't available outside ChromaDB.
    """
    if not text_a or not text_b:
        return 0.0
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
```

**Implementation notes:**
- The Jaccard similarity threshold of 0.85 is deliberately high — we only flag near-identical inputs, not vaguely similar ones. Better to miss edge cases than to flag false contradictions.
- The O(n^2) comparison loop is fine because `replay_episode_count` (from `DreamingConfig`) is typically 50. Even at 100, that's only 4,950 comparisons of trivial operations.
- We don't use ChromaDB's embedding similarity here because the detector is a pure function that takes episodes, matching the pattern of `extract_strategies()` and `predict_gaps()`.

## Part 2: Integrate into Dream Cycle

### Modify `src/probos/cognitive/dreaming.py`

**2a.** Add the import at the top with the other cognitive imports:

```python
from probos.cognitive.contradiction_detector import detect_contradictions
```

**2b.** Add a new `contradiction_resolve_fn` callback parameter to `__init__()`, following the pattern of `strategy_store_fn` and `gap_prediction_fn`:

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
    contradiction_resolve_fn: Any = None,  # NEW — AD-403
) -> None:
    # ... existing assignments ...
    self._contradiction_resolve_fn = contradiction_resolve_fn
```

**2c.** Add Step 3.5 to `dream_cycle()` between trust consolidation (Step 3) and pre-warm (Step 4):

```python
        # Step 3: Trust consolidation
        trust_adjustments = self._consolidate_trust(episodes)

        # Step 3.5: Contradiction detection (AD-403)
        contradictions = detect_contradictions(episodes)
        contradictions_found = len(contradictions)
        if contradictions and self._contradiction_resolve_fn:
            try:
                self._contradiction_resolve_fn(contradictions)
            except Exception as e:
                logger.debug("Contradiction resolve callback failed: %s", e)

        # Step 4: Pre-warm
        pre_warm = self._compute_pre_warm(episodes)
```

**2d.** Add `contradictions_found` to the `DreamReport` construction and log line.

## Part 3: Extend DreamReport

### Modify `src/probos/types.py`

Add `contradictions_found` field to the `DreamReport` dataclass (after `gaps_predicted`):

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

## Part 4: Wire Up the Callback in Runtime

### Modify `src/probos/runtime.py`

Find where `DreamingEngine` is constructed (search for `DreamingEngine(` in runtime.py). Add the `contradiction_resolve_fn` callback. The callback should log the contradictions and optionally annotate the older episodes:

```python
def _handle_contradictions(contradictions):
    """Log detected memory contradictions for review."""
    for c in contradictions:
        logger.info(
            "Memory contradiction: %s+%s — older %s (%s) vs newer %s (%s), "
            "similarity=%.2f",
            c.intent, c.agent_id,
            c.older_episode_id[:8], c.older_outcome,
            c.newer_episode_id[:8], c.newer_outcome,
            c.similarity,
        )
```

Pass `contradiction_resolve_fn=_handle_contradictions` to the `DreamingEngine` constructor alongside the existing `strategy_store_fn` and `gap_prediction_fn`.

**Important:** Read the existing DreamingEngine construction in runtime.py and match whatever pattern is used for the other callback parameters. Don't hardcode line numbers — find the constructor call by searching for `DreamingEngine(`.

## What NOT to Build (Yet)

- **LLM-based contradiction resolution** — Phase 2. Would use LLM to compare semantics, not just word overlap.
- **Episode annotation/superseding** — Phase 2. Would mark older episodes with `superseded_by` metadata in ChromaDB.
- **Cross-agent contradiction** — Phase 2. Comparing episodes across different agent shards.
- **Knowledge store reconciliation** — Phase 2. Propagating contradiction findings to the git-backed KnowledgeStore.
- **Automatic memory pruning** — Phase 2. Actually removing contradicted memories instead of just flagging.

## Files Created/Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/contradiction_detector.py` | **NEW** — `detect_contradictions()`, `Contradiction` dataclass, `_jaccard_similarity()` |
| `src/probos/cognitive/dreaming.py` | Add Step 3.5 — contradiction detection with callback |
| `src/probos/types.py` | Add `contradictions_found` field to `DreamReport` |
| `src/probos/runtime.py` | Wire `contradiction_resolve_fn` callback to DreamingEngine |

## Testing

### New tests in `tests/test_contradiction_detector.py`:

1. **No contradictions — identical outcomes:** Two episodes with same input and same success outcome → no contradictions detected.
2. **Contradiction detected — opposite outcomes:** Two episodes with near-identical inputs, same intent+agent, one success one failure → 1 contradiction, older episode identified correctly.
3. **Below similarity threshold — no match:** Two episodes with different inputs but same intent → 0 contradictions (Jaccard too low).
4. **Multiple contradictions:** Three episodes forming two contradiction pairs → both detected.
5. **Empty episodes list:** `detect_contradictions([])` → empty list, no crash.
6. **Single episode:** One episode → no contradictions (nothing to compare).
7. **Jaccard similarity — identical texts:** `_jaccard_similarity("hello world", "hello world")` → 1.0
8. **Jaccard similarity — disjoint texts:** `_jaccard_similarity("foo bar", "baz qux")` → 0.0
9. **Jaccard similarity — partial overlap:** Verify correct ratio.
10. **Jaccard similarity — empty input:** One or both empty → 0.0

### Extend `tests/test_dreaming.py`:

11. **Dream cycle includes contradiction count:** Run `dream_cycle()` with contradictory mock episodes → `DreamReport.contradictions_found > 0`.
12. **Dream cycle with no contradictions:** Normal episodes → `DreamReport.contradictions_found == 0`.
13. **Contradiction callback invoked:** Provide a mock `contradiction_resolve_fn`, verify it's called with the contradiction list.

### Regression:

```
uv run pytest tests/test_contradiction_detector.py tests/test_dreaming.py -v
```

Then:
```
uv run pytest tests/ --tb=short
```

## Commit Message

```
Add memory contradiction detection in dream consolidation (AD-403)

Deterministic contradiction detector: Jaccard word-overlap similarity
on episode inputs + outcome disagreement for same intent+agent pairs.
Integrated as Step 3.5 in dream_cycle between trust consolidation and
pre-warm. DreamReport extended with contradictions_found. Runtime
callback logs contradictions. Foundation for Phase 2 LLM-based
reconciliation and episode superseding.
```
