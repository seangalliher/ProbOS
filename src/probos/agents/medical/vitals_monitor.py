"""VitalsMonitorAgent — continuous health pulse for the medical pool (AD-290).

Subclasses HeartbeatAgent to collect system-wide health metrics every heartbeat
cycle.  When thresholds are breached, broadcasts a ``medical_alert`` intent
for the Diagnostician to triage.

No LLM calls — pure metric collection.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import (
    AgentState,
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
)

logger = logging.getLogger(__name__)


class VitalsMonitorAgent(HeartbeatAgent):
    agent_type = "vitals_monitor"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(can="vitals_monitor", detail="Continuous system health monitoring"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="medical_alert",
            params={
                "severity": "warning or critical",
                "metric": "metric name that breached threshold",
                "current_value": "current metric value",
                "threshold": "threshold that was breached",
                "affected": "pool name or agent IDs affected",
            },
            description="Alert the medical team of a health anomaly",
        ),
    ]
    initial_confidence = 0.95

    def __init__(self, pool: str = "medical", interval: float = 5.0, **kwargs: Any) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._window: deque[dict[str, Any]] = deque(maxlen=kwargs.get("window_size", 12))
        self._pool_health_min: float = kwargs.get("pool_health_min", 0.5)
        self._trust_floor: float = kwargs.get("trust_floor", 0.3)
        self._health_floor: float = kwargs.get("health_floor", 0.6)
        self._max_trust_outliers: int = kwargs.get("max_trust_outliers", 3)

    async def collect_metrics(self) -> dict[str, Any]:
        """Collect system-wide health metrics."""
        metrics: dict[str, Any] = {
            "pulse": self._pulse_count,
            "agent_id": self.id,
            "timestamp": time.time(),
        }

        rt = self._runtime
        if rt is None:
            return metrics

        # Pool health ratios
        pool_health: dict[str, float] = {}
        for pool_name, pool in rt.pools.items():
            target = pool.target_size
            active = len([
                a for a in pool.healthy_agents
                if (getattr(a, "state", None) == AgentState.ACTIVE
                    if hasattr(a, "state") else True)
            ])
            pool_health[pool_name] = active / target if target > 0 else 1.0
        metrics["pool_health"] = pool_health

        # Trust statistics
        scores = rt.trust_network.all_scores()
        if scores:
            score_vals = list(scores.values())
            metrics["trust_mean"] = sum(score_vals) / len(score_vals)
            metrics["trust_min"] = min(score_vals)
            metrics["trust_outliers"] = [
                aid for aid, s in scores.items() if s < self._trust_floor
            ]
        else:
            metrics["trust_mean"] = 1.0
            metrics["trust_min"] = 1.0
            metrics["trust_outliers"] = []

        # Dream state
        if rt.dream_scheduler:
            metrics["is_dreaming"] = rt.dream_scheduler._is_dreaming if hasattr(rt.dream_scheduler, "_is_dreaming") else False
        else:
            metrics["is_dreaming"] = False

        # Attention queue depth
        if hasattr(rt, "attention") and rt.attention:
            metrics["attention_queue"] = rt.attention.queue_size
        else:
            metrics["attention_queue"] = 0

        # Overall system health (mean confidence of ACTIVE agents)
        all_agents = rt.registry.all()
        active_confs = [
            a.confidence for a in all_agents
            if getattr(a, "state", None) == AgentState.ACTIVE
        ]
        metrics["system_health"] = (
            sum(active_confs) / len(active_confs) if active_confs else 1.0
        )

        # AD-557: Cached emergence metrics (read-only from last dream cycle)
        emergence_engine = getattr(rt, "_emergence_metrics_engine", None)
        if emergence_engine:
            snap = emergence_engine.latest_snapshot
            if snap:
                metrics["emergence_capacity"] = snap.emergence_capacity
                metrics["coordination_balance"] = snap.coordination_balance

        # Store in sliding window
        self._window.append(metrics)

        # Check thresholds and emit alerts
        await self._check_thresholds(metrics, rt)

        return metrics

    async def scan_now(self) -> dict[str, Any]:
        """On-demand metric snapshot for the Diagnostician (AD-350).

        Unlike the periodic heartbeat, this does NOT check thresholds or
        emit alerts — it simply collects and returns the current metrics.
        """
        metrics: dict[str, Any] = {
            "pulse": self._pulse_count,
            "agent_id": self.id,
            "timestamp": time.time(),
        }

        rt = self._runtime
        if rt is None:
            return metrics

        # Pool health ratios
        pool_health: dict[str, float] = {}
        for pool_name, pool in rt.pools.items():
            target = pool.target_size
            active = len([
                a for a in pool.healthy_agents
                if (getattr(a, "state", None) == AgentState.ACTIVE
                    if hasattr(a, "state") else True)
            ])
            pool_health[pool_name] = active / target if target > 0 else 1.0
        metrics["pool_health"] = pool_health

        # Trust statistics
        scores = rt.trust_network.all_scores()
        if scores:
            score_vals = list(scores.values())
            metrics["trust_mean"] = sum(score_vals) / len(score_vals)
            metrics["trust_min"] = min(score_vals)
            metrics["trust_outliers"] = [
                aid for aid, s in scores.items() if s < self._trust_floor
            ]
        else:
            metrics["trust_mean"] = 1.0
            metrics["trust_min"] = 1.0
            metrics["trust_outliers"] = []

        # Dream state
        if rt.dream_scheduler:
            metrics["is_dreaming"] = rt.dream_scheduler._is_dreaming if hasattr(rt.dream_scheduler, "_is_dreaming") else False
        else:
            metrics["is_dreaming"] = False

        # Attention queue depth
        if hasattr(rt, "attention") and rt.attention:
            metrics["attention_queue"] = rt.attention.queue_size
        else:
            metrics["attention_queue"] = 0

        # Overall system health
        all_agents = rt.registry.all()
        active_confs = [
            a.confidence for a in all_agents
            if getattr(a, "state", None) == AgentState.ACTIVE
        ]
        metrics["system_health"] = (
            sum(active_confs) / len(active_confs) if active_confs else 1.0
        )

        # Include recent window history if available
        if self._window:
            metrics["recent_history"] = list(self._window)

        return metrics

    async def _check_thresholds(self, metrics: dict[str, Any], rt: Any) -> None:
        """Check metrics against thresholds and broadcast alerts if breached."""
        alerts: list[dict[str, Any]] = []

        # Pool health check
        for pool_name, ratio in metrics.get("pool_health", {}).items():
            if pool_name == "medical":
                continue  # Don't alert on ourselves
            if ratio < self._pool_health_min:
                alerts.append({
                    "severity": "critical" if ratio < 0.25 else "warning",
                    "metric": "pool_health",
                    "current_value": ratio,
                    "threshold": self._pool_health_min,
                    "affected": pool_name,
                    "timestamp": metrics["timestamp"],
                })

        # Trust outliers
        outliers = metrics.get("trust_outliers", [])
        if len(outliers) > self._max_trust_outliers:
            alerts.append({
                "severity": "warning",
                "metric": "trust_outlier",
                "current_value": len(outliers),
                "threshold": self._max_trust_outliers,
                "affected": outliers,
                "timestamp": metrics["timestamp"],
            })

        # System health
        sys_health = metrics.get("system_health", 1.0)
        if sys_health < self._health_floor:
            alerts.append({
                "severity": "critical" if sys_health < 0.3 else "warning",
                "metric": "system_health",
                "current_value": sys_health,
                "threshold": self._health_floor,
                "affected": "system",
                "timestamp": metrics["timestamp"],
            })

        # Broadcast alerts via intent bus
        for alert_data in alerts:
            intent = IntentMessage(
                intent="medical_alert",
                params=alert_data,
            )
            try:
                await rt.intent_bus.broadcast(intent, timeout=5.0)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)

    @property
    def window(self) -> list[dict[str, Any]]:
        """Return the sliding window of recent metrics."""
        return list(self._window)

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    @property
    def latest_vitals(self) -> dict | None:
        """Return the most recent vitals snapshot, or None."""
        if self._window:
            return self._window[-1]
        return None

    @property
    def vitals_window(self) -> list:
        """Return a copy of the vitals history window."""
        return list(self._window)
