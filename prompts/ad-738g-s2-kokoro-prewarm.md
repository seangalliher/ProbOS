# AD-738g S2 (#1662): warm the resident Kokoro worker once, in the background, after boot

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-28
**Amended by:** the orchestrator, 2026-11-28, after the dry build (8.1): the `_installed` helper in 7.1 merges `update` over its defaults, so `test_p3` can override `python_path`. As drafted the helper passed `python_path` twice and P3 failed at 18 passed, 1 failed. The expected `-k default_off` count in 8.2 is corrected from 2 to 3: the second test is parametrised over two platforms. Amended again 2026-11-28 after E1 to E3 (12.2): 12.3 step 3's memory command now also shows ParentProcessId and Name, with a note to read the worker's row, because the command lists two processes, the venv launcher (about 5 MB) and its child, the worker. In 8.3, F5 is killed by P7, P8, P10 and P11; P9 calls prewarm() directly and cannot see it. Amended a third time 2026-11-28 after review round 1 (finding F1: a task-only task that had already ended was never cleared at shutdown): the early-return guard of `_stop_held_start_service` gains `task_only` (P3.5), test P14 pins it (two cases, 21 collected items), mutation row S3 is added, and 8.1's pair total is corrected (its own list sums to 18 with P3.5; it said 19). F2 and F3 are text fixes: the ASCII rule now names its exceptions (the generator's dash, the quoted DECISIONS anchor), two arrows are words, and the warm-up sentence is 61 characters.
**Status:** ready to build once the orchestrator's oracle and dry build (8.1) pass on the final base. **Owning issue:** #1662. It stays open: S4, S5 and the Captain's live acceptance remain. Commit bodies end `Refs #1662.`. No subject carries an `AD-` or `BF-` token or the words close, fix or resolve, and the PR text has no closing keyword.
**Base:** stacked on `fb0dc4850897d435df17d53c805943b940bb2c8e` (tree `a63b3690b48b248c76ddc37c03abde248748b09b`): S1, AD-738f and S3a. Main does not have S1 yet. S3a is in review and a repair may move its code. Every pair below anchors on lines S3a did not write, except where 6.1 and 6.5 name the S3a lines they rely on. S2 may share one broad gate with S3a as a batch if S3a's gate has not run yet; otherwise it gets its own.
**Number:** a slice of AD-738g, the issue's own number, as S1 and S3a were. No new AD or BF number is allocated.
**Design base:** the Architect decision of 2026-11-28 01:02 (`s2-options-decision.md`): option A, one real sentence after boot, `tts.kokoro.prewarm: bool = True`, the hook in `startup/finalize.py`, the stored task, the shutdown cancel table, the failure behaviour, the tests and measurements. This contract changes that note in three places, and decision 2, 5 and 6 give the reasons: no `_worker_key()` extraction; `_stop_held_start_service` accepts a missing service; the warm-up line has reply length.
**The Captain's direction (2026-11-28 UTC):** S3 first, then S2. CPU only, because the GPU stays with Ollama. The GPL stays in the worker process. Nothing may change a default he is not already using: `tts.backend` stays `browser`, and the new switch acts only when `tts.backend == "kokoro"`.
**Line endings:** the working copies are CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. New authored text is ASCII; a quotation of a generated row or of an existing anchor keeps its characters (the generator's dash in `config-reference.md`, the em dash of the DECISIONS heading).
**Estimated tests:** one new file with 14 test functions, 21 collected items (P10 is parametrised over 7 cases, P14 over 2). Three existing tests are updated in place, each with its reason inline: two default-dump pins and one facade count. The fake worker fixture gains three test texts. Nothing is removed. No UI change.

## 1. Problem (premise table)

| Where (this tree) | What it does today | Effect |
|---|---|---|
| `audio/tts/resident.py`:295-296 | `_request` starts the process only when a request finds none alive (`if not self.alive: self._spawn()`) | the worker starts on the first reply |
| `scripts/kokoro_worker.py`:177 | after the model loads, the worker logs `kokoro worker ready` and does no warm-up synthesis | the first request also pays the first-call cost |
| `prompts/ad-738g-s1-local-kokoro-voice.md`:19 (S1's measurement) | the 3.2 s cold start splits into 0.72 s of model load and 2.43 s for the first call | starting the process alone would save about 0.7 s; the warm-up has to send a real request |
| `audio/tts/kokoro_backend.py`:136-175 | `_speak` is the only code that builds the `KokoroWorkerKey` (:165-172) and calls the service (:173) | a warm-up that does not go through `_speak` could build a different key and start a second worker |
| `audio/tts/resident.py`:572-573, :55 | a per-key `asyncio.Lock`; at most `VOICE_MAX_IN_FLIGHT` = 16 requests admitted | a reply that arrives during the warm-up waits for it, which is never worse than a cold start |
| `routers/avatars.py`:288-290 | the TTS route calls `dream_scheduler.record_speech_activity()` for each reply | a warm-up that went through the route would hold off the idle dream for a line nobody heard |
| `startup/shutdown.py`:429-499, :1582-1595 | `_stop_held_start_service` cancels and awaits a pending start task. The BF-881 table drives it, and every row names a service | the table cannot hold a task that has no service |
| `startup/shutdown.py`:1660-1661 | `_close_voice_synthesis(runtime)` kills every resident worker and shuts the executor down | a warm-up still running at that point would be cut off without its task being cancelled or awaited |
| `config_models/experience.py`:639-708, :839 | `KokoroTTSConfig` has no switch; the default `tts.backend` is `browser` | there is no way to turn a warm-up off, and a switch that defaults on does nothing on the default backend |

## 2. Solution

S2 is one slice in two commits.

- **Backend.** `KokoroBackend.prewarm(*, delay_seconds=0.0) -> bool` waits `delay_seconds`, then calls `self._speak(PREWARM_TEXT, self._config.voice, 1.0)` and throws the audio away.
  - `_speak` is the existing path every reply takes: install check, key, `synthesize_outcome`. So the warm-up and the replies share one key by construction.
  - It returns True when the worker answered with audio.
  - It logs one INFO line, `AD-738g S2: kokoro prewarm result=ok|degraded ms=N`.
  - It never raises, except to pass on a cancellation.
  - It does not log the per-sentence `AD-738g: kokoro voice=...` line, because the warm-up is not a reply.
- **Trigger.** `startup/finalize.py` gains `_start_voice_prewarm(*, runtime, config, delay_seconds=None)`, a plain function, so startup cannot await it.
  - It acts only when `tts.enabled`, `tts.backend == "kokoro"`, `tts.kokoro.prewarm` and `runtime.voice_synthesis` is a real `VoiceSynthesisService`.
  - It stores `runtime.voice_prewarm_task = asyncio.create_task(backend.prewarm(delay_seconds=PREWARM_DELAY_SECONDS), name="ad738g-s2-kokoro-prewarm")`.
  - `finalize_startup` calls it once, just before `runtime._started = True`.
- **Shutdown.** The BF-881 table gains the row `(None, "voice_prewarm_task", "AD-738g S2 Kokoro prewarm")`. `_stop_held_start_service` accepts `service_attr=None`, so the row cancels and awaits the task, or only clears the attribute when the task has already ended. This happens before `_close_voice_synthesis`, in a rollback too.
- **Config.** `KokoroTTSConfig.prewarm: bool = True`, defaulted on, with the reason in its docstring: it acts only on a vessel already set to `kokoro`. Every pinned or generated file moves in the same commit (6.6, 6.7).
- **Tests.** One new file runs the real worker loop with the fake engine as a real subprocess under the real service. The fake engine gains three texts: `CRASH` exits, `SLOW` takes 0.5 s and `HANG` sleeps 60 s.

Rejected, one line each:
- **Spawn only (`_claim` and `_spawn` without a request).** It saves about 0.7 s of the 3.2 s (S1's split) and needs private service API.
- **A `_worker_key()` helper moved out of `_speak`** (the decision note). The prewarm calls `_speak`, so the key code is already shared. Moving it would edit S3a's lines :165-175 for no gain (decision 2).
- **A client `POST /tts/warm`** (option B). It adds a route, its auth and a `voice.ts` change, and page load may come too late to hide the 3.2 s. It stays the follow-up if the memory held in sessions without voice turns out to matter.
- **Warm on the first chat message** (option C). That code is the chat path, which BF-932 owns.
- **A dedicated shutdown helper** for the task. It would duplicate `_stop_held_start_service`'s outer-cancellation logic (BF-303 and BF-881). One `None` guard reuses it (decision 5).
- **A config field for the delay or the line.** No measured need yet. Both are module constants.
- **One warm-up per language** (`en-us` and `en-gb`). Whether the second language has its own first-call cost is unmeasured. E3 measures it (section 12), and the change is "considered, deferred".

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| 1 | Option A: one real request, in the background, about 5 s after boot | The decision note's ranking. It touches no route, no HXI file and nothing of BF-932's. It adds no steady-state memory, because with no idle eviction the worker stays for the whole session after the first reply anyway. One switch reverses it, and the fake worker can test it. |
| 2 | `prewarm` calls `_speak`; nothing is moved out of it | `_speak` (`kokoro_backend.py`:136-175) holds the only key-building code and the only service call. Calling it gives the same guarantee the note's `_worker_key()` was meant to give, and S3a's lines :165-175 stay as they are. P2 pins key equality and P1 pins one process. |
| 3 | The ship's voice (`cfg.voice`) at speed 1.0 | The voice and speed travel on the request line and are not part of `KokoroWorkerKey` (`resident.py`:181-186). One warm-up therefore serves all 28 voices and every role in the same language. Speed 1.0 is inside the engine's range whatever `cfg.speed` is. |
| 4 | Not through the route | The route records speech activity for the dream scheduler (`avatars.py`:288-290) and stores the audio as an attachment. The warm-up does neither. The service deletes the WAV, and S3a's timing file, as it does for every request (`resident.py`:336-344). P1 checks that the worker's directory holds only `stderr.log` afterwards, and P7 and P11 check that the dream scheduler saw nothing. |
| 5 | `_stop_held_start_service(service_attr=None)` cancels a task that has no service | The table's loop already does the hard part. It cancels a pending start task first, swallows only that task's own `CancelledError`, re-raises an outer cancellation (BF-303 Ctrl+C), logs any other failure and clears the attribute. Four places change: the parameter type, the `getattr`, the early-return guard (a task-only row reaches the `finally` when its task has ended, so the attribute is cleared) and the guard on the `setattr`. Every existing caller passes a string and is unchanged. |
| 6 | `PREWARM_TEXT` is one ordinary reply-length sentence (61 characters), not a word | ONNX Runtime's CPU arena grows to the largest input it has seen (onnxruntime #11627, section 15). A sentence of reply length warms the buffers a reply needs, where one word might leave the first reply paying part of the cost again. E1 measures it. |
| 7 | The delay is the module constant `PREWARM_DELAY_SECONDS = 5.0` | Its only job is to keep the warm-up's CPU out of the rest of the start, and there is no measured need to tune it. The `delay_seconds` argument exists for tests and is not config. |
| 8 | The switch defaults on | It acts only when `tts.backend` is already `kokoro`, and the default is `browser` (`experience.py`:839), so no default the Captain is not using changes. On a vessel already on Kokoro the only change is that the load happens at boot, and is also paid in a session that never speaks. `tts.kokoro.prewarm: false` restores S1's behaviour exactly. |
| 9 | Failure leaves the service exactly as a failed reply would | Not installed: `_speak`'s existing WARNING, then the S2 INFO line with `degraded`, and nothing starts. A crash or a timeout makes `synthesize_outcome` retire the worker (`resident.py`:622-629), and the next reply starts it cold, as today. Cancellation is passed on. Anything else is logged with its traceback and ends in `degraded`. |
| 10 | The task is a census event, registered so that no census moves | It is stored on `runtime` (the AD-477 pattern, `finalize.py`:6339-6359), named, never awaited at startup, and cancelled and awaited by the shutdown table. It starts no subprocess of its own (the existing `PiperWorker._spawn` row of the AD-1346 effect census covers the launch), writes no file and opens no connection. The default config creates no task at all, so the runtime-lifecycle leak checks (`tests/fixtures/runtime_lifecycle.py`:111-116) see nothing new. |

## 4. Milestones and commits

Each milestone is one commit, built and focused-tested before the next (8.2). Stage explicit paths only, never `git add -A`. Run `git diff --cached --stat` before each commit, and stop on any unexpected file with more than 200 deletions.

| M | Sections | Commit subject |
|---|---|---|
| M1 | 6.1 to 6.6, new file 7.1, regenerations 6.7 | `Speech: warm the resident Kokoro worker once in the background after boot, on by default and only when the backend is kokoro` |
| M2 | 6.8, `gen_ad_ledger.py` (6.7) | `Speech: record the boot warm-up of the Kokoro worker in the progress log and the decisions` |

The new field and every file it moves belong to M1, all in one commit: `experience.py`, the three test pins, `config-reference.md` and `config-facade-baseline.yaml`. A commit holding only some of them fails the AD-1152 golden or the facade check.

## 5. Builder: may and may not

- **May:** create 7.1 with the content given; apply the pairs in order; run the focused lines of 8.2 and the commands of 6.7; run `git diff --check` and `git diff --stat`.
- **May not:**
  - edit an unnamed file;
  - edit `tests/test_bf930_voice_path_timing.py`, `tests/test_bf918_tts_latency.py`, `tests/test_issue1452_stop_leftovers.py`, the AD-1346 census fixtures or `tests/test_bf892_spawn_env_guard.py`;
  - add `skip`, `xfail` or a retry, or add a wall-clock assertion;
  - install or download anything;
  - run the measurements of section 12, which the orchestrator runs with no gate running;
  - reword an anchor.
- **Stop and report** if a SEARCH does not match exactly once, if a regenerated file differs from 6.7's expected diff, or if a census count moves.

## 6. The pairs

### 6.1 `src/probos/audio/tts/kokoro_backend.py` (M1)

S2 relies on two S3a lines here. `_speak` returns `PiperOutcome | None` (`:136`) and calls `self._service.synthesize_outcome` (`:173`); `prewarm` reads `outcome.audio`. If an S3a repair changed `_speak` back to returning `bytes | None`, P1.3 would change its `ok` line to `ok = outcome is not None` and the stand-ins of 7.1 would change with it. The orchestrator's dry build would catch that. None of the three SEARCH blocks below touches an S3a line.

**P1.1** SEARCH:
```python
import logging
import time
```
REPLACE:
```python
import asyncio
import logging
import time
```

**P1.2** SEARCH:
```python
#: kokoro-onnx raises ``ValueError`` for a speed outside this range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0
```
REPLACE:
```python
#: kokoro-onnx raises ``ValueError`` for a speed outside this range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0
#: AD-738g S2 (#1662): the line the boot warm-up speaks and discards. It is one ordinary reply-length
#: sentence, so the worker's first request (its model graph, and buffers sized for a sentence) is
#: paid before the first reply. ASCII, no name, nothing the Captain would mind in a log.
PREWARM_TEXT = "Voice systems are online, and the crew is ready when you are."
#: AD-738g S2: how long after boot the warm-up starts (seconds), so its CPU does not compete with
#: the rest of the start. A module constant, not config: there is no measured need to tune it.
PREWARM_DELAY_SECONDS = 5.0
```

**P1.3** SEARCH:
```python
        return self._config.voice

    async def synthesize(
```
REPLACE:
```python
        return self._config.voice

    async def prewarm(self, *, delay_seconds: float = 0.0) -> bool:
        """AD-738g S2 (#1662): start the resident worker and speak ``PREWARM_TEXT`` once; the audio is discarded.

        The worker loads its model when it starts, and its first request pays a further first-call
        cost (S1 measured 0.72 s and 2.43 s of the 3.2 s cold start), so a process start alone would
        save little. This sends one real request through ``_speak``, the only place the worker key is
        built, so the first reply finds the same worker warm. No route is involved: the warm-up is not
        speech activity for the dream scheduler and stores no attachment, and the service deletes the
        WAV (and its timing file) as it does for every request. The ship's voice is used; the voice
        travels on the request line and is not part of the key, so one warm-up serves every voice.

        Returns True when the worker answered with audio. Never raises but a cancellation (shutdown
        cancels the task): any failure leaves the service as a failed reply leaves it, and the next
        reply starts the worker cold, as before S2. One INFO line reports the result.
        """
        started = time.perf_counter()
        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            started = time.perf_counter()
            outcome = await self._speak(PREWARM_TEXT, self._config.voice, 1.0)
        except asyncio.CancelledError:
            logger.info("AD-738g S2: kokoro prewarm cancelled")
            raise
        except Exception:  # _speak never raises; this keeps a later defect below it inside the task
            logger.warning("AD-738g S2: kokoro prewarm failed; the first reply starts the worker", exc_info=True)
            outcome = None
        ok = outcome is not None and outcome.audio is not None
        logger.info(
            "AD-738g S2: kokoro prewarm result=%s ms=%.0f",
            "ok" if ok else "degraded", (time.perf_counter() - started) * 1000,
        )
        return ok

    async def synthesize(
```

### 6.2 `src/probos/startup/finalize.py` (M1)

**P2.1** The helper goes after `_start_transcript_reaper`. SEARCH:
```python
            "transcripts will not be reaped this run",
            exc_info=True,
        )


async def _start_working_memory_cognition(*, runtime: Any, config: "SystemConfig") -> None:
```
REPLACE:
```python
            "transcripts will not be reaped this run",
            exc_info=True,
        )


def _start_voice_prewarm(*, runtime: Any, config: "SystemConfig", delay_seconds: float | None = None) -> None:
    """AD-738g S2 (#1662): warm the resident Kokoro worker in the background, after boot.

    Only when speech is on, ``tts.backend`` is ``kokoro`` and ``tts.kokoro.prewarm`` is set, and only
    with the runtime's own voice synthesis service; otherwise nothing starts. The task is stored on
    ``runtime.voice_prewarm_task`` and never awaited here (a plain function, so startup cannot wait on
    it); shutdown cancels and awaits it before the voice service closes (``startup/shutdown.py``). It
    waits ``PREWARM_DELAY_SECONDS`` first; ``delay_seconds`` overrides that for tests.
    """
    runtime.voice_prewarm_task = None
    tts = getattr(config, "tts", None)
    if tts is None or tts.enabled is not True or tts.backend != "kokoro":
        return
    if tts.kokoro.prewarm is not True:
        logger.info("AD-738g S2: tts.kokoro.prewarm is off; the first reply starts the kokoro worker")
        return
    from probos.audio.tts.kokoro_backend import PREWARM_DELAY_SECONDS, KokoroBackend
    from probos.audio.tts.resident import VoiceSynthesisService

    service = getattr(runtime, "voice_synthesis", None)
    if not isinstance(service, VoiceSynthesisService):
        logger.info("AD-738g S2: no voice synthesis service on this runtime; no kokoro prewarm")
        return
    delay = PREWARM_DELAY_SECONDS if delay_seconds is None else delay_seconds
    backend = KokoroBackend(tts.kokoro, service=service)
    runtime.voice_prewarm_task = asyncio.create_task(
        backend.prewarm(delay_seconds=delay), name="ad738g-s2-kokoro-prewarm",
    )
    logger.info("AD-738g S2: kokoro prewarm scheduled in %.0f s", delay)


async def _start_working_memory_cognition(*, runtime: Any, config: "SystemConfig") -> None:
```

**P2.2** The call. SEARCH:
```python
    # BF-779: name the consensus intents that have no commit gate, now that
    # every template is registered.
    runtime.log_consensus_gap_register()

    runtime._started = True
```
REPLACE:
```python
    # BF-779: name the consensus intents that have no commit gate, now that
    # every template is registered.
    runtime.log_consensus_gap_register()

    # AD-738g S2 (#1662): warm the Kokoro worker in the background; never awaited here.
    _start_voice_prewarm(runtime=runtime, config=config)

    runtime._started = True
```

`asyncio` is already imported (`finalize.py`:10); `"SystemConfig"` is a `TYPE_CHECKING` import (`:33`). The imports inside the function follow the file's own pattern (`:815`, `:6344`).

### 6.3 `src/probos/startup/shutdown.py` (M1)

**P3.1** SEARCH:
```python
    *,
    service_attr: str,
    start_task_attr: str | None,
```
REPLACE:
```python
    *,
    service_attr: str | None,
    start_task_attr: str | None,
```

**P3.2** SEARCH:
```python
    service = getattr(runtime, service_attr, None)
    start_task = getattr(runtime, start_task_attr, None) if start_task_attr else None
```
REPLACE:
```python
    # AD-738g S2 (#1662): no service_attr for a task that has no service (the Kokoro warm-up).
    service = getattr(runtime, service_attr, None) if service_attr else None
    start_task = getattr(runtime, start_task_attr, None) if start_task_attr else None
```

**P3.3** SEARCH:
```python
        if service is not None:
            setattr(runtime, service_attr, None)
```
REPLACE:
```python
        if service is not None and service_attr:
            setattr(runtime, service_attr, None)
```

**P3.4** SEARCH:
```python
        ("plan_of_day_service", "plan_of_day_start_task",
         "AD-477 PlanOfDayService"),
    ):
```
REPLACE:
```python
        ("plan_of_day_service", "plan_of_day_start_task",
         "AD-477 PlanOfDayService"),
        # AD-738g S2 (#1662): the Kokoro warm-up has no service to stop. Its task is cancelled and
        # awaited here, before _close_voice_synthesis below stops the worker it may be talking to.
        (None, "voice_prewarm_task", "AD-738g S2 Kokoro prewarm"),
    ):
```

**P3.5** SEARCH:
```python
    if not (start_pending or stop_awaitable):
        return
```
REPLACE:
```python
    # AD-738g S2 (#1662): a task-only row (no service) reaches the finally even when its task has
    # ended, so the attribute is cleared; there is nothing to cancel, await or stop.
    task_only = service_attr is None and start_task is not None
    if not (start_pending or stop_awaitable or task_only):
        return
```

The table runs unconditionally in `shutdown()` (`:1582`, function body level), so a startup rollback cancels the task too. It runs before `_close_voice_synthesis` (`:1661`).

### 6.4 `src/probos/config_models/experience.py` (M1)

**P4.1** SEARCH:
```python
    role matches no crew member and changes nothing; each sentence's log line shows its
    ``voice=`` and ``role=``."""

    @field_validator("python_path", "model_path", "voices_path")
```
REPLACE:
```python
    role matches no crew member and changes nothing; each sentence's log line shows its
    ``voice=`` and ``role=``."""

    prewarm: bool = True
    """AD-738g S2 (#1662): about 5 s after boot, start the worker and speak one line to it in the
    background, discarding the audio, so the first reply does not pay the cold start (about 3.2 s,
    measured in S1). It acts only when ``tts.enabled`` is true and ``tts.backend`` is ``kokoro``
    (the default backend is ``browser``). The cost: the worker's memory is held from boot, also in a
    session that never speaks. ``false`` starts the worker on the first reply, as before."""

    @field_validator("python_path", "model_path", "voices_path")
```

The field is last, so every default dump gains `"prewarm": True` after `agent_voices`. That is why 6.6 edits the two dump pins at their last line.

### 6.5 `tests/fixtures/fake_kokoro_worker.py` (M1)

S3a replaced this file whole; the two anchors below are in it on this tree.

**P5.1** SEARCH:
```python
import os
import sys
```
REPLACE:
```python
import os
import sys
import time
```

**P5.2** SEARCH:
```python
        if text == "CHATTER":
            print("library chatter on stdout")
```
REPLACE:
```python
        if text == "CHATTER":
            print("library chatter on stdout")
        # AD-738g S2: CRASH ends the process mid-request; SLOW takes half a second; HANG outlasts any test's timeout.
        if text == "CRASH":
            raise SystemExit(3)
        if text == "SLOW":
            time.sleep(0.5)
        if text == "HANG":
            time.sleep(60.0)
```

All three texts are checked after the call is recorded, so a test can wait for the record line. `SystemExit` passes through the worker's `except Exception` handlers (`scripts/kokoro_worker.py`:160, :217) and ends the process. No existing test sends these three texts: Absence Verified, section 17.

### 6.6 Test edits (M1)

**a** `tests/test_ad1152_agentic_correlation.py`. The golden pops the Kokoro section and asserts its defaults dict, so the dict gains the field. `default_config_sha256` hashes the dump after the pop (`:566`), so the digest does not move. SEARCH:
```python
        "voices_path": "tools/kokoro/voices-v1.0.bin", "voice": "af_heart", "speed": 1.0, "threads": 4,
        "timeout_seconds": 30.0, "agent_voices": {},
    }
```
REPLACE:
```python
        "voices_path": "tools/kokoro/voices-v1.0.bin", "voice": "af_heart", "speed": 1.0, "threads": 4,
        # AD-738g S2 adds the boot warm-up switch (default on); it too acts only when tts.backend is "kokoro".
        "timeout_seconds": 30.0, "agent_voices": {}, "prewarm": True,
    }
```

**b** `tests/test_ad1270e2c_experience_models.py`. SEARCH:
```python
                                   # AD-738f S1 (#1868): the Captain's per-role voices, empty by default.
                                   'agent_voices': {}}},
```
REPLACE:
```python
                                   # AD-738f S1 (#1868): the Captain's per-role voices, empty by default.
                                   'agent_voices': {},
                                   # AD-738g S2 (#1662): the boot warm-up, on by default, inert unless the backend is kokoro.
                                   'prewarm': True}},
```

**c** `tests/test_ad1270e1_config_facade.py`. SEARCH:
```python
    # BF-932 (#1670) adds system.loop_stall_warn_seconds (1886 -> 1887).
    assert counts["field_definitions"] == 1887  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # BF-932 (#1670) adds system.loop_stall_warn_seconds (1886 -> 1887).
    # AD-738g S2 (#1662) adds KokoroTTSConfig.prewarm (1887 -> 1888).
    assert counts["field_definitions"] == 1888  # AD-1206 intentionally adds github_repository.
```

These files need no edit:
- `tests/test_ad738g_kokoro_voice.py`: `test_c1` (`:640-651`) asserts named fields one by one and `TTSConfig().kokoro == KokoroTTSConfig()`, which holds with the new field. P13 pins the new default.
- The settings registry, `src/probos/settings/section_registry.py`: it exposes no Kokoro sub-field, only the `tts.backend` enum at `:275`, so `/api/config`'s registry has no row to add.
- `tests/fixtures/ad1152_agentic_off_golden.json`: its `base_source_blobs` list names `finalize.py` (`:9`), but nothing reads that list (Absence Verified).

### 6.7 Regenerations and cross-checks (from the worktree root, in this order)

**M1**, after 6.4 and 6.6:
```text
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
```
Expected:
- `git diff docs/development/config-reference.md` is one added row after `:2079` (the `agent_voices` row of `## tts.kokoro`): ``| `prewarm` | `bool` | `True` | — |  |``. Any other line is a stop.
- `git diff docs/development/config-facade-baseline.yaml` adds one row and changes six. The orchestrator's dry build confirms the values.
  - Added after `:2245`: `    - {default: 'True', name: prewarm}`.
  - Changed: `surface_counts.canonical_dump_leaves` (`:50`, 1892 to 1893) and `surface_counts.field_definitions` (`:51`, 1887 to 1888).
  - Changed: `canonical_dump_sha256` (`:56`).
  - Changed: the `schema_sha256` of `KokoroTTSConfig` (`:2236`), of `TTSConfig` (`:3643`, whose schema embeds the nested model) and of `SystemConfig` (`:3431`, which depends on every config model).
  - Nothing else moves: no other `default:` row, no `names` or `models` entry, no other count. Anything else is a stop. `SystemConfig`'s value also differs if main has taken another config change; the rule (these rows only) still holds.
- The facade `--check` prints `config facade check passed (names=311, owned=298, incidental=13, models=229, fields=1888, env rows=4)`. Without `--update-baseline` it fails, and so does `tests/test_ad1270e1_config_facade.py::test_check_is_green_on_the_committed_baseline` (`:1814`).
- The other two checks pass.

**M2**, after 6.8:
```text
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
```
Stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` only if the ledger tool changed them.

### 6.8 Trackers (M2)

**P8.1** `PROGRESS.md`. SEARCH:
```text
# ProbOS Progress

```
REPLACE:
```text
# ProbOS Progress

**AD-738g S2 (2026-11-28), #1662 -- the Kokoro worker is warmed at boot.** When `tts.backend` is `kokoro`, startup schedules one background request about 5 s after boot: the ship's voice speaks one reply-length line to the resident worker and the audio is discarded, so the first reply no longer pays the cold start (about 3.2 s in S1). The warm-up goes through the backend's own request path, so it shares the replies' worker. It is not speech activity for the dream scheduler and stores nothing. Shutdown cancels it before the voice service closes. Any failure leaves the service as a failed reply would. The new `tts.kokoro.prewarm` defaults on and does nothing on the default `browser` backend; `false` restores the start on the first reply. Contract `prompts/ad-738g-s2-kokoro-prewarm.md`.

```

**P8.2** `DECISIONS.md`. SEARCH (the `—` is in the file today):
```text
## Era V — Civilization (Phases 31-36)

```
REPLACE:
```text
## Era V — Civilization (Phases 31-36)

### AD-738g S2 -- the resident Kokoro worker is warmed once, in the background, after boot (2026-11-28, #1662)

- *Scope.* `audio/tts/kokoro_backend.py` (`prewarm`, `PREWARM_TEXT`, `PREWARM_DELAY_SECONDS`), `startup/finalize.py` (`_start_voice_prewarm`), `startup/shutdown.py` (the BF-881 table's row and `service_attr=None`), `config_models/experience.py` (`KokoroTTSConfig.prewarm`). Contract `prompts/ad-738g-s2-kokoro-prewarm.md`.
- *D1.* One real request, not a process start. S1's 3.2 s cold start is 0.72 s of model load and 2.43 s of first call, so a start alone saves little.
- *D2.* The warm-up calls the backend's own request path, the only place the worker key is built, so it can never start a second worker.
- *D3.* It does not go through the route: no speech activity for the dream scheduler, and no attachment.
- *D4.* The task is stored, never awaited at startup, and cancelled and awaited by the shutdown table before the voice service closes, rollback included.
- *D5.* `tts.kokoro.prewarm` defaults on because it acts only on a vessel already set to `kokoro`. The cost is the worker's memory from boot in a session that never speaks.
- *Reversal.* `tts.kokoro.prewarm: false`, or revert the two commits. No persisted format changes.

```

## 7. New files

### 7.1 `tests/test_ad738g_s2_kokoro_prewarm.py` (M1)

```python
"""AD-738g (#1662) S2: the resident Kokoro worker is warmed once, in the background, after boot.

The worker loop is the real ``scripts/kokoro_worker.py`` with the stand-in engine of
``tests/fixtures/fake_kokoro_worker.py``, run as a real ``python -I`` subprocess under the real
``VoiceSynthesisService``. The engine appends one JSON line per call (text, voice, speed, pid) to the
file the key names as its model. The texts ``CRASH``, ``HANG`` and ``SLOW`` make it exit, hang or take
half a second. The only clock read is the bound of ``_until``, which fails a hang, never a slow run.
Nothing here needs kokoro-onnx.

- P1  the warm-up is one real request; the first reply reuses its process; nothing is left behind
- P2  the warm-up and every reply use one worker key; the warm-up's text, voice, speed and timeout
- P3  without an install or a service: degraded, nothing starts
- P4  a failure below the backend never leaves the task
- P5  a worker that dies during the warm-up is retired; the first reply starts a new one
- P6  a warm-up that times out is killed; the first reply starts a new one
- P7  shutdown cancels a running warm-up; no worker process is left; no speech activity
- P8  the warm-up waits its delay; a shutdown during the delay starts nothing
- P9  a reply that arrives during the warm-up waits for it and shares its process
- P10 no warm-up unless speech is on, the backend is kokoro, the switch is on and the service is real
- P11 startup starts the warm-up and returns before the worker answers
- P12 finalize starts it, and shutdown cancels it before the voice service closes (the wiring)
- P13 the switch is on by default and can be turned off
- P14 shutdown clears a warm-up that has already ended, finished or cancelled
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.audio.tts import KokoroBackend, kokoro_backend
from probos.audio.tts.resident import PiperOutcome, VoiceSynthesisService
from probos.config import KokoroTTSConfig, TTSConfig
from probos.startup import finalize as finalize_module
from probos.startup import shutdown as shutdown_module

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
_TASK_ATTR = "voice_prewarm_task"
_LABEL = "AD-738g S2 Kokoro prewarm"


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **update: Any) -> tuple[KokoroTTSConfig, Path]:
    """A config naming the fake worker. Its "model" is the engine's record file."""
    record = tmp_path / "engine-calls.jsonl"
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    fields: dict[str, Any] = {"python_path": sys.executable, "model_path": str(record), "voices_path": str(voices)}
    cfg = KokoroTTSConfig(**{**fields, **update})
    return cfg, record


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


async def _until(predicate: Any, seconds: float = 20.0) -> None:
    """Wait for the fake worker; the bound fails a hang only."""
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "the fake worker did not get there"
        await asyncio.sleep(0.02)


def _prewarm_lines(caplog: pytest.LogCaptureFixture, result: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.getMessage().startswith(f"AD-738g S2: kokoro prewarm result={result} ")
    ]


class _DreamScheduler:
    def __init__(self) -> None:
        self.speech = 0

    def record_speech_activity(self, now: float | None = None) -> bool:
        self.speech += 1
        return True


def _runtime(tts: Any, service: Any) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(tts=tts), voice_synthesis=service, dream_scheduler=_DreamScheduler())


async def _stop_task(runtime: SimpleNamespace) -> None:
    await shutdown_module._stop_held_start_service(
        runtime, service_attr=None, start_task_attr=_TASK_ATTR, label=_LABEL,
    )


class _KeyService:
    """Records each request; answers with audio."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, float, dict]] = []

    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return PiperOutcome(b"RIFF", "ok")


class _RaisingService:
    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        raise RuntimeError("a defect below the backend")


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


# --- the backend's warm-up --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p1_the_warm_up_is_one_real_request_and_the_first_reply_reuses_its_process(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cfg, record = _installed(tmp_path, monkeypatch)
    backend = KokoroBackend(cfg, service=service)

    assert await backend.prewarm() is True

    (warm,) = _calls(record)
    assert (warm["text"], warm["voice"], warm["speed"]) == (kokoro_backend.PREWARM_TEXT, "af_heart", 1.0)
    assert service.resident_count == 1
    # Nothing is left behind: the service deleted the WAV, so the worker's directory holds only its stderr log.
    directory = next(iter(service._resident.values()))._dir
    assert directory is not None and sorted(p.name for p in directory.iterdir()) == ["stderr.log"]
    assert len(_prewarm_lines(caplog, "ok")) == 1
    # The warm-up is not a reply: it does not log the per-sentence line the Captain reads.
    assert not any(r.getMessage().startswith("AD-738g: kokoro voice=") for r in caplog.records)

    reply = await backend.synthesize("Hello.")

    assert reply is not None and reply.audio_bytes[:4] == b"RIFF"
    calls = _calls(record)
    assert [call["text"] for call in calls] == [kokoro_backend.PREWARM_TEXT, "Hello."]
    assert calls[0]["pid"] == calls[1]["pid"]
    assert service.resident_count == 1


@pytest.mark.asyncio
async def test_p2_the_warm_up_and_every_reply_use_one_worker_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, _record = _installed(tmp_path, monkeypatch, voice="af_bella", speed=1.5, timeout_seconds=12.0)
    recorder = _KeyService()
    backend = KokoroBackend(cfg, service=recorder)

    assert await backend.prewarm() is True
    await backend.synthesize("Hello.")
    await backend.synthesize("Hello.", agent_type="pathologist")

    (warm_key, warm_text, warm_timeout, warm_fields), *replies = recorder.calls
    assert [key for key, *_rest in replies] == [warm_key, warm_key]
    assert warm_text == kokoro_backend.PREWARM_TEXT
    assert warm_timeout == 12.0
    assert warm_fields == {"voice": "af_bella", "speed": 1.0}


@pytest.mark.asyncio
async def test_p3_without_an_install_or_a_service_the_warm_up_is_degraded_and_starts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cfg, _record = _installed(tmp_path, monkeypatch, python_path=str(tmp_path / "no-such-python"))
    recorder = _KeyService()

    assert await KokoroBackend(cfg, service=recorder).prewarm() is False
    assert await KokoroBackend(cfg, service=None).prewarm() is False

    assert recorder.calls == []
    assert len(_prewarm_lines(caplog, "degraded")) == 2


@pytest.mark.asyncio
async def test_p4_a_failure_below_the_backend_never_leaves_the_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cfg, _record = _installed(tmp_path, monkeypatch)

    assert await KokoroBackend(cfg, service=_RaisingService()).prewarm() is False

    failed = [r for r in caplog.records if r.levelno == logging.WARNING and "kokoro prewarm failed" in r.getMessage()]
    assert len(failed) == 1
    assert len(_prewarm_lines(caplog, "degraded")) == 1


@pytest.mark.asyncio
async def test_p5_a_worker_that_dies_during_the_warm_up_is_retired_and_the_first_reply_starts_a_new_one(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "CRASH")
    backend = KokoroBackend(cfg, service=service)

    assert await backend.prewarm() is False
    assert service.resident_count == 0

    reply = await backend.synthesize("Hello.")

    assert reply is not None
    calls = _calls(record)
    assert [call["text"] for call in calls] == ["CRASH", "Hello."]
    assert calls[0]["pid"] != calls[1]["pid"]
    assert service.resident_count == 1


@pytest.mark.asyncio
async def test_p6_a_warm_up_that_times_out_is_killed_and_the_first_reply_starts_a_new_worker(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch, timeout_seconds=1.0)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "HANG")

    assert await KokoroBackend(cfg, service=service).prewarm() is False
    assert service.resident_count == 0

    # The timeout is per request, not part of the key, so a 30 s reply uses the same key.
    reply = await KokoroBackend(cfg.model_copy(update={"timeout_seconds": 30.0}), service=service).synthesize("Hello.")

    assert reply is not None
    texts = [call["text"] for call in _calls(record)]
    # A loaded machine may time the warm-up out before the worker read its line, so HANG may be absent.
    assert texts[-1] == "Hello." and set(texts[:-1]) <= {"HANG"}
    assert service.resident_count == 1


# --- startup and shutdown ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p7_shutdown_cancels_a_running_warm_up_and_no_worker_process_is_left(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "HANG")
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)
    task = rt.voice_prewarm_task
    await _until(lambda: bool(_calls(record)))
    proc = next(iter(service._resident.values()))._proc
    assert proc is not None and proc.poll() is None

    await _stop_task(rt)
    shutdown_module._close_voice_synthesis(rt)

    assert task.cancelled() and rt.voice_prewarm_task is None
    assert proc.wait(timeout=10) is not None
    assert service.closed and service.resident_count == 0
    assert rt.dream_scheduler.speech == 0


@pytest.mark.asyncio
async def test_p8_the_warm_up_waits_its_delay_and_a_shutdown_during_the_delay_starts_nothing(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert kokoro_backend.PREWARM_DELAY_SECONDS == 5.0
    cfg, record = _installed(tmp_path, monkeypatch)
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config)
    task = rt.voice_prewarm_task
    for _ in range(5):
        await asyncio.sleep(0)
    # Without the delay the request would hold a resident worker by now (it is made before the first await).
    assert service.resident_count == 0 and not task.done()

    await _stop_task(rt)

    assert task.cancelled() and rt.voice_prewarm_task is None
    assert service.resident_count == 0 and _calls(record) == []


@pytest.mark.asyncio
async def test_p9_a_reply_that_arrives_during_the_warm_up_waits_for_it_and_shares_its_process(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    monkeypatch.setattr(kokoro_backend, "PREWARM_TEXT", "SLOW")
    backend = KokoroBackend(cfg, service=service)
    warm = asyncio.create_task(backend.prewarm())
    try:
        await _until(lambda: bool(_calls(record)))
        reply = await backend.synthesize("Hello.")
        assert (await warm) is True
    finally:
        warm.cancel()  # a no-op once it has finished

    assert reply is not None
    calls = _calls(record)
    assert [call["text"] for call in calls] == ["SLOW", "Hello."]
    assert calls[0]["pid"] == calls[1]["pid"]
    assert service.resident_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["speech off", "browser", "piper", "switch off", "no tts section", "no service", "not the service"],
)
async def test_p10_no_warm_up_unless_speech_is_on_the_backend_is_kokoro_the_switch_is_on_and_the_service_is_real(
    case: str, service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    tts = {
        "speech off": TTSConfig(enabled=False, backend="kokoro", kokoro=cfg),
        "browser": TTSConfig(backend="browser", kokoro=cfg),
        "piper": TTSConfig(backend="piper", kokoro=cfg),
        "switch off": TTSConfig(backend="kokoro", kokoro=cfg.model_copy(update={"prewarm": False})),
    }.get(case, TTSConfig(backend="kokoro", kokoro=cfg))
    voice = {"no service": None, "not the service": MagicMock()}.get(case, service)
    rt = _runtime(tts, voice)
    if case == "no tts section":
        rt.config = SimpleNamespace()

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)
    for _ in range(5):
        await asyncio.sleep(0)

    assert rt.voice_prewarm_task is None
    assert service.resident_count == 0 and _calls(record) == []


@pytest.mark.asyncio
async def test_p11_startup_starts_the_warm_up_and_returns_before_the_worker_answers(
    service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not inspect.iscoroutinefunction(finalize_module._start_voice_prewarm)
    cfg, record = _installed(tmp_path, monkeypatch)
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)

    task = rt.voice_prewarm_task
    assert isinstance(task, asyncio.Task) and not task.done()
    assert task.get_name() == "ad738g-s2-kokoro-prewarm"
    assert _calls(record) == [] and service.resident_count == 0
    assert (await task) is True
    assert service.resident_count == 1 and rt.dream_scheduler.speech == 0


def _calls_by_name(fn: Any) -> list[ast.Call]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]


def test_p12_finalize_starts_the_warm_up_and_shutdown_cancels_it_before_the_voice_service_closes() -> None:
    # Source scans, as test_bf918_tts_latency.py's shutdown check: the wiring is the property here.
    # P7 to P11 drive the two helpers themselves.
    assert [c.func.id for c in _calls_by_name(finalize_module.finalize_startup)].count("_start_voice_prewarm") == 1

    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))
    rows = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Tuple)
        and any(isinstance(e, ast.Constant) and e.value == _TASK_ATTR for e in node.elts)
    ]
    assert len(rows) == 1
    assert [e.value for e in rows[0].elts if isinstance(e, ast.Constant)] == [None, _TASK_ATTR, _LABEL]
    closes = [c.lineno for c in _calls_by_name(shutdown_module.shutdown) if c.func.id == "_close_voice_synthesis"]
    assert len(closes) == 1 and rows[0].lineno < closes[0]


# --- config -----------------------------------------------------------------------------------


def test_p13_the_switch_is_on_by_default_and_can_be_turned_off() -> None:
    assert KokoroTTSConfig().prewarm is True
    assert TTSConfig().backend == "browser"  # on by default, and inert on the default backend
    assert TTSConfig.model_validate({"backend": "kokoro", "kokoro": {"prewarm": False}}).kokoro.prewarm is False
    assert list(KokoroTTSConfig().model_dump())[-1] == "prewarm"


# --- shutdown, a warm-up that has ended -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["finished", "cancelled"])
async def test_p14_shutdown_clears_a_warm_up_that_has_already_ended(
    ending: str, service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, record = _installed(tmp_path, monkeypatch)
    rt = _runtime(TTSConfig(backend="kokoro", kokoro=cfg), service)

    finalize_module._start_voice_prewarm(runtime=rt, config=rt.config, delay_seconds=0.0)
    task = rt.voice_prewarm_task
    if ending == "finished":
        assert (await task) is True
    else:
        task.cancel()  # before its first step: the coroutine never runs
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.done() and rt.voice_prewarm_task is task

    await _stop_task(rt)

    assert rt.voice_prewarm_task is None
    assert service.resident_count == (1 if ending == "finished" else 0)
    assert len(_calls(record)) == (1 if ending == "finished" else 0)
```

Notes for the reviewer of 7.1:
- **Private access.** The `service._resident`, `._dir` and `._proc` reads follow S3a's `test_r8` (`tests/test_ad738g_s3a_timing_sidecar.py`:180). They are the only way to see the worker's directory and process.
- **P12's source scan** is the precedent of `tests/test_bf918_tts_latency.py`:730-735. It pins wiring that S2 adds; it does not pin a line that a defect could be.
- **P8's yields.** On this tree the request makes its resident worker before its first suspension: `synthesize_outcome`, then `admit`, then the uncontended lock, then `_claim`, all before `run_in_executor`. So five `sleep(0)` are enough to see a missing delay.

## 8. Gates (the orchestrator runs them)

### 8.1 Oracle tree, before the Builder starts

- Count each SEARCH of section 6 at its turn: 1 each, 18 pairs (6.1: 3, 6.2: 2, 6.3: 5, 6.4: 1, 6.5: 2, 6.6: 3, 6.8: 2). 7.1 does not exist.
- A/B: on the base tree 7.1 fails at collection, because `finalize_module._start_voice_prewarm` is missing and `kokoro_backend.PREWARM_TEXT` is read. On the candidate all of it passes.
- The orchestrator's dry build supplies the counts of 8.2 and the digests of 6.7. The Builder's runs should reproduce them on the same tree; a different count is a stop-and-report, not a re-count.

### 8.2 Focused checks on the candidate

The Builder runs its milestone's lines; the orchestrator runs all of them once on the frozen candidate.
```text
M1: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738g_s2_kokoro_prewarm.py tests/test_ad738g_kokoro_voice.py tests/test_ad738g_s3a_timing_sidecar.py tests/test_ad738g_s3a_synthesizer_lipsync.py tests/test_ad738f_per_agent_voices.py tests/test_bf918_tts_latency.py tests/test_bf930_voice_path_timing.py tests/test_bf930_speech_defers_idle_dream.py tests/test_issue1452_stop_leftovers.py tests/test_ad477_naval.py tests/test_bf598_shutdown_idempotency.py tests/test_finalize.py tests/test_ad1270a_startup_receipts.py tests/test_ad1270e2c_experience_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_effect_census.py tests/test_bf892_spawn_env_guard.py -n 0 -q
M1: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1152_agentic_correlation.py -k default_off -n 0 -q
M1: the five commands of 6.7 (M1)
M2: the two commands of 6.7 (M2)
All: d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-738g-s2
```
Expected:
- `tests/test_ad738g_s2_kokoro_prewarm.py` alone gives `21 passed`.
- The whole first M1 line gives the dry build's count, with nothing skipped that was not skipped on the base.
- `-k default_off` gives `3 passed`: `test_default_off_matches_pinned_base` (`:572`) and `test_default_off_golden_pins_only_descriptor_owner_platform` (`:587`), which is parametrised over `linux` and `win32`.

`tests/test_ad1152_agentic_correlation.py` is in the set because it pins the Kokoro defaults dict (`:353-357`). The S1 batch's first canonical gate failed three of its tests because no focused set ran it.

The census files are in the set to prove S2 moves no count:
- `test_ad1346_admission_file_write_census.py`:170-188;
- the effect census's 12 sink launches in 8 rows, 19 system, 5 command-line and 3 unreached (`test_ad1346_admission_effect_census.py`:12-14);
- the BF-892 spawn guard.

Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time on the frozen candidate, each file restored byte for byte)

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| W1 | kokoro_backend: `outcome = await self._speak(PREWARM_TEXT, self._config.voice, 1.0)` | `outcome = None` (no request: the "spawn only" class) | P1, P11 |
| W2 | the same line | `outcome = await KokoroBackend(self._config.model_copy(update={"threads": self._config.threads + 1}), self._service)._speak(PREWARM_TEXT, self._config.voice, 1.0)` (its own key) | P1 (two pids, `resident_count` 2), P2 |
| W3 | kokoro_backend: `if delay_seconds > 0:` | `if False:` | P8 |
| W4 | kokoro_backend: the `except Exception:` clause and its two lines | removed | P4 |
| W5 | kokoro_backend: `ok = outcome is not None and outcome.audio is not None` | `ok = True` | P3, P5, P6 |
| W6 | kokoro_backend: `raise` (in `except asyncio.CancelledError:`) | `return False` | P7, P8 (`task.cancelled()` is False) |
| F1 | finalize: `if tts is None or tts.enabled is not True or tts.backend != "kokoro":` | `if tts is None or tts.enabled is not True:` | P10 `browser`, `piper` |
| F2 | the same line | `if tts is None or tts.backend != "kokoro":` | P10 `speech off` |
| F3 | finalize: `if tts.kokoro.prewarm is not True:` | `if False:` | P10 `switch off` |
| F4 | finalize: `if not isinstance(service, VoiceSynthesisService):` | `if service is None:` | P10 `not the service` |
| F5 | finalize: `def _start_voice_prewarm(` | `async def _start_voice_prewarm(` (call site unchanged) | P11, P7 to P10 |
| F6 | finalize: `delay = PREWARM_DELAY_SECONDS if delay_seconds is None else delay_seconds` | `delay = 0.0` | P8 |
| F7 | finalize: `_start_voice_prewarm(runtime=runtime, config=config)` (in `finalize_startup`) | removed | P12 |
| S1 | shutdown: `(None, "voice_prewarm_task", "AD-738g S2 Kokoro prewarm"),` | removed | P12 |
| S2 | shutdown: `service = getattr(runtime, service_attr, None) if service_attr else None` | `service = getattr(runtime, service_attr, None)` | P7, P8 (`getattr` with `None` raises `TypeError`) |
| S3 | shutdown: `if not (start_pending or stop_awaitable or task_only):` | `if not (start_pending or stop_awaitable):` | P14 finished, cancelled |
| C1 | experience: `prewarm: bool = True` | `prewarm: bool = False` | P13, `test_ad1270e2c_experience_models.py` (the dump pin), `test_ad1152_agentic_correlation.py -k default_off` |

P3.3 is a type guard only: `service_attr` is falsy only when `service` is `None`. It has no row. Record the base tree and each file's sha256 with the campaign, so a Builder whose files match does not repeat it. Rows to rerun if a file differs: W1 to W6 (kokoro_backend), F1 to F7 (finalize), S1 to S3 (shutdown), C1 (experience).

## 9. Diff Reviewer brief (properties to verify)

The consumers that must accept the change are:
- the Captain's vessel on `tts.backend: kokoro` with `lipsync.backend: rhubarb`;
- the default vessel on `browser`;
- the BF-881 shutdown table and its outer-cancellation rule;
- the AD-1152 golden, the config facade and the AD-1346 censuses;
- the runtime-lifecycle leak checks.

1. When `tts.backend` is `browser` or `piper`, or `tts.enabled` is false, or the switch is off, or the runtime has no real `VoiceSynthesisService`, startup creates no task and starts no process. The default config behaves as before.
2. The warm-up builds no worker key of its own: it calls `_speak`, and the admission, lock, claim and retire logic is the service's, unchanged. It cannot start a second worker.
3. The warm-up never calls `record_speech_activity`, never reaches a route or the attachment store, and leaves no file. The service deletes the WAV and the timing file as for any request.
4. The task is stored on `runtime.voice_prewarm_task`, named, and never awaited in `finalize_startup`. Shutdown cancels and awaits it before `_close_voice_synthesis`, in a rollback too. A task that has already ended (finished or cancelled) is not awaited again; its attribute is cleared. An outer cancellation (BF-303) still propagates.
5. `prewarm` never raises except `CancelledError`. After a crash, a timeout or a missing install the service is as a failed reply leaves it, and the next reply starts the worker cold.
6. `_stop_held_start_service` behaves byte for byte as before for every existing caller, all of which pass a string `service_attr`.
7. M1 holds the field and every file it moves, with exactly 6.7's diffs.
8. No census count moves: AD-1346 file-write and effect, BF-892 spawn.
9. No default the Captain uses changes: `tts.backend` (`browser`), `lipsync.backend` (`heuristic`) and every Kokoro field but the new one.
10. New authored text is ASCII; a quotation of a generated row or of an existing anchor keeps its characters (the generator's dash in `config-reference.md`, the em dash of the DECISIONS heading), and `git diff --check` is clean.

## 10. What this does not change, and what waits

**Unchanged:**
- the UI and every route;
- the worker script;
- the resident service (`resident.py`);
- the key and its argv;
- the BF-918 lifecycle, admission and locks;
- the BF-930 timing line;
- the AD-738f voice resolution;
- S3a's timing file and lip-sync path;
- `tts.backend`'s default;
- the dream scheduler;
- the installer;
- the licence register.

**Waits (one line each):**
- **A warm-up per language** (`en-gb` for the `b?_` role voices), if E3 shows a first-call cost per language.
- **A client warm-up route** (option B), if the memory held in sessions without voice matters.
- **An idle eviction of the worker**, which does not exist today and is not this slice's.
- **Warming on a runtime switch to `kokoro`** (the HXI backend enum). The warm-up runs at boot only, so after a switch the first reply is cold, as today.
- **S4 (GPU) and S5.**

## 11. License posture

- **New packages and licences:** none.
- **GPL boundary:** unchanged. The warm-up sends one text line to the same operator-installed worker process over the same line protocol. The phonemizer and espeak-ng (GPL-3.0-or-later) still run only in that process, and nothing in `src` imports them (`tests/test_ad738g_kokoro_voice.py` `test_w8`).
- **Install burden:** none. **Register:** `THIRD_PARTY_LICENSES.md` is unchanged. **Commercial boundary:** nothing near it.

## 12. Measurements and hand sessions

The Captain's rule: no install or timing measurement runs **during a gate** (F-757, #1870). Everything below runs only when no gate is running. None of it gates the build. Each check has its pass condition and its action on failure. **On any failure the defaults stay** (`tts.kokoro.prewarm: true`), and the numbers are recorded on #1662.

### 12.1 Before: the Captain's weekend recording (no S2 code)

After his live interviews, read the live log on his machine:
```powershell
Select-String -Path "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log" -Pattern "BF-930: kokoro request slow|AD-738g: kokoro voice=|resident kokoro started"
```
Record:
- the first sentence's BF-930 line with `cold=yes`, its `total_ms` and its `work_ms`;
- the `synth_ms` of the next ten `AD-738g: kokoro` lines.

This is the "before" sample: the first-sentence latency of a cold worker on his vessel. If he spoke a warm-up line first (section 13), it is that line's numbers.

### 12.2 After the build: the orchestrator, before the PR opens (E1 to E3)

Run after M1, from the worktree root, with no gate running.
- **Inputs.** S1's probe venv and its verified files: `G:\speech-kokoro-probe\venv`, `kokoro-v1.0.onnx` and `voices-v1.0.bin`.
- **The script.** Save it outside the repo as `G:\s2-measure\e1.py`, in a new, empty directory. It puts the candidate's `src` first on `sys.path` and prints `probos.__file__`; the run passes only if that path is under this worktree.
- **What it runs.** Three fresh services in turn:
  - cold: no warm-up, eleven replies;
  - warm: the warm-up, then eleven replies;
  - warm, then eleven replies in the voice of a crew role whose language differs from the warm-up's (`engineering_officer`, `bm_lewis`, `en-gb`; the warm-up is `af_heart`, `en-us`; `lang_for`, `scripts/kokoro_worker.py`:81-83).
- **Memory.** It reads the worker's working set and private bytes after the warm-up and after the eleven replies.

```python
"""AD-738g S2 E1 to E3: cold against warm first reply, worker memory, a second language. Run from the worktree root."""
import asyncio
import logging
import statistics
import subprocess
import sys
import time

sys.path.insert(0, "src")
import probos  # noqa: E402
from probos.audio.tts.kokoro_backend import KokoroBackend  # noqa: E402
from probos.audio.tts.resident import VoiceSynthesisService  # noqa: E402
from probos.config import KokoroTTSConfig  # noqa: E402

PROBE = r"G:\speech-kokoro-probe"
CFG = KokoroTTSConfig(
    python_path=PROBE + r"\venv\Scripts\python",
    model_path=PROBE + r"\kokoro-v1.0.onnx",
    voices_path=PROBE + r"\voices-v1.0.bin",
)
LINE = "Good evening, Captain. All systems are normal, and the watch is quiet."
MEMORY = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
    "Where-Object { $_.CommandLine -like '*kokoro_worker.py*' } | "
    "ForEach-Object { '{0} ws={1} private={2}' -f $_.ProcessId, $_.WorkingSetSize, $_.PrivatePageCount }"
)


def memory() -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", MEMORY], capture_output=True, text=True, check=False)
    return out.stdout.strip() or "no worker"


async def reply(backend: KokoroBackend, role: str | None) -> int:
    started = time.perf_counter()
    result = await (backend.synthesize(LINE, agent_type=role) if role else backend.synthesize(LINE))
    assert result is not None, "a reply degraded"
    return round((time.perf_counter() - started) * 1000)


async def run(warm: bool, role: str | None) -> None:
    service = VoiceSynthesisService()
    backend = KokoroBackend(CFG, service=service)
    try:
        if warm:
            print("prewarm", await backend.prewarm())
            print("memory after prewarm:", memory())
        first = await reply(backend, role)
        rest = [await reply(backend, role) for _ in range(10)]
        print(f"RUN warm={warm} role={role or '-'} first_ms={first} rest_median_ms={statistics.median(rest)} rest_ms={rest}")
        print("memory after 11 replies:", memory())
    finally:
        service.close()


logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
print("probos from", probos.__file__)
for warm, role in ((False, None), (True, None), (True, "engineering_officer")):
    asyncio.run(run(warm, role))
```
Run it with `d:/ProbOS/.venv/Scripts/python.exe G:\s2-measure\e1.py` from the worktree root. It takes about a minute.

- **E1, first reply.**
  - Pass:
    - the warm run prints `prewarm True`;
    - its `first_ms` is at most 1.2 x its `rest_median_ms`;
    - no `BF-930: kokoro request slow ... cold=yes` line appears between its `prewarm result=ok` line and its first `AD-738g: kokoro voice=` line;
    - the cold run's `first_ms` minus the warm run's `first_ms` is at least 2,000 ms (S1's split predicts about 3,100).
  - **Fail:** the defaults stay. Record the numbers, and the Architect decides before the PR, with them, between shipping as is (it does no harm and saves less) and a re-draft of the line (a longer `PREWARM_TEXT`, decision 6).
- **E2, memory.** Record the working set and private bytes after the warm-up and after eleven replies, for each run.
  - Pass: the private bytes after eleven replies are at most 1.25 x those after the warm-up. That shows the warm-up reached the steady state rather than a smaller one.
  - **Fail:** the defaults stay. Record the numbers, and the Architect decides whether a longer warm-up line is worth a follow-up. Growth across replies is the S1 worker's own behaviour and does not block S2.
  - The absolute size is what the Captain pays in a session that never speaks. It goes on #1662 for his information.
- **E3, a second language.**
  - Pass: the third run's `first_ms` is at most 1.2 x its `rest_median_ms`.
  - **Fail:** a per-language first-call cost exists. The defaults stay; record the numbers. Warming one line per language among the configured voices becomes a follow-up (section 10), and the Architect drafts it.

### 12.3 The Captain, in `D:\ProbOS`, after the merge (when convenient)

His vessel is already on `tts.backend: kokoro`, so S2 acts on the next restart.
1. Restart the vessel and wait about 10 s.
2. Read the log:
   ```powershell
   Select-String -Path "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log" -Pattern "kokoro prewarm|resident kokoro started|AD-738g: kokoro voice=|BF-930: kokoro request slow"
   ```
   Pass:
   - `AD-738g S2: kokoro prewarm scheduled in 5 s`, then `BF-918: resident kokoro started`, then `AD-738g S2: kokoro prewarm result=ok ms=...`. The warm-up's own BF-930 line may show `cold=yes`, and that is expected.
   - After the first spoken reply: no BF-930 `cold=yes` line for it, and its `synth_ms` within about 20 % of the later sentences. Compare with 12.1.
3. Memory, at the same time:
   ```powershell
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*kokoro_worker.py*' } | Select-Object ProcessId, ParentProcessId, Name, WorkingSetSize, PrivatePageCount
   ```
   Two rows: the venv launcher (about 5 MB) and its child, the worker; read the child's row.
4. **To turn it off:** set `tts.kokoro.prewarm: false` in `config/system.yaml` and restart. The worker then starts on the first reply, exactly as before S2.

## 13. Text for #1662 (the orchestrator posts these; no closing keyword)

**Design note (when this contract lands):**
> S2 design: the resident Kokoro worker is warmed once, about 5 s after boot, by one real request: the ship's voice speaks one reply-length line and the audio is discarded. A process start alone would save only about 0.7 s of the 3.2 s, because S1 measured 0.72 s of model load and 2.43 s of first call. The warm-up goes through the backend's own request path, so it shares the replies' worker; one warm-up covers every voice, since the voice is not part of the worker key. It is not speech activity for the dream scheduler and stores nothing. Shutdown cancels it before the voice service closes. Any failure leaves the service as a failed reply would. New `tts.kokoro.prewarm`, on by default and inert unless `tts.backend` is `kokoro`; `false` turns it off. Contract: `prompts/ad-738g-s2-kokoro-prewarm.md`. Refs #1662.

**Wave comment (when the S2 PR opens):**
> AD-738g S2 in review: the Kokoro worker is warmed at boot. It does nothing unless `tts.backend` is `kokoro`, and the default is still `browser`. On a Kokoro vessel the worker starts about 5 s after boot instead of on the first reply. To turn it off: `tts.kokoro.prewarm: false` in `config/system.yaml`, then restart. E1 (first reply, cold against warm; four runs, no gate running): the first reply after the warm-up was `cold=no` in all four and took 799 to 947 ms against a steady state of 1.23 to 1.35 s; a cold first reply took 1,857, 4,404, 1,862 and 1,924 ms, so the warm-up saved 915 to 1,093 ms in three runs and 3,579 ms in one. The 2,000 ms bar of 12.2 was met once: it assumed S1's cold-cache start of 3.2 s. Shipped as is, decided by the Architect under 12.2; a live `cold=yes` on the first reply after `prewarm result=ok` would reopen it. E2 (worker memory): about 0.5 GB working set and 1.3 GB private bytes after the warm-up, about 0.62 GB and 1.44 GB after eleven replies (ratio 1.107, bar 1.25). E3 (first reply in an `en-gb` role voice after an `en-us` warm-up): 1,137 to 1,241 ms against rest medians of 1,489 to 1,530 ms, pass in all four. Refs #1662.

**For the Captain (information only, nothing to decide):**
> This weekend's interviews: S2 will not ship by then. Before you record, say one throwaway line in the HXI. It warms the worker for the whole session, because nothing evicts it, so every later line, every crew voice included, is warm. One caveat: the British-English role voices (`bf_*` and `bm_*`) may pay a smaller first-line cost of their own; S2's measurement E3 checks that. After S2 merges the warm-up happens by itself at boot. To turn it off, set `tts.kokoro.prewarm: false` in `config/system.yaml` and restart.

## 14. Tracking

- `PROGRESS.md`: P8.1. `DECISIONS.md`: P8.2.
- `docs/development/ad-ledger-snapshot.json` and `open-ads-report.md`: by `gen_ad_ledger.py` (6.7).
- `docs/development/roadmap.md`: unchanged. Row `:827` is AD-738g as a whole.
- `THIRD_PARTY_LICENSES.md`: unchanged. `docs/research/reference-projects.md`: unchanged (section 15).
- No BF entry.

## 15. Prior art and blind spots

- **Internal.**
  - S1's contract (the 0.72 s and 2.43 s split, `:19`) and S3a's.
  - BF-918 (the resident service and its lock and admission) and BF-881 and BF-303 (the shutdown table and the outer-cancellation rule).
  - BF-930 (the `cold=` line, and speech activity for the idle dream).
  - The AD-477 stored start task (`finalize.py`:6339-6359).
  - `docs/research/`: nothing on worker warm-up.
- **External.** Date used: 2026-11-28. The Speech row of `docs/research/reference-projects.md` was reviewed 2026-11-28 (S3a), so it is not overdue. This slice is process plumbing and needed no project review; the other overdue rows (agent harnesses) are not relevant and are considered, deferred. Two searches:
  - **NVIDIA Triton's `model_warmup`.** The model config names sample requests that run before the model serves, to avoid the startup and optimisation slowdown ([model configuration](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/model_configuration.html), [optimisation](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/optimization.html)). **Absorbed:** a real request, not a load. **Rejected:** blocking readiness on it. ProbOS serves the browser voice meanwhile, so the warm-up runs in the background.
  - **ONNX Runtime first-run cost.** Maintainers in [onnxruntime #11627](https://github.com/microsoft/onnxruntime/issues/11627) and [#12880](https://github.com/microsoft/onnxruntime/issues/12880) say the CPU memory arena grows to the largest input seen, so a warm-up input should be of representative size. **Adapted:** `PREWARM_TEXT` is a reply-length sentence, not a word (decision 6), and E1 and E2 measure the effect.
- **Blind spots.**
  - A language not warmed: the `en-gb` role voices may pay their own first-call cost (E3; the follow-up is in section 10).
  - The memory is held from boot in a session that never speaks: the switch, and E2's numbers for the Captain.
  - A runtime switch to `kokoro` is not warmed (section 10).
  - A reply during the warm-up waits on the key lock, never longer than a cold start (P9).
  - The warm-up takes 1 of 16 admission slots, and the work runs in another process, so the event loop does not stall.
  - The warm-up's own BF-930 line shows `cold=yes`, which is correct (12.3).
  - Eviction: only the resident count (4) or a backend switch drops the worker. After either, the next reply pays the cold start, as today.

## 16. Acceptance criteria

1. The A/B of 8.1 holds, and W1 to W6, F1 to F7, S1, S2 and C1 are killed as 8.3 says.
2. The focused checks of 8.2 pass on each milestone and on the frozen candidate.
   - Pre-existing tests in those files pass unchanged, except the in-place edits of 6.6 a to c, each with its reason inline.
   - The config tools pass in `--check` form with exactly 6.7's diffs.
   - No census count moves.
3. `git diff --check` is clean, new authored text is ASCII (quotations excepted, as in 9.10), and no unnamed file changes.
4. The Diff Reviewer verifies the properties of section 9.
5. One receipted broad gate on the committed head is green, shared with S3a as a batch if S3a's has not run.
6. E1 to E3 (12.2) run before the PR opens, with no gate running, and are recorded on #1662. On a failure the defaults stay and the Architect decides as 12.2 says.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 17. Verified Against Codebase (2026-11-28, tree `a63b3690`)

```text
git rev-parse HEAD HEAD^{tree}
  fb0dc4850897d435df17d53c805943b940bb2c8e / a63b3690b48b248c76ddc37c03abde248748b09b
git status --short
  ?? s2-options-decision.md   (no tracked change)
src/probos/audio/tts/kokoro_backend.py
  20-21 import logging / import time; 29 import KokoroWorkerKey, PiperOutcome, VoiceSynthesisService
  38-40 SPEED_MIN 0.5 / SPEED_MAX 2.0; 76-79 __init__(config, service=None)
  99 return self._config.voice (end of resolve_voice); 101 async def synthesize(
  126-130 the "AD-738g: kokoro voice=%s ..." line; 131-134 TTSResult(..., timing=outcome.timing) (S3a)
  136 async def _speak(...) -> PiperOutcome | None (S3a); 140-142 no service -> WARNING, None
  158-164 "kokoro is not installed (missing: %s)" WARNING, None; 165-172 key = KokoroWorkerKey(...)
  173-175 return await self._service.synthesize_outcome(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed}) (S3a)
src/probos/audio/tts/__init__.py 44-46 select_backend "kokoro" -> KokoroBackend(config.kokoro, service=service)
src/probos/audio/tts/resident.py
  55 VOICE_MAX_IN_FLIGHT = 4 * VOICE_EXECUTOR_WORKERS (16); 61 SLOW_SYNTHESIS_MS = 750.0
  80-83 _caller_cancelled: current_task().cancelling() > 0
  171-212 KokoroWorkerKey(python, script, model, voices, threads, default_voice); no voice field; 201-202 timing_sidecar True
  246 self._proc; 247 self._dir; 260-261 alive; 295-296 if not self.alive: self._spawn()
  313-323 threading.Timer(timeout, self._expire) -> "timeout"; 324-325 not answered -> "exited"
  336-344 finally: unlink the WAV and its timing file
  404-424 _spawn: mkdtemp, stderr.log, Popen, "BF-918: resident %s started (voice=%s)"
  435-448 close: running -> kill only; 518-519 resident_count
  556-629 synthesize_outcome: admit (562), lock setdefault + async with (572-573), _claim (577),
          run_in_executor (588), CancelledError -> _forget, raise if the caller was cancelled (591-598),
          BF-930 line only when total_ms >= 750 with cold=yes|no (610-619), ok -> return outcome (620-621),
          failure -> retire (626-629)
  631-648 _claim makes the PiperWorker and puts it in _resident before any await; 688-709 close()
src/probos/routers/avatars.py 224-225 cfg = runtime.config.tts; disabled or browser -> disabled
  288-290 dream_scheduler.record_speech_activity(); 292-295 select_backend(cfg.backend, cfg, service=voice_service)
src/probos/startup/finalize.py
  10 import asyncio; 33 TYPE_CHECKING SystemConfig; 807-830 _start_recording_reaper (helper pattern)
  911-919 the end of _start_transcript_reaper, then async def _start_working_memory_cognition(*, runtime: Any, config: "SystemConfig") -> None:
  4168-4172 async def finalize_startup(*, runtime, config); 6337-6363 AD-477 stored start tasks
  6385-6389 log_consensus_gap_register(); runtime._started = True
src/probos/runtime.py 859 self.voice_synthesis = VoiceSynthesisService(); 3728 finalize_startup(runtime=self, config=self.config)
  (no captains_log_start_task declaration: finalize sets start-task attributes itself)
src/probos/startup/shutdown.py
  9 import asyncio; 11 import inspect; 22 from probos.audio.tts.resident import VoiceSynthesisService
  109-121 _close_voice_synthesis; 429-499 _stop_held_start_service (432 service_attr: str, 453 getattr,
  456 start_pending, 459 early return, 461-465 outer cancel, 468-481 cancel and await the start task, 496-497 setattr guard)
  870-871 async def shutdown(runtime, reason="", *, rollback=False)
  1582-1595 the BF-881 table (1587-1588 the plan_of_day row); 1660-1661 _close_voice_synthesis(runtime)
src/probos/config_models/experience.py 639 class KokoroTTSConfig; 676-682 agent_voices and its docstring;
  684 @field_validator("python_path", "model_path", "voices_path"); 834 enabled True; 839 backend default "browser"; 924 kokoro field
src/probos/settings/section_registry.py 275 enum_values=("browser", "piper", "kokoro") (the only kokoro hit)
scripts/kokoro_worker.py 81-83 lang_for: "en-gb" for b?_ voices, else "en-us"; 160, 217 except Exception; 177 "kokoro worker ready"
tests/fixtures/fake_kokoro_worker.py 18-24 imports (os 20, sys 21); 86-101 _speak records the call first (87-91), then checks; 98-99 CHATTER
tests/test_ad738g_s3a_timing_sidecar.py 53-75 the key and _installed helpers; 78-82 service fixture; 180 service._resident[key]._dir
tests/test_bf918_tts_latency.py 719-735 the shutdown source-scan precedent
tests/test_ad1152_agentic_correlation.py 353-357 the kokoro pop dict (agent_voices last); 566 default_config_sha256; 572, 587 default_off tests
tests/test_ad1270e2c_experience_models.py 211-219 the kokoro dump ('agent_voices': {}}} last)
tests/test_ad738g_kokoro_voice.py 640-651 test_c1 (named fields only)
tests/test_ad1270e1_config_facade.py 1531-1534 counts 311/298/13/229; 1582-1583 field_definitions == 1887; 1589-1590; 1814 test_check_is_green_on_the_committed_baseline
docs/development/config-reference.md 2066 ## tts.kokoro; 2079 agent_voices row (last)
docs/development/config-facade-baseline.yaml 50 canonical_dump_leaves 1892; 51 field_definitions 1887; 56 canonical_dump_sha256;
  2231-2245 KokoroTTSConfig (2236 schema_sha256, 2245 agent_voices last); 3426-3431 SystemConfig; 3638-3656 TTSConfig (3643)
scripts/check_config_facade.py 1783-1787 the passed line with fields=
tests/fixtures/runtime_lifecycle.py 111-116 pending tasks since a baseline
PROGRESS.md 1-3; DECISIONS.md 11 "## Era V — Civilization (Phases 31-36)"; docs/development/roadmap.md 827
```

**Absence Verified (2026-11-28):**

| Claim | Run | Found | Holds |
|---|---|---|---|
| No settings-registry row for a Kokoro sub-field | Grep `kokoro` in `src/probos/settings/section_registry.py` | `:275` only (the backend enum) | yes; no registry edit |
| `base_source_blobs` in the AD-1152 golden has no reader | Grep `base_source_blobs` in `*.py` (whole repo) | no match | yes; editing `finalize.py` moves no pin |
| No test pins `_stop_held_start_service`'s table or signature beyond string callers | Grep `captains_log_start_task\|_stop_held_start_service\|observability_bridge_start_task` in `tests` | `test_issue1452_stop_leftovers.py` (direct calls with a string `start_task_attr`, `:73`, `:302`), `test_ad477_naval.py` | yes; both are unchanged by a `None`-accepting parameter |
| No test scans `finalize.py` or `shutdown.py` for `create_task` | Grep `"create_task"\|'create_task'` in `tests` and `scripts` | other modules' scans (AD-1124 `:2091` crew session, AD-1346 recorder lists, BF-663 monkeypatch); `check_architecture_principles.py`:661-677 flags only an unowned bare `create_task` statement | yes; S2's task is assigned |
| Only the three known places pin the Kokoro defaults dict | Grep `"agent_voices"\|timeout_seconds": 30\.0\|"threads": 4` in `tests`; Grep `kokoro` in `tests` | `test_ad1152_agentic_correlation.py`:355-356, `test_ad1270e2c_experience_models.py`:211-219, `test_ad738f_per_agent_voices.py`:164 (a config value, not a pin); the others are unrelated | yes; 6.6 a and b |
| `config/system.yaml` holds no Kokoro section | Grep `kokoro\|agent_voices` in `config/system.yaml` | no match | yes |
| The facade counts are pinned only in the e1 test and the baseline | Grep `1887` in `tests`; Grep `field_definitions` in the baseline | `test_ad1270e1_config_facade.py`:1582-1583; baseline `:51` | yes; 6.6 c and 6.7 |
| No existing test sends `CRASH`, `SLOW` or `HANG` to the fake worker | Grep `"(CRASH\|SLOW\|HANG)"` in `tests` (whole directory); the fixture's own texts are `NOTIMINGS`, `BADTIMING` and `CHATTER` (`:77`, `:82`, `:98`) | no match | yes |
| `record_speech_activity` is called only by the route | Grep `record_speech_activity` in `src` | `routers/avatars.py`:290 (and its definition, `dreaming.py`:3270) | yes; the warm-up never calls it |
| The runtime does not declare the stored start tasks | Grep `captains_log_start_task\|plan_of_day_start_task` in `runtime.py` | no match | yes; `voice_prewarm_task` follows the same pattern |

**Not verified, and not stated as verified:**
- the dry-build counts and the new digests (8.1, 6.7);
- E1 to E3's numbers;
- that `canonical_dump_leaves` moves by exactly one, and that `config-reference.md` gains exactly one row (the orchestrator's dry build confirms both).

No test was run, nothing was installed and no file was downloaded on this run.
