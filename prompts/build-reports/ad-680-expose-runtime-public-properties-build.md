# AD-680 Runtime Public API Promotion Build Report

**Date:** 2026-04-29
**Status:** Complete
**Prompt:** `prompts/ad-680-expose-runtime-public-properties.md`
**Builder:** GitHub Copilot

## Files Changed

- `src/probos/runtime.py`
  - Widened `emit_event()` typing to accept `EventType` and added read-only `emergence_metrics_engine`.
- `src/probos/protocols.py`
  - Widened `EventEmitterProtocol.emit_event()` typing to accept `EventType`.
- `src/probos/startup/finalize.py`, `src/probos/routers/*.py`, `src/probos/cognitive/*.py`, `src/probos/proactive.py`, `src/probos/agents/medical/vitals_monitor.py`, `src/probos/sop/jit_bridge.py`
  - Migrated runtime private `_emit_event` and `_emergence_metrics_engine` access to public APIs.
- `tests/test_ad680_public_runtime_api.py`
  - Added 4 AD-680 public API and invariant tests.
- Event-adjacent test fixtures
  - Updated fake runtimes to assert public `emit_event()` calls where migrated production code now uses the public API.
- `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`
  - Added AD-680 tracking and recorded the one-shot private-to-public migration precedent.

## Sections Implemented

- `### Section 1: Update emit_event type hint to accept EventType` - implemented on runtime and protocol.
- `### Section 2: Add emergence_metrics_engine property` - added read-only property, no setter.
- `### Section 3: Migrate all external _emit_event call sites` - migrated runtime/rt/self._runtime private event access outside `runtime.py`.
- `### Section 4: Migrate all external _emergence_metrics_engine accesses` - migrated runtime-like `getattr(..., "_emergence_metrics_engine", None)` sites to the public property name.
- `## Tests` - implemented all 4 requested tests.
- `## Tracking` - updated project trackers and this build report.

## Post-Build Section Audit

- `## Problem` - addressed by removing external private runtime access from the listed modules.
- `### Section 1` - `EventType` appears in both public `emit_event` signatures and is asserted by test.
- `### Section 2` - property returns the existing backing attribute and has no setter.
- `### Section 3` - invariant scan confirms zero external `runtime._emit_event`, `rt._emit_event`, or `self._runtime._emit_event` source matches outside `runtime.py`.
- `### Section 4` - external runtime-like private emergence access was migrated; internal `DreamingEngine._emergence_metrics_engine` state remains untouched.
- `## What This Does NOT Change` - `_emit_event` remains the owning-class private implementation; non-runtime `self._emit_event` callback attributes remain untouched.
- `## Acceptance Criteria` - AD-680 focused and adjacent regression gates passed; full serial suite reserved for final sweep gate per revised execution instruction.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad680_public_runtime_api.py -v -n 0`
  - Result: 4 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad680_public_runtime_api.py tests/test_runtime.py tests/test_finalize.py tests/test_builder_api.py tests/test_hxi_chat_integration.py tests/test_agent_designer_cognitive.py tests/test_proactive.py tests/test_ad566e_collective_tests.py tests/test_api_system.py tests/test_bf206_confab_feedback.py tests/test_fallback_learning.py tests/test_multi_agent_replay_dispatch.py tests/test_dispatch_wiring.py tests/test_ad666_sensorium.py -q -n 0`
  - Result: 382 passed, 2 skipped.

## Deviations from Prompt

- None. Full-suite `-n 0` is being reserved for the final sweep gate per the revised execution instruction because xdist is known to produce environmental failures and serial full-suite runs are slow.
