"""AD-823: daily episodic backup task tests."""

from __future__ import annotations

import asyncio
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.config import MemoryConfig
from probos.maintenance.episodic_backup import (
    SnapshotResult,
    snapshot_episodic,
)


def _build_real_chroma_store(data_dir: Path) -> None:
    """Build a real chromadb PersistentClient with a row so artifacts exist."""
    import chromadb

    client = chromadb.PersistentClient(path=str(data_dir))
    coll = client.get_or_create_collection(name="episodes")
    coll.add(
        ids=["row-1"],
        documents=["hello world"],
        metadatas=[{"k": "v"}],
        embeddings=[[0.1, 0.2, 0.3]],
    )
    # Force flush so HNSW header.bin is written.
    del coll
    del client


def test_snapshot_creates_tar_with_expected_artifacts(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backups_dir = tmp_path / "backups"
    _build_real_chroma_store(data_dir)

    result = snapshot_episodic(data_dir, backups_dir)

    assert result.ok is True
    assert result.path is not None
    assert result.path.exists()
    assert result.bytes_written > 0

    with tarfile.open(result.path, mode="r") as tar:
        names = tar.getnames()

    assert "chroma.sqlite3" in names
    # At least one UUID dir entry with header.bin
    header_entries = [n for n in names if n.endswith("header.bin")]
    assert len(header_entries) >= 1


def test_same_day_snapshot_skipped(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backups_dir = tmp_path / "backups"
    _build_real_chroma_store(data_dir)

    fixed_today = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)

    first = snapshot_episodic(data_dir, backups_dir, today=fixed_today)
    assert first.ok is True
    assert first.path is not None
    first_mtime = first.path.stat().st_mtime

    # Ensure any FS-level mtime change would be detectable.
    time.sleep(0.05)

    second = snapshot_episodic(data_dir, backups_dir, today=fixed_today)
    assert second.ok is True
    assert second.skipped_reason == "already-exists"
    assert second.path == first.path
    assert second.path.stat().st_mtime == first_mtime


def test_retention_deletes_old_files_keeps_new(tmp_path: Path) -> None:
    # No chroma in this test — populate backups dir manually and call the
    # snapshot path that succeeds (data-dir-missing skip is ok=True but
    # does NOT trigger retention pruning). Instead, build chroma to take
    # the success branch and verify pruning happens.
    pytest.importorskip("chromadb")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()

    old_a = backups_dir / "episodic-2026-04-01.tar"
    old_b = backups_dir / "episodic-2026-04-15.tar"
    recent = backups_dir / "episodic-2026-05-19.tar"
    for p in (old_a, old_b, recent):
        p.write_bytes(b"")

    _build_real_chroma_store(data_dir)

    today = datetime(2026, 5, 22, tzinfo=timezone.utc)
    result = snapshot_episodic(
        data_dir, backups_dir, retain_days=7, today=today,
    )

    assert result.ok is True
    assert not old_a.exists()
    assert not old_b.exists()
    assert recent.exists()
    # And the new snapshot exists.
    assert (backups_dir / "episodic-2026-05-22.tar").exists()


def test_open_probe_failure_skips_snapshot(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backups_dir = tmp_path / "backups"

    # Write garbage so the AD-822 probe fails.
    (data_dir / "chroma.sqlite3").write_bytes(b"this is not a sqlite database")

    result = snapshot_episodic(data_dir, backups_dir)

    assert result.ok is False
    assert result.path is None
    assert result.skipped_reason is not None
    assert "health-probe-failed" in result.skipped_reason
    # No tar written.
    if backups_dir.exists():
        assert not any(backups_dir.glob("episodic-*.tar"))


def test_no_artifacts_returns_skip_reason(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backups_dir = tmp_path / "backups"

    result = snapshot_episodic(data_dir, backups_dir)

    # Health probe on an empty dir succeeds (chroma opens a fresh store),
    # but no artifacts exist to back up.
    assert result.ok is True
    assert result.skipped_reason == "no-artifacts"
    assert result.path is None


def test_config_validation_retain_days_bounds() -> None:
    with pytest.raises(ValidationError):
        MemoryConfig(backup_retain_days=0)
    with pytest.raises(ValidationError):
        MemoryConfig(backup_retain_days=400)
    cfg = MemoryConfig(backup_retain_days=7)
    assert cfg.backup_retain_days == 7
    assert cfg.backup_enabled is True


def test_backup_disabled_loop_exits(tmp_path: Path) -> None:
    """When backup_enabled=False, the loop must exit before the 60s warmup."""
    from probos.config import SystemConfig

    cfg = SystemConfig()
    cfg.memory.backup_enabled = False

    # Build a minimal stand-in object that exposes the attributes the
    # loop reads: self.config, self._data_dir. Avoid MagicMock per
    # BF-287 (phantom-attribute trap) and BF-722b-1a (real-config rule).
    class _RuntimeStub:
        def __init__(self, config: SystemConfig, data_dir: Path) -> None:
            self.config = config
            self._data_dir = data_dir

    stub = _RuntimeStub(cfg, tmp_path)

    # Reuse the unbound coroutine function on the stub.
    from probos.runtime import ProbOSRuntime

    coro = ProbOSRuntime._episodic_backup_loop(stub)  # type: ignore[arg-type]

    async def _run() -> None:
        await asyncio.wait_for(coro, timeout=2.0)

    # Should complete in well under 2s — no warmup sleep when disabled.
    asyncio.run(_run())
