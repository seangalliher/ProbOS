# Wave 14 — AD-487 Self-Distillation v1 (Map Step)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + GH #79 closure.
**Estimated time:** ~2 hours total subagent compute.

---

## Wave 14 scope

| AD | Title | Risk |
|---|---|---|
| AD-487 | Self-Distillation v1 — Personal Ontology Map Step | medium |

v1 ships 1 of 4 capabilities (Map step only). Collapse (AD-487b), Reduce (AD-487c), Daydream (AD-487d), DID portability (AD-487e) all deferred. AD-486 onboarding Phase 3 integration explicitly NOT required — v1 is standalone callable.

**Closes GH issue:** #79.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch with Wave 14 specific attention:

1. **Pre-deferral honesty.** v1 ships 1 of 4 capabilities. Verify NO Collapse/Reduce/Daydream/DID-portability functionality smuggled into v1. If yes, scope creep — Required.

2. **LLMClient.chat signature verification.** Prompt assumes a `chat()` method. AD-685 kwarg pre-check should catch shape mismatches; review confirms semantic alignment.

3. **Rate-limit infrastructure conflict check.** AD-636 (LLM Priority Scheduling) and AD-637f (Priority Model) exist. AD-487's per-(agent,domain,24h) rate limit is independent (about probe frequency, not scheduling priority). Confirm by grep — they're orthogonal but architect should explicitly check.

4. **SQLite schema isolation.** New `agent_probes` table; no conflict with existing tables expected. Grep src/ for `agent_probes` to confirm absent.

5. **Public-attribute wiring (Wave 5 convention #1).** `runtime.personal_ontology_prober` — NO leading underscore.

6. **Wave 9-13 retrospective conventions.** Apply architect-discretion sweep on:
   - LLMClient.chat async/sync (probably async)
   - ProbeResult dataclass field shape
   - SQLite cursor patterns (async per protocol)

Tolerance per convention #15 (relaxed): 1 ⚠️ allowed.

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 14 review pass 1: AD-487 reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended unless scope creep, judgment-call Nits. Append `## Revision (2026-05-03)`. Run pre-check.

Single commit: `Wave 14 revision: apply review findings to AD-487`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-14-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 14` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 14 specific reminders:

- v1 ships Map step ONLY (`probe_domain` + `get_recent_probes`).
- Public attribute `runtime.personal_ontology_prober` (no underscore).
- Section 0: 2 new EventTypes — verified collision-free.
- New SQLite table `agent_probes` via `_ensure_schema()` (CREATE TABLE IF NOT EXISTS).
- Test count target: ~15 tests.
- LLMClient.chat is async (verify-first at build time per AD-685 kwarg pre-check coverage).

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3 closes GH #79.**

```pwsh
gh issue close 79 --comment "AD-487 v1 closed in Wave 14 — see DECISIONS.md (Map step shipped: PersonalOntologyProber + agent_probes table; Collapse/Reduce/Daydream/DID-portability deferred to AD-487b/c/d/e)" --reason completed
```

Retrospective: optional. Heuristic — write only if AD-685 kwarg pre-check catches a phantom (validates ongoing tooling) OR if LLM rate-limit integration surfaces a new convention.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-14.md and README-wave-14-pass-2.md
- 1 source commit (AD-487)
- Full gate green; +15 tests
- 0 hard-stops
- GH issue #79 closed
- DECISIONS.md entry for AD-487 under Era V
