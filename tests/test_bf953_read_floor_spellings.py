"""BF-953 (#1752): ``resolve_read_path`` returns one decision for every spelling of one file.

A path is decided the same way however it is spelled: for the floor (a directory root and a file root), for
the exempt roots that lift the floor, and for the permitted roots; and the path returned is the resolved
path, which names the file the decision was made on. The Windows spellings are built from fixture files this
test creates. A spelling the host does not serve is skipped once its premise (it names the same file as the
ordinary spelling) fails, so a skip is never a pass. The textual canonicaliser, the identity helper and the
POSIX rule run on every platform.

Amendment 1 (review round 2, T11 to T22): identity only ever adds a refusal at the floor. A share spelling is
never admitted by an exempt or a permitted root its text does not name (T1 to T3 expect the refusal), a floor
that cannot be read refuses a share spelling (T12), an exemption stands where its text puts it in the path
and not where its root is spelled, and a floor file root outranks the workspace that encloses it (T13, T17), a
configured workspace root is spelled as the path under it is (T14), the spelling ``list_files`` shows has no
namespace prefix (T15 here; BF-948's T13 and T14 through the verified reader), and the final component is
decided by the file it names: a floor file root or a credential name is refused in every spelling of its final
component that a stream suffix, trailing dots and spaces and (for a name) another case make, on or off disk
(T18 to T21; on POSIX the names stay distinct: T22). That is a deny-side text rule, not a statement about files:
in the extended namespace a name that ends in a dot or a space can be another file, and it is refused too (L14).

Amendment 2 (review round 3, T23 to T28): a floor file root is compared by the file its own final component names,
as a candidate is (T23, T24, T28), a workspace root that does not resolve stays in the read policy's roots as it was
composed (T25), a listing shows a match only in a spelling that names it in the ordinary namespace (T26; BF-948's
T15 through the verified reader), and what T16 shows about counts of parts is pinned where the count is used (T27).

Amendment 3 (review round 4, T29 to T33): a listing shows a match only in a spelling the verified reader's rules on the
text admit, on every platform (T29, T30: the reader's location gate and its final-name rule; T31: the pinned directory's
own verdict), the function calls no filesystem function (T32), and a directory that holds names the reader's gate refuses
is listed without them, from an ordinary and an extended-prefix base, with every name it lists opened by the verified
reader (T33, Windows). None of these says that a listed name opens: BF-953 L18 lists what a listing cannot promise.

Amendment 4 (review round 5, T34 and T35): the listing admits exactly what the verified reader's text path admits: its
location gate on the file, its location gate on the file's direct parent (the directory the reader pins), and its
child-name rule on the final name. T34 checks that as a property over a generated corpus against the reader's own gate and
child-name rule (the POSIX shape on every platform, the Windows shape on Windows); T35 crosses the seam with real files and
the real reader and tool (a reserved device name as the direct parent is neither listed nor read; one above it is read, and
listed off Windows). T29 and T30 are corrected: only the direct parent is refused, not every ancestor.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from probos.config import SystemConfig
from probos.security import file_access
from probos.security.file_access import FileAccessDenied, protected_write_refusal, resolve_read_path
from tests.test_bf948_list_files_read_policy import SECRET_NAME, _OUTSIDE, _PROTECTED, _link, _list, _runtime, _scene, _unlink

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"
_FLOOR_REASON = "path is protected: the runtime's data directory or a config file"
_OUTSIDE_REASON = "path is outside every readable root"
_UNVERIFIED_REASON = "path cannot be verified against the protected roots"
_LEAF_REASON = "that file holds credentials and is not readable"

_FAMILIES = [
    "forward slashes", "doubled separator", "dot segment", "dotdot via sibling dir", "dotdot via missing dir",
    "swapped case", "8.3 short name", "trailing dot", "trailing space", "default stream suffix", "device prefix",
    "extended prefix", "extended prefix, swapped case", "extended prefix, 8.3",
    "UNC localhost admin share", "UNC 127.0.0.1 admin share", "UNC computer-name admin share",
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
]
# Amendment 1: a spelling that still names a share after its namespace prefix is gone. The floor refuses it by the
# identity of its own chain, and an exempt or a permitted root admits it only if the root's text names it, so where
# the ordinary spelling is admitted by one of those roots these are refused.
_SHARE_FAMILIES = frozenset({
    "UNC localhost admin share", "UNC 127.0.0.1 admin share", "UNC computer-name admin share",
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
})
_PARAMS = list(_FAMILIES)


def _short(text: str) -> str | None:
    """The 8.3 form of the existing path *text* the system gives, or None when the volume gives it none."""
    buffer = ctypes.create_unicode_buffer(1024)
    size = ctypes.windll.kernel32.GetShortPathNameW(text, buffer, len(buffer))  # type: ignore[attr-defined]
    return buffer.value if 0 < size < len(buffer) and buffer.value.lower() != text.lower() else None


def _spellings(target: Path) -> dict[str, str]:
    """Spellings of the existing path *target* (a drive-letter path), built from the path itself."""
    text = str(target)
    drive, rest = os.path.splitdrive(text)
    letter, parent, name = drive[0], str(target.parent), target.name
    parent_rest = rest.rsplit("\\", 1)[0]
    computer = os.environ.get("COMPUTERNAME", "")
    short = _short(text)

    def share(host: str, tail: str = rest) -> str:
        return f"\\\\{host}\\{letter}${tail}"

    spelled = {
        "forward slashes": text.replace("\\", "/"),
        "doubled separator": text.replace("\\", "\\\\", 1),
        "dot segment": f"{parent}\\.\\{name}",
        "dotdot via sibling dir": f"{parent}\\..\\{target.parent.name}\\{name}",
        "dotdot via missing dir": f"{parent}\\no-such-dir-bf953\\..\\{name}",
        "swapped case": text.swapcase(),
        "trailing dot": text + ".",
        "trailing space": text + " ",
        "device prefix": "\\\\.\\" + text,
        "extended prefix": "\\\\?\\" + text,
        "extended prefix, swapped case": "\\\\?\\" + text.swapcase(),
        "UNC localhost admin share": share("localhost"),
        "UNC 127.0.0.1 admin share": share("127.0.0.1"),
        "UNC extended localhost": "\\\\?\\UNC\\localhost\\" + letter + "$" + rest,
        "UNC localhost, dotdot": share("localhost", f"{parent_rest}\\..\\{target.parent.name}\\{name}"),
    }
    if target.is_file():
        spelled["default stream suffix"] = text + "::$DATA"
    if short:
        spelled["8.3 short name"] = short
        spelled["extended prefix, 8.3"] = "\\\\?\\" + short
    if computer:
        spelled["UNC computer-name admin share"] = share(computer)
        spelled["UNC extended computer-name"] = "\\\\?\\UNC\\" + computer + "\\" + letter + "$" + rest
    return spelled


def _spelling_or_none(family: str, target: Path) -> str | None:
    """The *family* spelling of the existing *target*, or None when this host has none or does not serve it."""
    spelling = _spellings(target).get(family)
    if spelling is None:
        return None
    try:
        same = os.path.samestat(os.stat(spelling), os.stat(target))
    except OSError:
        same = False
    return spelling if same else None


def _spelling(family: str, target: Path) -> str:
    spelling = _spelling_or_none(family, target)
    if spelling is None:
        pytest.skip(f"BF-953 premise: this host has no {family} spelling that names {target.name}")
    return spelling


def _fixture(tmp_path: Path) -> SimpleNamespace:
    """A floor directory holding an exempt directory, a config file with a neighbour, a permitted directory and one outside.

    Every name is long, so that the volume gives each an 8.3 name when it makes them."""
    root = tmp_path.resolve()
    lay = SimpleNamespace(
        data=root / "floor data directory",
        work=root / "floor data directory" / "work area directory",
        allowed=root / "allowed directory long name",
        outside=root / "outside directory long name",
        config=root / "config directory long name" / "loaded config long name.yaml",
    )
    for directory in (lay.work, lay.allowed, lay.outside, lay.config.parent):
        directory.mkdir(parents=True)
    lay.floor_note = lay.data / "floor note long name.txt"
    lay.work_note = lay.work / "work note long name.txt"
    lay.allowed_note = lay.allowed / "allowed note long name.txt"
    lay.outside_note = lay.outside / "outside note long name.txt"
    lay.neighbour = lay.config.parent / "neighbour file long name.yaml"
    for note in (lay.floor_note, lay.work_note, lay.allowed_note, lay.outside_note, lay.config, lay.neighbour):
        note.write_bytes(_CONTENT)
    return lay


def _decide(raw: str, *, protected: Any = (), exempt: Any = (), permitted: Any = None) -> tuple[str, str]:
    """The whole decision of one call: ``("admitted", <path returned>)`` or ``("refused", <reason>)``."""
    try:
        resolved = resolve_read_path(
            raw, protected_roots=list(protected), exempt_roots=list(exempt), permitted_roots=permitted,
        )
    except FileAccessDenied as exc:
        return "refused", exc.reason
    return "admitted", str(resolved)


def _other_volume_dir(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A new directory on a local fixed volume other than *tmp_path*'s, removed when the test ends; a skip when there is none."""
    here = os.stat(tmp_path).st_dev
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:  # type: ignore[attr-defined]  # DRIVE_FIXED
            continue
        try:
            if os.stat(root).st_dev == here:
                continue
            made = Path(tempfile.mkdtemp(prefix="bf953-", dir=root)).resolve()
        except OSError:
            continue
        request.addfinalizer(lambda made=made: shutil.rmtree(made, ignore_errors=True))
        return made
    pytest.skip("BF-953 premise: this host has no other local volume to write to")


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(tmp_path: Path, family: str) -> None:
    """T1: each spelling of a file is decided as its ordinary spelling is, against a directory root and a file root of
    the floor, an exempt root under the floor, and a permitted root; so is a file that is not on disk (a missing child of
    a directory, and a file root that is not on disk, whose share spellings are L2's); and the path an
    admitted call returns is the resolved path and names the file. The one exception is the share spellings
    (``_SHARE_FAMILIES``): only the floor decides them by identity, so where the ordinary spelling is admitted by an exempt
    or a permitted root they are refused, with the reason that root's refusal gives."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve(), lay.config.resolve()]
    exempt, permitted = [lay.work.resolve()], [lay.allowed.resolve()]
    cases = [
        (lay.floor_note, {"protected": floor, "exempt": exempt}, "refused", None),
        (lay.config, {"protected": floor}, "refused", None),
        (lay.neighbour, {"protected": floor}, "admitted", None),
        (lay.work_note, {"protected": floor, "exempt": exempt}, "admitted", _FLOOR_REASON),
        (lay.allowed_note, {"permitted": permitted}, "admitted", _OUTSIDE_REASON),
        (lay.outside_note, {"permitted": permitted}, "refused", None),
    ]
    for target, roots, expected, share_reason in cases:
        ordinary = _decide(str(target), **roots)
        assert ordinary[0] == expected, f"premise: the ordinary spelling of {target.name}: {ordinary}"
        spelled = _decide(_spelling(family, target), **roots)
        if share_reason is not None and family in _SHARE_FAMILIES:
            assert spelled == ("refused", share_reason), f"{family} of {target.name}: {spelled}"
            continue
        assert spelled[0] == expected, f"{family} of {target.name}: {spelled}"
        if expected == "refused":
            assert spelled[1] == ordinary[1], f"{family} of {target.name}: another reason"
        else:
            assert Path(spelled[1]) == Path(spelled[1]).resolve(), "the path returned is a resolved path"
            assert os.path.samestat(os.stat(spelled[1]), os.stat(target)), "the path returned names the file"
    absent_root = lay.config.parent / "absent config long name.yaml"
    floor_absent = [*floor, absent_root.resolve()]
    missing = [
        (lay.data, {"protected": floor}, "refused", None, "missing note long name.txt"),
        (lay.work, {"protected": floor, "exempt": exempt}, "admitted", _FLOOR_REASON, "missing note long name.txt"),
        (lay.allowed, {"permitted": permitted}, "admitted", _OUTSIDE_REASON, "missing note long name.txt"),
        (lay.outside, {"permitted": permitted}, "refused", None, "missing note long name.txt"),
        (lay.config.parent, {"protected": floor_absent}, "refused", "L2", absent_root.name),  # an absent file root
    ]
    for directory, roots, expected, share_reason, absent in missing:
        assert _decide(str(directory / absent), **roots)[0] == expected, "premise: the ordinary spelling"
        if family == "default stream suffix":
            # The family is a stream of an existing file, so a directory has no spelling of it: the child's own suffix.
            assert _decide(str(directory / absent) + "::$DATA", **roots)[0] == expected, f"{family}, not on disk"
            continue
        spelling = _spelling_or_none(family, directory)
        if spelling is None:  # a premise: this host does not serve the family for a directory
            continue
        spelled = _decide(spelling + "\\" + absent, **roots)
        if share_reason == "L2" and family in _SHARE_FAMILIES:
            continue  # L2: a share spelling of a file root that is not on disk has no identity to compare
        if share_reason is not None and family in _SHARE_FAMILIES:
            assert spelled == ("refused", share_reason), f"{family}, not on disk: {spelled}"
        else:
            assert spelled[0] == expected, f"{family}, not on disk"


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_read_file_decides_every_spelling_alike(tmp_path: Path, family: str) -> None:
    """T2: ``ReadFileTool`` answers every spelling of a file as it answers the ordinary one; a share spelling of a file a
    permitted root admits is answered as outside every readable root."""
    scene = _scene(tmp_path)
    floor_note = scene.data / "floor note long name.txt"
    allowed_note = scene.allowed / "allowed note long name.txt"
    outside_note = scene.outside / "outside note long name.txt"
    for note in (floor_note, allowed_note, outside_note):
        note.write_bytes(_CONTENT)
    cases = [
        (floor_note, [], _READ_PROTECTED),
        (outside_note, [scene.allowed], _READ_OUTSIDE),
        (allowed_note, [scene.allowed], None),
    ]
    for note, read_roots, refusal in cases:
        tool = ReadFileTool(_runtime(scene, read_roots=read_roots))
        ordinary = await tool.invoke({"path": str(note)})
        assert ordinary.error == refusal, f"premise: the ordinary spelling of {note.name}: {ordinary.error}"
        spelled = await tool.invoke({"path": _spelling(family, note)})
        want = _READ_OUTSIDE if refusal is None and family in _SHARE_FAMILIES else refusal
        assert spelled.error == want, f"{family} of {note.name}: {spelled.error}"
        if want is None:
            assert "bf953 fixture" in repr(spelled.output)
        else:
            assert spelled.output is None, family


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_list_files_decides_every_spelling_of_a_directory_alike(tmp_path: Path, family: str) -> None:
    """T3: ``list_files`` asks the same function for its base and for each match, on BF-948's rig. The ordinary
    spellings are decided first (the premise); then a spelling of the floor directory is refused, a spelling of a
    directory outside the permitted root is refused, and a spelling of the permitted root and of the agent
    workspace under the floor is listed, except a share spelling of either, which is refused (the permitted root
    and the exemption name it by their text only)."""
    scene = _scene(tmp_path)
    (scene.allowed / "allowed note long name.txt").write_bytes(_CONTENT)
    assert (await _list(scene, [], "*", str(scene.data))).error == _PROTECTED  # premise
    assert (await _list(scene, [scene.allowed], "*", str(scene.outside))).error == _OUTSIDE  # premise
    listed = await _list(scene, [scene.allowed], "*", str(scene.allowed))
    assert listed.error is None and {Path(n).name for n in listed.output["files"]} == {
        "allowed note long name.txt", "ok.txt", "sub",
    }  # premise
    assert (await _list(scene, [], "*", str(scene.workspace))).error is None  # premise: the exemption lifts the floor
    refused_floor = await _list(scene, [], "*", _spelling(family, scene.data))
    assert refused_floor.error == _PROTECTED and refused_floor.output is None, family
    refused_outside = await _list(scene, [scene.allowed], "*", _spelling(family, scene.outside))
    assert refused_outside.error == _OUTSIDE and refused_outside.output is None, family
    spelled = await _list(scene, [scene.allowed], "*", _spelling(family, scene.allowed))
    workspace = await _list(scene, [], "*", _spelling(family, scene.workspace))
    if family in _SHARE_FAMILIES:
        assert spelled.error == _OUTSIDE and spelled.output is None, family
        assert workspace.error == _PROTECTED and workspace.output is None, family
        return
    assert spelled.error is None, f"{family}: {spelled.error}"
    assert {Path(n).name for n in spelled.output["files"]} == {"allowed note long name.txt", "ok.txt", "sub"}, family
    assert workspace.error is None and [Path(n).name for n in workspace.output["files"]] == ["scratch.txt"], family


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
def test_the_read_floor_refuses_every_spelling_of_a_config_file_the_write_side_refuses(
    tmp_path: Path, family: str,
) -> None:
    """T4: the write side refuses every spelling of the loaded config file (BF-911); so does the read floor."""
    lay = _fixture(tmp_path)
    runtime = SimpleNamespace(config_path=lay.config)
    configs = file_access.protected_config_files(runtime)
    assert lay.config.resolve() in configs, "premise: the runtime names the file"
    assert protected_write_refusal(str(lay.config), runtime=runtime) is not None, "premise: the write side refuses it"
    assert _decide(str(lay.config), protected=configs)[0] == "refused", "premise: the read floor refuses it"
    spelled = _spelling(family, lay.config)
    assert protected_write_refusal(spelled, runtime=runtime) is not None, f"{family}: the write side"
    assert _decide(spelled, protected=configs)[0] == "refused", f"{family}: the read floor"


_NAMESPACE_CASES = [
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\c:\\Data", "c:\\Data"),
    ("\\\\?\\C:", "C:"),
    ("\\\\.\\C:\\data", "C:\\data"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\?\\unc\\host\\share", "\\\\host\\share"),
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\host\\share\\dir", "\\\\host\\share\\dir"),
    ("\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data", "\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data"),
    ("\\\\?\\1:\\data", "\\\\?\\1:\\data"),
    ("\\\\?\\CC:\\data", "\\\\?\\CC:\\data"),
    ("\\\\?\\C:data", "\\\\?\\C:data"),
    ("/srv/data/note.txt", "/srv/data/note.txt"),
    ("", ""),
    ("\\\\?\\", "\\\\?\\"),
]


@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
def test_the_namespace_free_form(text: str, expected: str) -> None:
    """T5: pure text, the same on every platform: the extended and device prefixes of a drive path and the extended
    UNC prefix go, and a bare drive after a prefix is the drive; a volume or device name, a drive-relative form with a
    path and a path of another platform stay."""
    assert file_access._namespace_free(text) == expected


@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
def test_the_namespace_free_form_agrees_with_the_write_sides_key(text: str) -> None:
    """T6: for every spelling the canonicaliser rewrites, the write side's key (BF-911) of the text and of the rewrite
    are the same."""
    assert file_access._write_key(text) == file_access._write_key(file_access._namespace_free(text))


def test_file_identity_is_the_file_the_system_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T7: one identity for every name of a file, none for a path that names nothing, and no answer (``_Unverifiable``,
    never ``None``) when the system cannot say: a name it rejects, a read it refuses, or no file index (zero)."""
    note = tmp_path / "note.txt"
    note.write_bytes(_CONTENT)
    (tmp_path / "sub").mkdir()
    link = tmp_path / "note-link.txt"
    os.link(note, link)
    identity = file_access._file_identity(note)
    assert identity is not None
    assert file_access._file_identity(tmp_path / "sub" / ".." / "note.txt") == identity == file_access._file_identity(link)
    assert file_access._file_identity(tmp_path / "sub") != identity
    assert file_access._file_identity(tmp_path / "missing.txt") is None
    assert file_access._file_identity(note / "child.txt") is None  # under a file: nothing is there
    with pytest.raises(file_access._Unverifiable):
        file_access._file_identity(Path("bad\x00name"))
    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", lambda _path: SimpleNamespace(st_dev=7, st_ino=0))
        with pytest.raises(file_access._Unverifiable):
            file_access._file_identity(note)

    def refused(_path: Any) -> Any:
        raise PermissionError(13, "refused")

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", refused)
        with pytest.raises(file_access._Unverifiable):
            file_access._file_identity(note)


@pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows these names are one directory")
def test_a_posix_name_keeps_what_a_permitted_root_admits(tmp_path: Path) -> None:
    """T8: on POSIX the names that differ by case, a trailing dot or space, a backslash or a Windows-looking prefix are
    other directories, and none of them is inside the permitted root."""
    root = tmp_path.resolve()
    names = ["allowed", "Allowed", "allowed.", "allowed ", "allowed\\x", "\\\\?\\allowed", "\\\\localhost\\allowed"]
    for name in names:
        (root / name).mkdir()
        (root / name / "note.txt").write_bytes(_CONTENT)
    assert len(list(root.iterdir())) == len(names), "premise: every name is its own directory"
    permitted = [root / "allowed"]
    assert _decide(str(root / "allowed" / "note.txt"), permitted=permitted)[0] == "admitted"
    for name in names[1:]:
        assert _decide(str(root / name / "note.txt"), permitted=permitted) == (
            "refused", "path is outside every readable root",
        ), name
    assert _decide(f"{root / 'allowed'}\\note.txt", permitted=permitted)[0] == "refused"


@WINDOWS
def test_a_drive_letter_path_costs_no_identity_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T9: a drive-letter path against drive-letter roots, and an extended-prefix local path (decided on its text),
    ask the system for no identity; the path returned is unchanged."""
    lay = _fixture(tmp_path)
    asked: list[Path] = []
    monkeypatch.setattr(file_access, "_file_identity", lambda path: asked.append(path))
    roots = {"protected": [lay.data.resolve()], "exempt": [lay.work.resolve()], "permitted": [lay.allowed.resolve()]}
    plain = _decide(str(lay.allowed_note), **roots)
    extended = _decide("\\\\?\\" + str(lay.allowed_note), **roots)
    assert plain == ("admitted", str(lay.allowed_note)) and extended == ("admitted", "\\\\?\\" + str(lay.allowed_note))
    assert asked == []


@WINDOWS
def test_a_share_path_no_root_covers_stays_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10: containment of a share path by a floor root is decided by identity, and only for the floor. With the system's
    answers replaced (no host is contacted): a share path that is not the root, has no ancestor that is the root and does
    not reach the root's volume is not inside it; one that has is, standing at that ancestor's count of parts; one whose
    chain is on the root's volume only through a link is inside at its own count; and a root that is not on disk contains
    nothing. An exempt or a permitted root is never matched by identity."""
    root = _fixture(tmp_path).data.resolve()
    absent_root = root.parent / "no-such-root"
    same_as_root = Path("\\\\bf953-alias\\share\\floor")
    linked = Path("\\\\bf953-link\\share\\jx\\note.txt")
    known = {root: (1, 1), same_as_root: (1, 1), absent_root: None, linked.parent: (1, 5), linked: (1, 6)}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known[path] if path in known else (2, hash(path)))
    elsewhere = Path("\\\\bf953-remote\\share\\dir\\note.txt")
    inside = same_as_root / "sub" / "note.txt"
    assert file_access._match_position(elsewhere, [root], floor=True) is None
    assert file_access._match_position(inside, [root], floor=True) == len(same_as_root.parts)
    assert file_access._match_position(same_as_root, [root], floor=True) == len(same_as_root.parts)
    assert file_access._match_position(inside, [absent_root], floor=True) is None
    assert file_access._match_position(inside, [root]) is None, "an exempt or a permitted root is matched by text only"
    assert file_access._match_position(linked, [root], floor=True) == len(linked.parts)
    known[root] = (3, 1)
    assert file_access._match_position(linked, [root], floor=True) is None, "a root on a volume the chain never reaches"
    known[root] = (2, 1)
    assert file_access._match_position(elsewhere, [root], floor=True) is None, "a root on the volume of the chain's top"
    twin = Path("\\\\bf953-twin\\share\\one\\two")
    known.update({root: (1, 1), twin.parent: (1, 1), twin: (1, 1)})
    assert file_access._match_position(twin, [root], floor=True) == len(twin.parts), "the deepest part with that identity"
    deeper = same_as_root / "sub"
    for roots in ([root, deeper], [deeper, root]):
        assert file_access._match_position(inside, roots, floor=True) == len(deeper.parts), "the deepest root wins"


@WINDOWS
async def test_a_share_spelling_is_never_admitted_by_a_root_its_text_does_not_name(
    tmp_path: Path, request: pytest.FixtureRequest,
) -> None:
    """T11 (Amendment 1, review finding 1 and the second reviewer's R2): a share spelling of a path through a link to another
    volume, below a permitted root, is refused, as the ordinary spelling is: the share's text names the permitted root's
    directory, the file is not in it. The same through the floor: a link into the interior of a floor root on that other
    volume, through the policy and through ``read_file`` and ``list_files``. And a share spelling the floor cannot contain
    (the floor is on the first volume) is still admitted."""
    lay = _fixture(tmp_path)
    other = _other_volume_dir(request, tmp_path)
    (other / "target directory long name").mkdir()
    (other / "target directory long name" / "target note long name.txt").write_bytes(_CONTENT)
    (other / "floor tree long name" / "interior directory long name").mkdir(parents=True)
    (other / "floor tree long name" / "interior directory long name" / "interior note long name.txt").write_bytes(_CONTENT)
    outward = lay.allowed / "link to the other volume"
    interior = lay.allowed / "link into the floor interior"
    _link(outward, other / "target directory long name")
    _link(interior, other / "floor tree long name" / "interior directory long name")
    try:
        note, deep = outward / "target note long name.txt", interior / "interior note long name.txt"
        assert os.stat(note).st_dev != os.stat(lay.allowed).st_dev, "premise: the link leaves the volume"
        permitted, floor = [lay.allowed.resolve()], [(other / "floor tree long name").resolve()]
        for target in (note, deep):
            spelled = _spelling_or_none("UNC localhost admin share", target)
            if spelled is None:
                pytest.skip("BF-953 premise: this host does not serve the local share spelling of the linked file")
            assert _decide(str(target), permitted=permitted) == ("refused", _OUTSIDE_REASON), "premise: the ordinary spelling"
            assert _decide(spelled, permitted=permitted) == ("refused", _OUTSIDE_REASON), target.name
        assert _decide(str(deep), protected=floor) == ("refused", _FLOOR_REASON), "premise: the file is in the floor"
        spelled = _spelling("UNC localhost admin share", deep)
        assert _decide(spelled, protected=floor) == ("refused", _FLOOR_REASON), "the interior of the floor, through a link"
        here = [lay.data.resolve()]
        assert _decide(_spelling("UNC localhost admin share", note), protected=here)[0] == "admitted", "no floor root is there"
        floor_runtime = SimpleNamespace(data_dir=other / "floor tree long name", config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=str(lay.work)),
        ))
        read = await ReadFileTool(floor_runtime).invoke({"path": spelled})
        assert read.error == _READ_PROTECTED and read.output is None, "read_file: the interior of the floor"
        listing = await ListFilesTool(floor_runtime).invoke(
            {"pattern": "*", "path": _spelling("UNC localhost admin share", interior)},
        )
        assert listing.error == _PROTECTED and listing.output is None, "list_files: the interior of the floor"
        confined = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[str(lay.allowed)]), execution=SimpleNamespace(workspace_root=str(lay.work)),
        ))
        read = await ReadFileTool(confined).invoke({"path": _spelling("UNC localhost admin share", note)})
        assert read.output is None and read.error in (_READ_OUTSIDE, _READ_PROTECTED), "read_file: a permitted root"
    finally:
        _unlink(outward)
        _unlink(interior)


@WINDOWS
@pytest.mark.parametrize("failure", ["a read the system refuses", "no file index"])
async def test_a_floor_that_cannot_be_read_refuses_a_share_spelling_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """T12 (Amendment 1, review finding 3): the floor root's identity cannot be read (or has no file index) while a
    permitted root's can. A share spelling of a floor file is refused with the bounded reason, through the policy and
    through ``read_file``, and gives no content; the ordinary spelling is refused as before; a drive-letter path outside
    the floor asks for no identity and is admitted."""
    scene = _scene(tmp_path)
    note = scene.data / "floor note long name.txt"
    note.write_bytes(_CONTENT)
    (scene.allowed / "allowed note long name.txt").write_bytes(_CONTENT)
    floor_text = os.path.normcase(str(scene.data))
    real_stat = os.stat

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        info = real_stat(path, *args, **kwargs)
        if os.path.normcase(str(path)) != floor_text:
            return info
        if failure == "no file index":
            return os.stat_result((info.st_mode, 0, info.st_dev, info.st_nlink, info.st_uid, info.st_gid, info.st_size,
                                   int(info.st_atime), int(info.st_mtime), int(info.st_ctime)))
        raise PermissionError(13, "refused")

    roots = {"protected": [scene.data.resolve()], "permitted": [scene.root]}
    shared = _spelling("UNC localhost admin share", note)
    assert _decide(shared, **roots) == ("refused", _FLOOR_REASON), "premise: the floor is read"
    monkeypatch.setattr(file_access.os, "stat", stat)
    assert _decide(shared, **roots) == ("refused", _UNVERIFIED_REASON)
    assert _decide(str(note), **roots) == ("refused", _FLOOR_REASON)
    assert _decide(str(scene.allowed / "allowed note long name.txt"), **roots)[0] == "admitted"
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.root]))
    answered = await reader.invoke({"path": shared})
    assert answered.error == f"read_file refused: {_UNVERIFIED_REASON}" and answered.output is None


def _device_spelling(target: Path) -> str | None:
    """The ``\\\\?\\GLOBALROOT`` spelling of the existing *target*, or None when the system names no device for its drive."""
    drive, rest = os.path.splitdrive(str(target))
    buffer = ctypes.create_unicode_buffer(512)
    if not ctypes.windll.kernel32.QueryDosDeviceW(drive, buffer, len(buffer)):  # type: ignore[attr-defined]
        return None
    return "\\\\?\\GLOBALROOT" + buffer.value.split("\0")[0] + rest


@WINDOWS
@pytest.mark.parametrize("kind", ["device", "extended prefix", "share", "extended UNC"])
def test_an_exemption_stands_where_its_text_puts_it_in_the_path_not_where_its_root_is_spelled(
    tmp_path: Path, kind: str,
) -> None:
    """T13 (Amendment 1, review finding 2): an exempt root that names the floor directory or its parent in another
    spelling never lifts the floor, for the ordinary spelling of a floor file or a share spelling of it. The exemption of
    the workspace under the floor lifts it, spelled with an extended prefix too; a root spelled so that its text does not
    name the ordinary path lifts nothing."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve()]
    drive, rest = os.path.splitdrive(str(lay.data))
    spellings = {
        "device": _device_spelling(lay.data),
        "extended prefix": "\\\\?\\" + str(lay.data),
        "share": f"\\\\localhost\\{drive[0]}${rest}",
        "extended UNC": f"\\\\?\\UNC\\localhost\\{drive[0]}${rest}",
    }
    if spellings[kind] is None:
        pytest.skip(f"BF-953 premise: this host has no {kind} spelling")
    assert _decide(str(lay.work_note), protected=floor, exempt=[lay.work.resolve()])[0] == "admitted", "premise"
    for named in (Path(str(spellings[kind])), Path(str(spellings[kind])).parent):
        assert _decide(str(lay.floor_note), protected=floor, exempt=[named])[0] == "refused", f"{kind}: {named}"
        shared = _spelling_or_none("UNC localhost admin share", lay.floor_note)
        if shared is not None:
            assert _decide(shared, protected=floor, exempt=[named])[0] == "refused", f"{kind}, share candidate: {named}"
    workspace = "\\\\?\\" + str(lay.work)
    assert _decide(str(lay.work_note), protected=floor, exempt=[Path(workspace)])[0] == "admitted", "the prefix is only text"
    configured = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=spellings[kind]),
    ))
    with pytest.raises(FileAccessDenied):
        file_access.resolve_for_runtime(str(lay.floor_note), configured)


@WINDOWS
def test_a_workspace_root_configured_as_a_short_path_is_spelled_as_its_candidates_are(tmp_path: Path) -> None:
    """T14 (Amendment 1, review finding 5): a workspace root configured as an 8.3 short path is the exempt root and the
    permitted root its long path is, so the workspace is readable and listed as the ordinary configuration reads it."""
    lay = _fixture(tmp_path)
    short = _short(str(lay.work))
    if short is None:
        pytest.skip("BF-953 premise: this volume gives the workspace directory no 8.3 name")
    ordinary = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[str(lay.allowed)]), execution=SimpleNamespace(workspace_root=str(lay.work)),
    ))
    configured = SimpleNamespace(data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[str(lay.allowed)]), execution=SimpleNamespace(workspace_root=short),
    ))
    assert file_access.workspace_exempt_roots(configured) == file_access.workspace_exempt_roots(ordinary) == [lay.work.resolve()]
    assert file_access.permitted_read_roots(configured)[-1] == lay.work.resolve()
    assert file_access.resolve_for_runtime(str(lay.work_note), ordinary) == lay.work_note.resolve()
    assert file_access.resolve_for_runtime(str(lay.work_note), configured) == lay.work_note.resolve()
    with pytest.raises(FileAccessDenied):
        file_access.resolve_for_runtime(str(lay.floor_note), configured)


_PLAIN_CASES = [
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\.\\C:\\data", "C:\\data"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\host\\share\\dir", "\\\\host\\share\\dir"),
    ("\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data", "\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data"),
]


@pytest.mark.parametrize(("text", "expected"), _PLAIN_CASES)
def test_the_plain_spelling_drops_the_namespace_prefix_on_windows_only(text: str, expected: str) -> None:
    """T15: the spelling a reader that rejects the prefix is given: the prefix of a drive path or an extended UNC path is
    dropped on Windows; every other path, and every path on another platform, is returned as it is."""
    assert str(file_access.plain_spelling(Path(text))) == (expected if os.name == "nt" else str(Path(text)))


@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
def test_a_namespace_free_root_stands_at_the_same_count_of_parts(text: str) -> None:
    """T16: dropping a namespace prefix changes no count of parts, so a root that is matched as text stands at the same
    count however its prefix is spelled. This is a property of the text alone: it shows that the root's own count and its
    namespace-free count are the same number, and it kills no mutant of the match (T27 pins the use of the count)."""
    assert len(PureWindowsPath(text).parts) == len(PureWindowsPath(file_access._namespace_free(text)).parts)


@WINDOWS
@pytest.mark.parametrize("kind", ["ordinary", "extended prefix", "device", "share", "extended UNC", "link to the floor"])
def test_a_loaded_config_file_outranks_the_workspace_that_encloses_it(tmp_path: Path, kind: str) -> None:
    """T17 (the second reviewer's R1): the loaded config file is a floor file root inside the exempt workspace, which is
    inside the data directory. However the workspace root is configured (in another spelling, or as a link to the data
    directory), the file is refused in its ordinary spelling and in the extended, device and share spellings of it: a file
    root outranks the workspace that encloses it, and two roots that name one directory tie. Where the configured root is
    the workspace itself, a workspace file beside the config file is still admitted; where it names the data directory it
    is not."""
    root = tmp_path.resolve()
    data = root / "floor data directory"
    workspace = data / "workspace directory long name"
    workspace.mkdir(parents=True)
    config, note = workspace / "loaded config long name.yaml", workspace / "workspace note long name.txt"
    config.write_bytes(_CONTENT)
    note.write_bytes(_CONTENT)
    drive, rest = os.path.splitdrive(str(workspace))
    link = root / "a link directory long name"
    configured = {
        "ordinary": str(workspace),
        "extended prefix": "\\\\?\\" + str(workspace),
        "device": _device_spelling(workspace),
        "share": f"\\\\localhost\\{drive[0]}${rest}",
        "extended UNC": f"\\\\?\\UNC\\localhost\\{drive[0]}${rest}",
        "link to the floor": str(link),
    }[kind]
    if configured is None:
        pytest.skip(f"BF-953 premise: this host has no {kind} spelling")

    def runtime(workspace_root: str) -> SimpleNamespace:
        return SimpleNamespace(data_dir=data, config_path=config, config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=workspace_root),
        ))

    ordinary = runtime(str(workspace))
    assert config.resolve() in file_access.protected_config_files(ordinary), "premise: the config file is a floor root"
    assert file_access.resolve_for_runtime(str(note), ordinary) == note.resolve(), "premise: the workspace is lifted"
    if kind == "link to the floor":
        _link(link, data)
    try:
        candidates = {
            "ordinary": str(config),
            "extended prefix": "\\\\?\\" + str(config),
            "device": _device_spelling(config),
            "share": _spelling_or_none("UNC localhost admin share", config),
        }
        for name, candidate in candidates.items():
            if candidate is None:
                continue  # a premise: this host has no such spelling of the file
            try:
                file_access.resolve_for_runtime(candidate, runtime(configured))
            except FileAccessDenied:
                continue
            pytest.fail(f"the {name} spelling of the loaded config file was admitted with the workspace root as {kind}")
        configured_runtime = runtime(configured)
        roots = {
            "protected_roots": file_access.protected_read_roots(configured_runtime),
            "exempt_roots": file_access.workspace_exempt_roots(configured_runtime),
        }
        with pytest.raises(FileAccessDenied):
            file_access.read_verified_file(config, **roots)
        bounded = file_access.read_bounded_utf8(str(config), authorized_root=workspace, **roots)
        assert bounded.status is file_access.BoundedReadStatus.DENIED and bounded.text == ""
        if kind in ("ordinary", "extended prefix", "device"):
            assert file_access.resolve_for_runtime(str(note), runtime(configured)) == note.resolve()
        if kind == "link to the floor":
            with pytest.raises(FileAccessDenied):
                file_access.resolve_for_runtime(str(note), runtime(configured))
    finally:
        if kind == "link to the floor":
            _unlink(link)


_FINAL_COMPONENT_SPELLINGS = [":zz", ":zz:$DATA", "::$DATA", ".", " ", ". "]


@pytest.mark.parametrize(
    ("name", "base"),
    [
        ("config.yaml", "config.yaml"), ("config.yaml:zz", "config.yaml"), ("config.yaml:zz:$DATA", "config.yaml"),
        ("config.yaml::$DATA", "config.yaml"), ("config.yaml.", "config.yaml"), ("config.yaml ", "config.yaml"),
        ("config.yaml. ", "config.yaml"), ("config.yaml:zz.", "config.yaml"), ("archive.tar.gz", "archive.tar.gz"),
        (".hidden", ".hidden"), (":zz", ":zz"), ("...", "..."), ("", ""),
    ],
)
def test_the_base_name_of_a_final_component(name: str, base: str) -> None:
    """T18: the file a final component names on Windows (any platform runs the text): the text from the first colon, then
    trailing dots and spaces, are dropped; a name that would be empty stays as it is."""
    assert file_access._base_name(name) == base


@WINDOWS
@pytest.mark.parametrize("suffix", _FINAL_COMPONENT_SPELLINGS)
def test_a_stream_or_trailing_dot_or_space_spelling_of_a_floor_file_is_decided_as_the_file_is(
    tmp_path: Path, suffix: str,
) -> None:
    """T19 (the second reviewer's R3): a named stream, a stream with its type, the default stream, trailing dots and trailing
    spaces on the final component of a floor file root, or of a credential vault name, are decided as the file is, with its
    reason, in the ordinary, extended-prefix and share spellings; a neighbour in the same directory with the same suffix is
    admitted, and the path returned is the one ``Path.resolve()`` spells for it (a named stream's suffix is kept there, T20;
    a trailing dot or space and the default stream's type are dropped by ``resolve()`` for a file on disk)."""
    lay = _fixture(tmp_path)
    vault = lay.outside / "credential_vault.json"
    vault.write_bytes(_CONTENT)
    floor = [lay.data.resolve(), lay.config.resolve()]
    for target, reason in ((lay.config, _FLOOR_REASON), (vault, _LEAF_REASON)):
        ordinary = _decide(str(target), protected=floor)
        assert ordinary == ("refused", reason), f"premise: the ordinary spelling of {target.name}: {ordinary}"
        assert _decide(str(target) + suffix, protected=floor) == ordinary, f"{target.name}{suffix!r}"
        assert _decide("\\\\?\\" + str(target) + suffix, protected=floor) == ordinary, f"extended {target.name}{suffix!r}"
        shared = _spelling_or_none("UNC localhost admin share", target)
        if shared is not None:
            assert _decide(shared + suffix, protected=floor) == ordinary, f"share {target.name}{suffix!r}"
    admitted = _decide(str(lay.neighbour) + suffix, protected=floor)
    assert admitted[0] == "admitted", f"a neighbour with {suffix!r}: {admitted}"
    assert admitted == ("admitted", str(Path(str(lay.neighbour) + suffix).resolve())), f"the path returned for {suffix!r}"


@WINDOWS
async def test_a_named_stream_of_a_floor_file_is_refused_and_one_of_a_neighbour_is_read(tmp_path: Path) -> None:
    """T20 (the second reviewer's R3), through ``ReadFileTool`` with a real named stream: the loaded config file's stream
    and a credential vault name's stream are refused with the file's own reason and give no content; the write side refuses
    the same name; a neighbour's stream is read, by the path as it was given."""
    lay = _fixture(tmp_path)
    vault = lay.outside / "credential_vault.json"
    vault.write_bytes(_CONTENT)
    try:
        for note in (lay.config, vault, lay.neighbour):
            Path(str(note) + ":zz").write_bytes(b"stream fixture")
    except OSError:
        pytest.skip("BF-953 premise: this volume makes no named streams")
    runtime = SimpleNamespace(config_path=lay.config, data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=str(lay.work)),
    ))
    reader = ReadFileTool(runtime)
    config_stream = await reader.invoke({"path": str(lay.config) + ":zz"})
    assert config_stream.error == _READ_PROTECTED and config_stream.output is None
    vault_stream = await reader.invoke({"path": str(vault) + ":zz"})
    assert vault_stream.error == f"read_file refused: {_LEAF_REASON}" and vault_stream.output is None
    assert protected_write_refusal(str(lay.config) + ":zz", runtime=runtime) is not None, "the write side refuses the name"
    neighbour_stream = await reader.invoke({"path": str(lay.neighbour) + ":zz"})
    assert neighbour_stream.error is None and "stream fixture" in repr(neighbour_stream.output)
    assert str(file_access.resolve_for_runtime(str(lay.neighbour) + ":zz", runtime)).endswith(":zz"), "the stream name is kept"


_ABSENT_SPELLINGS = [
    "forward slashes", "swapped case", "trailing dot", "trailing space", "default stream", "named stream",
    "extended prefix", "device prefix",
]


def _absent_spelling(kind: str, text: str) -> str:
    return {
        "forward slashes": text.replace("\\", "/"), "swapped case": text.swapcase(), "trailing dot": text + ".",
        "trailing space": text + " ", "default stream": text + "::$DATA", "named stream": text + ":zz",
        "extended prefix": "\\\\?\\" + text, "device prefix": "\\\\.\\" + text,
    }[kind]


@WINDOWS
@pytest.mark.parametrize("kind", _ABSENT_SPELLINGS)
def test_an_absent_file_root_and_an_absent_credential_name_are_decided_in_every_spelling_alike(
    tmp_path: Path, kind: str,
) -> None:
    """T21 (the second reviewer's R6): a floor file root that is not on disk, and a credential vault name that is not on
    disk, are refused in every spelling of the final component and of the path that this host serves (forward slashes,
    another case, trailing dot or space, a stream suffix, the extended and device prefixes), with the ordinary spelling's
    reason; an absent neighbour in the same spelling is admitted. The share spelling of an absent file root is not
    decided here: a root that is not on disk has no identity to compare (L2)."""
    lay = _fixture(tmp_path)
    absent_root = lay.config.parent / "absent config long name.yaml"
    absent_vault = lay.outside / "credential_vault.json"
    absent_neighbour = lay.config.parent / "absent neighbour long name.yaml"
    assert not any(path.exists() for path in (absent_root, absent_vault, absent_neighbour)), "premise: none is on disk"
    floor = [lay.data.resolve(), lay.config.resolve(), absent_root.resolve()]
    for target, reason in ((absent_root, _FLOOR_REASON), (absent_vault, _LEAF_REASON)):
        assert _decide(str(target), protected=floor) == ("refused", reason), "premise: the ordinary spelling"
        spelled = _decide(_absent_spelling(kind, str(target)), protected=floor)
        assert spelled == ("refused", reason), f"{kind} of {target.name}: {spelled}"
    assert _decide(str(absent_neighbour), protected=floor)[0] == "admitted", "premise"
    spelled = _decide(_absent_spelling(kind, str(absent_neighbour)), protected=floor)
    assert spelled[0] == "admitted", f"{kind} of a neighbour: {spelled}"


@pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows these names are one file")
def test_a_posix_name_that_differs_by_case_dot_space_or_colon_is_another_file_for_the_floor(tmp_path: Path) -> None:
    """T22: on POSIX the final component is compared as it is: another case, a trailing dot or space, or a colon suffix is
    another file, so none of them is a floor file root or a credential vault name; the names themselves are."""
    root = tmp_path.resolve()
    (root / "vault").mkdir()
    config_names = ["config.yaml", "Config.yaml", "config.yaml.", "config.yaml ", "config.yaml:zz"]
    vault_names = ["credential_vault.json", "Credential_vault.json", "credential_vault.json.", "credential_vault.json ",
                   "credential_vault.json:zz"]
    for name in config_names:
        (root / name).write_bytes(_CONTENT)
    for name in vault_names:
        (root / "vault" / name).write_bytes(_CONTENT)
    if len(list(root.iterdir())) != len(config_names) + 1 or len(list((root / "vault").iterdir())) != len(vault_names):
        pytest.skip("BF-953 premise: this filesystem folds case, so the names are not distinct files")
    assert _decide(str(root / "config.yaml"), protected=[root / "config.yaml"])[0] == "refused"
    for name in config_names[1:]:
        assert _decide(str(root / name), protected=[root / "config.yaml"])[0] == "admitted", name
    assert _decide(str(root / "vault" / vault_names[0])) == ("refused", _LEAF_REASON)
    for name in vault_names[1:]:
        assert _decide(str(root / "vault" / name))[0] == "admitted", name


_ROOT_SUFFIXES = [":settings", ":settings:$DATA", ".", " "]


@WINDOWS
@pytest.mark.parametrize("suffix", _ROOT_SUFFIXES)
def test_a_floor_file_root_spelled_with_a_suffix_is_decided_as_its_file_is(tmp_path: Path, suffix: str) -> None:
    """T23 (review round 3, A1): a floor file root whose own final component carries a stream suffix (a configuration loaded
    as ``loaded.yaml:settings``) or, spelled in the extended namespace, a trailing dot or space, is compared by the file it
    names, as a candidate is. The root's own spelling and every other spelling of its file (the ordinary one, the default
    stream, another stream, the extended prefix) are refused with the floor's reason, and a neighbour with the same suffix is
    admitted."""
    lay = _fixture(tmp_path)
    spelled = "\\\\?\\" + str(lay.config) + suffix if suffix in (".", " ") else str(lay.config) + suffix
    floor = [lay.data.resolve(), Path(spelled)]
    for candidate in (
        spelled, str(lay.config), "\\\\?\\" + str(lay.config), str(lay.config) + "::$DATA", str(lay.config) + ":other",
        "\\\\?\\" + str(lay.config) + ".",
    ):
        assert _decide(candidate, protected=floor) == ("refused", _FLOOR_REASON), f"{candidate!r}"
    assert _decide(str(lay.neighbour) + suffix, protected=floor)[0] == "admitted", "a neighbour with the same suffix"


_FLOOR_ROOT_CASES = [
    ("C:\\cfg\\loaded.yaml:settings", "C:\\cfg\\loaded.yaml"),
    ("C:\\cfg\\loaded.yaml:settings:$DATA", "C:\\cfg\\loaded.yaml"),
    ("\\\\?\\C:\\cfg\\old.yaml.", "\\\\?\\C:\\cfg\\old.yaml"),
    ("\\\\?\\C:\\cfg\\old.yaml. ", "\\\\?\\C:\\cfg\\old.yaml"),
]


@pytest.mark.parametrize(("text", "base"), _FLOOR_ROOT_CASES)
def test_the_floor_roots_include_the_file_each_final_component_names(text: str, base: str) -> None:
    """T24 (review round 3, A1): each floor root stays in the list as it is spelled and, on Windows, the file its final
    component names follows it when that is another spelling; a root that names itself (a directory root, an ordinary file
    root) adds nothing, and on another platform nothing is added."""
    directory, ordinary = Path("C:\\data"), Path("C:\\cfg\\loaded.yaml")
    assert file_access._floor_roots([directory, ordinary]) == [directory, ordinary]
    roots = [directory, Path(text), ordinary]
    assert file_access._floor_roots(roots) == ([*roots, Path(base)] if os.name == "nt" else roots)


async def test_a_workspace_root_that_does_not_resolve_stays_in_the_read_policy_as_it_was_composed(tmp_path: Path) -> None:
    """T25 (review round 3, A2): a workspace root the configuration accepts and the system cannot resolve (a text with a NUL)
    stays in both root builders as it was composed, so a configured read policy still confines reads, whether its own roots are
    usable or not; the exempt list lifts nothing for it. Through ``resolve_for_runtime``, ``read_file`` and ``list_files``."""
    scene = _scene(tmp_path)
    broken = str(scene.workspace) + "\x00"

    def runtime(read_roots: list[str], workspace: str) -> SimpleNamespace:
        config = SystemConfig(security_infra={"read_roots": read_roots}, execution={"workspace_root": workspace})
        return SimpleNamespace(data_dir=scene.data, config=config)

    with pytest.raises(ValueError):
        Path(broken).resolve()  # premise: the system refuses to resolve it
    assert file_access.permitted_read_roots(runtime(["\x00unusable"], str(scene.workspace))) == [scene.workspace.resolve()]
    assert file_access.permitted_read_roots(runtime(["\x00unusable"], broken)) == [Path(broken)]
    assert file_access.permitted_read_roots(runtime([str(scene.allowed)], broken)) == [scene.allowed.resolve(), Path(broken)]
    assert file_access.workspace_exempt_roots(runtime([], broken)) == [Path(broken)]
    outside = str(scene.outside / SECRET_NAME)
    for read_roots in (["\x00unusable"], [str(scene.allowed)]):
        policy = runtime(read_roots, broken)
        with pytest.raises(FileAccessDenied) as refused:
            file_access.resolve_for_runtime(outside, policy)
        assert refused.value.reason == _OUTSIDE_REASON, read_roots
        read = await ReadFileTool(policy).invoke({"path": outside})
        assert read.error == _READ_OUTSIDE and read.output is None, read_roots
        listing = await ListFilesTool(policy).invoke({"pattern": "*", "path": str(scene.outside)})
        assert listing.error == _OUTSIDE and listing.output is None, read_roots
    inside = scene.allowed / "ok.txt"
    assert file_access.resolve_for_runtime(str(inside), runtime([str(scene.allowed)], broken)) == inside.resolve()
    with pytest.raises(FileAccessDenied):
        file_access.resolve_for_runtime(str(scene.workspace / "scratch.txt"), runtime([], broken))


_READER_CASES = [
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\?\\C:\\data\\a b.txt", "C:\\data\\a b.txt"),
    ("\\\\?\\C:\\data\\x..y.txt", "C:\\data\\x..y.txt"),
    ("\\\\?\\C:\\data\\console.txt", "C:\\data\\console.txt"),
    ("\\\\?\\C:\\data\\confidential\\nul0.txt", "C:\\data\\confidential\\nul0.txt"),
    ("\\\\?\\C:\\data\\note.txt.", None),
    ("\\\\?\\C:\\data\\note.txt ", None),
    ("C:\\data\\note.txt. ", None),
    ("\\\\?\\C:\\data\\dir.\\deep.txt", None),
    ("\\\\?\\C:\\data\\dir \\deep.txt", None),
    ("\\\\?\\C:\\data\\up.\\down\\leaf.txt", None),
    ("\\\\?\\C:\\data\\...", None),
    ("\\\\?\\UNC\\host\\share\\dir.\\f.txt", None),
    ("\\\\?\\C:\\data\\NUL.txt", None),
    ("C:\\data\\con", None),
    ("C:\\data\\Aux.log", None),
    ("C:\\data\\COM1", None),
    ("C:\\data\\lpt9.txt", None),
    ("\\\\?\\C:\\data\\con\\g.txt", None),
    ("\\\\?\\C:\\data\\nul\\x\\y.txt", None),
]


@WINDOWS
@pytest.mark.parametrize(("text", "expected"), _READER_CASES)
def test_the_reader_spelling_is_one_that_names_the_file_in_the_ordinary_namespace(text: str, expected: str | None) -> None:
    """T26 (review round 3, A3 and B1; Windows only since review round 4): a path is given to a reader that rejects the
    namespace prefix as ``plain_spelling`` spells it, unless a component of that spelling names another file or none in the
    ordinary namespace: a component that ends in a dot or a space (the system drops both), or a reserved device name, in the
    final component or in an ancestor, has no such spelling and gives ``None``. A name that only starts or ends like a device
    name keeps its spelling. The rules of the verified reader on the text, which apply on every platform, are T29 to T31."""
    got = file_access.reader_spelling(Path(text))
    assert (None if got is None else str(got)) == expected


_STAND_CASES = [
    ("\\\\?\\C:\\data\\work", "C:\\data\\work\\note.txt", 3),
    ("\\\\.\\C:\\data", "C:\\data\\work\\note.txt", 2),
    ("\\\\?\\UNC\\host\\share\\data", "\\\\host\\share\\data\\note.txt", 2),
    ("C:\\data\\work", "\\\\?\\C:\\data\\work\\note.txt", 3),
]


@WINDOWS
@pytest.mark.parametrize(("root", "candidate", "count"), _STAND_CASES)
def test_a_text_match_stands_at_the_count_of_its_namespace_free_root(root: str, candidate: str, count: int) -> None:
    """T27 (review round 3, T16 strengthened): a root that contains a path as text stands at its count of parts without a
    namespace prefix, whichever of the two is spelled with one, and the deepest root wins whatever the order of the list."""
    assert file_access._match_position(Path(candidate), [Path(root)]) == count
    assert file_access._match_position(Path(candidate), [Path("C:\\"), Path(root)]) == count
    assert file_access._match_position(Path(candidate), [Path(root), Path("C:\\")]) == count


@WINDOWS
def test_an_identity_match_stands_where_the_path_names_it_not_where_its_root_is_spelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """T27 (review round 3, T16 strengthened): a floor root that is the same file as a part of the path's own chain stands at
    that part's count of parts, never at the count of the root as it is spelled; an exempt or a permitted root is not matched
    by identity."""
    spelled = Path("\\\\?\\GLOBALROOT\\Device\\HarddiskVolume3\\floor\\a\\b\\c\\d\\e")
    alias = Path("\\\\bf953-alias\\share\\floor")
    candidate = alias / "sub" / "note.txt"
    known = {spelled: (1, 1), alias: (1, 1)}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known.get(path, (2, hash(path))))
    assert len(spelled.parts) > len(alias.parts), "premise: the root is spelled with more parts than the part it names"
    assert file_access._match_position(candidate, [spelled], floor=True) == len(alias.parts)
    assert file_access._match_position(candidate, [spelled]) is None


@WINDOWS
async def test_a_configuration_loaded_as_a_stream_is_refused_for_every_spelling_of_its_file(tmp_path: Path) -> None:
    """T28 (review round 3, A1): the configuration the vessel loaded is the stream ``loaded.yaml:settings`` of a file. The
    floor lists it as spelled, and ``resolve_for_runtime`` and ``read_file`` refuse that spelling and the ordinary spelling of
    the file with the floor's reason and give no content; a neighbour's stream is read."""
    lay = _fixture(tmp_path)
    spelled = str(lay.config) + ":settings"
    try:
        Path(spelled).write_bytes(b"stream fixture")
        Path(str(lay.neighbour) + ":settings").write_bytes(b"stream fixture")
    except OSError:
        pytest.skip("BF-953 premise: this volume makes no named streams")
    runtime = SimpleNamespace(config_path=spelled, data_dir=lay.data, config=SimpleNamespace(
        security_infra=SimpleNamespace(read_roots=[]), execution=SimpleNamespace(workspace_root=str(lay.work)),
    ))
    assert any(str(root).endswith(":settings") for root in file_access.protected_config_files(runtime)), "premise: as loaded"
    reader = ReadFileTool(runtime)
    for raw in (spelled, str(lay.config)):
        with pytest.raises(FileAccessDenied) as refused:
            file_access.resolve_for_runtime(raw, runtime)
        assert refused.value.reason == _FLOOR_REASON, raw
        read = await reader.invoke({"path": raw})
        assert read.error == _READ_PROTECTED and read.output is None, raw
    neighbour = await reader.invoke({"path": str(lay.neighbour) + ":settings"})
    assert neighbour.error is None and "stream fixture" in repr(neighbour.output)


# --- M6 (Amendment 3, review round 4): a listing names only a spelling the verified reader's rules on the text admit ---


def _listed(*parts: str) -> Path:
    """An absolute path of this platform, ``C:\\data`` or ``/data`` joined with *parts*, built as text: nothing is created."""
    return Path("C:\\data" if os.name == "nt" else "/data").joinpath(*parts)


# (label, parts, given on Windows, given on another platform). A row whose two answers differ is a rule only Windows has:
# its same-file rule withholds a trailing dot or space and a reserved device name in any ancestor, which is wider than the
# reader's text path (BF-953 L21).
_TEXT_CASES = [
    ("an ordinary name", ("note.txt",), True, True),
    ("a space inside a name", ("a b.txt",), True, True),
    ("a non-ASCII name", ("caf\u00e9.txt",), True, True),
    ("an astral name", ("music-\U0001d11e.txt",), True, True),
    ("a name that only starts like a device name", ("console.txt",), True, True),
    ("a lone high surrogate", ("\ud800.txt",), False, False),
    ("a lone low surrogate inside a name", ("a\udcffb",), False, False),
    ("a lone surrogate in an ancestor", ("d\ud800", "note.txt"), False, False),
    ("a colon in the final name", ("run-12:30.txt",), False, False),
    ("a colon in an ancestor", ("12:30", "note.txt"), False, False),
    ("a newline in the final name", ("a\nb.txt",), False, False),
    ("a character below 32 in an ancestor", ("d\x01", "note.txt"), False, False),
    ("a reserved device stem as the final name", ("aux.py",), False, False),
    ("a reserved device name in another case", ("Con",), False, False),
    ("a trailing dot in the final name", ("note.txt.",), False, False),
    ("a trailing space in the final name", ("note.txt ",), False, False),
    ("a reserved device name as the direct parent", ("con", "g.txt"), False, False),
    ("a reserved device stem as the direct parent", ("aux.py", "g.txt"), False, False),
    ("a reserved device name above the direct parent", ("con", "sub", "g.txt"), False, True),
    ("a trailing dot on an ancestor", ("dir.", "deep.txt"), False, True),
    ("a trailing space on an ancestor", ("dir ", "deep.txt"), False, True),
]


@pytest.mark.parametrize(("label", "parts", "on_windows", "elsewhere"), _TEXT_CASES, ids=[row[0] for row in _TEXT_CASES])
def test_the_reader_spelling_follows_the_verified_readers_rules_on_the_text(
    label: str, parts: tuple[str, ...], on_windows: bool, elsewhere: bool,
) -> None:
    """T29 (review round 4, F1; corrected by review round 5; any platform): ``reader_spelling`` gives a spelling only where
    the verified reader's rules on the text admit it. Text that is not strict UTF-8 (a lone surrogate in the final name or an
    ancestor), a colon or a character below 32 anywhere, a reserved device name as the final name or as the direct parent
    (the reader gives both the file and the directory it pins to its location gate), and a trailing dot or space in the final
    name give none, on every platform; an ordinary, a non-ASCII and an astral name give the path itself. A reserved device
    name above the direct parent, or a trailing dot or space in an ancestor, gives none on Windows only: the reader opens
    the directories above the direct parent without the gate (BF-953 L21). Whatever the reader's own location gate refuses
    gives none."""
    path = _listed(*parts)
    got = file_access.reader_spelling(path)
    assert (got is not None) == (on_windows if os.name == "nt" else elsewhere), f"{label}: {got}"
    if got is not None:
        assert got == path
    try:
        file_access.validate_read_location(str(path))
    except ValueError:
        assert got is None, f"{label}: the reader's location gate refuses it, so there is no spelling"


# (label, text, given). Windows-shaped texts are not used: with ``os.name`` set to ``posix`` a host takes the branch a POSIX host takes.
_POSIX_CASES = [
    ("an ordinary name", "/data/note.txt", True),
    ("a reserved device name as the direct parent", "/data/con/g.txt", False),
    ("a reserved device stem as the direct parent", "/data/aux.py/g.txt", False),
    ("a reserved device name above the direct parent", "/data/con/sub/g.txt", True),
    ("a trailing dot on an ancestor", "/data/dir./deep.txt", True),
    ("a trailing space on an ancestor", "/data/dir /deep.txt", True),
    ("a colon in the final name", "/data/a:b.txt", False),
    ("a timestamp in the final name", "/data/run-2026-11-04T16:20:00Z.log", False),
    ("a newline in the final name", "/data/a\nb.txt", False),
    ("a reserved device stem as the final name", "/data/aux.py", False),
    ("a backslash in the final name", "/data/a\\b.txt", False),
    ("a trailing dot in the final name", "/data/note.", False),
    ("a trailing space in the final name", "/data/note ", False),
    ("a name decoded with surrogateescape", "/data/\udcff.txt", False),
    ("a relative spelling", "data/note.txt", False),
]


@pytest.mark.parametrize(("label", "text", "given"), _POSIX_CASES, ids=[row[0] for row in _POSIX_CASES])
def test_the_reader_spelling_applies_the_readers_rules_off_windows_too(
    monkeypatch: pytest.MonkeyPatch, label: str, text: str, given: bool,
) -> None:
    """T30 (review round 4, F1; corrected by review round 5; any platform): with ``os.name`` set to ``posix`` for the one call
    (a no-op on a POSIX host), the function takes the branch a POSIX host takes, and the reader's rules on the text still
    apply in it: a colon, a newline, a reserved device stem as the final name or as the direct parent, a backslash, a
    trailing dot or space in the final name, a name decoded with ``surrogateescape`` and a relative spelling give none, and
    a reserved device name above the direct parent, or a trailing dot or space in an ancestor, which only Windows refuses,
    gives the path itself."""
    path = PurePosixPath(text)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "posix")
        got = file_access.reader_spelling(path)  # type: ignore[arg-type]
    assert (got is not None) == given, f"{label}: {got}"
    if got is not None:
        assert got == path


@pytest.mark.parametrize("name", [
    "note.txt", "a b.txt", "caf\u00e9", ".hidden", "x..y", "note.", "note ", "note. ", "...",
    pytest.param("a\\b", marks=pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows a backslash separates components")),
])
def test_the_reader_spelling_agrees_with_the_pinned_directory_on_the_final_name(tmp_path: Path, name: str) -> None:
    """T31 (review round 4, F1; any platform): for one final name, a real pinned directory's ``read_bytes`` and
    ``reader_spelling`` agree. A name the pinned directory refuses as a child name (``invalid child name``) has no
    spelling, and a name it admits (the read goes on to the file that is not there) has one, so the lister's restatement of
    that rule is the reader's."""
    root = tmp_path.resolve()
    with file_access.pin_directory(root) as directory:
        try:
            directory.read_bytes(name)
        except FileAccessDenied as refused:
            assert refused.reason == "invalid child name", name
            admitted = False
        except FileNotFoundError:
            admitted = True
    assert (file_access.reader_spelling(root / name) is not None) == admitted, name


def test_the_reader_spelling_calls_no_filesystem_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """T32 (review round 4, F2; any platform): ``reader_spelling`` calls none of ``os.stat``, ``os.lstat``, ``os.scandir``,
    ``os.listdir``, ``os.getcwd`` and ``open``, for a spelling it gives and for one it refuses, for an extended-prefix
    spelling and for a relative one. It builds path objects and strings, which is work for each match and is not a
    filesystem call (BF-953 L20)."""
    inputs = [_listed(*parts) for _, parts, _, _ in _TEXT_CASES] + [Path("note.txt")]
    if os.name == "nt":
        inputs += [Path("\\\\?\\C:\\data\\note.txt"), Path("\\\\?\\UNC\\host\\share\\dir\\f.txt")]

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("reader_spelling called a filesystem function")

    with monkeypatch.context() as patch:
        for function in ("stat", "lstat", "scandir", "listdir", "getcwd"):
            patch.setattr(os, function, refused)
        patch.setattr("builtins.open", refused)
        results = [file_access.reader_spelling(path) for path in inputs]
    assert any(result is not None for result in results), "premise: some spellings were given"
    assert any(result is None for result in results), "premise: some were refused"


_CARRIED = {
    "note.txt": b"ordinary file", "caf\u00e9.txt": b"non-ASCII file", "music-\U0001d11e.txt": b"astral file",
    "ok\\inner.txt": b"file in an ordinary directory",
}
_UNCARRIED = {
    "\ud800.txt": b"lone high surrogate", "a\udcffb.txt": b"lone low surrogate", "\ud800dir\\inner.txt": b"file in a surrogate directory",
}


@WINDOWS
@pytest.mark.parametrize("spelling", ["ordinary base", "extended-prefix base"])
async def test_a_listing_leaves_out_a_name_the_verified_reader_cannot_carry(
    tmp_path: Path, request: pytest.FixtureRequest, spelling: str,
) -> None:
    """T33 (review round 4, F1; Windows): a directory holds names that the plain reader opens and the verified reader's
    location gate refuses (an unpaired surrogate in a file's name, in another file's name and in a directory's name) beside an
    ordinary, a non-ASCII and an astral name and a file in an ordinary directory. ``list_files`` of its ordinary and of its
    extended-prefix spelling leaves the first kind out and lists the second, and every file it lists is opened by the verified
    reader with the bytes of the file it matched. The plain reader reads the first kind: that is the cost of listing by the
    verified reader's rules, and it is recorded (BF-953 L19)."""
    root = tmp_path.resolve() / "d"
    root.mkdir()
    prefixed = "\\\\?\\" + str(root)
    request.addfinalizer(lambda: shutil.rmtree(prefixed, ignore_errors=True))
    for name, data in {**_CARRIED, **_UNCARRIED}.items():
        target = prefixed + "\\" + name
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    runtime = _runtime(_scene(tmp_path), read_roots=[])
    reader = ReadFileTool(runtime)
    roots: dict[str, Any] = {
        "protected_roots": file_access.protected_read_roots(runtime), "exempt_roots": file_access.workspace_exempt_roots(runtime),
        "permitted_roots": file_access.permitted_read_roots(runtime) or None,
    }
    for name, data in _UNCARRIED.items():  # premise: the verified reader's gate refuses each, and the plain reader reads each
        with pytest.raises(ValueError):
            file_access.read_verified_file(Path(str(root) + "\\" + name), **roots)
        with open(prefixed + "\\" + name, "rb") as handle:
            assert handle.read() == data, name
    plain = await reader.invoke({"path": str(root) + "\\" + "\ud800.txt"})
    assert plain.error is None and "lone high surrogate" in repr(plain.output), "premise: the unarmed read_file opens it"
    listed = await ListFilesTool(runtime).invoke(
        {"pattern": "**/*", "path": prefixed if spelling == "extended-prefix base" else str(root)},
    )
    assert listed.error is None and set(listed.output) == {"files"}, f"{spelling}: {listed.error}"
    expected = sorted(str(root / name) for name in (*_CARRIED, "ok"))
    assert sorted(listed.output["files"]) == expected, f"{spelling}: the names the verified reader's gate admits"
    for name in expected:
        if Path(name).is_dir():
            continue
        snapshot = file_access.read_verified_file(reader.resolve_source_path(name), **roots)
        with open(prefixed + "\\" + str(Path(name).relative_to(root)), "rb") as source:
            assert snapshot.data == source.read(), f"{spelling}: the verified reader opened {name!r}"


# --- M7 (Amendment 4, review round 5): the listing admits exactly what the verified reader's text path admits ---


class _TextOnlyDirectory(file_access.PinnedDirectory):
    """A pinned directory with no handle: ``verify`` does nothing, so the real ``_leaf`` runs on a text."""

    def verify(self) -> None:
        return None


class _PosixParent(str):
    """A parent text that joins a child name as a POSIX path does, so the real ``_leaf`` runs its location gate on a ``str``."""

    def __truediv__(self, name: str) -> str:
        return str(PurePosixPath(self) / name)


class _WindowsParent(str):
    """The same for a Windows path."""

    def __truediv__(self, name: str) -> str:
        return str(PureWindowsPath(self) / name)


_TEXT_SHAPES = {"posix": (PurePosixPath, _PosixParent, "/data", "/"), "windows": (PureWindowsPath, _WindowsParent, "C:\\data", "\\")}

# (component, withheld by Windows' same-file rule wherever it stands: a reserved device name, a trailing dot or a trailing space)
_CORPUS_DIRS = [
    ("src", False), ("x..y", False), ("a:b", False),
    ("con", True), ("aux.py", True), ("dot.", True), ("space ", True),
]
_CORPUS_FILES = ["g.txt", "note", "x..y", "dot.", "space ", "a:b", "back\\slash", "aux.py", "con", "\ud800.txt"]


def _corpus(base: str, sep: str) -> list[tuple[str, bool]]:
    """Every file text from zero to three directories below *base*, each directory from ``_CORPUS_DIRS``, each final name
    from ``_CORPUS_FILES``; with whether Windows' same-file rule withholds a directory of it."""
    texts = []
    for depth in range(4):
        for dirs in itertools.product(_CORPUS_DIRS, repeat=depth):
            prefix = base + "".join(sep + name for name, _ in dirs)
            texts += [(f"{prefix}{sep}{name}", any(flag for _, flag in dirs)) for name in _CORPUS_FILES]
    return texts


def _reader_admits(text: str, shape: str, *, parent_gate: bool = True) -> bool:
    """Whether the steps the armed reader takes on a text alone admit *text*, each one the reader's own call, in the order
    ``read_verified_file`` takes them: its location gate on the file; its location gate on the file's direct parent, which
    ``PinnedDirectory.open`` applies to the path ``pin_directory(candidate.parent)`` gives it; then the child-name rule and
    the location gate of ``read_bytes``, run by the real ``PinnedDirectory._leaf`` on a directory with no handle. Nothing in
    the reader reads the text again: the directories above the direct parent are opened by name."""
    pure, parent_type, _, _ = _TEXT_SHAPES[shape]
    parsed = pure(text)
    directory = _TextOnlyDirectory()
    directory._paths = [parent_type(str(parsed.parent))]  # type: ignore[list-item]
    try:
        file_access.validate_read_location(text)
        if parent_gate:
            file_access.validate_read_location(str(parsed.parent))
        directory._leaf(parsed.name)
    except (ValueError, FileAccessDenied):
        return False
    return True


@pytest.mark.parametrize("shape", ["posix", pytest.param("windows", marks=WINDOWS)])
def test_the_listing_admits_exactly_what_the_verified_readers_text_path_admits(
    monkeypatch: pytest.MonkeyPatch, shape: str,
) -> None:
    """T34 (review round 5, A; the POSIX shape on any platform with ``os.name`` set to ``posix`` for the calls, the Windows
    shape on Windows): over a generated corpus of file texts (a reserved device name, a trailing dot or space, a colon and an
    ordinary name as a directory from zero to three deep, and as the final name, with a lone surrogate and a backslash among
    the final names), ``reader_spelling``
    gives a spelling for no text the verified reader's text path refuses, and for every text it admits, except on Windows
    one that the same-file rule withholds (a reserved device name, a trailing dot or a trailing space in a directory). The
    reader's text path is its own functions: ``validate_read_location`` on the file and on the file's direct parent, and the
    real ``PinnedDirectory._leaf``. Premises: the corpus is large, the reader's text path admits and refuses a share of it,
    and the corpus holds texts that only the parent's gate refuses."""
    pure, _, base, sep = _TEXT_SHAPES[shape]
    texts = _corpus(base, sep)
    holes: list[str] = []
    misses: list[str] = []
    admitted_count = only_the_parent_gate_refuses = 0
    with monkeypatch.context() as patch:
        if shape == "posix":
            patch.setattr(os, "name", "posix")
        for text, same_file_withholds in texts:
            admitted = _reader_admits(text, shape)
            admitted_count += admitted
            only_the_parent_gate_refuses += (not admitted) and _reader_admits(text, shape, parent_gate=False)
            listed = file_access.reader_spelling(PurePosixPath(text) if shape == "posix" else Path(text)) is not None
            if listed and not admitted:
                holes.append(text)
            if admitted and not listed and not (shape == "windows" and same_file_withholds):
                misses.append(text)
    assert len(texts) >= 3500, "premise: the corpus is large"
    assert 0.05 * len(texts) < admitted_count < 0.95 * len(texts), "premise: the reader's text path admits and refuses a share"
    assert only_the_parent_gate_refuses >= 100, "premise: the corpus holds texts only the parent's gate refuses"
    assert not holes, f"{len(holes)} listed texts the reader's text path refuses, for example {holes[:3]!r}"
    assert not misses, f"{len(misses)} texts the reader's text path admits and the listing withholds, for example {misses[:3]!r}"


def _make_file(root: Path, rel: tuple[str, ...], data: bytes) -> None:
    base = ("\\\\?\\" + str(root)) if os.name == "nt" else str(root)
    target = base + os.sep + os.sep.join(rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as handle:
        handle.write(data)


async def test_a_listing_and_the_verified_reader_agree_about_a_reserved_direct_parent(
    tmp_path: Path, request: pytest.FixtureRequest,
) -> None:
    """T35 (review round 5, A; any platform, real files): a directory named ``con`` and one named ``aux.py`` (made through the
    extended namespace on Windows) each hold ``g.txt``, as does an ordinary directory and ``con/sub``. The real
    ``read_verified_file`` refuses a file whose direct parent is a reserved device name before it reads the disk
    (``ValueError``), and reads the ordinary one and the one a reserved name above its direct parent. ``list_files`` lists the
    ordinary one and, off Windows, the one above, and each file it lists is read by the verified reader with its own bytes;
    on Windows the same-file rule also withholds the one above (BF-953 L21)."""
    root = tmp_path.resolve() / "d"
    root.mkdir()
    cleanup = ("\\\\?\\" + str(root)) if os.name == "nt" else str(root)
    request.addfinalizer(lambda: shutil.rmtree(cleanup, ignore_errors=True))
    files = {
        ("ok", "g.txt"): b"ordinary", ("con", "g.txt"): b"under con", ("aux.py", "g.txt"): b"under aux.py",
        ("con", "sub", "g.txt"): b"above the direct parent",
    }
    for rel, data in files.items():
        _make_file(root, rel, data)
    runtime = _runtime(_scene(tmp_path), read_roots=[])
    reader = ReadFileTool(runtime)
    roots: dict[str, Any] = {
        "protected_roots": file_access.protected_read_roots(runtime), "exempt_roots": file_access.workspace_exempt_roots(runtime),
        "permitted_roots": file_access.permitted_read_roots(runtime) or None,
    }

    def verified(name: str) -> bytes:
        return file_access.read_verified_file(reader.resolve_source_path(name), **roots).data

    for rel in (("con", "g.txt"), ("aux.py", "g.txt")):  # premise: the reader refuses a reserved direct parent as text
        with pytest.raises(ValueError):
            verified(str(root.joinpath(*rel)))
    assert verified(str(root / "ok" / "g.txt")) == b"ordinary"
    assert verified(str(root / "con" / "sub" / "g.txt")) == b"above the direct parent", "premise: a reserved name above is read"
    listed = await ListFilesTool(runtime).invoke({"pattern": "**/g.txt", "path": str(root)})
    assert listed.error is None and set(listed.output) == {"files"}, listed.error
    expected = [("ok", "g.txt")] if os.name == "nt" else [("ok", "g.txt"), ("con", "sub", "g.txt")]
    assert sorted(listed.output["files"]) == sorted(str(root.joinpath(*rel)) for rel in expected)
    for name in listed.output["files"]:
        assert verified(name) == files[Path(name).relative_to(root).parts], f"the verified reader opened {name!r}"
