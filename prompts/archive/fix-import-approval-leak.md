# Build Prompt: Fix API Import Approval Callback Leak (AD-366)

## Context

GPT-5.4 code review found that the API self-mod path in `api.py` sets
`_import_approval_fn` to auto-approve but never restores it. After the first
HXI-triggered self-mod, all future import approvals (including interactive
shell use) are silently auto-approved. This weakens the safety boundary.

The `_user_approval_fn` is correctly saved and restored in the `finally`
block, but `_import_approval_fn` is not.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `src/probos/api.py`

**Change 1:** Save the original `_import_approval_fn` before overwriting it
(around line 537). The pattern should match how `_user_approval_fn` is
already handled.

Before (lines 519, 536-541):
```python
original_approval_fn = None
try:
    # ...
    if rt.self_mod_pipeline:
        rt.self_mod_pipeline._import_approval_fn = _auto_approve_imports
        original_approval_fn = rt.self_mod_pipeline._user_approval_fn
        rt.self_mod_pipeline._user_approval_fn = None
```

After:
```python
original_approval_fn = None
original_import_approval_fn = None
try:
    # ...
    if rt.self_mod_pipeline:
        original_import_approval_fn = rt.self_mod_pipeline._import_approval_fn
        rt.self_mod_pipeline._import_approval_fn = _auto_approve_imports
        original_approval_fn = rt.self_mod_pipeline._user_approval_fn
        rt.self_mod_pipeline._user_approval_fn = None
```

**Change 2:** Restore `_import_approval_fn` in the `finally` block (around
line 712-715).

Before:
```python
finally:
    # Restore the console approval callback for interactive shell use
    if rt.self_mod_pipeline and original_approval_fn is not None:
        rt.self_mod_pipeline._user_approval_fn = original_approval_fn
```

After:
```python
finally:
    # Restore callbacks for interactive shell use
    if rt.self_mod_pipeline:
        if original_approval_fn is not None:
            rt.self_mod_pipeline._user_approval_fn = original_approval_fn
        if original_import_approval_fn is not None:
            rt.self_mod_pipeline._import_approval_fn = original_import_approval_fn
```

---

## Tests

### File: `tests/test_api.py`

Add a test verifying both callbacks are restored. Find the existing self-mod
test section and add:

```python
@pytest.mark.asyncio
async def test_self_mod_restores_import_approval_callback():
    """Import approval callback must be restored after API self-mod (AD-366)."""
    from unittest.mock import MagicMock, AsyncMock, patch

    # Create a mock runtime with self_mod_pipeline
    mock_pipeline = MagicMock()
    original_import_fn = MagicMock(name="original_import_fn")
    original_user_fn = MagicMock(name="original_user_fn")
    mock_pipeline._import_approval_fn = original_import_fn
    mock_pipeline._user_approval_fn = original_user_fn
    mock_pipeline.design_and_deploy = AsyncMock(return_value=MagicMock(
        status="active",
        intent_name="test",
        agent_type="test",
        class_name="TestAgent",
    ))

    mock_rt = MagicMock()
    mock_rt.self_mod_pipeline = mock_pipeline
    mock_rt._emit_event = MagicMock()
    mock_rt._last_execution = None

    # Run the self-mod background task
    from probos.api import _run_self_mod_pipeline
    req = MagicMock()
    req.intent_name = "test_intent"
    req.intent_description = "test"
    await _run_self_mod_pipeline(req, mock_rt)

    # Both callbacks should be restored
    assert mock_pipeline._user_approval_fn == original_user_fn
    assert mock_pipeline._import_approval_fn == original_import_fn
```

Note: If `_run_self_mod_pipeline` is not directly importable (it might be a
nested function), you may need to adjust the test approach. Check how the
function is defined in `api.py` — if it's a nested `async def` inside
`create_api()`, the test needs to exercise it through the API endpoint or
extract the function. In that case, test via the FastAPI test client or
simply verify the pattern is correct by inspecting the finally block.

If a direct unit test is not feasible due to the nested function structure,
add a simpler test:

```python
def test_self_mod_import_approval_finally_block():
    """Verify api.py finally block restores _import_approval_fn (AD-366)."""
    import ast
    import inspect
    source = Path("src/probos/api.py").read_text()
    tree = ast.parse(source)
    # Find the finally block and check it references _import_approval_fn
    assert "original_import_approval_fn" in source
    assert source.count("_import_approval_fn") >= 3  # set, save, restore
```

---

## Constraints

- Modify ONLY `src/probos/api.py` and the test file
- Follow the existing save/restore pattern for `_user_approval_fn`
- Do NOT change the `_auto_approve_imports` function itself
- Do NOT modify `self_mod.py` or any other file
- Run `pytest tests/test_api.py -x -q` to verify
