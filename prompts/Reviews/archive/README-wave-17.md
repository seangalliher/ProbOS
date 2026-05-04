# Wave 17 — Review Pass 1 Sweep Summary

**Date:** 2026-05-03
**Stage:** 1 (Architect Review Pass 1)
**Scope:** 1 prompt (AD-513 Phase 2 v1 — Crew Manifest Shell + Watch Filter + Ship Manifest)

---

## Sweep Verdicts

| AD | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|
| AD-513 Phase 2 v1 | ⚠️ Conditional | 2 | 3 | 3 |

**Total:** 2 Required, 3 Recommended, 3 Nits across 1 prompt. Convention #15 (relaxed tolerance, 1 ⚠️ allowed) breached — revision pass required.

---

## Required Findings (digest)

1. **Phantom `alert_manager` parameter on `get_ship_manifest()`** (Section 2 + Section 3). No `AlertManager` / `runtime.alert_manager` exists; alert state actually lives at `self._loader.alert_condition` (already exposed via `get_alert_condition()`). Drop the parameter; source from `self.get_alert_condition()` directly. Update test #9 accordingly.
2. **WatchManager API spec gap** (Section 1). `WatchManager` has no per-agent watch query — only `get_roster() → dict[str, list[str]]`. Spec must include the reverse-lookup pattern, the `agent_id` (not `agent_type`) match key, and the lowercase case-normalization rule for the `watch:` arg.

## Recommended (digest)

3. Pin sources for `get_ship_manifest()` `ship_name` / `vessel_class` (`get_vessel_identity()`; `vessel_class` has no clean source — drop or remap).
4. Choose semantics for the `watches` field: current-watch only vs all populated watches.
5. Lowercase the `watch:` arg in Section 3 token parser before compare.

## Nits (digest)

6. Delete empty Section 5.
7. Promote `runtime.callsign_registry` to "verified" in footer (already verified at 2 sites).
8. Move "/manifest collision" hard-stop to "Verified" (0 matches grepped).

---

## Backward-Compat Assessment

✅ **Clean.** `get_crew_manifest()` has 2 existing callers; both pass kwargs only:
- `src/probos/cognitive/cognitive_agent.py:4126` (`_build_crew_complement`) — passes `callsign_registry=` only.
- `src/probos/routers/ontology.py:64` (REST endpoint) — passes `department=`, `trust_network=`, `callsign_registry=`.

New kwargs `watch: str | None = None` and `watch_manager: Any | None = None` default to None, preserving behavior on all existing call sites.

REST endpoint stays unchanged in v1 (per "What This Does NOT Change" — watch filter could be added later).

## WatchManager Attribute Verification

✅ `runtime.watch_manager` exists. Verified at:
- `src/probos/runtime.py:238` (type annotation)
- `src/probos/runtime.py:580` (init `self.watch_manager: WatchManager | None = None`)
- `src/probos/runtime.py:1659` (warm-boot restore from finalizer)

Real consumers already pattern-match this attribute (`runtime.py:829, 842`). The `getattr(runtime, "watch_manager", None)` defensive read in Section 3 is valid and consistent.

## Shell Command Pattern Conformance

✅ Pattern matches.

| Aspect | `/agents` (existing) | `/manifest` (proposed) | Match? |
|---|---|---|---|
| Handler signature | `async def cmd_agents(runtime, console, args)` (commands_status.py:30) | `async def cmd_manifest(runtime, console, arg)` | ✅ identical shape |
| Module name | `commands_status.py` | `commands_manifest.py` | ✅ consistent prefix convention |
| Dispatch lambda | `lambda: commands_status.cmd_agents(rt, con, arg)` | `lambda: commands_manifest.cmd_manifest(rt, con, arg)` | ✅ identical idiom |
| `self.COMMANDS` entry | `"/agents": "List all agents..."` | proposed: `"/manifest": "..."` | ✅ same dict shape |

`commands_manifest.py` as a fresh module is structurally consistent with `commands_status.py`, `commands_alert.py`, `commands_clearance.py`, `commands_skill.py` etc. (all single-cmd or cmd-cluster modules).

## AD-685b Validation Note

This is the **2nd consecutive wave with a real catch by AD-685b's kwarg-shape pre-check**.

Wave 16: `runtime.<missing-helper>` (caught at dispatch).
Wave 17: `runtime.vessel_ontology → runtime.ontology` (caught at dispatch, commit `e4363e2`).

Recurrence-class phantoms (Wave 9 retrospective convention #20-adjacent on `runtime.X.Y` shapes) are now compounding into the scripted check rather than re-emerging in review. Architect-discretion sweep weight reduces accordingly.

**Limit observed.** Pre-check caught `runtime.vessel_ontology` because it is `runtime.X` shape. It did **not** catch the `alert_manager` Required #1 finding because that defect is a *method parameter named after a non-existent collaborator*, not a `runtime.X` access. Recommend extending pre-check to flag method parameters whose name is `<noun>_manager` / `<noun>_registry` / `<noun>_service` against runtime attribute lookup. File as Wave 17 retrospective candidate (don't draft as a new AD until 2nd recurrence per convention #14 forcing-function discipline).

## Top Failure Modes If Shipped As-Is

1. `get_ship_manifest()` ships with permanently-`"GREEN"` `alert_state`; federation gossip consumers get wrong data. Tests pass (the test asserts the broken behavior!).
2. Builder invents a per-agent watch lookup; likely matches `agent_type` instead of `agent_id`, or skips empty-agent_id rows. Edge cases silently fail.
3. `vessel_class` becomes a hardcoded empty string or guessed config field. Federation routing breaks.

All catchable in one revision pass per the disposition.

---

## Stage Disposition

| Stage | Status |
|---|---|
| Stage 1 (this pass) | ⚠️ Conditional — 2 Required, revision required |
| Stage 2 (revision) | pending — apply 2 Required + fold 3 Recommended + judgment on 3 Nits |
| Stage 3 (pass-2 review) | pending |
| Stage 4 (GATE 1) | pending |

Convergence target after revision: 1 ✅.

## Cross-links

- Reviews: `prompts/Reviews/ad-513-phase2-manifest-v1-review.md`
- Prompt: `prompts/ad-513-phase2-manifest-v1.md`
- Wave dispatch: `prompts/WAVE-17-DISPATCH.md`
- Pre-check: `scripts/phantom-api-precheck.ps1` (AD-685 + AD-685b)
- Standing conventions: `DECISIONS.md` (Wave 5 / 5-7 / 8 / 9 retrospective entries; 23 total)
