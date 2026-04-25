# BF-040: Identity System Hardening — All Review Findings

## Context

Post-AD-441/441b code review identified multiple quality issues across identity.py. This BF addresses every finding not covered by AD-441c (Asset Tags + Boot Sequence Fix). All items below must be resolved before the first reset/commissioning.

## Findings Addressed

| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| C-2 | CRITICAL | `export_chain()` genesis credential attachment logic is inverted | Fix condition to match ship DID |
| H-1 | HIGH | No input validation on `generate_did()`, `generate_ship_did()`, `parse_did()`, `issue_birth_certificate()` | Add guards |
| H-2 | HIGH | Ledger race condition — concurrent `_append_to_ledger()` can break chain | Add `asyncio.Lock` |
| H-3 | HIGH | SQLite foreign keys not enforced (`PRAGMA foreign_keys` never set) | Add pragma |
| M-1 | MEDIUM | `verify_chain()` doesn't validate genesis `previous_hash` is `"0"*64` | Add assertion |
| M-2 | MEDIUM | DB rows loaded by positional index, not column name | Use explicit SELECT columns (already done) — add comments noting column order dependency |
| M-3 | MEDIUM | `_commission_ship` doesn't eagerly create genesis block | Create genesis during commissioning |
| M-4 | MEDIUM | `_cache` dict declared but never used | Remove |
| M-5 | MEDIUM | `proof.type: "Sha256Hash2024"` is non-standard | Add docstring documenting this is intentional for internal use |
| L-1 | LOW | `INSERT OR REPLACE` on `slot_mappings` could orphan old mappings | Add warning log |
| L-2 | LOW | Block hash uses colon-delimited string vs cert hash uses JSON | Document in code comment |
| L-3 | LOW | Float representation in hash could vary across Python versions | Document in code comment |
| L-4 | LOW | No index on `slot_mappings.agent_uuid` | Add index |

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/identity.py` | All fixes below |
| `tests/test_agent_identity.py` | Add/update tests for new validation, race condition, genesis creation |

## Implementation

### 1. Fix `export_chain()` credential attachment (C-2)

**File:** `identity.py`, around line 550-552

**Current (broken):**
```python
if blocks and blocks[0]["agent_did"] != "ship" and self._ship_certificate:
    blocks[0]["credential"] = self._ship_certificate.to_verifiable_credential()
```

The condition `!= "ship"` means: only attach when genesis is NOT a placeholder. But when a ship certificate exists AND the genesis was created properly (by AD-441c), the `agent_did` is the ship DID (e.g., `did:probos:uuid-123`), which is indeed `!= "ship"`. So the logic actually works correctly when AD-441c is in place. However, it should also handle the case where genesis was created WITH the ship certificate. Simplify:

**Fix:**
```python
# Attach ship certificate to genesis block if available
# The LEFT JOIN on birth_certificates won't find the ship cert (different table)
# so we attach it explicitly when it exists
if blocks and self._ship_certificate and not blocks[0].get("credential"):
    blocks[0]["credential"] = self._ship_certificate.to_verifiable_credential()
```

### 2. Input Validation (H-1)

**File:** `identity.py`

**Add validation to `generate_did()`:**
```python
def generate_did(instance_id: str, agent_uuid: str) -> str:
    """Generate a W3C DID for a ProbOS agent."""
    if not instance_id or not agent_uuid:
        raise ValueError(f"DID generation requires non-empty instance_id and agent_uuid, got '{instance_id}', '{agent_uuid}'")
    return f"did:{DID_METHOD}:{instance_id}:{agent_uuid}"
```

**Add validation to `generate_ship_did()`:**
```python
def generate_ship_did(instance_id: str) -> str:
    """Generate a W3C DID for a ProbOS instance."""
    if not instance_id:
        raise ValueError("Ship DID generation requires non-empty instance_id")
    return f"did:{DID_METHOD}:{instance_id}"
```

**Add `None` guard to `parse_did()`:**
```python
def parse_did(did: str) -> dict[str, str] | None:
    if not did or not isinstance(did, str):
        return None
    # ... rest unchanged
```

**Add validation to `issue_birth_certificate()`** — at the top of the method:
```python
if not agent_type:
    raise ValueError("agent_type is required for birth certificate issuance")
if not instance_id:
    raise ValueError("instance_id is required — ship must be commissioned before issuing birth certificates")
if not callsign:
    raise ValueError("callsign is required for birth certificate issuance")
```

### 3. Ledger Race Condition Fix (H-2)

**File:** `identity.py`

**Add lock in `__init__`:**
```python
import asyncio

def __init__(self, data_dir: Path) -> None:
    # ... existing attributes ...
    self._ledger_lock = asyncio.Lock()
```

**Wrap `_append_to_ledger()` call in lock:**

In `issue_birth_certificate()`, change the ledger call:
```python
# Append to Identity Ledger (blockchain) — serialized to prevent index conflicts
async with self._ledger_lock:
    await self._append_to_ledger(cert.certificate_hash, cert.did)
```

### 4. Enable SQLite Foreign Keys (H-3)

**File:** `identity.py`

In `start()`, after opening the DB connection and before executing the schema:
```python
await self._db.execute("PRAGMA foreign_keys = ON")
```

### 5. Validate Genesis `previous_hash` in `verify_chain()` (M-1)

**File:** `identity.py`

In `verify_chain()`, after the hash verification for genesis (where `i == 0`):
```python
# Verify genesis block has expected previous_hash
if i == 0:
    expected_prev = "0" * 64
    if block.previous_hash != expected_prev:
        return False, f"Genesis block: invalid previous_hash (expected all zeros)"
```

### 6. Document Column Order Dependency (M-2)

**File:** `identity.py`

Add a comment above each `SELECT *` or positional row access:
```python
# Column order: agent_uuid(0), did(1), agent_type(2), callsign(3),
# instance_id(4), vessel_name(5), birth_timestamp(6), department(7),
# post_id(8), baseline_version(9), certificate_hash(10), certificate_vc_json(11)
```

Do the same for ship_birth_certificate and identity_ledger selects.

### 7. Eager Genesis Block Creation (M-3)

**File:** `identity.py`

In `_commission_ship()`, after persisting the ship certificate and before the commit, create the genesis block:

```python
# Create genesis block immediately — the ship's birth is block 0
await self._create_genesis_block()

await self._db.commit()
```

This ensures the ledger is never empty when the ship is commissioned. The `_create_genesis_block()` method already uses `INSERT OR IGNORE`, so it's safe if called multiple times.

### 8. Remove Dead `_cache` Dict (M-4)

**File:** `identity.py`

Remove from `__init__`:
```python
self._cache: dict[str, AgentBirthCertificate] = {}  # agent_type -> cert (for crew singletons)
```

### 9. Document Proof Type Rationale (M-5)

**File:** `identity.py`

Add to the module docstring (top of file), after the existing description:

```python
"""
...
Proof Type: Uses 'Sha256Hash2024' — a content integrity hash, not a
cryptographic signature. This is intentional: ProbOS identity is self-sovereign
within the instance, not designed for external VC verifier interop (yet).
The hash proves immutability, not third-party authenticity.
Future: Replace with Ed25519Signature2020 when federation requires it.
"""
```

### 10. Warn on Slot Mapping Overwrite (L-1)

**File:** `identity.py`

In `issue_birth_certificate()`, before the `INSERT OR REPLACE` on slot_mappings:
```python
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
```

### 11. Document Hash Format Difference (L-2)

**File:** `identity.py`

Add comment to `LedgerBlock.compute_hash()`:
```python
def compute_hash(self) -> str:
    """Compute this block's hash from its contents.

    Uses colon-delimited string format (vs JSON for certificates).
    Both are deterministic within a Python version. The simpler format
    is intentional — block hashes are internal chain integrity checks,
    not externally verifiable credentials.
    """
```

### 12. Document Float Representation (L-3)

**File:** `identity.py`

Add comment to `AgentBirthCertificate.compute_hash()`:
```python
def compute_hash(self) -> str:
    """Compute the SHA-256 hash of this certificate's content fields.

    Note: birth_timestamp is a float. Python's json.dumps uses repr-style
    float formatting which is consistent within a CPython major version.
    For cross-platform federation hash verification, timestamps may need
    to be normalized to fixed-precision strings in a future version.
    """
```

### 13. Add Index on `slot_mappings.agent_uuid` (L-4)

**File:** `identity.py`

Add to `_IDENTITY_SCHEMA`:
```sql
CREATE INDEX IF NOT EXISTS idx_slot_agent ON slot_mappings(agent_uuid);
```

## Tests

Add/update these tests in `tests/test_agent_identity.py`:

```python
# ── Input Validation ────────────────────────────────────────────

class TestInputValidation:

    def test_generate_did_rejects_empty_instance_id(self):
        from probos.identity import generate_did
        with pytest.raises(ValueError, match="instance_id"):
            generate_did("", "uuid-123")

    def test_generate_did_rejects_empty_agent_uuid(self):
        from probos.identity import generate_did
        with pytest.raises(ValueError, match="agent_uuid"):
            generate_did("inst-1", "")

    def test_generate_ship_did_rejects_empty(self):
        from probos.identity import generate_ship_did
        with pytest.raises(ValueError, match="instance_id"):
            generate_ship_did("")

    def test_parse_did_returns_none_for_none(self):
        from probos.identity import parse_did
        assert parse_did(None) is None

    def test_parse_did_returns_none_for_empty(self):
        from probos.identity import parse_did
        assert parse_did("") is None

    @pytest.mark.asyncio
    async def test_issue_rejects_empty_instance_id(self, tmp_path):
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start()
        with pytest.raises(ValueError, match="instance_id"):
            await reg.issue_birth_certificate(
                agent_type="test", callsign="Test",
                instance_id="", vessel_name="ProbOS",
                department="test", post_id="test-post",
                baseline_version="0.0.0",
            )
        await reg.stop()

    @pytest.mark.asyncio
    async def test_issue_rejects_empty_agent_type(self, tmp_path):
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start()
        with pytest.raises(ValueError, match="agent_type"):
            await reg.issue_birth_certificate(
                agent_type="", callsign="Test",
                instance_id="inst-1", vessel_name="ProbOS",
                department="test", post_id="test-post",
                baseline_version="0.0.0",
            )
        await reg.stop()


# ── Genesis Block Eager Creation ────────────────────────────────

class TestEagerGenesis:

    @pytest.mark.asyncio
    async def test_commissioning_creates_genesis_immediately(self, tmp_path):
        """Genesis block exists right after commissioning, before any agent is born."""
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start(instance_id="eager-id", vessel_name="USS Eager", version="0.5.0")

        chain = await reg.export_chain()
        assert len(chain) == 1  # Genesis exists immediately
        assert chain[0]["agent_did"] == "did:probos:eager-id"
        assert chain[0]["certificate_hash"] != "genesis"  # Real hash, not placeholder

        await reg.stop()


# ── Chain Verification ──────────────────────────────────────────

class TestChainVerificationHardening:

    @pytest.mark.asyncio
    async def test_verify_rejects_tampered_genesis_previous_hash(self, tmp_path):
        """Tampered genesis previous_hash should fail verification."""
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start(instance_id="tamper-test", vessel_name="USS Tamper", version="0.5.0")

        # Tamper with genesis previous_hash
        await reg._db.execute(
            "UPDATE identity_ledger SET previous_hash = 'tampered' WHERE block_index = 0"
        )
        await reg._db.commit()

        valid, message = await reg.verify_chain()
        assert not valid
        assert "previous_hash" in message or "hash mismatch" in message

        await reg.stop()
```

**Update existing tests that pass empty `instance_id`:**

The input validation will break tests that call `generate_did("", ...)` or `issue_birth_certificate(instance_id="")`. Update these tests:

- `test_genesis_block_backwards_compat_no_instance_id` — this test intentionally uses empty `instance_id`. It should now expect a `ValueError` OR be removed since AD-441c makes this scenario impossible (infrastructure agents get asset tags, crew agents require `instance_id`). **Remove the test** — the backwards compat path is no longer needed.

- Any other tests using empty `instance_id` in `generate_did()` — update to use a real value.

## Verification

```bash
# Targeted tests
uv run pytest tests/test_agent_identity.py -v

# Full regression
uv run pytest tests/ -x -q
```

## Tracking

- Update `PROGRESS.md` with BF-040 completion
- Update `docs/development/roadmap.md` — add BF-040 to bug tracker, mark complete
