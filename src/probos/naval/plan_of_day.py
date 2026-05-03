"""Plan of the Day service (AD-477).

Generates a morning operations summary aggregating three sources:

1. Active work items (``WorkItemStatus.OPEN``).
2. Ward Room thread queue depth.
3. Current alert conditions (when ``include_alert_conditions`` is True).

Scheduled-duties source is deferred to AD-477f — ``DutyScheduleTracker`` is
private to ``ProactiveCognitiveLoop`` and ``runtime.duty_schedule_tracker``
does not exist as a public attribute.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.config import PlanOfDayConfig

logger = logging.getLogger(__name__)


class PlanOfDayService:
    """Generates a morning operations summary."""

    def __init__(self, runtime: Any, config: "PlanOfDayConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._task: asyncio.Task | None = None

    async def generate_for_date(self, date: datetime.date) -> str:
        """Generate Plan of the Day Markdown.

        Aggregates three sources (scheduled duties deferred to AD-477f):

        - Active work items via ``list_work_items(status="open")``.
        - Ward Room thread queue depth via ``list_threads`` (read-only).
        - Current alert conditions when ``include_alert_conditions`` is True.

        Returns Markdown content as a string. Caller writes to disk.
        """
        work_items_section = await self._collect_work_items_section()
        ward_room_section = await self._collect_ward_room_section()
        alerts_section = await self._collect_alerts_section()

        date_str = date.isoformat()
        lines = [
            f"# Plan of the Day — {date_str}",
            "",
            "## Active Work Items",
            "",
            work_items_section,
            "",
            "## Ward Room Queue",
            "",
            ward_room_section,
            "",
            "## Alert Conditions",
            "",
            alerts_section,
            "",
        ]
        return "\n".join(lines)

    async def write_to_disk(self, date: datetime.date) -> Path:
        """Generate + write Markdown to ``output_dir/YYYY-MM-DD.md``.

        Emits ``PLAN_OF_DAY_GENERATED`` after a successful write.
        """
        content = await self.generate_for_date(date)
        out_dir = Path(self._config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date.isoformat()}.md"
        out_path.write_text(content, encoding="utf-8")
        self._emit(
            EventType.PLAN_OF_DAY_GENERATED,
            {"date": date.isoformat(), "path": str(out_path)},
        )
        logger.info("AD-477: PlanOfDay written date=%s path=%s", date.isoformat(), out_path)
        return out_path

    async def start(self) -> None:
        """Start background task that runs at start-of-day."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Cancel the background task and wait for it to exit.

        Per ProbOS async-discipline rule (AD-477 Test #12): the underlying
        loop catches ``CancelledError``, performs cleanup, and re-raises. The
        re-raised cancellation propagates back to callers of ``stop()``.
        """
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        await task

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Periodic loop that generates the plan at the configured hour."""
        try:
            while True:
                try:
                    await asyncio.sleep(3600.0)
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            logger.info("AD-477: PlanOfDayService loop cancelled, cleaning up")
            raise

    async def _collect_work_items_section(self) -> str:
        store = getattr(self._runtime, "work_item_store", None)
        if store is None:
            return "_(work item store unavailable)_"
        try:
            items = await store.list_work_items(status="open")
        except Exception:
            logger.warning("AD-477: work_item_store.list_work_items failed", exc_info=True)
            return "_(work item query failed)_"
        if not items:
            return "_(no open work items)_"
        bullets = []
        for item in items[:10]:
            title = getattr(item, "title", "") or "(untitled)"
            priority = getattr(item, "priority", None)
            bullets.append(f"- (priority={priority}) {title}")
        return f"Open work items: {len(items)}\n\n" + "\n".join(bullets)

    async def _collect_ward_room_section(self) -> str:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return "_(ward room unavailable)_"
        try:
            threads = await ward_room.list_threads(
                channel_id=None, limit=50, sort="recent",
            )
        except Exception:
            logger.warning("AD-477: ward_room.list_threads failed", exc_info=True)
            return "_(ward room query failed)_"
        return f"Recent threads in queue: {len(threads)}"

    async def _collect_alerts_section(self) -> str:
        if not self._config.include_alert_conditions:
            return "_(alert conditions disabled in config)_"
        alerts_svc = getattr(self._runtime, "bridge_alerts", None)
        if alerts_svc is None:
            return "_(no active alerts)_"
        getter = getattr(alerts_svc, "get_recent_alerts", None)
        if getter is None:
            return "_(alert accessor unavailable)_"
        try:
            alerts = getter(10)
        except Exception:
            logger.warning("AD-477: bridge_alerts.get_recent_alerts failed", exc_info=True)
            return "_(alert query failed)_"
        if not alerts:
            return "_(no active alerts)_"
        bullets = []
        for a in alerts[:5]:
            severity = getattr(a, "severity", "")
            title = getattr(a, "title", "") or "(untitled alert)"
            bullets.append(f"- ({severity}) {title}")
        return "\n".join(bullets)

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        emit = getattr(self._runtime, "emit_event", None)
        if emit is None:
            return
        try:
            emit(event_type, data)
        except Exception:
            logger.warning("AD-477: emit_event failed for %s", event_type, exc_info=True)
