"""AD-597a: MCPAppRegistry tests."""

from __future__ import annotations

import pytest

from probos.events import EventType
from probos.mcp_apps.registry import MCPAppRegistry


_VALID_CSP = "default-src 'self'"


def _make_registry() -> MCPAppRegistry:
    return MCPAppRegistry(
        internal_default_csp=_VALID_CSP,
        external_default_csp=_VALID_CSP,
    )


async def _ok_handler(args):
    return {"isError": False, "content": [{"type": "text", "text": "ok"}]}


def test_register_app_tool_happy_path():
    r = _make_registry()
    r.register_app_tool(
        name="game-move",
        description="test",
        input_schema={"type": "object"},
        ui_resource_uri="ui://probos/games/x/index.html",
        handler=_ok_handler,
    )
    assert r.has_tool("game-move")
    tools = r.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "game-move"
    assert tools[0]["_meta"]["ui"]["resourceUri"] == "ui://probos/games/x/index.html"
    assert tools[0]["_meta"]["probos"]["external"] is False


def test_register_app_tool_duplicate_replace_with_warning(caplog):
    r = _make_registry()
    r.register_app_tool(
        name="game-move", description="a", input_schema={},
        ui_resource_uri="", handler=_ok_handler,
    )
    with caplog.at_level("WARNING"):
        r.register_app_tool(
            name="game-move", description="b", input_schema={},
            ui_resource_uri="", handler=_ok_handler,
        )
    assert any("replacing app tool game-move" in m for m in caplog.messages)


def test_register_app_tool_invalid_csp_raises():
    r = _make_registry()
    with pytest.raises(ValueError):
        r.register_app_tool(
            name="x", description="", input_schema={},
            ui_resource_uri="", handler=_ok_handler,
            csp="bad\r\nheader",
        )


def test_register_app_tool_missing_name_raises():
    r = _make_registry()
    with pytest.raises(ValueError):
        r.register_app_tool(
            name="", description="", input_schema={},
            ui_resource_uri="", handler=_ok_handler,
        )


def test_register_app_resource_happy_path():
    r = _make_registry()
    r.register_app_resource(
        uri="ui://probos/games/chess/index.html",
        mime_type="text/html",
        content=b"<html></html>",
    )
    assert r.get_resource_mime("ui://probos/games/chess/index.html") == "text/html"
    assert r.get_resource_csp("ui://probos/games/chess/index.html") == _VALID_CSP


def test_register_app_resource_invalid_path_raises():
    r = _make_registry()
    with pytest.raises(ValueError):
        r.register_app_resource(
            uri="not-ui-scheme",
            mime_type="text/html",
            content=b"",
        )
    with pytest.raises(ValueError):
        r.register_app_resource(
            uri="ui://probos/../etc/passwd",
            mime_type="text/html",
            content=b"",
        )


@pytest.mark.asyncio
async def test_read_resource_hit():
    r = _make_registry()
    r.register_app_resource(
        uri="ui://probos/games/chess/index.html",
        mime_type="text/html",
        content=b"<html>x</html>",
    )
    res = await r.read_resource("ui://probos/games/chess/index.html")
    assert res is not None
    assert res["contents"][0]["text"] == "<html>x</html>"


@pytest.mark.asyncio
async def test_read_resource_miss_returns_none():
    r = _make_registry()
    assert await r.read_resource("ui://probos/missing/index.html") is None


@pytest.mark.asyncio
async def test_call_tool_happy_path():
    r = _make_registry()
    r.register_app_tool(
        name="x", description="", input_schema={},
        ui_resource_uri="", handler=_ok_handler,
    )
    res = await r.call_tool("x", {})
    assert res["isError"] is False


@pytest.mark.asyncio
async def test_call_tool_unknown_returns_isError():
    r = _make_registry()
    res = await r.call_tool("nope", {})
    assert res["isError"] is True


@pytest.mark.asyncio
async def test_call_tool_handler_exception_log_and_degrade(caplog):
    r = _make_registry()

    async def boom(args):
        raise RuntimeError("kaboom")

    r.register_app_tool(
        name="bad", description="", input_schema={},
        ui_resource_uri="", handler=boom,
    )
    with caplog.at_level("WARNING"):
        res = await r.call_tool("bad", {})
    assert res["isError"] is True
    assert "kaboom" in res["content"][0]["text"]


def test_register_external_app_emits_discovered_event():
    r = _make_registry()
    events = []
    r.set_event_callback(lambda et, payload: events.append((et, payload)))

    class FakeClient:
        async def call_tool(self, name, args):
            return {"isError": False, "content": []}

    r.register_external_app(
        server_id="https://srv",
        tool_dict={
            "name": "ext-tool",
            "description": "d",
            "inputSchema": {},
            "_meta": {"ui": {"resourceUri": "ui://external/srv/x.html"}},
        },
        csp="",
        mcp_client=FakeClient(),
    )
    types = [e[0] for e in events]
    assert EventType.MCP_APP_EXTERNAL_DISCOVERED in types


def test_list_tools_merges_internal_and_external():
    r = _make_registry()
    r.register_app_tool(
        name="int", description="", input_schema={},
        ui_resource_uri="", handler=_ok_handler,
    )

    class FakeClient:
        async def call_tool(self, name, args):
            return {}

    r.register_external_app(
        server_id="srv",
        tool_dict={"name": "ext", "_meta": {"ui": {"resourceUri": "ui://external/srv/a"}}},
        csp="",
        mcp_client=FakeClient(),
    )
    names = {t["name"] for t in r.list_tools()}
    assert names == {"int", "ext"}


def test_unregister_app():
    r = _make_registry()
    r.register_app_tool(
        name="x", description="", input_schema={},
        ui_resource_uri="", handler=_ok_handler,
    )
    assert r.unregister_app("x") is True
    assert r.unregister_app("x") is False
    assert not r.has_tool("x")


def test_event_callback_fires_on_register():
    r = _make_registry()
    events = []
    r.set_event_callback(lambda et, payload: events.append((et, payload)))
    r.register_app_tool(
        name="x", description="", input_schema={},
        ui_resource_uri="", handler=_ok_handler,
    )
    assert any(e[0] == EventType.MCP_APP_TOOL_REGISTERED for e in events)


@pytest.mark.asyncio
async def test_external_app_handler_routes_through_mcp_client():
    r = _make_registry()

    class FakeClient:
        def __init__(self):
            self.called = []

        async def call_tool(self, name, args):
            self.called.append((name, args))
            return {"isError": False, "content": [{"type": "text", "text": "x"}]}

    client = FakeClient()
    r.register_external_app(
        server_id="srv",
        tool_dict={"name": "ext", "_meta": {"ui": {"resourceUri": "ui://external/srv/a"}}},
        csp="",
        mcp_client=client,
    )
    res = await r.call_tool("ext", {"foo": "bar"})
    assert res["isError"] is False
    assert client.called == [("ext", {"foo": "bar"})]


def test_invalid_default_csp_raises():
    with pytest.raises(ValueError):
        MCPAppRegistry(
            internal_default_csp="bad\r\nheader",
            external_default_csp=_VALID_CSP,
        )


def test_event_callback_exception_swallowed(caplog):
    r = _make_registry()

    def bad(et, payload):
        raise RuntimeError("emit fail")

    r.set_event_callback(bad)
    # Should not raise
    with caplog.at_level("WARNING"):
        r.register_app_tool(
            name="x", description="", input_schema={},
            ui_resource_uri="", handler=_ok_handler,
        )
    assert r.has_tool("x")
