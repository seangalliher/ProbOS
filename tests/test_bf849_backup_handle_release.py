"""BF-849 (#1344): ``_backup_one`` must RELEASE both SQLite handles.

``sqlite3.Connection.__exit__`` binds a TRANSACTION, not the connection's
lifetime -- it commits or rolls back and never calls ``close()``. So
``with sqlite3.connect(...) as conn`` leaks the handle.

The discriminator is a RENAME of the source after the call: renaming a file
fails while a handle is open on Windows. A test that asserts only "the backup
succeeded" cannot see this defect, because the copy does complete -- which is
why it survived from AD-466 until now.

Every test here asserts its own premise first. On a platform that does not lock
open files, a rename succeeds either way, and a passing assertion would prove
nothing about handles at all; those cases fall back to counting live
connections directly so the test still discriminates.
"""

from __future__ import annotations

import gc
import sqlite3
import sys
from pathlib import Path

import pytest

from probos.infrastructure.backup import BackupService


def _make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"r{i}",) for i in range(rows)])
        conn.commit()
    finally:
        conn.close()


def _service(tmp_path: Path) -> BackupService:
    return BackupService(
        data_dir=tmp_path / "data",
        backup_root=tmp_path / "backups",
    )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="only Windows locks an open file against rename; the handle-count "
           "test below covers every platform",
)
def test_backup_one_releases_the_source_handle_so_it_can_be_renamed(tmp_path: Path) -> None:
    """The reported reproduction, with its premise asserted.

    Against the unfixed handler this raises PermissionError [WinError 32]
    'being used by another process'.
    """
    data = tmp_path / "data"
    data.mkdir()
    src = data / "events.db"
    _make_db(src)

    # PREMISE: a rename must work on an untouched file. Without this, a passing
    # test could mean "renames never work here" rather than "the handle closed".
    probe = data / "premise.db"
    _make_db(probe)
    probe.rename(data / "premise_moved.db")
    assert not probe.exists(), "premise failed: rename does not work at all here"

    dest = tmp_path / "copy.db"
    _service(tmp_path)._backup_one(src, dest)

    moved = data / "events_moved.db"
    src.rename(moved)  # raises PermissionError if the handle leaked
    assert moved.exists()
    assert not src.exists()


def test_backup_one_leaves_no_live_connection_on_any_platform(tmp_path: Path) -> None:
    """Platform-independent form: count live sqlite3.Connection objects.

    Windows proves the leak by refusing a rename; elsewhere the handle is real
    but harmless, so it has to be observed directly instead.
    """
    data = tmp_path / "data"
    data.mkdir()
    src = data / "events.db"
    _make_db(src)
    dest = tmp_path / "copy.db"

    gc.collect()
    before = sum(1 for o in gc.get_objects() if isinstance(o, sqlite3.Connection))

    _service(tmp_path)._backup_one(src, dest)

    # No gc.collect() here: collecting is exactly what MASKS the defect, and
    # doing it before the count would make this test pass against the leak.
    after = [o for o in gc.get_objects() if isinstance(o, sqlite3.Connection)]
    still_open = 0
    for conn in after:
        try:
            conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            continue  # already closed
        except sqlite3.Error:
            continue
        still_open += 1

    assert still_open <= before, (
        f"_backup_one left {still_open - before} live sqlite connection(s); "
        f"sqlite3's context manager binds a transaction, not the handle"
    )


def test_the_backup_still_copies_the_data(tmp_path: Path) -> None:
    """Closing the handles must not cost the thing the method exists to do.

    Guards the obvious wrong fix -- closing before ``backup()`` runs.
    """
    data = tmp_path / "data"
    data.mkdir()
    src = data / "events.db"
    _make_db(src, rows=5)
    dest = tmp_path / "copy.db"

    _service(tmp_path)._backup_one(src, dest)

    conn = sqlite3.connect(str(dest))
    try:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 5
    finally:
        conn.close()


def test_the_fallback_path_still_copies_a_non_sqlite_file(tmp_path: Path) -> None:
    """The ``sqlite3.Error`` branch nobody exercises.

    A leak in the fallback would be the same defect in the branch without
    coverage, so the branch gets coverage.
    """
    data = tmp_path / "data"
    data.mkdir()
    src = data / "not_really.db"
    src.write_bytes(b"this is not a sqlite database")
    dest = tmp_path / "copy.db"

    _service(tmp_path)._backup_one(src, dest)

    assert dest.read_bytes() == b"this is not a sqlite database"
    if sys.platform == "win32":
        moved = data / "not_really_moved.db"
        src.rename(moved)
        assert moved.exists()
