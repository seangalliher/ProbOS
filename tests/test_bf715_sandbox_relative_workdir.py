"""BF-715: a relative workdir made the sandbox script path resolve twice.

``SubprocessSandbox`` launches the child with ``cwd=workdir`` and passes the
script path in ``argv``. When ``workdir`` was relative — which is the DEFAULT,
since ``execution.scratch_dir`` is ``data/execution/scratch`` — the relative
argv path was resolved a second time against the new cwd:

    argv script : data/execution/scratch/exec-A/script.py
    child cwd   : data/execution/scratch/exec-A
    child opens : data/execution/scratch/exec-A/
                  data/execution/scratch/exec-A/script.py     -> ENOENT

Every ``code_execution_tool`` run on a default configuration exited 2 with
"can't open file". Found live on the reference vessel: an agent asked to write
a report degraded honestly, said the execution environment "can't locate its own
script file", and correctly described the doubled path.
"""

from pathlib import Path

import pytest

from probos.execution.isolation import ExecutionRequest, SubprocessSandbox


class TestRelativeWorkdirStillRunsTheScript:
    """The regression. Both cases failed before BF-715."""

    @pytest.mark.asyncio
    async def test_relative_workdir_executes_successfully(self, tmp_path, monkeypatch):
        # Arrange — a RELATIVE workdir, exactly as the tool builds it.
        monkeypatch.chdir(tmp_path)
        workdir = Path("data/execution/scratch/exec-relative")
        workdir.mkdir(parents=True, exist_ok=True)
        sandbox = SubprocessSandbox(scratch_root="data/execution/scratch")

        # Act
        res = await sandbox.run(
            ExecutionRequest(
                code="print('hello from the sandbox')",
                workdir=workdir,
                timeout_seconds=60,
            )
        )

        # Assert — the doubled path produced exit_code 2 and "can't open file".
        assert res.exit_code == 0, f"stderr={res.stderr!r}"
        assert res.success is True
        assert "hello from the sandbox" in res.stdout
        assert "can't open file" not in res.stderr

    @pytest.mark.asyncio
    async def test_relative_scratch_root_with_no_workdir_also_runs(
        self, tmp_path, monkeypatch
    ):
        """The sandbox-generated branch takes the same doubling."""
        # Arrange
        monkeypatch.chdir(tmp_path)
        sandbox = SubprocessSandbox(scratch_root="data/execution/scratch")

        # Act — workdir omitted, so the sandbox builds it from scratch_root.
        res = await sandbox.run(
            ExecutionRequest(code="print('generated workdir')", timeout_seconds=60)
        )

        # Assert
        assert res.exit_code == 0, f"stderr={res.stderr!r}"
        assert "generated workdir" in res.stdout


class TestWorkdirIsReportedAbsolute:
    """Resolving also makes the returned path useful to callers."""

    @pytest.mark.asyncio
    async def test_reported_workdir_is_absolute(self, tmp_path, monkeypatch):
        # Arrange
        monkeypatch.chdir(tmp_path)
        workdir = Path("data/execution/scratch/exec-abs")
        workdir.mkdir(parents=True, exist_ok=True)
        sandbox = SubprocessSandbox(scratch_root="data/execution/scratch")

        # Act
        res = await sandbox.run(
            ExecutionRequest(code="pass", workdir=workdir, timeout_seconds=60)
        )

        # Assert — a relative string would be meaningless to a caller whose cwd
        # differs from the runtime's.
        assert Path(res.workdir).is_absolute()

    @pytest.mark.asyncio
    async def test_absolute_workdir_is_unchanged(self, tmp_path):
        """An already-absolute caller must be byte-identical to before."""
        # Arrange
        workdir = tmp_path / "exec-already-absolute"
        workdir.mkdir(parents=True, exist_ok=True)
        sandbox = SubprocessSandbox(scratch_root=str(tmp_path))

        # Act
        res = await sandbox.run(
            ExecutionRequest(
                code="print('absolute ok')", workdir=workdir, timeout_seconds=60
            )
        )

        # Assert
        assert res.exit_code == 0, f"stderr={res.stderr!r}"
        assert "absolute ok" in res.stdout
        assert Path(res.workdir) == workdir.resolve()


class TestCleanupStillHonoursOwnership:
    """Resolving must not change who deletes the directory."""

    @pytest.mark.asyncio
    async def test_caller_supplied_workdir_survives(self, tmp_path, monkeypatch):
        # Arrange
        monkeypatch.chdir(tmp_path)
        workdir = Path("data/execution/scratch/exec-kept")
        workdir.mkdir(parents=True, exist_ok=True)
        sandbox = SubprocessSandbox(scratch_root="data/execution/scratch")

        # Act
        await sandbox.run(
            ExecutionRequest(code="pass", workdir=workdir, timeout_seconds=60)
        )

        # Assert — the caller owns it and cleans it up itself (the tool does).
        assert workdir.exists()

    @pytest.mark.asyncio
    async def test_sandbox_generated_workdir_is_removed(self, tmp_path, monkeypatch):
        # Arrange
        monkeypatch.chdir(tmp_path)
        sandbox = SubprocessSandbox(scratch_root="data/execution/scratch")

        # Act
        res = await sandbox.run(
            ExecutionRequest(code="pass", timeout_seconds=60)
        )

        # Assert
        assert not Path(res.workdir).exists()
