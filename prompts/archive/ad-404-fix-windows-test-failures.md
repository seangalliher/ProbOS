# AD-404: Fix Windows-Specific Test Failures

## Context

19 tests fail on Windows with `FileNotFoundError: [WinError 2] The system cannot find the file specified`. All share the same root cause: `subprocess.run(["git/echo", ...])` can't resolve executables when `shell=False` (the default) because Windows doesn't search PATH the same way Linux does when running under `uv run pytest`.

These tests pass in isolation when run individually from a terminal with git on PATH, but fail in the full suite or under certain PATH configurations. They are test infrastructure bugs, not production code bugs.

## Root Cause Analysis

Four failure groups, all `FileNotFoundError` from `_winapi.CreateProcess`:

### Group 1: TestEscalationHook (4 tests in `test_builder_agent.py`)
**Problem:** Tests mock `_git_create_branch`, `_git_checkout_main`, and `_run_targeted_tests` but DON'T mock `_git_current_branch()` which is called at line ~2484 of `builder.py` early in `execute_approved_build()`. That function does `subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"])` which fails.
**Fix:** Add `patch("probos.cognitive.builder._git_current_branch", return_value="main")` to each test's mock context.

### Group 2: TestBranchLifecycle / TestDirtyWorkingTree / TestUntrackedFileCleanup / test_validation_errors_block_commit (5 tests in `test_builder_guardrails.py`)
**Problem:** These tests call `execute_approved_build()` with mocks for some git functions but miss `_git_current_branch()` (same as Group 1) or other subprocess calls.
**Fix:** Same — add the missing `_git_current_branch` mock. Scan each test for any other unmocked `_git_*` or `subprocess.run` calls and mock them.

### Group 3: TestShellCommandAgent (4 tests in `test_expansion_agents.py`)
**Problem:** `ShellCommandAgent.handle_intent()` runs `subprocess.run(["echo", "hello"], ...)` with `shell=False`. On Linux, `echo` is `/usr/bin/echo`. On Windows, `echo` is a CMD builtin — there is no `echo.exe`. The subprocess call fails.
**Fix:** Mock `subprocess.run` for these tests. The ShellCommandAgent tests should test the agent's logic, not whether `echo` exists as an executable. Use `patch("subprocess.run")` with a mock that returns a `CompletedProcess` with the expected output.

### Group 4: TestWorktreeManager (6 tests in `test_worktree_manager.py`)
**Problem:** The `git_repo` fixture creates a real git repo using `subprocess.run(["git", "init"], ...)`. When `git` is not on PATH (or PATH is incomplete under `uv run`), the fixture's `check=True` raises `FileNotFoundError`.
**Fix:** Add a `pytest.mark.skipif` guard that skips the entire test class if `git` is not available:

```python
import shutil

@pytest.fixture
def git_repo(tmp_path: Path) -> str:
    if shutil.which("git") is None:
        pytest.skip("git not found on PATH")
    # ... existing fixture code ...
```

Alternatively, skip at class level:
```python
@pytest.mark.skipif(shutil.which("git") is None, reason="git not found on PATH")
class TestWorktreeManager:
```

## Implementation

### File: `tests/test_builder_agent.py`

For ALL 4 tests in `TestEscalationHook`:

Add the missing mock. Each test already has a `with patch(...)` block. Add one more nested patch:

```python
with patch("probos.cognitive.builder._git_current_branch", return_value="main"):
```

**Example** — `test_hook_called_on_failure` should become:
```python
with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED tests/test_x.py::test_y", [])):
    with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
        with patch("probos.cognitive.builder._git_checkout_main"):
            with patch("probos.cognitive.builder._git_current_branch", return_value="main"):
                result = await execute_approved_build(...)
```

Apply the same pattern to all 4 tests. Read each test to see what's already mocked and only add what's missing.

### File: `tests/test_builder_guardrails.py`

For all 5 failing tests (`test_stale_branch_cleanup`, `test_failed_build_deletes_branch`, `test_dirty_working_tree_aborts_build`, `test_untracked_files_cleaned_on_failure`, `test_validation_errors_block_commit`):

1. Read each test carefully to find which `_git_*` functions are already mocked.
2. Add `patch("probos.cognitive.builder._git_current_branch", return_value="main")` where missing.
3. For any test that calls `execute_approved_build()`, make sure ALL `_git_*` functions that `execute_approved_build()` calls are mocked. The full list from `builder.py`:
   - `_git_current_branch(work_dir)`
   - `_git_create_branch(branch, work_dir)`
   - `_git_add_and_commit(message, work_dir, files)`
   - `_git_checkout_main(work_dir)`
4. If any test also runs into `_run_targeted_tests` or other subprocess calls, mock those too.

### File: `tests/test_expansion_agents.py`

For the 4 `TestShellCommandAgent` tests (`test_echo_hello`, `test_failing_command`) and the 2 integration tests (`test_nl_run_command`, `test_failing_command_via_runtime`):

Mock `subprocess.run` at the point where `ShellCommandAgent` calls it. Read the `ShellCommandAgent.handle_intent()` method to find the exact import path of the subprocess call.

For `test_echo_hello`:
```python
@pytest.mark.asyncio
async def test_echo_hello(self):
    agent = ShellCommandAgent()
    intent = IntentMessage(
        intent="run_command", params={"command": "echo hello"}
    )
    with patch("subprocess.run", return_value=subprocess.CompletedProcess(
        args=["echo", "hello"], returncode=0, stdout="hello\n", stderr=""
    )):
        result = await agent.handle_intent(intent)
    assert result is not None
    assert result.success
```

Find the correct module path for the `subprocess.run` patch — it should be patched where it's used (e.g., `probos.agents.expansion.subprocess.run` if that's where the import lives), not at `subprocess.run` globally.

For `test_failing_command`: Same pattern but with `returncode=1` and appropriate stderr.

For the integration tests (`test_nl_run_command`, `test_failing_command_via_runtime`): These go through the full runtime, so mock at the same subprocess level.

### File: `tests/test_worktree_manager.py`

Add a skip guard to the fixture:

```python
import shutil

@pytest.fixture
def git_repo(tmp_path: Path) -> str:
    """Create a minimal git repo for testing."""
    if shutil.which("git") is None:
        pytest.skip("git not available on PATH")
    repo = tmp_path / "repo"
    # ... rest unchanged ...
```

This is the correct fix because these tests legitimately need a real git repo — mocking `git worktree` commands would make the tests meaningless. Skipping when git isn't available is honest.

## Testing

Run each fixed group individually to verify:
```
uv run pytest tests/test_builder_agent.py::TestEscalationHook -v
uv run pytest tests/test_builder_guardrails.py -v
uv run pytest tests/test_expansion_agents.py -v
uv run pytest tests/test_worktree_manager.py -v
```

Then run the full suite:
```
uv run pytest tests/ --tb=short -q
```

Target: 0 failures, 0 errors. Some tests may be skipped if git is not on PATH — that's correct.

## What NOT to Change

- Do NOT modify production code. This AD only touches test files.
- Do NOT change `ShellCommandAgent.handle_intent()` to use `shell=True` — that's a security risk, production is fine.
- Do NOT modify the `WorktreeManager` implementation.
- Do NOT add `shell=True` to any subprocess calls in production code.

## Files Modified

| File | Change |
|------|--------|
| `tests/test_builder_agent.py` | Add missing `_git_current_branch` mock to 4 EscalationHook tests |
| `tests/test_builder_guardrails.py` | Add missing git function mocks to 5 failing tests |
| `tests/test_expansion_agents.py` | Mock `subprocess.run` in 4 ShellCommandAgent tests |
| `tests/test_worktree_manager.py` | Add `shutil.which("git")` skip guard to fixture |

## Commit Message

```
Fix 19 Windows-specific test failures with missing mocks and skip guards (AD-404)

Builder and guardrail tests missing _git_current_branch mock, expansion
agent tests calling shell builtins without shell=True, worktree tests
needing real git. Added subprocess mocks where tests should be
unit-testing logic, skip guards where tests legitimately need git.
```
