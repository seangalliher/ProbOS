# Fix: Self-Mod Timeout — Increase API Timeout for Agent Design

## Problem

Self-modification (capability gap → agent design → validate → sandbox → deploy) requires 3-5 sequential LLM calls. With Sonnet at ~3-5 seconds per call plus sandbox testing, the total is 15-30+ seconds. The `/api/chat` endpoint has a 30-second `asyncio.wait_for()` timeout that kills the self-mod pipeline before it completes. The user sees "(Request timed out — the mesh took too long to respond)".

## Fix

**File:** `src/probos/api.py`

Increase the timeout from 30 seconds to 90 seconds:

```python
dag_result = await asyncio.wait_for(
    runtime.process_natural_language(
        req.message, on_event=on_event,
    ),
    timeout=90.0,  # was 30.0 — self-mod needs 3-5 LLM calls
)
```

Also update the timeout error message to be more informative:

```python
except asyncio.TimeoutError:
    logger.warning("Chat request timed out after 90s: %s", req.message[:80])
    return {
        "response": "(This is taking longer than expected. The system may be designing a new agent — try again in a moment.)",
        "dag": None,
        "results": None,
    }
```

## Also: Show progress during self-mod

The self-mod pipeline emits events (`self_mod_design`, `self_mod_success`, `self_mod_failure`) that broadcast to WebSocket clients. The HXI should show these in the chat as progress updates so the user knows something is happening:

In `ui/src/store/useStore.ts` or `IntentSurface.tsx`: when a `self_mod_design` WebSocket event arrives while there's a pending request, add a system message to the chat:

```
"🔧 Designing a new agent for this capability..."
```

When `self_mod_success` arrives:
```
"✨ New agent created! Processing your request..."
```

This way the 30-60 second self-mod pipeline doesn't feel like a hang — the user sees progress.

## After fix

1. Restart `probos serve`
2. Type "write me a haiku about the ocean"
3. Should see "🔧 Designing..." progress, then the haiku
4. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
