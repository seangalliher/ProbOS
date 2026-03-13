# HXI Chat Fix — "(No response)" Bug

## Problem

Chat always shows "(No response)" for ALL inputs — conversational ("hello") and functional ("read file").

## Root Cause

In `src/probos/api.py`, the `/api/chat` endpoint uses `getattr()` on a **dict**, which always returns the default empty string:

```python
dag_result = await runtime.process_natural_language(req.message, on_event=on_event)

if dag_result:
    response_text = getattr(dag_result, "response", "") or ""  # BUG: dag_result is a dict!
```

`runtime.process_natural_language()` returns a **dict** (e.g., `{"response": "Hello!", "dag": ..., "results": ...}`), NOT an object with attributes. `getattr(dict, "response", "")` returns `""` because Python dicts don't have attribute access — they use `dict["key"]` or `dict.get("key")`.

## Fix

**File:** `src/probos/api.py`

Replace all `getattr(dag_result, ...)` calls with `dag_result.get(...)`:

```python
if dag_result:
    response_text = dag_result.get("response", "") or ""
    
    dag_obj = dag_result.get("dag")
    dag_dict = None
    if dag_obj and hasattr(dag_obj, "source_text"):
        dag_dict = {
            "source_text": getattr(dag_obj, "source_text", ""),
            "reflect": getattr(dag_obj, "reflect", False),
        }
    
    results_dict = dag_result.get("results", {})
    
    # Also extract reflection if present
    reflection = dag_result.get("reflection", "")
    if reflection and not response_text:
        response_text = reflection
```

Note: The `dag` value inside the result dict IS a `TaskDAG` object (not a dict), so `getattr` is correct for accessing `dag_obj.source_text` and `dag_obj.nodes`. But the top-level `dag_result` is a plain dict.

Also handle the case where `process_natural_language` returns `None`:

```python
dag_result = await runtime.process_natural_language(req.message, on_event=on_event)

if not dag_result:
    return {"response": "(Processing failed)", "dag": None, "results": None}
```

## After Fix

1. Rebuild: no rebuild needed for Python change — restart `probos serve`
2. Test: type "hello" in the HXI chat — should see ProbOS's greeting
3. Test: type "what time is it" — should see DAG execute and result text
4. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
