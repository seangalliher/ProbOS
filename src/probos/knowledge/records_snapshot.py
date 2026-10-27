"""AD-1341 S6 (#1569): the Ship's Records snapshot a ``--full`` reset keeps before it deletes Ship's Records.

AD-524's unbuilt item (1). Before a tier 3 reset deletes ``{data_dir}/ship-records``, ``probos reset`` copies every
regular file in it, byte for byte, into one ZIP file beside the Ship's Archive:
``{archive_dir}/ship-records-snapshots/{timeline_id}/{started}_{ended}.zip``, keyed by the ship's instance id (the
ship's DID is ``did:probos:{timeline_id}``) and the generation's dates. Inside is one BagIt bag (RFC 8493) named after
the file: ``bagit.txt``, ``bag-info.txt``, ``manifest-sha256.txt`` and the payload under ``data/``, so an extracted
snapshot can be checked by any BagIt validator.

- A snapshot is the Captain's copy, never knowledge. No agent, service or Oracle tier reads it and it is not an
  archive entry, so it holds every classification, as Ship's Records do. ``archive_ledger`` records it, and only the
  Captain's ``probos archive erase-snapshot`` removes it.
- Two top-level directories are left out: ``.git`` (the history; the working tree is what the promotion read) and
  ``procedures`` (the Cognitive JIT procedures' YAML copies: a procedure's body stays in its store, as nature).
- Every other entry must be a regular file or a directory that can be read now. A link or junction (never followed),
  a special file, a file that cannot be read, or one whose size changes while it is copied refuses the snapshot, and
  with it the reset, before anything is deleted. So does a tree of more than ``SNAPSHOT_MAX_FILES`` files or
  ``SNAPSHOT_MAX_BYTES`` bytes.
- The file is written under a temporary name beside its final one, flushed to disk, read back and checked against
  what was written, and only then published (``PreparedSnapshot.publish``: one ``os.replace``). No snapshot is ever
  written over. A file's modification time is not kept: every member carries the snapshot's time.
- Synchronous: the offline reset is its one caller.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

#: The directory beside the Ship's Archive's database that holds the snapshots.
SNAPSHOT_DIR_NAME = "ship-records-snapshots"

#: The top-level Ship's Records directories a snapshot leaves out (the module docstring says why).
SNAPSHOT_EXCLUDED = (".git", "procedures")

#: A larger tree refuses the snapshot, and the reset with it; ``--skip-promotion REASON`` skips both.
SNAPSHOT_MAX_FILES = 100_000
SNAPSHOT_MAX_BYTES = 2 * 1024**3

_BAGIT_TXT = "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
_CHUNK = 1024 * 1024
_STAMP = "%Y%m%dT%H%M%SZ"
_TIMELINE = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_TIMELINE_SEGMENT = re.compile(_TIMELINE)
_RELATIVE_PATH = re.compile(rf"{_TIMELINE}/\d{{8}}T\d{{6}}Z_\d{{8}}T\d{{6}}Z\.zip")

_ZipStamp = tuple[int, int, int, int, int, int]


class SnapshotRefused(Exception):
    """What a snapshot cannot hold or cannot read. The reset refuses, and nothing is deleted."""


@dataclass(frozen=True)
class SnapshotFile:
    """One regular file a snapshot holds: its path under the Ship's Records root ("/"-separated) and its size."""

    path: str
    size: int


@dataclass(frozen=True)
class SnapshotPlan:
    """What a snapshot of a Ship's Records root would hold, in path order. Building it opens no file."""

    files: tuple[SnapshotFile, ...]
    total_bytes: int


@dataclass(frozen=True)
class SnapshotResult:
    """A checked snapshot: its path under ``SNAPSHOT_DIR_NAME``, the ZIP file's SHA-256, and what it holds."""

    relative_path: str
    sha256: str
    file_count: int
    total_bytes: int
    generation_started: str
    generation_ended: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class PreparedSnapshot:
    """A snapshot written and checked under its temporary name. ``publish`` puts it in place; ``discard`` removes it."""

    result: SnapshotResult
    temp_path: Path
    final_path: Path

    def publish(self) -> None:
        """One ``os.replace``. A file that appeared at the final name meanwhile is never written over."""
        if os.path.lexists(self.final_path):  # a file that appeared meanwhile is never written over
            raise SnapshotRefused(f"a snapshot named {self.result.relative_path} exists already")
        os.replace(self.temp_path, self.final_path)

    def discard(self) -> None:
        """Remove the temporary file, if it is still there."""
        _remove_quietly(self.temp_path)


def is_snapshot_relative_path(value: object) -> bool:
    """Whether ``value`` is a snapshot's name as ``snapshot_relative_path`` builds it: one directory, one ZIP file."""
    return type(value) is str and _RELATIVE_PATH.fullmatch(value) is not None


def snapshot_relative_path(timeline_id: str, started: datetime, ended: datetime) -> str:
    """``{timeline_id}/{started}_{ended}.zip``, both in UTC. An instance id that cannot name a directory refuses."""
    if type(timeline_id) is not str or _TIMELINE_SEGMENT.fullmatch(timeline_id) is None:
        raise SnapshotRefused("the ship's instance id cannot name a snapshot directory (1-64 letters, digits, . _ -)")
    return f"{timeline_id}/{_stamp(started)}_{_stamp(ended)}.zip"


def plan_snapshot(root: Path) -> SnapshotPlan:
    """Every regular file a snapshot of ``root`` would hold, in path order. Reads names and sizes; opens no file.

    A missing root is an empty plan (a vessel with no Ship's Records). A link or junction, a special file or a tree
    beyond the bounds refuses. Any ``OSError`` propagates: a directory that cannot be listed is never taken for an
    empty one (an explicit walk, as S4 A5 chose over ``os.walk``, which swallows them).
    """
    if not os.path.lexists(root):
        return SnapshotPlan(files=(), total_bytes=0)
    if not root.is_dir():
        raise SnapshotRefused(f"Ship's Records at {root} is not a directory")
    files: list[SnapshotFile] = []
    total = 0
    pending: list[tuple[str, str]] = [("", str(root))]
    while pending:
        prefix, directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = f"{prefix}{entry.name}"
                if entry.is_symlink() or entry.is_junction():  # never followed: it may lead out of Ship's Records
                    raise SnapshotRefused(f"{relative} is a link; a snapshot copies only what Ship's Records hold")
                if entry.is_dir(follow_symlinks=False):
                    if not (prefix == "" and entry.name in SNAPSHOT_EXCLUDED):  # .git/ and procedures/ stay out
                        pending.append((f"{relative}/", entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise SnapshotRefused(f"{relative} is not a regular file")
                size = entry.stat(follow_symlinks=False).st_size
                files.append(SnapshotFile(path=relative, size=size))
                total += size
                if len(files) > SNAPSHOT_MAX_FILES or total > SNAPSHOT_MAX_BYTES:
                    raise SnapshotRefused(
                        f"Ship's Records exceed the snapshot's bound of {SNAPSHOT_MAX_FILES} files and "
                        f"{SNAPSHOT_MAX_BYTES} bytes"
                    )
    files.sort(key=lambda item: item.path)
    return SnapshotPlan(files=tuple(files), total_bytes=total)


def prepare_snapshot(
    root: Path, snapshots_dir: Path, *, timeline_id: str, ship_did: str, started: datetime, ended: datetime,
) -> PreparedSnapshot | None:
    """Write and check a snapshot of ``root`` under a temporary name; None when ``root`` holds no file to keep.

    Raises ``SnapshotRefused`` for what the snapshot cannot hold, and any ``OSError`` or ``zipfile`` error as it comes.
    The temporary file is removed on every failure, and nothing is ever written at the final name here.
    """
    relative = snapshot_relative_path(timeline_id, started, ended)
    plan = plan_snapshot(root)
    if not plan.files:
        return None
    final = snapshots_dir / relative
    if os.path.lexists(final):  # a snapshot is never written over
        raise SnapshotRefused(f"a snapshot named {relative} exists already")
    info = _bag_info(plan, timeline_id=timeline_id, ship_did=ship_did, started=started, ended=ended)
    final.parent.mkdir(parents=True, exist_ok=True)
    temp = final.with_name(f".{final.name}.partial")
    bag = final.stem
    stamp: _ZipStamp = tuple(_utc(ended).timetuple()[:6])  # type: ignore[assignment]
    raw = open(temp, "xb")  # exclusive: never another attempt's file  # noqa: SIM115
    try:
        with raw:
            digests = _write_bag(raw, root, bag, plan, info, stamp)
            raw.flush()
            os.fsync(raw.fileno())
        sha256 = _verify_bag(temp, bag, plan, digests)
    except BaseException:
        _remove_quietly(temp)
        raise
    return PreparedSnapshot(
        result=SnapshotResult(
            relative_path=relative, sha256=sha256, file_count=len(plan.files), total_bytes=plan.total_bytes,
            generation_started=_iso(started), generation_ended=_iso(ended),
            paths=tuple(item.path for item in plan.files),
        ),
        temp_path=temp,
        final_path=final,
    )


def _write_bag(
    raw: BinaryIO, root: Path, bag: str, plan: SnapshotPlan, info: str, stamp: _ZipStamp,
) -> dict[str, str]:
    """The bag's payload, then its manifest, ``bag-info.txt`` and ``bagit.txt``; each payload file's SHA-256."""
    digests: dict[str, str] = {}
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bag_zip:
        for item in plan.files:
            digests[item.path] = _copy_member(bag_zip, root / item.path, f"{bag}/data/{item.path}", item, stamp)
        manifest = "".join(f"{digests[item.path]}  data/{_bagit_path(item.path)}\n" for item in plan.files)
        _write_text(bag_zip, f"{bag}/manifest-sha256.txt", manifest, stamp)
        _write_text(bag_zip, f"{bag}/bag-info.txt", info, stamp)
        _write_text(bag_zip, f"{bag}/bagit.txt", _BAGIT_TXT, stamp)
    return digests


def _copy_member(
    bag_zip: zipfile.ZipFile, source: Path, name: str, item: SnapshotFile, stamp: _ZipStamp,
) -> str:
    """Copy one file into the bag, hashing what is read. A size other than the listed one refuses."""
    member = zipfile.ZipInfo(name, date_time=stamp)
    member.compress_type = zipfile.ZIP_DEFLATED
    digest = hashlib.sha256()
    copied = 0
    with open(source, "rb") as reader, bag_zip.open(member, "w", force_zip64=True) as writer:
        while chunk := reader.read(_CHUNK):
            copied += len(chunk)
            if copied > item.size:  # it grew after it was listed; stop reading it
                raise SnapshotRefused(f"{item.path} changed while it was copied")
            digest.update(chunk)
            writer.write(chunk)
    if copied != item.size:  # it shrank after it was listed
        raise SnapshotRefused(f"{item.path} changed while it was copied")
    return digest.hexdigest()


def _write_text(bag_zip: zipfile.ZipFile, name: str, text: str, stamp: _ZipStamp) -> None:
    member = zipfile.ZipInfo(name, date_time=stamp)
    member.compress_type = zipfile.ZIP_DEFLATED
    bag_zip.writestr(member, text.encode("utf-8"))


def _verify_bag(temp: Path, bag: str, plan: SnapshotPlan, digests: dict[str, str]) -> str:
    """Read the written file back: its members in order, each payload file's SHA-256; return the file's SHA-256."""
    expected = [f"{bag}/data/{item.path}" for item in plan.files]
    expected += [f"{bag}/manifest-sha256.txt", f"{bag}/bag-info.txt", f"{bag}/bagit.txt"]
    with zipfile.ZipFile(temp) as bag_zip:
        if bag_zip.namelist() != expected:
            raise SnapshotRefused("the snapshot read back does not list what was written")
        for item in plan.files:
            if _digest(bag_zip.open(f"{bag}/data/{item.path}")) != digests[item.path]:  # zipfile also checks each CRC
                raise SnapshotRefused(f"{item.path} does not read back as it was written")
    return _digest(open(temp, "rb"))  # noqa: SIM115 -- closed by _digest


def _digest(stream: BinaryIO) -> str:
    """The SHA-256 of a stream, read in chunks; the stream is closed."""
    digest = hashlib.sha256()
    with stream:
        while chunk := stream.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _bag_info(plan: SnapshotPlan, *, timeline_id: str, ship_did: str, started: datetime, ended: datetime) -> str:
    """``bag-info.txt``: RFC 8493's reserved elements, then ProbOS's own (the ship, its timeline and dates)."""
    if type(ship_did) is not str or not ship_did.strip() or not ship_did.isprintable():
        raise SnapshotRefused("the ship's DID cannot stand in the snapshot's metadata")
    return (
        f"Bagging-Date: {_utc(ended):%Y-%m-%d}\n"
        f"Payload-Oxum: {plan.total_bytes}.{len(plan.files)}\n"
        f"External-Identifier: {ship_did}\n"
        f"ProbOS-Timeline: {timeline_id}\n"
        f"ProbOS-Generation-Started: {_iso(started)}\n"
        f"ProbOS-Generation-Ended: {_iso(ended)}\n"
        f"ProbOS-Excluded: {' '.join(name + '/' for name in SNAPSHOT_EXCLUDED)}\n"
        "ProbOS-Source: AD-1341 S6, probos reset --full\n"
    )


def _bagit_path(path: str) -> str:
    """RFC 8493 2.1.3: a manifest path percent-encodes "%", CR and LF, and only those."""
    return path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _utc(moment: datetime) -> datetime:
    if type(moment) is not datetime or moment.tzinfo is None:
        raise ValueError("AD-1341 S6: a snapshot's times are datetimes with an offset")
    return moment.astimezone(UTC)


def _stamp(moment: datetime) -> str:
    return _utc(moment).strftime(_STAMP)


def _iso(moment: datetime) -> str:
    return _utc(moment).strftime("%Y-%m-%dT%H:%M:%SZ")


def _remove_quietly(path: Path) -> None:
    """Remove a temporary file. A failure is logged, never raised over the error that led here."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("AD-1341 S6: the temporary snapshot %s could not be removed", path, exc_info=True)
