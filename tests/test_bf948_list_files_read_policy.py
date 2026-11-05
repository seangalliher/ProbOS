"""BF-948 (#1736): list_files lists only what the read policy admits.

The real ``ListFilesTool`` and ``ReadFileTool`` over a runtime carrying what the read policy reads
(``config.security_infra.read_roots``, ``config.execution.workspace_root`` and ``data_dir``), and one
agent-work run on the AD-1347 rig with the native tools registered. Nothing here replaces the read
policy except T8 and T12, which make it raise to reach a failure handler. M4 (T10 to T12): a refusal
the policy decided is not a tool fault on either detector path, and only the policy's refusal is
answered as refused. M5 (T13, T14): what a listing names is what the verified reader opens.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import requests_for_work_item
from probos.cognitive.agentic_dispatch import classify_tool_fault_error
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from probos.fault_detection import collect_tool_fault_batch
from probos.fault_report import detect_tool_defect
from probos.security.file_access import (
    permitted_read_roots, protected_read_roots, read_verified_file, workspace_exempt_roots,
)
from probos.tools.protocol import is_caller_input_error
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _rig, _seen, _watch_runs
from tests.test_ad1356_s1_input_errors import _faults
from tests.test_ad1356_s2_tool_effect_table import _native, _notes, _self_task
from tests.test_ad1356_s3_chain_of_command import _chain, _finished

SECRET_NAME = "secret-name-948.txt"
_OUTSIDE = "list_files refused: path is outside every readable root"
_PROTECTED = "list_files refused: path is protected: the runtime's data directory or a config file"
_PATTERN_REFUSAL = (
    "list_files refused: pattern must be a relative glob with no '..' part; name the directory in path"
)


@dataclass(frozen=True)
class _Scene:
    root: Path
    allowed: Path
    outside: Path
    data: Path
    workspace: Path


def _scene(tmp_path: Path) -> _Scene:
    """``allowed/`` (ok.txt, sub/inner.txt), ``outside/`` (the secret name), ``data/`` with the agent
    workspace under it, and a credential vault file name at the root."""
    root = tmp_path.resolve()
    allowed, outside, data = root / "allowed", root / "outside", root / "data"
    workspace = data / "workspaces"
    (allowed / "sub").mkdir(parents=True)
    outside.mkdir()
    workspace.mkdir(parents=True)
    (allowed / "ok.txt").write_text("ok", encoding="utf-8")
    (allowed / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    (outside / SECRET_NAME).write_text("outside contents", encoding="utf-8")
    (workspace / "scratch.txt").write_text("scratch", encoding="utf-8")
    (root / "credential_vault.json").write_text("{}", encoding="utf-8")
    return _Scene(root, allowed, outside, data, workspace)


def _runtime(scene: _Scene, *, read_roots: list[Path]) -> SimpleNamespace:
    """What the read policy reads: the roots, the workspace root and the data directory (the floor)."""
    return SimpleNamespace(
        data_dir=scene.data,
        config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[str(root) for root in read_roots]),
            execution=SimpleNamespace(workspace_root=str(scene.workspace)),
        ),
    )


async def _list(
    scene: _Scene, read_roots: list[Path], pattern: Any, path: str | None = None,
    context: dict[str, Any] | None = None,
) -> Any:
    params = {"pattern": pattern} if path is None else {"pattern": pattern, "path": path}
    return await ListFilesTool(_runtime(scene, read_roots=read_roots)).invoke(params, context)


def _link(link: Path, target: Path) -> None:
    """A directory junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _unlink(link: Path) -> None:
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


@pytest.mark.parametrize("strict", [pytest.param(False, id="plain"), pytest.param(True, id="strict-dispatch")])
@pytest.mark.parametrize("spelling", ["absolute", "dotdot", "other-case"])
async def test_list_files_refuses_a_base_outside_every_readable_root(
    tmp_path: Path, spelling: str, strict: bool,
) -> None:
    """``read_file`` refuses a file in that directory, so the roots are live; ``list_files`` refuses the
    directory with the policy's reason, in a strict effect dispatch too, and names nothing in it."""
    scene = _scene(tmp_path)
    runtime = _runtime(scene, read_roots=[scene.allowed])
    refused = await ReadFileTool(runtime).invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == "read_file refused: path is outside every readable root"  # premise
    path = {
        "absolute": str(scene.outside),
        "dotdot": str(scene.allowed / ".." / "outside"),
        "other-case": str(scene.outside).swapcase(),
    }[spelling]
    context = {"_effect_dispatch_context": object()} if strict else None
    result = await ListFilesTool(runtime).invoke({"pattern": "*", "path": path}, context)
    assert result.error == _OUTSIDE and result.output is None


async def test_a_refusal_is_the_same_whether_the_path_exists(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    present = await _list(scene, [scene.allowed], "*", str(scene.outside))
    absent = await _list(scene, [scene.allowed], "*", str(scene.outside / "no-such-dir"))
    assert present.error == absent.error == _OUTSIDE


async def test_list_files_lists_a_permitted_root_outside_the_project_tree(tmp_path: Path) -> None:
    """A match outside the project tree is listed by its absolute path, which ``read_file`` accepts as given."""
    scene = _scene(tmp_path)
    top = await _list(scene, [scene.allowed], "*", str(scene.allowed))
    assert top.error is None
    assert set(top.output["files"]) == {str(scene.allowed / "ok.txt"), str(scene.allowed / "sub")}
    deep = await _list(scene, [scene.allowed], "**/*.txt", str(scene.allowed))
    assert set(deep.output["files"]) == {
        str(scene.allowed / "ok.txt"), str(scene.allowed / "sub" / "inner.txt"),
    }
    read = await ReadFileTool(_runtime(scene, read_roots=[scene.allowed])).invoke(
        {"path": deep.output["files"][0]},
    )
    assert read.error is None


@pytest.mark.parametrize("pattern", [
    pytest.param("../*", id="climbs"),
    pytest.param("sub/../../*", id="climbs-after-a-step"),
    pytest.param("{anchor}*", id="anchored"),
    pytest.param(["*"], id="not-a-string"),
])
async def test_a_pattern_that_climbs_or_is_anchored_is_refused(tmp_path: Path, pattern: Any) -> None:
    """Reads are unconfined here and the base is the project tree, so only the pattern rule refuses."""
    scene = _scene(tmp_path)
    if pattern == "{anchor}*":
        pattern = scene.root.anchor + "*"
    result = await _list(scene, [], pattern)
    assert result.error == _PATTERN_REFUSAL and result.output is None


async def test_a_link_inside_a_permitted_root_to_outside_is_not_listed(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    door = scene.allowed / "door"
    _link(door, scene.outside)
    try:
        assert (door / SECRET_NAME).is_file()  # premise: the link reaches the outside file
        runtime = _runtime(scene, read_roots=[scene.allowed])
        refused = await ReadFileTool(runtime).invoke({"path": str(door / SECRET_NAME)})
        assert refused.error == "read_file refused: path is outside every readable root"  # premise
        lister = ListFilesTool(runtime)
        top = await lister.invoke({"pattern": "*", "path": str(scene.allowed)})
        assert top.error is None
        assert set(top.output["files"]) == {str(scene.allowed / "ok.txt"), str(scene.allowed / "sub")}
        through = await lister.invoke({"pattern": "door/*", "path": str(scene.allowed)})
        assert through.output == {"files": []}
        everything = await lister.invoke({"pattern": "**/*", "path": str(scene.allowed)})
        assert everything.error is None and "secret-name-948" not in repr(everything.output)
        assert str(door) not in everything.output["files"]
    finally:
        _unlink(door)


async def test_the_floor_and_credential_names_are_dropped_with_no_read_roots(tmp_path: Path) -> None:
    """Reads unconfined: the data directory and a credential vault file name are not listed, the data
    directory is refused as a base, and the agent workspace under it is listed."""
    scene = _scene(tmp_path)
    top = await _list(scene, [], "*", str(scene.root))
    assert top.error is None and set(top.output["files"]) == {str(scene.allowed), str(scene.outside)}
    assert (await _list(scene, [], "*", str(scene.data))).error == _PROTECTED
    work = await _list(scene, [], "*", str(scene.workspace))
    assert work.output == {"files": [str(scene.workspace / "scratch.txt")]}


async def test_in_tree_listing_is_unchanged(tmp_path: Path) -> None:
    """A match under the project tree (the checkout's ``src``) is listed relative to it, as before BF-948."""
    scene = _scene(tmp_path)
    nested = await _list(scene, [], "*.py", "probos/cognitive/swe_harness")
    assert str(Path("probos", "cognitive", "swe_harness", "tools.py")) in nested.output["files"]
    default = await _list(scene, [], "probos/__init__.py")
    assert default.output == {"files": [str(Path("probos", "__init__.py"))]}


async def test_a_failure_reply_and_log_name_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected failure is answered with its exception class only, and logged without its text."""
    scene = _scene(tmp_path)
    caplog.set_level(logging.WARNING, logger=swe_tools.__name__)

    def _fails(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError(f"SENTINEL {scene.outside / SECRET_NAME}")

    monkeypatch.setattr(swe_tools, "resolve_read_path", _fails)
    result = await _list(scene, [], "*", str(scene.allowed))
    assert result.error == "list_files failed: RuntimeError"
    assert "SENTINEL" not in caplog.text and "secret-name-948" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


async def test_an_agent_work_run_lists_inside_the_roots_and_is_refused_outside_them(tmp_path: Path) -> None:
    """The AD-1347 rig with the native tools, read_roots set to the notes' directory and elevated calls
    decided ``auto`` (as S4's WD1): one run lists outside the roots, then inside them."""
    notes = _notes(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / SECRET_NAME).write_text("outside contents", encoding="utf-8")
    script = [
        _call("list_files", {"pattern": "*", "path": str(outside)}, "c1"),
        _call("list_files", {"pattern": "*.txt", "path": str(notes.parent)}, "c2"),
        _final(ANSWER),
    ]
    async with _rig(tmp_path, script) as rig:
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == []  # premise: both calls ran directly
                assert not _seen(rig, "secret-name-948")
                assert _seen(rig, "outside every readable root") and _seen(rig, "notes.txt")
                assert not _seen(rig, "list_files failed")
        finally:
            await store.stop()


# --- M4 (Amendment 1): a refusal the policy decided is not a tool fault ---------------------------------


@pytest.mark.parametrize(("tool_id", "error", "marked"), [
    pytest.param("list_files", _OUTSIDE, True, id="list-files-refusal"),
    pytest.param("list_files", _PATTERN_REFUSAL, True, id="pattern-refusal"),
    pytest.param(
        "read_file", "read_file refused: path is protected: the runtime's data directory or a config file", True,
        id="read-file-refusal",
    ),
    pytest.param("event_log_query", "event_log_query_invalid:filter_required", True, id="the-s1-mark-still-holds"),
    pytest.param("list_files", "list_files refused: ", False, id="nothing-after-the-mark"),
    pytest.param("list_files", "list_files refused:x", False, id="no-space-after-the-colon"),
    pytest.param("list_files", "read_file refused: path is outside every readable root", False, id="another-tools-mark"),
    pytest.param("list_files", "List_Files refused: path is outside every readable root", False, id="other-case"),
    pytest.param("list_files", "list_files failed: RuntimeError", False, id="a-failure"),
    pytest.param("list_files", "list_files_failed", False, id="the-strict-failure"),
    pytest.param("", " refused: path is outside every readable root", False, id="no-tool-id"),
])
def test_a_tools_own_refusal_mark_is_not_a_tool_fault(tool_id: str, error: str, marked: bool) -> None:
    """The refusal mark is the tool's own non-empty id, then `` refused: ``, then at least one more character,
    case-sensitive. S1.2's ``_invalid:`` mark is unchanged, and a failure is never marked."""
    assert is_caller_input_error(tool_id, error) is marked


async def test_repeated_refusals_in_an_agent_work_run_file_no_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 1's F2 on the AD-1347 rig: two identical ``list_files`` refusals and two identical ``read_file``
    refusals in one run leave the fault store empty, emit nothing, and give the run no tool defect."""
    notes = _notes(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / SECRET_NAME).write_text("outside contents", encoding="utf-8")
    listing = {"pattern": "*", "path": str(outside)}
    reading = {"path": str(outside / SECRET_NAME)}
    script = [
        _call("list_files", listing, "c1"), _call("list_files", listing, "c2"),
        _call("read_file", reading, "c3"), _call("read_file", reading, "c4"),
        _final(ANSWER),
    ]
    runs = _watch_runs(monkeypatch)
    async with _rig(tmp_path, script) as rig:
        faults, events = _faults(rig)
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == []  # premise: all four calls ran directly
                assert _seen(rig, _OUTSIDE)  # premise: the list_files refusals reached the model
                assert _seen(rig, "read_file refused: path is outside every readable root")  # premise
                assert faults.list_open() == [] and events == []
                assert [run["outcome"].tool_defect for run in runs] == [None]
        finally:
            await store.stop()


def _pairs(*results: Any) -> SimpleNamespace:
    """The loop's pairs for ``read_file`` results, through the adapter it uses."""
    calls = [ToolCallRequest(name="read_file", arguments={}, id=f"r{n}") for n in range(len(results))]
    pairs = [ToolCallResult.from_tool_result(f"r{n}", result, 0.0) for n, result in enumerate(results)]
    assert all(  # premise: the adapter carries each error verbatim as an error
        pair.is_error is True and pair.output == result.error for pair, result in zip(pairs, results, strict=True)
    )
    return SimpleNamespace(tool_calls=calls, tool_results=pairs)


async def test_read_file_answers_refused_only_for_the_policys_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver failure that is not the policy's refusal reaches ``read_file``'s existing handlers, a missing file as
    ``File not found:`` and any other failure as ``read_file failed:``; neither carries the refusal mark, so both still
    count: two of the second are the run's defect, and two real refusals beside them are neither fault nor success
    evidence."""
    scene = _scene(tmp_path)
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.allowed]))
    refused = await reader.invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == "read_file refused: path is outside every readable root"  # premise

    def _broken(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError("policy layer broke")

    def _gone(*_args: Any, **_kwargs: Any) -> Path:
        raise FileNotFoundError("gone")

    ok = str(scene.allowed / "ok.txt")
    monkeypatch.setattr(swe_tools, "resolve_for_runtime", _gone)
    gone = await reader.invoke({"path": ok})
    assert gone.error == f"File not found: {ok}" and not is_caller_input_error("read_file", gone.error)
    monkeypatch.setattr(swe_tools, "resolve_for_runtime", _broken)
    broken = await reader.invoke({"path": ok})
    assert broken.error == "read_file failed: policy layer broke"
    outcome = _pairs(refused, refused, broken, broken)
    defect = detect_tool_defect(outcome)
    assert defect is not None
    assert (defect.tool_id, defect.error_text, defect.count) == ("read_file", broken.error, 2)
    [evidence] = collect_tool_fault_batch(outcome, classify_error=classify_tool_fault_error).tools
    assert evidence.defect is not None and evidence.defect.error_text == broken.error
    assert evidence.mixed is False and evidence.succeeded is False


# --- M5 (Amendment 2): what a listing names is what the armed reader opens ------------------------------


@pytest.mark.skipif(os.name != "nt", reason="BF-953: an extended-length prefix is a Windows path spelling")
async def test_a_listed_path_is_one_the_armed_reader_opens(tmp_path: Path) -> None:
    """Review round 2's finding 4, on the AD-1347 rig whose loop arms ``read_file`` with the workspace-result context:
    ``list_files`` on an extended-prefix spelling of the permitted directory lists the plain spelling, and a
    ``read_file`` of the very string it listed reads the file; neither answers a failure and no fault is filed."""
    notes = _notes(tmp_path)
    prefixed = {"pattern": "*.txt", "path": "\\\\?\\" + str(notes.parent)}
    script: list[Any] = [_call("list_files", prefixed, "c1"), None, _final(ANSWER)]
    async with _rig(tmp_path, script) as rig:
        faults, events = _faults(rig)
        store = await _native(rig, tmp_path, read_roots=[notes.parent])
        try:
            listing = await ListFilesTool(rig.runtime).invoke(prefixed)
            assert listing.error is None and len(listing.output["files"]) == 1
            [listed] = listing.output["files"]
            assert not listed.startswith("\\\\") and Path(listed).resolve() == notes.resolve()  # the plain spelling
            script[1] = _call("read_file", {"path": listed}, "c2")  # the string the listing gave, as it gave it
            async with _chain(rig, agent_work_elevated_decider="auto"):
                item_id = await _self_task(rig, "List the relay notes")
                await _finished(rig, item_id)
                assert requests_for_work_item(rig.requests, item_id) == []  # premise: both calls ran directly
                assert _seen(rig, "Relay drift notes")  # the armed reader returned the file's text
                assert not _seen(rig, "invalid path") and not _seen(rig, "read_file failed")
                assert faults.list_open() == [] and events == []
        finally:
            await store.stop()


@pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
async def test_every_name_a_listing_returns_is_one_the_verified_reader_opens(tmp_path: Path) -> None:
    """The second reviewer's R4: a listing of a directory of the project tree gives a project-relative name for the
    ordinary spelling of it and for the extended-prefix spelling (the display form is applied before the relative test),
    and every name returned, the one a local-share spelling returns too, is opened by the verified reader
    (``resolve_source_path``, then ``read_verified_file``) with the bytes of the file."""
    runtime = _runtime(_scene(tmp_path), read_roots=[])
    reader = ReadFileTool(runtime)
    target = swe_tools._PROJECT_ROOT / "probos" / "security"
    drive, rest = os.path.splitdrive(str(target))
    bases = {"ordinary": str(target), "extended prefix": "\\\\?\\" + str(target)}
    share = f"\\\\localhost\\{drive[0]}${rest}"
    try:
        if os.path.samestat(os.stat(share), os.stat(target)):
            bases["local share"] = share
    except OSError:
        pass  # a premise: this host does not serve the local share spelling
    for name, base in bases.items():
        listed = await ListFilesTool(runtime).invoke({"pattern": "file_access.py", "path": base})
        assert listed.error is None, f"{name}: {listed.error}"
        [entry] = listed.output["files"]
        if name != "local share":
            assert entry == str(Path("probos", "security", "file_access.py")), f"{name}: a project-relative name"
        snapshot = read_verified_file(
            reader.resolve_source_path(entry), protected_roots=protected_read_roots(runtime),
            exempt_roots=workspace_exempt_roots(runtime), permitted_roots=permitted_read_roots(runtime) or None,
        )
        assert snapshot.data == (target / "file_access.py").read_bytes(), f"{name}: the verified reader opened {entry!r}"
