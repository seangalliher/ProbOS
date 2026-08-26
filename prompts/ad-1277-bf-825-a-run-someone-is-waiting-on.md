# AD-1277 / BF-825: a run someone is waiting on is not abandoned work

**Issue:** #1289 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1277 — newly minted. Ceiling was **AD-1276**, enumerated from `git log --all --format='%s'`,
`prompts/ad-*.md` filenames, and GitHub issue titles in all states. **Not** from `open-ads-report.md`.
**BF:** BF-825 — already allocated on the issue. Do not mint a new one.
**Supersedes:** `prompts/bf-825-live-promoted-run-heartbeat.md` — that file is a *decision* prompt that
hands the call back to the Captain, and its line anchors are 12–14 lines stale (`turn_promotion.py`
moved between 2026-08-22 and 2026-08-26). **Archive it as part of this build.**
**Depends on:** **AD-1274 must land first.** See "Ordering against AD-1274" below — this is a
behavioural dependency, not only a merge-conflict one.
**Status:** ready to build · **Estimated tests:** 10–14 across two slices

---

## Corrections to the issue text — read before anything else

The issue names two identifiers that do not exist. A builder who greps for them will find nothing and
start inventing.

| Issue says | Reality at HEAD |
|---|---|
| `reconcile_stall_seconds` | **No such field.** The real one is `strand_timeout_seconds` (`config.py:5746`). |
| `WorkReconciler` | The class is **`WorkItemReconciler`** (`work_reconciler.py:29`). |

Everything else in the issue holds, including the measurement.

---

## The defect, verified at HEAD (2026-08-26)

### The two decisions that contradict each other

```
work_reconciler.py:116        if not is_dispatchable:
                 :123-126         if is_stalled and status == "in_progress":
                                      return ReconcileDecision(
                                          wid, "strand_terminal", assignee, None,
                                          "stalled_not_dispatchable")
```

```
turn_promotion.py:830-834   logger.warning("BF-733: work item %s reported as unconfirmed and stays
                             open; the reporter keeps waiting so a late result is still delivered
                             rather than discarded", work_item_id)
                 :836       text = await task          # <-- UNBOUNDED
```

BF-730 decided *"a stalled non-dispatchable item must get an ending rather than sit forever."*
BF-733 decided *"keep waiting so a late result is not discarded."* Neither knows about the other.
**That gap is the defect — not a bug in either.**

### Staleness is read from a value nothing refreshes

```
quartermaster.py:301-309    is_stalled = False
                            if wi.get("status") == "in_progress":
                                threshold = (stall if is_disp else self._strand_timeout_seconds)
                                updated_at = wi.get("updated_at") or 0
                                if threshold > 0 and float(updated_at) < time.time() - threshold:
                                    is_stalled = True
```

A promoted turn writes its row **exactly twice, both at promotion**, and never again while the run
executes:

```
turn_promotion.py:529   store = getattr(runtime, "work_item_store", None)        # create
                 :560   await store.transition_work_item(item.id, "in_progress", source=agent_id)
                 :945   store = getattr(runtime, "work_item_store", None)        # finish
                 :959   await store.transition_work_item(work_item_id, "failed" if ... else "done", ...)
```

So `updated_at` means *last board mutation*, not *last sign of life*. **The config already says so and
already pays for it:**

```
config.py:5726-5729   # AD-881: ... updated_at is last-mutation (not a heartbeat), so this is a
                      # coarse signal -- default off.
                      stall_timeout_seconds: int = Field(default=0, ...)   # 0 = disabled
```

`stall_timeout_seconds` ships **disabled because there is no heartbeat.** That is the missing
primitive this AD supplies, and BF-825 is the first place its absence became Captain-visible.

### Both clocks are live on the shipped vessel

```
config/system.yaml:2150-2153   work_board_reconciler:  enabled: true
config.py:5746   strand_timeout_seconds:        int   = Field(default=14_400, ...)   # 4h
config.py:6307   promoted_run_deadline_seconds: float = Field(default=1800.0, ...)   # 30 min
```

`strand_timeout_seconds` is **not** overridden in `system.yaml`, so the Pydantic default applies.

### The exact path that reaches the conflict

The deadline is **eight times tighter** than the strand threshold, so an ordinary long run is stopped
and reported at 30 minutes and never reaches the reconciler. **One path gets there**, and the code
takes it deliberately: a run that blows its deadline **and then refuses its cancellation** past the
10-second grace (`turn_promotion.py:162`) gets an interim notice and the reporter then waits on it
with no bound (`:836`). The row sits `in_progress` with `updated_at` frozen since promotion. At four
hours the sweep strands it `failed`.

### NEW FINDING — the late landing is completely silent

The superseded prompt asserted the disagreement surfaces through the `except Exception` at
`turn_promotion.py:962`. **It does not.** Verified:

```
workforce.py:4337   if not self._validate_work_item_status_transition(item, new_status):
                        return None                       # <-- RETURNS None. Does NOT raise.
workforce.py:3229   logger.warning("Invalid transition for %s: %s", item.id, reason)
```

So on the late-landing path `_finish_promoted_turn` posts the success report to the transcript
(`:901`), stores a *successful* episode, calls `transition_work_item(..., "done")`, gets `None` back,
and **falls off the end without entering its own `except`.** The only trace anywhere is a generic
store-level `"Invalid transition"` warning that names no work item owner and no BF.

**Consequence for the build:** the comment at `turn_promotion.py:962-971` — which already cites
"BF-825, #1289" — describes a branch this defect never takes. It must be corrected, not extended.
And the recall layer records a *success* episode for a run the board calls `failed`; the acceptance
criterion "transcript and board never disagree" therefore covers **three** sinks, not two.

---

## The decision

### Chosen: (a) a bounded ownership lease held by the reporter

The reporter refreshes the row while it is genuinely waiting, the lease has a maximum lifetime, and
**when the lease expires the reporter — not the sweep — writes the ending.**

That last clause is the part the issue leaves open, and it is what makes the option coherent rather
than merely deferring the problem.

### Why the other two lose

**(b) Make the reconciler ask the owner — rejected.** `classify` is pure by construction: the module
docstring says *"Pure, side-effect-free service... never mutates the board"* (`work_reconciler.py:1-7`,
`:31-33`), and the staleness signal is deliberately computed by the caller because *"the sweep owns
the clock"* (`:96-99`, `quartermaster.py:296-298`). Giving it a channel to a reporter inverts that.
The issue itself names this as the largest option, for exactly this reason.

**(c) Bound the post-interim wait alone — rejected as the *whole* answer, adopted as slice 1.**
On shipped defaults it works: bound the reporter at ~1h and the sweep's 4h threshold is never
reached. But it is *coincidentally* correct, not *structurally* correct — it depends on a numeric
relationship between two independently-operable fields, and it has a hole that a bound cannot close:

```
turn_promotion.py:281 / :313-315   deadline_seconds <= 0 disarms the watchdog entirely
config.py:6309                     promoted_run_deadline_seconds: ge=0.0   -> operator may set 0
```

With the watchdog disarmed there is no interim notice and no post-interim wait to bound. The reporter
sits on the ordinary `await task` (`_PromotedRunSupervisor.result`, `:392-395`: *"if self._watch is
None: return await self._task"*), the row freezes at promotion, and at four hours the sweep strands a
run with a live owner. **A bound on the post-interim wait never executes on that path.** A lease does,
because it is keyed on *"a reporter is waiting"*, which is true in both.

### What bounds the lease, and what happens when a run exceeds it

**The bound:** a new field beside the deadline it derives from —

```python
promoted_run_unconfirmed_grace_seconds: float = Field(default=1800.0, ge=0.0, le=86400.0)
```

Default equal to `promoted_run_deadline_seconds`' default, and the description must say why: **a run
that refused its cancellation gets exactly one more budget's worth to land, then it is over.** One
symmetric restatement of a policy the operator already set, not a second tuning knob with an
unexplained number. Maximum life of a promoted row on shipped config becomes
`1800 + 10 + 1800 ≈ 1h`, comfortably inside the 4h strand threshold.

**What happens at the bound — this is the Captain's open question, answered:**

The reporter stops waiting and **closes the row itself**, `failed`, with a reason recorded in
metadata. It does **not** simply stop refreshing and let the sweep collect the row, because the sweep
runs on a 300s interval (`config.py:5717`) and that leaves a window in which the run can land and hit
the terminal-transition rejection again — the same defect, moved later and made rarer, which is the
worst of both.

**The late result is discarded, deliberately.** The Captain already holds the interim notice; the run
has already had two full budgets; and the alternative is the pre-BF-730 condition that measured items
idle between 23.5h and 182h. `_retrieve_late_run_failure` is **already registered on this exact path**
(`turn_promotion.py:379-381`), so giving up the await raises no unretrieved-task warning.

**The prose at `turn_promotion.py:830-834` promises the opposite and must be rewritten in the same
commit.** It currently says *"a late result is still delivered rather than discarded."* Leaving that
sentence over code that discards is precisely the failure this repo keeps re-learning.

**`0` disables the lease** and restores today's unbounded wait, matching the convention
`promoted_run_deadline_seconds` already sets. The field description must state that.

### Does the classifier stay pure? Yes — it is not touched at all

`work_reconciler.py` gets **zero changes**. No new parameter, no new branch, no new input. The fix is
entirely producer-side: the reporter writes to the board, which it already does through
`work_item_store`. `quartermaster.py`'s staleness computation is also unchanged — it keeps reading
`updated_at`, and the lease simply makes `updated_at` mean what that code already assumes it means.

**Guard this in a test.** Assert `WorkItemReconciler.classify`'s signature is unchanged (bind
`inspect.signature`), so a later builder cannot "simplify" the lease by teaching the classifier about
ownership.

### Ordering against AD-1274

**They interact, and AD-1274 must land first.** Two reasons, the second substantive:

1. **Mechanical.** AD-1274 makes `_post_report` async and changes its call at `turn_promotion.py:901`
   inside `_finish_promoted_turn` (`:782`) — the same function this AD modifies at `:836` and
   `:945-971`. It also changes the `on_unconfirmed=lambda: _post_report(...)` at `:1012`, which alters
   `_PromotedRunSupervisor.__init__`'s `on_unconfirmed: Callable[[], None]` contract (`:282`, `:366-390`).
2. **Behavioural — this is the real dependency.** This AD's decision to *discard a late answer* is
   defensible **only because the Captain reliably received the interim notice.** Today that notice is
   posted best-effort and synchronously, and AD-1274's own measurement shows `_post_report` can return
   its body **as if delivered** while the database holds nothing. Discarding a late result to protect a
   report that may itself have been silently lost trades one silent loss for another. AD-1274's durable
   `promoted_report_outbox` is what makes the trade honest.

**Shared-file note for the builder:** both write to `workforce.db`. AD-1274's premise is that
`chat_threads.db` and `workforce.db` are *different files with different locks*. The lease adds
periodic writes to `workforce.db`. At the interval specified below that is at most a handful of writes
per run — negligible, but say so in the commit rather than discovering it in review.

### Shippable first slice — stated plainly

**Slice 1 (bound + reporter-written ending + prose repair) closes the issue's acceptance on the
shipped configuration, and does not close it in general.** On defaults the reporter ends the row at
~1h and the 4h sweep never sees it, so transcript, episode and board agree. It does **not** hold when
`promoted_run_deadline_seconds: 0` (watchdog disarmed, no interim notice, unbounded `await task`), nor
if an operator lowers `strand_timeout_seconds` below the reporter's bound.

**Slice 2 (the lease) is what makes the guarantee structural.** Ship slice 1 alone only if slice 2 is
filed and scheduled; say so in the commit message rather than implying the issue is fully closed.

---

## Implementation

### Section 1 — config

`src/probos/config.py`, immediately after `promoted_run_deadline_seconds` (`:6307-6334`), in the same
model:

- `promoted_run_unconfirmed_grace_seconds: float = Field(default=1800.0, ge=0.0, le=86400.0)`
- Description must state: what it bounds; that `0` restores the unbounded wait; that the late result
  **is discarded** past it and why that is acceptable; and that its default is one more
  `promoted_run_deadline_seconds` budget rather than an independent number.

Slice 2 only — in `WorkBoardReconcilerConfig` or read from it at the call site, **not** a third
independent timeout: the lease's refresh interval must be **derived** from
`strand_timeout_seconds`, so an operator who lowers the threshold does not silently outrun the
heartbeat. `interval = max(60.0, strand_timeout_seconds / 4.0)` is sufficient and costs at most four
writes per strand window. Do not hard-code an interval.

### Section 2 — the bound (slice 1)

`src/probos/cognitive/turn_promotion.py`, the `_RunAbandoned` / `stopped=False` branch of
`_finish_promoted_turn` (`:830-846`):

- Replace the bare `text = await task` (`:836`) with a bounded wait using the new config value.
  Read it defensively at the call site the same way `deadline_seconds` is
  (`cognitive_agent.py:4486-4488` uses `_coerce_promotion_budget(getattr(cfg, ..., 0.0))`) — a
  `MagicMock` config must not hand a truthy proxy to a numeric comparison. **Follow that existing
  helper; do not write a second coercion.**
- On expiry: log at `warning` naming BF-825 and the work item, set a distinct outcome so the finish
  path closes the row `failed` with `metadata` recording the reason (use the existing
  `stranded_reason`-style key shape from `quartermaster.py:339` so the board reads consistently), and
  **do not post a second report** — the Captain already has the interim notice.
- Preserve the existing `asyncio.CancelledError` re-raise (`:838-844`) exactly. Cancellation is not
  expiry.
- Rewrite `:830-834`'s warning text to describe the bounded window.
- Correct the misleading `except Exception` comment at `:962-971`: `transition_work_item` returns
  `None` on a rejected transition and does not raise.

### Section 3 — the lease (slice 2)

While the reporter is waiting on a promoted run, refresh the row periodically. Constraints, each
verified:

- **Use `merge_work_item_metadata`, not `update_work_item`.** `update_work_item` short-circuits an
  empty update — `workforce.py:3118-3119  if not set_clauses: return item` — so it would not touch
  `updated_at` without inventing a column write. `merge_work_item_metadata` refreshes `updated_at`
  (`workforce.py:3468-3471`) and, decisively, offers **CAS on status**:
  `workforce.py:3348  or (expected_status is not None and item.status != expected_status)`.
  Pass `expected_status="in_progress"` so a heartbeat can never refresh a row the sweep already
  stranded, and never resurrect a terminal one.
- **Every refresh emits `WORK_ITEM_UPDATED` and refreshes the snapshot cache**
  (`workforce.py:3481-3486`). That is the cost that makes the derived interval mandatory rather than
  cosmetic.
- **Do not write `last_reconcile_at`.** That key drives the AD-877 backoff
  (`quartermaster.py:284-289`); writing it from the reporter would suppress unrelated sweep work.
- The lease must be cancelled on **every** exit from the wait — success, failure, expiry, cancellation.
  Use `try/finally`, hold the task reference, and re-raise `CancelledError`.

### Section 4 — archive the superseded prompt

`git mv prompts/bf-825-live-promoted-run-heartbeat.md prompts/archive/`.

---

## Required tests

New file: `tests/test_bf825_a_run_someone_is_waiting_on.py`.

1. **The crossing, end to end — one test, not three.** Promote → deadline fires → interim notice
   posted → the reconciliation threshold elapses → the run lands. Assert the transcript, the stored
   episode and the board **all agree**. Drive the **real** `WorkItemReconciler.classify` and the
   **real** AD-498 transition validator (`workforce.py:4337`), not doubles — the defect lives in what
   those two actually do. This repo's dominant defect shape is a chain whose every link is tested and
   whose seam is dead; three tests that each stop at a boundary do not satisfy this.
2. **Positive premise beside every negative.** "The row was not stranded" must sit beside "the sweep
   actually ran **and actually classified this item**" — assert the sweep's `scanned` count and that
   the item was not skipped by the `min_item_age_seconds` grace (`quartermaster.py:272-276`) or the
   AD-877 backoff (`:284-289`). Without this the test passes because the sweep never reached the row.
3. **BF-730's guarantee survives.** A promoted run **nothing is waiting on** is still stranded. This
   is the assertion that catches an over-broad fix. Reuse the config shape in
   `tests/test_bf752_stalled_promoted_turn_ends.py`.
4. **The bound is enforced.** A run that never lands is closed `failed` by the reporter, with the
   reason recorded — and it is closed by the **reporter**, not by the sweep. Assert the sweep did not
   run in this test at all, or the test cannot tell which component ended the row.
5. **The classifier is untouched.** Bind `inspect.signature(WorkItemReconciler.classify)` and assert
   its parameters are exactly `(wi, *, is_dispatchable, is_stalled)`.
6. **Slice 2 — the disarmed-watchdog hole.** With `promoted_run_deadline_seconds=0` and a short
   `strand_timeout_seconds`, a run with a live reporter is **not** stranded. This is the test that
   proves the lease earns its place over the bound alone; if it passes without the lease, the lease
   is unnecessary and should not be built.
7. **Slice 2 — event cost is bounded.** Count `WORK_ITEM_UPDATED` emissions across a simulated strand
   window and assert the number the derived interval predicts.

### Mutation check (required — Critical-risk behaviour)

Run the unmutated baseline FIRST and abort if it is already red. Mutate **in place** with a `.mutbak`
sibling, restore in `finally`, **single-line anchors only** (CRLF tree). An anchor that is not found
is **INERT, not killed** — say so.

- Revert the bound → test 1 and test 4 redden.
- Revert the **reporter-written ending** separately, leaving the bound → test 4 reddens. If it
  survives, the ending is untested and the sweep/reporter race is unproven.
- Revert the lease → test 6 reddens.
- Revert `expected_status="in_progress"` → a test must show a stranded row is not refreshed.

If a mutant survives, **check whether the MUTANT is wrong before concluding the test is weak** —
a mutant whose row is excluded by a *different* guard never reaches the behaviour it claims to break.

---

## Test blast radius — enumerated

| File | Why it is in scope |
|---|---|
| `tests/test_bf733_promoted_run_deadline.py` | Owns the deadline / grace / unconfirmed path. Contains an `ast.parse(inspect.getsource(...))` source-scan guard. **A `?raw` source scan cannot tell "required" from "what shipped"** — if it asserts the presence of the unbounded `await task` or the old warning prose, update the assertion and record why **inline**; never delete it. |
| `tests/test_bf730_strand_terminal.py` | BF-730's guarantee. **Do not weaken an assertion here to make a new test pass.** |
| `tests/test_bf752_stalled_promoted_turn_ends.py` | Asserts bounds on `strand_timeout_seconds`. If a default moves these encode the old policy — update and record the reasoning inline. |
| `tests/test_ad874_work_reconciler.py` | Owns `classify`'s contract. **Should need no change.** If it does, the purity claim above is false — stop and re-read the decision. |
| `tests/test_ad875_quartermaster.py`, `test_ad877_reconcile_thrash_guard.py`, `test_ad883_reconcile_observability.py` | The sweep's other contracts; the lease interacts with the AD-877 backoff and the observability counters. Check explicitly. |

---

## Do not build

- **Do not modify `src/probos/cognitive/work_reconciler.py`.** Zero changes. If the implementation
  seems to need one, the design has drifted — stop.
- **Do not remove or weaken `strand_terminal`.** BF-730 exists because 42 non-terminal items sat on
  the board, six idle between 23.5h and 182h. Not negotiable.
- **Do not change `promoted_run_deadline_seconds` or `strand_timeout_seconds` defaults.** They are
  separate policies with separate recorded rationales. This AD adds a bound; it does not retune
  existing ones.
- **Do not fix BF-826 here.** `_post_report`'s delivery is #1290 / AD-1274, visible in the same diff
  region. It is tempting to solve both with one change. Do not.
- **Do not add a work-item status.** There is no `paused`/`incomplete` in the AD-498 state machine and
  `turn_promotion.py:168-171` records the decision not to invent one.
- **Do not touch `is_dispatchable` or `hybrid_dispatch.dispatchable_tags`.** A promoted turn must stay
  non-dispatchable; making it dispatchable to dodge the classifier would replay side effects.
- **Do not widen this to non-promoted stalled items.** `stall_timeout_seconds` is 0 for a recorded
  reason. Enabling it because a heartbeat now exists is a **separate AD** with its own blast radius.
- **Do not change the BF-704 partial-work path** (`turn_promotion.py:948-957`) or the
  `CancelledError` path (`:849-860`). Both deliberately leave rows `in_progress`, and BF-730's strand
  is the correct ending for them.

---

## Acceptance criteria

- A promoted run genuinely still being waited on is not closed `failed` by the reconciler, within the
  configured bound.
- A promoted run nothing is waiting on is still stranded, as BF-730 requires.
- The transcript, the stored episode and the board never disagree about whether a promoted turn
  succeeded — **all three**, per the silent-late-landing finding above.
- One test spans the whole crossing: interim notice → reconciliation threshold → late success.
- The bound is itself tested and its mutant dies; the reporter-written ending is tested separately
  and its mutant dies.
- `WorkItemReconciler.classify` is unchanged and a test pins its signature.
- Every comment and field description in the touched region describes what the code now does —
  specifically `turn_promotion.py:830-834` and `:962-971`.
- Config reference regenerated: `python scripts/gen_config_reference.py`, with
  `docs/development/config-reference.md` staged in the **same** commit, or
  `tests/test_config_reference_current.py` reddens the gate.
- `prompts/bf-825-live-promoted-run-heartbeat.md` archived.
- If slice 1 ships alone, the commit message states the disarmed-watchdog hole remains open and names
  the follow-up.
- Focused gate: `pytest tests/test_bf825_*.py tests/test_bf733_*.py tests/test_bf730_*.py tests/test_bf752_*.py tests/test_ad874_*.py tests/test_ad875_*.py -q -n 0`
- Then one consolidated full gate after the wave is frozen: `pytest tests/ -q -n 16 --dist=loadfile`
  (~15–19 min; it sits at `[ 99%]` for several of them — that is normal, not a hang). A source or test
  change after the gate **invalidates it**; rerun.
- Run the `Diff Reviewer` subagent on the staged diff with a **different model than wrote the code**,
  and repair its findings before committing.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-08-26)

```
rg -n "reconcile_stall_seconds" .            ->  0 hits (issue's field name does not exist)
git log --all --format='%s' | rg -o 'AD-1\d\d\d' | sort -u | tail  ->  ceiling AD-1276
ls prompts/ad-1*.md | tail -1                ->  ad-1276-bf-789-a-node-charges-its-policy-once.md
gh issue list --state all  (AD-1277..1280)   ->  no allocation

work_reconciler.py:1-7     "Pure, side-effect-free service ... never mutates the board"
                 :29       class WorkItemReconciler          (NOT "WorkReconciler")
                 :82       def classify(self, wi, *, is_dispatchable, is_stalled=False)
                 :96-99    "``is_stalled`` (AD-881) is supplied by the sweep, which owns the clock"
                 :116      if not is_dispatchable:
                 :123-126      return ReconcileDecision(wid, "strand_terminal", ..., "stalled_not_dispatchable")

quartermaster.py:272-276   min_item_age_seconds grace skip
                :284-289   AD-877 backoff on metadata["last_reconcile_at"]
                :301-309   is_stalled computed from updated_at vs strand_timeout_seconds
                :310-312   decision = self._reconciler.classify(wi, is_dispatchable=..., is_stalled=...)
                :318       elif decision.action == "strand_terminal":
                :339       md["stranded_reason"] = "stalled_not_dispatchable"

turn_promotion.py:162      _ABANDON_GRACE_SECONDS: float = 10.0
                 :168-171  "There is no ``paused``/``incomplete`` status in the AD-498 state machine"
                 :281      def __init__(..., on_unconfirmed: Callable[[], None] | None = None)
                 :313-315  arm(): only when deadline > 0.0
                 :379-381  _retrieve_late_run_failure(...) then _notify_unconfirmed()  # already registered
                 :392-395  result(): if self._watch is None -> return await self._task   # disarmed path
                 :529,560  create + transition_work_item(in_progress)      \  the ONLY two
                 :945,959  store lookup + transition_work_item(done/failed) /  row writes
                 :830-834  "the reporter keeps waiting so a late result is still delivered"
                 :836      text = await task                               # UNBOUNDED
                 :901      reported = _post_report(...)                    # AD-1274 changes this call
                 :962-971  except Exception: "...BF-730's reconciler strands ... (BF-825, #1289)"
                 :1012     on_unconfirmed=lambda: _post_report(...)        # AD-1274 changes this too

workforce.py:3118-3119   if not set_clauses: return item      # empty update does NOT touch updated_at
            :3229        logger.warning("Invalid transition for %s: %s", ...)
            :3348        or (expected_status is not None and item.status != expected_status)   # CAS
            :3468-3471   UPDATE work_items SET metadata = ?, updated_at = ? WHERE id = ?
            :3481-3486   _refresh_snapshot_cache() + emit(WORK_ITEM_UPDATED)   # cost per refresh
            :4337-4338   if not _validate_work_item_status_transition(...): return None   # RETURNS None
            :4342        UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?

config.py:5717   reconcile_backoff_seconds: int = Field(default=600, ...)
         :5726-5729  "updated_at is last-mutation (not a heartbeat) ... default off"
                     stall_timeout_seconds: int = Field(default=0, ...)
         :5746   strand_timeout_seconds:        int   = Field(default=14_400, ge=0, le=604_800)
         :6307   promoted_run_deadline_seconds: float = Field(default=1800.0, ge=0.0, le=86400.0)
config/system.yaml:2150-2153  work_board_reconciler: enabled: true   (strand_timeout_seconds NOT overridden)

cognitive_agent.py:4486-4488  deadline_seconds=_coerce_promotion_budget(
                                  getattr(cfg, "promoted_run_deadline_seconds", 0.0))
```
