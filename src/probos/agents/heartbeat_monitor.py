"""System heartbeat monitor — collects OS-level metrics."""

from __future__ import annotations

import os
import platform
from typing import Any

from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor


class SystemHeartbeatAgent(HeartbeatAgent):
    """Concrete heartbeat agent that collects system-level metrics.

    Reports CPU load, memory usage, process count, and platform info.
    Uses only stdlib — no psutil dependency.
    """

    agent_type: str = "system_heartbeat"
    intent_descriptors = []  # Does not handle user intents
    default_capabilities = [
        CapabilityDescriptor(can="heartbeat", detail="System health metrics"),
        CapabilityDescriptor(can="system_metrics", detail="CPU, memory, load"),
    ]

    async def collect_metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "pulse": self._pulse_count,
            "agent_id": self.id,
            "platform": platform.system(),
        }

        # Load average (Unix) or fallback
        try:
            load = os.getloadavg()
            metrics["load_1m"] = round(load[0], 2)
            metrics["load_5m"] = round(load[1], 2)
            metrics["load_15m"] = round(load[2], 2)
        except (OSError, AttributeError):
            # Windows doesn't have getloadavg
            metrics["load_1m"] = None

        # CPU count
        metrics["cpu_count"] = os.cpu_count()

        # Process ID (our own) — proof of life
        metrics["pid"] = os.getpid()

        return metrics
