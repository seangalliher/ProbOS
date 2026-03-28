"""Tests for Agent Profile Panel API endpoints (AD-406)."""

import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace


@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    agent = MagicMock()
    agent.id = "agent-123"
    agent.agent_type = "scout"
    agent.confidence = 0.85
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.tier = "domain"
    agent.pool = "scout"
    agent.callsign = "Wesley"
    agent.is_alive = True
    return agent


@pytest.fixture
def mock_runtime(mock_agent):
    """Create a mock runtime with necessary services."""
    runtime = MagicMock()
    runtime.registry.get.return_value = mock_agent
    runtime.registry.all.return_value = [mock_agent]

    # Callsign registry
    runtime.callsign_registry.get_callsign.return_value = "Wesley"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Wesley",
        "agent_type": "scout",
        "agent_id": "agent-123",
        "display_name": "Science Officer",
        "department": "science",
    }

    # Trust network
    runtime.trust_network.get_score.return_value = 0.82

    # Hebbian router
    runtime.hebbian_router.all_weights_typed.return_value = {
        ("agent-123", "agent-456", "routing"): 0.75,
    }

    # No episodic memory
    runtime.episodic_memory = None

    # Intent bus for chat
    result = MagicMock()
    result.result = "Hello Captain, reporting for duty."
    result.success = True
    result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=result)

    # Event listener (needed for create_app)
    runtime.add_event_listener = MagicMock()

    # Workforce not enabled in test
    runtime.work_item_store = None

    return runtime


@pytest.fixture
def client(mock_runtime):
    """Create a test client for the API."""
    from probos.api import create_app
    from fastapi.testclient import TestClient
    app = create_app(mock_runtime)
    return TestClient(app)


def test_agent_profile_returns_data(client, mock_runtime):
    """GET /api/agent/{id}/profile returns agent profile data."""
    resp = client.get("/api/agent/agent-123/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "agent-123"
    assert data["agentType"] == "scout"
    assert data["callsign"] == "Wesley"
    assert data["department"] == "science"
    assert isinstance(data["trust"], float)
    assert isinstance(data["hebbianConnections"], list)


def test_agent_profile_404_unknown(client, mock_runtime):
    """GET /api/agent/{id}/profile returns 404 for unknown agent."""
    mock_runtime.registry.get.return_value = None
    resp = client.get("/api/agent/unknown-id/profile")
    assert resp.status_code == 404


def test_agent_chat_sends_message(client, mock_runtime):
    """POST /api/agent/{id}/chat routes direct_message intent."""
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "Status report, Wesley"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert data["callsign"] == "Wesley"
    assert data["agentId"] == "agent-123"
    # Verify intent was sent
    mock_runtime.intent_bus.send.assert_called_once()


def test_agent_chat_404_unknown(client, mock_runtime):
    """POST /api/agent/{id}/chat returns 404 for unknown agent."""
    mock_runtime.registry.get.return_value = None
    resp = client.post(
        "/api/agent/unknown-id/chat",
        json={"message": "Hello"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AD-430b: HXI conversation memory
# ---------------------------------------------------------------------------


def test_chat_with_history_passes_session_history(client, mock_runtime):
    """Chat with history sets session=True and passes session_history."""
    history = [
        {"role": "user", "text": "prev message"},
        {"role": "agent", "text": "prev response"},
    ]
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "follow up", "history": history},
    )
    assert resp.status_code == 200
    intent = mock_runtime.intent_bus.send.call_args[0][0]
    assert intent.params["session"] is True
    assert intent.params["session_history"] == history


def test_chat_without_history_session_false(client, mock_runtime):
    """Chat without history sets session=False and empty session_history."""
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "hello"},
    )
    assert resp.status_code == 200
    intent = mock_runtime.intent_bus.send.call_args[0][0]
    assert intent.params["session"] is False
    assert intent.params["session_history"] == []


def test_chat_history_capped_at_10(client, mock_runtime):
    """History is capped at 10 entries server-side."""
    history = [{"role": "user", "text": f"msg-{i}"} for i in range(25)]
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "latest", "history": history},
    )
    assert resp.status_code == 200
    intent = mock_runtime.intent_bus.send.call_args[0][0]
    assert len(intent.params["session_history"]) == 10
    # Should be the LAST 10
    assert intent.params["session_history"][0]["text"] == "msg-15"


def test_chat_stores_episode(client, mock_runtime):
    """HXI chat stores an episode in episodic memory."""
    mock_runtime.episodic_memory = MagicMock()
    mock_runtime.episodic_memory.store = AsyncMock()
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "Status report"},
    )
    assert resp.status_code == 200
    mock_runtime.episodic_memory.store.assert_called_once()
    episode = mock_runtime.episodic_memory.store.call_args[0][0]
    assert "[1:1 with" in episode.user_input
    assert "Status report" in episode.user_input
    assert episode.agent_ids == ["agent-123"]
    assert episode.outcomes[0]["source"] == "hxi_profile"
    assert episode.outcomes[0]["intent"] == "direct_message"


def test_chat_works_without_episodic_memory(client, mock_runtime):
    """Chat works fine when episodic_memory is None."""
    mock_runtime.episodic_memory = None
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "Hello"},
    )
    assert resp.status_code == 200
    assert "response" in resp.json()


def test_chat_episode_failure_does_not_block(client, mock_runtime):
    """Episode storage failure doesn't block the chat response."""
    mock_runtime.episodic_memory = MagicMock()
    mock_runtime.episodic_memory.store = AsyncMock(side_effect=RuntimeError("ChromaDB down"))
    resp = client.post(
        "/api/agent/agent-123/chat",
        json={"message": "Test message"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Hello Captain, reporting for duty."


def test_chat_history_recall_returns_memories(client, mock_runtime):
    """GET /api/agent/{id}/chat/history returns recalled memories."""
    mock_ep = MagicMock()
    mock_ep.user_input = "[1:1 with Wesley] Captain: How are you?"
    mock_runtime.episodic_memory = MagicMock()
    mock_runtime.episodic_memory.recall_for_agent = AsyncMock(return_value=[mock_ep])
    resp = client.get("/api/agent/agent-123/chat/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["memories"]) == 1
    assert "[Previous conversation]" in data["memories"][0]["text"]
    assert data["memories"][0]["role"] == "system"


def test_chat_history_recall_no_episodic_memory(client, mock_runtime):
    """GET /api/agent/{id}/chat/history returns empty when no episodic memory."""
    mock_runtime.episodic_memory = None
    resp = client.get("/api/agent/agent-123/chat/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["memories"] == []
