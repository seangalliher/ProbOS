"""Read-only resolution of durable notification provenance to current context."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Protocol

from probos.crew_session_delivery import (
    CrewSessionDeliveryOutboxEntry,
    CrewSessionDeliveryRecord,
)
from probos.crew_session_live import LoadedCrewSessionProjection
from probos.threads import ChatThread

logger = logging.getLogger(__name__)


class NotificationDeliveryReader(Protocol):
    async def get_crew_session_delivery(
        self, delivery_id: str,
    ) -> CrewSessionDeliveryOutboxEntry | None: ...


class NotificationThreadReader(Protocol):
    def get_thread(self, thread_id: str) -> ChatThread | None: ...


class NotificationContextError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.detail = {
            404: "notification_context_not_found",
            409: "notification_context_conflict",
            410: "notification_context_archived",
            422: "notification_context_id_invalid",
            503: "notification_context_unavailable",
        }[status_code]
        super().__init__(self.detail)


class NotificationContextResolver:
    def __init__(
        self,
        *,
        delivery_store: NotificationDeliveryReader | None,
        thread_store: NotificationThreadReader | None,
        load_projection: Callable[
            [str], Awaitable[LoadedCrewSessionProjection | None]
        ] | None,
    ) -> None:
        self._deliveries = delivery_store
        self._threads = thread_store
        self._load_projection = load_projection

    def _current_thread(self, record: CrewSessionDeliveryRecord) -> ChatThread:
        if self._threads is None:
            raise NotificationContextError(503)
        thread = self._threads.get_thread(record.thread_id)
        if thread is None:
            raise NotificationContextError(404)
        if thread.id != record.thread_id or thread.task_id != record.session_id:
            raise NotificationContextError(409)
        if thread.archived:
            raise NotificationContextError(410)
        return thread

    async def resolve(self, notification_id: str) -> dict[str, object]:
        """Return only current correlated context; never replay delivery actions."""
        if (
            type(notification_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", notification_id) is None
        ):
            raise NotificationContextError(422)
        if (
            self._deliveries is None
            or self._threads is None
            or self._load_projection is None
        ):
            raise NotificationContextError(503)
        try:
            entry = await self._deliveries.get_crew_session_delivery(notification_id)
            if entry is None:
                raise NotificationContextError(404)
            if (
                type(entry) is not CrewSessionDeliveryOutboxEntry
                or type(entry.record) is not CrewSessionDeliveryRecord
            ):
                raise NotificationContextError(409)
            record = CrewSessionDeliveryRecord.from_payload(entry.record.to_payload())
            if record.delivery_id != notification_id:
                raise NotificationContextError(409)
            self._current_thread(record)
            loaded = await self._load_projection(record.session_id)
            thread = self._current_thread(record)
            if loaded is None:
                raise NotificationContextError(404)
            detail = loaded.detail
            if (
                loaded.parent.id != record.session_id
                or loaded.parent.work_type != "crew_session"
                or detail.task_id != record.session_id
                or detail.thread_id != record.thread_id
                or detail.origin != record.origin
                or detail.originator_id != record.originator_id
                or detail.revision < record.session_revision
                or (
                    detail.revision == record.session_revision
                    and detail.state != record.outcome
                )
            ):
                raise NotificationContextError(409)
            return {
                "kind": "crew_session",
                "notification_id": notification_id,
                "delivery_revision": record.session_revision,
                "thread": thread.to_dict(),
                "session": detail.to_wire(),
            }
        except NotificationContextError:
            raise
        except (ValueError, TypeError) as exc:
            raise NotificationContextError(409) from exc
        except Exception as exc:
            logger.warning(
                "Notification context read failed; current destination cannot be "
                "verified; returning unavailable without navigation",
            )
            raise NotificationContextError(503) from exc