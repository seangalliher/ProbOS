# TTS Backends Evaluation (AD-718b, Wave 168)

**Status:** Research audit. **Parent:** AD-738 (Piper, Wave 157). **Closes:** #523. **Date:** 2026-05-17.

## Scope

Audit Coqui-TTS, Bark, and ElevenLabs as candidate TTS backends to slot alongside the AD-738 Piper backend via the `backend: str` extension point in `ui/src/audio/voice.ts:134` and `src/probos/audio/tts/backends.py`.

License whitelist per `.github/copilot-instructions.md` Captain rule 2026-05-09: MIT > Apache 2.0 > BSD > CC0 > MPL-2.0 > CC-BY-4.0. AGPL/GPL rejected. Paid-license deps rejected for OSS. Mixed-license repos require per-component review (lib license vs model-weight license — the OmniParser lesson: CC-BY-4.0 repo can ship AGPL weights).

## Verdict Summary

| Backend | Lib license | Model-weights license | Install footprint | Quality vs Piper | Cross-platform | Verdict |
|---------|-------------|------------------------|-------------------|-------------------|----------------|---------|
| Coqui-TTS | MPL-2.0 (permissive enough) | XTTS v2 **CPML non-commercial** (REJECTED); some VITS models MIT/Apache | ~2.0 GB weights + `torch` runtime (~600 MB) | Higher (XTTS multilingual SOTA-class); Piper-comparable for VITS | Win/Linux/macOS via torch | **DEFER (AD-718b-1)** — lib only, CPML weights blacklisted, operator whitelist required |
| Bark | MIT (suno-ai/bark) | MIT (model weights also MIT) | ~4.0 GB weights + `torch` runtime | Comparable expressivity, ~3-10x slower than Piper, no streaming | Win/Linux/macOS via torch | **DEFER (AD-718b-2)** — clean license, install footprint is the friction |
| ElevenLabs | Closed-source HTTP API | N/A (cloud-only) | ~0 (HTTP client + API key) | Higher (commercial SOTA) | All (HTTP) | **REJECT** — paid commercial; conflicts with OSS Captain rule |

## Coqui-TTS

### License analysis

- **Library:** [coqui-ai/TTS](https://github.com/coqui-ai/TTS) is **MPL-2.0**. MPL-2.0 is on the Captain whitelist as a weak-copyleft license — acceptable when used as a library dependency without modification of MPL-licensed files. Modifications to MPL files must remain MPL; static or dynamic linking from Apache 2.0 code is permitted.
- **Model weights — split decision:**
  - **XTTS v2** (the SOTA multilingual model): **CPML (Coqui Public Model License)** — non-commercial only. **REJECTED** for both OSS and commercial-overlay packaging. Operators may use it locally under CPML terms; ProbOS will not ship or auto-download CPML weights.
  - **VITS-based voices** (older Coqui catalog, including some YourTTS variants): individually MIT or Apache 2.0. Whitelist-by-name only; ship a curated `coqui_voices_allowlist.txt` if AD-718b-1 ever lands.
  - **Tortoise-TTS** distributed via Coqui: Apache 2.0. Acceptable, slow.
- **OmniParser lesson applied:** the repo wrapper license (MPL-2.0) does NOT cover the model artifacts. Per-model review is mandatory before any auto-download path.

### Install footprint

- `pip install TTS` pulls `torch>=2.0` (~700 MB on CPU, ~2.5 GB CUDA). Total cold install ~1 GB.
- Default model download: XTTS v2 is ~1.8 GB. VITS models are 50–200 MB each.
- Runtime memory: 1.5–3 GB RAM for XTTS inference; 200–400 MB for VITS.
- Cold-start latency: 8–15s first inference (torch + model load); subsequent ~300 ms per sentence on CPU.

### Voice quality vs Piper

- **XTTS v2:** SOTA-class multilingual, voice-clone-capable, expressive prosody. Subjectively higher than Piper. (CPML — REJECTED for our purposes.)
- **VITS:** competitive with Piper on English, similar inference speed. Quality parity, license parity — but adds the torch runtime tax.

### Cross-platform support

Win/Linux/macOS via torch. CUDA optional but recommended for XTTS. Apple MPS supported. ARM Linux (Raspberry Pi-class) NOT supported (torch wheels gap).

### Verdict

**DEFER to AD-718b-1.** Two preconditions for graduation:
1. Operator demand for multilingual quality beyond AD-718e's Piper 27-voice catalog.
2. Community publishing a Coqui voice set covering ≥10 languages under MIT/Apache 2.0 (NOT CPML).

Until both: no integration. AD-738 Piper + AD-718e multi-language voices cover the v1 surface.

## Bark

### License analysis

- **Library:** [suno-ai/bark](https://github.com/suno-ai/bark) is **MIT**. Whitelist top tier — no copyleft, no commercial restrictions.
- **Model weights:** MIT (same repo). Verified via `LICENSE` at repo root and model card.
- Clean across the board. Operator-friendly.

### Install footprint

- `pip install git+https://github.com/suno-ai/bark` (no PyPI release as of audit date). Pulls `torch`, `transformers`, `scipy`, `soundfile`. Cold install ~1.2 GB.
- Model weights: ~4 GB (text, coarse, fine, codec).
- Runtime memory: 4–6 GB RAM for inference (8 GB recommended). GPU strongly preferred.
- Cold-start: 10–20s first inference. Per-sentence: 5–15s on CPU, 1–3s on GPU. NO streaming output.

### Voice quality vs Piper

Comparable expressivity with notable strengths in non-speech sounds (laughs, sighs, music). Weaknesses: 13s max output per call (segments must be stitched), no per-voice fine-tuning without weight retraining, generation is non-deterministic (same prompt yields different audio).

### Cross-platform support

Win/Linux/macOS via torch. CUDA recommended for production use. CPU-only viable for dev / single-user. ARM Linux NOT supported.

### Verdict

**DEFER to AD-718b-2.** Three preconditions for graduation:
1. Operator demand for expressive non-speech audio (laughs, ambient sounds) beyond what Piper + AD-738e-1 emotional prosody covers.
2. Streaming or chunked generation pattern that masks per-call 5–15s latency.
3. ARM Linux story (or explicit deferral to x86-only deployments).

Until then: AD-738 Piper covers the production case.

## ElevenLabs

### License analysis

- **Closed-source HTTP API.** Paid commercial tiers only; no free tier viable for production.
- Operator must hold a paid account and provide an API key.

### Install footprint

- ~0 server-side (HTTP client + API key). Network round-trip per request (~500–1500ms).

### Voice quality vs Piper

SOTA commercial. Substantially higher than any open-source backend audited.

### Cross-platform support

All (HTTP).

### Verdict

**REJECT** for the OSS code path.

- Captain rule 2026-05-09: *"never absorb anything in the OSS repo that requires a paid license."*
- Even an opt-in extension creates an OSS code path that is non-functional without payment, contradicting the "free should stay free; users bring their own model weights / API keys" principle.
- Bring-your-own-key extensions for paid HTTP APIs are out of scope for this audit; revisit only via separate disposition.

No forward marker filed; no AD number reserved.

## Forward markers

- **AD-718b-1** — Coqui-TTS backend (MPL-2.0 lib; CPML weights rejected; per-voice MIT/Apache 2.0 allowlist required). Trigger: operator demand + community publishing ≥10-language MIT/Apache voice set.
- **AD-718b-2** — Bark backend (MIT lib + weights). Trigger: operator demand + streaming-output pattern + ARM Linux disposition.
- **AD-718b (ElevenLabs branch)** — NOT FILED. Paid commercial; rejected per OSS rule.

## Extension point preserved

The AD-738-shipped `backend: str` extension is unchanged:

- `ui/src/audio/voice.ts:134` — `type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string };`
- `src/probos/audio/tts/backends.py` — backend registry (1758 bytes).

When AD-718b-1 or AD-718b-2 fires, the implementer registers a new `Backend` class in `backends.py` and extends the literal-union in `voice.ts` — no spec rewrite required.

## No-deps confirmation

Zero new pip deps. Zero new npm deps. Zero new model downloads. Pure documentation.
