"""AD-1017a: MCP OAuth device-code (RFC 8628) tests.

BF-287: a real ``McpServerStore`` (``db_path=""`` cache-only), a real
``EncryptedFileCredentialVault`` on ``tmp_path``, a real ``MCPBridge``, a real
``SystemConfig``, and a real ``TestClient`` — no MagicMock at the store / vault
/ bridge / config boundary. Only the external httpx calls (the device-
authorization POST + the token-poll POST) are mocked, via the provider's
``http_client_factory`` + ``httpx.MockTransport`` (mirrors test_ad1017_mcp_auth).

SECURITY: the ``device_code`` poll secret is held SERVER-SIDE in ``_DEVICE_FLOWS``
keyed by an opaque ``flow_id``; it is never in any response body or log. Token
values + ``client_secret`` live ONLY in the vault by ref. The relevant
assertions are ``test_device_start_happy_and_secret_vaulted`` and
``test_device_code_and_token_never_in_response_or_logs``.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1017a_mcp_device_code.py -q -n 0 -p no:cacheprovider
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
from probos.integrations.mcp_bridge.store import McpServerStore
from probos.routers.mcp_servers import _clear_device_flows
from probos.tools.browser.credentials import (
    EncryptedFileCredentialVault,
    _derive_kek,
)

_CREW_TOKEN = "ad1017a-test-crew-token"


# --------------------------------------------------------------------------- #
# Fixtures / builders (mirror test_ad1017_mcp_auth.py)
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

_DEVICE_START_BODY = {
    "client_id": "cid",
    "client_secret": "csecret",
    "device_authorization_url": "https://auth.example.com/device",
    "token_url": "https://auth.example.com/token",
    "scopes": ["read"],
}


@pytest.fixture(autouse=True)
def _reset_device_flows() -> Any:
    _clear_device_flows()
    yield
    _clear_device_flows()


def _create_http(client: TestClient, **overrides: Any) -> dict[str, Any]:
    return client.post("/api/mcp/servers", json={**_HTTP_BODY, **overrides}).json()


def _device_start_payload() -> dict[str, Any]:
    return {
        "device_code": "dev-code-SECRET",
        "user_code": "WDJB-MJHT",
        "verification_uri": "https://verify.example.com",
        "verification_uri_complete": "https://verify.example.com?user_code=WDJB-MJHT",
        "expires_in": 600,
        "interval": 5,
    }


def _flow_handler(poll: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """Branch on grant_type: device-auth start (no grant_type) vs token poll."""

    def _h(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        if "grant_type=" in body:
            return poll
        return httpx.Response(200, json=_device_start_payload())

    return _h


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Inject an ``httpx.MockTransport`` into every router-built provider."""
    original = oauth_module.McpOAuthProvider.__init__

    def _patched(self: Any, **kwargs: Any) -> None:
        kwargs["http_client_factory"] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        )
        original(self, **kwargs)

    monkeypatch.setattr(oauth_module.McpOAuthProvider, "__init__", _patched)


def _device_provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> McpOAuthProvider:
    return McpOAuthProvider(
        client_id="cid",
        client_secret="csec",
        authorize_url="https://auth/authorize",
        token_url="https://auth/token",
        device_authorization_url="https://auth/device",
        scopes=["read", "write"],
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        ),
    )


# --------------------------------------------------------------------------- #
# McpOAuthProvider unit tests (MockTransport)
# --------------------------------------------------------------------------- #


async def test_start_device_authorization_happy_returns_payload() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_device_start_payload())

    info = await _device_provider(_h).start_device_authorization()
    assert info["device_code"] == "dev-code-SECRET"
    assert info["user_code"] == "WDJB-MJHT"
    assert info["verification_uri"] == "https://verify.example.com"


async def test_start_device_authorization_non_200_raises() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server_error"})

    with pytest.raises(McpOAuthError) as exc:
        await _device_provider(_h).start_device_authorization()
    assert exc.value.detail == "device_authorization_failed"


async def test_start_device_authorization_missing_device_code_raises() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"user_code": "X", "verification_uri": "https://v"}
        )

    with pytest.raises(McpOAuthError) as exc:
        await _device_provider(_h).start_device_authorization()
    assert exc.value.detail == "device_authorization_invalid"


async def test_poll_device_token_success_returns_bundle() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "access-DEVICE", "expires_in": 3600}
        )

    bundle = await _device_provider(_h).poll_device_token(device_code="dc")
    assert bundle is not None
    assert bundle.access_token == "access-DEVICE"


async def test_poll_device_token_authorization_pending_returns_none() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "authorization_pending"})

    assert await _device_provider(_h).poll_device_token(device_code="dc") is None


async def test_poll_device_token_slow_down_returns_none() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "slow_down"})

    assert await _device_provider(_h).poll_device_token(device_code="dc") is None


async def test_poll_device_token_access_denied_raises_400() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "access_denied"})

    with pytest.raises(McpOAuthError) as exc:
        await _device_provider(_h).poll_device_token(device_code="dc")
    assert exc.value.status == 400
    assert exc.value.detail == "access_denied"


async def test_poll_device_token_expired_token_raises() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "expired_token"})

    with pytest.raises(McpOAuthError) as exc:
        await _device_provider(_h).poll_device_token(device_code="dc")
    assert exc.value.status == 400
    assert exc.value.detail == "expired_token"


async def test_poll_device_token_transport_error_raises() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(McpOAuthError) as exc:
        await _device_provider(_h).poll_device_token(device_code="dc")
    assert exc.value.detail == "device_token_failed"


# --------------------------------------------------------------------------- #
# Gate (management_enabled=False ⇒ device endpoints 404)
# --------------------------------------------------------------------------- #


def test_device_gate_off_404(tmp_path: Path) -> None:
    client, _ = _make(tmp_path, management_enabled=False)
    assert (
        client.post("/api/mcp/servers/x/auth/device/start", json={}).status_code == 404
    )
    assert (
        client.post(
            "/api/mcp/servers/x/auth/device/poll", json={"flow_id": "f"}
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# device/start
# --------------------------------------------------------------------------- #


async def test_device_start_happy_and_secret_vaulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(
        monkeypatch, _flow_handler(httpx.Response(400, json={"error": "x"}))
    )
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/start", json=_DEVICE_START_BODY
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["flow_id"]
    assert body["user_code"] == "WDJB-MJHT"
    assert body["verification_uri"] == "https://verify.example.com"
    # device_code is held server-side — never returned (value + key absent).
    assert "device_code" not in body
    assert "dev-code-SECRET" not in resp.text
    # client_secret is vaulted, never in the response.
    assert "csecret" not in resp.text
    secret = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}:oauth_secret", requesting_agent_id="captain"
    )
    assert secret == "csecret"


def test_device_start_503_when_no_vault(tmp_path: Path) -> None:
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    runtime.credential_vault = None
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/start", json=_DEVICE_START_BODY
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "credential_vault_unavailable"


def test_device_start_404_unknown_server(tmp_path: Path) -> None:
    client, _ = _make(tmp_path)
    resp = client.post(
        "/api/mcp/servers/nope/auth/device/start", json=_DEVICE_START_BODY
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# device/poll
# --------------------------------------------------------------------------- #


def _start_flow(client: TestClient, server_id: str) -> str:
    resp = client.post(
        f"/api/mcp/servers/{server_id}/auth/device/start", json=_DEVICE_START_BODY
    )
    return resp.json()["flow_id"]


def test_device_poll_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(
        monkeypatch,
        _flow_handler(httpx.Response(400, json={"error": "authorization_pending"})),
    )
    client, _ = _make(tmp_path)
    created = _create_http(client)
    flow_id = _start_flow(client, created["id"])
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/poll", json={"flow_id": flow_id}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


async def test_device_poll_success_persists_and_drops_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(
        monkeypatch,
        _flow_handler(
            httpx.Response(
                200,
                json={
                    "access_token": "access-DEVICE",
                    "refresh_token": "refresh-DEVICE",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        ),
    )
    client, runtime = _make(tmp_path)
    created = _create_http(client)
    flow_id = _start_flow(client, created["id"])
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/poll", json={"flow_id": flow_id}
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "authenticated"}
    # Bundle persisted under mcp:{id}:oauth (DD-4 — identical to auth-code callback).
    raw = await runtime.credential_vault.read(
        ref=f"mcp:{created['id']}:oauth", requesting_agent_id="captain"
    )
    assert raw is not None
    bundle = json.loads(raw)
    assert bundle["access_token"] == "access-DEVICE"
    # Record flipped to oauth.
    got = client.get(f"/api/mcp/servers/{created['id']}").json()
    assert got["auth_kind"] == "oauth"
    assert got["credential_ref"] == f"mcp:{created['id']}:oauth"
    # Re-registered on the bridge.
    assert runtime.mcp_bridge.get_client("https://example.com/mcp") is not None
    # Flow dropped: a 2nd poll is an unknown flow.
    resp2 = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/poll", json={"flow_id": flow_id}
    )
    assert resp2.status_code == 404
    assert resp2.json()["detail"] == "unknown_flow"


def test_device_poll_unknown_flow_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(
        monkeypatch, _flow_handler(httpx.Response(400, json={"error": "x"}))
    )
    client, _ = _make(tmp_path)
    created = _create_http(client)
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/poll",
        json={"flow_id": "never-started"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown_flow"


def test_device_poll_terminal_access_denied_drops_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mock_transport(
        monkeypatch,
        _flow_handler(httpx.Response(400, json={"error": "access_denied"})),
    )
    client, _ = _make(tmp_path)
    created = _create_http(client)
    flow_id = _start_flow(client, created["id"])
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/poll", json={"flow_id": flow_id}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "access_denied"
    # Flow dropped on terminal error.
    resp2 = client.post(
        f"/api/mcp/servers/{created['id']}/auth/device/poll", json={"flow_id": flow_id}
    )
    assert resp2.status_code == 404
    assert resp2.json()["detail"] == "unknown_flow"


# --------------------------------------------------------------------------- #
# Security: device_code + token never in any response body or log
# --------------------------------------------------------------------------- #


def test_device_code_and_token_never_in_response_or_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_mock_transport(
        monkeypatch,
        _flow_handler(
            httpx.Response(
                200,
                json={
                    "access_token": "access-DEVICE",
                    "refresh_token": "refresh-DEVICE",
                    "expires_in": 3600,
                },
            )
        ),
    )
    client, _ = _make(tmp_path)
    created = _create_http(client)
    with caplog.at_level(logging.DEBUG):
        start = client.post(
            f"/api/mcp/servers/{created['id']}/auth/device/start",
            json=_DEVICE_START_BODY,
        )
        flow_id = start.json()["flow_id"]
        poll = client.post(
            f"/api/mcp/servers/{created['id']}/auth/device/poll",
            json={"flow_id": flow_id},
        )
        got = client.get(f"/api/mcp/servers/{created['id']}").json()
    # device_code never crosses the wire to the client.
    assert "dev-code-SECRET" not in start.text
    assert "dev-code-SECRET" not in poll.text
    # token value + client_secret never surfaced on any response or row.
    assert "access-DEVICE" not in poll.text
    assert "access-DEVICE" not in json.dumps(got)
    assert "csecret" not in start.text
    # Nothing secret reaches the logs.
    assert "dev-code-SECRET" not in caplog.text
    assert "access-DEVICE" not in caplog.text
    assert "csecret" not in caplog.text
