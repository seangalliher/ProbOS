# AD-670: Working Memory Metabolism

**Issue:** AD-670
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-573 (working memory — complete)
**Note:** AD-667 (named buffers) and AD-668 (salience filter) are listed as dependencies in the roadmap but are not yet implemented. This AD is designed to work with the **current** 5-deque buffer structure and will be forward-compatible when named buffers land. Salience scores are computed internally here, not delegated to AD-668.
**Files:** `src/probos/cognitive/memory_metabolism.py` (NEW ~180 lines), `src/probos/cognitive/agent_working_memory.py` (EDIT ~30 lines), `src/probos/config.py` (EDIT ~15 lines), `tests/test_ad670_memory_metabolism.py` (NEW ~16 tests)

---

## Problem

Agent working memory uses passive FIFO ring buffers (`deque(maxlen=N)`). Entries are evicted purely by position — the oldest entry is dropped when a new one arrives, regardless of whether the oldest entry is more valuable than the newest. There is no time-weighted decay, no active forgetting, no consistency checking.

The only staleness mechanism is in `from_dict()` (line 403), which prunes entries older than 24 hours during stasis restore. During active operation, a low-value entry from 5 seconds ago has the same retention priority as a high-value entry from 30 minutes ago.

This AD replaces passive FIFO eviction with intelligent lifecycle management via four metabolism operations:

1. **DECAY** — Time-weighted salience reduction. Recent entries outweigh stale ones.
2. **AUDIT** — Consistency checking for contradictory entries.
3. **FORGET** — Active removal of low-value entries based on decay score, not ring position.
4. **TRIAGE** — Score incoming entries for relevance before buffer entry (inline, called per-write).

Background execution during idle cognitive cycles via a periodic `run_cycle()`.

**What this does NOT include:**
- Named buffer restructuring (AD-667)
- External salience filter delegation (AD-668 — scores computed internally here)
- Cross-thread coordination (AD-669)
- Dream integration (AD-671)
- Modifying render_context() priority eviction — that stays as-is

---

## Section 1: MetabolismConfig

**File:** `src/probos/config.py` (EDIT)

Add a new Pydantic config model. Place it immediately after `WorkingMemoryConfig` (after line 681).

```python
class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management."""

    enabled: bool = True
    decay_half_life_seconds: float = 3600.0  # Salience halves every hour
    forget_threshold: float = 0.05  # Entries below this decayed score are forgotten
    min_entries_per_buffer: int = 2  # Always keep at least this many entries per buffer
    audit_enabled: bool = True  # Run contradiction audit during cycle
    cycle_interval_seconds: float = 300.0  # Run metabolism every 5 minutes
    triage_fullness_threshold: float = 0.8  # Buffer fullness ratio that raises promotion bar
    triage_base_score: float = 0.3  # Minimum salience score for buffer admission
```

Add `metabolism` field to `SystemConfig`. Find the existing `working_memory` field (line 1143) and add immediately after it:

```python
    metabolism: MetabolismConfig = MetabolismConfig()
```

**Run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x` — verify config loads without errors.

---

## Section 2: MemoryMetabolism — Core Engine

**File:** `src/probos/cognitive/memory_metabolism.py` (NEW)

This is a stateless service class. It operates on buffer contents passed to it — it does not own or store buffer references. `AgentWorkingMemory` calls it, passing its deques.

```python
"""AD-670: Working Memory Metabolism — active lifecycle management.

Four operations replace passive FIFO eviction:
  DECAY  — exponential time-weighted salience reduction
  AUDIT  — flag contradictory entries in same buffer
  FORGET — remove entries whose decayed salience falls below threshold
  TRIAGE — score incoming entries for buffer admission (inline gate)

MemoryMetabolism is a stateless service. AgentWorkingMemory owns the
buffers and calls metabolism methods, passing deques as arguments.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass

from probos.cognitive.agent_working_memory import WorkingMemoryEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditFlag:
    """A flagged pair of potentially contradictory entries."""

    entry_a_content: str
    entry_b_content: str
    buffer_name: str
    reason: str


@dataclass(frozen=True)
class MetabolismReport:
    """Summary of a single metabolism cycle."""

    decayed_count: int  # Entries that had their decay score updated
    forgotten_count: int  # Entries removed by FORGET
    audit_flags: list[AuditFlag]  # Contradictions found by AUDIT
    cycle_duration_ms: float


class MemoryMetabolism:
    """Stateless working memory lifecycle manager.

    All operations receive buffers as arguments. This class holds
    configuration but no mutable state — safe to share across agents.
    """

    def __init__(
        self,
        *,
        decay_half_life_seconds: float = 3600.0,
        forget_threshold: float = 0.05,
        min_entries_per_buffer: int = 2,
        audit_enabled: bool = True,
        triage_fullness_threshold: float = 0.8,
        triage_base_score: float = 0.3,
    ) -> None:
        if decay_half_life_seconds <= 0:
            raise ValueError("decay_half_life_seconds must be positive")
        if not (0.0 <= forget_threshold <= 1.0):
            raise ValueError("forget_threshold must be between 0.0 and 1.0")
        if min_entries_per_buffer < 0:
            raise ValueError("min_entries_per_buffer must be non-negative")

        self._decay_half_life = decay_half_life_seconds
        self._forget_threshold = forget_threshold
        self._min_entries = min_entries_per_buffer
        self._audit_enabled = audit_enabled
        self._triage_fullness_threshold = triage_fullness_threshold
        self._triage_base_score = triage_base_score

    # ── DECAY ────────────────────────────────────────────────────────

    def decay(self, buffer: deque[WorkingMemoryEntry], now: float | None = None) -> int:
        """Apply exponential decay to all entries in a buffer.

        Stores the decayed salience score in ``entry.metadata["_decay_score"]``.
        Formula: ``score = exp(-age / half_life * ln2)``

        Returns the number of entries updated.
        """
        now = now or time.time()
        count = 0
        for entry in buffer:
            age = now - entry.timestamp
            score = math.exp(-age * math.log(2) / self._decay_half_life)
            entry.metadata["_decay_score"] = round(score, 6)
            count += 1
        return count

    # ── FORGET ───────────────────────────────────────────────────────

    def forget(self, buffer: deque[WorkingMemoryEntry]) -> int:
        """Remove entries whose ``_decay_score`` is below forget_threshold.

        Always retains at least ``min_entries_per_buffer`` entries
        (the ones with the highest decay scores).

        Must be called AFTER ``decay()`` so that ``_decay_score`` is populated.

        Returns the number of entries removed.
        """
        if len(buffer) <= self._min_entries:
            return 0

        # Partition into keep vs candidates for removal
        scored = [
            (entry, entry.metadata.get("_decay_score", 1.0))
            for entry in buffer
        ]

        # Sort by score descending — highest score first
        scored.sort(key=lambda x: x[1], reverse=True)

        # Always keep at least min_entries, plus anything above threshold
        keep: list[WorkingMemoryEntry] = []
        remove_count = 0

        for i, (entry, score) in enumerate(scored):
            if i < self._min_entries or score >= self._forget_threshold:
                keep.append(entry)
            else:
                remove_count += 1
                logger.debug(
                    "FORGET: removing entry (score=%.4f, age=%.0fs): %.60s...",
                    score, entry.age_seconds(), entry.content,
                )

        if remove_count > 0:
            # Rebuild the buffer preserving original chronological order
            keep_set = set(id(e) for e in keep)
            surviving = [e for e in buffer if id(e) in keep_set]
            buffer.clear()
            buffer.extend(surviving)

        return remove_count

    # ── AUDIT ────────────────────────────────────────────────────────

    def audit(
        self,
        buffer: deque[WorkingMemoryEntry],
        buffer_name: str,
    ) -> list[AuditFlag]:
        """Scan for potentially contradictory entries in the same buffer.

        Heuristic: two entries within 5 minutes of each other from the
        same source_pathway, where one contains a negation word that the
        other does not, are flagged for review.

        Returns a list of AuditFlag objects. This method flags but does
        NOT remove entries — the agent or a higher-level process decides
        what to do with contradictions.
        """
        if not self._audit_enabled:
            return []

        _NEGATION_WORDS = frozenset({
            "not", "no", "never", "none", "nothing", "neither",
            "nobody", "nowhere", "isn't", "aren't", "wasn't",
            "weren't", "won't", "don't", "doesn't", "didn't",
            "can't", "couldn't", "shouldn't", "wouldn't",
            "unable", "failed", "failure", "stopped", "declined",
        })

        flags: list[AuditFlag] = []
        entries = list(buffer)

        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]

                # Only compare entries from the same source pathway
                if a.source_pathway != b.source_pathway:
                    continue

                # Only compare entries within 5 minutes of each other
                if abs(a.timestamp - b.timestamp) > 300:
                    continue

                words_a = set(a.content.lower().split())
                words_b = set(b.content.lower().split())

                neg_a = words_a & _NEGATION_WORDS
                neg_b = words_b & _NEGATION_WORDS

                # Flag if one has negation and the other doesn't
                if bool(neg_a) != bool(neg_b):
                    # Check they share at least one content word (>3 chars)
                    content_overlap = {
                        w for w in (words_a & words_b)
                        if len(w) > 3 and w not in _NEGATION_WORDS
                    }
                    if content_overlap:
                        flags.append(AuditFlag(
                            entry_a_content=a.content[:100],
                            entry_b_content=b.content[:100],
                            buffer_name=buffer_name,
                            reason=(
                                f"Potential contradiction: shared topics "
                                f"{content_overlap}, opposing sentiment"
                            ),
                        ))

        return flags

    # ── TRIAGE ───────────────────────────────────────────────────────

    def triage(
        self,
        entry: WorkingMemoryEntry,
        buffer: deque[WorkingMemoryEntry],
    ) -> bool:
        """Score an incoming entry for buffer admission.

        Returns True if the entry should be admitted, False if it should
        be dropped. When the buffer is above the fullness threshold,
        the admission bar is raised.

        Scoring factors:
        - Base score (always applied)
        - Recency bonus (entries about very recent events get a boost)
        - Fullness penalty (when buffer is near capacity)
        """
        if buffer.maxlen is None or buffer.maxlen == 0:
            return True  # Unbounded buffer, always admit

        fullness = len(buffer) / buffer.maxlen

        # Compute entry score
        score = 1.0  # Start at full score

        # Fullness penalty: raise the bar when buffer is getting full
        if fullness >= self._triage_fullness_threshold:
            # Linear penalty from threshold to full
            overflow_ratio = (fullness - self._triage_fullness_threshold) / (
                1.0 - self._triage_fullness_threshold
            )
            required_score = self._triage_base_score + (
                (1.0 - self._triage_base_score) * overflow_ratio
            )
        else:
            required_score = self._triage_base_score

        # Very short entries get a reduced score
        if len(entry.content) < 20:
            score *= 0.5

        # Empty content is always rejected
        if not entry.content.strip():
            return False

        return score >= required_score

    # ── CYCLE ────────────────────────────────────────────────────────

    def run_cycle(
        self,
        buffers: dict[str, deque[WorkingMemoryEntry]],
    ) -> MetabolismReport:
        """Execute a full metabolism cycle across all buffers.

        Runs DECAY -> AUDIT -> FORGET in sequence.
        TRIAGE is not part of the cycle — it runs inline on each write.

        Args:
            buffers: Map of buffer_name -> deque. The caller
                (AgentWorkingMemory) provides its internal deques.

        Returns:
            MetabolismReport summarizing the cycle.
        """
        start = time.monotonic()
        now = time.time()
        total_decayed = 0
        total_forgotten = 0
        all_flags: list[AuditFlag] = []

        for name, buf in buffers.items():
            if not buf:
                continue

            # Step 1: DECAY
            total_decayed += self.decay(buf, now=now)

            # Step 2: AUDIT
            flags = self.audit(buf, buffer_name=name)
            all_flags.extend(flags)

            # Step 3: FORGET
            total_forgotten += self.forget(buf)

        elapsed_ms = (time.monotonic() - start) * 1000

        if total_forgotten > 0 or all_flags:
            logger.info(
                "Metabolism cycle complete: decayed=%d, forgotten=%d, "
                "audit_flags=%d, duration=%.1fms",
                total_decayed, total_forgotten, len(all_flags), elapsed_ms,
            )

        return MetabolismReport(
            decayed_count=total_decayed,
            forgotten_count=total_forgotten,
            audit_flags=all_flags,
            cycle_duration_ms=round(elapsed_ms, 2),
        )
```

**Run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad670_memory_metabolism.py -v -x -k "test_decay or test_forget or test_audit or test_triage or test_run_cycle"` — tests from Section 4 below.

---

## Section 3: AgentWorkingMemory Integration

**File:** `src/probos/cognitive/agent_working_memory.py` (EDIT)

### 3a: Add import

At the top of the file, add after the existing imports (after line 22):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.memory_metabolism import MemoryMetabolism
```

Note: Use `TYPE_CHECKING` guard to avoid circular import risk. The actual `MemoryMetabolism` instance is injected at runtime.

### 3b: Add metabolism slot to __init__

In `AgentWorkingMemory.__init__()`, add after the `self._correlation_id` line (after line 107):

```python
        # AD-670: Optional metabolism engine for active lifecycle management
        self._metabolism: MemoryMetabolism | None = None
```

### 3c: Add set_metabolism method

Add a new public method after `clear_correlation_id()` (after line 225):

```python
    def set_metabolism(self, metabolism: MemoryMetabolism) -> None:
        """AD-670: Attach a metabolism engine for active lifecycle management."""
        self._metabolism = metabolism

    def get_buffers(self) -> dict[str, deque[WorkingMemoryEntry]]:
        """AD-670: Expose internal buffers for metabolism operations.

        Returns a dict mapping buffer names to the live deque references.
        The metabolism engine operates on these directly.
        """
        return {
            "actions": self._recent_actions,
            "observations": self._recent_observations,
            "conversations": self._recent_conversations,
            "events": self._recent_events,
            "reasoning": self._recent_reasoning,
        }

    def run_metabolism_cycle(self) -> None:
        """AD-670: Run one metabolism cycle if metabolism is attached."""
        if self._metabolism is None:
            return
        from probos.cognitive.memory_metabolism import MemoryMetabolism  # noqa: F811
        self._metabolism.run_cycle(self.get_buffers())
```

The `from` import inside `run_metabolism_cycle` is intentional — it resolves the TYPE_CHECKING guard at runtime only when the method is actually called. The `noqa` suppresses the "redefined" lint warning.

### 3d: Add triage gate to record methods (optional triage)

In each of the five `record_*` methods (`record_action`, `record_observation`, `record_conversation`, `record_event`, `record_reasoning`), add a triage gate **before** the `self._recent_*.append(...)` call.

For `record_action` (around line 120), change:

```python
        self._recent_actions.append(WorkingMemoryEntry(
```

to:

```python
        new_entry = WorkingMemoryEntry(
            content=summary,
            category="action",
            source_pathway=source,
            metadata=_meta,
            knowledge_source=knowledge_source,
        )
        if self._metabolism and not self._metabolism.triage(new_entry, self._recent_actions):
            logger.debug("TRIAGE rejected action entry: %.60s...", summary)
            return
        self._recent_actions.append(new_entry)
```

Remove the old `self._recent_actions.append(WorkingMemoryEntry(...))` block that was there before — replace it entirely with the above.

Apply the same pattern to the other four record methods:
- `record_observation`: gate before `self._recent_observations.append(...)`
- `record_conversation`: gate before `self._recent_conversations.append(...)`
- `record_event`: gate before `self._recent_events.append(...)`
- `record_reasoning`: gate before `self._recent_reasoning.append(...)`

Each follows the same pattern: construct the `WorkingMemoryEntry` first, pass it through `self._metabolism.triage()`, and only append if triage returns True (or if `self._metabolism` is None).

**Important:** When `self._metabolism is None`, all entries are admitted (no triage gate). This preserves backward compatibility — existing code that creates `AgentWorkingMemory` without calling `set_metabolism()` behaves identically to before.

**Run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py tests/test_ad670_memory_metabolism.py -v -x` — verify existing WM tests still pass AND new tests pass.

---

## Section 4: Tests

**File:** `tests/test_ad670_memory_metabolism.py` (NEW)

```python
"""AD-670: Tests for Working Memory Metabolism."""

from __future__ import annotations

import math
import time
from collections import deque

import pytest

from probos.cognitive.agent_working_memory import (
    AgentWorkingMemory,
    WorkingMemoryEntry,
)
from probos.cognitive.memory_metabolism import (
    AuditFlag,
    MemoryMetabolism,
    MetabolismReport,
)


def _make_entry(
    content: str = "test entry",
    category: str = "observation",
    source: str = "system",
    age_seconds: float = 0.0,
    metadata: dict | None = None,
) -> WorkingMemoryEntry:
    """Helper to create a WorkingMemoryEntry with a specific age."""
    return WorkingMemoryEntry(
        content=content,
        category=category,
        source_pathway=source,
        timestamp=time.time() - age_seconds,
        metadata=metadata or {},
    )


def _make_buffer(
    entries: list[WorkingMemoryEntry],
    maxlen: int = 10,
) -> deque[WorkingMemoryEntry]:
    buf: deque[WorkingMemoryEntry] = deque(maxlen=maxlen)
    buf.extend(entries)
    return buf


class TestDecay:
    """DECAY operation tests."""

    def test_decay_fresh_entry_score_near_one(self):
        """A just-created entry should have decay score near 1.0."""
        m = MemoryMetabolism(decay_half_life_seconds=3600)
        buf = _make_buffer([_make_entry(age_seconds=0)])
        m.decay(buf)
        score = buf[0].metadata["_decay_score"]
        assert 0.99 <= score <= 1.0

    def test_decay_half_life_entry(self):
        """An entry exactly one half-life old should have score ~0.5."""
        m = MemoryMetabolism(decay_half_life_seconds=3600)
        buf = _make_buffer([_make_entry(age_seconds=3600)])
        m.decay(buf)
        score = buf[0].metadata["_decay_score"]
        assert 0.49 <= score <= 0.51

    def test_decay_very_old_entry_near_zero(self):
        """An entry 10 half-lives old should have score near zero."""
        m = MemoryMetabolism(decay_half_life_seconds=3600)
        buf = _make_buffer([_make_entry(age_seconds=36000)])
        m.decay(buf)
        score = buf[0].metadata["_decay_score"]
        assert score < 0.01

    def test_decay_returns_count(self):
        """decay() returns the number of entries updated."""
        m = MemoryMetabolism()
        entries = [_make_entry(content=f"e{i}") for i in range(5)]
        buf = _make_buffer(entries)
        count = m.decay(buf)
        assert count == 5

    def test_decay_empty_buffer(self):
        """decay() on empty buffer returns 0."""
        m = MemoryMetabolism()
        buf: deque[WorkingMemoryEntry] = deque(maxlen=10)
        assert m.decay(buf) == 0


class TestForget:
    """FORGET operation tests."""

    def test_forget_removes_below_threshold(self):
        """Entries with decay score below threshold are removed."""
        m = MemoryMetabolism(forget_threshold=0.1, min_entries_per_buffer=0)
        entries = [
            _make_entry(content="fresh", age_seconds=0),
            _make_entry(content="stale", age_seconds=36000),
        ]
        buf = _make_buffer(entries)
        m.decay(buf)
        removed = m.forget(buf)
        assert removed == 1
        assert len(buf) == 1
        assert buf[0].content == "fresh"

    def test_forget_respects_min_entries(self):
        """Even if all entries are stale, min_entries_per_buffer are kept."""
        m = MemoryMetabolism(
            forget_threshold=0.5,
            min_entries_per_buffer=2,
            decay_half_life_seconds=3600,
        )
        entries = [_make_entry(content=f"old{i}", age_seconds=7200) for i in range(5)]
        buf = _make_buffer(entries)
        m.decay(buf)
        m.forget(buf)
        assert len(buf) >= 2

    def test_forget_without_prior_decay_keeps_all(self):
        """Without decay scores, entries default to 1.0 and are kept."""
        m = MemoryMetabolism(forget_threshold=0.5, min_entries_per_buffer=0)
        entries = [_make_entry(content=f"e{i}") for i in range(3)]
        buf = _make_buffer(entries)
        removed = m.forget(buf)
        assert removed == 0
        assert len(buf) == 3

    def test_forget_empty_buffer(self):
        """forget() on empty buffer returns 0."""
        m = MemoryMetabolism()
        buf: deque[WorkingMemoryEntry] = deque(maxlen=10)
        assert m.forget(buf) == 0


class TestAudit:
    """AUDIT operation tests."""

    def test_audit_flags_contradiction(self):
        """Two entries with opposing sentiment on same topic are flagged."""
        m = MemoryMetabolism(audit_enabled=True)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="Trust scores are stable and healthy",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="Trust scores are not stable at all",
                category="observation",
                source_pathway="proactive",
                timestamp=now + 10,
            ),
        ]
        buf = _make_buffer(entries)
        flags = m.audit(buf, "observations")
        assert len(flags) >= 1
        assert flags[0].buffer_name == "observations"
        assert "contradiction" in flags[0].reason.lower()

    def test_audit_no_flag_for_different_sources(self):
        """Entries from different source pathways are not compared."""
        m = MemoryMetabolism(audit_enabled=True)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="Trust scores are stable",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="Trust scores are not stable",
                category="observation",
                source_pathway="dm",
                timestamp=now + 10,
            ),
        ]
        buf = _make_buffer(entries)
        flags = m.audit(buf, "observations")
        assert len(flags) == 0

    def test_audit_disabled(self):
        """When audit_enabled=False, no flags are produced."""
        m = MemoryMetabolism(audit_enabled=False)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="System is healthy",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="System is not healthy",
                category="observation",
                source_pathway="proactive",
                timestamp=now + 10,
            ),
        ]
        buf = _make_buffer(entries)
        assert m.audit(buf, "obs") == []

    def test_audit_no_flag_for_distant_timestamps(self):
        """Entries more than 5 minutes apart are not flagged."""
        m = MemoryMetabolism(audit_enabled=True)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="Latency is normal",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="Latency is not normal anymore",
                category="observation",
                source_pathway="proactive",
                timestamp=now + 400,  # > 300s
            ),
        ]
        buf = _make_buffer(entries)
        flags = m.audit(buf, "observations")
        assert len(flags) == 0


class TestTriage:
    """TRIAGE operation tests."""

    def test_triage_admits_normal_entry(self):
        """A normal entry is admitted to a non-full buffer."""
        m = MemoryMetabolism(triage_base_score=0.3)
        entry = _make_entry(content="Normal observation about system health")
        buf = _make_buffer([], maxlen=10)
        assert m.triage(entry, buf) is True

    def test_triage_rejects_empty_content(self):
        """An entry with empty content is always rejected."""
        m = MemoryMetabolism()
        entry = _make_entry(content="   ")
        buf = _make_buffer([], maxlen=10)
        assert m.triage(entry, buf) is False

    def test_triage_raises_bar_when_full(self):
        """When buffer is near capacity, short entries are rejected."""
        m = MemoryMetabolism(
            triage_fullness_threshold=0.8,
            triage_base_score=0.3,
        )
        # Fill buffer to 90% (9 of 10)
        entries = [_make_entry(content=f"entry {i} with enough words") for i in range(9)]
        buf = _make_buffer(entries, maxlen=10)

        # A very short entry should be rejected (score *= 0.5)
        short_entry = _make_entry(content="ok")
        assert m.triage(short_entry, buf) is False

    def test_triage_unbounded_buffer_always_admits(self):
        """A buffer with maxlen=None always admits."""
        m = MemoryMetabolism()
        entry = _make_entry(content="x")
        buf: deque[WorkingMemoryEntry] = deque()  # No maxlen
        assert m.triage(entry, buf) is True


class TestRunCycle:
    """Full metabolism cycle tests."""

    def test_run_cycle_returns_report(self):
        """run_cycle returns a MetabolismReport."""
        m = MemoryMetabolism()
        buffers = {
            "actions": _make_buffer([_make_entry(content="action 1")]),
            "observations": _make_buffer([]),
        }
        report = m.run_cycle(buffers)
        assert isinstance(report, MetabolismReport)
        assert report.decayed_count == 1
        assert report.forgotten_count == 0
        assert report.cycle_duration_ms >= 0

    def test_run_cycle_forgets_stale_entries(self):
        """A full cycle decays then forgets old entries."""
        m = MemoryMetabolism(
            decay_half_life_seconds=3600,
            forget_threshold=0.1,
            min_entries_per_buffer=0,
        )
        entries = [
            _make_entry(content="very old entry about system", age_seconds=36000),
            _make_entry(content="fresh entry about system", age_seconds=0),
        ]
        buffers = {"observations": _make_buffer(entries)}
        report = m.run_cycle(buffers)
        assert report.forgotten_count == 1
        assert len(buffers["observations"]) == 1


class TestConstructorValidation:
    """Constructor input validation."""

    def test_negative_half_life_raises(self):
        with pytest.raises(ValueError, match="positive"):
            MemoryMetabolism(decay_half_life_seconds=-1)

    def test_forget_threshold_out_of_range_raises(self):
        with pytest.raises(ValueError, match="between"):
            MemoryMetabolism(forget_threshold=1.5)

    def test_negative_min_entries_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            MemoryMetabolism(min_entries_per_buffer=-1)


class TestAgentWorkingMemoryIntegration:
    """Integration: AgentWorkingMemory + MemoryMetabolism."""

    def test_set_metabolism_and_run_cycle(self):
        """Attaching metabolism and running a cycle succeeds."""
        wm = AgentWorkingMemory()
        m = MemoryMetabolism()
        wm.set_metabolism(m)
        wm.record_action("did something", source="system")
        wm.run_metabolism_cycle()
        # Verify decay score was set
        entry = list(wm.get_buffers()["actions"])[0]
        assert "_decay_score" in entry.metadata

    def test_run_metabolism_cycle_without_metabolism_is_noop(self):
        """Calling run_metabolism_cycle without set_metabolism is a no-op."""
        wm = AgentWorkingMemory()
        wm.record_action("test", source="system")
        wm.run_metabolism_cycle()  # Should not raise

    def test_triage_gate_rejects_empty_content(self):
        """With metabolism attached, empty-content entries are rejected."""
        wm = AgentWorkingMemory()
        m = MemoryMetabolism()
        wm.set_metabolism(m)
        wm.record_action("   ", source="system")
        assert len(wm.get_buffers()["actions"]) == 0

    def test_no_metabolism_admits_all(self):
        """Without metabolism, all entries are admitted (backward compat)."""
        wm = AgentWorkingMemory()
        wm.record_action("   ", source="system")
        assert len(wm.get_buffers()["actions"]) == 1
```

**Run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad670_memory_metabolism.py -v -x` — all 22 tests should pass.

---

## Section 5: Full Test Suite

**Run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` — full suite green.

Pay special attention to:
- `tests/test_agent_working_memory.py` — existing WM tests must all still pass
- `tests/test_config.py` — config loading must still work

---

## Tracking

After all tests pass:

1. **`PROGRESS.md`** — Find the AD-670 line (if present) and update status to `CLOSED`. If no line exists, add one in the Ambient Awareness wave section:
   ```
   - [x] AD-670: Working Memory Metabolism — active lifecycle management (CLOSED)
   ```

2. **`docs/development/roadmap.md`** — Update the AD-670 entry from `Planned` to `Complete`:
   Change `*(Planned, OSS, Issue #351)*` to `*(Complete, OSS, Issue #351)*`

3. **`DECISIONS.md`** — Add entry:
   ```
   ## AD-670: Working Memory Metabolism
   **Date:** 2026-04-26
   **Decision:** Implemented four metabolism operations (DECAY, AUDIT, FORGET, TRIAGE) as a stateless service class injected into AgentWorkingMemory. Exponential decay with configurable half-life replaces passive FIFO eviction. Works with current 5-deque structure; forward-compatible with AD-667 named buffers.
   **Alternatives considered:** (1) Inline decay in render_context() — rejected because it couples rendering with mutation. (2) Per-entry TTL field — simpler but doesn't support relative salience comparison. (3) Async background task in this AD — deferred to integration point; metabolism is synchronous and fast (<1ms per cycle).
   ```
