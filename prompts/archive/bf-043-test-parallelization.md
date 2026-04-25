# BF-043: Test Suite Performance — Parallel Execution & Slow Test Isolation

## Problem

The full test suite (~3581 pytest + 118 vitest) runs sequentially on a single core despite the development machine having 16 CPU cores. Each build cycle waits for all tests to complete serially, making the builder pipeline slower than necessary. Additionally, some tests use real `asyncio.sleep()` calls (2-3.5s each) that add wall-clock time regardless of parallelization.

## Fix Specification

### Fix 1: Add pytest-xdist for parallel test execution

**File:** `pyproject.toml`

Add `pytest-xdist` to both dependency locations:

At line ~38 (inside `[project.optional-dependencies]` dev list), add after `"pytest-cov>=6.0"`:
```toml
    "pytest-xdist>=3.5",
```

At line ~53 (inside `[dependency-groups]` dev list), add after `"pytest-cov>=6.0"`:
```toml
    "pytest-xdist>=3.5",
```

After adding, run:
```bash
uv sync --group dev
```

### Fix 2: Add pytest-timeout for hanging test protection

**File:** `pyproject.toml`

Add `pytest-timeout` to both dependency locations (same two places as Fix 1):
```toml
    "pytest-timeout>=2.3",
```

After adding, run:
```bash
uv sync --group dev
```

### Fix 3: Configure pytest defaults for parallelism and timeout

**File:** `pyproject.toml`

Update the `[tool.pytest.ini_options]` section (lines 62-67). Replace:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "live_llm: tests requiring live LLM backends (Ollama/Copilot proxy)",
]
```

With:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
timeout = 30
markers = [
    "live_llm: tests requiring live LLM backends (Ollama/Copilot proxy)",
    "slow: tests with real wall-clock waits (deselect with -m 'not slow')",
]
```

**Note:** Do NOT add `-n auto` as a default `addopts` — leave parallel execution as an explicit CLI flag so that the builder can choose when to use it. Some debugging scenarios need sequential execution.

### Fix 4: Mark slow test files

**File:** `tests/test_task_scheduler.py`

Add a module-level pytestmark at the top of the file, after the imports:

```python
pytestmark = pytest.mark.slow
```

This marks ALL tests in the file as slow. The file contains 7 real `asyncio.sleep()` calls ranging from 2.0s to 3.5s — roughly 17-20 seconds of pure wall-clock waiting.

**File:** `tests/test_dreaming.py`

Add the same module-level pytestmark after imports:

```python
pytestmark = pytest.mark.slow
```

This file contains 10 real `asyncio.sleep()` calls ranging from 0.3s to 1.5s.

Make sure `import pytest` is present in both files (it almost certainly already is).

### Fix 5: Verify parallel execution works

After all changes, run the full suite in parallel to verify no test isolation issues:

```bash
uv run pytest -n auto
```

If any tests fail ONLY in parallel (pass when run sequentially with `uv run pytest`), they have shared state issues. Fix by ensuring test isolation — likely candidates are tests that write to the same temp directory or use fixed port numbers. If found, mark them with `@pytest.mark.no_parallel` — but this is unlikely given all fixtures are function-scoped.

Also verify that the targeted fast run works:

```bash
uv run pytest -n auto -m "not slow"
```

This skips `test_task_scheduler.py` and `test_dreaming.py` for rapid iteration.

## Usage After Fix

| Command | When to Use |
|---------|-------------|
| `uv run pytest -n auto` | Full regression — parallel on all 16 cores |
| `uv run pytest -n auto -m "not slow"` | Fast iteration — skip wall-clock sleepers |
| `uv run pytest tests/test_foo.py` | Targeted single-file run (sequential) |
| `uv run pytest` | Full regression — sequential (debugging) |

Expected speedup with `-n auto` on 16 cores: **4-8x** (not full 16x due to test startup overhead and I/O contention, but substantial).

## Files to Modify

| File | Changes |
|------|---------|
| `pyproject.toml` | Add pytest-xdist + pytest-timeout deps (2 locations each), update pytest.ini_options |
| `tests/test_task_scheduler.py` | Add `pytestmark = pytest.mark.slow` |
| `tests/test_dreaming.py` | Add `pytestmark = pytest.mark.slow` |

## Testing

After making all changes:

1. `uv sync --group dev` — install new dependencies
2. `uv run pytest -n auto` — full parallel run, verify all tests pass
3. `uv run pytest -n auto -m "not slow"` — verify slow tests are skipped
4. `uv run pytest -n auto -m "slow"` — verify only slow tests run
5. `cd ui && npx vitest run` — verify vitest unaffected

## Acceptance Criteria

- [ ] `pytest-xdist>=3.5` in both dependency locations
- [ ] `pytest-timeout>=2.3` in both dependency locations
- [ ] `timeout = 30` in pytest.ini_options
- [ ] `slow` marker defined in pytest.ini_options
- [ ] `test_task_scheduler.py` marked with `pytestmark = pytest.mark.slow`
- [ ] `test_dreaming.py` marked with `pytestmark = pytest.mark.slow`
- [ ] `uv run pytest -n auto` — all tests pass in parallel
- [ ] `uv run pytest -n auto -m "not slow"` — skips slow tests, rest pass
- [ ] No test isolation failures in parallel mode
