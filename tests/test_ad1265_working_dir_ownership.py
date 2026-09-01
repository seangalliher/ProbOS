"""AD-1265 round-1 finding 2: "not promoted" is not "abandoned".

Review ran two ``BackupService`` instances against one backup root, slowed
one inside ``_backup_one``, and measured the second one's stale sweep
deleting the first's **active** working directory. The first then failed
with ``No such file or directory ... payload.db``.

The sweep still has to exist -- a crashed tick's working directory is
otherwise immortal, and it can never be admitted. So both states have to be
handled, and the sweep has to be able to tell them apart. It does that by
ownership (PID in a marker written before the directory is visible, plus an
in-process registry, because two services in one process share a PID), not
by timing.

What is deliberately **not** pinned here, because the protocol does not
provide it: that a live PID matching an owner really is that owner. PIDs are
recycled; ``_OWNER_STALE_SECONDS`` bounds the resulting accumulation and is
exercised below, but it is a bound, not a guarantee.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

import probos.infrastructure.backup as backup_module
from probos.infrastructure.backup import (
    _OWNER_STALE_SECONDS,
    BackupResult,
    BackupService,
)
from probos.infrastructure.backup_inventory import BackupRoot
from probos.infrastructure.snapshot_manifest import INCOMPLETE_SUFFIX, OWNER_NAME
from probos.pidfile_guard import is_pid_alive

_SWEEP_LOG = "removed abandoned snapshot working directory"


def _make_sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (k TEXT)")
        conn.execute("INSERT INTO t VALUES ('v')")
        conn.commit()
    finally:
        conn.close()


def _service(data_dir: Path, backup_root: Path, **kw: object) -> BackupService:
    return BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)], **kw,  # type: ignore[arg-type]
    )


def _plant_working_dir(
    backup_root: Path, name: str, *, pid: int | None, created_at: float | None = None,
) -> Path:
    """A ``<ts>.incomplete`` directory, optionally claimed by ``pid``."""
    working = backup_root / name
    (working / "data").mkdir(parents=True)
    (working / "data" / "torn.db").write_bytes(b"half a copy")
    if pid is not None:
        (working / OWNER_NAME).write_text(
            json.dumps({"pid": pid, "created_at": created_at or time.time()}),
            encoding="utf-8",
        )
    return working


@pytest.fixture
def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert is_pid_alive(proc.pid) is False, "premise: this PID must be dead"
    return proc.pid


@pytest.fixture
def live_foreign_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
    try:
        assert proc.pid != os.getpid()
        assert is_pid_alive(proc.pid) is True, "premise: this PID must be alive"
        yield proc.pid
    finally:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# the reported defect
# ---------------------------------------------------------------------------


class _SlowService(BackupService):
    """Holds a working directory open long enough for a peer to sweep it."""

    def _backup_one(self, src: Path, dest: Path) -> None:
        time.sleep(0.8)
        super()._backup_one(src, dest)


def test_a_peer_sweep_does_not_destroy_an_in_flight_working_directory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    # PREMISE ASSERTION: something the peer's sweep MUST remove. Without it a
    # peer whose sweep never ran at all would satisfy this test vacuously.
    unowned = _plant_working_dir(backup_root, "20200101-000000.incomplete", pid=None)

    slow = _SlowService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )
    peer = _service(data_dir, backup_root)

    results: dict[str, BackupResult] = {}
    worker = threading.Thread(
        target=lambda: results.__setitem__("slow", slow.snapshot())
    )
    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        worker.start()
        time.sleep(0.3)
        results["peer"] = peer.snapshot()
        worker.join(timeout=30)

    assert not worker.is_alive()
    assert not unowned.exists(), "the peer's sweep never ran"
    assert results["slow"].succeeded is True, (
        f"a peer sweep destroyed an in-flight snapshot: {results['slow'].error}"
    )
    assert results["peer"].succeeded is True
    swept = [r.getMessage() for r in caplog.records if _SWEEP_LOG in r.getMessage()]
    assert len(swept) == 1 and "20200101-000000" in swept[0], swept


# ---------------------------------------------------------------------------
# the four ownership cases the sweep distinguishes
# ---------------------------------------------------------------------------


def test_a_directory_claimed_by_a_live_foreign_process_survives_the_sweep(
    tmp_path: Path, live_foreign_pid: int,
) -> None:
    """The cross-process arm, decided by real OS liveness (AD-816's probe)."""
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    claimed = _plant_working_dir(
        backup_root, "20200101-000000.incomplete", pid=live_foreign_pid,
    )

    assert _service(data_dir, backup_root).snapshot().succeeded is True

    assert claimed.exists(), "a live peer's working directory was swept"


def test_a_directory_claimed_by_a_dead_process_is_swept(
    tmp_path: Path, dead_pid: int,
) -> None:
    """The other half: ownership must not make abandonment unreachable."""
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    abandoned = _plant_working_dir(
        backup_root, "20200101-000000.incomplete", pid=dead_pid,
    )

    assert _service(data_dir, backup_root).snapshot().succeeded is True

    assert not abandoned.exists(), "an abandoned working directory was kept forever"


def test_this_process_earlier_failed_working_directory_is_swept(
    tmp_path: Path,
) -> None:
    """Same PID, not in flight -- an earlier tick of *this* process.

    Without the in-process registry this case and the live-sibling case are
    indistinguishable, and whichever way you answer it you lose one of them.
    """
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "good.db")
    (data_dir / "bad.db").write_bytes(b"CORRUPT-NO-SQLITE-HEADER")
    svc = _service(data_dir, backup_root)

    failed = svc.snapshot()
    assert failed.succeeded is False
    left_behind = Path(failed.incomplete_dir)
    assert left_behind.exists()
    pid, _ = BackupService._read_owner(left_behind)
    assert pid == os.getpid(), "premise: the leftover is claimed by this process"

    (data_dir / "bad.db").unlink()
    assert svc.snapshot().succeeded is True

    assert not left_behind.exists()


def test_the_stale_backstop_sweeps_a_directory_claimed_by_a_recycled_pid(
    tmp_path: Path, live_foreign_pid: int, caplog: pytest.LogCaptureFixture,
) -> None:
    """The one case liveness cannot decide, and the bound that covers it."""
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    ancient = _plant_working_dir(
        backup_root, "20200101-000000.incomplete", pid=live_foreign_pid,
        created_at=time.time() - _OWNER_STALE_SECONDS - 60,
    )

    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        assert _service(data_dir, backup_root).snapshot().succeeded is True

    assert not ancient.exists()
    assert any("recycled" in r.getMessage() for r in caplog.records), (
        "the backstop removed a directory a live PID still claims without saying so"
    )


# ---------------------------------------------------------------------------
# the creation window, which is what makes ownership decidable at all
# ---------------------------------------------------------------------------


def test_a_working_directory_is_marked_before_it_becomes_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mkdir-then-mark would leave a window a peer's sweep can enter.

    That window is the same defect by another route, so the marker is written
    into a staging directory and the directory is *renamed* into place. This
    inspects the source of that rename.
    """
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")

    observed: list[tuple[str, bool]] = []
    real_rename = os.rename

    def _watched(src, dst, *a, **kw):  # noqa: ANN001, ANN202
        if str(dst).endswith(INCOMPLETE_SUFFIX):
            observed.append((str(dst), (Path(src) / OWNER_NAME).is_file()))
        return real_rename(src, dst, *a, **kw)

    monkeypatch.setattr(backup_module.os, "rename", _watched)
    assert _service(data_dir, backup_root).snapshot().succeeded is True

    assert observed, "the working directory was not renamed into place"
    assert all(marked for _dst, marked in observed), observed


def test_a_promoted_snapshot_carries_no_ownership_marker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert not (Path(result.snapshot_dir) / OWNER_NAME).exists()
    assert sorted(p.name for p in backup_root.iterdir()) == [
        Path(result.snapshot_dir).name
    ], "the staging directory leaked into the backup root"


def test_a_staging_directory_is_collected_only_once_its_owner_is_gone(
    tmp_path: Path, dead_pid: int, live_foreign_pid: int,
) -> None:
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    stranded = backup_root / f".staging-{dead_pid}-{uuid.uuid4().hex[:16]}"
    stranded.mkdir()
    peer_building = backup_root / f".staging-{live_foreign_pid}-{uuid.uuid4().hex[:16]}"
    peer_building.mkdir()

    assert _service(data_dir, backup_root).snapshot().succeeded is True

    assert not stranded.exists()
    assert peer_building.exists(), "a peer's half-built staging directory was removed"


def test_the_staging_name_pattern_matches_what_the_service_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep parses the owner PID out of the name; a drift here makes
    every stranded staging directory permanent and silently so."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir(parents=True)
    svc = _service(tmp_path / "data", backup_root)

    staging = svc._stage_owned_dir(time.time())

    match = re.match(backup_module._STAGING_RE, staging.name)
    assert match is not None, staging.name
    assert int(match.group(1)) == os.getpid()
