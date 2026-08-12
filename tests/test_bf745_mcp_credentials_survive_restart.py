"""BF-745: an authenticated MCP server keeps its credentials across a restart.

The defect had the shape this repo produces most: two paths to one outcome, one
of them correct. The HXI enable path resolved credentials out of the vault
before registering; the boot seed loop passed ``dict(rec.headers)`` verbatim.
Registration SUCCEEDED either way -- ``register_server`` stores what it is
given and resolves nothing -- so the only symptom was a remote auth error much
later, or a tool that quietly returned nothing.

Most tests here drive ``register_record`` directly with a REAL vault and a
recording bridge, and assert what the bridge actually received -- the value
that was missing. ``test_the_store_to_bridge_chain_carries_credentials`` adds
the seam that was genuinely broken (store row -> registration -> bridge) with a
real ``McpServerStore``. The two ``inspect.getsource`` checks are drift guards
on the wiring, not behavioural proof; review flagged an earlier version of this
docstring for claiming all of them "drive the REAL boot path", which they do
not -- ``finalize_startup`` itself is not invoked here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.integrations.mcp_bridge.registration import register_record
from probos.integrations.mcp_bridge.store import McpServerRecord
from probos.tools.browser.credentials import (
    CredentialScope,
    EncryptedFileCredentialVault,
    _derive_kek,
)

_CREW_TOKEN = "bf745-test-crew-token"


class _RecordingBridge:
    """Records exactly what registration handed the transport."""

    def __init__(self) -> None:
        self.http: list[tuple[str, dict]] = []
        self.stdio: list[dict] = []

    def register_server(self, url: str, headers: dict | None = None) -> bool:
        self.http.append((url, dict(headers or {})))
        return True

    async def register_stdio_server(self, **kwargs: Any) -> bool:
        self.stdio.append(dict(kwargs))
        return True


class _Runtime:
    def __init__(self, bridge: Any, vault: Any) -> None:
        self.mcp_bridge = bridge
        self.credential_vault = vault


def _vault(tmp_path: Path) -> Any:
    return EncryptedFileCredentialVault(
        path=tmp_path / "vault.json",
        kek=_derive_kek(_CREW_TOKEN),
        crew_scope_token=_CREW_TOKEN,
    )


@pytest.fixture
def env(tmp_path: Path):
    vault = _vault(tmp_path)
    bridge = _RecordingBridge()
    return _Runtime(bridge, vault), bridge, vault


# ---------------------------------------------------------------------------
# The headline: what reaches the bridge on a restart
# ---------------------------------------------------------------------------

async def test_a_restart_registers_an_http_server_with_its_credentials(env) -> None:
    runtime, bridge, vault = env
    await vault.store(ref="mcp:srv1", value="tok-9", scope=CredentialScope())
    record = McpServerRecord(
        name="learn", type="http", url="https://example.test/mcp", id="srv1",
        auth_kind="static", credential_ref="mcp:srv1", enabled=True,
    )

    await register_record(runtime, record)

    assert bridge.http == [
        ("https://example.test/mcp", {"Authorization": "Bearer tok-9"})
    ], "boot registered the server without the credentials it was configured with"


async def test_a_restart_registers_a_stdio_server_with_its_credentials(env) -> None:
    runtime, bridge, vault = env
    await vault.store(ref="mcp:srv2", value="env-tok", scope=CredentialScope())
    record = McpServerRecord(
        name="local", type="stdio", command="python", args=["-m", "srv"], id="srv2",
        auth_kind="static", credential_ref="mcp:srv2", auth_env_var="API_KEY",
        enabled=True,
    )

    await register_record(runtime, record)

    assert bridge.stdio[0]["env"] == {"API_KEY": "env-tok"}


async def test_oauth_credentials_survive_a_restart(env) -> None:
    runtime, bridge, vault = env
    await vault.store(
        ref="mcp:srv3",
        value='{"access_token": "oauth-tok", "token_type": "Bearer"}',
        scope=CredentialScope(),
    )
    record = McpServerRecord(
        name="oauthed", type="http", url="https://example.test/o", id="srv3",
        auth_kind="oauth", credential_ref="mcp:srv3", enabled=True,
    )

    await register_record(runtime, record)

    assert bridge.http[0][1] == {"Authorization": "Bearer oauth-tok"}


# ---------------------------------------------------------------------------
# The unauthenticated case must stay byte-identical
# ---------------------------------------------------------------------------

async def test_an_unauthenticated_server_registers_exactly_as_before(env) -> None:
    """``auth_kind=="none"`` resolves to {} -- which is why the defect survived
    so long, and why it must keep behaving identically."""
    runtime, bridge, _ = env
    record = McpServerRecord(
        name="plain", type="http", url="https://example.test/p",
        headers={"X-Custom": "v"}, auth_kind="none", enabled=True,
    )

    await register_record(runtime, record)

    assert bridge.http == [("https://example.test/p", {"X-Custom": "v"})]


async def test_a_vault_miss_registers_unauthenticated_and_does_not_raise(env) -> None:
    """Honest-degrade: a missing secret must not stop the ship booting."""
    runtime, bridge, _ = env
    record = McpServerRecord(
        name="missing", type="http", url="https://example.test/m", id="srv4",
        auth_kind="static", credential_ref="mcp:absent", enabled=True,
    )

    await register_record(runtime, record)

    assert bridge.http == [("https://example.test/m", {})]


async def test_no_bridge_is_a_no_op(env) -> None:
    _, _, vault = env
    record = McpServerRecord(name="x", type="http", url="u", auth_kind="none")

    await register_record(_Runtime(None, vault), record)  # must not raise


async def test_a_raising_vault_does_not_stop_the_ship_booting(env, tmp_path) -> None:
    """REVIEW FINDING. This code was safe in the router, where a raise became an
    HTTP 500. Moving it into the boot seed loop changed its blast radius: there
    is no guard above ``finalize``, so a vault that raises while reading (the
    encrypted-file backend can surface filesystem errors updating read
    metadata) meant ONE authenticated server prevented startup entirely."""
    _, bridge, _ = env

    class _RaisingVault:
        async def read(self, **_kw: Any) -> str:
            raise OSError("vault metadata unwritable")

    record = McpServerRecord(
        name="boom", type="http", url="https://example.test/b", id="srv9",
        auth_kind="static", credential_ref="mcp:srv9", enabled=True,
    )

    await register_record(_Runtime(bridge, _RaisingVault()), record)

    assert bridge.http == [("https://example.test/b", {})], (
        "a vault failure must degrade to unauthenticated, exactly as a vault "
        "miss does -- not abort the boot"
    )


async def test_the_store_to_bridge_chain_carries_credentials(tmp_path) -> None:
    """CROSSING: a real store row, read back the way the boot loop reads it,
    reaching the bridge with its credentials. This is the seam that was broken --
    the other tests construct the record by hand and so cannot see it."""
    from probos.integrations.mcp_bridge.store import McpServerStore

    vault = _vault(tmp_path)
    await vault.store(ref="mcp:stored", value="stored-tok", scope=CredentialScope())
    store = McpServerStore(db_path=str(tmp_path / "srv.db"))
    await store.start()
    try:
        await store.create(
            McpServerRecord(
                name="stored", type="http", url="https://example.test/s",
                auth_kind="static", credential_ref="mcp:stored", enabled=True,
            )
        )
        bridge = _RecordingBridge()
        runtime = _Runtime(bridge, vault)

        for rec in store.list_sync():
            if rec.enabled:
                await register_record(runtime, rec)

        assert bridge.http == [
            ("https://example.test/s", {"Authorization": "Bearer stored-tok"})
        ]
    finally:
        await store.stop()


# ---------------------------------------------------------------------------
# The structural guarantee: one registrar, not two
# ---------------------------------------------------------------------------

def test_the_boot_path_uses_the_shared_registrar() -> None:
    """CROSSING: the boot seed loop had its own copy of registration that did
    not resolve auth. If a second copy reappears, this is what catches it."""
    import inspect

    from probos.startup import finalize

    source = inspect.getsource(finalize)
    seed_at = source.index("for rec in mcp_server_store.list_sync():")
    following = source[seed_at:seed_at + 600]

    assert "await register_record(runtime, rec)" in following
    assert "headers=dict(rec.headers)" not in following, (
        "the boot loop is registering headers directly again -- that is the "
        "defect BF-745 fixed"
    )


def test_the_router_delegates_rather_than_keeping_a_second_copy() -> None:
    import inspect

    from probos.routers import mcp_servers

    assert "register_record" in inspect.getsource(mcp_servers._register)
    assert not hasattr(mcp_servers, "_resolve_secret_value"), (
        "the router kept its own secret resolver; there must be exactly one"
    )
