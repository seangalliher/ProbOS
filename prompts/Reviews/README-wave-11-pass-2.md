# Wave 11 Review Pass 2 — Sweep Summary

**Date:** 2026-05-03
**Mode:** Architect verify-first re-review against revised prompt.
**Scope:** 1 prompt (AD-685, tooling hygiene).
**Convergence target:** ✅ by Pass 2 — **MET.**

## Verdict Table

| AD | Title | Risk | Pass-1 | Pass-2 | Required-still-open | New findings |
|---|---|---|---|---|---|---|
| AD-685 | Phantom-API Pre-Check Method-Kwarg Shape Validation | low | ⚠️ Conditional | ✅ Approved | 0 | 0 |

**Convergence target met:** 1 of 1 prompts at ✅ after pass-2.

## Resolution Summary

Pass-1 surfaced 1 Required + 4 Recommended + 4 Nits. Revision (commit `eeaf9c7`) chose Required #1 Option B (shared pre-filter in PowerShell wrapper), folded all 4 Recommended findings, applied all 4 Nits. No new findings introduced across the 11 revision surfaces.

| Category | Pass-1 count | Resolved | Deferred | Still open |
|---|---|---|---|---|
| Required | 1 | 1 | 0 | 0 |
| Recommended | 4 | 4 | 0 | 0 |
| Nits | 4 | 4 | 0 | 0 |
| **Total** | **9** | **9** | **0** | **0** |

## Architectural Choice — Recursive-Validity Gate Framing

The revision's most important architectural decision is correctly placing the recursive-validity gate on the **Builder side**, not pre-dispatch:

- **Pre-dispatch precondition would be impossible** — the prompt cannot satisfy a check that depends on its own (yet-unbuilt) implementation.
- **Acceptance Criterion + Hard-Stop on Builder side** — Builder runs `./scripts/phantom-api-precheck.ps1 prompts/ad-685-...md` after Section 2 lands; expects 0 phantoms; tunes pre-filter if any remain (no allowlist short-circuit; no special-casing the AD-685 filename).
- **Pass-1 baseline preserved** — pre-check on the revised prompt still flags 1 phantom (`WorkItemStore.get_pending`), unchanged from pass-1. Confirmed by run.

This framing is the architecturally correct interpretation of pass-1 Required #1 Option (a). The revision adopted it cleanly.

## Pre-check Output (recursive-validity baseline)

```
$ ./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md
=== prompts/ad-685-phantom-precheck-kwarg-validation.md ===
  1 phantom symbol(s):
    - WorkItemStore.get_pending

=== Summary ===
Prompts scanned: 1
Total phantom candidates: 1
Exit: 1
```

**Expected:** 1 phantom self-reference (`WorkItemStore.get_pending`), unchanged from baseline. ✅
**No new phantoms introduced** by the revision. The shared pre-filter that will suppress this is what AD-685 itself ships.

## Hard-Stop Audit (per dispatch's four pre-conditions)

| # | Hard-Stop | Triggered? | Evidence |
|---|---|---|---|
| 1 | R1 not addressed | No | Section 2 wrapper-level shared pre-filter is Option B implementation. |
| 2 | New Required-class issue introduced | No | Five-point verification clean. |
| 3 | AST-index cache smuggled in caching infra | No | Module-level dict only; no JSON sidecar / no persistence / no IPC. |
| 4 | v1 scope creep (AD-685b field-name validation folded in) | No | Test plan and Section 1 contain zero field-name assertions. |

## Builder Dispatch Recommendation

**Dispatch as single commit.** The revision is tight, all findings resolved, no new surface. Recommended dispatch command:

```
./scripts/wave-orchestrator.ps1 dispatch
```

(Or builder-direct invocation per Wave 11 dispatch protocol.)

Builder will execute Sections 1–3 in order. Acceptance gates:
- 9 tests pass (was 8 in pass-1; +1 for shared-pre-filter coverage of the prose-table case).
- Recursive-validity gate: post-build pre-check on the AD-685 prompt itself exits 0.
- Calibration sweep against named corpus (`ad-641c-*`, `ad-500-*`, ≥3 others) documents true/false positive rates.
- Performance: <5s per prompt with cached AST index; cold-build time also reported.

## Convention Audit (delta vs pass-1)

No convention violations introduced by revision. Convention #15 (verdict tolerance): pass-2 surfaced 0 ⚠️ verdicts (was 1 in pass-1), within tolerance.

| # | Convention | Pass-1 | Pass-2 |
|---|---|---|---|
| 11 | Revision-section audit-trail handling | ✓ | ✓ (now applied via shared pre-filter) |
| 14 | Aggressive pre-deferral | ✓ (1 of 3 caps) | ✓ (2 of 4 caps; b/c/d deferred) |
| 15 | Verdict tolerance | 1 ⚠️ within tolerance | 0 ⚠️ — converged |
| 16 | Phantom-API pre-check mandatory | ✓ | ✓ (this AD strengthens it further) |
| 19 | Verify-first against codebase | ✓ | ✓ (Verified Against Codebase block intact) |

## Files

- Pass-1 review: `prompts/Reviews/ad-685-phantom-precheck-kwarg-validation-review.md` (## Pass-1 + ## Second-Pass Review (2026-05-03))
- Pass-1 sweep summary: `prompts/Reviews/README-wave-11.md`
- This pass-2 sweep summary: `prompts/Reviews/README-wave-11-pass-2.md`
- Revised prompt: `prompts/ad-685-phantom-precheck-kwarg-validation.md` (commit `eeaf9c7`)

## Stage 3 Expected Workflow

Builder dispatches AD-685. Single commit. On success, Wave 11 closes; tooling hygiene improvement lands before next HIGH-risk migration draft (Wave 12).
