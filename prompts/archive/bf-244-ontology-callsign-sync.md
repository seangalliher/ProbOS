# BF-244: Ontology Callsign Desync After Naming Ceremony

**Status:** Ready for builder
**Priority:** Medium
**Issue:** #357

---

## Problem

After cold-start naming ceremony, the agent's ontology identity context still shows the **seed callsign** (from `organization.yaml`) instead of the **self-named callsign**. The agent receives conflicting identity signals in its prompt:

1. Standing orders personality block: "You are **Anvil**, the Software Engineer" (correct — uses runtime callsign)
2. Ontology identity context: "You are **Forge**, Builder Officer in Engineering" (stale — never updated)

The agent notices the contradiction and flags it: *"the composition brief identifies me as Anvil, but my ship identity confirms I am Forge."*

**Root cause:** Startup ordering. The onboarding service is created with `ontology=None` (runtime.py:1190) because the ontology doesn't exist yet. Agent pools are created next (runtime.py:1199), triggering `wire_agent()` → naming ceremony → `self._ontology.update_assignment_callsign()`. But `self._ontology` is `None`, so the `if self._ontology:` guard at `src/probos/agent_onboarding.py:236` silently skips the update. The ontology is wired into onboarding later in finalize.py:354 — **after all agents are already onboarded**.

The ontology's `get_crew_context()` reads from the same `assignments` dict that `update_assignment_callsign()` modifies (shared reference via service.py:64). So the data flow is correct — the update just never fires.

**Prior art:** BF-049 (added `update_assignment_callsign`), BF-083 (runtime callsign override in personality block), BF-101 (callsign resolution fallback), BF-235 (stale identity cache invalidation). This bug is the gap BF-049 was supposed to close but couldn't because of startup ordering.

**Affected path:** `cognitive_agent.py:_build_cognitive_baseline()` → `ontology.get_crew_context()` → `identity.callsign` rendered in agent prompt. Reduces ambiguity in agent identity context — also affects peer and superior callsigns in the same render path (other agents' naming ceremony results are also not synced).

---

## Fix

### Section 1: Add callsign sync to finalize.py

**File:** `src/probos/startup/finalize.py`

After the existing ontology wiring at around line 354 (`runtime.onboarding._ontology = runtime.ontology`), add a callsign sync loop that reconciles the `CallsignRegistry` (source of truth for runtime callsigns) with the ontology assignments.

```python
# BF-244: Sync self-named callsigns into ontology.
# Naming ceremony runs during pool creation (Phase 2) before ontology
# is wired into onboarding (this phase). The ceremony updates
# CallsignRegistry but the ontology.update_assignment_callsign() call
# is skipped because self._ontology is None at that point. Reconcile
# here so get_crew_context() returns current callsigns.
# Note: update_assignment_callsign() preserves agent_id (wire_agent ran during pool creation).
if runtime.ontology and runtime.callsign_registry:
    for agent_type, callsign in runtime.callsign_registry.all_callsigns().items():
        current = runtime.ontology.get_assignment_for_agent(agent_type)
        if current and current.callsign != callsign:
            runtime.ontology.update_assignment_callsign(agent_type, callsign)
            logger.info("BF-244: Synced ontology callsign for %s: '%s' -> '%s'",
                        agent_type, current.callsign, callsign)
```

Insert this immediately before the `# AD-423c: Wire tool registry into onboarding service` comment block (line 362). This is after the ontology wiring (line 354) and orientation service wiring (lines 358-360), but before the catalog backfill (line 366). The callsign sync must precede the catalog backfill in case catalog logging references current callsigns.

**Builder note:** `finalize.py` already has `logger = logging.getLogger(__name__)` at line 22. No additional import needed.

**Engineering principles:**
- **DRY:** Reuses existing `update_assignment_callsign()` API (BF-049). No new method needed.
- **Fail Fast / Log-and-degrade:** `logger.info` on each sync (not silent). The `if current and current.callsign != callsign:` guard prevents no-op calls.
- **Law of Demeter:** Uses public API on `runtime.ontology` and `runtime.callsign_registry` — no private attribute access.

**Implementation note:** `update_assignment_callsign()` (departments.py:97-108) creates a **new** `Assignment` object with the updated callsign and replaces the entry in the shared `assignments` dict. Because `VesselOntologyService` and `DepartmentService` hold a reference to the same dict (service.py:64), the replacement is visible to both — `get_crew_context()` will read the updated Assignment on its next call without any additional wiring.

**What this does NOT change:**
- Does not change the startup ordering itself. Moving pool creation after finalize would be a larger refactor with cascade risk.
- Does not change `get_crew_context()` — it already reads from the correct shared dict.
- Does not change the naming ceremony flow in `agent_onboarding.py`.
- Does not change `CallsignRegistry` or `DepartmentService`.

---

### Section 2: Tests

**File:** `tests/test_bf244_ontology_callsign_sync.py` (new file)

All tests use `pytest` + `pytest-asyncio`. Arrange-Act-Assert pattern.

**Test 1: `test_finalize_syncs_renamed_callsign`**
Verify that after finalize, the ontology assignment reflects the runtime callsign, not the seed.

Setup:
- Create a mock runtime with `ontology` (real or mock `VesselOntologyService`) and `callsign_registry`
- Set the ontology assignment for `builder` with seed callsign `"Forge"`
- Set the registry to have `builder` → `"Anvil"` (simulating post-naming state)
- Call the sync logic (extract it or test the finalize path)
- Assert `ontology.get_assignment_for_agent("builder").callsign == "Anvil"`

**Test 2: `test_finalize_skips_unchanged_callsign`**
Verify no-op when callsign already matches (e.g., agent kept seed name).

Setup:
- Set ontology assignment for `builder` with `"Forge"` and registry with `builder` → `"Forge"`
- Use `unittest.mock.patch.object(runtime.ontology, 'update_assignment_callsign') as mock_update`
- Run sync
- Assert `mock_update.assert_not_called()` (no unnecessary mutations)

**Test 3: `test_finalize_syncs_multiple_renamed_agents`**
Verify that multiple agents' renamed callsigns are all synced.

Setup:
- Registry: `builder` → `"Anvil"`, `scout` → `"Horizon"`, `data_analyst` → `"Kira"`
- Ontology seeds: `builder` → `"Forge"`, `scout` → `"Wesley"`, `data_analyst` → `"Rahda"`
- Run sync
- Assert all three ontology assignments updated

**Test 4: `test_finalize_sync_tolerates_missing_assignment`**
Registry has an agent_type with no ontology assignment. Use a synthetic agent_type like `"nonexistent_test_agent"` (not a real agent type — makes the test deterministic regardless of which agents are in the seed YAML). Sync should skip gracefully via the `if current and ...` guard (log-and-degrade, no crash).

**Test 5: `test_get_crew_context_returns_synced_callsign`**
Integration test: after sync, `ontology.get_crew_context("builder")["identity"]["callsign"]` returns `"Anvil"`, not `"Forge"`.

**Test 6: `test_peer_callsigns_reflect_sync`**
After sync, `get_crew_context("engineering_officer")["peers"]` should contain `"Anvil"`, not `"Forge"` (peers read from the same assignments dict). **Setup requirement:** `builder` and `engineering_officer` must be in the same department in the test ontology so they appear as peers. Use the `engineering` department from `organization.yaml`.

**Test 7: `test_reports_to_reflects_synced_callsign`**
After sync, a subordinate's `get_crew_context("builder")["reports_to"]` should show the superior's synced callsign, not the seed. Covers `get_crew_context()` lines 337-339 which iterate assignments for the superior chain.

Setup:
- Registry: `engineering_officer` → `"Nova"` (was seed `"LaForge"`)
- Ontology seed: `engineering_officer` → `"LaForge"`
- Run sync
- Assert `get_crew_context("builder")["reports_to"]` contains `"Nova"`, not `"LaForge"`

**Test 8: `test_sync_idempotent`**
Running the sync loop twice in a row produces no change on second pass. First pass syncs mismatched callsigns; second pass finds all callsigns already match and calls no updates.

Setup:
- Registry: `builder` → `"Anvil"`, ontology seed: `builder` → `"Forge"`
- Run sync once (should update)
- Use `unittest.mock.patch.object(runtime.ontology, 'update_assignment_callsign') as mock_update`
- Run sync again
- Assert `mock_update.assert_not_called()`

---

### Section 3: Tracker Updates

**PROGRESS.md** — Add at top:
```
BF-244 CLOSED. Ontology callsign desync after naming ceremony. Startup ordering: onboarding runs with ontology=None, so update_assignment_callsign() silently skips. Fix: callsign reconciliation loop in finalize.py syncs CallsignRegistry → ontology assignments after ontology is wired. Fixed identity context, peer, and superior callsign display in get_crew_context(). 8 tests. Issue #357.
```

**docs/development/roadmap.md** — Add to Bug Tracker table:
```
| BF-244 | Ontology callsign desync after naming ceremony. Onboarding runs with `ontology=None` during pool creation, so `update_assignment_callsign()` silently skips. Agent sees seed callsign ("Forge") in ontology identity context while standing orders correctly show self-named callsign ("Anvil"). **Fix:** Callsign reconciliation loop in `finalize.py` syncs `CallsignRegistry` → ontology assignments after ontology is wired. Also fixes stale peer and superior callsigns in `get_crew_context()`. | Medium | **Closed** |
```

**DECISIONS.md** — Add to `decisions-era-4-evolution.md`:
```
### BF-244 — Ontology Callsign Sync After Naming Ceremony (2026-04-27)

**Context:** Cold-start naming ceremony updates `CallsignRegistry` and `agent.callsign` but cannot update ontology assignments because the ontology isn't wired into the onboarding service yet (startup ordering: pools created in Phase 2, ontology wired in Phase 8). The `if self._ontology:` guard silently skips the update. Agents then receive conflicting identity signals — correct callsign from standing orders personality block (BF-083) but stale seed callsign from ontology context in `get_crew_context()`.
**Decision:** Add a defensive callsign reconciliation loop in `finalize.py` immediately after wiring the ontology into onboarding. Loop iterates `CallsignRegistry.all_callsigns()`, compares each against the ontology assignment, and calls `update_assignment_callsign()` for any mismatches. This is the same pattern used for cognitive skill catalog backfill (finalize.py around line 370). Did not restructure startup ordering — the finalize backfill pattern is established and lower-risk.
**Consequences:** Ontology identity context and peer callsigns in `get_crew_context()` now reflect self-named callsigns. Completes the identity sync chain: BF-049 (added the API) → BF-083 (personality block override) → BF-101 (runtime resolution fallback) → BF-235 (cache invalidation) → BF-244 (ontology backfill).
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf244_ontology_callsign_sync.py -v

# Existing identity/callsign tests (regression)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ontology_callsign_sync.py tests/test_bf153_callsign_registry.py tests/test_callsign_validation.py tests/test_identity_persistence.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Report test count after each step.
