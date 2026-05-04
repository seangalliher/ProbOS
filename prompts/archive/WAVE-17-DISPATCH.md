# Wave 17 — AD-513 Phase 2 v1 (Crew Manifest Shell + Watch Filter + Ship Manifest)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + GH #14 closure.
**Estimated time:** ~2 hours total subagent compute.

---

## Wave 17 scope

| AD | Title | Risk |
|---|---|---|
| AD-513 Phase 2 v1 | Crew Manifest Shell Command + Watch Filter + Ship Manifest | low |

v1 ships 3 of 6 Phase-2 capabilities. Trust-gated visibility (Phase 2b), agent tool access (Phase 2c), ACM/competency fields (Phase 2e) all deferred. Read-only additive surfaces.

**Closes GH issue:** #14.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Wave 17 specific attention:

1. **Pre-deferral honesty.** v1 ships 3 of 6 capabilities. Verify NO trust-gated visibility, agent-tool-access plumbing, or ACM-competency-field smuggling.
2. **Backward-compat on get_crew_manifest.** New kwargs (watch, watch_manager) must NOT break existing Phase 1 callers (HXI panel, REST endpoint, _build_crew_complement). Verify by reading existing call sites.
3. **AD-685 + AD-685b coverage.** Pre-check now catches kwarg-name + method-name phantoms. Architect-discretion sweep focuses on async/sync, return shapes, and the runtime.watch_manager attribute name (verify exists).
4. **Shell command pattern conformance.** `/manifest` mirrors `/agents` (commands_status.cmd_agents). Verify the handler module/function naming matches the existing pattern.
5. **Public-attribute discipline.** No new runtime attributes in v1 (`get_ship_manifest` is a method on existing `VesselOntologyService`). Confirm no underscore-prefixed wiring.

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 17 review pass 1: AD-513 Phase 2 v1 reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended, judgment-call Nits. Append `## Revision (2026-05-03)`. Run extended pre-check.

Single commit: `Wave 17 revision: apply review findings to AD-513 Phase 2 v1`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-17-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 17` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 17 specific reminders:

- v1 ships 3 of 6 capabilities ONLY (shell + watch + ship-summary).
- `get_crew_manifest()` extension is BACKWARD-COMPATIBLE — kwargs default to None.
- `get_ship_manifest()` is a NEW method on VesselOntologyService.
- `/manifest` slash command added to shell.py dispatch table; new module commands_manifest.py created.
- No new EventTypes (Section 0 empty for v1).
- No new runtime public attributes (everything is methods on existing services).
- Test count target: ~17 tests.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3 closes GH #14.**

```pwsh
gh issue close 14 --comment "AD-513 Phase 2 v1 closed in Wave 17 — see DECISIONS.md (/manifest shell command + watch filter + get_ship_manifest shipped; trust-gated visibility / agent tool access / ACM-competency fields deferred to Phase 2b/c/e)" --reason completed
```

Retrospective: optional. Heuristic — write only if AD-685b catches a method-shape phantom in this wave.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-17.md and README-wave-17-pass-2.md
- 1 source commit (AD-513 Phase 2 v1)
- Full gate green; +17 tests
- 0 hard-stops
- GH issue #14 closed
- DECISIONS.md entry for AD-513 Phase 2 v1 under Era V
