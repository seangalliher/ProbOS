# Phase 24b: Self-Assessment Bug Fixes (AD-279, AD-280)

> **Context:** ProbOS demonstrated functional self-awareness by diagnosing its own
> gaps via Discord conversation. Investigation revealed two bugs that caused it to
> partially misdiagnose itself. These fixes improve the accuracy of ProbOS's
> self-assessment capabilities.

## Pre-read

Before starting, read these files to understand the current code:
- `src/probos/agents/introspect.py` — IntrospectionAgent, focus on `_introspect_memory()` (line ~372) and `_introspect_system()` (line ~406)
- `src/probos/cognitive/episodic.py` — `EpisodicMemory.get_stats()` return keys
- `src/probos/consensus/trust.py` — `TrustNetwork`, `_load_from_db()`, `remove()`
- `src/probos/runtime.py` — `_restore_from_knowledge()` (line ~2378), warm boot flow
- `PROGRESS.md` line 2 — current test count

## Step 1: Fix Episodic Memory Key Mismatch (AD-279)

**Problem:** `_introspect_memory()` reads `stats.get("total_episodes", 0)` but
`EpisodicMemory.get_stats()` returns `stats["total"]`. The keys don't match, so
the IntrospectionAgent **always reports 0 episodes** regardless of actual count.

**Mismatched keys:**

| IntrospectionAgent reads | get_stats() provides | Fix |
|---|---|---|
| `stats.get("total_episodes", 0)` | `stats["total"]` | Change to `stats.get("total", 0)` |
| `stats.get("unique_intents", 0)` | Not present | Compute from `len(stats.get("intent_distribution", {}))` |
| `stats.get("success_rate")` | `stats["avg_success_rate"]` | Change to `stats.get("avg_success_rate")` |
| `stats.get("backend", "chromadb")` | Not present | Keep default "chromadb" (fine) |

**Files to modify:**
- `src/probos/agents/introspect.py` — fix the key names in `_introspect_memory()`

**Tests to add** (in a new file `tests/test_introspect_memory_stats.py` or append to existing introspection tests):
1. Create a `FakeEpisodicMemory` with known stats, verify `_introspect_memory()` returns correct `total_episodes`, `unique_intents`, and `success_rate`
2. Verify `_introspect_memory()` returns `{"enabled": False}` when episodic memory is None

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 2: Add Trust Store Reconciliation After Warm Boot (AD-280)

**Problem:** Trust records from previous sessions persist in SQLite (`trust.db`)
and KnowledgeStore (`trust/snapshot.json`). On warm boot, ALL historical trust
entries load — including agents that no longer exist. There is no cleanup step.
`TrustNetwork.remove()` exists but is never called (dead code).

**Result:** IntrospectionAgent reports 72 agents in trust network but only 43
active agents in registry, causing misleading self-assessment.

**Fix:** Add a reconciliation method to `TrustNetwork` and call it after warm boot
completes (after all agents are registered).

**Files to modify:**

1. `src/probos/consensus/trust.py` — add `reconcile(active_agent_ids: set[str])` method:
   ```python
   def reconcile(self, active_agent_ids: set[str]) -> int:
       """Remove trust records for agents not in the active set. Returns count removed."""
       stale = [aid for aid in self._records if aid not in active_agent_ids]
       for aid in stale:
           del self._records[aid]
       return len(stale)
   ```

2. `src/probos/runtime.py` — call `reconcile()` at the END of `start()`, after all
   pools are started and agents registered. Get active IDs from `self.registry`:
   ```python
   # Reconcile trust store — remove stale entries from previous sessions
   active_ids = {a.agent_id for a in self.registry.all_agents()}
   removed = self.trust_network.reconcile(active_ids)
   if removed:
       logger.info("trust-reconcile removed=%d stale entries", removed)
   ```

**Tests to add:**
1. `TrustNetwork.reconcile()` removes stale entries and returns correct count
2. `TrustNetwork.reconcile()` preserves entries for active agents
3. `TrustNetwork.reconcile()` is a no-op when all entries are active
4. Integration test: after warm boot, trust agent count matches registry count

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 3: Update PROGRESS.md

- Update test count on line 2
- Add Phase 24b section after Phase 24a with AD-279 and AD-280 descriptions
- Note that these fixes were identified by ProbOS's own self-assessment via Discord

## Verification

After both fixes, the following should be true:
- `_introspect_memory()` returns the real episode count from `get_stats()`
- After warm boot, `trust_network.agent_count` == `registry.count`
- All existing tests still pass
- Report final test count
