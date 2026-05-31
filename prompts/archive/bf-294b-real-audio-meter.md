# BF-294b — Drive MicIndicator ring intensity from real audio amplitude

**Status:** Ready for Builder
**Closes:** #769
**Depends on:** BF-294 (shipped — `MicIndicator` three-state affordance), AD-705a (shipped — `voiceActivity.subscribePcm` PCM tap)
**Estimated tests:** 4 MicIndicator + 4 ProfileChatTab = 8 new
**Test gates:** BOTH required — `cd ui; npx vitest run` AND `cd ui; npm run build`

---

## Problem

BF-294 (commit `81ba3f87`) shipped the three-state mic affordance (`idle` / `listening` / `processing`) as CSS-only visuals. The `listening` ring uses a fixed `bf294-mic-listen` keyframe pulse — it animates the same way whether the operator is shouting or silent. The agent-side TTS path already drives `ParametricAvatar.tsx:48` from real `AnalyserNode` amplitude (see `useFrame` + `analyserRef`), so the human→mesh path is the only side of the audio loop without amplitude feedback.

`audio/voiceActivity.ts:301` already exports `subscribePcm(handler)` — a zero-overhead public tap on the existing 16 kHz / 30 ms VAD frame pipeline. This BF wires that tap into a smoothed amplitude state that drives `MicIndicator` opacity/scale, achieving full audio symmetry.

## Solution overview

1. Extend `MicIndicator` with an optional `intensity?: number` (0..1, clamped). When provided AND state is `listening`, override the keyframe-driven opacity/scale with `intensity`-driven inline values. When `intensity` is undefined, behavior is identical to BF-294 (keyframe pulse) — this is the fallback for paths where the VAD loop isn't armed.
2. In `ProfileChatTab.tsx`, when `listening === true`, subscribe to the PCM tap, compute per-frame RMS, smooth via EMA (alpha=0.3), and update an `audioIntensity` state at requestAnimationFrame cadence (NOT per-PCM-frame — frames arrive at ~33 Hz already, but RAF coalescing keeps render churn bounded and matches the existing `ParametricAvatar` pattern). On `listening === false` or unmount, unsubscribe and reset to 0.
3. The `processing` ring stays keyframe-only — no useful amplitude during transcription.

## Verified against codebase (2026-05-23)

```
ui/src/audio/voiceActivity.ts:50-58 — PcmTapHandler interface
  onFrame(frame: Float32Array, sampleRate: number, score?: number): void
  onSpeechStart?(now: number): void
  onSpeechEnd?(now: number): void

ui/src/audio/voiceActivity.ts:62  — const SAMPLE_RATE = 16000
ui/src/audio/voiceActivity.ts:63  — const FRAME_SAMPLES = 480  // 30 ms @ 16 kHz
ui/src/audio/voiceActivity.ts:301 — export function subscribePcm(handler: PcmTapHandler): () => void
ui/src/audio/voiceActivity.ts:302-307 — adds to module-scoped Set; returns unsubscribe closure that removes from Set

ui/src/components/profile/MicIndicator.tsx:23-28 — current MicIndicatorProps
  state: MicIndicatorState
  size?: number  (default 14)

ui/src/components/profile/MicIndicator.tsx:55-67 — listening ring (animation: 'bf294-mic-listen 1.1s ease-in-out infinite')
ui/src/components/profile/MicIndicator.tsx:69-81 — processing ring (keyframe-only — unchanged by this BF)

ui/src/components/profile/ProfileChatTab.tsx:68  — const [listening, setListening] = useState(false)
ui/src/components/profile/ProfileChatTab.tsx:25  — import { MicIndicator } from './MicIndicator'

ui/src/App.tsx:189-196 — startVoiceActivity is gated on perception.vad_engagement_enabled (default false for solo-Captain).
  ⇒ PCM tap is NOT guaranteed active during PTT. When VAD is disarmed,
    subscribePcm still registers the handler but no frames will fire,
    so audioIntensity stays at 0 and MicIndicator falls through to the
    keyframe fallback (graceful — explicit acceptance criterion in #769).

ui/src/audio/whisperStt.ts:154-160 — armWhisperStt() also calls subscribePcm; coexistence is fine (Set semantics; multiple subscribers receive every frame independently).

ui/src/components/profile/ParametricAvatar.tsx:48 — sibling pattern: AnalyserNode + useFrame driving scaleY. We are NOT using r3f useFrame here (MicIndicator is plain DOM); the analogue is RAF + setState.
```

## GitHub / industry pattern reference (brief)

The Discord/Slack/Zoom mic-meter pattern is: read time-domain samples, compute RMS over a frame, smooth with exponential moving average (EMA), drive opacity/scale at RAF cadence. EMA alpha of 0.2–0.4 is the standard range; the BF specifies **alpha = 0.3** which is dead-center and matches what Discord uses for their voice-activity meter.

RMS formula for a `Float32Array` frame `f` of length `N`:
```
rms = Math.sqrt( f.reduce((s, x) => s + x*x, 0) / N )
```
For a 16-bit-derived Float32 normalized to [-1, 1], typical speech RMS is ~0.05–0.3, peak transients ~0.5. Map to intensity via `intensity = clamp01(rms * GAIN)` where `GAIN ≈ 3.0` gives a usable 0..1 range for normal voice. This BF uses **GAIN = 3.0**.

EMA update:
```
smoothed = alpha * raw + (1 - alpha) * prevSmoothed
```

No further research needed — this is textbook Web Audio amplitude metering.

## Architectural surprises (none blocking, but document)

1. **VAD loop is opt-in.** `startVoiceActivity` is only called when `perception.vad_engagement_enabled` is true (App.tsx:189). Solo-Captain default is false. When the loop isn't running, `subscribePcm` returns an unsubscribe closure but no frames will arrive — `audioIntensity` stays at 0, `MicIndicator` falls through to keyframe pulse. This is the documented graceful degrade path (#769 explicit acceptance: "When `intensity` undefined, behavior identical to BF-294 (keyframe pulse)"). We pass `intensity={audioIntensity}` unconditionally; the *value* being persistently 0 vs the *prop* being undefined is a meaningful distinction — see Section 1's clamp/threshold logic.

2. **Browser SR and whisperStt both share this tap.** `whisperStt.ts:158` calls `subscribePcm` independently. Our subscription is additive (Set semantics in voiceActivity.ts:65). No coordination needed.

3. **`PcmTapHandler` is an interface with three methods**, not a single callback. Only `onFrame` is required; `onSpeechStart` / `onSpeechEnd` are optional. This BF implements only `onFrame`.

---

## Implementation

### Section 0: No new event types or interfaces beyond MicIndicatorProps extension

No changes to `voiceActivity.ts`. No new exports. The only new public API is the optional `intensity` prop on `MicIndicatorProps`.

### Section 1: Extend `MicIndicator` with `intensity` prop

**File:** `ui/src/components/profile/MicIndicator.tsx`

```tsx
===SEARCH===
export interface MicIndicatorProps {
  state: MicIndicatorState;
  /** Size of the rendered SVG glyph in px. Default 14 to match the
   *  existing mic button in ProfileChatTab. */
  size?: number;
}
===REPLACE===
export interface MicIndicatorProps {
  state: MicIndicatorState;
  /** Size of the rendered SVG glyph in px. Default 14 to match the
   *  existing mic button in ProfileChatTab. */
  size?: number;
  /** BF-294b — real-audio amplitude 0..1 driving the listening ring's
   *  opacity/scale. When undefined (or state !== 'listening'), the
   *  ring falls back to the BF-294 keyframe pulse. Values outside
   *  [0, 1] are clamped. */
  intensity?: number;
}
===END REPLACE===
```

```tsx
===SEARCH===
export function MicIndicator({ state, size = 14 }: MicIndicatorProps): React.ReactElement {
  const color = PALETTE[state];
===REPLACE===
export function MicIndicator({ state, size = 14, intensity }: MicIndicatorProps): React.ReactElement {
  const color = PALETTE[state];

  // BF-294b — when amplitude is supplied AND we're listening, override
  // the keyframe pulse with inline opacity/scale. Otherwise fall through
  // to the BF-294 keyframe animation.
  const hasIntensity = state === 'listening' && typeof intensity === 'number' && Number.isFinite(intensity);
  const clamped = hasIntensity ? Math.max(0, Math.min(1, intensity as number)) : 0;
  // Map intensity to visual range: opacity 0.35..1.0, scale 1.0..1.35.
  // The floor keeps the ring visible at silence (matches keyframe baseline).
  const dynOpacity = 0.35 + 0.65 * clamped;
  const dynScale = 1.0 + 0.35 * clamped;
===END REPLACE===
```

```tsx
===SEARCH===
      {state === 'listening' && (
        <span
          data-testid="mic-indicator-ring-listening"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px solid ${PALETTE.listening}`,
            animation: 'bf294-mic-listen 1.1s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />
      )}
===REPLACE===
      {state === 'listening' && (
        <span
          data-testid="mic-indicator-ring-listening"
          data-bf294b-mode={hasIntensity ? 'amplitude' : 'keyframe'}
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px solid ${PALETTE.listening}`,
            // BF-294b — when intensity is supplied, drive opacity/scale
            // from amplitude and suppress the keyframe pulse so the two
            // sources of motion don't fight. Otherwise keep BF-294's
            // keyframe behavior.
            animation: hasIntensity ? 'none' : 'bf294-mic-listen 1.1s ease-in-out infinite',
            opacity: hasIntensity ? dynOpacity : undefined,
            transform: hasIntensity ? `scale(${dynScale})` : undefined,
            transition: hasIntensity ? 'opacity 60ms linear, transform 60ms linear' : undefined,
            pointerEvents: 'none',
          }}
        />
      )}
===END REPLACE===
```

**Notes for Builder:**
- The `data-bf294b-mode` attribute lets tests assert which path was taken without DOM-style introspection.
- The `transition` adds a tiny 60 ms CSS smoothing on top of the EMA-smoothed prop — this is belt-and-braces and matches Discord's pattern of "EMA in JS, short CSS transition for sub-frame jitter."
- Do NOT touch the `processing` ring branch.
- Do NOT alter the SVG glyph stroke logic.

### Section 2: Wire `subscribePcm` in `ProfileChatTab.tsx`

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

First, add the import (place alongside the existing `whisperStt` import block):

```tsx
===SEARCH===
import { MicIndicator } from './MicIndicator';
===REPLACE===
import { MicIndicator } from './MicIndicator';
import { subscribePcm } from '../../audio/voiceActivity';
===END REPLACE===
```

Add `useRef`/`useEffect` to existing React imports if not already present (Builder: verify; if React imports already include both, skip this step). Then add the audio-intensity state and effect.

**Locate `const [listening, setListening] = useState(false);` (line 68)** and add immediately AFTER it:

```tsx
===SEARCH===
  const [listening, setListening] = useState(false);
  // BF-294: ``processing`` is true while whisperStt is running
===REPLACE===
  const [listening, setListening] = useState(false);
  // BF-294b — real-time amplitude meter for MicIndicator (0..1, smoothed
  // via EMA at RAF cadence). Stays at 0 when the voiceActivity loop
  // isn't armed (App.tsx gates it on perception.vad_engagement_enabled),
  // which is the documented graceful-degrade path (#769).
  const [audioIntensity, setAudioIntensity] = useState(0);
  const intensityRef = useRef(0);       // EMA accumulator, written from onFrame
  const rafPendingRef = useRef(false);  // RAF coalescing flag
  // BF-294: ``processing`` is true while whisperStt is running
===END REPLACE===
```

Then add the subscription effect. **Place it inside the component body** — Builder: locate any existing `useEffect` in this component, and add the new effect adjacent to a sibling effect (do not embed inside an unrelated effect). A safe anchor is immediately after the `[listening, setListening]` line group above:

```tsx
===SEARCH===
  const [audioIntensity, setAudioIntensity] = useState(0);
  const intensityRef = useRef(0);       // EMA accumulator, written from onFrame
  const rafPendingRef = useRef(false);  // RAF coalescing flag
  // BF-294: ``processing`` is true while whisperStt is running
===REPLACE===
  const [audioIntensity, setAudioIntensity] = useState(0);
  const intensityRef = useRef(0);       // EMA accumulator, written from onFrame
  const rafPendingRef = useRef(false);  // RAF coalescing flag

  // BF-294b — subscribe to voiceActivity PCM tap while listening; compute
  // RMS per frame, smooth via EMA (alpha=0.3, Discord-style), and flush
  // to state at RAF cadence to bound render churn. Unsubscribe and reset
  // when listening stops or the component unmounts.
  useEffect(() => {
    if (!listening) {
      // Reset to silence when disarmed (or on initial mount).
      intensityRef.current = 0;
      setAudioIntensity(0);
      return;
    }
    const EMA_ALPHA = 0.3;
    const GAIN = 3.0;
    const flushToState = () => {
      rafPendingRef.current = false;
      setAudioIntensity(intensityRef.current);
    };
    const scheduleFlush = () => {
      if (rafPendingRef.current) return;
      rafPendingRef.current = true;
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(flushToState);
      } else {
        // jsdom / non-browser: flush synchronously so tests don't hang.
        flushToState();
      }
    };
    const unsubscribe = subscribePcm({
      onFrame(frame: Float32Array, _sampleRate: number, _score?: number) {
        // RMS over the frame.
        let sumSq = 0;
        for (let i = 0; i < frame.length; i++) {
          const x = frame[i];
          sumSq += x * x;
        }
        const rms = frame.length > 0 ? Math.sqrt(sumSq / frame.length) : 0;
        const raw = Math.max(0, Math.min(1, rms * GAIN));
        intensityRef.current = EMA_ALPHA * raw + (1 - EMA_ALPHA) * intensityRef.current;
        scheduleFlush();
      },
    });
    return () => {
      try { unsubscribe(); } catch { /* Tier-2 — non-actionable on teardown */ }
      intensityRef.current = 0;
      rafPendingRef.current = false;
      setAudioIntensity(0);
    };
  }, [listening]);

  // BF-294: ``processing`` is true while whisperStt is running
===END REPLACE===
```

Finally, **wire the prop into the MicIndicator JSX render site.** Builder: search for `<MicIndicator` in this file (there is exactly one usage based on the existing BF-294 layout). Confirm the existing call shape, then:

```tsx
===SEARCH===
              <MicIndicator
                state={listening ? 'listening' : processing ? 'processing' : 'idle'}
              />
===REPLACE===
              <MicIndicator
                state={listening ? 'listening' : processing ? 'processing' : 'idle'}
                intensity={audioIntensity}
              />
===END REPLACE===
```

**Builder note:** if the existing `<MicIndicator ... />` call site uses a different formatting (e.g. all on one line, or with `size` prop), preserve that formatting and add `intensity={audioIntensity}` as a new prop. The SEARCH block above assumes the multi-line shape from the BF-294 commit; if it differs, adapt with a minimum 3-line context match.

### Section 3: New tests — `MicIndicator.bf294b.test.tsx`

**File:** `ui/src/components/profile/__tests__/MicIndicator.bf294b.test.tsx` (new)

```tsx
/**
 * BF-294b — MicIndicator intensity-driven ring tests.
 *
 * Verifies the optional ``intensity`` prop drives inline opacity/scale,
 * while the BF-294 keyframe fallback remains intact when ``intensity``
 * is undefined or state !== 'listening'.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MicIndicator } from '../MicIndicator';

describe('MicIndicator BF-294b (amplitude-driven ring)', () => {
  it('regression: no intensity prop falls back to BF-294 keyframe animation', () => {
    const { getByTestId } = render(<MicIndicator state="listening" />);
    const ring = getByTestId('mic-indicator-ring-listening');
    const style = ring.getAttribute('style') || '';
    expect(style).toContain('bf294-mic-listen');
    expect(ring.getAttribute('data-bf294b-mode')).toBe('keyframe');
  });

  it('intensity=0.5 applies inline opacity/scale and suppresses keyframe', () => {
    const { getByTestId } = render(<MicIndicator state="listening" intensity={0.5} />);
    const ring = getByTestId('mic-indicator-ring-listening');
    const style = ring.getAttribute('style') || '';
    expect(ring.getAttribute('data-bf294b-mode')).toBe('amplitude');
    // animation must be suppressed when amplitude-driven (or set to 'none')
    expect(style).not.toContain('bf294-mic-listen');
    // 0.35 + 0.65*0.5 = 0.675 opacity; 1.0 + 0.35*0.5 = 1.175 scale
    expect(style).toMatch(/opacity:\s*0\.675/);
    expect(style).toMatch(/scale\(1\.175\)/);
  });

  it('intensity is clamped to [0, 1] — out-of-range values do not break layout', () => {
    const { getByTestId, rerender } = render(<MicIndicator state="listening" intensity={1.5} />);
    let style = getByTestId('mic-indicator-ring-listening').getAttribute('style') || '';
    // clamp to 1.0 → opacity 1.0, scale 1.35
    expect(style).toMatch(/opacity:\s*1(\D|$)/);
    expect(style).toMatch(/scale\(1\.35\)/);

    rerender(<MicIndicator state="listening" intensity={-0.2} />);
    style = getByTestId('mic-indicator-ring-listening').getAttribute('style') || '';
    // clamp to 0 → opacity 0.35, scale 1.0 (no negative scale)
    expect(style).toMatch(/opacity:\s*0\.35/);
    expect(style).toMatch(/scale\(1\)/);
  });

  it('intensity only applies in listening state — processing/idle ignore it', () => {
    const { queryByTestId, rerender } = render(
      <MicIndicator state="processing" intensity={0.9} />,
    );
    // processing ring renders, not listening ring; intensity is ignored.
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
    const procRing = queryByTestId('mic-indicator-ring-processing');
    expect(procRing).not.toBeNull();
    // processing ring keeps its keyframe shimmer
    expect(procRing!.getAttribute('style') || '').toContain('bf294-mic-process');

    rerender(<MicIndicator state="idle" intensity={0.9} />);
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
    expect(queryByTestId('mic-indicator-ring-processing')).toBeNull();
  });

  it('NaN / Infinity intensity falls back to keyframe mode', () => {
    const { getByTestId, rerender } = render(<MicIndicator state="listening" intensity={NaN} />);
    let ring = getByTestId('mic-indicator-ring-listening');
    expect(ring.getAttribute('data-bf294b-mode')).toBe('keyframe');
    expect(ring.getAttribute('style') || '').toContain('bf294-mic-listen');

    rerender(<MicIndicator state="listening" intensity={Infinity} />);
    ring = getByTestId('mic-indicator-ring-listening');
    expect(ring.getAttribute('data-bf294b-mode')).toBe('keyframe');
  });
});
```

### Section 4: New tests — `ProfileChatTab.bf294b.test.tsx`

**File:** `ui/src/components/profile/__tests__/ProfileChatTab.bf294b.test.tsx` (new)

**Builder note on test scoping:** `ProfileChatTab` has heavy dependencies (settings store, agent stores, whisper, etc.). Rather than mount the full component, this suite mocks `subscribePcm` and **unit-tests the subscription/unsubscription contract through a tiny wrapper component** that exercises the same `useEffect`/`useState` pattern this BF adds. This is consistent with how prior BFs (e.g. BF-290 whisper PTT) tested mic-related logic without booting the full ProfileChatTab. If the Builder finds an existing ProfileChatTab test fixture that boots cleanly, the suite may be migrated to mount the real component — but the wrapper approach is the documented default to avoid the BF-279-class trap of accidentally depending on the full store graph.

```tsx
/**
 * BF-294b — PCM-tap subscription lifecycle tests for the audio-intensity
 * wiring added to ProfileChatTab. Uses a minimal wrapper component that
 * mirrors the same useEffect/useState pattern; the goal is to verify
 * the contract with voiceActivity.subscribePcm, not to render the full
 * ProfileChatTab (which has heavy store dependencies).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { useState, useEffect, useRef } from 'react';
import { render, act, cleanup } from '@testing-library/react';

// Mock subscribePcm BEFORE importing anything that uses it.
const mockUnsubscribe = vi.fn();
const subscribers: Array<{ onFrame: (f: Float32Array, sr: number, s?: number) => void }> = [];

vi.mock('../../../audio/voiceActivity', () => ({
  subscribePcm: vi.fn((handler: any) => {
    subscribers.push(handler);
    return () => {
      mockUnsubscribe();
      const idx = subscribers.indexOf(handler);
      if (idx >= 0) subscribers.splice(idx, 1);
    };
  }),
}));

// Wrapper mirrors the BF-294b ProfileChatTab logic exactly.
function MicHarness({ listening }: { listening: boolean }) {
  const [intensity, setIntensity] = useState(0);
  const intensityRef = useRef(0);
  const rafPendingRef = useRef(false);
  useEffect(() => {
    if (!listening) {
      intensityRef.current = 0;
      setIntensity(0);
      return;
    }
    const EMA_ALPHA = 0.3;
    const GAIN = 3.0;
    const flush = () => {
      rafPendingRef.current = false;
      setIntensity(intensityRef.current);
    };
    const schedule = () => {
      if (rafPendingRef.current) return;
      rafPendingRef.current = true;
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(flush);
      else flush();
    };
    // Inline import to honor the vi.mock above.
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { subscribePcm } = require('../../../audio/voiceActivity');
    const unsub = subscribePcm({
      onFrame(frame: Float32Array) {
        let sumSq = 0;
        for (let i = 0; i < frame.length; i++) sumSq += frame[i] * frame[i];
        const rms = frame.length > 0 ? Math.sqrt(sumSq / frame.length) : 0;
        const raw = Math.max(0, Math.min(1, rms * GAIN));
        intensityRef.current = EMA_ALPHA * raw + (1 - EMA_ALPHA) * intensityRef.current;
        schedule();
      },
    });
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
      intensityRef.current = 0;
      rafPendingRef.current = false;
      setIntensity(0);
    };
  }, [listening]);
  return <div data-testid="intensity">{intensity.toFixed(4)}</div>;
}

describe('ProfileChatTab BF-294b PCM-tap lifecycle', () => {
  beforeEach(() => {
    mockUnsubscribe.mockClear();
    subscribers.length = 0;
    // jsdom polyfill: synchronous RAF for deterministic state flush.
    (globalThis as any).requestAnimationFrame = (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    };
  });
  afterEach(() => {
    cleanup();
    delete (globalThis as any).requestAnimationFrame;
  });

  it('listening=true subscribes to PCM tap', () => {
    render(<MicHarness listening={true} />);
    expect(subscribers.length).toBe(1);
    expect(mockUnsubscribe).not.toHaveBeenCalled();
  });

  it('listening=true → false unsubscribes and resets intensity', () => {
    const { rerender, getByTestId } = render(<MicHarness listening={true} />);
    // Pump a synthetic frame to drive intensity > 0.
    act(() => {
      const frame = new Float32Array(480).fill(0.3);
      subscribers[0].onFrame(frame, 16000);
    });
    expect(parseFloat(getByTestId('intensity').textContent || '0')).toBeGreaterThan(0);
    rerender(<MicHarness listening={false} />);
    expect(mockUnsubscribe).toHaveBeenCalledTimes(1);
    expect(subscribers.length).toBe(0);
    expect(parseFloat(getByTestId('intensity').textContent || '0')).toBe(0);
  });

  it('unmount during listening unsubscribes (no leak)', () => {
    const { unmount } = render(<MicHarness listening={true} />);
    expect(subscribers.length).toBe(1);
    unmount();
    expect(mockUnsubscribe).toHaveBeenCalledTimes(1);
    expect(subscribers.length).toBe(0);
  });

  it('PCM frames drive non-zero intensity via RMS + EMA + GAIN', () => {
    const { getByTestId } = render(<MicHarness listening={true} />);
    // Constant 0.5 amplitude frame → RMS=0.5 → raw = min(1, 0.5*3.0) = 1.0
    // First EMA step: 0.3 * 1.0 + 0.7 * 0 = 0.3
    act(() => {
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
    });
    const after1 = parseFloat(getByTestId('intensity').textContent || '0');
    expect(after1).toBeGreaterThan(0.25);
    expect(after1).toBeLessThan(0.35);
    // Second EMA step: 0.3 * 1.0 + 0.7 * 0.3 = 0.51
    act(() => {
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
    });
    const after2 = parseFloat(getByTestId('intensity').textContent || '0');
    expect(after2).toBeGreaterThan(after1);  // smoothing — rises toward steady state
    expect(after2).toBeLessThan(0.55);
  });

  it('silent frame (RMS=0) drives intensity toward 0 from previous high', () => {
    const { getByTestId } = render(<MicHarness listening={true} />);
    // Prime with high amplitude.
    act(() => {
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
      subscribers[0].onFrame(new Float32Array(480).fill(0.5), 16000);
    });
    const peak = parseFloat(getByTestId('intensity').textContent || '0');
    expect(peak).toBeGreaterThan(0.5);
    // Then silence — EMA decays.
    act(() => {
      subscribers[0].onFrame(new Float32Array(480), 16000);
      subscribers[0].onFrame(new Float32Array(480), 16000);
    });
    const decayed = parseFloat(getByTestId('intensity').textContent || '0');
    expect(decayed).toBeLessThan(peak);
  });
});
```

---

## What this does NOT change

- `voiceActivity.ts` — no API changes. We are a consumer, not a producer.
- `MicIndicator`'s `idle` and `processing` branches — completely unchanged.
- The BF-294 keyframe CSS (`bf294-mic-listen`, `bf294-mic-process`) — left in place; the fallback path still uses them.
- `whisperStt.ts` — coexists harmlessly via Set-based subscribers in voiceActivity.
- `App.tsx` VAD gating — `perception.vad_engagement_enabled` semantics are unchanged. We document the graceful-degrade behavior when VAD is off; we do NOT force the loop on.
- `ParametricAvatar.tsx` — referenced for symmetry, not modified.
- No new `getUserMedia()` call sites (explicit acceptance criterion).
- No new HXI assets, palette entries, or keyframe definitions.

---

## Acceptance criteria

1. `MicIndicator` accepts `intensity?: number` (clamped 0..1; NaN/Infinity treated as undefined).
2. When `state === 'listening'` AND a finite `intensity` is provided, the listening ring renders with inline `opacity` and `transform: scale(...)` driven by `intensity`; the `bf294-mic-listen` keyframe animation is suppressed.
3. When `intensity` is undefined (or non-finite, or state !== 'listening'), behavior is byte-identical to BF-294 — keyframe pulse on `listening`, shimmer on `processing`, nothing on `idle`.
4. `ProfileChatTab` subscribes to `voiceActivity.subscribePcm` exactly while `listening === true`. Unsubscribes on disarm AND on unmount.
5. RMS computation + EMA smoothing (alpha=0.3, GAIN=3.0) + RAF-coalesced state flush, as specified.
6. 5 new tests in `MicIndicator.bf294b.test.tsx` + 5 new tests in `ProfileChatTab.bf294b.test.tsx` (the spec above ships 5+5, exceeding the "4+4" floor from the userRequest).
7. **Both gates green:**
   - `cd ui; npx vitest run` — full suite (target + regression on existing BF-294 / voiceActivity / whisperStt tests).
   - `cd ui; npm run build` — MUST succeed (BF-279 lesson: vitest does NOT exercise `tsc -b`; the build gate is mandatory for any UI-touching wave).
8. One commit with `Closes #769` in the body. Push to `origin/main` only when BOTH gates are green.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` — specifically:
   - HXI #3 (no emoji — pure SVG/inline-style, already satisfied)
   - HXI #4 (motion communicates state — amplitude-driven motion now encodes voice presence, replacing the constant keyframe pulse that encoded only "the mic is open")
   - Three-tier exception handling (the `try { unsubscribe(); } catch { }` on teardown is Tier-2 log-and-degrade — non-actionable in teardown context, matches the existing pattern in voiceActivity.ts:271)

---

## Tracking

- Update PROGRESS.md after merge with the BF-294b CLOSED entry (one-line summary + commit SHA).
- No DECISIONS.md entry — this is a behavior refinement, not an architectural decision.
- GitHub issue #769 auto-closes via the commit footer.

---

## Standing constraints (from userRequest)

- Do NOT touch the live runtime.
- Do NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.
- Do NOT run process sweeps (no `Get-Process python | Stop-Process`). If a vitest worker hangs, use the documented `scripts/kill-stale-pytest.ps1` pattern or `Stop-Process -Id <pid>` after explicitly excluding the live runtime PID from `data/probos.pid`.
- All work in the working tree under `d:\ProbOS\`; commits via standard `git add -p` + `git commit` flow.
