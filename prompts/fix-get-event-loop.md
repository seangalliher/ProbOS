# Build Prompt: Fix get_event_loop in Async Code (AD-364)

## Context

GPT-5.4 code review found 7 call sites in the experience layer that use
`asyncio.get_event_loop()` inside `async def` methods. ProbOS Standing Orders
(`config/standing_orders/ship.md` line 24) and Copilot Instructions
(`.github/copilot-instructions.md` line 31) both explicitly mandate:

> "Use `asyncio.get_running_loop()`, never `get_event_loop()`"

All 7 sites are inside `async def` methods where a running loop is guaranteed
to exist. `get_event_loop()` is deprecated behavior in Python 3.12+ and is
more fragile under Windows event loop policy differences.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

This is a mechanical find-and-replace. All 7 call sites use the same pattern:
`asyncio.get_event_loop().run_in_executor(...)` for non-blocking `input()` calls.

Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()` at each
location.

### File: `src/probos/experience/shell.py`

**Line 132** (inside `async def run`):
```python
# Before:
loop = asyncio.get_event_loop()
# After:
loop = asyncio.get_running_loop()
```

**Line 1049** (inside `async def _cmd_prune`):
```python
# Before:
response = await asyncio.get_event_loop().run_in_executor(
# After:
response = await asyncio.get_running_loop().run_in_executor(
```

**Line 1180** (inside `async def _user_escalation_callback`):
```python
# Before:
response = await asyncio.get_event_loop().run_in_executor(
# After:
response = await asyncio.get_running_loop().run_in_executor(
```

**Line 1207** (inside `async def _user_self_mod_approval`):
```python
# Before:
response = await asyncio.get_event_loop().run_in_executor(
# After:
response = await asyncio.get_running_loop().run_in_executor(
```

**Line 1234** (inside `async def _user_import_approval`):
```python
# Before:
response = await asyncio.get_event_loop().run_in_executor(
# After:
response = await asyncio.get_running_loop().run_in_executor(
```

**Line 1259** (inside `async def _user_dep_install_approval`):
```python
# Before:
response = await asyncio.get_event_loop().run_in_executor(
# After:
response = await asyncio.get_running_loop().run_in_executor(
```

### File: `src/probos/experience/renderer.py`

**Line 225** (inside `async def process_with_feedback`):
```python
# Before:
resp = await asyncio.get_event_loop().run_in_executor(
# After:
resp = await asyncio.get_running_loop().run_in_executor(
```

---

## Verification

After making the changes, confirm no occurrences of `get_event_loop` remain in
either file:

```bash
grep -n "get_event_loop" src/probos/experience/shell.py src/probos/experience/renderer.py
```

This should return no results.

Then run:
```bash
pytest tests/test_shell.py tests/test_renderer.py -x -q
```

---

## Constraints

- Modify ONLY `src/probos/experience/shell.py` and `src/probos/experience/renderer.py`
- This is a mechanical replacement — do NOT refactor surrounding code
- Do NOT change any logic, only the loop acquisition method
- Do NOT add new imports — `asyncio` is already imported in both files
- Do NOT create new test files — existing tests cover these paths
