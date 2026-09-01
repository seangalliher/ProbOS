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
import errno
import json
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
    OWNER_NAME,
    STATE_COPIED,
    STATE_FAILED,
    STATE_LINKED,
    ManifestEntry,
    SnapshotManifest,
    read_manifest,
    sha256_file,
    write_manifest,
)
from probos.pidfile_guard import is_pid_alive

logger = logging.getLogger(__name__)

#: ``20260824-061728`` plus the optional ``-123456`` collision suffix.
#: Matches **promoted** names only -- ``<ts>.incomplete`` deliberately fails
#: it, so retention cannot see one and hard-linking cannot source from one.
_SNAPSHOT_DIR_RE = re.compile(r"^(\d{8}-\d{6})(?:-\d{6})?$")

_DEFAULT_RETAIN_DAYS = 3
_DEFAULT_MAX_TOTAL_BYTES = 8 * 1024**3

#: Where a working directory is assembled before it is renamed into place
#: under its ``.incomplete`` name. The owner PID is in the name so a stranded
#: one can be attributed without reading anything out of it.
_STAGING_PREFIX = ".staging-"
_STAGING_RE = re.compile(r"^\.staging-(\d+)-[0-9a-f]{16}$")

#: Backstop for the single case PID liveness cannot decide: an owner that died
#: and whose PID the OS then handed to an unrelated, still-running process.
#: Without it that directory is never swept and accumulates forever.
#:
#: This is a bound on accumulation, **not** a safety property. It can in
#: principle delete a working directory a peer is still writing, which is why
#: it sits orders of magnitude beyond any plausible snapshot duration instead
#: of close to one. Ownership -- not this -- is what makes the sweep safe.
_OWNER_STALE_SECONDS = 24 * 3600

_ACTIVE_LOCK = threading.Lock()
#: Working directory paths this process intends to write, and how many
#: in-flight attempts claim each. Two BackupService instances in one process
#: share a PID, so liveness alone cannot tell a live sibling's directory from
#: one this process abandoned on an earlier tick; this can.
#:
#: A count rather than a set because two attempts legitimately claim the same
#: ``<ts>`` name in the same second -- one wins the rename and one falls
#: through to the collision-suffixed name. With a set, the loser's release
#: revoked the winner's claim and the sweep then ate a live directory: the
#: reported defect, reached from inside the fix for it.
_ACTIVE_CLAIMS: dict[str, int] = {}


def _claim_active(working_dir: Path) -> None:
    key = str(working_dir)
    with _ACTIVE_LOCK:
        _ACTIVE_CLAIMS[key] = _ACTIVE_CLAIMS.get(key, 0) + 1


def _release_active(working_dir: Path) -> None:
    key = str(working_dir)
    with _ACTIVE_LOCK:
        remaining = _ACTIVE_CLAIMS.get(key, 0) - 1
        if remaining > 0:
            _ACTIVE_CLAIMS[key] = remaining
        else:
            _ACTIVE_CLAIMS.pop(key, None)


def _is_active(working_dir: Path) -> bool:
    with _ACTIVE_LOCK:
        return _ACTIVE_CLAIMS.get(str(working_dir), 0) > 0


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

        working_dir, final_dir, failure = self._make_snapshot_dir(started)
        if working_dir is None or final_dir is None:
            return self._fail(failure[0], started, failure[1])
        try:
            return self._write_snapshot(started, working_dir, final_dir)
        finally:
            # The peer sweep consults these claims. Leaving one behind would
            # make a finished directory immortal, so it is released on every
            # path out -- promoted, failed or raised.
            _release_active(working_dir)

    def _write_snapshot(
        self, started: float, working_dir: Path, final_dir: Path,
    ) -> BackupResult:
        """Fill ``working_dir`` and promote it. Claimed as active by caller."""
        self._sweep_incomplete(exclude=working_dir)

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
                str(working_dir), started, str(exc), incomplete_dir=str(working_dir),
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
        self, started: float,
    ) -> tuple[Path | None, Path | None, tuple[str, str]]:
        """Reserve ``<ts>.incomplete`` and the ``<ts>`` name it promotes to.

        The directory is assembled elsewhere and *renamed* into place, so a
        ``<ts>.incomplete`` that a peer can see always already carries its
        ownership marker. Creating it first and writing the marker second
        would leave a window in which a peer's sweep sees an unowned
        directory -- the same defect this protocol closes, reached by another
        route.

        The rename is also the reservation: it fails when the target exists
        (on Windows always; on POSIX because a working directory is never
        empty, it always holds its marker), so two services in the same
        second still cannot both claim one ``<ts>``.
        """
        timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started))
        for base in (
            timestamp,
            f"{timestamp}-{int((started % 1) * 1_000_000):06d}",
        ):
            final_dir = self._backup_root / base
            working_dir = self._backup_root / f"{base}{INCOMPLETE_SUFFIX}"
            if final_dir.exists():
                continue
            try:
                staging = self._stage_owned_dir(started)
            except OSError as exc:
                return None, None, (str(working_dir), f"mkdir failed: {exc}")
            # Claimed before the directory is visible, never after.
            _claim_active(working_dir)
            try:
                os.rename(staging, working_dir)
            except OSError as exc:
                _release_active(working_dir)
                shutil.rmtree(staging, ignore_errors=True)
                if isinstance(exc, FileExistsError) or exc.errno in (
                    errno.EEXIST, errno.ENOTEMPTY,
                ):
                    continue
                return None, None, (str(working_dir), f"mkdir failed: {exc}")
            return working_dir, final_dir, ("", "")
        return None, None, (
            str(self._backup_root / timestamp),
            "mkdir failed: both the timestamped and collision-suffixed names exist",
        )

    def _stage_owned_dir(self, started: float) -> Path:
        """Build a marked working directory under a name no sweep will touch."""
        staging = self._backup_root / (
            f"{_STAGING_PREFIX}{os.getpid()}-{uuid.uuid4().hex[:16]}"
        )
        staging.mkdir(parents=True, exist_ok=False)
        (staging / OWNER_NAME).write_text(
            json.dumps({"pid": os.getpid(), "created_at": started}),
            encoding="utf-8",
        )
        return staging

    @staticmethod
    def _promote(working_dir: Path, final_dir: Path) -> Path:
        """Rename the working directory to its timestamped name.

        This, and only this, means promoted. A directory rename is the atomic
        step: an observer either sees no ``<ts>`` at all or sees a complete
        one. Copying files into ``<ts>`` directly would make every
        partially-written snapshot visible under a name that reads as
        finished, and process death between "manifest written" and "promoted"
        would leave exactly that on disk.

        The ownership marker is dropped *after* the rename, never before:
        clearing it first would expose an unowned working directory to a
        peer's sweep for as long as the rename takes.
        """
        os.replace(working_dir, final_dir)
        try:
            (final_dir / OWNER_NAME).unlink(missing_ok=True)
        except OSError:
            logger.debug(
                "AD-1265: could not drop the ownership marker from promoted "
                "snapshot %s; it is inert there", final_dir, exc_info=True,
            )
        return final_dir

    def _sweep_incomplete(self, *, exclude: Path) -> None:
        """Remove working directories nobody is writing any more.

        A crash leaves one behind and nothing else will ever collect it, so
        the sweep has to exist -- an ``.incomplete`` directory can never be
        admitted (promotion is the sole marker), which makes keeping them
        unbounded cost for no recovery value.

        But **"not promoted" and "abandoned" are different states**, and
        review measured what conflating them costs: a second service's sweep
        deleted a first service's *active* working directory, and the first
        then failed with ``No such file or directory`` on a file it was
        mid-copy. :meth:`_is_abandoned` is what tells the two apart.

        The failure itself survives in the event log and in the warning
        below, which names the directory before removing it.
        """
        try:
            children = list(self._backup_root.iterdir())
        except OSError:
            return
        now = time.time()
        stale = [
            child for child in children
            if child != exclude
            and child.name.endswith(INCOMPLETE_SUFFIX)
            and child.is_dir()
            and self._is_abandoned(child, now)
        ]
        # Oldest first, so a sweep interrupted part-way still made progress on
        # the directories abandoned longest. Names are timestamp-prefixed, so
        # lexical order is chronological order.
        stale.sort(key=lambda child: child.name)
        for child in stale:
            manifest = read_manifest(child)
            failed = [e.label for e in manifest.failed] if manifest else []
            try:
                shutil.rmtree(child)
            except OSError as exc:
                logger.warning(
                    "AD-1265: could not remove abandoned working directory %s "
                    "(%s); it stays on disk and is retried next tick",
                    child, exc,
                )
                continue
            logger.warning(
                "AD-1265: removed abandoned snapshot working directory %s "
                "(never promoted; failed files: %s)",
                child, ", ".join(failed) or "unrecorded",
            )
        self._sweep_staging(children)

    @staticmethod
    def _is_abandoned(working_dir: Path, now: float) -> bool:
        """Whether nothing is writing ``working_dir`` any more.

        Four cases, and the first two are why a PID alone cannot decide this
        -- two BackupService instances in one process share one:

        * in this process's active set -- a live sibling. Never sweep.
        * marked with this PID but not active -- this process's own earlier
          tick, which failed and left its bytes for inspection. Sweep.
        * marked with another PID that is alive -- a peer may be mid-copy.
          Never sweep.
        * marked with a dead PID, or unmarked -- abandoned. Sweep.

        What this does **not** decide: whether a live foreign PID is really
        *the* process that made the directory. The OS recycles PIDs, so a
        dead owner can be impersonated by an unrelated live process, and that
        directory would then never be swept. :data:`_OWNER_STALE_SECONDS` is
        the backstop for exactly that case and nothing else.
        """
        if _is_active(working_dir):
            return False
        pid, created_at = BackupService._read_owner(working_dir)
        if pid is None:
            # Unmarked: it predates this protocol, or lost its marker. Every
            # directory this code creates is marked before it is visible, so
            # nothing that is live can land here.
            return True
        if pid == os.getpid():
            return True
        if not is_pid_alive(pid):
            return True
        if created_at and now - created_at > _OWNER_STALE_SECONDS:
            logger.warning(
                "AD-1265: working directory %s is still claimed by live PID %d "
                "after %.1f h; treating that PID as recycled and sweeping. If "
                "that process really is still writing this snapshot it will "
                "fail -- raise _OWNER_STALE_SECONDS",
                working_dir, pid, (now - created_at) / 3600.0,
            )
            return True
        logger.debug(
            "AD-1265: leaving working directory %s alone -- PID %d is alive and "
            "may be mid-copy; not promoted is not the same as abandoned",
            working_dir, pid,
        )
        return False

    def _sweep_staging(self, children: Sequence[Path]) -> None:
        """Collect staging directories a crash stranded before their rename.

        The owner PID is in the *name*, so there is no marker to read and
        therefore no window in which one is missing. This process's own PID
        reads as alive, so a sibling's half-built staging directory is never
        touched.
        """
        for child in children:
            match = _STAGING_RE.match(child.name)
            if not match or not child.is_dir():
                continue
            if is_pid_alive(int(match.group(1))):
                continue
            try:
                shutil.rmtree(child)
            except OSError as exc:
                logger.debug(
                    "AD-1265: could not remove stranded staging directory %s (%s)",
                    child, exc,
                )
                continue
            logger.info("AD-1265: removed stranded staging directory %s", child)

    @staticmethod
    def _read_owner(working_dir: Path) -> tuple[int | None, float]:
        """``(pid, created_at)`` from the ownership marker, or ``(None, 0.0)``."""
        try:
            raw = json.loads(
                (working_dir / OWNER_NAME).read_text(encoding="utf-8")
            )
            return int(raw["pid"]), float(raw.get("created_at", 0.0) or 0.0)
        except (OSError, ValueError, TypeError, KeyError):
            return None, 0.0

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
    ) -> BackupResult:
        result = BackupResult(
            succeeded=False,
            snapshot_dir=snapshot_dir,
            duration_seconds=time.time() - started,
            error=error,
            incomplete_dir=incomplete_dir,
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
