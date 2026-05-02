# AD-467 Build Report

**Date:** 2026-05-01
**Builder:** Wave 7 continuous-build (4 of 5)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+5: EventTypes | `src/probos/events.py` | ✅ Added `RESOURCE_ALLOCATED`, `TASK_SCHEDULED`, `WORKFLOW_STARTED` after AD-528 events |
| Section 1: Package init | `src/probos/agents/operations/__init__.py` (new) | ✅ Owns directory creation |
| Section 2: ResourceAllocatorAgent | `src/probos/agents/operations/resource_allocator.py` (new) | ✅ Uses `pool.current_size` (real `@property` at `pool.py:53`); defensive `getattr(..., 0)` for stubs |
| Section 3: SchedulerAgent | `src/probos/agents/operations/scheduler.py` (new) | ✅ Per-task cadence dict; emits `TASK_SCHEDULED` |
| Section 4: CoordinatorAgent | `src/probos/agents/operations/coordinator.py` (new) | ✅ Active-workflow registry; emits `WORKFLOW_STARTED` |
| Section 6: OperationsConfig | `src/probos/config.py` | ✅ Added Pydantic class + field on `SystemConfig` |
| Section 7a: Template registration | `src/probos/runtime.py` | ✅ Inserted after AD-457 engineering crew block (lines 632→); uses `OpsCoordinatorAgent`/`OpsResourceAllocatorAgent`/`OpsSchedulerAgent` import aliases to avoid collision with the bundled cognitive `SchedulerAgent` from `probos.agents` (line 38 / line 599) |
| Section 7b: Pool spawn | `src/probos/startup/agent_fleet.py` | ✅ Inserted after AD-457 engineering block (line 165); pool naming `operations_resource_allocator`/`operations_scheduler`/`operations_coordinator` |
| Tests | `tests/test_ad467_operations_crew.py` (new) | ✅ 14/14 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4181` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad467_operations_crew.py -v -n 0` → **14/14 passed in 0.24s**
- Smoke: `tests/test_runtime_discovery.py` (5 tests) → **5/5 passed in 20.99s** (verifies template-registration collision was resolved)
- Full parallel gate: **10,448 passed (+14 vs AD-528 baseline 10,434), 14 skipped, 151 warnings in 344.13s**

## Notes / Decisions

- **Name collision resolved:** the prompt's draft template names (`scheduler`, `coordinator`, `resource_allocator`) collided with the existing bundled cognitive `SchedulerAgent` from `probos.agents` (registered as template `"scheduler"` at `runtime.py:599`). Resolution: prefix all three operations templates and `agent_type` strings with `operations_` (`operations_resource_allocator`, `operations_scheduler`, `operations_coordinator`) and import the operations classes with `as Ops*` aliases inside `__init__` to avoid the local-binding `UnboundLocalError`. This matches the Wave 7 dispatch reminder: "Pool naming `operations_<role>` ... mirrors AD-457 engineering_<role> precedent."
- ResourceAllocator uses `pool.current_size` (real `@property` at `pool.py:53`) and `pool.target_size` (real instance attribute at `pool.py:42`); defensive `getattr(..., 0)` preserved for test stubs (Wave 5 superset-filter discipline).
- All three agents are `HeartbeatAgent` subclasses; no consensus paths affected; no destructive intents.
- LLM Cost Tracker wholesale-deferred to AD-467d — depends on AD-463 ModelRegistry MODEL_ROUTED event payload (sibling Wave 7).
- WorkflowDefinition API deferred to AD-467b; Response-Time Scaling deferred to AD-467c.
- v1 emits 3 event types but no production handler currently consumes them — AD-467b/c/d will wire consumers per capability.

## Pre-Commit Sanity Check

10 files changed, ~480 insertions, 1 deletion (roadmap status flip). Max per-file deletion: 1 line. Well under 200-line threshold.
