"""AD-641a: Observability Bridge -- read-only sensor surface from brain to crew.

The Ship's Computer (brain) owns operational state (vitals, pools, attention).
The Crew (Ward Room agents) read that state via this bridge -- never directly.
Per the AD-641 design doc, this is the interface between nervous system and
consciousness.

Push-based: bridge polls sensors at a configurable cadence, posts a snapshot
summary into a Ward Room system channel, and emits OBSERVABILITY_SNAPSHOT_PUBLISHED
so subscribers can consume the structured payload.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservabilityBridgeSnapshot:
    """Frozen sensor snapshot. The public observation surface for crew agents."""

    captured_at: float
    vitals_summary: dict[str, Any] = field(default_factory=dict)
    pool_health: dict[str, dict[str, Any]] = field(default_factory=dict)
    attention_priorities: list[dict[str, Any]] = field(default_factory=list)


class ObservabilityBridge:
    """v1 read-only sensor bridge.

    Public API:
      - start() -> None  -- begin periodic publishing
      - stop()  -> None  -- cancel publish task
      - async take_snapshot() -> ObservabilityBridgeSnapshot  -- one-shot read
        (async because event_log query is async)
    """

    def __init__(
        self,
        *,
        runtime: Any,
        ward_room: Any | None,
        emit_event: Any | None = None,
        publish_interval_seconds: float = 60.0,
        system_channel: str = "system_observability",
    ) -> None:
        self._runtime = runtime
        self._ward_room = ward_room
        self._emit_event = emit_event
        self._interval = max(1.0, float(publish_interval_seconds))
        self._channel = system_channel
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._stopping = False
        self._task = loop.create_task(
            self._publish_loop(), name="observability_bridge",
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

    async def take_snapshot(self) -> ObservabilityBridgeSnapshot:
        # AD-641a revision: take_snapshot is async because event_log.query_structured
        # is async (verified at src/probos/substrate/event_log.py:170). Pool/attention
        # collectors stay sync -- only vitals reach the event log.
        return ObservabilityBridgeSnapshot(
            captured_at=time.time(),
            vitals_summary=await self._collect_vitals(),
            pool_health=self._collect_pool_health(),
            attention_priorities=self._collect_attention(),
        )

    async def _publish_loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    await self._publish_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # log-and-degrade
                    logger.warning(
                        "AD-641a: observability publish failed; will retry next cycle: %s",
                        exc,
                    )
                    if self._emit_event is not None:
                        try:
                            self._emit_event(
                                EventType.OBSERVABILITY_BRIDGE_FAILED,
                                {"reason": str(exc)},
                            )
                        except Exception:
                            pass
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            return

    async def _publish_once(self) -> None:
        snap = await self.take_snapshot()
        if self._ward_room is None:
            return
        body = self._format_post(snap)
        try:
            await self._ward_room.create_post(
                thread_id=self._channel,
                author_id="system",
                author_callsign="System",
                body=body,
            )
        except Exception as exc:
            logger.warning(
                "AD-641a: ward_room.create_post failed; will retry next cycle: %s",
                exc,
            )
            if self._emit_event is not None:
                try:
                    self._emit_event(
                        EventType.OBSERVABILITY_BRIDGE_FAILED,
                        {"reason": str(exc)},
                    )
                except Exception:
                    pass
            return
        if self._emit_event is not None:
            self._emit_event(
                EventType.OBSERVABILITY_SNAPSHOT_PUBLISHED,
                {
                    "captured_at": snap.captured_at,
                    "pools": list(snap.pool_health.keys()),
                    "attention_count": len(snap.attention_priorities),
                },
            )

    def _format_post(self, snap: ObservabilityBridgeSnapshot) -> str:
        lines = ["[Brain Observability Snapshot]"]
        if snap.vitals_summary:
            lines.append(f"vitals: {snap.vitals_summary}")
        if snap.pool_health:
            lines.append(f"pools: {snap.pool_health}")
        if snap.attention_priorities:
            lines.append(
                f"attention top-{len(snap.attention_priorities)}: "
                f"{snap.attention_priorities}"
            )
        return "\n".join(lines)

    async def _collect_vitals(self) -> dict[str, Any]:
        # AD-641a revision: event_log.query()/query_structured() are async
        # (verified at src/probos/substrate/event_log.py:132, 170). Live query()
        # signature accepts (category=, agent_id=, limit=) only -- there is NO
        # event_type= parameter. Use query_structured(event=...) to filter by
        # event name. Returned rows are dicts (per _row_to_dict at event_log.py:249)
        # with keys including agent_type and data (payload deserialized).
        event_log = getattr(self._runtime, "event_log", None)
        if event_log is None:
            return {}
        try:
            recent = await event_log.query_structured(
                event=EventType.AGENT_STATE.value, limit=20,
            )
        except Exception:
            return {}
        for entry in recent or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("agent_type") == "vitals_monitor":
                data = entry.get("data") or {}
                return dict(data) if isinstance(data, dict) else {}
        return {}

    def _collect_pool_health(self) -> dict[str, dict[str, Any]]:
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

    def _collect_attention(self) -> list[dict[str, Any]]:
        # AD-641a-iv: replace `attn._queue` read with `attn.snapshot()` once the
        # public API lands. v1 ships the private-attribute reach with this TODO
        # so the smell is tracked, not hidden.
        attn = getattr(self._runtime, "attention", None)
        if attn is None:
            return []
        queue = getattr(attn, "_queue", {}) or {}
        items: list[dict[str, Any]] = []
        for task_id, entry in queue.items():
            score = getattr(entry, "score", None)
            items.append(
                {"task_id": str(task_id), "score": float(score) if score is not None else 0.0},
            )
        items.sort(key=lambda x: x["score"], reverse=True)
        return items[:5]
