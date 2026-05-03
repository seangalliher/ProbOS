# Wave 15 — AD-685b Method-Call AST Validation

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit.
**Estimated time:** ~1.5 hours total subagent compute.

---

## Wave 15 scope

| AD | Title | Risk |
|---|---|---|
| AD-685b | Phantom-API Pre-Check — Method-Call AST Validation | low (tooling-only) |

Architect's 4th-recurrence forcing function for method-shape phantom pattern (Waves 9B, 10, 12, 14). Extends AD-685 v1 (Wave 11) with method-name validation against resolved class. Conservative heuristic: skip-when-unresolved over false-flag.

**Closes GH issues:** None directly. Tooling hygiene; benefit is reduced future-wave revision cost.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Special attention:

1. **Recursive validity** — AD-685b's own prompt must validate clean against the EXTENDED pre-check (Builder-side acceptance per AD-685 v1 precedent).
2. **Performance estimate** — AD-685 v1's <5s warm baseline. AD-685b adds AST class walking; should stay <10s warm.
3. **Class resolution heuristic conservatism** — skip-when-unresolved is the right posture. Verify the prompt's heuristic list doesn't accidentally flag legitimate dynamic patterns.
4. **No runtime imports** — helper must stay AST-only (no `import probos.X`); preserves sandbox.
5. **Aggressive pre-deferral (convention #14)** — v1 ships method-name check only. Type-shape (AD-685c) and field-name (AD-685d) deferred.

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 15 review pass 1: AD-685b reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended, judgment-call Nits. Append `## Revision (2026-05-03)`. Run pre-check.

Single commit: `Wave 15 revision: apply review findings to AD-685b`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-15-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 15` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 15 specific reminders:

- v1 ships method-name validation ONLY (extends AD-685 v1; do not add type-shape or field-name validation — those are AD-685c/d).
- Recursive-validity gate: after extension lands, AD-685b prompt must produce 0 phantoms via the extended pre-check.
- Calibration sweep on 3 archived post-revision prompts (ad-641c-ward-room-thread-priority.md, ad-500-dutyscheduler-workitem-migration.md, ad-487-self-distillation-v1.md): 0 false positives expected.
- Performance: <10s per prompt warm.
- Helper stays AST-only; no runtime imports from src/probos/.
- Test target: ~10 tests at tests/test_phantom_api_precheck_method_calls.py.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3:** no GH issues to close.

Retrospective: optional. Heuristic — write only if recursive-validity gate exposes a heuristic gap that materially affects prior-wave validation.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-15.md and README-wave-15-pass-2.md
- 1 source commit (AD-685b)
- Full gate green; +10 tests
- 0 hard-stops
- Recursive-validity gate passes (AD-685b prompt: 0 phantoms via extended pre-check)
- Calibration sweep: 0 false positives on 3 archived prompts
- DECISIONS.md entry for AD-685b under Era V
