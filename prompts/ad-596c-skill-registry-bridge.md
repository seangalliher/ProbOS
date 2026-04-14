# AD-596c: Skill-Registry Bridge

## Status: DRAFT — Architect Review

## Context

AD-596a delivered the CognitiveSkillCatalog (T2 cognitive skills via SKILL.md files). AD-596b wired it into all four cognitive pathways (system prompt, intent handling, LLM decisions, proactive context). However, the two skill systems — `CognitiveSkillCatalog` (T2 instruction-defined) and `SkillRegistry` (T3 proficiency tracking, AD-428) — are entirely disconnected. The `CognitiveSkillEntry.skill_id` bridge field exists in the metadata schema but nothing reads it programmatically.

**Current state:** An agent can activate a cognitive skill via intent matching, but:
- No proficiency gating — `min_proficiency` is declared on SKILL.md but never checked
- No exercise tracking — `record_exercise()` is never called when a cognitive skill is used
- No T2→T3 provenance — when Cognitive JIT extracts procedures from episodes, there's no marker linking back to the originating cognitive skill
- Gap predictor's `_intent_to_skill_id()` doesn't consult the cognitive skill catalog

**Prior work absorbed:**
1. **BF-596b-ordering** — `set_skill_catalog()` at runtime.py:1355-1358 runs before Phase 7 creates the catalog. The `if self.cognitive_skill_catalog:` guard is always False at that point. This is a no-op bug. Fix: relocate after line 1405.
2. **ProcedureStep.required_tools serialization gap** — AD-423c declared the field but `to_dict()` (procedures.py:44-54) omits it. Fix: add to serialization.
3. **Procedure T2 provenance** — Add `source_skill_id: str = ""` field to `Procedure` dataclass to close the T2→T3 provenance chain.

## Design Decisions

### 1. Bridge Service: `SkillBridge` (New Module)

Create `src/probos/cognitive/skill_bridge.py` — a lightweight coordinator that connects the two systems. Not a new service with its own lifecycle — a stateless bridge with injected references.

```python
class SkillBridge:
    """Bridges CognitiveSkillCatalog (T2) and SkillRegistry/AgentSkillService (T3).
    
    Stateless coordinator — no database, no lifecycle. Constructed once at startup
    with references to both systems. Dependency Inversion: depends on abstractions
    (the public APIs of both services), not their internals.
    """
    
    def __init__(
        self,
        catalog: CognitiveSkillCatalog,
        skill_registry: SkillRegistry,
        skill_service: AgentSkillService,
    ) -> None:
        ...
    
    async def validate_and_sync(self) -> dict[str, Any]:
        """Run at startup after both systems are initialized.
        
        For each CognitiveSkillEntry with a non-empty skill_id:
        1. Verify the skill_id exists in SkillRegistry
        2. Log warnings for unmatched skill_ids (don't auto-create — explicit registration only)
        3. Return summary: matched, unmatched, no_skill_id
        """
        ...
    
    def check_proficiency_gate(
        self,
        agent_id: str,
        entry: CognitiveSkillEntry,
        agent_profile: SkillProfile | None,
    ) -> bool:
        """Check if agent meets the proficiency requirement for a cognitive skill.
        
        If entry.skill_id is empty or entry.min_proficiency <= 1: always True (ungoverned).
        Otherwise: lookup agent's AgentSkillRecord for that skill_id,
        return record.proficiency >= entry.min_proficiency.
        """
        ...
    
    async def record_skill_exercise(
        self,
        agent_id: str,
        entry: CognitiveSkillEntry,
    ) -> None:
        """Record that an agent activated a cognitive skill.
        
        If entry.skill_id is empty: no-op (ungoverned skill, no proficiency tracking).
        If agent has no record for skill_id: auto-acquire at FOLLOW (1) via acquire_skill().
        Then call record_exercise() to update last_exercised and exercise_count.
        Log-and-degrade on any failure — skill activation must not be blocked by tracking errors.
        """
        ...
    
    def resolve_skill_for_gap(
        self,
        intent_types: list[str],
    ) -> str:
        """Enhanced intent-to-skill mapping that consults CognitiveSkillCatalog.
        
        1. Check CognitiveSkillCatalog.find_by_intent() for T2 skill matches
        2. If found and entry.skill_id is set, return that skill_id
        3. Fall back to existing SkillRegistry exact-match (current _intent_to_skill_id behavior)
        4. Final fallback: "duty_execution" PCC
        """
        ...
```

**Rationale:**
- **Single Responsibility** — bridge logic lives in one place, not scattered across handle_intent / gap_predictor / dreaming
- **Dependency Inversion** — depends on public APIs of both services, no private member access
- **Law of Demeter** — callers use bridge methods, don't reach through to individual services

### 2. Proficiency Gating at Activation Time

Modify `cognitive_agent.py` handle_intent() cognitive skill path (lines 1427-1444):

**Current flow:**
```
find_by_intent(intent) → found → get_instructions(name) → inject into observation
```

**New flow:**
```
find_by_intent(intent) → found → check_proficiency_gate(agent_id, entry, profile) → pass? → get_instructions(name) → inject → record_skill_exercise(agent_id, entry)
```

If proficiency gate fails: return `None` (self-deselect). The agent simply lacks the skill — same behavior as an unmatched intent. No error event.

**Profile resolution:** The bridge needs the agent's `SkillProfile`. To avoid an async DB call on every intent (hot path), use a cached profile:
- `wire_agent()` in `agent_onboarding.py` resolves profile once at onboarding → stores on `self._skill_profile` attribute
- Profile refreshed on `TRUST_UPDATE` events (rank change → proficiency requirements may change)
- `check_proficiency_gate()` accepts the cached profile as a parameter (no internal I/O)

### 3. Exercise Recording After Successful Activation

After `decide()` returns a non-None response AND cognitive skill instructions were injected:

```python
# After successful cognitive lifecycle completion (line ~1467)
if _cognitive_skill_instructions and _skill_entries:
    await self._skill_bridge.record_skill_exercise(self.id, _skill_entries[0])
```

**Fire-and-forget pattern** — matching AD-568e faithfulness verification. Exercise recording failure must not block the agent response. Use `asyncio.create_task()` with exception logging.

### 4. T2→T3 Provenance on Procedure

Add `source_skill_id: str = ""` to the `Procedure` dataclass (procedures.py). Include in `to_dict()`. When Cognitive JIT extracts a procedure from an episode cluster, check if any episode in the cluster has a `cognitive_skill_name` in its metadata (set during AD-596b's handle_intent path). If so, populate `source_skill_id` from the matching `CognitiveSkillEntry.skill_id`.

This closes the T2→T3 provenance chain: SKILL.md → CognitiveSkillEntry → episode metadata → Procedure.source_skill_id → SkillDefinition.

### 5. Gap Predictor Enhancement

Replace `_intent_to_skill_id()` in `gap_predictor.py` with a call to `SkillBridge.resolve_skill_for_gap()`. The bridge consults the cognitive skill catalog first (richer intent→skill mapping), then falls back to the existing SkillRegistry exact-match.

**Injection:** `map_gap_to_skill()` already receives `skill_service` as a parameter. Add optional `skill_bridge` parameter (default None, backward compatible).

### 6. Fix BF-596b Ordering Bug

Move the `set_skill_catalog()` wiring from runtime.py:1355-1358 (before Phase 7) to after line 1405 (after `self.cognitive_skill_catalog` is assigned from `comm.cognitive_skill_catalog`). This is a one-line relocation.

### 7. ProcedureStep.required_tools Serialization

Add `"required_tools": self.required_tools` to `ProcedureStep.to_dict()` (procedures.py:44-54). Also add extraction in `_build_steps_from_data()` if the LLM includes it. This is a gap left from AD-423c's declaration.

### 8. Startup Wiring

**Creation:** `SkillBridge` constructed in `runtime.py` after line 1405 (after both systems are assigned):

```python
# After Phase 7 assignments
if self.cognitive_skill_catalog and self.skill_registry and self.skill_service:
    from probos.cognitive.skill_bridge import SkillBridge
    self.skill_bridge = SkillBridge(
        catalog=self.cognitive_skill_catalog,
        skill_registry=self.skill_registry,
        skill_service=self.skill_service,
    )
    sync_result = await self.skill_bridge.validate_and_sync()
    logger.info("AD-596c: Skill bridge synced — %s", sync_result)
```

**Onboarding wiring:** `finalize.py` passes `skill_bridge` to onboarding service via new `set_skill_bridge()` setter. Onboarding sets `_skill_bridge` on each crew agent during `wire_agent()`.

**Shutdown:** `runtime.py` sets `self.skill_bridge = None` during shutdown. No async teardown needed (stateless).

## Files to Modify

| File | Changes |
|------|---------|
| `src/probos/cognitive/skill_bridge.py` | **NEW** — SkillBridge class |
| `src/probos/cognitive/cognitive_agent.py` | Proficiency gate + exercise recording in handle_intent() cognitive skill path |
| `src/probos/cognitive/procedures.py` | `source_skill_id` field on Procedure + `required_tools` serialization on ProcedureStep |
| `src/probos/cognitive/gap_predictor.py` | `resolve_skill_for_gap()` integration in `map_gap_to_skill()` |
| `src/probos/agent_onboarding.py` | `set_skill_bridge()` setter + wire `_skill_bridge` and `_skill_profile` on crew agents |
| `src/probos/startup/finalize.py` | Wire `skill_bridge` into onboarding service |
| `src/probos/runtime.py` | Create SkillBridge, fix set_skill_catalog ordering, assign to self |
| `tests/test_ad596c_skill_bridge.py` | **NEW** — bridge unit tests |

## Files NOT to Modify

| File | Reason |
|------|--------|
| `src/probos/skill_framework.py` | SkillRegistry/AgentSkillService are used through their public APIs — no changes needed |
| `src/probos/cognitive/skill_catalog.py` | CognitiveSkillCatalog API surface is sufficient — no changes needed |
| `src/probos/startup/communication.py` | Both services are created independently here — bridge is wired in runtime after both exist |
| `src/probos/startup/shutdown.py` | SkillBridge is stateless (no start/stop lifecycle) — just None the reference |
| `src/probos/config.py` | No new config fields needed — proficiency gates use existing SKILL.md metadata |

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|-------------|
| **Single Responsibility** | SkillBridge has one job: coordinate between T2 catalog and T3 registry. No database, no lifecycle. |
| **Open/Closed** | Extends cognitive skill activation with proficiency gating via composition, not modification of SkillRegistry |
| **Dependency Inversion** | SkillBridge depends on public APIs (get_entry, get_profile, record_exercise), not internals |
| **Law of Demeter** | CognitiveAgent calls `self._skill_bridge.check_proficiency_gate()`, never reaches through to skill_service |
| **Interface Segregation** | SkillBridge exposes 4 focused methods, not the union of both services' APIs |
| **Fail Fast / Log-and-Degrade** | exercise recording is fire-and-forget; proficiency gate failure is silent self-deselect (not an error) |
| **DRY** | `resolve_skill_for_gap()` replaces `_intent_to_skill_id()` — one mapping function, not two |
| **Cloud-Ready Storage** | No new database. Bridge is stateless. Both underlying services already use ConnectionFactory |

## Test Plan

1. **SkillBridge unit tests** (~15-20 tests):
   - `validate_and_sync()`: matched/unmatched/no_skill_id scenarios
   - `check_proficiency_gate()`: ungoverned (no skill_id), below threshold, meets threshold, no profile
   - `record_skill_exercise()`: happy path, auto-acquire, no skill_id (no-op), error handling
   - `resolve_skill_for_gap()`: catalog match, registry fallback, default fallback

2. **Integration tests** (~5-8 tests):
   - handle_intent with proficiency gate pass/fail
   - exercise recording after successful activation
   - gap predictor with bridge vs without (backward compat)

3. **Serialization tests** (~3 tests):
   - ProcedureStep.to_dict includes required_tools
   - Procedure.to_dict includes source_skill_id
   - Round-trip through from_dict

## Deferred

- **Auto-creation of SkillDefinitions from SKILL.md** — if a cognitive skill declares a `probos-skill-id` that doesn't exist in SkillRegistry, we log a warning but don't auto-create. Explicit registration via `register_builtins()` or crew-capability YAML is the correct path.
- **Proficiency-based progressive disclosure** — currently all skills at or above rank are shown. Future: only show skills the agent has proficiency for. Depends on AD-596c landing and runtime experience.
- **T2→T3 automatic graduation** — the provenance field enables it but the actual "promote this frequently-used cognitive skill to a compiled procedure" trigger is future work (AD-535 compilation + AD-538 lifecycle).
