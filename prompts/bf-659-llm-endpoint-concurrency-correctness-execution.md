# BF-659 Builder Execution — LLM endpoint concurrency correctness

GitHub issue: #1025  
**Base:** HEAD `509e8cd7`  
**Scope:** execute only `prompts/bf-659-llm-endpoint-concurrency-correctness.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-659-llm-endpoint-concurrency-correctness.md`
- `src/probos/cognitive/llm_client.py`
- `tests/test_bf654_endpoint_concurrency_cap.py`
- `tests/test_ad636_llm_priority_scheduling.py`
- `tests/test_bf069_llm_health.py`
- `tests/test_bf612_empty_content_retry.py`
- `tests/test_ad617_llm_rate_governance.py`

## Exact files

**Modify only:**
- `src/probos/cognitive/llm_client.py`
- `tests/test_bf654_endpoint_concurrency_cap.py`

**Do not modify:**
- `src/probos/config.py`
- `src/probos/types.py`
- `PROGRESS.md`
- `DECISIONS.md`
- any rate-governance, routing, or cache module

## Highest-risk instructions

1. Keep `OpenAICompatibleClient._complete_inner(self, request)` signature unchanged. Existing tests patch and directly call it.
2. Keep the priority lane in `complete()`. Put lane cleanup around every subsequent await so cancellation cannot leak it.
3. Use task-local state (`ContextVar` or equally concurrency-safe mechanism) to communicate CRITICAL bypass. Never use a shared instance boolean.
4. Move endpoint acquire to the actual `attempt_tier` inside `_complete_inner()`.
5. Background endpoint acquisition is hard/cancellable: **no timeout fail-open and no transport without a permit**.
6. Hold one attempt permit across BF-612 refresh/retry and all 429 sleeps/retries; release before fallback to another endpoint.
7. Preserve CRITICAL bypass and the lane→endpoint lock order. Never acquire a lane inside `_complete_inner()`.
8. `max_inflight_per_endpoint <= 0` remains the explicit disabled path.

## Required regressions

Replace the obsolete endpoint-timeout-fail-open test and add behavioral coverage for:

- timeout herd remains at cap,
- cancellation during endpoint wait restores lane,
- cancellation during BF-612 jitter restores lane + endpoint,
- distinct endpoint fallback observes target cap,
- BF-612 retry stays under one permit,
- 429 retry stays under one permit,
- direct `_complete_inner()` calls are governed,
- CRITICAL bypass and zero-disabled behavior remain.

## Commands

Focused:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf654_endpoint_concurrency_cap.py -q -n 0

Blast radius:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad636_llm_priority_scheduling.py tests/test_ad637f_priority.py tests/test_bf612_empty_content_retry.py tests/test_ad617_llm_rate_governance.py tests/test_bf069_llm_health.py tests/test_per_tier_llm.py tests/test_llm_client.py -q -n 0

Set an isolated `PROBOS_DATA_DIR` first.

## Stop conditions

Stop immediately if the fix appears to require:

- a new `LLMRequest`/`BaseLLMClient` field,
- `_complete_inner` signature churn,
- changes to retry counts, fallback order, RPM policy, cache behavior, or CRITICAL bypass,
- or any branch that permits background `_call_api()` without the actual endpoint permit.

Do not commit. Report files changed, exact test counts, and any deviation from the spec.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
