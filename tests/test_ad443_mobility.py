"""AD-443: Agent Mobility — Transfer Certificates & Memory Portability tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.config import FederationConfig
from probos.federation.bridge import FederationBridge
from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.router import FederationRouter
from probos.identity import (
    AgentIdentityRegistry,
    generate_ship_did,
)
from probos.mobility import (
    MemoryPolicy,
    TransferCertificate,
    apply_memory_policy,
)
from probos.types import FederationMessage, NodeSelfModel


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
async def registry(tmp_path: Path):
    reg = AgentIdentityRegistry(data_dir=tmp_path)
    await reg.start(instance_id="inst-A", vessel_name="USS Enterprise", version="v0.5.0")
    yield reg
    await reg.stop()


def _make_transfer_cert(**overrides) -> TransferCertificate:
    defaults = dict(
        did="did:probos:inst-A:uuid-001",
        agent_uuid="uuid-001",
        agent_type="counselor",
        callsign="Troi",
        origin_ship_did="did:probos:inst-A",
        origin_vessel_name="USS Enterprise",
        origin_instance_id="inst-A",
        origin_birth_timestamp=1700000000.0,
        transfer_timestamp=1700001000.0,
        target_instance_did="did:probos:inst-B",
        baseline_version="v0.5.0",
        qualification_credentials=[],
        assignment_history=[],
    )
    defaults.update(overrides)
    cert = TransferCertificate(**defaults)
    cert.certificate_hash = cert.compute_hash()
    return cert


# ── Class 1 — TransferCertificate ─────────────────────────────────────────


class TestTransferCertificate:
    def test_compute_hash_deterministic(self) -> None:
        c = _make_transfer_cert()
        assert c.compute_hash() == c.compute_hash()

    def test_compute_hash_changes_on_field_change(self) -> None:
        c1 = _make_transfer_cert()
        c2 = _make_transfer_cert(callsign="Counselor")
        assert c1.compute_hash() != c2.compute_hash()

    def test_to_verifiable_credential_type(self) -> None:
        c = _make_transfer_cert()
        vc = c.to_verifiable_credential()
        assert vc["type"] == ["VerifiableCredential", "AgentTransferCertificate"]

    def test_to_verifiable_credential_issuer_is_origin_ship(self) -> None:
        c = _make_transfer_cert()
        vc = c.to_verifiable_credential()
        assert vc["issuer"] == c.origin_ship_did

    def test_to_verifiable_credential_birth_provenance_block(self) -> None:
        c = _make_transfer_cert()
        vc = c.to_verifiable_credential()
        bp = vc["credentialSubject"]["birthProvenance"]
        assert bp["shipDid"] == c.origin_ship_did
        assert bp["vesselName"] == c.origin_vessel_name
        assert bp["instanceId"] == c.origin_instance_id
        assert "birthTimestamp" in bp

    def test_to_dict_round_trip(self) -> None:
        c = _make_transfer_cert(qualification_credentials=["q1"], assignment_history=[{"k": "v"}])
        round_tripped = TransferCertificate.from_dict(c.to_dict())
        assert round_tripped == c

    def test_qualification_credentials_default_empty(self) -> None:
        c = TransferCertificate(
            did="d", agent_uuid="u", agent_type="t", callsign="c",
            origin_ship_did="o", origin_vessel_name="v", origin_instance_id="i",
            origin_birth_timestamp=0.0, transfer_timestamp=0.0,
            target_instance_did="td", baseline_version="b",
        )
        assert c.qualification_credentials == []

    def test_assignment_history_default_empty(self) -> None:
        c = TransferCertificate(
            did="d", agent_uuid="u", agent_type="t", callsign="c",
            origin_ship_did="o", origin_vessel_name="v", origin_instance_id="i",
            origin_birth_timestamp=0.0, transfer_timestamp=0.0,
            target_instance_did="td", baseline_version="b",
        )
        assert c.assignment_history == []

    def test_qualification_credentials_sorted_in_hash_payload(self) -> None:
        c1 = _make_transfer_cert(qualification_credentials=["a", "b", "c"])
        c2 = _make_transfer_cert(qualification_credentials=["c", "b", "a"])
        assert c1.compute_hash() == c2.compute_hash()

    def test_certificate_hash_excluded_from_hash_payload(self) -> None:
        c = _make_transfer_cert()
        original = c.compute_hash()
        c.certificate_hash = "something-else-entirely"
        assert c.compute_hash() == original


# ── Class 2 — Chain Import & Verify ───────────────────────────────────────


@pytest.fixture
async def registry_b(tmp_path_factory):
    p = tmp_path_factory.mktemp("regB")
    reg = AgentIdentityRegistry(data_dir=p)
    await reg.start(instance_id="inst-B", vessel_name="USS Defiant", version="v0.5.0")
    yield reg
    await reg.stop()


class TestChainImportVerify:
    @pytest.mark.asyncio
    async def test_export_then_import_roundtrip(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        ok, msg = await registry_b.import_chain(chain)
        assert ok, msg

    @pytest.mark.asyncio
    async def test_verify_remote_chain_accepts_well_formed(
        self, registry: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        ok, msg = await registry.verify_remote_chain(chain)
        assert ok, msg

    @pytest.mark.asyncio
    async def test_verify_remote_chain_empty_returns_false(
        self, registry: AgentIdentityRegistry
    ) -> None:
        ok, msg = await registry.verify_remote_chain([])
        assert not ok

    @pytest.mark.asyncio
    async def test_verify_remote_chain_tampered_block_hash(
        self, registry: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        chain[0]["block_hash"] = "0" * 64
        ok, msg = await registry.verify_remote_chain(chain)
        assert not ok
        assert "hash mismatch" in msg

    @pytest.mark.asyncio
    async def test_verify_remote_chain_broken_linkage(
        self, registry: AgentIdentityRegistry
    ) -> None:
        await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        chain = await registry.export_chain()
        assert len(chain) >= 2
        chain[1]["previous_hash"] = "f" * 64
        # also recompute chain[1]'s block_hash to avoid the hash-mismatch path
        from probos.identity import LedgerBlock
        b = LedgerBlock(
            index=chain[1]["index"], timestamp=chain[1]["timestamp"],
            certificate_hash=chain[1]["certificate_hash"],
            agent_did=chain[1]["agent_did"],
            previous_hash=chain[1]["previous_hash"],
            block_hash="",
        )
        chain[1]["block_hash"] = b.compute_hash()
        ok, msg = await registry.verify_remote_chain(chain)
        assert not ok
        assert "linkage" in msg.lower()

    @pytest.mark.asyncio
    async def test_verify_remote_chain_genesis_previous_not_zero(
        self, registry: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        chain[0]["previous_hash"] = "1" * 64
        # recompute hash so we hit the genesis check, not the hash mismatch
        from probos.identity import LedgerBlock
        b = LedgerBlock(
            index=chain[0]["index"], timestamp=chain[0]["timestamp"],
            certificate_hash=chain[0]["certificate_hash"],
            agent_did=chain[0]["agent_did"],
            previous_hash=chain[0]["previous_hash"],
            block_hash="",
        )
        chain[0]["block_hash"] = b.compute_hash()
        ok, msg = await registry.verify_remote_chain(chain)
        assert not ok
        assert "Genesis" in msg or "genesis" in msg

    @pytest.mark.asyncio
    async def test_import_chain_persists_under_origin_ship_did(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        await registry_b.import_chain(chain)
        ship_did = generate_ship_did("inst-A")
        assert registry_b.get_foreign_chain(ship_did) is not None

    @pytest.mark.asyncio
    async def test_import_chain_replaces_prior_snapshot(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        chain1 = await registry.export_chain()
        await registry_b.import_chain(chain1)
        await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        chain2 = await registry.export_chain()
        await registry_b.import_chain(chain2)
        ship_did = generate_ship_did("inst-A")
        stored = registry_b.get_foreign_chain(ship_did)
        assert stored is not None
        assert len(stored) == len(chain2)

    @pytest.mark.asyncio
    async def test_import_chain_rejects_invalid_chain(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        chain[0]["block_hash"] = "0" * 64
        ok, _ = await registry_b.import_chain(chain)
        assert not ok
        ship_did = generate_ship_did("inst-A")
        assert registry_b.get_foreign_chain(ship_did) is None

    @pytest.mark.asyncio
    async def test_import_chain_survives_restart(
        self, registry: AgentIdentityRegistry, tmp_path_factory
    ) -> None:
        p = tmp_path_factory.mktemp("regB-restart")
        chain = await registry.export_chain()
        regB = AgentIdentityRegistry(data_dir=p)
        await regB.start(instance_id="inst-B", vessel_name="USS Defiant", version="v0.5.0")
        await regB.import_chain(chain)
        await regB.stop()

        regB2 = AgentIdentityRegistry(data_dir=p)
        await regB2.start(instance_id="inst-B", vessel_name="USS Defiant", version="v0.5.0")
        try:
            ship_did = generate_ship_did("inst-A")
            assert regB2.get_foreign_chain(ship_did) is not None
        finally:
            await regB2.stop()

    @pytest.mark.asyncio
    async def test_import_chain_empty_returns_false_no_persist(
        self, registry_b: AgentIdentityRegistry
    ) -> None:
        ok, _ = await registry_b.import_chain([])
        assert not ok

    @pytest.mark.asyncio
    async def test_export_then_import_other_ship_full_cycle(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        chain = await registry.export_chain()
        ok, _ = await registry_b.import_chain(chain)
        assert ok
        valid, _ = await registry_b.verify_remote_chain(chain)
        assert valid


# ── Class 3 — Slot Reassignment ───────────────────────────────────────────


class TestSlotReassignment:
    @pytest.mark.asyncio
    async def test_reassign_slot_native_cert_moves_mapping(
        self, registry: AgentIdentityRegistry
    ) -> None:
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        ok, _ = await registry.reassign_slot(cert.agent_uuid, "bridge_slot_0")
        assert ok
        assert registry.get_by_slot("bridge_slot_0").agent_uuid == cert.agent_uuid

    @pytest.mark.asyncio
    async def test_reassign_slot_unknown_uuid_rejects(
        self, registry: AgentIdentityRegistry
    ) -> None:
        ok, _ = await registry.reassign_slot("does-not-exist", "slot-x")
        assert not ok

    @pytest.mark.asyncio
    async def test_reassign_slot_empty_slot_id_rejects(
        self, registry: AgentIdentityRegistry
    ) -> None:
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        ok, _ = await registry.reassign_slot(cert.agent_uuid, "")
        assert not ok

    @pytest.mark.asyncio
    async def test_reassign_slot_foreign_cert_returns_via_get_by_slot(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        chain = await registry.export_chain()
        await registry_b.import_chain(chain)
        xfer = await registry.issue_transfer_certificate(
            cert.agent_uuid, target_instance_did=generate_ship_did("inst-B"),
        )
        ok, _ = await registry_b.import_transfer_certificate(xfer)
        assert ok
        ok, _ = await registry_b.reassign_slot(cert.agent_uuid, "ten_forward_slot_0")
        assert ok
        retrieved = registry_b.get_by_slot("ten_forward_slot_0")
        assert retrieved is not None
        assert retrieved.agent_uuid == cert.agent_uuid

    @pytest.mark.asyncio
    async def test_reassign_slot_birth_provenance_preserved(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        chain = await registry.export_chain()
        await registry_b.import_chain(chain)
        xfer = await registry.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        await registry_b.import_transfer_certificate(xfer)
        await registry_b.reassign_slot(cert.agent_uuid, "bridge_slot_0")
        assert registry_b.get_by_slot("bridge_slot_0").vessel_name == "USS Enterprise"

    @pytest.mark.asyncio
    async def test_reassign_slot_overwrites_existing_mapping(
        self, registry: AgentIdentityRegistry
    ) -> None:
        c1 = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
            slot_id="bridge_slot_0",
        )
        c2 = await registry.issue_birth_certificate(
            agent_type="science", callsign="Data", instance_id="inst-A",
            vessel_name="USS Enterprise", department="science",
            post_id="science_officer", baseline_version="v0.5.0",
        )
        await registry.reassign_slot(c2.agent_uuid, "bridge_slot_0")
        retrieved = registry.get_by_slot("bridge_slot_0")
        assert retrieved.agent_uuid == c2.agent_uuid
        assert retrieved.agent_uuid != c1.agent_uuid

    @pytest.mark.asyncio
    async def test_reassign_slot_persists_across_restart(
        self, tmp_path_factory, registry: AgentIdentityRegistry
    ) -> None:
        p = tmp_path_factory.mktemp("regB-slot-restart")
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        chain = await registry.export_chain()
        regB = AgentIdentityRegistry(data_dir=p)
        await regB.start(instance_id="inst-B", vessel_name="USS Defiant", version="v0.5.0")
        await regB.import_chain(chain)
        xfer = await registry.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        await regB.import_transfer_certificate(xfer)
        await regB.reassign_slot(cert.agent_uuid, "ten_forward_slot_0")
        await regB.stop()

        regB2 = AgentIdentityRegistry(data_dir=p)
        await regB2.start(instance_id="inst-B", vessel_name="USS Defiant", version="v0.5.0")
        try:
            assert regB2.get_by_slot("ten_forward_slot_0") is not None
            assert regB2.get_by_slot("ten_forward_slot_0").agent_uuid == cert.agent_uuid
        finally:
            await regB2.stop()

    @pytest.mark.asyncio
    async def test_get_by_uuid_falls_back_to_foreign_cache(
        self, registry: AgentIdentityRegistry, registry_b: AgentIdentityRegistry
    ) -> None:
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        chain = await registry.export_chain()
        await registry_b.import_chain(chain)
        xfer = await registry.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        await registry_b.import_transfer_certificate(xfer)
        retrieved = registry_b.get_by_uuid(cert.agent_uuid)
        assert retrieved is not None
        assert retrieved.did == cert.did

    @pytest.mark.asyncio
    async def test_get_by_uuid_native_wins_on_collision(
        self, registry: AgentIdentityRegistry
    ) -> None:
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        # Force a different cert with same UUID into foreign cache (defensive)
        from probos.identity import AgentBirthCertificate
        fake = AgentBirthCertificate(
            agent_uuid=cert.agent_uuid, did="did:probos:other:" + cert.agent_uuid,
            agent_type="other", callsign="OTHER", instance_id="other",
            vessel_name="USS Other", birth_timestamp=0.0,
            department="other", post_id="other", baseline_version="other",
        )
        registry._foreign_uuid_cache[cert.agent_uuid] = fake
        retrieved = registry.get_by_uuid(cert.agent_uuid)
        assert retrieved is not None
        assert retrieved.callsign == "Troi"  # native won
        assert retrieved.did == cert.did

    @pytest.mark.asyncio
    async def test_reassign_slot_logs_audit_line(
        self, registry: AgentIdentityRegistry, caplog
    ) -> None:
        import logging
        cert = await registry.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        with caplog.at_level(logging.INFO, logger="probos.identity"):
            await registry.reassign_slot(cert.agent_uuid, "bridge_slot_0")
        assert any("Slot reassigned" in r.message for r in caplog.records)
        assert any("bridge_slot_0" in r.message for r in caplog.records)


# ── Class 4 — MemoryPolicy ────────────────────────────────────────────────


class TestMemoryPolicy:
    def test_memory_policy_enum_values(self) -> None:
        assert MemoryPolicy.CLEAN_ROOM == "clean_room"
        assert MemoryPolicy.SELECTIVE == "selective"
        assert MemoryPolicy.FULL == "full"

    def test_apply_memory_policy_clean_room_returns_empty(self) -> None:
        eps = [{"id": "1", "tags": ["a"]}, {"id": "2"}]
        assert apply_memory_policy(MemoryPolicy.CLEAN_ROOM, eps) == []

    def test_apply_memory_policy_full_returns_verbatim(self) -> None:
        eps = [{"id": "1"}, {"id": "2"}]
        assert apply_memory_policy(MemoryPolicy.FULL, eps) == eps

    def test_apply_memory_policy_selective_filters_by_tag(self) -> None:
        eps = [{"id": "1", "tags": ["x", "y"]}, {"id": "2", "tags": ["z"]}]
        result = apply_memory_policy(MemoryPolicy.SELECTIVE, eps, selective_tags=["y"])
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_apply_memory_policy_selective_no_match_excluded(self) -> None:
        eps = [{"id": "1", "tags": ["x"]}]
        assert apply_memory_policy(MemoryPolicy.SELECTIVE, eps, selective_tags=["y"]) == []

    def test_apply_memory_policy_selective_empty_tags_returns_empty(self) -> None:
        eps = [{"id": "1", "tags": ["x"]}]
        assert apply_memory_policy(MemoryPolicy.SELECTIVE, eps, selective_tags=[]) == []

    def test_apply_memory_policy_episode_without_tags_excluded(self) -> None:
        eps = [{"id": "1"}]
        assert apply_memory_policy(MemoryPolicy.SELECTIVE, eps, selective_tags=["any"]) == []

    def test_federation_config_memory_policy_default_clean_room(self) -> None:
        assert FederationConfig().memory_policy == "clean_room"

    def test_federation_config_memory_policy_validator_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            FederationConfig(memory_policy="bogus")

    def test_federation_config_memory_policy_accepts_all_three_values(self) -> None:
        for v in ("clean_room", "selective", "full"):
            assert FederationConfig(memory_policy=v).memory_policy == v


# ── Class 5 — FederationBridge mobility messages ──────────────────────────


def _make_bridge(node_id: str, bus: MockTransportBus, registry, intent_bus_stub):
    transport = MockFederationTransport(node_id, bus)
    router = FederationRouter()
    config = FederationConfig(node_id=node_id, forward_timeout_ms=2000)

    def self_model_fn() -> NodeSelfModel:
        return NodeSelfModel(
            node_id=node_id, capabilities=[], pool_sizes={}, agent_count=0,
            health=1.0, uptime_seconds=0.0, timestamp=0.0,
        )

    bridge = FederationBridge(
        node_id=node_id, transport=transport, router=router,
        intent_bus=intent_bus_stub, config=config, self_model_fn=self_model_fn,
        identity_registry=registry,
    )
    return bridge, transport


class _StubIntentBus:
    async def broadcast(self, intent, federated=False):
        return []


@pytest.fixture
async def two_ship_setup(tmp_path_factory):
    pa = tmp_path_factory.mktemp("ship-A")
    pb = tmp_path_factory.mktemp("ship-B")
    regA = AgentIdentityRegistry(data_dir=pa)
    regB = AgentIdentityRegistry(data_dir=pb)
    await regA.start(instance_id="inst-A", vessel_name="USS Enterprise", version="v0.5.0")
    await regB.start(instance_id="inst-B", vessel_name="USS Defiant", version="v0.5.0")
    bus = MockTransportBus()
    stub_a = _StubIntentBus()
    stub_b = _StubIntentBus()
    bridgeA, transportA = _make_bridge("node-A", bus, regA, stub_a)
    bridgeB, transportB = _make_bridge("node-B", bus, regB, stub_b)
    await transportA.start()
    await transportB.start()
    await bridgeA.start()
    await bridgeB.start()
    yield regA, regB, bridgeA, bridgeB
    await bridgeA.stop()
    await bridgeB.stop()
    await transportA.stop()
    await transportB.stop()
    await regA.stop()
    await regB.stop()


class TestFederationTransferMessages:
    @pytest.mark.asyncio
    async def test_chain_request_returns_export(self, two_ship_setup) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        blocks = await bridgeB.request_chain("node-A")
        expected = await regA.export_chain()
        assert len(blocks) == len(expected)
        assert blocks[0]["block_hash"] == expected[0]["block_hash"]

    @pytest.mark.asyncio
    async def test_chain_request_no_identity_registry_returns_error(
        self, tmp_path_factory
    ) -> None:
        bus = MockTransportBus()
        stub = _StubIntentBus()
        # Bridge A with no registry
        transportA = MockFederationTransport("node-A", bus)
        routerA = FederationRouter()

        def selfA():
            return NodeSelfModel(node_id="node-A", capabilities=[], pool_sizes={},
                                 agent_count=0, health=1.0, uptime_seconds=0.0, timestamp=0.0)

        bridgeA = FederationBridge(
            node_id="node-A", transport=transportA, router=routerA,
            intent_bus=stub, config=FederationConfig(node_id="node-A", forward_timeout_ms=2000),
            self_model_fn=selfA, identity_registry=None,
        )
        # Bridge B issues the request — needs a transport on the bus
        transportB = MockFederationTransport("node-B", bus)
        routerB = FederationRouter()

        def selfB():
            return NodeSelfModel(node_id="node-B", capabilities=[], pool_sizes={},
                                 agent_count=0, health=1.0, uptime_seconds=0.0, timestamp=0.0)

        bridgeB = FederationBridge(
            node_id="node-B", transport=transportB, router=routerB,
            intent_bus=stub, config=FederationConfig(node_id="node-B", forward_timeout_ms=2000),
            self_model_fn=selfB, identity_registry=None,
        )
        await transportA.start(); await transportB.start()
        await bridgeA.start(); await bridgeB.start()
        try:
            # Ask A for chain — A should respond with empty + error.
            # Use receive_with_timeout directly via request_chain
            blocks = await bridgeB.request_chain("node-A")
            assert blocks == []
        finally:
            await bridgeB.stop(); await bridgeA.stop()
            await transportB.stop(); await transportA.stop()

    @pytest.mark.asyncio
    async def test_transfer_request_full_pipeline(self, two_ship_setup) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        cert = await regA.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        xfer = await regA.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        chain = await regA.export_chain()
        ok, msg = await bridgeA.request_transfer("node-B", xfer, chain)
        assert ok, msg
        assert regB.get_by_uuid(cert.agent_uuid) is not None

    @pytest.mark.asyncio
    async def test_transfer_request_invalid_cert_rejected(self, two_ship_setup) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        cert = await regA.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        xfer = await regA.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        xfer.certificate_hash = "f" * 64  # tamper
        chain = await regA.export_chain()
        ok, msg = await bridgeA.request_transfer("node-B", xfer, chain)
        assert not ok

    @pytest.mark.asyncio
    async def test_transfer_request_no_identity_registry_responds_not_wired(
        self, tmp_path_factory
    ) -> None:
        bus = MockTransportBus()
        stub = _StubIntentBus()
        pa = tmp_path_factory.mktemp("ship-A-x")
        regA = AgentIdentityRegistry(data_dir=pa)
        await regA.start(instance_id="inst-A", vessel_name="USS Enterprise", version="v0.5.0")

        bridgeA, transportA = _make_bridge("node-A", bus, regA, stub)

        # Bridge B with NO identity registry
        transportB = MockFederationTransport("node-B", bus)
        routerB = FederationRouter()

        def selfB():
            return NodeSelfModel(node_id="node-B", capabilities=[], pool_sizes={},
                                 agent_count=0, health=1.0, uptime_seconds=0.0, timestamp=0.0)

        bridgeB = FederationBridge(
            node_id="node-B", transport=transportB, router=routerB,
            intent_bus=stub, config=FederationConfig(node_id="node-B", forward_timeout_ms=2000),
            self_model_fn=selfB, identity_registry=None,
        )
        await transportA.start(); await transportB.start()
        await bridgeA.start(); await bridgeB.start()
        try:
            cert = await regA.issue_birth_certificate(
                agent_type="counselor", callsign="Troi", instance_id="inst-A",
                vessel_name="USS Enterprise", department="medical",
                post_id="counselor_officer", baseline_version="v0.5.0",
            )
            xfer = await regA.issue_transfer_certificate(
                cert.agent_uuid, generate_ship_did("inst-B"),
            )
            chain = await regA.export_chain()
            ok, msg = await bridgeA.request_transfer("node-B", xfer, chain)
            assert not ok
            assert "not wired" in msg
        finally:
            await bridgeB.stop(); await bridgeA.stop()
            await transportB.stop(); await transportA.stop()
            await regA.stop()

    @pytest.mark.asyncio
    async def test_transfer_request_does_not_auto_reassign_slot(
        self, two_ship_setup
    ) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        cert = await regA.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        xfer = await regA.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        chain = await regA.export_chain()
        await bridgeA.request_transfer("node-B", xfer, chain)
        # No auto-reassign — looking up by any plausible slot returns nothing
        assert regB.get_by_slot("bridge_slot_0") is None
        # But the cert is reachable via UUID
        assert regB.get_by_uuid(cert.agent_uuid) is not None

    @pytest.mark.asyncio
    async def test_end_to_end_2_ship_transfer_with_reassign(
        self, two_ship_setup
    ) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        cert = await regA.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        xfer = await regA.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        chain = await regA.export_chain()
        ok, _ = await bridgeA.request_transfer("node-B", xfer, chain)
        assert ok
        ok, _ = await regB.reassign_slot(cert.agent_uuid, "bridge_slot_0")
        assert ok
        retrieved = regB.get_by_slot("bridge_slot_0")
        assert retrieved.vessel_name == "USS Enterprise"

    @pytest.mark.asyncio
    async def test_transfer_stats_incremented(self, two_ship_setup) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        cert = await regA.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        xfer = await regA.issue_transfer_certificate(
            cert.agent_uuid, generate_ship_did("inst-B"),
        )
        chain = await regA.export_chain()
        sent_before = bridgeA._stats["transfers_sent"]
        recv_before = bridgeB._stats["transfers_received"]
        await bridgeA.request_transfer("node-B", xfer, chain)
        assert bridgeA._stats["transfers_sent"] == sent_before + 1
        assert bridgeB._stats["transfers_received"] == recv_before + 1

    @pytest.mark.asyncio
    async def test_transfer_request_message_id_correlation(
        self, two_ship_setup
    ) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        cert1 = await regA.issue_birth_certificate(
            agent_type="counselor", callsign="Troi", instance_id="inst-A",
            vessel_name="USS Enterprise", department="medical",
            post_id="counselor_officer", baseline_version="v0.5.0",
        )
        cert2 = await regA.issue_birth_certificate(
            agent_type="science", callsign="Data", instance_id="inst-A",
            vessel_name="USS Enterprise", department="science",
            post_id="science_officer", baseline_version="v0.5.0",
        )
        xfer1 = await regA.issue_transfer_certificate(
            cert1.agent_uuid, generate_ship_did("inst-B"),
        )
        xfer2 = await regA.issue_transfer_certificate(
            cert2.agent_uuid, generate_ship_did("inst-B"),
        )
        chain = await regA.export_chain()
        ok1, _ = await bridgeA.request_transfer("node-B", xfer1, chain)
        ok2, _ = await bridgeA.request_transfer("node-B", xfer2, chain)
        assert ok1 and ok2
        assert regB.get_by_uuid(cert1.agent_uuid) is not None
        assert regB.get_by_uuid(cert2.agent_uuid) is not None

    @pytest.mark.asyncio
    async def test_chain_response_delivered_to_response_queue(
        self, two_ship_setup
    ) -> None:
        regA, regB, bridgeA, bridgeB = two_ship_setup
        blocks = await bridgeB.request_chain("node-A")
        # If the response wasn't delivered to the queue, request_chain would
        # have timed out and returned []. So a non-empty result proves the
        # correlation path worked.
        assert isinstance(blocks, list)
        assert len(blocks) >= 1


# ── Class 6 — Standing Orders Federation tier ─────────────────────────────


_FEDERATION_MD = (
    Path(__file__).resolve().parents[1]
    / "config" / "standing_orders" / "federation.md"
)


class TestStandingOrdersFederationTier:
    def test_federation_md_contains_mobility_section(self) -> None:
        text = _FEDERATION_MD.read_text(encoding="utf-8")
        assert "AD-443" in text
        assert "Memory Policy" in text

    def test_federation_md_clean_room_default_documented(self) -> None:
        text = _FEDERATION_MD.read_text(encoding="utf-8")
        assert "Clean Room" in text
        assert "*(default)*" in text

    def test_federation_md_birth_provenance_referenced(self) -> None:
        text = _FEDERATION_MD.read_text(encoding="utf-8")
        # AD-499 must appear in the mobility section context
        idx = text.find("Mobility & Memory Portability")
        assert idx >= 0
        assert "AD-499" in text[idx:]

    def test_compose_instructions_includes_mobility_section(self) -> None:
        from probos.cognitive.standing_orders import compose_instructions
        composed = compose_instructions(
            agent_type="counselor",
            hardcoded_instructions="You are a counselor.",
            department="medical",
            callsign="Troi",
        )
        assert ("Mobility" in composed) or ("AD-443" in composed)

    def test_per_agent_override_via_additional_orders(self, tmp_path: Path) -> None:
        # Per-agent override mechanism: Tier 5 ({agent_type}.md) is composed
        # AFTER the federation tier. We mirror federation.md into a tmp orders
        # dir, drop a per-agent file, and verify ordering.
        from probos.cognitive.standing_orders import compose_instructions
        (tmp_path / "federation.md").write_text(
            _FEDERATION_MD.read_text(encoding="utf-8"), encoding="utf-8"
        )
        override = "Memory Policy: full per Captain order."
        (tmp_path / "counselor.md").write_text(override, encoding="utf-8")
        composed = compose_instructions(
            agent_type="counselor",
            hardcoded_instructions="You are a counselor.",
            orders_dir=tmp_path,
            department="medical",
            callsign="Troi",
        )
        assert override in composed
        fed_idx = composed.find("Federation Constitution")
        override_idx = composed.find(override)
        assert override_idx > fed_idx
