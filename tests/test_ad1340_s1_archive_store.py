"""AD-1340 S1 (M1): the episode archive store, ``probos.cognitive.episode_archive``.

Real SQLite on ``tmp_path``. A second, raw ``sqlite3`` connection is the independent witness for what is
committed and for which bytes are physically left in the file. Every test states its premise first, so a
pass cannot be vacuous.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import secrets
import sqlite3
import typing
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.episode_archive as episode_archive
import probos.cognitive.eviction_audit as eviction_audit
import probos.types as probos_types
from probos.cognitive.episode_archive import (
    ARCHIVE_REASONS,
    ArchiveRecord,
    EpisodeArchive,
    EpisodeArchiveIntegrityError,
    EpisodeArchiveUnavailable,
    decode_payload,
    encode_payload,
    primary_agent_id,
    resolve_disposition,
)
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.types import EvictionDisposition

ARCHIVE_LOGGER = "probos.cognitive.episode_archive"
NOT_OPEN = r"^episode_archive_not_open$"
UNDECODABLE = r"^episode_archive_payload_undecodable$"


# --- helpers -------------------------------------------------------------------------------------------------


def _record(i: int, **meta: Any) -> ArchiveRecord:
    metadata: dict[str, Any] = {
        "content_hash": f"{i:064x}",
        "agent_ids_json": '["agent-a"]',
        "timestamp": 1_700_000_000.0 + i,
    }
    metadata.update(meta)
    return ArchiveRecord(episode_id=f"ep-{i:03d}", document=f"document {i}", metadata=metadata)


def _rows(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Read through a connection of our own: what another process would see on disk."""
    with contextlib.closing(sqlite3.connect(path, timeout=5)) as connection:
        return connection.execute(sql, params).fetchall()


def _write(path: Path, sql: str, params: tuple[Any, ...] = ()) -> None:
    with contextlib.closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.execute(sql, params)
        connection.commit()


def _count(path: Path, table: str, episode_id: str | None = None) -> int:
    if episode_id is None:
        return _rows(path, f"SELECT count(*) FROM {table}")[0][0]
    return _rows(path, f"SELECT count(*) FROM {table} WHERE episode_id = ?", (episode_id,))[0][0]


@contextlib.asynccontextmanager
async def _started(archive: EpisodeArchive) -> AsyncIterator[EpisodeArchive]:
    await archive.start()
    try:
        yield archive
    finally:
        await archive.stop()


class _FakeCursor:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    async def fetchone(self) -> tuple[Any, ...]:
        return self._row

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return [self._row]


class _FaultyConnection:
    """Delegates to a real connection, records every SQL string it is given, and can fail the write."""

    def __init__(self, inner: Any, owner: _FaultyFactory) -> None:
        self._inner = inner
        self._owner = owner

    async def execute(self, sql: str, parameters: Any = None) -> Any:
        self._owner.sql.append(sql)
        if self._owner.secure_delete_answer is not None and sql == "PRAGMA secure_delete":
            return _FakeCursor((self._owner.secure_delete_answer,))
        return await self._inner.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Any) -> Any:
        self._owner.sql.append(sql)
        if self._owner.armed:
            raise sqlite3.OperationalError("injected: disk I/O error")
        return await self._inner.executemany(sql, parameters)

    async def executescript(self, script: str) -> Any:
        self._owner.sql.append(script)
        return await self._inner.executescript(script)

    async def commit(self) -> None:
        await self._inner.commit()

    async def close(self) -> None:
        self._owner.closed += 1
        await self._inner.close()


class _FaultyFactory:
    """Wraps ``SQLiteConnectionFactory``: records SQL, fails ``executemany`` when armed, can misreport secure_delete."""

    def __init__(self, *, secure_delete_answer: int | None = None) -> None:
        self._real = SQLiteConnectionFactory()
        self.armed = False
        self.secure_delete_answer = secure_delete_answer
        self.sql: list[str] = []
        self.connections = 0
        self.closed = 0

    async def connect(self, db_path: str) -> _FaultyConnection:
        self.connections += 1
        return _FaultyConnection(await self._real.connect(db_path), self)


# --- A1 ------------------------------------------------------------------------------------------------------

_KNOWN = ("activation_decay", "activation_decay_aggressive", "capacity", "activation_pruning")
_UNKNOWN = ("user_request", "qualification_test_cleanup", "forget this", "")
_ERASE_REASONS = ("activation_decay", "capacity", "user_request", "", "Captain: forget it")
_MODES = {"archive": "archived", "delete": "deleted"}
_ERASE = EvictionDisposition.ERASE
_ARCHIVE = EvictionDisposition.ARCHIVE


def _slug(reason: str) -> str:
    return re.sub(r"\W+", "_", reason).strip("_") or "empty"


_A1_CASES = [
    *(
        pytest.param(reason, None, mode, _MODES[mode], False, id=f"known-{reason}-{mode}")
        for reason in _KNOWN for mode in _MODES
    ),
    *(
        pytest.param("capacity", _ARCHIVE, mode, _MODES[mode], False, id=f"explicit-archive-known-{mode}")
        for mode in _MODES
    ),
    *(
        pytest.param(reason, _ERASE, mode, "erased", False, id=f"erase-{_slug(reason)}-{mode}")
        for reason in _ERASE_REASONS for mode in _MODES
    ),
    *(
        pytest.param(reason, None, mode, _MODES[mode], True, id=f"unknown-{_slug(reason)}-{mode}")
        for reason in _UNKNOWN for mode in _MODES
    ),
    *(
        pytest.param("forget this", _ARCHIVE, mode, _MODES[mode], True, id=f"explicit-archive-unknown-{mode}")
        for mode in _MODES
    ),
    pytest.param(
        "capacity", "erase", "archive", (TypeError, "eviction_disposition_invalid"), False, id="plain-string-erase",
    ),
    pytest.param(
        "capacity", None, "purge", (ValueError, "eviction_disposition_mode_invalid"), False, id="mode-purge",
    ),
]


@pytest.mark.parametrize(("reason", "explicit", "mode", "outcome", "warns"), _A1_CASES)
def test_resolve_disposition_table(
    caplog: pytest.LogCaptureFixture, reason: str, explicit: Any, mode: str, outcome: Any, warns: bool,
) -> None:
    # Premise: the table's "warns" flag agrees with the module's closed set of reasons, so a stale table
    # (or an edited set) fails here instead of passing the log assertions vacuously.
    assert (reason in ARCHIVE_REASONS) == (reason in _KNOWN), reason
    if explicit is not _ERASE:
        assert warns == (reason not in ARCHIVE_REASONS), reason

    if isinstance(outcome, tuple):
        exception, message = outcome
        if type(explicit) is str:
            # Premise: a plain string that EQUALS a member's value is still not the member.
            assert EvictionDisposition(explicit) is _ERASE
            assert explicit == _ERASE and explicit is not _ERASE
        with pytest.raises(exception, match=f"^{message}$"):
            resolve_disposition(reason, explicit, mode)
        return

    with caplog.at_level(logging.DEBUG, logger=ARCHIVE_LOGGER):
        result = resolve_disposition(reason, explicit, mode)
    warnings = [
        record for record in caplog.records
        if record.name == ARCHIVE_LOGGER and record.levelno == logging.WARNING
    ]

    assert result == outcome
    assert result in eviction_audit.DISPOSITIONS
    if warns:
        assert len(warnings) == 1
        assert repr(reason) in warnings[0].getMessage()
    else:
        assert warnings == []


# --- A2 ------------------------------------------------------------------------------------------------------


def test_payload_round_trip_and_integrity() -> None:
    metadata: dict[str, Any] = {
        "content_hash": f"{7:064x}",
        "agent_ids_json": '["agent-a"]',
        "timestamp": 1_700_000_123.456789,
        "importance": 5,
        "ratio": 0.1,
        "tiny": 1e-300,
        "pinned": True,
        "unpinned": False,
        "note": "",
        "label": "na\u00efve caf\u00e9 \u65e5\u672c\u8a9e",
    }
    record = ArchiveRecord("ep-007", "\u00dcn\u00efcode \u2014 \u65e5\u672c\u8a9e \u2713 \U0001f642", metadata)
    # Premise: the metadata holds every type the live store holds, including the cases JSON mangles easily.
    assert {type(value) for value in metadata.values()} == {str, int, float, bool}
    assert metadata["tiny"] != 0.0 and metadata["note"] == "" and metadata["pinned"] is True

    blob = encode_payload(record)
    decoded = decode_payload(record.episode_id, record.content_hash, 1, blob)

    assert isinstance(blob, bytes) and blob
    assert decoded == record
    assert dict(decoded.metadata) == metadata
    for key, value in metadata.items():
        assert type(decoded.metadata[key]) is type(value), key
    assert encode_payload(record) == blob
    # Canonical: the same record built in another key order encodes to the same bytes.
    reordered = ArchiveRecord(record.episode_id, record.document, dict(reversed(list(metadata.items()))))
    assert list(reordered.metadata) != list(metadata)
    assert encode_payload(reordered) == blob

    # A payload that decodes fine under its own key is rejected under another id or another hash.
    other_blob = encode_payload(ArchiveRecord("ep-other", record.document, metadata))
    assert decode_payload("ep-other", record.content_hash, 1, other_blob).episode_id == "ep-other"
    with pytest.raises(EpisodeArchiveIntegrityError, match=r"^episode_archive_payload_key_mismatch$"):
        decode_payload(record.episode_id, record.content_hash, 1, other_blob)
    with pytest.raises(EpisodeArchiveIntegrityError, match=r"^episode_archive_payload_key_mismatch$"):
        decode_payload(record.episode_id, f"{8:064x}", 1, blob)

    with pytest.raises(EpisodeArchiveIntegrityError, match=r"^episode_archive_payload_format_unknown$"):
        decode_payload(record.episode_id, record.content_hash, 2, blob)

    garbage = b"\x00not zlib\xff"
    with pytest.raises(zlib.error):  # premise: the bytes really are not a zlib stream
        zlib.decompress(garbage)
    with pytest.raises(EpisodeArchiveIntegrityError, match=UNDECODABLE):
        decode_payload(record.episode_id, record.content_hash, 1, garbage)
    with pytest.raises(EpisodeArchiveIntegrityError, match=UNDECODABLE):
        decode_payload(record.episode_id, record.content_hash, 1, zlib.compress(b"not json"))

    wrong_shape = zlib.compress(json.dumps({"id": record.episode_id, "document": "x"}).encode("utf-8"))
    with pytest.raises(EpisodeArchiveIntegrityError, match=r"^episode_archive_payload_shape$"):
        decode_payload(record.episode_id, record.content_hash, 1, wrong_shape)


# --- A3 ------------------------------------------------------------------------------------------------------


async def test_start_enables_and_verifies_secure_delete(tmp_path: Path) -> None:
    # Premise: this SQLite build honours the pragma, so the refusal below is the archive's doing.
    with contextlib.closing(sqlite3.connect(":memory:")) as probe:
        probe.execute("PRAGMA secure_delete=ON")
        assert probe.execute("PRAGMA secure_delete").fetchone() == (1,), sqlite3.sqlite_version

    factory = _FaultyFactory()
    archive = EpisodeArchive(str(tmp_path / "episode_archive.db"), factory)
    async with _started(archive):
        assert archive.is_open
        schema_at = next(index for index, sql in enumerate(factory.sql) if sql.startswith("CREATE TABLE"))
        # Enable first, verify next, and only then create the schema.
        assert factory.sql[0] == "PRAGMA secure_delete=ON"
        assert 0 < factory.sql.index("PRAGMA secure_delete") < schema_at

    refusing = _FaultyFactory(secure_delete_answer=0)
    refused = EpisodeArchive(str(tmp_path / "refused.db"), refusing)
    with pytest.raises(EpisodeArchiveUnavailable, match=r"^episode_archive_secure_delete_unavailable$"):
        await refused.start()
    assert refusing.sql[0] == "PRAGMA secure_delete=ON"  # it did ask for the pragma; the answer was refused
    assert refused.is_open is False
    assert (refusing.connections, refusing.closed) == (1, 1)
    assert not any(sql.startswith("CREATE TABLE") for sql in refusing.sql)  # fail closed: no schema on a refused db


# --- A4 ------------------------------------------------------------------------------------------------------


async def test_archive_commits_and_is_idempotent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "episode_archive.db"
    r1, r2 = _record(1), _record(2)
    columns = "episode_id, content_hash, agent_id, episode_timestamp, reason, payload_format, archived_at"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert _count(path, "episode_archive") == 0  # premise: the witness sees the schema, and it is empty
        assert await archive.archive([], reason="capacity") == frozenset()

        assert await archive.archive([r1, r2], reason="activation_decay") == frozenset(
            {r1.episode_id, r2.episode_id}
        )
        # The archive connection is still open and a second connection already sees both rows: committed.
        assert archive.is_open
        assert _count(path, "episode_archive") == 2
        before = _rows(path, f"SELECT {columns} FROM episode_archive ORDER BY episode_id")
        assert [row[:6] for row in before] == [
            (r.episode_id, r.content_hash, "agent-a", r.metadata["timestamp"], "activation_decay", 1)
            for r in (r1, r2)
        ]

        assert await archive.archive([r1], reason="capacity") == frozenset({r1.episode_id})
        # Nothing was replaced or duplicated: same rows, same reason, same archived_at.
        assert _rows(path, f"SELECT {columns} FROM episode_archive ORDER BY episode_id") == before

        # No usable agent or timestamp: the row still archives, under the audit's fallbacks.
        odd = _record(3, agent_ids_json="not json", timestamp="soon")
        assert await archive.archive([odd], reason="capacity") == frozenset({odd.episode_id})
        assert _rows(
            path, "SELECT agent_id, episode_timestamp FROM episode_archive WHERE episode_id = ?", (odd.episode_id,),
        ) == [("unknown", 0.0)]

        # A record that cannot be encoded is skipped, warned about, and NOT reported as archived.
        bad_type = _record(4, handle=object())
        bad_text = ArchiveRecord("ep-005", "lone surrogate \ud800", {"content_hash": f"{5:064x}"})
        good = _record(6)
        with pytest.raises(TypeError):
            encode_payload(bad_type)
        with pytest.raises(ValueError):
            encode_payload(bad_text)
        with caplog.at_level(logging.WARNING, logger=ARCHIVE_LOGGER):
            archived = await archive.archive([bad_type, bad_text, good], reason="capacity")
        assert archived == frozenset({good.episode_id})
        warned = " ".join(record.getMessage() for record in caplog.records if record.name == ARCHIVE_LOGGER)
        assert bad_type.episode_id in warned and bad_text.episode_id in warned
        assert _count(path, "episode_archive", bad_type.episode_id) == 0
        assert _count(path, "episode_archive", bad_text.episode_id) == 0
        assert _count(path, "episode_archive", good.episode_id) == 1

    assert primary_agent_id({"agent_ids_json": '["agent-b", "agent-c"]'}) == "agent-b"
    unusable = ({}, {"agent_ids_json": "[]"}, {"agent_ids_json": "{}"}, {"agent_ids_json": '{"k": 1}'},
                {"agent_ids_json": "not json"}, {"agent_ids_json": None})
    for metadata in unusable:
        assert primary_agent_id(metadata) == "unknown", metadata


# --- A5 ------------------------------------------------------------------------------------------------------


async def test_failed_write_commits_nothing(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    factory = _FaultyFactory()
    archive = EpisodeArchive(str(path), factory)
    record = _record(1)
    async with _started(archive):
        assert _count(path, "episode_archive") == 0  # premise: the schema exists, so a 0 below is a real count

        factory.armed = True
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            await archive.archive([record], reason="capacity")
        # Premise: the failure was injected at the write itself, and the archive rolled back.
        assert any(sql.startswith("INSERT INTO episode_archive") for sql in factory.sql)
        assert "ROLLBACK" in factory.sql
        assert archive.is_open
        assert _count(path, "episode_archive") == 0

        factory.armed = False
        assert await archive.archive([record], reason="capacity") == frozenset({record.episode_id})
        assert _count(path, "episode_archive") == 1


# --- A6 ------------------------------------------------------------------------------------------------------


async def test_erase_overwrites_the_bytes(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    secret = ArchiveRecord(
        "ep-secret", secrets.token_hex(2048),
        {"content_hash": f"{1:064x}", "agent_ids_json": '["agent-a"]', "timestamp": 1.0},
    )
    keep = _record(2)
    blob = encode_payload(secret)
    assert len(blob) > 2048  # incompressible, so the stored bytes are distinctive

    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([secret, keep], reason="activation_decay") == frozenset(
            {secret.episode_id, keep.episode_id}
        )
        await archive.record_access(secret.episode_id, accessor="test", purpose="premise")
        await archive.record_access(keep.episode_id, accessor="test", purpose="survivor")
    # Premise: before the erase the record's exact stored bytes are in the file, and so is its access row.
    assert blob in path.read_bytes()
    assert _count(path, "episode_archive", secret.episode_id) == 1
    assert _count(path, "archive_access", secret.episode_id) == 1

    async with _started(archive):
        assert await archive.erase([secret.episode_id]) == frozenset({secret.episode_id})
        assert await archive.erase([secret.episode_id]) == frozenset()
        assert await archive.erase(["ep-never-archived"]) == frozenset()
    assert path.stat().st_size > 0
    assert blob not in path.read_bytes()
    assert _count(path, "episode_archive", secret.episode_id) == 0
    assert _count(path, "archive_access", secret.episode_id) == 0
    # The erase named one id: the other record and its access row are untouched.
    assert _count(path, "episode_archive", keep.episode_id) == 1
    assert _count(path, "archive_access", keep.episode_id) == 1


# --- A7 ------------------------------------------------------------------------------------------------------


async def test_unknown_schema_version_is_refused_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    _write(path, "PRAGMA user_version = 2")
    # Premise: a real database file now exists and carries the version the archive does not know.
    assert path.stat().st_size > 0
    assert _rows(path, "PRAGMA user_version") == [(2,)]
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    archive = EpisodeArchive(str(path))
    with pytest.raises(EpisodeArchiveUnavailable, match=r"^episode_archive_schema_unknown$"):
        await archive.start()

    assert archive.is_open is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["episode_archive.db"]  # no journal left behind


# --- A8 ------------------------------------------------------------------------------------------------------


async def test_reads(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    # Two versions each of ep-001 and ep-002. In key order the newer ep-001 row comes first and the newer
    # ep-002 row comes last, so neither "first row wins" nor "last row wins" can pass for both ids.
    old_1 = _record(1, content_hash="f" * 64, version="old")
    new_1 = _record(1, content_hash="0" * 63 + "1", version="new")
    old_2 = _record(2, content_hash="0" * 64, version="old")
    new_2 = _record(2, content_hash="f" * 64, version="new")
    other = _record(3)

    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([old_1, new_1, old_2, new_2, other], reason="capacity") == frozenset(
            {"ep-001", "ep-002", "ep-003"}
        )
        for record, archived_at in ((old_1, 1000.0), (new_1, 2000.0), (old_2, 1000.0), (new_2, 2000.0)):
            _write(
                path,
                "UPDATE episode_archive SET archived_at = ? WHERE episode_id = ? AND content_hash = ?",
                (archived_at, record.episode_id, record.content_hash),
            )
        # Premise: four versioned rows, the newest first in key order for ep-001 and last for ep-002.
        assert _rows(
            path,
            "SELECT episode_id, archived_at FROM episode_archive WHERE episode_id IN ('ep-001', 'ep-002') "
            "ORDER BY episode_id, content_hash",
        ) == [("ep-001", 2000.0), ("ep-001", 1000.0), ("ep-002", 1000.0), ("ep-002", 2000.0)]

        # Latest archived_at per id, in input order, a repeated id folded, absent and empty ids skipped.
        assert await archive.get_records(["ep-002", "ep-absent", "ep-001", "ep-002", ""]) == [new_2, new_1]
        assert await archive.get_records(["ep-absent"]) == []
        assert await archive.get_records([]) == []

        assert await archive.archived_keys(["ep-003"]) == [
            ("ep-003", other.content_hash, "agent-a", other.metadata["timestamp"]),
        ]
        assert await archive.archived_keys(["ep-absent", ""]) == []
        assert await archive.archived_keys([]) == []

        # A corrupt payload, planted raw: the key columns still read, the decode refuses.
        bad_hash = f"{99:064x}"
        corrupt = b"\x00corrupt\xff"
        _write(
            path,
            "INSERT INTO episode_archive (episode_id, content_hash, agent_id, episode_timestamp, reason, "
            "archived_at, payload_format, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ep-bad", bad_hash, "agent-z", 123.5, "capacity", 1.0, 1, corrupt),
        )
        with pytest.raises(EpisodeArchiveIntegrityError, match=UNDECODABLE):  # premise: it really is corrupt
            decode_payload("ep-bad", bad_hash, 1, corrupt)
        assert await archive.archived_keys(["ep-bad"]) == [("ep-bad", bad_hash, "agent-z", 123.5)]
        with pytest.raises(EpisodeArchiveIntegrityError, match=UNDECODABLE):
            await archive.get_records(["ep-bad"])

    # Seven rows inserted out of key order; two share an id and straddle the first page boundary.
    paged_path = tmp_path / "paged.db"
    paged = [
        _record(3, content_hash="b" * 64), _record(3, content_hash="a" * 64),
        _record(6), _record(1), _record(5), _record(2), _record(4),
    ]
    in_key_order = sorted(paged, key=lambda record: (record.episode_id, record.content_hash))
    assert paged != in_key_order
    factory = _FaultyFactory()
    paged_archive = EpisodeArchive(str(paged_path), factory)
    async with _started(paged_archive):
        assert len(await paged_archive.archive(paged, reason="capacity")) == 6
        assert _count(paged_path, "episode_archive") == 7  # premise: seven rows, so page_size=3 needs three pages
        yielded = [record async for record in paged_archive.iter_records(page_size=3)]
        assert yielded == in_key_order
        assert sum("LIMIT ?" in sql for sql in factory.sql) >= 3  # it really paged
        for bad_size in (0, -1):
            with pytest.raises(ValueError, match=r"^episode_archive_page_size_invalid$"):
                async for _ in paged_archive.iter_records(page_size=bad_size):
                    pass


# --- A9 ------------------------------------------------------------------------------------------------------


async def test_unstarted_or_stopped_raises_unavailable(tmp_path: Path) -> None:
    factory = _FaultyFactory()
    archive = EpisodeArchive(str(tmp_path / "episode_archive.db"), factory)
    record = _record(1)

    async def drain() -> list[ArchiveRecord]:
        return [row async for row in archive.iter_records()]

    # In the order they can run while open: the last one erases what the first one archived.
    calls: dict[str, Callable[[], Awaitable[Any]]] = {
        "archive": lambda: archive.archive([record], reason="capacity"),
        "get_records": lambda: archive.get_records([record.episode_id]),
        "archived_keys": lambda: archive.archived_keys([record.episode_id]),
        "iter_records": drain,
        "record_access": lambda: archive.record_access(record.episode_id, accessor="test", purpose="probe"),
        "erase": lambda: archive.erase([record.episode_id]),
    }
    while_open: dict[str, Any] = {
        "archive": frozenset({record.episode_id}),
        "get_records": [record],
        "archived_keys": [(record.episode_id, record.content_hash, "agent-a", record.metadata["timestamp"])],
        "iter_records": [record],
        "record_access": None,
        "erase": frozenset({record.episode_id}),
    }
    assert calls.keys() == while_open.keys()

    async def assert_all_unavailable() -> None:
        assert archive.is_open is False
        for call in calls.values():
            with pytest.raises(EpisodeArchiveUnavailable, match=NOT_OPEN):
                await call()

    await assert_all_unavailable()  # before start()
    await archive.stop()  # stopping what never started is a no-op
    assert factory.connections == 0

    try:
        await archive.start()
        await archive.start()  # idempotent: no second connection
        assert archive.is_open and factory.connections == 1
        for name, call in calls.items():  # premise: every method works while open, so the raises are not vacuous
            assert await call() == while_open[name], name
    finally:
        await archive.stop()
    await archive.stop()
    assert factory.closed == 1

    await assert_all_unavailable()  # after stop()

    for unusable_path in ("", "   ", None):
        with pytest.raises(ValueError, match=r"^episode_archive_path_invalid$"):
            EpisodeArchive(unusable_path)  # type: ignore[arg-type]


# --- A10 -----------------------------------------------------------------------------------------------------


def test_eviction_disposition_lives_in_the_foundation_tier() -> None:
    # Premise: the enum is defined in the foundation tier, with exactly the two members the policy names.
    assert probos_types.EvictionDisposition.__module__ == "probos.types"
    assert {member.name: member.value for member in probos_types.EvictionDisposition} == {
        "ARCHIVE": "archive", "ERASE": "erase",
    }

    assert episode_archive.EvictionDisposition is probos_types.EvictionDisposition
    assert "EvictionDisposition" in episode_archive.__all__
    assert all(hasattr(episode_archive, name) for name in episode_archive.__all__)

    assert isinstance(eviction_audit.DISPOSITIONS, frozenset)
    assert eviction_audit.DISPOSITIONS == {"archived", "erased", "deleted"}
    assert (
        eviction_audit.DISPOSITION_ARCHIVED, eviction_audit.DISPOSITION_ERASED, eviction_audit.DISPOSITION_DELETED,
    ) == ("archived", "erased", "deleted")
    assert set(typing.get_args(episode_archive.AuditDisposition)) == set(eviction_audit.DISPOSITIONS)


# --- A11 -----------------------------------------------------------------------------------------------------


async def test_rearchive_with_changed_metadata_replaces_the_payload(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    r1 = _record(1)
    r1_changed = _record(1, valid_until=1234567890.0)  # same (episode_id, content_hash), new metadata
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([r1], reason="activation_decay") == frozenset({r1.episode_id})
        # premise: one row, holding the first payload
        assert _count(path, "episode_archive") == 1
        assert (await archive.get_records([r1.episode_id]))[0].metadata == r1.metadata
        assert r1_changed.metadata != r1.metadata
        assert (r1_changed.episode_id, r1_changed.content_hash) == (r1.episode_id, r1.content_hash)

        assert await archive.archive([r1_changed], reason="activation_decay") == frozenset({r1.episode_id})

        assert _count(path, "episode_archive") == 1
        (record,) = await archive.get_records([r1.episode_id])
        assert record.metadata == r1_changed.metadata


# --- A12 -----------------------------------------------------------------------------------------------------


async def test_archive_returns_only_ids_whose_stored_payload_matches(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    r1 = _record(1)
    r1_changed = _record(1, valid_until=1234567890.0)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([r1], reason="activation_decay") == frozenset({r1.episode_id})
        # A second connection makes every UPDATE of the table a silent no-op: the write "succeeds" and changes nothing.
        _write(path, "CREATE TRIGGER ignore_updates BEFORE UPDATE ON episode_archive BEGIN SELECT RAISE(IGNORE); END")

        # The key is present, but with the OLD payload: the read-back must not report the id as archived.
        assert await archive.archive([r1_changed], reason="activation_decay") == frozenset()

        assert _rows(path, "SELECT payload FROM episode_archive WHERE episode_id = ?", (r1.episode_id,)) == [
            (encode_payload(r1),)
        ]


# --- A13 -----------------------------------------------------------------------------------------------------


async def test_rearchive_of_an_identical_record_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    r1 = _record(1)
    columns = "reason, archived_at, payload"
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([r1], reason="activation_decay") == frozenset({r1.episode_id})
        before = _rows(path, f"SELECT {columns} FROM episode_archive")
        assert [row[0] for row in before] == ["activation_decay"]  # premise: the first reason is what a no-op keeps

        assert await archive.archive([r1], reason="capacity") == frozenset({r1.episode_id})

        assert _rows(path, f"SELECT {columns} FROM episode_archive") == before  # reason and archived_at unchanged


# --- A14 -----------------------------------------------------------------------------------------------------


async def test_iter_records_continues_past_an_undecodable_row_then_raises(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    records = [_record(1), _record(2), _record(3)]
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive(records, reason="capacity") == frozenset(r.episode_id for r in records)
        _write(path, "UPDATE episode_archive SET payload = ? WHERE episode_id = ?", (b"not zlib", records[1].episode_id))

        for page_size in (1, 500):  # one row per page, and everything in one page
            seen: list[str] = []

            with pytest.raises(EpisodeArchiveIntegrityError, match=r"^episode_archive_rows_undecodable:1$"):
                async for record in archive.iter_records(page_size=page_size):
                    seen.append(record.episode_id)

            # The corrupt middle row did not hide the row after it, and the failure is raised only once the scan is done.
            assert seen == [records[0].episode_id, records[2].episode_id], page_size


# --- A15 -----------------------------------------------------------------------------------------------------


async def test_get_versions_returns_every_row_for_the_id(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    r1 = _record(1)
    r1_other = _record(1, content_hash=f"{99:064x}", variant="second")  # a second version of the same episode id
    other_id = _record(2)
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([r1, r1_other, other_id], reason="capacity") == frozenset(
            {r1.episode_id, other_id.episode_id}
        )
        assert _count(path, "episode_archive", r1.episode_id) == 2  # premise: two rows for the id
        # The later hash is archived EARLIER, so ``archived_at`` (not the key) must decide the order.
        _write(path, "UPDATE episode_archive SET archived_at = 2000 WHERE content_hash = ?", (r1.content_hash,))
        _write(path, "UPDATE episode_archive SET archived_at = 1000 WHERE content_hash = ?", (r1_other.content_hash,))

        versions = await archive.get_versions([r1.episode_id])

        assert [record.metadata for record in versions] == [r1_other.metadata, r1.metadata]
        assert all(record.episode_id == r1.episode_id for record in versions)  # the other id is not returned
        assert await archive.get_versions([]) == []
        assert await archive.get_versions(["ep-unknown"]) == []
