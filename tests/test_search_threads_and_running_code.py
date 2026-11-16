"""Searches off the event loop (#1803) and agent writers kept out of the running vessel's code (#1806).

#1803: file search, code search (both engines) and list_files ask the read policy about each match in a worker thread, so a
broad search does not hold the event loop; list_files stops after a cap of glob matches and says so; a read policy composed
with no runtime warns once per process. #1806: the Captain's documents rule, at all eight writer sites, also refuses a path
at or below the running package directory, as written or once resolved, and a .env file that load_dotenv() can read.

Loop liveness (S1 to S3): the policy check is wrapped by ``_LoopProbe``. Every call records whether it ran on the event
loop's thread; the first call also waits on a threading.Event that only a coroutine on the loop sets. On a worker thread
the wait ends at the next tick; on the loop's own thread that coroutine cannot run, so the wait reaches ``_WAIT_S`` and
the case fails at its assert. No case asserts on a duration.
Writes (R3 to R13): a temporary package stands in for the running one (``builder_paths._RUNNING_PACKAGE``,
``swe_tools._PROJECT_ROOT`` and the standing-orders directory point into it), so the base tree writes into the temporary
tree only. R0 to R2 read the real package and write nothing on either tree.
A case marked ``until_built("#N")`` fails on the base at its own assert; the milestone that builds #N adds it to
``_BUILT``. ``SEARCH_AND_RUNNING_CODE_RUNXFAIL=1`` runs every case plainly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos
from probos.agents import code_search
from probos.agents.code_search import CodeSearchAgent
from probos.agents.file_search import FileSearchAgent
from probos.cognitive import builder_paths, standing_orders
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, ListFilesTool
from probos.security import file_access
from tests.test_ad1344_constitution_write_refusal import _dir_link
from tests.test_bf943_captain_document_write_refusal import _call, _office_file, _tree

_BUILT: frozenset[str] = frozenset()


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("SEARCH_AND_RUNNING_CODE_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_WAIT_S = 10.0  # a ceiling only a check on the loop's own thread reaches; a worker's wait ends at the next tick
_TICK_S = 0.005
_TOKEN = "search-threads-needle"
_FILES = 40
_rule = builder_paths.captain_document_write_refusal
_ABSENT_TEXT = "a text that builder_paths.py does not hold: 7d1c0e58"
_GENERAL = ("write_file", "edit_file", "commit", "propose", "docx_create", "pptx_create")


def _on_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _LoopProbe:
    """The slow filter's partner (module docstring)."""

    def __init__(self) -> None:
        self.on_loop: list[bool] = []
        self.answered: list[bool] = []
        self._pending: list[threading.Event] = []

    def call(self) -> None:
        self.on_loop.append(_on_loop())
        if self._pending:
            return
        event = threading.Event()
        self._pending.append(event)
        self.answered.append(event.wait(_WAIT_S))

    async def run(self, awaitable: Any) -> Any:
        task = asyncio.ensure_future(awaitable)
        while not task.done():
            for event in list(self._pending):
                event.set()
            await asyncio.sleep(_TICK_S)
        return task.result()


def _runtime(tmp: Path) -> SimpleNamespace:
    """What the read policy reads: a data directory (the floor), the agent workspace under it, and no read_roots."""
    data = tmp / "data"
    (data / "workspaces").mkdir(parents=True)
    return SimpleNamespace(
        data_dir=data,
        config_path=None,
        config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[]),
            execution=SimpleNamespace(workspace_root=str(data / "workspaces")),
        ),
    )


def _project(tmp: Path, count: int = _FILES) -> Path:
    root = tmp / "project"
    root.mkdir()
    for index in range(count):
        (root / f"note-{index:02d}.txt").write_text(f"{_TOKEN} {index}\n", encoding="utf-8")
    return root


# --- #1803 ---------------------------------------------------------------------------------------------------------


@until_built("#1803")
async def test_s1_file_search_asks_the_policy_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S1 (kills N1)."""
    tmp = tmp_path.resolve()
    root, rt, probe = _project(tmp), _runtime(tmp), _LoopProbe()
    real = file_access.ReadFloor.permits

    def permits(self: Any, path: str) -> bool:
        probe.call()
        return real(self, path)

    monkeypatch.setattr(file_access.ReadFloor, "permits", permits)
    result = await probe.run(FileSearchAgent(agent_id="s1", runtime=rt)._search_files(str(root), "*.txt"))
    assert result["success"] is True and result["count"] == _FILES, result  # control: the policy admits every file
    assert probe.answered == [True], probe.answered
    assert probe.on_loop and not any(probe.on_loop), probe.on_loop


@until_built("#1803")
@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_s2_code_search_asks_the_policy_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    """S2 (python kills N2; rg kills N3 and N4): the engine's checks and the final check."""
    tmp = tmp_path.resolve()
    root, rt, probe = _project(tmp), _runtime(tmp), _LoopProbe()
    real = code_search._ReadFloor.permits

    def permits(self: Any, path: str) -> bool:
        probe.call()
        return real(self, path)

    monkeypatch.setattr(code_search._ReadFloor, "permits", permits)
    if engine == "python":
        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
    else:
        stdout = "".join(f"{path}\x001:{_TOKEN}\n" for path in sorted(root.iterdir())).encode("utf-8")

        class _Rg:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return stdout, b""

        async def spawn(*_args: object, **_kwargs: object) -> _Rg:
            return _Rg()

        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: "rg-stub")
        monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", spawn)
    agent = CodeSearchAgent(agent_id=f"s2-{engine}", runtime=rt)
    plan = await agent.decide({"params": {"path": str(root), "pattern": _TOKEN}})
    result = await probe.run(agent.act(plan))
    assert (result["engine"], result["count"]) == (engine, _FILES), result
    assert probe.answered == [True], probe.answered
    assert probe.on_loop and not any(probe.on_loop), probe.on_loop


@until_built("#1803")
async def test_s3_list_files_asks_the_policy_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S3 (kills N5): each match's check; the base path's one check (``relative_base``) stays on the loop."""
    tmp = tmp_path.resolve()
    root, rt, probe = _project(tmp), _runtime(tmp), _LoopProbe()
    real = swe_tools.resolve_read_path

    def resolve(raw: str, **kwargs: Any) -> Path:
        if "relative_base" not in kwargs:
            probe.call()
        return real(raw, **kwargs)

    monkeypatch.setattr(swe_tools, "resolve_read_path", resolve)
    result = await probe.run(ListFilesTool(rt).invoke({"pattern": "*.txt", "path": str(root)}))
    assert result.success and len(result.output["files"]) == _FILES, result
    assert probe.answered == [True], probe.answered
    assert probe.on_loop and not any(probe.on_loop), probe.on_loop


@until_built("#1803")
async def test_s4_list_files_stops_at_the_cap_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S4 (kills N6): six matches, a cap of five."""
    tmp = tmp_path.resolve()
    root, rt = _project(tmp, count=6), _runtime(tmp)
    monkeypatch.setattr(swe_tools, "_LIST_FILES_MAX_MATCHES", 5, raising=False)  # raising=False: the base has none
    result = await ListFilesTool(rt).invoke({"pattern": "*.txt", "path": str(root)})
    assert result.success, result
    assert len(result.output["files"]) == 5 and result.output.get("truncated") is True, result.output
    note = result.output.get("note", "")
    assert "5 matches" in note and "at least one more" in note, note


async def test_s4_control_a_listing_at_the_cap_is_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: exactly the cap is not truncated, and the output keeps its one key."""
    tmp = tmp_path.resolve()
    root, rt = _project(tmp, count=5), _runtime(tmp)
    monkeypatch.setattr(swe_tools, "_LIST_FILES_MAX_MATCHES", 5, raising=False)
    result = await ListFilesTool(rt).invoke({"pattern": "*.txt", "path": str(root)})
    assert set(result.output) == {"files"} and len(result.output["files"]) == 5, result.output


@until_built("#1803")
async def test_s5_a_read_policy_with_no_runtime_warns_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """S5 (kills N7 and N8): one floor with a runtime (no warning), one with none on a worker thread, one on the loop."""
    monkeypatch.setattr(file_access, "_NO_RUNTIME_WARNED", False, raising=False)
    caplog.set_level(logging.WARNING, logger=file_access.logger.name)
    file_access.ReadFloor(_runtime(tmp_path.resolve()))
    await asyncio.to_thread(file_access.ReadFloor, None)
    file_access.ReadFloor(None)
    warned = [r.getMessage() for r in caplog.records if "operator read_roots not applied" in r.getMessage()]
    assert len(warned) == 1, warned


# --- #1806 ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def vessel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A checkout-shaped tree whose ``src/probos`` stands in for the running package; the working directory is a sibling."""
    tmp = tmp_path.resolve()
    root, work = tmp / "vessel", tmp / "work"
    package = root / "src" / "probos"
    for rel in ("security/file_access.py", "cognitive/builder_paths.py"):
        (package / rel).parent.mkdir(parents=True, exist_ok=True)
        (package / rel).write_text("x v1\n", encoding="utf-8")
    (root / "config" / "standing_orders").mkdir(parents=True)
    (root / "docs").mkdir()
    work.mkdir()
    monkeypatch.setattr(builder_paths, "_RUNNING_PACKAGE", package, raising=False)  # raising=False: the base has none
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", root / "config" / "standing_orders")
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", root / "src")
    monkeypatch.chdir(work)
    return SimpleNamespace(root=root, package=package, work=work)


@until_built("#1806")
def test_r0_the_rule_reads_the_package_this_process_imported() -> None:
    """R0: the guarded directory is ``Path(probos.__file__).resolve().parent``."""
    assert getattr(builder_paths, "_RUNNING_PACKAGE", None) == Path(probos.__file__).resolve().parent


@until_built("#1806")
@pytest.mark.parametrize("given", ["probos/security/x.py", "probos/cognitive/builder_paths.py", "absolute"])
def test_r1_the_rule_refuses_the_real_running_package(given: str) -> None:
    """R1 (kills W1): write_file's relative forms at the real ``<checkout>/src``, and the rule module's absolute path."""
    package = Path(probos.__file__).resolve().parent
    assert swe_tools._PROJECT_ROOT.resolve() == package.parent, "premise: write_file roots a relative path at src"
    text = str(package / "cognitive" / "builder_paths.py") if given == "absolute" else given
    reason = _rule(text, swe_tools._PROJECT_ROOT)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
async def test_r2_edit_file_refuses_the_rules_own_module_with_its_reason_code(caplog: pytest.LogCaptureFixture) -> None:
    """R2 (kills W1): the real tool and module; the text to replace is not in that module (the premise assert), so the base edit replaces nothing and writes nothing."""
    module = Path(builder_paths.__file__).resolve()
    before = module.read_bytes()
    assert _ABSENT_TEXT.encode("utf-8") not in before, "premise: the base edit replaces nothing"
    caplog.set_level(logging.WARNING, logger=swe_tools.logger.name)
    result = await EditFileTool(SimpleNamespace()).invoke(
        {"path": "probos/cognitive/builder_paths.py", "old_text": _ABSENT_TEXT, "new_text": "AMENDED"},
    )
    assert module.read_bytes() == before
    assert not result.success and "BF-975" in (result.error or ""), result
    assert "BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused" in caplog.text


@until_built("#1806")
@pytest.mark.parametrize("writer", _GENERAL)
async def test_r3_each_writer_refuses_a_file_in_the_running_package(vessel: SimpleNamespace, writer: str) -> None:
    """R3 (kills W1): six of the eight sites by absolute path; write_file and edit_file by their relative form too."""
    target = vessel.package / "security" / "file_access.py"
    given = [str(target)] + (["probos/security/file_access.py"] if writer in ("write_file", "edit_file") else [])
    before = _tree(vessel.root)
    for path in given:
        written, error = await _call(writer, path)
        assert not written and "BF-975" in error, (path, error)
    assert _tree(vessel.root) == before


@until_built("#1806")
@pytest.mark.parametrize("writer", ["docx_revise", "xlsx_update"])
async def test_r4_the_office_revise_and_update_refuse_a_file_in_the_running_package(
    vessel: SimpleNamespace, writer: str,
) -> None:
    """R4 (kills W1): the other two sites."""
    target = _office_file(vessel.package / ("x.docx" if writer == "docx_revise" else "x.xlsx"))
    before = target.read_bytes()
    written, error = await _call(writer, str(target))
    assert not written and "BF-975" in error, error
    assert target.read_bytes() == before


_SPELLINGS: dict[str, Any] = {
    "upper-case": lambda p: str(p / "security" / "x.py").upper(),
    "trailing-dot": lambda p: str(p.parent / "probos." / "x.py"),
    "stream": lambda p: str(p / "security" / "x.py") + ":hidden",
    "dot-dot": lambda p: str(p.parent.parent / "docs" / ".." / "src" / "probos" / "x.py"),
}
if os.name == "nt":
    _SPELLINGS["extended-length"] = lambda p: "\\\\?\\" + str(p / "x.py")


@until_built("#1806")
@pytest.mark.parametrize("spelling", sorted(_SPELLINGS))
def test_r5_the_rule_refuses_the_package_in_every_spelling(vessel: SimpleNamespace, spelling: str) -> None:
    """R5 (kills W1)."""
    reason = _rule(_SPELLINGS[spelling](vessel.package), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
def test_r6_a_link_into_the_package_is_refused_once_resolved(vessel: SimpleNamespace) -> None:
    """R6 (kills W4): a junction (Windows) or symlink outside the package, to it."""
    door = vessel.root.parent / "door"
    _dir_link(door, vessel.package)
    assert os.path.samefile(door / "security" / "file_access.py", vessel.package / "security" / "file_access.py"), "premise"
    reason = _rule(str(door / "security" / "new.py"), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
def test_r7_a_link_inside_the_package_is_refused_as_written(vessel: SimpleNamespace) -> None:
    """R7 (kills W5): a link in the package to a directory outside it; only the written form is in the package."""
    outside = vessel.root.parent / "outside"
    outside.mkdir()
    _dir_link(vessel.package / "door", outside)
    assert os.path.samefile(vessel.package / "door", outside), "premise"
    reason = _rule(str(vessel.package / "door" / "new.py"), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
@pytest.mark.skipif(os.name != "nt", reason="8.3 aliases are a Windows form")
def test_r8_a_real_8_3_alias_of_the_package_is_refused(vessel: SimpleNamespace) -> None:
    """R8: only on a volume that makes short names."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    made = ctypes.windll.kernel32.GetShortPathNameW(str(vessel.package), buffer, 1024)
    if not made or buffer.value.lower() == str(vessel.package).lower():
        pytest.skip("this volume does not make 8.3 names")
    reason = _rule(str(Path(buffer.value) / "new.py"), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


_ENV_PLACES: dict[str, Any] = {
    "package": lambda v: v.package / ".env",
    "src": lambda v: v.package.parent / ".env",
    "checkout": lambda v: v.root / ".env",
}


@until_built("#1806")
@pytest.mark.parametrize("place", sorted(_ENV_PLACES))
async def test_r9_a_dotenv_file_the_loader_can_read_is_refused(vessel: SimpleNamespace, place: str) -> None:
    """R9 (src kills W2): the package directory and the directories above it, where load_dotenv() looks."""
    target = _ENV_PLACES[place](vessel)
    written, error = await _call("commit", str(target))
    assert not written and "BF-943" in error, error
    assert not target.exists()


@until_built("#1806")
@pytest.mark.parametrize("name", [".ENV", ".env.", ".env ", ".env:x"])
def test_r9b_a_dotenv_file_above_the_package_is_refused_in_every_spelling(vessel: SimpleNamespace, name: str) -> None:
    """R9b (kills W2)."""
    reason = _rule(str(vessel.package.parent / name), vessel.work)
    assert reason is not None and "BF-975" in reason, reason


@until_built("#1806")
async def test_r10_a_dotenv_file_at_the_writers_root_is_refused(vessel: SimpleNamespace) -> None:
    """R10 (kills W3): the working directory is neither the package nor above it; only the list entry holds it."""
    written, error = await _call("commit", ".env")
    assert not written and "BF-943" in error, error
    assert not (vessel.work / ".env").exists()


_NEIGHBOURS: dict[str, Any] = {
    "dotenv-in-a-subdirectory": lambda v: v.root / "docs" / ".env",
    "dotenv-example": lambda v: v.root / ".env.example",
    "envrc": lambda v: v.root / ".envrc",
    "dotenv-below-the-writers-root": lambda v: v.work / "sub" / ".env",
    "package-name-prefix": lambda v: v.package.parent / "probos_extra" / "x.py",
    "package-name-suffix": lambda v: v.package.parent / "probos.bak" / "x.py",
}


@pytest.mark.parametrize("name", sorted(_NEIGHBOURS))
async def test_r11_control_a_neighbour_of_the_package_or_of_a_dotenv_file_is_written(
    vessel: SimpleNamespace, name: str,
) -> None:
    """Control: these pass on both trees."""
    target = _NEIGHBOURS[name](vessel)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert _rule(str(target), vessel.work) is None
    written, error = await _call("commit", str(target))
    assert written, error


async def test_r12_control_a_tree_shaped_like_a_checkout_outside_the_package_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control (#1806's acceptance): ``tree/src/probos`` outside the running package, written with the working directory in it."""
    tree = tmp_path.resolve() / "tree"
    (tree / "src" / "probos").mkdir(parents=True)
    monkeypatch.chdir(tree)
    assert _rule("src/probos/x.py", tree) is None
    for writer, path in (("commit", "src/probos/x.py"), ("docx_create", "src/probos/report.docx"),
                         ("write_file", str(tree / "src" / "probos" / "y.py"))):
        written, error = await _call(writer, path)
        assert written, (writer, error)
    assert {p.name for p in (tree / "src" / "probos").iterdir()} == {"x.py", "report.docx", "y.py"}


@until_built("#1806")
def test_r13_the_refusal_names_the_running_code_and_the_reviewed_build(vessel: SimpleNamespace) -> None:
    """R13 (kills W1)."""
    reason = _rule(str(vessel.package / "x.py"), vessel.work) or ""
    assert "running vessel's code" in reason and "a build the Captain reviews" in reason, reason
