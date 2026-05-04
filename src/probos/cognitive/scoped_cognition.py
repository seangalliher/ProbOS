"""AD-508 v1: Scoped Cognition -- Duty Scope helper.

Read-only observational helper that exposes a per-agent duty scope view
derived from ``runtime.work_item_store``. v1 just exposes the data surface;
proactive context injection, drift detection, Role/Ship/Personal scope, and
Earned Agency scaling are deferred to AD-508b/c/d/e.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DutyScopeSnapshot:
    """Per-agent duty scope view. AD-508 v1.

    Captured once per ``snapshot()`` call. Frozen so callers cannot mutate.
    """

    agent_id: str
    open_work_item_count: int
    work_item_titles: tuple[str, ...]  # up to 5 most recent titles
    captured_at: float


class DutyScopeProvider:
    """v1 observational read-only Duty Scope helper. AD-508 v1.

    Future consumer (AD-508b): proactive cognitive loop injects
    ``DutyScopeSnapshot`` into ``context["duty_scope"]``. v1 just exposes the
    surface so callers can pull on demand.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        # Public field per Wave 5 convention #1; mirrors AD-530 ClassificationGate.
        self.emit_event = emit_event

    async def snapshot(self, agent_id: str) -> DutyScopeSnapshot:
        """Return ``DutyScopeSnapshot`` for ``agent_id``.

        Empty snapshot when ``agent_id`` is falsy or ``work_item_store`` is
        missing. Failures from ``list_work_items`` are logged at debug and
        produce an empty snapshot (log-and-degrade).
        """
        if not agent_id:
            return DutyScopeSnapshot(
                agent_id="",
                open_work_item_count=0,
                work_item_titles=(),
                captured_at=time.time(),
            )
        store = getattr(self._runtime, "work_item_store", None)
        titles: tuple[str, ...] = ()
        count = 0
        if store is not None:
            try:
                items = await store.list_work_items(
                    status="open",
                    assigned_to=agent_id,
                    limit=5,
                )
                count = len(items)
                titles = tuple(getattr(it, "title", "") or "" for it in items[:5])
            except Exception:
                logger.debug(
                    "AD-508: list_work_items failed for agent_id=%s; returning empty snapshot",
                    agent_id,
                    exc_info=True,
                )
        snap = DutyScopeSnapshot(
            agent_id=agent_id,
            open_work_item_count=count,
            work_item_titles=titles,
            captured_at=time.time(),
        )
        self._emit(snap)
        return snap

    def _emit(self, snap: DutyScopeSnapshot) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.DUTY_SCOPE_QUERIED,
                {
                    "agent_id": snap.agent_id,
                    "open_count": snap.open_work_item_count,
                },
            )
        except Exception:
            logger.warning(
                "AD-508: emit_event failed for DUTY_SCOPE_QUERIED; continuing",
                exc_info=True,
            )
