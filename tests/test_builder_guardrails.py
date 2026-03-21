"""Tests for builder pipeline guardrails — AD-360."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from probos.cognitive.builder import (
    BuildSpec,
    _git_create_branch,
    _is_dirty_working_tree,
    _validate_file_path,
    execute_approved_build,
)


# ---------------------------------------------------------------------------
# TestValidateFilePath (tests 1-5)
# ---------------------------------------------------------------------------


class TestValidateFilePath:
    """Tests for _validate_file_path() guardrail."""

    def test_validate_file_path_allowed(self):
        """Valid paths return None (no error)."""
        assert _validate_file_path("src/probos/config.py") is None
        assert _validate_file_path("tests/test_foo.py") is None
        assert _validate_file_path("config/system.yaml") is None
        assert _validate_file_path("docs/guide.md") is None
        assert _validate_file_path("prompts/build.md") is None
        assert _validate_file_path("conftest.py") is None

    def test_validate_file_path_traversal_blocked(self):
        """Path traversal is blocked."""
        result = _validate_file_path("../../etc/passwd")
        assert result is not None
        assert "traversal" in result.lower()

        result = _validate_file_path("src/../../../evil.py")
        assert result is not None
        assert "traversal" in result.lower()

    def test_validate_file_path_forbidden(self):
        """Forbidden paths are blocked."""
        result = _validate_file_path(".git/config")
        assert result is not None
        assert "Forbidden" in result

        result = _validate_file_path(".env")
        assert result is not None
        assert "Forbidden" in result

        result = _validate_file_path("pyproject.toml")
        assert result is not None
        assert "Forbidden" in result

    def test_validate_file_path_outside_allowed(self):
        """Paths outside allowed prefixes are blocked."""
        result = _validate_file_path("probos/types.py")
        assert result is not None
        assert "outside allowed" in result.lower()

        result = _validate_file_path("random/file.py")
        assert result is not None

        result = _validate_file_path("node_modules/foo.js")
        assert result is not None

    def test_validate_file_path_absolute_blocked(self):
        """Absolute paths are blocked."""
        result = _validate_file_path("/etc/passwd")
        assert result is not None
        assert "Absolute" in result

        result = _validate_file_path("C:\\Windows\\system32\\cmd.exe")
        assert result is not None
        assert "Absolute" in result

    def test_validate_file_path_root_level_allowed(self):
        """Root-level files (no directory) are allowed."""
        assert _validate_file_path("conftest.py") is None
        assert _validate_file_path("test.py") is None
        assert _validate_file_path("setup.py") is None


# ---------------------------------------------------------------------------
# TestBranchLifecycle (tests 6-7)
# ---------------------------------------------------------------------------


class TestBranchLifecycle:
    """Tests for build branch lifecycle management."""

    @pytest.mark.asyncio
    async def test_stale_branch_cleanup(self, tmp_path):
        """Pre-existing branch with same name is auto-deleted."""
        work_dir = str(tmp_path)
        # Initialize a git repo
        proc = await asyncio.create_subprocess_exec(
            "git", "init", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Configure git user for commits
        for cmd in [
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test"],
        ]:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=work_dir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        # Create initial commit
        (tmp_path / "init.txt").write_text("init")
        proc = await asyncio.create_subprocess_exec(
            "git", "add", ".", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", "init", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Create a stale branch
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", "-b", "builder/test-stale", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        # Switch back to main/master
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", "-", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Now _git_create_branch should succeed despite the stale branch
        ok, name = await _git_create_branch("builder/test-stale", work_dir)
        assert ok is True
        assert name == "builder-test-stale"

    @pytest.mark.asyncio
    async def test_failed_build_deletes_branch(self, tmp_path):
        """Failed build cleans up its branch."""
        work_dir = str(tmp_path)
        # Initialize a git repo with initial commit on 'main' branch
        proc = await asyncio.create_subprocess_exec(
            "git", "init", "-b", "main", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        for cmd in [
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test"],
        ]:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=work_dir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        (tmp_path / "init.txt").write_text("init")
        proc = await asyncio.create_subprocess_exec(
            "git", "add", ".", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", "init", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Create src/probos/ so the file path is valid
        (tmp_path / "src" / "probos").mkdir(parents=True, exist_ok=True)

        spec = BuildSpec(title="test-fail", description="test")
        # File change that will create a file but tests will "fail"
        file_changes = [
            {"path": "src/probos/new_guardrail_test.py", "mode": "create", "content": "# test"},
        ]

        with patch("probos.cognitive.builder._run_tests", new_callable=AsyncMock) as mock_tests:
            mock_tests.return_value = (False, "FAILED")
            result = await execute_approved_build(
                file_changes, spec, work_dir,
                run_tests=True,
            )

        assert result.success is False
        # Branch should be cleaned up
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "--list", "builder-test-fail",
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        assert stdout.decode().strip() == "", "Branch should have been deleted"

        # Created file should also be cleaned up
        assert not (tmp_path / "src" / "probos" / "new_guardrail_test.py").exists()


# ---------------------------------------------------------------------------
# TestDirtyWorkingTree (test 8)
# ---------------------------------------------------------------------------


class TestDirtyWorkingTree:
    """Tests for dirty working tree protection."""

    @pytest.mark.asyncio
    async def test_dirty_working_tree_aborts_build(self, tmp_path):
        """Build aborts if working tree has uncommitted changes."""
        work_dir = str(tmp_path)

        spec = BuildSpec(title="test-dirty", description="test")
        file_changes = [
            {"path": "src/probos/foo.py", "mode": "create", "content": "# test"},
        ]

        with patch("probos.cognitive.builder._is_dirty_working_tree", new_callable=AsyncMock) as mock_dirty:
            mock_dirty.return_value = True
            result = await execute_approved_build(file_changes, spec, work_dir)

        assert result.success is False
        assert "uncommitted" in result.error.lower()


# ---------------------------------------------------------------------------
# TestUntrackedFileCleanup (test 9)
# ---------------------------------------------------------------------------


class TestUntrackedFileCleanup:
    """Tests for untracked file cleanup on failed builds."""

    @pytest.mark.asyncio
    async def test_untracked_files_cleaned_on_failure(self, tmp_path):
        """Created files and empty parent dirs are cleaned up on failed build."""
        work_dir = str(tmp_path)
        # Initialize a git repo with initial commit on 'main' branch
        proc = await asyncio.create_subprocess_exec(
            "git", "init", "-b", "main", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        for cmd in [
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test"],
        ]:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=work_dir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        (tmp_path / "init.txt").write_text("init")
        proc = await asyncio.create_subprocess_exec(
            "git", "add", ".", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", "init", cwd=work_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        spec = BuildSpec(title="test-cleanup", description="test")
        # This will create a nested new file
        file_changes = [
            {"path": "src/probos/deep/nested/file.py", "mode": "create", "content": "# test"},
        ]

        with patch("probos.cognitive.builder._run_tests", new_callable=AsyncMock) as mock_tests:
            mock_tests.return_value = (False, "FAILED")
            result = await execute_approved_build(
                file_changes, spec, work_dir,
                run_tests=True,
            )

        assert result.success is False
        # File should be cleaned up
        assert not (tmp_path / "src" / "probos" / "deep" / "nested" / "file.py").exists()
        # Empty parent dirs should also be removed
        assert not (tmp_path / "src" / "probos" / "deep" / "nested").exists()
        assert not (tmp_path / "src" / "probos" / "deep").exists()


# ── AD-367: Validation before commit ─────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_errors_block_commit(tmp_path):
    """Files with syntax errors should not be committed even with run_tests=False."""
    work_dir = str(tmp_path)
    subprocess.run(["git", "init", "-b", "main", work_dir], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", work_dir, "config", "user.email", "test@test.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", work_dir, "config", "user.name", "Test"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", work_dir, "commit", "--allow-empty", "-m", "init"],
                   check=True, capture_output=True)

    spec = BuildSpec(title="Bad syntax", description="Test syntax gate")
    file_changes = [
        {"path": "src/bad.py", "mode": "create", "content": "def broken(\n"},
    ]

    result = await execute_approved_build(
        file_changes, spec, work_dir, run_tests=False,
    )

    assert result.success is False
    assert "Syntax errors" in (result.error or "")
    assert not result.commit_hash, "Should NOT have committed invalid code"
