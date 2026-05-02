"""AD-467: Resource Allocator -- cross-pool capacity reporting."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


class ResourceAllocatorAgent(HeartbeatAgent):
    agent_type = "operations_resource_allocator"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="resource_allocation",
            detail="Cross-pool capacity reporting and allocation suggestions",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="resource_status",
            params={"pool": "pool name (or 'all')"},
            description="Report active/target/saturation for a pool or all pools",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "operations_resource",
        interval: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._last_emit_at: float = 0.0
        self._emit_interval_seconds: float = float(
            kwargs.get("emit_interval_seconds", 60.0)
        )

    async def collect_metrics(self) -> dict[str, Any]:
        rt = self._runtime
        metrics: dict[str, Any] = {
            "timestamp": time.time(),
            "agent_id": self.id,
        }
        if rt is None:
            return metrics
        pools = getattr(rt, "pools", {}) or {}
        capacity: dict[str, dict[str, int]] = {}
        for pool_name, pool_obj in pools.items():
            try:
                # AD-467: ResourcePool.current_size is a @property at pool.py:53;
                # ResourcePool.target_size is an instance attribute at pool.py:42.
                # Both are public (verified). Defensive getattr with 0 fallback
                # for test stubs that don't expose them.
                target = int(getattr(pool_obj, "target_size", 0) or 0)
                active = int(getattr(pool_obj, "current_size", 0) or 0)
                capacity[pool_name] = {
                    "active": active,
                    "target": target,
                }
            except Exception:
                continue
        metrics["capacity"] = capacity
        now = time.time()
        if now - self._last_emit_at >= self._emit_interval_seconds:
            self._emit_allocation(capacity, now)
            self._last_emit_at = now
        return metrics

    def _emit_allocation(self, capacity: dict[str, dict[str, int]], at: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.RESOURCE_ALLOCATED,
                {
                    "capacity": capacity,
                    "reported_at": at,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-467: RESOURCE_ALLOCATED emit failed", exc_info=True,
            )
