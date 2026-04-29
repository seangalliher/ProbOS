# AD-564: Quality-Triggered Forced Consolidation — Automated Notebook Maintenance

**Status:** Ready for builder
**Issue:** #10
**Dependencies:** AD-551 (Notebook Consolidation), AD-555 (NotebookQualityEngine)
**Layer:** Knowledge (`src/probos/knowledge/`)

## Problem

Notebook consolidation (AD-551) runs only during scheduled dream cycles.  Between
dreams, quality can degrade — high stale rate, repetition alerts — without
triggering maintenance.  No mechanism forces consolidation when quality drops
below threshold.

## Scope

- New file: `src/probos/knowledge/quality_trigger.py`
- Modify: `src/probos/config.py` (add `QualityTriggerConfig`, wire into `SystemConfig`)
- Modify: `src/probos/events.py` (add `FORCED_CONSOLIDATION_TRIGGERED` event)
- Modify: `src/probos/types.py` (add `forced_consolidations` to `DreamReport`)
- Modify: `src/probos/cognitive/dreaming.py` (Step 10 trigger check)
- New test file: `tests/test_ad564_quality_trigger.py`

## Do Not Build

- No LLM-based quality assessment (uses existing `NotebookQualitySnapshot` fields).
- No selective per-agent consolidation (ship-wide only).
- No quality trend analysis (point-in-time check only).
- No HXI controls for forced consolidation.

---

## Implementation

### 1. QualityTriggerConfig in `src/probos/config.py`

Add after `RecordsConfig`:

```python
class QualityTriggerConfig(BaseModel):
    """AD-564: Quality-triggered forced consolidation configuration."""

    enabled: bool = True
    min_quality_threshold: float = 0.4
    max_stale_rate: float = 0.3
    max_repetition_rate: float = 0.2
    cooldown_seconds: float = 1800.0  # 30 min between forced consolidations
    max_forced_per_day: int = 5
```

Wire into `SystemConfig`:

```python
quality_trigger: QualityTriggerConfig = QualityTriggerConfig()  # AD-564
```

### 2. Event in `src/probos/events.py`

Add to the `EventType` enum:

```python
# Quality-triggered consolidation (AD-564)
FORCED_CONSOLIDATION_TRIGGERED = "forced_consolidation_triggered"
```

No typed event dataclass needed.

### 3. QualityConsolidationTrigger in `src/probos/knowledge/quality_trigger.py`

New file.

```python
from __future__ import annotations
import logging
import time
from typing import Any

from probos.config import QualityTriggerConfig

logger = logging.getLogger(__name__)
```

**`QualityConsolidationTrigger` class:**

Constructor: `__init__(self, config: QualityTriggerConfig, emit_event_fn: Any = None)`
- `self._config = config`
- `self._emit_event_fn = emit_event_fn`
- `self._last_trigger_time: float = 0.0`
- `self._forced_today: int = 0`
- `self._day_start: float = time.time()`

**`check_and_trigger(self, snapshot: Any) -> bool`:**
- If `config.enabled is False`, return `False`.
- Call `_should_trigger(snapshot)`.
- If should trigger and cooldown/daily limits allow, log the reason, emit
  event, increment counters, return `True`.
- Otherwise return `False`.

The `snapshot` parameter is a `NotebookQualitySnapshot` (imported from
`probos.knowledge.notebook_quality`).  Use duck typing (`Any`) to avoid
hard import coupling.  Access via `snapshot.system_quality_score`,
`snapshot.stale_entry_rate`, `snapshot.repetition_alert_rate`.

**`_should_trigger(self, snapshot: Any) -> tuple[bool, str]`:**

Trigger conditions (any one sufficient):
- `snapshot.system_quality_score < config.min_quality_threshold`
  → reason: `"quality_score {score:.3f} < {threshold}"`
- `snapshot.stale_entry_rate > config.max_stale_rate`
  → reason: `"stale_rate {rate:.3f} > {threshold}"`
- `snapshot.repetition_alert_rate > config.max_repetition_rate`
  → reason: `"repetition_rate {rate:.3f} > {threshold}"`

Return `(False, "")` if none triggered.

**`_cooldown_ok(self) -> bool`:**
- Return `True` if `time.time() - self._last_trigger_time >= config.cooldown_seconds`.

**`_daily_limit_ok(self) -> bool`:**
- If current time is in a new day (86400s since `_day_start`), reset
  `_forced_today = 0` and `_day_start`.
- Return `self._forced_today < config.max_forced_per_day`.

**Event emission:**
When a trigger fires, if `self._emit_event_fn` is set:
```python
self._emit_event_fn("forced_consolidation_triggered", {
    "reason": reason,
    "quality_score": snapshot.system_quality_score,
    "stale_rate": snapshot.stale_entry_rate,
    "repetition_rate": snapshot.repetition_alert_rate,
})
```

### 4. DreamReport field — `src/probos/types.py`

Add after the existing `notebook_quality_agents` field (or after lint fields
if AD-563 is already present):

```python
# AD-564: Forced consolidation
forced_consolidations: int = 0
```

### 5. Dream Step 10 Integration — `src/probos/cognitive/dreaming.py`

After the quality snapshot is computed in Step 10, add:

```python
# AD-564: Quality-triggered forced consolidation check
forced_consolidation_count = 0
if self._quality_trigger and quality_snapshot:
    try:
        if self._quality_trigger.check_and_trigger(quality_snapshot):
            forced_consolidation_count += 1
            logger.info("AD-564 Step 10: Forced consolidation triggered")
    except Exception:
        logger.debug("AD-564 Step 10: trigger check failed", exc_info=True)
```

Add `set_quality_trigger()` late-bind method to `DreamingEngine`:

```python
def set_quality_trigger(self, trigger: Any) -> None:
    """AD-564: Late-bind quality consolidation trigger."""
    self._quality_trigger = trigger
```

Initialize `self._quality_trigger = None` in the constructor body.

Wire `forced_consolidation_count` into the `DreamReport` at the bottom:

```python
forced_consolidations=forced_consolidation_count,
```

### 6. Startup wiring — `src/probos/startup/dreaming.py`

After `NotebookQualityEngine` creation:

```python
# AD-564: Quality-triggered consolidation
from probos.knowledge.quality_trigger import QualityConsolidationTrigger
quality_trigger = None
if config.quality_trigger.enabled:
    quality_trigger = QualityConsolidationTrigger(
        config=config.quality_trigger,
        emit_event_fn=emit_event_fn,
    )
```

After dreaming engine creation, late-bind:

```python
if quality_trigger:
    dreaming_engine.set_quality_trigger(quality_trigger)
```

---

## Tests

File: `tests/test_ad564_quality_trigger.py`

10 tests:

| Test | Validates |
|------|-----------|
| `test_trigger_on_low_quality` | `system_quality_score < 0.4` triggers |
| `test_trigger_on_high_stale_rate` | `stale_entry_rate > 0.3` triggers |
| `test_trigger_on_high_repetition` | `repetition_alert_rate > 0.2` triggers |
| `test_no_trigger_good_quality` | All metrics within bounds → no trigger |
| `test_cooldown_prevents_rapid` | Second trigger within 1800s blocked |
| `test_max_per_day_limit` | 6th trigger in same day blocked |
| `test_config_disabled` | `enabled=False` → always returns `False` |
| `test_event_emitted` | `emit_event_fn` called with correct event type and data |
| `test_dream_report_field` | `DreamReport.forced_consolidations` field exists and defaults to 0 |
| `test_reason_string` | Trigger reason string includes metric name and values |

All tests use `_FakeSnapshot` with configurable quality fields.  `_FakeEmitter`
captures emitted events.  No LLM calls.  No filesystem access.

Snapshot stub:
```python
class _FakeSnapshot:
    def __init__(self, quality=0.8, stale=0.1, repetition=0.05):
        self.system_quality_score = quality
        self.stale_entry_rate = stale
        self.repetition_alert_rate = repetition
```

---

## Tracking

- `PROGRESS.md`: Add `AD-564  Quality-Triggered Forced Consolidation  CLOSED`
- `DECISIONS.md`: Add entry: "AD-564: Quality-triggered forced consolidation. Three trigger conditions (low quality, high stale rate, high repetition). Cooldown + daily limit. Event emission. Wired into Dream Step 10."
- `docs/development/roadmap.md`: Update AD-564 row status to Complete.
- GitHub: Close issue #10.

## Acceptance Criteria

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
