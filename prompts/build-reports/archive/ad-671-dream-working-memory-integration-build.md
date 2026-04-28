# AD-671 Dream-Working Memory Integration Build Report

**Date:** 2026-04-27
**Status:** Complete
**Prompt:** `prompts/ad-671-dream-working-memory-integration.md`

## Summary

Implemented AD-671 as an optional bidirectional bridge between `AgentWorkingMemory` and `DreamingEngine`. The bridge mechanically snapshots active working memory into a reflection-source session summary episode before dream consolidation, and seeds working memory with bounded dream insight observations after Step 15.

No existing dream steps were modified, no LLM calls were added, and storage remains in the async dreaming layer.

## Files Changed

- `src/probos/config.py`
  - Added `DreamWMConfig`.
  - Added `SystemConfig.dream_wm`.
- `src/probos/types.py`
  - Added `DreamReport.wm_entries_flushed` and `DreamReport.wm_priming_entries`.
- `src/probos/cognitive/dream_wm_bridge.py`
  - Added `DreamWorkingMemoryBridge` with `pre_dream_flush()` and `post_dream_seed()`.
- `src/probos/cognitive/dreaming.py`
  - Added optional `dream_wm_bridge` constructor parameter.
  - Added `set_agent_wm()` for late-bound working memory.
  - Added pre-dream flush before Step 0 and post-dream seed after Step 15.
  - Added WM bridge counters to `DreamReport` and dream-cycle logging.
  - Added getattr guards for `__new__`-constructed test fixtures.
- `src/probos/startup/dreaming.py`
  - Created the bridge when `config.dream_wm.enabled` is true and passed it into `DreamingEngine`.
- `tests/test_ad671_dream_wm_integration.py`
  - Added 13 tests covering pre-dream flush, post-dream seed, config defaults, `SystemConfig`, `DreamReport` counters, and constructor integration.
- `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`
  - Updated AD-671 tracking.

## Section Audit

- `## Section 1: DreamWMConfig` — implemented in `src/probos/config.py`; config gate passed.
- `## Section 2: DreamReport Extension` — implemented in `src/probos/types.py`.
- `## Section 3: DreamWorkingMemoryBridge` — implemented in `src/probos/cognitive/dream_wm_bridge.py`.
- `## Section 4: DreamingEngine Integration` — implemented constructor parameter, setter, pre-dream flush, post-dream seed, report fields, and log fields.
- `## Section 5: Startup Wiring` — implemented bridge creation and constructor injection in `src/probos/startup/dreaming.py`.
- `## Section 6: Tests` — implemented focused AD-671 tests.
- `## Targeted Test Commands` — focused tests and dream/config regression slice passed.
- `## Tracking` — updated project trackers and this build report.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x -n 0`
  - Result: 3 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad671_dream_wm_integration.py -v -x -n 0`
  - Result: 13 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py tests/test_dreaming.py tests/test_bf106_dreaming_di.py tests/test_ad671_dream_wm_integration.py -v -x -n 0`
  - Result: 64 passed, 1 warning.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_dream_step_7f.py::test_step_7f_runs_decay tests/test_config.py tests/test_dreaming.py tests/test_bf106_dreaming_di.py tests/test_ad671_dream_wm_integration.py -v -x -n 0`
  - Result after getattr guard fix: 65 passed, 2 warnings.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
  - First run: stopped on AD-671 `__new__` guard failure plus known NATS/xdist failures after 5821 passed. The guard failure was fixed.
  - Second run: stopped only on known NATS/JetStream stream/store collision class after 5214 passed, 3 skipped. Classified waived by Captain instruction.

## Notes

- The bridge returns a session-summary `Episode`; it does not store directly.
- Post-dream priming uses `record_observation()` and `knowledge_source="procedural"` as specified.
- No named-buffer-specific logic was added; the bridge consumes `AgentWorkingMemory.to_dict()`.
- No async scheduler or new dream step behavior was added.
