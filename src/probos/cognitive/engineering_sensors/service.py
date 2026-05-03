"""AD-641f: EngineeringSensorService -- read-only observation for LaForge.

v1 surfaces three Category D sensors as a structured bundle:
  - pool_summary    -- per-pool current/target sizes
  - capability_summary -- agent_count + capability count
  - gossip_summary  -- view_size + peer count

Optional periodic report() emits ENGINEERING_SENSOR_REPORT.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from probos.cognitive.engineering_sensors.bundle import EngineeringSensorBundle
from probos.events import EventType

logger = logging.getLogger(__name__)


class EngineeringSensorService:
    """Public API:
    - take_snapshot() -> EngineeringSensorBundle
    - report()        -> None  (one-shot emit)
    - start()         -> None  (begin periodic emit)
    - stop()          -> None  (cancel periodic task)
    """

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        report_interval_seconds: float = 60.0,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._interval = max(1.0, float(report_interval_seconds))
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def take_snapshot(self) -> EngineeringSensorBundle:
        return EngineeringSensorBundle(
            captured_at=time.time(),
            pool_summary=self._collect_pools(),
            capability_summary=self._collect_capabilities(),
            gossip_summary=self._collect_gossip(),
        )

    def report(self) -> None:
        snap = self.take_snapshot()
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.ENGINEERING_SENSOR_REPORT,
                {
                    "captured_at": snap.captured_at,
                    "pools": list(snap.pool_summary.keys()),
                    "capability_agents": snap.capability_summary.get("agent_count", 0),
                    "gossip_view_size": snap.gossip_summary.get("view_size", 0),
                },
            )
        except Exception:
            logger.warning("AD-641f: report emit failed", exc_info=True)

    async def start(self) -> None:
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
        self._task = loop.create_task(
            self._report_loop(), name="engineering_sensor_report",
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self._task = None

    async def _report_loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    self.report()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "AD-641f: periodic report failed; continuing",
                        exc_info=True,
                    )
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    def _collect_pools(self) -> dict[str, dict[str, Any]]:
        spawner = getattr(self._runtime, "spawner", None)
        if spawner is None:
            return {}
        pools = getattr(spawner, "pools", {}) or {}
        out: dict[str, dict[str, Any]] = {}
        for name, pool in pools.items():
            current = getattr(pool, "current_size", None)
            target = getattr(pool, "target_size", None)
            out[str(name)] = {
                "current_size": current if current is not None else 0,
                "target_size": target if target is not None else 0,
            }
        return out

    def _collect_capabilities(self) -> dict[str, Any]:
        registry = getattr(self._runtime, "capability_registry", None)
        if registry is None:
            return {"agent_count": 0, "intents": []}
        agent_count = int(getattr(registry, "agent_count", 0) or 0)
        intents: list[str] = []
        try:
            all_caps = registry.get_all_capabilities() or {}
            # AD-641f: get_all_capabilities() returns {agent_id: [CapabilityDescriptor, ...]}
            # -- keys are agent IDs, NOT intent strings. Flatten descriptors to recover
            # the union of intent labels (`cap.can`).
            if isinstance(all_caps, dict):
                seen: set[str] = set()
                for caps in all_caps.values():
                    for cap in caps or []:
                        can = getattr(cap, "can", None)
                        if can:
                            seen.add(str(can))
                intents = sorted(seen)
        except Exception:
            intents = []
        return {"agent_count": agent_count, "intents": intents}

    def _collect_gossip(self) -> dict[str, Any]:
        gossip = getattr(self._runtime, "gossip", None)
        if gossip is None:
            return {"view_size": 0, "peer_count": 0}
        view_size = int(getattr(gossip, "view_size", 0) or 0)
        try:
            view = gossip.get_view() or {}
            peer_count = len(view)
        except Exception:
            peer_count = 0
        return {"view_size": view_size, "peer_count": peer_count}
