"""BF-980 (#1811): after a prune empties the event table, the next row chains from the truncation anchor.

Real ``EventLog`` files under ``tmp_path``, ``~`` moved, no network. Rows come from ``log()`` (real hashes); the age
cases move the module's clock as BF-942's tests do. A row "restarted at genesis" is written the way the append before
BF-980 wrote it: linked to ``GENESIS_HASH`` with its hash recomputed by ``_compute_row_hash`` (AD-490), so the walk's
hash check passes and only the link decides the verdict. Every case asserts the state it needs (an anchor beside an
empty table, a genesis-linked first row) before it asserts the effect.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from probos.substrate import event_log as event_log_module
from probos.substrate.event_log import EventLog, _compute_row_hash

_NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
_PAYLOAD_COLUMNS = (
    "timestamp", "category", "event", "agent_id", "agent_type", "pool", "detail",
    "correlation_id", "parent_event_id", "data",
)


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
    async with log._db.execute("SELECT event_id, row_hash FROM events_truncation_anchor") as cursor:
        return [tuple(row) async for row in cursor]


async def _sql(log, sql: str, *params) -> None:
    await log._db.execute(sql, params)
    await log._db.commit()


def _seen(verdict):
    """``(the pair, state, anchor_id)`` of a ``ChainVerdict``."""
    return (tuple(verdict), verdict.state, verdict.anchor_id)


async def _relink_to_genesis(log, row_id: int) -> None:
    """Rewrite one row as the append before BF-980 wrote it on an emptied table: linked to genesis, hash recomputed."""
    async with log._db.execute(
        f"SELECT {', '.join(_PAYLOAD_COLUMNS)} FROM events WHERE id = ?", (row_id,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None, "premise: the row to relink exists"
    row_hash = _compute_row_hash(prev_hash=EventLog.GENESIS_HASH, payload=dict(zip(_PAYLOAD_COLUMNS, row)))
    await _sql(
        log, "UPDATE events SET prev_hash = ?, row_hash = ? WHERE id = ?", EventLog.GENESIS_HASH, row_hash, row_id
    )


async def _emptied(log, at) -> tuple[int, str]:
    """Log three rows ten days ago, prune them all by age, and prove the state BF-980 is about was reached."""
    at(10)
    old = await _fill(log, 3)
    before = await _rows(log)
    at(0)
    assert await log.prune(retention_days=7, max_rows=0) == 3, "premise: the age prune deletes every row"
    assert await _rows(log) == [], "premise: the table is empty"
    assert await _anchors(log) == [(old[2], before[2][2])], "premise: the anchor names the last row deleted"
    return old[2], before[2][2]


# A1 (the issue's first acceptance line)
async def test_a_prune_to_empty_then_one_event_chains_from_the_anchor(tmp_path, monkeypatch):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, anchor_hash = await _emptied(log, at)
        new_id = await log.log(category="c", event="after")
        rows = await _rows(log)
        assert [row[0] for row in rows] == [new_id] and new_id > anchor_id, "premise: one row, after the anchor"
        assert rows[0][1] == anchor_hash
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", anchor_id)


# A2 (the issue's second acceptance line)
async def test_a_first_row_forged_from_genesis_after_an_anchor_is_broken(tmp_path, monkeypatch):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, _ = await _emptied(log, at)
        forged = await log.log(category="c", event="forged")
        await _relink_to_genesis(log, forged)
        assert (await _rows(log))[0][:2] == (forged, EventLog.GENESIS_HASH), (
            "premise: the first row after the anchor links to genesis"
        )
        assert _seen(await log.verify_chain()) == ((False, forged), "broken", anchor_id)
        await _sql(log, "DELETE FROM events_truncation_anchor")
        assert _seen(await log.verify_chain()) == ((True, None), "intact", None), (
            "control: the forged row is a well-formed genesis row; only the anchor rule rejects it"
        )


# A3
async def test_after_a_prune_that_keeps_rows_the_append_chains_from_the_tail_not_the_anchor(tmp_path):
    async with _opened(tmp_path) as log:
        ids = await _fill(log, 10)
        before = await _rows(log)
        assert await log.prune(retention_days=0, max_rows=6) == 4
        assert await _anchors(log) == [(ids[3], before[3][2])], "premise: an anchor beside kept rows"
        new_id = await log.log(category="c", event="after")
        assert (await _rows(log))[-1][:2] == (new_id, before[9][2])
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", ids[3])


# A4
async def test_a_store_holding_an_anchor_and_no_rows_when_reopened_chains_its_next_row_from_the_anchor(
    tmp_path, monkeypatch
):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, anchor_hash = await _emptied(log, at)
    async with _opened(tmp_path) as reopened:
        assert (await _rows(reopened), await _anchors(reopened)) == ([], [(anchor_id, anchor_hash)]), (
            "premise: the reopened store holds the anchor and no row"
        )
        new_id = await reopened.log(category="c", event="after")
        assert (await _rows(reopened))[0][:2] == (new_id, anchor_hash)
        assert _seen(await reopened.verify_chain()) == ((True, None), "truncated", anchor_id)


# A5
async def test_wipe_after_an_anchor_still_starts_the_chain_at_genesis(tmp_path):
    async with _opened(tmp_path) as log:
        await _fill(log, 10)
        assert await log.prune(retention_days=0, max_rows=6) == 4
        assert await _anchors(log) != [], "premise: an anchor exists before the wipe"
        await log.wipe()
        assert (await _rows(log), await _anchors(log)) == ([], []), "premise: the wipe removed the rows and the anchor"
        new_id = await log.log(category="c", event="after")
        assert (await _rows(log))[0][:2] == (new_id, EventLog.GENESIS_HASH)
        assert _seen(await log.verify_chain()) == ((True, None), "intact", None)


# A6
async def test_an_empty_log_that_was_never_pruned_starts_at_genesis(tmp_path):
    async with _opened(tmp_path) as log:
        assert (await _rows(log), await _anchors(log)) == ([], []), "premise: no rows and no anchor"
        ids = await _fill(log, 2)
        rows = await _rows(log)
        assert [row[:2] for row in rows] == [(ids[0], EventLog.GENESIS_HASH), (ids[1], rows[0][2])]
        assert _seen(await log.verify_chain()) == ((True, None), "intact", None)


# A7 (D3: the compatibility decision)
async def test_a_store_that_held_a_genesis_restart_reads_broken_until_its_next_prune_moves_the_anchor(
    tmp_path, monkeypatch
):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, _ = await _emptied(log, at)
        restart = await log.log(category="c", event="restart")
        await _relink_to_genesis(log, restart)  # what the append before BF-980 wrote here
        second = await log.log(category="c", event="next")
        held = await _rows(log)
        assert held[0][:2] == (restart, EventLog.GENESIS_HASH) and held[1][:2] == (second, held[0][2]), (
            "premise: the store holds an anchor, a row chained from genesis and a row chained from it"
        )
    async with _opened(tmp_path) as reopened:
        assert await _rows(reopened) == held, "premise: opening the store rewrites no row"
        assert _seen(await reopened.verify_chain()) == ((False, restart), "broken", anchor_id)
        newest = await reopened.log(category="c", event="newest")
        assert await reopened.prune(retention_days=0, max_rows=1) == 2, "premise: the next prune deletes the restart rows"
        assert [row[0] for row in await _rows(reopened)] == [newest]
        assert await _anchors(reopened) == [(second, held[1][2])]
        assert _seen(await reopened.verify_chain()) == ((True, None), "truncated", second)


# A8 (D1: the anchor's hash is taken verbatim)
async def test_the_append_and_the_walk_take_the_anchor_hash_verbatim_even_when_it_is_empty(tmp_path, monkeypatch):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        anchor_id, _ = await _emptied(log, at)
        # A row written before AD-490 carries row_hash '' (BF-942 L4); an anchor naming one holds ''.
        await _sql(log, "UPDATE events_truncation_anchor SET row_hash = '' WHERE singleton = 1")
        assert await _anchors(log) == [(anchor_id, "")], "premise: the anchor holds an empty hash"
        new_id = await log.log(category="c", event="after")
        assert (await _rows(log))[0][:2] == (new_id, "")
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", anchor_id)


# A9
async def test_a_prune_that_empties_the_table_and_a_concurrent_append_leave_a_chain_that_verifies(
    tmp_path, monkeypatch
):
    at = _clock(monkeypatch)
    async with _opened(tmp_path) as log:
        at(10)
        old = await _fill(log, 3)
        before = await _rows(log)
        at(0)
        results = await asyncio.gather(
            log.prune(retention_days=7, max_rows=0),
            log.log(category="c", event="concurrent"),
            return_exceptions=True,
        )
        assert [r for r in results if isinstance(r, BaseException)] == []
        assert results[0] == 3, "premise: the prune deleted every old row"
        rows = await _rows(log)
        assert [row[0] for row in rows] == [results[1]], "premise: only the concurrent row remains"
        # Whichever order the write lock admits them in, the row follows the last old row's hash:
        # appended first it chains from the tail, appended after the prune from the anchor.
        assert rows[0][1] == before[2][2]
        assert _seen(await log.verify_chain()) == ((True, None), "truncated", old[2])
