"""AD-1298 (#1305, BF-839): the CancelCleanup flag handshake became a state machine.

BF-788 arbitrated scratch-dir ownership with three ``threading.Event``s. Ten
adversarial review rounds each closed one seam and found another *at the same
seam*, which is the signature of a structural problem rather than a missing
patch: separate flags cannot be read as one decision, so every reader had to
reconstruct the state from independent observations and each reconstruction had
a different hole.

Two residuals survived to here, both reproduced by execution before this change
was designed.

**Residual 1 -- the RUNNING-but-not-``started`` window.**
``ThreadPoolExecutor._WorkItem.run`` calls ``set_running_or_notify_cancel()``
*before* invoking the callable, so ``cancel()`` returns False while ``started``
is still clear, the asyncio wrapper cancels anyway, and the caller concludes it
owns the directory. Measured through the real sandbox::

    premise_worker_running=True premise_started_clear=True
    START_BOUNDARY_RACE cancellation=CancelledError
    tool_predicate_says_tool_owns_dir=True
    workdir_before_worker_entry=False
    staged_input_before_worker_entry=False
    child_outcome="FileNotFoundError: ... 'input.txt'" exit=1

with a natural frequency of ``30/5996`` cancels that landed on a RUNNING
future, no artificial gating.

**Residual 2 -- TWO unguarded ``communicate()`` exits, not one.** The
``except BaseException`` arm killed, bounded-waited, warned and re-raised --
and the outer honest-degrade arm converted that straight back into an
``ExecutionResult``, which every caller reads as "the child is gone". The
post-``TimeoutExpired`` retry sat outside every handler, so it also lost
``timed_out=True``::

    FAILED_KILL              returned_ExecutionResult=True timed_out=False child_alive_on_return=True
    TIMEOUT_FOLLOWUP_FAILURE returned_ExecutionResult=True timed_out=False child_alive_on_return=True

Warning and then deleting is the original corruption with a log line added.

The fix is one lock over one field, ``QUEUED -> {ABORTED | RUNNING} ->
{REAPED | UNSAFE}``. Whoever takes the lock first decides and the loser adapts
instead of guessing: the caller never has to know whether the future was still
cancellable, it only needs the worker to honour the decision.

``test_bf839_start_boundary_worker_honours_caller_abort`` is the test that
proves residual 1 is closed, and
``test_bf839_the_probe_reproduces_the_corruption_when_the_abort_is_ignored``
is what proves that test discriminates -- it runs the identical scenario with
the arbitration reverted in memory and asserts the measured HEAD symptoms come
back. A probe that cannot reproduce the known race proves nothing.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.execution.isolation as iso
import probos.tools.code_execution_tool as cet
from probos.config import ExecutionConfig
from probos.execution.isolation import (
    CancelCleanup,
    CleanupState,
    ExecutionRequest,
    ExecutionResult,
    SubprocessSandbox,
)
from probos.tools.code_execution_tool import CodeExecutionTool


class _Audit:
    """The real ``AuditLog`` surface: keyword-only ``append``."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, Any]]] = []

    def append(self, *, category: str, detail: str) -> None:
        self.entries.append((category, json.loads(detail)))

    @property
    def records(self) -> list[dict[str, Any]]:
        return [d for c, d in self.entries if c == "code_execution"]


def _runtime(tmp_path: Path, *, audit: Any = None) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True,
                scratch_dir=str(tmp_path / "scratch"),
                timeout_seconds=30,
            ),
            dependency=None,
        ),
        audit_log=audit,
        agent_registry=None,
        artifact_store=None,
        attachment_store=None,
    )


# ── the arbiter itself ─────────────────────────────────────────────


def test_the_three_flags_are_gone_rather_than_hidden_behind_properties() -> None:
    """Read-only survivors would invite the old reasoning straight back.

    Every seam BF-788 reopened came from a reader reconstructing state out of
    ``cancelled``/``finished``/``started``. Leaving them readable would let the
    next edit ask the old question and get an answer that no longer means what
    it used to.
    """
    handshake = CancelCleanup()
    for name in ("cancelled", "finished", "started"):
        assert not hasattr(handshake, name), (
            f"CancelCleanup still exposes `{name}`; the flag reasoning the "
            "state machine replaced is reachable again"
        )


def test_a_cancel_on_a_queued_job_aborts_it_and_keeps_teardown() -> None:
    handshake = CancelCleanup()

    assert handshake.note_cancelled() is True
    assert handshake.caller_owns_teardown is True
    assert handshake._state is CleanupState.ABORTED


def test_a_worker_that_finds_an_abort_refuses_to_start() -> None:
    """The decisive property: the worker HONOURS the caller's decision.

    Not "the caller guessed right about the future's cancellability" -- that
    is the question BF-788 kept trying to answer and could not.
    """
    handshake = CancelCleanup()
    handshake.note_cancelled()

    assert handshake.begin_worker() is False
    assert handshake._state is CleanupState.ABORTED


def test_a_cancel_on_a_running_worker_hands_teardown_over() -> None:
    handshake = CancelCleanup()
    assert handshake.begin_worker() is True

    assert handshake.note_cancelled() is False
    assert handshake.caller_owns_teardown is False
    assert handshake.note_worker_done(child_reaped=True) is True


def test_a_cancel_after_the_worker_finished_returns_to_the_caller_side() -> None:
    """The BF-788 race that the loop-side branch exists for.

    The worker got there first and read no cancellation, so it declined; if the
    caller side also declined nobody would remove the directory.
    """
    handshake = CancelCleanup()
    handshake.begin_worker()
    assert handshake.note_worker_done(child_reaped=True) is False

    assert handshake.note_cancelled() is True
    # NOT the outer caller: the worker did start, so the loop side is the one
    # that removes -- which is why this is distinct from the ABORTED case.
    assert handshake.caller_owns_teardown is False


def test_an_uncancelled_run_leaves_teardown_with_its_creator() -> None:
    """Artifact capture reads the directory after ``run()`` returns."""
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.note_worker_done(child_reaped=True)

    assert handshake.caller_owns_teardown is True
    assert handshake.safe_to_remove is True


def test_an_unreaped_child_makes_removal_unsafe_for_everyone() -> None:
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.note_worker_done(child_reaped=False)

    assert handshake.safe_to_remove is False
    assert handshake._state is CleanupState.UNSAFE


def test_marking_unsafe_survives_a_later_optimistic_report() -> None:
    """A reap failure recorded mid-run must not be cleared on the way out.

    ``_run_sync_inner`` records it as it unwinds; ``_run_sync``'s ``finally``
    then reports ``child_reaped`` from whatever it can see, which on a
    propagating BaseException is nothing. Non-sticky UNSAFE would let that
    report delete the directory a live child is using.
    """
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.mark_unsafe("child 123 survived the reap")

    handshake.note_worker_done(child_reaped=True)

    assert handshake.safe_to_remove is False


# ── the graph is enforced, not merely drawn ───────────────────────


@pytest.mark.parametrize(
    ("terminal", "reaped"),
    [(CleanupState.REAPED, True), (CleanupState.UNSAFE, False)],
    ids=["reaped", "unsafe"],
)
def test_a_terminal_state_refuses_to_start_another_worker(
    terminal: CleanupState, reaped: bool,
) -> None:
    """Measured before this guard: ``UNSAFE -> begin_worker()=True -> RUNNING``.

    Not a cosmetic graph violation. ``RUNNING`` un-records the live child, the
    next ``note_worker_done`` writes ``REAPED``, and ``safe_to_remove`` goes
    back to True -- so a reused arbiter hands a directory a live process is
    holding to a remover, which is the one thing ``UNSAFE`` exists to prevent.
    """
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.note_worker_done(child_reaped=reaped)
    assert handshake._state is terminal, "premise: the state under test"

    with pytest.raises(RuntimeError, match="terminal states are final"):
        handshake.begin_worker()

    assert handshake._state is terminal, "the refused call moved the state anyway"
    assert handshake.safe_to_remove is reaped, (
        "the refused call changed who may remove the directory"
    )


def test_an_aborted_run_cannot_report_a_worker_that_never_ran() -> None:
    """``ABORTED -> note_worker_done(True) -> REAPED`` was reachable.

    Nothing in ``_run_sync`` can do it -- the callable returns before its
    ``try`` when ``begin_worker`` says no -- so reaching it means something has
    lost track of which run the arbiter belongs to. It mattered because the
    flip took ``caller_owns_teardown`` away from a caller that had already been
    told it owned the directory.
    """
    handshake = CancelCleanup()
    assert handshake.note_cancelled() is True
    assert handshake.caller_owns_teardown is True

    with pytest.raises(RuntimeError, match="no worker entered the callable"):
        handshake.note_worker_done(child_reaped=True)

    assert handshake._state is CleanupState.ABORTED
    assert handshake.caller_owns_teardown is True, (
        "the refused report took teardown away from the side that owns it"
    )


def test_a_reaped_run_is_not_reopened_by_a_late_report() -> None:
    """Why this one is refused SILENTLY where ``begin_worker`` raises.

    Two BF-788 tests publish the worker's completion by hand and then let the
    real worker's ``finally`` report again, so a second ``note_worker_done``
    after ``REAPED`` is a live path -- it re-reads who owns teardown and must
    leave the decision alone. Only a call that would MOVE a terminal state is
    a violation, and it is the move that is refused.
    """
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.note_worker_done(child_reaped=True)
    handshake.note_cancelled()

    assert handshake.note_worker_done(child_reaped=False) is True

    assert handshake._state is CleanupState.REAPED
    assert handshake.safe_to_remove is True


def test_marking_unsafe_refuses_to_reopen_a_finished_run() -> None:
    """``REAPED -> mark_unsafe() -> UNSAFE`` would leave the graph too.

    Unreachable from ``_run_sync_inner`` -- it only marks while it is inside
    the worker's ``try``, where the state is ``RUNNING`` -- so this raises for
    the same reason ``begin_worker`` does.
    """
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.note_worker_done(child_reaped=True)

    with pytest.raises(RuntimeError, match="terminal states are final"):
        handshake.mark_unsafe("child 123 survived the reap")

    assert handshake._state is CleanupState.REAPED


def test_recording_the_same_reap_failure_twice_is_not_a_transition() -> None:
    """``UNSAFE -> mark_unsafe()`` re-reports one fact; it does not move."""
    handshake = CancelCleanup()
    handshake.begin_worker()
    handshake.mark_unsafe("child 123 survived the reap")

    handshake.mark_unsafe("child 123 survived the reap")

    assert handshake._state is CleanupState.UNSAFE
    assert handshake.safe_to_remove is False


def test_only_the_first_claimant_takes_the_removal() -> None:
    handshake = CancelCleanup()

    assert handshake.claim() is True
    assert handshake.claim() is False


def test_concurrent_claims_admit_exactly_one() -> None:
    """Measured under BF-788: ``REMOVE_CALL_COUNT=2`` on separate threads."""
    handshake = CancelCleanup()
    barrier = threading.Barrier(8)
    won: list[int] = []

    def contender() -> None:
        barrier.wait(timeout=5)
        if handshake.claim():
            won.append(threading.get_ident())

    threads = [threading.Thread(target=contender) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(won) == 1, won


# ── residual 1: the start boundary ────────────────────────────────


def _start_boundary_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    honour_abort: bool,
) -> dict[str, Any]:
    """Wire the measured start-boundary race and return what was observed.

    Gating on ``SubprocessSandbox._run_sync`` -- the executor callable itself
    -- is what makes this discriminate. It is the correct boundary ONLY while
    the state transition is the first EFFECTFUL operation inside that callable
    (the ``cleanup_on_cancel`` read above it creates nothing); put anything
    that touches the filesystem or spawns above it and this stops testing
    anything, which is why
    ``test_the_worker_arbitrates_before_anything_can_be_created`` in the BF-788
    file pins that placement separately.

    ``honour_abort=False`` reverts exactly one thing in memory -- the worker's
    obedience -- so the corruption can be shown to come back.
    """
    outcome = tmp_path / "child_outcome.txt"
    entered, release, worker_done = (
        threading.Event(), threading.Event(), threading.Event(),
    )
    seen: list[ExecutionRequest] = []
    begin_calls: list[bool] = []
    popen_argv: list[list[str]] = []

    real_begin = CancelCleanup.begin_worker

    def recording_begin(self: CancelCleanup) -> bool:
        answer = real_begin(self)
        begin_calls.append(answer)
        # The in-memory revert of AD-1298's decisive property: a worker that
        # ignores the abort and proceeds is precisely HEAD.
        return True if not honour_abort else answer

    original_run_sync = SubprocessSandbox._run_sync

    def gated(self: SubprocessSandbox, request: ExecutionRequest):
        seen.append(request)
        # Stands in for AD-1074d staging: a file the script needs, present in
        # the workdir before any worker could have entered.
        assert request.workdir is not None
        (Path(request.workdir) / "input.txt").write_text("payload", encoding="utf-8")
        entered.set()
        release.wait(timeout=15)
        try:
            return original_run_sync(self, request)
        finally:
            worker_done.set()

    real_popen = subprocess.Popen

    class _Counting(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, argv, *a, **kw):
            popen_argv.append(list(argv))
            super().__init__(argv, *a, **kw)

    monkeypatch.setattr(CancelCleanup, "begin_worker", recording_begin)
    monkeypatch.setattr(SubprocessSandbox, "_run_sync", gated)
    monkeypatch.setattr(iso.subprocess, "Popen", _Counting)

    code = (
        "import pathlib\n"
        "try:\n"
        "    payload = pathlib.Path('input.txt').read_text()\n"
        f"    pathlib.Path(r'{outcome}').write_text('OK:' + payload)\n"
        "except Exception as exc:\n"
        f"    pathlib.Path(r'{outcome}').write_text(type(exc).__name__)\n"
        "    raise\n"
    )
    return {
        "outcome": outcome,
        "entered": entered,
        "release": release,
        "worker_done": worker_done,
        "seen": seen,
        "begin_calls": begin_calls,
        "popen_argv": popen_argv,
        "code": code,
    }


async def _drive_start_boundary(tmp_path: Path, s: dict[str, Any]) -> dict[str, Any]:
    """Run the scenario and hand back the facts, premise checked on the way."""
    tool = CodeExecutionTool(runtime=_runtime(tmp_path))
    task = asyncio.create_task(
        tool.invoke({"code": s["code"]}, {"thread_id": "t", "agent_id": "ezri"}),
    )
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, s["entered"].wait, 15)

    # PREMISE, part 1: the executor callable was entered. `_WorkItem.run`
    # calls `set_running_or_notify_cancel()` before invoking it, so being here
    # is what makes the future uncancellable -- the whole window under test.
    if not s["entered"].is_set():
        pytest.fail(
            "the executor callable never ran, so the cancellation below lands "
            "on a QUEUED job -- the ordinary case, not the start-boundary race "
            "this probe exists to reproduce"
        )
    # PREMISE, part 2: the state is still QUEUED. If the worker had already
    # arbitrated, the cancel would meet RUNNING and hand off cleanly, which is
    # a different (already-working) path.
    if s["begin_calls"]:
        pytest.fail(
            "begin_worker() had already run when the cancellation was "
            f"delivered (calls={s['begin_calls']}); the state was not QUEUED, "
            "so this probe did not reproduce the start-boundary race and its "
            "result means nothing"
        )

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The tool's REAL teardown has now run. Record what it did to the directory
    # the worker is about to be released into.
    workdir = Path(s["seen"][0].workdir)  # type: ignore[arg-type]
    observed = {
        "workdir_before_worker_entry": workdir.exists(),
        "staged_input_before_worker_entry": (workdir / "input.txt").exists(),
    }

    s["release"].set()
    await loop.run_in_executor(None, s["worker_done"].wait, 20)
    for _ in range(200):
        if s["outcome"].exists():
            break
        await asyncio.sleep(0.05)

    observed["launched"] = s["seen"][0].launch_outcome.launched  # type: ignore[union-attr]
    observed["popen_argv"] = list(s["popen_argv"])
    observed["begin_calls"] = list(s["begin_calls"])
    observed["child_outcome"] = (
        s["outcome"].read_text(encoding="utf-8") if s["outcome"].exists() else ""
    )
    observed["workdir"] = workdir
    return observed


@pytest.mark.asyncio
async def test_bf839_start_boundary_worker_honours_caller_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Residual 1, closed.

    The caller could not tell whether the future was still cancellable, and
    BF-788 spent ten rounds trying to make it tell. It does not need to: the
    caller records ABORTED under the lock, and the worker re-reads that as the
    first thing it does. The directory is deleted, the worker aborts BEFORE
    ``Popen``, and there is nothing to corrupt.
    """
    scenario = _start_boundary_scenario(tmp_path, monkeypatch, honour_abort=True)
    observed = await _drive_start_boundary(tmp_path, scenario)

    assert observed["begin_calls"] == [False], (
        "the worker did not arbitrate exactly once and get told to stop: "
        f"{observed['begin_calls']}"
    )
    assert observed["popen_argv"] == [], (
        "a child was spawned after the caller had already taken the directory "
        f"away: {observed['popen_argv']}"
    )
    assert observed["launched"] is False, (
        "the audit trail says a child was launched into a directory that had "
        "already been removed"
    )
    assert observed["child_outcome"] == "", (
        "a script ran beside a teardown that believed nothing would: it "
        f"reported {observed['child_outcome']!r}"
    )


@pytest.mark.asyncio
async def test_bf839_the_probe_reproduces_the_corruption_when_the_abort_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proof that the test above discriminates.

    Identical scenario, with the one thing AD-1298 adds at the start boundary
    reverted in memory: the worker ignores the abort and proceeds. The measured
    HEAD symptoms come back -- a child spawned into a directory the caller had
    already removed, and a script that died on the staged file it was given.

    Without this, a green test above is indistinguishable from a probe that
    never reproduced the race at all.
    """
    scenario = _start_boundary_scenario(tmp_path, monkeypatch, honour_abort=False)
    observed = await _drive_start_boundary(tmp_path, scenario)

    assert observed["workdir_before_worker_entry"] is False, (
        "the caller did not remove the directory, so this run does not "
        "reproduce the measured race"
    )
    assert observed["staged_input_before_worker_entry"] is False
    assert observed["popen_argv"], "no child was spawned; nothing was corrupted"
    assert observed["launched"] is True
    assert observed["child_outcome"] == "FileNotFoundError", (
        "the child did not die on the file it was staged with; the "
        f"reproduction is not the measured one (got {observed['child_outcome']!r})"
    )


@pytest.mark.asyncio
async def test_an_aborted_run_resolves_the_launch_question_as_not_launched(
    tmp_path: Path,
) -> None:
    """A deliberate change to AD-1247's audit contract.

    AD-1247 waited a bounded time for the launch answer and, when the bound
    expired, recorded ``launch_state=unknown`` with a warning that a script MAY
    have run. On a cancel that never reached a worker that bound could ONLY
    expire, so the trail carried an uncertainty that was not uncertain at all.

    ``ABORTED`` is a definite "no child will ever exist" -- the worker is
    contractually bound to honour it -- so the answer is available immediately
    and the record for a run that provably never started is not written. Cf.
    the standing distinction between *nothing was sent* and *sent and heard
    nothing*: only the first licenses acting as though the work did not happen.
    """
    from concurrent.futures import ThreadPoolExecutor

    audit = _Audit()
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=1)
    hold, occupied = threading.Event(), threading.Event()
    seen: list[ExecutionRequest] = []
    original = SubprocessSandbox.run

    async def spy(self, request: ExecutionRequest):
        seen.append(request)
        return await original(self, request)

    def occupy() -> None:
        occupied.set()
        hold.wait(timeout=15)

    loop.set_default_executor(pool)
    SubprocessSandbox.run = spy  # type: ignore[method-assign]
    try:
        pool.submit(occupy)
        assert occupied.wait(5), "the executor never became busy"

        tool = CodeExecutionTool(runtime=_runtime(tmp_path, audit=audit))
        task = asyncio.create_task(
            tool.invoke({"code": "print('x')"}, {"agent_id": "ezri"}),
        )
        await asyncio.sleep(0.5)      # submitted, queued behind `occupy`
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        SubprocessSandbox.run = original  # type: ignore[method-assign]
        hold.set()
        pool.shutdown(wait=True)

    assert seen, "the request never reached the sandbox"
    launch = seen[0].launch_outcome
    assert launch is not None
    assert launch.resolved.is_set(), (
        "an aborted job left the launch question open, so a caller's bounded "
        "wait can still only expire into a guess"
    )
    assert launch.launched is False
    assert audit.records == [], (
        "a run that provably never started was recorded as one that might "
        f"have: {audit.records}"
    )


# ── residual 2: the two unguarded communicate() exits ──────────────


async def _run_with_failing_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, via_timeout: bool,
) -> dict[str, Any]:
    """Drive the tool with a child that cannot be killed OR waited on.

    ``kill`` raises ``OSError`` so the real ``_kill`` fallbacks run and are
    exhausted; ``wait`` raises so the reap cannot be confirmed. Deterministic
    on both platforms -- ``os.killpg`` may genuinely succeed on POSIX, and the
    unconfirmable ``wait`` is what the decision rests on either way.

    Records every removal ATTEMPT and calls through to the real remover. An
    earlier version of this helper asserted only that the directory was still
    on disk when ``invoke`` returned, and it PASSED with the ``safe_to_remove``
    guard bypassed at both sites -- because the tool's escalation is dispatched
    rather than awaited, so the directory is still there for another ~3s while
    the retry loop works. Measured::

        MUTANT events=[tool_rmtree, _remove_workdir, tool_rmtree]
               leftover_immediate=[exec-036a...]  leftover_after_3s=[]

    The attempt is the fact; the timing was an artifact.
    """
    real_popen = subprocess.Popen
    spawned: list[Any] = []
    results: list[ExecutionResult] = []
    attempts: list[str] = []

    class _Unkillable(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._calls = 0
            spawned.append(self)

        def communicate(self, *a, **kw):
            self._calls += 1
            if via_timeout and self._calls == 1:
                raise subprocess.TimeoutExpired(cmd="script.py", timeout=1)
            raise OSError("injected pipe failure while the child is live")

        def kill(self):
            raise OSError("kill refused")

        def wait(self, *a, **kw):
            raise subprocess.TimeoutExpired(cmd="script.py", timeout=5)

    real_rmtree = cet.shutil.rmtree
    real_remove = iso._remove_workdir

    def spy_rmtree(path, **kw):
        attempts.append("tool_rmtree")
        return real_rmtree(path, **kw)

    def spy_remove(workdir, **kw):
        attempts.append("_remove_workdir")
        return real_remove(workdir, **kw)

    original = SubprocessSandbox.run

    async def spy(self, request: ExecutionRequest):
        result = await original(self, request)
        results.append(result)
        return result

    monkeypatch.setattr(iso.subprocess, "Popen", _Unkillable)
    monkeypatch.setattr(cet.shutil, "rmtree", spy_rmtree)
    monkeypatch.setattr(iso, "_remove_workdir", spy_remove)
    monkeypatch.setattr(cet, "_remove_workdir", spy_remove)
    monkeypatch.setattr(SubprocessSandbox, "run", spy)

    tool = CodeExecutionTool(runtime=_runtime(tmp_path))
    scratch = tmp_path / "scratch"

    def leftover() -> list[Path]:
        return sorted(scratch.glob("exec-*")) if scratch.exists() else []

    try:
        await tool.invoke(
            {"code": "import sys; sys.exit(0)"},
            {"thread_id": "t", "agent_id": "ezri"},
        )
        # Only meaningful if something tried: the escalation is dispatched, so
        # a removal that WAS attempted needs time to land. Nothing attempted
        # means nothing can land, so the green path pays no wait at all.
        if attempts:
            for _ in range(60):
                if not leftover():
                    break
                await asyncio.sleep(0.1)
        observed = {
            "result": results[0] if results else None,
            "attempts": attempts,
            "leftover": leftover(),
        }
    finally:
        for proc in spawned:                  # reap for real, outside the fakes
            try:
                real_popen.kill(proc)
                real_popen.wait(proc, timeout=5)
            except Exception:                 # noqa: BLE001 - test cleanup
                pass

    return observed


@pytest.mark.asyncio
async def test_a_child_that_survives_its_reap_blocks_the_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Residual 2, first exit.

    Measured on HEAD::

        FAILED_KILL returned_ExecutionResult=True child_alive_on_return=True

    The handler warned and re-raised; the honest-degrade arm turned that back
    into a result, and every caller reads a returned result as "the child is
    gone". Leaving a directory behind is a smaller problem than deleting one a
    live process is using, so the answer has to reach the cleanup decision
    rather than only the log.
    """
    observed = await _run_with_failing_reap(tmp_path, monkeypatch, via_timeout=False)

    assert observed["result"] is not None
    assert observed["result"].child_reaped is False, (
        "the result claims the child was reaped when the wait never confirmed it"
    )
    assert observed["result"].timed_out is False
    assert observed["attempts"] == [], (
        "a cleanup owner tried to remove a workdir an unreaped child still "
        f"holds: {observed['attempts']}"
    )
    assert observed["leftover"], (
        "the teardown removed a workdir that an unreaped child still holds"
    )


@pytest.mark.asyncio
async def test_a_failed_post_timeout_reap_keeps_the_timeout_and_the_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Residual 2, second exit -- the one that was outside every handler.

    Measured on HEAD::

        TIMEOUT_FOLLOWUP_FAILURE returned_ExecutionResult=True timed_out=False

    The retry after ``TimeoutExpired`` sat outside the reaping handler, so a
    failure there both left the child live AND reported the run as something
    other than the timeout it was.
    """
    observed = await _run_with_failing_reap(tmp_path, monkeypatch, via_timeout=True)

    assert observed["result"] is not None
    assert observed["result"].child_reaped is False
    assert observed["result"].timed_out is True, (
        "the run timed out, but the failure in the post-timeout retry erased "
        "that from the result the caller reads"
    )
    assert observed["attempts"] == [], (
        "a cleanup owner tried to remove a workdir an unreaped child still "
        f"holds: {observed['attempts']}"
    )
    assert observed["leftover"], (
        "the teardown removed a workdir that an unreaped child still holds"
    )


# ── the path the arbiter does not cover ───────────────────────────


async def _run_sandbox_owned_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, reapable: bool,
) -> dict[str, Any]:
    """Run with ``workdir=None``, so the SANDBOX picks the scratch dir.

    ``reapable=False`` makes ``kill`` and ``wait`` fail so
    ``_terminate_and_reap`` cannot confirm the child is gone -- the only way
    this path learns the directory is still in use. Both removal names are
    spied on, because the fact under test is that NOTHING tried.
    """
    real_popen = subprocess.Popen
    spawned: list[Any] = []
    attempts: list[str] = []

    class _Child(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            spawned.append(self)

        def communicate(self, *a, **kw):
            if reapable:
                return super().communicate(*a, **kw)
            raise OSError("injected pipe failure while the child is live")

        def kill(self):
            if reapable:
                return super().kill()
            raise OSError("kill refused")

        def wait(self, *a, **kw):
            if reapable:
                return super().wait(*a, **kw)
            raise subprocess.TimeoutExpired(cmd="script.py", timeout=5)

    def spy(workdir, **kw):
        attempts.append(str(workdir))

    monkeypatch.setattr(iso.subprocess, "Popen", _Child)
    monkeypatch.setattr(iso, "remove_workdir", spy)
    monkeypatch.setattr(iso, "_remove_workdir", spy)

    sandbox = SubprocessSandbox(scratch_root=tmp_path / "scratch")
    try:
        result = await sandbox.run(ExecutionRequest(
            code="import time; time.sleep(0.05)", timeout_seconds=30,
        ))
    finally:
        for proc in spawned:                  # reap for real, outside the fakes
            try:
                real_popen.kill(proc)
                real_popen.wait(proc, timeout=5)
            except Exception:                 # noqa: BLE001 - test cleanup
                pass

    return {"result": result, "attempts": attempts}


@pytest.mark.asyncio
async def test_a_sandbox_owned_workdir_is_kept_when_the_child_survives_its_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exported default path, which NEITHER ``CancelCleanup`` owner covers.

    ``ExecutionRequest.workdir`` defaults to None and both arbiter-side
    removals are gated on ``request.workdir is not None``, so on this path the
    ``UNSAFE`` state cannot reach the decision at all -- ``_run_sync_inner``'s
    ``finally`` removed unconditionally. Measured with the guard reverted::

        child_reaped=False REMOVE_ATTEMPTS=1

    On POSIX that deletes a live child's own cwd; on Windows it burns the ~9s
    retry budget on a directory already known to be held. It is the corruption
    AD-1298 exists to prevent, on the one path the fix did not reach.

    Asserted on the removal ATTEMPT: the remover is replaced by a spy here, so
    the directory is present either way and presence cannot discriminate.
    """
    observed = await _run_sandbox_owned_workdir(
        tmp_path, monkeypatch, reapable=False,
    )

    assert observed["result"].child_reaped is False, (
        "premise: the reap must have failed, or this run never reaches the "
        "guard under test"
    )
    assert observed["attempts"] == [], (
        "the sandbox removed a workdir it chose itself while an unreaped "
        f"child still holds it: {observed['attempts']}"
    )


@pytest.mark.asyncio
async def test_a_sandbox_owned_workdir_is_still_removed_on_a_clean_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What makes the test above discriminate rather than pass by accident.

    Identical wiring with a child that reaps normally: the ephemeral directory
    must still go, or "no removal attempt" would be true because the branch
    never runs.
    """
    observed = await _run_sandbox_owned_workdir(
        tmp_path, monkeypatch, reapable=True,
    )

    assert observed["result"].child_reaped is True
    assert len(observed["attempts"]) == 1, (
        "the sandbox stopped cleaning up the directory it chose itself: "
        f"{observed['attempts']}"
    )


# ── one removal, through real production ──────────────────────────


@pytest.mark.asyncio
async def test_the_worker_also_refuses_to_remove_an_unsafe_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BOTH owners consult ``safe_to_remove``, not just the tool.

    The tool-side tests above cannot reach this branch: an uncancelled run
    never gives the worker teardown in the first place, so a mutant that drops
    the worker's guard is inert there. The case that reaches it is a CANCELLED
    run whose child could not be reaped -- the worker owns the removal and is
    the only thing standing between an unreaped child and its files.
    """
    workdir = tmp_path / "unsafe_cancel"
    workdir.mkdir()
    (workdir / "held.txt").write_text("x", encoding="utf-8")

    entered, release = threading.Event(), threading.Event()
    removals: list[Path] = []
    monkeypatch.setattr(
        iso, "_remove_workdir", lambda w, **kw: removals.append(Path(w)),
    )

    sandbox = SubprocessSandbox(scratch_root=tmp_path)
    handshake = CancelCleanup()

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        entered.set()
        release.wait(timeout=10)
        # Stands in for `_run_sync_inner`'s degrade arm after a reap that could
        # not be confirmed: a result exists, but the child is still out there.
        return ExecutionResult(
            success=False, workdir=str(request.workdir), child_reaped=False,
        )

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    task = asyncio.create_task(sandbox.run(ExecutionRequest(
        code="print(1)", workdir=workdir, cleanup_on_cancel=handshake,
    )))
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, entered.wait, 5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert handshake.caller_owns_teardown is False, (
        "premise: the worker must own the teardown here, or this test cannot "
        "reach the guard it exists to pin"
    )

    release.set()
    await loop.run_in_executor(None, lambda: None)
    for _ in range(100):
        if handshake.safe_to_remove is False:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)

    assert handshake.safe_to_remove is False, "the failed reap was not recorded"
    assert removals == [], (
        "the worker owned the teardown and removed a directory an unreaped "
        f"child still holds: {removals}"
    )
    assert workdir.exists()


@pytest.mark.asyncio
async def test_exactly_one_production_site_removes_on_a_real_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Carried-over debt from BF-788: the exactly-once property was never
    tested through production.

    BF-788's version drove the handshake object with two synthetic threads, so
    deleting ``claim()`` from either production site left it green. This drives
    a real cancellation against a real child and instruments every site that
    can remove the directory -- the worker's ``finally``, ``run()``'s cancel
    handler, and the tool's teardown.

    **What actually arbitrates now, measured.** Removing ``claim()`` from all
    three sites at once leaves this file and the BF-788 file green (47 passed).
    That is not a hole: the lock-guarded state machine makes the owners
    mutually exclusive by construction, so ``claim()`` is no longer the thing
    standing between one removal and two. Mutating the ARBITER does turn this
    red -- forcing ``caller_owns_teardown`` True makes the tool remove the
    directory beside the live child. So the property is pinned; it is pinned to
    the state, which is where AD-1298 moved it.
    """
    removals: list[str] = []

    def recording_remove(workdir, **kw):
        removals.append(f"_remove_workdir:{threading.get_ident()}")

    def recording_rmtree(path, **kw):
        removals.append("tool_rmtree")

    monkeypatch.setattr(iso, "_remove_workdir", recording_remove)
    monkeypatch.setattr(cet, "_remove_workdir", recording_remove)
    monkeypatch.setattr(cet.shutil, "rmtree", recording_rmtree)

    mark = tmp_path / "mark.txt"
    code = (
        "import time, pathlib\n"
        f"pathlib.Path(r'{mark}').write_text('started')\n"
        "time.sleep(1.0)\n"
    )

    tool = CodeExecutionTool(runtime=_runtime(tmp_path))
    task = asyncio.create_task(
        tool.invoke({"code": code}, {"thread_id": "t", "agent_id": "ezri"}),
    )
    for _ in range(200):
        if mark.exists():
            break
        await asyncio.sleep(0.05)
    assert mark.exists(), "the child never reached its live point"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The worker is still holding the child; give its `finally` time to run.
    await asyncio.sleep(2.5)

    assert len(removals) == 1, (
        "a cancelled run must be removed exactly once -- two retry loops "
        f"occupy two executor threads and can both warn about it: {removals}"
    )
    assert removals[0].startswith("_remove_workdir:"), (
        "the tool removed the directory while a child was still live; the "
        f"hand-off did not happen: {removals}"
    )


@pytest.mark.asyncio
async def test_the_worker_removes_it_when_the_cancel_lands_mid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mirror of the start boundary: the worker took the lock first.

    The caller then hands off entirely rather than guessing, and the removal
    happens on the WORKER thread once the child has let go -- asserted on the
    thread identity, not merely on the directory being gone, because the caller
    removing it early leaves the same end state.
    """
    workdir = tmp_path / "midrun"
    workdir.mkdir()
    (workdir / "held.txt").write_text("x", encoding="utf-8")

    entered, release = threading.Event(), threading.Event()
    worker_ident: list[int] = []
    remover_ident: list[int] = []

    monkeypatch.setattr(
        iso, "_remove_workdir",
        lambda w, **kw: remover_ident.append(threading.get_ident()),
    )

    sandbox = SubprocessSandbox(scratch_root=tmp_path)

    def fake_inner(request: ExecutionRequest) -> ExecutionResult:
        worker_ident.append(threading.get_ident())
        entered.set()
        release.wait(timeout=10)
        return ExecutionResult(success=True, workdir=str(request.workdir))

    sandbox._run_sync_inner = fake_inner  # type: ignore[method-assign]

    handshake = CancelCleanup()
    task = asyncio.create_task(sandbox.run(ExecutionRequest(
        code="print(1)", workdir=workdir, cleanup_on_cancel=handshake,
    )))
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, entered.wait, 5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert handshake.caller_owns_teardown is False, (
        "the caller kept teardown while a worker was inside the callable"
    )
    assert not remover_ident, "the caller removed it beside a live child"

    release.set()
    for _ in range(200):
        if remover_ident:
            break
        await asyncio.sleep(0.02)

    assert remover_ident == worker_ident, (
        "the removal did not happen on the worker thread that owned it: "
        f"remover={remover_ident} worker={worker_ident}"
    )


# ── the ownership boundary ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_colliding_workdir_is_not_adopted_and_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mkdir(exist_ok=False)`` is what turns responsibility into ownership.

    The tool set its teardown flag before ``mkdir`` deliberately -- an
    interrupt in that window used to leak the directory. But with
    ``exist_ok=True`` the flag could also be set for a directory this run did
    NOT create, and the teardown would then delete another owner's files. A
    ``uuid4`` collision is unlikely; adopting-and-deleting on one is not a risk
    worth carrying for nothing.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    real_mkdir = Path.mkdir
    victim: list[Path] = []

    def colliding_mkdir(self: Path, *a, **kw):
        if self.name.startswith("exec-") and not victim:
            # Someone else got this path first, and their files are in it.
            real_mkdir(self, parents=True, exist_ok=True)
            (self / "not_ours.txt").write_text("theirs", encoding="utf-8")
            victim.append(self)
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", colliding_mkdir)

    result = await CodeExecutionTool(runtime=_runtime(tmp_path)).invoke(
        {"code": "print('ok')"}, {"thread_id": "t", "agent_id": "ezri"},
    )
    monkeypatch.undo()

    assert victim, "the collision was never set up; this proves nothing"
    assert result.error, "a colliding workdir was silently adopted"
    assert (victim[0] / "not_ours.txt").exists(), (
        "the run adopted a directory it did not create and deleted the files "
        "of whoever did"
    )
