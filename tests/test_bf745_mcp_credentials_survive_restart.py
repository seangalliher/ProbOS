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

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from probos.capability_request import CapabilityRequest, CapabilityRequestStore
from probos.cognitive.capability_triage import fulfil_install
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.client import MCPProtocolError
from probos.integrations.mcp_bridge.registration import register_record
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.tools.browser.credentials import (
    CredentialScope,
    EncryptedFileCredentialVault,
    _derive_kek,
)

_CREW_TOKEN = "bf745-test-crew-token"


class _RegisteredStdioClient:
    # A bare object modeled presence only; strict stdio now also requires liveness.
    is_alive: bool = True


class _RecordingBridge:
    """Records exactly what registration handed the transport."""

    def __init__(self) -> None:
        self.http: list[tuple[str, dict[str, str]]] = []
        self.stdio: list[dict[str, Any]] = []
        self.clients: dict[str, object] = {}
        self.unregistered: list[str] = []
        self.configurations: dict[str, tuple[object, ...]] = {}

    def register_server(
        self, url: str, headers: dict[str, str] | None = None,
        *, reuse_if_matching: bool = False,
    ) -> bool:
        self.http.append((url, dict(headers or {})))
        configuration = ("http", url, frozenset((headers or {}).items()))
        if url in self.clients:
            return reuse_if_matching and self.configurations.get(url) == configuration
        self.clients[url] = object()
        self.configurations[url] = configuration
        return True

    async def register_stdio_server(
        self, name: str, command: str, args: list[str], env: dict[str, str],
        cwd: str, *, timeout: float | None = None, reuse_if_matching: bool = False,
    ) -> bool:
        self.stdio.append({
            "name": name, "command": command, "args": list(args), "env": dict(env),
            "cwd": cwd, "timeout": timeout,
        })
        configuration = ("stdio", name, command, tuple(args), frozenset(env.items()), cwd, timeout)
        if name in self.clients:
            return reuse_if_matching and self.configurations.get(name) == configuration
        self.clients[name] = _RegisteredStdioClient()
        self.configurations[name] = configuration
        return True

    def get_client(self, key: str) -> object | None:
        return self.clients.get(key)

    async def unregister_server(self, key: str) -> bool:
        self.unregistered.append(key)
        self.configurations.pop(key, None)
        return self.clients.pop(key, None) is not None


class _Runtime:
    def __init__(self, bridge: Any, vault: Any) -> None:
        self.mcp_bridge = bridge
        self.credential_vault = vault
        self.mcp_server_store: McpServerStore | None = None
        self.ensure_calls: list[str] = []

    async def ensure_dependency(self, target: str, *, pre_approved: bool = False) -> Any:
        self.ensure_calls.append(target)
        raise AssertionError("MCP registration must not invoke dependency installation")


class _FakeVault:
    def __init__(self, value: str | None = None, error: BaseException | None = None) -> None:
        self.value = value
        self.error = error

    async def read(self, *, ref: str, requesting_agent_id: str) -> str | None:
        if self.error is not None:
            raise self.error
        return self.value


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

@pytest.mark.parametrize("caller", ["boot", "router", "fulfiller"])
@pytest.mark.parametrize("auth", ["none", "static", "custom", "oauth", "stdio"])
async def test_auth_reaches_bridge_through_each_registration_caller(
    env: Any, tmp_path: Path, caller: str, auth: str
) -> None:
    from probos.routers.mcp_servers import _register

    runtime, bridge, vault = env
    secret = "parity-token"
    await vault.store(
        ref="mcp:parity",
        value='{"access_token":"parity-token","token_type":"Bearer"}'
        if auth == "oauth" else secret,
        scope=CredentialScope(),
    )
    record = McpServerRecord(
        id="parity", name="parity", type="stdio" if auth == "stdio" else "http",
        url="https://example.test/parity", command="python", args=["-m", "server"],
        cwd="test-workspace", timeout_seconds=17.0,
        headers={"X-Custom": "kept"}, env={"MODE": "test"},
        auth_kind="none" if auth == "none" else "oauth" if auth == "oauth" else "static",
        credential_ref="mcp:parity", auth_env_var="API_KEY" if auth == "stdio" else "",
        auth_header_name="X-Access" if auth == "custom" else "Authorization",
        auth_scheme="" if auth == "custom" else "Bearer", enabled=False,
    )
    mcp_store = McpServerStore(db_path=str(tmp_path / "parity-mcp.db"))
    request_store = CapabilityRequestStore(db_path=str(tmp_path / "parity-requests.db"))
    await mcp_store.start()
    try:
        await request_store.start()
        try:
            record = await mcp_store.create(record)
            runtime.mcp_server_store = mcp_store
            if caller == "fulfiller":
                request = await request_store.file_request(
                    agent_id="agent-1", kind="install", target=record.id, rationale="",
                    payload={"install_kind": "mcp", "mcp_server_id": record.id},
                )
                await request_store.decide(
                    request.id, approve=True, reason="ok", decided_by="captain"
                )
                result = await fulfil_install(
                    request.id, store=request_store, target=record.id, runtime=runtime
                )
                assert result is not None and result.status == "fulfilled"
                assert runtime.ensure_calls == []
            else:
                enabled = await mcp_store.set_enabled(record.id, True)
                assert enabled is not None
                result = await (
                    _register(runtime, enabled) if caller == "router"
                    else register_record(runtime, enabled)
                )
                assert result is None
            if auth == "stdio":
                assert bridge.stdio == [{
                    "name": "parity", "command": "python", "args": ["-m", "server"],
                    "env": {"MODE": "test", "API_KEY": secret},
                    "cwd": "test-workspace", "timeout": 17.0,
                }]
                assert bridge.get_client(record.name) is not None
            else:
                expected_headers = {"X-Custom": "kept"}
                if auth == "custom":
                    expected_headers["X-Access"] = secret
                elif auth != "none":
                    expected_headers["Authorization"] = f"Bearer {secret}"
                assert bridge.http == [(record.url, expected_headers)]
                assert bridge.get_client(record.url) is not None
        finally:
            await request_store.stop()
    finally:
        await mcp_store.stop()


@pytest.mark.parametrize("transport", ["http", "stdio"])
@pytest.mark.parametrize("failure", [
    "no-vault", "no-ref", "missing", "raising", "empty", "blank", "corrupt-oauth",
    "empty-oauth", "unknown-auth", "no-env-var", "invalid-header", "invalid-scheme",
])
async def test_strict_auth_failure_preserves_existing_clients_without_secret_logs(
    transport: str, failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "secret-must-not-be-logged"
    bridge = _RecordingBridge()
    vault = _FakeVault(secret)
    runtime = _Runtime(bridge, vault)
    record = McpServerRecord(
        name="strict", type=transport, url="https://example.test/strict",
        command="python", auth_kind="static", credential_ref="mcp:strict",
        auth_env_var="API_KEY",
    )
    if failure == "no-vault":
        runtime.credential_vault = None
    elif failure == "no-ref":
        record = replace(record, credential_ref="")
    elif failure == "missing":
        vault.value = None
    elif failure == "raising":
        vault.error = OSError(secret)
    elif failure == "empty":
        vault.value = ""
    elif failure == "blank":
        vault.value = "   "
    elif failure == "corrupt-oauth":
        record = replace(record, auth_kind="oauth")
    elif failure == "empty-oauth":
        record = replace(record, auth_kind="oauth")
        vault.value = '{"access_token":"","token_type":"Bearer"}'
    elif failure == "unknown-auth":
        record = replace(record, auth_kind="unknown")
    elif failure == "no-env-var":
        record = replace(record, type="stdio", auth_env_var="")
    elif failure == "invalid-header":
        record = replace(record, type="http", auth_header_name="invalid header")
    else:
        record = replace(record, type="http", auth_scheme="Bearer\r\nInjected: value")
    key = record.url if record.type == "http" else record.name
    existing = object()
    unrelated = object()
    bridge.clients.update({key: existing, "unrelated": unrelated})

    result = await register_record(runtime, record, require_ready=True)

    assert result is False
    assert bridge.get_client(key) is existing
    assert bridge.get_client("unrelated") is unrelated
    assert bridge.unregistered == []
    assert bridge.http == [] and bridge.stdio == []
    assert secret not in caplog.text


@pytest.mark.parametrize("transport", ["http", "stdio"])
async def test_strict_mismatch_resolves_credentials_without_replacing_target(
    transport: str,
) -> None:
    bridge = _RecordingBridge()
    record = McpServerRecord(
        name="refresh", type=transport, url="https://example.test/refresh",
        command="python", args=["-m", "server"], cwd="work", timeout_seconds=11,
        auth_kind="static", credential_ref="mcp:refresh", auth_env_var="API_KEY",
        headers={"Authorization": "stale", "X-Custom": "keep"},
        env={"API_KEY": "stale", "MODE": "keep"},
    )
    key = record.url if transport == "http" else record.name
    existing = object()
    unrelated = object()
    bridge.clients.update({key: existing, "unrelated": unrelated})

    class _CheckingVault:
        async def read(self, *, ref: str, requesting_agent_id: str) -> str:
            assert bridge.get_client(key) is existing
            assert bridge.unregistered == []
            return "fresh"

    result = await register_record(_Runtime(bridge, _CheckingVault()), record, require_ready=True)

    assert result is False, "unknown existing configuration must be refused, not destructively refreshed"
    assert bridge.get_client(key) is existing
    assert bridge.get_client("unrelated") is unrelated
    assert bridge.unregistered == []
    if transport == "http":
        assert bridge.http == [(record.url, {"Authorization": "Bearer fresh", "X-Custom": "keep"})]
    else:
        assert bridge.stdio == [{
            "name": record.name, "command": "python", "args": ["-m", "server"],
            "env": {"API_KEY": "fresh", "MODE": "keep"}, "cwd": "work", "timeout": 11,
        }]


async def test_default_duplicate_registration_keeps_existing_client() -> None:
    bridge = _RecordingBridge()
    record = McpServerRecord(name="duplicate", type="http", url="https://example.test/dup")
    assert bridge.register_server(record.url, {"X-Config": "first"}) is True
    existing = bridge.get_client(record.url)

    result = await register_record(_Runtime(bridge, None), record)

    assert result is None
    assert bridge.get_client(record.url) is existing
    assert bridge.unregistered == []


@pytest.mark.parametrize("reject", [False, True], ids=["mismatch", "rejected"])
async def test_review_regression_strict_http_mismatch_preserves_concrete_client(
    reject: bool,
) -> None:
    from probos.integrations.mcp_bridge import MCPBridge

    class _RejectingBridge(MCPBridge):
        reject_registration: bool = False

        def register_server(
            self, url: str, headers: dict[str, str] | None = None,
            *, reuse_if_matching: bool = False,
        ) -> bool:
            if self.reject_registration:
                return False
            return super().register_server(url, headers=headers, reuse_if_matching=reuse_if_matching)

    bridge = _RejectingBridge()
    record = McpServerRecord(
        name="mismatch", type="http", url="https://example.test/mismatch",
        headers={"X-Config": "original"},
    )
    try:
        assert bridge.register_server(record.url, headers=dict(record.headers)) is True
        existing = bridge.get_client(record.url)
        assert existing is not None
        assert bridge.register_server("https://example.test/unrelated") is True
        unrelated = bridge.get_client("https://example.test/unrelated")
        assert unrelated is not None
        changed = replace(record, headers={"X-Config": "changed"})
        assert changed.headers != record.headers
        bridge.reject_registration = reject

        result = await register_record(_Runtime(bridge, None), changed, require_ready=True)

        assert bridge.get_client(record.url) is existing
        assert bridge.get_client("https://example.test/unrelated") is unrelated
        assert result is False
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("unused_field", ["auth_header_name", "auth_scheme"])
async def test_review_regression_oauth_ignores_unused_header_metadata(
    env: Any, unused_field: str,
) -> None:
    runtime, bridge, vault = env
    await vault.store(
        ref="mcp:oauth-unused",
        value='{"access_token":"valid-oauth-token","token_type":"Bearer"}',
        scope=CredentialScope(),
    )
    record = McpServerRecord(
        name="oauth-unused", type="http", url="https://example.test/oauth-unused",
        auth_kind="oauth", credential_ref="mcp:oauth-unused",
        headers={"X-Custom": "kept"},
    )
    record = replace(record, **{unused_field: "invalid\r\nmetadata"})
    assert record.auth_kind == "oauth"
    assert getattr(record, unused_field) == "invalid\r\nmetadata"
    assert bridge.get_client(record.url) is None

    result = await register_record(runtime, record, require_ready=True)

    assert result is True
    assert bridge.http == [(
        record.url,
        {"X-Custom": "kept", "Authorization": "Bearer valid-oauth-token"},
    )]
    assert bridge.get_client(record.url) is not None


async def test_strict_missing_bridge_reports_failure() -> None:
    record = McpServerRecord(name="missing", type="http", url="https://example.test/missing")
    assert await register_record(_Runtime(None, None), record, require_ready=True) is False


async def test_strict_vault_cancellation_preserves_existing_client() -> None:
    bridge = _RecordingBridge()
    record = McpServerRecord(
        name="cancel", type="http", url="https://example.test/cancel",
        auth_kind="static", credential_ref="mcp:cancel",
    )
    existing = object()
    bridge.clients[record.url] = existing
    runtime = _Runtime(bridge, _FakeVault(error=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await register_record(runtime, record, require_ready=True)

    assert bridge.get_client(record.url) is existing
    assert bridge.unregistered == []
    assert bridge.http == []


@pytest.mark.parametrize("cleanup_raises", [False, True])
async def test_strict_stdio_cancellation_retains_published_client_and_propagates(
    cleanup_raises: bool,
) -> None:
    class _CancellingBridge(_RecordingBridge):
        async def register_stdio_server(
            self, name: str, command: str, args: list[str], env: dict[str, str],
            cwd: str, *, timeout: float | None = None, reuse_if_matching: bool = False,
        ) -> bool:
            await super().register_stdio_server(
                name, command, args, env, cwd, timeout=timeout, reuse_if_matching=reuse_if_matching,
            )
            raise asyncio.CancelledError()

        async def unregister_server(self, key: str) -> bool:
            removed = await super().unregister_server(key)
            if cleanup_raises:
                raise OSError("cleanup failed")
            return removed

    bridge = _CancellingBridge()
    record = McpServerRecord(name="cancel", type="stdio", command="python")

    with pytest.raises(asyncio.CancelledError):
        await register_record(_Runtime(bridge, None), record, require_ready=True)

    assert bridge.get_client(record.name) is not None, "published clients belong to the bridge, including on cancellation"
    assert bridge.unregistered == []

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


@pytest.fixture
def controlled_transport(monkeypatch: pytest.MonkeyPatch) -> Any:
    class _ControlledTransport:
        instances: list[Any] = []
        start_hook: Callable[[], Awaitable[None]] | None = None
        start_error: BaseException | None = None
        close_error: BaseException | None = None
        alive_after_start = True
        liveness_error: BaseException | None = None

        def __init__(
            self, *, command: str, args: list[str], env: dict[str, str],
            cwd: str, timeout: float, name: str,
        ) -> None:
            self.command = command
            self.args = list(args)
            self.env = dict(env)
            self.cwd = cwd
            self.timeout = timeout
            self.name = name
            self.started = False
            self.closes = 0
            self.last_metadata: dict[str, str] = {}
            self.hook = type(self).start_hook
            self.error = type(self).start_error
            self.close_failure = type(self).close_error
            self.close_hook: Callable[[], Awaitable[None]] | None = None
            self.alive = False
            self.ready = type(self).alive_after_start
            self.liveness_failure = type(self).liveness_error
            self.instances.append(self)

        @property
        def is_alive(self) -> bool:
            if self.liveness_failure is not None:
                raise self.liveness_failure
            return self.alive

        async def start(self) -> None:
            self.started = True
            if self.hook is not None:
                await self.hook()
            if self.error is not None:
                raise self.error
            self.alive = self.ready

        async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": payload["id"], "result": {}}

        async def close(self) -> None:
            self.closes += 1
            if self.close_hook is not None:
                await self.close_hook()
            if self.close_failure is not None:
                raise self.close_failure
            self.alive = False

    monkeypatch.setattr("probos.integrations.mcp_bridge.bridge.StdioTransport", _ControlledTransport)
    return _ControlledTransport


@pytest.mark.parametrize("initial_reuse", [False, True])
async def test_concrete_http_reuse_copies_headers_and_preserves_default_duplicates(
    initial_reuse: bool,
) -> None:
    bridge = MCPBridge()
    url = "https://example.test/copy"
    headers = {"Authorization": "Bearer original", "X-Config": "original"}
    original = dict(headers)
    try:
        assert bridge.register_server(url, headers, reuse_if_matching=initial_reuse) is True
        client = bridge.get_client(url)
        assert client is not None
        headers["Authorization"] = "Bearer changed"
        headers["X-Config"] = "changed"
        assert bridge.register_server(url, original, reuse_if_matching=True) is True
        assert bridge.get_client(url) is client
        assert bridge.register_server(url, headers, reuse_if_matching=True) is False
        assert bridge.register_server(url, original) is False
        assert bridge.register_server(url, object()) is False
        assert bridge.get_client(url) is client
        assert await bridge.unregister_server(url) is True
        assert bridge.get_client(url) is None
        assert await bridge.unregister_server(url) is False
        assert bridge.register_server(url, headers, reuse_if_matching=True) is True
        assert bridge.get_client(url) is not client
        await bridge.close_all()
        assert bridge.register_server(url, original, reuse_if_matching=True) is True
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("reuse", [False, True])
async def test_concrete_bridge_empty_http_and_disabled_stdio_remain_unregistered(reuse: bool) -> None:
    bridge = MCPBridge(command_allowlist=["python"])
    try:
        assert bridge.register_server("", reuse_if_matching=reuse) is False
        assert await bridge.register_stdio_server(
            "disabled", "python", [], {}, "", reuse_if_matching=reuse,
        ) is False
        assert bridge.list_servers() == []
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("field", ["command", "args", "env", "cwd", "timeout"])
@pytest.mark.parametrize("alive", [False, True])
async def test_concrete_stdio_exact_reuse_and_configuration_mismatch(
    controlled_transport: Any, tmp_path: Path, field: str, alive: bool,
) -> None:
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python", "other"])
    arguments = ["first", "second"]
    environment = {"API_KEY": "original", "MODE": "test"}
    original: dict[str, Any] = {
        "name": "copy", "command": "python", "args": list(arguments),
        "env": dict(environment), "cwd": str(tmp_path), "timeout": 7.0,
    }
    try:
        assert await bridge.register_stdio_server(
            "copy", "python", arguments, environment, str(tmp_path), timeout=7.0,
        ) is True
        client = bridge.get_client("copy")
        assert client is not None
        candidate = controlled_transport.instances[0]
        assert candidate.started is True and candidate.closes == 0
        assert candidate.args == ["first", "second"]
        assert candidate.env["API_KEY"] == "original" and candidate.env["MODE"] == "test"
        assert candidate.cwd == os.path.abspath(tmp_path) and candidate.timeout == 7.0
        arguments.reverse()
        environment["API_KEY"] = "changed"
        assert await bridge.register_stdio_server(**original, reuse_if_matching=True) is True
        assert await bridge.register_stdio_server(**original) is False
        candidate.alive = alive
        assert client.is_alive is alive
        changed = {**original, field: {
            "command": "other", "args": ["second", "first"], "env": environment,
            "cwd": str(tmp_path / "different"), "timeout": 8.0,
        }[field]}
        assert await bridge.register_stdio_server(**changed, reuse_if_matching=True) is False
        assert bridge.get_client("copy") is client
        assert len(controlled_transport.instances) == 1 and candidate.closes == 0
        assert await bridge.unregister_server("copy") is True
        assert candidate.closes == 1
        assert await bridge.register_stdio_server(**changed, reuse_if_matching=True) is True
        assert bridge.get_client("copy") is not client
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("failure", ["allowlist", "consent", "exception", "cancel"])
@pytest.mark.parametrize("alive", [False, True])
async def test_strict_stdio_reuse_still_checks_gates_and_preserves_owned_clients(
    controlled_transport: Any, failure: str, alive: bool,
) -> None:
    consent_state = {"mode": "allow", "calls": 0}

    async def consent(context: dict[str, Any]) -> bool:
        assert context["tool_name"] == "mcp_stdio_spawn"
        consent_state["calls"] += 1
        if consent_state["mode"] == "exception":
            raise OSError("consent unavailable")
        if consent_state["mode"] == "cancel":
            raise asyncio.CancelledError()
        return consent_state["mode"] == "allow"

    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"], consent_fn=consent)
    record = McpServerRecord(name="gated", type="stdio", command="python")
    runtime = _Runtime(bridge, None)
    try:
        assert await register_record(runtime, record, require_ready=True) is True
        existing = bridge.get_client(record.name)
        assert existing is not None
        controlled_transport.instances[0].alive = alive
        assert existing.is_alive is alive
        assert bridge.register_server("https://example.test/unrelated") is True
        unrelated = bridge.get_client("https://example.test/unrelated")
        consent_state["mode"] = failure
        if failure == "allowlist":
            record = replace(record, command="not-allowed")
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await register_record(runtime, record, require_ready=True)
        else:
            assert await register_record(runtime, record, require_ready=True) is False
        assert bridge.get_client(record.name) is existing
        assert bridge.get_client("https://example.test/unrelated") is unrelated
        assert len(controlled_transport.instances) == 1
        assert controlled_transport.instances[0].closes == 0
        before = consent_state["calls"]
        assert await bridge.register_stdio_server("gated", "python", [], {}, "") is False
        assert consent_state["calls"] == before, "default duplicate precedence is unchanged"
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("name,command", [("", "python"), ("named", "")])
async def test_strict_stdio_empty_identity_or_command_does_not_spawn(
    controlled_transport: Any, name: str, command: str,
) -> None:
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python", ""])
    try:
        assert await bridge.register_stdio_server(
            name, command, [], {}, "", reuse_if_matching=True,
        ) is False
        assert controlled_transport.instances == [] and bridge.list_servers() == []
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("first_transport", ["http", "stdio"])
async def test_exact_reuse_refuses_transport_collision_without_replacement(
    controlled_transport: Any, first_transport: str,
) -> None:
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    key = "https://example.test/shared"
    try:
        if first_transport == "http":
            assert bridge.register_server(key) is True
        else:
            assert await bridge.register_stdio_server(key, "python", [], {}, "") is True
        existing = bridge.get_client(key)
        assert existing is not None
        if first_transport == "http":
            assert await bridge.register_stdio_server(key, "python", [], {}, "", reuse_if_matching=True) is False
        else:
            assert bridge.register_server(key, reuse_if_matching=True) is False
        assert bridge.get_client(key) is existing
        assert all(candidate.closes == 0 for candidate in controlled_transport.instances)
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("failure", ["protocol", "exception", "cancel"])
@pytest.mark.parametrize("cleanup_raises", [False, True])
async def test_bridge_closes_only_unpublished_candidate_on_preparation_failure(
    controlled_transport: Any, failure: str, cleanup_raises: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "candidate-secret-not-for-logs"
    controlled_transport.start_error = {
        "protocol": MCPProtocolError(secret, reason=secret),
        "exception": OSError(secret), "cancel": asyncio.CancelledError(),
    }[failure]
    controlled_transport.close_error = OSError(secret) if cleanup_raises else None
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    runtime = _Runtime(bridge, None)
    record = McpServerRecord(name="candidate", type="stdio", command="python")
    try:
        assert bridge.register_server("https://example.test/owned") is True
        owned = bridge.get_client("https://example.test/owned")
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await register_record(runtime, record, require_ready=True)
        else:
            assert await register_record(runtime, record, require_ready=True) is False
        assert len(controlled_transport.instances) == 1
        candidate = controlled_transport.instances[0]
        assert candidate.started is True and candidate.closes == 1
        assert bridge.get_client("candidate") is None
        assert bridge.get_client("https://example.test/owned") is owned
        assert secret not in caplog.text
    finally:
        await bridge.close_all()


async def test_candidate_cleanup_cancellation_does_not_replace_original_cancellation(
    controlled_transport: Any,
) -> None:
    original = asyncio.CancelledError("original")
    controlled_transport.start_error = original
    controlled_transport.close_error = asyncio.CancelledError("cleanup")
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            await bridge.register_stdio_server("cancel", "python", [], {}, "", reuse_if_matching=True)
        assert caught.value is original
        assert controlled_transport.instances[0].closes == 1
        assert bridge.list_servers() == []
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("pause_at", ["consent", "start"])
@pytest.mark.parametrize("matching", [False, True])
async def test_concurrent_stdio_registration_cannot_overwrite_owned_client(
    controlled_transport: Any, pause_at: str, matching: bool,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def pause_once() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()

    async def consent(context: dict[str, Any]) -> bool:
        if pause_at == "consent":
            await pause_once()
        return True

    if pause_at == "start":
        controlled_transport.start_hook = pause_once
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"], consent_fn=consent)
    first: asyncio.Task[bool] | None = None
    try:
        first = asyncio.create_task(bridge.register_stdio_server(
            "raced", "python", ["original"], {}, "", reuse_if_matching=True,
        ))
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert not first.done() and bridge.get_client("raced") is None
        assert await bridge.register_stdio_server(
            "raced", "python", ["original" if matching else "different"], {}, "",
            reuse_if_matching=True,
        ) is True
        winner = bridge.get_client("raced")
        assert winner is not None
        release.set()
        assert await asyncio.wait_for(first, timeout=5) is matching
        assert bridge.get_client("raced") is winner
        assert len(controlled_transport.instances) == (2 if pause_at == "start" else 1)
        assert [candidate.closes for candidate in controlled_transport.instances] == (
            [1, 0] if pause_at == "start" else [0]
        )
    finally:
        release.set()
        if first is not None:
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        await bridge.close_all()


async def test_stdio_arguments_and_environment_are_copied_before_consent_await(
    controlled_transport: Any,
) -> None:
    args = ["original"]
    env = {"TOKEN": "original"}

    async def consent(context: dict[str, Any]) -> bool:
        assert context["args"] == ["original"]
        context["args"].append("not-a-spawn-argument")
        args.append("changed")
        env["TOKEN"] = "changed"
        return True

    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"], consent_fn=consent)
    try:
        assert await bridge.register_stdio_server("copied", "python", args, env, "", reuse_if_matching=True) is True
        candidate = controlled_transport.instances[0]
        assert candidate.args == ["original"] and candidate.env["TOKEN"] == "original"
        assert await bridge.register_stdio_server(
            "copied", "python", ["original"], {"TOKEN": "original"}, "", reuse_if_matching=True,
        ) is True
        assert len(controlled_transport.instances) == 1
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("transport", ["http", "stdio"])
async def test_strict_retry_reuses_concrete_client_after_fulfilment_failure(
    controlled_transport: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: str,
) -> None:
    mcp_store = McpServerStore(db_path=str(tmp_path / "retry-mcp.db"))
    requests = CapabilityRequestStore(db_path=str(tmp_path / "retry-requests.db"))
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    vault = _FakeVault("original-secret")
    runtime = _Runtime(bridge, vault)
    runtime.mcp_server_store = mcp_store
    await mcp_store.start()
    try:
        await requests.start()
        record = await mcp_store.create(McpServerRecord(
            name="retry", type=transport, url="https://example.test/retry", command="python",
            args=["echo"], env={"MODE": "test"}, timeout_seconds=9.0, enabled=False,
            auth_kind="static", credential_ref="mcp:retry", auth_env_var="API_KEY",
        ))
        key = record.url if transport == "http" else record.name
        request = await requests.file_request(
            "agent-1", "install", record.name,
            payload={"install_kind": "mcp", "mcp_server_id": record.id},
        )
        await requests.decide(request.id, approve=True)
        mark = requests.mark_fulfilled

        async def fail_mark(request_id: str) -> CapabilityRequest | None:
            assert bridge.get_client(key) is not None
            raise OSError("fulfilment unavailable")

        monkeypatch.setattr(requests, "mark_fulfilled", fail_mark)
        with pytest.raises(OSError, match="fulfilment unavailable"):
            await fulfil_install(request.id, store=requests, target=record.name, runtime=runtime)
        client = bridge.get_client(key)
        assert client is not None
        assert (await mcp_store.get(record.id)).enabled is True
        monkeypatch.setattr(requests, "mark_fulfilled", mark)
        vault.value = "changed-secret"
        assert await fulfil_install(request.id, store=requests, target=record.name, runtime=runtime) is None
        assert bridge.get_client(key) is client
        assert (await mcp_store.get(record.id)).enabled is True
        assert (await requests.get(request.id)).status == "approved"
        vault.value = "original-secret"
        result = await fulfil_install(request.id, store=requests, target=record.name, runtime=runtime)
        assert result is not None and result.status == "fulfilled"
        assert bridge.get_client(key) is client
        assert len(controlled_transport.instances) == (1 if transport == "stdio" else 0)
        assert all(candidate.closes == 0 for candidate in controlled_transport.instances)
        assert runtime.ensure_calls == []
    finally:
        await bridge.close_all()
        await requests.stop()
        await mcp_store.stop()


async def test_strict_dead_stdio_retry_replaces_only_matching_client(controlled_transport: Any) -> None:
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    arguments = ("replace", "python", ["echo"], {"MODE": "same"}, "")
    try:
        assert await bridge.register_stdio_server(*arguments, reuse_if_matching=True) is True
        original = bridge.get_client("replace")
        assert original is not None and original.is_alive is True
        old_transport = controlled_transport.instances[0]
        assert bridge.register_server("https://example.test/unrelated") is True
        unrelated = bridge.get_client("https://example.test/unrelated")
        old_transport.alive = False
        assert original.is_alive is False

        assert await bridge.register_stdio_server(*arguments, reuse_if_matching=True) is True

        replacement = bridge.get_client("replace")
        assert replacement is not None and replacement is not original
        assert replacement.is_alive is True
        assert bridge.get_client("https://example.test/unrelated") is unrelated
        assert len(controlled_transport.instances) == 2
        assert [candidate.closes for candidate in controlled_transport.instances] == [1, 0]
        assert await bridge.register_stdio_server(*arguments, reuse_if_matching=True) is True
        assert bridge.get_client("replace") is replacement
        assert len(controlled_transport.instances) == 2
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("already_registered", [False, True])
async def test_strict_unknown_stdio_liveness_refuses_without_replacing_owner(
    monkeypatch: pytest.MonkeyPatch, already_registered: bool,
) -> None:
    from tests.test_ad1014_stdio_mcp_transport import _FakeTransport

    transport = _FakeTransport(envelope={"result": {"tools": []}})
    monkeypatch.setattr(
        "probos.integrations.mcp_bridge.bridge.StdioTransport", lambda **kwargs: transport,
    )
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    arguments = ("unknown", "python", [], {}, "")
    try:
        if already_registered:
            assert await bridge.register_stdio_server(*arguments) is True
        original = bridge.get_client("unknown")
        if original is not None:
            assert original.is_alive is None
            assert await original.list_tools() == []

        assert await bridge.register_stdio_server(*arguments, reuse_if_matching=True) is False

        assert bridge.get_client("unknown") is original
        assert transport.started is True
        assert transport.closed is (not already_registered)
        if already_registered:
            assert await bridge.register_stdio_server(
                "unknown", "python", ["different"], {}, "", reuse_if_matching=True,
            ) is False
            assert bridge.get_client("unknown") is original and transport.closed is False
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("strict", [False, True])
async def test_fresh_dead_stdio_requires_liveness_only_in_strict_mode(
    controlled_transport: Any, strict: bool,
) -> None:
    controlled_transport.alive_after_start = False
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    try:
        assert await bridge.register_stdio_server(
            "dead", "python", [], {}, "", reuse_if_matching=strict,
        ) is (not strict)
        candidate = controlled_transport.instances[0]
        assert candidate.started is True and candidate.is_alive is False
        assert candidate.closes == (1 if strict else 0)
        if strict:
            assert bridge.get_client("dead") is None
        else:
            existing = bridge.get_client("dead")
            assert existing is not None and existing.is_alive is False
            assert await bridge.register_stdio_server("dead", "python", [], {}, "") is False
            assert bridge.get_client("dead") is existing and candidate.closes == 0
        assert len(controlled_transport.instances) == 1
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("error_type", [OSError, AttributeError, asyncio.CancelledError])
@pytest.mark.parametrize("already_registered", [False, True])
async def test_stdio_liveness_errors_preserve_owner_or_close_unpublished_candidate(
    controlled_transport: Any, error_type: type[BaseException], already_registered: bool,
) -> None:
    failure = error_type("liveness failure")
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    try:
        if already_registered:
            assert await bridge.register_stdio_server("error", "python", [], {}, "") is True
            controlled_transport.instances[0].liveness_failure = failure
        else:
            controlled_transport.liveness_error = failure
        original = bridge.get_client("error")

        with pytest.raises(error_type) as caught:
            await bridge.register_stdio_server("error", "python", [], {}, "", reuse_if_matching=True)

        assert caught.value is failure
        assert len(controlled_transport.instances) == 1
        assert controlled_transport.instances[0].closes == (0 if already_registered else 1)
        assert bridge.get_client("error") is original
    finally:
        await bridge.close_all()


@pytest.mark.parametrize("transport", ["http", "stdio"])
@pytest.mark.parametrize("state", [
    "alive", "dead", "unknown", "truthy", "unsupported", "missing", "error", "cancel",
])
async def test_strict_registrar_requires_positive_stdio_liveness_without_http_probe(
    transport: str, state: str,
) -> None:
    reads = 0

    class _ReportedClient:
        @property
        def is_alive(self) -> object:
            nonlocal reads
            reads += 1
            if state == "error":
                raise OSError("liveness unavailable")
            if state == "cancel":
                raise asyncio.CancelledError()
            return {"alive": True, "dead": False, "unknown": None, "truthy": 1}[state]

    reported = None if state == "missing" else object() if state == "unsupported" else _ReportedClient()

    class _ReportingBridge(_RecordingBridge):
        def get_client(self, key: str) -> object | None:
            return reported

    bridge = _ReportingBridge()
    record = McpServerRecord(
        name="reported", type=transport, command="python", url="https://example.test/reported",
    )
    if transport == "stdio" and state == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await register_record(_Runtime(bridge, None), record, require_ready=True)
    else:
        expected = state != "missing" if transport == "http" else state == "alive"
        assert await register_record(_Runtime(bridge, None), record, require_ready=True) is expected
    assert reads == (1 if transport == "stdio" and state not in ("missing", "unsupported") else 0)
    assert len(bridge.http if transport == "http" else bridge.stdio) == 1
    assert bridge.unregistered == [], "the registrar must not clean up bridge-owned clients"


@pytest.mark.parametrize("winner_state", ["matching", "mismatching", "dead"])
async def test_dead_stdio_cleanup_rechecks_current_winner_without_replacement_loop(
    controlled_transport: Any, winner_state: str,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pause_cleanup() -> None:
        entered.set()
        await release.wait()

    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    arguments = ("raced", "python", ["original"], {}, "")
    retry: asyncio.Task[bool] | None = None
    try:
        assert await bridge.register_stdio_server(*arguments, reuse_if_matching=True) is True
        original = bridge.get_client("raced")
        old_transport = controlled_transport.instances[0]
        old_transport.alive = False
        old_transport.close_hook = pause_cleanup
        retry = asyncio.create_task(bridge.register_stdio_server(*arguments, reuse_if_matching=True))
        await asyncio.wait_for(entered.wait(), timeout=5.0)
        assert not retry.done() and old_transport.closes == 1
        assert bridge.get_client("raced") is None
        assert "raced" not in bridge._registration_config
        winner_args = ["different" if winner_state == "mismatching" else "original"]
        assert await bridge.register_stdio_server(
            "raced", "python", winner_args, {}, "", reuse_if_matching=True,
        ) is True
        winner = bridge.get_client("raced")
        assert winner is not None and winner is not original
        if winner_state == "dead":
            controlled_transport.instances[1].alive = False
            assert winner.is_alive is False

        release.set()
        assert await asyncio.wait_for(retry, timeout=5.0) is (winner_state == "matching")

        assert bridge.get_client("raced") is winner
        assert len(controlled_transport.instances) == 2, "a dead winner waits for an explicit retry"
        assert [candidate.closes for candidate in controlled_transport.instances] == [1, 0]
        if winner_state != "dead":
            assert await bridge.register_stdio_server(
                "raced", "python", winner_args, {}, "", reuse_if_matching=True,
            ) is True
            assert bridge.get_client("raced") is winner
    finally:
        release.set()
        if retry is not None:
            if not retry.done():
                retry.cancel()
            await asyncio.gather(retry, return_exceptions=True)
        await bridge.close_all()


@pytest.mark.parametrize("failure", ["cancel", "cleanup-error"])
@pytest.mark.parametrize("matching", [False, True])
async def test_dead_stdio_cleanup_failure_cannot_succeed_or_detach_new_owner(
    controlled_transport: Any, failure: str, matching: bool,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pause_cleanup() -> None:
        entered.set()
        await release.wait()

    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    retry: asyncio.Task[bool] | None = None
    old_transport = None
    try:
        assert await bridge.register_stdio_server("raced", "python", ["original"], {}, "") is True
        old_transport = controlled_transport.instances[0]
        old_transport.alive = False
        old_transport.close_hook = pause_cleanup
        retry = asyncio.create_task(bridge.register_stdio_server(
            "raced", "python", ["original"], {}, "", reuse_if_matching=True,
        ))
        await asyncio.wait_for(entered.wait(), timeout=5.0)
        assert not retry.done() and bridge.get_client("raced") is None
        assert "raced" not in bridge._registration_config
        winner_args = ["original" if matching else "different"]
        assert await bridge.register_stdio_server(
            "raced", "python", winner_args, {}, "", reuse_if_matching=True,
        ) is True
        winner = bridge.get_client("raced")
        assert winner is not None

        if failure == "cancel":
            retry.cancel()
            with pytest.raises(asyncio.CancelledError):
                await retry
        else:
            old_transport.close_failure = OSError("dead client cleanup failed")
            release.set()
            with pytest.raises(OSError, match="dead client cleanup failed"):
                await asyncio.wait_for(retry, timeout=5.0)

        assert bridge.get_client("raced") is winner and winner.is_alive is True
        assert [candidate.closes for candidate in controlled_transport.instances] == [1, 0]
        assert await bridge.register_stdio_server(
            "raced", "python", winner_args, {}, "", reuse_if_matching=True,
        ) is True
        assert len(controlled_transport.instances) == 2
    finally:
        release.set()
        if retry is not None:
            if not retry.done():
                retry.cancel()
            await asyncio.gather(retry, return_exceptions=True)
        if old_transport is not None:
            old_transport.close_failure = None
            old_transport.close_hook = None
            await old_transport.close()
        await bridge.close_all()


@pytest.mark.parametrize("failure", ["cancel", "start-error"])
@pytest.mark.parametrize("matching", [False, True])
async def test_paused_stdio_start_failure_closes_only_candidate_not_new_owner(
    controlled_transport: Any, failure: str, matching: bool,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    starts = 0

    async def pause_first_start() -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            entered.set()
            await release.wait()

    controlled_transport.start_hook = pause_first_start
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    preparing: asyncio.Task[bool] | None = None
    try:
        preparing = asyncio.create_task(bridge.register_stdio_server(
            "raced", "python", ["original"], {}, "", reuse_if_matching=True,
        ))
        await asyncio.wait_for(entered.wait(), timeout=5.0)
        assert not preparing.done() and bridge.get_client("raced") is None
        winner_args = ["original" if matching else "different"]
        assert await bridge.register_stdio_server(
            "raced", "python", winner_args, {}, "", reuse_if_matching=True,
        ) is True
        winner = bridge.get_client("raced")
        assert winner is not None
        if failure == "cancel":
            preparing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preparing
        else:
            controlled_transport.instances[0].error = MCPProtocolError("controlled start failure")
            release.set()
            assert await asyncio.wait_for(preparing, timeout=5.0) is False
        assert bridge.get_client("raced") is winner and winner.is_alive is True
        assert [candidate.closes for candidate in controlled_transport.instances] == [1, 0]
        assert await bridge.register_stdio_server(
            "raced", "python", winner_args, {}, "", reuse_if_matching=True,
        ) is True
        assert len(controlled_transport.instances) == 2
    finally:
        release.set()
        if preparing is not None:
            if not preparing.done():
                preparing.cancel()
            await asyncio.gather(preparing, return_exceptions=True)
        await bridge.close_all()


@pytest.mark.parametrize("initial_matching,change", [
    (True, "matching"), (True, "mismatching"), (False, "matching"),
    (True, "dead"), (True, "removed"), (True, "liveness-error"),
    (True, "cancel"), (True, "cleanup-error"),
])
async def test_losing_stdio_candidate_rechecks_winner_after_cleanup(
    controlled_transport: Any, initial_matching: bool, change: str,
) -> None:
    start_entered = asyncio.Event()
    start_release = asyncio.Event()
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    starts = 0

    async def pause_first_start() -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            start_entered.set()
            await start_release.wait()

    async def pause_cleanup() -> None:
        cleanup_entered.set()
        await cleanup_release.wait()

    controlled_transport.start_hook = pause_first_start
    bridge = MCPBridge(stdio_enabled=True, command_allowlist=["python"])
    preparing: asyncio.Task[bool] | None = None
    candidate = None
    try:
        preparing = asyncio.create_task(bridge.register_stdio_server(
            "raced", "python", ["original"], {}, "", reuse_if_matching=True,
        ))
        await asyncio.wait_for(start_entered.wait(), timeout=5.0)
        assert not preparing.done() and bridge.get_client("raced") is None
        candidate = controlled_transport.instances[0]
        candidate.close_hook = pause_cleanup
        assert await bridge.register_stdio_server(
            "raced", "python", ["original" if initial_matching else "different"], {}, "",
            reuse_if_matching=True,
        ) is True
        previous_winner = bridge.get_client("raced")
        assert previous_winner is not None
        start_release.set()
        await asyncio.wait_for(cleanup_entered.wait(), timeout=5.0)
        assert not preparing.done() and candidate.closes == 1
        assert bridge.get_client("raced") is previous_winner
        assert controlled_transport.instances[1].closes == 0

        if change in ("matching", "mismatching", "removed"):
            assert await bridge.unregister_server("raced") is True
            assert controlled_transport.instances[1].closes == 1
            if change != "removed":
                assert await bridge.register_stdio_server(
                    "raced", "python", ["original" if change == "matching" else "new-config"],
                    {}, "", reuse_if_matching=True,
                ) is True
        elif change == "dead":
            controlled_transport.instances[1].alive = False
        elif change == "liveness-error":
            controlled_transport.instances[1].liveness_failure = OSError("winner liveness failed")
        elif change == "cleanup-error":
            candidate.close_failure = OSError("loser cleanup failed")
        winner = bridge.get_client("raced")

        if change == "cancel":
            preparing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await preparing
        else:
            cleanup_release.set()
            if change == "liveness-error":
                with pytest.raises(OSError, match="winner liveness failed"):
                    await asyncio.wait_for(preparing, timeout=5.0)
            else:
                assert await asyncio.wait_for(preparing, timeout=5.0) is (change == "matching")

        assert bridge.get_client("raced") is winner
        assert candidate.closes == 1
        assert len(controlled_transport.instances) == (3 if change in ("matching", "mismatching") else 2)
        if change in ("matching", "mismatching"):
            assert winner is not None and winner is not previous_winner and winner.is_alive is True
            assert controlled_transport.instances[2].closes == 0
        elif change == "removed":
            assert winner is None
        else:
            assert winner is previous_winner
            assert controlled_transport.instances[1].closes == 0
        if change == "dead":
            assert winner is not None and winner.is_alive is False
    finally:
        start_release.set()
        cleanup_release.set()
        if preparing is not None:
            if not preparing.done():
                preparing.cancel()
            await asyncio.gather(preparing, return_exceptions=True)
        if candidate is not None and change in ("cancel", "cleanup-error"):
            candidate.close_hook = None
            candidate.close_failure = None
            await candidate.close()
        await bridge.close_all()


@pytest.mark.parametrize("write_path", ["create", "update"])
async def test_unknown_auth_kind_is_reachable_from_store_and_strictly_refused(
    tmp_path: Path, write_path: str,
) -> None:
    store = McpServerStore(db_path=str(tmp_path / "unknown-auth.db"))
    bridge = MCPBridge()
    await store.start()
    try:
        record = await store.create(McpServerRecord(
            name="unknown-auth", type="http", url="https://example.test/unknown",
            auth_kind="unsupported" if write_path == "create" else "none", enabled=False,
        ))
        if write_path == "update":
            record = await store.update(record.id, auth_kind="unsupported")
        assert record is not None
        await store.stop()
        await store.start()
        restored = await store.get(record.id)
        assert restored is not None and restored.auth_kind == "unsupported"
        assert await register_record(_Runtime(bridge, None), restored, require_ready=True) is False
        assert (await store.get(record.id)).enabled is False
        assert bridge.list_servers() == []
    finally:
        await bridge.close_all()
        await store.stop()


@pytest.mark.parametrize("value", ["line\nbreak", "carriage\rreturn", "nul\x00byte", 123, []])
async def test_invalid_resolved_credentials_preserve_concrete_http_client(
    value: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    bridge = MCPBridge()
    record = McpServerRecord(
        name="invalid", type="http", url="https://example.test/invalid",
        auth_kind="static", credential_ref="mcp:invalid",
    )
    vault = _FakeVault("valid")
    runtime = _Runtime(bridge, vault)
    try:
        assert await register_record(runtime, record, require_ready=True) is True
        client = bridge.get_client(record.url)
        assert client is not None
        vault.value = value
        assert await register_record(runtime, record, require_ready=True) is False
        assert bridge.get_client(record.url) is client
        assert "carriage" not in caplog.text and "line" not in caplog.text and "nul" not in caplog.text
    finally:
        await bridge.close_all()
