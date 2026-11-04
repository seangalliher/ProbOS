"""BF-948 (#1736): list_files lists only what the read policy admits.

The real ``ListFilesTool`` and ``ReadFileTool`` over a runtime carrying what the read policy reads
(``config.security_infra.read_roots``, ``config.execution.workspace_root`` and ``data_dir``), and one
agent-work run on the AD-1347 rig with the native tools registered. Nothing here replaces the read
policy except T8, which makes it raise to reach the failure handler.
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
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import ListFilesTool, ReadFileTool
from tests.test_ad1347_s3_execution import ANSWER, _call, _final, _rig, _seen
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
