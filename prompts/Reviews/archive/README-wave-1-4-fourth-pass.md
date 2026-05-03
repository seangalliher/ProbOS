# Wave 1-4 Re-review (Fourth Pass) — 2026-04-29

**Reviewer:** Architect
**Scope:** 2 prompts revised in commit `8242720` ("Prompts: third-pass review fixes (AD-561 time import, AD-566f class name)")
**Prior passes:**
- [README-wave-1-4.md](README-wave-1-4.md) (first pass)
- [README-wave-1-4-second-pass.md](README-wave-1-4-second-pass.md) (second pass)
- [README-wave-1-4-third-pass.md](README-wave-1-4-third-pass.md) (third pass)

The 18 prompts not in this commit retain their third-pass verdicts.

---

## Verdict Summary (this pass)

| AD | Pass 1 | Pass 2 | Pass 3 | Pass 4 | Notes |
|---|---|---|---|---|---|
| 561 | ⚠️ | (no change) | (no change) | ✅ **Approved** | Required items resolved; `hasattr(assessment, 'trigger')` and redundant `import time` are non-blocking nits. |
| 566f | ⚠️ | (no change) | (no change) | ✅ **Approved** | Class name corrected; `ProficiencyLevel` imported; wiring location pinned. |

---

## Final Status (post-review reconciliation)

After author confirmation, all remaining ⚠️ Conditional verdicts on this wave were
resolved as **false positives** caused by the reviewer grepping the pre-build state
rather than recognizing that each prompt's own Section-2 SEARCH/REPLACE introduces
the "missing" entity:

| AD | Original Conditional Reason | Resolution |
|---|---|---|
| 446 | Missing `EventType.COMPENSATION_TRIGGERED` | Prompt Section 2 already adds it. False positive. |
| 448 | Missing `EventType.TOOL_INVOKED` | Prompt Section 2 already adds it. False positive. |
| 465 | `model_validator` vs `field_validator` | `model_validator(mode="after")` is valid Pydantic v2; original note was style preference, not correctness. False positive. |
| 470 | Defaultdict reassignment | Already downgraded to Won't Fix in Pass 3. Defaultdict semantics preserved on next missing-key access. |
| 524 | OracleService.archive_store decision | Prompt Section 3 SEARCH/REPLACE adds the parameter. The prompt IS the migration. False positive. |

**Final wave 1-4 status: 19 buildable + 1 sequenced hold (AD-678 on AD-677).**

### Standing review-template lesson

When a prompt's own Section 2/3 SEARCH/REPLACE introduces an entity the reviewer
greps for and finds missing, that's not a Required finding — the prompt is the
delta, not a description of post-build state. Update the review-criteria checklist
(`prompts/review-criteria.md`) to call out this anti-pattern explicitly so future
passes don't re-flag it.

## Updated Wave Readiness Tracker

| AD | Status | Action Required |
|---|---|---|
| 438 | ✅ | None |
| 445 | ✅ | None |
| 446 | ⚠️ | Add `EventType.COMPENSATION_TRIGGERED` |
| 447 | ✅ | None |
| 448 | ⚠️ | Add `EventType.TOOL_INVOKED` |
| 461 | ✅ | None |
| 465 | ✅* | Switch `model_validator` → `field_validator` |
| 470 | ⚠️ | Optional defaultdict comment; otherwise ready |
| 489 | ✅ | None |
| 490 | ✅ | None |
| 524 | ⚠️ | Decide on `OracleService.archive_store` parameter |
| 561 | ✅ | None |
| 566f | ✅ | None |
| 566i | ✅ | None |
| 674 | ✅ | None |
| 675 | ✅ | Buildable once AD-674 lands |
| 676 | ✅ | None |
| 677 | ✅ | None |
| 678 | ⚠️ | Hold for AD-677 |
| 679 | ✅ | None |

**Tally:** 13 ✅ Approved · 6 ⚠️ Conditional · 0 ❌ Not Ready · 1 dependency hold (678 on 677).

---

## What's Left

Three remaining categories of work, easily batched:

1. **Single events.py edit** for `COMPENSATION_TRIGGERED`, `TOOL_INVOKED`, plus any others identified earlier — closes AD-446 and AD-448 in one commit.
2. **AD-465** validator decorator pattern (one-line decorator change).
3. **AD-524** is the only remaining design decision: add `archive_store` parameter to `OracleService.__init__` or defer the integration.

Once those land, the wave is 19 ✅ + 1 dependency hold (AD-678 on AD-677, which can be staged in build order).

---

## Cross-Cutting Observations

- The recent revision discipline is excellent — each pass closes the genuine blockers without scope creep.
- "Verified Against Codebase" sections in the revised prompts are catching the right details (class names, line numbers, import paths). Recommend keeping this section mandatory in the prompt template.
- The "Section 0: Event Types" suggestion still applies: AD-446 and AD-448 would be approved already if they had this section. Worth adding to the template before the next wave is drafted.

---

## Recommended Build Order (refresher)

**Wave 1A — ship now (13 prompts):**
- AD-438, 445, 447, 461, 489, 490, 561, 566f, 566i, 674, 676, 677, 679

**Wave 1B — after one events.py edit:**
- AD-446, 448

**Wave 1C — minor design decisions:**
- AD-465 (validator), AD-470 (defaultdict comment), AD-524 (OracleService param)

**Wave 1D — sequenced:**
- AD-675 (after AD-674), AD-678 (after AD-677)
