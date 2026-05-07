"""AD-597: FederationMCPServer extension (resources/read + app-tool routing) tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.config import FederationMCPServerConfig
from probos.federation.mcp_server import FederationMCPServer
from probos.federation.peer import FederationPeerRegistry
from probos.mcp_apps.registry import MCPAppRegistry
from probos.types import IntentDescriptor, IntentResult


_VALID_CSP = "default-src 'self'"


class _FakeTrustNetwork:
    def __init__(self):
        self.priors: dict[str, tuple[float, float]] = {}
        self.outcomes: list = []
        self.scores: dict[str, float] = {}

    def create_with_prior(self, agent_id, alpha, beta):
        if agent_id in self.priors:
            return
        self.priors[agent_id] = (alpha, beta)

    def record_outcome(self, agent_id, success, weight=1.0, intent_type="",
                       episode_id="", verifier_id="", source="verification"):
        self.outcomes.append((agent_id, success, intent_type))
        prior = self.priors.get(agent_id, (1.0, 1.0))
        a, b = prior
        if success:
            a += weight
        else:
            b += weight
        self.priors[agent_id] = (a, b)
        score = a / (a + b)
        self.scores[agent_id] = score
        return score

    def get_score(self, agent_id):
        return self.scores.get(agent_id, 0.0)


def _stub_runtime(*, with_registry: bool = True):
    descriptors = {
        "echo": IntentDescriptor(
            name="echo", description="echo", params={},
        ),
    }
    tn = _FakeTrustNetwork()
    registry = FederationPeerRegistry(trust_network=tn)
    intent_bus = SimpleNamespace(
        broadcast=AsyncMock(return_value=[
            IntentResult(intent_id="i", agent_id="a", success=True,
                         result={"x": 1}, confidence=0.9),
        ]),
    )
    cert = SimpleNamespace(vessel_name="t", ship_did="did:t")
    identity_registry = SimpleNamespace(get_ship_certificate=lambda: cert)
    decomposer = SimpleNamespace(_intent_descriptors=descriptors)
    emitted: list[tuple] = []

    def _emit(event, data=None):
        emitted.append((getattr(event, "value", str(event)), dict(data or {})))

    runtime = SimpleNamespace(
        decomposer=decomposer,
        intent_bus=intent_bus,
        identity_registry=identity_registry,
        federation_peer_registry=registry,
        trust_network=tn,
        emit_event=_emit,
        _emitted=emitted,
    )
    if with_registry:
        runtime.mcp_app_registry = MCPAppRegistry(
            internal_default_csp=_VALID_CSP,
            external_default_csp=_VALID_CSP,
        )
    return runtime


def _server(runtime) -> FederationMCPServer:
    return FederationMCPServer(runtime=runtime, config=FederationMCPServerConfig())


@pytest.mark.asyncio
async def test_resources_read_dispatches_to_registry():
    rt = _stub_runtime()
    rt.mcp_app_registry.register_app_resource(
        uri="ui://probos/games/chess/index.html",
        mime_type="text/html",
        content=b"<html>ok</html>",
    )
    srv = _server(rt)
    out = await srv.handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "resources/read",
        "params": {"uri": "ui://probos/games/chess/index.html"},
    })
    assert "result" in out
    assert out["result"]["contents"][0]["text"] == "<html>ok</html>"


@pytest.mark.asyncio
async def test_resources_read_missing_uri_returns_invalid_params():
    rt = _stub_runtime()
    srv = _server(rt)
    out = await srv.handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {},
    })
    assert out["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_resources_read_unknown_uri_returns_server_error():
    rt = _stub_runtime()
    srv = _server(rt)
    out = await srv.handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "resources/read",
        "params": {"uri": "ui://probos/games/missing/index.html"},
    })
    assert out["error"]["code"] == -32000


@pytest.mark.asyncio
async def test_resources_read_no_registry_returns_error():
    rt = _stub_runtime(with_registry=False)
    rt.mcp_app_registry = None
    srv = _server(rt)
    out = await srv.handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "resources/read",
        "params": {"uri": "ui://x/y"},
    })
    assert out["error"]["code"] == -32000


@pytest.mark.asyncio
async def test_tools_list_merges_intent_and_app_tools():
    rt = _stub_runtime()

    async def _h(args):
        return {"isError": False, "content": []}

    rt.mcp_app_registry.register_app_tool(
        name="game-move", description="", input_schema={},
        ui_resource_uri="", handler=_h,
    )
    srv = _server(rt)
    out = await srv.handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
    })
    names = {t["name"] for t in out["result"]["tools"]}
    assert "echo" in names  # intent-derived
    assert "game-move" in names  # app-registry


@pytest.mark.asyncio
async def test_tools_call_routes_app_tool_before_intent_bus():
    rt = _stub_runtime()
    called = []

    async def _h(args):
        called.append(args)
        return {"isError": False, "content": [{"type": "text", "text": "app-handled"}]}

    rt.mcp_app_registry.register_app_tool(
        name="game-move", description="", input_schema={},
        ui_resource_uri="", handler=_h,
    )
    srv = _server(rt)
    out = await srv.handle_jsonrpc({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "game-move", "arguments": {"k": "v"}},
    }, session_id="sess")
    assert out["result"]["isError"] is False
    assert called == [{"k": "v"}]
    # IntentBus.broadcast must NOT be called when app tool handles it
    assert rt.intent_bus.broadcast.await_count == 0
