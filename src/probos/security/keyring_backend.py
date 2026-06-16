"""AD-1016: OS-keychain credential backend.

A second :class:`~probos.tools.browser.credentials.CredentialVault` backend that
stores secret *values* in the operating-system keychain (Windows DPAPI / macOS
Keychain / Linux libsecret) via :class:`CredentialEncryptor` (AD-754), and keeps
a **non-secret metadata sidecar** on disk so the vault can enumerate refs and
enforce per-credential scope (the OS keychain is a ``service+username -> value``
KV store with no list and no metadata).

This backend is structurally substitutable for
:class:`~probos.tools.browser.credentials.EncryptedFileCredentialVault`: same
Protocol method names, keyword-only signatures, and return types.

Crew-token gating decision (AD-1016, RESOLVED):
    The file vault derives a Fernet KEK from ``auth.crew_scope_token`` and refuses
    to construct without it. The keychain backend's secrecy is the **OS keychain
    itself** (already encrypted at rest by the OS), and the sidecar holds *no*
    secret values. Therefore this backend requires ``credential_vault.enabled``
    but does **not** require ``crew_scope_token``. Startup gates each backend
    accordingly (file -> needs token; keychain -> token optional).

Safety invariants:
* Secret values live ONLY in the OS keychain. The sidecar JSON holds metadata
  only (scope, created_at, last_read_at, read_count) — never a value.
* Honest-degrade: when the keyring is unavailable (``NoKeyringError`` or any
  backend error), reads/lists return ``None``/``[]`` and the backend never
  crashes the runtime. ``store`` raises a clear error so the caller knows the
  credential did not persist.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from probos.security.credential_encryption import CredentialEncryptor
from probos.tools.browser.credentials import CredentialMetadata, CredentialScope

logger = logging.getLogger(__name__)


class KeyringCredentialBackend:
    """OS-keychain credential backend with a non-secret metadata sidecar.

    Sidecar on-disk format (values NEVER stored here)::

        {"refs": {ref: {"scope": {...}, "created_at": float,
                          "last_read_at": float | None, "read_count": int}}}

    Atomic write via tmp+rename, guarded by a process-local ``threading.RLock``
    (mirrors ``EncryptedFileCredentialVault``). Secret values are stored in /
    retrieved from the OS keychain through :class:`CredentialEncryptor`.
    """

    def __init__(
        self,
        *,
        service_name: str,
        index_path: Path,
        encryptor: CredentialEncryptor | None = None,
    ) -> None:
        self._service_name = service_name
        self._index_path = Path(index_path)
        # Secret values flow only through the OS keychain via the encryptor.
        self._encryptor = encryptor or CredentialEncryptor(app_name=service_name)
        self._lock = threading.RLock()
        self._refs: dict[str, dict[str, Any]] = {}
        self._load()

    # -- Sidecar persistence (metadata only, no secret values) ------------

    def _load(self) -> None:
        if not self._index_path.exists():
            return
        try:
            with open(self._index_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._refs = data.get("refs", {}) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "AD-1016: keychain sidecar at %s is unreadable; starting with "
                "empty in-memory metadata (existing file preserved)",
                self._index_path,
                exc_info=True,
            )
            self._refs = {}

    def _save(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._index_path.with_suffix(self._index_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"refs": self._refs}, fh, indent=2)
        os.replace(tmp, self._index_path)

    # -- Sidecar helpers (run inside asyncio.to_thread; hold the lock) -----

    def _write_metadata(self, ref: str, scope_dict: dict[str, Any]) -> None:
        with self._lock:
            self._refs[ref] = {
                "scope": scope_dict,
                "created_at": time.time(),
                "last_read_at": None,
                "read_count": 0,
            }
            self._save()

    def _bump_read(self, ref: str) -> None:
        with self._lock:
            entry = self._refs.get(ref)
            if entry is None:
                return
            entry["last_read_at"] = time.time()
            entry["read_count"] = int(entry.get("read_count", 0)) + 1
            self._save()

    def _drop_metadata(self, ref: str) -> None:
        with self._lock:
            if ref in self._refs:
                del self._refs[ref]
                self._save()

    def _snapshot_refs(self) -> list[CredentialMetadata]:
        with self._lock:
            out: list[CredentialMetadata] = []
            for ref, entry in self._refs.items():
                out.append(
                    CredentialMetadata(
                        ref=ref,
                        scope=CredentialScope.from_dict(entry.get("scope") or {}),
                        created_at=float(entry.get("created_at", 0.0)),
                        last_read_at=entry.get("last_read_at"),
                        read_count=int(entry.get("read_count", 0)),
                    )
                )
            return out

    def _scope_for(self, ref: str) -> CredentialScope | None:
        with self._lock:
            entry = self._refs.get(ref)
            if entry is None:
                return None
            return CredentialScope.from_dict(entry.get("scope") or {})

    # -- Protocol surface -------------------------------------------------

    async def store(self, *, ref: str, value: str, scope: CredentialScope) -> None:
        # Keyring write FIRST so the sidecar only ever records persisted
        # credentials (a failed keyring write leaves no orphan metadata). If the
        # keyring is unavailable, surface a clear error — the caller must know
        # the credential did not persist.
        # NOTE: max_credentials enforcement is not wired at this layer (parity
        # with EncryptedFileCredentialVault, which also does not enforce it).
        try:
            await asyncio.to_thread(self._encryptor.store, ref, value)
        except Exception as exc:  # NoKeyringError / PasswordSetError / etc.
            raise RuntimeError(
                f"AD-1016: failed to persist credential {ref!r} to the OS "
                f"keychain (service={self._service_name!r}): {exc}. The "
                f"credential was NOT stored."
            ) from exc
        await asyncio.to_thread(self._write_metadata, ref, scope.to_dict())

    async def read(self, *, ref: str, requesting_agent_id: str) -> str | None:
        scope = await asyncio.to_thread(self._scope_for, ref)
        if scope is None:
            return None
        if scope.is_expired():
            return None
        if not scope.permits_agent(requesting_agent_id):
            return None
        try:
            value = await asyncio.to_thread(self._encryptor.retrieve, ref)
        except Exception:
            logger.warning(
                "AD-1016: keychain read failed for %s; degrading to no "
                "credential (runtime not impacted)",
                ref,
                exc_info=True,
            )
            return None
        if value is None:
            return None
        await asyncio.to_thread(self._bump_read, ref)
        return value

    async def materialize_to_temp(
        self, *, ref: str, requesting_agent_id: str
    ) -> Path | None:
        """Read the value to a 0600 tempfile. CALLER MUST UNLINK in finally."""
        plaintext = await self.read(ref=ref, requesting_agent_id=requesting_agent_id)
        if plaintext is None:
            return None
        fd, tmp_path = tempfile.mkstemp(prefix="probos-cred-", suffix=".bin")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(plaintext)
            # mkstemp creates 0600 on POSIX; make the intent explicit (best-effort
            # on Windows, where POSIX modes are not honored).
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                logger.debug(
                    "AD-1016: chmod 0600 on temp credential file failed "
                    "(non-POSIX platform?)",
                    exc_info=True,
                )
        except Exception:
            os.unlink(tmp_path)
            raise
        return Path(tmp_path)

    async def delete(self, *, ref: str) -> None:
        try:
            await asyncio.to_thread(self._encryptor.delete, ref)
        except Exception:
            logger.warning(
                "AD-1016: keychain delete failed for %s; dropping the sidecar "
                "entry anyway (runtime not impacted)",
                ref,
                exc_info=True,
            )
        await asyncio.to_thread(self._drop_metadata, ref)

    async def list_refs(self) -> list[CredentialMetadata]:
        return await asyncio.to_thread(self._snapshot_refs)
