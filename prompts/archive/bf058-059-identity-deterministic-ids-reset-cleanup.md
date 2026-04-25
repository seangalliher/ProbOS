# BF-058 + BF-059: Deterministic Crew IDs + Reset Identity Cleanup

**Priority:** Critical (BF-058), Medium (BF-059)
**Scope:** `runtime.py`, `__main__.py`
**Files to modify:** 2 source files, 1 test file (new)
**Estimated tests:** 8

## Context

BF-057 added a check in `_wire_agent` to look up existing birth certificates before running the naming ceremony. The check works correctly — but two underlying bugs mean it never fires for crew agents and silently blocks medical agents from ever re-naming:

### BF-058: Crew agents get random UUIDs on every boot

**Root cause:** The 7 crew agent pools (builder, architect, scout, counselor, security_officer, operations_officer, engineering_officer) are created at `runtime.py` lines 700–747 **without** passing `agent_ids=`. This means `BaseAgent.__init__` falls through to `uuid.uuid4().hex` (substrate/agent.py line 33), generating a new random ID every boot.

The BF-057 cert lookup uses `self.identity_registry.get_by_slot(agent.id)` — but since the slot ID changes on every boot, it never matches the cert from the previous boot. **Identity persistence is impossible.**

Medical agents work correctly because they use `generate_pool_ids()` (runtime.py line 778), giving them stable deterministic IDs.

**Fix:** Add `agent_ids=generate_pool_ids(agent_type, pool_name, 1)` to all 7 crew pool creation calls.

### BF-059: `probos reset` doesn't clear identity.db

**Root cause:** `_cmd_reset()` in `__main__.py` clears trust.db, episodic.db, ward_room.db, hebbian_weights.db, events.db, cognitive_journal.db, ChromaDB, KnowledgeStore — but **not** identity.db. After a reset (which is supposed to create a "new instance"), the old birth certificates survive. Because medical agents have deterministic IDs, `get_by_slot()` finds old certs and silently restores old callsigns, bypassing the naming ceremony entirely.

**Fix:** Add identity.db cleanup to `_cmd_reset()`. A reset = new ship, new crew, new identities.

---

## Implementation

### BF-058: Add deterministic IDs to crew pools

In `src/probos/runtime.py`, find the 7 crew pool creation blocks (lines ~700–747). Each looks like:

```python
# Engineering team — Builder Agent (AD-302)
if self.config.utility_agents.enabled:
    await self.create_pool(
        "builder", "builder", target_size=1,
        llm_client=self.llm_client, runtime=self,
    )
```

Change each to include deterministic IDs, following the same pattern as medical agents (line 778):

```python
# Engineering team — Builder Agent (AD-302)
if self.config.utility_agents.enabled:
    ids = generate_pool_ids("builder", "builder", 1)
    await self.create_pool(
        "builder", "builder", target_size=1,
        agent_ids=ids, llm_client=self.llm_client, runtime=self,
    )
```

Do this for ALL 7 crew pools:
1. `builder` (pool: "builder") — line ~702
2. `architect` (pool: "architect") — line ~709
3. `scout` (pool: "scout") — line ~716
4. `counselor` (pool: "counselor") — line ~723
5. `security_officer` (pool: "security_officer") — line ~730
6. `operations_officer` (pool: "operations_officer") — line ~737
7. `engineering_officer` (pool: "engineering_officer") — line ~744

The `generate_pool_ids` import already exists at line 86:
```python
from probos.substrate.identity import generate_agent_id, generate_pool_ids
```

### BF-059: Clear identity.db on reset

In `src/probos/__main__.py`, in the `_cmd_reset()` function, add identity.db cleanup. Find the section that clears other .db files (around line 596–640) and add:

```python
# Clear identity registry (AD-441) — new instance = new ship, new crew
identity_db = data_dir / "identity.db"
identity_cleared = False
if identity_db.is_file():
    identity_db.unlink()
    identity_cleared = True
```

Also add `identity_cleared` to the summary output and the console log at the end of `_cmd_reset()` so users see it was cleared. Follow the same pattern as the other DB cleanups (hebbian, ward_room, events, etc.).

Additionally, clear the `ontology/instance_id` file so the ship gets a new DID on the next boot:

```python
# Clear instance ID — new instance = new ship identity
ontology_dir = data_dir / "ontology"
instance_id_file = ontology_dir / "instance_id"
instance_id_cleared = False
if instance_id_file.is_file():
    instance_id_file.unlink()
    instance_id_cleared = True
```

Wait — check whether `probos reset` already clears the instance ID. If it does, only add identity.db. If it doesn't, add both. The instance ID should be cleared on reset because a reset creates a new instance.

---

## Tests

Create `tests/test_identity_deterministic.py`:

```python
"""BF-058 + BF-059: Deterministic crew IDs and reset identity cleanup."""
```

### BF-058 tests:

1. **test_crew_pools_use_deterministic_ids** — Mock `create_pool` and verify that all 7 crew pool calls pass `agent_ids=` with deterministic IDs (not None). Can introspect the call args.

2. **test_crew_ids_stable_across_boots** — Call `generate_pool_ids` for each crew agent type/pool combination twice. Verify the IDs are identical both times (deterministic).

3. **test_medical_ids_match_crew_pattern** — Verify medical and crew agents use the same `generate_pool_ids` function (consistency check).

4. **test_bf057_restores_identity_with_deterministic_ids** — Create a mock identity registry with a cert for the deterministic slot ID. Wire the agent. Verify BF-057 restore path fires (callsign restored from cert, naming ceremony skipped).

### BF-059 tests:

5. **test_reset_clears_identity_db** — Create a temp data dir with an identity.db file. Run the reset logic. Verify identity.db is deleted.

6. **test_reset_clears_instance_id** — Create a temp data dir with ontology/instance_id. Run reset. Verify it's deleted.

7. **test_reset_without_identity_db_no_error** — Run reset with no identity.db present. Verify no crash.

8. **test_fresh_boot_after_reset_runs_naming_ceremonies** — Integration-style: after reset clears identity.db, verify that crew agents with deterministic IDs don't find old certs and DO run naming ceremonies (cold start path).

---

## Verification

After building, manually verify:

1. **`probos reset -y`** — confirm output mentions "identity.db" cleared
2. **Start ProbOS** — ALL crew agents (including medical) should run naming ceremonies
3. **Stop ProbOS** (Ctrl+C)
4. **Restart ProbOS** (no reset) — ALL crew agents should show `BF-057: {agent_type} identity restored from birth certificate: '{name}'` log messages. No naming ceremonies should run.
5. **Verify HXI** — agent names in UI match ceremony/restored names

## Important

- Do NOT modify `identity.py`, `substrate/identity.py`, `substrate/agent.py`, or `substrate/pool.py`
- Do NOT change the `generate_pool_ids` function signature
- Do NOT change the birth certificate issuance logic
- Keep BF-057 logic exactly as-is — it's correct, it just needs stable IDs to work
- Run targeted tests: `python -m pytest tests/test_identity_deterministic.py tests/test_identity_persistence.py -x -v`
