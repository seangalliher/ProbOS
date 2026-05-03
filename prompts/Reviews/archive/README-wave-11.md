# Wave 11 Review Pass 1 — Sweep Summary

**Date:** 2026-05-03
**Mode:** Architect verify-first review.
**Scope:** 1 prompt (AD-685, tooling hygiene; low-risk single-prompt wave).
**Convergence target:** ✅ by Pass 2 (per dispatch).

## Verdict Table

| AD | Title | Risk | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|---|
| AD-685 | Phantom-API Pre-Check Method-Kwarg Shape Validation | low | ⚠️ Conditional | 1 | 4 | 4 |

**Tolerance check (convention #15):** 1 ⚠️ allowed when an architectural concern surfaces. One surfaced (recursive-validity gap). Within tolerance; revision pass expected to converge to ✅.

## Verification Results vs. Dispatch's Five High-Priority Points

1. **Recursive validity acknowledged.** Pre-check run on AD-685 itself flagged `WorkItemStore.get_pending` (documented FP per dispatch). **However**, the planned heuristics will NOT suppress this after AD-685 ships, because they are scoped to the new kwarg check while the existing symbol check is "preserved verbatim" (prompt line 74). → Required #1 in the review.
2. **Performance estimate.** `src/probos` has 403 Python files (verified via `Get-ChildItem -Recurse -Filter *.py | Measure-Object`). A cold `ast.parse` walk is plausible within 5s but tight; the prompt's hard-stop at >30s gives margin, but caching across invocations should be promoted from fallback to v1. → Recommended #1.
3. **Heuristic completeness.** All four heuristics (non-Python fence skip, prose-backtick skip, `## Revision` skip, overload acceptance) map to a real Wave 8/9/10 false-positive class. No completely unaddressed class. The only gap is the scoping issue (heuristics applied to new check only) — captured in Required #1.
4. **Test plan completeness.** 8 tests; each maps to a concrete observed failure or integration assertion. One nit (Test #4 only covers `pwsh` fences; should explicitly assert `bash`, `text`, bare fence) — Recommended #2.
5. **Aggressive pre-deferral (convention #14).** v1 boundary is honest. No field-name validation (`payload` vs `metadata`) has leaked into Section 1 or the test plan. AD-685b and AD-685c deferred with explicit rationale.

## Hard-Stops Triggered

| # | Hard-Stop | Triggered? |
|---|---|---|
| 1 | Phantom API in prompt body BEYOND documented self-reference | No |
| 2 | AD-685's helper conflicts with existing semantics non-additively | No (Section 2 is additive) |
| 3 | Heuristic gap — known FP class from Waves 8/9/10 not addressed | Partial — heuristics complete for new check, scoping issue for existing check (architectural finding, not hard-stop) |
| 4 | Performance estimate clearly wrong | No (403 files; estimate plausible with caching) |
| 5 | v1 scope creep (field-name validation in v1 instead of AD-685b) | No |

## Top Failure Modes If Shipped As-Is

1. **(High)** Acceptance Criterion "pre-check still passes on AD-685 prompt itself" fails on first Builder verification gate. Wave 11 cannot close.
2. **(Medium)** Future prompts citing past phantoms in prose will repeatedly trigger documented-FP review cycles.
3. **(Low–Medium)** Performance degrades on multi-prompt sweeps without cross-call caching.

## Recursive Validity Result

**Heuristics suppress the self-reference?** No — not as drafted. The new heuristics are scoped to the new check; the existing symbol check is "preserved verbatim." Required #1 in the review resolves this; recommended option is (a) — lift the prose-backtick + `## Revision` heuristics to a shared pre-filter applied to both checks.

## Performance Estimate Validation

| Metric | Value | Source |
|---|---|---|
| Python files in `src/probos` | 403 | `Get-ChildItem src/probos -Recurse -Filter *.py | Measure-Object` |
| AD-685's <5s claim | Plausible without caching, comfortable with caching | Estimate based on typical `ast.parse` throughput |
| AD-685's >30s hard-stop margin | 6× headroom | OK |
| Recommendation | Promote AST-index caching from fallback to v1 implementation | Recommended #1 |

## Convention Audit Summary (23 standing conventions)

Most conventions apply to runtime/source-code prompts and are N/A for tooling. The following are relevant and pass:

| # | Convention | Status |
|---|---|---|
| 11 | Revision-section audit-trail handling | ✓ (heuristic #3) |
| 14 | Aggressive pre-deferral | ✓ (1 of 3 caps shipped; b/c deferred) |
| 15 | Verdict tolerance (1 ⚠️ allowed) | ✓ (within tolerance) |
| 16 | Phantom-API pre-check mandatory | ✓ (this AD strengthens it) |
| 19 | Verify-first against codebase | ✓ (prompt has Verified Against Codebase block) |

No convention violations beyond the recursive-validity scoping issue captured as Required #1.

## Stage 2 Expected Workflow

Architect revises AD-685: applies Required #1 (lift heuristics to shared pre-filter), folds Recommended #1–#4, judgment-calls Nits. Appends `## Revision (2026-05-03)` section to the prompt. Re-runs the existing pre-check on the revised prompt to confirm — and after revision, the pre-filter heuristic will suppress the `WorkItemStore.get_pending` mention.

Stage 3 second-pass review at `prompts/Reviews/README-wave-11-pass-2.md` should converge to ✅.

## Files

- Review: `prompts/Reviews/ad-685-phantom-precheck-kwarg-validation-review.md`
- This summary: `prompts/Reviews/README-wave-11.md`
- Prompt under review: `prompts/ad-685-phantom-precheck-kwarg-validation.md`
- Existing pre-check (target of extension): `scripts/phantom-api-precheck.ps1`
