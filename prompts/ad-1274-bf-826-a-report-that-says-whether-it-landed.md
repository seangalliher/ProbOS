# AD-1274 / BF-826: a report that can say whether it landed

**Issue:** #1290 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1274 — newly minted, ceiling was AD-1272 (AD-1273 taken by BF-823). **BF:** BF-826 — already allocated.
**Supersedes:** `prompts/bf-826-promoted-report-delivery.md` — its line anchors are ~2 lines stale, it
leaves all three design questions open, and it predates the two issue comments of 2026-08-22 21:43/21:47
that measured the obvious fix breaking the HXI. **Archive that file as part of this build.**
**Status:** ready to build · **Estimated tests:** 12–16 across two slices

---

## The defect, verified at HEAD (2026-08-26)

```
src/probos/cognitive/turn_promotion.py:570   def _post_report(*, runtime, agent_id, thread_id,
                                                  work_item_id, body, tool_failures=None) -> str:
                                  :580-583   """Synchronous on purpose — ChatThreadStore is a
                                              synchronous SQLite store, and its commit callback is
                                              what emits CHAT_THREAD_MESSAGE_APPENDED ... (AD-1133)"""
                                  :623       store.append_message(thread_id, ...)   # on the event loop
                                  :629-635   except Exception: logger.warning(...)
                                  :636       return body                            # identical to :621 success
```

Two call sites, both verified:

| Site | Context |
|---|---|
| `turn_promotion.py:901` | `reported = _post_report(...)` in `async def _finish_promoted_turn` (`:782`) |
| `turn_promotion.py:1012` | `on_unconfirmed=lambda: _post_report(...)` in `async def _report_holding_slot` — the BF-733 deadline watchdog |

Measured by the Captain against the real `ChatThreadStore`: a 350 ms exclusive lock delayed a 50 ms
loop heartbeat to 437 ms; past the 5 s busy timeout the call took 7.406 s, **returned its body as if
delivered**, and the database held only the warm-up message.

**Do not re-litigate the premise. Do not claim the stall is reachable under ordinary load** — the
measurement forced the lock, and the issue says so explicitly.

### Why the watchdog caller is the serious one

For a run that refuses its cancellation, the interim notice is **the only report the Captain will
ever get** — the reporter is still waiting on the run. A silent loss there is unrecoverable. A lost
*final* report at least leaves a row on the board.

---

## The three decisions, made

The superseded prompt handed these to the builder. They are decided here. Overrule any of them only
with measurement, and record the measurement.

### Decision 1 — the callback hop is a PREREQUISITE, not scope creep

Wrapping `append_message` in an executor makes `ChatThreadStore`'s commit callback fire on a worker
thread. That callback is `_emit_chat_thread_message_appended` (`runtime.py:1236`, registered at
`:1296-1298`), which calls `emit_event` → `_emit_event` (`:1703`) → `_emit_event_local` (`:1742`).

**Both routing branches need a running loop in the calling thread:**

```
runtime.py:1728   loop = asyncio.get_running_loop()          # NATS branch
        :1729-32  except RuntimeError: warn + fall back to local
        :1749     task = asyncio.create_task(fn(event))      # coroutine listener   -> inside except Exception
        :1769     task = asyncio.create_task(result)         # awaitable live token -> inside except Exception
        :1751-57  except Exception: logger.warning(...)      # drops the event
```

Measured by the Captain: from a worker thread, a **sync** listener runs on `asyncio_0`; a
**coroutine** listener is **silently lost** (`RuntimeError: no running event loop`, swallowed). The
HXI live-refresh path is a live-listener token returning an awaitable — it is in the lost set.

**Build:** `ProbOSRuntime._emit_from_any_thread(event, data)`. Try `asyncio.get_running_loop()`; on
`RuntimeError`, hand the emit to a loop captured in `start()` (`runtime.py:2427`) via
`loop.call_soon_threadsafe(self.emit_event, ...)`. Point `_emit_chat_thread_message_appended` at it.

Three constraints, each from the Captain's verified-then-reverted implementation:

- **Capture the loop in `start()`, not `__init__`.** The constructor is synchronous and may run with
  no loop at all. Verified absence — there is no such attribute today:
  `rg -n "self\._loop|_dispatch_loop" src/probos/runtime.py` returns nothing.
- **With no captured loop, degrade with a warning — never raise.** Otherwise a store write fails
  because a *notification* could not be scheduled.
- **`call_soon_threadsafe` can itself raise `RuntimeError`** if the loop closes between the liveness
  check and the call. Catch it.

**This hop must land in the same commit as the executor move that consumes it.** Verified: **zero**
`append_message` call sites are currently off-loop —

```
rg -n "append_message" src/    # 20 call sites; every one a direct synchronous call
```

Shipped alone the hop guards a path nothing takes, and worse, makes the seam *look* closed so the
next person to move a write off-loop assumes it was already safe.

`_emit_artifact_version_added` (`runtime.py:1268`) has the identical shape and is **not** reached by
this change. Leave it. Note it in the commit.

### Decision 2 — durable-pending lives in `workforce.db`, modelled on the existing outbox

An error path must not fail the way the thing it reports on failed. The AD-857 Captain-DM notifier
writes to the same `chat_threads.db` and is therefore **not** a fallback — same file, same lock.

```
runtime.py:621                 ChatThreadStore(db_path=self._data_dir / "chat_threads.db")
startup/communication.py:277   WorkItemStore(db_path=str(data_dir / "workforce.db"))
```

Different files, different locks. That asymmetry is what makes durable pending possible.

**The pattern already exists in this repo — do not invent one.** `WorkItemStore` already carries a
transactional outbox with a bounded drainer:

```
workforce.py:1116-1127   CREATE TABLE crew_delivery_outbox (delivery_id PK, ..., delivered, created_at, delivered_at)
workforce.py:1139-1140   CREATE INDEX idx_crew_delivery_outbox_pending ON (delivered, created_at, delivery_id)
workforce.py:4036        list_pending_crew_session_deliveries(*, limit, ...)
workforce.py:4146        mark_crew_session_delivery_delivered(...)
crew_session_delivery.py:535-640   drain_pending(): bounded batch, per-row try, leave pending on failure
crew_session_delivery.py:571-575   await asyncio.to_thread(self._threads.get_thread, ...)   # the off-loop idiom, already in use
```

**Add a sibling table `promoted_report_outbox`, not a reuse of `crew_delivery_outbox`.** The
existing table is session-shaped — `UNIQUE (session_id, session_revision, outcome)` and its drainer
validates `thread.task_id == record.session_id` (`crew_session_delivery.py:592-596`). A promoted
report has a work item, not a session revision. Forcing it in corrupts the uniqueness semantics for
crew sessions, which are load-bearing elsewhere.

**Why not work-item metadata?** `merge_work_item_metadata` (`workforce.py:3245`) would persist the
text, but there is no pending index and no drainer, so nothing ever redelivers. That satisfies
"preserved" and fails "retried" — and the issue's acceptance says *"retried or preserved as durably
pending"*, where pending means something eventually drains it. Metadata alone is a durable grave.

### Decision 3 — exactly-once comes free, via `append_message_once`

This is the decisive finding and it removes the hardest part of the problem.

```
threads/__init__.py:1262   def append_message(...)  ->  delegates to:
                   :1271       self.append_message_once(..., message_id=self._id_factory(), ...)
                   :1281   def append_message_once(self, thread_id, *, message_id, ..., created_at, ...)
                   :1329+      existing = SELECT * FROM chat_thread_messages WHERE id = ?
                               if existing is not None:  -> exact-match check, returns without inserting
```

**Mint the `message_id` and `created_at` when the outbox row is written, store them in the row, and
have every delivery attempt — first try and every redelivery — call `append_message_once` with
them.** An at-least-once drain becomes exactly-once delivery with no new mechanism and no
distributed-transaction hand-wringing.

Without this, a retry layered over a write that *committed but whose acknowledgement was lost*
double-posts, and the Captain sees the same report twice. Test 4 below exists to catch precisely
that.

### The return type

`-> str` cannot express two outcomes. Return a small **frozen dataclass** carrying:

- **the composed body** — `_finish_promoted_turn` reuses it at `:932` (`body=reported`) for the
  episode and the outcome artifact. That reuse is AD-1248's deliberate *"render once per route"* and
  **must survive byte-identical**;
- whether it was delivered;
- if not, why, and whether it was durably queued.

Not an exception: both callers sit inside `try`/`except` regions whose contract is *"never raises
apart from cancellation"*, so a caller legitimately absorbing it must still be able to inspect it.

### The awkward caller

```
turn_promotion.py:282   on_unconfirmed: Callable[[], None] | None = None    # __init__ param
                :287    self._on_unconfirmed = on_unconfirmed
                :366    def _notify_unconfirmed(self) -> None:              # SYNC
                :383        self._on_unconfirmed()
                :363    ... called from `async def _enforce` (:313)         # the caller IS async
```

The sync boundary is incidental, not structural — an `await` is reachable. Make `_notify_unconfirmed`
async and await it from `_enforce`. **Keep its `self._task.done()` recheck (`:380`) and its broad
`except` (`:384-390`)** — both have recorded reasons in the docstring at `:367-378`, and the second
is what stops a failed notice from killing the watchdog.

### One trap that is NOT present — verified, so do not defend against it

`ChatThreadStore._connect()` opens a **fresh** `sqlite3.connect` per call
(`threads/__init__.py:255-256`, `isolation_level=None`). There is no shared connection and therefore
no `check_same_thread` affinity problem. `run_in_executor` is safe here. Do not add a connection
lock, a thread-local, or a `check_same_thread=False` flag — each would be a change to a store seven
other subsystems depend on, bought against a problem that does not exist.

---

## Slice A — off the loop, and honest (shippable on its own)

1. `_emit_from_any_thread` + loop capture in `start()` + repoint the chat callback.
2. `_post_report` → `async def`; the write goes through `asyncio.to_thread` /
   `loop.run_in_executor`; mint `message_id` + `created_at` and call `append_message_once`.
3. Bounded retry against the transient busy lock. **State the bound (attempts and total wall-clock)
   in the docstring.** A retry against a transient failure is not a retry against a rejection —
   `ValueError("chat_thread_message_invalid")` from `append_message_once`'s validation is a
   rejection and must not be retried.
4. Return the outcome dataclass. Update both call sites; `body=reported` at `:932` keeps receiving
   the composed text.
5. On exhaustion: log at **ERROR**, not WARNING, and return not-delivered. No new table yet.

**Slice A does not close #1290.** It closes the loop stall and the silent success. A permanently
failed watchdog notice is still lost — which is the unrecoverable case. Say so in the commit; do not
imply the loop is closed.

## Slice B — durably pending

6. `promoted_report_outbox` table + `list_pending_promoted_reports` / `mark_promoted_report_delivered`
   on `WorkItemStore`, mirroring `workforce.py:4036` / `:4146` including the bounded-limit
   validation shape.
7. A drainer mirroring `crew_session_delivery.py:535-640`: bounded batch, per-row `try`, a row that
   fails **stays pending**, and a backlog exceeding the bound logs and defers.
8. Drive it from startup and from the same trigger points the crew delivery service uses.
9. `_post_report` writes the pending row on retry exhaustion, carrying the already-minted
   `message_id` so the drain is exactly-once.

---

## Required tests

New files: `tests/test_ad1274_report_off_loop.py` (Slice A), `tests/test_ad1274_report_outbox.py` (Slice B).

1. **The headline, per the issue's acceptance.** With the **real** `ChatThreadStore` under lock
   contention, prove (a) a heartbeat task keeps meeting its schedule while the post is in flight,
   and (b) the report lands **exactly once**. Assert the heartbeat's own premise — that it recorded
   a plausible number of ticks — or a heartbeat that never ran passes trivially.
2. **The AD-1133 emit survives the worker thread.** A **coroutine** listener registered on
   `CHAT_THREAD_MESSAGE_APPENDED` must be invoked when the append happens off-loop. This is the
   regression the Captain measured; without this test the fix silently reintroduces it. Assert the
   listener ran **on the loop thread**, not merely that it ran.
3. **No captured loop degrades, does not raise.** Construct the emit path with no dispatch loop;
   assert a warning and no exception, and that the store write still succeeded.
4. **Exactly-once under retry.** A post that fails on attempt 1 *after committing* and succeeds on
   attempt 2 must leave **one** row. Drive it through `append_message_once` with a fixed
   `message_id`; assert the row count, not the return value.
5. **A rejection is not retried.** Feed `append_message_once` an input its validation rejects; assert
   exactly one attempt.
6. **A failed post is distinguishable.** Hold the lock past the busy timeout; assert the caller
   receives a not-delivered outcome **and** that the composed body is still returned so the episode
   and artifact are unaffected.
7. **The watchdog path.** Drive `_notify_unconfirmed` through `_enforce` with a failing store; assert
   the watchdog still completes and still cancels the run, and assert the positive premise that the
   notice was actually attempted.
8. **Wording is time-scoped** (issue acceptance). Assert on `_REPORT_ABANDON_UNCONFIRMED`
   (`turn_promotion.py:150`).
9. **Slice B: the pending row is durable and on a different resource.** Readable from
   `workforce.db` after `chat_threads.db` has failed.
10. **Slice B: the drain delivers it, once.** Drain twice; assert one row in the thread.

### Mutation check (required)

Revert independently: (a) the executor hop, (b) `_emit_from_any_thread`, (c) the outcome return type,
(d) the retry bound, (e) the fixed `message_id`. Confirm a **named** test reddens for each. A test
asserting on intermediate state rather than on what the caller receives will survive (c). Re-derive
anchors after each repair round.

---

## Test blast radius — enumerated, verified 2026-08-26

| File | Lines | What breaks |
|---|---|---|
| `tests/test_ad1248_slice_a_gaps.py` | `:52, :67, :81, :283, :309` | five **synchronous** `_post_report(...)` calls; each test becomes async and awaits |
| `tests/test_ad1248_slice_a_gaps.py` | `:286` | asserts `reported == store.appended[0]["body"]` — repoint to the outcome's body field |
| `tests/test_ad1248_slice_a_gaps.py` | **`:300`** | **`assert "reported = _post_report(" in source`** |
| `tests/test_bf732_promoted_run_slot.py` | `:52` | comment only (`thread_id="" -> _post_report is a no-op`); update the prose |

**`:300` is the dangerous one.** It is a `getsource` scan and it cannot distinguish *"this line is
required"* from *"this line is what shipped"* — it pins the synchronous call shape as contract.
**Update it to the new shape and record the reason inline. Never delete it.** Better: replace it
with the behavioural claim it stands in for — that the episode receives the composed text, which
`:301` already asserts properly — and say in the docstring why the structural half was dropped.

---

## Do not build

- **Do not make `ChatThreadStore` async.** Twenty call sites across nine modules call it
  synchronously. Wrap at this call site only.
- **Do not move any other `append_message` call off-loop in this AD.** The hop makes it *safe* to;
  that is not permission to. Each is its own change with its own consumer.
- **Do not add a connection lock, thread-local, or `check_same_thread=False`** — see the verified
  non-trap above.
- **Do not reuse `crew_delivery_outbox`** or widen its `UNIQUE` constraint. See Decision 2.
- **Do not build a general async outbox subsystem or a delivery abstraction over both tables.** A
  reviewer proposing one is the signal to file it, not to build it inside a BF.
- **Do not touch `_emit_artifact_version_added`** (`runtime.py:1268`). Identical shape, not reached.
- **Do not surface pending reports in the HXI or the notification queue.** File it separately;
  it touches the approval-inbox surfaces and is larger than this BF.
- **Do not touch `_store_promoted_episode`, `_store_outcome_artifact`, or the AD-1248 disclosure
  composition** beyond threading the new return type through.
- **Do not change the terminal `transition_work_item` call** or its warning text — it already names
  BF-825/#1289 and that cross-reference stays accurate.
- **Do not fix BF-825 here.** Adjacent, tempting to solve with one heartbeat. Do not.
- **Do not change `_REPORT_FAILED` / `_REPORT_EMPTY` / `_REPORT_ABANDONED`** except where test 8
  requires time-scoping.

---

## Tracking

- `PROGRESS.md` — AD-1274 entry; BF-826 CLOSED only when Slice B lands.
- `docs/development/roadmap.md` Bug Tracker — BF-826 row.
- `DECISIONS.md` — AD-1274: a store callback that can fire off-loop must hop its emit back; a
  delivery that can fail must be inspectable and durably pending.
- Archive `prompts/bf-826-promoted-report-delivery.md` to `prompts/archive/` in the same commit,
  with a one-line note that this file supersedes it.

---

## Acceptance criteria

- Thread-store writes on the promoted-report path do not run on the event loop, proven by a
  heartbeat measurement under real lock contention.
- The `CHAT_THREAD_MESSAGE_APPENDED` emit reaches a **coroutine** listener when the append happens
  off-loop, and that listener runs on the loop thread — verified by test, not assumed.
- A caller can tell whether a report was delivered; a failed one is retried within a stated bound
  and, on exhaustion, preserved durably in `workforce.db`, which is not the resource that failed.
- Delivery is exactly-once across first attempt, retry, and outbox redelivery.
- The composed body is still returned and still reused by the episode and outcome artifact —
  AD-1248's "render once per route" preserved.
- Every docstring, log line and comment describes the property the code provides. If any branch
  remains best-effort, that branch says so — and it is not called a report.
- Wording is time-scoped wherever delivery can lag the observation it describes.
- Both `_post_report` call sites updated; all five direct test call sites updated; the `:300` source
  scan updated with its reason recorded inline.
- Focused gate: `pytest tests/test_ad1274_*.py tests/test_ad1248_slice_a_gaps.py tests/test_bf733_*.py tests/test_bf732_*.py tests/test_ad1165_*.py tests/test_ad1133_*.py -q -n 0`
- Then one consolidated gate for the frozen slice: `pytest tests/ -q -n 16 --dist=loadfile`
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code.
  Tell it the consumer that must accept the change is *an HXI client with an open transcript*.

---

## Verified Against Codebase (2026-08-26)

```
grep -n "def _post_report\|_post_report(\|store.append_message\|return body" src/probos/cognitive/turn_promotion.py
  570: def _post_report(                                   # SYNC, -> str
  621: return body                                         # store is None branch
  623: store.append_message(                               # on the loop, inside try
  636: return body                                         # identical to the success return
  901: reported = _post_report(                            # in async _finish_promoted_turn (:782)
  932: body=reported,                                      # AD-1248 reuse -- must survive
 1012: on_unconfirmed=lambda: _post_report(                # in async _report_holding_slot

grep -n "on_unconfirmed\|_notify_unconfirmed\|async def _enforce\|_REPORT_ABANDON_UNCONFIRMED" src/probos/cognitive/turn_promotion.py
  150: _REPORT_ABANDON_UNCONFIRMED: str = (
  282: on_unconfirmed: Callable[[], None] | None = None
  313: async def _enforce(self) -> None:                    # caller IS async -> await is reachable
  363: self._notify_unconfirmed()
  366: def _notify_unconfirmed(self) -> None:               # SYNC
  380: if self._on_unconfirmed is None or self._task.done():
  383: self._on_unconfirmed()

grep -n "_emit_chat_thread_message_appended\|get_running_loop\|create_task(fn(event))\|set_message_committed_callback" src/probos/runtime.py
 1236: def _emit_chat_thread_message_appended(message) -> None:
 1258:     self.emit_event(EventType.CHAT_THREAD_MESSAGE_APPENDED, {...})
 1296: self.chat_thread_store.set_message_committed_callback(_emit_chat_thread_message_appended)
 1703: def _emit_event(...)
 1728:     loop = asyncio.get_running_loop()                # NATS branch
 1742: def _emit_event_local(...)
 1749:     task = asyncio.create_task(fn(event))            # coroutine listener -> lost off-loop
 1769:     task = asyncio.create_task(result)               # awaitable token   -> lost off-loop
 2427: async def start(self) -> None:                       # where the loop must be captured

ABSENCE VERIFIED — no loop is captured on the runtime today:
  rg -n "self\._loop|_dispatch_loop" src/probos/runtime.py     -> no matches

ABSENCE VERIFIED — nothing calls append_message off-loop today (20 sites, all direct):
  rg -n "append_message" src/
    proactive.py:4563 · cognitive_agent.py:1980,2046 · turn_promotion.py:623
    routers/agents.py:2769,2776,2829,3464 · routers/chat.py:174,283,436,443,494,531,665,677
    routers/thread_fanout.py:741 · routers/threads.py:579 · startup/finalize.py:2701
    threads/agent_group_chat.py:227 · crew_executor.py:2522 (append_message_once)

grep -n "def append_message\|def append_message_once\|def _connect\|sqlite3.connect" src/probos/threads/__init__.py
  255-256: def _connect(...): conn = sqlite3.connect(str(self._db_path), isolation_level=None)   # FRESH per call
  1262: def append_message(...)      -> delegates with self._id_factory()
  1281: def append_message_once(self, thread_id, *, message_id, ..., created_at, ...)
        -> caller-supplied id; existing exact match returns without inserting  == exactly-once primitive

grep -n "crew_delivery_outbox\|list_pending_crew_session_deliveries\|mark_crew_session_delivery_delivered\|merge_work_item_metadata" src/probos/workforce.py
 1116: CREATE TABLE IF NOT EXISTS crew_delivery_outbox (
 1126:     UNIQUE (session_id, session_revision, outcome)   # session-shaped -> do not reuse
 1139: CREATE INDEX idx_crew_delivery_outbox_pending ON (delivered, created_at, delivery_id)
 3245: async def merge_work_item_metadata(...)              # persists, but no pending index / no drainer
 4036: async def list_pending_crew_session_deliveries(*, limit, ...)
 4146: async def mark_crew_session_delivery_delivered(...)

grep -n "drain_pending\|to_thread" src/probos/crew_session_delivery.py
  535: async def drain_pending(...)                          # the model for the new drainer
  557:     entries = await self._outbox.list_pending_crew_session_deliveries(limit=bounded_limit + 1, ...)
  571:     thread = await asyncio.to_thread(self._threads.get_thread, record.thread_id)   # off-loop idiom in use
  614:     mark_result = await self._outbox.mark_crew_session_delivery_delivered(...)

DB path asymmetry:
  runtime.py:621                ChatThreadStore(db_path=self._data_dir / "chat_threads.db")
  startup/communication.py:277  WorkItemStore(db_path=str(data_dir / "workforce.db"))

grep -n "_post_report" tests/*.py
  test_ad1248_slice_a_gaps.py:52,67,81,283,309   direct SYNC calls
  test_ad1248_slice_a_gaps.py:300                assert "reported = _post_report(" in source
  test_bf732_promoted_run_slot.py:52             comment only
```
