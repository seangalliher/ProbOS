# Review: AD-685b — Phantom-API Pre-Check, Method-Call AST Validation

**Verdict:** ⚠️ Conditional
**Two spec gaps (output shape for unresolved candidates; Pattern A resolution priority) need clarification before Builder dispatch. Architecture is sound; AST-only, recursive-validity, and aggressive pre-deferral all honored.**

---

## Required (must fix before building)

1. **Section 1 step 4 — output shape for "unresolved" candidates is unspecified.** The prompt says "Log 'unresolved' candidates separately for architect awareness" but does not say where: separate JSON field, stderr, stdout, or silent. The PowerShell wrapper at [phantom-api-precheck.ps1](scripts/phantom-api-precheck.ps1#L257-L274) parses helper stdout as JSON via `ConvertFrom-Json`; any non-JSON noise on stdout breaks dispatch-time pre-check. Specify either:
   - Quiet-skip (no log; conservative posture wins on noise too), OR
   - Add a separate `"unresolved": [...]` field to the existing JSON shape and have the wrapper ignore it.
   Without this, the Builder may default to `print()` debug noise that corrupts wrapper output.

2. **Pattern A AST-resolution priority is under-specified.** Section 1 step 1 says: *"Pattern A: `runtime.X` where X is a known runtime attribute → look up class via `runtime.py` annotations or `finalize.py` instantiation sites"*. A `runtime.X` could appear in three AST shapes:
   - `runtime.py` `__init__`: `self.X: SomeClass = ...` (`ast.AnnAssign`)
   - `runtime.py` `__init__`: `self.X = SomeClass(...)` (`ast.Assign` with `ast.Call` RHS)
   - `finalize.py`: `runtime.X = SomeClass(...)` (post-construction assignment)

   The prompt does not specify priority order, what to do on disagreement (different classes inferred from different sites), or whether `Optional[SomeClass]` annotations resolve to `SomeClass`. Specify: try annotated assignment in runtime.py first (highest fidelity), fall back to `__init__` assignment RHS, fall back to finalize.py post-construction assignment; on conflict, conservative-skip with `unresolved` entry. This locks the heuristic so that test #5 (`test_helper_resolves_runtime_attribute_via_finalize_py`) has a defined contract.

## Recommended

1. **Test #5 only covers one Pattern A path.** `test_helper_resolves_runtime_attribute_via_finalize_py` implies finalize.py is the canonical resolution path, but Section 1 step 1 lists *runtime.py annotations OR finalize.py* as alternatives. Split into 5a (annotation in runtime.py) and 5b (assignment in finalize.py), or rename to `test_helper_resolves_runtime_attribute_via_either_path` and assert both paths are tried.

2. **Performance baseline drift.** AD-685 v1's <5s warm baseline was measured on 403 Python files in src/probos at Wave 11. Current count is 409 (verified via `Get-ChildItem src/probos -Recurse -Filter *.py | Measure-Object`). Marginal but the AD-685b extension adds per-call-site class-source AST re-walk (each resolved class triggers re-parse of the owning .py file unless cached). Add to Acceptance Criteria: *"Builder reports actual warm-pass timing on at least 1 representative prompt; if >10s, extend `_INDEX_CACHE` to also cache per-class method sets."* This converts the current implicit assumption into an explicit checkpoint.

3. **Calibration sweep success criterion is implicit.** Section 3 says "0 false positives expected" but does not define what counts as a false positive vs an unresolved warning. State explicitly: *"A false positive is a `method_phantom` flag on a method that DOES exist on the resolved class. `unresolved` entries are not false positives — they are conservative skips."* Without this distinction the Builder may misinterpret legitimate skip-when-ambiguous behavior as failure.

4. **Pattern B handling of multiple assignments to the same variable.** *"bare variable that matches a constructor pattern in the prompt (e.g., `client = SomeClass(...)`)"* — but a prompt body can have several SEARCH/REPLACE blocks that reassign `client`. Specify: take first assignment in document order; on later reassignment to a different class, conservative-skip (unresolved). This is the same conservative posture as Pattern A conflict resolution.

## Nits

- **Test #4 name.** `test_helper_skips_unresolvable_obj_no_false_positive` — the obj is resolvable as a name; the *class* is what fails resolution. Rename to `test_helper_skips_unresolvable_class_no_false_positive` for accuracy.
- **Acceptance Criteria #5 says "Performance: <10s per prompt (cold or warm; AD-685 v1's index cache amortizes)."** AD-685 v1's measured baseline was warm-only. Either drop "cold or warm" or add a separate cold-pass target; current wording overpromises.
- **Hard-Stops first bullet — ">5 false positives per archived prompt".** Given the conservative-skip posture, a >5 threshold per prompt is generous. Calibration is on 3 prompts; recommend stricter per-prompt threshold (≥1 false positive triggers heuristic tune) since the bar for shipping is "0 false positives expected" per Section 3. Aligns Hard-Stop with Acceptance Criteria.

## Verified

- **Recursive-validity gate framing.** Section 4 explicitly states "Builder-side acceptance: after Section 1 lands, run...", correctly framing the gate as a Builder check (matching AD-685 v1 precedent) rather than pre-dispatch architect work.
- **Acceptance Criteria includes recursive gate.** "Recursive-validity gate: AD-685b prompt itself produces 0 phantoms via extended pre-check." ✅
- **Hard-Stops include recursive failure clause.** "Recursive-validity gate fails after heuristic tuning — surface". ✅
- **AST-only constraint.** Section 1 specifies `ast.parse()` walks; no `import probos.X`. Hard-Stops include "Helper invokes runtime imports from `src/probos/` (would break sandbox) — surface". ✅
- **Calibration sweep targets all exist.** `prompts/archive/ad-641c-ward-room-thread-priority.md`, `prompts/archive/ad-500-dutyscheduler-workitem-migration.md`, `prompts/archive/ad-487-self-distillation-v1.md` — all three confirmed present. Phantoms confirmed gone from shipping content (grep returned 0 matches for `LLMClient.chat(`, `WorkItemStore.add`, `event_log.query(`).
- **finalize.py exists.** `src/probos/startup/finalize.py` confirmed (81985 bytes); Pattern A's reference to "finalize.py instantiation sites" is grounded.
- **Pattern A/B/C all achievable AST-only.** Pattern A walks runtime.py + finalize.py via `ast.parse`. Pattern B walks the prompt body itself. Pattern C walks type-hint AST nodes. No runtime imports required.
- **Convention #14 (aggressive pre-deferral) honored.** v1 ships method-name only. AD-685c (type-shape) and AD-685d (field-name) explicitly deferred in Solution Overview, "What This Does NOT Change" section, and DECISIONS.md entry.
- **No phantom APIs in shipping content beyond the 2 documented FPs.** `runtime.duty_schedule_tracker` (prose context, retrospective table) and `class:SomeClass` (illustrative placeholder in Pattern B) — both confirmed as documented false positives.
- **Test count matches dispatch.** 10 tests at `tests/test_phantom_api_precheck_method_calls.py`, matching WAVE-15-DISPATCH.md "~10 tests" target.
- **Verify-first footer is grounded.** All grep claims verified against live codebase.
- **Performance estimate plausible.** 409 files × per-class AST walk with caching is in the same order as v1's warm baseline; <10s target is reasonable given v1 hit <5s on 403 files. (See Recommended #2 for explicit baseline-drift checkpoint.)
- **No v1 scope creep.** No type-shape or field-name validation smuggled into Section 1 implementation; both deferred.
