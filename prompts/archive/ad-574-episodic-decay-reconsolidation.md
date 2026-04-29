# AD-574: Episodic Decay & Reconsolidation Scheduling

**Status:** Ready for builder
**Scope:** New file + config edits + dream integration (~220 lines new, ~40 lines edits)
**Depends on:** AD-567d (ActivationTracker), AD-598 (importance scoring), AD-541c (spaced retrieval therapy)

**Acceptance Criteria:**
- All 12 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

The activation tracker (AD-567d) provides access-based activation decay (ACT-R `B_i = ln(sum t_j^{-d})`), but there is no Ebbinghaus-style forgetting curve with spaced retrieval scheduling. Episodes that were important once but never re-accessed decay the same as trivial ones. No mechanism schedules reconsolidation reviews for memories at risk of being lost.

This AD adds a `ReconsolidationScheduler` that:
1. Automatically schedules high-importance episodes for spaced review at storage time.
2. Uses Ebbinghaus-inspired intervals scaled by episode importance.
3. Returns due episodes for reconsolidation during dream Step 11 (spaced retrieval).
4. Extends or prunes episodes based on review outcomes.

## Architecture

```
EpisodicMemory.store()
    |
    +-- importance >= 7 --> ReconsolidationScheduler.schedule_review()
                                |
                                v
                        In-memory dict: {episode_id: ReconsolidationEntry}

DreamingEngine.dream_cycle() Step 11
    |
    +-- scheduler.get_due_reviews(now)
    +-- for each due episode:
            mark_reviewed(episode_id, retained=True/False)
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/reconsolidation.py` | **NEW** -- ReconsolidationScheduler, ReconsolidationEntry |
| `src/probos/config.py` | Add ReconsolidationConfig + wire into SystemConfig |
| `src/probos/cognitive/dreaming.py` | Accept scheduler in constructor, call in Step 11 |
| `src/probos/cognitive/episodic.py` | Add setter + call schedule_review after store for importance >= 7 |
| `src/probos/startup/dreaming.py` | Create and wire ReconsolidationScheduler |
| `tests/test_ad574_reconsolidation.py` | **NEW** -- 12 tests |

---

## Implementation

### Section 1: ReconsolidationConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after the `MetabolismConfig` class (around line 810):

```python
class ReconsolidationConfig(BaseModel):
    """AD-574: Episodic decay reconsolidation scheduling."""

    enabled: bool = True
    base_intervals_hours: list[float] = Field(default_factory=lambda: [1.0, 6.0, 24.0, 72.0, 168.0, 720.0])
    importance_scale_factor: float = 0.1
    max_scheduled: int = 500
```

Wire into `SystemConfig`. SEARCH for this anchor:

```python
    consultation: ConsultationConfig = ConsultationConfig()  # AD-594
```

ADD after it:

```python
    reconsolidation: ReconsolidationConfig = ReconsolidationConfig()  # AD-574
```

### Section 2: ReconsolidationEntry and ReconsolidationScheduler

**File:** `src/probos/cognitive/reconsolidation.py` (NEW)

```python
"""AD-574: Episodic Decay & Reconsolidation Scheduling.

Ebbinghaus-inspired spaced review scheduling for high-importance episodes.
Intervals scale inversely with importance: more important memories get
shorter initial intervals and slower interval growth.

In-memory only -- schedule is rebuilt from activation_tracker on restart.
No SQLite persistence for the schedule itself.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReconsolidationEntry:
    """Tracks the reconsolidation schedule for a single episode."""

    episode_id: str
    importance: int
    review_count: int = 0
    next_review_at: float = 0.0
    last_reviewed_at: float = 0.0
    retained: bool = True


class ReconsolidationScheduler:
    """Manages Ebbinghaus-style spaced reconsolidation reviews.

    Episodes are scheduled for periodic review at increasing intervals.
    Importance scales the intervals: higher importance = shorter gaps
    (reviewed more frequently). Each successful review extends the
    interval to the next tier. Failed reviews mark the episode for
    pruning consideration.

    Parameters
    ----------
    config : ReconsolidationConfig-like
        Configuration. Required — always provided via Pydantic defaults.
    episodic_memory : EpisodicMemory-like or None
        Optional reference to episodic memory (unused in this build,
        reserved for future reconsolidation-triggered recall).

    **Builder:** Config is always injected. Do NOT add in-class fallback defaults when config is None.
    """

    def __init__(
        self,
        config: Any,
        episodic_memory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory

        self._enabled: bool = config.enabled
        self._base_intervals_hours: list[float] = list(config.base_intervals_hours)
        self._importance_scale_factor: float = config.importance_scale_factor
        self._max_scheduled: int = config.max_scheduled

        # In-memory schedule: episode_id -> ReconsolidationEntry
        self._schedule: dict[str, ReconsolidationEntry] = {}

    def schedule_review(self, episode_id: str, importance: int) -> None:
        """Add an episode to the reconsolidation review schedule.

        Computes the first review time based on importance-scaled
        Ebbinghaus intervals. No-op if disabled, already scheduled,
        or at capacity.

        Parameters
        ----------
        episode_id : str
            The episode to schedule.
        importance : int
            Importance score (1-10). Higher importance = shorter intervals.
        """
        if not self._enabled:
            return

        if episode_id in self._schedule:
            return

        if len(self._schedule) >= self._max_scheduled:
            logger.debug(
                "AD-574: Reconsolidation schedule at capacity (%d), skipping %s",
                self._max_scheduled, episode_id,
            )
            return

        now = time.time()
        next_review = self._compute_next_review(review_count=0, importance=importance)

        self._schedule[episode_id] = ReconsolidationEntry(
            episode_id=episode_id,
            importance=importance,
            review_count=0,
            next_review_at=now + next_review,
            last_reviewed_at=now,
            retained=True,
        )

    def get_due_reviews(self, now: float | None = None, limit: int = 10) -> list[str]:
        """Return episode IDs due for reconsolidation review.

        Parameters
        ----------
        now : float or None
            Current timestamp. Uses time.time() if None.
        limit : int
            Maximum number of episode IDs to return.

        Returns
        -------
        list[str]
            Episode IDs whose next_review_at <= now, sorted by
            next_review_at ascending (most overdue first).
        """
        if not self._enabled:
            return []

        if now is None:
            now = time.time()

        due = [
            entry for entry in self._schedule.values()
            if entry.retained and entry.next_review_at <= now
        ]
        due.sort(key=lambda e: e.next_review_at)
        return [e.episode_id for e in due[:limit]]

    def mark_reviewed(self, episode_id: str, retained: bool) -> None:
        """Update schedule after a reconsolidation review.

        If retained is True, advances to the next Ebbinghaus interval.
        If retained is False, marks the episode as not retained (candidate
        for pruning by the activation tracker).

        Parameters
        ----------
        episode_id : str
            The reviewed episode.
        retained : bool
            Whether the episode passed reconsolidation review.
        """
        entry = self._schedule.get(episode_id)
        if entry is None:
            return

        now = time.time()
        entry.last_reviewed_at = now

        if retained:
            entry.review_count += 1
            interval = self._compute_next_review(
                review_count=entry.review_count,
                importance=entry.importance,
            )
            entry.next_review_at = now + interval
            entry.retained = True
        else:
            entry.retained = False
            logger.info(
                "AD-574: Episode %s marked not-retained after %d reviews, "
                "flagged for pruning consideration",
                episode_id, entry.review_count,
            )

    def _compute_next_review(self, review_count: int, importance: int) -> float:
        """Compute the next review interval in seconds.

        Uses Ebbinghaus-style spaced intervals from base_intervals_hours,
        scaled by importance. Higher importance = shorter intervals
        (scale factor = importance / 10).

        The interval index is clamped to the length of base_intervals_hours.
        Once all tiers are exhausted, the last interval repeats.

        Parameters
        ----------
        review_count : int
            How many reviews have been completed (0 = first review).
        importance : int
            Episode importance (1-10).

        Returns
        -------
        float
            Interval in seconds until the next review.
        """
        # Clamp index to available intervals
        idx = min(review_count, len(self._base_intervals_hours) - 1)
        base_hours = self._base_intervals_hours[idx]

        # Scale by importance: higher importance -> shorter interval
        # scale = 1.0 - (importance * scale_factor) + scale_factor
        # e.g., importance=10, factor=0.1 -> scale=0.1 (10x shorter)
        # e.g., importance=5,  factor=0.1 -> scale=0.6 (1.67x shorter)
        # e.g., importance=1,  factor=0.1 -> scale=1.0 (no change)
        scale = max(
            self._importance_scale_factor,
            1.0 - (importance - 1) * self._importance_scale_factor,
        )

        return base_hours * 3600.0 * scale

    @property
    def scheduled_count(self) -> int:
        """Number of episodes currently in the reconsolidation schedule."""
        return len(self._schedule)

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        retained = sum(1 for e in self._schedule.values() if e.retained)
        return {
            "scheduled_count": self.scheduled_count,
            "retained_count": retained,
            "not_retained_count": self.scheduled_count - retained,
            "enabled": self._enabled,
        }
```

### Section 3: EpisodicMemory Integration

**File:** `src/probos/cognitive/episodic.py`

#### 3a: Instance variable

In `__init__`, add after the `self._activation_tracker` assignment. SEARCH for this anchor in `__init__`:

```python
        self._activation_tracker: Any = None
```

ADD immediately after:

```python
        self._reconsolidation_scheduler: Any = None  # AD-574
```

#### 3b: Setter method

After `set_activation_tracker` method (around line 678), add:

```python
    def set_reconsolidation_scheduler(self, scheduler: Any) -> None:
        """AD-574: Wire the reconsolidation scheduler after construction."""
        self._reconsolidation_scheduler = scheduler
```

#### 3c: Auto-schedule in store()

In `async def store()`, after the episode is successfully persisted (after the `self._collection.add(...)` call and before `await self._evict()`), add:

```python
        # AD-574: Auto-schedule high-importance episodes for reconsolidation
        if (
            self._reconsolidation_scheduler is not None
            and episode.importance >= 7
        ):
            try:
                self._reconsolidation_scheduler.schedule_review(
                    episode.id, episode.importance,
                )
            except Exception:
                logger.debug(
                    "AD-574: Failed to schedule reconsolidation for episode %s",
                    episode.id, exc_info=True,
                )
```

**Builder:** Find the exact location by searching for `await self._evict()` in the `store()` method. Insert the reconsolidation block immediately before the `_evict()` call.

**Verify:** `Episode.importance` field exists on the Episode dataclass (added by AD-598).

### Section 4: DreamingEngine Integration

**File:** `src/probos/cognitive/dreaming.py`

#### 4a: Constructor parameter

Add `reconsolidation_scheduler` parameter to `DreamingEngine.__init__`. SEARCH for this parameter:

```python
        dream_wm_bridge: Any = None,  # AD-671: working memory bridge
```

ADD after it:

```python
        reconsolidation_scheduler: Any = None,  # AD-574: spaced review scheduling
```

And in the body of `__init__`, after `self._dream_wm_bridge = dream_wm_bridge`:

```python
        self._reconsolidation_scheduler = reconsolidation_scheduler  # AD-574
```

#### 4b: Step 11 integration

In `dream_cycle()`, find the Step 11 block (spaced retrieval therapy). SEARCH for:

```python
        # Step 11: Spaced Retrieval Therapy (AD-541c)
```

At the END of the Step 11 block (after the `except Exception:` block for Step 11 and before `# Step 12`), add:

```python
        # Step 11b: Reconsolidation Reviews (AD-574)
        if self._reconsolidation_scheduler:
            try:
                due_ids = self._reconsolidation_scheduler.get_due_reviews(
                    now=time.time(), limit=10,
                )
                for ep_id in due_ids:
                    # For this build: mark all due reviews as retained.
                    # Future: integrate with retrieval practice to assess quality.
                    self._reconsolidation_scheduler.mark_reviewed(ep_id, retained=True)
                if due_ids:
                    logger.info(
                        "AD-574 Step 11b: Reviewed %d reconsolidation-due episodes",
                        len(due_ids),
                    )
            except Exception:
                logger.debug("AD-574 Step 11b: Reconsolidation review failed", exc_info=True)
```

### Section 5: Startup Wiring

**File:** `src/probos/startup/dreaming.py`

#### 5a: Import

At the top of the file, add:

```python
from probos.cognitive.reconsolidation import ReconsolidationScheduler
```

#### 5b: Create scheduler

In `init_dreaming()`, after the `DreamingEngine` is created and before it is returned, create and wire the scheduler. SEARCH for the line where `DreamingEngine(` is instantiated. After the engine is created, add:

```python
    # AD-574: Reconsolidation scheduler
    reconsolidation_scheduler = None
    if config.reconsolidation.enabled:
        reconsolidation_scheduler = ReconsolidationScheduler(
            config=config.reconsolidation,
            episodic_memory=episodic_memory,
        )
        logger.info("AD-574: ReconsolidationScheduler initialized")
```

Then wire it into the dreaming engine. If the engine constructor already has the parameter (from Section 4a), pass it directly. Otherwise, add a setter. Check whether the `DreamingEngine(...)` call in `init_dreaming` already passes keyword arguments. If so, add `reconsolidation_scheduler=reconsolidation_scheduler` to that call.

Also wire it into episodic memory:

```python
    if reconsolidation_scheduler and episodic_memory:
        episodic_memory.set_reconsolidation_scheduler(reconsolidation_scheduler)
```

**Builder:** Follow the existing pattern for how `activation_tracker` is wired in this file.

---

## Tests

**File:** `tests/test_ad574_reconsolidation.py` (NEW)

All tests use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mock chains. Each test is isolated with its own fixtures.

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_schedule_review_adds_entry` | schedule_review creates a ReconsolidationEntry in the scheduler |
| 2 | `test_get_due_reviews_returns_due` | get_due_reviews returns episode IDs whose next_review_at has passed |
| 3 | `test_mark_reviewed_extends_interval` | mark_reviewed(retained=True) advances review_count and extends next_review_at |
| 4 | `test_mark_not_retained_flags_episode` | mark_reviewed(retained=False) sets retained=False |
| 5 | `test_ebbinghaus_intervals_progressive` | _compute_next_review returns progressively longer intervals for each review_count |
| 6 | `test_importance_scaling_shortens_interval` | Higher importance produces shorter intervals |
| 7 | `test_max_scheduled_cap` | After max_scheduled entries, new schedule_review calls are no-ops |
| 8 | `test_no_due_reviews_when_future` | get_due_reviews returns empty list when all reviews are in the future |
| 9 | `test_config_disabled_no_ops` | When enabled=False, schedule_review and get_due_reviews are no-ops |
| 10 | `test_auto_schedule_high_importance` | Episodes with importance >= 7 stored in EpisodicMemory trigger schedule_review |
| 11 | `test_multiple_reviews_progressive` | Successive mark_reviewed(retained=True) calls produce increasing intervals |
| 12 | `test_dream_step_integration` | ReconsolidationScheduler is called during dream cycle Step 11b |

### Test Pattern

```python
import time
import pytest
from probos.cognitive.reconsolidation import ReconsolidationScheduler, ReconsolidationEntry


class _FakeReconsolidationConfig:
    """Stub config for tests."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        base_intervals_hours: list[float] | None = None,
        importance_scale_factor: float = 0.1,
        max_scheduled: int = 500,
    ):
        self.enabled = enabled
        self.base_intervals_hours = base_intervals_hours or [1.0, 6.0, 24.0, 72.0, 168.0, 720.0]
        self.importance_scale_factor = importance_scale_factor
        self.max_scheduled = max_scheduled


@pytest.fixture
def scheduler():
    return ReconsolidationScheduler(config=_FakeReconsolidationConfig())
```

**Builder:** Config is always provided via Pydantic defaults. Do NOT add in-class fallback defaults.
```

---

## Targeted Test Commands

After Section 1-2 (Config + Scheduler class):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad574_reconsolidation.py::test_schedule_review_adds_entry tests/test_ad574_reconsolidation.py::test_ebbinghaus_intervals_progressive tests/test_ad574_reconsolidation.py::test_config_disabled_no_ops -v
```

After Section 3 (EpisodicMemory integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad574_reconsolidation.py -v
```

After Section 4-5 (DreamingEngine + startup wiring):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad574_reconsolidation.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_dreaming.py -v -x
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-574 Episodic Decay & Reconsolidation Scheduling — CLOSED`
- **docs/development/roadmap.md:** Update the AD-574 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-574: Episodic Decay & Reconsolidation Scheduling. Ebbinghaus-inspired
  spaced review scheduling for high-importance episodes. ReconsolidationScheduler
  tracks in-memory schedule with importance-scaled intervals [1h, 6h, 24h, 72h,
  168h, 720h]. Auto-schedules episodes with importance >= 7 at store() time.
  Dream Step 11b processes due reviews. In-memory only (no persistence).
  ```

---

## Scope Boundaries

**DO:**
- Create `reconsolidation.py` with ReconsolidationScheduler and ReconsolidationEntry.
- Add ReconsolidationConfig to config.py and wire into SystemConfig.
- Add `set_reconsolidation_scheduler` setter to EpisodicMemory.
- Auto-schedule high-importance episodes (importance >= 7) in `store()`.
- Wire into DreamingEngine constructor and dream_cycle Step 11b.
- Wire scheduler creation in startup/dreaming.py.
- Write all 12 tests.

**DO NOT:**
- Add SQLite persistence for the schedule (in-memory only, rebuilt from activation_tracker on restart).
- Implement LLM-based review quality assessment (for this build, all reviews are marked retained=True).
- Add cross-agent reconsolidation coordination.
- Modify existing tests.
- Add docstrings/comments to code you did not change.
- Add `numpy`, `scipy`, or other heavy dependencies.
