"""BF-896 (#1550): a queued visiting build, end to end through the real dispatcher.

The seam this file crosses, which every unit test of its parts leaves open::

    worktree --> repository_identity pin --> session directory (mkdtemp, seeded)
      --> REAL CopilotBuilderAdapter on a fake SDK, under the REAL permission handler
      --> scan (only what the session created or changed; modify blocks carry "base")
      --> REAL execute_approved_build (builder_write_refusal live, identity re-checked)
      --> REAL git commit

Only the SDK client is fake. The worktree is a real temporary git repository, the queue,
the dispatcher, the adapter, the handler, the scan and the executor are real, and the
fake session behaves like the SDK's agent: it asks the handler installed in the config it
was created with before every write and writes only when the answer is "approved".

Every negative has a control that is asserted first, and every probe asserts its premise
so a setup that did not discriminate fails loudly. All paths live under ``tmp_path`` (the
session directories under a per-test temp root); nothing touches the repository tree.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos import build_dispatcher as dispatcher_module
from probos.build_dispatcher import BuildDispatcher
from probos.build_queue import BuildQueue, QueuedBuild
from probos.cognitive import copilot_adapter as sdk
from probos.cognitive.builder import BuildSpec
from probos.worktree_manager import WorktreeInfo, WorktreeManager

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

_APPROVED = "approved"
_DENIED = "denied-by-rules"

_A, _B, _NEW = "src/probos/a.py", "src/probos/b.py", "src/probos/new_mod.py"
_A_V1 = "def a() -> int:\n    return 1\n"
_A_V2 = "def a() -> int:\n    return 2\n"
_B_V1 = "def b() -> int:\n    return 1\n"
_NEW_MOD = "def new_mod() -> str:\n    return 'new'\n"
_SEEDED = {_A: _A_V1, _B: _B_V1}


# -- real git ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def _out(cwd: Path, *args: str) -> str:
    done = _git(cwd, *args)
    assert done.returncode == 0, f"premise: git {' '.join(args)} failed: {done.stderr}"
    return done.stdout.strip()


def _make_repo(path: Path, files: dict[str, str], branch: str = "main") -> Path:
    """A real repository with one initial commit holding *files* (repo-local identity)."""
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", branch),
        ("config", "user.email", "bf896@example.invalid"),
        ("config", "user.name", "BF896 Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    _out(path, "add", "--", ".")
    _out(path, "commit", "-q", "-m", "seed")
    return path


def _linked_worktree(root: Path) -> tuple[Path, Path, Path, Path]:
    """(base, victim, worktree, pointer): a linked worktree of *base* on ``main``.

    Adapted from tests/test_bf894_builder_write_boundary.py. The worktree's ``.git`` is a
    pointer file, which is what lets one rewrite move the repository the tree names.
    """
    base = _make_repo(root / "base", _SEEDED, branch="trunk")
    victim = _make_repo(root / "victim", {"README.md": "victim\n"}, branch="trunk")
    worktree = root / "wt"
    assert _git(base, "worktree", "add", "-q", "-b", "main", str(worktree)).returncode == 0, "premise"
    pointer = worktree / ".git"
    assert pointer.is_file(), "premise: a linked worktree's .git is a pointer file"
    if sys.platform == "win32":
        subprocess.run(["attrib", "-h", str(pointer)], check=True, capture_output=True)
        assert not os.stat(pointer).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN, "premise: pointer not hidden"
    return base, victim, worktree, pointer


def _snapshot(root: Path) -> dict[str, bytes]:
    """Every file under *root* except git's own (the ``.git`` directory or pointer file)."""
    files: dict[str, bytes] = {}
    for current, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name != ".git"]
        for name in names:
            if name != ".git":
                full = Path(current) / name
                files[full.relative_to(root).as_posix()] = full.read_bytes()
    return files


def _refs(repo: Path) -> str:
    """Every ref with its commit, and HEAD's branch: a new branch or commit changes this."""
    return _out(repo, "for-each-ref", "--format=%(refname) %(objectname)") + "|" + _out(
        repo, "rev-parse", "--abbrev-ref", "HEAD",
    )


def _show(repo: Path, branch: str, rel: str) -> str:
    done = _git(repo, "show", f"{branch}:{rel}")
    assert done.returncode == 0, f"{rel} is not on {branch}: {done.stderr}"
    return done.stdout.replace("\r\n", "\n")


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _inside(path: Path, root: Path) -> bool:
    child, parent = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives
        return False


# -- the fake SDK -----------------------------------------------------------------------


class _Kind(Enum):
    """The SDK 0.1.32 permission kinds: a real ``Enum``, never a ``str``."""

    WRITE = "write"
    READ = "read"
    SHELL = "shell"
    URL = "url"
    MCP = "mcp"
    MEMORY = "memory"
    CUSTOM_TOOL = "custom-tool"


@dataclass
class _Request:
    """The SDK 0.1.32 permission request: an ``Enum`` kind and snake_case fields."""

    kind: _Kind
    file_name: str | None = None
    path: str | None = None
    possible_paths: list[str] | None = None
    tool_name: str | None = None
    full_command_text: str | None = None


class _Sdk:
    """The fake SDK for one run: what the real adapter sent it and what its session did."""

    def __init__(self) -> None:
        self.script: Callable[[_FakeSession], Awaitable[None]] | None = None
        self.reply = ""
        self.start_error: Exception | None = None
        self.client_options: list[dict[str, Any]] = []
        self.configs: list[dict[str, Any]] = []
        self.lifecycle: list[str] = []
        self.requests: list[tuple[str, str, str]] = []  # (kind, subject, verdict)
        self.results_built: list[str] = []
        self.observed: dict[str, Any] = {}

    @property
    def session_dirs(self) -> list[Path]:
        """The session directories, as the SDK client was told them (its ``options["cwd"]``)."""
        return [Path(options["cwd"]) for options in self.client_options]

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = self

        @dataclass
        class _RecordedResult:
            """Stands in for ``PermissionRequestResult`` and records every result built."""

            kind: str

            def __post_init__(self) -> None:
                state.results_built.append(self.kind)

        monkeypatch.setattr(sdk, "_SDK_AVAILABLE", True)
        monkeypatch.setattr(dispatcher_module, "_SDK_AVAILABLE", True)
        # The options dict is positional-only, as in the SDK's CopilotClient.
        monkeypatch.setattr(sdk, "CopilotClient", lambda options, /: _FakeClient(state, options), raising=False)
        monkeypatch.setattr(sdk, "SessionEventType", SimpleNamespace(ASSISTANT_MESSAGE="assistant"), raising=False)
        monkeypatch.setattr(sdk, "Tool", lambda **kwargs: SimpleNamespace(**kwargs), raising=False)
        monkeypatch.setattr(sdk, "PermissionRequestResult", _RecordedResult, raising=False)


class _FakeClient:
    def __init__(self, state: _Sdk, options: dict[str, Any]) -> None:
        self._state = state
        self._options = options
        state.client_options.append(options)

    async def start(self) -> None:
        self._state.lifecycle.append("start")
        self._state.observed["dir_at_start"] = Path(self._options["cwd"]).is_dir()
        if self._state.start_error is not None:
            raise self._state.start_error

    async def create_session(self, config: dict[str, Any]) -> _FakeSession:
        self._state.configs.append(config)
        return _FakeSession(self._state, config)

    async def stop(self) -> None:
        self._state.lifecycle.append("stop")


class _FakeSession:
    """What the SDK's agent does: ask the config's permission handler, write only if approved."""

    def __init__(self, state: _Sdk, config: dict[str, Any]) -> None:
        self.state = state
        self.working_directory = Path(config["working_directory"])
        self._handler = config["on_permission_request"]

    def ask(self, request: _Request) -> str:
        result = self._handler(request, {"session_id": "bf896-fake"})
        verdict = result["kind"] if isinstance(result, dict) else result.kind
        subject = request.file_name or request.tool_name or request.full_command_text or ""
        self.state.requests.append((request.kind.value, subject, verdict))
        return verdict

    def write(self, target: str, text: str) -> str:
        verdict = self.ask(_Request(kind=_Kind.WRITE, file_name=target))
        if verdict == _APPROVED:
            destination = Path(target) if os.path.isabs(target) else self.working_directory / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8", newline="\n")
        return verdict

    async def send_and_wait(self, prompt: dict[str, str], *, timeout: float) -> None:
        if self.state.script is not None:
            await self.state.script(self)

    async def get_messages(self) -> list[Any]:
        if not self.state.reply:
            return []
        return [SimpleNamespace(type="assistant", data=SimpleNamespace(content=self.state.reply))]

    async def disconnect(self) -> None:
        self.state.lifecycle.append("disconnect")


# -- the real dispatcher over the fake SDK ----------------------------------------------


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This test's temp root: every ``probos_visiting_*`` session directory lands here."""
    root = tmp_path / "session-tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@dataclass
class _Outcome:
    build: QueuedBuild
    adapter_calls: list[dict[str, Any]]


def _spec(targets: list[str] | None = None, refs: list[str] | None = None) -> BuildSpec:
    return BuildSpec(
        title="BF-896 seam",
        description="BF-896 seam probe.",
        target_files=list(targets if targets is not None else [_A, _NEW]),
        reference_files=list(refs if refs is not None else [_B]),
    )


def _spy_on_adapter(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Route the dispatcher to a recording subclass of the REAL adapter."""
    calls: list[dict[str, Any]] = []
    real = sdk.CopilotBuilderAdapter

    class _Spy(real):  # type: ignore[valid-type, misc]
        def __init__(self, **kwargs: Any) -> None:
            calls.append(dict(kwargs))
            super().__init__(**kwargs)

    monkeypatch.setattr(dispatcher_module, "CopilotBuilderAdapter", _Spy)
    return calls


def _prepare(
    monkeypatch: pytest.MonkeyPatch, worktree: Path, state: _Sdk, spec: BuildSpec | None = None,
) -> tuple[BuildDispatcher, QueuedBuild, list[dict[str, Any]]]:
    state.install(monkeypatch)
    adapter_calls = _spy_on_adapter(monkeypatch)
    queue = BuildQueue()
    build = queue.enqueue(spec or _spec())
    queue.update_status(build.id, "dispatched")
    manager = MagicMock(spec=WorktreeManager)
    manager.create = AsyncMock(
        return_value=WorktreeInfo(path=str(worktree), branch="builder-bf896", build_id=build.id),
    )

    async def adopt_commit(build_id: str, branch: str) -> tuple[bool, str]:
        # BF-896 (R1-1): the real manager's adoption, done with the same two git effects in the plain repository,
        # so the mocked-manager tests see what a reviewing build holds: the commit on "builder-bf896", the
        # executor's branch gone. The real manager is exercised in the tests that use _prepare_real.
        sha = _out(worktree, "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}")
        _out(worktree, "branch", "-f", "builder-bf896", branch)
        _out(worktree, "branch", "-D", branch)
        return True, sha

    manager.adopt_commit = AsyncMock(side_effect=adopt_commit)
    return BuildDispatcher(queue=queue, worktree_mgr=manager, run_tests=False), build, adapter_calls


async def _run_build(
    monkeypatch: pytest.MonkeyPatch, worktree: Path, state: _Sdk, spec: BuildSpec | None = None,
) -> _Outcome:
    dispatcher, build, adapter_calls = _prepare(monkeypatch, worktree, state, spec)
    await dispatcher._execute_build(build)
    return _Outcome(build=build, adapter_calls=adapter_calls)


# -- the seam ---------------------------------------------------------------------------


async def test_a_queued_build_generates_off_the_worktree_and_commits_only_what_the_session_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo", _SEEDED)
    before = _snapshot(repo)
    state = _Sdk()

    async def session(s: _FakeSession) -> None:
        s.write(_A, _A_V2)  # an existing file, changed
        s.write(_NEW, _NEW_MOD)  # a new file
        # b.py is left exactly as it was seeded.
        state.observed["worktree_untouched"] = _snapshot(repo) == before
        state.observed["porcelain"] = _git(repo, "status", "--porcelain")
        state.observed["session_files"] = sorted(_snapshot(s.working_directory))

    state.script = session
    outcome = await _run_build(monkeypatch, repo, state)
    build = outcome.build

    # Controls, asserted first: the session wrote through the real handler, into its own seeded directory.
    assert state.requests == [("write", _A, _APPROVED), ("write", _NEW, _APPROVED)], build.error
    session_dir = state.session_dirs[0]
    assert session_dir.parent == sandbox and session_dir.name.startswith("probos_visiting_")
    assert not _inside(session_dir, repo) and not _inside(repo, session_dir), "premise: separate trees"
    assert outcome.adapter_calls[0]["cwd"] == str(session_dir)
    assert outcome.adapter_calls[0]["instruction_work_dir"] == str(repo)
    assert state.configs[0]["working_directory"] == str(session_dir) == state.client_options[0]["cwd"]
    assert state.observed["session_files"] == [_A, _B, _NEW], "premise: the session directory was seeded, b.py included"

    # While the session ran: the worktree's bytes were the pre-run snapshot and git saw nothing.
    assert state.observed["worktree_untouched"] is True, "the worktree changed during generation"
    porcelain = state.observed["porcelain"]
    assert porcelain.returncode == 0, "premise: git status ran"
    assert porcelain.stdout == ""

    # After: only the two files the session changed reached the branch, through the executor.
    assert build.status == "reviewing", build.error
    result = build.result
    assert result is not None and result.success, build.error
    branch = result.branch_name
    assert _out(repo, "diff", "--name-only", "main", branch).splitlines() == [_A, _NEW]
    assert _show(repo, branch, _A) == _A_V2
    assert _show(repo, branch, _NEW) == _NEW_MOD
    assert _out(repo, "rev-list", "--count", f"main..{branch}") == "1"
    assert result.files_modified == [_A]
    assert result.files_written == [_NEW]
    assert not session_dir.exists()
    assert _snapshot(repo) == before and _out(repo, "status", "--porcelain") == ""


async def test_the_session_cannot_write_into_the_worktree_or_run_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path / "repo", _SEEDED)
    before = _snapshot(repo)
    absolute_existing = str(repo / "src" / "probos" / "a.py")
    absolute_new = str(repo / "src" / "probos" / "evil.py")
    absolute_hook = str(repo / ".git" / "hooks" / "pre-commit")
    command = "git config core.hooksPath /tmp/evil"
    assert all(os.path.isabs(p) for p in (absolute_existing, absolute_new, absolute_hook)), "premise"
    state = _Sdk()

    async def session(s: _FakeSession) -> None:
        s.write(_A, _A_V2)  # control: a write inside the session directory
        state.observed["control_landed"] = (s.working_directory / _A).read_text(encoding="utf-8") == _A_V2
        s.write(absolute_existing, "PWNED = True\n")
        s.write(absolute_new, "PWNED = True\n")
        s.write(absolute_hook, "#!/bin/sh\necho pwned\n")
        if s.ask(_Request(kind=_Kind.SHELL, full_command_text=command)) == _APPROVED:
            (repo / "shell-ran.txt").write_text("ran\n", encoding="utf-8")  # what an approved shell would have done
        s.ask(_Request(kind=_Kind.CUSTOM_TOOL, tool_name="standing_orders_lookup"))
        state.observed["worktree_untouched"] = _snapshot(repo) == before
        state.observed["hook_exists"] = (repo / ".git" / "hooks" / "pre-commit").exists()

    state.script = session
    outcome = await _run_build(monkeypatch, repo, state)

    # The control comes first: an approved write lands, so a denial below is the handler's doing.
    assert state.requests == [
        ("write", _A, _APPROVED),
        ("write", absolute_existing, _DENIED),
        ("write", absolute_new, _DENIED),
        ("write", absolute_hook, _DENIED),
        ("shell", command, _DENIED),
        ("custom-tool", "standing_orders_lookup", _APPROVED),
    ], outcome.build.error
    assert state.observed["control_landed"] is True, "premise: an approved write is performed by the fake session"
    assert state.results_built == [verdict for _kind, _subject, verdict in state.requests], (
        "every answer was built through the SDK's PermissionRequestResult"
    )
    assert state.observed["worktree_untouched"] is True, "an absolute write reached the worktree"
    assert state.observed["hook_exists"] is False
    assert outcome.build.status == "reviewing", outcome.build.error
    assert _show(repo, "main", _A) == _A_V1


@pytest.mark.parametrize("hook_path", [".git/hooks/pre-commit", ".GiT/hooks/pre-commit"])
async def test_a_git_alias_block_from_the_session_is_refused_at_the_write_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hook_path: str,
) -> None:
    # Control, asserted first: the same fallback parse with a legitimate path reaches a commit.
    control_repo = _make_repo(tmp_path / "control", _SEEDED)
    control_state = _Sdk()
    control_state.reply = "===FILE: src/probos/ok.py===\nOK = True\n===END FILE===\n"
    control = await _run_build(monkeypatch, control_repo, control_state, _spec(["src/probos/ok.py"], []))
    assert control.build.status == "reviewing", control.build.error
    assert control_state.requests == [], "premise: the session wrote nothing; the block came from the reply text"
    assert _show(control_repo, control.build.result.branch_name, "src/probos/ok.py") == "OK = True\n"

    repo = _make_repo(tmp_path / "repo", _SEEDED)
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert not hook.exists(), "premise: no hook exists yet"
    entries, refs, commits = set(os.listdir(repo)), _refs(repo), _out(repo, "rev-list", "--all", "--count")
    state = _Sdk()
    state.reply = f"===FILE: {hook_path}===\n#!/bin/sh\necho pwned\n===END FILE===\n"
    outcome = await _run_build(monkeypatch, repo, state, _spec(["src/probos/ok.py"], []))

    assert state.requests == [], "premise: the session wrote nothing; the block came from the reply text"
    assert outcome.build.status == "failed"
    assert "Forbidden" in outcome.build.error, outcome.build.error
    assert not hook.exists()
    assert set(os.listdir(repo)) == entries
    assert _refs(repo) == refs and _out(repo, "rev-list", "--all", "--count") == commits


async def test_an_identity_change_during_generation_is_refused_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Control, asserted first: the same layout and the same session, without the swap, commits.
    control_base, control_victim, control_wt, _pointer = _linked_worktree(tmp_path / "control")
    control_victim_refs = _refs(control_victim)
    control_state = _Sdk()

    async def honest(s: _FakeSession) -> None:
        s.write(_A, _A_V2)

    control_state.script = honest
    control = await _run_build(monkeypatch, control_wt, control_state)
    assert control.build.status == "reviewing", control.build.error
    assert _show(control_base, control.build.result.branch_name, _A) == _A_V2
    assert _refs(control_victim) == control_victim_refs

    base, victim, worktree, pointer = _linked_worktree(tmp_path / "probe")
    pinned = _out(worktree, "rev-parse", "--absolute-git-dir")
    before, base_refs, victim_refs = _snapshot(worktree), _refs(base), _refs(victim)
    state = _Sdk()

    async def hostile(s: _FakeSession) -> None:
        s.write(_A, _A_V2)  # a legitimate change, so blocks do reach the executor
        # Anything outside the handler: the pointer now names the second repository.
        pointer.write_text(f"gitdir: {(victim / '.git').as_posix()}\n", encoding="utf-8")
        state.observed["identity_after_swap"] = _git(worktree, "rev-parse", "--absolute-git-dir").stdout.strip()

    state.script = hostile
    outcome = await _run_build(monkeypatch, worktree, state)
    build = outcome.build

    assert state.requests == [("write", _A, _APPROVED)], build.error
    assert _same_path(state.observed["identity_after_swap"], victim / ".git"), "premise: the swap moved the repository"
    assert not _same_path(pinned, victim / ".git"), "premise: the pin named a different repository"
    assert build.status == "failed"
    assert "identity" in build.error, build.error
    assert _snapshot(worktree) == before, "a worktree file changed"
    assert _refs(base) == base_refs, "a branch or commit appeared in the original repository"
    assert _refs(victim) == victim_refs, "a branch or commit appeared in the second repository"


@pytest.mark.parametrize(
    ("scenario", "status", "fragment"),
    [
        pytest.param("success", "reviewing", "", id="success"),
        pytest.param("adapter_failure", "failed", "no file changes", id="adapter_failure"),
        pytest.param("client_raises", "failed", "refused to start", id="client_raises"),
    ],
)
async def test_the_session_directory_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path, scenario: str, status: str, fragment: str,
) -> None:
    repo = _make_repo(tmp_path / "repo", _SEEDED)
    state = _Sdk()

    async def session(s: _FakeSession) -> None:
        if scenario == "success":
            s.write(_A, _A_V2)

    state.script = session
    if scenario == "client_raises":
        state.start_error = RuntimeError("fake SDK client refused to start")
    outcome = await _run_build(monkeypatch, repo, state)

    assert outcome.build.status == status, outcome.build.error
    assert fragment in outcome.build.error
    assert len(state.session_dirs) == 1
    assert state.observed["dir_at_start"] is True, "premise: the directory existed when the client started"
    assert not state.session_dirs[0].exists()
    assert list(sandbox.iterdir()) == []


async def test_the_session_directory_is_removed_on_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo", _SEEDED)
    state = _Sdk()
    entered, never = asyncio.Event(), asyncio.Event()

    async def session(s: _FakeSession) -> None:
        state.observed["dir_during_session"] = s.working_directory.is_dir()
        entered.set()
        await never.wait()  # the SDK is "still working" until the task is cancelled

    state.script = session
    dispatcher, build, _calls = _prepare(monkeypatch, repo, state)
    task = asyncio.create_task(dispatcher._execute_build(build))
    watcher = asyncio.create_task(entered.wait())
    try:
        done, _pending = await asyncio.wait({task, watcher}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
        assert watcher in done, f"premise: the session never started ({build.status}: {build.error})"
        assert state.observed["dir_during_session"] is True, "premise: the directory existed during the session"
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        for running in (task, watcher):
            if not running.done():
                running.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await running

    assert len(state.session_dirs) == 1
    assert not state.session_dirs[0].exists(), "cancellation left the session directory behind"
    assert list(sandbox.iterdir()) == []


@pytest.mark.parametrize("how", ["identity_is_none", "worktree_directory_is_missing"])
async def test_an_unpinnable_worktree_is_refused_before_the_adapter_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path, how: str,
) -> None:
    # Control, asserted first: a pinnable worktree gets a real adapter and a session directory
    # in this test's temp root, so an empty root below means none was made.
    control_repo = _make_repo(tmp_path / "control", _SEEDED)
    control_state = _Sdk()

    async def honest(s: _FakeSession) -> None:
        s.write(_A, _A_V2)

    control_state.script = honest
    control = await _run_build(monkeypatch, control_repo, control_state)
    assert control.build.status == "reviewing", control.build.error
    assert len(control.adapter_calls) == 1
    control_dir = control_state.session_dirs[0]
    assert control_dir.parent == sandbox and control_dir.name.startswith("probos_visiting_")
    assert not control_dir.exists() and list(sandbox.iterdir()) == []

    state = _Sdk()
    identity: AsyncMock | None = None
    if how == "identity_is_none":
        worktree = _make_repo(tmp_path / "repo", _SEEDED)
        identity = AsyncMock(return_value=None)
        monkeypatch.setattr(dispatcher_module, "repository_identity", identity)
    else:
        worktree = tmp_path / "no-such-worktree"
        assert not worktree.exists(), "premise"
    outcome = await _run_build(monkeypatch, worktree, state)

    assert outcome.build.status == "failed"
    assert "pin" in outcome.build.error, outcome.build.error
    assert outcome.adapter_calls == [], "the adapter class was called for an unpinnable worktree"
    assert state.client_options == [] and state.lifecycle == []
    assert list(sandbox.glob("probos_visiting_*")) == []
    if identity is not None:
        identity.assert_awaited_once_with(str(worktree))


# -- BF-896 (R1-1): the queued route through the REAL WorktreeManager --------------------
#
# The tests above stub the manager, which is how the defect survived: the executor commits on a branch
# of its own, while review (collect_diff) and approval (merge_to_main) read the branch the manager made.
# These tests use the real manager and the real executor over a real repository, and cross the whole
# chain: create -> generate -> reviewing -> collect_diff -> approve -> refused, the branch kept (BF-897; it used to land
# on main) (or reject -> clean repository).


@dataclass
class _Real:
    repo: Path
    manager: WorktreeManager
    dispatcher: BuildDispatcher
    build: QueuedBuild
    adoptions: list[tuple[str, str]]  # (build_id, branch) each time adopt_commit was awaited
    before_adoption: dict[str, Any]

    @property
    def branch(self) -> str:
        return f"builder-{self.build.id[:8]}"


def _prepare_real(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: _Sdk, spec: BuildSpec | None = None,
) -> _Real:
    repo = _make_repo(tmp_path / "repo", _SEEDED)
    assert _out(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main", "premise: the repository is on main"
    state.install(monkeypatch)
    _spy_on_adapter(monkeypatch)
    queue = BuildQueue()
    build = queue.enqueue(spec or _spec())
    queue.update_status(build.id, "dispatched")
    manager = WorktreeManager(repo_root=str(repo), worktree_base=str(tmp_path / "wts"))
    real_adopt = manager.adopt_commit
    adoptions: list[tuple[str, str]] = []
    before: dict[str, Any] = {}

    async def spy(build_id: str, branch: str) -> tuple[bool, str]:
        adoptions.append((build_id, branch))
        info = manager.get(build_id)
        assert info is not None
        before["executor_ahead"] = _out(repo, "rev-list", "--count", f"main..{branch}")
        before["manager_branch_ahead"] = _out(repo, "rev-list", "--count", f"main..{info.branch}")
        before["collect_diff"] = await manager.collect_diff(build_id)
        before["executor_branch"] = branch
        before["executor_sha"] = _out(repo, "rev-parse", f"refs/heads/{branch}")
        return await real_adopt(build_id, branch)

    monkeypatch.setattr(manager, "adopt_commit", spy)
    dispatcher = BuildDispatcher(queue=queue, worktree_mgr=manager, run_tests=False)
    return _Real(repo, manager, dispatcher, build, adoptions, before)


async def _change_a(s: _FakeSession) -> None:
    s.write(_A, _A_V2)


def _branches(repo: Path) -> list[str]:
    return _out(repo, "branch", "--format=%(refname:short)").splitlines()


def _worktree_entries(repo: Path) -> int:
    return sum(1 for line in _out(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree "))


async def test_an_approved_queued_build_is_refused_and_keeps_its_branch_for_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # BF-897 (#1559): this repository stands for the operator's checkout; approval used to merge here.
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    repo, build = real.repo, real.build
    main_before = _out(repo, "rev-parse", "main")

    await real.dispatcher._execute_build(build)

    # Premises, observed just before adoption: the executor's branch holds the commit and the manager's
    # branch does not, so review would have been empty and approval a no-op without the adoption.
    assert build.status == "reviewing", build.error
    assert len(real.adoptions) == 1
    assert real.before_adoption["executor_branch"] != real.branch
    assert real.before_adoption["executor_ahead"] == "1"
    assert real.before_adoption["manager_branch_ahead"] == "0"
    assert real.before_adoption["collect_diff"] == ""

    # After: the manager's branch carries the commit, review shows it, the executor's branch is gone.
    result = build.result
    assert result is not None and result.success, build.error
    assert result.branch_name == real.branch
    assert real.before_adoption["executor_sha"].startswith(result.commit_hash)  # the executor reports a short sha
    assert _out(repo, "rev-parse", real.branch) == real.before_adoption["executor_sha"]
    assert _out(repo, "rev-list", "--count", f"main..{real.branch}") == "1"
    assert real.before_adoption["executor_branch"] not in _branches(repo)
    diff = await real.manager.collect_diff(build.id)
    assert _A in diff and "return 2" in diff
    assert _out(repo, "rev-parse", "main") == main_before, "nothing reaches main before approval"

    # The operator's checkout holds an edit of its own, to a file the build never touched, when the build is approved. An
    # old-style merge succeeds beside such an edit, so the tuple below is what the refusal must leave alone.
    operator_edit = (_B_V1 + "# an edit the operator has not committed\n").encode("utf-8")
    (repo / _B).write_bytes(operator_edit)

    def operator_checkout() -> tuple[str, str, str, bytes]:
        return (
            _out(repo, "rev-parse", "main"),
            _out(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            _out(repo, "status", "--porcelain"),
            (repo / _B).read_bytes(),
        )

    before = operator_checkout()
    assert before[1] == "main" and _B in before[2] and before[3] == operator_edit, "premise: an uncommitted edit on main"

    approved, detail = await real.dispatcher.approve_and_merge(build.id)

    assert approved is False, detail
    assert "BF-897" in detail
    assert build.status == "reviewing"
    assert operator_checkout() == before
    assert _show(repo, "main", _A) == _A_V1
    # The branch is kept for delivery: it still holds the generated commit, one ahead of main, with its worktree.
    assert _out(repo, "rev-parse", real.branch) == real.before_adoption["executor_sha"]
    assert _out(repo, "rev-list", "--count", f"main..{real.branch}") == "1"
    assert _worktree_entries(repo) == 2

    # The refused build stays in review, so it can still be rejected (the operator's edit is put back first).
    (repo / _B).write_bytes(_B_V1.encode("utf-8"))
    assert _out(repo, "status", "--porcelain") == "", "premise: the operator's checkout is clean again"
    assert await real.dispatcher.reject_build(build.id) is True
    assert _branches(repo) == ["main"] and _worktree_entries(repo) == 1


async def test_a_rejected_queued_build_leaves_only_main_and_one_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    repo, build = real.repo, real.build
    main_before = _out(repo, "rev-parse", "main")

    await real.dispatcher._execute_build(build)
    assert build.status == "reviewing", build.error
    assert _worktree_entries(repo) == 2, "premise: the build's worktree exists"
    assert sorted(_branches(repo)) == sorted(["main", real.branch])

    assert await real.dispatcher.reject_build(build.id) is True

    assert build.status == "failed" and build.error == "rejected by Captain"
    assert _branches(repo) == ["main"], "a branch of the build survived the rejection"
    assert _worktree_entries(repo) == 1
    assert _out(repo, "rev-parse", "main") == main_before
    assert _show(repo, "main", _A) == _A_V1


async def test_a_commit_that_cannot_be_adopted_fails_the_build_and_stays_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    repo = real.repo
    real_adopt = real.manager.adopt_commit

    async def diverge_then_adopt(build_id: str, branch: str) -> tuple[bool, str]:
        # Something moved the manager's branch since the build began: it is no longer an ancestor of the commit.
        info = real.manager.get(build_id)
        assert info is not None
        tree = _out(repo, "rev-parse", "main^{tree}")
        other = _out(repo, "commit-tree", tree, "-p", "main", "-m", "moved")
        _out(repo, "update-ref", f"refs/heads/{info.branch}", other)
        assert _out(repo, "rev-list", "--count", f"{info.branch}..{branch}") == "1", "premise: diverged"
        return await real_adopt(build_id, branch)

    monkeypatch.setattr(real.manager, "adopt_commit", diverge_then_adopt)
    await real.dispatcher._execute_build(real.build)
    build = real.build

    assert build.status == "failed"
    assert len(real.adoptions) == 1
    executor_branch = build.result.branch_name
    assert executor_branch and executor_branch != real.branch
    assert f"commit {build.result.commit_hash} left on {executor_branch}" in build.error, build.error
    assert "merge --ff-only" in build.error
    # The commit is still there: nothing was deleted when the adoption was refused.
    assert _out(repo, "rev-parse", f"refs/heads/{executor_branch}").startswith(build.result.commit_hash)
    assert _show(repo, "main", _A) == _A_V1


async def test_a_successful_result_with_no_commit_fails_the_build_without_adopting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    real_execute = dispatcher_module.execute_approved_build

    async def execute_then_drop_the_commit(*args: Any, **kwargs: Any) -> Any:
        result = await real_execute(*args, **kwargs)
        assert result.success and result.commit_hash, "premise: the real executor committed"
        result.commit_hash = ""  # what a success that changed nothing looks like
        return result

    monkeypatch.setattr(dispatcher_module, "execute_approved_build", execute_then_drop_the_commit)
    await real.dispatcher._execute_build(real.build)

    assert real.build.status == "failed"
    assert real.build.error == "no change reached the worktree"
    assert real.adoptions == []
    assert _out(real.repo, "rev-list", "--count", f"main..{real.branch}") == "0"


async def test_an_identity_change_after_the_executor_returns_is_refused_before_adoption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    victim = _make_repo(tmp_path / "victim", {"README.md": "victim\n"}, branch="trunk")
    victim_refs = _refs(victim)
    real_execute = dispatcher_module.execute_approved_build
    swapped: dict[str, Any] = {}

    async def execute_then_swap(*args: Any, **kwargs: Any) -> Any:
        result = await real_execute(*args, **kwargs)
        assert result.success and result.commit_hash, "premise: the real executor committed"
        pointer = Path(kwargs["work_dir"]) / ".git"
        assert pointer.is_file(), "premise: a linked worktree's .git is a pointer file"
        if sys.platform == "win32":
            subprocess.run(["attrib", "-h", str(pointer)], check=True, capture_output=True)
        pointer.write_text(f"gitdir: {(victim / '.git').as_posix()}\n", encoding="utf-8")
        swapped["after"] = _git(Path(kwargs["work_dir"]), "rev-parse", "--absolute-git-dir").stdout.strip()
        return result

    monkeypatch.setattr(dispatcher_module, "execute_approved_build", execute_then_swap)
    await real.dispatcher._execute_build(real.build)

    assert _same_path(swapped["after"], victim / ".git"), "premise: the swap moved the repository"
    assert real.build.status == "failed"
    assert "identity" in real.build.error, real.build.error
    assert real.adoptions == [], "adoption ran in a tree that no longer names the pinned repository"
    assert _refs(victim) == victim_refs, "a branch or commit appeared in the second repository"
    assert _out(real.repo, "rev-list", "--count", f"main..{real.branch}") == "0", "the commit was adopted"
    assert _show(real.repo, "main", _A) == _A_V1


# -- BF-896 (R2-2): an adoption that RAISES is an adoption failure, not a lost build ------------------------


def _watch_completion(real: _Real) -> list[QueuedBuild]:
    """Record what the on_build_complete callback receives (the dispatcher keeps the hook privately)."""
    received: list[QueuedBuild] = []

    async def on_complete(build: QueuedBuild) -> None:
        received.append(build)

    real.dispatcher._on_build_complete = on_complete
    return received


async def test_adoption_that_succeeds_reaches_review_with_its_result_and_the_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    # Positive control for the raising-adoption tests below: same build, adoption not sabotaged.
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)

    await real.dispatcher._execute_build(real.build)

    assert real.build.status == "reviewing", real.build.error
    assert real.build.result is not None and real.build.result.commit_hash
    assert received == [real.build] and received[0].result is real.build.result
    assert len(state.session_dirs) == 1 and not state.session_dirs[0].exists()


async def test_an_adoption_that_raises_fails_the_build_keeping_its_result_and_recovery_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    seen: dict[str, str] = {}

    async def explode(build_id: str, branch: str) -> tuple[bool, str]:
        seen["branch"] = branch
        seen["sha"] = _out(real.repo, "rev-parse", f"refs/heads/{branch}")
        raise OSError("cannot launch git")

    monkeypatch.setattr(real.manager, "adopt_commit", explode)

    await real.dispatcher._execute_build(real.build)

    build = real.build
    assert seen.get("branch"), "premise: the executor committed and adoption was reached"
    assert build.status == "failed"
    assert build.result is not None, "the build result was lost"
    assert build.result.commit_hash and seen["sha"].startswith(build.result.commit_hash)
    assert build.result.branch_name == seen["branch"], "the recovery branch was lost"
    assert build.error == (
        f"commit {build.result.commit_hash} left on {seen['branch']}: OSError: cannot launch git"
    ), build.error
    # The commit is recoverable and nothing was adopted.
    assert _out(real.repo, "rev-parse", f"refs/heads/{seen['branch']}") == seen["sha"]
    assert _out(real.repo, "rev-list", "--count", f"main..{real.branch}") == "0"
    # The failure handling is the ordinary one: directory gone, callback saw the result.
    assert len(state.session_dirs) == 1 and not state.session_dirs[0].exists()
    assert list(sandbox.iterdir()) == []
    assert len(received) == 1 and received[0] is build and received[0].result is build.result


async def test_a_cancellation_raised_from_adoption_still_propagates_and_removes_the_session_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    reached: list[str] = []

    async def cancelled(build_id: str, branch: str) -> tuple[bool, str]:
        reached.append(branch)
        raise asyncio.CancelledError

    monkeypatch.setattr(real.manager, "adopt_commit", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await real.dispatcher._execute_build(real.build)

    assert len(reached) == 1, "premise: adoption was reached"
    assert real.build.status != "failed" or "CancelledError" not in (real.build.error or "")
    assert len(state.session_dirs) == 1 and not state.session_dirs[0].exists()
    assert list(sandbox.iterdir()) == []
    assert _out(real.repo, "rev-parse", f"refs/heads/{reached[0]}"), "the commit stays on the executor branch"


# -- BF-896 (R3-1, R3-2): a completed executor result survives every exit after the executor returned -------
#
# execute_approved_build returns a committed result, then the dispatcher still awaits the identity re-check
# and adoption. A stop() (or an error) in either used to leave status "building", result None and a callback
# with commit_hash "" although the commit exists. These tests hold the real build at those two awaits (REAL
# manager, REAL executor, real git) and exit it there.


@dataclass
class _Hook:
    reached: asyncio.Event
    never: asyncio.Event
    calls: list[Any]
    executed: list[Any]  # the executor's result, as it was when the executor returned
    executor_branches: list[str]


def _arm(monkeypatch: pytest.MonkeyPatch, real: _Real, seam: str, fault: str | None) -> _Hook:
    """Instrument one await after the executor returned.

    seam: "identity" (the re-check), "adoption" (before the real adoption runs) or "adoption_done" (after
    the real adoption ran, inside the same await). fault: None (observe only), "hold" (never return; wait
    to be cancelled) or "raise" (identity only: the re-check raises RuntimeError).
    """
    hook = _Hook(asyncio.Event(), asyncio.Event(), [], [], [])
    real_execute = dispatcher_module.execute_approved_build

    async def execute(*args: Any, **kwargs: Any) -> Any:
        result = await real_execute(*args, **kwargs)
        assert result.success and result.commit_hash, "premise: the real executor committed"
        hook.executed.append(result)
        hook.executor_branches.append(result.branch_name)
        return result

    monkeypatch.setattr(dispatcher_module, "execute_approved_build", execute)
    if seam == "identity":
        real_identity = dispatcher_module.repository_identity

        async def identity(path: str) -> str | None:
            hook.calls.append(path)
            if len(hook.calls) == 2:  # the first call is the pin; the second is the re-check
                hook.reached.set()
                if fault == "hold":
                    await hook.never.wait()
                if fault == "raise":
                    raise RuntimeError("identity probe unavailable")
            return await real_identity(path)

        monkeypatch.setattr(dispatcher_module, "repository_identity", identity)
    else:
        inner = real.manager.adopt_commit

        async def adopt(build_id: str, branch: str) -> tuple[bool, str]:
            hook.calls.append(branch)
            if seam == "adoption":
                hook.reached.set()
                if fault == "hold":
                    await hook.never.wait()
            outcome = await inner(build_id, branch)
            if seam == "adoption_done":
                hook.reached.set()
                if fault == "hold":
                    await hook.never.wait()
            return outcome

        monkeypatch.setattr(real.manager, "adopt_commit", adopt)
    return hook


async def _exit_while_held(real: _Real, hook: _Hook, via: str) -> asyncio.Task[None]:
    """Run the build until it is held at the armed await, then exit it by stop() or task.cancel()."""
    dispatcher, build = real.dispatcher, real.build
    task = asyncio.create_task(dispatcher._execute_build(build))
    dispatcher._active_tasks[build.id] = task
    watcher = asyncio.create_task(hook.reached.wait())
    try:
        done, _pending = await asyncio.wait({task, watcher}, timeout=60, return_when=asyncio.FIRST_COMPLETED)
        assert watcher in done, f"premise: the armed await was never reached ({build.status}: {build.error})"
        assert not task.done(), "premise: the build is still held at that await"
        if via == "stop":
            await dispatcher.stop()
        else:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert task.cancelled(), "the cancellation was swallowed: the task finished instead of being cancelled"
    finally:
        for running in (task, watcher):
            if not running.done():
                running.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await running
    return task


def _assert_commit_is_kept(real: _Real, hook: _Hook, received: list[QueuedBuild], sandbox: Path, state: _Sdk) -> str:
    """The result is attached, the callback saw it, the session directory is gone, the commit is still on a branch."""
    build = real.build
    assert len(hook.executed) == 1, "premise: the executor ran exactly once"
    assert build.status == "failed", (build.status, build.error)
    assert build.result is hook.executed[0], "the completed executor result was lost"
    sha = build.result.commit_hash
    assert sha
    assert len(received) == 1 and received[0] is build, "the callback did not receive the build"
    assert received[0].status == "failed" and received[0].result is not None
    assert received[0].result.commit_hash == sha, "the callback saw no commit hash"
    assert len(state.session_dirs) == 1 and not state.session_dirs[0].exists()
    assert list(sandbox.iterdir()) == []
    return sha


@pytest.mark.parametrize("seam", ["identity", "adoption"])
async def test_a_build_with_no_fault_at_the_seams_still_reaches_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path, seam: str,
) -> None:
    # Positive control for the exits below: the same instrumentation, nothing held or raised.
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    hook = _arm(monkeypatch, real, seam, None)

    await real.dispatcher._execute_build(real.build)

    assert hook.reached.is_set(), "premise: the armed await ran"
    assert len(hook.executed) == 1
    assert real.build.status == "reviewing", real.build.error
    assert real.build.result is not None and real.build.result.branch_name == real.branch
    assert len(received) == 1 and received[0].status == "reviewing"
    assert _out(real.repo, "rev-list", "--count", f"main..{real.branch}") == "1"


@pytest.mark.parametrize("via", ["stop", "cancel"])
@pytest.mark.parametrize("seam", ["identity", "adoption", "adoption_done"])
async def test_an_exit_after_the_executor_returned_keeps_the_result_and_names_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path, seam: str, via: str,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    hook = _arm(monkeypatch, real, seam, "hold")

    await _exit_while_held(real, hook, via)

    sha = _assert_commit_is_kept(real, hook, received, sandbox, state)
    executor_branch = hook.executor_branches[0]
    assert executor_branch != real.branch, "premise: the executor committed on a branch of its own"
    assert real.build.error == f"cancelled after commit {sha}; on {executor_branch} or {real.branch}", real.build.error
    assert real.build.completed_at, "the failed record has no completion time"
    # The commit is on a branch the error names: the executor's (adoption not done) or the worktree's (done).
    if seam == "adoption_done":
        assert _out(real.repo, "rev-parse", f"refs/heads/{real.branch}").startswith(sha)
        assert executor_branch not in _branches(real.repo)
    else:
        assert _out(real.repo, "rev-parse", f"refs/heads/{executor_branch}").startswith(sha)
        assert _out(real.repo, "rev-list", "--count", f"main..{real.branch}") == "0"


@pytest.mark.parametrize("via", ["stop", "cancel"])
async def test_a_failing_outcome_record_never_replaces_the_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path, via: str,
) -> None:
    # BF-896 (R4-1): the cancel handler records the outcome best effort. If that recording raises, what the
    # task and stop() see must still be the cancellation, never the recording error.
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    hook = _arm(monkeypatch, real, "identity", "hold")
    queue = real.dispatcher._queue
    real_update = queue.update_status
    attempts: list[str] = []

    def update_status(build_id: str, status: str, **kwargs: Any) -> bool:
        if status == "failed":
            attempts.append(status)
            raise RuntimeError("queue unavailable")
        return real_update(build_id, status, **kwargs)  # the control: every other transition still records

    monkeypatch.setattr(queue, "update_status", update_status)

    await _exit_while_held(real, hook, via)  # asserts task.cancelled(): the RuntimeError did not replace it

    assert attempts == ["failed"], "premise: the cancel handler tried to record the outcome and the record raised"
    assert real.build.status == "building", "premise: the failed record never landed"
    assert len(state.session_dirs) == 1 and not state.session_dirs[0].exists(), "the finally block still ran"
    assert len(received) == 1 and received[0] is real.build, "the callback still fired"


@pytest.mark.parametrize("via", ["stop", "cancel"])
async def test_a_cancellation_before_the_executor_returns_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path, via: str,
) -> None:
    # Positive control is test_a_build_with_no_fault_at_the_seams_still_reaches_review: the same build
    # completes. Here the session never returns, so there is no executor result to keep and none is made up.
    state = _Sdk()
    entered, never = asyncio.Event(), asyncio.Event()

    async def session(s: _FakeSession) -> None:
        entered.set()
        await never.wait()

    state.script = session
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    executed: list[Any] = []
    real_execute = dispatcher_module.execute_approved_build

    async def execute(*args: Any, **kwargs: Any) -> Any:
        executed.append(1)
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(dispatcher_module, "execute_approved_build", execute)
    hook = _Hook(entered, never, [], [], [])

    await _exit_while_held(real, hook, via)

    assert executed == [], "premise: the executor was never reached"
    assert real.build.status == "building", "a failure was recorded for a build that never produced a result"
    assert real.build.result is None and real.build.error == "" and not real.build.completed_at
    assert len(received) == 1 and received[0] is real.build and received[0].status == "building"
    assert len(state.session_dirs) == 1 and not state.session_dirs[0].exists()
    assert list(sandbox.iterdir()) == []
    assert sorted(_branches(real.repo)) == sorted(["main", real.branch])


async def test_an_unexpected_error_after_the_executor_returned_keeps_the_result_and_names_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    hook = _arm(monkeypatch, real, "identity", "raise")

    await real.dispatcher._execute_build(real.build)

    assert hook.reached.is_set() and len(hook.calls) == 2, "premise: the re-check raised"
    sha = _assert_commit_is_kept(real, hook, received, sandbox, state)
    executor_branch = hook.executor_branches[0]
    assert real.build.error == f"identity probe unavailable; commit {sha} on {executor_branch} or {real.branch}"
    assert _out(real.repo, "rev-parse", f"refs/heads/{executor_branch}").startswith(sha)
    assert real.adoptions == [], "premise: adoption was not reached"


async def test_an_unexpected_error_before_the_executor_returned_records_no_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    # The error text is unchanged when there is no executor result to name.
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)

    async def refuse(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(dispatcher_module, "execute_approved_build", refuse)
    await real.dispatcher._execute_build(real.build)

    assert real.build.status == "failed"
    assert real.build.error == "executor unavailable"
    assert real.build.result is None


async def test_a_branch_delete_that_raises_after_the_commit_moved_still_reaches_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: Path,
) -> None:
    # R3-2: the delete of the executor branch raises. The commit is already on the worktree's branch, so the
    # build is reviewing, the stored branch is that branch, and nothing names the executor branch as a home.
    # (The control, an honest delete, is test_adoption_that_succeeds_reaches_review_with_its_result_and_the_callback.)
    state = _Sdk()
    state.script = _change_a
    real = _prepare_real(monkeypatch, tmp_path, state)
    received = _watch_completion(real)
    real_git = real.manager._run_git
    deletes: list[tuple[str, ...]] = []

    async def run_git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[:2] == ("branch", "-D"):
            deletes.append(args)
            raise OSError("git output unavailable after the delete")
        return await real_git(*args, cwd=cwd)

    monkeypatch.setattr(real.manager, "_run_git", run_git)

    await real.dispatcher._execute_build(real.build)

    build = real.build
    assert len(deletes) == 1, "premise: the delete step was reached and raised"
    assert build.status == "reviewing", build.error
    assert build.result is not None and build.result.branch_name == real.branch
    assert build.error == ""
    assert _out(real.repo, "rev-parse", f"refs/heads/{real.branch}").startswith(build.result.commit_hash)
    assert len(received) == 1 and received[0].status == "reviewing"
