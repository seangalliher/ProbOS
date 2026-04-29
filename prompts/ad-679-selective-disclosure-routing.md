# AD-679: Selective Disclosure Routing

**Status:** Ready for builder
**Dependencies:** AD-677 (Context Provenance Metadata)
**Estimated tests:** ~8

---

## Problem

IntentBus `broadcast()` fans out to all indexed subscribers (or all
subscribers as fallback). There's no concept of information classification —
a security-sensitive intent reaches every subscriber equally. Similarly,
when context is injected into agent prompts, there's no filtering based
on the agent's clearance or the content's sensitivity.

AD-679 adds a disclosure routing layer that classifies content sensitivity
and filters recipients based on department-level clearance. This enables
need-to-know routing without replacing IntentBus mechanics.

## Fix

### Section 1: Create `DisclosureRouter`

**File:** `src/probos/mesh/disclosure.py` (new file)

```python
"""Selective Disclosure Routing (AD-679).

Classifies content sensitivity and filters intent recipients
based on department-level clearance. Does NOT replace IntentBus
routing — provides a filter layer that callers use to narrow
broadcast targets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class DisclosureLevel(IntEnum):
    """Content sensitivity classification (AD-679).

    Higher value = more restricted. Uses IntEnum for comparison operators.
    """

    PUBLIC = 0        # Available to all agents
    INTERNAL = 1      # Available to all department members
    RESTRICTED = 2    # Available to department chiefs + bridge
    CONFIDENTIAL = 3  # Bridge officers only
    CLASSIFIED = 4    # Captain only


# Department → default clearance level
DEFAULT_CLEARANCES: dict[str, DisclosureLevel] = {
    "bridge": DisclosureLevel.CONFIDENTIAL,
    "security": DisclosureLevel.RESTRICTED,
    "engineering": DisclosureLevel.INTERNAL,
    "medical": DisclosureLevel.RESTRICTED,
    "science": DisclosureLevel.INTERNAL,
    "operations": DisclosureLevel.INTERNAL,
    "core": DisclosureLevel.INTERNAL,
    "utility": DisclosureLevel.PUBLIC,
}


@dataclass(frozen=True)
class DisclosureDecision:
    """Result of a disclosure routing check (AD-679)."""

    agent_id: str
    permitted: bool
    agent_clearance: DisclosureLevel
    content_level: DisclosureLevel
    reason: str = ""


class DisclosureRouter:
    """Filters intent/context recipients by disclosure level (AD-679).

    Usage:
        router = DisclosureRouter()
        decisions = router.check_recipients(
            content_level=DisclosureLevel.RESTRICTED,
            candidates=["agent-1", "agent-2"],
            agent_departments={"agent-1": "security", "agent-2": "utility"},
        )
        permitted = [d.agent_id for d in decisions if d.permitted]
    """

    def __init__(
        self,
        *,
        clearance_overrides: dict[str, DisclosureLevel] | None = None,
    ) -> None:
        self._department_clearances = dict(DEFAULT_CLEARANCES)
        # Agent-specific clearance overrides (e.g., Captain always CLASSIFIED)
        self._agent_overrides: dict[str, DisclosureLevel] = clearance_overrides or {}

    def set_agent_clearance(
        self, agent_id: str, level: DisclosureLevel,
    ) -> None:
        """Override clearance for a specific agent."""
        self._agent_overrides[agent_id] = level

    def set_department_clearance(
        self, department: str, level: DisclosureLevel,
    ) -> None:
        """Override clearance for a department."""
        self._department_clearances[department] = level

    def get_clearance(
        self, agent_id: str, department: str = "",
    ) -> DisclosureLevel:
        """Resolve effective clearance for an agent.

        Priority: agent override > department default > PUBLIC.
        """
        if agent_id in self._agent_overrides:
            return self._agent_overrides[agent_id]
        if department:
            return self._department_clearances.get(
                department, DisclosureLevel.PUBLIC,
            )
        return DisclosureLevel.PUBLIC

    def check_recipients(
        self,
        *,
        content_level: DisclosureLevel,
        candidates: list[str],
        agent_departments: dict[str, str],
    ) -> list[DisclosureDecision]:
        """Check which candidates may receive content at the given level.

        Returns a DisclosureDecision for each candidate.
        """
        results: list[DisclosureDecision] = []
        for agent_id in candidates:
            department = agent_departments.get(agent_id, "")
            clearance = self.get_clearance(agent_id, department)
            permitted = clearance >= content_level

            results.append(DisclosureDecision(
                agent_id=agent_id,
                permitted=permitted,
                agent_clearance=clearance,
                content_level=content_level,
                reason=(
                    f"Clearance {clearance.name} >= {content_level.name}"
                    if permitted else
                    f"Clearance {clearance.name} < {content_level.name}"
                ),
            ))

        return results

    def filter_permitted(
        self,
        *,
        content_level: DisclosureLevel,
        candidates: list[str],
        agent_departments: dict[str, str],
    ) -> list[str]:
        """Return only permitted agent IDs (convenience method)."""
        decisions = self.check_recipients(
            content_level=content_level,
            candidates=candidates,
            agent_departments=agent_departments,
        )
        return [d.agent_id for d in decisions if d.permitted]

    def get_clearance_map(self) -> dict[str, str]:
        """Return department → clearance level name mapping."""
        return {
            dept: level.name
            for dept, level in self._department_clearances.items()
        }
```

### Section 2: Add `DISCLOSURE_FILTERED` event type

**File:** `src/probos/events.py`

Add near the intent-related events. Find the insertion point:

SEARCH:
```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
```

REPLACE:
```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
```

**Note:** If AD-677 has already built (adding `CONTEXT_PROVENANCE_INJECTED`
after this line) or AD-438 has already built (adding `TASK_ROUTED`), update
the SEARCH block to include those lines too.

### Section 3: Add disclosure routing API

**File:** `src/probos/routers/system.py`

```python
@router.get("/api/disclosure-clearances")
async def get_disclosure_clearances(runtime: Any = Depends(get_runtime)) -> dict:
    """Return disclosure clearance configuration (AD-679)."""
    disclosure_router = getattr(runtime, "_disclosure_router", None)
    if not disclosure_router:
        return {"status": "disabled"}
    return {
        "status": "active",
        "department_clearances": disclosure_router.get_clearance_map(),
    }
```

### Section 4: Wire DisclosureRouter in startup

**File:** `src/probos/startup/finalize.py`

Add near the IntentBus or security wiring:

```python
    # AD-679: Selective Disclosure Routing
    from probos.mesh.disclosure import DisclosureRouter
    disclosure_router = DisclosureRouter()
    runtime._disclosure_router = disclosure_router
    logger.info("AD-679: DisclosureRouter initialized")
```

## Tests

**File:** `tests/test_ad679_selective_disclosure_routing.py`

8 tests:

1. `test_disclosure_level_ordering` — verify PUBLIC < INTERNAL < RESTRICTED
   < CONFIDENTIAL < CLASSIFIED via integer comparison
2. `test_default_clearances` — verify bridge=CONFIDENTIAL, security=RESTRICTED,
   utility=PUBLIC
3. `test_check_recipients_permits_high_clearance` — security agent (RESTRICTED)
   receiving INTERNAL content → permitted
4. `test_check_recipients_blocks_low_clearance` — utility agent (PUBLIC)
   receiving RESTRICTED content → not permitted
5. `test_agent_override_takes_precedence` — set agent override to CLASSIFIED,
   verify it overrides department default
6. `test_filter_permitted_returns_only_allowed` — 3 candidates, 1 blocked →
   `filter_permitted()` returns only 2
7. `test_disclosure_decision_reason_text` — verify permitted decision includes
   ">=" in reason, blocked includes "<"
8. `test_disclosure_filtered_event_exists` — verify `EventType.DISCLOSURE_FILTERED`
   exists

## What This Does NOT Change

- IntentBus `broadcast()` unchanged — DisclosureRouter is a separate filter
  layer, not integrated into broadcast
- IntentBus subscriber index unchanged
- Agent subscription patterns unchanged
- DepartmentService unchanged — DisclosureRouter reads department info
  from callers, not from ontology directly
- Does NOT automatically apply disclosure filtering to broadcast — callers
  must explicitly use DisclosureRouter
- Does NOT add content classification heuristics — callers must set
  DisclosureLevel explicitly
- Does NOT modify IntentMessage dataclass

## Tracking

- `PROGRESS.md`: Add AD-679 as COMPLETE
- `docs/development/roadmap.md`: Update AD-679 status

## Acceptance Criteria

- `DisclosureLevel` enum with 5 levels (PUBLIC through CLASSIFIED)
- `DisclosureRouter` checks agent clearance against content level
- Department-level default clearances configured
- Agent-specific clearance overrides supported
- `check_recipients()` returns per-agent permit/deny decisions
- `filter_permitted()` convenience method returns allowed agent IDs
- `EventType.DISCLOSURE_FILTERED` exists
- All 8 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# IntentBus broadcast candidate selection
grep -n "_intent_index\|fallback" src/probos/mesh/intent.py
  34: self._intent_index: dict[str, set[str]]
  403-418: candidate selection logic

# DepartmentService
grep -n "class DepartmentService" src/probos/ontology/departments.py
  8: class DepartmentService

# No existing disclosure routing
grep -rn "DisclosureRouter\|disclosure_router\|DisclosureLevel" src/probos/ → no matches

# Events insertion point
grep -n "KNOWLEDGE_TIER_LOADED" src/probos/events.py
  169: KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
```
