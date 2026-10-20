"""BF-908: keyring ducks for the crew-scope token tests. Never the OS keyring (tests/conftest.py)."""

from __future__ import annotations

import threading
from typing import Any

import keyring.errors

from probos.credential_store import CredentialStore
from probos.security.crew_scope import (
    CREW_SCOPE_KEYRING_SERVICE,
    CREW_SCOPE_KEYRING_USERNAME,
    CrewScopeKeyring,
)

#: Synthetic tokens (16+ printable ASCII characters). No real token is in this tree.
KEYRING_TOKEN = "bf908-synthetic-keyring-token-7d3"
FILE_TOKEN = "bf908-synthetic-file-token-a41"
ROTATED_TOKEN = "bf908-synthetic-rotated-token-5e2"
ENTRY = (CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)


class MemoryKeyring:
    """A recommended (priority 5) in-memory backend, duck-typed as AD-1196's tests do."""

    def __init__(self, priority: float = 5, *, token: str | None = None) -> None:
        self.priority = priority
        self.entries: dict[tuple[str, str], str] = {}
        if token is not None:
            self.entries[ENTRY] = token

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.entries.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError("no such entry")


class InsecureKeyring(MemoryKeyring):
    """Priority 0: never recommended, so the host has no secure backend."""

    def __init__(self, *, token: str | None = None) -> None:
        super().__init__(priority=0, token=token)


class FailingKeyring(MemoryKeyring):
    """A recommended backend whose every call raises, as a locked or broken keychain does."""

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("keychain locked")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("keychain locked")

    def delete_password(self, service: str, username: str) -> None:
        raise RuntimeError("keychain locked")


class ForgetfulKeyring(MemoryKeyring):
    """A recommended backend that accepts a write and keeps nothing."""

    def set_password(self, service: str, username: str, password: str) -> None:
        return None


class SilentKeyring(MemoryKeyring):
    """A recommended backend whose read blocks until released (a keychain prompt nobody answers)."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def get_password(self, service: str, username: str) -> str | None:
        self.release.wait(5)
        return None


#: The text a refusing duck's deletion error carries; no message may contain it (the type only, D16).
DENIAL_DETAIL = "bf908-synthetic-denial-detail"


class RefusingDeleteKeyring(MemoryKeyring):
    """A recommended backend whose deletion is refused while the entry stays, as macOS reports a denied keychain.

    keyring's macOS backend raises ``PasswordDeleteError`` for every ``api.Error`` from a deletion,
    ``KeychainDenied`` included (``keyring/backends/macOS/__init__.py``), so that error alone does not mean
    "none was there" (BF-908 A2, D22). ``MemoryKeyring`` raises it only when the entry is absent.
    """

    def delete_password(self, service: str, username: str) -> None:
        raise keyring.errors.PasswordDeleteError(f"Can't delete password in keychain: {DENIAL_DETAIL}")


class LockedDeleteKeyring(RefusingDeleteKeyring):
    """A refused deletion whose read-back fails too (a keychain that locked between the calls)."""

    def get_password(self, service: str, username: str) -> str | None:
        raise keyring.errors.KeyringLocked(DENIAL_DETAIL)


async def loaded_store(config: Any, backend: Any, *, config_path: str | None = None) -> CredentialStore:
    """A real CredentialStore whose keyring step reads ``backend`` once, as startup does."""
    store = CredentialStore(config=config)
    store.crew_scope = CrewScopeKeyring(backend=backend)
    await store.crew_scope.load(config=config, config_path=config_path)
    return store
