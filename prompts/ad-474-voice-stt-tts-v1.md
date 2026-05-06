# AD-474 v1 — Voice (STT/TTS): Harden + Hands-Free

**Status:** Ready to build (Wave 86)
**Dependencies:** none (UI-only; the AD-474 substrate is **already shipping live** in the HXI — `ui/src/audio/voice.ts`, `ui/src/audio/speechInput.ts`, voice picker in `DecisionSurface.tsx`, mic button in `IntentSurface.tsx`, store `voiceEnabled` flag — but has zero tests)
**Estimated tests:** +30 vitest floor across three groups (AD-474a ≈ 20, AD-474b ≈ 6, AD-474c ≈ 4); ±0 pytest
**Closes:** GH #68

## Problem

`ui/src/audio/voice.ts` (90 LOC) and `ui/src/audio/speechInput.ts` (78 LOC) implement the browser-native TTS and STT slice of AD-474, are wired into `IntentSurface.tsx` (auto-speak responses; mic button) and `DecisionSurface.tsx` (voice picker, voice-enable toggle), and ship to every HXI user today. They have **zero vitest coverage** — `Test-Path ui/src/__tests__/voice.test.ts` → False, `Test-Path ui/src/__tests__/speechInput.test.ts` → False, `Select-String -Pattern 'voice|Voice|speech|Speech' -Path ui/src/__tests__/*.{ts,tsx}` → 0 hits.

Roadmap line 4207 lists five components for AD-474: (1) STT, (2) wake-word, (3) continuous talk mode, (4) full pipeline, (5) platform integration — plus a bundled "Voice Provider & Ship's Computer Voice" line. Of those, the **continuous talk mode** is the only one buildable in a UI-only wave with no new deps; the others all need new Python deps, new model-file binaries, or new desktop substrate (see WAVE-86-DISPATCH.md for the parked-AD forcing functions).

This prompt:

1. **Backfills** vitest tests against the shipped surface so it stops shipping untested (AD-474a).
2. **Extends** `startListening()` with a continuous-listen option for hands-free voice (AD-474b).
3. **Adds** an `onSpeechEnd` VAD callback to expose the browser-native end-of-utterance signal (AD-474c).

## Solution

Three surfaces, three sub-AD letters, one commit:

1. **Section 1 (AD-474a)** — `ui/src/__tests__/voice.test.ts` and `ui/src/__tests__/speechInput.test.ts`. Mock `window.speechSynthesis`, `window.SpeechSynthesisUtterance`, `window.SpeechRecognition` via `vi.stubGlobal()` — jsdom does not provide these. Lock the live behavior of every exported function plus the `voiceschanged` event handler.
2. **Section 2 (AD-474b)** — extend `startListening(onResult, onEnd?, onError?)` to `startListening(onResult, onEnd?, onError?, opts?: ListenOptions)` with `{ continuous?: boolean; interimResults?: boolean }`. Default `continuous=false`, `interimResults=false` — preserves current call-sites verbatim. When `continuous=true`, `recognition.onend` auto-restarts a fresh `recognition.start()` until a new `_stopRequested` guard flag is set by `stopListening()`. When `interimResults=true`, `recognition.interimResults=true` is forwarded; `onResult` only fires for final results (filtered via `event.results[i].isFinal`).
3. **Section 3 (AD-474c)** — add an optional fourth callback to `ListenOptions`: `onSpeechEnd?: () => void`. Forward it to `recognition.onspeechend` (the browser-native VAD event that fires when the user stops speaking, before `onend` fires for the session). Consumers can use this to flip the mic icon to a "processing…" state without polling.

Out of scope: wake-word detection (AD-474d), `SpeechRecognizer` ABC + Whisper / Deepgram backends (AD-474e), Ship's Computer custom voice via Piper / FishAudio / ElevenLabs (AD-474f), macOS menubar PTT (AD-474g), PWA mobile mic UX (AD-474h). See WAVE-86-DISPATCH.md for the parked-AD forcing functions.

---

### Section 1 — Vitest backfill (AD-474a)

#### 1A — `ui/src/__tests__/voice.test.ts`

Create a new file. jsdom does not provide `speechSynthesis` so each test stubs `window.speechSynthesis` with a fake implementation, asserts behavior, then `vi.unstubAllGlobals()` in `afterEach`.

The voice cache (`cachedVoice` module-private at `voice.ts:4`) is a module-level `let`. Tests that mutate it must call `setPreferredVoiceName(null)` in `beforeEach` to reset, and must call it before each `findPreferredVoice()` test that expects a fresh fetch from `getVoices()`. The `voiceschanged` event handler (`voice.ts:42`) clears `cachedVoice` itself — tests that fire that event verify it.

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  speakResponse,
  stopSpeaking,
  getAvailableVoices,
  setPreferredVoiceName,
  getCurrentVoiceName,
} from '../audio/voice';

interface FakeVoice { name: string; lang: string; default?: boolean; localService?: boolean; voiceURI?: string; }

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: FakeVoice | null = null;
  constructor(text: string) { this.text = text; }
}

describe('voice.ts (AD-474a)', () => {
  let speakSpy: ReturnType<typeof vi.fn>;
  let cancelSpy: ReturnType<typeof vi.fn>;
  let getVoicesSpy: ReturnType<typeof vi.fn>;
  let voiceList: FakeVoice[] = [];

  beforeEach(() => {
    voiceList = [];
    speakSpy = vi.fn();
    cancelSpy = vi.fn();
    getVoicesSpy = vi.fn(() => voiceList);
    vi.stubGlobal('speechSynthesis', {
      speak: speakSpy,
      cancel: cancelSpy,
      getVoices: getVoicesSpy,
      addEventListener: vi.fn(),
    });
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance as unknown as typeof SpeechSynthesisUtterance);
    localStorage.clear();
    setPreferredVoiceName(null);  // reset module cache
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('speakResponse no-ops when speechSynthesis is unavailable', () => {
    vi.unstubAllGlobals();  // remove speechSynthesis stub
    expect(() => speakResponse('hello')).not.toThrow();
  });

  it('speakResponse cancels prior utterance, sets rate/pitch/volume, and calls speak', () => {
    voiceList = [{ name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' }];
    speakResponse('hello world');
    expect(cancelSpy).toHaveBeenCalled();
    expect(speakSpy).toHaveBeenCalledTimes(1);
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.text).toBe('hello world');
    expect(utt.rate).toBeCloseTo(0.95);
    expect(utt.pitch).toBeCloseTo(0.9);
    expect(utt.volume).toBeCloseTo(0.8);
  });

  it('stopSpeaking calls speechSynthesis.cancel', () => {
    stopSpeaking();
    expect(cancelSpy).toHaveBeenCalled();
  });

  it('stopSpeaking is a no-op when speechSynthesis is unavailable', () => {
    vi.unstubAllGlobals();
    expect(() => stopSpeaking()).not.toThrow();
  });

  it('findPreferredVoice prefers the saved hxi_voice_name from localStorage', () => {
    voiceList = [
      { name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' },
      { name: 'Custom Pick', lang: 'en-GB' },
    ];
    localStorage.setItem('hxi_voice_name', 'Custom Pick');
    setPreferredVoiceName('Custom Pick');  // ensures cache reset; also writes through
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.name).toBe('Custom Pick');
  });

  it('findPreferredVoice falls back to Online (Natural) Edge neural voice', () => {
    voiceList = [
      { name: 'Microsoft David - English (United States)', lang: 'en-US' },
      { name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' },
      { name: 'Google US English', lang: 'en-US' },
    ];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.name).toContain('Online (Natural)');
  });

  it('findPreferredVoice falls back to Google US English when no Online voice present', () => {
    voiceList = [
      { name: 'Microsoft David - English (United States)', lang: 'en-US' },
      { name: 'Google US English', lang: 'en-US' },
    ];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.name).toBe('Google US English');
  });

  it('findPreferredVoice ultimate fallback is the first en-* voice', () => {
    voiceList = [
      { name: 'Microsoft Hazel - English (Great Britain)', lang: 'en-GB' },
    ];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice?.lang).toMatch(/^en/);
  });

  it('findPreferredVoice returns no voice when getVoices is empty (utt.voice unset)', () => {
    voiceList = [];
    speakResponse('test');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.voice).toBeNull();
  });

  it('getAvailableVoices filters to en-* voices only', () => {
    voiceList = [
      { name: 'EN Voice', lang: 'en-US' },
      { name: 'JP Voice', lang: 'ja-JP' },
      { name: 'EN UK Voice', lang: 'en-GB' },
    ];
    const result = getAvailableVoices();
    expect(result).toHaveLength(2);
    expect(result.every(v => v.lang.startsWith('en'))).toBe(true);
  });

  it('setPreferredVoiceName(name) writes to localStorage; null clears it', () => {
    setPreferredVoiceName('Custom Pick');
    expect(localStorage.getItem('hxi_voice_name')).toBe('Custom Pick');
    setPreferredVoiceName(null);
    expect(localStorage.getItem('hxi_voice_name')).toBeNull();
  });

  it('getCurrentVoiceName returns voice.name when a preferred voice resolves', () => {
    voiceList = [{ name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US' }];
    expect(getCurrentVoiceName()).toContain('Online (Natural)');
  });

  it('getCurrentVoiceName returns "Default" fallback when no voice resolves', () => {
    voiceList = [];
    expect(getCurrentVoiceName()).toBe('Default');
  });
});
```

12 tests. Floor: 11 (the strictly-redundant `setPreferredVoiceName` localStorage test could collapse with the saved-name test if needed).

#### 1B — `ui/src/__tests__/speechInput.test.ts`

Create a new file. jsdom does not provide `SpeechRecognition` so each test stubs the constructor.

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  isSpeechRecognitionSupported,
  startListening,
  stopListening,
  isListening,
} from '../audio/speechInput';

interface FakeSR {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

let lastInstance: FakeSR | null = null;
function makeFakeSRCtor() {
  return vi.fn(() => {
    const sr: FakeSR = {
      continuous: false,
      interimResults: false,
      lang: '',
      onresult: null,
      onerror: null,
      onend: null,
      start: vi.fn(),
      abort: vi.fn(),
      stop: vi.fn(),
    };
    lastInstance = sr;
    return sr;
  });
}

describe('speechInput.ts (AD-474a)', () => {
  beforeEach(() => {
    lastInstance = null;
    stopListening();  // reset module-private activeRecognition
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('isSpeechRecognitionSupported returns false when neither vendor present', () => {
    // jsdom default has neither
    expect(isSpeechRecognitionSupported()).toBe(false);
  });

  it('isSpeechRecognitionSupported returns true with standard SpeechRecognition', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    expect(isSpeechRecognitionSupported()).toBe(true);
  });

  it('isSpeechRecognitionSupported returns true with webkit prefix', () => {
    vi.stubGlobal('webkitSpeechRecognition', makeFakeSRCtor());
    expect(isSpeechRecognitionSupported()).toBe(true);
  });

  it('startListening invokes onError when unsupported and does not throw', () => {
    const onError = vi.fn();
    startListening(vi.fn(), undefined, onError);
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('not supported'));
  });

  it('startListening configures continuous=false, interimResults=false, lang=en-US (defaults)', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    expect(lastInstance).not.toBeNull();
    expect(lastInstance!.continuous).toBe(false);
    expect(lastInstance!.interimResults).toBe(false);
    expect(lastInstance!.lang).toBe('en-US');
    expect(lastInstance!.start).toHaveBeenCalled();
  });

  it('startListening aborts any previously active session before starting', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    const first = lastInstance!;
    startListening(vi.fn());
    expect(first.abort).toHaveBeenCalled();
    expect(lastInstance).not.toBe(first);
  });

  it('onresult forwards the latest final transcript to onResult', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onResult = vi.fn();
    startListening(onResult);
    // Browser SpeechRecognitionResultList is array-like with length + index access
    // and per-result isFinal. Test fake mirrors that shape.
    lastInstance!.onresult?.({ results: { length: 1, 0: { 0: { transcript: 'hello world' }, isFinal: true } } as never });
    expect(onResult).toHaveBeenCalledWith('hello world');
  });

  it('onerror swallows "aborted" but propagates other errors', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onError = vi.fn();
    startListening(vi.fn(), undefined, onError);
    lastInstance!.onerror?.({ error: 'aborted' });
    expect(onError).not.toHaveBeenCalled();
    lastInstance!.onerror?.({ error: 'no-speech' });
    expect(onError).toHaveBeenCalledWith('no-speech');
  });

  it('onend invokes onEnd callback and clears active recognition', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onEnd = vi.fn();
    startListening(vi.fn(), onEnd);
    expect(isListening()).toBe(true);
    lastInstance!.onend?.();
    expect(onEnd).toHaveBeenCalled();
    expect(isListening()).toBe(false);
  });

  it('stopListening calls abort and is safe when no active session', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    stopListening();
    expect(isListening()).toBe(false);
    // second call should not throw
    expect(() => stopListening()).not.toThrow();
  });
});
```

10 tests. Floor: 9.

**Section 1 floor: 22 tests** (12 voice + 10 speechInput).

---

### Section 2 — Continuous-listen mode (AD-474b)

Extend `ui/src/audio/speechInput.ts`. **Preserve the current 3-arg call signature** so `IntentSurface.tsx:1467` keeps compiling without edits — add an optional fourth parameter.

#### 2A — Add `ListenOptions` type and extend `startListening`

In `ui/src/audio/speechInput.ts`, find this exact text:

```
let activeRecognition: SpeechRecognitionInstance | null = null;

export function startListening(
  onResult: (text: string) => void,
  onEnd?: () => void,
  onError?: (error: string) => void,
): void {
  if (!isSpeechRecognitionSupported()) {
    onError?.('Speech recognition not supported in this browser');
    return;
  }

  // Stop any active session
  stopListening();

  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition!;
  const recognition = new Ctor();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    onResult(text);
  };

  recognition.onerror = (event) => {
    if (event.error !== 'aborted') {
      onError?.(event.error);
    }
  };

  recognition.onend = () => {
    activeRecognition = null;
    onEnd?.();
  };

  activeRecognition = recognition;
  recognition.start();
}
```

Replace with:

```
let activeRecognition: SpeechRecognitionInstance | null = null;
let stopRequested = false;
let activeContinuous = false;

/** Options for startListening. AD-474b adds continuous-listen + interim-results;
 *  AD-474c adds onSpeechEnd VAD callback. All fields optional; defaults preserve
 *  pre-AD-474 behavior verbatim (single-shot recognition, en-US, final results only). */
export interface ListenOptions {
  /** When true, recognition keeps listening across utterances and auto-restarts on session end
   *  until stopListening() is called. Defaults to false (single-shot — matches v0 behavior). */
  continuous?: boolean;
  /** When true, recognition reports interim (non-final) results in addition to finals.
   *  onResult still only fires for final results — interim filtering happens in the
   *  onresult handler. Set this if you wire a separate interim-display path. */
  interimResults?: boolean;
  /** Fires when the browser detects end-of-utterance (recognition.onspeechend), BEFORE
   *  recognition.onend fires for the session. Useful for flipping a mic icon to a
   *  "processing…" state without polling. AD-474c. */
  onSpeechEnd?: () => void;
}

export function startListening(
  onResult: (text: string) => void,
  onEnd?: () => void,
  onError?: (error: string) => void,
  opts?: ListenOptions,
): void {
  if (!isSpeechRecognitionSupported()) {
    onError?.('Speech recognition not supported in this browser');
    return;
  }

  // Stop any active session
  stopListening();
  stopRequested = false;

  const continuous = opts?.continuous === true;
  const interimResults = opts?.interimResults === true;
  activeContinuous = continuous;

  _spawnRecognition(onResult, onEnd, onError, continuous, interimResults, opts);
}

function _spawnRecognition(
  onResult: (text: string) => void,
  onEnd: (() => void) | undefined,
  onError: ((error: string) => void) | undefined,
  continuous: boolean,
  interimResults: boolean,
  opts: ListenOptions | undefined,
): void {
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition!;
  const recognition = new Ctor();
  recognition.continuous = continuous;
  recognition.interimResults = interimResults;
  recognition.lang = 'en-US';

  recognition.onresult = (event) => {
    // Pick the most recent final result. In single-shot mode this is always index 0.
    // In continuous mode results accumulate; we report the latest final transcript.
    // event.results[i].isFinal exists at runtime; types here keep the v0 shape.
    const results = event.results as unknown as ArrayLike<{ 0: { transcript: string }; isFinal?: boolean }>;
    let lastFinal: string | null = null;
    for (let i = 0; i < (results as { length: number }).length; i++) {
      const r = results[i];
      if (r.isFinal !== false) {
        lastFinal = r[0].transcript;
      }
    }
    if (lastFinal !== null) {
      onResult(lastFinal);
    }
  };

  recognition.onerror = (event) => {
    if (event.error !== 'aborted') {
      onError?.(event.error);
    }
  };

  // AD-474c — VAD end-of-utterance hook.
  if (opts?.onSpeechEnd) {
    (recognition as unknown as { onspeechend: (() => void) | null }).onspeechend = () => {
      opts.onSpeechEnd?.();
    };
  }

  recognition.onend = () => {
    const wasContinuous = activeContinuous;
    activeRecognition = null;
    if (wasContinuous && !stopRequested) {
      // Auto-restart for hands-free continuous mode (AD-474b).
      _spawnRecognition(onResult, onEnd, onError, continuous, interimResults, opts);
      return;
    }
    onEnd?.();
  };

  activeRecognition = recognition;
  recognition.start();
}

export function stopListening(): void {
  stopRequested = true;
  activeContinuous = false;
  if (activeRecognition) {
    try { activeRecognition.abort(); } catch { /* already stopped */ }
    activeRecognition = null;
  }
}

export function isListening(): boolean {
  return activeRecognition !== null;
}
```

Notes on the rewrite:

- The 4-arg signature is backward-compatible with the 3-arg call at `IntentSurface.tsx:1467`. No consumer edits required.
- `_spawnRecognition` is module-private (no `export`). It exists so the auto-restart path on `onend` can rebuild a fresh `SpeechRecognition` instance — Chrome refuses to call `.start()` twice on the same instance after `.onend` has fired.
- `stopRequested` guard prevents the auto-restart loop from racing with an explicit `stopListening()` call. `activeContinuous` is captured in `wasContinuous` before `activeRecognition = null` to guarantee the auto-restart decision uses the in-flight session's mode (defends against a `stopListening()` racing the `onend` handler).
- `event.results` is iterated with a `length` cast — the v0 type `{ [index: number]: { [index: number]: { transcript: string } } }` is structurally indexable but does not declare `length`. Browsers ship a `SpeechRecognitionResultList` which is array-like; the cast preserves the v0 type's wire shape without growing the type surface for v1.
- AD-474d wake-word integration will re-pass its own `onResult` / `onEnd` / `onError` callbacks into `_spawnRecognition` directly when the wake-word loop fires — no module-private callback caching is added in v1. (Earlier draft introduced speculative `activeOpts` / `activeOnResult` / etc fields; removed in review pass 2 per `.github/copilot-instructions.md` discipline #1 — "Don't add features beyond what was asked.")

#### 2B — Tests for AD-474b

Append to `ui/src/__tests__/speechInput.test.ts` (new `describe` block):

```ts
describe('speechInput.ts continuous-listen (AD-474b)', () => {
  beforeEach(() => {
    lastInstance = null;
    stopListening();
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('forwards continuous=true to the SpeechRecognition instance', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { continuous: true });
    expect(lastInstance!.continuous).toBe(true);
  });

  it('forwards interimResults=true to the SpeechRecognition instance', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { interimResults: true });
    expect(lastInstance!.interimResults).toBe(true);
  });

  it('continuous mode auto-restarts a fresh recognition on onend', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { continuous: true });
    const first = lastInstance!;
    first.onend?.();
    expect(lastInstance).not.toBe(first);  // a new instance was spawned
    expect(lastInstance!.continuous).toBe(true);
    expect(lastInstance!.start).toHaveBeenCalled();
  });

  it('stopListening prevents continuous-mode auto-restart', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { continuous: true });
    const first = lastInstance!;
    stopListening();
    first.onend?.();
    expect(lastInstance).toBeNull();  // no new instance spawned after stop
  });

  it('continuous mode does not invoke onEnd during auto-restart cycles', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onEnd = vi.fn();
    startListening(vi.fn(), onEnd, undefined, { continuous: true });
    const first = lastInstance!;
    first.onend?.();
    expect(onEnd).not.toHaveBeenCalled();  // auto-restarted, not ended
  });

  it('with interimResults=true, onResult fires only for the latest final result', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onResult = vi.fn();
    startListening(onResult, undefined, undefined, { interimResults: true, continuous: true });
    lastInstance!.onresult?.({
      results: {
        length: 2,
        0: { 0: { transcript: 'partial' }, isFinal: false },
        1: { 0: { transcript: 'final text' }, isFinal: true },
      } as never,
    });
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('final text');
  });

  it('single-shot mode (default) does not auto-restart', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    const first = lastInstance!;
    first.onend?.();
    expect(lastInstance).toBeNull();  // single-shot ends cleanly
  });
});
```

7 tests. Floor: 6.

---

### Section 3 — VAD `onSpeechEnd` callback (AD-474c)

Already wired into `_spawnRecognition` in Section 2 (the `if (opts?.onSpeechEnd)` block). Tests only.

#### 3A — Tests for AD-474c

Append to `ui/src/__tests__/speechInput.test.ts`:

```ts
describe('speechInput.ts VAD (AD-474c)', () => {
  beforeEach(() => {
    lastInstance = null;
    stopListening();
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('forwards opts.onSpeechEnd to recognition.onspeechend', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onSpeechEnd = vi.fn();
    startListening(vi.fn(), undefined, undefined, { onSpeechEnd });
    const sr = lastInstance as unknown as { onspeechend: (() => void) | null };
    expect(sr.onspeechend).toBeTypeOf('function');
    sr.onspeechend?.();
    expect(onSpeechEnd).toHaveBeenCalledTimes(1);
  });

  it('does not set onspeechend when opts.onSpeechEnd is omitted', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    const sr = lastInstance as unknown as { onspeechend: (() => void) | null };
    expect(sr.onspeechend ?? null).toBeNull();
  });

  it('onSpeechEnd fires before onEnd in single-shot mode', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const order: string[] = [];
    const onSpeechEnd = vi.fn(() => { order.push('speechEnd'); });
    const onEnd = vi.fn(() => { order.push('end'); });
    startListening(vi.fn(), onEnd, undefined, { onSpeechEnd });
    const sr = lastInstance as unknown as { onspeechend: (() => void) | null };
    sr.onspeechend?.();
    lastInstance!.onend?.();
    expect(order).toEqual(['speechEnd', 'end']);
  });

  it('onSpeechEnd fires per utterance in continuous mode (each restart wires a fresh handler)', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onSpeechEnd = vi.fn();
    startListening(vi.fn(), undefined, undefined, { continuous: true, onSpeechEnd });
    const first = lastInstance as unknown as FakeSR & { onspeechend: (() => void) | null };
    first.onspeechend?.();
    first.onend?.();  // triggers auto-restart
    const second = lastInstance as unknown as FakeSR & { onspeechend: (() => void) | null };
    expect(second).not.toBe(first);
    second.onspeechend?.();
    expect(onSpeechEnd).toHaveBeenCalledTimes(2);
  });
});
```

4 tests. Floor: 4.

---

## Test plan summary

| Section | File | Tests |
|---|---|---|
| AD-474a | `ui/src/__tests__/voice.test.ts` | 12 |
| AD-474a | `ui/src/__tests__/speechInput.test.ts` (first describe block) | 10 |
| AD-474b | `ui/src/__tests__/speechInput.test.ts` (continuous-listen describe) | 7 |
| AD-474c | `ui/src/__tests__/speechInput.test.ts` (VAD describe) | 4 |
| **Total** | **2 new files** | **33** |

Floor for closure: **+28 vitest** (5-test buffer for jsdom timing edge cases on the auto-restart spawn path or for collapsing 1A's strictly-redundant `setPreferredVoiceName` localStorage assertion into the saved-name test).

## What this prompt does NOT change

- No edits to `voice.ts` (Section 1 is tests only; the shipped surface is correct).
- No edits to `IntentSurface.tsx`, `DecisionSurface.tsx`, `useStore.ts`, or any other consumer of `voice.ts` / `speechInput.ts` — the new `ListenOptions` parameter is optional and call-site-compatible.
- No edits to `App.tsx`, `CognitiveCanvas.tsx`, `animations.tsx`, `GlassLayer.tsx`, or any HXI canvas surface.
- No new EventType, agent, pool, Intent, router edit, consensus change, trust scorer touch, episodic store touch.
- No Python source touched. No `pyproject.toml` edit. No `ui/package.json` dep edit.
- No new AD numbers minted (sub-AD letters a-h are organizational only).
- No commercial language (verified via the WAVE-86-DISPATCH.md leak audit).

## Tracking

Builder updates after build:

- `PROGRESS.md` — add Wave 86 completion line in the era progress file (`progress-era-4-evolution.md`); pytest count unchanged at 11705; vitest count delta `+28..+30`.
- `docs/development/roadmap.md:4207` — annotate AD-474 with `*(v1 shipped 2026-05-06 — see Wave 86; 474d/e/f/g/h parked with forcing functions in WAVE-86-DISPATCH.md)*`.
- No `DECISIONS.md` entry required (the substrate was already in place; Wave 86 hardens and extends).
- GH #68 close with the closure note from WAVE-86-DISPATCH.md.

## Acceptance criteria

1. `cd ui && npx vitest run` shows ≥ **334** tests (306 baseline + 28 floor) with the 1 pre-existing `WardRoomDmSync` failure unchanged.
2. `pytest tests/ -q -n 4 --dist=loadfile` shows **11705** pytest unchanged. (No Python source touched — if this changes, the build is wrong.)
3. `cd ui && npx tsc -b` passes — the 4-arg `startListening` signature must compile against `IntentSurface.tsx:1467`'s 3-arg call (it does — fourth param is optional).
4. `git diff --stat` shows changes only in `ui/src/audio/speechInput.ts`, `ui/src/__tests__/voice.test.ts` (new), `ui/src/__tests__/speechInput.test.ts` (new). Plus `PROGRESS.md` / `progress-era-4-evolution.md` and `docs/development/roadmap.md` annotations per Tracking.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`. In particular: SOLID-O (extension via optional new parameter, not edit to existing signature); SOLID-I (`ListenOptions` is a narrow interface — three optional fields); fail-fast (tier-2 log-and-degrade preserved on `recognition.abort()` `try/catch`); no fire-and-forget tasks; no defensive `getattr`; no untyped public API.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  6e46444

# Substrate (verified live at HEAD):
ui/src/audio/voice.ts:48     export function speakResponse(text: string): void {
ui/src/audio/voice.ts:65     export function stopSpeaking(): void {
ui/src/audio/voice.ts:72     export function getAvailableVoices(): SpeechSynthesisVoice[] {
ui/src/audio/voice.ts:76     export function setPreferredVoiceName(name: string | null): void {
ui/src/audio/voice.ts:85     export function getCurrentVoiceName(): string {
ui/src/audio/voice.ts:6      function findPreferredVoice(): SpeechSynthesisVoice | null {
ui/src/audio/voice.ts:42     speechSynthesis.addEventListener('voiceschanged', () => {

ui/src/audio/speechInput.ts:23    export function isSpeechRecognitionSupported(): boolean {
ui/src/audio/speechInput.ts:30    export function startListening(  # 3-arg signature at HEAD
ui/src/audio/speechInput.ts:69    export function stopListening(): void {
ui/src/audio/speechInput.ts:76    export function isListening(): boolean {

# Consumer call-site shape (verified):
ui/src/components/IntentSurface.tsx:1467    isSpeechRecognitionSupported() && (<button
ui/src/components/IntentSurface.tsx:1473    startListening(
ui/src/components/IntentSurface.tsx:1474      (text) => { setInput(text); setListening(false); …
ui/src/components/IntentSurface.tsx:1483      () => setListening(false),       # onEnd
ui/src/components/IntentSurface.tsx:1484      () => setListening(false),       # onError
# 3-arg call — Section 2's 4th-arg-optional extension is back-compatible.

ui/src/components/IntentSurface.tsx:8       import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput';
ui/src/components/IntentSurface.tsx:195     if (voiceEnabled && response && !response.startsWith('(')) {
ui/src/components/IntentSurface.tsx:209     speakResponse(cleanText);

# Voice picker (verified — no Section 1 edit):
ui/src/components/DecisionSurface.tsx:165   onClick={() => setVoiceEnabled(!voiceEnabled)}
ui/src/components/DecisionSurface.tsx:170   <svg width="14" height="14" … strokeLinecap="round"   # HXI principle #3 stroke icon
ui/src/components/DecisionSurface.tsx:206   if (voiceEnabled) { … speakResponse('Voice selected'); }

# Store integration (verified — no Section 1 edit):
ui/src/store/useStore.ts:300     voiceEnabled: boolean;
ui/src/store/useStore.ts:365     setVoiceEnabled: (v: boolean) => void;
ui/src/store/useStore.ts:539     voiceEnabled: false,
ui/src/store/useStore.ts:1010    setVoiceEnabled: (v) => { set({ voiceEnabled: v }); localStorage.setItem('hxi_voice_enabled', v ? '1' : '0'); },

# Greenfield (verified absent):
ui/src/__tests__/voice.test.ts                # absent
ui/src/__tests__/speechInput.test.ts          # absent
# zero existing voice/speech vitest coverage at HEAD

# Test runner config (verified — no edit needed):
ui/vitest.config.ts:7    environment: 'jsdom', globals: true, setupFiles: './src/test/setup.ts'
ui/src/test/setup.ts:1   import '@testing-library/jest-dom';

# Vitest baseline (verified):
cd ui && npx vitest run
  Test Files  1 failed | 17 passed (18)
  Tests       1 failed | 305 passed (306)
  # WardRoomDmSync.test.tsx pre-existing failure — NOT in scope.

# Pytest baseline (verified):
# Wave 85 archive note (commit 6e46444): "pytest 11705 post-build."
```
