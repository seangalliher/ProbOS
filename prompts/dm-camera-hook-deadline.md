# DM camera hook: one deadline bounds every step, and the DM route times a send that raises

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16
**Status:** ready to build on the merge of #1823 (head `0a3ef965`, tree `7db7edd7`). Every anchor was read on tree `7db7edd7`. `git diff --stat 2c756a93 HEAD` over every product and test file this contract edits, runs or cites is empty, so the line numbers are the same on `2c756a93`. **Owning issue:** #1808 (BF-977, already allocated). Commits say `Refs #1808.` This contract is saved as `prompts/dm-camera-hook-deadline.md`.
**Dependencies:** none beyond #1823's merge.
**Estimated tests:** 6 new tests in a new file, `tests/test_dm_camera_hook_deadline.py`: 4 `built` and 2 controls. No test removed or changed.
**Size:** about 45 product lines in `src/probos/perception/consumer.py` and about 8 in `src/probos/routers/agents.py`. The rest is tests and trackers.

## 1. Problem

`VisionConsumer.force_describe_current_frame` (`perception/consumer.py:722-872`) has a docstring calling `timeout_s` "a hard wall-clock cap" (`:738-741`). It bounds one step, `_process`, with `asyncio.wait_for` (`:822-832`). The storage pre-check (`:787`) and post-check (`:843`) are awaited with no bound. Both callers pass `timeout_s=4.0` and add no outer bound: the DM route (`routers/agents.py:3491`) and the group round (`routers/thread_fanout.py:406`). So a slow attachment store holds the DM route and the group round without limit.

The issue proposed `asyncio.timeout(timeout_s)` around the body. That is not enough for the live store. `FilesystemAttachmentStore.exists` calls `_find` (`attachments/filesystem_store.py:417-419`). `_find` runs its glob through `_run` (`:400-402`). `_run` awaits `asyncio.shield(call)`, and when it is cancelled it awaits `_finish_cancelled(call)` before it re-raises (`:193-197`). `_finish_cancelled` waits until the thread's call is done (`:55-72`). So a cancellation inside the caller's own task returns only when the store's thread returns.

On the DM route, the `BF-932: dm route` line is written after the send (`agents.py:3694-3708`), not in a `finally`. A send that raises, such as a denial with `raise_on_denial=True`, writes no line.

## 2. Solution overview

- **Consumer.** The steps move, unchanged except for the step labels, into `_force_describe_owned`. That method runs as a task. The caller waits for it with `asyncio.wait((work,), timeout=timeout_s)`. At the deadline the caller cancels the task, does not await it, logs one WARNING naming the step reached, and returns `None`. The task holds the BF-666 permit until its step ends. A strong reference to the task is kept in a set until it ends. If the caller is itself cancelled, it cancels the task and waits for the task to end, as the base caller did. The inner `wait_for` goes. The docstring is corrected.
- **DM route.** The send moves into `try/finally`. The `finally` stamps `_t_send1` and writes the line with `sent=yes`, `no` or `raised`.
- **Group round.** No change (D4).

Rejected designs:
- **`asyncio.timeout` around the steps** (the issue's proposal). It cannot release the caller while the store waits for its thread (section 1). T3 and MU2 measure this.
- **A deadline per store call.** The describe step also reads the store (`consumer.py:558`) and uses threads (`:995`), so it would need the same pattern in several places.
- **Changing the store's cancellation.** BF-918 chose to wait for the thread on purpose. The issue's Limits leave the store alone (#1670).

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | **The deadline** is `asyncio.wait` on a task that runs the steps. At the deadline the task is cancelled and not awaited. The inner `wait_for` goes. Python is 3.12 or later (`pyproject.toml:9`), so `asyncio.timeout` is available, but D1 rejects it on the merits. | Section 1: a cancellation in the caller's own task waits for the store's thread. One deadline now covers `_process`, so a second one inside it would only mislabel the step. Its `TimeoutError` handler (`:827-832`) goes with it. A `TimeoutError` raised inside `_process` for another reason reaches the existing `except Exception` (`:835-840`). |
| D2 | **The permit** is `_force_describe_permit` (`:447-463`), an `asyncio.Lock` acquired with a 0.001 s wait. A call that cannot acquire it returns `None`. The task acquires it, so it covers every step: the frame selection, the storage pre-check (`step=preflight`), the describe (`step=describe`: `_process`, which does the frame read `:558`, the vision call `:629`, the identity check `:640`, the working-memory write `:678-680`, the episode anchor `:691` and the observer `:703-719`) and the storage post-check (`step=postcheck`). | The cancellation lands at the task's current await. In a cancellable await, the task ends at once. In the store's `_run`, the task waits for the thread (`filesystem_store.py:193-197`) and keeps the permit until then, so calls made meanwhile return `None` at once rather than queueing more store threads. The identity check's `run_in_executor` (`consumer.py:995`) is not shielded, so its await ends at once and the thread finishes on its own with its result discarded. `consumer.py` starts no subprocess (search below). The caller sees `None` and one WARNING containing `force_describe timed out` and `step=<step>`. That substring is pinned by `tests/test_ad733c1_force_describe.py:192`. |
| D3 | **Working memory.** An observation written before a later step times out stays. The docstring says so (P2-3). | The write is a synchronous `wm.append` (`:680`), so a cancellation cannot split it. The consumer has no undo path. T2 pins this. |
| D4 | **The route line** is written in a `finally`. `_sent` starts as `"raised"` and is set after the send returns: `"no"` for a held thread, `"yes"` otherwise. The fields are unchanged: `intent agent thread_ms prep_ms hook hook_ms dispatch_ms send_ms total_ms sent`. The exception propagates unchanged because the `finally` does not catch it. `emit_line` never raises (`utils/step_timing.py:36-43`). **`thread_fanout.py` gets no edit.** | `_maybe_force_describe_frame` (`thread_fanout.py:386-410`) awaits the same method, which now returns by its deadline. The issue names only the DM route's line, and the group round has no `BF-932` or `emit_line` call (search below). |
| D5 | **Tests.** A store that never answers blocks on an `asyncio.Event` (T1, T2) or, in its own thread, on a `threading.Event` (T3). The test sets the event only during cleanup. Each call passes `timeout_s=0.2`, and the test waits at most 3.0 s for it. | The base never returns, so any finite bound tells the base from the build, and 3.0 s absorbs a loaded Windows host (BF-981, #1523 F-1). On the base each `built` consumer case costs 3 s. A gated thread gives up after 30 s, so a failing test strands no thread. |
| D6 | **Nothing is persisted, and no config field, flag or baseline changes.** | The searches are listed under Absence Verified. `VisionConsumer` gains 1 direct method. Its `srp-size` row already carries both `lines` and `methods` (`docs/development/architecture-baseline.yaml:836-840`), so the trigger set is unchanged. The new class has one method. |

## 4. Milestones and commits

The Builder is `claude-sonnet-5.5`, with at most about 150 tool calls per milestone. It searches first and then reads the range. It runs only the focused tests named here; the orchestrator runs the broad gate. Stage only the named files and never use `git add -A`. Every SEARCH must match exactly once at its turn. If one does not, stop and report.

- **M1:** P1-1.
  - Run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_dm_camera_hook_deadline.py -n 0 -p no:randomly -q`. Expected: 2 passed, 4 xfailed (about 10 s).
  - Subject: `DM camera hook tests: a slow store step answers by the deadline and a raised send is timed (expected failures until the build)`
  - Body: `Adds four cases that fail on the base at their own assert, marked strict expected failures until the build, and two controls that pass on the base. Three drive the vision consumer with a store that never answers: before the describe, after it, and in the store's own thread. One drives the DM route with a send that is denied.` Then `Refs #1808.` and the trailer.
- **M2:** P2-1 to P2-7 (`consumer.py`), P2-8 (`agents.py`), P2-9 (the marker becomes a no-op).
  - Run the section 8.2 command.
  - Subject: `DM camera hook bounds every step with one deadline, and the DM route times a send that raises`
  - Body: `The camera hook's steps run in a task of their own; the caller waits for it with one deadline, then logs the step reached, cancels the task and returns without a frame. The task keeps the force permit until its step ends, so calls made meanwhile return at once. The DM route writes its timing line in a finally, with sent=yes, no or raised; the exception still propagates.` Then `Refs #1808.` and the trailer.
- **M3:** P3-1 and P3-2.
  - Run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` (no `--online`). Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` if `git status` shows them changed.
  - Run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q`.
  - Subject: `Trackers for the DM camera hook's deadline`
  - Body: `PROGRESS.md and DECISIONS.md entries; ledger regenerated.` Then `Refs #1808.` and the trailer.

I checked the three subjects and bodies by eye against the issue's list of closing words, including inside other words, and for `AD-` and `BF-` tokens. They contain none.

## 5. Behaviour table (after M2)

| Where the hook is blocked at the deadline | Caller on the base | Caller after M2 |
|---|---|---|
| storage pre-check, cancellable await | waits until the store answers | `None` at the deadline; WARNING `step=preflight` |
| storage pre-check inside the filesystem store's thread | waits until the thread returns | `None` at the deadline; the task keeps the permit until the thread returns |
| describe (`_process`) | `None` at the deadline; WARNING | `None` at the deadline; WARNING `step=describe` |
| storage post-check | waits until the store answers | `None` at the deadline; WARNING `step=postcheck`; the working-memory observation stays |
| caller cancelled | waits for the cancelled step, then re-raises | the same |

| DM route send | Base line | After M2 |
|---|---|---|
| returns | `sent=yes` | `sent=yes` |
| thread held, nothing sent | `sent=no` | `sent=no` |
| raises | no line; the exception propagates | one line with `sent=raised`; the same exception propagates |

## 6. The contract

### 6.1 M1: new test file

**P1-1** (`tests/test_dm_camera_hook_deadline.py`: new file)
```python
"""The DM camera hook answers by its deadline whichever step is slow, and the DM route times a send that raises (#1808).

``VisionConsumer.force_describe_current_frame`` bounded only its describe step: the storage checks before and after
it could hold the DM route and the group round without limit. Its steps now run in a task of their own and the
caller waits for that task with one deadline. The DM route's timing line is written in a ``finally``.

Synthetic fixtures only. A store that never answers blocks on an event the test sets only when it cleans up, so the
base never returns and the bound below tells the base from the build however loaded the host is. Until M2 the cases
marked ``built`` are strict expected failures: each fails on the base at its own assert. M2 makes ``built`` a no-op.
The unmarked cases are controls that pass on the base and after.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.mesh.intent import IntentAuthorizationDenied
from probos.perception.consumer import (
    VisionConsumer,
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.chat import _ATTACHMENT_STORE_CACHE, _get_attachment_store
from probos.types import IntentMessage, LLMResponse
from tests.test_bf932_reply_path_timing import _ROUTE, _dm, _field, _lines, _runtime

# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1808: the hook bounds only its describe step until M2")

_DEADLINE = 0.2  # the timeout_s each bounded call passes
_BOUND = 3.0  # how long a test waits for a call before it fails; generous for a loaded host
_THREAD_CAP = 30.0  # a gated store thread gives up after this, so a failing test strands no thread
_TIMED_OUT = "force_describe timed out"
_DESCRIPTION = "A current frame."


@pytest.fixture(autouse=True)
def _reset_module_state() -> Any:
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()
    yield
    reset_working_memories_for_tests()
    _ATTACHMENT_STORE_CACHE.clear()


def _vision_runtime(tmp_path: Path) -> SimpleNamespace:
    """Real config and attachment store; the vision model and the episode store are service-level stubs."""
    config = SystemConfig()
    config.perception.enabled = True
    config.attachments.attachments_dir = str(tmp_path / "attachments")
    return SimpleNamespace(
        config=config,
        intent_bus=SimpleNamespace(),
        episodic_memory=SimpleNamespace(store=AsyncMock(return_value=None)),
        llm_client=SimpleNamespace(
            complete=AsyncMock(return_value=LLMResponse(content=_DESCRIPTION, model="vision-fake")),
        ),
        profile_store=None,
    )


def _consumer(runtime: SimpleNamespace) -> VisionConsumer:
    consumer = VisionConsumer(runtime, min_interval_seconds=0.0)
    consumer.register_observer("ezri")
    return consumer


async def _frame(
    runtime: SimpleNamespace, consumer: VisionConsumer,
) -> tuple[FilesystemAttachmentStore, str, float]:
    buf = BytesIO()
    Image.new("RGB", (16, 16), color=(80, 120, 160)).save(buf, "JPEG", quality=80)
    blob = buf.getvalue()
    sha = hashlib.sha256(blob).hexdigest()
    store = _get_attachment_store(runtime)
    assert isinstance(store, FilesystemAttachmentStore)
    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    captured_at = time.time()
    consumer.record_uploaded_frame(sha, "s1", captured_at)
    return store, sha, captured_at


def _timed_out(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and _TIMED_OUT in r.getMessage()
    ]


async def _settle(*tasks: asyncio.Task[Any]) -> None:
    """End the test's own calls: wait up to the bound, then cancel what is left."""
    if not tasks:
        return
    _done, pending = await asyncio.wait(tasks, timeout=_BOUND)
    for task in pending:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _permit_free(consumer: VisionConsumer) -> bool:
    deadline = time.monotonic() + _BOUND
    while consumer._force_describe_lock.locked() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    return not consumer._force_describe_lock.locked()


def _others_done() -> bool:
    current = asyncio.current_task()
    return all(task.done() for task in asyncio.all_tasks() if task is not current)


class _GatedRoot:
    """The store's root, except that ``glob`` blocks in the store's own thread until the test opens the gate."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.calls = 0

    def glob(self, pattern: str) -> Any:
        self.calls += 1
        self.entered.set()
        self.gate.wait(_THREAD_CAP)
        return self._root.glob(pattern)


@built
@pytest.mark.asyncio
async def test_t1_preflight_store_that_never_answers_returns_none_by_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills R0 (the base bounds only ``_process``), MU1 and MU3."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, _sha, _captured_at = await _frame(runtime, consumer)
    never = asyncio.Event()

    async def _exists(_content_hash: str) -> bool:
        await never.wait()
        return True

    monkeypatch.setattr(store, "exists", _exists)
    caplog.set_level(logging.WARNING)
    call = asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE))
    try:
        done, _pending = await asyncio.wait((call,), timeout=_BOUND)
        assert call in done, "the call still waits on the storage pre-check"
        assert call.result() is None
        lines = _timed_out(caplog)
        assert len(lines) == 1 and "step=preflight" in lines[0], lines
        runtime.llm_client.complete.assert_not_awaited()
    finally:
        never.set()
        await _settle(call)


@built
@pytest.mark.asyncio
async def test_t2_postcheck_store_that_never_answers_returns_none_and_keeps_the_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills R0, MU1 and MU4. The observation written before the post-check stays in working memory."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, sha, captured_at = await _frame(runtime, consumer)
    real_exists = store.exists
    exists_calls: list[str] = []
    never = asyncio.Event()

    async def _exists(content_hash: str) -> bool:
        exists_calls.append(content_hash)
        if len(exists_calls) == 1:
            return await real_exists(content_hash)
        await never.wait()
        return True

    observation = VisionObservation(
        timestamp=time.time(),
        attachment_ref=sha,
        description="Written before the post-check.",
        novelty_score=1.0,
        session_id="s1",
    )

    async def _process(
        _msg: IntentMessage, *, cache_candidate: tuple[str, float] | None = None,
    ) -> VisionObservation:
        assert cache_candidate == (sha, captured_at)
        get_or_create_working_memory("ezri").append(observation)
        return observation

    monkeypatch.setattr(store, "exists", _exists)
    monkeypatch.setattr(consumer, "_process", _process)
    caplog.set_level(logging.WARNING)
    call = asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE))
    try:
        done, _pending = await asyncio.wait((call,), timeout=_BOUND)
        assert call in done, "the call still waits on the storage post-check"
        assert call.result() is None
        assert len(exists_calls) == 2
        lines = _timed_out(caplog)
        assert len(lines) == 1 and "step=postcheck" in lines[0], lines
        kept = [e.description for e in get_or_create_working_memory("ezri").entries()]
        assert kept == ["Written before the post-check."]
    finally:
        never.set()
        await _settle(call)


@built
@pytest.mark.asyncio
async def test_t3_store_thread_that_never_returns_does_not_hold_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Kills R0, MU1, MU2 and MU3. The real store waits for its own thread after a cancellation, so only a
    caller that does not await its cancelled step returns by the deadline; the step keeps the permit meanwhile."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, _sha, _captured_at = await _frame(runtime, consumer)
    gated = _GatedRoot(store._root)
    monkeypatch.setattr(store, "_root", gated)
    caplog.set_level(logging.WARNING)
    calls: list[asyncio.Task[Any]] = []
    try:
        calls.append(asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE)))
        done, _pending = await asyncio.wait((calls[0],), timeout=_BOUND)
        assert calls[0] in done, "the call still waits on the store's thread"
        assert calls[0].result() is None
        lines = _timed_out(caplog)
        assert len(lines) == 1 and "step=preflight" in lines[0], lines
        assert await asyncio.to_thread(gated.entered.wait, _BOUND)
        calls.append(asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_DEADLINE)))
        done, _pending = await asyncio.wait((calls[1],), timeout=_BOUND)
        assert calls[1] in done and calls[1].result() is None
        assert gated.calls == 1
        gated.gate.set()
        assert await _permit_free(consumer), "the permit outlived the store's thread"
    finally:
        gated.gate.set()
        await _settle(*calls)
        store.close()


@built
@pytest.mark.asyncio
async def test_t4_denied_send_writes_one_route_line_with_sent_raised(caplog: pytest.LogCaptureFixture) -> None:
    """Kills R0b (the base writes the line only after a send that returns), MU7 and MU8."""
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    runtime = _runtime([])
    denial = IntentAuthorizationDenied("direct_message", "test-hook", "send")
    runtime.intent_bus.send = AsyncMock(side_effect=denial)
    with pytest.raises(IntentAuthorizationDenied) as raised:
        await _dm(runtime)
    assert raised.value is denial
    lines = _lines(caplog, _ROUTE)
    assert len(lines) == 1, lines
    assert _field(lines[0], "sent") == "raised"
    assert _field(lines[0], "hook") == "ran"
    assert float(_field(lines[0], "send_ms")) >= 0.0


@pytest.mark.asyncio
async def test_t5_describe_inside_the_deadline_returns_its_description(tmp_path: Path) -> None:
    """Control (passes on the base). Kills MU9."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    await _frame(runtime, consumer)
    assert await consumer.force_describe_current_frame("s1", timeout_s=5.0) == _DESCRIPTION


@pytest.mark.asyncio
async def test_t6_cancelled_caller_waits_for_the_store_thread_then_frees_the_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control (passes on the base). Kills MU5: a cancelled caller cancels its task and waits for it, so the
    permit is free and no task is left when the caller's cancellation surfaces."""
    runtime = _vision_runtime(tmp_path)
    consumer = _consumer(runtime)
    store, _sha, _captured_at = await _frame(runtime, consumer)
    gated = _GatedRoot(store._root)
    monkeypatch.setattr(store, "_root", gated)
    caller = asyncio.create_task(consumer.force_describe_current_frame("s1", timeout_s=_THREAD_CAP))
    try:
        assert await asyncio.to_thread(gated.entered.wait, _BOUND)
        caller.cancel()
        done, _pending = await asyncio.wait((caller,), timeout=0.3)
        assert caller not in done, "the cancelled caller left before its store thread ended"
        gated.gate.set()
        done, _pending = await asyncio.wait((caller,), timeout=_BOUND)
        assert caller in done and caller.cancelled()
        assert consumer._force_describe_lock.locked() is False
        assert _others_done()
    finally:
        gated.gate.set()
        await _settle(caller)
        store.close()
```

### 6.2 M2: `consumer.py`, `agents.py` and the marker

**P2-1** (`src/probos/perception/consumer.py`: the progress holder)
SEARCH:
```
_LatestFrameCandidate = tuple[str, float]
```
REPLACE:
```
_LatestFrameCandidate = tuple[str, float]


class _ForceDescribeProgress:
    """BF-977: the step one force-describe has reached and its frame, read by the caller at the deadline."""

    __slots__ = ("sha", "step")

    def __init__(self) -> None:
        self.step = "permit"
        self.sha = ""
```

**P2-2** (`src/probos/perception/consumer.py`: the task references)
SEARCH:
```
        self._latest_frame_lock = Lock()
        self._force_describe_lock = asyncio.Lock()
```
REPLACE:
```
        self._latest_frame_lock = Lock()
        self._force_describe_lock = asyncio.Lock()
        # BF-977: the force-describe tasks still running, held until each ends
        # (a task its caller stopped waiting for drains here).
        self._force_describe_work: set[asyncio.Task[str | None]] = set()
```

**P2-3** (`src/probos/perception/consumer.py`: the docstring, the caller's deadline and the task's method header)
SEARCH:
```
        ``timeout_s`` is a hard wall-clock cap: the caller (DM hook) must
        not block on a slow vision tier. BF-304 single-flight lock means
        spamming this call collapses to one describe per supervisor
        window.
        """
        async with self._force_describe_permit() as acquired:
```
REPLACE:
```
        BF-977: ``timeout_s`` bounds the caller's wait for every step: the
        permit, the storage pre-check, the describe (``_process``: the frame
        read, the vision call, the identity check, the working-memory write,
        the episode anchor and the proactive observer) and the storage
        post-check. The steps run as a task of their own
        (``_force_describe_owned``). At the deadline this method logs a
        WARNING naming the step reached, cancels the task and returns
        ``None`` without waiting for it. A step blocked in a thread ends only
        when that thread returns (the filesystem store waits for its own
        thread after a cancellation, BF-918); until then the task keeps the
        force permit, so calls made meanwhile return ``None`` at once. An
        observation already written to working memory stays when a later
        step times out. A caller that is itself cancelled cancels the task
        and waits for it to end. BF-304 single-flight lock means spamming
        this call collapses to one describe per supervisor window.
        """
        progress = _ForceDescribeProgress()
        work = asyncio.create_task(
            self._force_describe_owned(session_id, progress),
        )
        self._force_describe_work.add(work)
        work.add_done_callback(self._force_describe_work.discard)
        try:
            done, _pending = await asyncio.wait((work,), timeout=timeout_s)
        except asyncio.CancelledError:
            work.cancel()
            await asyncio.wait((work,))
            raise
        if work in done:
            return work.result()
        work.cancel()  # BF-977: not awaited; the task keeps the permit until its step ends
        logger.warning(
            "BF-977: force_describe timed out after %.1fs at step=%s sha=%s; "
            "the caller proceeds without a fresh frame",
            timeout_s, progress.step, progress.sha[:8],
        )
        return None

    async def _force_describe_owned(
        self,
        session_id: str | None,
        progress: _ForceDescribeProgress,
    ) -> str | None:
        """BF-977: the force-describe steps, run as the task the caller waits on; ``progress`` names the step."""
        async with self._force_describe_permit() as acquired:
```

**P2-4** (`src/probos/perception/consumer.py`: the frame is recorded for the WARNING)
SEARCH:
```
            sha, captured_at = candidate
            max_age = self._force_describe_max_age_seconds()
```
REPLACE:
```
            sha, captured_at = candidate
            progress.sha = sha
            max_age = self._force_describe_max_age_seconds()
```

**P2-5** (`src/probos/perception/consumer.py`: the pre-check step)
SEARCH:
```
            try:
                exists = await store.exists(sha)
```
REPLACE:
```
            progress.step = "preflight"
            try:
                exists = await store.exists(sha)
```

**P2-6** (`src/probos/perception/consumer.py`: the describe step; the inner `wait_for` goes)
SEARCH:
```
            try:
                produced_observation = await asyncio.wait_for(
                    self._process(synthetic, cache_candidate=candidate),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "AD-733c-1: force_describe timed out after %.1fs sha=%s",
                    timeout_s, sha[:8],
                )
                return None
            except asyncio.CancelledError:
```
REPLACE:
```
            progress.step = "describe"
            try:
                produced_observation = await self._process(
                    synthetic, cache_candidate=candidate,
                )
            except asyncio.CancelledError:
```

**P2-7** (`src/probos/perception/consumer.py`: the post-check step)
SEARCH:
```
            try:
                still_exists = await store.exists(sha)
```
REPLACE:
```
            progress.step = "postcheck"
            try:
                still_exists = await store.exists(sha)
```

**P2-8** (`src/probos/routers/agents.py`: the send in try/finally, the line in the finally)
SEARCH:
```
    _t_send0 = time.perf_counter()  # BF-932: log-only
    result = None if _held_notice else await runtime.intent_bus.send(
        intent, raise_on_denial=True,
    )
    _t_send1 = time.perf_counter()
    # BF-932: one line per Captain DM: where its time went before the agent's turn and during it (milliseconds, monotonic
    # clock). ``intent`` is the id the agent's own ``BF-932: dm turn`` line carries.
    emit_line(
        logger,
        "BF-932: dm route intent=%s agent=%s thread_ms=%.0f prep_ms=%.0f hook=%s hook_ms=%.0f dispatch_ms=%.0f "
        "send_ms=%.0f total_ms=%.0f sent=%s",
        intent.id[:8], agent_id[:12], ms_between(_t_entry, _t_thread), ms_between(_t_thread, _t_vision), _hook,
        ms_between(_t_hook0, _t_hook1), ms_between(_t_vision, _t_send0) - ms_between(_t_hook0, _t_hook1),
        ms_between(_t_send0, _t_send1), ms_between(_t_entry, _t_send1), "no" if _held_notice else "yes",
    )
```
REPLACE:
```
    _t_send0 = time.perf_counter()  # BF-932: log-only
    # BF-977: the line is written whether the send returns or raises. ``sent`` is yes, no (a held thread: nothing
    # sent) or raised (a denial or any other exception, which propagates unchanged).
    _sent = "raised"
    try:
        result = None if _held_notice else await runtime.intent_bus.send(
            intent, raise_on_denial=True,
        )
        _sent = "no" if _held_notice else "yes"
    finally:
        _t_send1 = time.perf_counter()
        # BF-932: one line per Captain DM: where its time went before the agent's turn and during it (milliseconds,
        # monotonic clock). ``intent`` is the id the agent's own ``BF-932: dm turn`` line carries.
        emit_line(
            logger,
            "BF-932: dm route intent=%s agent=%s thread_ms=%.0f prep_ms=%.0f hook=%s hook_ms=%.0f dispatch_ms=%.0f "
            "send_ms=%.0f total_ms=%.0f sent=%s",
            intent.id[:8], agent_id[:12], ms_between(_t_entry, _t_thread), ms_between(_t_thread, _t_vision), _hook,
            ms_between(_t_hook0, _t_hook1), ms_between(_t_vision, _t_send0) - ms_between(_t_hook0, _t_hook1),
            ms_between(_t_send0, _t_send1), ms_between(_t_entry, _t_send1), _sent,
        )
```

**P2-9** (`tests/test_dm_camera_hook_deadline.py`: the marker becomes a no-op)
SEARCH:
```
# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1808: the hook bounds only its describe step until M2")
```
REPLACE:
```
def built(func):
    """The built cases failed on the base at their own assert and pass now; the marker is a no-op."""
    return func
```

### 6.3 M3: trackers

**P3-1** (`PROGRESS.md`: entry under the title)

The title line occurs once in the file and does not move. Other batches also insert directly under it; whichever entry is applied last sits on top.

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**The DM camera hook answers by its deadline whichever step is slow, and the DM route's timing line is written when the send raises (2026-11-16), #1808.**
- **Base.** Before a Captain DM or a group round, a hook describes the latest camera frame. Its docstring called its timeout a hard wall-clock cap, but only the describe step was bounded. The storage checks before and after it were not, so a slow attachment store held the DM route and the group round without limit. The route's timing line was written only after a send that returned.
- **Change.** The hook's steps (the permit, the storage pre-check, the describe and the storage post-check) run in a task of their own. The caller waits for that task with one deadline. At the deadline it logs a WARNING naming the step, cancels the task and returns without a fresh frame, without waiting for the cancelled step. A deadline inside the caller's own task would not have been enough: the filesystem store waits for its own thread after a cancellation. One new case covers that store. The task keeps the hook's permit until its step ends, so calls made meanwhile return at once. An observation already written to working memory stays. A cancelled caller still waits for its task, as before. The DM route writes its timing line in a finally, with sent=yes, no or raised, and the exception propagates unchanged. No config field or persisted state changes. `tests/test_dm_camera_hook_deadline.py` adds six cases.
- **Limits.** The deadline bounds what the caller sees, not the store. A step blocked in the store's thread runs until that thread returns, and until then the hook gives no fresh frame. The store itself is not tuned here (#1670). The decisions are in DECISIONS.md; the contract is `prompts/dm-camera-hook-deadline.md`.
```

**P3-2** (`DECISIONS.md`: entry directly before the DM reply path's timing entry, found by its heading text)

The heading text occurs once in `DECISIONS.md`. Among prompts outside `prompts/archive/`, only the already-built contract `prompts/bf-930-932-voice-and-reply-path-timing.md` contains it.

SEARCH:
```markdown
### BF-932 slice 2 -- The Captain-DM reply path logs its own timeline, log-only (2026-11-13, #1670)
```
REPLACE:
```markdown
### The DM camera hook bounds every step with one deadline, and the DM route's timing line survives a raised send (2026-11-16, #1808)

- *Scope.* `perception/consumer.py`: `force_describe_current_frame`, a new `_force_describe_owned`, a progress holder and a set of task references. `routers/agents.py`: the send and its timing line in a try/finally. One new test file, `tests/test_dm_camera_hook_deadline.py`. No config, event or schema change. Contract `prompts/dm-camera-hook-deadline.md`.
- *Cause.* The hook bounded only `_process`, with `wait_for`. Both `AttachmentStore.exists` checks were awaited with no bound, and both callers (the DM route and the group round) pass `timeout_s=4.0` with no outer bound.
- *G1 (the deadline).* The steps run in a task. The caller waits with `asyncio.wait(timeout=timeout_s)`, then cancels the task without awaiting it. Rejected: `asyncio.timeout` around the steps, as the issue proposed. It cancels inside the caller's own task, and the filesystem store answers a cancellation by waiting for its thread to end, so a slow store lookup would still hold the caller. Rejected: a deadline per store call, because the describe step also reads the store and uses threads.
- *G2 (the permit).* The task keeps the permit until its step ends. A call made while a cancelled step drains therefore returns at once instead of starting a second store call. A cancelled caller cancels the task and waits for it, as on the base, so the permit is free when its cancellation surfaces.
- *G3 (working memory).* An observation written before a later step times out stays; the docstring says so.
- *G4 (the route line).* Written in a finally, with sent=yes, no or raised. The group round has no timing line and gets no edit: it awaits the same method, which now returns by its deadline.
- *Residual.* The deadline bounds the caller, not the store: a blocked store thread still runs to its end. *Reversal.* Revert the commits of #1808; nothing is persisted.

### BF-932 slice 2 -- The Captain-DM reply path logs its own timeline, log-only (2026-11-13, #1670)
```

The orchestrator appends a `*Mutation campaign of record.*` bullet to this entry after section 8.3.

## 7. Builder: may and may not

- **May:** apply the pairs in order; run the focused commands named in section 4; run `gen_ad_ledger.py` in M3; run `git diff --check` and `git diff --stat`; commit as section 4 says.
- **May not:**
  - edit any file not named here, in particular `thread_fanout.py` or `attachments/filesystem_store.py`;
  - change any other step of `force_describe_current_frame`'s body;
  - add a config field;
  - add `skip`, `xfail` (other than M1's marker) or a retry;
  - reword a SEARCH anchor.

## 8. Gates (the orchestrator runs them)

### 8.1 Base counts, on the merged head before M1

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf666_force_describe_cache_expiry.py tests/test_ad733c1_force_describe.py tests/test_ad746a_force_describe_mirror.py tests/test_ad978_group_perception.py tests/test_bf932_reply_path_timing.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad733a_vision_consumer.py tests/test_ad733c2_mode_controller.py tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q
```

Record each file's count. I did not run these.

### 8.2 Focused check on the built tree

Run the 8.1 command with `tests/test_dm_camera_hook_deadline.py` added. Expected results:
- `tests/test_dm_camera_hook_deadline.py`: 6 passed.
- Every other file: its base count, all passed.
- `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` passes.
- `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check` passes.

| File | Why it is in the set | Expected edit |
|---|---|---|
| `tests/test_bf666_force_describe_cache_expiry.py` | Drives the method with cancellation at the pre-check, in `_process` and at the post-check, and after each asserts that the permit is free and no task is pending (`:878-927`, `:931-968`). It also covers concurrent calls (`:1128-1176`) and a resolver raising `CancelledError` (`:736-747`). | none |
| `tests/test_ad733c1_force_describe.py` | Has a timeout case whose LLM sleeps 10 s and which pins the substring `force_describe timed out` (`:170-193`). It also has the returned-description cases (`:128-155`). | none |
| `tests/test_ad746a_force_describe_mirror.py` | Replaces `_process` on the instance (`:101-111`). | none |
| `tests/test_ad978_group_perception.py` | Uses a fake consumer for the group round (`:99-105`, `:271-272`). | none |
| `tests/test_bf932_reply_path_timing.py` | Pins the route line (`:31`, r1 to r6 `:134-223`, including a logger that fails, `:195-223`). The new file imports its helpers. | none |
| `tests/test_ad1343_stop_seam_inventory.py` with `tests/fixtures/ad1343_seam_registry.py` | Requires `active_stop` to come before `send` in `_agent_chat_impl` (`:127-131`; registry `:102`). P2-8 moves the send down, still after it. | none |
| `tests/test_ad733a_vision_consumer.py`, `tests/test_ad733c2_mode_controller.py` | Scan the text of `consumer.py` for base64 tokens (`:559-569`; `:245-260`). The new code contains none. | none |
| `tests/test_ad1184_ad_ledger.py` | M3 regenerates the ledger. | none |

### 8.3 Mutation campaign (one row at a time, restored before the next; win32)

- **Selector:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_dm_camera_hook_deadline.py tests/test_bf666_force_describe_cache_expiry.py tests/test_ad733c1_force_describe.py tests/test_bf932_reply_path_timing.py -n 0 -p no:randomly -q`.
- **Campaign of record:** record the tree id and the sha256 of `consumer.py`, `agents.py` and the four selected test files. Rerun only the rows whose file differs.
- Each "original" below is a whole stripped line that occurs exactly once in its M2 file.

| Row | File | Original | Mutant | Expected killers |
|---|---|---|---|---|
| MU1 (no deadline) | consumer | `done, _pending = await asyncio.wait((work,), timeout=timeout_s)` | `done, _pending = await asyncio.wait((work,))` | t1, t2, t3; also ad733c1 `test_force_describe_times_out_gracefully` (after about 10 s) |
| MU2 (the caller waits for its cancelled step: the `asyncio.timeout` design) | consumer | `work.cancel()  # BF-977: not awaited; the task keeps the permit until its step ends` | `work.cancel(); await asyncio.wait((work,))` | t3 |
| MU3 (pre-check step unlabelled) | consumer | `progress.step = "preflight"` | `pass` | t1, t3 |
| MU4 (post-check step unlabelled) | consumer | `progress.step = "postcheck"` | `pass` | t2 |
| MU5 (a cancelled caller leaves at once) | consumer | `await asyncio.wait((work,))` | `pass` | t6 |
| MU7 (the line only after a send that returns) | agents | `emit_line(` | `_sent != "raised" and emit_line(` | t4 |
| MU8 (a raise reported as sent) | agents | `_sent = "raised"` | `_sent = "yes"` | t4 |
| MU9 (a finished task treated as late) | consumer | `if work in done:` | `if False:` | t5; also ad733c1 `test_force_describe_returns_description_for_session` and `test_force_describe_falls_back_to_global`, and 14 BF-666 cases (every case that expects a returned description or no timeout WARNING; 17 cases in all, named in the campaign of record in `DECISIONS.md`) |
| R0 (bounding only `_process`) | consumer | `consumer.py` restored from the base | -- | t1, t2, t3 fail; t4, t5, t6 and every BF-666 and ad733c1 case pass |
| R0b (removing the `finally`) | agents | `agents.py` restored from the base | -- | t4 fails; every bf932 case passes |

There is no MU6 row. A caller that does not cancel its task on its own cancellation would hang the BF-666 cancellation cases until pytest's timeout, so the row is left out.

Record each row as KILLED (by the named case, or name the case that fired), SURVIVED or INVALID. Any survivor stops the slice for Architect triage.

### 8.4 Broad gate

Run it once, on the committed head after the last repair: `scripts/run_test_gate.py --label dm-camera-hook-deadline --receipt logs/gates/dm-camera-hook-deadline.receipt.json`. Search cannot reach tests that boot the full runtime with perception enabled and then send a DM. In such a test a `vision_consumer` call that outlives its 4.0 s deadline would now return `None` instead of blocking.

## 9. Diff Reviewer: properties to verify

1. The diff touches only `src/probos/perception/consumer.py`, `src/probos/routers/agents.py`, `tests/test_dm_camera_hook_deadline.py`, `PROGRESS.md`, `DECISIONS.md` and the two regenerated ledger files.
2. Consumers that must accept the change: the DM hook (`agents.py:3488-3497`) and `_maybe_force_describe_frame` (`thread_fanout.py:386-410`). For each step in D2, the method returns by `timeout_s` (plus scheduling) with `None` or the description, or it raises what the steps raised, as before.
3. The one `create_task` added is referenced in `_force_describe_work` until it ends, and the done callback removes it. The permit is released only by `_force_describe_permit`'s `finally`, inside the task.
4. When the caller is cancelled, it cancels the task and waits for it before it re-raises. The BF-666 cancellation cases still hold.
5. The route writes exactly one `BF-932: dm route` line per DM whether the send returns or raises. The fields are unchanged. `sent` is `yes`, `no` or `raised`. The raised exception is the same object. `_t_send1` is assigned in the `finally`.
6. The timeout WARNING contains `force_describe timed out` (`test_ad733c1_force_describe.py:192`) and `step=<step>`. No `timeout_s` reference remains in `_force_describe_owned`.
7. After M2, `built` is a no-op and no `skip`, `xfail` or retry remains.

## 10. Verified Against Codebase (2026-11-16, tree `7db7edd7`; the cited product and test files are identical on `2c756a93`)

```
consumer.py:18 from __future__ import annotations | :20 import asyncio | :41 _LatestFrameCandidate = tuple[str, float]
consumer.py:172-173 self._latest_frame_lock = Lock() / self._force_describe_lock = asyncio.Lock()
consumer.py:447-463 _force_describe_permit: wait_for(acquire, timeout=0.001); yield False on timeout; release in finally
consumer.py:501 async def _process | :558 store.read | :629 self._describe | :640 _resolve_subject_identity | :678-680 wm.append | :691 _anchor_episode | :703-719 observer.maybe_emit
consumer.py:722-743 signature, docstring (":738 ``timeout_s`` is a hard wall-clock cap"), async with permit
consumer.py:759-760 sha, captured_at = candidate / max_age = ...
consumer.py:787 exists = await store.exists(sha) | :822-832 wait_for(self._process(...)), except asyncio.TimeoutError | :843 still_exists = await store.exists(sha)
consumer.py:995 return await loop.run_in_executor(None, resolver.resolve, live_bytes)
filesystem_store.py:55-72 _finish_cancelled waits while not call.done() | :193-197 shield; on CancelledError await _finish_cancelled; raise
filesystem_store.py:199-210 close() | :400-402 _find -> self._run(lambda: list(self._root.glob(...))) | :417-419 exists -> _find
agents.py:48 from probos.mesh.intent import IntentAuthorizationDenied | :64 import emit_line, ms_between
agents.py:2934-2944 agent_chat try/finally around _agent_chat_impl | :3488-3497 the hook, timeout_s=4.0 | :3694-3708 send, then the route line
thread_fanout.py:386-410 _maybe_force_describe_frame, timeout_s=4.0, except Exception -> debug
utils/step_timing.py:36-43 emit_line catches Exception, returns bool
mesh/pre_intent_auth.py:65 class IntentAuthorizationDenied(PermissionError) | :83 __init__(intent_name, reason, entry_point)
routers/chat.py:1066-1080 _get_attachment_store caches by id(runtime)
perception/working_memory.py:37-44 VisionObservation fields | :77 append | :88 entries
pyproject.toml:9 requires-python = ">=3.12" | :181 asyncio_mode = "auto" | :196 addopts = "-n 16 --dist=loadfile"
architecture-baseline.yaml:836-840 probos.perception.consumer::VisionConsumer triggers lines, methods
check_architecture_principles.py:188 SRP_MAX_DIRECT_METHODS = 15 | :558-569 method count, triggers
DECISIONS.md: "### BF-932 slice 2 -- The Captain-DM reply path logs its own timeline" occurs 1 time | PROGRESS.md:1 "# ProbOS Progress" occurs 1 time
git diff --stat 2c756a93 HEAD -- (consumer.py, agents.py, thread_fanout.py, filesystem_store.py, chat.py, pre_intent_auth.py,
  working_memory.py, step_timing.py, pyproject.toml, the architecture script and baseline, the eight focused test files and the fixture): empty
```

## Absence Verified (2026-11-16)

| Claim | Search (Grep tool, on tree `7db7edd7`) | Found | Holds |
|---|---|---|---|
| No test outside the focused set calls the method | `force_describe_current_frame` in `tests/` | the 6 files in 8.2 that drive or fake it, plus `test_bf624_stale_meeting_vision_refresh.py:11`, which is a docstring only | yes |
| No UI consumer | `force_describe\|dm route\|BF-932\|sent=` in `ui/` | `SettingsMain.tsx:316` (`secretPresent=`, which is not the field) | yes |
| Only bf932 pins the route line | `BF-932: dm route\|dm route` in `tests/` | `test_bf932_reply_path_timing.py` | yes |
| No test reads the source of `consumer.py`, `agents.py` or `thread_fanout.py` beyond the 8.2 rows | `perception/consumer\|routers/agents\.py\|thread_fanout` in `tests/`; `read_text\|getsource\|ast\.parse` in the perception tests | ad733a, ad733c2 (base64 tokens); the ad1343 registry (`_agent_chat_impl` order); the rest are imports or calls | yes |
| No timeout or handler census covers these files | `["']wait_for\|["']asyncio\.timeout\|TimeoutError["']\|ast\.Try\|ast\.ExceptHandler` in `tests/` | 13 files; the one touching these functions is ad1343 (`crew_executor`) | yes |
| No config, profile or facade field | `force_describe` in `config.py` and `config_models/`; in `config/` | `config.py:2309-2312` (`dm_force_describe_enabled`), `config/system.yaml:1798`; both unchanged | yes |
| The group round has no timing line | `BF-932\|emit_line` in `thread_fanout.py` | none | yes |
| `consumer.py` starts no subprocess and uses one executor call | `subprocess\|create_subprocess\|to_thread\|run_in_executor` in `consumer.py` | `:995` only | yes |
| Nothing in `consumer.py` swallows cancellation | `except BaseException\|except asyncio\.CancelledError\|except:` in `consumer.py` | each `CancelledError` handler re-raises (`:488`, `:547`, `:559`, `:776`, `:788`, `:833`, `:844`) | yes |
| The perception package uses no context variables | `contextvar\|ContextVar` in `src/probos/perception` | none | yes |

## 11. What this does NOT change, and recorded limits

- No change to the store, its thread pool or its BF-918 cancellation; no change to `thread_fanout.py`, the hook's 4.0 s value, `_process`, or the BF-666 permit's logic.
- **L1.** The deadline bounds what the caller sees, not what the store does. A step blocked in the store's thread runs until that thread returns, and the hook gives no fresh frame until then. A cut can land in the episode anchor or the observer and stop them there, as the base `wait_for` could.
- **L2.** A cancelled caller still waits for a step blocked in a thread, as on the base (t6).
- **L3.** `_save_index_sync` and `_find` are measured under #1670, not here.

## 12. Prior art and blind spots (date used: 2026-11-16)

- **AnyIO** `to_thread.run_sync(abandon_on_cancel=True)`: the caller stops waiting while the function keeps running in its thread, and by default the caller waits ([AnyIO threads docs](https://sources.debian.org/src/python-anyio/4.8.0-3/docs/threads.rst)). Adopted at the task level: the caller abandons the task and the task waits for its thread. We do not import AnyIO; the stdlib's `asyncio.wait` covers it.
- **`asyncio.timeout`** (stdlib, 3.11 and later): rejected (D1).
- **Internal:** BF-918 M4 explains why the store waits. The BF-666 permit is reused to stop pile-up. The BF-932 line's fields are unchanged.
- **Reference projects:** a search of `docs/research/reference-projects.md` for `anyio|trio|asyncio|timeout|deadline` matched nothing, so none was due for this subject. Considered and deferred: none.
- **Blind spot found:** the issue's design leaves the live store unbounded (section 1). T3 and MU2 measure it.

## 13. Acceptance criteria

- With a store that never answers, before the describe or after it, the call returns `None` within the test's 3.0 s bound for `timeout_s=0.2` (t1, t2). The same holds when the store blocks in its own thread (t3). R0, which bounds only `_process`, fails all three.
- A denied send writes exactly one `BF-932: dm route` line with `sent=raised`, and the same exception propagates (t4). R0b, which removes the `finally`, fails it.
- The BF-666, AD-733c and BF-932 tests pass unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
