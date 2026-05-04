# Wave 20 — Combo D (AD-539c + AD-539d gap pipeline extensions)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 combo prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + 2 GH issue closures.
**Estimated time:** ~2 hours total subagent compute.

---

## Wave 20 scope

| Combo | Children | Closes |
|---|---|---|
| Combo D | AD-539c (Automatic Gap Remediation, observational v1) + AD-539d (Fleet-Level Gap Aggregation, local-ship v1) | #106, #107 |

**Throughput target: 2 GH issues closed in single Builder commit.** Both children are observational read-only extensions of shipped AD-539 pipeline. No active remediation, no federation — both deferred to grandchildren (AD-539c-i, AD-539d-i).

**Closes GH issues:** #106 + #107.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Wave 20 specific attention:

1. **Per-child verify-first.** Each mini-section needs grep evidence. Both children consume shipped AD-539 surfaces (gap_predictor.py:186 GapReport).
2. **Observational discipline.** Verify NO active remediation in AD-539c (only RECORDS candidates), NO federation in AD-539d (fleet = local ship only).
3. **AD-685 + AD-685b coverage.** Pre-check now catches kwarg-name + method-name phantoms. Architect-discretion sweep is light — focus on `runtime.ontology` access pattern (AD-539d `_resolve_department` reads ontology) and async/sync semantics.
4. **Section 0 EventTypes** don't collide with events.py post-Wave-19.
5. **Public-attribute discipline.** `runtime.gap_remediation_tracker` + `runtime.gap_aggregator` — NO leading underscore.
6. **Privacy invariant on AD-539d.** Aggregate snapshot payload should NOT include agent_ids — only counts. Test #10 asserts.

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 20 review pass 1: Combo D reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. If any child surfaces a hard-stop, wholesale-defer (AD-575b precedent). Single commit. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-20-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 20` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 20 specific reminders:

- v1 ships 2 children in single commit covering AD-539c + AD-539d.
- Both observational; never auto-act. AD-539c records candidates only; AD-539d aggregates local-ship only.
- Public attributes: `runtime.gap_remediation_tracker` + `runtime.gap_aggregator` (no underscore).
- Section 0: 2 new EventTypes (GAP_REMEDIATION_RECORDED, FLEET_GAP_SNAPSHOT_TAKEN). Verified collision-free.
- Test target: ~21 tests (11 + 10).
- Per-child test files acceptable per Combo A/C precedent.
- Privacy: AD-539d snapshot payload excludes agent_ids; only counts.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

**GATE 3 closes 2 issues:**

```pwsh
gh issue close 106 --comment "AD-539c v1 closed in Combo D Wave 20 (commit XXXXX). Observational GapRemediationTracker shipped: records remediation candidates per gap; never auto-acts. Active remediation deferred to AD-539c-i (forcing function: Captain decides observational → action mode)." --reason completed

gh issue close 107 --comment "AD-539d v1 closed in Combo D Wave 20 (commit XXXXX). Local-ship FleetGapAggregator shipped: aggregates GapReports into FleetGapSnapshot (by gap_type/priority/department/top intents). Cross-ship federation deferred to AD-539d-i (forcing function: AD-479 Federation Hardening ships)." --reason completed
```

Retrospective: optional. Heuristic — write only if combo pattern reveals new failure mode or AD-685b catches a phantom.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-20.md and README-wave-20-pass-2.md
- 1 source commit (Combo D; 2 children)
- Full gate green; +21 tests
- 0 hard-stops at builder time
- GH #106 + #107 BOTH closed
- DECISIONS.md combined entry for Combo D under Era V
- 2 roadmap.md status flags flipped
