"""AD-1343 S1 (#1595), amendment A3 (R3, R4): a cancelled issue or lift is settled against what the store holds (S1 to S4).

Cancelling an await on aiosqlite does not stop the call its worker thread was given (``aiosqlite/core.py``: a queued call runs
even after its future is cancelled). Before A3 a cancelled issue was marked unwritten although its COMMIT then landed, and a
cancelled lift left the agent stopped in memory although its row was lifted. These tests pause the REAL worker inside COMMIT: a
test-held SQLite connection keeps a read transaction open, so the service's COMMIT waits for its lock on the worker thread while
the test cancels the caller; then the test ends its read and the COMMIT lands.

* S1: an issue cancelled while its COMMIT is blocked is durable once the COMMIT lands; the re-issue, a lift and a restart agree.
* S2: a lift cancelled while its COMMIT is blocked is applied once the COMMIT lands; the EventLog has the lift; a restart agrees.
* S3: two cancellations during one blocked COMMIT end in one CancelledError and one settled, durable order.
* S4 (golden): with no cancellation the blocked COMMIT simply lands; the issue and the lift each run one statement, no ROLLBACK.
* S5, S6 (A4, F2): an issue or lift cancelled while its EventLog append waits behind another writer keeps its event.
* S7, S8 (A4, F2): a second cancellation during that append, after one was held through the COMMIT, loses no event, and the
  first cancellation is the one raised.
* S9 (A4, F3): a cancelled issue whose write failed raises ``CancelledError`` caused by the failure.
* S10 (golden): with no cancellation the append waits behind the other writer, lands, and nothing is logged as lost.

The other writer is real: a second ``EventLog.log`` takes the writer lock (``substrate/event_log.py:649``) and waits for
SQLite's write lock, which a test-held ``BEGIN IMMEDIATE`` keeps; every later append queues on the writer lock.

Every store lives in ``tmp_path``; the live data directory is never read. Waits are on events and tasks, bounded by ``_BOUND``;
S3 yields one loop turn so that its first cancellation is delivered before its second. The service's connection keeps SQLite's
default busy timeout (5 s), far above the few loop turns the test holds its read.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from probos.agent_stop import STOP_ISSUED_EVENT, STOP_LIFTED_EVENT, STORE_FILENAME, StopNotFound
from probos.substrate.event_log import EventLog
from tests.test_ad1343_agent_stop import AGENT, LIFT_REASON, REASON, _Clock, _FlakyFactory, _service, _stop_rows

_BOUND = 10.0  # seconds: the longest any step here waits; a wedged step raises TimeoutError instead of hanging the run


class _CommitSeen:
    """Test-local connection wrapper: forwards every call; marks each COMMIT just before the real ``commit`` queues it."""

    def __init__(self, inner: Any, seen: asyncio.Event) -> None:
        self._inner = inner
        self._seen = seen

    async def commit(self) -> None:
        self._seen.set()
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _CommitSeenFactory:
    """The SQLite default behind a ``_FlakyFactory`` (which records statements), with each COMMIT marked."""

    def __init__(self) -> None:
        self.seen = asyncio.Event()
        self._flaky = _FlakyFactory()

    @property
    def statements(self) -> list[str]:
        return self._flaky.statements

    async def connect(self, db_path: str) -> _CommitSeen:
        return _CommitSeen(await self._flaky.connect(db_path), self.seen)


@contextlib.contextmanager
def _read_held(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """A test-held read transaction on ``agent_stops.db``: while it is open the service's COMMIT waits on the worker thread."""
    conn = sqlite3.connect(data_dir / STORE_FILENAME, isolation_level=None)
    try:
        conn.execute("BEGIN")
        conn.execute("SELECT count(*) FROM agent_stops").fetchone()
        yield conn
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("COMMIT")
        conn.close()


# S1
async def test_an_issue_cancelled_while_its_commit_lands_is_durable(tmp_path: Path) -> None:
    factory = _CommitSeenFactory()
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        factory.seen.clear()  # start() committed its schema
        with _read_held(tmp_path) as reader:
            issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
            await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
            assert not issue.done()  # premise: the INSERT ran and its COMMIT is on the worker, waiting for the test's read
            issue.cancel()
            reader.execute("COMMIT")  # the read ends: the COMMIT the worker holds can land
            await asyncio.wait({issue}, timeout=_BOUND)
        assert issue.cancelled()  # the caller's cancellation still propagated
        in_force = service.stop_for(AGENT)
        assert in_force is not None
        assert [row["stop_id"] for row in _stop_rows(tmp_path)] == [in_force.stop_id]  # premise: the COMMIT landed
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force
        assert again.durable is True  # durability is what the store holds, not what the cancellation suggested
        lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert service.stop_for(AGENT) is None
    assert _stop_rows(tmp_path)[0]["lifted_at"] == lifted.lifted_at  # the lift wrote its row: it did not skip it as unwritten
    async with _service(tmp_path) as restarted:
        assert restarted.stop_for(AGENT) is None


# S2
async def test_a_lift_cancelled_while_its_commit_lands_is_applied(tmp_path: Path) -> None:
    stops = tmp_path / "stops"
    factory = _CommitSeenFactory()
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True  # premise: written, so the lift writes its row
            factory.seen.clear()
            with _read_held(stops) as reader:
                lift = asyncio.create_task(service.lift_stop(AGENT, reason=LIFT_REASON))
                await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
                assert not lift.done()  # premise: the lift's UPDATE ran and its COMMIT waits on the worker
                assert service.stop_for(AGENT) == issued.record  # in force while the lift is written
                lift.cancel()
                reader.execute("COMMIT")
                await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()
            assert service.stop_for(AGENT) is None  # R4: the lift that landed is applied in memory
    finally:
        await event_log.stop()
    rows = _stop_rows(stops)
    assert len(rows) == 1 and rows[0]["lifted_at"] is not None and rows[0]["lift_reason"] == LIFT_REASON
    with contextlib.closing(sqlite3.connect(tmp_path / "events.db")) as conn:
        events = [json.loads(data) for (data,) in conn.execute("SELECT data FROM events WHERE event = 'agent_stop_lifted'")]
    assert [event["stop_id"] for event in events] == [issued.record.stop_id]  # the lift's event is kept
    async with _service(stops) as restarted:
        assert restarted.stop_for(AGENT) is None


# S3
async def test_two_cancellations_during_one_commit_settle_it_once(tmp_path: Path) -> None:
    factory = _CommitSeenFactory()
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        factory.seen.clear()
        with _read_held(tmp_path) as reader:
            issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
            await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
            issue.cancel()
            await asyncio.sleep(0)  # one loop turn, not a wait on time: the first cancellation is delivered
            assert not issue.done()  # premise: still waiting on the blocked COMMIT
            issue.cancel()
            reader.execute("COMMIT")
            await asyncio.wait({issue}, timeout=_BOUND)
        assert issue.cancelled()
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.durable is True
        assert len(_stop_rows(tmp_path)) == 1


# S4 (golden)
async def test_an_uncancelled_write_waits_for_its_commit_and_issues_no_rollback(tmp_path: Path) -> None:
    factory = _CommitSeenFactory()
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        factory.seen.clear()
        mark = len(factory.statements)
        with _read_held(tmp_path) as reader:
            issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
            await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
            assert not issue.done()
            reader.execute("COMMIT")
            issued = await asyncio.wait_for(issue, timeout=_BOUND)
        assert issued.durable is True and issued.already_stopped is False
        lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert lifted.refused == {}
        assert [sql.lstrip().split()[0] for sql in factory.statements[mark:]] == ["INSERT", "UPDATE"]  # no ROLLBACK, no extra
    async with _service(tmp_path) as restarted:
        assert restarted.stop_for(AGENT) is None


async def _lift_held_at_its_commit_with_a_refusal(
    service: Any, factory: _CommitSeenFactory, stops: Path, agent_id: str, *, cancel: bool,
) -> asyncio.Task[Any]:
    """Run ``lift_stop`` with its worker held in COMMIT; count one ``tool`` refusal meanwhile (so the counts differ from those the
    lift wrote), cancel the caller when ``cancel``, then let the COMMIT land. The final-counts write that follows is not held."""
    factory.seen.clear()
    with _read_held(stops) as reader:
        lift = asyncio.create_task(service.lift_stop(agent_id, reason=LIFT_REASON))
        await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
        assert not lift.done()  # premise: the lift's UPDATE ran and its COMMIT waits on the worker
        assert service.refusal(agent_id, "tool") is not None  # premise: counted while the lift is being written
        if cancel:
            lift.cancel()
        reader.execute("COMMIT")
        await asyncio.wait({lift}, timeout=_BOUND)
    assert lift.done()  # premise: the lift ended within the bound
    return lift


def _lifted_events(events_db: Path) -> list[dict[str, Any]]:
    with contextlib.closing(sqlite3.connect(events_db)) as conn:
        return [json.loads(data) for (data,) in conn.execute("SELECT data FROM events WHERE event = 'agent_stop_lifted'")]


# HB2
async def test_a_cancellation_held_through_the_lift_write_is_raised_after_the_final_counts_are_written(tmp_path: Path) -> None:
    stops = tmp_path / "stops"
    other = AGENT + "_golden"
    factory = _CommitSeenFactory()
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            golden_issued = await service.issue_stop(other, reason=REASON)
            assert issued.durable is True and golden_issued.durable is True  # premise: written, so each lift writes its row

            lift = await _lift_held_at_its_commit_with_a_refusal(service, factory, stops, AGENT, cancel=True)
            assert lift.cancelled()  # the cancellation held through the first write is raised after the bookkeeping
            assert [row["refused_json"] for row in _stop_rows(stops) if row["stop_id"] == issued.record.stop_id] == ['{"tool": 1}']
            assert [row["lifted_at"] is not None for row in _stop_rows(stops) if row["stop_id"] == issued.record.stop_id] == [True]
            assert service.stop_for(AGENT) is None  # memory does not hold the stop
            events = [event for event in _lifted_events(tmp_path / "events.db") if event["stop_id"] == issued.record.stop_id]
            assert [event["refused"] for event in events] == [{"tool": 1}]  # one event, with the final counts
            with pytest.raises(StopNotFound):
                await service.lift_stop(AGENT, reason=LIFT_REASON)

            # golden: the same sequence with no cancellation returns the lift and raises nothing
            golden = await _lift_held_at_its_commit_with_a_refusal(service, factory, stops, other, cancel=False)
            assert not golden.cancelled() and golden.exception() is None
            result = golden.result()
            assert result.refused == {"tool": 1}
            assert [row["refused_json"] for row in _stop_rows(stops) if row["stop_id"] == golden_issued.record.stop_id] == ['{"tool": 1}']
            assert service.stop_for(other) is None
    finally:
        await event_log.stop()


class _CommitThenHook(_CommitSeen):
    """Test-local: as ``_CommitSeen``, and once the real COMMIT has landed (still on the loop, before the caller of the write
    is woken, so before any later write is queued) it runs the factory's one-shot hook."""

    def __init__(self, inner: Any, seen: asyncio.Event, factory: "_CommitThenHookFactory") -> None:
        super().__init__(inner, seen)
        self._factory = factory

    async def commit(self) -> None:
        self._seen.set()
        await self._inner.commit()
        hook, self._factory.after_commit = self._factory.after_commit, None  # one-shot
        if hook is not None:
            hook()


class _CommitThenHookFactory(_CommitSeenFactory):
    """``_CommitSeenFactory`` whose connections run ``after_commit`` once, right after the next COMMIT has landed."""

    def __init__(self) -> None:
        super().__init__()
        self.after_commit: Any = None

    async def connect(self, db_path: str) -> _CommitThenHook:
        return _CommitThenHook(await self._flaky.connect(db_path), self.seen, self)


# HB2'
async def test_a_second_cancellation_during_the_final_counts_write_raises_the_first(tmp_path: Path) -> None:
    stops = tmp_path / "stops"
    factory = _CommitThenHookFactory()
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True  # premise: written, so the lift writes its row and then its final counts
            armed: list[sqlite3.Connection] = []
            with contextlib.ExitStack() as readers:
                factory.seen.clear()

                def arm_second_read() -> None:
                    factory.seen.clear()  # the next COMMIT seen is the final-counts write's
                    armed.append(readers.enter_context(_read_held(stops)))

                first = readers.enter_context(_read_held(stops))
                factory.after_commit = arm_second_read
                lift = asyncio.create_task(service.lift_stop(AGENT, reason=LIFT_REASON))
                await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
                assert not lift.done()  # premise: the lift's UPDATE ran and its COMMIT waits on the worker
                assert service.refusal(AGENT, "tool") is not None  # premise: counted, so the final counts differ from those written
                lift.cancel("first")  # held through the lift's write
                await asyncio.sleep(0)  # one loop turn, not a wait on time: the first cancellation is delivered
                assert not lift.done()
                factory.seen.clear()  # so that the next COMMIT seen is the final-counts write's
                first.execute("COMMIT")  # the lift's COMMIT lands; a new read is held before the final-counts write is queued
                await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
                assert factory.after_commit is None and len(armed) == 1  # premise: the first COMMIT landed; a second read is held
                assert not lift.done()  # premise: the worker is inside the final-counts COMMIT, waiting for the second read
                assert service.stop_for(AGENT) is None  # premise: the lift is applied, only its final counts are pending
                lift.cancel("second")  # held through the final-counts write
                await asyncio.sleep(0)
                assert not lift.done()  # premise: still waiting on the held final-counts COMMIT
                armed[0].execute("COMMIT")  # the final-counts COMMIT lands
                await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.done()  # premise: the lift ended within the bound
            with pytest.raises(asyncio.CancelledError) as raised:
                lift.result()
            assert raised.value.args == ("first",)  # the cancellation held through the lift's write is the one raised
            rows = [row for row in _stop_rows(stops) if row["stop_id"] == issued.record.stop_id]
            assert [row["lifted_at"] is not None for row in rows] == [True]
            assert [row["refused_json"] for row in rows] == ['{"tool": 1}']  # the final counts landed
            assert service.stop_for(AGENT) is None  # memory does not hold the stop
    finally:
        await event_log.stop()
    assert [(e["stop_id"], e["refused"]) for e in _lifted_events(tmp_path / "events.db")] == [
        (issued.record.stop_id, {"tool": 1}),
    ]  # one event, with the final counts


# B5
async def test_a_lift_whose_write_fails_under_a_held_cancellation_raises_the_cancellation_and_stays_stopped(tmp_path: Path) -> None:
    factory = _FlakyFactory("UPDATE")
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the INSERT is not failed, so the lift has a row to write
        lift = asyncio.create_task(service.lift_stop(AGENT, reason=LIFT_REASON))
        await asyncio.sleep(0)  # one loop turn: the lift is waiting on its write task, which has not yet run
        assert not lift.done() and "UPDATE" not in [sql.lstrip().split()[0] for sql in factory.statements]  # premise
        lift.cancel()  # held until the write has ended
        with pytest.raises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(lift, timeout=_BOUND)
        assert "UPDATE" in [sql.lstrip().split()[0] for sql in factory.statements]  # premise: the write ran, and failed
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
