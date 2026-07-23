"""Authoritative live CrewSession projection loading and coalescing."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from probos.crew_session_projection import (
    CrewSessionDetailProjection,
    CrewSessionProjectionError,
    CrewSessionSummaryProjection,
    build_crew_session_detail,
    build_crew_session_summary,
    validate_synthesis_metadata,
)

if TYPE_CHECKING:
    from probos.artifacts import ArtifactStore
    from probos.cognitive.crew_session import CrewSessionService
    from probos.threads import ChatThreadStore
    from probos.workforce import WorkItem, WorkItemStore

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_PENDING = 256


@dataclass(frozen=True, slots=True)
class LoadedCrewSessionProjection:
    parent: WorkItem
    detail: CrewSessionDetailProjection
    summary: CrewSessionSummaryProjection


def _bounded_id(value: object) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise CrewSessionProjectionError()
    return value


def _require_current(still_current: Callable[[], bool] | None) -> None:
    if still_current is not None and not still_current():
        raise asyncio.CancelledError()


async def load_crew_session_projection(
    parent_id: str,
    *,
    crew_session_service: CrewSessionService,
    work_item_store: WorkItemStore,
    still_current: Callable[[], bool] | None = None,
) -> LoadedCrewSessionProjection:
    """Load and validate one exact AD-1132 detail and summary projection."""
    parent_key = _bounded_id(parent_id)
    _require_current(still_current)
    parent = await work_item_store.get_work_item(parent_key)
    _require_current(still_current)
    if parent is None or parent.id != parent_key or parent.work_type != "crew_session":
        raise CrewSessionProjectionError()
    session = await crew_session_service.get_session(parent_key)
    _require_current(still_current)
    if session is None or session.task_id != parent_key:
        raise CrewSessionProjectionError()
    current_parent = await work_item_store.get_work_item(parent_key)
    _require_current(still_current)
    if (
        current_parent is None
        or current_parent.id != parent_key
        or current_parent.work_type != "crew_session"
        or type(current_parent.metadata) is not dict
    ):
        raise CrewSessionProjectionError()
    raw_session = current_parent.metadata.get("crew_session")
    if raw_session is not None and (
        type(raw_session) is not dict
        or type(raw_session.get("revision")) is not int
        or raw_session["revision"] != session.revision
    ):
        raise CrewSessionProjectionError()
    parent = current_parent
    if type(parent.metadata) is not dict:
        raise CrewSessionProjectionError()
    synthesis = (
        validate_synthesis_metadata(parent.metadata["crew_synth"])
        if "crew_synth" in parent.metadata
        else None
    )
    children = await work_item_store.list_work_items(
        parent_id=parent_key,
        limit=1001,
    )
    _require_current(still_current)
    detail = build_crew_session_detail(
        session=session,
        synthesis=synthesis,
        children=children,
    )
    if detail.task_id != parent_key or detail.thread_id != session.thread_id:
        raise CrewSessionProjectionError()
    summary = build_crew_session_summary(detail)
    if (
        summary.task_id != detail.task_id
        or summary.thread_id != detail.thread_id
        or summary.state != detail.state
    ):
        raise CrewSessionProjectionError()
    return LoadedCrewSessionProjection(
        parent=parent,
        detail=detail,
        summary=summary,
    )


ProjectorDisposition = Literal["publish", "suppress", "drop"]


class CrewSessionLiveProjector:
    """Coalesce parent invalidations onto one generation-owned worker."""

    def __init__(
        self,
        *,
        crew_session_service: CrewSessionService | None,
        work_item_store: WorkItemStore | None,
        chat_thread_store: ChatThreadStore | None,
        artifact_store: ArtifactStore | None,
        publish: Callable[[str, dict[str, object], str], None],
        request_resync: Callable[[], None],
    ) -> None:
        self._service = crew_session_service
        self._work_items = work_item_store
        self._threads = chat_thread_store
        self._artifacts = artifact_store
        self._publish = publish
        self._request_resync = request_resync
        self._generation: str | None = None
        self._pending: deque[str] = deque()
        self._pending_ids: set[str] = set()
        self._dirty_ids: set[str] = set()
        self._active_parent_id: str | None = None
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._open = False

    def start(self, generation: str) -> None:
        if self._task is not None:
            raise RuntimeError("crew_live_projector_already_started")
        self._generation = generation
        self._open = True
        self._task = asyncio.create_task(
            self._run(),
            name="crew-session-live-projector",
        )

    def invalidate(self) -> None:
        self._open = False
        self._generation = None
        self._pending.clear()
        self._pending_ids.clear()
        self._dirty_ids.clear()
        self._active_parent_id = None
        self._wake.set()

    async def stop(self) -> None:
        self.invalidate()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _owns(self, generation: str) -> bool:
        return self._open and self._generation == generation

    def _schedule(self, parent_id: str) -> None:
        if not self._open:
            return
        try:
            parent_key = _bounded_id(parent_id)
        except CrewSessionProjectionError:
            return
        if parent_key in self._pending_ids:
            if parent_key == self._active_parent_id:
                self._dirty_ids.add(parent_key)
            return
        if len(self._pending_ids) >= _MAX_PENDING:
            self._request_resync()
            return
        self._pending_ids.add(parent_key)
        self._pending.append(parent_key)
        self._wake.set()

    async def route_event(
        self,
        event_type: str,
        data: dict[str, object],
        trigger: dict[str, object] | None,
    ) -> ProjectorDisposition:
        generation = self._generation
        if not self._open or generation is None:
            return "drop"
        if event_type in {
            "work_item_created",
            "work_item_updated",
            "work_item_status_changed",
        }:
            if trigger is None:
                return "drop"
            work_item_id = trigger.get("id")
            work_type = trigger.get("work_type")
            parent_id = trigger.get("parent_id")
            if type(work_item_id) is not str or _ID_RE.fullmatch(work_item_id) is None:
                return "drop"
            if work_type == "crew_session":
                self._schedule(work_item_id)
                return "suppress"
            if parent_id is None:
                return "publish"
            if type(parent_id) is not str or _ID_RE.fullmatch(parent_id) is None:
                return "drop"
            if self._work_items is None:
                return "drop"
            parent = await self._work_items.get_work_item(parent_id)
            if not self._owns(generation):
                return "drop"
            if parent is None:
                return "drop"
            if parent.id != parent_id:
                return "drop"
            if parent.work_type == "crew_session":
                self._schedule(parent_id)
                return "suppress"
            return "publish"

        if event_type == "artifact_version_added":
            thread_id = data.get("thread_id")
            if (
                type(thread_id) is not str
                or _ID_RE.fullmatch(thread_id) is None
                or self._threads is None
                or self._work_items is None
            ):
                return "drop"
            thread = await asyncio.to_thread(self._threads.get_thread, thread_id)
            if not self._owns(generation):
                return "drop"
            if thread is None or thread.id != thread_id or thread.task_id is None:
                return "publish"
            try:
                task_id = _bounded_id(thread.task_id)
            except CrewSessionProjectionError:
                return "drop"
            parent = await self._work_items.get_work_item(task_id)
            if not self._owns(generation):
                return "drop"
            if parent is None or parent.id != task_id:
                return "publish"
            if parent.work_type == "crew_session":
                self._schedule(task_id)
            return "publish"

        return "publish"

    async def _run(self) -> None:
        try:
            while True:
                await self._wake.wait()
                generation = self._generation
                if not self._open or generation is None:
                    return
                while self._pending:
                    parent_id = self._pending.popleft()
                    self._active_parent_id = parent_id
                    try:
                        await self._project(parent_id, generation)
                    except asyncio.CancelledError:
                        raise
                    except CrewSessionProjectionError:
                        if self._owns(generation):
                            self._request_resync()
                    except Exception:
                        if self._owns(generation):
                            logger.warning(
                                "Crew live projection for parent %s failed; "
                                "clients will repair through bounded GETs",
                                parent_id,
                                exc_info=True,
                            )
                            self._request_resync()
                    finally:
                        if self._active_parent_id == parent_id:
                            self._active_parent_id = None
                        if self._owns(generation) and parent_id in self._dirty_ids:
                            self._dirty_ids.discard(parent_id)
                            self._pending.append(parent_id)
                        else:
                            self._dirty_ids.discard(parent_id)
                            self._pending_ids.discard(parent_id)
                self._wake.clear()
        except asyncio.CancelledError:
            self._pending.clear()
            self._pending_ids.clear()
            self._dirty_ids.clear()
            self._active_parent_id = None
            raise

    async def _project(self, parent_id: str, generation: str) -> None:
        if (
            self._service is None
            or self._work_items is None
            or self._threads is None
            or self._artifacts is None
        ):
            raise CrewSessionProjectionError()
        loaded = await load_crew_session_projection(
            parent_id,
            crew_session_service=self._service,
            work_item_store=self._work_items,
            still_current=lambda: self._owns(generation),
        )
        if not self._owns(generation):
            return
        detail = loaded.detail
        summary = loaded.summary
        thread = await asyncio.to_thread(self._threads.get_thread, detail.thread_id)
        if not self._owns(generation):
            return
        if (
            thread is None
            or thread.id != detail.thread_id
            or thread.task_id != loaded.parent.id
            or detail.task_id != loaded.parent.id
            or summary.task_id != loaded.parent.id
            or summary.thread_id != thread.id
            or summary.state != detail.state
        ):
            raise CrewSessionProjectionError()
        steps = loaded.parent.steps
        if type(steps) is not list or len(steps) > 1000:
            raise CrewSessionProjectionError()
        steps_done = 0
        for step in steps:
            if type(step) is not dict or type(step.get("status")) is not str:
                raise CrewSessionProjectionError()
            if step["status"] == "done":
                steps_done += 1
        outputs = await asyncio.to_thread(
            self._artifacts.count_thread_latest,
            detail.thread_id,
        )
        if not self._owns(generation):
            return
        if type(outputs) is not int or outputs < 0:
            raise CrewSessionProjectionError()
        self._publish(
            "crew_session_projection",
            {
                "parent_id": loaded.parent.id,
                "thread_id": detail.thread_id,
                "revision": detail.revision,
                "session": detail.to_wire(),
                "room_summary": {
                    "outputs": outputs,
                    "steps_total": len(steps),
                    "steps_done": steps_done,
                    "topic": detail.goal,
                    "session": summary.to_wire(),
                },
            },
            generation,
        )