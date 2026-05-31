# Prior-Art Research — Wave 179 (voice stack completion)

**Drafted:** 2026-05-19 (architect-only, pre-build).
**Scope:** Architectural inputs for AD-721b-3 (whisper.cpp WASM tiny.en model bundle), AD-705a (offline STT via whisper.cpp WASM), AD-705c (custom wake-word training).
**Posture:** Pattern absorption. **Zero new pip / npm deps land in Wave 179** (whisper.cpp WASM is a runtime artifact, not an npm package; openWakeWord training is Python and `numpy` / `scikit-learn` / `torch` are already resident via `facenet-pytorch`). Every absorbed pattern is re-implemented in ProbOS-native code.

---

## 1. License-Aware Absorption Table

| Project | License | What it does | Absorb (pattern) | Do NOT absorb | Why |
|---|---|---|---|---|---|
| **whisper.cpp (`ggerganov/whisper.cpp`)** | MIT | C++ port of OpenAI Whisper + WASM build target. Reference WASM example under `examples/whisper.wasm/`. | The WASM runtime (`whisper.wasm` + `whisper.js` glue) shipped as a static artifact; the `examples/whisper.wasm/main.js` loader pattern; the `whisper_full(...)` API surface; the `ggml-*.bin` model file format. | The C++ source (we don't recompile); the demo HTML/CSS. | **Direct artifact-level dependency.** MIT-clean. The runtime + tiny.en model file are operator-pullable; bytes never committed. Whisper model weights themselves are MIT (OpenAI release, separate from the wrapper). |
| **OpenAI Whisper model weights (`openai/whisper`)** | MIT | The acoustic model. `tiny.en`-`large-v3` checkpoints. `tiny.en` is ~75 MB ggml-quantized. | The `ggml-tiny.en.bin` model file (operator-pull, gitignored). | The PyTorch weights themselves; the Python inference pipeline. | MIT model release. Distribution via Hugging Face mirror is the canonical path. tiny.en gives ~85-90% WER on clean dictation English — sufficient for Captain voice commands. |
| **transformers.js (`xenova/transformers.js`)** | Apache 2.0 | Browser-native ML pipeline (ONNX-runtime-web under the hood). Whisper supported. | Architectural alternative reference only. | Zero code in v1. | Heavier runtime (~15 MB ORT-web + ~75 MB ONNX-quantized tiny.en model) and adds a transformer pipeline abstraction we don't need for v1 single-model use. Filed as forward marker `AD-705a-1` if a future surface needs the broader pipeline (Whisper + multilingual + summarization in one runtime). |
| **whisper-web (`xenova/whisper-web`)** | Apache 2.0 | Reference UI integration of transformers.js Whisper. | UX patterns: drop-zone for file transcription; toggle between local-quantized vs hosted; "model loading…" progress; copy-transcript affordance. | Zero code (depends on transformers.js). | Pure UX reference. Confirms the design space: a sidecar Whisper surface is feasible browser-side. |
| **whisper.cpp WASM streaming demo** | MIT (same upstream) | Chunked streaming Whisper inference in the browser. | The chunked-decode + context-carryover pattern (forward marker only — v1 is batch). | The streaming code in v1. | v1 ships batch decode (VAD-bounded utterance). Streaming is forward marker `AD-705a-4`. |
| **wav2vec2 (`facebookresearch/fairseq`) / Moonshine (`usefulsensors/moonshine`)** | Apache 2.0 / Apache 2.0 | Alternative STT model families. Moonshine targets edge devices (~27 M params, smaller than Whisper tiny). | Reference data point for model selection. | Zero code. | Moonshine in particular is a credible v2 path — Apache 2.0, optimized for low-latency edge inference. Filed as forward marker `AD-705a-5` (alternative model backend). |
| **Silero VAD (`snakers4/silero-vad`)** | MIT | Frame-level voice-activity detection. **Already integrated** in ProbOS via AD-733c-7 (`ui/src/audio/silero-vad.ts` + `ui/src/audio/voiceActivity.ts`). | The existing seam — `createVadSession()` + speech-start/speech-end events drive when STT runs. | Already absorbed. | The VAD→STT handoff is the cleanest cost-control gate: only invoke Whisper between confirmed VAD speech-start and the matching speech-end. Eliminates the cost of decoding silence frames. |
| **OpenAI Realtime API** | Closed product | Reference end-to-end voice-to-action UX. | The "press-to-talk vs always-on" UX framing only. | Zero code. | Confirms the industry-converged shape: VAD-bounded utterance → STT → LLM → TTS. v1 follows the same shape locally. |
| **Picovoice Porcupine** | Proprietary, freemium | Wake-word detection (browser SDK + CLI training). | Reference data point for the custom-training UX (Picovoice Console is the most polished training UX in the industry). | Zero code; **proprietary license**. Captain rule (2026-05-09): "OSS repo: never absorb anything requiring a paid license." | **Captain's brief mentions "AD-733c-3's existing Picovoice path"; the actual codebase uses openWakeWord (see `ui/public/models/wake-word/README.md` + `ui/src/audio/wakeWord.ts:_loadOnnxRuntime`). Surfaced in the architect's final report as a clarification, NOT a blocker.** |
| **openWakeWord (`dscripka/openWakeWord`)** | Apache 2.0 | Open-source wake-word framework with Python training pipeline. Stock community models (`hey_jarvis_v0.1.onnx` etc.) already operator-installed under `ui/public/models/wake-word/`. | The training pipeline (`openwakeword.train.train_custom_verifier_model`); the ONNX export path; the negative-sample synthesis from common-voice / Mozilla audio corpora; the per-sample augmentation pipeline (noise, pitch, speed). | The pre-trained stock weights (already operator-pulled). | **Direct pipeline dependency for AD-705c.** Apache 2.0. Stock models ship Apache 2.0 weights. Active fork (2026 commits). |
| **Mycroft Precise (`MycroftAI/mycroft-precise`)** | Apache 2.0 | End-to-end wake-word training in Python. | The CLI ergonomics (`precise-collect`, `precise-train`, `precise-test`). | No code lift. Mycroft AI shut down 2023; project unmaintained. | Pattern-only reference for the CLI shape (`probos wake-word collect / train / test`). |
| **Snowboy** | DEPRECATED (KITT.AI shutdown 2020) | Pre-deprecation wake-word framework. | Pattern-only — documented training data requirements (200-500 positive + 1000+ negative samples). | Zero code. | Historical reference for sample-count expectations. |
| **Howl (`castorini/howl`)** | MIT | Wake-word framework with hot-word transfer learning. | The transfer-learning approach (fine-tune from a pre-trained encoder vs train from scratch). | Zero code in v1. | Forward marker `AD-705c-2` — transfer learning shrinks the sample requirement to ~20 positive utterances. Genuinely better UX but training infrastructure is heavier (PyTorch DataLoader pipeline). v1 sticks with openWakeWord's documented path. |
| **EfficientWord-Net (`Ant-Brain/EfficientWord-Net`)** | MIT | Few-shot wake-word training (3-5 utterances per word). | Few-shot architecture as a future option. | Zero code. | Forward marker `AD-705c-3`. Smaller community than openWakeWord; defer until validated by demand. |
| **Aeneas (`readbeyond/aeneas`)** | GPL-3.0 | Forced alignment between audio and text. | Pattern only — phoneme-level alignment is what whisper.cpp's `word_timestamps` already gives us. | **Zero code. GPL would propagate.** | Whisper's built-in word/phoneme timestamps subsume the use case. |
| **Montreal Forced Aligner** | MIT | Heavyweight server-side forced aligner. | Reference only. | Zero code. | Overkill for browser-side. whisper.cpp `whisper_full_params.token_timestamps=true` already produces token-level timestamps usable by `LipSyncTrack` (AD-721b). |

**Default disposition.** Pattern absorption (whisper.cpp WASM runtime is the lone artifact-level dependency, and even there we pull operator-side — zero bytes in the repo). The OSS repo stays MIT/Apache-only. Zero deps land in Wave 179.

---

## 2. Architectural Decisions (Phase 3 of dispatch spec)

### Decision 1 — Whisper backend: **whisper.cpp WASM** (not transformers.js)

Both are MIT/Apache. The deciding factors:

- **Bundle size.** whisper.cpp WASM = ~3 MB runtime + ~75 MB model. transformers.js Whisper = ~15 MB ORT-web + ~75 MB model. WASM wins by ~12 MB at first-paint cost.
- **API surface.** whisper.cpp exposes one C entry point (`whisper_full`); transformers.js wraps a pipeline abstraction we don't need.
- **Cross-AD consistency.** AD-721b family already lists whisper.cpp WASM as the canonical phoneme-alignment backend (`AD-721b-3` was filed as "whisper.cpp WASM tiny.en"). Using the same runtime for STT + phoneme alignment is DRY.
- **Maintenance.** whisper.cpp upstream is one of the most active C++ projects on GitHub (~30 K stars). Long-tail support is not a concern.

Forward marker `AD-705a-1`: transformers.js path if a future surface needs the broader ML-pipeline abstraction (e.g., on-device summarization + STT in one runtime).

### Decision 2 — Model distribution: **operator-pull PowerShell script**, mirrors `silero-vad-fetch.ps1` + `piper-voice-fetch.ps1`

| Option | Pros | Cons | Disposition |
|---|---|---|---|
| Operator-pull script | License-clean (zero bytes in repo); deterministic SHA pin; offline-after-fetch | First-run friction (one PowerShell command) | **v1 ships this.** Mirrors AD-733c-7 / AD-738 patterns. |
| Lazy CDN fetch on first use | Zero operator friction | Pulls third party into trust boundary; offline-by-default principle violated; CDN URL ownership churn | Forward marker `AD-705a-3`. |
| IndexedDB persistent cache after first fetch | Bandwidth-efficient on repeat visits | Adds storage-quota state to debug; cache invalidation on model version change | Forward marker `AD-705a-2`. Layered on top of v1 (browser fetches from local `/data/whisper/...` first, falls back to IDB cache, falls back to operator-pull instruction). |

The model bytes live at `data/whisper/ggml-tiny.en.bin` (gitignored under the existing `data/*` rule). The browser fetches via the existing static-file path (same pattern as AD-733c-7's `/data/silero-vad/silero_vad.onnx`). `THIRD_PARTY_LICENSES.md` gains a whisper.cpp entry + a Whisper model card entry at AD-705a ship time (not in AD-721b-3 since the model bundle alone is the artifact).

### Decision 3 — Streaming vs batch: **v1 batch (VAD-bounded utterance)**

- Captain wants tiny.en. Inference of a 5-10s clean dictation utterance on tiny.en + WASM = ~1-2 s on modern hardware (whisper.cpp benchmarks).
- Streaming Whisper requires chunked decode with context-state preservation across chunks. Implementation surface is ~3x larger; the v1 use case (post-VAD-speech-end dictation) doesn't need it.
- Forward marker `AD-705a-4` (streaming/incremental decode).

UX implication: a 1-2 s "transcribing…" indicator after VAD signals speech-end. Acceptable for v1 — Captain explicitly approved tiny.en. If latency proves intolerable, forward marker is the path.

### Decision 4 — VAD→STT seam: **extend the existing `voiceActivity.ts` mic stream** (DRY)

Two implementation paths considered:

| Option | Wins | Loses |
|---|---|---|
| **Extend existing stream.** Add a `pcmTap()` exporter on `voiceActivity.ts` that emits a ring buffer of recent Float32 PCM frames. New `whisperStt.ts` subscribes to the same tap, runs Whisper inference between speech-start and speech-end. | One `getUserMedia({audio: true})` stream; one permission prompt; cheapest CPU path (VAD already running); gating logic trivial (only run STT inside the VAD speech window). | Mild coupling between two audio modules. |
| Open parallel mic stream | SRP / isolated lifecycles | Two permission prompts (UX regression); two PCM consumers competing for the AudioContext; potential clock-skew between VAD scores and STT samples. | |

**Decision: extend.** The two modules already share the same conceptual layer (raw PCM consumers); separation would be premature SRP. Implementation: `voiceActivity.ts` exposes a new `subscribePcm(callback)` returning an unsubscribe handle. `whisperStt.ts` arms its inference window when VAD fires speech-start and runs `whisper_full` on the captured buffer when speech-end fires.

### Decision 5 — Wake-word trainer backend: **openWakeWord** (Apache 2.0)

| Backend | License | Active? | Sample count | Training compute | Disposition |
|---|---|---|---|---|---|
| **openWakeWord** | Apache 2.0 | Yes (2026 commits) | 200-500 positive + 1000+ synthetic negative | Server-side Python; ~5-15 min on CPU | **v1 ships this.** |
| Mycroft Precise | Apache 2.0 | No (org shut down 2023) | Similar | Similar | Pattern reference only. |
| Howl (transfer learning) | MIT | Slow | ~20 positive (via fine-tune) | Heavier PyTorch DataLoader | Forward marker `AD-705c-2`. |
| EfficientWord-Net (few-shot) | MIT | Slow | 3-5 positive | Lightweight | Forward marker `AD-705c-3`. |

openWakeWord is the matured baseline. The stock community models we already operator-install (`hey_jarvis_v0.1.onnx`) come from this project — using the same training pipeline to produce a custom model is the lowest-deviation path.

### Decision 6 — Trainer UX: **CLI-first (`probos wake-word` subcommand) + optional browser sample-recorder**

Three options considered:

| UX | Captain effort | Quality | v1? |
|---|---|---|---|
| **CLI only:** operator places `.wav` files under `data/wake-word/training-samples/positive/` + `data/wake-word/training-samples/negative/`, runs `probos wake-word train --label "Computer"`. | Manual sample collection (record via Audacity / phone) | Highest (operator picks samples) | **v1 ships this.** |
| Browser sample recorder: reuse the existing `getUserMedia({audio: true})` stream from AD-733c-7; record N positive utterances via guided prompts ("Say 'Computer' — utterance 1 of 50"). | Easiest | Mediocre (same mic, same room — over-fit risk) | **v1 ships this as an OPT-IN secondary path.** |
| Browser-only with no CLI fallback | Easiest | Same as above | No — operators with privacy preferences need a no-browser path. |

The CLI path is the canonical training surface. The browser recorder is an opt-in convenience that uploads samples to the same `data/wake-word/training-samples/` directory (multipart, single-shot per utterance). Samples are gitignored; deleted by the operator after training (or retained per a new `WakeWordConfig.retain_training_samples` flag, default `False` so the bytes are reaped after the ONNX is written).

### Decision 7 — Privacy posture

**STT (AD-705a):** Audio NEVER leaves the browser. Whisper inference is entirely WASM-side. The only thing posted back to the runtime is the resulting transcript string — flowing into the existing `agent_chat` DM endpoint as if the Captain typed it. Regression test asserts no fetch body in the new `whisperStt.ts` contains audio bytes / base64 / PCM. Mirrors the AD-733c-7 privacy invariant exactly.

**Wake-word training (AD-705c):** Audio samples upload via authenticated multipart (require_crew_scope) to `data/wake-word/training-samples/`. Samples are local-only — never federated, never logged externally. Default retention: delete after training (`retain_training_samples=False`). Operator opt-in to retain via the new config flag.

### Decision 8 — Existing wake-word path: **AUGMENT, not replace**

Captain's brief mentions Picovoice; the actual codebase uses openWakeWord stock community models (verified: `ui/public/models/wake-word/README.md` references `hey_jarvis_v0.1.onnx` from openWakeWord; `ui/src/audio/wakeWord.ts:_loadOnnxRuntime` lazy-loads `onnxruntime-web`; no Picovoice imports anywhere). Surfaced as a clarification (not a blocker) in the architect's final report.

v1 of AD-705c lands the custom-trained ONNX under `ui/public/models/wake-word/captain.onnx`. The existing `wakeWord.ts` loader tries `captain.onnx` first, falls back to the stock community model if `captain.onnx` is missing. New `WakeWordConfig.custom_model_filename` (default `"captain.onnx"`) lets operators name the file.

---

## 3. Open Questions Surfaced for Captain (GATE 1)

1. **Whisper model size.** Captain approved tiny.en. Confirm acceptance of ~85-90% WER on clean English dictation (typical-room conditions). Larger models (base.en ~150 MB, small.en ~500 MB) are forward-marker territory.
2. **Training sample collection UX.** v1 ships both CLI and browser-recorder paths. Captain preference for documentation emphasis? CLI-first or browser-first in the manual?
3. **Retain training samples after train?** Default `False` (delete after ONNX is written). Captain opt-in via `retain_training_samples=True` if they want to retrain later.
4. **Custom model filename convention.** Default `captain.onnx`. Multi-Captain support deferred (every fleet member trains their own wake-word in `data/wake-word/<callsign>.onnx`) — forward marker `AD-705c-4`.

---

## 4. v1 vs Forward-Marker Matrix

| Capability | v1 (Wave 179) | Forward marker |
|---|---|---|
| Whisper backend | whisper.cpp WASM | transformers.js — `AD-705a-1` |
| Model distribution | Operator-pull script | IndexedDB cache — `AD-705a-2`; lazy CDN — `AD-705a-3` |
| Decode mode | Batch (VAD-bounded) | Streaming — `AD-705a-4` |
| Model family | Whisper tiny.en (English only) | Moonshine alternative — `AD-705a-5`; multilingual Whisper — `AD-705a-6` |
| Mic stream | Reuse AD-733c-7 stream | — |
| Wake-word trainer | openWakeWord | Howl transfer learning — `AD-705c-2`; EfficientWord-Net few-shot — `AD-705c-3` |
| Trainer UX | CLI + browser recorder | Active-learning sample selection — `AD-705c-5` |
| Per-Captain wake-word | Single `captain.onnx` | Multi-Captain — `AD-705c-4` |
| Streaming wake-word from VAD | (out of scope) | `AD-733c-7-4` (VAD-driven wake-word mute, already filed Wave 176) |

---

## 5. License Hygiene Summary

| Item | License | Source |
|---|---|---|
| whisper.cpp WASM runtime | MIT | `ggerganov/whisper.cpp` |
| ggml-tiny.en.bin model | MIT (OpenAI Whisper release) | Hugging Face mirror of `openai/whisper` |
| openWakeWord training pipeline | Apache 2.0 | `dscripka/openWakeWord` |
| Stock community wake-word models | Apache 2.0 | Same upstream |
| onnxruntime-web | MIT (Microsoft) | Already resident (AD-733c-7) |
| Mozilla Common Voice (training negative samples) | CC0 | https://commonvoice.mozilla.org/ — optional augmentation |

**Hard rejections (license-incompatible):** Picovoice (proprietary), Aeneas (GPL-3.0), Open Interpreter (AGPL — pattern reference only, no code), Khoj (AGPL).

**THIRD_PARTY_LICENSES.md updates at ship time:**
- AD-721b-3 ships: 0-line diff (the model file alone is operator-pulled; no in-repo artifact triggers an attribution claim).
- AD-705a ships: +1 entry for whisper.cpp (MIT) + +1 entry for OpenAI Whisper model weights (MIT).
- AD-705c ships: +1 entry for openWakeWord (Apache 2.0).

`pyproject.toml`, `package.json`, `package-lock.json`, `LICENSE` — **0-line diff across the wave** (no new pip / npm deps; openWakeWord training pipeline is shipped as an operator-side requirement, surfaced via a documented `pip install openwakeword[training]` instruction in the wake-word README — NOT a hard dep in the project's main `pyproject.toml`. The runtime never imports openWakeWord; only the trainer CLI does, and the trainer CLI is operator-invoked).

---

## 6. Anti-Patterns to Avoid (top 3)

1. **Audio bytes in network requests.** Privacy invariant from AD-733c-7. STT inference is browser-local; only the transcript string crosses the wire. Wake-word training samples go via authenticated multipart to local disk — not federation, not telemetry.
2. **Static-import the ONNX runtime.** `wakeWord.ts:_loadOnnxRuntime` and `silero-vad.ts:_loadOnnxRuntime` both use the indirect-string-variable lazy-import pattern. Whisper WASM uses a similar lazy script-tag injection. First-paint MUST NOT regress for Captains who never enable voice.
3. **Hand-roll a wake-word training pipeline.** openWakeWord exists, is Apache 2.0, is mature, and matches our existing stock-model deployment. A bespoke ONNX export pipeline would be a maintenance burden with no functional advantage.
