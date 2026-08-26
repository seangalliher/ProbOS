# AD-1251: remove the watch-order machinery; `OrderManager` is where orders live

**Issues:** #1282 (BF-818) · **closes as removed-not-fixed:** #1278 (BF-814) · **Repo:** OSS, branch `main`, base `b4acdbfe`

## The decision, made

**Delete.** Not "add the producer".

This is the one item in the parked set where the product call is unambiguous, and the reason is
that deleting it **removes no Captain capability**. Design Principle 13(a) says a capability
ceiling must be a decision rather than an inheritance — that objection is the usual reason to
prefer wiring a producer over deleting a surface. It does not apply here, because the capability
already exists elsewhere, is better developed, and has a real producer.

| Object | Producer | Chain of command | State |
|---|---|---|---|
| `OrderManager.issue_order` — `cognitive/orders.py:114` | `cognitive/crew_delegation.py:146` | enforced (`authority_over`, per-post caps, TTL, `ORDER_REJECTED`) | **live** |
| `NightOrdersManager` — `runtime._night_orders_mgr` | `/night-orders` | n/a | **live** |
| `WatchManager.issue_order(CaptainOrder)` — `watch_rotation.py:177` | **none** | none | **inert** |

Adding a producer to the third would mean building a *second* orders path beside `OrderManager`
and then reconciling the two. That is strictly more work than deletion, for a worse result.

## Verified against the live codebase (2026-08-22)

```
rg -n 'CaptainOrder\(|add_standing_task\(' src/
  src/probos/watch_rotation.py:158  def add_standing_task(...)   <- the definition
  (no other match in src/ ; every construction is in tests/)

rg -n 'issue_order|get_active_orders|add_standing_task|get_standing_tasks' src/
  watch_rotation.py:158,168,177,193   <- definitions only
  watch_rotation.py:337               <- "active_orders_count": len(self.get_active_orders())
  cognitive/orders.py:114             <- DIFFERENT CLASS
  cognitive/crew_delegation.py:146    <- the real producer, of the other class
```

`runtime.py:1813` mentions `CaptainOrder` in a **docstring only**. The sole in-`src` reader of the
order list is the counter that structurally reports zero.

The dispatch loop is genuinely started in production (`startup/finalize.py:3361,3370`), stopped at
`startup/shutdown.py:747-749`, and sweeps two permanently empty lists forever
(`watch_rotation.py:220-239`).

## Required change

### 1. Delete from `src/probos/watch_rotation.py`

`StandingTask` (`:30`), `CaptainOrder` (`:52`), `_standing_tasks` (`:116`), `_captain_orders`
(`:117`), `add_standing_task` (`:158`), `remove_standing_task` (`:162`), `get_standing_tasks`
(`:168`), `issue_order` (`:177`), `rescind_order` (`:185`), `get_active_orders` (`:193`),
`_dispatch_due_tasks` (`:241`), `_dispatch_due_orders` (`:265`), `_expire_night_orders` (`:340`),
and the `_dispatch_fn` constructor parameter if nothing else consumes it.

`_expire_night_orders` iterates `_captain_orders` and is therefore also a no-op. **It is not the
Night Orders feature** — `NightOrdersManager` (`:419`) and `NightOrders` (`:377`) are a different
class in the same module and must be left completely untouched. Confusing these two is the exact
trap #1282 names; read the names twice.

### 1b. The bridge dies with it

`_dispatch_fn` is wired from `startup/finalize.py:3362` to `runtime._dispatch_watch_intent`
(`runtime.py:1790`), whose only caller is the dispatch loop being deleted. Remove the method, the
constructor parameter, and the `dispatch_fn=` argument.

Its 26-line docstring is the archaeology of BF-790, BF-790a and this defect — *"The watch dispatch
path has never delivered anything."* **Preserve that history in the commit message rather than
letting it vanish with the code.** It is the clearest single statement of why the surface is being
removed, and BF-790/BF-790a were real work spent on a path that could not be reached.

### 2. Decide the loop's fate explicitly

With both dispatch methods gone, `_dispatch_loop` (`:220`) retains only `auto_rotate()` (AD-471
wall-clock watch rotation), which **is** live and consumed. Keep the loop, keep `start`/`stop`,
and delete only the two dispatch calls at `:227-228`. Do not delete `start()`/`stop()` —
`finalize.py:3370` and `shutdown.py:748` call them.

### 3. Remove the two structurally-zero counters

`get_watch_status` (`:329-338`) returns `standing_tasks_count` and `active_orders_count`. Both
are always `0`. Two Captain-facing readers must change with them:

- `experience/commands/commands_autonomous.py:196-197` — the `/watch` panel prints both.
- `routers/system.py:381-385` — `GET` returns `get_watch_status()` wholesale.

Removing the keys is the point: a count that is structurally always zero reads to the Captain as
"no orders outstanding" when the truth is "this surface cannot hold an order."

## What this does NOT change

- **`OrderManager` (`cognitive/orders.py`) — not one line.** It is the live orders path and the
  reason deletion is safe. Do not "unify" the two; do not move `OrderManager` into
  `watch_rotation.py`; do not add a `CaptainOrder` shim in front of it.
- **`NightOrdersManager` / `NightOrders` / `NIGHT_ORDER_TEMPLATES` — not one line.**
- **The roster half stays:** `get_roster` (`:152`), `get_on_duty` (`:148`), `assign_to_watch`
  (`:138`), `remove_from_watch` (`:143`), `set_current_watch`, `auto_rotate`,
  `_get_current_watch_by_time`. Consumed by `ontology/service.py:499-512,619-627`,
  `routers/system.py:381`, and `runtime.py:1842`.
- **Do not build a replacement standing-task scheduler.** If watch-scheduled work is wanted later
  it arrives as standing tasks feeding `OrderManager`, as a separate AD, with a producer named in
  the prompt before any consumer is written.
- **Do not touch `IntentBus.publish` / `broadcast` behaviour.** `mesh/intent.py:1104`'s docstring
  calls itself *"an alias for broadcast() — used by WatchManager dispatch (runtime.py:689)"*.
  Verified: `runtime.py:685-696` is avatar telemetry construction, so that line reference is stale
  **and** the named consumer is the one being deleted. Correct the docstring; change no behaviour.
  `publish` has other callers — enumerate them before assuming otherwise.
- **Do not touch `mesh/intent.py:837`'s comment** about the WatchManager consumer being "a real
  one", beyond correcting it. It records why `broadcast` does not raise unconditionally; that
  reasoning may still hold for other consumers.

## Tests

Delete the tests that exercise the removed surface rather than porting them — a test for a
deleted capability is not evidence of anything. Then add:

1. `WatchManager` has no attribute named `issue_order`, `add_standing_task`, `_captain_orders` or
   `_standing_tasks`. This is the anti-resurrection guard; state inline that it exists so a future
   AD reintroducing watch orders has to delete an assertion and say why.
2. `get_watch_status()` returns exactly the expected key set, and it excludes both counters.
3. `/watch` renders without the two lines, and the `GET` route's response schema no longer
   carries them.
4. A started-then-stopped `WatchManager` still auto-rotates by wall clock — the surviving half of
   the loop is proven live, not assumed.
5. `OrderManager.issue_order` still works end-to-end from `crew_delegation.py:146`, including one
   out-of-chain rejection. This is the test that proves no capability was lost, and it is the most
   important one in the set.

## Tracking

- Close **#1282** as built. Record the sunk cost plainly: **BF-790, BF-790a and BF-814 were three
  fixes to a path that could not be reached.** #1172's forcing question — *name the real caller in
  production* — would have caught it before the first one.
- Close **#1288 (BF-824)** only if it turns out to be about this loop; verify first. It is about a
  pool health loop, not the watch loop, and is almost certainly unrelated.
- Close **#1278 (BF-814)** as **removed, not fixed** — say so in the close comment, in exactly
  those words, with a link to this AD. The defect it describes (`[]` from `broadcast` consumed as
  execution) was real; the surface carrying it no longer exists. Note in the comment that
  `DispatchAdmission` (`types.py:105`) remains the vocabulary for any future broadcast receipt,
  and that its `admitted` semantics — *the delivery substrate accepted responsibility, NOT that an
  agent processed the work* — is the distinction such a receipt would have to make.
- `PROGRESS.md` and `docs/development/roadmap.md` Bug Tracker.

## Report back

- The exact deleted symbol list, and confirmation that `OrderManager` and `NightOrdersManager` are
  byte-identical.
- Confirmation that `_dispatch_watch_intent` had no second caller.
- Test count before and after; the deletion should reduce it, and that is correct.
- **Anything in this prompt that turned out to be untrue.**

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
