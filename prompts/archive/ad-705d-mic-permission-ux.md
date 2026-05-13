# AD-736 — Mic-permission UX polish (failure modes for the wake-word loop)

**Status:** Ready for Builder
**AD:** AD-736 (next free top-level number after AD-734; Wave 156 highest-AD audit).
**GH issue:** [#558](https://github.com/seangalliher/ProbOS/issues/558) (closes)
**Parent AD:** AD-705 (always-on wake-word voice loop, shipped). Extends the state machine; does not change the wake-word algorithm.
**Wave:** 156
**Estimated tests:** ~4-5 new in `ui/src/audio/__tests__/wakeWord.micPermission.test.ts` (NEW file).

---

## Captain decisions baked in

1. **Surface failure modes; don't silently degrade.** The current `_emitFallbackToast` writes to `console.warn` only ([ui/src/audio/wakeWord.ts:463-471](ui/src/audio/wakeWord.ts#L463-L471)). Captains never see it. The HXI needs a visible state for "voice loop disabled and here's why."
2. **Four states, one state machine.** `pending` (not yet asked) / `granted` (working) / `denied` (browser blocked it) / `unavailable` (no hardware OR browser doesn't support SpeechRecognition). No flag-soup, no parallel booleans. Mirror the existing `WakeWordState` enum shape ([wakeWord.ts:32-37](ui/src/audio/wakeWord.ts#L32-L37)).
3. **One-time, dismissible hint.** When state transitions to `denied`, surface a non-modal text hint: "Click the microphone icon in your browser's address bar to enable voice input." Persist the dismissal via `localStorage` key `hxi_mic_hint_dismissed` so refreshing doesn't re-show.
4. **`unavailable` is quieter than `denied`.** Hardware absence isn't a user error; log one INFO line and surface a small "voice disabled — no microphone detected" indicator. No instructional hint.
5. **Inline SVG mic icon, not emoji** (HXI Design Principle #3). `strokeWidth: 1.5`, `strokeLinecap: round`. Amber when granted/active, dim when denied/unavailable, faint amber when pending. Match the existing speaker family in `DecisionSurface.tsx:135-146`.
6. **No retry button in v1.** The hint already tells the Captain what to do (click the address-bar icon); a "Retry" button would re-prompt and immediately fail in browsers that have already permanently denied the permission. The Captain refreshes the page after granting via the address bar; the wake loop re-arms on mount.
7. **Honest-degrade preserved.** The existing fallback path (`_emitFallbackToast` + `_setState('off', ...)` chain) keeps working. This AD adds a Captain-visible surface ON TOP of the existing log surface; the log line still fires for operators tailing the console.

---

## Problem

The wake-word loop already detects three fallback reasons today:
- `mic_permission_denied` ([wakeWord.ts:39](ui/src/audio/wakeWord.ts#L39))
- `onnx_load_failed` ([wakeWord.ts:38](ui/src/audio/wakeWord.ts#L38))
- `speech_recognition_unavailable` ([wakeWord.ts:40](ui/src/audio/wakeWord.ts#L40))

But the only surface for any of them is `console.warn` via `_emitFallbackToast`. The Captain hits "Voice on" → permission popup → "Block" → nothing visible happens. The voice button silently fails to do anything, and there's no path forward unless the Captain opens DevTools.

Additionally, **no current state distinguishes `denied` (active user refusal) from `unavailable` (no hardware, no browser support).** Both fold into `mic_permission_denied` or `speech_recognition_unavailable` depending on which code path the failure travelled through, and the messaging is identical. The Captain needs different guidance for "the browser blocked the mic" (actionable: click the address-bar icon) versus "no microphone detected" (actionable: plug in a mic, then refresh).

---

## Solution

Three pieces:

1. **Extend the state machine in `wakeWord.ts`** to emit four distinct mic-permission states. Add a new exported enum `MicPermissionState` separate from `WakeWordState` (the wake loop has its own concerns; mic permission is a sub-state). The existing `WakeFallbackReason` type stays — both surfaces co-exist.
2. **A small `MicPermissionHint.tsx` HXI component** that subscribes to the new permission state and renders the appropriate surface (mic SVG glyph + optional one-line hint + dismiss button). Mounts once at the HXI shell level.
3. **A pre-flight feature-detect** in `startWakeWordLoop` that uses `navigator.mediaDevices.enumerateDevices()` to distinguish "no microphone hardware" from "microphone present but permission denied." If `enumerateDevices` is unavailable or rejects, treat as `unavailable` and degrade quietly.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `ui/src/audio/wakeWord.ts` | Extend state machine with `MicPermissionState` + `onMicPermissionState` listener API; thread through `_emitFallbackToast` failure paths. |
| `ui/src/audio/__tests__/wakeWord.micPermission.test.ts` | NEW — 4-5 Vitest tests. |
| `ui/src/components/MicPermissionHint.tsx` | NEW — minimal HXI surface (mic SVG + one-line hint + dismiss). |
| `ui/src/components/__tests__/MicPermissionHint.test.tsx` | NEW — 2 component tests (render under each state, dismiss persists). |
| `ui/src/App.tsx` | Mount `<MicPermissionHint />` once as a top-level overlay sibling to `<DecisionSurface />`, `<AgentTooltip />`, etc. (Verified pass-1 review: `HXIShell.tsx` does not exist; `App.tsx` is the HXI root that mounts all persistent overlays.) |
| `PROGRESS.md` | Wave 156 entry; +tests count delta. |
| `DECISIONS.md` | Append AD-736 closure block. |
| `docs/development/roadmap.md` | Mark AD-736 shipped Wave 156; close [#558](https://github.com/seangalliher/ProbOS/issues/558). |

**Do NOT touch:**
- `ui/src/audio/speechInput.ts` — the underlying SpeechRecognition wrapper stays as-is. The error event already surfaces through `onError` ([speechInput.ts:104](ui/src/audio/speechInput.ts#L104)); this AD reads it through the existing chain.
- The wake-word ONNX path — out of scope. This AD covers mic permission only; ONNX load failure has its own fallback reason and continues to behave as today.
- `package.json` (no new deps; `navigator.mediaDevices` is a Web API platform standard).
- Any Python file. This is a pure UI change.

---

## Section 1 — Extend the state machine in `wakeWord.ts`

### 1a. Add the `MicPermissionState` type

In [ui/src/audio/wakeWord.ts](ui/src/audio/wakeWord.ts), after the existing `WakeFallbackReason` declaration (line 40), insert:

```typescript
/** AD-736: explicit mic-permission state machine. Separate from
 *  ``WakeWordState`` — the wake loop can be ``off`` for multiple
 *  reasons (mic denied, ONNX missing, SR unavailable); this enum
 *  captures the *mic-permission* subset for Captain-visible UX. */
export type MicPermissionState =
  | 'pending'       // not yet asked
  | 'granted'       // permission held; loop is functional
  | 'denied'        // browser actively refused or revoked
  | 'unavailable';  // no mic hardware OR SR unsupported in this browser

const _micPermissionListeners = new Set<(s: MicPermissionState) => void>();
let _micPermissionState: MicPermissionState = 'pending';

/** AD-736: subscribe to mic-permission state changes. Returns unsubscribe fn. */
export function onMicPermissionState(
  fn: (s: MicPermissionState) => void,
): () => void {
  _micPermissionListeners.add(fn);
  // Fire current state synchronously so subscribers don't need a separate getter.
  try { fn(_micPermissionState); } catch (err) { console.warn('[wakeWord] mic listener error', err); }
  return () => { _micPermissionListeners.delete(fn); };
}

/** AD-736: read the current mic-permission state. Synchronous; no Promise. */
export function getMicPermissionState(): MicPermissionState {
  return _micPermissionState;
}

function _setMicPermission(next: MicPermissionState): void {
  if (next === _micPermissionState) return;
  _micPermissionState = next;
  for (const fn of _micPermissionListeners) {
    try { fn(next); } catch (err) { console.warn('[wakeWord] mic listener error', err); }
  }
}
```

### 1b. Pre-flight feature-detect at `startWakeWordLoop`

Find the SR-support check at [wakeWord.ts:145-150](ui/src/audio/wakeWord.ts#L145-L150):

```typescript
  // Speech recognition is mandatory for both ONNX and fallback paths.
  if (!isSpeechRecognitionSupported()) {
    _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
    _emitFallbackToast(
      'Voice loop unavailable: SpeechRecognition not supported in this browser.',
    );
    return;
  }
```

Replace with:

```typescript
  // AD-736: feature-detect SR support, then hardware presence. The two
  // failure modes carry different Captain-facing guidance, so distinguish
  // them at the boundary.
  if (!isSpeechRecognitionSupported()) {
    _setMicPermission('unavailable');
    _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
    _emitFallbackToast(
      'Voice loop unavailable: SpeechRecognition not supported in this browser.',
    );
    return;
  }

  // Tier-2: hardware probe. If enumerateDevices is unavailable or rejects,
  // fall through optimistically — the SR onerror path will still catch
  // denial. Optimism preserves backward compat with browsers (Safari < 14)
  // that gate mediaDevices behind getUserMedia.
  try {
    const mediaDevices = navigator.mediaDevices;
    if (mediaDevices && typeof mediaDevices.enumerateDevices === 'function') {
      const devices = await mediaDevices.enumerateDevices();
      const hasAudioInput = devices.some(d => d.kind === 'audioinput');
      if (!hasAudioInput) {
        _setMicPermission('unavailable');
        _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
        console.info('[wakeWord] no audio input device detected; voice loop disabled');
        return;
      }
    }
  } catch (err) {
    // Tier-2 log-and-degrade: enumeration failed (rare on modern browsers).
    // Continue and let SR onerror surface the real failure mode.
    console.warn('[wakeWord] enumerateDevices probe failed; continuing', err);
  }
```

### 1c. Update the `'not-allowed'` / `'service-not-allowed'` error path

Find [wakeWord.ts:230-238](ui/src/audio/wakeWord.ts#L230-L238):

```typescript
    (err) => {
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        _setState('off', { fallbackReason: 'mic_permission_denied' });
        _emitFallbackToast(
          'Voice loop disabled: microphone permission denied.',
        );
        _teardown();
      }
      // Other errors are transient; speechInput auto-restarts.
    },
```

Replace with:

```typescript
    (err) => {
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        _setMicPermission('denied');
        _setState('off', { fallbackReason: 'mic_permission_denied' });
        _emitFallbackToast(
          'Voice loop disabled: microphone permission denied.',
        );
        _teardown();
      } else if (err === 'audio-capture') {
        // AD-736: SpeechRecognition.error 'audio-capture' = mic hardware
        // problem (disconnected, in use by another app). Distinct from
        // permission denial; surfaces as 'unavailable'.
        _setMicPermission('unavailable');
        _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
        console.info('[wakeWord] audio-capture error; voice loop disabled');
        _teardown();
      }
      // Other errors are transient; speechInput auto-restarts.
    },
```

### 1d. Set `granted` on the first successful transcript

In `_ingestTranscript` ([wakeWord.ts:249](ui/src/audio/wakeWord.ts#L249) — pass-1 review corrected from earlier draft's "262+"), find the SEARCH block:

```typescript
function _ingestTranscript(transcript: string): void {
  if (_bargedIn) return;
  if (_state === 'off') return;
```

Replace with:

```typescript
function _ingestTranscript(transcript: string): void {
  // AD-736: receiving any transcript means SR ran successfully, which
  // means the browser honoured the mic-permission grant. Promote state
  // once — subsequent calls short-circuit because _setMicPermission is
  // idempotent.
  if (_micPermissionState !== 'granted') {
    _setMicPermission('granted');
  }
  if (_bargedIn) return;
  if (_state === 'off') return;
```

### 1e. Reset on `stopWakeWordLoop`

In `_teardown` (called by `stopWakeWordLoop`), add at the end:

```typescript
  // AD-736: when the loop tears down, mic-permission state reverts to
  // pending UNLESS we know the browser refused permission. Permanent
  // denial sticks until page reload (the browser does not re-prompt).
  if (_micPermissionState !== 'denied' && _micPermissionState !== 'unavailable') {
    _setMicPermission('pending');
  }
```

Confirm in the test that this transition logic matches expectations.

---

## Section 2 — `MicPermissionHint.tsx` component

Create [ui/src/components/MicPermissionHint.tsx](ui/src/components/MicPermissionHint.tsx) (NEW):

```tsx
/** AD-736: Captain-visible mic permission state surface.
 *
 *  Subscribes to ``onMicPermissionState`` and renders one of:
 *    - 'pending' → nothing (loop will probe on first activation)
 *    - 'granted' → nothing (default operational state)
 *    - 'denied' → mic SVG + one-line dismissible hint ("Click the
 *                  microphone icon in your browser's address bar")
 *    - 'unavailable' → mic SVG (dim) + one-line non-dismissible label
 *                       ("No microphone detected")
 *
 *  Dismissal is sticky per state via ``localStorage`` so refresh keeps it.
 */
import { useEffect, useState } from 'react';
import {
  onMicPermissionState,
  type MicPermissionState,
} from '../audio/wakeWord';

const DISMISS_KEY = 'hxi_mic_hint_dismissed';

export function MicPermissionHint(): JSX.Element | null {
  const [state, setState] = useState<MicPermissionState>('pending');
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    return onMicPermissionState(setState);
  }, []);

  if (state === 'pending' || state === 'granted') return null;
  if (state === 'denied' && dismissed) return null;

  const isDenied = state === 'denied';
  const stroke = isDenied ? '#f0b060' : '#666680';
  const message = isDenied
    ? "Voice input blocked. Click the microphone icon in your browser's address bar to enable it, then refresh."
    : 'No microphone detected. Voice input is disabled.';

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="mic-permission-hint"
      data-state={state}
      style={{
        position: 'fixed',
        bottom: 12,
        right: 12,
        maxWidth: 320,
        padding: '8px 10px',
        background: 'rgba(20, 20, 32, 0.92)',
        border: `1px solid ${stroke}33`,
        borderRadius: 4,
        color: '#e0dcd4',
        fontSize: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        zIndex: 1000,
      }}
    >
      {/* Inline SVG mic glyph (HXI Design Principle #3). */}
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        aria-hidden="true"
        style={{ flexShrink: 0 }}
      >
        <rect x="6" y="2" width="4" height="8" rx="2" />
        <path d="M3 7v1a5 5 0 0 0 10 0V7" />
        <path d="M8 13v2" />
        {!isDenied && <path d="M3 3l10 10" />}
      </svg>
      <span style={{ flex: 1 }}>{message}</span>
      {isDenied && (
        <button
          type="button"
          aria-label="Dismiss hint"
          data-testid="mic-permission-dismiss"
          onClick={() => {
            try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* tier-1 */ }
            setDismissed(true);
          }}
          style={{
            border: 'none',
            background: 'transparent',
            color: '#8888a0',
            cursor: 'pointer',
            fontSize: 14,
            padding: '0 4px',
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}
```

Notes:
- The slash line `<path d="M3 3l10 10" />` is drawn only in the `unavailable` state, mirroring the muted-speaker glyph in `DecisionSurface.tsx:142`. Denied state shows the unstruck mic because the hardware is fine; the *permission* is what's missing.
- `role="status"` + `aria-live="polite"` ensures screen readers announce the message once.
- The dismiss button (`×`) is text-only, not an emoji — `×` is U+00D7 multiplication sign, standard typography.

### Mount the component

In [`ui/src/App.tsx`](ui/src/App.tsx) (the verified HXI root — see pass-1 review), find the SEARCH block at the overlay-mount region (around line 167-185):

```tsx
      <GlassLayer />
      <IntentSurface />
      <DecisionSurface />
      <AgentTooltip />
```

Replace with:

```tsx
      <GlassLayer />
      <IntentSurface />
      <DecisionSurface />
      <AgentTooltip />
      {/* AD-736: mic-permission state surface (renders only on denied/unavailable). */}
      <MicPermissionHint />
```

Add the import alongside the other component imports at the top of `App.tsx`:

```tsx
import { MicPermissionHint } from './components/MicPermissionHint';
```

---

## Section 3 — Tests

### 3a. `ui/src/audio/__tests__/wakeWord.micPermission.test.ts` (NEW) — 5 tests

1. **`test_initial_state_is_pending`** — Import `getMicPermissionState`; assert it returns `'pending'` before `startWakeWordLoop` is called.
2. **`test_unavailable_when_speech_recognition_not_supported`** — Stub `window.SpeechRecognition` and `window.webkitSpeechRecognition` to `undefined`. Call `startWakeWordLoop`. Assert state becomes `'unavailable'`.
3. **`test_unavailable_when_no_audio_input_device`** — Stub `navigator.mediaDevices.enumerateDevices` to resolve `[{ kind: 'videoinput', ... }]` (no `audioinput`). Call `startWakeWordLoop`. Assert state becomes `'unavailable'`.
4. **`test_denied_when_sr_emits_not_allowed`** — Mount the loop with a stubbed `SpeechRecognition` that fires `onerror({ error: 'not-allowed' })` immediately after `start()`. Assert state transitions to `'denied'` and `_setState('off', ...)` is called.
5. **`test_granted_on_first_transcript`** — Drive the loop to `armed` via `_simulateWakeFire` (or by injecting a transcript via the stubbed SR). Assert state transitions to `'granted'`.

(Optional 6th test if scope allows: `test_listener_fires_synchronously_on_subscribe` — subscribe via `onMicPermissionState`, assert the callback fires immediately with the current state.)

### 3b. `ui/src/components/__tests__/MicPermissionHint.test.tsx` (NEW) — 2 tests

1. **`test_hint_renders_only_for_denied_or_unavailable`** — Mount `<MicPermissionHint />`. Drive `onMicPermissionState` listeners to each of the four states. Assert: pending → no render; granted → no render; denied → render with `data-state="denied"`; unavailable → render with `data-state="unavailable"`.
2. **`test_denied_hint_dismiss_persists_across_remount`** — Mount, drive to `'denied'`, click the dismiss button, unmount, re-mount, drive to `'denied'` again. Assert the hint does NOT render on the second mount because `localStorage[DISMISS_KEY]` was set.

---

## Section 4 — What this does NOT change

- **Wake-word algorithm.** ONNX path, substring fallback, transcript pump — all unchanged.
- **`speechInput.ts`.** The SpeechRecognition wrapper still emits `onError(err)` with the same payload; this AD reads it through the existing chain.
- **AD-705 wake-word state names.** `armed` / `capturing` / `fallback-armed` / `fallback-capturing` / `off` are unchanged; `MicPermissionState` is a SEPARATE enum.
- **HXI shell layout.** The hint is a fixed-position overlay; no flexbox change to existing surfaces.
- **`navigator.permissions.query`.** Not used — Safari support is uneven; `enumerateDevices` + SR error event give the same information with better cross-browser coverage.
- **Retry button.** Out of scope for v1. The browser address-bar icon is the canonical recovery path; a retry button would re-prompt and fail in Chrome's permanent-deny state.
- **No Python change.** Pure UI.
- **No new deps.** `navigator.mediaDevices.enumerateDevices` is a Web API.
- **AD-731 attachment invariant respected.** This change does not touch the bus, RPC, or any attachment path.

---

## Section 5 — Verification commands

```powershell
cd ui

# Focused gates for the new files
npx vitest run src/audio/__tests__/wakeWord.micPermission.test.ts
npx vitest run src/components/__tests__/MicPermissionHint.test.tsx

# Full UI gate
npx vitest run
```

Live verification (operator-driven, post-commit):

1. Open the HXI in Chrome. When the mic permission prompt appears, click "Block."
2. Confirm the bottom-right hint appears: "Voice input blocked. Click the microphone icon in your browser's address bar to enable it, then refresh."
3. Confirm the dismiss × works and the hint stays dismissed across page refresh.
4. Disconnect the microphone (or test on a desktop with no mic). Reload. Confirm the dim-mic hint appears: "No microphone detected. Voice input is disabled." (no dismiss button).
5. Re-grant permission via the address bar, refresh. Confirm the hint disappears.

---

## Section 6 — Tracker updates

- **`PROGRESS.md`** — Wave 156 entry. Add tests count delta (+7 Vitest = 5 state-machine + 2 component). Reference AD-736 + closure of [#558](https://github.com/seangalliher/ProbOS/issues/558).
- **`DECISIONS.md`** — Append AD-736 closure block. Cite: (a) the four-state machine, (b) `enumerateDevices` hardware probe with `audio-capture` SR-error fallback, (c) localStorage dismissal key `hxi_mic_hint_dismissed`, (d) HXI Design Principle #3 honoured (inline SVG mic, no emoji), (e) AD-705 parent reference.
- **`docs/development/roadmap.md`** — Mark AD-736 shipped Wave 156; close [#558](https://github.com/seangalliher/ProbOS/issues/558).

---

## Section 7 — License Disposition

| Item | License | Posture |
|---|---|---|
| ProbOS code added | Apache 2.0 (matches repo) | New files `MicPermissionHint.tsx` + tests + edits to `wakeWord.ts` carry the same license posture as the rest of the repo. |

- **No external code absorption.** No third-party module copied; no upstream pattern adapted; no model weights.
- **No new dependencies.** `package.json` unchanged. `navigator.mediaDevices.enumerateDevices` is a Web API platform standard.
- **All-internal confirmed.** This is HXI surface refinement on top of the existing AD-705 wake-word loop.

---

## Forward markers

- **`navigator.permissions.query({ name: 'microphone' })` integration** — when Safari support stabilises, the permission state can be queried directly instead of inferred from SR errors. v2 may use this if available, fallback to current heuristic otherwise.
- **Retry button** — if Captains ask for "Try again" without manual address-bar click, a forward AD can add a button that calls `navigator.mediaDevices.getUserMedia({ audio: true })` to re-trigger the prompt (works in some browsers but not Chrome after permanent deny).
- **Per-page mic prompt** — currently the loop prompts on the FIRST `startWakeWordLoop`. If Captains find the prompt timing surprising, a forward AD can defer the prompt to first manual activation (clicking the voice button) instead of auto-arming.

---

## Acceptance criteria

- ✅ `MicPermissionState` enum exported from `wakeWord.ts`.
- ✅ `onMicPermissionState` listener API + `getMicPermissionState` synchronous read.
- ✅ State transitions correctly for: SR unsupported, no audio device, permission denied, transcript received, audio-capture hardware error.
- ✅ `MicPermissionHint.tsx` mounts once at HXI root and renders only in `denied` or `unavailable` states.
- ✅ Dismiss button persists via `localStorage[hxi_mic_hint_dismissed]`.
- ✅ No emoji; inline SVG mic glyph with `strokeWidth: 1.5`.
- ✅ ≥ 4 new Vitest tests for the state machine; 2 new component tests for the hint.
- ✅ Full UI gate green; full Python gate unchanged.
- ✅ `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md` updated.
- ✅ GH issue [#558](https://github.com/seangalliher/ProbOS/issues/558) closed with the merge commit.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-13)

```
Existing wake-word state machine to extend:
  ui/src/audio/wakeWord.ts:32-37        export type WakeWordState
  ui/src/audio/wakeWord.ts:38-40        export type WakeFallbackReason
                                          | 'onnx_load_failed'
                                          | 'mic_permission_denied'
                                          | 'speech_recognition_unavailable'
  ui/src/audio/wakeWord.ts:145-150      isSpeechRecognitionSupported() gate
  ui/src/audio/wakeWord.ts:230-238      onError 'not-allowed' / 'service-not-allowed' path
  ui/src/audio/wakeWord.ts:249          _ingestTranscript definition (corrected; earlier draft said 262+)
  ui/src/audio/wakeWord.ts:463-471      _emitFallbackToast (console.warn only — no UI)

HXI root mount point (corrected; HXIShell.tsx does NOT exist):
  ui/src/App.tsx:169                    <DecisionSurface /> mount line (insertion anchor)
  ui/src/App.tsx:167-185                top-level overlay region (GlassLayer, IntentSurface,
                                          DecisionSurface, AgentTooltip, AgentProfilePanel, ...)

Underlying SR error surface:
  ui/src/audio/speechInput.ts:102-104   recognition.onerror → onError?.(event.error)

Inline SVG icon family to match:
  ui/src/components/DecisionSurface.tsx:135-146   speaker SVG (stroke=#ffcc66 active, #8888aa inactive)
                                          The mic in this prompt mirrors the same stroke + slash convention.

State-machine pattern to mirror (existing onSpeechEvent / onWakeWordState):
  ui/src/audio/voice.ts:33-46           onSpeechEvent listener registration
  ui/src/audio/wakeWord.ts:80-86        onWakeWordState listener registration
```

---

## Revision (2026-05-13)

Pass-1 review addressed both Required findings:

1. **R1 — Mount-point file corrected.** Earlier draft named `ui/src/HXIShell.tsx` (does not exist; verified via `file_search`). Re-anchored to [`ui/src/App.tsx`](ui/src/App.tsx) with explicit SEARCH/REPLACE in Section 2 (insertion adjacent to `<AgentTooltip />` at line ~170, after `<DecisionSurface />` at line 169). Import added next to existing component imports. Section 0 file table updated.
2. **R2 — `_ingestTranscript` line reference corrected** from "262+" to **249** (verified via `grep _ingestTranscript`). Section 1d now provides an explicit SEARCH block (`function _ingestTranscript(transcript: string): void {\n  if (_bargedIn) return;\n  if (_state === 'off') return;`) so the insertion point is unambiguous instead of "at the first line of the function".
3. **Verified Against Codebase block** updated with the corrected line number and the new App.tsx mount anchor.

Recommended findings (R1-R5) deferred — they are observability / minor style nits and do not block the build:
- `_teardown` SEARCH block: deferred (the inline location is unambiguous given the single function body).
- `audio-capture` SR error string: not blocking; the spec lists it and `speechInput.ts:102-104` already passes through `event.error`.
- Listener-error log severity: borderline, accept as-is.
- `role="status"` aria refinement: minor a11y polish.
- HTTPS / secure-context comment: documentation only.

Nits (3) accepted as-shipped; closure note will mention them as future cleanup candidates.

No scope change; no new files beyond those listed in Section 0.
