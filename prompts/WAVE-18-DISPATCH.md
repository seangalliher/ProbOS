# Wave 18 — AD-572e Task Awareness in Captain DM Context

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + GH #109 comment update.
**Estimated time:** ~1.5 hours total subagent compute (small scope; single helper + 1 integration point).

---

## Wave 18 scope

| AD | Title | Risk |
|---|---|---|
| AD-572e | Task Awareness in Captain DM Context | low |

Final AD-572 child. Builds on Combo A (572b) + Combo C (572c). 1 capability (single async helper + proactive-loop integration). Mirrors Combo C's `wardroom_activity_summary` integration pattern.

**Closes/updates GH issues:** #109 partial-completion comment updated (572e shipped; 572d-i still deferred). Issue stays open if AD-572d-i is the last remaining child.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Wave 18 specific attention:

1. **Mirror-pattern conformance.** AD-572e mirrors Combo C's `wardroom_activity_summary()` integration. Verify the new helper signature, defensive error handling, and proactive-loop injection point match the proven precedent.
2. **WorkItemStore signature drift check.** `list_work_items(status, assigned_to, work_type, ...)` verified at workforce.py:1066 in Waves 10/12/16. Re-verify at Wave 18 (no signature changes expected post-Wave-12).
3. **WorkItem field names.** `id`, `title`, `work_type` — Wave 10 revealed `metadata` is the data dict; ensure these fields exist directly on WorkItem (not nested under metadata). Builder verify-first per AD-685b.
4. **AD-685 + AD-685b coverage.** Pre-check now catches kwarg-name + method-name phantoms. Architect-discretion sweep is light — focus on async/sync (helper is async; runtime callers must await) and field-name shapes.
5. **Public-attribute discipline.** No new public attributes (helper is method on existing `CaptainEngagementProvider`).

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 18 review pass 1: AD-572e reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended, judgment-call Nits. Append `## Revision (2026-05-03)`. Run extended pre-check.

Single commit: `Wave 18 revision: apply review findings to AD-572e`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-18-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 18` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 18 specific reminders:

- v1 ships 1 capability ONLY (task_awareness helper + proactive injection).
- Async helper; await at every call site.
- Real WorkItemStore method: `list_work_items` (NOT `add` or `get_pending` — phantoms from Wave 10).
- Real config attribute: `runtime.work_item_store` (verified Waves 10/12/16).
- Mirror Combo C `wardroom_activity_summary` integration pattern in proactive.py.
- No new EventTypes, no new public attributes.
- Test count target: ~12 tests.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

**GATE 3 closes/updates GH #109:**

```pwsh
gh issue comment 109 --body "Partial: AD-572e (task awareness in Captain DM context) closed in Wave 18 (commit XXXXX). 572b done in Combo A, 572c done in Combo C, 572e done here. AD-572d-i (Captain Priority Queue — interruptible-wait pattern) remains deferred until proactive loop introduces interruptible-wait support."
```

If AD-572d-i is the only remaining sub-AD, leave issue open. If you want to close issue #109 with note pointing to AD-572d-i: substitute close command with appropriate comment.

Retrospective: optional. Heuristic — write only if AD-685b catches a phantom in this wave.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-18.md and README-wave-18-pass-2.md
- 1 source commit (AD-572e)
- Full gate green; +12 tests
- 0 hard-stops
- GH issue #109 partial-completion comment updated
- DECISIONS.md entry for AD-572e under Era V
