# Third-party licenses

ProbOS is distributed under the Apache License, Version 2.0. The following
third-party components are referenced or optionally used at runtime. None
of them is shipped as a bundled binary in this OSS repository — operators
install the relevant runtime/model files locally per the linked READMEs.

## openWakeWord (AD-705)

- Project: <https://github.com/dscripka/openWakeWord>
- Author: David Scripka
- License: Apache License, Version 2.0
- Used by: `ui/src/audio/wakeWord.ts`
- Installation: `ui/public/models/wake-word/README.md`
- License text: `ui/public/models/wake-word/LICENSE-openwakeword.txt`

## Silero VAD (AD-705)

- Project: <https://github.com/snakers4/silero-vad>
- Author: Silero Team
- License: MIT
- Used by: `ui/src/audio/wakeWord.ts`
- Installation: `ui/public/models/vad/README.md`
- License text: `ui/public/models/vad/LICENSE-silero.txt`

## ONNX Runtime Web (AD-705)

- Project: <https://github.com/microsoft/onnxruntime>
- Author: Microsoft
- License: MIT
- Used by: `ui/src/audio/wakeWord.ts` (lazy-loaded; optional dependency)
- Installation: `npm install --prefix ui onnxruntime-web`

## Picovoice Porcupine — REJECTED (license incompatibility)

Pattern-absorption only. The free tier requires an AccessKey, which is
incompatible with this OSS project's Apache-2.0 / no-paid-license posture.
See the wake-word disposition table in `prompts/WAVE-137-DISPATCH.md` §2.

---

When adding a new third-party component:

1. Verify the license is permissive (MIT / Apache-2.0 / BSD / CC0 /
   MPL-2.0 / CC-BY-4.0). Reject AGPL/GPL and any paid-license deps.
2. Add an entry above with the project URL, author, license, and pointer
   to local installation docs.
3. If the component ships a binary (model weights, ONNX file, etc.), do
   NOT bundle it in this repo — document operator-side installation.
4. Surface the disposition in the relevant build prompt's License posture
   section before drafting deliverables.
