## Amendment A4 (2026-10-19): review round 3 (F1–F3)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19 — against the staged candidate on HEAD `04100dab` (index = working tree per `git status`; tree id as reported by the orchestrator, `5a3e8318`)

### Section 34: `src/probos/agent_stop.py` (F2, F3; scope)

34.1 `S1_SCOPE["does_not_end"]` (F1, D39)
<<<<<<< SEARCH
        "a promoted turn the Captain approves while the agent is stopped resumes, with its tool "
        "calls refused."
    ),
=======
        "a promoted turn the Captain approves while the agent is stopped resumes, with its tool "
        "calls refused; a crew session synthesis it had already begun (its start recorded) runs to "
        "its draft."
    ),
>>>>>>> REPLACE

34.2 import
<<<<<<< SEARCH
from collections.abc import Callable
=======
from collections.abc import Callable, Coroutine
>>>>>>> REPLACE

34.3 one shield for the store's writes and the EventLog's appends (F2, D40)
<<<<<<< SEARCH
    write = asyncio.create_task(_commit_or_roll_back(db, sql, params), name="ad1343-agent-stop-write")
    cancellation: asyncio.CancelledError | None = None
    while not write.done():
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError as exc:  # the caller's: the write goes on
            cancellation = cancellation or exc
        except Exception:  # noqa: BLE001 -- the write's own failure, read from its task below
            break
    failure = write.exception()  # raises CancelledError only when the write itself was cancelled (a closing loop)
    if failure is None or isinstance(failure, Exception):
        return failure, cancellation
    raise failure
=======
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
>>>>>>> REPLACE

34.4 `issue_stop` (F2, F3)
<<<<<<< SEARCH
        cancellation is raised once the order, its durability and its event are settled.
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
            durable, cancellation = await self._write_issued(record)  # A3: settled, so durable is what the store holds
            if not durable:
                self._volatile.add(record.stop_id)
        await self._record_issued(record, durable)
        if cancellation is not None:
            raise cancellation  # A3: held until the order, its durability and its event were settled
        return StopIssued(record, already_stopped=False, durable=durable)
=======
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
>>>>>>> REPLACE

34.5 `lift_stop` docstring
<<<<<<< SEARCH
        cancellation is raised once the lift, its counts and its event are settled.
        """
        text = _valid_reason(reason)
=======
        cancellation is raised once the lift, its counts and its event are settled. A4: the event's
        append also runs to its end, and the first cancellation is the one raised.
        """
        text = _valid_reason(reason)
>>>>>>> REPLACE

34.6 `lift_stop` tail (F2)
<<<<<<< SEARCH
            if durable and refused != written:
                cancellation = await self._write_final_counts(record, refused) or cancellation
        await self._record_lifted(record, lifted_at, refused)
        if cancellation is not None:
=======
            if durable and refused != written:
                later = await self._write_final_counts(record, refused)
                cancellation = cancellation or later  # A4 (F2): the first cancellation is the one raised, as below
        audit = await self._record_lifted(record, lifted_at, refused)  # A4 (F2): run to its end; a cancellation meanwhile is held
        cancellation = cancellation or audit  # A4 (F2): the first cancellation is the one raised (lift)
        if cancellation is not None:
>>>>>>> REPLACE

34.7 `_write_issued` returns its failure (F3, D41)
<<<<<<< SEARCH
    async def _write_issued(self, record: StopRecord) -> tuple[bool, asyncio.CancelledError | None]:
        """Write an order, run to its end (A3): ``(durable, cancellation)``. Not durable (logged) when the
        store is closed or the write fails; ``cancellation`` is the caller's, if one arrived meanwhile."""
        if self._db is None:
            logger.error(
                "AD-1343: stop %s for %s is in force but NOT written (the stop store is closed); "
                "it ends at the next restart", record.stop_id, record.agent_id,
            )
            return False, None
        failure, cancellation = await _write_settled(
            self._db, _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
        )
        if failure is not None:
            logger.error(
                "AD-1343: stop %s for %s is in force but was NOT written; it ends at the next restart",
                record.stop_id, record.agent_id, exc_info=failure,
            )
            return False, cancellation  # log-and-degrade: the stop stays in force
        return True, cancellation
=======
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
>>>>>>> REPLACE

34.8 the two appends (F2)
<<<<<<< SEARCH
    async def _record_issued(self, record: StopRecord, durable: bool) -> None:
        """Tell the EventLog of an order, best effort: the store is authoritative."""
        if self._event_log is None:
            return
        try:
            await self._event_log.log(
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
            )
        except Exception:
            logger.warning(
                "AD-1343: the EventLog did not record stop %s for %s; agent_stops.db is authoritative",
                record.stop_id, record.agent_id, exc_info=True,
            )

    async def _record_lifted(self, record: StopRecord, lifted_at: float, refused: dict[str, int]) -> None:
        """Tell the EventLog of a lift, best effort: the store is authoritative."""
        if self._event_log is None:
            return
        try:
            await self._event_log.log(
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
            )
        except Exception:
            logger.warning(
                "AD-1343: the EventLog did not record the lift of stop %s; agent_stops.db is authoritative",
                record.stop_id, exc_info=True,
            )
=======
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
>>>>>>> REPLACE

### Section 35: `src/probos/cognitive/crew_synth.py` (F1, D39)

35.1 signature and docstring
<<<<<<< SEARCH
        outcomes: tuple["SessionConvergenceOutcome", ...],
    ) -> SessionSynthesisDraft:
        """Produce one bounded session draft without completion or learning writes.

        AD-1343 A3: raises ``AgentStopped`` before the model call when the facilitator is stopped by
        the Captain's order; invalid inputs still fail first, as before.
        """
=======
        outcomes: tuple["SessionConvergenceOutcome", ...],
        admitted_synthesis: bool = False,
    ) -> SessionSynthesisDraft:
        """Produce one bounded session draft without completion or learning writes.

        AD-1343 A3: raises ``AgentStopped`` before the model call when the facilitator is stopped by
        the Captain's order; invalid inputs still fail first, as before. A4 (F1): ``admitted_synthesis=True``
        is passed only by the finalizer's owned resume once its durable synthesis claim is made (pinned by
        tests/test_ad1343_stop_seam_inventory.py, I18): that synthesis was admitted at the finalizer's own
        stop check before the claim, so it is not refused again (S1_SCOPE ``does_not_end``). Anything but
        ``True`` is refused as before.
        """
>>>>>>> REPLACE

35.2 the check
<<<<<<< SEARCH
        stopped = active_stop(getattr(self._runtime, "agent_stops", None), producer_key, SEAM_AGENTIC_RUN)
        if stopped is not None:
            raise AgentStopped(stopped)
=======
        if admitted_synthesis is not True:  # A4 (F1): claimed by the owned resume after its own check; not refused again
            stopped = active_stop(getattr(self._runtime, "agent_stops", None), producer_key, SEAM_AGENTIC_RUN)
            if stopped is not None:
                raise AgentStopped(stopped)
>>>>>>> REPLACE

### Section 36: `src/probos/cognitive/crew_finalizer.py` (F1, D39)

36.1 the resume passes its own admission
<<<<<<< SEARCH
        await self._claim_owned_synthesis(session)
        try:
            draft = await self._synthesizer.synthesize_for_session(
                parent_id=session.task_id,
                producer_agent_id=session.facilitator_id,
                producer_instructions=instructions,
                goal=session.goal,
                success_criteria=session.success_criteria,
                expected_deliverable=session.expected_deliverable,
                outcomes=tuple(item.outcome for item in publications),
            )
        except AgentStopped as exc:  # A3 (R1): stopped while the synthesis was claimed; nothing was synthesized
            raise ValueError("synthesis_producer_unavailable") from exc
=======
        # A4 (F1): the check above is the admission; the claim records it. A stop landing after the check runs the
        # admitted synthesis (S1_SCOPE does_not_end): a refusal after the claim would leave a fence that every later
        # resume reads as an interrupted synthesis, though nothing ran.
        admission = await self._claim_owned_synthesis(session)
        try:
            draft = await self._synthesizer.synthesize_for_session(
                parent_id=session.task_id,
                producer_agent_id=session.facilitator_id,
                producer_instructions=instructions,
                goal=session.goal,
                success_criteria=session.success_criteria,
                expected_deliverable=session.expected_deliverable,
                outcomes=tuple(item.outcome for item in publications),
                admitted_synthesis=admission is not None,  # A4 (F1): only a synthesis this resume has just claimed
            )
        except AgentStopped as exc:  # A3 (R1), A4: a session with no owned steps, so nothing was claimed or synthesized
            raise ValueError("synthesis_producer_unavailable") from exc
>>>>>>> REPLACE

36.2 the claim returns its admission
<<<<<<< SEARCH
    async def _claim_owned_synthesis(self, session: CrewSessionContract) -> None:
        snapshot = await self._owned_steps_snapshot(session.task_id)
        if snapshot is None:
            return
=======
    async def _claim_owned_synthesis(self, session: CrewSessionContract) -> owned_steps.OwnedStepMutationResult | None:
        """Claim the owned synthesis (the AD-1192 fence). A4 (F1): the admission is returned once the claim is made,
        so the synthesis it records is admitted; None when the session has no owned steps and nothing is claimed."""
        snapshot = await self._owned_steps_snapshot(session.task_id)
        if snapshot is None:
            return None
>>>>>>> REPLACE

<<<<<<< SEARCH
        if admission.disposition != "new":
            raise owned_steps.OwnedStepsError(
                "owned_steps_synthesis_interrupted", parent_id=session.task_id,
                actions=("inspect_source", "interrupted_work"),
            )
=======
        if admission.disposition != "new":
            raise owned_steps.OwnedStepsError(
                "owned_steps_synthesis_interrupted", parent_id=session.task_id,
                actions=("inspect_source", "interrupted_work"),
            )
        return admission  # A4 (F1): the durable claim is made; the synthesis it records is admitted
>>>>>>> REPLACE

### Section 37: `tests/test_ad1343_agent_stop_settle.py` (F2, F3)

37.1 docstring
<<<<<<< SEARCH
* S4 (golden): with no cancellation the blocked COMMIT simply lands; the issue and the lift each run one statement, no ROLLBACK.
=======
* S4 (golden): with no cancellation the blocked COMMIT simply lands; the issue and the lift each run one statement, no ROLLBACK.
* S5, S6 (A4, F2): an issue or lift cancelled while its EventLog append waits behind another writer keeps its event.
* S7, S8 (A4, F2): a second cancellation during that append, after one was held through the COMMIT, loses no event, and the
  first cancellation is the one raised.
* S9 (A4, F3): a cancelled issue whose write failed raises ``CancelledError`` caused by the failure.
* S10 (golden): with no cancellation the append waits behind the other writer, lands, and nothing is logged as lost.

The other writer is real: a second ``EventLog.log`` takes the writer lock (``substrate/event_log.py:649``) and waits for
SQLite's write lock, which a test-held ``BEGIN IMMEDIATE`` keeps; every later append queues on the writer lock.
>>>>>>> REPLACE

37.2 imports
<<<<<<< SEARCH
import asyncio
import contextlib
import json
import sqlite3
=======
import asyncio
import collections
import contextlib
import json
import logging
import sqlite3
>>>>>>> REPLACE

<<<<<<< SEARCH
from probos.agent_stop import STORE_FILENAME, StopNotFound
=======
from probos.agent_stop import STOP_ISSUED_EVENT, STOP_LIFTED_EVENT, STORE_FILENAME, StopNotFound
>>>>>>> REPLACE

37.3 helpers and tests, appended after B5
<<<<<<< SEARCH
        assert isinstance(raised.value.__cause__, sqlite3.OperationalError)  # the cancellation carries the write's failure
        assert service.stop_for(AGENT) == issued.record  # rolled back: the agent stays stopped
    assert _stop_rows(tmp_path)[0]["lifted_at"] is None
=======
        assert isinstance(raised.value.__cause__, sqlite3.OperationalError)  # the cancellation carries the write's failure
        assert service.stop_for(AGENT) == issued.record  # rolled back: the agent stays stopped
    assert _stop_rows(tmp_path)[0]["lifted_at"] is None


_HOLDER = "ad1343_holder"


class _AppendSeen(EventLog):
    """A real EventLog that marks each append, by event name, just before it runs (test-local)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.seen: collections.defaultdict[str, asyncio.Event] = collections.defaultdict(asyncio.Event)

    async def log(self, *args: Any, **kwargs: Any) -> int | None:
        self.seen[str(kwargs.get("event", ""))].set()
        return await super().log(*args, **kwargs)


@contextlib.contextmanager
def _sqlite_writer_held(events_db: Path) -> Iterator[sqlite3.Connection]:
    """A test-held ``BEGIN IMMEDIATE`` on ``events.db``: while it is open no append can take SQLite's write lock."""
    conn = sqlite3.connect(events_db, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("COMMIT")
        conn.close()


async def _another_writer(event_log: _AppendSeen) -> asyncio.Task[Any]:
    """Another EventLog writer: it holds the writer lock while it waits for SQLite's (held by the test)."""
    holder = asyncio.create_task(event_log.log(category="ad1343_test", event=_HOLDER))
    await asyncio.wait_for(event_log.seen[_HOLDER].wait(), timeout=_BOUND)
    assert not holder.done()  # premise: it holds the writer lock and waits on the test's SQLite transaction
    return holder


def _issued_events(events_db: Path) -> list[dict[str, Any]]:
    with contextlib.closing(sqlite3.connect(events_db)) as conn:
        return [json.loads(data) for (data,) in conn.execute("SELECT data FROM events WHERE event = 'agent_stop_issued'")]


# S5
async def test_an_issue_cancelled_while_its_event_waits_for_another_writer_keeps_its_event(tmp_path: Path) -> None:
    stops, events_db = tmp_path / "stops", tmp_path / "events.db"
    event_log = _AppendSeen(db_path=events_db)
    await event_log.start()
    try:
        async with _service(stops, event_log=event_log, clock=_Clock()) as service:
            with _sqlite_writer_held(events_db) as writer:
                holder = await _another_writer(event_log)
                issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
                await asyncio.wait_for(event_log.seen[STOP_ISSUED_EVENT].wait(), timeout=_BOUND)
                assert not issue.done()  # premise: the order is written and its event waits behind the other writer
                assert len(_stop_rows(stops)) == 1  # premise: the COMMIT landed before the event was asked
                issue.cancel()
                writer.execute("COMMIT")  # the other writer goes on, then the order's event
                await asyncio.wait({issue, holder}, timeout=_BOUND)
            assert holder.done() and holder.exception() is None  # premise: the other writer landed
            assert issue.cancelled()  # the caller's cancellation still propagated
            in_force = service.stop_for(AGENT)
            assert in_force is not None
            again = await service.issue_stop(AGENT, reason=REASON)
            assert again.already_stopped is True and again.durable is True
    finally:
        await event_log.stop()
    assert [(e["stop_id"], e["durable"]) for e in _issued_events(events_db)] == [(in_force.stop_id, True)]  # F2: kept


# S6
async def test_a_lift_cancelled_while_its_event_waits_for_another_writer_keeps_its_event(tmp_path: Path) -> None:
    stops, events_db = tmp_path / "stops", tmp_path / "events.db"
    event_log = _AppendSeen(db_path=events_db)
    await event_log.start()
    try:
        async with _service(stops, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True  # premise: written, so the lift writes its row
            with _sqlite_writer_held(events_db) as writer:
                holder = await _another_writer(event_log)
                lift = asyncio.create_task(service.lift_stop(AGENT, reason=LIFT_REASON))
                await asyncio.wait_for(event_log.seen[STOP_LIFTED_EVENT].wait(), timeout=_BOUND)
                assert not lift.done()  # premise: only the lift's event is pending
                assert service.stop_for(AGENT) is None  # premise: the lift is written and applied
                lift.cancel()
                writer.execute("COMMIT")
                await asyncio.wait({lift, holder}, timeout=_BOUND)
            assert holder.done() and holder.exception() is None
            assert lift.cancelled()
    finally:
        await event_log.stop()
    assert _stop_rows(stops)[0]["lifted_at"] is not None
    assert [(e["stop_id"], e["refused"]) for e in _lifted_events(events_db)] == [(issued.record.stop_id, {})]  # F2: kept


# S7
async def test_a_second_cancellation_at_the_issue_event_keeps_the_event_and_raises_the_first(tmp_path: Path) -> None:
    stops, events_db = tmp_path / "stops", tmp_path / "events.db"
    factory = _CommitSeenFactory()
    event_log = _AppendSeen(db_path=events_db)
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            factory.seen.clear()  # start() committed its schema
            with _sqlite_writer_held(events_db) as writer:
                holder = await _another_writer(event_log)
                with _read_held(stops) as reader:
                    issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
                    await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
                    assert not issue.done()  # premise: the INSERT ran and its COMMIT waits on the worker
                    issue.cancel("first")  # held through the COMMIT
                    reader.execute("COMMIT")
                await asyncio.wait_for(event_log.seen[STOP_ISSUED_EVENT].wait(), timeout=_BOUND)
                assert not issue.done()  # premise: the COMMIT landed and the event waits behind the other writer
                issue.cancel("second")
                writer.execute("COMMIT")
                await asyncio.wait({issue, holder}, timeout=_BOUND)
            assert issue.done()
            with pytest.raises(asyncio.CancelledError) as raised:
                issue.result()
            assert raised.value.args == ("first",)  # the cancellation held through the COMMIT is the one raised
            in_force = service.stop_for(AGENT)
            assert in_force is not None
    finally:
        await event_log.stop()
    assert [(e["stop_id"], e["durable"]) for e in _issued_events(events_db)] == [(in_force.stop_id, True)]


# S8
async def test_a_second_cancellation_at_the_lift_event_keeps_the_event_and_raises_the_first(tmp_path: Path) -> None:
    stops, events_db = tmp_path / "stops", tmp_path / "events.db"
    factory = _CommitSeenFactory()
    event_log = _AppendSeen(db_path=events_db)
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True
            factory.seen.clear()
            with _sqlite_writer_held(events_db) as writer:
                holder = await _another_writer(event_log)
                with _read_held(stops) as reader:
                    lift = asyncio.create_task(service.lift_stop(AGENT, reason=LIFT_REASON))
                    await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
                    assert not lift.done()  # premise: the lift's UPDATE ran and its COMMIT waits on the worker
                    lift.cancel("first")
                    reader.execute("COMMIT")
                await asyncio.wait_for(event_log.seen[STOP_LIFTED_EVENT].wait(), timeout=_BOUND)
                assert not lift.done()  # premise: the lift landed and its event waits behind the other writer
                lift.cancel("second")
                writer.execute("COMMIT")
                await asyncio.wait({lift, holder}, timeout=_BOUND)
            assert lift.done()
            with pytest.raises(asyncio.CancelledError) as raised:
                lift.result()
            assert raised.value.args == ("first",)
            assert service.stop_for(AGENT) is None
    finally:
        await event_log.stop()
    assert [e["stop_id"] for e in _lifted_events(events_db)] == [issued.record.stop_id]


# S9
async def test_an_issue_whose_write_fails_under_a_held_cancellation_raises_it_from_the_failure(tmp_path: Path) -> None:
    factory = _FlakyFactory("INSERT")
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
        await asyncio.sleep(0)  # one loop turn: the issue waits on its write task, which has not yet run
        assert not issue.done() and "INSERT" not in [sql.lstrip().split()[0] for sql in factory.statements]  # premise
        issue.cancel()  # held until the write has ended
        with pytest.raises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(issue, timeout=_BOUND)
        assert "INSERT" in [sql.lstrip().split()[0] for sql in factory.statements]  # premise: the write ran, and failed
        assert isinstance(raised.value.__cause__, sqlite3.OperationalError)  # F3: the cancellation carries the failure
        in_force = service.stop_for(AGENT)
        assert in_force is not None  # the order is in force although unwritten
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force and again.durable is False
    assert _stop_rows(tmp_path) == []


# S10 (golden)
async def test_an_uncancelled_event_waits_for_another_writer_and_lands(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    stops, events_db = tmp_path / "stops", tmp_path / "events.db"
    event_log = _AppendSeen(db_path=events_db)
    await event_log.start()
    try:
        with caplog.at_level(logging.WARNING, logger="probos.agent_stop"):
            async with _service(stops, event_log=event_log, clock=_Clock()) as service:
                with _sqlite_writer_held(events_db) as writer:
                    holder = await _another_writer(event_log)
                    issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
                    await asyncio.wait_for(event_log.seen[STOP_ISSUED_EVENT].wait(), timeout=_BOUND)
                    assert not issue.done()  # premise: the event waits behind the other writer
                    writer.execute("COMMIT")
                    issued = await asyncio.wait_for(issue, timeout=_BOUND)
                    await asyncio.wait({holder}, timeout=_BOUND)
                assert issued.durable is True and issued.already_stopped is False
    finally:
        await event_log.stop()
    assert [(e["stop_id"], e["durable"]) for e in _issued_events(events_db)] == [(issued.record.stop_id, True)]
    assert [r for r in caplog.records if r.name == "probos.agent_stop" and r.levelno >= logging.WARNING] == []
>>>>>>> REPLACE

### Section 38: `tests/test_ad1343_stop_crossing_resume.py` (X10b; F1)

38.1 docstring
<<<<<<< SEARCH
- X10b the race: the stop lands after the claim, the synthesizer refuses, and the same ``ValueError``
       is raised;
=======
- X10b the race (A4, F1): the stop lands right after the durable claim. The claimed synthesis was
       admitted at the finalizer's check, so it runs to completion; no claim is left behind;
>>>>>>> REPLACE

(Builder: the stray second `=======` that the Architect's draft showed here was removed by the orchestrator, as the Architect's note instructs.)

38.2 X10b rewritten (each change states why inline)
<<<<<<< SEARCH
# X10b
async def test_resume_with_a_stop_landing_after_the_synthesis_claim_is_refused_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        work = case.stores.work
        claimed = work.claim_owned_synthesis
        claims: list[bool] = []

        async def claim_then_stop(*args: Any, **kwargs: Any) -> Any:
            # The Captain's order lands in the window between the finalizer's check and the synthesizer's.
            claims.append(stops.stop_for(FACILITATOR) is None)
            await stops.issue_stop(FACILITATOR, reason=REASON)
            return await claimed(*args, **kwargs)

        monkeypatch.setattr(work, "claim_owned_synthesis", claim_then_stop)
        assert stops.stop_for(FACILITATOR) is None  # premise: the finalizer's own check will pass

        with pytest.raises(ValueError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert claims == [True]  # premise: the claim was reached once, with no order in force until it
        assert stops.stop_for(FACILITATOR) is not None  # premise: the order landed in the window
        assert str(refused.value) == "synthesis_producer_unavailable"  # AgentStopped is mapped, never surfaced
        assert rig.synth.requests == []  # the synthesizer refused before its model call
        assert len(rig.judge.requests) == 1  # premise: the child was verified, so the resume reached the synthesis step
        assert await rig.synthesis_claim() is not None  # premise: the stop landed after the claim
        record = stops.stop_for(FACILITATOR)
        assert record is not None and stops.refused_counts(record.stop_id) == {"agentic_run": 1}
=======
# X10b
async def test_resume_with_a_stop_landing_after_the_synthesis_claim_completes_the_admitted_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_network: TrustNetwork,
) -> None:
    # A4 (F1): round 3 showed this race refused after the claim and left a durable fence, so every resume after the lift
    # was read as an interrupted synthesis though nothing ran. The test asserted that leftover claim; it now asserts the
    # admitted synthesis completes and no stranded state remains.
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        work = case.stores.work
        claimed = work.claim_owned_synthesis
        claims: list[str] = []

        async def claim_then_stop(*args: Any, **kwargs: Any) -> Any:
            # The reviewer's window: the real claim has succeeded, then the Captain's order lands before synthesis.
            admission = await claimed(*args, **kwargs)
            claims.append(admission.disposition)
            await stops.issue_stop(FACILITATOR, reason=REASON)
            return admission

        monkeypatch.setattr(work, "claim_owned_synthesis", claim_then_stop)
        assert stops.stop_for(FACILITATOR) is None  # premise: the finalizer's own check will pass

        try:
            completed = await rig.finalizer.resume(rig.parent_id)
        except (ValueError, owned_steps.OwnedStepsError) as exc:
            pytest.fail(f"a synthesis admitted before the order was refused after its claim: {exc!r}")

        assert claims == ["new"]  # premise: the claim was made, once, before the order
        record = stops.stop_for(FACILITATOR)
        assert record is not None  # premise: the order landed after the claim and is still in force
        assert completed.completed is True and completed.state == "done"  # the admitted synthesis ran to its end
        assert (len(rig.judge.requests), len(rig.synth.requests)) == (2, 1)  # one synthesis, one final verification
        assert await rig.synthesis_claim() is not None  # the claim records a synthesis that ran
        assert stops.refused_counts(record.stop_id) == {}  # admitted work is not a refusal

        lifted = await stops.lift_stop(FACILITATOR, reason=LIFT_REASON)
        assert lifted.refused == {}
        again = await rig.finalizer.resume(rig.parent_id)  # lift -> second resume: nothing is stranded or re-run
        assert again.state == "done" and len(rig.synth.requests) == 1
>>>>>>> REPLACE

### Section 39: `tests/test_ad1343_agent_stop_verify.py` (Y2; F1)

39.1 docstring
<<<<<<< SEARCH
* Y1: ``CrewSynthesizer.synthesize_for_session`` raises ``AgentStopped`` before its model call when the facilitator is stopped
  (counted once, at ``agentic_run``), after the inputs are validated.
=======
* Y1: ``CrewSynthesizer.synthesize_for_session`` raises ``AgentStopped`` before its model call when the facilitator is stopped
  (counted once, at ``agentic_run``), after the inputs are validated.
* Y2 (A4, F1): ``admitted_synthesis=True`` runs the draft for a stopped facilitator with no refusal counted; any other value
  (a truthy ``1``) is refused as before.
>>>>>>> REPLACE

39.2 Y2, after Y1
<<<<<<< SEARCH
        # Invalid inputs fail first, as before, and are not counted as a refusal.
        with pytest.raises(ValueError, match="session_synthesis_input_invalid"):
            await asyncio.wait_for(call(synthesizer, criteria=()), timeout=_BOUND)
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}


# T35
=======
        # Invalid inputs fail first, as before, and are not counted as a refusal.
        with pytest.raises(ValueError, match="session_synthesis_input_invalid"):
            await asyncio.wait_for(call(synthesizer, criteria=()), timeout=_BOUND)
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}


# Y2
async def test_synthesize_for_session_runs_an_admitted_synthesis_for_a_stopped_facilitator(tmp_path: Path) -> None:
    class _Drafting:
        """A model client that counts its calls and answers a final draft."""

        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def complete(self, request: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls.append(request)
            return SimpleNamespace(content=FINAL_DRAFT, tokens_used=7)

    accepted = SimpleNamespace(
        accepted=True,
        status="converged",
        result=SubtaskResult(work_item_id=CHILD, spec_id=SPEC_ID, agent_id="ad1343_builder_0_00000003", output=CORRECTED, status="done"),
    )

    def call(synthesizer: CrewSynthesizer, admitted: Any) -> Any:
        return synthesizer.synthesize_for_session(
            parent_id="ad1343-parent-0001", producer_agent_id=AGENT, producer_instructions=INSTRUCTIONS, goal=TASK,
            success_criteria=("requirement X is met",), expected_deliverable="the evidence for requirement X",
            outcomes=(accepted,), admitted_synthesis=admitted,
        )

    async with _service(tmp_path, clock=_Clock()) as service:
        llm = _Drafting()
        synthesizer = CrewSynthesizer(
            llm_client=llm, work_item_store=_FakeStore(), trust_network=TrustNetwork(), episodic_memory=None,
            attachment_store=None, runtime=_runtime(service),
        )
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        assert service.stop_for(AGENT) == record  # premise

        draft = await asyncio.wait_for(call(synthesizer, True), timeout=_BOUND)
        assert draft == SessionSynthesisDraft(producer_agent_id=AGENT, final_text=FINAL_DRAFT, tokens_used=7)
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {}  # admitted work is not a refusal

        with pytest.raises(AgentStopped):
            await asyncio.wait_for(call(synthesizer, 1), timeout=_BOUND)  # fail closed: truthy is not True
        assert len(llm.calls) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}


# T35
>>>>>>> REPLACE

### Section 40: `tests/test_ad1343_stop_seam_inventory.py` (I18; F1)

40.1
<<<<<<< SEARCH
_PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops"})  # recorded as "name=value" on any call passing one
=======
_PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops", "admitted_synthesis"})  # recorded as "name=value" on any call passing one
>>>>>>> REPLACE

40.2
<<<<<<< SEARCH
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session"): "facilitator: SEAM_AGENTIC_RUN at the entry",
=======
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session"):
        "facilitator: SEAM_AGENTIC_RUN at the entry, unless the owned resume claimed it after its own check (I18)",
>>>>>>> REPLACE

40.3
<<<<<<< SEARCH
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})
=======
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})
# A4 (F1): the one place a synthesis is admitted past the facilitator's stop: the owned resume, from its own claim.
_ADMITTED_SYNTHESIS_SITES: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "admitted_synthesis=admission is not None"),
})
>>>>>>> REPLACE

40.4
<<<<<<< SEARCH
def test_only_the_agents_own_turns_pass_admitted_turn() -> None:
    found = {(c.file, c.function, k) for c in _census() for k in c.keywords if k.startswith("admitted_turn=")}
    assert found == _ADMITTED_TURN_SITES, sorted(found ^ _ADMITTED_TURN_SITES)
=======
def test_only_the_agents_own_turns_pass_admitted_turn() -> None:
    found = {(c.file, c.function, k) for c in _census() for k in c.keywords if k.startswith("admitted_turn=")}
    assert found == _ADMITTED_TURN_SITES, sorted(found ^ _ADMITTED_TURN_SITES)


def test_only_the_owned_resume_passes_admitted_synthesis() -> None:
    """I18 (A4, F1): a synthesis passes the facilitator's stop only when the owned resume has just claimed it."""
    found = {(c.file, c.function, k) for c in _census() for k in c.keywords if k.startswith("admitted_synthesis=")}
    assert found == _ADMITTED_SYNTHESIS_SITES, sorted(found ^ _ADMITTED_SYNTHESIS_SITES)
>>>>>>> REPLACE

### Tests (A4)

| # | File | Must show | RED on staged |
|---|---|---|---|
| X10b′ | crossing_resume | Section 38: the stop lands after the real claim; the resume completes `done`; (judge, synth) = (2, 1); claim present; refusals `{}`; lift then a second resume stays `done` with no new synthesis | yes (`ValueError`) |
| Y2 | verify | Section 39 | yes (`TypeError`: no such keyword) |
| I18 | inventory | Section 40 | yes (no site) |
| S5 | settle | issue cancelled at its append: the event is kept, `durable True` | yes (no event) |
| S6 | settle | lift cancelled at its append: the event is kept | yes (no event) |
| S7 | settle | `first` held through the COMMIT, `second` at the append: args `("first",)`, event kept | yes (`("second",)`, no event) |
| S8 | settle | the same, for the lift | yes |
| S9 | settle | cancelled issue, INSERT fails: `__cause__` is `OperationalError`; volatile; no row | yes (`__cause__ None`) |
| S10 | settle | golden: an append behind another writer lands; no WARNING | no |

**Goldens (no stop, no cancellation: unchanged behaviour):** X10 golden (`test_resume_with_no_order_in_force_completes_as_before`), Y1's golden half, S4, S10, T9 (event content and keys), T10 (a failing EventLog: one WARNING per lost event), T12 (closed store).

**Existing tests that change:** `test_ad1343_stop_crossing_resume.py` (X10b, docstring); `test_ad1343_stop_seam_inventory.py` (`_PINNED_KEYWORDS`, one `_CREW_MODEL_CALLS` description, new I18); `test_ad1343_agent_stop_settle.py` (docstring, imports, appended tests); `test_ad1343_agent_stop_verify.py` (docstring, Y2).

**Checked; no change needed:**
- Fakes and wrappers of `synthesize_for_session` all take `*args, **kwargs`: `test_ad1192:2484`, `test_ad1343_stop_crossing_finalizer.py:164`, `test_ad1127:4139-4150`.
- `test_ad1126:6112-6126` only requires every parameter to be annotated; `admitted_synthesis: bool` is.
- `test_ad1195`: the `.log(` calls stay in `AgentStopService._record_issued` and `_record_lifted` with the same module constants, so the pair and site census is unchanged.
- T10: the WARNING text still carries `stop_id`.
- T12: the closed-store issue is still `durable False`, with one ERROR.
- T29 (a) to (d2) and B5: unchanged contracts.
- No test names `_write_issued`, `_record_issued`, `_record_lifted`, `_write_settled` or `_claim_owned_synthesis`, except `_SOURCE_ORDER`'s callee name (unchanged).

**Focused gate:** A3's command, unchanged. Then the preflights: srp-size 92, and `git diff --exit-code docs/development/*baseline*.yaml`.

### Mutation rows (A4; whole stripped lines, unique per file)

| ID | File: anchor → mutant | Killed by |
|---|---|---|
| B1 | agent_stop.py `await asyncio.shield(write)` → `await write` (now in `_held_through`, shared) | S1–S3, S5–S8 |
| B2 | agent_stop.py `cancellation = cancellation or exc` → `raise` | S2, S3, S5 |
| C1 | agent_stop.py `cancellation = await _held_through(task)` → `cancellation = None; await task` | S5–S8 |
| C2 | agent_stop.py `logger.warning(warning, *args, exc_info=failure)` → `pass` | T10 |
| E1a | agent_stop.py `cancellation = cancellation or audit  # A4 (F2): the first cancellation is the one raised (issue)` → `cancellation = audit or cancellation` | S7 |
| E1b | same anchor → `cancellation = cancellation` | S5 |
| E2a | agent_stop.py `cancellation = cancellation or audit  # A4 (F2): the first cancellation is the one raised (lift)` → `cancellation = audit or cancellation` | S8 |
| E2b | same anchor → `cancellation = cancellation` | S6 |
| D1 | agent_stop.py `raise cancellation from failure  # A4 (F3): not written, and the caller is still cancelled` → `raise cancellation` | S9 |
| D2 | agent_stop.py `return failure, cancellation  # log-and-degrade on a failure: the stop stays in force` → `return None, cancellation` | T29 (a), S9 |
| D3 | agent_stop.py `durable = failure is None  # A4 (F3): the failure is kept for the cancellation's cause` → `durable = True` | T29 (a), T12 |
| D4 | agent_stop.py `return RuntimeError("AD-1343: the stop store is closed"), None` → `return None, None` | T12 |
| HB2′ | agent_stop.py `cancellation = cancellation or later  # A4 (F2): the first cancellation is the one raised, as below` → `cancellation = later or cancellation` | HAND (no test pauses the second write) |
| Y3a | crew_synth.py `if admitted_synthesis is not True:  # A4 (F1): claimed by the owned resume after its own check; not refused again` → `if False:` | Y1, X9 |
| Y3b | same anchor → `if True:` | X10b′, Y2 |
| F9a | crew_finalizer.py `admitted_synthesis=admission is not None,  # A4 (F1): only a synthesis this resume has just claimed` → `admitted_synthesis=False,` | X10b′ |
| F9b | same anchor → `admitted_synthesis=True,` | I18 |
| F10 | crew_finalizer.py `return admission  # A4 (F1): the durable claim is made; the synthesis it records is admitted` → `return None` | X10b′ |

Retired and changed rows:
- **B6:** its line is removed; D3 replaces it.
- **HB2:** its line is removed; HB2′ replaces it.
- **F2** (A3; `raise ValueError("synthesis_producer_unavailable") from exc` → `raise`): becomes HAND. It is now reached only by a resume of a session with no owned steps, and no rig builds one (D43).
- **B3, B4, B5, Y1m, Y2m, F1, F3–F6:** the stripped anchors are unchanged and stand.

**Campaign of record:** rerun every row on `agent_stop.py`, `crew_synth.py` and `crew_finalizer.py`, plus the new rows. All other rows stand from round 3.

### Diff Reviewer: properties to verify (delta)

- **P14 (amended).** Each stop write AND each EventLog append runs to its end whatever happens to its caller. A cancellation that arrives during either is held. The first held cancellation is the one raised, once the order or lift, its counts and its event are settled. A failed write with a cancelled caller raises `CancelledError` caused by the failure, on issue (new) and on lift. A real EventLog failure is still logged once and not raised.
- **P16 (amended).** Every crew model call under a crew agent's name follows a stop question with no await between them, with one named exception. The owned resume's synthesis is admitted at the finalizer's check before the claim, and the claim records it. Once claimed it is not refused again. That is the only `admitted_synthesis=` site (I18). Every other synthesis is refused at the entry.
- **P18 (new).** A refusal never leaves a synthesis claim behind. A claim exists only for a synthesis that started (X10, X10b′). No persisted shape, journal operation or failure code changes.
- **P3 (unchanged).** With no order and no cancellation, every changed path returns what it did before, with the same SQL and the same events (goldens listed above).
- **P9.** srp-size 92. `AgentStopService`, `CrewSynthesizer` and `CrewSessionFinalizer` gain no method (the helpers are module-level). Both baselines are byte-identical. `ToolRegistry` and `DelegateTaskTool` are untouched. The AD-1195 census stays 37/18.

**Round 4: delta review** (`git diff --cached <round-3 tree>` after A4), with the reviewer reading `agent_stop.py`, `crew_synth.py` and `crew_finalizer.py` in full.

### Decisions

| # | Decision | Rejected | Envelope |
|---|---|---|---|
| D39 | F1 option (b): the owned resume's synthesis is admitted at the finalizer's check, and its claim records it. Once claimed it runs (S1_SCOPE `does_not_end`). The synthesizer's entry check stays for every synthesis not claimed. | (a) a release transition: a persisted journal operation, an untested downgrade and a reversal of the AD-1192 fence (Captain). (c) the leftover claim as a defined outcome: the regression stays and the fence's meaning becomes false. (d) an in-memory set of unexecuted claims: lost on restart, and the orchestrator gate at `crew_orchestrator.py:746-757` would need it too. | Architect |
| D40 | F2: the EventLog append runs in its own task through the same shield (`_held_through`, shared with `_write_settled`). Log-and-degrade is kept. The first cancellation is raised, and the final-counts line follows the same order. | Bounding the append: EventLog already bounds its own wait at 5 s (`event_log.py:71`). | Architect |
| D41 | F3: `_write_issued` returns its failure; a cancelled issue raises from it. A closed store is reported as a `RuntimeError` failure. | Setting `__cause__` by hand | Architect |
| D42 | Round 4 is a delta review: no persisted, event, route or narrowed contract changes. | A whole-candidate review | Architect |
| D43 | The resume of a session with no owned steps keeps the A3 mapping; its race row is HAND. | Building a rig with no owned steps in S1 | Architect |

### Verified Against Codebase (2026-10-19, staged candidate; index = working tree per `git status`)

- `agent_stop.py`: 16-18 (S1/S2 docstring), 32 (import), 75-98 (`S1_SCOPE`), 166-192 (`_write_settled`), 293-316 (service; 13 methods), 371-395 (issue), 397-436 (lift), 438-472 (writers), 474-518 (appends).
- `crew_synth.py`: 49 (imports), 211 (the synthesizer's own legacy `claim_owned_synthesis`, ship prompt), 887-1009 (`synthesize_for_session`; check 986-988, model 990).
- `crew_finalizer.py`: 26 (import), 702/723 (`agent_stops`), 1790-1802 (`_owned_steps_snapshot`), 1966-2039 (`_resume_synthesis`; check 2011, claim 2020, except 2031-2032), 2041-2063 (`_claim_owned_synthesis`), 2853-2904 (fresh path, no claim; except 2901).
- `workforce.py`: 4027-4077 (`claim_owned_synthesis`: "synthesis-start"; a re-claim with the same digest is `already_started`, 4050-4054), 4079.
- `crew_orchestrator.py`: 713-909 (`_run_recovery_attempt`; claim gate 746-757; resume 889/896), 1107-1166 (loop), 1264-1267 (transient), 1393-1443 (contain: a `ValueError` becomes `blocked_needs_captain`/`recovery_integrity_conflict`).
- `crew_session.py:88-96` (`blocked_needs_captain` → `verifying` is allowed).
- `agentic_dispatch.py:2613-2623` (`admitted_turn` precedent).
- `event_log.py`: 71 (5 s budget), 492 (`_write_lock`), 584-649 (no await before the lock).
- `check_architecture_principles.py`: 187-188 (srp limits), 661-677 (`create_task` is reported, and flagged only when its result is not kept).
- `architecture-baseline.yaml:443-492`.
- `pyproject.toml:9` (Python ≥ 3.12: `cancel(msg)` and the original exception are kept).
- Tests: `test_ad1343_agent_stop_settle.py:1-253`, `test_ad1343_stop_crossing_resume.py:1-184`, `test_ad1343_stop_seam_inventory.py:40-408`, `test_ad1343_agent_stop_verify.py:1-20, 355-486`, `test_ad1343_agent_stop.py:52-193, 501-593`, `test_ad1343_agent_stop_lift.py:223-379`, `test_ad1126_verified_finalization.py:6100-6131`, `test_ad1195_eventlog_pair_freeze.py:1-36, 90-92, 396-399`.

### Absence Verified (2026-10-19)

| Claim | Run | Found | Holds |
|---|---|---|---|
| There is no release or re-arm of the synthesis claim | grep `def \w*owned_synthesis\w*\|release_owned\|rearm` in src/probos | `crew_finalizer:2041`, `crew_synth:211`, `workforce:4027, 4079`; the rest unrelated (sensorium, task_sessions) | yes |
| Only the finalizer calls `synthesize_for_session` in src | grep `synthesize_for_session` *.py | src: `crew_finalizer:2022, 2877` (def `crew_synth:887`) | yes |
| No test pins the changed private names | grep tests for `_write_issued\|_record_issued\|_record_lifted\|_write_settled\|_claim_owned_synthesis\|admitted_synthesis\|_write_final_counts` | `test_ad1343_stop_seam_inventory.py:108` (callee name in `_SOURCE_ORDER`) | yes |
| The new names are free in src | grep `admitted_synthesis\|_held_through\|_append_settled` | none | yes |
| `S1_SCOPE` is pinned only as a constant | grep tests `S1_SCOPE` | `test_ad1343_agent_stop.py:672-801` | yes |
| `AgentStopService` is built only in runtime and tests | grep `AgentStopService\(` | `runtime.py:2770`; tests | yes |

### Prior Art and Blind Spots

This repairs ProbOS plumbing and has no outside counterpart, so no external search was made and no row of `reference-projects.md` was reviewed. Internal prior art adopted:
- `admitted_turn` (`agentic_dispatch.py:2613-2623`): admission at the check, and the admitted work runs.
- The A3 shield (AD-1198 A-1), and `crew_orchestrator.py:1133-1143`.

Blind spots, recorded:
- The admission window is the snapshot read plus the claim transaction (milliseconds). One draft may finish under a facilitator stopped inside it; the stop counts no refusal for it.
- Through the orchestrator, a stopped facilitator at resume (A3's check at 2011) still ends `blocked_needs_captain` with the code `recovery_integrity_conflict` (`crew_orchestrator.py:1418-1423`), a misleading label. This predates A4 for a facilitator that is not live. Considered and deferred to the #1595 follow-up.
- A crash between the claim and the model call keeps the existing AD-1192 interrupted semantics (unchanged).
- The closing-loop case (a write's or append's own task cancelled) is unchanged: that `CancelledError` propagates.
