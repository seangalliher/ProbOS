"""Tests for BuildDispatcher (AD-372)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.build_queue import BuildQueue, QueuedBuild
from probos.cognitive.builder import BuildResult, BuildSpec
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.worktree_manager import WorktreeInfo, WorktreeManager


def _spec(
    title: str = "test",
    target_files: list[str] | None = None,
    reference_files: list[str] | None = None,
) -> BuildSpec:
    return BuildSpec(
        title=title,
        description="test",
        target_files=target_files or [],
        reference_files=reference_files or [],
    )


def _worktree_info(build_id: str = "abc123") -> WorktreeInfo:
    return WorktreeInfo(
        path="/tmp/wt",
        branch=f"builder-{build_id[:8]}",
        build_id=build_id,
        created_at=time.monotonic(),
    )


def _build_result(success: bool = True, error: str = "") -> BuildResult:
    return BuildResult(
        success=success,
        spec=_spec(),
        error=error,
    )


def _make_dispatcher(**kwargs):
    """Create a BuildDispatcher with mocked dependencies."""
    from probos.build_dispatcher import BuildDispatcher

    queue = kwargs.pop("queue", BuildQueue())
    wm = kwargs.pop("worktree_mgr", MagicMock(spec=WorktreeManager))
    return BuildDispatcher(queue=queue, worktree_mgr=wm, **kwargs)


class TestBuildDispatcher:
    def test_default_builder_uses_highest_available_model(self) -> None:
        dispatcher = _make_dispatcher()
        assert dispatcher._builder_model == "claude-sonnet-5.5"

    def test_find_dispatchable_returns_highest_priority(self) -> None:
        """Highest priority non-conflicting build is selected."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        q.enqueue(_spec("low"), priority=10)
        q.enqueue(_spec("high"), priority=1)
        d = BuildDispatcher(queue=q, worktree_mgr=MagicMock(spec=WorktreeManager))
        build = d._find_dispatchable()
        assert build is not None
        assert build.spec.title == "high"

    def test_find_dispatchable_skips_conflicts(self) -> None:
        """Builds with footprint conflicts are skipped."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        a = q.enqueue(_spec("A", target_files=["a.py"]))
        q.update_status(a.id, "dispatched")  # A is active, touches a.py
        q.enqueue(_spec("B", target_files=["a.py"]), priority=1)  # conflicts
        q.enqueue(_spec("C", target_files=["b.py"]), priority=5)  # no conflict
        d = BuildDispatcher(queue=q, worktree_mgr=MagicMock(spec=WorktreeManager))
        build = d._find_dispatchable()
        assert build is not None
        assert build.spec.title == "C"

    def test_find_dispatchable_empty_queue(self) -> None:
        """Returns None when no builds are dispatchable."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        d = BuildDispatcher(queue=q, worktree_mgr=MagicMock(spec=WorktreeManager))
        assert d._find_dispatchable() is None

    @pytest.mark.asyncio
    async def test_execute_build_success(self) -> None:
        """Successful build transitions to reviewing status."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("test build", target_files=["foo.py"]))
        q.update_status(build.id, "dispatched")

        wm = MagicMock(spec=WorktreeManager)
        wm.create = AsyncMock(return_value=_worktree_info(build.id))

        mock_copilot_result = MagicMock()
        mock_copilot_result.success = True
        mock_copilot_result.file_blocks = [{"path": "foo.py", "content": "x = 1"}]
        mock_copilot_result.error = ""

        mock_adapter = MagicMock(spec=CopilotBuilderAdapter)
        mock_adapter.start = AsyncMock()
        mock_adapter.stop = AsyncMock()
        mock_adapter.execute = AsyncMock(return_value=mock_copilot_result)

        good_result = _build_result(success=True)
        # BF-896: the executor commits on a branch of its own, which the manager adopts onto the worktree's branch.
        good_result.commit_hash = "abc"
        good_result.branch_name = "builder/test-build"
        wm.adopt_commit = AsyncMock(return_value=(True, "abc"))
        # BF-896: "/tmp/wt" does not exist and the route now fails closed on an unpinnable worktree, so the pin is supplied.

        with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
             patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=mock_adapter) as MockCls, \
             patch("probos.build_dispatcher.repository_identity", new_callable=AsyncMock, return_value="/tmp/wt/.git"), \
             patch("probos.build_dispatcher.execute_approved_build", new_callable=AsyncMock, return_value=good_result) as mock_exec:
            MockCls.is_available.return_value = True
            d = BuildDispatcher(queue=q, worktree_mgr=wm)
            await d._execute_build(build)

        assert build.status == "reviewing"
        # BF-896: the commit was adopted from the executor's branch, and the result now names the worktree's branch.
        wm.adopt_commit.assert_awaited_once_with(build.id, "builder/test-build")
        assert build.result.branch_name == f"builder-{build.id[:8]}"
        assert build.result.commit_hash == "abc"
        # BF-896: generation runs in its own session directory, never in the worktree;
        # the worktree is only where repository instructions are discovered.
        adapter_kwargs = MockCls.call_args.kwargs
        assert adapter_kwargs["instruction_work_dir"] == "/tmp/wt"
        assert adapter_kwargs["cwd"] != "/tmp/wt"
        # BF-896: the executor is handed the pinned identity, and the session directory is gone.
        assert mock_exec.await_args.kwargs["expected_git_dir"] == "/tmp/wt/.git"
        assert not Path(adapter_kwargs["cwd"]).exists()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["adoption_fails", "no_commit", "identity_changed"])
    async def test_execute_build_success_not_adopted_fails(self, scenario: str) -> None:
        """BF-896: a successful executor result that was not adopted never reaches reviewing."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("adopt build", target_files=["foo.py"]))
        q.update_status(build.id, "dispatched")

        wm = MagicMock(spec=WorktreeManager)
        wm.create = AsyncMock(return_value=_worktree_info(build.id))
        wm.adopt_commit = AsyncMock(return_value=(False, "merge --ff-only builder/adopt-build: not possible"))

        mock_copilot_result = MagicMock()
        mock_copilot_result.success = True
        mock_copilot_result.file_blocks = [{"path": "foo.py", "content": "x = 1"}]
        mock_copilot_result.error = ""
        mock_adapter = MagicMock(spec=CopilotBuilderAdapter)
        mock_adapter.start = AsyncMock()
        mock_adapter.stop = AsyncMock()
        mock_adapter.execute = AsyncMock(return_value=mock_copilot_result)

        result = _build_result(success=True)
        result.branch_name = "builder/adopt-build"
        result.commit_hash = "" if scenario == "no_commit" else "abc123"
        identity = AsyncMock(
            side_effect=["/tmp/wt/.git", "/tmp/other/.git"] if scenario == "identity_changed" else None,
            return_value="/tmp/wt/.git",
        )

        with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
             patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=mock_adapter) as MockCls, \
             patch("probos.build_dispatcher.repository_identity", identity), \
             patch("probos.build_dispatcher.execute_approved_build", new_callable=AsyncMock, return_value=result):
            MockCls.is_available.return_value = True
            await BuildDispatcher(queue=q, worktree_mgr=wm)._execute_build(build)

        assert build.status == "failed"
        if scenario == "adoption_fails":
            wm.adopt_commit.assert_awaited_once()
            assert "abc123" in build.error and "builder/adopt-build" in build.error
            assert "not possible" in build.error
        elif scenario == "no_commit":
            wm.adopt_commit.assert_not_awaited()
            assert build.error == "no change reached the worktree"
        else:
            wm.adopt_commit.assert_not_awaited()
            assert "identity" in build.error
        assert build.result is result

    @pytest.mark.asyncio
    async def test_execute_build_adapter_failure(self) -> None:
        """Adapter failure transitions to failed status."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("fail build"))
        q.update_status(build.id, "dispatched")

        wm = MagicMock(spec=WorktreeManager)
        wm.create = AsyncMock(return_value=_worktree_info(build.id))

        mock_copilot_result = MagicMock()
        mock_copilot_result.success = False
        mock_copilot_result.file_blocks = []
        mock_copilot_result.error = "LLM timeout"

        mock_adapter = MagicMock(spec=CopilotBuilderAdapter)
        mock_adapter.start = AsyncMock()
        mock_adapter.stop = AsyncMock()
        mock_adapter.execute = AsyncMock(return_value=mock_copilot_result)

        # BF-896: "/tmp/wt" does not exist and the route now fails closed on an unpinnable worktree, so the pin is supplied.
        with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
             patch("probos.build_dispatcher.repository_identity", new_callable=AsyncMock, return_value="/tmp/wt/.git"), \
             patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=mock_adapter) as MockCls:
            MockCls.is_available.return_value = True
            d = BuildDispatcher(queue=q, worktree_mgr=wm)
            await d._execute_build(build)

        assert build.status == "failed"
        assert "LLM timeout" in build.error

    @pytest.mark.asyncio
    async def test_execute_build_worktree_failure(self) -> None:
        """Worktree creation failure transitions to failed status."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("wt fail"))
        q.update_status(build.id, "dispatched")

        wm = MagicMock(spec=WorktreeManager)
        wm.create = AsyncMock(side_effect=RuntimeError("git worktree add failed"))

        d = BuildDispatcher(queue=q, worktree_mgr=wm)
        await d._execute_build(build)

        assert build.status == "failed"
        assert "worktree" in build.error.lower()

    @pytest.mark.asyncio
    async def test_approve_and_merge(self) -> None:
        """approve_and_merge merges, removes worktree, sets status to merged."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("merge me"))
        q.update_status(build.id, "dispatched")
        q.update_status(build.id, "building")
        q.update_status(build.id, "reviewing")

        wm = MagicMock(spec=WorktreeManager)
        wm.merge_to_main = AsyncMock(return_value=(True, "abc123def"))
        wm.remove = AsyncMock(return_value=True)

        d = BuildDispatcher(queue=q, worktree_mgr=wm)
        ok, commit = await d.approve_and_merge(build.id)

        assert ok is True
        assert commit == "abc123def"
        assert build.status == "merged"
        wm.remove.assert_awaited_once_with(build.id)

    @pytest.mark.asyncio
    async def test_approve_and_merge_refusal_keeps_the_build_in_review(self) -> None:
        """BF-897 (#1559): a refused merge leaves the build in review with its worktree, so it can still be rejected."""
        from probos.build_dispatcher import BuildDispatcher

        refusal = "This merge request was refused (BF-897): the merge step is not available."
        q = BuildQueue()
        build = q.enqueue(_spec("refused merge"))
        control = q.enqueue(_spec("accepted merge"))
        for queued in (build, control):
            q.update_status(queued.id, "dispatched")
            q.update_status(queued.id, "building")
            q.update_status(queued.id, "reviewing")

        wm = MagicMock(spec=WorktreeManager)
        # One mocked merge: it refuses for `build` and accepts for `control`, so the two outcomes differ only by its answer.
        wm.merge_to_main = AsyncMock(
            side_effect=lambda build_id: (True, "abc123def") if build_id == control.id else (False, refusal),
        )
        wm.remove = AsyncMock(return_value=True)

        d = BuildDispatcher(queue=q, worktree_mgr=wm)
        ok, reason = await d.approve_and_merge(build.id)

        # Premise: the merge was asked for and the mocked refusal came back (not "not in reviewing status").
        wm.merge_to_main.assert_awaited_once_with(build.id)
        assert (ok, reason) == (False, refusal)
        assert build.status == "reviewing"
        assert build.error == ""
        wm.remove.assert_not_awaited()

        # Control: the same dispatcher and mock, with the merge accepted, still merges and removes the worktree.
        assert await d.approve_and_merge(control.id) == (True, "abc123def")
        assert control.status == "merged"
        wm.remove.assert_awaited_once_with(control.id)
        assert build.status == "reviewing"

        # The refused build was never marked failed, so it can still be rejected.
        assert await d.reject_build(build.id) is True
        assert build.status == "failed"
        assert build.error == "rejected by Captain"
        assert wm.remove.await_args_list[-1].args == (build.id,)

    @pytest.mark.asyncio
    async def test_reject_build(self) -> None:
        """reject_build removes worktree and sets status to failed."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("reject me"))
        q.update_status(build.id, "dispatched")
        q.update_status(build.id, "building")
        q.update_status(build.id, "reviewing")

        wm = MagicMock(spec=WorktreeManager)
        wm.remove = AsyncMock(return_value=True)

        d = BuildDispatcher(queue=q, worktree_mgr=wm)
        ok = await d.reject_build(build.id)

        assert ok is True
        assert build.status == "failed"
        assert build.error == "rejected by Captain"
        wm.remove.assert_awaited_once_with(build.id)

    @pytest.mark.asyncio
    async def test_on_build_complete_callback(self) -> None:
        """on_build_complete callback fires after build finishes."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        build = q.enqueue(_spec("callback test"))
        q.update_status(build.id, "dispatched")

        wm = MagicMock(spec=WorktreeManager)
        wm.create = AsyncMock(side_effect=RuntimeError("fail for test"))

        callback = AsyncMock()
        d = BuildDispatcher(queue=q, worktree_mgr=wm, on_build_complete=callback)
        await d._execute_build(build)

        callback.assert_awaited_once()
        called_build = callback.call_args[0][0]
        assert called_build.id == build.id

    @pytest.mark.asyncio
    async def test_try_dispatch_respects_max_concurrent(self) -> None:
        """Does not dispatch when at max capacity."""
        from probos.build_dispatcher import BuildDispatcher

        q = BuildQueue()
        q.enqueue(_spec("queued item"))

        d = BuildDispatcher(queue=q, worktree_mgr=MagicMock(), max_concurrent=1)
        # Simulate an active task
        fake_task = MagicMock()
        fake_task.done.return_value = False
        d._active_tasks["existing"] = fake_task

        await d._try_dispatch()

        # Should still have only the fake task, no new dispatch
        assert len(d._active_tasks) == 1
        assert "existing" in d._active_tasks

    def test_read_source_files(self, tmp_path: Path) -> None:
        """Reads existing target + reference files from worktree."""
        from probos.build_dispatcher import BuildDispatcher

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").write_text("x = 1\n")
        (tmp_path / "src" / "bar.py").write_text("y = 2\n")

        spec = _spec(
            target_files=["src/foo.py"],
            reference_files=["src/bar.py", "src/missing.py"],
        )

        d = BuildDispatcher(queue=BuildQueue(), worktree_mgr=MagicMock(spec=WorktreeManager))
        contents = d._read_source_files(spec, str(tmp_path))

        assert contents["src/foo.py"] == "x = 1\n"
        assert contents["src/bar.py"] == "y = 2\n"
        assert "src/missing.py" not in contents
