# BF-826: a promoted report must run off the loop and say whether it landed

**Issue:** #1290 (already filed, OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**Number:** BF-826 — already allocated, do not mint a new one.
**Related:** BF-733 (#1288, shipped) added a second caller with the same properties. **Not a regression.**

---

## The defect, verified at HEAD (2026-08-22)

`turn_promotion._post_report` is a **synchronous** function doing SQLite work directly on the event
loop, which **cannot tell its caller whether delivery succeeded**:

```
src/probos/cognitive/turn_promotion.py:568   def _post_report(*, runtime, agent_id, thread_id,
                                                  work_item_id, body, tool_failures=None) -> str:
                                  :578-580   """Synchronous on purpose — ChatThreadStore is a
                                              synchronous SQLite store, and its commit callback ..."""
                                  :625       store.append_message(thread_id, ...)      # on the loop
                                  :631-637   except Exception:  logger.warning(...)
                                  :638       return body                               # same as success
```

The store it calls says the opposite in its own docstring:

```
src/probos/threads/__init__.py:233-235
    """SQLite-backed thread + message store.
       All methods synchronous — callers from async code should wrap in
       ``loop.run_in_executor`` per the substrate-store convention."""
```

The Captain measured both consequences against the real `ChatThreadStore`:

| condition | result |
|---|---|
| 350 ms exclusive SQLite lock | call took 375 ms; a 50 ms loop heartbeat was delayed to 437 ms |
| lock held past the 5,000 ms busy timeout | call took **7.406 s**, **returned its body as if delivered**, and the DB contained only the warm-up message |

**Do not re-litigate the premise.** What is *not* established, and must not be claimed: whether the
stall is reachable on the reference vessel under ordinary load. The measurement forced the lock.

### Why the second consequence is the serious one

BF-733 gives the deadline watchdog its own `_post_report` call so a run that refuses cancellation
still produces an interim notice without waiting on concurrency capacity. For a permanently stubborn
run **that notice is the only report the Captain will ever get** — the reporter is still waiting on
the run. A silent loss there is unrecoverable. A lost *final* report at least leaves a row on the board.

---

## The design decision

Three questions, in dependency order. Answer all three in the prompt's own terms before writing code.

### 1. Off the loop — mechanical, not contentious

Wrap the `append_message` call in `run_in_executor` / `asyncio.to_thread`, per the store's own
stated convention. That forces `_post_report` to become `async def`, which is the whole of question 3.

**Preserve the reason the current docstring gives for being synchronous**: the store's commit
callback emits `CHAT_THREAD_MESSAGE_APPENDED`, which the HXI consumes to live-refresh an open
transcript (AD-1133). Moving the call into a worker thread means **that callback now fires on a
non-loop thread.** Verify what the listener chain does with that before assuming it is safe — if it
touches loop-bound state, the emit must be hopped back with `call_soon_threadsafe`. This is the one
place where the obvious fix can quietly break a working feature; check it, do not assume it.

### 2. What a caller should DO with a failed post — this is the actual decision

Apply **Design Principle 13(c): authority routes capability, it does not ration it. A control that
is unavailable should ESCALATE, not silently degrade.**

Two hard constraints on any answer:

- **An error path must not fail the way the thing it reports on failed.** A failed thread post
  cannot be escalated by *posting to a thread*. The AD-857 Captain-DM notifier writes to the same
  `chat_threads.db` and is therefore not a fallback — it is the same lock. Verified: the thread store
  is `data_dir/chat_threads.db` (`runtime.py:618`); the work-item store is `data_dir/workforce.db`
  (`startup/communication.py:276`). **Different files, different locks.** That asymmetry is what
  makes a durable pending record possible at all.
- **If the fix leaves delivery best-effort, stop calling it a report.** A best-effort control is
  telemetry, not a control. The docstring, the log lines and the acceptance criteria must all
  describe the property the code actually provides. Do not ship a function whose name promises
  delivery and whose behaviour promises an attempt.

Recommended shape, to be confirmed or overruled:

1. **Bounded retry off-loop.** A SQLite busy lock is transient by nature, and a retry against a
   *transient* failure is not the same as a retry against a *rejected* one. Bound it explicitly
   (attempts and total wall-clock), and state the bound in the docstring.
2. **On exhaustion, persist the report as pending on the work item's metadata** — a different
   database, so it does not share the failing resource — and log at ERROR, not WARNING. The board
   row then carries the undelivered text and the Captain can be shown it.
3. **Never return a value that reads as delivered when it was not.** See question 3.

**Handed to the Captain — do not decide this unilaterally:** whether a pending report should also
*surface* to the Captain proactively (a notification, a board badge) or whether persisting it on the
row is sufficient for v1. Surfacing it touches the approval-inbox/notification surfaces and is a
larger change than this BF should carry. Recommendation: **persist and log in this BF; file the
surfacing separately.** Say so in the commit rather than implying the loop is closed.

### 3. The signature and return type

`-> str` cannot express two outcomes. Adding a return value to a method that already returns one
value is the smaller half; the shape is the decision.

Return an **inspectable outcome**, not an exception. A delivery guarantee cannot be expressed as an
exception when a caller legitimately absorbs it — and both callers here are inside `try`/`except`
regions whose contract is "never raise apart from cancellation".

Suggested: a small frozen dataclass carrying **the composed body** (`_finish_promoted_turn` reuses it
at `:899` for the episode and the outcome artifact — that reuse is AD-1248's deliberate
"render once per route" and must survive) **plus** whether it was delivered and, if not, why.

**Callers — the complete set, verified:**

| Site | Context | Change |
|---|---|---|
| `turn_promotion.py:899` | `reported = _post_report(...)` inside `async def _finish_promoted_turn` (`:780`) | `await`; `body=reported` at `:932` must keep receiving the **composed text** |
| `turn_promotion.py:1010` | `on_unconfirmed=lambda: _post_report(...)` inside `async def _report_holding_slot` | the lambda must become awaitable |

The second one is the awkward one and is worth reading before you start:

```
turn_promotion.py:280   on_unconfirmed: Callable[[], None] | None = None      # __init__ param
                :285   self._on_unconfirmed = on_unconfirmed
                :364   def _notify_unconfirmed(self) -> None:                 # SYNC method
                :381       self._on_unconfirmed()
                :363   ... called from `async def _enforce`                   # the caller IS async
```

`_notify_unconfirmed` is synchronous, but its only caller (`_enforce`, `:329`) is a coroutine, so an
`await` is reachable — the sync boundary is incidental, not structural. Making `_notify_unconfirmed`
async is the direct route. **Keep its `self._task.done()` recheck and keep its broad `except`** —
both have recorded reasons at `:370-379` and `:382-389`, and the second is what stops a failed
notice from killing the watchdog.

---

## Required tests

New file: `tests/test_bf826_promoted_report_delivery.py`.

1. **Headline, per the issue's own acceptance:** using the **real** `ChatThreadStore` under lock
   contention, prove (a) the event loop keeps making progress while the post is in flight, and
   (b) the report is delivered **exactly once**. A heartbeat task measuring its own scheduling delay
   is the shape that catches (a); an assertion on the store's row count catches (b).
2. **A failed post is distinguishable from a delivered one.** Hold the lock past the busy timeout
   and assert the caller receives a not-delivered outcome — and that the composed body is still
   returned so the episode and artifact are unaffected.
3. **The pending report is durable and lands on a different resource.** Assert it is readable from
   the work item after the thread store has failed.
4. **Exactly-once under retry.** A post that succeeds on attempt 2 must leave **one** row, not two.
   This is the assertion that catches a retry loop layered over a partially-succeeded write.
5. **The watchdog path.** Drive `_notify_unconfirmed` through `_enforce` with a failing store and
   assert the watchdog still completes and still cancels the run — a failed notice must not take out
   the supervision. Assert a positive premise beside it (the notice was actually attempted), or the
   test passes because nothing ran.
6. **Wording is time-scoped.** Per the issue: where delivery can lag the observation it describes,
   the text must say so ("At the deadline…"). Assert on `_REPORT_ABANDON_UNCONFIRMED` (`:148`).

### Mutation check (required)

Revert the off-loop hop, the outcome return, and the retry independently; confirm a named test
reddens for each. A test that asserts on `obs[...]`-style intermediate state rather than on what the
caller actually receives will survive all three — if a mutant survives, suspect the test before
congratulating the fix.

---

## Test blast radius — enumerated, not estimated

`_post_report` becoming `async` and changing its return type breaks every direct caller in the suite:

| File | Lines | What breaks |
|---|---|---|
| `tests/test_ad1248_slice_a_gaps.py` | `:52, :67, :81, :283, :309` | five **synchronous** calls; each test must become async and `await`. `:286` asserts `reported == store.appended[0]["body"]` — repoint to the outcome's body field. |
| `tests/test_ad1248_slice_a_gaps.py` | **`:300`** | **`assert "reported = _post_report(" in source`** — a source scan that pins the SYNC call shape as contract. |
| `tests/test_bf732_promoted_run_slot.py` | `:52` | comment only (`thread_id="" -> _post_report is a no-op`); update the prose if the behaviour moves. |

**`:300` is the dangerous one.** It is a `getsource` assertion and it cannot distinguish "this line
is required" from "this line is what shipped". **Update it — invert to the new shape and record the
reason inline. Never delete it.** Better: replace it with the behavioural claim it is standing in
for (that the episode receives the composed text, which `:301` already asserts properly), and say in
the docstring why the structural half was dropped.

---

## Do not build

- **Do not make `ChatThreadStore` async.** Seven other subsystems call it synchronously; that is a
  different and much larger change. Wrap at this call site only.
- **Do not add a general async outbox / delivery-queue subsystem.** A reviewer proposing one is the
  signal to file it, not to build it inside a BF.
- **Do not touch `_store_promoted_episode`, `_open_work_item`, or the AD-1248 disclosure composition**
  beyond threading the new return type through.
- **Do not change the terminal `transition_work_item` call at `:957`** or its warning text — it
  already names BF-825/#1289 and that cross-reference stays accurate.
- **Do not fix BF-825 here.** The reconciler stranding a live promoted row is #1289 and has its own
  prompt. These two are adjacent and it is tempting to solve both with one heartbeat; do not.
- **Do not surface pending reports in the HXI or the notification queue** in this BF — see the
  handback in question 2.
- **Do not change `_REPORT_FAILED` / `_REPORT_EMPTY` / `_REPORT_ABANDONED` wording** except where
  acceptance item 6 requires time-scoping.

---

## Acceptance criteria

- Thread-store writes on the promoted-report path do not run on the event loop, proven by a
  heartbeat measurement under real lock contention.
- A caller can tell whether a report was delivered; a failed one is retried within a stated bound and,
  on exhaustion, preserved durably on a resource that is not the one that failed.
- The composed body is still returned and still reused by the episode and the outcome artifact
  (AD-1248's "render once per route" is preserved).
- Delivery is exactly-once across the retry path.
- The `CHAT_THREAD_MESSAGE_APPENDED` emit still reaches the HXI listener chain correctly from a
  worker thread — verified, not assumed.
- Every docstring, log line and comment describes the property the code provides. If delivery
  remains best-effort in any branch, that branch says so.
- Wording is time-scoped wherever delivery can lag the observation.
- Both `_post_report` call sites updated; all 5 direct test call sites updated; the `:300` source
  scan updated with its reason recorded inline.
- Focused gate: `pytest tests/test_bf826_*.py tests/test_ad1248_slice_a_gaps.py tests/test_bf733_*.py tests/test_bf732_*.py tests/test_ad1165_*.py -q -n 0`
- Then one consolidated gate: `pytest tests/ -q -n 16 --dist=loadfile`
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code.

---

## Verified Against Codebase (2026-08-22)

```
grep -n "def _post_report\|_post_report(" src/probos/cognitive/turn_promotion.py
  568:  def _post_report(                                        # SYNC
  899:  reported = _post_report(                                 # in async _finish_promoted_turn (:780)
  1010: on_unconfirmed=lambda: _post_report(                     # in async _report_holding_slot

turn_promotion.py:625   store.append_message(thread_id, ...)     # on the loop, inside try
                :631    except Exception: logger.warning(...)
                :638    return body                              # identical to the success return

threads/__init__.py:233-235  "All methods synchronous — callers from async code should wrap in
                              ``loop.run_in_executor`` per the substrate-store convention."

turn_promotion.py:280   on_unconfirmed: Callable[[], None] | None = None
                :364    def _notify_unconfirmed(self) -> None:   # sync, but
                :363    ... called from `async def _enforce` (:329)   -> an await is reachable

runtime.py:618                 ChatThreadStore(db_path=self._data_dir / "chat_threads.db")
startup/communication.py:276   WorkItemStore(db_path=str(data_dir / "workforce.db"))
  -> distinct SQLite files, distinct locks

grep -n "_post_report" tests/*.py
  test_ad1248_slice_a_gaps.py:52,67,81,283,309   direct SYNC calls
  test_ad1248_slice_a_gaps.py:300                assert "reported = _post_report(" in source
  test_bf732_promoted_run_slot.py:52             comment only
```
