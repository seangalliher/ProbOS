# AD-441: Sovereign Agent Identity

## Overview

Establish persistent, globally unique, cryptographically verifiable agent identity based on W3C Decentralized Identifiers (DIDs) and Verifiable Credentials (VCs). Every agent born in any ProbOS instance receives a permanent identity — a DID, a Birth Certificate, and a tamper-evident ledger entry — issued by ACM and recorded on an append-only Identity Ledger (hash-chain blockchain).

**Prior art absorbed:**
- W3C DIDs v1.0 (https://www.w3.org/TR/did-core/) — self-sovereign decentralized identifiers
- W3C Verifiable Credentials v2.0 (https://www.w3.org/TR/vc-data-model-2.0/) — tamper-evident credentials
- DIF Trusted AI Agents Working Group — emerging standards for AI agent identity
- ArXiv 2025-2026 landscape: LOKA Protocol, Agent-OSI, BlockA2A, Fetch.ai — industry convergence on DIDs + blockchain anchoring

**Key architectural decisions:**
- **Ship DID:** `did:probos:{instance_id}` — the ProbOS instance itself has a sovereign identity. Reset = new instance_id = new ship DID = new timeline.
- **Agent DID:** `did:probos:{instance_id}:{agent_uuid}` — globally unique, namespaced under the ship that birthed the agent.
- Birth Certificate = W3C Verifiable Credential with embedded proof. Ships AND agents both get birth certificates.
- Identity Ledger = append-only hash-chain (blockchain), per-ship, federation-syncable. Genesis block = ship's own birth certificate (not a placeholder).
- ACM is the issuing authority for agents — agents don't manage their own identity. The ship's birth certificate is self-signed (it is the root of trust).
- Internal ID = UUID v4 string (SQLite/ChromaDB key). DID = external representation.
- Deterministic IDs from `substrate/identity.py` become **slot identifiers** (position in the deployment topology), distinct from **sovereign identity** (who the agent IS)
- No migration of existing data — this will be deployed with a clean reset

---

## File 1: `src/probos/identity.py` (NEW)

Create a new module implementing three components: DID utilities, Birth Certificate (VC), and Identity Ledger (blockchain).

### 1A: DID Utilities

```python
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
from dataclasses import asdict, dataclass, field
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
```

### 1B: Birth Certificate (Verifiable Credential)

```python
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
```

### 1C: Identity Ledger (Hash-Chain Blockchain)

```python
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
        # Lookup via auxiliary table (see schema)
        # For now, use in-memory cache built during boot
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

        Args:
            agent_type: The agent's type (e.g., "counselor")
            callsign: The agent's name/callsign (e.g., "Troi")
            instance_id: This ship's instance UUID
            vessel_name: This ship's name (e.g., "USS Enterprise")
            department: Department assignment at birth
            post_id: Ontology post assignment at birth
            baseline_version: Git tag/hash of the agent baseline code
            slot_id: Deterministic slot ID for restart mapping

        Returns:
            The signed AgentBirthCertificate
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

        Args:
            slot_id: Deterministic ID from substrate/identity.py
            Other args: same as issue_birth_certificate

        Returns:
            The agent's birth certificate (existing or newly issued)
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
```

**IMPORTANT**: Add a `slot_mappings` table to the schema:

```sql
CREATE TABLE IF NOT EXISTS slot_mappings (
    slot_id TEXT PRIMARY KEY,
    agent_uuid TEXT NOT NULL,
    FOREIGN KEY (agent_uuid) REFERENCES birth_certificates(agent_uuid)
);
```

And add `self._slot_cache: dict[str, AgentBirthCertificate] = {}` to `__init__`.

During `start()`, also load the slot mappings into `self._slot_cache`:

```python
async with self._db.execute(
    "SELECT slot_id, agent_uuid FROM slot_mappings"
) as cursor:
    async for row in cursor:
        cert = self._uuid_cache.get(row[1])
        if cert:
            self._slot_cache[row[0]] = cert
```

---

## File 2: `src/probos/runtime.py` (MODIFY)

### 2A: Initialize Identity Registry early in `start()`

After the trust network start and BEFORE pool creation (before line 644 `# Start default pools`), add:

```python
# --- Sovereign Agent Identity (AD-441) ---
from probos.identity import AgentIdentityRegistry
self.identity_registry = AgentIdentityRegistry(data_dir=self._data_dir)
await self.identity_registry.start()
logger.info("identity registry started")
```

Also add `self.identity_registry: Any = None` to `__init__` alongside the other service attributes (near line 245 where `self.ontology` is declared).

### 2B: Assign persistent UUIDs to agents at pool creation

The key integration point: when `generate_pool_ids()` creates deterministic slot IDs, the runtime then resolves each slot to a persistent UUID via the identity registry.

In `_wire_agent()` (line ~3855), after the agent is registered but BEFORE trust, events, and ACM onboarding, add identity resolution:

```python
# AD-441: Resolve or issue persistent sovereign identity
if self.identity_registry:
    instance_id = ""
    vessel_name = "ProbOS"
    if self.ontology:
        vi = self.ontology.get_vessel_identity()
        instance_id = vi.instance_id
        vessel_name = vi.name

    # Get department and post for the birth certificate
    dept = ""
    post_id = ""
    if self.ontology:
        dept = self.ontology.get_agent_department(agent.agent_type) or ""
        post = self.ontology.get_post_for_agent(agent.agent_type)
        post_id = post.id if post else ""
    if not dept:
        from probos.cognitive.standing_orders import get_department
        dept = get_department(agent.agent_type) or "unassigned"

    callsign = getattr(agent, 'callsign', '') or agent.agent_type
    baseline = self.config.system.version  # Use system version as baseline

    cert = await self.identity_registry.resolve_or_issue(
        slot_id=agent.id,  # The deterministic slot ID
        agent_type=agent.agent_type,
        callsign=callsign,
        instance_id=instance_id,
        vessel_name=vessel_name,
        department=dept,
        post_id=post_id,
        baseline_version=baseline,
    )

    # Store the persistent UUID on the agent for all subsystem access
    agent.sovereign_id = cert.agent_uuid
    agent.did = cert.did
```

**IMPORTANT**: The `agent.id` field is NOT changed — it remains the deterministic slot ID for backward compatibility with existing subsystem keys. The new `agent.sovereign_id` field holds the permanent UUID. Subsystems will be migrated to use `sovereign_id` in future ADs. For NOW, the identity registry establishes the mapping and starts recording birth certificates.

### 2C: Pass identity registry to ACM

After ACM is started (line ~1369), wire the identity registry:

```python
if self.acm and self.identity_registry:
    self.acm.set_identity_registry(self.identity_registry)
```

### 2D: Episodic Memory — use sovereign_id for storage and recall

In `_wire_agent()`, after sovereign identity is assigned, store episodes using `sovereign_id`:

The episodic memory `store_episode()` and `recall_for_agent()` calls throughout the codebase use `agent.id`. For the immediate fix, modify the proactive loop's episode storage to prefer `sovereign_id`:

Find all calls to `episodic_memory.store()` and `episodic_memory.recall_for_agent()` in `runtime.py` and `proactive.py`. Wherever the agent ID is passed, use:

```python
agent_id = getattr(agent, 'sovereign_id', None) or agent.id
```

This pattern ensures backward compatibility — if sovereign_id isn't set (e.g., infrastructure agents), the slot ID is used.

Key locations to update:
- `proactive.py` line ~375-392: `recall_for_agent(agent.id, ...)` → use sovereign_id
- `proactive.py` line ~317-341: episode storage after proactive think → use sovereign_id
- `proactive.py` line ~236-259: no-response episode storage → use sovereign_id
- `runtime.py` line ~2446: `store_episode()` in task dispatch → use sovereign_id
- `cognitive_agent.py` line ~592-651: `_recall_relevant_memories()` → use sovereign_id

### 2E: Add identity registry to shutdown sequence

In the `stop()` method, add:

```python
if self.identity_registry:
    await self.identity_registry.stop()
```

---

## File 3: `src/probos/acm.py` (MODIFY)

### 3A: Add identity registry reference

Add a method to receive the identity registry:

```python
def set_identity_registry(self, registry: Any) -> None:
    """Wire the identity registry for birth certificate access."""
    self._identity_registry = registry
```

Add `self._identity_registry: Any = None` to `__init__`.

### 3B: Enhance onboard() to record birth certificate reference

In the `onboard()` method, after the lifecycle transition to PROBATIONARY, log the birth certificate association:

```python
async def onboard(
    self, agent_id: str, agent_type: str, pool: str, department: str,
    initiated_by: str = "system",
    sovereign_id: str = "",  # AD-441: persistent UUID
) -> LifecycleTransition:
    """Onboard an agent — register and set to probationary."""
    if not self._db:
        raise RuntimeError("ACM not started")

    now = time.time()
    await self._db.execute(
        "INSERT OR IGNORE INTO lifecycle (agent_id, state, state_since) VALUES (?, ?, ?)",
        (agent_id, LifecycleState.REGISTERED.value, now),
    )

    # AD-441: Record sovereign identity mapping
    if sovereign_id:
        await self._db.execute(
            "INSERT OR IGNORE INTO identity_mapping (slot_id, sovereign_id) VALUES (?, ?)",
            (agent_id, sovereign_id),
        )

    await self._db.commit()

    return await self.transition(
        agent_id, LifecycleState.PROBATIONARY,
        reason=f"Onboarded as {agent_type} in {department}",
        initiated_by=initiated_by,
    )
```

Add the identity_mapping table to `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS identity_mapping (
    slot_id TEXT PRIMARY KEY,
    sovereign_id TEXT NOT NULL
);
```

### 3C: Update the onboard() call in runtime.py

In `_wire_agent()` where ACM onboard is called (line ~3916), add the sovereign_id:

```python
await self.acm.onboard(
    agent_id=agent.id,
    agent_type=agent.agent_type,
    pool=agent.pool,
    department=department,
    sovereign_id=getattr(agent, 'sovereign_id', ''),
)
```

---

## File 4: `src/probos/substrate/agent.py` (MODIFY)

### 4A: Add sovereign identity fields to BaseAgent

In `__init__` (after `self.id` assignment at line 33), add:

```python
self.sovereign_id: str = ""   # AD-441: Permanent UUID, set by identity registry
self.did: str = ""            # AD-441: W3C DID, set by identity registry
```

---

## File 5: `src/probos/api.py` (MODIFY)

### 5A: Add identity API endpoints

Add a new endpoint to retrieve an agent's birth certificate:

```python
@app.get("/api/agent/{agent_id}/identity")
async def get_agent_identity(agent_id: str) -> dict:
    """Return the agent's birth certificate and DID."""
    if not runtime.identity_registry:
        return {"error": "Identity registry not available"}, 503

    # Look up by slot ID (the agent_id in the URL is the deterministic ID)
    cert = runtime.identity_registry.get_by_slot(agent_id)
    if not cert:
        return {"error": "No birth certificate found"}, 404

    return {
        "sovereign_id": cert.agent_uuid,
        "did": cert.did,
        "birth_certificate": cert.to_verifiable_credential(),
    }
```

Add a ledger verification endpoint:

```python
@app.get("/api/identity/ledger")
async def get_identity_ledger() -> dict:
    """Return the Identity Ledger status and chain verification."""
    if not runtime.identity_registry:
        return {"error": "Identity registry not available"}, 503

    valid, message = await runtime.identity_registry.verify_chain()
    chain = await runtime.identity_registry.export_chain()

    return {
        "valid": valid,
        "message": message,
        "block_count": len(chain),
        "chain": chain,
    }
```

Add a birth certificates list endpoint:

```python
@app.get("/api/identity/certificates")
async def list_birth_certificates() -> dict:
    """Return all birth certificates on this ship."""
    if not runtime.identity_registry:
        return {"error": "Identity registry not available"}, 503

    certs = runtime.identity_registry.get_all()
    return {
        "count": len(certs),
        "certificates": [c.to_verifiable_credential() for c in certs],
    }
```

### 5B: Add sovereign_id to agent profile response

In the agent profile endpoint (wherever the agent details are returned), add:

```python
"sovereign_id": getattr(agent, 'sovereign_id', ''),
"did": getattr(agent, 'did', ''),
```

---

## Tests

Create `tests/test_agent_identity.py`:

### Test 1: `test_generate_did_format`
Verify DID format: `did:probos:{instance_id}:{agent_uuid}`. Parse it back with `parse_did()`.

### Test 2: `test_parse_did_invalid`
Verify `parse_did()` returns None for invalid DIDs.

### Test 3: `test_birth_certificate_hash_deterministic`
Create two certificates with identical fields. Verify their `compute_hash()` outputs are identical.

### Test 4: `test_birth_certificate_hash_changes_with_content`
Create two certificates with one field different. Verify hashes differ.

### Test 5: `test_birth_certificate_to_verifiable_credential`
Create a certificate and call `to_verifiable_credential()`. Verify it has `@context`, `type` includes `"AgentBirthCertificate"`, `credentialSubject` has the right fields, and `proof` has `proofValue`.

### Test 6: `test_identity_registry_issue_and_retrieve`
Start a registry (in-memory SQLite), issue a birth certificate, retrieve it by UUID. Verify all fields match.

### Test 7: `test_identity_registry_slot_mapping`
Issue a certificate with a slot_id. Call `get_by_slot()`. Verify it returns the correct certificate.

### Test 8: `test_identity_registry_resolve_or_issue_new`
Call `resolve_or_issue()` for a new slot. Verify a new certificate is created.

### Test 9: `test_identity_registry_resolve_or_issue_existing`
Issue a certificate, then call `resolve_or_issue()` with the same slot_id. Verify the SAME certificate is returned (same UUID, not a new one).

### Test 10: `test_ledger_genesis_block`
Start a registry and issue one certificate. Verify the ledger has 2 blocks (genesis + agent). Verify genesis block has `previous_hash` of all zeros.

### Test 11: `test_ledger_chain_integrity`
Issue 3 certificates. Call `verify_chain()`. Assert it returns `(True, ...)`.

### Test 12: `test_ledger_tamper_detection`
Issue certificates, then manually corrupt one block's hash in the DB. Call `verify_chain()`. Assert it returns `(False, ...)`.

### Test 13: `test_ledger_export_chain`
Issue certificates, export chain. Verify each block includes the VC JSON.

### Test 14: `test_identity_persists_across_restarts`
Start a registry, issue a certificate, stop, start again. Verify the certificate is still there and the slot mapping works.

### Test 15: `test_sovereign_id_on_agent`
Create a mock agent with `sovereign_id = ""`. After identity resolution, verify `agent.sovereign_id` is a UUID and `agent.did` starts with `did:probos:`.

### Test 16: `test_multiple_agents_same_type_different_ids`
Issue two certificates for `agent_type="counselor"` (different slot_ids). Verify they get different UUIDs — each is a sovereign individual.

### Test structure

Use `aiosqlite` with `":memory:"` for database path in tests. Use `pytest.mark.asyncio` for async tests. Keep test setup minimal — create a temporary `Path` for data_dir using `tmp_path` fixture.

---

## Verification

1. `uv run pytest tests/test_agent_identity.py -v` — all 16 tests pass
2. `uv run pytest tests/test_proactive.py -v` — existing tests pass
3. `uv run pytest tests/test_ward_room_agents.py -v` — existing tests pass
4. `uv run pytest tests/test_cognitive_agent.py -v` — existing tests pass
5. `uv run pytest` — full suite passes

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `src/probos/identity.py` | **NEW** | DID utilities, BirthCertificate (VC), LedgerBlock, AgentIdentityRegistry |
| `src/probos/runtime.py` | **MODIFY** | Init registry, resolve_or_issue in _wire_agent, sovereign_id assignment, episodic memory sovereign_id |
| `src/probos/acm.py` | **MODIFY** | set_identity_registry(), sovereign_id in onboard(), identity_mapping table |
| `src/probos/substrate/agent.py` | **MODIFY** | Add sovereign_id and did fields to BaseAgent |
| `src/probos/proactive.py` | **MODIFY** | Use sovereign_id for episode storage and recall |
| `src/probos/cognitive/cognitive_agent.py` | **MODIFY** | Use sovereign_id for memory recall |
| `src/probos/api.py` | **MODIFY** | Identity endpoints, sovereign_id in profile |
| `tests/test_agent_identity.py` | **NEW** | 16 tests for identity registry, ledger, certificates |

---

## What This Does NOT Include (future ADs)

- **Agent self-naming ceremony** → AD-442 (Adaptive Onboarding & Temporal Awareness)
- **Temporal consciousness** (agents know their birth date, understand time passage, sleep awareness) → AD-442
- **Adaptive onboarding** (context-aware onboarding tailored to current ship state) → AD-442
- **Versioned baselines** (counselor 1.0 vs 2.0, upgrade paths) → AD-442
- **Trust/Journal/Hebbian/WardRoom migration to sovereign_id** → Future AD (incremental subsystem migration)
- **Federation ledger sync** (gossip-based chain exchange between ships) → Federation phase
- **Blockchain consensus** (cross-ship verification protocol) → Nooplex phase
- **DID Document resolution** (full DID Document with verification methods and service endpoints) → Federation phase
- **Certificate revocation** (decommissioned agents) → Future AD
