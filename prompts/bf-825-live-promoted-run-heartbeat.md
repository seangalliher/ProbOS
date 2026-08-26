# BF-825: the board and the reporter disagree about a promoted run that outlives four hours

**Issue:** #1289 (already filed, OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**Number:** BF-825 — already allocated, do not mint a new one.
**This is a decision prompt.** Section 3 is the Captain's call. Do not build past it.

---

## Correction to the issue text — read first

The issue and its summary name the threshold **`reconcile_stall_seconds`**. **No such field exists**
— 0 hits across `src/`, `config/`, `tests/` and `docs/`. The real field is:

```
src/probos/config.py:5734   strand_timeout_seconds: int = Field(default=14_400, ge=0, le=604_800)
```

and the class is **`WorkItemReconciler`**, not `WorkReconciler`
(`src/probos/cognitive/work_reconciler.py:29`). Everything else in the issue holds. Use the real
names; a prompt that repeats the wrong one will send the Builder looking for a field that was never
written.

---

## The defect, verified at HEAD (2026-08-22)

### The classifier

```
src/probos/cognitive/work_reconciler.py:82    def classify(self, wi, *, is_dispatchable, is_stalled=False)
                                     :123-126     if is_stalled and status == "in_progress":
                                                      return ReconcileDecision(
                                                          wid, "strand_terminal", assignee, None,
                                                          "stalled_not_dispatchable")
```

reached only on the `not is_dispatchable` branch (`:116`) — which is where every AD-1165 promoted
turn lands, deliberately, because rerouting one would replay side effects it already performed.

### Staleness comes from a value nothing refreshes

```
src/probos/agents/quartermaster.py:300-311
    if wi.get("status") == "in_progress":
        threshold = self._stall_timeout_seconds if is_disp else self._strand_timeout_seconds
        updated_at = wi.get("updated_at") or 0
        if threshold > 0 and float(updated_at) < time.time() - threshold:
            is_stalled = True
```

A promoted turn writes its row **exactly twice**, both at promotion. `turn_promotion.py` touches the
store at four places and no others:

```
:527  store = getattr(runtime, "work_item_store", None)     # create
:558  await store.transition_work_item(item.id, "in_progress", source=agent_id)
:943  store = getattr(runtime, "work_item_store", None)     # finish
:957  await store.transition_work_item(work_item_id, "failed" if ... else "done", ...)
```

Nothing between `:558` and `:957` touches `updated_at`. So a live run's row is indistinguishable
from an abandoned one after four hours.

### Both thresholds are live on the shipped config

```
config/system.yaml (COMMITTED, line 2140)   work_board_reconciler: enabled: true
SystemConfig().work_board_reconciler.strand_timeout_seconds  ->  14400      # 4h
SystemConfig().work_board_reconciler.stall_timeout_seconds   ->  0          # dispatchable path off
```

(The Pydantic default for `enabled` is `False`, but the committed YAML sets it `true`. The sweep runs.)

### The exact path that reaches it — this is the part the issue does not spell out

BF-733's deadline is **eight times tighter** than the strand threshold:

```
config.py:6294   promoted_run_deadline_seconds: float = Field(default=1800.0, ...)   # 30 min
config.py:5734   strand_timeout_seconds:        int   = Field(default=14_400, ...)   # 4 h
```

So an ordinary long run is stopped and reported at 30 minutes and never reaches the reconciler.
**One path does reach it, and the code takes it deliberately:**

```
turn_promotion.py:828-832
    logger.warning("BF-733: work item %s reported as unconfirmed and stays open; "
                   "the reporter keeps waiting so a late result is still delivered "
                   "rather than discarded", work_item_id)
              :834    text = await task            # <-- UNBOUNDED, after the interim notice
```

A run that blows its 30-minute deadline **and then refuses its cancellation** (past the 10 s
`_ABANDON_GRACE_SECONDS`, `:160`) gets an interim notice and the reporter then waits on it with no
bound. The row sits `in_progress`, `updated_at` frozen since promotion. At the four-hour mark the
sweep strands it `failed`. If the run later lands:

```
workforce.py:312   return False, f"Cannot transition from terminal status '{from_status}'"
```

which is exactly the Captain's measurement:

```
live-owner reconcile action  strand_terminal   reason stalled_not_dispatchable
late success failed->done    allowed False     reason Cannot transition from terminal status 'failed'
```

**Two deliberate decisions, each correct alone, that contradict each other.** `turn_promotion.py:828`
chose "keep waiting so a late result is not discarded". BF-730 chose "a stalled non-dispatchable item
must get an ending rather than sit forever". Neither knows about the other. That is the defect —
not a bug in either.

---

## The decision

### 1. What is actually being asked

Not "should a live run be protected from the reconciler" in the abstract. Precisely:

> **Should a promoted run that has already blown a 30-minute deadline AND refused a cancellation be
> able to hold its board row open for more than four hours?**

Framed that way the Captain's instinct on the issue has real force: *"a run that has blown its
deadline and refused a cancel is not obviously something the board should keep open."*

### 2. Options, with their measured costs

**(a) Heartbeat / ownership lease — refresh `updated_at` while a reporter is waiting.**
Expresses the true fact ("someone is still waiting on this") in existing storage, and resolves the
conflict in both directions. Three costs, all verified:

- `update_work_item` **ignores an empty update**: `workforce.py:3046  if not set_clauses: return item`.
  A heartbeat must therefore write a real field — a metadata key — not call an empty update.
- Every write **emits `WORK_ITEM_UPDATED` and refreshes the snapshot cache**
  (`workforce.py:3055-3060`). A heartbeat is an HXI event at every tick, forever, for a wedged run.
  Choose an interval against `strand_timeout_seconds`, not against wall-clock intuition — one tick
  per hour is sufficient for a four-hour threshold and costs four events.
- **It needs a bound of its own.** A heartbeat with no ceiling converts a four-hour strand into an
  infinite one and re-creates the pre-BF-730 defect, which measured items idle between 23.5h and 182h.

**(b) A distinct non-terminal "unresponsive" state.** Honest — the row would say what is true. But
it is a change to the AD-498 state machine, which every board consumer and several exact-key
contracts read. Largest blast radius of the three; do not choose it without measuring that radius.

**(c) Bound the post-interim wait** (put a ceiling on `turn_promotion.py:834`'s `await task`).
Simplest. It re-opens what `:828-832` deliberately closed: a late-landing run's answer is discarded.
But note what BF-733 already established — an *abandoned* run's answer is not automatically the
Captain's answer, and by four hours past a thirty-minute deadline the Captain has long since had an
interim report.

### 3. HANDED TO THE CAPTAIN — do not decide this in the build

Two questions, both policy:

1. **Is four hours right for `strand_timeout_seconds`,** given BF-733 now bounds the ordinary case at
   thirty minutes? The 4h value was chosen (`config.py:5726-5733`) when nothing bounded a promoted
   run at all. That premise has changed.
2. **May a live-but-unconfirmed run hold its row open indefinitely?** If yes → option (a) with an
   explicit ceiling. If no → option (c), and `turn_promotion.py:828-832`'s comment must be rewritten
   to say the answer can now be discarded, because leaving prose that promises delivery over code
   that drops it is the failure mode this repo keeps re-learning.

**Architect's recommendation, offered not assumed: (a) with a hard ceiling** — heartbeat while a
reporter is genuinely waiting, up to a stated maximum (a small multiple of
`promoted_run_deadline_seconds`, not a new independent constant), then stop refreshing and let the
sweep strand it. That keeps BF-730's guarantee ("nothing waits forever"), keeps BF-733's ("a late
answer is not discarded") inside a bounded window, and makes the board tell the truth in both.

**Do not build until the Captain answers.** If the answer is (a), the ceiling value is theirs too.

---

## Required tests (whichever option is chosen)

New file: `tests/test_bf825_live_promoted_run_is_not_stranded.py`.

The issue's own acceptance demands **one test spanning the whole crossing** — this repo's dominant
defect shape is a chain whose every link is tested and whose seam is dead. Three tests that each
stop at a boundary do not count.

1. **The crossing, end to end:** promote → deadline fires → interim notice posted → the reconciliation
   threshold elapses → the run lands → assert the transcript and the board agree. Drive the **real**
   `WorkItemReconciler.classify` and the **real** AD-498 state machine (`workforce.py:312`), not
   doubles — the defect lives in what those two actually do.
2. **BF-730's guarantee survives:** a promoted run nothing is waiting on is *still* stranded. This is
   the assertion that catches an over-broad fix. Reuse the shape in
   `tests/test_bf752_stalled_promoted_turn_ends.py:113` (`strand_timeout_seconds=strand`).
3. **The ceiling is enforced** (if option (a)): a heartbeat that outlives its bound stops refreshing
   and the row is stranded. Without this the fix is unbounded and strictly worse than the defect.
4. **Positive premise beside every negative.** "The row was not stranded" must sit beside "the sweep
   actually ran and actually classified this item" — otherwise the test passes because the sweep
   never reached it. Three tests passed vacuously in BF-830 for exactly this omission.
5. **Event cost is bounded** (if option (a)): assert the number of `WORK_ITEM_UPDATED` emissions over
   a simulated four-hour window is what the design says it is.

### Mutation check (required)

Revert the heartbeat (or the bound) and confirm test 1 reddens. Revert the *ceiling* separately and
confirm test 3 reddens. If the ceiling mutant survives, the ceiling is untested and the fix is
unbounded in production.

---

## Test blast radius — enumerated

| File | Why it is in scope |
|---|---|
| `tests/test_bf730_strand_terminal.py` | `:234-241, :276` construct configs with `strand_timeout_seconds`. BF-730's guarantee must still hold — **do not weaken an assertion here to make a new test pass.** |
| `tests/test_bf752_stalled_promoted_turn_ends.py` | `:217, :226-227` assert `strand_timeout_seconds > 0`, `>= 3600`, `<= 86_400`. **If the Captain changes the default, these are the tests that encode the old policy** — update them and record the new reasoning inline; never delete. |
| `tests/test_ad874_work_reconciler.py` | owns `classify`'s contract. |
| `tests/test_bf733_promoted_run_deadline.py` | owns the deadline/grace/unconfirmed path, including an `ast.parse(inspect.getsource(cognitive_agent))` guard at `:1223`. |
| `tests/test_ad875_quartermaster.py`, `test_ad877_reconcile_thrash_guard.py`, `test_ad883_reconcile_observability.py` | the sweep's other contracts — a heartbeat interacts with the AD-877 backoff (`quartermaster.py:290-296`, keyed on `last_reconcile_at`). Check that interaction explicitly. |

---

## Do not build

- **Do not remove or weaken `strand_terminal`.** BF-730 exists because 42 non-terminal items sat on
  the board, six of them idle between 23.5h and 182h. That guarantee is not negotiable.
- **Do not make `classify` impure.** Its docstring and module header both state it is side-effect-free
  and that the sweep owns the clock. "Make the reconciler ask the owner" is named on the issue as the
  largest option for exactly this reason. The staleness signal is computed by the caller
  (`quartermaster.py:300-311`) — keep it there.
- **Do not fix BF-826 here.** `_post_report` being synchronous and best-effort is #1290 and has its
  own prompt. Both are visible in the same diff region and it is tempting to solve both with one
  change; do not.
- **Do not add a new work-item status** unless the Captain picks option (b), and not without first
  measuring what reads the AD-498 status set.
- **Do not change `promoted_run_deadline_seconds`** as a side effect of changing the strand threshold.
  They are separate policies with separate rationales, both recorded in their field descriptions.
- **Do not touch the `hybrid_dispatch.dispatchable_tags` logic or `is_dispatchable`.** A promoted turn
  must stay non-dispatchable; making it dispatchable to dodge the classifier would replay side effects.
- **Do not widen this to non-promoted stalled items.** `stall_timeout_seconds` is 0 by default for a
  recorded reason (rerouting a live dispatchable item replays work).

---

## Acceptance criteria

- A promoted run that is genuinely still being waited on is not closed `failed` by the reconciler,
  within whatever bound the Captain sets.
- A promoted run nothing is waiting on is still stranded, as BF-730 requires.
- The transcript and the board never disagree about whether a promoted turn succeeded.
- One test spans the whole crossing: interim notice → reconciliation threshold → late success.
- Any bound added is itself tested, and its mutant dies.
- Every comment and field description in the touched region describes what the code now does —
  specifically `turn_promotion.py:828-832` and `config.py:5726-5733`.
- If a config default moves, `python scripts/gen_config_reference.py` is re-run and
  `docs/development/config-reference.md` staged in the **same** commit, or
  `tests/test_config_reference_current.py` reddens the gate.
- Focused gate: `pytest tests/test_bf825_*.py tests/test_bf730_*.py tests/test_bf752_*.py tests/test_ad874_*.py tests/test_ad875_*.py tests/test_bf733_*.py -q -n 0`
- Then one consolidated gate: `pytest tests/ -q -n 16 --dist=loadfile`
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code.

---

## Verified Against Codebase (2026-08-22)

```
rg -n "reconcile_stall_seconds" .          ->  0 hits   (the issue's field name does not exist)

work_reconciler.py:29    class WorkItemReconciler:          (not "WorkReconciler")
                :82      def classify(self, wi, *, is_dispatchable, is_stalled=False)
                :116     if not is_dispatchable:
                :123-126     if is_stalled and status == "in_progress":
                                 return ReconcileDecision(wid, "strand_terminal", ...,
                                                          "stalled_not_dispatchable")

quartermaster.py:300-311  threshold = stall_timeout if is_disp else strand_timeout
                          updated_at = wi.get("updated_at") or 0   -> is_stalled

config.py:5734   strand_timeout_seconds: int   = Field(default=14_400, ge=0, le=604_800)
config.py:6294   promoted_run_deadline_seconds: float = Field(default=1800.0, ge=0.0, le=86400.0)
SystemConfig():  strand=14400  stall=0  reconciler.enabled(pydantic)=False
git show HEAD:config/system.yaml : "work_board_reconciler:\n ... enabled: true"   (line 2140)

grep -n "work_item_store\|transition_work_item" src/probos/cognitive/turn_promotion.py
  527, 558, 943, 957   -> only 4; nothing refreshes updated_at during the run

turn_promotion.py:160     _ABANDON_GRACE_SECONDS: float = 10.0
                 :828-832 "reported as unconfirmed and stays open; the reporter keeps waiting"
                 :834     text = await task                      # unbounded
                 :957     transition_work_item(..., "failed" if (failed or abandoned) else "done")

workforce.py:312   "Cannot transition from terminal status '{from_status}'"
workforce.py:3046  if not set_clauses: return item        # empty update does NOT touch updated_at
workforce.py:3055-3060  update_work_item -> _refresh_snapshot_cache() + emit WORK_ITEM_UPDATED
```
