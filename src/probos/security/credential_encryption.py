"""AD-754: system-keyring credential encryption utilities."""

from __future__ import annotations

import logging

import keyring

logger = logging.getLogger(__name__)


class CredentialEncryptor:
    """Platform-aware credential storage via the OS keyring."""

    def __init__(self, app_name: str = "ProbOS") -> None:
        """Initialize keyring namespace for this application."""
        self._service_name = app_name

    def store(self, key: str, value: str) -> None:
        """Encrypt and store a credential value in the system keyring."""
        if not key:
            raise ValueError("credential key must be non-empty")
        keyring.set_password(self._service_name, key, value)

    def retrieve(self, key: str) -> str | None:
        """Retrieve and decrypt a credential from the system keyring."""
        if not key:
            raise ValueError("credential key must be non-empty")
        try:
            return keyring.get_password(self._service_name, key)
        except Exception:
            logger.warning(
                "AD-754: keyring retrieve failed for key=%s; returning no credential",
                key,
                exc_info=True,
            )
            return None

    def delete(self, key: str) -> None:
        """Delete a credential from the system keyring."""
        if not key:
            raise ValueError("credential key must be non-empty")
        try:
            keyring.delete_password(self._service_name, key)
        except keyring.errors.PasswordDeleteError:
            logger.debug(
                "AD-754: keyring delete requested for missing key=%s; nothing to remove",
                key,
            )
