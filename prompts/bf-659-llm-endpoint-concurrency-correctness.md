# BF-659 — LLM endpoint concurrency correctness

**One-line:** Repair the BF-654 follow-up so every background transport attempt holds the semaphore for the endpoint it actually targets, endpoint saturation never fails open, and cancellation cannot leak the already-acquired priority-lane permit.

**Status:** Ready to build  
**Type:** Bug fix — **BF-659** (current highest verified BF is BF-658; no new AD)  
GitHub issue: #1025
**HEAD verified:** `509e8cd7` (2026-07-09)  
**Dependencies:** BF-654, BF-612, AD-617, AD-636/637f  
**Estimated tests:** 8–10 new/updated in the existing BF-654 test file; existing LLM suites unchanged  

## Problem

BF-654 added a per-endpoint semaphore in `OpenAICompatibleClient.complete()`, but three correctness gaps remain:

1. **Endpoint timeout fails open.** `complete()` catches `asyncio.TimeoutError`, jitters, and calls `_complete_inner()` without an endpoint permit. With cap=1 and a wide priority lane, five waiters reproduce transport peak=5.
2. **Cancellation leaks the lane.** The lane is acquired before the endpoint wait, but the cleanup `try/finally` begins only after the endpoint wait/jitter. Cancellation there exits before the lane release. Reproduced background semaphore value=0 when 1 was expected.
3. **Requested-tier key is not the transport key.** `complete()` chooses the endpoint semaphore from `request.tier`. `_complete_inner()` may fall back to another tier whose `base_url|api_format` differs. That transport therefore bypasses the target endpoint's semaphore; reproduced deep endpoint cap=1 with peak=2.

The current comment that the text fallback chain stays on one endpoint is not a valid invariant because `CognitiveConfig` supports distinct per-tier base URLs.

## Architecture decisions

### DD-1 — Keep the priority lane in `complete()`; move endpoint ownership to each `_complete_inner()` attempt

`complete(request, *, priority=...)` remains the only priority-lane boundary. `_complete_inner(request)` remains signature-compatible for tests and direct internal test calls. Add a module-scope task-local marker, preferably `ContextVar[bool]` with `default=True`, set by `complete()` to `not is_critical`. Hold the returned token and call `.reset(token)` in `finally`. `_complete_inner()` reads that marker; direct callers inherit the default and are background-governed.

This preserves:
- CRITICAL bypass: `complete()` sets the marker false, so no endpoint semaphore is acquired.
- Existing `_complete_inner(request)` signature and positional-only fakes.
- Direct `_complete_inner()` callers in `tests/test_bf069_llm_health.py`, which remain governed rather than silently bypassing.

Do **not** add a `priority` parameter to `_complete_inner()` and do not use a mutable instance flag; concurrent calls need task-local state.

### DD-2 — Endpoint saturation is fail-closed for background transport

Remove the endpoint-acquire timeout/jitter fail-open. A background call waits cancellably for the endpoint permit. The lane's existing timeout behavior is not redesigned here, but **no background transport may execute without the actual target endpoint permit**.

The endpoint permit is acquired with normal cancellable `await endpoint_sem.acquire()`. Cancellation while waiting owns no endpoint permit and must propagate. This is the only mechanism that makes `max_inflight_per_endpoint` a real cap rather than a best-effort hint.

### DD-3 — Acquire by `attempt_tier`, immediately around the whole attempt

Inside `_complete_inner()`, after choosing `attempt_tier` and before entering its 429 retry loop, resolve `endpoint_sem = self._endpoint_semaphores.get(self._client_key(attempt_tier))`. For background-governed calls, acquire it once for that attempt and release it in an attempt-local `finally`.

The held scope includes:
- every `_call_api()` for that attempt,
- BF-612 empty-content refresh plus its second `_call_api()`,
- AD-617 429 backoff and same-tier retries.

Release before advancing to a fallback tier, then acquire the fallback tier's real endpoint. Cache-only/error paths run no transport and need no endpoint permit.

### DD-4 — Preserve lock-order safety

The only nested order remains **lane → endpoint**. No code may acquire a lane from inside `_complete_inner()`, and no code may acquire endpoint → lane. Release endpoint in `_complete_inner()` before `complete()` releases the lane.

A CRITICAL call holds only its interactive lane and bypasses endpoint caps exactly as BF-654 intended.

### DD-5 — Endpoint disable escape hatch remains

`LLMRateConfig.max_inflight_per_endpoint <= 0` still creates no endpoint semaphores. In that explicit disabled mode, the new per-attempt helper is a no-op. Do not change the config field/default in this BF.

## Implementation

### Section 1 — Make lane cleanup cancellation-safe

Modify `OpenAICompatibleClient.complete()` in `src/probos/cognitive/llm_client.py`:

- Keep the existing lane selection and lane-acquire timeout behavior.
- Begin the outer `try/finally` immediately after lane acquisition (or timeout), before any further await.
- Set/reset the task-local endpoint-governance marker inside that protected region.
- Call `_complete_inner(request)` exactly once.
- In `finally`, reset the marker and release the lane iff this call acquired it.
- Delete requested-tier endpoint selection/acquire/release from `complete()`.
- Delete `_endpoint_acquire_timeout`; endpoint acquisition no longer times out.
- `_endpoint_failopen_jitter_seconds` may remain only if still used by the BF-612 retry jitter. Rename it only if necessary; avoid unrelated cleanup.

Cancellation at any point after lane acquisition must release the lane and re-raise `asyncio.CancelledError`.

### Section 2 — Add one private per-attempt endpoint permit helper

In `src/probos/cognitive/llm_client.py`, add a focused private async context manager or equivalent private helper with this contract:

- Input: `attempt_tier: str`.
- If task-local governance is false (CRITICAL) or `_endpoint_semaphores` is empty, yield without acquiring.
- Otherwise look up `_client_key(attempt_tier)`, await that semaphore, yield, and release exactly once in `finally`.
- Never catches `CancelledError`.
- Never fails open.

Keep it private; no new public API is needed.

### Section 3 — Wrap each actual fallback attempt

In `_complete_inner()`:

- Keep the existing fallback order, rate limiter, model resolution, retry limits, cache, health state, and response construction.
- Wrap the complete attempt-tier retry scope with the helper from Section 2.
- Hold the permit through BF-612's refresh/retry and all 429 sleeps/retries.
- Release it before the loop moves to the next fallback tier.
- Do not acquire permits for tiers skipped as known-unreachable before transport.

The transport invariant after this section is: for any non-CRITICAL `_call_api()` invocation, the semaphore keyed by that invocation's `attempt_tier` client key has been acquired by this task.

### Section 4 — Update BF-654 tests with real regressions

Update `tests/test_bf654_endpoint_concurrency_cap.py`; do not create a competing test file.

Required tests:

1. `test_endpoint_timeout_cannot_fail_open_past_cap` — cap=1, lane large, five calls, first transport held long enough that prior short timeout would fire; assert peak exactly 1 and all calls finish. This replaces the obsolete `test_endpoint_failopen_on_timeout` contract.
2. `test_cancel_during_endpoint_wait_restores_lane` — drain target endpoint, start NORMAL call, cancel while waiting; assert cancellation propagates and background lane returns to its initial value.
3. `test_cancel_during_retry_jitter_restores_lane_and_endpoint` — force BF-612 empty response, patch jitter sleep to block, cancel; assert both lane and endpoint permit restored.
4. `test_fallback_uses_actual_target_endpoint_cap` — configure distinct fast/deep base URLs; pre-hold or occupy deep's semaphore, force fast connect failure, and prove the fallback does not enter deep transport until the deep permit is available. Add a two-call peak assertion (`deep_peak == 1`).
5. `test_permit_covers_bf612_retry` — empty then success on one tier; inspect semaphore state inside both transport calls and assert the same attempt permit remains held.
6. `test_permit_covers_429_backoff_and_retry` — first transport raises HTTP 429, second succeeds; patch sleep, assert the endpoint remains held through the retry interval and second transport.
7. `test_critical_still_bypasses_actual_attempt_endpoint` — keep the existing CRITICAL bypass test, but make it behavioral through `_call_api()` or retain the `_complete_inner` fake plus a source-independent assertion.
8. `test_direct_complete_inner_call_is_background_governed` — call `_complete_inner()` directly (as the BF-069 tests do), cap=1, two attempts; assert transport peak=1.
9. Preserve zero-disabled behavior and independent-endpoint coverage.

Do not rely only on private `Semaphore._value`; use transport entry Events/counters for the headline cap and fallback tests. Private value assertions are acceptable only for exact cleanup accounting.

## Existing compatibility / caller audit

`_complete_inner` has one production caller: `OpenAICompatibleClient.complete()`. Existing direct test callers/fakes are:

- `tests/test_ad636_llm_priority_scheduling.py` patches `_complete_inner(request)` with `AsyncMock` and `slow_complete(req)`.
- `tests/test_bf654_endpoint_concurrency_cap.py` patches `_complete_inner(request)`.
- `tests/test_bf069_llm_health.py` calls `_complete_inner(LLMRequest(...))` directly.
- `tests/test_ad742a_vision_fast_tier.py` source-inspects `_complete_inner()` fallback behavior.

Therefore the signature must remain `async def _complete_inner(self, request: LLMRequest) -> LLMResponse`.

## Do Not Build

- Do **not** change RPM/token governance, cache size/eviction, model routing, health thresholds, fallback order, retry counts, or tier configuration.
- Do **not** add per-endpoint config maps or separate clients.
- Do **not** throttle CRITICAL calls with the endpoint semaphore.
- Do **not** remove the AD-636 lane timeout/fail-open in this BF; BF-659 only guarantees endpoint correctness and lane cleanup.
- Do **not** alter BF-612's one-refresh-per-tier rule or AD-617's 429 policy.
- Do **not** change `_complete_inner()`'s signature or public `BaseLLMClient` API.
- Do **not** edit `PROGRESS.md` or `DECISIONS.md` while executing this architect-authored prompt; tracking is handled separately after validation.

## Files

**Modify:**
- `src/probos/cognitive/llm_client.py`
- `tests/test_bf654_endpoint_concurrency_cap.py`

**Reference only:**
- `src/probos/config.py`
- `src/probos/types.py`
- `tests/test_ad636_llm_priority_scheduling.py`
- `tests/test_bf069_llm_health.py`
- `tests/test_bf612_empty_content_retry.py`
- `tests/test_ad617_llm_rate_governance.py`
- `tests/test_per_tier_llm.py`

## Test commands

Focused:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf654_endpoint_concurrency_cap.py -q -n 0

Blast radius:

    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad636_llm_priority_scheduling.py tests/test_ad637f_priority.py tests/test_bf612_empty_content_retry.py tests/test_ad617_llm_rate_governance.py tests/test_bf069_llm_health.py tests/test_per_tier_llm.py tests/test_llm_client.py -q -n 0

Use an isolated `PROBOS_DATA_DIR`. Do not use `-n auto`; the repository's Architect gate is `-n 4 --dist=loadfile` only for the full gate.

## Acceptance criteria

1. Background transport never runs without the semaphore for the actual attempt endpoint; cap=1 remains peak=1 after any wait duration.
2. Fallback to a distinct endpoint observes the target endpoint's cap.
3. Cancellation during endpoint wait, BF-612 jitter/refresh, transport, or 429 backoff restores every acquired lane/endpoint permit and propagates cancellation.
4. The endpoint permit spans BF-612's retry and all same-tier 429 retries.
5. CRITICAL calls still bypass endpoint caps.
6. `_complete_inner(request)` keeps its exact signature and direct callers are governed safely.
7. `max_inflight_per_endpoint <= 0` retains the explicit disabled/unbounded behavior.
8. Focused and blast-radius commands pass with no unrelated test edits.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Stop conditions

Stop and return to the Architect if implementation would require:

- changing `BaseLLMClient.complete()` or `LLMRequest`,
- changing fallback/rate-governance policy,
- weakening CRITICAL bypass,
- adding a new config surface,
- or allowing any background `_call_api()` without an acquired target permit.

## Verified Against Codebase (2026-07-09, HEAD 509e8cd7)

- `src/probos/cognitive/llm_client.py`: `OpenAICompatibleClient.complete()` acquires the priority lane, then requested-tier endpoint semaphore, and starts cleanup only after endpoint wait/jitter.
- `src/probos/cognitive/llm_client.py`: `_complete_inner(request)` selects `attempt_tier`, then performs BF-612 retry and AD-617 429 retry inside that attempt.
- `src/probos/cognitive/llm_client.py`: `_client_key(tier)` returns `base_url|api_format`; clients and endpoint semaphores use this key.
- `src/probos/config.py`: `LLMRateConfig.max_inflight_per_endpoint: int = 8` exists.
- `src/probos/types.py`: `Priority.CRITICAL`, `NORMAL`, and `LOW` are the live enum values.
- Grep found one production `_complete_inner()` call and the test callers listed above.
- Empirical probes at HEAD: cap=1 timeout herd reached peak=5; cancellation during jitter left background lane at 0 instead of 1; distinct fast→deep fallback reached deep peak=2 with cap=1.
