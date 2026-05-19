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

## pypdf (AD-720a-1)

- Project: <https://github.com/py-pdf/pypdf>
- License: BSD-3-Clause
- Used by: `src/probos/cognitive/text_extractor.py` (`_extract_pdf`)
- Installed via `pyproject.toml` `[project.dependencies]`: `pypdf>=4.0`.

## python-docx (AD-720a-1)

- Project: <https://github.com/python-openxml/python-docx>
- License: MIT
- Used by: `src/probos/cognitive/text_extractor.py` (`_extract_docx`)
- Installed via `pyproject.toml` `[project.dependencies]`: `python-docx>=1.1`.

## openpyxl (AD-720a-1)

- Project: <https://foss.heptapod.net/openpyxl/openpyxl>
- License: MIT
- Used by: `src/probos/cognitive/text_extractor.py` (`_extract_xlsx`)
- Installed via `pyproject.toml` `[project.dependencies]`: `openpyxl>=3.1`.

## cryptography (AD-706f)

- Project: <https://github.com/pyca/cryptography>
- License: Apache-2.0 OR BSD-3-Clause (dual-licensed; verified via `pip show cryptography` License-Expression field)
- Version pinned: `cryptography>=42` (installed: 48.0.0)
- Used by: `src/probos/tools/browser/credentials.py` (`cryptography.fernet.Fernet` for symmetric authenticated encryption of stored credentials)
- Installed via `pyproject.toml` `[project.dependencies]`: `cryptography>=42`.


## moondream (AD-742a)

- Project: <https://github.com/vikhyat/moondream>
- Author: vikhyat (Vikhyat Korrapati)
- License: Apache License, Version 2.0
- Model card: <https://huggingface.co/vikhyatk/moondream2>
- Used by: `src/probos/perception/consumer.py` `_describe` path as the
  default per-frame vision_fast model (`llm_model_vision_fast: moondream`)
- Installation: operator-pullable via `ollama pull moondream`. NOT bundled.


## facenet-pytorch (AD-742b)

- Project: <https://github.com/timesler/facenet-pytorch>
- Author: Tim Esler
- License: MIT (verified via `License :: OSI Approved :: MIT License` classifier and `LICENSE.md` shipped with the wheel)
- Pretrained weights: VGGFace2 / CASIA-WebFace, distributed by timesler/facenet-pytorch under Apache License 2.0
- Used by: `src/probos/perception/identity.py` (`IdentityResolver` — MTCNN face detection + InceptionResnetV1 face embedding)
- Installed via `pyproject.toml` `[project.dependencies]`: `facenet-pytorch>=2.5`.
- Privacy posture: only a 512-float embedding is persisted at `data/captain_identity.json`. Reference photo bytes are discarded after enrollment. File is gitignored.


## Silero VAD (AD-733c-7)

- Project: <https://github.com/snakers4/silero-vad>
- Authors: Silero Team (snakers4)
- License: MIT (https://github.com/snakers4/silero-vad/blob/master/LICENSE)
- Used by: `ui/src/audio/voiceActivity.ts` (lazy-loaded via existing `onnxruntime-web` resident dependency)
- Installation: operator-pullable via `./scripts/silero-vad-fetch.ps1`. Model bytes are NOT bundled in the repo (gitignored under `data/silero-vad/` via the existing `data/*` rule).
- Privacy posture: audio bytes never leave the browser. Only a boolean speech-detected event POSTs to `/api/perception/voice-activity`.
