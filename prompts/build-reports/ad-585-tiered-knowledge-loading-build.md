# Build Report: AD-585 Tiered Knowledge Loading

**Prompt:** prompts/ad-585-tiered-knowledge-loading.md  
**Builder:** 2026-04-27, GitHub Copilot  
**Status:** Blocked

## Files Changed
- src/probos/events.py (+11/-0)
- src/probos/config.py (+27/-1)
- src/probos/cognitive/tiered_knowledge.py (+242/-0)
- src/probos/cognitive/cognitive_agent.py (+36/-0)
- src/probos/startup/finalize.py (+32/-0)
- tests/test_ad585_tiered_knowledge.py (+308/-0)
- tests/test_finalize.py (+55/-0)
- prompts/build-reports/ad-585-tiered-knowledge-loading-build.md (+this report)

## Tests
- Added: 34 tests total: 32 in tests/test_ad585_tiered_knowledge.py, 2 in tests/test_finalize.py
- Suite before: not measurable in this session because the full suite was already red from NATS/xdist infrastructure failures
- Suite after: failed; latest full run reached 7425 passed, 3 skipped, then stopped with 49 failed and 628 warnings
- Focused result: passed
  - `tests/test_events.py -v -x`: 30 passed
  - `tests/test_config.py -v -x`: 3 passed
  - `tests/test_ad585_tiered_knowledge.py -v -x`: 32 passed
  - `tests/test_cognitive_agent.py -v -x -k "decide"`: 2 passed
  - `tests/test_finalize.py -v -x`: 2 passed
  - `tests/test_fallback_learning.py -v -x -k "run_llm_fallback_skips_procedure_memory or full_pipeline_quality_gate_near_miss"`: 2 passed after fix attempt 1
  - Combined focused rerun: 36 passed
- Full-suite result: failed
  - Initial full run: 5930 passed, 3 skipped, 6 failed, 5 errors. Two AD-585 compatibility failures came from legacy CognitiveAgent test construction without `_knowledge_loader`; the rest were NATS/xdist worker crashes and JetStream stream setup errors.
  - Fix attempt 1: changed `_decide_via_llm()` to use `getattr(self, "_knowledge_loader", None)`.
  - Retry full run: AD-585 compatibility failures gone. Remaining failures are outside AD-585 scope: many xdist worker crashes and `tests/test_new_crew_auto_welcome.py::TestAutoWelcome::test_auto_welcome_posts_for_new_crew` failing because the test runtime has `intent_bus=None` while the existing AD-654b finalize path calls `set_record_response()`.

Representative full-suite failure:

```text
FAILED tests/test_new_crew_auto_welcome.py::TestAutoWelcome::test_auto_welcome_posts_for_new_crew
AttributeError: 'NoneType' object has no attribute 'set_record_response'

FAILED tests/test_runtime.py::TestRuntimeSubstrate::test_start_and_stop
worker crashed while running runtime startup tests

nats.js.errors.BadRequestError: code=400 err_code=10058 description='stream name already in use with a different configuration'
nats.js.errors.ServerError: code=500 err_code=10049 description='error creating store for stream'
```

## Trackers Updated
- Not updated because the prompt says tracker updates happen after all tests pass, and the full-suite gate is blocked.
- PROGRESS.md: not marked CLOSED
- DECISIONS.md: no AD-585 entry added
- docs/development/roadmap.md: not updated

## Deviations from Prompt
- Live `ResourcePool.healthy_agents` returns agent IDs, not agent objects. Finalize wiring resolves IDs through `runtime.registry.get()` so AD-585 actually wires real CognitiveAgent instances.
- Live runtime event callbacks expect `(event_type, data)`. `TieredKnowledgeLoader` still uses `KnowledgeTierLoadedEvent`, but emits `wire_event["type"]` and `wire_event["data"]` to match existing callback semantics.
- The prompt named `tests/test_finalize.py`, but that file did not exist. Added focused finalize wiring tests and extracted `_wire_tiered_knowledge_loader()` to keep the gate narrow instead of driving all of `finalize_startup()`.
- Fix attempt 1 added defensive `getattr()` around `_knowledge_loader` for legacy tests that construct CognitiveAgent instances without calling `__init__`.
- `git diff --check` on AD-585 touched files passed with no output.

## Follow-ups
- Stop Condition triggered: the full test suite remains red after the AD-585 in-scope fix; remaining failures are outside this prompt's scope.
- Carry-forward item addressed inline: `src/probos/cognitive/tiered_knowledge.py` contains a TODO for future episode department filtering once episode records persist department metadata.
- Architect/repo follow-up: resolve NATS/xdist stream collisions and the existing AD-654b finalize mock failure in `tests/test_new_crew_auto_welcome.py` before continuing the sweep.
