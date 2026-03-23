"""Tests for WorktreeManager (AD-371)."""

from __future__ import annotations

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
