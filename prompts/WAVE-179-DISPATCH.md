# Wave 179 — Builder Dispatch (voice stack completion)

**Status:** GATE 1 — drafted (architect-only). **Builder dispatch deferred** pending Captain GATE 1 review.
**Closes:** #555 (AD-705a), #557 (AD-705c), #561 (AD-721b-3).
**Starting SHA (at draft):** `3c9fd27b` (Wave 178 close).
**Estimated:** ~16 h across three serial sub-commits, +23 pytest, +15 vitest.

## Build slate (STRICT serial order — each AD's contract is the next AD's pre-flight anchor)

| Order | AD | Issue | Prompt | Tests | Surface |
|-------|----|-------|--------|-------|---------|
| 1 | **AD-721b-3** | #561 | `prompts/ad-721b-3-whisper-wasm-model.md` | +6 pytest +3 vitest | Foundation — whisper.cpp WASM artifact + loader factory + model path resolver. NO STT yet. |
| 2 | **AD-705a** | #555 | `prompts/ad-705a-offline-stt-whisper-wasm.md` | +5 pytest +8 vitest | Offline STT consumer — `whisperStt.ts` reads VAD-bounded utterance, posts transcript through existing `agent_chat`. |
| 3 | **AD-705c** | #557 | `prompts/ad-705c-custom-wake-word-training.md` | +12 pytest +4 vitest | Independent — custom wake-word ONNX training via openWakeWord; `wakeWord.ts` loader prefers `captain.onnx`. |

**Build order rationale.**
- AD-721b-3 → AD-705a is a hard dependency (AD-705a's `whisperStt.ts` consumes `whisperLoader.loadWhisperModel()`).
- AD-705c is independent (operates on the wake-word ONNX loader, not the STT path). It's ordered third so the wave's audio surfaces stabilize first and the wake-word loader change ships last.

## Prior-art research

`prompts/RESEARCH-wave-179.md` — 16 projects surveyed across the Whisper, wake-word, and phoneme-alignment families. License-aware absorption matrix; 8 architectural decisions documented; v1 vs forward-marker matrix.

## Captain GATE 1 decisions surfaced (NOT auto-resolved by architect)

1. **Whisper model size confirmation.** Captain approved tiny.en (~75 MB). Confirm ~85-90% WER on clean English dictation is acceptable for v1. Larger models = forward-marker territory.
2. **Trainer UX emphasis.** v1 ships both CLI (`probos wake-word collect / train / test / status`) and browser sample-recorder. Documentation emphasis preference: CLI-first or browser-first?
3. **Sample retention default.** `retain_training_samples=False` default (delete after train). Override to `True` only if Captain wants the option of retraining later.
4. **Custom model filename.** Default `captain.onnx`. Multi-Captain deferred to forward marker `AD-705c-4`.
5. **`SpeechRecognition` fallback co-existence.** v1: offline STT and Chrome `SpeechRecognition` can both be enabled simultaneously. Forward marker `AD-705c-7` for "fully-offline mode" that disables `SpeechRecognition` when `offline_stt_enabled=true`. Captain preference for v1 default?

## Pre-flight (Builder runs before each prompt)

```
cd D:\ProbOS
git pull --ff-only
git status --short    # must be empty
git rev-parse HEAD    # confirm wave-179 base SHA
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
# Expect green baseline; record pre-wave count.
```

## Per-prompt build workflow

For each AD in strict order:

1. Read the prompt file fully.
2. Run the Pre-flight grep anchors block; verify EVERY anchor against HEAD.
3. Implement in the order the prompt sections appear.
4. After each logical sub-step, run the focused test gate:
   ```
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad<NNN>_<slug>.py -q -n 0
   cd ui && npx vitest run --reporter=basic   # if UI touched
   ```
5. Before commit, run the full parallel gate:
   ```
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
   cd ui && npx vitest run
   cd ui && npm run build      # AD-738b UI gate — REQUIRED for any UI-touching commit
   ```
6. One commit per AD. Single `git push`. THEN proceed to the next AD.

## Hard-stop conditions

- Any pre-flight grep anchor fails (the live codebase doesn't match the prompt's assumed shape). STOP — surface to architect.
- The whisper.cpp WASM artifact shape diverges from the assumed UMD-glue + WASM-binary + model-bin shape (Builder verifies via the upstream `examples/whisper.wasm/main.js`).
- Any test in the full parallel gate is failing PRE-wave. STOP — surface to architect; do NOT proceed on a yellow baseline.
- A new pip / npm dep would be required. **Zero new deps in this wave.** STOP — surface.
- Any `replace_string_in_file` would need to span more than one adjacent block. BF-274 single-replace discipline: split into multiple single-block edits.

## Anti-patterns the prompts already gate against (re-stated for Builder vigilance)

1. **Static import of `onnxruntime-web` or the Whisper glue.** Both must lazy-load via indirect-string-variable pattern. First-paint MUST NOT regress.
2. **Audio bytes in any fetch body.** Privacy invariant. Regression tests assert this for STT (AD-705a) and the wake-word training path (AD-705c — only multipart upload, no JSON body with audio).
3. **`asyncio.create_subprocess_exec` anywhere.** BF-280: Windows SelectorEventLoop incompatibility. Training runs in `loop.run_in_executor` (sync openWakeWord trainer).
4. **Fire-and-forget tasks without held reference.** AD-705c training task must be held in `runtime._wake_word_trainer_tasks: set[asyncio.Task]`.
5. **`hasattr` / `getattr` defensive guards** for APIs defined in the same prompt. Use the public method directly.
6. **Hardcoded model paths in `wakeWord.ts`.** Read `customModelFilename` from settings snapshot.
7. **Bare `try/except Exception` around imports.** BF-274 lesson: catch `ImportError` specifically; re-raise everything else.

## Post-wave close (architect, after Builder ships all three)

1. Verify the full parallel gate is green.
2. Append to `DECISIONS.md`:
   - AD-721b-3 entry (whisper.cpp WASM tiny.en foundation).
   - AD-705a entry (offline STT via whisper.cpp; 2 license entries added).
   - AD-705c entry (custom wake-word training via openWakeWord; 1 license entry added).
3. Move the three prompt files to `prompts/archive/`.
4. Update `prompts/wave-plan.yaml`: flip Wave 179 status `drafting → shipped`; update `prompt_paths` to point at the archive locations.
5. Close GH issues #555, #557, #561.
6. Update `PROGRESS.md` — flip Wave 179 block from "in flight" to the historical record.
7. Update `docs/development/roadmap.md` — flip the three Wave-179 rows to `**SHIPPED Wave 179** (...)` format.
8. File forward-marker GH issues per AD-722c-3 TECHNICAL trigger format for any forward markers that have a concrete demand trigger documented.

## Reference

- Wave 178 dispatch: `prompts/archive/WAVE-178-DISPATCH.md` (shape reference).
- BUILDER-EXECUTION-PLAN: `prompts/BUILDER-EXECUTION-PLAN.md` (standing rules).
- Engineering principles: `.github/copilot-instructions.md`.
