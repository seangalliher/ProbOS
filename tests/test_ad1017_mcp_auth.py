"""AD-1017: MCP server authentication (static tokens + OAuth) tests.

BF-287: a real ``McpServerStore`` (``db_path=""`` cache-only), a real
``EncryptedFileCredentialVault`` on ``tmp_path`` (a test crew token via
``_derive_kek``), a real ``MCPBridge``, a real ``SystemConfig``, and a real
``TestClient`` — no MagicMock at the store / vault / bridge / config boundary.
Only the external httpx OAuth token exchange is monkeypatched (via the
provider's ``http_client_factory`` + ``httpx.MockTransport``).

SECURITY: the secret value lives ONLY in the vault by ref — never in the store
row, never in any API response body, never logged. The relevant assertions are
``test_static_token_never_in_store_row_or_response`` and
``test_oauth_token_never_in_response`` and ``test_no_secret_value_in_logs``.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1017_mcp_auth.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import MCPConfig, SystemConfig
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge import mcp_oauth as oauth_module
from probos.integrations.mcp_bridge.mcp_oauth import McpOAuthError, McpOAuthProvider
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.routers.mcp_servers import (
    _clear_state_stores,
    _get_state_store,
    _resolve_auth_env,
    _resolve_auth_headers,
)
from probos.tools.browser.credentials import (
    CredentialScope,
    EncryptedFileCredentialVault,
    _derive_kek,
)

_CREW_TOKEN = "ad1017-test-crew-token"


# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #


class _Runtime:
    """A real (non-Mock) runtime stub exposing exactly what the router reads."""

    def __init__(
        self, config: SystemConfig, store: Any, bridge: Any, vault: Any
    ) -> None:
        self.config = config
        self.mcp_server_store = store
        self.mcp_bridge = bridge
        self.credential_vault = vault


def _config(*, management_enabled: bool = True) -> SystemConfig:
    return SystemConfig(
        mcp=MCPConfig(
            management_enabled=management_enabled,
            command_allowlist=["uvx", "npx", "python", "node", "docker", sys.executable],
            request_timeout_seconds=5.0,
        )
    )


def _bridge() -> MCPBridge:
    return MCPBridge(
        emit_event=None,
        request_timeout=5.0,
        stdio_enabled=False,
        command_allowlist=[sys.executable],
    )


def _vault(tmp_path: Path) -> EncryptedFileCredentialVault:
    return EncryptedFileCredentialVault(
        path=tmp_path / "vault.json",
        kek=_derive_kek(_CREW_TOKEN),
        crew_scope_token=_CREW_TOKEN,
    )


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.mcp_servers import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _make(
    tmp_path: Path,
    *,
    management_enabled: bool = True,
    vault: Any = "default",
) -> tuple[TestClient, _Runtime]:
    real_store = McpServerStore(db_path="")
    real_bridge = _bridge()
    real_vault = _vault(tmp_path) if vault == "default" else vault
    runtime = _Runtime(
        _config(management_enabled=management_enabled),
        real_store,
        real_bridge,
        real_vault,
    )
    return _client(runtime), runtime


_HTTP_BODY = {"name": "weather", "type": "http", "url": "https://example.com/mcp"}


@pytest.fixture(autouse=True)
def _reset_state_stores() -> Any:
    _clear_state_stores()
    yield
    _clear_state_stores()


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Inject an ``httpx.MockTransport`` into every ``McpOAuthProvider``.

    Mirrors the AD-720c cloud-picker endpoint-test seam: patch ``__init__`` to
    add an ``http_client_factory`` kwarg — so router-constructed providers use
    the mock instead of a real network call.
    """
    original = oauth_module.McpOAuthProvider.__init__

    def _patched(self: Any, **kwargs: Any) -> None:
        kwargs["http_client_factory"] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        )
        original(self, **kwargs)

    monkeypatch.setattr(oauth_module.McpOAuthProvider, "__init__", _patched)


def _token_handler(request: httpx.Request) -> httpx.Response:
    """One handler for both grants: branch on the form body's grant_type."""
    body = request.content.decode("utf-8")
    if "grant_type=refresh_token" in body:
        return httpx.Response(
            200, json={"access_token": "access-REFRESHED", "expires_in": 3600}
        )
    return httpx.Response(
        200,
        json={
            "access_token": "access-xyz",
            "refresh_token": "refresh-abc",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )


_OAUTH_START_BODY = {
    "client_id": "cid",
    "client_secret": "csecret",
    "authorize_url": "https://auth.example.com/authorize",
    "token_url": "https://auth.example.com/token",
    "scopes": ["read"],
    "redirect_uri": "https://app.example.com/callback",
}


# --------------------------------------------------------------------------- #
# Gate (management_enabled=False ⇒ new endpoints 404)
# --------------------------------------------------------------------------- #


def test_gate_off_new_endpoints_404(tmp_path: Path) -> None:
    client, _ = _make(tmp_path, management_enabled=False)
    assert client.post("/api/mcp/servers/x/credential", json={"value": "t"}).status_code == 404
    assert client.delete("/api/mcp/servers/x/credential").status_code == 404
    assert client.post("/api/mcp/servers/x/auth/start", json={}).status_code == 404
    assert client.get("/api/mcp/servers/x/auth/callback?code=c&state=s").status_code == 404
    assert client.post("/api/mcp/servers/x/auth/refresh").status_code == 404


# --------------------------------------------------------------------------- #
# Static credential
# --------------------------------------------------------------------------- #


def _create_http(client: TestClient, **overrides: Any) -> dict[str, Any]:
    return client.post("/api/mcp/servers", json={**_HTTP_BODY, **overrides}).json()


def test_set_credential_returns_static_kind_and_ref(tmp_path: Path) -> None:
    client, _ = _make(tmp_path)
    created = _create_http(client)
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "tok-123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_kind"] == "static"
    assert body["credential_ref"] == f"mcp:{created['id']}"


async def test_set_credential_value_in_vault_async(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "tok-123"}
    )
    val = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}", requesting_agent_id="captain"
    )
    assert val == "tok-123"


def test_set_credential_503_when_no_vault(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    runtime.credential_vault = None
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "tok"}
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "credential_vault_unavailable"


def test_set_credential_404_unknown_server(tmp_path: Path) -> None:
    client, _ = _make(tmp_path)
    assert (
        client.post("/api/mcp/servers/nope/credential", json={"value": "t"}).status_code
        == 404
    )


def test_set_credential_registers_with_injected_header(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    # Created enabled+http -> registered with no auth header.
    assert runtime.mcp_bridge.get_client("https://example.com/mcp").session.headers == {}
    client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "tok-123"}
    )
    client_obj = runtime.mcp_bridge.get_client("https://example.com/mcp")
    assert client_obj is not None
    assert client_obj.session.headers["Authorization"] == "Bearer tok-123"


def test_set_credential_custom_header_and_bare_scheme(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    client.post(
        f"/api/mcp/servers/{created['id']}/credential",
        json={"value": "raw-key", "header_name": "X-API-Key", "scheme": ""},
    )
    headers = runtime.mcp_bridge.get_client("https://example.com/mcp").session.headers
    assert headers["X-API-Key"] == "raw-key"  # bare value when scheme==""


def test_static_token_never_in_store_row_or_response(tmp_path: Path) -> None:
    client, _ = _make(tmp_path)
    created = _create_http(client)
    post_resp = client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "supersecret-tok"}
    )
    # Not in the POST response body.
    assert "supersecret-tok" not in post_resp.text
    # Not in the GET (store row serialization).
    get_resp = client.get(f"/api/mcp/servers/{created['id']}")
    assert "supersecret-tok" not in get_resp.text
    # Not in the list serialization.
    list_resp = client.get("/api/mcp/servers")
    assert "supersecret-tok" not in list_resp.text


def test_delete_credential_removes_and_clears(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "tok-123"}
    )
    resp = client.delete(f"/api/mcp/servers/{created['id']}/credential")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_kind"] == "none"
    assert body["credential_ref"] == ""
    # Re-registered without the auth header.
    headers = runtime.mcp_bridge.get_client("https://example.com/mcp").session.headers
    assert "Authorization" not in headers


async def test_delete_credential_purges_vault_async(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    client.post(
        f"/api/mcp/servers/{created['id']}/credential", json={"value": "tok-123"}
    )
    client.delete(f"/api/mcp/servers/{created['id']}/credential")
    val = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}", requesting_agent_id="captain"
    )
    assert val is None


def test_delete_credential_404_unknown_server(tmp_path: Path) -> None:
    client, _ = _make(tmp_path)
    assert client.delete("/api/mcp/servers/nope/credential").status_code == 404


# --------------------------------------------------------------------------- #
# _resolve_auth_headers / _resolve_auth_env (direct, incl. honest-degrade)
# --------------------------------------------------------------------------- #


async def test_resolve_auth_headers_none_is_empty(tmp_path: Path) -> None:
    _, runtime = _make(tmp_path)
    rec = McpServerRecord(name="x", type="http", url="u", auth_kind="none")
    assert await _resolve_auth_headers(rec, runtime) == {}


async def test_resolve_auth_headers_static_bearer(tmp_path: Path) -> None:
    _, runtime = _make(tmp_path)
    await runtime.credential_vault.store(
        ref="mcp:srv1", value="tok-9", scope=CredentialScope()
    )
    rec = McpServerRecord(
        name="x", type="http", url="u", id="srv1",
        auth_kind="static", credential_ref="mcp:srv1",
    )
    assert await _resolve_auth_headers(rec, runtime) == {"Authorization": "Bearer tok-9"}


async def test_resolve_auth_headers_vault_miss_degrades(tmp_path: Path) -> None:
    _, runtime = _make(tmp_path)
    rec = McpServerRecord(
        name="x", type="http", url="u", id="srv1",
        auth_kind="static", credential_ref="mcp:srv1",  # nothing stored
    )
    assert await _resolve_auth_headers(rec, runtime) == {}


async def test_resolve_auth_env_injects_when_var_set(tmp_path: Path) -> None:
    _, runtime = _make(tmp_path)
    await runtime.credential_vault.store(
        ref="mcp:srv1", value="env-tok", scope=CredentialScope()
    )
    rec = McpServerRecord(
        name="x", type="stdio", command="python", id="srv1",
        auth_kind="static", credential_ref="mcp:srv1", auth_env_var="API_KEY",
    )
    assert await _resolve_auth_env(rec, runtime) == {"API_KEY": "env-tok"}


async def test_resolve_auth_env_empty_when_no_var(tmp_path: Path) -> None:
    _, runtime = _make(tmp_path)
    await runtime.credential_vault.store(
        ref="mcp:srv1", value="env-tok", scope=CredentialScope()
    )
    rec = McpServerRecord(
        name="x", type="stdio", command="python", id="srv1",
        auth_kind="static", credential_ref="mcp:srv1", auth_env_var="",
    )
    assert await _resolve_auth_env(rec, runtime) == {}


# --------------------------------------------------------------------------- #
# auth_kind=="none" byte-identical register
# --------------------------------------------------------------------------- #


def test_register_none_byte_identical(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client, headers={"X-Trace": "1"})
    # No auth set: the session headers equal exactly the record's headers.
    headers = runtime.mcp_bridge.get_client("https://example.com/mcp").session.headers
    assert headers == {"X-Trace": "1"}
    assert created["auth_kind"] == "none"


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #


def test_oauth_start_returns_auth_url_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/start", json=_OAUTH_START_BODY
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_url"].startswith("https://auth.example.com/authorize?")
    assert f"state={body['state']}" in body["auth_url"]
    # State was minted into the per-runtime CSRF store.
    assert len(_get_state_store(runtime)) == 1


def test_oauth_start_secret_not_in_oauth_json_or_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/start", json=_OAUTH_START_BODY
    )
    assert "csecret" not in resp.text  # not in {auth_url,state}
    got = client.get(f"/api/mcp/servers/{created['id']}").json()
    assert "csecret" not in json.dumps(got)  # not in oauth_json on the row


async def test_oauth_start_secret_in_vault_async(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    client.post(f"/api/mcp/servers/{created['id']}/auth/start", json=_OAUTH_START_BODY)
    secret = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}:oauth_secret", requesting_agent_id="captain"
    )
    assert secret == "csecret"


def test_oauth_callback_invalid_state_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    resp = client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=c&state=bogus"
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid_state_token"


def _start_oauth(client: TestClient, server_id: str) -> str:
    resp = client.post(
        f"/api/mcp/servers/{server_id}/auth/start", json=_OAUTH_START_BODY
    )
    return resp.json()["state"]


def test_oauth_callback_persists_bundle_and_returns_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    resp = client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
    )
    assert resp.status_code == 200
    assert "window.close()" in resp.text  # same popup-close HTML shape
    assert "oauth_complete" in resp.text
    # Record flipped to oauth.
    got = client.get(f"/api/mcp/servers/{created['id']}").json()
    assert got["auth_kind"] == "oauth"
    assert got["credential_ref"] == f"mcp:{created['id']}:oauth"


async def test_oauth_callback_bundle_in_vault_async(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
    )
    raw = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}:oauth", requesting_agent_id="captain"
    )
    assert raw is not None
    bundle = json.loads(raw)
    assert bundle["access_token"] == "access-xyz"
    assert bundle["refresh_token"] == "refresh-abc"


async def test_oauth_resolve_auth_headers_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
    )
    rec = await runtime.mcp_server_store.get(created["id"])
    assert rec is not None
    assert await _resolve_auth_headers(rec, runtime) == {
        "Authorization": "Bearer access-xyz"
    }


def test_oauth_callback_exchange_failure_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    _install_mock_transport(monkeypatch, _fail_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    resp = client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=bad&state={state}"
    )
    assert resp.status_code == 502
    assert resp.json()["detail"] == "oauth_exchange_failed"


def test_oauth_refresh_restores_new_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
    )
    resp = client.post(f"/api/mcp/servers/{created['id']}/auth/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"refreshed": True}


async def test_oauth_refresh_new_token_in_vault_async(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
    )
    client.post(f"/api/mcp/servers/{created['id']}/auth/refresh")
    raw = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}:oauth", requesting_agent_id="captain"
    )
    bundle = json.loads(raw)
    assert bundle["access_token"] == "access-REFRESHED"
    # refresh_token preserved (mock refresh response omits one).
    assert bundle["refresh_token"] == "refresh-abc"


def test_oauth_refresh_no_token_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    # No prior callback -> no stored bundle.
    resp = client.post(f"/api/mcp/servers/{created['id']}/auth/refresh")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "no_refresh_token"


def test_oauth_token_never_in_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    state = _start_oauth(client, created["id"])
    cb = client.get(
        f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
    )
    assert "access-xyz" not in cb.text
    assert "refresh-abc" not in cb.text
    ref = client.post(f"/api/mcp/servers/{created['id']}/auth/refresh")
    assert "access-REFRESHED" not in ref.text
    got = client.get(f"/api/mcp/servers/{created['id']}").json()
    assert "access-xyz" not in json.dumps(got)  # no token surfaced on the row
    assert "access-REFRESHED" not in json.dumps(got)


# --------------------------------------------------------------------------- #
# No secret value in logs
# --------------------------------------------------------------------------- #


def test_no_secret_value_in_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_mock_transport(monkeypatch, _token_handler)
    client, _ = _make(tmp_path)
    created = _create_http(client)
    with caplog.at_level(logging.DEBUG):
        client.post(
            f"/api/mcp/servers/{created['id']}/credential",
            json={"value": "log-secret-tok"},
        )
        state = _start_oauth(client, created["id"])
        client.get(
            f"/api/mcp/servers/{created['id']}/auth/callback?code=auth-code&state={state}"
        )
        client.post(f"/api/mcp/servers/{created['id']}/auth/refresh")
    assert "log-secret-tok" not in caplog.text
    assert "csecret" not in caplog.text
    assert "access-xyz" not in caplog.text
    assert "access-REFRESHED" not in caplog.text


# --------------------------------------------------------------------------- #
# McpOAuthProvider unit tests (MockTransport)
# --------------------------------------------------------------------------- #


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> McpOAuthProvider:
    return McpOAuthProvider(
        client_id="cid",
        client_secret="csec",
        authorize_url="https://auth/authorize",
        token_url="https://auth/token",
        scopes=["read", "write"],
        redirect_uri="https://app/cb",
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        ),
    )


def test_provider_start_authorization_builds_url() -> None:
    url = _provider(_token_handler).start_authorization(state="st8")
    assert url.startswith("https://auth/authorize?")
    assert "client_id=cid" in url
    assert "response_type=code" in url
    assert "scope=read+write" in url
    assert "state=st8" in url


async def test_provider_handle_callback_exchanges_code() -> None:
    bundle = await _provider(_token_handler).handle_callback(code="auth-code")
    assert bundle.access_token == "access-xyz"
    assert bundle.refresh_token == "refresh-abc"
    assert bundle.expires_at > 0


async def test_provider_refresh_preserves_prior_refresh_token() -> None:
    bundle = await _provider(_token_handler).refresh(refresh_token="refresh-abc")
    assert bundle.access_token == "access-REFRESHED"
    assert bundle.refresh_token == "refresh-abc"  # response omits -> prior preserved


async def test_provider_non_200_raises() -> None:
    def _bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "nope"})

    with pytest.raises(McpOAuthError) as exc:
        await _provider(_bad).handle_callback(code="x")
    assert exc.value.detail == "oauth_exchange_failed"


async def test_provider_no_access_token_raises() -> None:
    def _empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})

    with pytest.raises(McpOAuthError) as exc:
        await _provider(_empty).handle_callback(code="x")
    assert exc.value.detail == "oauth_no_access_token"


async def test_provider_transport_error_raises() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(McpOAuthError) as exc:
        await _provider(_boom).handle_callback(code="x")
    assert exc.value.detail == "oauth_exchange_failed"


# --------------------------------------------------------------------------- #
# Store migration: AD-1015 rows gain the AD-1017 columns with defaults
# --------------------------------------------------------------------------- #

_AD1015_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    url TEXT DEFAULT '',
    headers_json TEXT DEFAULT '{}',
    command TEXT DEFAULT '',
    args_json TEXT DEFAULT '[]',
    env_json TEXT DEFAULT '{}',
    cwd TEXT DEFAULT '',
    timeout_seconds REAL,
    enabled INTEGER NOT NULL DEFAULT 1,
    auth_kind TEXT NOT NULL DEFAULT 'none',
    credential_ref TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


async def test_migration_reads_pre_ad1017_row_with_defaults(tmp_path: Path) -> None:
    import aiosqlite

    db = str(tmp_path / "legacy.db")
    # Build an AD-1015-shaped DB (no AD-1017 columns) + one row.
    conn = await aiosqlite.connect(db)
    await conn.executescript(_AD1015_SCHEMA)
    await conn.execute(
        "INSERT INTO mcp_servers (id, name, type, url, headers_json, command, "
        "args_json, env_json, cwd, timeout_seconds, enabled, auth_kind, "
        "credential_ref, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy1", "old", "http", "https://old/mcp", "{}", "", "[]", "{}", "",
         None, 1, "none", "", 1.0, 1.0),
    )
    await conn.commit()
    await conn.close()
    # AD-1017 store migrates the table on start() and reads the row.
    store = McpServerStore(db_path=db)
    await store.start()
    try:
        rec = await store.get("legacy1")
        assert rec is not None
        assert rec.name == "old"
        assert rec.auth_header_name == "Authorization"  # column default
        assert rec.auth_scheme == "Bearer"
        assert rec.auth_env_var == ""
        assert rec.oauth_json == ""
    finally:
        await store.stop()


async def test_new_db_roundtrips_auth_fields(tmp_path: Path) -> None:
    db = str(tmp_path / "fresh.db")
    store = McpServerStore(db_path=db)
    await store.start()
    rec = await store.create(
        McpServerRecord(
            name="weather", type="http", url="https://example.com/mcp",
            auth_kind="static", credential_ref="mcp:x",
            auth_header_name="X-API-Key", auth_scheme="", auth_env_var="API_KEY",
            oauth_json='{"client_id":"cid"}',
        )
    )
    await store.stop()
    store2 = McpServerStore(db_path=db)
    await store2.start()
    try:
        loaded = await store2.get(rec.id)
        assert loaded is not None
        assert loaded.auth_header_name == "X-API-Key"
        assert loaded.auth_scheme == ""
        assert loaded.auth_env_var == "API_KEY"
        assert loaded.oauth_json == '{"client_id":"cid"}'
    finally:
        await store2.stop()
