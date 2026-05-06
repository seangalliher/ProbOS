"""Operational Status Model — reliability metrics for non-crew agents (AD-571b).

Non-crew agents (utility tools, core infrastructure) do not earn Rank — they
maintain Operational Status. This module provides:
- OperationalStatus: AVAILABLE / DEGRADED / OFFLINE / MAINTENANCE.
- ReliabilityMetrics: success rate, p50/p95 latency, error count.
- OperationalStatusTracker: in-memory rolling window per agent.

The tracker is wired alongside AgentTierRegistry at startup. Crew agents are
intentional no-ops (they use Rank via TrustNetwork instead).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class OperationalStatus(StrEnum):
    """Health status for non-crew agents (AD-571b)."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class ReliabilityMetrics:
    """Rolling reliability snapshot computed from a tracker's sample window."""

    sample_count: int
    success_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    consecutive_errors: int


class OperationalStatusTracker:
    """In-memory tracker that records call outcomes for non-crew agents.

    Per-agent ring buffer of (success, latency_ms) tuples. Status is derived
    from rolling metrics and config thresholds; MAINTENANCE is sticky and only
    cleared explicitly via clear_maintenance().
    """

    def __init__(self, config: Any, tier_registry: Any | None = None) -> None:
        # Accept the OperationalStatusConfig pydantic model duck-typed via attrs.
        self._config = config
        self._tier_registry: Any = tier_registry
        # agent_id -> deque[(success: bool, latency_ms: float)]
        self._records: dict[str, deque[tuple[bool, float]]] = {}
        self._maintenance: set[str] = set()

    def set_tier_registry(self, registry: Any) -> None:
        """Late-bind the tier registry (matches AD-571a TrustNetwork pattern)."""
        self._tier_registry = registry

    def _is_crew(self, agent_id: str) -> bool:
        if self._tier_registry is None:
            return False
        try:
            return bool(self._tier_registry.is_crew(agent_id))
        except Exception:
            return False

    def record_call(self, agent_id: str, success: bool, latency_ms: float) -> None:
        """Record a single call outcome. No-op for crew agents (DLog #3)."""
        if self._is_crew(agent_id):
            return
        buf = self._records.get(agent_id)
        if buf is None:
            buf = deque(maxlen=self._config.sample_window_size)
            self._records[agent_id] = buf
        buf.append((bool(success), float(latency_ms)))

    def set_maintenance(self, agent_id: str) -> None:
        """Operator-driven MAINTENANCE flag. Sticky until cleared."""
        self._maintenance.add(agent_id)

    def clear_maintenance(self, agent_id: str) -> None:
        self._maintenance.discard(agent_id)

    def get_metrics(self, agent_id: str) -> ReliabilityMetrics | None:
        """Return rolling metrics, or None if no samples yet."""
        buf = self._records.get(agent_id)
        if not buf:
            return None
        n = len(buf)
        successes = sum(1 for s, _ in buf if s)
        latencies = sorted(lat for _, lat in buf)
        p50 = latencies[n // 2] if n > 0 else 0.0
        p95_idx = min(n - 1, int(0.95 * n)) if n > 0 else 0
        p95 = latencies[p95_idx] if n > 0 else 0.0
        # Consecutive errors counted from the most recent end of the buffer.
        consec = 0
        for s, _ in reversed(buf):
            if s:
                break
            consec += 1
        return ReliabilityMetrics(
            sample_count=n,
            success_rate=successes / n if n else 0.0,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            consecutive_errors=consec,
        )

    def get_status(self, agent_id: str) -> OperationalStatus:
        """Derive status from current metrics + config thresholds."""
        if agent_id in self._maintenance:
            return OperationalStatus.MAINTENANCE
        m = self.get_metrics(agent_id)
        if m is None or m.sample_count == 0:
            return OperationalStatus.AVAILABLE
        if m.consecutive_errors >= self._config.offline_consecutive_errors:
            return OperationalStatus.OFFLINE
        if m.success_rate < self._config.available_success_rate:
            return OperationalStatus.DEGRADED
        if m.p95_latency_ms > self._config.degraded_p95_latency_ms:
            return OperationalStatus.DEGRADED
        return OperationalStatus.AVAILABLE

    def all_statuses(self) -> dict[str, OperationalStatus]:
        """Return current status for every recorded agent."""
        ids = set(self._records) | set(self._maintenance)
        return {a: self.get_status(a) for a in sorted(ids)}
