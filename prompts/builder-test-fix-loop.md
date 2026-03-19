# AD-314: Builder Test-Fix Loop + Flaky Test Fixes

## Context

The Builder agent currently runs tests once after writing code. If tests fail, it reports failure but doesn't attempt to fix anything. The Captain has to manually intervene, interpret the errors, and restart the build. AD-314 adds a test-fix loop: after test failures, the Builder feeds the error output back to the LLM for a fix attempt, up to 2 retries.

Additionally, two pre-existing tests make real network calls to unreachable ports and fail intermittently. These need to be mocked properly.

## Scope

**Target files:**
- `src/probos/cognitive/builder.py` — test-fix loop in `execute_approved_build()`
- `tests/test_llm_client.py` — fix `test_unreachable_returns_false`
- `tests/test_per_tier_llm.py` — fix `test_all_tiers_unreachable_falls_back_to_mock`
- `tests/test_builder_agent.py` — new tests for test-fix loop

**Reference files:**
- `src/probos/cognitive/cognitive_agent.py` — CognitiveAgent base class, `decide()` and LLM call pattern
- `src/probos/cognitive/llm_client.py` — LLM client interface
- `.github/copilot-instructions.md` — Builder Agent section (lines 268-274)

**Do NOT change:**
- `src/probos/cognitive/architect.py`
- `src/probos/cognitive/decomposer.py`
- `src/probos/cognitive/prompt_builder.py`
- `src/probos/experience/shell.py`
- `src/probos/experience/panels.py`
- Any substrate or mesh layer files
- Do not add new files — all changes go in existing files
- Do not modify the git workflow (branch/commit logic)
- Do not modify `_parse_file_blocks()` or `_validate_python()`

---

## Step 1: Test-Fix Loop in execute_approved_build()

**File:** `src/probos/cognitive/builder.py`

Currently, step 5 in `execute_approved_build()` (approximately lines 482-500) runs pytest once and stores the result. Modify this to implement a retry loop:

### Design:

```
max_fix_attempts = 2  (configurable parameter on execute_approved_build)

for attempt in range(1 + max_fix_attempts):  # 1 initial + 2 retries
    run pytest
    if tests pass:
        break
    if attempt < max_fix_attempts:
        feed test output to LLM for fix
        apply fix (parse file blocks, apply MODIFY/CREATE)
        validate python
    else:
        # exhausted retries — report failure with all attempt history
```

### 1a: Add `max_fix_attempts` parameter

Add `max_fix_attempts: int = 2` parameter to the `execute_approved_build()` function signature (line 388).

### 1b: Add `fix_attempts` to BuildResult

Add a new field to the `BuildResult` dataclass:
```python
fix_attempts: int = 0  # number of test-fix iterations attempted
```

### 1c: Extract test runner to a helper

Extract the current test-running code (lines 483-500) into a standalone async function:

```python
async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pytest", "--tb=short", "-q",
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
        test_out = (stdout_b or b"").decode(errors="replace")
        test_err = (stderr_b or b"").decode(errors="replace")
        output = test_out + ("\n" + test_err if test_err else "")
        return proc.returncode == 0, output
    except asyncio.TimeoutError:
        return False, f"pytest timed out after {timeout}s"
```

### 1d: Build the fix prompt

Create a helper to build the fix prompt for the LLM:

```python
def _build_fix_prompt(
    spec_title: str,
    test_output: str,
    file_changes: list[dict],
    attempt: int,
) -> str:
    """Build a prompt asking the LLM to fix test failures."""
    # Include the files that were written/modified so the LLM knows what it produced
    file_listing = "\n".join(
        f"- {c['path']} ({c['mode']})" for c in file_changes
    )
    return (
        f"# Test Fix Required (attempt {attempt})\n\n"
        f"Build: {spec_title}\n\n"
        f"## Files Changed\n{file_listing}\n\n"
        f"## Test Failures\n```\n{test_output[-3000:]}\n```\n\n"
        "Fix the failing tests. Output ONLY the file changes needed to fix the "
        "failures. Use the same ===MODIFY: path=== or ===FILE: path=== format. "
        "Do NOT rewrite files that don't need changes. Keep fixes minimal — "
        "fix the bug, don't refactor."
    )
```

**Important:** Truncate test output to last 3000 chars to avoid blowing the context window. The most useful information (failure messages, assertion errors) is at the end.

### 1e: Implement the retry loop

Replace the current step 5 (test running, approximately lines 482-500) with the retry loop. The loop should:

1. Run tests using `_run_tests()`
2. If tests pass, break — success
3. If tests fail and we have retries left:
   a. Log: `"BuilderAgent: test failures on attempt %d/%d, requesting fix from LLM"`
   b. Build fix prompt using `_build_fix_prompt()`
   c. Call the LLM using the agent's `decide()` method (or directly via `self._llm_call()` if available — check how `CognitiveAgent.decide()` makes LLM calls and replicate the minimal path)
   d. Parse the LLM's response for file changes using `self._parse_file_blocks()`
   e. Apply the changes (same MODIFY/CREATE logic as the initial write, reuse the existing code)
   f. Run `_validate_python()` on modified .py files
   g. Increment `result.fix_attempts`
4. If tests still fail after all retries, set `result.tests_passed = False` with the final test output

**Key design decisions:**
- The fix LLM call should use the same tier as the initial build (deep)
- Each fix attempt's test output replaces the previous one in `result.test_result`
- Track ALL files written/modified across all attempts in the result
- If a fix attempt's `_parse_file_blocks()` returns empty, skip that attempt and continue to the next
- The fix prompt does NOT include the full reference files — just the test failures and the list of files changed. The LLM already produced the code; it just needs to know what went wrong.

### 1f: Wire LLM call for fix attempts

The Builder's LLM interaction currently goes through `CognitiveAgent.decide()` which calls the LLM with `self.instructions` as the system prompt and the user message from `_build_user_message()`.

For fix attempts, we need a simpler LLM call. Check how `CognitiveAgent` or the builder accesses the LLM client. The pattern should be:

```python
# Access the LLM client — check how decide() does it
# The fix call uses the same instructions (system prompt) but a different user message
fix_prompt = _build_fix_prompt(spec.title, test_output, file_changes, attempt)
# Make the LLM call however the agent normally does
fix_response = await self._llm_call(fix_prompt)  # or however the agent calls the LLM
fix_changes = self._parse_file_blocks(fix_response)
```

Look at `CognitiveAgent.decide()` to find the actual method name for making LLM calls. The fix call should use the same system prompt (Builder instructions) but with a different user message (the fix prompt).

---

## Step 2: Fix Flaky Network Tests

### 2a: Fix test_unreachable_returns_false

**File:** `tests/test_llm_client.py`

The test at approximately line 520 creates a client pointing to `http://localhost:1` and calls `_check_endpoint()` expecting `False`. This makes a real network call. Fix it by mocking the httpx client to raise a `ConnectError`:

```python
@pytest.mark.asyncio
async def test_unreachable_returns_false(self):
    cfg = _make_config(
        llm_base_url_fast="http://localhost:1",
        llm_api_format_fast="ollama",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        mock_client = client._clients[client._client_key("fast")]
        with patch.object(
            mock_client, "post", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await client._check_endpoint("fast")
            assert result is False
    finally:
        await client.close()
```

Check the existing test `test_ollama_format_probes_api_chat` in the same class for the exact mock pattern to follow. Import `httpx` at the top of the file if not already there.

### 2b: Fix test_all_tiers_unreachable_falls_back_to_mock

**File:** `tests/test_per_tier_llm.py`

The test at approximately line 280 creates a real config pointing to `http://localhost:1` and calls `_create_llm_client()`. Fix it by mocking the `check_connectivity()` method to return all tiers unreachable:

```python
@pytest.mark.asyncio
async def test_all_tiers_unreachable_falls_back_to_mock(self):
    """All tiers unreachable -> _create_llm_client returns MockLLMClient."""
    from io import StringIO
    from rich.console import Console
    from probos.config import SystemConfig
    from probos.__main__ import _create_llm_client

    config = SystemConfig(
        cognitive=CognitiveConfig(
            llm_base_url="http://localhost:1",
        )
    )
    console = Console(file=StringIO())

    with patch(
        "probos.__main__.OpenAICompatibleClient"
    ) as MockClientClass:
        mock_instance = AsyncMock()
        mock_instance.check_connectivity = AsyncMock(
            return_value={"standard": False, "fast": False, "deep": False}
        )
        mock_instance.close = AsyncMock()
        MockClientClass.return_value = mock_instance

        client = await _create_llm_client(config, console)
        assert isinstance(client, MockLLMClient)
```

Check the existing imports and mock patterns in the file. Make sure `AsyncMock` and `patch` are imported from `unittest.mock`.

---

## Step 3: Tests for Test-Fix Loop

**File:** `tests/test_builder_agent.py`

Add a new test class `TestTestFixLoop` with the following tests:

### Test 1: test_fix_loop_passes_on_first_try
Mock `_run_tests` to return `(True, "1 passed")` on the first call. Verify `result.tests_passed is True` and `result.fix_attempts == 0`.

### Test 2: test_fix_loop_fixes_on_second_try
Mock `_run_tests` to return `(False, "1 failed")` on first call, `(True, "1 passed")` on second call. Mock the LLM fix call to return a valid MODIFY block. Verify `result.tests_passed is True` and `result.fix_attempts == 1`.

### Test 3: test_fix_loop_exhausts_retries
Mock `_run_tests` to always return `(False, "1 failed")`. Mock the LLM fix calls. Verify `result.tests_passed is False` and `result.fix_attempts == 2` (max retries).

### Test 4: test_fix_loop_skips_empty_llm_response
Mock `_run_tests` to fail, then mock LLM fix to return empty string (no file blocks). Verify the loop handles it gracefully without crashing — it should skip the fix and try again or report failure.

### Test 5: test_fix_prompt_truncates_long_output
Call `_build_fix_prompt()` with test output longer than 3000 chars. Verify the prompt contains only the last 3000 chars of test output.

### Test 6: test_run_tests_helper
Test the `_run_tests()` function directly by mocking `asyncio.create_subprocess_exec`. Verify it returns `(True, output)` on success and `(False, output)` on failure.

### Test 7: test_fix_loop_disabled_with_zero_retries
Call `execute_approved_build()` with `max_fix_attempts=0`. Mock tests to fail. Verify no LLM fix calls are made and `result.fix_attempts == 0`.

**Total: 7 new tests minimum.**

---

## Step 4: Update copilot-instructions.md

**File:** `.github/copilot-instructions.md`

Update the Builder Agent section (approximately line 274) from:
```
- Single test pass — AD-314 will add retry loop
```
To:
```
- Test-fix loop (AD-314): runs pytest after writes, feeds failures back to LLM for up to 2 fix attempts. `_run_tests()` helper, `_build_fix_prompt()` for fix context. `max_fix_attempts` parameter on `execute_approved_build()`
```

---

## Step 5: Update Tracking Files

After all code changes and tests pass:

### PROGRESS.md (line 3)
Update the status line with the new test count: `Phase 32j complete — Phase 32 in progress (NNNN/NNNN tests + 21 Vitest + NN skipped)`

### DECISIONS.md
Append a new section at the end:

```
## Phase 32j: Builder Test-Fix Loop (AD-314)

| AD | Decision |
|----|----------|
| AD-314 | Builder Test-Fix Loop — `execute_approved_build()` now runs pytest in a retry loop: initial pass + up to `max_fix_attempts` (default 2) LLM-driven fix iterations. `_run_tests()` async helper extracted. `_build_fix_prompt()` feeds truncated (3000-char) test failure output back to the LLM with a minimal fix-only prompt. Fix responses parsed with existing `_parse_file_blocks()` and applied with existing MODIFY/CREATE logic. `fix_attempts` count added to `BuildResult`. Two flaky network tests fixed: `test_unreachable_returns_false` and `test_all_tiers_unreachable_falls_back_to_mock` now use mocked connections instead of real network calls. |

**Status:** Complete — N new Python tests (7 builder + 2 fixed), NNNN Python + 21 Vitest total
```

### progress-era-4-evolution.md
Append a new section at the end:

```
## Phase 32j: Builder Test-Fix Loop (AD-314)

**Decision:** AD-314 — Builder retries test failures via LLM-driven fix loop (2 attempts max). Extracted `_run_tests()` helper, `_build_fix_prompt()` for fix context. Two flaky network tests fixed with proper mocks.

**Status:** Phase 32j complete — NNNN Python + 21 Vitest
```

---

## Verification Checklist

Before committing, verify:

1. [ ] `_run_tests()` async helper extracted and working
2. [ ] `_build_fix_prompt()` truncates test output to 3000 chars
3. [ ] `execute_approved_build()` has `max_fix_attempts` parameter (default 2)
4. [ ] Retry loop: initial test → fail → LLM fix → apply changes → retest (up to max_fix_attempts)
5. [ ] `BuildResult.fix_attempts` tracks iteration count
6. [ ] `test_unreachable_returns_false` uses mocked network, no real connection
7. [ ] `test_all_tiers_unreachable_falls_back_to_mock` uses mocked network, no real connection
8. [ ] All 7 new builder tests pass
9. [ ] Previously flaky tests now pass reliably
10. [ ] Full suite passes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
11. [ ] PROGRESS.md, DECISIONS.md, progress-era-4-evolution.md updated

## Anti-Scope (Do NOT Build)

- Do NOT modify `_parse_file_blocks()` or `_validate_python()` — reuse them as-is
- Do NOT modify the git branch/commit flow
- Do NOT add new slash commands or API endpoints
- Do NOT modify the Architect agent
- Do NOT add parallel test execution or test filtering
- Do NOT add a "test selection" feature that only runs relevant tests — always run the full suite
- Do NOT modify the Decomposer or prompt_builder.py
