# BF-918 slices M4 and M5 (#1626): the attachment store gets its own I/O threads, and the speech arbiter waits for a pipelined reply's last sentence

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24 — Amendment A1: M4 review round 1 (one P1, three P2); code pairs on candidate 1 `6d63cc93`.
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24 — Amendment A2: M4 review round 2 (one P1, one P3); code pairs on candidate 2 `a8619b3b`.

**Status:** ready for the Builder. **Base:** `origin/main` `cb190f32` (BF-918 M1 to M3 merged, PR #1645). **Issue:** #1626 (BF-918). No new AD or BF number: both are slices of BF-918.

| Milestone | Slice | Finding | Tier | Files | Test files |
|---|---|---|---|---|---|
| M4 | the attachment store's bounded I/O executor | BF-918 §18 R9 | **HIGH** | `src/probos/attachments/filesystem_store.py`, `src/probos/routers/chat.py`, `src/probos/startup/shutdown.py`, `tests/test_ad720_attachment_store.py`, `tests/test_bf918_attachment_io.py` (new), `PROGRESS.md`, `DECISIONS.md` | `tests/test_bf918_attachment_io.py` (new, 20 cases after A2), `tests/test_ad720_attachment_store.py` (1 test and the `store` fixture updated) |
| M5 | the arbiter's wait ends on a pipelined reply's last sentence | BF-918 §18 R12 | **HIGH** | `ui/src/audio/voice.ts`, `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`, `PROGRESS.md`, `DECISIONS.md` | `voice.prefetch.bf918.test.tsx` (7 tests appended, P14 to P20) |

**Tiers.** Both HIGH, the parent's tier (BF-918 is HIGH and a slice is never lowered without the Captain). M4 also earns it on its own: every attachment write in the vessel (artifacts, traces, perception frames, spoken audio) and the index save move to new threads, and shutdown gains a step. M5 changes the one speech arbiter that all seven producers share and adds a field to the public `SpeechEvent`; a defect there silences every later utterance for 45 s.

**Independence.** The slices touch disjoint source and test files. Their tracker pairs (§8) anchor on disjoint text and apply in either order. Each gets its own Builder milestone, consolidated focused check, Diff Reviewer pass and local commit; the batch gets one broad gate.

**M6 is not in this batch** (decision 1 below): it changes `ProfileChatTab.tsx` and its test, which M5 does not touch.

## 1. Problem

**R9 (M4).** `FilesystemAttachmentStore` runs every blocking call on asyncio's default pool through `asyncio.to_thread` (`filesystem_store.py:229, 270, 279, 293, 306, 358, 359, 417`). Crew work shares that pool. When it is full, storing the spoken WAV (`routers/avatars.py:301` `store.write`, then `:315` `store.get_path`) and serving it (`routers/chat.py:1253` `store.exists`, `:1255` `store.get_path`, both through `_find` at `filesystem_store.py:270`) wait behind crew work. BF-918's M2 isolated synthesis and lip-sync on a voice executor (`audio/tts/resident.py:367-376`) and left the store on the default pool (DECISIONS.md BF-918 D4). The finding still holds on this tree; M1 added one more call on the default pool (`unlink_if_unchanged`, `:358-359`).

**R12 (M5).** Under AD-1071 pipelining (`sentence_pipelining_enabled`, default off; on in the Captain's live config, §16 of BF-918's contract), every sentence of a reply fires its own `'end'` with the reply's `utterance_id` (BF-767; `voice.ts:716`, `_playPreparedSpeech._finish`). The arbiter's wait for an entry ends on the first `'end'` with that id (`voice.ts:443-445`). The drain then dispatches the next queued entry, whose `_playNow` takes the device (`voice.ts:512`, `_activeUtteranceId = utterance_id`). The sentence queue's `shouldContinue` (`voice.ts:555`) then fails, and the rest of the reply is discarded. This still reproduces on this tree by reading; M3 changed the queue (`runPrefetchQueue`, `voiceChunking.ts:84`) but not the arbiter's condition. P14 is the executable reproduction (it fails on the base).

## 2. Solution

**M4.** The store owns a bounded `ThreadPoolExecutor` (`ATTACHMENT_IO_WORKERS = 4` threads, named `probos-attachment-io_N`), made on first use. One private helper `_run` sends every blocking call to it: the file reads, writes, stats, unlinks, the directory glob of `_find`, the cold size scan, the index save, and `write`'s path resolution with its existence check, in one call (A1). The only exception is the constructor (resolving the root, making it and loading the index), which is called from sync code. A thread cannot be stopped, so a cancelled caller waits for its call to end before the cancellation propagates: a caller holding the store's lock never releases it while its call still runs (A1). Calls beyond 4 queue on those threads; store I/O is never refused. `close()` stops the threads without cancelling accepted work and never awaits. After it, `_run` sends each call to the default pool with a copy of the caller's context, as `asyncio.to_thread` did before M4, so a caller late in shutdown still completes; the call is that pool's own future, never a task, so the event loop's teardown, which cancels every task, cannot end a caller's wait before its thread (A2). `startup/shutdown.py` closes the cached store right after the attachment reaper stops, through a new `routers/chat.py:close_attachment_store(runtime)`. That function builds no store and keeps the cached instance, preserving one instance per root (R16). With nothing cached, it leaves a marker in the cache, so a store first built afterwards (by a request accepted before shutdown) is closed before it is returned (A1).

**M5.** The pipelined path marks each sentence's `'end'` with an additive `final` field: `false` when more of the same utterance will play, `true` when nothing more will (its last sentence, or a stop or a newer dispatch took the device first). Every other utterance's `'end'` carries no `final`, so events with pipelining off are unchanged. The arbiter's wait ignores an `'end'` whose `final` is `false` and re-arms its join timeout on it. The timeout (GUARD 2) then bounds the silence between two events of the entry, not the length of the reply. A stop between two sentences fires no `'end'`, because nothing is playing, and its queue can still be awaiting the next sentence's synthesis. While a sentence queue runs, `stopSpeaking` therefore ends that entry's wait itself, through `_endSentenceQueueWait`. A reply stopped before its first sentence still ends with `dropped` (D7a, unchanged).

## 3. Decisions (for #1626; ranked where there were options)

1. **M6 stays out of this batch.** Options: (a) leave it out (chosen); (b) add it as milestone M6. M6 changes `ProfileChatTab.tsx`'s `end` branch (`:2196-2205`) and is tested in `ProfileChatTab.bf918.test.tsx`; M5 changes only `voice.ts` and `voice.prefetch.bf918.test.tsx`. No shared code, no shared harness, so adding M6 saves nothing and adds a third review. **But M6 is coupled to a new slice, M7** (decision 2). Build M6 and M7 together in the next batch.
2. **New slice M7 of #1626 (found while drafting M5; ordinary reach with pipelining on; by reading, not executed).** In conversation mode, `ProfileChatTab`'s reply listener completes the controller's turn on the reply's first sentence's `'end'` (`ProfileChatTab.tsx:2196-2205`: `type === 'end'`, own `agent_id`, own `utterance_id`, then `complete()`). The controller then enters `silence_pending` (`conversationController.ts:450-471`) while sentences 2 to n still play. Barge-in, which works only in `agent_speaking` (`:350`), stops working, and the silence timer starts early. This is R12's root, one consumer up. M5's `final` field is the signal M7 needs: one condition in that `end` branch, which is the same branch M6 changes, in the same test harness. The same family, with lower stakes, belongs in M7's design note: the in-flight key clear (`:1385-1393`) and the BF-300 PTT gate (`:563-590`) also act on every sentence's `'end'`. Under the convergence rule an ordinary-reach finding is a slice, not a register entry. **M7 does not gate the live acceptance** if the acceptance's 20 replies are typed in the chat, not spoken in conversation mode (see §15).
3. **M4's bound is a module constant**, `ATTACHMENT_IO_WORKERS = 4`, with a constructor keyword `io_workers` for tests. A Pydantic field was rejected: this follows BF-918's own precedent for the voice limits (`resident.py:46-50`, `VOICE_EXECUTOR_WORKERS = 4`, constants), no operator has a reason to tune it, and a config field moves the pinned dump, the facade field count and three generated files (BF-918 repair 5). Revisit if the live `store_ms` shows saturation of the store's own threads.
4. **A closed store degrades to the default pool; it does not refuse.** Refusing was rejected: about 60 call sites use the store (artifact writes, traces, perception frames, routes), many run after the reaper stops (the pools stop at `shutdown.py:1945` onward), and a refused artifact write is lost data. Accepted work is never cancelled (`cancel_futures=False`), for the same reason.
5. **M4 covers every blocking call, not only R9's four.** `write`'s existence check and the index save, which ran on the event loop, and `size`, `unlink`, `unlink_if_unchanged` and the cold scan, which ran on the default pool, all go through `_run`. One helper with a partial list would leave the same dependency on the default pool. The index save runs while `self._lock` is held, and every `_index` mutation in the file is under that lock (§11), so the dictionary does not change while it is serialised. A1: that held only while the caller was not cancelled; `_run` now waits for a cancelled caller's call to end before the cancellation propagates (decision 9).
6. **Close placement:** immediately after the attachment reaper's stop (`shutdown.py:1600-1605`), as R9 specified. The reaper is the store's only background user with a lifecycle. Everything else is request-driven and falls back (decision 4). The shutdown helper reads `sys.modules` instead of importing `probos.routers.chat`: only that module builds a store, so when it was never imported there is nothing to close, and importing it would load the HTTP layer during shutdown.
7. **M5's signal is an additive `final` field on `'end'`** (option a). Ranked: (a) the field (chosen): the arbiter needs it now, and M7 needs the same fact; (b) an internal-only wait object passed to `_playNow`: rejected, because M7 would then need a second mechanism for the same fact; (c) ending the wait when the sentence queue returns: rejected, because a last sentence spoken by the browser fallback returns at once (R3), so the next utterance's `_playNow` would cancel it; (d) a new event type: rejected, because it is a wider contract change than one optional field.
8. **Pipelining stays default-off.** Neither slice touches config.
9. **A1, review round 1 finding 1 (P1): the drain lives in `_run`, for every call** (option a). Ranked: (a) `_run` shields the call and, when its caller is cancelled, waits for the call to end, then re-raises (chosen): one mechanism covers the three index saves, the blob write and both unlinks, on the store's threads and on the default pool after close; a thread cannot be stopped, so no caller should end before the call it started. (b) A helper used only under the lock: rejected, because the next call added under the lock would be unprotected by default. (c) Shield each locked operation as a whole (all-or-nothing): deferred (§18 R31); each method splits in two, and the partial states it removes are index hints. (d) `asyncio.shield` alone: rejected; the call goes on, but the caller still leaves the lock (the finding). A second cancellation while waiting is absorbed and the first is re-raised when the call ends. An exception the call raises after its caller was cancelled is logged as a WARNING, and the caller ends cancelled. A closed store submits to the default pool itself, with a copy of the caller's context (A2, decision 12). `AttachmentReaper.stop()` and `close()` are unchanged: `stop()` now returns after the save it interrupted has ended, and `close()` still cancels nothing. The blob-call windows predate M4 (the parent ran `write_bytes` and the unlinks through `to_thread` under the lock); the index-save race is M4's.
10. **A1, finding 3: `write` resolves its path and tests it in one store-thread call** (`_locate_sync`), so a fresh write stays at three executor handoffs and a repeated one at two; a fourth handoff was avoidable. Validation errors (`ValueError`) now surface from that call, under the lock, and reach the caller unchanged.
11. **A1, finding 4: the "close point passed" fact is a marker in `_ATTACHMENT_STORE_CACHE`** (`_CLOSED_BEFORE_BUILD`, keyed by `id(runtime)` like the stores). Ranked: (a) the cache marker (chosen): one place, cleared with the cache by `tests/conftest.py` before each test, so `id()` reuse by a later test's runtime is handled by the clear that already handles a reused store; within one test a reused id gets a closed store, which still works on the default pool, as a runtime object started again after a shutdown does. (b) `runtime._shutdown_started` (`runtime.py:1550`): rejected, a private attribute across a module boundary, and a `MagicMock` runtime reads truthy. (c) A separate module set: rejected, `tests/conftest.py` would need a second clear. (d) An attribute set on the runtime: rejected, test runtimes include `MagicMock`s and `SimpleNamespace`s. `close_attachment_store(runtime)` keeps its signature, and `startup/shutdown.py` is unchanged.

12. **A2, review round 2 finding 1 (P1, injected-only reach, a regression): after `close()`, `_run`'s call is `run_in_executor(None, contextvars.copy_context().run, fn, *args)`** (option a). A1's closed branch handed the drain a task (`ensure_future(asyncio.to_thread(...))`). `asyncio.Runner.close()`, inside `asyncio.run`, cancels every task, so that task ended while its thread still ran, the caller left the lock, and another task's cleanup saved the index over the running save; review round 2 reproduced it, and after a reopen the real reaper removed an acknowledged durable attachment. Ranked: (a) submit to the default pool directly with a context copy (chosen): what `asyncio.to_thread` does, minus the coroutine that became the task, so the drain holds the pool's own future in both branches and no task stands between a caller and its thread; it also removes the file's one `asyncio.ensure_future`, which `docs/development/engineering-principles.md:84` forbids. (b) The same without the context copy: rejected; no store call reads a contextvar, but the closed path promises the behaviour before M4, and the copy costs nothing. (c) Keep the task and shield it: rejected; `Runner.close()` cancels every task directly. (d) A private fallback executor after close: rejected; `close()` exists so that the store's threads end. The guarantee is §14 M4 property 11. Finding 2 (P3, injected-only, not a regression: the every-blocking test never ran the cold size scan) is folded into that test, a trivial addition (row M4-21).

## 4. Milestones, focused checks and tests-first expectations

**M4** (Python). Apply §7.1 to §7.5 and §8's M4 pairs, then run:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1242_crew_verifier_trace.py tests/test_bf918_attachment_io.py tests/test_ad720_attachment_store.py tests/test_attachment_reaper.py tests/test_filesystem_store_origin.py tests/test_camera_frame_origin.py tests/test_ad720_attachments_endpoint.py tests/test_bf918_tts_retention.py tests/test_bf918_tts_latency.py tests/test_conftest_attachment_store_cache_isolation.py tests/test_issue1452_stop_leftovers.py tests/test_issue1419_failed_start_rollback.py -n 0 -q
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
```

Tests-first, on the base source with the M4 tests applied: `tests/test_bf918_attachment_io.py` fails at collection (it imports `ATTACHMENT_IO_THREAD_PREFIX`), and the updated `test_filesystem_store_runs_blocking_io_on_its_own_threads` fails (`ImportError` inside the test). Every other test in the list passes.

**M4 A1 (review round 1 repair).** Apply the A1 code pairs to candidate 1, then run the same focused check. It now starts with `tests/test_ad1242_crew_verifier_trace.py`, in the same process, which reproduces finding 2's ordering. Tests first, on candidate 1 with only A1's test pairs: these fail: the six `test_a_cancelled_caller_keeps_the_lock_until_its_index_save_finishes` cases, `test_a_cancelled_blob_write_keeps_the_lock_until_the_bytes_are_written`, `test_the_reapers_stop_returns_only_after_its_cancelled_save_has_finished`, `test_a_call_that_fails_after_its_caller_was_cancelled_is_logged`, `test_every_blocking_call_runs_on_the_store_threads` (`resolve` on the event loop's thread) and `test_a_store_first_built_after_the_close_point_is_born_closed`. Every other test passes, including the thread-exit test after the verifier-trace file. Then rerun all 19 Python rows of §10: `_run` and both campaign test files changed.

**M4 A2 (review round 2 repair).** Apply the A2 code pairs to candidate 2, then run the same focused check. Tests first, on candidate 2 with only A2's test pairs: `test_loop_teardown_keeps_the_lock_until_the_interrupted_save_ends[closed]` fails (its `states` assertion: `caller_pending` is false, because the teardown ended the interrupted caller while its save still ran). `[own-threads]` passes, and so does the extended `test_every_blocking_call_runs_on_the_store_threads` (the cold scan was already off the loop: finding 2 is a coverage gap). Every other test passes. Then rerun all 21 Python rows of §10: `_run` and the campaign's test file changed.

**M5** (TypeScript). Apply §7.6 and §7.7 and §8's M5 pairs, then, from `ui/`:

```
npx vitest run src/audio src/components/profile
npx tsc -b
```

Tests-first, on the base `voice.ts` with §7.7 applied: P14, P15, P16, P17, P19 and P20 fail; P18 passes (the pipelining-off control). P1 to P13 pass. P15 fails only at its last assertion, which reads the new `final` field (`[false]`); its earlier assertions pass on the base and pin what M5 must keep (a stop between two sentences frees the arbiter at once). The first draft of this paragraph predicted that P15 passes on the base; the Builder's tests-first run showed it does not.

**Harness rule (from BF-918 §6):** `_flush()` is 40 microtask turns. If a new case needs more because of the call depth (an estimate: none was run), raise the count for that case only and say so in the report. Never add a wall-clock sleep.

**The broad gate is run once for the batch by the main session, not by the Builder.** It does not run vitest; CI does.

## 7. The contract

### 7.1 `src/probos/attachments/filesystem_store.py` (M4)

Pair 1 (the module docstring):

SEARCH:
```python
Content-addressed by sha256. All blocking I/O wrapped in ``asyncio.to_thread``
(no ``aiofiles`` dependency — verified zero hits in pyproject.toml at HEAD;
project standard is ``run_in_executor`` / ``asyncio.to_thread``).
```
REPLACE:
```python
Content-addressed by sha256. BF-918 M4 (#1626): every blocking call runs on the
store's own bounded executor (``ATTACHMENT_IO_WORKERS`` threads), so crew work
that fills asyncio's default pool does not delay storing or serving an
attachment; after :meth:`close`, on the default pool (no ``aiofiles``
dependency; project standard is ``run_in_executor``). The exception is the
constructor (resolving the root, making it and loading the index), which is
called from sync code.
```

Pair 2:

SEARCH:
```python
import asyncio
import errno
import json
```
REPLACE:
```python
import asyncio
import concurrent.futures
import contextvars
import errno
import json
```

Pair 3:

SEARCH:
```python
import time
from pathlib import Path
from typing import Any
```
REPLACE:
```python
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar
```

Pair 4 (the bound and the thread name):

SEARCH:
```python
logger = logging.getLogger(__name__)


_MIME_TO_EXT: dict[str, str] = {
```
REPLACE:
```python
logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: BF-918 M4 (#1626): threads for one store's blocking I/O. Calls beyond it queue.
ATTACHMENT_IO_WORKERS = 4
#: BF-918 M4: the name prefix of those threads (``probos-attachment-io_0`` ...).
ATTACHMENT_IO_THREAD_PREFIX = "probos-attachment-io"


async def _finish_cancelled(call: asyncio.Future[Any]) -> None:
    """BF-918 M4 (review round 1): wait for a store call whose caller was cancelled.

    A thread cannot be stopped. Waiting keeps the caller's lock held until the call
    really ends; the caller then re-raises its cancellation. A further cancellation
    while waiting is absorbed for the same reason. An exception the call raised is
    logged, since its caller can no longer receive it.
    """
    while not call.done():
        try:
            await asyncio.wait((call,))
        except asyncio.CancelledError:
            pass  # cancelled again: keep waiting; the caller re-raises the first cancellation
    if not call.cancelled() and call.exception() is not None:
        logger.warning(
            "BF-918: an attachment store call failed after its caller was cancelled: %r",
            call.exception(),
        )


_MIME_TO_EXT: dict[str, str] = {
```

Pair 5 (the constructor; the check comes before any directory is made):

SEARCH:
```python
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
```
REPLACE:
```python
    def __init__(self, root: Path, *, io_workers: int = ATTACHMENT_IO_WORKERS) -> None:
        if io_workers < 1:
            raise ValueError("BF-918: the attachment store needs at least 1 I/O thread")
        # BF-918 M4 (#1626): this store's own I/O threads, made on first use.
        self._io_workers = io_workers
        self._io_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._io_closed = False
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
```

Pair 6 (`io_closed`, `_run`, `close`):

SEARCH:
```python
        self._lock = asyncio.Lock()

    # ---- AD-733-1: sidecar index helpers ------------------------------
```
REPLACE:
```python
        self._lock = asyncio.Lock()

    # ---- BF-918 M4 (#1626): the store's own I/O threads ---------------

    @property
    def io_closed(self) -> bool:
        """True once :meth:`close` has run; the store's I/O then uses the default pool."""
        return self._io_closed

    async def _run(self, fn: Callable[..., _T], *args: Any) -> _T:
        """Run one blocking call on this store's threads (the default pool once closed).

        Crew work that fills asyncio's default pool no longer delays the store.
        Calls beyond ``io_workers`` queue on these threads: store I/O is never
        refused. After :meth:`close`, a call (a route, or crew work that stops
        later in shutdown) runs on the default pool, as before BF-918 M4.

        A thread cannot be stopped, so a cancelled caller first waits for its call
        to end and then re-raises the cancellation (BF-918 M4, review round 1). A
        caller that holds ``self._lock`` therefore never releases it while its
        index save, blob write or unlink still runs.

        After :meth:`close`, the call is the default pool's own future, run in a
        copy of the caller's context, never a task: the event loop's teardown
        (``asyncio.run``) cancels every task, and a cancelled task would end the
        caller's wait while its thread still runs (BF-918 M4, review round 2).
        """
        call: asyncio.Future[_T]
        if self._io_closed:
            call = asyncio.get_running_loop().run_in_executor(None, contextvars.copy_context().run, fn, *args)
        else:
            if self._io_executor is None:
                self._io_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._io_workers,
                    thread_name_prefix=ATTACHMENT_IO_THREAD_PREFIX,
                )
            call = asyncio.get_running_loop().run_in_executor(self._io_executor, fn, *args)
        try:
            return await asyncio.shield(call)
        except asyncio.CancelledError:
            await _finish_cancelled(call)
            raise

    def close(self) -> None:
        """Stop this store's I/O threads. Idempotent; never raises; never awaits.

        Work already accepted runs to completion: nothing is cancelled, so a caller
        awaiting a write never sees it fail because shutdown began. The threads exit
        once that work is done. Called by ``startup/shutdown.py`` after the
        attachment reaper has stopped.
        """
        self._io_closed = True
        executor, self._io_executor = self._io_executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

    # ---- AD-733-1: sidecar index helpers ------------------------------
```

Pair 7 (`write`: the path and its existence check in one store-thread call, A1, then the blob):

SEARCH:
```python
        path = self._path_for(content_hash, mime)
        async with self._lock:
            need_write = not path.exists()
            if need_write:
                try:
                    await asyncio.to_thread(path.write_bytes, blob)
```
REPLACE:
```python
        async with self._lock:
            path, present = await self._run(self._locate_sync, content_hash, mime)
            need_write = not present
            if need_write:
                try:
                    await self._run(path.write_bytes, blob)
```

Pair 8 (`write`: the index save):

SEARCH:
```python
                entry.setdefault("size_bytes", len(blob))
            self._save_index_sync()
        return path
```
REPLACE:
```python
                entry.setdefault("size_bytes", len(blob))
            # BF-918 M4: still under the lock, so no other call changes the index while it is written.
            await self._run(self._save_index_sync)
        return path
```

Pair 9 (`_find`):

SEARCH:
```python
        matches = await asyncio.to_thread(
            lambda: list(self._root.glob(f"{content_hash}.*")),
        )
```
REPLACE:
```python
        matches = await self._run(
            lambda: list(self._root.glob(f"{content_hash}.*")),
        )
```

Pair 10 (`read`):

SEARCH:
```python
        if path is None:
            raise FileNotFoundError(content_hash)
        return await asyncio.to_thread(path.read_bytes)
```
REPLACE:
```python
        if path is None:
            raise FileNotFoundError(content_hash)
        return await self._run(path.read_bytes)
```

Pair 11 (`size`):

SEARCH:
```python
    async def size(self, content_hash: str) -> int:
        path = await self.get_path(content_hash)
        return await asyncio.to_thread(lambda: path.stat().st_size)
```
REPLACE:
```python
    async def size(self, content_hash: str) -> int:
        path = await self.get_path(content_hash)
        return await self._run(lambda: path.stat().st_size)
```

Pair 12 (`unlink`: the blob):

SEARCH:
```python
                try:
                    await asyncio.to_thread(path.unlink)
                    existed = True
```
REPLACE:
```python
                try:
                    await self._run(path.unlink)
                    existed = True
```

Pair 13 (`unlink`: the index save):

SEARCH:
```python
            if existed or removed_from_index:
                self._save_index_sync()
            return existed or removed_from_index
```
REPLACE:
```python
            if existed or removed_from_index:
                await self._run(self._save_index_sync)
            return existed or removed_from_index
```

Pair 14 (`unlink_if_unchanged`: the blob):

SEARCH:
```python
                    freed = (await asyncio.to_thread(path.stat)).st_size
                    await asyncio.to_thread(path.unlink)
```
REPLACE:
```python
                    freed = (await self._run(path.stat)).st_size
                    await self._run(path.unlink)
```

Pair 15 (`unlink_if_unchanged`: the index save):

SEARCH:
```python
            del self._index[content_hash]
            self._save_index_sync()
            return freed
```
REPLACE:
```python
            del self._index[content_hash]
            await self._run(self._save_index_sync)
            return freed
```

Pair 16 (`total_size_bytes`: the cold scan):

SEARCH:
```python
                    continue
            return total
        return await asyncio.to_thread(_scan)
```
REPLACE:
```python
                    continue
            return total
        return await self._run(_scan)
```

Pair 17 (A1: `_locate_sync`, after `_path_for`):

SEARCH:
```python
            raise ValueError(
                f"AD-720: path traversal rejected for {content_hash!r}"
            )
        return candidate
```
REPLACE:
```python
            raise ValueError(
                f"AD-720: path traversal rejected for {content_hash!r}"
            )
        return candidate

    def _locate_sync(self, content_hash: str, mime: str) -> tuple[Path, bool]:
        """BF-918 M4 (review round 1): the blob's checked path and whether it exists.

        ``Path.resolve`` and ``exists`` touch the filesystem, so ``write`` runs
        both in one call on a store thread. The validation in :meth:`_path_for`
        raises ``ValueError`` from there, unchanged.
        """
        path = self._path_for(content_hash, mime)
        return path, path.exists()
```

After §7.1, neither `to_thread` nor `ensure_future` occurs in the file (A2), `self._save_index_sync()` is no longer called directly anywhere in it, and `self._path_for(` is called only from `_locate_sync`.

### 7.2 `src/probos/routers/chat.py` (M4)

Pair 1 (A1: the marker):

SEARCH:
```python
_ATTACHMENT_STORE_CACHE: dict[int, Any] = {}
```
REPLACE:
```python
_ATTACHMENT_STORE_CACHE: dict[int, Any] = {}
#: BF-918 M4 (review round 1): cached in place of a store when shutdown closes the store
#: before any was built, so the store a later caller builds is closed before it is returned.
_CLOSED_BEFORE_BUILD: Any = object()
```

Pair 2 (A1: the lookup skips the marker):

SEARCH:
```python
    cached = _ATTACHMENT_STORE_CACHE.get(key)
    if cached is not None:
        return cached
```
REPLACE:
```python
    cached = _ATTACHMENT_STORE_CACHE.get(key)
    if cached is not None and cached is not _CLOSED_BEFORE_BUILD:
        return cached
```

Pair 3 (the closer; A1: a store built after the close point is closed):

SEARCH:
```python
    store = FilesystemAttachmentStore(root)
    _ATTACHMENT_STORE_CACHE[key] = store
    return store
```
REPLACE:
```python
    store = FilesystemAttachmentStore(root)
    _ATTACHMENT_STORE_CACHE[key] = store
    if cached is _CLOSED_BEFORE_BUILD:
        close_attachment_store(runtime)  # BF-918 M4 (review round 1): built after shutdown's close point
    return store


def close_attachment_store(runtime: Any) -> None:
    """BF-918 M4 (#1626): close the I/O threads of ``runtime``'s cached store.

    Builds no store, and keeps the cached one: a later caller gets the same
    instance (one store per attachment root, BF-918 R16), whose I/O then runs on
    asyncio's default pool. Anything else cached here (a test double) is left alone.
    With nothing cached, it records that the close point has passed (review round 1),
    so a store first built afterwards, by a request accepted before shutdown, is closed too.
    """
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    key = id(runtime)
    store = _ATTACHMENT_STORE_CACHE.get(key)
    if store is None:
        _ATTACHMENT_STORE_CACHE[key] = _CLOSED_BEFORE_BUILD
    elif isinstance(store, FilesystemAttachmentStore):
        store.close()
```

### 7.3 `src/probos/startup/shutdown.py` (M4)

Pair 1:

SEARCH:
```python
import math
import sqlite3
import time
```
REPLACE:
```python
import math
import sqlite3
import sys
import time
```

Pair 2 (the helper, after `_close_voice_synthesis`):

SEARCH:
```python
    try:
        voice_service.close()
    except Exception:
        logger.warning("BF-918: voice synthesis close failed", exc_info=True)
```
REPLACE:
```python
    try:
        voice_service.close()
    except Exception:
        logger.warning("BF-918: voice synthesis close failed", exc_info=True)


def _close_attachment_store(runtime: Any) -> None:
    """BF-918 M4 (#1626): stop the attachment store's own I/O threads. Never raises.

    Builds no store. Only ``probos.routers.chat`` builds one, so when that module
    was never imported there is nothing to close (importing it here would load the
    HTTP layer during shutdown for nothing). The store's later users, such as the
    routes and crew work until the pools stop, run on asyncio's default pool.
    """
    chat_router = sys.modules.get("probos.routers.chat")
    if chat_router is None:
        return
    try:
        chat_router.close_attachment_store(runtime)
    except Exception:
        logger.warning("BF-918: attachment store close failed", exc_info=True)
```

Pair 3 (the call, right after the reaper's stop):

SEARCH:
```python
            await runtime.attachment_reaper.stop()
        except Exception:
            logger.warning("AD-733-1: attachment_reaper.stop() failed", exc_info=True)
```
REPLACE:
```python
            await runtime.attachment_reaper.stop()
        except Exception:
            logger.warning("AD-733-1: attachment_reaper.stop() failed", exc_info=True)

    # BF-918 M4 (#1626): then the store's own I/O threads. Its later users (routes,
    # crew work until the pools stop) run on asyncio's default pool.
    _close_attachment_store(runtime)
```

### 7.4 `tests/test_ad720_attachment_store.py` (M4: the test that pinned the old dispatch)

This test asserted `asyncio.to_thread` itself, which is the dependency R9 removes. It is updated, not deleted. The property it protected, that blocking I/O runs off the event loop, is still asserted, together with the new owner of that I/O. A1 also makes the file's `store` fixture close the store it owns (pairs 2 and 3).

Pair 1 (the test):

SEARCH:
```python
@pytest.mark.asyncio
async def test_filesystem_store_uses_asyncio_to_thread(store, monkeypatch):
    """Verify blocking IO is dispatched through asyncio.to_thread."""
    calls: list[str] = []
    real_to_thread = asyncio.to_thread

    async def spy(fn, *args, **kwargs):
        calls.append(getattr(fn, "__name__", str(fn)))
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr("probos.attachments.filesystem_store.asyncio.to_thread", spy)
    blob, h = _make_blob(b"g")
    await store.write(h, blob, "image/png")
    assert calls, "asyncio.to_thread was not invoked"
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_filesystem_store_runs_blocking_io_on_its_own_threads(store, monkeypatch):
    """Blocking I/O runs off the event loop. BF-918 M4 (#1626) moved it from
    ``asyncio.to_thread`` (the default pool, which crew work can fill) to the
    store's own threads. This test pinned the old dispatch, so it now checks the
    property that matters: the write ran on a ``probos-attachment-io`` thread."""
    import threading
    from probos.attachments.filesystem_store import ATTACHMENT_IO_THREAD_PREFIX

    threads: list[str] = []
    real_write_bytes = Path.write_bytes

    def spy(self, data):
        threads.append(threading.current_thread().name)
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", spy)
    blob, h = _make_blob(b"g")
    try:
        await store.write(h, blob, "image/png")
    finally:
        store.close()
    assert threads and all(name.startswith(ATTACHMENT_IO_THREAD_PREFIX) for name in threads), threads
```

Pair 2 (A1: the import for the fixture's type):

SEARCH:
```python
import asyncio
import hashlib
from pathlib import Path
```
REPLACE:
```python
import asyncio
import hashlib
from collections.abc import Iterator
from pathlib import Path
```

Pair 3 (A1, review round 1 finding 2: the fixture closes the store it owns):

SEARCH:
```python
@pytest.fixture
def store(tmp_path: Path) -> FilesystemAttachmentStore:
    return FilesystemAttachmentStore(tmp_path / "attachments")
```
REPLACE:
```python
@pytest.fixture
def store(tmp_path: Path) -> Iterator[FilesystemAttachmentStore]:
    owned = FilesystemAttachmentStore(tmp_path / "attachments")
    yield owned
    owned.close()  # BF-918 M4 (review round 1): its I/O threads end with the test
```

### 7.5 New file: `tests/test_bf918_attachment_io.py` (M4)

```python
"""BF-918 M4 (#1626, the BF-918 contract's section 18 R9): the attachment store's own I/O threads.

Crew work can fill asyncio's default pool; storing the spoken WAV and serving it
must not wait behind that work. Real store, real files. Only the default pool and,
in some cases, one blocking file call are replaced.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import hashlib
import inspect
import json
import logging
import textwrap
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.attachments.filesystem_store import (
    ATTACHMENT_IO_THREAD_PREFIX,
    FilesystemAttachmentStore,
)
from probos.startup import shutdown as shutdown_module

_PNG = b"\x89PNG\r\n\x1a\n"


def _blob(seed: bytes) -> tuple[bytes, str]:
    blob = _PNG + seed * 32
    return blob, hashlib.sha256(blob).hexdigest()


async def _until(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())


class _HeldReads:
    """Stands in for ``Path.read_bytes``: each call records its thread, then blocks until released.

    It records the thread object, not its name: every store names its threads alike
    (review round 1, finding 2).
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.threads: list[threading.Thread] = []
        self._real = Path.read_bytes
        self._lock = threading.Lock()

    def __call__(self, path: Path) -> bytes:
        with self._lock:
            self.threads.append(threading.current_thread())
        self.release.wait(10)
        return self._real(path)


class _Gate:
    """Stands in for one blocking call: its first call sets ``entered``, then blocks until ``release``.

    ``finished`` is set once that call has returned or raised. Later calls pass straight through.
    """

    def __init__(self, real, *, fail: BaseException | None = None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self._real = real
        self._fail = fail
        self._first = True
        self._lock = threading.Lock()

    def __call__(self, *args):
        with self._lock:
            first, self._first = self._first, False
        if not first:
            return self._real(*args)
        self.entered.set()
        self.release.wait(10)
        try:
            if self._fail is not None:
                raise self._fail
            return self._real(*args)
        finally:
            self.finished.set()


async def _turns(count: int = 20) -> None:
    """Lets the event loop run ``count`` times: loop turns, not wall-clock time."""
    for _ in range(count):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _close_the_stores_built_here(monkeypatch) -> Iterator[None]:
    """Closes every store a test in this file builds, pass or fail (review round 1, finding 2)."""
    built: list[FilesystemAttachmentStore] = []
    real_init = FilesystemAttachmentStore.__init__

    def init(self, *args, **kwargs) -> None:
        real_init(self, *args, **kwargs)
        built.append(self)

    monkeypatch.setattr(FilesystemAttachmentStore, "__init__", init)
    yield
    for store in built:
        store.close()


@pytest.mark.asyncio
async def test_store_io_does_not_wait_for_a_busy_default_pool(tmp_path: Path) -> None:
    """R9: with asyncio's default pool fully held, spoken audio is stored, found and served."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    loop = asyncio.get_running_loop()
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bf918-m4-busy-default")
    loop.set_default_executor(pool)
    held = loop.run_in_executor(None, release.wait, 30)
    blob, h = _blob(b"w")

    async def _store_and_serve() -> bytes:
        await store.write(h, blob, "audio/wav", origin="tts_audio")  # routers/avatars.py
        assert await store.exists(h)  # routers/chat.py, GET /api/chat/attachments
        assert (await store.get_path(h)).name == f"{h}.wav"
        return await store.read(h)

    try:
        assert await asyncio.wait_for(_store_and_serve(), timeout=3.0) == blob
    finally:
        release.set()
        await held
        store.close()
        pool.shutdown(wait=True)
        loop.set_default_executor(ThreadPoolExecutor(thread_name_prefix="asyncio"))


@pytest.mark.asyncio
async def test_every_blocking_call_runs_on_the_store_threads(tmp_path: Path, monkeypatch) -> None:
    """Every blocking call of every method, including ``write``'s path resolution and each stat
    (review round 1, finding 3) and the cold size scan (review round 2, finding 2), runs on a store
    thread. Only calls on paths in the store count."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    root = str((tmp_path / "attachments").resolve())
    seen: dict[str, set[str]] = {}
    real_save = FilesystemAttachmentStore._save_index_sync

    def save(self) -> None:
        seen.setdefault("index save", set()).add(threading.current_thread().name)
        real_save(self)

    def spy(name: str, real):
        def call(path: Path, *args, **kwargs):
            if str(path).startswith(root):
                seen.setdefault(name, set()).add(threading.current_thread().name)
            return real(path, *args, **kwargs)

        return call

    (tmp_path / "attachments" / "stray.bin").write_bytes(b"abc")  # unindexed: only the cold size scan counts it
    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", save)
    for name in ("resolve", "exists", "stat", "read_bytes", "write_bytes", "unlink", "iterdir", "is_file"):
        monkeypatch.setattr(Path, name, spy(name, getattr(Path, name)))
    blob, h = _blob(b"n")
    other, h2 = _blob(b"m")
    try:
        await store.write(h, blob, "audio/wav", origin="tts_audio")
        await store.write(h, blob, "audio/wav", origin="tts_audio")  # the repeated write
        assert await store.read(h) == blob
        assert await store.size(h) == len(blob)
        assert await store.unlink(h) is True
        await store.write(h2, other, "audio/wav", origin="tts_audio")
        [(_, written_at)] = await store.list_by_origin("tts_audio")
        assert await store.unlink_if_unchanged(h2, origin="tts_audio", written_at=written_at) == len(other)
        assert await store.total_size_bytes() == 3  # the index is empty now: the cold scan of the root
    finally:
        store.close()
    expected = {"index save", "resolve", "exists", "stat", "read_bytes", "write_bytes", "unlink", "iterdir", "is_file"}
    assert set(seen) == expected, seen
    assert all(name.startswith(ATTACHMENT_IO_THREAD_PREFIX) for names in seen.values() for name in names), seen


@pytest.mark.asyncio
async def test_calls_beyond_the_bound_queue_and_all_complete(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemAttachmentStore(tmp_path / "attachments", io_workers=1)
    blob, h = _blob(b"q")
    await store.write(h, blob, "image/png")
    held = _HeldReads()
    monkeypatch.setattr(Path, "read_bytes", lambda self: held(self))
    reads = [asyncio.create_task(store.read(h)) for _ in range(3)]
    try:
        assert await _until(lambda: len(held.threads) == 1)
        await asyncio.sleep(0.05)  # room for a second read to start, if the bound allowed one
        assert len(held.threads) == 1
        assert not any(task.done() for task in reads)  # queued, not refused
    finally:
        held.release.set()
    assert await asyncio.wait_for(asyncio.gather(*reads), timeout=5.0) == [blob, blob, blob]
    assert len(held.threads) == 3 and len(set(held.threads)) == 1
    store.close()


@pytest.mark.asyncio
async def test_close_lets_accepted_work_finish_and_its_threads_exit(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemAttachmentStore(tmp_path / "attachments", io_workers=1)
    blob, h = _blob(b"c")
    await store.write(h, blob, "image/png")
    held = _HeldReads()
    monkeypatch.setattr(Path, "read_bytes", lambda self: held(self))
    running = asyncio.create_task(store.read(h))
    assert await _until(lambda: len(held.threads) == 1)
    worker = held.threads[0]  # this store's own thread: names repeat across stores
    queued = asyncio.create_task(store.read(h))  # its lookup is queued behind the running read
    await asyncio.sleep(0.05)

    store.close()
    store.close()  # idempotent
    assert store.io_closed is True
    held.release.set()

    assert await asyncio.wait_for(asyncio.gather(running, queued), timeout=5.0) == [blob, blob]
    assert await _until(lambda: not worker.is_alive())


@pytest.mark.asyncio
async def test_a_closed_store_still_stores_and_serves_on_the_default_pool(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    store.close()
    threads: list[str] = []
    real_write = Path.write_bytes

    def write(self, data) -> int:
        threads.append(threading.current_thread().name)
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", write)
    blob, h = _blob(b"d")
    await store.write(h, blob, "image/png")
    assert await store.read(h) == blob
    assert threads and not any(name.startswith(ATTACHMENT_IO_THREAD_PREFIX) for name in threads), threads


@pytest.mark.parametrize("workers", [0, -1])
def test_a_store_needs_at_least_one_io_thread(tmp_path: Path, workers: int) -> None:
    root = tmp_path / "attachments"
    with pytest.raises(ValueError):
        FilesystemAttachmentStore(root, io_workers=workers)
    assert not root.exists()


def test_shutdown_closes_the_cached_store_after_the_reaper_and_builds_none(tmp_path: Path) -> None:
    from probos.routers import chat as chat_router

    runtime = SimpleNamespace()
    shutdown_module._close_attachment_store(runtime)  # nothing cached: nothing built, the close point recorded
    assert not isinstance(chat_router._ATTACHMENT_STORE_CACHE.get(id(runtime)), FilesystemAttachmentStore)
    assert not (tmp_path / "attachments").exists()

    store = FilesystemAttachmentStore(tmp_path / "attachments")
    other = SimpleNamespace()
    chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = store
    chat_router._ATTACHMENT_STORE_CACHE[id(other)] = SimpleNamespace()  # a test double: left alone
    try:
        shutdown_module._close_attachment_store(runtime)
        shutdown_module._close_attachment_store(other)
        assert store.io_closed is True
        assert chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] is store  # kept: one store per root
    finally:
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(other), None)

    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))

    def _first_line(match) -> int:
        return min(node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and match(node))

    reaper_stop = _first_line(
        lambda n: isinstance(n.func, ast.Attribute) and n.func.attr == "stop"
        and ast.unparse(n.func.value) == "runtime.attachment_reaper"
    )
    store_close = _first_line(lambda n: isinstance(n.func, ast.Name) and n.func.id == "_close_attachment_store")
    assert reaper_stop < store_close


def test_a_store_first_built_after_the_close_point_is_born_closed(tmp_path: Path, monkeypatch) -> None:
    """Review round 1, finding 4: shutdown passed its close point before any store was built, and a
    request accepted earlier builds one afterwards. That store is closed before it is returned."""
    from probos.routers import chat as chat_router

    root = tmp_path / "attachments"
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: root)
    runtime = SimpleNamespace(config=SimpleNamespace(attachments=SimpleNamespace(attachments_dir="attachments")))
    try:
        shutdown_module._close_attachment_store(runtime)
        assert not root.exists()  # the closer built nothing
        store = chat_router._get_attachment_store(runtime)
        assert isinstance(store, FilesystemAttachmentStore) and store.io_closed is True
        assert chat_router._get_attachment_store(runtime) is store  # one store per root
    finally:
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)


_SAVE_SITES = ("write", "unlink", "unlink_if_unchanged")


@pytest.mark.parametrize("closed", [False, True], ids=["own-threads", "closed"])
@pytest.mark.parametrize("site", _SAVE_SITES)
@pytest.mark.asyncio
async def test_a_cancelled_caller_keeps_the_lock_until_its_index_save_finishes(
    tmp_path: Path, monkeypatch, site: str, closed: bool
) -> None:
    """Review round 1, finding 1: cancelling a caller while its index save runs (the reaper's stop
    cancels its sweep) neither releases the lock nor ends the caller before that save has ended, even
    when it is cancelled twice. The file on disk then holds what the caller left in memory."""
    root = tmp_path / "attachments"
    store = FilesystemAttachmentStore(root)
    blob, h = _blob(b"s")
    await store.write(h, blob, "image/png", origin="perception_frame")
    [(_, written_at)] = await store.list_by_origin("perception_frame")
    if closed:
        store.close()
    gate = _Gate(FilesystemAttachmentStore._save_index_sync)
    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", lambda self: gate(self))
    operations = {
        "write": lambda: store.write(h, blob, "image/png", origin="agent_artifact"),
        "unlink": lambda: store.unlink(h),
        "unlink_if_unchanged": lambda: store.unlink_if_unchanged(
            h, origin="perception_frame", written_at=written_at
        ),
    }
    task = asyncio.create_task(operations[site]())
    ended_after_save: list[bool] = []
    task.add_done_callback(lambda _task: ended_after_save.append(gate.finished.is_set()))
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)
        task.cancel()
        await _turns()
        task.cancel()  # cancelled again while it waits
        await _turns()
        contender = asyncio.create_task(store.list_by_origin("agent_artifact"))
        await _turns()
        assert not task.done() and not contender.done()  # the caller still holds the lock
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended_after_save == [True]
    in_memory = await contender
    reopened = FilesystemAttachmentStore(root)
    assert await reopened.list_by_origin("agent_artifact") == in_memory
    assert await reopened.list_by_origin("perception_frame") == await store.list_by_origin("perception_frame")


@pytest.mark.asyncio
async def test_a_cancelled_blob_write_keeps_the_lock_until_the_bytes_are_written(tmp_path: Path, monkeypatch) -> None:
    """Review round 1, finding 1: a write cancelled during its blob write keeps the lock until the bytes
    are on disk, so a second write of the same hash cannot find a partly written file and skip its own."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    gate = _Gate(Path.write_bytes)
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: gate(self, data))
    blob, h = _blob(b"p")
    first = asyncio.create_task(store.write(h, blob, "image/png", origin="perception_frame"))
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)
        first.cancel()
        await _turns()
        second = asyncio.create_task(store.write(h, blob, "image/png", origin="agent_artifact"))
        await _turns()
        assert not first.done() and not second.done()  # the cancelled write still holds the lock
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await second).read_bytes() == blob
    assert [sha for sha, _ in await store.list_by_origin("agent_artifact")] == [h]


@pytest.mark.asyncio
async def test_the_reapers_stop_returns_only_after_its_cancelled_save_has_finished(tmp_path: Path, monkeypatch) -> None:
    """Review round 1, finding 1, across the seam: shutdown's ``AttachmentReaper.stop()`` cancels a sweep
    whose index save is running. It returns once that save has ended, with the sweep's removal on disk."""
    from probos.attachments.reaper import AttachmentReaper
    from probos.config import AttachmentsConfig, PerceptionConfig

    root = tmp_path / "attachments"
    store = FilesystemAttachmentStore(root)
    blob, h = _blob(b"r")
    await store.write(h, blob, "image/png", origin="perception_frame")
    async with store._lock:  # noqa: SLF001 -- force-age, as tests/test_attachment_reaper.py does
        store._index[h]["written_at"] -= 3600  # noqa: SLF001
    gate = _Gate(FilesystemAttachmentStore._save_index_sync)
    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", lambda self: gate(self))
    reaper = AttachmentReaper(
        store,
        perception_cfg=PerceptionConfig(enabled=True, frame_retention_seconds=30, reaper_interval_seconds=60),
        attachments_cfg=AttachmentsConfig(max_store_bytes=0),
    )
    await reaper.start()  # its first sweep starts at once
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)  # the sweep's removal is saving the index
        stop = asyncio.create_task(reaper.stop())
        await _turns()
        assert not stop.done()  # stop() waits for the save its cancellation interrupted
    finally:
        gate.release.set()
    await stop
    assert gate.finished.is_set()
    assert await FilesystemAttachmentStore(root).list_by_origin("perception_frame") == []


@pytest.mark.asyncio
async def test_a_call_that_fails_after_its_caller_was_cancelled_is_logged(tmp_path: Path, monkeypatch, caplog) -> None:
    """Review round 1, finding 1: the caller ends cancelled, and the error its call raised afterwards is logged."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    gate = _Gate(Path.write_bytes, fail=OSError(errno.EIO, "injected"))
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: gate(self, data))
    caplog.set_level(logging.WARNING, logger="probos.attachments.filesystem_store")
    blob, h = _blob(b"e")
    task = asyncio.create_task(store.write(h, blob, "image/png"))
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)
        task.cancel()
        await _turns()
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any("after its caller was cancelled" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("closed", [False, True], ids=["own-threads", "closed"])
def test_loop_teardown_keeps_the_lock_until_the_interrupted_save_ends(
    tmp_path: Path, monkeypatch, closed: bool
) -> None:
    """Review round 2, finding 1: ``asyncio.run``'s teardown (``Runner.close()``) cancels every task, and
    another task's cleanup still writes to the store while those cancellations unwind. The caller whose
    index save it interrupted keeps the lock until that save has ended, open or closed, so the cleanup's
    durable upgrade is saved after it and survives a reopen and the real reaper. A plain function: the
    Runner owns its loop."""
    from probos.attachments.reaper import AttachmentReaper
    from probos.config import AttachmentsConfig, PerceptionConfig

    root = tmp_path / "attachments"
    store = FilesystemAttachmentStore(root)
    frame, h_frame = _blob(b"f")
    artifact, h_artifact = _blob(b"g")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    claimed: list[bool] = []
    claim = threading.Lock()
    errors: list[str] = []
    states: dict[str, bool] = {}
    pending: list[asyncio.Task[None]] = []
    real_dump = json.dump
    artifact_key = json.dumps(h_artifact)

    class _PausedFile:
        """The first save's file: it pauses after the frame's entry, before the artifact's key."""

        def __init__(self, file) -> None:
            self._file = file

        def write(self, chunk: str) -> int:
            if chunk == artifact_key and not entered.is_set():
                entered.set()
                release.wait(10)
            return self._file.write(chunk)

    def dump(value, file, *args, **kwargs) -> None:
        with claim:
            first = not claimed
            claimed.append(True)
        try:
            real_dump(value, _PausedFile(file) if first else file, *args, **kwargs)
        except BaseException as error:
            errors.append(repr(error))
            raise
        finally:
            if first:
                finished.set()

    async def main() -> None:
        await store.write(h_frame, frame, "image/png", origin="perception_frame")
        await store.write(h_artifact, artifact, "image/png", origin="agent_artifact")
        if closed:
            store.close()
        monkeypatch.setattr(json, "dump", dump)
        interrupted = asyncio.create_task(store.write(h_artifact, artifact, "image/png", origin="agent_artifact"))
        assert await asyncio.to_thread(entered.wait, 5)  # its index save has written the frame's entry

        async def cleanup_writer() -> None:
            try:
                await asyncio.Event().wait()  # pending until the teardown cancels it
            finally:
                await _turns(60)  # the teardown's other cancellations unwind
                states["caller_pending"] = not interrupted.done()
                states["save_running"] = not finished.is_set()
                try:
                    if not interrupted.done():
                        release.set()  # the save may end; this write waits for the lock
                    await store.write(h_frame, frame, "image/png", origin="agent_artifact")
                    states["acknowledged_while_save_ran"] = not finished.is_set()
                finally:
                    release.set()

        pending.extend((interrupted, asyncio.create_task(cleanup_writer())))
        await _turns(3)
        assert not any(task.done() for task in pending)

    try:
        with asyncio.Runner() as runner:
            runner.run(main())  # returns with both tasks pending; leaving the block tears the loop down
    finally:
        release.set()
    assert states == {"caller_pending": True, "save_running": True, "acknowledged_while_save_ran": False}, states
    assert finished.is_set() and errors == [] and pending[0].cancelled()

    async def reopen_and_reap() -> tuple[list[str], bool]:
        recovered = FilesystemAttachmentStore(root)
        reaper = AttachmentReaper(
            recovered,
            perception_cfg=PerceptionConfig(enabled=True, reaper_interval_seconds=60),
            attachments_cfg=AttachmentsConfig(max_store_bytes=1),  # the LRU pass removes all but agent_artifact
        )
        await reaper.sweep_once()
        durable = [sha for sha, _ in await recovered.list_by_origin("agent_artifact")]
        return durable, await recovered.exists(h_frame)

    durable, kept = asyncio.run(reopen_and_reap())
    assert h_frame in durable and kept
```

### 7.6 `ui/src/audio/voice.ts` (M5)

Pair 1 (the event field):

SEARCH:
```ts
   *  pipelining (default-off) every sentence of one reply shares this id.
   *  Absent only on events from a build/mock that predates this field. */
  utterance_id?: number;
}
```
REPLACE:
```ts
   *  pipelining (default-off) every sentence of one reply shares this id.
   *  Absent only on events from a build/mock that predates this field. */
  utterance_id?: number;
  /** BF-918 M5 (#1626, R12): on an 'end' only, and only from AD-1071 pipelining.
   *  `false`: this sentence has ended and more of the same utterance will play.
   *  `true`: nothing more of it will play (its last sentence, or it was stopped).
   *  Absent on every other utterance's 'end', which is always its last. The
   *  arbiter's wait for an entry ignores an 'end' whose `final` is `false`. */
  final?: boolean;
}
```

Pair 2 (the stop hook and the field's value):

SEARCH:
```ts
 *  'dropped' is its terminal event, and the arbiter's wait ends on it. */
const CANCELLED_BEFORE_AUDIO = 'cancelled-before-audio';

```
REPLACE:
```ts
 *  'dropped' is its terminal event, and the arbiter's wait ends on it. */
const CANCELLED_BEFORE_AUDIO = 'cancelled-before-audio';

/** BF-918 M5 (#1626, R12): ends the arbiter's wait for the entry whose AD-1071
 *  sentence queue is running, or null. `stopSpeaking` calls it: a queue stopped
 *  between two sentences fires no 'end' (nothing is playing) and can still be
 *  awaiting the next sentence's synthesis, which must not hold the next utterance. */
let _endSentenceQueueWait: (() => void) | null = null;

/** BF-918 M5: the `final` field of a pipelined sentence's 'end'; nothing for any other
 *  utterance. Read when the 'end' fires: if a stop or a newer dispatch has taken the
 *  device by then, nothing more of this utterance will play. */
function _finalField(last: boolean | undefined, utterance_id: number | undefined): { final?: boolean } {
  if (last === undefined) return {};
  return { final: last || _activeUtteranceId !== utterance_id };
}

```

Pair 3 (the test reset):

SEARCH:
```ts
  _activeUtteranceId = null;
  _dispatchStartedAt = null;
  _sentenceEndedAt = null;
}
```
REPLACE:
```ts
  _activeUtteranceId = null;
  _dispatchStartedAt = null;
  _sentenceEndedAt = null;
  _endSentenceQueueWait = null;
}
```

Pair 4 (the arbiter's wait):

SEARCH:
```ts
      if (event.type !== 'end' && event.type !== 'dropped') return;
      if (event.utterance_id !== entry.id) return;
      done();
    });
```
REPLACE:
```ts
      if (event.type !== 'end' && event.type !== 'dropped') return;
      if (event.utterance_id !== entry.id) return;
      // BF-918 M5 (#1626, R12): under AD-1071 pipelining every sentence fires an 'end'
      // with the reply's id (BF-767). Only the reply's last ends the wait: ending it
      // on the first let the next entry's `_playNow` take the device and cut the rest.
      // Each earlier 'end' re-arms GUARD 2, which then bounds the silence between two
      // events of this entry, not the length of the whole reply.
      if (event.type === 'end' && event.final === false) {
        if (timer !== undefined) { clearTimeout(timer); timer = setTimeout(done, SPEECH_JOIN_TIMEOUT_MS); }
        return;
      }
      done();
    });
```

Pair 5:

SEARCH:
```ts
    // GUARD 1: no engine on this path, so nothing will ever emit an 'end'.
    // Without this the queue wedges on entry one (the BF-290 shape).
    if (!_playNow(entry)) { done(); return; }
```
REPLACE:
```ts
    // GUARD 1: no engine on this path, so nothing will ever emit an 'end'.
    // Without this the queue wedges on entry one (the BF-290 shape).
    if (!_playNow(entry, done)) { done(); return; }
```

Pair 6:

SEARCH:
```ts
 *  signal that no 'end' is ever coming. */
function _playNow(entry: SpeechQueueEntry): boolean {
```
REPLACE:
```ts
 *  signal that no 'end' is ever coming. BF-918 M5: `endWait` ends the arbiter's wait
 *  for this entry; only a stop of its AD-1071 sentence queue calls it. */
function _playNow(entry: SpeechQueueEntry, endWait: () => void): boolean {
```

Pair 7 (the pipelined branch; the two lines after it, the `played === 0` comment and `_fireDropped`, are unchanged):

SEARCH:
```ts
      if (sentences.length > 1) {
        const played = await runPrefetchQueue<PreparedSpeech>(
          sentences,
          (sentence) => _prepareServerSpeech(sentence, profile, emotion),
          (prepared, sentence) => _playPreparedSpeech(prepared, sentence, profile, agent_id, utterance_id),
          () => _activeUtteranceId === utterance_id,
          TTS_PREFETCH_LOOKAHEAD,
          _discardPreparedSpeech,
        );
```
REPLACE:
```ts
      if (sentences.length > 1) {
        const last = sentences.length - 1;
        // BF-918 M5 (#1626, R12): each sentence's 'end' says whether it is the reply's
        // last (`final`), and while this queue runs a stop ends the arbiter's wait.
        _endSentenceQueueWait = endWait;
        let played = 0;
        try {
          played = await runPrefetchQueue<PreparedSpeech>(
            sentences,
            (sentence) => _prepareServerSpeech(sentence, profile, emotion),
            (prepared, sentence, index) => _playPreparedSpeech(prepared, sentence, profile, agent_id, utterance_id, index === last),
            () => _activeUtteranceId === utterance_id,
            TTS_PREFETCH_LOOKAHEAD,
            _discardPreparedSpeech,
          );
        } finally {
          if (_endSentenceQueueWait === endWait) _endSentenceQueueWait = null;
        }
```

Pair 8 (`_playPreparedSpeech`: the parameter, and a failed sentence's browser fallback):

SEARCH:
```ts
 *  visemes. */
async function _playPreparedSpeech(
  prepared: PreparedSpeech | null,
  text: string,
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
  utterance_id: number,
): Promise<void> {
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
    return;
  }
```
REPLACE:
```ts
 *  visemes. BF-918 M5: `last` is set only by the AD-1071 queue (is this the reply's
 *  last sentence); it gives this sentence's 'end' its `final` field. */
async function _playPreparedSpeech(
  prepared: PreparedSpeech | null,
  text: string,
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
  utterance_id: number,
  last?: boolean,
): Promise<void> {
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
    return;
  }
```

Pair 9 (the server sentence's `'end'`):

SEARCH:
```ts
        if (_activeAudio === audio) _activeAudio = null;
        if (fireEnd) _fire({ type: 'end', agent_id, utterance: synth, source: 'server', utterance_id });
        resolve();
```
REPLACE:
```ts
        if (_activeAudio === audio) _activeAudio = null;
        if (fireEnd) _fire({ type: 'end', agent_id, utterance: synth, source: 'server', utterance_id, ..._finalField(last, utterance_id) });
        resolve();
```

Pair 10 (a refused play's fallback):

SEARCH:
```ts
        // play() rejected — fall back to browser for THIS utterance, resolve.
        if (_activeAudio === audio) _activeAudio = null;
        _speakBrowserFallback(text, profile, agent_id, utterance_id);
```
REPLACE:
```ts
        // play() rejected — fall back to browser for THIS utterance, resolve.
        if (_activeAudio === audio) _activeAudio = null;
        _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
```

Pair 11 (a thrown play's fallback):

SEARCH:
```ts
  } catch {
    _invalidateTtsStatus();
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
  }
}
```
REPLACE:
```ts
  } catch {
    _invalidateTtsStatus();
    _speakBrowserFallback(text, profile, agent_id, utterance_id, last);
  }
}
```

Pair 12 (`_speakBrowserFallback`'s parameter):

SEARCH:
```ts
  agent_id?: string,
  utterance_id?: number,
): void {
  if (!('speechSynthesis' in window)) {
```
REPLACE:
```ts
  agent_id?: string,
  utterance_id?: number,
  last?: boolean,
): void {
  if (!('speechSynthesis' in window)) {
```

Pair 13 (its no-engine `'end'`):

SEARCH:
```ts
      utterance: { text } as unknown as SpeechSynthesisUtterance,
      source: 'browser',
      utterance_id,
    });
    return;
```
REPLACE:
```ts
      utterance: { text } as unknown as SpeechSynthesisUtterance,
      source: 'browser',
      utterance_id,
      ..._finalField(last, utterance_id),
    });
    return;
```

Pair 14 (its spoken `'end'`):

SEARCH:
```ts
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id });
```
REPLACE:
```ts
    if (_ended) return;
    _ended = true;
    _fire({ type: 'end', agent_id, utterance, source: 'browser', utterance_id, ..._finalField(last, utterance_id) });
```

Pair 15 (`stopSpeaking`):

SEARCH:
```ts
    try { _activeAudio.pause(); } catch { /* BF-918: barge-in silences server audio too */ }
    _activeAudio = null;
  }
}
```
REPLACE:
```ts
    try { _activeAudio.pause(); } catch { /* BF-918: barge-in silences server audio too */ }
    _activeAudio = null;
  }
  // BF-918 M5 (#1626, R12): a sentence queue stopped between two sentences fires no
  // 'end' (nothing is playing) and can still be awaiting the next sentence's
  // synthesis; end the arbiter's wait for it now. After a pause above, that
  // sentence's 'end' was final and already ended the wait, and this is a no-op.
  const endWait = _endSentenceQueueWait;
  _endSentenceQueueWait = null;
  if (endWait !== null) endWait();
}
```

### 7.7 `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx` (M5: seven cases appended)

The cases reuse this file's harness (`FakeAudio`, `_makeFetch`, `_flush`, `_voice`). The two fake-timer cases fake only `setTimeout` and `clearTimeout`, so `_flush`'s microtasks still run.

SEARCH:
```tsx
      expect(r.events).toEqual(['start:server:Pending.', 'end:server:Pending.', 'start:server:Playing.', 'end:server:Playing.']);
    } finally {
      r.off();
    }
  });
});
```
REPLACE:
```tsx
      expect(r.events).toEqual(['start:server:Pending.', 'end:server:Pending.', 'start:server:Playing.', 'end:server:Playing.']);
    } finally {
      r.off();
    }
  });
});

describe('BF-918 M5: the arbiter waits for a pipelined reply\'s last sentence (R12)', () => {
  const spoken = (): string[] => speakCalls.map((u) => (u as FakeUtterance).text);

  async function _recordEnds() {
    const voiceMod = await import('../voice');
    const events: string[] = [];
    const finals: Array<boolean | undefined> = [];
    const ends: Array<Record<string, unknown>> = [];
    const off = voiceMod.onSpeechEvent((e) => {
      events.push(`${e.type}:${e.utterance?.text ?? ''}`);
      if (e.type === 'end') { finals.push(e.final); ends.push({ ...e }); }
    });
    return { events, finals, ends, off };
  }

  it('P14 a reply queued behind a pipelined reply plays after its last sentence, and cuts none of it', async () => {
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordEnds();
    try {
      voiceMod.speakResponse('One. Two. Three.');
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.']);

      createdAudios[0].end();
      await _flush();
      // R12: before M5, sentence one's 'end' dispatched 'Next.' here, and Two never played.
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
      expect(createdAudios[1].played).toBe(true);
      createdAudios[1].end();
      await _flush();
      expect(createdAudios[2].played).toBe(true);
      expect(f.posted).not.toContain('Next.');

      createdAudios[2].end();
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.', 'Next.']);
      expect(createdAudios[3].played).toBe(true);
      expect(createdAudios.slice(0, 3).every((a) => a.pause.mock.calls.length === 0)).toBe(true);
      expect(r.events.filter((e) => e.startsWith('start'))).toEqual(['start:One.', 'start:Two.', 'start:Three.', 'start:Next.']);
      expect(r.finals).toEqual([false, false, true]);
    } finally {
      r.off();
    }
  });

  it('P15 a stop between two sentences frees the arbiter at once, while the next sentence still synthesizes', async () => {
    const f = _makeFetch({ pipelining: true, holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordEnds();
    try {
      voiceMod.speakResponse('One. Two.');
      await _flush();
      createdAudios[0].end(); // One ends; Two is still synthesizing, so nothing plays
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.']);
      expect(createdAudios.length).toBe(1);

      voiceMod.stopSpeaking();
      voiceMod.speakResponse('Next.');
      await _flush();
      // Dispatched now, not when Two's synthesis answers (or after SPEECH_JOIN_TIMEOUT_MS).
      expect(f.posted).toEqual(['One.', 'Two.', 'Next.']);
      expect(createdAudios[1].played).toBe(true); // Next's audio

      f.release(); // Two's synthesis answers after the stop
      await _flush();
      expect(createdAudios[2].played).toBe(false);
      expect(createdAudios[2].discarded).toBe(true);
      expect(r.finals).toEqual([false]); // One's 'end' said more would follow; the stop fired none
    } finally {
      r.off();
    }
  });

  it('P16 the join timeout bounds the silence between two sentences, not the length of the reply', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const f = _makeFetch({ pipelining: true });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      const step = voiceMod.SPEECH_JOIN_TIMEOUT_MS - 5000;
      voiceMod.speakResponse('One. Two. Three.');
      voiceMod.speakResponse('Next.');
      await _flush();
      vi.advanceTimersByTime(step);
      await _flush();
      createdAudios[0].end();
      await _flush();
      vi.advanceTimersByTime(step);
      await _flush();
      createdAudios[1].end();
      await _flush();
      vi.advanceTimersByTime(step);
      await _flush();
      // Far longer than SPEECH_JOIN_TIMEOUT_MS since the dispatch, never that long without an event of this reply.
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
      expect(createdAudios[2].pause).not.toHaveBeenCalled();
      createdAudios[2].end();
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.', 'Three.', 'Next.']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('P17 the join timeout still frees a reply that goes silent between two sentences (GUARD 2)', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      const f = _makeFetch({ pipelining: true, holdTts: [2] });
      (globalThis as any).fetch = f.fetchMock;
      const voiceMod = await _voice();
      voiceMod.speakResponse('One. Two.');
      voiceMod.speakResponse('Next.');
      await _flush();
      createdAudios[0].end(); // Two's synthesis never answers in time
      await _flush();
      vi.advanceTimersByTime(voiceMod.SPEECH_JOIN_TIMEOUT_MS - 1);
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.']);
      vi.advanceTimersByTime(1);
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.', 'Next.']);
      f.release();
      await _flush();
      expect(createdAudios[2].played).toBe(false); // Two's, discarded: Next owns the device
      expect(createdAudios[2].discarded).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('P18 with pipelining off, an end carries no final and ends the wait as before', async () => {
    const f = _makeFetch({ pipelining: false });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordEnds();
    try {
      voiceMod.speakResponse('One. Two.');
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['One. Two.']);
      createdAudios[0].end();
      await _flush();
      expect(f.posted).toEqual(['One. Two.', 'Next.']);
      expect(r.ends.length).toBe(1);
      expect(r.ends.every((e) => !('final' in e))).toBe(true);
    } finally {
      r.off();
    }
  });

  it('P19 a middle sentence the browser speaks (its synthesis failed) does not end the wait', async () => {
    const f = _makeFetch({ pipelining: true, failTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordEnds();
    try {
      voiceMod.speakResponse('One. Two. Three.');
      voiceMod.speakResponse('Next.');
      await _flush();
      createdAudios[0].end();
      await _flush();
      // Two failed: the browser speaks it, and Three plays meanwhile (R3, unchanged).
      expect(spoken()).toEqual(['Two.']);
      expect(createdAudios[1].played).toBe(true);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      expect(f.posted).not.toContain('Next.');
      expect(createdAudios[1].pause).not.toHaveBeenCalled();
      createdAudios[1].end();
      await _flush();
      expect(f.posted).toContain('Next.');
      expect(r.finals).toEqual([false, false, true]);
    } finally {
      r.off();
    }
  });

  it('P20 the end of a sentence a stop cuts is final', async () => {
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _recordEnds();
    try {
      voiceMod.speakResponse('One. Two.');
      await _flush();
      voiceMod.stopSpeaking();
      await _flush();
      expect(r.events.filter((e) => e.startsWith('end'))).toEqual(['end:One.']);
      expect(r.finals).toEqual([true]);
    } finally {
      r.off();
    }
  });
});
```

## 8. Tracking

The `PROGRESS.md` pairs are substrings of its one-line BF-918 entry. They contain no line break, and each occurs once. A tool that matches only whole lines must be told to match the substring. M4's and M5's pairs anchor on disjoint text, so either slice can be committed first. Set the date to the commit date.

**M4, `PROGRESS.md`** (pair 1):

SEARCH:
```markdown
Rhubarb and ffmpeg run on the same executor (the attachment store's write and lookups still use the default pool: slice M4 of #1626), and the route logs per-stage timings.
```
REPLACE:
```markdown
Rhubarb and ffmpeg run on the same executor, and the route logs per-stage timings. M4 (2026-10-24): the attachment store runs its blocking I/O (file reads and writes, path lookups, the index save) on 4 threads of its own (a cancelled caller waits for its call, so index saves never overlap, even while `asyncio.run` tears the loop down), closed after the attachment reaper at shutdown (later callers use the default pool), so crew work that fills asyncio's default pool no longer delays storing or serving spoken audio; `tests/test_bf918_attachment_io.py`.
```

**M4, `PROGRESS.md`** (pair 2):

SEARCH:
```markdown
#1626 stays open for slices M4 (a bounded I/O executor owned by the attachment store),
```
REPLACE:
```markdown
#1626 stays open for slices
```
(The space that followed the comma stays, so the text reads "slices M5 (..." or, after M5, "slices M6 (...".)

**M4, `DECISIONS.md`:**

SEARCH:
```markdown
The attachment store's I/O stays on the default pool (slice M4 of #1626).
```
REPLACE:
```markdown
M4 (2026-10-24): the attachment store owns a 4-thread I/O executor (`ATTACHMENT_IO_WORKERS`, a constant like the voice limits) for every blocking call it makes except the constructor's (resolving and making the root, loading the index). A cancelled caller waits for its call to end, so the store's lock is never released while an index save or blob call still runs, and a store first built after shutdown's close point is built closed (A1, review round 1). After `close()` a call is the default pool's own future, never a task, so the event loop's teardown, which cancels every task, cannot end that wait early (A2, review round 2). Calls beyond it queue, never refuse. `close()` runs after the attachment reaper; afterwards calls use the default pool, so a late caller still completes, and accepted work is never cancelled. Rejected: a config field (no tuning need), and refusing after close (a refused artifact write is lost data).
```

**M5, `PROGRESS.md`** (pair 1):

SEARCH:
```markdown
Two User Timing measures were added (`bf918:first-audio`, `bf918:sentence-gap`).
```
REPLACE:
```markdown
Two User Timing measures were added (`bf918:first-audio`, `bf918:sentence-gap`). M5 (2026-10-24): with pipelining on, a reply queued behind a multi-sentence reply waits for that reply's last sentence instead of cutting it after its first. An AD-1071 sentence's `end` carries `final` (`false` while more of the reply will play); the speech arbiter ignores `final: false`, its join timeout bounds the silence between two sentences rather than the reply's length, and a stop between two sentences frees it at once.
```

**M5, `PROGRESS.md`** (pair 2):

SEARCH:
```markdown
M5 (the arbiter's wait ends on a pipelined reply's last sentence) and M6 (an older reply's `end` no longer completes a newer reply's turn in the same conversation arm)
```
REPLACE:
```markdown
M6 (an older reply's `end` no longer completes a newer reply's turn in the same conversation arm) and M7 (in conversation mode, a pipelined reply's turn completes on its last sentence's `end`, not its first)
```

**M5, `DECISIONS.md`:**

SEARCH:
```markdown
Not covered: an `'inactive'` the controller coalesces (the contract's R21), and an older reply's `end` within one arm (slice M6 of #1626).
```
REPLACE:
```markdown
Not covered: an `'inactive'` the controller coalesces (the contract's R21), an older reply's `end` within one arm (slice M6 of #1626), and a pipelined reply's earlier sentences completing its conversation turn (slice M7). M5 (2026-10-24): an AD-1071 sentence's `end` carries `final` (`false` while more of the reply will play; absent on every other utterance). The arbiter's wait ignores `final: false` and re-arms its join timeout on it, and a stop between sentences ends it. Rejected: an internal-only signal (M7 needs the same fact), ending the wait when the sentence queue returns (it would cut a last sentence spoken by the browser fallback), and a new event type.
```

No `docs/development/roadmap.md` change (no new BF).

**#1626's acceptance checklist** (the orchestrator edits the issue):

- `[x] M4: the attachment store runs its blocking I/O on 4 threads of its own, closed after the attachment reaper (BF-918 §18 R9). Its reach is judged from the live store_ms (§16 step 1).` Tick it at M4's merge.
- `[x] M5: with pipelining on, a queued utterance waits for a pipelined reply's last sentence (BF-918 §18 R12).` Tick it at M5's merge.
- Add, unticked: `[ ] M7: in conversation mode with pipelining on, a reply's turn completes on its last sentence's end (final), not its first (found while drafting M5; with M6).`
- The live-acceptance item is unblocked by M4 and M5 together.
- Record §18's R22 correction and R26 to R31 in #1626's register (A1), with R26's design and R31's cost as A2 updates them.

## 9. What this does NOT change

- `ProfileChatTab.tsx`, `conversationController.ts` and `useMeetingVoice`: they still act on every `'end'` (M6 and M7). The meeting sequencer's next reply is now held by the arbiter until the pipelined reply's last sentence, which is M5's purpose.
- `speechQueueStore.ts`, `voiceChunking.ts` (`runPrefetchQueue` already passes `index` to `play`, `:111`), `flushSpeechQueue`, pre-emption, `dropped` and its reasons, BF-655's one `'end'` per `'start'`.
- No new export from `voice.ts` (about 50 test files mock it with factories).
- The `AttachmentStore` protocol (`store.py`): `close` is a filesystem-store lifecycle method, not part of the I/O seam a cloud store implements.
- `routers/avatars.py`, `routers/chat.py`'s routes, the reaper, configuration and generated files. `FileResponse`'s own file streaming (Starlette, on its own threads) is outside the store (§18).
- Pipelining stays default-off.

## 10. Mutation rows (21 Python after A2, 8 TypeScript; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row on the applied tree after an unmutated baseline run passes, and restore each file before the next row.

Python campaign command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_attachment_io.py tests/test_ad720_attachment_store.py -n 0 -x -q
```

The TypeScript rows are run by hand, from `ui/`: `npx vitest run src/audio/__tests__/voice.prefetch.bf918.test.tsx`.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| M4-1 | `src/probos/attachments/filesystem_store.py` | `call = asyncio.get_running_loop().run_in_executor(self._io_executor, fn, *args)` | `call = asyncio.ensure_future(asyncio.to_thread(fn, *args))` | `test_store_io_does_not_wait_for_a_busy_default_pool`, `test_every_blocking_call_runs_on_the_store_threads`, `test_filesystem_store_runs_blocking_io_on_its_own_threads`, `test_loop_teardown_keeps_the_lock_until_the_interrupted_save_ends[own-threads]` (the teardown cancels the task the mutant makes) |
| M4-2 | `src/probos/attachments/filesystem_store.py` | `if self._io_closed:` | `if True:` | the same three |
| M4-3 | `src/probos/attachments/filesystem_store.py` | `self._io_closed = True` | `self._io_closed = False` | `test_a_closed_store_still_stores_and_serves_on_the_default_pool`, `test_close_lets_accepted_work_finish_and_its_threads_exit`, `test_shutdown_closes_the_cached_store_after_the_reaper_and_builds_none` |
| M4-4 | `src/probos/attachments/filesystem_store.py` | `executor.shutdown(wait=False, cancel_futures=False)` | `executor.shutdown(wait=False, cancel_futures=True)` | `test_close_lets_accepted_work_finish_and_its_threads_exit` (the queued lookup is cancelled) |
| M4-5 | `src/probos/attachments/filesystem_store.py` | `max_workers=self._io_workers,` | `max_workers=self._io_workers + 1,` | `test_calls_beyond_the_bound_queue_and_all_complete` |
| M4-6 | `src/probos/attachments/filesystem_store.py` | `if io_workers < 1:` | `if io_workers < 0:` | `test_a_store_needs_at_least_one_io_thread[0]` |
| M4-7 | `src/probos/attachments/filesystem_store.py` | `matches = await self._run(` | `matches = await asyncio.to_thread(` | `test_store_io_does_not_wait_for_a_busy_default_pool` (the lookup of `exists` and `get_path`) |
| M4-8 | `src/probos/attachments/filesystem_store.py` | `return await self._run(path.read_bytes)` | `return await asyncio.to_thread(path.read_bytes)` | `test_store_io_does_not_wait_for_a_busy_default_pool`, `test_every_blocking_call_runs_on_the_store_threads` |
| M4-9 | `src/probos/attachments/filesystem_store.py` | `await self._run(path.write_bytes, blob)` | `await asyncio.to_thread(path.write_bytes, blob)` | `test_store_io_does_not_wait_for_a_busy_default_pool`, `test_every_blocking_call_runs_on_the_store_threads`, `test_filesystem_store_runs_blocking_io_on_its_own_threads` |
| M4-10 | `src/probos/startup/shutdown.py` | `_close_attachment_store(runtime)` | `pass` | `test_shutdown_closes_the_cached_store_after_the_reaper_and_builds_none` |
| M4-11 | `src/probos/routers/chat.py` | `store.close()` | `pass` | `test_shutdown_closes_the_cached_store_after_the_reaper_and_builds_none`, `test_a_store_first_built_after_the_close_point_is_born_closed` |
| M4-12 | `src/probos/attachments/filesystem_store.py` | `await _finish_cancelled(call)` | `pass` | `test_a_cancelled_caller_keeps_the_lock_until_its_index_save_finishes` (all six cases: the caller ends while its save still runs), `test_a_cancelled_blob_write_keeps_the_lock_until_the_bytes_are_written`, `test_the_reapers_stop_returns_only_after_its_cancelled_save_has_finished` |
| M4-13 | `src/probos/attachments/filesystem_store.py` | `return await asyncio.shield(call)` | `return await call` | the same three (cancelling the caller cancels its call's future while the thread goes on) |
| M4-14 | `src/probos/attachments/filesystem_store.py` | `pass  # cancelled again: keep waiting; the caller re-raises the first cancellation` | `raise` | `test_a_cancelled_caller_keeps_the_lock_until_its_index_save_finishes` (the second cancellation ends the caller before its save does) |
| M4-15 | `src/probos/attachments/filesystem_store.py` | `if not call.cancelled() and call.exception() is not None:` | `if False:` | `test_a_call_that_fails_after_its_caller_was_cancelled_is_logged` |
| M4-16 | `src/probos/attachments/filesystem_store.py` | `path, present = await self._run(self._locate_sync, content_hash, mime)` | `path, present = self._locate_sync(content_hash, mime)` | `test_every_blocking_call_runs_on_the_store_threads` (`resolve` and `exists` run on the event loop's thread) |
| M4-17 | `src/probos/attachments/filesystem_store.py` | `return await self._run(lambda: path.stat().st_size)` | `return await asyncio.to_thread(lambda: path.stat().st_size)` | `test_every_blocking_call_runs_on_the_store_threads` (`size`'s stat runs on a default-pool thread) |
| M4-18 | `src/probos/routers/chat.py` | `if cached is _CLOSED_BEFORE_BUILD:` | `if False:` | `test_a_store_first_built_after_the_close_point_is_born_closed` |
| M4-19 | `src/probos/routers/chat.py` | `_ATTACHMENT_STORE_CACHE[key] = _CLOSED_BEFORE_BUILD` | `pass` | `test_a_store_first_built_after_the_close_point_is_born_closed` |
| M4-20 | `src/probos/attachments/filesystem_store.py` | `call = asyncio.get_running_loop().run_in_executor(None, contextvars.copy_context().run, fn, *args)` | `call = asyncio.ensure_future(asyncio.to_thread(fn, *args))` | `test_loop_teardown_keeps_the_lock_until_the_interrupted_save_ends[closed]` (the teardown cancels the task, and the caller leaves the lock while its save still runs) |
| M4-21 | `src/probos/attachments/filesystem_store.py` | `return await self._run(_scan)` | `return _scan()` | `test_every_blocking_call_runs_on_the_store_threads` (`iterdir` and `is_file` run on the event loop's thread) |
| M5-1 | `ui/src/audio/voice.ts` | `if (event.type === 'end' && event.final === false) {` | `if (false) {` | run by hand: P14 (`Next.` posted after One's end), P16, P19 |
| M5-2 | `ui/src/audio/voice.ts` | `if (timer !== undefined) { clearTimeout(timer); timer = setTimeout(done, SPEECH_JOIN_TIMEOUT_MS); }` | `{}` | run by hand: P16 (the wait times out during Two) |
| M5-3 | `ui/src/audio/voice.ts` | `if (endWait !== null) endWait();` | `if (false) endWait();` | run by hand: P15 (`Next.` waits) |
| M5-4 | `ui/src/audio/voice.ts` | `_endSentenceQueueWait = endWait;` | `void endWait;` | run by hand: P15 |
| M5-5 | `ui/src/audio/voice.ts` | `(prepared, sentence, index) => _playPreparedSpeech(prepared, sentence, profile, agent_id, utterance_id, index === last),` | `(prepared, sentence, index) => _playPreparedSpeech(prepared, sentence, profile, agent_id, utterance_id, true),` | run by hand: P14 (finals, and `Next.` early) |
| M5-6 | `ui/src/audio/voice.ts` | `return { final: last \|\| _activeUtteranceId !== utterance_id };` | `return { final: last };` | run by hand: P20 |
| M5-7 | `ui/src/audio/voice.ts` | `if (last === undefined) return {};` | `if (false) return {};` | run by hand: P18 (the single-call `end` is ignored and `Next.` waits) |
| M5-8 | `ui/src/audio/voice.ts` | `if (fireEnd) _fire({ type: 'end', agent_id, utterance: synth, source: 'server', utterance_id, ..._finalField(last, utterance_id) });` | `if (fireEnd) _fire({ type: 'end', agent_id, utterance: synth, source: 'server', utterance_id });` | run by hand: P14 |

(In M5-6 the table escapes `||` as `\|\|`; the line in the file has `||`.)

No row for: the three `await self._run(self._save_index_sync)` lines and the three `_speakBrowserFallback(text, profile, agent_id, utterance_id, last);` lines, because each text occurs more than once in its file. They are covered by `test_every_blocking_call_runs_on_the_store_threads` (write's and unlink's save) and by P19 (the failed-synthesis fallback). Also no row for `need_write = not present` (A1; the dispatch of `_locate_sync` is M4-16). No source row for review round 1's finding 2: A1 changes only tests there (the thread-exit test compares the thread object, and the files close the stores they build). Its evidence is the focused check's order, which runs `tests/test_ad1242_crew_verifier_trace.py` first, in the same process; that ordering failed on candidate 1.

A2 adds no row for dropping the closed branch's context copy (`run_in_executor(None, fn, *args)`): no store call reads a contextvar (§14 M4 property 7), so that mutant is equivalent through the store. M4-2 (`if True:`) now selects A2's closed branch; its killers are unchanged.

## 11. Verified Against Codebase (2026-10-24, worktree `m45-draft`, detached at `origin/main` `cb190f32`, clean)

```
git log --oneline -3
  cb190f32 Merge pull request #1645 from seangalliher/fix/bf918-20261024-26bec26d
grep -n "to_thread" src/probos/attachments/filesystem_store.py
  3, 5 (docstring); 229: await asyncio.to_thread(path.write_bytes, blob); 270: matches = await asyncio.to_thread(;
  279: return await asyncio.to_thread(path.read_bytes); 293: return await asyncio.to_thread(lambda: path.stat().st_size);
  306: await asyncio.to_thread(path.unlink); 358: freed = (await asyncio.to_thread(path.stat)).st_size;
  359: await asyncio.to_thread(path.unlink); 417: return await asyncio.to_thread(_scan)
filesystem_store.py:101  def __init__(self, root: Path) -> None:
filesystem_store.py:109  self._lock = asyncio.Lock()
filesystem_store.py:226  need_write = not path.exists()          (on the event loop)
filesystem_store.py:260, 320, 371  self._save_index_sync()  (on the event loop, inside `async with self._lock`)
filesystem_store.py:225, 301, 344, 379, 394  async with self._lock:   (every _index mutation and read in the file)
filesystem_store.py:21-28  imports: asyncio, errno, json, logging, os, time, Path, Any (no concurrent.futures, Callable, TypeVar)
routers/chat.py:1004  _ATTACHMENT_STORE_CACHE: dict[int, Any] = {}
routers/chat.py:1007-1019  _get_attachment_store; 1017: store = FilesystemAttachmentStore(root)
routers/chat.py:1253  if not await store.exists(content_hash):   1255: path = await store.get_path(content_hash)
routers/avatars.py:301  await store.write(attachment_id, result.audio_bytes, result.mime, origin="tts_audio")
routers/avatars.py:315  audio_path = await store.get_path(attachment_id)
runtime.py:2241-2248  attachment_store property -> _get_attachment_store(self) (builds one if absent)
startup/shutdown.py:9-16  imports asyncio, contextlib, inspect, json, logging, math, sqlite3, time (no sys)
startup/shutdown.py:81-93  _close_voice_synthesis (pattern for the helper)
startup/shutdown.py:1597-1605  _close_voice_synthesis(runtime); AD-733-1 reaper stop block
startup/finalize.py:753-764  the reaper is built on _get_attachment_store(runtime)
audio/tts/resident.py:46-50  VOICE_EXECUTOR_WORKERS = 4 ... constants, not config
audio/tts/resident.py:367-376  the voice executor, made on first use, thread_name_prefix="probos-voice"
tests/conftest.py:166-168  chat_router._ATTACHMENT_STORE_CACHE.clear() per test
tests/fixtures/runtime_lifecycle.py:71, 144-156  non-daemon thread detector excludes only "asyncio_"; :271-277 polls
tests/test_ad720_attachment_store.py:93-105  test_filesystem_store_uses_asyncio_to_thread (updated in §7.4)
tests/test_bf918_tts_latency.py:500-517  busy-default-pool pattern reused in §7.5
voice.ts:59-80  SpeechEventType, SpeechEvent (utterance_id at :79, no final field)
voice.ts:223-231  _resetTtsStatusForTests
voice.ts:254-260  TTS_PREFETCH_LOOKAHEAD, CANCELLED_BEFORE_AUDIO
voice.ts:391-410  _drainSpeechQueue; 416-456 _awaitEntry (listener :438-446, GUARD 1 :450, GUARD 2 :454)
voice.ts:487  function _playNow(entry: SpeechQueueEntry): boolean {   512: _activeUtteranceId = utterance_id;
voice.ts:548-563  pipelined branch; 551 const played = await runPrefetchQueue; 555 shouldContinue; 561 played === 0 -> dropped
voice.ts:592-603  _synthesizeAndPlay calls _playPreparedSpeech with five arguments (no `last`)
voice.ts:684-774  _playPreparedSpeech: 693 fallback, 712-718 _finish (716 the 'end'), 733 pause -> _finish(true), 764-767 reject fallback, 770-773 catch fallback
voice.ts:816-877  _speakBrowserFallback: 840-847 no-engine 'end', 868-872 _fireBrowserEnd
voice.ts:893-910  stopSpeaking: 898 _activeUtteranceId = null before 907 pause
voiceChunking.ts:84-124  runPrefetchQueue; 111 await play(prepared, items[i], i); 104/108 shouldContinue breaks
voice.prefetch.bf918.test.tsx:1-164  harness (FakeAudio, _makeFetch with holdTts/failTts, _flush 40 turns); 525-530 the file's last case
ProfileChatTab.tsx:2190-2205  reply listener: 'end' with own id completes (M6, M7)
ProfileChatTab.tsx:1385-1393  in-flight keys clear on every 'end' or 'dropped' of the agent
conversationController.ts:350-364  barge-in only in agent_speaking; 450-471 markAgentReplyComplete -> silence_pending
A1 (2026-10-24, candidate 1 6d63cc93, tree 9796b2bb):
filesystem_store.py:135-150  _run (to_thread in the closed branch :144; run_in_executor :150)
filesystem_store.py:244-259  _path_for (resolve :254); :278 its one call, before the lock
filesystem_store.py:315, 375, 426  await self._run(self._save_index_sync), each under `async with self._lock`
routers/chat.py:1004-1033  the cache, the factory, the closer
attachments/reaper.py:75-92  stop(): cancel, then await the task (no timeout); 94-99 the first sweep runs at start; 230-239 _safe_reap catches Exception only
tests/test_attachment_reaper.py:24-56  _make_cfg and the force-age pattern
tests/test_ad720_attachments_endpoint.py:34-37  monkeypatch of probos.attachments.store._resolve_attachments_dir
tests/conftest.py:222-224  _ATTACHMENT_STORE_CACHE.clear() per test
pyproject.toml:9  requires-python = ">=3.12"
git show e973acbe:src/probos/attachments/filesystem_store.py  229 await asyncio.to_thread(path.write_bytes, blob) under the lock (:225); 260, 320, 371 self._save_index_sync() on the loop
```

## 12. Absence Verified (2026-10-24)

```
CLAIM: only routers/chat.py builds a FilesystemAttachmentStore in src
RUN:   Grep "FilesystemAttachmentStore\(" src/
FOUND: routers/chat.py:1017
HOLDS: yes; the shutdown helper's sys.modules check is sound

CLAIM: only one test depends on the store dispatching through asyncio.to_thread
RUN:   Grep "to_thread" tests/ (all files), then the store-specific hits
FOUND: test_ad720_attachment_store.py:93-105 (the store); test_ad818a*_paginated_migrations.py (episodic, unrelated);
       test_ad1124_crew_session_contract.py:2056 (another service's source); test_bf918_tts_latency.py:507 (the default pool, not the store)
HOLDS: yes; §7.4 updates the one

CLAIM: no ?raw or source-scan test reads filesystem_store.py or voice.ts
RUN:   Grep "voice\.ts\?raw|voice\?raw|filesystem_store\.py" tests/ ui/src/
FOUND: none (the shutdown source scans parse shutdown(); none counts Name calls in a way the new call breaks:
       test_issue1419 counts `with steps(...)` and the two named helpers; test_bf918_tts_latency.py:730-735 checks a Name is present)
HOLDS: yes

CLAIM: _playNow has one caller
RUN:   Grep "_playNow\(" ui/src/
FOUND: voice.ts:450 (the call), voice.ts:487 (the definition)
HOLDS: yes

CLAIM: no SpeechEvent consumer or producer uses a `final` field today
RUN:   Grep "\.final\b|final\?:|\bfinal:" ui/src/
FOUND: transformersStt.ts:115, 277, 389-390 and its test (an STT job's own field, unrelated)
HOLDS: yes

CLAIM: no existing test enqueues a second utterance behind a running pipelined reply (none pins R12's truncation)
RUN:   Grep "sentence_pipelining_enabled: true|pipelining: true" ui/src/
FOUND: voice.pipelining.test.tsx (2; each case speaks one reply), voice.prefetch.bf918.test.tsx (6; P9 enqueues 'Next.' only after a stop)
HOLDS: yes

CLAIM: no BF-918 mutation row pins a line M5 changes
RUN:   Grep "_playPreparedSpeech\(prepared, sentence|_playNow\(entry\)|_speakBrowserFallback\(text, profile, agent_id, utterance_id\)|if \(fireEnd\) _fire" prompts/bf-918-tts-first-audio-latency.md
FOUND: only §7 code blocks (4647, 4783, 4806, 4856, 4862); none in §10 (rows start at 6576)
HOLDS: yes

CLAIM: routers/chat.py has no close_attachment_store and no store.close() today
RUN:   Grep "store\.close\(\)|def close_attachment_store" src/probos/routers/chat.py
FOUND: none
HOLDS: yes (row M4-11's pinned line is unique after §7.2)

CLAIM (A1): `_path_for` has one caller, so moving it into `_locate_sync` changes no other path
RUN:   Grep "_path_for\(|_save_index_sync|\.io_closed|store\._run|\._io_executor" src/ tests/
FOUND: filesystem_store.py:278 (write); avatars/telemetry_history.py:52, 68, 109 (another class's own method)
HOLDS: yes

CLAIM (A1): only the factory and the closer read `_ATTACHMENT_STORE_CACHE`'s values, so no other reader sees the marker
RUN:   Grep "_ATTACHMENT_STORE_CACHE" (101 hits, 34 files); Grep "_ATTACHMENT_STORE_CACHE(\.get|\[[^\]]*\]\s*(is|==)|\.values|\.items| not in|\)| in )" tests/; Grep "in (chat_router\.|chat\.|chat_mod\.|_chat\.)?_ATTACHMENT_STORE_CACHE|len\(.*_ATTACHMENT_STORE_CACHE" tests/
FOUND: src: routers/chat.py only; tests: test_bf918_attachment_io.py:197 (updated by A1) and :207 (still true), test_conftest_attachment_store_cache_isolation.py:43 (an id left by an earlier test); every other test hit assigns, pops or clears
HOLDS: yes

CLAIM (A1): no public runtime flag says shutdown has started
RUN:   Grep "_shutdown_started" src/probos
FOUND: runtime.py:1550 (private field), startup/shutdown.py:887, 894
HOLDS: yes (decision 11 b)

CLAIM (A2): on candidate 2, the closed branch is the only task in `_run`'s drain path
RUN:   Grep "ensure_future|create_task|to_thread|contextvars" src/probos/attachments/filesystem_store.py (candidate 2 `a8619b3b`)
FOUND: :172 only (`call = asyncio.ensure_future(asyncio.to_thread(fn, *args))`, which A2 replaces)
HOLDS: yes; after A2 the file has neither `to_thread` nor `ensure_future`, and `contextvars` is a new import

CLAIM (A2): no test pins the closed branch's text, and no source scan reads the store
RUN:   Grep "to_thread" tests/test_bf918_attachment_io.py tests/test_ad720_attachment_store.py; Grep "getsource\(.*(FilesystemAttachmentStore|filesystem_store)|filesystem_store\.py" tests/
FOUND: test_bf918_attachment_io.py:341, 370, 406, 427 (each test's own wait on a gate Event); test_ad720_attachment_store.py:98 (a docstring); the second search: none
HOLDS: yes

CLAIM (A2): `Runner.close()` cancels tasks only, and `asyncio.to_thread` is a coroutine around `run_in_executor`
RUN:   CPython 3.12 Lib/asyncio/runners.py and Lib/asyncio/threads.py, read on GitHub
FOUND: `_cancel_all_tasks`: `to_cancel = tasks.all_tasks(loop)`, `task.cancel()`, `gather(*to_cancel, return_exceptions=True)`, before `shutdown_default_executor`; `to_thread`: `ctx = contextvars.copy_context()`, `return await loop.run_in_executor(None, func_call)`
HOLDS: yes; a `run_in_executor` future is not a task, so the teardown never cancels it
```

## 13. Prior Art and Blind Spots

Both slices are bug fixes inside BF-918, so the external prior-art search was skipped per the drafting standards, and so was the overdue review in `docs/research/reference-projects.md` (considered, deferred). Internal prior art used:

- **BF-918 D4** (`resident.py:337-376`): a service-owned executor made on first use and closed at shutdown. M4 copies the shape, but its closed state degrades to the default pool instead of refusing, because store I/O carries data, not best-effort voice.
- **AD-1291 / BF-764 / BF-767**: the arbiter and its correlation on `utterance_id`. M5 keeps both guards, and GUARD 2 changes from a deadline to an inactivity bound only for pipelined entries.
- **AD-1291's additive `dropped`**: the precedent for adding to `SpeechEvent` without breaking its nine consumers.

Blind spots found and settled:

1. **A pipelined reply longer than 45 s.** Ending the wait on the last sentence alone would let GUARD 2 fire during a long reply and cut it (P16). The fix re-arms the timeout on each non-final `end`.
2. **A stop between two sentences** fires no `end`, and the queue can still be awaiting a synthesis bounded by Piper's timeout. Without the stop hook, the next utterance would wait for that synthesis (P15).
3. **A browser-spoken last sentence (R3).** Ending the wait when the queue returns would cut it, so the wait ends on its own `final` `end` instead (decision 7c; P19 covers a middle one).
4. **The same per-sentence `end` one consumer up:** the conversation turn (M7).
5. **Contextvars:** `run_in_executor` does not copy the caller's context, as `to_thread` did. No store call reads a contextvar (filesystem calls only).
6. **Test threads:** store threads are non-daemon, and the lifecycle detector excludes only `asyncio_` (`runtime_lifecycle.py:71`). Shutdown closes the store and the detectors poll. A store that is never closed is garbage-collected after the per-test cache clear, and `ThreadPoolExecutor`'s weak-reference wake-up then ends its idle threads.

## 14. Diff Reviewer: properties to verify

**M4** (consumers: every caller of the store: the attachment reaper and its `stop()`, the chat, avatar (TTS) and federation routes, crew work through `runtime.attachment_store` and the other callers of `_get_attachment_store`; also `shutdown()` and the runtime lifecycle tests)
1. In `filesystem_store.py`, every blocking call except the constructor's (`root.resolve()`, `mkdir`, `_load_index_sync`) goes through `_run`, including `write`'s path resolution and existence check (`_locate_sync`, A1) and the cold size scan, and neither `to_thread` nor `ensure_future` occurs in the file (A2).
2. Every index save runs while `self._lock` is held, and nothing in the file mutates or reads `_index` outside that lock. The lock is released only after the call it guards has ended, also when the caller is cancelled once or more (A1).
3. `close()` cancels nothing, never blocks, is idempotent, and every store method still works after it.
4. Exceptions raised on a store thread (ENOSPC, `FileNotFoundError`, other `OSError`) reach the caller unchanged, so `write`'s errno handling still applies.
5. The `ValueError` for `io_workers < 1` comes before any directory is made.
6. Shutdown closes the store after the reaper's stop, builds no store, never raises, and keeps the cached instance.
7. The store's blocking calls read no contextvar; a closed store's calls still get a copy of the caller's context (`contextvars.copy_context().run`, as `asyncio.to_thread` gave them; A2).
8. (A1) A cancelled caller of `_run` ends with `CancelledError` only after its call has ended, on the store's threads and after close. A second cancellation while it waits does not end it sooner, and an exception its call raises afterwards is logged, not raised. `AttachmentReaper.stop()` returns after the save it interrupted. A caller waits longer than before only for the remainder of its own call.
9. (A1) After the closer ran with nothing cached, the store that `_get_attachment_store` first builds for that runtime is closed before it is returned. The closer still builds nothing, the marker is cleared with the cache (`tests/conftest.py`), and no reader of `_ATTACHMENT_STORE_CACHE` other than the factory and the closer can see it.
10. (A1) Tests: the thread-exit test checks the exact thread object; every store built in `test_bf918_attachment_io.py`, and the `store` fixture of `test_ad720_attachment_store.py`, is closed at teardown; the new cancellation tests synchronise on Events and event-loop turns; the lifecycle detector is unchanged.
11. (A2) In both branches `_run` drains `run_in_executor`'s own future: no task stands between a caller and its thread. While the event loop runs, including inside `asyncio.Runner.close()` (which `asyncio.run` calls and which cancels every task), no store caller, open or closed, returns or releases the store's lock before the thread running its call has returned, so another task's cleanup cannot save the index over a running save. Boundary: mutual exclusion, not completion; a task first created during teardown is not awaited by the Runner and may be left pending when the loop closes, its call still finishing on its thread. The teardown test is a plain function on a real `asyncio.Runner` and synchronises on Events and loop turns.

**M5** (consumers: every `onSpeechEvent` listener, the drain, the meeting sequencer, `ProfileChatTab`)
1. With pipelining off, every event `voice.ts` emits is unchanged (no `final` key), and the arbiter's wait ends exactly as before.
2. Under pipelining, the wait ends on the reply's last sentence's `end`, on a stopped sentence's `end`, on `stopSpeaking` between sentences, on the entry's `dropped`, or on GUARD 2 after 45 s with no non-final `end` of the entry. It never ends on an `end` with `final: false`.
3. Each sentence still has exactly one `start` and one `end` (BF-655), and `dropped` is unchanged.
4. `_endSentenceQueueWait` can never end the wait of a different entry: it holds that entry's own idempotent `done`.
5. `final` is computed when the `end` fires, not when the sentence is dispatched.
6. `voice.ts` gains no export.

## 15. Acceptance criteria

- [ ] M4: the focused check in §4 passes; `check_architecture_principles.py --check` passes; the 21 Python rows of §10 are killed (A1 added M4-12 to M4-19; A2 added M4-20 and M4-21).
- [ ] M4 A1: a cancelled store caller keeps the lock until its call has ended (the three index saves and the blob write, on the store's threads and after close, and through the real reaper's `stop()`); `write` resolves its path on a store thread; a store first built after the close point is born closed; the thread-exit test passes after `tests/test_ad1242_crew_verifier_trace.py` in one process.
- [ ] M4 A2: during a real `asyncio.Runner` teardown, a caller whose index save was interrupted keeps the lock until that save has ended, open or closed, and another task's cleanup write then survives a reopen and the real reaper (`test_loop_teardown_keeps_the_lock_until_the_interrupted_save_ends`); the cold size scan runs on a store thread (`test_every_blocking_call_runs_on_the_store_threads`).
- [ ] M4: with asyncio's default pool fully held, a write, lookup and read of the store complete (`test_store_io_does_not_wait_for_a_busy_default_pool`, the seam test: the default pool, then the route's store calls, then the store's thread, then the file).
- [ ] M4: shutdown closes the store after the reaper; a closed store still serves; accepted work is never cancelled.
- [ ] M5: `npx vitest run src/audio src/components/profile` and `npx tsc -b` pass; the 8 TypeScript rows are killed.
- [ ] M5: a reply queued behind a pipelined reply plays after that reply's last sentence and cuts none of it (P14); pipelining off is unchanged (P18).
- [ ] The live acceptance (BF-918 §16) runs once after both slices merge. **Its 20 or more replies should be typed in the chat, not spoken in conversation mode, until M7 lands** (decision 2). §16's measures are otherwise unchanged; step 1's `store_ms` is now M4's verification.
- [ ] All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live-vessel premise checks

None is needed to build either slice. M4's reach is judged from the live `store_ms` that BF-918 §16 step 1 already collects, and M5's reproduction is P14. Two optional read-only reads would size the register entries in §18 (PowerShell; `$D = "$env:LOCALAPPDATA\ProbOS\data"`; no SQLite file is opened):

```
(Get-Item "$D\attachments\.index.json").Length
(Get-ChildItem "$D\attachments" -File).Count
```

The first is the size each write's index save serialises. The second is the number of directory entries each `_find` scans. A1 needs no live check: the reaper's `stop()` (`shutdown.py:1621`) cancels a running sweep at every shutdown, which is the path A1 repairs, and review round 1's probes are its reproduction.

## 17. Not verified

- No pytest, vitest, `tsc`, precheck or architecture check was run (the brief asked for none). Every "fails on the base" claim in §4 comes from reading. The orchestrator's tests-first run is the execution check.
- The microtask depth of P14 to P20 is estimated (`_flush` is 40 turns). P16 and P17's fake timers (`toFake: ['setTimeout', 'clearTimeout']`) were not run against this file's global setup.
- R12's live reproduction was not observed; the reasoning in §1 and P14 stand in for it.
- From memory, not checked against the installed Starlette or anyio: `FileResponse` streams the file on anyio's worker threads, not on asyncio's default pool.
- Whether any runtime lifecycle test checks non-daemon threads without polling after the attachment reaper's first sweep has run (it would see a store thread); `test_issue1452` and `test_issue1419` are in M4's focused check.
- M7's finding is from reading; no conversation-mode run with pipelining was made.
- Possible phantom-precheck false positives: `_io_executor`, `_io_closed`, `_io_workers`, `io_closed`, `close_attachment_store`, `_close_attachment_store`, `_endSentenceQueueWait`, `_finalField`, `final`, and from A1 `_finish_cancelled`, `_locate_sync`, `_CLOSED_BEFORE_BUILD`, `_Gate`, `_turns`, `_close_the_stores_built_here` (all introduced here).
- A1 was drafted read-only and no test was run; §4's A1 tests-first claims come from reading candidate 1. `_turns()`'s 20 loop turns are an estimate of what a cancellation needs to reach `_run` and the lock. If a case needs more, raise the count for that case and say so.
- Whether `Path.exists` calls `Path.stat` depends on the Python version (3.12 does). The every-blocking test records `exists` and `stat` separately, so it does not depend on this.
- (A2) A1's teardown sentence here was false: while `asyncio.run` cancels every task, other cancelled coroutines still run their cleanup, and in review round 2 one saved the index over a closed store's running save. After A2 no task stands between a caller and its thread. The stdlib behaviour A2 relies on (`Runner.close()` cancels `all_tasks` and gathers them before `shutdown_default_executor`; `asyncio.to_thread` is `copy_context()` plus `run_in_executor(None, ...)`) was read in CPython 3.12's source, not in the venv's copy. A2 was drafted read-only and no test was run for it; the orchestrator's scratch run of the same closed branch passed the reviewer's probe in both cases and the two M4 test files. The new test's 60 loop turns are the reviewer's count, which on candidate 2 let the teardown's cancellations unwind.

## 18. For the register (found here, not fixed by this change)

- **R22 (P3, not a regression).** `_find` globs the whole attachment directory for each lookup (`filesystem_store.py:270`; over 1,126 files live), and `GET /api/chat/attachments` does it twice (`exists`, then `get_path`; `chat.py:1253-1255`), and the TTS route does it once, in its `get_path` (`avatars.py:315`) after `write` (`write` builds its path from the MIME and does not glob; corrected in A1). M4 moves the cost off the default pool, not off the request. Follow-up: resolve the path from the index's `mime`, falling back to the glob.
- **R23 (P3, not a regression).** Every write, unlink and conditional unlink rewrites the whole `.index.json` (962 entries live). The rewrite is now off the event loop (M4) but still happens on every spoken sentence. Follow-up: coalesce saves.
- **R24 (P3).** `FileResponse`'s streaming of the WAV runs outside the store, on anyio's worker threads (not verified, §17), which sync routes share. M4 covers the lookup only.
- **R25 (Low, M7's family).** The BF-300 PTT gate (`ProfileChatTab.tsx:563-590`) opens for each gap between two pipelined sentences, because it clears on every `end`. Follow-up with M7: keep it closed on `final: false`.
- **R26 (Low, no production reach).** `close()` from another thread is unsafe. `_run` has no await between its closed check and its submit, so on the one event loop `close()` cannot interleave, but a `close()` from another thread can (`RuntimeError: cannot schedule new futures after shutdown`, review round 1). Production calls `close()` only from `shutdown()`, on the loop, and every store caller is a coroutine on that loop. Supported lifecycle: one loop. Design if a cross-thread caller appears: catch that `RuntimeError` at submit and fall back to the closed branch's own submit (`run_in_executor(None, ...)`; never `asyncio.to_thread`, whose task the loop's teardown cancels: A2).
- **R27 (Low, tests only).** An alias import or a reload of `probos.routers.chat` has its own `_ATTACHMENT_STORE_CACHE`; the shutdown helper closes only the canonical module's (`sys.modules["probos.routers.chat"]`). Supported lifecycle: the canonical import. Design if needed: move the cache and its marker to the attachments layer (also R29).
- **R28 (Low, tests only).** About 150 test constructions of the store in 58 files never close it. Idle store threads accumulate per xdist worker (4, 8, 12 measured in review round 1) until garbage collection frees the store. A1 closes the stores of the two M4 test files. Design: a shared closing fixture, adopted file by file. Do not exclude store threads from the lifecycle detector.
- **R29 (Low).** When `probos.routers.chat` was never imported by shutdown, `_close_attachment_store` returns without a marker. A store first built later through `runtime.attachment_store` (`runtime.py:2240-2248`, which imports the module) is open and never closed. Reach: a runtime without the HTTP routers whose crew work first touches the store after the close point (headless runs, tests); its idle threads end at interpreter exit. Design: R27's move.
- **R30 (P2, pre-existing since AD-720, not a regression).** `write` writes the final path directly. A crash, or an error such as ENOSPC part-way through, leaves a partial file that every later write of that hash treats as present and acknowledges (`need_write` false); repeated TTS sentences produce repeated hashes. A reader that knows a hash before its write is acknowledged can also read a partial file. The parent wrote the same way (`e973acbe` `:229`). A1's drain removes only the cancelled-write variant. Reach: a disk-full or crash during a write; no supported reader learns a hash before its write is acknowledged (by reading). Design: write to a dot-prefixed temporary file in the root, then `os.replace` (the `{hash}.*` glob and the cold scan skip dotfiles). Schedule it as its own slice of #1626 after M5.
- **R31 (Low, A1's cost).** A cancelled store caller now ends when its in-flight call ends: at most one queued wait plus one call. An `asyncio.timeout` around a store call can overrun by that much, and `AttachmentReaper.stop()` returns after the interrupted call. A2 extends this to the event loop's teardown: `asyncio.run` returns only after an interrupted store call has ended, on either pool. None of these waits is bounded by time: a call that never returns holds its caller, and the teardown, indefinitely (review round 2); process exit already waited for such a thread, because `concurrent.futures` joins its worker threads at exit. A write cancelled after its blob write keeps the blob with no index entry (the index is a hint, AD-733-1), so the age and LRU sweeps miss it until a later write of that hash indexes it. An unlink cancelled after removing its blob keeps the entry until the next conditional unlink drops it (`freed` 0). Both partial states predate M4 for the blob calls (parent `:229`, `:306`, `:358-359`). Design, if live counts show untracked blobs: decision 9's option c.
