# AD-499 Build Report

**Date:** 2026-05-01
**Builder:** Builder agent
**Status:** Complete

## Files Changed

- `src/probos/naming.py` (new, 144 lines)
- `src/probos/events.py` (+2)
- `src/probos/config.py` (+8)
- `src/probos/startup/communication.py` (+22, includes `EventType` import)
- `src/probos/agent_onboarding.py` (+27)
- `tests/test_ad499_naming_conventions.py` (new, 130 lines, 17 tests)
- `PROGRESS.md` (+2)
- `docs/development/roadmap.md` (status flip planned → complete)

## Sections Implemented

- Section 0: Event Types ✓ (SHIP_NAMED, AGENT_SELF_NAMED)
- Section 1: naming.py — three policy classes ✓
- Section 1 (extended): AgentNamingPolicy constructor merges defaults ✓
- Section 2: EventTypes added ✓
- Section 3: NamingConfig + SystemConfig wiring ✓
- Section 4: ShipNamingPolicy in `startup/communication.py:399` (uses `emit_event_fn`) ✓
- Section 5: AgentNamingPolicy in `agent_onboarding.py:534` + AGENT_SELF_NAMED log emit after outer-caller `set_callsign` (line 232) ✓
- Section 6: REMOVED ✓ (federation integration deferred per prompt)

## Post-Build Section Audit

All `###` sections from the prompt map to live edits. Section 6 is documented as REMOVED (no implementation expected).

## Test Results

```
pytest tests/test_ad499_naming_conventions.py -v -n 0
17 passed in 0.33s
```

Coverage: 17 tests across the 10-test plan (added boundary tests for empty input, extra-banned-words merge, dataclass shape, and distinct-instance distinct-name probability per Recommended R3).

## Deviations

- Section 5 Step 2 (AGENT_SELF_NAMED emit) uses `chosen_callsign` (the live local variable at the outer-caller insertion seam, line 228) rather than `chosen` (the prompt's literal — but `chosen` is a different scope inside `run_naming_ceremony`). The variable name in the prompt was a regression introduced by the second-pass review; the actual code uses the correct in-scope name.
- Added `EventType` import to `startup/communication.py` (the prompt's verify-first claimed it was already imported; live code did not have it).

## Engineering Principles Compliance

- ✓ SOLID: three small classes, single-responsibility each
- ✓ Demeter: no `_private` cross-module access; `emit_event_fn` parameter used (not `runtime._emit_event`)
- ✓ Type annotations on all public methods
- ✓ Logging with context
- ✓ No fire-and-forget `create_task`
- ✓ Field validation via `field(default_factory=list)` on Pydantic config
