# AD-444: Knowledge Confidence Scoring

**Status:** Ready for builder
**Issue:** #43
**Dependencies:** AD-434 (RecordsStore), AD-555 (NotebookQualityEngine)
**Layer:** Knowledge (`src/probos/knowledge/`)

## Problem

Operational learnings in Ship's Records have no numerical confidence scores.
An entry confirmed 5 times and contradicted 0 times looks the same as a fresh
unverified observation.  There is no mechanism to auto-suppress low-confidence
knowledge or highlight high-confidence facts during dream-time quality checks.

## Scope

- New file: `src/probos/knowledge/confidence_tracker.py`
- Modify: `src/probos/config.py` (add `ConfidenceConfig`, wire into `SystemConfig`)
- Modify: `src/probos/events.py` (add two event types)
- Modify: `src/probos/knowledge/records_store.py` (expose confirm/contradict)
- Modify: `src/probos/cognitive/dreaming.py` (Step 10 cross-reference)
- New test file: `tests/test_ad444_confidence_scoring.py`

## Do Not Build

- No SQLite persistence — in-memory dict, rebuilt from entry metadata on restart.
- No LLM-based confirmation detection (that is future semantic analysis).
- No cross-instance confidence federation.
- No HXI dashboard for confidence.

---

## Implementation

### 1. ConfidenceConfig in `src/probos/config.py`

Add a new Pydantic config class after the existing `RecordsConfig`:

```python
class ConfidenceConfig(BaseModel):
    """AD-444: Knowledge confidence scoring configuration."""

    enabled: bool = True
    default_confidence: float = 0.5
    confirm_delta: float = 0.15
    contradict_delta: float = 0.25  # Applied as negative
    auto_supersede_threshold: float = 0.1
    auto_apply_threshold: float = 0.8
    suppress_threshold: float = 0.5
```

Wire into `SystemConfig`:

```python
confidence: ConfidenceConfig = ConfidenceConfig()  # AD-444
```

### 2. Events in `src/probos/events.py`

Add to the `EventType` enum (in the Knowledge section, after existing knowledge events):

```python
# Knowledge confidence (AD-444)
KNOWLEDGE_CONFIRMED = "knowledge_confirmed"
KNOWLEDGE_CONTRADICTED = "knowledge_contradicted"
```

No typed event dataclasses needed — these are simple dict-payload events.

### 3. ConfidenceTracker in `src/probos/knowledge/confidence_tracker.py`

New file.

**Imports:**
```python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from probos.config import ConfidenceConfig
```

**`ConfidenceEntry` dataclass:**
```python
@dataclass
class ConfidenceEntry:
    entry_path: str
    confidence: float = 0.5
    confirmations: int = 0
    contradictions: int = 0
    last_updated: float = field(default_factory=time.time)
```

**`ConfidenceTracker` class:**

- Constructor: `__init__(self, config: ConfidenceConfig)`
  - Store `self._config = config`
  - Store `self._entries: dict[str, ConfidenceEntry] = {}`

- `initialize_entry(self, entry_path: str) -> float` — create entry with default
  confidence if not already tracked.  Return current confidence.

- `get_confidence(self, entry_path: str) -> float` — return current confidence.
  If entry not tracked, return `config.default_confidence`.

- `confirm(self, entry_path: str) -> float` — increase confidence by
  `config.confirm_delta`, cap at 1.0.  Increment `confirmations` counter.
  Update `last_updated`.  Auto-create entry if not tracked.  Return new
  confidence.

- `contradict(self, entry_path: str) -> float` — decrease confidence by
  `config.contradict_delta`, floor at 0.0.  Increment `contradictions` counter.
  Update `last_updated`.  Auto-create entry if not tracked.  Return new
  confidence.

- `auto_supersede_check(self, entry_path: str) -> bool` — return `True` if
  confidence < `config.auto_supersede_threshold`.

- `get_presentation_tier(self, entry_path: str) -> str` — return:
  - `"auto_apply"` if confidence >= `config.auto_apply_threshold`
  - `"suppress"` if confidence < `config.suppress_threshold`
  - `"with_caveat"` otherwise

- `get_all_entries(self) -> dict[str, ConfidenceEntry]` — return copy of entries
  dict.  Used by dream step integration.

All methods must be no-ops (return defaults) when `config.enabled is False`.

### 4. Wire into RecordsStore — `src/probos/knowledge/records_store.py`

Add two public methods to `RecordsStore`:

```python
def set_confidence_tracker(self, tracker: Any) -> None:
    """AD-444: Late-bind confidence tracker."""
    self._confidence_tracker = tracker

async def confirm_entry(self, entry_path: str) -> float | None:
    """AD-444: Confirm an entry, increasing its confidence score."""
    if self._confidence_tracker is not None:
        return self._confidence_tracker.confirm(entry_path)
    return None

async def contradict_entry(self, entry_path: str) -> float | None:
    """AD-444: Contradict an entry, decreasing its confidence score."""
    if self._confidence_tracker is not None:
        return self._confidence_tracker.contradict(entry_path)
    return None
```

In `write_entry()`, after the file is written and committed, initialize confidence
for the new entry:

```python
# AD-444: Initialize confidence tracking for new entries
if self._confidence_tracker is not None:
    self._confidence_tracker.initialize_entry(path)
```

### 5. Dream Step 10 Integration — `src/probos/cognitive/dreaming.py`

Inside the existing Step 10 block (after `notebook_quality_score` is computed),
add a cross-reference of confidence scores.  This is read-only — no mutations.

```python
# AD-444: Cross-reference confidence scores during quality assessment
confidence_suppressed = 0
if self._confidence_tracker is not None:
    try:
        for entry in self._confidence_tracker.get_all_entries().values():
            if self._confidence_tracker.auto_supersede_check(entry.entry_path):
                confidence_suppressed += 1
        if confidence_suppressed > 0:
            logger.info(
                "AD-444 Step 10: %d entries below auto-supersede threshold",
                confidence_suppressed,
            )
    except Exception:
        logger.debug("AD-444 Step 10: confidence cross-ref failed", exc_info=True)
```

The DreamingEngine constructor does not need a new parameter.  The
`_confidence_tracker` attribute is set via late-binding at startup (same
pattern as `set_records_store()`):

```python
def set_confidence_tracker(self, tracker: Any) -> None:
    """AD-444: Late-bind confidence tracker."""
    self._confidence_tracker = tracker
```

**Builder:** Initialize `self._confidence_tracker: Any = None` in `__init__()` of both `RecordsStore` and `DreamingEngine`. Check with `if self._confidence_tracker is not None:` -- do NOT use `hasattr()`.

### 6. Startup wiring — `src/probos/startup/dreaming.py`

In `init_dreaming()`, after `NotebookQualityEngine` creation (line ~73):

```python
# AD-444: Confidence Tracker
from probos.knowledge.confidence_tracker import ConfidenceTracker
confidence_tracker = None
if config.confidence.enabled:
    confidence_tracker = ConfidenceTracker(config=config.confidence)
```

Pass to `DreamingEngine` via late-bind after engine creation:

```python
if confidence_tracker:
    dreaming_engine.set_confidence_tracker(confidence_tracker)
```

Also set on `records_store` if available:

```python
if confidence_tracker and records_store:
    records_store.set_confidence_tracker(confidence_tracker)
```

---

## Tests

File: `tests/test_ad444_confidence_scoring.py`

12 tests:

| Test | Validates |
|------|-----------|
| `test_default_confidence` | New entry gets `default_confidence` (0.5) |
| `test_confirm_increases` | `confirm()` raises by `confirm_delta` |
| `test_contradict_decreases` | `contradict()` lowers by `contradict_delta` |
| `test_confidence_floor_zero` | Repeated contradictions cannot go below 0.0 |
| `test_confidence_cap_one` | Repeated confirmations cannot exceed 1.0 |
| `test_auto_supersede_below_threshold` | `auto_supersede_check()` True when < 0.1 |
| `test_presentation_tier_auto_apply` | Tier is `"auto_apply"` when >= 0.8 |
| `test_presentation_tier_with_caveat` | Tier is `"with_caveat"` when 0.5-0.8 |
| `test_presentation_tier_suppress` | Tier is `"suppress"` when < 0.5 |
| `test_config_disabled` | All methods return defaults when `enabled=False` |
| `test_multiple_confirmations` | 5 confirms stack correctly (0.5 + 5*0.15 = 1.0 capped) |
| `test_records_store_confirm_contradict` | `RecordsStore.confirm_entry()` and `contradict_entry()` delegate to tracker |

All tests use `_Fake*` stubs.  No LLM calls.  No filesystem access.

---

## Tracking

- `PROGRESS.md`: Add `AD-444  Knowledge Confidence Scoring  CLOSED`
- `DECISIONS.md`: Add entry: "AD-444: In-memory confidence tracking for Ship's Records entries. Three-tier presentation (auto_apply/with_caveat/suppress). Wired into Dream Step 10 quality cross-reference."
- `docs/development/roadmap.md`: Update AD-444 row status to Complete.
- GitHub: Close issue #43.

## Acceptance Criteria

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
