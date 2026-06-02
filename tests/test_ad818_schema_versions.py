"""AD-818 (#751): tests for the schema-version sidecar + boot-scan short-circuit.

Uses real in-memory SQLite (connection_factory=lambda: aiosqlite.connect(":memory:"))
at the DB boundary — never MagicMock (Phantom-via-MagicMock lesson). The wrapper
tests drive a real async stub migration that flips a `called` flag and returns a
configurable int.
"""

from __future__ import annotations

import aiosqlite
import pytest

from probos.cognitive.schema_versions import MIGRATION_VERSIONS, SchemaVersionStore
from probos.startup.cognitive_services import _run_one_migration


def _store() -> SchemaVersionStore:
    return SchemaVersionStore(
        connection_factory=lambda: aiosqlite.connect(":memory:"),
    )


# --------------------------------------------------------------------------- #
# SchemaVersionStore
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_creates_table_get_works() -> None:
    store = _store()
    await store.start()
    try:
        # Table exists: a get against it returns None (no row) without error.
        assert await store.get("BF-103") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_record_get_roundtrip_returns_all_fields() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("AD-570", episode_count=42, version_hash="1", applied_at=123.0)
        row = await store.get("AD-570")
        assert row is not None
        assert row["migration_id"] == "AD-570"
        assert row["episode_count"] == 42
        assert row["version_hash"] == "1"
        assert row["applied_at"] == 123.0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_record_applied_at_auto_stamps_when_omitted() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("AD-584", episode_count=0, version_hash="1")
        row = await store.get("AD-584")
        assert row is not None
        assert row["applied_at"] > 0.0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_get_unknown_id_returns_none() -> None:
    store = _store()
    await store.start()
    try:
        assert await store.get("does-not-exist") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_is_current_true_when_row_and_hash_match() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("AD-605", episode_count=1, version_hash="1")
        assert await store.is_current("AD-605", "1") is True
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_is_current_false_on_hash_mismatch() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("AD-605", episode_count=1, version_hash="1")
        assert await store.is_current("AD-605", "2") is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_is_current_false_when_no_row() -> None:
    store = _store()
    await store.start()
    try:
        assert await store.is_current("BF-103", "1") is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_record_is_insert_or_replace() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("AD-570", episode_count=5, version_hash="1")
        await store.record("AD-570", episode_count=9, version_hash="2")
        row = await store.get("AD-570")
        assert row is not None
        assert row["episode_count"] == 9
        assert row["version_hash"] == "2"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_stop_is_safe_when_never_started() -> None:
    store = _store()
    # No start() — stop() must be a no-op, not raise.
    await store.stop()


# --------------------------------------------------------------------------- #
# _run_one_migration short-circuit / record-on-success
# --------------------------------------------------------------------------- #


class _StubMigration:
    """Real async stub: flips `called` and returns a configurable int."""

    def __init__(self, returns: int = 0) -> None:
        self.called = False
        self._returns = returns

    async def __call__(self) -> int:
        self.called = True
        return self._returns


@pytest.mark.asyncio
async def test_schema_store_none_always_calls() -> None:
    stub = _StubMigration(returns=3)
    await _run_one_migration(
        "BF-103", stub, 5.0, "ok %d %.1f", "noop %.1f",
        schema_store=None,
    )
    assert stub.called is True


@pytest.mark.asyncio
async def test_no_prior_row_calls_and_records() -> None:
    store = _store()
    await store.start()
    try:
        stub = _StubMigration(returns=7)
        await _run_one_migration(
            "BF-103", stub, 5.0, "ok %d %.1f", "noop %.1f",
            schema_store=store, migration_id="BF-103", version_hash="1",
        )
        assert stub.called is True
        row = await store.get("BF-103")
        assert row is not None
        assert row["version_hash"] == "1"
        assert row["episode_count"] == 7
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_matching_version_skips_migration() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("BF-103", episode_count=0, version_hash="1")
        stub = _StubMigration(returns=99)
        await _run_one_migration(
            "BF-103", stub, 5.0, "ok %d %.1f", "noop %.1f",
            schema_store=store, migration_id="BF-103", version_hash="1",
        )
        assert stub.called is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_mismatched_version_calls_and_updates() -> None:
    store = _store()
    await store.start()
    try:
        await store.record("BF-103", episode_count=1, version_hash="1")
        stub = _StubMigration(returns=4)
        await _run_one_migration(
            "BF-103", stub, 5.0, "ok %d %.1f", "noop %.1f",
            schema_store=store, migration_id="BF-103", version_hash="2",
        )
        assert stub.called is True
        row = await store.get("BF-103")
        assert row is not None
        assert row["version_hash"] == "2"
        assert row["episode_count"] == 4
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_migration_raises_records_nothing() -> None:
    store = _store()
    await store.start()
    try:
        async def _boom() -> int:
            raise RuntimeError("boom")

        await _run_one_migration(
            "BF-103", _boom, 5.0, "ok %d %.1f", "noop %.1f",
            schema_store=store, migration_id="BF-103", version_hash="1",
        )
        assert await store.get("BF-103") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_migration_times_out_records_nothing() -> None:
    import asyncio

    store = _store()
    await store.start()
    try:
        async def _slow() -> int:
            await asyncio.sleep(10)
            return 1

        await _run_one_migration(
            "BF-103", _slow, 0.01, "ok %d %.1f", "noop %.1f",
            schema_store=store, migration_id="BF-103", version_hash="1",
        )
        assert await store.get("BF-103") is None
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# MIGRATION_VERSIONS
# --------------------------------------------------------------------------- #


def test_migration_versions_has_exactly_five_versioned_ids() -> None:
    assert set(MIGRATION_VERSIONS) == {"BF-103", "AD-570", "AD-570b", "AD-584", "AD-605"}
    assert "BF-207" not in MIGRATION_VERSIONS
