"""AD-1265 §7: does this snapshot actually open?

Between this AD and AD-1266 (restore) the vessel has backups it has never
proved it can read. That is precisely the "looks like protection" failure
this line of work exists to close, so the split is only defensible if
something closes it. This module is that something.

``verify_snapshot`` opens every file in a promoted snapshot **through the
normal connection path a runtime would use** and checks it against the
manifest. It converts "we have files" into "we have files that open and
match what was recorded."

**It writes nothing. It is not restore and must not grow into it.** No
function here may write into a declared root, move a live database aside, or
acquire the AD-816 pidfile -- being read-only is exactly what lets an
operator run it against a live vessel, which is the difference from AD-1266
and it is deliberate.

Two rules from D3/D4 are load-bearing and are enforced in this order:

1. **Refuse by name first.** A hand-built ``<ts>.incomplete`` directory can
   contain a perfectly valid ``complete=true`` manifest. Promotion -- the
   atomic rename -- is the sole marker of a finished write, so the final path
   component is checked before the manifest is even read.
2. **Never infer the verification method from the artifact being verified.**
   The manifest is authoritative. If it records a digest, compute the digest
   and compare. Asking the file what kind of file it is hands the attacker,
   or the corruption, the choice of test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from probos.infrastructure.backup import is_promoted_snapshot_name
from probos.infrastructure.snapshot_manifest import (
    manifest_path,
    read_manifest,
    resolve_contained,
    sha256_file,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileVerdict:
    """One manifest entry, and whether its bytes are still what was recorded."""

    label: str
    ok: bool
    reason: str = ""

    def render(self) -> str:
        # No square brackets: this string is printed through Rich, which would
        # eat "[ok]" as a markup tag and silently drop the verdict.
        mark = "ok  " if self.ok else "FAIL"
        return f"  {mark}  {self.label}{'' if self.ok else f'  -- {self.reason}'}"


@dataclass(frozen=True)
class VerifyReport:
    """Per-file verdicts plus the one boolean an operator actually acts on."""

    snapshot_dir: str
    ok: bool
    refused_reason: str = ""
    verdicts: list[FileVerdict] = field(default_factory=list)

    @property
    def failed(self) -> list[FileVerdict]:
        return [v for v in self.verdicts if not v.ok]

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def render(self) -> str:
        lines = [f"snapshot: {self.snapshot_dir}"]
        if self.refused_reason:
            lines.append(f"REFUSED: {self.refused_reason}")
            return "\n".join(lines)
        lines.extend(verdict.render() for verdict in self.verdicts)
        lines.append(
            f"{len(self.verdicts) - len(self.failed)}/{len(self.verdicts)} "
            f"file(s) verified -- {'OK' if self.ok else 'FAILED'}"
        )
        return "\n".join(lines)


def _refuse(snapshot_dir: Path, reason: str) -> VerifyReport:
    logger.warning("AD-1265: refusing snapshot %s -- %s", snapshot_dir, reason)
    return VerifyReport(snapshot_dir=str(snapshot_dir), ok=False, refused_reason=reason)


async def verify_snapshot(
    snapshot_dir: Path,
    *,
    connection_factory: ConnectionFactory | None = None,
) -> VerifyReport:
    """Check a promoted snapshot against its own manifest. Writes nothing.

    ``connection_factory`` defaults to the runtime's own SQLite factory --
    opening the bytes through the same path production uses is the point of
    the exercise, so an injected factory is for tests and for a future
    non-SQLite backend, not for skipping the open.
    """
    if connection_factory is None:
        from probos.storage.sqlite_factory import default_factory

        connection_factory = default_factory

    snapshot_dir = Path(snapshot_dir)
    # D4: by name, before the manifest is read. A directory that was never
    # promoted has no claim on being complete no matter what it contains.
    if not is_promoted_snapshot_name(snapshot_dir.name):
        return _refuse(
            snapshot_dir,
            f"{snapshot_dir.name!r} is not a promoted snapshot directory name; "
            f"only the atomic rename out of '.incomplete' means complete",
        )
    if not snapshot_dir.is_dir():
        return _refuse(snapshot_dir, "not a directory")

    manifest = read_manifest(snapshot_dir)
    if manifest is None:
        # "Absent" and "present but rejected" are different things to tell an
        # operator, and the containment guard makes the second one reachable:
        # a manifest naming bytes outside the snapshot parses to None, and
        # reporting that as "no manifest" would send them looking for a file
        # that is sitting right there.
        if manifest_path(snapshot_dir).exists():
            return _refuse(
                snapshot_dir,
                "manifest.json is present but was rejected as unusable (see the "
                "AD-1265 warning in the log for which field); a manifest that "
                "cannot be parsed cannot attest anything",
            )
        return _refuse(
            snapshot_dir,
            "no readable manifest.json; nothing recorded what this snapshot "
            "was supposed to contain, so no one can say whether it is whole",
        )
    if not manifest.complete:
        return _refuse(
            snapshot_dir,
            f"manifest records {len(manifest.failed)} failed entry/entries: "
            f"{', '.join(e.label for e in manifest.failed)}",
        )

    verdicts: list[FileVerdict] = []
    for entry in manifest.present:
        verdicts.append(
            await _verify_entry(snapshot_dir, entry, connection_factory)
        )
    ok = all(verdict.ok for verdict in verdicts)
    return VerifyReport(snapshot_dir=str(snapshot_dir), ok=ok, verdicts=verdicts)


async def _verify_entry(
    snapshot_dir: Path,
    entry: object,
    connection_factory: ConnectionFactory,
) -> FileVerdict:
    label = getattr(entry, "label", "")
    # First, before size, digest or open. Review measured what happens when
    # it is not: a label of ``../outside.db`` had this function stat, hash
    # and open a database that is not in the snapshot, and return ok -- an
    # operator's "can I trust this?" answered yes with bytes that will not be
    # there at restore time. read_manifest refuses such a label too; this is
    # the half that also sees a symlink pointing out of the snapshot.
    path = resolve_contained(snapshot_dir, label)
    if path is None:
        return FileVerdict(
            label, False,
            "label resolves outside the snapshot directory; the snapshot "
            "cannot attest bytes it does not contain",
        )
    if not path.is_file():
        return FileVerdict(label, False, "absent from the snapshot")

    size = path.stat().st_size
    recorded_size = int(getattr(entry, "size_bytes", 0))
    if size != recorded_size:
        return FileVerdict(
            label, False, f"size {size} != manifest {recorded_size}",
        )

    # D3: the manifest decides the method. The digest is computed
    # unconditionally and is never skipped on the strength of what the bytes
    # look like -- that inference is how a replaced-but-valid SQLite file once
    # passed verification.
    recorded_digest = str(getattr(entry, "sha256", ""))
    if not recorded_digest:
        return FileVerdict(
            label, False, "manifest records no digest for a present entry",
        )
    try:
        actual = sha256_file(path)
    except OSError as exc:
        return FileVerdict(label, False, f"could not read for digest: {exc}")
    if actual != recorded_digest:
        return FileVerdict(
            label, False,
            f"sha256 {actual[:16]}... != manifest {recorded_digest[:16]}...",
        )

    opened = await _opens_and_answers(path, connection_factory)
    if opened:
        return FileVerdict(label, False, opened)
    return FileVerdict(label, True)


async def _opens_and_answers(
    path: Path, connection_factory: ConnectionFactory,
) -> str:
    """Empty string when the file opens and answers; the reason otherwise.

    Opening the bytes is the whole point of §7: a digest proves the file has
    not changed since it was written, and this proves it was worth writing.
    """
    conn = None
    try:
        conn = await connection_factory.connect(str(path))
        cursor = await conn.execute(
            "SELECT count(*) FROM sqlite_master"  # noqa: S608 - fixed literal
        )
        row = await cursor.fetchone()
        if row is None:
            return "opened but returned no rows from sqlite_master"
    except Exception as exc:
        return f"does not open through the runtime connection path: {exc}"
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                logger.debug(
                    "AD-1265: closing the verification connection for %s failed",
                    path, exc_info=True,
                )
    return ""
