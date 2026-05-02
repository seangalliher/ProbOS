# AD-463 Build Report

**Date:** 2026-05-01
**Builder:** Wave 7 continuous-build (5 of 5)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+4: EventTypes | `src/probos/events.py` | ✅ Added `MODEL_ROUTED`, `MODEL_FALLBACK` after AD-467 events |
| Section 1: ModelDescriptor + ModelRegistry | `src/probos/cognitive/model_registry.py` (new) | ✅ Frozen dataclass + 3 default seeds (gpt-4o-mini/claude-sonnet-4-6/claude-opus-4-0) |
| Section 2: ModelRouter | `src/probos/cognitive/model_router.py` (new) | ✅ Cost-aware + cost-ceiling filter; cross-tier fallback; HebbianRouter NOT in v1 |
| Section 3a: __init__ kw-only model_router param | `src/probos/cognitive/llm_client.py` | ✅ Public `self.model_router` attribute |
| Section 3b: _resolve_model_for_tier helper | `src/probos/cognitive/llm_client.py` | ✅ Defensive `getattr(..., None)` for tests that bypass `__init__` via `__new__` |
| Section 3c: SEARCH/REPLACE in _complete_inner:441-447 | `src/probos/cognitive/llm_client.py` | ✅ `_override = self._resolve_model_for_tier(attempt_tier); model = _override or tc["model"]` |
| Section 5: ModelRoutingConfig | `src/probos/config.py` | ✅ Pydantic class + field on `SystemConfig` |
| Section 6: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ Wires `runtime.model_registry` + `runtime.model_router` + post-init `runtime.llm_client.model_router = ...` |
| Tests | `tests/test_ad463_model_routing.py` (new) | ✅ 16/16 pass at `-n 0` (3 extra LLM-client integration tests beyond the 13-spec) |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4169` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad463_model_routing.py -v -n 0` → **16/16 passed in 0.42s**
- Full parallel gate: **10,464 passed (+16 vs AD-467 baseline 10,448), 14 skipped, 151 warnings in 353.45s**

## Notes / Decisions

- **Defensive `getattr` fix:** the BF-069 `TestDwellTimeCriterion` tests construct `OpenAICompatibleClient.__new__(...)` to bypass `__init__`, so `self.model_router` is not set. Initial `if self.model_router is None` raised `AttributeError` on these 4 tests. Fixed with `router = getattr(self, "model_router", None)` — preserves expected behavior for normal-construction paths and gracefully no-ops for `__new__` bypasses. Standing Wave 5 superset-filter discipline (#4): callers that don't construct via `__init__` are unaffected.
- HebbianRouter integration wholesale-deferred to AD-463d. `LLMRequest.agent_id` does not exist; v1 routes by tier+cost only. No theater.
- `runtime.model_router` is the public attribute (no leading underscore) per Wave 5 convention #1.
- The SEARCH block matched `_complete_inner` line 441-447 verbatim per Wave 7 third-pass review — NOT `complete()`.
- v1 emits `MODEL_ROUTED`/`MODEL_FALLBACK` events — AD-467d Cost Tracker will consume the MODEL_ROUTED payload for per-model cost aggregation.

## Pre-Commit Sanity Check

10 files changed, ~470 insertions, 5 deletions (1 line roadmap, 4 lines from `__init__` signature reformatting + `_complete_inner` 1-line edit). Max per-file deletion: 4 lines (llm_client.py refactor). Well under 200-line threshold.
