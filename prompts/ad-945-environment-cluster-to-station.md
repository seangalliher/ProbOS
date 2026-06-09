# AD-945 — Fold the bottom-right environment toggles into the Engineering station, remove the cluster (Bridge as Ship's Computer)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-945.** GitHub epic `seangalliher/ProbOS#873`; this issue `#880`.
**Mode:** Builder. Frontend only (UI). Commit local. **No push** (the Captain decides the push).
**Builds on:** AD-943 (commit `d373501b`) — the typed `CommandStation` model + registry; AD-944 (commit `6ddecf55`) —
toolbar retired, `BridgePanel` now renders `st.actions` alongside `st.body?.()` and `st.config`. **Epic siblings
(DO NOT build — awareness only):** `#881` AD-946 (Ship's-Computer command palette in the omnibox / `Ask ProbOS…`
pill).

## Goal
Relocate the four bottom-right environment toggles — **ambient sounds**, **voice output**, **wake-word**,
**visual legend** — out of `DecisionSurface.tsx` and into a single **Engineering** station `config` item
(`buildBridgeStations` / `BridgePanel`), then **REMOVE the cluster** (the four buttons + the volume slider + the
voice-picker dropdown + the now-orphaned flex spacer) from the bottom status bar. The bottom-left **status strip**
(`Live — N crew` / Health / mode / `TC_N` / Entropy / `VisionBudgetBadge`) **STAYS** — it is ambient ship
telemetry (Glass Bridge "status bar as ship's telemetry", HXI #6), not a menu. The **legend overlay** itself
(the bloom-color annotation) also STAYS in `DecisionSurface` — it is a canvas annotation driven by the
`showLegend` store flag; only its toggle button moves.

After this AD the canvas overlay chrome is reduced to the Captain's target end state: the **Bridge button** + the
**`Ask ProbOS…` pill** (AD-946) + the read-only bottom-left **status strip**.

## Why
The toggles are environment/system controls — they belong in the Ship's-Computer command surface (the Bridge),
not floating on the canvas. AD-943 built the typed `StationConfig` slot and AD-944 made `BridgePanel` render
`config`; the `Communications` station already demonstrates the pattern (`config: [{ id:'comms-admin', label:
'Communications', render: () => <BridgeCommunications /> }]`). AD-945 is the third wave: drop one `StationConfig`
onto `engineering`. The `stations.tsx` header comment already reserves this: *"AD-945 folds the bottom-right
toggles in."* This is a **relocation, not a rewrite** — the audio / VAD / wake-word / legend engines are
untouched; the same store actions fire with the same effects.

Reference: `docs/design/hxi-glass-bridge.md`; the 11 HXI Design Principles in `.github/copilot-instructions.md`
(esp. #3 no-emoji stroke-SVG glyphs, #6 the canvas IS the information).

---

## Verified current shape (grep evidence in the footer)

**All four toggles live in one flex row inside `DecisionSurface.tsx`** — they are NOT a separate cluster; they
share the status-bar `<div>` with the telemetry spans, pushed right by a `flex:1` spacer:

```
DecisionSurface return
└─ <div absolute bottom:0 …>                         (outer, zIndex:10, pointerEvents:none)
   ├─ <div status-bar flex gap:16 …>                 (glass strip, pointerEvents:auto)
   │   ├─ Live — N crew · Health · mode · TC_N · Entropy · <VisionBudgetBadge/>   ← STAYS (telemetry)
   │   ├─ <span style={{ flex: 1 }} />                ← DELETE (orphaned spacer)
   │   ├─ Sound toggle  (+ Volume slider)            ← MOVE
   │   ├─ Voice toggle  (+ Voice-picker dropdown)    ← MOVE
   │   ├─ Wake-word toggle [data-testid]             ← MOVE
   │   └─ Legend toggle                              ← MOVE
   └─ {showLegend && <div legend overlay …>}         ← STAYS (canvas annotation, reads showLegend)
```

**Each toggle → its exact store flag + action** (all in `ui/src/store/useStore.ts`, all preserved verbatim):

| Toggle (off-state `title`) | `data-testid` | Reads | Writes (action) | Side effects in the setter |
|---|---|---|---|---|
| `Enable ambient sounds` | — | `soundEnabled` | `setSoundEnabled` | `localStorage hxi_sound_enabled`; `soundEngine.init()` (lazy) + `soundEngine.setMuted(!v)` |
| `Enable voice output` | — | `voiceEnabled` | `setVoiceEnabled` | `localStorage hxi_voice_enabled` |
| `Enable wake-word listening ("Computer…")` | `wake-word-toggle` | `wakeWordEnabled` | `setWakeWordEnabled` | `localStorage hxi_wake_word_enabled` (try/catch) |
| `Toggle visual legend` (static title) | — | `showLegend` | `setShowLegend` | none (`set({ showLegend: v })`) |

Right-click affordances ride along: the **sound** button's `onContextMenu` opens the **volume slider**
(`soundEngine.setVolume`); the **voice** button's `onContextMenu` opens the **voice-picker dropdown**
(`getAvailableVoices` / `setPreferredVoiceName` / `getCurrentVoiceName` / `speakResponse`). Only the wake-word and
legend buttons have no context menu.

**Wake-word single-owner lifecycle is NOT here — leave it alone.** The arming/disarming loop is owned by
`IntentSurface.tsx` (AD-705): it subscribes `wakeWordEnabled` and runs `startWakeWordLoop` / `stopWakeWordLoop`
in an effect keyed `[wakeWordEnabled, agentsMap]`. The relocated toggle keeps flipping the **same**
`wakeWordEnabled` flag via `setWakeWordEnabled` — `IntentSurface`'s effect reacts. **Do NOT add a second owner or
duplicate the loop.** The `<WakeWordIndicator />` (the listening-state dot) is also rendered by
`IntentSurface.tsx` (driven by `getWakeWordState`/`onWakeWordState` from `audio/wakeWord`) — it is **separate
from this cluster and does NOT move.**

**`BridgePanel` renders `config` (post-AD-944):** the registry map draws `{st.actions.map(...)}` →
`{st.body?.()}` → `{st.config.map(c => <div key={c.id}>{c.render()}</div>)}`. `BridgeSection` renders its
children only when the section is expanded. `isPopulated(engineering)` is already `true` (it has a `body` —
`<BridgeSystem />`), so adding a `config` entry needs **no `isPopulated` change**.

---

## Design decision (documented)

**Which station:** **Engineering** (`#70a0d0`). It is the ship-subsystems / "is-the-machinery-online" station —
environment/sensory controls (ambient sound, voice, wake-word, legend) are the room-level system controls and
read naturally there. It already owns the `<BridgeSystem />` body, so the config nests under the same
"Engineering" header. (Considered: a dedicated `operations` placement — rejected; operations is the
mission/task pipeline. Considered "Sensory" as the config label — `Environment` is broader and matches the
epic's primary proposal.)

**How the toggles render:** **ONE** `StationConfig` — `{ id: 'environment', label: 'Environment', render: () =>
<BridgeEnvironment /> }` — rendering a NEW component `ui/src/components/bridge/BridgeEnvironment.tsx` that draws
all four toggles as a small vertical group. This mirrors the `BridgeCommunications` precedent (one config → one
panel component) and is cleaner than four separate `StationConfig` entries, because two of the toggles carry
companion sub-UIs (the volume slider, the voice picker) that belong grouped with their button. Stroke-SVG glyphs
only, **NO emoji** (HXI #3); active state amber `#f0b060` (the existing glyphs already use `#ffcc66` active /
`#8888aa` inactive — preserve them byte-for-byte).

---

## Section 1 — NEW FILE: `ui/src/components/bridge/BridgeEnvironment.tsx`

Create the component that the Engineering `config` renders. It **owns** the four toggles and their companion
sub-UIs, relocated from `DecisionSurface.tsx`. This is a **move with a layout adaptation**, not a rewrite.

**1a. Imports** (note the `bridge/` depth — `../../` to `store`/`audio`, `../` to `icons`; mirror
`BridgeCommunications.tsx:1`):
```tsx
import { useState, useEffect, useRef } from 'react';
import { useStore } from '../../store/useStore';
import { soundEngine } from '../../audio/soundEngine';
import { Sparkle, StatusPending } from '../icons/Glyphs';
import { getAvailableVoices, setPreferredVoiceName, getCurrentVoiceName, speakResponse } from '../../audio/voice';
```

**1b. State + selectors** — move these verbatim out of `DecisionSurface` (selectors
`DecisionSurface.tsx:15`–`24`, local state `:26`–`30`, the two voice-picker `useEffect`s `:32`–`47`):
- selectors: `showLegend` + `setShowLegend`, `soundEnabled` + `setSoundEnabled`, `voiceEnabled` +
  `setVoiceEnabled`, `wakeWordEnabled` + `setWakeWordEnabled`.
- local state: `showVolume`, `volume` (seeded `soundEngine.volume`), `showVoicePicker`, `availableVoices`,
  `voicePickerRef`.
- the two `useEffect`s that (i) populate `availableVoices` when `showVoicePicker` opens and (ii) attach the
  outside-mousedown handler that closes the picker.
- the `btnStyle(active)` helper (`DecisionSurface.tsx:64`–`70`) — move it here verbatim (it is unused in
  `DecisionSurface` once the toggles leave).

**1c. Render** — a vertical group (suited to the 380px Bridge panel, dark glass), one labeled row per toggle.
**Preserve EXACTLY, byte-for-byte, from `DecisionSurface.tsx`:**
- the **sound** `<button>` (`:131`–`150`): its `onClick={() => setSoundEnabled(!soundEnabled)}`,
  `onContextMenu` (→ `setShowVolume`), the dynamic `title` (`Mute ambient sounds (right-click: volume)` /
  `Enable ambient sounds`), and **both** inline speaker SVGs (on/off).
- the **voice** `<button>` (`:171`–`182`): `onClick={() => setVoiceEnabled(!voiceEnabled)}`, `onContextMenu`
  (→ `setShowVoicePicker`), the dynamic `title`, the equalizer SVG.
- the **wake-word** `<button>` (`:184`–`214`): **keep `data-testid="wake-word-toggle"`**, the
  `onClick={() => setWakeWordEnabled(!wakeWordEnabled)}`, the dynamic `title`
  (`Enable wake-word listening ("Computer…")` …), and the concentric-arc SVG (`strokeWidth="1.5"`).
- the **legend** `<button>` (`:265`–`274`): `onClick={() => setShowLegend(!showLegend)}`,
  `title="Toggle visual legend"`, the circle+dot SVG.
- the **volume** `<input type="range">` (`:152`–`169`) — render conditionally on `showVolume`, same
  `onChange` (`setVolume` + `soundEngine.setVolume`).
- the **voice-picker dropdown** (`:216`–`262`) — same list of `availableVoices`, same `onClick`
  (`setPreferredVoiceName` + conditional `speakResponse`), same `Sparkle`/`StatusPending` markers.

**ADAPT ONLY the layout (the engines are untouched):**
- Wrap the four rows in a vertical container styled like `BridgeCommunications`' `sectionStyle`/`labelStyle`
  idiom; a section label `Environment` (uppercase mono, `#8888a0`) reads cleanly at the top.
- **Re-anchor the companion sub-UIs to the panel flow.** The voice-picker dropdown currently uses
  `position:absolute; bottom:40; right:60` (anchored to the old status bar) — that is WRONG inside the
  scrollable 380px panel. Render the picker **inline** (relative, directly under the voice row) and the volume
  slider **inline** (under the sound row). Keep the `voicePickerRef` outside-click-close behavior. Do **not**
  change the voice-selection logic.
- **Recommended (additive panel chrome, optional):** a short text label next to each glyph
  (`Ambient sound` / `Voice output` / `Wake-word` / `Visual legend`) so the roomy panel reads better than the
  icon-only status bar. The dynamic `title` attributes are preserved regardless (aria-label contract intact).

> `BridgeEnvironment` reads + writes the same store flags the canvas already binds; no new store field, no engine
> change. `soundEngine` / `voice` are imported here now instead of in `DecisionSurface`.

---

## Section 2 — MODIFY: `ui/src/components/bridge/stations.tsx` — wire the Engineering config

**2a. Import the new component** (after the `BridgeCommunications` import at `:11`):
```
SEARCH:
import { BridgeCommunications } from './BridgeCommunications';

REPLACE:
import { BridgeCommunications } from './BridgeCommunications';
import { BridgeEnvironment } from './BridgeEnvironment';
```

**2b. Add the `environment` config to the Engineering station** (the `body: () => <BridgeSystem />` block is the
unique anchor — `operations` also has `config: []` but no `<BridgeSystem />` body):
```
SEARCH:
      onExpand: () => useStore.setState({ mainViewer: 'system' }),
      body: () => <BridgeSystem />,
      actions: [],
      config: [],
    },

REPLACE:
      onExpand: () => useStore.setState({ mainViewer: 'system' }),
      body: () => <BridgeSystem />,
      actions: [],
      // AD-945: the four bottom-right environment toggles (sound / voice / wake-word /
      // legend), relocated from DecisionSurface into the Ship's-Computer command layer.
      config: [
        { id: 'environment', label: 'Environment', render: () => <BridgeEnvironment /> },
      ],
    },
```
> `isPopulated(engineering)` was already `true` (it has a `body`); the config entry keeps it populated. No
> `isPopulated` edit. The factory `ctx` is unchanged (these toggles read the store directly, not `ctx`).

---

## Section 3 — MODIFY: `ui/src/components/DecisionSurface.tsx` — remove the cluster, keep the strip + overlay

**3a. Delete the relocated cluster.** Remove the contiguous JSX from the **`{/* Spacer */}` comment + the
`flex:1` span** (`:127`–`128`) through the **Legend toggle's closing `</button>`** (`:274`) — i.e. the spacer +
Sound toggle + Volume slider + Voice toggle + Wake-word toggle + Voice-picker dropdown + Legend toggle. This is
everything between `<VisionBudgetBadge />` (`:125`, KEEP) and the status-bar closing `</div>` (`:275`, KEEP).
After the edit the status-bar `<div>` contains only the telemetry spans and closes; the telemetry stays
left-aligned (the spacer was its only right-pusher).

**KEEP unchanged:** the outer `<div>`, the status-bar `<div>` + all telemetry spans (`Live — N crew`, Health,
mode, `TC_N`, Entropy, `<VisionBudgetBadge />`), **and the entire Legend overlay block**
(`{showLegend && (…)}` at `:278`+ — it reads `showLegend` and renders the bloom-color annotation; the relocated
legend toggle still flips that flag).

**3b. Drop the now-unused symbols** (verify with `npm run build` — `tsc` flags any miss):
- selectors no longer used here: `setShowLegend`, `soundEnabled`, `setSoundEnabled`, `voiceEnabled`,
  `setVoiceEnabled`, `wakeWordEnabled`, `setWakeWordEnabled`. **KEEP `showLegend`** (the overlay reads it).
- local state + refs: `showVolume`, `volume`, `showVoicePicker`, `availableVoices`, `voicePickerRef`, and the
  two voice-picker `useEffect`s.
- the `btnStyle` helper (now lives in `BridgeEnvironment`).
- imports: remove `import { soundEngine } from '../audio/soundEngine';` and
  `import { getAvailableVoices, setPreferredVoiceName, getCurrentVoiceName, speakResponse } from '../audio/voice';`.
  **KEEP** `import { Sparkle, StatusPending, StatusDone } from './icons/Glyphs';` (the legend overlay uses all
  three) and `import { VisionBudgetBadge } from './perception/VisionBudgetBadge';`. `useState`/`useEffect`/`useRef`
  from `react` are no longer needed in `DecisionSurface` after the picker state leaves — verify and trim the
  `react` import to what remains (likely none of the three).

> `DecisionSurface` keeps: `agents`, `systemMode`, `tcN`, `routingEntropy`, `connected`, `showLegend`, the
> `crewAgents`/`avgHealth`/`modeColor`/`healthColor` derivations, the status strip, and the legend overlay.

---

## Section 4 — UPDATE tests: re-home the wake-word test, add BridgeEnvironment cases

The only test that renders the moved toggle is
`ui/src/__tests__/DecisionSurface.wakeWordToggle.test.tsx` — it renders `<DecisionSurface />` and queries
`[data-testid="wake-word-toggle"]` (`:37`/`:39`, `:54`/`:56`). After the move that button is no longer in
`DecisionSurface`, so the query returns `null` and both cases fail. Re-point it to the new component and extend
it. (No e2e spec and no other unit references these toggles — `useMeetingVoice.test.tsx` sets `voiceEnabled` via
`useStore.setState`, i.e. it reads the store flag directly, **unaffected**.)

**4a. Rename the file** `ui/src/__tests__/DecisionSurface.wakeWordToggle.test.tsx` →
`ui/src/__tests__/BridgeEnvironment.test.tsx`. **Keep it in `src/__tests__/`** so the existing
`vi.mock('../audio/soundEngine')` / `vi.mock('../audio/voice')` paths still resolve to the SAME modules
`BridgeEnvironment` imports (vitest mocks by resolved module id — the `../../audio/…` specifier in the component
resolves to the same `src/audio/…` module the test mocks). Use `git mv` so history follows.

**4b. Re-point import + renders:**
```
SEARCH:
import { DecisionSurface } from '../components/DecisionSurface';

REPLACE:
import { BridgeEnvironment } from '../components/bridge/BridgeEnvironment';
```
Replace both `render(<DecisionSurface />)` with `render(<BridgeEnvironment />)`, and update the top `describe`
label to `BridgeEnvironment toggles (AD-945, was AD-705 D5)`. The two existing cases (toggle persists via
`hxi_wake_word_enabled`; default `false` → `#8888aa` stroke) keep their bodies verbatim.

**4c. Add four BridgeEnvironment cases** in the same file (the soundEngine + voice mocks are already set up;
`beforeEach` already `localStorage.clear()` + resets `wakeWordEnabled` — also reset `soundEnabled`,
`voiceEnabled`, `showLegend` to `false` so the OFF-state `title`s resolve):
- **Sound:** click `container.querySelector('[title="Enable ambient sounds"]')` → assert
  `useStore.getState().soundEnabled === true` and `localStorage.getItem('hxi_sound_enabled') === '1'`.
- **Voice:** click `[title="Enable voice output"]` → assert `voiceEnabled === true` and
  `localStorage.getItem('hxi_voice_enabled') === '1'`.
- **Legend:** click `[title="Toggle visual legend"]` → assert `useStore.getState().showLegend === true`.
- **No emoji (HXI #3):** render `<BridgeEnvironment />`, assert
  `/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(container.textContent ?? '') === false` (mirror the AD-943/944
  no-emoji assertion).

> Query the unlabeled buttons by their OFF-state `title` (set in `beforeEach`). The wake-word button keeps its
> `data-testid` query.

---

## Gates
- `cd d:\ProbOS\ui; npx vitest run` → green. **Baseline after AD-944 = 1340 passed / 1 skipped (225 files) — run
  this FIRST to confirm the baseline before editing.** AD-945 retains the 2 wake-word cases (re-homed) and adds
  ~4 BridgeEnvironment cases, so expect **≥ 1344 passed / 1 skipped, zero regressions.** Report the exact pass +
  file count.
- `cd d:\ProbOS\ui; npm run build` → clean (`tsc -b` + `vite`). **No unused-import / unused-symbol drift** after
  the `DecisionSurface` deletion (3b) — `tsc` is the check that the trim is complete.
- `cd d:\ProbOS\ui; npx playwright test` → green. The four AD-941 specs drive panels through the DEV
  `window.__store` seam and never touch these toggles, so they are **expected unaffected** — run them to confirm.
  (Requires `vite dev` on :5173 per the AD-941 harness.)
- No backend change → **no pytest.**

## Acceptance
- The four toggle buttons + the volume slider + the voice-picker dropdown + the orphaned `flex:1` spacer are
  **gone** from `DecisionSurface.tsx`'s status bar. The bottom-left **status strip** (telemetry) renders
  unchanged and stays left-aligned; the **legend overlay** still renders when `showLegend` is on.
- A new `ui/src/components/bridge/BridgeEnvironment.tsx` renders the four toggles (stroke-SVG, no emoji, amber
  `#f0b060`/`#ffcc66` active) as one `Environment` config group, reachable via **Bridge → Engineering →
  Environment**. Each toggle fires the **same** store action with the **same** side effects (sound:
  `setSoundEnabled` + `soundEngine`; voice: `setVoiceEnabled` + picker; wake-word: `setWakeWordEnabled`; legend:
  `setShowLegend`). The wake-word toggle keeps `data-testid="wake-word-toggle"` and flips the **same**
  `wakeWordEnabled` flag that `IntentSurface`'s AD-705 loop owns — **no second owner**.
- `engineering`'s `config` carries `{ id:'environment', … }`; `isPopulated` unchanged; the factory `ctx`
  unchanged.
- Gates green (Vitest ≥ 1344/1, build clean, Playwright green).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Do NOT build (scope fence)
- **Do NOT touch the omnibox / `Ask ProbOS…` pill / add a command palette** — that is **AD-946**.
- **Do NOT remove or move the Bridge open/close button** or the **bottom-left status strip** (telemetry) — the
  strip STAYS (it is ship telemetry, not a menu).
- **Do NOT alter the audio / STT / TTS / VAD / wake-word / legend engines** — `audio/soundEngine`, `audio/voice`,
  `audio/wakeWord`, `startWakeWordLoop`/`stopWakeWordLoop`, the legend overlay's content. This is a **relocation**:
  same store actions, same effects.
- **Do NOT introduce a second wake-word owner** or duplicate `startWakeWordLoop`/`stopWakeWordLoop` — the single
  owner is `IntentSurface.tsx`; the relocated toggle only flips `wakeWordEnabled`.
- **Do NOT move `<WakeWordIndicator />`** — it is rendered by `IntentSurface.tsx`, separate from this cluster.
- **Do NOT change `engineering`'s `body`/`onExpand`/`count`/`accent`** or any other station — only add the
  `environment` config item.
- **Do NOT** change the store flags, setters, defaults, or localStorage keys; **do NOT** flip any `defaultOpen`.
- No backend / REST / FastAPI / pytest. No push. Stage explicit paths (NOT `git add -A`); deletion-audit before
  commit.

## Trackers (after gates green — match where AD-944 went)
- `docs/development/roadmap.md`: AD-945 row — SHIPPED + date + gate note; tag the epic (`#873`) / issue (`#880`).
- `PROGRESS.md`: prepend an AD-945 block (cluster relocated → Engineering `Environment` config; the four
  toggle→action preserves; the `DecisionSurface` trim; the Vitest delta + suite count).
- `DECISIONS.md` (match where AD-944 went): AD-945 entry — Engineering placement rationale, the single-config
  render decision, the wake-word single-owner preservation, the status-strip/legend-overlay STAY decision.

---

## Verified Against Codebase (2026-06-09)
```
PROGRESS.md:3                          "AD-944 shipped (2026-06-09 …)" → current highest AD = AD-944
DecisionSurface.tsx:10                 export function DecisionSurface()
DecisionSurface.tsx:15-24              selectors: showLegend/setShowLegend, soundEnabled/setSoundEnabled, voiceEnabled/setVoiceEnabled, wakeWordEnabled/setWakeWordEnabled
DecisionSurface.tsx:64-70              btnStyle(active) helper (only the 4 toggles use it)
DecisionSurface.tsx:125                <VisionBudgetBadge /> (last telemetry item — KEEP)
DecisionSurface.tsx:127-128            {/* Spacer */} + <span style={{ flex: 1 }} />  (deletion-span start)
DecisionSurface.tsx:130-150            Sound toggle button (onClick setSoundEnabled; title "Enable ambient sounds"; speaker SVG)
DecisionSurface.tsx:151-169            Volume slider <input type=range> (soundEngine.setVolume)
DecisionSurface.tsx:170-182            Voice toggle button (onClick setVoiceEnabled; title "Enable voice output")
DecisionSurface.tsx:184-214            Wake-word toggle button — data-testid="wake-word-toggle"; onClick setWakeWordEnabled
DecisionSurface.tsx:216-262            Voice-picker dropdown (position:absolute bottom:40 right:60 — re-anchor inline on move)
DecisionSurface.tsx:265-274            Legend toggle button (onClick setShowLegend; title "Toggle visual legend")  (deletion-span end)
DecisionSurface.tsx:278+               {showLegend && <div legend overlay …>}  (KEEP — uses StatusDone/StatusPending/Sparkle)
useStore.ts:436,453,454,457            interface: showLegend / soundEnabled / voiceEnabled / wakeWordEnabled (booleans)
useStore.ts:920,929,930,932-940        defaults: showLegend false; soundEnabled false; voiceEnabled false; wakeWordEnabled ← localStorage hxi_wake_word_enabled
useStore.ts:1605                        setShowLegend: (v) => set({ showLegend: v })
useStore.ts:1632-1636                  setSoundEnabled: set + localStorage hxi_sound_enabled + soundEngine.init()/setMuted(!v)
useStore.ts:1638-1640                  setVoiceEnabled: set + localStorage hxi_voice_enabled
useStore.ts:1642-1651                  setWakeWordEnabled: set + try localStorage hxi_wake_word_enabled
IntentSurface.tsx:17-19,88,183,234-239 AD-705 single owner: imports start/stopWakeWordLoop; effect on [wakeWordEnabled, agentsMap]
IntentSurface.tsx:820                  <WakeWordIndicator /> rendered here (separate — does NOT move)
WakeWordIndicator.tsx:1-46             driven by getWakeWordState/onWakeWordState from ../audio/wakeWord (not the cluster)
bridge/stations.tsx:11                 import { BridgeCommunications } from './BridgeCommunications';  (add BridgeEnvironment after)
bridge/stations.tsx:30                 "AD-945 folds the bottom-right toggles in."  (StationConfig comment)
bridge/stations.tsx:95                 config precedent: { id:'comms-admin', label:'Communications', render: () => <BridgeCommunications /> }
bridge/stations.tsx:138-148            engineering: count:0, onExpand mainViewer:'system', body <BridgeSystem/>, actions:[], config:[]
bridge/stations.tsx (isPopulated)      returns true when body present → engineering already populated, no edit
BridgePanel.tsx:~233-238               registry map renders {st.actions} → {st.body?.()} → {st.config.map(c => <div>{c.render()}</div>)}
BridgeCommunications.tsx:1             import { useStore } from '../../store/useStore'  (bridge/ depth = ../../ for store/audio, ../ for icons)
__tests__/DecisionSurface.wakeWordToggle.test.tsx:23,37,39,54,56  renders <DecisionSurface/>, queries [data-testid="wake-word-toggle"] — re-point to <BridgeEnvironment/>
audio/__tests__/useMeetingVoice.test.tsx:30-71  sets voiceEnabled via useStore.setState (reads store flag directly — UNAFFECTED)
ui/e2e/**                              no spec references ambient/wake/legend/voice/sound/DecisionSurface — 4 Playwright specs unaffected
```
