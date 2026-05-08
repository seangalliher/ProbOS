# AD-700b CognitiveJournal Level Tagging Build Report

**Title:** Cognitive Journal level tagging for `diagnose_system`
**Prompt:** `prompts/ad-700b-cognitive-journal-level-tagging-v1.md`
**Builder:** Builder agent (continuous-build, Wave 129)
**Date:** 2026-05-08
**Status:** SHIPPED

## Files Changed

- `src/probos/cognitive/journal.py` — added `level`/`level_rank` columns to `_SCHEMA_BASE`, added `idx_journal_level` to `_SCHEMA_INDEXES`, added `_migrate_ad700b()` (called between ALTER block and `_SCHEMA_INDEXES`), added `level`/`level_rank` kwargs to `record()` and INSERT statement.
- `src/probos/cognitive/cognitive_agent.py` — appended `level=` / `level_rank=` kwargs (gated on `observation.get('intent') == 'diagnose_system'`) to the existing journal `record()` call at `:1722-1748`.
- `tests/test_ad700b_journal_level_tag.py` — new (6 tests).

## Sections Implemented

- **D1** Schema additions: `level` TEXT and `level_rank` INTEGER columns; `idx_journal_level` index. ✅
- **D2** `_migrate_ad700b()` migration mirroring BF-031 split-base/migration/indexes pattern; called from `start()` between the AD-432/AD-492 ALTER block and `_SCHEMA_INDEXES` execution. ✅
- **D3** `record()` extended with `level: str = ""` / `level_rank: int = 0` kwargs and INSERT updated. ✅
- **D4** `cognitive_agent._decide_via_llm` journal-record call now passes `level`/`level_rank` from `observation`, gated on `intent == "diagnose_system"`. ✅
- **D5** 6 tests: L3 round-trip, non-diagnose default empty, L1-L5 round-trip, legacy migration, migration idempotency, index existence. ✅

## Post-Build Section Audit

Every D# section maps to implemented code. No omissions.

## Test Results

- Focused: `pytest tests/test_ad700b_journal_level_tag.py -v -n 0` → **6/6 pass** in 0.58s.
- Adjacent regression: `pytest tests/test_cognitive_journal.py tests/test_ad700_multi_level_diagnostics.py -q -n 0` → **53/53 pass** in 1.72s.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` → **12752 passed, 16 skipped, 175 warnings** in 8m26s. Test count up by 6 from AD-491 baseline (12746 → 12752).

## Deviations

None. Prompt implemented as written.
