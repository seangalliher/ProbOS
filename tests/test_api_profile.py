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
