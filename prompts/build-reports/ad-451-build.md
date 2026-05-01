# AD-451 Build Report

**Date:** 2026-05-01
**Commit:** (pending)
**Builder:** Wave 6 continuous-build

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0 + 4: EventTypes | `src/probos/events.py` | ✅ Added `VALIDATION_RECONCILIATION_REQUESTED`, `VALIDATION_OUTCOME_VERIFIED` after `AGENT_SELF_NAMED` |
| Section 1: TwoStageVerifier | `src/probos/cognitive/validation_framework.py` (new) | ✅ + module-level `_MetadataCheck` flat dataclass |
| Section 2: SelfVerificationHook Protocol | `src/probos/cognitive/validation_framework.py` | ✅ `@runtime_checkable` decorated |
| Section 3: ReconciliationEscalator | `src/probos/cognitive/validation_framework.py` | ✅ wires TwoStageVerifier as real consumer in `_invoke_third` |
| Section 5: ValidationFrameworkConfig | `src/probos/config.py` | ✅ added Pydantic class + field after `orders: OrdersConfig` |
| Section 6: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ `runtime.reconciliation_escalator` (public) after AD-440 OrderManager |
| Tests | `tests/test_ad451_validation_framework.py` (new) | ✅ 15/15 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4117` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad451_validation_framework.py -v -n 0` → **15/15 passed in 0.27s**
- Full parallel gate: **10,355 passed (+15 vs AD-491 baseline 10,340), 14 skipped, 151 warnings in 347.00s**

## Notes / Decisions

- **Layer boundary:** `cognitive/validation_framework.py` imports `RedTeamAgent` under `TYPE_CHECKING` (the runtime dependency is injected via constructor). This crosses the `cognitive → agents` layer boundary. Added a documented `ALLOWED_EXCEPTIONS` entry in `tests/test_layer_boundaries.py` mirroring the existing `cognitive/decomposer.py → consensus.escalation` precedent.
- All 4 cross-cutting fixes from second-pass review are honored: TwoStageVerifier has a real production consumer (`_invoke_third`), `_MetadataCheck` is flat module-level, `@runtime_checkable` is on `SelfVerificationHook`, `_invoke_third` excludes primary/secondary IDs and uses `random.choice`.
- Wave 5 retrospective convention #1 honored: `runtime.reconciliation_escalator` is public.

## Pre-Commit Sanity Check

7 files changed, 575 insertions, 4 deletions. Max per-file deletion: 4 lines (events.py rewrite of one-line). Well under 200-line threshold.
