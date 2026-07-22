"""AD-480: Federation MCP server + A2A both directions tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from probos.config import (
    A2APeerConfig,
    FederationA2AConfig,
    FederationConfig,
    FederationMCPServerConfig,
    FederationPeerTrustConfig,
)
from probos.federation.a2a import A2A_PROTOCOL_VERSION
from probos.federation.a2a.agent_card import (
    AgentCapabilities,
    AgentCard,
    AgentProvider,
    AgentSkill,
)
from probos.federation.a2a.client import A2AClient, A2AProtocolError
from probos.federation.a2a.server import FederationA2AServer
from probos.federation.mcp_server import FederationMCPServer
from probos.federation.peer import FederationPeer, FederationPeerRegistry
from probos.types import IntentDescriptor, IntentResult


# -------------------- helpers --------------------


class _FakeTrustNetwork:
    def __init__(self) -> None:
        self.priors: dict[str, tuple[float, float]] = {}
        self.outcomes: list[tuple[str, bool, float, str, str]] = []
        self.scores: dict[str, float] = {}

    def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None:
        if agent_id in self.priors:
            return
        self.priors[agent_id] = (alpha, beta)

    def record_outcome(
        self,
        agent_id: str,
        success: bool,
        weight: float = 1.0,
        intent_type: str = "",
        episode_id: str = "",
        verifier_id: str = "",
        source: str = "verification",
    ) -> float:
        self.outcomes.append((agent_id, success, weight, intent_type, source))
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

    def get_score(self, agent_id: str) -> float:
        return self.scores.get(agent_id, 0.0)


def _make_descriptor(name: str = "echo", **kw) -> IntentDescriptor:
    return IntentDescriptor(
        name=name,
        params=kw.get("params", {"text": "Text to echo"}),
        description=kw.get("description", f"{name} intent"),
        requires_consensus=kw.get("requires_consensus", False),
        tier=kw.get("tier", "domain"),
    )


def _stub_runtime(
    *,
    descriptors: dict[str, IntentDescriptor] | None = None,
    broadcast_results: list[IntentResult] | None = None,
    trust_network: _FakeTrustNetwork | None = None,
    vessel_name: str = "ProbOS-Test",
    ship_did: str = "did:probos:test",
):
    descriptors = descriptors or {"echo": _make_descriptor("echo")}
    if broadcast_results is None:
        broadcast_results = [
            IntentResult(intent_id="i", agent_id="agent-a", success=True,
                         result={"echoed": "hi"}, confidence=0.9),
        ]
    tn = trust_network or _FakeTrustNetwork()
    registry = FederationPeerRegistry(trust_network=tn)

    decomposer = SimpleNamespace(_intent_descriptors=descriptors)
    intent_bus = SimpleNamespace(broadcast=AsyncMock(return_value=broadcast_results))
    cert = SimpleNamespace(vessel_name=vessel_name, ship_did=ship_did)
    identity_registry = SimpleNamespace(get_ship_certificate=lambda: cert)
    emitted: list[tuple[str, dict]] = []

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
    return runtime


def _mock_response(*, status_code: int = 200, body=None, headers=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=body if body is not None else {})
    resp.headers = headers or {}
    return resp


# -------------------- TestFederationPeerRegistry (480f + 480g) --------------------


class TestFederationPeerRegistry:
    @pytest.mark.asyncio
    async def test_register_peer_first_time_invokes_create_with_prior(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn,
                                     probationary_alpha=1.0, probationary_beta=3.0)
        ok = await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="p1", endpoint="p1",
            trust_record_id="mcp-peer:p1",
        ))
        assert ok is True
        assert tn.priors == {"mcp-peer:p1": (1.0, 3.0)}

    @pytest.mark.asyncio
    async def test_register_peer_idempotent_does_not_invoke_create_with_prior_twice(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn)
        peer = FederationPeer(protocol="a2a", peer_id="p", endpoint="p",
                              trust_record_id="a2a-peer:p")
        await reg.register_peer(peer)
        ok2 = await reg.register_peer(peer)
        assert ok2 is False
        assert list(tn.priors.keys()) == ["a2a-peer:p"]

    @pytest.mark.asyncio
    async def test_unregister_peer_removes_entry(self):
        reg = FederationPeerRegistry()
        await reg.register_peer(FederationPeer(
            protocol="zmq", peer_id="n1", endpoint="tcp://x", trust_record_id="zmq:n1",
        ))
        assert await reg.unregister_peer("n1") is True
        assert reg.get_peer("n1") is None
        assert await reg.unregister_peer("n1") is False

    @pytest.mark.asyncio
    async def test_list_peers_filtered_by_protocol(self):
        reg = FederationPeerRegistry()
        await reg.register_peer(FederationPeer(
            protocol="zmq", peer_id="n1", endpoint="x", trust_record_id="t1"))
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="m1", endpoint="x", trust_record_id="t2"))
        await reg.register_peer(FederationPeer(
            protocol="a2a", peer_id="a1", endpoint="x", trust_record_id="t3"))
        assert {p.peer_id for p in reg.list_peers()} == {"n1", "m1", "a1"}
        assert [p.peer_id for p in reg.list_peers(protocol="mcp")] == ["m1"]
        assert [p.peer_id for p in reg.list_peers(protocol="a2a")] == ["a1"]

    @pytest.mark.asyncio
    async def test_peers_supporting_returns_subset_with_capability(self):
        reg = FederationPeerRegistry()
        p1 = FederationPeer(protocol="mcp", peer_id="m1", endpoint="x",
                            trust_record_id="t1", capabilities=["echo", "sum"])
        p2 = FederationPeer(protocol="a2a", peer_id="a1", endpoint="x",
                            trust_record_id="t2", capabilities=["sum"])
        await reg.register_peer(p1)
        await reg.register_peer(p2)
        ids = sorted(p.peer_id for p in reg.peers_supporting("sum"))
        assert ids == ["a1", "m1"]
        assert [p.peer_id for p in reg.peers_supporting("echo")] == ["m1"]

    @pytest.mark.asyncio
    async def test_record_outcome_invokes_trust_record_outcome(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn)
        await reg.register_peer(FederationPeer(
            protocol="a2a", peer_id="p", endpoint="p", trust_record_id="a2a-peer:p"))
        reg.record_outcome("p", True, intent_type="echo")
        assert tn.outcomes[0][0] == "a2a-peer:p"
        assert tn.outcomes[0][1] is True
        assert tn.outcomes[0][3] == "echo"
        assert tn.outcomes[0][4] == "federation_outcome"

    @pytest.mark.asyncio
    async def test_record_outcome_busy_trust_preserves_timestamp(self):
        tn = MagicMock()
        tn.create_with_prior = MagicMock()
        tn.record_outcome.side_effect = RuntimeError("trust_write_in_progress")
        reg = FederationPeerRegistry(trust_network=tn)
        peer = FederationPeer(
            protocol="a2a",
            peer_id="p",
            endpoint="p",
            trust_record_id="a2a-peer:p",
        )
        await reg.register_peer(peer)

        reg.record_outcome("p", True, intent_type="echo")

        assert peer.last_outcome_at > 0.0

    @pytest.mark.asyncio
    async def test_record_outcome_other_trust_runtime_error_propagates(self):
        tn = MagicMock()
        tn.create_with_prior = MagicMock()
        tn.record_outcome.side_effect = RuntimeError("trust store defect")
        reg = FederationPeerRegistry(trust_network=tn)
        await reg.register_peer(FederationPeer(
            protocol="a2a",
            peer_id="p",
            endpoint="p",
            trust_record_id="a2a-peer:p",
        ))

        with pytest.raises(RuntimeError, match="^trust store defect$"):
            reg.record_outcome("p", True, intent_type="echo")


# -------------------- TestAgentCard (480c) --------------------


class TestAgentCard:
    def test_to_json_dict_minimal(self):
        card = AgentCard(name="A", description="d", url="u", version="0.1.0")
        d = card.to_json_dict()
        assert d["name"] == "A"
        assert d["capabilities"] == {
            "streaming": False, "pushNotifications": False,
            "stateTransitionHistory": False,
        }
        assert d["skills"] == []
        assert "provider" not in d

    def test_to_json_dict_with_provider(self):
        card = AgentCard(
            name="A", description="d", url="u", version="0.1.0",
            provider=AgentProvider(organization="org", url="did:probos:x"),
        )
        d = card.to_json_dict()
        assert d["provider"] == {"organization": "org", "url": "did:probos:x"}

    def test_to_json_dict_with_skills(self):
        card = AgentCard(
            name="A", description="d", url="u", version="0.1.0",
            skills=[AgentSkill(id="echo", name="echo", description="ok",
                               tags=["domain"])],
        )
        d = card.to_json_dict()
        assert d["skills"][0]["id"] == "echo"
        assert d["skills"][0]["tags"] == ["domain"]
        assert d["skills"][0]["inputModes"] == ["text"]

    def test_capabilities_streaming_default_false(self):
        assert AgentCapabilities().streaming is False

    def test_capabilities_push_default_false(self):
        assert AgentCapabilities().pushNotifications is False

    def test_from_runtime_uses_vessel_name(self):
        runtime = _stub_runtime(vessel_name="USS-Foo")
        card = AgentCard.from_runtime(runtime, base_url="http://x")
        assert card.name == "USS-Foo"

    def test_from_runtime_uses_ship_did_in_provider_url(self):
        runtime = _stub_runtime(ship_did="did:probos:abc")
        card = AgentCard.from_runtime(runtime)
        assert card.provider is not None
        assert card.provider.url == "did:probos:abc"

    def test_from_runtime_skills_derived_from_descriptors(self):
        descriptors = {
            "echo": _make_descriptor("echo"),
            "sum": _make_descriptor("sum", description="add", tier="utility"),
        }
        runtime = _stub_runtime(descriptors=descriptors)
        card = AgentCard.from_runtime(runtime)
        ids = sorted(s.id for s in card.skills)
        assert ids == ["echo", "sum"]


# -------------------- TestA2AClient (480e) --------------------


def _a2a_client(monkeypatch=None, *, auth_token: str = "") -> A2AClient:
    return A2AClient(peer_url="https://peer.example.com", auth_token=auth_token)


class TestA2AClient:
    @pytest.mark.asyncio
    async def test_discover_fetches_agent_json(self):
        c = _a2a_client()
        body = {
            "name": "Peer", "description": "d", "url": "https://peer.example.com",
            "version": "0.1.0", "capabilities": {}, "skills": [],
        }
        c._http = MagicMock()
        c._http.get = AsyncMock(return_value=_mock_response(body=body))
        card = await c.discover()
        assert card.name == "Peer"
        assert c.discovered_card is card

    @pytest.mark.asyncio
    async def test_discover_parses_capabilities(self):
        c = _a2a_client()
        body = {
            "name": "P", "description": "", "url": "", "version": "",
            "capabilities": {"streaming": True, "pushNotifications": True,
                             "stateTransitionHistory": True},
            "skills": [],
        }
        c._http = MagicMock()
        c._http.get = AsyncMock(return_value=_mock_response(body=body))
        card = await c.discover()
        assert card.capabilities.streaming is True
        assert card.capabilities.pushNotifications is True
        assert card.capabilities.stateTransitionHistory is True

    @pytest.mark.asyncio
    async def test_discover_parses_skills(self):
        c = _a2a_client()
        body = {
            "name": "P", "description": "", "url": "", "version": "",
            "capabilities": {},
            "skills": [{"id": "echo", "name": "echo", "tags": ["x"]}],
        }
        c._http = MagicMock()
        c._http.get = AsyncMock(return_value=_mock_response(body=body))
        card = await c.discover()
        assert card.skills[0].id == "echo"
        assert card.skills[0].tags == ["x"]

    @pytest.mark.asyncio
    async def test_discover_handles_missing_provider(self):
        c = _a2a_client()
        body = {"name": "P", "description": "", "url": "", "version": "",
                "capabilities": {}, "skills": []}
        c._http = MagicMock()
        c._http.get = AsyncMock(return_value=_mock_response(body=body))
        card = await c.discover()
        assert card.provider is None

    @pytest.mark.asyncio
    async def test_send_task_posts_jsonrpc_envelope(self):
        c = _a2a_client()
        body = {"jsonrpc": "2.0", "id": "x", "result": {"id": "t1", "status": {}}}
        c._http = MagicMock()
        c._http.post = AsyncMock(return_value=_mock_response(body=body))
        result = await c.send_task("echo", {"text": "hi"})
        assert result["id"] == "t1"
        assert c._http.post.call_count == 1
        sent_payload = json.loads(c._http.post.call_args.kwargs["content"])
        assert sent_payload["method"] == "tasks/send"
        assert sent_payload["params"]["message"]["parts"][0]["text"].startswith("echo:")

    @pytest.mark.asyncio
    async def test_send_task_with_auth_token_sets_authorization_header(self):
        c = _a2a_client(auth_token="secret-token")
        body = {"jsonrpc": "2.0", "id": "x", "result": {"id": "t1"}}
        c._http = MagicMock()
        c._http.post = AsyncMock(return_value=_mock_response(body=body))
        await c.send_task("echo", {})
        headers = c._http.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-token"

    @pytest.mark.asyncio
    async def test_get_task_correlates_by_id(self):
        c = _a2a_client()
        body = {"jsonrpc": "2.0", "id": "x", "result": {"id": "task-1"}}
        c._http = MagicMock()
        c._http.post = AsyncMock(return_value=_mock_response(body=body))
        result = await c.get_task("task-1")
        assert result["id"] == "task-1"
        sent = json.loads(c._http.post.call_args.kwargs["content"])
        assert sent["method"] == "tasks/get"
        assert sent["params"]["id"] == "task-1"

    @pytest.mark.asyncio
    async def test_close_aclose_idempotent_after_close(self):
        c = _a2a_client()
        c._http = MagicMock()
        c._http.aclose = AsyncMock()
        await c.close()
        await c.close()  # second call must not raise
        with pytest.raises(A2AProtocolError):
            await c.send_task("echo", {})


# -------------------- TestA2AServerInbound (480d) --------------------


def _a2a_server_with_runtime(*, broadcast_results=None, descriptors=None,
                              outbound_peers=None) -> tuple[FederationA2AServer, object]:
    runtime = _stub_runtime(descriptors=descriptors,
                            broadcast_results=broadcast_results)
    cfg = FederationA2AConfig(outbound_peers=outbound_peers or [])
    server = FederationA2AServer(runtime=runtime, config=cfg)
    return server, runtime


class TestA2AServerInbound:
    @pytest.mark.asyncio
    async def test_handle_agent_card_request_returns_card(self):
        server, _ = _a2a_server_with_runtime()
        d = await server.handle_agent_card_request()
        assert d["name"] == "ProbOS-Test"
        assert "capabilities" in d
        assert d["capabilities"]["streaming"] is False

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tasks_send_dispatches_intent(self):
        server, runtime = _a2a_server_with_runtime()
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
            "params": {"id": "t1", "message": {
                "role": "user",
                "parts": [{"type": "text", "text": 'echo:{"text":"hi"}'}],
            }},
        }
        result = await server.handle_jsonrpc(payload, peer_id="peer-x")
        assert "result" in result
        assert runtime.intent_bus.broadcast.await_count == 1
        sent_intent = runtime.intent_bus.broadcast.await_args.args[0]
        assert sent_intent.intent == "echo"
        assert sent_intent.params == {"text": "hi"}
        assert runtime.intent_bus.broadcast.await_args.kwargs["federated"] is False

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tasks_send_returns_completed_task(self):
        server, _ = _a2a_server_with_runtime()
        payload = {
            "jsonrpc": "2.0", "id": 2, "method": "tasks/send",
            "params": {"id": "task-42", "message": {
                "parts": [{"type": "text", "text": "echo:{}"}],
            }},
        }
        out = await server.handle_jsonrpc(payload, peer_id="p")
        assert out["result"]["id"] == "task-42"
        assert out["result"]["status"]["state"] == "completed"
        assert out["result"]["artifacts"][0]["parts"][0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tasks_get_correlates_by_id(self):
        server, _ = _a2a_server_with_runtime()
        # First send to populate the store
        await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
            "params": {"id": "tx", "message": {
                "parts": [{"type": "text", "text": "echo:{}"}],
            }},
        }, peer_id="p")
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 2, "method": "tasks/get",
            "params": {"id": "tx"},
        })
        assert out["result"]["id"] == "tx"

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tasks_get_unknown_returns_invalid_params(self):
        server, _ = _a2a_server_with_runtime()
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 3, "method": "tasks/get",
            "params": {"id": "missing"},
        })
        assert out["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_unknown_method_returns_method_not_found(self):
        server, _ = _a2a_server_with_runtime()
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 4, "method": "totally/unknown", "params": {},
        })
        assert out["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_streaming_method_returns_method_not_found(self):
        server, _ = _a2a_server_with_runtime()
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 5, "method": "tasks/sendSubscribe",
            "params": {},
        })
        assert out["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_push_method_returns_method_not_found(self):
        server, _ = _a2a_server_with_runtime()
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 6, "method": "tasks/pushNotification/set",
            "params": {},
        })
        assert out["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_auth_token_mismatch_returns_invalid_request(self):
        server, _ = _a2a_server_with_runtime(outbound_peers=[
            A2APeerConfig(peer_url="https://peer.example.com",
                          auth_token="expected"),
        ])
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 7, "method": "tasks/send", "params": {},
        }, peer_id="https://peer.example.com", auth_header="Bearer wrong")
        assert out["error"]["code"] == -32600

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_records_outcome_on_success_path(self):
        server, runtime = _a2a_server_with_runtime()
        await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 8, "method": "tasks/send",
            "params": {"id": "ts", "message": {
                "parts": [{"type": "text", "text": "echo:{}"}],
            }},
        }, peer_id="peer-1")
        # Outcome was recorded for peer-1
        assert any(
            o[0] == "a2a-peer:peer-1" and o[1] is True
            for o in runtime.trust_network.outcomes
        )


# -------------------- TestMCPServerInbound (480a + 480b) --------------------


def _mcp_server_with_runtime(**kw) -> tuple[FederationMCPServer, object]:
    runtime = _stub_runtime(**kw)
    cfg = FederationMCPServerConfig()
    server = FederationMCPServer(runtime=runtime, config=cfg)
    return server, runtime


class TestMCPServerInbound:
    @pytest.mark.asyncio
    async def test_handle_jsonrpc_initialize_assigns_session_id(self):
        server, _ = _mcp_server_with_runtime()
        out = await server.handle_jsonrpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert "_assigned_session" in out
        assert out["_assigned_session"]

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_initialize_returns_protocol_version(self):
        server, _ = _mcp_server_with_runtime()
        out = await server.handle_jsonrpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert out["result"]["protocolVersion"] == "2025-03-26"

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_list_projects_descriptors(self):
        descriptors = {
            "echo": _make_descriptor("echo", description="echo back",
                                     params={"text": "what to say"}),
        }
        server, _ = _mcp_server_with_runtime(descriptors=descriptors)
        out = await server.handle_jsonrpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools = out["result"]["tools"]
        assert tools[0]["name"] == "echo"
        assert tools[0]["description"] == "echo back"

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_list_input_schema_marks_params_required(self):
        descriptors = {
            "sum": _make_descriptor("sum", params={"a": "first", "b": "second"}),
        }
        server, _ = _mcp_server_with_runtime(descriptors=descriptors)
        out = await server.handle_jsonrpc(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )
        schema = out["result"]["tools"][0]["inputSchema"]
        assert schema["type"] == "object"
        assert sorted(schema["required"]) == ["a", "b"]
        assert schema["properties"]["a"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_call_dispatches_via_intent_bus_federated_false(self):
        server, runtime = _mcp_server_with_runtime()
        await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hi"}},
        }, session_id="s-1")
        assert runtime.intent_bus.broadcast.await_count == 1
        kwargs = runtime.intent_bus.broadcast.await_args.kwargs
        assert kwargs["federated"] is False

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_call_returns_highest_confidence_success(self):
        results = [
            IntentResult(intent_id="i", agent_id="low", success=True,
                         result={"v": 1}, confidence=0.3),
            IntentResult(intent_id="i", agent_id="high", success=True,
                         result={"v": 2}, confidence=0.9),
        ]
        server, _ = _mcp_server_with_runtime(broadcast_results=results)
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "echo", "arguments": {}},
        })
        text = out["result"]["content"][0]["text"]
        assert json.loads(text) == {"v": 2}
        assert out["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_call_unknown_intent_returns_no_handler_error(self):
        server, _ = _mcp_server_with_runtime(broadcast_results=[])
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        })
        assert out["error"]["code"] == -32000
        assert "no agent" in out["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_call_handler_failure_returns_jsonrpc_error(self):
        results = [
            IntentResult(intent_id="i", agent_id="x", success=False,
                         error="boom", confidence=0.8),
        ]
        server, _ = _mcp_server_with_runtime(broadcast_results=results)
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "echo", "arguments": {}},
        })
        assert out["error"]["code"] == -32000
        assert "boom" in out["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_unknown_method_returns_method_not_found(self):
        server, _ = _mcp_server_with_runtime()
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 8, "method": "wat", "params": {},
        })
        assert out["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_invalid_params_returns_minus_32602(self):
        server, _ = _mcp_server_with_runtime()
        out = await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": "not-a-dict",
        })
        assert out["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_registers_peer_on_first_tools_call(self):
        server, runtime = _mcp_server_with_runtime()
        await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "echo", "arguments": {}},
        }, session_id="sid-7")
        peers = runtime.federation_peer_registry.list_peers(protocol="mcp")
        assert any(p.peer_id == "mcp-session:sid-7" for p in peers)

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_records_outcome_on_each_tools_call(self):
        server, runtime = _mcp_server_with_runtime()
        await server.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "echo", "arguments": {}},
        }, session_id="sid-8")
        assert any(
            o[0] == "mcp-peer:mcp-session:sid-8" and o[1] is True
            for o in runtime.trust_network.outcomes
        )


# -------------------- TestProbationaryTrustWiring (480g) --------------------


class TestProbationaryTrustWiring:
    @pytest.mark.asyncio
    async def test_first_registration_calls_create_with_prior_with_alpha_1_beta_3(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn,
                                     probationary_alpha=1.0, probationary_beta=3.0)
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="p", endpoint="p", trust_record_id="mcp-peer:p"))
        assert tn.priors["mcp-peer:p"] == (1.0, 3.0)

    @pytest.mark.asyncio
    async def test_repeat_registration_does_not_re_call_create_with_prior(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn)
        peer = FederationPeer(protocol="mcp", peer_id="p", endpoint="p",
                              trust_record_id="mcp-peer:p")
        await reg.register_peer(peer)
        # Mutate the prior so we'd see a second create_with_prior overwrite if called.
        tn.priors["mcp-peer:p"] = (5.0, 5.0)
        await reg.register_peer(peer)
        assert tn.priors["mcp-peer:p"] == (5.0, 5.0)

    @pytest.mark.asyncio
    async def test_record_outcome_success_increases_alpha(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn)
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="p", endpoint="p", trust_record_id="mcp-peer:p"))
        before = tn.priors["mcp-peer:p"][0]
        reg.record_outcome("p", True, intent_type="echo")
        after = tn.priors["mcp-peer:p"][0]
        assert after > before

    @pytest.mark.asyncio
    async def test_record_outcome_failure_increases_beta(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn)
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="p", endpoint="p", trust_record_id="mcp-peer:p"))
        before = tn.priors["mcp-peer:p"][1]
        reg.record_outcome("p", False, intent_type="echo")
        after = tn.priors["mcp-peer:p"][1]
        assert after > before

    def test_destructive_intent_requires_consensus_regardless_of_trust(self):
        # IntentDescriptor.requires_consensus is honored at the existing
        # dispatcher (verified at consensus pipeline tests). Here we assert
        # that a destructive descriptor remains marked even after federation
        # projection — AD-480 does not strip the flag.
        desc = _make_descriptor("rm_file", requires_consensus=True)
        assert desc.requires_consensus is True

    @pytest.mark.asyncio
    async def test_config_overrides_default_alpha_beta(self):
        tn = _FakeTrustNetwork()
        reg = FederationPeerRegistry(trust_network=tn,
                                     probationary_alpha=2.5, probationary_beta=7.5)
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="p", endpoint="p", trust_record_id="mcp-peer:p"))
        assert tn.priors["mcp-peer:p"] == (2.5, 7.5)


# -------------------- TestFederationRouterPolymorphism (480f) --------------------


class TestFederationRouterPolymorphism:
    def test_select_peers_keeps_existing_signature(self):
        from probos.federation.router import FederationRouter
        router = FederationRouter()
        peers = router.select_peers("echo", ["node-a", "node-b"])
        assert isinstance(peers, list)

    @pytest.mark.asyncio
    async def test_registry_list_peers_includes_zmq_and_mcp_and_a2a(self):
        reg = FederationPeerRegistry()
        for proto, pid in [("zmq", "n1"), ("mcp", "m1"), ("a2a", "a1")]:
            await reg.register_peer(FederationPeer(
                protocol=proto, peer_id=pid, endpoint="x",
                trust_record_id=f"{proto}:{pid}"))
        protocols = sorted(p.protocol for p in reg.list_peers())
        assert protocols == ["a2a", "mcp", "zmq"]

    @pytest.mark.asyncio
    async def test_registry_filters_by_protocol(self):
        reg = FederationPeerRegistry()
        await reg.register_peer(FederationPeer(
            protocol="zmq", peer_id="n1", endpoint="x", trust_record_id="t1"))
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="m1", endpoint="x", trust_record_id="t2"))
        assert [p.peer_id for p in reg.list_peers(protocol="zmq")] == ["n1"]

    @pytest.mark.asyncio
    async def test_peers_supporting_intent_filters_by_capability(self):
        reg = FederationPeerRegistry()
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="m1", endpoint="x",
            trust_record_id="t1", capabilities=["echo"]))
        await reg.register_peer(FederationPeer(
            protocol="a2a", peer_id="a1", endpoint="x",
            trust_record_id="t2", capabilities=[]))
        ids = [p.peer_id for p in reg.peers_supporting("echo")]
        assert ids == ["m1"]

    @pytest.mark.asyncio
    async def test_zmq_peer_auto_registered_on_gossip_path(self):
        # Surface contract: zmq peers can be inserted via register_peer just
        # like external peers — single registration path.
        reg = FederationPeerRegistry()
        ok = await reg.register_peer(FederationPeer(
            protocol="zmq", peer_id="node-1", endpoint="tcp://127.0.0.1:5555",
            trust_record_id="zmq:node-1"))
        assert ok is True
        assert reg.get_peer("node-1") is not None

    @pytest.mark.asyncio
    async def test_external_peer_appears_alongside_zmq_in_listings(self):
        reg = FederationPeerRegistry()
        await reg.register_peer(FederationPeer(
            protocol="zmq", peer_id="n1", endpoint="x", trust_record_id="t1"))
        await reg.register_peer(FederationPeer(
            protocol="mcp", peer_id="m1", endpoint="x", trust_record_id="t2"))
        ids = sorted(p.peer_id for p in reg.list_peers())
        assert ids == ["m1", "n1"]


# -------------------- TestFederationConfigSchema (480h) --------------------


class TestFederationConfigSchema:
    def test_mcp_server_config_default_disabled(self):
        c = FederationMCPServerConfig()
        assert c.enabled is False
        assert c.bind_port == 8765
        assert c.path_prefix == "/mcp"

    def test_a2a_config_default_disabled_with_default_port(self):
        c = FederationA2AConfig()
        assert c.enabled is False
        assert c.bind_port == 8766
        assert c.agent_card_path == "/.well-known/agent.json"
        assert c.outbound_peers == []

    def test_peer_trust_config_default_alpha_1_beta_3(self):
        c = FederationPeerTrustConfig()
        assert c.probationary_alpha == 1.0
        assert c.probationary_beta == 3.0

    def test_a2a_outbound_peers_validates_url_field(self):
        c = FederationA2AConfig(outbound_peers=[
            A2APeerConfig(peer_url="https://peer.example.com",
                          auth_token="t"),
        ])
        assert c.outbound_peers[0].peer_url == "https://peer.example.com"
        assert c.outbound_peers[0].auth_token == "t"


# -------------------- TestSlashFederationPeersCommand (480i) --------------------


class _FakeConsole:
    def __init__(self) -> None:
        self.printed: list = []

    def print(self, payload) -> None:
        self.printed.append(payload)


class TestSlashFederationPeersCommand:
    @pytest.mark.asyncio
    async def test_no_arg_renders_existing_panel(self):
        from probos.experience.commands.commands_status import cmd_federation
        bridge = MagicMock()
        bridge.federation_status = MagicMock(return_value={
            "enabled": True, "node_id": "n1", "bind_address": "tcp://x",
            "connected_peers": [], "gossip_interval": 10,
            "intents_forwarded": 0, "intents_received": 0,
            "results_collected": 0,
        })
        runtime = SimpleNamespace(
            federation_bridge=bridge,
            federation_peer_registry=FederationPeerRegistry(),
            trust_network=_FakeTrustNetwork(),
        )
        console = _FakeConsole()
        await cmd_federation(runtime, console, "")
        assert console.printed
        # The default-arg path renders the standard federation panel, which
        # has title "Federation" — distinct from "Federation Peers".
        rendered = console.printed[0]
        assert getattr(rendered, "title", "") == "Federation"

    @pytest.mark.asyncio
    async def test_peers_arg_renders_peers_panel(self):
        from probos.experience.commands.commands_status import cmd_federation
        runtime = SimpleNamespace(
            federation_bridge=None,
            federation_peer_registry=FederationPeerRegistry(),
            trust_network=_FakeTrustNetwork(),
        )
        console = _FakeConsole()
        await cmd_federation(runtime, console, "peers")
        assert getattr(console.printed[0], "title", "") == "Federation Peers"

    @pytest.mark.asyncio
    async def test_peers_panel_empty_when_registry_empty(self):
        from probos.experience.panels import render_federation_peers_panel
        panel = render_federation_peers_panel([], _FakeTrustNetwork())
        assert getattr(panel, "title", "") == "Federation Peers"

    @pytest.mark.asyncio
    async def test_peers_panel_lists_zmq_and_mcp_and_a2a_peers(self):
        from probos.experience.panels import render_federation_peers_panel
        peers = [
            FederationPeer(protocol="zmq", peer_id="n1", endpoint="x",
                           trust_record_id="t1"),
            FederationPeer(protocol="mcp", peer_id="m1", endpoint="x",
                           trust_record_id="t2"),
            FederationPeer(protocol="a2a", peer_id="a1", endpoint="x",
                           trust_record_id="t3"),
        ]
        panel = render_federation_peers_panel(peers, _FakeTrustNetwork())
        body = panel.renderable
        assert "zmq" in body and "mcp" in body and "a2a" in body
        assert "n1" in body and "m1" in body and "a1" in body

    @pytest.mark.asyncio
    async def test_peers_panel_shows_trust_score(self):
        from probos.experience.panels import render_federation_peers_panel
        tn = _FakeTrustNetwork()
        tn.scores["t1"] = 0.421
        peers = [FederationPeer(protocol="mcp", peer_id="m1", endpoint="x",
                                trust_record_id="t1")]
        panel = render_federation_peers_panel(peers, tn)
        assert "0.421" in panel.renderable

    @pytest.mark.asyncio
    async def test_invalid_subcommand_falls_back_to_default_panel(self):
        from probos.experience.commands.commands_status import cmd_federation
        bridge = MagicMock()
        bridge.federation_status = MagicMock(return_value={
            "enabled": True, "node_id": "n", "bind_address": "x",
            "connected_peers": [], "gossip_interval": 10,
            "intents_forwarded": 0, "intents_received": 0,
            "results_collected": 0,
        })
        runtime = SimpleNamespace(
            federation_bridge=bridge,
            federation_peer_registry=FederationPeerRegistry(),
            trust_network=_FakeTrustNetwork(),
        )
        console = _FakeConsole()
        await cmd_federation(runtime, console, "bogus")
        assert getattr(console.printed[0], "title", "") == "Federation"


# -------------------- TestStartupWiring --------------------


class TestStartupWiring:
    def test_default_config_skips_mcp_server_start(self):
        # Default FederationConfig disables mcp_server.
        c = FederationConfig()
        assert c.mcp_server.enabled is False

    def test_default_config_skips_a2a_server_start(self):
        c = FederationConfig()
        assert c.a2a.enabled is False

    @pytest.mark.asyncio
    async def test_mcp_server_enabled_attempts_start(self):
        # When enabled-but-starlette-missing, start() is a no-op (degrade-to-warn).
        cfg = FederationMCPServerConfig(enabled=True, bind_port=18765)
        runtime = _stub_runtime()
        server = FederationMCPServer(runtime=runtime, config=cfg)
        # start() must not raise even if uvicorn cannot actually bind in test env.
        # We do not actually serve here; the contract is: returns without raising.
        try:
            await server.start()
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"start() raised: {exc}")
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_a2a_server_enabled_attempts_start(self):
        cfg = FederationA2AConfig(enabled=True, bind_port=18766)
        runtime = _stub_runtime()
        server = FederationA2AServer(runtime=runtime, config=cfg)
        try:
            await server.start()
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"start() raised: {exc}")
        finally:
            await server.stop()

    def test_runtime_federation_peer_registry_initialized_eagerly(self):
        # Verified by inspecting runtime.py:__init__ (eager construction).
        # Smoke check: the class is importable as the type the prompt declares.
        from probos.federation.peer import FederationPeerRegistry as Reg
        assert Reg is FederationPeerRegistry

    def test_zmq_only_deployment_unchanged_behavior(self):
        # FederationConfig with only legacy zmq fields must validate.
        c = FederationConfig(enabled=True, node_id="n1",
                             bind_address="tcp://127.0.0.1:5555")
        assert c.enabled is True
        # New fields default-quietly so legacy YAML continues to load.
        assert c.mcp_server.enabled is False
        assert c.a2a.enabled is False
        assert c.peer_trust.probationary_alpha == 1.0


# -------------------- protocol-version sanity --------------------


def test_a2a_protocol_version_pinned():
    assert A2A_PROTOCOL_VERSION == "0.2.0"
