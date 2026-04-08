# BF-127: Working Memory Persistence Should Be Crew-Only

## Classification
- **Type:** Bug Fix (waste / principles violation)
- **Priority:** Low
- **Risk:** Low — filtering only, no behavioral change for crew agents
- **Estimated Scope:** 2 files modified, 1 file optional, ~15 lines changed, 6+ new tests

## Problem

Working memory freeze/restore (AD-573) iterates `runtime.registry.all()` without crew
filtering. This persists working memory for ~20 non-crew agents (bundled utility agents
like NoteTaker, Calculator, WebSearch + CodeReviewAgent) alongside the ~14 sovereign crew.

**Log evidence:** `AD-573: Froze working memory for 34 agents` — only ~14 of those are crew.

**Why this is wrong:**
- Per AD-398 (Three-Tier Agent Architecture): utility agents don't have Character/Reason/Duty.
  "If it doesn't have Character/Reason/Duty, it's not crew. A microwave with a name tag isn't a person."
- Utility agents are stateless single-shot processors — they don't participate in the Ward Room,
  proactive cycles, DMs, or games. Their working memory is always empty.
- Persisting empty dicts to SQLite on every shutdown is wasted I/O.
- Restoring empty state on every startup is wasted iteration.

**Why it's currently safe (but wasteful):**
The `getattr(agent, 'working_memory', None)` guard means infrastructure agents (BaseAgent
subclasses without the property) are already skipped. Only CognitiveAgent subclasses pass
the guard — but that includes ~10 bundled utility agents and CodeReviewAgent that shouldn't
have persistent memory.

## Root Cause

`CognitiveAgent.__init__()` unconditionally creates `AgentWorkingMemory()` (line 70 of
`cognitive_agent.py`). The freeze/restore loops don't filter by crew status.

## Fix

Add `is_crew_agent()` filtering to the three `registry.all()` + `working_memory` loops.
Do NOT change `CognitiveAgent.__init__()` — utility agents can keep ephemeral WM for
in-session use (even though they currently don't use it). The fix is persistence-only.

### Prior Work to Absorb
- **AD-573** — Created the freeze/restore mechanism. This fix narrows its scope.
- **AD-398** — Three-tier agent architecture defining crew vs utility vs infrastructure.
- **BF-125** — Added the GAME_COMPLETED event subscriber loop (also needs filtering).
- **`is_crew_agent()`** in `crew_utils.py` — Existing function, already used by proactive loop.
- **Proactive loop pattern** (`proactive.py` line 289-291) — Canonical crew-filtering pattern:
  ```python
  for agent in rt.registry.all():
      if not is_crew_agent(agent, rt.ontology):
          continue
  ```

### Engineering Principles Applied
- **Single Responsibility (S):** Persistence is a crew concern, not a utility concern.
- **Interface Segregation (I):** Don't persist data for agents that don't use it.
- **DRY:** Reuse existing `is_crew_agent()` — don't create a new filtering mechanism.
- **Fail Fast / Log-and-Degrade:** Keep existing try/except blocks, just filter earlier.

## Implementation

### 1. Filter freeze loop — `src/probos/startup/shutdown.py`

**Location:** Lines 237-249

**Change:** Add `is_crew_agent()` filter inside the freeze loop.

```python
# AD-573: Freeze all agent working memory before pools stop
if hasattr(runtime, 'working_memory_store') and runtime.working_memory_store:
    try:
        from probos.crew_utils import is_crew_agent  # BF-127
        states: dict = {}
        for agent in runtime.registry.all():
            # BF-127: Only persist working memory for sovereign crew agents
            if not is_crew_agent(agent, getattr(runtime, 'ontology', None)):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm:
                states[agent.id] = wm.to_dict()
        if states:
            await runtime.working_memory_store.save_all(states)
            logger.info("AD-573: Froze working memory for %d agents", len(states))
    except Exception as e:
        logger.warning("AD-573: Working memory freeze failed: %s", e)
```

### 2. Filter restore loop — `src/probos/startup/finalize.py`

**Location:** Lines 340-373 (the `AD-573: Restore working memory from stasis` block)

**Change:** Add `is_crew_agent()` filter inside the restore loop.

```python
# AD-573: Restore working memory from stasis
if (runtime._lifecycle_state == "stasis_recovery"
        and hasattr(runtime, 'working_memory_store')
        and runtime.working_memory_store):
    try:
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        from probos.crew_utils import is_crew_agent  # BF-127
        frozen_states = await runtime.working_memory_store.load_all()
        stale_hours = config.working_memory.stale_threshold_hours
        restored = 0
        for agent in runtime.registry.all():
            # BF-127: Only restore working memory for sovereign crew agents
            if not is_crew_agent(agent, getattr(runtime, 'ontology', None)):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm is None:
                continue
            state = frozen_states.get(agent.id)
            if state:
                restored_wm = AgentWorkingMemory.from_dict(
                    state,
                    stale_threshold_seconds=stale_hours * 3600,
                )
                # Revalidate game engagements against live RecreationService
                if hasattr(runtime, 'recreation_service') and runtime.recreation_service:
                    active_game_ids = {
                        g.get("game_id", "")
                        for g in runtime.recreation_service.get_active_games()
                    }
                    for eng in list(restored_wm.get_engagements_by_type("game")):
                        if eng.engagement_id not in active_game_ids:
                            restored_wm.remove_engagement(eng.engagement_id)
                agent._working_memory = restored_wm
                restored += 1
        if restored:
            logger.info("AD-573: Restored working memory for %d agents", restored)
    except Exception:
        logger.debug("AD-573: Working memory restore failed", exc_info=True)
```

### 3. Filter BF-125 event subscriber — `src/probos/startup/finalize.py`

**Location:** Lines 155-174 (the `_on_game_completed` subscriber)

**Change:** Add `is_crew_agent()` filter. This is a minor optimization — only crew agents
play games, so non-crew agents would never match `wm.get_engagement(game_id)` anyway.
But filtering is principled and consistent.

```python
# BF-125: Subscribe to GAME_COMPLETED to clean both players' working memory
from probos.events import EventType
from probos.crew_utils import is_crew_agent  # BF-127

async def _on_game_completed(event: dict) -> None:
    """BF-125: Clean both players' working memory on game completion."""
    event_data = event.get("data", event)
    game_id = event_data.get("game_id", "")
    if not game_id:
        return
    for agent in runtime.registry.all():
        # BF-127: Only crew agents have meaningful working memory
        if not is_crew_agent(agent, getattr(runtime, 'ontology', None)):
            continue
        wm = getattr(agent, 'working_memory', None)
        if wm and wm.get_engagement(game_id):
            wm.remove_engagement(game_id)
            logger.debug("BF-125: Removed game %s from %s working memory",
                         game_id, getattr(agent, 'callsign', agent.id))

runtime.add_event_listener(
    _on_game_completed,
    event_types=[EventType.GAME_COMPLETED],
)
```

## Tests

**File:** `tests/test_bf127_crew_only_wm_persistence.py`

All tests use the existing `is_crew_agent()` function and mock agents with appropriate
`agent_type` values.

### Test Class: `TestCrewOnlyWMFreeze`

1. **`test_freeze_skips_non_crew_agents`**
   - Create a mock registry with 3 crew agents (agent_type="architect", "counselor", "scout")
     and 3 non-crew agents (agent_type="calculator", "web_search", "code_reviewer")
   - All 6 have `working_memory` attributes with `to_dict()` returning non-empty state
   - Run the freeze logic (extract to testable form or test via integration)
   - Assert only 3 states were saved (crew agents only)

2. **`test_freeze_log_message_reflects_crew_count`**
   - Verify the log message count matches crew agent count, not total agent count

3. **`test_freeze_handles_crew_agent_without_wm_gracefully`**
   - Crew agent with `working_memory` returning None → skipped without error

### Test Class: `TestCrewOnlyWMRestore`

4. **`test_restore_skips_non_crew_agents`**
   - Load frozen states for 3 crew agents + 2 non-crew agents
   - Verify only crew agents get `_working_memory` replaced
   - Verify non-crew agents' `_working_memory` is untouched

5. **`test_restore_log_message_reflects_crew_count`**
   - Verify restored count matches crew agents with valid frozen state

6. **`test_game_completed_cleanup_skips_non_crew`**
   - Fire GAME_COMPLETED event with a known game_id
   - 2 crew agents have the game engagement, 1 non-crew agent also has it
   - Verify only crew agents' engagements are removed

## Verification

1. `pytest tests/test_bf127_crew_only_wm_persistence.py -v` — all new tests pass
2. `pytest tests/test_bf125_working_memory_desync.py -v` — BF-125 tests still pass
3. `pytest tests/ -x --timeout=60` — full suite, no regressions
4. Manual: Start ProbOS → shutdown → verify log says `Froze working memory for ~14 agents`
   (crew count, not 34)
5. Manual: Restart → verify `Restored working memory for N agents` shows crew-only count
