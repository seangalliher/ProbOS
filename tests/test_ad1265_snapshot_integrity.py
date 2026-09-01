"""AD-1265: promotion, the manifest, and what ``verify_snapshot`` actually proves.

Two round-2 findings against the reverted AD-1262 attempt are pinned here and
must stay pinned:

* a directory with a valid ``complete=true`` manifest was admitted even though
  it had never been promoted -- process death between "manifest written" and
  "renamed" leaves exactly that on disk;
* an entry's recorded digest was bypassed because verification **chose its
  method by looking at the bytes it was verifying**, so replacing an opaque
  payload with a structurally valid SQLite database took the SQLite path and
  never reached the digest.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from probos.infrastructure.backup import BackupService
from probos.infrastructure.backup_inventory import BackupRoot
from probos.infrastructure.snapshot_manifest import (
    INCOMPLETE_SUFFIX,
    MANIFEST_NAME,
    STATE_COPIED,
    ManifestEntry,
    SnapshotManifest,
    read_manifest,
    sha256_file,
    write_manifest,
)
from probos.infrastructure.snapshot_verify import verify_snapshot


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


def _service(tmp_path: Path) -> tuple[BackupService, Path, Path]:
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    data_dir.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    svc = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
    )
    return svc, data_dir, backup_root


# ---------------------------------------------------------------------------
# 11-13: promotion is the rename, and nothing else
# ---------------------------------------------------------------------------


def test_a_failed_file_leaves_the_directory_incomplete_and_skips_retention(
    tmp_path: Path,
) -> None:
    events: list[tuple[object, dict]] = []
    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    data_dir.mkdir(parents=True)
    backup_root.mkdir(parents=True)
    _make_sqlite_db(data_dir / "good.db")
    # A .db that is not a database: the online backup falls back to a byte
    # copy and PRAGMA integrity_check then refuses it.
    (data_dir / "bad.db").write_bytes(b"CORRUPT-NO-SQLITE-HEADER")

    svc = BackupService(
        data_dir=data_dir, backup_root=backup_root,
        roots=[BackupRoot("data", data_dir)],
        emit_event=lambda kind, payload: events.append((kind, payload)),
    )
    result = svc.snapshot()

    assert result.succeeded is False
    assert result.snapshot_promoted is False
    assert result.files_failed == ["data/bad.db"]
    assert result.pruned_dirs == [], "retention must not run on an unpromoted tick"

    dirs = sorted(p.name for p in backup_root.iterdir())
    assert len(dirs) == 1 and dirs[0].endswith(INCOMPLETE_SUFFIX), dirs

    assert len(events) == 1
    kind, payload = events[0]
    assert getattr(kind, "value", kind) == "backup_failed"
    assert payload["files_failed"] == ["data/bad.db"]

    manifest = read_manifest(backup_root / dirs[0])
    assert manifest is not None
    assert manifest.complete is False


@pytest.mark.asyncio
async def test_hand_built_incomplete_dir_with_a_valid_manifest_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """The round-2 finding: only the rename means promoted.

    This must fail loudly if promotion ever stops being the sole marker, so
    the manifest here is deliberately valid and ``complete=true``.
    """
    forged = tmp_path / f"20260824-061728{INCOMPLETE_SUFFIX}"
    forged.mkdir(parents=True)
    payload = forged / "data"
    _make_sqlite_db(payload / "payload.db")
    write_manifest(
        forged,
        SnapshotManifest(
            snapshot=forged.name, created_at=time.time(),
            entries=[
                ManifestEntry(
                    label="data/payload.db", tier="included", state=STATE_COPIED,
                    size_bytes=(payload / "payload.db").stat().st_size,
                    sha256=sha256_file(payload / "payload.db"),
                )
            ],
        ),
    )
    # PREMISE ASSERTION: the forged manifest really does claim completeness,
    # otherwise the refusal could be for the wrong reason.
    forged_manifest = read_manifest(forged)
    assert forged_manifest is not None and forged_manifest.complete is True

    report = await verify_snapshot(forged)
    assert report.ok is False
    assert "not a promoted snapshot directory name" in report.refused_reason
    assert report.verdicts == [], "the manifest must not even be consulted"


def test_stale_incomplete_directories_are_swept_on_the_next_tick(
    tmp_path: Path,
) -> None:
    svc, data_dir, backup_root = _service(tmp_path)
    _make_sqlite_db(data_dir / "payload.db")
    stale = backup_root / f"20200101-000000{INCOMPLETE_SUFFIX}"
    (stale / "data").mkdir(parents=True)
    (stale / "data" / "torn.db").write_bytes(b"half a copy")

    result = svc.snapshot()

    assert result.succeeded is True
    assert not stale.exists(), "a crashed tick's working directory was never collected"
    assert sorted(p.name for p in backup_root.iterdir()) == [
        Path(result.snapshot_dir).name
    ]


# ---------------------------------------------------------------------------
# 14-18: what verify_snapshot proves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_promoted_snapshot_verifies_and_every_file_opens(tmp_path: Path) -> None:
    svc, data_dir, _ = _service(tmp_path)
    _make_sqlite_db(data_dir / "alpha.db")
    _make_sqlite_db(data_dir / "nested" / "beta.db", rows=3)

    result = svc.snapshot()
    assert result.succeeded is True

    report = await verify_snapshot(Path(result.snapshot_dir))
    assert report.ok is True, report.render()
    assert report.refused_reason == ""
    assert sorted(v.label for v in report.verdicts) == [
        "data/alpha.db", "data/nested/beta.db",
    ]
    assert all(v.ok for v in report.verdicts)


@pytest.mark.asyncio
async def test_a_same_length_payload_edit_is_caught_by_the_digest(
    tmp_path: Path,
) -> None:
    """The exact ``TAMPERED`` case ``PRAGMA integrity_check`` passed.

    A same-length edit inside a page leaves the file structurally valid, so
    the structural check cannot see it. Only the recorded digest can.
    """
    svc, data_dir, _ = _service(tmp_path)
    _make_sqlite_db(data_dir / "alpha.db", rows=4)
    result = svc.snapshot()
    assert result.succeeded is True

    victim = Path(result.snapshot_dir) / "data" / "alpha.db"
    before = victim.stat().st_size
    raw = bytearray(victim.read_bytes())
    marker = raw.find(b"v0")
    assert marker != -1, "test fixture no longer contains the payload it edits"
    raw[marker:marker + 2] = b"XX"
    victim.write_bytes(bytes(raw))
    assert victim.stat().st_size == before, "the edit must be same-length"

    # PREMISE ASSERTION: the structural check still passes, so a failure below
    # can only have come from the digest.
    conn = sqlite3.connect(str(victim))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    report = await verify_snapshot(Path(result.snapshot_dir))
    assert report.ok is False
    assert [v.label for v in report.failed] == ["data/alpha.db"]
    assert "sha256" in report.failed[0].reason


@pytest.mark.asyncio
async def test_replacing_a_file_with_a_different_valid_sqlite_db_is_caught(
    tmp_path: Path,
) -> None:
    """D3: verification must never be able to take a path that skips the digest.

    AD-1262 chose its method by inspecting the artifact -- a valid SQLite
    header meant "use integrity_check", so swapping in a healthy but *wrong*
    database passed. The manifest is authoritative now.
    """
    svc, data_dir, _ = _service(tmp_path)
    _make_sqlite_db(data_dir / "alpha.db", rows=4)
    result = svc.snapshot()
    assert result.succeeded is True

    victim = Path(result.snapshot_dir) / "data" / "alpha.db"
    imposter = tmp_path / "imposter.db"
    _make_sqlite_db(imposter, rows=4)
    # Pad to the same length so the cheap size check cannot be what catches it.
    blob = bytearray(imposter.read_bytes())
    target_size = victim.stat().st_size
    if len(blob) < target_size:
        blob.extend(b"\x00" * (target_size - len(blob)))
    victim.write_bytes(bytes(blob[:target_size]))
    assert victim.stat().st_size == target_size

    # PREMISE ASSERTION: the replacement really is a structurally valid
    # SQLite database, which is the whole point of the finding.
    conn = sqlite3.connect(str(victim))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()

    report = await verify_snapshot(Path(result.snapshot_dir))
    assert report.ok is False
    assert [v.label for v in report.failed] == ["data/alpha.db"]
    assert "sha256" in report.failed[0].reason


def test_a_digest_that_cannot_be_computed_marks_the_entry_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never a present-but-undigested entry.

    AD-1262 swallowed the failure into an opaque entry with no digest,
    promoted the snapshot as complete, and left restore to refuse it later.
    Recorded-but-unverified is the failure class.
    """
    svc, data_dir, backup_root = _service(tmp_path)
    _make_sqlite_db(data_dir / "alpha.db")

    import probos.infrastructure.backup as backup_module

    def _no_digest(path: Path, **kwargs: object) -> str:
        raise OSError("cannot read for digest (simulated)")

    monkeypatch.setattr(backup_module, "sha256_file", _no_digest)
    result = svc.snapshot()

    assert result.succeeded is False
    assert result.files_failed == ["data/alpha.db"]
    dirs = [p for p in backup_root.iterdir() if p.is_dir()]
    assert len(dirs) == 1 and dirs[0].name.endswith(INCOMPLETE_SUFFIX)
    manifest = read_manifest(dirs[0])
    assert manifest is not None
    assert manifest.present == []
    assert [e.state for e in manifest.entries] == ["failed"]


def test_a_present_entry_without_a_digest_cannot_be_constructed() -> None:
    """The structural half of the same rule (defence in depth)."""
    with pytest.raises(ValueError, match="no sha256"):
        ManifestEntry(label="data/x.db", tier="included", state=STATE_COPIED)


@pytest.mark.asyncio
async def test_verify_snapshot_refuses_a_manifestless_ad466_era_directory(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "20260101-000000"
    _make_sqlite_db(legacy / "events.db")

    report = await verify_snapshot(legacy)
    assert report.ok is False
    assert "manifest" in report.refused_reason


@pytest.mark.asyncio
async def test_verify_snapshot_refuses_a_manifest_that_records_a_failure(
    tmp_path: Path,
) -> None:
    incomplete = tmp_path / "20260101-000001"
    _make_sqlite_db(incomplete / "data" / "alpha.db")
    write_manifest(
        incomplete,
        SnapshotManifest(
            snapshot=incomplete.name, created_at=time.time(),
            entries=[
                ManifestEntry(
                    label="data/beta.db", tier="included", state="failed",
                    error="disk full",
                )
            ],
        ),
    )

    report = await verify_snapshot(incomplete)
    assert report.ok is False
    assert "failed entry" in report.refused_reason


@pytest.mark.asyncio
async def test_verify_snapshot_reports_an_absent_file(tmp_path: Path) -> None:
    svc, data_dir, _ = _service(tmp_path)
    _make_sqlite_db(data_dir / "alpha.db")
    result = svc.snapshot()
    assert result.succeeded is True

    (Path(result.snapshot_dir) / "data" / "alpha.db").unlink()
    report = await verify_snapshot(Path(result.snapshot_dir))

    assert report.ok is False
    assert report.failed[0].reason == "absent from the snapshot"


def test_read_manifest_returns_none_for_malformed_json(tmp_path: Path) -> None:
    snapshot = tmp_path / "20260101-000002"
    snapshot.mkdir()
    (snapshot / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    assert read_manifest(snapshot) is None


def test_read_manifest_refuses_a_manifest_whose_present_entry_lost_its_digest(
    tmp_path: Path,
) -> None:
    """A hand-edited manifest cannot smuggle in an undigested present entry."""
    snapshot = tmp_path / "20260101-000003"
    snapshot.mkdir()
    (snapshot / MANIFEST_NAME).write_text(
        json.dumps({
            "schema": 2,
            "snapshot": snapshot.name,
            "created_at": time.time(),
            "complete": True,
            "entries": [{
                "label": "data/alpha.db", "tier": "included",
                "state": STATE_COPIED, "size_bytes": 4096, "sha256": "",
            }],
        }),
        encoding="utf-8",
    )
    assert read_manifest(snapshot) is None
