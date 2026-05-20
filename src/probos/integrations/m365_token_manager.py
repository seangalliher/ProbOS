"""Microsoft 365 OAuth token lifecycle management."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import keyring

logger = logging.getLogger(__name__)

# Keyring service and username for token storage
KEYRING_SERVICE = "probos.m365"
KEYRING_USERNAME = "refresh_token"


class M365TokenManager:
    """Manages OAuth token lifecycle for M365 personal account.
    
    Stores refresh tokens in system keyring (Windows DPAPI, macOS Keychain, Linux libsecret).
    Never logs credentials or tokens.
    """

    def __init__(self, cache_dir: str, config: Any) -> None:
        """Initialize token manager with local cache.
        
        Args:
            cache_dir: Directory for token storage (encrypted via system keyring).
            config: M365Config with client_id, authority, scopes.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config = config
        self._cached_token: dict[str, Any] | None = None
        self._token_expiry: datetime | None = None
        logger.info("M365TokenManager initialized with cache_dir=%s", self.cache_dir)

    async def acquire_token_device_code_flow(self) -> str | None:
        """Device-code OAuth flow for personal accounts.
        
        Returns:
            Access token (valid for Outlook/Teams/Calendar/SharePoint/OneDrive).
            None on auth failure (logs warning without sensitive data).
        """
        try:
            import msal
        except ImportError:
            logger.error("msal library not installed; install via 'pip install msal'")
            return None

        try:
            app = msal.PublicClientApplication(
                self.config.client_id,
                authority=self.config.authority,
            )
            
            # Device-code flow
            flow = app.initiate_device_flow(scopes=self.config.scopes)
            if "user_code" not in flow:
                logger.warning("M365 device-code flow failed; no user_code received")
                return None

            logger.info(
                "M365 device-code flow initiated. User must visit the provided URL and enter the code."
            )

            # In a real implementation, this would return the flow info to the caller
            # to display the URL and user code. For now, we'll just log it.
            result = app.acquire_token_by_device_flow(flow)

            if "access_token" in result:
                # Store refresh token in keyring if available
                if "refresh_token" in result:
                    try:
                        keyring.set_password(
                            KEYRING_SERVICE, KEYRING_USERNAME, result["refresh_token"]
                        )
                        logger.info("M365 refresh token securely stored in system keyring")
                    except Exception:
                        logger.warning(
                            "Failed to store M365 refresh token in keyring; "
                            "tokens will not persist across restarts"
                        )

                # Cache the access token with expiry
                self._cached_token = result
                expires_in = result.get("expires_in", 3600)
                self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                logger.info("M365 access token acquired (expires in %d seconds)", expires_in)
                return result["access_token"]

            logger.warning(
                "M365 device-code flow auth failed (likely user declined or timeout); "
                "system will degrade gracefully"
            )
            return None

        except Exception:
            logger.exception("M365 device-code flow error; no credentials logged")
            return None

    async def get_token(self, scope: str = "https://graph.microsoft.com/.default") -> str | None:
        """Get cached token or refresh if expired.
        
        Stores raw refresh_token in system keyring (Windows DPAPI / macOS Keychain / Linux libsecret).
        Never logs credentials or tokens.
        
        Args:
            scope: OAuth scope (default: Microsoft Graph API).
            
        Returns:
            Access token or None if unavailable/expired.
        """
        # Check if cached token is still valid
        if self._cached_token and self._token_expiry:
            if datetime.now(timezone.utc) < self._token_expiry - timedelta(seconds=60):
                # Token still valid (with 60s safety margin)
                return self._cached_token.get("access_token")

        # Try to refresh using stored refresh token
        try:
            import msal
        except ImportError:
            logger.error("msal library not installed")
            return None

        try:
            refresh_token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            if not refresh_token:
                logger.warning(
                    "No M365 refresh token available in keyring; "
                    "run acquire_token_device_code_flow() first"
                )
                return None

            app = msal.PublicClientApplication(
                self.config.client_id,
                authority=self.config.authority,
            )

            result = app.acquire_token_by_refresh_token(refresh_token, scopes=[scope])

            if "access_token" in result:
                # Update cached token
                self._cached_token = result
                expires_in = result.get("expires_in", 3600)
                self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                logger.debug("M365 token refreshed (expires in %d seconds)", expires_in)
                return result["access_token"]

            logger.warning(
                "M365 token refresh failed (refresh token may have expired); "
                "will need to re-authenticate"
            )
            return None

        except Exception:
            logger.exception("M365 token refresh error; no credentials logged")
            return None

    def revoke(self) -> None:
        """User-initiated token erasure ('forget this' flow)."""
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
            logger.info("M365 refresh token revoked from keyring")
        except keyring.errors.PasswordDeleteError:
            logger.debug("M365 refresh token not found in keyring (already revoked or not set)")
        except Exception:
            logger.exception("Error revoking M365 refresh token")

        self._cached_token = None
        self._token_expiry = None
