"""BF-904b (#1585), milestone M3: a build in review holds its files (item 6), and the visiting builder works from
whole files with project-relative change paths (item 7).

Before M3 ``BuildQueue.has_footprint_conflict`` counted only ``dispatched`` and ``building``, so a second build on
the same files was dispatched while the first waited in review. ``BuilderAgent.perceive`` seeded the visiting
session with the localization excerpts and handed them to the adapter, whose scan takes each whole-file change's
``base`` from that mapping, so ``execute_approved_build`` refused every such change to a localized target; and
``act`` returned ``transporter_complete`` changes without ``_normalize_change_paths``.

Rules: the real ``BuildQueue`` and ``BuildDispatcher``; the real ``BuilderAgent`` (``perceive``, ``decide``,
``act``) with ``_PROJECT_ROOT`` and ``_SOURCE_ROOT`` pointed at a source tree under ``tmp_path``; the real
``seed_session_directory`` and ``execute_approved_build`` on real git. The adapter is a stand-in (no SDK here) whose
change is built the way its disk scan builds one. No sleeps; every await and subprocess is bounded.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Awaitable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.build_dispatcher import BuildDispatcher
from probos.build_queue import BuildQueue
from probos.cognitive import builder as builder_module
from probos.cognitive import copilot_adapter as adapter_module
from probos.cognitive.builder import BuilderAgent, BuildSpec, execute_approved_build
from probos.runtime import ProbOSRuntime
from probos.worktree_manager import WorktreeManager

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

BIG = "src/probos/big.py"
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


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


def _blob(repo: Path, ref: str, path: str) -> str:
    shown = _git(repo, "show", f"{ref}:{path}")
    assert shown.returncode == 0, f"{ref}:{path} must exist in the repository ({shown.stderr.strip()})"
    return shown.stdout.replace("\r\n", "\n")


def _spec(title: str, files: list[str] | tuple[str, ...] = ()) -> BuildSpec:
    return BuildSpec(title=title, description="d", target_files=list(files))


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    return await asyncio.wait_for(awaited, timeout=seconds)


def _big_text() -> str:
    return "".join(f"value_{i:04d} = {i}  # padding that makes this file large enough to be localized\n" for i in range(800))


class _Generated:
    def __init__(self, blocks: list[dict[str, Any]]) -> None:
        self.success = True
        self.file_blocks = blocks
        self.raw_output = "visiting"
        self.error = None


class _VisitingProbe:
    """Stands in for ``CopilotBuilderAdapter``. It records the mapping ``execute`` receives and what the session
    directory holds then, and answers with one whole-file change built as the adapter's disk scan builds one
    (``content`` the new text, ``base`` the text it was given for that path)."""

    last: Any = None

    def __init__(self, *, cwd: str = "", **_kw: Any) -> None:
        self.cwd = cwd
        self.files: dict[str, str] | None = None
        self.seeded: dict[str, bytes] | None = None
        type(self).last = self

    async def start(self) -> None:
        return None

    async def execute(self, _spec: Any, files: dict[str, str]) -> _Generated:
        self.files = dict(files)
        root = Path(self.cwd)
        self.seeded = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        given = files.get(BIG, "")
        return _Generated([{"path": BIG, "mode": "modify", "content": given + "extra = 1\n", "base": given}])

    async def stop(self) -> None:
        return None


def _source_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "source"
    (source / "src" / "probos").mkdir(parents=True)
    (source / BIG).write_bytes(_big_text().encode("utf-8"))
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", source)
    monkeypatch.setattr(builder_module, "_SOURCE_ROOT", source / "src" / "probos")
    _VisitingProbe.last = None
    monkeypatch.setattr(adapter_module, "CopilotBuilderAdapter", lambda **kw: _VisitingProbe(**kw))
    return source


def _agent() -> Any:
    return BuilderAgent(agent_id="builder-bf904b", llm_client=MagicMock(), runtime=MagicMock(spec=ProbOSRuntime))


async def _perceive_visiting(agent: Any) -> dict:
    return await _bounded(agent.perceive({
        "intent": "build_code",
        "params": {"title": "t", "description": "d", "target_files": [BIG], "force_visiting": True},
    }))


# D1
async def test_a_build_in_review_holds_its_files() -> None:
    queue = BuildQueue()
    first = queue.enqueue(_spec("first", ["src/probos/a.py"]))
    for status in ("dispatched", "building", "reviewing"):
        assert queue.update_status(first.id, status), f"premise: {status}"
    second = queue.enqueue(_spec("second", ["src/probos/a.py", "src/probos/b.py"]), priority=1)
    third = queue.enqueue(_spec("third", ["src/probos/c.py"]), priority=5)
    worktrees = MagicMock(spec=WorktreeManager)
    worktrees.remove = AsyncMock()
    dispatcher = BuildDispatcher(queue=queue, worktree_mgr=worktrees)
    assert queue.has_footprint_conflict(second.file_footprint) is True
    picked = dispatcher._find_dispatchable()
    assert picked is not None and picked.id == third.id, "the overlapping build waits; a disjoint one goes"
    assert await dispatcher.reject_build(first.id) is True
    assert queue.has_footprint_conflict(second.file_footprint) is False
    picked = dispatcher._find_dispatchable()
    assert picked is not None and picked.id == second.id, "rejecting the reviewed build releases its files"


# D2
@pytest.mark.parametrize(
    ("statuses", "holds"),
    [
        ((), False),
        (("dispatched",), True),
        (("dispatched", "building"), True),
        (("dispatched", "building", "reviewing"), True),
        (("dispatched", "building", "reviewing", "merged"), False),
        (("dispatched", "building", "failed"), False),
    ],
    ids=["queued", "dispatched", "building", "reviewing", "merged", "failed"],
)
def test_which_statuses_hold_a_builds_files(statuses: tuple[str, ...], holds: bool) -> None:
    queue = BuildQueue()
    build = queue.enqueue(_spec("held", ["src/probos/a.py"]))
    for status in statuses:
        assert queue.update_status(build.id, status), f"premise: {status}"
    assert queue.has_footprint_conflict(["src/probos/a.py"]) is holds


# V1
async def test_the_visiting_builder_is_seeded_with_whole_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _source_tree(tmp_path, monkeypatch)
    original = _big_text()
    assert len(original) > BuilderAgent._LOCALIZE_THRESHOLD, "premise: perceive localizes this target"
    obs = await _perceive_visiting(_agent())
    probe = _VisitingProbe.last
    assert probe is not None and probe.files is not None and probe.seeded is not None, "premise: the visiting route ran"
    assert "omitted" in obs["target_context"], "control: the native prompt context is still the excerpt"
    assert probe.files[BIG] == original, "the visiting builder is handed the whole file"
    assert probe.seeded[BIG].decode("utf-8").replace("\r\n", "\n") == original, "and the session directory holds it"


# V2
@needs_git
async def test_a_whole_file_change_from_the_visiting_builder_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _source_tree(tmp_path, monkeypatch)
    original = _big_text()
    repo = _init_repo(tmp_path / "repo", {BIG: original})
    agent = _agent()
    obs = await _perceive_visiting(agent)
    decision = await _bounded(agent.decide(obs))
    assert decision.get("action") == "transporter_complete", "premise: the visiting route answered"
    acted = await _bounded(agent.act(decision))
    changes = acted["result"]["file_changes"]
    assert [change["path"] for change in changes] == [BIG], changes
    result = await _bounded(execute_approved_build(changes, _spec("bf904b visiting", [BIG]), str(repo), run_tests=False))
    assert result.success and result.commit_hash, result.error
    assert _blob(repo, result.branch_name, BIG) == original + "extra = 1\n"


# V3
@needs_git
@pytest.mark.parametrize("source", ["transporter", "visiting"])
async def test_transporter_changes_get_project_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str,
) -> None:
    tree = tmp_path / "source"
    (tree / "src" / "probos" / "pkg").mkdir(parents=True)
    (tree / "src" / "probos" / "pkg" / "mod.py").write_bytes(b"v = 1\n")
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", tree)
    monkeypatch.setattr(builder_module, "_SOURCE_ROOT", tree / "src" / "probos")
    decision: dict[str, Any] = {
        "action": "transporter_complete",
        "file_changes": [_modify("pkg/mod.py", "v = 1", "v = 2")],
        "llm_output": "bf904b",
    }
    if source == "visiting":
        decision["builder_source"] = "visiting"
    acted = await _bounded(_agent().act(decision))
    changes = acted["result"]["file_changes"]
    assert [change["path"] for change in changes] == ["src/probos/pkg/mod.py"], changes
    repo = _init_repo(tmp_path / "repo", {"src/probos/pkg/mod.py": "v = 1\n"})
    result = await _bounded(execute_approved_build(changes, _spec("bf904b paths"), str(repo), run_tests=False))
    assert result.success and result.commit_hash, result.error
    assert _blob(repo, result.branch_name, "src/probos/pkg/mod.py") == "v = 2\n"
