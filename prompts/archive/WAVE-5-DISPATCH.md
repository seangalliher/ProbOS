# Wave 5 Prompt Drafting — Architect Subagent Dispatch

**Date:** 2026-04-30
**Mode:** Architect subagent (use the Architect agent type, run as a subagent invocation)
**Output:** 5 build prompts at `prompts/ad-{439,440,455,468,499}-*.md`, ready for Builder
**Estimated time:** ~1–2 hours subagent compute (parallel batches if dispatcher supports it)

---

## Subagent Prompt — paste into `runSubagent` invocation with `agentName: Architect`

```
You are the ProbOS Architect. Draft 5 build prompts for Wave 5 of the wave-5-8 fleet
sweep. Each prompt must follow the standard ProbOS prompt template enforced by the
.github/copilot-instructions.md and prompts/review-criteria.md. Verify-first against
the live codebase at d:/ProbOS for every concrete claim — do NOT draft from memory.

## Inputs (read first, in order)

1. .github/copilot-instructions.md — engineering principles, layer architecture, hard
   rules. Comply with all of it.
2. prompts/review-criteria.md — review tiers and standing format.
3. prompts/WAVE-5-8-RECONCILED-PLAN.md — wave context and sequencing.
4. prompts/wave-5-8-ad-selection-plan.md — per-AD scope summaries and verify-first
   reminders.
5. prompts/AD-BACKLOG-AUDIT.md — classification table for each AD's risk, file
   footprint, dependencies, and EventType additions.
6. prompts/archive/ad-447-phase-gates-pool-group.md AND
   prompts/archive/ad-676-action-risk-tiers.md — two recent reference prompts that
   show the standard template applied well. Match their structure and verify-first
   discipline.
7. .claude/agents/architect.md (if accessible) — architect agent standing
   instructions.

## Wave 5 ADs to draft

| AD | Title | Risk | Audit Group | Roadmap line |
|---|---|---|---|---|
| AD-439 | Emergent Leadership Detection | medium | 3 | docs/development/roadmap.md:4083 |
| AD-440 | Chain of Command Delegation | high | 3 | docs/development/roadmap.md:4085 |
| AD-455 | Security Team — Threat Detection & Trust Integrity | high | 2 | docs/development/roadmap.md (search) |
| AD-468 | Runtime Configuration Service | medium | 3 | docs/development/roadmap.md:4183 |
| AD-499 | Ship & Crew Naming Conventions | low | 1A | docs/development/roadmap.md:6967 |

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
10. Pre-Commit Sanity Check — copy-paste from prior prompts (git diff --cached
    --stat, >200-line deletion = STOP).
11. Acceptance Criteria — including the standing line: "Verify all changes comply
    with the Engineering Principles in .github/copilot-instructions.md."
12. Verified Against Codebase (date) — paste the grep evidence for every concrete
    claim in the prompt. Every API/file/line/method assertion in the prompt body
    must map to a grep hit shown here.

## AD-Specific Requirements

### AD-439 (Emergent Leadership Detection)
- Verify HebbianRouter weight access patterns. Grep src/probos/mesh/routing.py for
  the public weight-query API. Confirm Hebbian data is queryable.
- Likely creates src/probos/cognitive/leadership.py (new) and touches
  src/probos/mesh/routing.py for read access.
- Section 0 EventType: LEADERSHIP_DIVERGENCE (or similar — pick a stable name).
- LOW–MED risk; analytics-only.

### AD-440 (Chain of Command Delegation)
- Verify the authority_over ontology relationship. Grep
  src/probos/ontology/service.py and config/organization.yaml for authority_over.
- Confirm that issue_order() does not exist. Grep widely.
- Likely creates src/probos/cognitive/orders.py (new) and touches
  src/probos/cognitive/proactive.py for context injection.
- Section 0 EventType: ORDER_ISSUED.
- HIGH risk: trust/authority semantics. Acceptance criteria must require
  destructive-intent consensus gating where appropriate.
- Depends on AD-477 (Naval Org Protocols, NOT BUILT). If AD-477 is a hard
  prerequisite for the order semantics, surface this — wave-5-8 plan said all
  deps met but AD-477 should be verified before drafting.

### AD-455 (Security Team — Threat Detection & Trust Integrity)
- src/probos/security/ does NOT exist. AD-455 OWNS the directory creation,
  mirroring AD-676's governance/__init__.py precedent. Make this explicit in
  Section 1 of the prompt.
- Verify-first: grep for existing RedTeamAgent, SIF (Security Information Flow)
  module locations. Verify agent pool spawn patterns in src/probos/runtime.py.
- Likely creates src/probos/security/{__init__,threat_detector,trust_integrity,
  input_validator,red_team_lead}.py (new package).
- Section 0 EventTypes: THREAT_DETECTED, TRUST_INTEGRITY_VIOLATION.
- HIGH risk: cross-cutting (touches events.py, runtime.py, finalize.py).

### AD-468 (Runtime Configuration Service — Ship's Computer)
- Verify existing runtime config patterns. Grep src/probos/config.py for the
  runtime_overrides pattern (does runtime_overrides.toml exist? if not, AD-468
  introduces it).
- Verify NL-driven config does not already exist via grep for "Ship's Computer"
  in src/probos/cognitive/.
- Likely creates src/probos/runtime/config_service.py (new) and touches
  src/probos/experience/shell.py for the slash command.
- Section 0 EventType: CONFIG_CHANGED.
- MED risk: cross-cutting (touches config, runtime, shell).

### AD-499 (Ship & Crew Naming Conventions)
- Verify deps are closed: AD-441 (DIDs), AD-441b (Commission), AD-442 (Naming
  Ceremony) all CLOSED per PROGRESS.md.
- Verify-first: grep for existing naming/identity modules in src/probos/identity/.
- Likely creates src/probos/identity/naming.py (new) and touches
  src/probos/config.py for the naming format config.
- Section 0 EventTypes: SHIP_NAMED, AGENT_SELF_NAMED.
- LOW risk: trivial-class. Audit Group 1A. Smallest of the 5.

## Verify-First Discipline Examples

For every concrete claim:

WRONG (do not do this):
> Section 1: Add ChainOfCommand class to src/probos/ontology/service.py around
> line 200.

RIGHT (do this):
> grep -n "class OntologyService" src/probos/ontology/service.py
>   180: class OntologyService:
> grep -n "authority_over" src/probos/ontology/service.py
>   (no match — relationship lives in YAML, parsed at line 245)
>
> Section 1: Add issue_order() method to OntologyService at line ~250 (after
> the existing authority_over parser block). SEARCH targets the line content,
> not the line number, since line numbers may drift.

## Hard Rules (carry forward)

- NEVER assert a method/file/line that you have not grep-confirmed in the live
  codebase. The wave-1-4 retrospective showed phantom APIs were the top cause
  of Builder hard-stops.
- For SEARCH/REPLACE blocks: the SEARCH literal must include any inline
  comments or formatting present in the live file. The wave-1-4 BF-247 prompt
  had to be hot-fixed because a SEARCH block didn't include a "# AD-585"
  trailing comment. Never trust a stripped paste; always grep the literal
  line.
- AD-455 MUST own src/probos/security/__init__.py creation. Single most
  important AD-specific instruction in this batch.
- Common false-positive patterns to AVOID flagging:
  - "EventType.X is missing" when YOUR OWN Section 0 adds it (it's the migration,
    not the pre-state).
  - "model_validator(mode='after')" — valid Pydantic v2.
  - "hasattr(runtime, 'emit_event')" guards — these are dead code post-AD-680;
    use runtime.emit_event directly in NEW prompts.

## Output

Write each prompt to:
- prompts/ad-439-emergent-leadership-detection.md
- prompts/ad-440-chain-of-command-delegation.md
- prompts/ad-455-security-team-threat-detection.md
- prompts/ad-468-runtime-configuration-service.md
- prompts/ad-499-ship-crew-naming-conventions.md

Do NOT modify any source files. Do NOT modify PROGRESS.md / DECISIONS.md /
roadmap.md. The output of this dispatch is 5 prompt files only.

After all 5 prompts are written, run a final pre-commit check:

  git diff --cached --stat

Expected delta: 5 new files, ~1500–2500 lines total (300–500 each). No deletions.
If the deletion column shows >0, STOP — something went wrong with the file
writes.

Commit with the message:
  "Wave 5: draft prompts for AD-439, AD-440, AD-455, AD-468, AD-499"

Push to origin/main.

## Hard-Stop Conditions

Stop and surface to the dispatching architect (NOT the user) if:

1. AD-477 is a hard prerequisite for AD-440 — verify by reading AD-477's
   description; if hard, surface and AD-440 may need deferral.
2. Any AD's Section 0 EventTypes collide with values already in events.py.
   Pick a different name and document.
3. The roadmap line for any AD is missing or significantly different from the
   wave-5-8 plan's summary. Means the audit's classification was wrong; surface.
4. src/probos/security/ already exists. Means someone created the package
   between the audit and this dispatch; AD-455's __init__.py ownership note
   needs revision.
5. You cannot write all 5 prompts in one session. Surface partial state — write
   what you have, list what's incomplete in a follow-up message.

## Acceptance Criteria

- 5 prompt files created at the listed paths.
- Each prompt has all 12 required sections in order.
- Each prompt has Section 0: Event Types listing all new EventType values with
  insertion points.
- Each prompt has a Verified Against Codebase footer with grep evidence for
  every concrete claim.
- AD-455 explicitly owns src/probos/security/__init__.py creation.
- Single commit lands; push succeeds; no source files touched.
- Pre-commit deletion sanity check clean.

Begin.
```

---

## Instructions to send to the user (for triggering the dispatch)

To run this from VS Code chat with the architect subagent, paste the entire prompt block above into a `runSubagent` invocation. From the CLI or any agent harness that supports the Architect agent type:

1. Confirm `.claude/agents/architect.md` is present locally (it is — verified earlier).
2. Invoke the Architect subagent with the prompt block above as the task.
3. Wall time: 1–2 hours subagent compute. The 5 prompts are independent; the subagent can write them sequentially or in batches at its discretion.
4. When the subagent returns, you'll have 5 prompt files in `prompts/` ready for review.

After the dispatch completes, the next architect step is a verify-first review pass over the 5 drafted prompts (3-pass tier system from `review-criteria.md`). That review can happen as a separate Architect subagent invocation or in the main session, depending on how interactive you want it.

If the subagent surfaces a hard-stop condition, the most likely candidates are AD-477 prerequisite for AD-440 and any EventType naming collision. Both are quick decisions if they come up.
