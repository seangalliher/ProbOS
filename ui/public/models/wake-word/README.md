# Wake-word ONNX models (AD-705)

The wake-word voice loop (`ui/src/audio/wakeWord.ts`) lazy-loads an
[openWakeWord](https://github.com/dscripka/openWakeWord) ONNX model from this
directory at runtime. The model file is **NOT bundled** in the OSS repository:
it is operator-installed so the OSS image stays small and license-clean.

## Recommended model

`hey_jarvis_v0.1.onnx` (or any small openWakeWord stock model). The "Computer"
label in the HXI is independent of the underlying model — the user-visible
wake phrase is configured in `ui/src/audio/wakeWord.router.ts`
(`STATIC_WAKE_PHRASES`) and the substring-match fallback uses that list
verbatim.

## Installation

1. Download the ONNX model from
   <https://github.com/dscripka/openWakeWord/tree/main/openwakeword/resources/models>.
2. Place it as `ui/public/models/wake-word/<model>.onnx`.
3. Install the runtime: `npm install --prefix ui onnxruntime-web`.

## Fallback

If either the runtime or the model file is missing, the wake-word loop falls
through to a Tier-2 substring-match fallback over continuous browser
SpeechRecognition. The Captain sees a "Voice unavailable: ONNX runtime failed
to load" label on the indicator, and the loop still functions at degraded
accuracy.

## License

`hey_jarvis_v0.1.onnx` and other openWakeWord stock models are released under
Apache-2.0 by David Scripka. See `LICENSE-openwakeword.txt` in this directory.
