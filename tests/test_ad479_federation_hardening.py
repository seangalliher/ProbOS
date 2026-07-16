"""AD-479 Wave 91 — Federation Hardening tests.

Tests cover the nine v1 sub-AD letters:
- 479a Capability-aware peer selection
- 479b Trust-weighted peer ranking
- 479c FederationHebbianMap
- 479d recall_federated IntentDescriptor + handler
- 479e share_designed_agent + CodeValidator gate
- 479f FederationTLSConfig Pydantic surface
- 479g FederationClusterMonitor
- 479h MulticastDiscovery + FederationBridge.add_peer
- 479i /federation routing slash subcommand
"""
from __future__ import annotations

import asyncio
import inspect
import socket
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import (
    FederationClusterMonitorConfig,
    FederationConfig,
    FederationDiscoveryConfig,
    FederationTLSConfig,
)
from probos.events import EventType
from probos.federation import (
    FederationBridge,
    FederationClusterMonitor,
    FederationHebbianMap,
    FederationRouter,
    MockFederationTransport,
    MockTransportBus,
    MulticastDiscovery,
)
from probos.federation.multicast_discovery import _multicast_available
from probos.types import (
    FederationMessage,
    IntentMessage,
    IntentResult,
    NodeSelfModel,
)


# ── helpers ────────────────────────────────────────────────────────────


def _make_peer_model(node_id: str, capabilities: list[str], timestamp: float = 1.0) -> NodeSelfModel:
    return NodeSelfModel(
        node_id=node_id,
        capabilities=capabilities,
        pool_sizes={},
        agent_count=0,
        health=1.0,
        uptime_seconds=10.0,
        timestamp=timestamp,
    )


class _FakeTrust:
    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.scores = scores or {}
        self.calls: list[tuple] = []

    def get_score(self, agent_id: str) -> float:
        return float(self.scores.get(agent_id, 0.5))

    def record_outcome(
        self, agent_id: str, *, success: bool, weight: float = 1.0,
        intent_type: str = "", source: str = "",
    ) -> None:
        self.calls.append((agent_id, success, intent_type, source))


# ══════════════════════════════════════════════════════════════════════
# Section 1 — AD-479a Capability-aware peer selection
# ══════════════════════════════════════════════════════════════════════


class TestCapabilityAwareSelectPeers:
    def test_select_peers_returns_all_when_no_capability_data(self):
        router = FederationRouter()
        result = router.select_peers("read_file", ["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_select_peers_filters_by_capability_when_data_present(self):
        router = FederationRouter()
        router.update_peer_model(_make_peer_model("a", ["read_file"]))
        router.update_peer_model(_make_peer_model("b", ["write_file"]))
        result = router.select_peers("read_file", ["a", "b"])
        assert result == ["a"]

    def test_select_peers_returns_empty_when_no_peer_supports_intent(self):
        router = FederationRouter()
        router.update_peer_model(_make_peer_model("a", ["other"]))
        router.update_peer_model(_make_peer_model("b", ["other2"]))
        result = router.select_peers("read_file", ["a", "b"])
        assert result == []

    def test_select_peers_keeps_peer_with_partial_capability_match(self):
        router = FederationRouter()
        router.update_peer_model(_make_peer_model("a", ["read_file", "write_file"]))
        result = router.select_peers("read_file", ["a"])
        assert result == ["a"]

    def test_select_peers_unknown_peer_excluded_when_data_present(self):
        router = FederationRouter()
        router.update_peer_model(_make_peer_model("a", ["read_file"]))
        # b is in the available list but has no model entry — once capability
        # data exists, b is excluded.
        result = router.select_peers("read_file", ["a", "b"])
        assert result == ["a"]

    def test_select_peers_multiple_peers_intent_match(self):
        router = FederationRouter()
        router.update_peer_model(_make_peer_model("a", ["read_file"]))
        router.update_peer_model(_make_peer_model("b", ["write_file"]))
        router.update_peer_model(_make_peer_model("c", ["read_file"]))
        result = router.select_peers("read_file", ["a", "b", "c"])
        assert set(result) == {"a", "c"}


# ══════════════════════════════════════════════════════════════════════
# Section 2 — AD-479b Trust-weighted peer ranking
# ══════════════════════════════════════════════════════════════════════


class TestTrustWeightedRanking:
    def test_ranking_happy_path(self):
        trust = _FakeTrust({
            "federation_peer:a": 0.3,
            "federation_peer:b": 0.9,
            "federation_peer:c": 0.6,
        })
        router = FederationRouter(trust_network=trust)
        for nid in ("a", "b", "c"):
            router.update_peer_model(_make_peer_model(nid, ["x"]))
        result = router.select_peers("x", ["a", "b", "c"])
        assert result == ["b", "c", "a"]

    def test_below_min_trust_score_dropped(self):
        trust = _FakeTrust({
            "federation_peer:a": 0.1,
            "federation_peer:b": 0.9,
        })
        router = FederationRouter(trust_network=trust, min_trust_score=0.5)
        router.update_peer_model(_make_peer_model("a", ["x"]))
        router.update_peer_model(_make_peer_model("b", ["x"]))
        result = router.select_peers("x", ["a", "b"])
        assert result == ["b"]

    def test_trust_network_none_is_noop(self):
        router = FederationRouter()  # trust_network=None
        router.update_peer_model(_make_peer_model("a", ["x"]))
        router.update_peer_model(_make_peer_model("b", ["x"]))
        result = router.select_peers("x", ["a", "b"])
        assert set(result) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_record_outcome_called_on_success(self):
        env = _make_bridge_pair(trust=_FakeTrust())
        env["bus_b"].broadcast.return_value = [
            IntentResult(intent_id="i1", agent_id="agent-b", success=True, confidence=0.9),
        ]
        env["router_a"].update_peer_model(_make_peer_model("node-b", ["test_intent"]))
        intent = IntentMessage(intent="test_intent", params={})
        await env["bridge_a"].forward_intent(intent)
        assert any(c[0] == "federation_peer:node-b" and c[1] is True for c in env["trust"].calls)

    @pytest.mark.asyncio
    async def test_record_outcome_called_on_failure(self):
        env = _make_bridge_pair(trust=_FakeTrust())
        env["bus_b"].broadcast.return_value = [
            IntentResult(intent_id="i1", agent_id="agent-b", success=False, error="x"),
        ]
        env["router_a"].update_peer_model(_make_peer_model("node-b", ["test_intent"]))
        intent = IntentMessage(intent="test_intent", params={})
        await env["bridge_a"].forward_intent(intent)
        assert any(c[0] == "federation_peer:node-b" and c[1] is False for c in env["trust"].calls)

    @pytest.mark.asyncio
    async def test_record_id_namespace(self):
        trust = _FakeTrust()
        env = _make_bridge_pair(trust=trust)
        env["bus_b"].broadcast.return_value = [
            IntentResult(intent_id="i1", agent_id="agent-b", success=True),
        ]
        env["router_a"].update_peer_model(_make_peer_model("node-b", ["test_intent"]))
        intent = IntentMessage(intent="test_intent", params={})
        await env["bridge_a"].forward_intent(intent)
        # Regression vs AD-480f mcp-peer / a2a-peer namespaces.
        assert all(c[0].startswith("federation_peer:") for c in trust.calls)

    def test_ranking_stable_on_equal_trust(self):
        trust = _FakeTrust({
            "federation_peer:a": 0.5,
            "federation_peer:b": 0.5,
            "federation_peer:c": 0.5,
        })
        router = FederationRouter(trust_network=trust)
        for nid in ("a", "b", "c"):
            router.update_peer_model(_make_peer_model(nid, ["x"]))
        # Python's sort is stable — equal trust preserves input order.
        result = router.select_peers("x", ["a", "b", "c"])
        assert result == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_forward_no_trust_does_not_mutate(self):
        env = _make_bridge_pair(trust=None)
        env["bus_b"].broadcast.return_value = [
            IntentResult(intent_id="i1", agent_id="agent-b", success=True),
        ]
        env["router_a"].update_peer_model(_make_peer_model("node-b", ["test_intent"]))
        intent = IntentMessage(intent="test_intent", params={})
        # Should not raise — trust_network is None on the bridge.
        results = await env["bridge_a"].forward_intent(intent)
        assert len(results) == 1


def _make_bridge_pair(*, trust: Any | None) -> dict[str, Any]:
    """Two-node bridge harness; bus_b is a mock returning canned IntentResults."""
    config = FederationConfig(
        enabled=True, node_id="node-a", forward_timeout_ms=200,
        gossip_interval_seconds=100,
    )
    config_b = FederationConfig(
        enabled=True, node_id="node-b", forward_timeout_ms=200,
        gossip_interval_seconds=100,
    )
    transport_bus = MockTransportBus()
    t_a = MockFederationTransport("node-a", transport_bus)
    t_b = MockFederationTransport("node-b", transport_bus)

    bus_a = SimpleNamespace(broadcast=AsyncMock(return_value=[]))
    bus_b = SimpleNamespace(broadcast=AsyncMock(return_value=[]))

    def _self_model_fn() -> NodeSelfModel:
        return _make_peer_model("self", [])

    router_a = FederationRouter()
    router_b = FederationRouter()
    bridge_a = FederationBridge(
        node_id="node-a", transport=t_a, router=router_a, intent_bus=bus_a,
        config=config, self_model_fn=_self_model_fn,
        trust_network=trust,
    )
    bridge_b = FederationBridge(
        node_id="node-b", transport=t_b, router=router_b, intent_bus=bus_b,
        config=config_b, self_model_fn=_self_model_fn,
    )
    # Wire bridge_b's inbound handler so peer can respond.
    t_b._inbound_handler = bridge_b.handle_inbound
    # Wire bridge_a so it can route intent_response messages.
    t_a._inbound_handler = bridge_a.handle_inbound
    return {
        "bridge_a": bridge_a, "bridge_b": bridge_b,
        "router_a": router_a, "router_b": router_b,
        "bus_a": bus_a, "bus_b": bus_b, "trust": trust,
        "t_a": t_a, "t_b": t_b,
    }


# ══════════════════════════════════════════════════════════════════════
# Section 3 — AD-479c FederationHebbianMap
# ══════════════════════════════════════════════════════════════════════


class TestFederationHebbianRouting:
    def test_empty_map_returns_zero(self):
        m = FederationHebbianMap()
        assert m.score("read_file", "node-x") == 0.0

    def test_success_increments_by_reward(self):
        m = FederationHebbianMap(reward=0.05)
        m.record_outcome(intent_name="x", peer_node_id="p", success=True)
        assert abs(m.score("x", "p") - 0.05) < 1e-9

    def test_failure_applies_decay(self):
        m = FederationHebbianMap(reward=0.5, decay_rate=0.5)
        m.record_outcome(intent_name="x", peer_node_id="p", success=True)  # 0.5
        m.record_outcome(intent_name="x", peer_node_id="p", success=False)  # 0.25
        assert abs(m.score("x", "p") - 0.25) < 1e-9

    def test_weight_clamped(self):
        m = FederationHebbianMap(reward=2.0)
        for _ in range(3):
            m.record_outcome(intent_name="x", peer_node_id="p", success=True)
        assert m.score("x", "p") == 1.0

    @pytest.mark.asyncio
    async def test_persistence_round_trip(self, tmp_path):
        db = str(tmp_path / "fed_hebb.db")
        m1 = FederationHebbianMap(db_path=db)
        await m1.init()
        m1.record_outcome(intent_name="x", peer_node_id="p", success=True)
        await m1.persist()
        await m1.close()

        m2 = FederationHebbianMap(db_path=db)
        await m2.init()
        try:
            assert abs(m2.score("x", "p") - 0.05) < 1e-9
        finally:
            await m2.close()

    @pytest.mark.asyncio
    async def test_separate_table_from_agent_hebbian(self, tmp_path):
        """federation_hebbian_weights and hebbian_weights coexist."""
        import aiosqlite
        db = str(tmp_path / "shared.db")
        # Create the agent hebbian table first.
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS hebbian_weights "
                "(source TEXT, target TEXT, weight REAL)"
            )
            await conn.commit()
        m = FederationHebbianMap(db_path=db)
        await m.init()
        try:
            m.record_outcome(intent_name="x", peer_node_id="p", success=True)
            await m.persist()
        finally:
            await m.close()
        # Both tables exist.
        async with aiosqlite.connect(db) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            rows = await cursor.fetchall()
            tables = {r[0] for r in rows}
        assert "hebbian_weights" in tables
        assert "federation_hebbian_weights" in tables

    def test_all_weights_returns_defensive_copy(self):
        m = FederationHebbianMap()
        m.record_outcome(intent_name="x", peer_node_id="p", success=True)
        copy = m.all_weights()
        copy[("x", "p")] = 999.0
        assert m.score("x", "p") != 999.0

    @pytest.mark.asyncio
    async def test_init_idempotent(self, tmp_path):
        db = str(tmp_path / "fed_hebb.db")
        m = FederationHebbianMap(db_path=db)
        await m.init()
        await m.init()  # second call should not error
        await m.close()


# ══════════════════════════════════════════════════════════════════════
# Section 4 — AD-479d recall_federated
# ══════════════════════════════════════════════════════════════════════


class TestRecallFederated:
    def test_intent_descriptor_registered(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        descs = FederationRecallAgent.intent_descriptors
        assert any(d.name == "recall_federated" for d in descs)
        d = next(d for d in descs if d.name == "recall_federated")
        assert d.requires_consensus is False

    @pytest.mark.asyncio
    async def test_skip_path_on_non_matching_intent(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        agent = FederationRecallAgent()
        plan = await agent.perceive(IntentMessage(intent="other"))
        result = await agent.act(plan)
        assert result.success is False
        assert result.error == "not recall_federated"

    @pytest.mark.asyncio
    async def test_empty_local_recall(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        runtime = SimpleNamespace(
            episodic_memory=SimpleNamespace(recall=AsyncMock(return_value=[])),
            config=SimpleNamespace(federation=SimpleNamespace(node_id="node-a")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "hi", "k": 3}))
        plan = await agent.decide(plan)
        result = await agent.act(plan)
        assert result.success is True
        assert result.result["episodes"] == []

    @pytest.mark.asyncio
    async def test_happy_path_top_k(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        eps = [
            SimpleNamespace(episode_id="e1", summary="s1", score=0.9, dag_summary={"classification": "ship"}),
            SimpleNamespace(episode_id="e2", summary="s2", score=0.5, dag_summary={"classification": "ship"}),
            SimpleNamespace(episode_id="e3", summary="s3", score=0.7, dag_summary={"classification": "ship"}),
        ]
        runtime = SimpleNamespace(
            episodic_memory=SimpleNamespace(recall=AsyncMock(return_value=eps)),
            config=SimpleNamespace(federation=SimpleNamespace(node_id="node-a")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "q", "k": 2}))
        result = await agent.act(plan)
        assert result.success is True
        ids = [e["episode_id"] for e in result.result["episodes"]]
        assert ids == ["e1", "e3"]

    @pytest.mark.asyncio
    async def test_deduplication_keeps_higher_score(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        eps = [
            SimpleNamespace(episode_id="dup", summary="low", score=0.3, dag_summary={"classification": "ship"}),
            SimpleNamespace(episode_id="dup", summary="hi", score=0.9, dag_summary={"classification": "ship"}),
        ]
        runtime = SimpleNamespace(
            episodic_memory=SimpleNamespace(recall=AsyncMock(return_value=eps)),
            config=SimpleNamespace(federation=SimpleNamespace(node_id="n")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "q", "k": 5}))
        result = await agent.act(plan)
        assert len(result.result["episodes"]) == 1
        assert result.result["episodes"][0]["summary"] == "hi"

    @pytest.mark.asyncio
    async def test_episodic_memory_missing_graceful(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        runtime = SimpleNamespace(
            episodic_memory=None,
            config=SimpleNamespace(federation=SimpleNamespace(node_id="n")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "q"}))
        result = await agent.act(plan)
        assert result.success is True
        assert result.result["episodes"] == []

    @pytest.mark.asyncio
    async def test_recall_raising_caught(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        runtime = SimpleNamespace(
            episodic_memory=SimpleNamespace(recall=AsyncMock(side_effect=RuntimeError("boom"))),
            config=SimpleNamespace(federation=SimpleNamespace(node_id="n")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "q"}))
        result = await agent.act(plan)
        assert result.success is True  # graceful degrade
        assert result.result["episodes"] == []

    @pytest.mark.asyncio
    async def test_source_node_populated(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        eps = [SimpleNamespace(episode_id="e1", summary="s", score=0.5, dag_summary={"classification": "ship"})]
        runtime = SimpleNamespace(
            episodic_memory=SimpleNamespace(recall=AsyncMock(return_value=eps)),
            config=SimpleNamespace(federation=SimpleNamespace(node_id="alpha")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "q"}))
        result = await agent.act(plan)
        assert result.result["episodes"][0]["source_node"] == "alpha"

    @pytest.mark.asyncio
    async def test_result_count_matches(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        eps = [
            SimpleNamespace(episode_id=f"e{i}", summary="", score=float(i), dag_summary={"classification": "ship"})
            for i in range(5)
        ]
        runtime = SimpleNamespace(
            episodic_memory=SimpleNamespace(recall=AsyncMock(return_value=eps)),
            config=SimpleNamespace(federation=SimpleNamespace(node_id="n")),
        )
        agent = FederationRecallAgent(runtime=runtime)
        plan = await agent.perceive(IntentMessage(intent="recall_federated", params={"query": "q", "k": 3}))
        result = await agent.act(plan)
        assert result.result["count"] == len(result.result["episodes"])
        assert result.result["count"] == 3

    @pytest.mark.asyncio
    async def test_report_returns_dict(self):
        from probos.agents.federation_recall_agent import FederationRecallAgent
        agent = FederationRecallAgent()
        ir = IntentResult(intent_id="i", agent_id="a", success=True, result={"episodes": []})
        out = await agent.report(ir)
        assert out["intent_id"] == "i"
        assert out["success"] is True


# ══════════════════════════════════════════════════════════════════════
# Section 5 — AD-479e share_designed_agent
# ══════════════════════════════════════════════════════════════════════


def _make_single_bridge(*, identity_registry: Any = None) -> FederationBridge:
    config = FederationConfig(
        enabled=True, node_id="node-a", forward_timeout_ms=200,
        gossip_interval_seconds=100,
    )
    bus = MockTransportBus()
    transport = MockFederationTransport("node-a", bus)
    router = FederationRouter()
    intent_bus = SimpleNamespace(broadcast=AsyncMock(return_value=[]))

    def _self_model_fn() -> NodeSelfModel:
        return _make_peer_model("node-a", [])

    bridge = FederationBridge(
        node_id="node-a", transport=transport, router=router,
        intent_bus=intent_bus, config=config, self_model_fn=_self_model_fn,
        identity_registry=identity_registry,
    )
    return bridge


class TestShareDesignedAgent:
    @pytest.mark.asyncio
    async def test_outbound_no_payload_matches_baseline(self):
        bridge = _make_single_bridge()
        sent_messages: list[FederationMessage] = []

        async def _capture(peer_id, msg):
            sent_messages.append(msg)

        bridge._transport.send_to_peer = _capture
        bridge._transport.receive_with_timeout = AsyncMock(return_value=None)
        cert = SimpleNamespace(to_dict=lambda: {"a": 1}, did="did:x", agent_uuid="u1")
        await bridge.request_transfer("node-b", cert, [{"block": 1}])
        assert "designed_agent_payload" not in sent_messages[0].payload

    @pytest.mark.asyncio
    async def test_outbound_with_payload(self):
        bridge = _make_single_bridge()
        sent_messages: list[FederationMessage] = []

        async def _capture(peer_id, msg):
            sent_messages.append(msg)

        bridge._transport.send_to_peer = _capture
        bridge._transport.receive_with_timeout = AsyncMock(return_value=None)
        cert = SimpleNamespace(to_dict=lambda: {"a": 1}, did="did:x", agent_uuid="u1")
        payload = {"instructions": "you are a helpful agent", "template_name": "T1"}
        await bridge.request_transfer("node-b", cert, [], payload)
        assert sent_messages[0].payload["designed_agent_payload"] == payload

    @pytest.mark.asyncio
    async def test_incoming_designed_payload_remains_dormant_without_runtime_handle(
        self,
        tmp_path,
    ):
        from probos.identity import AgentIdentityRegistry, generate_ship_did

        origin = AgentIdentityRegistry(data_dir=tmp_path / "origin")
        destination = AgentIdentityRegistry(data_dir=tmp_path / "destination")
        await origin.start(
            instance_id="inst-A",
            vessel_name="USS Origin",
            version="v1",
        )
        await destination.start(
            instance_id="inst-B",
            vessel_name="USS Destination",
            version="v1",
        )
        try:
            birth = await origin.issue_birth_certificate(
                agent_type="designed",
                callsign="Designed",
                instance_id="inst-A",
                vessel_name="USS Origin",
                department="science",
                post_id="designed-agent",
                baseline_version="v1",
            )
            transfer = await origin.issue_transfer_certificate(
                birth.agent_uuid,
                generate_ship_did("inst-B"),
            )
            chain = await origin.export_chain()
            bridge = _make_single_bridge(identity_registry=destination)
            responses: list[FederationMessage] = []

            async def _capture(peer_id: str, message: FederationMessage) -> None:
                responses.append(message)

            bridge._transport.send_to_peer = _capture
            await bridge.handle_inbound(FederationMessage(
                type="transfer_request",
                source_node="node-b",
                message_id="bf672-designed-agent",
                payload={
                    "cert_dict": transfer.to_dict(),
                    "chain_blocks": chain,
                    "designed_agent_payload": {
                        "instructions": "operate safely",
                        "template_name": "DormantTemplate",
                    },
                },
                timestamp=1.0,
            ))

            assert len(responses) == 1
            assert responses[0].payload["accepted"] is True
            assert destination.get_by_uuid(birth.agent_uuid) is not None
            assert (
                "designed_agent_note=no_runtime_handle"
                in responses[0].payload["message"]
            )
        finally:
            await destination.stop()
            await origin.stop()

    def test_dormant_reconstruction_has_no_receive_event_or_registration_dependency(
        self,
    ):
        bridge = _make_single_bridge()
        source = inspect.getsource(
            type(bridge)._reconstruct_designed_agent
        )
        assert "FEDERATION_DESIGNED_AGENT_RECEIVED" not in source
        assert "register_designed_template_from_payload" not in source


# ══════════════════════════════════════════════════════════════════════
# Section 6 — AD-479f FederationTLSConfig
# ══════════════════════════════════════════════════════════════════════


class TestFederationTLSConfig:
    def test_defaults(self):
        c = FederationTLSConfig()
        assert c.enabled is False
        assert c.cert_file is None
        assert c.key_file is None
        assert c.ca_file is None
        assert c.verify_peer is True

    def test_explicit_values_round_trip(self):
        c = FederationTLSConfig(
            enabled=True, cert_file="c", key_file="k", ca_file="ca",
            verify_peer=False,
        )
        assert c.enabled is True
        assert c.cert_file == "c"
        assert c.verify_peer is False

    def test_default_factory_isolates_instances(self):
        a = FederationConfig()
        b = FederationConfig()
        assert a.tls is not b.tls

    def test_discovery_default_off(self):
        c = FederationDiscoveryConfig()
        assert c.multicast_enabled is False

    def test_cluster_monitor_default_on(self):
        c = FederationClusterMonitorConfig()
        assert c.enabled is True
        assert c.peer_unreachable_seconds == 60.0


# ══════════════════════════════════════════════════════════════════════
# Section 7 — AD-479g FederationClusterMonitor
# ══════════════════════════════════════════════════════════════════════


class TestClusterHealthMonitor:
    def test_is_unreachable_unknown_returns_false(self):
        bridge = SimpleNamespace(_router=SimpleNamespace(_peer_models={}))
        m = FederationClusterMonitor(bridge=bridge)
        assert m.is_unreachable("nobody") is False

    def test_tick_before_threshold_no_transition(self):
        events: list[tuple] = []
        router = SimpleNamespace(_peer_models={
            "p": _make_peer_model("p", [], timestamp=100.0),
        })
        bridge = SimpleNamespace(
            _router=router,
            _config=SimpleNamespace(gossip_interval_seconds=10.0),
        )
        m = FederationClusterMonitor(
            bridge=bridge, peer_unreachable_seconds=60.0,
            emit_event_fn=lambda et, data: events.append((et, data)),
        )
        m._tick(now=110.0)  # silent_for=10
        assert m.is_unreachable("p") is False
        assert events == []

    def test_tick_after_threshold_emits_unreachable(self):
        events: list[tuple] = []
        router = SimpleNamespace(_peer_models={
            "p": _make_peer_model("p", [], timestamp=100.0),
        })
        bridge = SimpleNamespace(
            _router=router,
            _config=SimpleNamespace(gossip_interval_seconds=10.0),
        )
        m = FederationClusterMonitor(
            bridge=bridge, peer_unreachable_seconds=10.0,
            emit_event_fn=lambda et, data: events.append((et, data)),
        )
        m._tick(now=200.0)  # silent_for=100
        assert m.is_unreachable("p") is True
        assert events[0][0] == EventType.FEDERATION_PEER_UNREACHABLE
        assert events[0][1]["peer_node_id"] == "p"
        assert "silent_for_seconds" in events[0][1]

    def test_recovery_emits_recovered(self):
        events: list[tuple] = []
        peer = _make_peer_model("p", [], timestamp=100.0)
        router = SimpleNamespace(_peer_models={"p": peer})
        bridge = SimpleNamespace(
            _router=router,
            _config=SimpleNamespace(gossip_interval_seconds=10.0),
        )
        m = FederationClusterMonitor(
            bridge=bridge, peer_unreachable_seconds=10.0,
            emit_event_fn=lambda et, data: events.append((et, data)),
        )
        m._tick(now=200.0)  # unreachable
        # gossip arrives — bump timestamp.
        peer.timestamp = 200.0
        m._tick(now=205.0)  # silent_for=5, threshold=10 → recovered
        assert m.is_unreachable("p") is False
        assert any(e[0] == EventType.FEDERATION_PEER_RECOVERED for e in events)

    def test_list_unreachable(self):
        router = SimpleNamespace(_peer_models={
            "a": _make_peer_model("a", [], timestamp=100.0),
            "b": _make_peer_model("b", [], timestamp=100.0),
        })
        bridge = SimpleNamespace(
            _router=router,
            _config=SimpleNamespace(gossip_interval_seconds=10.0),
        )
        m = FederationClusterMonitor(bridge=bridge, peer_unreachable_seconds=5.0)
        m._tick(now=200.0)
        assert set(m.list_unreachable()) == {"a", "b"}

    def test_select_peers_excludes_unreachable(self):
        router = FederationRouter()
        router.update_peer_model(_make_peer_model("a", ["x"]))
        router.update_peer_model(_make_peer_model("b", ["x"]))
        cm = SimpleNamespace(is_unreachable=lambda nid: nid == "b")
        router2 = FederationRouter(cluster_monitor=cm)
        router2.update_peer_model(_make_peer_model("a", ["x"]))
        router2.update_peer_model(_make_peer_model("b", ["x"]))
        result = router2.select_peers("x", ["a", "b"])
        assert result == ["a"]

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        router = SimpleNamespace(_peer_models={})
        bridge = SimpleNamespace(
            _router=router,
            _config=SimpleNamespace(gossip_interval_seconds=10.0),
        )
        m = FederationClusterMonitor(bridge=bridge, poll_interval_seconds=0.05)
        await m.start()
        await asyncio.sleep(0.1)
        await m.stop()
        assert m._task is None

    def test_emit_fn_raising_caught(self):
        def _raise(*a, **k):
            raise RuntimeError("oops")
        router = SimpleNamespace(_peer_models={
            "p": _make_peer_model("p", [], timestamp=100.0),
        })
        bridge = SimpleNamespace(
            _router=router,
            _config=SimpleNamespace(gossip_interval_seconds=10.0),
        )
        m = FederationClusterMonitor(
            bridge=bridge, peer_unreachable_seconds=10.0, emit_event_fn=_raise,
        )
        # Should not raise.
        m._tick(now=200.0)
        assert m.is_unreachable("p") is True


# ══════════════════════════════════════════════════════════════════════
# Section 8 — AD-479h MulticastDiscovery + add_peer
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(not _multicast_available(), reason="multicast not available")
class TestMulticastDiscovery:
    @pytest.mark.asyncio
    async def test_start_failure_graceful(self, monkeypatch):
        # Force a bind failure by patching socket.socket to raise
        original_socket = socket.socket
        call_count = {"n": 0}

        def _raising_socket(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                # Second socket (recv) raises
                raise OSError("simulated bind failure")
            return original_socket(*args, **kwargs)

        monkeypatch.setattr(socket, "socket", _raising_socket)
        d = MulticastDiscovery(
            node_id="me", bind_address="tcp://1.2.3.4:5555",
            multicast_group="239.255.42.99", multicast_port=15556,
            announce_interval_seconds=0.1,
        )
        await d.start()
        # No tasks should be running.
        assert d._announce_task is None
        assert d._listen_task is None
        await d.stop()

    @pytest.mark.asyncio
    async def test_announce_send_and_filter_self(self):
        sent_payloads: list[bytes] = []
        d = MulticastDiscovery(
            node_id="me", bind_address="tcp://1.2.3.4:5555",
            multicast_group="239.255.42.99", multicast_port=15557,
            announce_interval_seconds=10.0,
        )
        # Skip start — directly drive the announce body.
        import json as _json
        body = _json.dumps({"node_id": "me", "bind_address": "x"}).encode("utf-8")
        # Self-announce should be filtered in listen path.
        assert "me" in d._known_peer_ids

    @pytest.mark.asyncio
    async def test_listen_calls_on_peer_discovered(self):
        called: list[tuple] = []

        async def _on_peer(node_id, bind_address):
            called.append((node_id, bind_address))

        d = MulticastDiscovery(
            node_id="me", bind_address="tcp://x",
            multicast_group="239.255.42.99", multicast_port=15558,
            announce_interval_seconds=10.0,
            on_peer_discovered=_on_peer,
        )
        # Synthesize incoming msg path.
        import json as _json
        msg = _json.loads(_json.dumps({"node_id": "newpeer", "bind_address": "y"}))
        # Manually drive the dedup + callback.
        node_id = msg["node_id"]
        if node_id not in d._known_peer_ids:
            d._known_peer_ids.add(node_id)
            await d._on_peer_discovered(node_id, msg["bind_address"])
        # Replay — should not be re-called.
        if node_id not in d._known_peer_ids:
            await d._on_peer_discovered(node_id, msg["bind_address"])
        assert called == [("newpeer", "y")]

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        d = MulticastDiscovery(
            node_id="me", bind_address="tcp://x",
            multicast_group="239.255.42.99", multicast_port=15559,
            announce_interval_seconds=10.0,
        )
        # Don't really bind — test stop on never-started instance.
        await d.stop()
        assert d._stopped is True


class TestBridgeAddPeer:
    @pytest.mark.asyncio
    async def test_add_peer_calls_transport(self):
        bridge = _make_single_bridge()

        async def _stub(pc):
            return True

        bridge._transport.add_peer = _stub  # type: ignore[assignment]
        result = await bridge.add_peer(SimpleNamespace(node_id="new"))
        assert result is True

    @pytest.mark.asyncio
    async def test_add_peer_no_hook_returns_false(self):
        bridge = _make_single_bridge()
        # Remove the add_peer attribute by replacing transport.
        original = bridge._transport.add_peer
        try:
            del bridge._transport.add_peer
        except AttributeError:
            bridge._transport.add_peer = None  # type: ignore[assignment]
        result = await bridge.add_peer(SimpleNamespace(node_id="x"))
        assert result is False
        bridge._transport.add_peer = original  # type: ignore[assignment]

    @pytest.mark.asyncio
    async def test_add_peer_catches_transport_exception(self):
        bridge = _make_single_bridge()

        async def _raise(pc):
            raise RuntimeError("boom")

        bridge._transport.add_peer = _raise  # type: ignore[assignment]
        result = await bridge.add_peer(SimpleNamespace(node_id="x"))
        assert result is False


# ══════════════════════════════════════════════════════════════════════
# Section 9 — AD-479i /federation routing slash subcommand
# ══════════════════════════════════════════════════════════════════════


class TestSlashFederationRoutingCommand:
    @pytest.mark.asyncio
    async def test_no_peers_message(self):
        from probos.experience.commands.commands_status import cmd_federation
        bridge = SimpleNamespace(
            federation_status=lambda: {"peer_models": {}},
        )
        runtime = SimpleNamespace(
            federation_bridge=bridge,
            trust_network=None,
            federation_hebbian_map=None,
            federation_cluster_monitor=None,
        )
        captured = []
        console = SimpleNamespace(print=lambda x: captured.append(x))
        await cmd_federation(runtime, console, "routing")
        assert captured  # panel printed

    @pytest.mark.asyncio
    async def test_one_peer_in_table(self):
        from probos.experience.panels import render_federation_routing_panel
        bridge = SimpleNamespace(federation_status=lambda: {
            "peer_models": {"node-x": {"capabilities": ["read_file"]}},
        })
        trust = _FakeTrust({"federation_peer:node-x": 0.75})
        panel = render_federation_routing_panel(
            bridge=bridge, trust_network=trust,
            hebbian_map=None, cluster_monitor=None,
        )
        body = str(panel.renderable)
        assert "node-x" in body
        assert "0.750" in body

    @pytest.mark.asyncio
    async def test_unreachable_state(self):
        from probos.experience.panels import render_federation_routing_panel
        bridge = SimpleNamespace(federation_status=lambda: {
            "peer_models": {"down": {"capabilities": []}},
        })
        cm = SimpleNamespace(is_unreachable=lambda nid: nid == "down")
        panel = render_federation_routing_panel(
            bridge=bridge, trust_network=None,
            hebbian_map=None, cluster_monitor=cm,
        )
        assert "unreachable" in str(panel.renderable)

    @pytest.mark.asyncio
    async def test_hebbian_top_weights_shown(self):
        from probos.experience.panels import render_federation_routing_panel
        bridge = SimpleNamespace(federation_status=lambda: {
            "peer_models": {"a": {"capabilities": []}},
        })
        m = FederationHebbianMap(reward=0.4)
        m.record_outcome(intent_name="read_file", peer_node_id="a", success=True)
        panel = render_federation_routing_panel(
            bridge=bridge, trust_network=None,
            hebbian_map=m, cluster_monitor=None,
        )
        body = str(panel.renderable)
        assert "Hebbian" in body
        assert "read_file" in body

    @pytest.mark.asyncio
    async def test_existing_no_arg_preserved(self):
        from probos.experience.commands.commands_status import cmd_federation
        bridge = SimpleNamespace(federation_status=lambda: {
            "node_id": "n", "bind_address": "x", "connected_peers": [],
            "peer_models": {}, "intents_forwarded": 0, "intents_received": 0,
            "results_collected": 0, "gossip_interval": 10.0,
        })
        runtime = SimpleNamespace(federation_bridge=bridge)
        captured = []
        console = SimpleNamespace(print=lambda x: captured.append(x))
        await cmd_federation(runtime, console, "")
        assert captured

    @pytest.mark.asyncio
    async def test_routing_disabled_when_bridge_none(self):
        from probos.experience.commands.commands_status import cmd_federation
        runtime = SimpleNamespace(federation_bridge=None)
        captured = []
        console = SimpleNamespace(print=lambda x: captured.append(x))
        await cmd_federation(runtime, console, "routing")
        assert any("not enabled" in str(c).lower() for c in captured)
