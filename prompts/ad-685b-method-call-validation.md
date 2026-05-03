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

1. For each `<obj>.<method>(<kwargs>)` call site detected, attempt to resolve `<obj>` to its class:
   - Pattern A: `runtime.X` where X is a known runtime attribute → look up class via `runtime.py` annotations or `finalize.py` instantiation sites
   - Pattern B: bare variable that matches a constructor pattern in the prompt (e.g., `client = SomeClass(...)`)  → resolve to `SomeClass`
   - Pattern C: typed parameter via type hints in surrounding context

2. Once class is resolved, walk the AST of that class's source file to collect all method definitions (sync + async). 

3. Flag the call site if `<method>` is NOT in the collected method set.

4. Skip when class resolution fails (don't false-flag — the heuristic should be conservative). Log "unresolved" candidates separately for architect awareness.

Add to existing JSON output:
```json
{
  "phantoms": [
    {"call_site": "...", "method": "...", "kwarg": "...", "category": "kwarg_mismatch", "candidates": [...]},
    {"call_site": "...", "obj": "runtime.X", "resolved_class": "SomeClass", "method": "...", "category": "method_phantom", "candidates_at": [...]}
  ]
}
```

### Section 2 — Wire into PowerShell wrapper

Update `scripts/phantom-api-precheck.ps1`:

1. The AD-685 v1 wrapper already calls the AST helper and merges JSON output. AD-685b extension is internal to the helper — wrapper changes are minimal:
   - Display `[method_phantom]` category prefix in output (alongside existing `[kwarg_mismatch]` and `[runtime.X]` / `[Class.method]`).
   - Exit code unchanged: 1 if any phantom (existing behavior).

### Section 3 — Calibration sweep against archived prompts

Run extended pre-check against:
- `prompts/archive/ad-641c-ward-room-thread-priority.md` (post-revision; Wave 9B `event_log.query(event_type=...)` was the original phantom)
- `prompts/archive/ad-500-dutyscheduler-workitem-migration.md` (post-revision; Wave 10 `WorkItemStore.add` and `WorkItemStore.get_pending` were the originals)
- `prompts/archive/ad-487-self-distillation-v1.md` (post-revision; Wave 14 `LLMClient.chat` was the original)

These are POST-revision prompts — the phantoms are gone from shipping content. Goal: confirm extended pre-check produces 0 false positives on these clean prompts. The actual catches are validated via synthetic test cases in tests/.

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
| 4 | `test_helper_skips_unresolvable_obj_no_false_positive` | Conservative skip behavior |
| 5 | `test_helper_resolves_runtime_attribute_via_finalize_py` | Pattern A class resolution |
| 6 | `test_helper_resolves_constructor_assignment_in_prompt` | Pattern B class resolution |
| 7 | `test_helper_walks_async_and_sync_methods` | Method set includes both `def` and `async def` |
| 8 | `test_helper_class_method_set_excludes_dunders` | Skip `__init__`, `__repr__` etc. (those aren't user-callable phantoms) |
| 9 | `test_powershell_wrapper_displays_method_phantom_category` | Integration: output formatting |
| 10 | `test_recursive_validity_ad685b_prompt_clean` | AD-685b's own prompt produces 0 phantoms |

Tests live at `tests/test_phantom_api_precheck_method_calls.py`. Use Python helper directly + invoke PowerShell wrapper via subprocess for integration tests.

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

grep -n "def visit_" scripts/phantom_api_ast_helper.py
  (Builder reads existing AST visitor pattern)

grep -rn "class .*:" src/probos | wc -l
  (Builder estimates class count for performance — AD-685 v1 already validated <30s on 403 files)
```

## Acceptance Criteria

- `scripts/phantom_api_ast_helper.py` extended with method-name validation.
- `scripts/phantom-api-precheck.ps1` wrapper minimal-change (category prefix).
- 10 tests pass at `tests/test_phantom_api_precheck_method_calls.py`.
- Recursive-validity gate: AD-685b prompt itself produces 0 phantoms via extended pre-check.
- Calibration sweep on 3 archived post-revision prompts: 0 false positives.
- Performance: <10s per prompt (cold or warm; AD-685 v1's index cache amortizes).
- DECISIONS.md entry under Era V.

## Hard-Stops

- Class resolution heuristic produces >5 false positives per archived prompt — surface; tune heuristic before merge.
- Performance regression beyond AD-685 v1's <5s warm baseline — surface; cache strategy may need refinement.
- Recursive-validity gate fails after heuristic tuning — surface; architectural choice may need revision.
- Helper invokes runtime imports from `src/probos/` (would break sandbox) — surface; AST-only pattern must be preserved.
