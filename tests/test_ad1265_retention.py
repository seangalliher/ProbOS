"""AD-1265: retention, and the valve announcing itself.

AD-1262 shipped ``retain_days=7`` against a ~1.6 GiB/tick footprint and an
8 GiB ceiling, so the byte bound actually bound at roughly two days and the
seven-day knob was decorative. Nothing said so. These tests pin the two
bounds, the never-prune-the-last floor, and the warning that keeps a silent
override from becoming policy again.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import pytest

from probos.infrastructure.backup import BackupService, PruneResult
from probos.infrastructure.backup_inventory import BackupRoot
from probos.infrastructure.snapshot_manifest import INCOMPLETE_SUFFIX


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


def _service(
    tmp_path: Path, *, retain_days: int = 3, max_total_bytes: int = 8 * 1024**3,
) -> tuple[BackupService, Path, Path]:
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    data_dir.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    svc = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
        retain_days=retain_days, max_total_bytes=max_total_bytes,
    )
    return svc, data_dir, backup_root


def _plant(backup_root: Path, name: str, *, size: int = 1024) -> Path:
    """A promoted-looking snapshot directory with `size` bytes in it."""
    path = backup_root / name
    path.mkdir(parents=True)
    (path / "payload.bin").write_bytes(b"\x00" * size)
    return path


# ---------------------------------------------------------------------------
# 19-21: the two bounds and the floor
# ---------------------------------------------------------------------------


def test_retain_days_prunes_by_age(tmp_path: Path) -> None:
    svc, _, backup_root = _service(tmp_path, retain_days=3)
    old = _plant(backup_root, "20200101-000000")
    recent = _plant(backup_root, time.strftime("%Y%m%d-%H%M%S", time.gmtime()))

    result = svc.prune()

    assert result.pruned_dirs == [str(old)]
    assert result.bound == "days"
    assert not old.exists()
    assert recent.exists()


def test_max_total_bytes_prunes_oldest_first(tmp_path: Path) -> None:
    now = time.time()
    svc, _, backup_root = _service(tmp_path, retain_days=3650, max_total_bytes=2500)
    names = [
        time.strftime("%Y%m%d-%H%M%S", time.gmtime(now - 300)),
        time.strftime("%Y%m%d-%H%M%S", time.gmtime(now - 200)),
        time.strftime("%Y%m%d-%H%M%S", time.gmtime(now - 100)),
    ]
    planted = [_plant(backup_root, name, size=1000) for name in names]

    result = svc.prune()

    assert result.pruned_dirs == [str(planted[0])]
    assert result.bound == "bytes"
    assert not planted[0].exists()
    assert planted[1].exists() and planted[2].exists()


def test_the_newest_promoted_snapshot_is_never_pruned_even_alone_over_the_ceiling(
    tmp_path: Path,
) -> None:
    """A retention policy that can prune itself to zero is worse than none.

    It still reads as protection.
    """
    now = time.time()
    svc, _, backup_root = _service(tmp_path, retain_days=1, max_total_bytes=64 * 1024**2)
    old = _plant(backup_root, "20200101-000000", size=4096)
    newest = _plant(
        backup_root, time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)), size=4096,
    )

    # Both are over-age against retain_days=1 and the pair is over the ceiling.
    svc._max_total_bytes = 1
    result = svc.prune()

    assert not old.exists()
    assert newest.exists(), "retention pruned the only remaining snapshot"
    assert result.retained_dirs == 1


# ---------------------------------------------------------------------------
# 22-23: what retention is allowed to see and when it runs
# ---------------------------------------------------------------------------


def test_retention_runs_only_after_a_promoted_snapshot(tmp_path: Path) -> None:
    svc, data_dir, backup_root = _service(tmp_path, retain_days=3)
    _make_sqlite_db(data_dir / "good.db")
    (data_dir / "bad.db").write_bytes(b"CORRUPT-NO-SQLITE-HEADER")
    prunable = _plant(backup_root, "20200101-000000")

    failed = svc.snapshot()
    assert failed.succeeded is False
    assert failed.pruned_dirs == []
    assert prunable.exists(), "retention ran on an unpromoted tick"

    # PREMISE ASSERTION: with the bad file gone the same call DOES prune, so
    # the assertion above discriminates on promotion rather than on age math.
    (data_dir / "bad.db").unlink()
    promoted = svc.snapshot()
    assert promoted.succeeded is True
    assert promoted.pruned_dirs == [str(prunable)]
    assert not prunable.exists()


def test_incomplete_directories_are_invisible_to_retention(tmp_path: Path) -> None:
    svc, _, backup_root = _service(tmp_path, retain_days=1, max_total_bytes=1)
    stale = _plant(backup_root, f"20200101-000000{INCOMPLETE_SUFFIX}", size=4096)
    promoted_old = _plant(backup_root, "20200102-000000", size=4096)
    newest = _plant(
        backup_root, time.strftime("%Y%m%d-%H%M%S", time.gmtime()), size=4096,
    )

    result = svc.prune()

    assert result.pruned_dirs == [str(promoted_old)]
    assert stale.exists(), (
        "retention deleted a working directory; it could be the tick currently "
        "being written"
    )
    assert newest.exists()
    # Only promoted directories are counted at all, so the stale .incomplete
    # is absent from `retained_dirs` as well as from the prune candidates.
    assert result.retained_dirs == 1


# ---------------------------------------------------------------------------
# 24: the valve announces itself (D2)
# ---------------------------------------------------------------------------


def test_bytes_bound_warning_fires_and_reaches_the_event_payload(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """D2: a ceiling that quietly overrides the stated policy is how the
    AD-1262 default became a lie."""
    now = time.time()
    events: list[tuple[object, dict]] = []
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    data_dir.mkdir(parents=True)
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")

    svc = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
        retain_days=3650,  # days would keep everything
        max_total_bytes=6000,
        emit_event=lambda kind, payload: events.append((kind, payload)),
    )
    for offset in (300, 200, 100):
        _plant(
            backup_root,
            time.strftime("%Y%m%d-%H%M%S", time.gmtime(now - offset)),
            size=3000,
        )

    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        result = svc.snapshot()

    assert result.succeeded is True
    assert result.pruned_dirs, "the ceiling should have bound here"
    assert result.retention_bound == "bytes"

    kind, payload = events[-1]
    assert getattr(kind, "value", kind) == "backup_complete"
    assert payload["retention_bound"] == "bytes"

    warnings = [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING and "byte ceiling" in r.getMessage()
    ]
    assert len(warnings) == 1, warnings
    assert "retain_days=3650" in warnings[0]
    assert "max_total_bytes=6000" in warnings[0]
    assert "effective retention is" in warnings[0]


def test_days_bound_is_reported_when_age_alone_pruned(tmp_path: Path) -> None:
    """The other half: retention_bound must discriminate, not always say bytes."""
    svc, _, backup_root = _service(tmp_path, retain_days=3, max_total_bytes=8 * 1024**3)
    _plant(backup_root, "20200101-000000")
    _plant(backup_root, time.strftime("%Y%m%d-%H%M%S", time.gmtime()))

    result = svc.prune()
    assert result.pruned_dirs
    assert result.bound == "days"


# ---------------------------------------------------------------------------
# 25: a hard link is data-present
# ---------------------------------------------------------------------------


def test_pruning_a_snapshot_leaves_hard_linked_bytes_readable_elsewhere(
    tmp_path: Path,
) -> None:
    """D1's whole distinction, measured.

    A hard link is data-present; a ``bulk_source`` reference is data-absent.
    Pruning the snapshot a link was sourced from must not destroy the bytes.
    """
    import os

    svc, data_dir, backup_root = _service(tmp_path, retain_days=3650)
    ward = data_dir / "archives" / "ward_room_001.db"
    _make_sqlite_db(ward, rows=3)
    old = time.time() - 3600
    os.utime(ward, (old, old))

    first = Path(svc.snapshot().snapshot_dir)
    time.sleep(1.05)
    second_result = svc.snapshot()
    second = Path(second_result.snapshot_dir)

    # PREMISE ASSERTION: the link actually happened, or pruning proves nothing.
    assert "data/archives/ward_room_001.db" in second_result.files_linked
    linked = second / "data" / "archives" / "ward_room_001.db"
    assert linked.stat().st_nlink > 1

    import shutil

    shutil.rmtree(first)
    assert not first.exists()

    assert linked.is_file()
    conn = sqlite3.connect(str(linked))
    try:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 3
    finally:
        conn.close()


def test_prune_on_an_empty_backup_root_is_a_no_op(tmp_path: Path) -> None:
    svc, _, _ = _service(tmp_path)
    assert svc.prune() == PruneResult(retained_dirs=0)
