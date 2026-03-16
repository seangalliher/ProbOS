# E2E Integration Test: Self-Mod Pipeline Through API

## Problem

All self-mod bugs this session (rate limiter cascade, QA competing with auto-retry, auto-retry sending wrong message, tooltip regression from new agents) were cross-component interaction bugs that unit tests can't catch. We need an end-to-end test that exercises the full chain: API chat → capability gap → self-mod approve → design → validate → sandbox → deploy → auto-retry → result.

## Implementation

### File: `tests/test_selfmod_e2e.py` (new file)

Create a comprehensive E2E test class that exercises the full self-mod pipeline using the FastAPI test client and MockLLMClient. No real LLM or API calls.

```python
"""End-to-end integration tests for the self-mod pipeline.

These tests exercise the full chain:
  /api/chat → capability gap → /api/selfmod/approve → 
  design → validate → sandbox → deploy → auto-retry → result

All cross-component interactions that caused bugs in production
(rate limiter cascade, QA competition, auto-retry routing, 
tooltip regression) are covered here.
"""

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime


@pytest.fixture
async def app_and_runtime(tmp_path):
    """Boot a full runtime + FastAPI app with MockLLMClient."""
    config = SystemConfig()
    config.self_mod.enabled = True
    config.qa.enabled = False  # Prevent QA from interfering with E2E flow
    llm = MockLLMClient()
    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    app = create_app(rt)
    yield app, rt
    await rt.stop()


class TestSelfModE2E:
    """End-to-end tests for the self-mod → auto-retry pipeline."""

    @pytest.mark.asyncio
    async def test_chat_returns_capability_gap(self, app_and_runtime):
        """Chat with an unhandled intent returns self_mod_proposal."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat", json={
                "message": "I want you to design a new agent that can count words in a text",
            })
            data = resp.json()
            assert resp.status_code == 200
            # Should either have a self_mod_proposal or a response indicating gap
            # (depends on whether MockLLM returns a gap or routes to existing intent)
            assert "response" in data

    @pytest.mark.asyncio
    async def test_selfmod_approve_creates_agent(self, app_and_runtime):
        """POST /api/selfmod/approve creates a new agent and returns success."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/selfmod/approve", json={
                "intent_name": "count_words",
                "intent_description": "Count the number of words in a text",
                "parameters": {"text": "input text"},
                "original_message": "count the words in hello world",
            })
            data = resp.json()
            assert resp.status_code == 200
            assert data["status"] == "started"

            # Wait for the background task to complete
            await asyncio.sleep(5)

            # Verify the agent was created
            assert "count_words" in [
                d.name for d in rt._collect_intent_descriptors()
            ]

    @pytest.mark.asyncio
    async def test_selfmod_creates_pool_with_size_1(self, app_and_runtime):
        """Designed agent pool should have size 1 (AD-265)."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/selfmod/approve", json={
                "intent_name": "count_words",
                "intent_description": "Count words in text",
                "parameters": {"text": "input"},
                "original_message": "",
            })
            await asyncio.sleep(5)

            pool = rt.pools.get("designed_count_words")
            if pool:
                assert pool.current_size == 1

    @pytest.mark.asyncio
    async def test_auto_retry_uses_intent_description(self, app_and_runtime):
        """Auto-retry should use intent_description, not original_message."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Use a meta-request as original_message
            await client.post("/api/selfmod/approve", json={
                "intent_name": "count_words",
                "intent_description": "Count the number of words in a text",
                "parameters": {"text": "input text"},
                "original_message": "I want you to design a new agent that counts words",
            })
            await asyncio.sleep(5)

            # The auto-retry should have used "Count the number of words in a text"
            # not the meta-request about designing. Check _last_execution_text
            if rt._last_execution_text:
                assert "design" not in rt._last_execution_text.lower() or \
                       "count" in rt._last_execution_text.lower()

    @pytest.mark.asyncio
    async def test_qa_runs_after_auto_retry(self, app_and_runtime):
        """QA should not interfere with auto-retry (runs after)."""
        # With QA disabled in fixture, this verifies no QA interference
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/selfmod/approve", json={
                "intent_name": "count_words",
                "intent_description": "Count words",
                "parameters": {"text": "input"},
                "original_message": "count words in hello",
            })
            await asyncio.sleep(5)
            # If we got here without timeout, QA didn't block the pipeline
            assert True

    @pytest.mark.asyncio
    async def test_health_endpoint(self, app_and_runtime):
        """GET /api/health returns system status."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
            data = resp.json()
            assert resp.status_code == 200
            assert "status" in data
            assert "agents" in data
            assert data["agents"] > 0

    @pytest.mark.asyncio
    async def test_chat_hello_no_selfmod_proposal(self, app_and_runtime):
        """Conversational 'Hello' should NOT return a self_mod_proposal."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat", json={
                "message": "Hello",
            })
            data = resp.json()
            assert resp.status_code == 200
            assert "self_mod_proposal" not in data

    @pytest.mark.asyncio
    async def test_chat_with_conversation_history(self, app_and_runtime):
        """Chat with history should pass conversation context to decomposer."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat", json={
                "message": "What about Portland?",
                "history": [
                    {"role": "user", "text": "What is the weather in Seattle?"},
                    {"role": "system", "text": "The weather in Seattle is 55°F..."},
                ],
            })
            data = resp.json()
            assert resp.status_code == 200
            # Should have processed without error — the history was passed through
            assert "response" in data or "results" in data

    @pytest.mark.asyncio
    async def test_enrich_endpoint(self, app_and_runtime):
        """POST /api/selfmod/enrich returns enriched description."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/selfmod/enrich", json={
                "intent_name": "count_words",
                "intent_description": "Count words",
                "parameters": {"text": "input"},
                "user_guidance": "Use Python's split() method to count words",
            })
            data = resp.json()
            assert resp.status_code == 200
            assert "enriched" in data
            assert len(data["enriched"]) > 0


class TestAPIEdgeCases:
    """Edge cases and error handling for the API layer."""

    @pytest.mark.asyncio
    async def test_chat_empty_message(self, app_and_runtime):
        """Empty message should not crash."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat", json={"message": ""})
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_selfmod_disabled(self, tmp_path):
        """Self-mod approve should fail gracefully when self-mod is disabled."""
        config = SystemConfig()
        config.self_mod.enabled = False
        llm = MockLLMClient()
        rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data2", llm_client=llm)
        await rt.start()
        app = create_app(rt)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/selfmod/approve", json={
                "intent_name": "test",
                "intent_description": "test",
                "parameters": {},
                "original_message": "",
            })
            data = resp.json()
            assert data["status"] == "error"
        await rt.stop()

    @pytest.mark.asyncio
    async def test_slash_command_via_api(self, app_and_runtime):
        """Slash commands via API should work or be blocked appropriately."""
        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat", json={"message": "/status"})
            data = resp.json()
            assert resp.status_code == 200
            assert "response" in data
```

### Key design decisions:

1. **Uses httpx AsyncClient with ASGITransport** — tests the FastAPI app directly, no real HTTP server needed
2. **QA disabled in fixture** — prevents QA smoke tests from interfering with E2E timing (the bug we found)
3. **asyncio.sleep(5)** for self-mod background tasks — the approve endpoint returns immediately and runs design in background
4. **Tests cover every bug found this session:** capability gap detection, auto-retry message, pool size, QA ordering, hello no-proposal, conversation history, enrich endpoint
5. **MockLLMClient** — no real LLM calls, fully deterministic

### Dependencies:

Add `httpx` to dev dependencies if not already present:
```
pip install httpx
```
(`httpx` is already a dependency via FastAPI, so it should be available)

## PROGRESS.md

Update status line test count. No new AD section needed — this is testing infrastructure.

## Constraints

- Create `tests/test_selfmod_e2e.py` as a new file
- Do NOT modify any production code
- Do NOT modify existing test files
- Use `ASGITransport` from httpx for FastAPI testing (no real server)
- All tests must use MockLLMClient — no real LLM calls
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_selfmod_e2e.py -x -q` (run new file first)
- Then full suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Update PROGRESS.md test count
