"""BF-873: EventLog hash-chain appends must serialize.

The AD-490 chain append is a read-modify-write (read the tail row_hash, chain
against it, insert). Unserialized, two writers chain against the same
predecessor: the rows still read back fine, but verify_chain() silently stops
holding. Every concurrency case here is paired with a sequential control, so a
green run cannot be confused with a probe that never exercised anything.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

import pytest

from probos.storage.sqlite_factory import default_factory
from probos.substrate import event_log as event_log_module
from probos.substrate.event_log import (
    _CHAIN_BUSY_TIMEOUT_MS,
    _CHAIN_WRITE_BUDGET_S,
    _MAX_CHAIN_WRITE_ATTEMPTS,
    EventLog,
    _is_database_locked,
)

_WRITES = 30

# Appends to the same events.db from a genuinely separate OS process. Writes
# until the parent says stop, so overlap is arranged by barriers rather than by
# hoping the two processes race. Stops the log before exiting: aiosqlite's
# worker thread is non-daemon and would hold the child open, which the parent
# would score as a hang.
_CHILD_WRITER = '''
import asyncio, os, sys, time
from pathlib import Path
from probos.substrate.event_log import EventLog

db = sys.argv[1]
ready, go, stop = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
CAP = 2000

async def main():
    log = EventLog(db_path=db)
    await log.start()
    try:
        ready.write_text("1")
        deadline = time.monotonic() + 60
        while not go.exists():
            if time.monotonic() > deadline:
                return 3
            time.sleep(0.01)
        written = 0
        while written < CAP and not stop.exists() and time.monotonic() < deadline:
            await log.log(category="child", event="c%d" % written)
            written += 1
            await asyncio.sleep(0.002)
        return 0 if written else 4
    finally:
        await log.stop()

rc = asyncio.run(main())
sys.stdout.flush()
os._exit(rc)
'''

# Appends exactly once, and reports whether its chain tail read executed. That
# read is the statement BEGIN IMMEDIATE exists to gate: a bare SELECT is
# permitted while another connection holds SQLite's RESERVED lock, so if the
# marker appears while the parent still holds it, the append is not gated.
_CHILD_LOCK_PROBE = '''
import asyncio, os, sys, time
from pathlib import Path
from probos.substrate.event_log import EventLog

db = sys.argv[1]
ready, go, stop = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
attempted, read_ok, tail_read = Path(sys.argv[5]), Path(sys.argv[6]), Path(sys.argv[7])

async def main():
    log = EventLog(db_path=db)
    await log.start()
    try:
        real_execute = log._db.execute

        def traced(sql, *args, **kwargs):
            if "SELECT row_hash FROM events" in str(sql):
                tail_read.write_text("1")
            return real_execute(sql, *args, **kwargs)

        log._db.execute = traced
        ready.write_text("1")

        deadline = time.monotonic() + 60
        while not go.exists():
            if stop.exists():
                return 5
            if time.monotonic() > deadline:
                return 3
            time.sleep(0.01)

        attempted.write_text("1")
        # Proves to the parent that reads ARE permitted under its RESERVED lock,
        # so a missing tail-read marker means BEGIN IMMEDIATE gated that read
        # rather than SQLite blocking every reader.
        async with log._db.execute("SELECT COUNT(*) FROM events") as cursor:
            [row async for row in cursor]
        read_ok.write_text("1")

        await log.log(category="child", event="probe")
        return 0
    finally:
        await log.stop()

rc = asyncio.run(main())
sys.stdout.flush()
os._exit(rc)
'''


async def _await_marker(marker, why: str, timeout: float = 30.0) -> None:
    """Bounded wait for a child-written marker; fails the test if it never lands."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.exists():
            return
        await asyncio.sleep(0.02)
    pytest.fail(f"premise: {why}")


async def _shutdown_child(proc, stop_marker) -> tuple[bytes, bool]:
    """Stop, drain and reap the child. Returns (stderr, timed_out).

    Called from a finally on EVERY exit path, so it must never raise: an
    exception here would mask the assertion that got us there, and a leaked
    child keeps events.db open and turns the next failure into a hang.
    """
    try:
        stop_marker.write_text("1")
    except OSError:
        pass
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        return err, False
    except (asyncio.TimeoutError, TimeoutError):
        proc.kill()
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (asyncio.TimeoutError, TimeoutError):
            err = b""
        await proc.wait()
        return err, True


@pytest.fixture
async def event_logs(tmp_path):
    """Factory for started EventLogs; stops them all in teardown.

    Mandatory: aiosqlite's worker thread is non-daemon, so an EventLog that is
    never stopped blocks interpreter exit and the run hangs instead of failing.
    """
    created: list[EventLog] = []

    async def _make(filename: str = "events.db") -> EventLog:
        log = EventLog(db_path=tmp_path / filename)
        await log.start()
        created.append(log)
        return log

    try:
        yield _make
    finally:
        for log in created:
            await log.stop()


class TestChainSerialization:
    async def test_sequential_writes_keep_chain_verifiable(self, event_logs):
        """CONTROL. If this ever fails, the concurrency cases below prove nothing."""
        log = await event_logs()

        for i in range(_WRITES):
            await log.log(category="control", event=f"e{i}")

        assert await log.verify_chain() == (True, None)
        assert await log.count() == _WRITES

    async def test_concurrent_writes_keep_chain_verifiable(self, event_logs):
        """Same connection, 30 writes racing in one event loop."""
        log = await event_logs()

        await asyncio.gather(
            *(log.log(category="race", event=f"e{i}") for i in range(_WRITES))
        )

        assert await log.verify_chain() == (True, None)
        assert await log.count() == _WRITES

    async def test_concurrent_writes_across_connections_keep_chain_verifiable(
        self, event_logs
    ):
        """Two connections on one events.db — the vessel plus CLI tooling shape.

        Each EventLog owns a separate _write_lock, so the in-process lock cannot
        help here: only the BEGIN IMMEDIATE transaction can. Measured before the
        fix, this corrupted the chain with zero lock errors raised.

        DOCUMENTED GAP: two connections in ONE interpreter, not two OS
        processes. The real multi-process case is covered separately by
        TestCrossProcessChainSerialization below; do not read this one as a
        cross-process regression.
        """
        vessel = await event_logs("shared.db")
        tooling = await event_logs("shared.db")

        tasks = []
        for i in range(_WRITES // 2):
            tasks.append(vessel.log(category="vessel", event=f"v{i}"))
            tasks.append(tooling.log(category="tooling", event=f"t{i}"))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert [r for r in results if isinstance(r, BaseException)] == []
        assert await vessel.verify_chain() == (True, None)
        assert await vessel.count() == _WRITES

    async def test_concurrent_writes_assign_distinct_prev_hashes(self, event_logs):
        """The specific corruption: two rows chained onto the same predecessor."""
        log = await event_logs()

        await asyncio.gather(
            *(log.log(category="race", event=f"e{i}") for i in range(_WRITES))
        )

        rows = []
        async with log._db.execute("SELECT prev_hash FROM events ORDER BY id") as cursor:
            async for row in cursor:
                rows.append(row[0])
        assert len(rows) == _WRITES
        assert len(set(rows)) == _WRITES

    async def test_prune_does_not_collide_with_concurrent_log(self, event_logs):
        """prune() holds an implicit transaction across awaits.

        Interleaved with log()'s BEGIN IMMEDIATE on the same connection, SQLite
        raises "cannot start a transaction within a transaction" — measured.
        """
        log = await event_logs()
        for i in range(6):
            await log.log(category="c", event=f"e{i}")

        before = {}
        async with log._db.execute(
            "SELECT id, prev_hash, row_hash FROM events ORDER BY id"
        ) as cursor:
            async for row in cursor:
                before[row[0]] = (row[1], row[2])
        assert len(before) == 6, "premise: the pre-prune snapshot must cover every row"

        results = await asyncio.gather(
            log.prune(retention_days=0, max_rows=3),
            log.log(category="c", event="concurrent"),
            return_exceptions=True,
        )

        assert [r for r in results if isinstance(r, BaseException)] == []
        assert results[0] > 0, "premise: prune must actually delete, or the assertion below proves nothing"

        after = {}
        async with log._db.execute(
            "SELECT id, prev_hash, row_hash FROM events ORDER BY id"
        ) as cursor:
            async for row in cursor:
                after[row[0]] = (row[1], row[2])

        # Used to require verify_chain() to FAIL, which pinned the known pruning
        # defect as required behaviour: a future truncation anchor that let the
        # retained suffix verify would have broken this regression rather than
        # satisfying it. What prune() actually promises (docstring, prune()) is
        # that it deletes rows and never rewrites the ones it keeps, so assert
        # exactly that.
        retained = sorted(set(after) & set(before))
        assert retained, "premise: prune must leave some original rows, or the check is vacuous"
        assert {i: after[i] for i in retained} == {i: before[i] for i in retained}


class TestTransactionIsNeverLeftOpen:
    """Every write path must close its transaction, including the paths that
    change nothing. A leaked transaction is worse than the bug BF-873 fixes:
    the connection stops accepting writes for the life of the process, and
    submit_intent() awaits logging before it broadcasts.
    """

    async def test_noop_prune_leaves_no_open_transaction(self, event_logs):
        """DELETE opens a transaction even when zero rows match.

        The concurrency case above forces deletions, so it cannot reach this;
        the runtime prunes hourly and most prunes delete nothing.
        """
        log = await event_logs()
        await log.log(category="c", event="before")

        deleted = await log.prune(retention_days=3650, max_rows=1_000_000)
        assert deleted == 0, "premise: this must be the zero-deletion path"

        # Crosses the seam: unreachable if the no-op prune left its transaction
        # open ("cannot start a transaction within a transaction").
        assert await log.log(category="c", event="after") is not None
        assert await log.verify_chain() == (True, None)
        assert await log.count() == 2

    async def test_cancelled_blocked_begin_leaves_no_open_transaction(self, event_logs):
        """Cancelling a log() that is blocked on BEGIN IMMEDIATE.

        The awaiting future dies, but aiosqlite's worker still completes the
        BEGIN once the other connection releases. Unless the rollback covers
        the BEGIN itself, that leaks a RESERVED transaction which blocks every
        writer on the file.
        """
        vessel = await event_logs("shared.db")
        blocker = await event_logs("shared.db")

        await blocker._db.execute("BEGIN IMMEDIATE")

        task = asyncio.create_task(vessel.log(category="c", event="cancelled"))
        await asyncio.sleep(0.2)
        assert not task.done(), "premise: the append must still be blocked on BEGIN"

        task.cancel()
        await asyncio.sleep(0.05)  # deliver the cancellation while BEGIN is still blocked
        await blocker._db.execute("ROLLBACK")  # now the worker's BEGIN succeeds

        with pytest.raises(asyncio.CancelledError):
            await task

        # Crosses the seam: only reachable if the cancelled append rolled back
        # the transaction its worker thread went on to open.
        assert await vessel.log(category="c", event="after") is not None
        assert await vessel.verify_chain() == (True, None)

    async def test_wipe_rolls_back_before_suppressing_commit_failure(
        self, event_logs, monkeypatch
    ):
        """wipe() suppresses failures by contract — but must not suppress the
        open transaction its DELETE started."""
        log = await event_logs()
        await log.log(category="c", event="e0")

        commits = {"n": 0}

        async def _failing_commit():
            commits["n"] += 1
            raise RuntimeError("commit exploded")

        monkeypatch.setattr(log._db, "commit", _failing_commit)
        await log.wipe()
        assert commits["n"] == 1, "premise: the failure path must actually have run"
        monkeypatch.undo()

        # Crosses the seam: the row survives (rolled back) and the connection
        # still accepts writes.
        assert await log.log(category="c", event="after") is not None
        assert await log.count() == 2


class TestCrossProcessChainSerialization:
    """The case BEGIN IMMEDIATE was actually chosen for: two OS processes.

    The vessel and CLI tooling both open events.db, so an in-process asyncio
    lock cannot serialize them. Everything else in this file runs two
    connections inside one interpreter, which does not exercise that.
    """

    async def test_second_process_appending_keeps_chain_verifiable(
        self, event_logs, tmp_path
    ):
        """Overlap is enforced by barriers, not by hoping the processes race.

        Measured while building this: without the barriers the parent finished
        all of its writes before the child's first one in 4 of 6 runs, so the
        test passed green while never exercising concurrency at all.
        """
        child_py = tmp_path / "child_writer.py"
        child_py.write_text(_CHILD_WRITER)
        ready, go, stop = tmp_path / "ready", tmp_path / "go", tmp_path / "stop"
        n = _WRITES // 2

        vessel = await event_logs("cross_process.db")

        async def _child_rows(after_id: int = 0) -> int:
            async with vessel._db.execute(
                "SELECT COUNT(*) FROM events WHERE category = 'child' AND id > ?",
                (after_id,),
            ) as cursor:
                return [row async for row in cursor][0][0]

        async def _await_child_row(after_id: int, why: str) -> None:
            for _ in range(600):
                if await _child_rows(after_id):
                    return
                await asyncio.sleep(0.05)
            pytest.fail(f"premise: {why}")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(child_py), str(tmp_path / "cross_process.db"),
            str(ready), str(go), str(stop),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        # Every exit path below reaps the child: an assertion failure used to
        # leave it running, holding events.db open, so a failure could become a
        # hang. A hang is INVALID, never a pass.
        try:
            await _await_marker(ready, "child process never opened its EventLog")
            go.write_text("1")

            # Barrier 1: the other process is writing before we start.
            await _await_child_row(0, "child never wrote a row")
            last_parent_id = 0
            for i in range(n):
                last_parent_id = await vessel.log(category="parent", event=f"p{i}")
            # Barrier 2: it is still writing after we finish, so its rows must
            # straddle ours rather than sit entirely on one side.
            await _await_child_row(last_parent_id, "child stopped writing before our rows landed")
        finally:
            err, timed_out = await _shutdown_child(proc, stop)

        if timed_out:
            pytest.fail("INVALID: child writer never exited — a hang is not a pass")
        assert proc.returncode == 0, f"child rc={proc.returncode} stderr={err.decode(errors='replace')[-800:]}"

        categories = []
        async with vessel._db.execute("SELECT category FROM events ORDER BY id") as cursor:
            async for row in cursor:
                categories.append(row[0])
        assert categories.count("parent") == n
        # All-child-then-all-parent is one transition and proves nothing about
        # concurrent appends; the two writers have to have actually interleaved.
        # Interleaving is still only ORDERING — the lock premise that proves the
        # append is gated lives in the test below.
        transitions = sum(1 for a, b in zip(categories, categories[1:]) if a != b)
        assert transitions >= 2, f"premise: writers never interleaved (transitions={transitions})"

        assert await vessel.verify_chain() == (True, None)
        assert await vessel.count() == len(categories)

    async def test_second_process_cannot_read_the_chain_tail_while_we_hold_reserved(
        self, event_logs, tmp_path
    ):
        """The discriminator the ordering assertions above cannot supply.

        Child-then-parent-then-child ordering does not prove the read-modify-write
        sections overlapped: measured, a forced legal child/parent/child schedule
        satisfied every one of those assertions, verify_chain included, against an
        implementation with no BEGIN IMMEDIATE at all.

        So hold SQLite's RESERVED lock and ask a genuinely separate process
        whether its `SELECT row_hash` ran while we held it. Without BEGIN
        IMMEDIATE that read is permitted and lands immediately; with it, the
        append blocks before reaching the read. The child also proves a plain
        read succeeds under the same lock, or a missing marker would prove
        nothing.
        """
        child_py = tmp_path / "lock_probe.py"
        child_py.write_text(_CHILD_LOCK_PROBE)
        ready, go, stop = tmp_path / "lp_ready", tmp_path / "lp_go", tmp_path / "lp_stop"
        attempted = tmp_path / "lp_attempted"
        read_ok = tmp_path / "lp_read_ok"
        tail_read = tmp_path / "lp_tail_read"

        vessel = await event_logs("lock_probe.db")
        await vessel.log(category="parent", event="seed")  # give the chain a tail to read

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(child_py), str(tmp_path / "lock_probe.db"),
            str(ready), str(go), str(stop),
            str(attempted), str(read_ok), str(tail_read),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        tail_read_while_held = None
        try:
            await _await_marker(ready, "child process never opened its EventLog")

            await vessel._db.execute("BEGIN IMMEDIATE")  # take RESERVED
            try:
                go.write_text("1")
                await _await_marker(attempted, "child never reached its append")
                await _await_marker(
                    read_ok,
                    "child could not read at all while we held RESERVED, so a "
                    "missing tail-read marker would prove nothing",
                )
                # A permitted tail read lands microseconds after read_ok.
                await asyncio.sleep(0.5)
                tail_read_while_held = tail_read.exists()
            finally:
                await vessel._db.execute("ROLLBACK")
        finally:
            err, timed_out = await _shutdown_child(proc, stop)

        if timed_out:
            pytest.fail("INVALID: lock-probe child never exited — a hang is not a pass")
        assert proc.returncode == 0, f"child rc={proc.returncode} stderr={err.decode(errors='replace')[-800:]}"

        assert tail_read_while_held is False, (
            "the other process read the chain tail while we held SQLite's RESERVED "
            "lock — the append is not gated, so two writers can still chain onto "
            "the same predecessor"
        )
        # Premise for the assertion above: the gated read must have happened
        # once we released, or the child simply never got that far.
        assert tail_read.exists(), "premise: the child never read the chain tail at all"
        assert await vessel.verify_chain() == (True, None)
        assert await vessel.count() == 2


class TestWriteBudgetIsBounded:
    """M5: contention must not let the writer queue grow without bound.

    Measured before this bound: one contended caller cost 16.8s (three stacked
    5s busy_timeouts), and three queued callers cost 17.7s because each started
    a fresh budget only after winning _write_lock.
    """

    def test_retry_policy_fits_inside_one_budget(self):
        """Attempts x busy_timeout must not exceed the budget they run inside."""
        assert _MAX_CHAIN_WRITE_ATTEMPTS >= 2, "premise: a single-attempt policy cannot overrun"
        assert (
            _MAX_CHAIN_WRITE_ATTEMPTS * _CHAIN_BUSY_TIMEOUT_MS
            <= _CHAIN_WRITE_BUDGET_S * 1000
        )

    async def test_connection_uses_the_budgeted_busy_timeout(self, event_logs, tmp_path):
        """Crosses the seam: the computed constant reaches the live connection."""
        raw = await default_factory.connect(str(tmp_path / "raw.db"))
        try:
            async with raw.execute("PRAGMA busy_timeout") as cursor:
                house_default = [row async for row in cursor][0][0]
        finally:
            await raw.close()
        # Without this the assertion below could pass on a connection EventLog
        # never touched.
        assert house_default != _CHAIN_BUSY_TIMEOUT_MS, (
            f"premise: the factory default ({house_default}) must differ from the "
            f"budgeted value ({_CHAIN_BUSY_TIMEOUT_MS}) for this to discriminate"
        )

        log = await event_logs()
        async with log._db.execute("PRAGMA busy_timeout") as cursor:
            live = [row async for row in cursor][0][0]
        assert live == _CHAIN_BUSY_TIMEOUT_MS

    async def test_queued_caller_past_its_budget_makes_no_attempt(
        self, event_logs, tmp_path, monkeypatch
    ):
        """A caller that spent its whole budget queueing gets ZERO attempts.

        This used to assert one attempt and a "database is locked" error, which
        pinned the defect: that always-taken attempt was a full blocking try, so
        the budget bounded nothing. Measured against it — a 0.2s budget spent
        entirely queued still committed at 0.641s.

        Asserts on ATTEMPT COUNT, not elapsed time, so it does not flake on a
        slow runner. The queue is held open by the test rather than by real
        contention, so the wait is deterministic.
        """
        vessel = await event_logs("budget.db")
        blocker = await event_logs("budget.db")
        monkeypatch.setattr(event_log_module, "_CHAIN_WRITE_BUDGET_S", 0.2)
        await blocker._db.execute("BEGIN IMMEDIATE")

        attempts = {"n": 0}
        real_insert = vessel._insert_chained_row

        async def _counting(payload):
            attempts["n"] += 1
            return await real_insert(payload)

        monkeypatch.setattr(vessel, "_insert_chained_row", _counting)

        await vessel._write_lock.acquire()
        task = asyncio.create_task(vessel.log(category="c", event="queued"))
        try:
            await asyncio.sleep(0.5)  # > budget, so the deadline expires while queued
            assert not task.done(), "premise: the caller must still be waiting on _write_lock"
            assert attempts["n"] == 0, "premise: it must not have attempted before winning the lock"
        finally:
            vessel._write_lock.release()

        with pytest.raises(TimeoutError):
            await task
        assert attempts["n"] == 0

        await blocker._db.execute("ROLLBACK")

    async def test_contended_caller_stops_waiting_at_its_budget(
        self, event_logs, monkeypatch
    ):
        """One caller against a lock nobody releases.

        Measured before the per-attempt bound: a 5.0s budget raised at 5.907s,
        because the retry sleeps and one final full busy_timeout ran on top of
        the budget instead of inside it.
        """
        vessel = await event_logs("single.db")
        blocker = await event_logs("single.db")
        budget = 0.5
        monkeypatch.setattr(event_log_module, "_CHAIN_WRITE_BUDGET_S", budget)
        await blocker._db.execute("BEGIN IMMEDIATE")
        loop = asyncio.get_running_loop()
        try:
            started = loop.time()
            with pytest.raises(Exception) as excinfo:
                await vessel.log(category="c", event="contended")
            elapsed = loop.time() - started
        finally:
            await blocker._db.execute("ROLLBACK")

        assert _is_database_locked(excinfo.value) or isinstance(excinfo.value, TimeoutError), (
            f"premise: contention must actually have occurred, got {excinfo.value!r}"
        )
        # 2x is slack for scheduling, not for the contract: nothing here can make
        # progress, so the whole call is waiting. One untightened busy_timeout
        # alone is _CHAIN_BUSY_TIMEOUT_MS, which is over this bound.
        assert elapsed < budget * 2, (
            f"waited {elapsed:.3f}s against a {budget}s wait budget"
        )

    async def test_stale_queued_callers_do_not_stack_their_waits(
        self, event_logs, monkeypatch
    ):
        """Three callers behind one lock cost about one budget, not three.

        Measured before the bound, for a 5s budget: 5.938s / 7.844s / 9.766s —
        every stale caller added a full blocking attempt to everyone behind it.
        """
        vessel = await event_logs("stacked.db")
        blocker = await event_logs("stacked.db")
        budget = 0.5
        monkeypatch.setattr(event_log_module, "_CHAIN_WRITE_BUDGET_S", budget)
        await blocker._db.execute("BEGIN IMMEDIATE")
        loop = asyncio.get_running_loop()
        try:
            started = loop.time()
            results = await asyncio.gather(
                *(vessel.log(category="c", event=f"q{i}") for i in range(3)),
                return_exceptions=True,
            )
            elapsed = loop.time() - started
        finally:
            await blocker._db.execute("ROLLBACK")

        assert all(isinstance(r, BaseException) for r in results), (
            f"premise: every caller must have been blocked, got {results}"
        )
        assert elapsed < budget * 3, (
            f"three queued callers took {elapsed:.3f}s against a {budget}s wait budget"
        )


class TestIsDatabaseLocked:
    def test_returns_true_for_sqlite_busy_message(self):
        assert _is_database_locked(Exception("database is locked")) is True

    def test_returns_true_for_table_locked_message(self):
        assert _is_database_locked(Exception("database table is locked")) is True

    def test_returns_false_for_unrelated_error(self):
        assert _is_database_locked(ValueError("no such column: nope")) is False

    def test_returns_false_for_empty_message(self):
        assert _is_database_locked(Exception("")) is False


class TestRollbackQuietly:
    async def test_rollback_without_open_transaction_keeps_the_connection(self, event_logs):
        """SQLite reports "cannot rollback - no transaction is active".

        Also asserts the connection SURVIVES. This is the one rollback failure
        that must stay suppressed, so if the predicate stopped matching
        sqlite3's wording the connection would be taken out of service here and
        every later append would silently return None.
        """
        log = await event_logs()
        await log._rollback_quietly()

        assert log._db is not None
        assert await log.log(category="c", event="after") is not None

    async def test_rollback_without_database_is_a_noop(self):
        assert await EventLog(db_path="unused.db")._rollback_quietly() is None

    async def test_failed_rollback_takes_the_connection_out_of_service(self, event_logs):
        """A ROLLBACK that fails must not hand back a usable-looking connection.

        Reproduced before this narrowing: with a real BEGIN IMMEDIATE open and
        failure injected only for ROLLBACK, it returned with in_transaction=True
        and the next append died on "cannot start a transaction within a
        transaction" — self-healing only because THAT failure happened to
        trigger another, successful, rollback.
        """
        log = await event_logs()
        await log.log(category="c", event="before")

        db = log._db
        real_execute = db.execute
        seen = {"begin": 0, "rollback": 0}

        def _execute(sql, *args, **kwargs):
            statement = str(sql).lstrip().upper()
            if statement.startswith("BEGIN"):
                seen["begin"] += 1
            elif statement.startswith("ROLLBACK"):
                seen["rollback"] += 1
                raise RuntimeError("disk I/O error during rollback")
            elif statement.startswith("INSERT INTO EVENTS"):
                raise RuntimeError("insert exploded")
            return real_execute(sql, *args, **kwargs)

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture()
        event_log_module.logger.addHandler(handler)
        db.execute = _execute
        try:
            with pytest.raises(RuntimeError, match="insert exploded"):
                await log.log(category="c", event="poisoned")
        finally:
            db.execute = real_execute
            event_log_module.logger.removeHandler(handler)

        assert seen["begin"] == 1, "premise: a real transaction must have been open"
        assert seen["rollback"] == 1, "premise: the rollback path must actually have run"
        assert [r for r in records if r.levelno >= logging.ERROR], (
            "the rollback failure must surface loudly, not as a debug no-op"
        )

        # Crosses the seam: the connection is out of service, so the next append
        # degrades honestly instead of dying on "cannot start a transaction
        # within a transaction" against a handle that still looked usable.
        assert log._db is None
        assert await log.log(category="c", event="after") is None
