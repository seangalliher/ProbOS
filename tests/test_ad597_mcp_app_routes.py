"""AD-597: /api/mcp/jsonrpc + /api/mcp/resource REST endpoint tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.mcp_apps.registry import MCPAppRegistry
from probos.routers.deps import get_runtime
from probos.routers.system import router


_VALID_CSP = "default-src 'self'"


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_mcp_jsonrpc_503_when_server_not_running():
    runtime = SimpleNamespace(federation_mcp_server=None, mcp_app_registry=None)
    with _client(runtime) as c:
        r = c.post("/api/mcp/jsonrpc", json={"jsonrpc": "2.0", "method": "ping"})
    assert r.status_code == 503


def test_mcp_jsonrpc_200_happy():
    fake_server = SimpleNamespace(
        handle_jsonrpc=AsyncMock(return_value={
            "jsonrpc": "2.0", "id": 1, "result": {"ok": True},
        }),
    )
    runtime = SimpleNamespace(federation_mcp_server=fake_server, mcp_app_registry=None)
    with _client(runtime) as c:
        r = c.post(
            "/api/mcp/jsonrpc",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert r.status_code == 200
    assert r.json()["result"] == {"ok": True}


def test_mcp_resource_404_unregistered():
    reg = MCPAppRegistry(internal_default_csp=_VALID_CSP, external_default_csp=_VALID_CSP)
    runtime = SimpleNamespace(federation_mcp_server=None, mcp_app_registry=reg)
    with _client(runtime) as c:
        r = c.get("/api/mcp/resource", params={"uri": "ui://probos/missing/index.html"})
    assert r.status_code == 404


def test_mcp_resource_200_with_csp_header():
    reg = MCPAppRegistry(internal_default_csp=_VALID_CSP, external_default_csp=_VALID_CSP)
    reg.register_app_resource(
        uri="ui://probos/games/chess/index.html",
        mime_type="text/html",
        content=b"<html>chess</html>",
    )
    runtime = SimpleNamespace(federation_mcp_server=None, mcp_app_registry=reg)
    with _client(runtime) as c:
        r = c.get("/api/mcp/resource", params={"uri": "ui://probos/games/chess/index.html"})
    assert r.status_code == 200
    assert r.text == "<html>chess</html>"
    assert r.headers.get("content-security-policy") == _VALID_CSP
    assert r.headers["content-type"].startswith("text/html")


def test_mcp_resource_503_when_registry_missing():
    runtime = SimpleNamespace(federation_mcp_server=None, mcp_app_registry=None)
    with _client(runtime) as c:
        r = c.get("/api/mcp/resource", params={"uri": "ui://probos/games/chess/index.html"})
    assert r.status_code == 503
