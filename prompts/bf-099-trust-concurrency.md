# BF-099: Trust Engine Concurrency Safety

## Context

The TrustNetwork has **zero concurrency protection** on its in-memory state and database writes. Six independent code paths call `record_outcome()` or directly mutate trust records concurrently. Over sustained operation (72+ hours), this causes:

- Lost updates from interleaved read-modify-write cycles on `_records`
- "Stuck" trust scores that don't reflect recent outcomes
- Potential data loss from the unsafe DELETE-all/INSERT-all save pattern
- Database lock errors from missing WAL mode and busy_timeout

The crew independently diagnosed this as a recurring "stuck calculation" with ~72-hour recurrence — the time needed for enough concurrent mutations to accumulate visible drift.

**This is a prerequisite for AD-558 (Trust Cascade Dampening).** Dampening logic in `record_outcome()` is meaningless if concurrent callers can race with it.

## Six Findings to Fix

### Finding 1: No Locks on `_records` Dict (Critical)
**File:** `src/probos/consensus/trust.py`

`TrustNetwork` stores all trust records in a plain `dict` (`self._records`) with no locking. `record_outcome()` does a read-modify-write cycle (get_or_create → mutate alpha/beta → emit event). `decay_all()` iterates and mutates every record. Multiple concurrent callers can interleave these operations.

Compare to `procedure_store.py` which uses `self._write_lock = threading.Lock()`.

### Finding 2: Six Concurrent Writers, No Coordination (Critical)

These code paths all call `record_outcome()` or directly mutate trust records:

1. **Verification pipeline** (`runtime.py`) — called from `_verify_one()` inside `asyncio.create_task()`
2. **QA smoke tests** (`runtime.py`) — iterates over every healthy agent per test
3. **Proactive cognitive loop** (`proactive.py`) — background `asyncio.Task`
4. **Ward Room endorsements** (`ward_room_router.py`) — triggered by social interactions
5. **Feedback system** (`cognitive/feedback.py`) — user feedback triggers trust writes
6. **Dream consolidation** (`cognitive/dreaming.py`) — **bypasses `record_outcome()` entirely**, directly mutates `record.alpha` and `record.beta`

### Finding 3: DELETE-then-INSERT Save Without Transaction (Critical)
**File:** `src/probos/consensus/trust.py`, `_save_to_db()` method

The save method does `DELETE FROM trust_scores` then inserts all records one by one, then commits. These are NOT wrapped in an explicit transaction. If in-memory state is mutated between DELETE and commit, the save captures a partially-mutated state. If the process crashes between DELETE and commit, all trust data is lost.

### Finding 4: No WAL Mode, No Busy Timeout (High)
**File:** `src/probos/consensus/trust.py`, `start()` method

The trust database is opened with only `PRAGMA foreign_keys = ON`. No WAL mode (`PRAGMA journal_mode=WAL`) and no busy timeout (`PRAGMA busy_timeout`). In default rollback journal mode, any write locks the entire database file. Without busy_timeout, SQLite immediately raises SQLITE_BUSY instead of retrying.

Compare to `procedure_store.py` which sets WAL mode.

### Finding 5: Periodic Flush / Shutdown Race (High)
**Files:** `dream_adapter.py` `periodic_flush_loop()`, `startup/shutdown.py`

The periodic flush runs every 60 seconds. During shutdown:
1. Flush task is cancelled
2. `store_trust_snapshot()` reads in-memory state and writes to KnowledgeStore
3. `trust_network.stop()` triggers `_save_to_db()` to SQLite

If the flush cancellation hasn't fully propagated before shutdown writes begin, both paths write simultaneously.

### Finding 6: Dream Consolidation Races With Request Processing (High)
**File:** `src/probos/cognitive/dreaming.py`, `_consolidate_trust()` method

Dream cycle runs as a background `asyncio.Task`. During a dream:
- `_prune_weights()` calls `self.router.decay_all()` mutating all Hebbian weights
- `_consolidate_trust()` directly mutates trust records' alpha/beta

Meanwhile, the main request processing loop is concurrently calling `record_outcome()` via verification, proactive loop, Ward Room, and feedback. The `_is_dreaming` flag only prevents overlapping dream cycles; it does NOT block other callers.

---

## Implementation

### Part 1: Add asyncio.Lock to TrustNetwork

In `src/probos/consensus/trust.py`:

1. Add `self._lock = asyncio.Lock()` in `__init__()`.

2. Wrap the mutation section of `record_outcome()` in `async with self._lock:`. The lock must cover:
   - `get_or_create(agent_id)`
   - The alpha/beta mutation
   - The score calculation
   - The `_records` dict write

   The event emission (`emit()`) should happen OUTSIDE the lock to avoid holding it during async I/O.

3. Wrap `decay_all()` in `async with self._lock:`. The entire iteration over `_records.values()` must be atomic.

4. Wrap `_save_to_db()` in `async with self._lock:`. Ensures the in-memory snapshot is consistent during the save.

5. Wrap `_load_from_db()` in `async with self._lock:`. Ensures loading doesn't race with writes.

6. Wrap `get_or_create()` — when it creates a new record and inserts into `_records`, this must be under the lock. Note: callers that already hold the lock (like `record_outcome()`) should call an internal `_get_or_create()` to avoid deadlock. Use a re-entrant pattern or split into locked/unlocked variants.

**Design note:** Since TrustNetwork methods are `async`, use `asyncio.Lock()` not `threading.Lock()`. All callers run in the same event loop. The lock is lightweight since the critical section is just dict mutation (no I/O except the save path).

### Part 2: Explicit Transaction in `_save_to_db()`

In `src/probos/consensus/trust.py`, `_save_to_db()`:

```python
async def _save_to_db(self) -> None:
    if not self._db:
        return
    now = datetime.now(timezone.utc).isoformat()
    async with self._lock:
        await self._db.execute("BEGIN IMMEDIATE")
        try:
            await self._db.execute("DELETE FROM trust_scores")
            for record in self._records.values():
                await self._db.execute(
                    "INSERT INTO trust_scores (agent_id, alpha, beta, updated) "
                    "VALUES (?, ?, ?, ?)",
                    (record.agent_id, record.alpha, record.beta, now),
                )
            await self._db.commit()
        except Exception:
            await self._db.execute("ROLLBACK")
            raise
```

Use `BEGIN IMMEDIATE` to acquire a write lock upfront rather than upgrading from a read lock mid-transaction (avoids SQLITE_BUSY on upgrade).

### Part 3: Add WAL Mode and Busy Timeout

In `src/probos/consensus/trust.py`, `start()` method, after opening the connection:

```python
await self._db.execute("PRAGMA journal_mode=WAL")
await self._db.execute("PRAGMA busy_timeout=5000")
await self._db.execute("PRAGMA foreign_keys = ON")
```

WAL mode allows concurrent readers during writes. busy_timeout=5000 gives SQLite 5 seconds to retry on lock contention before raising SQLITE_BUSY.

### Part 4: Route Dream Consolidation Through `record_outcome()`

In `src/probos/cognitive/dreaming.py`, `_consolidate_trust()`:

Currently the code does:
```python
record = self.trust_network.get_or_create(agent_id)
record.alpha += self.config.trust_boost
```

Replace with:
```python
await self.trust_network.record_outcome(
    agent_id,
    success=True,
    weight=self.config.trust_boost,
    source="dream_consolidation",
)
```

This ensures:
- The write goes through the lock
- A TrustEvent is logged
- Events are emitted (Counselor and EmergentDetector can see dream trust changes)
- AD-558 dampening will apply when implemented

**Important:** `record_outcome()` currently has a `source` parameter? Check the signature. If not, add an optional `source: str = "verification"` parameter so dream consolidation vs. normal verification can be distinguished in event logs. If `record_outcome()` doesn't accept `source`, add it as an optional parameter with a default.

Check the current signature of `record_outcome()` and adapt accordingly. The key requirement is: dream trust consolidation MUST go through `record_outcome()`, not directly mutate alpha/beta.

Do the same for the negative consolidation path if one exists (check for `record.beta +=` in the dream code).

### Part 5: Fix Shutdown Race

In `src/probos/startup/shutdown.py`:

After cancelling the periodic flush task, `await` it with a try/except to ensure cancellation completes before proceeding:

```python
flush_task.cancel()
try:
    await flush_task
except asyncio.CancelledError:
    pass
# NOW safe to do trust writes
```

If this pattern isn't already in place, add it. The key is: no trust writes (snapshot or save) until the flush task is confirmed dead.

### Part 6: Apply Same WAL/Busy Timeout Pattern to Hebbian Router

In `src/probos/mesh/routing.py`:

The Hebbian router has the same DELETE-all/INSERT-all save pattern. Apply the same fixes:
1. Add WAL mode and busy_timeout PRAGMAs in its `start()` / initialization
2. Wrap its save method in an explicit transaction with `BEGIN IMMEDIATE`

This is a secondary fix — the trust engine is the priority — but since the same pattern exists, fix both while we're here.

---

## Tests

### File: `tests/test_trust_concurrency.py` (NEW — 15-20 tests)

```
test_record_outcome_concurrent_writes_no_lost_updates
    - Launch 10 concurrent record_outcome() calls for the same agent
    - Verify final alpha + beta equals expected sum (no lost updates)

test_record_outcome_concurrent_different_agents
    - Launch concurrent record_outcome() for 5 different agents
    - Verify all 5 records exist with correct values

test_decay_all_doesnt_race_with_record_outcome
    - Launch record_outcome() and decay_all() concurrently
    - Verify no exception and records are in valid state

test_save_to_db_transaction_atomicity
    - Call _save_to_db() and verify records are either all present or all absent
    - No partial state

test_save_to_db_uses_begin_immediate
    - Mock or spy on db.execute to verify BEGIN IMMEDIATE is called before DELETE

test_save_to_db_rollback_on_error
    - Inject an error during INSERT
    - Verify ROLLBACK is called and original data survives

test_wal_mode_enabled
    - After start(), query PRAGMA journal_mode and assert 'wal'

test_busy_timeout_set
    - After start(), query PRAGMA busy_timeout and assert >= 5000

test_dream_consolidation_uses_record_outcome
    - Run _consolidate_trust() and verify record_outcome() was called
    - Verify TrustEvent was logged (not a direct alpha/beta mutation)

test_dream_consolidation_emits_trust_update_event
    - Run _consolidate_trust() and verify TRUST_UPDATE event was emitted

test_concurrent_dream_and_verification
    - Launch _consolidate_trust() and record_outcome() concurrently
    - Verify no exception and valid final state

test_shutdown_waits_for_flush_cancellation
    - Verify shutdown sequence awaits flush task before writing trust

test_get_or_create_under_lock
    - Concurrent get_or_create() for same agent_id
    - Verify only one record created (no duplicate)

test_lock_not_held_during_event_emission
    - Verify record_outcome() releases lock before emitting events
    - (Test that a second record_outcome() can proceed while event handlers run)

test_hebbian_router_wal_mode
    - After routing.start(), verify WAL mode is enabled

test_hebbian_router_transaction_save
    - Verify Hebbian save uses BEGIN IMMEDIATE
```

### Existing test expectations

All existing trust tests should pass unchanged. The lock is transparent to single-threaded test execution. The WAL mode and busy_timeout are additive. The dream consolidation routing through `record_outcome()` changes the code path but the observable result (alpha increases) is the same.

Run the full test suite after implementation to verify no regressions.

---

## Verification Checklist

- [ ] `asyncio.Lock` added to TrustNetwork, used in record_outcome, decay_all, save, load, get_or_create
- [ ] `_save_to_db()` uses `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`
- [ ] `start()` sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`
- [ ] Dream `_consolidate_trust()` calls `record_outcome()` instead of direct mutation
- [ ] Dream trust changes now emit events (check event bus)
- [ ] Shutdown awaits flush task cancellation before trust writes
- [ ] Hebbian router save uses explicit transaction
- [ ] Hebbian router DB uses WAL mode and busy_timeout
- [ ] All new concurrency tests pass
- [ ] Full existing test suite passes with no regressions
- [ ] `record_outcome()` releases lock before event emission (no deadlock risk)

## Scope Boundaries

- Do NOT add dampening, floors, or circuit breakers — that's AD-558
- Do NOT change the trust scoring math (alpha/beta Bayesian model)
- Do NOT change the API surface of `record_outcome()` beyond adding an optional `source` parameter
- Do NOT modify how trust scores are consumed by routing or consensus
- Keep changes minimal and focused on concurrency safety
