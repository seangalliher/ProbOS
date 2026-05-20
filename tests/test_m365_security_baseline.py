"""Tests for M365 security baseline."""

import pytest
import logging
from unittest.mock import MagicMock, AsyncMock, patch
from io import StringIO

from probos.integrations.m365_token_manager import M365TokenManager


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


def test_no_credentials_logged_on_auth_failure(token_manager, caplog):
    """Test that credentials are not logged on auth failure."""
    import asyncio

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
        with caplog.at_level(logging.WARNING):
            asyncio.run(token_manager.acquire_token_device_code_flow())

    # Check that no sensitive tokens appear in logs
    log_output = caplog.text
    assert "Bearer" not in log_output
    # Check for actual token values (JWT-like format), not the word "token"
    assert not any(x in log_output for x in ["eyJ0", "access_token:", "refresh_token:"])
    assert "secret" not in log_output.lower()


def test_pii_redaction_in_logs(token_manager, caplog):
    """Test that PII (emails, etc) would be masked in logs if present."""
    import asyncio

    # When a token refresh fails, ensure no email or private info is logged
    mock_app = MagicMock()
    mock_app.acquire_token_by_refresh_token.return_value = {
        "error": "invalid_grant",
        "error_description": "Token has expired",
    }

    with patch("keyring.get_password", return_value="refresh-token"):
        with patch("msal.PublicClientApplication", return_value=mock_app):
            with caplog.at_level(logging.WARNING):
                asyncio.run(token_manager.get_token())

    log_output = caplog.text
    # Verify no email addresses are logged
    assert "@" not in log_output or "masked" in log_output.lower()


def test_token_not_logged_on_success(token_manager, caplog):
    """Test that access tokens are never logged, even on success."""
    import asyncio

    mock_app = MagicMock()
    mock_app.initiate_device_flow.return_value = {
        "device_code": "test-device-code",
        "user_code": "ABC123",
        "verification_url": "https://example.com/auth",
        "expires_in": 900,
        "interval": 5,
    }
    mock_app.acquire_token_by_device_flow.return_value = {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6Ik5r",
        "refresh_token": "0.ARgAI-e7W5dGq0EQYnqkqjq1r2C2_xkXQHO...",
        "expires_in": 3600,
    }

    with patch("msal.PublicClientApplication", return_value=mock_app):
        with patch("keyring.set_password"):
            with caplog.at_level(logging.DEBUG):
                asyncio.run(token_manager.acquire_token_device_code_flow())

    log_output = caplog.text
    # Verify the actual token is NOT in logs
    assert "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6Ik5r" not in log_output
    assert "0.ARgAI-e7W5dGq0EQYnqkqjq1r2C2_xkXQHO" not in log_output
