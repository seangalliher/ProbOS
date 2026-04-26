# AD-618e: Cognitive JIT Bridge — Bill Step → Skill Compilation

**Issue:** #204 (AD-618 umbrella)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-618b (Bill Instance + Runtime — must be built first), AD-596c (Skill Bridge — complete), AD-531-539 (Cognitive Skill Framework — complete)
**Files:** `src/probos/sop/jit_bridge.py` (NEW), `src/probos/sop/__init__.py` (EDIT — add to imports + `__all__`), `src/probos/startup/finalize.py` (EDIT — wire JIT bridge), `tests/test_ad618e_cognitive_jit_bridge.py` (NEW)

## Problem

AD-618b delivers BillRuntime — agents execute bill steps and emit `BILL_STEP_COMPLETED` events. AD-596c delivers SkillBridge — connects the CognitiveSkillCatalog (T2 instruction-defined) to SkillRegistry/AgentSkillService (T3 proficiency-tracked). There is no bridge between these two systems.

When an agent successfully completes a Bill step, that execution represents **demonstrated competence** in a real operational procedure. This is exactly the signal the Cognitive JIT system should use to auto-acquire and exercise T3 skills. Currently, bill step completion is a dead-end event — no learning happens.

AD-618e delivers the bridge: `BILL_STEP_COMPLETED` events feed SkillBridge to auto-acquire skills, record exercises, and build proficiency over time. Agents that repeatedly execute bill steps compile those steps into internalized T3 skills — the operational version of "practice makes expert."

**Navy model:** A sailor who stands enough watches at a station earns a Personnel Qualification Standard (PQS) sign-off. AD-618e is the automated PQS sign-off for agents.

**Architectural principle:** The bridge is a **listener**, not a controller. It subscribes to events and makes SkillBridge calls. It doesn't modify BillRuntime behavior, step outcomes, or the cognitive chain. Pure side-effect: learning from doing.

**What this does NOT include:**
- Modifying BillRuntime step execution (AD-618b owns that)
- Creating new CognitiveSkillEntry files from bill steps (future — skill catalog authoring)
- Promotion triggers based on bill step proficiency (future — ties to AD-566 Qualification Programs)
- HXI visibility into JIT compilation (future — could add to AD-618d dashboard)

---

## Section 1: BillStepSkillMap — Step-to-Skill Mapping

**File:** `src/probos/sop/jit_bridge.py` (NEW)

The core mapping: which bill steps correspond to which T3 skills. This is a lookup table, not an AI inference — explicit, auditable, maintainable.

```python
"""AD-618e: Cognitive JIT Bridge — Bill step completion → T3 skill acquisition.

Listens to BILL_STEP_COMPLETED events and feeds SkillBridge to auto-acquire
skills, record exercises, and build agent proficiency from operational
experience. Pure side-effect listener — does not modify BillRuntime behavior.

Navy model: automated PQS sign-off from demonstrated watchstanding competence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.skill_framework import ProficiencyLevel

if TYPE_CHECKING:
    from probos.cognitive.skill_bridge import SkillBridge
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog, CognitiveSkillEntry
    from probos.skill_framework import AgentSkillService
    from probos.sop.runtime import BillRuntime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepSkillMapping:
    """Maps a bill step action type to a T3 skill_id.

    The mapping can be scoped to a specific bill_id + step_id (exact match)
    or to an action type (broad match). Exact matches take priority.
    """

    skill_id: str                 # T3 skill to exercise/acquire
    action: str = ""              # StepAction value (e.g., "cognitive_skill", "tool")
    bill_id: str = ""             # Specific bill (empty = all bills)
    step_id: str = ""             # Specific step (empty = all steps with matching action)
    min_proficiency_to_acquire: ProficiencyLevel = ProficiencyLevel.FOLLOW  # Auto-acquisition level
```

### Mapping Resolution

The bridge resolves mappings in priority order:
1. **Exact match**: `bill_id` + `step_id` both match
2. **Bill-scoped action match**: `bill_id` matches + `action` matches
3. **Global action match**: `bill_id` is empty + `action` matches

### Default Mappings

Provide a set of default mappings that cover the StepAction types from AD-618a:

```python
DEFAULT_STEP_SKILL_MAPPINGS: list[StepSkillMapping] = [
    # Cognitive skill steps → "duty_execution" (general operational competence)
    StepSkillMapping(skill_id="duty_execution", action="cognitive_skill"),
    # Tool usage steps → "tool_operation" (general tool proficiency)
    StepSkillMapping(skill_id="tool_operation", action="tool"),
    # Communication steps → "communication" (Ward Room proficiency)
    StepSkillMapping(skill_id="communication", action="post_to_channel"),
    StepSkillMapping(skill_id="communication", action="send_dm"),
    # Sub-bill orchestration → "coordination" (multi-agent coordination)
    StepSkillMapping(skill_id="coordination", action="sub_bill"),
]
```

**Builder note:** The skill_ids above (`duty_execution`, `tool_operation`, `communication`, `coordination`) should match existing T3 SkillRegistry entries if they exist. If they don't exist, the SkillBridge.record_skill_exercise() will auto-acquire at FOLLOW level — this is the expected cold-start behavior from AD-596c.

---

## Section 2: BillJITBridge — Event Listener + SkillBridge Integration

**File:** `src/probos/sop/jit_bridge.py` (same file, continued)

```python
class BillJITBridge:
    """Bridges Bill step completions to T3 skill proficiency tracking.

    Subscribes to BILL_STEP_COMPLETED events. For each completed step:
    1. Resolve the step's action type to a T3 skill_id via StepSkillMapping
    2. Look up matching CognitiveSkillEntry in the catalog (if any)
    3. Call SkillBridge.record_skill_exercise() to update proficiency

    Pure listener — never modifies BillRuntime, step outcomes, or agent state
    beyond skill proficiency records. Log-and-degrade on all errors.

    Parameters
    ----------
    skill_bridge : SkillBridge
        The T2↔T3 bridge for skill exercise recording.
    catalog : CognitiveSkillCatalog
        The T2 cognitive skill catalog for entry lookup.
    skill_service : AgentSkillService
        The T3 skill service for direct exercise recording (when no
        catalog entry exists). Passed explicitly to avoid reaching
        into SkillBridge's private ``_service`` attribute.
    mappings : list[StepSkillMapping], optional
        Custom step→skill mappings. Defaults to DEFAULT_STEP_SKILL_MAPPINGS.
    """

    def __init__(
        self,
        skill_bridge: SkillBridge,
        catalog: CognitiveSkillCatalog,
        skill_service: AgentSkillService,
        mappings: list[StepSkillMapping] | None = None,
    ) -> None:
        self._bridge = skill_bridge
        self._catalog = catalog
        self._skill_service = skill_service
        self._mappings = mappings or list(DEFAULT_STEP_SKILL_MAPPINGS)
        self._exercise_count: int = 0  # Dispatch attempts (not confirmed completions)

    @property
    def exercise_count(self) -> int:
        """Total skill exercises recorded since initialization."""
        return self._exercise_count

    def add_mapping(self, mapping: StepSkillMapping) -> None:
        """Add a custom step→skill mapping at runtime."""
        self._mappings.append(mapping)

    def resolve_mapping(
        self,
        bill_id: str,
        step_id: str,
        action: str,
    ) -> StepSkillMapping | None:
        """Resolve the best StepSkillMapping for a completed step.

        Priority order:
        1. Exact match (bill_id + step_id)
        2. Bill-scoped action match (bill_id + action)
        3. Global action match (action only)

        Returns None if no mapping matches.
        """
        exact: StepSkillMapping | None = None
        bill_action: StepSkillMapping | None = None
        global_action: StepSkillMapping | None = None

        for m in self._mappings:
            # Exact match
            if m.bill_id and m.step_id and m.bill_id == bill_id and m.step_id == step_id:
                exact = m
                break  # Highest priority — stop searching
            # Bill-scoped action match
            if m.bill_id and not m.step_id and m.bill_id == bill_id and m.action == action:
                if not bill_action:
                    bill_action = m
            # Global action match
            if not m.bill_id and not m.step_id and m.action == action:
                if not global_action:
                    global_action = m

        return exact or bill_action or global_action

    async def on_step_completed(self, event: dict[str, Any]) -> None:
        """Handle a BILL_STEP_COMPLETED event envelope.

        Receives the full event envelope from runtime._emit_event_local or
        NATS callback — both deliver the same shape:
        ``{"type": "bill_step_completed", "data": {...}, "timestamp": ...}``

        The AD-618b payload fields (instance_id, bill_id, step_id, action,
        agent_id, agent_type, duration_s) live under event["data"].

        Log-and-degrade: never raises. A failure here must not affect
        bill execution or agent operations.
        """
        try:
            event_data = event.get("data", {}) if isinstance(event, dict) else {}

            bill_id = event_data.get("bill_id", "")
            step_id = event_data.get("step_id", "")
            action = event_data.get("action", "")
            agent_id = event_data.get("agent_id", "")

            if not agent_id:
                logger.debug(
                    "AD-618e: BILL_STEP_COMPLETED without agent_id — skipping JIT",
                )
                return

            # 1. Resolve mapping
            mapping = self.resolve_mapping(bill_id, step_id, action)
            if not mapping:
                logger.debug(
                    "AD-618e: No skill mapping for step %s/%s (action=%s)",
                    bill_id, step_id, action,
                )
                return

            # 2. Find CognitiveSkillEntry in catalog (if exists)
            entry = self._find_catalog_entry(mapping.skill_id)

            # 3. Record exercise via SkillBridge
            if entry:
                await self._bridge.record_skill_exercise(agent_id, entry)
            else:
                # No catalog entry — record directly via SkillBridge's
                # underlying service (auto-acquire at mapping's proficiency)
                await self._record_direct_exercise(agent_id, mapping)

            self._exercise_count += 1
            logger.debug(
                "AD-618e: Recorded skill exercise for %s — skill=%s (bill=%s, step=%s)",
                agent_id, mapping.skill_id, bill_id, step_id,
            )

        except Exception:
            # Log-and-degrade — JIT bridge must never crash
            logger.debug(
                "AD-618e: JIT bridge error on step completion",
                exc_info=True,
            )

    def _find_catalog_entry(self, skill_id: str) -> Any:
        """Look up CognitiveSkillEntry by skill_id in the catalog.

        Returns None if not found. The catalog may not have an entry for
        every T3 skill — that's fine, we fall back to direct recording.
        """
        for entry in self._catalog.list_entries():
            if entry.skill_id == skill_id:
                return entry
        return None

    async def _record_direct_exercise(
        self,
        agent_id: str,
        mapping: StepSkillMapping,
    ) -> None:
        """Record exercise directly via AgentSkillService when no catalog entry exists.

        Direct path mirrors SkillBridge.record_skill_exercise auto-acquire logic;
        required because SkillBridge.record_skill_exercise needs a CognitiveSkillEntry,
        not a bare skill_id.

        Uses the injected skill service to record_exercise().
        If the agent doesn't have the skill, auto-acquires at the mapping's
        proficiency level.
        """
        try:
            record = await self._skill_service.record_exercise(agent_id, mapping.skill_id)
            if record is None:
                # Auto-acquire at mapping's proficiency level
                await self._skill_service.acquire_skill(
                    agent_id,
                    mapping.skill_id,
                    source="bill_step_completion",
                    proficiency=mapping.min_proficiency_to_acquire,
                )
                await self._skill_service.record_exercise(agent_id, mapping.skill_id)
                logger.info(
                    "AD-618e: Auto-acquired skill '%s' for %s via bill step completion",
                    mapping.skill_id, agent_id,
                )
        except ValueError as e:
            # acquire_skill raises ValueError when prerequisites not met
            logger.info(
                "AD-618e: Cannot auto-acquire '%s' for %s — prerequisite not met: %s",
                mapping.skill_id, agent_id, e,
            )
        except Exception:
            logger.debug(
                "AD-618e: Direct exercise recording failed for %s / %s",
                agent_id, mapping.skill_id, exc_info=True,
            )

    def get_stats(self) -> dict[str, Any]:
        """Return diagnostic stats for the JIT bridge."""
        return {
            "exercise_count": self._exercise_count,
            "mapping_count": len(self._mappings),
            "custom_mappings": sum(
                1 for m in self._mappings if m.bill_id or m.step_id
            ),
        }
```

---

## Section 3: Wire BillJITBridge in finalize.py

**File:** `src/probos/startup/finalize.py` (EDIT)

The bridge runs in-process via `add_event_listener` — the same local dispatch path used by all event listeners. When NATS is connected, events still fire through `_emit_event_local` for in-process subscribers (AD-637d), so the bridge handler receives events regardless of transport.

**Envelope convention:** Both dispatch paths (`_emit_event_local` at runtime.py:765 and `_nats_callback` at runtime.py:675) call `fn(event)` with the full envelope `{"type": "...", "data": {...}, "timestamp": ...}`. The handler unpacks `event["data"]` internally. This is the same convention every other event listener in the codebase uses.

Add after the AD-618d BillRuntime wiring block (after the `logger.info("AD-618d: BillRuntime wired")` line):

```python
    # --- AD-618e: Wire BillJITBridge (Bill step → skill proficiency) ---
    if (
        getattr(runtime, '_bill_runtime', None)
        and getattr(runtime, 'skill_bridge', None)
        and getattr(runtime, 'cognitive_skill_catalog', None)
        and getattr(runtime, 'skill_service', None)
    ):
        from probos.sop.jit_bridge import BillJITBridge
        _jit_bridge = BillJITBridge(
            skill_bridge=runtime.skill_bridge,
            catalog=runtime.cognitive_skill_catalog,
            skill_service=runtime.skill_service,
        )
        runtime.add_event_listener(
            _jit_bridge.on_step_completed,
            event_types={"bill_step_completed"},
        )
        logger.info("AD-618e: BillJITBridge wired (bill_step_completed → skill exercises)")
```

**Verified accessor names:**
| Accessor | Location | Notes |
|----------|----------|-------|
| `runtime.skill_bridge` | runtime.py:1567 | Public attr, created Phase 7 (after skill_catalog + skill_service) |
| `runtime.cognitive_skill_catalog` | runtime.py:441/1549 | Public attr, created Phase 7 |
| `runtime.skill_service` | runtime.py:438/1548 | Public attr, created Phase 7 |
| `runtime.add_event_listener(fn, event_types=...)` | runtime.py:638 | Param is `event_types` (not `types`) |

**Why finalize.py:** All dependencies (BillRuntime from Phase 6, SkillBridge/catalog/service from Phase 7) are guaranteed available by Phase 8 (finalize). Same rationale as AD-618d's event callback wiring.

---

## Section 4: Module Exports

**File:** `src/probos/sop/__init__.py` (EDIT)

The file already exists with AD-618a/b/c exports and uses `__all__`. Add to **both** the import block and the `__all__` list:

Add to the imports:
```python
from probos.sop.jit_bridge import (
    BillJITBridge,
    StepSkillMapping,
    DEFAULT_STEP_SKILL_MAPPINGS,
)
```

Add to `__all__`:
```python
    "BillJITBridge",
    "StepSkillMapping",
    "DEFAULT_STEP_SKILL_MAPPINGS",
```

---

## Section 5: Tests

**File:** `tests/test_ad618e_cognitive_jit_bridge.py` (NEW)

### Test infrastructure

Create mock/stub versions of:
- `SkillBridge` — mock `record_skill_exercise()` and `_service` attribute
- `CognitiveSkillCatalog` — mock `list_entries()` returning test entries
- `AgentSkillService` — mock `record_exercise()` and `acquire_skill()`

Use `unittest.mock.AsyncMock` for async methods. Use `@dataclass` stubs for `CognitiveSkillEntry` with fields: `name`, `skill_id`, `description`, `skill_dir`, `department`, `min_proficiency`, `intents`, `activation`, `triggers`.

**Important:** All tests calling `on_step_completed` must pass the full event envelope, not bare payload data:
```python
# Correct — full envelope:
await bridge.on_step_completed({
    "type": "bill_step_completed",
    "data": {"bill_id": "gq", "step_id": "s1", "action": "cognitive_skill", "agent_id": "a1"},
    "timestamp": 1234567890.0,
})

# WRONG — bare payload (this is NOT what runtime delivers):
await bridge.on_step_completed({"bill_id": "gq", ...})
```

### Test categories (22 tests):

**Mapping resolution (6 tests):**
1. `test_resolve_exact_match` — mapping with matching bill_id + step_id returns it
2. `test_resolve_bill_scoped_action` — mapping with matching bill_id + action returns it
3. `test_resolve_global_action` — mapping with only action returns it
4. `test_resolve_priority_exact_over_action` — exact match wins over action match
5. `test_resolve_no_match` — unknown action returns None
6. `test_resolve_empty_mappings` — empty mapping list returns None

**Event handling — happy path (5 tests):**
7. `test_on_step_completed_exercises_skill_via_catalog` — envelope with catalog entry calls `record_skill_exercise()`
8. `test_on_step_completed_exercises_skill_direct` — envelope without catalog entry calls `_record_direct_exercise()`
9. `test_on_step_completed_auto_acquires` — agent without skill auto-acquires at FOLLOW
10. `test_on_step_completed_increments_count` — `exercise_count` increments on success
11. `test_on_step_completed_with_default_mappings` — default mappings cover `cognitive_skill` action when handler receives a properly-formed envelope

**Event handling — edge cases (7 tests):**
12. `test_on_step_completed_no_agent_id` — envelope with missing agent_id in data skips (no error)
13. `test_on_step_completed_no_mapping` — unmapped action skips (no error)
14. `test_on_step_completed_bridge_call_raises_degrades` — patch `record_skill_exercise` to raise (overrides SkillBridge's internal swallowing) → logs, doesn't crash
15. `test_on_step_completed_service_error_degrades` — AgentSkillService raises → logs, doesn't crash
16. `test_on_step_completed_empty_event_data` — both `{}` and `{"data": {}}` don't crash
17. `test_record_direct_exercise_prerequisite_not_met` — `acquire_skill` raises `ValueError` → logs at info level with "prerequisite not met" message, doesn't crash
18. `test_on_step_completed_unwraps_envelope` — pass full envelope `{"type": "bill_step_completed", "data": {"bill_id": "general_quarters", "step_id": "set_condition", "action": "cognitive_skill", "agent_id": "agent_1"}, "timestamp": 1234567890.0}` and verify the bridge correctly resolves the mapping and calls `record_skill_exercise`. This is the regression pin against the v2 envelope-unwrap bug.

**Custom mappings (2 tests):**
19. `test_add_mapping_runtime` — `add_mapping()` adds to mapping list
20. `test_custom_mapping_overrides_default` — exact-match custom mapping takes priority over default

**Stats (2 tests):**
21. `test_get_stats_initial` — returns zero counts on fresh bridge
22. `test_get_stats_after_exercises` — reflects exercise_count and mapping_count

---

## Engineering Principles Compliance

- **SOLID/S** — Pure listener. Does not mutate BillRuntime, step outcomes, or cognitive chain. Single responsibility: map step completions to skill exercises.
- **SOLID/D** — Constructor-injected SkillBridge, CognitiveSkillCatalog, AgentSkillService. No reaching into runtime internals. Wiring is in finalize.py, not inside the bridge.
- **Fail Fast** — Validates `agent_id` presence immediately. Everything else is log-and-degrade per "tracking must never block operations" tier.
- **DRY** — Reuses SkillBridge auto-acquire path when catalog entry exists. Direct path duplicates auto-acquire logic only because SkillBridge.record_skill_exercise requires a CognitiveSkillEntry object, not a bare skill_id (interface constraint, not oversight).
- **Law of Demeter** — Bridge accesses only its injected dependencies. No `self._bridge._service` chains. `skill_service` passed explicitly to avoid reaching into SkillBridge internals.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   | AD-618e | Cognitive JIT Bridge | Bill step completions → T3 skill acquisition via SkillBridge. 22 tests. | CLOSED |
   ```

2. **docs/development/roadmap.md** — Update the AD-618e row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ## AD-618e: Bill Step → Skill Compilation (Cognitive JIT Bridge)

   **Decision:** Bill step completions feed T3 skill proficiency via SkillBridge. Mapping is explicit (StepSkillMapping table), not AI-inferred. Default mappings cover action types; custom mappings can target specific bill+step pairs.

   **Rationale:** Explicit mappings are auditable, testable, and don't require ML inference. The Navy PQS model: demonstrated competence at a station earns a qualification. Auto-acquisition at FOLLOW level provides cold-start tolerance while allowing proficiency to grow through repeated execution.

   **Alternative considered:** Automatic skill inference from step descriptions using LLM. Rejected — too opaque, too expensive for a side-effect system, and violates "reference, not engine" principle.
   ```
