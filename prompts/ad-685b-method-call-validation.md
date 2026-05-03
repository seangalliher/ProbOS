# AD-685b: Phantom-API Pre-Check — Method-Call AST Validation

**Status:** Drafted (Wave 15)
**Risk:** low (tooling-only; extends AD-685 v1)
**Depends on:** AD-685 v1 (shipped Wave 11; commit dc08971)
**Closes:** N/A (tooling hygiene)

---

## Solution Overview

AD-685 v1 (Wave 11) extended `scripts/phantom-api-precheck.ps1` with kwarg-name validation against live class signatures. Four documented recurrences since Wave 8 of the **method-shape** failure mode that AD-685 v1 doesn't catch:

| Wave | Phantom |
|---|---|
| 9B | `event_log.query(event_type=...)` — caught at review (real param: `event=`) |
| 10 | `WorkItemStore.add(work_item)` — caught at review (real method: `create_work_item`) |
| 12 | `runtime.duty_schedule_tracker` — caught by AD-685 v1 dispatch-time |
| 14 | `LLMClient.chat(...)` — caught at review (real method: `complete`) |

Three of the four were caught at REVIEW time (post-dispatch), not at draft-time pre-check. The pattern is: prompt asserts `<obj>.<method>(...)` where `<method>` doesn't exist on the resolved class. AD-685 v1 validates kwargs against existing methods but doesn't validate that the method name itself exists on the target class.

**v1 ships 1 of 2 capabilities** (per convention #14):
1. **Method-name validation against resolved class.** For each `<obj>.<method>(...)` call site in prompt body, the AST helper resolves `<obj>` to its likely class (via type hints, constructor signatures, or shipped attributes registered in src/) and validates that `<method>` exists on that class. Flags mismatches as `method_phantom`.

**Deferred:**
- AD-685c: Type-shape validation — flag if a kwarg expects `dict` but prompt passes `list`. Requires runtime type semantics; harder.
- AD-685d (renamed from AD-685c per Wave 11 deferral list): Field-name validation for dataclass/Pydantic constructors (e.g., `WorkItem(payload=...)` when field is `metadata`). Requires class-AST resolution beyond signatures.

## Dependencies

- `scripts/phantom-api-precheck.ps1` — current PowerShell wrapper (extended by AD-685 v1).
- `scripts/phantom_api_ast_helper.py` — Python AST helper from AD-685 v1.
- `src/probos/**/*.py` — target tree for class lookups.

## Sections

### Section 1 — Extend `phantom_api_ast_helper.py`

Add a new check class to the existing helper. Pattern: extend the call-site collection (already runs) to additionally:

1. For each `<obj>.<method>(<kwargs>)` call site detected, attempt to resolve `<obj>` to its class via the patterns below.

   **Pattern A — `runtime.X` resolution priority order** (try in sequence; first hit wins):
   1. **`AnnAssign` in `runtime.py`** (highest fidelity — explicit type hint). Match `self.X: SomeClass = ...` or `self.X: SomeClass`. `Optional[SomeClass]` and `SomeClass | None` resolve to `SomeClass`.
   2. **`Assign` with `Call` RHS in `finalize.py`** (mid fidelity — instantiation site shows class). Match `runtime.X = SomeClass(...)`.
   3. **`Assign` with `Call` RHS in `runtime.py` `__init__`** (low fidelity — fallback when no annotation). Match `self.X = SomeClass(...)`.
   4. **`Assign` without `Call` RHS in `runtime.py` or `finalize.py`** (no class info — treat as unresolved).

   **Tie-breaking on conflict** (different classes inferred at different priorities — already disallowed since first-hit wins; this clause covers same-priority duplicates):
   - Same priority, multiple matches → prefer the most-recent commit date for the matched line (architect's note: `git blame -L <line>,<line> -- <file>`).
   - Still tied (same commit) → emit an `unresolved` entry with `reason: "pattern_a_conflict"` and skip; never guess.

   **Pattern B — bare variable assignment in prompt body.** Match `<var> = SomeClass(...)` in the prompt's SEARCH/REPLACE blocks. Resolve `<var>` to `SomeClass`.
   - **Multiple assignments to the same variable:** take the FIRST assignment in document order.
   - **Later reassignment to a DIFFERENT class:** emit an `unresolved` entry with `reason: "pattern_b_reassignment"` and skip subsequent call sites on `<var>` after the reassignment line. Conservative-skip mirrors Pattern A.

   **Pattern C — typed parameter via type hints in surrounding context.** Resolve via parameter annotations in enclosing function signatures within the prompt's code blocks.

2. Once class is resolved, walk the AST of that class's source file to collect all method definitions (sync + async).

3. Flag the call site if `<method>` is NOT in the collected method set.

4. Skip when class resolution fails (don't false-flag — the heuristic is conservative). Emit unresolved candidates as a structured `"unresolved"` field in the JSON output (NOT stdout prose, NOT stderr noise — the wrapper parses stdout as JSON via `ConvertFrom-Json`).

Extended JSON output schema (additive to AD-685 v1):
```json
{
  "phantoms": [
    {"call_site": "...", "method": "...", "kwarg": "...", "category": "kwarg_mismatch", "candidates": ["..."]},
    {"call_site": "...", "obj": "runtime.X", "resolved_class": "SomeClass", "method": "...", "category": "method_phantom", "candidates_at": ["..."]}
  ],
  "unresolved": [
    {"call_site": "<obj>.<method>", "obj": "<obj>", "reason": "no_class_resolution"},
    {"call_site": "<obj>.<method>", "obj": "<obj>", "reason": "pattern_a_conflict"},
    {"call_site": "<obj>.<method>", "obj": "<obj>", "reason": "pattern_b_reassignment"}
  ]
}
```
The `unresolved` field is informational only — no phantom count contribution, no exit-code impact.

### Section 2 — Wire into PowerShell wrapper

Update `scripts/phantom-api-precheck.ps1`:

1. The AD-685 v1 wrapper already calls the AST helper and merges JSON output. AD-685b extension is internal to the helper — wrapper changes are minimal:
   - Display `[method_phantom]` category prefix in output (alongside existing `[kwarg_mismatch]` and `[runtime.X]` / `[Class.method]`).
   - **Display `unresolved` entries separately** under a `Skipped (unresolved class)` header, AFTER the phantom list. Format: `    ~ [<reason>] <call_site> (obj=<obj>)`. These do NOT contribute to `$phantomsHere.Count` and do NOT affect exit code — purely informational for architect awareness.
   - Exit code unchanged: 1 if any phantom (existing behavior); 0 even if `unresolved` entries are present.

### Section 3 — Calibration sweep against archived prompts

Run extended pre-check against:
- `prompts/archive/ad-641c-ward-room-thread-priority.md` (post-revision; Wave 9B `event_log.query(event_type=...)` was the original phantom)
- `prompts/archive/ad-500-dutyscheduler-workitem-migration.md` (post-revision; Wave 10 `WorkItemStore.add` and `WorkItemStore.get_pending` were the originals)
- `prompts/archive/ad-487-self-distillation-v1.md` (post-revision; Wave 14 `LLMClient.chat` was the original)

These are POST-revision prompts — the phantoms are gone from shipping content. Goal: confirm extended pre-check produces 0 false positives on these clean prompts. The actual catches are validated via synthetic test cases in tests/.

**False-positive definition (binding for calibration):** a `method_phantom` flag on a method that DOES exist on the resolved class. `unresolved` entries are NOT false positives — they are conservative skips by design. A flagged phantom on a class that resolved correctly to the wrong class (e.g., `LLMClient` resolved to `MockLLMClient`) is also a false positive (heuristic miss). Calibration target: 0 false positives across all 3 prompts. Any false positive triggers a heuristic-tuning pass before merge.

### Section 4 — Recursive validity gate

Per AD-685 v1 precedent: AD-685b's own prompt must produce 0 phantoms when scanned by the EXTENDED pre-check. The shared pre-filter (AD-685 v1 Section 2) already suppresses prose backticks and `## Revision` sections; new method_phantom check inherits this.

Builder-side acceptance: after Section 1 lands, run:
```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-685b-method-call-validation.md
```
Expected: 0 phantoms. Tune class-resolution heuristics if any false-positive method_phantom appears.

## What This Does NOT Change

- Existing AD-685 v1 kwarg-name check — preserved.
- Existing PowerShell wrapper exit semantics — unchanged.
- Field-name validation (dataclass/Pydantic constructor kwargs) — deferred to AD-685c/d.
- Type-shape validation — deferred.
- Class resolution heuristic stays conservative: skip-when-unresolved over false-flag.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_helper_catches_llmclient_chat_phantom` | Wave 14 regression — flags `LLMClient.chat(...)` (real method: `complete`) |
| 2 | `test_helper_catches_workitemstore_add_phantom` | Wave 10 regression — flags `WorkItemStore.add(...)` (real method: `create_work_item`) |
| 3 | `test_helper_catches_event_log_query_phantom` | Wave 9B regression — flags `event_log.query(...)` (real method: `query_structured`) |
| 4 | `test_helper_skips_unresolvable_class_no_false_positive` | Conservative skip behavior — emits `unresolved` entry, no `method_phantom` flag |
| 5a | `test_helper_resolves_runtime_attribute_via_annassign_in_runtime_py` | Pattern A priority 1 (highest fidelity — annotation) |
| 5b | `test_helper_resolves_runtime_attribute_via_finalize_py_assignment` | Pattern A priority 2 (instantiation site in finalize.py) |
| 6 | `test_helper_resolves_constructor_assignment_in_prompt` | Pattern B class resolution |
| 7 | `test_helper_walks_async_and_sync_methods` | Method set includes both `def` and `async def` |
| 8 | `test_helper_class_method_set_excludes_dunders` | Skip `__init__`, `__repr__` etc. (those aren't user-callable phantoms) |
| 9 | `test_powershell_wrapper_displays_method_phantom_category` | Integration: output formatting |
| 10 | `test_recursive_validity_ad685b_prompt_clean` | AD-685b's own prompt produces 0 phantoms |

Tests live at `tests/test_phantom_api_precheck_method_calls.py`. Use Python helper directly + invoke PowerShell wrapper via subprocess for integration tests. Total: 11 tests (test #5 split into 5a/5b).

## Tracking

1. **PROGRESS.md:** prepend AD-685b entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-685b: Phantom-API Pre-Check — Method-Call AST Validation (2026-05-03)

**Problem:** AD-685 v1 catches kwarg-name phantoms but NOT method-name phantoms. 4 documented recurrences across Waves 9B, 10, 12, 14 of the pattern: prompt asserts `<obj>.<method>(...)` where `<method>` doesn't exist on the resolved class. 3 of 4 caught at review time (LLMClient.chat → complete being the most recent in Wave 14); only 1 caught by AD-685 v1 (runtime.duty_schedule_tracker via runtime.X check). Architect's 4th-recurrence forcing function.

**Decision:** Extend `scripts/phantom_api_ast_helper.py` with method-name validation:
- Resolve `<obj>` to its class via runtime attribute lookup (Pattern A), constructor assignment in prompt (Pattern B), or type hint (Pattern C).
- Walk class source file AST to collect method names (sync + async, exclude dunders).
- Flag call sites where `<method>` is NOT in the class's method set as `method_phantom`.
- Conservative: skip when class resolution fails — never false-flag.

PowerShell wrapper changes: minimal (display new category prefix). Exit semantics unchanged.

**Why:** 4 recurrences across 6 waves means the architect-discretion sweep posture has expired. One scripted convention beats N drafting-time conventions. Recursive-validity gate (AD-685 v1 precedent) ensures AD-685b's own prompt validates clean.

**Deferred:**
- AD-685c: Type-shape validation (dict vs list kwarg values).
- AD-685d: Field-name validation for dataclass/Pydantic constructor kwargs (e.g., WorkItem field `payload` vs `metadata`).

**Cross-links:** AD-685 v1 (Wave 11; symbol-existence + kwarg-name), Wave 14 retrospective (4th method-shape recurrence trigger), `phantom_api_ast_helper.py` (extended in-place).
```

3. **docs/development/roadmap.md:** add AD-685b entry under tooling/hygiene section (or alongside AD-685).

## Verified Against Codebase (2026-05-03)

```
ls scripts/phantom_api_ast_helper.py
  scripts/phantom_api_ast_helper.py exists (AD-685 v1 / Wave 11; commit dc08971)

ls scripts/phantom-api-precheck.ps1
  scripts/phantom-api-precheck.ps1 exists (Wave 8 Addendum #16 + AD-685 v1)

grep -n "ConvertFrom-Json" scripts/phantom-api-precheck.ps1
  263:                $parsed = $helperJson | ConvertFrom-Json
  (Wrapper consumes helper stdout as JSON; non-JSON noise on stdout breaks dispatch — confirms R1 fix)

grep -n "2>\$null" scripts/phantom-api-precheck.ps1
  261:            $helperJson = $filteredBody | & $pythonExe $helperPath --src-root $srcRoot 2>$null
  (stderr already discarded; unresolved entries MUST land in JSON, not stderr — confirms R1 schema choice)

ls src/probos/startup/finalize.py
  src/probos/startup/finalize.py exists (Pattern A priority 2 source)

ls src/probos/runtime.py
  src/probos/runtime.py exists (Pattern A priority 1 + 3 source)

grep -rn "*.py" src/probos | wc -l
  409 files (current count; AD-685 v1's <5s baseline was 403 — drift checkpoint per Recommended #2)
```

## Acceptance Criteria

- `scripts/phantom_api_ast_helper.py` extended with method-name validation and `unresolved` JSON field.
- `scripts/phantom-api-precheck.ps1` wrapper minimal-change (category prefix + `unresolved` display section).
- 11 tests pass at `tests/test_phantom_api_precheck_method_calls.py` (test #5 split into 5a/5b for Pattern A priority coverage).
- Recursive-validity gate: AD-685b prompt itself produces 0 phantoms via extended pre-check.
- Calibration sweep on 3 archived post-revision prompts: 0 false positives (per binding definition in Section 3).
- Performance: warm-pass <10s per prompt (matches AD-685 v1 baseline). **Builder reports actual warm-pass timing on at least 1 representative prompt; if >10s, extend `_INDEX_CACHE` to also cache per-class method sets before merge.**
- DECISIONS.md entry under Era V.

## Hard-Stops

- Class resolution heuristic produces ≥1 false positive on any archived calibration prompt (per Section 3 definition) — surface; tune heuristic before merge. (Tightened from ">5 per prompt" to align with Section 3's "0 false positives expected" target.)
- Performance regression beyond AD-685 v1's <5s warm baseline (Builder-reported timing exceeds 10s warm) — surface; cache strategy may need refinement.
- Recursive-validity gate fails after heuristic tuning — surface; architectural choice may need revision.
- Helper invokes runtime imports from `src/probos/` (would break sandbox) — surface; AST-only pattern must be preserved.

## Revision (2026-05-03)

Pass-1 review (commit 6def44f) verdict: ⚠️ Conditional. All 2 Required + 4 Recommended + 3 Nits applied.

**Required**
- **R1 (output shape):** Section 1 step 4 + JSON schema now specify explicit `"unresolved": [...]` field with structured `{call_site, obj, reason}` entries. Reasons enumerated: `no_class_resolution`, `pattern_a_conflict`, `pattern_b_reassignment`. Section 2 documents wrapper-level handling — display under separate `Skipped (unresolved class)` header, no phantom-count contribution, no exit-code impact. Confirms wrapper's existing `2>$null` stderr discard + stdout-only `ConvertFrom-Json` parsing.
- **R2 (Pattern A priority):** Section 1 step 1 now specifies 4-level resolution priority: (1) `AnnAssign` in runtime.py, (2) `Assign+Call` in finalize.py, (3) `Assign+Call` in runtime.py `__init__`, (4) bare `Assign` (no class info → unresolved). `Optional[X]` and `X | None` resolve to `X`. Tie-breaking: most-recent commit date; still tied → `unresolved` with reason `pattern_a_conflict`.

**Recommended**
- **Rec #1 (test #5 coverage):** Split into 5a (`test_helper_resolves_runtime_attribute_via_annassign_in_runtime_py`) and 5b (`test_helper_resolves_runtime_attribute_via_finalize_py_assignment`). Test plan now 11 tests; AC updated to match.
- **Rec #2 (perf baseline drift):** AC bullet now includes Builder-reported warm-pass timing on at least 1 representative prompt; >10s triggers `_INDEX_CACHE` extension before merge. Verified footer shows current 409 files vs v1's 403.
- **Rec #3 (FP definition):** Section 3 adds binding false-positive definition: `method_phantom` flag on a method that DOES exist on the resolved class, OR class resolved to wrong class. `unresolved` entries explicitly NOT false positives.
- **Rec #4 (Pattern B multi-assign):** Section 1 Pattern B specifies first-assignment-wins; later reassignment to different class → `unresolved` with reason `pattern_b_reassignment`.

**Nits**
- Test #4 renamed to `test_helper_skips_unresolvable_class_no_false_positive` (class is what fails resolution, not obj).
- AC #5 dropped `cold or warm`; explicit warm-pass target with Builder timing checkpoint.
- Hard-Stop tightened from `>5 false positives per prompt` to `≥1` to align with Section 3's `0 false positives expected`.

**Surfaces touched:** Section 1 (Pattern A/B/C resolution rules + JSON schema), Section 2 (wrapper unresolved display), Section 3 (FP definition), Test Plan (test #4 rename, #5 split), Acceptance Criteria (11 tests + timing checkpoint), Hard-Stops (FP threshold), Verified Against Codebase (R1/R2 grep evidence).

**Lines:** ~+55 / -15 (Section 1 expanded; Test Plan +1 row; Verified footer expanded).

**Closing self-check:**
- No OLD claims remain: grep for old test #4 name (`unresolvable_obj`), old test #5 name (`via_finalize_py` without `_assignment`), old hard-stop threshold (`>5 false positives per archived prompt`), and old AC `cold or warm` wording all return zero hits in shipping content (only present in this Revision section as historical reference).
- Solution Overview / Section 1 / Acceptance Criteria internally consistent: 11 tests asserted in both Test Plan and AC; `unresolved` field referenced in Section 1 schema, Section 2 display, Section 3 FP definition.
