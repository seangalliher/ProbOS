# AD-738g S3a (#1662): lip-sync timed by the synthesizer, from the kokoro-onnx export that reports durations

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-28
**Amended:** same author, 2026-11-28, after the Diff Reviewer's round 1 (findings 1 to 5); no design change. The rollback restores the previous values instead of deleting the lines. The timing check refuses `RecursionError` and `OverflowError` input. A comment and the D2 status are corrected. W12 checks its own premise. `test_t9` and two `test_x1` cases are new; mutation rows S21 and S22 are new.
**Amended:** same author, 2026-11-28, for two orchestrator decisions: (1) no existing default changes, so the duration-reporting model is an installer opt-in (`-TimedModel`) and `KokoroTTSConfig.model_path` stays `tools/kokoro/kokoro-v1.0.onnx`; (2) the go/no-go measurements D0 to D4 run before the build (section 12.1), and only D0e and the installer sessions run after it (12.2).
**Orchestrator ruling, 2026-11-28 (after the amendment, in the delegated envelope):** (3) the D2 listen does **not** gate the build, the PR or the merge. The model is an installer opt-in and no default changes, so a pending listen puts nothing at risk, and a rejection after the fact loses only M3 (12.4). The listen gates the Captain's own opt-in and the later default flip. Sections 12.1, 12.4 and 16 (criterion 6) say so; nothing else changes.
**Amended:** same author, 2026-11-27, after the orchestrator's dry build on tree `490bdbb8` (8.1); no design change. D1: `test_x1`'s float-`samples` case passed `samples` twice. D2: `test_x1` gains `ids` (Windows' 32,767-character environment limit). D3: `test_f5`'s tolerance is `abs=2e-4`. D4: the wider `Literal` moves two facade `schema_sha256` rows, so M2 runs `--update-baseline` (decision 11, 6.11, 9.9, 16.2). The base moves to `fae613df` and the citations of the two files the S1 repair changed are re-read (section 17).
**Status:** ready to build after the S1 batch merges **and** the pre-build go/no-go of 12.1 passes (D0 passes and the D2 listen is not rejected). **Owning issue:** #1662 (stays open: S2, S4, S5 and the Captain's live acceptance remain). Commit bodies end `Refs #1662.`; no subject carries an `AD-` or `BF-` token or the words close, fix or resolve; the PR text has no closing keyword.
**Base:** the repaired S1 batch head `fae613dff8688abe336d7b4ee4eae60b516015cb` (tree `490bdbb893cecc2ffa4f8ec35d1562860f0519da`; PR #1872, repair commits `5140323b` and `fae613df`), which becomes main when PR #1872 merges. Rebase onto that merge before building. The anchors were first read on `88676ab1` (tree `6b9082a9`); the repair moved only `src/probos/audio/tts/piper_backend.py` and `tests/test_ad738g_kokoro_voice.py`, whose citations are re-read on `490bdbb8` (section 17), and every SEARCH matches once on `490bdbb8` (8.1). **Number:** a slice of AD-738g, the issue's own number, as S1 was. No new AD or BF number. `scripts/ad_ceiling.py` exited 1 on this run (git log AD-1359, prompts AD-1361, GitHub titles FAILED: no gh host for this clone's remote), so no number could have been allocated anyway.
**Design base:** the Architect re-rank of 2026-11-28 (`s3-rerank-decision.md`: option D, design points 1 to 7, measurements D0 to D4). The router, outcome and timing-carrier design comes from `s3-architect-decision.md`, with one change (decision 3). The evidence is `s3-evidence-pack.md` sections 6 and 8. The PyTorch reading (pack sections 2 to 5) is the fallback's evidence only.
**Line endings:** the working copies are CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII, and IPA symbols in Python are `\uXXXX` escapes.
**Estimated tests:** Python 31 new functions in two new files (11 in 7.2, 20 in 7.4) (one is parametrised over the 114 vocabulary symbols, one over 24 refusals, one over 2 route cases). 1 case added to a parametrised test. 1 test updated in place (a stand-in engine attribute, with its reason inline). 2 test stand-ins gain the new service method. The three existing default-path pins are not touched. 0 removed. No UI change.

## 1. Problem (premise table)

| Where (this tree) | What it does today | Effect |
|---|---|---|
| `scripts/kokoro-fetch.ps1`:42-46 | pins release `model-files-v1.0`, `kokoro-v1.0.onnx` 325,532,387 B, sha `7d5df8ec...`; it has only `-Force` and `-DestDir` (`:24-27`) | that export has only an `audio` output (S1, `reference-projects.md`:83), so `Kokoro.has_timings` is False and `create_timed` returns no timings (`kokoro_onnx/__init__.py`:86, :138, :286); there is no way to fetch an export that has them |
| `config_models/experience.py`:652; pinned by `tests/test_ad1152_agentic_correlation.py`:353-357, `tests/test_ad738g_kokoro_voice.py`:647, `tests/test_ad1270e2c_experience_models.py`:212 | the default `model_path` is `tools/kokoro/kokoro-v1.0.onnx`, the file every S1 install has | S3a keeps it (decision 2): a default naming a file the operator has not fetched would drop his Kokoro voice to the browser voice on the next pull |
| `scripts/kokoro_worker.py`:41-46, :103 | `Engine` has `get_voices` and `create`; `speak` calls `create` | no timings leave the worker even from a model that has them |
| `audio/tts/resident.py`:197-204, :303-304, :490-492 | `PiperOutcome(audio, reason, ...)`; `synthesize` returns `bytes \| None` | nothing can carry a second file from the worker to the backend |
| `audio/tts/backends.py`:9-19 | `TTSResult(audio_bytes, mime)` | the route cannot receive timings |
| `config_models/experience.py`:726; `settings/section_registry.py`:285 | `LipSyncConfig.backend: Literal["heuristic", "rhubarb"]` | no way to choose synthesizer timing |
| `routers/avatars.py`:333 | frames come only from rhubarb (inline, or deferred to `/lipsync`) | Kokoro speech costs a rhubarb run of about 0.85 s per sentence (`avatars.py`:277) |
| `kokoro_onnx/__init__.py`:258, :302; `pauses.py`:79-80 | `create()` *is* `create_timed()`; with timings present, `insert_pauses` tops up the gap after every `.!?…` to 0.25 s and after every `,;:` to 0.1 s | swapping the model file alone changes pacing even with the worker unchanged |
| `kokoro_onnx/__init__.py`:206-210, :238-240; `chunker.py`:89-96 | a request over 510 phonemes is split; each batch but the last is followed by `pause_after(...)` seconds of silence | zero pauses also drop the batch-join silence S1 has today (decision 5) |

## 2. Solution

S3a is one slice, built as three commits. The model gains a duration output, the worker writes the timings beside each WAV, the resident service and the backend carry them through, and under the new opt-in `lipsync.backend: "synthesizer"` the route makes Oculus frames from them inline. A sentence without usable timings takes the rhubarb path, exactly as `rhubarb` does.

- **Model (an installer opt-in; no default changes).** `scripts/kokoro-fetch.ps1 -TimedModel` also fetches `model-files-v1.1`'s `kokoro-v1.0.onnx` (325,505,369 B, sha256 `beb0d184...`) and saves it as `<DestDir>/kokoro-v1.1.onnx`, beside S1's `kokoro-v1.0.onnx`, with the same size and SHA-256 check and the same guards. It then speaks the test line through that file, requires the timing file, and prints the `tts.kokoro.model_path` line to set. A run without the switch is S1's run exactly. The voices file is unchanged: the same pin, byte-identical in both releases. `KokoroTTSConfig.model_path` stays `tools/kokoro/kokoro-v1.0.onnx`; the operator opts in by setting it. Flipping the default waits for the Captain's acceptance of D2 (section 10).
- **Worker.** `Engine` gains `has_timings` and `create_timed`.
  - When `has_timings` is True, `speak` calls `create_timed(..., sentence_pause=0.0, clause_pause=0.0)`. Before it prints the path, it writes `<output_file>.timing.json` = `{"v":1,"rate":24000,"samples":N,"timings":[{"p","s","e"}]}`, atomically.
  - Otherwise it calls `create` exactly as S1 does and writes no file. Empty timings also mean no file.
  - The line protocol is byte-identical.
- **Resident service.** `WorkerKey.timing_sidecar` is False for Piper and True for Kokoro. `PiperOutcome.timing: bytes | None = None` is read with a 256 KiB cap, and the timing file is deleted along with the WAV. The new `synthesize_outcome` returns the `ok` outcome, and `synthesize` stays as that call without the timing.
- **Backend.** `TTSResult.timing: bytes | None = None` is the raw file; `KokoroBackend` passes it through.
- **Frames.** New `src/probos/avatars/phoneme_visemes.py` (standard library plus `VisemeFrame`):
  - a tested 114-symbol table from espeak-style IPA to the Oculus 15-set;
  - `frames_from_timing(timing, wav)`, which checks the file against the WAV and returns frames, or `None` after one WARNING.
- **Router and config.** `LipSyncConfig.backend` gains `"synthesizer"`, and the registry enum gains it too. The code default stays `heuristic`, and `rhubarb` behaves byte for byte as today.

Rejected, one line each:
- **Option B (a PyTorch engine in a second venv).** About 585 MB plus about 1 GB of torch and an unproven pin set, for durations the export asserts equal to D's (`export.py`:187-189, agent-read). It stays the named fallback, re-opened by a D0 failure or a rejected D2 listen.
- **Option A (torch replaces ONNX).** It has B's costs and gives up the measured default voice.
- **Option C (ONNX audio, torch durations).** Unsound: misaki and espeak give different phoneme strings.
- **`TTSResult.visemes` (frames built in the backend).** It creates an import cycle (decision 3).
- **A config field for the pauses or the offset.** No measured need yet. D3 and D4 pick values, and a later slice exposes them if the Captain wants them.
- **Timed frames for deferred `/lipsync` requests.** That would need timings cached by attachment id. Inline frames cost nothing, so a synthesizer request never defers.
- **`create(continuous=True)`.** It is a prosody change costing about 1.4x the work (`__init__.py`:287-288). Out of scope.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| 1 | Build D, not B; B is the named fallback | The Captain's order ("PyTorch first; fall back to the ONNX export question only if it fails") set the order of research, and the PyTorch check succeeded. D was found while answering it: the same engine, voices file, licence set, CPU path and 326 MB size, and the library S1 runs already reads its output (`__init__.py`:85-86, :271-306). His fallback clause describes D. Building the cheaper equivalent first is inside the envelope and needs no Captain decision, and because the model is an opt-in (decision 2) nothing changes for him until he chooses it. D0 and D2 run before the build (12.1), so a file that fails costs no build. The reasoning is recorded on #1662 (section 13). |
| 2 | The new model is an installer opt-in, `-TimedModel`, saved as `kokoro-v1.1.onnx` beside the old file; **no default changes** (orchestrator decision, 2026-11-28) | A default naming a file the operator does not have is a foot-gun: anyone who pulls `D:\ProbOS` without re-running a 326 MB installer would drop from his working S1 voice to the browser voice mid-session (`kokoro_backend.py`:156-160). So `model_path` keeps S1's default, and the v1.1 file is fetched only on request. The local name differs because the v1.1 asset is also named `kokoro-v1.0.onnx` but has a different hash (`kokoro-fetch.ps1`:44 vs the release digest): one name for two files would make the skip check (`:67`) re-download every run, or make a rollback silently load the new file. Flipping the default is its own later slice (section 10). |
| 3 | The timings travel as raw bytes (`TTSResult.timing`), and frames are made in the route, not in the backend | `avatars/rhubarb_backend.py`:26 imports `probos.audio.tts.resident`. If `audio/tts/kokoro_backend.py` imported `avatars.phoneme_visemes` (which needs `VisemeFrame`), then importing `rhubarb_backend` first would run `audio/tts/__init__` → `kokoro_backend` → `phoneme_visemes` → a partly initialised `rhubarb_backend`, and fail with ImportError. The lip-sync choice is the route's concern (`avatars.py`:332), so the backend should not read `lipsync` config. The route already imports avatar modules locally (`:374`). V3 guards the layer edge. |
| 4 | Pauses at zero only when `has_timings`; the untimed path calls `create` unchanged | With the v1.0 file, `create_timed` with zero pauses would also drop S1's batch-join silence (`__init__.py`:238-240). Keeping `create` keeps S1 byte-identical on the old model, which is the rollback. |
| 5 | Pause premise, corrected: zero is exact parity with S1 only for single-batch requests | Zero removes `insert_pauses` (`pauses.py`:79-80) *and* the batch-join pause (`chunker.py`:89-96 via `__init__.py`:206-210, :238-240), which S1 has on requests over 510 phonemes. The client sends one sentence at a time (`ui/src/audio/voice.ts`, sentence pipelining), so multi-batch requests are rare. D3 counts them, and the library defaults (0.25 s and 0.1 s) are a later opt-in. |
| 6 | Validation replaces the 50 ms sum check | `sliding.py`:38-41 rescales the durations to the real audio length, so the sum always matches. D0 checks the raw relation once per pinned file. At runtime `frames_from_timing` refuses: an unreadable file; `v != 1`; a `rate` or `samples` other than the WAV header's; anything but 1 to 4096 entries; a symbol that is not one character; a non-finite or non-numeric (or bool) time; `s > e`; a time outside [0, (samples + 600) / rate]; a start earlier than the previous one. A refusal logs one WARNING and the sentence takes the rhubarb path. |
| 7 | The table is keyed on the 114 symbols of kokoro-onnx 0.6.1's vocabulary (`kokoro_onnx/config.json`:35-148) | The symbols are espeak IPA (`tokenizer.py`:85-88), so a diphthong is already two symbols: no splitting. Stress, length, aspiration, palatalisation, nasalisation, intonation and `\u1d5d` take the previous key. Space and punctuation are `sil`. Gaps (BOS lead-in, the EOS tail, #392's long end pauses) are `sil`. Zero-length spans (made by `np.clip` after the head trim, `__init__.py`:237) are dropped. An unknown symbol is `sil` and is counted in one INFO line; it never raises. Equal neighbours merge. The misaki letters `A I O Q S T W Y` are in the vocabulary but espeak never emits them; each maps to its nearest single key. The renderer reads only `aa ih ou E oh` for its morph weights (`rhubarb_backend.py`:34-40), so the consonant rows are for completeness. |
| 8 | Under `synthesizer`, valid timings go inline with `visemes_deferred: false` even when the client asked to defer | No rhubarb run, so there is nothing to defer. The shipped client takes inline frames when `visemes_deferred` is not true (`voice.ts`:731-734). |
| 9 | `/api/avatars/lipsync` is unchanged; under `synthesizer` it runs rhubarb and answers `backend: "rhubarb"` | Its only branch is `== "heuristic"` (`avatars.py`:62), so the rest is rhubarb. The client accepts deferred frames only with `backend === 'rhubarb'` (`voice.ts`:757). |
| 10 | `TIMING_OFFSET_SECONDS = 0.0` is a module constant | D4 tunes it once if needed, as a one-line source change with its own test. HeadTTS ships a similar pair of constants (section 15). |
| 11 | No new config field | `LipSyncConfig.backend` widens only: a wider `Literal` changes no default value, so neither the AD-1152 digest (it hashes values) nor the facade counts move. The facade baseline holds a `schema_sha256` per model as well as its defaults (`config-facade-baseline.yaml`:2287, :2290), so the wider `Literal` moves exactly two digests, `LipSyncConfig`'s and `SystemConfig`'s (which depends on every config model), and M2 regenerates the baseline with `--update-baseline` (6.11), as the S1 batch did for three models. No default changes at all, `model_path` included (decision 2), so the three default-path pins, the facade baseline line `:2239` and the reference line `config-reference.md`:2072 are not touched. |

## 4. Milestones and commits

Each milestone is one commit, built and focused-tested before the next (section 8 names the tests). Stage explicit paths only, never `git add -A`. Run `git diff --cached --stat` before each commit, and stop on any unexpected file with more than 200 deletions.

| M | Sections | Commit subject |
|---|---|---|
| M1 | 6.1 to 6.5, new files 7.1 and 7.2, test edits 6.10 a to c | `Speech: the Kokoro worker writes phoneme timings beside each WAV when its model reports durations, and the voice service carries them to the backend` |
| M2 | 6.6, 6.7, 6.8, new files 7.3 and 7.4, test edit 6.10 d, regenerations 6.11 (M2 lines: `docs/development/config-reference.md` and `docs/development/config-facade-baseline.yaml`) | `Speech: lip-sync from the synthesizer's phoneme timings, opt in as lipsync.backend synthesizer; rhubarb and the heuristic unchanged` |
| M3 | 6.11 (M3 lines), 6.12, 6.13 | `Speech: the Kokoro installer fetches the export that reports durations on request (-TimedModel), beside the earlier model file; no default changes` |

M3 changes no default and no test: the default `model_path` stays, and so do its three pins (`tests/test_ad1152_agentic_correlation.py`:353-357, `tests/test_ad738g_kokoro_voice.py`:647, `tests/test_ad1270e2c_experience_models.py`:212). Section 6.9 and test edits 6.10 e to g are withdrawn. 7.4's `test_c6` pins the default.

The build starts only after the pre-build go/no-go of 12.1 (D0 passes, the D2 listen is not rejected). D0e runs after M2 and the installer sessions after M3 (12.2), both before the PR opens.

## 5. Builder: may and may not

- **May:** create the four new files with the content given; apply the pairs in order; run each milestone's focused line (8.2); run the regeneration commands of 6.11 and `gen_ad_ledger.py`; `git diff --check` and `git diff --stat`. Run the vocabulary cross-check of 6.11 (it reads `G:\speech-kokoro-probe\venv\Lib\site-packages\kokoro_onnx\config.json`, read-only).
- **May not:** edit an unnamed file; edit `tests/test_bf930_voice_path_timing.py`, `tests/test_bf918_tts_latency.py`, the AD-1346 census fixtures or `tests/test_bf892_spawn_env_guard.py`; add `skip`, `xfail` or a retry; add a wall-clock assertion; install or download anything; run the installer; reword an anchor. Stop and report if a SEARCH does not match exactly once, if a regenerated file differs from 6.11's expected diff, or if the census counts move.

## 6. The pairs

### 6.1 `src/probos/audio/tts/resident.py` (M1)

**P1.1** SEARCH:
```python
#: BF-930: a Piper request that takes at least this long (milliseconds) is reported with its steps (log-only).
SLOW_SYNTHESIS_MS = 750.0
```
REPLACE:
```python
#: BF-930: a Piper request that takes at least this long (milliseconds) is reported with its steps (log-only).
SLOW_SYNTHESIS_MS = 750.0
#: AD-738g S3a (#1662): the phoneme-timing file a Kokoro worker writes beside each WAV. The worker cannot
#: import this module, so ``scripts/kokoro_worker.py`` keeps its own ``TIMING_SUFFIX`` and a test pins the two equal.
TIMING_SUFFIX = ".timing.json"
#: AD-738g S3a: a timing file over this size is not read (4096 timed symbols of about 45 bytes each, with headroom).
TIMING_MAX_BYTES = 262144
```

**P1.2** SEARCH:
```python
    ``label`` names the engine in logs and in the temporary directory, ``name`` names the
    model in logs, and ``retire_on_empty`` says whether a request answered without audio
    retires the process (Piper: yes, as BF-918 shipped; Kokoro: no, its worker answers a
    request it cannot speak and stays healthy, and a restart reloads the model).
    """

    @property
    def label(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def retire_on_empty(self) -> bool: ...
```
REPLACE:
```python
    ``label`` names the engine in logs and in the temporary directory, ``name`` names the
    model in logs, and ``retire_on_empty`` says whether a request answered without audio
    retires the process (Piper: yes, as BF-918 shipped; Kokoro: no, its worker answers a
    request it cannot speak and stays healthy, and a restart reloads the model).
    AD-738g S3a: ``timing_sidecar`` says whether the worker may leave a phoneme-timing file
    beside the WAV (``TIMING_SUFFIX``), which the outcome then carries (Piper: no; Kokoro: yes).
    """

    @property
    def label(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def retire_on_empty(self) -> bool: ...

    @property
    def timing_sidecar(self) -> bool: ...
```

**P1.3** SEARCH:
```python
    @property
    def retire_on_empty(self) -> bool:
        return True
```
REPLACE:
```python
    @property
    def retire_on_empty(self) -> bool:
        return True

    @property
    def timing_sidecar(self) -> bool:
        return False
```

**P1.4** SEARCH:
```python
    @property
    def retire_on_empty(self) -> bool:
        return False
```
REPLACE:
```python
    @property
    def retire_on_empty(self) -> bool:
        return False

    @property
    def timing_sidecar(self) -> bool:
        return True
```

**P1.5** SEARCH:
```python
    """One request's result. ``audio`` is set only when ``reason`` is ``ok``."""

    audio: bytes | None
    reason: str
    returncode: int | None = None
    stderr_tail: str = ""
```
REPLACE:
```python
    """One request's result. ``audio`` is set only when ``reason`` is ``ok``.

    AD-738g S3a: ``timing`` is the worker's phoneme-timing file for that audio, when its key has
    ``timing_sidecar`` and the file was there and within ``TIMING_MAX_BYTES``; otherwise ``None``.
    """

    audio: bytes | None
    reason: str
    returncode: int | None = None
    stderr_tail: str = ""
    timing: bytes | None = None
```

**P1.6** SEARCH:
```python
            audio = out.read_bytes() if out.is_file() else b""
            return PiperOutcome(audio, "ok") if audio else PiperOutcome(None, "empty")
        except (OSError, ValueError) as exc:
            if self._timed_out:
                return PiperOutcome(None, "timeout")
            return PiperOutcome(None, f"error: {type(exc).__name__}: {exc}")
        finally:
            if out is not None:
                try:
                    out.unlink(missing_ok=True)
                except OSError:
                    pass
```
REPLACE:
```python
            audio = out.read_bytes() if out.is_file() else b""
            if not audio:
                return PiperOutcome(None, "empty")
            # AD-738g S3a: a timing key's worker may have left phoneme timings beside the WAV.
            timing = self._read_timing(out) if self.key.timing_sidecar else None
            return PiperOutcome(audio, "ok", timing=timing)
        except (OSError, ValueError) as exc:
            if self._timed_out:
                return PiperOutcome(None, "timeout")
            return PiperOutcome(None, f"error: {type(exc).__name__}: {exc}")
        finally:
            if out is not None:
                # AD-738g S3a: the timing file goes with its WAV (a leftover would also go with the directory).
                leftovers = (out, out.with_name(out.name + TIMING_SUFFIX)) if self.key.timing_sidecar else (out,)
                for leftover in leftovers:
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError:
                        pass
```
(The census of `tests/test_ad1346_admission_file_write_census.py`:170-188 counts `unlink` call sites: still one here. A read-mode `open` is not a point, per the same file's docstring at :15. Its counts must not move.)

**P1.7** SEARCH:
```python
    @staticmethod
    def _await_answer(stdout: IO[bytes], name: str) -> bool:
```
REPLACE:
```python
    @staticmethod
    def _read_timing(wav: Path) -> bytes | None:
        """AD-738g S3a: the timing file beside ``wav``. ``None`` when there is none (a model that reports
        no durations, or a write the worker gave up on), when it cannot be read, or when it is over
        ``TIMING_MAX_BYTES``; the last two log one WARNING. Never raises."""
        path = wav.with_name(wav.name + TIMING_SUFFIX)
        try:
            with path.open("rb") as handle:
                data = handle.read(TIMING_MAX_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning(
                "AD-738g: cannot read the timing file (%s: %s); this sentence has no synthesizer timings",
                type(exc).__name__, exc,
            )
            return None
        if len(data) > TIMING_MAX_BYTES:
            logger.warning(
                "AD-738g: the timing file is over %d bytes; this sentence has no synthesizer timings",
                TIMING_MAX_BYTES,
            )
            return None
        return data

    @staticmethod
    def _await_answer(stdout: IO[bytes], name: str) -> bool:
```

**P1.8** SEARCH:
```python
    async def synthesize(
        self, key: WorkerKey, text: str, timeout: float, *, fields: Mapping[str, str | float] | None = None,
    ) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade.

        AD-738g: ``fields`` join the request line (Kokoro's voice and speed); Piper passes
        none, so its line is unchanged.
        """
```
REPLACE:
```python
    async def synthesize(
        self, key: WorkerKey, text: str, timeout: float, *, fields: Mapping[str, str | float] | None = None,
    ) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade.

        AD-738g: ``fields`` join the request line (Kokoro's voice and speed); Piper passes
        none, so its line is unchanged. AD-738g S3a: ``synthesize_outcome`` without the timing.
        """
        outcome = await self.synthesize_outcome(key, text, timeout, fields=fields)
        return None if outcome is None else outcome.audio

    async def synthesize_outcome(
        self, key: WorkerKey, text: str, timeout: float, *, fields: Mapping[str, str | float] | None = None,
    ) -> PiperOutcome | None:
        """AD-738g S3a: the ``ok`` outcome for ``text`` (its WAV bytes and, for a ``timing_sidecar``
        key, its timing file or ``None``), or ``None`` to degrade. Admission, locking, retirement and
        the BF-930 timing line are ``synthesize``'s, unchanged."""
```

**P1.9** SEARCH:
```python
                if outcome.audio is not None:
                    return outcome.audio
```
REPLACE:
```python
                if outcome.audio is not None:
                    return outcome
```

### 6.2 `src/probos/audio/tts/backends.py` (M1)

**P2.1** SEARCH (the `—` is in the file today):
```python
    ``None`` from a backend means "honest-degrade — caller falls back."
    """

    audio_bytes: bytes
    mime: str
```
REPLACE:
```python
    ``None`` from a backend means "honest-degrade — caller falls back."

    AD-738g S3a (#1662): ``timing`` is the Kokoro worker's phoneme-timing file for this audio
    (JSON bytes, ``scripts/kokoro_worker.py``), or ``None``. The route checks it and makes lip-sync
    frames from it only under ``lipsync.backend: synthesizer`` (``probos.avatars.phoneme_visemes``).
    """

    audio_bytes: bytes
    mime: str
    timing: bytes | None = None
```

### 6.3 `src/probos/audio/tts/kokoro_backend.py` (M1)

**P3.1** SEARCH:
```python
the phonemizer (GPL-3.0-or-later) and the espeak-ng library it loads (GPL-3.0-or-later) run
only in that separate process, which receives text, a voice id and a speed and returns a WAV
file path. Nothing in ProbOS imports them (THIRD_PARTY_LICENSES.md, "License policy").
```
REPLACE:
```python
the phonemizer (GPL-3.0-or-later) and the espeak-ng library it loads (GPL-3.0-or-later) run
only in that separate process, which receives text, a voice id and a speed and returns a WAV
file path; beside the WAV it may leave a JSON file of phoneme timings (AD-738g S3a), which is
data. Nothing in ProbOS imports them (THIRD_PARTY_LICENSES.md, "License policy").
```

**P3.2** SEARCH:
```python
from probos.audio.tts.resident import KokoroWorkerKey, VoiceSynthesisService
```
REPLACE:
```python
from probos.audio.tts.resident import KokoroWorkerKey, PiperOutcome, VoiceSynthesisService
```

**P3.3** SEARCH:
```python
        wav = await self._speak(text, voice, speed)
        # D10: one line for every attempt, the early degradations in _speak included. The role
        # goes last (AD-738f, #1868), so the Captain can read which role spoke in which voice;
        # no agent id is logged.
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s role=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded", role or "-",
        )
        if wav is None:
            return None
        return TTSResult(audio_bytes=wav, mime="audio/wav")

    async def _speak(self, text: str, voice: str, speed: float) -> bytes | None:
        """The worker's WAV bytes, or ``None`` after a WARNING: no service, an install path the
        OS cannot resolve or a missing file, or the service's own degradation. Never raises."""
```
REPLACE:
```python
        outcome = await self._speak(text, voice, speed)
        # D10: one line for every attempt, the early degradations in _speak included. The role
        # goes last (AD-738f, #1868), so the Captain can read which role spoke in which voice;
        # no agent id is logged.
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s role=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if outcome is not None else "degraded", role or "-",
        )
        if outcome is None or outcome.audio is None:
            return None
        # AD-738g S3a: the worker's timing file rides with the audio; the route decides whether to use it.
        return TTSResult(audio_bytes=outcome.audio, mime="audio/wav", timing=outcome.timing)

    async def _speak(self, text: str, voice: str, speed: float) -> PiperOutcome | None:
        """The service's ``ok`` outcome (the WAV and its timing file, if any), or ``None`` after a WARNING:
        no service, an install path the OS cannot resolve or a missing file, or the service's own
        degradation. Never raises."""
```

**P3.4** SEARCH:
```python
        return await self._service.synthesize(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed})
```
REPLACE:
```python
        return await self._service.synthesize_outcome(
            key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed},
        )
```

### 6.4 `scripts/kokoro_worker.py` (M1)

**P4.1** SEARCH:
```python
(exit 2). Logs go to stderr, which the service sends to a file; library prints go there too.

License posture: this file imports only the standard library and numpy at module level, and
``onnxruntime`` and ``kokoro_onnx`` (both MIT) inside ``load_engine``. kokoro-onnx loads
phonemizer and espeak-ng (GPL-3.0-or-later) into this process, which the operator installs
into ``tools/kokoro/venv`` (``scripts/kokoro-fetch.ps1``) and which exchanges only text, a
voice id and a speed in and a WAV path out with ProbOS (THIRD_PARTY_LICENSES.md, "License policy").
"""
```
REPLACE:
```python
(exit 2). Logs go to stderr, which the service sends to a file; library prints go there too.

AD-738g S3a: when the model reports durations (kokoro-onnx's ``has_timings``: the
``model-files-v1.1`` export), the worker asks for the phoneme timings with no added pauses and,
before it prints the path, writes ``<output_file>.timing.json`` (``write_timing``):
``{"v": 1, "rate": R, "samples": N, "timings": [{"p": symbol, "s": start, "e": end}, ...]}``, the
times in seconds from the start of the WAV. No timings, no file; a file it cannot write is logged
and the audio stands. Any other engine is called exactly as in S1. The line protocol is unchanged.

License posture: this file imports only the standard library and numpy at module level, and
``onnxruntime`` and ``kokoro_onnx`` (both MIT) inside ``load_engine``. kokoro-onnx loads
phonemizer and espeak-ng (GPL-3.0-or-later) into this process, which the operator installs
into ``tools/kokoro/venv`` (``scripts/kokoro-fetch.ps1``) and which exchanges only text, a
voice id and a speed in and a WAV path out with ProbOS, plus the timing file beside the WAV,
which is data (THIRD_PARTY_LICENSES.md, "License policy").
"""
```

**P4.2** SEARCH:
```python
EXIT_CANNOT_START = 2
EXIT_UNREADABLE_LINE = 3
```
REPLACE:
```python
EXIT_CANNOT_START = 2
EXIT_UNREADABLE_LINE = 3
#: AD-738g S3a: the timing file's name after the WAV's (``probos.audio.tts.resident.TIMING_SUFFIX``) and its format version
#: (``probos.avatars.phoneme_visemes.TIMING_VERSION``); this process cannot import probos, so tests pin them equal.
TIMING_SUFFIX = ".timing.json"
TIMING_VERSION = 1
```

**P4.3** SEARCH:
```python
class Engine(Protocol):
    """The part of ``kokoro_onnx.Kokoro`` the worker uses."""

    def get_voices(self) -> list[str]: ...

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]: ...
```
REPLACE:
```python
class Engine(Protocol):
    """The part of ``kokoro_onnx.Kokoro`` the worker uses.

    AD-738g S3a: ``has_timings`` is kokoro-onnx 0.6.1's own flag, True when the model has a
    ``duration`` output; ``create_timed`` returns the audio, the rate and one timing per spoken
    symbol, each with ``phoneme``, ``start`` and ``end`` (seconds).
    """

    has_timings: bool

    def get_voices(self) -> list[str]: ...

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]: ...

    def create_timed(
        self, text: str, voice: str, speed: float, lang: str, sentence_pause: float, clause_pause: float,
    ) -> tuple[Any, int, list[Any]]: ...
```

**P4.4** SEARCH:
```python
def write_wav(path: Path, samples: Any, rate: int) -> None:
    """Write ``samples`` (floats in -1..1) as a 16-bit mono WAV; the file appears whole or not at all."""
    pcm = np.nan_to_num(np.asarray(samples, dtype=np.float32).reshape(-1), nan=0.0)
    if pcm.size == 0:
        raise ValueError("the engine returned no samples")
    frames = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    part = path.with_name(path.name + ".part")
    try:
        with wave.open(str(part), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(int(rate))
            out.writeframes(frames)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
```
REPLACE:
```python
def write_wav(path: Path, samples: Any, rate: int) -> int:
    """Write ``samples`` (floats in -1..1) as a 16-bit mono WAV; the file appears whole or not at all.

    Returns the number of samples written (AD-738g S3a: the timing file records it).
    """
    pcm = np.nan_to_num(np.asarray(samples, dtype=np.float32).reshape(-1), nan=0.0)
    if pcm.size == 0:
        raise ValueError("the engine returned no samples")
    frames = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    part = path.with_name(path.name + ".part")
    try:
        with wave.open(str(part), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(int(rate))
            out.writeframes(frames)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    return int(pcm.size)


def write_timing(path: Path, timings: list[Any], rate: int, samples: int) -> None:
    """AD-738g S3a: write ``timings`` beside the WAV at ``path`` as ASCII JSON; the file appears whole or not at all."""
    body = {
        "v": TIMING_VERSION,
        "rate": int(rate),
        "samples": int(samples),
        "timings": [
            {"p": str(t.phoneme), "s": round(float(t.start), 6), "e": round(float(t.end), 6)} for t in timings
        ],
    }
    target = path.with_name(path.name + TIMING_SUFFIX)
    part = target.with_name(target.name + ".part")
    try:
        part.write_bytes(json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
```

**P4.5** SEARCH:
```python
    try:
        samples, rate = engine.create(text, voice=voice, speed=float(request.get("speed", 1.0)), lang=lang_for(voice))
        write_wav(Path(request["output_file"]), samples, rate)
        return True
    except Exception as exc:  # one request: answer with the path and no file, keep serving (contract D2)
        _log(log, f"AD-738g: no audio for {len(text)} chars in {voice}: {type(exc).__name__}: {exc}")
        return False
```
REPLACE:
```python
    out = Path(request["output_file"])
    timings: list[Any] = []
    try:
        speed = float(request.get("speed", 1.0))
        if engine.has_timings:
            # AD-738g S3a: no added pauses, so the pacing is S1's for a one-batch request (contract decision 5).
            samples, rate, timings = engine.create_timed(
                text, voice=voice, speed=speed, lang=lang_for(voice), sentence_pause=0.0, clause_pause=0.0,
            )
        else:
            samples, rate = engine.create(text, voice=voice, speed=speed, lang=lang_for(voice))
        written = write_wav(out, samples, rate)
    except Exception as exc:  # one request: answer with the path and no file, keep serving (contract D2)
        _log(log, f"AD-738g: no audio for {len(text)} chars in {voice}: {type(exc).__name__}: {exc}")
        return False
    if timings:
        try:
            write_timing(out, timings, rate, written)
        except Exception as exc:  # the audio stands; this sentence's lip-sync takes the rhubarb path
            _log(log, f"AD-738g: no timing file for {len(text)} chars in {voice}: {type(exc).__name__}: {exc}")
    return True
```
(`speak`'s docstring, "True when a file was written; never raises", is still true. The module-level imports are unchanged, so `test_w8` (`tests/test_ad738g_kokoro_voice.py`:347) still holds.)

### 6.5 `tests/fixtures/fake_kokoro_worker.py` (M1): replaced whole by 7.1

### 6.6 `src/probos/config_models/experience.py`: the `Literal` (M2)

**P6.1** SEARCH (the `→` is in the file today):
```python
    backend: Literal["heuristic", "rhubarb"] = "heuristic"
    """``heuristic``: AD-721b v1 text→viseme. ``rhubarb``: subprocess to
    rhubarb-lip-sync for phonetic alignment of real audio."""
```
REPLACE:
```python
    backend: Literal["heuristic", "rhubarb", "synthesizer"] = "heuristic"
    """``heuristic``: AD-721b v1 text→viseme. ``rhubarb``: subprocess to
    rhubarb-lip-sync for phonetic alignment of real audio. ``synthesizer``
    (AD-738g S3a, #1662): frames from the phoneme timings the Kokoro worker reports
    when its model has a duration output (the default ``kokoro-v1.0.onnx`` has none: this also needs
    ``tts.kokoro.model_path`` set to the ``kokoro-fetch.ps1 -TimedModel`` file),
    sent inline with the audio; a sentence without usable timings (Piper, an older
    Kokoro model, a timing file the check refuses) is served exactly as ``rhubarb``."""
```

### 6.7 `src/probos/settings/section_registry.py` (M2)

**P7.1** SEARCH:
```python
                enum_values=("heuristic", "rhubarb"),
```
REPLACE:
```python
                enum_values=("heuristic", "rhubarb", "synthesizer"),
```

### 6.8 `src/probos/routers/avatars.py` (M2)

**P8.1** SEARCH:
```python
    # backend == "rhubarb". BF-918: on the voice executor, inside its admission bound.
```
REPLACE:
```python
    # backend == "rhubarb", or "synthesizer" (AD-738g S3a: a deferred request under it is one whose
    # sentence had no usable timings, so rhubarb serves it; the client accepts backend "rhubarb").
    # BF-918: on the voice executor, inside its admission bound.
```

**P8.2** SEARCH:
```python
    lipsync_cfg = getattr(runtime.config, "lipsync", None)
    if lipsync_cfg is not None and lipsync_cfg.enabled and lipsync_cfg.backend == "rhubarb":
        if defer_visemes:
            visemes_mode = "deferred"
```
REPLACE:
```python
    lipsync_cfg = getattr(runtime.config, "lipsync", None)
    if lipsync_cfg is not None and lipsync_cfg.enabled and lipsync_cfg.backend in ("rhubarb", "synthesizer"):
        # AD-738g S3a (#1662): under "synthesizer" a sentence whose backend sent phoneme timings gets
        # its frames from them, inline: no rhubarb run, so nothing to defer, and the client takes inline
        # frames whatever it asked (ui/src/audio/voice.ts). A sentence without timings, or with timings
        # the check refuses, takes the rhubarb path below exactly as "rhubarb" does.
        timed = None
        if lipsync_cfg.backend == "synthesizer" and result.timing is not None:
            from probos.avatars.phoneme_visemes import frames_from_timing
            timed = frames_from_timing(result.timing, result.audio_bytes)
        if timed:
            visemes_mode = "synthesizer"
            visemes_payload = [
                {"time": f.time, "duration": f.duration, "viseme": f.viseme}
                for f in timed
            ]
        elif defer_visemes:
            visemes_mode = "deferred"
```
(Under `rhubarb` the new condition reads `result.timing` only after `== "synthesizer"` short-circuits, so a test stub that returns something other than a `TTSResult` under `rhubarb` is unaffected. The `else` branch after it is unchanged.)

### 6.9 Withdrawn: the default model does not change

`KokoroTTSConfig.model_path` (`experience.py`:652-653) is not edited, its docstring included (decision 2). The Builder must not touch it. `test_c6` (7.4) and the three existing pins guard it.

### 6.10 Test edits

**a (M1)** `tests/test_ad738g_kokoro_voice.py`. SEARCH:
```python
    class _ToneEngine:
        def get_voices(self) -> list[str]:
            return ["af_heart"]
```
REPLACE:
```python
    class _ToneEngine:
        has_timings = False  # AD-738g S3a: an S1-style engine, which the worker calls through create as before

        def get_voices(self) -> list[str]:
            return ["af_heart"]
```

**b (M1)** The same file. SEARCH:
```python
from probos.audio.tts.resident import KokoroWorkerKey, PiperWorkerKey, VoiceSynthesisService
```
REPLACE:
```python
from probos.audio.tts.resident import KokoroWorkerKey, PiperOutcome, PiperWorkerKey, VoiceSynthesisService
```
SEARCH:
```python
    async def synthesize(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return self.wav
```
REPLACE:
```python
    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        # AD-738g S3a: KokoroBackend calls synthesize_outcome; this stand-in has no synthesize, so a call to it fails.
        self.calls.append((key, text, timeout, dict(fields or {})))
        return None if self.wav is None else PiperOutcome(self.wav, "ok")
```

**c (M1)** `tests/test_ad738f_per_agent_voices.py`. SEARCH:
```python
from probos.audio.tts.resident import VoiceSynthesisService
```
REPLACE:
```python
from probos.audio.tts.resident import PiperOutcome, VoiceSynthesisService
```
SEARCH:
```python
    async def synthesize(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return b"RIFF"
```
REPLACE:
```python
    async def synthesize(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return b"RIFF"

    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        # AD-738g S3a: KokoroBackend's call; PiperBackend (test_p1) still calls synthesize.
        self.calls.append((key, text, timeout, dict(fields or {})))
        return PiperOutcome(b"RIFF", "ok")
```

**d (M2)** `tests/test_ad1270e2c_experience_models.py`. SEARCH:
```python
    # AD-738g S1 (#1662): "kokoro" joins the TTS backend Literal; "espeak" stays rejected below.
    [("TTSConfig", "piper"), ("TTSConfig", "kokoro"), ("LipSyncConfig", "rhubarb")],
```
REPLACE:
```python
    # AD-738g S1 (#1662): "kokoro" joins the TTS backend Literal; "espeak" stays rejected below.
    # AD-738g S3a: "synthesizer" joins the lip-sync backend Literal.
    [("TTSConfig", "piper"), ("TTSConfig", "kokoro"), ("LipSyncConfig", "rhubarb"), ("LipSyncConfig", "synthesizer")],
```

**e, f, g: withdrawn.** The three default-path pins (`tests/test_ad738g_kokoro_voice.py`:647, `tests/test_ad1270e2c_experience_models.py`:212, `tests/test_ad1152_agentic_correlation.py`:353-357) stay exactly as they are, because the default does not change (decision 2). They move only in the later slice that flips the default (section 10).

S3a adds no config field and changes no default, so `tests/test_ad1152_agentic_correlation.py` needs no edit: no new `pop`, and the digest hashes values (`:563`), so the wider `Literal` does not move it. It stays in the focused set (8.2) all the same.

### 6.11 Regenerations and cross-checks (from the worktree root, in this order)

**M2** (after 6.6 and 6.7):
```text
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe -c "import json; from probos.avatars.phoneme_visemes import PHONEME_VISEMES; v = json.load(open(r'G:\speech-kokoro-probe\venv\Lib\site-packages\kokoro_onnx\config.json', encoding='utf-8'))['vocab']; print(len(v), len(PHONEME_VISEMES), sorted(set(v) ^ set(PHONEME_VISEMES)))"
```
Expected:
- `git diff docs/development/config-reference.md` is the one line `:2042`, which becomes `Literal['heuristic', 'rhubarb', 'synthesizer']`.
- `git diff docs/development/config-facade-baseline.yaml` is exactly two lines: the `schema_sha256` of `LipSyncConfig` (`:2287`) and of `SystemConfig` (`:3431`). No default row and no count changes. Informative only (measured on tree `490bdbb8`): `LipSyncConfig` `d5adee56...` becomes `f07fcef579cb75e70621d9e9520aec7d0add0dfedc8edea88760173cfc4b516c`, and `SystemConfig` `809d14b4...` becomes `09bc44854361aed334f26d899554c03a6d2043aeeac06d4612035840e411d77f`; `SystemConfig`'s digest depends on every config model, so if `main` has taken another config change its value differs and the rule (these two rows only, counts unchanged) still holds. A third row, or any `default:` row, means something else moved: stop and report.
- The facade `--check` then passes: `config facade check passed (names=311, owned=298, incidental=13, models=229, fields=1886, env rows=4)`. (Measured on `490bdbb8`; on the re-anchored base `55ae03eb` the count is `fields=1887`, because main's PR #1873 added one config field and S3a adds none.) Without `--update-baseline` it fails with two `facade-schema-digest` problems, and so does `tests/test_ad1270e1_config_facade.py::test_check_is_green_on_the_committed_baseline` (`:1813`).
- The last command prints `114 114 []`. Any symbol it prints means the table or V1's literal is wrong: stop and report.

**M3** (after 6.13; no config regeneration, since no default changes):
```text
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
```
Expected:
- Both config checks pass, and M3 changes neither `config-facade-baseline.yaml` nor `config-reference.md`: M2 changed them (the two `schema_sha256` lines and the one line `:2042`), and M3 adds nothing. A diff at `:2239` or `:2072` means the default moved: stop and report.
- The checker's counts equal the pins at `tests/test_ad1270e1_config_facade.py`:1531-1534 and :1582 (311, 298, 13, 229, 1886). No model or field is added, so none moves.
- Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` only if the ledger tool changed them.

### 6.12 `scripts/kokoro-fetch.ps1` (M3)

**The switch: `-TimedModel`.** Without it, the script runs exactly as S1's: the same two files, the same lines, the same test sentence on `kokoro-v1.0.onnx`, the same closing lines. Every new line is inside `if ($TimedModel)`, except the one URL line of P12.3, which yields S1's URL for S1's two files. With it:
- a third entry joins the file list: `model-files-v1.1`'s asset `kokoro-v1.0.onnx`, saved as `kokoro-v1.1.onnx` under `$DestDir` beside S1's files, size- and SHA-256-checked by S1's loop, with S1's skip, `.part` and mismatch handling and messages;
- the test sentence runs through `kokoro-v1.1.onnx`, and the run **throws** unless the worker wrote the timing file;
- the closing lines name the two config lines to set and, for the rollback, the S1 model file of this install (restore the previous values; never delete the lines).

How it composes:
- **`-DestDir`:** the new file goes into the same resolved, ASCII-checked folder as the other two. The printed `model_path` is `tools/kokoro/kokoro-v1.1.onnx` when `-DestDir` was not passed, and the absolute path otherwise (as S1's header asks for a non-default folder).
- **`-Force`:** it applies to every file of the run, as in S1: the venv is rebuilt and all three files are re-downloaded.
- **S1's files:** S1's `kokoro-v1.0.onnx` and `voices-v1.0.bin` are still fetched or `[skip]`ped. The script never deletes or overwrites `kokoro-v1.0.onnx` with the v1.1 bytes, because the local names differ (decision 2).

Every S1 guard stays as it is: the destination is resolved first (`:37`), the ASCII-path refusal (`:38-40`), the `uv` check, the venv, the boundary check, and the UTF-8 decode scope with its `finally` restore (`:106-113`). A new parameter is declared last, so `-DestDir`'s position does not move (it is the only non-switch parameter).

**P12.1** SEARCH:
```text
#   2. The Kokoro-82M model files (Apache-2.0 weights) from the kokoro-onnx release
#      model-files-v1.0, each checked for its size and SHA-256 (the release publishes no
#      digests; the pins are the LFS ids of the byte-identical files on
#      huggingface.co/fastrtc/kokoro-onnx, and matched a download on 2026-11-27).
```
REPLACE:
```text
#   2. The Kokoro-82M model files (Apache-2.0 weights) from the kokoro-onnx release
#      model-files-v1.0, each checked for its size and SHA-256 (the release publishes no
#      digests; the pins are the LFS ids of the byte-identical files on
#      huggingface.co/fastrtc/kokoro-onnx, and matched a download on 2026-11-27).
#      With -TimedModel (AD-738g S3a), also the release model-files-v1.1 export of the same
#      weights, which has a duration output (phoneme timings for lip-sync). The release names
#      it kokoro-v1.0.onnx too, so it is saved as kokoro-v1.1.onnx beside S1's file; its pin is
#      the release's own asset digest (read 2026-11-28). Nothing changes until
#      tts.kokoro.model_path is set to it; setting it back to its previous value undoes that.
```

**P12.1b** SEARCH:
```text
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -Force   # rebuild the venv, re-download
#
param(
    [switch]$Force,
    [string]$DestDir = "tools/kokoro"
)
```
REPLACE:
```text
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -Force   # rebuild the venv, re-download
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -TimedModel   # also the export with timings
#
# -TimedModel composes with both: -DestDir puts kokoro-v1.1.onnx in that folder beside the
# other two files, and -Force re-downloads every file of the run, kokoro-v1.1.onnx included.
param(
    [switch]$Force,
    [string]$DestDir = "tools/kokoro",
    [switch]$TimedModel
)
```

**P12.2** SEARCH:
```text
    @{ name = "kokoro-v1.0.onnx"; size = 325532387; sha256 = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5" }
    @{ name = "voices-v1.0.bin";  size = 28214398;  sha256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" }
)
```
REPLACE (`name` stays the local file name, so every message of the loop is unchanged; the unary comma appends the hashtable as one element):
```text
    @{ name = "kokoro-v1.0.onnx"; size = 325532387; sha256 = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5" }
    @{ name = "voices-v1.0.bin";  size = 28214398;  sha256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" }
)
if ($TimedModel) {
    # AD-738g S3a: release model-files-v1.1's asset, also named kokoro-v1.0.onnx, saved as kokoro-v1.1.onnx.
    $Files += ,@{ name = "kokoro-v1.1.onnx"; url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx"; size = 325505369; sha256 = "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a" }
}
```

**P12.3** SEARCH:
```text
    $target = Join-Path $DestDir $f.name
    if (-not $Force -and (Test-Path $target) -and ((Get-FileHash $target -Algorithm SHA256).Hash.ToLower() -eq $f.sha256)) {
        Write-Host "[skip] $($f.name) (present, SHA-256 verified)" -ForegroundColor DarkGray
        continue
    }
    $part = "$target.part"
    Write-Host "[get ] $($f.name) ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri "$Base/$($f.name)" -OutFile $part -UseBasicParsing
```
REPLACE (only the URL line changes; S1's two entries have no `url`, so they get S1's URL):
```text
    $target = Join-Path $DestDir $f.name
    if (-not $Force -and (Test-Path $target) -and ((Get-FileHash $target -Algorithm SHA256).Hash.ToLower() -eq $f.sha256)) {
        Write-Host "[skip] $($f.name) (present, SHA-256 verified)" -ForegroundColor DarkGray
        continue
    }
    $part = "$target.part"
    Write-Host "[get ] $($f.name) ..." -ForegroundColor Cyan
    $Url = if ($f.ContainsKey("url")) { $f.url } else { "$Base/$($f.name)" }
    Invoke-WebRequest -Uri $Url -OutFile $part -UseBasicParsing
```

**P12.4: withdrawn.** The mismatch and `[ ok ]` lines are S1's; `name` is the local name, so they name `kokoro-v1.1.onnx` for the new file.

**P12.5** SEARCH:
```text
$Model = Join-Path $DestDir "kokoro-v1.0.onnx"
$Voices = Join-Path $DestDir "voices-v1.0.bin"
$Worker = Join-Path $Root "scripts\kokoro_worker.py"
$Probe = Join-Path $DestDir "fetch-check.wav"
if (Test-Path $Probe) { Remove-Item $Probe -Force }
```
REPLACE:
```text
$Model = Join-Path $DestDir "kokoro-v1.0.onnx"
if ($TimedModel) { $Model = Join-Path $DestDir "kokoro-v1.1.onnx" }  # AD-738g S3a: the test line runs on the new file
$Voices = Join-Path $DestDir "voices-v1.0.bin"
$Worker = Join-Path $Root "scripts\kokoro_worker.py"
$Probe = Join-Path $DestDir "fetch-check.wav"
$Timing = "$Probe.timing.json"  # AD-738g S3a: the worker's phoneme timings beside the WAV
if (Test-Path $Probe) { Remove-Item $Probe -Force }
if ($TimedModel -and (Test-Path $Timing)) { Remove-Item $Timing -Force }
```

**P12.6** SEARCH (the end of the file):
```text
$Bytes = (Get-Item $Probe).Length
Remove-Item $Probe -Force
Write-Host "[ ok ] the Kokoro worker spoke the test line ($Bytes bytes of 24 kHz WAV)" -ForegroundColor Green
Write-Host ""
Write-Host "Kokoro is installed at: $DestDir" -ForegroundColor White
Write-Host "Set tts.backend: kokoro and tts.sentence_pipelining_enabled: true in config/system.yaml, then restart." -ForegroundColor White
```
REPLACE:
```text
$Bytes = (Get-Item $Probe).Length
Remove-Item $Probe -Force
Write-Host "[ ok ] the Kokoro worker spoke the test line ($Bytes bytes of 24 kHz WAV)" -ForegroundColor Green
if ($TimedModel) {
    if (-not (Test-Path $Timing)) {
        throw "kokoro-v1.1.onnx spoke the test line but wrote no phoneme timings ($Timing), so it cannot time lip-sync. Leave tts.kokoro.model_path on kokoro-v1.0.onnx."
    }
    Remove-Item $Timing -Force
    Write-Host "[ ok ] the model reports phoneme timings (lipsync.backend: synthesizer can use them)" -ForegroundColor Green
}
Write-Host ""
Write-Host "Kokoro is installed at: $DestDir" -ForegroundColor White
Write-Host "Set tts.backend: kokoro and tts.sentence_pipelining_enabled: true in config/system.yaml, then restart." -ForegroundColor White
if ($TimedModel) {
    $Setting = if ($PSBoundParameters.ContainsKey("DestDir")) { $Model } else { "tools/kokoro/kokoro-v1.1.onnx" }
    $S1Model = Join-Path (Split-Path -Parent $Model) "kokoro-v1.0.onnx"
    if (-not $PSBoundParameters.ContainsKey("DestDir")) { $S1Model = "tools/kokoro/kokoro-v1.0.onnx" }
    Write-Host "For lip-sync timed by the voice, also set tts.kokoro.model_path: $Setting and lipsync.backend: synthesizer, then restart." -ForegroundColor White
    Write-Host "To go back, set those two settings to the values they had before, then restart. The S1 model file for this install is $S1Model." -ForegroundColor White
}
```
Without the switch the output is S1's line for line: the `$Timing` assignment prints nothing, and the stale-file removal and both new blocks are skipped.

### 6.13 Licences, research row and trackers (M3)

**P13.1** `THIRD_PARTY_LICENSES.md`. SEARCH:
```text
- Used by: `scripts/kokoro_worker.py`, a ProbOS-authored worker that runs in a separate process. `src/probos/audio/tts/kokoro_backend.py` starts it through the resident voice service (`src/probos/audio/tts/resident.py`) and exchanges only text, a voice id and a speed in, and a WAV file path out (one JSON line each way).
- Installation: **not** in `pyproject.toml`. The operator runs `scripts/kokoro-fetch.ps1`, which makes a separate venv at `tools/kokoro/venv` (gitignored under `/tools/`) with `uv pip install kokoro-onnx==0.6.1`, and downloads `kokoro-v1.0.onnx` (325,532,387 B) and `voices-v1.0.bin` (28,214,398 B) from the kokoro-onnx release `model-files-v1.0`, SHA-256 pinned.
```
REPLACE:
```text
- Used by: `scripts/kokoro_worker.py`, a ProbOS-authored worker that runs in a separate process. `src/probos/audio/tts/kokoro_backend.py` starts it through the resident voice service (`src/probos/audio/tts/resident.py`) and exchanges only text, a voice id and a speed in, and a WAV file path out (one JSON line each way). Since AD-738g S3a the worker may also leave `<wav>.timing.json` beside the WAV: phoneme symbols and times, which are data; `src/probos/avatars/phoneme_visemes.py` (standard library only) reads it.
- Installation: **not** in `pyproject.toml`. The operator runs `scripts/kokoro-fetch.ps1`, which makes a separate venv at `tools/kokoro/venv` (gitignored under `/tools/`) with `uv pip install kokoro-onnx==0.6.1`, and downloads `kokoro-v1.0.onnx` (325,532,387 B) and `voices-v1.0.bin` (28,214,398 B) from the kokoro-onnx release `model-files-v1.0`, SHA-256 pinned. With `-TimedModel` (AD-738g S3a, opt-in) it also downloads, SHA-256 pinned, release `model-files-v1.1`'s `kokoro-v1.0.onnx` (325,505,369 B; the same weights re-exported with a `duration` output), saved as `kokoro-v1.1.onnx` beside the first; it is used only when `tts.kokoro.model_path` names it. Both exports are Apache-2.0 Kokoro-82M weights; no new package or licence.
```

**P13.2** `docs/research/reference-projects.md`. SEARCH:
```text
| Kokoro / misaki / HeadTTS / mlx-audio | 2026-11-27 | checked | AD-738g (#1662) Prior Art; S1 contract `prompts/ad-738g-s1-local-kokoro-voice.md`: kokoro-onnx 0.6.1 and its dependencies (phonemizer GPL-3; espeakng-loader bundles espeak-ng with no licence file), model-files-v1.0 hashes from the Hugging Face LFS ids, and `kokoro-v1.0.onnx` has no `duration` output (no synthesizer timings) |
```
REPLACE:
```text
| Kokoro / misaki / HeadTTS / mlx-audio | 2026-11-28 | checked | AD-738g (#1662) Prior Art; S1 contract `prompts/ad-738g-s1-local-kokoro-voice.md`: kokoro-onnx 0.6.1 and its dependencies (phonemizer GPL-3; espeakng-loader bundles espeak-ng with no licence file), model-files-v1.0 hashes from the Hugging Face LFS ids, and that release's `kokoro-v1.0.onnx` has no `duration` output. S3a contract `prompts/ad-738g-s3a-synthesizer-timed-lipsync.md`: release `model-files-v1.1` re-exports the same weights with a `duration` output that kokoro-onnx 0.6.1 reads (`has_timings`, `create_timed`); its asset digests from the GitHub API; HeadTTS's viseme timing offsets (`deltaStart` -10 ms, `deltaEnd` +10 ms) |
```

**P13.3** `PROGRESS.md`. SEARCH:
```text
# ProbOS Progress

```
REPLACE:
```text
# ProbOS Progress

**AD-738g S3a (2026-11-28), #1662 -- lip-sync timed by the synthesizer, opt in.** `scripts/kokoro-fetch.ps1 -TimedModel` also fetches kokoro-onnx's `model-files-v1.1` export, which reports phoneme durations, saved as `tools/kokoro/kokoro-v1.1.onnx` beside S1's `kokoro-v1.0.onnx`. No default changes: `tts.kokoro.model_path` stays S1's file until the operator sets it to the new one. The worker asks that model for phoneme timings with no added pauses and writes `<wav>.timing.json` beside each WAV; the resident service and `TTSResult.timing` carry it to the route. Under the new `lipsync.backend: synthesizer` the route checks the file against the WAV and sends Oculus frames inline (`src/probos/avatars/phoneme_visemes.py`, a 114-symbol espeak-IPA table); a sentence without usable timings is served exactly as `rhubarb`. The default stays `heuristic` and `rhubarb` is unchanged. To opt in, the operator runs `scripts/kokoro-fetch.ps1 -TimedModel` (326 MB) and sets `tts.kokoro.model_path` and `lipsync.backend: synthesizer`; the rollback is to set both back to their previous values (the installer prints this install's S1 model path), not to delete them. Contract `prompts/ad-738g-s3a-synthesizer-timed-lipsync.md`.

```

**P13.4** `DECISIONS.md`. SEARCH (the `—` is in the file today):
```text
## Era V — Civilization (Phases 31-36)

```
REPLACE:
```text
## Era V — Civilization (Phases 31-36)

### AD-738g S3a -- lip-sync timed by the synthesizer: the kokoro-onnx export that reports durations, a timing file beside each WAV, an opt-in lip-sync backend (2026-11-28, #1662)

- *Scope.* `scripts/kokoro-fetch.ps1` (the `-TimedModel` opt-in and its pin), `scripts/kokoro_worker.py` (`create_timed`, `write_timing`), `audio/tts/resident.py` (`timing_sidecar`, `PiperOutcome.timing`, `synthesize_outcome`), `audio/tts/backends.py` (`TTSResult.timing`), `audio/tts/kokoro_backend.py`, `avatars/phoneme_visemes.py` (new), `routers/avatars.py`, `config_models/experience.py` (`LipSyncConfig.backend` gains `synthesizer`). Contract `prompts/ad-738g-s3a-synthesizer-timed-lipsync.md`.
- *D1.* Option D (the `model-files-v1.1` ONNX export, same weights, a `duration` output) over B (PyTorch kokoro in a second venv): the same engine, voices, licences and CPU path, one 326 MB file instead of about 1.6 GB, and timings asserted equal to torch's by the export script. B is the fallback if the file fails the raw duration check or the Captain rejects how it sounds. D0 and D2's numeric ratio passed before the build. The Captain's D2 listen is pending and gates neither the build, the PR nor the merge, only his own opt-in and the later default flip (contract 12.4).
- *D1b.* The new model is an installer opt-in, and no default changes: a default naming a file the operator has not fetched would drop his Kokoro voice to the browser voice on the next pull. Flipping the `model_path` default is a later slice, after the Captain accepts the sound.
- *D2.* Timings travel as the raw file (`TTSResult.timing`), and frames are made in the route. A backend-side `visemes` field would import `avatars` from `audio`, which `rhubarb_backend` already imports: a cycle. The lip-sync choice belongs to the route.
- *D3.* Zero added pauses, and only on a model with timings, so a one-batch sentence keeps S1's pacing. Zero also drops the batch-join silence on requests over 510 phonemes; a later slice may opt in to the library's pauses.
- *D4.* The file is checked against the WAV (rate, sample count, bounds, order, at most 4096 entries); a refusal logs one WARNING and the sentence is served as `rhubarb`. `/api/avatars/lipsync` is unchanged.
- *Reversal.* Set the operator's `tts.kokoro.model_path` and `lipsync.backend` back to their previous values (S1's model and behaviour exactly). Deleting them is not the same: an absent `lipsync.backend` is `heuristic`, and an absent `model_path` is the default folder's file. Or revert the three commits. No persisted format changes.

```

## 7. New files

### 7.1 `tests/fixtures/fake_kokoro_worker.py` (M1; replaces the file)

```python
"""AD-738g (#1662): the real Kokoro worker loop with a stand-in engine, for tests.

Run exactly as the service runs the real worker: ``python -I <this file> --model M --voices V
--threads N --default-voice D``. Only the engine is fake: ``scripts/kokoro_worker.py``'s own
``main`` parses the arguments, moves library prints off stdout, reads each JSON line, picks
the voice and language, writes the WAV and prints the path. The fake engine has no model, so
``--model`` names a file where it appends one JSON line per call (text, voice, speed, lang and
this process's pid). Nothing here needs kokoro-onnx; numpy is a ProbOS dependency.

AD-738g S3a: a ``--model`` file whose name ends ``.timed.jsonl`` makes the engine report timings
(``has_timings``), as the ``model-files-v1.1`` export does: ``FAKE_PHONEMES`` spread evenly over
the audio. Its calls also record ``method``, ``sentence_pause`` and ``clause_pause``. The text
``NOTIMINGS`` returns no timings, and ``BADTIMING`` ends the last one a second past the audio.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

WORKER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "kokoro_worker.py"
VOICES: tuple[str, ...] = ("af_heart", "af_bella", "bf_emma", "bm_fable", "am_liam")
RATE = 24000
#: The symbols a timed fake speaks for any text: espeak-style IPA for "hello" (frames kk, E, nn, oh, ou).
FAKE_PHONEMES = "h\u0259l\u02c8o\u028a"


def load_worker() -> Any:
    """``scripts/kokoro_worker.py`` as a module, loaded by path (``-I`` puts no script directory on ``sys.path``)."""
    spec = importlib.util.spec_from_file_location("kokoro_worker", WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FakeTiming:
    """kokoro-onnx 0.6.1's ``Timing`` (``sliding.py``): one spoken symbol and its span in seconds."""

    phoneme: str
    start: float
    end: float


class FakeEngine:
    """kokoro-onnx 0.6.1's checks, measured 2026-11-27: an unknown voice, a speed outside [0.5, 2.0]
    and a text with no phonemes raise ``ValueError``. A voice's audio is 0.05 s per catalogue
    position (``af_heart`` 0.05 s, ``bm_fable`` 0.2 s), so a WAV's length shows which voice spoke."""

    def __init__(self, record: Path | None = None, voices: tuple[str, ...] = VOICES, timed: bool = False) -> None:
        self.record = record
        self.voices = voices
        self.calls: list[dict[str, Any]] = []
        self.has_timings = timed

    def get_voices(self) -> list[str]:
        return list(self.voices)

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]:
        return self._speak(text, voice, speed, lang)

    def create_timed(
        self, text: str, voice: str, speed: float, lang: str, sentence_pause: float = 0.25, clause_pause: float = 0.1,
    ) -> tuple[Any, int, list[FakeTiming]]:
        samples, rate = self._speak(
            text, voice, speed, lang,
            method="create_timed", sentence_pause=sentence_pause, clause_pause=clause_pause,
        )
        if text == "NOTIMINGS":
            return samples, rate, []
        seconds = len(samples) / rate
        step = seconds / len(FAKE_PHONEMES)
        timings = [FakeTiming(p, i * step, (i + 1) * step) for i, p in enumerate(FAKE_PHONEMES)]
        if text == "BADTIMING":
            timings[-1] = FakeTiming(timings[-1].phoneme, timings[-1].start, seconds + 1.0)
        return samples, rate, timings

    def _speak(self, text: str, voice: str, speed: float, lang: str, **extra: Any) -> tuple[Any, int]:
        call = {"text": text, "voice": voice, "speed": speed, "lang": lang, "pid": os.getpid(), **extra}
        self.calls.append(call)
        if self.record is not None:
            with self.record.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(call) + "\n")
        if voice not in self.voices:
            raise ValueError(f"Voice {voice} not found in available voices")
        if not 0.5 <= speed <= 2.0:
            raise ValueError(f"Speed should be between 0.5 and 2.0, got {speed}")
        if not text.strip():
            raise ValueError(f"Nothing to synthesize, {text!r} produced no phonemes")
        if text == "CHATTER":
            print("library chatter on stdout")
        frames = int(RATE * 0.05 * (1 + self.voices.index(voice)))
        return np.full(frames, 0.25, dtype=np.float32), RATE


if __name__ == "__main__":
    worker = load_worker()
    sys.exit(worker.main(
        engine_factory=lambda args: FakeEngine(Path(args.model), timed=Path(args.model).name.endswith(".timed.jsonl")),
    ))
```

### 7.2 `tests/test_ad738g_s3a_timing_sidecar.py` (M1)

```python
"""AD-738g (#1662) S3a: the Kokoro worker's phoneme-timing file and the voice service that carries it.

The worker loop is the real ``scripts/kokoro_worker.py``; only its engine is a stand-in
(``tests/fixtures/fake_kokoro_worker.py``), in process or as a real ``python -I`` subprocess under
the real ``VoiceSynthesisService``. A record file named ``*.timed.jsonl`` makes the subprocess's
engine report timings, as the ``model-files-v1.1`` export does. Nothing here needs kokoro-onnx.
No assertion reads a clock.
"""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import os
import sys
import wave
from pathlib import Path

import pytest

from probos.audio.tts import KokoroBackend, TTSResult, kokoro_backend, resident
from probos.audio.tts.resident import (
    TIMING_MAX_BYTES,
    TIMING_SUFFIX,
    KokoroWorkerKey,
    PiperOutcome,
    PiperWorker,
    PiperWorkerKey,
    VoiceSynthesisService,
)
from probos.config import KokoroTTSConfig
from tests.fixtures.fake_kokoro_worker import FAKE_PHONEMES, VOICES, FakeEngine, load_worker
from tests.fixtures.fake_piper import FakePiperLauncher

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
_FIELDS = {"voice": "af_heart", "speed": 1.0}
_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
worker = load_worker()


def _line(request: dict) -> bytes:
    return json.dumps(request).encode("ascii") + b"\n"


def _nframes(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as handle:
        return handle.getnframes()


def _key(tmp_path: Path, *, timed: bool) -> tuple[KokoroWorkerKey, Path]:
    record = tmp_path / ("engine-calls.timed.jsonl" if timed else "engine-calls.jsonl")
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    key = KokoroWorkerKey(
        python=sys.executable, script=str(FAKE_WORKER), model=str(record), voices=str(voices),
        threads=1, default_voice="af_heart",
    )
    return key, record


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KokoroTTSConfig:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"\x00")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    return KokoroTTSConfig(python_path=sys.executable, model_path=str(model), voices_path=str(voices))


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


# --- the worker, in process -------------------------------------------------------------------


def test_w10_a_timed_engine_gets_no_added_pauses_and_the_timing_file_lands_beside_the_wav(tmp_path: Path) -> None:
    engine = FakeEngine(timed=True)
    out = tmp_path / "out.wav"
    stdout = io.BytesIO()
    request = {"text": "Hello.", "output_file": str(out), "voice": "af_heart", "speed": 1.0}

    code = worker.serve(engine, io.BytesIO(_line(request)), stdout, default_voice="af_heart", log=io.StringIO())

    assert code == 0
    assert stdout.getvalue() == str(out).encode("utf-8") + b"\n"
    assert engine.calls == [{
        "text": "Hello.", "voice": "af_heart", "speed": 1.0, "lang": "en-us", "pid": os.getpid(),
        "method": "create_timed", "sentence_pause": 0.0, "clause_pause": 0.0,
    }]
    timing = json.loads((tmp_path / ("out.wav" + TIMING_SUFFIX)).read_text(encoding="ascii"))
    assert list(timing) == ["v", "rate", "samples", "timings"]
    assert (timing["v"], timing["rate"], timing["samples"]) == (1, 24000, _nframes(out.read_bytes()))
    assert [entry["p"] for entry in timing["timings"]] == list(FAKE_PHONEMES)
    assert all(list(entry) == ["p", "s", "e"] for entry in timing["timings"])
    assert timing["timings"][-1]["e"] == pytest.approx(timing["samples"] / 24000)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav", "out.wav" + TIMING_SUFFIX]


def test_w11_an_engine_without_timings_is_called_exactly_as_in_s1_and_writes_no_timing_file(tmp_path: Path) -> None:
    engine = FakeEngine()
    out = tmp_path / "out.wav"
    request = {"text": "Hello.", "output_file": str(out), "voice": "af_heart", "speed": 1.0}

    worker.serve(engine, io.BytesIO(_line(request)), io.BytesIO(), default_voice="af_heart", log=io.StringIO())

    assert engine.calls == [{"text": "Hello.", "voice": "af_heart", "speed": 1.0, "lang": "en-us", "pid": os.getpid()}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav"]


def test_w12_a_timed_engine_that_returns_no_timings_writes_no_timing_file(tmp_path: Path) -> None:
    engine = FakeEngine(timed=True)
    out = tmp_path / "out.wav"
    log = io.StringIO()

    assert worker.speak(engine, frozenset(VOICES), "af_heart", {"text": "NOTIMINGS", "output_file": str(out)}, log)

    assert [(c.get("method"), c.get("sentence_pause"), c.get("clause_pause")) for c in engine.calls] == [("create_timed", 0.0, 0.0)]

    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav"]
    assert log.getvalue() == ""


def test_w13_a_timing_file_that_cannot_be_written_keeps_the_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _disk_full(path, timings, rate, samples):
        raise OSError("disk full")

    monkeypatch.setattr(worker, "write_timing", _disk_full)
    out = tmp_path / "out.wav"
    log = io.StringIO()

    assert worker.speak(FakeEngine(timed=True), frozenset(VOICES), "af_heart", {"text": "Hello.", "output_file": str(out)}, log) is True

    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.wav"]
    assert "AD-738g: no timing file for 6 chars in af_heart: OSError: disk full" in log.getvalue()


def test_w15_an_interrupted_timing_write_leaves_neither_the_file_nor_a_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_write_bytes = Path.write_bytes

    def _half(self, data):
        real_write_bytes(self, data[: len(data) // 2])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", _half)
    timings = [dataclasses.make_dataclass("T", ["phoneme", "start", "end"])("m", 0.0, 0.05)]

    with pytest.raises(OSError, match="disk full"):
        worker.write_timing(tmp_path / "out.wav", timings, 24000, 1200)

    assert list(tmp_path.iterdir()) == []


# --- the resident service ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r8_the_service_returns_a_timed_workers_file_with_its_wav_and_leaves_neither(service, tmp_path: Path) -> None:
    key, record = _key(tmp_path, timed=True)

    outcome = await service.synthesize_outcome(key, "Good evening, Captain.", 30.0, fields=_FIELDS)

    assert outcome is not None and outcome.reason == "ok" and outcome.audio is not None
    assert outcome.timing is not None
    timing = json.loads(outcome.timing.decode("ascii"))
    assert timing["samples"] == _nframes(outcome.audio)
    assert [entry["p"] for entry in timing["timings"]] == list(FAKE_PHONEMES)
    assert _calls(record)[0]["method"] == "create_timed"
    # The worker's private directory holds only its stderr log once the request returns.
    directory = service._resident[key]._dir
    assert directory is not None and sorted(p.name for p in directory.iterdir()) == ["stderr.log"]


@pytest.mark.asyncio
async def test_r9_an_untimed_worker_gives_no_timing_and_synthesize_still_returns_bytes(service, tmp_path: Path) -> None:
    key, record = _key(tmp_path, timed=False)

    outcome = await service.synthesize_outcome(key, "Hello.", 30.0, fields=_FIELDS)
    wav = await service.synthesize(key, "Hello.", 30.0, fields=_FIELDS)

    assert outcome is not None and outcome.timing is None
    assert isinstance(wav, bytes) and wav[:4] == b"RIFF"
    assert all("method" not in call for call in _calls(record))


def test_r10_the_timing_file_is_read_up_to_its_cap(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    wav = tmp_path / "a.wav"
    beside = tmp_path / ("a.wav" + TIMING_SUFFIX)

    assert PiperWorker._read_timing(wav) is None
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []

    beside.write_bytes(b"x" * TIMING_MAX_BYTES)
    assert PiperWorker._read_timing(wav) == b"x" * TIMING_MAX_BYTES

    beside.write_bytes(b"x" * (TIMING_MAX_BYTES + 1))
    assert PiperWorker._read_timing(wav) is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


@pytest.mark.asyncio
async def test_r11_only_a_kokoro_key_carries_timings_and_piper_never_reads_a_file(
    service, monkeypatch: pytest.MonkeyPatch,
) -> None:
    piper = PiperWorkerKey(binary="piper", model="m.onnx", noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35)
    kokoro = KokoroWorkerKey(python="py", script="w.py", model="m.onnx", voices="v.bin", threads=4, default_voice="af_heart")
    assert piper.timing_sidecar is False
    assert kokoro.timing_sidecar is True

    reads: list[Path] = []
    monkeypatch.setattr(PiperWorker, "_read_timing", staticmethod(lambda wav: reads.append(wav)))
    monkeypatch.setattr(resident.subprocess, "Popen", FakePiperLauncher("ok", wav=_WAV))

    assert await service.synthesize(piper, "Hello.", 5.0) == _WAV
    assert reads == []


# --- the backend ------------------------------------------------------------------------------


class _TimedService:
    def __init__(self, timing: bytes | None) -> None:
        self.timing = timing

    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        return PiperOutcome(b"RIFF", "ok", timing=self.timing)


@pytest.mark.asyncio
async def test_b9_the_backend_hands_the_outcomes_timing_to_its_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _installed(tmp_path, monkeypatch)

    timed = await KokoroBackend(cfg, service=_TimedService(b'{"v":1}')).synthesize("Hello.")
    plain = await KokoroBackend(cfg, service=_TimedService(None)).synthesize("Hello.")

    assert timed == TTSResult(audio_bytes=b"RIFF", mime="audio/wav", timing=b'{"v":1}')
    assert plain == TTSResult(audio_bytes=b"RIFF", mime="audio/wav")


def test_b10_tts_result_gains_one_trailing_optional_field() -> None:
    assert [field.name for field in dataclasses.fields(TTSResult)] == ["audio_bytes", "mime", "timing"]
    assert TTSResult(b"x", "audio/wav").timing is None
    assert [field.name for field in dataclasses.fields(PiperOutcome)][-1] == "timing"
    assert PiperOutcome(b"x", "ok").timing is None
```
(`FakePiperLauncher("ok", wav=...)` and `resident.subprocess.Popen` follow `tests/test_ad738g_kokoro_voice.py`:82-88. `service._resident` and `PiperWorker._read_timing` are private names, read only in these tests.)

### 7.3 `src/probos/avatars/phoneme_visemes.py` (M2)

```python
"""AD-738g (#1662) S3a: lip-sync frames from the Kokoro worker's phoneme timings.

The worker (``scripts/kokoro_worker.py``) writes ``<wav>.timing.json`` when its model reports
durations (the kokoro-onnx ``model-files-v1.1`` export): one entry per spoken symbol,
``{"p": symbol, "s": start, "e": end}`` in seconds from the start of the WAV. kokoro-onnx 0.6.1
rescales the model's durations to the real audio and moves them with the head trim, so the spans
follow the audio. The symbols are espeak-ng IPA filtered to the package's 114-symbol vocabulary
(``kokoro_onnx/config.json``), so a diphthong is already two symbols.

``frames_from_timing`` checks the file against the WAV and maps it to the Oculus 15-set
(``rhubarb_backend.OculusViseme``). A file that fails a check gives ``None`` after one WARNING,
and the route serves that sentence as ``rhubarb``. Never raises.

License posture: standard library only, plus ``VisemeFrame``. The timing file is data (symbols
and numbers); nothing from the worker's venv is imported.
"""

from __future__ import annotations

import io
import json
import logging
import math
import struct
import wave
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from probos.avatars.rhubarb_backend import VisemeFrame

logger = logging.getLogger(__name__)

#: The timing file's format version (``scripts/kokoro_worker.py`` ``TIMING_VERSION``).
TIMING_VERSION = 1
#: At most this many timed symbols in one file (about eight 510-symbol batches); a longer file is refused.
MAX_TIMINGS = 4096
#: One Kokoro duration frame (600 samples at 24 kHz); a time may run at most one frame past the audio.
FRAME_SAMPLES = 600
#: Seconds added to every frame's start. Zero until measurement D4 of the S3a contract tunes it once.
TIMING_OFFSET_SECONDS = 0.0
#: A gap up to this long between spans (the worker rounds times to 6 decimals) is closed, not shown as sil.
MIN_GAP_SECONDS = 0.001

# Oculus key -> the vocabulary symbols shown with it; None: the symbol takes the key before it (stress,
# length, aspiration, palatalisation, nasalisation and intonation marks). The renderer weights only the
# vowels aa, ih, ou, E and oh (rhubarb_backend.py); the consonant rows are for completeness. The misaki
# letters A I O Q S T W Y are in the vocabulary but espeak never emits them; each has its nearest key.
_GROUPS: tuple[tuple[str | None, str], ...] = (
    ("sil", ";:,.!?\u2014\u2026\"()\u201c\u201d "),
    (None, "\u02c8\u02cc\u02d0\u02b0\u02b2\u0303\u2193\u2192\u2197\u2198\u1d5d"),
    ("PP", "pbm\u03b2\u0278"),
    ("FF", "fv\u028b"),
    ("TH", "\u03b8\u00f0"),
    ("DD", "td\u0256\u0288\u027e\u0294T"),
    ("kk", "kc\u0261\u025fqx\u0263\u03c7\u0281\u0270h\u00e7"),
    ("CH", "\u0283\u0292\u02a7\u02a4\u02a8\u02a5\u0255\u029d\u0282"),
    ("SS", "sz\u02a6\u02a3S"),
    ("nn", "nl\u014b\u0272\u0273\u0274\u028e"),
    ("RR", "r\u0279\u027b\u027d\u025a\uab67"),
    ("aa", "a\u0251\u0250\u00e6\u028cIW"),
    ("E", "e\u025b\u0259\u1d4a\u025cA"),
    ("ih", "i\u026a\u0268\u1d7b\u026fj"),
    ("oh", "o\u0254\u0252\u0264\u00f8\u0153OQY"),
    ("ou", "u\u028aw\u0265y"),
)

#: Every vocabulary symbol to its Oculus key, or ``None`` for a mark that takes the key before it.
PHONEME_VISEMES: Mapping[str, str | None] = MappingProxyType(
    {symbol: key for key, symbols in _GROUPS for symbol in symbols}
)


def frames_from_timing(timing: bytes, wav: bytes) -> tuple[VisemeFrame, ...] | None:
    """Frames covering the whole WAV from its timing file, or ``None`` after one WARNING. Never raises.

    Gaps between spans (the lead-in, the tail, long end pauses) and space and punctuation are ``sil``;
    zero-length spans are dropped; an unknown symbol is ``sil`` and counted in one INFO line; equal
    neighbours merge.
    """
    checked = _checked_spans(timing, wav)
    if checked is None:
        return None
    spans, end_of_audio = checked
    frames: list[VisemeFrame] = []
    previous, cursor, unknown = "sil", 0.0, 0
    for symbol, start, end in spans:
        start = max(start, cursor)
        if end <= start:
            continue  # zero length: the head trim clips a span to nothing (kokoro_onnx __init__.py)
        if symbol in PHONEME_VISEMES:
            mapped = PHONEME_VISEMES[symbol]
            key = previous if mapped is None else mapped
        else:
            key, unknown = "sil", unknown + 1
        if start - cursor > MIN_GAP_SECONDS:
            _add(frames, cursor, start, "sil")
        else:
            start = cursor  # a rounding gap: the frames stay contiguous
        _add(frames, start, end, key)
        previous, cursor = key, end
    if end_of_audio - cursor > MIN_GAP_SECONDS:
        _add(frames, cursor, end_of_audio, "sil")
    elif frames and end_of_audio > cursor:
        frames[-1] = VisemeFrame(frames[-1].time, end_of_audio - frames[-1].time, frames[-1].viseme)
    if unknown:
        logger.info("AD-738g: %d timed symbol(s) outside the viseme table were shown as sil", unknown)
    return tuple(
        VisemeFrame(round(max(0.0, f.time + TIMING_OFFSET_SECONDS), 4), round(f.duration, 4), f.viseme)
        for f in frames
    )


def _add(frames: list[VisemeFrame], start: float, end: float, key: str) -> None:
    """Append ``[start, end)`` as ``key``, merging it into the frame before when that has the same key."""
    if frames and frames[-1].viseme == key:
        frames[-1] = VisemeFrame(frames[-1].time, end - frames[-1].time, key)
    else:
        frames.append(VisemeFrame(start, end - start, key))


def _checked_spans(timing: bytes, wav: bytes) -> tuple[list[tuple[str, float, float]], float] | None:
    """The file's spans and the WAV's length in seconds, or ``None`` after one WARNING naming the failed check."""
    try:
        body = json.loads(timing.decode("ascii"))
        with wave.open(io.BytesIO(wav), "rb") as handle:
            rate, samples = handle.getframerate(), handle.getnframes()
    except (ValueError, EOFError, wave.Error, struct.error, RecursionError) as exc:  # RecursionError: nested too deep
        return _refused(f"unreadable: {type(exc).__name__}")
    if not isinstance(body, dict) or body.get("v") != TIMING_VERSION:
        return _refused("not a version-1 timing object")
    if not _is_int(body.get("rate")) or rate <= 0 or body["rate"] != rate:
        return _refused(f"rate {body.get('rate')!r} is not the WAV's {rate}")
    if not _is_int(body.get("samples")) or body["samples"] != samples:
        return _refused(f"samples {body.get('samples')!r} is not the WAV's {samples}")
    entries = body.get("timings")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_TIMINGS:
        return _refused(f"timings is not a list of 1 to {MAX_TIMINGS} entries")
    limit = (samples + FRAME_SAMPLES) / rate
    spans: list[tuple[str, float, float]] = []
    last_start = 0.0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return _refused(f"entry {index} is not an object")
        symbol, start, end = entry.get("p"), entry.get("s"), entry.get("e")
        if not (isinstance(symbol, str) and len(symbol) == 1 and _is_number(start) and _is_number(end)):
            return _refused(f"entry {index} is not one symbol with two finite numbers")
        if not 0.0 <= start <= end <= limit:
            return _refused(f"entry {index} spans {start}..{end}, outside 0..{limit:.3f} s")
        if start < last_start:
            return _refused(f"entry {index} starts before entry {index - 1}")
        spans.append((symbol, float(start), float(end)))
        last_start = start
    return spans, samples / rate


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """A JSON int or float with a finite float value; an int past float range has none (``OverflowError``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _refused(reason: str) -> None:
    logger.warning("AD-738g: the synthesizer's timings were refused (%s); this sentence's lip-sync uses rhubarb", reason)
    return None
```

### 7.4 `tests/test_ad738g_s3a_synthesizer_lipsync.py` (M2)

```python
"""AD-738g (#1662) S3a: lip-sync frames from the synthesizer's timings, behind lipsync.backend "synthesizer".

Real table, check, route, store, config and registry. The route cases run the real
``scripts/kokoro_worker.py`` loop with the stand-in engine of ``tests/fixtures/fake_kokoro_worker.py``
as a real ``python -I`` subprocess under the real ``VoiceSynthesisService``; a record file named
``*.timed.jsonl`` is a model that reports durations. Rhubarb is a stub that records each call.
No assertion reads a clock.
"""

from __future__ import annotations

import ast
import io
import json
import logging
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import kokoro_backend, resident
from probos.audio.tts.resident import VoiceSynthesisService
from probos.avatars import phoneme_visemes
from probos.avatars.phoneme_visemes import PHONEME_VISEMES, frames_from_timing
from probos.avatars.rhubarb_backend import OculusViseme, VisemeFrame
from probos.config import AttachmentsConfig, KokoroTTSConfig, LipSyncConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.settings.section_registry import get_section
from tests.fixtures.fake_kokoro_worker import load_worker

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
RATE = 24000
_RHUBARB = [{"time": 0.0, "duration": 0.1, "viseme": "aa"}]

#: kokoro-onnx 0.6.1's vocabulary (kokoro_onnx/config.json, "vocab", in file order).
VOCAB = (
    ";:,.!?\u2014\u2026\"()\u201c\u201d \u0303\u02a3\u02a5\u02a6\u02a8\u1d5d\uab67AIOQSTWY\u1d4a"
    "abcdefhijklmnopqrstuvwxyz"
    "\u0251\u0250\u0252\u00e6\u03b2\u0254\u0255\u00e7\u0256\u00f0\u02a4\u0259\u025a\u025b\u025c\u025f\u0261\u0265"
    "\u0268\u026a\u029d\u026f\u0270\u014b\u0273\u0272\u0274\u00f8\u0278\u03b8\u0153\u0279\u027e\u027b\u0281\u027d"
    "\u0282\u0283\u0288\u02a7\u028a\u028b\u028c\u0263\u0264\u03c7\u028e\u0292\u0294\u02c8\u02cc\u02d0\u02b0\u02b2"
    "\u2193\u2192\u2197\u2198\u1d7b"
)

#: The key each symbol must have, written per symbol in VOCAB's order (None: takes the key before it).
EXPECTED: dict[str, str | None] = {
    ";": "sil", ":": "sil", ",": "sil", ".": "sil", "!": "sil", "?": "sil", "\u2014": "sil", "\u2026": "sil",
    '"': "sil", "(": "sil", ")": "sil", "\u201c": "sil", "\u201d": "sil", " ": "sil",
    "\u0303": None, "\u02a3": "SS", "\u02a5": "CH", "\u02a6": "SS", "\u02a8": "CH", "\u1d5d": None, "\uab67": "RR",
    "A": "E", "I": "aa", "O": "oh", "Q": "oh", "S": "SS", "T": "DD", "W": "aa", "Y": "oh", "\u1d4a": "E",
    "a": "aa", "b": "PP", "c": "kk", "d": "DD", "e": "E", "f": "FF", "h": "kk", "i": "ih", "j": "ih",
    "k": "kk", "l": "nn", "m": "PP", "n": "nn", "o": "oh", "p": "PP", "q": "kk", "r": "RR", "s": "SS",
    "t": "DD", "u": "ou", "v": "FF", "w": "ou", "x": "kk", "y": "ou", "z": "SS",
    "\u0251": "aa", "\u0250": "aa", "\u0252": "oh", "\u00e6": "aa", "\u03b2": "PP", "\u0254": "oh", "\u0255": "CH",
    "\u00e7": "kk", "\u0256": "DD", "\u00f0": "TH", "\u02a4": "CH", "\u0259": "E", "\u025a": "RR", "\u025b": "E",
    "\u025c": "E", "\u025f": "kk", "\u0261": "kk", "\u0265": "ou", "\u0268": "ih", "\u026a": "ih", "\u029d": "CH",
    "\u026f": "ih", "\u0270": "kk", "\u014b": "nn", "\u0273": "nn", "\u0272": "nn", "\u0274": "nn", "\u00f8": "oh",
    "\u0278": "PP", "\u03b8": "TH", "\u0153": "oh", "\u0279": "RR", "\u027e": "DD", "\u027b": "RR", "\u0281": "kk",
    "\u027d": "RR", "\u0282": "CH", "\u0283": "CH", "\u0288": "DD", "\u02a7": "CH", "\u028a": "ou", "\u028b": "FF",
    "\u028c": "aa", "\u0263": "kk", "\u0264": "oh", "\u03c7": "kk", "\u028e": "nn", "\u0292": "CH", "\u0294": "DD",
    "\u02c8": None, "\u02cc": None, "\u02d0": None, "\u02b0": None, "\u02b2": None,
    "\u2193": None, "\u2192": None, "\u2197": None, "\u2198": None, "\u1d7b": "ih",
}


def _wav(samples: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"\x00\x00" * samples)
    return buffer.getvalue()


def _timing(spans, samples: int, **override) -> bytes:
    body = {"v": 1, "rate": RATE, "samples": samples, "timings": [{"p": p, "s": s, "e": e} for p, s, e in spans]}
    body.update(override)
    return json.dumps(body).encode("ascii")


def _shape(frames) -> list[tuple[str, float, float]]:
    return [(f.viseme, round(f.time, 4), round(f.duration, 4)) for f in frames]


_GOOD = [("m", 0.0, 0.1), ("\u0251", 0.1, 0.5)]
_HALF = _wav(12000)  # 0.5 s
_DEEP = b"[" * 100_000 + b"]" * 100_000  # 200,000 B, under TIMING_MAX_BYTES; deeper than any parser recursion limit
_HUGE = 10**400  # 401 digits: parses (under the 4,300-digit limit) but has no float value


# --- the table --------------------------------------------------------------------------------


def test_v1_the_table_covers_exactly_the_114_symbol_vocabulary_once() -> None:
    assert len(VOCAB) == len(set(VOCAB)) == 114
    assert set(PHONEME_VISEMES) == set(VOCAB)
    assert sum(len(symbols) for _key, symbols in phoneme_visemes._GROUPS) == 114  # no symbol in two groups


@pytest.mark.parametrize("symbol", list(VOCAB), ids=[f"U+{ord(c):04X}" for c in VOCAB])
def test_v2_each_vocabulary_symbol_has_its_key(symbol: str) -> None:
    assert PHONEME_VISEMES[symbol] == EXPECTED[symbol]
    assert EXPECTED[symbol] is None or EXPECTED[symbol] in get_args(OculusViseme)


def test_v3_no_module_under_audio_imports_the_avatar_package() -> None:
    # Decision 3: avatars/rhubarb_backend.py imports probos.audio.tts.resident; the reverse edge would be a cycle.
    offenders = []
    for path in sorted((_REPO / "src" / "probos" / "audio").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_bytes())):
            names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            )
            if any(name == "probos.avatars" or name.startswith("probos.avatars.") for name in names):
                offenders.append(path.relative_to(_REPO).as_posix())
    assert offenders == []


def test_w14_the_worker_and_probos_agree_on_the_file_name_and_version() -> None:
    worker = load_worker()
    assert worker.TIMING_SUFFIX == resident.TIMING_SUFFIX == ".timing.json"
    assert worker.TIMING_VERSION == phoneme_visemes.TIMING_VERSION == 1


# --- the frames -------------------------------------------------------------------------------


def test_f1_gaps_and_space_are_sil_equal_neighbours_merge_and_the_frames_reach_the_end() -> None:
    spans = [("h", 0.1, 0.2), ("\u0251", 0.2, 0.25), ("a", 0.25, 0.3), (" ", 0.3, 0.35), ("m", 0.35, 0.4)]

    frames = frames_from_timing(_timing(spans, 12000), _HALF)

    assert _shape(frames) == [
        ("sil", 0.0, 0.1), ("kk", 0.1, 0.1), ("aa", 0.2, 0.1), ("sil", 0.3, 0.05), ("PP", 0.35, 0.05), ("sil", 0.4, 0.1),
    ]
    assert phoneme_visemes.TIMING_OFFSET_SECONDS == 0.0


def test_f2_a_mark_takes_the_key_before_it_and_a_leading_mark_is_sil() -> None:
    assert _shape(frames_from_timing(_timing([("\u0251", 0.0, 0.2), ("\u02d0", 0.2, 0.5)], 12000), _HALF)) == [("aa", 0.0, 0.5)]
    assert _shape(frames_from_timing(_timing([("\u02c8", 0.0, 0.1), ("m", 0.1, 0.5)], 12000), _HALF)) == [
        ("sil", 0.0, 0.1), ("PP", 0.1, 0.4),
    ]


def test_f3_a_zero_length_span_is_dropped() -> None:
    frames = frames_from_timing(_timing([("m", 0.0, 0.0), ("\u0251", 0.0, 0.5)], 12000), _HALF)

    assert _shape(frames) == [("aa", 0.0, 0.5)]


def test_f4_an_unknown_symbol_is_sil_and_counted_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="probos.avatars.phoneme_visemes")
    assert "g" not in PHONEME_VISEMES  # ASCII g is not in the vocabulary (U+0261 is)

    frames = frames_from_timing(_timing([("m", 0.0, 0.2), ("g", 0.2, 0.3), ("g", 0.3, 0.5)], 12000), _HALF)

    assert _shape(frames) == [("PP", 0.0, 0.2), ("sil", 0.2, 0.3)]
    assert [r.getMessage() for r in caplog.records] == [
        "AD-738g: 2 timed symbol(s) outside the viseme table were shown as sil",
    ]


def test_f5_frames_tile_the_audio_without_gaps_or_overlaps() -> None:
    step = 0.5 / 6
    spans = [(p, i * step, (i + 1) * step) for i, p in enumerate("h\u0259l\u02c8o\u028a")]

    frames = frames_from_timing(_timing(spans, 12000), _HALF)

    assert [f.viseme for f in frames] == ["kk", "E", "nn", "oh", "ou"]
    assert frames[0].time == 0.0
    for before, after in zip(frames, frames[1:]):
        assert after.time == pytest.approx(before.time + before.duration, abs=2e-4)
    assert frames[-1].time + frames[-1].duration == pytest.approx(0.5, abs=2e-4)


def test_f6_a_rounding_gap_is_closed_not_shown_as_sil() -> None:
    spans = [("m", 0.0, 0.1000004), ("ɑ", 0.1000009, 0.4999996)]

    assert _shape(frames_from_timing(_timing(spans, 12000), _HALF)) == [("PP", 0.0, 0.1), ("aa", 0.1, 0.4)]


# --- the check --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timing", "wav"),
    [
        (b"\xff", _HALF),
        (b"{", _HALF),
        (b"[1]", _HALF),
        (_timing(_GOOD, 12000), b"RIFF"),
        (_timing(_GOOD, 12000, v=2), _HALF),
        (_timing(_GOOD, 12000, rate=22050), _HALF),
        (_timing(_GOOD, 12000, rate=True), _HALF),
        (_timing(_GOOD, 11999), _HALF),
        (_timing(_GOOD, 12000.0), _HALF),
        (_timing([], 12000), _HALF),
        (_timing([("m", 0.0, 0.0)] * 4097, 12000), _HALF),
        (_timing(_GOOD, 12000, timings="x"), _HALF),
        (_timing(_GOOD, 12000, timings=[1]), _HALF),
        (_timing([("mm", 0.0, 0.1)], 12000), _HALF),
        (_timing(_GOOD, 12000, timings=[{"p": 1, "s": 0.0, "e": 0.1}]), _HALF),
        (_timing([("m", 0.2, 0.1)], 12000), _HALF),
        (_timing([("m", -0.1, 0.1)], 12000), _HALF),
        (_timing([("m", 0.0, 0.526)], 12000), _HALF),
        (_timing([("m", 0.2, 0.3), ("a", 0.1, 0.4)], 12000), _HALF),
        (_timing([("m", True, 0.1)], 12000), _HALF),
        (_timing([("m", "0", 0.1)], 12000), _HALF),
        (_timing([("m", float("nan"), 0.1)], 12000), _HALF),
        (_DEEP, _HALF),
        (_timing([("m", _HUGE, 0.1)], 12000), _HALF),
    ],
    ids=[
        "not-utf8", "truncated-json", "not-an-object", "not-a-wav", "version-2", "rate-22050", "rate-bool",
        "samples-11999", "samples-float", "no-timings", "4097-timings", "timings-not-a-list", "entry-not-an-object",
        "symbol-two-chars", "symbol-not-a-string", "end-before-start", "negative-start", "past-the-audio",
        "start-goes-back", "time-bool", "time-string", "time-nan", "nested-past-the-recursion-limit", "integer-past-float-range",
    ],
)
def test_x1_a_file_that_fails_a_check_is_refused_with_one_warning(
    timing: bytes, wav: bytes, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    assert frames_from_timing(timing, wav) is None

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].startswith("AD-738g: the synthesizer's timings were refused (")


def test_x2_the_boundaries_are_accepted() -> None:
    assert frames_from_timing(_timing([("m", 0.0, 0.525)], 12000), _HALF) is not None  # one frame past the audio
    assert frames_from_timing(_timing([("m", 0, 0.1)], 12000), _HALF) is not None  # integers are numbers
    assert _shape(frames_from_timing(_timing([("m", 0.0, 0.0)] * 4096, 12000), _HALF)) == [("sil", 0.0, 0.5)]


# --- config and registry ----------------------------------------------------------------------


def test_c5_synthesizer_is_an_opt_in_backend_and_the_registry_offers_it() -> None:
    assert LipSyncConfig().backend == "heuristic"
    assert LipSyncConfig(backend="synthesizer").backend == "synthesizer"
    section = get_section("voice")
    assert section is not None
    field = next(f for f in section.fields if f.field_id == "lipsync.backend")
    assert field.enum_values == get_args(LipSyncConfig.model_fields["backend"].annotation) == (
        "heuristic", "rhubarb", "synthesizer",
    )


def test_c6_the_default_model_is_still_s1s_export_and_the_timed_one_is_an_opt_in() -> None:
    # S3a changes no default: the duration-reporting export is fetched only by kokoro-fetch.ps1 -TimedModel, and an
    # operator who has not fetched it must keep his S1 voice after a pull. Flipping this is its own slice (contract 10).
    assert KokoroTTSConfig().model_path == "tools/kokoro/kokoro-v1.0.onnx"
    assert TTSConfig().kokoro.model_path == "tools/kokoro/kokoro-v1.0.onnx"


# --- the route, through the real worker loop --------------------------------------------------


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=AttachmentsConfig(attachments_dir=str(target)), lipsync=LipSyncConfig(), tts=TTSConfig()),
        voice_synthesis=service,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http, rt
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


def _kokoro(rt, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, timed: bool, lipsync: str | None) -> Path:
    record = tmp_path / ("calls.timed.jsonl" if timed else "calls.jsonl")
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    rt.config.tts = TTSConfig(
        backend="kokoro",
        kokoro=KokoroTTSConfig(python_path=sys.executable, model_path=str(record), voices_path=str(voices)),
    )
    rt.config.lipsync = LipSyncConfig() if lipsync is None else LipSyncConfig(backend=lipsync)
    return record


def _stub_rhubarb(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    async def _visemes(audio_path, **_kw):
        calls.append(Path(audio_path))
        return [VisemeFrame(time=0.0, duration=0.1, viseme="aa")]

    monkeypatch.setattr("probos.avatars.rhubarb_backend.generate_visemes", _visemes)
    return calls


def _records(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.asyncio
async def test_t4_the_default_heuristic_ignores_the_timings_and_runs_no_rhubarb(client, monkeypatch, tmp_path) -> None:
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync=None)
    calls = _stub_rhubarb(monkeypatch)

    for defer in (False, True):
        body = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": defer})).json()
        assert body["backend"] == "kokoro"
        assert body["visemes"] == [] and body["visemes_deferred"] is False

    assert calls == []


@pytest.mark.asyncio
async def test_t5_rhubarb_is_unchanged_when_the_worker_sends_timings(client, monkeypatch, tmp_path) -> None:
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="rhubarb")
    calls = _stub_rhubarb(monkeypatch)

    inline = (await http.post("/api/avatars/tts", json={"text": "Hello."})).json()
    deferred = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": True})).json()

    assert inline["visemes"] == _RHUBARB and inline["visemes_deferred"] is False
    assert deferred["visemes"] == [] and deferred["visemes_deferred"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_t6_synthesizer_sends_the_timed_frames_inline_and_runs_no_rhubarb(
    client, monkeypatch, tmp_path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.avatars")  # as tests/test_bf918_tts_latency.py:605
    http, rt = client
    record = _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)

    for defer in (False, True):
        body = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": defer})).json()
        assert body["visemes_deferred"] is False
        assert [f["viseme"] for f in body["visemes"]] == ["kk", "E", "nn", "oh", "ou"]
        assert body["visemes"][0]["time"] == 0.0
        last = body["visemes"][-1]
        assert last["time"] + last["duration"] == pytest.approx(body["duration_ms"] / 1000, abs=1e-3)

    assert calls == []
    assert all(r["sentence_pause"] == 0.0 and r["clause_pause"] == 0.0 for r in _records(record))
    assert "visemes=synthesizer" in caplog.text


@pytest.mark.asyncio
async def test_t7_synthesizer_on_a_model_without_timings_is_served_as_rhubarb_deferred_path_included(
    client, monkeypatch, tmp_path,
) -> None:
    http, rt = client
    record = _kokoro(rt, monkeypatch, tmp_path, timed=False, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)

    deferred = (await http.post("/api/avatars/tts", json={"text": "Hello.", "defer_visemes": True})).json()
    fetched = (await http.post("/api/avatars/lipsync", json={"attachment_id": deferred["audio_attachment_id"]})).json()
    inline = (await http.post("/api/avatars/tts", json={"text": "Hello."})).json()

    assert deferred["visemes"] == [] and deferred["visemes_deferred"] is True
    assert fetched == {"backend": "rhubarb", "frames": _RHUBARB}  # voice.ts accepts only backend "rhubarb"
    assert inline["visemes"] == _RHUBARB and inline["visemes_deferred"] is False
    assert len(calls) == 2
    assert all("method" not in r for r in _records(record))  # S1's create, S1's pauses


@pytest.mark.asyncio
async def test_t8_refused_timings_fall_back_to_rhubarb_with_one_warning(
    client, monkeypatch, tmp_path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)

    body = (await http.post("/api/avatars/tts", json={"text": "BADTIMING"})).json()

    assert body["visemes"] == _RHUBARB and body["visemes_deferred"] is False
    assert len(calls) == 1
    refused = [r for r in caplog.records if "the synthesizer's timings were refused" in r.getMessage()]
    assert len(refused) == 1 and refused[0].levelno == logging.WARNING


def _deep_timing(real):
    return lambda wav: _DEEP if real(wav) is not None else None


def _huge_timing(real):
    def _read(wav):
        data = real(wav)
        if data is None:
            return None
        body = json.loads(data)
        body["timings"][0]["s"] = _HUGE
        return json.dumps(body).encode("ascii")
    return _read


@pytest.mark.asyncio
@pytest.mark.parametrize("make", [_deep_timing, _huge_timing], ids=["nested-past-the-recursion-limit", "integer-past-float-range"])
async def test_t9_timings_past_the_parsers_limits_keep_the_audio_and_fall_back_to_rhubarb_with_one_warning(
    client, monkeypatch, tmp_path, caplog: pytest.LogCaptureFixture, make,
) -> None:
    caplog.set_level(logging.WARNING)
    http, rt = client
    _kokoro(rt, monkeypatch, tmp_path, timed=True, lipsync="synthesizer")
    calls = _stub_rhubarb(monkeypatch)
    monkeypatch.setattr(resident.PiperWorker, "_read_timing", staticmethod(make(resident.PiperWorker._read_timing)))

    response = await http.post("/api/avatars/tts", json={"text": "Hello."})

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "kokoro" and body["audio_attachment_id"] and body["duration_ms"] > 0
    assert body["visemes"] == _RHUBARB and body["visemes_deferred"] is False
    assert len(calls) == 1
    refused = [r for r in caplog.records if "the synthesizer's timings were refused" in r.getMessage()]
    assert len(refused) == 1 and refused[0].levelno == logging.WARNING
```

Rules for 7.4 (orchestrator dry build, 2026-11-27):
- A parametrization over large `bytes` must carry `ids`. Without them pytest builds each id from the whole `bytes` repr of `_HALF` (24 KB) and stores it in `PYTEST_CURRENT_TEST`, and Windows refuses an environment variable over 32,767 characters (`ValueError`, at setup and teardown); Linux has no such limit, so only the Windows gate would show it.
- `time` and `duration` are each rounded to four decimals from the raw values (7.3, the `VisemeFrame(round(...), round(...), ...)` line), so `F5`'s tolerance is `abs=2e-4`: the tiling check compares three independently rounded values (error at most 1.5e-4) and the end check two (at most 1e-4). The earlier `abs=1e-4` sat on the bound and failed (`0.4167 == 0.41659999999999997 +- 1.0e-4`).

## 8. Gates (the orchestrator runs them)

### 8.1 Oracle tree, before the Builder starts

- Count each SEARCH of section 6 at its turn: 1 each. The three new files (7.2, 7.3, 7.4) do not exist, and 7.1 does.
- A/B: on the base tree, 7.2 and 7.4 fail at collection (`TIMING_SUFFIX` and `phoneme_visemes` do not exist). On the candidate, all pass.

**Oracle and dry build of record (the orchestrator, 2026-11-27, local Windows).** On a `git archive` of `fae613df` (tree `490bdbb8`), the oracle found 39 SEARCH/REPLACE pairs in section 6, each matching exactly once at a line start, and the four files of section 7 were written. With D1 to D4 corrected (D1 the `samples-float` case of `test_x1`, D2 its `ids`, D3 `test_f5`'s `abs=2e-4`, D4 the facade `--update-baseline` of 6.11), the 8.2 lines gave: M1 `141 passed, 1 skipped`; M2 `587 passed`; M3 pytest line `458 passed, 1 skipped`; `tests/test_ad1152_agentic_correlation.py -k default_off` `3 passed`; the facade check `passed (names=311, owned=298, incidental=13, models=229, fields=1886, env rows=4)`. The Builder's runs should reproduce these counts on the same tree; a different count is a stop-and-report, not a re-count.

**Re-anchor of record (the orchestrator, 2026-11-28).** Batch head `55ae03eb` (tree `04e94e65`): the facade reports `fields=1887`, and `SystemConfig`'s `schema_sha256` differs from 6.11's informative value (PR #1873); 6.11's rule holds. After the round-1 repair, the M2 and M3 pytest lines each gain 4 cases and M1 gains none.

### 8.2 Focused checks on the candidate

The Builder runs its milestone's line; the orchestrator runs all of them once on the frozen candidate.
```text
M1: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_s3a_timing_sidecar.py tests/test_ad738g_kokoro_voice.py tests/test_ad738f_per_agent_voices.py tests/test_bf918_tts_latency.py tests/test_bf930_voice_path_timing.py tests/test_ad738_piper_tts.py tests/test_ad1346_admission_file_write_census.py -n 0 -q
M2: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_s3a_synthesizer_lipsync.py tests/test_ad738g_s3a_timing_sidecar.py tests/test_ad721b1_rhubarb_backend.py tests/test_bf918_tts_latency.py tests/test_bf918_tts_retention.py tests/test_bf930_voice_path_timing.py tests/test_bf930_speech_defers_idle_dream.py tests/test_ad738_piper_tts.py tests/test_ad1270e2c_experience_models.py tests/test_ad1270e1_config_facade.py tests/test_ad741_section_registry.py tests/test_ad741_config_api.py tests/test_ad826_voice_config.py -n 0 -q
M2: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1152_agentic_correlation.py -k default_off -n 0 -q
M2: the six commands of 6.11 (M2)
M3: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_kokoro_voice.py tests/test_ad738g_s3a_synthesizer_lipsync.py tests/test_ad1270e2c_experience_models.py tests/test_ad1270e1_config_facade.py -n 0 -q
M3: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1152_agentic_correlation.py -k default_off -n 0 -q
M3: the four commands of 6.11 (M3)
All: d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-738g-s3a
```
`-k default_off` selects `test_default_off_matches_pinned_base` and `test_default_off_golden_pins_only_descriptor_owner_platform` (`:569`, `:584`). S3a edits nothing in that file and changes no default, so it must stay green unchanged; it stays in the set because it hashes the whole default config dump (`:563`) and pins the Kokoro section (`:353-357`), so any default that moves by accident fails it, and the S1 batch's first canonical gate failed three of its tests because no focused set ran it. M3 changes no Python, so its pytest line is the guard that the default `model_path` and its pins did not move (`test_c6`, `test_ad738g_kokoro_voice.py`:647, `test_ad1270e2c_experience_models.py`:212). Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time on the frozen candidate, each file restored byte for byte)

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| S1 | worker: `if engine.has_timings:` | `if False:` | W10, W12, R8, T6 |
| S2 | worker: `sentence_pause=0.0, clause_pause=0.0,` | `sentence_pause=0.25, clause_pause=0.1,` | W10, T6 |
| S3 | worker: `samples, rate = engine.create(text, voice=voice, speed=speed, lang=lang_for(voice))` | `samples, rate, timings = engine.create_timed(text, voice=voice, speed=speed, lang=lang_for(voice), sentence_pause=0.0, clause_pause=0.0)` | W11, T7 (the untimed fake has no `create_timed` record shape) |
| S4 | worker: `if timings:` | `if True:` | W11, W12 (an empty timing file appears) |
| S5 | resident: `timing = self._read_timing(out) if self.key.timing_sidecar else None` | `timing = None` | R8, T6 |
| S6 | resident: the `leftovers = (out, ...)` line | `leftovers = (out,)` | R8 (the directory holds the timing file) |
| S7 | resident: `KokoroWorkerKey.timing_sidecar` returns `True` | returns `False` | R11, R8 |
| S8 | resident: `if len(data) > TIMING_MAX_BYTES:` | `if len(data) >= TIMING_MAX_BYTES:` | R10 |
| S9 | kokoro_backend: `timing=outcome.timing)` | `)` | B9, T6 |
| S10 | router: `lipsync_cfg.backend in ("rhubarb", "synthesizer")` | `lipsync_cfg.backend == "rhubarb"` | T6, T7, T8 |
| S11 | router: `if lipsync_cfg.backend == "synthesizer" and result.timing is not None:` | `if result.timing is not None:` | T5 |
| S12 | router: `if timed:` / `elif defer_visemes:` order | `if defer_visemes:` first, then `elif timed:` | T6 (the `defer=True` pass) |
| S13 | phoneme_visemes: `or body["samples"] != samples` | (removed) | X1 `samples 11999` |
| S14 | phoneme_visemes: `if start < last_start:` | `if False:` | X1 `a start goes back` |
| S15 | phoneme_visemes: `key = previous if mapped is None else mapped` | `key = "sil" if mapped is None else mapped` | F2 |
| S16 | phoneme_visemes: `continue  # zero length` | `pass` | F3 |
| S17 | phoneme_visemes: `_add(frames, cursor, start, "sil")` | (line removed, `pass`) | F1 |
| S17b | phoneme_visemes: `if start - cursor > MIN_GAP_SECONDS:` | `if start > cursor:` | F6 (a zero-length `sil` frame appears) |
| S18 | phoneme_visemes: `MAX_TIMINGS = 4096` | `MAX_TIMINGS = 4097` | X1 4097 entries |
| S19 | phoneme_visemes: `("aa", "a\u0251...` | `\u0251` moved to the `E` group | V2 `U+0251` |
| S20 | experience (unchanged by S3a): `model_path: str = "tools/kokoro/kokoro-v1.0.onnx"` | `"tools/kokoro/kokoro-v1.1.onnx"` (the default flip this slice does not make) | `test_c6`, `test_ad738g_kokoro_voice.py`:647, `test_ad1270e2c_experience_models.py`:212, `test_ad1152 -k default_off` |
| S21 | phoneme_visemes: `except (..., struct.error, RecursionError) as exc:` | `, RecursionError` removed | X1 `nested-past-the-recursion-limit`, T9 `nested-...` |
| S22 | phoneme_visemes: `except OverflowError:` | `except ZeroDivisionError:` | X1 `integer-past-float-range`, T9 `integer-...` |

S20 now guards the decision not to move the default, so it runs against a line S3a does not edit. The installer has no mutation rows; its `-TimedModel` behaviour is checked by the hand sessions of 12.2. Record the base tree and each file's sha256 with the campaign, so a Builder whose files match does not repeat it. Rows to rerun if a file differs: S1 to S4 (worker), S5 to S8 (resident), S9 (backend), S10 to S12 (router), S13 to S19, S21, S22 (phoneme_visemes), S20 (experience).

## 9. Diff Reviewer brief (properties to verify)

The consumers that must accept the change: the browser client (`ui/src/audio/voice.ts`:731-735, :757), the Captain's `lipsync.backend: rhubarb`, the AD-1152 golden, the AD-1346 census and the installer under Windows PowerShell 5.1.
1. With `lipsync.backend` at `heuristic` or `rhubarb`, the `/api/avatars/tts` and `/api/avatars/lipsync` responses and the rhubarb calls are what they were before the change, for every backend.
2. With a model whose `has_timings` is False, the worker calls `create` with S1's arguments and writes no extra file.
3. The line protocol is byte-identical; the timing file exists before the path is printed; no partial timing file is ever visible.
4. A timing file is deleted with its WAV, whatever the outcome; the service reads at most `TIMING_MAX_BYTES + 1` bytes.
5. `frames_from_timing` never raises on any bytes, and a refusal falls back to the rhubarb path with exactly one WARNING.
6. No module under `src/probos/audio` imports `probos.avatars`.
7. `kokoro-fetch.ps1` keeps the resolve, ASCII and UTF-8-scope guards unchanged and is ASCII. Without `-TimedModel` it fetches the same files from the same URLs, runs the same test line on `kokoro-v1.0.onnx` and prints the same lines as S1. With `-TimedModel` it pins the v1.1 asset's size and digest, saves it as `kokoro-v1.1.onnx`, never deletes or overwrites `kokoro-v1.0.onnx`, and throws unless the test line left a timing file.
8. The census counts of `tests/test_ad1346_admission_file_write_census.py`:170-188 do not move.
9. No default value changes: `KokoroTTSConfig.model_path` is still `tools/kokoro/kokoro-v1.0.onnx`, the AD-1152 digest does not move, no `default:` row of the facade baseline moves (its `schema_sha256` digests move only for `LipSyncConfig` and `SystemConfig`, from the wider `Literal`), and the three default-path pins are untouched.

## 10. What this does not change, and what waits

**Unchanged:**
- the UI;
- `/api/avatars/lipsync`;
- rhubarb's wrapper;
- Piper's line, key and outcome (timing always `None`);
- the voices file and its pin;
- `KokoroWorkerKey`'s argv;
- the BF-918 lifecycle, admission, locks and the BF-930 timing line;
- the AD-738f voice resolution and log line;
- `TTSBackend.synthesize`'s signature;
- the default `lipsync.backend` (`heuristic`);
- the default `tts.kokoro.model_path` (`tools/kokoro/kokoro-v1.0.onnx`), its docstring and its three pins;
- the installer's behaviour without `-TimedModel`, and S1's pin.

**Waits (one line each):**
- **Flipping the `model_path` default to `kokoro-v1.1.onnx`**, after the Captain accepts D2 and has run S3a on it: its own tiny slice. It moves `experience.py`:652-653, the three pins (`tests/test_ad1152_agentic_correlation.py`:353-357, `tests/test_ad738g_kokoro_voice.py`:647, `tests/test_ad1270e2c_experience_models.py`:212) and S3a's `test_c6`, with `config-facade-baseline.yaml`:2239 and `config-reference.md`:2072 regenerated. It also makes `-TimedModel` the installer's default and tells every operator to re-run it before pulling.
- The library pauses as an opt-in config (D3 picks the value).
- The `TIMING_OFFSET_SECONDS` tuning (D4, once).
- Word timestamps.
- The fp16 and int8 variants.
- `continuous=True`.
- Timed frames for deferred `/lipsync` requests.
- An HXI control for the lip-sync backend beyond the registry enum.
- Deleting the old model file (the Captain's choice).
- S2 prewarm.
- S4 GPU (the GPU stays with Ollama).
- S5.
- Option B (only on a D0 failure or a rejected D2 listen).

## 11. License posture

- **New packages and licences: none.** The v1.1 file holds the same Apache-2.0 Kokoro-82M weights, re-exported by kokoro-onnx (MIT) with `scripts/export.py` at commit `659b166c` (agent-read, pack section 8).
- **GPL boundary: unchanged.**
  - The phonemizer and espeak-ng (GPL-3.0-or-later) still run only in the operator-installed worker process.
  - The new artefact is a JSON file of phoneme symbols and floats, written by the ProbOS-authored worker. It is program output (data), not code from the GPL packages.
  - ProbOS reads it with the standard library (`phoneme_visemes.py`), and nothing in `src` imports the engine (`test_w8`, `tests/test_ad738g_kokoro_voice.py`:355-363).
- **Install burden:** none by default. An operator who opts in (`-TimedModel`) makes one 326 MB download into gitignored `tools/kokoro/`. No torch and no second venv, so the Captain's "GPL stays in the worker process" holds with no new register entry.
- **Register:** `THIRD_PARTY_LICENSES.md`:172-173 is corrected (P13.1). It recorded S1's release, size and exchange; the "no `duration` output" fact (`reference-projects.md`:83) is true of the v1.0 export only (P13.2).
- **Commercial boundary:** nothing paid, nothing near it.

## 12. Measurements, hand sessions and the Captain's opt-in

The Captain's rule: no install or timing measurement runs **during a gate** (F-757, #1870). Everything below runs only when no gate is running.

### 12.1 Pre-build go/no-go (the orchestrator, before M1)

Run as soon as the S1 batch's gate has ended. None of these needs S3a's code. They are the orchestrator's scripts in `G:\s3-research\d\` (`d0_fetch.ps1`, `d0_check.py`, `d1_rtf.py`, `d2_d3_equiv.py`, `d4_rhubarb.py`, with the corpus `s3_corpus.py`). They run under S1's probe venv, `G:\speech-kokoro-probe\venv\Scripts\python.exe -I`, against S1's verified files in `G:\speech-kokoro-probe\` and the new file in its own directory, `G:\s3-d-model\`. The scripts live apart from the download, and `-I` is safe because each script puts its own folder on `sys.path` for `s3_corpus`. Where a script differs from the first draft's step, the step below says so and keeps the stricter pass condition.

**Go/no-go:**
- **No-go:** D0 fails, or the Captain rejects the D2 listen (12.4).
- **Go:** D0 passes and the D2 ratio passes. The listen may stay pending through the build, the PR and the merge (orchestrator ruling, 12.4 says what a late rejection costs). It is requested of the Captain in the wave comment, as the acceptance of his own opt-in and of the later default flip.
- D1 and D4 failures follow their own actions below. D3 never blocks.

1. **D0a, fetch:** `powershell -ExecutionPolicy Bypass -File G:\s3-research\d\d0_fetch.ps1 -Dest G:\s3-d-model`.
   - Pass: `size matches (325505369): True   sha256 matches: True`, exit 0, and the voices line ends `True`.
   - Stricter than the script: `G:\s3-d-model` must not exist before the run (the script makes it with `-Force` and reuses a file already there). On a mismatch, delete `G:\s3-d-model\kokoro-v1.1.onnx` by hand: the script moves the download into place before it checks it.
   - **Fail** → B (12.4).
2. **D0b, outputs, flag and raw durations:** `G:\speech-kokoro-probe\venv\Scripts\python.exe -I G:\s3-research\d\d0_check.py G:\s3-d-model\kokoro-v1.1.onnx`.
   - Pass: the outputs include `duration`; `has_timings: True`; the summary's `"verdict": "PASS"`; and the `create_timed` line prints espeak symbols with rising starts.
   - The verdict means `len(audio) == int(sum(duration)) * 600` for every batch of the 50 sentences, multi-batch ones included, and `len(duration) == tokens + 2` for each. The script's length condition is stricter than the first draft's, so it is kept.
   - **Fail** → B.
3. **D0c, embedded vocabulary** (not in the scripts; kept from the first draft):
   ```powershell
   G:\speech-kokoro-probe\venv\Scripts\python.exe -I -c "import onnxruntime as ort; from kokoro_onnx.session import embedded_vocab; from kokoro_onnx.config import DEFAULT_VOCAB; s = ort.InferenceSession(r'G:\s3-d-model\kokoro-v1.1.onnx', providers=['CPUExecutionProvider']); e = embedded_vocab(s); print('none embedded' if not e else (e == DEFAULT_VOCAB, sorted(set(e) ^ set(DEFAULT_VOCAB))))"
   ```
   - Pass: `none embedded` or `(True, [])`.
   - Otherwise report the differing symbols. Each symbol outside the table is shown as `sil` (decision 7), and the Architect decides before M2 whether the table needs rows. This does not re-open B.
4. **D1, real-time factor:** `G:\speech-kokoro-probe\venv\Scripts\python.exe -I G:\s3-research\d\d1_rtf.py` (4 threads).
   - The script measures in process, by S1's probe method (eight sentences, `af_bella`, one warm-up), old and new file interleaved twice. The first draft said "through the worker", which needs S3a's worker; this replaces it, with the same thresholds.
   - Pass: both v1.1 rows' `overall_rtf` are ≤ 0.345 (S1's 0.314 plus 10 %). Requiring both passes is stricter than one.
   - Between 0.345 and 0.45, rerun with the argument `8` and pass at ≤ 0.35. Otherwise the Captain decides, with the numbers.
   - A D1 failure does not lead to B (torch is not faster) and does not stop M1; it goes to the Captain before the PR.
5. **D2, sound against S1:** `G:\speech-kokoro-probe\venv\Scripts\python.exe -I G:\s3-research\d\d2_d3_equiv.py`.
   - What it compares: v1.0 `create` against v1.1 `create_timed` at zero pauses, the worker's call, over twenty sentences.
   - Pass: `"all_within_5pct": true`, and the Captain accepts a five-sentence listen of `G:\s3-d-model\ab\old_0X.wav` against `new_0X.wav`.
   - Stricter than the script: the first draft said "sentences and voices", and the script uses `af_bella` only. Run the twenty-sentence ratio also with `af_heart`, the worker's `--default-voice` (`kokoro-fetch.ps1`:109), from a copy of the script in `G:\s3-research\d\` with that one word changed. It must pass on both voices.
   - **A rejected listen** → no build, or park it if M1 has started; B re-opens (12.4).
   - **A ratio outside ±5 %** with an accepted listen → the Architect decides, with the numbers, before M1.
6. **D3, pauses (non-blocking):**
   - The same script prints `d3_multi_batch` over the 50-sentence corpus and the three long paragraphs.
   - It also writes `new_zero_0X.wav` and `new_default_0X.wav` for the Captain's A/B of zero pauses against 0.25 s and 0.1 s, on five comma-heavy sentences.
   - This covers the first draft's D3 and more. It only picks a later setting.
7. **D4, timing against rhubarb:** `G:\speech-kokoro-probe\venv\Scripts\python.exe -I G:\s3-research\d\d4_rhubarb.py`. It runs `D:\ProbOS\tools\rhubarb\rhubarb.exe` read-only and writes its WAVs under `G:\s3-d-model\rhubarb`.
   - Pass: `raw_median_abs_ms` ≤ 60 and `raw_p90_abs_ms` ≤ 120. Both estimators are being compared, and rhubarb is not ground truth. Both thresholds sit inside ITU-R BT.1359-1's acceptability window (sound early +90 ms, sound late −185 ms; detectability +45 / −125 ms).
   - How the script differs: it matches every rhubarb vowel cue (C, D, E, F, and B over 80 ms) one to one to the nearest vowel-group onset of any class within 250 ms, and drops pairs further apart. The first draft matched open-vowel onsets of the same class (`D`→`aa`, `C`→`E`, `E`→`oh`). The same-class match needs M2's table, so it runs after M2 (12.2 step 2) and is the pass of record; this run picks the offset. Record `pairs` against the cue counts, so a low match rate is visible.
   - **Fails raw, passes tuned** (`tuned_*` within the thresholds) → before M2, the Architect sets `TIMING_OFFSET_SECONDS` in 7.3 to the script's `signed_median_offset_ms` / 1000, and moves `test_f1`'s pin (7.4) with it. The offset is rhubarb minus synthesizer, and frames move by +offset (`f.time + TIMING_OFFSET_SECONDS`, 7.3). No follow-up slice is needed.
   - **Fails even tuned** → build anyway: synthesizer stays an opt-in and the Captain stays on rhubarb. Not B: B's durations are the same numbers.

Record D0 to D4 on #1662 with the numbers. D0 and the D2 listen are the only checks that re-open B.

### 12.2 After the build (the orchestrator, before the PR opens)

1. **D0e, the whole seam on the real model** (after M2). Make `G:\s3-d-out\` new and empty, then, from the worktree root, send one line to the candidate's real worker under S1's probe venv:
   ```powershell
   '{"text": "Good evening, Captain. All systems are normal.", "output_file": "G:\\s3-d-out\\w1.wav", "voice": "af_heart", "speed": 1.0}' | G:\speech-kokoro-probe\venv\Scripts\python.exe -I scripts\kokoro_worker.py --model G:\s3-d-model\kokoro-v1.1.onnx --voices G:\speech-kokoro-probe\voices-v1.0.bin --threads 4 --default-voice af_heart
   ```
   - Pass: the worker prints the path, and `w1.wav.timing.json` is beside it.
   - Then, still from the worktree root, run in the ProbOS venv with the candidate's `src` first on the path:
     ```text
     d:/ProbOS/.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'src'); from pathlib import Path; import probos; from probos.avatars.phoneme_visemes import frames_from_timing; w = Path(r'G:\s3-d-out\w1.wav'); f = frames_from_timing(Path(str(w) + '.timing.json').read_bytes(), w.read_bytes()); print(probos.__file__, len(f), [x.viseme for x in f][:12])"
     ```
     Pass: `probos.__file__` is under this worktree, not `D:\ProbOS`; the list is non-empty and has vowel keys; no WARNING.
   - Then the untimed model: run the same worker line with `--model G:\speech-kokoro-probe\kokoro-v1.0.onnx` and `w0.wav`. Pass: the path is printed and no `w0.wav.timing.json` appears (decision 4, on the real untimed model).
2. **D4 by class** (after M2; non-blocking, recorded on #1662):
   - Run the candidate's worker as in step 1 over D4's twenty sentences (`s3_corpus.TWENTY`, `af_bella`) into `G:\s3-d-out\d4\`.
   - Then a script in the ProbOS venv (with `src` first on the path, as above) runs rhubarb on each WAV and builds frames with `frames_from_timing`. It matches each `aa`, `E` and `oh` frame onset to the nearest rhubarb `D`, `C` or `E` cue respectively, one to one.
   - Pass and failure as 12.1 step 7. This measures the frames that ship, merges and offset included, and it keeps the probe venv free of ProbOS.
3. **Installer hand sessions** (after M3), from the worktree root, each in a new window:
   - **Step 0:** parse the script in a 5.1 window and a 7 window, as `ad-738g-s1` 16.12.3 step 0. Pass: `0` in both.
   - **Session A:** S1's refusals (16.12.3 Session A), each run once as written and once with `-TimedModel` added. Pass: as written there, and nothing is created.
   - **Session T1, Windows PowerShell 5.1, opting in.**
     - Setup: make `G:\s3-install\` new and empty. Copy S1's verified `kokoro-v1.0.onnx` and `voices-v1.0.bin` into it from `G:\speech-kokoro-probe\`, so that only the new file downloads.
     - Run: `powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -DestDir G:\s3-install -TimedModel`.
     - Pass, in order: `[skip] kokoro-v1.0.onnx`; `[skip] voices-v1.0.bin`; `[get ] kokoro-v1.1.onnx ...`; `[ ok ] kokoro-v1.1.onnx (SHA-256 verified: beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a)`; `the Kokoro venv cannot import probos`; `the Kokoro worker spoke the test line`; `[ ok ] the model reports phoneme timings`; S1's two closing lines; then `... also set tts.kokoro.model_path: G:\s3-install\kokoro-v1.1.onnx and lipsync.backend: synthesizer ...`.
     - Also: `kokoro-v1.0.onnx`'s SHA-256 is still `7d5df8ec...`, and no `fetch-check.wav*` is left.
   - **Session T2, PowerShell 7, console UTF-16** (as 16.12.3 (c7)): `pwsh -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -DestDir G:\s3-install -TimedModel`. Pass: three `[skip]` lines, the test line, the timings line and the config line, and `WebName` prints `utf-16` afterwards.
   - **Session T3, Windows PowerShell 5.1, no switch, same folder.** Pass: S1's output line for line (two `[skip]` lines, the boundary line, the test line, S1's two closing lines), with no timings line and no config line. `kokoro-v1.1.onnx` is unchanged (same SHA-256).
   - A failure in any session → the Builder repairs 6.12 and the sessions rerun. It does not re-open B.

### 12.3 The Captain, in `D:\ProbOS` (an opt-in, after his weekend recording)

Nothing breaks on a pull: S3a moves no default, so his S1 voice and his `lipsync.backend: rhubarb` behave exactly as before, whether or not he opts in. The 326 MB download is a required action only when he opts in.

1. `powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -TimedModel`. Pass:
   - `[skip] kokoro-v1.0.onnx`;
   - `[skip] voices-v1.0.bin`;
   - `[ ok ] kokoro-v1.1.onnx (SHA-256 verified: beb0d184...)`;
   - the test line;
   - `[ ok ] the model reports phoneme timings`;
   - the closing line naming `tts.kokoro.model_path: tools/kokoro/kokoro-v1.1.onnx`.
2. In `config/system.yaml`, set `tts.kokoro.model_path: tools/kokoro/kokoro-v1.1.onnx` and `lipsync.backend: synthesizer`.
3. Restart the vessel and reload the HXI page.
4. Read the log: `Select-String -Path "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log" -Pattern "resident kokoro started|AD-738g: kokoro|visemes=|timings were refused"`. Pass:
   - `BF-918: resident kokoro started (voice=kokoro-v1.1)`;
   - `AD-738g: kokoro ... result=ok` per sentence;
   - `BF-918: tts route ... visemes=synthesizer` per Kokoro sentence;
   - no `the synthesizer's timings were refused` line;
   - the mouth moves with no rhubarb delay.

   A Piper sentence still logs `visemes=inline` or `visemes=deferred`.
5. **Rollback, any time:** set `tts.kokoro.model_path: tools/kokoro/kokoro-v1.0.onnx` and `lipsync.backend: rhubarb` (the values before step 2), and restart. That gives S1's model, pacing and rhubarb lip-sync exactly. Do not delete the lines: an absent `lipsync.backend` is the code default `heuristic`. Setting `lipsync.backend: rhubarb` alone keeps the new model with rhubarb frames.

### 12.4 If D0 or the D2 listen fails

- **Before M1 (the expected case now):** do not start the build. S3a parks. The Architect re-drafts it on B from pack sections 2 to 5 and `s3-architect-decision.md`. The re-draft keeps this contract's timing file, route and check (M1 and M2's design), and adds a second table for misaki's single-letter symbols. B's worker writes the same file format.
- **After M1 has started, before the PR merges** (a listen rejected late): park the batch before the PR. M1 and M2 carry over to B, and M3 is dropped.
- **After the PR merged:** S3a stays in main and inert (opt-in, no default changed, `lipsync.backend` still `rhubarb` unless set). B re-opens as a follow-up slice that reuses M1 and M2; M3's switch is retired or repointed at B's model.

## 13. Text for #1662 (the orchestrator posts both; no closing keyword)

**Finding (the engine decision):**
> S3 engine: option D, the kokoro-onnx `model-files-v1.1` export, over B (PyTorch kokoro in a second venv). The Captain's order was PyTorch first, then the ONNX export only if PyTorch failed. The PyTorch check succeeded: hexgrad's `KPipeline` gives `pred_dur` and English word timestamps. While answering it, the research found that kokoro-onnx's own `model-files-v1.1` release re-exports the same `.pth` weights with a `duration` output, which the kokoro-onnx 0.6.1 we already run reads (`has_timings`, `create_timed`). It is the same engine, voices file, licence set and CPU path. It is one 326 MB file instead of about 585 MB plus about 1 GB of torch, with no unproven pin set and no second venv, and its durations are asserted equal to torch's by the export script. Same answer, smaller cost, so D is built first. B stays the fallback if the file fails the raw duration check (D0) or the Captain rejects how it sounds (D2). D0 and D2's numeric ratio passed before the build; the listen is pending and gates only the Captain's own opt-in. The new model is an installer opt-in and no default changes, so nothing changes for anyone until they choose it. Contract: `prompts/ad-738g-s3a-synthesizer-timed-lipsync.md`. Refs #1662.

**Wave comment (when the S3a PR opens):**
> AD-738g S3a in review: lip-sync timed by the synthesizer, opt in (`lipsync.backend: synthesizer`). No default changes: `lipsync.backend` stays `heuristic`, `rhubarb` is unchanged, and `tts.kokoro.model_path` stays S1's `kokoro-v1.0.onnx`, so a pull changes nothing. To opt in (after the weekend, whenever convenient): run `scripts\kokoro-fetch.ps1 -TimedModel` (326 MB, saved as `tools/kokoro/kokoro-v1.1.onnx` beside S1's file); set `tts.kokoro.model_path: tools/kokoro/kokoro-v1.1.onnx` and `lipsync.backend: synthesizer` in `config/system.yaml`; restart and reload; check the log for `visemes=synthesizer`. Rollback: set them back to what they were (`tts.kokoro.model_path: tools/kokoro/kokoro-v1.0.onnx`, `lipsync.backend: rhubarb`) and restart; deleting them would leave lip-sync on `heuristic`. Pre-build checks D0 to D4: <results>. D0e and installer sessions: <results>. Refs #1662.

## 14. Tracking

- `PROGRESS.md`: P13.3.
- `DECISIONS.md`: P13.4.
- `THIRD_PARTY_LICENSES.md`: P13.1.
- `docs/research/reference-projects.md`: P13.2.
- `docs/development/ad-ledger-snapshot.json` and `open-ads-report.md`: by `gen_ad_ledger.py` (6.11).
- `docs/development/roadmap.md`: unchanged. Row `:827` already names "timing-derived lip-sync" under AD-738g.
- No BF entry.

## 15. Prior art and blind spots

- **Internal:**
  - S1's contract: the worker, the resident key Protocol, the installer guards, its sections 13 and 16.11-16.12.
  - BF-918 (deferred visemes, `/lipsync`) and AD-721b-1/AD-738c (the Oculus mapping and `_PRESTON_BLAIR_TO_OCULUS`).
  - `s3-evidence-pack.md` sections 6 and 8, `s3-architect-decision.md`, `s3-rerank-decision.md`.
  - `docs/research/`: nothing on phoneme-timed visemes beyond these.
- **External**, date used 2026-11-28; the Speech row was reviewed 2026-11-27 (interval 180 days), so it is not overdue. Re-examined because it bears directly on this slice; the row is updated in P13.2. Other overdue rows (agent harnesses) are not relevant: considered, deferred.
  - The GitHub release API for `model-files-v1.1`: asset names, sizes and digests read 2026-11-28. `kokoro-v1.0.onnx` 325,505,369 B `sha256:beb0d184...`; `voices-v1.0.bin` 28,214,398 B `sha256:bca610b8...`. The body notes that one asset in this release was later replaced. **Absorbed:** pin by digest, never by name.
  - The Meta OVRLipSync viseme reference (15 visemes and their phonemes: PP p/b/m, FF f/v, TH, DD t/d, kk k/g, CH tS/dZ/S, SS s/z, nn n/l, RR r, aa, E, ih, oh, ou). **Absorbed** as the table's basis.
  - HeadTTS (Kokoro plus Oculus visemes, `deltaStart` -10 ms and `deltaEnd` +10 ms defaults). **Adapted:** one offset constant, starting at 0 until D4 measures.
  - ITU-R BT.1359-1: detectability +45 / −125 ms, acceptability +90 / −185 ms. **Absorbed** as D4's frame, from the ITU text as surfaced by search. The PDF itself was not fetched.
- **Blind spots:**
  - Model durations are not acoustic boundaries (PyTorch kokoro #113) and punctuation durations disagree (#365); punctuation is `sil` here and D4 measures the rest.
  - The BOS window grows at slow speeds (#344); the lead-in is a gap, so it is `sil`.
  - Multi-batch requests lose the join pause (decision 5, D3).
  - An operator who sets `lipsync.backend: synthesizer` but leaves `model_path` on the default v1.0 file gets no timings, so every Kokoro sentence takes the rhubarb path. That is by design, and `visemes=deferred` or `inline` in the log shows it.
  - A default that names a file the operator has not fetched turns a pull into a silent voice downgrade (decision 2). That is why the default flip is its own later slice with an operator notice.
  - A same-user process could plant a timing file in the worker's private temp directory. That threat equals planting a WAV today, and the check bounds the damage to a wrong mouth shape.
  - Up to 4096 entries are checked on the event loop: a single pass, small next to a rhubarb run.
  - The table's consonant rows barely matter to the renderer (`rhubarb_backend.py`:34-40); its vowel rows do, and D4 measures them.

## 16. Acceptance criteria

1. The A/B of 8.1 holds, and S1 to S20 are killed as 8.3 says.
2. The focused checks of 8.2 pass on each milestone and on the frozen candidate. Pre-existing tests in those files pass unchanged, except the in-place edits of 6.10 a to d, each with its reason inline. The three default-path pins and `tests/test_ad1152_agentic_correlation.py` are not edited and pass. The config tools pass in `--check` form with exactly the diffs of 6.11 (M2): one line of `docs/development/config-reference.md` and the two `schema_sha256` lines of `docs/development/config-facade-baseline.yaml`.
3. `git diff --check` is clean, new text is ASCII, and no unnamed file changes.
4. The Diff Reviewer verifies the properties of section 9.
5. One receipted broad gate on the committed head is green.
6. D0 and D2's ratio (12.1) pass before M1 starts, and D2's listen is not rejected (it may be pending; it does not gate the PR or the merge, orchestrator ruling 2026-11-28). D1's action is settled before the PR opens. D0e and the installer hand sessions (12.2) pass before the PR opens. D1, D3 and D4 (and D4 by class) are recorded on #1662. No measurement runs during a gate.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 17. Verified Against Codebase (2026-11-28, tree `6b9082a9`; re-anchored 2026-11-27 on tree `490bdbb8`)

The repair of PR #1872 changed only `src/probos/audio/tts/piper_backend.py` and `tests/test_ad738g_kokoro_voice.py` (`git diff --stat 88676ab1 fae613df`); their rows below are re-read on `490bdbb8`, and the other rows stand as read on `6b9082a9`.

Re-anchored 2026-11-28 on `55ae03eb` (tree `04e94e65`) by the orchestrator; the round-1 repair's citations are `phoneme_visemes.py`:128 and :161-162, `experience.py`:730, `kokoro-fetch.ps1`:16 and :149, `resident.py`:346-347, and `fake_kokoro_worker.py`:73-78.

```text
git rev-parse HEAD HEAD^{tree}
  88676ab11a06b199eddd6ed1dd6a8cf5ced706ff / 6b9082a9f35d698aa2f0b44f5cf061332f3387e8  (first reading)
  fae613dff8688abe336d7b4ee4eae60b516015cb / 490bdbb893cecc2ffa4f8ec35d1562860f0519da  (re-anchor, 2026-11-27)
scripts/kokoro_worker.py
  41-46  class Engine(Protocol): get_voices; create(self, text, voice, speed, lang) -> tuple[Any, int]
  63-78  def write_wav(path, samples, rate) -> None ... os.replace(part, path) ... part.unlink(missing_ok=True)
  94-108 def speak(...): ... samples, rate = engine.create(text, voice=voice, speed=float(request.get("speed", 1.0)), lang=lang_for(voice))
  129-131 speak(...); stdout.write(request["output_file"].encode("utf-8") + b"\n")
  139-143 Kokoro.from_session(session, args.voices)
src/probos/audio/tts/resident.py
  60-61 SLOW_SYNTHESIS_MS = 750.0; 98-116 class WorkerKey(Protocol): label, name, retire_on_empty, argv
  138-140 retire_on_empty -> True (Piper); 182-184 -> False (Kokoro); 197-204 class PiperOutcome
  303-304 audio = out.read_bytes() ...; return PiperOutcome(audio, "ok") if audio else PiperOutcome(None, "empty")
  309-314 finally: out.unlink(missing_ok=True); 316-317 def _await_answer; 351 mkdtemp(prefix=f"probos-{label}-"); 422-423 rmtree
  490-497 async def synthesize(...) -> bytes | None; 556-557 if outcome.audio is not None: return outcome.audio
src/probos/audio/tts/backends.py 9-19 class TTSResult: audio_bytes: bytes; mime: str
src/probos/audio/tts/kokoro_backend.py 9-12 licence; 28 import KokoroWorkerKey, VoiceSynthesisService; 121-132; 134-136; 156-160 "kokoro is not installed (missing: %s); run scripts/kokoro-fetch.ps1"; 170 synthesize(key, ...)
src/probos/avatars/rhubarb_backend.py 26 from probos.audio.tts.resident import run_voice_work; 34-40 renderer uses only aa/ih/ou/E/oh; 43-46 OculusViseme; 74-84 VisemeFrame(time, duration, viseme)
src/probos/routers/avatars.py 62 if cfg.backend == "heuristic"; 69 comment; 290 local import; 332-343 rhubarb branch; 357-364 response
src/probos/config_models/experience.py 639 class KokoroTTSConfig; 652-653 model_path default "tools/kokoro/kokoro-v1.0.onnx" (unchanged by S3a); 726-728 LipSyncConfig.backend Literal; 816 class TTSConfig; 920 kokoro: KokoroTTSConfig = Field(default_factory=KokoroTTSConfig)
src/probos/settings/section_registry.py 282-285 "lipsync.backend" enum_values=("heuristic", "rhubarb")
scripts/kokoro-fetch.ps1 8-11 header; 20-23 usage; 24-27 param([switch]$Force, [string]$DestDir = "tools/kokoro"); 37 resolve; 38-40 ASCII guard; 42 $Base; 43-46 $Files; 65-82 loop (66 $target, 67 skip, 71-73 part/get/Invoke-WebRequest "$Base/$($f.name)"); 95-99 model/probe; 106-113 UTF-8 scope; 109 --default-voice af_heart; 117-119 ok line; 120-122 closing lines (end of file); no Set-StrictMode
G:\s3-research\d\ (orchestrator scripts, read 2026-11-28)
  d0_fetch.ps1 -Dest default G:\s3-d-model; New-Item -Force; Move-Item before the hash check; exit 1 on mismatch
  d0_check.py raw len(audio) == int(duration.sum()) * 600 per batch over CORPUS50; len(duration) == tokens + 2; af_bella, en-us
  d1_rtf.py S1_PROBE, af_bella, warm-up, old/new interleaved twice; thresholds 0.345 / 0.45 / 8 threads 0.35
  d2_d3_equiv.py TWENTY ratio 0.95-1.05, af_bella only; ab\old_XX/new_XX for XX < 5; d3 multi-batch, LONG, COMMA_HEAVY zero vs 0.25/0.1
  d4_rhubarb.py cues C/D/E/F and B > 80 ms vs vowel-group onsets of any class, one to one within 250 ms; signed_median_offset = rhubarb - synthesizer
tests/test_ad1152_agentic_correlation.py 353-357 kokoro pop with model_path; 563 default_config_sha256 of the dump; 569, 584 default_off tests
tests/test_ad1270e2c_experience_models.py 211-213 kokoro dump; 404-405 backend literal cases
tests/test_ad738g_kokoro_voice.py (tree 490bdbb8) 31 import KokoroWorkerKey, PiperWorkerKey, VoiceSynthesisService; 82-88 launcher fixture (FakePiperLauncher, resident.subprocess Popen); 98-107 _RecordingService (105 synthesize); 193-198 _ToneEngine; 327-363 test_w8 (337 parses kokoro_worker.py, 347 module-level set, 355-363 src never imports the engine); 484-494 test_b4 (494 installer named); 647 assert cfg.model_path == "tools/kokoro/kokoro-v1.0.onnx"
src/probos/audio/tts/piper_backend.py (tree 490bdbb8) 262 await self._service.synthesize(key, text, ...); 265 TTSResult(audio_bytes=wav_bytes, mime="audio/wav")
tests/test_ad738f_per_agent_voices.py 28 import; 44-52 _RecordingService.synthesize; 235-244 PiperBackend through it
tests/test_ad1270e1_config_facade.py 1531-1534, 1582 counts 311/298/13/229/1886
docs/development/config-reference.md 2042 Literal['heuristic', 'rhubarb']; 2072 model_path
docs/development/config-facade-baseline.yaml 2239 model_path default; 2282-2293 LipSyncConfig (2287 schema_sha256 d5adee56..., which hashes the types; 2289-2293 defaults); 3426-3431 SystemConfig (3431 schema_sha256 809d14b4...)
scripts/check_config_facade.py 137, 1716 --update-baseline; tests/test_ad1270e1_config_facade.py 1813 test_check_is_green_on_the_committed_baseline
THIRD_PARTY_LICENSES.md 169-174; docs/research/reference-projects.md 83; DECISIONS.md 11-13; PROGRESS.md 1-3
ui/src/audio/voice.ts 731-735 deferred vs inline; 757 data.backend === 'rhubarb'
kokoro-onnx 0.6.1 (G:\speech-kokoro-probe\venv\Lib\site-packages\kokoro_onnx\)
  __init__.py 77 vocab = explicit or embedded_vocab(session); 85-86 has_timings; 136-138 outputs[1] as duration
  __init__.py 206-210 pause_after for every batch but the last; 229 token_edges(...)[1:]; 237 np.clip(edges - head, 0, len(audio)); 238-240 join silence
  __init__.py 258 create -> create_timed; 271-306 create_timed(..., sentence_pause=0.25, clause_pause=0.1, continuous=False); 302 insert_pauses; 316-325 offsets from real lengths
  sliding.py 29-35 Timing(phoneme, start, end); 38-41 token_edges rescales to samples; 44-52 timings()
  pauses.py 79-80 if not timings or not (sentence or clause): return; chunker.py 13-14 marks; 89-96 pause_after
  tokenizer.py 73-75 known(); 85-88 phonemize(..., preserve_punctuation=True, with_stress=True) filtered to vocab
  config.py 5-6 MAX_PHONEME_LENGTH 510, SAMPLE_RATE 24000; config.json 35-148 the 114-symbol vocab
  session.py 76-85 embedded_vocab
```

**Absence Verified (2026-11-28):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| `lipsync` config is read only by the two routes | Grep `\.lipsync\b\|"lipsync"` in `src` | `avatars.py`:40, :332 | yes |
| only two callers of the service's `synthesize` | Grep `service\.synthesize\|...` in `src` | `kokoro_backend.py`:170, `piper_backend.py`:262 | yes; Piper keeps `synthesize` |
| `TTSResult` is built in two places | Grep `TTSResult\(` in `src` | `piper_backend.py`:265, `kokoro_backend.py`:132 | yes; the new field is defaulted |
| service stand-ins with `synthesize` | Grep `async def synthesize\(self, key` in `tests` | `test_ad738f_per_agent_voices.py`:50, `test_ad738g_kokoro_voice.py`:105 | yes; both edited (6.10 b, c) |
| no test pins the lip-sync enum or Literal text | Grep `"heuristic", "rhubarb"` in the repo | `section_registry.py`:285, `experience.py`:726, and archived prompts only | yes |
| no golden holds the lip-sync Literal | Grep `heuristic` in `tests/fixtures/ad1152_agentic_off_golden.json` | no match | yes |
| no source-text test reads the changed `src` files | Grep `(resident\|kokoro_worker\|kokoro_backend\|avatars\|backends)\.py.*read_text` in `tests` | none; `test_w8` parses `kokoro_worker.py` for imports only (`:337`) | yes |
| a read-mode `open` is not a census point | `test_ad1346_admission_file_write_census.py`:15 ("`open` with no mode, a read mode ... are not") | as quoted | yes |
| other files that name `kokoro-v1.0` | Grep `kokoro-v1\.0` outside `prompts/` | experience.py, three tests, ps1, the two docs, licences, research row, PROGRESS (history, unchanged), the two `s3-*` notes | yes; after the amendment experience.py, the three tests and the two generated docs stay unedited (no default changes), and the ps1 keeps S1's v1.0 entry |
| the three default-path pins are the only tests naming the v1.0 file | Grep `kokoro-v1\.0\.onnx` in `tests` | `test_ad1152_agentic_correlation.py`:354, `test_ad1270e2c_experience_models.py`:212, `test_ad738g_kokoro_voice.py`:647 | yes; none is edited |
| only one test reads the installer's name | Grep `kokoro-fetch` in `tests` | `test_ad738g_kokoro_voice.py`:494 (a log-text assertion) | yes; the switch changes no message it reads |

**Not verified, and not stated as verified:** that the v1.1 file exposes `duration` (D0), and that it sounds the same (D2). The `export.py` assertions are the research agent's reading. The v1.1 file was not downloaded or opened.
