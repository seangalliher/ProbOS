"""AD-456d: AuditLog SQLite persistence tests."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.events import EventType
from probos.security.audit import (
    AuditEntry,
    AuditLog,
    AuditLogPersistence,
    _SCHEMA,
)
from probos.storage.sqlite_factory import SQLiteConnectionFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_log(*, with_emit: bool = False) -> tuple[AuditLog, MagicMock | None]:
    emit = MagicMock() if with_emit else None
    log = AuditLog(emit_event=emit)
    return log, emit


def _make_persistence(
    tmp_path: Path,
    *,
    filename: str = "audit_test.db",
    with_emit: bool = False,
) -> tuple[AuditLogPersistence, MagicMock | None]:
    emit = MagicMock() if with_emit else None
    persistence = AuditLogPersistence(
        db_path=str(tmp_path / filename),
        connection_factory=SQLiteConnectionFactory(),
        emit_event=emit,
    )
    return persistence, emit


# ---------------------------------------------------------------------------
# Backwards compat — AuditLog without persistence
# ---------------------------------------------------------------------------

def test_auditlog_constructs_without_persistence_unchanged() -> None:
    """AD-456 v1 contract preserved: AuditLog with no persistence behaves
    identically to today (sync append, in-memory chain, AUDIT_RECORDED emit).
    """
    log, emit = _make_log(with_emit=True)
    assert log._persistence is None
    # AD-1278 retired the `_pending_writes` task set (one task per append) for a
    # single bounded queue. Repointed rather than deleted: what this pins is
    # "nothing is scheduled without persistence attached", which the queue
    # staying unbuilt says just as exactly.
    assert log._queue is None
    assert log._writer_task is None

    e = log.append(category="auth", detail="login user=alice")

    assert isinstance(e, AuditEntry)
    assert e.sequence == 0
    assert log.entries == [e]
    assert emit is not None
    emit.assert_called_once()
    args = emit.call_args.args
    assert args[0] == EventType.AUDIT_RECORDED


def test_attach_persistence_sets_field_no_other_side_effects() -> None:
    """attach_persistence is a pure setter (mirrors OracleService.attach_semantic_layer)."""
    log, _ = _make_log(with_emit=False)
    fake_persistence = MagicMock(spec=AuditLogPersistence)

    log.attach_persistence(fake_persistence)

    assert log._persistence is fake_persistence
    # No other side effects — entries unchanged, no writer stood up.
    assert log.entries == []
    assert log._queue is None
    assert log._writer_task is None


# ---------------------------------------------------------------------------
# AuditLogPersistence — start / stop / count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistence_start_creates_schema_and_starts_empty(tmp_path: Path) -> None:
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        assert await persistence.count() == 0
        # Schema constant is non-empty and references the table name.
        assert "audit_log" in _SCHEMA
        assert "entry_hash" in _SCHEMA
    finally:
        await persistence.stop()


# ---------------------------------------------------------------------------
# persist_entry — single + multiple + ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_entry_inserts_one_row(tmp_path: Path) -> None:
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        entry = AuditEntry(
            sequence=0,
            timestamp=1700000000.0,
            category="auth",
            detail="login user=bob",
            prior_hash=AuditLog.GENESIS_HASH,
            entry_hash="a" * 64,
        )
        await persistence.persist_entry(entry)
        assert await persistence.count() == 1

        loaded = await persistence.load_entries()
        assert len(loaded) == 1
        assert loaded[0] == entry
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_persist_entry_multiple_preserves_sequence(tmp_path: Path) -> None:
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        for i in range(3):
            await persistence.persist_entry(
                AuditEntry(
                    sequence=i,
                    timestamp=1700000000.0 + i,
                    category="evt",
                    detail=f"item-{i}",
                    prior_hash=("0" * 64) if i == 0 else (str(i - 1) * 64),
                    entry_hash=str(i) * 64,
                )
            )
        assert await persistence.count() == 3
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_load_entries_returns_rows_in_sequence_order(tmp_path: Path) -> None:
    """Locks the SQL ``ORDER BY sequence ASC`` requirement — without it,
    SQLite may return rows in any order, breaking chain rehydration.
    """
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        # Insert deliberately out of order to verify ORDER BY does the work.
        for i in [4, 0, 2, 3, 1]:
            await persistence.persist_entry(
                AuditEntry(
                    sequence=i,
                    timestamp=1700000000.0 + i,
                    category="evt",
                    detail=f"item-{i}",
                    prior_hash=("0" * 64),
                    entry_hash=f"{i:064d}",
                )
            )

        loaded = await persistence.load_entries()
        assert [e.sequence for e in loaded] == [0, 1, 2, 3, 4]
    finally:
        await persistence.stop()


# ---------------------------------------------------------------------------
# Append + persistence integration — fire-and-forget task path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_with_persistence_attached_persists_via_task(tmp_path: Path) -> None:
    """AuditLog.append enqueues for the single writer when a running loop is
    present; ``flush()`` synchronises.

    AD-1278 repointed this from ``_pending_writes``: the append no longer mints
    a task per entry, so "exactly one task was scheduled" became "exactly one
    entry is queued and exactly one writer exists".
    """
    persistence, _ = _make_persistence(tmp_path)
    await persistence.start()
    try:
        log, _ = _make_log(with_emit=False)
        log.attach_persistence(persistence)

        log.append(category="auth", detail="login user=carol")
        assert log._queue is not None
        assert log._queue.qsize() == 1
        assert log._writer_task is not None

        await log.flush()

        assert await persistence.count() == 1
        assert log._queue.qsize() == 0
    finally:
        await persistence.stop()


def test_append_without_running_loop_is_silent_noop_with_debug_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Sync append() with persistence attached but no running loop logs
    DEBUG and returns the entry — must not raise.
    """
    log, _ = _make_log(with_emit=False)
    fake_persistence = MagicMock(spec=AuditLogPersistence)
    log.attach_persistence(fake_persistence)

    caplog.set_level(logging.DEBUG, logger="probos.security.audit")
    e = log.append(category="auth", detail="login user=dave")

    assert isinstance(e, AuditEntry)
    assert log._queue is None
    fake_persistence.persist_entry.assert_not_called()
    assert any(
        "without running loop" in rec.message
        for rec in caplog.records
    )


def test_append_without_persistence_is_unchanged_sync_noop() -> None:
    """No persistence attached → no writer stood up, no queue, no warning."""
    log, _ = _make_log(with_emit=False)
    e = log.append(category="auth", detail="login user=eve")
    assert isinstance(e, AuditEntry)
    assert log._queue is None
    assert log._writer_task is None
    assert log._persistence is None


# ---------------------------------------------------------------------------
# AUDIT_PERSISTED event + persist failure handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_persisted_event_emitted_after_successful_insert(
    tmp_path: Path,
) -> None:
    persistence, emit = _make_persistence(tmp_path, with_emit=True)
    await persistence.start()
    try:
        entry = AuditEntry(
            sequence=0,
            timestamp=1700000000.0,
            category="auth",
            detail="login user=fred",
            prior_hash=AuditLog.GENESIS_HASH,
            entry_hash="b" * 64,
        )
        await persistence.persist_entry(entry)

        assert emit is not None
        persisted_calls = [
            c for c in emit.call_args_list
            if c.args and c.args[0] == EventType.AUDIT_PERSISTED
        ]
        assert len(persisted_calls) == 1
        payload = persisted_calls[0].args[1]
        assert payload == {"sequence": 0, "entry_hash": "b" * 64}
    finally:
        await persistence.stop()


@pytest.mark.asyncio
async def test_persist_entry_failure_logs_and_does_not_propagate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Tier-2 log-and-degrade: SQLite errors must not escape persist_entry."""
    persistence, emit = _make_persistence(tmp_path, with_emit=True)
    await persistence.start()
    try:
        entry = AuditEntry(
            sequence=0,
            timestamp=1700000000.0,
            category="auth",
            detail="login user=ginger",
            prior_hash=AuditLog.GENESIS_HASH,
            entry_hash="c" * 64,
        )
        await persistence.persist_entry(entry)
        assert await persistence.count() == 1

        # Insert again with the same sequence (PK collision) — must NOT raise.
        caplog.set_level(logging.WARNING, logger="probos.security.audit")
        await persistence.persist_entry(entry)
        # Count unchanged — second insert failed silently.
        assert await persistence.count() == 1
        assert any(
            "AuditLog persist failed" in rec.message
            for rec in caplog.records
        )
        # AUDIT_PERSISTED emitted once for the successful insert; NOT twice.
        assert emit is not None
        persisted_count = sum(
            1 for c in emit.call_args_list
            if c.args and c.args[0] == EventType.AUDIT_PERSISTED
        )
        assert persisted_count == 1
    finally:
        await persistence.stop()


# ---------------------------------------------------------------------------
# Rehydrate on boot — verify_chain happy + tamper detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rehydrate_extend_then_verify_chain_intact(tmp_path: Path) -> None:
    """First-run: append 3 entries to AuditLog → persist via task path.
    Second-run: fresh AuditLog + load_entries → extend → verify_chain True.
    """
    db_file = tmp_path / "audit_rehydrate.db"

    # First-run cycle.
    persistence_1 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_1.start()
    log_1, _ = _make_log(with_emit=False)
    log_1.attach_persistence(persistence_1)
    for i in range(3):
        log_1.append(category="evt", detail=f"item-{i}")
    await log_1.flush()
    assert await persistence_1.count() == 3
    await persistence_1.stop()

    # Second-run cycle: rehydrate.
    persistence_2 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_2.start()
    try:
        loaded = await persistence_2.load_entries()
        assert len(loaded) == 3

        log_2, _ = _make_log(with_emit=False)
        log_2.entries.extend(loaded)
        assert log_2.verify_chain() is True
    finally:
        await persistence_2.stop()


@pytest.mark.asyncio
async def test_rehydrate_after_db_tamper_verify_chain_false(tmp_path: Path) -> None:
    """If a row is mutated in the DB out-of-band, rehydrate + verify_chain
    catches it (returns False). Locks the warn-don't-fail-boot contract:
    finalize wiring logs WARNING and continues.
    """
    db_file = tmp_path / "audit_tamper.db"

    persistence_1 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_1.start()
    log_1, _ = _make_log(with_emit=False)
    log_1.attach_persistence(persistence_1)
    for i in range(3):
        log_1.append(category="evt", detail=f"item-{i}")
    await log_1.flush()
    # Tamper the middle row's detail without recomputing hash.
    await persistence_1._db.execute(
        "UPDATE audit_log SET detail = ? WHERE sequence = 1",
        ("MUTATED",),
    )
    await persistence_1._db.commit()
    await persistence_1.stop()

    # Second-run: rehydrate + verify.
    persistence_2 = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=SQLiteConnectionFactory(),
    )
    await persistence_2.start()
    try:
        loaded = await persistence_2.load_entries()
        log_2, _ = _make_log(with_emit=False)
        log_2.entries.extend(loaded)
        # Tamper detected.
        assert log_2.verify_chain() is False
    finally:
        await persistence_2.stop()


# ---------------------------------------------------------------------------
# Custom ConnectionFactory injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistence_accepts_custom_connection_factory(tmp_path: Path) -> None:
    """connection_factory is a required kwarg; tests can inject a custom
    factory that wraps SQLiteConnectionFactory (or anything implementing
    the ConnectionFactory Protocol). Locks the cloud-ready seam.
    """
    calls: list[str] = []

    class WrappingFactory:
        def __init__(self) -> None:
            self._inner = SQLiteConnectionFactory()

        async def connect(self, db_path: str) -> Any:
            calls.append(db_path)
            return await self._inner.connect(db_path)

    factory = WrappingFactory()
    db_file = tmp_path / "audit_custom_factory.db"
    persistence = AuditLogPersistence(
        db_path=str(db_file),
        connection_factory=factory,
    )
    await persistence.start()
    try:
        assert calls == [str(db_file)]
        assert await persistence.count() == 0
    finally:
        await persistence.stop()
