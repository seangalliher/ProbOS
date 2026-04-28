# Build Report: AD-668 Salience Filter

**Prompt:** prompts/ad-668-salience-filter.md  
**Builder:** 2026-04-27, GitHub Copilot  
**Status:** Complete with waived timing-sensitive full-suite failure

## Files Changed
- src/probos/cognitive/salience_filter.py
- src/probos/cognitive/agent_working_memory.py
- src/probos/config.py
- tests/test_ad668_salience_filter.py
- PROGRESS.md
- DECISIONS.md
- docs/development/roadmap.md
- prompts/build-reports/ad-668-salience-filter-build.md

## Sections Implemented
- Section 1: Added `SalienceScore` dataclass.
- Section 2: Added `SalienceFilter` constructor, normalized weights, optional NoveltyGate injection, and `from_config()`.
- Section 3: Implemented relevance, recency, novelty, urgency, social component scoring and weighted aggregation.
- Section 4: Added `should_promote()` convenience method.
- Section 5: Added capped `BackgroundStream`.
- Section 6: Added `SalienceConfig` and `SystemConfig.salience`.
- Section 7: Integrated optional salience gating into AgentWorkingMemory record methods and background stream count serialization.
- Section 8: Added 35 AD-668 tests.
- Section 9: Updated PROGRESS.md, DECISIONS.md, and docs/development/roadmap.md.

## Post-Build Section Audit
- Section 1: Implemented in `salience_filter.py`.
- Section 2: Implemented in `SalienceFilter`.
- Section 3: Implemented in `SalienceFilter._score_*()` and `score()`.
- Section 4: Implemented in `SalienceFilter.should_promote()`.
- Section 5: Implemented in `BackgroundStream`.
- Section 6: Implemented in `config.py`.
- Section 7: Implemented in `AgentWorkingMemory` constructor, public accessors, `_passes_salience_gate()`, record methods, and `to_dict()`.
- Section 8: Implemented in `tests/test_ad668_salience_filter.py`.
- Section 9: Trackers updated.

## Tests
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -k "TestSalienceScore or TestSalienceFilter or TestScoreR or TestScoreN or TestScoreU or TestScoreS or TestScoreAgg or TestBackgroundStream" -n 0`: 29 passed, 6 deselected
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -k "from_config" -n 0`: 1 passed, 34 deselected
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -k "TestWorkingMemoryIntegration" -n 0`: 6 passed, 29 deselected
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -n 0`: 35 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py tests/test_bf125_working_memory_desync.py tests/test_bf127_crew_only_wm_persistence.py -v -n 0`: 57 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x -n 0`: 3 passed
- `git diff --check -- src/probos/cognitive/salience_filter.py src/probos/cognitive/agent_working_memory.py src/probos/config.py tests/test_ad668_salience_filter.py tests/test_agent_working_memory.py`: passed with no output
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`: stopped at 1 failed, 4059 passed, 292 warnings
- Serial classification rerun for `tests/test_ad585_tiered_knowledge.py::TestCacheEntry::test_stale_after_max_age`: first retry failed, immediate second retry passed

## Full-Suite Classification
The full-suite failure was the known timing-sensitive AD-585 cache freshness test:

```text
FAILED tests/test_ad585_tiered_knowledge.py::TestCacheEntry::test_stale_after_max_age
assert True is False
```

The same test passed on immediate serial retry and is unrelated to AD-668. It is treated as waived timing/load behavior under the active sweep waiver.

## Notes
- `AgentWorkingMemory` salience filtering is opt-in; existing default construction still admits entries exactly as before.
- Demoted entries are not written to legacy ring buffers or named buffers; they are stored only in `BackgroundStream`.
- `SalienceFilter.score()` remains synchronous and side-effect-free.
