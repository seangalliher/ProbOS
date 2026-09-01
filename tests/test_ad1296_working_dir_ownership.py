"""AD-1296: working-directory ownership that never asks whether a peer is alive.

AD-1265 put the owner in an ``owner.json`` inside the working directory and
had the sweep judge liveness from it. Review measured three failures and
disclosed four more non-guarantees, and every one of the seven was reachable
only through that judgement: a peer's sweep deleting a live service's
directory, a path-keyed claim set letting a rename-losing peer release the
winner's claim, and a zero-byte marker reading as abandoned while a handle was
open -- plus PID recycling, the stale backstop's admitted "can in principle
delete a peer that is still writing", the POSIX non-empty reservation, and
nothing working across hosts.

AD-1296 removes the judgement instead of guarding it. The owner is in the
directory *name*, written by one ``mkdir``, so there is no marker to read, no
parse-failure branch, and no window in which a directory is unowned. The sweep
reclaims only what it can prove from memory -- this PID, a run id this process
is not writing -- and keeps everything else.

**Behaviour inversion, stated so no reviewer has to infer it from a missing
test:** AD-1265 asserted that a directory owned by a *dead foreign PID* is
swept. Under AD-1296 D3 it is **not**. ``test_a_dead_foreign_owner_survives_
the_sweep_and_is_reported`` pins the new behaviour deliberately.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import probos.infrastructure.backup as backup_module
from probos.config import SystemConfig
from probos.infrastructure.backup import (
    _DEFAULT_ORPHAN_ALERT_BYTES,
    _SNAPSHOT_DIR_RE,
    _WORKING_DIR_RE,
    BackupResult,
    BackupService,
)
from probos.infrastructure.backup_inventory import BackupRoot
from probos.infrastructure.snapshot_manifest import INCOMPLETE_SUFFIX
from probos.pidfile_guard import is_pid_alive

_FOREIGN_LOG = "are NOT reclaimed"
_RECLAIM_LOG = "reclaimed finished working directory"
#: Only the escalated branch says this; the plain warning must not.
_THRESHOLD_LOG = "at or past the alert threshold"


def _make_sqlite_db(path: Path) -> None:
    import sqlite3

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


def _bed(tmp_path: Path) -> tuple[Path, Path]:
    """A data dir with one backable database, and its backup root."""
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "payload.db")
    return data_dir, backup_root


def _plant(backup_root: Path, name: str, *, payload: bytes = b"half a copy") -> Path:
    """A working directory with some bytes in it, under a literal name."""
    working = backup_root / name
    (working / "data").mkdir(parents=True)
    (working / "data" / "torn.db").write_bytes(payload)
    return working


@pytest.fixture
def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert is_pid_alive(proc.pid) is False, "premise: this PID must be dead"
    return proc.pid


@pytest.fixture
def live_foreign_pid():  # noqa: ANN201
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
    try:
        assert proc.pid != os.getpid()
        assert is_pid_alive(proc.pid) is True, "premise: this PID must be alive"
        yield proc.pid
    finally:
        proc.kill()
        proc.wait()


# ---------------------------------------------------------------------------
# 1-3: carried over from AD-1265, retargeted at the new mechanism
# ---------------------------------------------------------------------------


class _SlowService(BackupService):
    """Holds a working directory open long enough for a peer to sweep it."""

    def _backup_one(self, src: Path, dest: Path) -> None:
        time.sleep(0.8)
        super()._backup_one(src, dest)


def test_a_peer_sweep_does_not_destroy_an_in_flight_working_directory(
    tmp_path: Path,
) -> None:
    """The AD-1265 round-1 regression. Now passes with no liveness call.

    Two services, one backup root, one slowed inside ``_backup_one``. The
    peer's sweep runs while the slow service is mid-copy. Under AD-1265 that
    sweep deleted the slow service's directory and it failed ``ENOENT`` on a
    file it was copying.

    What is asserted is that the *copy completed and the bytes survived*, not
    that both runs promoted. Dropping the reservation rename means two peers
    in the same second now pick the same promoted name and the second loses at
    promotion -- AD-1296 D1 prices that deliberately, and
    ``test_two_services_in_one_second_each_get_their_own_directory`` pins it.
    Failing at promotion with the bytes intact is a different event from being
    deleted mid-copy, and only the second one is the defect.
    """
    data_dir, backup_root = _bed(tmp_path)
    # PREMISE: something the peer's sweep MUST be able to act on, so "the slow
    # service survived" cannot be satisfied by a sweep that never ran. This
    # process's own PID with a retired run id is the one case D2 reclaims.
    reclaimable = _plant(
        backup_root, f"20200101-000000.{os.getpid()}-deadbeef{INCOMPLETE_SUFFIX}",
    )

    slow = _SlowService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )
    peer = _service(data_dir, backup_root)

    results: dict[str, BackupResult] = {}
    worker = threading.Thread(
        target=lambda: results.__setitem__("slow", slow.snapshot())
    )
    worker.start()
    time.sleep(0.3)
    results["peer"] = peer.snapshot()
    worker.join(timeout=30)

    assert not worker.is_alive()
    assert not reclaimable.exists(), "the peer's sweep never ran"

    slow_result = results["slow"]
    assert any("payload.db" in f for f in slow_result.files_copied), (
        f"the in-flight copy did not complete: {slow_result.error}"
    )
    assert Path(slow_result.snapshot_dir).is_dir(), (
        "a peer sweep destroyed an in-flight working directory"
    )
    assert "No such file" not in slow_result.error, slow_result.error
    assert results["peer"].succeeded is True


def test_this_process_earlier_finished_working_directory_is_reclaimed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Own PID, retired run id -- the one thing the sweep can prove."""
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
    match = _WORKING_DIR_RE.match(left_behind.name)
    assert match is not None, f"premise: {left_behind.name} must parse"
    assert int(match.group(2)) == os.getpid(), "premise: owned by this process"

    (data_dir / "bad.db").unlink()
    with caplog.at_level(logging.INFO, logger="probos.infrastructure.backup"):
        second = svc.snapshot()
    assert second.succeeded is True

    assert not left_behind.exists()
    assert any(_RECLAIM_LOG in r.getMessage() for r in caplog.records)
    assert second.orphaned_working_dirs == []


def test_a_promoted_snapshot_directory_name_carries_no_owner_segment(
    tmp_path: Path,
) -> None:
    data_dir, backup_root = _bed(tmp_path)

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    promoted = Path(result.snapshot_dir).name
    assert _SNAPSHOT_DIR_RE.match(promoted), promoted
    assert _WORKING_DIR_RE.match(promoted) is None
    assert sorted(p.name for p in backup_root.iterdir()) == [promoted], (
        "a working or staging directory leaked into the backup root"
    )


# ---------------------------------------------------------------------------
# 4-9: unknown ownership means keep, count and warn (D3)
# ---------------------------------------------------------------------------


def test_an_unreadable_owner_marker_changes_nothing(tmp_path: Path) -> None:
    """The round-2 finding, made structural rather than guarded.

    Under AD-1265 a zero-byte / truncated / unreadable ``owner.json`` read as
    "no owner", which read as abandoned, which swept a directory another
    process held open. Here the marker is not read at all, so its contents
    cannot influence anything.

    PREMISE: the same directory carrying a *valid* marker is also untouched.
    Without that, "the corrupt one survived" would be satisfied by a sweep
    that simply never ran.
    """
    data_dir, backup_root = _bed(tmp_path)
    foreign_pid = os.getpid() + 1
    planted: list[Path] = []
    for i, marker in enumerate(
        (
            b"",                                            # zero-byte
            b'{"pid": 12',                                  # truncated
            b"\xff\xfe not utf-8 at all",                   # unreadable
            json.dumps({"pid": foreign_pid, "created_at": time.time()}).encode(),
        )
    ):
        working = _plant(
            backup_root,
            f"2020010{i}-000000.{foreign_pid}-aaaaaaa{i}{INCOMPLETE_SUFFIX}",
        )
        (working / "owner.json").write_bytes(marker)
        planted.append(working)

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    for working in planted:
        assert working.exists(), f"{working.name} was swept"
    assert sorted(result.orphaned_working_dirs) == sorted(
        str(p) for p in planted
    )


def test_a_dead_foreign_owner_survives_the_sweep_and_is_reported(
    tmp_path: Path, dead_pid: int,
) -> None:
    """AD-1296 D3, and the deliberate inversion of AD-1265's behaviour.

    AD-1265 asserted that a dead foreign PID's directory IS swept -- that test
    is deleted, not because it failed but because the mechanism it exercised
    is gone. A PID is not comparable across hosts and is recycled locally, so
    "that PID is dead" is not proof this directory is finished. It is kept and
    reported instead.
    """
    data_dir, backup_root = _bed(tmp_path)
    abandoned = _plant(
        backup_root, f"20200101-000000.{dead_pid}-abcd1234{INCOMPLETE_SUFFIX}",
    )

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert abandoned.exists(), (
        "AD-1296 D3 keeps an unprovable directory; sweeping it is the "
        "AD-1265 behaviour this AD deliberately inverts"
    )
    assert result.orphaned_working_dirs == [str(abandoned)]


def test_a_legacy_working_directory_name_survives_and_is_reported(
    tmp_path: Path,
) -> None:
    """``<ts>.incomplete`` from AD-1265 has no owner segment. Unknown => keep."""
    data_dir, backup_root = _bed(tmp_path)
    legacy = _plant(backup_root, f"20200101-000000{INCOMPLETE_SUFFIX}")

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert legacy.exists()
    assert result.orphaned_working_dirs == [str(legacy)]


@pytest.mark.parametrize(
    "name",
    [
        f"20200101-000000.notapid-abcd1234{INCOMPLETE_SUFFIX}",
        f"20200101-000000.4321-NOTHEX01{INCOMPLETE_SUFFIX}",
        f"20200101-000000.4321-abcd12{INCOMPLETE_SUFFIX}",
        f"nonsense.4321-abcd1234{INCOMPLETE_SUFFIX}",
    ],
)
def test_a_malformed_owner_segment_survives_and_is_reported(
    tmp_path: Path, name: str,
) -> None:
    """Unparseable is not the same as unowned. There is no delete-on-parse-fail."""
    data_dir, backup_root = _bed(tmp_path)
    assert _WORKING_DIR_RE.match(name) is None, f"premise: {name} must not parse"
    malformed = _plant(backup_root, name)

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert malformed.exists()
    assert result.orphaned_working_dirs == [str(malformed)]


def test_orphaned_bytes_are_non_zero_and_reach_the_backup_result(
    tmp_path: Path,
) -> None:
    """Retention cannot see a working directory, so the size must be reported."""
    data_dir, backup_root = _bed(tmp_path)
    payload = b"x" * 4096
    orphan = _plant(
        backup_root,
        f"20200101-000000.{os.getpid() + 1}-abcd1234{INCOMPLETE_SUFFIX}",
        payload=payload,
    )

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert result.orphaned_working_dirs == [str(orphan)]
    assert result.orphaned_bytes == len(payload)
    # The byte ceiling must NOT absorb them: that would prune healthy
    # snapshots and misattribute the cause (AD-1296 D4).
    assert result.pruned_dirs == []


def test_orphans_warn_and_a_clean_root_does_not(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    data_dir, backup_root = _bed(tmp_path)

    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        clean = _service(data_dir, backup_root).snapshot()
    assert clean.succeeded is True
    assert not [r for r in caplog.records if _FOREIGN_LOG in r.getMessage()], (
        "a clean backup root warned about orphans that do not exist"
    )

    _plant(
        backup_root,
        f"20200101-000000.{os.getpid() + 1}-abcd1234{INCOMPLETE_SUFFIX}",
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        dirty = _service(data_dir, backup_root).snapshot()
    assert dirty.succeeded is True
    warned = [r.getMessage() for r in caplog.records if _FOREIGN_LOG in r.getMessage()]
    assert len(warned) == 1, warned
    assert "backup-reclaim" in warned[0]


# ---------------------------------------------------------------------------
# D3 reporting: the leak has to be visible where the operator actually looks,
# and it has to get louder as it grows. Neither of those may delete anything.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphan_counts_reach_the_event_log_payload(tmp_path: Path) -> None:
    """``events.db`` is the operator's surface; ``emit_event`` never reaches it.

    ``BackupResult`` carried these two fields from the start, but
    ``_log_backup_tick`` did not copy them into the row -- so a
    working-directory leak was absent from the exact table the #1313 diagnosis
    was made by querying. A field that is set and never read is inert and looks
    identical to working, so this reads the values back out of the database.
    """
    from probos.runtime import ProbOSRuntime

    data_dir, backup_root = _bed(tmp_path)
    payload = b"y" * 2048
    orphan = _plant(
        backup_root,
        f"20200101-000000.{os.getpid() + 1}-abcd1234{INCOMPLETE_SUFFIX}",
        payload=payload,
    )

    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=data_dir)
    await runtime.event_log.start()
    try:
        result = _service(data_dir, backup_root).snapshot()
        assert result.succeeded is True, result.error
        await runtime._log_backup_tick(result)

        rows = await runtime.event_log.query(category="backup", limit=10)
        assert [r["event"] for r in rows] == ["backup_complete"]
        assert rows[0]["data"]["orphaned_working_dirs"] == [str(orphan)]
        assert rows[0]["data"]["orphaned_bytes"] == len(payload)
    finally:
        await runtime.event_log.stop()

    assert orphan.is_dir(), "recording the leak must not remove the leak"


@pytest.mark.parametrize(
    ("threshold_delta", "expected_level", "why"),
    [
        (+1, logging.WARNING, "below the threshold"),
        (0, logging.ERROR, "exactly at the threshold"),
        (-1, logging.ERROR, "above the threshold"),
    ],
)
def test_the_orphan_message_escalates_at_the_alert_threshold(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    threshold_delta: int,
    expected_level: int,
    why: str,
) -> None:
    """One flat warning per tick reads as background noise after a month.

    ``threshold_delta`` moves the *threshold* around a fixed orphan size, so
    the three cases are orphan-bytes below, equal to, and above it. Equal
    escalates: this is an alert threshold, and "reached" is the point.
    """
    data_dir, backup_root = _bed(tmp_path)
    payload = b"z" * 4096
    orphan = _plant(
        backup_root,
        f"20200101-000000.{os.getpid() + 1}-abcd1234{INCOMPLETE_SUFFIX}",
        payload=payload,
    )

    svc = _service(
        data_dir, backup_root,
        orphan_alert_bytes=len(payload) + threshold_delta,
    )
    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        result = svc.snapshot()

    assert result.succeeded is True, result.error
    assert result.orphaned_bytes == len(payload)
    records = [r for r in caplog.records if _FOREIGN_LOG in r.getMessage()]
    assert len(records) == 1, [r.getMessage() for r in records]
    assert records[0].levelno == expected_level, (
        f"{why}: expected {logging.getLevelName(expected_level)}, "
        f"got {records[0].levelname}"
    )
    assert "backup-reclaim" in records[0].getMessage(), (
        "every severity must still say what to run"
    )
    escalated = expected_level == logging.ERROR
    assert (_THRESHOLD_LOG in records[0].getMessage()) is escalated

    # The whole point of AD-1296 D3: escalation is louder, never destructive.
    assert orphan.is_dir()
    assert (orphan / "data" / "torn.db").read_bytes() == payload


def test_escalation_deletes_nothing_even_when_every_orphan_is_over_threshold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """``orphan_alert_bytes=0`` escalates on any orphan at all. Still no rmtree.

    Deleting on "unknown owner" is the decision AD-1296 exists to remove: it
    was measured destroying an in-flight snapshot and breaking a live peer
    mid-write. Raising the log level must not have quietly reintroduced it, so
    this asserts every planted directory and its bytes survive a tick that
    fires the loudest branch.
    """
    data_dir, backup_root = _bed(tmp_path)
    payload = b"q" * 512
    planted = [
        _plant(backup_root, name, payload=payload)
        for name in (
            f"20200101-000000.{os.getpid() + 1}-abcd1234{INCOMPLETE_SUFFIX}",
            f"20200102-000000.{os.getpid() + 2}-beef5678{INCOMPLETE_SUFFIX}",
            f"legacy-shape{INCOMPLETE_SUFFIX}",
        )
    ]

    svc = _service(data_dir, backup_root, orphan_alert_bytes=0)
    with caplog.at_level(logging.WARNING, logger="probos.infrastructure.backup"):
        result = svc.snapshot()

    assert result.succeeded is True, result.error
    errors = [
        r for r in caplog.records
        if _FOREIGN_LOG in r.getMessage() and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1, [r.getMessage() for r in caplog.records]

    assert sorted(result.orphaned_working_dirs) == sorted(str(p) for p in planted)
    assert result.orphaned_bytes == len(payload) * len(planted)
    for orphan in planted:
        assert orphan.is_dir(), f"escalation deleted {orphan}"
        assert (orphan / "data" / "torn.db").read_bytes() == payload
    # And it did not reach for the promoted set instead (AD-1296 D4).
    assert result.pruned_dirs == []


def test_the_service_default_threshold_is_the_configured_one() -> None:
    """A default that drifts from config is a knob that silently does nothing."""
    assert (
        SystemConfig().infrastructure.backup_orphan_alert_bytes
        == _DEFAULT_ORPHAN_ALERT_BYTES
    )


def test_startup_threads_every_backup_knob_from_config_to_the_service(
    tmp_path: Path,
) -> None:
    """The knobs must ARRIVE at the service, not merely appear in the call.

    This replaces an AST assertion on the constructor call site. That check
    could prove a kwarg was *written*; it could not prove a value *arrives* --
    the distinction #1313 turned on, where ``BackupService`` was constructed
    and never invoked and nothing noticed for the life of AD-466. The two are
    not kept side by side, because the weaker one would only ever fail in cases
    this already covers.

    All three knobs, not just the newest, and each set to a NON-DEFAULT value
    so a wirer that quietly ignored config and used its own defaults fails
    here.
    """
    from types import SimpleNamespace

    from probos.startup.finalize import _wire_backup_service

    config = SystemConfig()
    config.infrastructure.enabled = True
    config.infrastructure.backup_enabled = True
    config.infrastructure.backup_retain_days = 11
    config.infrastructure.backup_max_total_bytes = 123_456_789
    config.infrastructure.backup_orphan_alert_bytes = 987_654_321

    runtime = SimpleNamespace(
        data_dir=tmp_path,
        emit_event=lambda *a, **kw: None,
        backup_service=None,
    )

    assert _wire_backup_service(runtime=runtime, config=config) is True

    svc = runtime.backup_service
    assert svc is not None
    assert svc._retain_days == 11
    assert svc._max_total_bytes == 123_456_789
    assert svc._orphan_alert_bytes == 987_654_321
    assert svc._backup_root == tmp_path / config.infrastructure.backup_subdir


def test_startup_leaves_no_service_when_backups_are_disabled(
    tmp_path: Path,
) -> None:
    """The premise the crossing test needs: the wirer really is consulted.

    Without this, a ``_wire_backup_service`` that unconditionally built a
    service would satisfy the test above while ignoring the enable flag. Both
    gates are covered, because the helper carries the ``infrastructure.enabled``
    precondition itself rather than relying on its one caller to apply it.
    """
    from types import SimpleNamespace

    from probos.startup.finalize import _wire_backup_service

    for enabled, backups in ((True, False), (False, True), (False, False)):
        config = SystemConfig()
        config.infrastructure.enabled = enabled
        config.infrastructure.backup_enabled = backups
        runtime = SimpleNamespace(
            data_dir=tmp_path,
            emit_event=lambda *a, **kw: None,
            backup_service="sentinel",
        )

        assert _wire_backup_service(runtime=runtime, config=config) is False, (
            f"wired a backup service with enabled={enabled}, "
            f"backup_enabled={backups}"
        )
        assert runtime.backup_service is None


def test_finalize_still_calls_the_backup_wirer() -> None:
    """The helper being correct is worth nothing if nobody calls it.

    Deliberately a source-structure check. Driving ``finalize_startup`` needs a
    whole booted runtime, so the alternative is no pin at all on this link --
    and an unpinned link is precisely #1313, where ``BackupService`` was
    constructed and never invoked for the life of AD-466. The runtime test
    above proves the values arrive *once the helper runs*; this proves startup
    still runs it.
    """
    import ast
    import inspect

    from probos.startup import finalize as finalize_module

    tree = ast.parse(inspect.getsource(finalize_module))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "_wire_backup_service" in defined, (
        "premise: the helper is gone, so this probe no longer discriminates"
    )

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_wire_backup_service" in called, (
        "finalize defines the backup wirer but never calls it, so every "
        "infrastructure.backup_* knob is inert at startup"
    )


# ---------------------------------------------------------------------------
# 10-12: the run-id registry, which is the finding-2 regression
# ---------------------------------------------------------------------------


def test_two_services_in_one_second_each_get_their_own_directory(
    tmp_path: Path,
) -> None:
    """The AD-1265 finding-2 regression.

    A path-keyed claim set gave two same-second attempts one key, so the
    loser's release revoked the winner's claim and the sweep ate a live
    directory. Keyed on the run id they cannot collide -- and under AD-1296
    they do not contend for a directory name either.

    This test must fail if ``_LIVE_RUNS`` is keyed by path.
    """
    data_dir, backup_root = _bed(tmp_path)
    fixed = time.time()
    # Same ``started`` => same timestamp => same ``final_dir`` for both.
    a, b = _service(data_dir, backup_root), _service(data_dir, backup_root)
    dir_a, final_a, fail_a = a._make_snapshot_dir(fixed, "aaaaaaaa")
    dir_b, final_b, fail_b = b._make_snapshot_dir(fixed, "bbbbbbbb")

    assert dir_a is not None and dir_b is not None, (fail_a, fail_b)
    assert dir_a != dir_b, "two runs shared one working directory"
    assert final_a == final_b, "premise: both aimed at the same promoted name"
    assert dir_a.is_dir() and dir_b.is_dir()

    # Both complete. The first promotion wins; the second must degrade down
    # the already-tested promote_error path, and NEITHER directory may be
    # swept out from under the other.
    backup_module._run_begin("aaaaaaaa")
    backup_module._run_begin("bbbbbbbb")
    try:
        res_a = a._write_snapshot(fixed, dir_a, final_a)
        res_b = b._write_snapshot(fixed, dir_b, final_b)
    finally:
        backup_module._run_end("aaaaaaaa")
        backup_module._run_end("bbbbbbbb")

    assert res_a.succeeded is True, res_a.error
    assert res_b.succeeded is False, "two directories both promoted to one name"
    assert "promotion failed" in res_b.error, res_b.error
    assert Path(res_b.incomplete_dir).exists(), "the loser's bytes were destroyed"
    assert res_a.orphaned_working_dirs == [], res_a.orphaned_working_dirs


def test_a_live_sibling_run_id_is_skipped(tmp_path: Path) -> None:
    """A PID cannot tell a live sibling from this process's own leftover."""
    data_dir, backup_root = _bed(tmp_path)
    sibling = _plant(
        backup_root, f"20200101-000000.{os.getpid()}-feedface{INCOMPLETE_SUFFIX}",
    )

    backup_module._run_begin("feedface")
    try:
        result = _service(data_dir, backup_root).snapshot()
    finally:
        backup_module._run_end("feedface")

    assert result.succeeded is True
    assert sibling.exists(), "a sibling's in-flight working directory was swept"
    # Skipped, not reported: it is ours and it is live, which is neither
    # reclaimable nor unknown.
    assert result.orphaned_working_dirs == []

    # PREMISE: once the run retires, the very same directory IS reclaimed.
    # Without this the assertion above would hold for a sweep that never ran.
    assert _service(data_dir, backup_root).snapshot().succeeded is True
    assert not sibling.exists()


def test_the_run_id_is_retired_when_write_snapshot_raises(tmp_path: Path) -> None:
    """No immortal directory: ``_run_end`` is in a ``finally``."""
    data_dir, backup_root = _bed(tmp_path)

    class _Exploding(BackupService):
        def _write_snapshot(self, started, working_dir, final_dir):  # noqa: ANN001, ANN202
            raise RuntimeError("boom")

    svc = _Exploding(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )
    before = set(backup_module._LIVE_RUNS)
    with pytest.raises(RuntimeError, match="boom"):
        svc.snapshot()
    assert set(backup_module._LIVE_RUNS) == before, "a run id outlived its run"

    # And the directory it stranded is therefore reclaimable next tick.
    stranded = [p for p in backup_root.iterdir() if p.name.endswith(INCOMPLETE_SUFFIX)]
    assert len(stranded) == 1, stranded
    assert _service(data_dir, backup_root).snapshot().succeeded is True
    assert not stranded[0].exists()


# ---------------------------------------------------------------------------
# 13-17: naming and promotion invariants
# ---------------------------------------------------------------------------


def test_the_working_dir_regex_parses_what_make_snapshot_dir_writes(
    tmp_path: Path,
) -> None:
    """Drift guard. The failure mode is silent: every directory reads foreign
    and nothing is ever reclaimed, while every test that only checks
    "the snapshot succeeded" still passes.
    """
    _data_dir, backup_root = _bed(tmp_path)
    svc = _service(_data_dir, backup_root)
    started = 1767225600.123456  # a fixed instant with sub-second precision

    plain, final_plain, _ = svc._make_snapshot_dir(started, "0123abcd")
    assert plain is not None
    # Force the collision-suffixed base by occupying the plain promoted name.
    assert final_plain is not None
    final_plain.mkdir()
    suffixed, _final, _ = svc._make_snapshot_dir(started, "89efabcd")
    assert suffixed is not None

    for working in (plain, suffixed):
        match = _WORKING_DIR_RE.match(working.name)
        assert match is not None, f"{working.name} does not parse"
        assert int(match.group(2)) == os.getpid()
    assert _WORKING_DIR_RE.match(plain.name).group(3) == "0123abcd"  # type: ignore[union-attr]
    assert _WORKING_DIR_RE.match(suffixed.name).group(3) == "89efabcd"  # type: ignore[union-attr]
    assert "-" in suffixed.name.split(".")[0], suffixed.name


@pytest.mark.parametrize(
    "name",
    [
        f"20200101-000000.4321-abcd1234{INCOMPLETE_SUFFIX}",
        f"20200101-000000-123456.4321-abcd1234{INCOMPLETE_SUFFIX}",
        f"20200101-000000{INCOMPLETE_SUFFIX}",
        f"20200101-000000-123456{INCOMPLETE_SUFFIX}",
    ],
)
def test_the_promoted_regex_excludes_every_working_directory_shape(
    name: str,
) -> None:
    """Retention and hard-link sourcing must never see a working directory."""
    assert _SNAPSHOT_DIR_RE.match(name) is None, name
    # PREMISE: the regex does match the promoted names those derive from.
    assert _SNAPSHOT_DIR_RE.match(name.split(".")[0]) is not None


def test_no_owner_marker_is_written_anywhere_during_a_snapshot(
    tmp_path: Path,
) -> None:
    """The marker is gone, not merely unread."""
    data_dir, backup_root = _bed(tmp_path)

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert not list(backup_root.rglob("owner.json"))
    assert not list(backup_root.rglob(".staging-*"))


def test_promotion_onto_an_existing_directory_fails(tmp_path: Path) -> None:
    """The property that replaces the reservation rename.

    PREMISE: promotion onto an absent name succeeds in this same test, so
    "the second one failed" is not vacuous.
    """
    data_dir, backup_root = _bed(tmp_path)
    svc = _service(data_dir, backup_root)

    working = _plant(backup_root, f"20200101-000000.1-aaaaaaaa{INCOMPLETE_SUFFIX}")
    absent = backup_root / "20200101-000000"
    assert svc._promote(working, absent) == absent
    assert absent.is_dir() and not working.exists()

    second = _plant(backup_root, f"20200102-000000.1-bbbbbbbb{INCOMPLETE_SUFFIX}")
    with pytest.raises(OSError):
        svc._promote(second, absent)
    assert second.exists(), "the loser's bytes were destroyed by a failed promotion"


def test_a_mkdir_failure_fails_the_run_and_retires_the_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir, backup_root = _bed(tmp_path)

    def _boom(self, *a, **kw):  # noqa: ANN001, ANN202
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "mkdir", _boom)
    before = set(backup_module._LIVE_RUNS)
    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is False
    assert "mkdir failed" in result.error
    assert set(backup_module._LIVE_RUNS) == before, "a run id outlived a failed run"


def test_a_mkdir_failure_does_not_report_a_measured_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``orphaned_bytes: 0`` here means "not counted", not "nothing to count".

    The sweep never runs when ``mkdir`` fails, so the zero carries no
    information about orphans. These counts are routed to ``events.db`` and the
    #1313 diagnosis was made by querying that table, so a consumer aggregating
    them across ticks would otherwise read an unmeasured tick as a clean one
    and report no leak while one accumulated.
    """
    data_dir, backup_root = _bed(tmp_path)

    def _boom(self, *a, **kw):  # noqa: ANN001, ANN202
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "mkdir", _boom)
    failed = _service(data_dir, backup_root).snapshot()

    assert failed.succeeded is False
    assert failed.orphaned_bytes == 0
    assert failed.orphans_measured is False, (
        "a tick that never swept is reporting its zero as a measurement"
    )


def test_a_completed_tick_reports_its_orphan_count_as_measured(
    tmp_path: Path,
) -> None:
    """The companion the test above needs to mean anything.

    Without it ``orphans_measured`` could be hardcoded ``False`` and the
    unmeasured-zero assertion would still pass, proving nothing.
    """
    data_dir, backup_root = _bed(tmp_path)

    result = _service(data_dir, backup_root).snapshot()

    assert result.succeeded is True
    assert result.orphans_measured is True


def test_the_run_is_registered_before_its_directory_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: there is no instant at which our directory exists and its run is not
    yet live.

    That window is the whole reason AD-1265 needed a staging directory and a
    rename. Here it is closed by ordering instead: ``_run_begin`` runs before
    ``_make_snapshot_dir``, so a peer sweeping the moment the directory
    appears sees a live run id and leaves it alone. Move the registration
    after the ``mkdir`` and the peer reclaims it -- same PID, run not live --
    and the snapshot then fails on a directory that vanished under it.

    The window is nanoseconds wide, so it is opened deterministically: a hook
    on ``Path.mkdir`` runs a peer sweep the instant the directory exists.
    """
    data_dir, backup_root = _bed(tmp_path)
    svc = _service(data_dir, backup_root)
    peer = _service(data_dir, backup_root)

    real_mkdir = Path.mkdir
    observed: list[list[str]] = []

    def _hooked(self: Path, *a: object, **kw: object):  # noqa: ANN202
        made = real_mkdir(self, *a, **kw)  # type: ignore[arg-type]
        if (
            not observed
            and self.parent == backup_root
            and self.name.endswith(INCOMPLETE_SUFFIX)
        ):
            # A peer looks at the backup root the instant the directory is
            # there. It excludes nothing, because it has none of its own yet.
            observed.append(
                peer._sweep_incomplete(
                    exclude=backup_root / "no-such-dir"
                ).reclaimed_dirs
            )
        return made

    monkeypatch.setattr(Path, "mkdir", _hooked)
    result = svc.snapshot()

    assert observed, "premise: the hook never saw a working directory appear"
    assert observed[0] == [], (
        f"a peer reclaimed our working directory before its run was live: "
        f"{observed[0]}"
    )
    assert result.succeeded is True, result.error


# ---------------------------------------------------------------------------
# 18-22: probos backup-reclaim (Section 4)
# ---------------------------------------------------------------------------


def _reclaim(**kw: object) -> int:
    from probos.__main__ import _cmd_backup_reclaim

    args = argparse.Namespace(
        backup_root=kw.get("backup_root"),
        force=kw.get("force", False),
        data_dir=kw.get("data_dir"),
    )
    return _cmd_backup_reclaim(args)


def test_backup_reclaim_lists_without_deleting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    orphan = _plant(backup_root, f"20200101-000000.4321-abcd1234{INCOMPLETE_SUFFIX}")

    assert _reclaim(backup_root=backup_root) == 1
    assert orphan.exists(), "the read-only listing deleted something"
    out = capsys.readouterr().out
    assert orphan.name in out
    assert "--force" in out


def test_backup_reclaim_force_deletes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    orphan = _plant(backup_root, f"20200101-000000.4321-abcd1234{INCOMPLETE_SUFFIX}")
    promoted = backup_root / "20200101-000000"
    promoted.mkdir()

    assert _reclaim(backup_root=backup_root, force=True, data_dir=tmp_path) == 0
    assert not orphan.exists()
    assert promoted.is_dir(), "--force removed a promoted snapshot"
    assert "removed" in capsys.readouterr().out


def test_backup_reclaim_exit_codes(tmp_path: Path) -> None:
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    # 0: nothing orphaned.
    assert _reclaim(backup_root=backup_root) == 0
    # 1: something orphaned (so a health check can use it).
    _plant(backup_root, f"20200101-000000.4321-abcd1234{INCOMPLETE_SUFFIX}")
    assert _reclaim(backup_root=backup_root) == 1
    # 2: bad arguments.
    assert _reclaim(backup_root=None) == 2
    assert _reclaim(backup_root=tmp_path / "does-not-exist") == 2


def test_backup_reclaim_liveness_note_is_advisory_only(
    tmp_path: Path, dead_pid: int, capsys: pytest.CaptureFixture[str],
) -> None:
    """A dead owner is *described*, never acted on without ``--force``."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    orphan = _plant(
        backup_root, f"20200101-000000.{dead_pid}-abcd1234{INCOMPLETE_SUFFIX}",
    )

    assert _reclaim(backup_root=backup_root) == 1

    out = capsys.readouterr().out
    assert "owner PID is not running" in out
    assert "advisory" in out
    assert orphan.exists(), "an advisory hint drove an automatic delete"


def test_backup_reclaim_force_takes_the_pidfile_guard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """``--force`` deletes, so it must refuse while a vessel owns the data dir."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    orphan = _plant(backup_root, f"20200101-000000.4321-abcd1234{INCOMPLETE_SUFFIX}")

    data_dir = tmp_path / "vessel"
    data_dir.mkdir()
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
    try:
        (data_dir / "probos.pid").write_text(str(live.pid), encoding="utf-8")
        assert _reclaim(backup_root=backup_root, force=True, data_dir=data_dir) == 2
        assert orphan.exists(), "--force deleted while a vessel was running"
        assert "--force" in capsys.readouterr().out

        # PREMISE: the same call succeeds once the vessel is gone, so the
        # refusal above is the guard and not a broken argument path.
        live.kill()
        live.wait()
        assert _reclaim(backup_root=backup_root, force=True, data_dir=data_dir) == 0
        assert not orphan.exists()
    finally:
        if live.poll() is None:
            live.kill()
            live.wait()


def test_the_read_only_listing_does_not_take_the_pidfile_guard(
    tmp_path: Path,
) -> None:
    """Following ``verify-snapshot``: a read-only check runs on a live vessel."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    _plant(backup_root, f"20200101-000000.4321-abcd1234{INCOMPLETE_SUFFIX}")

    data_dir = tmp_path / "vessel"
    data_dir.mkdir()
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
    try:
        (data_dir / "probos.pid").write_text(str(live.pid), encoding="utf-8")
        assert _reclaim(backup_root=backup_root, data_dir=data_dir) == 1
    finally:
        live.kill()
        live.wait()
