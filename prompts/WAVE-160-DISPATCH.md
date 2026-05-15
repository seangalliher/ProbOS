# WAVE 160 DISPATCH

**Wave id:** 160 (per `prompts/wave-plan.yaml`).
**Title:** DM-path refactor + divergence auto-correction + fleet telemetry stream + multi-image policy + sensorium metadata.
**Kind:** main.
**Depends on:** Wave 159 (done — AD-722c/d, AD-722b-3, AD-720e + AD-738e-2, AD-725 closures).
**Estimated wall-time:** ~10h.
**Estimated tests:** +42 pytest + 2 vitest = +44 net.
**Issues closing:** [#584](https://github.com/seangalliher/ProbOS/issues/584) (partial — pre-LLM extractions deferred to AD-726a/b/c), [#613](https://github.com/seangalliher/ProbOS/issues/613), [#601](https://github.com/seangalliher/ProbOS/issues/601), [#632](https://github.com/seangalliher/ProbOS/issues/632), [#626](https://github.com/seangalliher/ProbOS/issues/626), [#654](https://github.com/seangalliher/ProbOS/issues/654) (folded into AD-726).

---

## Slate (5 prompts, dependency-ordered)

| # | Prompt | Closes | AD | Wall-time | Tests | Risk |
|---|---|---|---|---|---|---|
| 1 | `prompts/ad-726-dm-path-refactor.md` | #584 partial, #654 | AD-726 (+ AD-722c-3 fold) | ~3h | +12 py | MED |
| 2 | `prompts/ad-722a-4-divergence-auto-correction.md` | #613 | AD-722a-4 | ~2.5h | +8 py | MED |
| 3 | `prompts/ad-722b-4-multi-agent-telemetry-stream.md` | #601 | AD-722b-4 | ~2h | +6 py +2 ts | LOW-MED |
| 4 | `prompts/ad-730-2-multi-image-dm-policy.md` | #632 | AD-730-2 | ~1.5h | +9 py | LOW |
| 5 | `prompts/ad-723a-3-sensorium-entry-metadata.md` | #626 | AD-723a-3 | ~1.5h | +7 py | LOW |

**Build groups (dependency DAG):**

- **Group A (must build first):** Prompt 1 (AD-726). The DM reply pipeline `step_7_mark_emitted` is the cleanest place for Prompt 2's per-utterance correction-slot clear. Land AD-726 first; Prompt 2 references the pipeline.
- **Group B (any order, after A):** Prompt 2 (AD-722a-4), Prompt 3 (AD-722b-4), Prompt 4 (AD-730-2), Prompt 5 (AD-723a-3). All four touch independent surfaces.
- **Recommended commit order:** 1 → 5 → 2 → 4 → 3.
  - 5 before 2: AD-723a-3 is pure additive metadata; lowest risk; clears the easy win.
  - 2 before 4: AD-722a-4 touches `apply_voice_modulation` kwargs (minor signature extension); AD-730-2 is independent. Either order works; the chosen order matches risk gradient (MED before LOW vision-policy LOW).
  - 3 last because it's the only UI-touching prompt (Vitest + `npm run build` gate adds ~3 min per cycle).

---

## Standing rules (applied to every prompt this wave)

1. **Test gate per commit:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` MUST be green AFTER each prompt's commit.
2. **UI gate (AD-738b / BF-279):** if `git diff --name-only HEAD~1..HEAD -- ui/src/` shows any touch, BOTH `cd ui ; npx vitest run` AND `cd ui ; npm run build` MUST pass. Prompt 3 triggers this rule (the ONLY UI-touching prompt this wave).
3. **No new pip deps.** Verify `pyproject.toml` unchanged after each commit. Prompt 4 uses Pillow — already in venv (`PIL 12.2.0`).
4. **No new npm deps.** Verify `ui/package.json` unchanged after each commit.
5. **AD-731 invariant:** Prompt 4's downscale produces NEW content-addressable refs; the ORIGINAL refs are preserved. NEVER inline base64 in `IntentMessage.params`.
6. **No `asyncio.create_subprocess_*` in runtime paths** (BF-280). None of the 5 prompts spawn subprocesses; flag any drift during Builder execution.
7. **Windows binary-on-stdout** (BF-282): none of the 5 prompts captures binary output (Prompt 4's PIL operations are in-memory BytesIO, NOT subprocess). If the Builder discovers a need, route through tempfile.
8. **No emoji in UI** (HXI principle #3). Prompt 3 touches `ui/src/avatars/useFleetAvatarTelemetry.ts` (pure logic, no JSX, no emoji possible — verify on review nonetheless).
9. **`multi_replace_string_in_file` hazard (BF-274/278):** AVOID adjacent-block multi-replace. Prompt 1 explicitly forbids `multi_replace_string_in_file` on the `routers/agents.py:1278..1559` span — single `replace_string_in_file` only. Prompts 2 and 4 also touch `agent_chat` post-AD-726; same rule applies.
10. **AD-722c-3 (folded into Prompt 1):** forward markers use TECHNICAL triggers, NOT commercial-tier language. Reviewer checks every forward-marker block in this wave against the rule that lands in `BUILDER-EXECUTION-PLAN.md` Standing Rule #11.
11. **Verbatim moves (Prompt 1):** the 8 post-LLM cleanup steps extracted from `routers/agents.py` into `DmReplyPipeline.step_N_*` MUST be verbatim moves — same comments, log strings, exception tiers, AD references. Only the variable-name rebinding (`response_text` → `self.ctx.response_text`, etc.) changes. Snapshot-suite verification is deferred to AD-726c forward marker; v1 relies on the 9 existing regression test files staying green UNCHANGED.

---

## Pre-flight (before Builder dispatch)

```powershell
# Working tree clean (no tracked-file modifications outside wave-plan.yaml).
git status --porcelain
# Expected: empty OR only `M prompts/wave-plan.yaml` from the orchestrator's wave-start mark.

# Baseline test gate — must be green.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3

# UI baseline gates (run BOTH because Prompt 3 will touch ui/src/).
cd ui ; npx vitest run ; npm run build ; cd ..

# Phantom-API pre-check on all 5 prompts.
.\scripts\phantom-api-precheck.ps1 `
  prompts\ad-726-dm-path-refactor.md `
  prompts\ad-722a-4-divergence-auto-correction.md `
  prompts\ad-722b-4-multi-agent-telemetry-stream.md `
  prompts\ad-730-2-multi-image-dm-policy.md `
  prompts\ad-723a-3-sensorium-entry-metadata.md

# Highest AD audit.
Select-String -Path DECISIONS.md -Pattern "^### AD-7[3-9][0-9]" | Select-Object -Last 5

# Pillow availability (AD-730-2 needs PIL).
d:/ProbOS/.venv/Scripts/python.exe -c "import PIL; print('PIL', PIL.__version__)"
# Expected: PIL 12.2.0
```

**Hard-stop pre-flight conditions:**
- Baseline `pytest` gate red → fix baseline before Wave 160 starts.
- `npm run build` red on HEAD → file BF and stop; Wave 160 cannot ship UI on a broken baseline.
- `PIL` import fails → DEFER Prompt 4 (AD-730-2); proceed with 1/2/3/5 only.
- Phantom-API pre-check flags any concrete issue (not just informational notes) → revise prompt before Builder dispatch.

---

## Per-prompt workflow

For each prompt in order:

1. **Builder reads the prompt** from `prompts/<file>.md`.
2. **Builder applies sections** in order; verification steps inside each section MUST be performed before SEARCH/REPLACE.
3. **Builder runs the prompt's "Verification commands"** block.
4. **Builder runs the wave's full gate** (`pytest tests/ -q -n 4 --dist=loadfile`).
5. **If UI was touched (Prompt 3 only):** Builder runs `cd ui ; npx vitest run ; npm run build`.
6. **Builder commits** with the prompt's specified commit message (including `Closes #N` trailer; Prompt 1 uses `Closes #584 (partial)` + `Closes #654`).
7. **Builder updates `PROGRESS.md`** (closure line + test count delta).
8. **Builder marks the GH issue closed** via `gh issue close <N>`.
9. **Architect re-runs the wave's full gate** before approving the next prompt.

---

## Hard-stop conditions (during build)

Each condition triggers an immediate stop + architect surface:

1. **Working tree shows tracked changes Builder didn't make.** If they're architect-authored doc artifacts under `prompts/`, `Reviews/`, `DECISIONS.md` — commit on architect's behalf and resume. Otherwise: surface to user.
2. **Parallel test failure under `-n 4`.** Re-run failing file at `-n 0`. Pass → environmental, document and continue. Fail → triage per standard sequence.
3. **`git stash` reveals Builder's source change broke a pre-existing passing test.** Triage which change; fix minimally. Special concern for Prompt 1's verbatim-move regressions — if ANY of the 9 listed regression test files breaks, the refactor is NOT byte-identical; revert and re-extract.
4. **Phantom API in implementation** (not just test fixture) — stop. Prompt has a verification gap.
5. **Architectural change required** (modifying `BaseAgent` / `IntentMessage` Protocol / sensorium dispatch shape) — surface to user.
6. **New pip OR npm dep introduced.** Wave 160 commits to zero-new-deps; any drift is a stop-the-line.
7. **`multi_replace_string_in_file` deletes >50 lines beyond the visible SEARCH context** (BF-274 class). Run `git diff --numstat` after every `multi_replace_string_in_file` call and verify line-deletion count matches expected. Prompt 1 is HIGHEST risk — 281-line span; single `replace_string_in_file` mandated.
8. **`vitest run` green BUT `npm run build` red** (BF-279 class). Stop; UI bundle is the operator-facing artifact.
9. **Prompt 4 PIL operation crashes the runtime** — log WARNING and ship original (Tier-2 in code); if the WARNING fires more than once per test run, file BF.
10. **`apply_voice_modulation` signature change in Prompt 2 breaks existing callers** — Prompt 2 mandates default-1.0 kwargs (no-op preservation). Any existing caller that breaks indicates the kwargs default was misapplied. Stop.

---

## Quality gates (per commit)

- ✅ Test gate (`pytest -n 4 --dist=loadfile`) green.
- ✅ If UI touched: `vitest run` AND `npm run build` green.
- ✅ `git diff --stat` matches prompt's "Files to Modify" table (no surprise files).
- ✅ Commit message includes `Closes #N` trailer (Prompt 1: `Closes #584 (partial — AD-726a/b/c forward markers filed)` + `Closes #654`).
- ✅ No new files in `pyproject.toml`, `ui/package.json`, `ui/package-lock.json`.
- ✅ No emoji introduced in UI files (Prompt 3 only — pure logic file, no JSX, so no emoji vector exists; verify nonetheless).

---

## Wave-specific reminders (known false positives during architect review)

- **AD-726 verbatim moves.** Reviewer should NOT flag the pipeline-method bodies as "duplicate code" — they ARE duplicates of the old inline blocks by design. The verbatim-move discipline is the whole point of the refactor; structural change without behavior change.
- **AD-726 `agent_chat` final line count.** Post-refactor `agent_chat` is ~309 lines, NOT ≤60 as #584 specifies. The 60-line target requires the pre-LLM extractions (AD-726a/b) too. Reviewer should NOT flag this as incomplete — the SCOPE STATEMENT explicitly defers it.
- **AD-722a-4 default-OFF.** Reviewer should NOT flag the firewall as over-cautious — INVERTING AD-727 rule #1 read-only contract for prosody output is a real architectural deviation. Default-OFF is the right blast-radius mitigation.
- **AD-722b-4 fleet endpoint registers AFTER per-agent endpoint.** FastAPI uses declaration order ONLY for non-prefix paths. The fleet path `/avatar-telemetry/stream` and per-agent path `/{agent_id}/avatar-telemetry-stream` have different prefixes (no `/{agent_id}/` ⇒ no ambiguity). Reviewer should NOT flag insertion order as a routing bug.
- **AD-730-2 Pillow already installed.** Reviewer should NOT flag the `from PIL import Image` import as a new dep — verified `PIL 12.2.0` in venv as of 2026-05-14.
- **AD-730-2 hard-cap is the ONE strict reject.** The other two tiers (downscale, budget) are Tier-2 log-and-degrade. Reviewer should NOT flag asymmetry — it's intentional per the cost-gate-vs-quality-gate distinction.
- **AD-723a-3 `wrapper` typed as `object | None`.** Reviewer should NOT flag this as weak typing — frozen-dataclass + `Callable` interactions across Python versions are unreliable. The runtime `callable(...)` check is the real type gate. Documented in the docstring.
- **AD-723a-3 does NOT migrate any existing entries.** Reviewer should NOT flag `SENSORIUM_REGISTRY` as untouched — the AD is the metadata extension, not the migration. Per-entry migration is AD-723a-3a.

---

## Post-sweep procedures

After all 5 prompts ship:

1. **Full gate** `pytest tests/ -q -n 4 --dist=loadfile`.
2. **UI gate** `cd ui ; npx vitest run ; npm run build`.
3. **Close GH issues** #584 (partial — leave open with `AD-726a/b/c forward markers filed` comment; the issue title remains open as a tracker for the deferred extractions), #613, #601, #632, #626, #654 (Builder closes each at its own commit; double-check none are stragglers; AD-726 closes #654 in addition to #584-partial).

   Actually: #584 is closed by AD-726 PARTIAL with an explanatory comment that links to AD-726a/b/c forward markers. The issue stays CLOSED — the forward markers become new issues if/when they advance. This matches the AD-720-vs-AD-720a-vs-AD-720d series pattern.
4. **Update `docs/development/roadmap.md`** Bug Tracker — remove rows for #584, #613, #601, #632, #626, #654; add forward-marker rows AD-726a, AD-726b, AD-726c, AD-722a-4-1, AD-722a-4-2, AD-722b-4a, AD-722b-4-1, AD-730-2-1, AD-730-2-2, AD-723a-3a, AD-723a-3b.
5. **Append to `DECISIONS.md`**: AD-726, AD-722a-4, AD-722b-4, AD-730-2, AD-723a-3, AD-722c-3 (style-guide rule entry) entries.
6. **Update `prompts/wave-orchestrator-state.json`** — `current_wave` advances, `current_stage` returns to `idle`.
7. **Set `wave-plan.yaml` entry 160** `status: shipped`.

---

## Build report

After the wave completes, write `prompts/build-reports/wave-160-build-report.md` with:
- Test count delta (start vs end of wave).
- Per-prompt wall-time actuals.
- Any hard-stops triggered + how resolved.
- Any phantom-API or architectural revisions made mid-build.
- Forward markers filed.
- Any BF entries opened (parallel-test environmental noise, etc.).
- Specific notes on Prompt 1's verbatim-move regression coverage (did all 9 listed regression test files stay green unmodified? If any broke, document the root cause).

---

## Numbering — Hard Rule (audit)

**Current highest AD in DECISIONS.md / decisions-era-*.md:** AD-739 (verified via `grep` for `AD-7\d{2}` across all era files; result is 739 by a margin — 738 series has the most sub-ADs, 739 is the highest top-level).

Wave 160's AD numbering:
- **AD-726** — already reserved as a Wave 159 forward marker (open GH #584 became AD-726). NO new top-level number consumed.
- **AD-722a-4, AD-722b-4** — sub-AD slots of existing parent AD-722. NO new top-level number consumed.
- **AD-730-2** — sub-AD slot of AD-730. NO new top-level number consumed.
- **AD-723a-3** — sub-AD slot of AD-723a. NO new top-level number consumed.
- **AD-722c-3** — sub-AD slot of AD-722c (Wave 159). NO new top-level number consumed. Folded as a docs-edit into AD-726's prompt.

**Wave 160 consumes ZERO new top-level AD numbers.** Next free top-level AD remains **AD-740** (unchanged from Wave 159 close).
