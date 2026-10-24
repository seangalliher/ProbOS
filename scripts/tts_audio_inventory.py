"""BF-918 (#1626): inventory the spoken-reply WAVs stored before the ``tts_audio`` origin
existed. Read-only: it prints what it found and changes nothing, so it may run while
ProbOS runs (a database being written may then be reported ``unreadable``, which keeps
every candidate; run it with ProbOS stopped for a clean count).

Until BF-918 every reply the server spoke was stored as a ``chat_attachment``, which
never expires (on 2026-10-23 the live store held 1,126 WAV files, 962 of them indexed).
New speech is stored as ``tts_audio`` and the reaper deletes it by age. Deleting the old
ones is a later decision of the Captain's (review round 1 withdrew this tool's delete:
it could not yet show a WAV unreferenced everywhere a reference can live).

A WAV is a candidate only when every one of these holds:

* its index entry says ``chat_attachment`` (or no origin) and ``audio/wav``, and the
  file ``<id>.wav`` exists;
* its header is exactly the 44-byte header Piper writes: ``RIFF`` with the file's size
  less 8, ``WAVE``, a 16-byte ``fmt `` chunk for PCM, mono, 16 bits, 16000 or 22050 Hz,
  byte rate twice the rate and block alignment 2, then ``data`` with the file's size
  less 44, non-empty and even;
* it was written more than ``--min-age-days`` ago (default 1);
* its id occurs in no record under the data directory, the attachment directory
  excepted. Every file is read, whatever its name, and an ``episode_archive`` table is
  decoded row by row with the archive's own decoder (its payloads are compressed). A
  file or archive row that cannot be read, a directory that cannot be listed, and a
  link or junction to a directory other than the attachment directory (never followed)
  keep every candidate; ``unreadable`` names each, a directory with a trailing path
  separator.

The data directory given is resolved first. Under it, ``<data-dir>/attachments`` is the
one directory read through a link or junction, as the vessel reads its store (the store
resolves its root); the report's ``attachments_link`` names the target and is ``null``
for a plain directory. No other link to a directory is followed.

WAV files with no index entry are counted (``unindexed_wavs``; ``.wav`` is matched as the
OS matches names, so in any case on Windows) and never candidates. An attachment directory
that cannot be listed, or that links to nothing, stops the run, as an unreadable index does.

Usage (PowerShell)::

    d:/ProbOS/.venv/Scripts/python.exe scripts/tts_audio_inventory.py --data-dir "$env:LOCALAPPDATA\\ProbOS\\data"
    ... --list                       # also print every candidate id
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from probos.cognitive.episode_archive import EpisodeArchiveIntegrityError, decode_payload  # noqa: E402

EXIT_OK = 0
_PIPER_RATES = frozenset({16000, 22050})
# RIFF, its size, WAVE, "fmt ", its size, format, channels, rate, byte rate, block align, bits, "data", its size.
_WAV_HEADER = "<4sI4s4sIHHIIHH4sI"
_WAV_HEADER_BYTES = 44
_SQLITE_MAGIC = b"SQLite format 3\x00"
_HASH = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_CHUNK = 16 * 1024 * 1024
_KEPT_REASONS = ("other_origin", "missing_file", "not_piper_shaped", "too_young", "referenced")


@dataclass
class Inventory:
    """What one run found. ``candidates`` maps an id to its size in bytes; ``attachments_link``
    is the real path of the attachment directory when that directory is a link or junction."""

    wav_entries: int = 0
    unindexed_wavs: int = 0
    candidates: dict[str, int] = field(default_factory=dict)
    kept: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_KEPT_REASONS, 0))
    unreadable: list[str] = field(default_factory=list)
    attachments_link: str | None = None


def piper_shaped(path: Path) -> bool:
    """True only for the canonical 44-byte header Piper writes, with sizes that match the file."""
    try:
        with path.open("rb") as fh:
            head = fh.read(_WAV_HEADER_BYTES)
            size = os.fstat(fh.fileno()).st_size
    except OSError:
        return False
    if len(head) != _WAV_HEADER_BYTES:
        return False
    (riff, riff_size, wave, fmt_id, fmt_size, fmt, channels, rate,
     byte_rate, align, bits, data_id, data_size) = struct.unpack(_WAV_HEADER, head)
    return (
        (riff, wave, fmt_id, data_id) == (b"RIFF", b"WAVE", b"fmt ", b"data")
        and riff_size == size - 8
        and fmt_size == 16
        and (fmt, channels, bits) == (1, 1, 16)
        and rate in _PIPER_RATES
        and byte_rate == rate * 2
        and align == 2
        and 0 < data_size == size - _WAV_HEADER_BYTES
        and data_size % 2 == 0
    )


def _scan(data: bytes, targets: set[bytes], found: set[str]) -> None:
    for match in _HASH.finditer(data):
        if match.group() in targets:
            found.add(match.group().decode("ascii"))


def _scan_file(path: Path, targets: set[bytes], found: set[str]) -> bytes:
    """Scan every byte of ``path`` in chunks (an id across a chunk boundary is still
    seen); return the file's first 16 bytes."""
    head = b""
    carry = b""
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            head = head or chunk[:16]
            block = carry + chunk
            _scan(block, targets, found)
            carry = block[-65:]
    return head


def _scan_episode_archive(path: Path, targets: set[bytes], found: set[str]) -> None:
    """Decode every row of an ``episode_archive`` table in the SQLite file ``path``.

    The archive stores each episode as zlib-compressed JSON, so its ids are not in the
    file's bytes. Rows are decoded with the archive's own decoder; a row it rejects
    raises, and the caller keeps every candidate. Opened read-only and immutable, so
    nothing is created beside the file.
    """
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "episode_archive" not in tables:
            return
        rows = connection.execute("SELECT episode_id, content_hash, payload_format, payload FROM episode_archive")
        for episode_id, content_hash, payload_format, payload in rows:
            record = decode_payload(episode_id, content_hash, payload_format, payload)
            text = json.dumps([record.document, dict(record.metadata)], ensure_ascii=True)
            _scan(text.encode("ascii"), targets, found)
    finally:
        connection.close()


def _record_files(data_dir: Path, attachments_dir: Path, unreadable: list[str]) -> list[Path]:
    """Every entry under ``data_dir`` that is not a directory, outside ``attachments_dir``, sorted.

    Review round 2 (F1): ``Path.rglob`` skips a directory it cannot list without a word, so
    a reference inside it was missed and nothing said so; ``os.walk`` hands that error to
    ``onerror``. A directory that cannot be listed (refused, or gone since its parent was
    listed) and a link or junction to a directory are added to ``unreadable`` with a
    trailing separator, which keeps every candidate. A link is never followed: what it
    holds is not this data directory's, and it may loop (``os.walk`` alone would follow a
    Windows junction).
    """
    files: list[Path] = []

    def not_listed(error: OSError) -> None:
        unreadable.append(f"{error.filename}{os.sep}")  # refused, or gone since its parent was listed

    for directory, subdirs, names in os.walk(data_dir, onerror=not_listed):
        here = Path(directory)
        walked: list[str] = []
        for name in subdirs:
            child = here / name
            if child == attachments_dir:  # the store itself: its index names every id
                continue
            if os.path.islink(child) or os.path.isjunction(child):  # never followed
                unreadable.append(f"{child}{os.sep}")  # a link to a directory: its records are not read
                continue
            walked.append(name)
        subdirs[:] = walked
        files.extend(here / name for name in names)
    return sorted(files)


def referenced_ids(data_dir: Path, attachments_dir: Path, wanted: set[str]) -> tuple[set[str], list[str]]:
    """The ids in ``wanted`` that occur in a record under ``data_dir``, and everything that
    could not be read (then every id counts as referenced): files, and directories named
    with a trailing separator.

    Every regular file outside ``attachments_dir`` is read whatever its name: logs, WAL
    files and uncompressed backups included. A SQLite database is also opened, and an
    ``episode_archive`` table in it is decoded row by row.
    """
    if not wanted:
        return set(), []
    targets = {sha.encode("ascii") for sha in wanted}
    found: set[str] = set()
    unreadable: list[str] = []
    for path in _record_files(data_dir, attachments_dir, unreadable):
        if not path.is_file():  # a pipe, a socket or a link to nothing holds no record
            continue
        try:
            is_sqlite = _scan_file(path, targets, found) == _SQLITE_MAGIC
            if is_sqlite:
                _scan_episode_archive(path, targets, found)
        except (OSError, sqlite3.Error, EpisodeArchiveIntegrityError):
            unreadable.append(str(path))
    if unreadable:
        return set(wanted), sorted(unreadable)
    return found, unreadable


def take_inventory(data_dir: Path, attachments_dir: Path, *, min_age_days: float, now: float) -> Inventory:
    """Classify every indexed WAV. Reads only.

    Review round 3 (A7): an attachment directory that is a link or junction is read through,
    as the vessel reads its store, and its target is recorded in ``attachments_link``. A link
    to nothing is a store that cannot be listed: the run stops.
    """
    inventory = Inventory()
    if os.path.islink(attachments_dir) or os.path.isjunction(attachments_dir):  # read through, and named
        inventory.attachments_link = os.path.realpath(attachments_dir)
    index_path = attachments_dir / ".index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        index = {}
    if not isinstance(index, dict):
        raise ValueError(f"{index_path} is not an attachment index")
    # Review round 2: the store's listing raises like its index does; Path.glob skips a refusal silently.
    try:
        with os.scandir(attachments_dir) as entries:
            names = [entry.name for entry in entries]
    except FileNotFoundError:  # no store yet: nothing is indexed and nothing unindexed
        if inventory.attachments_link is not None:  # a link to nothing: the store cannot be listed
            raise
        names = []
    # Review round 3 (A-R3-2): ".wav" is matched as the OS matches names (any case on Windows), as Path.glob did.
    inventory.unindexed_wavs = sum(1 for name in names if os.path.normcase(name).endswith(".wav") and name[:-4] not in index)
    cutoff = now - min_age_days * 86400
    eligible: dict[str, int] = {}
    for sha, entry in sorted(index.items()):
        if not isinstance(entry, dict) or entry.get("mime") != "audio/wav":
            continue
        inventory.wav_entries += 1
        if entry.get("origin", "chat_attachment") != "chat_attachment":
            inventory.kept["other_origin"] += 1
            continue
        path = attachments_dir / f"{sha}.wav"
        if not path.is_file():
            inventory.kept["missing_file"] += 1
            continue
        if not piper_shaped(path):
            inventory.kept["not_piper_shaped"] += 1
            continue
        written_at = entry.get("written_at")
        if not isinstance(written_at, (int, float)) or written_at > cutoff:
            inventory.kept["too_young"] += 1
            continue
        eligible[sha] = path.stat().st_size
    referenced, inventory.unreadable = referenced_ids(data_dir, attachments_dir, set(eligible))
    for sha, size in eligible.items():
        if sha in referenced:
            inventory.kept["referenced"] += 1
        else:
            inventory.candidates[sha] = size
    return inventory


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BF-918: inventory the spoken WAVs stored before the tts_audio origin (read-only).",
    )
    parser.add_argument("--data-dir", required=True, help="the vessel's data directory, e.g. %%LOCALAPPDATA%%\\ProbOS\\data")
    parser.add_argument("--min-age-days", type=float, default=1.0)
    parser.add_argument("--list", action="store_true", help="also print every candidate id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    started = time.monotonic()
    data_dir = Path(args.data_dir).resolve()
    # Review round 1 (A3): one root. The store read is always the data directory's own.
    attachments_dir = data_dir / "attachments"
    inventory = take_inventory(data_dir, attachments_dir, min_age_days=args.min_age_days, now=time.time())
    report: dict[str, Any] = {
        "data_dir": str(data_dir),
        "attachments_link": inventory.attachments_link,
        "wav_entries": inventory.wav_entries,
        "unindexed_wavs": inventory.unindexed_wavs,
        "candidates": len(inventory.candidates),
        "candidate_bytes": sum(inventory.candidates.values()),
        "kept": inventory.kept,
        "unreadable": inventory.unreadable,
        "seconds": round(time.monotonic() - started, 1),
    }
    if args.list:
        report["candidate_ids"] = sorted(inventory.candidates)
    print(json.dumps(report, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
