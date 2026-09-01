"""AD-1265 (BF-842): the file that says whether a snapshot is whole.

A directory listing cannot answer the only question a consumer actually
asks -- *is everything here that should be here?* Adversarial review of the
AD-1262 attempt measured what that costs: a tick whose sole failure was
``data/missed.db`` still reported ``succeeded=True``, still emitted
``BACKUP_COMPLETE``, still triggered retention, and still restored -- mixing
``good.db`` from the snapshot with a **newer** live ``missed.db``. Every
individual step reported success; the vessel was silently inconsistent.

The manifest attests completeness of **content**; the directory name attests
completeness of **the write** (see ``backup._SNAPSHOT_DIR_RE`` and
:data:`INCOMPLETE_SUFFIX`). Both are required, and only the rename is atomic.

The integrity contract, stated as narrowly as it can be kept:

    For every file listed in a promoted snapshot's manifest, the bytes on
    disk SHA-256 to the digest the manifest records, and that digest was
    computed from the bytes as written, after those bytes passed
    ``PRAGMA integrity_check``.

That buys tamper-evidence, torn-write detection and silent-corruption
detection. It does **not** buy semantic correctness of the database (nothing
can), nor that the copy matches the source at the snapshot instant (that is
the online ``.backup`` API's contract, not the manifest's).

And the general lesson, which cost AD-1262 a round-2 finding:

    **Never infer the verification method from the artifact being
    verified.** The manifest is authoritative. If it records a digest,
    compute the digest and compare. Asking the file what kind of file it is
    hands the attacker -- or the corruption -- the choice of test.

That is why ``is_sqlite_file`` does not exist here. Its only caller chose a
verification path from the artifact's own bytes, so replacing an opaque
payload with a valid SQLite file skipped the recorded digest entirely.
Nothing may reintroduce it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import ntpath
import os
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

logger = logging.getLogger(__name__)

#: Bumped only for a breaking change. A consumer refuses a schema it does not
#: know rather than guessing at fields that may have changed meaning.
SCHEMA_VERSION = 2

MANIFEST_NAME = "manifest.json"

#: Suffix of the working directory a snapshot is built in. Deliberately not
#: matched by ``backup._SNAPSHOT_DIR_RE``, so retention never counts one and
#: hard-linking never sources from one.
INCOMPLETE_SUFFIX = ".incomplete"

#: Ownership marker written inside every working directory before that
#: directory is visible under its ``.incomplete`` name. It is what lets the
#: stale sweep tell an abandoned directory from a peer's in-flight one, and it
#: is removed on promotion so no promoted snapshot carries it.
OWNER_NAME = "owner.json"

STATE_COPIED = "copied"
STATE_LINKED = "linked"
STATE_FAILED = "failed"

#: The states whose bytes are inside the snapshot directory.
_PRESENT_STATES = (STATE_COPIED, STATE_LINKED)

#: Both separators, always: a label written on Windows is read on POSIX and
#: vice versa, so ``a\\..\\..\\x`` has to be an escape on both.
_LABEL_SEPARATORS = re.compile(r"[\\/]+")


def is_contained_label(label: str) -> bool:
    """Whether ``label`` can only ever name a file *inside* a snapshot.

    The cheap half of the check, and deliberately platform-agnostic:
    ``/etc/passwd`` is rejected on Windows and ``C:x.db`` is rejected on
    POSIX, because the manifest is a portable artifact and the reader is not
    always the writer's platform. A drive-qualified label is rejected even
    when it is *drive-relative* (``C:x.db``), which no leading-slash test and
    no ``posixpath.isabs`` sees.

    It cannot see symlinks -- that is :func:`resolve_contained`'s job, and
    both are required.
    """
    if not label or "\x00" in label:
        return False
    if posixpath.isabs(label) or ntpath.isabs(label):
        return False
    if PureWindowsPath(label).drive:
        return False
    return ".." not in _LABEL_SEPARATORS.split(label)


def resolve_contained(snapshot_dir: Path, label: str) -> Path | None:
    """``snapshot_dir/label`` when it really lands inside, else ``None``.

    Both sides are resolved, so a symlink *inside* the snapshot pointing out
    of it is caught -- a string-only guard would wave that through, and a
    snapshot that attests bytes it does not contain is the whole failure.
    """
    if not is_contained_label(label):
        return None
    root = Path(snapshot_dir).resolve()
    try:
        resolved = (root / label).resolve()
    except OSError:
        return None
    return resolved if resolved.is_relative_to(root) else None


@dataclass(frozen=True)
class ManifestEntry:
    """One database that was due this tick, and what became of it."""

    label: str
    tier: str
    state: str
    size_bytes: int = 0
    #: SHA-256 of the bytes as written, computed after they passed
    #: ``PRAGMA integrity_check``. Required and non-empty for every present
    #: entry -- there is no opaque tier and no present-but-undigested entry.
    #: AD-1262 recorded such entries, promoted the snapshot as complete, and
    #: left the consumer to refuse it later; recorded-but-unverified is the
    #: failure class, so it is rejected structurally here instead.
    sha256: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        # Structural, and before the digest rule: a label that can never be
        # valid must not survive into a parsed manifest at all. Review
        # measured what a reader-only guard costs -- a label of
        # ``../outside.db`` made verification size-check, digest and open a
        # database the snapshot does not contain, and report OK.
        if not is_contained_label(self.label):
            raise ValueError(
                f"manifest entry label {self.label!r} names a path outside the "
                f"snapshot directory; a snapshot may only attest bytes it "
                f"actually contains"
            )
        if self.state in _PRESENT_STATES and not self.sha256:
            raise ValueError(
                f"manifest entry {self.label!r} is present (state={self.state!r}) "
                f"but carries no sha256; a present entry without a digest is "
                f"unverifiable and must be recorded as {STATE_FAILED!r} instead"
            )

    @property
    def is_present(self) -> bool:
        """Whether this entry's bytes are inside this snapshot directory."""
        return self.state in _PRESENT_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "tier": self.tier,
            "state": self.state,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ManifestEntry:
        return cls(
            label=str(raw["label"]),
            tier=str(raw.get("tier", "")),
            state=str(raw.get("state", "")),
            size_bytes=int(raw.get("size_bytes", 0) or 0),
            sha256=str(raw.get("sha256", "") or ""),
            error=str(raw.get("error", "") or ""),
        )


@dataclass(frozen=True)
class SnapshotManifest:
    """What one tick was due to copy, and whether it managed to.

    Every discovered file is due on every tick -- there is no tier a tick can
    skip and no reference to another snapshot, so this manifest describes a
    self-sufficient point-in-time image.
    """

    snapshot: str
    created_at: float
    entries: list[ManifestEntry] = field(default_factory=list)
    schema: int = SCHEMA_VERSION

    @property
    def failed(self) -> list[ManifestEntry]:
        return [e for e in self.entries if e.state == STATE_FAILED]

    @property
    def present(self) -> list[ManifestEntry]:
        return [e for e in self.entries if e.is_present]

    @property
    def complete(self) -> bool:
        """True only when every due file this tick was actually written.

        One failure is enough. The alternative ("succeeded if anything
        copied") is the defect this whole module exists to close.
        """
        return not self.failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "snapshot": self.snapshot,
            "created_at": self.created_at,
            "complete": self.complete,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SnapshotManifest:
        return cls(
            schema=int(raw.get("schema", 0) or 0),
            snapshot=str(raw.get("snapshot", "")),
            created_at=float(raw.get("created_at", 0.0) or 0.0),
            entries=[ManifestEntry.from_dict(e) for e in raw.get("entries", [])],
        )


def manifest_path(snapshot_dir: Path) -> Path:
    return Path(snapshot_dir) / MANIFEST_NAME


def write_manifest(snapshot_dir: Path, manifest: SnapshotManifest) -> Path:
    """Write ``manifest.json`` into ``snapshot_dir``, replacing atomically.

    The staging file and the containing directory are both fsynced **where
    the platform supports it**: without the directory fsync the rename that
    promotes the snapshot can reach disk before the manifest's own bytes do,
    and a crash in that window leaves a promoted directory whose manifest is
    empty or truncated.

    On Windows there is no directory fsync, so that ordering is **not**
    obtained -- see :func:`_fsync_dir`. A promoted snapshot there is still
    atomic with respect to a *reader* (the rename is), but a host crash
    mid-promotion can leave ``<ts>`` present with a short manifest, and
    ``verify_snapshot`` is what catches it.

    Propagates on failure (tier 3): a snapshot whose manifest did not land is
    unusable, and promoting it would recreate exactly the "looks like
    protection" failure the manifest exists to prevent.
    """
    target = manifest_path(snapshot_dir)
    staging = target.with_name(f"{MANIFEST_NAME}.tmp")
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    with staging.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staging, target)
    _fsync_dir(Path(snapshot_dir))
    return target


def _fsync_dir(path: Path) -> None:
    """fsync a directory so a rename inside it is durable, where possible.

    Windows has no directory-fsync equivalent and ``os.open`` on a directory
    fails there, so on NTFS this is a no-op and the metadata ordering it buys
    on POSIX is simply absent -- a host crash between the manifest write and
    the promotion rename can leave a promoted directory with a truncated
    manifest. Degrading is still right (failing the snapshot would leave the
    vessel with no backup at all rather than one that must be verified), but
    nothing here should be read as durability parity.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        logger.debug(
            "AD-1265: cannot fsync directory %s on this platform; the manifest "
            "file itself was still fsynced", path,
        )
        return
    try:
        os.fsync(fd)
    except OSError:
        logger.debug("AD-1265: fsync of directory %s failed", path, exc_info=True)
    finally:
        os.close(fd)


def read_manifest(snapshot_dir: Path) -> SnapshotManifest | None:
    """Parse ``manifest.json``, or None if it is absent or unreadable.

    None is not "assume it is fine" -- every caller treats it as a refusal.
    AD-466-era snapshots predate the manifest and are refused for that
    reason: nothing recorded what they were *supposed* to contain, so no one
    can say whether they are whole. (The live vessel has zero snapshots of
    any kind, so this is a refusal rule, not a migration.)
    """
    path = manifest_path(snapshot_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("AD-1265: no manifest at %s", path)
        return None
    except (OSError, ValueError) as exc:
        logger.warning(
            "AD-1265: manifest at %s is unreadable (%s); the snapshot cannot "
            "be shown to be complete and will be refused",
            path, exc,
        )
        return None
    if not isinstance(raw, dict):
        logger.warning("AD-1265: manifest at %s is not an object; refusing", path)
        return None
    try:
        return SnapshotManifest.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning(
            "AD-1265: manifest at %s has unusable fields (%s); refusing", path, exc,
        )
        return None


def sha256_file(path: Path, *, chunk_bytes: int = 1024 * 1024) -> str:
    """Streaming SHA-256 so a multi-hundred-MB file is not read into RAM."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(chunk)
    return digest.hexdigest()
