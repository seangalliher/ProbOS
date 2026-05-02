"""AD-466: BackupService -- timestamped SQLite snapshots under data_dir."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupResult:
    """Result of a backup snapshot."""

    succeeded: bool
    snapshot_dir: str
    files_copied: list[str] = field(default_factory=list)
    bytes_copied: int = 0
    duration_seconds: float = 0.0
    error: str = ""


class BackupService:
    """Periodic snapshot of SQLite databases under runtime.data_dir.

    Stateless on construction. Each `snapshot()` call writes a timestamped
    subdirectory under `backup_root` and copies every `*.db` file from
    `data_dir` using SQLite's online `.backup` API (which works while the
    source database is being read/written).

    Caller is responsible for scheduling. v1 does not run a background task.
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        backup_root: Path,
        emit_event: Any | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._backup_root = backup_root
        self._emit_event = emit_event

    def snapshot(self) -> BackupResult:
        """Take one timestamped snapshot. Returns BackupResult regardless of outcome."""
        started = time.time()
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started))
        snapshot_dir = self._backup_root / timestamp
        try:
            snapshot_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            snapshot_dir = self._backup_root / f"{timestamp}-{int((started % 1) * 1_000_000):06d}"
            snapshot_dir.mkdir(parents=True, exist_ok=False)
        except Exception as exc:
            return self._fail(str(snapshot_dir), started, f"mkdir failed: {exc}")

        files_copied: list[str] = []
        bytes_copied = 0
        try:
            db_files = sorted(self._data_dir.glob("*.db"))
            for src in db_files:
                dest = snapshot_dir / src.name
                self._backup_one(src, dest)
                files_copied.append(src.name)
                try:
                    bytes_copied += dest.stat().st_size
                except OSError:
                    pass
            result = BackupResult(
                succeeded=True,
                snapshot_dir=str(snapshot_dir),
                files_copied=files_copied,
                bytes_copied=bytes_copied,
                duration_seconds=time.time() - started,
            )
            self._emit_complete(result)
            return result
        except Exception as exc:
            logger.error(
                "AD-466: backup snapshot failed (snapshot_dir=%s, files_copied=%d): %s",
                snapshot_dir, len(files_copied), exc,
            )
            return self._fail(str(snapshot_dir), started, str(exc))

    def _backup_one(self, src: Path, dest: Path) -> None:
        """SQLite online backup -- safe while source is being written."""
        try:
            with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dest)) as dest_conn:
                src_conn.backup(dest_conn)
        except sqlite3.Error:
            shutil.copyfile(src, dest)

    def _fail(self, snapshot_dir: str, started: float, error: str) -> BackupResult:
        result = BackupResult(
            succeeded=False,
            snapshot_dir=snapshot_dir,
            duration_seconds=time.time() - started,
            error=error,
        )
        self._emit_failed(result)
        return result

    def _emit_complete(self, result: BackupResult) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.BACKUP_COMPLETE,
                {
                    "snapshot_dir": result.snapshot_dir,
                    "files_copied": list(result.files_copied),
                    "bytes_copied": result.bytes_copied,
                    "duration_seconds": result.duration_seconds,
                },
            )
        except Exception:
            logger.warning(
                "AD-466: BACKUP_COMPLETE emit failed (snapshot_dir=%s)",
                result.snapshot_dir, exc_info=True,
            )

    def _emit_failed(self, result: BackupResult) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.BACKUP_FAILED,
                {
                    "snapshot_dir": result.snapshot_dir,
                    "error": result.error,
                    "duration_seconds": result.duration_seconds,
                },
            )
        except Exception:
            logger.warning(
                "AD-466: BACKUP_FAILED emit failed (snapshot_dir=%s)",
                result.snapshot_dir, exc_info=True,
            )
