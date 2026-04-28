# AD-610: Utility-Based Storage Gating

**Status:** Ready for builder
**Scope:** New file + config edits + integration edits (~250 lines new, ~50 lines edits)
**Depends on:** AD-598 (importance scoring), BF-039 (rate limiting/dedup in store), AD-527 (EventType)

**Acceptance Criteria:**
- All 14 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`
- StorageGate adds negligible latency to the store() hot path (no LLM calls, no external I/O).

## Summary

`EpisodicMemory.store()` currently has basic BF-039 rate limiting and content similarity dedup, but no structured utility assessment at write time. Near-duplicates that pass the simple Jaccard check still waste storage. Low-utility episodes (trivial observations, redundant confirmations) dilute recall quality. Contradictions are only detected during dream consolidation (delayed, never prevented at write time).

This AD adds a `StorageGate` that evaluates every episode before persistence, producing an ACCEPT/REJECT/MERGE decision with a utility score. It runs before the existing BF-039 checks, providing a more principled first-pass filter.

## Architecture

```
EpisodicMemory.store(episode)
    |
    +-- StorageGate.evaluate(episode)
            |
            +-- _check_utility()    -> utility_score (weighted composite)
            +-- _check_near_duplicate() -> bool (cosine > threshold)
            +-- _check_contradiction()  -> str | None
            |
            v
        StorageDecision(ACCEPT / REJECT / MERGE)
            |
            +-- REJECT: log, emit EPISODE_REJECTED, return
            +-- MERGE:  update existing metadata, return
            +-- ACCEPT: continue to BF-039 checks, persist
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/storage_gate.py` | **NEW** -- StorageGate, StorageDecision |
| `src/probos/config.py` | Add StorageGateConfig + wire into SystemConfig |
| `src/probos/events.py` | Add EPISODE_REJECTED EventType member |
| `src/probos/cognitive/episodic.py` | Add setter, call gate.evaluate() in store() |
| `tests/test_ad610_storage_gating.py` | **NEW** -- 14 tests |

---

## Implementation

### Section 1: EventType Addition

**File:** `src/probos/events.py`

Add to the EventType enum. SEARCH for this anchor:

```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"  # AD-585: tiered knowledge load
```

ADD after it:

```python
    EPISODE_REJECTED = "episode_rejected"  # AD-610: storage gate rejected episode
```

### Section 2: StorageGateConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `ReconsolidationConfig` (or after `MetabolismConfig` if AD-574 is not built yet):

```python
class StorageGateConfig(BaseModel):
    """AD-610: Utility-based storage gating — write-time validation."""

    enabled: bool = True
    duplicate_threshold: float = 0.95
    utility_floor: float = 0.2
    recent_window: int = 50
    contradiction_check_enabled: bool = True
```

Wire into `SystemConfig`. SEARCH for the last field in SystemConfig (e.g., `consultation: ConsultationConfig = ConsultationConfig()  # AD-594` or whatever is last). ADD after it:

```python
    storage_gate: StorageGateConfig = StorageGateConfig()  # AD-610
```

### Section 3: StorageGate and StorageDecision

**File:** `src/probos/cognitive/storage_gate.py` (NEW)

```python
"""AD-610: Utility-Based Storage Gating.

Write-time duplicate detection, utility scoring, and contradiction
flagging for episodic memory. Runs before persistence to prevent
low-value or redundant episodes from entering the store.

Uses lightweight heuristics (no LLM calls) for fast inline evaluation.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.similarity import jaccard_similarity
from probos.types import Episode

logger = logging.getLogger(__name__)


@dataclass
class StorageDecision:
    """Result of storage gate evaluation."""

    action: str  # "ACCEPT", "REJECT", "MERGE"
    reason: str
    utility_score: float
    duplicate_of: str | None = None


class StorageGate:
    """Evaluates episodes at write time for utility and duplication.

    Maintains a sliding window of recent episodes (content summaries)
    for near-duplicate detection. Does not access ChromaDB — works
    from an in-memory ring buffer of recent episode fingerprints.

    Parameters
    ----------
    config : StorageGateConfig-like
        Configuration. Required — always provided via Pydantic defaults.
    emit_event_fn : callable or None
        Callback ``(EventType, dict) -> None`` for event emission.

    **Builder:** Config is always provided via Pydantic defaults. Do NOT add in-class fallback defaults.
    """

    def __init__(
        self,
        config: Any,
        emit_event_fn: Any = None,
    ) -> None:
        self._emit_event_fn = emit_event_fn

        self._enabled: bool = config.enabled
        self._duplicate_threshold: float = config.duplicate_threshold
        self._utility_floor: float = config.utility_floor
        self._recent_window: int = config.recent_window
        self._contradiction_check_enabled: bool = config.contradiction_check_enabled

        # Ring buffer of recent episode fingerprints for dedup
        # Each entry: {"id": str, "content": str, "outcomes_summary": str, "timestamp": float}
        self._recent: deque[dict[str, Any]] = deque(maxlen=self._recent_window)

    def evaluate(self, episode: Episode) -> StorageDecision:
        """Evaluate an episode for storage worthiness.

        Checks in order:
        1. Empty content -> REJECT
        2. Near-duplicate of recent episode -> REJECT
        3. Utility score below floor -> REJECT (unless importance >= 8)
        4. Contradiction detected -> ACCEPT with warning logged
        5. Otherwise -> ACCEPT

        After evaluation, the episode fingerprint is added to the
        recent buffer regardless of decision (to catch future dupes).

        Parameters
        ----------
        episode : Episode
            The episode to evaluate.

        Returns
        -------
        StorageDecision
            The gating decision.
        """
        if not self._enabled:
            return StorageDecision(
                action="ACCEPT",
                reason="gate_disabled",
                utility_score=1.0,
            )

        content = self._extract_content(episode)

        # Check 1: Empty content
        if not content.strip():
            self._emit_rejection(episode, "empty_content")
            return StorageDecision(
                action="REJECT",
                reason="empty_content",
                utility_score=0.0,
            )

        # Check 2: Near-duplicate
        dup_id = self._check_near_duplicate(episode, content)
        if dup_id is not None:
            self._emit_rejection(episode, "near_duplicate")
            return StorageDecision(
                action="REJECT",
                reason="near_duplicate",
                utility_score=0.0,
                duplicate_of=dup_id,
            )

        # Check 3: Utility scoring
        utility = self._check_utility(episode, content)

        # High importance bypasses utility floor
        # **Note:** Episodes with importance >= 8 bypass the gate. This is
        # intentional — high-importance episodes (security alerts, system
        # errors) should always be stored.
        if utility < self._utility_floor and episode.importance < 8:
            self._emit_rejection(episode, "below_utility_floor")
            return StorageDecision(
                action="REJECT",
                reason="below_utility_floor",
                utility_score=utility,
            )

        # Check 4: Contradiction (informational only — still ACCEPT)
        if self._contradiction_check_enabled:
            contradiction = self._check_contradiction(episode, content)
            if contradiction:
                logger.info(
                    "AD-610: Contradiction detected for episode %s: %s",
                    episode.id, contradiction,
                )

        # Record fingerprint for future dedup
        self._record_fingerprint(episode, content)

        return StorageDecision(
            action="ACCEPT",
            reason="passed_all_checks",
            utility_score=utility,
        )

    def _extract_content(self, episode: Episode) -> str:
        """Extract searchable text content from an episode."""
        parts: list[str] = []
        if episode.user_input:
            parts.append(episode.user_input)
        if episode.reflection:
            parts.append(episode.reflection)
        for outcome in episode.outcomes:
            if isinstance(outcome, dict):
                result = outcome.get("result", "")
                if result:
                    parts.append(str(result))
        return " ".join(parts)

    def _check_near_duplicate(
        self,
        episode: Episode,
        content: str,
    ) -> str | None:
        """Check if episode is a near-duplicate of a recent episode.

        Uses Jaccard word similarity (already available in the codebase
        via probos.cognitive.similarity). Returns the duplicate's episode
        ID if similarity exceeds the threshold, else None.
        """
        if not content:
            return None

        for recent in self._recent:
            sim = jaccard_similarity(content, recent["content"])
            if sim >= self._duplicate_threshold:
                return recent["id"]
        return None

    def _check_utility(self, episode: Episode, content: str) -> float:
        """Score episode utility as a weighted composite.

        Components (weights sum to 1.0):
        - importance (40%): episode.importance / 10
        - content_length (20%): min(len(content) / 500, 1.0)
        - anchor_completeness (20%): fraction of anchor fields filled
        - source_diversity (20%): bonus for non-default source types

        Returns a score between 0.0 and 1.0.
        """
        # Importance component (40%)
        importance_score = min(episode.importance / 10.0, 1.0)

        # Content length component (20%)
        length_score = min(len(content) / 500.0, 1.0)

        # Anchor completeness component (20%)
        anchor_score = 0.0
        if episode.anchors is not None:
            filled = 0
            total = 6  # department, channel, trigger_type, watch_section, participants, trigger_agent
            if episode.anchors.department:
                filled += 1
            if episode.anchors.channel:
                filled += 1
            if episode.anchors.trigger_type:
                filled += 1
            if episode.anchors.watch_section:
                filled += 1
            if episode.anchors.participants:
                filled += 1
            if episode.anchors.trigger_agent:
                filled += 1
            anchor_score = filled / total

        # Source diversity component (20%)
        source_score = 0.5  # Default "direct" source
        if episode.source and episode.source != "direct":
            source_score = 0.8  # Non-default sources get higher score

        return (
            0.4 * importance_score
            + 0.2 * length_score
            + 0.2 * anchor_score
            + 0.2 * source_score
        )

    def _check_contradiction(
        self,
        episode: Episode,
        content: str,
    ) -> str | None:
        """Check for potential contradictions with recent episodes.

        Uses simple keyword overlap heuristic: if a recent episode shares
        significant word overlap but has a different outcome pattern,
        flag as potential contradiction. Returns a description string
        if contradiction detected, else None.

        This is a lightweight write-time check. Full contradiction detection
        happens during dream consolidation (AD-403).
        """
        if not content:
            return None

        for recent in self._recent:
            word_overlap = jaccard_similarity(content, recent["content"])
            if word_overlap < 0.3:
                continue  # Not similar enough to contradict

            # Check if outcomes differ significantly
            ep_outcomes = self._summarize_outcomes(episode)
            recent_outcomes = recent.get("outcomes_summary", "")

            if ep_outcomes and recent_outcomes:
                outcome_sim = jaccard_similarity(ep_outcomes, recent_outcomes)
                if outcome_sim < 0.2 and word_overlap > 0.5:
                    return (
                        f"High content similarity ({word_overlap:.2f}) but "
                        f"low outcome similarity ({outcome_sim:.2f}) with "
                        f"episode {recent['id']}"
                    )
        return None

    def _summarize_outcomes(self, episode: Episode) -> str:
        """Extract outcome summary for contradiction comparison."""
        parts: list[str] = []
        for outcome in episode.outcomes:
            if isinstance(outcome, dict):
                success = outcome.get("success", None)
                if success is not None:
                    parts.append(f"success={success}")
                error = outcome.get("error", "")
                if error:
                    parts.append(f"error={error}")
        return " ".join(parts)

    def _record_fingerprint(self, episode: Episode, content: str) -> None:
        """Add episode fingerprint to the recent buffer."""
        self._recent.append({
            "id": episode.id,
            "content": content,
            "outcomes_summary": self._summarize_outcomes(episode),
            "timestamp": episode.timestamp or time.time(),
        })

    def _emit_rejection(self, episode: Episode, reason: str) -> None:
        """Emit an EPISODE_REJECTED event."""
        if self._emit_event_fn:
            try:
                from probos.events import EventType
                self._emit_event_fn(EventType.EPISODE_REJECTED, {
                    "episode_id": episode.id,
                    "agent_ids": episode.agent_ids,
                    "reason": reason,
                    "importance": episode.importance,
                })
            except Exception:
                logger.debug(
                    "AD-610: Failed to emit EPISODE_REJECTED", exc_info=True,
                )

    @property
    def recent_count(self) -> int:
        """Number of episodes in the recent dedup window."""
        return len(self._recent)

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        return {
            "enabled": self._enabled,
            "recent_count": self.recent_count,
            "duplicate_threshold": self._duplicate_threshold,
            "utility_floor": self._utility_floor,
        }
```

### Section 4: EpisodicMemory Integration

**File:** `src/probos/cognitive/episodic.py`

#### 4a: Instance variable

In `__init__`, add after the `self._reconsolidation_scheduler` line (or after `self._activation_tracker` if AD-574 is not yet built). SEARCH for `self._activation_tracker: Any = None` and ADD nearby:

```python
        self._storage_gate: Any = None  # AD-610
```

#### 4b: Setter method

After `set_activation_tracker` (or after `set_reconsolidation_scheduler` if it exists), add:

```python
    def set_storage_gate(self, gate: Any) -> None:
        """AD-610: Wire the storage gate for write-time validation."""
        self._storage_gate = gate
```

#### 4c: Call gate in store()

In `async def store()`, insert the gate evaluation BEFORE the existing BF-039 checks. SEARCH for this anchor in `store()`:

```python
        # BF-039: Per-agent rate limit
        if self._is_rate_limited(episode):
```

INSERT before it:

```python
        # AD-610: Utility-based storage gating
        if self._storage_gate is not None:
            try:
                decision = self._storage_gate.evaluate(episode)
                if decision.action == "REJECT":
                    logger.debug(
                        "AD-610: Episode %s rejected by storage gate: %s",
                        episode.id, decision.reason,
                    )
                    return
                if decision.action == "MERGE":
                    logger.debug(
                        "AD-610: Episode %s merge suggested with %s (not implemented)",
                        episode.id, decision.duplicate_of,
                    )
                    return
            except Exception:
                logger.debug(
                    "AD-610: Storage gate evaluation failed for %s, allowing episode",
                    episode.id, exc_info=True,
                )

```

### Section 5: Startup Wiring

**File:** `src/probos/startup/cognitive_services.py`

After episodic memory is created and initialized, create and wire the StorageGate. SEARCH for the existing episodic memory initialization block. After it, add:

```python
    # AD-610: Storage gate for episodic memory
    storage_gate = None
    if config.storage_gate.enabled and episodic_memory:
        try:
            from probos.cognitive.storage_gate import StorageGate as _StorageGate

            storage_gate = _StorageGate(
                config=config.storage_gate,
                emit_event_fn=emit_event_fn,
            )
            episodic_memory.set_storage_gate(storage_gate)
            logger.info("AD-610: StorageGate initialized and wired to EpisodicMemory")
        except Exception as e:
            logger.warning("AD-610: StorageGate failed to start: %s — continuing without", e)
```

**Builder:** Follow the existing pattern in this file for how other services are created and wired to episodic memory (e.g., how activation_tracker is wired).

---

## Tests

**File:** `tests/test_ad610_storage_gating.py` (NEW)

All tests use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mock chains. Each test is isolated with its own fixtures.

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_accept_normal_episode` | Normal episode with adequate content passes all checks |
| 2 | `test_reject_near_duplicate` | Episode with Jaccard >= 0.95 similarity to recent episode is rejected |
| 3 | `test_reject_low_utility` | Episode with utility score below floor is rejected |
| 4 | `test_detect_contradiction` | Episode with high word overlap but different outcomes logs contradiction |
| 5 | `test_utility_scoring_components` | Each utility component (importance, length, anchor, source) contributes correctly |
| 6 | `test_duplicate_threshold_configurable` | Custom duplicate_threshold is respected |
| 7 | `test_utility_floor_configurable` | Custom utility_floor is respected |
| 8 | `test_disabled_gate_accepts_all` | When enabled=False, all episodes get ACCEPT |
| 9 | `test_merge_decision` | Future: MERGE path returns correctly (verify data structure) |
| 10 | `test_recent_window_boundary` | After recent_window episodes, oldest fingerprints are evicted |
| 11 | `test_high_importance_bypasses_utility` | Episode with importance >= 8 is accepted even with low utility |
| 12 | `test_event_emitted_on_reject` | EPISODE_REJECTED event is emitted when episode is rejected |
| 13 | `test_empty_episode_rejected` | Episode with no content (empty user_input, no outcomes) is rejected |
| 14 | `test_integration_with_store` | StorageGate wired to EpisodicMemory prevents rejected episodes from being stored |

### Test Pattern

```python
import pytest
import time

from probos.cognitive.storage_gate import StorageGate, StorageDecision
from probos.types import Episode, AnchorFrame


class _FakeStorageGateConfig:
    """Stub config for tests."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        duplicate_threshold: float = 0.95,
        utility_floor: float = 0.2,
        recent_window: int = 50,
        contradiction_check_enabled: bool = True,
    ):
        self.enabled = enabled
        self.duplicate_threshold = duplicate_threshold
        self.utility_floor = utility_floor
        self.recent_window = recent_window
        self.contradiction_check_enabled = contradiction_check_enabled


class _FakeEventCollector:
    """Collects emitted events for assertion."""

    def __init__(self):
        self.events: list[tuple] = []

    def __call__(self, event_type, data):
        self.events.append((event_type, data))


@pytest.fixture
def collector():
    return _FakeEventCollector()


@pytest.fixture
def gate(collector):
    return StorageGate(
        config=_FakeStorageGateConfig(),
        emit_event_fn=collector,
    )


def _make_episode(
    *,
    user_input: str = "test observation",
    importance: int = 5,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
    outcomes: list | None = None,
    episode_id: str = "",
) -> Episode:
    """Helper to create Episode instances for testing."""
    import uuid
    return Episode(
        id=episode_id or uuid.uuid4().hex,
        timestamp=time.time(),
        user_input=user_input,
        importance=importance,
        source=source,
        anchors=anchors,
        outcomes=outcomes or [],
    )
```

---

## Targeted Test Commands

After Section 1-2 (EventType + Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad610_storage_gating.py::test_disabled_gate_accepts_all -v
```

After Section 3 (StorageGate class):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad610_storage_gating.py -v
```

After Section 4 (EpisodicMemory integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad610_storage_gating.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_episodic_memory.py -v -x
```

After Section 5 (Startup wiring):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad610_storage_gating.py -v
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-610 Utility-Based Storage Gating — CLOSED`
- **docs/development/roadmap.md:** Update the AD-610 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-610: Utility-Based Storage Gating. Write-time episode validation via
  StorageGate: near-duplicate detection (Jaccard >= 0.95), utility scoring
  (importance 40%, content length 20%, anchor completeness 20%, source
  diversity 20%), lightweight contradiction flagging. Episodes below utility
  floor (0.2) are rejected unless importance >= 8. EPISODE_REJECTED event
  emitted on rejection. In-memory recent window (50 episodes) for dedup.
  ```

---

## Scope Boundaries

**DO:**
- Create `storage_gate.py` with StorageGate and StorageDecision.
- Add StorageGateConfig to config.py and wire into SystemConfig.
- Add EPISODE_REJECTED to EventType enum.
- Add `set_storage_gate` setter to EpisodicMemory.
- Insert gate.evaluate() call in store() before BF-039 checks.
- Wire StorageGate creation in startup/cognitive_services.py.
- Write all 14 tests.

**DO NOT:**
- Implement LLM-based semantic deduplication (use Jaccard word similarity only).
- Add retroactive dedup of existing episodes already in ChromaDB.
- Add cross-agent duplicate detection.
- Modify existing BF-039 rate limiting or content similarity dedup logic.
- Modify existing tests.
- Add docstrings/comments to code you did not change.
- Add `numpy`, `scipy`, or other heavy dependencies.
