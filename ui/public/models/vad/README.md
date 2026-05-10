# Silero VAD ONNX (AD-705)

The wake-word voice loop optionally uses [Silero VAD](https://github.com/snakers4/silero-vad)
to bound the post-wake utterance capture window. The ONNX file is **NOT
bundled** in the OSS repository — operators install it locally.

## Installation

1. Download `silero_vad.onnx` (~1.8 MB) from
   <https://github.com/snakers4/silero-vad>.
2. Place it as `ui/public/models/vad/silero_vad.onnx`.
3. Ensure `onnxruntime-web` is installed (see `../wake-word/README.md`).

## Fallback

If the model file or runtime is missing, the wake-word loop falls back to
the browser-native `onspeechend` heuristic (already wired) plus a hard
silence timeout (`SILENCE_TIMEOUT_MS = 1500ms`) plus a hard ceiling
(`UTTERANCE_MAX_DURATION_MS = 10000ms`). Capture still works; accuracy of
end-of-utterance detection is reduced.

## License

Silero VAD is released under MIT. See `LICENSE-silero.txt` in this directory.
