# Phase 14c — Persistent Agent Identity

## Phase Goal

Fix the warm boot trust/routing orphan bug and give agents persistent identity across restarts. Currently, `BaseAgent.__init__` generates a random `uuid4()` on every instantiation. When ProbOS restarts, pools are recreated with new agent instances bearing new IDs. All per-agent learned state — trust scores (keyed by `agent_id` in TrustNetwork), Hebbian routing weights (keyed by `(source_id, target_id)` in HebbianRouter), confidence history — is orphaned. An agent that earned Beta(20, 2) trust over many successful interactions restarts at probationary Beta(1, 3). All routing learning is lost.

After this phase: the same agent type in the same pool at the same position gets the same ID across restarts. Trust, routing weights, and confidence reconnect to the correct agent instances on warm boot. The system remembers its agents as individuals, not just as types.

---

## Architecture

Three components:

1. **Deterministic agent IDs** — derived from stable attributes, not random UUIDs. The ID formula is based on deployment topology (agent type, pool name, instance index), not implementation details. Same formula always produces the same ID.

2. **Agent manifest** — a Git-backed artifact in KnowledgeStore that records the full agent roster. On warm boot, the manifest is the source of truth for which agents should exist. Pools are recreated to match the manifest.

3. **Trust and routing reconnection** — the warm boot sequence loads trust snapshots and Hebbian weights, then recreates agents with matching deterministic IDs so the restored records key directly into the restored agents.

**What this fixes:** The `_restore_from_knowledge()` path currently loads trust records and Hebbian weights, then `_set_probationary_trust()` is called on freshly spawned agents with new random IDs. The old trust records sit in memory but are never matched to any living agent. After this phase, restored agents get the same IDs they had before, so trust and routing data reconnects automatically.

---

## Deliverables (build in this order)

### 1. Deterministic agent ID generation

**File:** `src/probos/substrate/agent.py`
- Add an `agent_id: str | None = None` parameter to `BaseAgent.__init__(**kwargs)`. If provided, use it instead of generating `uuid4().hex`. If not provided, fall back to `uuid4().hex` for backward compatibility (tests, ad-hoc agent creation).
- The agent does NOT compute its own deterministic ID — the caller provides it. This keeps the ID formula in one place (the spawner/pool/runtime), not scattered across agent subclasses.

**File:** `src/probos/substrate/identity.py` (NEW)
- `generate_agent_id(agent_type: str, pool_name: str, instance_index: int) -> str` — produces a deterministic, human-readable ID. Format: `{agent_type}_{pool_name}_{instance_index}_{short_hash}` where `short_hash` is the first 8 characters of `hashlib.sha256(f"{agent_type}:{pool_name}:{instance_index}".encode()).hexdigest()`. The human-readable prefix makes debug output, trust panels, and `/agents` displays immediately informative. The hash suffix guarantees uniqueness.
- Example: `file_reader_filesystem_0_a1b2c3d4`, `red_team_verifier_red_team_1_e5f6g7h8`
- `generate_pool_ids(agent_type: str, pool_name: str, count: int) -> list[str]` — convenience function that generates IDs for all agents in a pool.

### 2. Spawner and pool integration

**File:** `src/probos/substrate/spawner.py`
- `spawn(**kwargs)` now accepts an optional `agent_id` kwarg and forwards it to the agent constructor. No other changes — the spawner is a pass-through.

**File:** `src/probos/substrate/pool.py`
- `ResourcePool` pool creation loop passes deterministic `agent_id` to each spawn call when `agent_ids: list[str] | None` is provided at construction. When `agent_ids` is None (backward compat), falls back to random UUIDs via the existing path.
- `add_agent()` (used by PoolScaler for scale-up) generates a deterministic ID for the new instance using `generate_agent_id()` with the next available `instance_index` (one beyond the current max in the pool).
- `remove_agent()` (used by PoolScaler for scale-down) is unchanged — trust-aware selection already picks the lowest-trust agent. The removed agent's ID is NOT recycled.
- Recycle/respawn: when `_recycle_agent()` spawns a replacement for a degraded agent, the replacement gets the SAME agent_id as the agent it replaces. The individual persists through recycling — it's the same agent recovering, not a new agent being born.

### 3. Agent manifest in KnowledgeStore

**File:** `src/probos/knowledge/store.py`
- Add `store_manifest(manifest: list[dict])` — writes the agent roster to `manifest.json` in the knowledge repo. Each entry: `{"agent_id": str, "agent_type": str, "pool_name": str, "instance_index": int, "created_at": str}`. Designed agents additionally include `"skills_attached": list[str]`.
- Add `load_manifest() -> list[dict]` — reads the manifest from the knowledge repo. Returns empty list if no manifest exists (fresh start).
- Manifest is a single JSON file (not one file per agent). It represents the complete agent roster at a point in time. Each persist overwrites the previous manifest (Git history preserves all versions).

### 4. Runtime wiring

**File:** `src/probos/runtime.py`

**Pool creation with deterministic IDs:**
- When creating pools in `start()`, generate deterministic IDs using `generate_pool_ids()` and pass them to `ResourcePool` construction. Every built-in pool (system, filesystem, filesystem_writers, directory, search, shell, http, introspect, skills, system_qa, red_team) gets deterministic IDs.
- `_create_designed_pool()` also generates deterministic IDs for designed agent pools. The agent type and pool name are already known at creation time.

**Manifest persistence:**
- After all pools are created in `start()`, persist the agent manifest to KnowledgeStore. The manifest captures the current agent roster — all built-in and designed agents with their deterministic IDs.
- On shutdown, persist the manifest again (captures any runtime changes — designed agents added, agents pruned, pools scaled).
- When designed agents are created via self-mod (`_register_designed_agent`), update and persist the manifest.

**Warm boot reconnection:**
- In `_restore_from_knowledge()`, load the manifest FIRST. Use it to determine which agents should exist and what their IDs should be.
- For built-in pools: generate deterministic IDs (these are the same every time for the same pool configuration). Trust and routing records loaded from KnowledgeStore will match these IDs automatically — no special reconnection logic needed. The bug is fixed by the IDs being deterministic.
- For designed agent pools: the manifest tells the runtime which designed agents existed in the previous session. Restore their code from KnowledgeStore, create their pools with the manifest's agent IDs. Their earned trust and routing history reconnects via matching IDs.
- REMOVE the `_set_probationary_trust()` call for agents that already have trust records from the restore. Only set probationary trust for genuinely new agents (those not in the loaded trust snapshot). This is the key behavior change: previously, all agents got probationary trust on every boot. Now, only new agents do.

### 5. Pruning support

**File:** `src/probos/runtime.py`
- Add `prune_agent(agent_id: str)` method. Removes the agent from its pool, removes it from the manifest, archives its trust records and routing weights (they remain in Git history but are removed from the active TrustNetwork and HebbianRouter), and persists the updated manifest.
- Pruned agent IDs are NOT recycled. If the same agent type is needed later (e.g., pool recovery creates a replacement), it gets a new ID with the next available instance_index and probationary trust.

**File:** `src/probos/experience/shell.py`
- Add `/prune <agent_id>` command. Requires confirmation ("Remove agent {agent_id} permanently? This cannot be undone. [y/n]"). On confirmation, calls `runtime.prune_agent()`. Displays result.

**File:** `src/probos/experience/panels.py`
- No changes needed — the existing `/agents` panel already displays agent IDs, trust scores, and pool membership. With deterministic IDs, the display becomes informative rather than showing random hex strings.

### 6. Update PROGRESS.md

---

## Required Tests

### Identity generation tests (in `tests/test_identity.py`, NEW)
- `generate_agent_id()` returns a string (1 test)
- Same inputs produce same ID (deterministic) (1 test)
- Different inputs produce different IDs (1 test)
- ID format is human-readable: contains agent_type and pool_name (1 test)
- `generate_pool_ids()` returns correct count (1 test)
- `generate_pool_ids()` all IDs are unique (1 test)
- IDs are stable across function calls (idempotent) (1 test)

### Agent construction tests
- BaseAgent accepts `agent_id` kwarg and uses it (1 test)
- BaseAgent without `agent_id` kwarg falls back to uuid4 (1 test)

### Spawner/Pool tests
- Spawner forwards `agent_id` kwarg to agent (1 test)
- Pool created with `agent_ids` list uses those IDs (1 test)
- Pool created without `agent_ids` falls back to random (backward compat) (1 test)
- `add_agent()` generates deterministic ID with next instance_index (1 test)
- Recycle/respawn preserves the same agent_id (1 test)

### Manifest tests (in `tests/test_knowledge_store.py`, extend existing)
- `store_manifest()` creates manifest.json (1 test)
- `load_manifest()` returns stored data (1 test)
- `load_manifest()` returns empty list when no manifest exists (1 test)
- Manifest round-trip preserves all fields (1 test)
- Manifest includes designed agents with skills_attached (1 test)

### Warm boot reconnection tests
- Warm boot with manifest: agents get deterministic IDs matching trust records (1 test)
- Warm boot with manifest: restored agents have their earned trust, NOT probationary (1 test) — THE KEY TEST
- Warm boot with manifest: Hebbian weights reconnect to restored agents (1 test)
- Warm boot with manifest: designed agents restored with correct IDs and trust (1 test)
- Warm boot without manifest (fresh or legacy): falls back to current behavior (1 test)
- New agents (not in trust snapshot) get probationary trust (1 test)
- `--fresh` flag: agents get deterministic IDs but probationary trust (no restore) (1 test)

### Pruning tests
- `prune_agent()` removes agent from pool (1 test)
- `prune_agent()` removes agent from manifest (1 test)
- `prune_agent()` removes trust records from active TrustNetwork (1 test)
- `prune_agent()` removes routing weights from active HebbianRouter (1 test)
- Pruned agent ID is not recycled on pool recovery (1 test)
- Prune nonexistent agent is a no-op (1 test)

### Existing tests
- ALL existing 1007 tests must still pass. The `agent_id` kwarg is optional with backward-compatible default, so no existing test should break.

---

## Milestone End-to-End Test

A runtime starts, creates pools with deterministic IDs. An agent handles several intents successfully, earning trust Beta(8, 2) and strong Hebbian routing weights. The system shuts down, persisting trust, routing, and manifest to KnowledgeStore. The runtime starts again (warm boot). The same agent — identified by the same deterministic ID — is recreated with its earned trust Beta(8, 2) intact, its Hebbian routing weights connected, and its pool position preserved. The agent is the same individual it was before the restart. A new designed agent created after warm boot gets probationary trust Beta(1, 3) — it's genuinely new. The warm boot agent and the new agent coexist with their correct trust levels.

This demonstrates: deterministic IDs, manifest persistence, trust reconnection, routing reconnection, and the distinction between restored agents (earned trust) and new agents (probationary trust).

---

## Do NOT Build

- **Do NOT build per-agent episodic history filtering.** That depends on Cognitive Agents (Phase 15) to be useful. The persistent IDs make it possible (episodes already record agent_ids, and now those IDs are stable), but the query interface (`recall(filter={"agent_id": ...})`) is a Phase 15 deliverable.
- **Do NOT build dream-consolidated agent summaries.** Those require Cognitive Agents to articulate summaries via LLM. Persistent IDs are the prerequisite; the summaries are a later phase.
- **Do NOT build agent self-context at task time.** That's a Cognitive Agent feature — a cognitive agent querying its own history.
- **Do NOT change the EpisodicMemory, DreamingEngine, or WorkflowCache.** This phase is about identity and reconnection, not about changing how memory works. Episodes will naturally start accumulating stable agent_ids once the agents have them.
- **Do NOT change the self-modification pipeline's agent design logic.** The AgentDesigner still generates code the same way. The change is only in how the designed agent's pool is created (deterministic IDs) and how the agent is tracked (manifest).
- **Do NOT build agent versioning or shadow deployment.** Those are separate roadmap items that depend on persistent identity but are out of scope for this phase.
- **Do NOT change the Federation layer.** Persistent IDs are local to each node. Federated agent identity is a separate concern.

---

## Build Order

1. `identity.py` (new — deterministic ID generation utility)
2. `agent.py` (accept optional `agent_id` kwarg)
3. `spawner.py` (forward `agent_id` kwarg)
4. `pool.py` (accept `agent_ids` list, deterministic IDs on add/recycle)
5. `test_identity.py` + agent/spawner/pool tests (validate the foundation)
6. `store.py` (add manifest store/load)
7. `runtime.py` (deterministic pool creation, manifest persistence, warm boot reconnection, remove probationary override for restored agents, prune_agent method)
8. `shell.py` (add /prune command)
9. Warm boot reconnection tests + pruning tests
10. Verify all 1007 existing tests still pass
11. Update PROGRESS.md

---

## Key Design Constraints

**Backward compatibility.** The `agent_id` kwarg is optional everywhere. Any code that creates agents without specifying an ID gets the current random UUID behavior. All existing tests pass without modification.

**ID stability.** The deterministic ID formula must produce the same output for the same inputs forever. It is based on `(agent_type, pool_name, instance_index)` — deployment topology attributes that don't change across code updates. Do NOT incorporate anything volatile (timestamps, process IDs, Python object hashes) into the formula.

**Recycle = same individual.** When an agent is recycled (degraded → respawned), the replacement gets the SAME agent_id. The individual persists through health recovery. This is different from pruning (which removes the individual permanently) and from pool scale-up (which creates a genuinely new individual).

**Pruning = permanent death.** A pruned agent's ID is never reused. If a pool needs a new agent later, it gets a new ID with the next instance_index. Trust records and routing weights for the pruned agent are removed from active state (but preserved in Git history via KnowledgeStore).

**Manifest is descriptive, not prescriptive.** The manifest records what agents exist. It does not define pool sizes or agent behavior. Pool configuration still comes from `system.yaml`. The manifest is used during warm boot to reconnect identities, not to override configuration.
