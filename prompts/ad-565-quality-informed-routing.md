# AD-565: Quality-Informed Routing & Counselor Diagnostics

**Status:** Ready for builder
**Issue:** #10
**Dependencies:** AD-555 (NotebookQualityEngine), AD-503 (Counselor event subscriptions)
**Layer:** Knowledge (`src/probos/knowledge/`) + Cognitive (dreaming wiring)

## Problem

Quality scores from AD-555 notebook quality are computed during dream but not
used for routing decisions or Counselor diagnostics.  An agent with degrading
notebook quality gets the same routing weight as one with excellent quality.
The Counselor has no visibility into knowledge quality per agent.

## Scope

- New file: `src/probos/knowledge/quality_router.py`
- Modify: `src/probos/config.py` (add `QualityRouterConfig`, wire into `SystemConfig`)
- Modify: `src/probos/events.py` (add `QUALITY_CONCERN` event)
- Modify: `src/probos/cognitive/dreaming.py` (Step 10 quality router update)
- New test file: `tests/test_ad565_quality_routing.py`

## Do Not Build

- No LLM-based quality improvement suggestions.
- No quality-based task reassignment (routing weight only).
- No quality leaderboard or HXI dashboard.
- No direct HebbianRouter mutation — QualityRouter provides weights that callers
  can optionally use as multipliers.  HebbianRouter integration is informational
  only (log-level).

---

## Implementation

### 1. QualityRouterConfig in `src/probos/config.py`

Add after existing routing-related configs:

```python
class QualityRouterConfig(BaseModel):
    """AD-565: Quality-informed routing configuration."""

    enabled: bool = True
    min_weight: float = 0.5
    max_weight: float = 1.5
    concern_threshold: float = 0.3
```

Wire into `SystemConfig`:

```python
quality_router: QualityRouterConfig = QualityRouterConfig()  # AD-565
```

### 2. Event in `src/probos/events.py`

Add to the `EventType` enum:

```python
# Quality routing (AD-565)
QUALITY_CONCERN = "quality_concern"
```

No typed event dataclass needed.

### 3. QualityRouter in `src/probos/knowledge/quality_router.py`

New file.

```python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.config import QualityRouterConfig

logger = logging.getLogger(__name__)
```

**`QualityRouter` class:**

Constructor: `__init__(self, config: QualityRouterConfig, emit_event_fn: Any = None)`
- `self._config = config`
- `self._emit_event_fn = emit_event_fn`
- `self._quality_scores: dict[str, float] = {}`  — agent_id → quality_score
- `self._last_updated: dict[str, float] = {}`  — agent_id → timestamp

**`get_quality_weight(self, agent_id: str) -> float`:**
- If `config.enabled is False`, return `1.0` (neutral weight).
- If `agent_id` not in `_quality_scores`, return `1.0` (unknown agent = neutral).
- Formula: `config.min_weight + quality_score * (config.max_weight - config.min_weight)`
  - quality 0.0 → `min_weight` (0.5)
  - quality 1.0 → `max_weight` (1.5)
- Clamp to `[min_weight, max_weight]`.

**`update_quality(self, agent_id: str, quality_score: float) -> None`:**
- Store `quality_score` in `_quality_scores[agent_id]`.
- Store `time.time()` in `_last_updated[agent_id]`.
- If `quality_score < config.concern_threshold` and `emit_event_fn` is set,
  emit a `QUALITY_CONCERN` event:
  ```python
  self._emit_event_fn("quality_concern", {
      "agent_id": agent_id,
      "quality_score": quality_score,
      "weight": self.get_quality_weight(agent_id),
  })
  ```
- Log at INFO level: `"AD-565: Quality updated for %s — score=%.3f, weight=%.3f"`.

**`get_diagnostic(self, agent_id: str) -> dict`:**
- Return a dict suitable for Counselor consumption:
  ```python
  {
      "agent_id": agent_id,
      "quality_score": self._quality_scores.get(agent_id, None),
      "weight": self.get_quality_weight(agent_id),
      "last_updated": self._last_updated.get(agent_id, None),
      "concern": quality_score is not None and quality_score < config.concern_threshold,
  }
  ```

**`get_all_weights(self) -> dict[str, float]`:**
- Return `{agent_id: get_quality_weight(agent_id) for agent_id in _quality_scores}`.
- Used by Dream Step 10 for bulk logging.

### 4. Dream Step 10 Integration — `src/probos/cognitive/dreaming.py`

After quality snapshot is computed in Step 10, update the QualityRouter with
per-agent scores:

```python
# AD-565: Update quality router with per-agent scores
if self._quality_router and quality_snapshot:
    try:
        for agent_quality in quality_snapshot.per_agent:
            # AgentNotebookQuality has .callsign and .quality_score
            agent_id = agent_quality.callsign
            if agent_id:
                self._quality_router.update_quality(
                    agent_id, agent_quality.quality_score
                )
        weights = self._quality_router.get_all_weights()
        if weights:
            logger.info(
                "AD-565 Step 10: Quality routing updated for %d agents",
                len(weights),
            )
    except Exception:
        logger.debug("AD-565 Step 10: quality router update failed", exc_info=True)
```

Add `set_quality_router()` late-bind method to `DreamingEngine`:

```python
def set_quality_router(self, router: Any) -> None:
    """AD-565: Late-bind quality router."""
    self._quality_router = router
```

Initialize `self._quality_router = None` in the constructor body.

### 5. Startup wiring — `src/probos/startup/dreaming.py`

After `NotebookQualityEngine` creation:

```python
# AD-565: Quality-informed routing
from probos.knowledge.quality_router import QualityRouter
quality_router = None
if config.quality_router.enabled:
    quality_router = QualityRouter(
        config=config.quality_router,
        emit_event_fn=emit_event_fn,
    )
```

After dreaming engine creation, late-bind:

```python
if quality_router:
    dreaming_engine.set_quality_router(quality_router)
```

Store `quality_router` in `DreamingResult` so it is available for other
startup phases.  Add a `quality_router: Any = None` field to `DreamingResult`
in `src/probos/startup/results.py`.

---

## Tests

File: `tests/test_ad565_quality_routing.py`

10 tests:

| Test | Validates |
|------|-----------|
| `test_quality_weight_calculation` | Quality 0.0 → weight 0.5, quality 1.0 → weight 1.5, quality 0.5 → weight 1.0 |
| `test_update_quality` | `update_quality()` stores score and timestamp |
| `test_get_diagnostic` | Diagnostic dict has correct fields and values |
| `test_min_max_weight_bounds` | Weight never exceeds `[0.5, 1.5]` even with out-of-range quality |
| `test_unknown_agent_default_weight` | Unknown agent_id returns weight 1.0 |
| `test_quality_concern_event` | Quality < 0.3 emits `QUALITY_CONCERN` event |
| `test_no_concern_above_threshold` | Quality >= 0.3 → no event |
| `test_dream_update_flow` | Per-agent scores from `_FakeSnapshot` flow through to router |
| `test_config_disabled` | `enabled=False` → always returns weight 1.0, no events |
| `test_get_all_weights` | `get_all_weights()` returns correct dict for multiple agents |

All tests use `_Fake*` stubs.  No LLM calls.  No filesystem access.

Stubs:
```python
class _FakeEmitter:
    def __init__(self):
        self.events = []
    def __call__(self, event_type, data):
        self.events.append((event_type, data))

class _FakeAgentQuality:
    def __init__(self, callsign, quality_score):
        self.callsign = callsign
        self.quality_score = quality_score
```

---

## Tracking

- `PROGRESS.md`: Add `AD-565  Quality-Informed Routing  CLOSED`
- `DECISIONS.md`: Add entry: "AD-565: Quality-informed routing weights. Linear mapping quality 0-1 to weight 0.5-1.5. QUALITY_CONCERN event below 0.3. Counselor diagnostic API. No direct HebbianRouter mutation — callers opt in to multiplier."
- `docs/development/roadmap.md`: Update AD-565 row status to Complete.
- GitHub: Close issue #10.
