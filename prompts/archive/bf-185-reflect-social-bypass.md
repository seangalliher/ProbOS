# BF-185: Reflect Step Independently Suppresses Captain/@Mention Responses

**Type:** Bug Fix
**Priority:** High
**Relates to:** BF-184 (evaluate bypass), AD-632e (reflect handler), BF-157 (@mention bypass)
**Issue:** #TBD

## Problem

BF-184 fixed the Evaluate step auto-approving Captain/@mention messages. However, the Reflect handler makes an **independent** LLM self-critique call that can return `[NO_RESPONSE]`, suppressing the response even after Evaluate approved it. Result: only 2 of 14 crew responded to the Captain's welcome message.

Two suppression paths in reflect:
1. `_should_suppress()` short-circuit (line 263) — checks evaluate's recommendation. BF-184 fixed this (evaluate now returns `approve`). ✅
2. The reflect LLM call itself returns `[NO_RESPONSE]` as output (line 364 check) — the LLM independently decides to suppress. ❌ **This is the remaining bug.**

## Design

Same pattern as BF-184: add social obligation bypass **before** the LLM call.

When `_from_captain` or `_was_mentioned` is True in context:
- Skip the LLM self-critique call entirely
- Return the compose output unchanged (approved as-is)
- Log the bypass with `BF-185` prefix
- Save LLM tokens (up to 2048 max_tokens per agent)

## Engineering Principles Compliance

- **Single Responsibility:** One early-exit check added to `ReflectHandler.__call__()`.
- **DRY:** Reuses same `_from_captain` / `_was_mentioned` flags from BF-184 (already in context).
- **Fail Fast:** Missing flags default to `False` — no bypass.
- **BF-184 precedent:** Identical pattern to evaluate bypass. Consistent approach across both quality gates.

## Implementation

### File: `src/probos/cognitive/sub_tasks/reflect.py`

**Location:** Inside `ReflectHandler.__call__()`, after the suppress short-circuit block (after line 277), **before** the mode dispatch (before line 280).

Add:
```python
# BF-185: Captain messages and @mentions bypass self-critique.
# Social obligation outranks self-critique — the Captain expects a response.
if context.get("_from_captain") or context.get("_was_mentioned"):
    compose_output = _get_compose_output(prior_results)
    reason = "captain_message" if context.get("_from_captain") else "mentioned"
    logger.info(
        "BF-185: Reflect auto-approved for %s (social obligation: %s)",
        context.get("_agent_type", "unknown"),
        reason,
    )
    return SubTaskResult(
        sub_task_type=SubTaskType.REFLECT,
        name=spec.name,
        result={
            "output": compose_output,
            "revised": False,
            "suppressed": False,
            "bypass_reason": reason,
        },
        tokens_used=0,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=True,
        tier_used="",
    )
```

**No other files need changes.** The `_from_captain` and `_was_mentioned` flags are already propagated into the chain context by BF-184's changes in `cognitive_agent.py`.

## Testing

### File: `tests/test_bf185_reflect_social_bypass.py`

Write **8 tests** covering:

1. **Captain message auto-approved** — `_from_captain=True` → reflect returns compose output unchanged, bypass_reason="captain_message", 0 LLM tokens
2. **@mentioned auto-approved** — `_was_mentioned=True` → reflect returns compose output unchanged, bypass_reason="mentioned", 0 LLM tokens
3. **Both flags set** — `_from_captain=True` AND `_was_mentioned=True` → auto-approved, bypass_reason="captain_message" (captain precedence)
4. **Neither flag set** — normal LLM self-critique occurs (mock LLM, verify called)
5. **Flags missing from context** — no `_from_captain` or `_was_mentioned` keys → normal path
6. **No LLM call on bypass** — verify `llm_client.complete()` is NOT called when bypass active
7. **Compose output preserved** — verify the exact compose output is returned unchanged on bypass (no revision)
8. **Logging verification** — verify `BF-185` log message emitted on bypass

### Test patterns

- Same patterns as `test_bf184_evaluate_social_bypass.py`
- Use `unittest.mock.AsyncMock` for `llm_client`
- Create `ReflectHandler` directly with mocked llm_client
- Build prior_results with a mock Compose result containing known output text
- Context dict with `_from_captain`, `_was_mentioned`, `_callsign`, `_department`, `_agent_type`

## Verification

```bash
uv run python -m pytest tests/test_bf185_reflect_social_bypass.py -v
uv run python -m pytest tests/test_bf184_evaluate_social_bypass.py -v  # regression
uv run python -m pytest tests/ -k "sub_task or reflect or evaluate" -v  # all related
```

## Summary

- **1 source file** modified: `reflect.py` (~15 lines)
- **1 test file** created: `tests/test_bf185_reflect_social_bypass.py`
- **8 tests**
- **0 new dependencies**
- **Token savings:** Eliminates reflect LLM call for Captain/mentioned responses (~2048 max_tokens saved per agent per Captain message)
- Combined with BF-184: saves both evaluate + reflect LLM calls = ~2560 tokens per agent per obligated response
