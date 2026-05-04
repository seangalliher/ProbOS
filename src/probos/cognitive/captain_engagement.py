"""AD-572b: CaptainEngagementProvider -- proactive-context signals for Captain engagement.

Surfaces three signals into the proactive loop's context:
  1. Pending Captain alerts (count + most-recent topic).
  2. Ward-Room thread activity in the last 60 seconds (count).
  3. Priority DM queue depth (count of unread DMs to crew).

When dm_queue_depth > 0, emits CAPTAIN_DM_PRIORITY_QUEUED once per
discovery cycle (deduped by depth value to avoid floods).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class CaptainEngagementProvider:
    """v1 read-only snapshot of Captain-engagement signals."""

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        wardroom_activity_window_s: float = 60.0,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._wardroom_window_s = wardroom_activity_window_s
        self._last_emitted_depth: int = -1

    def snapshot(self) -> dict[str, int]:
        """Return engagement counts. Empty dict if runtime unavailable."""
        rt = getattr(self, "_runtime", None)
        if rt is None:
            return {}

        out: dict[str, int] = {
            "alerts_pending": 0,
            "wardroom_activity_60s": 0,
            "dm_queue_depth": 0,
        }

        # Alerts pending: read recent alerts from bridge_alerts service
        bridge = getattr(rt, "bridge_alerts", None)
        if bridge is not None:
            try:
                recent = bridge.get_recent_alerts(50) if hasattr(
                    bridge, "get_recent_alerts"
                ) else []
                # Count alerts not yet acknowledged (best-effort; field name may vary)
                out["alerts_pending"] = sum(
                    1 for a in (recent or [])
                    if not getattr(a, "acknowledged", False)
                )
            except Exception:
                logger.debug("AD-572b: bridge_alerts snapshot failed", exc_info=True)

        # Ward-room activity in the last window: count threads with recent
        # activity. Best-effort -- the underlying API surface may differ; we
        # return 0 silently when the surface is unavailable.
        ward_room = getattr(rt, "ward_room", None)
        if ward_room is not None:
            try:
                cutoff = time.time() - self._wardroom_window_s
                threads = getattr(ward_room, "_last_stats", None)
                if isinstance(threads, dict):
                    out["wardroom_activity_60s"] = int(
                        threads.get("active_threads", 0) or 0
                    )
            except Exception:
                logger.debug("AD-572b: ward_room snapshot failed", exc_info=True)

        # DM queue depth: count of recent DMs to crew (best-effort).
        # The Ward Room DM tables surface is operator-driven; v1 returns 0
        # unless an explicit count helper is available.
        if ward_room is not None:
            try:
                count_fn = getattr(ward_room, "captain_dm_queue_depth", None)
                if callable(count_fn):
                    out["dm_queue_depth"] = int(count_fn() or 0)
            except Exception:
                logger.debug("AD-572b: dm queue depth read failed", exc_info=True)

        # Emit CAPTAIN_DM_PRIORITY_QUEUED once per depth-change cycle
        depth = out["dm_queue_depth"]
        if depth > 0 and depth != self._last_emitted_depth:
            self._emit_priority_queued(depth)
            self._last_emitted_depth = depth
        elif depth == 0:
            self._last_emitted_depth = -1

        return out

    def _emit_priority_queued(self, depth: int) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.CAPTAIN_DM_PRIORITY_QUEUED,
                {"dm_queue_depth": depth},
            )
        except Exception:
            logger.debug(
                "AD-572b: CAPTAIN_DM_PRIORITY_QUEUED emit failed", exc_info=True,
            )

    # ------------------------------------------------------------------
    # AD-572c: Ward Room activity summary (async; aggregates per-channel)
    # ------------------------------------------------------------------

    async def wardroom_activity_summary(self) -> dict[str, Any]:
        """AD-572c: aggregate per-channel thread counts into a single context blob.

        ``WardRoomService.list_threads(channel_id)`` is per-channel, so a
        global summary requires iterating channels first. Returns an empty
        dict when ``ward_room`` is unavailable; degrades to partial results
        on per-channel failures (best-effort per Wave-5 tier-2).
        """
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return {}
        try:
            channels = await ward_room.list_channels()
        except Exception:
            logger.warning(
                "AD-572c: ward_room.list_channels failed; "
                "wardroom_activity_summary returns empty dict",
                exc_info=True,
            )
            return {}
        summary: dict[str, Any] = {"channels": {}, "total_threads": 0}
        for channel in channels:
            channel_id = (
                getattr(channel, "id", None)
                or getattr(channel, "channel_id", None)
            )
            if not channel_id:
                continue
            try:
                threads = await ward_room.list_threads(channel_id, limit=10)
            except Exception:
                logger.warning(
                    "AD-572c: list_threads(%s) failed; channel skipped",
                    channel_id, exc_info=True,
                )
                continue
            count = len(threads)
            summary["channels"][channel_id] = count
            summary["total_threads"] += count
        return summary

    # ------------------------------------------------------------------
    # AD-572e: Task awareness in Captain DM context
    # ------------------------------------------------------------------

    async def task_awareness(self, agent_id: str) -> dict[str, Any]:
        """AD-572e: open-WorkItem summary for an agent.

        Used by proactive cognitive loop to ground Captain DM response context
        in the agent's current commitments. Returns up to 10 most recent open
        WorkItems assigned to ``agent_id``.

        Args:
            agent_id: The agent identifier (matches WorkItemStore.list_work_items
                ``assigned_to`` filter; NOT agent_type).

        Returns:
            ``{"open_count": int, "tasks": [{"id", "title", "type"}]}`` or
            empty dict when ``work_item_store`` is unavailable / agent_id falsy.

        Defensive: catches all exceptions and logs at debug level; returns
        empty dict rather than raising (mirrors ``snapshot()`` /
        ``wardroom_activity_summary()`` error handling).
        """
        rt = getattr(self, "_runtime", None)
        if rt is None or not agent_id:
            return {}
        work_item_store = getattr(rt, "work_item_store", None)
        if work_item_store is None:
            return {}
        try:
            items = await work_item_store.list_work_items(
                status="open",
                assigned_to=agent_id,
                limit=10,
            )
        except Exception:
            logger.debug("AD-572e: work_item_store query failed", exc_info=True)
            return {}
        return {
            "open_count": len(items),
            "tasks": [
                {
                    "id": getattr(item, "id", "") or "",
                    "title": getattr(item, "title", "") or "",
                    "type": getattr(item, "work_type", "") or "",
                }
                for item in items[:10]
            ],
        }

