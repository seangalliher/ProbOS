# Fix: Block /quit from HXI Chat

## Problem

Typing `/quit` in the HXI chat triggers server shutdown, which kills the HXI the user is currently using. The user gets stuck in a "shutting down" state with no way to recover except force-killing the process.

## Fix

**File:** `src/probos/api.py` — in `_handle_slash_command()`

Before delegating to the shell, block commands that don't make sense from a web interface:

```python
# Commands that should NOT be available via the API
BLOCKED_COMMANDS = {'/quit', '/debug'}

parts = text.split(None, 1)
cmd = parts[0].lower()

if cmd in BLOCKED_COMMANDS:
    return {
        "response": f"{cmd} is only available in the CLI terminal, not the HXI chat.",
        "dag": None,
        "results": None,
    }
```

Add this check at the top of `_handle_slash_command()`, before the shell delegation.

## After fix
Restart `probos serve`. Type `/quit` in HXI chat — should see "not available in HXI" message instead of shutdown.
