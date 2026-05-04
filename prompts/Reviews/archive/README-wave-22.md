# Wave 22 Review Sweep

**Date:** 2026-05-04
**Convention:** Single-pass review per Wave 22 dispatch. Tolerance per #15 (relaxed): 1 ⚠️ allowed.

## Prompts Reviewed

| AD | File | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|
| AD-511 v1 | [ad-511-autonomy-boundaries-v1.md](../ad-511-autonomy-boundaries-v1.md) | ✅ Approved | 0 | 4 | 3 |

## Wave Posture

- 1/1 prompts approved.
- 0 Required findings across the wave.
- All 4 safety-critical hard-stops clear (active-blocking, privacy, mutation-API, FP-risk).
- Sibling-pattern conformance to AD-456 / AD-530 verified — module placement, EventType naming, `emit_event` Fail-Fast tier-2 discipline, dataclass frozen invariant.

## Top Themes Across Wave

1. **Pre-deferral honesty held.** AD-511 v1 ships 2 of 5 roadmap capabilities — registry + detector only. Active disengagement (511b), Holodeck training (511c), probing detection (511d), boundary evolution (511e) all properly deferred with explicit "What This Does NOT Change" enumeration. Continues the Wave 19 / Wave 20 deferral discipline.
2. **Privacy invariant pattern reaffirmed.** Same shape as AD-530: emit `(boundary_id, pattern_name, severity, content_length)` — never raw content, never matched substring. The detection-event privacy contract is now the de facto standard for any `<DOMAIN>_DETECTED` event under `security/`.
3. **Wiring-code-as-prose recurring smell.** AD-511 v1 says "mirrors AD-530 pattern" for `_wire_autonomy_boundaries` but AD-530 wires one object while AD-511 wires two (registry + detector + emit_event hookup). Same shorthand was tolerable in AD-530 because it was a one-liner; not so here. **Forcing function for Wave 23+ template:** when wiring count > 1 object OR > 2 attribute assignments, prompts must show concrete wiring code, not "mirrors X pattern."
4. **Constructor-kwarg vs post-construction-assignment divergence.** AD-456 / AD-530 take `emit_event` as a kwarg in `__init__`. AD-511's detector takes only `registry`, then expects post-hoc assignment. Minor but reduces grep-uniformity across `security/`. Recommended for alignment.

## Verify-First Pre-Check Notes

3 documented FPs (`runtime.boundary_registry`, `runtime.boundary_detector`, `SystemConfig.autonomy_boundaries`) all introduced by the prompt. Legitimate per Wave 5 convention #1. No new phantom-API shapes detected.

## Builder Dispatch

Single prompt → single Builder commit. Apply 4 Recommended findings (imports header, concrete wiring code, kwarg alignment, config.py SEARCH/REPLACE) inline before build. Nits are documentation-only — defer to Builder discretion.

## Open Questions for Future Waves

- Should `BoundaryViolationDetector.scan()` accept structured `IntentMessage` payloads (not just raw strings) so it can scan agent-to-agent intents directly? Currently a string-only API. Belongs in AD-511b's consumer-integration scope.
- Should `register_pattern` persist to YAML or stay runtime-only? Currently runtime-only. Persistence path is implied by AD-511e (boundary evolution) but not specified. Track for AD-511e drafting.
- Should `claim_other_callsign` pull crew identities dynamically from AD-398 registry instead of hardcoding seven names? Tracked for AD-511d when probing-pattern detection lands.
