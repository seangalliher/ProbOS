# Issue #770 — UI build hygiene: lazy chunk for VRM/three.js stack

**Status:** Ready for Builder
**Dependencies:** None (follow-up to BF-299 / commit 8743c77e, already shipped)
**Estimated tests:** 0 new (existing Vitest 934 must still pass)
**Type:** Build hygiene (no new AD; commits with `Closes #770`)

## Problem

`npm run build` currently emits a single eager bundle:

```
ui/dist/assets/index--GCHzeXV.js     3290.80 KB   (~925 KB gzipped)
ui/dist/assets/retarget-zy97S80V.js     1.40 KB
```

Rollup warns ">500 kB after minification". The dominant payload is `three` +
`@pixiv/three-vrm` + `three/examples/jsm/loaders/GLTFLoader` pulled in by the
avatar / canvas stack. Every surface (including Compact mode, which has no 3D)
ships the full vendor blob on first paint.

## Verified Against Codebase (2026-05-23)

### Current Vite config (no chunking)

```
grep -n "manualChunks\|rollupOptions" ui/vite.config.ts
  (no matches)
```

`ui/vite.config.ts` (verbatim, lines 1-22):

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:18900',
      '/ws': { target: 'ws://127.0.0.1:18900', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
```

### three.js import graph

```
grep -rEn "from ['\"]three|@pixiv/three-vrm" ui/src/ --include="*.ts*" \
  | grep -v __tests__
```

Production importers of `three` / `@pixiv/three-vrm`:

| Path | Imports |
|---|---|
| `ui/src/canvas/agentVRM.tsx` | three, GLTFLoader, @pixiv/three-vrm |
| `ui/src/canvas/agents.tsx` | three |
| `ui/src/canvas/animations.tsx` | three |
| `ui/src/canvas/clusters.tsx` | three |
| `ui/src/canvas/connections.tsx` | three |
| `ui/src/canvas/scene.ts` | three |
| `ui/src/canvas/animation/retarget.ts` | three |
| `ui/src/components/CognitiveCanvas.tsx` | three |
| `ui/src/components/profile/CrewVRM.tsx` | three, GLTFLoader, @pixiv/three-vrm |
| `ui/src/components/profile/ParametricAvatar.tsx` | three |
| `ui/src/components/profile/MemoryGraph3D.tsx` | three |
| `ui/src/components/profile/CrewAvatarPopout.tsx` | (via CrewVRM/ParametricAvatar) |
| `ui/src/components/spatial/ShipLayoutView.tsx` | three |

### Entry-point graph (the load-bearing observation)

`ui/src/main.tsx` (lines 1-24, verbatim):

```ts
import App from './App';
import CompactApp from './CompactApp';
import { InstallPrompt } from './components/InstallPrompt';
...
const compactMode = ... window.location.hash.toLowerCase().includes('compact');

createRoot(...).render(
  compactMode ? <CompactApp /> : <><App /><InstallPrompt /></>,
);
```

`App.tsx` statically imports `CognitiveCanvas` (three) and
`AgentProfilePanel` → `profile/index.ts` → `AgentProfilePanel.tsx` → which
ultimately pulls `CrewVRM` and `ParametricAvatar`. `CompactApp.tsx` imports
ONLY `ProfileChatTab`, which has no three.js dependency (verified — its
imports are `useStore`, `voice`, `speechInput`, `MicIndicator`,
`ModulationIndicator`, screen-share hooks; no three / VRM / canvas).

**Architectural surprise (critical):** because `main.tsx` statically imports
both `App` and `CompactApp` at module top, the static import graph from the
entry chunk includes the three.js stack unconditionally — Compact mode pays
the full ~3.3 MB cost today. A `manualChunks` split alone will produce
separate chunks but Rollup will still mark them as static entry-graph deps
of `index.js`, so the browser will pre-fetch all of them on first paint.

**For the chunk split to actually defer three.js, `App` must become a
`React.lazy` dynamic import.** This is the genuine fix; `manualChunks` alone
is necessary but not sufficient.

### Existing React.lazy usage

```
grep -rE "React\.lazy|\blazy\(" ui/src/
  (no matches — no existing lazy boundaries)
```

This is the first lazy boundary in the UI.

## Solution

Two coordinated changes:

1. **`ui/src/main.tsx`** — convert `App` to `React.lazy`. Keep `CompactApp`
   eager (it's the small surface; lazy-loading it adds a network roundtrip
   for the desktop tray app, which is the wrong tradeoff).
2. **`ui/vite.config.ts`** — add `build.rollupOptions.output.manualChunks` to
   group three / @pixiv/three-vrm into `avatar-vendor` and avatar/canvas
   app code into `avatar-app`. This lets the dynamic-import boundary at
   `main.tsx` actually carve a separate network fetch instead of being
   absorbed back into the main chunk by Rollup's default heuristic.

Both changes are required; either alone is insufficient.

## Implementation

### Section 1 — `ui/vite.config.ts`

Replace the current `build` block.

```search
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
```

```replace
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // Vendor: three.js + @pixiv/three-vrm. Heavy, only avatar/canvas
          // surfaces need them; defer until the App chunk is loaded.
          if (
            id.includes('node_modules/three/') ||
            id.includes('node_modules/@pixiv/three-vrm')
          ) {
            return 'avatar-vendor';
          }
          // App-side code that depends on three.js: canvas/* and avatar
          // components. Grouping these prevents Rollup from re-fanning
          // three-dependent modules back into the main chunk.
          if (
            id.includes('/ui/src/canvas/') ||
            id.includes('/ui/src/components/profile/CrewVRM') ||
            id.includes('/ui/src/components/profile/ParametricAvatar') ||
            id.includes('/ui/src/components/profile/MemoryGraph3D') ||
            id.includes('/ui/src/components/profile/CrewAvatarPopout') ||
            id.includes('/ui/src/components/spatial/ShipLayoutView') ||
            id.includes('/ui/src/components/CognitiveCanvas')
          ) {
            return 'avatar-app';
          }
        },
      },
    },
  },
```

Notes:
- `id` is a normalized absolute path from Rollup; `/` separators are
  consistent on Windows too. Match on POSIX-style `/ui/src/...` substrings.
- Do NOT include `__tests__` paths in `manualChunks` decisions — Vitest
  doesn't run through Vite's production build, so the test files aren't in
  the production graph anyway. No special-case needed.

### Section 2 — `ui/src/main.tsx`

Replace the eager App import with a lazy boundary. Keep `CompactApp` eager.

```search
import { createRoot } from 'react-dom/client';
import App from './App';
import CompactApp from './CompactApp';
import { InstallPrompt } from './components/InstallPrompt';
import { registerServiceWorker } from './pwa/register';

// Compact mode: chat-only Yeo surface for the desktop tray app. Selected
// when the URL hash contains `compact` (Electron host loads `/#compact`).
const compactMode =
  typeof window !== 'undefined' &&
  window.location.hash.toLowerCase().includes('compact');

createRoot(document.getElementById('root')!).render(
  compactMode ? (
    <CompactApp />
  ) : (
    <>
      <App />
      <InstallPrompt />
    </>
  ),
);
```

```replace
import { createRoot } from 'react-dom/client';
import { lazy, Suspense } from 'react';
import CompactApp from './CompactApp';
import { InstallPrompt } from './components/InstallPrompt';
import { registerServiceWorker } from './pwa/register';

// Issue #770: lazy-load the full HXI so Compact mode does not eagerly
// pull the three.js / VRM stack. Webpack-compatible default-export
// pattern; Vite/Rollup treats this as a code-split boundary, which is
// what lets `manualChunks` actually carve `avatar-vendor` /
// `avatar-app` out of the entry graph.
const App = lazy(() => import('./App'));

// Compact mode: chat-only Yeo surface for the desktop tray app. Selected
// when the URL hash contains `compact` (Electron host loads `/#compact`).
const compactMode =
  typeof window !== 'undefined' &&
  window.location.hash.toLowerCase().includes('compact');

createRoot(document.getElementById('root')!).render(
  compactMode ? (
    <CompactApp />
  ) : (
    // Suspense fallback is intentionally null — the existing
    // WelcomeOverlay / boot sequence handles first-paint UX once App
    // resolves. A spinner here would flash for one frame and feel
    // worse than the current behavior.
    <Suspense fallback={null}>
      <App />
      <InstallPrompt />
    </Suspense>
  ),
);
```

### Section 3 — Verify no other static importer of App

```
grep -rn "from ['\"]./App['\"]" ui/src/
```

Should return only `main.tsx` (and possibly test files under `__tests__/`,
which are fine — Vitest does not run through the Vite production build).
If anything else under `ui/src/` (non-test) imports `App` statically, the
lazy boundary is defeated; flag and pause.

## What This Does NOT Change

- No production runtime code changes outside `main.tsx` and `vite.config.ts`.
- No new tests. No test refactoring. Existing Vitest suite (934 tests at
  HEAD) must pass unchanged.
- No change to `CompactApp` or `ProfileChatTab` (already three-free).
- No change to `App.tsx` itself or any of its descendants.
- No change to dev-server behavior. `npm run dev` continues to work; Vite
  dev-mode does not respect `manualChunks` (only production builds do).
- No InstallPrompt change — still inside the App-loaded branch since it's
  not needed in Compact mode.

## Tests

This is build hygiene; acceptance is build-output shape, not behavior.

**Required smoke:**

```powershell
cd ui
npm run build
```

Expected:
- Build succeeds with no errors.
- `ui/dist/assets/` contains at minimum:
  - `index-*.js`  (main entry — should be substantially smaller than 3290 KB)
  - `avatar-vendor-*.js`  (three + @pixiv/three-vrm)
  - `avatar-app-*.js`  (canvas/* + profile avatar components)
- Rollup's ">500 kB" warning should disappear for the main chunk. It may
  still appear for `avatar-vendor` (three.js itself is ~600 KB minified) —
  that's expected and acceptable; the point is to make it lazy, not to
  shrink three.js.

**Capture for the commit message:**

```powershell
Get-ChildItem ui/dist/assets/*.js | Select-Object Name, @{N='KB';E={[math]::Round($_.Length/1KB,1)}}
```

Include before/after table in the commit body.

**Vitest gate:**

```powershell
cd ui
npx vitest run
```

934 tests should still pass. No new tests required. The existing
`vi.mock('../components/profile/CrewVRM', ...)` mocks in the test suite are
unaffected — Vitest resolves modules through its own pipeline and does not
hit the production `manualChunks` config.

## Acceptance Criteria

1. `cd ui; npm run build` succeeds.
2. `ui/dist/assets/` contains separate `avatar-vendor-*.js` and
   `avatar-app-*.js` chunks.
3. Main `index-*.js` is measurably smaller than the 3290 KB baseline
   (target: under 1500 KB; exact number depends on what App pulls in
   besides three).
4. `cd ui; npx vitest run` — all 934 tests pass.
5. One commit, message body includes a before/after byte-count table,
   subject ends with `Closes #770`.
6. Engineering Principles per `.github/copilot-instructions.md` verified
   (no new public methods need type annotations; this is config + entry
   refactor only).

## Tracking

- `PROGRESS.md` — append a short Build-Hygiene entry under the appropriate
  era's progress file (likely `progress-era-5-unification.md` given current
  AD-826 era), citing issue #770 closed.
- `docs/development/roadmap.md` — no change (this is hygiene, not a
  roadmap item).
- No `DECISIONS.md` entry needed (build config, not architectural).

## Standing Constraints

- DO NOT touch the live runtime (`probos serve` instance). Build the UI
  only.
- DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`. All
  work is under `d:\ProbOS\ui\`.
- DO NOT add new dependencies.
- DO NOT enable sourcemaps "while you're in there." Out of scope.

## Verified Against Codebase Footer

```
grep -n "outDir" ui/vite.config.ts
  17:    outDir: 'dist',
grep -c "from 'three'" ui/src/canvas/scene.ts ui/src/components/CognitiveCanvas.tsx
  ui/src/canvas/scene.ts:1
  ui/src/components/CognitiveCanvas.tsx:1
grep -n "import App from" ui/src/main.tsx
  4:import App from './App';
grep -n "React\.lazy\|from 'react'" ui/src/main.tsx
  (no lazy usage; only react-dom/client import)
grep -rn "from ['\"]./App['\"]" ui/src/
  (Builder must rerun and confirm only main.tsx in non-test code)
```
