# Wave 158 Dispatch — Hygiene + Polish Bundle

**Wave:** 158. **Status:** drafted (architect handoff pending Builder pickup).
**Issues to close on push:** [#648](https://github.com/seangalliher/ProbOS/issues/648), [#650](https://github.com/seangalliher/ProbOS/issues/650), [#651](https://github.com/seangalliher/ProbOS/issues/651), [#652](https://github.com/seangalliher/ProbOS/issues/652).
**Estimated wall-time:** ~7–10h. **Builder mode:** continuous-build (one AD = one commit).

---

## Wave Goal

Close every track-as-follow-up that accumulated across Waves 154–157 (4 GH issues), plus ship one small additive feature (per-emotion Piper prosody) that leverages the AD-738e knobs landed in BF-285. All five prompts are internal hygiene + polish — no new external deps, no architectural shifts, no operator-facing breakage, no Captain interaction required overnight. **License: all-internal Apache 2.0.**

---

## Five Prompts (dependency order — but parallel-safe within the wave)

Build in numeric order. Each prompt is one commit. **Prompt 2 (`ad-738a-orchestrator-test-affordance.md`) MUST land before Prompts 3 and 4** because it atomically renumbers the Wave-157 forward markers `AD-738a/b/c/d → AD-738f/g/h/i` in `docs/development/roadmap.md` and `DECISIONS.md`. Prompts 3 and 4 reuse the freed `AD-738b` / `AD-738c` slots.

| # | Prompt | AD | Closes | Touches UI? | Tests |
|---|---|---|---|---|---|
| 1 | `prompts/ad-737a-hygiene-divergence-detector.md` | AD-737a | #648 | no | +3 pytest |
| 2 | `prompts/ad-738a-orchestrator-test-affordance.md` | AD-738a | #650 | yes (voice.ts) | +2 Vitest |
| 3 | `prompts/ad-738b-ui-gate-npm-build.md` | AD-738b | #651 | no (process-only) | 0 |
| 4 | `prompts/ad-738c-viseme-mapping-polish.md` | AD-738c | #652 | yes (lipSyncTrack.ts) | +4 pytest + +1 Vitest |
| 5 | `prompts/ad-738e-1-per-emotion-prosody.md` | AD-738e-1 | none | yes (voice.ts, ProfileChatTab.tsx) | +6 pytest + +2 Vitest |

**Expected wave totals:** +13 pytest, +5 Vitest. **Expected commits:** 5.

### Cross-prompt collision notes

- **`ui/src/audio/voice.ts` is touched by Prompts 2 AND 5.** Prompt 2 edits the `_resetTtsStatusForTests` function body (line 143–147). Prompt 5 edits the `speakResponse` signature (line 167) and the POST body construction (line 207–209). The edits are at non-overlapping line ranges; build in numeric order to avoid conflicts. If Builder hits a merge conflict, the resolution is mechanical (both edits are additive).
- **`src/probos/avatars/divergence_detector.py` is touched only by Prompt 1.** Prompt 5 imports `_resolve_intent_name` from it but does NOT edit it.
- **`docs/development/roadmap.md` is touched only by Prompt 2** (Section 3a renumbers 4 forward markers). Other prompts' tracker sections explicitly note "no roadmap change."
- **`DECISIONS.md` is appended by every prompt.** Standard one-paragraph closure block per AD. No conflicts (appends only).

---

## Pre-flight Checklist

```pwsh
cd D:\ProbOS
git status --short                                                       # must be empty
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile        # full gate baseline (record count)
cd ui
npx vitest run                                                            # Vitest baseline (record count)
npm run build                                                             # ** BF-279 baseline ** — bundle must compile clean before any UI edit
cd ..
```

Baseline numbers to record (Builder writes them in the build report):

- pytest count: ______ (expected delta after Wave 158: +13)
- Vitest count: ______ (expected delta after Wave 158: +5)
- `ui/dist/index-*.js` size + timestamp: ______

**No operator action required.** No external deps. No new pip / npm installs. No model downloads.

---

## Per-Commit Gate

Every commit MUST pass:

1. **Focused pytest gate** for the prompt's new test file:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_<adNNN>_*.py -v -n 0
   ```
2. **Regression pytest gate** for adjacent ADs (each prompt lists its regression files):
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/<adjacent_files> -q -n 0
   ```
3. **Full pytest gate** before push:
   ```pwsh
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile
   ```
4. **UI gate (BF-279 lesson)** — if the commit touches `ui/src/**`:
   ```pwsh
   cd ui
   npx vitest run                # logic correctness
   npm run build                 # TypeScript strict + production bundle health
   cd ..
   ```
   Applies to Prompts 2, 4, 5. **Both steps MUST pass** before the commit lands. Per the AD-738b standing rule landing in this wave, this is now a permanent requirement codified in `BUILDER-EXECUTION-PLAN.md`.
5. **Pre-commit deletion sanity check** — `git diff --stat HEAD~1..HEAD | sort -k3nr | head -5` — flag any deletion > 200 lines that wasn't authored by the prompt. (Standing rule from BUILDER-EXECUTION-PLAN.)

Commit message format: `AD-NNN: <one-line summary>` matching the prompt title.

---

## Hard-Stop Conditions

Surface to the architect (do NOT continue) if any of:

1. **A regression test fails under `-n 0` on a file the prompt did not touch** — this is real baseline rot, not environmental flake. Triage per the BUILDER-EXECUTION-PLAN standing rules; quarantine with a BF entry only if pre-existing and unrelated.
2. **`npm run build` errors after Prompt 2, 4, or 5** — bundle compile failure is a hard stop. This is exactly the failure mode BF-279 codified; the gate exists to catch it.
3. **The architect-renumbering in Prompt 2 cannot land cleanly** (e.g., `roadmap.md` lines 361–364 have already drifted from the prompt's verified state). Stop; re-grep the live file; surface the diff for architect review.
4. **A `multi_replace_string_in_file` call appears to drop more lines than its diff suggests** — per the BF-274 / BF-278 standing rule, abort the edit, restore from `git`, and reapply with single-replacement calls.
5. **Any commit message begins with anything other than `AD-NNN:`** — process drift; abort.
6. **`Stop-Process` / `taskkill` is about to fire against any `python.exe` without first reading `data/probos.pid`** — per the 2026-05-12 standing rule, abort. Use `scripts/kill-stale-pytest.ps1` instead.
7. **More than 3 quarantines accumulate** during the wave — stop, surface.

---

## Post-Wave Procedure (Builder hands back to Architect)

1. Build report at `prompts/build-reports/wave-158-report.md` with: commit SHAs, test deltas, any quarantines, smoke-test transcripts from Prompts 4 & 5 (the only ones with operator-visible effects).
2. `./scripts/wave-orchestrator.ps1 advance` → moves wave to `verify_build`.
3. Architect runs GATE 2 (the new commit-count audit from Prompt 2 will fire on this wave's own commits — expected to print "matches: 5").
4. Architect approves push.
5. GitHub issues #648, #650, #651, #652 auto-close via the orchestrator's `close` stage.
6. Retrospective entry in `progress-era-5-unification.md` if any new pattern emerged (esp. the slot-reuse process — first time we've atomically renumbered forward markers in a hygiene wave).

---

## Verified Against Codebase (2026-05-13)

```
gh issue view 648 --json state | jq .state    # OPEN
gh issue view 650 --json state | jq .state    # OPEN
gh issue view 651 --json state | jq .state    # OPEN
gh issue view 652 --json state | jq .state    # OPEN

# Wave-plan entry exists:
grep -n '  - id: "158"' prompts/wave-plan.yaml
  3439:   - id: "158"

# Top of DECISIONS.md current highest AD:
grep -E "^### AD-7[3-9][0-9]" decisions-era-*.md DECISIONS.md | tail -5
  ### AD-738 — Server-streamed TTS via Piper (Wave 157)
  ### AD-738e — exposed piper prosody controls (BF-285, 2026-05-13)
  ### AD-739 — Captain Card: operator self-card, always-in-context (planning)

# AD-numbering hard rule (per copilot-instructions): current highest top-level AD is AD-739
# (planning placeholder). Wave 158 uses AD-737a, AD-738a, AD-738b, AD-738c, AD-738e-1 —
# all sub-ADs of existing parents. No new top-level AD number consumed.
```
