"""AD-441: Sovereign Agent Identity — DIDs, Birth Certificates, Identity Ledger.

Implements W3C Decentralized Identifiers (DIDs) and Verifiable Credentials (VCs)
for persistent, globally unique, cryptographically verifiable agent identity.

DID Method: did:probos:{instance_id}:{agent_uuid}
Birth Certificate: W3C VC with AgentBirthCertificate type
Identity Ledger: Append-only hash-chain (blockchain) of birth certificates

'Every agent is born once. Their identity is permanent. Their record is immutable.'
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# W3C VC context — included for forward compatibility with VC ecosystem
VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
PROBOS_CONTEXT = "https://probos.dev/ns/identity/v1"
DID_METHOD = "probos"


def generate_did(instance_id: str, agent_uuid: str) -> str:
    """Generate a W3C DID for a ProbOS agent.

    Format: did:probos:{instance_id}:{agent_uuid}
    Globally unique across all ProbOS instances in the Nooplex.
    """
    return f"did:{DID_METHOD}:{instance_id}:{agent_uuid}"


def generate_ship_did(instance_id: str) -> str:
    """Generate a W3C DID for a ProbOS instance (the ship itself).

    Format: did:probos:{instance_id}
    The ship is the root of trust — its DID has no agent suffix.
    Reset = new instance_id = new ship DID = new timeline.
    """
    return f"did:{DID_METHOD}:{instance_id}"


def generate_agent_uuid() -> str:
    """Generate a new UUID v4 for an agent. Called once at birth, never again."""
    return str(uuid.uuid4())


def parse_did(did: str) -> dict[str, str] | None:
    """Parse a did:probos DID into its components.

    Ship DID (3 parts): did:probos:{instance_id}
      Returns {"method": "probos", "instance_id": ..., "type": "ship"}

    Agent DID (4 parts): did:probos:{instance_id}:{agent_uuid}
      Returns {"method": "probos", "instance_id": ..., "agent_uuid": ..., "type": "agent"}

    Returns None if the DID is not a valid did:probos identifier.
    """
    parts = did.split(":")
    if len(parts) < 3 or parts[0] != "did" or parts[1] != DID_METHOD:
        return None
    if len(parts) == 3:
        return {
            "method": parts[1],
            "instance_id": parts[2],
            "type": "ship",
        }
    if len(parts) == 4:
        return {
            "method": parts[1],
            "instance_id": parts[2],
            "agent_uuid": parts[3],
            "type": "agent",
        }
    return None


@dataclass
class AgentBirthCertificate:
    """W3C Verifiable Credential — Agent Birth Certificate.

    Immutable once issued. Records the agent's origin: who they are,
    when and where they were born, and what baseline they started from.
    """
    # Identity
    agent_uuid: str          # UUID v4 — the permanent sovereign ID
    did: str                 # did:probos:{instance_id}:{agent_uuid}
    agent_type: str          # e.g., "counselor"
    callsign: str            # e.g., "Troi" — assigned at birth or self-chosen

    # Origin
    instance_id: str         # Ship's instance UUID
    vessel_name: str         # e.g., "USS Enterprise"
    birth_timestamp: float   # time.time() at creation
    department: str          # Department at birth
    post_id: str             # Ontology post at birth

    # Baseline
    baseline_version: str    # Git tag or commit hash of agent code at birth

    # Proof
    certificate_hash: str = ""  # SHA-256 of all fields above — computed at issuance

    def compute_hash(self) -> str:
        """Compute the SHA-256 hash of this certificate's content fields."""
        content = {
            "agent_uuid": self.agent_uuid,
            "did": self.did,
            "agent_type": self.agent_type,
            "callsign": self.callsign,
            "instance_id": self.instance_id,
            "vessel_name": self.vessel_name,
            "birth_timestamp": self.birth_timestamp,
            "department": self.department,
            "post_id": self.post_id,
            "baseline_version": self.baseline_version,
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_verifiable_credential(self) -> dict[str, Any]:
        """Serialize as a W3C Verifiable Credential JSON structure."""
        from datetime import datetime, timezone
        return {
            "@context": [VC_CONTEXT, PROBOS_CONTEXT],
            "type": ["VerifiableCredential", "AgentBirthCertificate"],
            "issuer": f"did:{DID_METHOD}:{self.instance_id}:ship",
            "validFrom": datetime.fromtimestamp(
                self.birth_timestamp, tz=timezone.utc
            ).isoformat(),
            "credentialSubject": {
                "id": self.did,
                "agentType": self.agent_type,
                "callsign": self.callsign,
                "department": self.department,
                "postId": self.post_id,
                "baselineVersion": self.baseline_version,
                "birthVessel": {
                    "instanceId": self.instance_id,
                    "name": self.vessel_name,
                },
            },
            "proof": {
                "type": "Sha256Hash2024",
                "created": datetime.fromtimestamp(
                    self.birth_timestamp, tz=timezone.utc
                ).isoformat(),
                "verificationMethod": f"did:{DID_METHOD}:{self.instance_id}:ship#key-1",
                "proofValue": self.certificate_hash,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentBirthCertificate:
        """Reconstruct from a dict (e.g., loaded from DB)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class LedgerBlock:
    """A single block in the Identity Ledger hash-chain."""
    index: int
    timestamp: float
    certificate_hash: str    # Hash of the birth certificate in this block
    agent_did: str           # DID of the agent (or "ship" for genesis)
    previous_hash: str       # Hash of the previous block
    block_hash: str = ""     # SHA-256(index + timestamp + cert_hash + agent_did + previous_hash)

    def compute_hash(self) -> str:
        """Compute this block's hash from its contents."""
        content = f"{self.index}:{self.timestamp}:{self.certificate_hash}:{self.agent_did}:{self.previous_hash}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


_IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS birth_certificates (
    agent_uuid TEXT PRIMARY KEY,
    did TEXT UNIQUE NOT NULL,
    agent_type TEXT NOT NULL,
    callsign TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    vessel_name TEXT NOT NULL,
    birth_timestamp REAL NOT NULL,
    department TEXT NOT NULL,
    post_id TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    certificate_hash TEXT NOT NULL,
    certificate_vc_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_ledger (
    block_index INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    certificate_hash TEXT NOT NULL,
    agent_did TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    block_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slot_mappings (
    slot_id TEXT PRIMARY KEY,
    agent_uuid TEXT NOT NULL,
    FOREIGN KEY (agent_uuid) REFERENCES birth_certificates(agent_uuid)
);

CREATE INDEX IF NOT EXISTS idx_cert_agent_type ON birth_certificates(agent_type);
CREATE INDEX IF NOT EXISTS idx_cert_did ON birth_certificates(did);
CREATE INDEX IF NOT EXISTS idx_ledger_did ON identity_ledger(agent_did);
"""


class AgentIdentityRegistry:
    """Persistent registry of agent identities with append-only ledger.

    Ship's Computer infrastructure service. Manages the lifecycle of
    agent identities: generation, storage, retrieval, and verification.
    The Identity Ledger provides a tamper-evident, federation-syncable
    record of all agent births on this ship.

    'ACM is the HR department. The Identity Registry is the vital records office.'
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._db: aiosqlite.Connection | None = None
        self._cache: dict[str, AgentBirthCertificate] = {}  # agent_type -> cert (for crew singletons)
        self._uuid_cache: dict[str, AgentBirthCertificate] = {}  # agent_uuid -> cert
        self._slot_cache: dict[str, AgentBirthCertificate] = {}  # slot_id -> cert

    async def start(self) -> None:
        """Initialize identity database and load existing certificates."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._data_dir / "identity.db"
        self._db = await aiosqlite.connect(str(db_path))
        await self._db.executescript(_IDENTITY_SCHEMA)
        await self._db.commit()

        # Load existing certificates into cache
        async with self._db.execute("SELECT * FROM birth_certificates") as cursor:
            async for row in cursor:
                cert = AgentBirthCertificate(
                    agent_uuid=row[0], did=row[1], agent_type=row[2],
                    callsign=row[3], instance_id=row[4], vessel_name=row[5],
                    birth_timestamp=row[6], department=row[7], post_id=row[8],
                    baseline_version=row[9], certificate_hash=row[10],
                )
                self._uuid_cache[cert.agent_uuid] = cert

        # Load slot mappings
        async with self._db.execute(
            "SELECT slot_id, agent_uuid FROM slot_mappings"
        ) as cursor:
            async for row in cursor:
                cert = self._uuid_cache.get(row[1])
                if cert:
                    self._slot_cache[row[0]] = cert

        logger.info("Identity registry loaded %d certificates", len(self._uuid_cache))

    async def stop(self) -> None:
        """Close identity database."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── Lookup ──────────────────────────────────────────────────────

    def get_by_uuid(self, agent_uuid: str) -> AgentBirthCertificate | None:
        """Look up a birth certificate by agent UUID."""
        return self._uuid_cache.get(agent_uuid)

    def get_by_slot(self, slot_id: str) -> AgentBirthCertificate | None:
        """Look up a birth certificate by deployment slot ID.

        The slot_id is the deterministic ID from substrate/identity.py
        (e.g., 'counselor_counselor_0_67c601cb'). We store the mapping
        slot_id -> agent_uuid so agents get the same identity across restarts.
        """
        return self._slot_cache.get(slot_id)

    def get_all(self) -> list[AgentBirthCertificate]:
        """Return all birth certificates."""
        return list(self._uuid_cache.values())

    def get_by_agent_type(self, agent_type: str) -> list[AgentBirthCertificate]:
        """Return all certificates for a given agent_type."""
        return [c for c in self._uuid_cache.values() if c.agent_type == agent_type]

    # ── Issuance ────────────────────────────────────────────────────

    async def issue_birth_certificate(
        self,
        agent_type: str,
        callsign: str,
        instance_id: str,
        vessel_name: str,
        department: str,
        post_id: str,
        baseline_version: str,
        slot_id: str = "",
    ) -> AgentBirthCertificate:
        """Issue a new birth certificate and record it on the Identity Ledger.

        Called by ACM during agent onboarding. This is the moment of birth —
        the agent receives its permanent identity.
        """
        if not self._db:
            raise RuntimeError("Identity registry not started")

        # Generate sovereign identity
        agent_uuid = generate_agent_uuid()
        did = generate_did(instance_id, agent_uuid)
        now = time.time()

        # Create certificate
        cert = AgentBirthCertificate(
            agent_uuid=agent_uuid,
            did=did,
            agent_type=agent_type,
            callsign=callsign,
            instance_id=instance_id,
            vessel_name=vessel_name,
            birth_timestamp=now,
            department=department,
            post_id=post_id,
            baseline_version=baseline_version,
        )

        # Compute proof hash
        cert.certificate_hash = cert.compute_hash()

        # Persist certificate
        vc_json = json.dumps(cert.to_verifiable_credential(), sort_keys=True)
        await self._db.execute(
            "INSERT INTO birth_certificates "
            "(agent_uuid, did, agent_type, callsign, instance_id, vessel_name, "
            "birth_timestamp, department, post_id, baseline_version, "
            "certificate_hash, certificate_vc_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cert.agent_uuid, cert.did, cert.agent_type, cert.callsign,
             cert.instance_id, cert.vessel_name, cert.birth_timestamp,
             cert.department, cert.post_id, cert.baseline_version,
             cert.certificate_hash, vc_json),
        )

        # Map slot_id -> agent_uuid for restart persistence
        if slot_id:
            await self._db.execute(
                "INSERT OR REPLACE INTO slot_mappings (slot_id, agent_uuid) VALUES (?, ?)",
                (slot_id, agent_uuid),
            )

        # Append to Identity Ledger (blockchain)
        await self._append_to_ledger(cert.certificate_hash, cert.did)

        await self._db.commit()

        # Update caches
        self._uuid_cache[cert.agent_uuid] = cert
        if slot_id:
            self._slot_cache[slot_id] = cert

        logger.info(
            "Birth certificate issued: %s (%s) — DID %s",
            cert.callsign, cert.agent_type, cert.did,
        )
        return cert

    async def resolve_or_issue(
        self,
        slot_id: str,
        agent_type: str,
        callsign: str,
        instance_id: str,
        vessel_name: str,
        department: str,
        post_id: str,
        baseline_version: str,
    ) -> AgentBirthCertificate:
        """Resolve an existing identity for this slot, or issue a new one.

        This is the primary entry point during boot. For a given deployment
        slot (deterministic ID), either return the existing persistent identity
        or create a new one if this is the agent's first instantiation.
        """
        # Check if this slot already has a persistent identity
        existing = self.get_by_slot(slot_id)
        if existing:
            return existing

        # First birth — issue new certificate
        return await self.issue_birth_certificate(
            agent_type=agent_type,
            callsign=callsign,
            instance_id=instance_id,
            vessel_name=vessel_name,
            department=department,
            post_id=post_id,
            baseline_version=baseline_version,
            slot_id=slot_id,
        )

    # ── Identity Ledger (Blockchain) ────────────────────────────────

    async def _append_to_ledger(self, certificate_hash: str, agent_did: str) -> LedgerBlock:
        """Append a new block to the Identity Ledger hash-chain."""
        if not self._db:
            raise RuntimeError("Identity registry not started")

        # Get the previous block
        async with self._db.execute(
            "SELECT block_index, block_hash FROM identity_ledger "
            "ORDER BY block_index DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            prev_index = row[0]
            prev_hash = row[1]
        else:
            # Genesis block needed — create it first
            genesis = await self._create_genesis_block()
            prev_index = genesis.index
            prev_hash = genesis.block_hash

        # Create new block
        block = LedgerBlock(
            index=prev_index + 1,
            timestamp=time.time(),
            certificate_hash=certificate_hash,
            agent_did=agent_did,
            previous_hash=prev_hash,
        )
        block.block_hash = block.compute_hash()

        await self._db.execute(
            "INSERT INTO identity_ledger "
            "(block_index, timestamp, certificate_hash, agent_did, previous_hash, block_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (block.index, block.timestamp, block.certificate_hash,
             block.agent_did, block.previous_hash, block.block_hash),
        )

        return block

    async def _create_genesis_block(self) -> LedgerBlock:
        """Create the genesis block — the ship's own birth on the ledger."""
        if not self._db:
            raise RuntimeError("Identity registry not started")

        # Genesis block: index 0, no previous hash
        genesis = LedgerBlock(
            index=0,
            timestamp=time.time(),
            certificate_hash="genesis",
            agent_did="ship",
            previous_hash="0" * 64,  # 64 zero chars — no predecessor
        )
        genesis.block_hash = genesis.compute_hash()

        await self._db.execute(
            "INSERT OR IGNORE INTO identity_ledger "
            "(block_index, timestamp, certificate_hash, agent_did, previous_hash, block_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (genesis.index, genesis.timestamp, genesis.certificate_hash,
             genesis.agent_did, genesis.previous_hash, genesis.block_hash),
        )

        return genesis

    async def verify_chain(self) -> tuple[bool, str]:
        """Verify the integrity of the entire Identity Ledger.

        Recomputes every block hash from genesis to tip. If any block's
        stored hash doesn't match its computed hash, or if the previous_hash
        linkage is broken, the chain is invalid.

        Returns:
            (valid: bool, message: str)
        """
        if not self._db:
            return False, "Registry not started"

        async with self._db.execute(
            "SELECT block_index, timestamp, certificate_hash, agent_did, "
            "previous_hash, block_hash FROM identity_ledger ORDER BY block_index ASC"
        ) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return True, "Empty ledger"

        for i, row in enumerate(rows):
            block = LedgerBlock(
                index=row[0], timestamp=row[1], certificate_hash=row[2],
                agent_did=row[3], previous_hash=row[4], block_hash=row[5],
            )

            # Verify hash
            expected_hash = block.compute_hash()
            if block.block_hash != expected_hash:
                return False, f"Block {block.index}: hash mismatch"

            # Verify chain linkage (skip genesis)
            if i > 0:
                prev_block_hash = rows[i - 1][5]
                if block.previous_hash != prev_block_hash:
                    return False, f"Block {block.index}: chain linkage broken"

        return True, f"Chain valid: {len(rows)} blocks"

    async def export_chain(self) -> list[dict[str, Any]]:
        """Export the full ledger for federation sync.

        Returns the complete chain as a list of dicts, each containing
        the block data and the associated birth certificate VC.
        """
        if not self._db:
            return []

        blocks: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT l.block_index, l.timestamp, l.certificate_hash, l.agent_did, "
            "l.previous_hash, l.block_hash, c.certificate_vc_json "
            "FROM identity_ledger l "
            "LEFT JOIN birth_certificates c ON l.agent_did = c.did "
            "ORDER BY l.block_index ASC"
        ) as cursor:
            async for row in cursor:
                blocks.append({
                    "index": row[0],
                    "timestamp": row[1],
                    "certificate_hash": row[2],
                    "agent_did": row[3],
                    "previous_hash": row[4],
                    "block_hash": row[5],
                    "credential": json.loads(row[6]) if row[6] else None,
                })

        return blocks
