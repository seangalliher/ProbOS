# BF-299: UI build hygiene — static/dynamic import mismatches

**Status:** Ready to build
**Closes:** #757 (mismatches only — `manualChunks` work deferred to a follow-up)
**Estimated tests:** 0 new behavioral tests. Acceptance is build-log + existing vitest suite green.

## Problem

`npm run build` in `ui/` emits two Vite/Rollup warnings of the form:

```
(!) ../store/useSettingsStore.ts is dynamically imported by audio/wakeWord.ts
    but also statically imported by App.tsx, CompactApp.tsx, ...
    dynamic import will not move module into another chunk.
(!) audio/useLipSyncCapture.ts is dynamically imported by audio/voice.ts
    but also statically imported by components/profile/CrewVRM.tsx
    dynamic import will not move module into another chunk.
```

Both modules are already eagerly loaded by their static-side consumers, so the
`await import(...)` calls are dead indirection — they pay the syntactic cost of
laziness without delivering a chunk split.

## Solution

Convert each `await import(...)` to a static import (Option A from #757). Both
sites read the imported binding only inside a function body, so the conversion
is a 1-line swap per file.

### Section 1 — `wakeWord.ts`

`useSettingsStore.ts` only imports from `zustand` (verified) — no path back to
audio code, so there is zero cycle risk.

File: `ui/src/audio/wakeWord.ts`

Add to the existing import block at the top of the file (after the existing
`./wakeWord.router` import block, before the type exports at line ~34):

```ts
import { useSettingsStore } from '../store/useSettingsStore';
```

Then in the body around line 290, replace:

```ts
  try {
    const { useSettingsStore } = await import('../store/useSettingsStore');
    const snapshot = useSettingsStore.getState().snapshot;
```

with:

```ts
  try {
    const snapshot = useSettingsStore.getState().snapshot;
```

The surrounding `try/catch` stays (it still guards against
`snapshot` being `undefined` before hydration).

### Section 2 — `voice.ts`

`useLipSyncCapture.ts` statically imports `onSpeechEvent` from `./voice` (line 16,
verified). Converting `voice.ts`'s dynamic import to static would create a
voice ↔ useLipSyncCapture cycle. The cycle is **benign in ES module semantics**
because neither side reads the imported binding at module-top-level evaluation
time: `voice.ts` reads `injectLipSyncFrames` inside an `addEventListener`
callback, and `useLipSyncCapture.ts` reads `onSpeechEvent` inside the hook body
(`useEffect`). Vite/Rollup handle live bindings correctly under this pattern
(verified: `CrewVRM.tsx` already participates in this same call graph via its
static import of `useLipSyncCapture`, and the build is green today).

File: `ui/src/audio/voice.ts`

Add to the existing import block at the top of the file (after line 5,
`import { useStore } from '../store/useStore';`):

```ts
import { injectLipSyncFrames } from './useLipSyncCapture';
```

Then in the body around line 291, replace:

```ts
      if (Array.isArray(data.visemes) && data.visemes.length > 0) {
        try {
          const { injectLipSyncFrames } = await import('./useLipSyncCapture');
          injectLipSyncFrames(data.visemes, agent_id);
        } catch {
          // ignore — visemes are best-effort
        }
      }
```

with:

```ts
      if (Array.isArray(data.visemes) && data.visemes.length > 0) {
        try {
          injectLipSyncFrames(data.visemes, agent_id);
        } catch {
          // ignore — visemes are best-effort
        }
      }
```

The `try/catch` stays — the call itself can still throw on degenerate frame
data and the existing "best-effort" contract is preserved.

## Verification

After both edits, from `d:\ProbOS\ui`:

1. `npm run build` — output must NOT contain either of the two
   "dynamically imported by ... but also statically imported by ..." warnings
   referencing `useSettingsStore` or `useLipSyncCapture`. Other unrelated
   warnings (if any) are out of scope for this BF.
2. `npx vitest run` — full suite green. Expected count: 934+ (current
   baseline per recent commits is in the 930s; do not assert an exact number
   in the commit message — confirm green, not count).

Specifically re-run the two suites that exercise the converted call paths:

- `npx vitest run src/audio/__tests__/useLipSyncCapture.test.tsx`
- `npx vitest run src/audio/__tests__/voice.serverTts.test.tsx`
- `npx vitest run src/__tests__/CrewVRM.realAudioFallback.test.tsx`

If `voice.serverTts.test.tsx` mocks `await import('./useLipSyncCapture')` via
`vi.mock` with a factory, it should still work — `vi.mock` hoists ahead of
both static and dynamic imports. No test edits expected; if a test breaks, the
right fix is in the test (update the mock pattern), not in production code.

## What This Does NOT Change

- No behavior changes. Identical runtime call sequence — only the module-load
  timing for two modules that were already eagerly loaded.
- No bundle-split work. The bundle stays ~3.36 MB / 924 KB gzipped. The
  `manualChunks` follow-up is a separate issue (file it after this BF lands —
  suggested title: "UI build hygiene: route-level lazy chunk for VRM/three.js
  stack"; cite #757 body lines 11-14 as the source).
- No changes to `useSettingsStore.ts`, `useLipSyncCapture.ts`, or their other
  consumers. The only files touched are `ui/src/audio/wakeWord.ts` and
  `ui/src/audio/voice.ts`.
- No live runtime restart. Build hygiene only — Captain can hard-refresh the
  HXI when convenient.

## Standing Constraints

- DO NOT touch the live runtime.
- DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.
- DO NOT run a process-sweep that filters on path/name (see user-memory:
  "broad python-kill" / `kill-stale-pytest.ps1`).

## Tracking

- `PROGRESS.md`: prepend a one-line `BF-299 shipped (date)` entry following the
  existing format. Confirm `Closes #757` in the commit message.
- `docs/development/roadmap.md` Bug Tracker: add BF-299 row pointing at this
  prompt and the closing commit SHA.
- After the commit lands, open a follow-up issue for the `manualChunks` /
  bundle-split work referenced in #757's second paragraph.

## Acceptance Criteria

- One commit titled `BF-299: UI build hygiene — static/dynamic import mismatches`
  with trailer `Closes #757`.
- `npm run build` output is free of the two specific
  static-vs-dynamic warnings for `useSettingsStore` and `useLipSyncCapture`.
- Existing vitest suite passes (934+ green; whatever the current baseline is).
- Follow-up `manualChunks` issue filed (link in commit body).
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-23)

```
grep -n "await import" ui/src/audio/wakeWord.ts
  290:    const { useSettingsStore } = await import('../store/useSettingsStore');

grep -n "await import" ui/src/audio/voice.ts
  291:          const { injectLipSyncFrames } = await import('./useLipSyncCapture');

grep -rn "from .*useSettingsStore" ui/src
  ui/src/App.tsx:27
  ui/src/CompactApp.tsx:20
  (+ 7 more static consumers per #757 body)

grep -rn "from .*useLipSyncCapture" ui/src
  ui/src/components/profile/CrewVRM.tsx:23
  ui/src/audio/__tests__/useLipSyncCapture.test.tsx:4   (test)
  ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx:8 (test)

grep -n "^import" ui/src/store/useSettingsStore.ts
  3:import { create } from 'zustand';   # no cycle source

grep -n "from './voice'" ui/src/audio/useLipSyncCapture.ts
  16:import { onSpeechEvent } from './voice';   # benign cycle (function-body only)
```
