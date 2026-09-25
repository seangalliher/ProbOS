"""AD-1195: persist DURABLE EventType members to events.db without blocking emission.

``ProbOSRuntime._emit_event`` offers every envelope to one ``DurableEventRouter``.
A routed member (DURABLE and not already written by an owner, see
``probos.event_persistence``) is admitted with ``put_nowait`` into one bounded
queue, which one held writer task drains into the EventLog as a
``(ROUTED_CATEGORY, <value>)`` row. ``offer()`` never awaits and never waits on
the writer or the store; it takes one short lock to count.
A record that is refused, or whose write fails or returns no row id, is a loss:
it is counted by reason in the current drop episode, and one drop-marker row
records each episode once a later write succeeds. Until its row or that marker
is written, ``unresolved()`` keeps counting it.

Chain safety: EventLog serialises writers and chains each row to the actual
tail at insert time, so a record dropped before insert leaves no hole in the
AD-490 hash chain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import islice
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, cast

from probos.event_persistence import (
    DROP_MARKER_EVENT,
    ROUTED_CATEGORY,
    durable_record_key,
    is_routed,
)
from probos.events import EventType
from probos.substrate.event_log import bounded_json_payload

logger = logging.getLogger(__name__)

# Module constants, not config fields: nobody sets them, and a config field
# would bring facade, profile and reference churn with it.
DURABLE_EVENT_QUEUE_MAX: Final = 1024
"""Queued routed records before an offer is dropped as ``queue_full``."""
DURABLE_PAYLOAD_MAX_BYTES: Final = 4096
"""Stored ``data`` bytes per routed row: the governed per-row read cap."""
DURABLE_DRAIN_WAIT_BUDGET_S: Final = 2.0
"""How long ``drain()`` waits for the queue to empty: a wait budget, not a deadline."""
_CANCEL_WAIT_S: Final = 0.5
_WARN_EVERY: Final = 256
_SNAPSHOT_ITEMS: Final = 33  # one past the projection's 32, so it still marks the cut
_SUMMARY_CHARS: Final = 128
_MARKER_EVENT_KEYS: Final = 32
_MARKER_SCAN: Final = 1000
_OTHER: Final = "_other"

ROUTED_VALUES: frozenset[str] = frozenset(m.value for m in EventType if is_routed(m.name))
"""The envelope ``type`` values the router admits."""


class DurableEventSink(Protocol):
    """Where routed rows go; ``EventLog`` satisfies it."""

    async def log(
        self,
        category: str,
        event: str,
        agent_id: str | None = None,
        agent_type: str | None = None,
        pool: str | None = None,
        detail: str | None = None,
        *,
        correlation_id: str | None = None,
        parent_event_id: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> int | None: ...


class DurableEventSource(Protocol):
    """What ``durable_answer`` reads; ``EventLog`` satisfies it.

    ``query_structured`` returns the newest matching rows first, and fewer than
    ``limit`` only when fewer match: the marker scan's truncation rule relies on it.
    """

    @property
    def is_open(self) -> bool: ...

    async def query_structured(
        self,
        *,
        category: str | None = None,
        event: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class DurableEventStats:
    """Router counters.

    ``offered`` counts routed envelopes. Each one is dropped before a write (per
    reason, in ``dropped``), written, failed, not_recorded, or still queued
    (``pending``). A record is in none of those while the writer holds it, while a
    thread's hand-off waits for the loop to run it, or once a drain's cancel has
    interrupted its write. A failed or not_recorded write is also a loss in the
    drop episode, so the next drop-marker row records it under that reason.
    """

    offered: int
    written: int
    failed: int
    not_recorded: int
    markers_written: int
    pending: int
    dropped: Mapping[str, int]


AnswerStatus = Literal[
    "recorded",
    "not_recorded",
    "unknown_pending",
    "unknown_dropped",
    "not_answerable",
    "unavailable",
]


@dataclass(frozen=True)
class DurableAnswer:
    """What events.db can say about one member; see ``durable_answer``."""

    member: str
    status: AnswerStatus
    row: dict[str, Any] | None
    record_key: tuple[str, str] | None


@dataclass(frozen=True, slots=True)
class _DurableRecord:
    event: str
    emitted_at: object
    payload: object


@dataclass(slots=True)
class _DropEpisode:
    """Losses not yet recorded by a drop-marker row; ``by_event`` is exact until written."""

    count: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    by_event: dict[str, int] = field(default_factory=dict)
    first_at: float | None = None
    last_at: float | None = None


class DurableEventRouter:
    """Admits routed envelopes without blocking and writes them from one held task.

    ``offer()`` and ``unresolved()`` may be called from any thread. Everything
    else runs on the loop given to ``bind_loop()``: the queue and the
    ``durable-event-writer`` task are created there on first use, and ``drain()``
    must be awaited there.
    """

    def __init__(
        self,
        sink: DurableEventSink,
        *,
        routes: Iterable[str] = ROUTED_VALUES,
        queue_max: int = DURABLE_EVENT_QUEUE_MAX,
    ) -> None:
        if type(queue_max) is not int or queue_max < 1:
            raise ValueError(f"queue_max must be a positive int, got {queue_max!r}")
        self._sink = sink
        self._routes = frozenset(routes)
        self._queue_max = queue_max
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[_DurableRecord] | None = None
        self._writer: asyncio.Task[None] | None = None
        self._closed = False
        self._generation = 0
        # Guards what offer() and unresolved() touch from other threads; never held across an await.
        self._lock = threading.Lock()
        self._offered = 0
        self._dropped: dict[str, int] = {}
        self._episode = _DropEpisode()
        self._unresolved: dict[str, int] = {}
        self._accepted = 0
        self._written = 0
        self._failed = 0
        self._not_recorded = 0
        self._markers_written = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the writer's loop; re-arms a drained router, dropping its stale queue and writer.

        Starts a new generation, so a thread's hand-off scheduled before this call
        is refused as ``closed`` when it runs.
        """
        with self._lock:
            self._loop = loop
            self._queue = None
            self._writer = None
            self._closed = False
            self._generation += 1

    def offer(self, event: Mapping[str, Any]) -> None:
        """Admit ``event`` if its type is routed; synchronous, never awaits or raises Exception.

        Past the type check every envelope is counted as offered, and one that
        is refused is counted as dropped with a reason (unbound, closed,
        loop_closed, queue_full or offer_error).
        """
        try:
            event_type = event.get("type")
            if event_type not in self._routes:
                return
        except Exception:
            return  # an unreadable or unhashable type is not a routed member
        with self._lock:
            self._offered += 1
        try:
            data = event.get("data")
            record = _DurableRecord(event_type, event.get("timestamp"), _snapshot(data))
        except Exception:
            self._drop("offer_error", event_type, held=False)
            return
        with self._lock:
            loop, closed, generation = self._loop, self._closed, self._generation
            if loop is not None and not closed:
                _bump(self._unresolved, event_type, 1)  # until its row or marker is written
        if loop is None:
            self._drop("unbound", event_type, held=False)
        elif closed:
            self._drop("closed", event_type, held=False)
        elif _running_loop() is loop:
            self._accept_on_loop(record, generation)
        else:
            try:
                loop.call_soon_threadsafe(self._accept_on_loop, record, generation)
            except RuntimeError:
                self._drop("loop_closed", event_type, held=True)
            except Exception:
                self._drop("offer_error", event_type, held=True)

    def unresolved(self, value: str) -> int:
        """How many records of ``value`` this router holds that events.db does not reflect yet.

        A record counts from the moment it is handed off or accepted until its row
        is written. A record that was refused, failed or returned no row id counts
        until the drop-marker row that records its loss is written. A record whose
        write a drain cancels, or that a drain leaves queued, is never resolved and
        stays counted. Safe to call from any thread.
        """
        with self._lock:
            return self._unresolved.get(value, 0)

    def stats(self) -> DurableEventStats:
        """A snapshot of the counters; ``pending`` is the current queue depth."""
        with self._lock:
            offered = self._offered
            dropped: Mapping[str, int] = MappingProxyType(dict(self._dropped))
        queue = self._queue
        return DurableEventStats(
            offered=offered,
            written=self._written,
            failed=self._failed,
            not_recorded=self._not_recorded,
            markers_written=self._markers_written,
            pending=queue.qsize() if queue is not None else 0,
            dropped=dropped,
        )

    async def drain(
        self, *, wait_budget_s: float = DURABLE_DRAIN_WAIT_BUDGET_S
    ) -> DurableEventStats:
        """Close admission, then wait up to ``wait_budget_s`` for queued rows to be written.

        Closing also ends the current generation, so a thread's hand-off that runs
        after this call is refused as ``closed`` even once ``bind_loop()`` re-arms.
        A wait budget, not a deadline: once it is spent the writer is cancelled
        and given ``_CANCEL_WAIT_S`` more to unwind, so a drain returns after
        about the budget plus that wait plus scheduling slack. Queued rows are
        then lost and logged; a write the cancel interrupts may or may not land.
        The drain's own cancellation propagates.
        """
        with self._lock:
            self._closed = True
            self._generation += 1
        queue, writer = self._queue, self._writer
        if queue is not None:
            join = asyncio.get_running_loop().create_task(
                queue.join(), name="durable-event-drain-join"
            )
            try:
                done, _ = await asyncio.wait({join}, timeout=wait_budget_s)
            finally:
                join.cancel()
            if not done:
                unwritten = self._accepted - self._written - self._failed - self._not_recorded
                if unwritten:  # zero means only a drop-marker write was in flight
                    logger.error(
                        "AD-1195: durable event drain spent its %.1fs wait budget with %d "
                        "rows still queued and %d admitted rows unwritten in all; the "
                        "queued rows are lost and an interrupted write may not land; "
                        "shutdown continues",
                        wait_budget_s, queue.qsize(), unwritten,
                    )
            if writer is not None and not writer.done():
                writer.cancel()
                await asyncio.wait({writer}, timeout=_CANCEL_WAIT_S)
                if not writer.done():
                    logger.warning(
                        "AD-1195: the durable event writer was cancelled but had not "
                        "stopped after %.1fs; it exits once its interrupted write "
                        "unwinds", _CANCEL_WAIT_S,
                    )
        unmarked = self._episode.count
        if unmarked:
            logger.warning(
                "AD-1195: %d dropped durable rows have no drop-marker row, so this log "
                "line is the only record of them", unmarked,
            )
        return self.stats()

    def _accept_on_loop(self, record: _DurableRecord, generation: int) -> None:
        """On the bound loop: arm the writer and enqueue, or count the drop."""
        with self._lock:
            # A thread's hand-off can run after drain() closed admission, or after
            # bind_loop() started a newer generation; either way it is stale.
            stale = self._closed or generation != self._generation
        if stale:
            self._drop("closed", record.event, held=True)
            return
        try:
            self._ensure_writer().put_nowait(record)
        except asyncio.QueueFull:
            self._drop("queue_full", record.event, held=True)
        except Exception:
            self._drop("offer_error", record.event, held=True)
        else:
            self._accepted += 1

    def _drop(self, reason: str, event: str, *, held: bool) -> None:
        """Count one record refused before a write; warn on an episode's first loss and every 256th.

        ``held`` says ``unresolved()`` already counts the record (it was handed off
        or accepted); otherwise it starts counting here.
        """
        now = time.time()
        with self._lock:
            _bump(self._dropped, reason, 1)
            if not held:
                _bump(self._unresolved, event, 1)
            count = _add_loss(self._episode, reason, event, now)
        if count == 1 or count % _WARN_EVERY == 0:
            logger.warning(
                "AD-1195: durable event %s was not persisted (%s); %d dropped since the "
                "last drop-marker row. The loss is counted, and a drop-marker row "
                "records it once a later write succeeds", event, reason, count,
            )

    def _ensure_writer(self) -> asyncio.Queue[_DurableRecord]:
        """Create the queue and the held ``durable-event-writer`` task on first use."""
        queue = self._queue
        if queue is None:
            queue = self._queue = asyncio.Queue(maxsize=self._queue_max)
        writer = self._writer
        if writer is None or writer.done():
            if writer is not None:
                logger.error(
                    "AD-1195: the durable event writer stopped (%s); starting a "
                    "replacement so queued rows are still written",
                    "cancelled" if writer.cancelled() else repr(writer.exception()),
                )
            self._writer = asyncio.get_running_loop().create_task(
                self._writer_loop(queue), name="durable-event-writer"
            )
        return queue

    async def _writer_loop(self, queue: asyncio.Queue[_DurableRecord]) -> None:
        """Write queued records in order; after losses, the next success also writes a marker.

        The marker is written before ``task_done()``, so a drain's ``join()``
        waits for it too.
        """
        while True:
            record = await queue.get()
            try:
                # An unlocked read: a stale answer only delays the marker by one record.
                if await self._write(record) and self._episode.count:
                    await self._write_marker()
            finally:
                queue.task_done()

    async def _write(self, record: _DurableRecord) -> bool:
        """Write one routed row; True only when the sink returned a row id.

        The row's ``agent_id`` and ``correlation_id`` columns stay NULL: an agent id or
        correlation id stays in the projected payload, so the readers of those indexed
        columns (AD-541's latest row for an agent, AD-664's correlation chains) see only
        the rows their owners write.
        A write that raises or returns no row id is a loss in the drop episode
        (``write_failed`` or ``not_recorded``), so the next marker records it.
        """
        try:
            row_id = await self._sink.log(ROUTED_CATEGORY, record.event, data=_row_data(record))
        except asyncio.CancelledError:
            raise  # stays unresolved: the interrupted write may or may not land
        except Exception as exc:
            self._failed += 1
            with self._lock:
                count = _add_loss(self._episode, "write_failed", record.event, time.time())
            if count == 1 or self._failed == 1 or self._failed % _WARN_EVERY == 0:
                logger.warning(
                    "AD-1195: durable event %s could not be written to events.db (%s: %s); "
                    "%d routed rows have failed so far. The row is lost; a drop-marker row "
                    "records the loss once a later write succeeds, and the writer "
                    "continues with the next one",
                    record.event, type(exc).__name__, exc, self._failed,
                )
            return False
        if type(row_id) is int:
            self._written += 1
            with self._lock:
                _bump(self._unresolved, record.event, -1)
            return True
        self._not_recorded += 1
        with self._lock:
            count = _add_loss(self._episode, "not_recorded", record.event, time.time())
        if count == 1 or self._not_recorded == 1 or self._not_recorded % _WARN_EVERY == 0:
            logger.warning(
                "AD-1195: durable event %s was not recorded: the store returned no row "
                "id (EventLog does that only while closed); %d routed rows are "
                "unrecorded so far. A drop-marker row records the loss once a later "
                "write succeeds, and the writer continues with the next one",
                record.event, self._not_recorded,
            )
        return False

    async def _write_marker(self) -> None:
        """Record the losses since the last marker in one row; if that fails, keep them."""
        with self._lock:
            episode, self._episode = self._episode, _DropEpisode()
        written = False
        try:
            row_id = await self._sink.log(
                ROUTED_CATEGORY,
                DROP_MARKER_EVENT,
                data={
                    "dropped": episode.count,
                    "by_reason": dict(episode.by_reason),
                    "by_event": _folded(episode.by_event),
                    "first_at": episode.first_at,
                    "last_at": episode.last_at,
                },
            )
            written = type(row_id) is int
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "AD-1195: the drop-marker row for %d dropped durable rows could not be "
                "written (%s: %s); the drops are kept and the next successful write "
                "retries the marker", episode.count, type(exc).__name__, exc,
            )
        finally:
            with self._lock:
                if written:  # from here the marker answers for these losses
                    for event, n in episode.by_event.items():
                        _bump(self._unresolved, event, -n)
                else:
                    self._episode = _merged(episode, self._episode)
        if written:
            self._markers_written += 1


async def durable_answer(
    source: DurableEventSource,
    member: EventType | str,
    *,
    router: DurableEventRouter | None = None,
) -> DurableAnswer:
    """Say whether events.db holds a record of a DURABLE member, within retention.

    "Ever" means within retention (7 days or 100,000 rows by default): pruning
    removes old rows, and old drop markers with them. ``member`` is an
    EventType, a member name or a member value. ``router`` is this process's
    router (``runtime.durable_events``). A query failure propagates.

    - ``unavailable``: the store is not open, or closed while answering, so
      nothing can be said.
    - ``not_answerable``: not a DURABLE member (or not a member at all).
    - ``recorded``: a row exists; ``row`` is the newest one.
    - ``unknown_pending``: no row, and ``router`` still holds a record of the
      member that events.db does not reflect yet (see
      ``DurableEventRouter.unresolved``): its row, or the drop-marker row for
      its loss, is not written yet.
    - ``unknown_dropped``: no row, and a retained drop marker names the member
      (or ``_other``), so a record may have been lost; ``row`` is that marker.
      Also returned with ``row=None`` when the scan read its full bound of
      1,000 markers without finding one: the marker scan could not establish
      absence.
    - ``not_recorded``: no row, a scan that read every retained marker found
      none naming the member, and ``router``, when given, holds nothing
      unresolved for it: evidence of absence within retention.

    Without ``router`` (for example, reading events.db from another process),
    records still queued in a running process, and losses not yet recorded by a
    drop marker, are not visible, so ``not_recorded`` then means only "not
    recorded by any write that has completed".

    The equivalent SQL for a routed member::

        SELECT id, timestamp, data FROM events WHERE category='event_type' AND event=? ORDER BY id DESC LIMIT 1;
        SELECT id, timestamp, data FROM events WHERE category='event_type' AND event='durable_event_dropped' ORDER BY id DESC LIMIT 1000;

    When the second query returns 1,000 rows and none names the member or
    ``_other``, the marker scan could not establish absence, so the answer is
    ``unknown_dropped`` with no row. An owner member uses its ``OWNER_RECORDS``
    pair instead, and has no markers.
    """
    name, resolved = _resolve_member(member)
    key = durable_record_key(resolved.name, resolved.value) if resolved is not None else None
    if not source.is_open:
        return DurableAnswer(name, "unavailable", None, key)
    if resolved is None or key is None:
        return DurableAnswer(name, "not_answerable", None, None)
    rows = await source.query_structured(category=key[0], event=key[1], limit=1)
    if rows:
        return DurableAnswer(name, "recorded", rows[0], key)
    if is_routed(resolved.name):
        if router is not None and router.unresolved(resolved.value) > 0:
            return DurableAnswer(name, "unknown_pending", None, key)
        markers = await source.query_structured(
            category=ROUTED_CATEGORY, event=DROP_MARKER_EVENT, limit=_MARKER_SCAN
        )
        for marker in markers:
            data = marker.get("data")
            by_event = data.get("by_event") if isinstance(data, dict) else None
            if isinstance(by_event, dict) and (resolved.value in by_event or _OTHER in by_event):
                return DurableAnswer(name, "unknown_dropped", marker, key)
        if len(markers) >= _MARKER_SCAN:  # older markers past the bound were not read
            return DurableAnswer(name, "unknown_dropped", None, key)
    if not source.is_open:  # it closed mid-answer, so the empty results prove nothing
        return DurableAnswer(name, "unavailable", None, key)
    return DurableAnswer(name, "not_recorded", None, key)


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _resolve_member(member: object) -> tuple[str, EventType | None]:
    """A label for ``member`` and the EventType it names (by member, NAME or value), if any."""
    if isinstance(member, EventType):
        return member.name, member
    if type(member) is not str:
        return repr(member), None
    found = EventType.__members__.get(member)
    if found is None:
        try:
            found = EventType(member)
        except ValueError:
            return member, None
    return found.name, found


def _snapshot(data: object) -> object:
    """A bounded shallow copy: later rebinding cannot reach it; nested values stay shared."""
    if isinstance(data, Mapping):
        return dict(islice(data.items(), _SNAPSHOT_ITEMS))
    if isinstance(data, (list, tuple)):
        return list(data[:_SNAPSHOT_ITEMS])
    return data


def _stored_bytes(value: object) -> int:
    """Bytes EventLog.log stores for ``value``: ``json.dumps(sort_keys=True)``, ASCII-escaped."""
    return len(json.dumps(value, sort_keys=True, default=str))


def _row_data(record: _DurableRecord) -> dict[str, Any]:
    """The routed row's ``data``: the governed read projection, cut to fit the byte cap."""
    projected, _ = bounded_json_payload(
        {"emitted_at": record.emitted_at, "payload": record.payload}
    )
    row = cast("dict[str, Any]", projected)
    if _stored_bytes(row) <= DURABLE_PAYLOAD_MAX_BYTES:
        return row
    emitted_at, payload = row.get("emitted_at"), row.get("payload")
    summary = {"emitted_at": emitted_at, "payload": _summary(payload)}
    if _stored_bytes(summary) <= DURABLE_PAYLOAD_MAX_BYTES:
        return summary
    return _keys_only(payload, emitted_at)


def _summary(payload: object) -> dict[str, Any]:
    """Top-level scalars and the scalar fields of top-level dicts, strings cut to 128."""
    kept: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, dict):
                kept[key] = {k: _cut(v) for k, v in value.items() if _is_scalar(v)}
            elif _is_scalar(value):
                kept[key] = _cut(value)
    kept["_truncated"] = True
    return kept


def _keys_only(payload: object, emitted_at: object) -> dict[str, Any]:
    """The last resort: as many top-level key names as fit under the cap.

    ``payload`` is already projected, so it has at most 32 keys.
    """
    keys: list[str] = []
    row: dict[str, Any] = {"emitted_at": emitted_at, "payload": {"_truncated": True, "keys": keys}}
    if _stored_bytes(row) > DURABLE_PAYLOAD_MAX_BYTES:
        row["emitted_at"] = None  # only a non-numeric timestamp can be this large
    for key in payload if isinstance(payload, dict) else ():
        if key == "_truncated":
            continue
        keys.append(key[:_SUMMARY_CHARS])
        if _stored_bytes(row) > DURABLE_PAYLOAD_MAX_BYTES:
            keys.pop()
            break
    return row


def _is_scalar(value: object) -> bool:
    return value is None or type(value) in (bool, int, float, str)


def _cut(value: object) -> object:
    return value[:_SUMMARY_CHARS] if type(value) is str else value


def _bump(counts: dict[str, int], key: str, n: int) -> None:
    """Add ``n`` to ``counts[key]``, removing the key once it reaches zero."""
    total = counts.get(key, 0) + n
    if total:
        counts[key] = total
    else:
        counts.pop(key, None)


def _add_loss(episode: _DropEpisode, reason: str, event: str, now: float) -> int:
    """Count one lost record in ``episode``; returns the episode's loss count."""
    episode.count += 1
    _bump(episode.by_reason, reason, 1)
    _bump(episode.by_event, event, 1)
    if episode.first_at is None:
        episode.first_at = now
    episode.last_at = now
    return episode.count


def _folded(by_event: Mapping[str, int]) -> dict[str, int]:
    """A marker's ``by_event``: the first 32 names kept, the rest summed into ``_other``."""
    folded: dict[str, int] = {}
    for index, (event, n) in enumerate(by_event.items()):
        _bump(folded, event if index < _MARKER_EVENT_KEYS else _OTHER, n)
    return folded


def _merged(earlier: _DropEpisode, later: _DropEpisode) -> _DropEpisode:
    """One episode holding both, ``earlier`` first."""
    merged = _DropEpisode(
        count=earlier.count + later.count,
        by_reason=dict(earlier.by_reason),
        by_event=dict(earlier.by_event),
        first_at=earlier.first_at if earlier.count else later.first_at,
        last_at=later.last_at if later.count else earlier.last_at,
    )
    for reason, n in later.by_reason.items():
        _bump(merged.by_reason, reason, n)
    for event, n in later.by_event.items():
        _bump(merged.by_event, event, n)
    return merged
