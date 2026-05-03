# Wave 6 Prompt Drafting — Architect Subagent Dispatch

**Date:** 2026-05-01
**Mode:** Architect subagent (use the Architect agent type, run as a subagent invocation)
**Output:** 5 build prompts at `prompts/ad-{451,457,458,459,491}-*.md`, ready for Builder
**Estimated time:** ~1–2 hours subagent compute

---

## Subagent Prompt — paste into `runSubagent` invocation with `agentName: Architect`

```
You are the ProbOS Architect. Draft 5 build prompts for Wave 6 of the wave-5-8 fleet
sweep. Apply the conventions established by Wave 5 (DECISIONS.md "Wave 5 Retrospective"
entry, dated 2026-05-01) — they are now standing rules for prompt drafting in this
codebase. Verify-first against the live codebase at d:/ProbOS for every concrete
claim — do NOT draft from memory.

## Inputs (read first, in order)

1. .github/copilot-instructions.md — engineering principles, layer architecture,
   hard rules.
2. prompts/review-criteria.md — review tiers and standing format.
3. DECISIONS.md "Wave 5 Retrospective" — conventions (read this fully; the 7
   numbered conventions are MANDATORY for Wave 6 prompts).
4. prompts/WAVE-5-8-RECONCILED-PLAN.md — wave context and sequencing.
5. prompts/wave-5-8-ad-selection-plan.md — per-AD scope summaries and verify-first
   reminders.
6. prompts/AD-BACKLOG-AUDIT.md — classification table for each AD's risk, file
   footprint, dependencies, and EventType additions.
7. Two recent reference prompts that show the standard template applied well:
   - prompts/archive/ad-455-security-team-threat-detection.md (Wave 5; mirrors the
     Demeter uplift, Section 0 events, deferred-sub-AD pattern)
   - prompts/archive/ad-468-runtime-configuration-service.md (Wave 5; mirrors the
     stdlib-only pattern, public-attribute setters)
8. .claude/agents/architect.md (if accessible) — architect agent standing
   instructions.

Match these reference prompts' structure and verify-first discipline.

## Wave 6 ADs to draft

| AD | Title | Risk | Audit Group | Roadmap line |
|---|---|---|---|---|
| AD-451 | Validation Framework Hardening | high | 2 | docs/development/roadmap.md:4117 |
| AD-457 | Engineering Crew (Performance/Maintenance/Damage Control) | medium | 3 | docs/development/roadmap.md:4148 |
| AD-458 | Navigational Deflector (Pre-Flight Validation) | medium | 3 | docs/development/roadmap.md:4150 |
| AD-459 | Saucer Separation (Graceful Degradation) | high | 2 | docs/development/roadmap.md:4152 |
| AD-491 | Infodynamic Telemetry (Information Entropy) | low | 3 | docs/development/roadmap.md:5995 |

## Required Sections in Each Prompt

Every prompt MUST contain (in this order):

1. Title and one-line summary.
2. Status / Dependencies / Estimated tests header.
3. Problem (concrete, with grep-confirmed file paths and line numbers).
4. Solution overview.
5. Section 0: Event Types — list every new EventType value the AD introduces with
   its exact insertion point in src/probos/events.py. The wave-1-4 retrospective
   identified missing Section 0 as the top recurring cause of false-positive
   review failures. NON-NEGOTIABLE.
6. Implementation sections (### Section 1, ### Section 2, ...) — each
   independently buildable. Use SEARCH/REPLACE blocks for modifications with at
   least 3 lines of context. Use full code for new files.
7. Tests — explicit test plan with named test cases following the
   test_{method}_{scenario}_{expected} naming convention.
8. What This Does NOT Change — explicit out-of-scope list.
9. Tracking — which trackers update (PROGRESS.md / roadmap.md / DECISIONS.md).
10. Pre-Commit Sanity Check — copy-paste from Wave 5 prompts (git diff --cached
    --stat, >200-line deletion = STOP).
11. Acceptance Criteria — including the standing line: "Verify all changes comply
    with the Engineering Principles in .github/copilot-instructions.md."
12. Verified Against Codebase (date) — paste the grep evidence for every concrete
    claim in the prompt. Every API/file/line/method assertion in the prompt body
    must map to a grep hit shown here.

## Wave-5 Conventions (MANDATORY for Wave 6)

These are now standing rules per the DECISIONS.md Wave 5 Retrospective:

1. **Public-attribute wiring.** Any service wired onto `ProbOSRuntime` that is
   read by code outside `runtime.py` must be a public attribute
   (`runtime.validation_framework`, NOT `runtime._validation_framework`). Reserve
   leading underscores for runtime-internal state only.
2. **stdlib-only for runtime persistence.** If a Wave 6 AD writes a config file,
   default to JSON via stdlib. Do NOT introduce new pyproject dependencies
   without explicit architect approval surfaced before drafting.
3. **Coordinator-then-dispatch pattern.** If an AD proposes synthesizing live
   intents into existing systems (trust network, IntentBus, ward room) for
   testing/validation purposes, defer the dispatch mechanism to a sub-AD.
   Deliver the read-only coordinator/health-monitor first.
4. **Superset-filter discipline.** When inserting validation hooks into existing
   flows, the new hook must NOT intercept cases the existing tests cover. Gate
   on conditions the existing checks do NOT already handle.
5. **`init_<phase>` startup signatures.** Grep the startup phase function's
   actual signature before claiming `runtime.X` is in scope. Most
   `src/probos/startup/*.py` modules use parameter callbacks (`emit_event_fn`,
   `add_event_listener_fn`), not the runtime object.
6. **Verify-first for anchor names.** Every anchor name referenced in an
   implementation section must have grep evidence in the Verified Against
   Codebase footer. No "Builder will figure out the anchor" hand-waving. The
   Wave 5 review caught this pattern in AD-468 (`runtime.data_dir`), AD-455
   (`run_probe`, `red_team_agents`), AD-499 (`EventLog.append`).

## AD-Specific Requirements

### AD-451 (Validation Framework Hardening)
- Verify-first: grep src/probos/cognitive/red_team.py and src/probos/cognitive/
  system_qa.py for the existing RedTeam and SystemQA APIs. The AD enhances
  these — the prompt must verify what's already there before specifying
  additions.
- Verify whether `verify(...)` (the AD-455 deferred-sub-AD method) exists or
  needs introduction here. If it lives in red_team.py, document the seam.
- Likely touches src/probos/cognitive/{red_team,system_qa,validation_*}.py and
  consensus paths.
- Section 0 EventTypes: VALIDATION_RECONCILIATION_REQUESTED,
  VALIDATION_OUTCOME_VERIFIED (or similar — pick stable names).
- HIGH risk: cross-cutting (touches consensus paths, two-stage verification,
  reconciliation escalation). Acceptance criteria must require destructive-
  intent consensus gating where appropriate.

### AD-457 (Engineering Crew — Performance/Maintenance/Damage Control)
- Verify-first: grep src/probos/agents/ for existing crew patterns
  (medical/vitals_monitor.py is the closest model). Verify Surgeon and
  VitalsMonitor interfaces.
- Likely creates src/probos/agents/engineering/ (NEW package) with 4 child
  agents: PerformanceMonitor, MaintenanceAgent, InfrastructureAgent,
  DamageControlTeams. AD-457 OWNS the directory creation, mirroring AD-455's
  security/ precedent and AD-676's governance/ precedent.
- Section 0 EventTypes: DAMAGE_CONTROL_ACTIVATED, MAINTENANCE_SCHEDULED.
- MED risk: cross-cutting. Watch for naming collisions with existing
  monitoring services.

### AD-458 (Navigational Deflector — Pre-Flight Validation)
- Verify-first: grep src/probos/cognitive/builder.py for existing pre-flight
  hooks. Check the BuildSpec and self-mod pipeline for middleware seams.
- Likely creates src/probos/cognitive/pre_flight.py (new) and touches
  src/probos/cognitive/builder.py for the middleware seam.
- Section 0 EventType: PREFLIGHT_FAILED.
- MED risk: extends the build pipeline. Apply the AD-446 (CompensationHandler)
  pattern — pre-flight check is a separate handler invoked by the existing
  pipeline, not a re-architecture of it.

### AD-459 (Saucer Separation — Graceful Degradation)
- Verify-first: grep src/probos/runtime.py for service registration patterns,
  alert_conditions.py for the existing crisis-tier mechanism.
- AD-459 introduces a three-tier service classification: Essential / Cognitive
  / Non-essential. Likely creates src/probos/degradation/ (NEW package) with
  the tier registry and shedding policy. AD-459 OWNS the directory creation.
- Section 0 EventType: SERVICE_TIER_DEGRADED.
- HIGH risk: cross-cutting (touches runtime.py, startup/finalize.py, alert
  paths). Coordinate with the Wave 6 inter-prompt full gate to avoid
  shedding any test that verifies a degradable service.

### AD-491 (Infodynamic Telemetry — Information Entropy)
- Verify-first: grep src/probos/cognitive/ for existing entropy/metrics
  (emergence_metrics.py exists; AD-491 should NOT duplicate it).
- Likely creates src/probos/telemetry/infodynamic.py (new) and emits one or
  two new event types via existing telemetry pathways.
- Section 0 EventType: INFODYNAMIC_REPORT.
- LOW risk: pure observability. Smallest of the 5. Audit Group 3 even though
  it could be Group 1A — minor mid-batch grouping note.

## Output

Write each prompt to:
- prompts/ad-451-validation-framework-hardening.md
- prompts/ad-457-engineering-crew.md
- prompts/ad-458-navigational-deflector-preflight.md
- prompts/ad-459-saucer-separation-graceful-degradation.md
- prompts/ad-491-infodynamic-telemetry.md

Do NOT modify any source files. Do NOT modify PROGRESS.md / DECISIONS.md /
roadmap.md. The output of this dispatch is 5 prompt files only.

After all 5 prompts are written, run a final pre-commit check:

  git diff --cached --stat

Expected delta: 5 new files, ~2000–3000 lines total (400–600 each — Wave 5
averaged 509 lines per prompt). No deletions. If the deletion column shows
>0, STOP — something went wrong with the file writes.

Commit with the message:
  "Wave 6: draft prompts for AD-451, AD-457, AD-458, AD-459, AD-491"

Push to origin/main.

## Hard-Stop Conditions

Stop and surface to the dispatching architect (NOT the user) if:

1. AD-451 references a verify(...) API that does NOT exist in red_team.py and
   AD-451 does NOT itself introduce it — would be a phantom API gap that
   cascades into the AD-455b deferred dispatch.
2. AD-457's directory ownership conflicts with an existing agents/engineering/
   path — surface so the prompt can adjust.
3. Any AD's Section 0 EventTypes collide with values already in events.py OR
   with another Wave 6 prompt's Section 0. Pick a different name and
   document.
4. AD-459's three-tier classification overlaps with an existing alert_
   conditions.py tier system in a way that requires an architectural pick —
   surface for explicit architect decision before drafting Section 1.
5. The roadmap line for any AD is missing or significantly different from the
   wave-5-8 plan's summary. Means the audit's classification was wrong;
   surface.
6. You cannot write all 5 prompts in one session. Surface partial state — write
   what you have, list what's incomplete in a follow-up message.

## Acceptance Criteria

- 5 prompt files created at the listed paths.
- Each prompt has all 12 required sections in order.
- Each prompt has Section 0: Event Types listing all new EventType values with
  insertion points.
- Each prompt has a Verified Against Codebase footer with grep evidence for
  every concrete claim.
- AD-457 explicitly owns src/probos/agents/engineering/__init__.py creation.
  AD-459 explicitly owns src/probos/degradation/__init__.py creation.
- All Wave-5 conventions applied: public attributes, stdlib-only persistence,
  coordinator-then-dispatch, superset filters, init_phase signature
  verification, verify-first for anchors.
- Single commit lands; push succeeds; no source files touched.
- Pre-commit deletion sanity check clean.

Begin.
```

---

## Instructions to send to the user (for triggering the dispatch)

Same dispatch pattern as Wave 5:

1. Confirm `.claude/agents/architect.md` is present locally.
2. Invoke the Architect subagent with the prompt block above as the task.
3. Wall time: 1–2 hours subagent compute.
4. When the subagent returns, you'll have 5 prompt files in `prompts/` ready for review.

After the dispatch completes, the next architect step is a verify-first review pass over the 5 drafted prompts. Wave 5 converged in 2 review passes; Wave 6 should hit the same target with the conventions now codified in DECISIONS.md.

Most likely hard-stops:
- AD-451 + AD-455b deferred-dispatch interaction (the `verify(...)` API question).
- AD-459 tier classification overlapping with existing alert_conditions.py.

Both are quick decisions if they come up — surface to architect via the dispatching context, not the user.
