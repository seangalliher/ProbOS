# Review: AD-461 — Ship's Telemetry

**Verdict:** ✅ Approved
**Re-review (2026-04-29 second pass): ✅ Approved.** Revisions clean.

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

---

## Second-Pass Re-review (2026-04-29)

**Verdict:** ✅ Approved.

Revisions did not introduce new issues. `BEHAVIORAL_METRICS_UPDATED` still at [events.py:134](src/probos/events.py#L134); `runtime.emit_event` at [runtime.py:771](src/probos/runtime.py#L771); pattern intact.

Minor: the `hasattr(runtime, 'emit_event')` guard in Section 4 is dead code now that AD-680 has landed (commit `73945d0`). Trim during build or accept as harmless. Not a blocker.

---

## Third-Pass Re-review (2026-04-29)

**Verdict:** ✅ Approved.

Revised prompt drops the `hasattr` guard — Section 4 now wires `emit_fn=runtime.emit_event` directly. No regressions introduced. `EventType.TELEMETRY_REPORT` insertion at [events.py:134](src/probos/events.py#L134) (after `BEHAVIORAL_METRICS_UPDATED`) remains correct.

Note: pre-existing `hasattr(runtime, 'emit_event')` patterns in 13 sites (`cognitive_agent.py`, `proactive.py`, `dreaming.py`) are dead code post-AD-680. Out of scope for AD-461; file a follow-up cleanup AD if desired.

Ready for builder.
