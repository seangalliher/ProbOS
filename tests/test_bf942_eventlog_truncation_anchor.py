"""BF-942 (#1706): routine pruning leaves the EventLog's hash chain verifiable from a durable truncation anchor.

Real ``EventLog`` files under ``tmp_path``, ``~`` moved, no network. Rows come from ``log()`` (real hashes); the age
cases move the module's clock. The functions before the class pass on the unfixed tree (T0); the class holds the
cases it fails. No BF-942 name is imported: ``state`` and ``anchor_id`` are read with ``getattr`` (the unfixed tree
returns a plain tuple) and the anchor rows by a helper that finds no table there.
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from probos.substrate import event_log as event_log_module
from probos.substrate.event_log import EventLog

_NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


class _Clock(datetime):
    """The module's ``datetime`` with a settable ``now()``: ``log()`` stamps rows and ``prune()`` takes its cutoff from ``at``."""

    at = _NOW

    @classmethod
    def now(cls, tz=None):
        return cls.at.astimezone(tz)


@pytest.fixture(autouse=True)
def _moved_home(tmp_path, monkeypatch):
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "home"))


def _clock(monkeypatch):
    """Install the clock; the function it returns sets the time to ``days_ago`` days before ``_NOW``."""
    monkeypatch.setattr(event_log_module, "datetime", _Clock)

    def at(days_ago: float = 0) -> None:
        monkeypatch.setattr(_Clock, "at", _NOW - timedelta(days=days_ago))

    at(0)
    return at


@asynccontextmanager
async def _opened(tmp_path, name: str = "events.db"):
    log = EventLog(db_path=tmp_path / name)
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _fill(log, count: int) -> list[int]:
    return [await log.log(category="c", event=f"e{i}", data={"i": i}) for i in range(count)]


async def _rows(log) -> list[tuple]:
    async with log._db.execute("SELECT id, prev_hash, row_hash FROM events ORDER BY id") as cursor:
        return [tuple(row) async for row in cursor]


async def _anchors(log) -> list[tuple]:
    """The anchor table's ``(event_id, row_hash)`` rows; none where the table does not exist (the unfixed tree)."""
    async with log._db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events_truncation_anchor'"
    ) as cursor:
        if await cursor.fetchone() is None:
            return []
    async with log._db.execute("SELECT event_id, row_hash FROM events_truncation_anchor") as cursor:
        return [tuple(row) async for row in cursor]


async def _sql(log, sql: str, *params) -> None:
    await log._db.execute(sql, params)
    await log._db.commit()


def _seen(verdict):
    """``(the pair, state, anchor_id)``; the last two are None on the unfixed tree's plain tuple."""
    return (tuple(verdict), getattr(verdict, "state", None), getattr(verdict, "anchor_id", None))


# ------------------------------------------------------------------
# T0: guards (pass on both trees)
# ------------------------------------------------------------------


async def test_a_prune_that_deletes_nothing_writes_no_anchor_and_changes_nothing(tmp_path):
    async with _opened(tmp_path) as log:
        await _fill(log, 5)
        before = await _rows(log)
        assert await log.prune(retention_days=7, max_rows=100) == 0
        assert (await _anchors(log), await _rows(log)) == ([], before)
        assert await log.verify_chain() == (True, None)


async def test_an_edit_to_the_first_retained_row_is_detected_there(tmp_path):
    async with _opened(tmp_path) as log:
        ids = await _fill(log, 8)
        assert await log.prune(retention_days=0, max_rows=5) == 3
        await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[3])
        assert await log.verify_chain() == (False, ids[3])


async def test_a_prune_whose_delete_fails_rolls_the_anchor_back_with_it(tmp_path):
    async with _opened(tmp_path) as log:
        await _fill(log, 8)
        before = await _rows(log)
        real = log._db.execute

        def failing(sql, *args, **kwargs):
            if str(sql).lstrip().startswith("DELETE FROM events WHERE"):
                raise RuntimeError("the delete failed")
            return real(sql, *args, **kwargs)

        log._db.execute = failing
        raised = None
        try:
            await log.prune(retention_days=0, max_rows=5)
        except RuntimeError as exc:
            raised = exc
        log._db.execute = real
        assert raised is not None, "premise: the delete must have been reached and failed"
        assert (await _rows(log), await _anchors(log)) == (before, [])
        assert await log.log(category="c", event="after") is not None
        assert await log.verify_chain() == (True, None)


async def test_a_cancelled_prune_leaves_no_open_transaction_and_no_anchor(tmp_path):
    async with _opened(tmp_path, "shared.db") as vessel, _opened(tmp_path, "shared.db") as blocker:
        await _fill(vessel, 6)
        await blocker._db.execute("BEGIN IMMEDIATE")
        task = asyncio.create_task(vessel.prune(retention_days=0, max_rows=3))
        await asyncio.sleep(0.2)
        assert not task.done(), "premise: the prune must still be waiting for the write lock"
        task.cancel()
        await asyncio.sleep(0.05)
        await blocker._db.execute("ROLLBACK")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await vessel.log(category="c", event="after") is not None
        assert (await _anchors(vessel), await vessel.count()) == ([], 7)
        assert await vessel.verify_chain() == (True, None)


# ------------------------------------------------------------------
# T1 to T7: the cases the unfixed tree fails
# ------------------------------------------------------------------


class TestTheChainSurvivesAPrune:
    async def test_an_unpruned_chain_is_intact_and_an_edit_to_it_is_broken(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 5)
            assert _seen(await log.verify_chain()) == ((True, None), "intact", None)
            await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[2])
            assert _seen(await log.verify_chain()) == ((False, ids[2]), "broken", None)

    async def test_after_a_prune_the_chain_verifies_from_the_anchor_it_names(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            before = await _rows(log)
            assert await log.verify_chain() == (True, None)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            assert await _rows(log) == before[4:]
            verdict = await log.verify_chain()
            assert verdict == (True, None)
            ok, broken_at = verdict
            assert (ok, broken_at) == (True, None)
            assert _seen(verdict) == ((True, None), "truncated", ids[3])
            assert await _anchors(log) == [(ids[3], before[3][2])]

    async def test_after_an_age_prune_the_chain_verifies_from_the_last_old_row(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            old = await _fill(log, 3)
            at(1)
            await _fill(log, 2)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])

    async def test_an_age_prune_deletes_the_row_with_the_highest_id_sqlite_allows(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            await _sql(log, "INSERT INTO sqlite_sequence (name, seq) VALUES ('events', ?)", 2**63 - 3)
            at(10)
            ids = await _fill(log, 2)
            assert ids == [2**63 - 2, 2**63 - 1], "premise: the two rows hold the two highest ids"
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 2
            assert (await _rows(log), await _anchors(log)) == ([], [(ids[1], before[1][2])])
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[1])

    async def test_when_both_stages_delete_one_anchor_names_the_last_row_deleted(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            await _fill(log, 3)
            at(1)
            await _fill(log, 7)
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=5) == 5
            assert await _anchors(log) == [(before[4][0], before[4][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", before[4][0])

    async def test_an_edit_to_a_retained_row_is_detected_at_that_row(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[7])
            assert _seen(await log.verify_chain()) == ((False, ids[7]), "broken", ids[3])

    @pytest.mark.parametrize("victim", [4, 6])
    async def test_deleting_a_retained_row_is_detected_not_mistaken_for_a_truncation(self, tmp_path, victim):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await _sql(log, "DELETE FROM events WHERE id = ?", ids[victim])
            assert _seen(await log.verify_chain()) == ((False, ids[victim + 1]), "broken", ids[3])

    async def test_a_reopened_store_verifies_the_same_way(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            anchors = await _anchors(log)
        async with _opened(tmp_path) as reopened:
            assert _seen(await reopened.verify_chain()) == ((True, None), "truncated", ids[3])
            assert await _anchors(reopened) == anchors

    async def test_two_prunes_keep_one_anchor_at_the_latest_cut_and_a_later_no_op_leaves_it(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 12)
            before = await _rows(log)
            assert await log.prune(retention_days=0, max_rows=9) == 3
            assert await log.prune(retention_days=0, max_rows=5) == 4
            assert await log.prune(retention_days=7, max_rows=100) == 0
            assert await _anchors(log) == [(ids[6], before[6][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[6])

    async def test_a_prune_that_empties_the_table_restarts_the_chain_and_it_still_verifies(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            at(10)
            old = await _fill(log, 3)
            before = await _rows(log)
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert await _rows(log) == []
            assert await _anchors(log) == [(old[2], before[2][2])]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
            await _fill(log, 2)
            first = (await _rows(log))[0]
            assert first[:2] == (old[2] + 1, EventLog.GENESIS_HASH), "premise: the append restarts at genesis"
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])

    async def test_a_clock_stepped_back_cannot_make_the_age_prune_cut_the_middle(self, tmp_path, monkeypatch):
        at = _clock(monkeypatch)
        async with _opened(tmp_path) as log:
            for days_ago in (10, 10, 10, 1, 9, 0.5):  # the fifth row was stamped after the clock stepped back
                at(days_ago)
                await _fill(log, 1)
            ids = [row[0] for row in await _rows(log)]
            at(0)
            assert await log.prune(retention_days=7, max_rows=0) == 3
            assert [row[0] for row in await _rows(log)] == ids[3:]
            assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[2])

    async def test_wipe_clears_the_anchor_with_the_events(self, tmp_path):
        async with _opened(tmp_path) as log:
            await _fill(log, 10)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await log.wipe()
            assert await _anchors(log) == []
            await _fill(log, 2)
            assert _seen(await log.verify_chain()) == ((True, None), "intact", None)

    async def test_log_and_prune_together_stay_serialized_and_the_chain_verifies(self, tmp_path):
        async with _opened(tmp_path) as log:
            await _fill(log, 6)
            results = await asyncio.gather(
                log.prune(retention_days=0, max_rows=3),
                log.log(category="c", event="concurrent"),
                return_exceptions=True,
            )
            assert [r for r in results if isinstance(r, BaseException)] == []
            assert results[0] > 0, "premise: the prune must have deleted"
            pair, state, anchor_id = _seen(await log.verify_chain())
            assert (pair, state) == ((True, None), "truncated")
            assert [row[0] for row in await _anchors(log)] == [anchor_id]

    async def test_a_store_pruned_before_the_anchor_existed_is_never_reported_intact(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 8)
            await _sql(log, "DELETE FROM events WHERE id <= ?", ids[2])  # what the old prune did: no anchor
            assert _seen(await log.verify_chain()) == ((False, ids[3]), "unanchored", None)

    async def test_a_cut_head_with_no_anchor_does_not_hide_an_edit_behind_it(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 8)
            await _sql(log, "DELETE FROM events WHERE id <= ?", ids[2])
            await _sql(log, "UPDATE events SET detail = 'edited' WHERE id = ?", ids[6])
            assert _seen(await log.verify_chain()) == ((False, ids[6]), "broken", None)

    async def test_the_first_retained_row_must_follow_the_anchor(self, tmp_path):
        async with _opened(tmp_path) as log:
            ids = await _fill(log, 10)
            before = await _rows(log)
            assert await log.prune(retention_days=0, max_rows=6) == 4
            await _sql(
                log,
                "CREATE TABLE IF NOT EXISTS events_truncation_anchor "
                "(singleton INTEGER PRIMARY KEY CHECK (singleton = 1), event_id INTEGER NOT NULL, row_hash TEXT NOT NULL)",
            )
            # The true hash, but an id that does not come before the retained rows.
            await _sql(log, "INSERT OR REPLACE INTO events_truncation_anchor VALUES (1, ?, ?)", ids[9], before[3][2])
            assert _seen(await log.verify_chain()) == ((False, ids[4]), "broken", ids[9])

    async def test_an_existing_store_gains_the_anchor_table_and_no_row_changes(self, tmp_path):
        async with _opened(tmp_path) as log:
            await _fill(log, 5)
            await _sql(log, "DROP TABLE IF EXISTS events_truncation_anchor")  # a store made before BF-942
        con = sqlite3.connect(tmp_path / "events.db")
        before = con.execute("SELECT * FROM events ORDER BY id").fetchall()
        con.close()
        async with _opened(tmp_path) as reopened:
            async with reopened._db.execute(
                "SELECT name FROM sqlite_master WHERE name = 'events_truncation_anchor'"
            ) as cursor:
                assert await cursor.fetchone() is not None
            async with reopened._db.execute("SELECT * FROM events ORDER BY id") as cursor:
                assert [tuple(row) async for row in cursor] == before
            assert await reopened.verify_chain() == (True, None)
