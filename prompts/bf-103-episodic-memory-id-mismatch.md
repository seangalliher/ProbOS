# BF-103: Episodic Memory Agent ID Mismatch — Orphaned Episodes

| Field | Value |
|-------|-------|
| **Ticket** | BF-103 |
| **Priority** | Critical |
| **Scope** | OSS (`src/probos/cognitive/episodic.py`, `src/probos/ward_room/`, `src/probos/dream_adapter.py`, `src/probos/runtime.py`, `src/probos/startup/`) |
| **Principles Compliance** | DRY (single ID resolution helper), Fail Fast (log if identity lookup fails), Defense in Depth (validate ID type at storage boundary) |
| **Dependencies** | AD-441 (Persistent Agent Identity, COMPLETE) |

---

## Bug Description

**Symptom:** After a normal restart (NOT reset), agents report "my episodic memory appears to have been cleared" and receive the system-injected message "You have no stored episodic memories yet." ChromaDB contains 843+ episodes on disk, but agents see zero.

**Root Cause:** Two different agent ID types exist:
- **Slot ID** (deterministic): `security_agent_0_67c601cb` — derived from `sha256(type:pool:index)`
- **Sovereign ID** (persistent UUID): `a1b2c3d4e5f6...` — from identity registry (`identity.db`)

**Some code paths store episodes with slot IDs, others with sovereign IDs. Recall always uses sovereign ID. Episodes stored under slot IDs are invisible to recall.**

### Storage Paths (what goes into `agent_ids_json`):

| Code Path | File:Line | Stores | ID Type |
|-----------|-----------|--------|---------|
| Cognitive agent episode creation | `cognitive_agent.py:2166` | `sovereign_id or self.id` | sovereign_id ✓ |
| Proactive episode creation | `proactive.py:489,642` | `sovereign_id or agent.id` | sovereign_id ✓ |
| Ward Room message episodes | `ward_room/messages.py:156` | `author_id` | **slot ID ✗** |
| Ward Room thread episodes | `ward_room/threads.py:355` | `author_id` | **slot ID ✗** |
| Dream adapter episodes | `dream_adapter.py:315-317` | `r.get("agent_id")` | **slot ID ✗** |
| Runtime QA episodes | `runtime.py:2861-2863` | `a.id` | **slot ID ✗** |

### Recall Paths (what ID is used for lookup):

| Code Path | File:Line | Uses |
|-----------|-----------|------|
| Cognitive agent recall | `cognitive_agent.py:2055` | `sovereign_id` |
| Proactive context gather | `proactive.py:701` | `sovereign_id` |
| Self-monitoring count | `proactive.py:1015-1029` | `sovereign_id` |

**Result:** Episodes from Ward Room, dreams, and runtime are orphaned — stored with slot IDs but queried by sovereign IDs. Agents are told they have zero memories despite hundreds existing in ChromaDB.

---

## Fix Strategy: Normalize + Migrate (No Dual Lookup)

Three-part fix with zero technical debt:

1. **Normalize all storage paths** to use sovereign_id
2. **One-time startup migration** to remap existing episodes from slot IDs to sovereign IDs
3. **No dual lookup** — after migration, all episodes use sovereign_id consistently

---

## Deliverables

### D1: ID Resolution Helper (`src/probos/cognitive/episodic.py`)

Add a module-level or utility function that resolves any agent reference to its sovereign_id:

```python
def resolve_sovereign_id(agent: Any) -> str:
    """Resolve an agent's sovereign_id, falling back to agent.id if unavailable.

    This is the ONLY correct way to get an agent ID for episode storage.
    All episode agent_ids_json entries MUST use sovereign_id.
    """
    return getattr(agent, 'sovereign_id', None) or getattr(agent, 'id', str(agent))
```

Also add a reverse-lookup helper that can map a slot_id to a sovereign_id using the identity registry:

```python
def resolve_sovereign_id_from_slot(slot_id: str, identity_registry: Any) -> str:
    """Resolve a slot ID to a sovereign ID via the identity registry.

    Used during episode storage when only a slot_id string is available
    (not an agent object). Returns slot_id unchanged if no mapping found.
    """
    if not identity_registry:
        return slot_id
    cert = identity_registry.get_by_slot(slot_id)
    if cert:
        return cert.agent_uuid
    return slot_id
```

These helpers enforce DRY — one place to resolve IDs, used by all storage paths.

### D2: Fix Storage Paths (4 files)

**D2a: `src/probos/ward_room/messages.py` (~line 156)**

Where `author_id` is stored in episode `agent_ids`, resolve to sovereign_id. The Ward Room message handler needs access to the identity registry (or the agent object with sovereign_id). Find where the episode is created and replace the raw `author_id` with the resolved sovereign_id.

The cleanest approach: the Ward Room already has access to agent objects or the runtime. Use `resolve_sovereign_id_from_slot()` with the identity registry to map the `author_id` (slot ID) to sovereign_id before storing.

If the identity registry is not available in this context, thread it through. The Ward Room is constructed during startup and can receive a reference to the identity registry.

**D2b: `src/probos/ward_room/threads.py` (~line 355)**

Same pattern as D2a. Where `author_id` goes into episode `agent_ids`, resolve via identity registry first.

**D2c: `src/probos/dream_adapter.py` (~line 315-317)**

Where `r.get("agent_id")` is used for episode agent_ids, the value is a slot ID from execution results. Resolve to sovereign_id via identity registry before storing.

The dream adapter is constructed during startup and should already have access to the runtime or identity registry. If not, add the identity registry as a constructor parameter.

**D2d: `src/probos/runtime.py` (~line 2861-2863)**

Where `a.id` is used for healthy agents in pool episodes, replace with `resolve_sovereign_id(a)` to get the sovereign_id.

### D3: Startup Migration (`src/probos/startup/cognitive_services.py` or new file)

**One-time migration** that runs during startup, after both the identity registry and episodic memory are initialized:

```python
async def migrate_episode_agent_ids(
    episodic_memory: EpisodicMemory,
    identity_registry: AgentIdentityRegistry,
) -> int:
    """Migrate episode agent_ids from slot IDs to sovereign IDs.

    Scans all episodes in ChromaDB. For each agent_id in agent_ids_json,
    checks if it's a slot ID with a known sovereign_id mapping. If so,
    replaces the slot ID with the sovereign_id.

    Returns the number of episodes updated.
    """
```

Implementation:
1. Get all episodes from ChromaDB collection (use `_collection.get()` with no filter)
2. For each episode's metadata:
   - Parse `agent_ids_json`
   - For each agent_id, call `identity_registry.get_by_slot(agent_id)`
   - If a mapping exists, replace slot_id with `cert.agent_uuid`
   - If ANY IDs changed, update the episode's metadata in ChromaDB via `_collection.update()`
3. Log summary: `"Migrated {n} episodes from slot IDs to sovereign IDs"`
4. If no episodes need migration (all already use sovereign_ids), log and return 0

**Idempotency:** The migration is safe to run multiple times — if an ID is already a sovereign_id (no slot mapping found), it's left unchanged. If the sovereign_id IS in the slot mapping table (because it happens to also be a slot for some other agent), the `get_by_slot()` would only match actual slot-format IDs.

**Performance:** One full scan of ChromaDB episodes + N identity lookups (in-memory cache). Should complete in under a second for 843 episodes. Log the duration.

**Placement:** After `episodic_memory.start()` and `identity_registry.start()` in the startup sequence. Before any agents are activated. Guard with a try/except — if migration fails, log the error but don't block startup (degrade, don't crash).

### D4: Wire Migration into Startup

In `src/probos/startup/cognitive_services.py` (or whichever startup phase has both episodic_memory and identity_registry initialized):

```python
# BF-103: Migrate episode agent_ids from slot IDs to sovereign IDs
from probos.cognitive.episodic import migrate_episode_agent_ids  # or wherever it lives

try:
    migrated = await migrate_episode_agent_ids(episodic_memory, identity_registry)
    if migrated > 0:
        logger.info("BF-103: Migrated %d episodes to sovereign IDs", migrated)
except Exception:
    logger.warning("BF-103: Episode ID migration failed (non-fatal)", exc_info=True)
```

The migration runs every startup but is effectively a no-op after the first successful run (all IDs already mapped). If this is a concern, add a flag file (`~/.probos/.episode_ids_migrated`) to skip on subsequent starts. But given the performance is negligible, running every time is acceptable and more resilient.

### D5: Ward Room Identity Registry Wiring

If the Ward Room does not currently have access to the identity registry, wire it in:

- Add `identity_registry` parameter to Ward Room constructor (or to the message/thread handler that creates episodes)
- Pass the identity registry during startup construction
- This enables D2a and D2b to resolve slot IDs to sovereign IDs

Check the existing Ward Room constructor in `src/probos/ward_room/` to determine the minimal wiring needed. If the Ward Room already has access to the runtime or a service locator that provides the identity registry, use that path instead of adding a new constructor parameter.

---

## Scope Exclusions

| Excluded Item | Reason |
|---------------|--------|
| Dual lookup fallback in recall methods | Not needed — migration converts all existing episodes |
| HXI chat history API (`routers/agents.py`) | Uses slot ID for URL routing, which is correct for the API — internal recall uses sovereign_id |
| Episode re-embedding after ID migration | IDs are metadata, not part of the embedding vector — no re-embedding needed |
| `MemoryConfig.collection_name` dead field | Minor cleanup, not related to this bug — track separately if desired |

---

## Test Requirements

### File: `tests/test_bf103_episode_id_mismatch.py` (NEW — 16 tests)

**D1: ID Resolution (3 tests)**

1. `test_resolve_sovereign_id_prefers_sovereign` — Agent with both `sovereign_id` and `id` returns sovereign_id
2. `test_resolve_sovereign_id_falls_back_to_id` — Agent without sovereign_id returns agent.id
3. `test_resolve_sovereign_id_from_slot_maps_correctly` — Slot ID with registry mapping returns sovereign UUID; unknown slot returns slot unchanged

**D2: Storage Path Fixes (4 tests)**

4. `test_ward_room_message_episode_uses_sovereign_id` — Episode created from Ward Room message stores sovereign_id in agent_ids_json, not author_id slot ID
5. `test_ward_room_thread_episode_uses_sovereign_id` — Episode created from Ward Room thread stores sovereign_id in agent_ids_json
6. `test_dream_adapter_episode_uses_sovereign_id` — Episode created by dream adapter stores sovereign_id, not execution result slot ID
7. `test_runtime_episode_uses_sovereign_id` — Runtime QA episode stores sovereign_id, not a.id

**D3: Migration (6 tests)**

8. `test_migration_converts_slot_ids_to_sovereign` — Episodes with slot IDs in agent_ids_json are updated to sovereign IDs after migration
9. `test_migration_leaves_sovereign_ids_unchanged` — Episodes already using sovereign IDs are not modified
10. `test_migration_handles_mixed_ids` — Episode with both slot ID and sovereign ID in agent_ids only converts the slot ID
11. `test_migration_returns_count` — Returns correct count of migrated episodes
12. `test_migration_idempotent` — Running migration twice produces same result (second run returns 0)
13. `test_migration_handles_empty_collection` — No episodes → returns 0, no errors

**D4/D5: Wiring (3 tests)**

14. `test_startup_migration_runs_after_identity_registry` — Migration executes in correct startup phase
15. `test_startup_migration_failure_non_fatal` — Migration exception is caught; startup continues
16. `test_ward_room_has_identity_registry_access` — Ward Room can resolve slot IDs to sovereign IDs

---

## Validation Checklist

- [ ] ALL four storage paths (D2a-D2d) use sovereign_id, verified by dedicated tests
- [ ] Migration converts existing slot-ID episodes to sovereign IDs on startup
- [ ] Migration is idempotent (safe to run multiple times)
- [ ] Migration failure does not block startup (log-and-degrade)
- [ ] No dual lookup code exists — clean single-ID path
- [ ] `resolve_sovereign_id()` helper is used consistently (DRY)
- [ ] Ward Room has access to identity registry for ID resolution
- [ ] All 16 tests pass
- [ ] Existing episodic memory tests still pass (regression)
- [ ] After fix: `count_for_agent(sovereign_id)` returns correct non-zero count for agents with existing episodes

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `src/probos/cognitive/episodic.py` | EDIT | Add `resolve_sovereign_id()` and `resolve_sovereign_id_from_slot()` helpers, add `migrate_episode_agent_ids()` function |
| `src/probos/ward_room/messages.py` | EDIT | Resolve author_id to sovereign_id before episode storage |
| `src/probos/ward_room/threads.py` | EDIT | Resolve author_id to sovereign_id before episode storage |
| `src/probos/dream_adapter.py` | EDIT | Resolve execution result agent_id to sovereign_id |
| `src/probos/runtime.py` | EDIT | Replace `a.id` with `resolve_sovereign_id(a)` |
| `src/probos/startup/cognitive_services.py` | EDIT | Wire migration after episodic_memory + identity_registry init |
| `src/probos/ward_room/__init__.py` or constructor | EDIT | Wire identity_registry into Ward Room (if not already accessible) |
| `tests/test_bf103_episode_id_mismatch.py` | **NEW** | 16 tests |
