# AD-738g S1 (#1662): a local Kokoro voice, on this machine's CPU, behind the TTS backend seam

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27: amendment A1, section 16 (review round 1 repairs; it supersedes 6.1, 6.2, 6.12, 6.13 and section 9 where they differ, and adds 4 tests)
**Status:** ready to build. **Owning issue:** #1662 (stays open: S2 to S5 and the Captain's live acceptance remain). Commits say `Refs #1662.` and never a closing keyword.
**Base:** main `63c536b3`. Branch `feat/ad738g-s1-local-kokoro-voice-20261127`. Built in parallel with BF-930's batch and merged with it before one gate (section 7.1). **Number:** AD-738g is the issue's own number; no new AD or BF number is allocated.
**Design base:** the Architect consult of 2026-11-27 (`ref-738-consult-answer.md`), accepted, plus the orchestrator's first-hand measurements of the same day (real-time factor, install, hashes, API, the missing `duration` output, the GPL boundary). Where this contract departs from the consult it says so in section 3.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** Python 28 new in one new file, 1 case added to a parametrised test, 2 tests updated in place (snapshot and counts, reasons inline); UI 3 new in one new file. 0 removed.
**Scope:** four commits (section 4). New: `src/probos/audio/tts/kokoro_backend.py`, `scripts/kokoro_worker.py`, `scripts/kokoro-fetch.ps1`, `tests/fixtures/fake_kokoro_worker.py`, `tests/test_ad738g_kokoro_voice.py`, `ui/src/audio/__tests__/voice.kokoroGate.test.tsx`. Changed: `src/probos/audio/tts/resident.py`, `src/probos/audio/tts/__init__.py`, `src/probos/audio/tts/piper_backend.py`, `src/probos/config_models/experience.py`, `src/probos/config_models/__init__.py`, `src/probos/config.py`, `src/probos/settings/section_registry.py`, `src/probos/routers/avatars.py` (one docstring), `ui/src/audio/voice.ts` (four lines), `tests/test_ad1270e2c_experience_models.py`, `tests/test_ad1270e1_config_facade.py`, `THIRD_PARTY_LICENSES.md`, `docs/development/roadmap.md`, `docs/research/reference-projects.md`, `PROGRESS.md`, `DECISIONS.md`, and the tool-regenerated `docs/development/config-facade-baseline.yaml`, `docs/development/config-reference.md`, `docs/development/ad-ledger-snapshot.json`, `docs/development/open-ads-report.md`.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `config_models/experience.py`:744 | `backend: Literal["browser", "piper"]` | no Kokoro backend can be configured |
| `audio/tts/__init__.py`:17-49 (`select_backend`) | knows `piper` (:31) and `browser` (:43); any other name warns and returns `NullBackend` (:45-49) | nothing builds a Kokoro backend |
| `audio/tts/resident.py`:93-115, :128, :198, :336 | the resident service (BF-918) is keyed by `PiperWorkerKey`, whose argv is Piper's flags; the request line carries only `text` and `output_file` | a Kokoro worker cannot run under it: one Kokoro process must take a voice and a speed per request |
| `resident.py`:458-465 | every outcome without audio retires the worker | correct for Piper (a 0.5 s reload); for Kokoro a respawn costs about 3.2 s (0.72 s model load and 2.43 s first call, measured 2026-11-27) and one sentence with no phonemes would make the next sentence pay it |
| `ui/src/audio/voice.ts`:555, :567 | the client takes the server path only when `backend === 'piper'` (`!== 'piper'` falls back) | a `kokoro` status would make the browser speak every sentence |
| `routers/avatars.py`:222 | the server already gates on `backend == "browser"` | the server needs no gate change; client and server disagree today for any third backend |
| `config_models/experience.py`:725-825, `docs/development/config-facade-baseline.yaml`:3621-3638, `tests/test_ad1270e2c_experience_models.py`:198-208 | `TTSConfig`'s fields, schema digest and default dump are frozen | any new field moves the facade baseline and the snapshot test; both are regenerated or updated with the reason inline |

## 2. Overview

S1 is row 1 of the consult's slice plan: a resident Kokoro voice on this machine's CPU, audio only, lip-sync unchanged, off until the Captain configures it.

- **Worker (`scripts/kokoro_worker.py`, new).** Runs in the operator's venv `tools/kokoro/venv` under `python -I`. It speaks Piper's `--json-input` line protocol: one ASCII JSON line in (`text`, `output_file`, `voice`, `speed`), a 24 kHz 16-bit mono WAV written to `output_file`, the path printed. It derives `lang` from the voice prefix (`b?_` gives `en-gb`, else `en-us`). Its failure policy is D2.
- **Resident service (`resident.py`).** A `WorkerKey` Protocol (`label`, `name`, `retire_on_empty`, `argv`). `PiperWorkerKey` keeps its fields and gains the three properties; a new frozen `KokoroWorkerKey`. `synthesize(..., *, fields=None)` merges `fields` into the line only when given, after `text` and `output_file` and never replacing them, so Piper's line is byte-identical. A Kokoro worker that answers without audio stays resident. Log wording and the temp-directory prefix use `key.label`, so every Piper line reads as before except two service-wide lines (D7).
- **Backend (`audio/tts/kokoro_backend.py`, new).** Resolves the install paths (AD-1025 anchoring), the voice (a catalogue override, else `tts.kokoro.voice`), and the speed (`tts.kokoro.speed / length_scale` of the AD-738e-1 emotion table, clamped to [0.5, 2.0]); calls the service; logs one INFO line per sentence with the voice and the synthesis time.
- **Config.** A nested `KokoroTTSConfig` under `TTSConfig.kokoro` (section 6.6); `backend` gains `"kokoro"`; the registry enum gains it.
- **Client gate.** `voice.ts`:555 and :567 test `backend === 'browser'`, matching the server at `avatars.py`:222.
- **Install.** `scripts/kokoro-fetch.ps1` makes the venv with `uv`, installs `kokoro-onnx==0.6.1`, downloads the two model files with size and SHA-256 checks, and speaks one test line through the real worker.

Rejected, one line each:
- A separate `KokoroWorker` class: it would duplicate BF-918's lifecycle (DRY); the key Protocol is the only seam needed.
- A ProbOS-owned HTTP speech service now: a port, a credential and a bind policy the local pipe does not need; it belongs to the remote-Mac slice.
- The PyTorch `kokoro` package or Kokoro-FastAPI: multi-GB torch install; FastAPI serves with no documented authentication (consult section 2).
- A catalogue module under `audio/tts/` for config validation (the consult's `kokoro_voices.py`): `config_models` would import the audio package. The voice `Literal` in the config is the one source; the backend reads it with `typing.get_args` (D5).
- A prewarm in S1: D1.
- A Kokoro-to-Piper fallback chain: it changes the voice as audibly as the browser fallback, and the chain belongs with the remote slice.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | `threads` default 4 (1 to 16); `timeout_seconds` default 30.0 (> 0); no prewarm in S1 | Measured on the Ryzen 9 7950X3D: real-time factor 0.314 at 4 threads (0.41 s for 13 chars, 1.13 s for 65, 1.99 s worst of 8), 0.23 at 8, 0.181 at 16. At 4 threads synthesis runs 3.2 times faster than playback, so BF-930's prefetch keeps ahead once speech starts; only the first sentence's latency is visible, and 8 threads would save about 0.3 s on a 65-char sentence while taking twice the cores from the vessel. The cold cost is 0.72 s load plus 2.43 s first call, once per process: with D3 the process stays for the session, so one spoken warm-up line before recording is enough. 30 s is about six times the worst cold first sentence (process start, load, lazy init and a 118-char sentence, about 5 s) and short enough that one runaway request does not hold the single Kokoro lock for minutes; the timer starts only when the worker takes the request (`resident.py`:200), so queued sentences do not age. A prewarm needs startup wiring, a stored task and a shutdown cancel: S2 (consult row 3) |
| D2 | Worker failure policy: an engine error on one request (no phonemes, a speed out of range, any `Exception` from `create` or the WAV write) is logged on stderr and answered with the path and no file, and the loop continues. A line it cannot read (not ASCII JSON, no string `text` or `output_file`) ends the worker with exit 3. A model it cannot load ends it with exit 2. A default voice the voices file lacks ends it with exit 2 before it reads a line. A per-request voice the file lacks is spoken in the default voice, with a stderr warning | A request it cannot speak leaves the process healthy and the pipe in step (it answered with the matching path), so retiring it would only add a 3.2 s reload to the next sentence of a live interview. An unreadable line means the pipe is no longer trustworthy and there is no path to answer with; exiting makes the service see end of file at once and respawn for the next request, instead of waiting the 30 s timeout. The default voice is validated against the catalogue at config load (D5) and the voices file is hash-pinned (section 6.12), so a missing default means a foreign voices file: refusing to start is honest, where silently speaking another voice would hide it; each sentence then degrades to the browser voice |
| D3 | `KokoroWorkerKey.retire_on_empty` is `False`; `PiperWorkerKey.retire_on_empty` is `True` | D2's per-request answer arrives as the service's `empty` outcome (`resident.py`:213-214). Piper's behaviour stays as BF-918 shipped (`test_bf918_tts_latency.py`:259-267 keeps passing) |
| D4 | The client gate becomes `backend === 'browser'` at `voice.ts`:555 and :567; the two comments at :548-549 and :561-562 follow | One rule on both sides (`avatars.py`:222). The zero-HTTP guarantee for the default config is unchanged: `browser` still makes no POST (`voice.serverTts.test.tsx`:81-125) |
| D5 | The 28 English voice ids are `KokoroVoiceId = Literal[...]` in `config_models/experience.py`; `KokoroTTSConfig.voice` is typed with it; the backend's catalogue is `frozenset(get_args(KokoroTTSConfig.model_fields["voice"].annotation))` | Parse-time validation with no validator code and no import from the audio package into config. English only: the worker supports `en-us` and `en-gb`; a non-English voice spoken with an English phonemiser would be wrong. Ids from hexgrad/Kokoro-82M VOICES.md (20 American, 8 British) |
| D6 | The backend honours `voice_override` only when it is a catalogue id; otherwise `tts.kokoro.voice`. Voice resolution is one public method, `KokoroBackend.resolve_voice` | AD-718a proposals and the HXI picker can hold Piper or browser names (`voice/proposal.py`:34 checks no catalogue). AD-738f (#1868) adds its per-role default inside that method and an `agent_type` keyword on the backend Protocol; S1 leaves the Protocol unchanged |
| D7 | The resident service's log lines use `key.label`; every Piper line reads as before except two service-wide lines, "all N resident voice processes are busy" and "stopped N resident voice process(es)" | They name a shared pool, not one engine. No test pins either text (Absence Verified) |
| D8 | Without `fields`, `synthesize_blocking` and `_request` are called with BF-918's two arguments | `test_bf930_voice_path_timing.py`:96 and :387 replace those methods with a two-argument signature; passing a third positional `None` would break them, and BF-930's batch may touch that file, so it is not edited here |
| D9 | The Kokoro process uses one of the 4 resident slots (`PIPER_MAX_RESIDENT`, unchanged) and the per-key lock serialises its sentences | One speaker at a time is the interview case; synthesis is 3.2 times faster than playback |
| D10 | The backend logs one INFO line per sentence: `AD-738g: kokoro voice=<id> speed=<x.xx> chars=<n> synth_ms=<ms> result=ok|degraded` | The Captain's live check reads it (section 13); the BF-930 slow-request line is rate-limited to 12 a minute (`utils/step_timing.py`:46-58) and fires only past 750 ms |

## 4. Milestones and commits

Each milestone is one commit, built and focused-tested before the next (section 8.2 names its tests). Stage explicit paths only; never `git add -A`. Run `git diff --cached --stat` before each commit and stop on any unexpected file with more than 200 deletions.

| M | Pairs | Commit subject |
|---|---|---|
| M1 resident generalisation | 6.1; the R1-R4 tests of 6.15 | `Speech: the resident voice service runs any keyed worker, and a Kokoro key passes each request's voice and speed` |
| M2 worker and fake worker | 6.2, 6.3; the W1-W8 and R5-R7 tests of 6.15 | `Speech: a Kokoro worker that speaks Piper's line protocol from the operator's own venv` |
| M3 backend, config, registry, client gate | 6.4 to 6.11, the regenerations of 6.9, 6.16; the B, C, S and T tests of 6.15 | `Speech: a resident Kokoro voice on this machine behind the TTS backend seam, off until configured` |
| M4 install, licences, trackers | 6.12, 6.13, 6.14, 6.17 to 6.20; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`) and stage the two ledger files when they change | `Speech: the Kokoro install script with pinned hashes, its licence record and the trackers` |

No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Each commit body ends `Refs #1662.`

## 5. Builder: may and may not

- **May:** create the six new files with the content given; apply the pairs in order; run each milestone's focused line of 8.2; run the three config tools of 6.9 and `gen_ad_ledger.py`; `git diff --check`, `git diff --stat`.
- **May not:** edit an unnamed file; edit `tests/test_bf930_voice_path_timing.py`, `tests/test_bf918_tts_latency.py`, the census fixtures or `tests/test_bf892_spawn_env_guard.py`; add `skip`, `xfail` or a retry; add a wall-clock assertion; install anything into the ProbOS venv; reword an anchor. If a SEARCH does not match exactly once, or a regenerated count differs from 6.9's arithmetic, stop and report.

## 6. The pairs

### 6.1 `src/probos/audio/tts/resident.py` (M1)

**P1.1** SEARCH:
```python
Not ``loop.set_default_executor``: that would change the pool under every other
caller, crew cognition included, and bound none of them.
"""
```
REPLACE:
```python
Not ``loop.set_default_executor``: that would change the pool under every other
caller, crew cognition included, and bound none of them.

AD-738g (#1662): a process is fixed by a ``WorkerKey``. ``PiperWorkerKey`` is BF-918's
key, unchanged; ``KokoroWorkerKey`` runs ``scripts/kokoro_worker.py``, which speaks the
same line protocol and takes each request's voice and speed as extra fields. One Kokoro
process serves every voice, and a request it answers without audio does not retire it.
"""
```

**P1.2** SEARCH:
```python
from typing import IO, Any, Callable, Iterator, TypeVar
```
REPLACE:
```python
from typing import IO, Any, Callable, Iterator, Mapping, Protocol, TypeVar
```

**P1.3** SEARCH (the whole of `PiperWorkerKey`):
```python
@dataclass(frozen=True)
class PiperWorkerKey:
    """What one resident process is fixed to: the binary, the model and the prosody flags."""

    binary: str
    model: str
    noise_scale: float
    length_scale: float
    noise_w: float
    sentence_silence: float

    def argv(self, output_dir: Path) -> list[str]:
        """The process's command line. ``--output_dir`` is a fallback; each request names its own file."""
        return [
            self.binary,
            "--model", self.model,
            "--json-input",
            "--output_dir", str(output_dir),
            "--noise_scale", str(self.noise_scale),
            "--length_scale", str(self.length_scale),
            "--noise_w", str(self.noise_w),
            "--sentence_silence", str(self.sentence_silence),
        ]
```
REPLACE:
```python
class WorkerKey(Protocol):
    """AD-738g (#1662): what one resident process is fixed to; implemented by frozen, hashable dataclasses.

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

    def argv(self, output_dir: Path) -> list[str]: ...


@dataclass(frozen=True)
class PiperWorkerKey:
    """What one resident process is fixed to: the binary, the model and the prosody flags."""

    binary: str
    model: str
    noise_scale: float
    length_scale: float
    noise_w: float
    sentence_silence: float

    @property
    def label(self) -> str:
        return "piper"

    @property
    def name(self) -> str:
        return Path(self.model).stem

    @property
    def retire_on_empty(self) -> bool:
        return True

    def argv(self, output_dir: Path) -> list[str]:
        """The process's command line. ``--output_dir`` is a fallback; each request names its own file."""
        return [
            self.binary,
            "--model", self.model,
            "--json-input",
            "--output_dir", str(output_dir),
            "--noise_scale", str(self.noise_scale),
            "--length_scale", str(self.length_scale),
            "--noise_w", str(self.noise_w),
            "--sentence_silence", str(self.sentence_silence),
        ]


@dataclass(frozen=True)
class KokoroWorkerKey:
    """AD-738g (#1662): one resident Kokoro worker (``scripts/kokoro_worker.py``) serves every voice.

    The voice and speed travel on each request line (``fields``); the process is fixed to
    the interpreter, the model, the voices file, the thread count and the default voice.
    ``-I`` isolates the interpreter: no ``PYTHON*`` variable, no user site, and neither the
    script's nor the working directory on ``sys.path``, so the worker cannot import ``probos``.
    """

    python: str
    script: str
    model: str
    voices: str
    threads: int
    default_voice: str

    @property
    def label(self) -> str:
        return "kokoro"

    @property
    def name(self) -> str:
        return Path(self.model).stem

    @property
    def retire_on_empty(self) -> bool:
        return False

    def argv(self, output_dir: Path) -> list[str]:
        """The process's command line. Each request names its own output file, so ``output_dir`` is unused."""
        return [
            self.python, "-I", self.script,
            "--model", self.model,
            "--voices", self.voices,
            "--threads", str(self.threads),
            "--default-voice", self.default_voice,
        ]
```

**P1.4** SEARCH:
```python
    def __init__(self, key: PiperWorkerKey) -> None:
        self.key = key
```
REPLACE:
```python
    def __init__(self, key: WorkerKey) -> None:
        self.key = key
```

**P1.5** SEARCH:
```python
    def synthesize_blocking(self, text: str, timeout: float) -> PiperOutcome:
        """Run one request; starts the process first when it is not running.

        Refused (``closed``) once the worker is closed. When ``close`` came while this
        request ran, the request releases the worker before it returns.
        """
        self.thread_started = time.perf_counter()  # BF-930: log-only
        with self._state:
            if self._closed:  # closed while this request was queued: start nothing
                return PiperOutcome(None, "closed")
            self._running = True
        try:
            return self._request(text, timeout)
```
REPLACE:
```python
    def synthesize_blocking(
        self, text: str, timeout: float, fields: Mapping[str, str | float] | None = None,
    ) -> PiperOutcome:
        """Run one request; starts the process first when it is not running.

        Refused (``closed``) once the worker is closed. When ``close`` came while this
        request ran, the request releases the worker before it returns. AD-738g:
        ``fields`` (Kokoro's voice and speed) join the request line.
        """
        self.thread_started = time.perf_counter()  # BF-930: log-only
        with self._state:
            if self._closed:  # closed while this request was queued: start nothing
                return PiperOutcome(None, "closed")
            self._running = True
        try:
            # AD-738g: without fields the call keeps BF-918's two arguments (test stand-ins
            # replace this method with that signature: test_bf930_voice_path_timing.py).
            return self._request(text, timeout) if fields is None else self._request(text, timeout, fields)
```

**P1.6** SEARCH:
```python
    def _request(self, text: str, timeout: float) -> PiperOutcome:
```
REPLACE:
```python
    def _request(
        self, text: str, timeout: float, fields: Mapping[str, str | float] | None = None,
    ) -> PiperOutcome:
```

**P1.7** SEARCH:
```python
                return PiperOutcome(None, "error: no pipes to the piper process")
```
REPLACE:
```python
                return PiperOutcome(None, f"error: no pipes to the {self.key.label} process")
```

**P1.8** SEARCH:
```python
            line = json.dumps({"text": " ".join(text.splitlines()), "output_file": str(out)}, ensure_ascii=True)
```
REPLACE:
```python
            payload: dict[str, str | float] = {"text": " ".join(text.splitlines()), "output_file": str(out)}
            if fields:
                # AD-738g: per-request fields follow the two above and never replace them.
                payload.update({name: value for name, value in fields.items() if name not in payload})
            line = json.dumps(payload, ensure_ascii=True)
```

**P1.9** SEARCH:
```python
        directory = Path(tempfile.mkdtemp(prefix="probos-piper-"))
```
REPLACE:
```python
        directory = Path(tempfile.mkdtemp(prefix=f"probos-{self.key.label}-"))
```

**P1.10** SEARCH:
```python
        logger.info("BF-918: resident piper started (voice=%s)", Path(self.key.model).stem)
```
REPLACE:
```python
        logger.info("BF-918: resident %s started (voice=%s)", self.key.label, self.key.name)
```

**P1.11** SEARCH:
```python
        self._resident: OrderedDict[PiperWorkerKey, PiperWorker] = OrderedDict()
        self._busy: set[PiperWorkerKey] = set()
        # BF-918: evicted workers whose close has not run yet; ``close`` reaches them here.
        self._retiring: set[PiperWorker] = set()
        self._locks: dict[PiperWorkerKey, asyncio.Lock] = {}
```
REPLACE:
```python
        self._resident: OrderedDict[WorkerKey, PiperWorker] = OrderedDict()
        self._busy: set[WorkerKey] = set()
        # BF-918: evicted workers whose close has not run yet; ``close`` reaches them here.
        self._retiring: set[PiperWorker] = set()
        self._locks: dict[WorkerKey, asyncio.Lock] = {}
```

**P1.12** SEARCH:
```python
    async def synthesize(self, key: PiperWorkerKey, text: str, timeout: float) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade."""
```
REPLACE:
```python
    async def synthesize(
        self, key: WorkerKey, text: str, timeout: float, *, fields: Mapping[str, str | float] | None = None,
    ) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade.

        AD-738g: ``fields`` join the request line (Kokoro's voice and speed); Piper passes
        none, so its line is unchanged.
        """
```

**P1.13** SEARCH:
```python
                    future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout)
```
REPLACE:
```python
                    # AD-738g: no third argument without fields (D8 of the contract).
                    extra: tuple[Mapping[str, str | float], ...] = () if fields is None else (fields,)
                    future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout, *extra)
```

**P1.14** SEARCH:
```python
                    logger.warning("BF-918: piper request failed; the browser speaks this one", exc_info=True)
```
REPLACE:
```python
                    logger.warning("BF-918: %s request failed; the browser speaks this one", key.label, exc_info=True)
```

**P1.15** SEARCH:
```python
                        "BF-930: piper request slow chars=%d voice=%s total_ms=%.0f lock_wait_ms=%.0f claim_ms=%.0f "
                        "pool_wait_ms=%.0f work_ms=%.0f resume_lag_ms=%.0f cold=%s result=%s in_flight=%d",
                        len(text), Path(key.model).stem, total_ms, ms_between(t_enter, t_locked),
```
REPLACE:
```python
                        "BF-930: %s request slow chars=%d voice=%s total_ms=%.0f lock_wait_ms=%.0f claim_ms=%.0f "
                        "pool_wait_ms=%.0f work_ms=%.0f resume_lag_ms=%.0f cold=%s result=%s in_flight=%d",
                        key.label, len(text), key.name, total_ms, ms_between(t_enter, t_locked),
```

**P1.16** SEARCH:
```python
                if not self._closed:  # a request that shutdown ended is not a piper failure
                    self._log_failure(outcome, text, timeout)
                if self._resident.get(key) is worker:
```
REPLACE:
```python
                if not self._closed:  # a request that shutdown ended is not a voice failure
                    self._log_failure(key.label, outcome, text, timeout)
                if outcome.reason == "empty" and not key.retire_on_empty:
                    return None  # AD-738g: the worker answered without audio; it stays resident
                if self._resident.get(key) is worker:
```

**P1.17** SEARCH:
```python
    async def _claim(self, key: PiperWorkerKey) -> PiperWorker | None:
```
REPLACE:
```python
    async def _claim(self, key: WorkerKey) -> PiperWorker | None:
```

**P1.18** SEARCH:
```python
                    "BF-918: all %d resident piper processes are busy; the browser speaks this one",
```
REPLACE:
```python
                    "BF-918: all %d resident voice processes are busy; the browser speaks this one",
```

**P1.19** SEARCH:
```python
    def _forget(self, key: PiperWorkerKey, worker: PiperWorker) -> None:
```
REPLACE:
```python
    def _forget(self, key: WorkerKey, worker: PiperWorker) -> None:
```

**P1.20** SEARCH:
```python
    @staticmethod
    def _log_failure(outcome: PiperOutcome, text: str, timeout: float) -> None:
        if outcome.reason == "timeout":
            logger.warning(
                "AD-738/BF-918: piper timed out after %ss synthesizing %d chars; killed, "
                "and the next request starts a new process",
                timeout, len(text),
            )
        elif outcome.reason == "exited":
            logger.warning("AD-738/BF-918: piper exit=%s; stderr=%s", outcome.returncode, outcome.stderr_tail)
        elif outcome.reason == "empty":
            logger.warning("AD-738/BF-918: piper produced 0 bytes; degrading")
        else:
            logger.warning("AD-738/BF-918: piper subprocess failed: %s", outcome.reason)
```
REPLACE:
```python
    @staticmethod
    def _log_failure(label: str, outcome: PiperOutcome, text: str, timeout: float) -> None:
        if outcome.reason == "timeout":
            logger.warning(
                "AD-738/BF-918: %s timed out after %ss synthesizing %d chars; killed, "
                "and the next request starts a new process",
                label, timeout, len(text),
            )
        elif outcome.reason == "exited":
            logger.warning("AD-738/BF-918: %s exit=%s; stderr=%s", label, outcome.returncode, outcome.stderr_tail)
        elif outcome.reason == "empty":
            logger.warning("AD-738/BF-918: %s produced 0 bytes; degrading", label)
        else:
            logger.warning("AD-738/BF-918: %s subprocess failed: %s", label, outcome.reason)
```

**P1.21** SEARCH:
```python
            logger.info("BF-918: voice synthesis closed; stopped %d resident piper process(es)", len(workers))
```
REPLACE:
```python
            logger.info("BF-918: voice synthesis closed; stopped %d resident voice process(es)", len(workers))
```

### 6.2 `scripts/kokoro_worker.py` (new, M2)

```python
"""AD-738g (#1662) S1: the resident Kokoro worker. ProbOS starts it; it is not part of the ProbOS process.

Run by ``VoiceSynthesisService`` (``src/probos/audio/tts/resident.py``) as
``<tools/kokoro/venv python> -I scripts/kokoro_worker.py --model M --voices V --threads N --default-voice D``.
``-I`` isolates it: no ``PYTHON*`` variable, no user site, and neither this directory nor the
working directory on ``sys.path``, so it cannot import ``probos``.

Protocol (Piper's ``--json-input``): one ASCII JSON object per stdin line,
``{"text", "output_file", "voice", "speed"}``. For each line the worker writes a 16-bit mono
WAV at the engine's rate (24 kHz) to ``output_file`` and prints that path on stdout. A request
it cannot speak (an engine error: no phonemes, a speed out of range) is answered with the path
and no file, and the worker keeps serving. A line it cannot read ends the worker (exit 3). A
model it cannot load, or a default voice the voices file lacks, ends it before it reads a line
(exit 2). Logs go to stderr, which the service sends to a file; library prints go there too.

License posture: this file imports only the standard library and numpy at module level, and
``onnxruntime`` and ``kokoro_onnx`` (both MIT) inside ``load_engine``. kokoro-onnx loads
phonemizer and espeak-ng (GPL-3.0-or-later) into this process, which the operator installs
into ``tools/kokoro/venv`` (``scripts/kokoro-fetch.ps1``) and which exchanges only text, a
voice id and a speed in and a WAV path out with ProbOS (THIRD_PARTY_LICENSES.md, "License policy").
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path
from typing import IO, Any, Callable, Protocol

import numpy as np

#: Exit codes; the service's log shows them as ``exit=N``.
EXIT_CANNOT_START = 2
EXIT_UNREADABLE_LINE = 3


class Engine(Protocol):
    """The part of ``kokoro_onnx.Kokoro`` the worker uses."""

    def get_voices(self) -> list[str]: ...

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ProbOS resident Kokoro worker (AD-738g)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--default-voice", required=True)
    return parser


def lang_for(voice: str) -> str:
    """kokoro-onnx's language for a voice id: ``b?_`` voices are British English, the rest American."""
    return "en-gb" if voice.startswith("b") else "en-us"


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


def read_request(raw: bytes) -> dict[str, Any]:
    """One request line. Raises ``ValueError`` unless it is a JSON object with string ``text`` and ``output_file``."""
    request = json.loads(raw.decode("ascii"))
    if (
        not isinstance(request, dict)
        or not isinstance(request.get("text"), str)
        or not isinstance(request.get("output_file"), str)
        or not request["output_file"]
    ):
        raise ValueError("a request needs a string text and a non-empty string output_file")
    return request


def speak(engine: Engine, voices: frozenset[str], default_voice: str, request: dict[str, Any], log: IO[str]) -> bool:
    """Synthesize one request into its output file. True when a file was written; never raises."""
    text: str = request["text"]
    voice = request.get("voice")
    if not isinstance(voice, str) or voice not in voices:
        if voice is not None:
            _log(log, f"AD-738g: voice {voice!r} is not in the voices file; speaking {default_voice}")
        voice = default_voice
    try:
        samples, rate = engine.create(text, voice=voice, speed=float(request.get("speed", 1.0)), lang=lang_for(voice))
        write_wav(Path(request["output_file"]), samples, rate)
        return True
    except Exception as exc:  # one request: answer with the path and no file, keep serving (contract D2)
        _log(log, f"AD-738g: no audio for {len(text)} chars in {voice}: {type(exc).__name__}: {exc}")
        return False


def serve(engine: Engine, stdin: IO[bytes], stdout: IO[bytes], *, default_voice: str, log: IO[str]) -> int:
    """Answer request lines until end of input (0), an unreadable line (3) or a missing default voice (2)."""
    voices = frozenset(engine.get_voices())
    if default_voice not in voices:
        _log(log, f"AD-738g: default voice {default_voice!r} is not in the voices file; refusing to start")
        return EXIT_CANNOT_START
    _log(log, f"AD-738g: kokoro worker ready ({len(voices)} voices, default {default_voice})")
    while True:
        raw = stdin.readline()
        if not raw:
            return 0
        if not raw.strip():
            continue
        try:
            request = read_request(raw)
        except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            _log(log, f"AD-738g: unreadable request line; exiting: {exc}")
            return EXIT_UNREADABLE_LINE
        speak(engine, voices, default_voice, request, log)
        stdout.write(request["output_file"].encode("utf-8") + b"\n")
        stdout.flush()


def load_engine(args: argparse.Namespace) -> Engine:
    """kokoro-onnx on the CPU with ``args.threads`` intra-op threads (measured RTF 0.314 at 4 on a 7950X3D)."""
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(args.model, sess_options=options, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(session, args.voices)


def main(
    argv: list[str] | None = None,
    *,
    engine_factory: Callable[[argparse.Namespace], Engine] = load_engine,
) -> int:
    args = build_parser().parse_args(argv)
    protocol = sys.stdout.buffer
    log = sys.stderr
    sys.stdout = sys.stderr  # a library print can never reach the protocol pipe
    try:
        engine = engine_factory(args)
    except Exception as exc:
        _log(log, f"AD-738g: cannot load the Kokoro model: {type(exc).__name__}: {exc}")
        return EXIT_CANNOT_START
    return serve(engine, sys.stdin.buffer, protocol, default_voice=args.default_voice, log=log)


def _log(log: IO[str], message: str) -> None:
    print(message, file=log, flush=True)


if __name__ == "__main__":
    sys.exit(main())
```

### 6.3 `tests/fixtures/fake_kokoro_worker.py` (new, M2)

```python
"""AD-738g (#1662): the real Kokoro worker loop with a stand-in engine, for tests.

Run exactly as the service runs the real worker: ``python -I <this file> --model M --voices V
--threads N --default-voice D``. Only the engine is fake: ``scripts/kokoro_worker.py``'s own
``main`` parses the arguments, moves library prints off stdout, reads each JSON line, picks
the voice and language, writes the WAV and prints the path. The fake engine has no model, so
``--model`` names a file where it appends one JSON line per call (text, voice, speed, lang and
this process's pid). Nothing here needs kokoro-onnx; numpy is a ProbOS dependency.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

WORKER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "kokoro_worker.py"
VOICES: tuple[str, ...] = ("af_heart", "af_bella", "bf_emma", "bm_fable", "am_liam")
RATE = 24000


def load_worker() -> Any:
    """``scripts/kokoro_worker.py`` as a module, loaded by path (``-I`` puts no script directory on ``sys.path``)."""
    spec = importlib.util.spec_from_file_location("kokoro_worker", WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeEngine:
    """kokoro-onnx 0.6.1's checks, measured 2026-11-27: an unknown voice, a speed outside [0.5, 2.0]
    and a text with no phonemes raise ``ValueError``. A voice's audio is 0.05 s per catalogue
    position (``af_heart`` 0.05 s, ``bm_fable`` 0.2 s), so a WAV's length shows which voice spoke."""

    def __init__(self, record: Path | None = None, voices: tuple[str, ...] = VOICES) -> None:
        self.record = record
        self.voices = voices
        self.calls: list[dict[str, Any]] = []

    def get_voices(self) -> list[str]:
        return list(self.voices)

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]:
        call = {"text": text, "voice": voice, "speed": speed, "lang": lang, "pid": os.getpid()}
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
    sys.exit(worker.main(engine_factory=lambda args: FakeEngine(Path(args.model))))
```

### 6.4 `src/probos/audio/tts/kokoro_backend.py` (new, M3)

```python
"""AD-738g (#1662) S1: Kokoro speech on this machine, from a resident worker process.

The worker (``scripts/kokoro_worker.py``) runs ``kokoro-onnx`` in the operator's venv under
``tools/kokoro/`` (installed by ``scripts/kokoro-fetch.ps1``; ``/tools/`` is gitignored) and
speaks Piper's line protocol, so the runtime's ``VoiceSynthesisService`` (BF-918) owns its
start, restart, timeout and stop. One process serves every voice: the voice and the speed
travel on each request line.

License posture: kokoro-onnx and onnxruntime are MIT and the Kokoro-82M weights Apache-2.0;
the phonemizer (GPL-3.0-or-later) and the espeak-ng library it loads (GPL-3.0-or-later) run
only in that separate process, which receives text, a voice id and a speed and returns a WAV
file path. Nothing in ProbOS imports them (THIRD_PARTY_LICENSES.md, "License policy").

Tier-2 log-and-degrade: ``synthesize`` returns ``None`` on any failure, and the browser speaks.
"""

from __future__ import annotations

import logging
import time
from typing import get_args

from probos.audio.tts.backends import TTSResult
from probos.audio.tts.piper_backend import anchor_install_path, resolve_executable_path
from probos.audio.tts.prosody import resolve_prosody_overrides
from probos.audio.tts.resident import KokoroWorkerKey, VoiceSynthesisService
from probos.config import KokoroTTSConfig

logger = logging.getLogger(__name__)

#: The worker script, relative to the ProbOS root (AD-1025 anchoring).
WORKER_SCRIPT = "scripts/kokoro_worker.py"
#: The voices the backend sends: the English ids of ``KokoroTTSConfig.voice``'s ``Literal`` (one source).
KOKORO_VOICES: frozenset[str] = frozenset(get_args(KokoroTTSConfig.model_fields["voice"].annotation))
#: kokoro-onnx raises ``ValueError`` for a speed outside this range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0


def kokoro_speed(base: float, emotion: str | None) -> float:
    """AD-738e-1's per-emotion ``length_scale`` as a Kokoro speed: ``base / length_scale``, clamped."""
    length_scale = resolve_prosody_overrides(emotion).get("length_scale", 1.0)
    return min(SPEED_MAX, max(SPEED_MIN, base / length_scale))


class KokoroBackend:
    """Kokoro TTS backend (``tts.backend: kokoro``): a 24 kHz 16-bit mono WAV, or ``None`` to degrade."""

    name: str = "kokoro"

    def __init__(self, config: KokoroTTSConfig, service: VoiceSynthesisService | None = None) -> None:
        self._config = config
        # BF-918: the runtime's resident synthesis; without it Kokoro degrades to the browser.
        self._service = service

    def resolve_voice(self, voice_override: str | None) -> str:
        """The voice for one call: a catalogue override (the HXI picker, an AD-718a proposal), else ``tts.kokoro.voice``.

        A name the catalogue lacks (a Piper or browser voice name) is ignored. AD-738f (#1868)
        adds the per-role default between the two.
        """
        if voice_override is not None and voice_override in KOKORO_VOICES:
            return voice_override
        return self._config.voice

    async def synthesize(
        self,
        text: str,
        emotion: str | None = None,
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """WAV bytes from the resident Kokoro worker, or ``None`` on any failure. NEVER raises."""
        if not text or not text.strip():
            return None
        if self._service is None:
            logger.warning("AD-738g: no voice synthesis service on this runtime; degrading to browser")
            return None
        cfg = self._config
        python = resolve_executable_path(cfg.python_path)
        script = anchor_install_path(WORKER_SCRIPT)
        model = anchor_install_path(cfg.model_path)
        voices = anchor_install_path(cfg.voices_path)
        missing = [str(path) for path in (script, model, voices) if not path.is_file()]
        if python is None:
            missing.insert(0, str(anchor_install_path(cfg.python_path)))
        if python is None or missing:
            logger.warning(
                "AD-738g: kokoro is not installed (missing: %s); run scripts/kokoro-fetch.ps1 or set "
                "tts.kokoro.* (relative paths anchor to the ProbOS root); degrading to browser",
                ", ".join(missing),
            )
            return None
        voice = self.resolve_voice(voice_override)
        speed = kokoro_speed(cfg.speed, emotion)
        key = KokoroWorkerKey(
            python=str(python),
            script=str(script),
            model=str(model),
            voices=str(voices),
            threads=cfg.threads,
            default_voice=cfg.voice,
        )
        started = time.perf_counter()
        wav = await self._service.synthesize(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed})
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded",
        )
        if wav is None:
            return None
        return TTSResult(audio_bytes=wav, mime="audio/wav")
```

### 6.5 `src/probos/audio/tts/piper_backend.py` (M3)

**P5.1** SEARCH:
```python
    location regardless of the process CWD. Absolute as-is; relative under
    ``_probos_root()``; NEVER the CWD. NEVER raises."""
    return _anchor_path(voices_dir)
```
REPLACE:
```python
    location regardless of the process CWD. Absolute as-is; relative under
    ``_probos_root()``; NEVER the CWD. NEVER raises."""
    return _anchor_path(voices_dir)


def anchor_install_path(configured: str) -> Path:
    """AD-738g: ``_anchor_path`` for the sibling Kokoro backend (AD-1025: absolute as-is,
    relative under ``_probos_root()``, never the CWD). NEVER raises."""
    return _anchor_path(configured)


def resolve_executable_path(configured: str) -> Path | None:
    """AD-738g: ``_resolve_binary_path`` for the sibling Kokoro backend (anchored; ``.exe``
    appended on Windows when the literal path is missing). ``None`` when not found. NEVER raises."""
    return _resolve_binary_path(configured)
```

### 6.6 `src/probos/config_models/experience.py` (M3)

**P6.1** SEARCH:
```python
class LipSyncConfig(BaseModel):
```
REPLACE:
```python
#: AD-738g (#1662): the English Kokoro-82M voices (hexgrad/Kokoro-82M VOICES.md, read 2026-11-27):
#: 20 American English (``a?_``) and 8 British English (``b?_``). The worker derives the
#: language from the prefix, so a non-English voice is not offered.
KokoroVoiceId = Literal[
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole",
    "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]


class KokoroTTSConfig(BaseModel):
    """AD-738g (#1662) S1 -- the local Kokoro backend, read when ``tts.backend`` is ``kokoro``.

    The operator installs the runtime and the model with ``scripts/kokoro-fetch.ps1``
    (``tools/kokoro/``, gitignored). Relative paths anchor to the ProbOS install root, never
    the process CWD (AD-1025). Kokoro runs on the CPU in one resident worker process; any
    failure degrades to the browser voice.
    """

    python_path: str = "tools/kokoro/venv/Scripts/python"
    """The operator venv's interpreter (``.exe`` appended on Windows). On Linux or macOS set
    ``tools/kokoro/venv/bin/python``."""

    model_path: str = "tools/kokoro/kokoro-v1.0.onnx"
    """The Kokoro-82M ONNX model (Apache-2.0 weights; release ``model-files-v1.0``)."""

    voices_path: str = "tools/kokoro/voices-v1.0.bin"
    """The voices file of the same release."""

    voice: KokoroVoiceId = "af_heart"
    """The ship's voice, and the worker's default when a request's voice is missing from the
    voices file. A per-call ``voice_name`` that is one of these ids overrides it."""

    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    """Speech rate (kokoro-onnx accepts 0.5 to 2.0). The AD-738e-1 per-emotion ``length_scale``
    divides it, clamped to the same range."""

    threads: int = Field(default=4, ge=1, le=16)
    """ONNX Runtime intra-op threads. Measured on a Ryzen 9 7950X3D: real-time factor 0.314
    at 4, 0.23 at 8, 0.181 at 16. 4 leaves the cores to the vessel."""

    timeout_seconds: float = Field(default=30.0, gt=0.0)
    """Per-sentence timeout, counted from when the worker takes the request. A timeout kills
    the worker, and the next sentence reloads the model (about 3.2 s cold)."""


class LipSyncConfig(BaseModel):
```

**P6.2** SEARCH:
```python
    backend: Literal["browser", "piper"] = "browser"
    """``browser``: server returns ``{"backend": "disabled"}``, browser
    uses SpeechSynthesisUtterance (default — zero behaviour change for
    operators who don't install Piper). ``piper``: subprocess wrapper
    around the piper binary."""
```
REPLACE:
```python
    backend: Literal["browser", "piper", "kokoro"] = "browser"
    """``browser``: server returns ``{"backend": "disabled"}``, browser
    uses SpeechSynthesisUtterance (default — zero behaviour change for
    operators who don't install Piper). ``piper``: subprocess wrapper
    around the piper binary. ``kokoro`` (AD-738g): a resident Kokoro
    worker on this machine's CPU, configured under ``kokoro``."""
```

**P6.3** SEARCH:
```python
    When ``True`` AND the backend is ``piper`` AND a reply contains more
```
REPLACE:
```python
    When ``True`` AND the backend is a server backend (``piper`` or
    ``kokoro``; AD-738g recommends it with ``kokoro``) AND a reply contains more
```

**P6.4** SEARCH:
```python
    ``GET /api/avatars/tts/status`` so the browser can read it via its
    existing one-time status probe."""


class WakeWordConfig(BaseModel):
```
REPLACE:
```python
    ``GET /api/avatars/tts/status`` so the browser can read it via its
    existing one-time status probe."""

    kokoro: KokoroTTSConfig = Field(default_factory=KokoroTTSConfig)
    """AD-738g (#1662): the local Kokoro backend's settings, read when
    ``backend`` is ``kokoro``."""


class WakeWordConfig(BaseModel):
```

### 6.7 `src/probos/config_models/__init__.py` (M3)

**P7.1** SEARCH:
```python
    KnowledgeBrowserConfig,
    LipSyncConfig,
    OnboardingConfig,
```
REPLACE:
```python
    KnowledgeBrowserConfig,
    KokoroTTSConfig,
    LipSyncConfig,
    OnboardingConfig,
```

**P7.2** SEARCH:
```python
    "KnowledgeLoadingConfig",
    "LLMRateConfig",
```
REPLACE:
```python
    "KnowledgeLoadingConfig",
    "KokoroTTSConfig",
    "LLMRateConfig",
```
(`__all__` is sorted and must equal the sorted imports: `tests/test_ad1270e2e_operations_models.py`:615-627.)

### 6.8 `src/probos/config.py` (M3)

**P8.1** SEARCH:
```python
    KnowledgeBrowserConfig,
    LipSyncConfig,
    OnboardingConfig,
```
REPLACE:
```python
    KnowledgeBrowserConfig,
    KokoroTTSConfig,
    LipSyncConfig,
    OnboardingConfig,
```

### 6.9 Regenerations and the two config tests (M3, after 6.6 to 6.8)

Run, from the worktree root, in this order:
```text
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
```
Expected counts (precedent: AD-1346 M3c, commit `0c859b90`, one model and two fields): one owned model and eight fields (`KokoroTTSConfig`'s seven and `TTSConfig.kokoro`): `names=311, owned=298, incidental=13, models=230, fields=1885`. If the checker prints other numbers, stop and report. `check_config_profiles.py --check` must pass unchanged (no new `bool` field).

**P9.1** `tests/test_ad1270e1_config_facade.py`. SEARCH:
```python
    assert counts["public_names"] == 310  # #1414 A3: drop_null_sections
    assert counts["owned"] == 297  # #1414 A3: drop_null_sections is owned
    assert counts["incidental"] == 13
    assert counts["own_models"] == 228  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig
```
REPLACE:
```python
    # AD-738g S1 (#1662) adds the owned model KokoroTTSConfig: public_names 310 -> 311, owned 297 -> 298,
    # own_models 228 -> 229, and the check prints names=311.
    assert counts["public_names"] == 311  # AD-738g S1 (#1662): KokoroTTSConfig
    assert counts["owned"] == 298  # AD-738g S1 (#1662): KokoroTTSConfig is owned
    assert counts["incidental"] == 13
    assert counts["own_models"] == 229  # AD-738g S1 (#1662): KokoroTTSConfig
```

**P9.2** same file. SEARCH:
```python
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    assert counts["field_definitions"] == 1877  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    # AD-738g S1 (#1662) adds KokoroTTSConfig's seven fields and TTSConfig.kokoro (1877 -> 1885).
    assert counts["field_definitions"] == 1885  # AD-1206 intentionally adds github_repository.
```

**P9.3** same file. SEARCH:
```python
    assert len(baseline["names"]) == 310  # #1414 A3: drop_null_sections (309 -> 310)
    assert len(baseline["models"]) == 229  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig (230 -> 229)
```
REPLACE:
```python
    # AD-738g S1 (#1662) adds KokoroTTSConfig (310 -> 311, 229 -> 230).
    assert len(baseline["names"]) == 311  # AD-738g S1 (#1662): KokoroTTSConfig (310 -> 311)
    assert len(baseline["models"]) == 230  # AD-738g S1 (#1662): KokoroTTSConfig (229 -> 230)
```

**P9.4** `tests/test_ad1270e2c_experience_models.py`. SEARCH:
```python
                     'sentence_silence': 0.35,
                     'sentence_pipelining_enabled': False},
```
REPLACE:
```python
                     'sentence_silence': 0.35,
                     'sentence_pipelining_enabled': False,
                     # AD-738g S1 (#1662) adds the nested Kokoro section after the
                     # pre-move fields; these are KokoroTTSConfig's own defaults.
                     'kokoro': {   'python_path': 'tools/kokoro/venv/Scripts/python',
                                   'model_path': 'tools/kokoro/kokoro-v1.0.onnx',
                                   'voices_path': 'tools/kokoro/voices-v1.0.bin',
                                   'voice': 'af_heart',
                                   'speed': 1.0,
                                   'threads': 4,
                                   'timeout_seconds': 30.0}},
```

**P9.5** same file. SEARCH:
```python
    [("TTSConfig", "piper"), ("LipSyncConfig", "rhubarb")],
```
REPLACE:
```python
    # AD-738g S1 (#1662): "kokoro" joins the TTS backend Literal; "espeak" stays rejected below.
    [("TTSConfig", "piper"), ("TTSConfig", "kokoro"), ("LipSyncConfig", "rhubarb")],
```

### 6.10 `src/probos/audio/tts/__init__.py` and `src/probos/settings/section_registry.py` (M3)

**P10.1** `audio/tts/__init__.py`. SEARCH:
```python
from probos.audio.tts.backends import TTSBackend, TTSResult
from probos.audio.tts.null_backend import NullBackend
from probos.audio.tts.piper_backend import PiperBackend
```
REPLACE:
```python
from probos.audio.tts.backends import TTSBackend, TTSResult
from probos.audio.tts.kokoro_backend import KokoroBackend
from probos.audio.tts.null_backend import NullBackend
from probos.audio.tts.piper_backend import PiperBackend
```

**P10.2** SEARCH:
```python
    if backend_name == "browser":
        return NullBackend()
```
REPLACE:
```python
    if backend_name == "kokoro":
        # AD-738g (#1662): a resident Kokoro worker on this machine's CPU.
        return KokoroBackend(config.kokoro, service=service)
    if backend_name == "browser":
        return NullBackend()
```

**P10.3** SEARCH:
```python
__all__ = ["TTSBackend", "TTSResult", "NullBackend", "PiperBackend", "select_backend"]
```
REPLACE:
```python
__all__ = ["TTSBackend", "TTSResult", "NullBackend", "PiperBackend", "KokoroBackend", "select_backend"]
```

**P10.4** `settings/section_registry.py`. SEARCH:
```python
                "tts.backend",
                "TTS backend",
                "enum",
                enum_values=("browser", "piper"),
```
REPLACE:
```python
                "tts.backend",
                "TTS backend",
                "enum",
                enum_values=("browser", "piper", "kokoro"),
```

### 6.11 `src/probos/routers/avatars.py` and `ui/src/audio/voice.ts` (M3)

**P11.1** `routers/avatars.py` (docstring only). SEARCH:
```python
    The browser caches this response in module-level state in ``voice.ts``
    and skips ``POST /api/avatars/tts`` entirely when ``backend != "piper"``.
```
REPLACE:
```python
    The browser caches this response in module-level state in ``voice.ts``
    and skips ``POST /api/avatars/tts`` entirely when ``backend == "browser"``
    (AD-738g: ``piper`` and ``kokoro`` both take the server path).
```

**P11.2** `ui/src/audio/voice.ts`. SEARCH:
```ts
  // Fast synchronous path: if fetch is unavailable OR the cached probe
  // already says "not piper", run the browser fallback synchronously.
```
REPLACE:
```ts
  // Fast synchronous path: if fetch is unavailable OR the cached probe
  // already says "browser" (AD-738g: any other backend is a server one), run
  // the browser fallback synchronously.
```

**P11.3** SEARCH:
```ts
  if (_ttsStatus !== null && (!_ttsStatus.enabled || _ttsStatus.backend !== 'piper')) {
```
REPLACE:
```ts
  if (_ttsStatus !== null && (!_ttsStatus.enabled || _ttsStatus.backend === 'browser')) {
```

**P11.4** SEARCH:
```ts
    // probe once, cache, and skip the POST entirely when backend != "piper".
```
REPLACE:
```ts
    // probe once, cache, and skip the POST entirely when backend == "browser"
    // (AD-738g: piper and kokoro both take the server path, as the server's gate does).
```

**P11.5** SEARCH:
```ts
    if (status === null || !status.enabled || status.backend !== 'piper') {
```
REPLACE:
```ts
    if (status === null || !status.enabled || status.backend === 'browser') {
```

### 6.12 `scripts/kokoro-fetch.ps1` (new, M4)

```powershell
# scripts/kokoro-fetch.ps1
# AD-738g (#1662) S1: install the local Kokoro voice into tools/kokoro/ (gitignored).
#
#   1. A Python 3.12 venv at tools/kokoro/venv made by uv, holding kokoro-onnx==0.6.1
#      (MIT) and what it pulls: onnxruntime (MIT), numpy, phonemizer (GPL-3.0-or-later)
#      and espeakng-loader (bundles espeak-ng, GPL-3.0-or-later). This venv is separate
#      from ProbOS's and cannot import probos; ProbOS never imports these packages.
#   2. The Kokoro-82M model files (Apache-2.0 weights) from the kokoro-onnx release
#      model-files-v1.0, each checked for its size and SHA-256 (the release publishes no
#      digests; the pins are the LFS ids of the byte-identical files on
#      huggingface.co/fastrtc/kokoro-onnx, and matched a download on 2026-11-27).
#   3. One test sentence spoken through scripts/kokoro_worker.py, the worker ProbOS runs.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -Force   # rebuild the venv, re-download
#
param(
    [switch]$Force,
    [string]$DestDir = "tools/kokoro"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is many times slower with its progress bar

$Root = Split-Path -Parent $PSScriptRoot
if (-not [System.IO.Path]::IsPathRooted($DestDir)) { $DestDir = Join-Path $Root $DestDir }
$Pin = "kokoro-onnx==0.6.1"
$Base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
$Files = @(
    @{ name = "kokoro-v1.0.onnx"; size = 325532387; sha256 = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5" }
    @{ name = "voices-v1.0.bin";  size = 28214398;  sha256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" }
)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required (https://docs.astral.sh/uv/). Install it, then run this script again."
}
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

# 1. The venv and the pinned runtime.
$Venv = Join-Path $DestDir "venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if ($Force -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
if (-not (Test-Path $Python)) {
    & uv venv --python 3.12 $Venv
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed (exit $LASTEXITCODE)" }
}
& uv pip install --python $Python $Pin
if ($LASTEXITCODE -ne 0) { throw "uv pip install $Pin failed (exit $LASTEXITCODE)" }

# 2. The model files, size- and hash-checked; a mismatch deletes the download and stops.
foreach ($f in $Files) {
    $target = Join-Path $DestDir $f.name
    if (-not $Force -and (Test-Path $target) -and ((Get-FileHash $target -Algorithm SHA256).Hash.ToLower() -eq $f.sha256)) {
        Write-Host "[skip] $($f.name) (present, SHA-256 verified)" -ForegroundColor DarkGray
        continue
    }
    $part = "$target.part"
    Write-Host "[get ] $($f.name) ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri "$Base/$($f.name)" -OutFile $part -UseBasicParsing
    $size = (Get-Item $part).Length
    $actual = (Get-FileHash $part -Algorithm SHA256).Hash.ToLower()
    if ($size -ne $f.size -or $actual -ne $f.sha256) {
        Remove-Item $part -Force
        throw "Mismatch for $($f.name): expected $($f.size) bytes, SHA-256 $($f.sha256); got $size bytes, $actual. File removed."
    }
    Move-Item -Force $part $target
    Write-Host "[ ok ] $($f.name) (SHA-256 verified: $actual)" -ForegroundColor Green
}

# 3. The boundary and one spoken line through the real worker.
# Windows PowerShell 5.1 turns a redirected native stderr line into an error record, which
# "Stop" would make terminating; the expected ImportError traceback must not end the script.
$Previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -I -c "import probos" 2>$null
$Importable = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $Previous
if ($Importable) { throw "The Kokoro venv can import probos; it must not (licence boundary)." }
Write-Host "[ ok ] the Kokoro venv cannot import probos" -ForegroundColor Green

$Model = Join-Path $DestDir "kokoro-v1.0.onnx"
$Voices = Join-Path $DestDir "voices-v1.0.bin"
$Worker = Join-Path $Root "scripts\kokoro_worker.py"
$Probe = Join-Path $DestDir "fetch-check.wav"
if (Test-Path $Probe) { Remove-Item $Probe -Force }
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + (ConvertTo-Json $Probe) + ', "voice": "af_heart", "speed": 1.0}'
$Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $LASTEXITCODE, answer '$Answer'); its messages are above."
}
$Bytes = (Get-Item $Probe).Length
Remove-Item $Probe -Force
Write-Host "[ ok ] the Kokoro worker spoke the test line ($Bytes bytes of 24 kHz WAV)" -ForegroundColor Green
Write-Host ""
Write-Host "Kokoro is installed at: $DestDir" -ForegroundColor White
Write-Host "Set tts.backend: kokoro and tts.sentence_pipelining_enabled: true in config/system.yaml, then restart." -ForegroundColor White
```

### 6.13 `THIRD_PARTY_LICENSES.md` (M4)

Append at the end of the file (after the `## openWakeWord (AD-705c)` section, line 167):

```markdown

## Kokoro speech: kokoro-onnx, Kokoro-82M, and its phonemizer (AD-738g)

- Projects: <https://github.com/thewh1teagle/kokoro-onnx> (kokoro-onnx 0.6.1, MIT), <https://huggingface.co/hexgrad/Kokoro-82M> (weights, Apache-2.0), <https://github.com/microsoft/onnxruntime> (MIT), <https://github.com/bootphon/phonemizer> (phonemizer 3.6.0, GPL-3.0-or-later per its package metadata), espeak-ng (GPL-3.0-or-later; bundled as `espeak-ng.dll` and `espeak-ng-data` by `espeakng-loader` 0.2.4, whose wheel ships no licence file).
- Used by: `scripts/kokoro_worker.py`, a ProbOS-authored worker that runs in a separate process. `src/probos/audio/tts/kokoro_backend.py` starts it through the resident voice service (`src/probos/audio/tts/resident.py`) and exchanges only text, a voice id and a speed in, and a WAV file path out (one JSON line each way).
- Installation: **not** in `pyproject.toml`. The operator runs `scripts/kokoro-fetch.ps1`, which makes a separate venv at `tools/kokoro/venv` (gitignored under `/tools/`) with `uv pip install kokoro-onnx==0.6.1`, and downloads `kokoro-v1.0.onnx` (325,532,387 B) and `voices-v1.0.bin` (28,214,398 B) from the kokoro-onnx release `model-files-v1.0`, SHA-256 pinned.
- License posture (policy above): the GPL components are installed by the operator, run only in that separate process and are never imported into the ProbOS process, vendored or committed. The worker runs under `python -I`, so it cannot import `probos` (the install script checks it), and the ProbOS venv does not contain these packages. The boundary is a simple request/response exchange. The weights are Apache-2.0.
```

### 6.14 `docs/development/roadmap.md` and `docs/research/reference-projects.md` (M4)

**P14.1** `roadmap.md` (line 827; the em dash is existing text). SEARCH:
```markdown
| AD-738g | Kokoro speech backend, local or LAN Mac, timing-derived lip-sync (Kokoro Apache 2.0 behind the TTSBackend Protocol; StyleTTS2 rejected as a separate engine) — renumbered from AD-738b (Wave 158); PAUSED | [#1662](https://github.com/seangalliher/ProbOS/issues/1662) | 4 |
```
REPLACE:
```markdown
| AD-738g | Kokoro speech backend, local or LAN Mac, timing-derived lip-sync (Kokoro Apache 2.0 behind the TTSBackend Protocol; StyleTTS2 rejected as a separate engine) — renumbered from AD-738b (Wave 158) | [#1662](https://github.com/seangalliher/ProbOS/issues/1662) | 4 |
```
(Row 826's issue column is the AD-738f contract's edit, not this one.)

**P14.2** `reference-projects.md`. SEARCH:
```markdown
| Kokoro / misaki / HeadTTS / mlx-audio | 2026-10-25 | checked | AD-738g (#1662) Prior Art |
```
REPLACE:
```markdown
| Kokoro / misaki / HeadTTS / mlx-audio | 2026-11-27 | checked | AD-738g (#1662) Prior Art; S1 contract `prompts/ad-738g-s1-local-kokoro-voice.md`: kokoro-onnx 0.6.1 and its dependencies (phonemizer GPL-3; espeakng-loader bundles espeak-ng with no licence file), model-files-v1.0 hashes from the Hugging Face LFS ids, and `kokoro-v1.0.onnx` has no `duration` output (no synthesizer timings) |
```

### 6.15 `tests/test_ad738g_kokoro_voice.py` (new; R1-R4 in M1, W1-W8 and R5-R7 in M2, the rest in M3)

The Builder writes the file in the order below, adding each group in its milestone. Every case is `async` with `@pytest.mark.asyncio` where it awaits (the style of `tests/test_bf918_tts_latency.py`). No assertion reads a clock. Shared code, at the top of the file:

```python
"""AD-738g (#1662) S1: a local Kokoro voice behind the TTS backend seam.

Real ``VoiceSynthesisService``, ``KokoroBackend``, routes, store and config. The worker
loop is the real ``scripts/kokoro_worker.py``; only its engine is a stand-in
(``tests/fixtures/fake_kokoro_worker.py``), run as a real ``python -I`` subprocess where a
case says so. Nothing here needs kokoro-onnx. No assertion reads a clock.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import logging
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import KokoroBackend, PiperBackend, TTSResult, select_backend
from probos.audio.tts import kokoro_backend, resident
from probos.audio.tts.kokoro_backend import KOKORO_VOICES, kokoro_speed
from probos.audio.tts.resident import KokoroWorkerKey, PiperWorkerKey, VoiceSynthesisService
from probos.config import AttachmentsConfig, KokoroTTSConfig, LipSyncConfig, TTSConfig
from probos.execution.command_env import trusted_command_env
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.settings.section_registry import get_section
from tests.fixtures.fake_kokoro_worker import FakeEngine, load_worker
from tests.fixtures.fake_piper import FakePiperLauncher

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
_FIELDS = {"voice": "bf_emma", "speed": 1.0}
worker = load_worker()


def _piper_key() -> PiperWorkerKey:
    return PiperWorkerKey(binary="piper", model="m.onnx", noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35)


def _kokoro_key() -> KokoroWorkerKey:
    return KokoroWorkerKey(python="py", script="w.py", model="m.onnx", voices="v.bin", threads=4, default_voice="af_heart")


def _line(request: dict) -> bytes:
    return json.dumps(request).encode("ascii") + b"\n"


def _wav(data: bytes) -> tuple[int, int, int, bytes]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        return handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.readframes(handle.getnframes())


def _real_key(tmp_path: Path, default_voice: str = "af_heart") -> tuple[KokoroWorkerKey, Path]:
    """A key that runs the real worker loop with the fake engine; the engine logs its calls to ``record``."""
    record = tmp_path / "engine-calls.jsonl"
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    key = KokoroWorkerKey(
        python=sys.executable, script=str(FAKE_WORKER), model=str(record), voices=str(voices),
        threads=1, default_voice=default_voice,
    )
    return key, record


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch):
    def _install(*modes: str):
        fake = FakePiperLauncher(*modes, wav=_WAV)
        monkeypatch.setattr(resident.subprocess, "Popen", fake)
        return fake
    return _install


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


class _RecordingService:
    """Stands in for the service where a case asks only what the backend sends."""

    def __init__(self, wav: bytes | None = b"RIFF") -> None:
        self.wav = wav
        self.calls: list[tuple] = []

    async def synthesize(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return self.wav


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> KokoroTTSConfig:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"\x00")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    values = {"python_path": sys.executable, "model_path": str(model), "voices_path": str(voices)}
    values.update(overrides)
    return KokoroTTSConfig(**values)
```

Named cases and what each asserts (the Builder writes the bodies; each assertion listed is required):

**Resident service (M1; `launcher` and `service` fixtures)**
- R1 `test_r1_a_piper_line_without_fields_has_exactly_text_and_output_file`: `launcher("ok")`; `await service.synthesize(_piper_key(), "Hello\nthere", 5.0) == _WAV`; the fake's first request has `list(request) == ["text", "output_file"]` and `request["text"] == "Hello there"`.
- R2 `test_r2_fields_follow_the_line_and_never_replace_text_or_output_file`: `launcher("ok")`; `synthesize(_kokoro_key(), "Hi.", 5.0, fields={"text": "evil", "output_file": "x", "voice": "bf_emma", "speed": 1.25})`; the request has `list(request) == ["text", "output_file", "voice", "speed"]`, `text == "Hi."`, `output_file != "x"`, `voice == "bf_emma"`, `speed == 1.25`.
- R3 `test_r3_a_kokoro_worker_that_answers_without_audio_stays_resident`: `launcher("empty")`; two `synthesize(_kokoro_key(), "Hi.", 5.0, fields=_FIELDS)` both return `None`; `len(fake.launched) == 1`, `fake.launched[0].returncode is None`, `service.resident_count == 1`; WARNING text contains `kokoro produced 0 bytes`. (Piper's opposite stays pinned by `test_bf918_tts_latency.py::test_an_empty_wav_degrades`.)
- R4 `test_r4_a_kokoro_key_launches_the_isolated_worker_with_the_trusted_environment`: `launcher("ok")`; one synthesize; `fake.launched[0].args == ["py", "-I", "w.py", "--model", "m.onnx", "--voices", "v.bin", "--threads", "4", "--default-voice", "af_heart"]`; `fake.launched[0].kwargs["env"] == trusted_command_env()`; INFO text contains `BF-918: resident kokoro started (voice=m)`.

**Worker loop in process (M2; `worker = load_worker()`)**
- W1 `test_w1_the_worker_writes_a_24khz_mono_16bit_wav_and_prints_its_path`: an engine (a small class in the test) whose `get_voices()` is `["af_heart"]` and whose `create` returns `(numpy.array([0.5, 1.5, -1.5], dtype=numpy.float32), 24000)`; `serve(engine, io.BytesIO(_line({"text": "Hi.", "output_file": str(out), "voice": "af_heart", "speed": 1.0})), stdout, default_voice="af_heart", log=io.StringIO()) == 0`; `stdout.getvalue() == str(out).encode("utf-8") + b"\n"`; `_wav(out.read_bytes())[:3] == (1, 2, 24000)` and `struct.unpack("<3h", frames) == (16383, 32767, -32767)`; no `out.name + ".part"` file remains.
- W2 `test_w2_the_language_follows_the_voice_prefix`: `FakeEngine()`; two lines for `bf_emma` and `af_heart`; `[c["lang"] for c in engine.calls] == ["en-gb", "en-us"]`.
- W3 `test_w3_a_voice_the_file_lacks_is_spoken_in_the_default_voice`: a line with `"voice": "zz_nobody"`; `engine.calls[0]["voice"] == "af_heart"`; the file is written; the log contains `'zz_nobody' is not in the voices file`.
- W4 `test_w4_an_engine_error_is_answered_with_the_path_and_no_file_and_the_loop_continues`: lines `{"text": "   ", output_file a}` then `{"text": "Hello.", output_file b}`; return 0; stdout holds both paths in order; `a` does not exist, `b` does; the log contains `no audio for 3 chars`.
- W5 `test_w5_a_default_voice_the_file_lacks_refuses_to_start`: `FakeEngine(voices=("af_bella",))`, `default_voice="af_heart"`, one valid line; return `2`; stdout empty; `engine.calls == []`; the log contains `refusing to start`.
- W6 `test_w6_an_unreadable_line_ends_the_worker`: input `b"not json\n"` followed by a valid line; return `3`; stdout empty; `engine.calls == []`.
- W7 `test_w7_main_keeps_library_prints_off_the_protocol_pipe`: monkeypatch `sys.stdin` to `io.TextIOWrapper(io.BytesIO(_line({"text": "CHATTER", "output_file": str(out), "voice": "af_heart"})), encoding="ascii")`, `sys.stdout` to `io.TextIOWrapper(io.BytesIO(), encoding="utf-8")` (keep a reference) and `sys.stderr` to `io.StringIO()`; `worker.main(["--model", "m", "--voices", "v", "--default-voice", "af_heart"], engine_factory=lambda args: FakeEngine()) == 0`; the stdout wrapper's `.buffer.getvalue() == str(out).encode("utf-8") + b"\n"`; the stderr text contains `library chatter on stdout`.
- W8 `test_w8_the_worker_imports_only_the_stdlib_and_numpy_at_module_level_and_src_never_imports_the_engine`: `ast.parse` of `scripts/kokoro_worker.py`; the module-level `Import`/`ImportFrom` top-level names are a subset of `{"__future__", "argparse", "json", "os", "sys", "wave", "pathlib", "typing", "numpy"}`; `kokoro_onnx` and `onnxruntime` are imported only inside `load_engine`; and no `.py` file under `src/probos` contains an `import`/`from` of `kokoro_onnx`, `onnxruntime`, `phonemizer` or `espeakng_loader` (walk with `Path.rglob("*.py")` and `ast`).

**Real subprocess through the service (M2; `service` fixture, no `launcher`)**
- R5 `test_r5_the_real_worker_loop_answers_the_resident_service_and_stays_one_process`: `key, record = _real_key(tmp_path)`; `first = await service.synthesize(key, "Good evening, Captain.", 30.0, fields={"voice": "bf_emma", "speed": 1.0})`; `second = ... "Status report.", fields={"voice": "am_liam", "speed": 0.9}`; both `_wav(...)[:3] == (1, 2, 24000)`; `[(c["text"], c["voice"], c["lang"], c["speed"]) for c in _calls(record)] == [("Good evening, Captain.", "bf_emma", "en-gb", 1.0), ("Status report.", "am_liam", "en-us", 0.9)]`; the two `pid` values are equal.
- R6 `test_r6_a_sentence_with_no_phonemes_degrades_and_the_process_stays`: `synthesize(key, "   ", 30.0, fields=_FIELDS) is None`; then `synthesize(key, "Hello.", 30.0, fields=_FIELDS)` returns WAV bytes; `_calls(record)` has 2 entries with equal `pid`.
- R7 `test_r7_a_worker_that_refuses_to_start_degrades`: `_real_key(tmp_path, default_voice="zz_nobody")`; `synthesize(...)` is `None`; `_calls(record) == []`; a WARNING whose text contains `kokoro` was logged (exit or broken pipe: the worker may exit before or after the line is written).

**Backend (M3; `_RecordingService` and `_installed`)**
- B1 `test_b1_the_backend_sends_the_configured_voice_and_speed_and_logs_the_sentence`: `caplog.set_level(logging.INFO)`; `KokoroBackend(cfg, service=svc).synthesize("Hello.")` returns `TTSResult(audio_bytes=b"RIFF", mime="audio/wav")`; the one call's key `== KokoroWorkerKey(python=str(Path(sys.executable).resolve()), script=str(FAKE_WORKER.resolve()), model=<model resolved>, voices=<voices resolved>, threads=4, default_voice="af_heart")`; its timeout is `30.0`; its fields are `{"voice": "af_heart", "speed": 1.0}`; the log contains `AD-738g: kokoro voice=af_heart speed=1.00 chars=6` and `result=ok`.
- B2 `test_b2_a_catalogue_override_wins_and_a_foreign_name_is_ignored`: with `voice="am_liam"` in the config: override `"bf_emma"` sends `bf_emma`; override `"en_US-ryan-medium"` sends `am_liam`; override `None` sends `am_liam`.
- B3 `test_b3_emotion_scales_the_speed_within_kokoros_range`: `kokoro_speed(1.0, None) == 1.0`; `kokoro_speed(1.0, "concerned") == pytest.approx(1 / 1.05)`; `kokoro_speed(2.0, "excited") == 2.0`; `kokoro_speed(0.5, "concerned") == 0.5`; and through the backend with `speed=2.0`, emotion `"excited"` sends `speed == 2.0`.
- B4 `test_b4_a_missing_install_degrades_without_calling_the_service`: `python_path=str(tmp_path / "absent")`; result `None`; `svc.calls == []`; WARNING contains `kokoro is not installed` and `scripts/kokoro-fetch.ps1`. Repeat with a missing `model_path`: `None`, no call.
- B5 `test_b5_blank_text_and_a_missing_service_degrade`: `"   "` returns `None` with no call; `KokoroBackend(cfg, service=None).synthesize("Hi.")` returns `None` and logs `no voice synthesis service`.
- B6 `test_b6_the_catalogue_is_the_28_english_voices`: `KOKORO_VOICES == {<the 28 ids of 6.6, written out>}`; every id matches `^[ab][fm]_[a-z]+$`.

**Config, registry, selection (M3)**
- C1 `test_c1_defaults_stay_browser_and_kokoro_defaults_are_the_measured_ones`: `TTSConfig().backend == "browser"`; `TTSConfig().kokoro == KokoroTTSConfig()`; `KokoroTTSConfig()` has `voice == "af_heart"`, `speed == 1.0`, `threads == 4`, `timeout_seconds == 30.0`, and the three `tools/kokoro/` paths of 6.6.
- C2 `test_c2_kokoro_config_rejects_values_the_engine_cannot_take`: `pytest.raises(ValueError)` for `speed=0.49`, `speed=2.01`, `threads=0`, `threads=17`, `timeout_seconds=0.0`, `voice="zz_nobody"`, `voice="jf_alpha"`; `speed=0.5`, `speed=2.0`, `threads=1`, `threads=16` are accepted.
- C3 `test_c3_the_settings_registry_offers_kokoro`: the `tts.backend` descriptor of `get_section("voice").fields` has `enum_values == ("browser", "piper", "kokoro")`.
- S1 `test_s1_select_backend_builds_kokoro_with_the_runtime_service`: `select_backend("kokoro", TTSConfig(backend="kokoro"), service=svc)` is a `KokoroBackend` whose `name == "kokoro"`; `select_backend("piper", TTSConfig(backend="piper"))` is still a `PiperBackend`.

**Route (M3; a `kokoro_client` fixture copied from `test_bf918_tts_latency.py`:538-557 with `lipsync=LipSyncConfig()`, `tts=TTSConfig()` and `voice_synthesis=service`)**
- T1 `test_t1_post_tts_speaks_kokoro_through_the_real_worker_loop` (the seam-crossing case): `key, record = _real_key(tmp_path)` for the paths; `monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))`; `rt.config.tts = TTSConfig(backend="kokoro", kokoro=KokoroTTSConfig(python_path=sys.executable, model_path=key.model, voices_path=key.voices, voice="bm_fable"))`; `POST /api/avatars/tts` with `{"text": "Good evening, Captain.", "emotion": "concerned", "defer_visemes": True}`; the body has `backend == "kokoro"`, `mime == "audio/wav"`, `duration_ms == 200` (`bm_fable` is the fake's 4th voice: 4800 frames at 24 kHz); the stored file (`chat_router_mod._get_attachment_store(rt).get_path(id)`) hashes to the body's `audio_attachment_id` and is a 24 kHz mono 16-bit WAV; `_calls(record)` is one call with `voice == "bm_fable"`, `lang == "en-gb"`, `speed == pytest.approx(1 / 1.05)`.
- T2 `test_t2_the_default_config_speaks_in_the_browser_and_starts_no_process`: `launcher("ok")`; default `TTSConfig()`; POST returns `backend == "disabled"` and `audio_attachment_id is None`; `fake.launched == []`.
- T3 `test_t3_tts_status_reports_kokoro`: `TTSConfig(backend="kokoro", sentence_pipelining_enabled=True)`; `GET /api/avatars/tts/status` returns `{"enabled": True, "backend": "kokoro", "sentence_pipelining_enabled": True}`.

### 6.16 `ui/src/audio/__tests__/voice.kokoroGate.test.tsx` (new, M3)

```tsx
/** AD-738g (#1662) S1: any TTS backend other than `browser` takes the server path.
 *  The gate used to test `backend !== 'piper'`, so a `kokoro` status made the browser speak. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

let speakCalls: any[] = [];
let createdAudios: FakeAudio[] = [];
const SHA = 'b'.repeat(64);

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  paused = false;
  pause = vi.fn(() => { this.paused = true; });
  play = vi.fn(async () => {});
  listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) { this.src = src; createdAudios.push(this); }
  addEventListener(ev: string, fn: () => void): void { (this.listeners[ev] ||= []).push(fn); }
}

function installGlobals(): void {
  speakCalls = [];
  createdAudios = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).Audio = FakeAudio;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: any) => speakCalls.push(u)),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  }
}

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

function fetchFor(status: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    if (url.endsWith('/api/avatars/tts/status')) return { ok: true, json: async () => status } as any;
    if (url === '/api/avatars/tts') {
      return {
        ok: true,
        json: async () => ({ backend: 'kokoro', audio_attachment_id: SHA, mime: 'audio/wav', visemes: [], duration_ms: 1000 }),
      } as any;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
}

const count = (m: ReturnType<typeof fetchFor>, pred: (u: string) => boolean) =>
  m.mock.calls.map((c) => c[0] as string).filter(pred).length;

beforeEach(() => {
  vi.resetModules();
  installGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('AD-738g speakResponse: the kokoro backend takes the server path', () => {
  it('posts to /api/avatars/tts and plays the audio when the status reports backend=kokoro', async () => {
    const fetchMock = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Good evening, Captain.');
    await flush();

    expect(count(fetchMock, (u) => u === '/api/avatars/tts')).toBe(1);
    expect(createdAudios.length).toBe(1);
    expect(createdAudios[0].src).toBe(`/api/chat/attachments/${SHA}`);
    expect(speakCalls.length).toBe(0);
  });

  it('makes no POST when the status reports kokoro but enabled=false', async () => {
    const fetchMock = fetchFor({ enabled: false, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi');
    await flush();

    expect(count(fetchMock, (u) => u === '/api/avatars/tts')).toBe(0);
    expect(speakCalls.length).toBe(1);
  });

  it('a cached kokoro status takes the server path on the next utterance without a second probe', async () => {
    const fetchMock = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('one');
    await flush();
    expect(createdAudios.length).toBe(1);
    (createdAudios[0].listeners.ended || []).forEach((fn) => fn());
    await flush();
    voiceMod.speakResponse('two');
    await flush();

    expect(count(fetchMock, (u) => u.includes('/api/avatars/tts/status'))).toBe(1);
    expect(count(fetchMock, (u) => u === '/api/avatars/tts')).toBe(2);
    expect(speakCalls.length).toBe(0);
  });
});
```
If the third case's first audio needs more than its `ended` listener to release the device (`voice.ts`:763), end it the way `voice.serverTts.test.tsx` does for its second-utterance case; do not add a timer.

### 6.17 `PROGRESS.md` (M4)

Insert above the newest entry (directly under `# ProbOS Progress` and its blank line):

```markdown
**AD-738g S1 (2026-11-27), #1662 -- a local Kokoro voice on this machine's CPU, behind the TTS backend seam, off until configured.** `tts.backend: kokoro` runs `scripts/kokoro_worker.py` in the operator's venv `tools/kokoro/venv` (kokoro-onnx 0.6.1, installed with the model files by `scripts/kokoro-fetch.ps1`, sizes and SHA-256 pinned) as one resident process under `python -I`; it speaks Piper's line protocol with each request's voice and speed, so the BF-918 resident service owns its start, restart, timeout and stop. The service is keyed by a `WorkerKey` Protocol (`PiperWorkerKey` unchanged, `KokoroWorkerKey` new); Piper's request line is byte-identical, and a Kokoro request answered without audio leaves the process resident (a respawn costs about 3.2 s). `KokoroBackend` takes a per-call voice only when it is one of the 28 English Kokoro ids (`KokoroTTSConfig.voice`'s `Literal`), maps the AD-738e-1 emotion `length_scale` to speed (clamped to 0.5-2.0) and logs one INFO line per sentence (`AD-738g: kokoro voice=... synth_ms=...`). `TTSConfig` gains `kokoro` (defaults: voice `af_heart`, 4 threads, 30 s timeout) and `"kokoro"` in its backend `Literal` and the settings registry. The HXI client takes the server path for any backend other than `browser` (`voice.ts`), as the server does. Lip-sync is unchanged (heuristic or rhubarb): the shipped `kokoro-v1.0.onnx` has no `duration` output, so synthesizer timings need another model file (S3). Measured on the Ryzen 9 7950X3D: real-time factor 0.314 at 4 threads. GPL phonemizer and espeak-ng run only in the worker process (THIRD_PARTY_LICENSES.md). New `tests/test_ad738g_kokoro_voice.py` (28 tests), `ui/src/audio/__tests__/voice.kokoroGate.test.tsx` (3 tests). #1662 stays open for S2 to S5 and the Captain's live acceptance. Contract `prompts/ad-738g-s1-local-kokoro-voice.md`.
```

### 6.18 `DECISIONS.md` (M4)

Insert above the newest entry's heading:

```markdown
### AD-738g S1 -- a local Kokoro voice: a resident worker in the operator's venv, keyed into the BF-918 voice service (2026-11-27, #1662)

- *Scope.* `audio/tts/resident.py` (`WorkerKey`, `KokoroWorkerKey`, request `fields`), `audio/tts/kokoro_backend.py` (new), `scripts/kokoro_worker.py` (new), `scripts/kokoro-fetch.ps1` (new), `config_models/experience.py` (`KokoroTTSConfig`, `TTSConfig.kokoro`), `ui/src/audio/voice.ts` (the gate). Contract `prompts/ad-738g-s1-local-kokoro-voice.md`.
- *D1.* Runtime: kokoro-onnx 0.6.1 in a separate venv under `tools/kokoro/`, one resident process speaking Piper's line protocol. Not the PyTorch package (multi-GB), not Kokoro-FastAPI (no documented authentication), not a ProbOS HTTP service (deferred to the remote-Mac slice).
- *D2.* The resident service is generalised by a key Protocol, not a second worker class (DRY); Piper's line, retirement and log text stay as BF-918 shipped, except two service-wide lines that now say "voice".
- *D3.* A Kokoro request the engine cannot speak is answered with no file and the process stays; an unreadable line or a missing default voice ends the worker. A respawn costs about 3.2 s of model load and first-call initialisation.
- *D4.* CPU, 4 threads, 30 s timeout, no prewarm in S1 (measured real-time factor 0.314; one warm-up line before recording).
- *D5.* The 28 English voice ids are the config's `Literal`, the single catalogue; a foreign per-call voice name is ignored.
- *Licence.* GPL-3.0-or-later phonemizer and espeak-ng run only in the operator-installed worker process, which exchanges text, voice and speed in and a WAV path out; the worker runs under `python -I` and cannot import `probos`.
- *Reversal.* Revert the four commits and set `tts.backend` back to `piper` or `browser`; no persisted format changes. `tools/kokoro/` can be deleted.
```

### 6.19 Commit staging lists

- M1: `src/probos/audio/tts/resident.py`, `tests/test_ad738g_kokoro_voice.py`.
- M2: `scripts/kokoro_worker.py`, `tests/fixtures/fake_kokoro_worker.py`, `tests/test_ad738g_kokoro_voice.py`.
- M3: `src/probos/audio/tts/kokoro_backend.py`, `src/probos/audio/tts/__init__.py`, `src/probos/audio/tts/piper_backend.py`, `src/probos/config_models/experience.py`, `src/probos/config_models/__init__.py`, `src/probos/config.py`, `src/probos/settings/section_registry.py`, `src/probos/routers/avatars.py`, `ui/src/audio/voice.ts`, `ui/src/audio/__tests__/voice.kokoroGate.test.tsx`, `tests/test_ad738g_kokoro_voice.py`, `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1270e2c_experience_models.py`, `docs/development/config-facade-baseline.yaml`, `docs/development/config-reference.md`.
- M4: `scripts/kokoro-fetch.ps1`, `THIRD_PARTY_LICENSES.md`, `docs/development/roadmap.md`, `docs/research/reference-projects.md`, `PROGRESS.md`, `DECISIONS.md`, and the two ledger files if they change.

### 6.20 Files that may hold unrelated Captain work

`PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`: stage by path after checking `git diff` shows only this contract's hunk. Never stage `config/system.yaml`.

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| `VoiceSynthesisService.synthesize(key, text, timeout)` | `PiperBackend.synthesize` (`piper_backend.py`:217) | unchanged call; same line, same retirement, same logs except D7 |
| `PiperWorker.synthesize_blocking` / `_request` two-argument stand-ins | `test_bf930_voice_path_timing.py`:96, :387 | still called with two arguments when no fields (D8) |
| `PiperWorker._spawn`, one `Popen` | effect census `tests/fixtures/ad1346_effect_census.py`:132, file-write census `ad1346_file_write_census.py`:206, spawn-env guard `test_bf892_spawn_env_guard.py`:87 | still one `Popen` with `env=trusted_command_env()` in `_spawn`; the census keys (`PiperWorker._spawn`) are unchanged |
| `select_backend(name, config, service)` | `_synthesize_tts_impl` (`avatars.py`:270-274) | builds `KokoroBackend` for `kokoro`; the response's `backend` is `kokoro` (`avatars.py`:335) |
| `TTSConfig` dump and schema | `GET/POST /api/config`, the settings registry, `check_config_facade.py`, `gen_config_reference.py` | one nested section more; baseline and reference regenerated (6.9) |
| `GET /api/avatars/tts/status` | `voice.ts` `_fetchTtsStatus` and the gates :555, :567 | `kokoro` passes through (`avatars.py`:109) and now takes the server path |
| WAV container | `_wav_duration_ms` (`avatars.py`), rhubarb when `lipsync.backend == "rhubarb"` | stdlib `wave` writes the canonical 44-byte header (T1 pins `duration_ms == 200`); rhubarb on 24 kHz is not verified (section 13) |

### 7.1 Merge with BF-930's batch

This contract edits, in the files BF-930's batch also edits:
- `ui/src/audio/voice.ts`: only lines 548-549, 555, 561-562 and 567 (P11.2 to P11.5), inside `speakResponse`'s gate. Nothing near `_prepareServerSpeech`, the prefetch buffer or `voiceChunking.ts`.
- `src/probos/routers/avatars.py`: only the `tts_status` docstring, lines 95-96 (P11.1). Nothing in `_synthesize_tts_impl`.
- No test of this contract depends on BF-930's tests or code; none of BF-930's tests mock a `kokoro` status, and a `piper` status still takes the server path. If BF-930's batch also edits `resident.py`, `tests/test_bf930_voice_path_timing.py` or `tests/test_bf918_tts_latency.py`, the merge is not mechanical: re-run 8.2's first line on the merged tree before the gate, and check D8's two stand-ins.

## 8. Gates (the orchestrator runs them)

### 8.1 Oracle tree, before the Builder starts

- Each SEARCH of section 6 counted at its turn: 1 each; the six new files do not exist.
- A/B: on `63c536b3` the new Python file fails at collection (`KokoroWorkerKey` and `kokoro_backend` do not exist); the UI file's cases 1 and 3 fail (the browser speaks) and case 2 passes. On the candidate all pass.

### 8.2 Focused checks on the candidate

Per milestone (the Builder runs its milestone's line; the orchestrator runs all on the frozen candidate):
```text
M1: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_kokoro_voice.py tests/test_bf918_tts_latency.py tests/test_bf930_voice_path_timing.py tests/test_ad738_piper_tts.py -n 0 -q
M2: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_kokoro_voice.py -n 0 -q
M3: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_kokoro_voice.py tests/test_ad738_piper_tts.py tests/test_bf918_tts_latency.py tests/test_bf918_tts_retention.py tests/test_bf918_attachment_io.py tests/test_bf930_voice_path_timing.py tests/test_bf291_piper_voice_catalog.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_ad1071_tts_pipelining.py tests/test_ad1025_path_anchoring.py tests/test_ad718_voice_profile.py tests/test_ad1270e2c_experience_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2_config_models.py tests/test_ad1270e2e_operations_models.py tests/test_ad741_section_registry.py tests/test_ad741_config_api.py tests/test_ad826_voice_config.py tests/test_bf892_spawn_env_guard.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_subprocess_plumbing.py -n 0 -q
M3 (ui/): npx vitest run src/audio/__tests__/voice.kokoroGate.test.tsx src/audio/__tests__/voice.serverTts.test.tsx src/audio/__tests__/voice.pipelining.test.tsx src/audio/__tests__/voice.prefetch.bf918.test.tsx src/audio/__tests__/voice.perEmotion.test.tsx src/audio/__tests__/voice.balancedEnd.test.tsx src/__tests__/CrewVRM.mouthClock.bf931.test.tsx src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx
M3: the five commands of 6.9 (the --check forms pass)
M4: d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
All: d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-738g-s1
```
Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time on the candidate, file restored byte for byte)

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| K1 | `__init__.py`: `return KokoroBackend(config.kokoro, service=service)` | `return NullBackend()` | S1, T1 |
| K2 | `voice.ts`:567 `... status.backend === 'browser') {` | `... status.backend !== 'piper') {` | UI case 1 |
| K3 | `voice.ts`:555 `... _ttsStatus.backend === 'browser')) {` | `... _ttsStatus.backend !== 'piper')) {` | UI case 3 |
| K4 | `resident.py`: `payload.update({name: value for name, value in fields.items() if name not in payload})` | (line deleted, `pass` under the `if`) | R2, R5, T1 |
| K5 | the same line | `payload.update(fields)` | R2 |
| K6 | `kokoro_backend.py`: `if voice_override is not None and voice_override in KOKORO_VOICES:` | `if voice_override:` | B2 |
| K7 | `kokoro_backend.py`: `return min(SPEED_MAX, max(SPEED_MIN, base / length_scale))` | `return base / length_scale` | B3 |
| K8 | `resident.py`: `if outcome.reason == "empty" and not key.retire_on_empty:` | `if False:` | R3, R6 |
| K9 | `KokoroWorkerKey.retire_on_empty`: `return False` | `return True` | R3, R6 |
| K10 | `PiperWorkerKey.retire_on_empty`: `return True` | `return False` | `test_bf918_tts_latency.py::test_an_empty_wav_degrades` |
| K11 | `kokoro_worker.py`: `return "en-gb" if voice.startswith("b") else "en-us"` | `return "en-us"` | W2, R5, T1 |
| K12 | `kokoro_worker.py`: `return False` in `speak`'s `except` | `raise` | W4, R6 |
| K13 | `kokoro_worker.py`: `voice = default_voice` (in `speak`) | `pass` | W3 |
| K14 | `kokoro_worker.py`: `sys.stdout = sys.stderr  # ...` | (line deleted) | W7 |
| K15 | `kokoro_worker.py`: `frames = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()` | `frames = (pcm * 32767.0).astype("<i2").tobytes()` | W1 |
| K16 | `kokoro_worker.py`: `return EXIT_UNREADABLE_LINE` | `continue` | W6 |
| K17 | `experience.py`: `backend: Literal["browser", "piper", "kokoro"] = "browser"` | `backend: Literal["browser", "piper"] = "browser"` | the e2c `kokoro` literal case, S1, T1, T3 |
| K18 | `kokoro_backend.py`: `name: str = "kokoro"` | `name: str = "piper"` | S1, T1 |
| K19 | `resident.py` (`synthesize_blocking`): `return self._request(text, timeout) if fields is None else self._request(text, timeout, fields)` | `return self._request(text, timeout, fields)` | `test_bf930_voice_path_timing.py` (the `_stub_request` cases) |

This campaign, run once on the frozen candidate overlay and recorded with each file's sha256, is the campaign of record; a Builder whose files match does not repeat it.

### 8.4 The gate

`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-738g-s1 --receipt logs/gates/ad-738g-s1.receipt.json` once on the committed head of the merged batch (this contract and BF-930's), after the base is merged in.

## 9. Diff Reviewer: properties to verify

The change claims a Kokoro voice that runs locally, only when configured, behind the existing backend seam, with Piper's behaviour unchanged. The consumers that must accept it: `PiperBackend` through `VoiceSynthesisService`, the `/api/avatars/tts` route, and `voice.ts`'s gate.
1. With `fields=None`, Piper's request line is the same bytes as on the base (key set and order `text`, `output_file`), and `synthesize_blocking` and `_request` are called with two arguments.
2. `fields` never replace `text` or `output_file`.
3. Only a key whose `retire_on_empty` is `False` keeps a worker after an `empty` outcome; every other outcome and Piper's `empty` retire as on the base.
4. The only `Popen` stays in `PiperWorker._spawn`, with `env=trusted_command_env()`; the Kokoro argv begins `[python, "-I", script]`.
5. No file under `src/probos` imports `kokoro_onnx`, `onnxruntime`, `phonemizer` or `espeakng_loader`; `scripts/kokoro_worker.py` imports only the stdlib and numpy at module level.
6. The worker never writes anything but request paths to the protocol stdout, and never leaves a partial WAV at `output_file`.
7. `TTSConfig()` defaults keep `backend == "browser"`; with it the route returns `disabled` and starts no process; the client makes no POST for `browser`.
8. Every new config field has a default and a bound where the engine has one; the voice is validated at parse time.
9. Piper's log lines read as on the base except the two of D7.
10. `avatars.py` changes only the `tts_status` docstring; `voice.ts` changes only the four lines of 6.11.
11. ASCII and LF in new text; no file outside section 6.19 changes; the regenerated files come from their tools.
12. Each absolute word of the new text (each, every, no, only, never) holds against sections 1, 7 and Absence Verified.

## 10. Verified Against Codebase (2026-11-27, tree `63c536b3`)

- `src/probos/audio/tts/resident.py`: module docstring :1-22 (ends :19-22); `from typing import IO, Any, Callable, Iterator, TypeVar` :40; `trusted_command_env` import :42; `PIPER_MAX_RESIDENT = 4` :52; `SLOW_SYNTHESIS_MS` :56; `PiperWorkerKey` :93-115 (argv :104-115); `PiperOutcome` :118-125; `PiperWorker` :128, `__init__(self, key: PiperWorkerKey)` :142-143; `synthesize_blocking` :161-180 (`self._request(text, timeout)` :173); `_request` :182-224 (no-pipes reason :193, line :198, timer :200, empty :213-214, `except (OSError, ValueError)` :215-218); `_await_answer` :226-234 (skips non-matching lines); `_spawn` :259-279 (`mkdtemp(prefix="probos-piper-")` :261, `Popen(... env=trusted_command_env())` :270-276, log :279); `VoiceSynthesisService` :336; `_resident`/`_busy`/`_retiring`/`_locks` :361-365; `synthesize` :400-465 (`run_in_executor` :426, failure warning :440, BF-930 slow line :449-457, failure branch :458-465); `_claim` :467-484 (busy warning :476-479); `_forget` :486; `_log_failure` :509-522; `close` log :545.
- `src/probos/audio/tts/__init__.py`: imports :8-10; `select_backend` :17-49 (`piper` :31, `browser` :43, warning :45-49); `__all__` :52.
- `src/probos/audio/tts/piper_backend.py`: `_probos_root` :29-38; `_anchor_path` :41-49; `resolve_voices_dir` :52-58; `_resolve_binary_path` :61-73; `PiperBackend.name` :100; `PiperWorkerKey(...)` and `service.synthesize(key, text, self._timeout_seconds)` :209-217.
- `src/probos/audio/tts/backends.py`: `TTSResult` :9-19; `TTSBackend.synthesize(text, emotion, voice_override)` :33-38.
- `src/probos/audio/tts/prosody.py`: `_EMOTION_PROSODY_OVERRIDES` :22-29 (`concerned` 1.05, `excited` 0.92, `formal` 1.0); `resolve_prosody_overrides` :32-44.
- `src/probos/config_models/experience.py`: `from typing import Literal` :10; `from pydantic import BaseModel, Field, model_validator` :12; `KnowledgeBrowserConfig` :610; `LipSyncConfig` :620; `TTSConfig` :725, `backend` :744-748, `timeout_seconds` :772, `sentence_pipelining_enabled` :810-825 (":813 AND the backend is ``piper``"); `WakeWordConfig` :828.
- `src/probos/config.py`: experience import block :42-59 (`KnowledgeBrowserConfig` :49, `LipSyncConfig` :50); `tts: TTSConfig = Field(default_factory=TTSConfig)` :4026; no `__all__`.
- `src/probos/config_models/__init__.py`: experience import :36-53 (`KnowledgeBrowserConfig` :43, `LipSyncConfig` :44); `__all__` :203; `"KnowledgeBrowserConfig"` :288 to `"LLMRateConfig"` :291.
- `src/probos/settings/section_registry.py`: `FieldDescriptor` :39-45 (`field_id`, `enum_values`); voice section :260-279; `tts.backend` enum :271-276; `get_section` :522.
- `src/probos/routers/avatars.py`: `tts_status` :89-115 (docstring :95-96, `"backend": str(cfg.backend)` :109); `_synthesize_tts_impl` :220 (browser gate :222, `voice_name` checks :255-262, `select_backend` :270-274, degraded log :277-280, stage log :326-332, `"backend": backend.name` :335).
- `ui/src/audio/voice.ts`: `TtsStatus` type :177; `_invalidateTtsStatus` :209-211; `_resetTtsStatusForTests` :229-238; `speakResponse` :353; gate comments :548-549, :561-562; gates :555, :567; `ended` listener :763; `getServerPiperVoices` :981-996 (`data.backend !== 'piper'` :987, the catalogue, not speech).
- `ui/src/audio/__tests__/voice.serverTts.test.tsx`: harness :7-79; zero-HTTP case :81-125; piper cases :128-206.
- `src/probos/runtime.py`:859 `self.voice_synthesis = VoiceSynthesisService()`; `src/probos/startup/shutdown.py`:109, :1661 `_close_voice_synthesis`.
- `src/probos/utils/step_timing.py`: `TimingLines` :46-58 (12 lines per 60 s).
- Tests: `tests/test_bf918_tts_latency.py` (`_key` :45, `launcher`/`service` fixtures :74-87, empty-retire case :258-267, `voice_client` :538-557, route case :703-716); `tests/test_bf930_voice_path_timing.py` (`_PIPER = "BF-930: piper request slow"` :44, `_lines`/`_field` :55-62, two-argument `_stub_request` :95-100, two-argument `synthesize_blocking` stand-in :384-393); `tests/test_ad1270e2c_experience_models.py` (`EXPECTED_DUMPS['TTSConfig']` :198-208, baseline identity :264-274, dump tests :321-348, literal cases :391-405); `tests/test_ad1270e1_config_facade.py` (counts :1515-1584); `tests/test_ad1270e2e_operations_models.py`:615-627 (sorted `__all__`); `tests/fixtures/fake_piper.py` (`FakePiperLauncher` :141-173, per-launch modes :167); census rows `tests/fixtures/ad1346_effect_census.py`:132, `tests/fixtures/ad1346_file_write_census.py`:206, `tests/test_bf892_spawn_env_guard.py`:87; the effect census scans `src/probos` only (`ad1346_effect_census.py`:250-252).
- `docs/development/config-facade-baseline.yaml`: regeneration header :1-34; `TTSConfig` :3621-3638. Precedent commit `0c859b90` (AD-1346 M3c: baseline and reference regenerated, counts `names=310 ... fields=1880`).
- Scripts: `scripts/check_config_facade.py` `--check`/`--update-baseline` :1710-1722; `scripts/gen_config_reference.py` `--check` :199-203; `scripts/check_config_profiles.py` :778-800; `scripts/whisper-tiny-en-fetch.ps1` SHA-256 pattern :27, :41-56; `scripts/piper-voice-fetch.ps1` (layout of 6.12).
- `scripts/check_architecture_principles.py`: `SRP_MAX_BODY_LINES = 500`, `SRP_MAX_DIRECT_METHODS = 15` :187-188 (no method is added to `PiperWorker` or `VoiceSynthesisService`); ranked layers are only substrate, mesh, consensus, cognitive, experience (`architecture-baseline.yaml`:12-17), so `audio` importing `config` is not a layer-import finding.
- `THIRD_PARTY_LICENSES.md`: License policy :53-78; last section `## openWakeWord (AD-705c)` :160-167. `.gitignore`:3 `/tools/`. `pyproject.toml`: `requires-python = ">=3.12"` :9, `numpy>=2.0` :86.
- `docs/development/roadmap.md`:826-827; `docs/research/reference-projects.md`:83.
- External (2026-11-27): VOICES.md lists 20 American and 8 British English voices, exactly the ids of 6.6 (WebFetch of `huggingface.co/hexgrad/Kokoro-82M/raw/main/VOICES.md`). The orchestrator's measurements (handoff items 1 to 5) are first-hand and are cited, not re-run.

### Absence Verified (2026-11-27)

- CLAIM: nothing in the tree mentions Kokoro yet. RUN: Grep `(?i)kokoro` over `src`, `scripts`, `config`; over `tests` and `ui/src` `*.py,*.ts,*.tsx`. FOUND: none. HOLDS.
- CLAIM: no `?raw` source import pins `voice.ts`. RUN: Grep `voice\.ts\?raw|voice\?raw` over `tests` and `ui/src`. FOUND: `useMeetingVoice?raw`, `meetingVoice?raw` only. HOLDS.
- CLAIM: no test pins the two service-wide log texts of D7. RUN: Grep `resident piper|piper timed out|piper exit=|piper produced|piper subprocess failed|piper request|probos-piper|piper process` over `tests`. FOUND: `test_ad738_piper_tts.py`:173, :193; `test_bf918_tts_latency.py`:241, :253; `test_bf930_voice_path_timing.py`:44, :376 (all Piper lines whose text is unchanged); census descriptions :132 and `test_bf892_spawn_env_guard.py`:87 (descriptions, not log text). HOLDS.
- CLAIM: no test asserts a broken-pipe or "subprocess failed" message. RUN: Grep `BrokenPipe|subprocess failed` over `tests/test_*.py`. FOUND: none. HOLDS.
- CLAIM: the only stand-ins for `synthesize_blocking`/`_request`, and the only direct callers, are in the BF-918 and BF-930 tests. RUN: Grep `_log_failure|synthesize_blocking|PiperWorker\(` over `tests`; Grep `def _stub_request` over `tests`. FOUND: `test_bf918_tts_latency.py`:331-339 (positional two-argument calls), `test_bf930_voice_path_timing.py`:96-100 and :384-393 (two-argument stand-ins). HOLDS.
- CLAIM: server code compares the TTS backend to `"piper"` only in `select_backend` and one docstring. RUN: Grep `== ["']piper["']|!= ["']piper["']|in \(["']piper` over `src`. FOUND: `audio/tts/__init__.py`:31, `routers/avatars.py`:96. HOLDS.
- CLAIM: no test checks the registry's `tts.backend` enum or reads `tts.backend` by name. RUN: Grep `tts\.backend|tts_backend` over `tests`. FOUND: none. HOLDS.
- CLAIM: nothing outside the config modules imports `probos.config_models` directly, so the backend imports `KokoroTTSConfig` from `probos.config`. RUN: Grep `from probos\.config_models` over `src/probos` excluding `config*.py`. FOUND: only `config_models/__init__.py` itself. HOLDS.
- CLAIM: the only UI sources that test `'piper'` are `voice.ts` and `ProfileInfoTab.tsx` (the Piper catalogue picker). RUN: Grep `piper|kokoro` count over `ui/src/**/*.{ts,tsx}`. FOUND: `voice.ts` 11, `ProfileInfoTab.tsx` 4, the rest tests. HOLDS.

Not verified here (the orchestrator's D4 pre-checks cover them): that all 28 ids are keys of `voices-v1.0.bin` (16 were checked first-hand); rhubarb's handling of a 24 kHz WAV; the worker's start-up time before the model load; that `_wav_duration_ms` reads the stdlib header (T1 proves it in the gate).

## 11. What this does NOT change

- Lip-sync: heuristic or rhubarb as configured. **Timing-derived lip-sync (the issue's headline, S3) needs a different model file**: the shipped `kokoro-v1.0.onnx` has one output, `audio`, and no `duration` output, so kokoro-onnx's `create_timed` returns an empty timing list ("The timings are empty unless the model exposes a duration output"). Before S3 is drafted it must establish: a Kokoro ONNX export that exposes per-phoneme durations (which file, its licence, size and hash), that kokoro-onnx 0.6.1 reads it, its real-time factor on this CPU against `kokoro-v1.0.onnx`, and how phoneme durations map onto the viseme frames `avatars.py` returns today.
- Per-agent voices (AD-738f, #1868): no role table, no `agent_type` keyword on `TTSBackend`, no `agent_id` on the request. Every crew member speaks `tts.kokoro.voice` unless a profile's `voice_name` is a Kokoro id.
- `GET /api/avatars/tts/voices` and the HXI voice picker (`ProfileInfoTab.tsx`, `getServerPiperVoices`): still the Piper catalogue; a Piper name stored on a profile is ignored by Kokoro.
- GPU (opt-in device and VRAM cap, S4), the remote Mac backend and the fallback chain (S5), prewarm (S2).
- `PiperBackend`, Piper's request line, process keys and retirement; the `TTSBackend` Protocol; the route's validation; `runtime.voice_synthesis` wiring and its shutdown; the census fixtures; `PIPER_MAX_RESIDENT`.
- The ProbOS Python environment: nothing is added to `pyproject.toml`.

## 12. Issue text (#1662, on merge; the issue stays open)

Wave comment:

```text
AD-738g S1 shipped (PR #<PR>, contract prompts/ad-738g-s1-local-kokoro-voice.md). Refs only: the issue stays open for S2 to S5 and the Captain's live acceptance.
- S1, a local Kokoro voice on this machine's CPU, off until configured: tts.backend: kokoro runs scripts/kokoro_worker.py in the operator's venv tools/kokoro/venv (kokoro-onnx 0.6.1; scripts/kokoro-fetch.ps1 installs it and downloads kokoro-v1.0.onnx and voices-v1.0.bin with sizes and SHA-256 pinned, then speaks one test line through the worker). One resident process under python -I serves every voice over Piper's line protocol, so the BF-918 voice service owns start, restart, timeout and stop; a sentence the engine cannot speak degrades to the browser voice and leaves the process resident. Defaults: voice af_heart, 4 threads, 30 s timeout. The HXI takes the server path for any backend other than browser. Measured on the Ryzen 9 7950X3D: real-time factor 0.314 at 4 threads; the first sentence after a restart costs about 3.2 s more (model load and first-call initialisation), so speak one line before recording. Lip-sync is unchanged. 28 Python tests and 3 UI tests; 19 mutation rows killed.
- Finding for S3: the shipped kokoro-v1.0.onnx has a single output (audio) and no duration output, so kokoro-onnx's create_timed returns no timings. Timing-derived lip-sync needs a different model export: S3 must first establish which file exposes phoneme durations, its licence, size and hash, that kokoro-onnx reads it, its real-time factor here, and the mapping from phoneme durations to viseme frames.
- Licence: phonemizer and espeak-ng (GPL-3.0-or-later) run only in the operator-installed worker process, which exchanges text, a voice id and a speed in and a WAV path out; the worker venv cannot import probos (checked by the install script). THIRD_PARTY_LICENSES.md has the entry.
- Limit: the worker venv must live under an ASCII-only path (espeak-ng cannot open its data from a non-ASCII one); the install script refuses a non-ASCII destination before creating anything. Model, voices and output paths may be anything.
- Next: AD-738f S1 (#1868, per-role voices) on the tree after BF-930; then S2 prewarm. If the live run shows the first sentence too slow, the GPU slice (S4) moves ahead of S3.
```

PR title: `A local Kokoro voice behind the TTS backend seam, off until configured`.

## 13. What the Captain does by hand, and what the orchestrator checks first (D4)

**Orchestrator, before the Captain (the scratch venv and models in `G:\speech-kokoro-probe`):**
1. The real worker alone, from the worktree root:
   ```powershell
   '{"text": "Good evening, Captain.", "output_file": "G:\\speech-kokoro-probe\\w1.wav", "voice": "bf_emma", "speed": 1.0}' | G:\speech-kokoro-probe\venv\Scripts\python.exe -I scripts\kokoro_worker.py --model G:\speech-kokoro-probe\kokoro-v1.0.onnx --voices G:\speech-kokoro-probe\voices-v1.0.bin --threads 4 --default-voice af_heart
   ```
   Pass: stdout is exactly `G:\speech-kokoro-probe\w1.wav`; stderr has `AD-738g: kokoro worker ready (54 voices, default af_heart)`; `w1.wav` plays as a British voice. Repeat with `"text": "   "`: the path is printed, no file, stderr says `no audio for 3 chars`.
2. The catalogue against the voices file:
   ```powershell
   G:\speech-kokoro-probe\venv\Scripts\python.exe -I -c "from kokoro_onnx import Kokoro; k = Kokoro(r'G:\speech-kokoro-probe\kokoro-v1.0.onnx', r'G:\speech-kokoro-probe\voices-v1.0.bin'); ids = set(k.get_voices()); want = 'af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis'.split(); print(len(want), [v for v in want if v not in ids])"
   ```
   Pass: `28 []`. Any id printed must be removed from `KokoroVoiceId` before merge.
3. The install script end to end in this worktree (its `tools/kokoro` is gitignored): `powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1`. Pass: exit 0, two `[ ok ]` lines with the pinned SHA-256s, `the Kokoro venv cannot import probos`, `the Kokoro worker spoke the test line`. A second run prints two `[skip]` lines.
4. If `lipsync.backend` is `rhubarb` on the Captain's machine: post one sentence to a vessel run from the worktree with `tts.backend: kokoro` and check the `/api/avatars/lipsync` frames are non-empty (rhubarb on 24 kHz is unverified).

**The Captain, in `D:\ProbOS`, after the merge:**
1. `powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1` (about 350 MB; same pass condition as check 3). The venv must be under an ASCII-only path; `D:\ProbOS\tools\kokoro` is. On a checkout whose path is not ASCII, the script stops at once and says so: pass `-DestDir` to an ASCII folder and set `tts.kokoro.python_path`, `model_path` and `voices_path` to the absolute paths there.
2. In his own `config/system.yaml`:
   ```yaml
   tts:
     enabled: true
     backend: kokoro
     sentence_pipelining_enabled: true
     kokoro:
       voice: af_heart     # any of the 28 ids; optional
       threads: 4          # optional
   ```
3. Restart the vessel and reload the HXI page (a page that cached `browser` does not re-probe).
4. Warm-up: ask any crew member one short question and let the reply play; the first sentence takes about 3 to 5 s.
5. Read the log: `Select-String -Path "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log" -Pattern "resident kokoro started|AD-738g: kokoro"`.
   Pass: one `BF-918: resident kokoro started (voice=kokoro-v1.0)` line after the restart, then one `AD-738g: kokoro voice=V speed=... chars=N synth_ms=M result=ok role=R` line per sentence. R is the speaking crew member's role (`-` when the request names none). V is the voice `KokoroBackend.resolve_voice` (`src/probos/audio/tts/kokoro_backend.py`) chooses, first match: the `voice_name` the request carries when it is one of the 28 catalogue ids (a crew member's voice profile supplies it, saved or being sampled; any other name is ignored), then `tts.kokoro.agent_voices[R]`, then the AD-738f built-in table for R, then the ship voice `tts.kokoro.voice`. With the block above (no `agent_voices`), and with no catalogue `voice_name` in the request (under Kokoro the HXI voice picker lists browser voices, whose names are ignored), expect: the counselor `voice=af_bella ... role=counselor`; each other crew member its AD-738f table voice, or `voice=af_heart` for a role the table does not name. If you map a role in `agent_voices`, or the request carries a catalogue `voice_name`, that voice replaces the table's, as the order says. (A2, 16.12, corrected three times: it first said `voice=af_heart` per sentence, then omitted the request's own voice and a mapped role, then said a request without a crew member always logs `voice=af_heart`.) After the warm-up `synth_ms` is roughly a third of the sentence's spoken length (about 1.1 s for a 65-character sentence); no `result=degraded`; the voice is Kokoro and the mouth moves as before. A `result=degraded` line with `kokoro is not installed` means step 1 did not complete.

## 14. Prior art and blind spots

- Internal: AD-738 and BF-918 (#1626: the resident service, its executor and lifecycle), BF-930 (timing lines and the prefetch now in flight), AD-738e-1 (the emotion table reused for speed), AD-1025 (path anchoring), BF-291 and AD-718a (per-call `voice_name`), the 2026-10-25 licence policy and the Captain's ruling on #1662 (GPL allowed out of process), the 2026-11-27 consult (runtime ranking, sources).
- External: not re-searched; the consult searched this week (kokoro-onnx source and PyPI metadata, the model-files release, Hugging Face licence and LFS ids, VOICES.md, misaki, phonemizer, espeakng-loader, onnxruntime GPU notes, CPU benchmarks) and the orchestrator measured the rest. Absorbed: kokoro-onnx `from_session` for thread control, the release's model files with LFS-derived hashes, Piper's line protocol. Rejected: Kokoro-FastAPI (no documented authentication), the PyTorch package (size). Reference-projects row updated (6.14; not overdue, reviewed 2026-10-25, interval 180 days; date used 2026-11-27).
- Blind spots:
  - A respawn (timeout, crash, LRU eviction) pays the cold cost again on the next sentence; D3 removes the common cause.
  - A sentence that degrades is spoken in the browser voice, an audible change mid-reply; logged as `result=degraded`.
  - With `sentence_pipelining_enabled: false` a long reply is one request: about 84 s of synthesis for 4096 characters at RTF 0.31, past the 30 s timeout. The Captain's config turns pipelining on; the docstring says so.
  - A worker that refuses to start can exit before or after the line is written, so the service logs either `kokoro exit=2; stderr=...` or a broken pipe without stderr. The install script's test line shows the worker's messages on the console, which is where a bad install is caught.
  - One process serialises sentences: two crew speaking at once queue; acceptable for interviews.
  - The default `python_path` is the Windows venv layout; other platforms set it (docstring).
  - `espeakng-loader`'s wheel carries no licence file; the entry records espeak-ng's own licence.
  - The HXI status cache: a page that cached `browser` needs a reload after switching (section 13).

## 15. Acceptance criteria

1. The A/B of 8.1 holds; K1 to K19 are killed as 8.3 says.
2. The focused checks of 8.2 pass on each milestone and on the frozen candidate; pre-existing tests in those files pass unchanged; the three config tools pass in `--check` form after regeneration.
3. `git diff --check` is clean, new text is ASCII, and no file outside 6.19 changes.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head of the merged batch is green.
6. The orchestrator's checks 1 to 3 of section 13 pass before the PR is opened; the Captain's live acceptance (section 13, his steps 1 to 5) is recorded on #1662, which stays open.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1: review round 1 repairs (2026-11-27)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27. Source: `review-738g-r1.md` (Diff Reviewer `gpt-6.1-sol`, snapshot `2afff0e0`) and `review-738f-r1.md` (snapshot `f573a703`), with the orchestrator's first-hand reproductions of findings 1 to 4.

**Base:** the batch branch `feat/ad738f-1868-per-agent-voices-20261127` at `f573a703` (this slice and AD-738f S1 stacked). Every SEARCH below is copied from the files **as AD-738f left them**; where it names a 738f line (the `role=` field, `resolve_voice(voice_override, agent_type)`, `agent_voices`) that is why. Working copies are CRLF, blocks LF: match after normalising. Each SEARCH occurs once in its file at its turn. All new hand-written text is ASCII.

**Order.** Apply this section's pairs (G1 to G11 and the combined GF1 to GF3) first, then the AD-738f contract's section 15 pairs (F1 to F4). **Combined pairs:** GF1, GF2 and GF3 carry both a 738g repair and a 738f repair on the same lines; their text is here only, and the 738f contract's section 15 points to them. A pair written to a file that A1 does not name is a stop.

**Tests (A1, this slice):** 4 new in `tests/test_ad738g_kokoro_voice.py` (W9, B7, B8, C4); 1 changed in place (S1, reason inline); 0 removed. The file goes from 28 to 32 tests.

**Repair commit (the orchestrator commits; one for the batch, after both sections are applied).** Subject: `Speech: round-one repairs to the Kokoro voice: a timeout the timer can take, paths that degrade, a log line per attempt, an ASCII installer pipe, role keys the config API can show`. Body ends `Refs #1662.` and `Refs #1868.` Stage exactly: `src/probos/config_models/experience.py`, `src/probos/audio/tts/kokoro_backend.py`, `src/probos/audio/tts/piper_backend.py`, `src/probos/audio/tts/resident.py`, `scripts/kokoro_worker.py`, `scripts/kokoro-fetch.ps1`, `THIRD_PARTY_LICENSES.md`, `DECISIONS.md`, `PROGRESS.md`, `tests/test_ad738g_kokoro_voice.py`, `tests/test_ad738f_per_agent_voices.py`, `docs/development/config-facade-baseline.yaml`, `docs/development/config-reference.md`, and the two ledger files only if `gen_ad_ledger.py` changes them.

### 16.1 Decisions, finding by finding (738g round 1)

| # | Finding | Decision | Reason |
|---|---|---|---|
| 1 | P2 timeout: `inf`, `> TIMEOUT_MAX` accepted; `threading.Timer` overflows in its thread and the deadline never fires | **Fix (G1).** `Field(default=30.0, gt=0.0, le=600.0, allow_inf_nan=False)` | 600 s is twenty times the default and far under `threading.TIMEOUT_MAX` on every platform (4294967 s on Windows); `allow_inf_nan=False` refuses NaN and infinity explicitly instead of relying on how a NaN compares. The config bound alone closes ordinary reach; `resident.py` is not touched. Piper's unbounded `TTSConfig.timeout_seconds` (`experience.py`, `class TTSConfig`, plain `float = 10.0`; line 864 at `cffb4d99`; corrected by the orchestrator: A1's first text cited line 715, which is `LipSyncConfig`'s field) has the same weakness: follow-up 2, out of scope |
| 2 | P2 installer: PS 5.1 pipes ASCII, a non-ASCII destination reaches the worker as `?` | **Fix (G9).** The orchestrator's escape, plus a UTF-8 read of the answer | Escaping makes the line pure ASCII on 5.1 and 7. The answer comes back as UTF-8 bytes (`kokoro_worker.py`:129) and both PowerShell versions decode native output with `[Console]::OutputEncoding` (an OEM code page by default), so the comparison is made under a temporary UTF-8 console encoding, restored in `finally`. The reviewer's ASCII-escaped control matched on a host whose console was evidently UTF-8; this keeps it matching on one that is not |
| 3 | P2 NUL path: accepted by config, then `ValueError` from `Path.resolve` crosses `synthesize` (route 500) | **Fix (GF2 config, GF3 backend, G4 docstrings).** Config refuses a blank path or one with a NUL; the backend's resolution block catches `OSError`/`ValueError`, warns and degrades; the two wrappers' docstrings stop promising "NEVER raises" | Belt and braces: the config closes ordinary reach, the guard keeps "NEVER raises" true for a config built in code (`model_copy`) and for any other path the OS refuses. `_anchor_path` and every other Piper line stay as they are |
| 4 | P3 no INFO line on early degradation | **Fix (GF3).** Voice and speed are resolved first; `_speak` holds the guards; the one INFO line follows every attempt | D10 is "one INFO line per sentence"; blank text is not an attempt and still logs nothing |
| 5 | P3 native fd-1 output reaches the protocol stdout (injected-only) | **Record** (follow-up 1) | No ordinary path writes natively to fd 1 (the real-model run was quiet), and the effect is mild: the resident reader skips every line that is not the expected WAV path (`resident.py` `_await_answer`, lines 317-325; the round-2 review sent a complete native diagnostic line ahead of the reply and the WAV was accepted, not degraded), so only the installer's strict answer comparison would reject such a line. A fix exists (keep `os.dup(1)` as the protocol stream, `os.dup2(2, 1)` before loading the engine: about four lines, plus a fake-engine mode that writes to fd 1 and one real-subprocess test), but it changes the protocol channel, which is a shared contract and would widen round 2. Not in A1 |
| 6 | P4 docs attribute package isolation to `-I` | **Fix (G5, G6, G7, G8).** Four sites: `resident.py`:162-163, `kokoro_worker.py`:5-6, `THIRD_PARTY_LICENSES.md`:174, and `DECISIONS.md`:31 (the same claim, found by search) | The property comes from the separate venv that `kokoro-fetch.ps1`:76-79 checks; `-I` only keeps `PYTHON*` variables, the user site and the script and working directories out |
| Tests | W1 survives a non-atomic write; S1 survives a dropped service injection; K-rows miss R1, R4, R7, W5, W8, B1, B4-B6, C1-C3, T2, UI case 2 | **W9 new** (an interrupted write leaves neither output nor `.part`); **S1 changed in place** (the built backend speaks through the injected service); **rows K20 to K36** in 16.5; R1, T2 and UI case 2 are compatibility tests that pass on the base by design (16.5) | Strengthens what a claim rests on; the campaign is extended, not rewritten |
| Exc. | Milestone tests landed in M3 (6.15/6.19); generated `config-reference.md` holds non-ASCII | **Record** (16.6) | No code change |

### 16.2 The pairs

**G1.** `src/probos/config_models/experience.py`. SEARCH:
```python
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    """Per-sentence timeout, counted from when the worker takes the request. A timeout kills
    the worker, and the next sentence reloads the model (about 3.2 s cold)."""
```
REPLACE:
```python
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0, allow_inf_nan=False)
    """Per-sentence timeout, counted from when the worker takes the request. A timeout kills
    the worker, and the next sentence reloads the model (about 3.2 s cold). At most 600 s:
    ``threading.Timer`` takes no more than ``threading.TIMEOUT_MAX`` (4294967 s on Windows),
    and an infinite deadline would never fire."""
```

**GF1 (combined: the import serves AD-738f's finding 1 in GF2).** `src/probos/config_models/experience.py`. SEARCH:
```python
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
```
REPLACE:
```python
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from probos.settings.section_registry import is_secret_field_id
```
(`section_registry` imports only `re`, `dataclasses` and `typing`, so there is no cycle; `probos.config` re-exports `experience` names by an explicit list, so no facade name moves. Absence Verified below.)

**GF2 (combined: 738g finding 3, the path validator; 738f finding 1, the secret-name check).** `src/probos/config_models/experience.py`. SEARCH:
```python
    @field_validator("agent_voices")
    @classmethod
    def _keys_are_role_names(cls, value: dict[str, str]) -> dict[str, str]:
        """A key is an ``agent_type``: lowercase letters, digits and ``_``, at most 64 characters."""
        for role in value:
            if not _ROLE_NAME.fullmatch(role):
                raise ValueError(f"tts.kokoro.agent_voices: {role!r} is not a role name (an agent_type)")
        return value
```
REPLACE:
```python
    @field_validator("python_path", "model_path", "voices_path")
    @classmethod
    def _paths_can_name_a_file(cls, value: str) -> str:
        """A path is non-blank and holds no NUL character, which no file system accepts."""
        if not value.strip() or "\x00" in value:
            raise ValueError("tts.kokoro: a path must be non-blank and must not contain a NUL character")
        return value

    @field_validator("agent_voices")
    @classmethod
    def _keys_are_role_names(cls, value: dict[str, str]) -> dict[str, str]:
        """A key is an ``agent_type``: lowercase letters, digits and ``_``, at most 64 characters,
        and not a name the config API treats as a secret field (AD-741)."""
        for role in value:
            if not _ROLE_NAME.fullmatch(role):
                raise ValueError(f"tts.kokoro.agent_voices: {role!r} is not a role name (an agent_type)")
            if is_secret_field_id(role):
                # /api/config hides such a key on read and refuses a patch that holds it
                # (routers/config.py); the redaction rule stays as AD-741 wrote it.
                raise ValueError(
                    f"tts.kokoro.agent_voices: {role!r} contains secret, token, password, api_key or "
                    "private_key, which the config API treats as a secret field and would hide and "
                    "refuse; this role speaks its KOKORO_ROLE_VOICES voice or tts.kokoro.voice"
                )
        return value
```

**GF3 (combined: 738g findings 3 and 4; 738f finding 4).** `src/probos/audio/tts/kokoro_backend.py`. SEARCH:
```python
        if not text or not text.strip():
            return None
        if self._service is None:
            logger.warning("AD-738g: no voice synthesis service on this runtime; degrading to browser")
            return None
        cfg = self._config
        python = resolve_executable_path(cfg.python_path)
        script = anchor_install_path(WORKER_SCRIPT)
        model = anchor_install_path(cfg.model_path)
        voices = anchor_install_path(cfg.voices_path)
        missing = [str(path) for path in (script, model, voices) if not path.is_file()]
        if python is None:
            missing.insert(0, str(anchor_install_path(cfg.python_path)))
        if python is None or missing:
            logger.warning(
                "AD-738g: kokoro is not installed (missing: %s); run scripts/kokoro-fetch.ps1 or set "
                "tts.kokoro.* (relative paths anchor to the ProbOS root); degrading to browser",
                ", ".join(missing),
            )
            return None
        voice = self.resolve_voice(voice_override, agent_type)
        speed = kokoro_speed(cfg.speed, emotion)
        key = KokoroWorkerKey(
            python=str(python),
            script=str(script),
            model=str(model),
            voices=str(voices),
            threads=cfg.threads,
            default_voice=cfg.voice,
        )
        started = time.perf_counter()
        wav = await self._service.synthesize(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed})
        # AD-738f (#1868): the role goes last, so the Captain can read which role spoke in which
        # voice; no agent id is logged.
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s role=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded", agent_type or "-",
        )
        if wav is None:
            return None
        return TTSResult(audio_bytes=wav, mime="audio/wav")
```
REPLACE:
```python
        if not text or not text.strip():
            return None
        # AD-738f (#1868): the route sends only strings; anything else from a direct caller is
        # no role, no per-call voice and no emotion, so this method still never raises.
        role = agent_type if isinstance(agent_type, str) else None
        override = voice_override if isinstance(voice_override, str) else None
        voice = self.resolve_voice(override, role)
        speed = kokoro_speed(self._config.speed, emotion if isinstance(emotion, str) else None)
        started = time.perf_counter()
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
        if self._service is None:
            logger.warning("AD-738g: no voice synthesis service on this runtime; degrading to browser")
            return None
        cfg = self._config
        try:
            python = resolve_executable_path(cfg.python_path)
            script = anchor_install_path(WORKER_SCRIPT)
            model = anchor_install_path(cfg.model_path)
            voices = anchor_install_path(cfg.voices_path)
            missing = [str(path) for path in (script, model, voices) if not path.is_file()]
            if python is None:
                missing.insert(0, str(anchor_install_path(cfg.python_path)))
        except (OSError, ValueError) as exc:  # Path.resolve on a path the OS cannot represent
            logger.warning(
                "AD-738g: a tts.kokoro path cannot be resolved (%s: %s); degrading to browser",
                type(exc).__name__, exc,
            )
            return None
        if python is None or missing:
            logger.warning(
                "AD-738g: kokoro is not installed (missing: %s); run scripts/kokoro-fetch.ps1 or set "
                "tts.kokoro.* (relative paths anchor to the ProbOS root); degrading to browser",
                ", ".join(missing),
            )
            return None
        key = KokoroWorkerKey(
            python=str(python),
            script=str(script),
            model=str(model),
            voices=str(voices),
            threads=cfg.threads,
            default_voice=cfg.voice,
        )
        return await self._service.synthesize(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed})
```
(`synth_ms` now also spans the path checks, a few filesystem stats; on a success it is still dominated by synthesis. The two WARNING texts are unchanged, so B4, B5 and R7 match as before.)

**G4.** `src/probos/audio/tts/piper_backend.py` (two docstrings only; `_anchor_path` and `_resolve_binary_path` untouched). SEARCH:
```python
    """AD-738g: ``_anchor_path`` for the sibling Kokoro backend (AD-1025: absolute as-is,
    relative under ``_probos_root()``, never the CWD). NEVER raises."""
    return _anchor_path(configured)


def resolve_executable_path(configured: str) -> Path | None:
    """AD-738g: ``_resolve_binary_path`` for the sibling Kokoro backend (anchored; ``.exe``
    appended on Windows when the literal path is missing). ``None`` when not found. NEVER raises."""
```
REPLACE:
```python
    """AD-738g: ``_anchor_path`` for the sibling Kokoro backend (AD-1025: absolute as-is,
    relative under ``_probos_root()``, never the CWD). Raises ``OSError`` or ``ValueError``
    for a path the OS cannot represent (``Path.resolve``, for example an embedded NUL); the
    Kokoro backend catches both and degrades."""
    return _anchor_path(configured)


def resolve_executable_path(configured: str) -> Path | None:
    """AD-738g: ``_resolve_binary_path`` for the sibling Kokoro backend (anchored; ``.exe``
    appended on Windows when the literal path is missing). ``None`` when not found. Raises
    ``OSError`` or ``ValueError`` for a path the OS cannot represent, as ``anchor_install_path``
    does; the Kokoro backend catches both and degrades."""
```

**G5.** `src/probos/audio/tts/resident.py`. SEARCH:
```python
    ``-I`` isolates the interpreter: no ``PYTHON*`` variable, no user site, and neither the
    script's nor the working directory on ``sys.path``, so the worker cannot import ``probos``.
```
REPLACE:
```python
    ``-I`` keeps ``PYTHON*`` variables, the user site and the script's and working directories
    off ``sys.path``. The worker cannot import ``probos`` because its venv does not contain it
    (``scripts/kokoro-fetch.ps1`` checks this), not because of ``-I``.
```

**G6.** `scripts/kokoro_worker.py`. SEARCH:
```python
``-I`` isolates it: no ``PYTHON*`` variable, no user site, and neither this directory nor the
working directory on ``sys.path``, so it cannot import ``probos``.
```
REPLACE:
```python
``-I`` keeps ``PYTHON*`` variables, the user site, this directory and the working directory
off ``sys.path``. It cannot import ``probos`` because ``tools/kokoro/venv`` does not contain it
(``scripts/kokoro-fetch.ps1`` checks this), not because of ``-I``.
```

**G7.** `THIRD_PARTY_LICENSES.md` (the whole line 174). SEARCH:
```markdown
- License posture (policy above): the GPL components are installed by the operator, run only in that separate process and are never imported into the ProbOS process, vendored or committed. The worker runs under `python -I`, so it cannot import `probos` (the install script checks it), and the ProbOS venv does not contain these packages. The boundary is a simple request/response exchange. The weights are Apache-2.0.
```
REPLACE:
```markdown
- License posture (policy above): the GPL components are installed by the operator, run only in that separate process and are never imported into the ProbOS process, vendored or committed. The worker runs from its own venv, which does not contain `probos` (the install script checks that it cannot import it); `python -I` only keeps `PYTHON*` variables, the user site and the script and working directories out. The ProbOS venv does not contain these packages. The boundary is a simple request/response exchange. The weights are Apache-2.0.
```

**G8.** `DECISIONS.md` (the whole line 31, in the AD-738g S1 entry). SEARCH:
```markdown
- *Licence.* GPL-3.0-or-later phonemizer and espeak-ng run only in the operator-installed worker process, which exchanges text, voice and speed in and a WAV path out; the worker runs under `python -I` and cannot import `probos`.
```
REPLACE:
```markdown
- *Licence.* GPL-3.0-or-later phonemizer and espeak-ng run only in the operator-installed worker process, which exchanges text, voice and speed in and a WAV path out; that venv does not contain `probos` (the install script checks it cannot import it), and `python -I` keeps `PYTHON*` variables and the user site out.
```

**G9.** `scripts/kokoro-fetch.ps1`. SEARCH:
```powershell
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + (ConvertTo-Json $Probe) + ', "voice": "af_heart", "speed": 1.0}'
$Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $LASTEXITCODE, answer '$Answer'); its messages are above."
}
```
REPLACE:
```powershell
# Windows PowerShell 5.1 pipes text to a native program as ASCII ($OutputEncoding), so a
# non-ASCII destination would reach the worker as '?': escape each non-ASCII UTF-16 unit as
# \uXXXX, which the worker's json.loads decodes. The worker answers in UTF-8; the console
# decodes it as UTF-8 for the comparison and gets its own encoding back afterwards.
$ProbeJson = [regex]::Replace((ConvertTo-Json $Probe), '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + $ProbeJson + ', "voice": "af_heart", "speed": 1.0}'
$ConsoleEncoding = [Console]::OutputEncoding
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { Write-Host "[warn] cannot set the console encoding; a non-ASCII path may fail the comparison" -ForegroundColor Yellow }
try {
    $Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
    $Exit = $LASTEXITCODE
} finally {
    try { [Console]::OutputEncoding = $ConsoleEncoding } catch { }
}
if ($Exit -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $Exit, answer '$Answer'); its messages are above."
}
```

**G10.** `PROGRESS.md`, the AD-738g S1 paragraph (line 5). Tracker exception to "starts at the beginning of a line": each SEARCH here is a substring that occurs once in the file (counted).
- SEARCH `4 threads, 30 s timeout)` REPLACE `4 threads, 30 s timeout, at most 600 s)`
- SEARCH `` `tests/test_ad738g_kokoro_voice.py` (28 tests) `` REPLACE `` `tests/test_ad738g_kokoro_voice.py` (32 tests) ``

**G11.** `tests/test_ad738g_kokoro_voice.py`.

G11.1 (W9, new, after W1). SEARCH:
```python
    assert struct.unpack("<3h", frames) == (16383, 32767, -32767)
    assert not (tmp_path / (out.name + ".part")).exists()


def test_w2_the_language_follows_the_voice_prefix(tmp_path: Path) -> None:
```
REPLACE:
```python
    assert struct.unpack("<3h", frames) == (16383, 32767, -32767)
    assert not (tmp_path / (out.name + ".part")).exists()


def test_w9_an_interrupted_write_leaves_neither_the_output_nor_a_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "out.wav"
    real_writeframes = wave.Wave_write.writeframes

    def _disk_full(self, data):
        real_writeframes(self, data[:2])  # one frame reaches the disk, then the write fails
        raise OSError("disk full")

    monkeypatch.setattr(wave.Wave_write, "writeframes", _disk_full)

    with pytest.raises(OSError, match="disk full"):
        worker.write_wav(out, [0.5, -0.5, 0.25], 24000)

    # The service reads output_file once the path comes back: it must never hold a partial WAV.
    assert not out.exists()
    assert not (tmp_path / (out.name + ".part")).exists()


def test_w2_the_language_follows_the_voice_prefix(tmp_path: Path) -> None:
```

G11.2 (B7 and B8, new, after B6). SEARCH:
```python
    }
    assert len(KOKORO_VOICES) == 28
    assert all(re.fullmatch(r"[ab][fm]_[a-z]+", voice) for voice in KOKORO_VOICES)
```
REPLACE:
```python
    }
    assert len(KOKORO_VOICES) == 28
    assert all(re.fullmatch(r"[ab][fm]_[a-z]+", voice) for voice in KOKORO_VOICES)


@pytest.mark.asyncio
async def test_b7_every_attempt_logs_one_result_line_even_when_it_degrades_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    svc = _RecordingService()

    missing = _installed(tmp_path, monkeypatch, model_path=str(tmp_path / "absent.onnx"))
    assert await KokoroBackend(missing, service=svc).synthesize("Hi.") is None
    assert await KokoroBackend(_installed(tmp_path, monkeypatch), service=None).synthesize("Hi.") is None
    assert await KokoroBackend(_installed(tmp_path, monkeypatch), service=svc).synthesize("   ") is None

    lines = [
        record.getMessage() for record in caplog.records
        if record.levelno == logging.INFO and record.getMessage().startswith("AD-738g: kokoro voice=")
    ]
    assert len(lines) == 2  # one per attempt (D10); blank text is not an attempt
    for line in lines:
        assert "voice=af_heart speed=1.00 chars=3" in line
        assert "result=degraded role=-" in line
    assert svc.calls == []


@pytest.mark.asyncio
async def test_b8_a_path_that_cannot_be_resolved_degrades_and_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    svc = _RecordingService()
    installed = _installed(tmp_path, monkeypatch)

    # C4: the config refuses a NUL; model_copy skips validation, as a config built in code can.
    for name in ("python_path", "model_path", "voices_path"):
        cfg = installed.model_copy(update={name: "tools/kokoro/a\x00b"})
        assert await KokoroBackend(cfg, service=svc).synthesize("Hi.") is None
    assert svc.calls == []
    assert caplog.text.count("result=degraded") == 3

    def _unrepresentable(configured: str) -> Path:
        raise OSError(22, "The filename, directory name, or volume label syntax is incorrect")

    monkeypatch.setattr(kokoro_backend, "anchor_install_path", _unrepresentable)
    assert await KokoroBackend(installed, service=svc).synthesize("Hi.") is None
    assert svc.calls == []
    assert "a tts.kokoro path cannot be resolved (OSError" in caplog.text
    assert caplog.text.count("result=degraded") == 4
```

G11.3 (C4, new, after C3). SEARCH:
```python
    backend = next(field for field in section.fields if field.field_id == "tts.backend")

    assert backend.enum_values == ("browser", "piper", "kokoro")
```
REPLACE:
```python
    backend = next(field for field in section.fields if field.field_id == "tts.backend")

    assert backend.enum_values == ("browser", "piper", "kokoro")


def test_c4_a_timeout_the_timer_cannot_take_and_a_path_no_file_can_have_are_refused() -> None:
    import threading

    # threading.Timer raises OverflowError past TIMEOUT_MAX (4294967.0 on Windows) inside its
    # own thread, so the deadline would silently never fire; infinity and NaN never fire either.
    assert 600.0 <= threading.TIMEOUT_MAX
    for value in (float("inf"), float("nan"), 600.01, 4294968.0, 1e30):
        with pytest.raises(ValueError):
            KokoroTTSConfig(timeout_seconds=value)
    assert KokoroTTSConfig(timeout_seconds=600.0).timeout_seconds == 600.0

    for name in ("python_path", "model_path", "voices_path"):
        for value in ("tools/kokoro/a\x00b", "", "   "):
            with pytest.raises(ValueError):
                KokoroTTSConfig(**{name: value})
```

G11.4 (S1, changed in place: it now proves the injected service is the one the backend speaks through; the reviewer showed a dropped injection survived it). SEARCH:
```python
def test_s1_select_backend_builds_kokoro_with_the_runtime_service(service) -> None:
    backend = select_backend("kokoro", TTSConfig(backend="kokoro"), service=service)

    assert isinstance(backend, KokoroBackend)
    assert backend.name == "kokoro"
    assert isinstance(select_backend("piper", TTSConfig(backend="piper")), PiperBackend)
```
REPLACE:
```python
@pytest.mark.asyncio
async def test_s1_select_backend_builds_kokoro_with_the_runtime_service(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = select_backend("kokoro", TTSConfig(backend="kokoro"), service=service)

    assert isinstance(backend, KokoroBackend)
    assert backend.name == "kokoro"
    assert isinstance(select_backend("piper", TTSConfig(backend="piper")), PiperBackend)
    # A1: the backend speaks through the service it was given (a dropped injection degrades).
    recording = _RecordingService()
    built = select_backend(
        "kokoro", TTSConfig(backend="kokoro", kokoro=_installed(tmp_path, monkeypatch)), service=recording,
    )
    assert await built.synthesize("Hi.") == TTSResult(audio_bytes=b"RIFF", mime="audio/wav")
    assert len(recording.calls) == 1
```

### 16.3 Regenerations and checks (after both A1 sections are applied)

G1 adds a schema maximum to `KokoroTTSConfig.timeout_seconds`; GF2 adds validators (no schema change); no field, model or public name is added. Run from the worktree root:
```text
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
```
**Pin rule.** The update must print `names=311, owned=298, incidental=13, models=229, fields=1886` on this tree (`fields=1887` if BF-932 has merged first). A1 moves **no** count pin: `test_ad1270e1_config_facade.py`'s `field_definitions` pin keeps the value it has. Any other printed number, or a baseline hunk outside the `KokoroTTSConfig` entry (and the reference's Kokoro rows), is a stop. Do not hand-edit either generated file. If `gen_ad_ledger.py --check` fails, run it without `--check` (no `--online`) and stage the two ledger files.

Focused tests (the orchestrator; `-n 0`):
```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_kokoro_voice.py tests/test_ad738f_per_agent_voices.py tests/test_ad738_piper_tts.py tests/test_bf918_tts_latency.py tests/test_bf918_tts_retention.py tests/test_bf930_voice_path_timing.py tests/test_ad1025_path_anchoring.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2c_experience_models.py tests/test_ad741_section_registry.py tests/test_ad741_config_api.py tests/test_ad705a_offline_stt_config.py tests/test_bf_codebase_index_config_models.py -n 0 -q
```
**Installer end-to-end: superseded by 16.11.1 (A1.1, which replaces G9); kept for the record, do not run.** (Was: the orchestrator, by hand; G9 has no automated test.) From an interactive console, with a destination whose folder name is non-ASCII and the two model files copied in so the hash check skips the download:
```text
$Dest = "G:\speech-kokoro-probe\voix-$([char]0xE9)"
New-Item -ItemType Directory -Force $Dest | Out-Null
Copy-Item tools\kokoro\kokoro-v1.0.onnx, tools\kokoro\voices-v1.0.bin $Dest
$Before = [Console]::OutputEncoding.CodePage
powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -DestDir $Dest
pwsh -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -DestDir $Dest
[Console]::OutputEncoding.CodePage -eq $Before
Get-ChildItem $Dest -Filter "*.wav*"
```
Pass: both runs end `[ ok ] the Kokoro worker spoke the test line (...)` and `Kokoro is installed at: ...voix-é`, neither prints `[warn]`, the code page is unchanged, and no `fetch-check.wav` or `voice-?` file remains. Record also one run from the non-interactive orchestrator shell: if it prints `[warn]` and fails the comparison, that host has no console; note it, it is not a defect of G9 (follow-up 3). Mutation check: with `$ProbeJson = ConvertTo-Json $Probe` the 5.1 run must fail (`WinError 123` from the worker).

### 16.4 What A1 does not change

`_anchor_path`, `_resolve_binary_path` and every other Piper line; Piper's `tts.timeout_seconds`; `resident.py`'s code (docstring only); the worker's protocol and its stdout handling; the redaction machinery in `routers/config.py` and `section_registry.py`; the route; `voice.ts`; the settings registry; `config/system.yaml`.

### 16.5 Mutation rows (A1 campaign, one at a time on the frozen A1 candidate, file restored byte for byte)

New rows for A1 code and for tests the K1-K19 campaign never targeted (each locator a whole stripped line, unique in its file):

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| K20 | `resident.py`: `self.python, "-I", self.script,` | `self.python, self.script,` | R4 |
| K21 | `kokoro_worker.py`: the first `return EXIT_CANNOT_START` (in `serve`, after `refusing to start`) | `pass` | W5, R7 |
| K22 | `kokoro_worker.py`: `import numpy as np` | the same line, then `import onnxruntime` | W8 |
| K23 | `kokoro_backend.py`: `threads=cfg.threads,` | `threads=1,` | B1 |
| K24 | `kokoro_backend.py`: `if python is None or missing:` | `if python is None:` | B4, B7 |
| K25 | `kokoro_backend.py`: `if not text or not text.strip():` | `if not text:` | B5, B7 |
| K26 | `experience.py`: `"af_nova", "af_river", "af_sarah", "af_sky",` | `"af_river", "af_sarah", "af_sky",` | B6 (and 738f V1) |
| K27 | `experience.py`: `threads: int = Field(default=4, ge=1, le=16)` | `threads: int = Field(default=8, ge=1, le=16)` | C1 |
| K28 | `experience.py`: `speed: float = Field(default=1.0, ge=0.5, le=2.0)` | `speed: float = Field(default=1.0, ge=0.0, le=2.0)` | C2 |
| K29 | `section_registry.py`: `enum_values=("browser", "piper", "kokoro"),` | `enum_values=("browser", "piper"),` | C3 |
| K30 | `experience.py`: `timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0, allow_inf_nan=False)` | `timeout_seconds: float = Field(default=30.0, gt=0.0)` | C4 |
| K31 | `experience.py`: `if not value.strip() or "\x00" in value:` | `if False:` | C4 |
| K32 | `kokoro_backend.py`: `except (OSError, ValueError) as exc:  # Path.resolve on a path the OS cannot represent` | `except KeyError as exc:` | B8 |
| K33 | `kokoro_backend.py`: `wav = await self._speak(text, voice, speed)` | the same line, then `if wav is None: return None` at the same indent | B7, B8 |
| K34 | `kokoro_worker.py`: `os.replace(part, path)` together with `with wave.open(str(part), "wb") as out:` | `with wave.open(str(path), "wb") as out:` and `pass` (a direct, non-atomic write) | W9 (W1 survives by design) |
| K35 | `kokoro_worker.py`: `part.unlink(missing_ok=True)` | `pass` | W9 |
| K36 | `__init__.py`: `return KokoroBackend(config.kokoro, service=service)` | `return KokoroBackend(config.kokoro)` | S1, T1 |

Tests with no row, by design: **R1** (Piper's line without fields is the base's line: it must pass on the base; K19 covers the call shape), **T2** (the default config speaks in the browser and starts nothing: true on the base), **UI case 2** of `voice.kokoroGate.test.tsx` (the browser status makes no POST: true on the base). These three are compatibility tests; the reviewer agrees.

**Rerun from K1-K19.** Files A1 changes: `experience.py`, `kokoro_backend.py`, `kokoro_worker.py` and `resident.py` (docstrings only), `piper_backend.py` (docstrings only, no row), and the test file. Rerun K1, K4 to K19 (every row whose file or killing test changed); K2 and K3 (`voice.ts`, UI file unchanged) keep their earlier result. The A1 campaign, run once on the frozen candidate with each file's sha256 recorded, is the campaign of record for A1.

### 16.6 Contract exceptions recorded (no code)

- **Milestone tests (6.15, 6.19).** The R and W tests were written in M3, not in M1 and M2 as 6.15 and 6.19 prescribe. The commits stand; the M1 and M2 commits are not focused-test-complete on their own, and the frozen candidate is the unit of evidence.
- **ASCII (6.19, section 9 item 11, acceptance 3).** "ASCII-only" applies to hand-written text. The generated `docs/development/config-reference.md` contains `—`, `≥` and `≤` written by `gen_config_reference.py`; it is regenerated, never hand-edited. *(Extended by A2, 16.12:)* this contract's own non-ASCII characters are exempt too when they sit in a verbatim quotation (of source, a document or tool output) or in a diagnostic example that must show the character (such as the e-acute of a non-ASCII path in 16.3). Its SEARCH/REPLACE blocks are ASCII except where they carry existing text verbatim: the em dash in 6.6's quoted docstring (lines 940, 948) and in 6.14's roadmap rows (1341, 1345).

### 16.7 Section 9 after A1

| # | Was | Now tested by |
|---|---|---|
| 6 | Not verified (native fd-1; atomic write) | The "never leaves a partial WAV" half: W9 (with K34, K35). The stdout half is narrowed to what is claimed and tested: no Python-level write reaches the protocol stdout (W7, K14); a native write to fd 1 is a recorded limit (follow-up 1), so item 6 now reads "no Python-level write". |
| 8 | Not verified (timeout bounds, path strings) | C4 (K30, K31): finite timeout in (0, 600], no NaN or infinity; paths non-blank with no NUL. B8 (K32): a path that still cannot be resolved degrades. |
| 11 | Not verified as worded | Scoped by 16.6: hand-written text is ASCII and LF; the generated reference is the tool's output (`gen_config_reference.py --check`). |
| 12 | Not verified (deadline, no-raise, stdout, isolation) | Deadline: C4. No-raise: B8 and AD-738f's B2. Per-sentence INFO: B7 (K33). Isolation wording corrected at four sites (G5 to G8). Stdout: as item 6. |

### 16.8 Follow-ups recorded (the orchestrator files them; none blocks this batch)

1. The worker's protocol stdout is the process's fd 1; a native library write to fd 1 would reach the pipe (injected-only; the resident reader skips lines that are not the expected WAV path, so it is ignored at run time and only the installer's strict answer comparison would reject it; corrected after the AD-738f round-2 review). Fix sketch in 16.1 row 5.
2. Piper's `TTSConfig.timeout_seconds` (`experience.py`, `class TTSConfig`, plain `float = 10.0`; line 864 at `cffb4d99`; the orchestrator corrected A1's first anchor, which named `LipSyncConfig`'s field) accepts infinity and values past `threading.TIMEOUT_MAX`, as Kokoro's did.
3. Replaced by 16.11.4 (A1.1 removed the console-encoding swap; *A2, 16.12, restores it*, so this original item stands again as a recorded limit: a host that refuses the setting prints `[warn]`, and under a non-ASCII-compatible console the comparison may then fail). Was: the installer's answer comparison relies on setting `[Console]::OutputEncoding`.
4. AD-741's secret rule treats a dictionary key as a field name; any future dict-valued config whose keys are data meets the same redaction (here closed at parse time for `agent_voices` only).

### 16.9 Verified Against Codebase (A1, 2026-11-27, tree `f573a703`)

```text
grep -n "timeout_seconds: float = Field(default=30.0, gt=0.0)" src/probos/config_models/experience.py   668
grep -n "^from pydantic import\|^import re" src/probos/config_models/experience.py                      13, 10
grep -n "_ROLE_NAME\|def _keys_are_role_names\|python_path: str\|model_path: str\|voices_path: str" src/probos/config_models/experience.py   634, 682, 646, 650, 653
grep -n "timeout_seconds: float = 30.0" src/probos/config_models/experience.py                          715 (Piper; untouched)
grep -n "if not text or not text.strip\|resolve_executable_path(cfg.python_path)\|role=%s\|agent_type or" src/probos/audio/tts/kokoro_backend.py   110, 116, 145, 147
grep -n "def _anchor_path\|return candidate.resolve()\|def anchor_install_path\|def resolve_executable_path" src/probos/audio/tts/piper_backend.py   41, 49, 61, 67
grep -n "threading.Timer(timeout\|isolates the interpreter" src/probos/audio/tts/resident.py           289, 162
grep -n "isolates it\|def write_wav\|os.replace(part, path)\|part.unlink\|sys.stdout = sys.stderr\|encode(\"utf-8\")" scripts/kokoro_worker.py   5, 62, 75, 77, 153, 129
grep -n "ConvertTo-Json \$Probe\|import probos" scripts/kokoro-fetch.ps1                                87, 76
grep -n "python -I" THIRD_PARTY_LICENSES.md DECISIONS.md                                                174; 31
grep -n "_SECRET_RE\|def is_secret_field_id\|^import\|^from" src/probos/settings/section_registry.py   508, 511, 14-18 (stdlib only)
grep -n "is_secret_field_id" src/probos/routers/config.py                                              44, 87, 103, 277
grep -n "def test_s1_\|assert len(KOKORO_VOICES) == 28\|assert backend.enum_values\|out.name + \".part\"" tests/test_ad738g_kokoro_voice.py   548, 503, 545, 210
grep -n "enum_values=(\"browser\", \"piper\", \"kokoro\")" src/probos/settings/section_registry.py      275
grep -n "return EXIT_CANNOT_START" scripts/kokoro_worker.py                                            115, 158
```

Absence Verified (A1):
```text
CLAIM: no test pins the "NEVER raises" wrapper docstrings or the two wrapper names
RUN:   Grep "NEVER raises|anchor_install_path|resolve_executable_path" tests
FOUND: tests/test_ad722_avatar_telemetry.py:4 (an unrelated module docstring)      HOLDS: yes
CLAIM: no test pins the -I isolation wording
RUN:   Grep "cannot import .probos|isolates the interpreter|THIRD_PARTY_LICENSES" tests
FOUND: test_ad705a_offline_stt_config.py:48, :59 (whisper.cpp sections only)       HOLDS: yes
CLAIM: no test builds a Kokoro path that is blank, or a timeout above 600
RUN:   Grep "(python_path|model_path|voices_path)=[\"']\s*[\"']|timeout_seconds=(\d{4,}|float)" tests
FOUND: test_bf825_a_run_someone_is_waiting_on.py:737 (strand_timeout_seconds; unrelated)   HOLDS: yes
CLAIM: no test counts the Kokoro INFO records, so a line on degraded attempts breaks none
RUN:   Grep "kokoro is not installed|no voice synthesis service|AD-738g: kokoro|kokoro.*caplog\.records" tests
FOUND: test_ad738g_kokoro_voice.py:392, :422, :468, :489; test_ad738f_per_agent_voices.py:181 (all substrings)   HOLDS: yes
CLAIM: config_models imports nothing outside config_models today, and no structural test forbids importing probos.settings
RUN:   Grep "^\s*from probos\.[a-z_]+ import|^\s*from probos\.[a-z_]+\." src/probos/config_models; Read test_ad1270e2c_experience_models.py:501-512
FOUND: only config_models.__init__ re-imports; the structural test forbids probos.config only   HOLDS: yes
CLAIM: GF1 adds no facade name
RUN:   Read scripts/check_config_facade.py:1020 (vars(probos.config)); config.py imports experience names by an explicit list (738f Absence Verified)
FOUND: is_secret_field_id is not re-exported                                         HOLDS: yes
```

### 16.10 Prior art (A1)

Repair round; no new design. The escape is the standard JSON `\uXXXX` form (RFC 8259 section 7, which allows each UTF-16 unit of a surrogate pair to be escaped separately); reading native output requires `[Console]::OutputEncoding` in both PowerShell 5.1 and 7 (`about_Character_Encoding`). No external search was run.

### 16.11 Amendment A1.1: the installer guard replaces G9 (2026-11-27)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27. **Base:** `7c63d3dc` (A1 applied and committed). Source: the orchestrator's probes `G:\speech-kokoro-probe\probe_g9_ascii_venv.ps1` and `probe_isolate_espeak.ps1` (2026-11-27).

> **Corrected by A2 (16.12), 2026-11-27. Three readings in 16.11 are false; the text below stays as A1.1 wrote it.** (1) The console-encoding swap is not dead code, and "ASCII under any console encoding" (H3's comment, 16.11.3) is wrong: PowerShell decodes the worker's UTF-8 answer with `[Console]::OutputEncoding`, and a UTF-16 console garbles even an ASCII answer, so H3 fails the comparison after a successful synthesis (orchestrator's `probe_utf16_console.ps1`, 5.1 and 7; round-2 review finding 2). A2 restores the swap. (2) H2 does not test "the resolved `$DestDir`": it tests the text after root anchoring, and `IsPathRooted` is true for a drive-relative `G:x`, which then resolves against a current directory that may be non-ASCII (`probe_driverel.ps1`; finding 1). A2 resolves to the full provider path first. (3) 16.11.1 and 16.11.2's "the hand check above discriminates" are replaced by 16.12.3.

**Decision: (b).** G9's transport is correct, but its premise in 16.1 row 2 ("a non-ASCII destination" is a valid one) is refuted: espeak-ng cannot open its data from a venv whose path has a non-ASCII character (isolation: non-ASCII venv + ASCII model paths = exit 1, `...espeak-ng-data\phontab: No such file or directory`; ASCII venv + non-ASCII model and output paths = wav written). The installer always puts the venv and the probe under `$DestDir`, so the escape and the console-encoding swap are reachable only on a run that cannot succeed. A guard on the resolved `$DestDir`, before anything is created, is the real protection; the dead code goes with it, and the script no longer touches the user's console state. (a) keeps unreachable code; (c) leaves the obscure failure after a 350 MB download and a venv build.

**Order.** H1 to H3 to `scripts/kokoro-fetch.ps1`, then H4 to `DECISIONS.md`. Working copies CRLF, blocks LF: match after normalising. Each SEARCH occurs once in its file at its turn (counted on `7c63d3dc`). The orchestrator commits: subject `Speech: the Kokoro installer refuses a non-ASCII destination up front (espeak-ng limit) instead of escaping its pipe`, body ends `Refs #1662.`; stage exactly `scripts/kokoro-fetch.ps1`, `DECISIONS.md`, and this contract.

**H1.** `scripts/kokoro-fetch.ps1` header. SEARCH:
```powershell
#   3. One test sentence spoken through scripts/kokoro_worker.py, the worker ProbOS runs.
#
```
REPLACE:
```powershell
#   3. One test sentence spoken through scripts/kokoro_worker.py, the worker ProbOS runs.
#
# The destination must be an ASCII-only path: espeak-ng, inside the venv, cannot open its
# data under a path with a non-ASCII character (measured 2026-11-27), so the script refuses
# one before creating anything. The model files and the output may live anywhere. If this
# checkout's path is not ASCII, pass -DestDir to an ASCII folder and set tts.kokoro.python_path,
# model_path and voices_path in config/system.yaml to the absolute paths there.
#
```

**H2.** The guard, right after `$DestDir` is resolved and before `uv` is looked up or any folder is made. SEARCH:
```powershell
if (-not [System.IO.Path]::IsPathRooted($DestDir)) { $DestDir = Join-Path $Root $DestDir }
```
REPLACE:
```powershell
if (-not [System.IO.Path]::IsPathRooted($DestDir)) { $DestDir = Join-Path $Root $DestDir }
if ($DestDir -match '[^\x00-\x7F]') {
    throw "The destination '$DestDir' contains a non-ASCII character. espeak-ng (inside the Kokoro venv) cannot open its data under such a path. Run again with -DestDir set to an ASCII-only folder (for example C:\kokoro), then set tts.kokoro.python_path, model_path and voices_path in config/system.yaml to the absolute paths there. Nothing was created."
}
```

**H3.** G9 reverted to the pre-A1 pipe, with one comment. SEARCH:
```powershell
# Windows PowerShell 5.1 pipes text to a native program as ASCII ($OutputEncoding), so a
# non-ASCII destination would reach the worker as '?': escape each non-ASCII UTF-16 unit as
# \uXXXX, which the worker's json.loads decodes. The worker answers in UTF-8; the console
# decodes it as UTF-8 for the comparison and gets its own encoding back afterwards.
$ProbeJson = [regex]::Replace((ConvertTo-Json $Probe), '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + $ProbeJson + ', "voice": "af_heart", "speed": 1.0}'
$ConsoleEncoding = [Console]::OutputEncoding
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { Write-Host "[warn] cannot set the console encoding; a non-ASCII path may fail the comparison" -ForegroundColor Yellow }
try {
    $Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
    $Exit = $LASTEXITCODE
} finally {
    try { [Console]::OutputEncoding = $ConsoleEncoding } catch { }
}
if ($Exit -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $Exit, answer '$Answer'); its messages are above."
}
```
REPLACE:
```powershell
# $Probe lies under $DestDir, which the guard above keeps ASCII, so the piped line and the
# worker's answer are ASCII under any console encoding (PowerShell 5.1 pipes ASCII).
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + (ConvertTo-Json $Probe) + ', "voice": "af_heart", "speed": 1.0}'
$Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $LASTEXITCODE, answer '$Answer'); its messages are above."
}
```

**H4.** `DECISIONS.md`, the AD-738g S1 entry: one bullet after *Licence*. SEARCH (the end of the *Licence* line; occurs once):
```markdown
that venv does not contain `probos` (the install script checks it cannot import it), and `python -I` keeps `PYTHON*` variables and the user site out.
```
REPLACE: the same text, then a new line:
```markdown
- *Limit.* The venv must live under an ASCII-only path: espeak-ng cannot open its data from a path with a non-ASCII character (measured 2026-11-27). `scripts/kokoro-fetch.ps1` refuses such a destination before creating anything; the model, voices and output paths may be anything. An escaped installer pipe (A1's G9) was replaced by this guard, because the run it served cannot succeed.
```

`PROGRESS.md`: no pair. Its AD-738g paragraph (line 5) does not mention the pipe or the escape (searched: `ASCII|pipe|test line` find nothing on line 5). The A1 repair commit `7c63d3dc` names "an ASCII installer pipe" in its subject; commits are history and stay as they are; the A1.1 commit supersedes it.

**Contract text changed in place by A1.1** (no pair; already edited in this file): section 12's licence bullet gains the limit; section 13's Captain step 1 gains the ASCII-path note; 16.3's installer paragraph is marked superseded; 16.8 follow-up 3 is replaced. 16.1 row 2 and 16.10 stay as written: the audit trail of what A1 decided.

#### 16.11.1 Installer end-to-end (replaces the 16.3 installer paragraph; the orchestrator, by hand)

> **Superseded by 16.12.3 (A2).** Kept as the record of what A1.1 asked.

From the worktree root, PowerShell 5.1 and 7 both:
```text
$Bad = "G:\speech-kokoro-probe\voix-$([char]0xE9)-a11"
Test-Path $Bad                                                            # must be False before
powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -DestDir $Bad; $LASTEXITCODE
pwsh -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -DestDir $Bad; $LASTEXITCODE
Test-Path $Bad                                                            # must still be False
powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1
powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1
```
Pass: (1) each non-ASCII run exits 1 at once (seconds, no `uv` output, no `[get ]`) with the message `The destination '...voix-<e-acute>-a11' contains a non-ASCII character. espeak-ng ...`, and `$Bad` does not exist afterwards; (2) the first ASCII run (default `tools/kokoro`, models present) ends `[ ok ] the Kokoro worker spoke the test line (...)` and `Kokoro is installed at: ...`; (3) the second prints two `[skip]` lines and ends the same way. No `[warn]` line can appear (the line is gone).

**Mutation (campaign of record: the orchestrator's probe, not rerun).** The mutant "guard removed" is exactly the pre-A1.1 script on a non-ASCII `-DestDir`, which the orchestrator ran on 2026-11-27: the venv was built, the worker loaded 54 voices, synthesis failed with the espeak `phontab` error, exit 1. The guard is therefore load-bearing for the message and for "nothing created", not for success. No other row changes: K1 to K36 touch no installer line.

#### 16.11.2 Tests

None added. The installer has no automated test by design; the only cheap test would spawn `powershell.exe` (Windows-only, skipped in CI) or scan the script's source (a `?raw`-style pin that cannot tell a required line from a shipped one). The hand check above discriminates, and the mutant's result is on record. The test count stays 32.

#### 16.11.3 Finding 2 for the round-2 reviewer (Readings, for its Assumptions check)

Finding 2 is **fixed by a different repair than A1 recorded**. Give the reviewer:
- *Reading.* Finding 2 said a non-ASCII destination reaches the worker as `?` under PowerShell 5.1. True, and G9 fixed that transport (orchestrator probe, ASCII venv + non-ASCII output path: plain `ConvertTo-Json` fails on 5.1 and 7, G9 succeeds on both). But a non-ASCII destination is not a valid install: the venv lives under it, and espeak-ng cannot open its data from a non-ASCII venv path (isolation run, 2026-11-27). So the finding's premise "a valid destination fails" does not hold; what remained was an obscure failure after a full download and venv build.
- *Repair.* A1.1 (H2) refuses a non-ASCII resolved `-DestDir` with a named message before anything is created, and (H3) removes G9's escape and console-encoding swap, which are unreachable once the guard holds. Check: H2 tests the resolved path (after `Join-Path $Root`), throws before `uv` and `New-Item`, and names the path; H3's comparison is ASCII under any console encoding because `$Probe` is under `$DestDir`.
- *Assumption to check.* That the probe path cannot become non-ASCII other than through `$DestDir` (it is `Join-Path $DestDir "fetch-check.wav"`), and that the model, voices and worker paths are passed as arguments (Unicode-safe), not through the pipe.

#### 16.11.4 Follow-up (replaces 16.8 item 3)

3. A non-ASCII `tts.kokoro.python_path` (or a default install under a non-ASCII checkout) passes config and fails at the first sentence with espeak's error in the worker's stderr. A WARNING at backend start naming the limit (one check in `kokoro_backend.py`, one test) would make it visible. Not in this batch: no supported install produces it once the guard holds, and the Captain's `D:\ProbOS` is ASCII.

#### 16.11.5 Verified Against Codebase (A1.1, 2026-11-27, tree `7c63d3dc`)

```text
grep -n "IsPathRooted\|New-Item -ItemType Directory\|uv venv --python" scripts/kokoro-fetch.ps1   27, 38, 45 (guard goes before 35's uv check)
grep -n "ProbeJson\|OutputEncoding\|\$Probe = Join-Path \$DestDir" scripts/kokoro-fetch.ps1        91-92, 93-99, 85
grep -n "\$Venv = Join-Path \$DestDir" scripts/kokoro-fetch.ps1                                    41
grep -n "that venv does not contain .probos." DECISIONS.md                                        31 (count 1)
```
Absence Verified (A1.1):
```text
CLAIM: no test pins the installer's text
RUN:   Grep "kokoro-fetch|OutputEncoding|ProbeJson" tests
FOUND: test_ad738g_kokoro_voice.py:489 (a log substring naming the script); test_bf957 (git's logOutputEncoding, unrelated)   HOLDS: yes
CLAIM: PROGRESS.md's AD-738g paragraph does not mention the pipe or the escape
RUN:   Grep "ASCII|pipe|test line|speaks one" PROGRESS.md
FOUND: lines 43, 47, 49, 174, 205+ (other entries); none on line 5                                 HOLDS: yes
```

#### 16.11.6 Prior art

No new design: an up-front input check. The espeak-ng limit is the orchestrator's measurement; no external search was run, and none is cited as its cause (the C library falling back to its build-time data path is what the error shows, not a documented contract). Considered, deferred: a worker-side workaround (copying `espeak-ng-data` to an ASCII temp folder or using an 8.3 short path), which would widen the protocol slice for a case no supported install reaches.

### 16.12 Amendment A2: review round 2 repairs (2026-11-27)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27. **Base:** `d6bbd913` (clean; A1, A1.1 and the orchestrator's two docs commits applied). Sources: `review-738g-r2.md` (agent 3de72541) and `review-738f-r2.md` (agent 583bb6be), the orchestrator's probes `G:\speech-kokoro-probe\probe_driverel.ps1` and `probe_utf16_console.ps1` (2026-11-27, PowerShell 5.1 and 7).

#### 16.12.1 Decisions

| 738g r2 finding | Decision | Reason |
|---|---|---|
| 1 P2 the guard reads unresolved text | **Fix (A2-1).** After the root anchoring, `$DestDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestDir)`, then the guard. | `IsPathRooted` is true for `G:x` and `\x`, which resolve against a current directory. This API resolves a path that need not exist against PowerShell's current location on that drive, as `New-Item` does; the orchestrator confirmed it gives `G:\ascii-destination-check`. Writing it back to `$DestDir` hands `New-Item`, `uv` and Python one absolute path, so a native process cannot resolve a relative path against a different current directory. A drive that does not exist (`Q:x`) throws PowerShell's own error before anything is created: accepted. |
| 2 P2 regression (A1.1) the answer is garbled under a UTF-16 console | **Fix (A2-2): restore A1's UTF-8 scope around the worker call, console restored in `finally`; no escape.** | PowerShell decodes native output with `[Console]::OutputEncoding`. A1's block passed under a UTF-16 console on both versions; with an ASCII path its escape changes nothing, so that probe is evidence for A2-2. **Rejected: `System.Diagnostics.Process` with `StandardOutputEncoding`.** On 5.1 (.NET Framework) `ProcessStartInfo` has no `ArgumentList`, so four paths, the worker's lying under a checkout that may be non-ASCII or contain spaces, would need a hand-quoted `Arguments` string, as well as stdin write-and-close and stderr passthrough: about 15 new untested lines against 7 measured ones. The console change is scoped and restored, the idiom `about_Character_Encoding` gives. **Rejected: dropping the answer comparison.** It is the installer's only check that the protocol stdout carries exactly the path (16.8 item 1). |
| 3 P3 the Captain's check expects `af_heart` per sentence | **Fixed in place**: section 13, Captain step 5. | It now matches `kokoro_backend.py:124-126` with AD-738f's `role=` field and the table voice (counselor `af_bella`), and says the ship voice appears with `role=-` or for a role neither table names (`kokoro_backend.py:92-93`). AD-738f's own check (its contract, line 1265) already says this. D10 (section 3) stays as written: it is 738g's own record, and 738f records the appended field. Searched: section 12's issue text names no per-sentence voice; lines 1505 and 2278 are test bodies. |
| 4 P4 `DECISIONS.md:32` join | Fixed in `d6bbd913`. | Nothing in A2. |
| 5 P4 the ASCII exception is not literal | **Extend 16.6 (done in place)** to verbatim quotations (including existing text a SEARCH/REPLACE block carries) and diagnostic examples. | ASCII-ifying a quotation would falsify it, and the e-acute in 16.3's example is the point of the example. Enumerated: `[^\x00-\x7F]` in this contract hits only 940, 948, 1341, 1345 (quoted source and roadmap text), 2396 (16.3's example) and 2433 (16.6 quoting the generated reference). Generated files are untouched. |
| 6 P3 K-FD1 record | Fixed (contract 16.8 item 1, #1869). | Nothing in A2. |
| 7 P4 NaN comment | **Fix (A2-3)**, comment only. | `Condition.wait` treats a timeout that is not `> 0` as no wait, so `Timer(nan)` fires at once (0.48 ms in the probe), the opposite of "never". The assertions stay. |
| K-TIMEOUT-PIPER | Stays P3, pre-existing, in #1869 (anchor `TTSConfig.timeout_seconds`, `experience.py:864`). | Both reviewers place it there. |

`DECISIONS.md`: **no pair.** The *Limit* bullet (line 32) says the script "refuses such a destination before creating anything" and that the escaped pipe was replaced. Both statements hold after A2, and A2-1 makes the first true for drive-relative input. The bullet never mentioned the console swap.

AD-738f contract: **no edit.** Its round-2 repairs are `d6bbd913` and #1869.

#### 16.12.2 The pairs

**Order.** A2-1, then A2-2 to `scripts/kokoro-fetch.ps1`; A2-3 to `tests/test_ad738g_kokoro_voice.py`. The working copies are CRLF and the blocks LF: match after normalising. Each SEARCH occurs once in its file at its turn (counted on `d6bbd913`). Focused check: `pytest tests/test_ad738g_kokoro_voice.py -q -n 0` (32 pass; the only Python change is a comment). Commit (the orchestrator): subject `Speech: the Kokoro installer checks the resolved destination and decodes the worker's answer as UTF-8 again (AD-738g A2)`, body ends `Refs #1662.`; stage exactly `scripts/kokoro-fetch.ps1`, `tests/test_ad738g_kokoro_voice.py` and this contract.

**A2-1.** SEARCH:
```powershell
if (-not [System.IO.Path]::IsPathRooted($DestDir)) { $DestDir = Join-Path $Root $DestDir }
```
REPLACE:
```powershell
if (-not [System.IO.Path]::IsPathRooted($DestDir)) { $DestDir = Join-Path $Root $DestDir }
# IsPathRooted is also true for a drive-relative "G:kokoro" or a root-relative "\kokoro",
# which name a folder under a current directory. Check the full path, and hand that one
# absolute path to New-Item, uv and Python alike.
$DestDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestDir)
```

**A2-2.** SEARCH:
```powershell
# $Probe lies under $DestDir, which the guard above keeps ASCII, so the piped line and the
# worker's answer are ASCII under any console encoding (PowerShell 5.1 pipes ASCII).
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + (ConvertTo-Json $Probe) + ', "voice": "af_heart", "speed": 1.0}'
$Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $LASTEXITCODE, answer '$Answer'); its messages are above."
}
```
REPLACE:
```powershell
# $Probe lies under $DestDir, which the guard above keeps ASCII, so the piped line needs no
# escaping (PowerShell 5.1 pipes ASCII). The worker answers in UTF-8, and PowerShell decodes
# a native program's output with [Console]::OutputEncoding, which need not be ASCII-compatible
# (a UTF-16 console garbles even an ASCII answer): the console decodes UTF-8 for this one
# call and gets its own encoding back afterwards.
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + (ConvertTo-Json $Probe) + ', "voice": "af_heart", "speed": 1.0}'
$ConsoleEncoding = [Console]::OutputEncoding
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { Write-Host "[warn] cannot set the console encoding; the answer comparison may fail" -ForegroundColor Yellow }
try {
    $Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
    $Exit = $LASTEXITCODE
} finally {
    try { [Console]::OutputEncoding = $ConsoleEncoding } catch { }
}
if ($Exit -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $Exit, answer '$Answer'); its messages are above."
}
```

**A2-3.** `tests/test_ad738g_kokoro_voice.py`, `test_c4_...`. SEARCH:
```python
    # threading.Timer raises OverflowError past TIMEOUT_MAX (4294967.0 on Windows) inside its
    # own thread, so the deadline would silently never fire; infinity and NaN never fire either.
```
REPLACE:
```python
    # threading.Timer raises OverflowError past TIMEOUT_MAX (4294967.0 on Windows) inside its
    # own thread, so the deadline would silently never fire; infinity is past it too. NaN is
    # the opposite: Condition.wait treats it as no wait, so the timer fires at once and every
    # sentence would time out (measured 2026-11-27).
```

**Contract text changed in place by A2** (no pair; already edited in this file): section 13, Captain step 5 (finding 3); 16.6's ASCII bullet (finding 5); 16.8 item 3 (the swap is back); a correction banner under 16.11's provenance line and a superseded banner on 16.11.1. 16.11's own text stays as A1.1 wrote it.

#### 16.12.3 Installer end-to-end (replaces 16.11.1; the orchestrator, by hand, from the worktree root)

**Step 0, parse (a 5.1 window and a 7 window):**
```text
$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path scripts\kokoro-fetch.ps1).Path, [ref]$null, [ref]$e); $e.Count
```
Pass: `0` in both.

**Session A, the refusals (one window, either version; the children run both). `uv` is hidden, so no run can build anything, before A2 or after:**
```text
$Wt = (Get-Location).Path
$env:PATH = ($env:PATH -split ';' | Where-Object { $_ -and -not (Test-Path (Join-Path $_ 'uv.exe')) }) -join ';'
Get-Command uv -ErrorAction SilentlyContinue                      # must print nothing
$Bad = "G:\speech-kokoro-probe\voix-$([char]0xE9)-a2"
$Cwd = "G:\speech-kokoro-probe\voix-$([char]0xE9)-cwd"
New-Item -ItemType Directory -Force $Cwd | Out-Null
Test-Path $Bad; Test-Path "$Cwd\rel-a2"                           # False, False
powershell -ExecutionPolicy Bypass -File "$Wt\scripts\kokoro-fetch.ps1" -DestDir $Bad; $LASTEXITCODE     # (a5)
pwsh -ExecutionPolicy Bypass -File "$Wt\scripts\kokoro-fetch.ps1" -DestDir $Bad; $LASTEXITCODE           # (a7)
Push-Location $Cwd
powershell -ExecutionPolicy Bypass -File "$Wt\scripts\kokoro-fetch.ps1" -DestDir G:rel-a2; $LASTEXITCODE # (b5)
pwsh -ExecutionPolicy Bypass -File "$Wt\scripts\kokoro-fetch.ps1" -DestDir G:rel-a2; $LASTEXITCODE       # (b7)
Pop-Location
Test-Path $Bad; Test-Path "$Cwd\rel-a2"                           # still False, False
```
Pass: (a5) and (a7) exit 1 at once with `The destination 'G:\speech-kokoro-probe\voix-<e-acute>-a2' contains a non-ASCII character. ...`. (b5) and (b7) exit 1 at once with `The destination 'G:\speech-kokoro-probe\voix-<e-acute>-cwd\rel-a2' contains a non-ASCII character. ...`: the message names the **resolved** path, not `G:rel-a2`. No run prints `uv is required`. Both folders are still absent afterwards. (If `Get-Command uv` prints a path, remove that folder from `$env:PATH` too.)

**Session B, the worker call (normal PATH; the models are present under this worktree's gitignored `tools/kokoro`). In a 5.1 window and then a 7 window, entering the lines one at a time:**
```text
$Saved = [Console]::OutputEncoding
[Console]::OutputEncoding = [System.Text.Encoding]::Unicode
& .\scripts\kokoro-fetch.ps1                                       # (c5) / (c7)
[Console]::OutputEncoding.WebName                                  # must print utf-16
[Console]::OutputEncoding = $Saved
```
Then, with the console as it was:
```text
powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1   # (d5)
pwsh -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1         # (e7)
```
Pass: (c5) and (c7) each print two `[skip]` lines (the idempotent re-run on both versions), no `[warn]`, and end `[ ok ] the Kokoro worker spoke the test line (... bytes of 24 kHz WAV)`. `WebName` prints `utf-16` afterwards, so the `finally` restored the caller's console. (d5) and (e7) end the same way, followed by `Kokoro is installed at: <worktree>\tools\kokoro`, an absolute path.

#### 16.12.4 Mutation rows of record (run the two "before" runs on `d6bbd913`, before the Builder applies A2)

| Row | Mutant | Discriminating step | Expected on the mutant | Status |
|---|---|---|---|---|
| KA1 | A2-1's resolve line absent (exactly `d6bbd913`) | Session A (b5), (b7) | prints `uv is required ...`: the guard passed the ASCII text | Run live before A2 (safe: `uv` is hidden, so it throws before `New-Item`). Also on record: `probe_driverel.ps1` (guard on the text rejects False; resolved path non-ASCII True; 5.1 and 7) |
| KA2 | A2-2's UTF-8 scope absent (exactly `d6bbd913`) | Session B (c5), (c7) | `The Kokoro worker did not speak the test line (exit 0, answer '...')` | Run live before A2. Also on record: `probe_utf16_console.ps1` (A1.1 block FAIL, A1 block PASS, both versions) |
| -- | the `finally` restore removed | Session B's `WebName` line | prints `utf-8` | Not run as a mutant: A1's line is unchanged and the check prints it on every run |

K1 to K36: no row touches the installer or the C4 comment, so none is rerun. A2-3 is a comment and has no row.

#### 16.12.5 Tests

None added; the count stays 32 Python and 3 UI. A cheap discriminating test for A2-2 does not exist. A PowerShell parse of the script (step 0) passes on both the defective and the repaired block, so it guards syntax only, and it stays a hand step rather than a Windows-only pytest. Exercising the comparison needs `uv`, the venv and the real models, because the installer hardcodes the worker. Sessions A and B with KA1 and KA2 are the discriminating evidence.

#### 16.12.6 Verified Against Codebase (A2, 2026-11-27, tree `d6bbd913`)

```text
git log --oneline -1                                                     d6bbd913 (HEAD)
grep -n "IsPathRooted" scripts/kokoro-fetch.ps1                          33 (count 1)
grep -n "contains a non-ASCII character" scripts/kokoro-fetch.ps1        35 (guard at 34-36, before uv check 44 and New-Item 47)
grep -n "worker's answer are ASCII under any console encoding" scripts/kokoro-fetch.ps1   97 (A2-2 SEARCH = 96-102)
grep -n "never fire either" tests/test_ad738g_kokoro_voice.py           622 (count 1; A2-3 SEARCH = 621-622)
grep -n "AD-738g: kokoro voice=%s .* role=%s" src/probos/audio/tts/kokoro_backend.py   124; role or "-" at 126
grep -n "agent_voices" src/probos/audio/tts/kokoro_backend.py            92-93 (the Captain's map; precedence listed in resolve_voice's docstring, 80-85)
grep -n "voice=af_bella ... result=ok role=counselor" prompts/ad-738f-s1-per-agent-kokoro-voices.md   1265
grep -n "\*Limit\.\* The venv must live" DECISIONS.md                    32
```
Absence Verified (A2):
```text
CLAIM: the script has no $Exit and no OutputEncoding today (A2-2 introduces both)
RUN:   Grep "\$Exit|OutputEncoding" scripts/kokoro-fetch.ps1
FOUND: nothing                                                                       HOLDS: yes
CLAIM: no test reads the installer's text or the C4 comment
RUN:   Grep "kokoro-fetch|never fire" tests
FOUND: test_ad738g_kokoro_voice.py:489 (a log substring naming the script), :622 (the comment itself); others are unrelated "never fire(d)" prose   HOLDS: yes
CLAIM: no other per-sentence af_heart expectation in this contract outside test bodies
RUN:   Grep "voice=af_heart.{0,120}" -o prompts/ad-738g-s1-local-kokoro-voice.md
FOUND: 1505, 2278 (test bodies), 1870 (section 13; corrected by A2)                  HOLDS: yes
```

#### 16.12.7 Prior art

Repair round; no new design. `PathIntrinsics.GetUnresolvedProviderPathFromPSPath` is PowerShell's documented resolver for a path that need not exist. The console-decoding behaviour is the one 16.10 already cited (`about_Character_Encoding`). No external search was run.

### 16.13 Amendment A3: CI repair, the interpreter path on POSIX (2026-11-27)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27. **Base:** `88676ab1` (the speech batch head before the repair). Source: GitHub Actions run 46104840915 on PR #1872; the orchestrator's runner probe, run 46106607981; the round-three brake decision **continue** (pairs P1 to P6), applied as written. A3 supersedes 16.2 and 6.4 where they define `resolve_executable_path`, and the `test_b1` expectation in 6.15; it adds 3 tests (B9, B10, B11).

**Round five (2026-11-27, applied by the orchestrator under the Architect's decision "any finding from round five is repaired in place and goes straight to the gate").** The Diff Reviewer (`gpt-6.1-sol`) reported two findings. **F-CI-2 (P2, ordinary reach, not a regression: the previous helper did the same):** a Windows drive-relative interpreter path such as `C:python.exe` is not absolute, so joining it to the install root dropped the root and left the launch to that drive's current directory (16.13.1a). **A P3 on this text:** it said "every POSIX host" and "Linux is the only platform", and it quoted T3 as `disabled == kokoro`. Both are repaired in this section: the helper (P2 below), the Windows-only test B11 (P5), mutation row MA3-3, and the corrected wording. The pairs below are the final applied text.

#### 16.13.1 Finding F-CI-1 (P1 on POSIX)

`resolve_executable_path` (`piper_backend.py:69-74`) delegates to `_resolve_binary_path`, which returns `candidate.resolve()` (`piper_backend.py:49`). A POSIX venv's `bin/python` is a symlink to its base interpreter, and Python finds its venv from the `pyvenv.cfg` beside the path it was started as. Started through the link's target, the Kokoro worker runs in the base interpreter and cannot import the venv's packages. Wherever the venv's interpreter is a symlink (the default of `python -m venv` and `uv venv` on POSIX; `--copies` makes a real file), the backend therefore starts a worker that dies at its first import: the feature cannot work with such a venv, and the Windows gate cannot see it (a Windows venv's `python.exe` is a copy, not a link).

Evidence (2026-11-27):
- **The failures.** Run 46104840915: shard 2 failed `test_ad738g_kokoro_voice.py::test_t1_post_tts_speaks_kokoro_through_the_real_worker_loop`; shard 1 failed `test_ad738f_per_agent_voices.py::test_t1_...`, `::test_t2_...` and `::test_t3_...`. All four print `ModuleNotFoundError: No module named 'numpy'` from `tests/fixtures/fake_kokoro_worker.py` line 20 (`import numpy as np`). The same log installs `numpy==2.5.1` into the venv.
- **The differential control.** R5 and R6 (`test_ad738g_kokoro_voice.py:368`, `:388`; no skip or platform marker; each asserts a 24 kHz WAV came back) spawn the same fake worker through `_real_key`, whose key carries `python=sys.executable` unresolved (`:70`). Both passed in the same shard-2 file run that failed T1. Same venv, same worker; the only difference is the resolved path.
- **The runner probe.** Throwaway branch `probe/speech-symlink-20261128` (deleted), run 46106607981, `ubuntu-latest`, `uv venv .venv` then `uv pip install numpy` (numpy 2.5.5). `sys.executable` = `/home/runner/work/ProbOS/ProbOS/.venv/bin/python`; `os.path.islink` True; `os.path.realpath` = `/opt/hostedtoolcache/Python/3.12.16/x64/bin/python3.12`. Started as configured, with `-I` and without: rc 0, `sys.prefix` = the venv, `numpy 2.5.5`. Started through the resolved path, with `-I` and without: rc 1, `sys.prefix` = `/opt/hostedtoolcache/Python/3.12.16/x64`, `ModuleNotFoundError: No module named 'numpy'`.
- **No local reproduction.** This host has no WSL or Docker and the account has no symlink privilege. The runner probe is the direct evidence; the repaired tree's own CI run is the end-to-end confirmation, because the four failing tests are the chain test (backend, real worker process, numpy importable) and they show the fix wherever the test interpreter is a symlinked venv interpreter. The platform measured is one Ubuntu runner; macOS has the same symlink default and was not measured.
- **The repair, on the runner image, before the gate** (orchestrator; run 46107061250 for P1 to P5 and run 46108932695 for the final patch, which adds the round-five repair; throwaway branches `probe/speech-symlink-repair-20261128` and `probe/speech-symlink-final-20261128` at the PR head, both deleted; the repair applied as a patch at run time, so no unreviewed commit was pushed; the install is ci.yml's `uv sync --group dev --extra discovery --extra browser`). The four tests that failed on PR 1872, before the patch: `4 failed in 2.81s` (`2.01s` in the second run), three with `assert 'disabled' == 'kokoro'` and T3 with `assert 0 == 50` (its `duration_ms`), all with `ModuleNotFoundError: No module named 'numpy'` (the control reproduces CI's failure). After `git apply`, the six files of the focused check below at `-n 0`: P1 to P5 gave `132 passed, 1 skipped in 10.08s`; the final patch (two files, 87 insertions and 6 deletions) gave `132 passed, 2 skipped in 7.61s`, B10 included (a real symlink on Linux); the second skip is B11, which is Windows-only.

`test_b1` (`test_ad738g_kokoro_voice.py:433`) asserted `python=str(Path(sys.executable).resolve())`: a test that pinned the defect as the contract. P4 updates it with the reason inline; it is not deleted, and no POSIX-only skip is added to the four tests.

#### 16.13.1a Finding F-CI-2 (P2, found by the round-five review; ordinary reach, not a regression)

A Windows drive-relative path such as `C:python.exe` is not absolute (`Path.is_absolute()` is False: a drive without a root). `_probos_root() / Path("C:python.exe")` keeps the other drive and drops the root, so the interpreter is found relative to that drive's current directory. The previous helper did the same; the replacement's docstring said "never the CWD", which this case falsified. The reviewer's probe: `KokoroTTSConfig(python_path="C:python.exe")` is accepted; with the CWD beside the base interpreter, both `KokoroWorkerKey.python` and a real `Popen` received that interpreter (the worker then failed importing numpy); with another CWD the same configuration degraded before launch. Repair: the helper refuses a drive-qualified, non-absolute path with `ValueError` before joining (P2), and the backend degrades as it does for a NUL. B11 (Windows only) covers the helper and the backend; MA3-3 kills its removal. Scope: the interpreter only. `model_path` and `voices_path` go through `anchor_install_path` and share the drive-relative dependence as data-file paths; that is one line for #1869 (16.13.6), not part of this repair. On POSIX `C:python.exe` is an ordinary relative file name and stays one.

#### 16.13.2 The pairs (as applied)

**Order.** P1, P2 to `src/probos/audio/tts/piper_backend.py`; P3 (two pairs), P4, P5 to `tests/test_ad738g_kokoro_voice.py`. Match after normalising CRLF to LF. `tests/fixtures/fake_kokoro_worker.py` and `kokoro_backend.py` do not change. Leave `kokoro_backend.py:148` alone: it only formats the "missing" message, and the resolved target of a dangling venv link is the useful thing to name there. 16.4's "`_anchor_path`, `_resolve_binary_path` and every other Piper line" still holds: P2 changes only the Kokoro-only helper (its only callers are `kokoro_backend.py:26,142`).

**P1: `src/probos/audio/tts/piper_backend.py`, imports.** SEARCH:
```python
import logging
import sys
from pathlib import Path
```
REPLACE:
```python
import logging
import os
import sys
from pathlib import Path
```

**P2: `piper_backend.py`, the helper** (Piper's `_anchor_path` and `_resolve_binary_path` stay byte-identical). SEARCH:
```python
def resolve_executable_path(configured: str) -> Path | None:
    """AD-738g: ``_resolve_binary_path`` for the sibling Kokoro backend (anchored; ``.exe``
    appended on Windows when the literal path is missing). ``None`` when not found. Raises
    ``OSError`` or ``ValueError`` for a path the OS cannot represent, as ``anchor_install_path``
    does; the Kokoro backend catches both and degrades."""
    return _resolve_binary_path(configured)
```
REPLACE:
```python
def resolve_executable_path(configured: str) -> Path | None:
    """AD-738g: the Kokoro backend's interpreter, anchored as ``_anchor_path`` anchors (absolute
    as-is, relative under ``_probos_root()``, never the CWD), with ``.exe`` appended on Windows
    when the literal path is missing. ``None`` when not found.

    A3 (F-CI-1): the path is made absolute with ``os.path.abspath`` and NOT resolved. A POSIX
    venv's ``bin/python`` is a symlink to its base interpreter, and Python finds the venv by the
    ``pyvenv.cfg`` beside the path it was started as. Started through the link's target, it
    cannot import the venv's packages. The ``.exe`` probe mirrors ``_resolve_binary_path``,
    which Piper keeps unchanged. Raises ``ValueError`` for a path holding a NUL on every
    platform (``ntpath.abspath`` would otherwise swallow it), and on Windows for a drive-relative
    path such as ``C:python.exe``: it is not absolute, and joining it to the install root would
    drop the root and leave the launch to that drive's current directory. The Kokoro backend
    catches the ``ValueError`` and degrades."""
    if "\x00" in configured:
        raise ValueError("embedded null byte")
    candidate = Path(configured)
    if not candidate.is_absolute():
        if candidate.drive:
            raise ValueError("a drive-relative path depends on the working directory")
        candidate = _probos_root() / candidate
    p = Path(os.path.abspath(candidate))
    if p.is_file():
        return p
    if sys.platform == "win32" and p.suffix.lower() != ".exe":
        with_exe = p.parent / (p.name + ".exe")
        if with_exe.is_file():
            return with_exe
    return None
```

**P3: `tests/test_ad738g_kokoro_voice.py`, imports (two pairs).** First SEARCH:
```python
import logging
import struct
```
REPLACE:
```python
import logging
import os
import struct
```
Second SEARCH:
```python
from probos.audio.tts.kokoro_backend import KOKORO_VOICES, kokoro_speed
```
REPLACE:
```python
from probos.audio.tts.kokoro_backend import KOKORO_VOICES, kokoro_speed
from probos.audio.tts.piper_backend import resolve_executable_path
```

**P4: `test_b1`'s expectation, updated with the reason inline (not deleted).** SEARCH:
```python
    assert key == KokoroWorkerKey(
        python=str(Path(sys.executable).resolve()),
```
REPLACE:
```python
    assert key == KokoroWorkerKey(
        # A3 (F-CI-1): the interpreter is absolute but NOT resolved. Resolving a POSIX venv's
        # bin/python symlink starts the base interpreter, which cannot import the venv's packages.
        # The script, model and voices paths are data files and stay resolved.
        python=os.path.abspath(sys.executable),
```

**P5: new tests after `test_b8`.** SEARCH:
```python
    assert "a tts.kokoro path cannot be resolved (OSError" in caplog.text
    assert caplog.text.count("result=degraded") == 4


# --- config, registry, selection --------------------------------------------------------------
```
REPLACE:
```python
    assert "a tts.kokoro path cannot be resolved (OSError" in caplog.text
    assert caplog.text.count("result=degraded") == 4


def test_b9_the_interpreter_path_is_not_followed_through_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A3 (F-CI-1): a POSIX venv's bin/python links to the base interpreter, which finds no
    # pyvenv.cfg beside itself. The link is simulated through os.path.realpath (which
    # Path.resolve calls), so this case fails on a resolving helper on every platform.
    link = tmp_path / "venv" / "bin" / "python"
    link.parent.mkdir(parents=True)
    link.write_bytes(b"")
    target = tmp_path / "base" / "python"
    target.parent.mkdir()
    target.write_bytes(b"")
    real = os.path.realpath

    def _follows_the_link(path, *args, **kwargs):
        return str(target) if os.fspath(path) == str(link) else real(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", _follows_the_link)

    assert resolve_executable_path(str(link)) == link
    assert resolve_executable_path(str(tmp_path / "venv" / "bin" / "absent")) is None
    with pytest.raises(ValueError):
        resolve_executable_path("tools/kokoro/a\x00b")


@pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs privilege on Windows; test_b9 simulates one")
def test_b10_a_real_venv_interpreter_symlink_is_returned_unfollowed(tmp_path: Path) -> None:
    link = tmp_path / "venv" / "bin" / "python"
    link.parent.mkdir(parents=True)
    link.symlink_to(sys.executable)

    assert resolve_executable_path(str(link)) == link


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="a drive-relative path (C:python.exe) exists only on Windows")
async def test_b11_a_drive_relative_interpreter_path_is_refused_never_joined_to_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A3, round five: Path("C:python.exe") is not absolute, and joining it to the install root would
    # drop the root and leave the launch to that drive's current directory.
    for configured in ("C:python.exe", "C:"):
        with pytest.raises(ValueError):
            resolve_executable_path(configured)

    svc = _RecordingService()
    cfg = _installed(tmp_path, monkeypatch, python_path="C:python.exe")

    assert await KokoroBackend(cfg, service=svc).synthesize("Hi.") is None
    assert svc.calls == []


# --- config, registry, selection --------------------------------------------------------------
```

**Focused check** (local, Windows, `-n 0`): `tests/test_ad738g_kokoro_voice.py`, `tests/test_ad738f_per_agent_voices.py`, `tests/test_ad1025_path_anchoring.py`, `tests/test_ad1025b_path_anchoring.py`, `tests/test_ad738_piper_tts.py`, `tests/test_bf918_tts_latency.py`. The path-anchoring and Piper files prove Piper did not move. The orchestrator's run on the final candidate: 133 passed, 1 skipped (B10, by design on Windows), 14.4 s; with the ledger, standing-orders and AD-1152 test files added: 240 passed, 1 skipped.

#### 16.13.3 Mutation rows (A3 campaign, on Windows, one at a time on the frozen A3 candidate, file restored byte for byte; record each file's sha256)

| Row | Mutant | Discriminating test | Expected on the mutant | Observed |
|---|---|---|---|---|
| MA3-1 | `resolve_executable_path`'s body after the docstring replaced by `return _resolve_binary_path(configured)` | B9; B1 and B10 on POSIX | B9 fails on every platform (the simulated link is followed); B1 also fails on POSIX, and B10 fails there too (it skips on Windows). On Windows B1 cannot discriminate: `Path(sys.executable).resolve()` equals `os.path.abspath(sys.executable)` because the venv's `python.exe` is not a link | **Killed.** `2 failed, 32 passed, 1 skipped`: B9 (the helper returned the simulated link's target, `.../base/python`, instead of the link) and B11 (`_resolve_binary_path("C:python.exe")` does not raise, so the old resolver fails the Windows boundary test too). B1 passes on Windows, as expected; B10 skips. `piper_backend.py` restored byte for byte (sha256 `4a2d1312b09ee4e44e8c9169509ff8155e6ff4a444298f09223d8b3f9017e28b` before and after). |
| MA3-2 | the NUL guard (`if "\x00" in configured: raise ...`) removed | B9's `pytest.raises` | B9 fails on every platform: `ntpath.abspath` swallows the NUL and `Path.is_file()` returns `False` for it, so the helper returns `None` instead of raising. C4 (inside `test_b8`) still counts 3, because a NUL `python_path` degrades either way, which is why B9 carries this check | **Killed.** `1 failed, 33 passed, 1 skipped`: B9 only, `Failed: DID NOT RAISE <class 'ValueError'>` at its `pytest.raises` line; C4 (`test_b8`) passes. `piper_backend.py` restored byte for byte (same sha256 as MA3-1); the test file was never mutated (sha256 `c25f1f046dad2bc85e4c1f8aa3025b0d7f9798ca8be4dc9373f6f60cacef1bc5`). |
| MA3-3 | the drive guard (`if candidate.drive: raise ValueError(...)`) removed (round five) | B11 | B11 fails on Windows: without the guard `C:python.exe` is joined to the root, which keeps drive C and drops the root, so the helper returns `None` (or a path found through drive C's current directory) instead of raising | **Killed.** `1 failed, 33 passed, 1 skipped`: B11 only, `Failed: DID NOT RAISE <class 'ValueError'>` at its first `pytest.raises` line. `piper_backend.py` restored byte for byte (same sha256 as MA3-1). |

All three rows were run on the frozen final candidate (after the round-five repair).

K1 to K36 and KA1, KA2 do not touch the helper or `test_b1`'s expectation; none is rerun.

#### 16.13.4 Tests

32 to 35 Python tests (B9, B10, B11); B10 skips on Windows (it needs a real symlink), B11 skips off Windows (a drive-relative path exists only there); UI tests stay at 3. B9 is the platform-independent discriminator for the symlink; B10 and the four T tests in CI are the POSIX evidence; B11 is the Windows boundary test.

#### 16.13.5 Section 9 after A3

| # | Property | Tested by |
|---|---|---|
| 13 (new) | The interpreter path handed to `KokoroWorkerKey.python` is anchored and absolute but never symlink-resolved; the script, model and voices paths may be. `resolve_executable_path` raises `ValueError` on a NUL on every platform and, on Windows, on a drive-relative path (`C:python.exe`); C4's counts in `test_b8` (3, then 4) are unchanged. | B1 (POSIX), B9 (every platform), B10 (POSIX), B11 (Windows), MA3-1, MA3-2, MA3-3; end to end: the four T tests in CI on Linux |

Round five (the Diff Reviewer's delta pass) also checks: Piper's `_anchor_path` and `_resolve_binary_path` are byte-identical to the base, and `test_b1` was updated with its reason, not deleted. The consumers: `kokoro_backend._speak` (`kokoro_backend.py:141-161`) and C4.

#### 16.13.6 Considered and deferred

- **Piper's `_resolve_binary_path` also resolves** (`piper_backend.py:49`). Out of scope: a native binary does not depend on the path it was started from.
- **A drive-relative `model_path` or `voices_path`** (found by the round-five review): both go through `anchor_install_path` and `_anchor_path`, which share the drive-relative dependence on the working directory (`C:model.onnx`). They are data files, not an executable, and the config accepts them as it accepted `python_path`. One follow-up line in #1869: refuse a drive-relative path in `KokoroTTSConfig` at parse time, for all three path fields, on Windows.
- **A POSIX installer and a platform-aware `python_path` default** (the default `tools/kokoro/venv/Scripts/python`, `experience.py:648`, does not exist on POSIX and degrades with "not installed"): one follow-up line in #1869, not part of this work. The lesson goes there as a K-item too: the Windows-only gate cannot see symlink semantics, so a contract that launches an interpreter carries a test that simulates the link on every platform.

#### 16.13.7 Verified Against Codebase (A3, 2026-11-27, tree `88676ab1`, before the repair)

```text
git log --oneline -1                                                       88676ab1 (HEAD)
grep -n "^import logging|^import sys" src/probos/audio/tts/piper_backend.py   18, 19 (P1 SEARCH; no "import os")
grep -n "return candidate.resolve()" src/probos/audio/tts/piper_backend.py    49
grep -n "def resolve_executable_path" src/probos/audio/tts/piper_backend.py   69 (body: return _resolve_binary_path(configured), 74)
grep -n "resolve_executable_path" src/probos/audio/tts/kokoro_backend.py      26 (import), 142 (only call)
grep -n "missing.insert(0, str(anchor_install_path(cfg.python_path)))" src/probos/audio/tts/kokoro_backend.py   148
grep -n "import numpy as np" tests/fixtures/fake_kokoro_worker.py             20
grep -n "^import logging|^import struct" tests/test_ad738g_kokoro_voice.py    15, 16
grep -n "from probos.audio.tts.kokoro_backend import" tests/test_ad738g_kokoro_voice.py   28
grep -n "python=sys.executable" tests/test_ad738g_kokoro_voice.py             70 (_real_key, unresolved)
grep -n "def test_r5_|def test_r6_" tests/test_ad738g_kokoro_voice.py         368, 388 (each asserts a 24 kHz WAV)
grep -n "def test_b1_" tests/test_ad738g_kokoro_voice.py                      419; resolved expectation at 433
grep -n "def test_b8_" tests/test_ad738g_kokoro_voice.py                      552; counts 3 at 565, 4 at 574 (P5 SEARCH = 573-577)
grep -n "def test_t1_" tests/test_ad738g_kokoro_voice.py                      681
```
Absence Verified (A3):
```text
CLAIM: no other file under src/probos/audio resolves an interpreter path
RUN:   Grep "\.resolve\(" src/probos/audio
FOUND: piper_backend.py:34 (docstring), :38 (_probos_root), :49 (_resolve_binary_path)   HOLDS: yes
CLAIM: the repair is not yet in this clone (A3 documents the pairs as applied elsewhere)
RUN:   Grep "F-CI-1" src tests (*.py)
FOUND: nothing                                                                            HOLDS: yes
```

#### 16.13.8 Prior art

Repair round; no new design. The `site` documentation says Python looks for `pyvenv.cfg` beside, or one directory above, `sys.executable`, which is the path the interpreter was started as. The runner probe measured that a start through the link's target does not find the venv. No external search was run.
