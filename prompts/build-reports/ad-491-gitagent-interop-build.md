# AD-491 gitagent Interop Adapter Build Report

**Title:** gitagent interop adapter (publish/install boundary only)
**Prompt:** `prompts/ad-491-gitagent-interop-adapter-v1.md`
**Builder:** Builder agent (continuous-build, Wave 129)
**Date:** 2026-05-08
**Status:** SHIPPED

## Files Changed

- `src/probos/interop/__init__.py` — new (package docstring only).
- `src/probos/interop/gitagent.py` — new module with `export_agent_to_gitagent_yaml()` and `import_gitagent_yaml()`.
- `tests/test_ad491_gitagent_interop.py` — new (8 tests).

## Sections Implemented

- **D1** New `src/probos/interop/__init__.py` package with docstring. ✅
- **D2** `src/probos/interop/gitagent.py` module with both public functions. ✅
  - **D2a** `export_agent_to_gitagent_yaml()` — uses `getattr` for safe attribute access; emits `probos` sub-section. ✅
  - **D2b** `import_gitagent_yaml()` — required-key validation; security boundary clears foreign-runtime sovereign IDs. ✅
- **D3** 8 tests covering happy path, missing-attr graceful, capability/intent serialization, round-trip, foreign-runtime sovereign clearing, missing-key ValueError, malformed YAML. ✅

## Post-Build Section Audit

Every D# section maps to implemented code. No omissions.

## Test Results

- Focused: `pytest tests/test_ad491_gitagent_interop.py -v -n 0` → **8/8 pass** in 0.30s.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` → **12746 passed, 16 skipped, 176 warnings** in 8m23s. Test count up by 8 from AD-490 baseline (12738 → 12746).

## Deviations

None. Prompt implemented as written. Used `getattr(..., default)` throughout the export path so `_FakeAgent` `SimpleNamespace` stubs without all attributes (e.g. test_export_handles_missing_sovereign_id_gracefully) still produce valid YAML.
