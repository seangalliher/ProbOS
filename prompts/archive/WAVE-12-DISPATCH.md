# Wave 12 — AD-477 Naval Organization (Captain's Log + Plan of the Day)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + GH #71 closure.
**Estimated time:** ~2 hours total subagent compute.

---

## Wave 12 scope

| AD | Title | Risk |
|---|---|---|
| AD-477 | Naval Organization Protocols (v1: Captain's Log + Plan of the Day) | medium |

v1 ships 2 of 6 capabilities (Captain's Log + Plan of the Day) — the truly NEW generative surfaces with no overlap with existing AD-566 (qualification battery), AD-539 (gap pipeline), AD-595e (qualification gates), or Standing Orders. Aggressive pre-deferral applied: Qualification Programs → AD-477b, 3M System → AD-477c, Damage Control → AD-477d, SORM → AD-477e.

**Closes GH issue:** #71.

---

## Stage 1 — Architect: Review Pass 1

Dispatch to Architect subagent. Standard review pattern. Special attention:

1. **Pre-deferral honesty.** v1 ships 2 of 6 capabilities; verify no Qualification Programs / 3M / Damage Control / SORM functionality smuggled into v1. If yes, scope creep — Required.
2. **AD-566 conflict avoidance.** AD-477's deferred AD-477b extends AD-566. v1 must NOT modify AD-566 or its sub-ADs (539, 595e). Read-only consumers only.
3. **Wave 9 retrospective conventions** — especially #21 structural-defect sweep on `list_work_items`, episodic memory, dreaming engine consumer paths. The new AD-685 kwarg pre-check (Wave 11) will catch most of these mechanically.
4. **Section 0 EventTypes** don't collide with events.py.
5. **Public-attribute wiring** (Wave 5 convention #1) — `runtime.captains_log_service`, `runtime.plan_of_day_service`, NO leading underscore.

Hard-stops per dispatch.

After review + sweep summary written:
- Single commit: `Wave 12 review pass 1: AD-477 reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended unless scope creep, judgment-call Nits. Append `## Revision (2026-05-03)`. Run pre-check (now extended with kwarg validation per AD-685).

Single commit: `Wave 12 revision: apply review findings to AD-477`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-12-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

Inspect sweep summary. Approve via convention #15 verdict criteria.

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 12` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch with Wave 12 specific reminders:

- v1 ships 2 capabilities (CaptainsLogService + PlanOfDayService) ONLY.
- Read-only consumers; no writes to episodic_memory / dreaming_engine / work_item_store / ward_room.
- Public attributes `runtime.captains_log_service`, `runtime.plan_of_day_service` (no underscore).
- Section 0: `CAPTAINS_LOG_GENERATED`, `PLAN_OF_DAY_GENERATED` (verify no collision).
- Test count target: ~14 tests.
- Background tasks must catch `CancelledError` + cleanup + re-raise (async discipline standing rule).

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3 closes GH #71.**

```pwsh
gh issue close 71 --comment "AD-477 v1 closed in Wave 12 — see DECISIONS.md (Captain's Log + Plan of the Day shipped; Qualification Programs/3M/Damage Control/SORM deferred to AD-477b/c/d/e)" --reason completed
```

Retrospective: optional. Heuristic — write only if AD-685 kwarg pre-check catches a phantom in pass-1 review (validates the tooling investment), or if a new convention emerges.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-12.md and README-wave-12-pass-2.md
- 1 source commit (AD-477)
- Full gate green; +14 tests
- 0 hard-stops
- GH issue #71 closed
- DECISIONS.md entry for AD-477 under Era V
- Optional: Wave 12 retrospective if AD-685 pre-check catches a phantom (would validate tooling)
