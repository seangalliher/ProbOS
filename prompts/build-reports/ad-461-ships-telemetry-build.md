# AD-461 Ship's Telemetry Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-461-ships-telemetry.md`

## Summary

Implemented Ship's Telemetry as a centralized operation timing service. The build adds timing buckets, report generation, flush/report emission, configuration, startup/runtime wiring, and `/api/telemetry` access for current reports.

BF-255 quarantines an order-dependent Ward Room DM test that passes in isolation and when paired with AD-461's focused tests. The underlying fixture isolation follow-up is deferred to AD-682.

## Files Changed

- `src/probos/substrate/telemetry.py`
  - Added `TelemetrySample`, `TelemetryBucket`, and `TelemetryService`.
  - Implemented `record()`, async `measure()`, `get_report()`, `flush()`, and `maybe_emit_report()`.
- `src/probos/events.py`
  - Added `EventType.TELEMETRY_REPORT`.
- `src/probos/config.py`
  - Added `TelemetryConfig`.
  - Added `SystemConfig.telemetry`.
- `src/probos/startup/results.py`
  - Added `CognitiveServicesResult.telemetry_service`.
- `src/probos/startup/cognitive_services.py`
  - Initialized `TelemetryService` from `config.telemetry` using the existing `emit_event_fn`.
  - Returned the service through `CognitiveServicesResult`.
- `src/probos/runtime.py`
  - Assigned `cog.telemetry_service` to `runtime._telemetry_service`.
- `src/probos/routers/system.py`
  - Added `GET /api/telemetry`.
- `tests/test_ad461_telemetry.py`
  - Added 12 focused tests for telemetry recording, stats, p95, async measurement, flush, sample eviction, event emission, config defaults, and API behavior.
- `tests/test_ward_room_dms.py`
  - Quarantined BF-255 order-dependent full-gate failure.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-461 and BF-255 tracking.

## Sections Implemented

- `### Section 1: Create TelemetryService`
  - Implemented in `src/probos/substrate/telemetry.py`.
- `### Section 2: Add TELEMETRY_REPORT event type`
  - Implemented in `src/probos/events.py`.
- `### Section 3: Add TelemetryConfig to SystemConfig`
  - Implemented in `src/probos/config.py`.
- `### Section 4: Wire TelemetryService in startup`
  - Implemented via `CognitiveServicesResult.telemetry_service`, `init_cognitive_services()`, and `runtime._telemetry_service`.
- `### Section 5: Add telemetry API endpoint`
  - Implemented in `src/probos/routers/system.py`.
- `## Tests`
  - Implemented focused telemetry tests in `tests/test_ad461_telemetry.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Create TelemetryService` — complete; service, bucket, sample dataclasses, recording, measurement, report, flush, and report emission exist.
- `### Section 2: Add TELEMETRY_REPORT event type` — complete; enum value exists.
- `### Section 3: Add TelemetryConfig to SystemConfig` — complete; config class and `SystemConfig.telemetry` exist.
- `### Section 4: Wire TelemetryService in startup` — complete; service is created in cognitive startup, returned on the result dataclass, and assigned onto runtime.
- `### Section 5: Add telemetry API endpoint` — complete; `/api/telemetry` returns the current telemetry report or disabled status.
- `## Tests` — complete; focused and targeted regression gates passed.
- `## Tracking` — complete; AD-461 and BF-255 tracker entries added.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad461_telemetry.py -v -n 0`
  - Result: 12 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_api_system.py tests/test_config.py -v -n 0`
  - Result: 8 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ward_room_dms.py -v -n 0`
  - Result: 21 passed, 1 skipped after BF-255 quarantine.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad461_telemetry.py tests/test_ward_room_dms.py -v -n 0`
  - Result: 33 passed, 1 skipped after BF-255 quarantine.

## Deviations

- Section 4 wiring spec was revised mid-build (commit 91536be) to use CognitiveServicesResult field instead of direct runtime parameter — matches existing pattern.
- BF-255 quarantine was added per architect disposition because the Ward Room DM test failure is order-dependent pollution and not an AD-461 regression.
