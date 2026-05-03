# Wave 10 Review Pass 1 — Sweep Summary

**Date:** 2026-05-03
**Scope:** 2 Workforce Cleanup prompts (AD-501 → AD-500).
**Reviewer posture:** Verify-first against live `src/`, relaxed tolerance per convention #15 (1 ⚠️ allowed on highest-risk).
**Highest known AD before wave:** AD-641f (umbrella AD-641 closed via AD-641a..f). Highest known BF: BF-257.

---

## Verdicts

| AD | Risk | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|
| AD-501 | medium | ⚠️ Conditional | 5 | 3 | 2 |
| AD-500 | HIGH | ❌ Not Ready | 6 | 5 | 3 |

**Totals:** 11 Required, 8 Recommended, 5 Nits across the wave.

**Tolerance status:** AD-500 is ❌ (out of tolerance for the relaxed cap of 1 ⚠️). AD-501 is ⚠️ where dispatch expected ✅. **The wave does NOT pass pass-1 within tolerance.** A revision pass is mandatory before pass-2 dispatch.

---

## High-priority verification result table

| Check | Result |
|---|---|
| AD-501 file paths and line numbers grep-confirmed | ✅ runtime.py:69/234/543/1058/1526 + task_tracker.py:149/177/260 confirmed exact. Test count was wrong (30 actual vs 32 claimed). |
| AD-500 cross-AD dep on AD-498 (`duty` work type registered) | ✅ `duty` registered at `workforce.py:206`. No AD-498 extension needed. **Hard-stop #2 NOT triggered.** |
| AD-500 `list_work_items` filter signature | ✅ Confirmed at `workforce.py:1066-1076` — accepts `work_type`, `status`, `assigned_to`, `limit`, `offset`. |
| AD-500 booking surface (`start_booking` / `complete_booking`) | ✅ Confirmed at `workforce.py:1371` / `:1424`. |
| AD-500 `DutyConfig.use_work_items` shape | ❌ **Phantom class.** Real class is `DutyScheduleConfig` at `config.py:1397`. Required #2. |
| AD-500 `no_dual_dispatch` test #10 structural-vs-runtime | ❌ Untestable as drafted. Required #6. |
| AD-500 EventType collision (`DUTY_WORK_ITEM_CREATED`) | ✅ No collision; `events.py` has zero `DUTY_*` events. (But redundant with `WORK_ITEM_CREATED` — Recommended #1.) |

---

## Hard-stop status

| # | Hard-stop | Triggered? |
|---|---|---|
| 1 | Phantom API NOT introduced by the prompt itself | ⚠️ **YES — AD-500.** Two phantoms: `work_item_store.add()` and `DutyConfig`. Both are recurrences of the Wave 9B structural-defect pattern (convention #21). |
| 2 | AD-500 cannot be implemented without AD-498 extension | ✅ NO — `duty` work type already registered at `workforce.py:206`. |
| 3 | AD-501 NotificationQueue has hidden state on TaskTracker | ✅ NO — clean separation. |
| 4 | Cross-prompt source-file conflicts on `runtime.py` | ✅ NO — AD-500 doesn't touch `runtime.py`; AD-501 modifies it; sequencing AD-501 → AD-500 is safe. |
| 5 | AD-500 proactive.py call site more entangled than prompt assumes | ⚠️ **YES** — 6 unaddressed `record_execution` call sites + double-select between `_think_for_agent` and outer poll loop. Surfaced as Required #4 + #5 with reframe-recommendation in Recommended #5. |

---

## Wave 9B structural-defect pattern recurrence

**RECURRED in AD-500.** Two distinct pattern types:

1. **Wrong method shape (phantom kwargs/method):** `runtime.work_item_store.add(work_item)` vs real `await runtime.work_item_store.create_work_item(**kwargs)`.
2. **Wrong class name / missing field:** `DutyConfig.use_work_items` vs real `DutyScheduleConfig` (or `ProactiveCognitiveConfig.duty_schedule`).

Convention #21 (Wave 9 retrospective addendum) anticipated this: *"the retrospective lesson did not propagate into the proactive drafting pipeline — only the reactive review pipeline."* AD-500 is direct evidence the gap persists. The recommended tooling extension (`scripts/phantom-api-precheck.ps1` parsing method calls and validating kwargs against live signatures) would have caught BOTH defects mechanically. **Recommend filing the tooling hygiene AD as a Wave 11 forcing function.**

AD-501 had a related but lower-severity slip: a phantom `api.py` reference (no such file at HEAD; routers/ is the actual surface) plus an unrelated naming overlap (`routers/deps.py:get_task_tracker` is unrelated to `TaskTracker`). Surfaced as AD-501 Required #5.

---

## Top failure modes

1. **Phantom API drift in HIGH-risk migration drafts.** Both AD-500 phantoms originate in Section 2 + Section 5 (the migration mechanics + transitional flag) — exactly the highest-stakes surfaces. The pre-check script appears not to have run on this wave (or it ran and was tuned to pass these patterns). Run it and tighten signatures against live before pass-2 dispatch.

2. **Test triage assumption defects (AD-501).** The prompt's mental model (32 tests with mixed notification + tracker concerns, move some, delete some) does not match HEAD: 30 tests, all tracker-orphan, plus an existing `test_notifications.py` with 12 notification tests already in place. Re-frame test triage as "delete entire `test_task_tracker.py`; one-line import update in existing `test_notifications.py`."

3. **HIGH-risk migration entanglement under-specified (AD-500).** The proactive loop has 6 `record_execution` call sites and `_think_for_agent` self-selects the duty. The prompt's "open booking, call `_think_for_agent`, close booking" mental model omits both surfaces. Recommend reframing v1 scope to ship the WorkItem-emit method only, defer the proactive loop migration to AD-500a-1.

---

## Recommended next steps

1. **Revision pass on both prompts.** Apply all Required findings; fold Recommended unless they expand v1 scope; judgment-call Nits.
2. **Re-run `scripts/phantom-api-precheck.ps1`** on revised prompts; expect zero phantoms post-revision.
3. **Pass-2 review** appended as `## Second-Pass Review (2026-05-03)` on each review file. Convergence target: 2 ✅, but if AD-500 still has structural concerns after revision, ⚠️ within tolerance is acceptable.
4. **Consider scope reframe for AD-500** (per AD-500 Recommended #5): ship `DutyScheduleTracker.emit_due_duties_as_work_items` as the v1 surface only; defer proactive loop migration to AD-500a-1. This drops 6 of 12 tests and moves the breaking-change risk out of Wave 10 entirely.

---

## Cross-AD dependency verification (per convention #20 — read SHIPPED code, not prompts)

- AD-496 (WorkItemStore) — ✅ shipped at `workforce.py:905`. AD-501 + AD-500 both verified against shipped code.
- AD-498 (Work Type Registry) — ✅ shipped at `workforce.py:248` with `duty` type pre-registered at `:206`. AD-500 Section 1 reduces to verify-only.

---

## Convention audit (23 standing conventions across Wave 5/5-7/8/9 retrospectives)

| Convention | AD-501 | AD-500 |
|---|---|---|
| #3 coordinator-then-dispatch transitional flag | n/a | ✅ flag present (`use_work_items`); ⚠️ default value posture (Recommended #3) |
| #5 narrow dependency injection | n/a | ❌ unspecified injection type (Required #3) |
| #7 no-theater | ✅ | ⚠️ `DUTY_WORK_ITEM_CREATED` redundant (Recommended #1); Section 1 no-op (Recommended #2) |
| #14 aggressive pre-deferral | ✅ 4 of 5 | ✅ 3 of 5 |
| #15 relaxed tolerance (1 ⚠️ allowed on highest-risk) | ⚠️ unexpected | ❌ out of tolerance |
| #16 phantom-API pre-check (mandatory Wave 9+) | n/a | ❌ apparent miss — 2 phantoms at draft time |
| #20 cross-wave dep verifies SHIPPED | ✅ | ✅ |
| #21 structural-defect pattern propagation | ✅ no recurrence | ❌ 2 recurrences (method shape + class name) |
| #22 v1 isolation | ✅ | ✅ scope explicit; deferrals named |

All other conventions either no-op for these prompts or pass — the violations cluster around #15/#16/#21 on AD-500 and #14-test-scope on AD-501.

---

## Author dispatch decision

**Dispatch revision pass.** AD-501 needs ~5 mechanical fixes (test count, test_notifications.py framing, conftest path, routers naming clarification, runtime.py:237 note). AD-500 needs both phantoms fixed (Required #1 + #2), constructor signature spec (#3), record_execution migration spec (#4), `_think_for_agent` parameter wiring (#5), test #10 reframe (#6), plus the recommended scope reframe to drop the breaking-change risk from v1.

If AD-500 cannot be revised to ✅ in pass-2 (i.e. the `_think_for_agent` integration model remains contested), prefer the Recommended #5 scope reframe over a third pass: ship the emit method only, file AD-500a-1 for the proactive loop migration. Wave 10 should not extend beyond pass-2.
