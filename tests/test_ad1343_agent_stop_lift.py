"""AD-1343 S1 (#1595), amendment A2 (F3, F4): the lift's final counts and the write rollback (T27 to T29).

The tests of ``prompts/ad-1343-a2-amendment.md`` Section 11 for ``AgentStopService.lift_stop`` and the writes it makes:

* T27: a refusal counted while the lift is being written is in the answer, in the EventLog event and in the row;
* T28: when the row cannot be brought up to date the lift stands, the answer keeps the final counts, and the failure is
  logged at ERROR;
* T29: a commit that fails is rolled back, on issue and on lift, so no later successful write lands it; a cancelled caller
  waits for its write to settle, and memory follows what the store holds (A3: R3, R4).

Every service is a real ``AgentStopService`` over a real ``agent_stops.db`` in ``tmp_path`` (T27 adds a real ``EventLog``); the
live data directory is never read. The connection that pauses or fails a commit is test-local (``_GatedFactory``: the SQLite
default behind ``_FlakyFactory``, with a ``_CommitGate`` on every commit). A paused commit waits on an ``asyncio.Event`` the test
sets, bounded by ``_BOUND``; nothing sleeps and nothing is ordered by wall-clock time.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Coroutine
from pathlib import Path
from typing import Any

import pytest

from probos.agent_stop import SEAM_INTENT, SEAM_TOOL
from probos.substrate.event_log import EventLog
from tests.test_ad1343_agent_stop import (
    AGENT,
    LIFT_REASON,
    OTHER,
    PRIVATE_FRAGMENT,
    REASON,
    _Clock,
    _FlakyFactory,
    _service,
    _stop_log,
    _stop_rows,
)

_BOUND = 10.0  # seconds: the longest any step here waits; a wedged step raises TimeoutError instead of hanging the run
_INSERT_SQL = "INSERT"  # a statement prefix: the write of an order
_LIFT_SQL = "UPDATE agent_stops SET lifted_by"  # a statement prefix: the write of a lift
_COUNTS_SQL = "UPDATE agent_stops SET refused_json"  # a statement prefix: a lift's second write, the row's final counts


class _CommitGate:
    """What the test decides about the service's commits: one pauses, or one raises, after a statement it names."""

    def __init__(self) -> None:
        self.pause_after: str | None = None  # a statement prefix: the next commit after it waits for ``release``, once
        self.fail_after: str | None = None  # a statement prefix: the next commit after it raises, once, transaction still open
        self.reached = asyncio.Event()  # set when a commit has paused
        self.release = asyncio.Event()  # set by the test to let a paused commit go on
        self.last_sql = ""  # the statement the transaction ran last
        self.paused = 0
        self.failed = 0


class _GatedConnection:
    """Test-local connection wrapper: forwards every call, but a commit can pause or raise once after a named statement."""

    def __init__(self, inner: Any, gate: _CommitGate) -> None:
        self._inner = inner
        self._gate = gate

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        executing = self._inner.execute(sql, *args, **kwargs)  # a flaky inner raises here, before the statement runs
        self._gate.last_sql = sql
        return executing

    async def commit(self) -> None:
        gate = self._gate
        last = gate.last_sql.lstrip()
        if gate.pause_after is not None and last.startswith(gate.pause_after):
            gate.pause_after = None
            gate.paused += 1
            gate.reached.set()
            await asyncio.wait_for(gate.release.wait(), timeout=_BOUND)
        if gate.fail_after is not None and last.startswith(gate.fail_after):
            gate.fail_after = None
            gate.failed += 1
            raise sqlite3.OperationalError("disk I/O error during COMMIT (simulated by the test)")
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _GatedFactory:
    """Test-local connection factory: the SQLite default behind a ``_FlakyFactory``, with a ``_CommitGate`` on every commit."""

    def __init__(self, *fail_on: str) -> None:
        self.gate = _CommitGate()
        self._flaky = _FlakyFactory(*fail_on)

    @property
    def statements(self) -> list[str]:
        """Every statement the connection was asked to execute, in order (``executescript`` and commits are not among them)."""
        return self._flaky.statements

    async def connect(self, db_path: str) -> _GatedConnection:
        return _GatedConnection(await self._flaky.connect(db_path), self.gate)


@contextlib.asynccontextmanager
async def _paused(gate: _CommitGate, operation: Coroutine[Any, Any, Any]) -> AsyncIterator[asyncio.Task[Any]]:
    """Run ``operation`` as a task until one of its commits is paused by ``gate``, and yield the task.

    The wait is bounded. On exit the gate is released and the task, if it still runs, is cancelled and awaited, so a
    failing test leaves no paused commit and no unretrieved exception behind it.
    """
    task = asyncio.create_task(operation)
    reached = asyncio.create_task(gate.reached.wait())
    try:
        await asyncio.wait({task, reached}, timeout=_BOUND, return_when=asyncio.FIRST_COMPLETED)
        assert gate.reached.is_set() and not task.done(), f"the operation did not stop at a paused commit: {task!r}"
        yield task
    finally:
        gate.release.set()
        reached.cancel()
        task.cancel()
        await asyncio.gather(task, reached, return_exceptions=True)


def _rows_by_agent(data_dir: Path) -> dict[str, dict[str, Any]]:
    """The rows of ``agent_stops.db`` keyed by agent, read with the standard library (one order per agent in these tests)."""
    return {row["agent_id"]: row for row in _stop_rows(data_dir)}


# T27
async def test_a_refusal_made_while_the_lift_is_written_is_kept_in_the_answer_the_event_and_the_row(tmp_path: Path) -> None:
    stops = tmp_path / "stops"
    factory = _GatedFactory()
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True  # premise: the order is written, so the lift writes its row
            assert service.refused_counts(issued.record.stop_id) == {}  # premise: nothing was refused before the lift began

            factory.gate.pause_after = _LIFT_SQL
            async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
                # The lift's UPDATE has run and its commit has not: the order is being lifted and is still in force.
                assert service.refusal(AGENT, SEAM_TOOL) == issued.record
                factory.gate.release.set()
                lifted = await asyncio.wait_for(lift, timeout=_BOUND)
            assert lifted.refused == {"tool": 1}  # the answer carries the refusal made while the row was being written
            assert service.stop_for(AGENT) is None  # and the lift was applied
            updates = [sql for sql in factory.statements if sql.lstrip().startswith("UPDATE")]
            assert len(updates) == 2 and updates[0].startswith(_LIFT_SQL) and updates[1].startswith(_COUNTS_SQL)  # row brought up to date

            # Golden: nothing refused while the lift is written makes one UPDATE, and the row is the lift-time counts.
            other = await service.issue_stop(OTHER, reason=REASON)
            assert other.durable is True  # premise: written
            for seam in (SEAM_INTENT, SEAM_INTENT, SEAM_TOOL):
                assert service.refusal(OTHER, seam) == other.record  # premise: these refusals come before the lift begins
            mark = len(factory.statements)
            calm = await service.lift_stop(OTHER, reason=LIFT_REASON)
            assert calm.refused == {"intent": 2, "tool": 1}
            calm_updates = [sql for sql in factory.statements[mark:] if sql.lstrip().startswith("UPDATE")]
            assert len(calm_updates) == 1 and calm_updates[0].startswith(_LIFT_SQL)  # no second write: nothing changed
    finally:
        await event_log.stop()

    rows = _rows_by_agent(stops)
    assert rows[AGENT]["lifted_at"] == lifted.lifted_at and rows[AGENT]["lift_reason"] == LIFT_REASON  # premise: the lifted row
    assert rows[AGENT]["refused_json"] == '{"tool": 1}'  # the row has the final counts, not the counts at the moment of the write
    assert rows[OTHER]["refused_json"] == '{"intent": 2, "tool": 1}'  # golden: the row equals the lift-time counts
    with contextlib.closing(sqlite3.connect(tmp_path / "events.db")) as conn:
        events = {
            agent_id: json.loads(data)
            for agent_id, data in conn.execute("SELECT agent_id, data FROM events WHERE event = 'agent_stop_lifted' ORDER BY id")
        }
    assert events[AGENT]["refused"] == {"tool": 1}  # the EventLog's lifted row has the final counts
    assert events[OTHER]["refused"] == {"intent": 2, "tool": 1}  # golden


# T28
async def test_a_failed_final_count_write_leaves_the_lift_standing_and_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    factory = _GatedFactory(_COUNTS_SQL)  # the final-count UPDATE raises; every other statement works
    # A3 (review item b): with an EventLog, so a lift that skipped its event when the second write fails cannot pass.
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    with caplog.at_level(logging.WARNING, logger="probos.agent_stop"):
        async with _service(tmp_path, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True  # premise: the order is written, so the lift writes its row

            factory.gate.pause_after = _LIFT_SQL
            async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
                assert service.refusal(AGENT, SEAM_TOOL) == issued.record  # refused while the lift is being written
                factory.gate.release.set()
                lifted = await asyncio.wait_for(lift, timeout=_BOUND)
            assert lifted.refused == {"tool": 1}  # the answer has the final counts although the row cannot
            assert service.stop_for(AGENT) is None  # the lift stands
            attempts = [sql for sql in factory.statements if sql.lstrip().startswith(_COUNTS_SQL)]
            assert len(attempts) == 1  # premise: the row was brought up to date once, and that statement raised
    await event_log.stop()
    with contextlib.closing(sqlite3.connect(tmp_path / "events.db")) as conn:
        lifted_events = [json.loads(data) for (data,) in conn.execute("SELECT data FROM events WHERE event = 'agent_stop_lifted'")]
    assert [(event["stop_id"], event["refused"]) for event in lifted_events] == [(issued.record.stop_id, {"tool": 1})]

    errors = [line for level, line in _stop_log(caplog) if level == logging.ERROR]
    assert len(errors) == 1 and issued.record.stop_id in errors[0]  # one ERROR, and it names the order
    assert PRIVATE_FRAGMENT not in caplog.text  # and no log line or traceback carries the Captain's reason
    rows = _stop_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["lifted_at"] == lifted.lifted_at and rows[0]["lifted_by"] == "captain"  # the lift is on file
    assert rows[0]["lift_reason"] == LIFT_REASON
    assert rows[0]["refused_json"] == "{}"  # and keeps the counts at the moment it was written
    async with _service(tmp_path) as restarted:
        assert restarted.stop_for(AGENT) is None  # a restart does not stop the agent again


# T29
async def test_a_failed_or_cancelled_commit_is_rolled_back_on_issue_and_lift(tmp_path: Path) -> None:
    await _issue_whose_commit_fails(tmp_path / "issue")
    await _lift_whose_commit_fails(tmp_path / "lift")
    await _lift_whose_statement_fails(tmp_path / "lift_statement")
    # A3 (R3, R4): (c) and (d) asserted that a cancelled caller's write is rolled back. That held only because this double
    # never forwarded the COMMIT once its caller was cancelled; the real aiosqlite worker does (aiosqlite/core.py:59-75), and
    # tests/test_ad1343_agent_stop_settle.py pauses the real worker. Each case is now split by what the COMMIT then does.
    await _lift_cancelled_in_its_commit_that_lands(tmp_path / "lift_cancelled")
    await _lift_cancelled_in_its_commit_that_fails(tmp_path / "lift_cancelled_fails")
    await _issue_cancelled_in_its_commit_that_lands(tmp_path / "issue_cancelled")
    await _issue_cancelled_in_its_commit_that_fails(tmp_path / "issue_cancelled_fails")


async def _issue_whose_commit_fails(data_dir: Path) -> None:
    """(a) Issue: the INSERT runs and its COMMIT raises. The order is in force and unwritten, and a later write cannot land it."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        factory.gate.fail_after = _INSERT_SQL
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert factory.gate.failed == 1  # premise: the INSERT ran, and its COMMIT raised with the transaction open
        assert issued.durable is False and issued.already_stopped is False  # in force, and honest that it is unwritten
        assert service.stop_for(AGENT) == issued.record
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True  # a later write succeeds
        assert list(_rows_by_agent(data_dir)) == [OTHER]  # and lands itself alone, not the order whose COMMIT failed
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) is None
        assert restarted.stop_for(OTHER) == other.record


async def _lift_whose_commit_fails(data_dir: Path) -> None:
    """(b) Lift: the UPDATE runs and its COMMIT raises. The original error propagates, the agent stays stopped, and a later
    write cannot land the lift."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the order is written
        assert service.refusal(AGENT, SEAM_TOOL) == issued.record  # premise: a count that must survive the failed lift
        factory.gate.fail_after = _LIFT_SQL
        with pytest.raises(sqlite3.OperationalError, match="simulated"):
            await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert factory.gate.failed == 1  # premise: the COMMIT after the lift's UPDATE raised, with the transaction open
        assert service.stop_for(AGENT) == issued.record  # written before applied: the agent is still stopped
        assert service.refused_counts(issued.record.stop_id) == {"tool": 1}  # and nothing was discarded
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True  # a later write succeeds
    assert _rows_by_agent(data_dir)[AGENT]["lifted_at"] is None  # and does not commit the lift
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == issued.record
        assert restarted.stop_for(OTHER) == other.record


async def _lift_whose_statement_fails(data_dir: Path) -> None:
    """(b) Lift, nothing to undo: the UPDATE itself raises, before a transaction opens, so the rollback has nothing to roll
    back and raises too. The error that surfaces is still the original one, not the rollback's."""
    factory = _GatedFactory(_LIFT_SQL)
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the order is written
        with pytest.raises(sqlite3.OperationalError, match="simulated"):
            await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert factory.statements[-1] == "ROLLBACK"  # premise: the rollback was tried after the failed UPDATE, and had nothing to undo
        assert service.stop_for(AGENT) == issued.record  # the agent is still stopped
    assert _rows_by_agent(data_dir)[AGENT]["lifted_at"] is None
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == issued.record


async def _lift_cancelled_in_its_commit_that_lands(data_dir: Path) -> None:
    """(c) Cancel, then the COMMIT lands: CancelledError propagates once it has, and the lift is applied, in memory and on file."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the order is written
        assert service.refusal(AGENT, SEAM_TOOL) == issued.record  # premise: a count the lift carries
        factory.gate.pause_after = _LIFT_SQL
        async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
            lift.cancel()
            factory.gate.release.set()  # the paused COMMIT goes on, as the real worker's does
            await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()  # held until the write settled, then propagated: not swallowed
        assert service.stop_for(AGENT) is None  # the lift landed, so it is applied
    row = _rows_by_agent(data_dir)[AGENT]
    assert row["lifted_at"] is not None and row["refused_json"] == '{"tool": 1}'
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) is None


async def _lift_cancelled_in_its_commit_that_fails(data_dir: Path) -> None:
    """(c2) Cancel, then the COMMIT fails: the caller is still cancelled, the agent stays stopped, the counts are intact, and a
    later write cannot land the lift."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True
        assert service.refusal(AGENT, SEAM_TOOL) == issued.record
        factory.gate.pause_after = _LIFT_SQL
        factory.gate.fail_after = _LIFT_SQL
        async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
            lift.cancel()
            factory.gate.release.set()
            await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()  # told it was cancelled, not handed the write's error
        assert factory.gate.failed == 1  # premise: the COMMIT raised after the pause
        assert service.stop_for(AGENT) == issued.record
        assert service.refused_counts(issued.record.stop_id) == {"tool": 1}
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True
    assert _rows_by_agent(data_dir)[AGENT]["lifted_at"] is None
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == issued.record
        assert restarted.stop_for(OTHER) == other.record


async def _issue_cancelled_in_its_commit_that_lands(data_dir: Path) -> None:
    """(d) Cancel issue, then the COMMIT lands: the order is in force and durable, as the store holds it."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        factory.gate.pause_after = _INSERT_SQL
        async with _paused(factory.gate, service.issue_stop(AGENT, reason=REASON)) as issue:
            in_force = service.stop_for(AGENT)
            assert in_force is not None  # premise: an order is applied before it is written
            issue.cancel()
            factory.gate.release.set()
            await asyncio.wait({issue}, timeout=_BOUND)
            assert issue.cancelled()
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force
        assert again.durable is True  # A3 (R3): what the store holds
    assert list(_rows_by_agent(data_dir)) == [AGENT]
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == in_force


async def _issue_cancelled_in_its_commit_that_fails(data_dir: Path) -> None:
    """(d2) Cancel issue, then the COMMIT fails: the order stays in force, marked unwritten, and a later write cannot land it."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        factory.gate.pause_after = _INSERT_SQL
        factory.gate.fail_after = _INSERT_SQL
        async with _paused(factory.gate, service.issue_stop(AGENT, reason=REASON)) as issue:
            in_force = service.stop_for(AGENT)
            assert in_force is not None
            issue.cancel()
            factory.gate.release.set()
            await asyncio.wait({issue}, timeout=_BOUND)
            assert issue.cancelled()
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force
        assert again.durable is False
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True
        assert list(_rows_by_agent(data_dir)) == [OTHER]
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) is None
        assert restarted.stop_for(OTHER) == other.record
