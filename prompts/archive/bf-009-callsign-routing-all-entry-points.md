# BF-009: @Callsign Routing Missing from HXI and Embedded in Text

## Problem

AD-397 added `@callsign` routing for 1:1 crew sessions. It works when `@callsign` is the very first character of input in the shell and channel adapters. Two gaps:

1. **`/api/chat` endpoint** (`src/probos/api.py`) has **no** `@callsign` routing at all. Messages like `@wesley hello` from HXI chat go straight to `runtime.process_natural_language()`. The decomposer doesn't know about callsigns and responds as the Ship's Computer.

2. **All three entry points** only detect `@callsign` at the start of text via `text.startswith("@")`. Natural phrasing like `Hello @wesley` or `Can you ask @bones about the crew?` bypasses callsign routing entirely.

Console log confirming the API gap:
```
WARNING probos.runtime No intents parsed from NL input: @wesley hello
```

## Root Cause

- `api.py:282` `/api/chat` → dispatches `/` commands → falls through to `process_natural_language()`. No `@` branch.
- `channels/base.py:86` → `text.startswith("@")` — misses embedded `@callsign`.
- `shell.py:176` → `line.startswith("@")` — misses embedded `@callsign`.

## Fix

### Part 1: Extract callsign detection into a shared utility

Create a helper function in `src/probos/crew_profile.py` (where `CallsignRegistry` lives) that extracts `@callsign` from anywhere in a message:

```python
import re

def extract_callsign_mention(text: str) -> tuple[str, str] | None:
    """Extract the first @callsign mention from text.

    Returns (callsign, remaining_text) or None if no @mention found.
    The remaining_text has the @callsign removed and is stripped.
    """
    match = re.search(r'@(\w+)', text)
    if match:
        callsign = match.group(1)
        # Remove the @callsign from the text, keeping the rest as the message
        remaining = text[:match.start()] + text[match.end():]
        remaining = remaining.strip()
        return (callsign, remaining)
    return None
```

### Part 2: Add @callsign routing to `/api/chat`

In `src/probos/api.py`, in the `chat()` function, add a `@callsign` branch **after** the slash-command block and **before** the NL processing block (between lines 339 and 341).

The pattern should mirror `channels/base.py:112-142` (`_handle_callsign_message`):

```python
# AD-397/BF-009: @callsign direct message routing
mention = extract_callsign_mention(text)
if mention:
    callsign, message_text = mention
    resolved = runtime.callsign_registry.resolve(callsign)
    if resolved is not None:
        if resolved["agent_id"] is None:
            return {
                "response": f"{resolved['callsign']} is not currently on duty.",
                "dag": None,
                "results": None,
            }
        if not message_text:
            return {
                "response": f"{resolved['callsign']} is available. Send a message: @{callsign} <message>",
                "dag": None,
                "results": None,
            }
        from probos.types import IntentMessage
        intent = IntentMessage(
            intent="direct_message",
            params={"text": message_text, "from": "hxi", "session": False},
            target_agent_id=resolved["agent_id"],
        )
        result = await runtime.intent_bus.send(intent)
        response = f"{resolved['callsign']}: {result.result}" if result and result.result else f"{resolved['callsign']}: (no response)"
        return {"response": response, "dag": None, "results": None}
    # Callsign not found — fall through to NL processing
    # (user might have typed @something that isn't a callsign)
```

Add the import at the top of `api.py`:
```python
from probos.crew_profile import extract_callsign_mention
```

### Part 3: Update channel adapter to use shared utility

In `src/probos/channels/base.py`, replace the rigid `text.startswith("@")` check (line 86) with the shared utility:

```python
# AD-397/BF-009: @callsign direct message via channel (anywhere in text)
from probos.crew_profile import extract_callsign_mention
mention = extract_callsign_mention(text)
if mention:
    callsign, message_text = mention
    return await self._handle_callsign_message_parsed(callsign, message_text)
```

Refactor `_handle_callsign_message()` into `_handle_callsign_message_parsed(callsign, message_text)` that takes pre-parsed args instead of raw text. The existing `_handle_callsign_message` can be kept as a thin wrapper if needed for backwards compat, or just replaced.

The body stays the same (resolve callsign, check agent_id, build IntentMessage, send via intent_bus), just receives pre-parsed callsign and message_text instead of parsing them inline.

### Part 4: Update shell to use shared utility

In `src/probos/experience/shell.py`, replace the `line.startswith("@")` check (line 176) with the shared utility:

```python
from probos.crew_profile import extract_callsign_mention

# In execute_command(), replace lines 176-177:
mention = extract_callsign_mention(line)
if mention:
    await self._handle_at_parsed(mention[0], mention[1])
```

Refactor `_handle_at()` similarly — extract the callsign/message parsing (lines 1426-1429) into the caller, or add a `_handle_at_parsed(callsign, message)` that the utility calls into.

**Important**: The session mode check on line 168-174 also needs to use the utility for the embedded `@callsign` switching case (line 169). Apply the same pattern there.

### Part 5: Edge cases

- **Unknown callsign**: If `extract_callsign_mention` finds `@something` but it doesn't resolve, fall through to NL processing. The user might have typed `@` in a non-callsign context.
- **Multiple @mentions**: Only use the first one. This is a 1:1 conversation, not a group chat.
- **Slash commands take priority**: The `/` check must come before `@callsign` check in all entry points. Current ordering already handles this.
- **Session mode**: When in a shell session (`self._session_callsign`), the session-mode code should still take priority. Only use the embedded `@callsign` detection for session-switching. Current logic on line 168-174 handles this correctly — just update the `line.startswith("@")` on line 169 to also detect embedded mentions.

## Testing

1. **Unit test `extract_callsign_mention`**:
   - `"@wesley hello"` → `("wesley", "hello")`
   - `"Hello @wesley"` → `("wesley", "Hello")`
   - `"Hello @wesley how are you?"` → `("wesley", "Hello how are you?")`
   - `"@wesley"` → `("wesley", "")`
   - `"no mention"` → `None`
   - `"email@address.com"` — this will match `@address` which is an edge case. If it doesn't resolve as a callsign, we fall through to NL. Acceptable.

2. **API endpoint test**: Mock runtime with callsign_registry and intent_bus. POST `/api/chat` with `{"message": "@wesley hello"}`. Verify IntentMessage with `intent="direct_message"` is sent.

3. **API endpoint embedded test**: POST with `{"message": "Hello @wesley"}`. Same verification.

4. **Channel adapter test**: Send `"Hello @wesley"` through `handle_message()`. Verify callsign routing fires.

5. **Regression**: Verify slash commands still work. Verify messages with no `@` still go through NL. Verify unknown `@callsign` falls through to NL.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/crew_profile.py` | Add `extract_callsign_mention()` utility |
| `src/probos/api.py` | Add `@callsign` routing branch in `chat()` |
| `src/probos/channels/base.py` | Replace `startswith("@")` with `extract_callsign_mention()` |
| `src/probos/experience/shell.py` | Replace `startswith("@")` with `extract_callsign_mention()` |
| `tests/test_callsign_routing.py` | **NEW** — tests for the utility and routing |

## Commit Message

```
Fix @callsign routing in HXI and embedded mentions (BF-009)

@callsign was only detected at the start of text and was missing
entirely from the /api/chat endpoint. Extract callsign detection
into a shared utility, add routing to the API endpoint, and support
@mentions anywhere in the message across all entry points.
```
