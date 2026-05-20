"""AD-441: Sovereign Agent Identity — DIDs, Birth Certificates, Identity Ledger.

Implements W3C Decentralized Identifiers (DIDs) and Verifiable Credentials (VCs)
for persistent, globally unique, cryptographically verifiable agent identity.

DID Method: did:probos:{instance_id}:{agent_uuid}
Birth Certificate: W3C VC with AgentBirthCertificate type
Identity Ledger: Append-only hash-chain (blockchain) of birth certificates

Proof Type: Uses 'Sha256Hash2024' — a content integrity hash, not a
cryptographic signature. This is intentional: ProbOS identity is self-sovereign
within the instance, not designed for external VC verifier interop (yet).
The hash proves immutability, not third-party authenticity.
Future: Replace with Ed25519Signature2020 when federation requires it.

'Every agent is born once. Their identity is permanent. Their record is immutable.'
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


import hashlib
from probos.captain_card.card import CaptainCard


logger = logging.getLogger(__name__)


# --- AD-757 Voice & Avatar Continuity Hooks ---
class VoiceProfileManager:
    async def set_voice_profile(self, captain_id: str, voice: str) -> None:
        """Store voice preference (e.g. 'Ezri', 'Ship\'s Computer')."""
        # Placeholder: In real implementation, persist to CaptainCard or DB
        logger.info(f"Set voice profile for {captain_id}: {voice}")

    async def get_voice_profile(self, captain_id: str) -> str | None:
        """Retrieve voice for TTS rendering."""
        # Placeholder: In real implementation, fetch from CaptainCard or DB
        logger.info(f"Get voice profile for {captain_id}")
        return None


class AvatarProfileManager:
    async def set_avatar_theme(self, captain_id: str, theme: str) -> None:
        """Store avatar visual theme (color, style, etc.)."""
        # Placeholder: In real implementation, persist to CaptainCard or DB
        logger.info(f"Set avatar theme for {captain_id}: {theme}")

    async def get_avatar_theme(self, captain_id: str) -> dict[str, object]:
        """Retrieve avatar config for UI rendering."""
        # Placeholder: In real implementation, fetch from CaptainCard or DB
        logger.info(f"Get avatar theme for {captain_id}")
        return {"theme": "default"}


# --- AD-757 Continuity Checksum & Anomaly Detection Hook ---
class ContinuityValidator:
    def compute_checksum(self, card_dict: dict[str, Any]) -> str:
        card_json = str(sorted(card_dict.items())).encode("utf-8")
        return hashlib.sha256(card_json).hexdigest()

    def validate(self, card_dict: dict[str, Any], checksum: str) -> bool:
        return self.compute_checksum(card_dict) == checksum

# W3C VC context — included for forward compatibility with VC ecosystem
VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
PROBOS_CONTEXT = "https://probos.dev/ns/identity/v1"
DID_METHOD = "probos"


def generate_did(instance_id: str, agent_uuid: str) -> str:
    """Generate a W3C DID for a ProbOS agent.

    Format: did:probos:{instance_id}:{agent_uuid}
    Globally unique across all ProbOS instances in the Nooplex.
    """
    if not instance_id or not agent_uuid:
        raise ValueError(f"DID generation requires non-empty instance_id and agent_uuid, got '{instance_id}', '{agent_uuid}'")
    return f"did:{DID_METHOD}:{instance_id}:{agent_uuid}"


def generate_ship_did(instance_id: str) -> str:
    """Generate a W3C DID for a ProbOS instance (the ship itself).

    Format: did:probos:{instance_id}
    The ship is the root of trust — its DID has no agent suffix.
    Reset = new instance_id = new ship DID = new timeline.
    """
    if not instance_id:
        raise ValueError("Ship DID generation requires non-empty instance_id")
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
    if not did or not isinstance(did, str):
        return None
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
        """Compute the SHA-256 hash of this certificate's content fields.

        Note: birth_timestamp is a float. Python's json.dumps uses repr-style
        float formatting which is consistent within a CPython major version.
        For cross-platform federation hash verification, timestamps may need
        to be normalized to fixed-precision strings in a future version.
        """
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
            "issuer": generate_ship_did(self.instance_id),
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
                "verificationMethod": f"{generate_ship_did(self.instance_id)}#key-1",
                "proofValue": self.certificate_hash,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentBirthCertificate:
        """Reconstruct from a dict (e.g., loaded from DB)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ShipBirthCertificate:
    """W3C Verifiable Credential — Ship Birth Certificate.

    Issued once at commissioning. The ship's own identity document.
    Self-signed: the ship is its own root of trust.
    Reset = new instance_id = new ship = new certificate.
    """
    # Identity
    ship_did: str              # did:probos:{instance_id}
    instance_id: str           # UUID — the ship's permanent ID for this timeline
    vessel_name: str           # e.g., "ProbOS"

    # Commissioning
    commissioned_at: float     # time.time() — the ship's birthday
    version: str               # Software version at commissioning

    # Proof
    certificate_hash: str = "" # SHA-256 of content fields

    def compute_hash(self) -> str:
        """Compute the SHA-256 hash of this certificate's content fields."""
        content = {
            "ship_did": self.ship_did,
            "instance_id": self.instance_id,
            "vessel_name": self.vessel_name,
            "commissioned_at": self.commissioned_at,
            "version": self.version,
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_verifiable_credential(self) -> dict[str, Any]:
        """Serialize as a W3C Verifiable Credential JSON structure."""
        from datetime import datetime, timezone
        return {
            "@context": [VC_CONTEXT, PROBOS_CONTEXT],
            "type": ["VerifiableCredential", "ShipBirthCertificate"],
            "issuer": self.ship_did,  # Self-signed — ship is its own root of trust
            "validFrom": datetime.fromtimestamp(
                self.commissioned_at, tz=timezone.utc
            ).isoformat(),
            "credentialSubject": {
                "id": self.ship_did,
                "vesselName": self.vessel_name,
                "version": self.version,
            },
            "proof": {
                "type": "Sha256Hash2024",
                "created": datetime.fromtimestamp(
                    self.commissioned_at, tz=timezone.utc
                ).isoformat(),
                "verificationMethod": f"{self.ship_did}#key-1",
                "proofValue": self.certificate_hash,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShipBirthCertificate:
        """Reconstruct from a dict (e.g., loaded from DB)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AssetTag:
    """Lightweight identity for infrastructure and utility agents.

    Like a serial number on equipment — tracks the asset for inventory
    and management, but does not confer sovereign identity.
    Not recorded on the Identity Ledger. No W3C VC ceremony.

    'A microwave with a name tag isn't a person. But it still has a serial number.'
    """
    asset_uuid: str          # UUID v4 — permanent tracking ID
    asset_type: str          # e.g., "file_reader", "shell_command"
    slot_id: str             # Deterministic deployment slot
    installed_at: float      # time.time() at first instantiation
    pool_name: str           # Pool this asset belongs to
    tier: str                # "infrastructure" or "utility"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/logging."""
        return {
            "asset_uuid": self.asset_uuid,
            "asset_type": self.asset_type,
            "slot_id": self.slot_id,
            "installed_at": self.installed_at,
            "pool_name": self.pool_name,
            "tier": self.tier,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetTag:
        """Reconstruct from a dict."""
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
        """Compute this block's hash from its contents.

        Uses colon-delimited string format (vs JSON for certificates).
        Both are deterministic within a Python version. The simpler format
        is intentional — block hashes are internal chain integrity checks,
        not externally verifiable credentials.
        """
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

CREATE TABLE IF NOT EXISTS ship_birth_certificate (
    ship_did TEXT PRIMARY KEY,
    instance_id TEXT UNIQUE NOT NULL,
    vessel_name TEXT NOT NULL,
    commissioned_at REAL NOT NULL,
    version TEXT NOT NULL,
    certificate_hash TEXT NOT NULL,
    certificate_vc_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS slot_mappings (
    slot_id TEXT PRIMARY KEY,
    agent_uuid TEXT NOT NULL
    -- AD-443d: FOREIGN KEY removed so foreign agent_uuids (held in
    -- foreign_birth_certificates) can be assigned to a slot via reassign_slot.
);

CREATE TABLE IF NOT EXISTS asset_tags (
    asset_uuid TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    slot_id TEXT UNIQUE NOT NULL,
    installed_at REAL NOT NULL,
    pool_name TEXT NOT NULL,
    tier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS foreign_birth_certificates (
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
    certificate_vc_json TEXT NOT NULL,
    origin_ship_did TEXT NOT NULL,
    imported_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS foreign_chains (
    origin_ship_did TEXT PRIMARY KEY,
    chain_json TEXT NOT NULL,
    imported_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS transfer_certificates (
    did TEXT NOT NULL,
    transfer_timestamp REAL NOT NULL,
    direction TEXT NOT NULL,
    certificate_hash TEXT UNIQUE NOT NULL,
    certificate_vc_json TEXT NOT NULL,
    PRIMARY KEY (did, transfer_timestamp, direction)
);

CREATE INDEX IF NOT EXISTS idx_cert_agent_type ON birth_certificates(agent_type);
CREATE INDEX IF NOT EXISTS idx_cert_did ON birth_certificates(did);
CREATE INDEX IF NOT EXISTS idx_ledger_did ON identity_ledger(agent_did);
CREATE INDEX IF NOT EXISTS idx_asset_type ON asset_tags(asset_type);
CREATE INDEX IF NOT EXISTS idx_asset_slot ON asset_tags(slot_id);
CREATE INDEX IF NOT EXISTS idx_slot_agent ON slot_mappings(agent_uuid);
CREATE INDEX IF NOT EXISTS idx_foreign_did ON foreign_birth_certificates(did);
CREATE INDEX IF NOT EXISTS idx_foreign_origin ON foreign_birth_certificates(origin_ship_did);
CREATE INDEX IF NOT EXISTS idx_xfer_did ON transfer_certificates(did);
"""


class AgentIdentityRegistry:
    """Persistent registry of agent identities with append-only ledger.

    Ship's Computer infrastructure service. Manages the lifecycle of
    agent identities: generation, storage, retrieval, and verification.
    The Identity Ledger provides a tamper-evident, federation-syncable
    record of all agent births on this ship.

    'ACM is the HR department. The Identity Registry is the vital records office.'
    """

    def __init__(self, data_dir: Path, connection_factory: ConnectionFactory | None = None) -> None:
        self._data_dir = data_dir
        self._db: DatabaseConnection | None = None
        self._uuid_cache: dict[str, AgentBirthCertificate] = {}  # agent_uuid -> cert
        self._slot_cache: dict[str, AgentBirthCertificate] = {}  # slot_id -> cert
        self._ship_certificate: ShipBirthCertificate | None = None
        self._asset_cache: dict[str, AssetTag] = {}  # slot_id -> AssetTag
        # AD-443: Foreign certificates and chain snapshots imported from peer ships.
        self._foreign_uuid_cache: dict[str, AgentBirthCertificate] = {}  # foreign agent_uuid -> cert
        self._foreign_chain_cache: dict[str, list[dict[str, Any]]] = {}  # origin_ship_did -> chain blocks
        self._ledger_lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self, instance_id: str = "", vessel_name: str = "ProbOS", version: str = "") -> None:
        """Initialize identity database and load existing certificates.

        If instance_id is provided, also loads or creates the ship's birth
        certificate. Can be called with instance_id later via commission_ship()
        if the instance_id isn't available at first boot.
        """
        if not self._db:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            db_path = self._data_dir / "identity.db"
            self._db = await self._connection_factory.connect(str(db_path))
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.executescript(_IDENTITY_SCHEMA)
            await self._db.commit()

            # Load existing certificates into cache
            # Column order: agent_uuid(0), did(1), agent_type(2), callsign(3),
            # instance_id(4), vessel_name(5), birth_timestamp(6), department(7),
            # post_id(8), baseline_version(9), certificate_hash(10), certificate_vc_json(11)
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

            # Load existing asset tags
            async with self._db.execute(
                "SELECT asset_uuid, asset_type, slot_id, installed_at, pool_name, tier "
                "FROM asset_tags"
            ) as cursor:
                async for row in cursor:
                    tag = AssetTag(
                        asset_uuid=row[0], asset_type=row[1], slot_id=row[2],
                        installed_at=row[3], pool_name=row[4], tier=row[5],
                    )
                    self._asset_cache[tag.slot_id] = tag

            # AD-443b: Load foreign birth certificates imported from peer ships.
            async with self._db.execute(
                "SELECT agent_uuid, did, agent_type, callsign, instance_id, "
                "vessel_name, birth_timestamp, department, post_id, "
                "baseline_version, certificate_hash FROM foreign_birth_certificates"
            ) as cursor:
                async for row in cursor:
                    fcert = AgentBirthCertificate(
                        agent_uuid=row[0], did=row[1], agent_type=row[2],
                        callsign=row[3], instance_id=row[4], vessel_name=row[5],
                        birth_timestamp=row[6], department=row[7], post_id=row[8],
                        baseline_version=row[9], certificate_hash=row[10],
                    )
                    self._foreign_uuid_cache[fcert.agent_uuid] = fcert

            # AD-443d: Load slot mappings that point at foreign certs.
            async with self._db.execute(
                "SELECT slot_id, agent_uuid FROM slot_mappings"
            ) as cursor:
                async for row in cursor:
                    if row[1] in self._foreign_uuid_cache and row[0] not in self._slot_cache:
                        self._slot_cache[row[0]] = self._foreign_uuid_cache[row[1]]

            # AD-443b: Load foreign-chain snapshots.
            async with self._db.execute(
                "SELECT origin_ship_did, chain_json FROM foreign_chains"
            ) as cursor:
                async for row in cursor:
                    self._foreign_chain_cache[row[0]] = json.loads(row[1])

            logger.info(
                "Identity registry loaded %d certificates, %d asset tags, "
                "%d foreign certificates, %d foreign chain snapshots",
                len(self._uuid_cache), len(self._asset_cache),
                len(self._foreign_uuid_cache), len(self._foreign_chain_cache),
            )

        # Load or create ship birth certificate (if instance_id provided)
        if instance_id and not self._ship_certificate:
            self._ship_certificate = await self._load_or_commission_ship(
                instance_id, vessel_name, version
            )

    async def stop(self) -> None:
        """Close identity database."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _load_or_commission_ship(
        self, instance_id: str, vessel_name: str, version: str
    ) -> ShipBirthCertificate | None:
        """Load existing ship certificate or commission a new ship.

        First boot: creates the ShipBirthCertificate and writes genesis block.
        Subsequent boots: loads the existing certificate from DB.
        """
        if not self._db or not instance_id:
            return None

        # Check for existing ship certificate
        # Column order: ship_did(0), instance_id(1), vessel_name(2),
        # commissioned_at(3), version(4), certificate_hash(5)
        async with self._db.execute(
            "SELECT ship_did, instance_id, vessel_name, commissioned_at, "
            "version, certificate_hash FROM ship_birth_certificate LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            cert = ShipBirthCertificate(
                ship_did=row[0], instance_id=row[1], vessel_name=row[2],
                commissioned_at=row[3], version=row[4], certificate_hash=row[5],
            )
            logger.info("Ship certificate loaded: %s (commissioned %.0f)", cert.ship_did, cert.commissioned_at)
            return cert

        # First boot — commission the ship
        return await self._commission_ship(instance_id, vessel_name, version)

    async def _commission_ship(
        self, instance_id: str, vessel_name: str, version: str
    ) -> ShipBirthCertificate:
        """Commission a new ship — create ShipBirthCertificate and genesis block.

        This is the founding act of a ProbOS timeline. The ship receives its DID,
        its birth certificate is the first credential, and the genesis block
        carries the ship's certificate hash as proof of origin.

        'Every ship is born once. Every timeline begins with a commissioning.'
        """
        if not self._db:
            raise RuntimeError("Identity registry not started")

        ship_did = generate_ship_did(instance_id)
        now = time.time()

        cert = ShipBirthCertificate(
            ship_did=ship_did,
            instance_id=instance_id,
            vessel_name=vessel_name,
            commissioned_at=now,
            version=version,
        )
        cert.certificate_hash = cert.compute_hash()

        # Persist ship certificate
        vc_json = json.dumps(cert.to_verifiable_credential(), sort_keys=True)
        await self._db.execute(
            "INSERT INTO ship_birth_certificate "
            "(ship_did, instance_id, vessel_name, commissioned_at, version, "
            "certificate_hash, certificate_vc_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cert.ship_did, cert.instance_id, cert.vessel_name,
             cert.commissioned_at, cert.version, cert.certificate_hash, vc_json),
        )

        # Create genesis block immediately — the ship's birth is block 0
        self._ship_certificate = cert  # Set before genesis so it uses real ship data
        await self._create_genesis_block()

        await self._db.commit()

        logger.info(
            "SHIP COMMISSIONED: %s — DID %s — Timeline begins",
            vessel_name, ship_did,
        )
        return cert

    def get_ship_certificate(self) -> ShipBirthCertificate | None:
        """Return the ship's birth certificate, if commissioned."""
        return self._ship_certificate

    # ── Lookup ──────────────────────────────────────────────────────

    def get_by_uuid(self, agent_uuid: str) -> AgentBirthCertificate | None:
        """Look up a birth certificate by agent UUID.

        AD-443d: After a transfer, foreign certs accepted via
        `import_transfer_certificate` are returned alongside native ones —
        callers do not need to know whether an agent was born here or arrived
        via mobility. Native certs win on UUID collision (defensive — DIDs
        prevent collision in practice).
        """
        cert = self._uuid_cache.get(agent_uuid)
        if cert is not None:
            return cert
        return self._foreign_uuid_cache.get(agent_uuid)

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

    # ── Asset Tags ─────────────────────────────────────────────────

    async def issue_asset_tag(
        self,
        asset_type: str,
        slot_id: str,
        pool_name: str,
        tier: str = "infrastructure",
    ) -> AssetTag:
        """Issue an asset tag for an infrastructure or utility agent.

        No Identity Ledger entry. No W3C VC. Just inventory tracking.
        """
        if not self._db:
            raise RuntimeError("Identity registry not started")

        tag = AssetTag(
            asset_uuid=generate_agent_uuid(),
            asset_type=asset_type,
            slot_id=slot_id,
            installed_at=time.time(),
            pool_name=pool_name,
            tier=tier,
        )

        await self._db.execute(
            "INSERT INTO asset_tags "
            "(asset_uuid, asset_type, slot_id, installed_at, pool_name, tier) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tag.asset_uuid, tag.asset_type, tag.slot_id,
             tag.installed_at, tag.pool_name, tag.tier),
        )
        await self._db.commit()
        self._asset_cache[tag.slot_id] = tag

        logger.info("Asset tag issued: %s (%s) — %s", tag.asset_type, tag.tier, tag.asset_uuid)
        return tag

    async def resolve_or_issue_asset_tag(
        self,
        slot_id: str,
        asset_type: str,
        pool_name: str,
        tier: str = "infrastructure",
    ) -> AssetTag:
        """Resolve an existing asset tag for this slot, or issue a new one."""
        existing = self._asset_cache.get(slot_id)
        if existing:
            return existing
        return await self.issue_asset_tag(asset_type, slot_id, pool_name, tier)

    def get_asset_tags(self) -> list[AssetTag]:
        """Return all asset tags."""
        return list(self._asset_cache.values())

    def get_asset_by_slot(self, slot_id: str) -> AssetTag | None:
        """Look up an asset tag by deployment slot ID."""
        return self._asset_cache.get(slot_id)

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

        # Input validation — catch misuse before corrupting the ledger
        if not agent_type:
            raise ValueError("agent_type is required for birth certificate issuance")
        if not instance_id:
            raise ValueError("instance_id is required — ship must be commissioned before issuing birth certificates")
        if not callsign:
            raise ValueError("callsign is required for birth certificate issuance")

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
            # Check for existing mapping — warn if overwriting
            existing = self._slot_cache.get(slot_id)
            if existing:
                logger.warning(
                    "Slot %s already mapped to agent %s — overwriting with %s",
                    slot_id, existing.agent_uuid, agent_uuid,
                )
            await self._db.execute(
                "INSERT OR REPLACE INTO slot_mappings (slot_id, agent_uuid) VALUES (?, ?)",
                (slot_id, agent_uuid),
            )

        # Append to Identity Ledger (blockchain) — serialized to prevent index conflicts
        async with self._ledger_lock:
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
        # Column order: block_index(0), block_hash(1)
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
        """Create the genesis block — the ship's commissioning on the ledger.

        If a ShipBirthCertificate exists, the genesis block carries its hash
        and the ship's DID. Otherwise falls back to placeholder values for
        backwards compatibility with pre-commissioning databases.
        """
        if not self._db:
            raise RuntimeError("Identity registry not started")

        # Use real ship identity if available
        if self._ship_certificate:
            cert_hash = self._ship_certificate.certificate_hash
            agent_did = self._ship_certificate.ship_did
        else:
            cert_hash = "genesis"
            agent_did = "ship"

        genesis = LedgerBlock(
            index=0,
            timestamp=self._ship_certificate.commissioned_at if self._ship_certificate else time.time(),
            certificate_hash=cert_hash,
            agent_did=agent_did,
            previous_hash="0" * 64,
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

            # Verify genesis block has expected previous_hash
            if i == 0:
                expected_prev = "0" * 64
                if block.previous_hash != expected_prev:
                    return False, f"Genesis block: invalid previous_hash (expected all zeros)"

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

        # Attach ship certificate to genesis block if available
        # The LEFT JOIN on birth_certificates won't find the ship cert (different table)
        # so we attach it explicitly when it exists
        if blocks and self._ship_certificate and not blocks[0].get("credential"):
            blocks[0]["credential"] = self._ship_certificate.to_verifiable_credential()

        return blocks

    # ── AD-443: Mobility (Transfer Certificates + Foreign Chains) ─────────

    async def verify_remote_chain(self, blocks: list[dict[str, Any]]) -> tuple[bool, str]:
        """AD-443b: Pure local validation of a foreign Identity Ledger snapshot.

        Mirrors the local `verify_chain()` shape: walks blocks in order,
        recomputes each block_hash, verifies previous_hash linkage, verifies
        genesis previous_hash is all zeros. Does not require a started DB.
        """
        if not blocks:
            return False, "Empty chain"

        for i, b in enumerate(blocks):
            try:
                block = LedgerBlock(
                    index=b["index"],
                    timestamp=b["timestamp"],
                    certificate_hash=b["certificate_hash"],
                    agent_did=b["agent_did"],
                    previous_hash=b["previous_hash"],
                    block_hash=b["block_hash"],
                )
            except KeyError as exc:
                return False, f"Block {i}: missing field {exc!s}"

            expected_hash = block.compute_hash()
            if block.block_hash != expected_hash:
                return False, f"Block {block.index}: hash mismatch"

            if i == 0:
                if block.previous_hash != "0" * 64:
                    return False, "Genesis block: invalid previous_hash (expected all zeros)"
            else:
                prev_block_hash = blocks[i - 1]["block_hash"]
                if block.previous_hash != prev_block_hash:
                    return False, f"Block {block.index}: chain linkage broken"

        return True, f"Chain valid: {len(blocks)} blocks"

    async def import_chain(self, blocks: list[dict[str, Any]]) -> tuple[bool, str]:
        """AD-443b: Accept a remote ship's exported Identity Ledger and persist it.

        Validates the chain via verify_remote_chain BEFORE persisting; rejects
        on any integrity failure. Latest-wins on repeated import for the same
        origin_ship_did.
        """
        if not self._db:
            return False, "Registry not started"

        valid, message = await self.verify_remote_chain(blocks)
        if not valid:
            logger.warning(
                "Import chain rejected: %s; foreign chain not persisted", message,
            )
            return False, message

        origin_ship_did = blocks[0]["agent_did"]
        await self._db.execute(
            "INSERT OR REPLACE INTO foreign_chains "
            "(origin_ship_did, chain_json, imported_at) VALUES (?, ?, ?)",
            (origin_ship_did, json.dumps(blocks), time.time()),
        )
        await self._db.commit()
        self._foreign_chain_cache[origin_ship_did] = list(blocks)
        logger.info(
            "Foreign chain imported: %d blocks from %s; available for transfer verification",
            len(blocks), origin_ship_did,
        )
        return True, f"Chain imported: {len(blocks)} blocks from {origin_ship_did}"

    async def issue_transfer_certificate(
        self,
        agent_uuid: str,
        target_instance_did: str,
        qualification_credentials: list[str] | None = None,
    ) -> TransferCertificate:
        """AD-443a: Issue a Transfer Certificate at the origin ship.

        Looks up local birth cert by agent_uuid, freezes assignment history,
        constructs and persists a TransferCertificate under direction='outgoing'.
        Rejects foreign UUIDs (re-transfer is a v2 concern).
        """
        if not self._db:
            raise RuntimeError("Registry not started")

        cert = self._uuid_cache.get(agent_uuid)
        if cert is None:
            raise ValueError(
                f"Cannot issue transfer certificate: agent_uuid {agent_uuid} "
                "not found in local birth certificates"
            )

        now = time.time()
        assignment_history = [
            {
                "instance_did": generate_ship_did(cert.instance_id),
                "vessel_name": cert.vessel_name,
                "joined_at": cert.birth_timestamp,
                "departed_at": now,
            }
        ]
        xfer = TransferCertificate(
            did=cert.did,
            agent_uuid=cert.agent_uuid,
            agent_type=cert.agent_type,
            callsign=cert.callsign,
            origin_ship_did=generate_ship_did(cert.instance_id),
            origin_vessel_name=cert.vessel_name,
            origin_instance_id=cert.instance_id,
            origin_birth_timestamp=cert.birth_timestamp,
            transfer_timestamp=now,
            target_instance_did=target_instance_did,
            baseline_version=cert.baseline_version,
            qualification_credentials=list(qualification_credentials or []),
            assignment_history=assignment_history,
        )
        xfer.certificate_hash = xfer.compute_hash()

        await self._db.execute(
            "INSERT INTO transfer_certificates "
            "(did, transfer_timestamp, direction, certificate_hash, certificate_vc_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                xfer.did,
                xfer.transfer_timestamp,
                "outgoing",
                xfer.certificate_hash,
                json.dumps(xfer.to_verifiable_credential()),
            ),
        )
        await self._db.commit()
        logger.info(
            "Transfer certificate issued: %s (%s) -> %s; ready for delivery to destination",
            xfer.callsign, xfer.did, target_instance_did,
        )
        return xfer

    async def import_transfer_certificate(
        self,
        cert: TransferCertificate,
    ) -> tuple[bool, str]:
        """AD-443a + 443b + 443d: Accept an incoming Transfer Certificate.

        Validation chain: cert hash integrity -> origin chain imported ->
        cert claim consistent with chain. On success, persists a foreign
        birth certificate (cache + DB) plus the cert under direction='incoming'.
        Does NOT reassign a slot — caller must call reassign_slot explicitly.
        """
        if not self._db:
            return False, "Registry not started"

        expected_hash = cert.compute_hash()
        if expected_hash != cert.certificate_hash:
            logger.warning(
                "Transfer certificate rejected: hash mismatch on %s; "
                "cert not imported",
                cert.did,
            )
            return False, "Certificate hash mismatch"

        chain = self._foreign_chain_cache.get(cert.origin_ship_did)
        if chain is None:
            logger.warning(
                "Transfer certificate rejected: origin chain %s not imported; "
                "call import_chain first",
                cert.origin_ship_did,
            )
            return False, f"Origin chain {cert.origin_ship_did} not imported"

        # Confirm the cert claims an agent the origin ship's ledger actually issued.
        chain_match = False
        for block in chain:
            credential = block.get("credential")
            if not credential:
                continue
            subject = credential.get("credentialSubject") or {}
            block_did = subject.get("id") or subject.get("did")
            if block_did != cert.did:
                continue
            chain_match = True
            break

        if not chain_match:
            logger.warning(
                "Transfer certificate rejected: cert subject %s not present "
                "in origin chain %s",
                cert.did, cert.origin_ship_did,
            )
            return False, (
                f"Certificate subject {cert.did} not found in origin chain"
            )

        # Build a foreign AgentBirthCertificate from the cert + chain VC.
        # Department / post_id / certificate_hash come from the chain VC subject;
        # cert carries the canonical sovereign fields.
        fcert: AgentBirthCertificate | None = None
        for block in chain:
            credential = block.get("credential")
            if not credential:
                continue
            subject = credential.get("credentialSubject") or {}
            block_did = subject.get("id") or subject.get("did")
            if block_did != cert.did:
                continue
            fcert = AgentBirthCertificate(
                agent_uuid=cert.agent_uuid,
                did=cert.did,
                agent_type=cert.agent_type,
                callsign=cert.callsign,
                instance_id=cert.origin_instance_id,
                vessel_name=cert.origin_vessel_name,
                birth_timestamp=cert.origin_birth_timestamp,
                department=subject.get("department", ""),
                post_id=subject.get("postId", subject.get("post_id", "")),
                baseline_version=cert.baseline_version,
                certificate_hash=block.get("certificate_hash", ""),
            )
            break

        if fcert is None:
            return False, "Failed to reconstruct foreign birth certificate"

        await self._db.execute(
            "INSERT OR REPLACE INTO foreign_birth_certificates "
            "(agent_uuid, did, agent_type, callsign, instance_id, vessel_name, "
            "birth_timestamp, department, post_id, baseline_version, "
            "certificate_hash, certificate_vc_json, origin_ship_did, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fcert.agent_uuid, fcert.did, fcert.agent_type, fcert.callsign,
                fcert.instance_id, fcert.vessel_name, fcert.birth_timestamp,
                fcert.department, fcert.post_id, fcert.baseline_version,
                fcert.certificate_hash,
                json.dumps(cert.to_verifiable_credential()),
                cert.origin_ship_did, time.time(),
            ),
        )
        await self._db.execute(
            "INSERT OR REPLACE INTO transfer_certificates "
            "(did, transfer_timestamp, direction, certificate_hash, certificate_vc_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                cert.did, cert.transfer_timestamp, "incoming",
                cert.certificate_hash,
                json.dumps(cert.to_verifiable_credential()),
            ),
        )
        await self._db.commit()
        self._foreign_uuid_cache[fcert.agent_uuid] = fcert
        logger.info(
            "Transfer certificate imported: %s (%s) from %s; "
            "available via get_by_uuid (caller must reassign_slot)",
            cert.callsign, cert.did, cert.origin_vessel_name,
        )
        return True, f"Certificate imported: {cert.did}"

    async def reassign_slot(
        self,
        agent_uuid: str,
        new_slot_id: str,
    ) -> tuple[bool, str]:
        """AD-443d: Reassign a deployment slot to a foreign or native agent.

        Birth provenance (vessel_name) preserved automatically per AD-499.
        """
        if not self._db:
            return False, "Registry not started"
        if not new_slot_id:
            return False, "new_slot_id must be non-empty"

        cert = self.get_by_uuid(agent_uuid)
        if cert is None:
            return False, f"agent_uuid {agent_uuid} not found"

        prior = self._slot_cache.get(new_slot_id)
        await self._db.execute(
            "INSERT OR REPLACE INTO slot_mappings (slot_id, agent_uuid) VALUES (?, ?)",
            (new_slot_id, agent_uuid),
        )
        await self._db.commit()
        self._slot_cache[new_slot_id] = cert
        logger.info(
            "Slot reassigned: %s -> %s (%s [%s]); prior occupant %s; "
            "birth provenance preserved per AD-499",
            new_slot_id, cert.did, cert.callsign, cert.vessel_name,
            prior.did if prior else "none",
        )
        return True, f"Slot {new_slot_id} reassigned to {cert.did}"

    def get_foreign_chain(self, origin_ship_did: str) -> list[dict[str, Any]] | None:
        """Return the imported chain snapshot for a peer ship, or None."""
        return self._foreign_chain_cache.get(origin_ship_did)

    async def get_transfer_certificates_for(
        self, agent_did: str
    ) -> list[dict[str, Any]]:
        """Return all stored Transfer Certificates (incoming + outgoing) for an agent DID.

        Read-only audit accessor. Returns dict form suitable for HXI rendering.
        """
        if not self._db:
            return []
        out: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT did, transfer_timestamp, direction, certificate_hash, "
            "certificate_vc_json FROM transfer_certificates WHERE did = ? "
            "ORDER BY transfer_timestamp ASC",
            (agent_did,),
        ) as cursor:
            async for row in cursor:
                out.append({
                    "did": row[0],
                    "transfer_timestamp": row[1],
                    "direction": row[2],
                    "certificate_hash": row[3],
                    "credential": json.loads(row[4]),
                })
        return out
