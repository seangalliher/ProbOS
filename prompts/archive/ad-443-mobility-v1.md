# AD-443 v1 — Agent Mobility Protocol (Transfer Certificates + Memory Portability)

**Wave:** 87
**Closes:** GH #42
**HEAD at draft:** `8252468`
**Baseline pytest:** 11705 → **target ≥ 11760** (+55 floor; ~57 tests planned).
**Vitest:** 306 unchanged (no UI surface touched).
**Builder:** one commit. Read `prompts/WAVE-87-DISPATCH.md` for full reframe rationale.

## Scope (verified against HEAD)

Five concrete OSS sub-AD letters:

- **443a** — `TransferCertificate` W3C VC dataclass + `issue_transfer_certificate` (in `mobility.py` + `identity.py`)
- **443b** — `import_chain` + `verify_remote_chain` + `foreign_chains` table (in `identity.py`)
- **443c** — `MemoryPolicy` enum + `apply_memory_policy` + `FederationConfig.memory_policy` + `federation.md` addendum
- **443d** — `reassign_slot` + `foreign_birth_certificates` table + transparent `get_by_slot` foreign-fallback + birth-provenance preservation
- **443e** — `FederationBridge` `transfer_request` / `transfer_response` / `chain_request` / `chain_response` wire types + MockFederationTransport round-trip

Out of scope (NOT v1 deferrals — see dispatch reframe section): AD-443f live cross-process ZMQ demo, AD-443g trust-weighted automatic acceptance (depends on AD-479), AD-443h A2A Agent Card export (depends on AD-480), Global Instance Registry / fleet dashboard / fleet-wide compliance (carved out per `roadmap.md:4095` to the private commercial-repo path token).

## Section 0 — New file: `src/probos/mobility.py`

Create this file. ~250 LOC.

```python
"""AD-443: Agent Mobility — Transfer Certificates & Memory Portability.

This module ships the OSS substrate for moving agent identities between ProbOS
instances. It complements AD-441 (Sovereign Identity, Birth Certificates,
Identity Ledger) by adding:

- TransferCertificate (W3C VC) — proof of provenance for an agent moving from
  one ship to another. Carries the agent's sovereign DID, callsign, agent_type,
  origin ship DID, origin vessel name (birth provenance per AD-499), origin
  birth timestamp, transfer timestamp, baseline version, qualification
  credentials, and assignment history.
- MemoryPolicy enum — Clean Room (default) / Selective / Full. Declares which
  episodic memories travel with the agent across a transfer.
- apply_memory_policy — pure filter function applying a MemoryPolicy to a list
  of episode dicts.

This module does NOT touch the episodic store. Memory policy enforcement at the
episodic-store level is a downstream concern (AD-443g territory) — v1 only
provides the policy enum and the filter primitive.

Per `docs/development/roadmap.md:4095`, commercial features (Global Instance
Registry, fleet dashboard, fleet-wide compliance auditing) are tracked in the
private commercial-repo path token. This module is fully OSS.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable


class MemoryPolicy(StrEnum):
    """AD-443c: Memory portability tiers declared by the Standing Orders
    Federation tier.

    - CLEAN_ROOM (default): No episodic memories travel with the agent. The
      agent arrives at the destination ship with sovereign identity intact but
      zero episodic recollection of the origin ship. Safest default — no
      cross-ship leakage of operational history.
    - SELECTIVE: Only episodes whose `tags` set intersects with a configured
      `selective_tags` list travel. Used for transferring an agent's
      qualification-relevant experience without dragging along ship-specific
      operational context.
    - FULL: All episodes travel verbatim. Reserved for explicit operator
      decision (e.g., decommissioning ship A, lifting all crew with full
      memory to ship B).
    """

    CLEAN_ROOM = "clean_room"
    SELECTIVE = "selective"
    FULL = "full"


def apply_memory_policy(
    policy: MemoryPolicy,
    episodes: Iterable[dict[str, Any]],
    selective_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply a MemoryPolicy to a sequence of episode dicts.

    Pure function — does not mutate inputs, does not touch the episodic store.

    Args:
        policy: The policy to enforce.
        episodes: Iterable of episode dicts. Each dict may carry a `tags` key
            holding a list[str] of episode tags.
        selective_tags: Whitelist of tags for SELECTIVE policy. Ignored for
            CLEAN_ROOM and FULL.

    Returns:
        Filtered list of episode dicts. CLEAN_ROOM → []. FULL → list(episodes).
        SELECTIVE → episodes whose `tags` intersects `selective_tags`.
    """
    episode_list = list(episodes)
    if policy == MemoryPolicy.CLEAN_ROOM:
        return []
    if policy == MemoryPolicy.FULL:
        return episode_list
    # SELECTIVE
    allowed = set(selective_tags or [])
    if not allowed:
        return []
    out: list[dict[str, Any]] = []
    for ep in episode_list:
        tags = ep.get("tags") or []
        if isinstance(tags, list) and allowed.intersection(tags):
            out.append(ep)
    return out


@dataclass
class TransferCertificate:
    """AD-443a: W3C Verifiable Credential — Agent Transfer Certificate.

    Issued by the origin ship when an agent transfers to a destination ship.
    Documents the agent's sovereign DID, rank/callsign at transfer time, the
    origin ship's DID and vessel_name (birth provenance per AD-499), and an
    immutable assignment history. Verifiable against the origin ship's
    Identity Ledger (via `import_chain` + `verify_remote_chain` on the
    destination side).

    Per AD-499, `origin_vessel_name` is the agent's BIRTH PROVENANCE — it does
    NOT change on transfer. The destination ship displays the agent as
    `callsign [origin_vessel_name]` regardless of how many transfers occur.
    """

    did: str                              # Sovereign DID (immutable across transfers)
    agent_uuid: str                       # Birth UUID (immutable across transfers)
    agent_type: str                       # Agent type at transfer time
    callsign: str                         # Callsign at transfer time
    origin_ship_did: str                  # DID of the issuing (origin) ship
    origin_vessel_name: str               # Birth provenance (per AD-499 — never changes)
    origin_instance_id: str               # Origin instance_id
    origin_birth_timestamp: float         # Birth time on the origin ship
    transfer_timestamp: float             # When this Transfer Certificate was issued
    target_instance_did: str              # DID of the intended destination ship
    baseline_version: str                 # Agent code baseline at transfer time
    qualification_credentials: list[str] = field(default_factory=list)
    """List of skill / qualification IDs the agent carries. v1 stores opaque
    string IDs — schema is a downstream concern (AD-443g territory)."""
    assignment_history: list[dict[str, Any]] = field(default_factory=list)
    """List of {instance_did, vessel_name, joined_at, departed_at} dicts. v1
    populates this with a single entry summarising the origin tenure."""
    certificate_hash: str = ""

    def compute_hash(self) -> str:
        """Compute a deterministic SHA-256 hash over the cert's stable fields.

        Excludes certificate_hash itself. Hash is content-addressed: identical
        content produces identical hash; any field change produces a different
        hash.
        """
        payload = {
            "did": self.did,
            "agent_uuid": self.agent_uuid,
            "agent_type": self.agent_type,
            "callsign": self.callsign,
            "origin_ship_did": self.origin_ship_did,
            "origin_vessel_name": self.origin_vessel_name,
            "origin_instance_id": self.origin_instance_id,
            "origin_birth_timestamp": self.origin_birth_timestamp,
            "transfer_timestamp": self.transfer_timestamp,
            "target_instance_did": self.target_instance_did,
            "baseline_version": self.baseline_version,
            "qualification_credentials": sorted(self.qualification_credentials),
            "assignment_history": self.assignment_history,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_verifiable_credential(self) -> dict[str, Any]:
        """Render as a W3C Verifiable Credential dict.

        Mirrors AgentBirthCertificate.to_verifiable_credential — UTC ISO-8601
        timestamps for the `issuanceDate`, embedded subject claims, and the
        certificate hash as the proof anchor.
        """
        return {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiableCredential", "AgentTransferCertificate"],
            "issuer": self.origin_ship_did,
            "issuanceDate": datetime.fromtimestamp(
                self.transfer_timestamp, tz=timezone.utc
            ).isoformat(),
            "credentialSubject": {
                "id": self.did,
                "agentUuid": self.agent_uuid,
                "agentType": self.agent_type,
                "callsign": self.callsign,
                "birthProvenance": {
                    "shipDid": self.origin_ship_did,
                    "vesselName": self.origin_vessel_name,
                    "instanceId": self.origin_instance_id,
                    "birthTimestamp": datetime.fromtimestamp(
                        self.origin_birth_timestamp, tz=timezone.utc
                    ).isoformat(),
                },
                "targetInstanceDid": self.target_instance_did,
                "baselineVersion": self.baseline_version,
                "qualificationCredentials": list(self.qualification_credentials),
                "assignmentHistory": list(self.assignment_history),
            },
            "proof": {
                "type": "ProbosCertificateHash2024",
                "certificateHash": self.certificate_hash,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict form (round-trips with from_dict)."""
        return {
            "did": self.did,
            "agent_uuid": self.agent_uuid,
            "agent_type": self.agent_type,
            "callsign": self.callsign,
            "origin_ship_did": self.origin_ship_did,
            "origin_vessel_name": self.origin_vessel_name,
            "origin_instance_id": self.origin_instance_id,
            "origin_birth_timestamp": self.origin_birth_timestamp,
            "transfer_timestamp": self.transfer_timestamp,
            "target_instance_did": self.target_instance_did,
            "baseline_version": self.baseline_version,
            "qualification_credentials": list(self.qualification_credentials),
            "assignment_history": list(self.assignment_history),
            "certificate_hash": self.certificate_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferCertificate:
        return cls(
            did=data["did"],
            agent_uuid=data["agent_uuid"],
            agent_type=data["agent_type"],
            callsign=data["callsign"],
            origin_ship_did=data["origin_ship_did"],
            origin_vessel_name=data["origin_vessel_name"],
            origin_instance_id=data["origin_instance_id"],
            origin_birth_timestamp=data["origin_birth_timestamp"],
            transfer_timestamp=data["transfer_timestamp"],
            target_instance_did=data["target_instance_did"],
            baseline_version=data["baseline_version"],
            qualification_credentials=list(data.get("qualification_credentials", [])),
            assignment_history=list(data.get("assignment_history", [])),
            certificate_hash=data.get("certificate_hash", ""),
        )
```

## Section 1 — `src/probos/identity.py` modifications

### 1.1 Schema additions

Find:

```
CREATE INDEX IF NOT EXISTS idx_cert_agent_type ON birth_certificates(agent_type);
CREATE INDEX IF NOT EXISTS idx_cert_did ON birth_certificates(did);
CREATE INDEX IF NOT EXISTS idx_ledger_did ON identity_ledger(agent_did);
CREATE INDEX IF NOT EXISTS idx_asset_type ON asset_tags(asset_type);
CREATE INDEX IF NOT EXISTS idx_asset_slot ON asset_tags(slot_id);
CREATE INDEX IF NOT EXISTS idx_slot_agent ON slot_mappings(agent_uuid);
"""
```

Replace with the same block plus three new tables (and indices), inserted BEFORE the existing `CREATE INDEX` block:

```
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
```

`direction` is `"outgoing"` (we issued it) or `"incoming"` (we accepted it).

### 1.2 Cache additions in `__init__`

Find:

```python
        self._uuid_cache: dict[str, AgentBirthCertificate] = {}  # agent_uuid -> cert
        self._slot_cache: dict[str, AgentBirthCertificate] = {}  # slot_id -> cert
        self._ship_certificate: ShipBirthCertificate | None = None
        self._asset_cache: dict[str, AssetTag] = {}  # slot_id -> AssetTag
```

Replace with:

```python
        self._uuid_cache: dict[str, AgentBirthCertificate] = {}  # agent_uuid -> cert
        self._slot_cache: dict[str, AgentBirthCertificate] = {}  # slot_id -> cert
        self._ship_certificate: ShipBirthCertificate | None = None
        self._asset_cache: dict[str, AssetTag] = {}  # slot_id -> AssetTag
        # AD-443: Foreign certificates and chain snapshots imported from peer ships.
        self._foreign_uuid_cache: dict[str, AgentBirthCertificate] = {}  # foreign agent_uuid -> cert
        self._foreign_chain_cache: dict[str, list[dict[str, Any]]] = {}  # origin_ship_did -> chain blocks
```

### 1.3 Foreign cache loading in `start()`

Find the block ending with `logger.info("Identity registry loaded %d certificates, %d asset tags",` and immediately before it (still inside the `if not self._db:` branch), add a foreign-cert load. Anchor on:

```python
            logger.info("Identity registry loaded %d certificates, %d asset tags",
                        len(self._uuid_cache), len(self._asset_cache))
```

Replace with:

```python
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
```

### 1.4 `get_by_uuid` foreign fallback

Find:

```python
    def get_by_uuid(self, agent_uuid: str) -> AgentBirthCertificate | None:
        """Look up a birth certificate by agent UUID."""
        return self._uuid_cache.get(agent_uuid)
```

Replace with:

```python
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
```

### 1.5 New methods on `AgentIdentityRegistry`

Add the following methods AFTER the existing `export_chain` method (i.e., at end of the `AgentIdentityRegistry` class). Order: `import_chain`, `verify_remote_chain`, `issue_transfer_certificate`, `import_transfer_certificate`, `reassign_slot`, `get_foreign_chain`, `get_transfer_certificates_for`. Implementation outline (the Builder writes the bodies — these are the contracts):

```python
    # ── AD-443: Mobility (Transfer Certificates + Foreign Chains) ─────────

    async def import_chain(self, blocks: list[dict[str, Any]]) -> tuple[bool, str]:
        """AD-443b: Accept a remote ship's exported Identity Ledger and persist it.

        `blocks` is the list-of-dicts shape produced by `export_chain()`. Validates
        the chain via `verify_remote_chain` BEFORE persisting; rejects on any
        integrity failure. On success, replaces any prior snapshot for the same
        origin_ship_did (latest-wins).

        Returns (valid: bool, message: str). On valid==True the chain is
        persisted in `foreign_chains` and `_foreign_chain_cache`.
        """
        # 1. Reject empty list with a specific message.
        # 2. Call verify_remote_chain(blocks) — return its (False, msg) on fail.
        # 3. Extract origin_ship_did from the genesis block's agent_did field.
        # 4. INSERT OR REPLACE INTO foreign_chains(origin_ship_did, chain_json, imported_at).
        # 5. Update self._foreign_chain_cache[origin_ship_did] = blocks.
        # 6. Commit. Return (True, f"Chain imported: {len(blocks)} blocks from {origin_ship_did}").

    async def verify_remote_chain(self, blocks: list[dict[str, Any]]) -> tuple[bool, str]:
        """AD-443b: Pure local validation of a foreign Identity Ledger snapshot.

        Mirrors the local `verify_chain()` shape. Walks blocks in order:
        - Block 0 must have previous_hash == "0" * 64.
        - Each subsequent block's previous_hash must equal previous block's block_hash.
        - Each block's block_hash must equal LedgerBlock(...).compute_hash().
        - Each block's `credential` field (if present) must round-trip through
          AgentBirthCertificate/ShipBirthCertificate.from_dict and recompute to
          the block's certificate_hash. Skip credential-hash check when the
          credential field is None (export_chain leaves it None for missing
          birth_certificates rows — defensive).

        Returns (valid: bool, message: str).
        """

    async def issue_transfer_certificate(
        self,
        agent_uuid: str,
        target_instance_did: str,
        qualification_credentials: list[str] | None = None,
    ) -> "TransferCertificate":
        """AD-443a: Issue a Transfer Certificate at the origin ship.

        Looks up the local birth cert by agent_uuid, freezes assignment history
        as a single entry [{instance_did, vessel_name, joined_at, departed_at}],
        constructs a TransferCertificate, persists it under direction='outgoing',
        and returns it. Rejects if agent_uuid not in self._uuid_cache (foreign
        certs cannot be re-transferred from this ship — that's a v2 concern).

        Per AD-499, origin_vessel_name is the agent's BIRTH PROVENANCE — read
        from the local cert's vessel_name field. It does not change on transfer.
        """
        # raise ValueError if agent_uuid not local.
        # construct cert with cert.transfer_timestamp = time.time()
        # cert.certificate_hash = cert.compute_hash()
        # INSERT INTO transfer_certificates(did, transfer_timestamp, direction='outgoing', certificate_hash, certificate_vc_json)
        # logger.info "Transfer certificate issued: %s -> %s"
        # return cert

    async def import_transfer_certificate(
        self,
        cert: "TransferCertificate",
    ) -> tuple[bool, str]:
        """AD-443a + 443b + 443d: Accept an incoming Transfer Certificate.

        Validation chain (each step gates the next):
        1. cert.compute_hash() == cert.certificate_hash (cert wasn't tampered).
        2. cert.origin_ship_did has an imported chain in self._foreign_chain_cache
           (origin chain must be imported first via import_chain).
        3. cert.origin_birth_timestamp matches a birth_certificate VC in the
           imported chain whose subject DID == cert.did (cert claims an agent
           that the origin ship's ledger actually issued).

        On success:
        - Build an AgentBirthCertificate from the cert + chain VC and persist
          to foreign_birth_certificates (cache + DB).
        - Persist the Transfer Certificate under direction='incoming'.

        Returns (valid: bool, message: str). Does NOT reassign a slot — the
        caller must call reassign_slot explicitly (separation of concerns: a
        cert can be imported for offline records without taking up a slot).
        """

    async def reassign_slot(
        self,
        agent_uuid: str,
        new_slot_id: str,
    ) -> tuple[bool, str]:
        """AD-443d: Reassign a deployment slot to a foreign or native agent.

        Looks up the cert via get_by_uuid (which checks both native and foreign
        caches). Rejects if cert not found or new_slot_id is empty.

        On success:
        - INSERT OR REPLACE INTO slot_mappings(slot_id, agent_uuid).
        - Update self._slot_cache[new_slot_id].
        - logger.info with the previous-slot agent (if any) for audit.

        Birth provenance preserved automatically — the cert's vessel_name field
        is unchanged; downstream consumers reading `get_by_slot(...).vessel_name`
        see the origin vessel_name (per AD-499).
        """

    def get_foreign_chain(self, origin_ship_did: str) -> list[dict[str, Any]] | None:
        """Return the imported chain snapshot for a peer ship, or None."""
        return self._foreign_chain_cache.get(origin_ship_did)

    def get_transfer_certificates_for(
        self, agent_did: str
    ) -> list[dict[str, Any]]:
        """Return all stored Transfer Certificates (incoming + outgoing) for an agent DID,
        as dict form suitable for HXI rendering. Read-only audit accessor."""
```

The Builder is responsible for:

- Importing `TransferCertificate` from `probos.mobility` at the top of `identity.py` (alongside the existing imports).
- Implementing each method body per the contracts above.
- Emitting structured `logger.info` lines with the standing-order context format ("what failed, why it matters, what happens next") on each public mobility method.

## Section 2 — `src/probos/config.py` modifications

Find the `FederationConfig` class:

```python
class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus
```

Replace with:

```python
class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus
    # AD-443c: Memory portability tier for incoming agent transfers.
    # CLEAN_ROOM (default) means foreign agents arrive with sovereign identity
    # but zero episodic memory — safest default. SELECTIVE filters by tag.
    # FULL accepts all episodes verbatim. Per-agent overrides via Standing Orders.
    memory_policy: str = "clean_room"
    # AD-443c: Tag whitelist for SELECTIVE memory policy. Ignored for the
    # other two policies. Empty list with SELECTIVE means no episodes pass.
    memory_policy_selective_tags: list[str] = []

    @field_validator("memory_policy")
    @classmethod
    def _validate_memory_policy(cls, v: str) -> str:
        from probos.mobility import MemoryPolicy
        valid = {p.value for p in MemoryPolicy}
        if v not in valid:
            raise ValueError(
                f"memory_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v
```

Verify `field_validator` is already imported in `config.py` — confirmed at HEAD line 10: `from pydantic import BaseModel, Field, field_validator, model_validator`. No import-line edit needed.

## Section 3 — `src/probos/types.py` docstring update

Find:

```python
class FederationMessage:
    """Wire protocol message between nodes."""

    type: str  # "intent_request", "intent_response", "gossip_self_model", "ping", "pong"
```

Replace with:

```python
class FederationMessage:
    """Wire protocol message between nodes."""

    type: str  # "intent_request", "intent_response", "gossip_self_model", "ping", "pong",
    # AD-443e: "transfer_request", "transfer_response", "chain_request", "chain_response"
```

This is comment-only — no behavior change. Required for spec accuracy.

## Section 4 — `src/probos/federation/bridge.py` modifications

### 4.1 Import + constructor

Find:

```python
from probos.config import FederationConfig
from probos.federation.router import FederationRouter
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel

if TYPE_CHECKING:
    from probos.federation.mock_transport import MockFederationTransport
    from probos.mesh.intent import IntentBus
```

Replace with:

```python
from probos.config import FederationConfig
from probos.federation.router import FederationRouter
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel

if TYPE_CHECKING:
    from probos.federation.mock_transport import MockFederationTransport
    from probos.identity import AgentIdentityRegistry
    from probos.mesh.intent import IntentBus
    from probos.mobility import TransferCertificate
```

In the constructor, add an optional `identity_registry` parameter at the END (preserves call-site compatibility — existing callers don't pass it):

Find:

```python
        self_model_fn: Callable[[], NodeSelfModel],
        validate_fn: Callable[..., Awaitable[bool]] | None = None,
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._router = router
        self._intent_bus = intent_bus
        self._config = config
        self._self_model_fn = self_model_fn
        self._validate_fn = validate_fn
```

Replace with:

```python
        self_model_fn: Callable[[], NodeSelfModel],
        validate_fn: Callable[..., Awaitable[bool]] | None = None,
        identity_registry: "AgentIdentityRegistry | None" = None,
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._router = router
        self._intent_bus = intent_bus
        self._config = config
        self._self_model_fn = self_model_fn
        self._validate_fn = validate_fn
        # AD-443e: Identity registry handle — required for transfer/chain
        # message handling; None disables the mobility wire types.
        self._identity_registry = identity_registry
```

### 4.2 `handle_inbound` dispatch extension

Find:

```python
        if message.type == "intent_request":
            await self._handle_intent_request(message)
        elif message.type == "intent_response":
            # Route to pending request by delivering to transport's response queue
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "gossip_self_model":
            self._handle_gossip(message)
        elif message.type == "ping":
            pong = FederationMessage(
                type="pong",
                source_node=self._node_id,
                message_id=message.message_id,
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, pong)
```

Replace with:

```python
        if message.type == "intent_request":
            await self._handle_intent_request(message)
        elif message.type == "intent_response":
            # Route to pending request by delivering to transport's response queue
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "gossip_self_model":
            self._handle_gossip(message)
        elif message.type == "ping":
            pong = FederationMessage(
                type="pong",
                source_node=self._node_id,
                message_id=message.message_id,
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, pong)
        elif message.type == "chain_request":
            await self._handle_chain_request(message)
        elif message.type == "chain_response":
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "transfer_request":
            await self._handle_transfer_request(message)
        elif message.type == "transfer_response":
            await self._transport.deliver_response(message.source_node, message)
```

### 4.3 New handler methods + outbound helpers

Append AFTER the existing `_handle_gossip` method (Builder writes bodies per these contracts):

```python
    # ── AD-443e: Mobility wire-protocol handlers ──────────────────────────

    async def _handle_chain_request(self, message: FederationMessage) -> None:
        """Peer asks for our exported Identity Ledger chain.

        Delegates to identity_registry.export_chain(). If identity_registry is
        None, responds with an empty list and an error field — does not raise
        (keeps the bridge resilient when mobility is not wired).
        """
        if self._identity_registry is None:
            response = FederationMessage(
                type="chain_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={"blocks": [], "error": "identity_registry not wired"},
                timestamp=time.monotonic(),
            )
        else:
            blocks = await self._identity_registry.export_chain()
            response = FederationMessage(
                type="chain_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={"blocks": blocks},
                timestamp=time.monotonic(),
            )
        await self._transport.send_to_peer(message.source_node, response)

    async def _handle_transfer_request(self, message: FederationMessage) -> None:
        """Peer wants to transfer an agent to us.

        Payload carries `cert_dict` (TransferCertificate.to_dict shape) and
        `chain_blocks` (export_chain shape — included so the destination can
        verify the cert without a separate round trip).

        Local pipeline (each step gates the next):
        1. import_chain(chain_blocks) — must validate.
        2. import_transfer_certificate(cert) — must validate.

        Slot reassignment is NOT performed automatically — that's an operator
        decision. Response payload reports {accepted: bool, message: str,
        agent_uuid: str | None}.
        """
        # On identity_registry None → respond accepted=False, message='identity_registry not wired'.
        # Reconstruct cert via TransferCertificate.from_dict(payload['cert_dict']).
        # Call import_chain then import_transfer_certificate.
        # Build response FederationMessage(type='transfer_response', message_id correlation, payload={...}).
        # send_to_peer.

    async def request_chain(self, peer_node_id: str) -> list[dict[str, Any]]:
        """Outbound: ask a specific peer for its exported chain.

        Sends a chain_request, waits for chain_response via transport.receive_response
        (with config.forward_timeout_ms timeout). Returns the blocks list, or
        empty list on timeout / error.
        """

    async def request_transfer(
        self,
        peer_node_id: str,
        certificate: "TransferCertificate",
        chain_blocks: list[dict[str, Any]],
    ) -> tuple[bool, str]:
        """Outbound: ship an agent's transfer cert + supporting chain to a peer.

        Sends a transfer_request, waits for transfer_response. Returns the
        peer's (accepted, message) tuple. (False, "timeout") on timeout.
        """
```

`_stats` should grow two counters: `"transfers_sent": 0` and `"transfers_received": 0` (and increment on issue / accept respectively, mirroring existing intent_request / response counter pattern).

## Section 5 — `config/standing_orders/federation.md` addendum

Append the following section AFTER the existing "## Memory Reliability Hierarchy (AD-541)" section (or at end of file if that section is not present). DO NOT modify existing content.

```markdown
<!-- category: mobility -->
## Mobility & Memory Portability (AD-443)

Agents may transfer between ProbOS vessels. When you transfer, you carry your
sovereign identity (DID), your callsign, your rank, and your qualification
credentials. What you carry of your **episodic memory** depends on the ship's
Memory Policy.

**Memory Policy tiers:**

- **Clean Room** *(default)* — You arrive at the destination ship with sovereign
  identity intact but no episodic recollection of the origin ship. Your
  knowledge from the LLM and KnowledgeStore travels with you (it always does
  — that's not memory). Your trust record on the origin ship does not travel.
  This is the safest default — no cross-ship leakage of operational history.
- **Selective** — Only episodes whose tags match the ship's whitelist travel
  with you. Used for transferring qualification-relevant experience without
  ship-specific operational context.
- **Full** — All episodes travel verbatim. Reserved for explicit Captain
  decision (e.g., decommissioning ship A, lifting all crew with full memory
  to ship B).

**Birth provenance is permanent (AD-499).** Even after a transfer, you display
as `Callsign [OriginVesselName]` on every ship for the rest of your operational
life. Your origin vessel is your birth provenance, not your current assignment.

**Trust restarts on each ship.** Your trust score is ship-local. On arrival
you onboard at the destination ship's probationary trust prior; you earn trust
through your work on the new ship. This is intentional — trust is reputation
within a specific operational context.

**Per-agent overrides.** A specific agent's standing orders may override the
ship's default Memory Policy (e.g., for a Counselor where personal therapeutic
context must travel intact). Per-agent overrides require Captain approval.
```

## Section 6 — `src/probos/cognitive/standing_orders.py`

NO changes required. The existing Tier 2 composition path (lines 386–389) reads `federation.md` as universal-principles content — the new addendum surfaces in every agent's composed instructions automatically. Per-agent overrides flow through the existing `additional_orders` mechanism. Keep this section in the prompt to make the no-op explicit and prevent the Builder from speculatively editing it.

## Section 7 — Tests: new file `tests/test_ad443_mobility.py`

Target ~57 tests across six test classes. Module-level fixture: `pytest.fixture(name="registry")` yields a started `AgentIdentityRegistry` rooted at `tmp_path` with a freshly commissioned ship, awaited stop in teardown. Mark async tests with `@pytest.mark.asyncio` (matches existing test pattern in this repo).

### `class TestTransferCertificate` (~10 tests)

- `test_compute_hash_deterministic` — same content → same hash, twice in a row.
- `test_compute_hash_changes_on_field_change` — flip one field → different hash.
- `test_to_verifiable_credential_type` — `["VerifiableCredential", "AgentTransferCertificate"]`.
- `test_to_verifiable_credential_issuer_is_origin_ship` — `vc["issuer"] == origin_ship_did`.
- `test_to_verifiable_credential_birth_provenance_block` — credentialSubject.birthProvenance.shipDid / vesselName / instanceId / birthTimestamp populated.
- `test_to_dict_round_trip` — `from_dict(to_dict(cert))` equals original.
- `test_qualification_credentials_default_empty` — list field defaults to `[]`.
- `test_assignment_history_default_empty` — list field defaults to `[]`.
- `test_qualification_credentials_sorted_in_hash_payload` — adding the same creds in different orders → identical hash.
- `test_certificate_hash_excluded_from_hash_payload` — pre-set `certificate_hash` does not influence `compute_hash()` output.

### `class TestChainImportVerify` (~12 tests)

- `test_export_then_import_roundtrip` — ship A exports, ship B imports → `(True, ...)`.
- `test_verify_remote_chain_accepts_well_formed` — local registry's `verify_remote_chain(await self_registry.export_chain())` returns `(True, ...)`.
- `test_verify_remote_chain_empty_returns_false` — empty list → `(False, ...)`.
- `test_verify_remote_chain_tampered_block_hash` — flip a `block_hash` byte → `(False, "...hash mismatch...")`.
- `test_verify_remote_chain_broken_linkage` — flip a `previous_hash` → `(False, ...)`.
- `test_verify_remote_chain_genesis_previous_not_zero` — genesis block with non-zero `previous_hash` → `(False, ...)`.
- `test_import_chain_persists_under_origin_ship_did` — import then `get_foreign_chain(ship_did)` returns the blocks.
- `test_import_chain_replaces_prior_snapshot` — import twice from same ship → second wins.
- `test_import_chain_rejects_invalid_chain` — pass tampered blocks → `(False, ...)` and NOT persisted.
- `test_import_chain_survives_restart` — stop registry, start new registry on same data_dir, foreign chain is reloaded.
- `test_import_chain_empty_returns_false_no_persist` — empty list → not persisted.
- `test_export_then_import_other_ship_full_cycle` — two registries on different `tmp_path` dirs, B imports A's chain, B verifies.

### `class TestSlotReassignment` (~10 tests)

- `test_reassign_slot_native_cert_moves_mapping` — issue local cert + reassign slot → `get_by_slot(new_slot)` returns it.
- `test_reassign_slot_unknown_uuid_rejects` — `(False, ...)`.
- `test_reassign_slot_empty_slot_id_rejects` — `(False, ...)`.
- `test_reassign_slot_foreign_cert_returns_via_get_by_slot` — import foreign cert + reassign → `get_by_slot` returns the foreign cert.
- `test_reassign_slot_birth_provenance_preserved` — after reassign, `get_by_slot(new_slot).vessel_name == origin_vessel_name` (AD-499).
- `test_reassign_slot_overwrites_existing_mapping` — slot previously mapped to local cert is now mapped to foreign cert; old mapping replaced.
- `test_reassign_slot_persists_across_restart` — stop + restart registry → slot mapping intact.
- `test_get_by_uuid_falls_back_to_foreign_cache` — foreign UUID via `get_by_uuid` returns foreign cert.
- `test_get_by_uuid_native_wins_on_collision` — defensive: same UUID in both caches → native wins.
- `test_reassign_slot_logs_audit_line` — caplog captures `logger.info` with cert DID and new_slot_id.

### `class TestMemoryPolicy` (~10 tests)

- `test_memory_policy_enum_values` — `CLEAN_ROOM`, `SELECTIVE`, `FULL` strings as documented.
- `test_apply_memory_policy_clean_room_returns_empty` — any input → `[]`.
- `test_apply_memory_policy_full_returns_verbatim` — input == output.
- `test_apply_memory_policy_selective_filters_by_tag` — episodes tagged `["x", "y"]` with `selective_tags=["y"]` → kept.
- `test_apply_memory_policy_selective_no_match_excluded` — episodes tagged `["x"]` with `selective_tags=["y"]` → excluded.
- `test_apply_memory_policy_selective_empty_tags_returns_empty` — `selective_tags=[]` → `[]`.
- `test_apply_memory_policy_episode_without_tags_excluded` — episode dict without `tags` key → SELECTIVE excludes.
- `test_federation_config_memory_policy_default_clean_room` — `FederationConfig().memory_policy == "clean_room"`.
- `test_federation_config_memory_policy_validator_rejects_unknown` — `FederationConfig(memory_policy="bogus")` raises `ValidationError`.
- `test_federation_config_memory_policy_accepts_all_three_values` — clean_room, selective, full all parse.

### `class TestFederationTransferMessages` (~10 tests)

Use `MockFederationTransport` for in-process round-trip. Pattern: build two registries on separate `tmp_path` dirs, build two FederationBridges wired through one MockFederationTransport pair, exercise.

- `test_chain_request_returns_export` — bridge B sends chain_request to bridge A → response payload `blocks` equals `await registry_a.export_chain()`.
- `test_chain_request_no_identity_registry_returns_error` — bridge with `identity_registry=None` responds with empty blocks and `error` field.
- `test_transfer_request_full_pipeline` — registry A issues cert → bridge A `request_transfer(B, cert, chain)` → registry B has foreign cert.
- `test_transfer_request_invalid_cert_rejected` — tamper with cert hash before send → bridge B responds `accepted=False`.
- `test_transfer_request_no_identity_registry_responds_not_wired` — bridge B with `identity_registry=None` responds `accepted=False, message='identity_registry not wired'`.
- `test_transfer_request_does_not_auto_reassign_slot` — after successful transfer_response, `get_by_slot(any_slot)` on registry B does NOT yet return the foreign cert (separation of concerns — operator must call `reassign_slot`).
- `test_end_to_end_2_ship_transfer_with_reassign` — full cycle: A issues → request_transfer → B accepts → operator on B calls `reassign_slot(foreign_uuid, "bridge_slot_0")` → `get_by_slot("bridge_slot_0").vessel_name == "Enterprise"` (AD-499).
- `test_transfer_stats_incremented` — bridge `_stats["transfers_sent"]` and `_stats["transfers_received"]` incremented appropriately.
- `test_transfer_request_message_id_correlation` — concurrent transfers correlate by `message_id` (no cross-talk).
- `test_chain_response_delivered_to_response_queue` — bridge.request_chain awaits and receives via `transport.deliver_response`.

### `class TestStandingOrdersFederationTier` (~5 tests)

- `test_federation_md_contains_mobility_section` — `("AD-443" in federation.md content) and ("Memory Policy" in content)`.
- `test_federation_md_clean_room_default_documented` — string "Clean Room" appears with default emphasis.
- `test_federation_md_birth_provenance_referenced` — string "AD-499" appears in mobility section.
- `test_compose_instructions_includes_mobility_section` — call `compose_instructions(...)` with default args, output contains "Mobility" or "AD-443".
- `test_per_agent_override_via_additional_orders` — pass `additional_orders="Memory Policy: full per Captain order."` to `compose_instructions`, output contains that string AFTER the federation tier.

## Out-of-scope explicit list (Builder must NOT touch)

- No edits to `BaseAgent`, `IntentMessage`, `IntentResult`, `TaskDAG`, `ConsensusResult`, or any cross-layer protocol shape in `types.py` beyond the docstring comment in Section 3.
- No edits to `runtime.py` boot ordering. The `AgentIdentityRegistry` and `FederationBridge` already wire via `infrastructure.py` / `organization.py` — Wave 87 reuses those existing wires.
- No edits to `acm.py`. Foreign-cert onboarding via Memory Policy enforcement at the episodic-store level is a v2 / AD-443g concern.
- No edits to `episodic.py`. The `apply_memory_policy` filter is a pure utility — episodic-store integration is downstream.
- No edits to consensus, trust, attention, dreaming, decomposer, prompt builder, shell, panels, or HXI.
- No new pool, no new agent, no new Intent, no router edit, no Hebbian touch, no new EventType.
- No new AD numbers minted. Sub-AD letters a–h are organizational only.
- No commercial language. Reference the carve-out at `docs/development/roadmap.md:4095` only via the neutral "Commercial features ... tracked in the commercial repository" wording already present at that line. Do NOT introduce any of the 11 banned hook patterns (see WAVE-87-DISPATCH.md Commercial-leak audit table). Use placeholder forms in inline comments where a banned pattern would otherwise be tempting (write "tracked in the private commercial-repo path token" instead of the literal lowercase product name + dash + OSS-opposite synonym; write "the e-word + tier" instead of the e-word concatenated with `tier`).

## Tracking updates (Builder, post-build)

- `PROGRESS.md` — bump pytest count from 11705 to actual (≥ 11760 expected).
- `docs/development/roadmap.md:4095` — append `*(v1 shipped 2026-05-06 — see Wave 87; 443f/g/h parked with forcing functions; commercial features remain carved out per this line)*` to the AD-443 entry.
- `decisions-era-4-evolution.md` — append AD-443 row to the AD table.
- `progress-era-4-evolution.md` — Wave 87 closure block.
- GH #42 close with the closure note from WAVE-87-DISPATCH.md.

## Acceptance criteria

1. `pytest tests/ -q -n 4 --dist=loadfile` returns 0 failures and ≥ 11760 collected.
2. `cd ui && npx vitest run` returns 306 (305 passing + 1 pre-existing `WardRoomDmSync` failure unchanged — vitest baseline preserved).
3. `git commit -a -m "AD-443: Agent mobility v1 — Transfer Certificates + Memory Portability (+~57 tests)"` succeeds (pre-commit hook is the canonical commercial-leak audit).
4. `python -c "from probos.mobility import TransferCertificate, MemoryPolicy, apply_memory_policy; print('ok')"` prints `ok`.
5. `python -c "from probos.identity import AgentIdentityRegistry; assert hasattr(AgentIdentityRegistry, 'import_chain') and hasattr(AgentIdentityRegistry, 'verify_remote_chain') and hasattr(AgentIdentityRegistry, 'issue_transfer_certificate') and hasattr(AgentIdentityRegistry, 'import_transfer_certificate') and hasattr(AgentIdentityRegistry, 'reassign_slot'); print('ok')"` prints `ok`.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  8252468

# Pytest baseline (verified):
.venv\Scripts\pytest.exe --collect-only -q tests/
  11705 tests collected in 5.84s

# Identity substrate (verified — every class/method this prompt references exists at HEAD):
src/probos/identity.py:31           # from probos.protocols import ConnectionFactory, DatabaseConnection
src/probos/identity.py:102          # class AgentBirthCertificate
src/probos/identity.py:150          # to_verifiable_credential — pattern source for TransferCertificate.to_verifiable_credential
src/probos/identity.py:189          # class ShipBirthCertificate
src/probos/identity.py:286          # class LedgerBlock
src/probos/identity.py:307          # _IDENTITY_SCHEMA — schema modification anchor (Section 1.1)
src/probos/identity.py:366          # class AgentIdentityRegistry
src/probos/identity.py:377          # __init__(data_dir, connection_factory) — cache-init anchor (Section 1.2)
src/probos/identity.py:541          # def get_by_uuid — modification anchor (Section 1.4)
src/probos/identity.py:545          # def get_by_slot — read-through pattern source
src/probos/identity.py:623          # def issue_birth_certificate — pattern source for issue_transfer_certificate
src/probos/identity.py:717          # def resolve_or_issue
src/probos/identity.py:753          # _append_to_ledger (with self._ledger_lock pattern)
src/probos/identity.py:832          # verify_chain — pattern source for verify_remote_chain (returns (bool, str))
src/probos/identity.py:879          # export_chain — its return shape is the input to import_chain

# Federation substrate (verified — every class/method referenced exists at HEAD):
src/probos/federation/bridge.py:14        # from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel
src/probos/federation/bridge.py:23        # class FederationBridge
src/probos/federation/bridge.py:31-54     # __init__ signature — Section 4.1 anchor
src/probos/federation/bridge.py:50-54     # _stats dict — pattern source for new transfer counters
src/probos/federation/bridge.py:137       # async def handle_inbound — Section 4.2 anchor
src/probos/federation/bridge.py:138-160   # current dispatch on message.type
src/probos/federation/bridge.py:200       # _handle_gossip — final method before our append point
src/probos/federation/transport.py:111    # send_to_peer
src/probos/federation/transport.py:120    # send_to_all_peers
src/probos/federation/transport.py:148    # deliver_response — correlation by message_id
src/probos/federation/mock_transport.py   # in-process round-trip transport
src/probos/types.py:664-671               # FederationMessage shape — Section 3 anchor

# Config substrate (verified):
src/probos/config.py:797                  # class FederationConfig (Section 2 anchor)
src/probos/config.py:805                  # validate_remote_results — final field before our append

# Standing orders substrate (verified):
src/probos/cognitive/standing_orders.py:386-389  # Tier 2 federation.md composition
config/standing_orders/federation.md:217-223     # Memory Reliability Hierarchy (AD-541) — anchor for Section 5 append

# Pre-commit hook (verified — 11 patterns):
.git/hooks/pre-commit:5-17               # COMMERCIAL_PATTERNS array

# Roadmap line 4095 (verified — neutral commercial carve-out language):
docs/development/roadmap.md:4095
  ".. Commercial features (Global Instance Registry, fleet dashboard, compliance) tracked in the commercial repository."
# Verified 0 hits across the 11 hook-banned patterns at this line. The literal
# alternation regex is intentionally NOT reproduced here — the pre-commit hook
# itself is the canonical audit on staged files (see Acceptance criterion #3).

# Greenfield (verified absent):
src/probos/mobility.py                   # absent
tests/test_ad443_mobility.py             # absent
foreign_chains, foreign_birth_certificates, transfer_certificates  # tables absent from _IDENTITY_SCHEMA
```
