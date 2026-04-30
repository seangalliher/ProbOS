"""Ship's Telemetry — centralized operation timing (AD-461).

Collects timing samples for key operations and emits periodic
TELEMETRY_REPORT events with min/max/mean/p95 aggregations.
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable


@dataclass(frozen=True)
class TelemetrySample:
    """A single timing sample."""

    operation: str
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
    """Centralized operation timing collector (AD-461)."""

    def __init__(
        self,
        *,
        emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
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
        report: dict[str, Any] = {
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
