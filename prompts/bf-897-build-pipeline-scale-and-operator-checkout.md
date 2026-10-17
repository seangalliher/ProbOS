# BF-897 (#1559): the builder runs targeted tests only, and nothing in the build pipeline merges or executes in the operator's checkout

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Revised by:** the orchestrator, 2026-10-17: one anchor only (Section 8, the `PROGRESS.md` SEARCH, re-anchored on the AD-1328 S2c entry after PR #1574 added it at the head of the file); no design change.
**Status:** ready to build. Drafted on `origin/main` `2400b14c`; built on `b91448c1` (PR #1574 merged: it touched `DECISIONS.md` and `PROGRESS.md`, no file this contract changes). No new AD or BF number; BF-897 is allocated by the title of #1559.
**Dependencies:** none. This contract does not touch anything AD-1328 owns (`execution/command_policy.py`, `run_command`, the escalation store); its S2b and S2c are on another branch.
**Estimated tests:** about 24 new tests in one new file, 3 new tests in existing files, 8 existing tests updated (named under Tests).
**Milestones:** M1 = Sections 1-2 and test groups T-A1..T-A3 and T-C. M2 = Sections 3-5 and test groups T-A4..T-A6 and T-B, then Sections 6-8 (docs and trackers).

## Risk classification (the Captain's rule: scale rigor to risk)

| Part | Property | Class | Rigor |
|---|---|---|---|
| Merge (`merge_to_main`, `approve_and_merge`) | The operator's checkout is never mutated | Data integrity | Real-git tests, before/after snapshot, mutation rows M1-M7 |
| Execute (`/api/build/approve`, `/resolve`, `execute_approved_build`) | Same | Data integrity | Same |
| Test timeouts (`_run_targeted_tests`, the test loop) | A correct build is not reported as failed | Correctness, not integrity | Standard focused tests with a fake runner, rows M8-M9 |

## Decisions (ranked; the top option of each is chosen)

### D-a: the full-suite phase, the no-targeted-tests fallback and timeouts

| Rank | Option | Correctness | Safety | Compatibility | Fit with AD-1336 child 2 | Reversibility | Validation cost |
|---|---|---|---|---|---|---|---|
| **1 (chosen)** | Remove phase 2 from the builder and report the full suite as `not_run` (`BuildResult.metadata["full_suite"]`). With no mapped test, run nothing and return a stated reason; the change is not committed. Only a real `failed` result enters the fix loop. | A correct build is no longer failed by a run that cannot finish | Fail closed: an untested change is still not committed | No config field (the golden pin `tests/test_ad1152_agentic_correlation.py` is unchanged); `BuildResult` gains no field | Child 2 replaces the single `FULL_SUITE_NOT_RUN` assignment with a call to the governed runner | One constant and one branch | Low (fake runner) |
| 2 | A configured bound (a new SystemConfig field, default 1,800 s or more), with expiry reported as `timed_out` | Correct | A 15-20 minute pytest run in a runtime executor thread, up to 3 times per build with the fix loop, on the live vessel | Changes the default-config hash | Builds a second full-suite runner that child 2 then removes | Medium | Medium |
| 3 | Off by default behind a new flag, plus the bound | Correct | As 2 when on | Changes the hash | Dead path by default; child 2 replaces it | Medium | Medium |
| 4 | Raise the hard-coded 180 to about 1,800 | Fails again as the suite grows | As 2 | No config change | Pre-empts child 2 | Easy | Low |

What a timeout does: a **targeted** timeout leaves `tests_passed=False`, records `metadata["targeted_tests"]="timed_out"`, does not enter the fix loop and is not committed. The error starts with "Targeted tests timed out", and `classify_build_failure` still classifies it as `timeout` (it matches "timed out after"). The **full suite** never runs in the builder, so it can never time out or fail a change.

The no-targeted fallback had three options. The chosen one is "not run, not committed, no fix loop". The two rejected options:
- Commit anyway with `tests_passed=False`. This weakens the AD-338 commit gate.
- Run a "smoke subset". This invents a test policy that no one owns.

The chosen option is not a regression: today the 60 s full-suite fallback always fails.

### D-b: `merge_to_main`

| Rank | Option | Notes |
|---|---|---|
| **1 (chosen)** | Refuse with a reason and run no git command. The build stays `reviewing`, and its branch and worktree are kept for delivery through a pull request (AD-1336 child 6, AD-1299). Reject still discards it. | Zero mutation by construction. Child 6 replaces the method body; the signature and the `(ok, detail)` contract stay. |
| 2 | Merge in a dedicated linked worktree (detached at `main`, then move `refs/heads/main`) | The operator normally has `main` checked out. Moving `refs/heads/main` then moves that checkout's HEAD, and their tree shows the merge reversed as uncommitted changes. That breaks "same HEAD". To be safe it must refuse whenever `main` is checked out anywhere, which is the normal case, so this is option 1 at a higher cost. |
| 3 | Merge into an integration branch in a linked worktree | Invents a delivery branch policy that child 6 owns. |

### D-c: `/api/build/approve`

| Rank | Option | Notes |
|---|---|---|
| **1 (chosen)** | Refuse before any task is scheduled. Emit `build_failure` with the reason (the HXI shows it through the legacy branch of `useStore.ts:3807-3818`) and return `{"status":"error","build_id","message"}`. Defence in depth: `execute_approved_build` refuses any `work_dir` inside the checkout the runtime started from (`builder_paths.operator_checkout_refusal`, no subprocess), and `/resolve` refuses abort and commit_override on such a cached `work_dir`. | Fail closed, with the API keys kept. Child 5 (the build lane) replaces the refusal with a run in a governed worktree, and the lower guard then passes it unchanged. |
| 2 | Run in a `WorktreeManager` worktree | Needs a public accessor for the dispatcher's private manager, plus an owner for the worktree's lifecycle (review, removal, delivery) and for `/resolve` semantics inside it. That is child 5's lane, and merge is refused anyway, so every approval would strand a worktree. |
| 3 | Enqueue the pre-generated changes on the dispatcher | Changes the BF-896 route. Forbidden by #1559's Do Not Build. |

**Cut, and why:**
- `classify_build_failure` gets no `not_run` category. After this change it is reachable only through the router's `_execute_build`, whose only caller is now the `/resolve` retry over an empty cache, and through `escalation_hook`, which both production callers pass as `None`.
- `_run_tests` stays. It has no production caller after this change, but the BF-892 environment boundary is tested through it (`tests/test_bf892_spawn_env.py:69`).
- No HXI message for the queue-approve refusal. The body carries the reason and the buttons ignore bodies. Emitting `build_failure` would fire the Night Orders `build_failure` escalation (`runtime.py:2097`) for a click the Captain made. Child 6 replaces the refusal.

## Needs the Captain

None. Every part is fail-closed, reversible and inside #1559's acceptance. No security control is weakened (two are added), and there is no schema or API key change, no spending and no OSS boundary question. One behaviour change is worth stating: HXI approval no longer lands a commit on `main`. The Captain delivers a reviewed build's branch (`builder-<id8>`, kept in `../ProbOS-builders/`) himself, or through a PR, until child 6 lands.

## Problem (verified on `2400b14c`)

1. **Timeouts.** `src/probos/cognitive/builder.py:2877-2889`: phase 1 runs `_run_targeted_tests(..., timeout=60)`. If that passes with mapped files, phase 2 runs `_run_tests(work_dir, timeout=180)` (the whole suite) and sets `tests_passed=False` on any failure, including `"pytest timed out after 180s"` (`builder.py:2445-2446`). `_run_targeted_tests` (`builder.py:2499-2502`) runs the whole suite under the targeted 60 s budget when nothing maps. The suite is about 48K tests and takes 14-19 minutes, so both paths always fail, and the fix loop (`builder.py:2894-2971`) then asks the model to "fix" a timeout. **Reachable today:** `BuildDispatcher(run_tests=True)` is the default (`build_dispatcher.py:49`, `structural_services.py:113-117` passes no `run_tests`), and its route calls `execute_approved_build(..., run_tests=self._run_tests)` (`build_dispatcher.py:215-222`).
2. **Merge.** `WorktreeManager.merge_to_main` (`worktree_manager.py:146-172`) runs `git checkout main` and `git merge <branch> --no-edit` with `cwd=self._repo_root` (`_run_git` default, `worktree_manager.py:53`). `repo_root` is the source checkout (`structural_services.py:110-112`). The only caller is `BuildDispatcher.approve_and_merge` (`build_dispatcher.py:388`), reached from `POST /api/build/queue/approve` (`routers/build.py:158`), which `FullKanban.tsx:74` and `IntentSurface.tsx:2063` call. **The BF-896 visiting route itself does not call `merge_to_main`.** Its build step (`build_dispatcher.py:150-358`) ends at `reviewing`, and the Captain's approval of that build calls it.
3. **Execute.** `POST /api/build/approve` (`routers/build.py:43-71`) sets `work_dir` to the repository root (`routers/build.py:60`) and schedules `_execute_build` (`routers/build.py:374-445`). That calls `execute_approved_build` (`routers/build.py:394-401`), which creates a branch (`builder.py:2701`), writes files, runs pytest, commits and finally runs `git checkout main` (`builder.py:3049`) in that tree. On a dirty tree it refuses at `builder.py:2673-2678`; on the Captain's machine today that is the uncommitted `config/system.yaml`. In a clean checkout (CI, a fresh clone) it runs. The test `tests/test_builder_api.py:139` (`test_approve_returns_started`) schedules exactly this against the real repository root through a real runtime. A failure is cached with that `work_dir` (`routers/build.py:426-432`), and then `/resolve` "abort" runs `git checkout main` and "commit_override" commits, both in the operator's checkout (`routers/build.py:91-125`). The dispatcher route passes `work_dir=worktree_info.path` (`build_dispatcher.py:218`), a linked worktree under `<repo>/../ProbOS-builders/`. **The router is the only place that executes in the repository root.**

## Solution

- `builder_paths.operator_checkout_refusal(work_dir, operator_root)`: a pure filesystem check with no subprocess. It finds the nearest `.git` entry at or above `work_dir`, the way git discovers a repository. If that entry belongs to `operator_root`, the work tree is refused. A linked worktree, nested or not, has its own `.git` pointer file and passes.
- `execute_approved_build` calls the guard first, before the BF-896 pin, any git command or any write.
- `/api/build/approve` refuses. `/resolve` refuses abort and commit_override on a cached operator `work_dir`.
- `merge_to_main` refuses with no git command. `approve_and_merge` keeps the build in `reviewing`.
- The test loop is targeted-only. A classifier separates `passed`, `failed`, `timed_out` and `not_run`, and only `failed` reaches the fix loop.

---

## Section 1: `src/probos/cognitive/builder_paths.py`

<<<<<<< SEARCH
        if os.path.samestat(current, git_entry):
            return f"Forbidden path (same file as .git): {path_str}"
    return None
=======
        if os.path.samestat(current, git_entry):
            return f"Forbidden path (same file as .git): {path_str}"
    return None


def operator_checkout_refusal(
    work_dir: str | os.PathLike[str], operator_root: str | os.PathLike[str],
) -> str | None:
    """BF-897 (#1559): why a build must not run in *work_dir*, or None if it may.

    *operator_root* is the checkout the runtime started from. A build that runs
    there switches the operator's branch, writes beside their uncommitted edits
    and commits in their tree, so it is refused. Git finds a work tree's
    repository at the nearest ``.git`` entry (a directory, or a linked
    worktree's pointer file) at or above it; *work_dir* is refused when that
    entry is *operator_root*'s. A linked worktree, nested inside the checkout or
    not, has its own ``.git`` entry and is allowed, and so is a tree outside any
    checkout. No git command runs, so a test that patches ``subprocess.run``
    sees no extra call. A path that cannot be examined is refused.
    """
    root = Path(operator_root)
    try:
        if not os.path.lexists(root / ".git"):
            return None  # the runtime does not run from a checkout: nothing to protect
        target = Path(work_dir).resolve()
        for candidate in (target, *target.parents):
            if os.path.lexists(candidate / ".git"):
                if os.path.samefile(candidate, root):
                    return (
                        f"Refused (BF-897): {work_dir} is in the checkout ProbOS runs from "
                        f"({root}); a build runs only in a linked worktree"
                    )
                return None
    except OSError as exc:
        return (
            "Refused (BF-897): cannot verify the build work tree against the checkout "
            f"ProbOS runs from ({type(exc).__name__}): {work_dir}"
        )
    return None
>>>>>>> REPLACE

## Section 2: `src/probos/cognitive/builder.py`

### 2.1 Import

<<<<<<< SEARCH
from probos.cognitive.builder_paths import builder_write_refusal
from probos.cognitive.cognitive_agent import CognitiveAgent
=======
from probos.cognitive.builder_paths import builder_write_refusal, operator_checkout_refusal
from probos.cognitive.cognitive_agent import CognitiveAgent
>>>>>>> REPLACE

### 2.2 Constants, and the `_run_tests` docstring

<<<<<<< SEARCH
async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
=======
# BF-897 (#1559): the builder runs only the targeted tests. The full suite (about 48K
# tests, 14 to 19 minutes) never fit the 180 s phase 2 or the 60 s fallback, so every
# build with tests failed. It belongs to the receipted gate (AD-1336 child 2); the
# builder records it as not run, at the one place a governed runner later replaces.
TARGETED_TEST_TIMEOUT_S = 60
FULL_SUITE_NOT_RUN = "not_run"
NO_TARGETED_TESTS = (
    "No targeted tests map to the changed files, and the builder does not run the "
    "full suite (BF-897), so the change was not tested and is not committed."
)
_PYTEST_TIMEOUT_PREFIX = "pytest timed out after"


async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run the whole pytest suite in *work_dir* and return (passed, output).

    BF-897: no build path calls this any more (the full suite is the receipted
    gate's). It is kept because BF-892's environment boundary is tested through it.
    """
>>>>>>> REPLACE

### 2.3 The no-targeted-tests fallback

<<<<<<< SEARCH
    Returns (passed, output, test_files_run).
    If no matching test files found, falls back to full suite.
    """
    test_files = _map_source_to_tests(changed_files, work_dir)

    if not test_files:
        # No targeted tests found, run full suite
        passed, output = await _run_tests(work_dir, timeout=timeout)
        return passed, output, []
=======
    Returns (passed, output, test_files_run).
    BF-897 (#1559): when no test file maps to the changed files nothing runs and
    the result is ``(False, NO_TARGETED_TESTS, [])``. The full suite never finished
    within this budget; it belongs to the receipted gate (AD-1336 child 2).
    """
    test_files = _map_source_to_tests(changed_files, work_dir)

    if not test_files:
        return False, NO_TARGETED_TESTS, []
>>>>>>> REPLACE

### 2.4 The outcome classifier

<<<<<<< SEARCH
    return returncode == 0, output, test_files


def _build_fix_prompt(
=======
    return returncode == 0, output, test_files


def _classify_test_run(passed: bool, output: str) -> str:
    """BF-897: ``passed``, ``timed_out``, ``not_run`` or ``failed``.

    Only ``failed`` reaches the fix loop: a timeout or an untested change is
    nothing a model's repair can fix, and asking for one spends a deep-tier call
    on output that names no failing test.
    """
    if passed:
        return "passed"
    if output.startswith(_PYTEST_TIMEOUT_PREFIX):
        return "timed_out"
    if output == NO_TARGETED_TESTS:
        return "not_run"
    return "failed"


def _build_fix_prompt(
>>>>>>> REPLACE

### 2.5 The entry guard

<<<<<<< SEARCH
    result = BuildResult(success=False, spec=spec)
    identity_lost = False

    # 0. BF-896: the tree must still name the repository pinned before generation.
=======
    result = BuildResult(success=False, spec=spec)
    identity_lost = False

    # 0a. BF-897 (#1559): never in the checkout the runtime started from. Before any
    # git command or write; no subprocess, so tests that patch subprocess.run see none.
    checkout_refusal = operator_checkout_refusal(work_dir, _PROJECT_ROOT)
    if checkout_refusal is not None:
        result.error = checkout_refusal
        return result

    # 0. BF-896: the tree must still name the repository pinned before generation.
>>>>>>> REPLACE

### 2.6 The test loop: targeted only, and only a failure reaches the fix loop

<<<<<<< SEARCH
            for attempt in range(1 + max_fix_attempts):
                # Phase 1: Targeted tests only (fast, AD-344)
                passed, test_output, targeted_files = await _run_targeted_tests(
                    work_dir, all_changed_files, timeout=60,
                )
                result.test_result = test_output
                result.tests_passed = passed

                if passed and targeted_files:
                    # Phase 2: Full suite only if targeted passed (AD-344)
                    passed_full, full_output = await _run_tests(work_dir, timeout=180)
                    if not passed_full:
                        result.test_result = full_output
                        result.tests_passed = False
                        passed = False

                if passed:
                    break

                if attempt < max_fix_attempts and llm_client is not None:
=======
            for attempt in range(1 + max_fix_attempts):
                # Targeted tests only (AD-344). BF-897: there is no full-suite phase here.
                passed, test_output, _targeted_files = await _run_targeted_tests(
                    work_dir, all_changed_files, timeout=TARGETED_TEST_TIMEOUT_S,
                )
                result.test_result = test_output
                result.tests_passed = passed
                test_outcome = _classify_test_run(passed, test_output)
                result.metadata["targeted_tests"] = test_outcome

                if passed:
                    break
                if test_outcome != "failed":
                    # BF-897: a timeout or an untested change never enters the fix loop.
                    logger.warning(
                        "BuilderAgent: targeted tests %s on attempt %d; no fix requested",
                        test_outcome, attempt + 1,
                    )
                    break

                if attempt < max_fix_attempts and llm_client is not None:
>>>>>>> REPLACE

### 2.7 Record the full suite as not run

<<<<<<< SEARCH
            result.files_written = written
            result.files_modified = modified_files

        # 5.4. BF-896: the tests may have run arbitrary code; the tree must still
=======
            result.files_written = written
            result.files_modified = modified_files
            # BF-897: the full suite is the receipted gate's (AD-1336 child 2); not run here.
            result.metadata["full_suite"] = FULL_SUITE_NOT_RUN

        # 5.4. BF-896: the tests may have run arbitrary code; the tree must still
>>>>>>> REPLACE

### 2.8 Say what happened at the commit gate

<<<<<<< SEARCH
                if run_tests and not result.tests_passed:
                    result.error = (
                        "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
                        "Code written to branch but NOT committed.\n"
                        + (result.test_result or "")[-1000:]
                    )
                    result.success = False
=======
                if run_tests and not result.tests_passed:
                    # BF-897: only a failure is "Tests failed".
                    test_outcome = result.metadata.get("targeted_tests", "failed")
                    if test_outcome == "timed_out":
                        lead = "Targeted tests timed out; no fix was requested. "
                    elif test_outcome == "not_run":
                        lead = "No targeted tests ran. "
                    else:
                        lead = "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
                    result.error = (
                        lead
                        + "Code written to branch but NOT committed.\n"
                        + (result.test_result or "")[-1000:]
                    )
                    result.success = False
>>>>>>> REPLACE

## Section 3: `src/probos/worktree_manager.py`

<<<<<<< SEARCH
    async def merge_to_main(self, build_id: str) -> tuple[bool, str]:
        """Merge the worktree's branch into main.

        Returns (success, commit_hash_or_error).
        Must be called from the main repo (not the worktree).
        """
        info = self._worktrees.get(build_id)
        if info is None:
            return False, "unknown build_id"

        # Checkout main
        rc, out, err = await self._run_git("checkout", "main")
        if rc != 0:
            return False, f"checkout main failed: {err}"

        # Merge branch
        rc, out, err = await self._run_git("merge", info.branch, "--no-edit")
        if rc != 0:
            return False, f"merge failed: {err}"

        # Get the merge commit hash
        rc, commit_hash, err = await self._run_git("rev-parse", "HEAD")
        if rc != 0:
            return False, f"rev-parse failed: {err}"

        logger.info("worktree merged build_id=%s branch=%s commit=%s", build_id, info.branch, commit_hash)
        return True, commit_hash
=======
    async def merge_to_main(self, build_id: str) -> tuple[bool, str]:
        """BF-897 (#1559): refuse; ProbOS never merges in the checkout it runs from.

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
            "Not merged (BF-897): ProbOS does not merge in the checkout it runs from. "
            f"Branch {info.branch} is kept in {info.path}; deliver it through a pull "
            "request, or reject the build to discard it."
        )
        logger.warning("worktree merge refused build_id=%s branch=%s", build_id, info.branch)
        return False, reason
>>>>>>> REPLACE

## Section 4: `src/probos/build_dispatcher.py`

<<<<<<< SEARCH
    async def approve_and_merge(self, build_id: str) -> tuple[bool, str]:
        """Captain approves a build — merge to main and clean up.

        Returns (success, commit_hash_or_error).
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
            self._queue.update_status(
                build_id, "failed",
                error=f"Merge failed: {result}",
                completed_at=time.monotonic(),
            )
            logger.error("build-dispatcher merge failed id=%s: %s", build_id, result)

        return ok, result
=======
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
>>>>>>> REPLACE

## Section 5: `src/probos/routers/build.py`

### 5.1 Imports

<<<<<<< SEARCH
import logging
import time
from typing import Any, Callable

from fastapi import APIRouter, Depends

from probos.api_models import (
    BuildApproveRequest, BuildEnqueueRequest, BuildQueueApproveRequest,
    BuildQueueRejectRequest, BuildRequest, BuildResolveRequest,
)
from probos.events import EventType
from probos.routers.deps import get_runtime, get_task_tracker
=======
import logging
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends

from probos.api_models import (
    BuildApproveRequest, BuildEnqueueRequest, BuildQueueApproveRequest,
    BuildQueueRejectRequest, BuildRequest, BuildResolveRequest,
)
from probos.cognitive.builder_paths import operator_checkout_refusal
from probos.events import EventType
from probos.routers.deps import get_runtime, get_task_tracker
>>>>>>> REPLACE

### 5.2 Constants

<<<<<<< SEARCH
router = APIRouter(prefix="/api/build", tags=["build"])
=======
router = APIRouter(prefix="/api/build", tags=["build"])

# BF-897 (#1559): the checkout this runtime runs from (src/probos/routers -> repository).
_REPO_ROOT = Path(__file__).resolve().parents[3]
APPROVE_REFUSED = (
    "Approved builds do not run in the checkout ProbOS runs from (BF-897). "
    "Queue the build instead (/api/build/enqueue): it runs in its own worktree, "
    "and its branch is kept for delivery."
)
>>>>>>> REPLACE

### 5.3 `/approve` refuses

<<<<<<< SEARCH
@router.post("/approve")
async def approve_build(
    req: BuildApproveRequest,
    runtime: Any = Depends(get_runtime),
    track_task: Callable = Depends(get_task_tracker),
) -> dict[str, Any]:
    """Execute an approved build — write files, test, commit."""
    from probos.cognitive.builder import BuildSpec
    import pathlib

    spec = BuildSpec(
        title=req.title,
        description=req.description,
        ad_number=req.ad_number,
        branch_name=req.branch_name,
    )

    work_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)

    track_task(
        _execute_build(req.build_id, req.file_changes, spec, work_dir, runtime),
        name=f"execute-{req.build_id}",
    )

    return {
        "status": "started",
        "build_id": req.build_id,
        "message": "Executing approved build...",
    }
=======
@router.post("/approve")
async def approve_build(
    req: BuildApproveRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Refuse: an approved build never executes in the checkout ProbOS runs from (BF-897).

    This used to run ``execute_approved_build`` with ``work_dir`` set to the
    repository root, so the build created a branch, wrote files, ran pytest and
    committed in the operator's own checkout. Nothing here owns a worktree's
    lifecycle; AD-1336 child 5 (the build lane) replaces this refusal with a run in
    a governed worktree. The response keeps its keys; the HXI shows the reason from
    the ``build_failure`` event (``useStore.ts``, the branch without a report).
    """
    logger.warning("build approve refused build_id=%s: %s", req.build_id, APPROVE_REFUSED)
    runtime.emit_event(EventType.BUILD_FAILURE, {
        "build_id": req.build_id,
        "message": f"Build not executed: {APPROVE_REFUSED}",
        "error": APPROVE_REFUSED,
    })
    return {"status": "error", "build_id": req.build_id, "message": APPROVE_REFUSED}
>>>>>>> REPLACE

### 5.4 `/resolve` refuses a cached operator work tree

<<<<<<< SEARCH
    cached = _pending_failures[req.build_id]
    file_changes = cached["file_changes"]
    spec = cached["spec"]
    work_dir = cached["work_dir"]
=======
    cached = _pending_failures[req.build_id]
    file_changes = cached["file_changes"]
    spec = cached["spec"]
    work_dir = cached["work_dir"]

    # BF-897: abort and commit_override run git in work_dir, and a retry executes
    # there; never in the checkout ProbOS runs from.
    checkout_refusal = operator_checkout_refusal(work_dir, _REPO_ROOT)
    if checkout_refusal is not None:
        del _pending_failures[req.build_id]
        return {"status": "error", "message": checkout_refusal}
>>>>>>> REPLACE

## Section 6: `docs/development/self-maintenance-architecture.md`

<<<<<<< SEARCH
**Existing paths that patch the running checkout (constraint).**
`WorktreeManager.merge_to_main` checks out `main` and merges in the repository
root (`worktree_manager.py:143-169`), reached through
`BuildDispatcher.approve_and_merge` and `routers/build.py:158`;
`WorktreeManager.remove` uses `worktree remove --force` and `branch -D`
(`worktree_manager.py:105,112`); `routers/build.py:60` builds with the repository
root as `work_dir`. **AD-1299 work must never route through them.** A separate
BF is recommended; it is not filed by this rescope.
=======
**Paths that patched the running checkout (closed by BF-897, #1559).**
`WorktreeManager.merge_to_main` used to check out `main` and merge in the
repository root, and `/api/build/approve` (`routers/build.py`) used to build with
the repository root as `work_dir`. Both now refuse with a reason, and
`execute_approved_build` refuses any `work_dir` inside the checkout the runtime
started from (`builder_paths.operator_checkout_refusal`). `WorktreeManager.remove`
(`worktree remove --force`, `branch -D`) acts on the build's own worktree and
branch, not on the operator's checkout. **AD-1299 work must still never route
through `merge_to_main`;** delivery is the pull-request route (AD-1336 child 6).
>>>>>>> REPLACE

## Section 7: `DECISIONS.md`

<<<<<<< SEARCH
### BF-896 -- The queued visiting build runs in its own session directory under a deny-by-default permission policy, and its commit reaches review and approval (2026-10-16, #1550)
=======
### BF-897 -- The builder runs targeted tests only, and nothing in the build pipeline merges or executes in the operator's checkout (2026-10-16, #1559)

- *Scope.* Three defects that are reachable today. (1) The builder ran the whole suite (about 48K tests, 14-19 minutes) with `timeout=180` after the targeted tests passed, and with the targeted 60 s when nothing mapped, so every build with tests failed and the fix loop was asked to repair a timeout. (2) `WorktreeManager.merge_to_main` ran `git checkout main` and `git merge` in the checkout the runtime started from, reached through the Captain's queue approval. (3) `/api/build/approve` executed with `work_dir` set to the repository root, and `/resolve` then ran abort and commit_override there. Decided by the Architect (2026-10-16, Delegated AD Execution Mode); the rankings are in the contract.
- *D-a (tests).* No full-suite phase in the builder: it is the receipted gate's (AD-1336 child 2), recorded as `metadata["full_suite"] = "not_run"` at the one place a governed runner later replaces. With no mapped test nothing runs (`NO_TARGETED_TESTS`), the change is not committed and no fix is requested. A targeted timeout is `timed_out`, is not committed and requests no fix. Only `failed` enters the fix loop. No config field, so the default-config golden pin is unchanged. Rejected: a configured bound (a 15-20 minute in-process run per attempt, a second runner that child 2 would remove).
- *D-b (merge).* `merge_to_main` refuses with no git command, and the build stays in review with its branch and worktree, for delivery by pull request (AD-1336 child 6, AD-1299) or for rejection. Rejected: a merge in a linked worktree, because moving `refs/heads/main` moves the HEAD of an operator checkout that has `main` checked out.
- *D-c (execute).* `/api/build/approve` refuses before scheduling anything (response keys kept, reason in `build_failure`). `execute_approved_build` refuses any `work_dir` whose nearest `.git` entry is the runtime's own checkout (`builder_paths.operator_checkout_refusal`, filesystem only), and `/resolve` refuses a cached one. Rejected: running in a `WorktreeManager` worktree (that is child 5's lane: worktree lifecycle and delivery).
- *Recorded, not fixed.* When `native_swe_harness.enabled` (default False) is on, the AD-546 harness runs `write_file`, `edit_file` and `run_command` with `work_dir=_PROJECT_ROOT` during generation (`builder.py:2197-2203`, `swe_harness/native_builder.py:46-54`). `WorktreeManager.create` branches from the operator checkout's current HEAD, not from `main`. The queue-approve refusal is not shown in the HXI (the buttons ignore response bodies).
- Contract `prompts/bf-897-build-pipeline-scale-and-operator-checkout.md` (claude-architect).

### BF-896 -- The queued visiting build runs in its own session directory under a deny-by-default permission policy, and its commit reaches review and approval (2026-10-16, #1550)
>>>>>>> REPLACE

## Section 8: `PROGRESS.md`

<<<<<<< SEARCH
# ProbOS Progress

**AD-1328 slice S2c (2026-10-16), #1530 -- an approved escalated command now runs: a dispatched work item waits for the Captain's decision and resumes on approval; no new AD or BF number.**
=======
# ProbOS Progress

**BF-897 (2026-10-16), #1559 -- the builder runs targeted tests only, and nothing in the build pipeline merges or executes in the operator's checkout.** The full suite no longer runs inside a build: a run that could never finish in 180 s (or 60 s when no test mapped) had failed every build. It is the receipted gate's job and is reported as `not_run`. A change with no mapped test, or whose targeted tests time out, is not committed and gets no fix attempt. `merge_to_main` and `/api/build/approve` refuse with a reason. `execute_approved_build` and `/resolve` refuse a work tree inside the checkout ProbOS runs from. A reviewed queued build keeps its branch for delivery by pull request (AD-1336 child 6). Contract `prompts/bf-897-build-pipeline-scale-and-operator-checkout.md`.

**AD-1328 slice S2c (2026-10-16), #1530 -- an approved escalated command now runs: a dispatched work item waits for the Captain's decision and resumes on approval; no new AD or BF number.**
>>>>>>> REPLACE

**Roadmap Bug Tracker** (`docs/development/roadmap.md:1131-1145`): no row. That table lists only BFs that were filed but deliberately not fixed (BF-896 has no row either). The three "recorded, not fixed" items above go on #1559 as findings; the orchestrator files any of them as an issue.

---

## Tests

Builders write these. All are OS-independent:
- Paths use `pathlib`.
- Git runs with list arguments and `-C`.
- Each temporary repository sets `user.name`, `user.email` and `core.autocrlf=false` locally and is created with `git init -b main`.
- Mark real-git tests `@pytest.mark.skipif(shutil.which("git") is None, reason="git not found on PATH")`.
- Reuse the helper pattern of `tests/test_bf896_dispatcher_confinement_seam.py:64-133` (`_git`, `_out`, `_make_repo`, `_show`); copy it, do not import it from another test module.
- No test touches the real repository, and none relies on order: patch shared state with `monkeypatch`, including `monkeypatch.setitem` on `probos.api._pending_failures`.

**Shared premise, "the operator's checkout".** A temporary repository `op` on branch `captain-work`:
- `main` holds `src/probos/a.py` and `config/system.yaml`.
- `captain-work` is one commit ahead of `main`, and that commit touches only `src/probos/a.py`. This keeps `config/system.yaml` identical on both branches, so a mutant's `git checkout main` succeeds and is observable.
- `config/system.yaml` carries an uncommitted edit, and `notes.txt` is untracked.

Premise assertions: the branch is `captain-work`, and `status --porcelain` lists both entries.

`snapshot(op)` returns:
- the branch (`rev-parse --abbrev-ref HEAD`) and `rev-parse HEAD`;
- `rev-parse main`;
- `status --porcelain=v1 -uall`;
- the bytes of `config/system.yaml` and `notes.txt`;
- `stash list`;
- the sorted output of `for-each-ref --format=%(refname) refs/heads`.

`checkout_state(op)` is the same without the ref list. Use it where a test legitimately creates branches in the shared repository.

### New file `tests/test_bf897_build_pipeline_scale_and_checkout.py`

**T-A1: `operator_checkout_refusal` (real directories, real `git worktree add`)**
1. `test_refuses_the_operator_checkout_itself`: `operator_checkout_refusal(op, op)` is a string containing "BF-897".
2. `test_refuses_a_subdirectory_of_the_operator_checkout`: `op / "src"` is refused, and so is `str(op / "src" / "..")`.
3. `test_allows_a_linked_worktree_outside_the_checkout` (control): `git -C op worktree add -b wt-out <tmp>/wts/out main`, then `None`.
4. `test_allows_a_linked_worktree_nested_inside_the_checkout` (control, kills M2): `git -C op worktree add -b wt-in <op>/.wt/in main`. The result for it and for its `src` subdirectory is `None`.
5. `test_allows_a_tree_outside_any_checkout` (control): a plain `tmp_path / "plain"` gives `None`.
6. `test_no_checkout_means_nothing_to_protect`: when `operator_root` has no `.git` entry, the result is `None` even for `operator_root` itself.
7. `test_an_unexaminable_path_is_refused`: monkeypatch `probos.cognitive.builder_paths.os.path.samefile` to raise `PermissionError`. The result is a refusal naming `PermissionError`.

**T-A2: `execute_approved_build` refuses the operator checkout (data integrity, kills M1 and M3)**
8. `test_execute_refuses_the_operator_checkout_and_leaves_it_unchanged`: `monkeypatch.setattr(builder_module, "_PROJECT_ROOT", op)`, then `before = snapshot(op)`. Call `execute_approved_build([{"path": "src/probos/new_mod.py", "mode": "create", "content": "x = 1\n"}], BuildSpec(title="bf897", description="d"), str(op), run_tests=False)`. Assert `success is False`, `"BF-897" in result.error`, `not (op/"src/probos/new_mod.py").exists()` and `snapshot(op) == before`. In the same test, call with `work_dir=str(op / "src")`: refused, and the snapshot is still unchanged. **Clean variant (required):** repeat with `op_clean`, the same premise without the uncommitted edit and the untracked file. The dirty-tree refusal (`builder.py:2673-2678`) then cannot stand in for the guard: without the guard the build would create a branch, commit and `git checkout main` there. Assert `"BF-897" in result.error` and `snapshot(op_clean) == before`. This variant is what kills M3 by snapshot as well as by message.
9. `test_execute_refusal_runs_no_git` (premise for the "before any git command" claim): with `_PROJECT_ROOT` patched as above, patch `probos.cognitive.builder.subprocess.run` with a `MagicMock` and `probos.cognitive.builder.asyncio.create_subprocess_exec` with an `AsyncMock`. After the refused call, both have no calls.

**T-A3: control, a linked worktree of the same repository builds normally**
10. `test_execute_runs_in_a_linked_worktree_and_the_operator_checkout_is_unchanged`: `wt = git -C op worktree add -b builder-bf897 <tmp>/wts/b main`, then `before = checkout_state(op)` with `_PROJECT_ROOT` patched to `op`. `execute_approved_build(..., str(wt), run_tests=False)` gives `success is True` and a non-empty `commit_hash`, and the file exists in `wt`. `git -C op cat-file -e <commit_hash>` succeeds, and `checkout_state(op) == before`. This proves the guard does not over-refuse, and the branch, HEAD and uncommitted edits survive a real build in the shared repository.

**T-A4: `merge_to_main` refuses and runs no git (kills M4)**
11. `test_merge_to_main_refuses_runs_no_git_and_keeps_the_branch`:
    - Setup: `mgr = WorktreeManager(repo_root=str(op), worktree_base=str(tmp/"wts"))` and `info = await mgr.create("bf897build01")`. Commit a change to `src/probos/a.py` on `info.branch` inside `info.path` (git with `cwd=info.path`), then `before = snapshot(op)`.
    - Spy: `monkeypatch.setattr(mgr, "_run_git", spy)`, where the spy records its calls and delegates.
    - Act: `ok, reason = await mgr.merge_to_main("bf897build01")`.
    - Assert: `ok is False`; `"BF-897"`, `info.branch` and `info.path` are in `reason`; the spy has no calls; `snapshot(op) == before` (the `main` sha and `captain-work` HEAD are unchanged); `git -C op rev-list --count main..<info.branch> == "1"`; `mgr.get("bf897build01") is info`.
12. `test_merge_to_main_unknown_build`: `(False, "unknown build_id")`.

**T-C: the test phase (fake runner, standard)**
13. `test_no_mapped_tests_runs_nothing`: `tmp/tests/` exists with `test_other.py`. Patch `probos.cognitive.builder.subprocess.run` with `MagicMock(side_effect=AssertionError("pytest ran"))`. `await _run_targeted_tests(str(tmp), ["src/probos/zz_unmapped.py"])` returns `(False, NO_TARGETED_TESTS, [])`. Repeat with no `tests/` directory at all.
14. `test_targeted_timeout_output_is_classified_timed_out`: `tmp/tests/test_foo.py` exists. Patch `subprocess.run` with `side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=60)`. The output of `_run_targeted_tests(str(tmp), ["src/probos/foo.py"], timeout=60)` starts with `"pytest timed out after"`, and `_classify_test_run(False, output) == "timed_out"`. The same holds for `_run_tests(str(tmp), timeout=5)` (the prefix is shared).
15. `test_classify_test_run_table`:
    - `(True, "x")` gives `passed`.
    - `(False, "1 failed")` gives `failed`.
    - `(False, "pytest timed out after 60s")` gives `timed_out`.
    - `(False, NO_TARGETED_TESTS)` gives `not_run`.
    - `(False, "FAILED t.py - pytest timed out after 3s")` gives `failed` (the prefix must lead).
    - `(False, NO_TARGETED_TESTS + "\nmore")` gives `failed`.
16. `test_full_suite_never_runs_and_is_reported_not_run` (kills M8):
    - Patch `_run_targeted_tests` to return `(True, "1 passed", ["tests/test_x.py"])`. The non-empty file list is the old phase-2 premise.
    - Patch `_run_tests` as an `AsyncMock`, and patch the git helpers as in `tests/test_builder_agent.py:3113-3118`.
    - Assert: `success` and `tests_passed`; `_run_tests` not awaited; `result.metadata["full_suite"] == "not_run"`; `result.metadata["targeted_tests"] == "passed"`.
17. `test_targeted_phase_uses_the_targeted_budget`: a `side_effect` records `timeout`, and it equals `TARGETED_TEST_TIMEOUT_S == 60`.
18. `test_targeted_timeout_requests_no_fix_and_is_not_committed` (kills M9):
    - Patch `_run_targeted_tests` to return `(False, "pytest timed out after 60s", ["tests/test_x.py"])`. Pass an `llm_client` whose `complete` returns a valid `===MODIFY:` block, and `max_fix_attempts=2`.
    - Assert: `_run_targeted_tests` awaited once; no prompt containing "Test Fix Required" (count the prompts in `llm_client.complete.await_args_list`); `fix_attempts == 0`; `success is False`; `result.error.startswith("Targeted tests timed out")`; `_git_add_and_commit` not awaited; `metadata["targeted_tests"] == "timed_out"`.
    - Control in the same test, with a fresh `tmp_path` subdirectory: the output `"1 failed"` leads to 3 awaits and 2 fix prompts.
19. `test_untested_change_requests_no_fix_and_is_not_committed`: the same with `(False, NO_TARGETED_TESTS, [])`. Assert `error.startswith("No targeted tests ran")`, one await, no fix prompt and no commit.
20. `test_a_real_failure_still_says_tests_failed`: with `(False, "1 failed", [])` and `max_fix_attempts=0`, `"Tests failed after 0 fix attempt(s)"` is in `result.error`.

**T-B: routers (real router through `create_app`)**
21. `test_resolve_refuses_a_cached_operator_checkout` (kills M7):
    - Setup: monkeypatch `probos.routers.build._REPO_ROOT` to `op`. Build the app with `rt = MagicMock(spec=ProbOSRuntime)` and `TestClient(create_app(rt))`, the `tests/test_dispatch_wiring.py:138-142` pattern.
    - For each `resolution` in `("abort", "commit_override")`:
      - Seed `monkeypatch.setitem(probos.api._pending_failures, "bf897r", {"file_changes": [], "spec": BuildSpec(title="t", description="d"), "work_dir": str(op), "report": BuildFailureReport(files_modified=["config/system.yaml"]), "timestamp": time.time()})`.
      - Take `before = snapshot(op)` and POST `/api/build/resolve`.
      - Assert: `status == "error"`; `"BF-897"` is in the message; `"bf897r" not in probos.api._pending_failures`; `snapshot(op) == before`. The old abort would switch `op` to `main`, and the old override would commit `config/system.yaml`.

### Changes to existing tests (update in place; record why inline; never delete)

| File and test | Today | Change |
|---|---|---|
| `tests/test_builder_api.py::TestBuildApproveEndpoint::test_approve_returns_started` (line 139) | Pins `status == "started"`. It schedules a real execute in the real repository root | **Seam test of record for D-c.** Rename to `test_approve_is_refused_and_executes_nothing`. Patch `probos.cognitive.builder.execute_approved_build` with an `AsyncMock` and capture `rt._emit_event` (the pattern at lines 283-290). Assert: `status == "error"`; `build_id == "test123"`; the message is `routers.build.APPROVE_REFUSED`; the executor mock is not awaited; no `asyncio` task named `execute-test123` exists; a `build_failure` event carries `build_id` and a message containing "BF-897". Kills M6. Inline: "BF-897 (#1559): approval used to execute in the repository root." |
| `tests/test_builder_api.py::TestExecuteBuildEvents::test_emits_build_success` (276) and `::test_emits_build_failure` (322) | Drive `_execute_build` through `/approve` | Call `probos.routers.build._execute_build(build_id, changes, spec, str(tmp_path), rt)` directly, with the same `execute_approved_build` patch and event capture. `_execute_build` is still the `/resolve` retry's path. Inline reason. |
| `tests/test_bf896_dispatcher_confinement_seam.py::test_an_approved_queued_build_lands_the_generated_commit_on_main` (691) | Pins the merge into the repository | **Seam test of record for D-b.** Rename to `test_an_approved_queued_build_is_refused_and_keeps_its_branch_for_delivery`. Keep lines 694-721 as they are. Then, before approval, write an uncommitted edit to `repo / _B` and take `before = (rev-parse main, rev-parse --abbrev-ref HEAD, status --porcelain, bytes of _B)`. After `approve_and_merge`, assert: `approved is False`; `"BF-897" in detail`; `build.status == "reviewing"`; that tuple is unchanged; `_show(repo, "main", _A) == _A_V1`; `rev-parse real.branch == before_adoption["executor_sha"]`; `_worktree_entries(repo) == 2`. Then restore `_B`, call `reject_build`, and assert `_branches(repo) == ["main"]` and `_worktree_entries(repo) == 1`. Kills M4 and M5. Inline: "BF-897 (#1559): this repository stands for the operator's checkout; approval used to merge here." |
| `tests/test_builder_agent.py::TestEscalationHook::test_hook_not_called_on_success` (3102) | Patches `_run_tests` returning "2254 passed" (phase 2) | Keep the patch as `AsyncMock` and add `assert not mock.await_count`. Inline: the full suite no longer runs in the builder. |
| `tests/test_builder_guardrails.py::TestBranchLifecycle::test_failed_build_deletes_branch` (156, patch at 195) and `::TestUntrackedFileCleanup::test_untracked_files_cleaned_on_failure` (253, patch at 289) | Patch `_run_tests` (False, "FAILED"). The patch is reached only through the removed fallback | Patch `probos.cognitive.builder._run_targeted_tests` to return `(False, "FAILED", [])` instead, so the premise stays "tests failed". Inline reason. |

New tests in existing files:
- `tests/test_build_dispatcher.py::test_approve_and_merge_refusal_keeps_the_build_in_review` (kills M5). Mock `wm.merge_to_main` to return `(False, "Not merged (BF-897): ...")`. Assert: `(False, reason)` is returned; `build.status == "reviewing"`; `build.error == ""`; `wm.remove` not awaited. Then `await d.reject_build(build.id)` returns `True`, and the status is `failed`.

Unchanged, and they must stay green (verify; do not edit):
- `tests/test_build_dispatcher.py::test_approve_and_merge` (the mocked ok path);
- `tests/test_dispatch_wiring.py` (mocked dispatcher);
- `tests/test_bf892_spawn_env.py` (`_run_tests` and `_run_targeted_tests` with a mapped test);
- the `tests/test_bf896_executor_identity_and_blocks.py` and `tests/test_bf894_builder_write_boundary.py` repair tests ("1 failed" is still `failed`);
- `tests/test_builder_agent.py` `TestTestFixLoop` and `TestCommitGate` ("Tests failed" is still the lead for a failure);
- `tests/test_ad1152_agentic_correlation.py` (no config field is added).

### Focused gate (per milestone)

`d:/ProbOS/.venv/Scripts/pytest.exe -n 0 -q` on these files:
- `tests/test_bf897_build_pipeline_scale_and_checkout.py`
- `tests/test_builder_agent.py`
- `tests/test_builder_guardrails.py`
- `tests/test_builder_api.py`
- `tests/test_build_dispatcher.py`
- `tests/test_dispatch_wiring.py`
- `tests/test_bf896_dispatcher_confinement_seam.py`
- `tests/test_bf896_executor_identity_and_blocks.py`
- `tests/test_bf894_builder_write_boundary.py`
- `tests/test_bf892_spawn_env.py`
- `tests/test_ad1152_agentic_correlation.py`

The broad gate runs once, in the main session, per the orchestrator.

## Mutation rows (data-integrity rows M1-M7; standard rows M8-M9)

Apply each mutant alone to the built tree and run the focused file named. Each must fail; restore the tree afterwards.

| Row | File | Mutant | Must be killed by |
|---|---|---|---|
| M1 | `builder_paths.py` | `if os.path.samefile(candidate, root):` becomes `if False:` | T-A1 #1, #2; T-A2 #8 |
| M2 | `builder_paths.py` | the inner `return None` (after a non-operator `.git`) becomes `continue` | T-A1 #4 |
| M3 | `builder.py` | delete the 0a guard block in `execute_approved_build` | T-A2 #8 |
| M4 | `worktree_manager.py` | restore the old `merge_to_main` body (checkout, merge, rev-parse) | T-A4 #11; the D-b seam |
| M5 | `build_dispatcher.py` | restore `update_status(build_id, "failed", error=f"Merge failed: {result}", ...)` in the else branch | `test_approve_and_merge_refusal_keeps_the_build_in_review`; the D-b seam |
| M6 | `routers/build.py` | restore the `track_task(_execute_build(... work_dir ...))` in `/approve` | the D-c seam (`test_approve_is_refused_and_executes_nothing`) |
| M7 | `routers/build.py` | delete the `/resolve` guard | T-B #21 |
| M8 | `builder.py` | re-insert phase 2 (`if passed and _targeted_files: passed_full, full_output = await _run_tests(work_dir, timeout=180) ...`) | T-C #16; `test_hook_not_called_on_success` |
| M9 | `builder.py` | `if test_outcome != "failed":` becomes `if False:` | T-C #18, #19 |

The campaign of record is the Builder's, on the frozen candidate. Record the base tree and the sha256 of each of the five source files. A file that later differs reruns its own rows only.

## Hidden pins (grep each before editing; each is handled above)

- `grep -rn "status\"\] == \"started\"" tests/test_builder_api.py`: lines 116 and 134 (`/submit`, unchanged) and 152 (`/approve`, changed).
- `grep -rn "/api/build/approve" tests/`: `test_builder_api.py:141, 306, 349` (all three changed).
- `grep -rn "merge_to_main\|approve_and_merge" tests/`: `test_build_dispatcher.py:250-270` (unchanged ok path), `test_bf896_dispatcher_confinement_seam.py:723-730` (changed), `test_dispatch_wiring.py:22,115-122` (mocked, unchanged).
- `grep -rn "builder._run_tests" tests/`: `test_builder_agent.py:3114`, `test_builder_guardrails.py:195,289` (all changed).
- `grep -rn "Tests failed" tests/`: `test_builder_agent.py:2638`, `test_bf896_executor_identity_and_blocks.py:652` (both "1 failed", which is still the "Tests failed" lead; unchanged).
- `grep -rn "timed out after" tests/test_builder_agent.py`: lines 2874 and 2930 build `BuildResult(test_result="pytest timed out after 120s")` for `classify_build_failure` (unchanged; the category is still `timeout`).
- `grep -rn "Merge failed\|checkout main failed\|merge failed" tests/`: none.
- Docs that cite the old behaviour: `docs/development/self-maintenance-architecture.md:102-109` (Section 6). `decisions-era-4-evolution.md:97` (AD-344, "full suite only if targeted pass (180s)") is history and is not edited; the BF-897 entry supersedes it.

## What this does not change

- The BF-896 Copilot SDK route: `BuildDispatcher._execute_build` (`build_dispatcher.py:150-358`), the adapter, the session directory, the identity pin and `adopt_commit`. Its test phase is now targeted-only, as #1559 requires.
- `config/system.yaml` and every config model. No field is added.
- `WorktreeManager.create`, `remove`, `collect_diff`, `adopt_commit` and `cleanup_all`. `remove` acts on `info.path` and `info.branch`, the build's own, so it stays out of scope as the issue says.
- `classify_build_failure` and `BuildFailureReport`; `BuildResult` gains no field (`metadata` is the existing dict, `builder.py:138`).
- `_run_tests` (kept, with no production caller); `_map_source_to_tests`; the fix-loop body.
- `/api/build/queue/approve`'s response (`{"status":"error","message":...}` on refusal, already the shape); `/submit`, `/enqueue`, `/queue` and `/queue/reject`.
- Generation-phase reads of `_PROJECT_ROOT` (transporter, perceive), and the opt-in AD-546 harness (recorded, not fixed).
- Anything AD-1328 owns.
- HXI code. The consumers are `IntentSurface.tsx:924` (it ignores the body; the outcome comes from events), `useStore.ts:3807-3818` (`build_failure` without `report` shows `data.message`), and `FullKanban.tsx:74` and `IntentSurface.tsx:2063` (they ignore the queue-approve body). The `BuildResult` readers are `routers/build.py:403-419` (fields unchanged), `build_dispatcher.py:223-287` (`branch_name`, `commit_hash`, `success`, `error`) and `routers/build.py:226,253` (`commit_hash`).

## Tracking

- `DECISIONS.md`: Section 7. The orchestrator appends the review and evidence line at closure.
- `PROGRESS.md`: Section 8.
- `docs/development/roadmap.md` Bug Tracker: no row (see Section 8).
- `docs/development/self-maintenance-architecture.md`: Section 6.
- #1559: the D-a/D-b/D-c rankings, and the three recorded findings (the AD-546 harness writing in `_PROJECT_ROOT` when enabled, `create` branching from the operator's HEAD, the invisible queue-approve refusal).

## Acceptance criteria

- [ ] The targeted phase stays, with a 60 s budget. No build path runs the full suite. `metadata["full_suite"] == "not_run"` whenever tests ran.
- [ ] With no mapped test nothing runs, the change is not committed, and no fix is requested.
- [ ] A targeted timeout is `timed_out`: not committed, no fix requested, and the error says it timed out.
- [ ] `merge_to_main` runs no git command and returns `(False, reason)`. The operator's checkout keeps its branch, its HEAD, `main`, its uncommitted and untracked files and its stash (real git, T-A4 #11 and the D-b seam).
- [ ] `/api/build/approve` schedules nothing and returns `{"status":"error","build_id","message"}` with a `build_failure` event. `execute_approved_build` and `/resolve` refuse a work tree inside the runtime's checkout and leave it unchanged (T-A2 #8, T-B #21). A linked worktree still builds (T-A3 #10).
- [ ] Every SEARCH block applies exactly once to `2400b14c`. M1-M9 are each killed.
- [ ] The default-config golden pin `tests/test_ad1152_agentic_correlation.py` passes unchanged.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior art and blind spots

- **Prior art.** Skipped: this is a bug fix in ProbOS-specific plumbing, so the prior-art review in the drafting standard does not apply and `docs/research/reference-projects.md` was not consulted (date used: 2026-10-16). Git's own semantics are the design input: a repository is found at the nearest `.git` entry, and a linked worktree's `.git` is a pointer file. A branch checked out in one worktree cannot be checked out in another, and moving a ref moves the HEAD of every worktree that has it checked out. Those semantics decided D-b, and the filesystem-only discovery decided the guard.
- **Blind spots found and absorbed:**
  - `/resolve` acted on the cached root `work_dir`: absorbed as Section 5.4.
  - `test_approve_returns_started` scheduled a real execute against the real repository root in a clean checkout: absorbed, because that test becomes the D-c seam.
  - A `subprocess.run`-based guard would have collided with the existing tests that patch `subprocess.run` with `stdout=b"main\n"` and made both identities equal: absorbed by a filesystem-only guard.
- **Considered, deferred:**
  - The AD-546 harness writing in `_PROJECT_ROOT` when enabled (opt-in, touches `run_command`, AD-1328's).
  - `create` branching from the operator's current HEAD (child 5).
  - The invisible queue-approve refusal (child 6).
  - A `not_run` category in `classify_build_failure` (unreachable after this change).
  - Deleting `_run_tests` (it carries the BF-892 tests).

## Verified Against Codebase (2026-10-16, worktree at `origin/main` `2400b14c`)

```
grep -n "merge_to_main|approve_and_merge|execute_approved_build|_run_tests\(|_run_targeted_tests\(|WorktreeManager\(" src/
  build_dispatcher.py:215: build_result = await execute_approved_build(
  build_dispatcher.py:218:     work_dir=worktree_info.path,
  build_dispatcher.py:379: async def approve_and_merge(self, build_id: str) -> tuple[bool, str]:
  build_dispatcher.py:388: ok, result = await self._worktree_mgr.merge_to_main(build_id)
  build_pipeline.py:56: async def execute_approved_build(   (delegates at :89; no caller, see below)
  cognitive/builder.py:2425: async def _run_tests(work_dir: str, timeout: int = 120)
  cognitive/builder.py:2487: async def _run_targeted_tests(
  cognitive/builder.py:2501: passed, output = await _run_tests(work_dir, timeout=timeout)
  cognitive/builder.py:2627: async def execute_approved_build(
  cognitive/builder.py:2877: passed, test_output, targeted_files = await _run_targeted_tests(
  cognitive/builder.py:2885: passed_full, full_output = await _run_tests(work_dir, timeout=180)
  worktree_manager.py:146: async def merge_to_main(self, build_id: str) -> tuple[bool, str]:
  routers/build.py:158: ok, result = await runtime.build_dispatcher.approve_and_merge(req.build_id)
  routers/build.py:394: result = await execute_approved_build(
  startup/structural_services.py:112: _worktree_mgr = WorktreeManager(repo_root=_repo_root)
Read worktree_manager.py:53       work_dir = cwd or str(self._repo_root)
Read worktree_manager.py:157,162  _run_git("checkout", "main"); _run_git("merge", info.branch, "--no-edit")
Read routers/build.py:60          work_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
Read routers/build.py:89-114      /resolve: work_dir = cached["work_dir"]; _git_checkout_main(work_dir); _git_add_and_commit(..., work_dir)
Read builder.py:41                _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
Read builder.py:138               metadata: dict[str, Any] = field(default_factory=dict)
Read builder.py:2445-2446         except subprocess.TimeoutExpired: return 1, f"pytest timed out after {timeout}s"
Read builder.py:2673-2678         dirty-tree refusal; builder.py:3049 await _git_checkout_main(work_dir)
Read builder.py:219               if "timed out after" in combined: report.failure_category = "timeout"
Read build_queue.py:25            "reviewing": {"merged", "failed"}   (no reviewing->reviewing; the refusal makes no transition)
Read build_dispatcher.py:49       run_tests: bool = True; structural_services.py:113-117 passes none
Read ui/src/components/IntentSurface.tsx:924-934   fetch('/api/build/approve', ...) with the body ignored
Read ui/src/store/useStore.ts:3807-3818            build_failure: report or the legacy data.message
Read ui/src/components/bridge/FullKanban.tsx:74; IntentSurface.tsx:2063   queue/approve with the body ignored
Read runtime.py:2097              "build_failure": "build_failure" (Night Orders trigger)
Read config.py:3133-3135          NativeSWEHarnessConfig.enabled default=False
gh issue view 1559                "BF-897: the native build pipeline cannot pass its own tests ..." OPEN
```

## Absence Verified (2026-10-16)

| Claim | Run | Found | Holds |
|---|---|---|---|
| Nothing else calls `merge_to_main` | grep `merge_to_main` in `src/` | `build_dispatcher.py:388` (plus a docstring at `worktree_manager.py:178`) | yes |
| Nothing calls `BuildPipeline.execute_approved_build` | grep `BuildPipeline\(\|\.execute_approved_build\(` in `src/` | `runtime.py:3497` (constructs it only); no `.execute_approved_build(` call | yes |
| `_run_tests` has no production caller after this change | grep `_run_tests\(` in `src/` | `builder.py:2501` and `2885`, both removed here | yes |
| `_pending_failures` is written only by the router's `_execute_build` | grep `_pending_failures` in `src/` | `api.py:48,55,57` (define and clean), `routers/build.py:426` (the only write) | yes |
| Only one `WorktreeManager(` in production | grep `WorktreeManager\(` in `src/` | `structural_services.py:112` | yes |
| `cleanup_all` has no caller | grep `cleanup_all\(` in `src/` | `worktree_manager.py:231` (the definition only) | yes |
| No existing executor test passes the project root as `work_dir` | grep `_PROJECT_ROOT\|work_dir="\."\|Path\.cwd\(\)` in the builder test files | `test_bf896_session_permission_handler.py:882` and `test_bf896_executor_identity_and_blocks.py:1046` (neither is a `work_dir`) | yes |
| No HXI caller reads the `/approve` or `/queue/approve` body | grep `build/approve\|queue/approve` in `ui/src` | `IntentSurface.tsx:924,2063`, `FullKanban.tsx:74`, all `await fetch(...)` with the result discarded | yes |
| No test pins "Merge failed" | grep `Merge failed\|merge failed\|checkout main failed` in `tests/` | none | yes |
