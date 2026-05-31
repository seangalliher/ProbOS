# BF-294: Mic affordance — listening / processing visual states

**Status:** Ready to build
**GitHub issue:** #768
**Estimated tests:** 9 new Vitest tests (5 MicIndicator + 4 ProfileChatTab.bf294)
**Engineering Principles checkpoint:** HXI #3 (no emoji), #4 (motion communicates state), #6 (progressive disclosure). All inline SVG glyphs `strokeWidth: 1.5`, `strokeLinecap: round`. Trust-spectrum amber `#f0b060` (active) / `#a08040` (dim).

---

## Problem

Current mic button in `ui/src/components/profile/ProfileChatTab.tsx` (lines 793–905) has only two visual states:

- Idle: dim grey glyph.
- `listening === true`: hardcoded red (`#ff6666`) flash + `pulse-mic` CSS keyframe + red drop-shadow.

User reports (today, 2026-05-22) that this looks like an error indicator, gives no feedback that the mic is actually capturing voice, and gives no feedback during the whisper transcription window. From the agent-side, TTS playback animates `ParametricAvatar.tsx` via amplitude from an `AnalyserNode` (`onSpeechEvent` → `_attachAnalyserOrSchedule`). The mic side needs symmetrical feedback.

Required three states:

| State        | Visual                                | Trigger                                                |
|--------------|---------------------------------------|--------------------------------------------------------|
| `idle`       | Static mic glyph, neutral grey        | No active capture                                      |
| `listening`  | Amber glyph, pulsing amber ring       | `listening === true` (browser SR or whisper armed)     |
| `processing` | Dim-amber glyph, shimmer/spinner ring | `onTranscribing(true)` (whisper transcribing in flight)|

---

## Solution overview

**Option A (chosen): CSS pulse animation, no live audio-level meter.** A new `<MicIndicator state={...} />` component encapsulates the three states. `ProfileChatTab.tsx` derives state from `listening` + a new `processing` flag wired to `onTranscribing()` from `whisperStt.ts`.

### Why not Option B (real audio-level meter)?

Option B (RMS from a live PCM stream → ring opacity/scale) is **easier than the BF body suggests** because `audio/voiceActivity.ts` already exports a `subscribePcm(handler)` API that fans out the existing mic tap (no parallel `getUserMedia`, no second stream conflict). Confirmed:

```text
ui/src/audio/voiceActivity.ts:301  export function subscribePcm(handler: PcmTapHandler): () => void
```

However, `subscribePcm` only emits frames when the voiceActivity loop is armed (started via `startVoiceActivity()` or via conversation-mode auto-arm). In pure browser-SR PTT mode the tap is NOT running, so the meter would be silent — degrading to "Option A but with extra wiring complexity." Shipping Option A as v1 keeps the surface narrow and avoids permission-flow rework.

**Filed as BF-294b at end of this prompt:** "wire MicIndicator amplitude to `subscribePcm` when the tap is armed." Builder MUST NOT implement BF-294b in this prompt.

---

## Implementation

### Section 1: New component `ui/src/components/profile/MicIndicator.tsx`

Create a new file with:

```tsx
/**
 * BF-294 — Three-state mic affordance.
 *
 * States:
 *   - idle:       static mic glyph, neutral grey
 *   - listening:  amber glyph + pulsing amber ring (CSS @keyframes)
 *   - processing: dim-amber glyph + shimmer ring (CSS @keyframes)
 *
 * HXI compliance:
 *   - #3 No emoji — inline SVG glyph only, strokeWidth 1.5, strokeLinecap round.
 *   - #4 Motion communicates state — distinct animations per state.
 *   - Trust-spectrum palette: #f0b060 active amber, #a08040 dim amber.
 *
 * The component is presentational only. Parent supplies `state` and the
 * usual ``onClick`` / ``aria-label`` / ``title`` props for the button
 * wrapper. ``MicIndicator`` renders the SVG glyph + animated ring overlay,
 * NOT the <button> element itself — parents wrap it in a <button> so they
 * keep ownership of click handling, aria-haspopup, refs, etc.
 */
import React from 'react';

export type MicIndicatorState = 'idle' | 'listening' | 'processing';

export interface MicIndicatorProps {
  state: MicIndicatorState;
  /** Size of the rendered SVG glyph in px. Default 14 to match the
   *  existing mic button in ProfileChatTab. */
  size?: number;
}

const PALETTE = {
  idle: '#8888aa',
  listening: '#f0b060',
  processing: '#a08040',
} as const;

export function MicIndicator({ state, size = 14 }: MicIndicatorProps): React.ReactElement {
  const color = PALETTE[state];
  // data-bf294-state lets tests assert state without DOM-traversal heuristics.
  return (
    <span
      data-testid="mic-indicator"
      data-bf294-state={state}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
      }}
    >
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
      {state === 'processing' && (
        <span
          data-testid="mic-indicator-ring-processing"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px dashed ${PALETTE.processing}`,
            animation: 'bf294-mic-process 1.4s linear infinite',
            pointerEvents: 'none',
          }}
        />
      )}
      <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <line x1="8" y1="2" x2="8" y2="9" />
        <path d="M5 7c0 1.7 1.3 3 3 3s3-1.3 3-3" />
        <line x1="8" y1="12" x2="8" y2="14" />
        <line x1="6" y1="14" x2="10" y2="14" />
      </svg>
    </span>
  );
}
```

### Section 2: Global CSS keyframes

The existing `pulse-mic` keyframe is referenced inline in `ProfileChatTab.tsx` line 886 but the keyframe definition itself is in a global stylesheet. Builder MUST locate the file that owns the existing `pulse-mic` keyframe (likely `ui/src/index.css`, `ui/src/styles/global.css`, or similar) and add two new keyframes alongside it.

Search command:

```powershell
Get-ChildItem ui/src -Recurse -Include *.css,*.tsx,*.ts | Select-String -Pattern "@keyframes pulse-mic|pulse-mic\s*{"
```

Add to the same file:

```css
@keyframes bf294-mic-listen {
  0%, 100% { opacity: 0.35; transform: scale(1.0); }
  50%      { opacity: 0.85; transform: scale(1.18); }
}

@keyframes bf294-mic-process {
  0%   { transform: rotate(0deg);   opacity: 0.55; }
  50%  { transform: rotate(180deg); opacity: 0.85; }
  100% { transform: rotate(360deg); opacity: 0.55; }
}
```

If no global stylesheet exists, create `ui/src/styles/bf294-mic.css` and import it from `ui/src/main.tsx` (or whatever the existing app entry is — verify with grep).

### Section 3: Wire `MicIndicator` into `ProfileChatTab.tsx`

Three changes in `ui/src/components/profile/ProfileChatTab.tsx`:

#### 3a — Add `processing` state and `onTranscribing` wiring

Find the import block (around lines 12–16):

```tsx
import {
  armWhisperStt,
  disarmWhisperStt,
  onTranscript as onWhisperTranscript,
} from '../../audio/whisperStt';
```

Replace with:

```tsx
import {
  armWhisperStt,
  disarmWhisperStt,
  onTranscript as onWhisperTranscript,
  onTranscribing as onWhisperTranscribing,
} from '../../audio/whisperStt';
import { MicIndicator, type MicIndicatorState } from './MicIndicator';
```

Find the state declarations (around line 59):

```tsx
  const [listening, setListening] = useState(false);
```

Add immediately after:

```tsx
  // BF-294: ``processing`` is true while whisperStt is running
  // transcribeBuffer (between speech_end and transcript delivery).
  // Browser-SR's onend → onresult is effectively instant, so we only
  // wire this to the whisper path. Falls back to false on error.
  const [processing, setProcessing] = useState(false);
  useEffect(() => {
    const unsub = onWhisperTranscribing((active) => {
      setProcessing(active);
    });
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
      setProcessing(false);
    };
  }, []);
```

`useEffect` is already imported — verify the existing import line in the file (`import React, { ..., useEffect, ... }`). If `useEffect` is not imported, add it.

#### 3b — Replace inline SVG + style on the mic button with `<MicIndicator />`

Find the button rendering block (lines 870–905, the `<button>` whose `aria-label={listening ? 'Stop listening' : 'Voice input'}`). The relevant block currently inlines a `<svg>` and a hardcoded `background`/`color`/`animation`/`filter` style. Replace the inline `<svg>` element (lines 898–905) with:

```tsx
              <MicIndicator state={processing ? 'processing' : listening ? 'listening' : 'idle'} size={14} />
```

Replace the hardcoded color-driven `style={{ ... }}` block on the `<button>` (lines 884–897) with a state-derived equivalent that uses the same palette as `MicIndicator`:

```tsx
              style={{
                background: listening
                  ? 'rgba(240, 176, 96, 0.12)' // amber wash, matches MicIndicator listening
                  : processing
                    ? 'rgba(160, 128, 64, 0.10)' // dim-amber wash
                    : 'transparent',
                border: 'none',
                cursor: 'pointer',
                fontSize: 14,
                padding: '4px',
                borderRadius: 4,
                transition: 'background 0.2s, filter 0.2s',
                flexShrink: 0,
                filter: listening
                  ? 'drop-shadow(0 0 4px #f0b060)'
                  : processing
                    ? 'drop-shadow(0 0 3px #a08040)'
                    : micMode === 'conversation'
                      ? 'drop-shadow(0 0 4px #f0b060)'
                      : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
              }}
```

Update `title` and `aria-label` to reflect three states:

```tsx
              title={
                processing ? 'Transcribing…' :
                listening ? 'Stop listening' : 'Voice input'
              }
              aria-label={
                processing ? 'Transcribing speech' :
                listening ? 'Stop listening' : 'Voice input'
              }
```

#### 3c — Defensive: clear `processing` when listening is forcibly stopped

In the `if (listening) { stopListening(); ... }` early-return branch (around lines 805–814), after `setListening(false)`:

```tsx
                  setListening(false);
                  setProcessing(false); // BF-294: cancel any pending processing visual
                  return;
```

### Section 4: Tests

#### 4a — `ui/src/components/profile/__tests__/MicIndicator.test.tsx`

```tsx
/**
 * BF-294 — MicIndicator visual-state tests.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MicIndicator } from '../MicIndicator';

describe('MicIndicator (BF-294)', () => {
  it('idle state renders no ring overlay', () => {
    const { queryByTestId, getByTestId } = render(<MicIndicator state="idle" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
    expect(queryByTestId('mic-indicator-ring-processing')).toBeNull();
  });

  it('listening state renders the pulsing ring with amber color', () => {
    const { getByTestId, queryByTestId } = render(<MicIndicator state="listening" />);
    const ring = getByTestId('mic-indicator-ring-listening');
    expect(ring).toBeTruthy();
    expect(ring.getAttribute('style') || '').toContain('#f0b060');
    expect(ring.getAttribute('style') || '').toContain('bf294-mic-listen');
    expect(queryByTestId('mic-indicator-ring-processing')).toBeNull();
  });

  it('processing state renders the shimmer ring with dim-amber color', () => {
    const { getByTestId, queryByTestId } = render(<MicIndicator state="processing" />);
    const ring = getByTestId('mic-indicator-ring-processing');
    expect(ring).toBeTruthy();
    expect(ring.getAttribute('style') || '').toContain('#a08040');
    expect(ring.getAttribute('style') || '').toContain('bf294-mic-process');
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
  });

  it('state prop drives data-bf294-state attribute on re-render', () => {
    const { getByTestId, rerender } = render(<MicIndicator state="idle" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
    rerender(<MicIndicator state="listening" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('listening');
    rerender(<MicIndicator state="processing" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');
    rerender(<MicIndicator state="idle" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });

  it('SVG glyph stroke color matches the active state palette', () => {
    const { container, rerender } = render(<MicIndicator state="idle" />);
    const svgIdle = container.querySelector('svg');
    expect(svgIdle?.getAttribute('stroke')).toBe('#8888aa');
    rerender(<MicIndicator state="listening" />);
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('#f0b060');
    rerender(<MicIndicator state="processing" />);
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('#a08040');
  });
});
```

#### 4b — `ui/src/__tests__/ProfileChatTab.bf294.test.tsx`

Follow the same setup pattern as the existing `ProfileChatTab.bf290.test.tsx` (open it, copy the import/mocking scaffolding — particularly the `whisperStt` and `speechInput` mocks). Add 4 new tests:

1. **PTT click → MicIndicator state is `listening`.** Mock `startListening` so it does not auto-resolve. Click the mic button. Assert `data-bf294-state="listening"` on the rendered `MicIndicator`.

2. **`onTranscribing(true)` callback flips state to `processing`.** Mock `onTranscribing` to capture the registered listener. Set `listening=true` via PTT click, then invoke the captured listener with `true`. Assert `data-bf294-state="processing"`. State priority: processing > listening.

3. **`onTranscribing(false)` after transcript flips state back to idle.** Continuing from test 2: invoke the captured listener with `false`, and simulate the `setListening(false)` path (via the whisper transcript callback). Assert `data-bf294-state="idle"`.

4. **Force-stop while listening also clears `processing`.** Arm both listening and processing (call captured `onTranscribing(true)`). Click the mic button to force-stop. Assert `data-bf294-state="idle"` and that `disarmWhisperStt` was called.

For each test, render `<ProfileChatTab agentId="alpha" />` (or whatever the existing fixture uses), use `@testing-library/react` `screen.getByTestId('mic-indicator')`, and follow the same mock-store/mock-fetch scaffolding as `ProfileChatTab.bf290.test.tsx`.

---

## What this does NOT change

- The mic mode popover (`micMenuOpen`, conversation/PTT toggle) is untouched.
- The `stopListening` / `disarmWhisperStt` cleanup paths are untouched apart from the `setProcessing(false)` defensive call.
- The whisperStt audio pipeline, the voiceActivity PCM tap, and `subscribePcm` are NOT wired in this prompt (filed as BF-294b below).
- No new `getUserMedia` call sites. No `AudioContext`. No `AnalyserNode`. No `requestAnimationFrame` loops. All animation is CSS-driven.
- The agent-side TTS playback animation in `ParametricAvatar.tsx` is the symmetry target, NOT a code dependency — do not import from it.
- The `pulse-mic` keyframe currently driving the red flash is left in place (other code paths may still reference it; do not delete).

---

## Verification checklist

Before opening a PR, the Builder must confirm:

- [ ] `cd ui ; npx vitest run` passes (target ≥ 9 new tests across `MicIndicator.test.tsx` + `ProfileChatTab.bf294.test.tsx`; existing suite remains green).
- [ ] `cd ui ; npm run build` succeeds. **REQUIRED per BF-279 — Vitest does not exercise `tsc`. A passing `vitest run` is NOT proof the bundle builds.**
- [ ] All inline SVG uses `strokeWidth: 1.5`, `strokeLinecap: round`. No emoji anywhere in the diff (HXI #3).
- [ ] No hardcoded color outside `PALETTE` / button background helper. Amber `#f0b060` / dim `#a08040` reused consistently.
- [ ] No `setInterval`, no parallel `getUserMedia`, no `AudioContext`. (Per BF body's "no setInterval" rule and this prompt's Option A scope.)
- [ ] Cleanup verified: `useEffect` unsubscribe runs, `setProcessing(false)` fires on unmount and on force-stop.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` (HXI #3, #4, #6, #11; SOLID/DRY; type annotations on all exported props).

---

## Tracking

- Close `#768` in commit body: `Closes #768`.
- Append BF-294 entry to `docs/development/roadmap.md` Bug Tracker.
- Append AD ROW to `PROGRESS.md` BF table (no new AD number — this is BF-only).
- File **BF-294b** (separate `gh issue create` AFTER this prompt ships) titled: *"BF-294b: wire MicIndicator amplitude to subscribePcm for live audio-level feedback when voiceActivity tap is armed."* Body should note: optional v2 enhancement, depends on `voiceActivity.startVoiceActivity()` being active, applies only in conversation mode or when whisperStt is armed. No `getUserMedia` parallel stream — reuse the existing tap.

---

## Verified Against Codebase (2026-05-22)

```text
grep -n "aria-label.*listen\|aria-label.*voice" ui/src/components/profile/ProfileChatTab.tsx
  730:  aria-label={ttsEnabled ? 'Mute agent voice' : 'Enable agent voice'}
  873:  aria-label={listening ? 'Stop listening' : 'Voice input'}

grep -n "const \[listening" ui/src/components/profile/ProfileChatTab.tsx
  59:  const [listening, setListening] = useState(false);

grep -n "armWhisperStt\|disarmWhisperStt\|onTranscript as onWhisperTranscript" ui/src/components/profile/ProfileChatTab.tsx
  13:    armWhisperStt,
  14:    disarmWhisperStt,
  15:    onTranscript as onWhisperTranscript,

grep -n "export function onTranscribing\|export function onTranscript\|export function armWhisperStt\|export function disarmWhisperStt" ui/src/audio/whisperStt.ts
  154:  export function armWhisperStt(): () => void
  168:  export function disarmWhisperStt(): void
  184:  export function onTranscript(listener: TranscriptListener): () => void
  192:  export function onTranscribing(listener: (active: boolean) => void): () => void

grep -n "animation: listening\|pulse-mic" ui/src/components/profile/ProfileChatTab.tsx
  886:  animation: listening ? 'pulse-mic 1s ease-in-out infinite' : undefined,

grep -n "export function subscribePcm" ui/src/audio/voiceActivity.ts
  301:  export function subscribePcm(handler: PcmTapHandler): () => void

grep -n "onSpeechEvent\|speakingRef\|_attachAnalyserOrSchedule" ui/src/components/profile/ParametricAvatar.tsx
  46:  const speakingRef = useRef(false)
  48:  const off = onSpeechEvent((e) => ...)
  53:  analyserRef.current = _attachAnalyserOrSchedule(e.utterance)
  55:  speakingRef.current = true

ls ui/src/__tests__/ProfileChatTab.bf290.test.tsx  (exists — use as scaffolding template)
ls ui/src/components/profile/MicIndicator.tsx       (does not exist — to be created)
ls ui/src/components/profile/__tests__/             (directory must be created or verified)
```

All concrete claims in this prompt map to a grep hit above. The `MicIndicator` component, the `bf294-mic-listen` / `bf294-mic-process` keyframes, the `processing` state, and the `onWhisperTranscribing` import are introduced by this prompt — these MUST NOT be flagged as missing by review.
