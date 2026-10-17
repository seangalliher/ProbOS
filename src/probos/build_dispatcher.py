"""Build Dispatcher — automated builder dispatch loop (AD-372).

Watches the BuildQueue, allocates worktrees, invokes builders,
and applies changes with full guardrails (test, review, commit).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from probos.build_queue import BuildQueue, QueuedBuild
from probos.cognitive.builder import (
    BuildResult,
    BuildSpec,
    execute_approved_build,
    repository_identity,
)
from probos.execution.isolation import remove_workdir_off_loop
from probos.worktree_manager import WorktreeManager

try:
    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter, seed_session_directory
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

logger = logging.getLogger(__name__)


class BuildDispatcher:
    """Orchestrates automated build execution from queue to completion."""

    def __init__(
        self,
        queue: BuildQueue,
        worktree_mgr: WorktreeManager,
        *,
        max_concurrent: int = 2,
        poll_interval: float = 5.0,
        builder_model: str = "claude-sonnet-5.5",
        builder_timeout: float = 300.0,
        run_tests: bool = True,
        on_build_complete: Callable[[QueuedBuild], Awaitable[None]] | None = None,
    ) -> None:
        self._queue = queue
        self._worktree_mgr = worktree_mgr
        self._max_concurrent = max_concurrent
        self._poll_interval = poll_interval
        self._builder_model = builder_model
        self._builder_timeout = builder_timeout
        self._run_tests = run_tests
        self._on_build_complete = on_build_complete
        self._task: asyncio.Task[None] | None = None
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._running: bool = False

    # -- properties ----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_builds(self) -> list[str]:
        """Build IDs currently being executed."""
        return list(self._active_tasks.keys())

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the dispatch loop."""
        self._running = True
        self._task = asyncio.create_task(self._dispatch_loop())
        logger.info("build-dispatcher started max_concurrent=%d", self._max_concurrent)

    async def stop(self) -> None:
        """Stop the dispatch loop and cancel active builds."""
        self._running = False
        # Cancel all active build tasks
        for build_id, task in list(self._active_tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._active_tasks.clear()
        # Cancel the dispatch loop
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("build-dispatcher stopped")

    # -- dispatch loop -------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        """Poll the queue and dispatch builds."""
        while self._running:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._try_dispatch()
            except Exception as exc:
                logger.error("dispatch loop error: %s", exc)

    async def _try_dispatch(self) -> None:
        """Try to dispatch one queued build if capacity allows."""
        # Clean up finished tasks
        done_ids = [bid for bid, t in self._active_tasks.items() if t.done()]
        for bid in done_ids:
            del self._active_tasks[bid]

        # Check capacity
        if len(self._active_tasks) >= self._max_concurrent:
            return

        # Get next available build (skip if footprint conflicts)
        build = self._find_dispatchable()
        if build is None:
            return

        # Dispatch it
        self._queue.update_status(build.id, "dispatched")
        task = asyncio.create_task(self._execute_build(build))
        self._active_tasks[build.id] = task
        logger.info(
            "build-dispatcher dispatched id=%s title=%r",
            build.id, build.spec.title,
        )

    # -- conflict detection (absorbs AD-374) ---------------------------------

    def _find_dispatchable(self) -> QueuedBuild | None:
        """Find the highest-priority queued build with no footprint conflicts."""
        queued = self._queue.get_by_status("queued")
        # Sort by priority (ascending) then created_at (ascending = FIFO)
        queued.sort(key=lambda b: (b.priority, b.created_at))
        for build in queued:
            if not self._queue.has_footprint_conflict(build.file_footprint):
                return build
        return None  # All queued builds conflict with active builds

    # -- build execution -----------------------------------------------------

    async def _execute_build(self, build: QueuedBuild) -> None:
        """Execute a single build: worktree -> adapter -> apply -> result.

        BF-896: generation runs in a fresh session directory, never in the
        worktree. The worktree's repository identity is pinned before the
        adapter exists and is checked by ``execute_approved_build``, the only
        route by which blocks reach the worktree. The session directory is
        always removed.
        """
        worktree_info = None
        session_dir: str | None = None
        # BF-896: once the executor returns, its result (and the commit it made on
        # its own branch) must survive any later exit: an error or a cancellation.
        build_result: BuildResult | None = None
        executor_branch = ""
        try:
            # 1. Create worktree
            worktree_info = await self._worktree_mgr.create(build.id)
            self._queue.update_status(
                build.id, "building",
                worktree_path=worktree_info.path,
            )

            # 2. Read source files from worktree
            file_contents = self._read_source_files(build.spec, worktree_info.path)

            # 3. Generate code via CopilotBuilderAdapter
            if not _SDK_AVAILABLE:
                raise RuntimeError("Copilot SDK not available")

            # BF-896: pin the repository the worktree names before anything
            # model-driven runs; a tree whose identity cannot be read is refused.
            expected_git_dir = await repository_identity(worktree_info.path)
            if expected_git_dir is None:
                raise RuntimeError(
                    f"Cannot pin the repository identity of worktree {worktree_info.path}"
                )

            # BF-896: the session runs in its own directory, seeded with the files
            # it may change, so the scan reports only what the session changed.
            session_dir = tempfile.mkdtemp(prefix="probos_visiting_")
            file_contents = seed_session_directory(session_dir, file_contents)

            adapter = CopilotBuilderAdapter(
                model=self._builder_model,
                cwd=session_dir,
                instruction_work_dir=worktree_info.path,
            )
            if not CopilotBuilderAdapter.is_available():
                raise RuntimeError("Copilot SDK not available")

            await adapter.start()
            try:
                copilot_result = await adapter.execute(
                    build.spec, file_contents, timeout=self._builder_timeout,
                )
            finally:
                await adapter.stop()

            if not copilot_result.success or not copilot_result.file_blocks:
                raise RuntimeError(
                    copilot_result.error or "Adapter returned no file changes"
                )

            # 4. Apply changes via execute_approved_build (all guardrails)
            build_result = await execute_approved_build(
                file_changes=copilot_result.file_blocks,
                spec=build.spec,
                work_dir=worktree_info.path,
                run_tests=self._run_tests,
                builder_source="visiting",
                expected_git_dir=expected_git_dir,
            )
            executor_branch = build_result.branch_name

            # 5. Update queue with result
            if build_result.success:
                # BF-896: the executor committed on a branch of its own, but review
                # (collect_diff) and approval (merge_to_main) read the worktree's
                # branch. Adopt the commit there, or the approval would report
                # "merged" while main was unchanged.
                sha = build_result.commit_hash
                if not sha:
                    self._queue.update_status(
                        build.id, "failed",
                        result=build_result,
                        error="no change reached the worktree",
                        completed_at=time.monotonic(),
                    )
                elif await repository_identity(worktree_info.path) != expected_git_dir:
                    # The pin must cover the hooks adoption runs (checkout, merge).
                    self._queue.update_status(
                        build.id, "failed",
                        result=build_result,
                        error=(
                            f"Repository identity changed after the build; "
                            f"commit {sha} left on {build_result.branch_name}, not adopted"
                        ),
                        completed_at=time.monotonic(),
                    )
                else:
                    try:
                        adopted, detail = await self._worktree_mgr.adopt_commit(
                            build.id, executor_branch,
                        )
                    except Exception as adopt_exc:
                        # An adoption that raises is an adoption failure: keep
                        # build_result and the recovery branch/commit. Cancellation
                        # (BaseException) still propagates.
                        logger.error(
                            "build-dispatcher adopt_commit raised id=%s commit=%s "
                            "branch=%s: %s: %s; build marked failed, commit left on "
                            "the executor branch",
                            build.id, sha, executor_branch,
                            type(adopt_exc).__name__, adopt_exc,
                        )
                        adopted = False
                        detail = f"{type(adopt_exc).__name__}: {adopt_exc}"
                    if adopted:
                        build_result.branch_name = worktree_info.branch
                        self._queue.update_status(
                            build.id, "reviewing",
                            result=build_result,
                        )
                    else:
                        self._queue.update_status(
                            build.id, "failed",
                            result=build_result,
                            error=f"commit {sha} left on {executor_branch}: {detail}",
                            completed_at=time.monotonic(),
                        )
            else:
                self._queue.update_status(
                    build.id, "failed",
                    result=build_result,
                    error=build_result.error or "Build failed",
                    completed_at=time.monotonic(),
                )

        except Exception as exc:
            logger.error("build-dispatcher build failed id=%s: %s", build.id, exc)
            error = str(exc)
            if build_result is not None and build_result.commit_hash:
                error = (
                    f"{error}; commit {build_result.commit_hash} on {executor_branch} "
                    f"or {worktree_info.branch}"
                )
            self._queue.update_status(
                build.id, "failed",
                result=build_result,
                error=error,
                completed_at=time.monotonic(),
            )
        except asyncio.CancelledError:
            # Before the executor returned there is nothing to record. After it,
            # keep the result and name where its commit is (it is on the executor
            # branch, or on the worktree branch if adoption got that far).
            # update_status is synchronous and never raises.
            if build_result is not None:
                if build_result.commit_hash:
                    cancel_error = (
                        f"cancelled after commit {build_result.commit_hash}; "
                        f"on {executor_branch} or {worktree_info.branch}"
                    )
                else:
                    cancel_error = (
                        "cancelled after the build ran, before its outcome was recorded"
                    )
                logger.warning(
                    "build-dispatcher cancelled after the build ran id=%s: %s",
                    build.id, cancel_error,
                )
                try:
                    self._queue.update_status(
                        build.id, "failed",
                        result=build_result,
                        error=cancel_error,
                        completed_at=time.monotonic(),
                    )
                except Exception:
                    # Best effort: whatever stops here must still see the
                    # cancellation, never the failure to record it.
                    logger.error(
                        "build-dispatcher could not record the cancelled build id=%s",
                        build.id, exc_info=True,
                    )
            raise
        finally:
            if session_dir is not None:
                # BF-896: the session directory is the SDK client's cwd. Removal
                # retries (BF-844); its failure must not change the recorded outcome,
                # and a cancellation still escapes.
                try:
                    await remove_workdir_off_loop(Path(session_dir))
                except asyncio.CancelledError:
                    raise
                except Exception as cleanup_exc:
                    logger.warning(
                        "build-dispatcher: could not remove session directory %s "
                        "(%s: %s); it may remain on disk. The build result is unaffected.",
                        session_dir, type(cleanup_exc).__name__, cleanup_exc,
                    )
            # Fire callback if provided
            updated_build = self._queue.get(build.id)
            if updated_build and self._on_build_complete:
                try:
                    await self._on_build_complete(updated_build)
                except Exception as cb_exc:
                    logger.warning("on_build_complete callback failed: %s", cb_exc)

    # -- helpers -------------------------------------------------------------

    def _read_source_files(
        self, spec: BuildSpec, work_dir: str,
    ) -> dict[str, str]:
        """Read target + reference files from the worktree."""
        contents: dict[str, str] = {}
        root = Path(work_dir)
        for path in spec.target_files + spec.reference_files:
            full = root / path
            if full.exists() and full.is_file():
                try:
                    contents[path] = full.read_text(encoding="utf-8")
                except Exception:
                    logger.debug("Build dispatch failed", exc_info=True)
        return contents

    # -- captain actions -----------------------------------------------------

    async def approve_and_merge(self, build_id: str) -> tuple[bool, str]:
        """Captain approves a build: deliver it, then clean up.

        Returns (success, commit_hash_or_reason). BF-897 (#1559): ``merge_to_main``
        refuses until the pull-request route (AD-1336 child 6) replaces it, so this
        returns ``(False, reason)`` and the build stays in review.
        """
        build = self._queue.get(build_id)
        if build is None or build.status != "reviewing":
            return False, f"Build {build_id} not in reviewing status"

        ok, result = await self._worktree_mgr.merge_to_main(build_id)
        if ok:
            await self._worktree_mgr.remove(build_id)
            self._queue.update_status(
                build_id, "merged",
                completed_at=time.monotonic(),
            )
            logger.info("build-dispatcher merged id=%s commit=%s", build_id, result)
        else:
            # BF-897: the build stays in review with its branch and worktree, so it
            # can still be delivered or rejected. Marking it failed would misreport a
            # correct build and strand its worktree.
            logger.warning("build-dispatcher merge refused id=%s: %s", build_id, result)

        return ok, result

    async def reject_build(self, build_id: str) -> bool:
        """Captain rejects a build — clean up worktree."""
        build = self._queue.get(build_id)
        if build is None or build.status != "reviewing":
            return False
        await self._worktree_mgr.remove(build_id)
        self._queue.update_status(
            build_id, "failed",
            error="rejected by Captain",
            completed_at=time.monotonic(),
        )
        logger.info("build-dispatcher rejected id=%s", build_id)
        return True
