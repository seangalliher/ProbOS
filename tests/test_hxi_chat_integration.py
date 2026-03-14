"""Automated HXI chat integration tests.

These tests start a ProbOS runtime with MockLLMClient and test
the /api/chat endpoint with common user queries to catch regressions.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.runtime import ProbOSRuntime


@pytest.fixture
async def chat_client(tmp_path):
    """Create a test client with a running ProbOS runtime."""
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    app = create_app(rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await rt.stop()


class TestChatEndpoint:
    """Test common chat queries don't crash or hang."""

    @pytest.mark.asyncio
    async def test_hello(self, chat_client):
        """Conversational greeting returns a response."""
        r = await chat_client.post("/api/chat", json={"message": "hello"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # non-empty

    @pytest.mark.asyncio
    async def test_what_can_you_do(self, chat_client):
        """Capability question returns a response."""
        r = await chat_client.post("/api/chat", json={"message": "what can you do?"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # non-empty

    @pytest.mark.asyncio
    async def test_read_file(self, chat_client):
        """File read query produces a result."""
        r = await chat_client.post(
            "/api/chat", json={"message": "read the file at /tmp/test.txt"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("response") or data.get("results")

    @pytest.mark.asyncio
    async def test_slash_status(self, chat_client):
        """Slash command /status returns clean text."""
        r = await chat_client.post("/api/chat", json={"message": "/status"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]
        # Should NOT contain box-drawing characters
        assert "\u2502" not in data["response"]
        assert "\u2500" not in data["response"]

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
        assert data["response"]  # should say something about no recent execution

    @pytest.mark.asyncio
    async def test_empty_message(self, chat_client):
        """Empty message doesn't crash."""
        r = await chat_client.post("/api/chat", json={"message": ""})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_timeout_handling(self, chat_client):
        """Long-running query eventually returns (doesn't hang forever)."""
        r = await chat_client.post(
            "/api/chat",
            json={"message": "what time is it in Tokyo, Japan?"},
            timeout=35.0,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["response"]


class TestHealthEndpoint:
    """Test health and status endpoints."""

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
