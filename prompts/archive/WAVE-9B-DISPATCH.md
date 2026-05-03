# Wave 9B — AD-641 Cross-Cutting Children Review & Build

**Date:** 2026-05-02
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 2 sub-AD prompts already drafted in Wave 8.5 (`prompts/ad-641{c,e}-*.md`).
**Outputs:** 2 review files + sweep summary + revisions + 2 source commits.
**Estimated time:** ~2-3 hours total subagent compute.

---

## Wave 9B scope

| Sub-AD | Title | Risk |
|---|---|---|
| AD-641c | Ward Room Thread Priority | medium-high (cross-cutting) |
| AD-641e | Learned Shortcut Abstraction | medium-high (cross-cutting) |

**Cross-cutting** because each touches multiple existing modules (proactive routing, working memory, attention, etc.). Pass-2 review of Wave 9A confirmed neither prompt depends on the now-deferred `WardRoomEndorsementListener` (commit 7528631 verification).

---

## Stage 1 — Architect: Review Pass 1

Dispatch to Architect subagent:

```
Wave 9B Review Pass 1 — verify-first review of 2 sub-AD prompts.

Read first:
1. prompts/review-criteria.md
2. DECISIONS.md "Wave 5 Retrospective" + "Wave 5-7 Retrospective Addendum" + "Wave 8 Retrospective Addendum" — 19 standing conventions
3. prompts/WAVE-8.5-SPLIT-SUMMARY.md
4. prompts/Reviews/README-wave-9A-pass-2.md (Wave 9A converged 3✅; lessons may apply)
5. The 2 sub-AD prompts:
   - prompts/ad-641c-ward-room-thread-priority.md
   - prompts/ad-641e-learned-shortcut-abstraction.md
6. .claude/agents/architect.md

Output one review file per prompt at prompts/Reviews/<stem>-review.md plus a sweep summary at prompts/Reviews/README-wave-9B.md.

Five high-priority verification points:

1. **No hidden dependency on the deferred WardRoomEndorsementListener.** Wave 9A pass-2 confirmed neither prompt grep-matches `listener|EndorsementListener|handle_event|ward_room_endorsement_listener`. Re-confirm during review and document.

2. **Cross-cutting touch surface.** Both prompts touch multiple modules. For each prompt, list the source files modified and confirm:
   - No conflicts with Wave 9A's commits (4476091, a56b6c6, f8e12ea).
   - No conflicts between 641c and 641e themselves.
   - Each modification is grep-confirmed against live source.

3. **Standard verify-first per prompt.** Verified Against Codebase footer must have grep evidence for every concrete API/file/line/method claim.

4. **Section 0 EventTypes do not collide** with events.py or with each other or with Wave 9A's 5 new types (OBSERVABILITY_SNAPSHOT_PUBLISHED, OBSERVABILITY_BRIDGE_FAILED, WARD_ROOM_HEBBIAN_UPDATED, WARD_ROOM_HEBBIAN_DECAYED, ENGINEERING_SENSOR_REPORT).

5. **Aggressive pre-deferral applied (convention #14).** Each prompt should ship 2-4 v1 capabilities with explicit grandchildren. If a prompt absorbs >5 capabilities into v1, flag.

Wave 9A's revision pass caught 3 structural defects beyond the review (async/sync mismatch, wrong param names, wrong row shape). Apply the same architect-discretion verify-first repair posture during pass-1 review for 9B — if you spot a structural defect not flagged in any tier, document it explicitly.

Tolerance per convention #15 (relaxed): 1 ⚠️ allowed on the highest-risk prompt only.

Hard-stops:
1. Phantom API not introduced by the prompt itself.
2. Cross-prompt source-file conflicts the dispatch didn't identify.
3. Section 0 EventType collisions across Wave 9B prompts or with events.py.
4. Hidden listener dependency (would invalidate Wave 9A's defer decision).

After all 2 reviews + sweep summary are written:
- Single commit: `Wave 9B review pass 1: 2 prompts reviewed, N findings (M Required)`
- Push.

Begin with AD-641e (smaller blast radius — purely cognitive layer) → AD-641c (touches more surfaces).

Return per-prompt verdicts, total findings, top failure modes, commit hash.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Dispatch to Architect:

```
Wave 9B Revision Pass — apply review findings to 2 prompts.

Read pass-1 reviews + sweep summary. Apply Required findings, fold in Recommended unless they expand scope, judgment-call Nits.

Each revised prompt gets `## Revision (2026-05-02)` section appended.

Closing self-check (per Wave 8 convention): grep each prompt for OLD names/values changed; expect zero hits.

Phantom-API pre-check (mandatory):
./scripts/phantom-api-precheck.ps1 prompts/ad-641c-ward-room-thread-priority.md prompts/ad-641e-learned-shortcut-abstraction.md

Expected: 0 phantoms (no cross-prompt deps in 9B per pass-2 review of 9A).

Single commit: `Wave 9B revision: apply review findings to AD-641{c,e}`. Pre-commit deletion sanity check. Push.

Hard-stops: Required cannot be addressed without scope expansion; phantom-API pre-check finds >1 phantom; cascading regression on Wave 9A artifacts.

Return per-prompt revision deltas, pre-check output, commit hash.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Same shape as Wave 9A pass-2. Append `## Second-Pass Review (2026-05-02)` to existing review files. Sweep at `prompts/Reviews/README-wave-9B-pass-2.md`.

Convergence target: 2 ✅ (tolerance reservation likely unused given 9A precedent).

Hard-stops: 2+ prompts fail with new Required; cascading regression vs Wave 9A.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

Inspect `prompts/Reviews/README-wave-9B-pass-2.md`. Approve via convention #15 verdict criteria.

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 9B` (reject).

---

## Stage 5 — Builder: Continuous Build

Dispatch to Builder:

```
Build Wave 9B — 2 prompts (AD-641c/e), continuous-build mode.

Read first:
1. prompts/BUILDER-EXECUTION-PLAN.md
2. .github/copilot-instructions.md
3. DECISIONS.md (Wave 5/5-7/8 retrospective entries — 19 standing conventions)
4. prompts/Reviews/README-wave-9B-pass-2.md
5. The 2 build prompts:
   - prompts/ad-641c-ward-room-thread-priority.md
   - prompts/ad-641e-learned-shortcut-abstraction.md

Pre-flight:
git pull
git status --short
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile

Expected baseline: ~10603 passed, 15 skipped (post-Wave-9A state).

Build order: AD-641e → AD-641c (smallest blast radius first; both are cross-cutting but 641e is purely cognitive layer, 641c touches more surfaces).

Per-prompt: read prompt + review, verify-first, implement, focused gate at -n 0, update trackers, build report, commit `AD-641X: <one-line>`.

Per-commit gate: full pytest passes, test count non-decreasing, deletion sanity check.

Wave 9B specific reminders:
- Wave 9A convention reapplied: any per-instance mutable state in __init__, public attrs (no underscore), stdlib-only persistence, ASCII comments.
- WardRoomEndorsementListener is DEFERRED (AD-641b-iv). Do not implement.
- Each prompt's Section 0 EventTypes are distinct from Wave 9A's 5 types.

Hard-stops (per BUILDER-EXECUTION-PLAN):
1. Phantom API
2. Architectural change required beyond scope
3. Persistent serial test failure on unchanged file
4. Existing test breaks unanticipated by "What This Does NOT Change"
5. >5 sweep-introduced quarantines

Inter-group full gate: pytest tests/ -q -n 8 --dist=loadfile. Test delta target: ~+20-30 (2 prompts × 10-15 tests).

Tracker updates: PROGRESS.md, DECISIONS.md (Era V), roadmap.md.

Return per-prompt commit hash, test count, lines +/-, cumulative delta, hard-stops triggered (target: 0).

Begin with AD-641e.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → gates → push → close → retrospective → done

Same as Wave 9A:

- verify_build: full gate (Builder ran per-prompt; orchestrator's verify is optional)
- GATE 2: inspect commits before push
- push
- GATE 3: approve issue closure (none for 9B; AD-641 umbrella waits for 9C)
- close: no-op
- retrospective: optional (skip unless new pattern emerges)

---

## Acceptance Criteria

- 2 review files (pass-1 + pass-2 sections each)
- README-wave-9B.md and README-wave-9B-pass-2.md
- 2 source commits (AD-641e → AD-641c)
- Full gate green; +20-30 tests
- 0 hard-stops
- Wave 9B confirmed compatible with Wave 9A artifacts
- AD-641 umbrella issue (#277) NOT closed (waits for 9C)
