# AD-672 Agent Concurrency Management Build Report

**Date:** 2026-04-27
**Status:** Complete
**Prompt:** `prompts/ad-672-agent-concurrency-management.md`

## Summary

Implemented per-agent concurrency management for cognitive lifecycles. `ConcurrencyManager` now enforces a role-tuned ceiling, queues excess intents by priority, emits capacity-approaching events, supports same-resource priority arbitration, and exposes a diagnostic snapshot. `CognitiveAgent.handle_intent()` uses the manager when wired and degrades queue-full cases to `[NO_RESPONSE]`.

No AttentionManager, LLM semaphore, SubTaskChain concurrency, APIs, HXI, or work-stealing behavior was changed.

## Files Changed

- `src/probos/events.py`
  - Added `EventType.AGENT_CAPACITY_APPROACHING`.
  - Added `AgentCapacityApproachingEvent`.
- `src/probos/config.py`
  - Added `ConcurrencyConfig` with defaults and role overrides.
  - Added `SystemConfig.concurrency`.
- `src/probos/cognitive/concurrency_manager.py`
  - Added `ThreadEntry`, `QueuedIntent`, and `ConcurrencyManager`.
  - Implemented acquire/release, priority queue promotion, capacity warning emission, resource arbitration, slot context manager, and snapshot diagnostics.
- `src/probos/cognitive/cognitive_agent.py`
  - Added `_classify_concurrency_priority()`.
  - Added optional `set_concurrency_manager()` wiring.
  - Wrapped cognitive lifecycle execution in a concurrency slot when available.
  - Preserved BF-239 thread-engagement cleanup on both managed and unmanaged paths.
- `src/probos/startup/finalize.py`
  - Wired one `ConcurrencyManager` per crew agent during finalization when `config.concurrency.enabled` is true.
- `tests/test_ad672_concurrency_manager.py`
  - Added 18 focused tests for manager behavior, events, arbitration, context manager cleanup, priority classification, and config defaults.
- `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`
  - Updated AD-672 tracking.

## Section Audit

- `### Section 1: EventType Addition` — implemented in `src/probos/events.py`.
- `### Section 2: ConcurrencyConfig` — implemented in `src/probos/config.py`.
- `### Section 3: ConcurrencyManager` — implemented in `src/probos/cognitive/concurrency_manager.py`.
- `### Section 4: CognitiveAgent Integration` — implemented import, manager slot, setter, lifecycle wrapping, and priority classifier.
- `### Section 5: Startup Wiring` — implemented in `src/probos/startup/finalize.py` adjacent to existing crew-agent service wiring.
- `## Tests` — implemented all 18 requested tests.
- `## Targeted Test Commands` — focused tests and CognitiveAgent regression passed.
- `## Tracking` — updated trackers and this build report.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad672_concurrency_manager.py -v -x -n 0`
  - Result: 18 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x -n 0`
  - Result: 56 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py tests/test_ad672_concurrency_manager.py tests/test_cognitive_agent.py -v -x -n 0`
  - Result: 77 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
  - Result: stopped on known NATS/JetStream collision plus xdist worker crash storm after 6512 passed and 14 skipped.
  - Classification: waived by Captain instruction for the rest of builds.

## Notes

- The manager uses `asyncio.get_running_loop()` for queued futures.
- Queue-full acquisition raises `ValueError`; `CognitiveAgent.handle_intent()` catches it and returns `[NO_RESPONSE]` with current confidence.
- Capacity warnings are debounced per manager instance.
- `meta.inf` remains untracked and was not part of this build.
