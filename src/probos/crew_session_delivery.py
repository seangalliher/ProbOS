"""Durable CrewSession outcome delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from probos.notifications import AgentNotification, NotificationQueue

logger = logging.getLogger(__name__)

CrewSessionDeliveryOutcome = Literal[
    "done",
    "failed",
    "blocked_needs_captain",
]
CrewSessionDeliveryOwnership = Literal["captain", "self"]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_RECORD_BYTES = 8_192
_MAX_DRAIN_LIMIT = 1_000
_MAX_TIMESTAMP = 253_402_300_799.0
_OUTCOME_CONTENT: dict[str, tuple[str, str, str]] = {
    "done": (
        "info",
        "Crew session completed",
        "Open the existing crew room for details.",
    ),
    "failed": (
        "error",
        "Crew session failed",
        "Open the existing crew room for details.",
    ),
    "blocked_needs_captain": (
        "action_required",
        "Crew session needs Captain input",
        "Open the existing crew room for details.",
    ),
}
_RECORD_KEYS = frozenset({
    "version",
    "delivery_id",
    "session_id",
    "session_revision",
    "outcome",
    "thread_id",
    "origin",
    "originator_id",
    "author_id",
    "ownership",
    "notification_type",
    "title",
    "detail",
    "action_url",
    "occurred_at",
    "elapsed_seconds",
})


def _exact_json_bytes(
    value: Any,
    *,
    error: str,
    maximum: int = _MAX_RECORD_BYTES,
) -> bytes:
    def _validate(current: Any) -> None:
        if current is None or type(current) in (bool, int, str):
            return
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError(error)
            return
        if type(current) is list:
            for item in current:
                _validate(item)
            return
        if type(current) is dict:
            if any(type(key) is not str for key in current):
                raise ValueError(error)
            for item in current.values():
                _validate(item)
            return
        raise ValueError(error)

    try:
        _validate(value)
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError(error) from exc
    if len(encoded) > maximum:
        raise ValueError(error)
    return encoded


def _required_id(value: Any) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ValueError("crew_delivery_record_invalid")
    return value


@dataclass(frozen=True, slots=True)
class CrewSessionDeliveryRecord:
    version: Literal[1]
    delivery_id: str
    session_id: str
    session_revision: int
    outcome: CrewSessionDeliveryOutcome
    thread_id: str
    origin: Literal["captain", "agent"]
    originator_id: str
    author_id: str
    ownership: CrewSessionDeliveryOwnership
    notification_type: Literal["info", "error", "action_required"]
    title: str
    detail: str
    action_url: str
    occurred_at: float
    elapsed_seconds: float

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            raise ValueError("crew_delivery_record_invalid")
        if type(self.delivery_id) is not str or _SHA_RE.fullmatch(self.delivery_id) is None:
            raise ValueError("crew_delivery_identity_conflict")
        _required_id(self.session_id)
        _required_id(self.thread_id)
        _required_id(self.originator_id)
        _required_id(self.author_id)
        if (
            type(self.session_revision) is not int
            or not 1 <= self.session_revision <= 2_147_483_647
            or type(self.outcome) is not str
            or self.outcome not in _OUTCOME_CONTENT
            or type(self.origin) is not str
            or self.origin not in {"captain", "agent"}
            or type(self.ownership) is not str
            or self.ownership not in {"captain", "self"}
        ):
            raise ValueError("crew_delivery_record_invalid")
        expected_content = _OUTCOME_CONTENT[self.outcome]
        if (
            (self.notification_type, self.title, self.detail) != expected_content
            or type(self.action_url) is not str
            or self.action_url != f"thread:{self.thread_id}"
            or type(self.occurred_at) is not float
            or not math.isfinite(self.occurred_at)
            or not 0.0 <= self.occurred_at <= _MAX_TIMESTAMP
            or type(self.elapsed_seconds) is not float
            or not math.isfinite(self.elapsed_seconds)
            or not 0.0 <= self.elapsed_seconds <= _MAX_TIMESTAMP
        ):
            raise ValueError("crew_delivery_record_invalid")
        if self.origin == "captain":
            if self.originator_id != "captain" or self.ownership != "captain":
                raise ValueError("crew_delivery_record_invalid")
        elif self.ownership != "self" or self.author_id != self.originator_id:
            raise ValueError("crew_delivery_record_invalid")
        expected_id = hashlib.sha256(self.identity_bytes()).hexdigest()
        if self.delivery_id != expected_id:
            raise ValueError("crew_delivery_identity_conflict")

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
        thread_id: str,
        origin: Literal["captain", "agent"],
        originator_id: str,
        author_id: str,
        ownership: CrewSessionDeliveryOwnership,
        occurred_at: float,
        elapsed_seconds: float,
    ) -> CrewSessionDeliveryRecord:
        if type(outcome) is not str or outcome not in _OUTCOME_CONTENT:
            raise ValueError("crew_delivery_record_invalid")
        notification_type, title, detail = _OUTCOME_CONTENT[outcome]
        identity = {
            "version": 1,
            "session_id": session_id,
            "session_revision": session_revision,
            "outcome": outcome,
            "thread_id": thread_id,
            "origin": origin,
            "originator_id": originator_id,
            "author_id": author_id,
            "ownership": ownership,
            "notification_type": notification_type,
            "title": title,
            "detail": detail,
            "action_url": f"thread:{thread_id}",
            "occurred_at": occurred_at,
            "elapsed_seconds": elapsed_seconds,
        }
        delivery_id = hashlib.sha256(
            _exact_json_bytes(identity, error="crew_delivery_record_invalid"),
        ).hexdigest()
        return cls(delivery_id=delivery_id, **identity)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CrewSessionDeliveryRecord:
        if type(payload) is not dict or set(payload) != _RECORD_KEYS:
            raise ValueError("crew_delivery_record_invalid")
        detached = json.loads(
            _exact_json_bytes(payload, error="crew_delivery_record_invalid"),
        )
        return cls(**detached)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "session_id": self.session_id,
            "session_revision": self.session_revision,
            "outcome": self.outcome,
            "thread_id": self.thread_id,
            "origin": self.origin,
            "originator_id": self.originator_id,
            "author_id": self.author_id,
            "ownership": self.ownership,
            "notification_type": self.notification_type,
            "title": self.title,
            "detail": self.detail,
            "action_url": self.action_url,
            "occurred_at": self.occurred_at,
            "elapsed_seconds": self.elapsed_seconds,
        }

    def identity_bytes(self) -> bytes:
        return _exact_json_bytes(
            self.identity_payload(),
            error="crew_delivery_record_invalid",
        )

    def to_payload(self) -> dict[str, Any]:
        return {"delivery_id": self.delivery_id, **self.identity_payload()}

    def canonical_bytes(self) -> bytes:
        return _exact_json_bytes(
            self.to_payload(),
            error="crew_delivery_record_invalid",
        )

    def to_notification(self) -> AgentNotification:
        return AgentNotification(
            id=self.delivery_id,
            agent_id=self.author_id,
            agent_type="crew_session",
            department="operations",
            notification_type=self.notification_type,
            title=self.title,
            detail=self.detail,
            action_url=self.action_url,
            suggested_action=None,
            created_at=self.occurred_at,
            acknowledged=False,
        )


class _CrewSessionOutcomeContract(Protocol):
    state: str
    revision: int
    task_id: str
    thread_id: str
    origin: str
    originator_id: str
    facilitator_id: str
    created_at: float
    transitioned_at: float
    completed_at: float | None


def build_crew_session_delivery_record(
    contract: _CrewSessionOutcomeContract,
) -> CrewSessionDeliveryRecord:
    outcome = contract.state
    if outcome not in _OUTCOME_CONTENT:
        raise ValueError("crew_delivery_outcome_invalid")
    occurred_at = (
        contract.transitioned_at
        if outcome == "blocked_needs_captain"
        else contract.completed_at
    )
    if type(occurred_at) is not float:
        raise ValueError("crew_delivery_record_invalid")
    if contract.origin == "captain":
        ownership: CrewSessionDeliveryOwnership = "captain"
        author_id = contract.facilitator_id
    elif contract.origin == "agent":
        ownership = "self"
        author_id = contract.originator_id
    else:
        raise ValueError("crew_delivery_record_invalid")
    return CrewSessionDeliveryRecord.create(
        session_id=contract.task_id,
        session_revision=contract.revision,
        outcome=outcome,
        thread_id=contract.thread_id,
        origin=contract.origin,
        originator_id=contract.originator_id,
        author_id=author_id,
        ownership=ownership,
        occurred_at=occurred_at,
        elapsed_seconds=occurred_at - contract.created_at,
    )


def build_crew_session_delivery_record_from_payload(
    payload: dict[str, Any],
) -> CrewSessionDeliveryRecord:
    if type(payload) is not dict:
        raise ValueError("crew_delivery_record_invalid")
    required = {
        "state",
        "revision",
        "task_id",
        "thread_id",
        "origin",
        "originator_id",
        "facilitator_id",
        "created_at",
        "transitioned_at",
        "completed_at",
    }
    if not required.issubset(payload):
        raise ValueError("crew_delivery_record_invalid")
    outcome = payload["state"]
    occurred_at = (
        payload["transitioned_at"]
        if outcome == "blocked_needs_captain"
        else payload["completed_at"]
    )
    if payload["origin"] == "captain":
        ownership: CrewSessionDeliveryOwnership = "captain"
        author_id = payload["facilitator_id"]
    elif payload["origin"] == "agent":
        ownership = "self"
        author_id = payload["originator_id"]
    else:
        raise ValueError("crew_delivery_record_invalid")
    return CrewSessionDeliveryRecord.create(
        session_id=payload["task_id"],
        session_revision=payload["revision"],
        outcome=outcome,
        thread_id=payload["thread_id"],
        origin=payload["origin"],
        originator_id=payload["originator_id"],
        author_id=author_id,
        ownership=ownership,
        occurred_at=occurred_at,
        elapsed_seconds=occurred_at - payload["created_at"],
    )


@dataclass(frozen=True, slots=True)
class CrewSessionDeliveryOutboxEntry:
    record: CrewSessionDeliveryRecord
    delivered: bool
    created_at: float
    delivered_at: float | None

    def __post_init__(self) -> None:
        if (
            type(self.record) is not CrewSessionDeliveryRecord
            or type(self.delivered) is not bool
            or type(self.created_at) is not float
            or not math.isfinite(self.created_at)
            or not 0.0 <= self.created_at <= _MAX_TIMESTAMP
            or (
                self.delivered_at is not None
                and (
                    type(self.delivered_at) is not float
                    or not math.isfinite(self.delivered_at)
                    or not 0.0 <= self.delivered_at <= _MAX_TIMESTAMP
                )
            )
            or (self.delivered and self.delivered_at is None)
            or (not self.delivered and self.delivered_at is not None)
        ):
            raise ValueError("crew_delivery_outbox_corrupt")


class _DeliveryOutboxProtocol(Protocol):
    async def list_pending_crew_session_deliveries(
        self,
        *,
        limit: int,
        session_id: str | None = None,
        session_revision: int | None = None,
    ) -> tuple[CrewSessionDeliveryOutboxEntry, ...]: ...

    async def mark_crew_session_delivery_delivered(
        self,
        delivery_id: str,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> bool | None: ...

    async def get_exact_crew_session_delivery(
        self,
        record: CrewSessionDeliveryRecord,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> CrewSessionDeliveryOutboxEntry | None: ...


class _Thread(Protocol):
    id: str
    task_id: str | None
    archived: bool


class _ThreadStoreProtocol(Protocol):
    def get_thread(self, thread_id: str) -> _Thread | None: ...


class CrewSessionDeliveryService:
    def __init__(
        self,
        *,
        outbox: _DeliveryOutboxProtocol,
        thread_store: _ThreadStoreProtocol,
        notification_queue: NotificationQueue,
        drain_limit: int = _MAX_DRAIN_LIMIT,
    ) -> None:
        if type(drain_limit) is not int or not 1 <= drain_limit <= _MAX_DRAIN_LIMIT:
            raise ValueError("crew_delivery_outbox_limit_invalid")
        self._outbox = outbox
        self._threads = thread_store
        self._notifications = notification_queue
        self._drain_limit = drain_limit
        self._callback_admission_open = True
        self._callback_tasks: set[asyncio.Task[int]] = set()

    def admit_status_changed(self, event: Any) -> bool:
        if not self._callback_admission_open:
            return False
        task = asyncio.create_task(
            self.on_status_changed(event),
            name="crew-session-delivery-event",
        )
        self._callback_tasks.add(task)
        task.add_done_callback(self._observe_callback_task)
        return True

    def _observe_callback_task(self, task: asyncio.Task[int]) -> None:
        self._callback_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.warning(
                "Crew delivery event callback failed; durable rows remain "
                "pending and the next bounded event or startup drain will retry",
                exc_info=True,
            )

    async def close(self) -> None:
        self._callback_admission_open = False
        tasks = tuple(self._callback_tasks)
        if not tasks:
            return

        async def _drain_callbacks() -> list[Any]:
            return await asyncio.gather(*tasks, return_exceptions=True)

        drain_task = asyncio.create_task(
            _drain_callbacks(),
            name="crew-session-delivery-close",
        )
        first_cancellation: asyncio.CancelledError | None = None
        while not drain_task.done():
            try:
                await asyncio.shield(drain_task)
            except asyncio.CancelledError as exc:
                if first_cancellation is None:
                    first_cancellation = exc
                current_task = asyncio.current_task()
                if current_task is not None:
                    while current_task.cancelling():
                        current_task.uncancel()
        results = drain_task.result()
        for task, result in zip(tasks, results):
            self._callback_tasks.discard(task)
            if (
                first_cancellation is None
                and isinstance(result, asyncio.CancelledError)
            ):
                first_cancellation = result
        if first_cancellation is not None:
            raise first_cancellation

    async def on_status_changed(self, event: Any) -> int:
        if (
            type(event) is not dict
            or event.get("type") != "work_item_status_changed"
        ):
            return 0
        data = event.get("data")
        if type(data) is not dict:
            return 0
        work_item = data.get("work_item")
        if type(work_item) is not dict:
            return 0
        session_id = work_item.get("id")
        if type(session_id) is not str or _ID_RE.fullmatch(session_id) is None:
            return 0
        delivered = await self.drain_pending(
            limit=1,
            session_id=session_id,
        )
        if self._drain_limit > 1:
            delivered += await self.drain_pending(limit=self._drain_limit - 1)
        return delivered

    async def drain_pending(
        self,
        *,
        limit: int | None = None,
        session_id: str | None = None,
        session_revision: int | None = None,
    ) -> int:
        bounded_limit = self._drain_limit if limit is None else limit
        if (
            type(bounded_limit) is not int
            or not 1 <= bounded_limit <= self._drain_limit
            or (session_id is None and session_revision is not None)
            or (session_id is not None and _ID_RE.fullmatch(session_id) is None)
            or (
                session_revision is not None
                and (
                    type(session_revision) is not int
                    or not 1 <= session_revision <= 2_147_483_647
                )
            )
        ):
            raise ValueError("crew_delivery_outbox_limit_invalid")
        entries = await self._outbox.list_pending_crew_session_deliveries(
            limit=bounded_limit + 1,
            session_id=session_id,
            session_revision=session_revision,
        )
        if len(entries) > bounded_limit:
            logger.warning(
                "Crew delivery pending backlog exceeds bounded drain limit=%d; "
                "this pass will process only the oldest rows and a later event "
                "or startup will retry the remainder",
                bounded_limit,
            )
        delivered = 0
        for entry in entries[:bounded_limit]:
            record = CrewSessionDeliveryRecord.from_payload(entry.record.to_payload())
            try:
                thread = await asyncio.to_thread(
                    self._threads.get_thread,
                    record.thread_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Crew delivery room lookup failed for delivery_id=%s; the "
                    "durable row remains pending and the next bounded drain will retry",
                    record.delivery_id,
                    exc_info=True,
                )
                continue
            if (
                thread is None
                or thread.archived
                or thread.id != record.thread_id
                or thread.task_id != record.session_id
            ):
                logger.warning(
                    "Crew delivery room is missing, archived, or task-mismatched "
                    "for delivery_id=%s; the durable row remains pending and the "
                    "next bounded drain will retry",
                    record.delivery_id,
                )
                continue
            try:
                self._notifications.notify_once(record)
            except ValueError:
                raise
            except Exception:
                logger.warning(
                    "Crew delivery queue insertion failed for delivery_id=%s; "
                    "the durable row remains pending and the next bounded drain "
                    "will retry",
                    record.delivery_id,
                    exc_info=True,
                )
                continue
            try:
                mark_result = await self._outbox.mark_crew_session_delivery_delivered(
                    record.delivery_id,
                    session_id=record.session_id,
                    session_revision=record.session_revision,
                    outcome=record.outcome,
                )
                mark_error: BaseException | None = None
                first_cancellation: asyncio.CancelledError | None = None
            except asyncio.CancelledError as exc:
                mark_result = None
                mark_error = exc
                first_cancellation = exc
            except BaseException as exc:
                mark_result = None
                mark_error = exc
                first_cancellation = None

            authoritative, first_cancellation = (
                await self._read_authoritative_delivery(
                    record,
                    first_cancellation=first_cancellation,
                )
            )
            if first_cancellation is not None:
                raise first_cancellation
            if mark_error is not None and not isinstance(mark_error, Exception):
                raise mark_error
            if authoritative is None:
                raise ValueError("crew_delivery_ack_authority_missing") from mark_error
            if authoritative.delivered:
                if mark_error is not None:
                    logger.warning(
                        "Crew delivery acknowledgement raised after delivery_id=%s "
                        "committed; exact authoritative reread proved delivery and "
                        "no second mark will be attempted",
                        record.delivery_id,
                    )
                delivered += 1
                continue
            if mark_error is not None:
                logger.warning(
                    "Crew delivery acknowledgement failed for delivery_id=%s; "
                    "the exact queue entry is replay-safe and the durable row "
                    "remains pending for the next bounded drain",
                    record.delivery_id,
                    exc_info=(
                        type(mark_error),
                        mark_error,
                        mark_error.__traceback__,
                    ),
                )
            elif mark_result is not True:
                logger.warning(
                    "Crew delivery acknowledgement did not match delivery_id=%s; "
                    "the exact notification remains idempotent and the next bounded "
                    "drain will retry the pending row",
                    record.delivery_id,
                )
        return delivered

    async def _read_authoritative_delivery(
        self,
        record: CrewSessionDeliveryRecord,
        *,
        first_cancellation: asyncio.CancelledError | None,
    ) -> tuple[
        CrewSessionDeliveryOutboxEntry | None,
        asyncio.CancelledError | None,
    ]:
        current_task = asyncio.current_task()
        if (
            first_cancellation is not None
            and current_task is not None
            and current_task.cancelling()
        ):
            while current_task.cancelling():
                current_task.uncancel()
        read_task = asyncio.create_task(
            self._outbox.get_exact_crew_session_delivery(
                record,
                session_id=record.session_id,
                session_revision=record.session_revision,
                outcome=record.outcome,
            ),
            name="crew-session-delivery-authority",
        )
        while not read_task.done():
            try:
                await asyncio.shield(read_task)
            except asyncio.CancelledError as exc:
                if first_cancellation is None:
                    first_cancellation = exc
                current_task = asyncio.current_task()
                if current_task is not None:
                    while current_task.cancelling():
                        current_task.uncancel()
        try:
            authoritative = read_task.result()
        except asyncio.CancelledError as exc:
            if first_cancellation is None:
                first_cancellation = exc
            authoritative = None
        except Exception:
            if first_cancellation is None:
                raise
            logger.warning(
                "Crew delivery exact acknowledgement reread failed after "
                "cancellation; no success is counted and the first cancellation "
                "will propagate after reconciliation",
                exc_info=True,
            )
            authoritative = None
        return authoritative, first_cancellation
