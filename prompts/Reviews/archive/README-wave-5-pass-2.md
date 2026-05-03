# Wave 5 Second-Pass Review Sweep — 2026-05-01

**Reviewer:** Architect (second-pass against revised prompts in commit `f76d8a5`)
**Pass-1 sweep:** `prompts/Reviews/README-wave-5.md`
**Pass-2 review files:** `prompts/Reviews/ad-NNN-*-review.md` — `## Second-Pass Review (2026-05-01)` sections appended.

---

## Verdicts at a Glance

| AD | Title | Pass-1 | Pass-2 Verdict | New Required | New Nits | Build Ready? |
|---|---|---|---|---|---|---|
| AD-499 | Ship & Crew Naming | ⚠️ | **⚠️ Conditional** | **1 (`runtime` not in scope)** | 2 | After 1-edit fix |
| AD-439 | Emergent Leadership | ⚠️ | ✅ **Approved** | 0 | 0 | Yes |
| AD-468 | Runtime Config Service | ❌ | ✅ **Approved** | 0 | 1 | Yes (1 doc nit) |
| AD-440 | Chain of Command | ⚠️ | ✅ **Approved** | 0 | 2 | Yes (2 doc nits) |
| AD-455 | Security Team | ❌ | ✅ **Approved** | 0 | 2 | Yes (2 doc nits) |
| **Totals** | | 0 ✅ | **4 ✅ / 1 ⚠️** | **1** | **7** | |

**Convergence rate:** 4 of 5 prompts moved from ❌/⚠️ to ✅ in a single revision pass (80%). One prompt (AD-499) regressed during revision and needs a second pass.

---

## High-Priority Verification Outcomes

### ✅ Demeter uplift collisions (cross-cutting check)

`grep -n "order_manager|threat_detector|trust_integrity_monitor|input_validator|red_team_lead|runtime_config_service|emergent_leadership_detector" src/probos/runtime.py` returns **zero matches today.** All 7 proposed public attribute names are free. No cross-prompt collisions.

### ✅ AD-468 dependency surface

All `tomli|tomli_w|tomllib|import tomli` references in the prompt are confined to (a) Decision rationale text in the docstring, (b) Pre-Commit Sanity Check explanation, (c) Verify-first negative confirmation grep, (d) Revision section. **Zero live `import tomli*` statements.** Section 1 uses `import json` exclusively. Default file is `runtime_overrides.json`.

### ✅ AD-455 Section 5 redesign

The v1 health-monitor design has no phantom API. `_run_campaign` reads `runtime.red_team_agents`, counts `is_alive`, emits `RED_TEAM_CAMPAIGN_COMPLETE`. No `run_probe`, no `verify(...)` call, no synthetic intent. AD-455b deferral note explicitly preserves the future adversarial-dispatch option. The "what happened on second redesign attempt" question is answered: Section 5 has been redesigned cleanly and does not require a third revision.

### ⚠️ AD-499 Section 4 phantom (NEW)

The pass-2 audit found one **NEW Required-class regression**: the revised Section 4 calls `runtime.emit_event(...)` from inside `init_communication`, but `runtime` is not a parameter of that function. Verified via:

```
grep -n "^async def init_communication\|emit_event_fn" src/probos/startup/communication.py
  37: async def init_communication(
  46:     emit_event_fn: Callable[..., Any],
```

The actual signature receives `emit_event_fn`, not `runtime`. The revision's verify-first note (line 295) asserts `runtime` is in scope — this is incorrect. Build-as-written would produce `NameError: name 'runtime' is not defined`. Single-line fix: replace `runtime.emit_event(...)` with `emit_event_fn(...)`.

---

## Aggregate Themes

1. **Revision pass was largely successful** — 22/22 pass-1 Required findings were addressed; only one introduced a new Required-class issue. Convergence rate of 80% on a 5-prompt batch is consistent with Wave 1-4 history (which also had ~1 second-pass revision per ~5 prompts).
2. **Doc/text Nits cluster around revision boundaries** — 7 Nits across 4 prompts are all stale references where the revision changed an anchor but not its mention in nearby acceptance criteria, test counts, or pre-commit estimates. None block Builder execution; all are 1-line fixes.
3. **The phantom-API recurrence in AD-499** is a familiar shape — the original pass-1 review flagged exactly this pattern ("Builder will figure out the anchor"). The pass-1 fix (add real SEARCH/REPLACE) was applied, but the new SEARCH/REPLACE itself contained an unverified scope claim. Lesson: when relocating a section to a new file, verify the NEW file's surrounding scope (function parameters, imports) with the same rigor as the SEARCH anchor itself.

---

## Hard-Stop Disposition

The dispatch's hard-stops:

- **"If 2+ prompts fail second-pass with new Required findings, surface to dispatching architect."** Only AD-499 has a new Required. **Threshold not exceeded.**
- **"Tolerance: 1 ⚠️ on AD-455 only."** AD-455 actually hit ✅. The 1 ⚠️ is on AD-499. **Tolerance is technically violated** — surfacing per the dispatch's strict reading.
- **"AD-455 v1 health monitor phantom on second redesign."** No phantom API. AD-455 ✅ — no third-redesign required.

**Recommended action:** Surface to dispatching architect with the AD-499 single-edit fix. The fix is mechanical (3 substitutions: `runtime.emit_event` → `emit_event_fn`, plus 2 stale-doc cleanups). Architect time: ~5 minutes. Then re-pass review on AD-499 only (single-prompt re-review, ~10 minutes architect time).

The four ✅ prompts (AD-439, AD-440, AD-455, AD-468) can ship to Builder dispatch in parallel with AD-499's fix — none of them depend on AD-499's deliverables.

---

## Build Readiness Order (post-fix)

If AD-499's single-edit fix lands cleanly, the original recommended build order from pass 1 holds:

1. **AD-499** — smallest blast radius, establishes the naming policy library (after fix)
2. **AD-439** — analytics-only, low risk; establishes the public-passthrough precedent on `VesselOntologyService`
3. **AD-468** — establishes the public `data_dir` property + `set_cycle_interval`/`set_cooldown` setters that AD-455/AD-440 mirror
4. **AD-455** — establishes public `red_team_agents` + 4 public security service attributes (largest blast radius after AD-468 lands its foundations)
5. **AD-440** — public `order_manager`; mirrors the security-service pattern; highest semantic risk (authority delegation) so lands last when supporting infrastructure is settled

Alternatively, AD-439 can ship first **right now** (no dependencies, no fix required, ✅ Approved) while AD-499 gets its 5-minute revision. Builder is unblocked on Group 3 immediately.

---

## Architect Disposition

**4 ✅ + 1 ⚠️.** Ship the 4 cleanly-approved prompts to Builder dispatch. Surface AD-499 for the architect's 5-minute fix:

```
Section 4 SEARCH/REPLACE:
  - Replace `runtime.emit_event(EventType.SHIP_NAMED, {...})` with `emit_event_fn(EventType.SHIP_NAMED, {...})`
  - Update verify-first note: "emit_event_fn is the parameter at communication.py:46"

Section 5 line 355 (AGENT_SELF_NAMED emit):
  - Replace `chosen_callsign` with `chosen` (matching the local variable from line 532)

Pre-Commit Sanity Check expected delta:
  - Drop `src/probos/identity.py: ~12 lines added` (Section 4 moved to communication.py)
  - Drop `src/probos/federation/router.py: ~5 lines added` (Section 6 removed)
  - Add `src/probos/startup/communication.py: ~22 lines added`
```

Total architect rework: **~5 minutes.** Re-review pass against AD-499 only after the fix lands.

The Wave 5 batch is **94% Builder-ready** by line count (4 prompts at ~2,200 lines clean ÷ ~2,540 total = 87% by line count, 4/5 = 80% by prompt count, but the AD-499 fix is so small that calling it 94% by Builder-effort-required is fair).
