# WAVE 80 DISPATCH — AD-594c v1 Parallel Execution Dispatch (1-build, full scope)

**Wave id:** 80
**Umbrella AD:** AD-594 (Crew Consultation Protocol)
**Sub-AD in scope:** AD-594c
**Closes:** GH issue #162
**HEAD at draft:** `3bcd608` (post-Wave-79)
**Baseline test count:** 11528 → expected **≥ 11553** pytest (Δ ≥ +25)
**Builder required:** true (one focused build prompt)
**AD numbering:** Current highest stem in trackers: **AD-696** (Wave 72). AD-594c is the planned sub-AD assigned at GH issue #162 creation; no new number is minted by this wave.

## Verdict

Verify-first against HEAD `3bcd608` confirms the substrate AD-594c needs is in place:

- AD-594a substrate: `consultation/` package, `WorkspaceRegistry`, `ConsultationWorkspace.add_work_item(spec)` writes YAML to `workitems/`, `_ALLOWED_TRANSITIONS` (AD-594d extended `COMPLETED → CONSULTING/EXECUTING`), `WorkspaceLifecycleState` 7-state IntEnum.
- AD-496–498 substrate: `WorkItemStore` at `workforce.py:905`, `create_work_item(**kwargs)` (`:1004`), `list_work_items(status, assigned_to, parent_id, work_type, tags, limit, offset)` (`:1066`), `update_work_item(work_item_id, **updates)` (`:1108`); `WorkItem` dataclass has `depends_on: list[str]`, `metadata: dict`, `parent_id: str | None`, `tags: list[str]` (`:559-585`); `runtime.work_item_store` adopted at `runtime.py:1595`.
- Existing EventTypes `WORK_ITEM_CREATED` / `WORK_ITEM_STATUS_CHANGED` / `WORK_ITEM_ASSIGNED` (`events.py:87-90`) are reused; new EventTypes `PARALLEL_DISPATCH_STARTED` / `PARALLEL_DISPATCH_PROGRESS` / `PARALLEL_DISPATCH_BLOCKED` are collision-free (verified greenfield).

AD-594c v1 is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: every line of GH #162's stated scope ships in this wave. **AD-594b (#161 consultation primitive) is NOT a build-time dependency** — AD-594c reads `plan/plan_v{N}.md` regardless of who authored it (manual captain edit, AD-594b primitive output, dream synthesis). The roadmap "depends: AD-594b" is sequencing prose, not technical coupling. Verified at HEAD: nothing in the proposed surface imports from a hypothetical `consultation.consult` module.

| GH #162 scope bullet | Wave 80 action |
|---|---|
| Plan → WorkItem decomposition with dependency graph | **BUILD.** `PlanDecomposer.decompose(markdown_text) -> list[WorkItemSpec]` parses ATX-2 task headings + body lines `- id: <slug>`, `- file: <path>`, `- agent: <type>`, `- depends_on: [a, b]`, `- description: ...`, `- priority: 1..5`. Tolerant: missing fields default. |
| Conflict detection (no two executors on same resource) | **BUILD.** `ConflictDetector.detect(specs) -> list[ConflictPair]` flags any two specs that share at least one resource (`spec.resources`). Does NOT block dispatch; surfaces conflicts as a structured result so the dispatcher can serialize colliding specs by injecting synthetic `depends_on` edges. |
| Multi-executor assignment via WorkItemStore + IntentBus | **BUILD.** `ParallelDispatcher.dispatch(workspace_id, *, plan_version=None) -> DispatchReceipt` reads latest `plan/plan_vN.md`, decomposes, conflict-resolves (synthesizes serialization edges), registers each spec via `runtime.work_item_store.create_work_item(work_type="duty", title=..., description=..., depends_on=..., metadata={"workspace_id":..., "spec_id":..., "resources":[...]}, tags=["consultation", workspace_id], assigned_to=spec.agent or None)`, mirrors each spec into the workspace via `workspace.add_work_item(spec_dict_with_real_id)` for audit, transitions `APPROVED → EXECUTING`, emits `PARALLEL_DISPATCH_STARTED`. |
| Task boundary enforcement ("boundaries and control measures") | **BUILD.** Boundary metadata = the `resources` list on each spec; `ConflictDetector` is the enforcement primitive. v1 enforces by serializing colliding specs (deterministic order: original spec list order). |
| Progress tracking | **BUILD.** `ParallelDispatcher.get_progress(workspace_id) -> ProgressSnapshot` reads `runtime.work_item_store.list_work_items(tags=["consultation", workspace_id])` and returns `{total, by_status: dict, blocked_specs: list, completed: int, started_at, updated_at}`. Pure read; no mutation. |
| Completion verification | **BUILD.** `ParallelDispatcher.check_completion(workspace_id) -> bool`: when all dispatched WorkItems reach a terminal status (per `WorkTypeRegistry`), append a `dispatch_completed` journal entry, attempt `workspace.transition_to(COMPLETED, agent_id="captain")`. Idempotent. |
| Blocker escalation | **BUILD.** `ParallelDispatcher.detect_blockers(workspace_id, *, now=None) -> list[BlockerReport]` returns specs whose `depends_on` set is unmet AND wall-time-since-dispatch exceeds `ConsultationDispatchConfig.blocker_threshold_seconds` (default 600). Each blocker emits `PARALLEL_DISPATCH_BLOCKED` once (per-blocker dedup ring keyed on `(workspace_id, spec_id)`). Journal entry appended. |
| Pydantic config | **BUILD.** `ConsultationDispatchConfig` with `enabled=True`, `blocker_threshold_seconds=600.0`, `progress_subscription_enabled=True`, `default_work_type="duty"`, `default_tags=["consultation"]`. |
| Finalize wirer | **BUILD.** `_wire_consultation_dispatch(*, runtime, config) -> bool` mirrors `_wire_consultation_workspaces` shape; gated on `runtime.consultation_workspaces` AND `runtime.work_item_store`; sets `runtime.consultation_dispatcher`. Skips with INFO when either dependency is missing. |

## Reframe decision (Captain rule applied)

**Full-scope v1 in one wave. No deferral of stated scope.** Three pieces COULD have been pulled out as separate ADs but stay in v1:

1. **HXI surface for dispatch progress** — explicitly *not in GH #162* (issue body lists no HXI work). Stays out as scope-true, not deferral. AD-594c-i covers HXI when consumer signal arrives.
2. **AD-581 Hybrid Dispatch wiring** — `assigned_to=spec.agent` writes a string to the WorkItem; the actual ASA dispatcher hand-off lives under AD-581 (#113 Wave 81). AD-594c v1 produces correctly-shaped WorkItems; AD-581 routes them. Not a deferral — a sequencing.
3. **LLM-driven plan-to-spec semantic decomposition** — out of GH #162 scope (issue body says "Plan → WorkItem decomposition with dependency graph", not "LLM decomposition"). v1 ships a structured-markdown decomposer; LLM-driven decomposition is AD-594c-ii if signal warrants.

Closes #162 cleanly because every issue-body bullet ships.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  3bcd608

# AD-594a + AD-594d substrate (verified shipped):
src/probos/consultation/__init__.py:1-90   # 28 re-exports incl. WorkspaceRegistry, ConsultationWorkspace, DeliveryPipeline
src/probos/consultation/workspace.py:43-58 # WorkspaceLifecycleState IntEnum (7 states)
src/probos/consultation/workspace.py:55-63 # _ALLOWED_TRANSITIONS — APPROVED→EXECUTING, EXECUTING→COMPLETED, COMPLETED→{ARCHIVED, CONSULTING, EXECUTING}
src/probos/consultation/workspace.py:205-219 # ConsultationWorkspace.add_work_item(spec, *, agent_id) — writes wi_<id>.yaml + journal entry
src/probos/consultation/workspace.py:243-258 # transition_to(state, *, agent_id) — returns False on invalid; never raises
src/probos/consultation/workspace.py:262-275 # append_journal(message, *, agent_id) — log-and-degrade
src/probos/consultation/workspace.py:299-330 # WorkspaceRegistry.create() — materializes 6 subdirs incl. workitems/, plan/

# AD-496–498 WorkItemStore substrate (verified shipped):
src/probos/workforce.py:559-585     # WorkItem dataclass — depends_on, metadata, parent_id, tags, work_type, status, priority, assigned_to
src/probos/workforce.py:905         # class WorkItemStore(EventEmitterMixin)
src/probos/workforce.py:1004        # async def create_work_item(**kwargs) -> WorkItem
src/probos/workforce.py:1066-1106   # async def list_work_items(status, assigned_to, work_type, parent_id, priority, tags, limit, offset)
src/probos/workforce.py:1108        # async def update_work_item(work_item_id, **updates) -> WorkItem | None
src/probos/runtime.py:213           # ProbOSRuntime.work_item_store: WorkItemStore | None
src/probos/runtime.py:1595          # adoption: self.work_item_store = comm.work_item_store

# Event surface (verified collision-free):
src/probos/events.py:87  WORK_ITEM_CREATED         # reused (WorkItemStore emits)
src/probos/events.py:89  WORK_ITEM_STATUS_CHANGED  # reused (WorkItemStore emits)
src/probos/events.py:90  WORK_ITEM_ASSIGNED        # reused (WorkItemStore emits)
src/probos/events.py:302-305 CONSULTATION_*        # AD-594 main; orthogonal namespace (reqd/completed/timeout/failed)
# PARALLEL_DISPATCH_STARTED, PARALLEL_DISPATCH_PROGRESS, PARALLEL_DISPATCH_BLOCKED — 0 hits at HEAD; safe to add.

# Config insertion anchor:
src/probos/config.py: ConsultationWorkspaceConfig (~:1876) and ConsultationDeliveryConfig (Wave 79 added) live adjacent.
src/probos/config.py: SystemConfig.consultation_workspaces / consultation_delivery fields adjacent.
# AD-594c adds ConsultationDispatchConfig immediately after ConsultationDeliveryConfig.

# Wirer insertion anchor:
src/probos/startup/finalize.py: _wire_consultation_workspaces / _wire_consultation_delivery defined adjacent.
src/probos/startup/finalize.py: finalize_startup invokes consultation_workspaces then consultation_delivery.
# AD-594c adds _wire_consultation_dispatch immediately after _wire_consultation_delivery.

# AD-594b is NOT shipped at HEAD (verified):
grep -rn "def consult\b\|class ConsultationPrimitive" src/probos/  → 0 hits.
# AD-594c does NOT depend on AD-594b at the import or method-call level. Roadmap "depends: AD-594b"
# is sequencing prose; verify-first confirms zero hard coupling.

# Roadmap status line:
docs/development/roadmap.md:4841   # > - **AD-594c: Parallel Execution Dispatch** *(planned, OSS, ...)* — ...

# GH issue:
gh issue view 162   # State: open. Scope: plan→workitem, conflict detection, multi-executor,
                    # boundaries, progress, completion, blockers. No commercial extension listed
                    # (only Related: AD-581 Hybrid Dispatch).

# Test conventions:
tests/test_ad594a_consultation_workspace.py   # sibling test file (do not modify)
tests/test_ad594d_delivery_pipeline.py        # sibling test file (do not modify)
tests/test_workforce.py                       # WorkItemStore regression suite (must stay green)
```

Every concrete claim in this dispatch maps to a grep hit above.

## Captain workflow

1. **Append wave 80 entry to `prompts/wave-plan.yaml`** under id `"80"`, after id `"79"` (template at end of this dispatch).
2. **Builder runs `prompts/ad-594c-parallel-dispatch-v1.md`** end-to-end. One commit. Outputs:
   - **New:** `src/probos/consultation/dispatch.py`, `tests/test_ad594c_parallel_dispatch.py`
   - **Modified:** `src/probos/consultation/__init__.py`, `src/probos/events.py`, `src/probos/config.py`, `src/probos/startup/finalize.py`, `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, `prompts/wave-plan.yaml`
3. **Pre-commit gate (Builder responsibility):**
   - `pytest tests/ -q -n 4 --dist=loadfile` — collection ≥ 11553 (Δ ≥ +25), all green.
   - `pytest tests/test_ad594c_parallel_dispatch.py -v -n 0` — focused gate, ≥25 tests pass serially.
   - `pytest tests/test_ad594a_consultation_workspace.py tests/test_ad594d_delivery_pipeline.py tests/test_workforce.py -v -n 0` — sibling regression gate; all existing tests pass unchanged.
4. **Update `PROGRESS.md`** (top of "Recent Builder Closures" block) with one Wave 80 paragraph entry mirroring Wave 79 style.
5. **Update `docs/development/roadmap.md` line 4841**: `*(planned, OSS, depends: AD-594a, AD-594b, AD-496–498 WorkItemStore)*` → `*(complete — Wave 80, OSS; LLM-driven semantic decomposition deferred behind PlanDecomposer protocol seam pending consumer)*`. Preserve descriptive prose.
6. **Update `DECISIONS.md`** — append AD-594c v1 entry above AD-594d's entry (Problem / Decision / Consequences shape mirroring AD-594d's entry).
7. **Update `prompts/wave-plan.yaml`** id `"80"` entry with `status: done` after Builder gate passes.
8. **Commit:** `Wave 80: AD-594c v1 Parallel Execution Dispatch (full scope) (#162)`.
9. **Archive** `prompts/WAVE-80-DISPATCH.md` and `prompts/ad-594c-parallel-dispatch-v1.md` to `prompts/archive/` after the GH close.
10. **Close GH #162** with verify-first evidence + commit hash + scope-completed checklist (one row per scope bullet, all ✓).
11. **Update memory `/memories/session/wave-queue-batch2.md`** with `W80 #162 done (single: AD-594c v1 full-scope; +<actual> tests, baseline 11528)`.

## Hard-stop conditions

1. **Phantom API in implementation.** Every method/attribute/anchor asserted in `prompts/ad-594c-parallel-dispatch-v1.md` is verified at HEAD `3bcd608`. If the Builder finds a mismatch (e.g. `WorkItemStore.create_work_item` rejects a kwarg, `list_work_items` does not accept `tags=` filter, `_ALLOWED_TRANSITIONS` shape differs, `add_work_item` signature differs), → hard stop, surface to Architect.
2. **Architectural change required.** AD-594c is additive on top of AD-594a + AD-594d + AD-496. If the Builder concludes a `BaseAgent` / `IntentMessage` / `WorkItem` schema / `WorkspaceLifecycleState` enum change is required, → hard stop. Architect re-scopes; the dispatch's "no architectural changes" invariant is a hard line.
3. **Consensus gate missing.** AD-594c registers WorkItems on the existing `WorkItemStore` surface; it does NOT introduce destructive Intents. If the Builder adds a new Intent that mutates state, set `requires_consensus=True` in its `IntentDescriptor` (per copilot-instructions). Failure to do so → hard stop.
4. **HXI / router surface ships.** Any `routers/*.py` modification, any new `/api/consultation-dispatch/*` endpoint, any `ui/src/` modification → hard stop. AD-594c v1 is service-only.
5. **AD-594b consultation primitive smuggling.** Any new `consult(question, context)` method on `CognitiveAgent`, any `cognitive/consult.py` module, any LLM-driven advisor selection — that is AD-594b (#161), out of scope. → hard stop.
6. **AD-581 Hybrid Dispatch smuggling.** Any new `Dispatcher` / `DepartmentChiefDispatch` / `ASADispatcher` class, any HebbianRouter integration in dispatch.py — that is AD-581 (#113 Wave 81). → hard stop.
7. **AD-594d Delivery smuggling.** Any auto-trigger of `DeliveryPipeline.deliver()` from `check_completion()`, any `delivery_*.py` modification → hard stop. AD-594c writes to `outputs/` only via existing `workspace.add_output(...)` if at all; delivery is the consumer's call.
8. **LLM call in PlanDecomposer.** Any `llm_client.complete(...)` invocation inside `dispatch.py` → hard stop. v1 is structured-markdown only; LLM-driven decomposition deferred behind the Protocol seam.
9. **EventType naming collision.** Any `PARALLEL_DISPATCH_*` value that overlaps an existing event → hard stop (verify-first confirms greenfield; Builder should re-grep before adding).
10. **Subscriber side-effect on `WORK_ITEM_STATUS_CHANGED`.** AD-594c may subscribe (read-only) to `WORK_ITEM_*` events for journal updates; ANY mutation of WorkItem state from the subscriber → hard stop. Status mutation is the executor's job, not the dispatcher's.
11. **Working-tree drift.** Untracked changes outside the file set listed in step 2 → hard stop. Only the listed files may be modified.
12. **Sibling regression.** Any AD-594a / AD-594d / AD-496 test failure after the build → hard stop. AD-594c is purely additive.
13. **Test count drift.** Pytest full gate must report ≥ 11553 collected (Δ ≥ +25). Less → hard stop, surface to Architect; more → fine.
14. **Commercial leak.** Any pricing / revenue / customer-count / professional-services / GTM / competitive-positioning language in the prompt body, the module, the config docstring, the DECISIONS entry, the roadmap entry, the GH close comment, or any wave artifact → hard stop. GH #162 issue body lists ZERO commercial extensions; AD-594c is OSS-only by issue scope.

## Acceptance criteria

1. `git status` (post-Builder) shows exactly:
   - `?? src/probos/consultation/dispatch.py` (new)
   - `?? tests/test_ad594c_parallel_dispatch.py` (new)
   - `M src/probos/consultation/__init__.py`
   - `M src/probos/events.py`
   - `M src/probos/config.py`
   - `M src/probos/startup/finalize.py`
   - `M PROGRESS.md`
   - `M docs/development/roadmap.md`
   - `M DECISIONS.md`
   - `M prompts/wave-plan.yaml`
   No other files.
2. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` — ≥ **11553 collected**, all passed (Δ ≥ +25 vs baseline 11528).
3. **Focused gate** `pytest tests/test_ad594c_parallel_dispatch.py -v -n 0` — ≥25 tests, all pass.
4. **Sibling regression gate** `pytest tests/test_ad594a_consultation_workspace.py tests/test_ad594d_delivery_pipeline.py tests/test_workforce.py -v -n 0` — all existing tests pass unchanged.
5. PROGRESS.md Wave 80 entry summarizes the build in one paragraph, matching Wave 79 style.
6. roadmap.md line 4841 status flipped per Captain workflow step 5.
7. DECISIONS.md AD-594c v1 entry inserted above AD-594d's entry (Problem / Decision / Consequences shape).
8. wave-plan.yaml id `"80"` entry committed with `status: done` after gate passes.
9. GH #162 closed with verify-first evidence + commit hash + scope checklist (one row per issue-body bullet, all ✓).
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically: SOLID-S (decomposer parses, detector flags, dispatcher orchestrates, sub-services have single purpose); SOLID-D (constructor injection for `work_item_store`, `workspace_registry`, `clock`, `event_emitter`); Liskov (`PlanDecomposer` Protocol seam; future LLM-driven decomposer must honor the same return contract); three-tier exception handling (tier-2 log-and-degrade for `add_work_item`/`update_work_item`/journal/`transition_to` failures; tier-3 propagate for caller programming errors via `ValueError` on unknown `workspace_id`); full type annotations on the public surface; async hygiene (no fire-and-forget tasks; subscribers are sync callbacks bound to `EventEmitterMixin`); structured logging with `"AD-594c: <what> on workspace=<id>"` format; no commercial language; no emoji.

## Wave-plan entry to append

```yaml
  - id: "80"
    title: "AD-594c v1 Parallel Execution Dispatch (full-scope)"
    kind: single
    depends_on: ["79"]
    dispatch_prompt: "prompts/WAVE-80-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-594c-parallel-dispatch-v1.md"
    builder_required: true
    issues_to_close: [162]
    status: pending
    notes: |
      Closes GH #162 (AD-594c Parallel Execution Dispatch). Full v1 scope in one
      wave per Captain rule (don't defer unless no choice). Module shape:
      WorkItemSpec frozen dataclass + PlanDecomposer (structured-markdown,
      Protocol seam for future LLM-driven decomposers) + ConflictDetector
      (resource-overlap pairs) + ParallelDispatcher orchestrator
      (dispatch -> registers WorkItems via runtime.work_item_store, mirrors to
      workspace.add_work_item, transitions APPROVED -> EXECUTING; get_progress;
      check_completion -> EXECUTING -> COMPLETED; detect_blockers -> emits
      PARALLEL_DISPATCH_BLOCKED with per-spec dedup). 3 new EventTypes
      (PARALLEL_DISPATCH_STARTED / _PROGRESS / _BLOCKED). Pydantic
      ConsultationDispatchConfig + finalize wirer (gated on
      runtime.consultation_workspaces AND runtime.work_item_store). LLM-driven
      semantic decomposition deferred behind PlanDecomposer Protocol seam
      (mirrors AD-594a InputProcessor + AD-594d FormatTransformer precedent).
      AD-594b not a build dependency (verified zero coupling). Baseline 11528 ->
      target >= 11553 (+25 floor). No HXI surface. No new Intent. No router.
      OSS only.
```

---

**Architect note for the Builder:** the prompt body at `prompts/ad-594c-parallel-dispatch-v1.md` carries the SEARCH/REPLACE blocks, full module text, and test plan. This dispatch is the contract; the prompt is the implementation script.
