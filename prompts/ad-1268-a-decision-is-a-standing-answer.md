# AD-1268 — a decision is a standing answer, so a refused repair is not asked again

**Status:** Ready to build
**Depends on:** **AD-1267 must land first.** This adds the second half of its guarantee.
**Blocks:** turning `RepairConfig.enabled` on. Until this lands, enabling repairs ships a slow
approval storm.
**Estimated tests:** ≥ 9 new

---

## Numbering

Allocated in the same wave as AD-1267. Highest before this wave: **AD-1266**, **BF-853**.

- **This work is AD-1268.** Next free AD after this one: **AD-1269**. Next free BF: **BF-855**.

---

## Problem

AD-1267 makes the approval store the durable owner of repair-proposal identity, and its dedup runs
through `_find_pending_action`, which skips anything already decided:

```python
# capability_request.py:423
if req.status != "pending" or req.kind != "action" or req.payload is None:
    continue
```

So AD-1267's guarantee stops at *pending*:

> At most one **pending** repair approval exists per fault report, across restarts.

A fault whose approval the Captain **denied** is therefore proposed again on its next recurrence, and
on the one after that. With AD-1267's producer fix, `FAULT_REPORTED` now fires on **every**
occurrence, so a hot tool failing in a loop produces one approval per failure for a decision the
Captain has already made. The old in-process `_proposed` set masked this by holding forever; removing
it — correctly — exposes it.

This is not a defect in AD-1267. It is the half AD-1267 deliberately declined to fuse into its own
seam, and it is why `RepairConfig.enabled` stays `False` until this lands.

---

## Solution

### DD-1 — Any decision is a standing answer for that fault report

| Prior request for this `fault_id` | Next recurrence |
|---|---|
| none | proposes |
| `pending` | holds (AD-1267, via `_find_pending_action`) |
| `denied` | **holds** — the Captain answered |
| `approved` | **holds** — a dispatch is in flight; asking again is noise |
| `fulfilled` | **holds** — see the cost below |
| `failed` | **holds** — see the cost below |

One rule, not five: **a fault report that has ever raised a decided approval does not raise another.**

**The escape hatch is resolution, not a timer.** `FaultReport.id` is minted fresh on the create branch
and a *resolved* fault that recurs takes that branch (`fault_report.py:258-269`), so the new report
carries a new `fault_id`, a new dedup key, and asks cleanly. That is the same id-rotation property
AD-1267 relies on, used a second time. `repair_verification.verify_and_close` resolves a fault whose
repair held (`repair_verification.py:192`), so the successful path re-arms itself for free.

**The cost, stated rather than hidden.** A repair that was dispatched and did **not** hold will not
automatically ask again: the fault stays `open`, keeps incrementing, stays in
`FaultReportStore.list_open()`, and emits on every recurrence — but raises no new approval until the
report is resolved or dismissed. That is deliberate. The alternative is ask → approve → dispatch →
fail → ask, a loop that spends deep-tier tokens on a repair that is already known not to work, which
is the exact harm `RepairConfig.enabled`'s docstring says the approval gate exists to prevent. A
visible, non-escalating fault is the better failure.

**Do not build a retry budget, a cooldown, or an attempt counter.** A bounded retry whose expiry is
indistinguishable from success is the BF-840 defect, and there is no measured case demanding one.

### DD-2 — The lookup lives in the store, not in the dispatcher's reach

The dispatcher must not scan `store._cache`. Private-attribute access across a module boundary is a
standing review blocker, and the cache is the store's business. Add one narrow **public, synchronous**
read method beside `_find_pending_action`:

```python
def find_action_requests_by_param(
    self,
    param_key: str,
    param_value: str,
    *,
    statuses: tuple[str, ...] | None = None,
) -> list[CapabilityRequest]:
```

Requirements:

- `kind == "action"` and `payload is not None` only; compare `payload["params"].get(param_key)`
  against `param_value` as strings.
- `statuses=None` means every status. Otherwise filter to those given.
- Return oldest-first by `created_at`, so "was this ever decided" and "what was decided first" are
  both answerable.
- **Synchronous**, matching `_find_pending_action` and `count_pending_sync`. It reads the cache and
  does no I/O, so making it `async` would buy nothing and add an await to the dispatcher's
  reservation window — which AD-1267 requires to stay await-free.
- Defensive on shape: a payload whose `params` is not a dict is skipped, not raised on.

**Cost:** an O(n) scan of the cache per call, where n is every request ever filed —
`_refresh_cache` loads all statuses (`capability_request.py:292-306`). This matches
`_find_pending_action`'s existing cost and is not new, but it is now paid twice per fault event.
Note it in the docstring. Do **not** add an index or a second cache here; if the scan ever matters it
is its own AD with its own measurement.

### DD-3 — The dispatcher asks before it reserves

In `on_fault_event`, between resolving the report and taking AD-1267's in-flight guard:

```python
decided = store.find_action_requests_by_param(
    "fault_id", fault_id, statuses=("approved", "denied", "fulfilled", "failed"),
)
if decided:
    # log once at debug, naming the status and the request id
    return
```

Placement matters: **before** the in-flight `add`, so a held fault never enters the guard, and
**after** the surface check, so a missing store is still the earlier and cheaper return. The call is
synchronous, so it does not open an await window between the presence check and the reservation.

Guard the call with `hasattr(store, "find_action_requests_by_param")` — repair dispatch is wired
against whatever `runtime.capability_request_store` is, and the existing code already tolerates a
store lacking `file_action_request` (`repair_dispatch.py:145`). A store without the method degrades
to AD-1267 behaviour (pending-only dedup); log that once at `debug`.

**Log at `debug`, not `warning`.** This fires on every recurrence of a decided fault — by design,
possibly for a long time — and a WARNING per tool failure is its own storm.

---

## Tests

New file `tests/test_ad1268_a_decision_is_a_standing_answer.py`. Real stores on `tmp_path`; every
negative assertion needs a positive premise beside it.

1. `test_a_denied_repair_is_not_proposed_again` — drive to occurrence 2, assert **one** pending
   request (the premise), `decide(...)` it denied, drive occurrences 3, 4 and 5, assert
   `list_pending()` is **empty** and no new request of any status was created. Assert the events
   actually crossed the threshold, or "no new approval" could mean "the path never ran".
2. `test_an_approved_repair_is_not_proposed_again_while_it_is_in_flight` — same, status `approved`.
3. `test_a_fulfilled_repair_is_not_proposed_again` — same, status `fulfilled`; the docstring must
   state this is the deliberate cost in DD-1, so a future reader sees it was chosen.
4. `test_resolving_the_fault_re_arms_the_proposal` — deny, then `FaultReportStore.resolve(...)`, then
   recur. Assert a **new** request exists **and** that its `params["fault_id"]` differs from the
   denied one. Both halves — a new request under the *same* fault id would be the bug.
5. `test_the_standing_answer_survives_a_restart` — deny, `stop()`, new store on the same `db_path`,
   `start()`, recur. Assert nothing new is filed. This is the whole point of putting the record in the
   store.
6. `test_a_pending_request_still_holds` — AD-1267's guarantee is not regressed by this change.
7. `test_the_lookup_ignores_other_faults_and_other_kinds` — seed a denied action request for a
   *different* `fault_id` and a `kind="build"` request, assert neither suppresses this fault.
8. `test_a_malformed_payload_row_does_not_break_the_lookup` — seed a row whose `params` is not a
   dict; assert the lookup skips it and returns the genuine match.
9. `test_a_store_without_the_method_degrades_to_pending_only` — a double lacking
   `find_action_requests_by_param`; assert a denied fault **does** propose again (AD-1267 behaviour)
   and that the degradation was logged, rather than the dispatcher raising.

---

## What this does NOT change

- `RepairConfig.enabled`'s default. It stays `False`. Enabling repairs is an operator decision;
  this AD removes the reason it was unsafe, it does not make the choice.
- `_find_pending_action`, `action_dedup_key`, `validate_action_payload`, `file_action_request` —
  untouched. AD-1154's shared dedup semantics must not shift for browser actions.
- The in-flight guard, `params` contents, `render_for_payload`, the target bounds, the thread-id
  narrowing — all AD-1267, all frozen here.
- No cooldown, no retry budget, no attempt counter, no expiry, no timer.
- No withdrawal or auto-denial of a pending approval when its fault resolves.
- No index, no second cache, no schema change.

---

## Tracking

- `PROGRESS.md` — CLOSED entry recording the completed guarantee: *at most one repair approval per
  fault report, ever, durably* — and the cost (a failed repair does not re-ask until resolved).
- `DECISIONS.md` — AD-1268, recording DD-1's one rule and why no cooldown exists.
- `docs/development/roadmap.md` — note that `repair.enabled` is now safe to turn on.

## Acceptance criteria

- [ ] AD-1267 is committed before this starts.
- [ ] Test 1 fails against post-AD-1267 HEAD before this fix — it must reproduce the denied storm.
      Paste the failure in the commit message.
- [ ] Full gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
- [ ] `grep -rn "_cache" src/probos/cognitive/repair_dispatch.py` returns nothing — the dispatcher
      never reaches into the store's internals.
- [ ] `grep -rn "cooldown\|retry_after\|attempts" src/probos/cognitive/repair_dispatch.py` returns
      nothing.
- [ ] The commit message states the completed guarantee and the cost in DD-1's wording.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop rule

If review lands **two** findings inside `find_action_requests_by_param` or the suppression check,
stop, revert, and hand back. This AD is one query and one branch; if it needs a protocol, the state
model is wrong again and grinding it out is what cost the previous two attempts.

---

## Verified against codebase (2026-08-24)

```
HEAD f3348ca4, tree clean.

capability_request.py:292-306  _refresh_cache -> SELECT ... FROM capability_requests   (ALL statuses,
                               so a decided request IS in the cache after a restart)
capability_request.py:422      def _find_pending_action(self, key: str)      <- sync, cache scan
capability_request.py:423      if req.status != "pending" ... continue       <- the gap this closes
capability_request.py:438      def count_pending_sync(...)                   <- precedent for a
                                                                                public sync cache read
capability_request.py:57       RequestStatus = pending|approved|denied|fulfilled|failed

fault_report.py:258-269        resolved fault recurs -> create branch -> new uuid4 id
                                                                  <- the escape hatch in DD-1
repair_verification.py:192     verify_and_close -> FaultReportStore.resolve(...)
repair_dispatch.py:145         existing precedent for degrading on a store lacking a method

config.py  RepairConfig.enabled: bool = Field(default=False, ...)

Live probe (P4/P5), same run that grounded AD-1267:
  restart preserves the durable dedup: same request id after restart: True
```
