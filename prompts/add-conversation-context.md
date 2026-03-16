# AD-273: Conversation Context for Decomposer

## Problem

Each message to ProbOS is stateless — the decomposer sees only the current message, working memory, and episodic recall. It cannot resolve conversational references like "What about Portland?" (after asking about Seattle weather), "Do that again", "Now try it in French", or "Tell me more." The system feels "born 5 minutes ago" every time.

## Design

Send the last N chat messages as conversation history from the HXI to the API, then inject them into the decomposer's LLM prompt. The LLM naturally resolves references when it can see the conversation flow.

### Example:

```
## CONVERSATION CONTEXT
User: What is the weather in Seattle?
System: The weather in Seattle is 72°F, partly cloudy...
User: What about Portland?
```

The LLM sees "What about Portland?" in context of the previous weather query and correctly decomposes it as `get_weather` with `location: "Portland"`.

## Implementation

### File: `src/probos/api.py`

1. Update `ChatRequest` to include optional history:

```python
class ChatMessage(BaseModel):
    role: str  # "user" or "system"
    text: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
```

2. In the `chat()` endpoint, pass history to `process_natural_language()`:

```python
dag_result = await asyncio.wait_for(
    runtime.process_natural_language(
        req.message,
        on_event=on_event,
        auto_selfmod=False,
        conversation_history=[(m.role, m.text) for m in req.history[-10:]],
    ),
    timeout=30.0,
)
```

### File: `src/probos/runtime.py`

3. Add `conversation_history` parameter to `process_natural_language()`:

```python
async def process_natural_language(
    self,
    text: str,
    on_event: ... = None,
    auto_selfmod: bool = True,
    conversation_history: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
```

4. Pass it through to the decomposer:

```python
dag = await self.decomposer.decompose(
    text,
    context=context,
    similar_episodes=similar_episodes or None,
    conversation_history=conversation_history,
)
```

### File: `src/probos/cognitive/decomposer.py`

5. Add `conversation_history` parameter to `decompose()`:

```python
async def decompose(
    self,
    text: str,
    context: WorkingMemorySnapshot | None = None,
    similar_episodes: list[Episode] | None = None,
    conversation_history: list[tuple[str, str]] | None = None,
) -> TaskDAG:
```

6. Add conversation context section to the prompt, AFTER working memory and BEFORE user request:

```python
# Add conversation history for context resolution
if conversation_history:
    prompt_parts.append("## CONVERSATION CONTEXT")
    prompt_parts.append("Recent messages in this conversation (most recent last):")
    for role, msg_text in conversation_history[-5:]:
        label = "User" if role == "user" else "ProbOS"
        # Truncate long responses to save tokens
        truncated = msg_text[:200] + "..." if len(msg_text) > 200 else msg_text
        prompt_parts.append(f"{label}: {truncated}")
    prompt_parts.append("")
    prompt_parts.append(
        "Use this context to resolve references like 'it', 'that', "
        "'the same thing', 'what about X', 'do it again', etc."
    )
    prompt_parts.append("")
```

7. Place this BEFORE `prompt_parts.append(f"User request: {text}")` so the conversation flows naturally into the current request.

### File: `ui/src/components/IntentSurface.tsx`

8. In the `submit` function where `fetch('/api/chat', ...)` is called, include the last 10 chat messages as history:

```typescript
const recentHistory = chatHistory.slice(-10).map(m => ({
  role: m.role,
  text: m.text.slice(0, 300), // Truncate for payload size
}));

const response = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    message: text,
    history: recentHistory,
  }),
});
```

## Key design decisions

- **Last 5 messages in the prompt** (from up to 10 sent by client) — enough for reference resolution without bloating the prompt
- **Truncate system responses to 200 chars** — the LLM only needs the gist, not the full weather report
- **Conversation history is optional** — `process_natural_language()` works without it (backward compat for shell, tests)
- **No persistence** — conversation context is session-only (localStorage chat history is for display, not for the LLM)
- **Token budget** — 5 messages × ~50 tokens each = ~250 extra tokens. Well within budget

## Tests

### File: `tests/test_decomposer.py`

Add 2-3 tests:

1. `test_conversation_context_in_prompt` — pass conversation_history to decompose(), verify "CONVERSATION CONTEXT" appears in the LLM prompt
2. `test_conversation_context_truncation` — pass a long message, verify it's truncated to 200 chars
3. `test_conversation_context_optional` — decompose() without conversation_history still works (backward compat)

## PROGRESS.md

Update:
- Status line test count
- Add AD-273 section before `## Active Roadmap`:

```
### AD-273: Conversation Context for Decomposer

**Problem:** Each message was stateless — the decomposer couldn't resolve references like "What about Portland?" after a Seattle weather query. The system felt "born 5 minutes ago" every time.

| AD | Decision |
|----|----------|
| AD-273 | HXI sends last 10 chat messages as `history` in ChatRequest. Runtime passes to decomposer as `conversation_history`. Decomposer injects last 5 messages (truncated to 200 chars) as CONVERSATION CONTEXT section in LLM prompt. LLM resolves references naturally. Optional parameter — backward compatible with shell/tests |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | ChatMessage model, history field on ChatRequest, passed to process_natural_language() |
| `src/probos/runtime.py` | conversation_history parameter on process_natural_language(), passed to decomposer |
| `src/probos/cognitive/decomposer.py` | conversation_history parameter on decompose(), CONVERSATION CONTEXT prompt section |
| `ui/src/components/IntentSurface.tsx` | Sends last 10 messages as history in /api/chat request |

NNNN/NNNN tests passing (+ 11 skipped). N new tests.
```

## Constraints

- Only touch: api.py, runtime.py, decomposer.py, IntentSurface.tsx, test_decomposer.py, PROGRESS.md
- Do NOT modify the shell (shell.py) — it doesn't have chat history
- Do NOT modify prompt_builder.py — the context is injected in decompose(), not in the system prompt
- Do NOT modify episodic memory — conversation context is separate from episodic recall
- The `conversation_history` parameter MUST be optional with default None for backward compat
- Rebuild UI: cd ui && npm run build
- Run tests: d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
- Report final test count
