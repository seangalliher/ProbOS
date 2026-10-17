"""Worktree Manager — git worktree lifecycle for parallel builds (AD-371)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from probos.execution.command_env import trusted_command_env

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WorktreeInfo:
    """Tracks an active git worktree."""

    path: str
    branch: str
    build_id: str = ""
    created_at: float = 0.0


# ---------------------------------------------------------------------------
# WorktreeManager
# ---------------------------------------------------------------------------


class WorktreeManager:
    """Manages git worktree lifecycle for parallel builder execution."""

    def __init__(self, repo_root: str, worktree_base: str = "") -> None:
        self._repo_root = Path(repo_root).resolve()
        if worktree_base:
            self._worktree_base = Path(worktree_base).resolve()
        else:
            self._worktree_base = self._repo_root.parent / "ProbOS-builders"
        self._worktrees: dict[str, WorktreeInfo] = {}

    # -- helpers -------------------------------------------------------------

    async def _run_git(
        self, *args: str, cwd: str | None = None
    ) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        work_dir = cwd or str(self._repo_root)
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            env=trusted_command_env(),
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode(errors="replace").strip(),
            stderr_bytes.decode(errors="replace").strip(),
        )

    # -- lifecycle -----------------------------------------------------------

    async def create(self, build_id: str) -> WorktreeInfo:
        """Create a new worktree for a build.

        Branch name: builder-{build_id[:8]}
        Path: {worktree_base}/builder-{build_id[:8]}
        """
        short_id = build_id[:8]
        branch = f"builder-{short_id}"
        wt_path = self._worktree_base / f"builder-{short_id}"

        # Ensure worktree base directory exists
        self._worktree_base.mkdir(parents=True, exist_ok=True)

        rc, out, err = await self._run_git(
            "worktree", "add", "-b", branch, str(wt_path)
        )
        if rc != 0:
            raise RuntimeError(f"git worktree add failed (rc={rc}): {err}")

        info = WorktreeInfo(
            path=str(wt_path),
            branch=branch,
            build_id=build_id,
            created_at=time.monotonic(),
        )
        self._worktrees[build_id] = info
        logger.info("worktree created build_id=%s path=%s branch=%s", build_id, wt_path, branch)
        return info

    async def remove(self, build_id: str) -> bool:
        """Remove worktree and delete branch. Returns True on success."""
        info = self._worktrees.get(build_id)
        if info is None:
            return False

        # Remove worktree
        rc, out, err = await self._run_git(
            "worktree", "remove", "--force", info.path
        )
        if rc != 0:
            logger.warning("worktree remove failed build_id=%s: %s", build_id, err)
            # Try to continue with branch deletion anyway

        # Delete branch
        rc2, out2, err2 = await self._run_git("branch", "-D", info.branch)
        if rc2 != 0:
            logger.warning("branch delete failed build_id=%s branch=%s: %s", build_id, info.branch, err2)

        del self._worktrees[build_id]
        logger.info("worktree removed build_id=%s", build_id)
        return True

    # -- queries -------------------------------------------------------------

    def get(self, build_id: str) -> WorktreeInfo | None:
        """Get worktree info by build ID."""
        return self._worktrees.get(build_id)

    def get_all(self) -> list[WorktreeInfo]:
        """List all active worktrees."""
        return list(self._worktrees.values())

    # -- diff / merge --------------------------------------------------------

    async def collect_diff(self, build_id: str) -> str:
        """Run git diff main...{branch} and return the diff output."""
        info = self._worktrees.get(build_id)
        if info is None:
            return ""
        rc, out, err = await self._run_git("diff", f"main...{info.branch}")
        if rc != 0:
            logger.warning("collect_diff failed build_id=%s: %s", build_id, err)
            return ""
        return out

    async def merge_to_main(self, build_id: str) -> tuple[bool, str]:
        """BF-897 (#1559): refuse; this method never merges in the checkout ProbOS runs from.

        This used to run ``git checkout main`` and ``git merge`` in ``repo_root``,
        the operator's own checkout: it switched their branch and merged beside
        their uncommitted edits. A merge in another worktree is no better while
        ``main`` is checked out here, because moving ``refs/heads/main`` moves this
        checkout's HEAD. Delivery is the pull-request route (AD-1336 child 6,
        AD-1299), which replaces this body and keeps the ``(ok, detail)`` contract.

        Runs no git command. Returns ``(False, reason)``; the build's branch and
        worktree are kept, so it can still be delivered or rejected.
        """
        info = self._worktrees.get(build_id)
        if info is None:
            return False, "unknown build_id"
        reason = (
            "This merge request was refused (BF-897): the merge step is not available. "
            f"Branch {info.branch} is kept in {info.path}; deliver it through a pull "
            "request, or reject the build to discard it."
        )
        logger.warning("worktree merge refused build_id=%s branch=%s", build_id, info.branch)
        return False, reason

    async def adopt_commit(self, build_id: str, branch: str) -> tuple[bool, str]:
        """BF-896: move the commit on *branch* onto the worktree's own branch.

        ``execute_approved_build`` commits on a branch of its own, but ``collect_diff``
        and ``merge_to_main`` only look at ``info.branch``. This fast-forwards
        ``info.branch`` to *branch*, verifies it, then deletes *branch*.

        Returns ``(True, sha)``. A failure before the delete returns
        ``(False, "<step>: <stderr>")`` and leaves *branch* in place, so the commit
        stays recoverable. Every git call runs in the worktree and nothing assumes
        where its HEAD is.
        """
        info = self._worktrees.get(build_id)
        if info is None:
            return False, "unknown build_id"

        rc, sha, err = await self._run_git(
            "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=info.path,
        )
        if rc != 0 or not sha:
            return False, f"rev-parse {branch}: {err}"

        rc, _out, err = await self._run_git("checkout", info.branch, cwd=info.path)
        if rc != 0:
            return False, f"checkout {info.branch}: {err}"

        rc, _out, err = await self._run_git("merge", "--ff-only", branch, cwd=info.path)
        if rc != 0:
            return False, f"merge --ff-only {branch}: {err}"

        rc, tip, err = await self._run_git(
            "rev-parse", f"refs/heads/{info.branch}", cwd=info.path,
        )
        if rc != 0 or tip != sha:
            return False, f"verify {info.branch}: expected {sha}, found {tip or err}"

        try:
            rc, _out, err = await self._run_git("branch", "-D", branch, cwd=info.path)
        except Exception as delete_exc:
            # The commit is already on info.branch and verified; a failing delete
            # must not make the adoption look failed. Cancellation still propagates.
            rc, err = 1, f"{type(delete_exc).__name__}: {delete_exc}"
        if rc != 0:
            logger.warning(
                "worktree adopt_commit could not delete branch %s build_id=%s: %s; "
                "the commit is on %s and the executor branch may remain",
                branch, build_id, err, info.branch,
            )

        logger.info(
            "worktree adopted build_id=%s from=%s into=%s commit=%s",
            build_id, branch, info.branch, sha,
        )
        return True, sha

    # -- cleanup -------------------------------------------------------------

    async def cleanup_all(self) -> int:
        """Remove all managed worktrees. Returns count removed."""
        build_ids = list(self._worktrees.keys())
        count = 0
        for build_id in build_ids:
            if await self.remove(build_id):
                count += 1
        logger.info("worktree cleanup_all removed=%d", count)
        return count
