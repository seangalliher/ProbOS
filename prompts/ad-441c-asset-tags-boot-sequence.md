# AD-441c: Asset Tags for Infrastructure/Utility + Boot Sequence Fix

## Context

The AD-441/441b code review found a **critical boot sequence issue**: builtin pool agents (system, filesystem, search, shell, http, introspect) are wired *before* the ontology loads, so they receive empty `instance_id` values — producing malformed DIDs like `did:probos::uuid-xxx`. The genesis block also gets placeholder values because the ship isn't commissioned until after these agents are born.

The architectural root cause: all agents — regardless of tier — go through the same `resolve_or_issue()` → `AgentBirthCertificate` → Identity Ledger path. But AD-398 established a three-tier agent architecture:

| Tier | Examples | Identity Needs |
|------|----------|---------------|
| Infrastructure (Ship's Computer) | system_heartbeat, file_reader, shell_command, introspect | Asset tracking only |
| Utility (bundled tools) | web_search, page_reader, weather, calculator, summarizer | Asset tracking only |
| Crew (sovereign individuals) | architect, counselor, builder, security_officer | Full sovereign identity |

The principle: *"Even microwaves get serial numbers. But a serial number is not a birth certificate."*

## Goals

1. Introduce `AssetTag` — lightweight identity for infrastructure and utility agents
2. Split `_wire_agent` identity logic: crew → `AgentBirthCertificate`, non-crew → `AssetTag`
3. Fix boot sequence so ship is commissioned before any crew birth certificates are issued
4. Asset tags do NOT go on the Identity Ledger (no ceremony, no blockchain)
5. Asset tags do NOT require `instance_id` — they are local inventory, not sovereign identity
6. Existing `_is_crew_agent()` and ontology `get_crew_agent_types()` determine the split

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/identity.py` | Add `AssetTag` dataclass, `asset_tags` DB table, `issue_asset_tag()`, `resolve_or_issue_asset_tag()`, `get_asset_tags()` |
| `src/probos/runtime.py` | Split identity wiring in `_wire_agent`, reorder boot sequence |
| `src/probos/api.py` | Add `GET /api/identity/assets` endpoint |
| `tests/test_agent_identity.py` | Add asset tag tests |

## Implementation

### 1. `AssetTag` dataclass (`identity.py`)

Add after `ShipBirthCertificate`:

```python
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
```

### 2. Database Schema (`identity.py`)

Add to `_IDENTITY_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS asset_tags (
    asset_uuid TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    slot_id TEXT UNIQUE NOT NULL,
    installed_at REAL NOT NULL,
    pool_name TEXT NOT NULL,
    tier TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_asset_type ON asset_tags(asset_type);
CREATE INDEX IF NOT EXISTS idx_asset_slot ON asset_tags(slot_id);
```

### 3. Registry Methods (`identity.py` — `AgentIdentityRegistry`)

Add new instance attributes in `__init__`:
```python
self._asset_cache: dict[str, AssetTag] = {}  # slot_id -> AssetTag
```

Add to `start()`, after loading slot_mappings:
```python
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

logger.info("Identity registry loaded %d certificates, %d asset tags",
            len(self._uuid_cache), len(self._asset_cache))
```

Add methods:

```python
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
```

### 4. Runtime Boot Sequence Fix (`runtime.py`)

**Problem:** Lines 647-669 create pool agents before ontology loads (line 1389). When `_wire_agent` runs for these agents, `self.ontology` is `None`, so `instance_id=""`.

**Fix `_wire_agent` (around line 3935):**

Replace the current identity block with a two-path approach:

```python
# AD-441c: Two-tier identity — crew get birth certificates, others get asset tags
if self.identity_registry:
    try:
        if self._is_crew_agent(agent):
            # Sovereign identity — requires ship to be commissioned
            instance_id = ""
            vessel_name = "ProbOS"
            if self.ontology:
                vi = self.ontology.get_vessel_identity()
                instance_id = vi.instance_id
                vessel_name = vi.name

            if not instance_id:
                # Ship not commissioned yet — defer identity until commissioning
                logger.debug("Identity deferred for crew agent %s — ship not yet commissioned", agent.id)
            else:
                dept = ""
                post_id = ""
                if self.ontology:
                    dept = self.ontology.get_agent_department(agent.agent_type) or ""
                    post = self.ontology.get_post_for_agent(agent.agent_type)
                    post_id = post.id if post else ""
                if not dept:
                    from probos.cognitive.standing_orders import get_department as _get_dept
                    dept = _get_dept(agent.agent_type) or "unassigned"

                _callsign = getattr(agent, 'callsign', '') or agent.agent_type
                baseline = self.config.system.version

                cert = await self.identity_registry.resolve_or_issue(
                    slot_id=agent.id,
                    agent_type=agent.agent_type,
                    callsign=_callsign,
                    instance_id=instance_id,
                    vessel_name=vessel_name,
                    department=dept,
                    post_id=post_id,
                    baseline_version=baseline,
                )
                agent.sovereign_id = cert.agent_uuid
                agent.did = cert.did
        else:
            # Asset identity — lightweight tracking, no DID needed
            pool_name = agent.pool or "unknown"
            # Determine tier
            _infra_pools = {"system", "filesystem", "filesystem_writers", "directory",
                           "search", "shell", "http", "introspect",
                           "medical_vitals", "red_team", "system_qa"}
            tier = "infrastructure" if pool_name in _infra_pools else "utility"

            tag = await self.identity_registry.resolve_or_issue_asset_tag(
                slot_id=agent.id,
                asset_type=agent.agent_type,
                pool_name=pool_name,
                tier=tier,
            )
            agent.sovereign_id = tag.asset_uuid  # tracking UUID, not sovereign
            agent.did = ""  # No DID for assets
    except Exception as e:
        logger.debug("Identity resolution skipped for %s: %s", agent.id, e)
```

**Add post-commissioning crew identity sweep (after line 1404):**

After the ship is commissioned (around the AD-441b block at line 1396-1404), add a sweep to issue birth certificates for any crew agents that were deferred:

```python
# --- Ship Commissioning (AD-441b) ---
# Now that ontology is loaded, commission the ship's identity
if self.ontology and self.identity_registry:
    vi = self.ontology.get_vessel_identity()
    await self.identity_registry.start(
        instance_id=vi.instance_id,
        vessel_name=vi.name,
        version=self.config.system.version,
    )

    # AD-441c: Issue deferred crew birth certificates now that ship is commissioned
    for agent in self.registry.all():
        if self._is_crew_agent(agent) and not getattr(agent, 'did', ''):
            try:
                dept = self.ontology.get_agent_department(agent.agent_type) or ""
                post = self.ontology.get_post_for_agent(agent.agent_type)
                post_id = post.id if post else ""
                if not dept:
                    from probos.cognitive.standing_orders import get_department as _get_dept
                    dept = _get_dept(agent.agent_type) or "unassigned"

                _callsign = getattr(agent, 'callsign', '') or agent.agent_type
                cert = await self.identity_registry.resolve_or_issue(
                    slot_id=agent.id,
                    agent_type=agent.agent_type,
                    callsign=_callsign,
                    instance_id=vi.instance_id,
                    vessel_name=vi.name,
                    department=dept,
                    post_id=post.id if post else "",
                    baseline_version=self.config.system.version,
                )
                agent.sovereign_id = cert.agent_uuid
                agent.did = cert.did
            except Exception as e:
                logger.debug("Deferred identity skipped for %s: %s", agent.id, e)
```

### 5. API Endpoint (`api.py`)

Add after the `GET /api/identity/certificates` endpoint:

```python
@app.get("/api/identity/assets")
async def list_asset_tags() -> Any:
    """Return all asset tags for infrastructure and utility agents."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    tags = runtime.identity_registry.get_asset_tags()
    return {
        "count": len(tags),
        "assets": [t.to_dict() for t in tags],
    }
```

### 6. Tests (`tests/test_agent_identity.py`)

Add a new test class:

```python
class TestAssetTags:
    """Asset tags for infrastructure and utility agents."""

    @pytest.mark.asyncio
    async def test_issue_asset_tag(self, tmp_path):
        """Asset tag is issued and cached."""
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start()

        tag = await reg.issue_asset_tag(
            asset_type="file_reader",
            slot_id="file_reader_filesystem_0_abc123",
            pool_name="filesystem",
            tier="infrastructure",
        )

        assert tag.asset_uuid  # non-empty UUID
        assert tag.asset_type == "file_reader"
        assert tag.tier == "infrastructure"
        assert tag.pool_name == "filesystem"

        # Retrievable by slot
        found = reg.get_asset_by_slot("file_reader_filesystem_0_abc123")
        assert found is not None
        assert found.asset_uuid == tag.asset_uuid

        await reg.stop()

    @pytest.mark.asyncio
    async def test_asset_tag_not_on_ledger(self, tmp_path):
        """Asset tags do NOT create ledger entries."""
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start()

        await reg.issue_asset_tag(
            asset_type="shell_command",
            slot_id="shell_command_shell_0_def456",
            pool_name="shell",
            tier="infrastructure",
        )

        chain = await reg.export_chain()
        assert len(chain) == 0  # No ledger entries for asset tags

        await reg.stop()

    @pytest.mark.asyncio
    async def test_resolve_or_issue_asset_tag_idempotent(self, tmp_path):
        """Calling resolve_or_issue twice returns same tag."""
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start()

        tag1 = await reg.resolve_or_issue_asset_tag(
            slot_id="heartbeat_0",
            asset_type="system_heartbeat",
            pool_name="system",
        )
        tag2 = await reg.resolve_or_issue_asset_tag(
            slot_id="heartbeat_0",
            asset_type="system_heartbeat",
            pool_name="system",
        )

        assert tag1.asset_uuid == tag2.asset_uuid

        await reg.stop()

    @pytest.mark.asyncio
    async def test_asset_tag_persists_across_restarts(self, tmp_path):
        """Asset tags persist in DB and reload on restart."""
        from probos.identity import AgentIdentityRegistry

        reg1 = AgentIdentityRegistry(data_dir=tmp_path)
        await reg1.start()
        tag = await reg1.issue_asset_tag(
            asset_type="http_fetch", slot_id="http_0",
            pool_name="http", tier="infrastructure",
        )
        await reg1.stop()

        reg2 = AgentIdentityRegistry(data_dir=tmp_path)
        await reg2.start()
        found = reg2.get_asset_by_slot("http_0")
        assert found is not None
        assert found.asset_uuid == tag.asset_uuid
        await reg2.stop()

    @pytest.mark.asyncio
    async def test_asset_tag_to_dict_round_trip(self):
        """AssetTag round-trips through to_dict/from_dict."""
        from probos.identity import AssetTag
        tag = AssetTag(
            asset_uuid="uuid-1", asset_type="shell_command",
            slot_id="shell_0", installed_at=1700000000.0,
            pool_name="shell", tier="infrastructure",
        )
        data = tag.to_dict()
        restored = AssetTag.from_dict(data)
        assert restored.asset_uuid == tag.asset_uuid
        assert restored.tier == tag.tier

    @pytest.mark.asyncio
    async def test_get_all_asset_tags(self, tmp_path):
        """get_asset_tags() returns all issued tags."""
        from probos.identity import AgentIdentityRegistry
        reg = AgentIdentityRegistry(data_dir=tmp_path)
        await reg.start()

        await reg.issue_asset_tag("type_a", "slot_a", "pool_a", "infrastructure")
        await reg.issue_asset_tag("type_b", "slot_b", "pool_b", "utility")

        tags = reg.get_asset_tags()
        assert len(tags) == 2
        types = {t.asset_type for t in tags}
        assert types == {"type_a", "type_b"}

        await reg.stop()
```

### 7. Update `cognitive_agent.py` and `proactive.py`

These files use `getattr(self, 'sovereign_id', None) or self.id` for memory lookups. This now works correctly for both:
- **Crew agents**: `sovereign_id` = permanent UUID from birth certificate
- **Non-crew agents**: `sovereign_id` = asset UUID from tag (still unique, but not sovereign)

No code changes needed — the pattern is compatible.

## Verification

```bash
# Targeted tests
uv run pytest tests/test_agent_identity.py -v

# Full regression
uv run pytest tests/ -x -q
```

## Tracking

- Update `PROGRESS.md` with AD-441c completion
- Update `DECISIONS.md` with AD-441c decision
- Update `docs/development/roadmap.md` — mark AD-441c complete
