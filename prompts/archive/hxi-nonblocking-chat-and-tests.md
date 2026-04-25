# HXI Chat Fixes — Non-Blocking + Automated Testing

## Problem 1: Chat blocks during task execution

The `/api/chat` endpoint is synchronous — the frontend `fetch()` call waits for the full pipeline (decompose → execute → reflect) to complete before the user can send another message. This makes the chat feel frozen during long operations.

### Fix: Make chat non-blocking

**File:** `ui/src/components/IntentSurface.tsx`

The `handleSubmit` function currently does:
```typescript
setSending(true);
const res = await fetch('/api/chat', ...);  // blocks until complete
setSending(false);
```

Change to fire-and-forget + poll for results:

```typescript
async function handleSubmit(e: React.FormEvent) {
  e.preventDefault();
  const text = input.trim();
  if (!text) return;

  setInput('');
  addChatMessage('user', text);
  
  // Don't block — fire and forget, response comes via callback
  fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text }),
  })
    .then(res => res.json())
    .then(data => {
      const response = data.response
        || data.reflection
        || extractResultText(data.results)
        || '(No response)';
      addChatMessage('system', response);
    })
    .catch(() => {
      addChatMessage('system', '(Request failed or timed out)');
    });

  // Input is immediately ready for next message
  // No setSending(true) — user can keep typing
}
```

This means:
- User types "What time is it in Tokyo?" → sends, input clears immediately
- User can immediately type another message ("Hello") while Tokyo query processes
- When Tokyo result arrives, it appears in the conversation thread
- If it times out, "(Request failed or timed out)" appears

**Important:** Multiple concurrent requests are fine — the runtime handles them independently. Each response goes into the chat thread when it arrives. Order may not match submission order — that's acceptable.

### Also: Show a "thinking" indicator for pending requests

Track pending request count in the store:

```typescript
// In the store
pendingRequests: number;  // increment on send, decrement on response

// In the conversation thread — show "⚡ Thinking..." for each pending request
{pendingRequests > 0 && (
  <div style={{ color: '#f0b060', fontSize: 12, padding: '4px 0' }}>
    ⚡ Thinking... ({pendingRequests} pending)
  </div>
)}
```

## Problem 2: Automated HXI Chat Testing

Create an automated test script that sends common queries through the API and validates responses. This catches regressions without manual testing.

**File:** `tests/test_hxi_chat_integration.py` (new)

```python
"""Automated HXI chat integration tests.

These tests start a ProbOS runtime with MockLLMClient and test
the /api/chat endpoint with common user queries to catch regressions.
"""

import pytest
import asyncio
from probos.api import create_app
from probos.runtime import ProbOSRuntime
from probos.config import load_config

# Use httpx.AsyncClient for testing FastAPI
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def chat_client():
    """Create a test client with a running ProbOS runtime."""
    config = load_config()
    runtime = ProbOSRuntime(config)
    await runtime.start()
    app = create_app(runtime)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await runtime.stop()


class TestChatEndpoint:
    """Test common chat queries don't crash or hang."""
    
    @pytest.mark.asyncio
    async def test_hello(self, chat_client):
        """Conversational greeting returns a response."""
        r = await chat_client.post("/api/chat", json={"message": "hello"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # non-empty
        assert "ProbOS" in data["response"] or "Hello" in data["response"]
    
    @pytest.mark.asyncio
    async def test_what_can_you_do(self, chat_client):
        """Capability question returns a helpful response."""
        r = await chat_client.post("/api/chat", json={"message": "what can you do?"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # non-empty
    
    @pytest.mark.asyncio
    async def test_read_file(self, chat_client):
        """File read query produces a DAG result."""
        r = await chat_client.post("/api/chat", json={"message": "read the file at /tmp/test.txt"})
        assert r.status_code == 200
        data = r.json()
        # Should have either a response or results
        assert data.get("response") or data.get("results")
    
    @pytest.mark.asyncio
    async def test_slash_status(self, chat_client):
        """Slash command /status returns clean text."""
        r = await chat_client.post("/api/chat", json={"message": "/status"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]
        # Should NOT contain box-drawing characters
        assert '│' not in data["response"]
        assert '─' not in data["response"]
    
    @pytest.mark.asyncio
    async def test_slash_model(self, chat_client):
        """Slash command /model returns LLM info."""
        r = await chat_client.post("/api/chat", json={"message": "/model"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]
    
    @pytest.mark.asyncio
    async def test_slash_help(self, chat_client):
        """Slash command /help returns command list."""
        r = await chat_client.post("/api/chat", json={"message": "/help"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]
        assert "/status" in data["response"]
    
    @pytest.mark.asyncio
    async def test_slash_quit_blocked(self, chat_client):
        """Slash command /quit is blocked from API."""
        r = await chat_client.post("/api/chat", json={"message": "/quit"})
        assert r.status_code == 200
        data = r.json()
        assert "not available" in data["response"].lower() or "CLI" in data["response"]
    
    @pytest.mark.asyncio
    async def test_slash_feedback_no_execution(self, chat_client):
        """/feedback good without prior execution returns appropriate message."""
        r = await chat_client.post("/api/chat", json={"message": "/feedback good"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # should say "no recent execution" or similar
    
    @pytest.mark.asyncio
    async def test_empty_message(self, chat_client):
        """Empty message doesn't crash."""
        r = await chat_client.post("/api/chat", json={"message": ""})
        assert r.status_code == 200
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, chat_client):
        """Long-running query eventually returns (doesn't hang forever)."""
        # This tests that the 30s timeout works
        r = await chat_client.post(
            "/api/chat", 
            json={"message": "what time is it in Tokyo, Japan?"},
            timeout=35.0,  # slightly longer than server timeout
        )
        assert r.status_code == 200
        # Either got a real response or a timeout message
        data = r.json()
        assert data["response"]


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, chat_client):
        r = await chat_client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["agents"] > 0
    
    @pytest.mark.asyncio
    async def test_status(self, chat_client):
        r = await chat_client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "total_agents" in data
```

Add `httpx` to test dependencies in `pyproject.toml` if not already present.

## After applying

1. Rebuild frontend: `cd ui && npm run build`
2. Restart `probos serve`
3. Test: type a long query, then immediately type "hello" — both should work without blocking
4. Run test suite including new tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
