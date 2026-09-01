"""AD-1265: what gets backed up, and what deliberately is not.

AD-466 backed up ``data_dir.glob("*.db")`` -- top level only, and (per
BF-842) with nothing calling it. This module supplies the discovery half:
mechanical recursion under a short list of *declared roots*, minus a
hand-authored exclusion table that must state a reason.

Neither pure model works on its own. Pure recursion re-enters ``backups/``
(which lives inside ``data_dir``) so each snapshot embeds its predecessors,
and it sweeps broker internals. A pure hand-maintained inventory is what
rots -- that rot is BF-838. So: recursion, which cannot go stale, bounded by
an explicit table, which ``tests/test_ad1265_backup_coverage.py`` binds to
the ``*.db`` literals actually declared in ``src/``.

**There is no "sometimes" tier.** A database is either *included* -- copied
into every snapshot, because restoring it is necessary for the vessel to be
correct -- or *excluded*, with a written reason. AD-1262 shipped a third
``bulk`` tier that was carried forward by reference from an earlier
snapshot; review measured the consequence: retention deleted the snapshot
the reference named and restore then reported success with the database
simply absent. A directory that is only restorable in combination with
another directory is not a snapshot.

``IMMUTABLE`` survives, but as an *optimization inside included*, never as a
tier a tick can skip:

    A hard link is data-present. A ``bulk_source`` reference is data-absent.
    Pruning the snapshot a hard link was sourced from does not destroy the
    bytes (link count > 1). Pruning the snapshot a reference names destroys
    the data.

Pruning ``backup_root`` is unconditional and deliberately NOT a config
field: a typo must not be able to re-arm recursive self-inclusion.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

_ROOT_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

#: ``archives/ward_room_*.db`` -- rotated, closed, never rewritten.
_IMMUTABLE_PATTERNS: tuple[str, ...] = ("archives/ward_room_*.db",)


class BackupTier(StrEnum):
    """How a database's bytes get into a snapshot.

    Both tiers are present in **every** snapshot. ``IMMUTABLE`` differs only
    in mechanism -- a hard link when the file is provably unchanged since the
    previous promoted snapshot, a copy otherwise. It is never a skip.
    """

    INCLUDED = "included"
    IMMUTABLE = "immutable"


@dataclass(frozen=True)
class BackupRoot:
    """A directory tree to recurse for ``*.db`` files.

    ``name`` becomes the snapshot subdirectory (``<ts>/<name>/<rel>``), so
    two roots cannot collide on a filename. It is used unescaped as a path
    segment and is validated as one.
    """

    name: str
    path: Path

    def __post_init__(self) -> None:
        if not _ROOT_NAME_RE.match(self.name):
            raise ValueError(
                f"BackupRoot name {self.name!r} is used as a snapshot directory "
                f"segment; it must match {_ROOT_NAME_RE.pattern}"
            )


@dataclass(frozen=True)
class DiscoveredDatabase:
    """One ``*.db`` found under a root, with its tier already decided."""

    root_name: str
    relative_path: PurePosixPath
    absolute_path: Path
    tier: BackupTier

    @property
    def snapshot_relative_path(self) -> PurePosixPath:
        """Where this file lands inside a snapshot directory."""
        return PurePosixPath(self.root_name) / self.relative_path


#: glob (against the path relative to its root) -> why it is not backed up.
#: Every reason is asserted non-empty by the AD-1265 drift test: an exclusion
#: without a stated reason is indistinguishable from an oversight.
#:
#: Exclusion is a strong claim -- it says restore deliberately will not
#: provide this file. Size alone is never a justification.
EXCLUDED_DATABASES: Mapping[str, str] = {
    "nats-jetstream/**": (
        "broker internals; rebuilt from stream config on reconnect"
    ),
    "**/backups/**": (
        "backup root; excluded unconditionally, see prune_backup_root"
    ),
    "activation_tracker.db": (
        "1.03 GB / 6,820,292 rows in its sole table episode_access_log "
        "(activation_tracker.py:292,304); a derived ACT-R access log with "
        "180-day self-retention (activation_tracker.py:36), scoring episodes "
        "that live in ChromaDB, which AD-823 already snapshots separately. "
        "Losing it degrades activation ranking; it destroys nothing. This is "
        "the single largest decision in AD-1265 by bytes -- 986 MiB per tick "
        "-- and it is what makes a self-sufficient snapshot affordable."
    ),
}

# Rejected exclusion candidates (AD-1265, measured 2026-08-24). AD-1262 named
# these four as size-ranked demotion candidates and required a confirmed
# reconstructibility argument. None could be established, so all four stay
# INCLUDED -- and exclusion is a stronger claim than that AD's `bulk` demotion
# was, so the bar is higher now, not lower:
#   semantic_work.db     164.7 MB, semantic_work=378,893 -- primary store of
#                        the AD-750 semantic work layer, not derived.
#   cognitive_journal.db 152.3 MB, cognitive_journal=350,567 -- the journal
#                        IS the record; there is no upstream to replay.
#   eviction_audit.db    140.1 MB, eviction_audit=323,066 -- an audit trail
#                        is by definition not reconstructible.
#   episode_fts.db        29.6 MB, episode_fts=5,316 -- an FTS5 sidecar
#                        derived from episodes (AD-567b), but the only
#                        repopulation path is EpisodicMemory's internal seed;
#                        there is no rebuild entry point, so reconstructibility
#                        is not operationally established.


def prune_backup_root(paths: Sequence[Path], backup_root: Path) -> list[Path]:
    """Drop every path at or under ``backup_root``.

    Unconditional by design: ``backup_root`` defaults to
    ``data_dir / "backups"``, i.e. *inside* the tree being recursed, so
    without this each snapshot would embed all of its predecessors.
    Comparison is on resolved paths so neither ``..`` nor a symlink into the
    backup root can slip past.
    """
    try:
        resolved_root = backup_root.resolve()
    except OSError:
        resolved_root = backup_root.absolute()
    kept: list[Path] = []
    for candidate in paths:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if resolved == resolved_root or resolved.is_relative_to(resolved_root):
            continue
        kept.append(candidate)
    return kept


def _pattern_matches(relative_path: PurePosixPath, pattern: str) -> bool:
    """Path-aware glob for the two shapes the tables actually use.

    ``fnmatch`` treats ``**`` as a plain wildcard that also crosses ``/``,
    which silently over-matches, so the directory forms are handled
    explicitly:

    * ``**/<seg>/**`` -- a directory component named ``<seg>`` at any depth
    * ``<prefix>/**`` -- anything at or under ``<prefix>``

    Anything else falls through to ``fnmatch`` on the whole relative path.
    """
    text = str(relative_path)
    if pattern.startswith("**/") and pattern.endswith("/**"):
        segment = pattern[3:-3]
        return any(
            fnmatch.fnmatch(part, segment) for part in relative_path.parts[:-1]
        )
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return text == prefix or text.startswith(f"{prefix}/")
    return fnmatch.fnmatch(text, pattern)


def classify(relative_path: PurePosixPath) -> BackupTier:
    """Decide a tier from a root-relative path. Defaults to INCLUDED.

    INCLUDED is never inferred away: a store added tomorrow lands in the tier
    that is always protected, and leaving it out requires someone to write a
    reason into :data:`EXCLUDED_DATABASES`.
    """
    for pattern in _IMMUTABLE_PATTERNS:
        if _pattern_matches(relative_path, pattern):
            return BackupTier.IMMUTABLE
    return BackupTier.INCLUDED


def is_excluded(
    relative_path: PurePosixPath,
    exclude: Mapping[str, str] = EXCLUDED_DATABASES,
) -> str | None:
    """Return the exclusion reason for a root-relative path, or None."""
    for pattern, reason in exclude.items():
        if _pattern_matches(relative_path, pattern):
            return reason
    return None


def build_default_roots(data_dir: Path, config: object) -> list[BackupRoot]:
    """The roots a vessel snapshots, from its effective configuration.

    The Ship's Archive (AD-524) lives *outside* ``data_dir`` -- on Windows
    under ``%LOCALAPPDATA%\\ProbOS\\archive`` -- so it is a second,
    separately-namespaced root rather than something to move. Moving it would
    be a data migration on a path the operator may have overridden; a root
    costs 20 KB and is reversible.

    The archive path is read from :func:`probos.config.resolve_archive_db_path`
    rather than recomputed from the platform branch, because an operator who
    overrode ``archive.db_path`` must not silently go unbacked.
    """
    from probos.config import resolve_archive_db_path

    roots = [BackupRoot("data", Path(data_dir))]
    infrastructure = getattr(config, "infrastructure", None)
    archive = getattr(config, "archive", None)
    if (
        archive is not None
        and getattr(archive, "enabled", False)
        and getattr(infrastructure, "backup_include_archive_root", False)
    ):
        try:
            roots.append(BackupRoot("archive", resolve_archive_db_path(archive).parent))
        except Exception:
            logger.warning(
                "AD-1265: could not resolve the archive directory; snapshots "
                "will cover the data root only and archive.db goes unbacked",
                exc_info=True,
            )
    return roots


def discover(
    roots: Sequence[BackupRoot],
    *,
    backup_root: Path,
    exclude: Mapping[str, str] = EXCLUDED_DATABASES,
) -> list[DiscoveredDatabase]:
    """Enumerate every ``*.db`` under ``roots``, tiered and deduplicated.

    Ordering is deterministic (``root.name``, then relative path) so two runs
    against an unchanged tree produce identical manifests. A root that does
    not exist yields zero entries and logs at ``info`` -- a fresh vessel is
    not an error.
    """
    found: list[DiscoveredDatabase] = []
    for root in roots:
        if not root.path.is_dir():
            logger.info(
                "AD-1265: backup root %r (%s) does not exist yet; contributing "
                "no files to this snapshot",
                root.name, root.path,
            )
            continue
        candidates = prune_backup_root(sorted(root.path.rglob("*.db")), backup_root)
        for absolute in candidates:
            try:
                relative = PurePosixPath(absolute.relative_to(root.path).as_posix())
            except ValueError:
                # rglob cannot normally produce this; skip rather than write
                # outside the snapshot's root namespace.
                logger.warning(
                    "AD-1265: %s is not under its declared root %s; skipped",
                    absolute, root.path,
                )
                continue
            reason = is_excluded(relative, exclude)
            if reason:
                logger.debug(
                    "AD-1265: %s/%s excluded (%s)", root.name, relative, reason,
                )
                continue
            found.append(
                DiscoveredDatabase(
                    root_name=root.name,
                    relative_path=relative,
                    absolute_path=absolute,
                    tier=classify(relative),
                )
            )
    found.sort(key=lambda d: (d.root_name, str(d.relative_path)))
    return found
