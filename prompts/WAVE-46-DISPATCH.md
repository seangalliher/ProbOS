# WAVE 46 DISPATCH — AD-685c v1 Phantom-API Type-Shape Validation

**Spec:** `prompts/ad-685c-phantom-type-shape-v1.md`
**Closes:** GH #406
**Test count baseline:** 11106 → expected 11116-11118 (+10-12)
**Single commit per ask. Continuous build. No mid-wave pause.**

## Highest-risk constraints (read first)

1. **Captain's spec assumed `scripts/phantom-api-precheck/` is a directory. It is NOT.** The Python helper is a SINGLE FILE: `scripts/phantom_api_ast_helper.py` (~620 lines). All Section 1–5 edits land in this single file. Do NOT split into a package; that would be a separate refactor AD.

2. **Backward compatibility is the most critical invariant.** Existing AD-685 (kwarg phantoms with no `category` field) and AD-685b (method phantoms with `category="method_phantom"`) records MUST ship unchanged. The new `type_shape_mismatch` records must carry their own `category` label and additional fields — they augment, never replace, existing output.

3. **Skip > flag.** This validator must err strongly toward NOT flagging. A single false positive in production wave runs erodes trust in the whole pre-check. Conservative path: any unknown class annotation, any unresolvable value (variable ref, call, attribute access, bytes literal) → silent skip. Only flag when ALL candidate annotations are KNOWN primitives/containers AND NONE match the value.

4. **`bool` matches `int`.** Python booleans are int subclasses. The compatibility rule explicitly allows `bool` value to match `int` annotation. Do not regress this — there's a test for it.

5. **Empty containers match permissively.** `tags=[]` against `tags: list[str]` must NOT flag (no element evidence).

6. **Self-test the new validator on its own prompt.** After the build, run:
   ```
   pwsh ./scripts/phantom-api-precheck.ps1 prompts/ad-685c-phantom-type-shape-v1.md
   ```
   The prompt's example fixtures use placeholder identifiers (`Foo`, `obj`, `def f`, `def g`, etc.) that are NOT in `src/probos/`, so all candidates should resolve to one of the existing FP classes (intro-not-in-index, stdlib alias, prose example) or be silently skipped. If genuine new phantoms surface, they must be documented in the build report as expected FPs from the prompt's own example bodies — NOT shipping defects. The example calls `obj.f(name=42)` etc. exist inside ```python``` fences so the existing pre-filter does NOT mask them; rely on the helper's "method not in src — skip" branch (line 194 of helper at HEAD).

## Verified anchors at HEAD `c33c38d`

| Anchor | Path:Line | Used by |
|---|---|---|
| `build_index` | `scripts/phantom_api_ast_helper.py:120` | Section 1 |
| `_collect_param_names` | `scripts/phantom_api_ast_helper.py:152` | Section 1 |
| `find_kwarg_phantoms` | `scripts/phantom_api_ast_helper.py:190` | Read-only |
| `_CALL_RE` | `scripts/phantom_api_ast_helper.py:114` | Reused in Section 4 |
| `_NOISY_METHODS` / `_NOISY_RECEIVER_TOKENS` | `scripts/phantom_api_ast_helper.py:88, 109` | Reused in Section 4 |
| `_extract_class_from_annotation` | `scripts/phantom_api_ast_helper.py:237` | Pattern-match for new helper |
| `find_method_phantoms` | `scripts/phantom_api_ast_helper.py:445` | Read-only |
| `main()` phantom merge | `scripts/phantom_api_ast_helper.py:592` | Section 5 |
| Wrapper category dispatch | `scripts/phantom-api-precheck.ps1:273-291` | Section 6 |

## Build groups (single Builder cycle)

| Section | File | Edit kind |
|---|---|---|
| 1 | `scripts/phantom_api_ast_helper.py` | Add `_collect_param_annotations` + extend `build_index()` signature dict |
| 2 | `scripts/phantom_api_ast_helper.py` | Append `TypeShape` class + `_annotation_to_type_shape` + helpers |
| 3 | `scripts/phantom_api_ast_helper.py` | Append `ValueShape` + `_value_to_shape` + `_value_matches_shape` |
| 4 | `scripts/phantom_api_ast_helper.py` | Append `find_type_shape_phantoms` |
| 5 | `scripts/phantom_api_ast_helper.py` | Wire into `main()` phantom merge |
| 6 | `scripts/phantom-api-precheck.ps1` | Add 3rd category branch in helper-output dispatch |
| 7 | `tests/test_ad685c_phantom_type_shape.py` | NEW — 12 tests |

Bundle Sections 1+5 into a single multi_replace call (`scripts/phantom_api_ast_helper.py` 2-block edit). Sections 2+3+4 are pure appends; can land via a single `replace_string_in_file` anchored on the helper module's `# AD-685b: Method-name validation against resolved class.` divider region — append the new AD-685c block AFTER the existing AD-685b helpers but BEFORE `def main(`.

## Test discipline

- Tests load the helper via `importlib.util` since it lives outside `src/probos/`. Use this skeleton:
  ```python
  import importlib.util
  from pathlib import Path
  REPO_ROOT = Path(__file__).resolve().parent.parent
  HELPER_PATH = REPO_ROOT / "scripts" / "phantom_api_ast_helper.py"
  _spec = importlib.util.spec_from_file_location("phantom_api_ast_helper", HELPER_PATH)
  _mod = importlib.util.module_from_spec(_spec)
  _spec.loader.exec_module(_mod)
  ```
- Synthetic source fixtures go under `tmp_path / "probos" / "<file>.py"`. Pass `tmp_path` (not the inner `probos/`) as `src_root` to `_mod.build_index()` — the helper walks recursively.
- Clear the module's index caches between fixture-bearing tests:
  ```python
  _mod._INDEX_CACHE.clear()
  _mod._CLASS_METHODS_CACHE.clear()
  _mod._RUNTIME_ATTRS_CACHE.clear()
  _mod._RUNTIME_CONFLICTS_CACHE.clear()
  ```
- Test #16 (self-test) uses `subprocess.run(["pwsh", ...])`. If `pwsh` is not on PATH in CI, fall back to `powershell` or skip with `pytest.importorskip`-style guard. Don't let CI portability gaps block the wave.

## Pre-flight

1. `git status` — confirm clean working tree.
2. `git pull` — confirm you're at HEAD; verify_build before edits with `pytest tests/ -q -n 8 --dist=loadfile` to capture baseline 11106. Document any deviation in build report.
3. `pwsh ./scripts/phantom-api-precheck.ps1 prompts/ad-685c-phantom-type-shape-v1.md` — capture pre-build candidates (expected: intro-not-in-index FPs only). Document in build report.

## Per-commit quality gates

After Sections 1–6 land but BEFORE writing tests, run:
```
python scripts/phantom_api_ast_helper.py --src-root src/probos < /dev/null
```
on Linux or PowerShell equivalent on Windows — confirms no syntax error in the helper after edits. Then:
```
pytest tests/test_ad685c_phantom_type_shape.py -v -n 0
```
on the new test file alone. Test #16 (self-test) gates the whole prompt.

Final gate:
```
pytest tests/ -q -n 8 --dist=loadfile
```
Acceptance: 11116-11118 passing, 0 net regressions vs baseline 11106. 1 known xdist flake (`test_dreaming::test_nl_to_dream_cycle_changes_weights`) tolerated.

## Hard-stop conditions

- **Helper output JSON shape change**: existing kwarg-phantom records MUST NOT gain a `category` field (back-compat for downstream consumers). The new `category="type_shape_mismatch"` field is on the new records only. If you find yourself adding `category` to existing record shapes, STOP — that's a breaking change.
- **`build_index()` cache invalidation**: the helper relies on `_INDEX_CACHE` keyed by src_root. Adding `param_annotations` to the cached dict shape is fine BUT the cache will retain the new shape. Tests must clear the cache between fixtures (per "Test discipline" above). If a test fails because index keys collide across fixtures, the cache wasn't cleared — fix the test, not the helper.
- **Don't widen `_NOISY_METHODS` / `_NOISY_RECEIVER_TOKENS`**: those are AD-685/685b tunings. AD-685c reuses them but does not edit them.
- **Don't change exit-code semantics**: `type_shape_mismatch` records contribute to non-zero exit per existing `$totalPhantoms -gt 0` rule. No new exit code.

## Tracker updates (post-build)

- `PROGRESS.md` — prepend AD-685c v1 CLOSED entry (one paragraph, follow Wave 45 / 43 / 42 shape).
- `docs/development/roadmap.md` — find AD-685c row, flip status to "Complete (Wave 46)".
- `DECISIONS.md` — prepend AD-685c entry to Era V (anchor on `## Era V — Civilization (Phases 31-36)\n\n### AD-695` per Wave 42 lesson; do NOT anchor on bare `### AD-695`).
- `prompts/wave-plan.yaml` id="46" — flip `prompts_already_drafted: false` → `true` AND `status: pending` → `status: closed` (or per orchestrator convention, leave to `wave-orchestrator.ps1 advance`).

## Issue close

GH issue #406. Attempt close via MCP. EMU 403 likely (per Waves 31–45 history) — if blocked, document in build report and move on. User closes manually.

## Single commit message

```
Wave 46: AD-685c v1 phantom-API type-shape validation
```

Push to origin/main. Done.
