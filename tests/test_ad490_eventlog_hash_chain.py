"""Tests for AD-490: EventLog hash chain (substrate-tier tamper detection)."""

from __future__ import annotations

import pytest

from probos.substrate.event_log import EventLog, _compute_row_hash


@pytest.fixture
async def event_log(tmp_path):
    el = EventLog(db_path=tmp_path / "test_events.db")
    await el.start()
    yield el
    await el.stop()


@pytest.mark.asyncio
async def test_log_first_event_uses_genesis_hash(event_log):
    await event_log.log(category="lifecycle", event="spawn", agent_id="a1")
    async with event_log._db.execute(
        "SELECT prev_hash, row_hash FROM events ORDER BY id ASC"
    ) as cursor:
        rows = [tuple(r) async for r in cursor]
    assert len(rows) == 1
    assert rows[0][0] == "0" * 64
    assert rows[0][1] != "" and len(rows[0][1]) == 64


@pytest.mark.asyncio
async def test_log_second_event_chains_to_first(event_log):
    await event_log.log(category="lifecycle", event="spawn", agent_id="a1")
    await event_log.log(category="lifecycle", event="active", agent_id="a1")
    async with event_log._db.execute(
        "SELECT id, prev_hash, row_hash FROM events ORDER BY id ASC"
    ) as cursor:
        rows = [tuple(r) async for r in cursor]
    assert len(rows) == 2
    assert rows[1][1] == rows[0][2]  # row 2's prev_hash == row 1's row_hash


def test_compute_row_hash_is_pure():
    payload = {"k": "v", "n": 1}
    h1 = _compute_row_hash(prev_hash="X", payload=payload)
    h2 = _compute_row_hash(prev_hash="X", payload=payload)
    assert h1 == h2
    assert len(h1) == 64
    # Different prev_hash -> different output
    h3 = _compute_row_hash(prev_hash="Y", payload=payload)
    assert h1 != h3


@pytest.mark.asyncio
async def test_verify_chain_empty_returns_ok_none(event_log):
    ok, broken = await event_log.verify_chain()
    assert ok is True
    assert broken is None


@pytest.mark.asyncio
async def test_verify_chain_intact_after_three_logs(event_log):
    await event_log.log(category="lifecycle", event="spawn", agent_id="a1")
    await event_log.log(category="mesh", event="intent", agent_id="a1")
    await event_log.log(category="system", event="tick")
    ok, broken = await event_log.verify_chain()
    assert ok is True
    assert broken is None


@pytest.mark.asyncio
async def test_verify_chain_detects_tampered_row(event_log):
    await event_log.log(category="lifecycle", event="spawn", agent_id="a1")
    await event_log.log(category="lifecycle", event="active", agent_id="a1")
    await event_log.log(category="lifecycle", event="degraded", agent_id="a1")
    # Tamper with row 2's detail
    await event_log._db.execute(
        "UPDATE events SET detail = 'tampered' WHERE id = 2"
    )
    await event_log._db.commit()
    ok, broken = await event_log.verify_chain()
    assert ok is False
    assert broken == 2


@pytest.mark.asyncio
async def test_verify_chain_detects_tampered_prev_hash(event_log):
    await event_log.log(category="lifecycle", event="spawn")
    await event_log.log(category="lifecycle", event="active")
    await event_log.log(category="lifecycle", event="degraded")
    await event_log._db.execute(
        "UPDATE events SET prev_hash = ? WHERE id = 2", ("f" * 64,)
    )
    await event_log._db.commit()
    ok, broken = await event_log.verify_chain()
    assert ok is False
    assert broken == 2


@pytest.mark.asyncio
async def test_migration_adds_columns_to_legacy_db(tmp_path):
    """Pre-create AD-664-era schema (no hash columns), then migrate via start()."""
    import aiosqlite

    db_path = tmp_path / "legacy.db"
    db = await aiosqlite.connect(str(db_path))
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT    NOT NULL,
            category        TEXT    NOT NULL,
            event           TEXT    NOT NULL,
            agent_id        TEXT,
            agent_type      TEXT,
            pool            TEXT,
            detail          TEXT,
            correlation_id  TEXT,
            parent_event_id INTEGER,
            data            TEXT
        );
        """
    )
    await db.commit()
    await db.close()

    el = EventLog(db_path=db_path)
    await el.start()
    async with el._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "prev_hash" in columns
    assert "row_hash" in columns
    await el.stop()
