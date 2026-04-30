# AD-438 Ontology-Based Task Routing Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-438-ontology-task-routing.md`

## Summary

Implemented `TaskRouter` as a parallel routing-decision service that maps intent types to departments, resolves department agents through ontology posts and assignments, and falls back to broadcast when mappings or wired agents are unavailable. Startup finalization wires the router onto runtime, and the system API exposes the current mapping configuration.

`IntentBus`, `Dispatcher`, and ontology service behavior were not changed.

## Files Changed

- `src/probos/activation/task_router.py`
  - Added `RouteDecision` and `TaskRouter`.
- `src/probos/events.py`
  - Added `EventType.TASK_ROUTED`.
- `src/probos/startup/finalize.py`
  - Added finalize-time `TaskRouter` initialization near dispatcher wiring.
- `src/probos/routers/system.py`
  - Added task router configuration endpoint.
- `tests/test_ad438_ontology_task_routing.py`
  - Added 12 focused tests for routing decisions, mappings, ontology-directed routing, fallbacks, event existence, and endpoint behavior.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-438 tracking.

## Sections Implemented

- `### Section 1: Create TaskRouter`
  - Implemented in `src/probos/activation/task_router.py`.
- `### Section 2: Add TASK_ROUTED event type`
  - Implemented in `src/probos/events.py` in the existing TaskEvent section.
- `### Section 3: Wire TaskRouter in startup`
  - Implemented in `src/probos/startup/finalize.py` near `Dispatcher` wiring.
- `### Section 4: Add routing API endpoint`
  - Implemented in `src/probos/routers/system.py`.
- `## Tests`
  - Implemented in `tests/test_ad438_ontology_task_routing.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Create TaskRouter` — complete; route decision model, default mappings, runtime mapping registration, ontology lookup, directed strategy, broadcast fallback, and mapping listing exist.
- `### Section 2: Add TASK_ROUTED event type` — complete; event type exists in `EventType`.
- `### Section 3: Wire TaskRouter in startup` — complete; finalization creates `runtime._task_router` near dispatcher setup.
- `### Section 4: Add routing API endpoint` — complete; task router endpoint returns disabled or active mapping state under the existing `/api` prefix.
- `## Tests` — complete; 12 focused tests added.
- `## Tracking` — complete; tracker and build report updates added.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad438_ontology_task_routing.py -v -n 0`
  - Result: 12 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad438_ontology_task_routing.py tests/test_dispatch_wiring.py tests/test_api_system.py -v -n 0`
  - Result: 26 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10162 passed, 18 skipped.

## Deviations

- The prompt's route snippet included `/api/task-router` inside `system.py`. Because `system.py` already defines `router = APIRouter(prefix="/api", ...)`, the implemented decorator uses `/task-router` so the public endpoint is `/api/task-router` without double-prefixing.
- `EventType.TASK_ROUTED` was placed in the existing TaskEvent dispatcher section rather than after `KNOWLEDGE_TIER_LOADED`, because the live codebase already has a task-event section.
- Added 2 tests beyond the prompt's 10 to cover the task-router API endpoint.
