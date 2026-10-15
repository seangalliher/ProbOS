# BF-891 (#1542): ProcedureStore's write lock blocks the event loop

**Drafted by:** claude-architect (read-only consult, session id from the bridge header; saved verbatim by the orchestrator)
**Corrections (orchestrator, after review round 1, 2026-10-15; the rows and sentences below are corrected in place):** mutant M3 is killed by the contention check (`contended >= 1`) and the AST guard, not by a hang, because only `deactivate` takes the mutant lock; the aiosqlite worker thread inherits `daemon` from the thread that creates the connection (non-daemon in production, daemon inside the harness's private-loop thread); `runtime.py:3953` dispatches the backup snapshot to a thread, so "no thread dispatch" is narrowed to "no store writer is dispatched to a thread" (the store is referenced by 17 modules, not 14, and `runtime.py:3953` is the only dispatch among them).
**Status:** Ready to build. One slice. **Dependencies:** none. **Estimated tests:** 18 new, 1 pin updated.

**Verdict:** ✅ Buildable. The orchestrator's facts hold, with two corrections:
- `_save_to_index` holds 2 + N awaits (N = number of parent procedures), not "2-5".
- Today's code does **not** guarantee "no half-written row". If a writer is cancelled or fails mid-block, its statements stay pending, and the next writer's `commit` makes them durable.

The fix has two parts:
- Swap the `threading.Lock` for an `asyncio.Lock`.
- Route all 17 sites through one store-local async context manager, `_index_write()`, which rolls back an abandoned block before it releases the lock.

**Numbering:** BF-891 was assigned by the orchestrator. The prompts directory, `PROGRESS.md` and the roadmap show nothing above BF-890 (`prompts/bf-890-command-environment-allowlist.md`). I could not check git log or GitHub titles: Bash was denied in this run, even for `ls` and `head`.

---

## Problem

`src/probos/cognitive/procedure_store.py:136` sets `self._write_lock = threading.Lock()`. Seventeen `with self._write_lock:` blocks inside `async def` bodies `await` aiosqlite while they hold it. A second coroutine that reaches `acquire()` blocks the loop thread, and the holder can only resume on that same loop, so the runtime stops (executed probe: `logs/architect/probe_f23.py`).

The overlap is reachable in production. One store, built at `runtime.py:2917`, is shared by:
- every cognitive agent's replay bookkeeping (`cognitive_agent.py:1818`, `1834` and `7362-7565`: `record_*`, `promote_*`/`demote_*`, `reset_*`), which runs concurrently across agents;
- the dream steps (`dreaming.py:672-2427`: save, deactivate, decay, archive);
- the AD-1326 challenger (`procedure_challenger.py:290`, `420`, `530`, `550`);
- the HXI/shell routes (`routers/procedures.py:102`, `127`, `281`, `323`).

### Site inventory (verified by reading every block)

| # | Line | Method | Awaits inside the lock | Awaits before the lock |
|---|---|---|---|---|
| 1 | 601 | `_save_to_index` (via `save`) | execute INSERT OR REPLACE, execute ×N lineage, commit | none |
| 2 | 847 | `delete` | 2 execute, commit | SELECT 1 + fetchone |
| 3 | 999 | `record_selection` | execute, commit | `_increment_counter`, which takes and releases the lock first |
| 4 | 1022 | `record_consecutive_success` | execute, commit (its SELECT runs after release) | none |
| 5 | 1040 | `reset_consecutive_successes` | execute, commit | none |
| 6 | 1051 | `promote_compilation_level` | execute, commit (`get` runs after release) | none |
| 7 | 1066 | `demote_compilation_level` | execute, commit | none |
| 8 | 1129 | `_increment_counter` (record_applied, record_completion, record_fallback, record_selection) | execute, commit | none |
| 9 | 1207 | `deactivate` | execute UPDATE, execute SELECT, fetchone, [execute UPDATE snapshot], commit | none |
| 10 | 1325 | `request_promotion` | execute, commit | SELECT + fetchone |
| 11 | 1364 | `approve_promotion` | execute, commit | none |
| 12 | 1381 | `reject_promotion` | execute, commit | none |
| 13 | 1565 | `decay_stale_procedures` (one block per row) | execute, [execute], commit | SELECT + fetchall |
| 14 | 1639 | `archive_stale_procedures` (one block per row) | execute, execute SELECT, fetchone, [execute], commit | SELECT + fetchall |
| 15 | 1716 | `restore_procedure` | execute, [execute], commit | SELECT + fetchone |
| 16 | 1920 | `merge_procedures` (stats transfer) | execute, commit | get ×2, get_quality_metrics |
| 17 | 1959 | `merge_procedures` (tags; inside `try/except Exception: pass`) | execute, commit | SELECT + fetchone |

- **Nested acquisition: none.** Every in-lock body calls only `self._db.execute`, `cursor.fetchone` and `self._db.commit`.
- **Sequential re-acquisition** (safe with either lock type): `record_selection` (site 8, then site 3) and `merge_procedures` (16 → 17 → `deactivate` at site 9, called at :1975 after release).
- **Every site checks `self._db` before entering the block:**
  - an early `if not self._db: return` before 1, 2, 4-17;
  - site 3 sits inside `if self._db:`.

### Threads (fact 2)

- **Callers:** of the 17 modules that reference `ProcedureStore` or `procedure_store` (`git grep -l -E "ProcedureStore|procedure_store" -- src/probos`, excluding the store itself), the only thread-dispatch primitive (`run_in_executor`, `to_thread`, `threading.Thread`, `run_coroutine_threadsafe`, `ThreadPoolExecutor`) is `runtime.py:3953`, which runs the backup `snapshot` in a thread; it copies files through `sqlite3`'s backup API on its own connections and calls no store method. So no store writer is dispatched to a thread.
- **API server:** uvicorn runs as a task on the runtime loop (`__main__.py:932`: `asyncio.create_task(server.serve())`).
- **aiosqlite's worker thread** runs queued SQL only (`aiosqlite/core.py:48-66`, `150-160`). It never touches store attributes or the lock.
- **Chroma calls** are synchronous on the loop thread, outside the lock.

So the lock is only ever acquired and released on one loop thread, and `asyncio.Lock`, which is not thread-safe, is correct here.

### Today's cancellation behaviour

A cancelled holder's `with` releases the `threading.Lock` (on CancelledError, `__exit__` runs). A waiter can never be cancelled, because the loop is blocked. The statements the holder already issued (aiosqlite still runs a cancelled call: `core.py:59-66` sets the result only `if not fut.done()`) stay in the connection's implicit transaction, and the next writer's `commit` makes them durable.

Example: `deactivate` cancelled after its first UPDATE leaves the `is_active=0` column set while the snapshot still says active. The same happens to a statement that raises: a FOREIGN KEY failure on a lineage INSERT leaves the procedure row, without its lineage, to be committed by the next writer.

## Solution

**Option P1 (chosen): a per-store `asyncio.Lock` plus a store-local `@asynccontextmanager _index_write()`.**
- The context manager acquires the lock and yields.
- On any `BaseException` leaving the block, it queues `ROLLBACK` in a shielded task and keeps the lock until the ROLLBACK has run.
- A second cancellation during that wait is delivered afterwards, never swallowed.
- This follows the reviewed AD-1326 ledger pattern (`procedure_challenges.py:173-221`, R3-2/R4-1), minus `BEGIN IMMEDIATE`. The store keeps SQLite's implicit transaction, so the transaction mode and lock timing against other connections do not change.

| Rank | Primitive | Cancellation guarantee | Why it wins or loses |
|---|---|---|---|
| **P1 ✅** | `asyncio.Lock` + `_index_write()` with shielded ROLLBACK | A waiter is removed from the FIFO and wakes the next one (`locks.py:111-119`). A holder's partial statements are rolled back before release, and a cancelled `commit` the worker finished leaves "no transaction is active", which is ignored. | Meets both constraints. Mechanical across the 17 sites. The SQL text and order do not change. |
| P2 | Bare `async with self._write_lock:` (asyncio.Lock only) | The lock is released, but the half-written row stays exactly as today. | Fixes the hang but fails the issue's "no half-written row" constraint. |
| P3 | Single writer task with a queue | A caller's cancellation does not withdraw its queued write. Needs a new start/stop lifecycle and error propagation through futures. | Larger, changes caller-visible semantics, and adds a task that must not leak. Rejected. |
| P4 | Reuse `procedure_challenges._write_transaction(lock, connect)` | Same as P1. | It imports a private name across modules, adds `BEGIN IMMEDIATE` at 17 sites (new busy semantics, no `busy_timeout` on this connection) and a double commit. Rejected. Unifying the two is a DRY follow-up. |

### Design answers

**Event-loop binding.** On 3.12.13 (`d:/ProbOS/.venv/pyvenv.cfg:4`), `asyncio.Lock()` binds no loop at construction. `_get_loop()` binds on the first *contended* acquire (`locks.py:105`, `mixins.py:12-21`), so creating the lock in `__init__` outside a running loop is safe. In production the store is constructed and started inside the async startup (`runtime.py:2917-2921`) and used on that loop. Using one store under contention on two loops would raise `RuntimeError`; no caller does that. The test harness below creates its store on its own private loop.

**Fairness.** `asyncio.Lock` wakes waiters FIFO (`_wake_up_first`). `threading.Lock` made no ordering promise. This is an improvement, not a dependency.

**Re-entrancy.** Neither lock is re-entrant, and there are no nested acquisitions today (verified above). A future nested writer would now deadlock its own coroutine instead of the whole loop. That is a follow-up; no guard is added here.

**Guard test.** The chosen form (G1) works by structure, not by name: in `procedure_store.py`, no synchronous `with` block inside an `async def` may contain an `await`, `async with` or `async for` (not counting nested defs or lambdas). This catches a threading lock under any name or alias, including `__dict__.setdefault(...)` mutants. It is strict but sound, because after the fix the module has no sync `with` at all (the only 17 today are the lock sites; grep below). Rejected alternatives:
- G2 (resolve names bound to `threading.*` constructors) misses aliasing.
- G3 (name contains "lock") is brittle.

The runtime check `isinstance(store._write_lock, asyncio.Lock)` complements G1.

**Real-overlap tests.**
- **Harness.** Each scenario runs `asyncio.run(...)` on a daemon thread, with its own store created on that loop. The pytest thread waits on `threading.Event`s, with one budget for start-up and another for the scenario.
- **On a hang** the harness:
  - records `hung=True`;
  - releases every locked plain `threading.Lock` found in `vars(store)` (any thread may release one), so the loop thread can finish its scenario and close the store instead of staying blocked with an open connection;
  - returns.
  The test then fails without hanging the suite.
- **Controls first:** a single save, then sequential saves, both with `contended == 0`.
- **Overlaps:** one `asyncio.gather` per site group. Each run swaps in an `_ObservedLock(asyncio.Lock)` and asserts `contended >= 1`, which proves the calls really met inside the critical section.

---

## Implementation

### Section 1 -- `src/probos/cognitive/procedure_store.py` (imports)

SEARCH:
```python
import asyncio
import json
import logging
import threading
import time
from enum import Enum
```
REPLACE:
```python
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum
```
(`threading` has no other use in this module: its only hits are :17 and :136.)

### Section 2 -- `src/probos/cognitive/procedure_store.py` (module rollback helper)

SEARCH:
```python
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# AD-536: Procedure Criticality Classification
```
REPLACE:
```python
logger = logging.getLogger(__name__)


async def _roll_back_index_write(db: "DatabaseConnection") -> None:
    """BF-891: ``ROLLBACK`` an abandoned index write; a failure other than "nothing to undo" is logged at ERROR.

    SQLite refuses a ``ROLLBACK`` when no transaction is open ("cannot rollback - no transaction
    is active"): the block issued no statement, or a cancelled ``commit`` still completed on the
    worker thread. Either way nothing is pending, so that refusal is not logged.
    """
    try:
        await db.execute("ROLLBACK")
    except Exception as exc:
        if "no transaction is active" in str(exc):
            return
        # Propagate (the caller re-raises its original error); this log is the only trace of the open transaction.
        logger.error(
            "BF-891: an abandoned procedure index write could not be rolled back; its statements "
            "remain pending on the store's connection and the next write's commit would make them durable",
            exc_info=True,
        )


# ------------------------------------------------------------------
# AD-536: Procedure Criticality Classification
```

### Section 3 -- `src/probos/cognitive/procedure_store.py` (the primitive)

SEARCH:
```python
            self._connection_factory = default_factory
        self._write_lock = threading.Lock()
        self._chroma_collection: Any = None
```
REPLACE:
```python
            self._connection_factory = default_factory
        # BF-891: loop-owned; a threading.Lock held across the awaits in _index_write blocked the
        # event-loop thread when two writes overlapped (#1542). Binds to the loop on first contention.
        self._write_lock = asyncio.Lock()
        self._chroma_collection: Any = None
```

### Section 4 -- `src/probos/cognitive/procedure_store.py` (the write context manager)

SEARCH:
```python
        self._challenges: ProcedureChallengeLedger | None = None  # AD-1326

    async def start(self) -> None:
        """Initialize SQLite index and ChromaDB collection."""
```
REPLACE:
```python
        self._challenges: ProcedureChallengeLedger | None = None  # AD-1326

    @asynccontextmanager
    async def _index_write(self) -> AsyncIterator[None]:
        """BF-891: one SQLite index write, serialised by the loop-owned ``_write_lock``.

        A writer that finds the lock held suspends instead of blocking the event-loop thread.
        Waiters wake in FIFO order. The lock is not re-entrant: no block may call another writer.
        Every caller has checked ``self._db`` before entering.

        An exception or cancellation that leaves the block is rolled back before it propagates.
        This store's writes share one connection and run in SQLite's implicit transaction, so a
        block abandoned after its first statement would otherwise be committed by the next
        writer's ``commit`` (a half-written row). aiosqlite runs one connection's calls in order
        on one worker thread, so a cancelled statement may still run; the ``ROLLBACK`` is queued
        behind it, and the lock is held, through further cancellations, until it has run (the
        AD-1326 ledger's R4-1 rule in ``procedure_challenges._write_transaction``). A second
        cancellation during the rollback of another error is re-raised, not swallowed.
        """
        async with self._write_lock:
            db = self._db
            try:
                yield
            except BaseException as exc:
                cleanup = asyncio.create_task(_roll_back_index_write(db))
                cancelled_again = False
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        cancelled_again = True
                if cancelled_again and not isinstance(exc, asyncio.CancelledError):
                    raise asyncio.CancelledError() from exc
                raise

    async def start(self) -> None:
        """Initialize SQLite index and ChromaDB collection."""
```

### Section 5 -- `src/probos/cognitive/procedure_store.py` (17 sites, scripted)

The 17 lines are identical, apart from indentation, so SEARCH/REPLACE cannot anchor them. Apply this exact rewrite from the worktree root. It preserves CRLF and asserts the count:

```
d:/ProbOS/.venv/Scripts/python.exe -I -c "import re,pathlib; p=pathlib.Path('src/probos/cognitive/procedure_store.py'); t=p.read_bytes().decode('utf-8'); pat=re.compile(r'(?m)^([ \t]+)with self\._write_lock:'); n=len(pat.findall(t)); assert n==17, n; p.write_bytes(pat.sub(r'\1async with self._index_write():', t).encode('utf-8')); print('rewrote', n)"
```

The pattern requires `with` right after the indentation, so Section 4's `async with self._write_lock:` is never matched, and the order of Sections 4 and 5 does not matter. Before → after, at every row of the site table: `with self._write_lock:` → `async with self._index_write():`, with the indentation unchanged and the block bodies untouched.

**Post-rewrite checks** (the orchestrator runs them; expected results in brackets):
- `grep -c "async with self._index_write():" src/probos/cognitive/procedure_store.py` → **17**
- `grep -n "with self._write_lock" src/probos/cognitive/procedure_store.py` → **exactly 1 line**, the helper's `async with self._write_lock:`
- `grep -n "threading" src/probos/cognitive/procedure_store.py` → **no lines**

### Section 6 -- `tests/test_procedure_store.py` (hidden pin)

SEARCH:
```python
    async def test_write_lock_exists(self, store):
        """Store has a threading.Lock for write serialization."""
        assert hasattr(store, '_write_lock')
        # Verify it's a lock by checking it has acquire/release
        assert hasattr(store._write_lock, 'acquire')
        assert hasattr(store._write_lock, 'release')
```
REPLACE:
```python
    async def test_write_lock_exists(self, store):
        """Store serialises writes with a loop-owned asyncio.Lock.

        BF-891: was a threading.Lock, which blocked the event loop when two writes overlapped
        (#1542); the old acquire/release check passed for either type, so it pinned nothing.
        """
        assert isinstance(store._write_lock, asyncio.Lock)
        assert not store._write_lock.locked()
```
(`asyncio` is already imported at `tests/test_procedure_store.py:16`.)

### Section 7 -- `tests/test_bf891_procedure_store_lock.py` (new)

**Shared helpers** (the Builder writes them; the names are binding):
- `_proc(pid, *, level=1, parents=(), tags=())` builds a minimal `Procedure` from `ProcedureStep` (same shape as `tests/test_procedure_store.py:39-75`).
- `_ObservedLock(asyncio.Lock)` adds `contended: int`. Its `acquire` does `if self.locked(): self.contended += 1` and then calls `super().acquire()`.
- `_run_on_private_loop(tmp_path, scenario, *, start_budget_s=120.0, budget_s=15.0) -> _LoopRun(hung, error, stage)` is the watchdog harness described in Design answers:
  - a daemon thread runs `asyncio.run(main())`;
  - `main` builds `ProcedureStore(data_dir=tmp_path/"procedures")`, awaits `start()`, sets `started`, swaps in an `_ObservedLock` as `store._write_lock`, awaits `scenario(store, lock)`, and stops the store in `finally`;
  - when `finished` is not set within `budget_s` after `started`, it releases every locked `type(threading.Lock())` value in `vars(store)` (up to 100 tries, 0.1 s apart) and returns `hung=True`;
  - when `started` itself times out, it returns `stage="start"`, which tests report as a premise failure, not a hang.
- `_GatedFactory` wraps only the `procedures.db` connection, with a `_GatedConnection` that delegates through `__getattr__`. `execute(sql, *a)` checks the next armed one-shot gate `(predicate, entered, release)`: on a match it sets `entered`, awaits `release`, then delegates. Other paths return the real connection, so the AD-1326 ledger is untouched.
- `_committed_row(db_path, pid)` reads `is_active, superseded_by, content_snapshot` through an independent `sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)`.
- `scan_sync_with_awaits(source) -> list[int]` is the G1 AST scanner.

| Test | Premise / assertion | Negative control |
|---|---|---|
| `test_harness_reports_a_blocked_loop_instead_of_hanging` | A scenario stores `threading.Lock()` on the store and gathers two coroutines that each do `with lock: await asyncio.sleep(0.05)`. With `budget_s=2`, the harness returns `hung=True` and its thread has finished. | It *is* the harness's negative control: it proves the watchdog can fail. |
| `test_control_single_save_completes` | `save(p0)` → `get(p0)` is not None; `lock.contended == 0`; not hung. | Overlap tests below require `contended >= 1`. |
| `test_control_sequential_saves_complete` | Saves p1 then p2 → both present; `contended == 0`. | As above. |
| `test_overlapping_saves_complete` | `gather(save(p3), save(p4))` → both rows present; `contended >= 1` (site 1). | M2 hangs it, and the harness reports it. |
| `test_save_overlapping_deactivate_completes` | Seed p1; `gather(save(p5), deactivate("p1", superseded_by="p5"))` → p5 active; p1's column and snapshot both inactive and superseded by p5; `contended >= 1` (sites 1 and 9). This is the challenger-promotion overlap. | M3 fails it: only `deactivate` takes the mutant lock, so nothing contends (`contended == 0`) and no hang is possible. |
| `test_overlapping_counter_writes_complete` | Seed p1; `gather(record_selection, record_applied, record_completion, record_fallback, record_consecutive_success)` → metrics 1/1/1/1 and `consecutive_successes == 1`; `contended >= 1` (sites 3, 4, 8). | `contended == 0` under M9. |
| `test_overlapping_compilation_level_writes_complete` | Seed p1-p3; `gather(promote(p1,3), demote(p2,1), reset_consecutive_successes(p3))` → levels 3 and 1, p3 at 0 (sites 5, 6, 7). | M9 |
| `test_overlapping_promotion_status_writes_complete` | Seed p3 at level 4 with 10 selections and 10 completions (written sequentially); `gather(request_promotion(p3), approve_promotion(p1,"captain","d1"), reject_promotion(p2,"captain","r"))` → p3 eligible and pending, p1 approved, p2 rejected (sites 10, 11, 12). | M9 |
| `test_overlapping_decay_and_archive_complete` | Seed pA at level 1 and pB at level 3 with 3 selections; `future = time.time() + 91*86400`; `gather(archive_stale_procedures(now=future), decay_stale_procedures(now=future))` → pA archived, pB at level 2 (sites 13, 14). | M9 |
| `test_overlapping_restore_delete_merge_complete` | Seed pArch, archive it sequentially with the future `now`, then seed pDel, pPrim and pDup; `gather(restore_procedure(pArch), delete(pDel), merge_procedures(pPrim, pDup))` → pArch active at level 1, pDel gone, pDup inactive and superseded by pPrim (sites 2, 15, 16, 17, 9). | M9 |
| `test_cancel_while_waiting_writes_nothing_and_releases` | Pytest loop: hold `async with store._write_lock`, start `save(p9)`, yield ×5; premise: the task is not done; cancel it, exit the hold → CancelledError; lock not held; `get(p9)` is None; a following `save(p10)` succeeds. | Under M2 the save bypasses the lock, so the premise ("still waiting") fails. |
| `test_cancel_while_holding_rolls_back_the_partial_deactivate` | Gated store; seed p1; arm a gate on `SELECT content_snapshot FROM procedure_records WHERE id`; run `deactivate("p1","x")` and await `entered`. Premises: the lock is held; the same connection sees `is_active=0` (the partial write is pending); the independent read sees 1. Cancel → CancelledError, lock released; `save(p2)` commits; the independent read shows p1 `is_active=1`, `superseded_by=""`. | M4 (and today's code) commit the half-row. |
| `test_second_cancel_during_rollback_holds_the_lock_until_it_ran` | Gates on the SELECT, then on `ROLLBACK`. First cancel at the SELECT gate; await the ROLLBACK gate's `entered`; cancel again; yield ×5; assert the lock is held and the task is not done; open the gate → CancelledError; lock released; follow-up save; p1 still active. | M5: the second cancel kills the cleanup before ROLLBACK, so the lock is released early and the half-row is committed. |
| `test_failed_statement_rolls_back_the_partial_save` | `save(_proc("child", parents=["missing"]))` raises `sqlite3.IntegrityError`. This premise is FOREIGN KEY enforcement (`:109-110`, `PRAGMA foreign_keys=ON` at `:154`); if it does not raise, stop and report, do not weaken the test. Then `save(p2)` → the independent read finds no `child` row. | M4 and today's code make `child` durable without its lineage. |
| `test_cancel_during_rollback_of_an_error_is_not_swallowed` | Gate on `ROLLBACK`; start the FK-failing save; await `entered`; cancel; open the gate → the task raises **CancelledError** (not IntegrityError); lock released. | M6 surfaces IntegrityError. |
| `test_no_sync_with_block_in_procedure_store_awaits` | `scan_sync_with_awaits(<module source>) == []`; the message lists `procedure_store.py:<line>` for each hit. | M2 and M3 are named by line. |
| `test_scanner_flags_a_sync_with_that_awaits` | On inline sources: `async def f():\n    with self._x:\n        await g()` → `[2]`. An `async with` → `[]`. A sync `with` without an await → `[]`. An `await` inside a nested `async def` within the `with` → `[]`. | It proves the scanner can fail. |
| `test_write_lock_is_loop_owned` | A fresh `ProcedureStore(tmp)` built with no running loop (a sync test) → `isinstance(store._write_lock, asyncio.Lock)`. | M1 |

## Mutation table

Anchors marked *(occurrence k/17)* are the k-th line, in file order, whose stripped text equals `async with self._index_write():`. Select it by that rule (Python: `[i for i,l in enumerate(lines) if l.strip()=="async with self._index_write():"][k-1]`) and keep the indentation.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| M1 | `src/probos/cognitive/procedure_store.py` | `self._write_lock = asyncio.Lock()` | `self._write_lock = __import__("threading").Lock()` | `test_write_lock_is_loop_owned`, `tests/test_procedure_store.py::TestThreadSafety::test_write_lock_exists` |
| M2 | `src/probos/cognitive/procedure_store.py` | `async with self._index_write():` *(occurrence 1/17, `_save_to_index`)* | `with self.__dict__.setdefault("_bf891_mutant_lock", __import__("threading").Lock()):` | `test_no_sync_with_block_in_procedure_store_awaits`, `test_overlapping_saves_complete` (hung) |
| M3 | `src/probos/cognitive/procedure_store.py` | `async with self._index_write():` *(occurrence 9/17, `deactivate`)* | `with self.__dict__.setdefault("_bf891_mutant_lock", __import__("threading").Lock()):` | `test_no_sync_with_block_in_procedure_store_awaits`, `test_save_overlapping_deactivate_completes` (fails `contended >= 1`; no hang) |
| M4 | `src/probos/cognitive/procedure_store.py` | `cleanup = asyncio.create_task(_roll_back_index_write(db))` | `cleanup = asyncio.create_task(asyncio.sleep(0))` | `test_cancel_while_holding_rolls_back_the_partial_deactivate`, `test_failed_statement_rolls_back_the_partial_save` |
| M5 | `src/probos/cognitive/procedure_store.py` | `await asyncio.shield(cleanup)` | `await cleanup` | `test_second_cancel_during_rollback_holds_the_lock_until_it_ran` |
| M6 | `src/probos/cognitive/procedure_store.py` | `if cancelled_again and not isinstance(exc, asyncio.CancelledError):` | `if False:` | `test_cancel_during_rollback_of_an_error_is_not_swallowed` |
| M9 | `src/probos/cognitive/procedure_store.py` | `async with self._write_lock:` | `async with __import__("contextlib").nullcontext():` | every overlap test's `contended >= 1` |

M7 (rollback failure log) is deliberately not tested: making a real ROLLBACK fail needs a closed-connection race that is out of scope.

## Builder briefs

- **`procedure_store.py`:**
  - apply Sections 1-4 as SEARCH/REPLACE, then run the Section 5 script and its three checks;
  - change no SQL text, statement order, schema or method signature;
  - leave the `except Exception: pass` blocks inside sites 9, 13, 14 and 15 as they are.
- **`tests/test_procedure_store.py`:** Section 6 only.
- **`tests/test_bf891_procedure_store_lock.py`:**
  - each test's premise and negative control are in the table above;
  - the harness must never `join()` without a timeout;
  - the cancellation tests run on the pytest loop with `asyncio.wait_for(entered.wait(), 5)`;
  - read the committed state only through the independent `sqlite3` read-only connection;
  - if `test_failed_statement_rolls_back_the_partial_save`'s premise (IntegrityError) fails, hard-stop and report;
  - budgets stay under pytest-timeout's 180 s (`pyproject.toml:190`).

## Diff Reviewer brief (properties to verify)

1. No synchronous `with` in `procedure_store.py` contains an await. All 17 former sites, and only those, use `_index_write()`.
2. `_index_write` keeps the lock until the ROLLBACK has run, across further cancellations; the original exception propagates; a second cancellation is not swallowed.
3. No SQL, schema, ordering or signature change, and no other module edited.
4. The tests cannot hang the suite: every wait is bounded, and a wedged threading lock is released.
5. The consumers that must accept this:
   - the runtime's shared store, written concurrently by `cognitive_agent` `record_*`, by dreaming and by `procedure_challenger`;
   - the `ChallengeProcedureStore` protocol (`procedure_challenger.py:73`), which is unchanged.

## What this does not change

- The procedure challenger's decisions.
- The schema and on-disk files.
- The ledger's `_write_transaction`.
- Other stores' locks.
- `stop()` closing the connection under a suspended writer (that race exists today; follow-up).
- The `DatabaseConnection` protocol (ROLLBACK goes through `execute`, as in the ledger).

## Tracking

- `PROGRESS.md`: add one line: "BF-891 (#1542): ProcedureStore write lock is loop-owned (asyncio.Lock) and an abandoned write rolls back; overlapping writes no longer stop the event loop."
- The roadmap Bug Tracker carries no BF-88x/890 rows (grep found none), so follow the current convention and add no row.
- No DECISIONS.md entry.

## Acceptance criteria

1. The Section 5 checks give 17, 1 and 0 lines.
2. All 18 new tests and the updated pin pass at `-n 0`. The existing procedure test files pass.
3. `d:/ProbOS/.venv/Scripts/python.exe logs/architect/probe_f23.py` prints all four phases and exits 0.
4. The mutation campaign kills M1-M6 and M9. M2 and M3 are the "restore the blocking lock at one site" mutants.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do not build

- `procedure_challenger_enabled` changes.
- Locking in any other store (follow-ups below).
- `BEGIN IMMEDIATE`/`busy_timeout` on the store connection.
- Extracting a shared transaction helper.
- A `stop()` lock.
- Any change to `DatabaseConnection`.

## Orchestrator commands

- **Focused gate:**
  `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf891_procedure_store_lock.py tests/test_procedure_store.py tests/test_procedure_evolution.py tests/test_procedure_archival.py tests/test_procedure_decay.py tests/test_procedure_dedup.py tests/test_graduated_compilation.py tests/test_procedure_store_promotion.py tests/test_promotion_approval.py tests/test_ad1326_procedure_challenger.py tests/test_ad1326_challenger_e2e.py tests/test_ad1326_procedure_ledger.py -q -n 0`
- **Probe:** `d:/ProbOS/.venv/Scripts/python.exe logs/architect/probe_f23.py`
- **Broad gate (once, after commit):**
  `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-891 --receipt logs/gates/bf-891.receipt.json`

## Captain's fallback (not in this contract's edits)

If BF-891 cannot land this session, defaulting `dreaming.procedure_challenger_enabled` to false touches:
- **Config:** `src/probos/config_models/cognition.py:169` (`default=True` → `False`).
- **Docs:** `docs/development/config-reference.md:310` (default column) and the description text.
- **Golden:** `docs/development/config-facade-baseline.yaml:1592` (`default: 'True'`).
- **Default pins:**
  - `tests/test_ad1152_agentic_correlation.py:285` (`pop(...) is True`);
  - `tests/test_ad1270e2b_cognition_models.py:142`;
  - `tests/test_ad1326_config.py:3` and `:41` (the docstring and `_DEFAULTS`).
- **AD-1326 tests that rely on the default** to build the challenger: they need an explicit `procedure_challenger_enabled=True`. Find them with `rg -n "DreamingConfig\(\)|SystemConfig\(\)" tests/test_ad1326_*.py tests/test_ad1326_startup_wiring.py`; I did not run that enumeration.
- **Prose:** `DECISIONS.md:26` and the AD-1326 `PROGRESS.md` line.

The fallback narrows the overlap but does not remove it: the agents' `record_*` calls and the dream saves still overlap.

## Prior art and blind spots

**Adopted:** the AD-1326 ledger's reviewed cancellation-safe write (`procedure_challenges.py:152-221`) and the `asyncio.Lock` row-write pattern already used in `workforce.py:2769`, `event_log.py:492` and `episodic.py:1273`.

**Rejected:** `BEGIN IMMEDIATE` (it changes the locking against other connections) and a writer task (P3). No outside research was needed: this is ProbOS-specific plumbing, and the asyncio and aiosqlite behaviour was verified in the installed sources.

**Blind spots, recorded as follow-ups:**
1. `stop()` can close `_db` under a suspended writer. The rollback then logs ERROR on a closed connection. `stop()` should take `_write_lock`.
2. DRY: unify `_roll_back_index_write` with the ledger's `_roll_back` and `_write_transaction` in `probos/storage/`.
3. Reads outside the lock on the same connection see a writer's uncommitted statements (unchanged).
4. A repo-wide AST guard for threading locks held across awaits. The text scan below is window-bounded.
5. A future nested writer call would self-deadlock one coroutine.

**Other `threading` locks held across `await` (fact 4):** a multiline scan, `^[ \t]+with [\w\.]*(lock|LOCK)\w*(\(\))?:[ \t]*\r?\n(?:[ \t]+[^\n]*\n){0,12}?[ \t]+[^\n]*\bawait\b` over `src/probos`, hit 28 times in 7 files. After the 17 sites here, the other 11 are:
- `long_runs.py:291`
- `peer_perception.py:127` and `:231`
- `peer_observation_monitor.py:509` and `:534`
- `durable_events.py:290` and `:446`
- `loop_host.py:280`
- `credentials.py:195`, `:256` and `:264`

I read all 11, and in every one the `await` is after the block ends (dedented), so none holds a lock across an await. The scan only looks 12 lines ahead, so an await in a longer block would be missed: hence follow-up 4.

---

## Verified Against Codebase (2026-10-14)

```
Grep "_write_lock|threading|async def |..." src/probos/cognitive/procedure_store.py
  17: import threading   136: self._write_lock = threading.Lock()
  601 847 999 1022 1040 1051 1066 1129 1207 1325 1364 1381 1565 1639 1716 1920 1959: with self._write_lock:
Grep "^\s+(async )?with " procedure_store.py   -> only the 17 lock sites (+ docstring text at 946)
Grep "asynccontextmanager|AsyncIterator" procedure_store.py   -> none (Section 1 adds them)
Read procedure_store.py 120-176, 285-384, 565-734, 836-865, 990-1151, 1200-1395, 1528-1747, 1900-1982   (site bodies, guards, lifecycle)
Grep "REFERENCES|FOREIGN KEY" procedure_store.py   -> 109-110
Grep "\"(UPDATE|INSERT|DELETE|ALTER|CREATE)|\.commit\(\)" procedure_store.py   -> writes outside the lock only in start() migrations (150-280, 1150-1159)
Read procedure_challenges.py 152-221   -> _roll_back / _write_transaction (prior art)
Read protocols.py 325-358   -> DatabaseConnection has no rollback
Read storage/sqlite_factory.py   -> plain aiosqlite.connect (no isolation_level set)
Read aiosqlite/core.py 28-72, 84-93, 150-160   -> one worker thread (daemon flag inherited from the creating thread), FIFO, set_result only if not done
Read cpython-3.12 asyncio/locks.py 92-139, mixins.py 12-21   -> lazy loop binding, FIFO, cancelled waiter cleanup
Read d:/ProbOS/.venv/pyvenv.cfg   -> 3.12.13
Grep "run_in_executor|to_thread|threading\.Thread|run_coroutine_threadsafe|ThreadPoolExecutor" (the 17 modules that reference the store)   -> only runtime.py:3953 (the backup snapshot; it calls no store method)
Grep "store\.(save|deactivate|...)\(" src/probos   -> callers listed in Problem
Read runtime.py 2913-2925; Grep __main__.py "server.serve" -> 932 create_task on runtime loop
Grep "_write_lock" repo (excluding module)   -> tests/test_procedure_store.py:1292-1297 (only code pin)
Grep "ProcedureStore\.__new__" tests -> test_ad567d_dream_provenance.py:171 (hasattr only; unaffected)
Grep "_write_transaction" -> procedure_challenges.py, test_ad1326_procedure_ledger.py (hence the name _index_write)
Grep pyproject.toml -> asyncio_mode="auto" (181), timeout=180 (190), addopts "-n 16 --dist=loadfile" (196)
Grep config.py LIFECYCLE_/PROMOTION_MIN_ -> 273-275, 291-296
Grep "procedure_challenger_enabled" (fallback pins) -> cognition.py:168, config-reference.md:310, config-facade-baseline.yaml:1592, test_ad1152:285, test_ad1270e2b:142, test_ad1326_config.py:3,41
```

## Absence Verified (2026-10-14)

```
CLAIM: no lock site calls another lock-taking method inside its block
RUN:   Read of all 17 block bodies (ranges above)
FOUND: only self._db.execute / cursor.fetchone / self._db.commit inside; re-acquisitions at 996→999 and 1920→1959→1975 are sequential
HOLDS: yes

CLAIM: no store writer is dispatched to another thread
RUN:   Grep run_in_executor|to_thread|threading\.Thread|run_coroutine_threadsafe|ThreadPoolExecutor over the 17 modules that reference the store (git grep -l -E "ProcedureStore|procedure_store" -- src/probos, minus the store itself)
FOUND: only runtime.py:3953 (to_thread of the backup snapshot, which copies files through sqlite3's backup API and calls no store method)
HOLDS: yes; uvicorn shares the loop (__main__.py:932)

CLAIM: no other test or script pins _write_lock's type
RUN:   Grep "_write_lock" across the repo, excluding the module
FOUND: tests/test_procedure_store.py:1292-1297 only (the other hits are other stores' attributes, prompts and docs)
HOLDS: yes
```

---

**Memory note written:** `.claude/agent-memory/claude-architect/feedback_grep_crlf.md`. On this CRLF checkout, multiline Grep needs `\r?\n`; my first scan came back empty because of it.
