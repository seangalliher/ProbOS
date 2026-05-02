"""AD-466: Tests for Engineering Infrastructure (Backup + StorageBackend ABC)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from probos.config import InfrastructureConfig
from probos.events import EventType
from probos.infrastructure import (
    BackupResult,
    BackupService,
    SQLiteStorageBackend,
    StorageBackend,
)


# ---------------------------------------------------------------------------
# EventTypes & Config
# ---------------------------------------------------------------------------


def test_event_type_backup_complete_exists() -> None:
    assert EventType.BACKUP_COMPLETE.value == "backup_complete"


def test_event_type_backup_failed_exists() -> None:
    assert EventType.BACKUP_FAILED.value == "backup_failed"


def test_infrastructure_config_defaults() -> None:
    cfg = InfrastructureConfig()
    assert cfg.enabled is True
    assert cfg.backup_enabled is True
    assert cfg.backup_subdir == "backups"


# ---------------------------------------------------------------------------
# BackupService
# ---------------------------------------------------------------------------


def _make_sqlite_db(path: Path) -> None:
    """Helper: create a small SQLite database for backup tests."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS t (k TEXT, v TEXT)")
    conn.execute("INSERT INTO t VALUES ('a', '1')")
    conn.commit()
    conn.close()


def test_backup_service_snapshot_creates_timestamped_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_root = tmp_path / "backups"
    data_dir.mkdir()
    backup_root.mkdir()
    _make_sqlite_db(data_dir / "events.db")

    svc = BackupService(data_dir=data_dir, backup_root=backup_root)
    result = svc.snapshot()

    assert result.succeeded is True
    assert "events.db" in result.files_copied
    assert Path(result.snapshot_dir).exists()
    assert (Path(result.snapshot_dir) / "events.db").exists()
    assert result.bytes_copied > 0


def test_backup_service_snapshot_handles_no_db_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_root = tmp_path / "backups"
    data_dir.mkdir()
    backup_root.mkdir()

    svc = BackupService(data_dir=data_dir, backup_root=backup_root)
    result = svc.snapshot()

    assert result.succeeded is True
    assert result.files_copied == []
    assert result.bytes_copied == 0


def test_backup_service_snapshot_emits_complete_event(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_root = tmp_path / "backups"
    data_dir.mkdir()
    backup_root.mkdir()
    _make_sqlite_db(data_dir / "events.db")
    emit = MagicMock()

    svc = BackupService(data_dir=data_dir, backup_root=backup_root, emit_event=emit)
    svc.snapshot()

    assert emit.call_count == 1
    args = emit.call_args.args
    assert args[0] == EventType.BACKUP_COMPLETE
    payload = args[1]
    assert "snapshot_dir" in payload
    assert "files_copied" in payload
    assert "bytes_copied" in payload
    assert "duration_seconds" in payload


def test_backup_service_snapshot_emits_failed_event_on_unwritable_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When mkdir raises OSError (e.g., permission denied), emit BACKUP_FAILED."""
    data_dir = tmp_path / "data"
    backup_root = tmp_path / "backups"
    data_dir.mkdir()
    emit = MagicMock()

    # Patch Path.mkdir to raise OSError (permission denied scenario, cross-platform)
    original_mkdir = Path.mkdir

    def failing_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        if "backups" in str(self):
            raise OSError("permission denied (simulated)")
        return original_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)

    svc = BackupService(data_dir=data_dir, backup_root=backup_root, emit_event=emit)
    result = svc.snapshot()

    assert result.succeeded is False
    assert result.error
    assert emit.call_count == 1
    args = emit.call_args.args
    assert args[0] == EventType.BACKUP_FAILED
    assert "error" in args[1]


def test_backup_service_uses_online_backup_api(tmp_path: Path) -> None:
    """Smoke test that the SQLite online backup path executes without exception."""
    data_dir = tmp_path / "data"
    backup_root = tmp_path / "backups"
    data_dir.mkdir()
    backup_root.mkdir()
    _make_sqlite_db(data_dir / "events.db")

    svc = BackupService(data_dir=data_dir, backup_root=backup_root)
    result = svc.snapshot()

    # Verify we can read the backed-up DB
    backup_db = Path(result.snapshot_dir) / "events.db"
    conn = sqlite3.connect(str(backup_db))
    rows = conn.execute("SELECT k, v FROM t").fetchall()
    conn.close()
    assert rows == [("a", "1")]


def test_backup_service_falls_back_to_file_copy_on_sqlite_error(tmp_path: Path) -> None:
    """A non-SQLite file with a .db extension triggers the shutil.copyfile fallback."""
    data_dir = tmp_path / "data"
    backup_root = tmp_path / "backups"
    data_dir.mkdir()
    backup_root.mkdir()
    # Write a plain text file with .db extension to trigger SQLite error
    fake_db = data_dir / "fake.db"
    fake_db.write_bytes(b"not a sqlite database")

    svc = BackupService(data_dir=data_dir, backup_root=backup_root)
    result = svc.snapshot()

    assert result.succeeded is True
    assert "fake.db" in result.files_copied
    backup_path = Path(result.snapshot_dir) / "fake.db"
    assert backup_path.exists()


# ---------------------------------------------------------------------------
# StorageBackend ABC
# ---------------------------------------------------------------------------


def test_storage_backend_sqlite_returns_factory() -> None:
    backend = SQLiteStorageBackend()
    factory = backend.connection_factory()
    from probos.storage.sqlite_factory import default_factory
    assert factory is default_factory


@pytest.mark.asyncio
async def test_storage_backend_sqlite_connect_passes_through() -> None:
    backend = SQLiteStorageBackend()
    conn = await backend.connect(":memory:")
    try:
        assert conn is not None
    finally:
        # Clean up — DatabaseConnection has close() per protocol
        if hasattr(conn, "close"):
            close_fn = conn.close
            if callable(close_fn):
                result = close_fn()
                if hasattr(result, "__await__"):
                    await result


def test_storage_backend_abc_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        StorageBackend()  # type: ignore[abstract]
