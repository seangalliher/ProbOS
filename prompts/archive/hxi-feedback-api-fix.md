# HXI Feedback API Fix

## Problem

Clicking feedback icons (👍 👎 ✏️) sends slash commands like `/feedback good` to `/api/chat`, which routes them through `process_natural_language()`. The decomposer interprets these as natural language queries instead of feedback commands, producing system health reports or other unrelated responses.

The CLI shell handles `/feedback good` as a slash command via `execute_command()`. The API endpoint needs the same routing.

## Fix

**File:** `src/probos/api.py` — add slash command handling in the `/api/chat` endpoint

Before calling `process_natural_language()`, check if the message starts with `/` and handle feedback commands directly:

```python
@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    text = req.message.strip()
    
    # Handle slash commands directly (don't send through NL decomposer)
    if text.startswith('/'):
        return await _handle_slash_command(text, runtime)
    
    # Normal NL processing
    ...existing code...
```

```python
async def _handle_slash_command(text: str, runtime: Any) -> dict[str, Any]:
    """Handle slash commands via the API without going through the decomposer."""
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    
    if cmd == '/feedback':
        if not hasattr(runtime, 'record_feedback'):
            return {"response": "Feedback not available", "dag": None, "results": None}
        if arg not in ('good', 'bad'):
            return {"response": "Usage: /feedback good|bad", "dag": None, "results": None}
        try:
            result = runtime.record_feedback(arg == 'good')
            if result is None:
                return {"response": "No recent execution to rate.", "dag": None, "results": None}
            return {"response": f"✓ Feedback recorded ({arg})", "dag": None, "results": None}
        except Exception as e:
            return {"response": f"Feedback error: {e}", "dag": None, "results": None}
    
    elif cmd == '/correct':
        # Correction is more complex — pass the correction text through NL with correction context
        if arg:
            # Process as a normal message — the correction detector will pick it up
            dag_result = await runtime.process_natural_language(arg)
            response_text = dag_result.get("response", "") if dag_result else ""
            correction = dag_result.get("correction") if dag_result else None
            if correction:
                response_text = f"Correction applied: {correction.get('changes', 'OK')}"
            return {"response": response_text or "Correction processed", "dag": None, "results": None}
        return {"response": "Usage: /correct <what to fix>", "dag": None, "results": None}
    
    elif cmd == '/status':
        status = runtime.status()
        return {"response": f"Agents: {status.get('total_agents', 0)}, Health: {status.get('overall_health', 'N/A')}", "dag": None, "results": None}
    
    else:
        # Unknown slash command — pass through as NL (might be intentional)
        dag_result = await runtime.process_natural_language(text)
        response_text = dag_result.get("response", "") if dag_result else ""
        return {"response": response_text or f"Unknown command: {cmd}", "dag": None, "results": None}
```

## Also fix the frontend feedback handlers

**File:** `ui/src/components/IntentSurface.tsx` (or wherever feedback buttons live)

The feedback button click handler should:
1. Send the `/feedback good` or `/feedback bad` command to `/api/chat`
2. Show the confirmation text ("✓ Learned" / "✓ Noted") based on the RESPONSE from the API — not optimistically
3. Do NOT display the API response as a chat message — feedback confirmation is shown inline on the button, not in the conversation thread

```typescript
async function handleFeedback(type: 'good' | 'bad') {
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: `/feedback ${type}` }),
    });
    const data = await res.json();
    // Show inline confirmation on the button, NOT as a chat message
    // Set feedback state to show "✓ Learned" or "✓ Noted"
  } catch {
    // Show error state on button
  }
}
```

**Important:** Feedback responses should NOT appear in the conversation thread. They're inline UI confirmations on the feedback icons themselves.

## After fix

1. Restart `probos serve` (Python change)
2. Rebuild frontend if button handlers changed: `cd ui && npm run build`
3. Test: click 👍 → should see "✓ Learned" on the button, NOT a system health report in the chat
4. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
