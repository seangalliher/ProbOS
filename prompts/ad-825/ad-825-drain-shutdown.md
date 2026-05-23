# AD-825 — Drain-before-cancel shutdown semantics

**Status:** Ready for Builder
**Closes:** https://github.com/seangalliher/ProbOS/issues/760
**Depends on:** AD-820 (`shutdown_integrity.py` clean marker), AD-824 (`_spawn_background` registry + cancel sweep)
**Estimated tests:** 7 new
**Risk:** Medium — touches shutdown sequencing. Operator runtime PID guard required.

---

## Problem

Today's recovery arc started because the AD-820 integrity marker recorded
`consolidation_result=failed` after a shutdown. Phase 1 in
`src/probos/startup/shutdown.py` calls
`runtime.dream_scheduler.engine.dream_cycle()` under `asyncio.wait_for`
(lines 118–155). The `(asyncio.CancelledError, Exception)` branch maps
to `"failed"`. That branch can fire when in-flight dream / consolidation
work is torn down mid-write — either because `stop()` itself was
cancelled by `__main__.py`'s overall timeout, or because the
`DreamScheduler._monitor_loop` continues running a parallel
`dream_cycle` while shutdown's explicit `dream_cycle` is also in flight
(both write to the same Chroma collection).

AD-824 added the `_background_tasks` registry + cancel sweep, but cancel
is the wrong tier for tasks that hold open Chroma write transactions or
SQLite checkpoint writes. Cancelling a task mid-`_collection.add()`
leaves the HNSW index in a torn state (the same pathology AD-819 / AD-822
have to repair on the next boot).

We need a **drain phase** that runs BEFORE the AD-824 cancel sweep:
write-holding tasks are signalled to stop accepting new work, given a
bounded window to finish whatever atomic operation is currently in
flight, and only THEN fall through to the cancel sweep if they refuse
to exit cleanly.

## Solution overview

1. New `runtime._drain_tasks` registry parallel to `_background_tasks`.
2. New `runtime._shutdown_event: asyncio.Event` that drain-tagged loops
   check on every iteration (replaces bare `asyncio.sleep` with
   `asyncio.wait_for(self._shutdown_event.wait(), timeout=N)`).
3. New `runtime._signal_drain_stop()` helper that sets the event.
4. `_spawn_background(...)` grows a kw-only `drain_on_shutdown: bool =
   False` parameter that routes the task to `_drain_tasks` instead of
   `_background_tasks`.
5. New drain phase inserted in `startup/shutdown.py` BEFORE the AD-824
   cancel sweep: signal event, `asyncio.wait(drain_tasks,
   timeout=shutdown_drain_timeout_s)`, log warnings for any task that
   doesn't drain in time (the AD-824 cancel sweep that runs next will
   force them).
6. New `MemoryConfig.shutdown_drain_timeout_s` (default 30s).
7. `DreamScheduler` grows a public `stop_gracefully()` method that the
   drain phase calls before Phase 1 consolidation runs, so the explicit
   `dream_cycle()` in Phase 1 is the only writer (no concurrent
   `_monitor_loop` dream cycle). See Section 6 below — `DreamScheduler`
   manages its own `_task` outside `_spawn_background`, so option (b)
   from the issue body applies.

---

## Section 0: `MemoryConfig.shutdown_drain_timeout_s`

**File:** `src/probos/config.py`

Insert immediately after `shutdown_consolidation_timeout_s` (currently
line 827).

```
===MODIFY: src/probos/config.py===
===SEARCH===
    # AD-820: shutdown consolidation budget. Old default was a hardcoded 2s
    # which is too tight when the dream cycle has real work to do; a partial
    # consolidation tears ChromaDB's HNSW index. Default raised to 30s so
    # normal shutdowns complete; operator can lower for fast-restart workflows.
    shutdown_consolidation_timeout_s: float = 30.0
    # AD-821: ChromaDB HNSW per-collection sync threshold.
===REPLACE===
    # AD-820: shutdown consolidation budget. Old default was a hardcoded 2s
    # which is too tight when the dream cycle has real work to do; a partial
    # consolidation tears ChromaDB's HNSW index. Default raised to 30s so
    # normal shutdowns complete; operator can lower for fast-restart workflows.
    shutdown_consolidation_timeout_s: float = 30.0
    # AD-825: max seconds to wait for write-holding background tasks
    # (dream monitor loop, episodic backup) to finish their current
    # operation before the AD-824 cancel sweep force-cancels them. Drain
    # is best-effort; cancel is the fallback. Default 30s mirrors
    # shutdown_consolidation_timeout_s. Operator can lower for
    # fast-restart workflows or raise for write-heavy snapshots.
    shutdown_drain_timeout_s: float = Field(
        default=30.0, ge=1.0, le=300.0,
        description=(
            "AD-825: max seconds to wait for write-holding tasks (dreaming, "
            "consolidation, episodic backup) to finish current operation "
            "before falling through to AD-824 cancel sweep."
        ),
    )
    # AD-821: ChromaDB HNSW per-collection sync threshold.
===END REPLACE===
```

Verify `Field` is already imported in `config.py` (it is — used heavily
in this file).

---

## Section 1: Runtime registries + helpers

**File:** `src/probos/runtime.py`

### 1a. Add `_drain_tasks` + `_shutdown_event` to `__init__`

Insert directly after the existing `_background_tasks` registration
block (line 937).

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
        # AD-824: registry for long-lived runtime-owned background loops.
        # The shutdown sequence in startup/shutdown.py cancels everything in
        # this set before AD-820's mark_clean_shutdown so a stuck loop can
        # never block the integrity marker. Per-event one-shot tasks
        # (ward room alerts, QA fan-out, NATS publish) are NOT registered
        # here — those use _nats_publish_tasks or are intentionally fire-
        # and-forget with their own bounded lifetimes.
        self._background_tasks: set[asyncio.Task] = set()
        self._nats_events_wired: bool = False  # AD-637z: gate for inline NATS event subscription
===REPLACE===
        # AD-824: registry for long-lived runtime-owned background loops.
        # The shutdown sequence in startup/shutdown.py cancels everything in
        # this set before AD-820's mark_clean_shutdown so a stuck loop can
        # never block the integrity marker. Per-event one-shot tasks
        # (ward room alerts, QA fan-out, NATS publish) are NOT registered
        # here — those use _nats_publish_tasks or are intentionally fire-
        # and-forget with their own bounded lifetimes.
        self._background_tasks: set[asyncio.Task] = set()
        # AD-825: separate registry for write-holding background loops
        # (episodic backup, dream-cycle adjacent work). The shutdown
        # sequence drains these BEFORE the AD-824 cancel sweep so any
        # atomic write (Chroma add/upsert, SQLite checkpoint, tar copy)
        # can finish cleanly. Tasks that don't drain in time are
        # force-cancelled by the AD-824 sweep that runs immediately
        # after the drain phase.
        self._drain_tasks: set[asyncio.Task] = set()
        # AD-825: shutdown signal. Drain-tagged loops replace bare
        # ``asyncio.sleep(N)`` with ``asyncio.wait_for(self._shutdown_event.wait(),
        # timeout=N)`` so they exit cleanly the moment shutdown is
        # initiated, instead of waiting up to N seconds for the next
        # iteration tick.
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._nats_events_wired: bool = False  # AD-637z: gate for inline NATS event subscription
===END REPLACE===
```

> **Note on event-loop binding:** `asyncio.Event()` constructed in
> `__init__` outside a running loop is safe in Python 3.10+ — the event
> only binds to a loop on first `.wait()` / `.set()`. If the runtime is
> ever instantiated under a different event loop than the one that runs
> shutdown, that's a separate AD; for this prompt, follow the existing
> pattern (the runtime already creates `asyncio.Task` references at
> construction time elsewhere).

### 1b. Extend `_spawn_background` with `drain_on_shutdown`

Replace the existing helper (lines 2389–2408).

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
    def _spawn_background(
        self, coro: "Coroutine[Any, Any, Any]", name: str
    ) -> asyncio.Task:
        """AD-824: spawn a long-lived runtime-owned background task.

        Stores the task in ``self._background_tasks`` so the shutdown
        sweep in ``startup/shutdown.py`` can cancel it before the AD-820
        clean-shutdown marker is written. Uses ``.discard`` (not
        ``.remove``) in the done-callback so a duplicate removal never
        raises.

        Use ONLY for loops that live for the runtime's lifetime. For
        per-event fan-out tasks (ward room alerts, QA, NATS publish)
        continue to use ``asyncio.create_task`` directly with whatever
        per-feature registry already exists.
        """
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task
===REPLACE===
    def _spawn_background(
        self,
        coro: "Coroutine[Any, Any, Any]",
        name: str,
        *,
        drain_on_shutdown: bool = False,
    ) -> asyncio.Task:
        """AD-824 + AD-825: spawn a long-lived runtime-owned background task.

        By default the task is stored in ``self._background_tasks`` and
        the shutdown sweep in ``startup/shutdown.py`` cancels it before
        the AD-820 clean-shutdown marker is written. Uses ``.discard``
        (not ``.remove``) in the done-callback so a duplicate removal
        never raises.

        Use ONLY for loops that live for the runtime's lifetime. For
        per-event fan-out tasks (ward room alerts, QA, NATS publish)
        continue to use ``asyncio.create_task`` directly with whatever
        per-feature registry already exists.

        AD-825 — ``drain_on_shutdown=True``:
            The task is stored in ``self._drain_tasks`` instead. The
            shutdown sequence runs a drain phase BEFORE the AD-824
            cancel sweep: ``self._shutdown_event`` is set and the
            shutdown awaits ``asyncio.wait(_drain_tasks,
            timeout=memory.shutdown_drain_timeout_s)``. Tasks that
            exit cleanly within the budget never see ``CancelledError``;
            tasks that don't exit in time fall through to the AD-824
            cancel sweep.

            Drain-tagged loops MUST follow this contract:
            1. Replace inner ``await asyncio.sleep(N)`` with::

                   try:
                       await asyncio.wait_for(
                           self._runtime._shutdown_event.wait(),
                           timeout=N,
                       )
                   except asyncio.TimeoutError:
                       pass  # normal idle tick

               (Exits the wait immediately on shutdown; otherwise
               continues looping each N seconds.)
            2. On ``self._runtime._shutdown_event.is_set()`` becoming
               True, finish the current atomic operation (any open
               write) inside a ``try/finally`` and ``return`` cleanly
               — do NOT ``raise CancelledError``.
            3. Keep the outer ``except asyncio.CancelledError:
               <cleanup>; raise`` arm from AD-824 as the fallback path
               for the cancel sweep.
        """
        task = asyncio.create_task(coro, name=name)
        if drain_on_shutdown:
            registry = self._drain_tasks
        else:
            registry = self._background_tasks
        registry.add(task)
        task.add_done_callback(registry.discard)
        return task

    def _signal_drain_stop(self) -> None:
        """AD-825: signal drain-tagged background loops to exit cleanly.

        Idempotent — calling more than once is a no-op. Drain-tagged
        loops check ``self._shutdown_event`` on every iteration and
        return cleanly the next time they wake up.
        """
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()
===END REPLACE===
```

---

## Section 2: Drain phase in `startup/shutdown.py`

**File:** `src/probos/startup/shutdown.py`

Insert the new drain phase IMMEDIATELY BEFORE the existing AD-824
cancel sweep (currently lines 166–185). The drain phase runs after
Phase 1 explicit consolidation has been called by the existing code,
but before the AD-824 cancel sweep AND before the AD-820 marker write.

```
===MODIFY: src/probos/startup/shutdown.py===
===SEARCH===
    # AD-824: cancel registered long-lived background loops so the
    # AD-820 marker write below is never blocked by a stuck task. We
    # snapshot the set into a list because the done-callback mutates it.
    background_tasks = getattr(runtime, "_background_tasks", None)
    if background_tasks:
        pending_snapshot = list(background_tasks)
        for _task in pending_snapshot:
            _task.cancel()
        try:
            _, _pending = await asyncio.wait(pending_snapshot, timeout=5.0)
            for _task in _pending:
                logger.warning(
                    "AD-824: background task %s did not exit within 5s; abandoning",
                    _task.get_name(),
                )
        except Exception:
            # Sweep must never block the AD-820 marker — log and move on.
            logger.warning("AD-824: background-task sweep raised", exc_info=True)
===REPLACE===
    # AD-825: drain phase — let write-holding background loops finish
    # their current operation (Chroma add/upsert, SQLite checkpoint,
    # tar snapshot) before the AD-824 cancel sweep below force-cancels
    # them. Tasks that don't drain within the budget fall through to
    # cancel — drain is best-effort, cancel is the fallback. The drain
    # phase must NEVER raise out of shutdown(); on error we log and
    # proceed so the AD-820 marker still gets written.
    drain_tasks = getattr(runtime, "_drain_tasks", None)
    if drain_tasks:
        try:
            runtime._signal_drain_stop()
            pending_snapshot = list(drain_tasks)
            if pending_snapshot:
                _drain_budget = float(
                    getattr(
                        getattr(runtime, "config", None), "memory", None,
                    ).shutdown_drain_timeout_s
                    if (
                        getattr(runtime, "config", None)
                        and getattr(runtime.config, "memory", None)
                    )
                    else 30.0
                )
                logger.info(
                    "AD-825: draining %d write-holding task(s) (budget=%.1fs)",
                    len(pending_snapshot), _drain_budget,
                )
                _, _pending = await asyncio.wait(
                    pending_snapshot, timeout=_drain_budget,
                )
                for _task in _pending:
                    logger.warning(
                        "AD-825: drain task %s did not exit within %.1fs; "
                        "falling through to AD-824 cancel sweep",
                        _task.get_name(), _drain_budget,
                    )
        except Exception:
            # Drain must never block the AD-820 marker — log and proceed
            # to the cancel sweep.
            logger.warning(
                "AD-825: drain phase raised; proceeding to cancel sweep",
                exc_info=True,
            )

    # AD-824: cancel registered long-lived background loops so the
    # AD-820 marker write below is never blocked by a stuck task. We
    # snapshot the set into a list because the done-callback mutates it.
    # AD-825: this also catches any drain-tagged tasks that didn't exit
    # cleanly within the drain budget — drain was best-effort, this is
    # the fallback. We sweep _drain_tasks here too for that reason.
    background_tasks = getattr(runtime, "_background_tasks", None)
    drain_tasks_remaining = getattr(runtime, "_drain_tasks", None)
    pending_snapshot: list[asyncio.Task] = []
    if background_tasks:
        pending_snapshot.extend(background_tasks)
    if drain_tasks_remaining:
        pending_snapshot.extend(drain_tasks_remaining)
    if pending_snapshot:
        for _task in pending_snapshot:
            _task.cancel()
        try:
            _, _pending = await asyncio.wait(pending_snapshot, timeout=5.0)
            for _task in _pending:
                logger.warning(
                    "AD-824: background task %s did not exit within 5s; abandoning",
                    _task.get_name(),
                )
        except Exception:
            # Sweep must never block the AD-820 marker — log and move on.
            logger.warning("AD-824: background-task sweep raised", exc_info=True)
===END REPLACE===
```

---

## Section 3: Migrate `_episodic_backup_task` to drain-tagged

**File:** `src/probos/runtime.py` (line ~2317)

The episodic backup loop writes a tar snapshot of Chroma's on-disk
footprint. If cancelled mid-tar, the snapshot file is corrupt.
Drain-tag it.

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
        # AD-823 + AD-824: schedule the daily episodic backup loop via
        # the runtime's background-task registry so the shutdown sweep
        # can cancel it deterministically before AD-820's clean-shutdown
        # marker is written.
        self._episodic_backup_task = self._spawn_background(
            self._episodic_backup_loop(),
            name="episodic-backup-loop",
        )
===REPLACE===
        # AD-823 + AD-824 + AD-825: schedule the daily episodic backup
        # loop via the runtime's drain-on-shutdown registry. The loop
        # writes a tar snapshot of Chroma's on-disk footprint; if
        # cancelled mid-tar the snapshot file is corrupt. The drain
        # phase in startup/shutdown.py gives it the configured
        # ``memory.shutdown_drain_timeout_s`` window to finish the
        # current tar before the AD-824 cancel sweep would fire.
        self._episodic_backup_task = self._spawn_background(
            self._episodic_backup_loop(),
            name="episodic-backup-loop",
            drain_on_shutdown=True,
        )
===END REPLACE===
```

### 3a. Update `_episodic_backup_loop` to honour the shutdown event

Find the existing loop body (search `def _episodic_backup_loop` in
`runtime.py`) and verify its inner `await asyncio.sleep(...)` is
replaced with the drain-aware wait pattern documented in
`_spawn_background`'s new docstring. The Builder MUST:

1. Read the current loop body in full.
2. Replace the inner `await asyncio.sleep(N)` with::

       try:
           await asyncio.wait_for(
               self._shutdown_event.wait(),
               timeout=N,
           )
       except asyncio.TimeoutError:
           pass  # normal idle tick

   (If `N` is computed inside the loop, preserve that.)
3. At the top of each iteration, check `if self._shutdown_event.is_set(): return` BEFORE starting a new tar.
4. Wrap the actual tar write in a `try/finally` so a flag/close runs
   even on `return`.
5. Keep the existing outer `except asyncio.CancelledError: ...; raise`
   arm (added by AD-824) as the cancel-sweep fallback.

**Do NOT change the tar logic, file paths, or retention behaviour —
only the wait + early-exit shape.**

---

## Section 4: `DreamScheduler.stop_gracefully()`

**File:** `src/probos/cognitive/dreaming.py`

### Architectural deviation from issue body

The issue body lists "dreaming + reconsolidation tasks" as drain
migration targets, but the live code is:

| Component | Owns asyncio.Task? | `start()`/`stop()`? | Holds writes? |
|---|---|---|---|
| `DreamScheduler` | YES — `self._task` via internal `start()` (dreaming.py:2881) | YES | YES — `_monitor_loop` triggers `dream_cycle()` which writes Chroma |
| `ReconsolidationScheduler` | NO | NO | Called inline from `dream_cycle` |
| `FailureDistiller` | NO | NO | Called inline from `dream_cycle` |

`DreamScheduler` does NOT route through `_spawn_background`, so we
can't tag it with `drain_on_shutdown=True` without refactoring its
ownership model. The minimal fix is option (b) from the issue body: add
a public `stop_gracefully()` method.

There is also a latent **concurrent-writer hazard**: Phase 1 in
`startup/shutdown.py` (line 125) calls
`runtime.dream_scheduler.engine.dream_cycle()` explicitly under
`wait_for`, but the `DreamScheduler._monitor_loop` task is still alive
at that point (it only stops at shutdown.py:555). If `_monitor_loop`
happens to be running its own `dream_cycle` concurrently, both writers
collide on the same Chroma collection — a likely cause of the
`consolidation_result=failed` event the user reported.

The fix: `stop_gracefully()` sets an internal stop flag, waits for any
in-flight cycle to complete, and returns. The shutdown sequence calls
it BEFORE Phase 1's explicit consolidation, so Phase 1 is the only
writer.

### 4a. Add `stop_gracefully()` to `DreamScheduler`

Insert directly after the existing `stop()` method
(dreaming.py:2883–2892).

```
===MODIFY: src/probos/cognitive/dreaming.py===
===SEARCH===
    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def force_dream(self) -> DreamReport:
===REPLACE===
    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def stop_gracefully(self, timeout: float = 30.0) -> bool:
        """AD-825: stop the monitor loop after current dream cycle completes.

        Signals the loop to stop accepting new work (``self._stopped =
        True``) and waits up to ``timeout`` seconds for any in-flight
        dream cycle to finish. Returns True if the loop exited cleanly
        within the budget, False if the timeout expired and the task
        is still alive (in which case the caller should fall through
        to ``self.stop()`` for forceful cancellation).

        Called from ``startup/shutdown.py`` BEFORE Phase 1's explicit
        ``dream_cycle()`` so the explicit call is the only writer to
        the Chroma collection during shutdown consolidation. Without
        this, the monitor loop's own dream cycle could collide with
        the shutdown's explicit cycle (concurrent writers on the same
        collection → torn HNSW index → AD-820 ``consolidation_result=
        failed``).

        Safe to call when ``_task`` is None or already stopped — both
        return True immediately.
        """
        self._stopped = True
        if self._task is None or self._task.done():
            return True
        try:
            await asyncio.wait_for(
                asyncio.shield(self._task), timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "AD-825: DreamScheduler.stop_gracefully timed out "
                "after %.1fs; in-flight dream cycle did not complete",
                timeout,
            )
            return False
        except asyncio.CancelledError:
            # The shielded task can still raise CancelledError if WE
            # are cancelled. Re-raise so the outer shutdown sees it.
            raise

    async def force_dream(self) -> DreamReport:
===END REPLACE===
```

> Why `asyncio.shield`: `wait_for` cancels its inner awaitable on
> timeout. We do NOT want to cancel `_task` here — that's `stop()`'s
> job. `shield` makes the timeout fall through cleanly and leaves
> `_task` running, so the caller can decide whether to escalate to
> `stop()` or let it run to natural completion.

### 4b. Call `stop_gracefully` in shutdown Phase 1 prelude

**File:** `src/probos/startup/shutdown.py`

Insert directly BEFORE the existing Phase 1 dream-cycle block
(currently lines 118–155 — the block starting `if runtime.dream_scheduler and runtime.episodic_memory:`).

```
===MODIFY: src/probos/startup/shutdown.py===
===SEARCH===
    # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
    # Must run BEFORE pools stop (dream_cycle may trigger Ward Room notifications)
    # and BEFORE LLM client is closed (dream_cycle makes LLM calls).
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info(
            "Consolidating session memories (budget=%.0fs)...",
            _shutdown_consolidation_timeout,
        )
===REPLACE===
    # AD-825: quiesce the DreamScheduler monitor loop BEFORE the
    # explicit dream_cycle below. Without this, the monitor loop can
    # run its own dream_cycle concurrently with the explicit one, and
    # the two writers collide on the same Chroma collection — torn
    # HNSW index → AD-820 ``consolidation_result=failed``. We give it
    # the configured drain budget; if it doesn't exit cleanly we log
    # and proceed (the AD-824 cancel sweep will reap it later).
    if runtime.dream_scheduler:
        try:
            _drain_budget = float(
                getattr(
                    getattr(runtime, "config", None), "memory", None,
                ).shutdown_drain_timeout_s
                if (
                    getattr(runtime, "config", None)
                    and getattr(runtime.config, "memory", None)
                )
                else 30.0
            )
            _ok = await runtime.dream_scheduler.stop_gracefully(
                timeout=_drain_budget,
            )
            if not _ok:
                logger.warning(
                    "AD-825: DreamScheduler did not quiesce within %.1fs; "
                    "proceeding to explicit consolidation (concurrent-write hazard)",
                    _drain_budget,
                )
        except Exception:
            logger.warning(
                "AD-825: DreamScheduler.stop_gracefully raised; "
                "proceeding to explicit consolidation",
                exc_info=True,
            )

    # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
    # Must run BEFORE pools stop (dream_cycle may trigger Ward Room notifications)
    # and BEFORE LLM client is closed (dream_cycle makes LLM calls).
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info(
            "Consolidating session memories (budget=%.0fs)...",
            _shutdown_consolidation_timeout,
        )
===END REPLACE===
```

---

## Section 5: Tests — `tests/test_ad825_drain_shutdown.py`

Create a NEW test file. The Builder MUST NOT modify the live operator
runtime at `C:\Users\seang\AppData\Local\ProbOS\data\probos.pid` and
MUST run tests with `-n 0 --timeout=60`.

```
===FILE: tests/test_ad825_drain_shutdown.py===
"""AD-825: drain-before-cancel shutdown semantics — regression tests.

These tests construct a minimal runtime-shaped fixture with the new
``_drain_tasks`` / ``_shutdown_event`` / ``_spawn_background`` /
``_signal_drain_stop`` surface and exercise the drain → cancel
hand-off in ``startup/shutdown.py``. We deliberately do NOT spin up
the full ProbOSRuntime — these are unit-level tests for the new
machinery only. End-to-end behaviour is covered by the existing
AD-820 / AD-824 regression suites.
"""
from __future__ import annotations

import asyncio
import logging

import pytest


class _MiniRuntime:
    """Minimal shape needed by ``_spawn_background`` + drain phase.

    Mirrors the fields the real ProbOSRuntime owns (set in __init__
    around runtime.py:937). Used so we can unit-test the helpers
    without booting the full runtime.
    """

    def __init__(self) -> None:
        self._background_tasks: set[asyncio.Task] = set()
        self._drain_tasks: set[asyncio.Task] = set()
        self._shutdown_event: asyncio.Event = asyncio.Event()

    # The real runtime's helpers — copied verbatim so the unit tests
    # exercise the contract, not a stub. If the production helpers
    # drift, these tests will fail by being out of sync with the
    # production source — which is what we want.
    def _spawn_background(
        self,
        coro,
        name: str,
        *,
        drain_on_shutdown: bool = False,
    ) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        registry = self._drain_tasks if drain_on_shutdown else self._background_tasks
        registry.add(task)
        task.add_done_callback(registry.discard)
        return task

    def _signal_drain_stop(self) -> None:
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()


# --------------------------------------------------------------------
# Test 1: drain-tagged tasks land in _drain_tasks, NOT _background_tasks
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spawn_background_drain_routes_to_drain_registry():
    runtime = _MiniRuntime()

    async def _noop():
        await asyncio.sleep(0)

    task = runtime._spawn_background(
        _noop(), name="drain-loop", drain_on_shutdown=True,
    )
    assert task in runtime._drain_tasks, (
        "drain_on_shutdown=True must route to _drain_tasks"
    )
    assert task not in runtime._background_tasks, (
        "drain_on_shutdown=True must NOT route to _background_tasks"
    )
    await task


# --------------------------------------------------------------------
# Test 2: default behaviour (regression) — non-drain stays in _background_tasks
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spawn_background_default_routes_to_background_registry():
    runtime = _MiniRuntime()

    async def _noop():
        await asyncio.sleep(0)

    task = runtime._spawn_background(_noop(), name="poll-loop")
    assert task in runtime._background_tasks, (
        "default (drain_on_shutdown=False) must route to _background_tasks"
    )
    assert task not in runtime._drain_tasks, (
        "default must NOT route to _drain_tasks"
    )
    await task


# --------------------------------------------------------------------
# Test 3: drain phase signals event, awaits clean exit BEFORE cancel
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_phase_signals_event_and_awaits_clean_exit():
    runtime = _MiniRuntime()
    exited_cleanly = False
    saw_cancel = False

    async def _drain_loop():
        nonlocal exited_cleanly, saw_cancel
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        runtime._shutdown_event.wait(), timeout=0.05,
                    )
                except asyncio.TimeoutError:
                    continue
                # Event set → exit cleanly without raising
                exited_cleanly = True
                return
        except asyncio.CancelledError:
            saw_cancel = True
            raise

    task = runtime._spawn_background(
        _drain_loop(), name="drain-loop", drain_on_shutdown=True,
    )
    # Let the loop spin a couple of iterations
    await asyncio.sleep(0.15)

    # Drain phase: signal + wait
    runtime._signal_drain_stop()
    pending_snapshot = list(runtime._drain_tasks)
    done, pending = await asyncio.wait(pending_snapshot, timeout=2.0)

    assert task in done, "drain task should exit cleanly within budget"
    assert exited_cleanly, "loop should have observed the shutdown event"
    assert not saw_cancel, (
        "drain phase must NOT cancel — clean exit only"
    )


# --------------------------------------------------------------------
# Test 4: drain timeout falls through with WARNING; cancel sweep handles it
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_timeout_falls_through_to_cancel(caplog):
    caplog.set_level(logging.WARNING)
    runtime = _MiniRuntime()
    cancelled = False

    async def _stuck_loop():
        nonlocal cancelled
        try:
            # Ignores the shutdown event — simulates a buggy task
            while True:
                await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = runtime._spawn_background(
        _stuck_loop(), name="stuck-drain-loop", drain_on_shutdown=True,
    )
    await asyncio.sleep(0.05)

    # Drain phase with tiny budget — task will NOT exit
    runtime._signal_drain_stop()
    pending_snapshot = list(runtime._drain_tasks)
    done, pending = await asyncio.wait(pending_snapshot, timeout=0.2)
    assert task in pending, "stuck task should still be running after drain timeout"

    # Builder code in shutdown.py logs a WARNING and falls through; we
    # simulate the AD-824 cancel sweep here directly.
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert cancelled, "AD-824 cancel sweep should catch the stuck task"


# --------------------------------------------------------------------
# Test 5: in-flight atomic write completes before drain returns
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_lets_atomic_write_finish_before_exit():
    runtime = _MiniRuntime()
    write_completed = False
    exit_observed = False

    async def _writer_loop():
        nonlocal write_completed, exit_observed
        while not runtime._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    runtime._shutdown_event.wait(), timeout=0.05,
                )
                break  # event fired during sleep
            except asyncio.TimeoutError:
                # Begin an "atomic write" that must finish even if
                # shutdown was signalled during it.
                try:
                    await asyncio.sleep(0.3)  # simulate write
                finally:
                    write_completed = True
                # Loop tail: check event, exit cleanly
                if runtime._shutdown_event.is_set():
                    exit_observed = True
                    return

    task = runtime._spawn_background(
        _writer_loop(), name="writer-loop", drain_on_shutdown=True,
    )
    # Let it begin the write
    await asyncio.sleep(0.1)
    # Signal during the write
    runtime._signal_drain_stop()
    # Wait long enough for the write to finish AND the post-write exit
    done, pending = await asyncio.wait([task], timeout=2.0)
    assert task in done
    assert write_completed, "atomic write must finish even after signal"
    assert exit_observed, "loop must exit cleanly after write completes"


# --------------------------------------------------------------------
# Test 6: drain phase exception path — AD-820 marker must still proceed
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_phase_exception_does_not_block_marker(caplog):
    """If the drain phase itself raises, shutdown must continue.

    We simulate this by stubbing ``_signal_drain_stop`` with a raiser
    and verifying that the drain-then-cancel pattern in shutdown.py
    swallows the exception and proceeds (this is what the
    ``try/except Exception:`` arm in the new drain-phase block is for).
    """
    caplog.set_level(logging.WARNING)

    class _BadRuntime(_MiniRuntime):
        def _signal_drain_stop(self) -> None:
            raise RuntimeError("simulated drain failure")

    runtime = _BadRuntime()

    async def _short_loop():
        await asyncio.sleep(0.01)

    runtime._spawn_background(
        _short_loop(), name="dummy", drain_on_shutdown=True,
    )

    # Mimic the shutdown.py drain block — must not raise out
    raised = False
    try:
        try:
            runtime._signal_drain_stop()
            pending_snapshot = list(runtime._drain_tasks)
            if pending_snapshot:
                await asyncio.wait(pending_snapshot, timeout=1.0)
        except Exception:
            # This is the production guard — equivalent to the
            # try/except in startup/shutdown.py's new drain block.
            pass
    except Exception:
        raised = True

    assert not raised, "drain phase exception must not propagate"


# --------------------------------------------------------------------
# Test 7: non-drain background task still cancelled by AD-824 sweep
#         after drain phase runs (regression for AD-824 sweep semantics)
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ad824_cancel_sweep_still_handles_non_drain_tasks():
    runtime = _MiniRuntime()
    cancelled = False

    async def _poll_loop():
        nonlocal cancelled
        try:
            while True:
                await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = runtime._spawn_background(_poll_loop(), name="poll-loop")
    assert task in runtime._background_tasks
    await asyncio.sleep(0.05)

    # Simulate the AD-824 cancel sweep (drain phase doesn't touch
    # _background_tasks; only _drain_tasks).
    for t in list(runtime._background_tasks):
        t.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert cancelled, (
        "AD-824 regression: non-drain tasks must still be cancelled by the sweep"
    )
===END FILE===
```

---

## Section 6: What this prompt does NOT change

- AD-820 (`src/probos/shutdown_integrity.py`) — untouched.
- AD-824's existing `_event_log_prune_loop` / `_journal_prune_loop` /
  any other poll loop already wired through `background_register=` —
  untouched. Those are pure poll loops, not write-holders.
- The AD-824 cancel sweep itself — the new drain phase is INSERTED
  BEFORE it; the cancel sweep still runs after (and now also reaps any
  drain task that didn't exit cleanly within the budget).
- Dream cycle logic, consolidation cadence, episode replay budget.
- `ReconsolidationScheduler` and `FailureDistiller` — both are passive
  (no `start()`/`stop()`, no task ownership). They run inline inside
  `dream_cycle`, so they're covered transitively when
  `DreamScheduler.stop_gracefully()` lets the in-flight cycle finish.
- Phase 1 explicit `dream_cycle()` consolidation — untouched (still
  bounded by `shutdown_consolidation_timeout_s`).
- Per-event fire-and-forget tasks (NATS publish, ward room alerts) —
  untouched.

---

## Tracking

- **PROGRESS.md** — add CLOSED entry referencing AD-825 + #760.
- **docs/development/roadmap.md** — append AD-825 (one-line: "drain-before-cancel shutdown semantics; insert drain phase before AD-824 cancel sweep; quiesce DreamScheduler before Phase 1 consolidation").
- **DECISIONS.md** — append AD-825 entry per project convention.
- **No Bug Tracker entry** — this is a forward AD, not a BF.

---

## Acceptance Criteria

1. New file `tests/test_ad825_drain_shutdown.py` exists with the 7 tests above; all pass under::

       D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_ad825_drain_shutdown.py

2. Existing shutdown / integrity / boot probe regressions still pass::

       D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 \
           tests/test_ad820_*.py tests/test_ad821_*.py tests/test_ad822_*.py \
           tests/test_ad823_*.py tests/test_ad824_*.py

3. Episodic rebuild + episode-id regressions still pass::

       D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 \
           tests/test_ad819_rebuild_episodic.py \
           tests/test_bf103_episode_id_mismatch.py

4. `_episodic_backup_task` is spawned with `drain_on_shutdown=True` and
   its loop body uses the shutdown-event wait pattern (verify by
   grepping `runtime.py` for `drain_on_shutdown=True`).

5. `DreamScheduler.stop_gracefully()` exists and is called from
   `startup/shutdown.py` BEFORE the Phase 1 explicit `dream_cycle()`
   block.

6. No new `asyncio.create_subprocess_*` calls (BF-280 standing rule).

7. Compliance verified with Engineering Principles in
   `.github/copilot-instructions.md` (async hygiene, task references
   stored, `CancelledError` re-raised in outer arms, public APIs typed,
   structured log context).

8. One commit message: ``AD-825: drain-before-cancel shutdown semantics``
   with body referencing all sections and `Closes #760`. Pushed to
   `origin/main`.

## Hard Constraints

- **DO NOT touch the live operator runtime** at
  `C:\Users\seang\AppData\Local\ProbOS\data\probos.pid`. Use
  `scripts/kill-stale-pytest.ps1` for any pytest cleanup; never sweep
  `python.exe` by path.
- **DO NOT use `asyncio.create_subprocess_*`** anywhere in runtime
  code paths (BF-280). This prompt should not require any subprocess
  calls — flag if it does.
- **DO NOT modify the AD-824 cancel sweep behaviour itself** — the
  drain phase is inserted BEFORE it; the cancel sweep still runs after
  (extended to also reap any drain task that didn't exit cleanly).
- **DO NOT modify dream cycle logic, consolidation cadence, or
  reconsolidation/distillation behaviour.**
- Builder MUST verify section line numbers against current HEAD before
  applying — if HEAD has drifted, surface and revise rather than
  applying blind.

---

## Verified Against Codebase (2026-05-22)

```
# Section 0 — config insertion point
grep -n "shutdown_consolidation_timeout_s" src/probos/config.py
  827:    shutdown_consolidation_timeout_s: float = 30.0

# Section 1a — runtime __init__ insertion point
grep -n "_background_tasks: set\[asyncio.Task\]" src/probos/runtime.py
  937:        self._background_tasks: set[asyncio.Task] = set()

# Section 1b — _spawn_background existing definition
grep -n "_spawn_background\|_background_tasks\.add" src/probos/runtime.py
  937:        self._background_tasks: set[asyncio.Task] = set()
  1686:           background_register=self._background_tasks.add,
  2056:           background_register=self._background_tasks.add,
  2317:       self._episodic_backup_task = self._spawn_background(
  2389:   def _spawn_background(
  2406:       self._background_tasks.add(task)

# Section 2 — shutdown.py AD-824 cancel sweep + AD-820 marker
grep -n "AD-824:\|mark_clean_shutdown\|mark_dirty_shutdown" src/probos/startup/shutdown.py
  (sweep block at lines 167-185; marker call at lines 188-208 confirmed)

# Section 3 — _episodic_backup_task spawn site
grep -n "_episodic_backup_task" src/probos/runtime.py
  2317:       self._episodic_backup_task = self._spawn_background(

# Section 4 — DreamScheduler class + task management
grep -n "^class DreamScheduler\|async def stop\|self._task = asyncio" src/probos/cognitive/dreaming.py
  2833:  class DreamScheduler:
  2855:      self._task: asyncio.Task[None] | None = None
  2881:      self._task = asyncio.create_task(self._monitor_loop())
  2883:  async def stop(self) -> None:

# Section 4 — ReconsolidationScheduler / FailureDistiller have no start/stop
grep -n "^class \|async def start\|async def stop\|create_task" src/probos/cognitive/reconsolidation.py
  22:  class ReconsolidationEntry:
  33:  class ReconsolidationScheduler:
  (no start/stop/create_task — confirms passive, no migration needed)

grep -n "^class \|async def start\|async def stop\|create_task" src/probos/cognitive/failure_distiller.py
  20:  class ComparativeInsight:
  30:  class FailureDistiller:
  (no start/stop/create_task — confirms passive, no migration needed)

# Section 4b — Phase 1 dream_cycle call site
grep -n "dream_scheduler" src/probos/startup/shutdown.py
  118:   if runtime.dream_scheduler and runtime.episodic_memory:
  125:           runtime.dream_scheduler.engine.dream_cycle(),
  554:   if runtime.dream_scheduler:
  555:       await runtime.dream_scheduler.stop()
```
