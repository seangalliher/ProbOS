"""Captain's Log service (AD-477).

Synthesizes a daily Markdown narrative aggregating three sources:

1. Top-N episodes from episodic memory (importance >= threshold) for the date.
2. Ward Room thread highlights (recent threads with activity on the date).
3. Active work item summary (WorkItemStatus.OPEN).

Dream-consolidation source is deferred to AD-477g — ``runtime.dreaming_engine``
is not a public attribute and ``runtime.dream_scheduler`` exposes no
recent-summaries accessor.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.config import CaptainsLogConfig

logger = logging.getLogger(__name__)


def _install_root() -> Path:
    """AD-1025b: the ProbOS install/repo root. ``src/probos/naval/captains_log.py``
    -> ``parents[3]`` (captains_log->naval->probos->src->root). Mirrors
    ``__main__.py``'s ``project_root`` and ``piper_backend._probos_root`` (the
    bundled ``tools/`` anchor). NEVER the CWD."""
    return Path(__file__).resolve().parents[3]


def _anchor_under_root(configured) -> Path:
    """AD-1025b: absolute configured path used as-is; a relative one is anchored
    under the install root (NOT the CWD). Mirrors ``piper_backend._anchor_path``."""
    p = Path(configured)
    return p.resolve() if p.is_absolute() else (_install_root() / p).resolve()


class CaptainsLogService:
    """Synthesizes daily narrative from episodic memory + Ward Room + work items."""

    def __init__(self, runtime: Any, config: "CaptainsLogConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._task: asyncio.Task | None = None

    async def generate_for_date(self, date: datetime.date) -> str:
        """Generate Captain's Log Markdown for the given date.

        Aggregates three sources (dream consolidation deferred to AD-477g):

        - Top N episodes from episodic memory: ``recent(k=top_episodes_count*4)``
          over-fetch + Python-side ``[date_start, date_end]`` UTC-midnight filter
          + ``importance >= importance_threshold`` filter + sort by importance
          descending, then take ``top_episodes_count``.
        - Ward Room thread highlights via ``list_threads`` (read-only).
        - Active work item summary via ``list_work_items(status="open")``.

        Returns the Markdown content as a string. Caller writes to disk.
        """
        episodes_section = await self._collect_episodes_section(date)
        ward_room_section = await self._collect_ward_room_section(date)
        work_items_section = await self._collect_work_items_section()

        date_str = date.isoformat()
        lines = [
            f"# Captain's Log — {date_str}",
            "",
            "## Top Episodes",
            "",
            episodes_section,
            "",
            "## Ward Room Activity",
            "",
            ward_room_section,
            "",
            "## Active Work Items",
            "",
            work_items_section,
            "",
        ]
        return "\n".join(lines)

    async def write_to_disk(self, date: datetime.date) -> Path:
        """Generate + write Markdown to ``output_dir/YYYY-MM-DD.md``.

        Emits ``CAPTAINS_LOG_GENERATED`` after a successful write.
        """
        content = await self.generate_for_date(date)
        out_dir = _anchor_under_root(self._config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date.isoformat()}.md"
        out_path.write_text(content, encoding="utf-8")
        self._emit(
            EventType.CAPTAINS_LOG_GENERATED,
            {"date": date.isoformat(), "path": str(out_path)},
        )
        logger.info("AD-477: CaptainsLog written date=%s path=%s", date.isoformat(), out_path)
        return out_path

    async def start(self) -> None:
        """Start background task that runs at end-of-day."""
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
        """Periodic loop that generates the log at the configured hour."""
        try:
            while True:
                try:
                    await asyncio.sleep(3600.0)
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            logger.info("AD-477: CaptainsLogService loop cancelled, cleaning up")
            raise

    async def _collect_episodes_section(self, date: datetime.date) -> str:
        episodic = getattr(self._runtime, "episodic_memory", None)
        if episodic is None:
            return "_(episodic memory unavailable)_"
        top_n = self._config.top_episodes_count
        threshold = self._config.importance_threshold
        try:
            episodes = await episodic.recent(k=top_n * 4)
        except Exception:
            logger.warning("AD-477: episodic.recent failed; rendering empty section", exc_info=True)
            return "_(episodic memory query failed)_"
        date_start = datetime.datetime(date.year, date.month, date.day, tzinfo=datetime.timezone.utc).timestamp()
        date_end = date_start + 86400.0
        filtered = [
            ep for ep in episodes
            if date_start <= float(getattr(ep, "timestamp", 0.0) or 0.0) < date_end
            and int(getattr(ep, "importance", 0) or 0) >= threshold
        ]
        filtered.sort(key=lambda e: int(getattr(e, "importance", 0) or 0), reverse=True)
        top = filtered[:top_n]
        if not top:
            return "_(no episodes met the importance threshold for this date)_"
        bullets = []
        for ep in top:
            summary = getattr(ep, "user_input", "") or ""
            summary = summary.strip().replace("\n", " ")[:120]
            importance = int(getattr(ep, "importance", 0) or 0)
            bullets.append(f"- (importance={importance}) {summary}")
        return "\n".join(bullets)

    async def _collect_ward_room_section(self, date: datetime.date) -> str:
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
        date_start = datetime.datetime(date.year, date.month, date.day, tzinfo=datetime.timezone.utc).timestamp()
        date_end = date_start + 86400.0
        same_day = [
            t for t in threads
            if date_start <= float(getattr(t, "last_activity", 0.0) or 0.0) < date_end
        ]
        if not same_day:
            return f"_(no Ward Room thread activity on {date.isoformat()})_"
        topics = [getattr(t, "title", "") or "(untitled)" for t in same_day[:5]]
        bullets = "\n".join(f"- {t}" for t in topics)
        return f"Threads with activity: {len(same_day)}\n\nTop topics:\n{bullets}"

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
        return f"Open work items: {len(items)}"

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        emit = getattr(self._runtime, "emit_event", None)
        if emit is None:
            return
        try:
            emit(event_type, data)
        except Exception:
            logger.warning("AD-477: emit_event failed for %s", event_type, exc_info=True)
