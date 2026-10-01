"""AD-1196: where the ship's identity private key lives.

:class:`IdentityKeyStore` is the narrow protocol the key binding depends on --
the extension point for other stores. Two implementations:

* :class:`KeyringKeyStore` -- the OS keyring, through a *recommended* (secure)
  backend only. A ``ChainerBackend`` is replaced by its first recommended member
  and never called through, because a chained miss falls through to whatever
  insecure backend answers. Every backend failure is :class:`KeyStoreUnavailable`
  -- fail closed, never read as "missing" -- and every call is bounded in time,
  so a locked keychain prompt cannot hang boot.
* :class:`PlaintextDevKeyStore` -- unencrypted files, only when explicitly
  configured for development, with a loud warning. Never a fallback.

Private keys leave a store only as the signatures it returns.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from probos.identity_keys import KeyStoreUnavailable, key_id

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass(frozen=True)
class KeyStoreStatus:
    """What a key store reports about itself. Carries no key material."""

    kind: str
    backend: str
    secure: bool
    available: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready copy."""
        return asdict(self)


class IdentityKeyStore(Protocol):
    """Holds identity private keys; hands out only public keys and signatures."""

    async def describe(self) -> KeyStoreStatus:
        """The store's kind, backend and availability."""
        ...

    async def create(self, did: str) -> tuple[str, str]:
        """Generate and persist a new key for ``did``; return ``(kid, public_key_b64)``."""
        ...

    async def public_key(self, kid: str) -> str | None:
        """The public key of the entry under ``kid``, or ``None`` when there is no entry."""
        ...

    async def sign(self, kid: str, message: str) -> str:
        """Sign ``message`` with the key under ``kid``, read from the store on every call; standard base64."""
        ...


def _qualified_name(backend: Any) -> str:
    kind = type(backend)
    return f"{kind.__module__}.{kind.__qualname__}"


def _priority(backend: Any) -> str:
    try:
        return f"{float(backend.priority):g}"
    except (AttributeError, TypeError, ValueError):
        return "unknown"


def _require_recommended(backend: Any) -> Any:
    import keyring.core

    if not keyring.core.recommended(backend):
        raise KeyStoreUnavailable(
            f"keyring backend {_qualified_name(backend)} (priority {_priority(backend)}) is not a "
            "recommended secure backend; identity keys are never stored on it"
        )
    return backend


class KeyringKeyStore:
    """Identity private keys in the OS keyring, through a recommended backend only."""

    def __init__(
        self,
        backend: Any | None = None,
        *,
        service_prefix: str = "probos.identity",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._backend = backend
        self._service_prefix = service_prefix
        self._timeout_seconds = timeout_seconds

    async def describe(self) -> KeyStoreStatus:
        """Resolve the backend; report it, or why no secure backend is available."""
        try:
            backend = await self._call(lambda backend: backend)
        except KeyStoreUnavailable as exc:
            return KeyStoreStatus(kind="keyring", backend="", secure=False, available=False, reason=str(exc))
        return KeyStoreStatus(
            kind="keyring", backend=_qualified_name(backend), secure=True, available=True, reason="",
        )

    async def create(self, did: str) -> tuple[str, str]:
        """Generate a key, store it, and read it back before trusting it."""
        from probos.substrate.device_pairing import encode_private_key, encode_public_key, generate_keypair

        private_key, public_key = generate_keypair()
        kid = key_id(did, public_key)
        secret = encode_private_key(private_key)
        service = f"{self._service_prefix}:{kid}"
        await self._call(lambda backend: backend.set_password(service, kid, secret))
        stored = await self._load(kid)
        if stored is None or encode_public_key(stored.public_key()) != public_key:
            raise KeyStoreUnavailable(f"the keyring backend did not persist {kid}")
        return kid, public_key

    async def public_key(self, kid: str) -> str | None:
        """The stored entry's public key, read from the backend (``None`` when absent)."""
        from probos.substrate.device_pairing import encode_public_key

        private_key = await self._load(kid)
        if private_key is None:
            return None
        return encode_public_key(private_key.public_key())

    async def sign(self, kid: str, message: str) -> str:
        """Sign with the key under ``kid``, read from the backend on every call."""
        from probos.substrate.device_pairing import sign_challenge

        private_key = await self._load(kid)
        if private_key is None:  # AD-1196 A-1 keyring re-read
            raise KeyStoreUnavailable(f"no private key is stored for {kid}")
        return sign_challenge(private_key, message)

    def _resolve_backend(self) -> Any:
        """The secure backend for this call (runs in the worker thread)."""
        import keyring
        import keyring.core
        from keyring.backends.chainer import ChainerBackend

        backend = self._backend if self._backend is not None else keyring.get_keyring()
        if not isinstance(backend, ChainerBackend):
            return _require_recommended(backend)
        candidates = [b for b in backend.backends if keyring.core.recommended(b)]
        if not candidates:
            raise KeyStoreUnavailable(
                "no chained keyring backend is recommended (secure): "
                + ", ".join(f"{_qualified_name(b)} (priority {_priority(b)})" for b in backend.backends)
            )
        backend = candidates[0]
        return _require_recommended(backend)

    async def _call(self, action: Callable[[Any], _T]) -> _T:
        """Run ``action(backend)`` off the loop under the time bound; any failure is unavailability."""

        def run() -> _T:
            return action(self._resolve_backend())

        try:
            return await asyncio.wait_for(asyncio.to_thread(run), timeout=self._timeout_seconds)
        except KeyStoreUnavailable:
            raise
        except TimeoutError:
            raise KeyStoreUnavailable(
                f"the keyring backend did not answer within {self._timeout_seconds:g} s"
            ) from None
        except Exception as exc:  # noqa: BLE001 -- fail closed: a failing backend is unavailable, never "missing"
            raise KeyStoreUnavailable(f"the keyring backend failed ({type(exc).__name__})") from None

    async def _load(self, kid: str) -> Any | None:
        from probos.substrate.device_pairing import decode_private_key

        service = f"{self._service_prefix}:{kid}"
        stored = await self._call(lambda backend: backend.get_password(service, kid))
        if stored is None:
            return None
        try:
            return decode_private_key(stored)
        except ValueError:
            raise KeyStoreUnavailable(f"the keyring entry for {kid} is malformed") from None


class PlaintextDevKeyStore:
    """UNENCRYPTED key files, for development only (``federation.identity_key_store: plaintext_dev``)."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        logger.warning(
            "AD-1196: identity private keys are stored UNENCRYPTED under %s because "
            "federation.identity_key_store=plaintext_dev; use only for development",
            directory,
        )

    async def describe(self) -> KeyStoreStatus:
        """Always available, never secure."""
        return KeyStoreStatus(
            kind="plaintext_dev", backend=str(self._directory), secure=False, available=True,
            reason="identity private keys are stored unencrypted (plaintext_dev)",
        )

    async def create(self, did: str) -> tuple[str, str]:
        """Write a new key to a fresh file (exclusive create; 0600 in a 0700 directory on POSIX)."""
        from probos.substrate.device_pairing import encode_private_key, generate_keypair

        private_key, public_key = generate_keypair()
        kid = key_id(did, public_key)
        body = json.dumps({"kid": kid, "private_key": encode_private_key(private_key)}).encode("utf-8")
        try:
            self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            with os.fdopen(os.open(self._path(kid), flags, 0o600), "wb") as handle:
                handle.write(body)
        except OSError as exc:
            raise KeyStoreUnavailable(
                f"the development key file for {kid} could not be written ({type(exc).__name__})"
            ) from None
        return kid, public_key

    async def public_key(self, kid: str) -> str | None:
        """The key file's public key (``None`` when there is no file)."""
        from probos.substrate.device_pairing import encode_public_key

        private_key = self._load(kid)
        if private_key is None:
            return None
        return encode_public_key(private_key.public_key())

    async def sign(self, kid: str, message: str) -> str:
        """Sign with the key under ``kid``, read from its file on every call."""
        from probos.substrate.device_pairing import sign_challenge

        private_key = self._load(kid)
        if private_key is None:  # AD-1196 A-1 dev re-read
            raise KeyStoreUnavailable(f"no private key is stored for {kid}")
        return sign_challenge(private_key, message)

    def _path(self, kid: str) -> Path:
        return self._directory / f"{hashlib.sha256(kid.encode('utf-8')).hexdigest()[:32]}.key"

    def _load(self, kid: str) -> Any | None:
        from probos.substrate.device_pairing import decode_private_key

        try:
            raw = self._path(kid).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise KeyStoreUnavailable(
                f"the development key file for {kid} could not be read ({type(exc).__name__})"
            ) from None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("kid") != kid:
                raise ValueError("kid mismatch")
            return decode_private_key(data["private_key"])
        except (ValueError, KeyError, TypeError):
            raise KeyStoreUnavailable(f"the development key file for {kid} is malformed") from None


def build_key_store(kind: str, data_dir: Path) -> IdentityKeyStore:
    """The store for ``federation.identity_key_store``: ``keyring`` or, explicitly, ``plaintext_dev``."""
    if kind == "keyring":
        return KeyringKeyStore()
    if kind == "plaintext_dev":
        return PlaintextDevKeyStore(data_dir / "identity-keys-dev")
    raise ValueError(f"unknown identity key store kind {kind!r}")
