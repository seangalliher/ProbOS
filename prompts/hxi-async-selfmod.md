# HXI Async Self-Mod with Approval Flow

## Problem

Self-modification (capability gap → agent design → validate → sandbox → deploy) is currently synchronous in the API path. It takes 30-60+ seconds (multiple LLM calls), blocks the chat, and bypasses the user approval step that exists in the CLI. The result is either a timeout or a long hang.

## Design: Async Self-Mod with Approval

### The Flow

```
1. User: "write me a haiku about the ocean"
2. Decomposer: capability gap detected → returns immediately
3. Chat shows: "I don't have a creative writing capability yet, but I can build one."
              [✨ Build Agent]  [❌ Skip]
4. User clicks [✨ Build Agent]
5. Frontend sends POST /api/selfmod/approve with the intent details
6. Backend starts self-mod pipeline as asyncio.create_task() (non-blocking)
7. Pipeline emits WebSocket events at each stage:
   - self_mod_started: "🔧 Designing creative writing agent..."
   - self_mod_validated: "✓ Code passed validation"
   - self_mod_sandboxed: "✓ Sandbox test passed"
   - self_mod_deployed: "✨ CreativeWritingAgent is ready!"
8. Frontend shows these as progress messages in the chat
9. After deployment, frontend auto-sends the original request again
10. The new agent handles it: "Waves crash and sigh..."
```

### The User Never Waits Blocked

- The capability gap response returns in < 3 seconds (just decomposition)
- The approval buttons appear instantly
- After approval, progress messages stream via WebSocket while the user can continue chatting
- If they reject, nothing happens — no time wasted

## Implementation

### Backend: New API endpoint + async pipeline

**File:** `src/probos/api.py` — add self-mod endpoints

```python
class SelfModRequest(BaseModel):
    intent_name: str
    intent_description: str
    parameters: dict[str, str] = {}
    original_message: str = ""  # the user's original request to auto-retry

@app.post("/api/selfmod/approve")
async def approve_selfmod(req: SelfModRequest) -> dict[str, Any]:
    """Start async self-mod pipeline. Progress via WebSocket events."""
    if not hasattr(runtime, 'self_mod_pipeline') or not runtime.self_mod_pipeline:
        return {"response": "Self-modification is not enabled.", "status": "error"}
    
    # Start pipeline in background — don't block
    asyncio.create_task(_run_selfmod(req, runtime))
    
    return {
        "response": "🔧 Starting agent design...",
        "status": "started",
    }

async def _run_selfmod(req: SelfModRequest, runtime: Any) -> None:
    """Background self-mod pipeline with WebSocket progress events."""
    try:
        # Emit start event
        runtime._emit_event("self_mod_started", {
            "intent": req.intent_name,
            "description": req.intent_description,
            "message": f"🔧 Designing agent for '{req.intent_name}'..."
        })
        
        record = await runtime.self_mod_pipeline.handle_unhandled_intent(
            intent_name=req.intent_name,
            intent_description=req.intent_description,
            parameters=req.parameters,
        )
        
        if record and record.status == "active":
            # Register the new agent
            await runtime._register_designed_agent(record)
            
            runtime._emit_event("self_mod_success", {
                "intent": req.intent_name,
                "agent_type": record.agent_type,
                "message": f"✨ {record.class_name} deployed! Handling your request..."
            })
            
            # Auto-retry the original request
            if req.original_message:
                result = await runtime.process_natural_language(req.original_message)
                response = result.get("response", "") or result.get("reflection", "") or "Done."
                runtime._emit_event("self_mod_retry_complete", {
                    "intent": req.intent_name,
                    "response": response,
                    "message": response,
                })
        else:
            runtime._emit_event("self_mod_failure", {
                "intent": req.intent_name,
                "message": f"❌ Could not design agent for '{req.intent_name}'",
                "reason": getattr(record, 'status', 'unknown') if record else "design failed",
            })
    except Exception as e:
        runtime._emit_event("self_mod_failure", {
            "intent": req.intent_name,
            "message": f"❌ Agent design failed: {e}",
        })
```

### Backend: Modify capability gap response

**File:** `src/probos/api.py` — in the `/api/chat` handler

When `dag_result` has `capability_gap: true` or `self_mod` data, return a structured response that the frontend can render as an approval prompt:

```python
# After getting dag_result, check for capability gap
if not response_text and dag_result.get("self_mod"):
    self_mod = dag_result["self_mod"]
    return {
        "response": f"I don't have a capability for '{self_mod.get('intent', 'this')}' yet, but I can build one.",
        "dag": None,
        "results": None,
        "self_mod_proposal": {
            "intent_name": self_mod.get("intent", ""),
            "intent_description": self_mod.get("intent", ""),
            "status": "proposed",
            "original_message": req.message,
        }
    }
```

BUT ALSO — the self-mod pipeline currently runs INLINE in `process_natural_language()`. We need to prevent it from running there and instead return the gap for the API to handle:

**File:** `src/probos/runtime.py` — add a flag to skip inline self-mod

Add a parameter `auto_selfmod: bool = True` to `process_natural_language()`. When called from the API, pass `auto_selfmod=False` so the capability gap is returned WITHOUT triggering inline self-mod. The CLI still passes `True` (or omits it) for backward compatibility.

```python
async def process_natural_language(
    self,
    text: str,
    on_event: ... = None,
    auto_selfmod: bool = True,  # NEW — set False from API
) -> dict[str, Any]:
    ...
    if not dag.nodes:
        if self.self_mod_pipeline and auto_selfmod and (not dag.response or is_gap):
            # existing inline self-mod code
            ...
        elif self.self_mod_pipeline and not auto_selfmod and (not dag.response or is_gap):
            # Return the gap WITHOUT running self-mod
            intent_meta = await self._extract_unhandled_intent(text)
            result["self_mod_proposal"] = {
                "intent": intent_meta["name"] if intent_meta else "unknown",
                "description": intent_meta.get("description", "") if intent_meta else "",
                "parameters": intent_meta.get("parameters", {}) if intent_meta else {},
                "status": "proposed",
            }
```

In `api.py`, call with `auto_selfmod=False`:
```python
dag_result = await asyncio.wait_for(
    runtime.process_natural_language(req.message, on_event=on_event, auto_selfmod=False),
    timeout=30.0,
)
```

### Frontend: Approval buttons + progress messages

**File:** `ui/src/components/IntentSurface.tsx`

When a chat response includes `self_mod_proposal`, render approval buttons:

```typescript
// After adding system message, check for self_mod_proposal
if (data.self_mod_proposal) {
  // Add a special message with action buttons
  addChatMessage('system', data.response, {
    selfModProposal: data.self_mod_proposal,
  });
}
```

Render the proposal message with buttons:

```tsx
// In the message rendering:
{msg.selfModProposal && (
  <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
    <button 
      onClick={() => approveSelfMod(msg.selfModProposal)}
      style={{
        background: 'rgba(80, 200, 120, 0.2)',
        border: '1px solid rgba(80, 200, 120, 0.4)',
        borderRadius: 8, padding: '6px 16px',
        color: '#80c878', cursor: 'pointer', fontSize: 13,
      }}
    >
      ✨ Build Agent
    </button>
    <button
      onClick={() => addChatMessage('system', 'Skipped — no agent created.')}
      style={{
        background: 'rgba(128, 128, 160, 0.1)',
        border: '1px solid rgba(128, 128, 160, 0.2)',
        borderRadius: 8, padding: '6px 16px',
        color: '#8888a0', cursor: 'pointer', fontSize: 13,
      }}
    >
      ❌ Skip
    </button>
  </div>
)}
```

```typescript
async function approveSelfMod(proposal: SelfModProposal) {
  addChatMessage('system', '🔧 Starting agent design...');
  
  await fetch('/api/selfmod/approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      intent_name: proposal.intent_name,
      intent_description: proposal.intent_description,
      parameters: proposal.parameters || {},
      original_message: proposal.original_message || '',
    }),
  });
  // Progress and results come via WebSocket events
}
```

**File:** `ui/src/store/useStore.ts` — handle self-mod WebSocket events

```typescript
case 'self_mod_started':
case 'self_mod_success':
case 'self_mod_failure':
case 'self_mod_retry_complete':
  // Add the message to chat history
  const msg = event.data.message || event.data.response || '';
  if (msg) {
    get().addChatMessage('system', msg);
  }
  break;
```

**File:** `ui/src/store/types.ts` — extend ChatMessage type

```typescript
interface ChatMessage {
  role: 'user' | 'system';
  text: string;
  timestamp: number;
  selfModProposal?: {
    intent_name: string;
    intent_description: string;
    parameters: Record<string, string>;
    original_message: string;
    status: 'proposed' | 'approved' | 'rejected';
  };
}
```

### CLI backward compatibility

The CLI shell continues to work as before — `process_natural_language()` defaults to `auto_selfmod=True`, which runs the inline pipeline with the existing terminal approval prompt. No CLI changes needed.

## Do NOT Change

- No changes to `self_mod.py` pipeline logic — it stays the same, just called from a different place
- No changes to `CodeValidator`, `SandboxRunner`, `AgentDesigner` — the pipeline is unchanged
- No changes to CLI shell behavior — `auto_selfmod=True` preserves existing flow
- Keep the 30s timeout on normal chat — only self-mod runs longer (and it's async, so timeout doesn't apply)

## After Fix

1. Rebuild frontend: `cd ui && npm run build`
2. Restart `probos serve`
3. Test: "write me a haiku about the ocean"
   - Should see: "I don't have a capability for 'creative_writing' yet, but I can build one."
   - Two buttons: [✨ Build Agent] [❌ Skip]
   - Click Build Agent → progress messages stream in chat
   - Agent deploys → original request auto-retries → haiku appears
4. Test: Click Skip → "Skipped" message, no agent created
5. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
