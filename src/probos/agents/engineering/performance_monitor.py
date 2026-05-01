"""AD-457: Performance Monitor — latency, throughput, memory pressure."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
)

logger = logging.getLogger(__name__)


class PerformanceMonitorAgent(HeartbeatAgent):
    agent_type = "performance_monitor"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="performance_monitor",
            detail="Continuous latency/throughput/memory pressure monitoring",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="performance_alert",
            params={
                "metric": "metric name (latency_p99, throughput, memory_pressure)",
                "value": "current measured value",
                "threshold": "configured threshold",
            },
            description="Alert engineering of a performance threshold breach",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "engineering_performance",
        interval: float = 10.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._latency_p99_max: float = kwargs.get("latency_p99_max", 5.0)
        self._memory_pressure_max: float = kwargs.get("memory_pressure_max", 0.85)
        self._window: deque[dict[str, Any]] = deque(
            maxlen=kwargs.get("window_size", 60),
        )

    async def collect_metrics(self) -> dict[str, Any]:
        rt = self._runtime
        metrics: dict[str, Any] = {
            "timestamp": time.time(),
            "agent_id": self.id,
        }
        if rt is None:
            return metrics
        metrics["active_pools"] = len(getattr(rt, "pools", {}))
        metrics["heartbeat_pulse"] = self._pulse_count
        self._window.append(metrics)
        # v1 collects-and-records only. Real instrumentation (latency_p99,
        # throughput, memory pressure) lives in AD-466 Engineering
        # Infrastructure. AD-457 establishes the agent surface; AD-466 wires
        # the actual signal producers and triggers `_emit_threshold_breach`
        # from a separate evaluator.
        return metrics

    def _emit_threshold_breach(self, metric: str, value: float, threshold: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.PERFORMANCE_THRESHOLD_BREACHED,
                {
                    "metric": metric,
                    "value": value,
                    "threshold": threshold,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-457: PERFORMANCE_THRESHOLD_BREACHED emit failed", exc_info=True,
            )
