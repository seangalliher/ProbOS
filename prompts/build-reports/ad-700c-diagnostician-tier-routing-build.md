# AD-700c Diagnostician Per-Call LLM Tier Routing Build Report

**Title:** Diagnostician per-call LLM tier override from `level_llm_tier`
**Prompt:** `prompts/ad-700c-diagnostician-tier-routing-v1.md`
**Builder:** Builder agent (continuous-build, Wave 129)
**Date:** 2026-05-08
**Status:** SHIPPED

## Files Changed

- `src/probos/cognitive/cognitive_agent.py` — added `_resolve_tier_for_observation()` helper next to `_resolve_tier()`; in `_decide_via_llm` added the L4/L5 short-circuit guard before the `LLMRequest` construction and rewired `tier=` from the static `_resolve_tier()` call to the new per-observation helper.
- `tests/test_ad700c_diagnostician_tier_routing.py` — new (10 tests).

## Sections Implemented

- **D1** New `_resolve_tier_for_observation(observation)` helper: returns string override when present, `""` on explicit None, falls back to `self._resolve_tier()` otherwise. ✅
- **D2** `_decide_via_llm` rewired: per-call tier resolved once; short-circuit guard returns the structured no-LLM decision when tier is empty AND intent is `diagnose_system`; `LLMRequest(tier=...)` uses the resolved per-call tier. ✅
- **D3** 10 tests (3 unit on helper + 7 integration through `_decide_via_llm`): override string, explicit None empty, missing-key fallback, L1 deep, L2 fast, L3 fast, L4 short-circuit, L5 short-circuit, non-diagnose static fallback, non-diagnose-with-None-still-uses-LLM defensive scoping. ✅

## Post-Build Section Audit

Every D# section maps to implemented code. No omissions.

## Test Results

- Focused: `pytest tests/test_ad700c_diagnostician_tier_routing.py -v -n 0` → **10/10 pass** in 0.36s.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` → **12762 passed, 16 skipped, 176 warnings** in 8m12s. Test count up by 10 from AD-700b baseline (12752 → 12762).

## Deviations

- Added 3 unit tests on the helper in addition to the 7 integration tests the prompt requested. The unit tests proved valuable during dev (caught the `_cognitive_journal` property setter issue which is unrelated to AD-700c logic and was a test-fixture-only concern — fixed by removing the unnecessary `agent._cognitive_journal = None` line, since the journal block already guards on `if self._cognitive_journal:`).
