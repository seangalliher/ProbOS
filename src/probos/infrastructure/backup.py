"""AD-466 / AD-1265: BackupService -- self-sufficient point-in-time snapshots.

AD-466 wired this service at startup and *nothing ever called it* (BF-842):
three writes to ``runtime.backup_service`` in ``finalize.py``, zero reads
anywhere in ``src/``, and a class docstring that named the gap outright.
AD-1265 supplies the scheduler (``ProbOSRuntime._sqlite_backup_loop``), the
manifest, promotion-by-rename, and retention.

Two invariants carry most of the weight:

* **Every snapshot is self-sufficient.** There is no tier a tick may skip and
  no reference to a sibling snapshot. A directory that is only restorable in
  combination with another directory is not a snapshot -- it breaks every
  operator instinct (copy this folder to safety, ship it to another host,
  keep the one from before the bad migration) and it breaks them silently.
* **Promotion is the atomic rename, and nothing else means complete.** The
  snapshot is built in ``<ts>.incomplete`` and becomes ``<ts>`` only once
  every due file landed and the manifest was fsynced. An observer either sees
  no ``<ts>`` at all or sees a whole one.

Hard-linking (the ``IMMUTABLE`` optimization) is *not* the carry-forward that
AD-1262 shipped, and confusing the two is why that AD was reverted:

    A hard link is data-present. A ``bulk_source`` reference is data-absent.
    Pruning the snapshot a hard link was sourced from does not destroy the
    bytes (link count > 1). Pruning the snapshot a reference names destroys
    the data.
"""

from __future__ import annotations

import calendar
import contextlib
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.events import EventType
from probos.infrastructure.backup_inventory import (
    BackupRoot,
    BackupTier,
    DiscoveredDatabase,
    discover,
)
from probos.infrastructure.snapshot_manifest import (
    INCOMPLETE_SUFFIX,
    STATE_COPIED,
    STATE_FAILED,
    STATE_LINKED,
    ManifestEntry,
    SnapshotManifest,
    read_manifest,
    sha256_file,
    write_manifest,
)

logger = logging.getLogger(__name__)

#: ``20260824-061728`` plus the optional ``-123456`` collision suffix.
#: Matches **promoted** names only -- ``<ts>.incomplete`` deliberately fails
#: it, so retention cannot see one and hard-linking cannot source from one.
_SNAPSHOT_DIR_RE = re.compile(r"^(\d{8}-\d{6})(?:-\d{6})?$")

_DEFAULT_RETAIN_DAYS = 3
_DEFAULT_MAX_TOTAL_BYTES = 8 * 1024**3
#: Half ``_DEFAULT_MAX_TOTAL_BYTES``. See ``InfrastructureConfig``.
_DEFAULT_ORPHAN_ALERT_BYTES = 4 * 1024**3

#: ``<ts>[-<micros>].<pid>-<runid>.incomplete``. The owner is in the *name*, so
#: it is present the instant the directory exists and cannot be truncated,
#: emptied or made unreadable. AD-1265 kept it in an ``owner.json`` instead;
#: review then measured a zero-byte marker reading as abandoned and the sweep
#: removing a directory another process held open. A name has no parse-failure
#: mode, so that branch does not exist here.
_WORKING_DIR_RE = re.compile(
    r"^(\d{8}-\d{6}(?:-\d{6})?)\.(\d+)-([0-9a-f]{8})" + re.escape(INCOMPLETE_SUFFIX) + r"$"
)

_LIVE_LOCK = threading.Lock()
#: Run ids this process is writing *right now*. Two BackupService instances in
#: one process share a PID, so the PID alone cannot tell a live sibling's
#: directory from one an earlier tick left behind; this can.
#:
#: Keyed on the run id, not the path. AD-1265 keyed it on the path and two
#: attempts racing for the same ``<ts>`` therefore shared one key, so the
#: loser's release revoked the winner's claim and the sweep ate a live
#: directory -- a defect reached from inside the fix for it. A run id is unique
#: per attempt by construction, so two attempts can never collide on a key and
#: no reference counting is needed. They also no longer contend for a directory
#: name at all: each gets its own.
_LIVE_RUNS: set[str] = set()


def _run_begin(run_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE_RUNS.add(run_id)


def _run_end(run_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE_RUNS.discard(run_id)


def _run_is_live(run_id: str) -> bool:
    with _LIVE_LOCK:
        return run_id in _LIVE_RUNS


@dataclass(frozen=True)
class BackupResult:
    """Result of a backup snapshot.

    ``succeeded`` means **promoted**: every discovered file landed, passed
    ``PRAGMA integrity_check``, was digested, the manifest was written and
    fsynced, and the directory was renamed out of ``.incomplete``. It is not
    "something copied" -- that shape (``succeeded = bool(files_copied)``) is
    the defect the manifest exists to close.
    """

    succeeded: bool
    snapshot_dir: str
    files_copied: list[str] = field(default_factory=list)
    bytes_copied: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    # AD-1265 additive fields.
    files_linked: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    snapshot_promoted: bool = False
    pruned_dirs: list[str] = field(default_factory=list)
    #: ``"days"`` or ``"bytes"`` -- which bound actually decided retention.
    retention_bound: str = ""
    #: Where the bytes are when a tick did not promote. The directory is kept
    #: rather than deleted so the failure can be inspected, and it is swept by
    #: a later tick.
    incomplete_dir: str = ""
    #: Working directories left alone because ownership could not be proven.
    orphaned_working_dirs: list[str] = field(default_factory=list)
    orphaned_bytes: int = 0
    #: Whether the orphan sweep actually ran. A tick that fails before the
    #: sweep reports ``orphaned_bytes = 0`` because nothing was counted, not
    #: because nothing was there, and an aggregate over ticks would otherwise
    #: read "not measured" as "no leak".
    orphans_measured: bool = False


@dataclass(frozen=True)
class PruneResult:
    """Outcome of one retention sweep over ``backup_root``."""

    pruned_dirs: list[str] = field(default_factory=list)
    bytes_freed: int = 0
    retained_dirs: int = 0
    errors: list[str] = field(default_factory=list)
    #: Which bound removed something: ``""`` (nothing pruned), ``"days"``, or
    #: ``"bytes"`` when the ceiling took anything the age rule would have kept.
    bound: str = ""


@dataclass
class SweepResult:
    """What one working-directory sweep reclaimed, and what it refused to."""

    reclaimed_dirs: list[str] = field(default_factory=list)
    #: Working directories this process cannot prove are finished. Kept, never
    #: deleted, and reported so the leak is not silent. See AD-1296 D3.
    foreign_dirs: list[str] = field(default_factory=list)
    foreign_bytes: int = 0


def parse_snapshot_timestamp(name: str) -> float | None:
    """Epoch seconds encoded in a promoted snapshot directory name, or None."""
    match = _SNAPSHOT_DIR_RE.match(name)
    if not match:
        return None
    try:
        return float(calendar.timegm(time.strptime(match.group(1), "%Y%m%d-%H%M%S")))
    except ValueError:
        return None


def is_promoted_snapshot_name(name: str) -> bool:
    """Whether ``name`` is a promoted snapshot directory name (AD-1265 D4).

    Any consumer that admits a snapshot must admit it **by name first**: an
    operator-supplied path whose final component fails this is refused before
    its manifest is even read, because a hand-built ``.incomplete`` directory
    can contain a perfectly valid ``complete=true`` manifest.
    """
    return _SNAPSHOT_DIR_RE.match(name) is not None


class BackupService:
    """Point-in-time snapshots of the SQLite databases under a set of roots.

    Stateless on construction. Each :meth:`snapshot` writes one timestamped
    directory under ``backup_root`` and, on promotion, runs :meth:`prune`.

    Scheduling lives in ``ProbOSRuntime._sqlite_backup_loop`` (AD-1265),
    which calls :meth:`snapshot` through ``asyncio.to_thread`` -- the method
    is synchronous and does blocking multi-hundred-MB file I/O.
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        backup_root: Path,
        emit_event: Any | None = None,
        roots: Sequence[BackupRoot] | None = None,
        retain_days: int = _DEFAULT_RETAIN_DAYS,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
        orphan_alert_bytes: int = _DEFAULT_ORPHAN_ALERT_BYTES,
    ) -> None:
        self._data_dir = data_dir
        self._backup_root = backup_root
        self._emit_event = emit_event
        # AD-466 callers pass only data_dir; synthesize the single root they
        # implied so the original construction still works.
        self._roots: tuple[BackupRoot, ...] = (
            tuple(roots) if roots else (BackupRoot("data", data_dir),)
        )
        self._retain_days = retain_days
        self._max_total_bytes = max_total_bytes
        # Deliberately NOT folded into ``_max_total_bytes``: orphans are
        # invisible to ``prune`` and charging them to the byte ceiling would
        # prune healthy promoted snapshots and blame retention for a leak
        # retention cannot reach (AD-1296 D4).
        self._orphan_alert_bytes = orphan_alert_bytes

    @property
    def roots(self) -> tuple[BackupRoot, ...]:
        return self._roots

    def snapshot(self) -> BackupResult:
        """Take one point-in-time snapshot. Returns a result either way.

        The snapshot is built in ``<ts>.incomplete`` and renamed to ``<ts>``
        only when every discovered file landed, verified and digested. A
        per-file failure keeps the copied bytes (they stay in the
        ``.incomplete`` directory for inspection) but forfeits promotion,
        ``BACKUP_COMPLETE`` and retention -- because a snapshot missing a file
        it was due to hold restores a vessel whose other databases have moved
        on, and does so while reporting success.
        """
        started = time.time()
        run_id = uuid.uuid4().hex[:8]

        # Registered before the directory exists, never after: the sweep must
        # never see a directory of ours whose run is not yet marked live.
        _run_begin(run_id)
        try:
            working_dir, final_dir, failure = self._make_snapshot_dir(started, run_id)
            if working_dir is None or final_dir is None:
                return self._fail(failure[0], started, failure[1])
            return self._write_snapshot(started, working_dir, final_dir)
        finally:
            # Retired on every path out -- promoted, failed or raised. Leaving
            # one live would make this run's directory immortal.
            _run_end(run_id)

    def _write_snapshot(
        self, started: float, working_dir: Path, final_dir: Path,
    ) -> BackupResult:
        """Fill ``working_dir`` and promote it. Its run id is live in the caller."""
        sweep = self._sweep_incomplete(exclude=working_dir)

        files_copied: list[str] = []
        files_linked: list[str] = []
        files_failed: list[str] = []
        entries: list[ManifestEntry] = []
        bytes_copied = 0
        try:
            prior_dir, prior_started = self._prior_promoted_snapshot()
            for entry in discover(self._roots, backup_root=self._backup_root):
                label = str(entry.snapshot_relative_path)
                dest = working_dir / entry.snapshot_relative_path
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    linked = False
                    if entry.tier is BackupTier.IMMUTABLE:
                        linked = self._try_link(entry, dest, prior_dir, prior_started)
                    if not linked:
                        self._backup_one(entry.absolute_path, dest)
                        if entry.tier is BackupTier.IMMUTABLE:
                            # Neither sqlite3.backup nor shutil.copyfile carries
                            # mtime across, so without this the next snapshot's
                            # (size, mtime_ns) comparison could never match and
                            # the link path would be dead code.
                            self._preserve_mtime(entry.absolute_path, dest)
                    described = self._describe(
                        label, entry.tier,
                        STATE_LINKED if linked else STATE_COPIED, dest,
                    )
                    entries.append(described)
                    if linked:
                        files_linked.append(label)
                    else:
                        files_copied.append(label)
                        bytes_copied += described.size_bytes
                except Exception as exc:
                    files_failed.append(label)
                    entries.append(
                        ManifestEntry(
                            label=label, tier=entry.tier.value,
                            state=STATE_FAILED, error=str(exc),
                        )
                    )
                    logger.warning(
                        "AD-1265: backup of %s failed (%s); snapshot %s will NOT "
                        "be promoted -- an incomplete snapshot that restores "
                        "reads as protection it cannot give",
                        entry.absolute_path, exc, working_dir,
                    )
        except Exception as exc:
            logger.error(
                "AD-1265: backup snapshot failed (working_dir=%s, files_copied=%d): %s",
                working_dir, len(files_copied), exc,
            )
            return self._fail(
                str(working_dir), started, str(exc),
                incomplete_dir=str(working_dir), sweep=sweep,
            )

        manifest = SnapshotManifest(
            snapshot=final_dir.name, created_at=started, entries=entries,
        )
        promoted: Path | None = None
        promote_error = ""
        try:
            write_manifest(working_dir, manifest)
        except OSError as exc:
            promote_error = f"manifest write failed: {exc}"
            logger.error(
                "AD-1265: could not write the manifest in %s (%s); the snapshot "
                "cannot be shown to be whole and is not promoted",
                working_dir, exc,
            )
        else:
            if manifest.complete:
                try:
                    promoted = self._promote(working_dir, final_dir)
                except OSError as exc:
                    promote_error = f"promotion failed: {exc}"
                    logger.error(
                        "AD-1265: could not promote %s to %s (%s); the bytes stay "
                        "in the incomplete directory and no BACKUP_COMPLETE is emitted",
                        working_dir, final_dir, exc,
                    )

        succeeded = promoted is not None
        pruned: list[str] = []
        retention_bound = ""
        if succeeded:
            prune_result = self.prune()
            pruned = prune_result.pruned_dirs
            retention_bound = prune_result.bound

        if files_failed:
            error = f"{len(files_failed)} due file(s) failed: {', '.join(files_failed)}"
        else:
            error = promote_error

        result = BackupResult(
            succeeded=succeeded,
            snapshot_dir=str(promoted or working_dir),
            files_copied=files_copied,
            bytes_copied=bytes_copied,
            duration_seconds=time.time() - started,
            error=error,
            files_linked=files_linked,
            files_failed=files_failed,
            snapshot_promoted=succeeded,
            pruned_dirs=pruned,
            retention_bound=retention_bound,
            incomplete_dir="" if succeeded else str(working_dir),
            orphaned_working_dirs=list(sweep.foreign_dirs),
            orphaned_bytes=sweep.foreign_bytes,
            orphans_measured=True,
        )
        if succeeded:
            self._emit_complete(result)
        else:
            self._emit_failed(result)
        return result

    # ------------------------------------------------------------------
    # retention
    # ------------------------------------------------------------------

    def prune(self) -> PruneResult:
        """Enforce ``retain_days`` then ``max_total_bytes``, oldest-first.

        Only **promoted** directories are enumerated; ``.incomplete`` is
        invisible to retention because it is not a snapshot and pruning one
        would race the tick that is writing it.

        The newest promoted snapshot is never pruned, even when it alone
        exceeds the byte ceiling. A retention policy that can prune itself to
        zero is worse than none, because it still reads as protection.

        Hard-linked immutables need no special handling: pruning the snapshot
        a link was sourced from does not destroy bytes still linked elsewhere
        (link count > 1). Do not add any.

        Byte accounting sums ``st_size`` per snapshot, so a hard-linked file
        is counted once per snapshot rather than once on disk. That
        over-estimates, which is the safe direction for a ceiling.
        """
        snapshots = self._existing_snapshots()
        if len(snapshots) <= 1:
            return PruneResult(retained_dirs=len(snapshots))

        sizes = {path: self._dir_size(path) for path, _ in snapshots}
        # The last element is the newest and is never a candidate.
        candidates = [path for path, _ in snapshots[:-1]]
        doomed: list[Path] = []

        cutoff = time.time() - (self._retain_days * 86400)
        for path, ts in snapshots[:-1]:
            if ts < cutoff:
                doomed.append(path)
        aged_out = len(doomed)

        remaining = sum(sizes.values()) - sum(sizes[p] for p in doomed)
        for path in candidates:
            if remaining <= self._max_total_bytes:
                break
            if path in doomed:
                continue
            doomed.append(path)
            remaining -= sizes[path]
        bytes_bound_took = len(doomed) - aged_out

        if bytes_bound_took:
            # AD-1265 D2: a ceiling that quietly overrides the stated policy is
            # how the AD-1262 default became a lie. Announce the valve.
            kept = len(snapshots) - len(doomed)
            logger.warning(
                "AD-1265: retention pruned %d snapshot(s) for the byte ceiling "
                "that retain_days would have kept (retain_days=%d, "
                "max_total_bytes=%d); effective retention is %d tick(s). Raise "
                "max_total_bytes or lengthen the cadence -- retain_days is not "
                "what is binding here",
                bytes_bound_took, self._retain_days, self._max_total_bytes, kept,
            )

        pruned: list[str] = []
        errors: list[str] = []
        freed = 0
        for path in doomed:
            try:
                shutil.rmtree(path)
            except OSError as exc:
                errors.append(f"{path}: {exc}")
                logger.warning(
                    "AD-1265: failed to prune snapshot %s (%s); it stays on disk "
                    "and counts against the byte ceiling next sweep",
                    path, exc,
                )
                continue
            pruned.append(str(path))
            freed += sizes[path]
            logger.info(
                "AD-1265: pruned snapshot %s (retain_days=%d, max_total_bytes=%d)",
                path, self._retain_days, self._max_total_bytes,
            )
        bound = ""
        if pruned:
            bound = "bytes" if bytes_bound_took else "days"
        return PruneResult(
            pruned_dirs=pruned,
            bytes_freed=freed,
            retained_dirs=len(snapshots) - len(pruned),
            errors=errors,
            bound=bound,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _make_snapshot_dir(
        self, started: float, run_id: str,
    ) -> tuple[Path | None, Path | None, tuple[str, str]]:
        """Create this run's private working directory and pick its promoted name.

        One ``mkdir``. No staging directory and no reservation rename: the name
        carries the owner, so it is never briefly unowned, and two peers in the
        same second get different directories instead of racing for one.

        ``final_dir`` is only *chosen* here. Promotion is what claims it, and
        ``os.replace`` refuses a directory onto an existing directory, so a peer
        that picks the same name loses at promotion and degrades down the
        already-tested ``promote_error`` path. The reservation this replaces
        bought one avoided wasted build and cost every failure in AD-1296 D1.
        """
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started))
        for base in (
            timestamp,
            f"{timestamp}-{int((started % 1) * 1_000_000):06d}",
        ):
            final_dir = self._backup_root / base
            if final_dir.exists():
                continue
            working_dir = (
                self._backup_root
                / f"{base}.{os.getpid()}-{run_id}{INCOMPLETE_SUFFIX}"
            )
            try:
                working_dir.mkdir(parents=True, exist_ok=False)
            except OSError as exc:
                return None, None, (str(working_dir), f"mkdir failed: {exc}")
            return working_dir, final_dir, ("", "")
        return None, None, (
            str(self._backup_root / timestamp),
            "mkdir failed: both the timestamped and collision-suffixed names exist",
        )

    @staticmethod
    def _promote(working_dir: Path, final_dir: Path) -> Path:
        """Rename the working directory to its timestamped name.

        This, and only this, means promoted. A directory rename is the atomic
        step: an observer either sees no ``<ts>`` at all or sees a complete
        one. Copying files into ``<ts>`` directly would make every
        partially-written snapshot visible under a name that reads as
        finished, and process death between "manifest written" and "promoted"
        would leave exactly that on disk.
        """
        os.replace(working_dir, final_dir)
        return final_dir

    def _sweep_incomplete(self, *, exclude: Path) -> SweepResult:
        """Reclaim this process's finished working directories. Nothing else.

        A working directory can never be admitted -- promotion is the sole
        marker of completeness -- so one left behind is pure cost. But AD-1265
        measured what reclaiming aggressively costs: a peer's sweep deleted a
        live service's directory and the victim failed ``ENOENT`` mid-copy,
        and a zero-byte ownership marker was enough to make a held-open
        directory read as abandoned.

        So this sweep answers only the question it can answer exactly. A
        directory naming *this* PID and a run id this process is not currently
        writing is finished, with certainty, from memory, with no syscall.
        Everything else is left alone and returned to the caller to report: a
        foreign PID cannot be judged (PIDs recycle and are not comparable
        across hosts), and neither can a name this code did not write.

        Deleting on "unknown" trades a silent correctness loss in the one
        component whose job is not losing data for a visible,
        operator-reclaimable disk cost. See AD-1296 D3, and
        ``probos backup-reclaim``.
        """
        try:
            children = list(self._backup_root.iterdir())
        except OSError:
            return SweepResult()

        result = SweepResult()
        mine: list[Path] = []
        for child in children:
            if child == exclude or not child.name.endswith(INCOMPLETE_SUFFIX):
                continue
            if not child.is_dir():
                continue
            match = _WORKING_DIR_RE.match(child.name)
            if match is None:
                # Predates this naming, or nothing this code wrote. Unknown owner.
                result.foreign_dirs.append(str(child))
                continue
            pid, run_id = int(match.group(2)), match.group(3)
            if pid != os.getpid():
                result.foreign_dirs.append(str(child))
                continue
            if _run_is_live(run_id):
                continue  # A sibling BackupService in this process is writing it.
            mine.append(child)

        # Oldest first, so a sweep interrupted part-way still made progress on
        # the directories abandoned longest. Names are timestamp-prefixed, so
        # lexical order is chronological order.
        mine.sort(key=lambda child: child.name)
        for child in mine:
            manifest = read_manifest(child)
            failed = [e.label for e in manifest.failed] if manifest else []
            try:
                shutil.rmtree(child)
            except OSError as exc:
                logger.warning(
                    "AD-1296: could not remove this process's finished working "
                    "directory %s (%s); it stays on disk and is retried next tick",
                    child, exc,
                )
                continue
            result.reclaimed_dirs.append(str(child))
            logger.info(
                "AD-1296: reclaimed finished working directory %s "
                "(never promoted; failed files: %s)",
                child, ", ".join(failed) or "unrecorded",
            )

        result.foreign_bytes = sum(
            self._dir_size(Path(p)) for p in result.foreign_dirs
        )
        if result.foreign_dirs:
            # Retention cannot see these -- _SNAPSHOT_DIR_RE matches promoted
            # names only -- so without this line the leak is completely silent.
            # And one warning repeated every tick for a month is
            # indistinguishable from background noise, so past the threshold it
            # is an error: this set has no bound and now rivals everything
            # retention does bound. Still nothing is deleted -- see the
            # docstring above for why the sweep must not decide that.
            escalated = result.foreign_bytes >= self._orphan_alert_bytes
            emit = logger.error if escalated else logger.warning
            emit(
                "AD-1296: %d working director(ies) totalling %d bytes belong to "
                "another process or predate this naming and are NOT reclaimed "
                "automatically; retention cannot see them%s. Run "
                "'probos backup-reclaim --backup-root %s' to review them: %s",
                len(result.foreign_dirs), result.foreign_bytes,
                (
                    " and they are at or past the alert threshold "
                    f"({self._orphan_alert_bytes} bytes, "
                    "infrastructure.backup_orphan_alert_bytes), so the backup "
                    "root will keep growing until they are reclaimed"
                    if escalated else ""
                ),
                self._backup_root,
                ", ".join(result.foreign_dirs[:5]),
            )
        return result

    @staticmethod
    def _describe(
        label: str, tier: BackupTier, state: str, dest: Path,
    ) -> ManifestEntry:
        """Verify one written file and record it.

        ``PRAGMA integrity_check`` runs here -- at snapshot time, not at
        verify time -- because this is the only moment a retry is possible,
        and it keeps every later check a pure digest comparison.

        The digest is unconditional. AD-1262 hashed only files that did not
        look like SQLite databases, which meant verification chose its method
        by inspecting the artifact it was verifying; replacing the payload
        with a valid SQLite file then skipped the recorded digest entirely.
        Both steps propagate to the caller, which records the entry as
        ``failed`` and forfeits promotion: recorded-but-unverified is the
        failure class this AD exists to close.
        """
        size = dest.stat().st_size
        BackupService._integrity_check(dest)
        return ManifestEntry(
            label=label, tier=tier.value, state=state,
            size_bytes=size, sha256=sha256_file(dest),
        )

    @staticmethod
    def _integrity_check(path: Path) -> None:
        """Raise unless ``path`` is a SQLite database that reports ``ok``."""
        with contextlib.closing(sqlite3.connect(str(path))) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise sqlite3.DatabaseError(
                f"PRAGMA integrity_check on {path} reported {row!r}, not 'ok'"
            )

    def _existing_snapshots(self) -> list[tuple[Path, float]]:
        """Promoted snapshot directories under ``backup_root``, oldest first."""
        found: list[tuple[Path, float]] = []
        try:
            children = list(self._backup_root.iterdir())
        except OSError:
            return found
        for child in children:
            if not child.is_dir():
                continue
            ts = parse_snapshot_timestamp(child.name)
            if ts is None:
                continue
            found.append((child, ts))
        found.sort(key=lambda pair: (pair[1], pair[0].name))
        return found

    def _prior_promoted_snapshot(self) -> tuple[Path | None, float]:
        """The newest promoted snapshot, or ``(None, 0.0)``.

        Sourcing hard links from anything else -- an ``.incomplete``
        directory in particular -- would link against bytes nobody has
        attested, so the name check inside :func:`parse_snapshot_timestamp` is
        load-bearing rather than cosmetic.
        """
        for path, ts in reversed(self._existing_snapshots()):
            return path, ts
        return None, 0.0

    def _try_link(
        self,
        entry: DiscoveredDatabase,
        dest: Path,
        prior_dir: Path | None,
        prior_started: float,
    ) -> bool:
        """Hard-link an immutable file from the prior promoted snapshot.

        Both guards are load-bearing. ``(size, mtime_ns)`` matching alone
        would alias a same-size in-place rewrite; additionally requiring the
        mtime to predate the prior snapshot's start means the prior copy
        cannot have been taken before that rewrite. Link failure (cross-device,
        a filesystem without hard links) falls back to a copy, never to a skip
        -- a skipped file would make this snapshot depend on its predecessor,
        which is exactly what D1 forbids.
        """
        if prior_dir is None:
            return False
        prior_copy = prior_dir / entry.snapshot_relative_path
        try:
            src_stat = entry.absolute_path.stat()
            prior_stat = prior_copy.stat()
        except OSError:
            return False
        if src_stat.st_size != prior_stat.st_size:
            return False
        if src_stat.st_mtime_ns != prior_stat.st_mtime_ns:
            return False
        if src_stat.st_mtime_ns >= int(prior_started * 1_000_000_000):
            return False
        try:
            os.link(prior_copy, dest)
        except OSError as exc:
            logger.debug(
                "AD-1265: hard link %s -> %s unavailable (%s); copying instead",
                prior_copy, dest, exc,
            )
            return False
        return True

    @staticmethod
    def _preserve_mtime(src: Path, dest: Path) -> None:
        try:
            src_stat = src.stat()
            os.utime(dest, ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
        except OSError:
            logger.debug(
                "AD-1265: could not stamp %s with the mtime of %s; it will be "
                "copied again next snapshot instead of hard-linked",
                dest, src,
            )

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
        return total

    def _backup_one(self, src: Path, dest: Path) -> None:
        """SQLite online backup -- safe while source is being written.

        BF-849: this was ``with sqlite3.connect(...) as conn``, which binds a
        TRANSACTION, not the connection's lifetime -- ``Connection.__exit__``
        commits or rolls back and never calls ``close()``. Both handles leaked
        on every call. On POSIX that is reclaimed at GC and mostly invisible;
        on Windows an open handle LOCKS the file, so the source database could
        not be renamed, moved or removed after a backup.

        Latent for the life of AD-466 only because ``snapshot()`` was never
        called from ``src/`` (#1313). Wiring the scheduler is what would make
        it reachable, so it is fixed ahead of that work rather than behind it.

        The discriminating test renames the source afterwards -- a rename fails
        while a handle is open. A test that asserts only "the backup succeeded"
        cannot see this, because the copy does complete.
        """
        try:
            with contextlib.closing(sqlite3.connect(str(src))) as src_conn, \
                    contextlib.closing(sqlite3.connect(str(dest))) as dest_conn:
                src_conn.backup(dest_conn)
        except sqlite3.Error:
            # The fallback opens no handles of its own -- copyfile closes both
            # streams -- but it is reached only after the connects above have
            # been closed by ``closing``, so a leak here would be the same
            # defect in the branch nobody exercises.
            shutil.copyfile(src, dest)

    def _fail(
        self,
        snapshot_dir: str,
        started: float,
        error: str,
        *,
        incomplete_dir: str = "",
        sweep: SweepResult | None = None,
    ) -> BackupResult:
        result = BackupResult(
            succeeded=False,
            snapshot_dir=snapshot_dir,
            duration_seconds=time.time() - started,
            error=error,
            incomplete_dir=incomplete_dir,
            orphaned_working_dirs=list(sweep.foreign_dirs) if sweep else [],
            orphaned_bytes=sweep.foreign_bytes if sweep else 0,
            orphans_measured=sweep is not None,
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
                    "files_linked": list(result.files_linked),
                    "files_failed": list(result.files_failed),
                    "pruned_dirs": list(result.pruned_dirs),
                    "retention_bound": result.retention_bound,
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
                    "files_copied": list(result.files_copied),
                    "files_linked": list(result.files_linked),
                    "files_failed": list(result.files_failed),
                    "incomplete_dir": result.incomplete_dir,
                },
            )
        except Exception:
            logger.warning(
                "AD-466: BACKUP_FAILED emit failed (snapshot_dir=%s)",
                result.snapshot_dir, exc_info=True,
            )
