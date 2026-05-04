# Wave 16 — AD-525 Creative Expression v1 (Skills Inventory + Records Output)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + GH #100 closure.
**Estimated time:** ~2 hours total subagent compute.

---

## Wave 16 scope

| AD | Title | Risk |
|---|---|---|
| AD-525 | Agent Creative Expression v1 — Skills Inventory + Records Output | medium |

v1 ships 2 of 5 capabilities (CreativeSkillsRegistry + CreativeOutputWriter). Time Allocation (AD-525b), Code-as-Art (AD-525c), Cultural Emergence (AD-525d), Collaboration (AD-525e) all deferred. Read-only consumers of records_store + crew_profile.

**Closes GH issue:** #100.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Wave 16 specific attention:

1. **Pre-deferral honesty.** v1 ships 2 of 5 capabilities. Verify NO time-allocation gating, code-as-creative branching, cultural-emergence detection, or collaboration logic smuggled in.
2. **AD-526 conflict check.** Combo A AD-526c (recreation/metadata.py) and Combo C AD-526d (recreation/preferences.py) exist. AD-525 is creative expression; AD-526 is games/recreation. Verify orthogonal package paths (`src/probos/creative/` vs `src/probos/recreation/`).
3. **AD-685 + AD-685b coverage.** Phantom-API pre-check now catches both kwarg-name AND method-name phantoms. Architect-discretion sweep is lighter; focus on async/sync, return shapes, public-attribute discipline.
4. **Section 0 EventTypes** don't collide with events.py post-Wave-15.
5. **Public-attribute wiring (Wave 5 convention #1).** `runtime.creative_skills_registry` + `runtime.creative_output_writer` — NO leading underscore.
6. **CrewProfile Big Five field verification.** Affinity scoring uses generic `dict[str, float]` interface but real-world callers will pass `CrewProfile.{openness,conscientiousness,extraversion,agreeableness,neuroticism}` floats. Verify field names match.

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 16 review pass 1: AD-525 reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended unless scope creep, judgment-call Nits. Append `## Revision (2026-05-03)`. Run extended pre-check (AD-685 v1 + AD-685b method-call validation).

Single commit: `Wave 16 revision: apply review findings to AD-525`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-16-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 16` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 16 specific reminders:

- v1 ships Skills Inventory + Output Writer ONLY.
- Public attributes `runtime.creative_skills_registry` + `runtime.creative_output_writer` (no underscore).
- Section 0: 2 new EventTypes — verified collision-free.
- 8 default creative skills seeded in DEFAULT_SKILLS tuple.
- Path namespace: `creative/{callsign}/{topic_slug}.md` (mirrors notebook pattern; verify `creative/` not already in use).
- Test count target: ~20 tests.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3 closes GH #100.**

```pwsh
gh issue close 100 --comment "AD-525 v1 closed in Wave 16 — see DECISIONS.md (Skills Inventory + Records Output shipped; Time Allocation/Code-as-Art/Cultural Emergence/Collaboration deferred to AD-525b/c/d/e)" --reason completed
```

Retrospective: optional. Heuristic — write only if AD-685b catches a method-shape phantom (validates Wave 15 tooling) OR if creative-output write path surfaces a new convention.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-16.md and README-wave-16-pass-2.md
- 1 source commit (AD-525)
- Full gate green; +20 tests
- 0 hard-stops
- GH issue #100 closed
- DECISIONS.md entry for AD-525 under Era V
