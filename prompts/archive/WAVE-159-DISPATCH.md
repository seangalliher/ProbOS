# WAVE 159 DISPATCH

**Wave id:** 159 (per `prompts/wave-plan.yaml:3459`).
**Title:** Telemetry pipeline extensions + audio attachments + DM sub-intent dispatch.
**Kind:** main.
**Depends on:** Wave 158 (done — AD-738a/b/c/e-1 + AD-738e-2 forward marker).
**Estimated wall-time:** ~10h.
**Estimated tests:** +31 pytest + 4 vitest = +35 net.
**Issues closing:** [#569](https://github.com/seangalliher/ProbOS/issues/569), [#570](https://github.com/seangalliher/ProbOS/issues/570), [#600](https://github.com/seangalliher/ProbOS/issues/600), [#566](https://github.com/seangalliher/ProbOS/issues/566), [#583](https://github.com/seangalliher/ProbOS/issues/583), [#653](https://github.com/seangalliher/ProbOS/issues/653).

---

## Slate (5 prompts, dependency-ordered)

| # | Prompt | Closes | AD | Wall-time | Tests | Risk |
|---|---|---|---|---|---|---|
| 1 | `prompts/ad-722c-telemetry-history.md` | #569 | AD-722c | ~2h | +6 py | LOW |
| 2 | `prompts/ad-722d-records-auto-write.md` | #570 | AD-722d | ~1.5h | +5 py | LOW |
| 3 | `prompts/ad-722b-3-snapshot-diff.md` | #600 | AD-722b-3 | ~2h | +6 py +1 ts | LOW-MED |
| 4 | `prompts/ad-720e-audio-attachments.md` | #566, #653 | AD-720e + AD-738e-2 (folded) | ~3h | +4 py +3 ts | LOW |
| 5 | `prompts/ad-725-dm-subintent-dispatch.md` | #583 | AD-725 | ~2h | +10 py | MED |

**Build groups (dependency DAG):**
- **Group A (must build first):** Prompt 1 (AD-722c history JSONL) — Prompt 2 (AD-722d) AND Prompt 3 (AD-722b-3) both reference the AD-722c publish-loop hook block. Prompt 1 lands → Prompts 2 + 3 can be built in either order.
- **Group B (any order, independent of A):** Prompt 4 (audio attachments), Prompt 5 (DM sub-intent dispatch).
- Recommended commit order: 1 → 2 → 3 → 4 → 5.

---

## Standing rules (applied to every prompt this wave)

1. **Test gate per commit:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` MUST be green AFTER each prompt's commit.
2. **UI gate (AD-738b / BF-279):** if `git diff --name-only HEAD~1..HEAD -- ui/src/` shows any touch, BOTH `cd ui ; npx vitest run` AND `cd ui ; npm run build` MUST pass. Prompts 3 and 4 trigger this rule.
3. **No new pip deps.** Verify `pyproject.toml` unchanged after each commit.
4. **No new npm deps.** Verify `ui/package.json` unchanged after each commit.
5. **AD-731 invariant:** audio bytes (Prompt 4) go through `AttachmentStore` as SHA-256 refs. NEVER inline base64 in `IntentMessage.params`. NEVER inline into prompts.
6. **No `asyncio.create_subprocess_*` in runtime paths** (BF-280 standing rule). None of the 5 prompts spawn subprocesses; flag any drift during Builder execution.
7. **Windows binary-on-stdout** (BF-282): none of the 5 prompts captures binary output; if Builder discovers a need, route through tempfile.
8. **No emoji in UI** (HXI principle #3). Inline SVG only. Prompts 3 + 4 touch UI; verify on review.
9. **`multi_replace_string_in_file` hazard (BF-274/278):** avoid adjacent SEARCH blocks with overlapping context. Prefer single `replace_string_in_file` calls when removing adjacent sections.
10. **Phase ordering (BF-259/260):** Prompt 2 (AD-722d) uses a two-phase finalize wiring because `records_store` lands in Phase 4 while the writer is constructed earlier. Verify the late-bind block lands in finalize per the prompt.

---

## Pre-flight (before drafting Builder)

```powershell
# Working tree clean (no tracked-file modifications).
git status --porcelain
# (expect empty output OR only untracked artifacts in known locations)

# Baseline test gate — must be green.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3

# UI baseline gates (run BOTH because Prompts 3 + 4 will touch ui/src/).
cd ui ; npx vitest run ; npm run build ; cd ..

# Phantom-API pre-check on all 5 prompts.
.\scripts\phantom-api-precheck.ps1 `
  prompts\ad-722c-telemetry-history.md `
  prompts\ad-722d-records-auto-write.md `
  prompts\ad-722b-3-snapshot-diff.md `
  prompts\ad-720e-audio-attachments.md `
  prompts\ad-725-dm-subintent-dispatch.md

# Highest AD audit.
Select-String -Path DECISIONS.md -Pattern "^### AD-7[3-9][0-9]" | Select-Object -Last 5
```

Hard-stop pre-flight conditions:
- Baseline `pytest` gate red → fix baseline before Wave 159 starts.
- `npm run build` red on HEAD → file BF and stop; Wave 159 cannot ship UI on a broken baseline.
- Phantom-API pre-check flags any concrete issue (not just informational notes) → revise prompt before Builder dispatch.

---

## Per-prompt workflow

For each prompt in order:

1. **Builder reads the prompt** from `prompts/<file>.md`.
2. **Builder applies Section 1..N** (verification steps inside each section MUST be performed before SEARCH/REPLACE).
3. **Builder runs the prompt's "Verification commands"** block.
4. **Builder runs the wave's full gate** (`pytest tests/ -q -n 4 --dist=loadfile`).
5. **If UI was touched:** Builder runs `cd ui ; npx vitest run ; npm run build`.
6. **Builder commits** with the prompt's specified commit message (including `Closes #N` trailer).
7. **Builder updates `PROGRESS.md`** (closure line + test count delta).
8. **Builder marks the GH issue closed** via `gh issue close <N>`.
9. **Architect re-runs the wave's full gate** before approving the next prompt.

---

## Hard-stop conditions (during build)

Each condition triggers an immediate stop + architect surface (per user-memory standing rule):

1. **Working tree shows tracked changes Builder didn't make.** If they're architect-authored doc artifacts under `prompts/`, `Reviews/`, `DECISIONS.md` — commit on architect's behalf and resume. Otherwise: surface to user.
2. **Parallel test failure under `-n 4`.** Re-run failing file at `-n 0`. Pass → environmental, document and continue. Fail → triage per standard sequence.
3. **`git stash` reveals Builder's source change broke a pre-existing passing test.** Triage which change; fix minimally.
4. **Phantom API in implementation** (not just test fixture) — stop. Prompt has a verification gap.
5. **Architectural change required** (modifying `BaseAgent` / `IntentMessage` Protocol / sensorium dispatch shape) — surface to user.
6. **New pip OR npm dep introduced.** Wave 159 commits to zero-new-deps; any drift is a stop-the-line.
7. **`multi_replace_string_in_file` deletes >50 lines beyond the visible SEARCH context** (BF-274 class). Run `git diff --numstat` after every `multi_replace_string_in_file` call and verify line-deletion count matches expected.
8. **`vitest run` green BUT `npm run build` red** (BF-279 class). Stop; UI bundle is the operator-facing artifact.

---

## Quality gates (per commit)

- ✅ Test gate (`pytest -n 4 --dist=loadfile`) green.
- ✅ If UI touched: `vitest run` AND `npm run build` green.
- ✅ `git diff --stat` matches prompt's "Files to Modify" table (no surprise files).
- ✅ Commit message includes `Closes #N` (or `Refs #N` per AD-738e-2 standing rule, but Wave 159 prompts all have direct issue closes).
- ✅ No new files in `pyproject.toml`, `ui/package.json`, `ui/package-lock.json`.
- ✅ No emoji introduced in UI files (Prompt 3, 4).

---

## Wave-specific reminders (known false positives during architect review)

- **AD-722c JSONL location.** `data/avatar_telemetry/` is created on first write; absence on pre-build trees is NOT a missing-directory gap. Builder must NOT pre-create the directory at startup.
- **AD-722d two-phase finalize.** Initial construction at runtime.py:~430 sets `avatar_telemetry_records_writer = None`. The actual `TelemetryRecordsWriter` is instantiated at runtime.py:~1528 AFTER `_records_store` is wired. Reviewer must NOT flag the first None-assignment as dead code.
- **AD-722b-3 frame `type` field.** Existing AD-722b tests that assert WS frame shape MUST be checked for `type` field expectation drift. The diff prompt's Section 3 sends `{"type": "snapshot", **snap_dict}`. If existing tests assert exact dict equality on the old shape, they'll fail. Update assertions to include `"type": "snapshot"` rather than reverting.
- **AD-720e magic-byte matcher semantics.** Builder MUST read `attachments/mime.py:40-70` before applying Section 2. Multi-option MP3 sync bytes need any-of semantics; if current matcher is all-required, extend the matcher (documented as Section 2a in the prompt).
- **AD-725 runtime method names.** Prompt's `_dispatch` method uses defensive `hasattr` guards. Builder MUST grep `runtime.oracle_service.lookup`, `runtime.episodic_memory.recall_for_agent`, `runtime.codebase_index.query`, `runtime.records_store.search` to confirm exact names. Wrong name → silent degradation, not crash, but the entire branch becomes a no-op.
- **AD-738e-2 numbering note.** DECISIONS.md AD-738e-1 (line 2466) reserves AD-738e-2 for a prosody forward marker. Issue #653 reuses the slot for the Refs-trailer rule. Prompt 4 renumbers the prosody marker to `AD-738e-2-prosody`. Reviewer must NOT flag this as a conflict — it's an intentional slot reuse per Captain instruction.

---

## Post-sweep procedures

After all 5 prompts ship:

1. **Full gate** `pytest tests/ -q -n 4 --dist=loadfile`.
2. **UI gate** `cd ui ; npx vitest run ; npm run build`.
3. **Close GH issues** #569, #570, #600, #566, #583, #653 (Builder closes each at its own commit; double-check none are stragglers).
4. **Update `docs/development/roadmap.md`** Bug Tracker — remove all 6 issue rows; add forward markers AD-722c-1/2, AD-722d-1/2, AD-722b-3a/b, AD-720e-1/2, AD-725-1/2/3/4.
5. **Append to `DECISIONS.md`**: AD-722c, AD-722d, AD-722b-3, AD-720e, AD-738e-2, AD-725 entries.
6. **Update `prompts/wave-orchestrator-state.json`** — `current_wave` advances, `current_stage` returns to `idle`.
7. **Set `wave-plan.yaml` entry 159** `status: shipped`.

---

## Build report

After the wave completes, write `prompts/build-reports/wave-159-build-report.md` with:
- Test count delta (start vs end of wave).
- Per-prompt wall-time actuals.
- Any hard-stops triggered + how resolved.
- Any phantom-API or architectural revisions made mid-build.
- Forward markers filed.
- Any BF entries opened (parallel-test environmental noise, etc.).

---

## Numbering — Hard Rule (audit)

**Current highest AD in DECISIONS.md:** AD-739 (Captain Card planning placeholder, line 2457).

Wave 159's AD numbering:
- AD-722c, AD-722d, AD-722b-3 — sub-AD slots of existing parent ADs (AD-722). NO new top-level number consumed.
- AD-720e — sub-AD slot of AD-720. NO new top-level number consumed.
- AD-725 — already reserved as forward marker in DECISIONS.md AD-722 addendum / AD-723 family.
- AD-738e-2 — slot REUSED from AD-738e-1's prosody forward marker (renumbered to `AD-738e-2-prosody`). Per Captain instruction; documented in Prompt 4.

**Wave 159 consumes ZERO new top-level AD numbers.** Next free top-level AD remains **AD-740**.
