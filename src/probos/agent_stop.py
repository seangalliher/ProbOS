"""AD-1343 S1 (#1595): the Captain's stop for one crew agent, owned by the ship.

ProbOS is a vessel of vessels: each crew member is its own vessel carried inside the
ship. The stop belongs to the ship. This module holds the Captain's stop orders and
answers one question for every dispatch seam: is this agent stopped, and by which
order? The seams consult it; the agent never does, and nothing an agent can reach
issues or lifts an order (``routers/agent_stop.py`` holds the only callers, pinned by
``tests/test_ad1343_stop_seam_inventory.py``).

Durable authority: ``agent_stops.db``, one row per order; a partial unique index
allows one active order per agent, and a lift updates its row and never deletes it.
The in-memory view is loaded at start and is the only thing a seam reads, so no
dispatch does I/O and no seam can find the record unreadable after startup. An
unopenable store aborts startup: nothing runs without the record.

S1 refuses new work. It does not end work already running (S2), stop every agent at
once (S3) or reach external harness sessions (S4); ``S1_SCOPE`` says so in every answer
that reports an order to the Captain.

The EventLog is told of each order and lift, best effort: the store is authoritative.
The Captain's free-text reason stays in the store (inside the BF-758 file-read floor)
and is never copied into the EventLog, which agents can query.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from probos.tools.protocol import ToolResult
from probos.types import IntentMessage, IntentResult

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection
    from probos.substrate.event_log import EventLog

logger = logging.getLogger(__name__)

STORE_FILENAME: Final = "agent_stops.db"
CAPTAIN: Final = "captain"
STOP_REASON_CODE: Final = "agent_stopped"
STOP_METADATA_KEY: Final = "agent_stop"
MAX_REASON_CHARS: Final = 500

# The EventLog pair, as module constants bound once so the AD-1195 census resolves
# ('agent_stop', 'agent_stop_issued') and ('agent_stop', 'agent_stop_lifted').
STOP_EVENT_CATEGORY = "agent_stop"
STOP_ISSUED_EVENT = "agent_stop_issued"
STOP_LIFTED_EVENT = "agent_stop_lifted"

# Where a refusal happened. Every seam that consults the stop names one of these.
SEAM_INTENT: Final = "intent"
SEAM_CONSULTATION: Final = "consultation"
SEAM_TOOL: Final = "tool"
SEAM_PROACTIVE: Final = "proactive"
SEAM_WARD_ROOM: Final = "ward_room"
SEAM_DM_ROUTE: Final = "dm_route"
SEAM_GROUP_FANOUT: Final = "group_fanout"
SEAM_BROWSER_ACTION: Final = "browser_action_ack"
SEAM_AGENTIC_RUN: Final = "agentic_run"  # A2: the shared entry of every new agentic run, and correction rounds
SEAM_DELEGATION: Final = "delegation"  # A2: a task delegated to a stopped agent
SEAM_AGENT_WORK: Final = "agent_work"  # AD-1347 S1: work an agent creates for itself or requests from a colleague
SEAMS: Final[frozenset[str]] = frozenset({
    SEAM_INTENT, SEAM_CONSULTATION, SEAM_TOOL, SEAM_PROACTIVE, SEAM_WARD_ROOM,
    SEAM_DM_ROUTE, SEAM_GROUP_FANOUT, SEAM_BROWSER_ACTION, SEAM_AGENTIC_RUN, SEAM_DELEGATION,
    SEAM_AGENT_WORK,
})

S1_SCOPE: Final[dict[str, str]] = {
    "refuses": (
        "New work for the agent, wherever it is dispatched: intents (DMs, Ward Room notices, "
        "proactive and duty cycles, work items and the mesh), consultations, group chat turns, "
        "the DM route, tasks delegated to it, crew work under its name (it is not eligible for a crew "
        "subtask: a new one goes to an eligible colleague and one already assigned to it is not started; "
        "it is not picked to verify a colleague's work; a crew session it facilitates is not synthesized "
        "while the order stands: the session retries on its recovery schedule, continues if the order is "
        "lifted in time and otherwise ends blocked for the Captain, who can retry it after the lift), "
        "correction re-runs of its refuted subtasks (a crew session waits and ends in the same way; one whose "
        "correction was admitted just before the order ends blocked and cannot be retried; elsewhere the "
        "result is escalated unverified), browser actions and every "
        "tool call, protected effects included."
    ),
    "does_not_end": (
        "Work already running when the order was given (AD-1343 S2): a turn in progress may "
        "finish and post, though each tool call it makes is refused and a browser action it "
        "proposes is dropped; a crew subtask it is running is not re-invoked for another iteration; "
        "a promoted turn the Captain approves while the agent is stopped resumes, with its tool "
        "calls refused; a crew session synthesis it had already begun (its start recorded) runs to "
        "its draft."
    ),
    "not_covered": (
        "Voice and appearance proposals the Captain requests, directly or through the Counselor; "
        "the ship's upkeep of the agent's records (dreams, trust decay); every agent at once "
        "(AD-1343 S3); external harness sessions, which are not_reachable until AD-1342."
    ),
}

LIFT_NOTE: Final = (
    "Dispatch is restored. Work refused while the agent was stopped is not replayed; "
    "refused_while_stopped counts it by seam since the last start. A crew session that was waiting "
    "on the agent continues on its own recovery schedule, or is blocked for the Captain to retry."
)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS agent_stops (
    stop_id      TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    reason       TEXT NOT NULL,
    issued_by    TEXT NOT NULL,
    issued_at    REAL NOT NULL,
    lifted_by    TEXT,
    lifted_at    REAL,
    lift_reason  TEXT,
    refused_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_stops_one_active
    ON agent_stops (agent_id) WHERE lifted_at IS NULL;
"""
_INSERT: Final = (
    "INSERT INTO agent_stops (stop_id, agent_id, reason, issued_by, issued_at) VALUES (?, ?, ?, ?, ?)"
)
_SELECT_ACTIVE: Final = (
    "SELECT stop_id, agent_id, reason, issued_by, issued_at FROM agent_stops WHERE lifted_at IS NULL"
)
_LIFT: Final = (
    "UPDATE agent_stops SET lifted_by = ?, lifted_at = ?, lift_reason = ?, refused_json = ? "
    "WHERE stop_id = ? AND lifted_at IS NULL"
)
_FINAL_COUNTS: Final = (
    "UPDATE agent_stops SET refused_json = ? WHERE stop_id = ? AND lifted_at IS NOT NULL"
)


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")


def _valid_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or len(reason) > MAX_REASON_CHARS:
        raise ValueError(f"AD-1343: a reason of 1..{MAX_REASON_CHARS} characters is required")
    return reason.strip()


async def _rollback_quietly(db: "DatabaseConnection") -> None:
    """Undo an uncommitted write so a later commit cannot land it (the AD-1213 pattern)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1343: rollback after a failed stop write found no open transaction")


async def _commit_or_roll_back(db: "DatabaseConnection", sql: str, params: tuple[Any, ...]) -> None:
    """One statement and its commit; on a failure the transaction is rolled back (so the next
    successful commit cannot land it) and the original error is re-raised. A3: run only as
    ``_write_settled``'s task, which its caller never cancels; a task cancelled by a closing loop
    still rolls back."""
    try:
        await db.execute(sql, params)
        await db.commit()
    except BaseException:
        await _rollback_quietly(db)
        raise


async def _write_settled(
    db: "DatabaseConnection", sql: str, params: tuple[Any, ...],
) -> tuple[Exception | None, asyncio.CancelledError | None]:
    """One statement and its commit, run to its end whatever happens to the caller (A3: R3, R4).

    Cancelling an await on aiosqlite does not stop the call its worker thread was given: a queued
    COMMIT runs even after its future is cancelled, and a ROLLBACK queued behind it then has nothing
    to undo, so a cancellation says nothing about whether the write landed. The write runs in a task
    of its own and the caller waits through a shield (the AD-1198 A-1 pattern of
    ``federation/envelope.py``): the caller's cancellation is held until the write has ended.
    Returns ``(failure, cancellation)``: ``failure`` is None when the commit landed, else the
    write's own error, already rolled back; ``cancellation`` is the caller's, to be raised once
    memory matches the store. Unbounded, as an uncancelled write is.
    """
    write = asyncio.create_task(_commit_or_roll_back(db, sql, params), name="ad1343-agent-stop-write")
    cancellation = await _held_through(write)
    failure = write.exception()  # raises CancelledError only when the write itself was cancelled (a closing loop)
    if failure is None or isinstance(failure, Exception):
        return failure, cancellation
    raise failure


async def _held_through(write: asyncio.Task[Any]) -> asyncio.CancelledError | None:
    """Wait for ``write`` to end through a shield (A3); A4 shares it with the EventLog append.

    The caller's cancellation is held, not delivered to the write, and returned; the first one is kept.
    The write's own outcome is read from its task by the caller. Unbounded, as an uncancelled write is.
    """
    cancellation: asyncio.CancelledError | None = None
    while not write.done():
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError as exc:  # the caller's: the write goes on
            cancellation = cancellation or exc
        except Exception:  # noqa: BLE001 -- the write's own failure, read from its task by the caller
            break
    return cancellation


async def _append_settled(append: Coroutine[Any, Any, Any], warning: str, *args: object) -> asyncio.CancelledError | None:
    """One EventLog append, run to its end whatever happens to the caller (A4: F2), best effort.

    ``EventLog.log`` queues for its writer lock (``substrate/event_log.py:649``) behind any other writer, so a
    caller cancelled there lost the event of an order or lift the store already holds. The append runs in a
    task of its own and the caller waits through the same shield as a store write. A failure of the append is
    logged (``warning``) and not raised, as before: agent_stops.db is authoritative. Returns the caller's
    cancellation, to be raised once the bookkeeping is settled.
    """
    task = asyncio.create_task(append, name="ad1343-agent-stop-event")
    cancellation = await _held_through(task)
    failure = task.exception()  # raises CancelledError only when the append itself was cancelled (a closing loop)
    if failure is not None:
        logger.warning(warning, *args, exc_info=failure)
    return cancellation


@dataclass(frozen=True, slots=True)
class StopRecord:
    """One Captain's order in force: which agent, why, by whom and since when."""

    stop_id: str
    agent_id: str
    reason: str
    issued_by: str
    issued_at: float

    def sender_text(self) -> str:
        """What a sender is told. Names the order, never the Captain's reason."""
        return (
            f"Not delivered: agent {self.agent_id} is stopped by the Captain's order "
            f"(stop {self.stop_id}, since {_utc(self.issued_at)}). Nothing was started "
            "and nothing is queued for later."
        )

    def sender_detail(self) -> dict[str, str]:
        """The refusal as data, for an HTTP body or result metadata."""
        return {
            "code": STOP_REASON_CODE,
            "agent_id": self.agent_id,
            "stop_id": self.stop_id,
            "since": _utc(self.issued_at),
            "message": self.sender_text(),
        }

    def notice(self, callsign: str) -> str:
        """One line for a thread that addressed the stopped agent: the order and its start, never the reason."""
        return (
            f"{callsign} is stopped by the Captain's order (stop {self.stop_id}, since {_utc(self.issued_at)}). "
            "New messages here are not delivered to them until the stop is lifted; "
            "a reply already in progress may still post."
        )

    def refuse_intent(self, intent: IntentMessage, agent_id: str) -> IntentResult | None:
        """A refusal naming the order for an intent sent to this agent; None for a broadcast.

        A broadcast addressed no one, so the stopped agent abstains, as an agent that
        does not handle the intent: a failure row would read to the broadcaster as a fault.
        """
        if intent.target_agent_id != agent_id:
            return None
        text = self.sender_text()
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=False,
            result=text,
            error=text,
            confidence=0.0,
            metadata={STOP_METADATA_KEY: self.sender_detail()},
        )

    def public_dict(self) -> dict[str, Any]:
        """The Captain's view of the order, reason included."""
        return {
            "stop_id": self.stop_id,
            "agent_id": self.agent_id,
            "reason": self.reason,
            "issued_by": self.issued_by,
            "issued_at": self.issued_at,
            "since": _utc(self.issued_at),
        }


@dataclass(frozen=True, slots=True)
class StopIssued:
    record: StopRecord
    already_stopped: bool
    durable: bool


@dataclass(frozen=True, slots=True)
class StopLifted:
    record: StopRecord
    lifted_at: float
    refused: dict[str, int]


class StopNotFound(LookupError):
    """No Captain's stop is in force for the agent."""


class AgentStopped(RuntimeError):
    """A new agentic run refused for a stopped agent: nothing was started (AD-1343 S1, A2).

    Raised, never returned, so no caller can read the refusal as finished work or store it
    as output; each caller maps it to its own not-started vocabulary. The message names the
    order and its start, never the Captain's reason.
    """

    def __init__(self, record: StopRecord) -> None:
        super().__init__(record.sender_text())
        self.record = record


class AgentStopService:
    """Ship's Computer service: the Captain's stop orders and the one question every seam asks."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        event_log: "EventLog | None" = None,
        connection_factory: "ConnectionFactory | None" = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._event_log = event_log
        self._clock = clock
        self._db: "DatabaseConnection | None" = None
        self._active: dict[str, StopRecord] = {}
        self._volatile: set[str] = set()
        self._refused: dict[str, dict[str, int]] = {}
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory = connection_factory

    async def start(self) -> None:
        """Open the store and load every order in force. Raises when the store cannot be opened."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(str(self._data_dir / STORE_FILENAME))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        async with self._db.execute(_SELECT_ACTIVE) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            self._active[row[1]] = StopRecord(row[0], row[1], row[2], row[3], float(row[4]))
        if self._active:
            logger.warning(
                "AD-1343: %d agent(s) remain stopped by the Captain's order: %s",
                len(self._active), ", ".join(sorted(self._active)),
            )

    async def stop(self) -> None:
        """Close the store. The in-memory view is kept: a stopped agent stays refused."""
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None

    def stop_for(self, agent_id: str) -> StopRecord | None:
        """The order in force for ``agent_id``, or None. Memory only."""
        if type(agent_id) is not str:
            return None
        return self._active.get(agent_id)

    def refusal(self, agent_id: str, seam: str) -> StopRecord | None:
        """The order in force for ``agent_id``, counted as one refusal at ``seam``; None when not stopped."""
        if seam not in SEAMS:
            raise ValueError(f"AD-1343: unknown seam {seam!r}")
        record = self.stop_for(agent_id)
        if record is None:
            return None
        counts = self._refused.setdefault(record.stop_id, {})
        counts[seam] = counts.get(seam, 0) + 1
        logger.log(
            logging.INFO if counts[seam] == 1 else logging.DEBUG,
            "AD-1343: refused %s work for %s under the Captain's stop %s (%d at this seam)",
            seam, agent_id, record.stop_id, counts[seam],
        )
        return record

    def active(self) -> tuple[StopRecord, ...]:
        """Every order in force, oldest first."""
        return tuple(sorted(self._active.values(), key=lambda record: record.issued_at))

    def refused_counts(self, stop_id: str) -> dict[str, int]:
        """Refusals by seam under one order since this start."""
        return dict(self._refused.get(stop_id, {}))

    async def issue_stop(self, agent_id: str, *, reason: str) -> StopIssued:
        """Stop one crew agent by the Captain's order.

        Applied to the in-memory view before it is written: if the write fails the agent
        is still stopped, and the answer says the order ends at the next restart. Issuing
        for an agent already stopped returns the order in force. A3: the write runs to its end
        even when the caller is cancelled, so ``durable`` is what the store holds; the
        cancellation is raised once the order, its durability and its event are settled. A4: the
        event's append also runs to its end; the first cancellation is the one raised, and it is
        raised from the write's failure when the order was not written.
        """
        if type(agent_id) is not str or not agent_id:
            raise ValueError("AD-1343: agent_id must be a non-empty str")
        text = _valid_reason(reason)
        async with self._lock:
            existing = self._active.get(agent_id)
            if existing is not None:
                return StopIssued(existing, already_stopped=True, durable=existing.stop_id not in self._volatile)
            record = StopRecord(uuid.uuid4().hex, agent_id, text, CAPTAIN, self._clock())
            self._active[agent_id] = record
            failure, cancellation = await self._write_issued(record)  # A3: settled, so durable is what the store holds
            durable = failure is None  # A4 (F3): the failure is kept for the cancellation's cause
            if not durable:
                self._volatile.add(record.stop_id)
        audit = await self._record_issued(record, durable)  # A4 (F2): run to its end; a cancellation meanwhile is held
        cancellation = cancellation or audit  # A4 (F2): the first cancellation is the one raised (issue)
        if cancellation is not None and failure is not None:
            raise cancellation from failure  # A4 (F3): not written, and the caller is still cancelled
        if cancellation is not None:
            raise cancellation  # A3: held until the order, its durability and its event were settled
        return StopIssued(record, already_stopped=False, durable=durable)

    async def lift_stop(self, agent_id: str, *, reason: str) -> StopLifted:
        """Lift the Captain's stop on one agent.

        Written before it is applied: if the write fails it is rolled back, the agent stays
        stopped and the error propagates. Work refused while stopped is not replayed. The
        counts returned, sent to the EventLog and kept in the row are final: a seam can count
        under this order until the in-memory lift, so a refusal made while the lift was being
        written is included, and the row is brought up to date when one was. A failure of that
        second write is logged and leaves the lift standing. A3: each write runs to its end even
        when the caller is cancelled, so what is applied in memory is what the store holds; the
        cancellation is raised once the lift, its counts and its event are settled. A4: the event's
        append also runs to its end, and the first cancellation is the one raised.
        """
        text = _valid_reason(reason)
        cancellation: asyncio.CancelledError | None = None
        async with self._lock:
            record = self.stop_for(agent_id)
            if record is None:
                raise StopNotFound(agent_id)
            lifted_at = self._clock()
            durable = record.stop_id not in self._volatile
            written = self.refused_counts(record.stop_id)
            if durable:
                if self._db is None:
                    raise RuntimeError("AD-1343: the stop store is closed; the stop stays in force")
                failure, cancellation = await _write_settled(
                    self._db, _LIFT, (CAPTAIN, lifted_at, text, json.dumps(written, sort_keys=True), record.stop_id),
                )
                if failure is not None and cancellation is not None:
                    raise cancellation from failure  # rolled back: the agent stays stopped, and the caller is still cancelled
                if failure is not None:
                    raise failure  # rolled back: the agent stays stopped
            del self._active[agent_id]  # the last moment a seam can count a refusal under this order
            self._volatile.discard(record.stop_id)
            refused = self._refused.pop(record.stop_id, {})
            if durable and refused != written:
                later = await self._write_final_counts(record, refused)
                cancellation = cancellation or later  # A4 (F2): the first cancellation is the one raised, as below
        audit = await self._record_lifted(record, lifted_at, refused)  # A4 (F2): run to its end; a cancellation meanwhile is held
        cancellation = cancellation or audit  # A4 (F2): the first cancellation is the one raised (lift)
        if cancellation is not None:
            raise cancellation  # A3: held until the lift, its counts and its event were settled
        return StopLifted(record, lifted_at, refused)

    async def _write_issued(self, record: StopRecord) -> tuple[Exception | None, asyncio.CancelledError | None]:
        """Write an order, run to its end (A3): ``(failure, cancellation)``. ``failure`` is None when the store
        holds the order, else why it does not (logged: the store is closed, or the write failed and was rolled
        back); A4 (F3) returns it so a cancelled caller's ``CancelledError`` is raised from it, as the lift's is.
        ``cancellation`` is the caller's, if one arrived meanwhile."""
        if self._db is None:
            logger.error(
                "AD-1343: stop %s for %s is in force but NOT written (the stop store is closed); "
                "it ends at the next restart", record.stop_id, record.agent_id,
            )
            return RuntimeError("AD-1343: the stop store is closed"), None
        failure, cancellation = await _write_settled(
            self._db, _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
        )
        if failure is not None:
            logger.error(
                "AD-1343: stop %s for %s is in force but was NOT written; it ends at the next restart",
                record.stop_id, record.agent_id, exc_info=failure,
            )
        return failure, cancellation  # log-and-degrade on a failure: the stop stays in force

    async def _write_final_counts(self, record: StopRecord, refused: dict[str, int]) -> asyncio.CancelledError | None:
        """Bring a lifted row's refusal counts to their final value, run to its end (A3); on failure log it
        (the lift stands). Returns the caller's cancellation, if one arrived while it was written."""
        if self._db is None:  # for the type checker: stop() closes the store only under the lock held here
            return None
        failure, cancellation = await _write_settled(
            self._db, _FINAL_COUNTS, (json.dumps(refused, sort_keys=True), record.stop_id),
        )
        if failure is not None:
            logger.error(
                "AD-1343: stop %s for %s is lifted, but its final refusal counts %s were NOT written; "
                "the row keeps the counts at the moment the lift was written",
                record.stop_id, record.agent_id, refused, exc_info=failure,
            )
        return cancellation

    async def _record_issued(self, record: StopRecord, durable: bool) -> asyncio.CancelledError | None:
        """Tell the EventLog of an order, best effort: the store is authoritative. A4 (F2): the append runs to
        its end whatever happens to the caller; returns the caller's cancellation, if one arrived meanwhile."""
        if self._event_log is None:
            return None
        return await _append_settled(
            self._event_log.log(
                category=STOP_EVENT_CATEGORY,
                event=STOP_ISSUED_EVENT,
                agent_id=record.agent_id,
                data={
                    "stop_id": record.stop_id,
                    "initiated_by": record.issued_by,
                    "issued_at": record.issued_at,
                    "reason_chars": len(record.reason),
                    "durable": durable,
                },
            ),
            "AD-1343: the EventLog did not record stop %s for %s; agent_stops.db is authoritative",
            record.stop_id, record.agent_id,
        )

    async def _record_lifted(
        self, record: StopRecord, lifted_at: float, refused: dict[str, int],
    ) -> asyncio.CancelledError | None:
        """Tell the EventLog of a lift, best effort: the store is authoritative. A4 (F2): the append runs to
        its end whatever happens to the caller; returns the caller's cancellation, if one arrived meanwhile."""
        if self._event_log is None:
            return None
        return await _append_settled(
            self._event_log.log(
                category=STOP_EVENT_CATEGORY,
                event=STOP_LIFTED_EVENT,
                agent_id=record.agent_id,
                data={
                    "stop_id": record.stop_id,
                    "initiated_by": CAPTAIN,
                    "issued_at": record.issued_at,
                    "lifted_at": lifted_at,
                    "refused": refused,
                },
            ),
            "AD-1343: the EventLog did not record the lift of stop %s; agent_stops.db is authoritative",
            record.stop_id,
        )


def active_stop(gate: object, agent_id: object, seam: str) -> StopRecord | None:
    """The order in force for ``agent_id``, counted as one refusal at ``seam``, or None.

    ``gate`` is whatever the seam holds. Only a real ``AgentStopService`` answers, and only
    an exact ``StopRecord`` counts, so a seam built without the service (a test double, an
    older wiring) routes exactly as before. The production wiring is pinned by
    tests/test_ad1343_stop_crossing.py.
    """
    if not isinstance(gate, AgentStopService) or type(agent_id) is not str:
        return None
    record = gate.refusal(agent_id, seam)
    return record if type(record) is StopRecord else None


def tool_refusal(gate: object, agent_id: object, tool_id: str) -> ToolResult | None:
    """The tool sink's refusal for a stopped agent, or None."""
    stopped = active_stop(gate, agent_id, SEAM_TOOL)
    if stopped is None:
        return None
    return ToolResult(
        error=f"Tool {tool_id!r} was not run. {stopped.sender_text()}",
        metadata={STOP_METADATA_KEY: stopped.sender_detail()},
    )


def standing_stop(gate: object, agent_id: object) -> StopRecord | None:
    """The order in force for ``agent_id``, or None, WITHOUT counting a refusal (A2).

    For an eligibility question asked about many candidates (crew assignment), where an
    answer refuses no work. The same type guards as ``active_stop``.
    """
    if type(agent_id) is not str or not isinstance(gate, AgentStopService):
        return None
    found = gate.stop_for(agent_id)
    return found if type(found) is StopRecord else None


def refuse_new_run(runtime: object, agent_id: object) -> None:
    """Raise ``AgentStopped`` when ``agent_id`` is stopped: the shared entry of every new agentic run (A2).

    The gate is the one the run's own tool calls are refused by, ``runtime.tool_registry.stop_gate``:
    the ship's runtime and the projected correction runtime (``crew_verifier.py``) both carry it.
    """
    gate = getattr(getattr(runtime, "tool_registry", None), "stop_gate", None)
    stopped = active_stop(gate, agent_id, SEAM_AGENTIC_RUN)
    if stopped is not None:
        raise AgentStopped(stopped)
