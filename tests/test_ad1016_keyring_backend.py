"""AD-1016: KeyringCredentialBackend tests.

BF-287: the keyring backend is exercised against a REAL dict-backed fake of
``keyring.set_password``/``get_password``/``delete_password`` (mirroring
``tests/test_credential_encryptor.py``), NOT MagicMock — so storage semantics
(roundtrip, miss, delete) are real. The metadata sidecar lives on ``tmp_path``.
"""

from __future__ import annotations

import inspect
import json
import time
from pathlib import Path

import pytest

from probos.config import CredentialVaultConfig
from probos.security.keyring_backend import KeyringCredentialBackend
from probos.tools.browser.credentials import (
    CredentialMetadata,
    CredentialScope,
    EncryptedFileCredentialVault,
)

_SECRET = "s3cr3t-token-value-AD1016"


@pytest.fixture
def keyring_store(monkeypatch) -> dict[tuple[str, str], str]:
    """Real dict-backed fake keyring (BF-287). Returns the backing store."""
    values: dict[tuple[str, str], str] = {}

    def _set_password(service: str, username: str, value: str) -> None:
        values[(service, username)] = value

    def _get_password(service: str, username: str) -> str | None:
        return values.get((service, username))

    def _delete_password(service: str, username: str) -> None:
        values.pop((service, username), None)

    monkeypatch.setattr("keyring.set_password", _set_password)
    monkeypatch.setattr("keyring.get_password", _get_password)
    monkeypatch.setattr("keyring.delete_password", _delete_password)
    return values


def _backend(tmp_path: Path) -> KeyringCredentialBackend:
    return KeyringCredentialBackend(
        service_name="probos.test",
        index_path=tmp_path / "keyring_index.json",
    )


# ---------------------------------------------------------------------------
# Protocol conformance (structural substitutability)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method", ["store", "read", "materialize_to_temp", "delete", "list_refs"]
)
def test_protocol_signature_matches_file_vault(method: str) -> None:
    kb = getattr(KeyringCredentialBackend, method)
    fv = getattr(EncryptedFileCredentialVault, method)
    assert inspect.iscoroutinefunction(kb), f"{method} must be async"
    assert inspect.iscoroutinefunction(fv)
    assert inspect.signature(kb) == inspect.signature(fv), (
        f"{method} signature diverges from EncryptedFileCredentialVault"
    )


def test_has_all_five_protocol_methods() -> None:
    for method in ("store", "read", "materialize_to_temp", "delete", "list_refs"):
        assert hasattr(KeyringCredentialBackend, method)


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_then_read_returns_value(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())

    got = await backend.read(ref="r1", requesting_agent_id="captain")

    assert got == _SECRET


@pytest.mark.asyncio
async def test_read_wrong_agent_scope_returns_none(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    scope = CredentialScope(allowed_agent_ids=frozenset({"agent-x"}))
    await backend.store(ref="r1", value=_SECRET, scope=scope)

    # agent-y is not in the allow-list.
    assert await backend.read(ref="r1", requesting_agent_id="agent-y") is None
    # agent-x is.
    assert await backend.read(ref="r1", requesting_agent_id="agent-x") == _SECRET


@pytest.mark.asyncio
async def test_read_expired_scope_returns_none(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    scope = CredentialScope(expires_at=time.time() - 100.0)  # already expired
    await backend.store(ref="r1", value=_SECRET, scope=scope)

    assert await backend.read(ref="r1", requesting_agent_id="captain") is None


@pytest.mark.asyncio
async def test_read_unknown_ref_returns_none(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    assert await backend.read(ref="missing", requesting_agent_id="captain") is None


@pytest.mark.asyncio
async def test_delete_removes_value_and_sidecar_entry(keyring_store, tmp_path) -> None:
    index_path = tmp_path / "keyring_index.json"
    backend = KeyringCredentialBackend(
        service_name="probos.test", index_path=index_path
    )
    await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())

    await backend.delete(ref="r1")

    # Value gone from the keychain.
    assert keyring_store.get(("probos.test", "r1")) is None
    # Metadata gone from the sidecar.
    assert await backend.read(ref="r1", requesting_agent_id="captain") is None
    assert await backend.list_refs() == []
    on_disk = json.loads(index_path.read_text(encoding="utf-8"))
    assert "r1" not in on_disk.get("refs", {})


@pytest.mark.asyncio
async def test_list_refs_returns_metadata_only(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    scope = CredentialScope(allowed_domains=frozenset({"example.com"}))
    await backend.store(ref="r1", value=_SECRET, scope=scope)

    refs = await backend.list_refs()

    assert len(refs) == 1
    meta = refs[0]
    assert isinstance(meta, CredentialMetadata)
    assert meta.ref == "r1"
    assert meta.read_count == 0
    assert meta.last_read_at is None
    assert "example.com" in meta.scope.allowed_domains
    # CredentialMetadata has no value field (Protocol guarantee).
    assert not hasattr(meta, "value")


@pytest.mark.asyncio
async def test_read_bumps_read_count_and_last_read_at(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())

    await backend.read(ref="r1", requesting_agent_id="captain")
    after_one = {m.ref: m for m in await backend.list_refs()}["r1"]
    assert after_one.read_count == 1
    assert after_one.last_read_at is not None

    await backend.read(ref="r1", requesting_agent_id="captain")
    after_two = {m.ref: m for m in await backend.list_refs()}["r1"]
    assert after_two.read_count == 2


# ---------------------------------------------------------------------------
# Secret never in the sidecar (the load-bearing invariant)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_value_never_in_sidecar(keyring_store, tmp_path) -> None:
    index_path = tmp_path / "keyring_index.json"
    backend = KeyringCredentialBackend(
        service_name="probos.test", index_path=index_path
    )
    await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())
    # Read (bumps metadata, re-persists) to be thorough.
    await backend.read(ref="r1", requesting_agent_id="captain")

    raw = index_path.read_text(encoding="utf-8")
    assert _SECRET not in raw, "secret value leaked into the metadata sidecar"
    # But the secret IS in the (fake) keychain.
    assert keyring_store[("probos.test", "r1")] == _SECRET


# ---------------------------------------------------------------------------
# materialize_to_temp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_materialize_to_temp_writes_value(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())

    path = await backend.materialize_to_temp(ref="r1", requesting_agent_id="captain")

    assert path is not None
    try:
        assert path.read_text(encoding="utf-8") == _SECRET
    finally:
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_materialize_to_temp_missing_ref_returns_none(keyring_store, tmp_path) -> None:
    backend = _backend(tmp_path)
    assert (
        await backend.materialize_to_temp(ref="missing", requesting_agent_id="captain")
        is None
    )


# ---------------------------------------------------------------------------
# Honest-degrade on keyring failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_honest_degrades_when_keyring_get_raises(
    keyring_store, tmp_path, monkeypatch
) -> None:
    backend = _backend(tmp_path)
    await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())

    def _boom(service: str, username: str) -> str | None:
        raise RuntimeError("keyring backend unavailable")

    monkeypatch.setattr("keyring.get_password", _boom)

    # read degrades to None without crashing...
    assert await backend.read(ref="r1", requesting_agent_id="captain") is None
    # ...and list_refs still works (it reads only the sidecar).
    refs = await backend.list_refs()
    assert [m.ref for m in refs] == ["r1"]


@pytest.mark.asyncio
async def test_store_raises_clear_error_when_keyring_set_raises(
    keyring_store, tmp_path, monkeypatch
) -> None:
    backend = _backend(tmp_path)

    def _boom(service: str, username: str, value: str) -> None:
        raise RuntimeError("no keyring backend")

    monkeypatch.setattr("keyring.set_password", _boom)

    with pytest.raises(RuntimeError, match="AD-1016"):
        await backend.store(ref="r1", value=_SECRET, scope=CredentialScope())

    # No orphan sidecar entry — the credential did not persist.
    assert await backend.list_refs() == []


# ---------------------------------------------------------------------------
# Config: backend selector + validator
# ---------------------------------------------------------------------------


def test_config_backend_default_is_file() -> None:
    cfg = CredentialVaultConfig()
    assert cfg.backend == "file"


def test_config_backend_keychain_accepted() -> None:
    cfg = CredentialVaultConfig(backend="keychain")
    assert cfg.backend == "keychain"


def test_config_backend_bogus_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CredentialVaultConfig(backend="bogus")


def test_config_keyring_defaults() -> None:
    cfg = CredentialVaultConfig()
    assert cfg.keyring_index_path == "data/credential_keyring_index.json"
    assert cfg.keyring_service_name == "probos.credentials"
