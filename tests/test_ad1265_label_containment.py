"""AD-1265 round-1 finding 1: a manifest label may not escape its snapshot.

The consumer of ``verify_snapshot`` is an operator asking "can I trust this
snapshot?". Review measured the answer a crafted manifest got: a label of
``../outside.db`` made the verifier size-check, digest and open a database
that the snapshot does **not** contain, and report ``ok`` -- a yes built
from bytes that will not be there at restore time.

Four escapes are pinned here rather than the one that was reported, because
a string check that only knows about ``..`` is trivially routed around:
``..``, an absolute path, a symlink inside the snapshot pointing out of it,
and a Windows drive-qualified label (which is not absolute by POSIX rules
and so survives a naive ``startswith('/')``).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from probos.infrastructure.snapshot_manifest import (
    MANIFEST_NAME,
    STATE_COPIED,
    ManifestEntry,
    is_contained_label,
    read_manifest,
    resolve_contained,
    sha256_file,
)
from probos.infrastructure.snapshot_verify import verify_snapshot

_SNAPSHOT_NAME = "20260824-061728"


def _make_sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (k TEXT)")
        conn.execute("INSERT INTO t VALUES ('v')")
        conn.commit()
    finally:
        conn.close()


def _write_raw_manifest(snapshot_dir: Path, label: str, target: Path) -> None:
    """Hand-write ``manifest.json`` naming ``label`` with ``target``'s bytes.

    Written as raw JSON rather than through :func:`write_manifest` on
    purpose: once the parse-time guard lands, ``ManifestEntry`` refuses to be
    constructed with an escaping label, and this fixture still has to be able
    to put one on disk to prove the reader rejects it.
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 2,
        "snapshot": snapshot_dir.name,
        "created_at": time.time(),
        "complete": True,
        "entries": [
            {
                "label": label,
                "tier": "included",
                "state": STATE_COPIED,
                "size_bytes": target.stat().st_size,
                "sha256": sha256_file(target),
                "error": "",
            }
        ],
    }
    (snapshot_dir / MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _escape_label(snapshot_dir: Path, outside: Path, kind: str) -> str:
    if kind == "dotdot":
        return f"../{outside.name}"
    if kind == "absolute":
        return outside.as_posix()
    if kind == "drive_relative":
        drive = os.path.splitdrive(str(outside))[0]
        if not drive:
            pytest.skip("no drive letter on this platform")
        # "D:name" is drive-relative: not absolute by either os.path.isabs
        # on POSIX or a leading-slash test, which is the point.
        return f"{drive}{os.path.relpath(outside, Path(drive + os.sep))}"
    raise AssertionError(kind)


def _link_out(snapshot_dir: Path, outside_dir: Path) -> str:
    """Make ``snapshot_dir/esc`` point at ``outside_dir``; return the label."""
    link = snapshot_dir / "esc"
    try:
        os.symlink(outside_dir, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if sys.platform != "win32":
            pytest.skip("symlinks unavailable on this platform")
        # Unprivileged Windows cannot create symlinks but can create a
        # junction, which Path.resolve() follows just the same.
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not link.exists():
            pytest.skip(f"cannot create a symlink or junction here: {proc.stderr}")
    return "esc/outside.db"


def _assert_refused_as_an_escape(report: object, what: str) -> None:
    """Refused, and refused *as containment* -- at either of the two layers.

    The parse-time guard catches a label that is escaping as a string, so the
    verifier never sees it and the refusal lands in ``refused_reason``. The
    symlink label is a perfectly ordinary relative string, so it reaches the
    per-entry check and lands in a verdict instead. Both count; "failed for
    some other reason" does not, which is what makes this discriminate --
    against the unfixed code the drive-relative label also failed, as
    "absent from the snapshot".
    """
    assert report.ok is False, f"{what} verified bytes the snapshot lacks"
    if report.refused_reason:
        assert "present but was rejected" in report.refused_reason, report.render()
        return
    assert report.failed, report.render()
    assert report.failed[0].reason.startswith("label resolves outside"), (
        report.render()
    )


# ---------------------------------------------------------------------------
# the reported escape, and the three ways around a naive fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dotdot", "absolute", "drive_relative"])
async def test_verify_snapshot_refuses_a_label_that_names_bytes_outside(
    tmp_path: Path, kind: str,
) -> None:
    snapshot = tmp_path / "promoted" / _SNAPSHOT_NAME
    outside = tmp_path / "promoted" / "outside.db"
    _make_sqlite_db(outside)
    label = _escape_label(snapshot, outside, kind)
    _write_raw_manifest(snapshot, label, outside)

    report = await verify_snapshot(snapshot)

    _assert_refused_as_an_escape(report, f"a {kind} label")


@pytest.mark.asyncio
async def test_the_verifier_refuses_an_escaping_label_even_if_parsing_let_it_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two guards are independent, so neither may be load-bearing alone.

    ``read_manifest`` now rejects ``../outside.db`` before the verifier sees
    it, which would leave the reader-side check untested and free to rot.
    This hands the verifier the manifest the parser refuses to build.
    """
    import probos.infrastructure.snapshot_verify as verify_module

    snapshot = tmp_path / "promoted" / _SNAPSHOT_NAME
    snapshot.mkdir(parents=True)
    outside = tmp_path / "promoted" / "outside.db"
    _make_sqlite_db(outside)

    class _Entry:
        label = "../outside.db"
        size_bytes = outside.stat().st_size
        sha256 = sha256_file(outside)

    class _Manifest:
        complete = True
        failed: list[object] = []
        present = [_Entry()]

    monkeypatch.setattr(verify_module, "read_manifest", lambda _dir: _Manifest())
    report = await verify_snapshot(snapshot)

    assert report.ok is False
    assert report.failed[0].reason.startswith("label resolves outside"), (
        report.render()
    )


@pytest.mark.asyncio
async def test_verify_snapshot_refuses_a_symlink_that_leaves_the_snapshot(
    tmp_path: Path,
) -> None:
    """A pure string check cannot see this one: the label is ``esc/outside.db``."""
    snapshot = tmp_path / "promoted" / _SNAPSHOT_NAME
    snapshot.mkdir(parents=True)
    outside_dir = tmp_path / "elsewhere"
    _make_sqlite_db(outside_dir / "outside.db")
    label = _link_out(snapshot, outside_dir)
    _write_raw_manifest(snapshot, label, outside_dir / "outside.db")

    report = await verify_snapshot(snapshot)

    _assert_refused_as_an_escape(report, "a symlink out of the snapshot")


@pytest.mark.asyncio
async def test_a_contained_label_still_verifies(tmp_path: Path) -> None:
    """PREMISE ASSERTION: the fixture builds a manifest that CAN verify.

    Without this the four refusals above are satisfied by any breakage --
    a fixture that never produced a verifiable snapshot would pass them all.
    """
    snapshot = tmp_path / "promoted" / _SNAPSHOT_NAME
    inside = snapshot / "data" / "alpha.db"
    _make_sqlite_db(inside)
    _write_raw_manifest(snapshot, "data/alpha.db", inside)

    report = await verify_snapshot(snapshot)

    assert report.ok is True, report.render()


# ---------------------------------------------------------------------------
# defence in depth: the label never survives into a parsed manifest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["../outside.db", "a/../../outside.db", "/etc/passwd", "C:/Windows/x.db",
     "C:x.db", "\\\\host\\share\\x.db", "data\\..\\..\\outside.db", ""],
)
def test_an_escaping_label_cannot_be_constructed(label: str) -> None:
    with pytest.raises(ValueError, match="outside the snapshot"):
        ManifestEntry(
            label=label, tier="included", state=STATE_COPIED,
            size_bytes=1, sha256="0" * 64,
        )


def test_read_manifest_refuses_a_manifest_carrying_an_escaping_label(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / _SNAPSHOT_NAME
    outside = tmp_path / "outside.db"
    _make_sqlite_db(outside)
    _write_raw_manifest(snapshot, "../outside.db", outside)

    assert read_manifest(snapshot) is None


def test_contained_labels_are_accepted(tmp_path: Path) -> None:
    """PREMISE ASSERTION for the guard itself: it is not refusing everything."""
    for label in ("data/alpha.db", "data/nested/beta.db", "data\\alpha.db"):
        assert is_contained_label(label) is True, label
        assert resolve_contained(tmp_path, label) is not None, label


def test_resolve_contained_rejects_a_symlink_out_but_keeps_one_that_stays_in(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / _SNAPSHOT_NAME
    (snapshot / "data").mkdir(parents=True)
    (snapshot / "data" / "alpha.db").write_bytes(b"x")
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    label = _link_out(snapshot, outside_dir)

    assert resolve_contained(snapshot, label) is None
    assert resolve_contained(snapshot, "data/alpha.db") is not None
