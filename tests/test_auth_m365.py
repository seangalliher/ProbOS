"""Tests for M365 auth routes."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from probos.routers.auth_m365 import router


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_config():
    """Mock config."""
    config = MagicMock()
    config.m365.enabled = True
    config.m365.client_id = "test-client-id"
    config.m365.authority = "https://login.microsoftonline.com/common"
    config.m365.scopes = ["https://graph.microsoft.com/.default"]
    return config


def test_authorize_m365_disabled(client):
    """Test authorize endpoint when M365 is disabled."""
    mock_runtime = MagicMock()
    mock_runtime.config.m365.enabled = False
    client.app.state.runtime = mock_runtime

    response = client.post("/auth/m365/authorize")
    assert response.status_code == 400
    assert "not enabled" in response.json()["detail"]


def test_authorize_m365_no_client_id(client):
    """Test authorize endpoint when client_id is missing."""
    mock_runtime = MagicMock()
    mock_runtime.config.m365.enabled = True
    mock_runtime.config.m365.client_id = None
    client.app.state.runtime = mock_runtime

    response = client.post("/auth/m365/authorize")
    assert response.status_code == 400
    assert "client_id" in response.json()["detail"]


def test_authorize_m365_success(client, mock_config):
    """Test successful authorize endpoint."""
    mock_runtime = MagicMock()
    mock_runtime.config = mock_config
    mock_runtime._m365_device_flows = {}
    client.app.state.runtime = mock_runtime

    mock_app = MagicMock()
    mock_app.initiate_device_flow.return_value = {
        "device_code": "test-device-code",
        "user_code": "ABC123",
        "verification_url": "https://example.com/auth",
        "expires_in": 900,
        "interval": 5,
    }

    with patch("msal.PublicClientApplication", return_value=mock_app):
        response = client.post("/auth/m365/authorize")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "device_code_initiated"
    assert data["user_code"] == "ABC123"
    assert "verification_uri" in data


def test_complete_m365_no_device_code(client):
    """Test complete endpoint without device_code."""
    mock_runtime = MagicMock()
    client.app.state.runtime = mock_runtime

    response = client.post("/auth/m365/complete", json={})
    assert response.status_code == 400
    assert "device_code" in response.json()["detail"]


def test_complete_m365_unknown_flow(client):
    """Test complete endpoint with unknown device_code."""
    mock_runtime = MagicMock()
    mock_runtime._m365_device_flows = {}
    client.app.state.runtime = mock_runtime

    response = client.post("/auth/m365/complete", json={"device_code": "unknown"})
    assert response.status_code == 400
    assert "Unknown device_code" in response.json()["detail"]
