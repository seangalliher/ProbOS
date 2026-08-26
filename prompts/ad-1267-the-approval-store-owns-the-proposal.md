# AD-1267 — a recurring fault reaches the repair dispatcher, and the approval store owns the proposal

**Status:** Ready to build
**Closes:** #1307 (BF-841). **Subsumes** #1315 (BF-845, durable repair-proposal dedup) — see DD-4.
**Depends on:** **BF-854 must land first.** Repair briefs carry arbitrary tool error text into
`params`, and this AD routes that text through `action_dedup_key`, which raises on lone surrogates at
HEAD.
**Supersedes:** `prompts/ad-1264-a-recurring-fault-reaches-the-repair-dispatcher.md` (built, reviewed
twice, reverted at its own stop rule). Archive that file; do not build from it.
**Estimated tests:** ≥ 22 new

---

## Numbering

Highest allocated: **AD-1266**, **BF-853**. `AD-1267` / `BF-854` collision-checked against
`PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md` — no hits.

- **This work is AD-1267.** Next free AD after this one: **AD-1268** (allocated below, same wave).

---

## The problem, unchanged

`FaultReportStore.file_fault` emits `FAULT_REPORTED` only on the branch that **creates** a report
(`fault_report.py:287`), so every event carries `occurrences=1` (`:281`), while
`RepairDispatcher.on_fault_event` requires `occurrences >= propose_after_occurrences` (default 2,
`repair_dispatch.py:93-95`). **No repair proposal can ever be raised.** The coalesce branch
(`fault_report.py:258-265`) returns without emitting.

Measured against the real store: five faults, one signature → store reaches `occurrences=5`, one
event emitted, carrying `1`. Zero approvals.

The emit moves, not the threshold: `_DEFECT_MIN_OCCURRENCES` / `DEFAULT_PATTERN_THRESHOLD` /
`REPEAT_THRESHOLD` / `propose_after_occurrences` are pinned transitively equal by
`tests/test_ad1172_repair_dispatch.py:308`, so lowering one is a four-subsystem decision. "Once is a
transient, twice is the tool" stays intact.

---

## Why the previous design was wrong, and what replaces it

The reverted attempt put proposal identity in an in-process map, `RepairDispatcher._proposals`, under
a rule that *nothing releases except a resolution*. Round 2 found that the map was unbounded and
could permanently jam, that its trim policy silently traded a duplicate approval for a **missed**
one, and that a restart produced two pending approvals for one fault.

**All three are properties of the reimplementation, not of the problem.** The approval store already
holds this record, and already holds it durably. Measured:

```
=== P4: is PENDING dedup durable across a restart, when the key is STABLE? ===
same request id after restart (dedup survived): True
pending rows: 1
```

`_refresh_cache` (`capability_request.py:292`) loads **all** rows on `start()`, and
`_find_pending_action` (`:422`) re-derives `action_dedup_key` from each. Durable dedup is already
built. It does not fire for repairs for exactly one reason:

```
=== P3: is the dedup key stable across occurrence counts? ===
occ2 key == occ3 key: False

=== P5: the SAME fault at a higher occurrence count, after restart ===
occ-3 deduped onto occ-2? False
pending rows now: 2 <- 2 == two approvals for ONE fault
distinct fault_ids among them: {'abc123'}
```

`action_dedup_key` hashes the **entirety** of canonical `params` (`capability_request.py:186-197`),
and `params["brief"]` is `render_markdown()`, which renders the occurrence count
(`repair_brief.py:91`: `f"...returned the same error {self.occurrences} time(s):"`). Occurrence 2 and
occurrence 3 are different keys. **Note P5 needs no restart** — two pending approvals for one
`fault_id` appear inside a single process. The in-process map was papering over an unstable key.

So the design is: **make the key stable and delete the record.**

---

## Solution

### DD-1 — Split the two things the previous attempt fused

| Concern | Owner | Lifetime |
|---|---|---|
| *"Has this fault already asked?"* | the **approval store**, keyed on a stable dedup key | durable, survives restart |
| *"Are two tasks filing **right now**?"* | an in-process `set[str]` of fault ids | **the await, and no longer** |

The previous map had to outlive the await *and everything after it*, because it was the only record.
That is what forced the four-state model, the never-release rule, the unbounded map, the trim policy
and the restart duplicate. Once the store holds the record, the in-process set only has to survive
the await, and **unconditional release in `finally` is correct** — it is not claiming anything was
filed; the store answers that on the next occurrence.

This dissolves the two hazards the four-state model existed to survive:

- **Commit-then-raise** (`file_request` commits at `:340`, caches at `:341`, then emits at `:342`,
  which can raise). Release the in-flight marker anyway: the row is committed, so the next recurrence
  calls `file_action_request`, `_find_pending_action` finds it, and returns it unchanged. Nothing is
  filed twice.
- **Cancellation vs a landed insert.** Identical. The row exists; the next event dedups onto it.

The four-state model was correctly *verified* — it genuinely reached `unknown`, and `CancelledError`
genuinely propagated while only `Exception` was swallowed. It is removed not because it was wrong but
because **the question it answered is now answered authoritatively by the store instead of inferred
from a call outcome.** That is the AD-1264 lesson applied one step further: before hardening a
compensating path, ask whether the thing being compensated for can be removed.

### DD-2 — `params` carries identity only; the occurrence count moves to `rationale`

Everything in `params` participates in the key, so `params` may contain **only fields invariant
across recurrences of one fault report**. Verified: the coalesce branch mutates exactly two fields,
and `_persist_occurrence` writes exactly two columns —

```
UPDATE fault_reports SET occurrences = ?, last_seen_at = ? WHERE id = ?
```

— so **every other field of the report is invariant on coalesce.** A brief rendered without the
occurrence count is therefore stable by construction, not by hope.

| Field | In `params`? | Why |
|---|---|---|
| `fault_id` | yes | `uuid4().hex[:12]` set at create (`fault_report.py:269`), never changed on coalesce, and a resolved fault that recurs takes the create branch and gets a **new** id. That rotation is exactly the identity semantics wanted. |
| `signature` | yes | invariant; it is the coalescing key |
| `targets` | yes | config-derived. A config edit that changes the target list is genuinely a different ask — say so in a comment rather than treating it as drift. |
| `brief` | yes, **rendered without the count** | new `RepairBrief.render_for_payload()` |
| occurrence count | **no** | volatile by definition |

**How the Captain still sees the count.** `rationale` already carries it verbatim —
`"The {tool_id} tool has failed the same way {occurrences} times."` — and `rationale` is **not** part
of `action_dedup_key` (the key material is `agent_id | tool_id | action | scope_key | work_item_id |
canonical_params`, `capability_request.py:189-197`). It is bounded at 280 chars (`_RATIONALE_MAX`),
which that sentence fits. So the count reaches the Captain on every filing and never touches the key.
Leave the existing `rationale` text unchanged; it is already correct and already excluded.

### DD-3 — Bound `targets` and narrow `thread_id`, then **prove** the payload fits

Two contract mismatches make an *ordinary* fault permanently unproposable today:

- `fault_report._THREAD_ID_MAX = 128` (`:58`) vs `capability_request._THREAD_ID_MAX = 64` (`:63`);
  the dispatcher forwards unchanged (`repair_dispatch.py:167`). Measured: a normal report with a
  128-char thread id → `validate_action_payload` returns `None` → 3 recurrences, 3 attempts, **0
  requests**.
- `resolve_targets` is unbounded. Measured: one 4,500-char target serialises to 6,127 canonical
  chars; 12 targets of ~210 chars to 4,158. Both rejected against the 4,000 bound.

Fix both at their source, then **assert the payload fits with a test instead of building a fitter.**
With `brief` ≤ `_BRIEF_PREVIEW_MAX` (1,200), `targets` ≤ 8 × 64, `thread_id` ≤ 64, `fault_id` 12 and
`signature` bounded, the canonical payload cannot approach 4,000 — measured at 2,146 for
8 × 64 against a maximal fault. **Do not build a truncating fitter.** A binary-search helper for a
case the bounds make unreachable is machinery for an impossible state, and one test pins the
guarantee more honestly than a helper that is never expected to fire.

### DD-4 — Relationship to #1315 (BF-845)

**AD-1267 subsumes it.** #1315 asks for durable repair-proposal dedup. P4 proves the durable
mechanism already exists and already works; it was disabled by an unstable key, not missing. Making
the key stable turns it on. Close #1315 as subsumed and say why, citing P4/P5.

**The honest guarantee, and it is stronger than the reverted attempt's:**

> **At most one *pending* repair approval exists per fault report, across restarts.**

Not "per process". The claim it does **not** make: a fault whose approval has been **decided**
(denied, approved, fulfilled, failed) can raise a new approval on its next recurrence, because
`_find_pending_action` filters on `status == "pending"` (`capability_request.py:423`). For a
**denied** fault that keeps recurring, that is an approval storm at a slower rate — one per failure.
**That is AD-1268, and it must land before `repair.enabled` is turned on.** It is safe to ship this
AD without it because `RepairConfig.enabled` defaults to `False` (verified, `config.py`), so nothing
reaches a Captain until both are in.

Do **not** fix the denied case here. It is a different seam — "what a decision means" rather than
"what a proposal is" — and fusing seams is what cost two reverts.

---

## Implementation

### Section 1 — `src/probos/fault_report.py`: emit on the coalesce branch

The producer fix. Anchor verified verbatim at HEAD (`:258-265`).

```
===SEARCH===
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            await self._persist_occurrence(existing)
            return existing
===REPLACE===
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            await self._persist_occurrence(existing)
            # AD-1267: the recurrence IS the signal. Emitting only on the create
            # branch meant every event carried occurrences=1 while the repair
            # dispatcher requires >= 2, so no repair could ever be proposed.
            # Measured before this: five faults with one signature drove the
            # store to occurrences=5 and emitted one event, at 1.
            self._emit_fault("FAULT_REPORTED", existing)
            return existing
===END REPLACE===
```

`_emit_fault` swallows its own failures (`:405`) and the payload already carries `occurrences`
(`:402`), so `file_fault`'s "never raises" contract is unaffected. Nothing else in this file changes.

### Section 2 — `src/probos/cognitive/repair_brief.py`

**2a. A stable projection for the payload.** Add `render_for_payload()` beside `render_markdown()`.
It must not be a copy-paste fork — factor the shared body so a field added later cannot appear in one
and not the other. The simplest honest shape is a private `_render(*, include_occurrences: bool)`
that both call. The docstring must state *why* the count is excluded: it is hashed into the approval
store's dedup key, and a value that changes per recurrence makes one fault raise one approval per
occurrence.

**2b. Bound the targets** at `resolve_targets` (`:195`), the single source of the list, after dedup,
preserving declared order. Log once at `WARNING` when clipped, naming how many were dropped and why.

```
===SEARCH===
_TITLE_MAX = 120
_EVIDENCE_MAX = 4000
===REPLACE===
_TITLE_MAX = 120
_EVIDENCE_MAX = 4000

# AD-1267: the target list reaches the approval payload, whose canonical JSON is
# capped at 4,000 chars. Measured against the real validator with a maximal fault
# report: one 4,500-char target serialised to 6,127 and 12 targets of ~210 chars
# to 4,158 -- both rejected, so the fault became permanently unproposable.
# 8 x 64 measures 2,146 and leaves comfortable headroom.
_TARGETS_MAX = 8
_TARGET_NAME_MAX = 64
===END REPLACE===
```

### Section 3 — `src/probos/capability_request.py`: export the bound, nothing else

```python
#: AD-1267: the action-approval contract's own thread_id bound, exported so a
#: producer with a wider field (fault reports allow 128) narrows to the consumer's
#: contract instead of forwarding a value that will be rejected outright.
THREAD_ID_MAX_CHARS: int = _THREAD_ID_MAX
```

Circular-import check, run: `capability_request.py:41-42` imports only `probos.events` and
`probos.protocols` from the package; `repair_dispatch` sits in `cognitive/` above it, so a direct
import is clean.

Do **not** add `fit_action_payload`. Do **not** change `validate_action_payload`,
`_ACTION_PAYLOAD_MAX_CHARS`, `action_dedup_key`, `file_action_request`, `file_request` or
`_find_pending_action`.

### Section 4 — `src/probos/cognitive/repair_dispatch.py`

**4a. `__init__`.** Replace `self._proposed: set[str] = set()` with:

```python
# AD-1267: fault ids with a filing IN FLIGHT right now. This is concurrency
# control, NOT the record of what has been proposed -- the approval store holds
# that, durably, keyed on a payload that no longer varies per occurrence. So it
# releases unconditionally: if a filing committed and then raised, the next
# recurrence dedups onto the committed row rather than filing again. Bounded by
# the number of concurrent listener tasks, so it needs no cap and no trim.
self._inflight: set[str] = set()
```

Nothing outside this module reads `_proposed` — enumerate before deleting:
`grep -rn "_proposed" src/ tests/ ui/` and paste the result in the commit message. Expect hits only
in this file, in `*_PROPOSED` EventType members, and a `test_ad721d_2` local attribute.

**4b. `on_fault_event`.** Order matters; there must be **no await between the check and the add**.

1. Fix the docstring. It currently claims "this runs inline on the event bus" — false.
   `runtime._emit_event_local` creates an independent task per coroutine listener
   (`runtime.py:1751`), and that per-event concurrency is precisely why the guard is taken before the
   await. Say it swallows `Exception` but not `BaseException`, so cancellation propagates.
2. Keep the malformed-event guards unchanged.
3. `fault_resolved` → **return, clearing nothing.** State why inline: a resolved fault that recurs
   takes the create branch and gets a new `fault_id`, hence a new dedup key, hence a clean proposal.
   The old approval, if still pending, stays pending on purpose — the Captain has not answered it.
   Withdrawing it is out of scope and is not silently assumed here.
4. Keep the `enabled` and threshold gates unchanged.
5. Check the approval surface **before** guarding: if `self._requests` is `None` or lacks
   `file_action_request`, log at `info` (reuse the message at `_file_dispatch_request:147`) and
   return, having provably written nothing.
6. `report = self._faults.get(signature)` — a plain `def` (`fault_report.py:379`), so synchronous.
   `None` → return.
7. `fault_id = str(getattr(report, "id", "") or "") or signature`. The signature fallback keeps
   today's behaviour for a report with no id; document it rather than letting it differ silently.
8. `if fault_id in self._inflight: return` then `self._inflight.add(fault_id)`. **No await between
   7, 8.** That atomicity with respect to the event loop is what closes the fan-out storm without a
   lock.
9. ```python
   try:
       await self.propose(signature)
   finally:
       self._inflight.discard(fault_id)
   ```
   The `finally` is synchronous — no I/O, no await — so cancellation cannot skip it or stall the loop.

**4c. `propose`.** Keeps its signature `async def propose(self, signature: str) -> Any | None` and
its success log. Delete the `self._proposed.add(signature)` line. Its docstring must say it does not
take the in-flight guard — `on_fault_event` owns that — so a direct operator call is deliberate and
still safe, because the store deduplicates it.

**4d. `_file_dispatch_request`.** Keeps returning `Any | None`. Changes:

- Narrow the thread id: `(brief.thread_id or "")[:THREAD_ID_MAX_CHARS]`, with a comment naming both
  bounds (128 vs 64) and noting the full thread id is one lookup away via `params["fault_id"]`.
- `params` becomes `fault_id`, `signature`, `targets`, `brief` — with `brief` from
  `render_for_payload()`, still clipped at `_BRIEF_PREVIEW_MAX`.
- Add a comment above `params` stating the invariant: **every value here is hashed into
  `action_dedup_key`, so nothing that varies between recurrences of one fault may appear.** That
  comment is what stops the count being re-added later.
- `rationale` unchanged.

---

## Tests

Three files. **Every negative assertion needs a positive premise assertion beside it** — assert you
reached the path before asserting what did not happen on it.

### `tests/test_ad1267_recurrence_is_emitted.py` — the producer

Carry these forward from `.git/AD1264_test_ad1264_recurrence_reaches_the_dispatcher.py`; they were
sound.

1. `test_a_recurrence_emits_with_the_post_increment_count` — two faults → `[1, 2]`.
2. `test_every_recurrence_is_observable` — five faults → `[1, 2, 3, 4, 5]`, asserting
   `max(...) >= 2` with a message naming the dispatcher threshold.
3. `test_a_different_signature_starts_its_own_count` — `[1, 1, 2]`.
4. `test_a_resolved_fault_that_recurs_is_a_new_report` — new `id`, `occurrences == 1`, two events
   both carrying 1.
5. `test_an_emit_failure_still_lets_the_turn_finish` — exploding `emit_event`; `file_fault` still
   returns the coalesced report.

The `_Capture` double must expose its recording for the **test** to read. An assertion placed inside
a double is swallowed by `_emit_fault`'s own `except Exception` (`fault_report.py:405`) and proves
nothing.

### `tests/test_ad1267_one_pending_approval_per_fault.py` — the guarantee

6. **`test_the_key_is_stable_across_occurrence_counts`** — the P3 reproduction, at the level of
   `action_dedup_key`, using payloads built by the real `_file_dispatch_request` path at
   `occurrences` 2 and 3. Must fail against HEAD.
7. **`test_occurrences_two_three_and_seven_file_one_approval`** — real `FaultReportStore` →
   real `RepairDispatcher` → real `CapabilityRequestStore` on `tmp_path`. Drive seven faults,
   replay the captured events in order, assert exactly **one** pending request with `kind == "action"`.
   Positive premise: assert the first occurrence filed **nothing**, and assert ≥ 3 events crossed the
   threshold — otherwise "one approval" could mean "the path never ran".
8. **`test_the_approval_survives_a_restart`** — the P4/P5 reproduction end to end. File at
   occurrence 2, `stop()`, construct a **new** store on the same `db_path`, `start()`, drive
   occurrence 3, assert still one pending row and the **same request id**.
9. `test_concurrent_recurrences_file_one_approval` — the storm. Do **not** use a sleep. Use a
   rendezvous: a store double whose `file_action_request` parks until N callers are inside together,
   then releases; drive N concurrent `on_fault_event` tasks via `asyncio.gather`. Assert one filing.
   Then assert the guard is **released** afterwards by driving one more event and observing a second
   filing attempt reach the store — a guard that never releases would pass the first half alone.
10. `test_a_filing_that_commits_then_raises_does_not_file_twice` — a store whose
    `file_action_request` inserts and then raises. Assert the in-flight marker released, then drive
    the next recurrence and assert the real store dedups onto the committed row.
11. `test_a_cancelled_filing_releases_the_guard` — cancel a filing mid-await; assert
    `_inflight` is empty and `CancelledError` propagated (not swallowed). Ensure the coroutine
    actually ran before cancelling — a `create_task()` + immediate `cancel()` with no yield never
    executes the body and the assertion cannot fail. That exact vacuous test shipped in the reverted
    attempt.
12. `test_a_resolved_fault_that_recurs_can_propose_again` — resolve, recur, assert a **second**
    pending approval with a **different** `fault_id`.

### `tests/test_ad1267_payload_fits_the_contract.py` — the bounds

13. `test_an_ordinary_fault_with_a_128_char_thread_id_is_accepted` — the defect-4 reproduction. Must
    fail against HEAD with `validate_action_payload(...) is None`.
14. `test_the_thread_id_is_narrowed_not_dropped` — the stored value is the 64-char prefix, and
    `params["fault_id"]` still resolves the full report.
15. `test_targets_are_clipped_to_eight_by_sixty_four` — count and per-name length, declared order
    preserved, one WARNING logged.
16. **`test_a_maximal_fault_still_fits`** — the assertion that replaces the fitter. Build a fault
    with every field at its documented maximum (`error_text` 2,000, `attempted` 1,000, `tool_id` 128,
    `agent_id` 128, `thread_id` 128, `tool_trace_ref` 128), 8 targets of 64 chars, and assert
    `validate_action_payload(payload) is not None` **and** that the canonical JSON length is recorded
    in the assertion message. If a future field pushes this over, this test says so and names the number.
17. `test_the_brief_in_the_payload_has_no_occurrence_count` — assert the rendered payload brief does
    not contain the count, **and** that `render_markdown()` still does. Both halves, or this passes
    by rendering nothing.
18. `test_the_rationale_still_tells_the_captain_the_count` — the reconciliation in DD-2. Assert the
    count appears in `rationale`, and assert `rationale` is absent from the dedup key material by
    filing two requests differing only in rationale and asserting they dedup onto one.

---

## What this does NOT change

- The threshold constants. Do not touch `_DEFECT_MIN_OCCURRENCES`, `DEFAULT_PATTERN_THRESHOLD`,
  `REPEAT_THRESHOLD` or `propose_after_occurrences`.
- `RepairConfig.enabled`'s default. It stays `False` until AD-1268 lands.
- `action_dedup_key`, `_find_pending_action`, `validate_action_payload`, `file_action_request`,
  `file_request` — all untouched. Changing shared AD-1154 dedup semantics would affect browser
  actions too.
- The commit-then-emit ordering in `file_request`. DD-1 makes it harmless here; reordering it is a
  change to a store with many other callers.
- Behaviour for **decided** requests. That is AD-1268.
- No `fit_action_payload`. No `_Proposal` dataclass. No four-state model. No `_PROPOSALS_MAX`.
  No trim. No `asyncio.shield`, no owned task, no done-callback.
- No withdrawal of a pending approval when its fault resolves.

---

## Tracking

- `PROGRESS.md` — one CLOSED entry naming the measured before/after.
- `docs/development/roadmap.md` — Bug Tracker row for #1307.
- `DECISIONS.md` — AD-1267, recording DD-1 (identity lives in the store) and DD-4 (#1315 subsumed).
- Close #1315 as subsumed, citing P4/P5.
- Archive `prompts/ad-1264-a-recurring-fault-reaches-the-repair-dispatcher.md`.

## Acceptance criteria

- [ ] BF-854 is committed before this starts.
- [ ] Tests 6, 7, 8, 13 **fail against HEAD** before the fix. Paste the failures in the commit message.
- [ ] Full gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
- [ ] `grep -rn "_proposed" src/` returns no hits in `repair_dispatch.py`.
- [ ] `grep -rn "_PROPOSALS_MAX\|_Proposal\|fit_action_payload\|asyncio.shield" src/` returns nothing.
- [ ] The commit message states the guarantee in the DD-4 wording — *at most one pending approval per
      fault report, across restarts* — and names what it excludes (decided requests, AD-1268).
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop rule

**Count findings by location, not severity.** If adversarial review lands **two** findings inside the
in-flight guard or the payload-identity invariant — the seam this AD introduces — stop, revert,
preserve the patch, and hand the state model back. Do not open a third round. That threshold is
lower than the usual three because this seam has already produced seven findings across two rounds.

A finding elsewhere in the diff is an ordinary fix.

---

## Verified against codebase (2026-08-24)

```
HEAD f3348ca4, tree clean.

fault_report.py:258-265  coalesce branch, verbatim, returns without emitting
fault_report.py:269      id=uuid.uuid4().hex[:12]        (create branch only)
fault_report.py:281      occurrences=1
fault_report.py:287      self._emit_fault("FAULT_REPORTED", report)   <- sole emitter
fault_report.py:326      UPDATE fault_reports SET occurrences = ?, last_seen_at = ? WHERE id = ?
                         -> every other field is INVARIANT on coalesce
fault_report.py:379      def get(...)                    <- plain def, synchronous
fault_report.py:405      _emit_fault swallows its own failures

repair_dispatch.py:59    self._proposed: set[str] = set()
repair_dispatch.py:93-95 threshold gate
repair_dispatch.py:97    check           }  the storm: 19 lines and one await apart
repair_dispatch.py:116   add             }
repair_dispatch.py:167   "thread_id": brief.thread_id,   <- forwarded unnarrowed

repair_brief.py:46-47    _TITLE_MAX / _EVIDENCE_MAX      <- constants anchor
repair_brief.py:91       f"...the same error {self.occurrences} time(s):"  <- the unstable field
repair_brief.py:195      def resolve_targets(...)        <- unbounded

capability_request.py:63   _THREAD_ID_MAX = 64     (vs fault_report.py:58 = 128)
capability_request.py:186-197  key material includes canonical_params, EXCLUDES rationale
capability_request.py:292  _refresh_cache  -> SELECT ... FROM capability_requests  (all statuses)
capability_request.py:423  status != "pending" -> skip     <- why AD-1268 exists

config.py  RepairConfig.enabled: bool = Field(default=False, ...)   <- safe to land without AD-1268

Live probe:
  P3 occ2 key == occ3 key: False
  P4 same request id after restart (dedup survived): True ; pending rows: 1
  P5 pending rows now: 2 ; distinct fault_ids among them: {'abc123'}
```
