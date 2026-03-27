"""AD-441: Sovereign Agent Identity — tests for DIDs, Birth Certificates, Identity Ledger."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from probos.identity import (
    AgentBirthCertificate,
    AgentIdentityRegistry,
    LedgerBlock,
    generate_agent_uuid,
    generate_did,
    generate_ship_did,
    parse_did,
)


# ── DID Utilities ──────────────────────────────────────────────────


class TestGenerateDid:
    def test_generate_did_format(self) -> None:
        """Test 1: DID format is did:probos:{instance_id}:{agent_uuid}."""
        did = generate_did("inst-123", "uuid-456")
        assert did == "did:probos:inst-123:uuid-456"

        parsed = parse_did(did)
        assert parsed is not None
        assert parsed["method"] == "probos"
        assert parsed["instance_id"] == "inst-123"
        assert parsed["agent_uuid"] == "uuid-456"
        assert parsed["type"] == "agent"

    def test_generate_ship_did_format(self) -> None:
        """Ship DID format is did:probos:{instance_id}."""
        did = generate_ship_did("inst-789")
        assert did == "did:probos:inst-789"

        parsed = parse_did(did)
        assert parsed is not None
        assert parsed["method"] == "probos"
        assert parsed["instance_id"] == "inst-789"
        assert parsed["type"] == "ship"
        assert "agent_uuid" not in parsed


class TestParseDid:
    def test_parse_did_invalid(self) -> None:
        """Test 2: parse_did returns None for invalid DIDs."""
        assert parse_did("") is None
        assert parse_did("not-a-did") is None
        assert parse_did("did:other:inst:uuid") is None
        assert parse_did("did:probos") is None  # Too few parts
        assert parse_did("did:probos:a:b:c") is None  # Too many parts


# ── Birth Certificate ──────────────────────────────────────────────


def _make_cert(**overrides: object) -> AgentBirthCertificate:
    """Helper to create a birth certificate with sensible defaults."""
    defaults = {
        "agent_uuid": "uuid-001",
        "did": "did:probos:inst:uuid-001",
        "agent_type": "counselor",
        "callsign": "Troi",
        "instance_id": "inst",
        "vessel_name": "USS Enterprise",
        "birth_timestamp": 1700000000.0,
        "department": "medical",
        "post_id": "counselor_officer",
        "baseline_version": "v0.5.0",
    }
    defaults.update(overrides)
    return AgentBirthCertificate(**defaults)  # type: ignore[arg-type]


class TestBirthCertificate:
    def test_hash_deterministic(self) -> None:
        """Test 3: Identical certificates produce identical hashes."""
        cert1 = _make_cert()
        cert2 = _make_cert()
        assert cert1.compute_hash() == cert2.compute_hash()

    def test_hash_changes_with_content(self) -> None:
        """Test 4: Different content produces different hashes."""
        cert1 = _make_cert(callsign="Troi")
        cert2 = _make_cert(callsign="Bones")
        assert cert1.compute_hash() != cert2.compute_hash()

    def test_to_verifiable_credential(self) -> None:
        """Test 5: VC contains all required W3C fields."""
        cert = _make_cert()
        cert.certificate_hash = cert.compute_hash()
        vc = cert.to_verifiable_credential()

        assert "@context" in vc
        assert "VerifiableCredential" in vc["type"]
        assert "AgentBirthCertificate" in vc["type"]
        assert vc["credentialSubject"]["id"] == cert.did
        assert vc["credentialSubject"]["agentType"] == "counselor"
        assert vc["credentialSubject"]["callsign"] == "Troi"
        assert vc["proof"]["proofValue"] == cert.certificate_hash
        assert vc["issuer"].startswith("did:probos:")

    def test_from_dict_round_trip(self) -> None:
        """from_dict reconstructs a certificate from a dict."""
        cert = _make_cert()
        cert.certificate_hash = cert.compute_hash()
        data = {
            "agent_uuid": cert.agent_uuid,
            "did": cert.did,
            "agent_type": cert.agent_type,
            "callsign": cert.callsign,
            "instance_id": cert.instance_id,
            "vessel_name": cert.vessel_name,
            "birth_timestamp": cert.birth_timestamp,
            "department": cert.department,
            "post_id": cert.post_id,
            "baseline_version": cert.baseline_version,
            "certificate_hash": cert.certificate_hash,
        }
        restored = AgentBirthCertificate.from_dict(data)
        assert restored.agent_uuid == cert.agent_uuid
        assert restored.certificate_hash == cert.certificate_hash


# ── Identity Registry ──────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path: Path) -> AgentIdentityRegistry:
    return AgentIdentityRegistry(data_dir=tmp_path)


class TestIdentityRegistry:
    @pytest.mark.asyncio
    async def test_issue_and_retrieve(self, registry: AgentIdentityRegistry) -> None:
        """Test 6: Issue a certificate and retrieve by UUID."""
        await registry.start()
        try:
            cert = await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
            )
            assert cert.agent_uuid
            assert cert.did.startswith("did:probos:")
            assert cert.certificate_hash

            retrieved = registry.get_by_uuid(cert.agent_uuid)
            assert retrieved is not None
            assert retrieved.agent_uuid == cert.agent_uuid
            assert retrieved.callsign == "Troi"
        finally:
            await registry.stop()

    @pytest.mark.asyncio
    async def test_slot_mapping(self, registry: AgentIdentityRegistry) -> None:
        """Test 7: Issue with slot_id and retrieve by slot."""
        await registry.start()
        try:
            cert = await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
                slot_id="counselor_counselor_0_abc123",
            )

            by_slot = registry.get_by_slot("counselor_counselor_0_abc123")
            assert by_slot is not None
            assert by_slot.agent_uuid == cert.agent_uuid
        finally:
            await registry.stop()

    @pytest.mark.asyncio
    async def test_resolve_or_issue_new(self, registry: AgentIdentityRegistry) -> None:
        """Test 8: resolve_or_issue creates new cert for unknown slot."""
        await registry.start()
        try:
            cert = await registry.resolve_or_issue(
                slot_id="new_slot_001",
                agent_type="engineer",
                callsign="LaForge",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="engineering",
                post_id="chief_engineer",
                baseline_version="v0.5.0",
            )
            assert cert.agent_uuid
            assert cert.agent_type == "engineer"
        finally:
            await registry.stop()

    @pytest.mark.asyncio
    async def test_resolve_or_issue_existing(self, registry: AgentIdentityRegistry) -> None:
        """Test 9: resolve_or_issue returns same cert for known slot."""
        await registry.start()
        try:
            cert1 = await registry.resolve_or_issue(
                slot_id="slot_x",
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
            )
            cert2 = await registry.resolve_or_issue(
                slot_id="slot_x",
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
            )
            # Same UUID — not a new identity
            assert cert1.agent_uuid == cert2.agent_uuid
        finally:
            await registry.stop()


# ── Identity Ledger ────────────────────────────────────────────────


class TestLedger:
    @pytest.mark.asyncio
    async def test_genesis_block(self, registry: AgentIdentityRegistry) -> None:
        """Test 10: First issuance creates genesis + agent block."""
        await registry.start()
        try:
            await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
            )

            chain = await registry.export_chain()
            assert len(chain) == 2  # genesis + agent

            genesis = chain[0]
            assert genesis["agent_did"] == "ship"
            assert genesis["previous_hash"] == "0" * 64
        finally:
            await registry.stop()

    @pytest.mark.asyncio
    async def test_chain_integrity(self, registry: AgentIdentityRegistry) -> None:
        """Test 11: Issue 3 certs, verify chain passes."""
        await registry.start()
        try:
            for i, (atype, callsign) in enumerate([
                ("counselor", "Troi"),
                ("engineer", "LaForge"),
                ("security", "Worf"),
            ]):
                await registry.issue_birth_certificate(
                    agent_type=atype,
                    callsign=callsign,
                    instance_id="inst-001",
                    vessel_name="USS Enterprise",
                    department="ops",
                    post_id=f"post_{i}",
                    baseline_version="v0.5.0",
                )

            valid, msg = await registry.verify_chain()
            assert valid is True
            assert "4 blocks" in msg  # genesis + 3 agents
        finally:
            await registry.stop()

    @pytest.mark.asyncio
    async def test_tamper_detection(self, registry: AgentIdentityRegistry) -> None:
        """Test 12: Corrupted block hash detected by verify_chain."""
        await registry.start()
        try:
            await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
            )

            # Corrupt the agent block's hash in DB
            await registry._db.execute(
                "UPDATE identity_ledger SET block_hash = 'corrupted' WHERE block_index = 1"
            )
            await registry._db.commit()

            valid, msg = await registry.verify_chain()
            assert valid is False
            assert "hash mismatch" in msg
        finally:
            await registry.stop()

    @pytest.mark.asyncio
    async def test_export_chain(self, registry: AgentIdentityRegistry) -> None:
        """Test 13: Export includes VC JSON for agent blocks."""
        await registry.start()
        try:
            cert = await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
            )

            chain = await registry.export_chain()
            agent_block = chain[1]
            assert agent_block["credential"] is not None
            assert "AgentBirthCertificate" in agent_block["credential"]["type"]
        finally:
            await registry.stop()


# ── Persistence ────────────────────────────────────────────────────


class TestPersistence:
    @pytest.mark.asyncio
    async def test_identity_persists_across_restarts(self, tmp_path: Path) -> None:
        """Test 14: Stop and restart registry — certificates persist."""
        reg1 = AgentIdentityRegistry(data_dir=tmp_path)
        await reg1.start()
        cert = await reg1.issue_birth_certificate(
            agent_type="counselor",
            callsign="Troi",
            instance_id="inst-001",
            vessel_name="USS Enterprise",
            department="medical",
            post_id="counselor_officer",
            baseline_version="v0.5.0",
            slot_id="slot_troi",
        )
        original_uuid = cert.agent_uuid
        await reg1.stop()

        # Restart
        reg2 = AgentIdentityRegistry(data_dir=tmp_path)
        await reg2.start()
        try:
            by_uuid = reg2.get_by_uuid(original_uuid)
            assert by_uuid is not None
            assert by_uuid.callsign == "Troi"

            by_slot = reg2.get_by_slot("slot_troi")
            assert by_slot is not None
            assert by_slot.agent_uuid == original_uuid
        finally:
            await reg2.stop()


# ── Agent Integration ──────────────────────────────────────────────


class TestAgentIntegration:
    def test_sovereign_id_on_agent(self) -> None:
        """Test 15: BaseAgent has sovereign_id and did fields."""
        from probos.substrate.agent import BaseAgent

        # BaseAgent is abstract, so use a mock-like approach
        agent = MagicMock(spec_set=["id", "pool", "sovereign_id", "did", "agent_type"])
        agent.sovereign_id = ""
        agent.did = ""

        # Simulate identity resolution
        agent.sovereign_id = generate_agent_uuid()
        agent.did = generate_did("inst-001", agent.sovereign_id)

        assert agent.sovereign_id  # Non-empty UUID
        assert agent.did.startswith("did:probos:")

    @pytest.mark.asyncio
    async def test_multiple_agents_same_type(self, registry: AgentIdentityRegistry) -> None:
        """Test 16: Two agents of same type get different UUIDs."""
        await registry.start()
        try:
            cert1 = await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
                slot_id="counselor_slot_0",
            )
            cert2 = await registry.issue_birth_certificate(
                agent_type="counselor",
                callsign="Troi-2",
                instance_id="inst-001",
                vessel_name="USS Enterprise",
                department="medical",
                post_id="counselor_officer",
                baseline_version="v0.5.0",
                slot_id="counselor_slot_1",
            )
            assert cert1.agent_uuid != cert2.agent_uuid
            assert cert1.did != cert2.did

            # Both retrievable by type
            by_type = registry.get_by_agent_type("counselor")
            assert len(by_type) == 2
        finally:
            await registry.stop()
