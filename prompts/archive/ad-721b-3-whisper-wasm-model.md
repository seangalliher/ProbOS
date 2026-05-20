# AD-721b-3 — whisper.cpp WASM tiny.en model bundle for offline phoneme alignment

**Issue:** [#561](https://github.com/seangalliher/ProbOS/issues/561)
**Status:** GATE 1 — drafting (Wave 179).
**Depends on:** none (foundation prompt).
**Consumed by:** AD-705a (offline STT) — Wave 179 build group 2.
**Estimated tests:** +6 pytest, +3 vitest.

---

## Problem

ProbOS has no Whisper integration today. AD-705 v1 (Wave 137) shipped the wake-word voice loop using browser-native `SpeechRecognition`, which on Chrome is cloud-routed to Google. The Captain wants offline STT AND offline phoneme alignment for lip-sync (AD-721b family).

The pre-condition for both consumers is a Whisper model file + a deterministic loader. AD-721b-3 ships **only that foundation** — the operator-pull script, the gitignore rule, the documented file path, a Python-side loader stub used by AD-705c training (negative-sample augmentation), and the browser-side loader factory consumed by AD-705a.

No STT functionality is exposed in this AD. AD-721b-3 is the artifact bundle + plumbing; AD-705a wires it to the conversational surface.

## Solution

Five-part deliverable:

1. **Operator-pull PowerShell script** `scripts/whisper-tiny-en-fetch.ps1` mirrors `scripts/silero-vad-fetch.ps1` shape (param `-Force`, `-DestDir` default `data/whisper`, fetch from a Hugging Face mirror of `ggml-tiny.en.bin`, pinned version, license note).
2. **Gitignore.** Existing `data/*` rule already covers `data/whisper/`. Verify with a regression-style note in the script header. No diff on `.gitignore`.
3. **Browser-side loader** `ui/src/audio/whisperLoader.ts` (~120 lines): lazy `<script>`-tag injection of the whisper.cpp WASM glue (operator-pulled to `data/whisper/whisper.js` + `data/whisper/whisper.wasm`), a `loadWhisperModel(): Promise<WhisperHandle | null>` factory that honest-degrades to `null` when (a) the glue script 404s, (b) the wasm 404s, or (c) the model `.bin` 404s. Exposes a single `transcribeBuffer(buffer: Float32Array, sampleRate: number): Promise<string>` method on the handle. **No UI changes in this AD** — `whisperLoader.ts` is a pure library module, only consumed by AD-705a's `whisperStt.ts`.
4. **Python-side path resolver** `src/probos/voice/whisper_model.py` (new module): single function `resolve_whisper_model_path(config: SystemConfig) -> Path | None` that reads `cognitive.whisper_model_path` (new field), resolves it against `runtime.data_dir`, and returns `None` if the file is absent. Used by AD-705c's training augmentation step (negative-sample synthesis from voice clips); never imported by the runtime hot path.
5. **Config knob** `CognitiveConfig.whisper_model_path: str = "whisper/ggml-tiny.en.bin"` (new field; default points at the operator-pulled location relative to `data_dir`). Restart-required per BF-308 (loader needs warm state). New `FieldDescriptor` in the LLM Tiers section of the AD-741 settings registry (low-priority — operators rarely tune this).

### Static-asset serving

The browser fetches `whisper.js` / `whisper.wasm` / `ggml-tiny.en.bin` from the same `/data/...` static-file route AD-733c-7 already exercises for `/data/silero-vad/silero_vad.onnx`. Confirm via pre-flight grep (see anchors below).

## Scope

- `scripts/whisper-tiny-en-fetch.ps1` (new, ~50 lines).
- `ui/src/audio/whisperLoader.ts` (new).
- `ui/src/audio/__tests__/whisperLoader.test.ts` (new, +3 vitest).
- `src/probos/voice/__init__.py` (new module package).
- `src/probos/voice/whisper_model.py` (new, ~40 lines).
- `tests/test_ad721b_3_whisper_model_resolver.py` (new, +6 pytest).
- `src/probos/config.py` — add `whisper_model_path` field to `CognitiveConfig`.
- `src/probos/settings/section_registry.py` — add one `FieldDescriptor` for `cognitive.whisper_model_path` (low-priority position).

## NOT in scope

- STT functionality (AD-705a).
- Wake-word training (AD-705c).
- Bundling the model bytes in the repo (license posture: model files are operator-pulled; bytes never committed).
- Phoneme alignment hookup to `LipSyncTrack` (forward marker — separate prompt at AD-721b-3-1 once AD-705a proves the loader).
- Multi-model selection (tiny / base / small). v1 = tiny.en only.
- HXI surface changes. No new badges, no settings UI work beyond the one FieldDescriptor (which the AD-741 framework renders for free).

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `scripts/silero-vad-fetch.ps1:1-40` — mirror this shape exactly. `param([switch]$Force, [string]$DestDir = "...")`, pinned URL, `$ErrorActionPreference = "Stop"`, `Invoke-WebRequest -Uri ... -OutFile $Target -UseBasicParsing`, post-fetch size echo + license line.
2. `.gitignore:25` — confirm `data/*` rule covers `data/whisper/` without needing a new line. (It does — same as `data/silero-vad/`.)
3. `ui/src/audio/silero-vad.ts:31-60` — lazy-loader pattern reference. Whisper diverges: the WASM glue is shipped via `<script>` tag injection (whisper.cpp's WASM build emits `whisper.js` as a UMD-style module that registers a global `Module` factory), NOT via `await import()`. Builder fetches the glue via `fetch('/data/whisper/whisper.js')`, evaluates as a `<script>` element, and reads the resulting global. **Verify by reading whisper.cpp's `examples/whisper.wasm/main.js` upstream pattern; do NOT mimic ESM dynamic-import pattern from silero-vad.ts because the artifact ships as UMD.**
4. `src/probos/config.py` — locate `CognitiveConfig` (search for `class CognitiveConfig`). Add `whisper_model_path: str = "whisper/ggml-tiny.en.bin"` after the existing `llm_*_vision_fast` fields per AD-742a precedent.
5. `src/probos/settings/section_registry.py` — find the LLM Tiers section (search for `section_id="llm_tiers"` or equivalent). Add a `FieldDescriptor` with `path="cognitive.whisper_model_path"`, `label="Whisper model path"`, `kind="text"`, `requires_restart=True`, `help="Path to ggml-tiny.en.bin under data_dir. Operator-pull via scripts/whisper-tiny-en-fetch.ps1."`.
6. `src/probos/__main__.py` (or wherever `runtime.data_dir` is set) — confirm `runtime.data_dir` is a public attribute. Used by `resolve_whisper_model_path` to anchor the relative path.
7. `data/silero-vad/` is gitignored under the broader `data/*` rule; the README at `ui/public/models/vad/README.md` documents the operator-install seam. **Builder mirrors this for whisper.** New file `ui/public/models/whisper/README.md` documents the install path (mirror `ui/public/models/vad/README.md` exactly: license, source URL, install command, fallback behavior).
8. `THIRD_PARTY_LICENSES.md` — **NO diff in this AD.** AD-721b-3 is the bundle + plumbing only. The license entries land when AD-705a ships (the consumer of the model file).

## Engineering-principles audit

- **SOLID — DIP.** `resolve_whisper_model_path` depends on `SystemConfig` (abstraction) not on the file system directly. The function returns `Path | None`; consumers decide what to do with absence.
- **Defaults preserve current behavior.** Field defaults to a path that does NOT exist by default (no operator pull yet); `resolve_whisper_model_path` returns `None`; consumers honest-degrade. ProbOS boots identically to today.
- **License posture.** Zero bytes in the repo. Operator-pull script lands; THIRD_PARTY_LICENSES diff = 0 until AD-705a actually uses the artifact.
- **Hot-reload (BF-308).** `whisper_model_path` is restart-required (loader needs warm state). FieldDescriptor sets `requires_restart=True`.
- **HXI Principle #3 (no emoji).** N/A — no UI surface in this AD.
- **HXI Principle #5 (progressive disclosure).** N/A — no UI surface in this AD. (The settings field is hidden under the LLM Tiers section that operators only visit when configuring tiers.)
- **AD-731 invariant.** N/A — Whisper model bytes are operator-pulled to local disk, not carried in `IntentMessage.params`.
- **AD-738b UI gate.** `npx vitest run` + `npm run build` clean.
- **BF-274 single-replace discipline.** Tracker file edits use single `replace_string_in_file` per adjacent block.
- **BF-287 (MagicMock at substrate boundary).** Python tests use real `SystemConfig()` + real `tmp_path` for data dir. Vitest stubs `fetch` (network boundary) and the `<script>` injection (DOM boundary).

## Test plan

### pytest (+6 in `tests/test_ad721b_3_whisper_model_resolver.py`)

1. `test_resolver_default_path_relative_to_data_dir` — real `SystemConfig()`, monkey-patch `runtime.data_dir = tmp_path`, assert resolved path = `tmp_path / "whisper" / "ggml-tiny.en.bin"`.
2. `test_resolver_returns_none_when_file_absent` — same setup, file does not exist, assert returns `None`.
3. `test_resolver_returns_path_when_file_present` — touch the file, assert returns the path AND `.exists()` is True.
4. `test_resolver_absolute_path_passes_through` — set `cognitive.whisper_model_path = str(tmp_path / "custom" / "model.bin")`, touch the file, assert returns the absolute path unchanged.
5. `test_config_field_default_value` — assert `SystemConfig().cognitive.whisper_model_path == "whisper/ggml-tiny.en.bin"`.
6. `test_field_descriptor_registered_in_section_registry` — import `LLM_TIERS_SECTION` (or whatever name the AD-741 registry uses), find the descriptor with `path == "cognitive.whisper_model_path"`, assert `requires_restart is True`.

### vitest (+3 in `ui/src/audio/__tests__/whisperLoader.test.ts`)

1. `loadWhisperModel returns null when glue script 404s` — stub `fetch('/data/whisper/whisper.js')` to return `{ok: false, status: 404}`, assert `loadWhisperModel()` resolves `null` (NOT throws).
2. `loadWhisperModel returns null when model bin 404s` — glue OK, wasm OK, `fetch('/data/whisper/ggml-tiny.en.bin')` returns 404; assert null.
3. `loadWhisperModel returns a handle with transcribeBuffer when all artifacts load` — stub all three fetches to return valid bytes (small fake ArrayBuffer); stub the `Module` factory the glue would register; assert returned handle has `typeof handle.transcribeBuffer === 'function'`.

## Tracker updates (at ship time, NOT now)

- `PROGRESS.md` — flip AD-721b-3 line to **SHIPPED** under Wave 179 in-flight block.
- `docs/development/roadmap.md` — update line 368 (the AD-721b-3 row) to mark **SHIPPED Wave 179**.
- `DECISIONS.md` — append at build time.
- `THIRD_PARTY_LICENSES.md` — 0-line diff in this AD; entries land at AD-705a ship.

## Acceptance criteria

1. `scripts/whisper-tiny-en-fetch.ps1` exists; downloads `ggml-tiny.en.bin` from the pinned upstream URL into `data/whisper/`; idempotent (`-Force` to re-download); echoes size + MIT license note.
2. `ui/public/models/whisper/README.md` exists; mirrors `ui/public/models/vad/README.md` shape.
3. `ui/src/audio/whisperLoader.ts` exists; lazy-injects `data/whisper/whisper.js`, fetches `whisper.wasm` and `ggml-tiny.en.bin`, returns `null` on any 404; exposes `WhisperHandle` with `transcribeBuffer(buffer, sampleRate): Promise<string>`. No static imports of any whisper-related symbol.
4. `src/probos/voice/whisper_model.py` exposes `resolve_whisper_model_path(config) -> Path | None`.
5. `CognitiveConfig.whisper_model_path` field added with default `"whisper/ggml-tiny.en.bin"`.
6. New `FieldDescriptor` registered in the AD-741 LLM Tiers section.
7. All 6 new pytest pass; all 3 new vitest pass.
8. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` exits 0; `cd ui && npx vitest run` exits 0; `cd ui && npm run build` exits 0.
9. **Zero diff** on `THIRD_PARTY_LICENSES.md`, `LICENSE`, `pyproject.toml`, `package.json`, `package-lock.json`, `.gitignore`.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-19)

```
ui/src/audio/silero-vad.ts:31-60         (lazy-loader reference pattern)
ui/src/audio/silero-vad.ts:43             const MODEL_URL = '/data/silero-vad/silero_vad.onnx';
ui/public/models/vad/README.md:1-25       (README shape reference)
scripts/silero-vad-fetch.ps1:1-39         (PowerShell shape reference)
.gitignore:25                              data/*
src/probos/config.py: CognitiveConfig     (verified class exists; vision_fast fields land after vision)
src/probos/settings/section_registry.py   (AD-741 registry exists; LLM Tiers section is canonical)
THIRD_PARTY_LICENSES.md: Silero VAD       (entry pattern reference at file tail)
```
