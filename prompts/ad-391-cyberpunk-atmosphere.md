# AD-391: Cyberpunk Atmosphere Layer

## Overview

Add opt-in cyberpunk atmosphere effects to the glass layer: configurable scan
lines, chromatic aberration, data rain overlay (Ctrl+Shift+D toggle), luminance
ripple transitions on state changes, and new sound engine cues for DAG completion
and bridge state ambience. All visual effects are **off by default** — the
cyberpunk soul comes from the color palette, typography, and spatial design, not
CRT simulation. Let the user dial them up if they want the full aesthetic.

This is Phase 4 of the Glass Bridge. Builds on AD-388 (GlassLayer), AD-389
(DAG nodes), AD-390 (ambient intelligence). Full design spec:
`docs/design/hxi-glass-bridge.md`.

## Architecture

### Store Changes — Atmosphere Preferences

Add four new fields to the `HXIState` interface in `ui/src/store/useStore.ts`:

```ts
// Atmosphere preferences (AD-391)
scanLinesEnabled: boolean;        // default false
chromaticAberrationEnabled: boolean;  // default false
dataRainEnabled: boolean;         // default false, toggled with Ctrl+Shift+D
atmosphereIntensity: number;      // 0-1 scale, default 0.3 (subtle)

// Actions
setScanLinesEnabled: (v: boolean) => void;
setChromaticAberrationEnabled: (v: boolean) => void;
setDataRainEnabled: (v: boolean) => void;
setAtmosphereIntensity: (v: number) => void;
```

**Persistence:** Save all four to `localStorage` under key `hxi_atmosphere_prefs`
(JSON object). Restore on store creation. Pattern: same as existing `soundEnabled`
persistence but as a single JSON blob.

### New Component: ScanLineOverlay

Create `ui/src/components/glass/ScanLineOverlay.tsx` — a CSS-only scan line
effect rendered as a full-size absolute div inside the glass layer.

**Implementation:**
- `pointer-events: none`, `position: absolute`, `inset: 0`
- A repeating linear-gradient: `repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0, 0, 0, 0.03) 2px, rgba(0, 0, 0, 0.03) 4px)`
- Opacity scales with `atmosphereIntensity` (0→0, 1→0.8)
- Optional: a very slow vertical scroll animation (CSS `translateY` from 0 to 4px
  over 8s, looping) to simulate CRT refresh
- Only renders when `scanLinesEnabled === true`
- Accepts `intensity: number` prop (0-1)

### New Component: DataRainOverlay

Create `ui/src/components/glass/DataRainOverlay.tsx` — matrix-style falling
characters using a canvas element.

**Implementation:**
- Full-size `<canvas>` element, `pointer-events: none`, `position: absolute`
- Characters: hex digits and unicode block elements (`0-9`, `A-F`, `█`, `▓`, `▒`)
- Color: use the current bridge state color (cyan for idle, gold for autonomous,
  amber for attention) at low opacity (0.15-0.25)
- Columns: one character every ~14px across the width
- Fall speed: staggered, 30-60px/s per column, randomized starting positions
- Rendering: use `requestAnimationFrame` loop, draw characters with
  `JetBrains Mono` at 10px
- Fade: each character fades as it falls (top = full opacity, bottom = 0)
- Intensity: `atmosphereIntensity` controls character opacity and column density
- Clean up `requestAnimationFrame` on unmount
- Only renders when `dataRainEnabled === true`
- Accepts `intensity: number` and `stateColor: string` props

### Chromatic Aberration

Add a CSS filter effect to the glass layer container. This is NOT a separate
component — it's applied directly on the GlassLayer `<div>`.

**Implementation:**
- When `chromaticAberrationEnabled === true`, add a subtle RGB channel offset
  using a CSS `filter: url(#chromatic-aberration)` referencing an inline SVG filter
- The SVG filter uses `feColorMatrix` and `feOffset` to shift red and blue
  channels by 0.5-1px in opposite directions
- Intensity scales with `atmosphereIntensity` (0→0px offset, 1→1.5px)
- Add the SVG filter definition as a hidden `<svg>` inside the GlassLayer
- If the SVG filter approach is too complex, a simpler alternative: duplicate the
  noise texture overlay with red-tinted and blue-tinted versions offset by 0.5px
  each direction. The key: the effect should be barely perceptible at low intensity.

### Luminance Ripple Transitions

Add a brief directional luminance sweep when bridgeState changes. This is the
"the system shifted" signal.

**Implementation:**
- Track previous `bridgeState` via `useRef<BridgeState>` in GlassLayer
- When bridgeState changes, set a `rippleActive` state to `true` for 80ms
- The ripple: a pseudo-gradient overlay that sweeps left-to-right in 80ms
  (`linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0.04) 50%, rgba(255,255,255,0) 100%)`)
  animated with a CSS transform (`translateX(-100%) → translateX(100%)`) over 80ms
- The ripple is always active (not gated by atmosphere preferences) — it's a
  functional signal, not an aesthetic choice
- Use CSS `@keyframes` for the sweep animation
- After 80ms, remove the ripple div

### Sound Design Enhancements

Add three new methods to `ui/src/audio/soundEngine.ts`:

**1. `playStepComplete(stepIndex: number, totalSteps: number)`**
- Ascending chime that builds a chord across DAG steps
- Base note: C5 (523 Hz). Each step advances by a major third interval
- `frequency = 523 * Math.pow(2, (stepIndex * 4) / (12 * totalSteps))`
- Short duration: 200ms, soft volume (0.08 gain)
- When `stepIndex === totalSteps - 1` (final step), play the chord resolution:
  all accumulated notes together for 400ms (the "completion chord")

**2. `playBridgeHum(state: 'idle' | 'autonomous' | 'attention')`**
- Ambient background hum that reflects bridge state
- `idle`: barely audible drone at 55Hz, 0.02 gain (engine room hum)
- `autonomous`: warm 80Hz + 120Hz layered, 0.04 gain
- `attention`: slightly tense 65Hz + 98Hz (minor interval), 0.05 gain
- Continuous tone using `OscillatorNode` — store reference to stop/transition
- Cross-fade between states over 2s when state changes
- Store active oscillators as class properties (like existing `dreamDrone`)

**3. `playCaptainReturn()`**
- Brief welcoming tone when Captain returns after absence
- Two ascending notes: E5 (659Hz) → G5 (784Hz), 150ms each, 60ms gap
- Warm sine wave, 0.1 gain, 300ms total
- Called from GlassLayer when briefing card appears

### Keyboard Shortcut: Ctrl+Shift+D

Add a global keyboard listener in GlassLayer for the data rain toggle:

```ts
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'D') {
      e.preventDefault();
      useStore.getState().setDataRainEnabled(!useStore.getState().dataRainEnabled);
    }
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, []);
```

### GlassLayer Integration

Modify `ui/src/components/GlassLayer.tsx` to integrate all atmosphere effects:

1. Read atmosphere preferences from store: `scanLinesEnabled`, `chromaticAberrationEnabled`,
   `dataRainEnabled`, `atmosphereIntensity`
2. Add luminance ripple tracking (`prevBridgeStateRef`, `rippleActive`)
3. Render new overlays inside the glass layer div (after noise texture, before task cards):
   - `{scanLinesEnabled && <ScanLineOverlay intensity={atmosphereIntensity} />}`
   - `{dataRainEnabled && <DataRainOverlay intensity={atmosphereIntensity} stateColor={STATE_COLORS[bridgeState]} />}`
4. Apply chromatic aberration filter on the glass layer div when enabled
5. Render ripple overlay when `rippleActive` is true
6. Add Ctrl+Shift+D keyboard listener
7. Add the SVG filter definition (hidden) for chromatic aberration
8. Call `soundEngine.playCaptainReturn()` when briefing card appears (if sound enabled)

**Import the bridge state colors from ContextRibbon** — the `STATE_COLORS` record
is not currently exported. Export it from `ContextRibbon.tsx` so DataRainOverlay
can use bridge state colors.

## File Plan

| Action | File | Description |
|--------|------|-------------|
| CREATE | `ui/src/components/glass/ScanLineOverlay.tsx` | CSS scan line effect |
| CREATE | `ui/src/components/glass/DataRainOverlay.tsx` | Canvas-based falling hex characters |
| MODIFY | `ui/src/components/glass/ContextRibbon.tsx` | Export `STATE_COLORS` record |
| MODIFY | `ui/src/components/GlassLayer.tsx` | Integrate atmosphere overlays, ripple, chromatic aberration, Ctrl+Shift+D, captain return sound |
| MODIFY | `ui/src/audio/soundEngine.ts` | Add `playStepComplete`, `playBridgeHum`, `playCaptainReturn` |
| MODIFY | `ui/src/store/useStore.ts` | Add atmosphere preference fields + persistence |
| CREATE | `ui/src/__tests__/GlassAtmosphere.test.tsx` | Tests for atmosphere logic |

## Acceptance Criteria

1. Scan lines render as horizontal stripes when enabled, intensity-adjustable (0-1)
2. Chromatic aberration applies subtle RGB channel offset when enabled
3. Data rain renders falling hex characters colored by bridge state
4. Ctrl+Shift+D toggles data rain on/off
5. All three visual effects are OFF by default
6. Luminance ripple sweeps left-to-right on bridge state changes (always on, 80ms)
7. `atmosphereIntensity` controls visual effect strength for all three effects
8. Atmosphere preferences persist to localStorage across sessions
9. `playStepComplete` produces ascending tones that build a chord
10. `playCaptainReturn` plays a welcoming two-note chime
11. Sound cues only play when `soundEnabled === true`
12. Glass layer still renders correctly with all effects off (zero visual change from AD-390)
13. All `requestAnimationFrame` and event listeners properly cleaned up on unmount

## Test Requirements

Create `ui/src/__tests__/GlassAtmosphere.test.tsx`:

1. **Atmosphere defaults** — all three effects default to false, intensity defaults to 0.3
2. **Atmosphere persistence** — settings round-trip through localStorage
3. **Toggle setters** — `setScanLinesEnabled`, `setChromaticAberrationEnabled`, `setDataRainEnabled` update store correctly
4. **Intensity clamping** — `setAtmosphereIntensity` clamps to 0-1 range
5. **Ripple detection** — bridge state change triggers a ripple (test the ref-tracking logic, similar to celebration detection test pattern)
6. **Sound engine has new methods** — `playStepComplete`, `playCaptainReturn` exist as functions (no AudioContext mocking needed, just verify they don't throw when called without init)

## Do NOT Build

- **Do NOT** add trust-driven card sizing or Command Surface breathing — that is AD-392
- **Do NOT** add Captain's Gaze attention weighting — that is AD-392
- **Do NOT** modify CognitiveCanvas, IntentSurface, or BridgePanel
- **Do NOT** add new WebSocket events or backend endpoints
- **Do NOT** add a settings panel UI for atmosphere controls — that is a future AD.
  The preferences are set via store actions (and Ctrl+Shift+D for data rain).
  A settings panel will come later.
- **Do NOT** use emoji anywhere in the UI
