# AD-824 — Shutdown hygiene: centralize background-task cancellation

**Status:** Ready for Builder
**Dependencies:** AD-820 (clean-shutdown marker, commit `bc1e0e00`), AD-823 (episodic backup loop, commit `6d8a9555`)
**Closes:** GitHub issue #759
**Estimated tests:** 5+ new in `tests/test_ad824_shutdown_hygiene.py`
**Standing rules:**

- Live operator runtime PID is at `C:\Users\seang\AppData\Local\ProbOS\data\probos.pid`. Do NOT touch the running process. Do NOT broad-kill python by path.
- ProbOS runs on `WindowsSelectorEventLoop`. Do NOT use `asyncio.create_subprocess_*`.
- Engineering Principles in `.github/copilot-instructions.md` apply — async hygiene section especially: every `create_task` ref must be stored; `CancelledError` must be caught and re-raised; never use `asyncio.ensure_future()`.

---

## 1. Problem

`ProbOSRuntime` and the `startup/` package spawn long-lived background loops via `asyncio.create_task`, but the references are stored inconsistently:

| Loop | Spawn site | Ref stored? | `CancelledError` handled? |
|------|-----------|-------------|---------------------------|
| `_event_log_prune_loop` | `src/probos/startup/infrastructure.py:49` | **No** — local var `event_prune_task`, lost on return | No |
| `_journal_prune_loop` (via `journal_prune_loop_fn`) | `src/probos/startup/communication.py:313` | **No** — fire-and-forget | No |
| `_episodic_backup_loop` (AD-823) | `src/probos/runtime.py:2306` | Yes — `self._episodic_backup_task` | No |
| `_flush_task` (dream periodic flush) | `src/probos/startup/finalize.py:3763` | Yes — `runtime._flush_task` | Loop body owned by `dream_adapter`; cancellation path already in `startup/shutdown.py:88-92` |
| `_mcp_app_external_discovery_task` | `src/probos/startup/finalize.py:1225` | Yes — `runtime._mcp_app_external_discovery_task` | No (one-shot, but assigned via `create_task`) |

Two of the three prune-class loops are pure fire-and-forget: the GC could collect their task wrapper at any time, swallowing exceptions silently. None of the three loops has an `except asyncio.CancelledError` arm, so cancellation either propagates as a generic `Exception` (`_episodic_backup_loop`, `_event_log_prune_loop`, `_journal_prune_loop` all have `except Exception` inside an outer `while True` — they would actually swallow `CancelledError` if it surfaced inside the inner try, which would prevent shutdown sweep from working). The shutdown sequence in `startup/shutdown.py` relies on event-loop teardown to clean these up. That is fragile: if any task ignores cancellation, AD-820's clean-shutdown marker writes successfully (because nothing actually blocks it today) but on the next boot AD-822 has degraded signal value because we never confirmed the loops actually exited.

Symptom of doing this right: a stuck background loop never blocks the AD-820 marker, the operator sees a clear `WARNING Background task <name> did not exit within 5s; abandoning` log, and `data/shutdown_status.json` stays trustworthy.

---

## 2. Solution overview

1. Add a task registry + helper on `ProbOSRuntime`:
   - `self._background_tasks: set[asyncio.Task] = set()` in `__init__`.
   - `def _spawn_background(self, coro, name: str) -> asyncio.Task` that calls `asyncio.create_task(coro, name=name)`, adds to the set, and registers a done-callback `self._background_tasks.discard` (using `.discard` so a doubled removal never raises).
2. Migrate the three currently-unprotected long-lived loops to the helper.
3. Add `except asyncio.CancelledError: <cleanup>; raise` to each migrated loop's body.
4. Add an explicit cancellation sweep to `startup/shutdown.py` IMMEDIATELY before `mark_clean_shutdown(...)` so a stuck task cannot prevent the integrity marker from being written.

---

## 3. Implementation

### Section 3.1 — Add registry + helper on `ProbOSRuntime`

**File:** `src/probos/runtime.py`

**Insertion point A — declaration in `__init__`:** add immediately after the existing `_nats_publish_tasks` initializer at line 928. Use `_nats_publish_tasks` as the indentation reference.

```
===SEARCH===
        self._nats_publish_tasks: set[asyncio.Task] = set()  # AD-637d: prevents GC of publish tasks
===REPLACE===
        self._nats_publish_tasks: set[asyncio.Task] = set()  # AD-637d: prevents GC of publish tasks

        # AD-824: registry for long-lived runtime-owned background loops.
        # The shutdown sequence in startup/shutdown.py cancels everything in
        # this set before AD-820's mark_clean_shutdown so a stuck loop can
        # never block the integrity marker. Per-event one-shot tasks
        # (ward room alerts, QA fan-out, NATS publish) are NOT registered
        # here — those use _nats_publish_tasks or are intentionally fire-
        # and-forget with their own bounded lifetimes.
        self._background_tasks: set[asyncio.Task] = set()
===END REPLACE===
```

**Insertion point B — helper method.** Place it immediately before `_event_log_prune_loop` at line 2377 (so the helper sits with the loops it serves).

```
===SEARCH===
    # --- BF-071: Retention prune loops ---

    async def _event_log_prune_loop(self) -> None:
===REPLACE===
    # --- BF-071: Retention prune loops ---

    def _spawn_background(
        self, coro: Coroutine[Any, Any, Any], name: str
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

    async def _event_log_prune_loop(self) -> None:
===END REPLACE===
```

Verify the `Coroutine` and `Any` imports exist at the top of `runtime.py`. If `Coroutine` is missing, add it to the existing `typing` import.

### Section 3.2 — Add `CancelledError` arm to the three loops

**File:** `src/probos/runtime.py`

#### `_event_log_prune_loop` (lines 2377-2388)

```
===SEARCH===
    async def _event_log_prune_loop(self) -> None:
        """Periodic event log retention cleanup."""
        cfg = self.config.event_log
        while True:
            await asyncio.sleep(cfg.prune_interval_seconds)
            try:
                await self.event_log.prune(
                    retention_days=cfg.retention_days,
                    max_rows=cfg.max_rows,
                )
            except Exception:
                logger.debug("Event log prune failed", exc_info=True)
===REPLACE===
    async def _event_log_prune_loop(self) -> None:
        """Periodic event log retention cleanup.

        AD-824: explicit ``CancelledError`` arm so the shutdown sweep
        terminates this loop deterministically.
        """
        cfg = self.config.event_log
        try:
            while True:
                await asyncio.sleep(cfg.prune_interval_seconds)
                try:
                    await self.event_log.prune(
                        retention_days=cfg.retention_days,
                        max_rows=cfg.max_rows,
                    )
                except Exception:
                    logger.debug("Event log prune failed", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("AD-824: _event_log_prune_loop cancelled")
            raise
===END REPLACE===
```

#### `_journal_prune_loop` (lines 2390-2401)

```
===SEARCH===
    async def _journal_prune_loop(self) -> None:
        """Periodic cognitive journal retention cleanup."""
        cfg = self.config.cognitive_journal
        while True:
            await asyncio.sleep(cfg.prune_interval_seconds)
            try:
                await self.cognitive_journal.prune(
                    retention_days=cfg.retention_days,
                    max_rows=cfg.max_rows,
                )
            except Exception:
                logger.debug("Journal prune failed", exc_info=True)
===REPLACE===
    async def _journal_prune_loop(self) -> None:
        """Periodic cognitive journal retention cleanup.

        AD-824: explicit ``CancelledError`` arm.
        """
        cfg = self.config.cognitive_journal
        try:
            while True:
                await asyncio.sleep(cfg.prune_interval_seconds)
                try:
                    await self.cognitive_journal.prune(
                        retention_days=cfg.retention_days,
                        max_rows=cfg.max_rows,
                    )
                except Exception:
                    logger.debug("Journal prune failed", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("AD-824: _journal_prune_loop cancelled")
            raise
===END REPLACE===
```

#### `_episodic_backup_loop` (around lines 2403-2445)

Read the full body before editing — only the outer `while True:` needs to be wrapped. Do NOT change `snapshot_episodic` cadence, retention math, or warmup-sleep semantics. The pre-existing `try: ... except Exception:` around `snapshot_episodic(...)` stays.

```
===SEARCH===
        # Warmup: 60s after start so we don't compete with boot I/O.
        await asyncio.sleep(60.0)
        while True:
            try:
                result = snapshot_episodic(
===REPLACE===
        # Warmup: 60s after start so we don't compete with boot I/O.
        await asyncio.sleep(60.0)
        try:
            while True:
                try:
                    result = snapshot_episodic(
===END REPLACE===
```

Then close the outer `try` at the end of the loop. Find the loop's existing tail (the final `else:` / `logger.warning` / `await asyncio.sleep(24 * 3600)` style closing — read lines 2403-2460 first to verify the exact final lines) and append:

```
        except asyncio.CancelledError:
            logger.debug("AD-824: _episodic_backup_loop cancelled")
            raise
```

aligned with the outer `try:` you added above. **Do not** dedent the existing body. **Do not** change `await asyncio.sleep(24 * 3600)` to anything else.

### Section 3.3 — Migrate the spawn sites to the helper

#### Spawn site: `_episodic_backup_task` (`runtime.py:2305-2308`)

```
===SEARCH===
        # AD-823: schedule the daily episodic backup loop. Task reference
        # stored on self so cancellation in shutdown can reach it; this
        # avoids the fire-and-forget anti-pattern called out in the
        # standing engineering principles.
        self._episodic_backup_task = asyncio.create_task(
            self._episodic_backup_loop()
        )
===REPLACE===
        # AD-823 + AD-824: schedule the daily episodic backup loop via
        # the runtime's background-task registry so the shutdown sweep
        # can cancel it deterministically before AD-820's clean-shutdown
        # marker is written.
        self._episodic_backup_task = self._spawn_background(
            self._episodic_backup_loop(),
            name="episodic-backup-loop",
        )
===END REPLACE===
```

#### Spawn site: `_event_log_prune_loop` (`src/probos/startup/infrastructure.py:49`)

The function receives `event_log_prune_loop_fn` as a parameter; the runtime passes `self._event_log_prune_loop`. The cleanest migration keeps the wiring but routes through the helper. Replace the local `event_prune_task` line.

```
===SEARCH===
    # Start infrastructure
    data_dir.mkdir(parents=True, exist_ok=True)
    await event_log.start()
    event_prune_task = asyncio.create_task(event_log_prune_loop_fn())
    await hebbian_router.start()
===REPLACE===
    # Start infrastructure
    data_dir.mkdir(parents=True, exist_ok=True)
    await event_log.start()
    # AD-824: register through the runtime's background-task helper.
    # The helper is added later as a kw-only parameter on this function;
    # for now we keep the existing local assignment but also register on
    # the runtime if a registry was supplied. See AD-824 for details.
    event_prune_task = asyncio.create_task(
        event_log_prune_loop_fn(), name="event-log-prune-loop"
    )
    if background_register is not None:
        background_register(event_prune_task)
    await hebbian_router.start()
===END REPLACE===
```

Then update the function signature and the caller. Add a new kw-only parameter `background_register: Callable[[asyncio.Task], None] | None = None` to `start_infrastructure` (or whatever the function in `infrastructure.py` is named — read lines 1-80 to confirm). Update the call site in `runtime.py` (search for `event_log_prune_loop_fn=self._event_log_prune_loop` at line 1676) to also pass `background_register=self._background_tasks.add`.

> **Rationale for not using `_spawn_background` directly here:** the task is constructed inside the `startup/` helper before the runtime is fully initialized in some test fixtures. Passing `self._background_tasks.add` as a callable keeps the helper's API narrow (no `runtime` reference threaded into `startup/infrastructure.py`).

#### Spawn site: `journal_prune_loop_fn` (`src/probos/startup/communication.py:313`)

Same pattern: add a `background_register` kw-only parameter, register the task.

```
===SEARCH===
    cognitive_journal = None
    if config.cognitive_journal.enabled:
        from probos.cognitive.journal import CognitiveJournal

        cognitive_journal = CognitiveJournal(
            db_path=str(data_dir / "cognitive_journal.db"),
        )
        await cognitive_journal.start()
        asyncio.create_task(journal_prune_loop_fn())
        logger.info("cognitive-journal started")
===REPLACE===
    cognitive_journal = None
    if config.cognitive_journal.enabled:
        from probos.cognitive.journal import CognitiveJournal

        cognitive_journal = CognitiveJournal(
            db_path=str(data_dir / "cognitive_journal.db"),
        )
        await cognitive_journal.start()
        _journal_task = asyncio.create_task(
            journal_prune_loop_fn(), name="cognitive-journal-prune-loop"
        )
        if background_register is not None:
            background_register(_journal_task)
        logger.info("cognitive-journal started")
===END REPLACE===
```

Update this function's signature with the same `background_register` kw-only parameter; update the caller in `runtime.py` (search for `journal_prune_loop_fn=self._journal_prune_loop` at line 2045) to pass `background_register=self._background_tasks.add`.

### Section 3.4 — Cancellation sweep in `startup/shutdown.py`

**File:** `src/probos/startup/shutdown.py`

The sweep MUST run after Phase 1 critical persistence completes (so the chroma close, eviction audit, etc. are already done — those are not registered loops) and IMMEDIATELY before the AD-820 marker block, so a stuck task cannot prevent the marker from being written. Insertion point is between the Phase 1 elapsed log (line 163) and the AD-820 try block (line 169).

```
===SEARCH===
    _phase1_elapsed = _time.monotonic() - _phase1_start
    logger.info("BF-207: Phase 1 (Critical Persistence) completed in %.1fs", _phase1_elapsed)

    # AD-820: write shutdown integrity marker so the next boot can detect a
    # clean vs. partial shutdown BEFORE opening ChromaDB. If consolidation
    # was 'full', the marker is 'clean'; otherwise 'partial' and the next
    # boot refuses to start unless --force-unclean is passed.
    try:
        from probos.shutdown_integrity import mark_clean_shutdown, mark_dirty_shutdown
===REPLACE===
    _phase1_elapsed = _time.monotonic() - _phase1_start
    logger.info("BF-207: Phase 1 (Critical Persistence) completed in %.1fs", _phase1_elapsed)

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

    # AD-820: write shutdown integrity marker so the next boot can detect a
    # clean vs. partial shutdown BEFORE opening ChromaDB. If consolidation
    # was 'full', the marker is 'clean'; otherwise 'partial' and the next
    # boot refuses to start unless --force-unclean is passed.
    try:
        from probos.shutdown_integrity import mark_clean_shutdown, mark_dirty_shutdown
===END REPLACE===
```

---

## 4. Tests

**File:** `tests/test_ad824_shutdown_hygiene.py` (new)

Use a real (or minimal stub) `ProbOSRuntime` instance rather than `MagicMock` per the standing "no MagicMock at substrate boundaries" rule. The helper only needs `self._background_tasks`; you can construct a tiny harness class that mirrors the helper's contract OR construct a real `ProbOSRuntime` with a minimal config — use whichever existing test fixture in the repo is already in service for runtime-tight unit tests (search `tests/conftest.py` for a runtime fixture first).

Required test cases:

1. **`test_spawn_background_registers_and_returns_task`** — calling `runtime._spawn_background(coro, name="t1")` returns an `asyncio.Task`, the task is in `runtime._background_tasks`, and `task.get_name() == "t1"`.
2. **`test_done_callback_removes_task_on_natural_completion`** — spawn a task that resolves immediately (`async def _q(): return None`), await its completion + one event-loop tick, assert the registry is empty.
3. **`test_stop_cancels_all_registered_tasks`** — spawn two long-sleeping tasks via `_spawn_background`, run the shutdown sweep code path (call `await shutdown(runtime, reason="test")` OR factor the sweep into a callable and test it directly if invoking full shutdown is too heavy), assert both tasks finished with `task.cancelled() is True`.
4. **`test_stop_returns_within_budget_when_task_ignores_cancellation`** — spawn an antagonist:
   ```python
   async def _stubborn():
       while True:
           try:
               await asyncio.sleep(60)
           except asyncio.CancelledError:
               pass  # deliberately swallow
   ```
   Run the sweep with a wall-clock timer. Assert the sweep returns in under 5.5s and that a `WARNING` log with `did not exit within 5s` is emitted (use `caplog.at_level(logging.WARNING)`).
5. **`test_spawn_background_preserves_attr_binding_pattern`** — verify the `self._x_task = self._spawn_background(...)` usage works: the attr holds the same `asyncio.Task` that the registry holds (`runtime._episodic_backup_task is task` AND `task in runtime._background_tasks`).

Optional (recommended): a sixth test that asserts the AD-820 marker file is written even when an antagonist is registered — confirms ordering invariant. Use a tmp_path data_dir.

**Test command:**

```
D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_ad824_shutdown_hygiene.py
```

---

## 5. What this does NOT change

- Per-event one-shot tasks (`asyncio.create_task(self.ward_room_router.deliver_bridge_alert(...))` at runtime.py lines 2699, 4065; `asyncio.create_task(fn(event))` at line 1197; `asyncio.create_task(_run_qa_for_designed_agent)` at line 3177). These are intentionally fire-and-forget with bounded lifetimes and do not block shutdown.
- NATS publish tasks (`_nats_publish_tasks` set at line 928). Already protected by their own registry per AD-637d.
- `_flush_task` (`startup/finalize.py:3763`). It is already explicitly cancelled in `startup/shutdown.py:88-92` before the sweep. Migrating it through `_background_tasks` would double-cancel; leave as-is for this AD.
- `_mcp_app_external_discovery_task` (`startup/finalize.py:1225`). One-shot, not a `while True` loop — leave as-is. File a forward marker if you observe it hanging in practice.
- AD-820's `shutdown_integrity` module. Do NOT modify it.
- AD-823's `snapshot_episodic` cadence or retention math.
- Per-agent tasks (yeoman `_flush_task` at `cognitive/yeoman.py:170` — that is owned by the agent, not the runtime).
- Loop bodies beyond adding the `CancelledError` handler. No refactoring, no cadence tweaks.

---

## 6. Acceptance criteria

- [ ] `_background_tasks: set[asyncio.Task]` declared in `ProbOSRuntime.__init__` near line 928.
- [ ] `_spawn_background(coro, name) -> asyncio.Task` method on `ProbOSRuntime` near line 2377.
- [ ] All three target loops (`_event_log_prune_loop`, `_journal_prune_loop`, `_episodic_backup_loop`) have `except asyncio.CancelledError: ... raise` arms.
- [ ] All three target spawn sites register through `_background_tasks` (directly via `_spawn_background` for the runtime-owned spawn; via the `background_register` kw-only parameter for the startup-module spawns).
- [ ] Shutdown sweep block present in `startup/shutdown.py` immediately before the AD-820 marker write, uses `timeout=5.0`, logs `WARNING` per abandoned task, and never raises.
- [ ] `tests/test_ad824_shutdown_hygiene.py` has 5+ tests covering the cases in Section 4 and passes.
- [ ] Full gate green: `D:\ProbOS\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile`.
- [ ] No `asyncio.create_subprocess_*` introduced (search the diff).
- [ ] No `asyncio.ensure_future` introduced (search the diff).
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- [ ] PROGRESS.md updated with one-line entry for AD-824.
- [ ] One commit, message ends with `Closes #759`. Push to `origin/main` when green.

---

## 7. Verified against codebase (2026-05-22)

```
grep -n "asyncio\.create_task\|loop\.create_task" src/probos/runtime.py
  1132: task = loop.create_task(_do_subscribe())                  # NATS publish, already in _nats_publish_tasks
  1183: task = loop.create_task(self.nats_bus.js_publish(...))    # same
  1197: asyncio.create_task(fn(event))                            # per-event handler, fire-and-forget
  2306: self._episodic_backup_task = asyncio.create_task(         # AD-823 — target of this AD
            self._episodic_backup_loop()
        )
  2699: asyncio.create_task(self.ward_room_router.deliver_bridge_alert(...))  # one-shot alert
  3177: asyncio.create_task(self._run_qa_for_designed_agent(record))          # one-shot QA
  4065: asyncio.create_task(self.ward_room_router.deliver_bridge_alert(...))  # one-shot alert

grep -n "_task" src/probos/runtime.py | head
  358:  self._episodic_backup_task: asyncio.Task[None] | None = None
  802:  self._mcp_app_external_discovery_task: asyncio.Task | None = None
  928:  self._nats_publish_tasks: set[asyncio.Task] = set()
  1988: self._flush_task = dream_result.flush_task

grep -n "async def \(stop\|shutdown\)" src/probos/runtime.py
  2470: async def stop(self, reason: str = "") -> None:           # delegates to startup/shutdown.py

grep -n "mark_clean_shutdown" src/probos/startup/shutdown.py
  170: from probos.shutdown_integrity import mark_clean_shutdown, mark_dirty_shutdown
  174:     mark_clean_shutdown(

grep -n "runtime\._\w*_task\s*=" src/probos/**
  src/probos/startup/finalize.py:1226: runtime._mcp_app_external_discovery_task = task
  src/probos/startup/finalize.py:3763: runtime._flush_task = asyncio.create_task(dream_adapter.periodic_flush_loop())

grep -n "except asyncio\.CancelledError" src/probos/runtime.py
  (no matches — none of the three target loops handle cancellation today)
```

All three target loop bodies (`_event_log_prune_loop` at runtime.py:2377-2388, `_journal_prune_loop` at runtime.py:2390-2401, `_episodic_backup_loop` at runtime.py:2403-2445) currently have `except Exception` arms inside their inner try, which under PEP-492 semantics will NOT swallow `CancelledError` (it inherits from `BaseException` in 3.8+). Confirmed by the AD-820 author's matching pattern in `_flush_task` cancellation at `startup/shutdown.py:88-92`. The new outer `try / except asyncio.CancelledError` arm is therefore additive — it makes the cancellation observable for logging, not behaviorally different.
