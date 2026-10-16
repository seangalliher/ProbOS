"""Tests for WorktreeManager (AD-371)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from probos.worktree_manager import WorktreeManager, WorktreeInfo


@pytest.fixture
def git_repo(tmp_path: Path) -> str:
    """Create a minimal git repo for testing."""
    if shutil.which("git") is None:
        pytest.skip("git not available on PATH")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), check=True, capture_output=True,
    )
    # Rename branch to main (in case default is master)
    subprocess.run(
        ["git", "checkout", "-b", "main"],
        cwd=str(repo), capture_output=True,
    )
    # Initial commit so we have a HEAD
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "initial"],
        cwd=str(repo), check=True, capture_output=True,
    )
    return str(repo)


class TestWorktreeManager:
    @pytest.mark.asyncio
    async def test_create_worktree(self, git_repo: str) -> None:
        """Create creates a worktree directory and branch."""
        wm = WorktreeManager(git_repo)
        info = await wm.create("abcdef123456")
        assert isinstance(info, WorktreeInfo)
        assert info.build_id == "abcdef123456"
        assert info.branch == "builder-abcdef12"
        assert Path(info.path).exists()
        assert info.created_at > 0

    @pytest.mark.asyncio
    async def test_remove_worktree(self, git_repo: str) -> None:
        """Remove deletes worktree directory and branch."""
        wm = WorktreeManager(git_repo)
        await wm.create("remove_test_1")
        ok = await wm.remove("remove_test_1")
        assert ok is True
        assert wm.get("remove_test_1") is None

    @pytest.mark.asyncio
    async def test_get_worktree(self, git_repo: str) -> None:
        """Get returns WorktreeInfo for known build_id."""
        wm = WorktreeManager(git_repo)
        created = await wm.create("get_test_123")
        fetched = wm.get("get_test_123")
        assert fetched is not None
        assert fetched.path == created.path

    @pytest.mark.asyncio
    async def test_get_unknown_returns_none(self, git_repo: str) -> None:
        """Get returns None for unknown build_id."""
        wm = WorktreeManager(git_repo)
        assert wm.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_collect_diff(self, git_repo: str) -> None:
        """collect_diff returns diff output for worktree changes."""
        wm = WorktreeManager(git_repo)
        info = await wm.create("diff_test_123")
        # Write a file inside the worktree and commit
        wt_path = Path(info.path)
        (wt_path / "new_file.py").write_text("print('hello')\n")
        subprocess.run(
            ["git", "add", "new_file.py"],
            cwd=info.path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add file"],
            cwd=info.path, check=True, capture_output=True,
        )
        diff = await wm.collect_diff("diff_test_123")
        assert "new_file.py" in diff
        assert "hello" in diff

    @pytest.mark.asyncio
    async def test_cleanup_all(self, git_repo: str) -> None:
        """cleanup_all removes all worktrees."""
        wm = WorktreeManager(git_repo)
        await wm.create("clean_aa0001")
        await wm.create("clean_bb0002")
        assert len(wm.get_all()) == 2
        removed = await wm.cleanup_all()
        assert removed == 2
        assert len(wm.get_all()) == 0


def _git(cwd: str, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, f"premise: git {' '.join(args)} failed: {done.stderr}"
    return done.stdout.strip()


def _ahead(repo: str, base: str, branch: str) -> int:
    return int(_git(repo, "rev-list", "--count", f"{base}..{branch}"))


def _commit_on_new_branch(worktree: str, branch: str, name: str) -> str:
    """The executor's shape: a new branch off the worktree's HEAD with one commit; HEAD stays on it."""
    _git(worktree, "checkout", "-q", "-b", branch)
    (Path(worktree) / name).write_text("x = 1\n", encoding="utf-8")
    _git(worktree, "add", name)
    _git(worktree, "commit", "-q", "-m", f"add {name}")
    return _git(worktree, "rev-parse", "HEAD")


class TestAdoptCommit:
    """BF-896 (#1550 R1-1): the executor's commit is moved onto the branch the manager reviews and merges."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("head", ["executor_branch", "worktree_branch", "detached_at_main"])
    async def test_adopt_commit_moves_the_commit_onto_the_worktree_branch(
        self, git_repo: str, head: str,
    ) -> None:
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_ok_0001")
        sha = _commit_on_new_branch(info.path, "builder/executor", "feature.py")
        if head == "worktree_branch":
            _git(info.path, "checkout", "-q", info.branch)
        elif head == "detached_at_main":
            _git(info.path, "checkout", "-q", "--detach", "main")
        # Premises: the repository is on main, the commit is only on the executor's branch, and the
        # manager's own branch is not ahead, so collect_diff is empty and an approval would merge nothing.
        assert _git(git_repo, "branch", "--show-current") == "main"
        assert _ahead(git_repo, "main", "builder/executor") == 1
        assert _ahead(git_repo, "main", info.branch) == 0
        assert await wm.collect_diff("adopt_ok_0001") == ""

        ok, detail = await wm.adopt_commit("adopt_ok_0001", "builder/executor")

        assert (ok, detail) == (True, sha)
        assert _git(git_repo, "rev-parse", f"refs/heads/{info.branch}") == sha
        assert _git(git_repo, "branch", "--list", "builder/executor") == ""
        assert _git(info.path, "branch", "--show-current") == info.branch
        assert "feature.py" in await wm.collect_diff("adopt_ok_0001")
        assert _git(git_repo, "rev-parse", "main") != sha, "adoption must not touch main"

    @pytest.mark.asyncio
    async def test_adopt_commit_refuses_a_non_fast_forward_and_keeps_the_commit(self, git_repo: str) -> None:
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_div_0001")
        sha = _commit_on_new_branch(info.path, "builder/executor", "feature.py")
        _git(info.path, "checkout", "-q", info.branch)
        (Path(info.path) / "other.py").write_text("y = 1\n", encoding="utf-8")
        _git(info.path, "add", "other.py")
        _git(info.path, "commit", "-q", "-m", "diverge")
        tip = _git(info.path, "rev-parse", "HEAD")
        assert _ahead(git_repo, info.branch, "builder/executor") == 1, "premise: the branches have diverged"

        ok, detail = await wm.adopt_commit("adopt_div_0001", "builder/executor")

        assert ok is False
        assert detail.startswith("merge --ff-only builder/executor:")
        assert _git(git_repo, "rev-parse", f"refs/heads/{info.branch}") == tip
        assert _git(git_repo, "rev-parse", "refs/heads/builder/executor") == sha

    @pytest.mark.asyncio
    async def test_adopt_commit_unknown_build_id_is_refused(self, git_repo: str) -> None:
        wm = WorktreeManager(git_repo)
        assert await wm.adopt_commit("nope", "builder/executor") == (False, "unknown build_id")

    @pytest.mark.asyncio
    async def test_adopt_commit_missing_branch_is_refused_and_changes_nothing(self, git_repo: str) -> None:
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_gone_001")
        before = _git(git_repo, "rev-parse", f"refs/heads/{info.branch}")
        assert _git(git_repo, "branch", "--list", "builder/executor") == "", "premise: no such branch"

        ok, detail = await wm.adopt_commit("adopt_gone_001", "builder/executor")

        assert ok is False
        assert detail.startswith("rev-parse builder/executor:")
        assert _git(git_repo, "rev-parse", f"refs/heads/{info.branch}") == before
        assert _git(info.path, "branch", "--show-current") == info.branch

    @pytest.mark.asyncio
    async def test_adopt_commit_checkout_failure_is_refused_and_leaves_the_commit(self, git_repo: str) -> None:
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_co_0001")
        sha = _commit_on_new_branch(info.path, "builder/executor", "feature.py")
        main_before = _git(git_repo, "rev-parse", "main")
        # The worktree is on the executor's branch, so the manager's branch can be deleted: checkout of it fails.
        _git(git_repo, "branch", "-D", info.branch)
        assert _git(git_repo, "branch", "--list", info.branch) == "", "premise: the manager's branch is gone"
        assert _git(info.path, "branch", "--show-current") == "builder/executor"

        ok, detail = await wm.adopt_commit("adopt_co_0001", "builder/executor")

        assert ok is False
        assert detail.startswith(f"checkout {info.branch}:"), detail
        assert _git(git_repo, "rev-parse", "refs/heads/builder/executor") == sha, "the executor's branch lost its commit"
        assert _git(git_repo, "branch", "--list", info.branch) == "", "a branch was recreated by the refused adoption"
        assert _git(git_repo, "rev-parse", "main") == main_before

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tip_is_wrong", [False, True])
    async def test_adopt_commit_verifies_the_tip_before_deleting_the_executor_branch(
        self, git_repo: str, monkeypatch: pytest.MonkeyPatch, tip_is_wrong: bool,
    ) -> None:
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_vf_0001")
        sha = _commit_on_new_branch(info.path, "builder/executor", "feature.py")
        real_run_git = wm._run_git
        tip_queries: list[tuple[str, ...]] = []

        async def run_git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
            result = await real_run_git(*args, cwd=cwd)
            if args == ("rev-parse", f"refs/heads/{info.branch}"):
                tip_queries.append(args)
                if tip_is_wrong:
                    assert result[1] == sha, "premise: the merge really did move the branch to the commit"
                    return 0, "0" * 40, ""
            return result

        monkeypatch.setattr(wm, "_run_git", run_git)

        ok, detail = await wm.adopt_commit("adopt_vf_0001", "builder/executor")

        assert len(tip_queries) == 1, "premise: the tip verification step ran"
        executor_branches = _git(git_repo, "branch", "--list", "builder/executor")
        if not tip_is_wrong:  # positive control: the same wrapper, an honest tip
            assert (ok, detail) == (True, sha)
            assert executor_branches == ""
        else:
            assert ok is False
            assert detail.startswith(f"verify {info.branch}: expected {sha}, found {'0' * 40}"), detail
            assert executor_branches != "", "the executor's branch was deleted after a failed verification"
            assert _git(git_repo, "rev-parse", "refs/heads/builder/executor") == sha


    @pytest.mark.asyncio
    @pytest.mark.parametrize("delete", ["honest", "raises", "nonzero_exit"])
    async def test_adopt_commit_a_failing_executor_branch_delete_still_reports_the_adoption(
        self, git_repo: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, delete: str,
    ) -> None:
        # BF-896 (R3-2): once the commit is on info.branch and verified, a delete that RAISES must not turn the
        # adoption into an exception: the caller would then name an executor branch that may already be gone.
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_del_0001")
        sha = _commit_on_new_branch(info.path, "builder/executor", "feature.py")
        real_run_git = wm._run_git
        deletes: list[tuple[str, ...]] = []

        async def run_git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
            if args[:2] == ("branch", "-D"):
                deletes.append(args)
                if delete == "raises":
                    raise OSError("git output unavailable")
                if delete == "nonzero_exit":
                    return 1, "", "cannot delete"
            return await real_run_git(*args, cwd=cwd)

        monkeypatch.setattr(wm, "_run_git", run_git)
        with caplog.at_level("WARNING", logger="probos.worktree_manager"):
            ok, detail = await wm.adopt_commit("adopt_del_0001", "builder/executor")

        assert deletes == [("branch", "-D", "builder/executor")], "premise: the delete step ran exactly once"
        assert (ok, detail) == (True, sha)
        assert _git(git_repo, "rev-parse", f"refs/heads/{info.branch}") == sha
        warned = [r.getMessage() for r in caplog.records if "could not delete branch" in r.getMessage()]
        stray = _git(git_repo, "branch", "--list", "builder/executor")
        if delete == "honest":  # positive control: the same wrapper, an honest delete
            assert warned == [] and stray == ""
        else:
            assert len(warned) == 1 and "builder/executor" in warned[0], warned
            # R4-2: the delete may have completed before its output failed, so the message must not assert a leftover.
            assert "may remain" in warned[0] and "stray branch remains" not in warned[0], warned
            assert stray != "", "premise: the delete did not happen, so the stray branch remains"
            if delete == "raises":
                assert "OSError" in warned[0], warned

    @pytest.mark.asyncio
    async def test_adopt_commit_a_cancellation_during_the_delete_still_propagates(
        self, git_repo: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        wm = WorktreeManager(git_repo, worktree_base=str(Path(git_repo).parent / "wts"))
        info = await wm.create("adopt_cx_0001")
        sha = _commit_on_new_branch(info.path, "builder/executor", "feature.py")
        real_run_git = wm._run_git

        async def run_git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
            if args[:2] == ("branch", "-D"):
                raise asyncio.CancelledError
            return await real_run_git(*args, cwd=cwd)

        monkeypatch.setattr(wm, "_run_git", run_git)

        with pytest.raises(asyncio.CancelledError):
            await wm.adopt_commit("adopt_cx_0001", "builder/executor")

        assert _git(git_repo, "rev-parse", f"refs/heads/{info.branch}") == sha, "premise: adoption reached the delete"
