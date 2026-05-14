# AD-738b — Per-wave UI gate must include `npm run build` (BF-279 lesson)

**AD:** AD-738b. **Parent ADs:** BF-279 (2026-05-13, stale `ui/dist/` for ~32h); cross-wave orchestrator hygiene.
**GH issues closed:** [#651](https://github.com/seangalliher/ProbOS/issues/651).
**Wave:** 158. **Estimated tests:** 0 (process change only). **Estimated wall-time:** ~30 min.

> ### AD-numbering note
> The `AD-738b` slot was reserved by Wave 157's closure block for "GPU-accelerated TTS backend eval (Kokoro / StyleTTS2)." That forward marker is **renumbered to AD-738g** by `prompts/ad-738a-orchestrator-test-affordance.md` Section 3 (which lands first in Wave 158). This prompt assumes the renumber has been applied; if AD-738a is built second, Builder must do AD-738a first OR manually verify roadmap.md no longer has a colliding `AD-738b` row.

---

## Solution Overview

Wave 156's `MicPermissionHint.tsx` introduced `JSX.Element` (not resolvable under React 19 + bundler-mode tsconfig). `tsc -b` errored, `vite build` never ran, and `ui/dist/` stayed frozen for ~32 hours through Waves 155, 156, and 157. The Counselor lip-sync work and Piper TTS shipped to `origin/main` but never reached the operator's browser. Captain reported "everything still sounds the same" after restart — actual cause was a stale bundle, NOT a runtime fault.

**Vitest passes everything that compiles**, but **vitest does NOT run `tsc -b` strict checks** and **does NOT verify `vite build` produces a fresh `ui/dist/`**. A test suite can be 100% green while the production bundle can't compile.

**Fix:** make the per-wave UI gate run BOTH `cd ui; npx vitest run` AND `cd ui; npm run build` for any wave touching `ui/src/**`. BF-279 fixed the specific `JSX.Element` regression; this AD codifies the standing rule so it never recurs.

Two artifacts updated:

1. `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules — add a "UI gate" rule entry referencing BF-279 as the canonical case study.
2. `scripts/wave-orchestrator.ps1` `Format-BuildDispatch` — append `npm run build` to the per-prompt verification block whenever the wave touches UI.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `prompts/BUILDER-EXECUTION-PLAN.md` | ~24 (Standing Rules section) | Add "UI gate" rule. |
| `scripts/wave-orchestrator.ps1` | ~262–305 (`Format-BuildDispatch`) | Append `npm run build` to dispatch for UI-touching waves. |

No code changes (`src/` and `ui/src/` are not touched). No new tests (process-change-only).

---

## Section 1 — Add "UI gate" Standing Rule

In `prompts/BUILDER-EXECUTION-PLAN.md`, find the `## Standing Rules (carry forward from prior sweep)` heading (line 24) and the bullet list immediately below. Insert this new bullet **between the "License policy" bullet and the `---` separator** (so it lands as the last bullet in the Standing Rules section):

```markdown
- **UI gate (BF-279, 2026-05-13):** any wave touching `ui/src/**` (or any file matched by `git diff --name-only origin/main..HEAD -- ui/src/`) MUST run BOTH UI verification steps before the per-prompt commit:
  1. `cd ui; npx vitest run` — logic correctness for the UI changes.
  2. `cd ui; npm run build` — TypeScript strict + Vite production bundle health.
  Vitest skips `tsc -b` strict checks. A test suite can be 100% green while `vite build` errors. BF-279 (commit `2d685bc5`) is the canonical case study: Wave 156's `MicPermissionHint.tsx` introduced `JSX.Element` (unresolved under React 19 + bundler-mode tsconfig), `vite build` errored, `ui/dist/` stayed frozen for ~32 hours, and three waves' user-visible work never reached the operator's browser despite all Vitest tests passing.
```

---

## Section 2 — Orchestrator dispatch surfaces `npm run build`

In `scripts/wave-orchestrator.ps1`, find `Format-BuildDispatch` (line 262). The current `Per-prompt:` and `Per-commit gate:` lines in the dispatch body read:

```powershell
  Per-prompt: read prompt + review (apply non-blocking nits at code-review),
  implement section by section, run focused gate at -n 0, update trackers,
  commit with ``AD-NNN: <one-line>`` format, push.

  Per-commit gate: full pytest passes, test count non-decreasing,
  pre-commit deletion sanity check.
```

Replace with:

```powershell
  Per-prompt: read prompt + review (apply non-blocking nits at code-review),
  implement section by section, run focused gate at -n 0, update trackers,
  commit with ``AD-NNN: <one-line>`` format, push.

  Per-commit gate: full pytest passes, test count non-decreasing,
  pre-commit deletion sanity check.

  UI gate (AD-738b / BF-279): if the prompt touches any file under
  ``ui/src/**``, run BOTH ``cd ui; npx vitest run`` AND ``cd ui; npm run build``
  before the commit. Vitest alone does NOT exercise ``tsc -b`` strict checks;
  ``npm run build`` is the only signal that the production bundle compiles.
  Detection: ``git diff --name-only HEAD~1..HEAD -- ui/src/`` after the
  per-prompt edits; if non-empty, run both. The standing rule lives in
  ``prompts/BUILDER-EXECUTION-PLAN.md`` Standing Rules section.
```

Place this block AFTER the existing `Per-commit gate:` line and BEFORE the `Begin in dependency order;` line.

---

## What This Does NOT Change

- The wave-orchestrator state machine, advance logic, or stage list. No new stages.
- The Vitest test runner config. `vitest.config.ts` is untouched.
- The Vite config (`ui/vite.config.ts`). No build flags change.
- `.github/copilot-instructions.md` review-flag list — the `HXI Canvas regression` flag and `HXI emoji violation` flag already exist; this rule is captured in `BUILDER-EXECUTION-PLAN.md` (the Builder's standing reference), not duplicated in copilot-instructions.
- Any production code. Pure process change.
- CI workflows (if any exist under `.github/workflows/`). Future work can mirror this rule into CI.

---

## Test Plan

This is a process-change-only AD. No new automated tests.

**Manual verification** (done as part of the Wave 158 dispatch itself — Builder verifies):

1. After editing `BUILDER-EXECUTION-PLAN.md`, run `Get-Content prompts/BUILDER-EXECUTION-PLAN.md | Select-String -Pattern 'UI gate \(BF-279'` and confirm the new bullet appears in the Standing Rules section.
2. After editing `scripts/wave-orchestrator.ps1`, run `./scripts/wave-orchestrator.ps1 dispatch` against a UI-touching wave (e.g., Wave 158 itself once prompts #4 / #5 are in flight) and confirm the dispatch output includes the new `UI gate (AD-738b / BF-279)` paragraph.
3. The forward-effect verification — that Wave 158's own UI prompts (#4 `ad-738c-viseme-mapping-polish.md`, #5 `ad-738e-1-per-emotion-prosody.md`) actually run `npm run build` in their gates — is the real proof. If the Builder skips `npm run build` for those prompts, the AD is broken.

---

## Verification Commands

```pwsh
Get-Content prompts/BUILDER-EXECUTION-PLAN.md | Select-String -Pattern 'UI gate \(BF-279, 2026-05-13\)'
# Expect: 1 match in the Standing Rules section.

Get-Content scripts/wave-orchestrator.ps1 | Select-String -Pattern 'UI gate \(AD-738b / BF-279\)'
# Expect: 1 match inside Format-BuildDispatch.

# No code changes — pytest / vitest baselines unchanged.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile   # regression baseline (must be flat)
cd ui; npx vitest run; npm run build; cd ..                          # regression baseline (must be flat)
```

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## License Disposition

All-internal. **No new pip deps, no new npm deps, no external code absorbed.** Apache 2.0 compliant.

---

## Tracker Updates

- **PROGRESS.md**: bullet under Wave 158: "AD-738b — per-wave UI gate codifies `npm run build` requirement (closes BF-279 root cause)."
- **DECISIONS.md**: append `### AD-738b — Per-wave UI gate must include npm run build (Wave 158)` closure block; cross-reference BF-279.
- **docs/development/roadmap.md**: no change (the Wave-157 AD-738b forward marker is renumbered by `prompts/ad-738a-orchestrator-test-affordance.md` Section 3 — this prompt assumes that renumber has landed).
- **GH #651**: close on push.

---

## Forward Markers

- (none — this AD codifies a standing rule and is self-contained)

---

## Verified Against Codebase (2026-05-13)

```
grep -n "## Standing Rules" prompts/BUILDER-EXECUTION-PLAN.md
  24: ## Standing Rules (carry forward from prior sweep)

grep -n "License policy" prompts/BUILDER-EXECUTION-PLAN.md
  31: - **License policy (Captain rule, 2026-05-09):** ...
  (last bullet before the --- separator; new bullet inserts after this one)

grep -n "function Format-BuildDispatch" scripts/wave-orchestrator.ps1
  262: function Format-BuildDispatch {

grep -n "Per-commit gate" scripts/wave-orchestrator.ps1
  290:   Per-commit gate: full pytest passes, test count non-decreasing,

grep -n "Begin in dependency order" scripts/wave-orchestrator.ps1
  293:   Begin in dependency order; surface only on hard-stop conditions per

grep -rn "BF-279" prompts/ scripts/ DECISIONS.md decisions-era-*.md
  (current BF-279 references — confirm the case-study citation lands in the bullet)
```
