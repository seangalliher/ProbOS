# BF-183: Sub-Task Chain Budget-Aware Retry Before Fallback

**Type:** Bug Fix (quality improvement)
**Priority:** Medium
**Relates to:** AD-632a (Sub-Task Protocol), AD-636 (LLM Priority Scheduling)
**Issue:** #TBD

## Problem

When a sub-task chain step times out (15s default), `SubTaskExecutor` immediately raises `SubTaskStepError`, which causes `_execute_sub_task_chain()` in `cognitive_agent.py` to catch it and fall back to single-call `_decide_via_llm()`. This produces lower-quality output because single-call reasoning loses the multi-step decomposition benefits (query → analyze → compose → evaluate → reflect).

The timeout is typically caused by transient LLM proxy contention — multiple agents firing proactive chains simultaneously. A brief backoff and retry would succeed in most cases, preserving chain quality.

## Design: Budget-Aware Retry

Instead of a fixed retry count, use **remaining chain time budget** to decide whether to retry:

1. Step times out at its `timeout_ms` (15s)
2. Calculate `remaining_budget = chain_timeout_ms - elapsed_chain_time`
3. If `remaining_budget >= step.timeout_ms` → backoff 2s, retry the failed step once
4. If `remaining_budget < step.timeout_ms` → no retry, raise `SubTaskStepError` immediately (let fallback handle it)

This naturally yields 0-1 retries depending on when in the chain the failure occurs:
- Early step failure (e.g., analyze at 15s into a 30s chain): ~13s remaining after 2s backoff → retry possible
- Late step failure (e.g., reflect at 28s into a 30s chain): ~0s remaining → no retry, fall back

### Backoff Duration

Use a fixed 2-second backoff (not exponential). Rationale:
- These are transient LLM contention timeouts, not persistent failures
- Exponential backoff is overkill for a single retry
- 2s is enough for one competing chain to release the LLM proxy

## Engineering Principles Compliance

- **Single Responsibility:** Retry logic lives in `_execute_single_step()` only. No retry awareness needed in callers.
- **Open/Closed:** No changes to `SubTaskHandler` protocol or handler implementations. Retry is transparent to handlers.
- **Fail Fast:** If budget is insufficient, fail immediately — don't attempt a doomed retry.
- **DRY:** Reuse the same `handler(spec, step_context, prior_results)` call for retry. No duplicated execution logic.
- **Law of Demeter:** Budget calculation uses only data already available in `_execute_single_step` (passed as parameter).

## Implementation

### File: `src/probos/cognitive/sub_task.py`

#### 1. Add `chain_start_time` parameter to `_execute_single_step()`

Add parameter `chain_start_time: float` and `chain_timeout_ms: int` to `_execute_single_step()`. These are passed from `_execute_steps()` which already has access to the chain object and can compute `chain_start` from `time.monotonic()` at chain start.

**IMPORTANT:** `_execute_steps()` does NOT currently track `chain_start_time` — it's tracked in `_execute_chain()`. Pass it down:
- `_execute_chain()` already computes `chain_start = time.monotonic()` at line 291
- Pass `chain_start` into `_execute_steps()` as a new parameter
- `_execute_steps()` passes it through to `_execute_single_step()`

#### 2. Modify timeout handling in `_execute_single_step()`

Current code (lines 490-498):
```python
try:
    result = await asyncio.wait_for(
        handler(spec, step_context, prior_results),
        timeout=spec.timeout_ms / 1000,
    )
except asyncio.TimeoutError:
    raise SubTaskStepError(
        spec.name, spec.sub_task_type,
        f"Step timed out after {spec.timeout_ms}ms",
    )
```

Replace with budget-aware retry:
```python
try:
    result = await asyncio.wait_for(
        handler(spec, step_context, prior_results),
        timeout=spec.timeout_ms / 1000,
    )
except asyncio.TimeoutError:
    # BF-183: Budget-aware retry before fallback
    elapsed_ms = (time.monotonic() - chain_start_time) * 1000
    remaining_ms = chain_timeout_ms - elapsed_ms
    backoff_ms = 2000  # Fixed 2s backoff

    if remaining_ms >= (spec.timeout_ms + backoff_ms):
        logger.info(
            "BF-183: Step '%s' timed out, retrying (%.0fms budget remaining)",
            spec.name, remaining_ms,
        )
        await asyncio.sleep(backoff_ms / 1000)

        # Retry with remaining budget as timeout (capped at step timeout)
        retry_timeout_ms = min(spec.timeout_ms, remaining_ms - backoff_ms)
        try:
            result = await asyncio.wait_for(
                handler(spec, step_context, prior_results),
                timeout=retry_timeout_ms / 1000,
            )
        except (asyncio.TimeoutError, Exception) as retry_exc:
            logger.warning(
                "BF-183: Step '%s' retry also failed: %s",
                spec.name, retry_exc,
            )
            raise SubTaskStepError(
                spec.name, spec.sub_task_type,
                f"Step timed out after {spec.timeout_ms}ms (retry also failed)",
            )
    else:
        logger.info(
            "BF-183: Step '%s' timed out, no budget for retry (%.0fms remaining)",
            spec.name, remaining_ms,
        )
        raise SubTaskStepError(
            spec.name, spec.sub_task_type,
            f"Step timed out after {spec.timeout_ms}ms (no retry budget)",
        )
```

#### 3. Update `_execute_steps()` signature

Add `chain_start_time: float` parameter. Receive it from `_execute_chain()`.

In `_execute_steps()`, pass through to both the single-step and parallel-step paths:
```python
result = await self._execute_single_step(
    spec, step_index, context, list(results),
    chain_id=chain_id, agent_id=agent_id, agent_type=agent_type,
    intent=intent, intent_id=intent_id, journal=journal,
    chain_start_time=chain_start_time,
    chain_timeout_ms=chain.chain_timeout_ms,
)
```

Same for the parallel `wave_tasks` list comprehension.

#### 4. Update `_execute_chain()` to pass `chain_start`

At line 302, `chain_start` is already computed. Pass it into `_execute_steps()`:
```python
await asyncio.wait_for(
    self._execute_steps(
        chain, context, chain_id, results,
        agent_id=agent_id, agent_type=agent_type,
        intent=intent, intent_id=intent_id,
        journal=journal,
        chain_start_time=chain_start,
    ),
    timeout=chain.chain_timeout_ms / 1000,
)
```

#### 5. Journal recording for retried steps

The existing journal recording block (lines 520-540) will fire for the successful retry since it's after the try/except. If the retry fails, SubTaskStepError is raised before journal recording — that's correct (failed steps don't get journal entries, the chain event captures the failure).

For the **first** failed attempt (before retry), add a journal entry with a distinct `dag_node_id` suffix:
```python
# Inside the retry branch, before the sleep:
if spec.sub_task_type != SubTaskType.QUERY and journal is not None:
    dag_node_id = f"st:{chain_id}:{step_index}:{spec.sub_task_type.value}:timeout"
    try:
        await journal.record(
            entry_id=uuid.uuid4().hex,
            timestamp=time.time(),
            agent_id=agent_id,
            agent_type=agent_type,
            tier=spec.tier,
            total_tokens=0,
            latency_ms=spec.timeout_ms,
            intent=intent,
            intent_id=intent_id,
            success=False,
            dag_node_id=dag_node_id,
        )
    except Exception:
        logger.debug("BF-183: Journal recording failed for timeout step", exc_info=True)
```

### File: `src/probos/events.py`

No changes needed. The existing `SubTaskChainCompletedEvent` already has `success` and `fallback_used` fields which capture the outcome. A `retries_attempted` field is not worth adding for a single-retry mechanism — the journal entries provide the detail.

## Testing

### File: `tests/test_bf183_subtask_retry.py`

Write **10-12 tests** covering:

1. **Retry succeeds** — step times out, budget allows retry, retry succeeds → chain completes
2. **Retry fails** — step times out, budget allows retry, retry also times out → SubTaskStepError
3. **No budget for retry** — step times out late in chain, insufficient remaining time → immediate SubTaskStepError with "no retry budget" message
4. **Budget boundary** — remaining budget exactly equals `step.timeout_ms + backoff_ms` → retry attempted
5. **Budget boundary (just under)** — remaining budget is 1ms short → no retry
6. **Non-timeout errors skip retry** — handler raises ValueError, not TimeoutError → no retry, immediate SubTaskStepError (retry is only for timeouts)
7. **Backoff duration** — verify 2s sleep occurs between attempts (mock `asyncio.sleep`)
8. **Retry timeout uses remaining budget** — verify retry timeout is `min(step.timeout_ms, remaining - backoff)`, not full step timeout
9. **Journal records timeout** — verify journal.record called with `:timeout` dag_node_id on first failure
10. **Journal records successful retry** — verify journal.record called with normal dag_node_id on retry success
11. **Optional step timeout** — optional (required=False) step timeout → no retry needed (already skipped gracefully)
12. **Parallel step retry** — step in a parallel wave times out → retry logic still applies per-step

### Test patterns

- Use the existing `SubTaskExecutor` test fixtures from `tests/test_ad636_llm_priority_scheduling.py` and `tests/` for handler mocking patterns
- Mock handlers with `asyncio.TimeoutError` on first call, success on second call (for retry-succeeds tests)
- Use `unittest.mock.AsyncMock` for handlers
- Use `time.monotonic()` mocking or controlled chain_start_time values to test budget calculations

## Verification

```bash
uv run python -m pytest tests/test_bf183_subtask_retry.py -v
uv run python -m pytest tests/test_ad636_llm_priority_scheduling.py -v  # regression
uv run python -m pytest tests/ -k "sub_task" -v  # all sub-task tests
```

## Summary

- **1 source file** modified: `src/probos/cognitive/sub_task.py`
- **1 test file** created: `tests/test_bf183_subtask_retry.py`
- **10-12 tests**
- **0 new dependencies**
- No config changes needed — uses existing `chain_timeout_ms` and `timeout_ms` values
