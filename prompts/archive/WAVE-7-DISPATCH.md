# Wave 7 Prompt Drafting — Architect Subagent Dispatch

**Date:** 2026-05-01
**Mode:** Architect subagent (use the Architect agent type, run as a subagent invocation)
**Output:** 5 build prompts at `prompts/ad-{456,463,466,467,528}-*.md`, ready for Builder
**Estimated time:** ~1.5–2.5 hours subagent compute (AD-463 is foundation work and may take longer than the others)

---

## Subagent Prompt — paste into `runSubagent` invocation with `agentName: Architect`

```
You are the ProbOS Architect. Draft 5 build prompts for Wave 7 of the wave-5-8 fleet
sweep. Apply the conventions established by Waves 5 and 6 (DECISIONS.md "Wave 5
Retrospective" entry, dated 2026-05-01) — they are now standing rules for prompt
drafting in this codebase. Verify-first against the live codebase at d:/ProbOS for
every concrete claim — do NOT draft from memory.

## Inputs (read first, in order)

1. .github/copilot-instructions.md — engineering principles, layer architecture,
   hard rules.
2. prompts/review-criteria.md — review tiers and standing format.
3. DECISIONS.md "Wave 5 Retrospective" — 7 standing conventions (read this fully;
   they are MANDATORY for Wave 7 prompts).
4. prompts/WAVE-5-8-RECONCILED-PLAN.md — wave context and sequencing.
5. prompts/wave-5-8-ad-selection-plan.md — per-AD scope summaries and verify-first
   reminders.
6. prompts/AD-BACKLOG-AUDIT.md — classification table for each AD's risk, file
   footprint, dependencies, and EventType additions.
7. Three recent reference prompts that show the standard template applied well:
   - prompts/archive/ad-451-validation-framework-hardening.md (Wave 6; HIGH risk;
     mirrors no-theater discipline + flat dataclass pattern + real-consumer
     wiring)
   - prompts/archive/ad-459-saucer-separation-graceful-degradation.md (Wave 6;
     HIGH risk; mirrors coordinator-then-dispatch pattern + new-package
     directory ownership)
   - prompts/archive/ad-457-engineering-crew.md (Wave 6; mirrors agent-pool
     directory ownership + concrete pool wiring per agent_fleet.py:154-198)
8. .claude/agents/architect.md (if accessible) — architect agent standing
   instructions.

Match these reference prompts' structure and verify-first discipline.

## Wave 7 ADs to draft

| AD | Title | Risk | Audit Group | Roadmap line |
|---|---|---|---|---|
| AD-456 | Security Infrastructure (Secrets/Sandbox/Egress/Audit) | high | 2 | docs/development/roadmap.md:4142 |
| AD-463 | Model Diversity & Neural Routing (FOUNDATION) | high | 4 | docs/development/roadmap.md:4169 |
| AD-466 | Engineering Infrastructure (Backup/CI/CD/Observability/Storage) | medium | 3 | docs/development/roadmap.md:4177 |
| AD-467 | Operations Crew (Resource Mgmt & Coordination) | medium | 3 | docs/development/roadmap.md:4181 |
| AD-528 | Ground-Truth Task Verification (Anti-Fabrication) | high | 2 | docs/development/roadmap.md:6489 |

## Required Sections in Each Prompt

Every prompt MUST contain (in this order):

1. Title and one-line summary.
2. Status / Dependencies / Estimated tests header.
3. Problem (concrete, with grep-confirmed file paths and line numbers).
4. Solution overview.
5. Section 0: Event Types — list every new EventType value the AD introduces with
   its exact insertion point in src/probos/events.py. NON-NEGOTIABLE.
6. Implementation sections (### Section 1, ### Section 2, ...) — each
   independently buildable. Use SEARCH/REPLACE blocks for modifications with at
   least 3 lines of context. Use full code for new files.
7. Tests — explicit test plan with named test cases following the
   test_{method}_{scenario}_{expected} naming convention.
8. What This Does NOT Change — explicit out-of-scope list.
9. Tracking — which trackers update (PROGRESS.md / roadmap.md / DECISIONS.md).
10. Pre-Commit Sanity Check — copy-paste from Wave 6 prompts (git diff --cached
    --stat, >200-line deletion = STOP).
11. Acceptance Criteria — including the standing line: "Verify all changes comply
    with the Engineering Principles in .github/copilot-instructions.md."
12. Verified Against Codebase (date) — paste the grep evidence for every concrete
    claim in the prompt. Every API/file/line/method assertion in the prompt body
    must map to a grep hit shown here.

## Wave-5 Standing Conventions (MANDATORY for Wave 7)

These are now standing rules per the DECISIONS.md Wave 5 Retrospective:

1. **Public-attribute wiring.** Any service wired onto `ProbOSRuntime` that is
   read by code outside `runtime.py` must be a public attribute (e.g.,
   `runtime.secrets_service`, NOT `runtime._secrets_service`). Reserve leading
   underscores for runtime-internal state only.
2. **stdlib-only for runtime persistence.** If a Wave 7 AD writes a config or
   state file, default to JSON via stdlib. Do NOT introduce new pyproject
   dependencies without explicit architect approval surfaced before drafting.
3. **Coordinator-then-dispatch pattern.** If an AD proposes synthesizing live
   intents into existing systems for testing/validation, defer the dispatch
   mechanism to a sub-AD. Deliver the read-only coordinator first.
4. **Superset-filter discipline.** When inserting validation hooks into existing
   flows, the new hook must NOT intercept cases the existing tests cover.
5. **`init_<phase>` startup signatures.** Grep the startup phase function's
   actual signature before claiming `runtime.X` is in scope. Most
   `src/probos/startup/*.py` modules use parameter callbacks, not the runtime
   object.
6. **Verify-first for anchor names.** Every anchor name referenced in an
   implementation section must have grep evidence in the Verified Against
   Codebase footer.
7. **No-theater discipline.** Any v1 component that ships as a stub waiting for
   v2 must either (a) do something real today (read existing state, emit events,
   reject obviously-bad inputs), or (b) be removed from v1 and put entirely into
   the deferred sub-AD. The AD-455 v1-vs-AD-455b precedent and AD-451
   TwoStageVerifier real-consumer wiring are the canonical examples.

## Wave-6 Standing Notes (apply where relevant)

These minor conventions emerged from Wave 6 builds:

- **TYPE_CHECKING cross-layer imports.** When a lower layer needs to type-hint a
  higher-layer class for static analysis only, use a TYPE_CHECKING-guarded
  import and add the file pair to `tests/test_layer_boundaries.py`
  ALLOWED_EXCEPTIONS. Don't restructure to avoid the layer boundary if the
  import is type-only. Mirrors BF-085 precedent.
- **ASCII-only source comments.** Use ASCII characters in source-file comments.
  Unicode arrows (←/→), em-dashes (—), and similar break Windows `cp1252` default
  `Path(...).read_text()` calls in tests that read source files. Use `<-`,
  `->`, `--` instead.
- **Anchor-chain fallback to AD-440 terminal.** When a prompt's SEARCH anchors
  on a previous-wave prompt that may not have landed yet, the fallback chain
  must terminate at `orders: OrdersConfig = OrdersConfig()` (config.py:1593,
  AD-440 landmark). This guarantees Builder can find a valid anchor regardless
  of build order.

## AD-Specific Requirements

### AD-456 (Security Infrastructure — Secrets/Sandbox/Egress/Audit)
- Verify-first: grep src/probos/security/ to confirm AD-455's directory exists.
  AD-456 EXTENDS AD-455's package — does NOT own __init__.py creation.
- Verify the SecretsManager interface does not exist anywhere; if a stub does,
  document it and adjust scope.
- 4 sub-capabilities: SecretsManager, RuntimeSandbox, EgressPolicy, AuditLog.
  Apply the **coordinator-then-dispatch** convention: v1 may ship 2-3 fully
  functional capabilities and defer the most invasive (likely RuntimeSandbox —
  process isolation is a deep change) to AD-456b.
- Likely creates src/probos/security/{secrets,sandbox,egress,audit}.py and
  touches startup/finalize.py for wiring.
- Section 0 EventTypes: SECRET_ROTATED, SANDBOX_VIOLATION, EGRESS_BLOCKED,
  AUDIT_RECORDED (or similar — pick stable names; verify no collisions).
- HIGH risk: cross-cutting; touches startup, runtime, and possibly the LLM
  client for outbound HTTP if egress policy is enforced at the HTTP layer.
  Acceptance criteria must require destructive-intent consensus gating where
  appropriate.

### AD-463 (Model Diversity & Neural Routing — FOUNDATION)
- This is the highest-complexity AD in the wave and likely needs the longest
  drafting time. Verify ModelRegistry does NOT exist (grep returned no
  matches — confirm in your own pass).
- Verify-first: grep src/probos/cognitive/llm_client.py for the existing
  `BaseLLMClient` ABC and `OpenAICompatibleClient` patterns. AD-463 EXTENDS
  this — it does NOT replace it.
- 10 sub-capabilities listed in roadmap line 4169. **Apply no-theater
  discipline aggressively** — v1 should ship maybe 3-4 real capabilities
  (ModelRegistry catalog + ProviderABC + a router stub that is wired into one
  real call site + cost-aware selection at one decision point). Defer
  multi-model comparison, MAD confidence scoring, brain diversity, hot-swap,
  per-model edit format selection to sub-ADs.
- HebbianRouter integration: do NOT extend HebbianRouter directly; introduce a
  ModelRouter that consults HebbianRouter weights via a public API. Verify the
  HebbianRouter weight-query API exists (grep src/probos/mesh/routing.py).
- Likely creates src/probos/cognitive/model_registry.py (NEW) and
  src/probos/cognitive/model_router.py (NEW). Touches src/probos/cognitive/
  llm_client.py for the consumer hook.
- Section 0 EventType: MODEL_ROUTED, MODEL_FALLBACK.
- HIGH risk: foundation work that AD-428b, AD-462f, AD-469 all depend on.
  Acceptance criteria must NOT require all 10 capabilities — explicit v1 scope
  with deferred items listed.
- Connects to AD-460 (Cognitive Journal — token ledger) for cost tracking;
  verify the journal's existing schema supports the cost-aware routing data
  AD-463 needs to record.

### AD-466 (Engineering Infrastructure — Backup/CI/CD/Observability/Storage)
- 5 capabilities listed. Apply no-theater: v1 ships a subset that does real
  work today; defer the rest.
- Repo-level capabilities (CI/CD pipeline, GitHub Actions changes) should be
  scoped carefully — they're not Python changes, they're .github/workflows/
  changes. Verify what's already in .github/workflows/.
- Backup/Restore likely creates src/probos/infrastructure/backup.py (new
  package) — AD-466 may OWN src/probos/infrastructure/__init__.py creation
  if it's the first AD in that directory. Verify and call out explicitly.
- StorageBackend ABC may be foundational for future PostgreSQL migration;
  scope this carefully. v1 may ship only the ABC + SQLite default, defer
  PostgreSQL implementation.
- Section 0 EventTypes: BACKUP_COMPLETE, BACKUP_FAILED, OBSERVABILITY_EXPORT
  (or similar).
- MED risk: most repo-level work doesn't touch runtime semantics.

### AD-467 (Operations Crew — Resource Management & Coordination)
- Mirrors AD-457 (Engineering Crew) structure. Likely creates
  src/probos/agents/operations/ (NEW package) — AD-467 OWNS the directory
  creation, mirroring AD-457's agents/engineering/ precedent.
- 6 capabilities listed (Resource Allocator, Scheduler, Coordinator, Workflow
  Definition API, Response-Time Scaling, LLM Cost Tracker). Apply no-theater:
  v1 ships maybe 3 agents (Resource Allocator, Scheduler, Coordinator) plus
  the Workflow Definition API endpoint. Defer Response-Time Scaling and
  LLM Cost Tracker to sub-ADs.
- LLM Cost Tracker depends on AD-460 (Cognitive Journal — partial-complete)
  and AD-463 (this wave's ModelRegistry). Sequence carefully.
- Section 0 EventTypes: RESOURCE_ALLOCATED, TASK_SCHEDULED, WORKFLOW_STARTED.
- MED risk: cross-cutting (touches workforce.py, scheduler.py, IntentBus
  budget enforcement hooks).

### AD-528 (Ground-Truth Task Verification — Anti-Fabrication)
- Verify-first: grep src/probos/ for existing fabrication-detection patterns
  (BF-204, AD-592 are precedents per the roadmap entry). AD-528 enhances —
  does NOT replace — these.
- Likely creates src/probos/cognitive/ground_truth.py (new) and touches
  feedback/ for the verification hook seam.
- Apply coordinator-then-dispatch: v1 likely ships a verification scoring
  service that observes BookingJournal entries and Ward Room messages and
  emits VERIFICATION_FAILED events; active rejection/quarantine deferred to a
  sub-AD.
- Section 0 EventType: VERIFICATION_FAILED, VERIFICATION_PASSED.
- HIGH risk: trust/safety critical. This is the "Agents of Chaos" failure-mode
  countermeasure cited in the roadmap. Acceptance criteria must include
  episode storage so future audits can retrospectively verify the
  verification.

## Inter-Prompt Dependencies

- **AD-456 builds on AD-455's security/ directory.** Verify the directory
  exists today (it does — AD-455 shipped in Wave 5).
- **AD-463 is foundation for AD-467 LLM Cost Tracker.** AD-467's prompt
  should explicitly defer LLM Cost Tracker to wait for AD-463.
- **AD-466 may touch the same files as AD-461 (Telemetry, complete).** Verify
  no overlap.
- **AD-528 may interact with AD-451 (Validation Framework, just landed in
  Wave 6).** Verify whether AD-528 should integrate with AD-451's
  ReconciliationEscalator or operate independently. If they integrate,
  document the seam.

## Output

Write each prompt to:
- prompts/ad-456-security-infrastructure.md
- prompts/ad-463-model-diversity-neural-routing.md
- prompts/ad-466-engineering-infrastructure.md
- prompts/ad-467-operations-crew.md
- prompts/ad-528-ground-truth-task-verification.md

Do NOT modify any source files. Do NOT modify PROGRESS.md / DECISIONS.md /
roadmap.md. The output of this dispatch is 5 prompt files only.

After all 5 prompts are written, run a final pre-commit check:

  git diff --cached --stat

Expected delta: 5 new files. AD-463 may run 600-800 lines (foundation work);
the others 400-600 each. Total ~2400-3300 lines. No deletions.

Commit with the message:
  "Wave 7: draft prompts for AD-456, AD-463, AD-466, AD-467, AD-528"

Push to origin/main.

## Hard-Stop Conditions

Stop and surface to the dispatching architect (NOT the user) if:

1. AD-463: ModelRegistry has any pre-existing footprint in the codebase. The
   architect's pre-check found no matches; if you find any, surface — the
   prompt scope changes.
2. AD-456: SecretsManager / sandbox primitives have any pre-existing
   implementation that must be replaced (vs extended). Surface for scope
   guidance.
3. AD-466: GitHub Actions workflow changes would conflict with active CI
   pipelines. Verify .github/workflows/ contents before specifying changes.
4. AD-467: agents/operations/ already exists. Means someone created the
   package between waves; AD-467's directory ownership note needs revision.
5. AD-528: existing ground-truth verification pattern exists (BF-204, AD-592)
   that already covers AD-528's scope. Surface for de-scoping.
6. Any AD's Section 0 EventTypes collide with values already in events.py OR
   with another Wave 7 prompt's Section 0. Pick a different name and
   document.
7. AD-463's complexity exceeds what can be drafted in one session. Surface
   partial state — write what you have, list deferred items in a follow-up
   message. **For AD-463 specifically, it is acceptable to surface a draft
   that explicitly defers half its capabilities to AD-463b and AD-463c.** The
   no-theater discipline favors small-and-real over big-and-stub.
8. You cannot write all 5 prompts in one session. Surface partial state.

## Acceptance Criteria

- 5 prompt files created at the listed paths.
- Each prompt has all 12 required sections in order.
- Each prompt has Section 0: Event Types listing all new EventType values with
  insertion points.
- Each prompt has a Verified Against Codebase footer with grep evidence for
  every concrete claim.
- AD-466 explicitly addresses src/probos/infrastructure/__init__.py creation
  ownership (if applicable) per AD-455/AD-457 precedents.
- AD-467 explicitly owns src/probos/agents/operations/__init__.py creation
  per AD-457 precedent.
- AD-463 v1 scope is realistic — explicitly defers items to AD-463b/c.
  No-theater discipline applied aggressively.
- All Wave-5 standing conventions applied: public attributes, stdlib-only
  persistence, coordinator-then-dispatch, superset filters, init_phase
  signature verification, verify-first for anchors, no-theater.
- Wave-6 standing notes applied: ASCII-only source comments,
  TYPE_CHECKING cross-layer guidance where relevant, anchor-chain terminal
  fallback.
- Single commit lands; push succeeds; no source files touched.
- Pre-commit deletion sanity check clean.

Begin.
```

---

## Instructions to send to the user (for triggering the dispatch)

Same dispatch pattern as Wave 5/6:

1. Confirm `.claude/agents/architect.md` is present locally.
2. Invoke the Architect subagent with the prompt block above as the task.
3. Wall time: 1.5–2.5 hours subagent compute. AD-463 is foundation work and
   will likely take longer than the others.
4. When the subagent returns, you'll have 5 prompt files in `prompts/`.

After the dispatch completes, the next architect step is the standard 3-pass
review (Wave 5/6 cadence: review → revision → second-pass review).

Most likely hard-stops:

- **AD-463 v1 scope reduction** — the no-theater discipline may force the
  subagent to surface for explicit architect approval before settling on
  v1/v2 split. This is the highest-probability hard-stop in the wave.
- **AD-528 + AD-451 integration question** — does AD-528 integrate with the
  ReconciliationEscalator landed in Wave 6, or operate independently?
- **AD-466 GitHub Actions workflow conflicts** — verify what's already in CI
  before specifying.

All are <10 min architect decisions if they surface — surface to the
dispatching architect via the dispatching context, not the user.
