"""AD-1015: MCP server CRUD management API tests (routers/mcp_servers.py).

BF-287: a real ``McpServerStore`` (``db_path=""`` cache-only), a real
``MCPBridge``, a real ``SystemConfig``, and a real ``TestClient`` — no MagicMock
at the store/bridge/config boundary. The live-register / test-connection paths
that need a real server reuse the AD-1014 stdio echo fixture.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1015_mcp_servers_api.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import MCPConfig, SystemConfig
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.store import McpServerStore

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class _Runtime:
    """A real (non-Mock) runtime stub exposing exactly what the router reads."""

    def __init__(self, config: SystemConfig, store: Any, bridge: Any) -> None:
        self.config = config
        self.mcp_server_store = store
        self.mcp_bridge = bridge


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


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.mcp_servers import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _make(
    *, management_enabled: bool = True, store: Any = "default", bridge: Any = "default"
) -> tuple[TestClient, _Runtime]:
    # db_path="" -> cache-only real store (start() is a no-op in that mode).
    real_store = McpServerStore(db_path="") if store == "default" else store
    real_bridge = _bridge() if bridge == "default" else bridge
    runtime = _Runtime(_config(management_enabled=management_enabled), real_store, real_bridge)
    return _client(runtime), runtime


_HTTP_BODY = {"name": "weather", "type": "http", "url": "https://example.com/mcp"}


# --------------------------------------------------------------------------- #
# Gate (default-OFF)
# --------------------------------------------------------------------------- #


def test_gate_off_every_endpoint_404() -> None:
    client, _ = _make(management_enabled=False, store=None, bridge=None)
    assert client.get("/api/mcp/servers").status_code == 404
    assert client.post("/api/mcp/servers", json=_HTTP_BODY).status_code == 404
    assert client.get("/api/mcp/servers/x").status_code == 404
    assert client.put("/api/mcp/servers/x", json={"url": "https://y/mcp"}).status_code == 404
    assert client.delete("/api/mcp/servers/x").status_code == 404
    assert client.post("/api/mcp/servers/x/enable").status_code == 404
    assert client.post("/api/mcp/servers/x/disable").status_code == 404
    assert client.post("/api/mcp/servers/x/test").status_code == 404


def test_gate_off_detail_is_feature_disabled() -> None:
    client, _ = _make(management_enabled=False, store=None, bridge=None)
    resp = client.get("/api/mcp/servers")
    assert resp.json()["detail"] == "feature_disabled"


# --------------------------------------------------------------------------- #
# List + create
# --------------------------------------------------------------------------- #


def test_list_empty_then_populated() -> None:
    client, _ = _make()
    empty = client.get("/api/mcp/servers").json()
    assert empty == {"servers": [], "count": 0}
    client.post("/api/mcp/servers", json=_HTTP_BODY)
    populated = client.get("/api/mcp/servers").json()
    assert populated["count"] == 1
    assert populated["servers"][0]["name"] == "weather"


def test_create_http_returns_201_and_registers_in_bridge() -> None:
    client, runtime = _make()
    resp = client.post("/api/mcp/servers", json=_HTTP_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "weather"
    assert body["id"]
    # enabled http row -> live-registered under its url key.
    assert "https://example.com/mcp" in runtime.mcp_bridge.list_servers()


def test_create_stdio_returns_201() -> None:
    client, _ = _make()
    resp = client.post(
        "/api/mcp/servers",
        json={
            "name": "echo",
            "type": "stdio",
            "command": sys.executable,
            "args": [FIXTURE],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["type"] == "stdio"


def test_create_disabled_row_not_registered() -> None:
    client, runtime = _make()
    resp = client.post(
        "/api/mcp/servers",
        json={**_HTTP_BODY, "enabled": False},
    )
    assert resp.status_code == 201
    assert runtime.mcp_bridge.list_servers() == []


def test_create_validation_400_missing_url() -> None:
    client, _ = _make()
    resp = client.post("/api/mcp/servers", json={"name": "weather", "type": "http"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "url_required"


def test_create_validation_400_secret_header() -> None:
    client, _ = _make()
    resp = client.post(
        "/api/mcp/servers",
        json={**_HTTP_BODY, "headers": {"Authorization": "Bearer abc"}},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "secret_value_not_allowed"


def test_create_duplicate_name_409() -> None:
    client, _ = _make()
    assert client.post("/api/mcp/servers", json=_HTTP_BODY).status_code == 201
    dup = client.post(
        "/api/mcp/servers", json={**_HTTP_BODY, "url": "https://other/mcp"}
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["error"] == "duplicate_name"


# --------------------------------------------------------------------------- #
# Get / 404
# --------------------------------------------------------------------------- #


def test_get_one_and_404() -> None:
    client, _ = _make()
    created = client.post("/api/mcp/servers", json=_HTTP_BODY).json()
    got = client.get(f"/api/mcp/servers/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]
    assert client.get("/api/mcp/servers/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Update (re-register on connection-affecting change)
# --------------------------------------------------------------------------- #


def test_put_reregisters_when_url_changes() -> None:
    client, runtime = _make()
    created = client.post("/api/mcp/servers", json=_HTTP_BODY).json()
    assert "https://example.com/mcp" in runtime.mcp_bridge.list_servers()
    resp = client.put(
        f"/api/mcp/servers/{created['id']}", json={"url": "https://moved.example.com/mcp"}
    )
    assert resp.status_code == 200
    keys = runtime.mcp_bridge.list_servers()
    assert "https://moved.example.com/mcp" in keys
    assert "https://example.com/mcp" not in keys  # old key flipped away


def test_put_missing_404() -> None:
    client, _ = _make()
    assert client.put("/api/mcp/servers/nope", json={"url": "https://y/mcp"}).status_code == 404


def test_put_invalid_change_400() -> None:
    client, _ = _make()
    created = client.post("/api/mcp/servers", json=_HTTP_BODY).json()
    resp = client.put(f"/api/mcp/servers/{created['id']}", json={"url": ""})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "url_required"


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #


def test_delete_unregisters_and_removes() -> None:
    client, runtime = _make()
    created = client.post("/api/mcp/servers", json=_HTTP_BODY).json()
    assert "https://example.com/mcp" in runtime.mcp_bridge.list_servers()
    resp = client.delete(f"/api/mcp/servers/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": created["id"]}
    assert "https://example.com/mcp" not in runtime.mcp_bridge.list_servers()
    assert client.get(f"/api/mcp/servers/{created['id']}").status_code == 404


def test_delete_missing_404() -> None:
    client, _ = _make()
    assert client.delete("/api/mcp/servers/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Enable / disable (toggle registration, keep the row)
# --------------------------------------------------------------------------- #


def test_enable_disable_toggles_registration_keeps_row() -> None:
    client, runtime = _make()
    created = client.post("/api/mcp/servers", json=_HTTP_BODY).json()
    server_id = created["id"]
    assert "https://example.com/mcp" in runtime.mcp_bridge.list_servers()

    # disable -> unregistered, row kept (enabled=False)
    disabled = client.post(f"/api/mcp/servers/{server_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert runtime.mcp_bridge.list_servers() == []
    assert client.get(f"/api/mcp/servers/{server_id}").status_code == 200

    # enable -> re-registered, row kept (enabled=True)
    enabled = client.post(f"/api/mcp/servers/{server_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert "https://example.com/mcp" in runtime.mcp_bridge.list_servers()


def test_enable_missing_404() -> None:
    client, _ = _make()
    assert client.post("/api/mcp/servers/nope/enable").status_code == 404
    assert client.post("/api/mcp/servers/nope/disable").status_code == 404


# --------------------------------------------------------------------------- #
# Test-connection (transient client, closed in finally, honest-degrade)
# --------------------------------------------------------------------------- #


def test_test_connection_stdio_ok() -> None:
    client, _ = _make()
    created = client.post(
        "/api/mcp/servers",
        json={
            "name": "echo",
            "type": "stdio",
            "command": sys.executable,
            "args": [FIXTURE],
            "timeout_seconds": 5.0,
        },
    ).json()
    resp = client.post(f"/api/mcp/servers/{created['id']}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["tool_count"] == 3  # echo fixture exposes echo/slow/badjson


def test_test_connection_honest_degrade_returns_200_ok_false() -> None:
    client, _ = _make()
    # An unreachable target -> connection refused fast; never a 500.
    created = client.post(
        "/api/mcp/servers",
        json={
            "name": "dead",
            "type": "http",
            "url": "http://127.0.0.1:1/mcp",
            "timeout_seconds": 3.0,
        },
    ).json()
    resp = client.post(f"/api/mcp/servers/{created['id']}/test")
    assert resp.status_code == 200  # honest-degrade, NOT 500
    assert resp.json()["ok"] is False


def test_test_connection_missing_404() -> None:
    client, _ = _make()
    assert client.post("/api/mcp/servers/nope/test").status_code == 404


# --------------------------------------------------------------------------- #
# Config/store dedup — config wins (bridge no-op on duplicate key)
# --------------------------------------------------------------------------- #


def test_config_registered_key_wins_store_seed_is_noop() -> None:
    bridge = _bridge()
    # Simulate a config-registered server occupying the url key first.
    assert bridge.register_server("https://dup.example.com/mcp") is True
    config_client = bridge.get_client("https://dup.example.com/mcp")

    client, runtime = _make(bridge=bridge)
    resp = client.post(
        "/api/mcp/servers",
        json={"name": "dup", "type": "http", "url": "https://dup.example.com/mcp"},
    )
    # The store row is created (201) but the bridge register is a no-op (dup key).
    assert resp.status_code == 201
    keys = runtime.mcp_bridge.list_servers()
    assert keys.count("https://dup.example.com/mcp") == 1
    # Config's client is NOT replaced by the store seed.
    assert runtime.mcp_bridge.get_client("https://dup.example.com/mcp") is config_client


def test_no_secret_persisted_or_returned() -> None:
    """The secret-guard blocks the value at validate time; nothing reaches the
    store or any response body. A non-secret header alongside is preserved."""
    client, runtime = _make()
    rejected = client.post(
        "/api/mcp/servers",
        json={**_HTTP_BODY, "headers": {"X-Api-Key": "live-key-123"}},
    )
    assert rejected.status_code == 400
    # Nothing persisted.
    assert client.get("/api/mcp/servers").json()["count"] == 0
    # And the secret value never appears in any response body.
    assert "live-key-123" not in rejected.text
    # A non-secret header IS persisted + returned verbatim.
    ok = client.post(
        "/api/mcp/servers",
        json={**_HTTP_BODY, "headers": {"Content-Type": "application/json"}},
    )
    assert ok.status_code == 201
    assert ok.json()["headers"] == {"Content-Type": "application/json"}
