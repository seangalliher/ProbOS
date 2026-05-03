# Wave 12 — Review Pass 1 Sweep Summary

**Date:** 2026-05-03
**Scope:** 1 single-AD wave (AD-477 Naval Organization v1: Captain's Log + Plan of the Day).
**Reviewer:** Architect (Stage 1 of WAVE-12-DISPATCH.md).
**Convention regime:** Relaxed tolerance (Wave 5-7 Addendum #15) — 1 ⚠️ allowed.

---

## Verdicts

| AD | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|
| AD-477 | ⚠️ Conditional | 3 | 3 | 3 |
| **Totals** | **⚠️** | **3** | **3** | **3** |

Within tolerance: 1 ⚠️ on a single-AD wave is acceptable per convention #15.

## High-Priority Verification Results

| Verification point | Result |
|---|---|
| 1. Pre-deferral honesty (no QualProg/3M/DamageControl/SORM/scheduled-duties smuggled) | ✓ Clean. v1 ships only Captain's Log + Plan of the Day. |
| 2. AD-566/539/595e read-only consumer status | ✓ Confirmed by grep. No imports, no writes from `naval/` to `qualification_battery`/`gap_pipeline`/`qualification_gates`. |
| 3a. `runtime.episodic_memory.recent_for_agent` signature | ✓ Exists at `episodic.py:1747`, async, signature `(agent_id: str, k: int = 5) -> list[Episode]`. **However**, by-date episode retrieval (used by Section 2's `generate_for_date`) has no live API — Required #2. |
| 3b. `runtime.dreaming_engine` attribute existence | ✗ **Phantom.** Runtime has `dream_scheduler`, NOT `dreaming_engine`. Same shape as duty-tracker phantom. Required #1. |
| 3c. `runtime.work_item_store.list_work_items` kwargs | ✓ kwarg name `status` valid. ✗ kwarg VALUE `"pending"` not in `WorkItemStatus` enum (canonical is `"open"`). Required #3. |
| 3d. `runtime.ward_room` thread query API read-only path | ✓ `list_threads(channel_id, limit, offset, sort, include_archived)` at `ward_room/service.py:289`, async, read-only. |
| 4. Section 0 EventType collisions (`CAPTAINS_LOG_GENERATED`, `PLAN_OF_DAY_GENERATED`) | ✓ Zero collisions in `events.py`. |
| 5. Public-attribute wiring (Wave 5 convention #1, no underscore) | ✓ `captains_log_service`, `plan_of_day_service`, `captains_log_start_task`, `plan_of_day_start_task` — all public. |

## Hard-Stops Hit

None of the five hard-stops in the dispatch fired:

1. ✓ Phantom API in v1 shipping content — the documented `runtime.duty_schedule_tracker` NOTE is correctly negative-framing (audit trail, not usage assertion). New phantoms (`runtime.dreaming_engine`, `status="pending"`) are review-tier Required, not hard-stops.
2. ✓ AD-566/539/595e write-side modifications — none. v1 is structurally read-only with respect to those surfaces.
3. ✓ Section 0 EventType collisions — none.
4. ✓ Background task `CancelledError` handling — Test #12 mentions cancellation but assertion strength is Recommended #3 territory, not hard-stop.
5. ✓ Output path conflicts with existing `data/` — none.

## Wave 9B Structural-Defect Pattern Recurrence

**Target: 0. Actual: 1 (with one new shape).**

- **Recurrence (same shape):** `runtime.dreaming_engine` is structurally identical to the already-mitigated `runtime.duty_schedule_tracker` phantom — both are "private to a startup-phase module / not exposed on `runtime`" patterns. Wave 9B retrospective convention #21 says proactive drafting pipeline still under-catches these. AD-685 kwarg pre-check doesn't catch attribute existence — that's still convention #16 territory (`scripts/phantom-api-precheck.ps1` symbol-existence check).
- **New shape:** `status="pending"` is a phantom kwarg VALUE (the kwarg name `status` is valid; the value `"pending"` is not in the live `WorkItemStatus` enum). AD-685 v1 does not validate kwarg values against enum members. Bank as candidate for AD-685c or AD-685e (enum-value validation against live enum members).

Both will be fixed mechanically in Stage 2 revision.

## Top Failure Modes Surfaced

1. **Consumer-side spec under-specification on cross-cutting reads.** AD-477's two services aggregate from four different runtime surfaces (`episodic_memory`, `dreaming_engine`, `work_item_store`, `ward_room`). The prompt's `Verified Against Codebase` section verified 2 of 4. The two unverified ones produced the two consumer-path Required findings. **Convention reinforcement:** verify-first must enumerate ALL consumer surfaces, not just the ones the drafter remembered to check.
2. **Phantom kwarg value (not name).** AD-685 v1's kwarg-name validation is a partial mitigation; value-drift on enum-typed kwargs is a separate class. New tooling-hygiene candidate.
3. **Negative-framing pattern works.** The `runtime.duty_schedule_tracker` NOTE is the right shape — explicitly says symbol does NOT exist, defers to AD-477f, no usage assertion. Ratifies the pattern from earlier mitigation. Required #1 should produce a parallel NOTE for `runtime.dreaming_engine`.

## Recommendations for Stage 2 Revision

Apply all 3 Required findings (mechanical fixes). Fold Recommended #1 (Field default_factory) and #2 (verify-first audit trail completion) — both convention discipline. Recommended #3 (Test #12 wording) is judgment-call; mild preference to apply for clarity. Nits 1-3 are optional; not worth the diff churn.

Convergence target for Pass 2: ✅ (single-AD waves with 3 mechanical Required typically converge in one revision).

## Tooling-Hygiene Banking

For the post-wave retrospective:

- **AD-685 extension candidate (kwarg value validation).** Surface count after this review: 1. If the same shape recurs in Wave 13+, escalate to scoped tooling AD.
- **Convention #16 enforcement strength.** Verify-first audit-trail completeness is uneven across waves. Consider adding to dispatch-time pre-check: "every `<obj>.<method>` reference in the prompt body MUST appear in the Verified Against Codebase block, OR be tagged as Hard-Stop." Mechanical script candidate.

---

**Output artifacts:**
- `prompts/Reviews/ad-477-naval-organization-v1-review.md` (this review)
- `prompts/Reviews/README-wave-12.md` (this sweep summary)

**Next stage:** WAVE-12-DISPATCH.md Stage 2 — revision pass on AD-477.
