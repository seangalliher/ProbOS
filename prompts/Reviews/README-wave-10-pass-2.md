# Wave 10 Review Pass 2 — Sweep Summary

**Date:** 2026-05-03
**Scope:** 2 Workforce Cleanup prompts (AD-501 → AD-500), revised at commit `fd4b301` after pass-1.
**Reviewer posture:** Verify-first against live `src/`, relaxed tolerance per convention #15.
**Pass-1 baseline:** AD-501 ⚠️ Conditional (5 R / 3 Rec / 2 N), AD-500 ❌ Not Ready (6 R / 5 Rec / 3 N).

---

## Verdicts

| AD | Risk | Pass-1 | Pass-2 | Required-still-open | New findings |
|---|---|---|---|---|---|
| AD-501 | medium | ⚠️ Conditional | ✅ Approved | 0 | 0 |
| AD-500 | medium (was HIGH) | ❌ Not Ready | ✅ Approved | 0 | 1 (Recommended-class, non-blocking) |

**Totals:** 0 Required still open. 1 new Recommended-class finding (AD-500 `metadata` vs `payload` example), non-blocking because the prompt has a verify-at-build-time escape hatch.

**Convergence target met:** ✅ 2 of 2 prompts approved.

---

## Six high-priority verification points (per pass-2 dispatch)

| # | Check | Result |
|---|---|---|
| 1 | AD-500 SCOPE REFRAME completeness | ✅ Solution Overview "v1 ships 2 of 5"; title says "(Producer Side)"; Section 3 defers proactive-loop migration; v1-deliverables / Acceptance Criteria carry no consumer-side claims; Test Plan = 6 tests; AD-500a-1 listed under Deferred Grandchildren with explicit forcing function; DECISIONS.md template reflects producer-only. **Closing self-check:** 0 hits in shipping content for `work_item_store.add` / `DutyConfig` / `DUTY_WORK_ITEM_CREATED` / "3 of 5 capabilities" / `no_dual_dispatch` / "12 new tests" / "breaking change to proactive". All hits live in audit-trail Revision section and DECISIONS.md "Why scope-reframe" rationale, as expected. |
| 2 | AD-500 phantom fixes verified | ✅ `create_work_item` (workforce.py:992), `DutyScheduleConfig` (config.py:1397), Section 1 no-op, default `False`, TYPE_CHECKING guard, WorkItem field-name verify-at-build-time note all present. |
| 3 | AD-501 test triage matches HEAD | ✅ `pytest --collect-only` confirms 30 test_task_tracker.py + 12 test_notifications.py = 42 total. Section 5 reframed to "augment existing"; deletion of test_task_tracker.py confirmed; conftest.py:158/200 + test_notifications.py:7 enumerated. |
| 4 | Section 0 EventTypes consistent | ✅ `DUTY_WORK_ITEM_CREATED` dropped in favor of payload-discriminated existing `WORK_ITEM_CREATED`. Acceptance Criteria explicit: "No new EventType added". |
| 5 | Pre-check matches expected | ✅ `./scripts/phantom-api-precheck.ps1 prompts/ad-501-tasktracker-deprecation.md prompts/ad-500-dutyscheduler-workitem-migration.md` → 0 phantoms on both. |
| 6 | Solution Overview drift discipline (convention #12) | ✅ Both prompts: front-matter, Solution Overview, Dependencies, v1-deliverables, Acceptance Criteria, all aligned with Revision section. AD-500's reframe (highest drift risk) reads consistently top-to-bottom. |

---

## Hard-stop status

| # | Hard-stop | Triggered? |
|---|---|---|
| 1 | AD-500 scope reframe missed consumer-migration mention in shipping content | ✅ NO — closing self-check clean. |
| 2 | New Required-class issue introduced during revision | ✅ NO — single new finding is Recommended-class, non-blocking. |
| 3 | AD-501 stale test_task_tracker.py claims about notification tests, or count ≠ 30 | ✅ NO — count confirmed 30 at HEAD; test_task_tracker.py contains zero notification tests per pass-1 verification. |
| 4 | Pre-check finds phantoms | ✅ NO — 0 phantoms on both prompts. |
| 5 | `WorkItem` field-name uncertainty unresolvable + Builder round-trip | ⚠️ **RESOLVED AT REVIEW TIME.** HEAD shows `WorkItem.metadata` at workforce.py:583. The prompt's Section 2 verify-at-build-time note structurally prevents phantom-shipping; surfaced as Recommended #1 with one-line improvement (substitute `payload=` → `metadata=` in Section 2 example + Test row 2). Non-blocking because the escape hatch works as written. |

---

## New finding detail (AD-500 only)

**`WorkItem` field name `metadata` vs example `payload`** (Recommended-class).

- HEAD: `src/probos/workforce.py:583` declares `metadata: dict[str, Any] = field(default_factory=dict)`. No `payload` or `params` field.
- Prompt Section 2 example uses `payload={"duty_id": ..., "agent_type": ...}`.
- Prompt Section 2 line 80 acknowledges the uncertainty and instructs Builder to verify at build time.
- Test row 2 description repeats "payload containing `duty_id`".

**Status: non-blocking.** The verify-at-build-time note is the structurally correct response to user's hard-stop #5. Builder will read `workforce.py` near `:559` and substitute `metadata=` automatically. A one-line example fix would save a Builder read but is an optional polish, not a Required-class change.

---

## Wave 9B structural-defect pattern recurrence — closure check

Pass-1 surfaced **2 phantoms in AD-500** (`work_item_store.add()` + `DutyConfig`) — the third structural-defect recurrence in 3 waves (TrustNetwork → Procedure → WorkItemStore.add). Pass-2 confirms:

- Both phantoms removed from shipping content (verified by pre-check + manual closing self-check).
- The pattern repeats not because the reactive review pipeline misses it (pass-1 caught both), but because the **proactive drafting pipeline** does not validate kwargs against live signatures. Convention #21's recommendation (extend `phantom-api-precheck.ps1` to parse method calls and match kwargs against AST signatures) remains warranted as a Wave 11 forcing-function tooling-hygiene AD.

**Specifically:** the Section 2 `payload=` → `metadata=` slip in AD-500 is the SAME class of defect (kwarg-not-on-target-API) that Wave 11 tooling would catch automatically. The current pre-check passes both prompts because it does not parse `create_work_item(...)` kwargs against `WorkItem` dataclass fields. **Tooling-hygiene AD is reinforced, not weakened, by this finding.**

---

## Recommended Builder order

Per dispatch:

1. **AD-501 first** (lower-risk; mostly mechanical file moves + import updates + delete).
2. **AD-500 second** (medium-risk producer-only; constructor signature unchanged in v1).

**Pre-build reminder for AD-500 Builder:** when implementing Section 2, read `workforce.py` near `:559` first; expect `metadata=` (HEAD-confirmed at workforce.py:583).

**Cross-prompt source-file overlap:** none (AD-501 modifies `runtime.py` + deletes `task_tracker.py` + edits 3 test/conftest files; AD-500 adds method to `duty_schedule.py` + adds field to `config.py`). Sequencing is safe.

---

## Convention audit (post-revision)

| Convention | AD-501 | AD-500 |
|---|---|---|
| #3 coordinator-then-dispatch transitional flag | n/a | ✅ flag present + default `False` (compliant) |
| #5 narrow dependency injection | n/a | ✅ `work_item_store` injected at call time (constructor unchanged) |
| #7 no-theater | ✅ | ✅ (DUTY_WORK_ITEM_CREATED dropped; Section 1 explicit no-op) |
| #12 Solution Overview drift discipline | ✅ | ✅ (post-reframe; closing self-check clean) |
| #14 aggressive pre-deferral | ✅ 4 of 5 | ✅ 2 of 5 (was 3 of 5; reframe deepened deferral) |
| #15 relaxed tolerance | ✅ converged to ✅ | ✅ converged to ✅ (highest-risk reservation not needed) |
| #16 phantom-API pre-check (mandatory Wave 9+) | ✅ 0 phantoms | ✅ 0 phantoms |
| #20 cross-wave dep verifies SHIPPED | ✅ | ✅ |
| #21 structural-defect pattern propagation | ✅ no recurrence | ✅ pattern resolved (but tooling gap remains; see above) |
| #22 v1 isolation | ✅ | ✅ |

---

## Final convergence judgment

**Wave 10 pass-2: 2 of 2 ✅ Approved.** Convergence target met without invoking the relaxed-tolerance reservation. AD-500's largest-revision-in-wave (full scope reframe) was executed cleanly with zero drift between sections and zero new Required-class findings. The single new Recommended-class finding (AD-500 `metadata` vs `payload`) is structurally non-blocking because the prompt carries a verify-at-build-time escape hatch.

**Tooling-hygiene AD recommendation for Wave 11: STILL WARRANTED.** This finding is itself evidence — the current pre-check does not parse `create_work_item(...)` kwargs against `WorkItem` dataclass fields. Pre-check parsing extensions remain the recommended Wave 11 forcing function.

Builder dispatch unblocked.
