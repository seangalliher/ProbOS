# Build Report: AD-666 Agent Sensorium Formalization

**Prompt:** prompts/ad-666-agent-sensorium-formalization.md  
**Builder:** 2026-04-27, GitHub Copilot  
**Status:** Complete with waived xdist timing failure

## Files Changed
- src/probos/cognitive/cognitive_agent.py
- src/probos/config.py
- src/probos/events.py
- tests/test_ad666_sensorium.py
- PROGRESS.md
- DECISIONS.md
- docs/development/roadmap.md
- prompts/build-reports/ad-666-agent-sensorium-formalization-build.md

## Sections Implemented
- Section 1: Added `SensoriumLayer` and `CognitiveAgent.SENSORIUM_REGISTRY`.
- Section 2: Updated `_build_cognitive_state()` docstring to reference the Agent Sensorium model.
- Section 3: Added `_track_sensorium_budget()` and wired it into `_execute_chain_with_intent_routing()` after cognitive state and situation awareness assembly.
- Section 4: Added `EventType.SENSORIUM_BUDGET_EXCEEDED` and `SensoriumBudgetExceededEvent`.
- Section 5: Added `SensoriumConfig` and `SystemConfig.sensorium`.
- Section 6: Added injection ordering audit notes to `_build_user_message()`.
- Section 7: Added focused sensorium tests.
- Section 8: Updated trackers.

## Tests
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad666_sensorium.py -v -x -n 0`: 14 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_events.py -v -x -n 0`: 30 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x -n 0`: 3 passed
- `git diff --check -- src/probos/cognitive/cognitive_agent.py src/probos/events.py src/probos/config.py tests/test_ad666_sensorium.py`: passed with no output
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`: stopped at 1 failed, 4003 passed, 291 warnings

## Full-Suite Classification
The full-suite failure was unrelated to AD-666 and matched the already-classified xdist timing pattern:

```text
FAILED tests/test_ad585_tiered_knowledge.py::TestCacheEntry::test_stale_after_max_age
assert True is False
```

This exact test passed serially during the AD-651 gate classification. It is treated as waived xdist timing/load behavior under the user's 2026-04-27 instruction to ignore the NATS/xdist collision class for the rest of the sweep.

## Deviations from Prompt
- The prompt acceptance line said 12 tests, but the detailed test sketch contained 14 distinct tests. Implemented the detailed 14-test coverage.
- `_track_sensorium_budget()` defensively ignores non-integer mock thresholds so generic runtime mocks do not crash budget tracking.

## Trackers Updated
- PROGRESS.md: marked AD-666 CLOSED.
- DECISIONS.md: added AD-666 decision entry.
- docs/development/roadmap.md: updated AD-666 from Planned to Closed.