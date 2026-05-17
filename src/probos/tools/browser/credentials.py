"""AD-706f: Browser Tool credential vault.

Encrypted-at-rest credential storage for authenticated browser flows. KEK
derived from ``AuthConfig.crew_scope_token`` via stdlib ``hashlib.scrypt``;
values encrypted via ``cryptography.fernet.Fernet`` (Apache-2.0/BSD).

Safety invariants:
* Vault values NEVER cross an LLM prompt — they flow only Vault -> Playwright
  ``page.fill()`` (fill_credential) or Vault -> tempfile -> ``page.set_input_files``
  (upload_file). Tier-3 always (Captain ACK every read).
* Per-credential capability scope: ``allowed_agent_ids`` + ``allowed_domains``
  + ``expires_at``.
* AuditLog row per read (handled at the BrowserTool layer, not in this module).
* Honest-degrade when ``AuthConfig.crew_scope_token`` is empty — vault
  construction raises ``RuntimeError`` with operator remediation message.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses + Protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CredentialScope:
    """Per-credential capability scope. Empty allowed_agent_ids = Captain-only."""
    allowed_agent_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_domains: frozenset[str] = field(default_factory=frozenset)
    expires_at: float | None = None  # Unix timestamp

    def is_expired(self, *, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or time.time()) >= self.expires_at

    def permits_agent(self, agent_id: str) -> bool:
        """Captain (empty set) OR explicit allow-list membership."""
        if not self.allowed_agent_ids:
            return agent_id == "captain"
        return agent_id in self.allowed_agent_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_agent_ids": sorted(self.allowed_agent_ids),
            "allowed_domains": sorted(self.allowed_domains),
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CredentialScope":
        return cls(
            allowed_agent_ids=frozenset(d.get("allowed_agent_ids") or []),
            allowed_domains=frozenset(d.get("allowed_domains") or []),
            expires_at=d.get("expires_at"),
        )


@dataclass(frozen=True)
class CredentialMetadata:
    """Returned by ``list_refs`` — NO value field."""
    ref: str
    scope: CredentialScope
    created_at: float
    last_read_at: float | None
    read_count: int


class CredentialVault(Protocol):
    """v1 credential-vault Protocol surface."""

    async def store(self, *, ref: str, value: str, scope: CredentialScope) -> None: ...
    async def read(self, *, ref: str, requesting_agent_id: str) -> str | None: ...
    async def materialize_to_temp(
        self, *, ref: str, requesting_agent_id: str
    ) -> Path | None: ...
    async def delete(self, *, ref: str) -> None: ...
    async def list_refs(self) -> list[CredentialMetadata]: ...


# ---------------------------------------------------------------------------
# KEK derivation
# ---------------------------------------------------------------------------


_KEK_SALT = b"probos-credential-vault-v1"
_KEK_SCRYPT_N = 2**14
_KEK_SCRYPT_R = 8
_KEK_SCRYPT_P = 1
_KEK_DKLEN = 32


def _derive_kek(crew_scope_token: str) -> bytes:
    """Derive a 32-byte KEK from the AD-722b-1 crew-scope token.

    Empty token derives a valid byte string deterministically but the vault
    constructor refuses to use it (operators MUST set a real token).
    """
    if not isinstance(crew_scope_token, str):
        raise TypeError("crew_scope_token must be a string")
    return hashlib.scrypt(
        crew_scope_token.encode("utf-8"),
        salt=_KEK_SALT,
        n=_KEK_SCRYPT_N,
        r=_KEK_SCRYPT_R,
        p=_KEK_SCRYPT_P,
        dklen=_KEK_DKLEN,
    )


# ---------------------------------------------------------------------------
# EncryptedFileCredentialVault (v1 backend)
# ---------------------------------------------------------------------------


class EncryptedFileCredentialVault:
    """v1 backend: JSON sidecar + Fernet symmetric encryption.

    On-disk format::

        {"refs": {ref: {"ciphertext": str, "scope": {...},
                          "created_at": float, "last_read_at": float | None,
                          "read_count": int}}}

    Atomic write via tmp+rename (matches AD-720d-2.1 / AD-721d-4 pattern).
    """

    def __init__(self, *, path: Path, kek: bytes, crew_scope_token: str) -> None:
        if not isinstance(kek, bytes) or len(kek) != _KEK_DKLEN:
            raise RuntimeError(
                f"AD-706f: invalid KEK length {len(kek) if isinstance(kek, bytes) else '?'}; "
                f"expected {_KEK_DKLEN} bytes from _derive_kek()"
            )
        if not crew_scope_token:
            raise RuntimeError(
                "AD-706f credential vault requires a non-empty "
                "auth.crew_scope_token. The KEK derivation needs a real "
                "operator secret. Set auth.crew_scope_token in config/system.yaml "
                "and restart, or set credential_vault.enabled=False to disable."
            )
        # Lazy import — cryptography is a v1 hard dep but keep import close to use.
        from cryptography.fernet import Fernet
        import base64

        self._path = Path(path)
        self._lock = threading.RLock()
        # Fernet expects a urlsafe-base64-encoded 32-byte key.
        self._fernet = Fernet(base64.urlsafe_b64encode(kek))
        self._refs: dict[str, dict[str, Any]] = {}
        self._load()

    # -- Persistence ------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._refs = data.get("refs", {}) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "AD-706f: credential vault file at %s is unreadable; starting "
                "with empty in-memory state (existing file preserved)",
                self._path,
                exc_info=True,
            )
            self._refs = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"refs": self._refs}, fh, indent=2)
        os.replace(tmp, self._path)

    # -- Protocol surface -------------------------------------------------

    async def store(self, *, ref: str, value: str, scope: CredentialScope) -> None:
        def _do() -> None:
            with self._lock:
                ciphertext = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
                self._refs[ref] = {
                    "ciphertext": ciphertext,
                    "scope": scope.to_dict(),
                    "created_at": time.time(),
                    "last_read_at": None,
                    "read_count": 0,
                }
                self._save()
        await asyncio.get_running_loop().run_in_executor(None, _do)

    async def read(self, *, ref: str, requesting_agent_id: str) -> str | None:
        def _do() -> str | None:
            with self._lock:
                entry = self._refs.get(ref)
                if entry is None:
                    return None
                scope = CredentialScope.from_dict(entry.get("scope") or {})
                if scope.is_expired():
                    return None
                if not scope.permits_agent(requesting_agent_id):
                    return None
                # Decrypt
                from cryptography.fernet import InvalidToken
                try:
                    plaintext = self._fernet.decrypt(
                        entry["ciphertext"].encode("ascii")
                    ).decode("utf-8")
                except (InvalidToken, KeyError):
                    logger.warning(
                        "AD-706f: credential %s failed to decrypt (KEK rotated?)",
                        ref,
                    )
                    return None
                entry["last_read_at"] = time.time()
                entry["read_count"] = int(entry.get("read_count", 0)) + 1
                self._save()
                return plaintext
        return await asyncio.get_running_loop().run_in_executor(None, _do)

    async def materialize_to_temp(
        self, *, ref: str, requesting_agent_id: str
    ) -> Path | None:
        """Decrypt to a tempfile. CALLER MUST UNLINK in finally."""
        plaintext = await self.read(ref=ref, requesting_agent_id=requesting_agent_id)
        if plaintext is None:
            return None
        # Write synchronously — tempfile creation is fast and we want the path
        # back immediately so the caller can hand it to Playwright.
        fd, tmp_path = tempfile.mkstemp(prefix="probos-cred-", suffix=".bin")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(plaintext)
        except Exception:
            os.unlink(tmp_path)
            raise
        return Path(tmp_path)

    async def delete(self, *, ref: str) -> None:
        def _do() -> None:
            with self._lock:
                if ref in self._refs:
                    del self._refs[ref]
                    self._save()
        await asyncio.get_running_loop().run_in_executor(None, _do)

    async def list_refs(self) -> list[CredentialMetadata]:
        def _do() -> list[CredentialMetadata]:
            with self._lock:
                out: list[CredentialMetadata] = []
                for ref, entry in self._refs.items():
                    out.append(CredentialMetadata(
                        ref=ref,
                        scope=CredentialScope.from_dict(entry.get("scope") or {}),
                        created_at=float(entry.get("created_at", 0.0)),
                        last_read_at=entry.get("last_read_at"),
                        read_count=int(entry.get("read_count", 0)),
                    ))
                return out
        return await asyncio.get_running_loop().run_in_executor(None, _do)


# ---------------------------------------------------------------------------
# fill_credential action (registered into _HANDLERS by actions.py late-bind)
# ---------------------------------------------------------------------------


async def action_fill_credential(
    session: Any,
    params: dict[str, Any],
    *,
    runtime: Any,
    emit_event: Any,
) -> dict[str, Any]:
    """AD-706f: Vault -> Playwright page.fill(). Tier-3 always.

    Returns ``{ok: bool, skipped_reason, ...}``. Tier-2 honest-degrade; never raises.
    """
    from probos.events import EventType
    from urllib.parse import urlparse

    selector = params.get("selector")
    ref = params.get("credential_ref")
    agent_id = params.get("agent_id") or getattr(session, "_agent_id", "")  # noqa: SLF001

    if not selector or not isinstance(selector, str):
        return {"ok": False, "skipped_reason": "missing_selector"}
    if not ref or not isinstance(ref, str):
        return {"ok": False, "skipped_reason": "missing_credential_ref"}

    vault = getattr(runtime, "credential_vault", None)
    if vault is None:
        return {
            "ok": False,
            "skipped_reason": "credential_vault_unavailable",
            "message": "AD-706f credential vault not configured on this runtime",
        }

    cfg = getattr(runtime, "config", None)
    browser_cfg = getattr(cfg, "browser_tool", None)
    vault_cfg = getattr(browser_cfg, "credential_vault", None) if browser_cfg else None
    require_https = bool(getattr(vault_cfg, "require_https_for_fill", True))

    last_url = getattr(session, "last_url", "") or ""
    parsed = urlparse(last_url)
    if require_https and parsed.scheme and parsed.scheme != "https":
        return {
            "ok": False,
            "skipped_reason": "https_required",
            "message": f"credential fill blocked: page scheme is {parsed.scheme!r}, require_https_for_fill=True",
        }

    # Domain-scope check: read metadata first to inspect scope before decrypting.
    refs_meta = await vault.list_refs()
    meta = next((m for m in refs_meta if m.ref == ref), None)
    if meta is None:
        if emit_event is not None:
            try:
                emit_event(
                    EventType.CREDENTIAL_READ_DENIED,
                    {"ref": ref, "agent_id": agent_id, "reason": "unknown_ref"},
                )
            except Exception:
                logger.debug("AD-706f: emit_event(CREDENTIAL_READ_DENIED) failed", exc_info=True)
        return {"ok": False, "skipped_reason": "unknown_ref"}

    host = (parsed.hostname or "").lower()
    if meta.scope.allowed_domains and host:
        import fnmatch
        if not any(fnmatch.fnmatchcase(host, pat.lower()) for pat in meta.scope.allowed_domains):
            if emit_event is not None:
                try:
                    emit_event(
                        EventType.CREDENTIAL_READ_DENIED,
                        {"ref": ref, "agent_id": agent_id, "reason": "domain_mismatch", "host": host},
                    )
                except Exception:
                    logger.debug("AD-706f: emit_event(CREDENTIAL_READ_DENIED) failed", exc_info=True)
            return {"ok": False, "skipped_reason": "domain_mismatch"}

    value = await vault.read(ref=ref, requesting_agent_id=agent_id)
    if value is None:
        if emit_event is not None:
            try:
                emit_event(
                    EventType.CREDENTIAL_READ_DENIED,
                    {"ref": ref, "agent_id": agent_id, "reason": "scope_denied_or_expired"},
                )
            except Exception:
                logger.debug("AD-706f: emit_event(CREDENTIAL_READ_DENIED) failed", exc_info=True)
        return {"ok": False, "skipped_reason": "credential_denied"}

    page = getattr(session, "page", None)
    if page is None:
        return {"ok": False, "skipped_reason": "session_not_started"}

    try:
        await page.fill(selector, value)
    except Exception:
        logger.warning("AD-706f: page.fill failed for %s", selector, exc_info=True)
        return {"ok": False, "skipped_reason": "fill_error"}

    if emit_event is not None:
        try:
            emit_event(
                EventType.CREDENTIAL_READ,
                {"ref": ref, "agent_id": agent_id},
            )
            emit_event(
                EventType.CREDENTIAL_FILL_REQUESTED,
                {"ref": ref, "agent_id": agent_id, "selector": selector, "host": host},
            )
        except Exception:
            logger.debug("AD-706f: emit_event for fill failed", exc_info=True)

    return {"ok": True, "selector": selector, "ref": ref}
