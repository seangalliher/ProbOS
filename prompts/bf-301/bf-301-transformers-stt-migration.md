# BF-301 — Migrate Browser STT from whisper.cpp WASM to transformers.js Whisper

**Status:** Ready for Builder
**Closes:** #775
**Depends on:** AD-820..AD-826 (whisper-first STT chain), BF-290/292/293/294/294b/300 (mic UX gates)
**Estimated tests:** 14+ new (9 frontend + 5 backend) + AD-826 test migration

## One-line summary

Swap the abandoned whisper.cpp WASM artifact pipeline (AD-826) for browser-side `@huggingface/transformers` ASR running in a Web Worker, so PTT works identically in Chrome, Edge, Firefox, Safari, and the Electron desktop app without any operator setup step.

## Problem

AD-826 shipped the correct architecture (local-first STT, browser-side inference, browser SR as fallback) but bound it to whisper.cpp's WASM example bundle, which upstream has effectively abandoned for browser deployment:

- `https://huggingface.co/ggerganov/whisper.cpp/resolve/v1.5.4/...` returns "Invalid rev id" — tag deleted/retagged on HF.
- `whisper.ggerganov.com` CDN is a dead GitHub Pages site (404).
- `npm i whisper.cpp` ships only JS glue — the `.wasm` runtime binary is not on npm and has no stable mirror.
- Net effect verified 2026-05-23: every operator's `/api/voice/health` reports `backend_available=false`, AD-826 silently falls through to the flaky `webkitSpeechRecognition` path AD-826 was designed to eliminate.

The industry has converged on `transformers.js` + ONNX Runtime Web since whisper.cpp WASM peaked. `@huggingface/transformers` v3 (Apache 2.0, ~3M weekly npm downloads) ships the `Xenova/whisper-tiny.en` ONNX model directly from the HF CDN with browser Cache API persistence — no operator setup, no abandoned artifacts, identical behavior across all evergreen browsers and Chromium-Electron.

## Solution overview

Replace the AD-826 browser-side engine with a Web-Worker-isolated `pipeline('automatic-speech-recognition', 'Xenova/whisper-tiny.en')`. Keep the AD-826 architecture intact:

- Public surface of the new `transformersStt.ts` mirrors `whisperStt.ts` (arm / disarm / onTranscript / onTranscribing) so the migration is a typed import swap at three call sites.
- Add a fourth subscription, `onTransformersProgress(handler)`, so the UI can render a first-load download bar (transformers.js v3 emits structured progress callbacks during model fetch).
- `/api/voice/health` keeps its 4-field shape (`primary_stt`, `engine`, `backend_available`, `healthy`) so existing UI consumers (BF-294 / AD-826) do not regress. The `engine` value flips from `"whisper"` → `"transformers"` when the local-first path is selected.
- Extend `cognitive.primary_stt` Literal to `"transformers" | "whisper" | "browser"`. `"whisper"` becomes a deprecated alias that resolves to `engine: "transformers"` so saved operator configs do not break.
- Leave `whisperStt.ts`, `whisperLoader.ts`, and `scripts/whisper-tiny-en-fetch.ps1` on disk with deprecation banners. A separate hygiene PR will delete them once one ProbOS release cycle has shipped on transformers.js.

## Research findings (verified against live sources 2026-05-23)

| Item | Decision | Evidence |
|---|---|---|
| Package | `@huggingface/transformers` (v3.x, current stable) | v3 is the rename of `@xenova/transformers`. Apache 2.0. The Xenova/* HF hub namespace is preserved across v2/v3. |
| ONNX Runtime | Bundled inside `@huggingface/transformers` v3 | Do **NOT** add `onnxruntime-web` as a separate dependency in v3. The existing `optionalDependencies.onnxruntime-web` in `ui/package.json` was a transitive footprint of the legacy whisper.cpp glue and can be removed. |
| Model id | `Xenova/whisper-tiny.en` | ~40 MB compressed ONNX. English-only. Lowest latency tier that still produces usable PTT transcripts. Operator can swap to `Xenova/whisper-base.en` via `cognitive.transformers_model`. |
| API shape | `await pipeline('automatic-speech-recognition', model_id, { progress_callback })` returns a transcriber. `transcriber(audioFloat32Array, { sampling_rate: 16000, chunk_length_s: 30, stride_length_s: 5, return_timestamps: false, chunk_callback })` returns `{ text: string }`. | xenova/whisper-web `src/worker.js`; transformers.js v3 docs (`/docs/transformers.js/api/pipelines#asr`). |
| Worker pattern | Vite-native: `new Worker(new URL('./transformersWorker.ts', import.meta.url), { type: 'module' })` | Existing Vite 6 + `worker.format: 'es'` (default in Vite 6) — no plugin changes needed. |
| Progress event shape | `{ status: 'progress' \| 'download' \| 'done' \| 'ready' \| 'initiate', name: string, file?: string, progress?: number, loaded?: number, total?: number }` | xenova/whisper-web `src/App.jsx` progress reducer + transformers.js source. |
| HomeAssistant pattern | Cloud → local → browser-SR cascade matches what AD-826 already does; we keep the cascade and only swap the local engine. | Not directly imported. Confirmed the layered design is industry-standard. |

**Architectural surprise (vs. issue body):** the issue body lists three changes to `ProfileChatTab.tsx`, but `armWhisperStt` is also imported by **`ui/src/audio/conversationController.ts`** (AD-747 always-on conversation mode) **and `ui/src/components/IntentSurface.tsx`** (AD-705a global PTT hook). All three call sites must be migrated in this commit or the build will fail with unresolved imports. This is reflected in Section 4 below.

**Architectural surprise (vs. issue body):** the issue body proposes a backend `is_internet_reachable()` HEAD probe in `/api/voice/health`. This is the wrong layer — the runtime cannot know whether the operator's *browser* can reach the HF CDN (the runtime might be on a different network than the browser; air-gapped operators run the runtime locally and the browser fetches the model from a corporate proxy). The probe semantics in this prompt are simpler and correct: `healthy` reflects whether `offline_stt_enabled=true` AND the new `transformers_model` field is set. The browser is responsible for its own model fetch and reports failures through the new `onTransformersProgress` channel.

## Section 0: Dependencies

### 0.1 `ui/package.json`

Add `@huggingface/transformers` to `dependencies`. Remove `onnxruntime-web` from `optionalDependencies` (bundled by v3).

```diff
   "dependencies": {
+    "@huggingface/transformers": "^3.0.0",
     "@pixiv/three-vrm": "^3.5.2",
     "@react-three/drei": "^10.0.0",
     ...
-  },
-  "optionalDependencies": {
-    "onnxruntime-web": "^1.18.0"
   },
```

Builder command (must run before any other section's tests):

```powershell
cd D:\ProbOS\ui
npm install @huggingface/transformers@^3.0.0
npm uninstall onnxruntime-web
```

### 0.2 `ui/vite.config.ts` — chunk `transformers` separately

Add a `stt-vendor` chunk so the ~1 MB transformers.js + onnxruntime runtime does not balloon the main bundle. Existing `avatar-vendor` pattern is the template.

Insert into `manualChunks(id)` BEFORE the avatar-vendor branch:

```ts
        manualChunks(id: string) {
          // BF-301: transformers.js + bundled onnxruntime-web for browser STT.
          // Loaded only when the PTT handler arms (lazy `import('../audio/transformersStt')`).
          if (
            id.includes('node_modules/@huggingface/transformers') ||
            id.includes('node_modules/onnxruntime-web') ||
            id.includes('/ui/src/audio/transformersStt') ||
            id.includes('/ui/src/audio/transformersWorker')
          ) {
            return 'stt-vendor';
          }
          // Vendor: three.js + @pixiv/three-vrm. ...
```

## Section 1: Frontend — `ui/src/audio/transformersStt.ts` (new file)

Mirror the public surface of `whisperStt.ts` so call sites migrate via import-name swap. Internally own a single Web Worker.

Public API (matches issue body):

```ts
export function armTransformersStt(): () => void;
export function disarmTransformersStt(): void;
export function onTransformersTranscript(listener: (text: string) => void): () => void;
export function onTransformersTranscribing(listener: (active: boolean) => void): () => void;
// New in BF-301 — first-load model download progress.
export function onTransformersProgress(
  listener: (event: TransformersProgressEvent) => void,
): () => void;

export interface TransformersProgressEvent {
  status: 'initiate' | 'download' | 'progress' | 'done' | 'ready' | 'error';
  name?: string;     // model id
  file?: string;     // shard name
  loaded?: number;   // bytes
  total?: number;    // bytes
  progress?: number; // 0..1
}

// Test seams (mirror whisperStt.ts):
export function _setTransformersWorkerOverride(
  factory: (() => Worker) | null,
): void;
export function _resetTransformersStt(): void;
export function _isArmed(): boolean;
```

Behavior contract:

1. **`armTransformersStt()`** — idempotent. On first call: instantiate the Web Worker (default factory: `new Worker(new URL('./transformersWorker.ts', import.meta.url), { type: 'module' })`); post `{ type: 'init', model: <from voice-health response or fallback to 'Xenova/whisper-tiny.en'> }`; subscribe to the AD-733c-7-5 VAD PCM tap via `subscribePcm` from `./voiceActivity`; collect Float32 frames between `onSpeechStart`/`onSpeechEnd`; on `onSpeechEnd` post `{ type: 'transcribe', samples: Float32Array, sampleRate: 16000 }` to the worker (transfer the underlying ArrayBuffer to avoid a copy).
2. **Worker `message` handler** — three event shapes:
   - `{ type: 'progress', event: TransformersProgressEvent }` → dispatch to `_progressListeners`.
   - `{ type: 'transcript', text: string, isPartial: boolean }` → dispatch to `_transcriptListeners` (partials AND final; subscribers may dedupe).
   - `{ type: 'transcribing', active: boolean }` → dispatch to `_transcribingListeners`.
3. **`disarmTransformersStt()`** — idempotent. Unsubscribe the PCM tap; post `{ type: 'shutdown' }` to the worker; `worker.terminate()` after a 250 ms grace; null out module state. Subsequent `armTransformersStt()` calls reinstantiate cleanly.
4. **MAX_UTTERANCE_SAMPLES = 16000 * 30** (30 s ceiling, matches `whisperStt.ts`).
5. **Privacy invariant** (AD-733c-7 extended): no `fetch()` calls from this module with any audio payload. Only the transcript text is dispatched to subscribers. The model fetch is initiated by transformers.js itself inside the worker; that traffic is model weight bytes to/from HF CDN, never operator audio.
6. **Honest-degrade**: if the worker posts `{ type: 'progress', event: { status: 'error', ... } }` during init (model fetch fails), the module surfaces an error progress event AND silently stops emitting transcripts. `_isArmed()` returns true (arm succeeded; only model load failed) so the UI shows the engine name in the mic tooltip per AD-826 behavior. Callers fall through to browser SR via the existing AD-826 fallback counter pattern.

Test seam discipline (mirrors `whisperStt.ts`): a `_setTransformersWorkerOverride(factory)` setter lets vitest stub the Worker boundary with a `MessageChannel`-backed fake — production code MUST NOT import `Worker` from anywhere mockable. The override is read inside `armTransformersStt()`, falling back to the real `new Worker(...)` factory.

## Section 2: Frontend — `ui/src/audio/transformersWorker.ts` (new file)

Web Worker entry. Self-contained; only imports from `@huggingface/transformers`.

Lifecycle:

```ts
import { pipeline, type AutomaticSpeechRecognitionPipeline } from '@huggingface/transformers';

let _asr: AutomaticSpeechRecognitionPipeline | null = null;
let _model = 'Xenova/whisper-tiny.en';

self.addEventListener('message', async (e: MessageEvent) => {
  const msg = e.data;
  if (msg.type === 'init') {
    _model = msg.model ?? _model;
    try {
      _asr = await pipeline(
        'automatic-speech-recognition',
        _model,
        {
          progress_callback: (event: unknown) => {
            // Forward HF progress shape verbatim; the main thread normalizes.
            (self as unknown as Worker).postMessage({ type: 'progress', event });
          },
          // dtype + device left as defaults — transformers v3 picks WASM+q8
          // automatically on browsers without WebGPU and WebGPU+f16 when
          // available. Operator can pin via a future cognitive.transformers_*
          // config field (forward marker — out of scope for BF-301).
        },
      );
      (self as unknown as Worker).postMessage({
        type: 'progress',
        event: { status: 'ready', name: _model },
      });
    } catch (err) {
      (self as unknown as Worker).postMessage({
        type: 'progress',
        event: { status: 'error', name: _model, file: String(err) },
      });
    }
    return;
  }
  if (msg.type === 'transcribe') {
    if (!_asr) return;
    (self as unknown as Worker).postMessage({ type: 'transcribing', active: true });
    try {
      const samples = msg.samples as Float32Array;
      const out = await _asr(samples, {
        sampling_rate: msg.sampleRate ?? 16000,
        chunk_length_s: 30,
        stride_length_s: 5,
        return_timestamps: false,
        // chunk_callback fires per chunk during transcription, enabling
        // progressive partial transcripts (xenova/whisper-web pattern).
        chunk_callback: (chunk: { text?: string }) => {
          if (chunk && typeof chunk.text === 'string' && chunk.text.length > 0) {
            (self as unknown as Worker).postMessage({
              type: 'transcript',
              text: chunk.text,
              isPartial: true,
            });
          }
        },
      });
      const text = (out as { text?: string })?.text ?? '';
      if (text.length > 0) {
        (self as unknown as Worker).postMessage({
          type: 'transcript',
          text,
          isPartial: false,
        });
      }
    } catch (err) {
      // Tier-2 log; no transcript emitted on failure.
      console.warn('[BF-301] transcribe error', err);
    } finally {
      (self as unknown as Worker).postMessage({ type: 'transcribing', active: false });
    }
    return;
  }
  if (msg.type === 'shutdown') {
    _asr = null;
    self.close();
  }
});
```

Notes:

- This file must have **no** non-`@huggingface/transformers` imports. Vite chunks the worker into its own bundle entry and a transitive import of `../store/...` or anything else would balloon the worker bundle.
- `console.warn` is acceptable in workers — there is no shared logger.
- The `(self as unknown as Worker)` cast appeases the TypeScript lib mismatch between `WorkerGlobalScope` and `Worker` `postMessage` shapes. Standard pattern; xenova/whisper-web uses the same trick.

## Section 3: Frontend — `ui/src/audio/whisperStt.ts` + `whisperLoader.ts` deprecation banners

**DO NOT delete these files in this commit** (per the user's prompt — easier review + revert). Add a deprecation comment block at the top of each file referencing BF-301:

`ui/src/audio/whisperStt.ts` — replace the existing top-of-file docblock's first paragraph with:

```ts
/**
 * AD-705a — Offline STT consumer driven by the AD-721b-3 whisper.cpp
 * loader and the AD-733c-7-5 VAD PCM tap.
 *
 * **DEPRECATED in BF-301 (#775).** The whisper.cpp WASM artifact pipeline
 * this module depends on is abandoned upstream (HF tag deleted, CDN dead,
 * npm package incomplete). All active call sites have been migrated to
 * ``./transformersStt.ts``. This file is retained for one ProbOS release
 * cycle to ease revert; a follow-up hygiene PR will delete it.
 *
 * (... existing AD-705a docstring follows ...)
```

`ui/src/audio/whisperLoader.ts` — same treatment with reference to BF-301.

No code changes to these files. Their existing tests continue to pass; they are simply unreferenced by production code paths after Section 4.

## Section 4: Frontend — migrate three call sites

### 4.1 `ui/src/components/profile/ProfileChatTab.tsx`

Replace the `whisperStt` import block (currently around lines 20-24):

```ts
// SEARCH
import {
  armWhisperStt,
  disarmWhisperStt,
  onTranscript as onWhisperTranscript,
  onTranscribing as onWhisperTranscribing,
} from '../../audio/whisperStt';
// REPLACE
import {
  armTransformersStt as armWhisperStt,
  disarmTransformersStt as disarmWhisperStt,
  onTransformersTranscript as onWhisperTranscript,
  onTransformersTranscribing as onWhisperTranscribing,
  onTransformersProgress,
  type TransformersProgressEvent,
} from '../../audio/transformersStt';
```

(The local aliases are retained so the rest of the file — including the BF-290/292/293/294/294b/300 gating logic that references `armWhisperStt`/`disarmWhisperStt` literally — does not need to change.)

Update the `VoiceHealth` interface (currently around line 6) and the tooltip rendering (currently around line 1121):

```ts
// SEARCH
interface VoiceHealth {
  primary_stt: 'whisper' | 'browser';
  engine: 'whisper' | 'browser';
  backend_available: boolean;
  healthy: boolean;
}
// REPLACE
interface VoiceHealth {
  primary_stt: 'transformers' | 'whisper' | 'browser';
  engine: 'transformers' | 'whisper' | 'browser';
  backend_available: boolean;
  healthy: boolean;
  model?: string; // BF-301: transformers model id when engine === 'transformers'
}
```

```tsx
// SEARCH
                voiceHealth?.engine === 'whisper' ? 'Voice input (whisper)' :
                voiceHealth?.engine === 'browser' ? 'Voice input (browser)' :
// REPLACE
                voiceHealth?.engine === 'transformers' ? `Voice input (transformers · ${voiceHealth?.model ?? 'whisper-tiny.en'})` :
                voiceHealth?.engine === 'whisper' ? 'Voice input (whisper)' :
                voiceHealth?.engine === 'browser' ? 'Voice input (browser)' :
```

Add the first-load progress UI. Inside the `ProfileChatTab` function, near the other `useState` declarations (after the existing `voiceHealth` state):

```tsx
  // BF-301: first-load model download progress. Cleared once status === 'ready'.
  const [transformersProgress, setTransformersProgress] = useState<TransformersProgressEvent | null>(null);
  useEffect(() => {
    const unsub = onTransformersProgress((event) => {
      // Subtle UX: keep showing progress until model is ready; clear on done/ready.
      if (event.status === 'ready' || event.status === 'done') {
        setTransformersProgress(null);
      } else {
        setTransformersProgress(event);
      }
    });
    return () => { try { unsub(); } catch { /* Tier-2 */ } };
  }, []);
```

Render the progress bar inline near the mic affordance (HXI Design Principle #4 — motion communicates state, subtle). Place it in the mic button row, conditional on `transformersProgress && transformersProgress.progress !== undefined`:

```tsx
              {transformersProgress && transformersProgress.progress !== undefined && transformersProgress.progress < 1 && (
                <div
                  data-testid="bf301-progress"
                  style={{
                    position: 'absolute',
                    bottom: -4,
                    left: 0,
                    right: 0,
                    height: 2,
                    background: 'rgba(240, 176, 96, 0.15)',
                    overflow: 'hidden',
                  }}
                  title={`Loading STT model: ${Math.round((transformersProgress.progress ?? 0) * 100)}%`}
                >
                  <div
                    style={{
                      width: `${Math.round((transformersProgress.progress ?? 0) * 100)}%`,
                      height: '100%',
                      background: '#f0b060',
                      transition: 'width 200ms linear',
                    }}
                  />
                </div>
              )}
```

(Exact placement: inside the mic button container — Builder picks the closest matching JSX scope. Use `data-testid="bf301-progress"` so the BF-301 test file can assert on it.)

**DO NOT change** the existing BF-290/292/293/294/294b/300 gating logic (`listening` / `processing` state, mic-during-TTS gate, empty-counter fallback). The aliased imports preserve every existing call.

### 4.2 `ui/src/components/IntentSurface.tsx`

Replace the import block around lines 11-14:

```ts
// SEARCH
import {
  armWhisperStt,
  onTranscript,
  onTranscribing,
} from '../audio/whisperStt';
// REPLACE
import {
  armTransformersStt as armWhisperStt,
  onTransformersTranscript as onTranscript,
  onTransformersTranscribing as onTranscribing,
} from '../audio/transformersStt';
```

No further changes in this file. Local aliases preserve the AD-705a useEffect block exactly.

### 4.3 `ui/src/audio/conversationController.ts`

Replace the import block around lines 50-53:

```ts
// SEARCH
import {
  armWhisperStt,
  disarmWhisperStt,
  onTranscript as _onWhisperTranscript,
} from './whisperStt';
// REPLACE
import {
  armTransformersStt as armWhisperStt,
  disarmTransformersStt as disarmWhisperStt,
  onTransformersTranscript as _onWhisperTranscript,
} from './transformersStt';
```

No further changes. AD-747 state machine references are unaffected by the engine swap.

## Section 5: Backend — `src/probos/config.py`

Extend `primary_stt` Literal and add `transformers_model`. Keep existing `whisper_model_path` and `offline_stt_enabled` semantics.

```python
# SEARCH
    primary_stt: Literal["whisper", "browser"] = Field(
        default="whisper",
        description=(
            "AD-826: which STT engine the UI PTT handler arms first. "
            "whisper = local whisper.cpp WASM (cross-browser, privacy-"
            "aligned). browser = Web Speech API (Chrome-only reliable; "
            "flaky on Edge/Firefox/Safari). When whisper is selected "
            "AND artifacts/config are unavailable, the UI honest-"
            "degrades to the browser engine. Hot-reload."
        ),
    )
# REPLACE
    primary_stt: Literal["transformers", "whisper", "browser"] = Field(
        default="transformers",
        description=(
            "BF-301 (was AD-826): which STT engine the UI PTT handler "
            "arms first. transformers = local @huggingface/transformers "
            "Whisper running in a Web Worker (cross-browser, no operator "
            "setup, default since BF-301). whisper = DEPRECATED alias "
            "for transformers — retained for back-compat with saved "
            "operator configs; resolves to engine='transformers' in "
            "the health endpoint. browser = Web Speech API (Chrome-only "
            "reliable; flaky on Edge/Firefox/Safari). When transformers "
            "is selected AND offline_stt_enabled is False, the UI "
            "honest-degrades to the browser engine. Hot-reload."
        ),
    )
```

Add the `transformers_model` field immediately after `primary_stt` / `fallback_stt_enabled` (current ~line 297):

```python
    # BF-301 (#775): transformers.js Whisper model id. The browser-side
    # @huggingface/transformers pipeline fetches the ONNX shards from HF
    # CDN on first use and caches them in the browser's Cache API.
    # Defaults to ``Xenova/whisper-tiny.en`` (~40 MB, English-only,
    # lowest-latency tier with usable PTT accuracy). Operators on
    # high-bandwidth machines can swap to ``Xenova/whisper-base.en`` for
    # better accuracy at ~150 MB. The runtime does NOT validate the model
    # id against the HF hub — typos surface as a model-load failure in
    # the browser (the UI honest-degrades to browser SR). Hot-reload.
    transformers_model: str = Field(
        default="Xenova/whisper-tiny.en",
        description=(
            "BF-301: HuggingFace model id for the browser-side "
            "transformers.js ASR pipeline. Browser fetches and caches; "
            "the runtime never holds the weights. Hot-reload."
        ),
    )
```

Mark `whisper_model_path` as deprecated by appending to its existing description (do NOT remove the field — `scripts/whisper-tiny-en-fetch.ps1` writes to that path and air-gapped operators may still use it for offline transformers.js model loads in a follow-up AD):

```python
# SEARCH
    whisper_model_path: str = "whisper/ggml-tiny.en.bin"
# REPLACE
    # BF-301: DEPRECATED. The whisper.cpp WASM artifact pipeline this
    # path was created for is abandoned upstream. Retained for one
    # release cycle; air-gapped operators may use it in a future AD to
    # pre-warm the transformers.js Cache API. New deployments should
    # ignore this field and rely on transformers.js's HF CDN fetch.
    whisper_model_path: str = "whisper/ggml-tiny.en.bin"
```

## Section 6: Backend — `src/probos/routers/voice.py` `/api/voice/health`

Replace the `get_voice_health` handler. Keep the 4-field shape (BF-294 / AD-826 back-compat). Add the optional `model` field for the transformers branch. Treat `primary_stt='whisper'` as an alias that resolves to `engine='transformers'`.

```python
# SEARCH
@router.get("/health")
async def get_voice_health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-826 — STT engine availability for the UI PTT handler.

    Returns the operator's ``cognitive.primary_stt`` selection plus an
    honest health probe for the whisper engine. Probe is filesystem-
    only: confirms ``cognitive.offline_stt_enabled`` is True AND the
    operator-pulled GGML model file exists. NO subprocess, NO model
    invocation — whisper inference runs in the browser per AD-705a.

    Response shape::

        {
          "primary_stt": "whisper" | "browser",
          "engine": "whisper" | "browser",      # primary_stt mirror
          "backend_available": bool,             # whisper artifact present
          "healthy": bool,                       # primary engine usable
        }

    ``healthy`` semantics:
    * ``primary_stt == "whisper"``: True iff ``backend_available``.
    * ``primary_stt == "browser"``: always True (the UI knows whether
      Web Speech API is supported in the current browser; backend
      cannot probe that).
    """
    config = runtime.config
    primary = config.cognitive.primary_stt
    offline_enabled = bool(config.cognitive.offline_stt_enabled)
    model_path = resolve_whisper_model_path(config, runtime.data_dir)
    backend_available = offline_enabled and model_path is not None
    healthy = backend_available if primary == "whisper" else True
    return {
        "primary_stt": primary,
        "engine": primary,
        "backend_available": backend_available,
        "healthy": healthy,
    }
# REPLACE
@router.get("/health")
async def get_voice_health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """BF-301 (#775, supersedes AD-826) — STT engine availability for the
    UI PTT handler.

    The browser-side STT engine is now @huggingface/transformers Whisper
    running in a Web Worker. The runtime no longer hosts ONNX weights —
    the browser fetches them from HF CDN on first use and caches them.
    This endpoint reports the operator's intent (primary_stt) and
    whether the local-first path is enabled (offline_stt_enabled). It
    does NOT probe the browser-to-CDN reachability — that is browser-
    side responsibility, surfaced through the BF-301
    ``onTransformersProgress`` channel.

    Response shape (4-field — back-compat with BF-294 / AD-826 UI)::

        {
          "primary_stt": "transformers" | "whisper" | "browser",
          "engine": "transformers" | "browser",
          "backend_available": bool,
          "healthy": bool,
          "model": str | None,
        }

    Engine semantics:
    * ``primary_stt`` is the raw operator config value.
    * ``engine`` is the resolved value: ``"whisper"`` (deprecated alias)
      resolves to ``"transformers"``; ``"browser"`` passes through.
    * ``backend_available`` is True iff the resolved engine is
      ``"transformers"`` AND ``offline_stt_enabled`` is True.
    * ``healthy`` is True iff ``backend_available`` is True OR resolved
      engine is ``"browser"``.
    * ``model`` is the configured transformers model id when the resolved
      engine is ``"transformers"``; ``None`` for ``"browser"``.
    """
    config = runtime.config
    primary = config.cognitive.primary_stt
    offline_enabled = bool(config.cognitive.offline_stt_enabled)
    # Resolve deprecated "whisper" alias.
    resolved_engine = "transformers" if primary in ("transformers", "whisper") else "browser"
    backend_available = resolved_engine == "transformers" and offline_enabled
    healthy = backend_available or resolved_engine == "browser"
    model = config.cognitive.transformers_model if resolved_engine == "transformers" else None
    return {
        "primary_stt": primary,
        "engine": resolved_engine,
        "backend_available": backend_available,
        "healthy": healthy,
        "model": model,
    }
```

**Note:** `resolve_whisper_model_path` is no longer imported by this function. Remove the import at the top of `voice.py`:

```python
# SEARCH
from probos.voice.whisper_model import resolve_whisper_model_path
# REPLACE
# BF-301: resolve_whisper_model_path no longer used; the browser owns
# model fetch via transformers.js. Import retained as a forward-marker
# comment for the air-gapped-operator follow-up AD.
# from probos.voice.whisper_model import resolve_whisper_model_path
```

## Section 7: AD-826 test migration

`tests/test_ad826_voice_config.py` currently asserts `engine == "whisper"` in two cases. BF-301 flips the default, so these tests must be migrated as part of this commit. Migrate, don't delete — the AD-826 invariants (Literal validation, registry registration, fallback flag) still hold:

```python
# SEARCH
def test_primary_stt_default_whisper() -> None:
    config = SystemConfig()
    assert config.cognitive.primary_stt == "whisper"
# REPLACE
def test_primary_stt_default_transformers() -> None:
    """BF-301: default flipped from 'whisper' to 'transformers'."""
    config = SystemConfig()
    assert config.cognitive.primary_stt == "transformers"


def test_primary_stt_whisper_is_deprecated_alias() -> None:
    """BF-301: 'whisper' Literal value accepted (back-compat) but resolves to transformers in health."""
    cfg = CognitiveConfig(primary_stt="whisper")
    assert cfg.primary_stt == "whisper"  # raw value preserved
```

```python
# SEARCH
def test_voice_health_endpoint_whisper_primary_unhealthy(tmp_path: Path) -> None:
    """Default config: whisper primary, no model on disk → unhealthy."""
    runtime = _FakeRuntime(tmp_path)
    # offline_stt_enabled defaults to False AND no model file → unhealthy.
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "primary_stt": "whisper",
        "engine": "whisper",
        "backend_available": False,
        "healthy": False,
    }
# REPLACE
def test_voice_health_endpoint_default_transformers_offline_disabled(tmp_path: Path) -> None:
    """BF-301: default config: transformers primary, offline_stt_enabled=False → backend unavailable, but healthy=False per AD-826 semantics (resolved engine usable only when offline_stt_enabled OR engine='browser')."""
    runtime = _FakeRuntime(tmp_path)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "primary_stt": "transformers",
        "engine": "transformers",
        "backend_available": False,
        "healthy": False,
        "model": "Xenova/whisper-tiny.en",
    }
```

```python
# SEARCH
def test_voice_health_endpoint_whisper_primary_healthy(tmp_path: Path) -> None:
    """offline_stt_enabled + model file present → healthy."""
    config = SystemConfig()
    config.cognitive.offline_stt_enabled = True
    # whisper_model_path default is "whisper/ggml-tiny.en.bin" relative to data_dir.
    model_path = tmp_path / "whisper" / "ggml-tiny.en.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"fake ggml weights")
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_stt"] == "whisper"
    assert data["engine"] == "whisper"
    assert data["backend_available"] is True
    assert data["healthy"] is True
# REPLACE
def test_voice_health_endpoint_transformers_offline_enabled_healthy(tmp_path: Path) -> None:
    """BF-301: offline_stt_enabled=True → backend_available=True, healthy=True. No filesystem probe (browser owns the model)."""
    config = SystemConfig()
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_stt"] == "transformers"
    assert data["engine"] == "transformers"
    assert data["backend_available"] is True
    assert data["healthy"] is True
    assert data["model"] == "Xenova/whisper-tiny.en"
```

Keep `test_voice_health_endpoint_browser_primary_always_healthy` as-is; only update the asserted dict to include `"model": None`.

```python
# SEARCH
    assert data["primary_stt"] == "browser"
    assert data["engine"] == "browser"
    assert data["backend_available"] is False
    assert data["healthy"] is True
# REPLACE
    assert data["primary_stt"] == "browser"
    assert data["engine"] == "browser"
    assert data["backend_available"] is False
    assert data["healthy"] is True
    assert data["model"] is None
```

Keep `test_primary_stt_accepts_browser`, `test_primary_stt_rejects_unknown_value`, `test_fallback_stt_enabled_default_true`, and `test_primary_stt_registered_in_section_registry` unchanged — they still hold.

## Section 8: New backend tests — `tests/test_bf301_voice_health.py`

Five+ tests covering the BF-301 surface area. Use the `_FakeRuntime` pattern from `test_ad826_voice_config.py` (real `SystemConfig`, NOT `MagicMock` — BF-287 lesson).

```python
"""BF-301 (#775) — transformers.js STT engine config + health endpoint."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.config import CognitiveConfig, SystemConfig
from probos.routers import voice as voice_router


class _FakeRuntime:
    def __init__(self, data_dir: Path, config: SystemConfig | None = None) -> None:
        self.config = config if config is not None else SystemConfig()
        self.data_dir = data_dir


def _make_client(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(voice_router.router)
    app.dependency_overrides[voice_router.get_runtime] = lambda: runtime
    app.dependency_overrides[voice_router.require_crew_scope] = lambda: None
    return TestClient(app)


def test_transformers_model_default() -> None:
    cfg = CognitiveConfig()
    assert cfg.transformers_model == "Xenova/whisper-tiny.en"


def test_transformers_model_accepts_base_model() -> None:
    cfg = CognitiveConfig(transformers_model="Xenova/whisper-base.en")
    assert cfg.transformers_model == "Xenova/whisper-base.en"


def test_voice_health_returns_engine_transformers_with_model(tmp_path: Path) -> None:
    config = SystemConfig()
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["engine"] == "transformers"
    assert data["model"] == "Xenova/whisper-tiny.en"
    assert data["backend_available"] is True
    assert data["healthy"] is True


def test_voice_health_whisper_alias_resolves_to_transformers(tmp_path: Path) -> None:
    """BF-301: saved configs with primary_stt='whisper' continue to work."""
    config = SystemConfig()
    config.cognitive.primary_stt = "whisper"
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["primary_stt"] == "whisper"  # raw config preserved
    assert data["engine"] == "transformers"  # resolved alias
    assert data["backend_available"] is True
    assert data["healthy"] is True


def test_voice_health_browser_primary_model_is_none(tmp_path: Path) -> None:
    config = SystemConfig()
    config.cognitive.primary_stt = "browser"
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["engine"] == "browser"
    assert data["model"] is None
    assert data["healthy"] is True


def test_voice_health_offline_disabled_unhealthy(tmp_path: Path) -> None:
    """BF-301: transformers primary + offline_stt_enabled=False → unhealthy."""
    runtime = _FakeRuntime(tmp_path)  # defaults: transformers + offline=False
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["engine"] == "transformers"
    assert data["backend_available"] is False
    assert data["healthy"] is False


def test_primary_stt_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        CognitiveConfig(primary_stt="azure")  # type: ignore[arg-type]
```

## Section 9: New frontend tests

### 9.1 `ui/src/__tests__/transformersStt.bf301.test.tsx` — 4+ tests on the worker boundary

Use the `_setTransformersWorkerOverride` seam to inject a `MessageChannel`-backed fake Worker.

Required cases:

1. **`armTransformersStt` instantiates worker and posts `{type: 'init'}`** — verify the fake worker received an init message with the model id.
2. **PCM frames between speech_start/speech_end are collected and posted as `{type: 'transcribe'}`** — drive the VAD tap via the existing `voiceActivity` test seam (import the `_emitFrame`/`_emitSpeechStart`/`_emitSpeechEnd` helpers if they exist; if not, the prompt's test must add them as a small follow-on diff to `voiceActivity.ts` — Builder verifies).
3. **Worker `{type: 'transcript', text, isPartial: false}` dispatches to `onTransformersTranscript` subscribers.**
4. **Worker `{type: 'progress', event: {...}}` dispatches to `onTransformersProgress` subscribers.**
5. **`disarmTransformersStt` posts `{type: 'shutdown'}` and terminates the worker** — verify subsequent `armTransformersStt` creates a fresh worker.

### 9.2 `ui/src/__tests__/ProfileChatTab.bf301.test.tsx` — 5+ tests

Mirror the pattern of `ProfileChatTab.ad826.test.tsx` (use the same render harness; stub `/api/voice/health` to return the BF-301 shape).

Required cases:

1. **PTT with `primary_stt: 'transformers'` calls `armTransformersStt` (not `armWhisperStt`)** — mock both modules and assert the call goes to the transformers seam.
2. **First-load progress shows the `bf301-progress` element** — emit a synthetic `onTransformersProgress` event with `progress: 0.5`; assert the bar is rendered at 50% width.
3. **`progress: 1.0` / `status: 'ready'` removes the progress UI.**
4. **`engine: 'browser'` does NOT show the progress UI** — the bar is transformers-tier-only.
5. **Streaming partial transcripts update the input progressively** — emit two `{type: 'transcript', text: '...', isPartial: true}` then a final; assert the input value sequence.
6. **Disarm cleans up subscriptions** — unmount the component; verify no further transcript callbacks fire.

## Section 10: Test gates (BOTH required — BF-279 lesson)

```powershell
# Backend
D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_bf301_voice_health.py tests/test_ad826_voice_config.py -v

# Backend regression
D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 -k "ad820 or ad821 or ad822 or ad823 or ad824 or ad825 or ad826 or bf291 or bf295 or bf296 or bf297 or bf298 or bf300" -v

# Frontend tests
cd D:\ProbOS\ui
npx vitest run

# Frontend BUILD (BF-279 lesson — vitest is NOT enough)
cd D:\ProbOS\ui
npm run build
```

All four gates MUST pass. A green vitest with a red `npm run build` blocks the operator; treat the build gate as load-bearing.

## What this does NOT change

- AD-733c-7-5 voiceActivity / Silero VAD (engine is independent of VAD).
- BF-318 speechRecognitionArbiter (mic lease semantics).
- AD-747 conversationController state machine (only the engine import changes).
- BF-290/292/293/294/294b/300 mic UX gates (the aliased imports preserve every call).
- `cognitive.fallback_stt_enabled` (still applies — fallback chain remains transformers→browser-SR).
- AD-705c wake-word training endpoints (`/api/voice/wake-word/...`).
- Vision tier (AD-732), vision_fast (AD-742a), compute_use (AD-706c-2).
- `whisper-tiny-en-fetch.ps1` — retained with a deprecation banner only; out-of-scope removal will land in a separate hygiene PR.
- Deletion of `whisperStt.ts` / `whisperLoader.ts` — deferred to a separate PR (smaller revert surface).

## Out of scope (defer)

- Multi-language model selection (default English-only; operators can swap model id via config).
- WebGPU device pinning (transformers.js v3 picks WASM+q8 / WebGPU+f16 automatically; future AD can expose `cognitive.transformers_device`).
- moonshine / distil-whisper alternatives — defer to AD-826b if tiny.en accuracy is insufficient in practice.
- Server-side STT fallback (cloud-routed) — explicit non-goal per the no-paid-solution constraint.
- Removing `whisper_model_path` from config — air-gapped operators may use it in a future AD to pre-warm the transformers.js Cache API.

## Critical constraints

- **DO NOT touch the live runtime.** No `Stop-Process`, no `taskkill`, no port-8765 / port-18900 probes.
- **DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.**
- **DO NOT delete `whisperStt.ts` / `whisperLoader.ts` / `whisper-tiny-en-fetch.ps1`** — deprecation banners only.
- **DO NOT use `asyncio.create_subprocess_exec`** anywhere (BF-280 lesson — irrelevant here but keep the standing rule visible).
- **DO NOT use `multi_replace_string_in_file` for adjacent edit blocks** in `ProfileChatTab.tsx` — use single `replace_string_in_file` calls (BF-274/278 lesson).
- **Preserve BF-290/292/293/294/294b/300 behavior** — the import aliases (`armTransformersStt as armWhisperStt`) are deliberate so the existing gating logic remains untouched.

## Tracking

- `PROGRESS.md` — append BF-301 closed line.
- `docs/development/roadmap.md` Bug Tracker — table row.
- `DECISIONS.md` — append BF-301 entry: "Migrate browser STT from whisper.cpp WASM (abandoned upstream) to @huggingface/transformers v3 + Web Worker + Xenova/whisper-tiny.en. Health endpoint `engine` value transitions whisper→transformers; `whisper` retained as deprecated alias."
- One commit, message `BF-301: migrate browser STT to transformers.js Whisper\n\nCloses #775`.

## Acceptance criteria

- All four test gates green (backend BF-301, backend AD-826 migrated, vitest full suite, `npm run build`).
- 14+ new tests (≥6 backend, ≥9 frontend) pass.
- Bundle size delta documented in commit body. Expected: `stt-vendor` chunk lands at ~1-1.5 MB compressed (transformers.js + onnxruntime-web bundled), main bundle delta ≤ +5 KB.
- Manual verification (operator-driven, post-merge):
  - Chrome PTT: identical or better than today.
  - Edge PTT: works on first try.
  - Desktop / Electron PTT: works.
  - First-load progress bar visible in mic affordance during initial model fetch.
  - DevTools → Application → Cache Storage shows `transformers-cache` populated; subsequent loads hit cache (no HF CDN requests).
  - BF-300 regression check: no mic-during-TTS echo loop.
- All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-23)

```
grep -n "armWhisperStt" ui/src/**
  ui/src/audio/conversationController.ts:50
  ui/src/components/IntentSurface.tsx:11,247
  ui/src/components/profile/ProfileChatTab.tsx:20,1021,1073

grep -n "primary_stt" src/probos/config.py
  274: primary_stt: Literal["whisper", "browser"] = Field(
  default="whisper",

grep -n "engine.*primary_stt\|backend_available\|model_path" src/probos/routers/voice.py
  62: model_path = resolve_whisper_model_path(config, runtime.data_dir)
  63: backend_available = offline_enabled and model_path is not None
  64: healthy = backend_available if primary == "whisper" else True
  67: "engine": primary,

grep -n "manualChunks" ui/vite.config.ts
  21: manualChunks(id: string) {

grep -n "onnxruntime-web\|@huggingface/transformers\|@xenova" ui/package.json
  optionalDependencies: onnxruntime-web ^1.18.0 (only; transformers/@xenova absent)

grep -n "engine.*whisper\|primary_stt.*whisper" tests/test_ad826_voice_config.py
  65: "engine": "whisper",
  92: assert data["engine"] == "whisper"

grep -n "VoiceHealth" ui/src/components/profile/ProfileChatTab.tsx
  6: interface VoiceHealth {
  170: const [voiceHealth, setVoiceHealth] = useState<VoiceHealth | null>(null);
  1121: voiceHealth?.engine === 'whisper' ? 'Voice input (whisper)' :
```

Every concrete claim in this prompt (file paths, line numbers, identifiers, current shapes) is verified against HEAD on 2026-05-23.
