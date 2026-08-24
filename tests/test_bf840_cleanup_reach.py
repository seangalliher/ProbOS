"""BF-840: sandbox scratch cleanup reaches the callers BF-788 did not.

BF-788 (#1252) replaced the one-shot ``shutil.rmtree(path, ignore_errors=True)``
with a retry-and-warn removal, but only for ``CodeExecutionTool``. Three other
SANDBOX-WORKDIR cleanup sites kept the original shape, and are covered here:

    src/probos/agents/code_runner.py       (CodeRunnerAgent._reap)
    src/probos/cognitive/skill_forge.py    (SkillForge._smoke_test finally)
    src/probos/execution/isolation.py      (the generated-workdir branch)

The same one-shot shape survives elsewhere on directories that are not sandbox
scratch and are deliberately out of scope: SkillForge's staging tree, and the
visiting-builder temp tree tracked as #1314.

Reproduced before the fix, with a live child holding a file under the target::

    CHILD_LIVE=True
    ONESHOT_RMTREE_WHILE_HELD  survived=True   (no exception, no warning)
    CHILD_EXITED=True
    AFTER_CHILD_EXIT           survived=True   <- the leak
    AFTER__remove_workdir      survived=False

The directory was still there after the child had gone, because nothing
retried.

Two things adversarial review corrected, both pinned here:

* The generated-workdir branch is NOT dead. ``ExecutionRequest.workdir``
  defaults to ``None`` and ``SubprocessSandbox`` is exported, so the branch
  belongs to any caller that lets the sandbox choose. Every in-repo production
  caller happens to pass one today, but "no caller in this repo" is not "dead".
* Both agent-side cleanups run in a ``finally`` on the EVENT LOOP. Doing the
  retry synchronously there freezes every other task -- measured at a 0.250s
  heartbeat gap for a 0.25s sleep, so the real ~9s budget would stall the loop
  for ~9s. They now go off-loop.

Scope: this does not change WHICH side owns removal when a run is cancelled --
that is #1305 (BF-839). It does mean these finalizers now retry, and they do
still execute under cancellation, so this is not a "non-cancelled path only"
change; it is an ownership-unchanged one.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from probos.agents.code_runner import CodeRunnerAgent
from probos.cognitive import skill_forge as skill_forge_module
from probos.execution import isolation as iso
from probos.execution.isolation import (
    ExecutionRequest,
    ExecutionResult,
    SubprocessSandbox,
    _still_present,
    remove_workdir,
)


def _make_dir(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir()
    (d / "payload.txt").write_text("data", encoding="utf-8")
    return d


class _StubbornRmtree:
    """A ``rmtree`` that refuses ``fail_times`` times, then really removes.

    Stands in deterministically for the real cause -- a Windows child still
    holding the directory. ``ignore_errors=True`` means the real ``rmtree``
    reports nothing when it fails, so refusing is a silent no-op, exactly like
    the production failure.

    The real callable is captured at construction: ``iso.shutil`` IS the
    ``shutil`` module, so patching it and then calling ``shutil.rmtree`` from
    here would re-enter this stub and recurse.
    """

    def __init__(self, fail_times: int) -> None:
        self._remaining = fail_times
        self._real = shutil.rmtree
        self.calls = 0

    def __call__(self, path: Any, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            return
        self._real(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# CodeRunnerAgent._reap
# ---------------------------------------------------------------------------

async def test_reap_retries_until_a_held_directory_can_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: the first two removals are silent no-ops, as when a child holds it.
    target = _make_dir(tmp_path, "held")
    stubborn = _StubbornRmtree(fail_times=2)
    monkeypatch.setattr(iso.shutil, "rmtree", stubborn)
    monkeypatch.setattr(iso.time, "sleep", lambda _s: None)  # keep the test fast

    # Act
    await CodeRunnerAgent._reap(target)

    # Assert: gone, and it took more than one attempt. A one-shot rmtree would
    # have called once and left the directory behind.
    assert not _still_present(target)
    assert stubborn.calls >= 3


def test_a_single_rmtree_is_genuinely_defeated_by_the_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counter-case: proves the retry is what does the work.

    Without this, the test above would still pass if the stub were somehow
    ineffective and the first attempt had simply succeeded.
    """
    # Arrange
    target = _make_dir(tmp_path, "held")
    stubborn = _StubbornRmtree(fail_times=2)
    monkeypatch.setattr(iso.shutil, "rmtree", stubborn)

    # Act: one attempt, the pre-BF-840 shape.
    iso.shutil.rmtree(target, ignore_errors=True)

    # Assert
    assert _still_present(target)
    assert stubborn.calls == 1


async def test_reap_warns_with_the_path_when_it_cannot_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Arrange: never removable, the pathological case.
    target = _make_dir(tmp_path, "stuck")
    monkeypatch.setattr(iso.shutil, "rmtree", _StubbornRmtree(fail_times=10_000))
    monkeypatch.setattr(iso.time, "sleep", lambda _s: None)

    # Act
    with caplog.at_level(logging.WARNING, logger=iso.logger.name):
        await CodeRunnerAgent._reap(target)  # must not raise out of a `finally`

    # Assert: still there, but the operator is told -- from THIS logger, naming
    # the path, and saying it MAY remain. A bare "some warning happened"
    # assertion would pass on an unrelated record.
    assert _still_present(target)
    ours = [
        r for r in caplog.records
        if r.name == iso.logger.name and r.levelno >= logging.WARNING
    ]
    assert ours, f"expected a warning from {iso.logger.name}; got {caplog.records!r}"
    joined = " ".join(r.getMessage() for r in ours)
    assert str(target) in joined, "the warning must name the directory"
    assert "may remain" in joined.lower(), (
        "the warning must say the directory MAY remain -- it is a "
        "point-in-time observation, and a concurrent remover can still "
        "succeed afterwards, so a flat 'it is left on disk' can go stale"
    )


async def test_reap_removes_a_free_directory(tmp_path: Path) -> None:
    """The common path must still work."""
    # Arrange
    target = _make_dir(tmp_path, "free")

    # Act
    await CodeRunnerAgent._reap(target)

    # Assert
    assert not _still_present(target)


async def test_reap_is_unbothered_by_a_directory_that_is_already_gone(
    tmp_path: Path,
) -> None:
    # Arrange
    target = tmp_path / "never-existed"

    # Act / Assert: a `finally` must never raise on a path that isn't there.
    await CodeRunnerAgent._reap(target)
    assert not _still_present(target)


# ---------------------------------------------------------------------------
# Off-loop behaviour (the event loop must keep running)
# ---------------------------------------------------------------------------

async def test_cleanup_does_not_freeze_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retrying removal must not stall every other task.

    Pins the reason this is off-loop: done synchronously, the heartbeat gap
    equals the whole retry budget.
    """
    # Arrange: a removal that takes a visible amount of wall time.
    target = _make_dir(tmp_path, "slow")
    real = shutil.rmtree

    def slow_rmtree(path: Any, *a: Any, **k: Any) -> None:
        import time as _t
        _t.sleep(0.30)
        real(path, ignore_errors=True)

    monkeypatch.setattr(iso.shutil, "rmtree", slow_rmtree)

    beats: list[float] = []

    async def heartbeat() -> None:
        loop = asyncio.get_running_loop()
        while True:
            beats.append(loop.time())
            await asyncio.sleep(0.01)

    hb = asyncio.create_task(heartbeat())
    try:
        # Act
        await CodeRunnerAgent._reap(target)
    finally:
        hb.cancel()

    # Assert
    assert not _still_present(target)
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert gaps, "the heartbeat never ran"
    assert max(gaps) < 0.25, (
        f"event loop stalled for {max(gaps):.3f}s during cleanup; it must run "
        "off-loop"
    )


async def test_cleanup_still_happens_when_the_task_is_cancelled(
    tmp_path: Path,
) -> None:
    """A single cancellation must not lose the cleanup.

    Note this case alone does NOT discriminate the implementation -- every
    shape survives one cancellation. See the double-cancellation test below.
    """
    # Arrange
    target = _make_dir(tmp_path, "cancelled")

    async def body() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            await CodeRunnerAgent._reap(target)

    task = asyncio.create_task(body())
    await asyncio.sleep(0.05)

    # Act
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(50):  # let the executor land
        if not _still_present(target):
            break
        await asyncio.sleep(0.02)

    # Assert
    assert not _still_present(target)


async def test_a_second_cancellation_cannot_skip_the_cleanup(
    tmp_path: Path,
) -> None:
    """The case that actually discriminates the implementation.

    A SINGLE cancellation is survived by every shape, so mutants substituting
    ``to_thread`` and dropping the ``shield`` both survived a single-cancel
    test. The discriminating case is a second cancellation arriving while the
    removal is still QUEUED: without the shield it cancels the future before
    the worker starts, and the directory is never removed.

    What this pins is the SHIELD. Measured separately, ``shield(to_thread(...))``
    also survives -- so this does not prove that submitting before awaiting is
    necessary, only that shielding is. The executor is deliberately saturated
    so "still queued" is deterministic rather than a race.
    """
    # Arrange
    target = _make_dir(tmp_path, "double")
    loop = asyncio.get_running_loop()
    # Capture the loop's real default so it can be RESTORED, not merely
    # replaced: installing a fresh pool would leave the original alive and
    # un-shut-down, which is only harmless while loops are function-scoped.
    previous_executor = getattr(loop, "_default_executor", None)
    pool = ThreadPoolExecutor(max_workers=1)
    release = threading.Event()
    entered = asyncio.Event()

    async def body() -> None:
        try:
            await asyncio.sleep(10)
        finally:
            entered.set()
            await CodeRunnerAgent._reap(target)

    try:
        loop.set_default_executor(pool)
        # Occupy the only worker, so the cleanup job must wait in the queue.
        blocker = loop.run_in_executor(pool, release.wait)

        task = asyncio.create_task(body())
        await asyncio.sleep(0.05)
        task.cancel()             # first: unwinds into the `finally`
        await entered.wait()      # the finally has begun; the job is submitted

        # Act: second cancellation, landing on the await inside the `finally`.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        release.set()             # free the worker; the queued job may run now
        await blocker
        for _ in range(100):
            if not _still_present(target):
                break
            await asyncio.sleep(0.02)

        # Assert
        assert not _still_present(target), (
            "a second cancellation skipped the cleanup: the removal must be "
            "shielded from cancellation"
        )
    finally:
        release.set()
        if isinstance(previous_executor, ThreadPoolExecutor):
            loop.set_default_executor(previous_executor)
        else:
            # There was no default executor yet -- the loop makes one lazily.
            # Clear ours rather than leaving a shut-down pool installed, and
            # rather than inventing a replacement the loop never had.
            loop._default_executor = None  # type: ignore[attr-defined]
        pool.shutdown(wait=False)


async def test_a_partial_submit_cleans_up_and_stays_harmless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run_in_executor` can enqueue the job and THEN raise.

    Review reproduced it against a busy real worker: the fallback ran, and the
    queued job ran too. The contract is deliberately NOT exactly-once --
    `remove_workdir` is idempotent, so a duplicated removal costs at most a
    duplicate warning. An earlier revision claimed the removal once and had the
    loser wait on an Event; that swallowed the winner's exception and could
    time out indistinguishably from success, so it was removed rather than
    extended. What must hold is that the directory ends up gone and nothing
    raises.
    """
    # Arrange
    target = _make_dir(tmp_path, "partial-submit")
    calls: list[Path] = []
    real_remove = iso.remove_workdir

    def counting_remove(workdir: Any, **kwargs: Any) -> None:
        calls.append(Path(workdir))
        real_remove(workdir, **kwargs)

    monkeypatch.setattr(iso, "remove_workdir", counting_remove)

    loop = asyncio.get_running_loop()
    real_run_in_executor = loop.run_in_executor
    submitted: list[Any] = []

    def enqueue_then_raise(executor: Any, func: Any, *args: Any) -> Any:
        # Really submits, THEN raises -- the CPython behaviour review
        # reproduced, where `submit` enqueues and then fails starting a worker.
        submitted.append(real_run_in_executor(executor, func, *args))
        raise RuntimeError("executor is shutting down")

    monkeypatch.setattr(loop, "run_in_executor", enqueue_then_raise)

    # Act
    await iso.remove_workdir_off_loop(target)
    # Drain the enqueued job rather than sleeping: a sleep-based version passed
    # against a busy executor even with the duplicate suppressed, because the
    # second invocation had not run yet when it asserted.
    for fut in submitted:
        await fut

    # Assert
    assert not _still_present(target)
    assert calls, "cleanup never ran at all"
    assert all(p == target for p in calls), f"removed the wrong path: {calls}"


async def test_a_failed_submission_still_cleans_up_synchronously(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Submission refused outright -- nothing is queued, so only the fallback
    can act.

    The partial-submit test above does NOT pin this: there the queued job also
    runs, so deleting the fallback still leaves the directory removed. Mutation
    caught that gap.
    """
    # Arrange
    target = _make_dir(tmp_path, "no-executor")
    loop = asyncio.get_running_loop()

    def refuse(executor: Any, func: Any, *args: Any) -> Any:
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(loop, "run_in_executor", refuse)

    # Act
    await iso.remove_workdir_off_loop(target)

    # Assert
    assert not _still_present(target)


async def test_a_failure_inside_the_removal_reaches_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker's exception must not be swallowed.

    Pins what the removed Event handoff got wrong: it reported success while
    the loop separately logged "Future exception was never retrieved".
    """
    # Arrange
    target = _make_dir(tmp_path, "boom")

    def exploding_remove(workdir: Any, **kwargs: Any) -> None:
        raise ValueError("removal blew up")

    monkeypatch.setattr(iso, "remove_workdir", exploding_remove)

    # Act / Assert
    with pytest.raises(ValueError, match="removal blew up"):
        await iso.remove_workdir_off_loop(target)


# ---------------------------------------------------------------------------
# SubprocessSandbox's own generated workdir (review: NOT a dead branch)
# ---------------------------------------------------------------------------

async def test_sandbox_generated_workdir_is_removed_with_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ExecutionRequest.workdir`` defaults to None, so the sandbox picks one.

    I originally called this branch dead because every in-repo caller passes a
    workdir. Review executed the exported path and showed the generated
    directory survives a single transient failure. "No caller in this repo" is
    not "unreachable".
    """
    # Arrange
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    sandbox = SubprocessSandbox(scratch_root=scratch)
    stubborn = _StubbornRmtree(fail_times=1)
    monkeypatch.setattr(iso.shutil, "rmtree", stubborn)
    monkeypatch.setattr(iso.time, "sleep", lambda _s: None)

    # Act
    result = await sandbox.run(
        ExecutionRequest(code="print('hi')\n", timeout_seconds=60)
    )

    # Assert: the sandbox-chosen directory is gone, and it took a retry.
    assert isinstance(result, ExecutionResult)
    leftovers = [p for p in scratch.iterdir() if p.is_dir()]
    assert leftovers == [], f"sandbox leaked its own workdir: {leftovers}"
    assert stubborn.calls >= 2, "the generated-workdir branch did not retry"


# ---------------------------------------------------------------------------
# SkillForge._smoke_test
# ---------------------------------------------------------------------------

class _FakeSandbox:
    """Writes a deliverable into the workdir and reports success."""

    def __init__(self) -> None:
        self.workdirs: list[Path] = []

    async def run(self, request: Any) -> ExecutionResult:
        workdir = Path(request.workdir)
        self.workdirs.append(workdir)
        (workdir / "deliverable.txt").write_text("out", encoding="utf-8")
        return ExecutionResult(success=True, stdout="ok", workdir=str(workdir))


def _forge(sandbox: Any) -> Any:
    return skill_forge_module.SkillForge(
        llm_client=object(), catalog=object(), sandbox=sandbox
    )


def _staging(tmp_path: Path) -> Path:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "main.py").write_text("print('hi')\n", encoding="utf-8")
    return staging


async def test_smoke_test_removes_its_scratch_dir_through_the_shared_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the WIRING: reverting to a bare rmtree must fail this."""
    # Arrange. The spy DELEGATES to the real remover -- `_smoke_test` allocates
    # its workdir with `mkdtemp`, OUTSIDE `tmp_path`, so a recording no-op
    # would leak a real directory into %TEMP% on every run.
    staging = _staging(tmp_path)
    seen: list[Path] = []

    async def spy(workdir: Path) -> None:
        seen.append(Path(workdir))
        remove_workdir(workdir)

    monkeypatch.setattr(skill_forge_module, "remove_workdir_off_loop", spy)
    sandbox = _FakeSandbox()

    # Act
    outcome = await _forge(sandbox)._smoke_test(staging, "main.py")

    # Assert
    assert outcome.ok, outcome.detail
    assert sandbox.workdirs, "the fake sandbox was never driven"
    assert seen == sandbox.workdirs, (
        "the smoke test's scratch dir must be removed through the shared "
        "helper, not a one-shot rmtree"
    )
    assert not _still_present(sandbox.workdirs[0])


async def test_smoke_test_scratch_dir_is_actually_gone_afterwards(
    tmp_path: Path,
) -> None:
    """The seam: not just that a helper was called, but that the dir is gone."""
    # Arrange
    staging = _staging(tmp_path)
    sandbox = _FakeSandbox()

    # Act
    outcome = await _forge(sandbox)._smoke_test(staging, "main.py")

    # Assert
    assert outcome.ok, outcome.detail
    assert not _still_present(sandbox.workdirs[0])


async def test_smoke_test_still_cleans_up_when_the_run_fails(
    tmp_path: Path,
) -> None:
    """A failing smoke test must not leak its scratch dir either."""
    # Arrange
    staging = _staging(tmp_path)

    class _FailingSandbox(_FakeSandbox):
        async def run(self, request: Any) -> ExecutionResult:
            workdir = Path(request.workdir)
            self.workdirs.append(workdir)
            return ExecutionResult(
                success=False, stderr="boom", workdir=str(workdir)
            )

    sandbox = _FailingSandbox()

    # Act
    outcome = await _forge(sandbox)._smoke_test(staging, "main.py")

    # Assert
    assert not outcome.ok
    assert not _still_present(sandbox.workdirs[0])
