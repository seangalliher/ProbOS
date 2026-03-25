# AD-430b: HXI 1:1 Conversation Memory (Pillar 3)

## Context

ProbOS's HXI agent profile chat (`/api/agent/{id}/chat`) is stateless — each message is a one-shot request with no conversation history. The agent has no memory of what was just discussed. Meanwhile, the shell `/hail` command maintains full session history, passes it to the agent via `session_history` in IntentMessage params, and stores episodes. The cognitive layer's `_build_user_message()` already handles `session_history` — it just never receives it from the HXI path.

**The gap is pure plumbing:** the HXI client already tracks conversation history in the Zustand store (`agentConversations` map); it just never sends it to the server.

**Prerequisite:** AD-430a (episodic memory write paths) must be merged first.

## Changes

### Step 1: API Request Model — Add history field

**File:** `src/probos/api.py`

Find the `AgentChatRequest` model (near line 186). Add an optional `history` field:

```python
class AgentChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []  # AD-430b: conversation history from HXI
```

The history format matches the shell pattern: `[{"role": "user", "text": "..."}, {"role": "agent", "text": "..."}]`.

### Step 2: API Endpoint — Pass history through IntentMessage

**File:** `src/probos/api.py`

Find the `agent_chat()` endpoint (the `POST /api/agent/{agent_id}/chat` handler). Update the IntentMessage construction to pass history:

```python
intent = IntentMessage(
    intent="direct_message",
    params={
        "text": req.message,
        "from": "hxi_profile",
        "session": bool(req.history),  # AD-430b: session=True when history present
        "session_history": req.history[-10:] if req.history else [],  # AD-430b: last 10 exchanges max
    },
    target_agent_id=agent_id,
)
```

**Cap at 10 exchanges** (20 messages) — prevents unbounded context growth. The shell `/hail` has no cap because it manages its own session lifecycle; HXI conversations can run indefinitely.

### Step 3: API Endpoint — Store episode after response

**File:** `src/probos/api.py`

In the same `agent_chat()` endpoint, after the response is obtained from `handle_intent()` and before returning, store an episode. Follow the shell `/hail` pattern:

```python
# AD-430b: Store HXI 1:1 interaction as episodic memory
if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
    try:
        import time as _time
        from probos.types import Episode
        callsign = ""
        if hasattr(runtime, 'callsign_registry'):
            callsign = runtime.callsign_registry.get_callsign(agent_type) or ""
        episode = Episode(
            user_input=f"[1:1 with {callsign or agent_id}] Captain: {req.message}",
            timestamp=_time.time(),
            agent_ids=[agent_id],
            outcomes=[{
                "intent": "direct_message",
                "success": True,
                "response": response_text[:500],
                "session_type": "1:1",
                "callsign": callsign,
                "source": "hxi_profile",
            }],
            reflection=f"Captain had a 1:1 conversation with {callsign or agent_id} via HXI.",
        )
        await runtime.episodic_memory.store(episode)
    except Exception:
        pass  # Non-critical — don't block the response
```

**Note:** You'll need to extract `response_text` and `agent_type` from the handle_intent result. Look at how the endpoint currently processes the response to determine the right variable names. The `agent_type` can be resolved from `agent_id` via the runtime's pool registry — check how the endpoint currently resolves the agent for the request.

### Step 4: HXI Client — Send history with chat requests

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

Find the `fetch` call that posts to `/api/agent/${agentId}/chat`. Update the body to include conversation history from the Zustand store:

```typescript
// Get conversation history from store
const conversation = useStore.getState().agentConversations.get(agentId);
const history = (conversation?.messages || [])
    .slice(-20)  // Last 20 messages (10 exchanges)
    .map(m => ({
        role: m.role === 'user' ? 'user' : 'agent',
        text: m.text,
    }));

const res = await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, history }),
});
```

**Important:** Send the history from the store state at the time of the request, BEFORE appending the current user message to the store. The current message is already in `req.message` — don't duplicate it in history. Check the component's flow to ensure correct ordering.

### Step 5: Cross-session memory seeding (optional but valuable)

**File:** `src/probos/api.py`

When the HXI profile chat panel opens, it should seed with relevant past episodes — just like the shell `/hail` command seeds `_session_history` with recalled episodes before the first message.

Add a new endpoint:

```python
@app.get("/api/agent/{agent_id}/chat/history")
async def agent_chat_history(agent_id: str) -> dict[str, Any]:
    """Recall past 1:1 interactions with this agent for session seeding."""
    runtime = _require_runtime()
    memories: list[dict[str, str]] = []
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        try:
            episodes = await runtime.episodic_memory.recall_for_agent(
                agent_id, f"1:1 conversation with Captain", k=3
            )
            for ep in episodes:
                memories.append({
                    "role": "system",
                    "text": f"[Previous conversation] {ep.user_input}",
                })
        except Exception:
            pass
    return {"memories": memories}
```

On the HXI side, call this endpoint when the chat panel first opens and prepend the returned memories to the first message's history. This gives the agent long-term conversational continuity across HXI sessions.

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

On component mount (or first message send), fetch `/api/agent/${agentId}/chat/history` and store the returned memories. Pass them as the first entries in each request's `history` array, before client-tracked conversation messages.

## Tests

**File:** `tests/test_api.py` — Add to existing API test class.

### Test 1: Chat with history passes session_history to intent
```
POST /api/agent/{id}/chat with {"message": "hello", "history": [{"role": "user", "text": "prev"}, {"role": "agent", "text": "resp"}]}.
Assert the IntentMessage created has params["session"] == True and params["session_history"] matching the history.
```

### Test 2: Chat without history sets session=False
```
POST /api/agent/{id}/chat with {"message": "hello"} (no history field).
Assert IntentMessage has params["session"] == False and params["session_history"] == [].
```

### Test 3: History is capped at 10 entries
```
POST /api/agent/{id}/chat with history containing 25 entries.
Assert IntentMessage params["session_history"] has exactly 10 entries (the last 10).
```

### Test 4: HXI chat stores episode
```
POST /api/agent/{id}/chat with a message. Mock episodic_memory on runtime.
Assert episodic_memory.store() was called with an Episode whose:
- user_input contains "[1:1 with" and the message text
- agent_ids == [agent_id]
- outcomes[0]["source"] == "hxi_profile"
- outcomes[0]["intent"] == "direct_message"
```

### Test 5: HXI chat works without episodic_memory
```
POST /api/agent/{id}/chat with runtime that has no episodic_memory.
Assert the response is successful — no crash.
```

### Test 6: Episode storage failure doesn't block response
```
POST /api/agent/{id}/chat with episodic_memory that raises on store().
Assert the chat response is still returned successfully.
```

### Test 7: Chat history recall endpoint returns memories
```
GET /api/agent/{id}/chat/history with mock episodic_memory containing past episodes.
Assert response contains memories list with "Previous conversation" formatted entries.
```

### Test 8: Chat history recall with no episodic_memory returns empty
```
GET /api/agent/{id}/chat/history with runtime that has no episodic_memory.
Assert response has memories == [].
```

**File:** `ui/src/components/profile/__tests__/ProfileChatTab.test.tsx` (if vitest tests exist for this component)

### Test 9: Chat sends history from store
```
Populate store with agentConversations for an agent. Trigger a chat send.
Assert the fetch body includes history array matching store messages.
```

## Constraints

- All episode storage is wrapped in try/except — non-critical, never blocks the response.
- History is capped at 10 entries server-side to prevent unbounded context growth.
- `response_text` in episode outcomes is truncated to 500 chars (consistent with AD-430a pattern).
- The `_build_user_message()` in `cognitive_agent.py` already handles `session_history` — NO changes needed there.
- Cross-session recall (Step 5) is a net-new endpoint. If it adds too much scope, it can be deferred — the core value (history passing + episode storage) is in Steps 1-4.
- Vitest tests (Step 9) are optional if the component doesn't have an existing test file — don't create test infrastructure just for one test.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_api.py -x -v -k "chat" 2>&1 | tail -40
```
