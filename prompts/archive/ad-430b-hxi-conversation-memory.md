# AD-430b: HXI 1:1 Conversation Memory (Pillar 3)

## Context

ProbOS's HXI agent profile chat (`/api/agent/{id}/chat`) is stateless — each message is a one-shot request with no conversation history. The agent has no memory of what was just discussed. Meanwhile, the shell `/hail` command maintains full session history, passes it to the agent via `session_history` in IntentMessage params, and stores episodes. The cognitive layer's `_build_user_message()` (cognitive_agent.py line 310) already handles `session_history` — it just never receives it from the HXI path.

**The gap is pure plumbing:** the HXI client already tracks conversation history in the Zustand store (`agentConversations` map); it just never sends it to the server.

**Prerequisite:** AD-430a (episodic memory write paths) must be merged first. ✅ Done.

## Changes

### Step 1: API Request Model — Add history field

**File:** `src/probos/api.py`, line 186

Find the `AgentChatRequest` model. Add an optional `history` field:

```python
class AgentChatRequest(BaseModel):
    """Request to send a direct message to a specific agent."""
    message: str
    history: list[dict[str, str]] = []  # AD-430b: conversation history from HXI
```

The history format matches the shell pattern: `[{"role": "user", "text": "..."}, {"role": "agent", "text": "..."}]`.

### Step 2: API Endpoint — Pass history through IntentMessage

**File:** `src/probos/api.py`, line 1188

Find the IntentMessage construction inside `agent_chat()`. Replace the current block (lines 1188–1192):

```python
# Before (current):
intent = IntentMessage(
    intent="direct_message",
    params={"text": req.message, "from": "hxi_profile", "session": False},
    target_agent_id=agent_id,
)
```

With:

```python
# After (AD-430b):
intent = IntentMessage(
    intent="direct_message",
    params={
        "text": req.message,
        "from": "hxi_profile",
        "session": bool(req.history),  # AD-430b: session=True when history present
        "session_history": req.history[-10:] if req.history else [],  # AD-430b: last 10 exchanges
    },
    target_agent_id=agent_id,
)
```

**Cap at 10 entries** — prevents unbounded context growth. The shell `/hail` has no cap because it manages its own session lifecycle; HXI conversations can run indefinitely.

### Step 3: API Endpoint — Store episode after response

**File:** `src/probos/api.py`

In the same `agent_chat()` function, after `response_text` is resolved (after line 1205) and before the `return` statement at line 1207, insert episode storage:

```python
# AD-430b: Store HXI 1:1 interaction as episodic memory
if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
    try:
        import time as _time
        from probos.types import Episode
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
                "agent_type": agent.agent_type,
            }],
            reflection=f"Captain had a 1:1 conversation with {callsign or agent_id} via HXI.",
        )
        await runtime.episodic_memory.store(episode)
    except Exception:
        pass  # Non-critical — don't block the response
```

**Note:** `callsign` is already resolved at line 1196–1197. `response_text` is already resolved at lines 1199–1205. `agent` is already resolved at line 1180. No new lookups needed — all variables are in scope.

### Step 4: HXI Client — Send history with chat requests

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

**Critical ordering:** The current code (line 28) calls `addAgentMessage(agentId, 'user', text)` BEFORE the fetch. This means the current user message is already in the Zustand store when we build history. We must capture history BEFORE adding the current message — otherwise the current message appears in both `history` AND `req.message`, duplicating it.

Replace the `handleSend` body (lines 22–42) with:

```typescript
const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setSending(true);

    // AD-430b: Capture conversation history BEFORE adding current message
    const conv = useStore.getState().agentConversations.get(agentId);
    const history = (conv?.messages || [])
        .slice(-20)  // Last 20 messages (10 exchanges)
        .map(m => ({
            role: m.role === 'user' ? 'user' : 'agent',
            text: m.text,
        }));

    // Add user message immediately (after capturing history)
    useStore.getState().addAgentMessage(agentId, 'user', text);

    try {
        const res = await fetch(`/api/agent/${agentId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, history }),  // AD-430b: send history
        });
        const data = await res.json();
        useStore.getState().addAgentMessage(agentId, 'agent', data.response || '(no response)');
    } catch {
        useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
        setSending(false);
    }
}, [agentId, input, sending]);
```

### Step 5: Cross-session memory seeding

**File:** `src/probos/api.py`

Add a new endpoint after the `agent_chat()` function (after line 1211). This mirrors how the shell `/hail` command seeds `_session_history` with recalled episodes before the first message:

```python
@app.get("/api/agent/{agent_id}/chat/history")
async def agent_chat_history(agent_id: str) -> dict[str, Any]:
    """Recall past 1:1 interactions with this agent for session seeding."""
    memories: list[dict[str, str]] = []
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        try:
            episodes = await runtime.episodic_memory.recall_for_agent(
                agent_id, "1:1 conversation with Captain", k=3
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

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

Add a `useEffect` to fetch cross-session memories when the chat panel mounts. Store them in component state and prepend to the first request's history:

```typescript
const [seedMemories, setSeedMemories] = useState<{role: string; text: string}[]>([]);

// AD-430b: Fetch cross-session memories on mount
useEffect(() => {
    fetch(`/api/agent/${agentId}/chat/history`)
        .then(r => r.json())
        .then(data => setSeedMemories(data.memories || []))
        .catch(() => {});  // Non-critical
}, [agentId]);
```

Then in `handleSend`, prepend seed memories to the history array (only on first message, when no prior conversation exists):

```typescript
const fullHistory = conv?.messages?.length ? history : [...seedMemories, ...history];
// Use fullHistory instead of history in the fetch body
body: JSON.stringify({ message: text, history: fullHistory }),
```

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

## Constraints

- All episode storage is wrapped in try/except — non-critical, never blocks the response.
- History is capped at 10 entries server-side to prevent unbounded context growth.
- `response_text` in episode outcomes is truncated to 500 chars (consistent with AD-430a pattern).
- The `_build_user_message()` in `cognitive_agent.py` already handles `session_history` — NO changes needed there.
- No vitest test files exist for this component — don't create test infrastructure for one test.
- The `/api/chat` endpoint's @callsign path (line 431) is NOT modified — it's a one-shot command interface, not a conversation. Only the profile chat panel (`/api/agent/{id}/chat`) gets history support.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_api.py -x -v -k "chat" 2>&1 | tail -40
```
