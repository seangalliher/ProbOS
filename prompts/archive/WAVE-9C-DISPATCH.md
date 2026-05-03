# Wave 9C — AD-641d Crew Deliberation Protocol + Umbrella Closure

**Date:** 2026-05-02
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 sub-AD prompt drafted in Wave 8.5 (`prompts/ad-641d-crew-deliberation-protocol.md`).
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + AD-641 umbrella closure (GH issue #277).
**Estimated time:** ~2 hours total subagent compute (single-prompt wave).

---

## Wave 9C scope

| Sub-AD | Title | Risk |
|---|---|---|
| AD-641d | Crew Deliberation Protocol | **HIGH** (Captain↔Computer arbitration; cross-cutting; closes umbrella) |

This is the highest-risk sub-AD in the AD-641 umbrella. It depends on AD-641a (observability, Wave 9A), AD-641b (Hebbian, Wave 9A), and AD-641c (thread priority, Wave 9B). AD-641e (Wave 9B) is independent of 641d.

When this lands, **AD-641 umbrella issue #277 closes.**

---

## Stage 1 — Architect: Review Pass 1

Dispatch to Architect subagent:

```
Wave 9C Review Pass 1 — verify-first review of AD-641d (HIGH-risk single-prompt wave).

Read first:
1. prompts/review-criteria.md
2. DECISIONS.md "Wave 5/5-7/8 retrospective" entries — 19 standing conventions
3. prompts/WAVE-8.5-SPLIT-SUMMARY.md
4. prompts/Reviews/README-wave-9A-pass-2.md (3✅ convergence)
5. prompts/Reviews/README-wave-9B-pass-2.md (2✅ convergence; structural defect pattern recurred and was caught)
6. prompts/ad-641d-crew-deliberation-protocol.md
7. .claude/agents/architect.md

Output one review file at prompts/Reviews/ad-641d-crew-deliberation-protocol-review.md plus a sweep summary at prompts/Reviews/README-wave-9C.md.

Apply the 3-tier format. Audit against all 19 standing conventions. Tolerance per convention #15 (relaxed): given this is the highest-risk sub-AD (cross-cutting, depends on 9A+9B artifacts), 1 ⚠️ is allowed.

Six high-priority verification points:

1. **Cross-wave dependency verification.** AD-641d reads:
   - Wave 9A AD-641a artifact: `runtime.observability_bridge` (commit 4476091)
   - Wave 9A AD-641b artifact: `runtime.ward_room_hebbian_router` or equivalent (commit a56b6c6)
   - Wave 9B AD-641c artifact: thread priority service (commit c9860c5)

   For each: confirm the prompt's claimed API call against the live shipped code (NOT against the prompt that introduced it — verify the actual built code in src/).

2. **Wave 9B structural-defect pattern.** AD-641c originally reproduced 3+2 structural defects (async/sync, wrong kwargs, wrong row shape, tree-shape assumption, missing field). Apply the SAME architect-discretion sweep to AD-641d — if any of these patterns recur (or new ones), document them in the review as Required findings even if not formally surfaced via the verify-first footer.

   Specifically check:
   - Async functions awaited at every call site
   - Method kwargs match live signatures
   - Row/dict access uses correct keys (`data` vs `payload`, etc.)
   - Tree-shaped responses are walked, not iterated flat
   - Resolver helpers used over direct field access

3. **Standard verify-first.** Verified Against Codebase footer must have grep evidence for every concrete API/file/line/method claim.

4. **Section 0 EventTypes do not collide** with events.py or with Wave 9A's 5 types or Wave 9B's 3 types (OBSERVABILITY_SNAPSHOT_PUBLISHED, OBSERVABILITY_BRIDGE_FAILED, WARD_ROOM_HEBBIAN_UPDATED, WARD_ROOM_HEBBIAN_DECAYED, ENGINEERING_SENSOR_REPORT, plus 9B's new types — grep events.py for current state).

5. **Aggressive pre-deferral.** AD-641d is HIGH-risk; v1 should ship 2-3 capabilities with 4-5+ deferred grandchildren. If the prompt absorbs more than ~3 capabilities into v1, flag as a no-theater risk.

6. **Captain protocol DECISIONS.md entry.** Per the original Wave 8.5 dispatch, AD-641d as the high-risk Captain protocol child requires an explicit DECISIONS.md entry documenting the arbitration semantics. Confirm the prompt's Tracking section includes a DECISIONS.md draft.

Hard-stops:

1. Phantom API not introduced by the prompt itself (HIGH stakes given cross-wave deps).
2. The cross-wave dependency claims do not match the actually-shipped Wave 9A/9B code (e.g., the prompt asserts a method that the implementation didn't end up exposing).
3. Section 0 EventType collisions with Wave 9A, 9B, or events.py.
4. AD-641d v1 absorbs >4 capabilities (no-theater risk on a HIGH-risk sub-AD).
5. The arbitration semantics in the prompt would conflict with existing Captain command paths in src/probos/ (e.g., proactive cognitive loop already has captain DM handling — surface for architectural review).

After review + sweep summary:
- Single commit: `Wave 9C review pass 1: AD-641d reviewed, N findings (M Required)`
- Push to origin/main.

Return per-prompt verdict, total Required/Recommended counts, top failure modes, commit hash. Pay special attention to whether the Wave 9B retrospective lesson on structural defects propagated into the AD-641d draft.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision pattern. Apply Required, fold Recommended, judgment-call Nits. Append `## Revision (2026-05-02)` section. Run phantom-API pre-check post-revision (expected 0 phantoms).

Single commit: `Wave 9C revision: apply review findings to AD-641d`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-02)`. Sweep at `prompts/Reviews/README-wave-9C-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

Inspect sweep summary. Approve via convention #15 verdict criteria.

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 9C` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Dispatch to Builder:

```
Build Wave 9C — AD-641d Crew Deliberation Protocol (single-prompt wave).

Read first:
1. prompts/BUILDER-EXECUTION-PLAN.md
2. .github/copilot-instructions.md
3. DECISIONS.md (Wave 5/5-7/8 retrospective entries — 19 standing conventions)
4. prompts/Reviews/README-wave-9C-pass-2.md
5. prompts/ad-641d-crew-deliberation-protocol.md

Pre-flight:
git pull
git status --short
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile

Expected baseline: ~10633 passed, 15 skipped (post-Wave-9B state).

Single commit: AD-641d builds in one commit. Verify cross-wave dependencies against live shipped code:
- Wave 9A AD-641a: runtime.observability_bridge (commit 4476091)
- Wave 9A AD-641b: ward_room_hebbian_router (commit a56b6c6)
- Wave 9B AD-641c: thread priority service (commit c9860c5)

If any cross-wave dep doesn't match the prompt's claim, STOP and surface — review/revision pass should have caught this; if it didn't, that's a Wave 9C hard-stop.

Per-prompt: verify-first, implement section by section per 19 conventions, focused gate at -n 0, update trackers, build report, commit `AD-641d: <one-line>`.

Per-commit gate: full pytest passes, test count non-decreasing, deletion sanity.

Wave 9C specific reminders:
- HIGH-risk; expect ~12-18 tests added.
- Captain protocol arbitration semantics are LIVE — no theater. v1 ships 2-3 capabilities; rest deferred.
- WardRoomEndorsementListener still DEFERRED (AD-641b-iv); 641d does NOT depend on it.
- DECISIONS.md entry required (per Captain-protocol dispatch convention).

Hard-stops (per BUILDER-EXECUTION-PLAN):
1. Phantom API
2. Architectural change beyond scope (high stakes for HIGH-risk; surface immediately)
3. Persistent serial test failure on unchanged file
4. Existing test breaks unanticipated by "What This Does NOT Change"
5. >5 sweep-introduced quarantines
6. Cross-wave dep mismatch (prompt says X, live shipped code says Y)

Inter-group full gate after commit lands: pytest tests/ -q -n 8 --dist=loadfile. Test delta target: ~+12-18.

Tracker updates:
- PROGRESS.md: prepend AD-641d entry
- DECISIONS.md: full entry under Era V (Captain protocol arbitration semantics)
- docs/development/roadmap.md: flip 641d status flag if present; flip AD-641 umbrella status to **Closed** (this wave closes the umbrella).

Return commit hash, test count, lines +/-, full gate status, hard-stops triggered, confirmation that AD-641 umbrella is now fully shipped.

Begin.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

**GATE 3 difference vs prior waves:** Wave 9C closes GH issue **#277 (AD-641 umbrella)**. The orchestrator's `close` stage will run:

```
gh issue close 277 --comment 'AD-641 umbrella closed — all 5 children shipped: 641a/b/c/e (Wave 9A/9B) + 641d (Wave 9C). 641b-iv (endorsement listener) wholesale-deferred per Wave 8 AD-575b precedent.' --reason completed
```

Update `prompts/wave-plan.yaml` 9C entry's `issues_to_close: [277]` is already set. The orchestrator's CloseAction will surface the closure command at the close stage.

Retrospective: **likely worth writing** — Wave 9 (8.5+9A+9B+9C) is the first multi-sub-wave on a Northstar umbrella; lessons on cross-wave dependency handling, the structural-defect pattern propagation question, and the orchestrator's 3-gate pipeline efficacy should be banked.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-9C.md and README-wave-9C-pass-2.md
- 1 source commit (AD-641d)
- Full gate green; +12-18 tests
- 0 hard-stops
- AD-641 umbrella issue #277 closed
- DECISIONS.md entry for AD-641d (Captain protocol arbitration)
- Optional: Wave 9 retrospective addendum to DECISIONS.md
