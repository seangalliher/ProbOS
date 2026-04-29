# Review: AD-461 — Ship's Telemetry

**Verdict:** ✅ Approved
**Headline:** Clean new service addition with proper config integration.

## Required

None.

## Recommended

1. When AD-465 (Containerized Deployment) lands, ensure config validators stay consistent — `config.py` uses `@field_validator` throughout (e.g., NatsConfig at line 1418). The AD-461 prompt sketches a `@model_validator(mode="after")`; align with `field_validator` for consistency.

## Nits

- `telemetry.maybe_emit_report()` is invoked periodically — recommend a docstring example showing the calling pattern (heartbeat or periodic task).
- `TelemetryBucket.to_dict()` rounds floats — confirm precision loss is acceptable for downstream consumers.

## Verified

- `BEHAVIORAL_METRICS_UPDATED` exists at [events.py:134](src/probos/events.py#L134) — insertion point for `TELEMETRY_REPORT` confirmed.
- `CognitiveConfig` exists at [config.py:149](src/probos/config.py#L149); nested-config pattern verified.
- `runtime.emit_event` is a public method at [runtime.py:771](src/probos/runtime.py#L771).
- `Depends(get_runtime)` pattern at [routers/system.py:20](src/probos/routers/system.py#L20) matches.
- `startup/cognitive_services.py:452` exists; oracle-service insertion section identified.
