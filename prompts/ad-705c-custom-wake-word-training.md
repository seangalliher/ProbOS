# AD-705c — Custom wake-word model training pipeline

**Issue:** [#557](https://github.com/seangalliher/ProbOS/issues/557)
**Status:** GATE 1 — drafting (Wave 179).
**Depends on:** AD-705 v1 (existing `wakeWord.ts` openWakeWord loader + `ui/public/models/wake-word/` operator-install seam).
**Consumed by:** none (top of the chain).
**Estimated tests:** +12 pytest, +4 vitest.

---

## Problem

AD-705 v1 (Wave 137) ships with operator-installed openWakeWord **stock community** models (`hey_jarvis_v0.1.onnx` or similar) under `ui/public/models/wake-word/`. The browser's user-visible wake phrase is "Computer" (per `STATIC_WAKE_PHRASES` in `wakeWord.router.ts`), but the underlying detector recognizes whatever the stock model was trained on.

Captain's accuracy expectations don't match stock-model output in real-world use:
- Stock model trigger rate has documented FAR (false-accept rate) issues in noisy environments.
- The visible wake phrase ("Computer") is decoupled from the detector's actual trained phrase.
- No way to fingerprint the Captain's voice — anyone in the room can fire the wake.

AD-705c lands a training pipeline that produces a Captain-specific wake-word ONNX, which the existing `wakeWord.ts` loader prefers over the stock model.

> **Clarification.** Captain's dispatch brief mentions "AD-733c-3's existing Picovoice path." Verification (2026-05-19, see grep anchors below) shows the codebase uses **openWakeWord**, not Picovoice. AD-705c builds on the actual openWakeWord pipeline. This is a labeling clarification; not a blocker.

## Solution

Server-side training pipeline (Python, operator-invoked) + browser-side sample-recording UX + an updated `wakeWord.ts` loader that prefers the custom ONNX.

### 1. CLI command: `probos wake-word`

New `src/probos/experience/commands/commands_wake_word.py` registers a slash-command branch + a Click subcommand:

- `probos wake-word collect` — interactive: prompts operator to record N positive utterances ("Say 'Computer' — utterance 1 of 50"); writes WAVs under `data/wake-word/training-samples/positive/<timestamp>.wav`. Optional `--samples 50` (default), `--phrase "Computer"`.
- `probos wake-word train --label "Computer" [--epochs 100] [--output captain.onnx]` — runs the openWakeWord training pipeline; writes ONNX to `ui/public/models/wake-word/captain.onnx`; emits a build report to `data/wake-word/training-reports/<timestamp>.json` (epochs, loss curve, validation accuracy, FAR/FRR estimates).
- `probos wake-word test [--positive-samples-dir ...] [--negative-samples-dir ...]` — validates the trained model against held-out data; emits accuracy metrics.
- `probos wake-word status` — reports whether `captain.onnx` exists, training-sample counts, last train timestamp.

All four are honest-degrade: if `openwakeword` is not installed, the command exits with a clear "operator pip install openwakeword[training]" instruction. No hard dep on `openwakeword` in `pyproject.toml`.

### 2. Training service module

New `src/probos/voice/wake_word_trainer.py` (~250 lines). Exposes:

```python
class WakeWordTrainer:
    def __init__(self, config: SystemConfig, data_dir: Path): ...
    async def train(
        self,
        label: str,
        positive_samples_dir: Path,
        negative_samples_dir: Path | None,  # synthesized if None
        epochs: int = 100,
        output_path: Path | None = None,
    ) -> WakeWordTrainingReport: ...
    async def test(self, model_path: Path, samples_dir: Path) -> WakeWordTestReport: ...
```

`train()` runs the openWakeWord training pipeline in a `loop.run_in_executor` (the openWakeWord trainer is sync PyTorch — must NOT block the event loop; mirrors BF-280 pattern). When `negative_samples_dir` is `None`, the trainer synthesizes negatives from a curated common-voice subset (operator-pullable via a new `scripts/wake-word-negatives-fetch.ps1` — but v1 ships **without** this script; operators provide their own negatives OR train on positives-only using openWakeWord's default negative synthesis). Forward marker `AD-705c-1` for the negatives-fetch script + Mozilla Common Voice CC0 attribution.

### 3. Browser sample recorder (opt-in HXI surface)

New `ui/src/components/wakeword/WakeWordTrainerPanel.tsx` rendered inside the AD-741 Settings → Voice section. Components:

- "Train custom wake word" button — opens an inline guided recorder.
- Recording state machine: idle → countdown (3-2-1) → recording (4s ceiling, VAD-bounded via the AD-733c-7 `voiceActivity.ts` stream) → uploaded → next-sample.
- Progress: "12 / 50 samples collected." Recommended count = 50 (configurable, but documented baseline matches openWakeWord training-data minimums).
- Upload: per-utterance multipart POST to new `POST /api/voice/wake-word/sample` (require_crew_scope) with `phrase` form field.
- After 50: a "Train now" button that POSTs to `POST /api/voice/wake-word/train` (require_crew_scope) which spawns a background `asyncio.create_task` (held in a runtime-owned set per the async-discipline rule) running `WakeWordTrainer.train()`. UI polls `GET /api/voice/wake-word/training-status` every 5s for progress.
- On train complete: download success indicator; offer "Test" button that runs `POST /api/voice/wake-word/test`; offer "Activate" button that copies the trained ONNX into the loader path (`ui/public/models/wake-word/captain.onnx`) and triggers a `window.location.reload()` so `wakeWord.ts` picks up the new model on next page load.

### 4. Loader path update

Modify `ui/src/audio/wakeWord.ts` `_loadOnnxRuntime()` (the stub-returning-false placeholder per AD-705 v1) to:

1. Try `fetch('/models/wake-word/' + customModelFilename)` first (configured via `WakeWordConfig.custom_model_filename` default `"captain.onnx"`).
2. Fall back to the stock model fetch path on 404.
3. Fall back to substring match on any failure (existing behavior).

This is the **only** functional change to `wakeWord.ts` — the rest of the file (state machine, transcript pump, fallback toast) is untouched.

### 5. API endpoints

New `src/probos/routers/voice.py` (or add to existing `routers/perception.py` if voice routing already lives there; verify pre-flight). Three endpoints under `require_crew_scope`:

- `POST /api/voice/wake-word/sample` (multipart) — accepts a single WAV per call; writes to `data/wake-word/training-samples/positive/<sha>.wav`; honest-degrade 503 when `wake_word_trainer_enabled=False`; 413 when audio > 1 MB; 400 when not WAV magic bytes; returns `{stored: true, samples_count: N}`.
- `POST /api/voice/wake-word/train` (JSON `{label?, epochs?}`) — spawns the background training task; returns `{job_id, status: "started"}`. Holds the task reference in a runtime-owned set.
- `GET /api/voice/wake-word/training-status?job_id=...` — returns `{status: "running"|"complete"|"failed", progress: 0..1, error?: str, model_path?: str}`.

### 6. Config

New `WakeWordConfig` Pydantic block (was bypassed in AD-705 v1 — the existing `wakeWord.ts` reads no config). Fields:

- `wake_word_trainer_enabled: bool = False` (default OFF — convention #14; opt-in).
- `custom_model_filename: str = "captain.onnx"`.
- `retain_training_samples: bool = False` (default: delete after train).
- `training_samples_max_count: int = 200` (cap to prevent unbounded disk use).
- `training_audio_max_bytes: int = 1_048_576` (1 MB per sample).

Three new `FieldDescriptor`s in the Voice section of the AD-741 registry.

### 7. Gitignore

Existing `data/*` rule already covers `data/wake-word/`. Verify (no diff expected).

## Scope

- New `src/probos/voice/wake_word_trainer.py` (~250 lines).
- New `src/probos/experience/commands/commands_wake_word.py` (~150 lines).
- New `src/probos/routers/voice.py` if no existing voice router (else extend; verify).
- Modify `src/probos/__main__.py` — register the `wake-word` Click subcommand + the slash-command.
- Modify `src/probos/config.py` — add `WakeWordConfig`.
- Modify `src/probos/settings/section_registry.py` — add 3 `FieldDescriptor`s in Voice section.
- New `ui/src/components/wakeword/WakeWordTrainerPanel.tsx`.
- Modify `ui/src/audio/wakeWord.ts` — `_loadOnnxRuntime` prefers `customModelFilename`. SINGLE block edit (BF-274).
- Modify `ui/public/models/wake-word/README.md` — document the custom-model path + the `probos wake-word` CLI.
- Modify `THIRD_PARTY_LICENSES.md` — +1 entry for openWakeWord (Apache 2.0).
- New `tests/test_ad705c_wake_word_trainer.py` (+6 pytest).
- New `tests/test_ad705c_wake_word_api.py` (+6 pytest).
- New `ui/src/components/wakeword/__tests__/WakeWordTrainerPanel.test.tsx` (+4 vitest).

## NOT in scope

- A hard dependency on `openwakeword` in `pyproject.toml`. v1 ships the trainer code; operator runs `pip install openwakeword[training]` separately. The CLI honest-degrades when the package is absent.
- Multi-Captain wake words. v1 = single `captain.onnx`. Forward marker `AD-705c-4`.
- Few-shot training (3-5 samples). Forward marker `AD-705c-3` (EfficientWord-Net).
- Transfer learning. Forward marker `AD-705c-2` (Howl).
- Training on federated samples or telemetry data. Privacy invariant — training audio is local-only.
- A new wake-word at runtime (without retraining). The visible phrase change is a separate AD (operator edits `STATIC_WAKE_PHRASES`).
- Replacing the stock-model fallback. Stock community model stays as Tier-2 path.
- Negative-sample synthesis CDN fetch. Forward marker `AD-705c-1`.

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `ui/src/audio/wakeWord.ts:261-289` — `_loadOnnxRuntime` returns `false` placeholder. **Builder modifies this function only — SINGLE block edit. Do NOT replace the indirect-string-import pattern; it's a load-bearing first-paint guarantee.**
2. `ui/public/models/wake-word/README.md` — existing README. Append `probos wake-word` CLI documentation.
3. `src/probos/__main__.py` — locate the Click command group (search for `@click.group` or `app.command`). Add `wake-word` as a subcommand alongside existing `serve` / `dump` etc.
4. `src/probos/experience/commands/` — directory of existing slash-commands (`commands_llm.py` exists per grep on Wave 168). Mirror the file structure.
5. `src/probos/routers/perception.py` — confirm there's no existing voice router; if one exists, extend it instead of creating `routers/voice.py`. Builder verifies.
6. `src/probos/config.py` — locate the existing config classes. `WakeWordConfig` goes near `PerceptionConfig` or `AvatarsConfig` (voice-adjacent).
7. `src/probos/settings/section_registry.py` — Voice section (or whatever owns TTS + audio per AD-741). Add three descriptors there.
8. `THIRD_PARTY_LICENSES.md` (tail) — append openWakeWord Apache 2.0 entry, mirror the existing Silero VAD entry shape.
9. `ui/src/store/useSettingsStore.ts` — Confirm the snapshot path that reads `wake_word_trainer_enabled` so the panel renders conditionally.
10. `src/probos/runtime.py` — confirm the existing `data_dir` attribute. Used by `WakeWordTrainer` for `training-samples/` and `training-reports/` paths.

## Engineering-principles audit

- **SOLID — DIP.** `WakeWordTrainer` accepts `SystemConfig` + `data_dir` via constructor; no global imports.
- **SOLID — SRP.** Trainer = training only. Sample collection = HXI panel + API endpoint. Loader hot-swap = `wakeWord.ts`. Three responsibilities, three modules.
- **Defaults preserve current behavior.** `wake_word_trainer_enabled=False` default. Existing AD-705 v1 wake-word path runs unchanged.
- **Privacy posture.** Training audio NEVER leaves the local runtime. Samples in `data/wake-word/training-samples/` (gitignored). Default retention: delete after train. Regression test: no telemetry / federation hook on the wake-word audio path.
- **License posture.** +1 entry in THIRD_PARTY_LICENSES.md for openWakeWord (Apache 2.0). **No `openwakeword` in `pyproject.toml`** — operator-installed separately. 0-line diff on `pyproject.toml`, `package.json`, `package-lock.json`, `LICENSE`.
- **Hot-reload (BF-308).** `wake_word_trainer_enabled` hot-reload (UI panel render). `custom_model_filename` restart-required (next page load reads it). Other fields hot-reload.
- **Async discipline.** Training task = `asyncio.create_task(...)`; reference held in `runtime._wake_word_trainer_tasks: set[asyncio.Task]`; removed on completion. Cancellation handled; cleanup re-raises `CancelledError`. PyTorch training itself runs in `loop.run_in_executor(None, _sync_train)` (BF-280 pattern — must NOT use `asyncio.create_subprocess_exec`).
- **HXI Principle #3 (no emoji).** Trainer panel uses inline stroke SVG glyphs only (recording dot = stroke circle, success check = stroke checkmark). Amber active, dim idle.
- **HXI Principle #5 (progressive disclosure).** Panel hidden when `wake_word_trainer_enabled=false`. Progress states show only relevant controls (recording → upload-progress → train-now → training-progress → activate).
- **HXI Principle #11 (agentic-first).** Training is workstation-tier — the operator IS doing the work directly. Not an anti-pattern; this is the rare case where the human is the data source. Forward marker `AD-705c-5` for "Counselor suggests retraining when FAR spikes" agentic surfacing.
- **AD-738b UI gate.** `cd ui && npx vitest run` + `cd ui && npm run build`.
- **BF-274 single-replace discipline.** Multiple edits to `wakeWord.ts` / `__main__.py` / `config.py` use single `replace_string_in_file` per adjacent block.
- **BF-287 (MagicMock at substrate boundary).** Python tests use real `SystemConfig()` + real `tmp_path` for `data_dir`. Tests of the trainer mock the `openwakeword` import (not installed in CI) and assert the honest-degrade path. Vitest stubs `fetch` (network boundary) and the recorder stream (DOM boundary).
- **AD-541b memory integrity.** Successful training event writes an episode (`importance=6`, `channel="voice"`, `trigger_type="wake_word_trained"`). NOT a regression — same anchor pattern as AD-733c-7 voice-activity entries.

## Test plan

### pytest (+12 across two files)

`tests/test_ad705c_wake_word_trainer.py` (+6):
1. `train_returns_report_when_openwakeword_installed` — patch `import openwakeword.train` to a stub that emits a fake `model.onnx`; assert report fields populated.
2. `train_honest_degrades_when_openwakeword_missing` — patch the import to raise `ImportError`; assert `train()` returns a report with `status="error"` AND `error_message` mentions `pip install openwakeword`; assert no exception propagates.
3. `train_writes_onnx_to_output_path` — happy path; assert file exists at requested path after train.
4. `test_returns_metrics_for_held_out_samples` — happy path on `test()`.
5. `delete_samples_after_train_when_retain_false` — `retain_training_samples=False`; assert `data/wake-word/training-samples/positive/` is empty after `train()` returns.
6. `keep_samples_when_retain_true` — `retain_training_samples=True`; assert samples preserved.

`tests/test_ad705c_wake_word_api.py` (+6):
1. `post_sample_writes_wav_to_disk` — multipart with WAV magic bytes; assert file lands under `data/wake-word/training-samples/positive/`.
2. `post_sample_503_when_trainer_disabled` — `wake_word_trainer_enabled=False`; assert 503.
3. `post_sample_413_when_oversize` — payload > `training_audio_max_bytes`; assert 413.
4. `post_sample_400_when_not_wav` — non-WAV bytes; assert 400.
5. `post_train_spawns_background_task` — POST returns `{job_id, status: "started"}`; assert task is in `runtime._wake_word_trainer_tasks` set.
6. `get_training_status_returns_progress` — happy path; assert progress 0..1.

### vitest (+4 in `ui/src/components/wakeword/__tests__/WakeWordTrainerPanel.test.tsx`)

1. `panel renders when wake_word_trainer_enabled=true`.
2. `panel hidden when wake_word_trainer_enabled=false` — progressive disclosure.
3. `clicking record arms the mic stream and uploads on stop` — assert one `POST /api/voice/wake-word/sample` per recorded utterance.
4. `train button posts to /train and polls /training-status until complete` — full state machine round-trip.

## Tracker updates (at ship time, NOT now)

- `PROGRESS.md` — flip AD-705c line to **SHIPPED** under Wave 179 in-flight block.
- `docs/development/roadmap.md` — flip the AD-705c row (added Wave 179) to **SHIPPED Wave 179**.
- `DECISIONS.md` — append at build time.
- `THIRD_PARTY_LICENSES.md` — +1 entry (openWakeWord Apache 2.0).

## Acceptance criteria

1. `probos wake-word collect / train / test / status` CLI subcommands exist; all four honest-degrade when `openwakeword` is not installed.
2. `WakeWordTrainer.train()` runs the openWakeWord pipeline in a thread executor (BF-280); honest-degrades on missing import.
3. Three API endpoints exist under `require_crew_scope`; all four config-gates honored (enabled, max_count, max_bytes, retain).
4. `WakeWordTrainerPanel.tsx` renders the full guided recorder UX; uploads per-utterance; polls training status; offers Activate at completion.
5. `wakeWord.ts:_loadOnnxRuntime` prefers `captain.onnx` over the stock model; falls back gracefully.
6. `WakeWordConfig` Pydantic block added with five fields; three FieldDescriptors registered.
7. `THIRD_PARTY_LICENSES.md` +1 openWakeWord entry.
8. Privacy regression: training audio never leaves the runtime (no telemetry, no federation hook on the wake-word path).
9. All 12 new pytest + 4 new vitest pass.
10. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` exits 0; `cd ui && npx vitest run` exits 0; `cd ui && npm run build` exits 0.
11. **Zero diff** on `pyproject.toml`, `package.json`, `package-lock.json`, `LICENSE`.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-19)

```
ui/src/audio/wakeWord.ts:261-289          _loadOnnxRuntime() returns false placeholder
ui/public/models/wake-word/README.md      openWakeWord operator-install seam
ui/public/models/wake-word/LICENSE-openwakeword.txt   Apache 2.0
src/probos/__main__.py                     Click command group entry point
src/probos/experience/commands/            commands_llm.py + sibling slash-command modules
src/probos/routers/perception.py           reference router shape; verify no existing voice router
src/probos/config.py                       config class layout
src/probos/settings/section_registry.py    AD-741 registry with Voice section
THIRD_PARTY_LICENSES.md (tail)             Silero VAD entry as shape reference
src/probos/runtime.py                      data_dir attribute (used for training-samples path)
```
