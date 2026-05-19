# Whisper tiny.en GGML model (AD-721b-3 / AD-705a)

The offline STT path (AD-705a) and lip-sync phoneme alignment (AD-721b
family) optionally use the [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
WASM runtime + the `ggml-tiny.en.bin` model (~75 MB). The artifacts are
**NOT bundled** in the OSS repository — operators install them locally.

## Installation

1. Run `./scripts/whisper-tiny-en-fetch.ps1` from the repository root.
   This downloads three files into `data/whisper/`:
   - `ggml-tiny.en.bin` (~75 MB, SHA-256 verified)
   - `whisper.js` (UMD glue, ~50 KB)
   - `whisper.wasm` (~3 MB)
2. The browser fetches each file from `/data/whisper/` via the static
   route the runtime already exposes for `/data/silero-vad/`.
3. No npm install required — whisper.cpp ships as standalone WASM.

## Fallback

If any of the three artifacts is missing, `whisperLoader.loadWhisperModel()`
returns `null` and the AD-705a STT path honest-degrades to the existing
browser-native `SpeechRecognition` (which on Chrome is cloud-routed —
operators who want fully-offline voice MUST run the fetch script).

## License

- whisper.cpp WASM glue: MIT
  (<https://github.com/ggerganov/whisper.cpp/blob/master/LICENSE>).
- Whisper tiny.en model weights: MIT
  (<https://github.com/openai/whisper/blob/main/LICENSE>).
