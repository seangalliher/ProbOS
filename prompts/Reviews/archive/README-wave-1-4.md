# Wave 1-4 Prompt Review Sweep — 2026-04-29

**Reviewer:** Architect (with parallel Explore subagents for verification)
**Scope:** 20 newly-drafted prompts from commit `ec00b25` ("Draft 20 build prompts for Waves 1-4")
**Method:** Verify-first review against the live codebase. Each prompt's concrete API/file/line/method assertions were grepped before being judged.

---

## Verdict Summary

| Verdict | Count |
|---|---|
| ✅ Approved | **9** |
| ⚠️ Conditional | **10** |
| ❌ Not Ready | **1** |

---

## Per-Prompt Verdicts (sorted by AD)

| AD | Title | Verdict | Headline |
|---|---|---|---|
| 438 | Ontology-Based Task Routing | ⚠️ Conditional | Missing `EventType.TASK_ROUTED` |
| 445 | Decision Queue & Pause/Resume | ⚠️ Conditional | Missing event type; `governance/` dir must be created |
| 446 | Compensation & Recovery Pattern | ⚠️ Conditional | Missing event type; depends on AD-445 |
| 447 | Phase Gates for PoolGroup | ✅ Approved | Clean; all references verified |
| 448 | Wrapped Tool Executor | ⚠️ Conditional | Missing `EventType.TOOL_INVOKED` |
| 461 | Ship's Telemetry | ✅ Approved | Clean addition |
| 465 | Containerized Deployment | ✅ Approved | One Required: validator decorator pattern |
| 470 | IntentBus Enhancements | ⚠️ Conditional | Missing `defaultdict` import; timing-instrumentation specifics |
| 489 | Federation Code of Conduct | ✅ Approved | Clean |
| 490 | Agent Wiring Security Logs | ✅ Approved | Clean |
| 524 | Ship's Archive | ⚠️ Conditional | OracleService doesn't accept `archive_store` — Section 3 SEARCH/REPLACE will fail |
| 561 | Intervention Classification | ⚠️ Conditional | Missing `Enum` import + missing event type |
| 566f | Qualification → Skill Bridge | ⚠️ Conditional | Class name mismatch (`SkillService` vs `AgentSkillService`) |
| 566i | Role Skill Template Expansion | ✅ Approved | Clean; matches existing patterns |
| 674 | Graduated Initiative Scale | ⚠️ Conditional | Threshold config not wired to call site |
| 675 | Uncertainty-Calibrated Initiative | ❌ Not Ready | Hard dependency on AD-674 (not built yet) |
| 676 | Action Risk Tiers | ✅ Approved | All deps verified |
| 677 | Context Provenance Metadata | ✅ Approved | Clean |
| 678 | Memory Transparency Mechanism | ⚠️ Conditional | Depends on AD-677 |
| 679 | Selective Disclosure Routing | ✅ Approved | Clean |

Per-prompt detail in `prompts/Reviews/ad-NNN-*-review.md`.

---

## Cross-Cutting Patterns

### 1. Missing event-type enum entries dominate the Required list

Six prompts (AD-438, 445, 446, 448, 561, 676) introduce new `EventType` enum values that don't yet exist in [src/probos/events.py](src/probos/events.py). None of the prompts include the enum addition as Section 1 — they all assume the value is in scope. **Pattern fix:** add a "Section 0: Event Types" subsection to the prompt template that lists every new `EventType` value the AD references, with the exact insertion point near the appropriate cluster (governance, tools, counselor, etc.).

### 2. The `governance/` directory does not exist yet

AD-445 (DecisionQueue) and AD-676 (ActionRiskTiers) both create files under `src/probos/governance/`. Neither prompt explicitly instructs the builder to create `src/probos/governance/__init__.py` first. Whichever AD is built first should own the directory creation; the second should reference it. Document this in the wave's Builder execution plan.

### 3. Verify-first discipline caught two phantom-API class-name bugs

- AD-524 asserts `OracleService.__init__(archive_store=...)` — parameter doesn't exist.
- AD-566f asserts `SkillService` — actual class is `AgentSkillService`.

Both would have caused Builder-time SEARCH/REPLACE failures. The standing review template (with mandatory grep evidence) is doing its job; recommend keeping it for all future prompt batches.

### 4. Cross-AD dependency chain needs explicit sequencing

Several prompts depend on others in this same batch:

- AD-446 → AD-445 (DecisionQueue must exist)
- AD-675 → AD-674 (InitiativeLevel + resolve_initiative_level)
- AD-678 → AD-677 (ProvenanceTag/Envelope)

The new Builder execution plan for this wave needs an explicit DAG showing build order, not just a flat list.

### 5. Defensive `getattr` / `hasattr` for in-prompt APIs is creeping back in

AD-445 uses `hasattr(runtime, 'emit_event')` even though AD-680 makes `emit_event` a stable public method. AD-561 uses `hasattr(assessment, 'trigger')` for an attribute defined in the same prompt. Pattern flagged in user-memory; reviewers should keep raising it.

---

## Recommended Build Order

Sequenced for dependency safety:

**Wave 1A — independent, low-risk (parallel safe):**
- AD-447 (PoolGroup Phase Gates)
- AD-461 (Ship's Telemetry)
- AD-465 (Containerized Deployment) — after fixing the validator-pattern issue
- AD-489 (Federation CoC)
- AD-490 (Agent Wiring Security Logs)
- AD-566i (Role Skill Template Expansion)

**Wave 1B — Conditional, fixable in one round:**
- AD-438 (Ontology Routing) — add event type
- AD-448 (Wrapped Tool Executor) — add event type
- AD-470 (IntentBus Enhancements) — add `defaultdict` import; pin timing line

**Wave 2 — governance + risk substrate (sequenced):**
- AD-676 (Action Risk Tiers, owns `governance/__init__.py` creation)
- AD-445 (DecisionQueue, references existing `governance/`)
- AD-446 (Compensation, after AD-445)

**Wave 3 — counselor + interventions:**
- AD-561 (Intervention Classification) — add Enum import + event type
- AD-566f (Qualification → Skill Bridge) — fix class name + ProficiencyLevel import

**Wave 4 — Northstar initiative + provenance (must sequence):**
- AD-674 (Graduated Initiative Scale) — fix threshold wiring
- AD-675 (Uncertainty-Calibrated Initiative) — only after AD-674 ships
- AD-677 (Context Provenance Metadata)
- AD-678 (Memory Transparency) — only after AD-677 ships
- AD-679 (Selective Disclosure Routing) — independent
- AD-524 (Ship's Archive) — needs OracleService param decision

---

## Readiness Tracker for the Builder

| AD | Action Required Before Builder Picks Up |
|---|---|
| 438 | Author: add `EventType.TASK_ROUTED` to prompt Section 0 |
| 445 | Author: add event type + explicit `governance/__init__.py` creation step |
| 446 | Author: add event type; document AD-445 prerequisite |
| 447 | **None — ready** |
| 448 | Author: add `EventType.TOOL_INVOKED` |
| 461 | **None — ready** |
| 465 | Author: switch `model_validator` → `field_validator` |
| 470 | Author: add `defaultdict` import; spell out `send()` timing |
| 489 | **None — ready** |
| 490 | **None — ready** |
| 524 | Author: decide on `OracleService.archive_store` parameter (add to AD or defer) |
| 561 | Author: add `Enum` import + event type |
| 566f | Author: fix class name (`AgentSkillService`) + add `ProficiencyLevel` import |
| 566i | **None — ready** |
| 674 | Author: wire `initiative_trust_thresholds` config to `resolve_initiative_level()` call site |
| 675 | **HOLD** — wait for AD-674 to ship |
| 676 | **None — ready** (owns `governance/__init__.py` creation) |
| 677 | **None — ready** |
| 678 | Hold — wait for AD-677 to ship |
| 679 | **None — ready** |

**Ready now (9):** 447, 461, 489, 490, 566i, 676, 677, 679, plus AD-465 once the validator pattern is corrected.

**Quick fixes (10):** 438, 445, 446, 448, 470, 524, 561, 566f, 674, 678 — all single-round revisions, mostly missing event types or imports.

**Hold (1):** 675 — blocked on AD-674.

---

## Notes for the Author

- Most Conditional findings are minor and can be batched into a single revision pass.
- The "missing EventType" pattern is repetitive enough to warrant a one-line prompt-template requirement: **"List every new `EventType` value introduced by this AD with its exact insertion point in `events.py`."**
- The Wave 1-4 build will need its own execution plan analogous to `prompts/BUILDER-EXECUTION-PLAN.md` — recommend drafting it after the Conditional fixes land and the dependency DAG is locked.
