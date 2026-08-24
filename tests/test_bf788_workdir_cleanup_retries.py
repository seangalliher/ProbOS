"""BF-788 (#1252): a cancelled run left its workdir behind on Windows.

The tool's async `finally` calls `shutil.rmtree(workdir, ignore_errors=True)`
while the cancelled child still holds a handle. On Windows an open handle blocks
directory removal, so the tree survives -- and nothing retried once the child
exited. `ignore_errors=True` made the failure silent.

Measured against the real `CodeExecutionTool.invoke`:

    workdir_exists_after_confirmed_exit=True
    entries=['held.txt']

THREE EARLIER ATTEMPTS FAILED HERE. What each got wrong is why these tests look
the way they do:

1. The retry went into `SubprocessSandbox`'s `finally` behind `created_workdir`.
   Every production `ExecutionRequest` supplies `workdir`, so that flag is False
   and the helper was NEVER CALLED. Tests passed; the leak was untouched.
2. The retry became an asyncio task scheduled from the async `finally`. It
   expired after 1s while a child may run for the configured 30s (300s max),
   and loop shutdown cancelled it outright.
3. The "did the production path use it" test was a source-string assertion. It
   passed with the helper replaced by a no-op at runtime.

So the removal now happens on the WORKER thread, in `_run_sync`'s `finally`,
which is normally reached only after the child has exited -- the earliest
moment a Windows handle can be released. An abnormal `communicate()` now kills
and reaps the child first; if that reap itself fails, cleanup can still run
beside a live process (filed -- HEAD has the same hazard and does not try at
all). It is opt-in via `cleanup_on_cancel`, because a non-cancelled run still
needs the directory: `_capture_artifacts` reads it after `sandbox.run` returns.
A cancelled run does not reach artifact capture by the ordinary route, which is
what makes worker-side removal safe there. A cancellation delivered DURING
capture is possible; the ownership hand-off is what keeps that case safe, not
the ordering.

These tests do not rely on an open handle blocking removal -- true on Windows,
false on POSIX, and CI runs ubuntu. Removal is made to fail deterministically.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
from pathlib import Path

import pytest

import probos.execution.isolation as iso
from probos.execution.isolation import (
    CancelCleanup,
    ExecutionRequest,
    ExecutionResult,
    SubprocessSandbox,
    _remove_workdir,
)


def _populated(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "held.txt").write_text("x", encoding="utf-8")
    return d


# ── the handshake, driven through the real sandbox ────────────────


async def test_a_cancelled_run_removes_the_workdir_after_the_child_exits(
    tmp_path: Path,
) -> None:
    """The defect, end to end through `SubprocessSandbox.run`.

    The worker keeps running after the await is cancelled -- that is precisely
    why it is the only place that can clean up once the child lets go.
    """
    workdir = _populated(tmp_path, "cancelled")
    started, may_finish = threading.Event(), threading.Event()
    finished = threading.Event()

    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        started.set()
        may_finish.wait(timeout=5)          # stands in for a live child
        finished.set()
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    request = ExecutionRequest(
        code="print(1)",
        workdir=workdir,
        cleanup_on_cancel=CancelCleanup(),
    )

    task = asyncio.create_task(sandbox.run(request))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The child is still holding it; the directory is still there.
    assert workdir.exists()
    assert request.cleanup_on_cancel.cancelled.is_set(), "run() did not flag it"

    may_finish.set()                        # the child exits
    await asyncio.get_running_loop().run_in_executor(None, finished.wait, 5)
    await asyncio.get_running_loop().run_in_executor(None, lambda: None)

    for _ in range(100):                    # the worker finishes its `finally`
        if not workdir.exists():
            break
        await asyncio.sleep(0.02)

    assert not workdir.exists(), list(workdir.iterdir())


async def test_a_completed_run_keeps_its_workdir(tmp_path: Path) -> None:
    """The positive premise, and the thing that must not regress.

    `_capture_artifacts` reads this directory after `sandbox.run` returns.
    Removing it on the success path would silently destroy every artifact.
    """
    workdir = _populated(tmp_path, "completed")
    sandbox = SubprocessSandbox(scratch_root=tmp_path)
    sandbox._run_sync_inner = lambda req: ExecutionResult(  # type: ignore[method-assign]
        success=True, workdir=str(req.workdir),
    )

    request = ExecutionRequest(
        code="print(1)", workdir=workdir, cleanup_on_cancel=CancelCleanup(),
    )
    result = await sandbox.run(request)

    assert result.success
    assert workdir.exists()
    assert (workdir / "held.txt").exists()


async def test_without_the_opt_in_nothing_is_removed(tmp_path: Path) -> None:
    """Callers that did not opt in get no cleanup-on-cancel behaviour.

    Not "byte-identical to before": absolute-path resolution and the abnormal-
    `communicate()` reaping apply to every caller.
    """
    workdir = _populated(tmp_path, "no_optin")
    started, may_finish = threading.Event(), threading.Event()
    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        started.set()
        may_finish.wait(timeout=5)
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    request = ExecutionRequest(code="print(1)", workdir=workdir)  # no event
    task = asyncio.create_task(sandbox.run(request))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    may_finish.set()
    await asyncio.sleep(0.1)

    assert workdir.exists()


async def test_it_cleans_up_when_the_worker_finishes_before_the_cancel_lands(
    tmp_path: Path,
) -> None:
    """The race attempt 4 lost, as the `run()`-side branch that closes it.

    A single flag has a hole: the worker can read `cleanup_on_cancel` in the
    instant BEFORE `run()` sets it, decide there is nothing to do, and exit --
    leaving `run()`'s handler facing a worker that has already gone. The
    measured symptom was a surviving descendant:

        DESCENDANT_RACE immediate_exists=True after_descendant_exists=True

    Thread interleaving cannot be made deterministic, so `finished` is
    published directly here: that is precisely the state a worker leaves behind
    when it wins the race. The worker itself stays blocked, which proves the
    removal came from `run()` and not from the worker's `finally`.
    """
    workdir = _populated(tmp_path, "late_cancel")
    entered, release = threading.Event(), threading.Event()
    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        entered.set()
        release.wait(timeout=10)
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    handshake = CancelCleanup()
    request = ExecutionRequest(
        code="print(1)", workdir=workdir, cleanup_on_cancel=handshake,
    )

    task = asyncio.create_task(sandbox.run(request))
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, entered.wait, 5)

    # Stand in for a worker that published `finished` and read `cancelled` as
    # clear, all before this cancellation was delivered.
    handshake.finished.set()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(100):
        if not workdir.exists():
            break
        await asyncio.sleep(0.05)

    release.set()
    assert not workdir.exists(), (
        "the worker had already published `finished` when the cancel arrived, "
        "so run() owns the removal -- nobody did it. The single-flag race is "
        "back."
    )


async def test_the_worker_publishes_finished_before_it_reads_cancelled(
    tmp_path: Path,
) -> None:
    """The ORDER is the whole fix; reversing it reopens the leak.

    With the two writes inverted the worker reads `cancelled` (clear), the loop
    then sets `cancelled` and reads `finished` (still clear, so it declines),
    and only afterwards does the worker publish `finished`. Neither side cleans
    up. Mutation R10 -- swapping those two statements -- survived every other
    test in this file, which is why this one exists.

    Observed from the worker thread only, on an ordinary uncancelled run, so
    there is no timing dependence.
    """
    workdir = _populated(tmp_path, "ordering")
    log: list[tuple[int, str]] = []

    class _Recording(threading.Event):
        def __init__(self, name: str) -> None:
            super().__init__()
            self._name = name

        def set(self) -> None:
            log.append((threading.get_ident(), f"{self._name}.set"))
            super().set()

        def is_set(self) -> bool:
            log.append((threading.get_ident(), f"{self._name}.is_set"))
            return super().is_set()

    sandbox = SubprocessSandbox(scratch_root=tmp_path)
    worker_ident: list[int] = []

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        worker_ident.append(threading.get_ident())
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    await sandbox.run(ExecutionRequest(
        code="print(1)",
        workdir=workdir,
        cleanup_on_cancel=CancelCleanup(
            cancelled=_Recording("cancelled"), finished=_Recording("finished"),
        ),
    ))

    assert worker_ident, "the worker never ran"
    ops = [op for ident, op in log if ident == worker_ident[0]]
    assert "finished.set" in ops, ops
    assert "cancelled.is_set" in ops, ops
    assert ops.index("finished.set") < ops.index("cancelled.is_set"), (
        "the worker read `cancelled` before publishing `finished`; the loop "
        f"can then decline too and nobody removes the directory. ops={ops}"
    )
    # An uncancelled run must NOT remove the directory -- artifact capture
    # reads it after `run()` returns.
    assert workdir.exists()


async def test_the_sandbox_resolves_a_relative_workdir_before_the_child_starts(
    tmp_path: Path, monkeypatch,
) -> None:
    """Blocker 2 from review.

    `_run_sync_inner` resolves a LOCAL copy, so a relative `request.workdir`
    stayed relative on the request itself. Cleanup then joins it against
    whatever the process cwd happens to be at that moment -- which BF-715
    established the sandbox must not depend on. Resolve once, up front.
    """
    (tmp_path / "rel").mkdir()
    monkeypatch.chdir(tmp_path)

    seen: list[Path | None] = []
    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        seen.append(request.workdir)
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    await sandbox.run(ExecutionRequest(code="print(1)", workdir=Path("rel")))

    assert seen and seen[0] is not None
    assert Path(seen[0]).is_absolute(), seen
    assert Path(seen[0]) == (tmp_path / "rel").resolve()


# ── the removal helper ────────────────────────────────────────────


def test_it_retries_when_the_first_removal_loses(tmp_path: Path, monkeypatch) -> None:
    """Deterministic on every platform: the first attempt is made to fail
    rather than relying on an open handle, which blocks only on Windows."""
    d = _populated(tmp_path, "retry")
    real = iso.shutil.rmtree
    calls = {"n": 0}

    def failing_first(path, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return
        real(path, **kw)

    monkeypatch.setattr(iso.shutil, "rmtree", failing_first)
    monkeypatch.setattr(iso.time, "sleep", lambda s: None)

    _remove_workdir(d, attempts=3, delay=0.01)

    assert not d.exists()
    assert calls["n"] == 2, calls


def test_it_removes_a_free_workdir_on_the_first_attempt(
    tmp_path: Path, monkeypatch,
) -> None:
    """The positive premise for the helper: a normal removal must not retry.

    Counts attempts. Asserting only that the directory is gone passed against
    a mutant that retried three times after confirming absence, and emitted a
    false give-up warning.
    """
    d = _populated(tmp_path, "free")
    real = iso.shutil.rmtree
    attempts = {"n": 0}

    def counting(path, **kw):
        attempts["n"] += 1
        return real(path, **kw)

    monkeypatch.setattr(iso.shutil, "rmtree", counting)

    _remove_workdir(d, attempts=3, delay=0.01)

    assert not d.exists()
    assert attempts["n"] == 1, (
        f"a free directory took {attempts['n']} removal attempts"
    )


def test_giving_up_is_reported_not_swallowed(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    d = _populated(tmp_path, "stuck")
    monkeypatch.setattr(iso.shutil, "rmtree", lambda path, **kw: None)
    monkeypatch.setattr(iso.time, "sleep", lambda s: None)

    with caplog.at_level(logging.WARNING, logger="probos.execution.isolation"):
        _remove_workdir(d, attempts=2, delay=0.01)

    messages = [r.getMessage() for r in caplog.records]
    assert any("BF-788" in m for m in messages), messages
    assert any(str(d) in m for m in messages), messages


def test_the_survival_check_does_not_follow_links(
    tmp_path: Path, monkeypatch,
) -> None:
    """`stat()` follows symlinks, so a dangling one reads as removed while the
    entry remains. `os.lstat` does not follow. Asserts the ARGUMENT, not merely
    that something was called -- a previous version passed against a wrong-path
    implementation.
    """
    d = tmp_path / "linkcheck"
    seen: list[str] = []

    def probe(p):
        seen.append(str(p))
        raise FileNotFoundError(p)

    monkeypatch.setattr(iso.shutil, "rmtree", lambda path, **kw: None)
    monkeypatch.setattr(iso.time, "sleep", lambda s: None)
    monkeypatch.setattr(iso.os, "lstat", probe)

    _remove_workdir(d, attempts=1, delay=0.01)

    assert seen == [str(d)], seen


def test_an_undecidable_stat_counts_as_present(monkeypatch) -> None:
    """`_still_present` must never guess "gone".

    That guess is precisely how BF-788 stayed silent: `os.path.lexists`
    catches OSError internally and returns False, so a PermissionError reads
    as a successful removal. The caller uses this to decide whether to
    escalate, so a False here means nobody retries.
    """
    def denied(_p):
        raise PermissionError("denied")

    monkeypatch.setattr(iso.os, "lstat", denied)
    assert iso._still_present(Path("anything")) is True


def test_a_dangling_link_is_not_read_as_removed(tmp_path: Path) -> None:
    """The positive case for using lstat: a link whose target is gone must
    still count as present, because the entry itself is."""
    d = tmp_path / "dangling"
    target = tmp_path / "gone"
    target.mkdir()
    try:
        d.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")
    target.rmdir()

    assert not d.exists(), "premise: exists() follows the link and reports False"
    assert iso.os.path.lexists(d), "premise: the entry itself is still there"
    # The point of the test: production must agree with the entry, not the
    # target. An earlier version asserted only the two premises and never
    # called production at all -- it would have passed if `_still_present`
    # returned False or raised.
    assert iso._still_present(d) is True


def test_a_stat_failure_gives_up_rather_than_raising(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    """This runs in a `finally`. Raising here would replace the run's real
    result with a cleanup error -- but giving up SILENTLY would restore the
    very property BF-788 exists to remove.

    Patches `os.lstat`, which is what the helper actually calls. An earlier
    version patched `os.path.lexists` and made it RAISE -- but the real
    `lexists` catches OSError internally and returns False, so that double was
    more capable than the collaborator and the `except` branch it "covered" was
    dead code. Worse, the real behaviour was to report the directory GONE.
    """
    d = _populated(tmp_path, "statfail")

    def boom(_p):
        raise PermissionError("cannot stat")

    monkeypatch.setattr(iso.shutil, "rmtree", lambda path, **kw: None)
    monkeypatch.setattr(iso.os, "lstat", boom)

    with caplog.at_level(logging.WARNING, logger="probos.execution.isolation"):
        _remove_workdir(d, attempts=3, delay=0.01)  # must not raise

    messages = [r.getMessage() for r in caplog.records]
    assert any("BF-788" in m for m in messages), messages
    assert any(str(d) in m for m in messages), messages


def test_a_permission_error_is_not_mistaken_for_removal(
    tmp_path: Path, monkeypatch, caplog,
) -> None:
    """The specific trap: `os.path.lexists` swallows OSError and returns False.

    Review measured `DIRECT_LEXISTS_UNDER_PERMISSION_ERROR=False` with
    `WORKDIR_EXISTS_AFTER_HELPER=True` and `WARNING_COUNT=0` -- the helper
    returned as if it had succeeded. This pins that a stat error can never be
    read as absence.
    """
    d = _populated(tmp_path, "permerror")
    monkeypatch.setattr(iso.shutil, "rmtree", lambda path, **kw: None)
    monkeypatch.setattr(
        iso.os, "lstat", lambda _p: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with caplog.at_level(logging.WARNING, logger="probos.execution.isolation"):
        _remove_workdir(d, attempts=2, delay=0.01)

    assert d.exists(), "the directory really is still there"
    assert caplog.records, (
        "a PermissionError was read as 'already removed' and reported nothing"
    )


def test_the_retry_budget_outlasts_a_detached_descendant(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 1: a DETACHED grandchild outlives the child.

    A flat 5 x 0.2s budget (0.8s) gave up while a 3s grandchild still held the
    directory. The budget now backs off, so the total wait covers a
    multi-second holder. Asserted on the SLEEP SCHEDULE rather than by racing a
    real grandchild, so it is deterministic and platform-independent.
    """
    d = _populated(tmp_path, "detached")
    slept: list[float] = []
    monkeypatch.setattr(iso.shutil, "rmtree", lambda path, **kw: None)
    monkeypatch.setattr(iso.time, "sleep", lambda s: slept.append(s))

    _remove_workdir(d)

    assert sum(slept) >= 3.0, (
        "the retry budget is shorter than a detached descendant's lifetime; "
        f"total wait was {sum(slept)}s across {len(slept)} sleeps"
    )
    assert max(slept) <= 2.0, f"backoff is unbounded: {slept}"


async def test_a_shut_down_executor_does_not_mask_the_cancellation(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 4.

    When the worker had already published `finished`, `run()` owns the removal
    and hands it to the executor. If the executor is shutting down that
    submission raises RuntimeError -- measured as:

        OUTCOME=RuntimeError: cannot schedule new futures after shutdown
        FLAGS cancelled=True finished=True   WORKDIR_EXISTS=True

    which both replaced the caller's CancelledError with the wrong exception
    and left the directory behind. The caller must still see CancelledError,
    and the directory must still go.
    """
    workdir = _populated(tmp_path, "shutdown")
    entered, release = threading.Event(), threading.Event()
    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        entered.set()
        release.wait(timeout=10)
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    handshake = CancelCleanup()
    request = ExecutionRequest(
        code="print(1)", workdir=workdir, cleanup_on_cancel=handshake,
    )

    task = asyncio.create_task(sandbox.run(request))
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, entered.wait, 5)
    handshake.finished.set()          # the worker got there first

    real_submit = loop.run_in_executor

    def refusing(executor, func, *args):
        if func is iso._remove_workdir:
            raise RuntimeError("cannot schedule new futures after shutdown")
        return real_submit(executor, func, *args)

    monkeypatch.setattr(loop, "run_in_executor", refusing)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task                    # NOT RuntimeError

    release.set()
    assert not workdir.exists(), (
        "the executor refused the handoff and nothing fell back; the "
        "directory survived"
    )


async def test_the_tool_resolves_its_workdir_when_scratch_is_relative(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 2.

    `scratch_dir` defaults to a RELATIVE path, and the tool keeps its own copy
    of `workdir` for artifact capture and for its `finally` removal. Resolving
    only inside the sandbox left those two joining a relative path against
    whatever the process cwd had become:

        RESULT_ARTIFACTS=[]  STORED_ARTIFACT_COUNT=0
        ORIGINAL_REPORTS=[...report.txt]  LEFTOVER_EXEC_DIRS=[...]
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools.code_execution_tool import CodeExecutionTool

    monkeypatch.chdir(tmp_path)
    # The TOOL's own copy, not the sandbox's. `run()` rebinds
    # `request.workdir`, which does NOT fix the local the tool keeps for
    # artifact capture and its own `finally` removal -- so asserting on the
    # request would pass with the tool-side resolve reverted.
    captured: list[Path] = []
    real_capture = CodeExecutionTool._capture_artifacts

    async def capture_spy(self, workdir, *a, **kw):
        captured.append(workdir)
        return await real_capture(self, workdir, *a, **kw)

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(enabled=True, scratch_dir="rel_scratch"),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    monkeypatch.setattr(CodeExecutionTool, "_capture_artifacts", capture_spy)
    await CodeExecutionTool(runtime=runtime).invoke(
        {"code": "print('ok')"}, {"thread_id": "t", "agent_id": "ezri"},
    )

    assert captured, "artifact capture never ran"
    assert Path(captured[0]).is_absolute(), (
        "the tool kept a RELATIVE workdir for artifact capture and cleanup; a "
        f"cwd change between creation and capture targets the wrong directory: {captured[0]}"
    )


# ── the production caller opts in ─────────────────────────────────


async def test_the_tool_teardown_uses_the_retrying_removal(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 1, on the path that actually leaked.

    The tool's teardown was `shutil.rmtree(workdir, ignore_errors=True)`. A
    DETACHED grandchild inherits the workdir as its cwd and outlives the child,
    so that call fails -- and `ignore_errors=True` said nothing. Measured with
    a true-detached grandchild: an EMPTY exec dir survived 20s past a run that
    had already completed. Note this is the SUCCESS path; the cancel-path
    handshake never fires here.

    The FIRST removal is made to fail deterministically. An earlier version of
    this test only spied on the dispatched callable against a freely removable
    directory -- review proved it could not tell `_remove_workdir` from the old
    one-shot silent remover, because both leave an empty dir gone.
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools import code_execution_tool as cet

    real_rmtree = shutil.rmtree
    blocked: dict[str, int] = {"n": 0}
    BLOCK_UNTIL = 3

    def failing_first(path, **kw):
        # Defeat the first few removals, exactly as an open handle would.
        # THREE, not one: a one-shot escalation gets two attempts in total
        # (the tool's own plus its replacement), so blocking a single attempt
        # let the old silent remover pass this test. Only something that keeps
        # retrying gets past three.
        blocked["n"] += 1
        if blocked["n"] <= BLOCK_UNTIL:
            return
        return real_rmtree(path, **kw)

    monkeypatch.setattr(cet.shutil, "rmtree", failing_first)
    monkeypatch.setattr(iso.shutil, "rmtree", failing_first)
    monkeypatch.setattr(iso.time, "sleep", lambda s: None)

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "scratch"),
            ),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    result = await cet.CodeExecutionTool(runtime=runtime).invoke(
        {"code": "print('ok')"}, {"thread_id": "t", "agent_id": "ezri"},
    )

    # Prove the run actually happened. Review showed this test passing with
    # `sandbox.run` replaced by a RuntimeError -- an empty scratch dir is
    # indistinguishable from a cleaned one if nothing ever ran.
    assert result.error is None, result.error
    assert result.output.get("success") is True, result.output

    scratch = tmp_path / "scratch"
    # The escalation is dispatched, not awaited, so give the executor a moment.
    for _ in range(100):
        if not (scratch.exists() and list(scratch.glob("exec-*"))):
            break
        await asyncio.sleep(0.05)

    leftover = list(scratch.glob("exec-*")) if scratch.exists() else []
    assert blocked["n"] > BLOCK_UNTIL, (
        "the teardown gave up after too few attempts; a one-shot removal "
        f"cannot survive a held directory (attempts={blocked['n']})"
    )
    assert leftover == [], f"workdir leaked past a failed first removal: {leftover}"


async def test_a_queued_run_cancelled_before_it_starts_is_still_cleaned(
    tmp_path: Path,
) -> None:
    """Review's blocker 1 on attempt 5b -- a regression I introduced.

    Deferring to the sandbox handshake whenever `cancelled` was set looked
    right. It is not: when the executor is saturated, cancelling the awaiting
    task cancels the QUEUED job outright, so `_run_sync` never runs, never
    publishes `finished`, and never reaches its `finally`. Review measured:

        SUBMITTED=True  WORKER_STARTED_BEFORE_CANCEL=False
        ASYNC_EXECUTOR_FUTURE_CANCELLED=True
        LEFTOVER_EXEC_DIRS=[...exec-c0a5235f...]

    No child ever existed, so the caller can and must remove it.
    """
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools.code_execution_tool import CodeExecutionTool

    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=1)
    hold, occupied = threading.Event(), threading.Event()

    def occupy():
        occupied.set()
        hold.wait(timeout=15)

    loop.set_default_executor(pool)
    try:
        pool.submit(occupy)
        assert occupied.wait(5), "the executor never became busy"

        runtime = SimpleNamespace(
            config=SimpleNamespace(
                execution=ExecutionConfig(
                    enabled=True, scratch_dir=str(tmp_path / "scratch"),
                ),
            ),
            artifact_store=None,
            attachment_store=None,
        )
        task = asyncio.create_task(CodeExecutionTool(runtime=runtime).invoke(
            {"code": "print('ok')"}, {"thread_id": "t", "agent_id": "ezri"},
        ))
        await asyncio.sleep(0.5)      # submitted, queued behind `occupy`
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Read it while the pool is STILL saturated. The escalation would have
        # to queue behind `occupy`, so it cannot have run -- only the
        # synchronous removal can have. Measured: with that removal skipped,
        # the directory is still here at this point.
        scratch = tmp_path / "scratch"
        leftover = list(scratch.glob("exec-*")) if scratch.exists() else []
    finally:
        hold.set()
        pool.shutdown(wait=True)

    assert leftover == [], (
        "the queued job was cancelled before any worker ran, so no child ever "
        "existed -- but the directory was still here while the executor was "
        f"busy, i.e. cleanup depended on a thread that was not free: {leftover}"
    )


async def test_a_cancelled_run_does_not_also_dispatch_the_retry(
    tmp_path: Path, monkeypatch,
) -> None:
    """The worker owns the RETRY on a cancelled run.

    The tool still makes its own plain attempt (see the queued-cancel case),
    but escalating to the retrying remover as well would only race the worker
    to a spurious give-up warning while the child is still running.
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools import code_execution_tool as cet

    dispatched: list[Path] = []
    monkeypatch.setattr(
        cet, "_remove_workdir", lambda workdir, **kw: dispatched.append(Path(workdir)),
    )

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "scratch"),
            ),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    task = asyncio.create_task(cet.CodeExecutionTool(runtime=runtime).invoke(
        {"code": "import time; time.sleep(5)"},
        {"thread_id": "t", "agent_id": "ezri"},
    ))
    await asyncio.sleep(0.8)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.3)
    assert not dispatched, (
        "the tool escalated to the retrying remover on a cancelled run, "
        f"racing the worker that owns it: {dispatched}"
    )


async def test_a_communicate_failure_reaps_the_child_before_returning(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 1 on attempt 5f.

    Every caller treats `_run_sync_inner` returning as "the child is gone", and
    cleanup acts on that. But an exception out of `communicate()` returned with
    the child STILL RUNNING, so cleanup deleted files out from under it.
    Measured against HEAD with a real child and an injected pipe error:

        HEAD:  CHILD_OUTCOME = FileNotFoundError   CORRUPTED = True
        fixed: CHILD_OUTCOME = <no result>         CORRUPTED = False

    "No result" is the correct outcome: the child is reaped, so it never
    reaches the read at all.
    """
    import subprocess as _sp

    sandbox = SubprocessSandbox(scratch_root=tmp_path)
    workdir = tmp_path / "reap"
    workdir.mkdir()
    killed: list[str] = []
    spawned: list = []
    real_popen = _sp.Popen

    class Injecting(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            spawned.append(self)

        def communicate(self, *a, **kw):
            raise OSError("injected pipe failure while the child is live")

        def kill(self):
            killed.append("kill")
            return super().kill()

    monkeypatch.setattr(_sp, "Popen", Injecting)

    result = await sandbox.run(ExecutionRequest(
        code="import time; time.sleep(30)",
        workdir=workdir,
        timeout_seconds=60,
    ))

    assert result.success is False
    assert killed, (
        "the run returned after a communicate() failure without killing the "
        "child; cleanup will now delete files from under a live process"
    )
    # Asserting `kill()` was CALLED is not enough -- review showed those
    # assertions still hold with `proc.wait()` removed. Read `returncode`
    # DIRECTLY: `poll()` performs a nonblocking reap itself, so calling it
    # here would do production's job and pass 13/20 runs against a mutant.
    assert spawned, "no child was created, so this proves nothing"
    assert spawned[0].returncode is not None, (
        "kill() was called but the child had not been reaped when `run` "
        "returned; cleanup will act beside a live process"
    )


async def test_exactly_one_side_removes_when_both_observe(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 2 on attempt 5f.

    Both flag reads can succeed: if `cancelled` and `finished` are both set
    before either side reads, each sees the other's and removes. Measured
    `REMOVE_CALL_COUNT=2` on two threads. `rmtree` is idempotent, but two retry
    loops occupy two executor threads and can both warn about one directory.

    Driven through the handshake object directly, so the interleaving is exact
    rather than hoped for.
    """
    calls: list[int] = []
    monkeypatch.setattr(
        iso, "_remove_workdir", lambda w, **kw: calls.append(threading.get_ident()),
    )

    handshake = CancelCleanup()
    handshake.cancelled.set()
    handshake.finished.set()

    barrier = threading.Barrier(2)

    def contender():
        barrier.wait(timeout=5)
        if handshake.claim():
            iso._remove_workdir(tmp_path)

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(calls) == 1, (
        f"both sides removed the same directory concurrently: {calls}"
    )


async def test_an_interrupt_right_after_mkdir_still_cleans_up(
    tmp_path: Path, monkeypatch,
) -> None:
    """Review's blocker 1 on attempt 5e -- a regression I introduced.

    `workdir_created` was set AFTER `mkdir` returned. A BaseException in that
    window skipped teardown entirely and leaked the directory, where HEAD's
    unconditional removal had cleaned it:

        WORKDIR_EXISTS_AFTER_INTERRUPT=True   (mine)
        HEAD_WORKDIR_EXISTS_AFTER_INTERRUPT=False

    The flag now means "this path is valid and ours to clean", so it is set
    before anything can create the directory.
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools import code_execution_tool as cet

    # Pre-create the scratch root. With `parents=True` the patched `mkdir`
    # recurses to build it and would raise while creating the PARENT, so the
    # exec dir would never exist and the test would pass either way -- which
    # is exactly how the first version of this test let the mutant live.
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    real_mkdir = Path.mkdir
    hooked: list[str] = []

    def exploding_mkdir(self, *a, **kw):
        real_mkdir(self, *a, **kw)      # the directory really is created
        if self.name.startswith("exec-"):
            hooked.append(self.name)
            raise KeyboardInterrupt("interrupted right after mkdir")

    monkeypatch.setattr(Path, "mkdir", exploding_mkdir)

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(enabled=True, scratch_dir=str(scratch)),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    with pytest.raises(KeyboardInterrupt):
        await cet.CodeExecutionTool(runtime=runtime).invoke(
            {"code": "print('ok')"}, {"thread_id": "t", "agent_id": "ezri"},
        )

    monkeypatch.undo()
    assert hooked, (
        "the exec-dir mkdir hook never fired, so the interrupt window was "
        "never entered -- this test would pass against anything"
    )
    leftover = list(scratch.glob("exec-*")) if scratch.exists() else []
    assert leftover == [], (
        f"an interrupt between mkdir and the ownership flag leaked: {leftover}"
    )


async def test_a_refused_run_still_answers_the_launch_question(
    tmp_path: Path,
) -> None:
    """Review's blocker 2 on attempt 5e.

    AD-1247's contract is that EVERY exit from `run` answers whether a child
    was created. The malformed-workdir early return bypassed it:

        MALFORMED_RESULT_SUCCESS=False  MALFORMED_LAUNCH_RESOLVED=False

    A caller doing a bounded wait on `resolved` would have waited out its whole
    budget and then recorded "unknown" for a run that definitely never started.
    """
    from probos.execution.isolation import LaunchOutcome

    launch = LaunchOutcome()
    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    result = await sandbox.run(ExecutionRequest(
        code="print(1)",
        workdir=Path(str(tmp_path / "nul\x00dir")),
        launch_outcome=launch,
    ))

    assert result.success is False
    assert launch.resolved.is_set(), (
        "the run refused before starting but never answered the launch "
        "question; a caller waiting on it blocks for its full budget"
    )
    assert launch.launched is False


async def test_run_degrades_a_malformed_workdir_instead_of_raising(
    tmp_path: Path,
) -> None:
    """`SubprocessSandbox.run` promises to honest-degrade ordinary failures.

    BF-788 added a `.resolve()` at the top of `run`, outside anything guarded,
    which broke that for a malformed path:

        RAISED = ValueError: stat: embedded null character in path
    """
    sandbox = SubprocessSandbox(scratch_root=tmp_path)
    bad = Path(str(tmp_path / "nul\x00dir"))

    result = await sandbox.run(ExecutionRequest(code="print(1)", workdir=bad))

    assert result.success is False
    assert "workdir" in result.error, result.error


async def test_a_malformed_scratch_dir_degrades_instead_of_escaping(
    tmp_path: Path,
) -> None:
    """Review's blocker 3 on attempt 5d.

    `shutil.rmtree(..., ignore_errors=True)` swallows OSError but NOT
    ValueError, and a path with an embedded NUL raises the latter. The teardown
    runs in a `finally`, so it replaced the ToolResult with a raised exception:

        ESCAPED=ValueError: lstat: embedded null character in path

    A configuration fault must degrade like any other ordinary failure.
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools.code_execution_tool import CodeExecutionTool

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "bad\x00nul" / "scratch"),
            ),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    result = await CodeExecutionTool(runtime=runtime).invoke(
        {"code": "print('ok')"}, {"thread_id": "t", "agent_id": "ezri"},
    )

    assert result is not None
    assert result.error, "a malformed scratch_dir produced no error to report"


async def test_a_cancelled_run_does_not_delete_files_from_a_live_child(
    tmp_path: Path,
) -> None:
    """The behaviour this whole change most has to get right.

    Measured against HEAD, whose teardown removes unconditionally on every
    path: the child's own file vanished mid-run and the script died with
    `FileNotFoundError`. With the ownership hand-off it completes.

    Uses a real child and a real cancellation -- a stub cannot hold a handle.
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools.code_execution_tool import CodeExecutionTool

    out = tmp_path / "out.txt"
    mark = tmp_path / "mark.txt"
    code = (
        "import time, pathlib\n"
        "pathlib.Path('needed.txt').write_text('payload')\n"
        f"pathlib.Path(r'{mark}').write_text('started')\n"
        "time.sleep(1.5)\n"
        "try:\n"
        "    d = pathlib.Path('needed.txt').read_text()\n"
        f"    pathlib.Path(r'{out}').write_text('OK:' + d)\n"
        "except Exception as e:\n"
        f"    pathlib.Path(r'{out}').write_text(type(e).__name__)\n"
    )

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "scratch"),
                timeout_seconds=30,
            ),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    task = asyncio.create_task(CodeExecutionTool(runtime=runtime).invoke(
        {"code": code}, {"thread_id": "t", "agent_id": "ezri"},
    ))
    for _ in range(200):
        if mark.exists():
            break
        await asyncio.sleep(0.05)
    assert mark.exists(), "the child never reached its live point"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    for _ in range(200):
        if out.exists():
            break
        await asyncio.sleep(0.1)

    assert out.exists(), "the child never recorded an outcome"
    assert out.read_text() == "OK:payload", (
        "the cancelled run deleted the workdir out from under a LIVE child; "
        f"the script saw {out.read_text()}"
    )


async def test_the_tool_passes_the_cancellation_flag(tmp_path) -> None:
    """Crosses the RUNTIME seam, not the source text.

    Attempt 3's version of this test asserted on `inspect.getsource`. Review
    replaced the helper with a no-op at runtime and it still passed -- it was
    checking spelling. This drives the real `CodeExecutionTool.invoke` and
    inspects the `ExecutionRequest` that actually reaches the sandbox.
    """
    from types import SimpleNamespace

    from probos.config import ExecutionConfig
    from probos.tools.code_execution_tool import CodeExecutionTool

    seen: list[ExecutionRequest] = []
    original = SubprocessSandbox.run

    async def spy(self, request: ExecutionRequest):
        seen.append(request)
        return await original(self, request)

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "scratch"),
            ),
        ),
        artifact_store=None,
        attachment_store=None,
    )

    SubprocessSandbox.run = spy  # type: ignore[method-assign]
    try:
        tool = CodeExecutionTool(runtime=runtime)
        await tool.invoke(
            {"code": "print('ok')"},
            {"thread_id": "t-1", "agent_id": "ezri"},
        )
    finally:
        SubprocessSandbox.run = original  # type: ignore[method-assign]

    assert seen, "invoke() never reached SubprocessSandbox.run"
    handshake = seen[0].cleanup_on_cancel
    assert isinstance(handshake, CancelCleanup), (
        "the production request does not carry the opt-in; the fix is inert "
        f"(got {handshake!r})"
    )
    # It must arrive unset -- a pre-set `cancelled` would remove the workdir
    # from under artifact capture on every ordinary run.
    assert not handshake.cancelled.is_set()
    # And `workdir` must be absolute by the time the sandbox sees it, so both
    # cleanup sites and the child name one path regardless of process cwd.
    assert seen[0].workdir is not None
    assert Path(seen[0].workdir).is_absolute()
