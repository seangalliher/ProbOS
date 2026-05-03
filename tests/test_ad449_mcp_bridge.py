"""AD-449 MCP Bridge tests."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from probos.config import MCPConfig, MCPServerConfig
from probos.events import EventType
from probos.integrations.mcp_bridge import (
    MCPBridge,
    MCPClient,
    MCPProtocolError,
    MCPSession,
    MCPToolAdapter,
)


# ----- EventTypes -----


def test_event_type_mcp_bridge_invoke_exists():
    assert EventType.MCP_BRIDGE_INVOKE.value == "mcp_bridge_invoke"


def test_event_type_mcp_bridge_failed_exists():
    assert EventType.MCP_BRIDGE_FAILED.value == "mcp_bridge_failed"


# ----- Config -----


def test_mcp_config_defaults():
    cfg = MCPConfig()
    assert cfg.enabled is True
    assert cfg.request_timeout_seconds == 30.0
    assert cfg.servers == []


# ----- MCPSession -----


def test_mcp_session_immutable():
    """Frozen dataclass; replace returns a new instance."""
    s1 = MCPSession(server_url="https://example.com/mcp")
    s2 = replace(s1, session_id="sid-123")
    assert s1.session_id == ""
    assert s2.session_id == "sid-123"
    assert s1 is not s2


# ----- MCPClient -----


def _make_client(**kwargs) -> MCPClient:
    """Helper: client with controlled defaults."""
    session = kwargs.pop("session", MCPSession(server_url="https://example.com/mcp"))
    return MCPClient(session=session, **kwargs)


def _mock_response(*, status_code: int = 200, body: dict | None = None,
                   headers: dict | None = None) -> MagicMock:
    """Build a httpx.Response-shaped MagicMock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=body or {})
    resp.headers = headers or {}
    return resp


@pytest.mark.asyncio
async def test_mcp_client_initialize_returns_session_with_capabilities():
    """Body returns capabilities; headers carry Mcp-Session-Id; session captures both."""
    client = _make_client()
    body = {
        "jsonrpc": "2.0",
        "id": "abc",
        "result": {"capabilities": {"tools": {"listChanged": False}}},
    }
    mock_resp = _mock_response(
        status_code=200, body=body, headers={"Mcp-Session-Id": "s-123"},
    )
    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=mock_resp)

    session = await client.initialize()
    assert session.session_id == "s-123"
    assert session.capabilities == {"tools": {"listChanged": False}}


@pytest.mark.asyncio
async def test_mcp_client_list_tools_returns_list():
    client = _make_client()
    body = {
        "jsonrpc": "2.0",
        "id": "abc",
        "result": {"tools": [{"name": "search"}]},
    }
    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=_mock_response(body=body))

    tools = await client.list_tools()
    assert tools == [{"name": "search"}]


@pytest.mark.asyncio
async def test_mcp_client_call_tool_returns_dict_result():
    client = _make_client()
    body = {
        "jsonrpc": "2.0",
        "id": "abc",
        "result": {"content": [{"type": "text", "text": "ok"}]},
    }
    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=_mock_response(body=body))

    result = await client.call_tool("search", {"q": "x"})
    assert result["content"][0]["text"] == "ok"


@pytest.mark.asyncio
async def test_mcp_client_egress_blocked_emits_failed_and_raises():
    """Egress policy denies URL -> MCPProtocolError; emit fires with reason='egress_blocked'."""
    policy = MagicMock()
    policy.is_allowed = MagicMock(return_value=False)
    emit = MagicMock()
    client = _make_client(egress_policy=policy, emit_event=emit)

    with pytest.raises(MCPProtocolError):
        await client.call_tool("x", {})

    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.MCP_BRIDGE_FAILED
    assert payload["reason"] == "egress_blocked"


@pytest.mark.asyncio
async def test_mcp_client_http_error_emits_failed_and_raises():
    emit = MagicMock()
    client = _make_client(emit_event=emit)
    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=_mock_response(status_code=500))

    with pytest.raises(MCPProtocolError):
        await client.call_tool("x", {})

    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.MCP_BRIDGE_FAILED
    assert payload["reason"] == "http_error"


@pytest.mark.asyncio
async def test_mcp_client_rpc_error_emits_failed_and_raises():
    emit = MagicMock()
    client = _make_client(emit_event=emit)
    body = {
        "jsonrpc": "2.0",
        "id": "abc",
        "error": {"code": -32601, "message": "method not found"},
    }
    client._http = MagicMock()
    client._http.post = AsyncMock(return_value=_mock_response(body=body))

    with pytest.raises(MCPProtocolError):
        await client.call_tool("x", {})

    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.MCP_BRIDGE_FAILED
    assert payload["reason"] == "rpc_error"


# ----- MCPBridge -----


def test_mcp_bridge_register_server_rejects_duplicates_and_empty():
    bridge = MCPBridge()
    assert bridge.register_server("") is False
    assert bridge.register_server("https://example.com/mcp") is True
    # Duplicate
    assert bridge.register_server("https://example.com/mcp") is False


@pytest.mark.asyncio
async def test_mcp_bridge_invoke_unknown_server_raises():
    bridge = MCPBridge()
    with pytest.raises(MCPProtocolError):
        await bridge.invoke("https://nonexistent.example.com/mcp", "x", {})


@pytest.mark.asyncio
async def test_mcp_bridge_invoke_routes_to_correct_client():
    bridge = MCPBridge()
    bridge.register_server("https://a.example.com/mcp")
    bridge.register_server("https://b.example.com/mcp")

    # Stub the call_tool on each client
    client_a = bridge.get_client("https://a.example.com/mcp")
    client_b = bridge.get_client("https://b.example.com/mcp")
    client_a.call_tool = AsyncMock(return_value={"from": "a"})
    client_b.call_tool = AsyncMock(return_value={"from": "b"})

    result = await bridge.invoke("https://b.example.com/mcp", "tool", {})
    assert result == {"from": "b"}
    client_b.call_tool.assert_awaited_once_with("tool", {})
    client_a.call_tool.assert_not_called()


# ----- MCPToolAdapter -----


def test_mcp_tool_adapter_name_format():
    adapter = MCPToolAdapter(
        bridge=None,
        server_url="https://api.example.com/mcp",
        tool_name="search",
    )
    assert adapter.name == "mcp.api_example_com.search"
    assert adapter.tool_name == "search"
    assert adapter.server_url == "https://api.example.com/mcp"
