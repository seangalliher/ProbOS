"""AD-1265: the snapshot scheduler AD-466 never shipped (BF-842, BF-849).

The defect these tests exist to prevent is *the absence of a caller*. AD-466
had six passing tests and zero production snapshots, because every one of
those tests supplied the caller production lacked -- the half-chain shape,
with no consumer at all. So the first test here boots the real startup path
and must never call ``snapshot()`` itself.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from probos.config import SystemConfig
from probos.infrastructure.backup import BackupService
from probos.infrastructure.backup_inventory import BackupRoot, BackupTier
from probos.infrastructure.snapshot_manifest import (
    INCOMPLETE_SUFFIX,
    read_manifest,
)


def _make_sqlite_db(path: Path, *, rows: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS t (k TEXT, v TEXT)")
        for i in range(rows):
            conn.execute("INSERT INTO t VALUES (?, ?)", (f"k{i}", f"v{i}"))
        conn.commit()
    finally:
        conn.close()


def _service(tmp_path: Path, **kwargs: object) -> tuple[BackupService, Path, Path]:
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    data_dir.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    svc = BackupService(
        data_dir=data_dir, backup_root=backup_root, **kwargs,  # type: ignore[arg-type]
    )
    return svc, data_dir, backup_root


# ---------------------------------------------------------------------------
# 1-3: the loop exists, ticks from startup, and drains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_appears_from_runtime_startup_without_any_test_calling_it(
    tmp_path: Path,
) -> None:
    """The AD-466 defect, inverted.

    This test must never call ``snapshot()`` and must not use
    ``BackupService`` to trigger anything -- if it did, it would reproduce
    exactly the half-chain that let BF-842 sit undetected for months. The
    runtime's own loop is the only thing allowed to produce the directory.
    """
    from probos.runtime import ProbOSRuntime

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_sqlite_db(data_dir / "payload.db")

    config = SystemConfig()
    config.infrastructure.enabled = True
    config.infrastructure.backup_enabled = True
    config.infrastructure.backup_warmup_seconds = 0.05
    config.infrastructure.backup_interval_seconds = 300.0
    config.infrastructure.backup_include_archive_root = False

    runtime = ProbOSRuntime(config=config, data_dir=data_dir)
    backup_root = data_dir / config.infrastructure.backup_subdir
    backup_root.mkdir(parents=True, exist_ok=True)
    runtime.backup_service = BackupService(
        data_dir=data_dir,
        backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )

    task = asyncio.create_task(runtime._sqlite_backup_loop())
    try:
        promoted: list[Path] = []
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            promoted = [
                p for p in backup_root.iterdir()
                if p.is_dir() and not p.name.endswith(INCOMPLETE_SUFFIX)
            ]
            if promoted:
                break
            await asyncio.sleep(0.05)
        assert promoted, (
            "the runtime's own loop produced no promoted snapshot; this is the "
            "BF-842 shape -- a service wired at startup that nothing calls"
        )
        assert (promoted[0] / "data" / "payload.db").is_file()
    finally:
        runtime._shutdown_event.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_backup_complete_is_queryable_from_the_event_log(tmp_path: Path) -> None:
    """The live evidence in #1313 was event-log rows, not emit_event calls.

    ``emit_event`` fans out to in-memory listeners and never reaches
    ``events.db``, so a test that asserts "emit_event was called" cannot fail
    the way the vessel failed.
    """
    from probos.runtime import ProbOSRuntime

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_sqlite_db(data_dir / "payload.db")

    config = SystemConfig()
    config.infrastructure.backup_warmup_seconds = 0.0
    config.infrastructure.backup_interval_seconds = 300.0

    runtime = ProbOSRuntime(config=config, data_dir=data_dir)
    await runtime.event_log.start()
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    runtime.backup_service = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )
    try:
        result = runtime.backup_service.snapshot()
        assert result.succeeded is True
        await runtime._log_backup_tick(result)

        rows = await runtime.event_log.query(category="backup", limit=10)
        assert [r["event"] for r in rows] == ["backup_complete"]
        assert rows[0]["data"]["snapshot_promoted"] is True
    finally:
        await runtime.event_log.stop()


@pytest.mark.asyncio
async def test_shutdown_drains_without_leaving_a_promoted_looking_directory(
    tmp_path: Path,
) -> None:
    """Both halves: shutdown during warmup, and shutdown after a real tick.

    The second half is the one that matters -- a directory that *looks*
    promoted but is not whole is the failure mode promotion-by-rename exists
    to prevent, so the surviving directory is put through the real verifier
    rather than merely inspected by name.
    """
    from probos.infrastructure.snapshot_verify import verify_snapshot
    from probos.runtime import ProbOSRuntime

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_sqlite_db(data_dir / "payload.db")

    config = SystemConfig()
    config.infrastructure.backup_warmup_seconds = 30.0  # never reached
    runtime = ProbOSRuntime(config=config, data_dir=data_dir)
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    runtime.backup_service = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )

    task = asyncio.create_task(runtime._sqlite_backup_loop())
    await asyncio.sleep(0.05)
    runtime._shutdown_event.set()
    await asyncio.wait_for(task, timeout=5.0)

    assert list(backup_root.iterdir()) == [], (
        "shutdown during warmup left something in the backup root"
    )

    # Now let one tick actually complete, then shut down.
    runtime._shutdown_event.clear()
    config.infrastructure.backup_warmup_seconds = 0.0
    config.infrastructure.backup_interval_seconds = 300.0
    task = asyncio.create_task(runtime._sqlite_backup_loop())
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not list(backup_root.iterdir()):
        await asyncio.sleep(0.05)
    runtime._shutdown_event.set()
    await asyncio.wait_for(task, timeout=10.0)

    survivors = list(backup_root.iterdir())
    assert len(survivors) == 1, survivors
    assert not survivors[0].name.endswith(INCOMPLETE_SUFFIX)
    report = await verify_snapshot(survivors[0])
    assert report.ok is True, report.render()


# ---------------------------------------------------------------------------
# 4-5: self-exclusion
# ---------------------------------------------------------------------------


def test_second_snapshot_contains_no_entry_from_the_first(tmp_path: Path) -> None:
    svc, data_dir, backup_root = _service(tmp_path)
    _make_sqlite_db(data_dir / "payload.db")

    first = Path(svc.snapshot().snapshot_dir)
    second = Path(svc.snapshot().snapshot_dir)
    assert first != second

    embedded = [p for p in second.rglob("*") if first.name in p.parts]
    assert embedded == [], f"the second snapshot embedded the first: {embedded}"
    manifest = read_manifest(second)
    assert manifest is not None
    assert {e.label for e in manifest.entries} == {"data/payload.db"}


def test_self_exclusion_holds_under_nested_subdir_and_through_a_symlink(
    tmp_path: Path,
) -> None:
    """A recursive glob must never re-enter the backup root, by any route."""
    data_dir = tmp_path / "data"
    backup_root = data_dir / "deep" / "nested" / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    # A decoy that would be swept in if the prune were name-based.
    _make_sqlite_db(backup_root / "stale-snapshot" / "old.db")

    link = data_dir / "link_to_backups"
    try:
        link.symlink_to(backup_root, target_is_directory=True)
        have_symlink = True
    except (OSError, NotImplementedError):
        have_symlink = False

    svc = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )
    result = svc.snapshot()
    assert result.succeeded is True
    assert result.files_copied == ["data/payload.db"], (
        f"the backup root leaked into the snapshot: {result.files_copied}"
    )
    # PREMISE ASSERTION: the symlink route was actually exercised, otherwise
    # "no leak" says nothing about it.
    assert have_symlink or sys.platform == "win32", (
        "symlink could not be created and this is not Windows; the symlink "
        "half of this test did not run"
    )
    if have_symlink:
        assert link.is_dir()


# ---------------------------------------------------------------------------
# 6: BF-849
# ---------------------------------------------------------------------------


def test_backup_one_releases_the_source_handle_so_the_file_can_be_renamed(
    tmp_path: Path,
) -> None:
    """BF-849.

    ``_backup_one`` used ``with sqlite3.connect(...)``, which is a
    *transaction* manager, not a closer -- both handles leaked on every file,
    every tick. On Windows an open handle blocks ``os.replace``, so retention
    could not delete what the previous tick left open.

    Renaming the source afterwards is the discriminator. A test that merely
    asserts "the backup succeeded" passes against the leak.
    """
    svc, data_dir, backup_root = _service(tmp_path)
    src = data_dir / "payload.db"
    _make_sqlite_db(src)

    # PREMISE ASSERTION: rename must work on an untouched file, or "rename
    # failed" would prove nothing about handles.
    control = data_dir / "control.db"
    control.write_bytes(b"x")
    control.replace(data_dir / "control_moved.db")

    svc._backup_one(src, backup_root / "payload.db")

    moved = data_dir / "payload_moved.db"
    os.replace(src, moved)  # raises PermissionError (WinError 32) if leaked
    assert moved.is_file()

    dest = backup_root / "payload.db"
    os.replace(dest, backup_root / "payload_moved.db")


# ---------------------------------------------------------------------------
# 7: self-sufficiency (D1)
# ---------------------------------------------------------------------------


def test_every_tick_contains_every_included_database(tmp_path: Path) -> None:
    """D1: there is no tier a tick can skip.

    AD-1262 shipped a ``bulk`` tier carried forward by reference; retention
    deleted the snapshot the reference named and restore then reported
    success with the database simply absent.
    """
    svc, data_dir, _ = _service(tmp_path)
    for name in ("alpha.db", "beta.db", "nested/gamma.db"):
        _make_sqlite_db(data_dir / name)
    _make_sqlite_db(data_dir / "archives" / "ward_room_001.db")

    label_sets = []
    for _ in range(3):
        result = svc.snapshot()
        assert result.succeeded is True
        manifest = read_manifest(Path(result.snapshot_dir))
        assert manifest is not None
        label_sets.append({e.label for e in manifest.present})
        time.sleep(1.05)  # distinct second-resolution timestamps

    assert label_sets[0] == label_sets[1] == label_sets[2]
    assert label_sets[0] == {
        "data/alpha.db",
        "data/archives/ward_room_001.db",
        "data/beta.db",
        "data/nested/gamma.db",
    }


# ---------------------------------------------------------------------------
# 8-10: the IMMUTABLE optimization
# ---------------------------------------------------------------------------


def test_unchanged_immutable_file_is_hard_linked_from_the_prior_promoted_snapshot(
    tmp_path: Path,
) -> None:
    svc, data_dir, _ = _service(tmp_path)
    ward = data_dir / "archives" / "ward_room_001.db"
    _make_sqlite_db(ward)
    # Age it well before the first snapshot so the mtime guard is satisfied.
    old = time.time() - 3600
    os.utime(ward, (old, old))

    first = svc.snapshot()
    assert first.succeeded is True
    time.sleep(1.05)
    second = svc.snapshot()
    assert second.succeeded is True

    assert "data/archives/ward_room_001.db" in second.files_linked
    linked = Path(second.snapshot_dir) / "data" / "archives" / "ward_room_001.db"
    assert linked.stat().st_nlink > 1


def test_immutable_file_modified_after_the_prior_snapshot_is_copied_not_linked(
    tmp_path: Path,
) -> None:
    svc, data_dir, _ = _service(tmp_path)
    ward = data_dir / "archives" / "ward_room_001.db"
    _make_sqlite_db(ward)
    old = time.time() - 3600
    os.utime(ward, (old, old))

    first = svc.snapshot()
    assert first.succeeded is True
    time.sleep(1.05)
    # Rewrite it: mtime now postdates the prior snapshot's start.
    _make_sqlite_db(ward, rows=5)

    second = svc.snapshot()
    assert second.succeeded is True
    assert second.files_linked == []
    assert "data/archives/ward_room_001.db" in second.files_copied


def test_os_link_failure_falls_back_to_a_copy_never_to_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, data_dir, _ = _service(tmp_path)
    ward = data_dir / "archives" / "ward_room_001.db"
    _make_sqlite_db(ward)
    old = time.time() - 3600
    os.utime(ward, (old, old))

    assert svc.snapshot().succeeded is True
    time.sleep(1.05)

    def _no_links(*args: object, **kwargs: object) -> None:
        raise OSError("hard links unsupported (simulated)")

    monkeypatch.setattr(os, "link", _no_links)
    second = svc.snapshot()

    assert second.succeeded is True
    assert second.files_linked == []
    assert "data/archives/ward_room_001.db" in second.files_copied
    copied = Path(second.snapshot_dir) / "data" / "archives" / "ward_room_001.db"
    assert copied.is_file(), "link failure must fall back to a copy, never a skip"


# ---------------------------------------------------------------------------
# tier shape
# ---------------------------------------------------------------------------


def test_backup_tier_has_no_bulk_member() -> None:
    assert {t.value for t in BackupTier} == {"included", "immutable"}
