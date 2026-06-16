"""AD-1019: per-agent + per-tool MCP enablement tests.

BF-287 (no MagicMock at the store/bridge/config boundary): a real
``McpServerStore`` (``db_path=""`` cache-only), a real ``ToolPermissionStore``
(``db_path=""``), a real ``MCPBridge`` (``stdio_enabled=True``), the AD-1014
stdio echo fixture, and a real ``TestClient``. Connected-server tests run inside
``with TestClient(app) as client:`` so the echo subprocess spawned during the
``POST`` register request stays usable across the subsequent ``GET`` requests
(one persistent portal event loop), and the server is deleted in ``finally`` so
no subprocess leaks.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1019_mcp_enablement.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import MCPConfig, SystemConfig
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.access import resolve_mcp_access
from probos.integrations.mcp_bridge.store import McpServerStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolAccessGrant, ToolPermission

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")
_AGENT = "science-officer"


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #


class _Runtime:
    """A real (non-Mock) runtime stub exposing exactly what the router reads."""

    def __init__(
        self, config: SystemConfig, store: Any, bridge: Any, perms: Any
    ) -> None:
        self.config = config
        self.mcp_server_store = store
        self.mcp_bridge = bridge
        self.tool_permission_store = perms


def _config(*, management_enabled: bool = True) -> SystemConfig:
    return SystemConfig(
        mcp=MCPConfig(
            management_enabled=management_enabled,
            command_allowlist=["uvx", "npx", "python", "node", "docker", sys.executable],
            request_timeout_seconds=5.0,
        )
    )


def _bridge() -> MCPBridge:
    # stdio_enabled=True so the echo fixture actually registers + connects (the
    # GET /tools path reads a *registered* client, unlike AD-1015's transient test).
    return MCPBridge(
        emit_event=None,
        request_timeout=5.0,
        stdio_enabled=True,
        command_allowlist=[sys.executable],
    )


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.mcp_servers import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _make(
    *,
    management_enabled: bool = True,
    store: Any = "default",
    bridge: Any = "default",
    perms: Any = "default",
) -> tuple[TestClient, _Runtime]:
    real_store = McpServerStore(db_path="") if store == "default" else store
    real_bridge = _bridge() if bridge == "default" else bridge
    real_perms = ToolPermissionStore(db_path="") if perms == "default" else perms
    runtime = _Runtime(
        _config(management_enabled=management_enabled),
        real_store,
        real_bridge,
        real_perms,
    )
    return _client(runtime), runtime


def _create_echo(client: TestClient, *, name: str = "echo") -> str:
    """POST a stdio echo server (enabled → live-registered) and return its id."""
    resp = client.post(
        "/api/mcp/servers",
        json={
            "name": name,
            "type": "stdio",
            "command": sys.executable,
            "args": [FIXTURE],
            "timeout_seconds": 5.0,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@contextmanager
def _connected_echo(
    *, perms: Any = "default"
) -> Iterator[tuple[TestClient, _Runtime, str]]:
    """Yield (client, runtime, server_id) with a live echo server; always clean up.

    The ``with client:`` block pins a single portal event loop so the subprocess
    spawned in the create request is usable across later requests; the ``finally``
    deletes the server (unregister → terminate subprocess) so nothing leaks.
    """
    client, runtime = _make(perms=perms)
    with client:
        sid = _create_echo(client)
        try:
            yield client, runtime, sid
        finally:
            client.delete(f"/api/mcp/servers/{sid}")


def _grant(tool_id: str, *, is_restriction: bool = False) -> ToolAccessGrant:
    return ToolAccessGrant(
        id=f"g-{tool_id}-{'r' if is_restriction else 'g'}",
        agent_id=_AGENT,
        tool_id=tool_id,
        permission=ToolPermission.NONE if is_restriction else ToolPermission.WRITE,
        is_restriction=is_restriction,
    )


# --------------------------------------------------------------------------- #
# resolve_mcp_access — pure, all branches
# --------------------------------------------------------------------------- #


def test_resolve_default_disabled_when_no_grants() -> None:
    assert resolve_mcp_access([], "weather", "forecast") == (False, "default")


def test_resolve_server_grant_enables_all() -> None:
    grants = [_grant("mcp:weather")]
    assert resolve_mcp_access(grants, "weather", "forecast") == (True, "server")
    assert resolve_mcp_access(grants, "weather", "alerts") == (True, "server")


def test_resolve_server_restriction_disables() -> None:
    grants = [_grant("mcp:weather", is_restriction=True)]
    assert resolve_mcp_access(grants, "weather", "forecast") == (False, "server")


def test_resolve_tool_grant_enables() -> None:
    grants = [_grant("mcp:weather:forecast")]
    assert resolve_mcp_access(grants, "weather", "forecast") == (True, "tool")
    # A tool-level grant on one tool does not enable a sibling tool.
    assert resolve_mcp_access(grants, "weather", "alerts") == (False, "default")


def test_resolve_tool_restriction_disables() -> None:
    grants = [_grant("mcp:weather:forecast", is_restriction=True)]
    assert resolve_mcp_access(grants, "weather", "forecast") == (False, "tool")


def test_resolve_tool_restriction_beats_server_grant() -> None:
    # Tool-level overrides server-level: server-grant all, but forecast restricted.
    grants = [_grant("mcp:weather"), _grant("mcp:weather:forecast", is_restriction=True)]
    assert resolve_mcp_access(grants, "weather", "forecast") == (False, "tool")
    assert resolve_mcp_access(grants, "weather", "alerts") == (True, "server")


def test_resolve_tool_grant_overrides_server_restriction() -> None:
    # Server disabled, but one tool explicitly enabled.
    grants = [
        _grant("mcp:weather", is_restriction=True),
        _grant("mcp:weather:forecast"),
    ]
    assert resolve_mcp_access(grants, "weather", "forecast") == (True, "tool")
    assert resolve_mcp_access(grants, "weather", "alerts") == (False, "server")


def test_resolve_restriction_beats_grant_at_same_level() -> None:
    grants = [_grant("mcp:weather"), _grant("mcp:weather", is_restriction=True)]
    assert resolve_mcp_access(grants, "weather", "forecast") == (False, "server")


def test_resolve_empty_tool_folds_to_server_scope() -> None:
    # The router computes server_enabled via tool_name="".
    assert resolve_mcp_access([_grant("mcp:weather")], "weather", "") == (True, "server")
    assert resolve_mcp_access([], "weather", "") == (False, "default")


# --------------------------------------------------------------------------- #
# Gate (default-OFF) — the new endpoints 404 when management_enabled is False
# --------------------------------------------------------------------------- #


def test_gate_off_new_endpoints_404() -> None:
    client, _ = _make(
        management_enabled=False, store=None, bridge=None, perms=None
    )
    assert client.get("/api/mcp/servers/x/tools").status_code == 404
    assert client.get("/api/mcp/servers/x/agents/a/access").status_code == 404
    assert (
        client.post("/api/mcp/servers/x/agents/a", json={"enabled": True}).status_code
        == 404
    )
    assert client.delete("/api/mcp/servers/x/agents/a").status_code == 404


# --------------------------------------------------------------------------- #
# GET /tools — enumeration + honest-degrade
# --------------------------------------------------------------------------- #


def test_get_tools_enumerates_echo_fixture() -> None:
    with _connected_echo() as (client, _runtime, sid):
        body = client.get(f"/api/mcp/servers/{sid}/tools").json()
        assert body["count"] == 3
        names = {t["name"] for t in body["tools"]}
        assert {"echo", "slow", "badjson"} <= names
        # the echo fixture carries descriptions
        assert all("description" in t for t in body["tools"])
        assert "error" not in body


def test_get_tools_honest_degrade_when_not_registered() -> None:
    # A disabled row is never registered in the bridge -> get_client miss.
    client, _ = _make()
    created = client.post(
        "/api/mcp/servers",
        json={"name": "weather", "type": "http", "url": "https://example.com/mcp", "enabled": False},
    ).json()
    resp = client.get(f"/api/mcp/servers/{created['id']}/tools")
    assert resp.status_code == 200  # honest-degrade, NOT 500
    body = resp.json()
    assert body == {"tools": [], "count": 0, "error": "not_registered"}


def test_get_tools_missing_server_404() -> None:
    client, _ = _make()
    assert client.get("/api/mcp/servers/nope/tools").status_code == 404


# --------------------------------------------------------------------------- #
# POST / GET access / DELETE — grant lifecycle over the real ToolPermissionStore
# --------------------------------------------------------------------------- #


def test_post_server_level_then_access_all_enabled() -> None:
    with _connected_echo() as (client, _runtime, sid):
        resp = client.post(
            f"/api/mcp/servers/{sid}/agents/{_AGENT}", json={"enabled": True}
        )
        assert resp.status_code == 200
        assert resp.json()["grant_id"]

        access = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access").json()
        assert access["server_enabled"] is True
        assert len(access["tools"]) == 3
        for tool in access["tools"]:
            assert tool["enabled"] is True
            assert tool["source"] == "server"


def test_post_tool_level_disable_one_tool() -> None:
    with _connected_echo() as (client, _runtime, sid):
        # Enable server-wide, then disable just the "echo" tool.
        client.post(f"/api/mcp/servers/{sid}/agents/{_AGENT}", json={"enabled": True})
        disable = client.post(
            f"/api/mcp/servers/{sid}/agents/{_AGENT}",
            json={"enabled": False, "tool": "echo"},
        )
        assert disable.status_code == 200
        assert disable.json()["is_restriction"] is True

        access = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access").json()
        by_name = {t["name"]: t for t in access["tools"]}
        assert by_name["echo"] == {"name": "echo", "enabled": False, "source": "tool"}
        # siblings remain enabled at server scope
        assert by_name["slow"]["enabled"] is True
        assert by_name["slow"]["source"] == "server"
        assert by_name["badjson"]["enabled"] is True
        assert access["server_enabled"] is True


def test_delete_reverts_to_default() -> None:
    with _connected_echo() as (client, _runtime, sid):
        client.post(f"/api/mcp/servers/{sid}/agents/{_AGENT}", json={"enabled": True})
        pre = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access").json()
        assert pre["server_enabled"] is True

        deleted = client.delete(f"/api/mcp/servers/{sid}/agents/{_AGENT}")
        assert deleted.status_code == 200
        assert deleted.json() == {"revoked": 1}

        post = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access").json()
        assert post["server_enabled"] is False
        for tool in post["tools"]:
            assert tool["enabled"] is False
            assert tool["source"] == "default"


def test_delete_tool_level_only_revokes_that_tool() -> None:
    with _connected_echo() as (client, _runtime, sid):
        client.post(f"/api/mcp/servers/{sid}/agents/{_AGENT}", json={"enabled": True})
        client.post(
            f"/api/mcp/servers/{sid}/agents/{_AGENT}",
            json={"enabled": False, "tool": "echo"},
        )
        # Revoke only the tool-level restriction; the server-level grant remains.
        deleted = client.delete(
            f"/api/mcp/servers/{sid}/agents/{_AGENT}?tool=echo"
        )
        assert deleted.json() == {"revoked": 1}
        access = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access").json()
        by_name = {t["name"]: t for t in access["tools"]}
        assert by_name["echo"]["enabled"] is True
        assert by_name["echo"]["source"] == "server"


def test_grants_recorded_in_real_permission_store() -> None:
    with _connected_echo() as (client, runtime, sid):
        resp = client.post(
            f"/api/mcp/servers/{sid}/agents/{_AGENT}", json={"enabled": True}
        )
        grant_id = resp.json()["grant_id"]
        # The composite-id grant is recorded in the audited ToolPermissionStore.
        active = runtime.tool_permission_store.get_active_grants_sync(_AGENT)
        assert any(
            g.id == grant_id
            and g.tool_id == "mcp:echo"
            and g.permission == ToolPermission.WRITE
            and g.is_restriction is False
            for g in active
        )
        # Scoped read by composite id returns exactly the one grant.
        scoped = runtime.tool_permission_store.get_active_grants_sync(_AGENT, "mcp:echo")
        assert len(scoped) == 1
        assert scoped[0].id == grant_id


def test_tool_level_disable_records_restriction_in_store() -> None:
    with _connected_echo() as (client, runtime, sid):
        client.post(
            f"/api/mcp/servers/{sid}/agents/{_AGENT}",
            json={"enabled": False, "tool": "echo"},
        )
        scoped = runtime.tool_permission_store.get_active_grants_sync(
            _AGENT, "mcp:echo:echo"
        )
        assert len(scoped) == 1
        assert scoped[0].is_restriction is True
        assert scoped[0].permission == ToolPermission.NONE
        assert scoped[0].reason == "mcp enablement"


# --------------------------------------------------------------------------- #
# Honest-degrade — no permission store → 503 (never 500); missing server → 404
# --------------------------------------------------------------------------- #


def test_post_no_perm_store_returns_503() -> None:
    client, _ = _make(perms=None)
    created = client.post(
        "/api/mcp/servers",
        json={"name": "weather", "type": "http", "url": "https://example.com/mcp", "enabled": False},
    ).json()
    resp = client.post(
        f"/api/mcp/servers/{created['id']}/agents/{_AGENT}", json={"enabled": True}
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "tool_permission_store_unavailable"


def test_delete_no_perm_store_returns_503() -> None:
    client, _ = _make(perms=None)
    created = client.post(
        "/api/mcp/servers",
        json={"name": "weather", "type": "http", "url": "https://example.com/mcp", "enabled": False},
    ).json()
    resp = client.delete(f"/api/mcp/servers/{created['id']}/agents/{_AGENT}")
    assert resp.status_code == 503


def test_post_missing_server_404() -> None:
    client, _ = _make()
    assert (
        client.post(
            "/api/mcp/servers/nope/agents/a", json={"enabled": True}
        ).status_code
        == 404
    )


def test_access_missing_server_404() -> None:
    client, _ = _make()
    assert client.get("/api/mcp/servers/nope/agents/a/access").status_code == 404


def test_access_no_perm_store_degrades_to_default() -> None:
    # GET /access must not 500 without a perm store — every tool resolves default.
    with _connected_echo(perms=None) as (client, _runtime, sid):
        access = client.get(f"/api/mcp/servers/{sid}/agents/{_AGENT}/access").json()
        assert access["server_enabled"] is False
        assert len(access["tools"]) == 3
        for tool in access["tools"]:
            assert tool["enabled"] is False
            assert tool["source"] == "default"
