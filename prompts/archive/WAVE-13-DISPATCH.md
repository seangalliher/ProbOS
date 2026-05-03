# Wave 13 — Combo C (7 trivial extensions)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 combo prompt drafted directly (`prompts/combo-C-trivial-extensions.md`).
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + 1 GH issue closure + 3 partial-completion comment updates.
**Estimated time:** ~3 hours total subagent compute.

---

## Wave 13 scope

| Combo | Children | Closes |
|---|---|---|
| Combo C | AD-526d, AD-572c, AD-572d, AD-573c, AD-573e, AD-573f, AD-575c (7) | #7 (AD-575); comment-update #101 #109 #8 |

Wave 8 Combo A precedent: 7 children in single commit, pre-check + AD-685 catches phantoms across all children, per-child verify-first per mini-section. ~26 tests target.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Special attention:

1. **Per-child verify-first** — each mini-section must have its own grep evidence. Wave 8 Combo A's 558-line shape (~70 per child) is the proven template; Combo C is similar.
2. **Inter-child file conflicts** — AD-572c/d/575c all touch proactive.py; AD-573c/e/f all touch working_memory.py. Sequential application required. Confirm dispatch documents the order.
3. **AD-572d hard-stop risk** — proactive loop interruptible-wait pattern may not exist. Architect should verify NOW (not at Builder time) and either confirm pattern exists OR mark AD-572d for wholesale-defer (per AD-575b precedent).
4. **Wave 9 retrospective + AD-685 conventions** — apply architect-discretion sweep especially on cognitive_journal.recent_for_agent (AD-573e) and ward_room.list_threads(channel_id=None) (AD-572c).
5. **Section 0 EventTypes** — 4 new types; grep events.py for collisions.

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 13 review pass 1: Combo C reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. If any single child hits a hard-stop, wholesale-defer it (Wave 8 AD-575b precedent) — don't block the wave. Document the drop. Single commit. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-13-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 13` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 13 specific reminders:

- Single commit `Combo C: AD-526d/572c/572d/573c/573e/573f/575c trivial extensions`.
- Inter-child file sequencing (proactive.py: 572c → 572d → 575c; working_memory.py: 573c → 573e → 573f).
- Section 0: 4 new EventTypes — verified collision-free at pass-2.
- Test target: ~26 tests; per-child files acceptable per Combo A precedent.
- If any child wholesale-dropped during revision, build remaining 6 (or fewer); update commit message + tracker counts accordingly.

Hard-stops standard + per-child hard-stops listed in combo prompt.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

**GATE 3 closes 1 issue + comments on 3:**

```pwsh
gh issue close 7 --comment "AD-575 closed in Combo C (Wave 13 commit XXXXX). AD-575b dropped wholesale in Wave 8 Combo A (theater per convention #7). AD-575c shipped here. Both surface children resolved." --reason completed

gh issue comment 101 --body "Partial: AD-526d (Game Preference Tracking) closed in Combo C (Wave 13 commit XXXXX). 526c done in Combo A. 526e/f/g/h remain (spectator, holodeck, creative, chess) — each substantial enough for standalone treatment."
gh issue comment 109 --body "Partial: AD-572c (Ward Room activity in DM) + AD-572d (Captain Priority Queue) closed in Combo C (Wave 13 commit XXXXX). 572b done in Combo A. 572e (task awareness in DM) remains."
gh issue comment 8 --body "Partial: AD-573c (scratchpad NOTE tag) + AD-573e (CognitiveJournal as WM source) + AD-573f (commitment tracker) closed in Combo C (Wave 13 commit XXXXX). 573b done in Combo A. 573d (dream-to-WM pipeline) remains — depends on runtime.dream_scheduler exposing summaries (same blocker as AD-477g)."
```

Retrospective: optional. Heuristic — write only if 2+ children wholesale-dropped during revision (would indicate scope-trimming pattern worth banking) OR if AD-685 caught a kwarg phantom inside the combo.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-13.md and README-wave-13-pass-2.md
- 1 source commit (Combo C; 7 children OR fewer if any wholesale-dropped)
- Full gate green; +20-30 tests
- 0 hard-stops at builder time (per-child hard-stops resolved in revision via wholesale-defer)
- GH #7 closed; #101 + #109 + #8 partial-completion comments updated
- DECISIONS.md combined entry for Combo C under Era V
- 7 roadmap.md status flags flipped (or fewer if any wholesale-dropped)
