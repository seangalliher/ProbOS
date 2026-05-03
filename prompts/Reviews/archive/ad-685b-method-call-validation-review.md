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

---

## Second-Pass Review (2026-05-03)

**Verdict:** ✅ Approved
**All 2 Required + 4 Recommended + 3 Nits resolved. Recursive-validity gate clean (2 documented FPs only). Historical-phantom catch coverage validated against all 4 wave recurrences. Ready for Builder dispatch.**

### Resolution Audit — Required

| Pass-1 Required | Status | Evidence |
|---|---|---|
| R1 (output schema unresolved field) | ✅ | Section 1 step 4 specifies `"unresolved"` JSON field with structured `{call_site, obj, reason}` entries; reasons enumerated (`no_class_resolution`, `pattern_a_conflict`, `pattern_b_reassignment`). Section 2 wrapper documents separate `Skipped (unresolved class)` display, NO exit-code/phantom-count impact. Verified footer grep shows wrapper `2>$null` (stderr discard) + `ConvertFrom-Json` (stdout-only JSON), confirming schema choice prevents wrapper corruption. |
| R2 (Pattern A priority + tie-breaking) | ✅ | Section 1 step 1 enumerates 4-level priority: (1) `AnnAssign` in runtime.py [highest], (2) `Assign+Call` in finalize.py, (3) `Assign+Call` in runtime.py `__init__`, (4) bare `Assign` → unresolved. `Optional[X]` and `X \| None` resolve to `X`. Same-priority conflict → `git blame` most-recent commit; still tied → `unresolved` with `pattern_a_conflict`. First-hit-wins prevents priority-level conflict. |

### Resolution Audit — Recommended

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| Rec #1 (test #5 split) | ✅ | Tests 5a/5b in Test Plan: `via_annassign_in_runtime_py` (priority 1) + `via_finalize_py_assignment` (priority 2). Total 11 tests. AC updated. |
| Rec #2 (perf baseline drift) | ✅ | AC bullet: "Builder reports actual warm-pass timing on at least 1 representative prompt; if >10s, extend `_INDEX_CACHE` to also cache per-class method sets before merge." Explicit checkpoint per recommendation. |
| Rec #3 (FP definition) | ✅ | Section 3 adds binding definition: `method_phantom` flag on existing method OR wrong-class resolution = FP; `unresolved` entries explicitly NOT FPs. |
| Rec #4 (Pattern B multi-assign) | ✅ | Section 1 Pattern B: first-assignment-wins in document order; later reassignment to different class → `unresolved` with reason `pattern_b_reassignment`. Mirrors Pattern A conservative posture. |

### Resolution Audit — Nits

| Pass-1 Nit | Status | Notes |
|---|---|---|
| Nit #1 (test #4 rename) | ✅ | Renamed to `test_helper_skips_unresolvable_class_no_false_positive`. |
| Nit #2 (AC cold/warm overpromise) | ✅ | AC #5 now warm-only with Builder timing checkpoint. |
| Nit #3 (Hard-Stop FP threshold) | ✅ | Tightened from `>5 false positives per prompt` to `≥1 false positive` — aligns with Section 3 `0 expected`. |

### Pre-check Output (recursive validity)

```
./scripts/phantom-api-precheck.ps1 prompts/ad-685b-method-call-validation.md
=== prompts/ad-685b-method-call-validation.md ===
  2 phantom symbol(s):
    - [runtime.X] runtime.duty_schedule_tracker   (documented FP: prose context, retrospective table)
    - [<Class>(...)] class:SomeClass              (documented FP: illustrative placeholder in Pattern B)
```

**No new phantoms beyond the 2 documented FPs.** Verify-first regression check passes.

### Historical-Phantom Catch Coverage

| Wave | Phantom | Pattern | Test | Covered |
|---|---|---|---|---|
| 9B | `event_log.query(event_type=...)` | A (runtime.event_log → EventLog) | Test #3 | ✅ (real: `query_structured`) |
| 10 | `WorkItemStore.add(work_item)` | A (runtime.work_item_store → WorkItemStore) | Test #2 | ✅ (real: `create_work_item`) |
| 12 | `runtime.duty_schedule_tracker` | (AD-685 v1 territory — runtime-attribute existence) | covered by v1 | ✅ |
| 14 | `LLMClient.chat(...)` | B (bare `client = LLMClient(...)` in prompt body) | Test #1 | ✅ (real: `complete`) |

**All 4 method-shape recurrences covered.** Pattern A handles 3 of 4 (runtime-attribute-shape); Pattern B handles 1 of 4 (bare-constructor-shape); Pattern C (parameter type hints) provides defense-in-depth for future recurrences in delegated methods. Wave 14 retrospective gap-closing verified.

### New Findings

None. No regressions introduced; no new Required-class issues; no new phantoms in shipping content.

### Closing Note

Revision adheres to convention #14 (aggressive pre-deferral): v1 ships method-name only; AD-685c (type-shape) and AD-685d (field-name) explicitly deferred in Solution Overview, "What This Does NOT Change", and DECISIONS.md entry. Recursive-validity gate is the canonical Builder-side acceptance check; framing matches AD-685 v1 precedent.

**Recommended Builder dispatch:** single commit, no further architect cycles required.