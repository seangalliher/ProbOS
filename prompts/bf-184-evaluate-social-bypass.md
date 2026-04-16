# BF-184: Evaluate Step Suppresses Responses to Captain and @Mentioned Messages

**Type:** Bug Fix
**Priority:** High
**Relates to:** AD-632e (Evaluate handler), BF-157 (@mention bypass), AD-407d (Captain post detection)
**Issue:** #TBD

## Problem

When the Captain posts a message in the Ward Room (e.g., a welcome message), all crew agents receive `ward_room_notification` intents and activate sub-task chains. The chains compose responses, but the **Evaluate** step scores them all as low quality (0.00–0.50) and recommends `suppress` or `revise`. The **Reflect** step then short-circuits to `[NO_RESPONSE]` based on the evaluate recommendation. Result: the Captain gets zero replies.

Root cause: The evaluate handler (`src/probos/cognitive/sub_tasks/evaluate.py`) has **zero awareness** of the social context — specifically:
1. Whether the original message is from the **Captain** (chain of command requires a response)
2. Whether the agent was **@mentioned** (BF-157 established that @mentions require a response)

The observation dict already carries `params.author_id` (set to `"captain"` for Captain messages) and `params.was_mentioned` (set in `ward_room_router.py` line 448), but these are consumed by `_build_observation()` (line 2862-2876) for the LLM prompt text only — they are **not** propagated as structured flags into the chain context that the evaluate handler receives.

## Design

Two-part fix:

### Part A: Propagate social obligation flags into chain context

In `cognitive_agent.py`, the `_execute_sub_task_chain()` method (line 1580) already injects `_agent_id`, `_agent_type`, `_callsign`, `_department` into the observation dict. Add two more flags:

```python
# BF-184: Social obligation flags for evaluate/reflect bypass
_params = observation.get("params", {})
observation["_from_captain"] = _params.get("author_id", "") == "captain"
observation["_was_mentioned"] = _params.get("was_mentioned", False)
```

Add these lines after the existing `_department` injection (after line 1588), inside the same block.

### Part B: Auto-approve in evaluate handler when social obligation exists

In `evaluate.py`, add an early return in `EvaluateHandler.__call__()` **before** the LLM call (after the mode dispatch, around line 238):

```python
# BF-184: Captain messages and @mentions bypass quality gate.
# Social obligation outranks quality scoring — failing to respond
# to the Captain is worse than a mediocre response.
if context.get("_from_captain") or context.get("_was_mentioned"):
    reason = "captain_message" if context.get("_from_captain") else "mentioned"
    logger.info(
        "BF-184: Evaluate auto-approved for %s (social obligation: %s)",
        context.get("_agent_type", "unknown"),
        reason,
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name=spec.name,
        result={
            "pass": True,
            "score": 1.0,
            "criteria": {},
            "recommendation": "approve",
            "bypass_reason": reason,
        },
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )
```

This also saves LLM tokens — the evaluate call is skipped entirely for socially obligated responses.

## Engineering Principles Compliance

- **Single Responsibility:** Evaluate handler gains one early-exit check. No new class, no new file. The bypass is self-contained.
- **Open/Closed:** `SubTaskResult` structure unchanged. `bypass_reason` is an informational field in the result dict, not a new dataclass field.
- **Fail Fast:** If flags are missing, defaults are `False` — no bypass. Fail-open only when social obligation is explicitly set.
- **DRY:** Reuses existing `_from_captain` / `_was_mentioned` flags. No duplicate author detection.
- **Law of Demeter:** Flags are flat context keys, no reaching into nested objects.
- **Defense in Depth:** The compose step still produces the actual content — we're only bypassing the quality gate, not skipping composition.
- **BF-157 precedent:** This mirrors BF-157's approach where `was_mentioned` bypasses cooldown/caps in ward_room_router.py. Same principle: social obligation > throttling.

## Implementation

### File 1: `src/probos/cognitive/cognitive_agent.py`

**Location:** `_execute_sub_task_chain()` method, after line 1588 (after `observation["_department"] = _dept`).

Add:
```python
# BF-184: Social obligation flags for evaluate/reflect bypass
_params = observation.get("params", {})
observation["_from_captain"] = _params.get("author_id", "") == "captain"
observation["_was_mentioned"] = _params.get("was_mentioned", False)
```

### File 2: `src/probos/cognitive/sub_tasks/evaluate.py`

**Location:** Inside `EvaluateHandler.__call__()`, after line 239 (`department = context.get("_department", "")`), **before** the `system_prompt, user_prompt = builder(...)` call at line 241.

Add the early return block from Part B above.

**Import:** `time` is already imported (line 14). `SubTaskResult` and `SubTaskType` are already imported (line 17). No new imports needed.

## Testing

### File: `tests/test_bf184_evaluate_social_bypass.py`

Write **8-10 tests** covering:

1. **Captain message auto-approved** — `_from_captain=True` → evaluate returns pass=True, score=1.0, bypass_reason="captain_message", zero LLM tokens used
2. **@mentioned auto-approved** — `_was_mentioned=True` → evaluate returns pass=True, score=1.0, bypass_reason="mentioned", zero LLM tokens used
3. **Both flags set** — `_from_captain=True` AND `_was_mentioned=True` → auto-approved, bypass_reason="captain_message" (captain takes precedence)
4. **Neither flag set** — `_from_captain=False`, `_was_mentioned=False` → normal LLM evaluation occurs (mock LLM, verify it's called)
5. **Flags missing from context** — context has no `_from_captain` or `_was_mentioned` keys → normal evaluation (no bypass)
6. **Flag propagation in cognitive_agent** — Mock observation with `params.author_id="captain"` → verify `_from_captain=True` is set in observation before chain execution
7. **Flag propagation for mention** — Mock observation with `params.was_mentioned=True` → verify `_was_mentioned=True` is set
8. **Flag propagation for crew message** — Mock observation with `params.author_id="some_agent_id"` → verify `_from_captain=False`
9. **No LLM call on bypass** — Verify `llm_client.complete()` is NOT called when bypass is active
10. **Logging verification** — Verify `BF-184` log message emitted on bypass

### Test patterns

- Use `unittest.mock.AsyncMock` for `llm_client`
- Create `EvaluateHandler` directly with mocked llm_client
- Build minimal `SubTaskSpec` with `sub_task_type=SubTaskType.EVALUATE`
- Context dict with `_from_captain`, `_was_mentioned`, `_callsign`, `_department`, `_agent_type`
- Prior results list with a mock Compose result (needed for non-bypass path)

## Verification

```bash
uv run python -m pytest tests/test_bf184_evaluate_social_bypass.py -v
uv run python -m pytest tests/ -k "evaluate" -v  # regression
uv run python -m pytest tests/ -k "sub_task" -v  # all sub-task tests
```

## Summary

- **2 source files** modified: `cognitive_agent.py` (3 lines), `evaluate.py` (~15 lines)
- **1 test file** created: `tests/test_bf184_evaluate_social_bypass.py`
- **8-10 tests**
- **0 new dependencies**
- **Token savings:** Eliminates evaluate LLM call for Captain/mentioned responses (~512 max_tokens saved per agent per Captain message)
