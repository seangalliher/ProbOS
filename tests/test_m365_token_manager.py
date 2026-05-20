"""Tests for M365TokenManager."""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timedelta, timezone

from probos.integrations.m365_token_manager import M365TokenManager, KEYRING_SERVICE, KEYRING_USERNAME


@pytest.fixture
def mock_m365_config():
    """Mock M365Config."""
    config = MagicMock()
    config.client_id = "test-client-id"
    config.authority = "https://login.microsoftonline.com/common"
    config.scopes = ["https://graph.microsoft.com/.default"]
    return config


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Temporary cache directory."""
    return str(tmp_path / ".m365_cache")


@pytest.fixture
def token_manager(mock_m365_config, temp_cache_dir):
    """Create M365TokenManager instance."""
    return M365TokenManager(cache_dir=temp_cache_dir, config=mock_m365_config)


@pytest.mark.asyncio
async def test_acquire_token_device_code_flow_success(token_manager):
    """Test successful device-code flow token acquisition."""
    mock_app = MagicMock()
    mock_app.initiate_device_flow.return_value = {
        "device_code": "test-device-code",
        "user_code": "ABC123",
        "verification_url": "https://example.com/auth",
        "expires_in": 900,
        "interval": 5,
    }
    mock_app.acquire_token_by_device_flow.return_value = {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_in": 3600,
    }

    with patch("msal.PublicClientApplication", return_value=mock_app):
        with patch("keyring.set_password"):
            token = await token_manager.acquire_token_device_code_flow()

    assert token == "test-access-token"
    assert token_manager._cached_token is not None


@pytest.mark.asyncio
async def test_acquire_token_device_code_flow_no_user_code(token_manager):
    """Test device-code flow when no user_code is returned."""
    mock_app = MagicMock()
    mock_app.initiate_device_flow.return_value = {}  # Missing user_code

    with patch("msal.PublicClientApplication", return_value=mock_app):
        token = await token_manager.acquire_token_device_code_flow()

    assert token is None


@pytest.mark.asyncio
async def test_acquire_token_device_code_flow_no_access_token(token_manager):
    """Test device-code flow when auth returns no access token."""
    mock_app = MagicMock()
    mock_app.initiate_device_flow.return_value = {
        "device_code": "test-device-code",
        "user_code": "ABC123",
        "verification_url": "https://example.com/auth",
    }
    mock_app.acquire_token_by_device_flow.return_value = {
        "error": "authorization_pending",
    }

    with patch("msal.PublicClientApplication", return_value=mock_app):
        token = await token_manager.acquire_token_device_code_flow()

    assert token is None


@pytest.mark.asyncio
async def test_get_token_from_cache(token_manager):
    """Test getting token from cache when still valid."""
    token_manager._cached_token = {"access_token": "cached-token"}
    token_manager._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    token = await token_manager.get_token()

    assert token == "cached-token"


@pytest.mark.asyncio
async def test_get_token_refresh_when_expired(token_manager):
    """Test token refresh when cached token is expired."""
    token_manager._cached_token = {"access_token": "old-token"}
    token_manager._token_expiry = datetime.now(timezone.utc) - timedelta(seconds=60)

    mock_app = MagicMock()
    mock_app.acquire_token_by_refresh_token.return_value = {
        "access_token": "new-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    }

    with patch("keyring.get_password", return_value="refresh-token"):
        with patch("msal.PublicClientApplication", return_value=mock_app):
            token = await token_manager.get_token()

    assert token == "new-token"


@pytest.mark.asyncio
async def test_get_token_no_refresh_token(token_manager):
    """Test get_token when no refresh token is available."""
    with patch("keyring.get_password", return_value=None):
        token = await token_manager.get_token()

    assert token is None


@pytest.mark.asyncio
async def test_revoke_token(token_manager):
    """Test token revocation."""
    token_manager._cached_token = {"access_token": "test-token"}
    token_manager._token_expiry = datetime.now(timezone.utc)

    with patch("keyring.delete_password"):
        token_manager.revoke()

    assert token_manager._cached_token is None
    assert token_manager._token_expiry is None
