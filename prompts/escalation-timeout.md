# AD-325: Escalation Tier 3 User Callback Timeout

## Context

The `EscalationManager._tier3_user()` method awaits the user callback with no timeout. If the user callback never returns (e.g., the HXI WebSocket disconnects mid-escalation, or the callback implementation has a bug), the entire escalation cascade — and the DAGExecutor that called it — hangs forever. This was identified in a code review as a P0/Critical issue.

The fix is simple: wrap the `await self._user_callback(description, ctx)` call in `asyncio.wait_for()` with a configurable timeout.

## Scope

**Target files:**
- `src/probos/consensus/escalation.py` — add timeout to `_tier3_user()`, add `user_timeout` constructor parameter
- `tests/test_escalation.py` — new tests for timeout behavior

**Do NOT change:**
- `src/probos/api.py`
- `src/probos/cognitive/decomposer.py`
- `src/probos/cognitive/builder.py`
- `src/probos/cognitive/architect.py`
- `src/probos/runtime.py`
- Do not add new files — all changes go in existing files
- Do not modify the Tier 1 or Tier 2 escalation logic
- Do not modify the existing `escalate()` flow or the `_reexecute_without_consensus()` method
- Do not modify the DAGExecutor

---

## Step 1: Add `user_timeout` Parameter

**File:** `src/probos/consensus/escalation.py`

### 1a: Add parameter to `__init__()` (line 57-72)

Add a `user_timeout: float = 120.0` parameter to the `__init__()` signature, after `surge_fn`:

```python
def __init__(
    self,
    runtime: Any,
    llm_client: Any,
    max_retries: int = 2,
    user_callback: Callable | None = None,
    pre_user_hook: Callable | None = None,
    surge_fn: Callable | None = None,
    user_timeout: float = 120.0,  # Tier 3 callback timeout in seconds
) -> None:
```

Store it: `self._user_timeout = user_timeout`

**Design decision:** 120 seconds is generous — a human should respond within 2 minutes. The DAG-level timeout (typically 30s) will usually fire first, but this is a safety net for cases where the DAG timeout is very large or has been extended by user-wait exclusions.

---

## Step 2: Wrap User Callback with Timeout

**File:** `src/probos/consensus/escalation.py`

### 2a: Modify `_tier3_user()` (lines 340-342)

Replace the bare await at line 342:

```python
# BEFORE (line 340-343):
try:
    t_user_start = time.monotonic()
    user_decision = await self._user_callback(description, ctx)
    self.user_wait_seconds += time.monotonic() - t_user_start
```

With a timeout-wrapped version:

```python
# AFTER:
try:
    t_user_start = time.monotonic()
    user_decision = await asyncio.wait_for(
        self._user_callback(description, ctx),
        timeout=self._user_timeout,
    )
    self.user_wait_seconds += time.monotonic() - t_user_start
except asyncio.TimeoutError:
    elapsed = time.monotonic() - t_user_start
    self.user_wait_seconds += elapsed
    logger.warning(
        "Tier 3 user callback timed out after %.1fs", elapsed,
    )
    return EscalationResult(
        tier=EscalationTier.USER,
        resolved=False,
        original_error=error,
        user_approved=None,
        reason=f"User callback timed out after {self._user_timeout:.0f}s",
    )
```

**Important details:**
- The `asyncio.TimeoutError` catch must come BEFORE the existing `except Exception` block (line 344). Place the `TimeoutError` handler between the `try:` and the existing `except Exception`.
- Still accumulate `user_wait_seconds` on timeout — the time was genuinely spent waiting for the user, even though they didn't respond.
- Use `resolved=False` and `user_approved=None` — the user didn't reject, they just didn't respond.
- Add `import asyncio` at the top of the file if not already there.

### 2b: Verify `asyncio` import

Check if `asyncio` is already imported at the top of `escalation.py`. If not, add `import asyncio` to the imports section (around line 10).

---

## Step 3: Tests

**File:** `tests/test_escalation.py`

Add a new test class `TestTier3Timeout` at the end of the file (after the existing `TestDAGTimeoutUserWait` class). Follow existing patterns — use `_make_mock_runtime()`, `_make_node()`, `EscalationManager`.

### Test 1: test_user_callback_timeout_returns_unresolved

Mock a user callback that never returns (use `asyncio.sleep(999)` or `asyncio.Future()` that's never set). Set `user_timeout=0.5` (short for testing). Verify:
- `result.resolved is False`
- `result.tier == EscalationTier.USER`
- `result.user_approved is None`
- `"timed out"` in `result.reason`

```python
@pytest.mark.asyncio
async def test_user_callback_timeout_returns_unresolved(self):
    """User callback hangs forever — should timeout and return unresolved."""
    async def hanging_callback(desc, ctx):
        await asyncio.sleep(999)  # never returns

    runtime = _make_mock_runtime()
    mgr = EscalationManager(
        runtime=runtime,
        llm_client=None,
        max_retries=0,  # skip tier 1
        user_callback=hanging_callback,
        user_timeout=0.5,
    )

    node = _make_node()
    result = await mgr.escalate(node, "test error", {})

    assert result.tier == EscalationTier.USER
    assert result.resolved is False
    assert result.user_approved is None
    assert "timed out" in result.reason
```

### Test 2: test_user_callback_timeout_accumulates_wait_seconds

Same as test 1, but also verify that `mgr.user_wait_seconds` is approximately equal to the timeout value (within 0.5s tolerance).

```python
@pytest.mark.asyncio
async def test_user_callback_timeout_accumulates_wait_seconds(self):
    """Timed-out callback still accumulates user_wait_seconds."""
    async def hanging_callback(desc, ctx):
        await asyncio.sleep(999)

    runtime = _make_mock_runtime()
    mgr = EscalationManager(
        runtime=runtime,
        llm_client=None,
        max_retries=0,
        user_callback=hanging_callback,
        user_timeout=0.5,
    )

    node = _make_node()
    await mgr.escalate(node, "test error", {})

    # Should have accumulated ~0.5s of user-wait time
    assert mgr.user_wait_seconds >= 0.4
    assert mgr.user_wait_seconds < 2.0
```

### Test 3: test_user_callback_responds_before_timeout

Verify normal behavior is unchanged — callback responds in 0.1s, timeout is 2.0s. Should return the user's decision normally.

```python
@pytest.mark.asyncio
async def test_user_callback_responds_before_timeout(self):
    """User responds before timeout — normal behavior preserved."""
    async def quick_callback(desc, ctx):
        await asyncio.sleep(0.05)
        return True

    runtime = _make_mock_runtime(
        submit_intent_side_effect=_success_intent_results,
    )
    mgr = EscalationManager(
        runtime=runtime,
        llm_client=None,
        max_retries=0,
        user_callback=quick_callback,
        user_timeout=2.0,
    )

    node = _make_node()
    result = await mgr.escalate(node, "test error", {})

    assert result.tier == EscalationTier.USER
    assert result.resolved is True
    assert result.user_approved is True
```

### Test 4: test_default_user_timeout_is_120

Verify the default timeout value without passing the parameter:

```python
def test_default_user_timeout_is_120(self):
    """Default user_timeout is 120 seconds."""
    runtime = _make_mock_runtime()
    mgr = EscalationManager(
        runtime=runtime,
        llm_client=None,
        max_retries=1,
    )
    assert mgr._user_timeout == 120.0
```

### Test 5: test_custom_user_timeout

Verify a custom timeout is respected:

```python
def test_custom_user_timeout(self):
    """Custom user_timeout is stored correctly."""
    runtime = _make_mock_runtime()
    mgr = EscalationManager(
        runtime=runtime,
        llm_client=None,
        max_retries=1,
        user_timeout=30.0,
    )
    assert mgr._user_timeout == 30.0
```

**Total: 5 new tests.**

---

## Step 4: Update copilot-instructions.md

**File:** `.github/copilot-instructions.md`

Find the Escalation section (search for "3-tier" or "Tier 3" or "EscalationManager"). If there is a mention of escalation behavior, add a note about the timeout. If there is no existing escalation section, no changes needed here.

---

## Step 5: Update Tracking Files

After all code changes and tests pass:

### PROGRESS.md (line 3)
Update the status line with the new test count: `Phase 32k complete — Phase 32 in progress (NNNN/NNNN tests + 21 Vitest + NN skipped)`

### DECISIONS.md
Append a new section at the end:

```
## Phase 32k: Escalation Tier 3 Timeout (AD-325)

| AD | Decision |
|----|----------|
| AD-325 | Escalation Tier 3 Timeout — `_tier3_user()` now wraps the `user_callback` in `asyncio.wait_for()` with a configurable `user_timeout` (default 120s). On timeout, returns `EscalationResult(resolved=False, user_approved=None)` with descriptive reason. User-wait seconds still accumulated on timeout for accurate DAG deadline accounting. Prevents hung escalation cascades when user callback never returns. |

**Status:** Complete — N new Python tests, NNNN Python + 21 Vitest total
```

### progress-era-4-evolution.md
Append a new section at the end:

```
## Phase 32k: Escalation Tier 3 Timeout (AD-325)

**Decision:** AD-325 — Tier 3 `user_callback` wrapped in `asyncio.wait_for(timeout=user_timeout)`. Default 120s. Returns unresolved on timeout. User-wait seconds accumulated for DAG deadline accounting.

**Status:** Phase 32k complete — NNNN Python + 21 Vitest
```

---

## Verification Checklist

Before committing, verify:

1. [ ] `EscalationManager.__init__()` accepts `user_timeout: float = 120.0`
2. [ ] `_tier3_user()` wraps `user_callback` in `asyncio.wait_for()`
3. [ ] `asyncio.TimeoutError` is caught BEFORE the existing `except Exception` block
4. [ ] On timeout, `user_wait_seconds` is still accumulated
5. [ ] On timeout, returns `resolved=False`, `user_approved=None`, descriptive reason
6. [ ] `asyncio` is imported at the top of `escalation.py`
7. [ ] All 5 new tests pass
8. [ ] Existing escalation tests still pass (no regressions)
9. [ ] Full suite passes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
10. [ ] PROGRESS.md, DECISIONS.md, progress-era-4-evolution.md updated

## Anti-Scope (Do NOT Build)

- Do NOT modify the `escalate()` method logic (Tier 1 → 2 → 3 flow)
- Do NOT add timeout to Tier 1 or Tier 2 (those have their own timeout mechanisms via `submit_intent(timeout=10.0)`)
- Do NOT modify the DAGExecutor
- Do NOT add task registry or task lifecycle changes (that's AD-326)
- Do NOT modify `_reexecute_without_consensus()`
- Do NOT modify api.py, runtime.py, builder.py, or architect.py
- Do NOT add a `set_user_timeout()` setter — just the constructor parameter is enough
