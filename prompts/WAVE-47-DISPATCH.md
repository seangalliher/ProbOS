# Wave 47 Dispatch — AD-685d v1 Phantom-API Field-Name Validation

**Single-AD continuous-build wave.** Closes GH issue #407.

**Inputs (read first):**
- `prompts/ad-685d-phantom-field-name-v1.md` (this prompt — full spec)
- `scripts/phantom_api_ast_helper.py` (extend; ~1000 lines at HEAD `893f29b`)
- `scripts/phantom-api-precheck.ps1` (extend dispatch block ~line 282)

**Test gate:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`

**Baseline:** Wave 46 = 11122 passed. Expected post-build: 11134 (+12).

## Highest-Risk Constraints

1. **AST nodes must NEVER reach JSON output.** Existing `_jsonable_candidate()` strips `param_annotations`. The new field index uses `set[str]` and `list[str]` only — no AST nodes. Verify: `valid_fields` in field-phantom records is `sorted(set)[:20]`. No AST.
2. **5 caches to clear between fixtures**, not 4. Add `_CLASS_FIELDS_CACHE.clear()` to every test fixture that re-builds an index. The provided test fixture handles this; do not omit it on any new tests added.
3. **Constructor regex `_CTOR_RE` must match nested kwargs only inside the OUTER paren block**. The pattern `\b([A-Z][a-zA-Z0-9_]+)\s*\(([^()]*)\)` already excludes nested parens via `[^()]` — preserves Wave 46 lesson. Do not loosen it.
4. **Backward compat**: AD-685 kwarg phantom records ship without a `category` field; AD-685b records have `category="method_phantom"`; AD-685c records have `category="type_shape_mismatch"`. NEW records add `category="field_phantom"` or `category="property_field_collision"`. Do not retroactively add `category` to AD-685 records.
5. **Skip private fields (`_` prefix)** in both attribute access AND constructor kwarg validation. ProbOS conventions accept private-attribute access in narrow wiring contexts; the validator's role is to catch typos on the public field surface.
6. **`ClassVar[...]` annotations are NOT fields.** The walker in `build_class_field_index()` explicitly checks for `Subscript(value=Name("ClassVar"), ...)` and skips. Test #11 enforces this.

## Wave 46 False Positives To Watch

- `class:SimpleNamespace` — stdlib, harmless. Keep skipping via existing `_NOISY_RECEIVER_TOKENS` (it's already in the wrapper's `STDLIB_PREFIXES`).
- `runtime.X` introductions in the prompt body itself — wrapper's negative-framing guard already handles these.

## Hard Stops (surface to user, do not work around)

- Architectural change required to `BaseAgent` / `IntentMessage` protocols.
- Phantom-API in implementation (Captain spec references a method that doesn't exist on the live class). The verify-first section of the prompt grep-confirms every helper anchor; if Builder finds drift, surface immediately.
- Test fail signal that doesn't reproduce in serial (`-n 0` rerun). Quarantine via `pytest.mark.skip(reason="BF-NNN: ...")` and resume.

## Workflow

1. Apply Section 1 (class-field index) — append to `phantom_api_ast_helper.py` after line ~89 (cache decl) AND after line ~715 (`build_class_method_index` end).
2. Apply Section 2 (field-phantom + collision walkers) — append after `find_type_shape_phantoms()` (line ~575).
3. Apply Section 3 (`main()` wiring) — single SEARCH/REPLACE.
4. Apply Section 4 (PowerShell wrapper dispatch) — single SEARCH/REPLACE inserting two new `elseif` branches.
5. Create `tests/test_ad685d_phantom_field_name.py`.
6. Run focused gate: `pytest tests/test_ad685d_phantom_field_name.py -v -n 0`. All 12 must pass.
7. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`. Expect 11134 passed.
8. Run wrapper self-test: `pwsh ./scripts/phantom-api-precheck.ps1 prompts/ad-685d-phantom-field-name-v1.md`. Exit 0 preferred; exit 1 with all FPs referencing fixture classes acceptable.
9. Update PROGRESS.md, roadmap.md, DECISIONS.md.
10. Single commit `AD-685d: Phantom-API pre-check field-name + property-collision validation (Wave 47, closes #407)`.
11. Push, archive prompt + dispatch into `prompts/archive/`, advance wave-orchestrator state, push archive commit.

## Tracker Edits

- `PROGRESS.md` — prepend AD-685d entry above AD-685c (line 5 area). Include test count delta + closed-by line.
- `docs/development/roadmap.md` — flip AD-685d row Scoped→Complete (or add row to Phantom-API Pre-Check section).
- `DECISIONS.md` — prepend AD-685d entry above AD-685c, grouped with the AD-685 family.
- `prompts/wave-plan.yaml` — left untouched (id="47" pre-populated per Wave 41+ convention).

## Notes for Builder

- The class-field index has zero overlap with the existing kwarg index. Building it adds one extra ClassDef walk per `.py` file — well under the 2x performance bound.
- `_resolve_transitive_fields()` is recursive with cycle protection via `_seen`. Don't refactor to iterative — the recursion depth is bounded by class hierarchy depth (typically ≤4 in this codebase).
- The Pattern A (`runtime.X.field`) attribute access is intentionally NOT validated in v1. The regex would match `runtime.records_store.list_entries` and the helper has no way to distinguish "field access on resolved class" from "method call without parens" cleanly without a full AST walk. Punt to v2 if data justifies.
