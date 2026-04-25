# AD-441b: Ship Commissioning — Genesis Block with ShipBirthCertificate

## Context

AD-441 implemented sovereign agent identity with W3C DIDs, birth certificates, and an Identity Ledger hash-chain blockchain. The genesis block (block 0) currently uses placeholder values:

```python
genesis = LedgerBlock(
    index=0,
    timestamp=time.time(),
    certificate_hash="genesis",       # ← placeholder
    agent_did="ship",                 # ← placeholder, not a real DID
    previous_hash="0" * 64,
)
```

Ship commissioning is the first act of a new timeline. The ship must be born properly — with its own DID (`did:probos:{instance_id}`), a real `ShipBirthCertificate` W3C Verifiable Credential, and a genesis block that carries the certificate hash. Only after the ship is commissioned can agents be born under it.

The `generate_ship_did()` and `parse_did()` functions already exist in `identity.py`. The `instance_id` is already generated and persisted by `ontology.py` (`_load_or_generate_instance_id()`). This AD wires them together into a proper commissioning ceremony.

## Goals

1. Create a `ShipBirthCertificate` dataclass (W3C VC) for the ship itself
2. Replace the placeholder genesis block with a real commissioning block carrying the ship's certificate hash and ship DID
3. Persist the ship certificate in the DB alongside agent certificates
4. Expose the ship's identity via the existing API endpoints
5. The commissioning timestamp becomes the ship's `born_at` — the start of this timeline

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/identity.py` | Add `ShipBirthCertificate`, update `_create_genesis_block()`, add `get_ship_certificate()`, update `start()` to load ship cert, add `ship_birth_certificate` table |
| `src/probos/runtime.py` | Pass `instance_id` + `vessel_name` to `identity_registry.start()` for commissioning |
| `src/probos/api.py` | Add `GET /api/identity/ship` endpoint |
| `tests/test_agent_identity.py` | Add tests for ship commissioning |

## Implementation

### 1. `ShipBirthCertificate` dataclass (`identity.py`)

Add after `AgentBirthCertificate`:

```python
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
```

### 2. Database Schema Update (`identity.py`)

Add to `_IDENTITY_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS ship_birth_certificate (
    ship_did TEXT PRIMARY KEY,
    instance_id TEXT UNIQUE NOT NULL,
    vessel_name TEXT NOT NULL,
    commissioned_at REAL NOT NULL,
    version TEXT NOT NULL,
    certificate_hash TEXT NOT NULL,
    certificate_vc_json TEXT NOT NULL
);
```

### 3. Update `AgentIdentityRegistry` (`identity.py`)

**Add instance attributes:**

In `__init__`, add:
```python
self._ship_certificate: ShipBirthCertificate | None = None
```

**Update `start()` signature and behavior:**

Change `start()` to accept commissioning parameters:
```python
async def start(self, instance_id: str = "", vessel_name: str = "ProbOS", version: str = "") -> None:
```

After schema creation and loading existing agent certs, add:
```python
# Load or create ship birth certificate
self._ship_certificate = await self._load_or_commission_ship(
    instance_id, vessel_name, version
)
```

**Add `_load_or_commission_ship()` method** (after `start()`):

```python
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
```

**Add `_commission_ship()` method:**

```python
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

    await self._db.commit()

    logger.info(
        "SHIP COMMISSIONED: %s — DID %s — Timeline begins",
        vessel_name, ship_did,
    )
    return cert
```

**Update `_create_genesis_block()` to use ship certificate:**

Replace the existing `_create_genesis_block` method:

```python
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
```

**Add `get_ship_certificate()` accessor:**

```python
def get_ship_certificate(self) -> ShipBirthCertificate | None:
    """Return the ship's birth certificate, if commissioned."""
    return self._ship_certificate
```

### 4. Update `AgentBirthCertificate.to_verifiable_credential()` (`identity.py`)

Fix the `issuer` field — currently uses `did:probos:{instance_id}:ship` (a 4-part DID with "ship" as the UUID, which is incorrect). The issuer should be the ship DID `did:probos:{instance_id}` (3-part):

```python
"issuer": generate_ship_did(self.instance_id),
```

And fix the `verificationMethod` similarly:

```python
"verificationMethod": f"{generate_ship_did(self.instance_id)}#key-1",
```

### 5. Runtime Integration (`runtime.py`)

In `start()`, where the identity registry is started (around line 648-651), update to pass commissioning parameters:

```python
from probos.identity import AgentIdentityRegistry
self.identity_registry = AgentIdentityRegistry(data_dir=self._data_dir)

# Get instance identity for commissioning
instance_id = ""
vessel_name = "ProbOS"
version = self.config.system.version
if self.ontology:
    vi = self.ontology.get_vessel_identity()
    instance_id = vi.instance_id
    vessel_name = vi.name

await self.identity_registry.start(
    instance_id=instance_id,
    vessel_name=vessel_name,
    version=version,
)
logger.info("identity registry started")
```

### 6. API Endpoint (`api.py`)

Add after the existing `/api/identity/certificates` endpoint:

```python
@app.get("/api/identity/ship")
async def get_ship_identity() -> Any:
    """Return the ship's birth certificate and commissioning data."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    cert = runtime.identity_registry.get_ship_certificate()
    if not cert:
        return JSONResponse({"error": "Ship not commissioned"}, status_code=404)

    return {
        "ship_did": cert.ship_did,
        "instance_id": cert.instance_id,
        "vessel_name": cert.vessel_name,
        "commissioned_at": cert.commissioned_at,
        "birth_certificate": cert.to_verifiable_credential(),
    }
```

### 7. Tests (`tests/test_agent_identity.py`)

Add these test cases:

```python
# ── Ship Commissioning ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_ship_birth_certificate_creation(tmp_path):
    """ShipBirthCertificate computes hash and produces valid VC."""
    from probos.identity import ShipBirthCertificate, generate_ship_did

    cert = ShipBirthCertificate(
        ship_did=generate_ship_did("test-instance-id"),
        instance_id="test-instance-id",
        vessel_name="USS Test",
        commissioned_at=1700000000.0,
        version="0.5.0",
    )
    cert.certificate_hash = cert.compute_hash()

    assert cert.certificate_hash  # non-empty
    assert cert.ship_did == "did:probos:test-instance-id"

    vc = cert.to_verifiable_credential()
    assert "ShipBirthCertificate" in vc["type"]
    assert vc["issuer"] == "did:probos:test-instance-id"  # Self-signed
    assert vc["credentialSubject"]["id"] == "did:probos:test-instance-id"
    assert vc["credentialSubject"]["vesselName"] == "USS Test"
    assert vc["proof"]["proofValue"] == cert.certificate_hash


@pytest.mark.asyncio
async def test_ship_birth_certificate_from_dict():
    """ShipBirthCertificate round-trips through from_dict."""
    from probos.identity import ShipBirthCertificate

    cert = ShipBirthCertificate(
        ship_did="did:probos:abc123",
        instance_id="abc123",
        vessel_name="ProbOS",
        commissioned_at=1700000000.0,
        version="0.5.0",
        certificate_hash="deadbeef",
    )
    data = {
        "ship_did": cert.ship_did,
        "instance_id": cert.instance_id,
        "vessel_name": cert.vessel_name,
        "commissioned_at": cert.commissioned_at,
        "version": cert.version,
        "certificate_hash": cert.certificate_hash,
    }
    restored = ShipBirthCertificate.from_dict(data)
    assert restored.ship_did == cert.ship_did
    assert restored.commissioned_at == cert.commissioned_at


@pytest.mark.asyncio
async def test_ship_commissioning_on_first_boot(tmp_path):
    """First boot commissions the ship — creates certificate and genesis block."""
    from probos.identity import AgentIdentityRegistry

    registry = AgentIdentityRegistry(data_dir=tmp_path)
    await registry.start(
        instance_id="first-boot-id",
        vessel_name="USS FirstBoot",
        version="0.5.0",
    )

    # Ship certificate should exist
    ship_cert = registry.get_ship_certificate()
    assert ship_cert is not None
    assert ship_cert.ship_did == "did:probos:first-boot-id"
    assert ship_cert.vessel_name == "USS FirstBoot"
    assert ship_cert.version == "0.5.0"
    assert ship_cert.certificate_hash  # non-empty hash

    # Genesis block should carry ship's certificate hash and DID
    chain = await registry.export_chain()
    assert len(chain) == 0  # No blocks yet until first agent is issued

    # Issue an agent — this triggers genesis + agent block
    cert = await registry.issue_birth_certificate(
        agent_type="counselor", callsign="Troi",
        instance_id="first-boot-id", vessel_name="USS FirstBoot",
        department="medical", post_id="counselor-post",
        baseline_version="0.5.0",
    )

    chain = await registry.export_chain()
    assert len(chain) == 2  # genesis + agent

    genesis = chain[0]
    assert genesis["agent_did"] == "did:probos:first-boot-id"
    assert genesis["certificate_hash"] == ship_cert.certificate_hash

    await registry.stop()


@pytest.mark.asyncio
async def test_ship_certificate_persists_across_restarts(tmp_path):
    """Ship certificate persists — second boot loads, doesn't re-commission."""
    from probos.identity import AgentIdentityRegistry

    # First boot — commission
    reg1 = AgentIdentityRegistry(data_dir=tmp_path)
    await reg1.start(instance_id="persist-id", vessel_name="USS Persist", version="0.5.0")
    cert1 = reg1.get_ship_certificate()
    assert cert1 is not None
    ts1 = cert1.commissioned_at
    await reg1.stop()

    # Second boot — should load existing, not re-commission
    reg2 = AgentIdentityRegistry(data_dir=tmp_path)
    await reg2.start(instance_id="persist-id", vessel_name="USS Persist", version="0.5.1")
    cert2 = reg2.get_ship_certificate()
    assert cert2 is not None
    assert cert2.commissioned_at == ts1  # Same timestamp — not re-commissioned
    assert cert2.ship_did == cert1.ship_did
    await reg2.stop()


@pytest.mark.asyncio
async def test_genesis_block_backwards_compat_no_instance_id(tmp_path):
    """Without instance_id, genesis block falls back to placeholder values."""
    from probos.identity import AgentIdentityRegistry

    registry = AgentIdentityRegistry(data_dir=tmp_path)
    await registry.start()  # No instance_id — pre-commissioning mode

    assert registry.get_ship_certificate() is None

    # Issue an agent — genesis should use placeholder
    cert = await registry.issue_birth_certificate(
        agent_type="test", callsign="Test",
        instance_id="", vessel_name="ProbOS",
        department="test", post_id="test-post",
        baseline_version="0.0.0",
    )

    chain = await registry.export_chain()
    genesis = chain[0]
    assert genesis["agent_did"] == "ship"  # placeholder
    assert genesis["certificate_hash"] == "genesis"  # placeholder

    await registry.stop()


@pytest.mark.asyncio
async def test_agent_vc_issuer_uses_ship_did():
    """Agent birth certificate issuer field should be the ship DID, not ship:key."""
    from probos.identity import AgentBirthCertificate

    cert = AgentBirthCertificate(
        agent_uuid="uuid-123",
        did="did:probos:inst-1:uuid-123",
        agent_type="engineer",
        callsign="LaForge",
        instance_id="inst-1",
        vessel_name="ProbOS",
        birth_timestamp=1700000000.0,
        department="engineering",
        post_id="chief-engineer",
        baseline_version="0.5.0",
        certificate_hash="abc",
    )
    vc = cert.to_verifiable_credential()
    # Issuer should be the 3-part ship DID, not 4-part with ":ship"
    assert vc["issuer"] == "did:probos:inst-1"
    assert "#key-1" in vc["proof"]["verificationMethod"]
    assert vc["proof"]["verificationMethod"] == "did:probos:inst-1#key-1"
```

## Update `export_chain()` to include ship certificate

In `export_chain()`, the genesis block's LEFT JOIN on `birth_certificates` via `agent_did = did` won't find the ship certificate (it's in a different table). Update the method to handle this:

After the existing query loop, check if the first block is genesis and attach the ship certificate:

```python
# Attach ship certificate to genesis block if available
if blocks and blocks[0]["agent_did"] != "ship" and self._ship_certificate:
    blocks[0]["credential"] = self._ship_certificate.to_verifiable_credential()
```

## Verification

```bash
# Targeted tests
uv run pytest tests/test_agent_identity.py -v

# Full regression
uv run pytest tests/ -x -q
```

## Tracking

- Update `PROGRESS.md` status line to include AD-441b
- Update `DECISIONS.md` with AD-441b decision
- Update `docs/development/roadmap.md` — mark AD-441b complete
