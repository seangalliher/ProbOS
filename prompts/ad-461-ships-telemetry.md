# AD-461: Ship's Telemetry

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~9

---

## Problem

ProbOS has no centralized telemetry for key operations. Timing data is
scattered across individual modules (VitalsMonitor collects health metrics,
IntrospectiveTelemetryService provides self-awareness, but neither tracks
operation durations as structured events). There's no way to answer "how
long did the cognitive chain take?" or "what's the LLM call latency trend?"

## Fix

### Section 1: Create `TelemetryService`

**File:** `src/probos/substrate/telemetry.py` (new file)

A lightweight service that collects operation timing samples and periodically
emits a `TELEMETRY_REPORT` event with aggregated metrics.

```python
"""Ship's Telemetry — centralized operation timing (AD-461).

Collects timing samples for key operations and emits periodic
TELEMETRY_REPORT events with min/max/mean/p95 aggregations.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetrySample:
    """A single timing sample."""

    operation: str  # e.g. "cognitive_chain", "llm_call", "trust_update"
    duration_ms: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TelemetryBucket:
    """Aggregation bucket for a single operation type."""

    operation: str
    samples: list[float] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def mean_ms(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.samples) if self.samples else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.samples:
            return 0.0
        sorted_s = sorted(self.samples)
        idx = int(len(sorted_s) * 0.95)
        return sorted_s[min(idx, len(sorted_s) - 1)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "count": self.count,
            "mean_ms": round(self.mean_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
        }

    def clear(self) -> None:
        self.samples.clear()


class TelemetryService:
    """Centralized operation timing collector (AD-461).

    Usage:
        telemetry.record("cognitive_chain", duration_ms=42.5)
        # or as context manager:
        async with telemetry.measure("llm_call"):
            result = await llm.chat(...)
    """

    def __init__(
        self,
        *,
        emit_fn: Callable | None = None,
        report_interval_seconds: float = 60.0,
        max_samples_per_bucket: int = 1000,
    ) -> None:
        self._emit_fn = emit_fn
        self._report_interval = report_interval_seconds
        self._max_samples = max_samples_per_bucket
        self._buckets: dict[str, TelemetryBucket] = defaultdict(
            lambda: TelemetryBucket(operation="")
        )
        self._last_report_time = time.monotonic()

    def record(self, operation: str, *, duration_ms: float) -> None:
        """Record a timing sample for an operation."""
        if operation not in self._buckets:
            self._buckets[operation] = TelemetryBucket(operation=operation)
        bucket = self._buckets[operation]
        bucket.samples.append(duration_ms)
        # Evict oldest if over limit
        if len(bucket.samples) > self._max_samples:
            bucket.samples = bucket.samples[-self._max_samples:]

    @asynccontextmanager
    async def measure(self, operation: str) -> AsyncIterator[None]:
        """Context manager for timing an async operation."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record(operation, duration_ms=elapsed_ms)

    def get_report(self) -> dict[str, Any]:
        """Generate a telemetry report from current buckets."""
        report = {
            "timestamp": time.time(),
            "operations": {},
        }
        for op, bucket in self._buckets.items():
            if bucket.count > 0:
                report["operations"][op] = bucket.to_dict()
        return report

    def flush(self) -> dict[str, Any]:
        """Generate report and clear all buckets."""
        report = self.get_report()
        for bucket in self._buckets.values():
            bucket.clear()
        self._last_report_time = time.monotonic()
        return report

    async def maybe_emit_report(self) -> None:
        """Emit a telemetry report if the interval has elapsed."""
        now = time.monotonic()
        if now - self._last_report_time >= self._report_interval:
            report = self.flush()
            if self._emit_fn and report.get("operations"):
                from probos.events import EventType
                self._emit_fn(EventType.TELEMETRY_REPORT, report)
```

### Section 2: Add `TELEMETRY_REPORT` event type

**File:** `src/probos/events.py`

Add after the behavioral metrics events (around line 134):

SEARCH:
```python
    BEHAVIORAL_METRICS_UPDATED = "behavioral_metrics_updated"
```

REPLACE:
```python
    BEHAVIORAL_METRICS_UPDATED = "behavioral_metrics_updated"
    TELEMETRY_REPORT = "telemetry_report"  # AD-461
```

### Section 3: Add `TelemetryConfig` to SystemConfig

**File:** `src/probos/config.py`

Add a simple config class near the other monitoring configs:

```python
class TelemetryConfig(BaseModel):
    """Ship's Telemetry configuration (AD-461)."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    max_samples_per_bucket: int = 1000
```

Add `telemetry: TelemetryConfig = TelemetryConfig()` to `SystemConfig`.
Find the pattern by grepping:
```
grep -n "records:" src/probos/config.py
```

### Section 4: Wire TelemetryService in startup

**File:** `src/probos/startup/cognitive_services.py`

Add telemetry service initialization. Find the module's initialization
section and add before the Oracle Service block:

```python
    # AD-461: Ship's Telemetry
    telemetry_service = None
    if config.telemetry.enabled:
        try:
            from probos.substrate.telemetry import TelemetryService
            telemetry_service = TelemetryService(
                emit_fn=runtime.emit_event if hasattr(runtime, 'emit_event') else None,
                report_interval_seconds=config.telemetry.report_interval_seconds,
                max_samples_per_bucket=config.telemetry.max_samples_per_bucket,
            )
            runtime._telemetry_service = telemetry_service
            logger.info("AD-461: TelemetryService initialized")
        except Exception as e:
            logger.warning("TelemetryService failed to start: %s — continuing without", e)
```

Store on runtime so cognitive agents can access it for timing their
operations. Future ADs will add `telemetry.measure()` wrappers around
LLM calls, trust updates, etc.

### Section 5: Add telemetry API endpoint

**File:** `src/probos/routers/system.py`

Add a `GET /api/telemetry` endpoint that returns the current telemetry report.
Follow the health endpoint pattern (lines 21-35):

```python
@router.get("/api/telemetry")
async def get_telemetry(request: Request) -> dict:
    """Return current telemetry report (AD-461)."""
    runtime = request.app.state.runtime
    telemetry = getattr(runtime, "_telemetry_service", None)
    if not telemetry:
        return {"status": "disabled", "operations": {}}
    return telemetry.get_report()
```

## Tests

**File:** `tests/test_ad461_telemetry.py`

9 tests:

1. `test_telemetry_record` — record 3 samples, verify `get_report()` shows correct count
2. `test_telemetry_bucket_stats` — record [10, 20, 30], verify mean=20, min=10, max=30
3. `test_telemetry_p95` — record 100 samples, verify p95 is approximately correct
4. `test_telemetry_measure_context_manager` — use `async with telemetry.measure("op")`,
   verify a sample was recorded with duration > 0
5. `test_telemetry_flush_clears_buckets` — record, flush, verify buckets are empty
6. `test_telemetry_max_samples_eviction` — set max_samples=5, record 10, verify only 5 kept
7. `test_telemetry_maybe_emit_report` — set interval to 0, record a sample, call
   `maybe_emit_report()`, verify emit_fn was called with `EventType.TELEMETRY_REPORT`
8. `test_telemetry_event_type_exists` — verify `EventType.TELEMETRY_REPORT` exists
9. `test_telemetry_config_defaults` — verify `TelemetryConfig` defaults

## What This Does NOT Change

- No existing timing code is modified — this is a new, additive service
- No automatic instrumentation — operations must explicitly call `record()` or use
  `measure()`. Instrumenting specific operations is deferred to future ADs.
- Does NOT replace VitalsMonitor or IntrospectiveTelemetryService — those track
  different concerns (health metrics vs self-awareness vs operation timing)
- Does NOT add distributed tracing or correlation IDs to telemetry
- Does NOT push telemetry to external systems (Prometheus, etc.)

## Tracking

- `PROGRESS.md`: Add AD-461 as COMPLETE
- `docs/development/roadmap.md`: Update AD-461 status

## Acceptance Criteria

- `TelemetryService` exists with `record()`, `measure()`, `get_report()`, `flush()`
- `EventType.TELEMETRY_REPORT` exists in events.py
- `TelemetryConfig` exists in config.py
- `GET /api/telemetry` endpoint works
- All 9 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# No existing telemetry module
find . -name "*telemetry*" → src/probos/cognitive/introspective_telemetry.py only

# Existing timing patterns
grep -rn "time.perf_counter\|time.monotonic" src/probos/cognitive/ | head -5
  → anomaly_window.py:49, behavioral_monitor.py:51, counselor.py:2070

# VitalsMonitor health metrics
grep -n "collect_metrics" src/probos/agents/medical/vitals_monitor.py
  58: async def collect_metrics(self)

# Events.py insertion point
grep -n "BEHAVIORAL_METRICS" src/probos/events.py
  134: BEHAVIORAL_METRICS_UPDATED = "behavioral_metrics_updated"

# Health endpoint pattern
grep -n "api/health" src/probos/routers/system.py
  21: @router.get("/api/health")

# IntrospectiveTelemetryService (existing, different scope)
grep -n "class Introspective" src/probos/cognitive/introspective_telemetry.py
  23: class IntrospectiveTelemetryService
```
