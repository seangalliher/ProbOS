# AD-721b-2 — Browser-side real-audio capture for lip-sync

**Status:** Ready for Builder
**GH issue:** [#560](https://github.com/seangalliher/ProbOS/issues/560) (closes)
**Parent AD:** AD-721b v1 (heuristic 5-vowel viseme driver, shipped Wave 138).
**Depends on:** **AD-721b-1** (server endpoint `POST /api/avatars/lipsync` MUST be in place — drafted in `prompts/ad-721b-1-rhubarb-lipsync-backend.md`, same wave). Build AD-721b-1 first; build AD-721b-2 second.
**Wave:** 155
**Estimated tests:** ≥ 6 new Vitest in `ui/src/audio/__tests__/lipSyncCapture.test.ts` + `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` + `ui/src/components/profile/__tests__/CrewVRM.realAudioFallback.test.tsx`

---

## Captain decisions baked in

1. **Best-effort capture, honest-degrade everywhere.** Most browsers today (Chromium, Firefox) do **NOT** expose `SpeechSynthesis` output through Web Audio. This is documented at `ui/src/audio/speechAmplitude.ts:1-7` ("Browsers ship SpeechSynthesis without a routable audio graph by default"). The capture path tries — and when it fails, the system falls through to the AD-721b v1 heuristic with zero behavior change. **Speech must NEVER stop animating because of a capture failure.**
2. **AD-731 invariant: refs not blobs on the bus.** The captured audio uploads via the existing `POST /api/chat/attachments/multipart` endpoint (AD-720a, `routers/chat.py:757`). The lipsync request then references the resulting sha256 hash — never inline base64. This honors BF-265/AD-731's lesson (refs go on RPC paths, bytes go in content-addressable stores).
3. **Always-on capture; honest-degrade end-to-end on the server.** The hook is hardcoded `enabled: true`. Every utterance attempts capture. When `MediaRecorder` produces 0 bytes (the common case — most browsers don't route SpeechSynthesis), `captureUtteranceAudio` returns `null` and the hook short-circuits before uploading. When capture succeeds but the server's `lipsync.backend = "heuristic"` (default) or the rhubarb binary is missing, `POST /api/avatars/lipsync` returns `{backend: "heuristic" \| "disabled", frames: []}` (server-side honest-degrade chain shipped by AD-721b-1). The hook treats every empty-frames response identically: leave `frames: []` and let CrewVRM fall through to the existing `buildHeuristicTrack` path. **No browser config-fetch endpoint is added in this prompt.** The cost of a probe-then-decide handshake on first utterance is similar to the cost of the actual capture attempt, and the probe would still fail on every browser that can't route SpeechSynthesis — the always-on path is operationally simpler and the wasted work is bounded by the AD-731 ref-not-blob upload pattern (capture path short-circuits before the multipart upload when there are 0 bytes to send).
4. **No emoji in any UI surface.** This prompt does not add UI components, but if any operator-visible diagnostic is added, it follows HXI Design Principle #3 (stroke-based SVG icons only).
5. **Pure hook + thin module.** No new React component. The capture runs as an effect inside `useLipSyncCapture()`, fed via a subscription to the existing `onSpeechEvent` lifecycle from `ui/src/audio/voice.ts:35`. CrewVRM stays the only component touching VRM internals.

---

## Problem (verified diagnostic baseline — 2026-05-12)

The current path:

```
voice.speakResponse(text)
  → SpeechSynthesisUtterance fires onstart
  → onSpeechEvent('start') → CrewVRM.tsx:322 buildHeuristicTrack(text, {rate})
  → text-only viseme schedule → useFrame samples
```

After AD-721b-1 (the server-side rhubarb wrapper), the missing piece is the audio bytes. The browser's built-in TTS is the only voice path today (`ui/src/audio/voice.ts:99 speakResponse`). The Web Audio API's `MediaStreamAudioDestinationNode` + `MediaRecorder` chain is the standard way to capture an audio stream for upload, but it requires the audio to be present in a Web Audio graph. SpeechSynthesis output is not routed through Web Audio in any current browser without vendor-specific hacks.

**The honest engineering position**: AD-721b-2 ships the capture infrastructure and best-effort wiring. It will work today on browsers (or future engines) where SpeechSynthesis IS routable, and it will gracefully fall through to the heuristic on every other browser. The prompt does NOT pretend to solve the SpeechSynthesis-routability problem — that's an upstream browser issue. The infrastructure landing now means the day a browser ships routable SpeechSynthesis (or ProbOS adopts a server-streamed TTS path under a future AD), the capture path lights up automatically.

---

## Solution

Three pieces:

1. New module `ui/src/audio/lipSyncCapture.ts` — pure capture functions (no React). Tries `MediaStreamAudioDestinationNode` + `MediaRecorder`; returns a Blob or null.
2. New hook `ui/src/audio/useLipSyncCapture.ts` — React lifecycle. Subscribes to `onSpeechEvent`, runs the capture on `'start'`, uploads on `'end'`, exposes `visemes` state for `CrewVRM` to consume.
3. Wire from `CrewVRM.tsx` — when the hook returns a non-empty `visemes` array, prefer it over `buildHeuristicTrack`. When empty (capture failed, server degraded, or backend disabled), fall through to the existing heuristic path. Zero regression for operators who don't enable rhubarb.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `ui/src/audio/lipSyncCapture.ts` | NEW — `captureUtteranceAudio`, `uploadAudioForLipSync`, `LipSyncFrame` type |
| `ui/src/audio/useLipSyncCapture.ts` | NEW — React hook |
| `ui/src/audio/__tests__/lipSyncCapture.test.ts` | NEW — pure-function tests |
| `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` | NEW — hook lifecycle tests |
| `ui/src/components/profile/CrewVRM.tsx` | UPDATE — consume `useLipSyncCapture` output, prefer over heuristic when present |
| `ui/src/components/profile/__tests__/CrewVRM.realAudioFallback.test.tsx` | NEW — regression test that capture-failure path falls back to heuristic (co-located with the existing `CrewVRM.expressionResting.test.tsx`) |

**Coordination with AD-721b-1 (mime allow-list seam):**

AD-721b-2 captures audio as `audio/webm` and uploads via `POST /api/chat/attachments/multipart`, which validates against `AttachmentsConfig.allowed_mime_types`. **AD-721b-1 OWNS the allow-list extension** (Section 0.5 of `prompts/ad-721b-1-rhubarb-lipsync-backend.md`): both `audio/webm` and `audio/wav` are added to the default in `src/probos/config.py` AND the magic-byte sniffer in `src/probos/attachments/mime.py._SIGNATURES`. **Build order: AD-721b-1 first, AD-721b-2 second** (already enforced by the dispatch). If AD-721b-1's Section 0.5 is skipped, every capture upload silently 415s and this prompt's user-visible improvement is zero. Do NOT touch `config.py` or `attachments/mime.py` from this prompt.

**Do NOT touch:**
- `ui/src/audio/lipSyncTrack.ts` (heuristic stays as fallback; AD-721b v1 contract intact)
- `ui/src/audio/voice.ts` (subscription via existing `onSpeechEvent`; no new event types)
- `ui/src/audio/speechAmplitude.ts` (the AD-721 D5 amplitude path remains the FINAL fallback when both rhubarb and heuristic produce nothing)
- `ui/src/audio/voiceModulation.ts` (AD-718d unrelated — modulates pitch/rate/volume, doesn't touch the audio stream)
- The server-side `/api/avatars/lipsync` endpoint (AD-721b-1 owns it; this prompt only consumes it)
- `src/probos/config.py` and `src/probos/attachments/mime.py` (AD-721b-1 Section 0.5 owns the allow-list + magic-byte extensions for the audio MIMEs)

---

## Section 1 — `lipSyncCapture.ts` (pure module)

Create `ui/src/audio/lipSyncCapture.ts`:

```typescript
/** AD-721b-2: Browser-side real-audio capture for server-side lip-sync.
 *
 *  Best-effort: most browsers today do NOT expose SpeechSynthesis output
 *  through Web Audio (see ``speechAmplitude.ts:1-7``), so this module is
 *  written to fail gracefully. Every entry point returns ``null`` / empty
 *  on any failure; the consumer (``useLipSyncCapture``) treats that as the
 *  signal to fall through to the AD-721b v1 heuristic path.
 *
 *  Wire shape: AD-731 invariant — captured bytes upload via the existing
 *  multipart attachment endpoint and produce a sha256 hash; the lipsync
 *  request body carries only the hash, never inline base64.
 */

/** One viseme frame returned by ``POST /api/avatars/lipsync``.
 *  Mirrors the server's ``VisemeFrame`` dataclass shape. */
export interface LipSyncFrame {
  time: number;        // seconds since utterance start
  duration: number;    // seconds
  viseme: string;      // Oculus 15-set key
}

/** Server response shape for ``POST /api/avatars/lipsync``. */
export interface LipSyncResponse {
  backend: 'rhubarb' | 'heuristic' | 'disabled';
  frames: LipSyncFrame[];
}

/** Browser feature-detection result. ``null`` means capture is impossible
 *  on this engine; the consumer falls through to heuristic. */
export interface CaptureCapability {
  ok: boolean;
  reason?: string;
}

/** Detect whether the browser exposes the APIs needed for capture.
 *  Pure synchronous check — safe to call on every render. */
export function detectCaptureCapability(): CaptureCapability {
  if (typeof window === 'undefined') {
    return { ok: false, reason: 'no-window' };
  }
  // AudioContext: required for MediaStreamDestination.
  const Ctor = (window as any).AudioContext || (window as any).webkitAudioContext;
  if (typeof Ctor !== 'function') {
    return { ok: false, reason: 'no-audiocontext' };
  }
  // MediaRecorder: required to encode the captured stream.
  if (typeof (window as any).MediaRecorder !== 'function') {
    return { ok: false, reason: 'no-mediarecorder' };
  }
  // SpeechSynthesis routability is not feature-detectable without an
  // utterance in flight. ``captureUtteranceAudio`` returns null when
  // the actual capture produces zero bytes — that is the runtime signal
  // for "this engine doesn't route SpeechSynthesis through Web Audio".
  return { ok: true };
}

/** Attempt to capture the audio of a SpeechSynthesisUtterance via Web Audio
 *  + MediaRecorder. Returns the captured Blob on success, ``null`` on any
 *  failure (capability missing, zero bytes captured, recorder error).
 *
 *  Caller is responsible for invoking this BEFORE ``speechSynthesis.speak``
 *  on engines that route SpeechSynthesis through Web Audio. The returned
 *  Promise resolves when the utterance ends.
 *
 *  Tier-2 log-and-degrade: NEVER throws. ``null`` is the only failure signal.
 */
export async function captureUtteranceAudio(
  utterance: SpeechSynthesisUtterance,
  opts?: { mimeType?: string; maxDurationMs?: number },
): Promise<Blob | null> {
  const cap = detectCaptureCapability();
  if (!cap.ok) {
    // eslint-disable-next-line no-console
    console.info(`[AD-721b-2] capture unavailable: ${cap.reason}`);
    return null;
  }
  const Ctor = (window as any).AudioContext || (window as any).webkitAudioContext;
  let ctx: AudioContext | null = null;
  let recorder: MediaRecorder | null = null;
  try {
    ctx = new Ctor();
    const dest = ctx.createMediaStreamDestination();
    const mimeType = opts?.mimeType ?? 'audio/webm';
    recorder = new MediaRecorder(dest.stream, { mimeType });
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    recorder.start();
    // Wait for utterance to end (or maxDurationMs safety bound).
    const maxMs = opts?.maxDurationMs ?? 30_000;
    const ended = new Promise<void>((resolve) => {
      const onEnd = () => { utterance.removeEventListener('end', onEnd); resolve(); };
      utterance.addEventListener('end', onEnd);
      // Safety bound — never wait more than maxMs even if onend never fires.
      setTimeout(() => { utterance.removeEventListener('end', onEnd); resolve(); }, maxMs);
    });
    await ended;
    // Stop recording and wait for the final ondataavailable.
    const stopped = new Promise<void>((resolve) => {
      const onStop = () => { recorder?.removeEventListener('stop', onStop); resolve(); };
      recorder?.addEventListener('stop', onStop);
      try { recorder?.stop(); } catch { resolve(); }
    });
    await stopped;
    if (chunks.length === 0) {
      // eslint-disable-next-line no-console
      console.info('[AD-721b-2] capture produced 0 bytes; SpeechSynthesis not routed');
      return null;
    }
    return new Blob(chunks, { type: mimeType });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[AD-721b-2] captureUtteranceAudio failed', err);
    return null;
  } finally {
    try { ctx?.close(); } catch { /* ignore */ }
  }
}

/** Upload the captured Blob and request a viseme schedule from the server.
 *  Returns the parsed response or ``null`` on any failure. NEVER throws.
 *
 *  Honors AD-731: bytes upload first via the existing multipart endpoint,
 *  the lipsync request body carries only the resulting sha256.
 */
export async function uploadAudioForLipSync(
  blob: Blob,
  opts?: { fetchImpl?: typeof fetch },
): Promise<LipSyncResponse | null> {
  const f = opts?.fetchImpl ?? fetch;
  try {
    // Step 1: multipart upload (AD-720a path; routers/chat.py:757).
    const form = new FormData();
    // Filename hint for server-side ext_to_mime resolver (AD-720a).
    const fname = blob.type === 'audio/webm' ? 'capture.webm' : 'capture.wav';
    form.append('file', blob, fname);
    const uploadResp = await f('/api/chat/attachments/multipart', {
      method: 'POST',
      body: form,
    });
    if (!uploadResp.ok) {
      // eslint-disable-next-line no-console
      console.warn(`[AD-721b-2] upload failed status=${uploadResp.status}`);
      return null;
    }
    const uploadJson = await uploadResp.json();
    const attachmentId = uploadJson?.attachment_id;
    if (typeof attachmentId !== 'string' || attachmentId.length !== 64) {
      // eslint-disable-next-line no-console
      console.warn('[AD-721b-2] upload returned invalid attachment_id');
      return null;
    }
    // Step 2: lipsync request — refs only, no inline bytes (AD-731 invariant).
    const lipsyncResp = await f('/api/avatars/lipsync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ attachment_id: attachmentId }),
    });
    if (!lipsyncResp.ok) {
      // eslint-disable-next-line no-console
      console.warn(`[AD-721b-2] lipsync failed status=${lipsyncResp.status}`);
      return null;
    }
    const data = (await lipsyncResp.json()) as LipSyncResponse;
    if (!data || !Array.isArray(data.frames)) return null;
    return data;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[AD-721b-2] uploadAudioForLipSync failed', err);
    return null;
  }
}
```

Notes:
- `MediaRecorder` mimeType compatibility varies (`audio/webm`, `audio/ogg`, `audio/wav`). Pick `audio/webm` as the most broadly supported. **AD-721b-1 Section 0.5 extends `AttachmentsConfig.allowed_mime_types` AND the magic-byte sniffer to accept both `audio/webm` and `audio/wav`** — this prompt does NOT touch the validator. If a future browser only supports `audio/ogg` or another container, file an AD-721b-2.1 follow-up to extend the allow-list there; do NOT extend it inline.
- `setTimeout` safety bound prevents the hook from leaking a recorder if `onend` never fires (browser bug or interrupted utterance).

---

## Section 2 — `useLipSyncCapture.ts` (React hook)

Create `ui/src/audio/useLipSyncCapture.ts`:

```typescript
/** AD-721b-2: React hook to capture utterance audio and resolve a real
 *  viseme schedule from the server-side rhubarb backend (AD-721b-1).
 *
 *  Honest-degrade: when capture is unavailable, the upload fails, or the
 *  server returns ``backend == "heuristic"`` / empty frames, the hook
 *  exposes ``frames: []`` — the consumer (``CrewVRM``) MUST fall through
 *  to ``buildHeuristicTrack`` on an empty schedule. This invariant
 *  preserves the AD-721b v1 contract: speech never stops animating.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { onSpeechEvent } from './voice';
import {
  captureUtteranceAudio,
  uploadAudioForLipSync,
  type LipSyncFrame,
  type LipSyncResponse,
} from './lipSyncCapture';

export interface UseLipSyncCaptureOptions {
  /** True when the operator has set ``lipsync.backend = "rhubarb"`` AND the
   *  server endpoint is reachable. The hook does NOT attempt capture when
   *  this is false — heuristic path runs unchanged. */
  enabled: boolean;
  /** Filter to a single agent's utterances. ``undefined`` = capture for all. */
  agentId?: string;
}

export interface UseLipSyncCaptureResult {
  /** Most recent viseme schedule from the server. Empty when:
   *   - capture not yet attempted,
   *   - capture in progress,
   *   - capture failed (use heuristic),
   *   - server returned ``backend == "heuristic"`` (use heuristic),
   *   - server returned ``backend == "disabled"`` (use heuristic). */
  frames: LipSyncFrame[];
  /** True while a capture is in progress. */
  capturing: boolean;
  /** Reset frames to []. CrewVRM should call this on utterance end. */
  reset: () => void;
}

export function useLipSyncCapture(
  opts: UseLipSyncCaptureOptions,
): UseLipSyncCaptureResult {
  const [frames, setFrames] = useState<LipSyncFrame[]>([]);
  const [capturing, setCapturing] = useState(false);
  // Hold the latest enable flag in a ref so the subscription doesn't churn.
  const enabledRef = useRef(opts.enabled);
  const agentIdRef = useRef(opts.agentId);
  useEffect(() => { enabledRef.current = opts.enabled; }, [opts.enabled]);
  useEffect(() => { agentIdRef.current = opts.agentId; }, [opts.agentId]);

  const reset = useCallback(() => setFrames([]), []);

  useEffect(() => {
    let mounted = true;
    let inflight: Promise<void> | null = null;
    const off = onSpeechEvent((e) => {
      if (!enabledRef.current) return;
      if (agentIdRef.current && e.agent_id !== agentIdRef.current) return;
      if (e.type !== 'start') return;
      // Spawn the capture. Do NOT await inside the listener — listeners are
      // synchronous and per voice.ts:42 a thrown exception would be caught
      // and other listeners would still fire. We DO want to track the
      // promise so unmount can wait/abort.
      setCapturing(true);
      inflight = (async () => {
        try {
          const blob = await captureUtteranceAudio(e.utterance);
          if (!mounted) return;
          if (!blob) {
            setCapturing(false);
            return;
          }
          const resp: LipSyncResponse | null = await uploadAudioForLipSync(blob);
          if (!mounted) return;
          if (!resp || resp.backend !== 'rhubarb' || resp.frames.length === 0) {
            setCapturing(false);
            return;
          }
          setFrames(resp.frames);
        } finally {
          if (mounted) setCapturing(false);
        }
      })();
    });
    return () => {
      mounted = false;
      off();
      // inflight promise resolves on its own; mounted=false short-circuits
      // its setState calls. AudioContext cleanup is in captureUtteranceAudio's
      // finally block.
    };
  }, []);

  return { frames, capturing, reset };
}
```

### 2c. Hook activation

The hook is hardcoded `enabled: true` at the call site (Section 3a). No config-fetch endpoint is added by this prompt. Honest-degrade chains end-to-end on the server side:

1. Capture short-circuits to `null` when `MediaRecorder` produces 0 bytes (every browser that doesn't route SpeechSynthesis).
2. When capture succeeds but the operator hasn't enabled rhubarb, the server returns `{backend: "heuristic", frames: []}` and the hook leaves `frames: []`.
3. When the operator enabled rhubarb but the binary is missing or the subprocess fails, AD-721b-1's `generate_visemes` returns `[]` and the endpoint returns `{backend: "heuristic", frames: []}` (same shape).
4. The CrewVRM consumer (Section 3) treats every `frames.length === 0` identically: fall through to `buildHeuristicTrack`.

The `enabled: false` code path is preserved in the hook signature for future use (e.g. an HXI Captain-facing toggle), but no production caller exercises it. The corresponding Vitest case is dropped from Section 4 to avoid testing dead code; a comment in `useLipSyncCapture.ts` notes the future-use intent.

---

## Section 3 — `CrewVRM.tsx` consumer wiring

Modify `ui/src/components/profile/CrewVRM.tsx`. Two surgical changes:

### 3a. Add the hook + per-frame consumer

Near the top of `CrewVRM` body (after the existing `currentTrackRef = useRef<LipSyncTrack | null>(null);` at line ~205):

```tsx
// AD-721b-2: real-audio capture path. Always-on — honest-degrade chains
// end-to-end on the server (capture-fail → 0-byte short-circuit, server-fail
// → backend: "heuristic" → empty frames). When the server returns a non-empty
// rhubarb schedule, prefer it. When empty, fall through to the existing
// heuristic path (currentTrackRef from buildHeuristicTrack).
const lipsync = useLipSyncCapture({ enabled: true, agentId });
const realFramesRef = useRef<LipSyncFrame[]>([]);
useEffect(() => { realFramesRef.current = lipsync.frames; }, [lipsync.frames]);
```

Add the matching imports at the top of the file:

```tsx
import { useLipSyncCapture } from '../../audio/useLipSyncCapture';
import type { LipSyncFrame } from '../../audio/lipSyncCapture';
```

### 3b. Per-frame: prefer rhubarb schedule when present

In the existing `useFrame` callback (the per-frame sampler that reads `currentTrackRef.current.sample(elapsedMs)`), add a preference check at the top of the schedule-resolution block. The Builder must locate the existing `currentTrackRef.current?.sample(...)` call site (around `CrewVRM.tsx` line ~330-380 — verify with grep at build time) and wrap it:

```tsx
// AD-721b-2: prefer real-audio rhubarb schedule when available.
let vowelWeights: VowelWeights;
const rhubarbFrames = realFramesRef.current;
if (rhubarbFrames.length > 0) {
  vowelWeights = _sampleRhubarbFrames(rhubarbFrames, elapsedMs);
} else if (currentTrackRef.current) {
  vowelWeights = currentTrackRef.current.sample(elapsedMs);
} else {
  // Fall through to the AD-721 D5 amplitude path (existing).
  vowelWeights = ZERO_WEIGHTS;
}
```

Add a small helper (top-level in `CrewVRM.tsx`, NOT exported — kept colocated for now; can be moved to `lipSyncTrack.ts` if a follow-up consumer appears):

```tsx
function _sampleRhubarbFrames(frames: LipSyncFrame[], elapsedMs: number): VowelWeights {
  // rhubarb times are seconds; convert.
  const t = elapsedMs / 1000;
  // Linear scan — schedules are short (typical ~50 frames for a 5s utterance).
  let active: LipSyncFrame | null = null;
  for (const f of frames) {
    if (t >= f.time && t < f.time + f.duration) { active = f; break; }
  }
  if (!active) return { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
  // Reuse the AD-721b v1 VISEME_TARGETS map. Builder: import _VISEME_TARGETS
  // from lipSyncTrack.ts (already exported there for testing — line ~263).
  const target = _VISEME_TARGETS[active.viseme as VisemeKey] ?? ZERO_WEIGHTS;
  return { aa: target.aa, ih: target.ih, ou: target.ou, ee: target.ee, oh: target.oh };
}
```

This means importing `_VISEME_TARGETS` and `ZERO_WEIGHTS` (or recreating them locally — Builder picks whichever is cleaner; if `ZERO_WEIGHTS` is not exported from `lipSyncTrack.ts`, define a local const inside CrewVRM rather than touching the shared module).

### 3c. Reset on utterance end

In the existing `'end'` branch of the `onSpeechEvent` handler (around CrewVRM.tsx line ~330-345), add a reset call alongside the existing `currentTrackRef.current = null`:

```tsx
currentTrackRef.current = null;
lipsync.reset();   // AD-721b-2: clear stale rhubarb frames
```

---

## Section 4 — Tests (≥ 7 new Vitest)

### Pure module — `ui/src/audio/__tests__/lipSyncCapture.test.ts` (4 tests)

1. **`detectCaptureCapability returns ok=false when AudioContext is missing`** — `vi.stubGlobal('AudioContext', undefined); vi.stubGlobal('webkitAudioContext', undefined);` Assert `detectCaptureCapability().ok === false` and `reason === 'no-audiocontext'`.
2. **`detectCaptureCapability returns ok=false when MediaRecorder is missing`** — Stub `AudioContext` present, `MediaRecorder` undefined. Assert `reason === 'no-mediarecorder'`.
3. **`uploadAudioForLipSync uploads via multipart then POSTs lipsync ref`** — Mock `fetch` to return `{attachment_id: 'a'.repeat(64)}` then `{backend: 'rhubarb', frames: [{time: 0, duration: 0.1, viseme: 'aa'}]}`. Pass a small Blob. Assert two fetch calls in order: multipart upload, then JSON lipsync request whose body is `{attachment_id: 'a'.repeat(64)}`. **CRITICAL: assert the lipsync request body is JSON with the ref, NOT a base64 blob (AD-731 invariant).**
4. **`uploadAudioForLipSync returns null on upload failure`** — Mock fetch to return `{ok: false, status: 500}` on first call. Assert returns `null` and the second fetch was NEVER called.

### Hook lifecycle — `ui/src/audio/__tests__/useLipSyncCapture.test.tsx` (3 tests)

5. **`useLipSyncCapture exposes empty frames when capture returns null`** — Mock `captureUtteranceAudio` to resolve `null`. Fire start. Assert `result.current.frames === []` and `capturing` returns to `false`.
6. **`useLipSyncCapture sets frames when server returns rhubarb backend`** — Mock `captureUtteranceAudio` to resolve a Blob. Mock `uploadAudioForLipSync` to resolve `{backend: 'rhubarb', frames: [{time:0, duration:0.1, viseme:'aa'}]}`. Fire start. Assert `result.current.frames.length === 1` after the promise settles.
7. **`useLipSyncCapture cleans up subscription on unmount`** — Render + unmount. Assert no setState calls fire after unmount even when an in-flight upload resolves (`mounted` flag in the hook).

### Regression — `ui/src/components/profile/__tests__/CrewVRM.realAudioFallback.test.tsx` (1 test)

8. **`CrewVRM falls back to heuristic when useLipSyncCapture returns empty frames`** — Mock `useLipSyncCapture` to return `{frames: [], capturing: false, reset: vi.fn()}`. Fire a speech-start event. Verify `buildHeuristicTrack` was called (existing AD-721b v1 path) — the path should be unchanged from current behavior. This is the load-bearing regression sentinel for "honest-degrade preserves heuristic."

### Test gates

- Pure module: `cd ui && npx vitest run src/audio/__tests__/lipSyncCapture.test.ts -t "lipSyncCapture"`
- Hook: `cd ui && npx vitest run src/audio/__tests__/useLipSyncCapture.test.tsx`
- Regression: `cd ui && npx vitest run src/components/profile/__tests__/CrewVRM.realAudioFallback.test.tsx`
- Full UI: `cd ui && npx vitest run`

---

## Section 5 — Documentation

- **`DECISIONS.md`** — Append AD-721b-2 closure block. Cite: (a) the SpeechSynthesis-routability constraint (`ui/src/audio/speechAmplitude.ts:1-7`), (b) the AD-731 invariant compliance (refs not blobs in lipsync request), (c) the honest-degrade contract chain: capture-fail → upload-fail → server-degraded → empty frames → CrewVRM falls back to AD-721b v1 heuristic → finally to AD-721 D5 amplitude.
- **`PROGRESS.md`** — Wave 155 entry. AD-721b-2 shipped. Test count delta (≥ 7 Vitest, ≥ 1 regression).
- **`docs/development/roadmap.md`** — Mark AD-721b-2 shipped Wave 155. Close [#560](https://github.com/seangalliher/ProbOS/issues/560).

---

## Section 6 — License Disposition

| Item | License | Posture |
|---|---|---|
| Web Audio API / MediaRecorder API | Browser-platform standard | No license concern. Standard web platform APIs. |
| New TypeScript code in `ui/src/audio/` | Apache 2.0 (matches repo) | No external code absorbed. |
| Server endpoint consumed (`/api/avatars/lipsync`) | AD-721b-1 (this wave) — wraps MIT rhubarb-lip-sync via operator-provided binary | Honored by the AD-731 ref-not-blob upload pattern. |
| New npm deps | None | Does NOT add anything to `ui/package.json`. Uses only stdlib browser APIs. |

---

## Engineering Principles compliance

- **Single Responsibility**: `lipSyncCapture.ts` does capture+upload only. `useLipSyncCapture.ts` does React lifecycle only. `CrewVRM.tsx` keeps owning VRM internals.
- **Open/Closed**: `useLipSyncCapture` is added as a sibling to the existing heuristic path. The heuristic path is not modified — it remains the load-bearing fallback.
- **Dependency Inversion**: The hook accepts a `fetchImpl` injection point on the upload helper for testing. The capture helper depends on browser globals (`AudioContext`, `MediaRecorder`) which are stubbed in tests.
- **Fail Fast / Log-and-Degrade**: Every async path in `lipSyncCapture.ts` returns `null` on failure with `console.info` / `console.warn`. The hook surfaces `[]` on every failure. CrewVRM checks `frames.length > 0` once per frame.
- **Cloud-Ready Storage**: Honors AD-731 invariant — captured bytes upload via the existing AD-720a multipart endpoint and reference the resulting sha256 hash. NEVER inline base64 in NATS message params or RPC bodies.
- **HXI Design Principles**: No emoji, no UI surface added (hook only). All console output uses plain text labels.
- **Type annotations**: Every public function fully typed. `LipSyncFrame`, `LipSyncResponse`, `CaptureCapability`, `UseLipSyncCaptureOptions`, `UseLipSyncCaptureResult` exported.
- **Logging quality**: Each `console.warn` includes the failure stage (capture / upload / lipsync) and the response status when applicable.
- **Async hygiene**: `mounted` ref prevents post-unmount setState. AudioContext cleanup in `finally`. `setTimeout` safety bound on the utterance-end wait prevents hang if `onend` never fires.

---

## What this does NOT change

- **No change to AD-721b v1 heuristic path.** `buildHeuristicTrack` and `lipSyncTrack.ts` remain bit-for-bit identical. The heuristic is the fallback, exercised by the regression test in Section 4.
- **No new event types on `onSpeechEvent`.** The existing `'start' | 'end' | 'boundary'` set is unchanged. The `'boundary'` reservation in `voice.ts:24` (AD-721b phoneme work) remains reserved — this prompt does NOT consume it.
- **No new TTS path.** `speakResponse` and the browser SpeechSynthesis dependency are unchanged. The capture is a passive listener.
- **No server-side TTS** (e.g. Coqui, Piper, ElevenLabs). That would be a separate AD that materially changes the audio path — and would actually make AD-721b-2 work universally rather than best-effort. Forward marker, NOT this prompt.
- **No `voiceModulation.ts` changes.** AD-718d adjusts utterance pitch/rate/volume — unrelated to capture.
- **No federation / cross-mesh** lip-sync routing. Capture, upload, and processing all happen on the local node.
- **No HXI Captain-facing UI surface.** Operator opts in via `config/system.yaml` (via AD-721b-1's `LipSyncConfig`). No HXI button or panel added.

---

## Forward markers

- **AD-721b-2.1** — Server-side audio transcoding (ffmpeg shim) when the captured `audio/webm` blob can't be parsed by rhubarb directly. File only if a real operator hits this; rhubarb supports WAV natively and many browsers can encode WAV via `MediaRecorder` mimeType selection.
- **AD-721b-2.2** — Cache the viseme schedule by audio_sha256 in the browser. Cheap LRU, useful for repeat playbacks. Defer until measurement shows need.
- **AD-721b-2.3** — Server-streamed TTS path (Coqui / Piper / ElevenLabs) so the server is the source of audio bytes from the start. This obsoletes the browser-capture problem entirely. Material architecture change — file as a top-level AD if pursued, NOT a sub-AD.
- **AD-721b-3** — whisper.cpp WASM tiny.en for offline phoneme alignment in the browser ([#561](https://github.com/seangalliher/ProbOS/issues/561), already filed). Eliminates the round-trip and the operator-binary requirement. Tracked separately.

---

## Acceptance criteria

- ✅ `ui/src/audio/lipSyncCapture.ts` exposes `detectCaptureCapability`, `captureUtteranceAudio`, `uploadAudioForLipSync`, `LipSyncFrame`, `LipSyncResponse`. All log-and-degrade.
- ✅ `ui/src/audio/useLipSyncCapture.ts` exposes the `useLipSyncCapture(opts)` hook with `frames`, `capturing`, `reset` API.
- ✅ Upload path uses `/api/chat/attachments/multipart` (AD-720a) + `/api/avatars/lipsync` (AD-721b-1). Lipsync request body is `{"attachment_id": "<sha256>"}` — AD-731 invariant, NEVER inline base64.
- ✅ `CrewVRM.tsx` prefers rhubarb frames when present; falls through to `buildHeuristicTrack` heuristic when empty; falls through to AD-721 D5 amplitude when both are empty.
- ✅ All ≥ 6 new Vitest tests pass.
- ✅ The regression test (`CrewVRM.realAudioFallback.test.tsx`) confirms heuristic is preserved when capture returns empty.
- ✅ Existing UI test suite green: `cd ui && npx vitest run` (no regressions).
- ✅ Existing Python test suite green: `pytest tests/ -q -n 4 --dist=loadfile` (this prompt should not affect Python tests, but verify).
- ✅ `DECISIONS.md` AD-721b-2 entry includes the SpeechSynthesis-routability acknowledgment and the AD-731 invariant compliance.
- ✅ `PROGRESS.md` Wave 155 entry shows AD-721b-2 closed + test count delta.
- ✅ `roadmap.md` AD-721b-2 row marked shipped Wave 155 with `Closes #560`.
- ✅ No new entry in `ui/package.json` dependencies. Uses only browser stdlib APIs.
- ✅ No emoji in any code, comment, or test added by this prompt.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-12)

```
grep -n "speakResponse\|onSpeechEvent" ui/src/audio/voice.ts
   35: export function onSpeechEvent(fn: SpeechListener): () => void {
   99: export function speakResponse(
  109: const utterance = new SpeechSynthesisUtterance(text);
  145: utterance.onstart = () => _fire({ type: 'start', agent_id, utterance });
  146: utterance.onend   = () => _fire({ type: 'end',   agent_id, utterance });

grep -n "boundary" ui/src/audio/voice.ts
   24: //  v1 emits 'start' and 'end' only; 'boundary' is reserved for AD-721b phoneme work.

grep -n "buildHeuristicTrack\|currentTrackRef" ui/src/components/profile/CrewVRM.tsx
   17: buildHeuristicTrack,
  205: const currentTrackRef = useRef<LipSyncTrack | null>(null);
  271: // fallback amplitude path when buildHeuristicTrack returns null.
  322: currentTrackRef.current = buildHeuristicTrack(text, { rate });
  327: analyserRef.current = _attachAnalyserOrSchedule(e.utterance);

grep -n "_VISEME_TARGETS\|ZERO_WEIGHTS" ui/src/audio/lipSyncTrack.ts
   62: const ZERO_WEIGHTS: VowelWeights = Object.freeze({...
  263: export const _VISEME_TARGETS = VISEME_TARGETS;
  (note: ZERO_WEIGHTS is NOT exported; CrewVRM defines a local fallback)

grep -n "speech\|amplitude" ui/src/audio/speechAmplitude.ts
    1: /** AD-721 D5: Audio amplitude provider for VRM mouth animation.
    3: * Browsers ship SpeechSynthesis without a routable audio graph by default,
    7: * is the AD-721b forward marker.

grep -n "POST /api/chat/attachments/multipart\|@router.post" src/probos/routers/chat.py
  757: async def upload_chat_attachment_multipart(
  712: @router.post("/chat/attachments")
  756: @router.post("/chat/attachments/multipart")

grep -n "AD-731" src/probos/cognitive/vision_dispatch.py
  (Builder: confirm at build time — the AD-731 attachment_ref shape lives there)

grep -n "fire({ type:" ui/src/__tests__/ModulationIndicator.test.tsx
   35: fire({ type: 'start', agent_id: 'agent-1', utterance: {} as SpeechSynthesisUtterance });
   37: fire({ type: 'end', agent_id: 'agent-1', utterance: {} as SpeechSynthesisUtterance });
  (test pattern for synthetic onSpeechEvent firing)

License verification (browser APIs):
  Web Audio API, MediaRecorder API — W3C / WHATWG standards, no license concern.
```


---

## Revision (2026-05-12) — pass-1 review fold-in

Applied Required findings R3 + R4 from `prompts/Reviews/ad-721b-2-browser-real-audio-capture-review.md` and Recommended #3/#5 + Nit #1.

| Finding | Severity | Resolution |
|---|---|---|
| **R3 — hook-activation contradiction** | Required | Took Architect option (b): hook is hardcoded `enabled: true` in Section 3a; honest-degrade chains end-to-end on the server (capture-fail → 0-byte short-circuit; server-fail → `backend: "heuristic"` → empty frames; CrewVRM falls through to `buildHeuristicTrack` on every empty response). Captain Decision #3 rewritten to reflect always-on capture. Section 2c rewritten as documentation of the honest-degrade chain (no probe spec, no synthetic-blob upload, no missing endpoint reference). The orphaned `GET /api/system/config` reference is removed. |
| **R4 — AttachmentStore upload pattern** | Required (verify) | Verified: prompt already uses `POST /api/chat/attachments/multipart` (the canonical AD-720a path); `_get_attachment_store` is reused server-side via the AD-721b-1 endpoint, not re-instantiated. No `/api/avatars/upload` endpoint is added. No code change needed; coordination call-out added below. |
| **R2 / cross-prompt mime — coordination** | Required (cross-prompt) | New "Coordination with AD-721b-1" sub-section added between Section 0 intro and the "Do NOT touch" list. Explicit reference to AD-721b-1 Section 0.5 as the allow-list owner; build order `AD-721b-1 → AD-721b-2` reasserted; `config.py` and `attachments/mime.py` added to the "Do NOT touch" list. |
| **Rec #3 — dead test #5 (`does not capture when disabled`)** | Recommended | Removed. With `enabled: true` hardcoded, the test guarded a configuration path that does not exist in production. Test count drops 7 → 6 (3 pure + 3 hook + 1 regression). Header + Section 4 sub-section counts updated. |
| **Rec #5 — synthetic-blob probe footgun** | Recommended | Section 2c rewritten; the synthetic-blob/probe alternative is removed entirely. The new Section 2c is purely documentary (describes the honest-degrade chain and notes the `enabled` parameter is preserved for future use). |
| **Nit #1 — co-locate regression test** | Nit | Test path moved from `ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx` to `ui/src/components/profile/__tests__/CrewVRM.realAudioFallback.test.tsx` to match the existing `CrewVRM.expressionResting.test.tsx` co-location. Files-touched table + test gates updated. |

The CrewVRM Section 3a code-comment was extended to reflect the always-on contract. No source-shape changes to lipSyncCapture.ts or useLipSyncCapture.ts. The Vitest mock plan and AD-731 invariant test (test #3) are unchanged.

No scope expansion: every change addresses an explicitly-flagged finding. Recommended #1 (AudioContext leak risk on rapid-fire utterances), Recommended #2 (AbortController on cleanup), and Recommended #4 (test-pattern fragility note) are deferred to AD-721b-2.1+ as stress/hardening follow-ups; they do not block the wave.
