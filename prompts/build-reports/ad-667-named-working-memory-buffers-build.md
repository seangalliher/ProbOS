# Build Report: AD-667 Named Working Memory Buffers

**Prompt:** prompts/ad-667-named-working-memory-buffers.md  
**Builder:** 2026-04-27, GitHub Copilot  
**Status:** Complete with waived NATS/xdist full-suite failure

## Files Changed
- src/probos/cognitive/agent_working_memory.py
- src/probos/config.py
- tests/test_agent_working_memory.py
- PROGRESS.md
- DECISIONS.md
- docs/development/roadmap.md
- prompts/build-reports/ad-667-named-working-memory-buffers-build.md

## Sections Implemented
- Section 1: Added `NamedBuffer` dataclass with append, render, entries, and len support.
- Section 2: Added four named buffer instances plus `get_buffer()` and `buffer_names` accessors.
- Section 3: Dual-wrote existing record methods to Duty/Social/Ship/Engagement buffers; mirrored engagements and cognitive state updates.
- Section 4: Added `render_buffers()` for selective named-buffer rendering with proportional budget allocation and unknown-name warnings.
- Section 5: Added per-buffer `WorkingMemoryConfig` budgets.
- Section 6: Added named buffer serialization/restoration while preserving legacy restore compatibility.
- Section 7: Added `TestNamedBuffers` with 15 focused tests.
- Section 8: Updated PROGRESS.md, DECISIONS.md, and docs/development/roadmap.md.

## Post-Build Section Audit
- Section 1: Implemented in `NamedBuffer`.
- Section 2: Implemented in `AgentWorkingMemory.__init__()`, `get_buffer()`, and `buffer_names`.
- Section 3: Implemented in `record_action()`, `record_observation()`, `record_conversation()`, `record_event()`, `record_reasoning()`, `add_engagement()`, and `update_cognitive_state()`.
- Section 4: Implemented in `render_buffers()`.
- Section 5: Implemented in `WorkingMemoryConfig`.
- Section 6: Implemented in `to_dict()` and `from_dict()`.
- Section 7: Implemented in `tests/test_agent_working_memory.py`.
- Section 8: Trackers updated.

## Tests
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py -v -x -n 0`: 43 passed
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x -n 0`: 3 passed
- `git diff --check -- src/probos/cognitive/agent_working_memory.py src/probos/config.py tests/test_agent_working_memory.py`: passed; emitted only Git LF/CRLF warning for the test file
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`: stopped after 4 failed, 5916 passed, 327 warnings, 4 errors

## Full-Suite Classification
The full-suite failure matched the user-waived NATS/xdist collision class:

```text
nats.js.errors.BadRequestError: stream name already in use with a different configuration
nats.js.errors.ServerError: error creating store for stream
worker 'gw27' crashed while running tests/test_builder_api.py::TestExecuteBuildEvents::test_emits_build_success
worker 'gw30' crashed while running tests/test_dreaming.py::TestRuntimeDreamingIntegration::test_status_after_dream_includes_report
worker 'gw8' crashed while running tests/test_distribution.py::TestUtilityRuntimeIntegration::test_utility_agents_have_runtime
```

No AD-667 focused tests failed. The failure is treated as waived infrastructure under the 2026-04-27 Captain instruction to ignore the NATS/xdist collision class for the rest of the builds.

## Notes
- `render_context()` was not modified and continues to render legacy ring buffers.
- `from_dict()` restores the stasis marker into the legacy event ring directly so legacy payloads without `named_buffers` keep named buffers empty, as required by the prompt.
- No call sites outside AgentWorkingMemory were changed.
