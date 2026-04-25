# AD-269: Fix Conversational Responses Showing Build Agent Button

## Problem

Saying "Hello" in the HXI chat shows a "Build Agent" button alongside the greeting response. Conversational replies should NEVER show the Build Agent button. Only actual capability gaps should trigger self-mod proposals.

## Root Cause

In `src/probos/runtime.py`, inside `process_natural_language()`, the `auto_selfmod=False` branch (API mode, around line 1226) calls `_extract_unhandled_intent(text)` and creates a `self_mod_result` with `status: "proposed"` without checking whether the response is a genuine capability gap or just a conversational reply.

The outer guard `if self.self_mod_pipeline and (not dag.response or is_gap)` should prevent this, but the `else` branch inside it unconditionally extracts an intent for ANY empty-DAG response when `auto_selfmod=False`. The `is_gap` check is missing from this inner branch.

## Fix

### File: `src/probos/runtime.py`

Find the `else` branch inside the empty-DAG / self-mod block (around line 1226). It currently looks like:

```python
else:
    # API mode: return the capability gap as a proposal
    # without running inline self-mod
    intent_meta = await self._extract_unhandled_intent(text)
    if intent_meta:
        self_mod_result = {
            "status": "proposed",
            "intent": intent_meta["name"],
            "description": intent_meta.get("description", ""),
            "parameters": intent_meta.get("parameters", {}),
        }
```

Add the `is_gap or not dag.response` guard so conversational replies are excluded:

```python
else:
    # API mode: return the capability gap as a proposal
    # without running inline self-mod.
    # Only propose when there's an actual capability gap,
    # not for conversational replies (AD-269).
    if is_gap or not dag.response:
        intent_meta = await self._extract_unhandled_intent(text)
        if intent_meta:
            self_mod_result = {
                "status": "proposed",
                "intent": intent_meta["name"],
                "description": intent_meta.get("description", ""),
                "parameters": intent_meta.get("parameters", {}),
            }
```

The key change: wrap the `_extract_unhandled_intent` call in `if is_gap or not dag.response:`. This ensures:
- "Hello" → `dag.response` is truthy ("Hello! I'm ProbOS..."), `is_gap` is False → skipped, no Build Agent button
- "Get the Bitcoin price" → `dag.response` is truthy ("I don't have..."), `is_gap` is True → proposed, Build Agent button shown
- Empty dag with no response → `dag.response` is falsy → proposed, Build Agent button shown

## Tests

### File: `tests/test_hxi_chat_integration.py` (or wherever the chat API tests live)

Add 2 tests:

1. `test_hello_no_selfmod_proposal` — call `process_natural_language("Hello", auto_selfmod=False)`, verify `result.get("self_mod")` is None
2. `test_capability_gap_has_selfmod_proposal` — call `process_natural_language("generate a QR code", auto_selfmod=False)` with a runtime that has self_mod enabled, verify `result.get("self_mod")` has `status: "proposed"`

If the test file doesn't exist or is hard to set up, these can be skipped — the critical thing is the runtime fix. But do add them if feasible.

## PROGRESS.md

Update:
- Status line (line 3) test count
- Add AD-269 section before `## Active Roadmap`:

```
### AD-269: Fix Conversational Responses Showing Build Agent Button

**Problem:** Saying "Hello" in the HXI showed a "Build Agent" button alongside the greeting. The API-mode self-mod proposal path in `process_natural_language()` was missing the `is_gap` check, causing `_extract_unhandled_intent()` to run for conversational replies.

| AD | Decision |
|----|----------|
| AD-269 | Added `if is_gap or not dag.response` guard around the API-mode self-mod proposal path. Conversational responses (where `dag.response` is set and `is_gap` is False) no longer trigger `_extract_unhandled_intent()` or produce `self_mod_proposal` in the API response |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/runtime.py` | Added `is_gap` guard in API-mode self-mod proposal branch |

NNNN/NNNN tests passing (+ 11 skipped).
```

Replace NNNN with the actual test count.

## Constraints

- Only touch `src/probos/runtime.py` (and optionally test files + PROGRESS.md)
- Do NOT touch any UI/TypeScript files
- Do NOT touch `api.py`
- Do NOT modify the `auto_selfmod=True` path — only the `else` (API mode) branch
- Run tests after edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Report the final test count
