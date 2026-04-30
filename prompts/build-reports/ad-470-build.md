# AD-470 IntentBus Enhancements Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-470-intentbus-enhancements.md`

## Summary

Implemented IntentBus metrics tracking and subscriber introspection. Broadcast and directed-send paths now record counts and elapsed durations, duration samples are capped per intent type, and the system API exposes metrics plus subscriber maps.

IntentBus broadcast/send behavior, JetStream integration, deduplication, `IntentMessage`, and `IntentResult` were not changed.

## Files Changed

- `src/probos/mesh/intent.py`
  - Added `IntentMetrics`.
  - Wired broadcast/send metrics.
  - Added `get_subscriber_map()` and `get_metrics()`.
- `src/probos/routers/system.py`
  - Added intent metrics endpoint.
- `tests/test_ad470_intent_bus_enhancements.py`
  - Added 13 focused tests for metrics, subscriber maps, bus integration, send/broadcast recording, and endpoint behavior.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-470 tracking.

## Sections Implemented

- `### Section 1: Add IntentMetrics tracker`
  - Implemented in `src/probos/mesh/intent.py`, including `defaultdict` import and capped duration samples.
- `### Section 2: Wire metrics into IntentBus`
  - Implemented in `IntentBus.__init__()`, `broadcast()`, and `send()`.
- `### Section 3: Add subscriber introspection`
  - Implemented as `get_subscriber_map()` and `get_metrics()`.
- `### Section 4: Add metrics API endpoint`
  - Implemented in `src/probos/routers/system.py`.
- `## Tests`
  - Implemented in `tests/test_ad470_intent_bus_enhancements.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Add IntentMetrics tracker` — complete; broadcast/send counts, per-type counts, result totals, duration samples, sample cap, and summaries exist.
- `### Section 2: Wire metrics into IntentBus` — complete; broadcast and send paths record elapsed durations in `finally` or before return.
- `### Section 3: Add subscriber introspection` — complete; subscriber maps include indexed and fallback subscribers, and metrics summary is exposed.
- `### Section 4: Add metrics API endpoint` — complete; endpoint uses the public `runtime.intent_bus` attribute.
- `## Tests` — complete; 13 focused tests added.
- `## Tracking` — complete; tracker and build report updates added.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad470_intent_bus_enhancements.py -v -n 0`
  - Result: 13 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad470_intent_bus_enhancements.py tests/test_intent.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_api_system.py -v -n 0`
  - Result: 91 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10185 passed, 18 skipped.

## Deviations

- The endpoint decorator uses `/intent-metrics` because `system.py` already has `router = APIRouter(prefix="/api", ...)`; the public endpoint is `/api/intent-metrics`.
- The API endpoint uses public `runtime.intent_bus` rather than `_intent_bus`, matching the live runtime attribute verified in the prompt review.
- Added 3 tests beyond the prompt's 10 to cover directed send metrics and endpoint enabled/disabled behavior.
