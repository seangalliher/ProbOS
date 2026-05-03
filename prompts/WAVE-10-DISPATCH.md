# Wave 10 — Workforce Cleanup (Combo B)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 2 single-AD prompts drafted directly (no meta-wave needed).
**Outputs:** 2 review files + sweep summary + revisions + 2 source commits + 2 GH issue closures.
**Estimated time:** ~3 hours total subagent compute.

---

## Wave 10 scope

| AD | Title | Risk | Build order |
|---|---|---|---|
| AD-501 | TaskTracker Deprecation & NotificationQueue Separation | medium | 1st (cleanup; isolates `notifications.py`) |
| AD-500 | DutyScheduleTracker → WorkItem Migration | HIGH (breaking change to proactive loop) | 2nd (migration; relies on a stable runtime) |

These were discussed in earlier waves as "Combo B — Workforce Cleanup" but each is substantial enough to warrant its own commit. Building as a 2-prompt main wave (Wave 9A precedent: 3 prompts in one wave; this is 2).

**Closes GH issues:** #88 (AD-501), #87 (AD-500).

---

## Stage 1 — Architect: Review Pass 1

Dispatch to Architect subagent:

```
Wave 10 Review Pass 1 — verify-first review of 2 Workforce Cleanup prompts.

Read first:
1. prompts/review-criteria.md
2. DECISIONS.md "Wave 5/5-7/8/9 retrospective" entries — 23 standing conventions
3. The 2 prompts:
   - prompts/ad-501-tasktracker-deprecation.md
   - prompts/ad-500-dutyscheduler-workitem-migration.md
4. .claude/agents/architect.md

Output one review file per prompt at prompts/Reviews/<stem>-review.md plus a sweep summary at prompts/Reviews/README-wave-10.md.

Apply the 3-tier format. Audit against all 23 standing conventions (Wave 5 #1-7, Wave 5-7 Addendum #8-15, Wave 8 Addendum #16-19, Wave 9 Addendum #20-22).

Five high-priority verification points:

1. **AD-501 verify-first.** All claimed file paths and line numbers are grep-confirmed. Specifically:
   - `src/probos/task_tracker.py:149,177,260` (NotificationQueue, AgentNotification, TaskTracker classes)
   - `src/probos/runtime.py:69,234,543,1058,1526` (task_tracker references)
   - 32 tests in `tests/test_task_tracker.py` — verify count or update prompt with actual count

2. **AD-500 cross-AD dependency on AD-498.** AD-500 assumes AD-498's `duty` work type can be registered. Verify:
   - `class WorkTypeRegistry` exists at `workforce.py:248`
   - There's no existing `duty` work type registration (AD-500 introduces it)
   - State machine + transitions for `duty` are appropriate (no theater on this surface)

3. **AD-500 breaking change risk.** Proactive loop migration is HIGH-risk. Confirm:
   - The `DutyConfig.use_work_items` transitional flag is the right shape (Wave 5 convention #3)
   - The "no_dual_dispatch" guarantee (test #10) is structural, not a runtime check
   - Existing duty/proactive tests are accounted for in the Test Plan

4. **Wave 9 retrospective conventions applied:**
   - #20 cross-wave dep verifies SHIPPED code (AD-500 reads AD-496/498 surfaces from src/, not from prompts).
   - #21 structural-defect pattern (async/sync, kwargs, row shape, tree shape, missing field) — apply architect-discretion sweep, especially on AD-500's WorkItemStore poll path.
   - #22 v1 isolation — AD-500 ships 3 of 5; AD-501 ships 4 of 5; deferrals explicit.

5. **Section 0 EventTypes.** AD-500's `DUTY_WORK_ITEM_CREATED` does not collide with existing events. Grep events.py.

Wave 9 retrospective lesson: structural-defect pattern propagation is asymmetric (caught in review, not always in drafting). Apply architect-discretion sweep — flag any of these patterns even if not formally surfaced via verify-first footer:
- Async functions awaited at every call site
- Method kwargs match live signatures
- Row/dict access uses correct keys
- Tree-shaped responses walked, not iterated flat
- Resolver helpers used over direct field access

Tolerance per convention #15 (relaxed): 1 ⚠️ allowed on highest-risk prompt only (AD-500 expected; AD-501 should be ✅).

Hard-stops:
1. Phantom API not introduced by the prompt itself.
2. AD-500 cannot be implemented without AD-498 extension (e.g., `duty` work type requires new WorkTypeRegistry feature) — surface; may need AD-498 extension prompt first.
3. AD-501's NotificationQueue has hidden state on TaskTracker (e.g., shared `_lock` or registry) that prevents clean separation — surface for re-bundling.
4. Cross-prompt source-file conflicts (both prompts touch `runtime.py`) — surface, sequence the SEARCH/REPLACE blocks.

After all 2 reviews + sweep summary are written:
- Single commit: `Wave 10 review pass 1: 2 prompts reviewed, N findings (M Required)`
- Push to origin/main.

Begin with AD-501 (smaller, lower-risk) → AD-500 (higher-risk).

Return per-prompt verdicts, total Required/Recommended counts, top failure modes, commit hash, and whether the Wave 9B structural-defect pattern recurred in either draft.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision pattern. Apply Required, fold Recommended unless they expand scope, judgment-call Nits. Append `## Revision (2026-05-03)` section. Run phantom-API pre-check post-revision (expected 0 phantoms).

Single commit: `Wave 10 revision: apply review findings to AD-500 + AD-501`. Pre-commit deletion sanity check. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-10-pass-2.md`. Convergence target: 2 ✅ (tolerance reservation likely consumed by AD-500 pass-1).

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

Inspect `prompts/Reviews/README-wave-10-pass-2.md`. Approve via convention #15 verdict criteria.

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 10` (reject).

---

## Stage 5 — Builder: Continuous Build

Dispatch to Builder:

```
Build Wave 10 — Workforce Cleanup (AD-501 → AD-500), continuous-build mode.

Read first:
1. prompts/BUILDER-EXECUTION-PLAN.md
2. .github/copilot-instructions.md
3. DECISIONS.md (Wave 5/5-7/8/9 retrospective entries — 23 standing conventions)
4. prompts/Reviews/README-wave-10-pass-2.md
5. The 2 build prompts:
   - prompts/ad-501-tasktracker-deprecation.md (1st — cleanup; isolates notifications.py)
   - prompts/ad-500-dutyscheduler-workitem-migration.md (2nd — migration; HIGH-risk)

Pre-flight:
git pull
git status --short
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile

Expected baseline: ~10648 passed, 15 skipped (post-Wave-9C state).

Build order: AD-501 → AD-500.

1. **AD-501** — TaskTracker deprecation. Move NotificationQueue + AgentNotification to new src/probos/notifications.py; delete task_tracker.py; remove runtime.task_tracker. Triage 32 tests. Test count target: ~18-23.

2. **AD-500** — DutyScheduleTracker WorkItem migration. HIGH-risk; touches proactive.py + duty_schedule.py. Use `DutyConfig.use_work_items=True` transitional flag (Wave 5 convention #3). Test count target: ~12 new tests + existing regression. Watch for the Wave 9B structural-defect pattern especially on the WorkItemStore poll path.

Per-prompt: read prompt + review, verify-first, implement, focused gate at -n 0, update trackers, build report, commit `AD-NNN: <one-line>`.

Per-commit gate: full pytest passes, test count non-decreasing, deletion sanity check.

Wave 10 specific reminders:
- AD-501 deletes a file (task_tracker.py). Pre-commit deletion sanity check: a single file delete is normal; >200 line deletion across a single file is the trigger.
- AD-500's transitional flag (`use_work_items`) is the rollout escape hatch — keep behavior identical when False.
- Both prompts touch `runtime.py` — sequence SEARCH/REPLACE blocks carefully; AD-501 deletes lines 69/234/543/1058/1526; AD-500 doesn't touch those (it modifies proactive.py).
- AD-500's `DUTY_WORK_ITEM_CREATED` EventType — verify no collision before adding.

Hard-stops (per BUILDER-EXECUTION-PLAN):
1. Phantom API
2. Architectural change beyond scope
3. Persistent serial test failure on unchanged file
4. Existing test breaks unanticipated by "What This Does NOT Change"
5. >5 sweep-introduced quarantines
6. AD-500 finds AD-498 doesn't support `duty` work type registration (need state machine surgery) — STOP and surface
7. AD-501 finds NotificationQueue has hidden coupling to TaskTracker preventing clean split — STOP and surface

Inter-group full gate after both land: pytest tests/ -q -n 8 --dist=loadfile. Test delta target: ~+25-35 (AD-501 +18-23 net of triage; AD-500 +12).

Tracker updates per prompt:
- PROGRESS.md: prepend AD-NNN entry
- DECISIONS.md: add entry under Era V (verbatim from prompt's Tracking section)
- docs/development/roadmap.md: flip AD-NNN status flag

When all 2 commits land + full gate passes, report back with:
- Per-prompt commit hash, test count, lines +/-
- Cumulative test count delta vs baseline (10648 → ?)
- Hard-stops triggered (target: 0)
- Confirmation that AD-501 deleted task_tracker.py cleanly + notifications.py is live
- Confirmation that AD-500's `use_work_items=True` is default + opt-out path works
- Any flakes observed (re-run at -n 0 if needed)

Begin with AD-501.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3 closes 2 GH issues:**

```pwsh
gh issue close 88 --comment "AD-501 closed in Wave 10 — see DECISIONS.md (NotificationQueue moved to src/probos/notifications.py; TaskTracker deleted)" --reason completed
gh issue close 87 --comment "AD-500 closed in Wave 10 — see DECISIONS.md (DutyScheduleTracker migrated to WorkItem path; transitional use_work_items flag default True; templates and config migration deferred to AD-500b/c)" --reason completed
```

Retrospective: optional. Heuristic — write only if Wave 9B structural-defect pattern recurs (would suggest tooling extension is now urgent), or if the transitional-flag pattern reveals new convention.

---

## Acceptance Criteria

- 2 review files (pass-1 + pass-2 sections)
- README-wave-10.md and README-wave-10-pass-2.md
- 2 source commits (AD-501 → AD-500)
- Full gate green; +25-35 tests
- 0 hard-stops
- GH issues #87 + #88 closed
- DECISIONS.md entries for AD-500 and AD-501
- Optional: Wave 10 retrospective if patterns warrant
