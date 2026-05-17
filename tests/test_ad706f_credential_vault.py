"""AD-706f: Browser Tool credential vault tests.

Real EncryptedFileCredentialVault, real SystemConfig per BF-287. KEK
derivation uses a short test-only token so scrypt completes quickly
(scrypt n=2**14 takes ~50ms, acceptable for the test suite).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from probos.config import (
    AuthConfig,
    BrowserToolConfig,
    CredentialVaultConfig,
    SystemConfig,
)
from probos.events import EventType
from probos.tools.browser.actions import classify_action
from probos.tools.browser.credentials import (
    CredentialScope,
    EncryptedFileCredentialVault,
    _derive_kek,
    action_fill_credential,
)
from probos.tools.browser.session import BrowserSession


# -- Helpers --------------------------------------------------------------


def _make_vault(tmp_path: Path, token: str = "test-token-12345") -> EncryptedFileCredentialVault:
    kek = _derive_kek(token)
    return EncryptedFileCredentialVault(
        path=tmp_path / "vault.json",
        kek=kek,
        crew_scope_token=token,
    )


class _FakePage:
    def __init__(self) -> None:
        self.fills: list[tuple[str, str]] = []

    async def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))


def _make_session(*, last_url: str = "https://example.com/login") -> BrowserSession:
    cfg = BrowserToolConfig(enabled=True)
    sess = BrowserSession(session_id="s-f-1", agent_id="captain", config=cfg)
    sess._page = _FakePage()  # noqa: SLF001
    sess.set_last_url(last_url)
    return sess


# -- Tests ----------------------------------------------------------------


def test_vault_disabled_by_default() -> None:
    cfg = SystemConfig()
    assert cfg.browser_tool.credential_vault.enabled is False
    assert isinstance(cfg.browser_tool.credential_vault, CredentialVaultConfig)


def test_vault_requires_crew_scope_token_for_construction(tmp_path: Path) -> None:
    """Empty crew_scope_token rejected by the EncryptedFileCredentialVault ctor."""
    kek = _derive_kek("")  # deterministic but unsafe
    with pytest.raises(RuntimeError, match="crew_scope_token"):
        EncryptedFileCredentialVault(
            path=tmp_path / "vault.json",
            kek=kek,
            crew_scope_token="",
        )


def test_vault_kek_derivation_deterministic() -> None:
    """Same token => same KEK; different token => different KEK."""
    k1 = _derive_kek("alpha-token")
    k2 = _derive_kek("alpha-token")
    k3 = _derive_kek("beta-token")
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 32


@pytest.mark.asyncio
async def test_vault_store_and_read_roundtrip(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    scope = CredentialScope()  # Captain-only by default
    await vault.store(ref="github-pat", value="ghp_secretvalue", scope=scope)
    value = await vault.read(ref="github-pat", requesting_agent_id="captain")
    assert value == "ghp_secretvalue"


@pytest.mark.asyncio
async def test_vault_scope_denies_unauthorized_agent(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    scope = CredentialScope(allowed_agent_ids=frozenset({"agent-1"}))
    await vault.store(ref="login-pw", value="hunter2", scope=scope)
    # Captain not in allow-list when allow-list is non-empty.
    assert await vault.read(ref="login-pw", requesting_agent_id="captain") is None
    assert await vault.read(ref="login-pw", requesting_agent_id="agent-2") is None
    # Permitted agent gets the value.
    assert await vault.read(ref="login-pw", requesting_agent_id="agent-1") == "hunter2"


@pytest.mark.asyncio
async def test_vault_expires_at_enforced(tmp_path: Path) -> None:
    import time

    vault = _make_vault(tmp_path)
    # Expired one second ago.
    scope = CredentialScope(expires_at=time.time() - 1.0)
    await vault.store(ref="stale", value="x", scope=scope)
    assert await vault.read(ref="stale", requesting_agent_id="captain") is None


@pytest.mark.asyncio
async def test_vault_persists_across_restart(tmp_path: Path) -> None:
    v1 = _make_vault(tmp_path)
    await v1.store(ref="api-key", value="k-12345", scope=CredentialScope())
    # Recreate vault — should load existing state.
    v2 = _make_vault(tmp_path)
    assert await v2.read(ref="api-key", requesting_agent_id="captain") == "k-12345"


@pytest.mark.asyncio
async def test_vault_materialize_to_temp_returns_path_caller_unlinks(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    await vault.store(ref="upload-blob", value="payload-bytes", scope=CredentialScope())
    temp_path = await vault.materialize_to_temp(
        ref="upload-blob", requesting_agent_id="captain"
    )
    assert temp_path is not None
    assert temp_path.exists()
    try:
        assert temp_path.read_text(encoding="utf-8") == "payload-bytes"
    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_vault_delete(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    await vault.store(ref="to-delete", value="bye", scope=CredentialScope())
    await vault.delete(ref="to-delete")
    assert await vault.read(ref="to-delete", requesting_agent_id="captain") is None


@pytest.mark.asyncio
async def test_vault_list_refs_returns_metadata_no_values(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    await vault.store(ref="a", value="val-a", scope=CredentialScope())
    refs = await vault.list_refs()
    assert len(refs) == 1
    meta = refs[0]
    assert meta.ref == "a"
    assert meta.read_count == 0
    # CredentialMetadata has no value field — sanity check the dataclass shape.
    assert not hasattr(meta, "value")


# -- fill_credential action -----------------------------------------------


@pytest.mark.asyncio
async def test_action_fill_credential_honest_degrades_when_vault_none() -> None:
    """No vault on runtime => skipped_reason='credential_vault_unavailable'."""

    class _Runtime:
        config = SystemConfig()
        credential_vault = None

    sess = _make_session()
    result = await action_fill_credential(
        sess,
        {"selector": "#pw", "credential_ref": "ref-1", "agent_id": "captain"},
        runtime=_Runtime(),
        emit_event=None,
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "credential_vault_unavailable"


@pytest.mark.asyncio
async def test_action_fill_credential_blocks_http_when_require_https_true(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    await vault.store(ref="pw", value="secret", scope=CredentialScope())

    class _Runtime:
        config = SystemConfig()
        credential_vault = vault

    # require_https_for_fill defaults True.
    sess = _make_session(last_url="http://example.com/login")  # http, not https
    events: list[tuple[Any, Any]] = []
    result = await action_fill_credential(
        sess,
        {"selector": "#pw", "credential_ref": "pw", "agent_id": "captain"},
        runtime=_Runtime(),
        emit_event=lambda et, data: events.append((et, data)),
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "https_required"


@pytest.mark.asyncio
async def test_action_fill_credential_blocks_domain_mismatch(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    scope = CredentialScope(allowed_domains=frozenset({"github.com"}))
    await vault.store(ref="gh", value="token", scope=scope)

    class _Runtime:
        config = SystemConfig()
        credential_vault = vault

    sess = _make_session(last_url="https://gitlab.com/login")
    events: list[tuple[Any, Any]] = []
    result = await action_fill_credential(
        sess,
        {"selector": "#pw", "credential_ref": "gh", "agent_id": "captain"},
        runtime=_Runtime(),
        emit_event=lambda et, data: events.append((et, data)),
    )
    assert result["ok"] is False
    assert result["skipped_reason"] == "domain_mismatch"
    assert any(et == EventType.CREDENTIAL_READ_DENIED for et, _ in events)


@pytest.mark.asyncio
async def test_action_fill_credential_happy_path(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    scope = CredentialScope(allowed_domains=frozenset({"example.com"}))
    await vault.store(ref="login", value="hunter2", scope=scope)

    class _Runtime:
        config = SystemConfig()
        credential_vault = vault

    sess = _make_session(last_url="https://example.com/login")
    events: list[tuple[Any, Any]] = []
    result = await action_fill_credential(
        sess,
        {"selector": "#password", "credential_ref": "login", "agent_id": "captain"},
        runtime=_Runtime(),
        emit_event=lambda et, data: events.append((et, data)),
    )
    assert result["ok"] is True, result
    assert sess.page.fills == [("#password", "hunter2")]
    types = [et for et, _ in events]
    assert EventType.CREDENTIAL_READ in types
    assert EventType.CREDENTIAL_FILL_REQUESTED in types


def test_action_fill_credential_always_tier_3() -> None:
    sess = _make_session()
    assert classify_action(sess, "fill_credential", {}) == 3
    assert classify_action(sess, "fill_credential", {"credential_ref": "x"}) == 3
