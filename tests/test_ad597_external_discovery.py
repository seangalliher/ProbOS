"""AD-597f: External MCP App discovery tests."""

from __future__ import annotations

import pytest

from probos.mcp_apps.external_discovery import discover_external_apps
from probos.mcp_apps.registry import MCPAppRegistry


_VALID_CSP = "default-src 'self'"


def _registry() -> MCPAppRegistry:
    return MCPAppRegistry(
        internal_default_csp=_VALID_CSP,
        external_default_csp=_VALID_CSP,
    )


class _FakeClient:
    def __init__(self, tools):
        self._tools = tools

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, args):
        return {"isError": False, "content": []}


class _FakeBridge:
    def __init__(self, mapping: dict):
        self._mapping = mapping

    def list_servers(self):
        return list(self._mapping.keys())

    def get_client(self, url):
        return self._mapping.get(url)


@pytest.mark.asyncio
async def test_discover_with_no_bridge_returns_zero():
    r = _registry()
    n = await discover_external_apps(r, None)
    assert n == 0


@pytest.mark.asyncio
async def test_discover_zero_servers_returns_zero():
    r = _registry()
    bridge = _FakeBridge({})
    n = await discover_external_apps(r, bridge)
    assert n == 0


@pytest.mark.asyncio
async def test_discover_one_server_one_app_tool():
    r = _registry()
    client = _FakeClient([
        {"name": "ext-tool", "_meta": {"ui": {"resourceUri": "ui://external/srv/x.html"}}},
        {"name": "non-ui-tool"},  # filtered out
    ])
    bridge = _FakeBridge({"https://srv": client})
    n = await discover_external_apps(r, bridge)
    assert n == 1
    assert r.has_tool("ext-tool")
    assert not r.has_tool("non-ui-tool")


@pytest.mark.asyncio
async def test_discover_two_servers():
    r = _registry()
    c1 = _FakeClient([
        {"name": "a", "_meta": {"ui": {"resourceUri": "ui://external/s1/a.html"}}},
    ])
    c2 = _FakeClient([
        {"name": "b", "_meta": {"ui": {"resourceUri": "ui://external/s2/b.html"}}},
    ])
    bridge = _FakeBridge({"s1": c1, "s2": c2})
    n = await discover_external_apps(r, bridge)
    assert n == 2


@pytest.mark.asyncio
async def test_per_server_failure_log_and_degrade(caplog):
    r = _registry()

    class BoomClient:
        async def list_tools(self):
            raise RuntimeError("network down")

    good = _FakeClient([
        {"name": "ok", "_meta": {"ui": {"resourceUri": "ui://external/g/x.html"}}},
    ])
    bridge = _FakeBridge({"bad": BoomClient(), "good": good})
    with caplog.at_level("WARNING"):
        n = await discover_external_apps(r, bridge)
    assert n == 1
    assert r.has_tool("ok")
    assert any("list_tools failed" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_external_csp_propagated():
    r = _registry()
    client = _FakeClient([
        {
            "name": "x",
            "_meta": {"ui": {"resourceUri": "ui://external/s/x", "csp": "default-src 'none'"}},
        },
    ])
    bridge = _FakeBridge({"s": client})
    await discover_external_apps(r, bridge)
    tools = r.list_tools()
    assert tools[0]["_meta"]["ui"]["csp"] == "default-src 'none'"


@pytest.mark.asyncio
async def test_external_flag_set_on_registration():
    r = _registry()
    client = _FakeClient([
        {"name": "x", "_meta": {"ui": {"resourceUri": "ui://external/s/x"}}},
    ])
    bridge = _FakeBridge({"s": client})
    await discover_external_apps(r, bridge)
    tools = r.list_tools()
    assert tools[0]["_meta"]["probos"]["external"] is True


@pytest.mark.asyncio
async def test_list_servers_exception_returns_zero(caplog):
    r = _registry()

    class BadBridge:
        def list_servers(self):
            raise RuntimeError("oops")

        def get_client(self, url):
            return None

    with caplog.at_level("WARNING"):
        n = await discover_external_apps(r, BadBridge())
    assert n == 0
    assert any("list_servers failed" in m for m in caplog.messages)
