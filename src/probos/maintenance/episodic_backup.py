"""AD-823: daily episodic backup snapshot.

Third-line recovery primitive for the episodic store. Pairs with:

* AD-819 (``rebuild-episodic``): rebuild ChromaDB from surviving ward
  room threads when chroma is corrupt but the ward room is intact.
* AD-822 (``episodic_health``): refuse to boot when chroma is corrupt,
  pointing the operator at AD-819 or AD-823 for recovery.

This module is **not** prevention — corruption that happens between
snapshots is still lost. It's the fallback for the case where both
chroma and the ward room journal are gone (disk failure, accidental
``rm -rf data/``, external sync corruption).

What the snapshot captures:
    * ``data_dir/chroma.sqlite3`` — chroma's metadata store.
    * Every UUID-named subdirectory of ``data_dir`` that contains an
      HNSW marker file (``header.bin``). Those are chroma's per-collection
      index directories.

What the snapshot does NOT capture:
    * ``events.db``, ``journal.db``, ``ward_room.db`` — these have their
      own retention policies (BF-071 prune loops) and are not in scope
      for AD-823.
    * Attachment blobs, audio cache, knowledge store — also out of scope.

Format: uncompressed ``.tar`` (speed > space; local-only recovery store).

File naming: ``backups_dir/episodic-YYYY-MM-DD.tar``. Same-day re-runs are
idempotent (skip-if-exists).

Retention: delete ``episodic-*.tar`` files older than ``retain_days`` days
(default 7) after a successful snapshot. The cleanup runs only on success
so a failed snapshot doesn't take older healthy backups down with it.
"""

from __future__ import annotations

import logging
import re
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from probos.episodic_health import check_episodic_health

logger = logging.getLogger(__name__)

# Chroma's UUID collection directories use the standard 8-4-4-4-12 hex
# layout. Match defensively rather than parsing chroma internals.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_HNSW_MARKER = "header.bin"
_BACKUP_NAME_RE = re.compile(r"^episodic-(\d{4}-\d{2}-\d{2})\.tar$")


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    path: Path | None
    bytes_written: int
    skipped_reason: str | None


def _find_chroma_artifacts(data_dir: Path) -> list[Path]:
    """Return absolute paths of chroma's on-disk footprint inside data_dir.

    Includes ``chroma.sqlite3`` (if present) and every UUID-named
    subdirectory whose contents look like a chroma HNSW collection
    (presence of ``header.bin``).
    """
    artifacts: list[Path] = []
    sqlite_path = data_dir / "chroma.sqlite3"
    if sqlite_path.exists():
        artifacts.append(sqlite_path)
    for child in data_dir.iterdir():
        if not child.is_dir():
            continue
        if not _UUID_RE.match(child.name):
            continue
        if (child / _HNSW_MARKER).exists():
            artifacts.append(child)
    return artifacts


def snapshot_episodic(
    data_dir: Path,
    backups_dir: Path,
    *,
    retain_days: int = 7,
    today: datetime | None = None,
) -> SnapshotResult:
    """Snapshot chroma's on-disk footprint to ``backups_dir``.

    Args:
        data_dir: per-instance data directory (chroma lives at root).
        backups_dir: where to write ``episodic-YYYY-MM-DD.tar``.
        retain_days: delete older snapshots after a successful new one.
            Clamp to ``>=1`` at the caller (config validation enforces).
        today: override the date stamp (testing seam). Defaults to UTC now.

    Returns:
        :class:`SnapshotResult`. ``ok=True`` on either successful new
        snapshot OR same-day skip. ``ok=False`` when the source is
        unopenable or unwritable.
    """
    data_dir = Path(data_dir)
    backups_dir = Path(backups_dir)

    today = today or datetime.now(timezone.utc)
    stamp = today.strftime("%Y-%m-%d")
    target = backups_dir / f"episodic-{stamp}.tar"

    if target.exists():
        logger.info(
            "AD-823: snapshot %s already exists; skipping", target,
        )
        return SnapshotResult(
            ok=True,
            path=target,
            bytes_written=0,
            skipped_reason="already-exists",
        )

    if not data_dir.exists():
        logger.info(
            "AD-823: data_dir %s does not exist; skipping snapshot", data_dir,
        )
        return SnapshotResult(
            ok=True, path=None, bytes_written=0,
            skipped_reason="data-dir-missing",
        )

    # Open-probe fallback (no lock file exists; AD-822 probe gives us a
    # cheap subprocess-isolated openability check). If the store is
    # corrupt, taring it would just snapshot the corruption. Skip with a
    # reason and let AD-822 surface the corruption on next boot.
    health = check_episodic_health(data_dir, timeout_s=30.0)
    if not health.ok:
        logger.warning(
            "AD-823: skipping snapshot — episodic health probe failed: %s",
            health.error,
        )
        return SnapshotResult(
            ok=False, path=None, bytes_written=0,
            skipped_reason=f"health-probe-failed: {health.error}",
        )

    artifacts = _find_chroma_artifacts(data_dir)
    if not artifacts:
        logger.info(
            "AD-823: no chroma artifacts found in %s; nothing to snapshot",
            data_dir,
        )
        return SnapshotResult(
            ok=True, path=None, bytes_written=0,
            skipped_reason="no-artifacts",
        )

    backups_dir.mkdir(parents=True, exist_ok=True)
    tmp_target = target.with_suffix(target.suffix + ".tmp")

    try:
        with tarfile.open(tmp_target, mode="w") as tar:
            for artifact in artifacts:
                # arcname relative to data_dir so restore can untar
                # straight back into data_dir/.
                arcname = artifact.relative_to(data_dir)
                tar.add(str(artifact), arcname=str(arcname))
        tmp_target.replace(target)
    except (OSError, tarfile.TarError) as exc:
        logger.error(
            "AD-823: snapshot write failed for %s: %r", target, exc,
        )
        try:
            tmp_target.unlink(missing_ok=True)
        except OSError:
            pass
        return SnapshotResult(
            ok=False, path=None, bytes_written=0,
            skipped_reason=f"write-failed: {exc!r}",
        )

    bytes_written = target.stat().st_size
    logger.info(
        "AD-823: snapshot %s written (%d bytes, %d artifacts)",
        target, bytes_written, len(artifacts),
    )

    # Retention: only after a successful write. Failures upstream
    # MUST NOT delete older backups.
    _prune_old_snapshots(backups_dir, retain_days=retain_days, today=today)

    return SnapshotResult(
        ok=True, path=target,
        bytes_written=bytes_written, skipped_reason=None,
    )


def _prune_old_snapshots(
    backups_dir: Path,
    *,
    retain_days: int,
    today: datetime,
) -> None:
    """Delete ``episodic-*.tar`` files older than retain_days."""
    cutoff = today.timestamp() - (retain_days * 86400)
    for child in backups_dir.iterdir():
        m = _BACKUP_NAME_RE.match(child.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue
        if file_date.timestamp() < cutoff:
            try:
                child.unlink()
                logger.info(
                    "AD-823: pruned old snapshot %s (older than %d days)",
                    child, retain_days,
                )
            except OSError:
                logger.warning(
                    "AD-823: failed to prune old snapshot %s", child,
                    exc_info=True,
                )
