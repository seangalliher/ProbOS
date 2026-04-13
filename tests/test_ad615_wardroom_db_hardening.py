"""AD-615: Ward Room database performance hardening — WAL mode, busy_timeout, synchronous."""

import ast

import pytest
import pytest_asyncio

from probos.ward_room.service import WardRoomService


@pytest_asyncio.fixture
async def ward_room(tmp_path):
    """Create a WardRoomService with temp SQLite DB."""
    events = []
    def capture_event(event_type, data):
        events.append({"type": event_type, "data": data})

    svc = WardRoomService(
        db_path=str(tmp_path / "ward_room.db"),
        emit_event=capture_event,
    )
    await svc.start()
    yield svc
    await svc.stop()


class TestWardRoomWalMode:
    """AD-615: Ward Room DB PRAGMA verification."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, ward_room):
        """Ward Room DB should use WAL journal mode after start()."""
        async with ward_room._threads._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row[0] == "wal"

    @pytest.mark.asyncio
    async def test_busy_timeout_set(self, ward_room):
        """Ward Room DB should have busy_timeout=5000 after start()."""
        async with ward_room._threads._db.execute("PRAGMA busy_timeout") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 5000

    @pytest.mark.asyncio
    async def test_synchronous_normal(self, ward_room):
        """Ward Room DB should use synchronous=NORMAL (1) after start()."""
        async with ward_room._threads._db.execute("PRAGMA synchronous") as cursor:
            row = await cursor.fetchone()
        # NORMAL = 1
        assert row[0] == 1


class TestWardRoomWalModeFallback:
    """AD-615: WAL mode degradation logging."""

    def test_wal_failure_logged_as_warning(self):
        """The WAL failure warning path exists in source code."""
        src = open("src/probos/ward_room/service.py", encoding="utf-8").read()
        assert "WAL mode not accepted" in src
        assert "logger.warning" in src


class TestWardRoomPragmaOrdering:
    """AD-615: PRAGMAs must execute before schema creation."""

    def test_pragmas_before_schema_in_source(self):
        """WAL/busy_timeout/synchronous PRAGMAs appear before executescript(_SCHEMA)."""
        lines = open("src/probos/ward_room/service.py", encoding="utf-8").readlines()
        pragma_lines = {}
        schema_line = None
        for i, line in enumerate(lines, 1):
            if "journal_mode=WAL" in line:
                pragma_lines["wal"] = i
            if "busy_timeout=5000" in line:
                pragma_lines["busy"] = i
            if "synchronous=NORMAL" in line:
                pragma_lines["sync"] = i
            if "executescript(_SCHEMA)" in line and schema_line is None:
                schema_line = i

        assert "wal" in pragma_lines, "journal_mode=WAL PRAGMA not found"
        assert "busy" in pragma_lines, "busy_timeout=5000 PRAGMA not found"
        assert "sync" in pragma_lines, "synchronous=NORMAL PRAGMA not found"
        assert schema_line is not None, "executescript(_SCHEMA) not found"

        for name, line_num in pragma_lines.items():
            assert line_num < schema_line, (
                f"PRAGMA {name} (line {line_num}) must appear before "
                f"executescript(_SCHEMA) (line {schema_line})"
            )
