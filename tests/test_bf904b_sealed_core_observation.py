"""BF-904b (#1585), milestone M1: the sealed-core observation (AD-481f, warn-only) can fire.

Before M1 ``_check_sealed_path`` returned at once without a runtime, and neither production caller of
``execute_approved_build`` passed one (the resolve route's ``_execute_build``, ``BuildDispatcher._execute_build``).
Given a runtime (``BuildPipeline``), it handed ``is_sealed_path`` the absolute ``Path(work_dir) / path``, which no
repository-relative glob matches. M1 passes the flag, reads this ProbOS's own policy file only when it is on, and
matches the change path repository-relative, with ``/`` separators and case folded. Observation only: no build is
refused for it (AD-481l is the hard block).

Rules: real git in repositories under ``tmp_path`` (helpers copied from the BF-904a tests); the real
``is_sealed_path`` with the real ``config/sealed_modules.yaml``; the real ``BuildDispatcher``, ``BuildPipeline`` and
a real boot. Every ``GIT_*`` name is removed from the environment and the policy cache is cleared around each test.
No sleeps; every await and subprocess is bounded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace as _SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.build_dispatcher import BuildDispatcher
from probos.build_pipeline import BuildPipeline
from probos.build_queue import BuildQueue
from probos.cognitive import builder as builder_module
from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.events import EventType
from probos.extensions import sealed_core as sealed_core_module
from probos.runtime import ProbOSRuntime
from probos.worktree_manager import WorktreeInfo, WorktreeManager

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
SEALED = "src/probos/substrate/agent.py"
SEALED_NEW = "src/probos/substrate/fresh.py"
SEED = {TARGET: "x = 1\n", SEALED: "a = 1\n"}
BUILDER_LOGGER = "probos.cognitive.builder"
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    sealed_core_module.load_sealed_globs.cache_clear()
    yield
    sealed_core_module.load_sealed_globs.cache_clear()


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "bf904b@example.invalid"),
        ("config", "user.name", "BF904b Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _spec(title: str = "bf904b probe") -> BuildSpec:
    return BuildSpec(title=title, description="")


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


def _modify_block(path: str, search: str, replace: str) -> str:
    return f"===MODIFY: {path}===\n===SEARCH===\n{search}\n===REPLACE===\n{replace}\n===END REPLACE===\n===END MODIFY===\n"


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    return await asyncio.wait_for(awaited, timeout=seconds)


async def _build(work_dir: Path, changes: list[dict[str, Any]], **kwargs: Any) -> BuildResult:
    kwargs.setdefault("run_tests", False)
    return await _bounded(execute_approved_build(changes, _spec(), str(work_dir), **kwargs))


class _Targeted:
    """Stands in for ``_run_targeted_tests``: answers *passes* in order and records each call's changed files."""

    def __init__(self, passes: list[bool]) -> None:
        self._passes = list(passes)
        self.calls: list[list[str]] = []

    async def __call__(self, work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        self.calls.append(list(changed_files))
        passed = self._passes.pop(0)
        return passed, ("1 passed" if passed else "1 failed"), ["tests/test_a.py"]


class _FakeModel:
    """A model client whose every answer is *reply* (the code review reads it too)."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=_SimpleNamespace(content=reply))


class _Runtime:
    """What the resolve route and ``BuildPipeline`` read from a runtime here: ``emit_event``, ``llm_client`` and,
    when given, ``config``. No ``pre_flight_runner`` and no ``hebbian_router``."""

    def __init__(self, config: SystemConfig | None = None) -> None:
        self.emit_event = MagicMock()
        self.llm_client = None
        if config is not None:
            self.config = config


def _config(enforce: bool) -> SystemConfig:
    config = SystemConfig()
    config.extensions.enforce_sealed_core = enforce
    return config


def _sealed_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == BUILDER_LOGGER and "sealed-core" in r.getMessage()]


def _route_modules() -> tuple[Any, Any]:
    """``(probos.api, probos.routers.build)``. The second takes its failure cache from the first, so it loads first."""
    import probos.api as api_module
    from probos.routers import build as build_router

    return api_module, build_router


# S1
@needs_git
@pytest.mark.parametrize("site", ["modify", "create", "repair-modify", "repair-create"])
async def test_a_write_to_a_sealed_path_is_observed_at_each_write_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, site: str,
) -> None:
    """Each of the four write sites logs one observation naming the path, and the build still commits."""
    repo = _init_repo(tmp_path / "repo", SEED)
    kwargs: dict[str, Any] = {"enforce_sealed_core": True}
    if site == "modify":
        changes, written = [_modify(SEALED, "a = 1", "a = 2")], SEALED
    elif site == "create":
        changes, written = [_create(SEALED_NEW, "z = 1\n")], SEALED_NEW
    else:
        changes = [_modify(TARGET, "x = 1", "x = 2")]
        if site == "repair-modify":
            written, reply = SEALED, _modify_block(SEALED, "a = 1", "a = 3")
        else:
            written, reply = SEALED_NEW, f"===FILE: {SEALED_NEW}===\nz = 1\n===END FILE===\n"
        monkeypatch.setattr(builder_module, "_run_targeted_tests", _Targeted([False, True]))
        kwargs.update(run_tests=True, llm_client=_FakeModel(reply))
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _build(repo, changes, **kwargs)
    assert result.success and result.commit_hash, f"premise: an observation never blocks the build: {result.error}"
    records = _sealed_records(caplog)
    assert len(records) == 1 and repr(written) in records[0], records


# S2
@pytest.mark.parametrize(
    ("spelling", "observed"),
    [
        ("src/Probos/SUBSTRATE/agent.py", True),
        ("src\\probos\\substrate\\agent.py", True),
        ("src/probos/./substrate//agent.py", True),
        ("src/probos/substrate_extra/agent.py", False),
        ("../src/probos/substrate/agent.py", False),
        ("docs/notes.md", False),
    ],
    ids=["mixed-case", "backslashes", "dot-and-double-slash", "sibling-directory", "escaping", "unsealed"],
)
def test_spellings_of_a_sealed_path_are_observed_and_others_are_not(
    caplog: pytest.LogCaptureFixture, spelling: str, observed: bool,
) -> None:
    globs = builder_module._sealed_globs()
    assert "src/probos/substrate/**" in globs, "premise: this ProbOS's policy seals the substrate"
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        builder_module._check_sealed_path(spelling, globs)
    assert bool(_sealed_records(caplog)) is observed


# S2b
@pytest.mark.parametrize("spelling", ["src/probos/substrate/agent.py", "src/probos/substrate"], ids=["file", "directory-itself"])
def test_a_glob_is_matched_without_regard_to_case(caplog: pytest.LogCaptureFixture, spelling: str) -> None:
    """``directory-itself`` reaches only ``is_sealed_path``'s prefix test, which compares case-sensitively on every
    host, so it shows the globs are folded even where ``fnmatch`` already ignores case (Windows)."""
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        builder_module._check_sealed_path(spelling, ("SRC/Probos/Substrate/**",))
    assert len(_sealed_records(caplog)) == 1


# S3
@needs_git
@pytest.mark.parametrize("flag", ["off", "unset-without-runtime"])
async def test_with_the_flag_off_no_policy_is_read_and_nothing_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, flag: str,
) -> None:
    loads: list[int] = []
    matches: list[str] = []
    real_globs = builder_module._sealed_globs
    real_match = sealed_core_module.is_sealed_path
    monkeypatch.setattr(builder_module, "_sealed_globs", lambda: loads.append(1) or real_globs())
    monkeypatch.setattr(
        sealed_core_module, "is_sealed_path", lambda path, globs=None: matches.append(str(path)) or real_match(path, globs),
    )
    repo = _init_repo(tmp_path / "repo", SEED)
    kwargs: dict[str, Any] = {"enforce_sealed_core": False} if flag == "off" else {}
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _build(repo, [_modify(SEALED, "a = 1", "a = 2")], **kwargs)
    assert result.success and result.commit_hash, result.error
    assert loads == [], "no policy is read with the flag off"
    assert matches == [], "and nothing is matched"
    assert _sealed_records(caplog) == []


# S4
@needs_git
async def test_the_policy_is_this_probos_file_not_the_work_tree_or_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A build writes the work tree, config/ included, so a policy there (here an empty one) must not switch the
    observation off; and the process's working directory is not the repository."""
    repo = _init_repo(tmp_path / "repo", {**SEED, "config/sealed_modules.yaml": "sealed_globs: []\n"})
    monkeypatch.chdir(repo)  # a policy read relative to the working directory reads the empty file above
    assert builder_module._SEALED_POLICY.is_file(), "premise: this ProbOS's policy file exists"
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _build(repo, [_modify(SEALED, "a = 1", "a = 2")], enforce_sealed_core=True)
    assert result.success and result.commit_hash, result.error
    assert len(_sealed_records(caplog)) == 1


# S5
@needs_git
@pytest.mark.parametrize("runtime_kind", ["flag-on", "no-config"])
async def test_the_resolve_route_passes_the_runtime_flag(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, runtime_kind: str,
) -> None:
    _api_module, build_router = _route_modules()
    repo = _init_repo(tmp_path / "repo", SEED)
    rt = _Runtime(_config(True)) if runtime_kind == "flag-on" else _Runtime()
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        await _bounded(build_router._execute_build(
            "bf904b-s5", [_modify(SEALED, "a = 1", "a = 2")], _spec(), str(repo), rt, run_tests=False,
        ))
    kinds = [call.args[0] for call in rt.emit_event.call_args_list]
    assert EventType.BUILD_SUCCESS in kinds, f"premise: the build ran and committed: {kinds}"
    assert len(_sealed_records(caplog)) == (1 if runtime_kind == "flag-on" else 0)


# S6
@pytest.mark.parametrize("flag", [True, False], ids=["on", "default"])
async def test_the_dispatcher_hands_its_flag_to_the_executor(flag: bool) -> None:
    queue = BuildQueue()
    build = queue.enqueue(BuildSpec(title="bf904b dispatch", description="d", target_files=[TARGET]))
    queue.update_status(build.id, "dispatched")
    worktrees = MagicMock(spec=WorktreeManager)
    worktrees.create = AsyncMock(return_value=WorktreeInfo(path="/tmp/wt", branch=f"builder-{build.id[:8]}", build_id=build.id, created_at=0.0))
    generated = MagicMock()
    generated.success = True
    generated.file_blocks = [{"path": TARGET, "mode": "create", "content": "x = 2\n", "base": ""}]
    generated.error = ""
    adapter = MagicMock(spec=CopilotBuilderAdapter)
    adapter.start = AsyncMock()
    adapter.stop = AsyncMock()
    adapter.execute = AsyncMock(return_value=generated)
    stopped = BuildResult(success=False, spec=build.spec, error="bf904b: stop after the executor")
    kwargs: dict[str, Any] = {"enforce_sealed_core": True} if flag else {}
    with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
         patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=adapter) as adapter_cls, \
         patch("probos.build_dispatcher.repository_identity", new_callable=AsyncMock, return_value="/tmp/wt/.git"), \
         patch("probos.build_dispatcher.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
        adapter_cls.is_available.return_value = True
        dispatcher = BuildDispatcher(queue=queue, worktree_mgr=worktrees, **kwargs)
        await _bounded(dispatcher._execute_build(build))
    assert executor.await_args is not None, "premise: the dispatcher reached the executor"
    assert executor.await_args.kwargs["enforce_sealed_core"] is flag
    assert dispatcher.enforce_sealed_core is flag


# S7
async def test_a_real_boot_wires_the_config_flag_into_the_dispatcher(tmp_path: Path) -> None:
    """``init_structural_services`` builds the one dispatcher, and nothing else passes it the flag."""
    config = _config(True)
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await _bounded(runtime.start(), 600)
    try:
        assert runtime.build_dispatcher is not None, "premise: the boot started the build dispatcher"
        assert runtime.build_dispatcher.enforce_sealed_core is True
    finally:
        await _bounded(runtime.stop(), 600)


# S8
@needs_git
async def test_build_pipeline_still_turns_it_on_through_its_runtime(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    pipeline = BuildPipeline(runtime=_Runtime(_config(True)))
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        result = await _bounded(pipeline.execute_approved_build(
            [_modify(SEALED, "a = 1", "a = 2")], _spec(), str(repo), run_tests=False,
        ))
    assert result.success and result.commit_hash, result.error
    assert len(_sealed_records(caplog)) == 1


# S9 (Amendment A2; the corrupt scalars and the unlisted class, Amendment A4)
class _UnlistedParserFault(Exception):
    """A class no list names: what a parser raises on corrupt content is an open set (Amendment A4)."""


_OutOfMemory = MemoryError  # aliased: the phantom-API precheck reads a capitalised call as a ProbOS name
_POLICY_HEAD = b"sealed_globs:\n  - src/probos/substrate/**\n"
_UNREADABLE = [  # (id, policy bytes, the class the loader lets out); each real case executed on PyYAML 6.0.3
    ("not-utf-8", b"sealed_globs:\n  - \xff\xfe/**\n", "UnicodeDecodeError"),
    ("invalid-date", _POLICY_HEAD + b"reviewed: 2026-13-45\n", "ValueError"),
    ("overflow", _POLICY_HEAD + b"reviewed: 1" + b":0" * 179 + b".0\n", "OverflowError"),
    ("unknown-bool", _POLICY_HEAD + b"reviewed: !!bool neither\n", "KeyError"),
    ("empty-int", _POLICY_HEAD + b'reviewed: !!int ""\n', "IndexError"),
    ("bad-timestamp", _POLICY_HEAD + b"reviewed: !!timestamp never\n", "AttributeError"),
    ("deep-nesting", b"", "RecursionError"),  # sized in the test from the recursion limit
    ("unlisted-class", _POLICY_HEAD, "_UnlistedParserFault"),  # a valid file; the loader's parser is replaced
]


def _parser_raising(fault: type[BaseException]) -> Any:
    """The loader's ``yaml``, with ``safe_load`` replaced by one that raises *fault*; its ``YAMLError`` is kept."""

    def _safe_load(stream: Any) -> Any:
        raise fault("injected")

    return _SimpleNamespace(safe_load=_safe_load, YAMLError=sealed_core_module.yaml.YAMLError)


@needs_git
@pytest.mark.parametrize(("kind", "text", "raised"), _UNREADABLE, ids=[case[0] for case in _UNREADABLE])
async def test_a_policy_that_cannot_be_read_observes_nothing_and_the_build_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, kind: str, text: bytes,
    raised: str,
) -> None:
    """The loader degrades a missing file, a YAML error and an OS error itself. Whatever else it raises on the file,
    of any class but ``MemoryError``, ``_sealed_globs`` catches (Amendment A4): a file that is not UTF-8, the classes
    PyYAML's constructors raise on corrupt scalars, nesting past the recursion limit, and a class no list names. With
    the flag on, one warning names the file and the exception class, nothing is observed, and the resolve route's
    build still commits (D5). A scratch policy is substituted; the shipped one loads. The class assertion is the
    premise: a case a later PyYAML turns into a ``YAMLError`` fails here, since the loader's own warning is not this."""
    if kind == "deep-nesting":  # the composer recurses twice per level, so this depth passes the limit whatever it is
        depth = sys.getrecursionlimit()
        text = ("sealed_globs: " + "[" * depth + "]" * depth + "\n").encode("utf-8")
    elif kind == "unlisted-class":
        monkeypatch.setattr(sealed_core_module, "yaml", _parser_raising(_UnlistedParserFault))
    policy = tmp_path / "policy" / "sealed_modules.yaml"
    policy.parent.mkdir()
    policy.write_bytes(text)
    monkeypatch.setattr(builder_module, "_SEALED_POLICY", policy)
    _api_module, build_router = _route_modules()
    repo = _init_repo(tmp_path / "repo", SEED)
    rt = _Runtime(_config(True))
    with caplog.at_level(logging.WARNING, logger=BUILDER_LOGGER):
        await _bounded(build_router._execute_build(
            "bf904b-s9", [_modify(SEALED, "a = 1", "a = 2")], _spec(), str(repo), rt, run_tests=False,
        ))
    kinds = [call.args[0] for call in rt.emit_event.call_args_list]
    assert EventType.BUILD_SUCCESS in kinds and EventType.BUILD_FAILURE not in kinds, f"the policy changed the build: {kinds}"
    degraded = [r.getMessage() for r in caplog.records if r.name == BUILDER_LOGGER and "sealed policy" in r.getMessage()]
    assert len(degraded) == 1 and str(policy) in degraded[0], degraded
    assert f"({raised})" in degraded[0], degraded
    assert _sealed_records(caplog) == [], "no globs, so the sealed write is not observed"


# S10 (Amendment A4)
def test_running_out_of_memory_while_loading_the_policy_still_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MemoryError`` is the process failing, not the policy: ``_sealed_globs`` lets it out, as before A4, and the
    route's own handler fails the build. The shipped policy is read; only the loader's parser is replaced."""
    assert builder_module._SEALED_POLICY.is_file(), "premise: the loader reaches its parser"
    monkeypatch.setattr(sealed_core_module, "yaml", _parser_raising(_OutOfMemory))
    with pytest.raises(_OutOfMemory):
        builder_module._sealed_globs()
