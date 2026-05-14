# AD-738a — Wave-orchestrator commit-count audit + `voice.ts` test-affordance gating

**AD:** AD-738a. **Parent ADs:** AD-738 (Wave 157 Piper TTS) + wave-orchestrator scaffolding (AD-682 / cross-wave).
**GH issues closed:** [#650](https://github.com/seangalliher/ProbOS/issues/650).
**Wave:** 158. **Estimated tests:** +2 Vitest (no new pytest). **Estimated wall-time:** ~1h.

> ### AD-numbering note — slot reuse
> Wave 157's closure block reserved `AD-738a` for "Per-agent voice selection (`CrewProfile.voice_model` + UI selector)." That forward marker is **renumbered to AD-738f** by this wave (see `prompts/ad-738a-orchestrator-test-affordance.md` Tracker Updates section below). The new AD-738a is GitHub issue #650's hygiene bundle.
>
> Other Wave-157 forward markers renumber atomically in this prompt:
> - AD-738a (was: per-agent voice selection) → **AD-738f**
> - AD-738b (was: GPU TTS eval Kokoro/StyleTTS2) → **AD-738g** (the AD-738b slot is reused by Wave-158 prompt #3, GH #651)
> - AD-738c (was: server-side voice modulation) → **AD-738h** (the AD-738c slot is reused by Wave-158 prompt #4, GH #652)
> - AD-738d (was: TTS text caching) → **AD-738i**
>
> All four renumberings happen inside THIS prompt's tracker section so subsequent Wave-158 prompts can use the freed `AD-738a/b/c` slots without ambiguity.

---

## Solution Overview

Two small hygiene items surfaced during Wave 157's GATE 2 review:

1. **Wave-orchestrator commit-count drift surface** (`scripts/wave-orchestrator.ps1`, `Format-Gate2`). The current GATE 2 emits raw `git log --oneline origin/main..HEAD` + `git diff --stat`. Add one line that compares the actual unpushed-commit count against the wave's claimed commit count (read from `prompts/wave-plan.yaml` — Wave 157 expected 1, actually had 2 because a prior AD-739 docs-only placeholder was already on the branch). **Audit trail only — never block a push.**
2. **`_resetTtsStatusForTests` gated by `MODE === 'test'`** (`ui/src/audio/voice.ts:143`). The underscore-prefixed test affordance is exported from production code without guard. Add an early-return when `import.meta.env.MODE !== 'test'` so production calls become no-ops, and add one Vitest case asserting the production call path is inert.

Both items are independent and parallel-safe; Section 1 touches the orchestrator PowerShell, Section 2 touches the browser TypeScript. Section 3 below atomically renumbers the four Wave-157 forward markers (AD-738a → AD-738f, etc.) since this prompt is the first in Wave 158 to touch `roadmap.md` and `DECISIONS.md`.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `scripts/wave-orchestrator.ps1` | ~327–355 (`Format-Gate2`) | Add commit-count audit line. |
| `ui/src/audio/voice.ts` | ~142–147 (`_resetTtsStatusForTests`) | Add MODE guard early-return. |
| `ui/src/audio/__tests__/voice.testGate.test.tsx` | NEW | 2 Vitest assertions. |
| `docs/development/roadmap.md` | 361–364 | Renumber 4 forward markers. |
| `DECISIONS.md` | ~2446 (AD-738 closure forward-markers paragraph) | Renumber 4 forward markers in narrative. |

No new Python deps, no new npm deps.

---

## Section 1 — Wave-orchestrator commit-count audit

In `scripts/wave-orchestrator.ps1`, find `Format-Gate2` (currently at line 327). The existing body is:

```powershell
function Format-Gate2 {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — GATE 2: ARCHITECT APPROVAL TO PUSH
============================================================

ACTION: Inspect commits before pushing.

COMMANDS:
  git log --oneline origin/main..HEAD
  git diff origin/main..HEAD --stat
  git log -p origin/main..HEAD | Select-String -Pattern 'TODO|XXX|FIXME|breakpoint'
```

Replace the `COMMANDS:` block with:

```powershell
COMMANDS:
  git log --oneline origin/main..HEAD
  git diff origin/main..HEAD --stat
  git log -p origin/main..HEAD | Select-String -Pattern 'TODO|XXX|FIXME|breakpoint'

COMMIT-COUNT AUDIT (AD-738a — audit trail only, NEVER blocks a push):
  `$expected = ($wave.prompt_paths | Measure-Object).Count
  `$actual   = (git log --oneline origin/main..HEAD | Measure-Object).Count
  if (`$expected -ne `$actual) {
    Write-Host "AUDIT: wave $($wave.id) expected `$expected commit(s); HEAD has `$actual unpushed commit(s). Review the extra commits before pushing." -ForegroundColor Yellow
  } else {
    Write-Host "AUDIT: wave $($wave.id) commit count matches (`$expected)." -ForegroundColor Green
  }
```

(Note: the PowerShell escapes `` ` `` are required because the outer string is a here-string `@"..."@` that interpolates `$wave.id` but must NOT interpolate `$expected` / `$actual` at script-load time — those should resolve when the architect pastes the block into their terminal at GATE 2.)

The expected count uses `$wave.prompt_paths.Count` (one commit per prompt is the standing convention in `BUILDER-EXECUTION-PLAN.md:79`). If a wave deviates (e.g., one prompt produces two commits), the architect sees the audit line and decides. The audit NEVER affects the orchestrator's advance state — it's an informational print.

---

## Section 2 — Gate `_resetTtsStatusForTests` behind `MODE === 'test'`

In `ui/src/audio/voice.ts` around line 142, the current function is:

```typescript
/** AD-738: TEST-ONLY hook to reset the module-level probe cache between tests. */
export function _resetTtsStatusForTests(): void {
  _ttsStatus = null;
  _ttsStatusInflight = null;
  _activeAudio = null;
}
```

Replace with:

```typescript
/** AD-738: TEST-ONLY hook to reset the module-level probe cache between tests.
 *  AD-738a (Wave 158): gated behind ``import.meta.env.MODE === 'test'``.
 *  Vitest sets MODE='test' at module load. Production builds (``vite build``)
 *  set MODE='production' so this becomes a no-op — accidental production
 *  callers cannot reset the cache and disturb the zero-HTTP-per-utterance
 *  guarantee. The function is still exported so existing test imports
 *  resolve without a binding error. */
export function _resetTtsStatusForTests(): void {
  if (import.meta.env.MODE !== 'test') return;
  _ttsStatus = null;
  _ttsStatusInflight = null;
  _activeAudio = null;
}
```

**Backward-compat check:** the 6 existing call sites in `ui/src/audio/__tests__/voice.serverTts.test.tsx` all run under Vitest with MODE='test' — they keep working unchanged. The new guard adds zero behavior change for any current caller.

---

## Section 3 — Atomic renumbering of Wave-157 forward markers

Wave 157's closure block in `DECISIONS.md:2446` and its roadmap entries (`docs/development/roadmap.md:361-364`) reserved `AD-738a/b/c/d` for future work. Wave 158's GH issues #650 / #651 / #652 (titled "AD-738a", "AD-738b", "AD-738c") reuse those slots for hygiene. **This prompt is responsible for renumbering the original forward markers to free the slots.**

### 3a — `docs/development/roadmap.md`

Find lines 361–364:

```
| AD-738a | Per-agent voice selection (CrewProfile.voice_model + UI selector with license display) | none | 4 |
| AD-738b | GPU-accelerated TTS backend eval (Kokoro Apache 2.0 / StyleTTS2 MIT slot into TTSBackend Protocol) | none | 4 |
| AD-738c | Server-side voice modulation (apply AD-735 pitch/rate at Piper synthesis, not `<audio>` post-processing) | none | 4 |
| AD-738d | TTS text caching layer (LRU keyed `(agent_id, voice, sha256(text))` → `attachment_id`) | none | 4 |
```

Replace with:

```
| AD-738f | Per-agent voice selection (CrewProfile.voice_model + UI selector with license display) — renumbered from AD-738a (Wave 158) | none | 4 |
| AD-738g | GPU-accelerated TTS backend eval (Kokoro Apache 2.0 / StyleTTS2 MIT slot into TTSBackend Protocol) — renumbered from AD-738b (Wave 158) | none | 4 |
| AD-738h | Server-side voice modulation (apply AD-735 pitch/rate at Piper synthesis, not `<audio>` post-processing) — renumbered from AD-738c (Wave 158) | none | 4 |
| AD-738i | TTS text caching layer (LRU keyed `(agent_id, voice, sha256(text))` → `attachment_id`) — renumbered from AD-738d (Wave 158) | none | 4 |
```

### 3b — `DECISIONS.md` around line 2446 (Wave 157 closure block)

The current "Forward markers" paragraph reads (verbatim from the live file):

> **Forward markers.** AD-738a (per-agent voice selection — `CrewProfile.voice_model` field + selector UI in `ProfileInfoTab.tsx` with license display; trigger: operator has > 2 voice models installed). AD-738b (GPU-accelerated TTS backend eval — Kokoro Apache 2.0 / StyleTTS2 MIT slot into the `TTSBackend` Protocol; trigger: operator with capable GPU requests higher fidelity). AD-738c (server-side voice modulation — apply AD-735 pitch/rate at the synthesis step rather than `<audio>` post-processing; closes the "no pitch on `<audio>`" limitation). AD-738d (TTS text caching layer — LRU keyed `(agent_id, voice, sha256(text))` → `attachment_id`; trigger: telemetry shows the same text re-synthesizing repeatedly).

Append a short clarification paragraph immediately after that paragraph (do NOT rewrite the existing text — append for audit history):

> **AD-738a/b/c/d renumbering (Wave 158).** The four forward markers reserved here are renumbered to **AD-738f / AD-738g / AD-738h / AD-738i** respectively. Wave 158 GH issues #650 / #651 / #652 reuse the freed `AD-738a / AD-738b / AD-738c` slots for hygiene-track work (orchestrator commit-count audit + voice.ts test gating / per-wave `npm run build` UI gate / rhubarb→Oculus viseme mapping polish). The renumbered Tier-4 work remains unshipped and is now tracked under the new names in `docs/development/roadmap.md:361-364`.

---

## What This Does NOT Change

- The orchestrator's advance state machine. The audit print is informational only — it never fails or blocks.
- The 4 renumbered forward markers' scope or priority. Tier-4 roadmap remains Tier-4.
- `_fetchTtsStatus`, `_invalidateTtsStatus`, `_ttsStatus` module state. The test-gate change only affects the test-reset helper.
- The 6 existing Vitest call sites in `voice.serverTts.test.tsx`. All keep passing because Vitest sets MODE='test'.
- Any non-`voice.ts` UI file. No bundle-shape change.
- `BUILDER-EXECUTION-PLAN.md` — see prompt #3 (`ad-738b-ui-gate-npm-build.md`) for the standing-rule edit.

---

## Test Plan

### `ui/src/audio/__tests__/voice.testGate.test.tsx` (NEW, 2 tests)

Use Vitest's `vi.stubEnv` (already imported in nearby tests, see `voice.serverTts.test.tsx`).

1. **`_resetTtsStatusForTests is a no-op under MODE=production`** (production guard).
   ```typescript
   import { _resetTtsStatusForTests } from '../voice';
   // ...prime the module's internal state via a probe...
   vi.stubEnv('MODE', 'production');
   _resetTtsStatusForTests();
   // Probe again — must return the cached value, NOT re-fetch.
   ```
2. **`_resetTtsStatusForTests resets state under MODE=test`** (happy path).
   ```typescript
   vi.stubEnv('MODE', 'test');
   _resetTtsStatusForTests();
   // Probe — must re-fetch (fetch mock asserts called).
   ```

**Test ordering:** these two tests MUST be in their own file (NOT `voice.serverTts.test.tsx`) because `vi.stubEnv('MODE', 'production')` would otherwise leak into the 6 existing serverTts tests and break them. The new file uses `vi.unstubAllEnvs()` in `afterEach`.

No new pytest tests (the wave-orchestrator change is a PowerShell here-string with no automated coverage today; manual smoke at GATE 2 of Wave 158 itself is the verification).

---

## Verification Commands

```pwsh
cd ui
npx vitest run src/audio/__tests__/voice.testGate.test.tsx
npx vitest run src/audio/__tests__/voice.serverTts.test.tsx   # regression
npx vitest run
npm run build                                                   # UI gate (BF-279 lesson)
cd ..

d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile   # full pytest gate (regression only)

# Smoke the orchestrator audit line — fake a wave-plan entry and call Format-Gate2.
# Manual verification only (no automated test for the orchestrator).
```

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## License Disposition

All-internal. **No new npm deps** (Vitest already in `ui/package.json`). **No new pip deps.** Apache 2.0 compliant.

---

## Tracker Updates

- **PROGRESS.md**: bump Vitest count by 2; bullet under Wave 158: "AD-738a — orchestrator commit-count audit + `_resetTtsStatusForTests` MODE gate."
- **DECISIONS.md**: append `### AD-738a — Orchestrator commit-count audit + voice.ts test gate (Wave 158)` closure block. Reference the supersession of the Wave-157 forward marker and the slot reuse.
- **docs/development/roadmap.md**: see Section 3a (4 forward-marker renumberings).
- **GH #650**: close on push.

---

## Forward Markers

- (none — this AD is itself a closure of a Wave-157 forward marker)

---

## Verified Against Codebase (2026-05-13)

```
grep -n "function Format-Gate2" scripts/wave-orchestrator.ps1
  327: function Format-Gate2 {
grep -n "origin/main..HEAD" scripts/wave-orchestrator.ps1
  337:   git log --oneline origin/main..HEAD
  338:   git diff origin/main..HEAD --stat
  339:   git log -p origin/main..HEAD | Select-String -Pattern 'TODO|XXX|FIXME|breakpoint'

grep -n "_resetTtsStatusForTests" ui/src/audio/voice.ts
  143: export function _resetTtsStatusForTests(): void {

grep -n "_resetTtsStatusForTests" ui/src/audio/__tests__/voice.serverTts.test.tsx
  95:     voiceMod._resetTtsStatusForTests();
  135:    voiceMod._resetTtsStatusForTests();
  153:    voiceMod._resetTtsStatusForTests();
  181:    voiceMod._resetTtsStatusForTests();
  213:    voiceMod._resetTtsStatusForTests();
  248:    voiceMod._resetTtsStatusForTests();
  (6 callers, all under Vitest with MODE='test' by default)

grep -n "AD-738a\|AD-738b\|AD-738c\|AD-738d" docs/development/roadmap.md
  361: | AD-738a | Per-agent voice selection ...
  362: | AD-738b | GPU-accelerated TTS backend eval ...
  363: | AD-738c | Server-side voice modulation ...
  364: | AD-738d | TTS text caching layer ...

grep -n "Forward markers.\*AD-738a" DECISIONS.md
  2446: **Forward markers.** AD-738a ... AD-738b ... AD-738c ... AD-738d ...
```
