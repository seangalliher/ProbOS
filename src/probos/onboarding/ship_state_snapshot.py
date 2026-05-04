"""Ship State Snapshot for Cold-Start Onboarding (AD-683 v1).

Observational aggregator that captures the ship's current operational state
(departments, open work, recent Ward Room topics, alert condition, uptime)
into one frozen ``ShipStateSnapshot`` for injection into a cold-start agent's
first user-message.

v1 ships builder + capture-at-activation + DM-path render. Per-agent
personalization (AD-683b), snapshot deltas/refreshes (AD-683c), federation
sync (AD-683d), chain-path injection (AD-683e) are all deferred.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


_MAX_OPEN_WORK_ITEMS: int = 5
_MAX_TOPIC_CHANNELS: int = 3
_MAX_THREAD_TITLES_PER_CHANNEL: int = 3
_TITLE_TRUNCATE_CHARS: int = 80


def _truncate(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= _TITLE_TRUNCATE_CHARS:
        return text
    return text[: _TITLE_TRUNCATE_CHARS - 1] + "…"


@dataclass(frozen=True)
class DepartmentSummary:
    """Per-department crew presence summary. AD-683 v1."""

    department_id: str
    name: str
    crew_count: int


@dataclass(frozen=True)
class WardRoomTopicSummary:
    """Recent thread titles in one Ward Room channel. AD-683 v1."""

    channel_name: str
    thread_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShipStateSnapshot:
    """Cold-start orientation snapshot. AD-683 v1.

    Defaulted-field-ordering: ``captured_at`` is the sole non-defaulted field
    and comes first, per the standing frozen-dataclass convention.
    """

    captured_at: float
    vessel_name: str = "ProbOS"
    alert_condition: str = "GREEN"
    uptime_seconds: float = 0.0
    active_crew_count: int = 0
    departments: tuple[DepartmentSummary, ...] = ()
    open_work_item_count: int = 0
    open_work_item_titles: tuple[str, ...] = ()
    recent_ward_room_topics: tuple[WardRoomTopicSummary, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "vessel_name": self.vessel_name,
            "alert_condition": self.alert_condition,
            "uptime_seconds": self.uptime_seconds,
            "active_crew_count": self.active_crew_count,
            "departments": [
                {"department_id": d.department_id, "name": d.name, "crew_count": d.crew_count}
                for d in self.departments
            ],
            "open_work_item_count": self.open_work_item_count,
            "open_work_item_titles": list(self.open_work_item_titles),
            "recent_ward_room_topics": [
                {"channel_name": t.channel_name, "thread_titles": list(t.thread_titles)}
                for t in self.recent_ward_room_topics
            ],
        }

    def render_text(self) -> str:
        """Render as a Markdown-style block for prompt injection."""
        lines: list[str] = []
        lines.append(
            f"Vessel: {self.vessel_name}  |  Alert: {self.alert_condition}  "
            f"|  Uptime: {int(self.uptime_seconds)}s  |  Active crew: {self.active_crew_count}"
        )
        if self.departments:
            dept_str = ", ".join(
                f"{d.name} ({d.crew_count})" for d in self.departments
            )
            lines.append(f"Departments: {dept_str}")
        if self.open_work_item_count > 0:
            lines.append(f"Open work items: {self.open_work_item_count}")
            for title in self.open_work_item_titles:
                lines.append(f"  - {title}")
        else:
            lines.append("Open work items: none")
        if self.recent_ward_room_topics:
            lines.append("Recent Ward Room topics:")
            for topic in self.recent_ward_room_topics:
                if topic.thread_titles:
                    titles = "; ".join(topic.thread_titles)
                    lines.append(f"  [{topic.channel_name}] {titles}")
                else:
                    lines.append(f"  [{topic.channel_name}] (no recent threads)")
        return "\n".join(lines)


class ShipStateSnapshotBuilder:
    """Aggregates ship state from runtime collectors. AD-683 v1.

    Read-only observational. Each per-source collector is wrapped in
    try/except → ``logger.warning`` + degraded default. Builder never
    raises; ``build()`` always returns a (possibly partial) snapshot.

    Mirrors AD-508 ``DutyScopeProvider`` ctor shape:
    ``__init__(runtime, *, emit_event=None)``.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self.emit_event = emit_event

    async def build(self) -> ShipStateSnapshot:
        captured_at = time.time()
        vessel_name, alert_condition, uptime_seconds, active_crew_count = (
            self._collect_vessel()
        )
        departments = self._collect_departments()
        open_work_item_count, open_work_item_titles = await self._collect_work_items()
        recent_ward_room_topics = await self._collect_ward_room_topics()

        snap = ShipStateSnapshot(
            captured_at=captured_at,
            vessel_name=vessel_name,
            alert_condition=alert_condition,
            uptime_seconds=uptime_seconds,
            active_crew_count=active_crew_count,
            departments=departments,
            open_work_item_count=open_work_item_count,
            open_work_item_titles=open_work_item_titles,
            recent_ward_room_topics=recent_ward_room_topics,
        )
        self._emit_captured(snap)
        return snap

    # ------------------------------------------------------------------
    # Collectors — each returns a degraded default on failure.
    # ------------------------------------------------------------------

    def _collect_vessel(self) -> tuple[str, str, float, int]:
        ontology = getattr(self._runtime, "ontology", None)
        if ontology is None:
            return ("ProbOS", "GREEN", 0.0, 0)
        try:
            identity = ontology.get_vessel_identity()
            state = ontology.get_vessel_state()
            return (
                identity.name,
                state.alert_condition,
                state.uptime_seconds,
                state.active_crew_count,
            )
        except Exception:
            logger.warning(
                "AD-683: vessel identity/state collection failed; "
                "snapshot uses defaults",
                exc_info=True,
            )
            return ("ProbOS", "GREEN", 0.0, 0)

    def _collect_departments(self) -> tuple[DepartmentSummary, ...]:
        ontology = getattr(self._runtime, "ontology", None)
        if ontology is None:
            return ()
        try:
            depts = ontology.get_departments()
        except Exception:
            logger.warning(
                "AD-683: ontology.get_departments failed; snapshot omits departments",
                exc_info=True,
            )
            return ()
        crew_count_by_dept: dict[str, int] = {}
        try:
            for agent_type in ontology.get_crew_agent_types():
                assignment = ontology.get_assignment_for_agent(agent_type)
                if assignment is None or assignment.agent_id is None:
                    continue
                post = ontology.get_post_for_agent(agent_type)
                if post is None:
                    continue
                dept_id = getattr(post, "department_id", "")
                if dept_id:
                    crew_count_by_dept[dept_id] = (
                        crew_count_by_dept.get(dept_id, 0) + 1
                    )
        except Exception:
            logger.warning(
                "AD-683: department crew-count derivation failed; counts default to 0",
                exc_info=True,
            )
        summaries: list[DepartmentSummary] = []
        for d in depts:
            summaries.append(
                DepartmentSummary(
                    department_id=d.id,
                    name=d.name,
                    crew_count=crew_count_by_dept.get(d.id, 0),
                )
            )
        return tuple(summaries)

    async def _collect_work_items(self) -> tuple[int, tuple[str, ...]]:
        store = getattr(self._runtime, "work_item_store", None)
        if store is None:
            return (0, ())
        try:
            items = await store.list_work_items(status="open", limit=_MAX_OPEN_WORK_ITEMS)
        except Exception:
            logger.warning(
                "AD-683: work_item_store.list_work_items failed; snapshot omits work items",
                exc_info=True,
            )
            return (0, ())
        if not items:
            return (0, ())
        titles = tuple(_truncate(getattr(it, "title", "") or "(untitled)") for it in items)
        return (len(items), titles)

    async def _collect_ward_room_topics(self) -> tuple[WardRoomTopicSummary, ...]:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return ()
        try:
            channels = await ward_room.list_channels()
        except Exception:
            logger.warning(
                "AD-683: ward_room.list_channels failed; snapshot omits topics",
                exc_info=True,
            )
            return ()
        topics: list[WardRoomTopicSummary] = []
        for channel in channels[:_MAX_TOPIC_CHANNELS]:
            try:
                threads = await ward_room.list_threads(
                    channel.id,
                    limit=_MAX_THREAD_TITLES_PER_CHANNEL,
                    sort="recent",
                )
            except Exception:
                logger.warning(
                    "AD-683: ward_room.list_threads failed for channel=%s; skipping",
                    getattr(channel, "name", "?"),
                    exc_info=True,
                )
                continue
            titles = tuple(
                _truncate(getattr(t, "title", "") or "(untitled)") for t in threads
            )
            topics.append(
                WardRoomTopicSummary(
                    channel_name=getattr(channel, "name", "") or channel.id,
                    thread_titles=titles,
                )
            )
        return tuple(topics)

    # ------------------------------------------------------------------

    def _emit_captured(self, snap: ShipStateSnapshot) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.SHIP_STATE_SNAPSHOT_CAPTURED,
                {
                    "captured_at": snap.captured_at,
                    "alert_condition": snap.alert_condition,
                    "work_item_count": snap.open_work_item_count,
                    "dept_count": len(snap.departments),
                    "topic_count": len(snap.recent_ward_room_topics),
                },
            )
        except Exception:
            logger.warning(
                "AD-683: emit_event for SHIP_STATE_SNAPSHOT_CAPTURED failed",
                exc_info=True,
            )
