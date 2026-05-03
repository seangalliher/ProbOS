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
