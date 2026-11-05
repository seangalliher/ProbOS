"""BF-953 (#1752): ``resolve_read_path`` returns one decision for every spelling of one file.

A path is decided the same way however it is spelled: for the floor (a directory root and a file root), for
the exempt roots that lift the floor, and for the permitted roots; and the path returned is the resolved
path, which names the file the decision was made on. The Windows spellings are built from fixture files this
test creates. A spelling the host does not serve is skipped once its premise (it names the same file as the
ordinary spelling) fails, so a skip is never a pass. The textual canonicaliser, the identity helper and the
POSIX rule run on every platform.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import ReadFileTool
from probos.security import file_access
from probos.security.file_access import FileAccessDenied, protected_write_refusal, resolve_read_path
from tests.test_bf948_list_files_read_policy import _OUTSIDE, _PROTECTED, _list, _runtime, _scene

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"

_FAMILIES = [
    "forward slashes", "doubled separator", "dot segment", "dotdot via sibling dir", "dotdot via missing dir",
    "swapped case", "8.3 short name", "trailing dot", "trailing space", "default stream suffix", "device prefix",
    "extended prefix", "extended prefix, swapped case", "extended prefix, 8.3",
    "UNC localhost admin share", "UNC 127.0.0.1 admin share", "UNC computer-name admin share",
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
]
# The spellings the base decides differently from the ordinary one (measured on the committed head): the extended-length
# and share spellings and, for a file that is not on disk only (T1), a trailing space (the resolved path of a missing
# child of such a directory carries the extended-length prefix). M2 removes the marks.
_DECIDED_DIFFERENTLY = frozenset(_FAMILIES[11:])
_XFAIL = pytest.mark.xfail(strict=True, reason="BF-953: the base decides this spelling differently from the ordinary one")
_PARAMS = [pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY else name for name in _FAMILIES]
_PARAMS_T1 = [
    pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY | {"trailing space"} else name for name in _FAMILIES
]
_BASE_LACKS_IT = pytest.mark.xfail(strict=True, raises=AttributeError, reason="BF-953: M2 adds the helper this test calls")


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


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS_T1)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(tmp_path: Path, family: str) -> None:
    """T1: each spelling of a file is decided as its ordinary spelling is, against a directory root and a file root of
    the floor, an exempt root under the floor, and a permitted root; so is a file that is not on disk; and the path an
    admitted call returns is the resolved path and names the file."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve(), lay.config.resolve()]
    exempt, permitted = [lay.work.resolve()], [lay.allowed.resolve()]
    cases = [
        (lay.floor_note, {"protected": floor, "exempt": exempt}, "refused"),
        (lay.config, {"protected": floor}, "refused"),
        (lay.neighbour, {"protected": floor}, "admitted"),
        (lay.work_note, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed_note, {"permitted": permitted}, "admitted"),
        (lay.outside_note, {"permitted": permitted}, "refused"),
    ]
    for target, roots, expected in cases:
        ordinary = _decide(str(target), **roots)
        assert ordinary[0] == expected, f"premise: the ordinary spelling of {target.name}: {ordinary}"
        spelled = _decide(_spelling(family, target), **roots)
        assert spelled[0] == expected, f"{family} of {target.name}: {spelled}"
        if expected == "refused":
            assert spelled[1] == ordinary[1], f"{family} of {target.name}: another reason"
        else:
            assert Path(spelled[1]) == Path(spelled[1]).resolve(), "the path returned is a resolved path"
            assert os.path.samestat(os.stat(spelled[1]), os.stat(target)), "the path returned names the file"
    missing = [
        (lay.data, {"protected": floor}, "refused"),
        (lay.work, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed, {"permitted": permitted}, "admitted"),
        (lay.outside, {"permitted": permitted}, "refused"),
    ]
    for directory, roots, expected in missing:
        absent = "missing note long name.txt"
        assert _decide(str(directory / absent), **roots)[0] == expected, "premise: the ordinary spelling"
        spelling = _spelling_or_none(family, directory)
        if spelling is not None:
            assert _decide(spelling + "\\" + absent, **roots)[0] == expected, f"{family}, not on disk"


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_read_file_decides_every_spelling_alike(tmp_path: Path, family: str) -> None:
    """T2: ``ReadFileTool`` answers every spelling of a file as it answers the ordinary one."""
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
        assert spelled.error == refusal, f"{family} of {note.name}: {spelled.error}"
        if refusal is None:
            assert "bf953 fixture" in repr(spelled.output)


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_list_files_decides_every_spelling_of_a_directory_alike(tmp_path: Path, family: str) -> None:
    """T3: ``list_files`` asks the same function for its base and for each match, on BF-948's rig. The ordinary
    spellings are decided first (the premise); then a spelling of the floor directory is refused, a spelling of a
    directory outside the permitted root is refused, and a spelling of the permitted root and of the agent
    workspace under the floor is listed."""
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
    assert spelled.error is None, f"{family}: {spelled.error}"
    assert {Path(n).name for n in spelled.output["files"]} == {"allowed note long name.txt", "ok.txt", "sub"}, family
    workspace = await _list(scene, [], "*", _spelling(family, scene.workspace))
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


@_BASE_LACKS_IT
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
def test_the_namespace_free_form(text: str, expected: str) -> None:
    """T5: pure text, the same on every platform: the extended and device prefixes of a drive path and the extended
    UNC prefix go; a volume or device name, a drive-relative form and a path of another platform stay."""
    assert file_access._namespace_free(text) == expected


@_BASE_LACKS_IT
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
def test_the_namespace_free_form_agrees_with_the_write_sides_key(text: str) -> None:
    """T6: for every spelling the canonicaliser rewrites, the write side's key (BF-911) of the text and of the rewrite
    are the same."""
    assert file_access._write_key(text) == file_access._write_key(file_access._namespace_free(text))


@_BASE_LACKS_IT
def test_file_identity_is_the_file_the_system_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T7: one identity for every name of a file, none for a path that names nothing, and none when the filesystem
    reports no file index."""
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
    assert file_access._file_identity(Path("bad\x00name")) is None
    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", lambda _path: SimpleNamespace(st_dev=7, st_ino=0))
        assert file_access._file_identity(note) is None


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
@_BASE_LACKS_IT
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
@_BASE_LACKS_IT
def test_a_share_path_no_root_covers_stays_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10: containment of a share path is decided by identity. With the system's answers replaced (no host is
    contacted), a share path that is not the root and has no ancestor that is the root is not inside it, and one
    that has is."""
    root = _fixture(tmp_path).data.resolve()
    absent_root = root.parent / "no-such-root"
    same_as_root = Path("\\\\bf953-alias\\share\\floor")
    known = {root: (1, 1), same_as_root: (1, 1), absent_root: None}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known[path] if path in known else (2, hash(path)))
    elsewhere = Path("\\\\bf953-remote\\share\\dir\\note.txt")
    inside = same_as_root / "sub" / "note.txt"
    assert file_access._longest_match(elsewhere, [root]) is None
    assert file_access._longest_match(inside, [root]) == root
    assert file_access._longest_match(same_as_root, [root]) == root
    assert file_access._longest_match(inside, [absent_root]) is None
