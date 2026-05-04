# Wave 17 — Review Pass 2 Sweep Summary

**Date:** 2026-05-03
**Stage:** 3 (Architect Review Pass 2 — post-revision)
**Scope:** 1 prompt (AD-513 Phase 2 v1 — Crew Manifest Shell + Watch Filter + Ship Manifest)

---

## Sweep Verdicts

| AD | Pass-1 | Pass-2 | Required-still-open | New findings |
|---|---|---|---|---|
| AD-513 Phase 2 v1 | ⚠️ Conditional | ✅ Approved | 0 | 0 |

**Total Required-still-open:** 0 (target: 0). **New findings:** 0 (target: 0).

Convention #15 tolerance restored (was breached at pass-1 with 2 Required). Single revision pass converged, matching pass-1 disposition forecast.

---

## Resolution Summary

| Pass-1 Finding | Tier | Resolved? | Notes |
|---|---|---|---|
| R1 — phantom `alert_manager` parameter | Required | ✅ | Section 2 signature, body, cmd_manifest call site, test #9 all clean. Alert sourced from `self.get_alert_condition()` (verified service.py:99-100). |
| R2 — `vessel_class` undefined on VesselIdentity | Required | ✅ | Field dropped from return shape; VesselIdentity actual fields documented in footer (verified models.py:56-61). |
| R3 — pin sources for return-shape keys | Recommended | ✅ | All five keys mapped to verified sources. |
| R4 — `watches` shape decision | Recommended | ✅ | Chose populated-watches (option b) for federation gossip use case. |
| R5 — lowercase `watch:` arg | Recommended | ✅ | `.lower()` applied at token parse. |
| N6 — empty Section 5 | Nit | ✅ | Deleted. |
| N7 — `runtime.callsign_registry` verified | Nit | ✅ | Promoted in footer. |
| N8 — `/manifest` collision check | Nit | ✅ | Moved to verified; hard-stop removed. |

Plus the Section 1 watch-filter spec gap (under Required #2): rewritten with explicit pseudo-code, `agent_id` match key, empty-string skip, lowercase normalization, and `watch_manager=None` empty-list semantics.

---

## Phantom-API Pre-Check

```
./scripts/phantom-api-precheck.ps1 prompts/ad-513-phase2-manifest-v1.md
=== prompts/ad-513-phase2-manifest-v1.md ===
  Clean — no phantom symbols detected.
=== Summary ===
Prompts scanned: 1
Total phantom candidates: 0
```

---

## AD-685b Validation Note (2 Consecutive Waves)

Wave 16 = 1 real catch (`runtime.<missing-helper>`).
Wave 17 = 1 real catch (`runtime.vessel_ontology → runtime.ontology` at dispatch, commit `e4363e2`).

**Two consecutive non-trivial catches.** The scripted `runtime.X` shape pre-check is now compounding into the workflow rather than re-emerging in review. Tooling investment paying back. Architect-discretion review weight on `runtime.X.Y` shapes can stand down further (was already trimmed after Wave 16).

**Tooling extension candidate.** Pass-1 Required #1 (phantom `alert_manager` *parameter*, not `runtime.alert_manager` *attribute*) was caught by review — pre-check did not see it because the shape is "method parameter named after a non-existent collaborator", not `runtime.X`. Recommend extending the script to flag method parameters matching `<noun>_manager` / `<noun>_registry` / `<noun>_service` against runtime attribute existence. Hold pending 2nd recurrence per convention #14 forcing-function discipline.

---

## Recommended Builder Dispatch

**Single commit.** Prompt is ✅ Approved with 0 Required and 0 new findings. No hard-stops. Builder may proceed against the revised prompt at HEAD (commit `9acf78c` + this pass-2 commit).

Dispatch shape:
- Target: `prompts/ad-513-phase2-manifest-v1.md`
- Test target: `tests/test_ad513_phase2_manifest.py` (~17 tests)
- Surfaces: `src/probos/ontology/service.py` (modify get_crew_manifest, add get_ship_manifest), `src/probos/experience/commands/commands_manifest.py` (new), `src/probos/experience/shell.py` (dispatch + COMMANDS).
- Tracking: PROGRESS.md, DECISIONS.md (Era V), roadmap.md flip-to-partial.

---

## Stage Disposition

| Stage | Status |
|---|---|
| Stage 1 (pass-1 review) | ✅ ⚠️ Conditional — 2 Required, 3 Recommended, 3 Nits |
| Stage 2 (revision) | ✅ committed at `9acf78c` |
| Stage 3 (pass-2 review, this sweep) | ✅ Approved |
| Stage 4 (GATE 1 — Builder dispatch) | ready |

Convergence target met: 1 ✅.
