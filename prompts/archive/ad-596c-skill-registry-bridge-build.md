# AD-596c: Skill-Registry Bridge — Build Prompt

## Objective

Bridge the two disconnected skill systems: `CognitiveSkillCatalog` (T2, instruction-defined cognitive skills via SKILL.md) and `SkillRegistry`/`AgentSkillService` (T3, proficiency tracking). Create a stateless `SkillBridge` coordinator, wire proficiency gating into cognitive skill activation, add exercise recording, close the T2→T3 provenance chain, and fix absorbed bugs.

**Read the full design rationale in `prompts/ad-596c-skill-registry-bridge.md`.**

---

## Part 1: Fix ProcedureStep.required_tools Serialization (BF — AD-423c gap)

**File:** `src/probos/cognitive/procedures.py`

### 1a. Add `required_tools` to ProcedureStep.to_dict()

At line 54, the `to_dict()` method ends with `"resolved_agent_type": self.resolved_agent_type,`. Add `required_tools`:

```python
# In ProcedureStep.to_dict() — add after line 53 ("resolved_agent_type"):
            "required_tools": self.required_tools,
```

The full return dict (lines 45-54) should become:

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "expected_input": self.expected_input,
            "expected_output": self.expected_output,
            "fallback_action": self.fallback_action,
            "invariants": self.invariants,
            "agent_role": self.agent_role,
            "resolved_agent_type": self.resolved_agent_type,
            "required_tools": self.required_tools,
        }
```

### 1b. Add `source_skill_id` field to Procedure dataclass

Add a new field after `source_anchors` (line 92):

```python
    source_anchors: list[dict[str, Any]] = field(default_factory=list)
    # AD-596c: T2→T3 provenance — links to CognitiveSkillEntry.skill_id
    source_skill_id: str = ""
```

### 1c. Add `source_skill_id` to Procedure.to_dict()

Add after the `source_anchors` entry (line 121):

```python
            "source_anchors": self.source_anchors,
            "source_skill_id": self.source_skill_id,
```

### 1d. Add `source_skill_id` to Procedure.from_dict()

Add after the `source_anchors` kwarg (line 154):

```python
            source_anchors=data.get("source_anchors", []),
            source_skill_id=data.get("source_skill_id", ""),
```

---

## Part 2: Fix BF-596b set_skill_catalog Ordering Bug

**File:** `src/probos/runtime.py`

The `set_skill_catalog()` call at lines 1355-1358 runs BEFORE Phase 7 creates the catalog. At that point `self.cognitive_skill_catalog` is still `None` from Phase 6, so the `if self.cognitive_skill_catalog:` guard is always False — this is a no-op bug. Standing orders Tier 7 skill descriptions have never been injected in production.

### 2a. Remove the premature call

Delete lines 1355-1358:

```python
        # AD-596b: Wire cognitive skill catalog into standing orders
        if self.cognitive_skill_catalog:
            from probos.cognitive.standing_orders import set_skill_catalog
            set_skill_catalog(self.cognitive_skill_catalog)
```

### 2b. Add the call after Phase 7 assignments

Insert after line 1405 (`self.cognitive_skill_catalog = comm.cognitive_skill_catalog`):

```python
        # AD-596c (BF-596b fix): Wire cognitive skill catalog into standing orders
        # Must be AFTER Phase 7 assigns self.cognitive_skill_catalog from comm result
        if self.cognitive_skill_catalog:
            from probos.cognitive.standing_orders import set_skill_catalog
            set_skill_catalog(self.cognitive_skill_catalog)
```

---

## Part 3: Create SkillBridge Module (NEW FILE)

**File:** `src/probos/cognitive/skill_bridge.py` — **CREATE**

```python
"""AD-596c: Skill-Registry Bridge.

Stateless coordinator connecting CognitiveSkillCatalog (T2 instruction-defined skills)
and SkillRegistry/AgentSkillService (T3 proficiency-tracked skills).

No database. No lifecycle. Constructed once at startup with references to both systems.
Dependency Inversion: depends on public APIs of both services, not their internals.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog, CognitiveSkillEntry
    from probos.skill_framework import AgentSkillService, SkillProfile, SkillRegistry

logger = logging.getLogger(__name__)


class SkillBridge:
    """Bridges CognitiveSkillCatalog (T2) and SkillRegistry/AgentSkillService (T3).

    Stateless coordinator — no database, no lifecycle. Constructed once at startup
    with references to both systems.
    """

    def __init__(
        self,
        catalog: CognitiveSkillCatalog,
        skill_registry: SkillRegistry,
        skill_service: AgentSkillService,
    ) -> None:
        self._catalog = catalog
        self._registry = skill_registry
        self._service = skill_service

    # ── Startup Sync ──────────────────────────────────────────────────

    async def validate_and_sync(self) -> dict[str, Any]:
        """Validate skill_id mappings between T2 catalog and T3 registry at startup.

        For each CognitiveSkillEntry with a non-empty skill_id:
        1. Verify the skill_id exists in SkillRegistry
        2. Log warnings for unmatched skill_ids
        3. Return summary: matched, unmatched, no_skill_id
        """
        matched: list[str] = []
        unmatched: list[str] = []
        no_skill_id: list[str] = []

        registered_ids = {s.skill_id for s in self._registry.list_skills()}

        for entry in self._catalog.list_entries():
            if not entry.skill_id:
                no_skill_id.append(entry.name)
                continue
            if entry.skill_id in registered_ids:
                matched.append(entry.name)
            else:
                unmatched.append(entry.name)
                logger.warning(
                    "AD-596c: Cognitive skill '%s' references skill_id '%s' "
                    "not found in SkillRegistry — proficiency gating will be inactive",
                    entry.name,
                    entry.skill_id,
                )

        result = {
            "matched": len(matched),
            "unmatched": len(unmatched),
            "no_skill_id": len(no_skill_id),
            "unmatched_names": unmatched,
        }
        logger.info(
            "AD-596c: Skill bridge sync — %d matched, %d unmatched, %d ungoverned",
            len(matched), len(unmatched), len(no_skill_id),
        )
        return result

    # ── Proficiency Gating ────────────────────────────────────────────

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
        # Ungoverned skills (no skill_id or min_proficiency not set) — always pass
        if not entry.skill_id or entry.min_proficiency <= 1:
            return True

        # No profile available — fail closed (agent hasn't been profiled yet)
        if not agent_profile:
            logger.debug(
                "AD-596c: Proficiency gate FAIL for %s on '%s' — no profile",
                agent_id, entry.name,
            )
            return False

        # Search for matching skill record across all skill categories
        for record in agent_profile.all_skills:
            if record.skill_id == entry.skill_id:
                passes = record.proficiency >= entry.min_proficiency
                if not passes:
                    logger.debug(
                        "AD-596c: Proficiency gate FAIL for %s on '%s' — "
                        "has %d, needs %d",
                        agent_id, entry.name,
                        record.proficiency, entry.min_proficiency,
                    )
                return passes

        # Agent has no record for this skill — fail
        logger.debug(
            "AD-596c: Proficiency gate FAIL for %s on '%s' — "
            "skill_id '%s' not in profile",
            agent_id, entry.name, entry.skill_id,
        )
        return False

    # ── Exercise Recording ────────────────────────────────────────────

    async def record_skill_exercise(
        self,
        agent_id: str,
        entry: CognitiveSkillEntry,
    ) -> None:
        """Record that an agent activated a cognitive skill.

        If entry.skill_id is empty: no-op (ungoverned skill, no proficiency tracking).
        If agent has no record for skill_id: auto-acquire at FOLLOW (1).
        Then call record_exercise() to update last_exercised and exercise_count.
        Log-and-degrade on any failure — skill activation must not be blocked by tracking errors.
        """
        if not entry.skill_id:
            return  # Ungoverned — no tracking

        try:
            # Check if agent has this skill; auto-acquire if not
            record = await self._service.record_exercise(agent_id, entry.skill_id)
            if record is None:
                # Agent doesn't have this skill yet — auto-acquire at FOLLOW
                from probos.skill_framework import ProficiencyLevel
                await self._service.acquire_skill(
                    agent_id,
                    entry.skill_id,
                    source="cognitive_skill_activation",
                    proficiency=ProficiencyLevel.FOLLOW,
                )
                await self._service.record_exercise(agent_id, entry.skill_id)
                logger.info(
                    "AD-596c: Auto-acquired skill '%s' for %s via cognitive activation",
                    entry.skill_id, agent_id,
                )
        except Exception:
            # Log-and-degrade — never block skill activation for tracking errors
            logger.debug(
                "AD-596c: Exercise recording failed for %s / %s",
                agent_id, entry.skill_id, exc_info=True,
            )

    # ── Gap Predictor Bridge ──────────────────────────────────────────

    def resolve_skill_for_gap(
        self,
        intent_types: list[str],
    ) -> str:
        """Enhanced intent-to-skill mapping that consults CognitiveSkillCatalog.

        1. Check CognitiveSkillCatalog.find_by_intent() for T2 skill matches
        2. If found and entry.skill_id is set, return that skill_id
        3. Fall back to SkillRegistry exact-match (existing behavior)
        4. Final fallback: "duty_execution" PCC
        """
        # T2 catalog match — richer intent→skill mapping
        for intent in intent_types:
            entries = self._catalog.find_by_intent(intent)
            if entries:
                entry = entries[0]
                if entry.skill_id:
                    return entry.skill_id

        # T3 registry exact-match fallback (replaces old _intent_to_skill_id behavior)
        registered_ids = {s.skill_id for s in self._registry.list_skills()}
        for intent in intent_types:
            if intent in registered_ids:
                return intent

        return "duty_execution"
```

---

## Part 4: Proficiency Gating + Exercise Recording in CognitiveAgent

**File:** `src/probos/cognitive/cognitive_agent.py`

### 4a. Add proficiency gate in handle_intent cognitive skill path

Currently lines 1427-1444 handle the cognitive skill activation. After finding a matching skill entry (line 1432) and before loading instructions (line 1433), add the proficiency gate.

Replace the block at lines 1427-1444:

```python
        if not is_direct and intent.intent not in self._handled_intents:
            _catalog = getattr(self, '_cognitive_skill_catalog', None)
            if _catalog:
                _skill_entries = _catalog.find_by_intent(intent.intent)
                if _skill_entries:
                    _entry = _skill_entries[0]
                    _cognitive_skill_instructions = _catalog.get_instructions(_entry.name)
                    if _cognitive_skill_instructions:
                        logger.info(
                            "AD-596b: Loaded cognitive skill '%s' for intent '%s' on %s",
                            _entry.name, intent.intent, self.agent_type,
                        )
                    else:
                        return None
                else:
                    return None
            else:
                return None
```

With:

```python
        if not is_direct and intent.intent not in self._handled_intents:
            _catalog = getattr(self, '_cognitive_skill_catalog', None)
            if _catalog:
                _skill_entries = _catalog.find_by_intent(intent.intent)
                if _skill_entries:
                    _entry = _skill_entries[0]
                    # AD-596c: Proficiency gate — check before loading instructions
                    _bridge = getattr(self, '_skill_bridge', None)
                    if _bridge:
                        _profile = getattr(self, '_skill_profile', None)
                        if not _bridge.check_proficiency_gate(self.id, _entry, _profile):
                            return None  # Silent self-deselect — agent lacks proficiency
                    _cognitive_skill_instructions = _catalog.get_instructions(_entry.name)
                    if _cognitive_skill_instructions:
                        logger.info(
                            "AD-596b: Loaded cognitive skill '%s' for intent '%s' on %s",
                            _entry.name, intent.intent, self.agent_type,
                        )
                    else:
                        return None
                else:
                    return None
            else:
                return None
```

### 4b. Add exercise recording after successful decide()

After the decision is made and faithfulness is processed, add exercise recording. Find the location after the post-decision faithfulness block. Look for the line after the faithfulness Counselor fire-and-forget block (after the `except Exception:` / `logger.debug("AD-568e:..."` at line ~1497).

Add exercise recording right after the faithfulness block and before the `act()` call:

```python
        # AD-596c: Record cognitive skill exercise (fire-and-forget)
        if _cognitive_skill_instructions and _skill_entries:
            _bridge = getattr(self, '_skill_bridge', None)
            if _bridge:
                try:
                    import asyncio
                    asyncio.create_task(
                        _bridge.record_skill_exercise(self.id, _skill_entries[0])
                    )
                except Exception:
                    logger.debug("AD-596c: Exercise recording task creation failed", exc_info=True)
```

**Important:** This must be placed BEFORE the `result = await self.act(decision, intent)` call but AFTER the faithfulness block. It uses `asyncio.create_task()` so it doesn't block the response path.

---

## Part 5: Gap Predictor Enhancement

**File:** `src/probos/cognitive/gap_predictor.py`

### 5a. Modify `map_gap_to_skill()` to accept optional `skill_bridge` parameter

At line 420, update the signature:

```python
async def map_gap_to_skill(
    gap: GapReport,
    skill_service: Any,
    skill_bridge: Any = None,  # AD-596c: Optional SkillBridge for enhanced mapping
) -> GapReport:
```

### 5b. Replace the body of map_gap_to_skill (lines 427-449+)

Replace the skill mapping logic. The current code at lines 430-439 accesses private `registry._skills` (Law of Demeter violation). Replace with:

```python
    try:
        # AD-596c: Use SkillBridge for enhanced intent→skill mapping if available
        if skill_bridge:
            gap.mapped_skill_id = skill_bridge.resolve_skill_for_gap(
                gap.affected_intent_types
            )
        else:
            # Legacy fallback: exact match via _intent_to_skill_id
            registry = getattr(skill_service, "registry", None)
            registered = None
            if registry:
                registered = list(getattr(registry, "_skills", {}).values())
            gap.mapped_skill_id = _intent_to_skill_id(
                gap.affected_intent_types, registered
            )
```

Keep the existing proficiency check code (lines 441-449+) unchanged — it already works correctly through the public `skill_service.get_profile()` API.

---

## Part 6: Agent Onboarding Wiring

**File:** `src/probos/agent_onboarding.py`

### 6a. Add `_skill_bridge` attribute

After line 77 (`self._cognitive_skill_catalog: Any = None`), add:

```python
        self._skill_bridge: Any = None  # AD-596c: Late-bound
```

### 6b. Add `set_skill_bridge()` setter

After the `set_cognitive_skill_catalog` setter (line 89), add:

```python
    def set_skill_bridge(self, bridge: Any) -> None:
        """AD-596c: Set skill bridge (public setter for LoD)."""
        self._skill_bridge = bridge
```

### 6c. Wire `_skill_bridge` and `_skill_profile` on crew agents during `wire_agent()`

In `wire_agent()` (starts at line 91), after the IntentBus subscription block (after line 137), add:

```python
        # AD-596c: Wire skill bridge and cached skill profile onto crew agents
        if self._skill_bridge and hasattr(agent, 'handle_intent'):
            agent._skill_bridge = self._skill_bridge
            # Cache the skill profile to avoid async DB calls on every intent
            try:
                _profile = await self._skill_bridge._service.get_profile(agent.id)
                agent._skill_profile = _profile
            except Exception:
                agent._skill_profile = None
                logger.debug("AD-596c: Could not cache skill profile for %s", agent.id)
```

**Note:** The `_skill_bridge._service.get_profile()` call is acceptable here because onboarding is a one-time setup path (not hot path). The profile is cached on the agent to avoid per-intent async database access.

---

## Part 7: Startup Finalize Wiring

**File:** `src/probos/startup/finalize.py`

After line 155 (the `set_cognitive_skill_catalog` wiring), add:

```python
    # AD-596c: Wire skill bridge into onboarding service
    if hasattr(runtime, 'skill_bridge') and runtime.skill_bridge:
        runtime.onboarding.set_skill_bridge(runtime.skill_bridge)
```

---

## Part 8: Runtime SkillBridge Creation

**File:** `src/probos/runtime.py`

### 8a. Create SkillBridge after Phase 7 assignments

After the `set_skill_catalog` call you added in Part 2b (which is after the Phase 7 assignments at line 1405), add:

```python
        # AD-596c: Create SkillBridge to coordinate T2 catalog and T3 registry
        self.skill_bridge = None
        if self.cognitive_skill_catalog and self.skill_registry and self.skill_service:
            from probos.cognitive.skill_bridge import SkillBridge
            self.skill_bridge = SkillBridge(
                catalog=self.cognitive_skill_catalog,
                skill_registry=self.skill_registry,
                skill_service=self.skill_service,
            )
            try:
                sync_result = await self.skill_bridge.validate_and_sync()
                logger.info("AD-596c: Skill bridge synced — %s", sync_result)
            except Exception:
                logger.warning("AD-596c: Skill bridge sync failed", exc_info=True)
```

### 8b. Cleanup in shutdown

**File:** `src/probos/startup/shutdown.py`

After the `set_skill_catalog(None)` call (line 169), add:

```python
    # AD-596c: Clear skill bridge reference (stateless, no teardown needed)
    runtime.skill_bridge = None
```

---

## Part 9: Tests (NEW FILE)

**File:** `tests/test_ad596c_skill_bridge.py` — **CREATE**

Write comprehensive tests covering:

### SkillBridge unit tests (~15-20 tests):

1. **`validate_and_sync()`:**
   - All entries matched (every skill_id found in registry)
   - Some entries unmatched (skill_id not in registry)
   - Entries with no skill_id (counted as no_skill_id)
   - Empty catalog returns all zeros
   - Mixed scenario (some matched, some unmatched, some ungoverned)

2. **`check_proficiency_gate()`:**
   - No skill_id → always True (ungoverned)
   - min_proficiency <= 1 → always True (default threshold)
   - Agent meets proficiency → True
   - Agent below proficiency → False
   - No profile → False
   - skill_id not in profile → False
   - Proficiency exactly at threshold → True (boundary)

3. **`record_skill_exercise()`:**
   - No skill_id → no-op (returns without calling service)
   - Happy path: record_exercise returns record
   - Auto-acquire: record_exercise returns None first → acquire_skill → record again
   - Error in service → log-and-degrade, no exception raised

4. **`resolve_skill_for_gap()`:**
   - Catalog match with skill_id → returns that skill_id
   - Catalog match without skill_id → falls through to registry
   - No catalog match, registry match → returns registry match
   - No matches → returns "duty_execution"

### Serialization tests:

5. **ProcedureStep.to_dict() includes required_tools**
6. **Procedure.to_dict() includes source_skill_id**
7. **Procedure.from_dict() round-trip with source_skill_id**

### Test setup patterns:

Use mocks for `CognitiveSkillCatalog`, `SkillRegistry`, `AgentSkillService`. Create `CognitiveSkillEntry` instances directly (it's a simple dataclass).

Example mock setup:

```python
from unittest.mock import AsyncMock, MagicMock
from probos.cognitive.skill_catalog import CognitiveSkillEntry
from probos.cognitive.skill_bridge import SkillBridge

def make_entry(name="test_skill", skill_id="", min_proficiency=1, intents=None):
    return CognitiveSkillEntry(
        name=name,
        description=f"Test {name}",
        skill_dir=Path("."),
        skill_id=skill_id,
        min_proficiency=min_proficiency,
        intents=intents or [],
    )

def make_bridge(entries=None, registered_ids=None):
    catalog = MagicMock()
    catalog.list_entries.return_value = entries or []
    catalog.find_by_intent = MagicMock(side_effect=lambda i: [
        e for e in (entries or []) if i in e.intents
    ])

    registry = MagicMock()
    skills = []
    for sid in (registered_ids or []):
        s = MagicMock()
        s.skill_id = sid
        skills.append(s)
    registry.list_skills.return_value = skills

    service = AsyncMock()
    return SkillBridge(catalog=catalog, skill_registry=registry, skill_service=service)
```

---

## Verification Checklist

After all changes, run:

```bash
# Targeted tests
uv run python -m pytest tests/test_ad596c_skill_bridge.py -v

# Serialization regression
uv run python -m pytest tests/ -k "procedure" -v

# Cognitive agent tests
uv run python -m pytest tests/ -k "cognitive" -v

# Full suite
uv run python -m pytest tests/ -x --timeout=120
```

**Manual verification:**
1. Start ProbOS, check logs for `AD-596c: Skill bridge synced`
2. Check logs for `AD-596c (BF-596b fix):` — standing orders should now include skill descriptions
3. Trigger an intent that matches a cognitive skill → verify proficiency gate check in debug logs
4. Verify no regressions in existing cognitive skill activation

---

## Files Summary

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/cognitive/procedures.py` | MODIFY — required_tools serialization + source_skill_id field |
| 2 | `src/probos/runtime.py` | MODIFY — fix BF-596b ordering, create SkillBridge |
| 3 | `src/probos/cognitive/skill_bridge.py` | **CREATE** — SkillBridge class |
| 4 | `src/probos/cognitive/cognitive_agent.py` | MODIFY — proficiency gate + exercise recording |
| 5 | `src/probos/cognitive/gap_predictor.py` | MODIFY — resolve_skill_for_gap integration |
| 6 | `src/probos/agent_onboarding.py` | MODIFY — set_skill_bridge setter + wire on agents |
| 7 | `src/probos/startup/finalize.py` | MODIFY — wire skill_bridge into onboarding |
| 8 | `src/probos/startup/shutdown.py` | MODIFY — clear skill_bridge reference |
| 9 | `tests/test_ad596c_skill_bridge.py` | **CREATE** — bridge unit + serialization tests |

## Engineering Principles Compliance

| Principle | Applied |
|-----------|---------|
| Single Responsibility | SkillBridge: one job — coordinate T2↔T3. No database, no lifecycle |
| Open/Closed | Extends cognitive skill activation with proficiency gating via composition |
| Dependency Inversion | SkillBridge uses public APIs: `list_skills()`, `get_profile()`, `record_exercise()`, `acquire_skill()` |
| Law of Demeter | No `_private` attribute access. Gap predictor's `registry._skills` violation eliminated |
| Interface Segregation | 4 focused methods, not the union of both services' APIs |
| Fail Fast / Log-and-Degrade | Exercise recording: fire-and-forget. Proficiency gate: silent self-deselect |
| DRY | `resolve_skill_for_gap()` replaces `_intent_to_skill_id()` when bridge available |
| Cloud-Ready Storage | No new database. Both underlying services use ConnectionFactory |
