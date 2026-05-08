"""Tests for AD-700b: CognitiveJournal level tagging for diagnose_system."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.journal import CognitiveJournal


@pytest.fixture
async def journal(tmp_path):
    j = CognitiveJournal(db_path=str(tmp_path / "journal.db"))
    await j.start()
    yield j
    await j.stop()


@pytest.mark.asyncio
async def test_record_diagnose_system_l3_writes_level_and_rank(journal):
    await journal.record(
        entry_id="e1",
        timestamp=time.time(),
        agent_id="bones",
        intent="diagnose_system",
        level="L3",
        level_rank=3,
    )
    async with journal._db.execute(
        "SELECT level, level_rank FROM journal WHERE id = 'e1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "L3"
    assert row[1] == 3


@pytest.mark.asyncio
async def test_record_non_diagnose_intent_keeps_level_empty(journal):
    await journal.record(
        entry_id="e2",
        timestamp=time.time(),
        agent_id="bones",
        intent="medical_alert",
    )
    async with journal._db.execute(
        "SELECT level, level_rank FROM journal WHERE id = 'e2'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row[0] == ""
    assert row[1] == 0


@pytest.mark.asyncio
async def test_record_l1_l5_round_trip(journal):
    for i, lvl in enumerate(["L1", "L2", "L3", "L4", "L5"], start=1):
        await journal.record(
            entry_id=f"r{i}",
            timestamp=time.time(),
            agent_id="bones",
            intent="diagnose_system",
            level=lvl,
            level_rank=i,
        )
    async with journal._db.execute(
        "SELECT id, level, level_rank FROM journal ORDER BY id ASC"
    ) as cursor:
        rows = [tuple(r) async for r in cursor]
    assert rows == [
        ("r1", "L1", 1),
        ("r2", "L2", 2),
        ("r3", "L3", 3),
        ("r4", "L4", 4),
        ("r5", "L5", 5),
    ]


@pytest.mark.asyncio
async def test_migration_adds_columns_to_pre_ad700b_journal(tmp_path):
    """Pre-create AD-431/432-era journal schema (no level columns)."""
    import aiosqlite

    db_path = tmp_path / "old.db"
    db = await aiosqlite.connect(str(db_path))
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS journal (
            id          TEXT PRIMARY KEY,
            timestamp   REAL NOT NULL,
            agent_id    TEXT NOT NULL,
            agent_type  TEXT NOT NULL DEFAULT '',
            tier        TEXT NOT NULL DEFAULT 'standard',
            model       TEXT NOT NULL DEFAULT '',
            prompt_tokens    INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens     INTEGER NOT NULL DEFAULT 0,
            latency_ms       REAL NOT NULL DEFAULT 0.0,
            intent           TEXT NOT NULL DEFAULT '',
            success          INTEGER NOT NULL DEFAULT 1,
            cached           INTEGER NOT NULL DEFAULT 0,
            request_id       TEXT NOT NULL DEFAULT '',
            prompt_hash      TEXT NOT NULL DEFAULT '',
            response_length  INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    await db.commit()
    await db.close()

    j = CognitiveJournal(db_path=str(db_path))
    await j.start()
    async with j._db.execute("PRAGMA table_info(journal)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "level" in columns
    assert "level_rank" in columns
    await j.stop()


@pytest.mark.asyncio
async def test_migration_idempotent(journal):
    # Run migration a second time on an already-migrated DB
    await journal._migrate_ad700b()
    async with journal._db.execute("PRAGMA table_info(journal)") as cursor:
        column_list = [row[1] async for row in cursor]
    # Each column should appear exactly once
    assert column_list.count("level") == 1
    assert column_list.count("level_rank") == 1


@pytest.mark.asyncio
async def test_idx_journal_level_exists_after_start(journal):
    async with journal._db.execute("PRAGMA index_list(journal)") as cursor:
        index_names = {row[1] async for row in cursor}
    assert "idx_journal_level" in index_names
