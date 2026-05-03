# Wave 15 Pass-1 Sweep Summary

**Date:** 2026-05-03
**Stage:** Architect Review Pass 1
**Prompts reviewed:** 1 (AD-685b)
**Convergence target:** 1 ✅ at pass-2.

## Verdicts

| AD | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|
| AD-685b | ⚠️ Conditional | 2 | 4 | 3 |

**Total:** 1 ⚠️ Conditional, 0 ✅ Approved, 0 ❌ Not Ready.

Per convention #15 (relaxed tolerance: 1 ⚠️ allowed), Wave 15 is on-track for pass-2 convergence.

## Pre-flight summary

- src/probos Python file count: **409** (Wave 11 baseline was 403 — marginal drift, see AD-685b Recommended #2).
- Calibration sweep targets: all 3 archived prompts confirmed present in `prompts/archive/`.
  - `ad-641c-ward-room-thread-priority.md`
  - `ad-500-dutyscheduler-workitem-migration.md`
  - `ad-487-self-distillation-v1.md`
- Phantoms confirmed **gone** from shipping content of all 3 calibration targets (grep on `LLMClient.chat(`, `WorkItemStore.add`, `event_log.query(` returned 0 matches each).
- `src/probos/startup/finalize.py` exists at 81985 bytes — Pattern A's "finalize.py instantiation sites" reference is grounded.

## Six high-priority verification points

| # | Check | Result |
|---|---|---|
| 1 | Recursive-validity gate framing (Builder-side, not pre-dispatch) | ✅ Verified |
| 2 | Performance estimate (<10s warm, src/probos = 409 files) | ✅ Plausible (Recommended #2: explicit baseline checkpoint) |
| 3 | Class resolution Pattern A/B/C achievable AST-only | ✅ Verified |
| 4 | AST-only constraint (no runtime imports) | ✅ Verified (Section 1 + Hard-Stops both enforce) |
| 5 | Calibration sweep targets exist in prompts/archive/ | ✅ Verified |
| 6 | Aggressive pre-deferral (convention #14: v1 method-name only) | ✅ Verified |

All 6 high-priority points pass. The two Required findings are tooling-spec gaps (output-shape clarity, Pattern A resolution priority), not architectural concerns.

## Top failure modes flagged

1. **Output shape for `unresolved` candidates is unspecified** (Required #1). Helper stdout is parsed as JSON by the wrapper; non-JSON noise breaks dispatch-time pre-check. Builder needs explicit specification: quiet-skip OR `"unresolved": [...]` JSON field.

2. **Pattern A AST-resolution priority is under-specified** (Required #2). `runtime.X` could resolve via 3 different AST shapes (annotated assignment, `__init__` assign, finalize.py post-construction assign). No priority or conflict-resolution rule is given. Specify: try annotation first, fall back to assignments, conservative-skip on conflict.

## Hard-stops triggered

None. AD-685b is on track for revision and pass-2 approval.

## Standing convention compliance

- **#14 (aggressive pre-deferral):** ✅ v1 ships method-name validation only; AD-685c/d deferred.
- **#15 (1 ⚠️ tolerance):** ✅ within budget.
- **#16 (mandatory phantom-API pre-check):** ✅ pre-check produced 2 documented FPs only; no real phantoms.
- **Verify-first standing order:** ✅ all concrete claims grep-verified before findings.

## Next steps

- Stage 2: Architect revision pass (apply 2 Required, fold 4 Recommended, judgment-call on 3 Nits). Re-run extended pre-check post-revision (will be retroactive once AD-685b ships, since extension validates AD-685b's own prompt).
- Stage 3: Architect Pass 2 review at `prompts/Reviews/README-wave-15-pass-2.md`. Convergence target: 1 ✅.
