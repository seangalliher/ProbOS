# AD-438: Ontology-Based Task Routing

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~10

---

## Problem

The IntentBus (`mesh/intent.py`) routes intents via a simple subscriber
index: agents subscribe to intent names, and `broadcast()` fans out to
all matching subscribers (or all subscribers if no index match). There's
no semantic routing based on the ontology — the Bus doesn't know which
department handles "threat_analysis" vs "power_diagnostic".

The `Dispatcher` (`activation/dispatcher.py`) routes `TaskEvent` objects
to agent queues but only handles explicit `AgentTarget` resolution (by
agent_id, capability, or broadcast). Neither system uses the ontology's
department→agent mapping for intelligent routing.

AD-438 adds a `TaskRouter` that maps intent types to departments using
the ontology, enabling directed routing when the ontology knows who
handles a given intent, with broadcast fallback for novel/unknown intents.

## Fix

### Section 1: Create `TaskRouter`

**File:** `src/probos/activation/task_router.py` (new file)

```python
"""Ontology-Based Task Routing (AD-438).

Maps intent types to departments and agents using the ontology's
department→post→agent assignments. When the ontology knows which
department handles an intent type, routes directly. Falls back to
broadcast for unknown intent types.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteDecision:
    """Result of a routing lookup (AD-438)."""

    intent_type: str
    strategy: str  # "directed" | "broadcast"
    department: str | None = None  # Target department (if directed)
    agent_ids: list[str] = field(default_factory=list)
    reason: str = ""


class TaskRouter:
    """Maps intent types to departments via ontology (AD-438).

    Two routing strategies:
    - DIRECTED: ontology maps intent → department → agents. Only
      those agents receive the intent.
    - BROADCAST: no ontology mapping exists. Falls back to
      IntentBus broadcast (all subscribers self-select).

    The router does NOT replace IntentBus or Dispatcher. It provides
    a routing decision that callers use to choose between directed
    send and broadcast.
    """

    def __init__(
        self,
        *,
        ontology: Any | None = None,
    ) -> None:
        self._ontology = ontology
        # Static intent → department mappings (extensible at runtime)
        self._intent_department_map: dict[str, str] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default intent → department mappings."""
        self._intent_department_map.update({
            # Security intents
            "threat_analysis": "security",
            "security_assessment": "security",
            "access_review": "security",
            # Engineering intents
            "power_diagnostic": "engineering",
            "system_repair": "engineering",
            "performance_optimization": "engineering",
            # Medical intents
            "wellness_check": "medical",
            "crew_health_report": "medical",
            # Science intents
            "data_analysis": "science",
            "anomaly_investigation": "science",
            "research_query": "science",
            # Operations intents
            "resource_allocation": "operations",
            "scheduling": "operations",
        })

    def register_mapping(self, intent_type: str, department: str) -> None:
        """Register or override an intent → department mapping."""
        self._intent_department_map[intent_type] = department
        logger.debug(
            "AD-438: Registered %s → %s", intent_type, department,
        )

    def resolve(self, intent_type: str) -> RouteDecision:
        """Resolve routing for an intent type.

        Returns a RouteDecision indicating directed or broadcast strategy.
        """
        department = self._intent_department_map.get(intent_type)

        if department is None:
            return RouteDecision(
                intent_type=intent_type,
                strategy="broadcast",
                reason="No ontology mapping for this intent type",
            )

        # Look up agents in the department via ontology public API
        agent_ids: list[str] = []
        if self._ontology:
            try:
                # Use OntologyService public methods (not private _dept)
                posts = self._ontology.get_posts(department_id=department)
                post_ids = {p.id for p in posts}
                assignments = self._ontology.get_all_assignments()
                for assignment in assignments:
                    if assignment.post_id in post_ids and assignment.agent_id:
                        agent_ids.append(assignment.agent_id)
            except Exception:
                logger.debug(
                    "AD-438: Ontology lookup failed for department %s",
                    department, exc_info=True,
                )

        if not agent_ids:
            # Department known but no agents wired yet — broadcast fallback
            return RouteDecision(
                intent_type=intent_type,
                strategy="broadcast",
                department=department,
                reason=f"Department '{department}' has no wired agents",
            )

        return RouteDecision(
            intent_type=intent_type,
            strategy="directed",
            department=department,
            agent_ids=agent_ids,
            reason=f"Ontology: {intent_type} → {department}",
        )

    def list_mappings(self) -> dict[str, str]:
        """Return all registered intent → department mappings."""
        return dict(self._intent_department_map)
```

### Section 2: Add `TASK_ROUTED` event type

**File:** `src/probos/events.py`

Add near the task event section. Find the insertion point:

```
grep -n "TASK_EVENT_EMITTED\|task_event" src/probos/events.py
```

If no existing task event, add after `KNOWLEDGE_TIER_LOADED`:

SEARCH:
```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
```

REPLACE:
```python
    KNOWLEDGE_TIER_LOADED = "knowledge_tier_loaded"
    TASK_ROUTED = "task_routed"  # AD-438
```

**Note:** If AD-677 has already built (adding `CONTEXT_PROVENANCE_INJECTED`
after this line), update the SEARCH block to include that line too.

### Section 3: Wire TaskRouter in startup

**File:** `src/probos/startup/finalize.py`

Find the section where the Dispatcher is initialized. Grep for:
```
grep -n "Dispatcher\|dispatcher" src/probos/startup/finalize.py
```

Add TaskRouter initialization near the Dispatcher wiring:

```python
    # AD-438: Ontology-Based Task Routing
    from probos.activation.task_router import TaskRouter
    task_router = TaskRouter(ontology=ontology)
    runtime._task_router = task_router
    logger.info(
        "AD-438: TaskRouter initialized with %d mappings",
        len(task_router.list_mappings()),
    )
```

### Section 4: Add routing API endpoint

**File:** `src/probos/routers/system.py`

Add a `GET /api/task-router` endpoint following the existing health endpoint pattern:

```python
@router.get("/api/task-router")
async def get_task_router(request: Request) -> dict:
    """Return task routing configuration (AD-438)."""
    runtime = request.app.state.runtime
    task_router = getattr(runtime, "_task_router", None)
    if not task_router:
        return {"status": "disabled", "mappings": {}}
    return {
        "status": "active",
        "mappings": task_router.list_mappings(),
    }
```

## Tests

**File:** `tests/test_ad438_ontology_task_routing.py`

10 tests:

1. `test_route_decision_creation` — create a `RouteDecision`, verify fields
2. `test_default_mappings_exist` — verify default intent → department mappings
   include `threat_analysis → security`, `power_diagnostic → engineering`
3. `test_resolve_known_intent_no_ontology` — resolve `threat_analysis` with
   no ontology → broadcast fallback (department known, no agents)
4. `test_resolve_unknown_intent` — resolve `unknown_intent` → broadcast strategy
5. `test_resolve_directed_with_ontology` — mock ontology with wired agents →
   directed strategy with agent_ids populated
6. `test_register_custom_mapping` — register `custom_intent → science`, verify
   `resolve("custom_intent").department == "science"`
7. `test_broadcast_reason_includes_no_mapping` — verify broadcast reason text
8. `test_directed_reason_includes_department` — verify directed reason mentions
   the department
9. `test_list_mappings_returns_all` — verify `list_mappings()` returns dict of
   all registered mappings
10. `test_task_routed_event_type_exists` — verify `EventType.TASK_ROUTED` exists

## What This Does NOT Change

- IntentBus `broadcast()` / `send()` / `dispatch_async()` unchanged
- Dispatcher `dispatch()` unchanged — TaskRouter is a parallel system
  that provides routing decisions, not routing execution
- OntologyService unchanged — TaskRouter reads from it, doesn't modify it
- No changes to agent subscription patterns
- Does NOT add automatic routing — callers must explicitly use TaskRouter.
  Future AD can integrate TaskRouter into IntentBus.broadcast()
- Does NOT replace the subscriber index in IntentBus

## Tracking

- `PROGRESS.md`: Add AD-438 as COMPLETE
- `docs/development/roadmap.md`: Update AD-438 status

## Acceptance Criteria

- `TaskRouter` with `resolve()` returning `RouteDecision` exists
- Default intent → department mappings registered
- `register_mapping()` allows runtime extension
- Broadcast fallback for unknown intents
- Directed routing when ontology maps intent → department → agents
- `EventType.TASK_ROUTED` exists
- All 10 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# IntentBus routing
grep -n "def broadcast\|def send\|def dispatch_async" src/probos/mesh/intent.py
  309: send(), 369: broadcast(), 456: publish(), 460: dispatch_async()

# Existing Dispatcher
grep -n "class Dispatcher" src/probos/activation/dispatcher.py
  40: class Dispatcher — routes TaskEvents to cognitive queues

# OntologyService department queries (public API)
grep -n "def get_posts\|def get_all_assignments\|def get_agent_department" src/probos/ontology/service.py
  117: get_posts(department_id) → list[Post]
  150: get_all_assignments() → list[Assignment]
  156: get_agent_department(agent_type) → str | None

# Assignment model
grep -n "class Assignment" src/probos/ontology/models.py
  47: agent_type, post_id, callsign, agent_id (filled at runtime)

# DepartmentService
grep -n "class DepartmentService" src/probos/ontology/departments.py
  8: class DepartmentService

# No existing task routing
grep -rn "TaskRouter\|task_router" src/probos/ → no matches
```
