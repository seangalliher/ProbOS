# AD-459 Build Report

**Date:** 2026-05-01
**Builder:** Wave 6 continuous-build (final prompt)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+5: EventTypes | `src/probos/events.py` | ✅ Added 2 (`SERVICE_TIER_DEGRADED`, `SERVICE_TIER_RESTORED`) |
| Section 1: Package init | `src/probos/degradation/__init__.py` (new) | ✅ Owns directory creation |
| Section 2: ServiceTierRegistry | `src/probos/degradation/registry.py` (new) | ✅ 11 verified-against-runtime seed names |
| Section 3: SheddingPolicy | `src/probos/degradation/policy.py` (new) | ✅ |
| Section 4: DegradationManager | `src/probos/degradation/manager.py` (new) | ✅ Read-only v1 coordinator |
| Section 6: DegradationConfig | `src/probos/config.py` | ✅ No-fields placeholder; AD-459b adds operator tuning |
| Section 7: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ Always-wired (no `enabled` flag); `runtime.degradation_manager` (public) |
| Tests | `tests/test_ad459_saucer_separation.py` (new) | ✅ 13/13 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4152` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad459_saucer_separation.py -v -n 0` → **13/13 passed in 0.27s**
- Full parallel gate: **10,392 passed (+13 vs AD-457 baseline 10,379), 14 skipped**

## Notes / Decisions

- Owns directory creation: `src/probos/degradation/__init__.py` mirrors AD-455 `security/` and AD-676 `governance/` precedents.
- v1 is read-only coordinator (no subsystem mutation). Active shedding hooks deferred to AD-459b.
- All 11 seed names verified against live runtime.py / finalize.py during draft and re-confirmed during build.
- HIGH/CRITICAL share v1 shed mask; AD-459b will differentiate via active-shedding hooks (cancel tasks, pause queues).
- Always-wired contract: no `enabled` flag, manager always created, default state NORMAL.
- `bridge_alerts.AlertSeverity` is unchanged — orthogonal incident-severity surface.

## Pre-Commit Sanity Check

10 files changed, ~390 insertions, 4 deletions. Max per-file deletion: 1 line. Well under 200-line threshold.
