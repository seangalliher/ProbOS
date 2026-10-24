# BF-918: a spoken reply's first audio and the gaps between its sentences (#1626): the next sentence is prefetched, Piper stays resident, rhubarb is off the first-audio path and voice work has its own executor; spoken audio expires

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23

**Status:** build-ready. One BF, three milestones (M1 S3, M2 S2, M3 S1), one batch, one PR, one broad gate. **BF number:** BF-918 (#1626); this contract allocates nothing. **Tier:** S1 STANDARD, S2 STANDARD, **S3 HIGH** (the reaper gains an automatic age-based deletion on the live store, and a delete-capable tool ships); the batch is reviewed at HIGH (use the Copilot `Diff Reviewer`). **Base:** `origin/main` `26bec26d` (the Architect drafted on `eea6e2f4`; BF-914 merged since, and the three generated files and one pin are regenerated on top of it). **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Orchestrator mechanical repairs (2026-10-24; found by applying this contract by tool to `origin/main` `26bec26d` and running its tests; no design decision, and the tree they produce is what the contract now says).** (1) §7.9's `_tool()` registers the loaded module in `sys.modules` while it executes (and `import sys` joins the imports): a dataclass in `scripts/tts_audio_inventory.py` finds its module's namespace there, so without it the four inventory-tool tests failed with an `AttributeError` on Python 3.12. (2) New §7.9a raises the pinned model-field count in `tests/test_ad1270e1_config_facade.py` from 1879 to 1880 (the one new field; the contract listed no pin there). (3) Eight pairs state their SEARCH as a range ("the block from X through Y") instead of a fenced block: §7.20 pairs 2 and 3, §7.21 pairs 2 and 3, §7.22 pairs 3 and 4, §7.26 pair 7 and §7.27 pair 2. A Builder replaces the stated block with the REPLACE; the orchestrator's oracle applies them with a range tool that locates each block by its start and end lines, never by line numbers.

**Tests:**
- New `tests/test_bf918_tts_retention.py` (M1, 11 functions).
- New `tests/test_bf918_tts_latency.py` (M2, 17 functions).
- New fixture `tests/fixtures/fake_piper.py` (M2).
- New `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx` (M3, 8 cases).
- `ui/src/audio/__tests__/voiceChunking.test.ts`: the `runSentenceQueue` describe (4 cases) is replaced by a `runPrefetchQueue` describe (6 cases).
- Updated pins:
  - `tests/test_ad738_piper_tts.py`: 4 backend tests and 3 stubs.
  - `tests/test_ad738e_1_per_emotion_prosody.py`: 2 tests and 1 stub.
  - `tests/test_ad1025_path_anchoring.py`: 2 tests.
  - `tests/test_bf291_piper_voice_catalog.py`: 3 stubs.
  - `tests/test_bf892_spawn_env_guard.py`: 1 inventory row.
  - `tests/test_ad1270e2d_integrations_models.py`: 1 dump key.
  - `tests/test_ad1270e1_config_facade.py`: 1 field count (§7.9a).
  - `voice.pipelining.test.tsx`: 2 tests and the `_flush` depth.
  - `voice.perEmotion.test.tsx`: 2 body assertions.

**Builder's first action (V0), before M2:** verify the installed Piper's line protocol. From any directory, with the venv interpreter:

```python
import json, pathlib, subprocess, tempfile
d = pathlib.Path(tempfile.mkdtemp(prefix="bf918-v0-"))
p = subprocess.Popen([r"d:\ProbOS\tools\piper\piper.exe", "--model", r"d:\ProbOS\tools\piper\voices\en_US-amy-medium.onnx",
                      "--json-input", "--output_dir", str(d)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
for i, text in enumerate(["Caf\u00e9 one. Two.", "Three."]):
    p.stdin.write((json.dumps({"text": text, "output_file": str(d / f"{i}.wav")}, ensure_ascii=True) + "\n").encode("ascii")); p.stdin.flush()
    print(p.stdout.readline())
p.stdin.close(); print(p.wait(timeout=30), [(f.name, f.stat().st_size, f.read_bytes()[:4]) for f in sorted(d.iterdir())])
```

The expected result is:
- two printed lines, ending `0.wav` and `1.wav`;
- exit code 0;
- two files, each over 44 bytes and starting with `b'RIFF'`.

Also run `d:\ProbOS\tools\piper\piper.exe --help` and check it lists `--json-input`, `--output_dir`, `--noise_scale`, `--length_scale`, `--noise_w` and `--sentence_silence`.

**Any other result is a hard stop:** send it to the Architect. Touch nothing under `%LOCALAPPDATA%\ProbOS\data`.

---

## 0. Premise: what is present on this tree

- **Piper call path:**
  - `PiperBackend.synthesize` (`src/probos/audio/tts/piper_backend.py:126-288`) starts `subprocess.Popen` per call (`:223`) with a `NamedTemporaryFile` (BF-282, `:218`), through `loop.run_in_executor(None, …)` (`:264`).
  - `select_backend` (`audio/tts/__init__.py:16-40`) builds a fresh `PiperBackend` per request.
  - `routers/avatars.py:259-261` is its only production caller.
- **Route order:** synthesize → `store.write(...)` without an origin (`:280`) → rhubarb `generate_visemes` (`:287-295`) → respond (`:304-310`).
- **Rhubarb and ffmpeg** also run on `run_in_executor(None, …)` (`rhubarb_backend.py:194, 269, 405`).
- **No `set_default_executor`** exists in `src/`.
- **Store:** `ATTACHMENT_ORIGINS` (`attachments/store.py:16-23`), `_ORIGIN_DURABILITY` and `_origin_can_upgrade` (`filesystem_store.py:91-98, 179-187`; the upgrade happens at `:252-255`), `_LRU_EVICTION_ORDER` (`reaper.py:30-36`), and the age TTL for `perception_frame` only (`reaper.py:146-169`).
- **Client:**
  - `runSentenceQueue` (`ui/src/audio/voiceChunking.ts:84-100`) awaits each `processOne`.
  - `processOne` is `_synthesizeAndPlay` (`voice.ts:490-494`), which resolves on `ended` (`:562-603`).
  - `stopSpeaking` (`:718-727`) cancels `speechSynthesis` only.
- **Lifecycle precedent:** `LongRunService` is built in `ProbOSRuntime.__init__` (`runtime.py:818-822`) and closed in `shutdown()` (`startup/shutdown.py:899-902`).
- **Captain's config** (`d:\ProbOS\config\system.yaml`, uncommitted): `lipsync.backend: rhubarb` (`:1739`), `tts.backend: piper` (`:1745`), `sentence_silence: 0.35` (`:1752`), `sentence_pipelining_enabled: true` (`:1753`).
- **Installed Piper:** `d:\ProbOS\tools\piper\piper.exe` with `onnxruntime.dll`, `espeak-ng.dll`, `piper_phonemize.dll` and 31 voices, among them `en_US-amy-medium` and `en_US-kathleen-low`. Version unknown (V0).

## 1. Problem

A reply of 5 or more sentences waits 6-7 s for its first audio, and stalls 1 s or more between sentences. Measured on 2026-10-22 for a 7-sentence reply:

| Cost | Seconds |
|---|---|
| Piper, run directly (about 0.5 s of it is process start and model load) | 1.7 |
| Rhubarb, on the critical path | 2.8 |
| Queueing on the shared pool and disk writes | about 1.9 |

There are four defects:

- **D1:** the client synthesizes sentence N+1 only after sentence N has finished playing.
- **D2:** Piper is started, and loads its model, on every call.
- **D3:** rhubarb sits on the first-audio path, and all voice work shares asyncio's default pool with crew cognition.
- **D4:** every spoken WAV is stored as a `chat_attachment`, which never expires: 1,126 WAVs on the live store on 2026-10-23.

One more defect, found in the same path: barge-in does not stop Piper audio (`stopSpeaking` only cancels the browser engine).

## 2. Solution overview

- **S1:**
  - `runPrefetchQueue` replaces `runSentenceQueue`. With lookahead 1, sentence N+1 is prepared while N plays, and N+1 plays only after N ends. A stop plays nothing further and discards whatever was prepared.
  - Preparing an utterance means POSTing its text and creating its `<audio>` element, which starts the WAV loading. Playing it means attaching the listeners and calling `play`.
  - The client sends `defer_visemes: true`, fetches deferred visemes from `/api/avatars/lipsync`, and injects them only while the same audio is playing.
  - `stopSpeaking` pauses the server audio.
  - Two User Timing measures, `bf918:first-audio` and `bf918:sentence-gap`, feed the live acceptance.
- **S2:**
  - New `probos/audio/tts/resident.py`: `PiperWorkerKey`, `PiperWorker` (one resident `piper --json-input` process) and `VoiceSynthesisService` (a dedicated executor, a bound on admitted work, and an LRU set of resident workers).
  - `PiperBackend` runs through the service; `select_backend` takes the service.
  - Rhubarb and ffmpeg take an `executor`.
  - The route defers visemes when asked, and logs per-stage timings.
- **S3:**
  - The new origin `tts_audio` is the least durable: an upload of the same bytes upgrades it.
  - The reaper deletes it by age, and evicts it first under the size cap.
  - `scripts/tts_audio_inventory.py` inventories the legacy WAVs, read-only by default.

## 3. Decisions

| # | Decision | Ranked options (chosen first) and reason |
|---|---|---|
| D1 | Slicing | One contract, three milestones (M1 S3, M2 S2, M3 S1), one batch and gate. M1 and M2 both edit `_synthesize_tts_impl`, so they are sequential. M3's prefetch stands alone; its use of deferred visemes degrades to inline frames without M2. |
| D2 | Resident synthesizer | (1) A `piper --json-input` process per (binary, model, prosody), at most 4 resident, least recently used idle one evicted. Upstream `main.cpp`: prosody fixed per process; per-line keys `text`, `output_file`, `speaker_id`, `speaker`; prints the path with `endl`; logs to stderr. wyoming-piper v1.5.0 does the same. (2) In-process synthesis: rejected (no package installed; piper1-gpl is GPL-3). (3) Per-call spawn on a dedicated pool: rejected (keeps the 0.5 s load). |
| D2a | Process protocol | Each request writes one ASCII JSON line, `{"text": <lines joined by spaces>, "output_file": "<worker dir>/<uuid>.wav"}`. The one-shot path also joined lines with spaces. Lines are read until one names that file. The WAV is read from the file and removed (BF-282). Stderr goes to a file in the worker's directory, so the pipe can never fill and block Piper, and a crash warning quotes its last 500 bytes. `--output_dir` points at that directory, so nothing is ever written to the working directory. |
| D2b | Timeout | A `threading.Timer(timeout)` armed for one request kills the process. The read then returns end of file, the request degrades to `None`, the worker is retired, and the next request starts a new process. Queue and lock waits are not counted, as before (the old `communicate` timeout ran inside the thread). |
| D3 | Visemes | (1) The client opts in with `defer_visemes: true`; the route answers `visemes: []`, `visemes_deferred: true`; the browser POSTs `/api/avatars/lipsync` at prepare time and injects only while that `<audio>` is the one playing; the heuristic track runs in between. (2) Rhubarb overlapped with the store write: rejected (still on the path). (3) Piper phoneme timing: rejected (not emitted). (4) WebSocket push: deferred. |
| D4 | Executor | `VoiceSynthesisService` owns it, as `runtime.voice_synthesis`, created in `__init__` and closed in `shutdown()` before the attachment reaper stops. Constants: 4 threads, 16 in flight, 4 resident. Saturated or closed: refused, `None` (browser speech) or `[]` (heuristic). A runtime without the service: Piper degrades to the browser; rhubarb keeps the default pool (pre-BF-918 behaviour). |
| D5 | Retention | `tts_audio`, first in both tuples. TTL `attachments.tts_audio_retention_seconds` = 900 (from 60 to 86400). The upgrade rule exists already; its tuple must include the new origin. The index format is unchanged; no migration. |
| D5a | Legacy sweep | (i) The inventory tool, deleting only on `--delete --confirm N` with the pidfile held. (ii) An age rule over old `audio/wav` `chat_attachment` items: rejected (it would delete the Captain's uploads). (iii) No sweep: the fallback. **Running `--delete` is the Captain's decision** ("an irreversible or destructive production-data operation"). |
| D6 | Config | One field only. The lookahead is a TypeScript constant (1); the viseme mode is a request flag; pipelining stays default-off. |
| D7 | Barge-in | `stopSpeaking` also pauses `_activeAudio`. That fires that utterance's single terminal `end` (BF-655), and the sentence queue, whose condition is already false, stops and discards. |

## 4. Interaction with the queue

- **BF-914 (#1621):** the only shared files are `docs/development/config-facade-baseline.yaml`, `config-profiles.yaml` and `config-reference.md`. They are never hand-edited: after rebasing onto BF-914, regenerate them (§7.10). This contract does not edit `config_models/experience.py` or `test_ad1270e2c_experience_models.py`.
- **AD-1346 (#1601):** M2 (lifecycle graph, `finalize.py`) and M10 (runtime services, `runtime.py`) may touch `finalize.py`, `runtime.py` and `shutdown.py`. The anchors here are text:
  - `_start_attachment_reaper`'s guard;
  - the `LongRunService` two lines;
  - the `# AD-733-1: Stop attachment retention reaper.` comment;
  - the `def _memory_field(` line;
  - the `long_runs` import line.

  M3's future subprocess effect point will need the resident spawn classified as a `system` principal; BF-892's inventory row (§7.24) records it today.
- **AD-1341 S2 to S6 and BF-919 (#1632):** they touch the archive, the reset path, `tests/conftest.py` and `config.py`, none of which this contract edits. `tests/test_bf918_tts_latency.py` constructs a runtime without starting it, so the archive is never opened.

## 5. Consumers of every value this changes

| Value | Producer | Consumers (grep in §11) |
|---|---|---|
| `POST /api/avatars/tts` response: `backend`, `audio_attachment_id`, `visemes`, `mime`, `duration_ms` | `routers/avatars.py` | `ui/src/audio/voice.ts` (`backend`, `audio_attachment_id`, `visemes`); no client reads `mime` or `duration_ms`; Python tests `test_ad738_piper_tts.py`, `test_ad738e_1…`, `test_bf291…`; vitest `voice.serverTts`, `voice.pipelining`, `voice.perEmotion`, `voice.balancedEnd`, `voice.testGate` |
| new request key `defer_visemes`, response key `visemes_deferred` | `voice.ts` / route | route, `voice.ts`, the new tests |
| `select_backend(…, service)` | `audio/tts/__init__.py` | route (the only production caller); test stubs at `test_ad738_piper_tts.py:508, 544, 589`, `test_ad738e_1…:198`, `test_bf291…:187, 211, 237` |
| `PiperBackend(…, service=)` | `audio/tts/__init__.py` | the route; tests in `test_ad738…`, `test_ad738e_1…`, `test_ad1025_path_anchoring.py` |
| `generate_visemes(…, executor=)` | `rhubarb_backend.py` | both avatar routes; stubs `(*_a, **_kw)` in `test_ad738_piper_tts.py:537, 584` and `test_ad721b1…:333`; `test_bf292…:101` reads `generate_visemes`' source for the `_SUPPORTED_SUFFIXES` line, which stays unchanged |
| `runSentenceQueue` → `runPrefetchQueue` | `voiceChunking.ts` | `voice.ts` (the only production caller); `voiceChunking.test.ts`; a comment at `voice.ts:381` |
| `ATTACHMENT_ORIGINS` | `store.py` | `filesystem_store._normalize_origin`; `test_ad1192…:2883` iterates it (an empty `tts_audio` list is fine) |
| `_LRU_EVICTION_ORDER`, `_ORIGIN_DURABILITY` | reaper, store | the reaper's LRU pass; `write`'s upgrade |
| index `origin` | `FilesystemAttachmentStore.write` | `list_by_origin` (reaper only), `write`, the new tool |
| `AttachmentsConfig` dump | `config_models/integrations.py` | `test_ad1270e2d…` `EXPECTED_DUMPS`; the facade baseline, profiles and reference (regenerated) |
| BF-892 launch inventory | `test_bf892_spawn_env_guard.py:87` | the guard scan |
| `runtime.voice_synthesis` | `runtime.py` | the route, `_bounded_visemes`, `_close_voice_synthesis` |

No `?raw` reader exists for `voice.ts`, `voiceChunking.ts` or `useLipSyncCapture.ts`.

## 6. Milestones and tests

**M1 (S3), §7.1 to §7.10.** Commit "BF-918 M1: spoken TTS audio expires (tts_audio origin, TTL, LRU first) and a read-only legacy inventory".

The tests in `tests/test_bf918_tts_retention.py`:
- `test_tts_audio_is_a_known_origin`
- `test_reaper_deletes_tts_audio_past_its_ttl_and_nothing_else`
- `test_a_chat_upload_of_the_same_bytes_upgrades_tts_audio`
- `test_speaking_bytes_already_held_never_downgrades_them`
- `test_lru_evicts_tts_audio_first`
- `test_route_stores_speech_as_tts_audio`
- `test_reaper_starts_for_the_tts_ttl_alone`
- `test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing`
- `test_delete_refuses_without_the_matching_count`
- `test_delete_with_the_count_removes_exactly_the_candidates`
- `test_delete_refuses_while_probos_runs`

Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_tts_retention.py tests/test_attachment_reaper.py tests/test_ad1192_owned_steps_finalization.py tests/test_ad1270e2d_integrations_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_ad738_piper_tts.py -n 0 -q
```

Then run each `--check` in §7.10.

**M2 (S2), §7.11 to §7.24.** Commit "BF-918 M2: resident Piper on a dedicated voice executor; rhubarb off the first-audio path; route stage timings".

Do V0 first. The tests in `tests/test_bf918_tts_latency.py`:
- `test_one_resident_process_serves_consecutive_requests`
- `test_each_prosody_set_gets_its_own_process`
- `test_overlapping_requests_share_one_process_one_at_a_time`
- `test_a_hung_process_is_killed_at_the_timeout_and_replaced`
- `test_a_crashed_process_degrades_with_its_stderr_and_is_replaced`
- `test_an_empty_wav_degrades`
- `test_saturation_refuses_and_degrades_instead_of_queueing`
- `test_the_least_recently_used_idle_process_makes_room`
- `test_close_stops_resident_processes_and_refuses_new_work`
- `test_voice_work_does_not_queue_behind_a_busy_default_pool`
- `test_rhubarb_runs_on_the_executor_it_is_given`
- `test_a_client_that_does_not_ask_keeps_inline_visemes`
- `test_deferred_visemes_come_from_the_lipsync_route_for_the_stored_audio` (crosses the seam: speech → store → lip-sync)
- `test_the_route_logs_its_stage_timings`
- `test_lipsync_route_runs_rhubarb_on_the_voice_executor`
- `test_the_route_speaks_through_the_resident_process` (crosses the seam: route → backend → service → worker → store)
- `test_the_runtime_owns_one_voice_service_and_shutdown_closes_it`

Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_tts_latency.py tests/test_bf918_tts_retention.py tests/test_ad738_piper_tts.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_ad1025_path_anchoring.py tests/test_ad1025b_path_anchoring.py tests/test_bf291_piper_voice_catalog.py tests/test_bf892_spawn_env_guard.py tests/test_ad721b1_rhubarb_backend.py tests/test_ad721b_1a_ffmpeg_conversion.py tests/test_bf292_rhubarb_unsupported_format.py tests/test_ad1071_tts_pipelining.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1270b_architecture_fitness.py -n 0 -q
```

Then run `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`. Every new class has 15 or fewer methods and fewer than 500 lines.

**M3 (S1), §7.25 to §7.30.** Commit "BF-918 M3: the next sentence is synthesized while one plays; a stop drops prefetched audio; deferred visemes; barge-in silences Piper".

The cases:
- `voice.prefetch.bf918.test.tsx`: P1 to P8.
- `voiceChunking.test.ts`: Q1 to Q6.

Focused check, from `ui/` (the Builder's tree has a `ui/node_modules` junction):

```
npx vitest run src/audio src/__tests__/voice.test.ts src/components/profile/__tests__/ProfileChatTab.ad1291.e2e.test.tsx src/components/profile/__tests__/ProfileChatTab.bf764.test.tsx src/components/profile/__tests__/ProfileChatTab.bf767.test.tsx src/components/profile/__tests__/ProfileChatTab.groupReplyIdentity.test.tsx src/components/profile/__tests__/ProfileChatTab.issue1340.groupUnmount.test.tsx
```

Then the type check, `npx tsc -b`; CI's `ui-tests` job runs `npm run test` and `npm run build`, which is `tsc -b && vite build`.

**Timing harness rule:** if an existing case in `voice.serverTts`, `voice.perEmotion` or `voice.balancedEnd` fails only because its `_flush` helper runs out of microtask ticks (the single-call path gains one await), raise that helper's loop count to 30 and say so in the commit. Never change an assertion.

**The broad gate is run once by the main session, not by the Builder.** It does not run vitest; CI does.

## 7. The contract

### 7.1 `src/probos/attachments/store.py` (M1)

SEARCH:
```python
    "agent_artifact",  # AD-797 (Wave 197): artifact bytes extracted from agent replies
    "crew_trace",  # AD-859a: durable agentic-loop provenance JSON
)
```
REPLACE:
```python
    "agent_artifact",  # AD-797 (Wave 197): artifact bytes extracted from agent replies
    "crew_trace",  # AD-859a: durable agentic-loop provenance JSON
    "tts_audio",  # BF-918 (#1626): spoken reply audio, deleted by age (attachments.tts_audio_retention_seconds)
)
```

### 7.2 `src/probos/attachments/filesystem_store.py` (M1)

SEARCH:
```python
    _ORIGIN_DURABILITY: tuple[str, ...] = (
        "perception_frame",
```
REPLACE:
```python
    _ORIGIN_DURABILITY: tuple[str, ...] = (
        "tts_audio",  # BF-918: least durable; any other write of the same bytes wins
        "perception_frame",
```

### 7.3 `src/probos/attachments/reaper.py` (M1)

Pair 1 of 3:

SEARCH:
```python
Two policies, run in sequence each tick:
  1. Age TTL -- origin=perception_frame older than frame_retention_seconds.
  2. LRU cap -- if total > attachments.max_store_bytes, evict oldest
      perception_frame, browser_screenshot, avatar_render, crew_trace, then
      chat_attachment entries until under cap.
```
REPLACE:
```python
Two policies, run in sequence each tick:
  1. Age TTL -- origin=perception_frame older than frame_retention_seconds,
      and (BF-918) origin=tts_audio older than tts_audio_retention_seconds.
  2. LRU cap -- if total > attachments.max_store_bytes, evict oldest
      tts_audio, perception_frame, browser_screenshot, avatar_render,
      crew_trace, then chat_attachment entries until under cap.
```

Pair 2 of 3:

SEARCH:
```python
_LRU_EVICTION_ORDER: tuple[str, ...] = (
    "perception_frame",
```
REPLACE:
```python
_LRU_EVICTION_ORDER: tuple[str, ...] = (
    "tts_audio",  # BF-918: spoken audio is played once, so it goes first
    "perception_frame",
```

Pair 3 of 3:

SEARCH:
```python
    async def _sweep_age_ttl(self) -> tuple[int, int]:
        """Evict perception_frame entries older than the retention window."""
        retention = int(self._perception_cfg.frame_retention_seconds)
        if retention <= 0:
            return (0, 0)
        cutoff = time.time() - retention
        try:
            candidates = await self._store.list_by_origin("perception_frame")
        except Exception:
            logger.warning(
                "AD-733-1: list_by_origin(perception_frame) failed",
                exc_info=True,
            )
            return (0, 0)
        removed = 0
        freed = 0
        for sha, written_at in candidates:
            if written_at >= cutoff:
                break  # list is sorted oldest-first.
            freed_one = await self._safe_unlink(sha)
            if freed_one is not None:
                removed += 1
                freed += freed_one
        return (removed, freed)
```
REPLACE:
```python
    async def _sweep_age_ttl(self) -> tuple[int, int]:
        """Evict entries older than their origin's retention window.

        ``perception_frame``: ``perception.frame_retention_seconds`` (AD-733-1).
        ``tts_audio``: ``attachments.tts_audio_retention_seconds`` (BF-918). Bytes
        also written under a more durable origin carry that origin, so they are
        never listed here.
        """
        removed = 0
        freed = 0
        for origin, retention in (
            ("perception_frame", int(self._perception_cfg.frame_retention_seconds)),
            ("tts_audio", int(self._attachments_cfg.tts_audio_retention_seconds)),
        ):
            if retention <= 0:
                continue
            cutoff = time.time() - retention
            try:
                candidates = await self._store.list_by_origin(origin)
            except Exception:
                logger.warning(
                    "AD-733-1: list_by_origin(%s) failed",
                    origin,
                    exc_info=True,
                )
                continue
            for sha, written_at in candidates:
                if written_at >= cutoff:
                    break  # list is sorted oldest-first.
                freed_one = await self._safe_unlink(sha)
                if freed_one is not None:
                    removed += 1
                    freed += freed_one
        return (removed, freed)
```

### 7.4 `src/probos/config_models/integrations.py` (M1)

SEARCH:
```python
            "chat_attachment entries, until under cap. 0 = disabled."
        ),
    )

    @field_validator("vision_tier")
```
REPLACE:
```python
            "chat_attachment entries, until under cap. 0 = disabled."
        ),
    )

    # BF-918 (#1626): a spoken reply's audio is played once and no chat record
    # keeps its id, so the reaper deletes origin=tts_audio entries older than
    # this. Bytes also written under a more durable origin keep that origin.
    tts_audio_retention_seconds: int = Field(
        default=900,
        ge=60,
        le=86400,
        description=(
            "BF-918: TTL for spoken TTS audio (origin tts_audio). Default 15 min -- "
            "ample for the browser to fetch and play a reply and its deferred "
            "lip-sync request."
        ),
    )

    @field_validator("vision_tier")
```

### 7.5 `src/probos/startup/finalize.py` (M1)

SEARCH:
```python
    Active when ``perception.enabled`` (ephemeral frames present) or when
    ``attachments.max_store_bytes > 0`` (LRU safety net active for any
    producer). Tier-2 honest-degrade on construction failure -- the
    runtime keeps booting; attachments simply will not be reaped.
    """
    perception_cfg = getattr(config, "perception", None)
    attachments_cfg = getattr(config, "attachments", None)
    if attachments_cfg is None:
        return
    perception_enabled = bool(getattr(perception_cfg, "enabled", False))
    lru_enabled = int(getattr(attachments_cfg, "max_store_bytes", 0)) > 0
    if not (perception_enabled or lru_enabled):
        return
```
REPLACE:
```python
    Active when ``perception.enabled`` (ephemeral frames present), when
    ``attachments.max_store_bytes > 0`` (LRU safety net active for any
    producer), or (BF-918) when spoken TTS audio has a retention window.
    Tier-2 honest-degrade on construction failure -- the
    runtime keeps booting; attachments simply will not be reaped.
    """
    perception_cfg = getattr(config, "perception", None)
    attachments_cfg = getattr(config, "attachments", None)
    if attachments_cfg is None:
        return
    perception_enabled = bool(getattr(perception_cfg, "enabled", False))
    lru_enabled = int(getattr(attachments_cfg, "max_store_bytes", 0)) > 0
    tts_ttl_enabled = int(getattr(attachments_cfg, "tts_audio_retention_seconds", 0)) > 0
    if not (perception_enabled or lru_enabled or tts_ttl_enabled):
        return
```

### 7.6 `src/probos/routers/avatars.py` (M1: the origin)

SEARCH:
```python
    await store.write(attachment_id, result.audio_bytes, result.mime)
```
REPLACE:
```python
    # BF-918 (#1626): spoken audio is played once and no chat record keeps its
    # id, so it is stored under its own origin, which the reaper deletes by age.
    # Identical bytes written under a more durable origin keep that origin.
    await store.write(attachment_id, result.audio_bytes, result.mime, origin="tts_audio")
```

### 7.7 New file: `scripts/tts_audio_inventory.py` (M1)

```python
"""BF-918 (#1626): inventory -- and, on the Captain's word, delete -- the spoken-reply
WAVs stored before the ``tts_audio`` origin existed.

Until BF-918 every reply the server spoke was stored as a ``chat_attachment``, which
never expires (on 2026-10-23 the live store held 1,126 WAVs). New speech is stored as
``tts_audio`` and the reaper deletes it by age; this tool deals with the old ones.

Read-only by default: it prints what it found and changes nothing. ``--delete`` also
needs ``--confirm N``, where N is the candidate count this same run finds, and it holds
the vessel's pidfile while it works, so it refuses while ProbOS runs and ProbOS cannot
start meanwhile. Deletion goes through the attachment store, so its index stays right.

A WAV is a candidate only when every one of these holds:

* its index entry says ``chat_attachment`` (or no origin) and ``audio/wav``, and the
  file ``<id>.wav`` exists;
* its header is what Piper writes: RIFF/WAVE, PCM, mono, 16 bits, 16000 or 22050 Hz;
* it was written more than ``--min-age-days`` ago (default 1);
* its id occurs in no other record file under the data directory (the attachment
  directory excepted), so no chat message, artifact or note refers to it. A record
  file that cannot be read keeps every candidate.

Usage (PowerShell)::

    d:/ProbOS/.venv/Scripts/python.exe scripts/tts_audio_inventory.py --data-dir "$env:LOCALAPPDATA\\ProbOS\\data"
    ... --list                       # also print every candidate id
    ... --delete --confirm <count>   # with ProbOS stopped
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from probos.attachments.filesystem_store import FilesystemAttachmentStore  # noqa: E402
from probos.pidfile_guard import (  # noqa: E402
    AnotherInstanceRunning,
    PidfileLockUnavailable,
    acquire_pidfile,
)

EXIT_OK, EXIT_ERROR, EXIT_REFUSED, EXIT_RUNNING = 0, 1, 2, 3
_PIPER_RATES = frozenset({16000, 22050})
_RECORD_SUFFIXES = frozenset({
    ".db", ".db-wal", ".sqlite", ".sqlite3", ".json", ".jsonl", ".yaml", ".yml", ".md", ".txt",
})
_HASH = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_CHUNK = 16 * 1024 * 1024
_KEPT_REASONS = ("other_origin", "missing_file", "not_piper_shaped", "too_young", "referenced")


@dataclass
class Inventory:
    """What one run found. ``candidates`` maps an id to its size in bytes."""

    wav_entries: int = 0
    unindexed_wavs: int = 0
    candidates: dict[str, int] = field(default_factory=dict)
    kept: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_KEPT_REASONS, 0))
    unreadable: list[str] = field(default_factory=list)


def piper_shaped(path: Path) -> bool:
    """True when the WAV header is the one Piper writes (only the header is read)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(64)
    except OSError:
        return False
    if len(head) < 36 or head[0:4] != b"RIFF" or head[8:12] != b"WAVE" or head[12:16] != b"fmt ":
        return False
    fmt, channels, rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", head[20:36])
    return fmt == 1 and channels == 1 and bits == 16 and rate in _PIPER_RATES


def referenced_ids(data_dir: Path, attachments_dir: Path, wanted: set[str]) -> tuple[set[str], list[str]]:
    """The ids in ``wanted`` that occur in a record file under ``data_dir``, and any
    record file that could not be read (then every id counts as referenced)."""
    if not wanted:
        return set(), []
    targets = {sha.encode("ascii") for sha in wanted}
    found: set[str] = set()
    unreadable: list[str] = []
    for path in sorted(data_dir.rglob("*")):
        if path.suffix.lower() not in _RECORD_SUFFIXES or attachments_dir in path.parents:
            continue
        if not path.is_file():
            continue
        carry = b""
        try:
            with path.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    block = carry + chunk
                    for match in _HASH.finditer(block):
                        if match.group() in targets:
                            found.add(match.group().decode("ascii"))
                    carry = block[-65:]
        except OSError:
            unreadable.append(str(path))
    if unreadable:
        return set(wanted), unreadable
    return found, unreadable


def take_inventory(data_dir: Path, attachments_dir: Path, *, min_age_days: float, now: float) -> Inventory:
    """Classify every indexed WAV. Reads only."""
    inventory = Inventory()
    index_path = attachments_dir / ".index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        index = {}
    if not isinstance(index, dict):
        raise ValueError(f"{index_path} is not an attachment index")
    inventory.unindexed_wavs = sum(1 for p in attachments_dir.glob("*.wav") if p.stem not in index)
    cutoff = now - min_age_days * 86400
    eligible: dict[str, int] = {}
    for sha, entry in sorted(index.items()):
        if not isinstance(entry, dict) or entry.get("mime") != "audio/wav":
            continue
        inventory.wav_entries += 1
        if entry.get("origin", "chat_attachment") != "chat_attachment":
            inventory.kept["other_origin"] += 1
            continue
        path = attachments_dir / f"{sha}.wav"
        if not path.is_file():
            inventory.kept["missing_file"] += 1
            continue
        if not piper_shaped(path):
            inventory.kept["not_piper_shaped"] += 1
            continue
        written_at = entry.get("written_at")
        if not isinstance(written_at, (int, float)) or written_at > cutoff:
            inventory.kept["too_young"] += 1
            continue
        eligible[sha] = path.stat().st_size
    referenced, inventory.unreadable = referenced_ids(data_dir, attachments_dir, set(eligible))
    for sha, size in eligible.items():
        if sha in referenced:
            inventory.kept["referenced"] += 1
        else:
            inventory.candidates[sha] = size
    return inventory


async def _unlink_all(store: FilesystemAttachmentStore, ids: list[str]) -> tuple[int, int]:
    deleted = 0
    freed = 0
    for sha in ids:
        try:
            size = await store.size(sha)
        except FileNotFoundError:
            size = 0
        if await store.unlink(sha):
            deleted += 1
            freed += size
    return deleted, freed


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BF-918: inventory, and on request delete, spoken WAVs stored before the tts_audio origin.",
    )
    parser.add_argument("--data-dir", required=True, help="the vessel's data directory, e.g. %%LOCALAPPDATA%%\\ProbOS\\data")
    parser.add_argument("--attachments-dir", default=None, help="the attachment store (default: <data-dir>/attachments)")
    parser.add_argument("--min-age-days", type=float, default=1.0)
    parser.add_argument("--list", action="store_true", help="also print every candidate id")
    parser.add_argument("--delete", action="store_true", help="delete the candidates (ProbOS must be stopped)")
    parser.add_argument("--confirm", type=int, default=None, help="with --delete: the candidate count of a dry run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    data_dir = Path(args.data_dir).resolve()
    attachments_dir = Path(args.attachments_dir).resolve() if args.attachments_dir else data_dir / "attachments"
    if args.delete and args.confirm is None:
        print("refused: --delete needs --confirm N, where N is the candidate count a dry run reported", file=sys.stderr)
        return EXIT_REFUSED
    pidfile: Path | None = None
    if args.delete:
        try:
            pidfile = acquire_pidfile(data_dir)
        except (AnotherInstanceRunning, PidfileLockUnavailable) as exc:
            print(f"refused: a ProbOS instance holds {data_dir} ({exc}); stop it, then run this again", file=sys.stderr)
            return EXIT_RUNNING
    try:
        inventory = take_inventory(data_dir, attachments_dir, min_age_days=args.min_age_days, now=time.time())
        report: dict[str, Any] = {
            "data_dir": str(data_dir),
            "attachments_dir": str(attachments_dir),
            "wav_entries": inventory.wav_entries,
            "unindexed_wavs": inventory.unindexed_wavs,
            "candidates": len(inventory.candidates),
            "candidate_bytes": sum(inventory.candidates.values()),
            "kept": inventory.kept,
            "unreadable": inventory.unreadable,
            "deleted": 0,
            "freed_bytes": 0,
        }
        if args.list:
            report["candidate_ids"] = sorted(inventory.candidates)
        if args.delete:
            if args.confirm != len(inventory.candidates):
                report["refused"] = (
                    f"--confirm {args.confirm} does not match the {len(inventory.candidates)} candidate(s) found now"
                )
                print(json.dumps(report, indent=2))
                return EXIT_REFUSED
            store = FilesystemAttachmentStore(attachments_dir)
            report["deleted"], report["freed_bytes"] = asyncio.run(_unlink_all(store, sorted(inventory.candidates)))
        print(json.dumps(report, indent=2))
        return EXIT_OK
    finally:
        if pidfile is not None:
            pidfile.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
```

### 7.8 `tests/test_ad1270e2d_integrations_models.py` (M1: the pinned dump)

SEARCH:
```python
        "vision_tier_overrides": {},
        "max_store_bytes": 5368709120,
    },
```
REPLACE:
```python
        "vision_tier_overrides": {},
        "max_store_bytes": 5368709120,
        # BF-918 (#1626): a field added after the move, so not in the pre-move text.
        "tts_audio_retention_seconds": 900,
    },
```

### 7.9 New file: `tests/test_bf918_tts_retention.py` (M1)

```python
"""BF-918 (#1626) S3: spoken TTS audio is stored as ``tts_audio`` and swept by age;
anything else holding the same bytes keeps them; the inventory tool deletes nothing
unless the Captain says so, and never while ProbOS runs.

Real store, reaper, route and tool. Every path is under ``tmp_path``; nothing touches
the live store.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.reaper import AttachmentReaper
from probos.audio.tts import TTSResult
from probos.config import AttachmentsConfig, LipSyncConfig, PerceptionConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.startup.finalize import _start_attachment_reaper

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DAY = 86400


def _piper_wav(samples: int, *, rate: int = 22050, channels: int = 1) -> bytes:
    """A PCM WAV of ``samples`` frames: Piper's shape by default."""
    data = b"\x00\x00" * samples * channels
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, channels, rate, rate * 2 * channels, 2 * channels, 16)
    body = fmt + struct.pack("<4sI", b"data", len(data)) + data
    return struct.pack("<4sI4s", b"RIFF", 4 + len(body), b"WAVE") + body


async def _write(store, blob: bytes, origin: str, *, mime: str = "audio/wav", age_seconds: float | None = None) -> str:
    sha = hashlib.sha256(blob).hexdigest()
    await store.write(sha, blob, mime, origin=origin)
    if age_seconds is not None:
        async with store._lock:  # noqa: SLF001 -- force-age, as tests/test_attachment_reaper.py does
            store._index[sha]["written_at"] = time.time() - age_seconds  # noqa: SLF001
            store._save_index_sync()  # noqa: SLF001
    return sha


def _reaper(store, *, tts_ttl: int = 900, max_store_bytes: int = 0) -> AttachmentReaper:
    return AttachmentReaper(
        store,
        perception_cfg=PerceptionConfig(enabled=True, frame_retention_seconds=300),
        attachments_cfg=AttachmentsConfig(max_store_bytes=max_store_bytes, tts_audio_retention_seconds=tts_ttl),
    )


@pytest.mark.asyncio
async def test_tts_audio_is_a_known_origin(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    store = FilesystemAttachmentStore(tmp_path)
    sha = await _write(store, _piper_wav(100), "tts_audio")
    assert [s for s, _ in await store.list_by_origin("tts_audio")] == [sha]
    assert "unknown attachment origin" not in caplog.text


@pytest.mark.asyncio
async def test_reaper_deletes_tts_audio_past_its_ttl_and_nothing_else(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    old_tts = await _write(store, _piper_wav(110), "tts_audio", age_seconds=1000)
    new_tts = await _write(store, _piper_wav(120), "tts_audio", age_seconds=10)
    old_chat = await _write(store, _piper_wav(130), "chat_attachment", age_seconds=10 * _DAY)

    summary = await _reaper(store, tts_ttl=900).sweep_once()

    assert summary["age_ttl_removed"] == 1
    assert not await store.exists(old_tts)
    assert await store.exists(new_tts)
    assert await store.exists(old_chat)


@pytest.mark.asyncio
async def test_a_chat_upload_of_the_same_bytes_upgrades_tts_audio(tmp_path: Path) -> None:
    """Spoken first, then uploaded by the Captain: the more durable origin wins, and it is kept."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(140)
    sha = await _write(store, blob, "tts_audio")
    await _write(store, blob, "chat_attachment", age_seconds=10 * _DAY)

    assert [s for s, _ in await store.list_by_origin("chat_attachment")] == [sha]
    assert await store.list_by_origin("tts_audio") == []
    await _reaper(store, tts_ttl=60).sweep_once()
    assert await store.exists(sha)


@pytest.mark.asyncio
async def test_speaking_bytes_already_held_never_downgrades_them(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(150)
    sha = await _write(store, blob, "chat_attachment")
    await _write(store, blob, "tts_audio", age_seconds=10 * _DAY)

    assert [s for s, _ in await store.list_by_origin("chat_attachment")] == [sha]
    await _reaper(store, tts_ttl=60).sweep_once()
    assert await store.exists(sha)


@pytest.mark.asyncio
async def test_lru_evicts_tts_audio_first(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    frame = await _write(store, b"\xff\xd8" + b"f" * 4000, "perception_frame", mime="image/jpeg", age_seconds=5)
    spoken = await _write(store, _piper_wav(2000), "tts_audio", age_seconds=1)  # newer than the frame
    total = await store.total_size_bytes()

    summary = await _reaper(store, tts_ttl=_DAY, max_store_bytes=total - 1).sweep_once()

    assert summary["lru_removed"] == 1
    assert not await store.exists(spoken)  # spoken audio goes first, though it is newer
    assert await store.exists(frame)


@pytest.mark.asyncio
async def test_route_stores_speech_as_tts_audio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    wav = _piper_wav(160)

    class _Stub:
        name = "piper"

        async def synthesize(self, text, emotion=None, voice_override=None):
            return TTSResult(audio_bytes=wav, mime="audio/wav")

    monkeypatch.setattr("probos.audio.tts.select_backend", lambda *_a, **_k: _Stub())
    rt = SimpleNamespace(config=SimpleNamespace(
        attachments=AttachmentsConfig(attachments_dir=str(target)),
        lipsync=LipSyncConfig(),
        tts=TTSConfig(backend="piper"),
    ))
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            body = (await client.post("/api/avatars/tts", json={"text": "hello"})).json()
        index = json.loads((target / ".index.json").read_text(encoding="utf-8"))
        assert index[body["audio_attachment_id"]]["origin"] == "tts_audio"
    finally:
        chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_reaper_starts_for_the_tts_ttl_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Perception off and no size cap: spoken audio still expires."""
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    config = SimpleNamespace(
        perception=PerceptionConfig(enabled=False),
        attachments=AttachmentsConfig(attachments_dir=str(target), max_store_bytes=0),
    )
    runtime = SimpleNamespace(config=config, attachment_reaper=None)
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    try:
        await _start_attachment_reaper(runtime=runtime, config=config)
        assert isinstance(runtime.attachment_reaper, AttachmentReaper)
    finally:
        if runtime.attachment_reaper is not None:
            await runtime.attachment_reaper.stop()
        chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


# --- the inventory tool (scripts/tts_audio_inventory.py) -------------------------------


def _tool():
    spec = importlib.util.spec_from_file_location(
        "tts_audio_inventory", _REPO_ROOT / "scripts" / "tts_audio_inventory.py",
    )
    module = importlib.util.module_from_spec(spec)
    # A dataclass in the tool finds its module's namespace through sys.modules while the module executes.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


async def _legacy_store(data_dir: Path) -> dict[str, str]:
    """A data dir with the shapes a live store holds: legacy spoken WAVs, and what must be kept."""
    store = FilesystemAttachmentStore(data_dir / "attachments")
    shas = {
        "legacy": await _write(store, _piper_wav(700), "chat_attachment", age_seconds=3 * _DAY),
        "legacy_low": await _write(store, _piper_wav(700, rate=16000), "chat_attachment", age_seconds=3 * _DAY),
        "referenced": await _write(store, _piper_wav(800), "chat_attachment", age_seconds=3 * _DAY),
        "stereo": await _write(store, _piper_wav(900, channels=2), "chat_attachment", age_seconds=3 * _DAY),
        "recent": await _write(store, _piper_wav(1000), "chat_attachment", age_seconds=60),
        "spoken_now": await _write(store, _piper_wav(1100), "tts_audio", age_seconds=3 * _DAY),
        "image": await _write(store, b"\x89PNG" + b"i" * 50, "chat_attachment", mime="image/png", age_seconds=3 * _DAY),
    }
    (data_dir / "chat.db").write_bytes(b"SQLite format 3\x00 msg " + shas["referenced"].encode("ascii") + b" end")
    return shas


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    before = _snapshot(data_dir)

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert sorted(report["candidate_ids"]) == sorted([shas["legacy"], shas["legacy_low"]])
    assert report["wav_entries"] == 6
    assert report["kept"] == {
        "other_origin": 1, "missing_file": 0, "not_piper_shaped": 1, "too_young": 1, "referenced": 1,
    }
    assert report["deleted"] == 0
    assert _snapshot(data_dir) == before


def test_delete_refuses_without_the_matching_count(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    before = _snapshot(data_dir / "attachments")
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir), "--delete"]) == tool.EXIT_REFUSED
    assert tool.main(["--data-dir", str(data_dir), "--delete", "--confirm", "3"]) == tool.EXIT_REFUSED
    assert _snapshot(data_dir / "attachments") == before
    assert not (data_dir / "probos.pid").exists()


def test_delete_with_the_count_removes_exactly_the_candidates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))

    assert _tool().main(["--data-dir", str(data_dir), "--delete", "--confirm", "2"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["deleted"] == 2
    attachments = data_dir / "attachments"
    for name, sha in shas.items():
        assert any(attachments.glob(f"{sha}.*")) is (name not in {"legacy", "legacy_low"}), name
    index = json.loads((attachments / ".index.json").read_text(encoding="utf-8"))
    assert shas["legacy"] not in index and shas["referenced"] in index
    assert not (data_dir / "probos.pid").exists()  # released


def test_delete_refuses_while_probos_runs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    before = _snapshot(data_dir / "attachments")
    # A live process (this test's parent) holds the vessel's pidfile.
    (data_dir / "probos.pid").write_text(str(os.getppid()), encoding="ascii")
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir), "--delete", "--confirm", "2"]) == tool.EXIT_RUNNING
    assert _snapshot(data_dir / "attachments") == before
    assert (data_dir / "probos.pid").read_text(encoding="ascii") == str(os.getppid())
```

### 7.9a `tests/test_ad1270e1_config_facade.py` (M1: the pinned field count; added by the orchestrator after the oracle run, see the header)

SEARCH:
```python
    # BF-914 adds channels.discord.allow_all_users and channels.slack.allow_all_users (1877 -> 1879).
    assert counts["field_definitions"] == 1879  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # BF-914 adds channels.discord.allow_all_users and channels.slack.allow_all_users (1877 -> 1879).
    # BF-918 adds attachments.tts_audio_retention_seconds (1879 -> 1880).
    assert counts["field_definitions"] == 1880  # AD-1206 intentionally adds github_repository.
```

### 7.10 Generated files (M1; by tool, never by hand)

Rebase onto `main` with BF-914 merged first, if it has merged. Then run:

```
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
```

- The diff should add exactly the `attachments.tts_audio_retention_seconds` leaf and its rows. Do not hard-code a leaf count or a checksum.
- If BF-914 merges after M1 is committed, regenerate on top of it, never by merging these files by hand.

### 7.11 New file: `src/probos/audio/tts/resident.py` (M2)

```python
"""BF-918 (#1626): resident Piper synthesis on a dedicated, bounded executor.

Before BF-918 every ``POST /api/avatars/tts`` started ``piper`` and loaded its voice
model (about 0.5 s of every call, measured 2026-10-22), and Piper, rhubarb and ffmpeg
ran on asyncio's default thread pool, which about 100 call sites share with crew
cognition. This module keeps one ``piper --json-input`` process per voice and prosody
set, and runs all voice work on its own executor.

Piper fixes the model and the prosody flags per process (a JSON line carries only
``text``, ``output_file``, ``speaker_id`` and ``speaker``: rhasspy/piper
``src/cpp/main.cpp``), so a process is keyed by both. The per-emotion prosody table
(``prosody.py``) is finite, so the keys are too.

Kept from the one-shot path: the per-request timeout (a hung process is killed and
the next request starts a new one); honest degrade to ``None``; BF-282 (each WAV goes
to a file, never stdout); BF-280 (``subprocess.Popen`` in a thread, never an asyncio
subprocess); BF-892 (``env=trusted_command_env()``). New: a clean stop with the
runtime (``close``, called from ``startup/shutdown.py``).

Not ``loop.set_default_executor``: that would change the pool under every other
caller, crew cognition included, and bound none of them.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator

from probos.execution.command_env import trusted_command_env

logger = logging.getLogger(__name__)

#: Threads for voice work: Piper requests and rhubarb/ffmpeg runs.
VOICE_EXECUTOR_WORKERS = 4
#: Voice work admitted at once, running or queued; beyond it work is refused and degrades.
VOICE_MAX_IN_FLIGHT = 4 * VOICE_EXECUTOR_WORKERS
#: Resident Piper processes at once (each holds a voice model in memory).
PIPER_MAX_RESIDENT = 4
#: How much of a dead process's stderr its warning quotes.
_STDERR_TAIL_BYTES = 500


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


@dataclass(frozen=True)
class PiperOutcome:
    """One request's result. ``audio`` is set only when ``reason`` is ``ok``."""

    audio: bytes | None
    reason: str
    returncode: int | None = None
    stderr_tail: str = ""


class PiperWorker:
    """One resident ``piper --json-input`` process for one ``PiperWorkerKey``.

    ``synthesize_blocking`` blocks: the service runs it on the voice executor, one
    request at a time per worker (it holds the key's lock). The process, its stderr
    file and its output directory belong to this object; ``close`` releases them.
    """

    def __init__(self, key: PiperWorkerKey) -> None:
        self.key = key
        self._proc: subprocess.Popen[bytes] | None = None
        self._dir: Path | None = None
        self._stderr: IO[bytes] | None = None
        self._timed_out = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def synthesize_blocking(self, text: str, timeout: float) -> PiperOutcome:
        """Run one request; starts the process first when it is not running."""
        out: Path | None = None
        try:
            if not self.alive:
                self._spawn()
            proc, out_dir = self._proc, self._dir
            if proc is None or out_dir is None or proc.stdin is None or proc.stdout is None:
                return PiperOutcome(None, "error: no pipes to the piper process")
            out = out_dir / f"{uuid.uuid4().hex}.wav"
            # One JSON object per line. ensure_ascii keeps every byte on the pipe ASCII,
            # and a line break in the text becomes a space, as the one-shot path's Piper
            # joined stdin's lines.
            line = json.dumps({"text": " ".join(text.splitlines()), "output_file": str(out)}, ensure_ascii=True)
            self._timed_out = False
            timer = threading.Timer(timeout, self._expire, args=(proc,))
            timer.daemon = True
            timer.start()
            try:
                proc.stdin.write(line.encode("ascii") + b"\n")
                proc.stdin.flush()
                answered = self._await_answer(proc.stdout, out.name)
            finally:
                timer.cancel()
            if self._timed_out:
                return PiperOutcome(None, "timeout")
            if not answered:
                return PiperOutcome(None, "exited", self._reap(proc), self._stderr_tail())
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

    @staticmethod
    def _await_answer(stdout: IO[bytes], name: str) -> bool:
        """Read lines until Piper prints the path of ``name``; False at end of file."""
        while True:
            reply = stdout.readline()
            if not reply:
                return False
            if Path(reply.decode("utf-8", errors="replace").strip()).name == name:
                return True

    @staticmethod
    def _reap(proc: subprocess.Popen[bytes]) -> int | None:
        try:
            return proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return None

    def _stderr_tail(self) -> str:
        if self._dir is None:
            return ""
        try:
            data = (self._dir / "stderr.log").read_bytes()
        except OSError:
            return ""
        return data[-_STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")

    def _expire(self, proc: subprocess.Popen[bytes]) -> None:
        self._timed_out = True
        try:
            proc.kill()
        except OSError:
            pass

    def _spawn(self) -> None:
        self.close()
        self._dir = Path(tempfile.mkdtemp(prefix="probos-piper-"))
        # BF-918: stderr goes to a file, so Piper's per-line log can never fill a pipe and block it.
        self._stderr = (self._dir / "stderr.log").open("wb")
        self._proc = subprocess.Popen(
            self.key.argv(self._dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=trusted_command_env(),
        )
        logger.info("BF-918: resident piper started (voice=%s)", Path(self.key.model).stem)

    def kill(self) -> None:
        """Kill the process if it runs. Never blocks."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def close(self, wait_seconds: float = 2.0) -> None:
        """Kill the process and release its pipes, stderr file and directory. Idempotent."""
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=wait_seconds)
            except subprocess.TimeoutExpired:
                pass
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        stderr, self._stderr = self._stderr, None
        if stderr is not None:
            try:
                stderr.close()
            except OSError:
                pass
        directory, self._dir = self._dir, None
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


class VoiceSynthesisService:
    """BF-918: the runtime's voice work: one bounded executor and the resident Piper processes.

    Owned by the runtime (``runtime.voice_synthesis``), built with it (constructing it
    starts nothing) and closed at shutdown. Everything but the workers' blocking
    methods runs on the event loop. Work beyond ``max_in_flight`` is refused and
    degrades (the browser speaks that sentence, or keeps its heuristic lip-sync); it
    never queues without bound.
    """

    def __init__(
        self,
        *,
        workers: int = VOICE_EXECUTOR_WORKERS,
        max_in_flight: int = VOICE_MAX_IN_FLIGHT,
        max_resident: int = PIPER_MAX_RESIDENT,
    ) -> None:
        if min(workers, max_in_flight, max_resident) < 1:
            raise ValueError("BF-918: voice synthesis limits must be at least 1")
        self._workers = workers
        self._max_in_flight = max_in_flight
        self._max_resident = max_resident
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._in_flight = 0
        self._closed = False
        self._resident: OrderedDict[PiperWorkerKey, PiperWorker] = OrderedDict()
        self._busy: set[PiperWorkerKey] = set()
        self._locks: dict[PiperWorkerKey, asyncio.Lock] = {}

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def resident_count(self) -> int:
        return len(self._resident)

    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """The voice executor, made on first use. Raises ``RuntimeError`` once closed."""
        if self._closed:
            raise RuntimeError("BF-918: the voice synthesis service is closed")
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._workers,
                thread_name_prefix="probos-voice",
            )
        return self._executor

    @contextlib.contextmanager
    def admit(self) -> Iterator[bool]:
        """Yield True and hold one slot while voice work runs; False when closed or full."""
        if self._closed or self._in_flight >= self._max_in_flight:
            yield False
            return
        self._in_flight += 1
        try:
            yield True
        finally:
            self._in_flight -= 1

    async def synthesize(self, key: PiperWorkerKey, text: str, timeout: float) -> bytes | None:
        """WAV bytes for ``text`` from the resident process for ``key``, or ``None`` to degrade."""
        with self.admit() as admitted:
            if not admitted:
                if not self._closed:
                    logger.warning(
                        "BF-918: voice work refused, %d request(s) already in flight (limit %d); "
                        "the browser speaks this one",
                        self._in_flight, self._max_in_flight,
                    )
                return None
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                if self._closed:
                    return None
                worker = await self._claim(key)
                if worker is None:
                    return None
                loop = asyncio.get_running_loop()
                self._busy.add(key)
                try:
                    future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout)
                    outcome = await future
                except asyncio.CancelledError:
                    # The caller went away while the worker is mid-request on its thread: kill it
                    # and drop it, so no later request can share its pipes.
                    self._forget(key, worker)
                    raise
                except Exception:
                    # The executor shut down (the runtime is stopping) or the worker raised what
                    # it does not handle: degrade, and never reuse that worker.
                    logger.warning("BF-918: piper request failed; the browser speaks this one", exc_info=True)
                    self._forget(key, worker)
                    return None
                finally:
                    self._busy.discard(key)
                if outcome.audio is not None:
                    return outcome.audio
                self._log_failure(outcome, text, timeout)
                if self._resident.get(key) is worker:
                    del self._resident[key]
                await self._retire(worker)
                return None

    async def _claim(self, key: PiperWorkerKey) -> PiperWorker | None:
        """The resident worker for ``key``, made when missing; the least recently used idle one makes room."""
        worker = self._resident.get(key)
        if worker is not None:
            self._resident.move_to_end(key)
            return worker
        while len(self._resident) >= self._max_resident:
            idle = next((k for k in self._resident if k not in self._busy), None)
            if idle is None:
                logger.warning(
                    "BF-918: all %d resident piper processes are busy; the browser speaks this one",
                    self._max_resident,
                )
                return None
            await self._retire(self._resident.pop(idle))
        worker = PiperWorker(key)
        self._resident[key] = worker
        return worker

    def _forget(self, key: PiperWorkerKey, worker: PiperWorker) -> None:
        if self._resident.get(key) is worker:
            del self._resident[key]
        worker.close(wait_seconds=0.5)

    async def _retire(self, worker: PiperWorker) -> None:
        """Close a worker that has no request in flight, off the event loop."""
        worker.kill()
        try:
            await asyncio.get_running_loop().run_in_executor(self.executor, worker.close)
        except RuntimeError:
            worker.close(wait_seconds=0.5)

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

    def close(self) -> None:
        """Stop every resident process and the executor; refuse all later work. Idempotent; never awaits."""
        if self._closed:
            return
        self._closed = True
        workers = list(self._resident.items())
        self._resident.clear()
        for _key, worker in workers:
            worker.kill()
        for key, worker in workers:
            if key not in self._busy:
                worker.close(wait_seconds=0.5)
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if workers:
            logger.info("BF-918: voice synthesis closed; stopped %d resident piper process(es)", len(workers))
```

### 7.12 `src/probos/audio/tts/piper_backend.py` (M2)

Pair 1 of 4:

SEARCH:
```python
import asyncio
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from probos.audio.tts.backends import TTSResult
from probos.audio.tts.prosody import resolve_prosody_overrides
from probos.execution.command_env import trusted_command_env
```
REPLACE:
```python
import logging
import sys
from pathlib import Path

from probos.audio.tts.backends import TTSResult
from probos.audio.tts.prosody import resolve_prosody_overrides
from probos.audio.tts.resident import PiperWorkerKey, VoiceSynthesisService
```

Pair 2 of 4:

SEARCH:
```python
class PiperBackend:
    """Subprocess wrapper around the piper binary.

    Piper reads text on stdin and writes a complete WAV file (RIFF header
    + PCM data) to stdout when invoked with ``--model <path> --output_file -``.
    NOTE: ``--output_raw`` writes raw PCM samples WITHOUT a header — that is
    NOT what we want; ``<audio>`` and rhubarb both require a WAV container.
    Verified against rhasspy/piper README (MIT, archived 2025-10-06): the
    ``-`` argument to ``--output_file`` is the documented stdout sink.
    The wrapper passes text via stdin (UTF-8), reads the WAV from stdout,
    and returns it as ``TTSResult(audio_bytes=..., mime="audio/wav")``.
    """
```
REPLACE:
```python
class PiperBackend:
    """Piper TTS backend.

    Resolves the binary, the voice model (including the BF-291 per-call
    override) and the per-emotion prosody (AD-738e-1) for one call, then asks
    the runtime's ``VoiceSynthesisService`` (BF-918) for the audio: a resident
    ``piper --json-input`` process for that voice and prosody set, which writes
    each WAV to a file (BF-282) and runs on the voice executor. Returns
    ``TTSResult(audio_bytes=..., mime="audio/wav")`` or ``None`` (degrade).
    ``<audio>`` and rhubarb both need a WAV container, never raw PCM.
    """
```

Pair 3 of 4:

SEARCH:
```python
        noise_w: float = 1.0,
        sentence_silence: float = 0.35,
    ) -> None:
        self._binary_path = binary_path
```
REPLACE:
```python
        noise_w: float = 1.0,
        sentence_silence: float = 0.35,
        service: VoiceSynthesisService | None = None,
    ) -> None:
        # BF-918: the runtime's resident synthesis; without it Piper degrades to the browser.
        self._service = service
        self._binary_path = binary_path
```

Pair 4 of 4:

SEARCH:
```python
        try:
            # BF-282 (2026-05-13): write to a temp WAV file instead of stdout.
            # On Windows, ``--output_file -`` writes to stdout which Piper's
            # C runtime opens in text mode by default, converting every 0x0A
            # byte to 0x0D 0x0A and corrupting the PCM body — produces audio
            # that sounds like static. Writing to a file bypasses the text-
            # mode translation entirely. Identical behavior on Linux/macOS.
            #
            # BF-280 (2026-05-13): use subprocess.Popen in a thread executor
            # instead of asyncio.create_subprocess_exec. The latter requires
            # ProactorEventLoop, but ProbOS runtime uses WindowsSelectorEventLoop
            # which raises NotImplementedError on Windows. Mirrors the
            # shell_command.py:_run_sync pattern.
            def _run_sync() -> tuple[int, bytes, bytes]:
                # NamedTemporaryFile + delete=False so Piper can open it by
                # name; we delete in the finally block after reading.
                with tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False
                ) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    proc = subprocess.Popen(
                        [
                            str(binary),
                            "--model", str(model),
                            "--output_file", str(tmp_path),
                            # AD-738e prosody knobs — see TTSConfig docstrings
                            # for tuning rationale. Captain Decision: piper
                            # upstream defaults (0.667 / 1.0 / 0.8 / 0.2) sound
                            # monotone; our defaults bump expressiveness +
                            # rhythm variation at a small clarity cost.
                            "--noise_scale", str(_noise_scale),
                            "--length_scale", str(_length_scale),
                            "--noise_w", str(_noise_w),
                            "--sentence_silence", str(_sentence_silence),
                        ],
                        stdin=subprocess.PIPE,
                        env=trusted_command_env(),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        _stdout, err = proc.communicate(
                            input=text.encode("utf-8"),
                            timeout=self._timeout_seconds,
                        )
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                        raise
                    rc = proc.returncode or 0
                    if rc != 0 or not tmp_path.is_file():
                        return rc, b"", err
                    return rc, tmp_path.read_bytes(), err
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            loop = asyncio.get_running_loop()
            try:
                returncode, wav_bytes, stderr_bytes = await loop.run_in_executor(
                    None, _run_sync,
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "AD-738: piper timed out after %ss synthesizing %d chars",
                    self._timeout_seconds, len(text),
                )
                return None
            if returncode != 0:
                logger.warning(
                    "AD-738: piper exit=%s; stderr=%s",
                    returncode,
                    stderr_bytes.decode("utf-8", errors="replace")[:500],
                )
                return None
            if not wav_bytes:
                logger.warning("AD-738: piper produced 0 bytes; degrading")
                return None
            return TTSResult(audio_bytes=wav_bytes, mime="audio/wav")
        except (OSError, ValueError) as e:
            logger.warning(
                "AD-738: piper subprocess failed: %s: %s", type(e).__name__, e
            )
            return None
```
REPLACE:
```python
        if self._service is None:
            logger.warning(
                "BF-918: no voice synthesis service on this runtime; degrading to browser"
            )
            return None
        # BF-918 (#1626): one resident process per (voice, prosody) key on the voice
        # executor. The service keeps BF-280, BF-282, BF-892 and the timeout, and logs
        # any failure in the AD-738 wording.
        key = PiperWorkerKey(
            binary=str(binary),
            model=str(model),
            noise_scale=_noise_scale,
            length_scale=_length_scale,
            noise_w=_noise_w,
            sentence_silence=_sentence_silence,
        )
        wav_bytes = await self._service.synthesize(key, text, self._timeout_seconds)
        if wav_bytes is None:
            return None
        return TTSResult(audio_bytes=wav_bytes, mime="audio/wav")
```

### 7.13 `src/probos/audio/tts/__init__.py` (M2)

SEARCH:
```python
if TYPE_CHECKING:
    from probos.config import TTSConfig


def select_backend(backend_name: str, config: "TTSConfig") -> TTSBackend:
    """Select a backend instance by configured name.

    Tier-2 log-and-degrade: an unknown backend name is treated as
    ``"browser"`` (NullBackend). Logged at WARNING.
    """
    logger = logging.getLogger(__name__)
    if backend_name == "piper":
        return PiperBackend(
            binary_path=config.binary_path,
            voice_model=config.voice_model,
            voices_dir=config.voices_dir,
            timeout_seconds=config.timeout_seconds,
            noise_scale=config.noise_scale,
            length_scale=config.length_scale,
            noise_w=config.noise_w,
            sentence_silence=config.sentence_silence,
        )
```
REPLACE:
```python
if TYPE_CHECKING:
    from probos.audio.tts.resident import VoiceSynthesisService
    from probos.config import TTSConfig


def select_backend(
    backend_name: str,
    config: "TTSConfig",
    service: "VoiceSynthesisService | None" = None,
) -> TTSBackend:
    """Select a backend instance by configured name.

    Tier-2 log-and-degrade: an unknown backend name is treated as
    ``"browser"`` (NullBackend). Logged at WARNING.

    BF-918: ``service`` is the runtime's voice synthesis service; Piper runs in
    its resident processes, and degrades to the browser without one.
    """
    logger = logging.getLogger(__name__)
    if backend_name == "piper":
        return PiperBackend(
            binary_path=config.binary_path,
            voice_model=config.voice_model,
            voices_dir=config.voices_dir,
            timeout_seconds=config.timeout_seconds,
            noise_scale=config.noise_scale,
            length_scale=config.length_scale,
            noise_w=config.noise_w,
            sentence_silence=config.sentence_silence,
            service=service,
        )
```

### 7.14 `src/probos/avatars/rhubarb_backend.py` (M2)

Pair 1 of 7:

SEARCH:
```python
from typing import Literal

from probos.execution.command_env import trusted_command_env
```
REPLACE:
```python
from typing import TYPE_CHECKING, Literal

from probos.execution.command_env import trusted_command_env

if TYPE_CHECKING:
    from concurrent.futures import Executor
```

Pair 2 of 7:

SEARCH:
```python
async def _convert_to_wav(
    audio_path: Path,
    ffmpeg_binary: Path,
    *,
    timeout_seconds: float = 30.0,
) -> Path | None:
```
REPLACE:
```python
async def _convert_to_wav(
    audio_path: Path,
    ffmpeg_binary: Path,
    *,
    timeout_seconds: float = 30.0,
    executor: Executor | None = None,
) -> Path | None:
```

Pair 3 of 7:

SEARCH:
```python
            returncode, stderr_bytes = await loop.run_in_executor(None, _run_sync)
```
REPLACE:
```python
            returncode, stderr_bytes = await loop.run_in_executor(executor, _run_sync)
```

Pair 4 of 7:

SEARCH:
```python
async def generate_visemes(
    audio_path: Path,
    binary_path: str,
    timeout_seconds: float = 30.0,
    *,
    ffmpeg_binary_path: str | None = None,
) -> list[VisemeFrame]:
```
REPLACE:
```python
async def generate_visemes(
    audio_path: Path,
    binary_path: str,
    timeout_seconds: float = 30.0,
    *,
    ffmpeg_binary_path: str | None = None,
    executor: Executor | None = None,
) -> list[VisemeFrame]:
    # BF-918: ``executor`` is the runtime's voice executor; ``None`` keeps asyncio's default pool.
```

Pair 5 of 7:

SEARCH:
```python
            converted_temp = await _convert_to_wav(audio_path, ffmpeg_binary)
```
REPLACE:
```python
            converted_temp = await _convert_to_wav(audio_path, ffmpeg_binary, executor=executor)
```

Pair 6 of 7:

SEARCH:
```python
        return await _run_rhubarb(audio_path, binary_path, timeout_seconds)
```
REPLACE:
```python
        return await _run_rhubarb(audio_path, binary_path, timeout_seconds, executor=executor)
```

Pair 7 of 7 (the signature and the executor call of `_run_rhubarb`; two blocks):

SEARCH:
```python
async def _run_rhubarb(
    audio_path: Path,
    binary_path: str,
    timeout_seconds: float,
) -> list[VisemeFrame]:
```
REPLACE:
```python
async def _run_rhubarb(
    audio_path: Path,
    binary_path: str,
    timeout_seconds: float,
    *,
    executor: Executor | None = None,
) -> list[VisemeFrame]:
```

SEARCH:
```python
            returncode, stdout_bytes, stderr_bytes = await loop.run_in_executor(
                None, _run_sync,
            )
```
REPLACE:
```python
            returncode, stdout_bytes, stderr_bytes = await loop.run_in_executor(
                executor, _run_sync,
            )
```

The pair 4 comment is placed before the docstring, so the docstring stops being the function's docstring. **Builder:** put that one comment line after the docstring's closing `"""`, not before it. Do not change `_SUPPORTED_SUFFIXES = {".wav", ".ogg"}`: `test_bf292` reads it from the source.

### 7.15 `src/probos/routers/avatars.py` (M2)

Pair 1 of 6:

SEARCH:
```python
import logging
from typing import Any
```
REPLACE:
```python
import logging
import time
from typing import Any
```

Pair 2 of 6 (the lip-sync route):

SEARCH:
```python
    # backend == "rhubarb"
    from probos.avatars.rhubarb_backend import generate_visemes
    audio_path = await store.get_path(attachment_id)
    frames = await generate_visemes(
        audio_path,
        binary_path=cfg.binary_path,
        timeout_seconds=cfg.timeout_seconds,
        ffmpeg_binary_path=cfg.ffmpeg_binary_path,
    )
    if not frames:
```
REPLACE:
```python
    # backend == "rhubarb". BF-918: on the voice executor, inside its admission bound.
    audio_path = await store.get_path(attachment_id)
    started = time.perf_counter()
    frames = await _bounded_visemes(runtime, audio_path, cfg)
    logger.info(
        "BF-918: lipsync route visemes_ms=%.0f frames=%d",
        (time.perf_counter() - started) * 1000, len(frames),
    )
    if not frames:
```

Pair 3 of 6 (the docstring):

SEARCH:
```python
    Returns:
        - Best path: ``{"backend": "piper", "audio_attachment_id": "<sha256>",
          "mime": "audio/wav", "visemes": [...], "duration_ms": <int>}``
```
REPLACE:
```python
    BF-918: ``{"defer_visemes": true}`` in the body skips rhubarb here; the
    response then has ``"visemes": []`` and ``"visemes_deferred": true``, and the
    client asks ``POST /api/avatars/lipsync`` for them while the audio plays.

    Returns:
        - Best path: ``{"backend": "piper", "audio_attachment_id": "<sha256>",
          "mime": "audio/wav", "visemes": [...], "visemes_deferred": <bool>,
          "duration_ms": <int>}``
```

Pair 4 of 6:

SEARCH:
```python
    from probos.audio.tts import select_backend
    backend = select_backend(cfg.backend, cfg)
    result = await backend.synthesize(text, emotion=emotion, voice_override=voice_name)
    if result is None:
```
REPLACE:
```python
    # BF-918 (#1626): a client that asks gets its visemes from POST /api/avatars/lipsync
    # while the audio plays, so rhubarb (0.85 s for one sentence, 2.8 s for seven,
    # measured 2026-10-22) is off the first-audio path. Any other client keeps the
    # single round trip.
    defer_visemes = payload.get("defer_visemes") is True

    from probos.audio.tts import select_backend
    voice_service = getattr(runtime, "voice_synthesis", None)
    started = time.perf_counter()
    backend = select_backend(cfg.backend, cfg, service=voice_service)
    result = await backend.synthesize(text, emotion=emotion, voice_override=voice_name)
    synthesized = time.perf_counter()
    if result is None:
        logger.info(
            "BF-918: tts route chars=%d synth_ms=%.0f result=degraded",
            len(text), (synthesized - started) * 1000,
        )
```

Pair 5 of 6 (the text after M1's §7.6):

SEARCH:
```python
    await store.write(attachment_id, result.audio_bytes, result.mime, origin="tts_audio")

    # Reuse AD-721b-1 rhubarb backend by direct internal call. lipsync.backend
    # may be "heuristic" (default) — in that case skip rhubarb and let the
    # browser fall back to its heuristic schedule for THIS audio.
    visemes_payload: list[dict[str, Any]] = []
    lipsync_cfg = getattr(runtime.config, "lipsync", None)
    if lipsync_cfg is not None and lipsync_cfg.enabled and lipsync_cfg.backend == "rhubarb":
        from probos.avatars.rhubarb_backend import generate_visemes
        audio_path = await store.get_path(attachment_id)
        frames = await generate_visemes(
            audio_path,
            binary_path=lipsync_cfg.binary_path,
            timeout_seconds=lipsync_cfg.timeout_seconds,
            ffmpeg_binary_path=lipsync_cfg.ffmpeg_binary_path,
        )
        visemes_payload = [
            {"time": f.time, "duration": f.duration, "viseme": f.viseme}
            for f in frames
        ]

    # Duration: parse from WAV header. Cheap and self-contained.
    duration_ms = _wav_duration_ms(result.audio_bytes)

    return {
        "backend": backend.name,
        "audio_attachment_id": attachment_id,
        "mime": result.mime,
        "visemes": visemes_payload,
        "duration_ms": duration_ms,
    }
```
REPLACE:
```python
    await store.write(attachment_id, result.audio_bytes, result.mime, origin="tts_audio")
    stored = time.perf_counter()

    # Reuse AD-721b-1 rhubarb backend by direct internal call. lipsync.backend
    # may be "heuristic" (default) — in that case skip rhubarb and let the
    # browser fall back to its heuristic schedule for THIS audio.
    visemes_payload: list[dict[str, Any]] = []
    visemes_mode = "off"
    lipsync_cfg = getattr(runtime.config, "lipsync", None)
    if lipsync_cfg is not None and lipsync_cfg.enabled and lipsync_cfg.backend == "rhubarb":
        if defer_visemes:
            visemes_mode = "deferred"
        else:
            visemes_mode = "inline"
            audio_path = await store.get_path(attachment_id)
            frames = await _bounded_visemes(runtime, audio_path, lipsync_cfg)
            visemes_payload = [
                {"time": f.time, "duration": f.duration, "viseme": f.viseme}
                for f in frames
            ]
    finished = time.perf_counter()

    # Duration: parse from WAV header. Cheap and self-contained.
    duration_ms = _wav_duration_ms(result.audio_bytes)
    # BF-918: the stage timings the live acceptance reads (probos.log).
    logger.info(
        "BF-918: tts route chars=%d synth_ms=%.0f store_ms=%.0f visemes_ms=%.0f "
        "total_ms=%.0f visemes=%s audio_ms=%d",
        len(text), (synthesized - started) * 1000, (stored - synthesized) * 1000,
        (finished - stored) * 1000, (finished - started) * 1000, visemes_mode, duration_ms,
    )

    return {
        "backend": backend.name,
        "audio_attachment_id": attachment_id,
        "mime": result.mime,
        "visemes": visemes_payload,
        "visemes_deferred": visemes_mode == "deferred",
        "duration_ms": duration_ms,
    }
```

Pair 6 of 6:

SEARCH:
```python
def _wav_duration_ms(wav_bytes: bytes) -> int:
```
REPLACE:
```python
async def _bounded_visemes(runtime: Any, audio_path: Any, lipsync_cfg: Any) -> list[Any]:
    """BF-918 (#1626): rhubarb (and ffmpeg) on the voice executor, inside its admission bound.

    A runtime that never built the voice service keeps asyncio's default pool,
    as before BF-918. Saturated or stopping: no frames, and the browser keeps
    its heuristic schedule (AD-721b).
    """
    from probos.avatars.rhubarb_backend import generate_visemes

    voice_service = getattr(runtime, "voice_synthesis", None)
    if voice_service is None:
        return await generate_visemes(
            audio_path,
            binary_path=lipsync_cfg.binary_path,
            timeout_seconds=lipsync_cfg.timeout_seconds,
            ffmpeg_binary_path=lipsync_cfg.ffmpeg_binary_path,
        )
    with voice_service.admit() as admitted:
        if not admitted:
            logger.warning(
                "BF-918: lip-sync refused (voice work is at its limit or stopping); "
                "the browser keeps its heuristic schedule"
            )
            return []
        return await generate_visemes(
            audio_path,
            binary_path=lipsync_cfg.binary_path,
            timeout_seconds=lipsync_cfg.timeout_seconds,
            ffmpeg_binary_path=lipsync_cfg.ffmpeg_binary_path,
            executor=voice_service.executor,
        )


def _wav_duration_ms(wav_bytes: bytes) -> int:
```

### 7.16 `src/probos/runtime.py` (M2)

SEARCH:
```python
        from probos.execution.long_runs import LongRunService
        self.execution_long_runs = LongRunService()
```
REPLACE:
```python
        from probos.execution.long_runs import LongRunService
        self.execution_long_runs = LongRunService()

        # BF-918 (#1626): voice work -- resident Piper processes and a dedicated,
        # bounded executor for synthesis and lip-sync, so a spoken reply does not
        # queue behind crew cognition on asyncio's default pool. Constructing it
        # starts nothing; closed in startup/shutdown.py.
        from probos.audio.tts.resident import VoiceSynthesisService
        self.voice_synthesis = VoiceSynthesisService()
```

### 7.17 `src/probos/startup/shutdown.py` (M2)

Pair 1 of 3:

SEARCH:
```python
from probos.execution.long_runs import LONG_RUN_SETTLE_SECONDS, LongRunService
```
REPLACE:
```python
from probos.audio.tts.resident import VoiceSynthesisService
from probos.execution.long_runs import LONG_RUN_SETTLE_SECONDS, LongRunService
```

Pair 2 of 3:

SEARCH:
```python
def _memory_field(runtime: Any, name: str, default: float) -> float:
```
REPLACE:
```python
def _close_voice_synthesis(runtime: Any) -> None:
    """BF-918: stop the resident Piper processes and the voice executor.

    Synchronous and idempotent; never raises (a spoken reply is not worth a
    failed shutdown). A runtime without the service has nothing to stop.
    """
    voice_service = getattr(runtime, "voice_synthesis", None)
    if not isinstance(voice_service, VoiceSynthesisService):
        return
    try:
        voice_service.close()
    except Exception:
        logger.warning("BF-918: voice synthesis close failed", exc_info=True)


def _memory_field(runtime: Any, name: str, default: float) -> float:
```

Pair 3 of 3:

SEARCH:
```python
    # AD-733-1: Stop attachment retention reaper.
```
REPLACE:
```python
    # BF-918: stop the resident Piper processes and the voice executor.
    _close_voice_synthesis(runtime)

    # AD-733-1: Stop attachment retention reaper.
```

This step uses a plain call, not `with steps(...)`, as the attachment reaper does, so `tests/test_issue1419_failed_start_rollback.py`'s census of `steps` labels is unchanged.

### 7.18 New file: `tests/fixtures/fake_piper.py` (M2)

```python
"""BF-918 (#1626): a stand-in for a resident ``piper --json-input`` process.

Only the process is fake. The worker under test writes real JSON lines to it and
reads real path lines back, and each WAV is written into the worker's own
directory, so the code path is the production one. Nothing here needs piper.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

#: How long a fake read waits for an answer before reporting end of file.
_READ_DEADLINE_S = 10.0


class _Stdin:
    def __init__(self, proc: "FakePiperProcess") -> None:
        self._proc = proc

    def write(self, data: bytes) -> int:
        self._proc.accept(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Stdout:
    def __init__(self, proc: "FakePiperProcess") -> None:
        self._proc = proc

    def readline(self) -> bytes:
        return self._proc.next_line()

    def close(self) -> None:
        return None


class FakePiperProcess:
    """One fake resident process. ``mode`` decides how it answers each request.

    ``ok``: writes ``wav`` to the request's ``output_file`` and prints that path.
    ``empty``: writes an empty file and prints its path.
    ``hang``: never answers; a read returns end of file once killed.
    ``exit``: writes ``stderr_bytes`` to the stderr file it was given and exits with code 1.
    ``gate``: as ``ok``, but answers only once ``release`` is set.
    """

    def __init__(
        self,
        args: list[str],
        kwargs: dict[str, Any],
        *,
        mode: str,
        wav: bytes,
        stderr_bytes: bytes,
        release: threading.Event | None,
    ) -> None:
        self.args = list(args)
        self.kwargs = dict(kwargs)
        self.mode = mode
        self.wav = wav
        self.stderr_bytes = stderr_bytes
        self.release = release
        self.requests: list[dict[str, Any]] = []
        self.request_threads: list[str] = []
        self.killed = False
        self.overlapped = False
        self.returncode: int | None = None
        self._busy = False
        self._lines: list[bytes] = []
        self._cond = threading.Condition()
        self.stdin = _Stdin(self)
        self.stdout = _Stdout(self)

    def accept(self, data: bytes) -> None:
        with self._cond:
            if self.returncode is not None:
                raise BrokenPipeError("the fake piper process has exited")
            if self._busy:
                self.overlapped = True
            self._busy = True
            request = json.loads(data.decode("ascii"))
            self.requests.append(request)
            self.request_threads.append(threading.current_thread().name)
        if self.mode == "hang":
            return
        if self.mode == "exit":
            stderr = self.kwargs.get("stderr")
            if stderr is not None and hasattr(stderr, "write"):
                stderr.write(self.stderr_bytes)
                stderr.flush()
            self._exit(1)
            return
        if self.mode == "gate" and self.release is not None:
            self.release.wait(timeout=_READ_DEADLINE_S)
        out = Path(request["output_file"])
        out.write_bytes(b"" if self.mode == "empty" else self.wav)
        with self._cond:
            self._busy = False
            self._lines.append(str(out).encode("utf-8") + b"\n")
            self._cond.notify_all()

    def next_line(self) -> bytes:
        deadline = time.monotonic() + _READ_DEADLINE_S
        with self._cond:
            while not self._lines and self.returncode is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._cond.wait(timeout=remaining)
            return self._lines.pop(0) if self._lines else b""

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self._exit(-9)

    def _exit(self, code: int) -> None:
        with self._cond:
            if self.returncode is None:
                self.returncode = code
            self._busy = False
            self._cond.notify_all()


class FakePiperLauncher:
    """Stands in for ``subprocess.Popen``. The n-th launch uses the n-th mode; the last repeats."""

    def __init__(
        self,
        *modes: str,
        wav: bytes = b"RIFF fake wav",
        stderr_bytes: bytes = b"",
        release: threading.Event | None = None,
    ) -> None:
        self.modes = list(modes) or ["ok"]
        self.wav = wav
        self.stderr_bytes = stderr_bytes
        self.release = release
        self.launched: list[FakePiperProcess] = []
        self.launch_threads: list[str] = []

    def __call__(self, args: list[str], *_pos: Any, **kwargs: Any) -> FakePiperProcess:
        mode = self.modes[min(len(self.launched), len(self.modes) - 1)]
        proc = FakePiperProcess(
            args, kwargs, mode=mode, wav=self.wav, stderr_bytes=self.stderr_bytes, release=self.release,
        )
        self.launched.append(proc)
        self.launch_threads.append(threading.current_thread().name)
        return proc
```

### 7.19 New file: `tests/test_bf918_tts_latency.py` (M2)

```python
"""BF-918 (#1626) S2: resident Piper, the voice executor, deferred visemes, stage timings.

Real ``VoiceSynthesisService``, ``PiperWorker``, ``PiperBackend``, routes and store.
Only the processes are fakes (``tests/fixtures/fake_piper.py`` and a rhubarb stand-in);
nothing needs piper, rhubarb or ffmpeg installed, and no test relies on a pid.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import logging
import subprocess
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import TTSResult
from probos.audio.tts import resident
from probos.audio.tts.piper_backend import PiperBackend
from probos.audio.tts.resident import PiperWorkerKey, VoiceSynthesisService
from probos.avatars import rhubarb_backend
from probos.avatars.rhubarb_backend import VisemeFrame, generate_visemes
from probos.config import AttachmentsConfig, LipSyncConfig, SystemConfig, TTSConfig
from probos.execution.command_env import trusted_command_env
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.startup import shutdown as shutdown_module
from tests.fixtures.fake_piper import FakePiperLauncher

_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32


def _key(model: str = "m.onnx") -> PiperWorkerKey:
    return PiperWorkerKey(
        binary="piper", model=model, noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35,
    )


async def _until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


@pytest.fixture
def launcher(monkeypatch: pytest.MonkeyPatch):
    def _install(*modes: str, **kwargs):
        fake = FakePiperLauncher(*modes, wav=kwargs.pop("wav", _WAV), **kwargs)
        monkeypatch.setattr(resident.subprocess, "Popen", fake)
        return fake
    return _install


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


def _voice(tmp_path: Path) -> tuple[Path, Path]:
    binary = tmp_path / "piper"
    binary.write_bytes(b"")
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "v.onnx").write_bytes(b"\x00")
    (voices / "v.onnx.json").write_bytes(b"{}")
    return binary, voices


class _StubBackend:
    name = "piper"

    async def synthesize(self, text, emotion=None, voice_override=None):
        return TTSResult(audio_bytes=_WAV, mime="audio/wav")


class _FakeRhubarb:
    """Stands in for rhubarb's ``subprocess.Popen``; records the thread it ran on."""

    def __init__(self) -> None:
        self.threads: list[str] = []

    def __call__(self, args, *_a, **_kw):
        self.threads.append(threading.current_thread().name)
        cues = b'{"mouthCues": [{"start": 0.0, "end": 0.1, "value": "A"}]}'
        return SimpleNamespace(
            returncode=0,
            communicate=lambda input=None, timeout=None: (cues, b""),
            kill=lambda: None,
            wait=lambda timeout=None: 0,
        )


# --- the resident process --------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_resident_process_serves_consecutive_requests(launcher, service) -> None:
    fake = launcher("ok")

    first = await service.synthesize(_key(), "Hello\nworld.", 5.0)
    second = await service.synthesize(_key(), "Again.", 5.0)

    assert first == _WAV and second == _WAV
    assert len(fake.launched) == 1
    proc = fake.launched[0]
    args = proc.args
    assert "--json-input" in args
    assert args[args.index("--model") + 1] == "m.onnx"
    out_dir = Path(args[args.index("--output_dir") + 1])
    assert [r["text"] for r in proc.requests] == ["Hello world.", "Again."]
    assert all(Path(r["output_file"]).parent == out_dir for r in proc.requests)
    assert not any(Path(r["output_file"]).exists() for r in proc.requests)  # read, then removed (BF-282)
    assert proc.kwargs["env"] == trusted_command_env()  # BF-892
    assert proc.kwargs["stdin"] == subprocess.PIPE and proc.kwargs["stdout"] == subprocess.PIPE
    assert proc.killed is False


@pytest.mark.asyncio
async def test_each_prosody_set_gets_its_own_process(launcher, service, tmp_path: Path) -> None:
    """AD-738e-1's per-emotion prosody stays per call: one resident process per prosody set."""
    fake = launcher("ok")
    binary, voices = _voice(tmp_path)
    backend = PiperBackend(binary_path=str(binary), voice_model="v", voices_dir=str(voices), service=service)

    assert await backend.synthesize("Hi.", emotion="excited") is not None
    assert await backend.synthesize("Hi.") is not None
    assert await backend.synthesize("Hi again.", emotion="excited") is not None

    assert len(fake.launched) == 2
    excited, plain = (p.args for p in fake.launched)
    assert excited[excited.index("--noise_scale") + 1] == "0.95"
    assert excited[excited.index("--length_scale") + 1] == "0.92"
    assert plain[plain.index("--noise_scale") + 1] == "0.85"
    assert plain[plain.index("--length_scale") + 1] == "1.0"
    assert len(fake.launched[0].requests) == 2


@pytest.mark.asyncio
async def test_overlapping_requests_share_one_process_one_at_a_time(launcher, service) -> None:
    release = threading.Event()
    fake = launcher("gate", release=release)
    try:
        first = asyncio.create_task(service.synthesize(_key(), "first", 5.0))
        second = asyncio.create_task(service.synthesize(_key(), "second", 5.0))
        await _until(lambda: bool(fake.launched) and bool(fake.launched[0].requests))
        await asyncio.sleep(0.05)
        assert [r["text"] for r in fake.launched[0].requests] == ["first"]  # the second waits its turn
        release.set()
        assert await first == _WAV and await second == _WAV
    finally:
        release.set()
    proc = fake.launched[0]
    assert len(fake.launched) == 1
    assert [r["text"] for r in proc.requests] == ["first", "second"]
    assert proc.overlapped is False


@pytest.mark.asyncio
async def test_a_hung_process_is_killed_at_the_timeout_and_replaced(launcher, service, caplog) -> None:
    caplog.set_level(logging.WARNING)
    fake = launcher("hang", "ok")

    started = time.monotonic()
    assert await service.synthesize(_key(), "hello", 0.2) is None
    assert time.monotonic() - started < 3.0
    assert fake.launched[0].killed is True
    assert "piper timed out" in caplog.text

    assert await service.synthesize(_key(), "hello", 5.0) == _WAV
    assert len(fake.launched) == 2


@pytest.mark.asyncio
async def test_a_crashed_process_degrades_with_its_stderr_and_is_replaced(launcher, service, caplog) -> None:
    caplog.set_level(logging.WARNING)
    fake = launcher("exit", "ok", stderr_bytes=b"piper: bad model")

    assert await service.synthesize(_key(), "hi", 5.0) is None
    assert "piper exit=1" in caplog.text and "piper: bad model" in caplog.text
    assert await service.synthesize(_key(), "hi", 5.0) == _WAV
    assert len(fake.launched) == 2


@pytest.mark.asyncio
async def test_an_empty_wav_degrades(launcher, service, caplog) -> None:
    caplog.set_level(logging.WARNING)
    launcher("empty")
    assert await service.synthesize(_key(), "hi", 5.0) is None
    assert "0 bytes" in caplog.text


@pytest.mark.asyncio
async def test_saturation_refuses_and_degrades_instead_of_queueing(launcher, caplog) -> None:
    caplog.set_level(logging.WARNING)
    release = threading.Event()
    fake = launcher("gate", release=release)
    svc = VoiceSynthesisService(max_in_flight=1)
    try:
        held = asyncio.create_task(svc.synthesize(_key(), "held", 5.0))
        await _until(lambda: bool(fake.launched) and bool(fake.launched[0].requests))
        assert await svc.synthesize(_key("other.onnx"), "refused", 5.0) is None
        assert "voice work refused" in caplog.text
        with svc.admit() as admitted:
            assert admitted is False
        release.set()
        assert await held == _WAV
        with svc.admit() as admitted:
            assert admitted is True
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_the_least_recently_used_idle_process_makes_room(launcher) -> None:
    fake = launcher("ok")
    svc = VoiceSynthesisService(max_resident=2)
    try:
        for model in ("a.onnx", "b.onnx", "a.onnx", "c.onnx"):
            assert await svc.synthesize(_key(model), "x", 5.0) == _WAV
        by_model = {p.args[p.args.index("--model") + 1]: p for p in fake.launched}
        assert sorted(by_model) == ["a.onnx", "b.onnx", "c.onnx"]
        assert by_model["b.onnx"].killed is True  # least recently used
        assert by_model["a.onnx"].killed is False
        assert svc.resident_count == 2
    finally:
        svc.close()


@pytest.mark.asyncio
async def test_close_stops_resident_processes_and_refuses_new_work(launcher) -> None:
    fake = launcher("ok")
    svc = VoiceSynthesisService()
    assert await svc.synthesize(_key(), "x", 5.0) == _WAV
    out_dir = Path(fake.launched[0].requests[0]["output_file"]).parent

    svc.close()
    svc.close()  # idempotent

    assert fake.launched[0].killed is True
    assert not out_dir.exists()
    assert svc.closed is True
    assert await svc.synthesize(_key(), "x", 5.0) is None
    with svc.admit() as admitted:
        assert admitted is False


@pytest.mark.asyncio
async def test_voice_work_does_not_queue_behind_a_busy_default_pool(launcher, service) -> None:
    """D3: asyncio's default pool fully held by other work (the crew-busy case of 2026-10-22)."""
    fake = launcher("ok")
    loop = asyncio.get_running_loop()
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bf918-busy-default")
    loop.set_default_executor(pool)
    held = loop.run_in_executor(None, release.wait, 30)
    try:
        audio = await asyncio.wait_for(service.synthesize(_key(), "x", 5.0), timeout=3.0)
        assert audio == _WAV
        assert fake.launch_threads[0].startswith("probos-voice")
        assert fake.launched[0].request_threads[0].startswith("probos-voice")
    finally:
        release.set()
        await held
        pool.shutdown(wait=True)
        loop.set_default_executor(ThreadPoolExecutor())


@pytest.mark.asyncio
async def test_rhubarb_runs_on_the_executor_it_is_given(tmp_path: Path, monkeypatch, service) -> None:
    fake = _FakeRhubarb()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    binary = tmp_path / "rhubarb"
    binary.write_bytes(b"")
    audio = tmp_path / "a.wav"
    audio.write_bytes(_WAV)

    frames = await generate_visemes(audio, str(binary), executor=service.executor)

    assert frames
    assert fake.threads[0].startswith("probos-voice")


# --- the routes --------------------------------------------------------------------------


@pytest.fixture
async def voice_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(backend="rhubarb"),
            tts=TTSConfig(backend="piper"),
        ),
        voice_synthesis=service,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, rt, target
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


def _stub_rhubarb(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    async def _visemes(audio_path, **_kw):
        calls.append(Path(audio_path))
        return [VisemeFrame(time=0.0, duration=0.1, viseme="aa")]

    monkeypatch.setattr("probos.avatars.rhubarb_backend.generate_visemes", _visemes)
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _StubBackend())
    return calls


@pytest.mark.asyncio
async def test_a_client_that_does_not_ask_keeps_inline_visemes(voice_client, monkeypatch) -> None:
    client, _rt, _target = voice_client
    calls = _stub_rhubarb(monkeypatch)

    body = (await client.post("/api/avatars/tts", json={"text": "hello"})).json()

    assert body["visemes"] == [{"time": 0.0, "duration": 0.1, "viseme": "aa"}]
    assert body["visemes_deferred"] is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_deferred_visemes_come_from_the_lipsync_route_for_the_stored_audio(voice_client, monkeypatch) -> None:
    client, _rt, _target = voice_client
    calls = _stub_rhubarb(monkeypatch)

    spoken = (await client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})).json()
    assert spoken["visemes"] == [] and spoken["visemes_deferred"] is True
    assert calls == []  # rhubarb is off the first-audio path
    sha = spoken["audio_attachment_id"]
    assert sha == hashlib.sha256(_WAV).hexdigest()

    lipsync = (await client.post("/api/avatars/lipsync", json={"attachment_id": sha})).json()

    assert lipsync == {"backend": "rhubarb", "frames": [{"time": 0.0, "duration": 0.1, "viseme": "aa"}]}
    assert len(calls) == 1 and calls[0].name.startswith(sha)


@pytest.mark.asyncio
async def test_the_route_logs_its_stage_timings(voice_client, monkeypatch, caplog) -> None:
    client, _rt, _target = voice_client
    _stub_rhubarb(monkeypatch)
    caplog.set_level(logging.INFO, logger="probos.routers.avatars")

    await client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})

    line = next(r.getMessage() for r in caplog.records if "BF-918: tts route" in r.getMessage())
    for field in ("synth_ms=", "store_ms=", "visemes_ms=", "total_ms=", "visemes=deferred"):
        assert field in line


@pytest.mark.asyncio
async def test_lipsync_route_runs_rhubarb_on_the_voice_executor(voice_client, monkeypatch, tmp_path: Path) -> None:
    client, rt, target = voice_client
    fake = _FakeRhubarb()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    binary = tmp_path / "rhubarb"
    binary.write_bytes(b"")
    rt.config.lipsync = LipSyncConfig(backend="rhubarb", binary_path=str(binary))
    sha = hashlib.sha256(_WAV).hexdigest()
    (target / f"{sha}.wav").write_bytes(_WAV)

    body = (await client.post("/api/avatars/lipsync", json={"attachment_id": sha})).json()

    assert body["backend"] == "rhubarb"
    assert fake.threads and fake.threads[0].startswith("probos-voice")


@pytest.mark.asyncio
async def test_the_route_speaks_through_the_resident_process(voice_client, launcher, tmp_path: Path) -> None:
    client, rt, _target = voice_client
    fake = launcher("ok")
    binary, voices = _voice(tmp_path)
    rt.config.tts = TTSConfig(backend="piper", binary_path=str(binary), voice_model="v", voices_dir=str(voices))
    rt.config.lipsync = LipSyncConfig()  # heuristic: no rhubarb in this case

    for text in ("One.", "Two."):
        body = (await client.post("/api/avatars/tts", json={"text": text, "defer_visemes": True})).json()
        assert body["backend"] == "piper"
        assert body["audio_attachment_id"] == hashlib.sha256(_WAV).hexdigest()

    assert len(fake.launched) == 1


def test_the_runtime_owns_one_voice_service_and_shutdown_closes_it(tmp_path: Path) -> None:
    from probos.runtime import ProbOSRuntime

    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "data")
    voice = runtime.voice_synthesis
    assert isinstance(voice, VoiceSynthesisService)

    shutdown_module._close_voice_synthesis(runtime)
    assert voice.closed is True
    shutdown_module._close_voice_synthesis(SimpleNamespace())  # no service: nothing to stop, no raise

    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))
    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_close_voice_synthesis" in called
```

### 7.20 `tests/test_ad738_piper_tts.py` (M2: stale pins)

Pair 1 of 5:

SEARCH:
```python
from probos.audio.tts.piper_backend import _resolve_binary_path, _resolve_voice_model
```
REPLACE:
```python
from probos.audio.tts.piper_backend import _resolve_binary_path, _resolve_voice_model
from probos.audio.tts.resident import VoiceSynthesisService
from tests.fixtures.fake_piper import FakePiperLauncher
```

Pair 2 of 5. Remove the one-shot stub: the SEARCH is the whole block from `class _StubProcess:` through `_make_subprocess_factory`'s final `    return _factory` (lines 36-101 on this tree). The REPLACE is:
```python
# BF-918 (#1626): Piper runs as a resident ``--json-input`` process; its fake is
# tests/fixtures/fake_piper.py (the one-shot communicate() stub is gone).
```

Pair 3 of 5. The SEARCH is the block from `@pytest.mark.asyncio` / `async def test_piper_backend_subprocess_timeout_returns_none(` through `    assert result.audio_bytes == wav` (lines 208-297). The REPLACE is:
```python
@pytest.fixture
def voice_service():
    """BF-918: Piper runs in the runtime's resident processes; these tests own one."""
    service = VoiceSynthesisService()
    yield service
    service.close()


@pytest.mark.asyncio
async def test_piper_backend_subprocess_timeout_returns_none(
    monkeypatch, tmp_path, caplog, voice_service
):
    # BF-918: the resident process hangs and is killed at the timeout.
    caplog.set_level(logging.WARNING)
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    launcher = FakePiperLauncher("hang")
    monkeypatch.setattr("subprocess.Popen", launcher)
    backend = PiperBackend(
        binary_path=str(fake_bin), voice_model="v", timeout_seconds=0.2,
        voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
        service=voice_service,
    )
    assert await backend.synthesize("hello") is None
    assert launcher.launched[0].killed is True
    assert any("piper timed out" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_piper_backend_nonzero_exit_returns_none(
    monkeypatch, tmp_path, caplog, voice_service
):
    caplog.set_level(logging.WARNING)
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    monkeypatch.setattr("subprocess.Popen", FakePiperLauncher("exit", stderr_bytes=b"piper: bad model"))
    backend = PiperBackend(
        binary_path=str(fake_bin), voice_model="v",
        voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
        service=voice_service,
    )
    assert await backend.synthesize("hi") is None
    assert any(
        "piper exit=1" in r.message and "piper: bad model" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_piper_backend_zero_bytes_returns_none(
    monkeypatch, tmp_path, caplog, voice_service
):
    caplog.set_level(logging.WARNING)
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    monkeypatch.setattr("subprocess.Popen", FakePiperLauncher("empty"))
    backend = PiperBackend(
        binary_path=str(fake_bin), voice_model="v",
        voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
        service=voice_service,
    )
    assert await backend.synthesize("hi") is None
    assert any("0 bytes" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_piper_backend_happy_path_returns_wav(monkeypatch, tmp_path, voice_service):
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    wav = _make_minimal_wav(num_samples=8000, sample_rate=16000)
    monkeypatch.setattr("subprocess.Popen", FakePiperLauncher("ok", wav=wav))
    backend = PiperBackend(
        binary_path=str(fake_bin), voice_model="v",
        voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
        service=voice_service,
    )
    result = await backend.synthesize("hello world")
    assert result is not None
    assert result.mime == "audio/wav"
    assert result.audio_bytes == wav
```

Pair 4 of 5:

SEARCH:
```python
    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg: _NoneBackend(),
    )
```
REPLACE:
```python
    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg, service=None: _NoneBackend(),
    )
```

Pair 5 of 5 (two blocks):

SEARCH:
```python
    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg: _StubBackend(),
    )
    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _stub_visemes,
    )
```
REPLACE:
```python
    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg, service=None: _StubBackend(),
    )
    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _stub_visemes,
    )
```

SEARCH:
```python
    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg: _StubBackend(),
    )
    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _explode,
    )
```
REPLACE:
```python
    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg, service=None: _StubBackend(),
    )
    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _explode,
    )
```

### 7.21 `tests/test_ad738e_1_per_emotion_prosody.py` (M2: stale pins)

Pair 1 of 4:

SEARCH:
```python
from probos.audio.tts.piper_backend import PiperBackend
```
REPLACE:
```python
from probos.audio.tts.piper_backend import PiperBackend
from probos.audio.tts.resident import VoiceSynthesisService
from tests.fixtures.fake_piper import FakePiperLauncher
```

Pair 2 of 4. The SEARCH is the block from `class _StubProc:` through `_make_args_capturing_factory`'s `    return captured, _factory` (lines 32-66). The REPLACE is:
```python
# BF-918 (#1626): Piper runs as a resident process; the prosody flags are its argv
# (Piper fixes them per process). The fake is tests/fixtures/fake_piper.py.
```

Pair 3 of 4. The SEARCH is the block from `@pytest.mark.asyncio` / `async def test_piper_backend_applies_override_at_synthesis(` through `    assert args[args.index("--sentence_silence") + 1] == "0.35"` (lines 119-179). The REPLACE is:
```python
@pytest.mark.asyncio
async def test_piper_backend_applies_override_at_synthesis(monkeypatch, tmp_path):
    """`excited` overrides noise_scale + length_scale; other knobs keep defaults."""
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    launcher = FakePiperLauncher("ok", wav=_make_minimal_wav())
    monkeypatch.setattr("subprocess.Popen", launcher)
    service = VoiceSynthesisService()
    try:
        backend = PiperBackend(
            binary_path=str(fake_bin),
            voice_model="v",
            voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
            noise_scale=0.85,
            length_scale=1.0,
            noise_w=1.0,
            sentence_silence=0.35,
            service=service,
        )
        result = await backend.synthesize("hi", emotion="excited")
    finally:
        service.close()
    assert result is not None
    assert len(launcher.launched) == 1
    args = launcher.launched[0].args
    # excited override: noise_scale=0.95, length_scale=0.92.
    assert args[args.index("--noise_scale") + 1] == "0.95"
    assert args[args.index("--length_scale") + 1] == "0.92"
    # noise_w / sentence_silence retain constructor defaults.
    assert args[args.index("--noise_w") + 1] == "1.0"
    assert args[args.index("--sentence_silence") + 1] == "0.35"


@pytest.mark.asyncio
async def test_piper_backend_no_emotion_uses_defaults(monkeypatch, tmp_path):
    """Backward compat: no emotion kwarg → all knobs use constructor values."""
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    launcher = FakePiperLauncher("ok", wav=_make_minimal_wav())
    monkeypatch.setattr("subprocess.Popen", launcher)
    service = VoiceSynthesisService()
    try:
        backend = PiperBackend(
            binary_path=str(fake_bin),
            voice_model="v",
            voices_dir=str(tmp_path / "tools" / "piper" / "voices"),
            noise_scale=0.85,
            length_scale=1.0,
            noise_w=1.0,
            sentence_silence=0.35,
            service=service,
        )
        result = await backend.synthesize("hi")  # no emotion kwarg
    finally:
        service.close()
    assert result is not None
    args = launcher.launched[0].args
    assert args[args.index("--noise_scale") + 1] == "0.85"
    assert args[args.index("--length_scale") + 1] == "1.0"
    assert args[args.index("--noise_w") + 1] == "1.0"
    assert args[args.index("--sentence_silence") + 1] == "0.35"
```

Pair 4 of 4:

SEARCH:
```python
    def _select_backend_stub(name, cfg):
        return _StubBackend()
```
REPLACE:
```python
    def _select_backend_stub(name, cfg, service=None):
        return _StubBackend()
```

### 7.22 `tests/test_ad1025_path_anchoring.py` (M2: stale pins)

Pair 1 of 4:

SEARCH:
```python
the boundary; the only stubs are ``SimpleNamespace`` runtime/config shells and
a fake ``subprocess.Popen`` that mirrors the BF-282 ``--output_file`` shape).
```
REPLACE:
```python
the boundary; the only stubs are ``SimpleNamespace`` runtime/config shells and
BF-918's fake resident ``piper --json-input`` process, tests/fixtures/fake_piper.py).
```

Pair 2 of 4:

SEARCH:
```python
from probos.startup.finalize import _wire_relationship_inference
```
REPLACE:
```python
from probos.audio.tts.resident import VoiceSynthesisService
from probos.startup.finalize import _wire_relationship_inference
from tests.fixtures.fake_piper import FakePiperLauncher
```

Pair 3 of 4. The SEARCH is the block from `class _FakePopen:` through `_capturing_popen`'s `    return _factory` (lines 44-77). The REPLACE is:
```python
# BF-918 (#1626): the fake Piper process lives in tests/fixtures/fake_piper.py.
```

Pair 4 of 4. The SEARCH is the block from `@pytest.mark.asyncio` / `async def test_relative_voices_dir_and_override_anchor_to_root(` through `    assert seen["model"] == str((voices / "amy.onnx").resolve())` (lines 188-242). The REPLACE is:
```python
@pytest.mark.asyncio
async def test_relative_voices_dir_and_override_anchor_to_root(
    monkeypatch, tmp_path
) -> None:
    """A relative ``voices_dir`` AND the BF-291 ``voice_override`` both resolve
    under the ProbOS root, independent of CWD (end-to-end through synthesize)."""
    root = tmp_path / "probos_root"
    binary = root / "tools" / "piper" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    voices = root / "tools" / "piper" / "voices"
    _write_voice(voices, "amy")   # configured default
    _write_voice(voices, "ryan")  # per-call override
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    monkeypatch.chdir(elsewhere)
    launcher = FakePiperLauncher("ok", wav=b"RIFF\x00\x00\x00\x00WAVE")
    monkeypatch.setattr("subprocess.Popen", launcher)
    service = VoiceSynthesisService()
    try:
        backend = PiperBackend(
            binary_path="tools/piper/piper",
            voice_model="amy",
            voices_dir="tools/piper/voices",
            service=service,
        )
        result = await backend.synthesize("hi", voice_override="ryan")
    finally:
        service.close()

    assert result is not None
    # The override voice resolved under the ROOT-anchored base, not the CWD.
    args = launcher.launched[0].args
    assert args[args.index("--model") + 1] == str((voices / "ryan.onnx").resolve())


@pytest.mark.asyncio
async def test_absolute_voices_dir_used_as_is(monkeypatch, tmp_path) -> None:
    """An ABSOLUTE ``voices_dir`` is used verbatim regardless of the anchor."""
    root = tmp_path / "probos_root"
    root.mkdir()
    monkeypatch.setattr(piper_backend, "_probos_root", lambda: root)
    binary = tmp_path / "bin" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    voices = tmp_path / "custom_voices"
    _write_voice(voices, "amy")
    launcher = FakePiperLauncher("ok", wav=b"RIFF\x00\x00\x00\x00WAVE")
    monkeypatch.setattr("subprocess.Popen", launcher)
    service = VoiceSynthesisService()
    try:
        backend = PiperBackend(
            binary_path=str(binary),
            voice_model="amy",
            voices_dir=str(voices),
            service=service,
        )
        result = await backend.synthesize("hi")
    finally:
        service.close()

    assert result is not None
    args = launcher.launched[0].args
    assert args[args.index("--model") + 1] == str((voices / "amy.onnx").resolve())
```

### 7.23 `tests/test_bf291_piper_voice_catalog.py` (M2: stale pins)

Pair 1 of 3:

SEARCH:
```python
    def _fake_select(_backend, _cfg):
        return _CaptureBackend()
```
REPLACE:
```python
    def _fake_select(_backend, _cfg, service=None):
        return _CaptureBackend()
```

Pair 2 of 3:

SEARCH:
```python
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda b, c: _CaptureBackend())

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))

    for evil in ("../../etc/passwd", "..\\..\\secrets", "voices/foo"):
```
REPLACE:
```python
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda b, c, service=None: _CaptureBackend())

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))

    for evil in ("../../etc/passwd", "..\\..\\secrets", "voices/foo"):
```

Pair 3 of 3:

SEARCH:
```python
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda b, c: _CaptureBackend())

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))
    resp = client.post("/api/avatars/tts", json={"text": "hello"})
```
REPLACE:
```python
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda b, c, service=None: _CaptureBackend())

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))
    resp = client.post("/api/avatars/tts", json={"text": "hello"})
```

### 7.24 `tests/test_bf892_spawn_env_guard.py` (M2: the launch moved)

SEARCH:
```python
    ("src/probos/audio/tts/piper_backend.py", "PiperBackend.synthesize._run_sync"): (1, "piper; text on stdin"),
```
REPLACE:
```python
    ("src/probos/audio/tts/resident.py", "PiperWorker._spawn"): (1, "resident piper --json-input; text as JSON lines on stdin (BF-918)"),
```

`_KNOWN_LAUNCH_FLOOR` (39) does not change: one launch was removed and one added.

### 7.25 `ui/src/audio/voiceChunking.ts` (M3)

SEARCH (lines 67-100: the doc comment from `/** AD-1071 — Drive a strictly-ordered queue of async side-effects.` through `runSentenceQueue`'s closing `}`):
```ts
/** AD-1071 — Drive a strictly-ordered queue of async side-effects.
 *
 *  Given ``items`` and a ``processOne`` that returns a Promise resolving when
 *  that item's work is DONE (e.g. its audio fired ``ended``), each item is
 *  processed only after the previous one resolves — the sequencing guarantee
 *  behind "next sentence starts after the previous one ends".
 *
 *  Honest-degrade: a ``processOne`` that throws is swallowed here (the
 *  side-effect owner logs) and the queue advances to the next item so one
 *  failed sentence never aborts the whole reply.
 *
 *  ``shouldContinue`` (optional) is checked before each item; returning false
 *  stops the queue early (used by voice.ts to cancel an in-flight reply when
 *  a newer one starts). Returns the number of items processed.
 *
 *  Pure control flow — the Audio/fetch side-effects live entirely inside the
 *  injected ``processOne``, so this is unit-testable with a stub. */
export async function runSentenceQueue(
  items: string[],
  processOne: (item: string, index: number) => Promise<void>,
  shouldContinue?: () => boolean,
): Promise<number> {
  let processed = 0;
  for (let i = 0; i < items.length; i++) {
    if (shouldContinue && !shouldContinue()) break;
    try {
      await processOne(items[i], i);
    } catch {
      // Honest-degrade: keep speaking the rest of the reply.
    }
    processed += 1;
  }
  return processed;
}
```
REPLACE:
```ts
/** BF-918 (#1626) — Drive an ordered queue that prepares ahead of what plays.
 *
 *  AD-1071's queue (`runSentenceQueue`, which this replaces) prepared item N+1 only
 *  after item N had finished PLAYING, so every sentence boundary cost a whole
 *  synthesis. Here:
 *   - `prepare` runs one item at a time, in order: item k starts once k-1 is
 *     prepared, and never more than `lookahead` items ahead of the one playing;
 *   - `play(k)` starts only after `play(k-1)` and `prepare(k)` resolved, so playback
 *     order is item order;
 *   - `shouldContinue` is checked before each play and before each prepare starts;
 *     once it is false nothing more plays, nothing more is prepared, and every
 *     prepared-but-unplayed result goes to `discard` (when it arrives, if it is
 *     still in flight);
 *   - a `prepare` that rejects counts as `null`; a `play` that throws is swallowed
 *     and the queue moves on (AD-1071's honest-degrade).
 *  Lookahead 0 is AD-1071's sequential queue. Returns the number of items played.
 *  Pure control flow: the Audio/fetch side-effects live in the injected callbacks. */
export async function runPrefetchQueue<P>(
  items: string[],
  prepare: (item: string, index: number) => Promise<P | null>,
  play: (prepared: P | null, item: string, index: number) => Promise<void>,
  shouldContinue: () => boolean,
  lookahead = 1,
  discard: (prepared: P | null) => void = () => {},
): Promise<number> {
  const pending: Array<Promise<P | null>> = [];
  const ensure = (k: number): void => {
    if (k >= items.length || pending[k] !== undefined) return;
    const previous: Promise<unknown> = k === 0 ? Promise.resolve(null) : pending[k - 1];
    pending[k] = previous
      .then(() => (shouldContinue() ? prepare(items[k], k) : null))
      .then((prepared) => prepared, () => null);
  };
  let consumed = 0;
  let played = 0;
  try {
    for (let i = 0; i < items.length; i += 1) {
      if (!shouldContinue()) break;
      ensure(i);
      const prepared = await pending[i];
      consumed = i + 1;
      if (!shouldContinue()) { discard(prepared); break; }
      for (let k = i + 1; k <= i + lookahead; k += 1) ensure(k);
      try {
        await play(prepared, items[i], i);
      } catch {
        // Honest-degrade: keep speaking the rest of the reply.
      }
      played += 1;
    }
  } finally {
    for (let k = consumed; k < pending.length; k += 1) {
      const p = pending[k];
      if (p !== undefined) void p.then(discard);
    }
  }
  return played;
}
```

### 7.26 `ui/src/audio/voice.ts` (M3)

Pair 1 of 8:

SEARCH:
```ts
import { injectLipSyncFrames } from './useLipSyncCapture';
import { splitIntoSentences, runSentenceQueue } from './voiceChunking';
```
REPLACE:
```ts
import { injectLipSyncFrames } from './useLipSyncCapture';
import type { LipSyncFrame } from './lipSyncCapture';
import { splitIntoSentences, runPrefetchQueue } from './voiceChunking';
```

Pair 2 of 8:

SEARCH:
```ts
  _ttsStatus = null;
  _ttsStatusInflight = null;
  _activeAudio = null;
  _activeUtteranceId = null;
}
```
REPLACE:
```ts
  _ttsStatus = null;
  _ttsStatusInflight = null;
  _activeAudio = null;
  _activeUtteranceId = null;
  _dispatchStartedAt = null;
  _sentenceEndedAt = null;
}
```

Pair 3 of 8:

SEARCH:
```ts
let _activeUtteranceId: number | null = null;
```
REPLACE:
```ts
let _activeUtteranceId: number | null = null;

/** BF-918 (#1626): sentences synthesized ahead of the one playing under AD-1071
 *  pipelining. One hides a sentence's synthesis behind the previous one's
 *  playback, and caps what a stopped reply can have spent at one sentence. */
const TTS_PREFETCH_LOOKAHEAD = 1;

/** BF-918 (#1626): User Timing measures for the live acceptance.
 *  `bf918:first-audio` runs from an utterance's dispatch to its audio actually
 *  playing; `bf918:sentence-gap` from one sentence's `ended` to the next
 *  sentence's `playing` in the same reply. Diagnostic only, capped, never thrown. */
const VOICE_MEASURE_CAP = 1000;
let _dispatchStartedAt: { id: number; at: number } | null = null;
let _sentenceEndedAt: { id: number; at: number } | null = null;

function _voiceNow(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

function _recordVoiceMeasure(name: string, start: number): void {
  try {
    if (typeof performance === 'undefined' || typeof performance.measure !== 'function') return;
    if (performance.getEntriesByName(name, 'measure').length >= VOICE_MEASURE_CAP) {
      performance.clearMeasures(name);
    }
    performance.measure(name, { start, end: performance.now() });
  } catch { /* Tier-2: timing is diagnostic only */ }
}

function _notePlaying(utterance_id: number): void {
  if (_dispatchStartedAt !== null && _dispatchStartedAt.id === utterance_id) {
    _recordVoiceMeasure('bf918:first-audio', _dispatchStartedAt.at);
    _dispatchStartedAt = null;
  }
  if (_sentenceEndedAt !== null && _sentenceEndedAt.id === utterance_id) {
    _recordVoiceMeasure('bf918:sentence-gap', _sentenceEndedAt.at);
  }
  _sentenceEndedAt = null;
}
```

Pair 4 of 8:

SEARCH:
```ts
      // sentence's 'end' fail `runSentenceQueue`'s shouldContinue and silence
```
REPLACE:
```ts
      // sentence's 'end' fail `runPrefetchQueue`'s shouldContinue and silence
```

Pair 5 of 8:

SEARCH:
```ts
  _activeUtteranceId = utterance_id;

  // Fast synchronous path: if fetch is unavailable OR the cached probe
```
REPLACE:
```ts
  _activeUtteranceId = utterance_id;
  // BF-918: first audio is measured from here, where the device becomes this utterance's.
  _dispatchStartedAt = { id: utterance_id, at: _voiceNow() };
  _sentenceEndedAt = null;

  // Fast synchronous path: if fetch is unavailable OR the cached probe
```

Pair 6 of 8:

SEARCH:
```ts
    if (status.sentence_pipelining_enabled) {
      const sentences = splitIntoSentences(text);
      if (sentences.length > 1) {
        await runSentenceQueue(
          sentences,
          (sentence) => _synthesizeAndPlay(sentence, profile, agent_id, emotion, utterance_id),
          () => _activeUtteranceId === utterance_id,
        );
        return;
      }
    }
```
REPLACE:
```ts
    // BF-918 (#1626): sentence N+1 is synthesized while sentence N plays (it used to
    // start only once N had ended, so every boundary cost a whole synthesis).
    // Playback stays strictly ordered; a stop drops what was prepared, unplayed.
    if (status.sentence_pipelining_enabled) {
      const sentences = splitIntoSentences(text);
      if (sentences.length > 1) {
        await runPrefetchQueue<PreparedSpeech>(
          sentences,
          (sentence) => _prepareServerSpeech(sentence, profile, emotion),
          (prepared, sentence) => _playPreparedSpeech(prepared, sentence, profile, agent_id, utterance_id),
          () => _activeUtteranceId === utterance_id,
          TTS_PREFETCH_LOOKAHEAD,
          _discardPreparedSpeech,
        );
        return;
      }
    }
```

Pair 7 of 8. The SEARCH is the whole of `_synthesizeAndPlay`, from `/** AD-738 / AD-1071: synthesize ONE utterance via the server Piper backend,` through its closing `}` before `/** AD-738: factor out per-agent modulation resolution` (lines 504-608 on this tree). The REPLACE is:
```ts
/** BF-918 (#1626): one server-synthesized utterance, ready to play. Its <audio> is
 *  made at prepare time, so the browser fetches the WAV while the previous sentence
 *  still plays; nothing listens to it until `_playPreparedSpeech`, so one that is
 *  discarded fires no event. `visemes`: the frames that came with the audio (a
 *  server without BF-918 ignores `defer_visemes`). `deferredVisemes`: the request
 *  for them, made at prepare time, when the server deferred them. */
interface PreparedSpeech {
  audio: HTMLAudioElement;
  visemes: LipSyncFrame[] | null;
  deferredVisemes: Promise<LipSyncFrame[]> | null;
}

/** AD-738 / AD-1071: synthesize ONE utterance via the server Piper backend, play
 *  it, and resolve when playback ENDS. The default single-call path (the full
 *  reply) uses it; the pipelined path drives the same two halves through
 *  `runPrefetchQueue`. Honest-degrade: on any failure the browser speaks THIS
 *  utterance instead. */
async function _synthesizeAndPlay(
  text: string,
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
  emotion: string | undefined,
  utterance_id: number,
): Promise<void> {
  const prepared = await _prepareServerSpeech(text, profile, emotion);
  await _playPreparedSpeech(prepared, text, profile, agent_id, utterance_id);
}

/** BF-918: the network half. POST the text and make (but do not play) its <audio>.
 *  Resolves `null` on any failure, which the play half turns into the browser
 *  fallback for this utterance. Never rejects. */
async function _prepareServerSpeech(
  text: string,
  profile: VoiceProfile | undefined,
  emotion: string | undefined,
): Promise<PreparedSpeech | null> {
  try {
    // AD-738e-1: pass v1 emotion name (resolved server-side) so the TTS
    // endpoint can apply per-emotion prosody. Omit when undefined — server
    // falls back to defaults. BF-291 / AD-738f: pass per-agent voice_name
    // when set; server resolves against tools/piper/voices/ and falls back
    // to the configured tts.voice_model on miss. BF-918: ask for the visemes
    // separately (POST /api/avatars/lipsync), so first audio does not wait for
    // rhubarb.
    const _body: { text: string; defer_visemes: boolean; emotion?: string; voice_name?: string } = {
      text,
      defer_visemes: true,
    };
    if (typeof emotion === 'string' && emotion.length > 0) {
      _body.emotion = emotion;
    }
    if (profile && typeof profile.voice_name === 'string' && profile.voice_name.length > 0) {
      _body.voice_name = profile.voice_name;
    }
    const resp = await fetch('/api/avatars/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_body),
    });
    if (!resp.ok) {
      _invalidateTtsStatus();
      return null;
    }
    const data = await resp.json();
    if (
      !data ||
      data.backend === 'disabled' ||
      typeof data.audio_attachment_id !== 'string' ||
      data.audio_attachment_id.length !== 64
    ) {
      // Server flipped to disabled — invalidate so the next call re-probes.
      _invalidateTtsStatus();
      return null;
    }
    const deferred = data.visemes_deferred === true;
    return {
      audio: new Audio(`/api/chat/attachments/${data.audio_attachment_id}`),
      visemes: deferred ? null : (Array.isArray(data.visemes) ? data.visemes : []),
      deferredVisemes: deferred ? _fetchDeferredVisemes(data.audio_attachment_id) : null,
    };
  } catch {
    _invalidateTtsStatus();
    return null;
  }
}

/** BF-918: the visemes the server deferred. Resolves `[]` on any failure, and the
 *  avatar keeps its heuristic schedule for that utterance (AD-721b). Never rejects. */
async function _fetchDeferredVisemes(attachmentId: string): Promise<LipSyncFrame[]> {
  try {
    const resp = await fetch('/api/avatars/lipsync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ attachment_id: attachmentId }),
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    return data && data.backend === 'rhubarb' && Array.isArray(data.frames) ? data.frames : [];
  } catch {
    return [];
  }
}

/** BF-918: the device half. Play a prepared utterance and resolve when it ENDS;
 *  `null` (its preparation failed) speaks it through the browser instead, as
 *  before. Each call fires its own balanced 'start'/'end' and injects its own
 *  visemes. */
async function _playPreparedSpeech(
  prepared: PreparedSpeech | null,
  text: string,
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
  utterance_id: number,
): Promise<void> {
  if (prepared === null) {
    _sentenceEndedAt = null; // a browser-spoken sentence is not a gap between two server ones
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
    return;
  }
  const { audio, visemes, deferredVisemes } = prepared;
  try {
    // Build a synthetic utterance object so existing 'start'/'end' listeners
    // (AD-718 / AD-721) keep firing the same shape. agent_id propagates.
    const synth = new SpeechSynthesisUtterance(text);
    _activeAudio = audio;
    const effective = _resolveEffectiveProfile(profile, agent_id);
    audio.volume = Math.max(0, Math.min(1, effective.volume ?? 0.8));
    audio.playbackRate = Math.max(0.25, Math.min(4.0, effective.rate ?? 0.95));
    try { (audio as any).preservesPitch = false; } catch { /* not supported */ }
    await new Promise<void>((resolve) => {
      let _settled = false;
      // BF-655: fireEnd=false is now used ONLY by the play()-reject path below,
      // where the 'play' event never fired so no 'start' was emitted — firing
      // no 'end' there keeps start/end balanced. Every path that DID emit
      // 'start' (ended / error / pause) fires exactly one terminal 'end'.
      const _finish = (fireEnd: boolean) => {
        if (_settled) return;
        _settled = true;
        if (_activeAudio === audio) _activeAudio = null;
        if (fireEnd) _fire({ type: 'end', agent_id, utterance: synth, source: 'server', utterance_id });
        resolve();
      };
      audio.addEventListener('play', () => _fire({ type: 'start', agent_id, utterance: synth, source: 'server', utterance_id }));
      audio.addEventListener('playing', () => _notePlaying(utterance_id));
      audio.addEventListener('ended', () => {
        _sentenceEndedAt = { id: utterance_id, at: _voiceNow() };
        _finish(true);
      });
      audio.addEventListener('error', () => _finish(true));
      // BF-655 (refines AD-1071): a newer speakResponse, or a barge-in (BF-918),
      // pauses _activeAudio to end this utterance. Fire the terminal 'end' (same
      // agent_id, source:'server'): the utterance is genuinely over, so the
      // modulation icon, avatar head-bob and PTT gate MUST reset. The _settled
      // guard above makes this a no-op if 'ended'/'error' already ran, so there is
      // no double-'end'. The pipelined queue stops on its own predicate, not this
      // event, and _finish still resolve()s.
      audio.addEventListener('pause', () => _finish(true));
      // AD-738: feed visemes directly to useLipSyncCapture via the injection setter.
      if (visemes !== null) {
        if (visemes.length > 0) {
          try {
            injectLipSyncFrames(visemes, agent_id);
          } catch {
            // ignore — visemes are best-effort
          }
        }
      } else if (deferredVisemes !== null) {
        // BF-918: until these arrive the avatar animates on the browser's
        // heuristic schedule (CrewVRM builds it at 'start'). Rhubarb's frames are
        // timed from the audio's start and sampled on its clock (BF-283), so late
        // frames still line up. Frames for a sentence that has ended, or been
        // replaced, are dropped.
        void deferredVisemes.then((frames) => {
          if (_settled || _activeAudio !== audio || frames.length === 0) return;
          try {
            injectLipSyncFrames(frames, agent_id);
          } catch {
            // ignore — visemes are best-effort
          }
        });
      }
      audio.play().then(undefined, () => {
        // play() rejected — fall back to browser for THIS utterance, resolve.
        if (_activeAudio === audio) _activeAudio = null;
        _speakBrowserFallback(text, profile, agent_id, utterance_id);
        _finish(false);
      });
    });
  } catch {
    _invalidateTtsStatus();
    _speakBrowserFallback(text, profile, agent_id, utterance_id);
  }
}

/** BF-918: drop a prepared utterance that will never play (its reply was stopped). */
function _discardPreparedSpeech(prepared: PreparedSpeech | null): void {
  if (prepared === null) return;
  try {
    prepared.audio.removeAttribute('src');
    prepared.audio.load();
  } catch { /* best effort: an unplayed element holds no listener and fires no event */ }
}
```

Pair 8 of 8:

SEARCH:
```ts
  _activeUtteranceId = null;
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
}
```
REPLACE:
```ts
  _activeUtteranceId = null;
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  // BF-918 (#1626): the server path too. Its <audio> used to play on after a
  // barge-in (only the browser engine was cancelled). Pausing fires that
  // utterance's one terminal 'end' (BF-655), and the sentence queue, whose
  // predicate is already false, stops and drops what it had prepared.
  if (_activeAudio !== null) {
    try { _activeAudio.pause(); } catch { /* BF-918: barge-in silences server audio too */ }
    _activeAudio = null;
  }
}
```

### 7.27 `ui/src/audio/__tests__/voiceChunking.test.ts` (M3)

Pair 1 of 2:

SEARCH:
```ts
import { splitIntoSentences, runSentenceQueue } from '../voiceChunking';
```
REPLACE:
```ts
import { splitIntoSentences, runPrefetchQueue } from '../voiceChunking';
```

Pair 2 of 2. The SEARCH is the whole `describe('AD-1071 runSentenceQueue', () => {` block, through its closing `});` at the end of the file (lines 88-165). The REPLACE is:
```ts
describe('BF-918 runPrefetchQueue', () => {
  const flush = async (): Promise<void> => {
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };

  function harness() {
    const events: string[] = [];
    const preps: Array<() => void> = [];
    const ends: Array<() => void> = [];
    const prepare = (item: string): Promise<string> =>
      new Promise<string>((resolve) => {
        events.push(`prep:${item}`);
        preps.push(() => resolve(item));
      });
    const play = (_p: string | null, item: string): Promise<void> =>
      new Promise<void>((resolve) => {
        events.push(`play:${item}`);
        ends.push(() => { events.push(`end:${item}`); resolve(); });
      });
    return { events, preps, ends, prepare, play };
  }

  it('Q1 lookahead 0: one item at a time, in order (the AD-1071 queue)', async () => {
    const events: string[] = [];
    const ends: Array<() => void> = [];
    const prepare = async (item: string): Promise<string> => { events.push(`prep:${item}`); return item; };
    const play = (_p: string | null, item: string): Promise<void> =>
      new Promise<void>((resolve) => {
        events.push(`play:${item}`);
        ends.push(() => { events.push(`end:${item}`); resolve(); });
      });
    const done = runPrefetchQueue(['a', 'b', 'c'], prepare, play, () => true, 0);
    await flush();
    expect(events).toEqual(['prep:a', 'play:a']);
    ends[0]();
    await flush();
    expect(events).toEqual(['prep:a', 'play:a', 'end:a', 'prep:b', 'play:b']);
    ends[1]();
    await flush();
    ends[2]();
    expect(await done).toBe(3);
    expect(events).toEqual(['prep:a', 'play:a', 'end:a', 'prep:b', 'play:b', 'end:b', 'prep:c', 'play:c', 'end:c']);
  });

  it('Q2 lookahead 1: the next item is prepared while the current one plays, and plays only after it', async () => {
    const h = harness();
    const done = runPrefetchQueue(['a', 'b', 'c'], h.prepare, h.play, () => true, 1);
    await flush();
    expect(h.events).toEqual(['prep:a']); // nothing else until a is prepared
    h.preps[0]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'play:a', 'prep:b']);
    h.preps[1]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'play:a', 'prep:b']); // b is ready, a still plays, c waits
    h.ends[0]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'play:a', 'prep:b', 'end:a', 'play:b', 'prep:c']);
    h.preps[2]();
    h.ends[1]();
    await flush();
    h.ends[2]();
    expect(await done).toBe(3);
  });

  it('Q3 a stop drops every prepared item that never played, including one still in flight', async () => {
    const h = harness();
    let go = true;
    const discarded: Array<string | null> = [];
    const done = runPrefetchQueue(['a', 'b', 'c'], h.prepare, h.play, () => go, 1, (p) => { discarded.push(p); });
    await flush();
    h.preps[0]();
    await flush(); // a plays, b is being prepared
    go = false;
    h.ends[0]();
    expect(await done).toBe(1);
    expect(discarded).toEqual([]); // b is still in flight
    h.preps[1]();
    await flush();
    expect(discarded).toEqual(['b']);
    expect(h.events).not.toContain('play:b');
    expect(h.events).not.toContain('prep:c');
  });

  it('Q4 a stop found after an item is prepared discards it instead of playing it', async () => {
    let go = true;
    const discarded: Array<string | null> = [];
    const play = vi.fn(async () => {});
    const prepare = async (item: string): Promise<string> => { if (item === 'a') go = false; return item; };
    expect(await runPrefetchQueue(['a', 'b'], prepare, play, () => go, 1, (p) => { discarded.push(p); })).toBe(0);
    expect(discarded).toEqual(['a']);
    expect(play).not.toHaveBeenCalled();
  });

  it('Q5 a rejected prepare plays as null, and a throwing play does not stop the queue', async () => {
    const seen: Array<string | null> = [];
    const prepare = async (item: string): Promise<string> => {
      if (item === 'b') throw new Error('synth failed');
      return item;
    };
    const play = async (p: string | null, item: string): Promise<void> => {
      seen.push(p);
      if (item === 'a') throw new Error('play failed');
    };
    expect(await runPrefetchQueue(['a', 'b', 'c'], prepare, play, () => true, 1)).toBe(3);
    expect(seen).toEqual(['a', null, 'c']);
  });

  it('Q6 nothing is prepared or played when stopped from the start, or for an empty list', async () => {
    const prepare = vi.fn(async (item: string) => item);
    const play = vi.fn(async () => {});
    expect(await runPrefetchQueue(['a'], prepare, play, () => false, 1)).toBe(0);
    expect(await runPrefetchQueue([], prepare, play, () => true, 1)).toBe(0);
    expect(prepare).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });
});
```

### 7.28 `ui/src/audio/__tests__/voice.pipelining.test.tsx` (M3: stale pins)

Pair 1 of 3:

SEARCH:
```ts
async function _flush(): Promise<void> {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}
```
REPLACE:
```ts
async function _flush(): Promise<void> {
  // BF-918: prefetching the next sentence adds microtask hops (harness only).
  for (let i = 0; i < 30; i++) await Promise.resolve();
}
```

Pair 2 of 3:

SEARCH:
```ts
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();

    // First-audio wins: only the FIRST sentence is synthesized so far.
    expect(posted).toEqual(['One.']);
    expect(createdAudios.length).toBe(1);

    // Finishing sentence[0] triggers sentence[1] — and only then.
    createdAudios[0].end();
    await _flush();
    expect(posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.length).toBe(2);

    createdAudios[1].end();
    await _flush();
    expect(posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.length).toBe(3);

    createdAudios[2].end();
```
REPLACE:
```ts
    voiceMod.speakResponse('One. Two. Three.');
    await _flush();

    // BF-918: first audio still needs only the FIRST sentence; the second is
    // synthesized while the first plays (it used to wait for the first to end).
    expect(posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false]);

    // Finishing sentence[0] plays sentence[1] and prefetches sentence[2].
    createdAudios[0].end();
    await _flush();
    expect(posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, true, false]);

    createdAudios[1].end();
    await _flush();
    expect(createdAudios.map((a) => a.played)).toEqual([true, true, true]);

    createdAudios[2].end();
```

Pair 3 of 3:

SEARCH:
```ts
    voiceMod.speakResponse('Alpha. Bravo. Charlie.');
    await _flush();
    expect(posted).toEqual(['Alpha.']);
    // Advance past sentence[0].
    createdAudios[0].end();
    await _flush();
    // Sentence[1] synth failed (fell back to browser) and resolved immediately,
    // so the queue already advanced to sentence[2] without a new 'ended'.
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
```
REPLACE:
```ts
    voiceMod.speakResponse('Alpha. Bravo. Charlie.');
    await _flush();
    // BF-918: sentence[1] is prefetched (and fails) while sentence[0] plays;
    // its browser fallback waits for its turn.
    expect(posted).toEqual(['Alpha.', 'Bravo.']);
    expect(speakCalls.length).toBe(0);
    // Advance past sentence[0].
    createdAudios[0].end();
    await _flush();
    // Sentence[1] fell back to the browser in its turn and resolved at once,
    // so the queue already moved on to sentence[2] without a new 'ended'.
    expect(speakCalls.length).toBe(1);
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
```

### 7.29 `ui/src/audio/__tests__/voice.perEmotion.test.tsx` (M3: stale pins)

Pair 1 of 2:

SEARCH:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({
      text: 'hello',
      emotion: 'concerned',
    });
```
REPLACE:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({
      text: 'hello',
      emotion: 'concerned',
      defer_visemes: true, // BF-918
    });
```

Pair 2 of 2:

SEARCH:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({ text: 'hello' });
```
REPLACE:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({ text: 'hello', defer_visemes: true }); // BF-918
```

### 7.30 New file: `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx` (M3)

```tsx
/** BF-918 (#1626): AD-1071 pipelining prefetches the next sentence while one plays;
 *  a stop drops what was prefetched; deferred visemes reach the sentence playing;
 *  barge-in silences Piper. Real voice.ts, real queue, real lip-sync registry; only
 *  Audio, SpeechSynthesis, fetch and (in one case) performance are fakes. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

let createdUtterances: FakeUtterance[] = [];
let speakCalls: unknown[] = [];
let createdAudios: FakeAudio[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
    createdUtterances.push(this);
  }
}

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  played = false;
  discarded = false;
  private _listeners: Record<string, Array<() => void>> = {};
  pause = vi.fn(() => { this.emit('pause'); });
  play = vi.fn(async () => { this.played = true; this.emit('play'); });
  removeAttribute = vi.fn(() => { this.discarded = true; });
  load = vi.fn();
  constructor(src: string) {
    this.src = src;
    createdAudios.push(this);
  }
  addEventListener(ev: string, fn: () => void): void {
    (this._listeners[ev] ||= []).push(fn);
  }
  emit(ev: string): void {
    for (const fn of (this._listeners[ev] || [])) fn();
  }
  end(): void { this.emit('ended'); }
}

const fakeVoices: unknown[] = [{ name: 'Microsoft Aria Online (Natural)', lang: 'en-US' }];

function _installGlobals(): void {
  createdUtterances = [];
  speakCalls = [];
  createdAudios = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).Audio = FakeAudio;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: unknown) => speakCalls.push(u)),
    getVoices: () => fakeVoices,
    addEventListener: vi.fn(),
  };
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  }
}

async function _flush(): Promise<void> {
  for (let i = 0; i < 40; i++) await Promise.resolve();
}

interface Plan {
  pipelining: boolean;
  deferVisemes?: boolean;
  inlineVisemes?: unknown[];
  holdTts?: number[];
  holdLipsync?: boolean;
  framesFor?: (attachmentId: string) => unknown[];
}

function _makeFetch(plan: Plan) {
  const posted: string[] = [];
  const bodies: Array<Record<string, unknown>> = [];
  const lipsyncIds: string[] = [];
  const held: Array<() => void> = [];
  let nth = 0;
  const fetchMock = vi.fn(async (url: string, opts?: { body?: string }): Promise<any> => {
    if (url.endsWith('/api/avatars/tts/status')) {
      return { ok: true, json: async () => ({ enabled: true, backend: 'piper', sentence_pipelining_enabled: plan.pipelining }) };
    }
    if (url === '/api/avatars/tts') {
      const body = JSON.parse(opts?.body ?? '{}');
      bodies.push(body);
      posted.push(body.text);
      nth += 1;
      const sha = String.fromCharCode(97 + nth).repeat(64);
      const response = {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes: plan.inlineVisemes ?? [],
          visemes_deferred: plan.deferVisemes === true,
          duration_ms: 0,
        }),
      };
      if (plan.holdTts?.includes(nth)) return new Promise((resolve) => { held.push(() => resolve(response)); });
      return response;
    }
    if (url === '/api/avatars/lipsync') {
      const id = String(JSON.parse(opts?.body ?? '{}').attachment_id);
      lipsyncIds.push(id);
      const response = { ok: true, json: async () => ({ backend: 'rhubarb', frames: plan.framesFor ? plan.framesFor(id) : [] }) };
      if (plan.holdLipsync) return new Promise((resolve) => { held.push(() => resolve(response)); });
      return response;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
  return {
    fetchMock, posted, bodies, lipsyncIds,
    release: (): void => { const next = held.shift(); if (next) next(); },
  };
}

const frame = (viseme: string) => [{ time: 0, duration: 0.1, viseme }];

async function _voice() {
  const voiceMod = await import('../voice');
  voiceMod._resetTtsStatusForTests();
  return voiceMod;
}

beforeEach(() => { _installGlobals(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cleanup(); });

describe('BF-918 prefetch (AD-1071 pipelining on)', () => {
  it('P1 synthesizes the next sentence while one plays, and plays them in order', async () => {
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();

    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    expect(f.posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false]);
    expect(f.bodies.every((b) => b.defer_visemes === true)).toBe(true);

    createdAudios[0].end();
    await _flush();
    expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, true, false]);

    createdAudios[1].end();
    await _flush();
    expect(createdAudios.map((a) => a.played)).toEqual([true, true, true]);
    createdAudios[2].end();
    await _flush();
    expect(f.posted.length).toBe(3);
  });

  it('P2 a stop during sentence one silences it and drops the prefetched sentence two, which fires no start', async () => {
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const events: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { events.push(`${e.type}:${e.utterance?.text ?? ''}`); });
    try {
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      expect(createdAudios.length).toBe(2);

      voiceMod.stopSpeaking();
      await _flush();

      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(createdAudios[1].played).toBe(false);
      expect(createdAudios[1].discarded).toBe(true);
      expect(f.posted).toEqual(['One.', 'Two.']);
      expect(events.filter((e) => e.startsWith('start'))).toEqual(['start:One.']);
      expect(events.filter((e) => e.startsWith('end'))).toEqual(['end:One.']);
    } finally {
      off();
    }
  });

  it('P3 a sentence still being synthesized when the reply stops is never played', async () => {
    const f = _makeFetch({ pipelining: true, holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const starts: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { if (e.type === 'start') starts.push(e.utterance?.text ?? ''); });
    try {
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      expect(f.posted).toEqual(['One.', 'Two.']);
      expect(createdAudios.length).toBe(1); // Two's response has not arrived

      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      expect(createdAudios.length).toBe(2); // made when its response arrived...
      expect(createdAudios[1].played).toBe(false); // ...and never played
      expect(createdAudios[1].discarded).toBe(true);
      expect(starts).toEqual(['One.']);
    } finally {
      off();
    }
  });
});

describe('BF-918 deferred visemes', () => {
  it('P4 fetches them for the stored audio and injects them while it plays; late ones are dropped', async () => {
    const f = _makeFetch({
      pipelining: false, deferVisemes: true, holdLipsync: true,
      framesFor: (id) => frame(id[0] === 'b' ? 'aa' : 'oh'),
    });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() => useLipSyncCapture({ enabled: true, agentId: 'agent-7' }));

    voiceMod.speakResponse('hi', undefined, 'agent-7');
    await act(async () => { await _flush(); });
    expect(f.lipsyncIds).toEqual(['b'.repeat(64)]);
    expect(result.current.frames).toEqual([]); // the heuristic schedule animates meanwhile
    await act(async () => { f.release(); await _flush(); });
    expect(result.current.frames).toEqual(frame('aa'));

    createdAudios[0].end();
    await act(async () => { await _flush(); });
    voiceMod.speakResponse('bye', undefined, 'agent-7');
    await act(async () => { await _flush(); });
    expect(f.lipsyncIds.length).toBe(2);
    createdAudios[1].end(); // its audio ends before its frames arrive
    await act(async () => { f.release(); await _flush(); });
    expect(result.current.frames).toEqual(frame('aa')); // 'oh' was dropped
  });

  it('P5 an older server that sends visemes inline still has them injected, with no lipsync request', async () => {
    const f = _makeFetch({ pipelining: false, inlineVisemes: frame('ee') });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() => useLipSyncCapture({ enabled: true, agentId: 'agent-7' }));

    voiceMod.speakResponse('hi', undefined, 'agent-7');
    await act(async () => { await _flush(); });

    expect(result.current.frames).toEqual(frame('ee'));
    expect(f.lipsyncIds).toEqual([]);
  });

  it('P6 pipelined: each sentence gets its own deferred visemes, the prefetched one at its own play', async () => {
    const f = _makeFetch({
      pipelining: true, deferVisemes: true,
      framesFor: (id) => frame(id[0] === 'b' ? 'aa' : 'ih'),
    });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() => useLipSyncCapture({ enabled: true, agentId: 'agent-7' }));

    voiceMod.speakResponse('One. Two.', undefined, 'agent-7');
    await act(async () => { await _flush(); });
    expect(result.current.frames).toEqual(frame('aa'));
    expect(f.lipsyncIds).toEqual(['b'.repeat(64), 'c'.repeat(64)]); // the second fetched while the first plays
    expect(createdAudios[1].played).toBe(false);

    await act(async () => { createdAudios[0].end(); await _flush(); });

    expect(createdAudios[1].played).toBe(true);
    expect(result.current.frames).toEqual(frame('ih'));
  });
});

describe('BF-918 stop and timing', () => {
  it('P7 stopSpeaking silences server audio on the single-call path and fires its one end', async () => {
    const f = _makeFetch({ pipelining: false });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const ends: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { if (e.type === 'end') ends.push(e.utterance?.text ?? ''); });
    try {
      voiceMod.speakResponse('One. Two.');
      await _flush();
      voiceMod.stopSpeaking();
      await _flush();
      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(ends).toEqual(['One. Two.']);
    } finally {
      off();
    }
  });

  it('P8 records first audio and the gap between sentences as User Timing measures', async () => {
    const measure = vi.fn();
    vi.stubGlobal('performance', {
      now: () => Date.now(),
      measure,
      getEntriesByName: () => [],
      clearMeasures: vi.fn(),
    });
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();

    voiceMod.speakResponse('One. Two.');
    await _flush();
    createdAudios[0].emit('playing');
    expect(measure.mock.calls.map((c) => c[0])).toEqual(['bf918:first-audio']);
    createdAudios[0].end();
    await _flush();
    createdAudios[1].emit('playing');
    expect(measure.mock.calls.map((c) => c[0])).toEqual(['bf918:first-audio', 'bf918:sentence-gap']);
  });
});
```

## 8. Tracking

Each pair anchors on a line that occurs once in its file and that BF-914's and AD-1347's entries do not change: `PROGRESS.md`'s title line, and the heading `### Explicit delegation models, plain-id profile models and the orchestrator's model guard` in `DECISIONS.md` (line 674 on this tree). The tracker entries go in M3's commit, or in a docs-only commit after it. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-918 (2026-10-23), #1626 -- a spoken reply's first audio and sentence gaps: the next sentence is synthesized while one plays, Piper stays resident, rhubarb is off the first-audio path, voice work has its own executor, and spoken audio expires.** S1: `runPrefetchQueue` (`ui/src/audio/voiceChunking.ts`) replaces the AD-1071 sequential queue: sentence N+1 is synthesized while N plays, playback stays ordered, and a stop drops prefetched audio unplayed. The client asks for deferred visemes and fetches them from `/api/avatars/lipsync`. `stopSpeaking` now also pauses Piper audio (barge-in used to let it play on). Two User Timing measures were added (`bf918:first-audio`, `bf918:sentence-gap`). S2: new `probos/audio/tts/resident.py` (`VoiceSynthesisService`, `runtime.voice_synthesis`) holds one `piper --json-input` process per voice and prosody set (at most 4), on a 4-thread voice executor that admits 16 requests (more degrade to the browser). Rhubarb and ffmpeg run on the same executor, and the route logs per-stage timings. S3: a new origin `tts_audio`, deleted after `attachments.tts_audio_retention_seconds` (900) and evicted first under the size cap; a more durable write of the same bytes keeps its origin. `scripts/tts_audio_inventory.py` inventories the 1,126 legacy WAVs (read-only; it deletes only on the Captain's `--delete --confirm N`). New: `tests/test_bf918_tts_retention.py`, `tests/test_bf918_tts_latency.py`, `tests/fixtures/fake_piper.py`, `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`. #1626 stays open for the Captain's live measurement and the sweep decision. The contract is `prompts/bf-918-tts-first-audio-latency.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-918 -- A spoken reply's first audio and the gaps between its sentences (2026-10-23, #1626)

- *Scope.* `audio/tts/resident.py` (new), `piper_backend.py`, `audio/tts/__init__.py`, `avatars/rhubarb_backend.py`, `routers/avatars.py`, `runtime.py`, `startup/shutdown.py`, `startup/finalize.py`, `attachments/{store,filesystem_store,reaper}.py`, `config_models/integrations.py`, `scripts/tts_audio_inventory.py` (new), `ui/src/audio/{voice,voiceChunking}.ts`. Contract: `prompts/bf-918-tts-first-audio-latency.md`. Tier HIGH for S3.
- *D2 (resident synthesizer).* One `piper --json-input` process per (binary, model, prosody set). Piper fixes prosody per process, and its JSON lines carry only text, output_file and speaker (upstream `main.cpp`; wyoming-piper does the same). At most 4 processes; the least recently used idle one is evicted. Requests write ASCII JSON lines; WAVs go to files (BF-282); `Popen` in a thread (BF-280); `trusted_command_env()` (BF-892); stderr to a file. A per-request timer kills a hung process and the next request starts another. Rejected: in-process synthesis (no package installed; piper1-gpl is GPL-3).
- *D3 (visemes).* A client that sends `defer_visemes: true` gets audio without rhubarb (`visemes_deferred: true`) and fetches the visemes from the existing `/api/avatars/lipsync`; the heuristic schedule runs until they arrive. Other clients are unchanged. Rejected: Piper phoneme timing (not emitted), and overlapping rhubarb with the store write.
- *D4 (executor).* `VoiceSynthesisService` is owned by the runtime (built in `__init__`, closed in `shutdown()`): 4 threads, 16 admitted requests; refusal degrades. Not `set_default_executor` (global, and bounds nothing).
- *D5 (retention).* Origin `tts_audio`, first in both the durability and the eviction order; TTL 900 s. The store's upgrade rule already existed (#1626's "keeps the first origin" was wrong). The legacy WAVs are handled by a dry-run tool; deleting them is the Captain's decision.
- *D7.* `stopSpeaking` pauses Piper audio; the AD-1291 arbiter and BF-655's one terminal 'end' are unchanged.
- *Reversal.* Revert the commits. `tts_audio` index entries then belong to no known origin and are never swept or evicted (the safe direction). Resident processes end with the runtime.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916 precedent).

## 9. What this does NOT change

- `tts.sentence_pipelining_enabled` stays default-off, and the Captain's `config/system.yaml` is not touched. The status route is unchanged.
- The browser backend makes zero HTTP calls per utterance (Captain decision #9).
- The AD-1291 arbiter, its classes, `flushSpeechQueue`, `SPEECH_JOIN_TIMEOUT_MS`, BF-764, BF-767 and BF-655 balance are unchanged.
- `splitIntoSentences` is unchanged.
- The `/api/avatars/lipsync` contract is unchanged, and so is the browser-capture lip-sync path (`useLipSyncCapture`, `uploadAudioForLipSync`).
- The prosody table, voice resolution, AD-1025 anchoring and BF-291 overrides are unchanged.
- Rhubarb's flags, the ffmpeg conversion, `probe_version` and `is_available` (default pool, used by the doctor) are unchanged.
- The `.index.json` format, every other origin's retention, `agent_artifact` (never LRU-evicted) and `max_store_bytes` are unchanged.
- Out of scope: streaming the LLM reply (#1130), compressed or streamed audio, and a voice mode. The legacy WAVs are not deleted by any build, test or gate.

## 10. Mutation rows (21 Python and 4 TypeScript; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row on the applied tree after an unmutated baseline run passes, and restore each file before the next row.

Python campaign command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_tts_retention.py tests/test_bf918_tts_latency.py tests/test_bf892_spawn_env_guard.py -n 0 -x -q
```

The TypeScript rows (TS*) are run by hand. The command, from `ui/`, is `npx vitest run src/audio/__tests__/voiceChunking.test.ts src/audio/__tests__/voice.prefetch.bf918.test.tsx`.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| R1 | `src/probos/attachments/reaper.py` | `"tts_audio",  # BF-918: spoken audio is played once, so it goes first` | `"perception_frame",` | `test_lru_evicts_tts_audio_first` |
| R2 | `src/probos/attachments/reaper.py` | `("tts_audio", int(self._attachments_cfg.tts_audio_retention_seconds)),` | `("tts_audio", 0),` | `test_reaper_deletes_tts_audio_past_its_ttl_and_nothing_else` |
| R4 | `src/probos/attachments/filesystem_store.py` | `"tts_audio",  # BF-918: least durable; any other write of the same bytes wins` | `"perception_frame",` | `test_a_chat_upload_of_the_same_bytes_upgrades_tts_audio` (the upgrade check raises `ValueError`, so the origin stays `tts_audio`) |
| R5 | `src/probos/attachments/store.py` | `"tts_audio",  # BF-918 (#1626): spoken reply audio, deleted by age (attachments.tts_audio_retention_seconds)` | `"perception_frame",` | `test_tts_audio_is_a_known_origin` (coerced, with a warning) |
| R6 | `src/probos/routers/avatars.py` | `await store.write(attachment_id, result.audio_bytes, result.mime, origin="tts_audio")` | `await store.write(attachment_id, result.audio_bytes, result.mime)` | `test_route_stores_speech_as_tts_audio` |
| R7 | `src/probos/routers/avatars.py` | `defer_visemes = payload.get("defer_visemes") is True` | `defer_visemes = False` | `test_deferred_visemes_come_from_the_lipsync_route_for_the_stored_audio` |
| R8 | `src/probos/routers/avatars.py` | `if defer_visemes:` | `if True:` | `test_a_client_that_does_not_ask_keeps_inline_visemes` |
| R10 | `src/probos/routers/avatars.py` | `executor=voice_service.executor,` | `executor=None,` | `test_lipsync_route_runs_rhubarb_on_the_voice_executor` |
| R11 | `src/probos/startup/finalize.py` | `tts_ttl_enabled = int(getattr(attachments_cfg, "tts_audio_retention_seconds", 0)) > 0` | `tts_ttl_enabled = False` | `test_reaper_starts_for_the_tts_ttl_alone` |
| R12 | `src/probos/audio/tts/resident.py` | `"--json-input",` | `"--quiet",` | `test_one_resident_process_serves_consecutive_requests` |
| R13 | `src/probos/audio/tts/resident.py` | `if not self.alive:` | `if True:` | `test_one_resident_process_serves_consecutive_requests` (two launches) |
| R14 | `src/probos/audio/tts/resident.py` | `timer.start()` | `pass` | `test_a_hung_process_is_killed_at_the_timeout_and_replaced` (no kill; the fake answers end of file only after 10 s, logged as an exit) |
| R15 | `src/probos/audio/tts/resident.py` | `async with lock:` | `if True:` | `test_overlapping_requests_share_one_process_one_at_a_time` |
| R16 | `src/probos/audio/tts/resident.py` | `if self._closed or self._in_flight >= self._max_in_flight:` | `if self._closed:` | `test_saturation_refuses_and_degrades_instead_of_queueing` |
| R17 | `src/probos/audio/tts/resident.py` | `self._resident.move_to_end(key)` | `pass` | `test_the_least_recently_used_idle_process_makes_room` |
| R18 | `src/probos/audio/tts/resident.py` | `env=trusted_command_env(),` | `env=None,` | `test_one_resident_process_serves_consecutive_requests`; BF-892 guard |
| R19 | `src/probos/audio/tts/resident.py` | `future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout)` | `future = loop.run_in_executor(None, worker.synthesize_blocking, text, timeout)` | `test_voice_work_does_not_queue_behind_a_busy_default_pool` |
| R21 | `src/probos/audio/tts/piper_backend.py` | `noise_scale=_noise_scale,` | `noise_scale=self._noise_scale,` | `test_each_prosody_set_gets_its_own_process` |
| R22 | `src/probos/startup/shutdown.py` | `voice_service.close()` | `pass` | `test_the_runtime_owns_one_voice_service_and_shutdown_closes_it` |
| R24 | `scripts/tts_audio_inventory.py` | `if args.confirm != len(inventory.candidates):` | `if False:` | `test_delete_refuses_without_the_matching_count` |
| R25 | `scripts/tts_audio_inventory.py` | `if sha in referenced:` | `if False:` | `test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing` |
| TS1 | `ui/src/audio/voiceChunking.ts` | `for (let k = i + 1; k <= i + lookahead; k += 1) ensure(k);` | `for (let k = i + 1; k <= i; k += 1) ensure(k);` | run by hand: voiceChunking Q2; prefetch P1 |
| TS3 | `ui/src/audio/voiceChunking.ts` | `if (p !== undefined) void p.then(discard);` | `if (false) void p.then(discard);` | run by hand: voiceChunking Q3; prefetch P3 |
| TS5 | `ui/src/audio/voice.ts` | `if (_settled \|\| _activeAudio !== audio \|\| frames.length === 0) return;` | `if (frames.length === 0) return;` | run by hand: prefetch P4 |
| TS6 | `ui/src/audio/voice.ts` | `try { _activeAudio.pause(); } catch { /* BF-918: barge-in silences server audio too */ }` | `// BF-918 mutant: no pause` | run by hand: prefetch P7, P2 |

## 11. Verified Against Codebase (2026-10-23, worktree `bf918-consult` at `origin/main` `eea6e2f4`)

**The issue's citations, re-checked:**

| Location on this tree | What it shows |
|---|---|
| `voiceChunking.ts:84-100` | `runSentenceQueue`; `for`; `await processOne(items[i], i)` |
| `voice.ts:487-495` | `if (status.sentence_pipelining_enabled)` … `runSentenceQueue(` … `_synthesizeAndPlay` |
| `voice.ts:504-608` | `_synthesizeAndPlay`; `'play'` at `:575`; inject at `:590-592` |
| `voice.ts:455-460, 493` | the ownership predicate |
| `voice.ts:718-727` | `stopSpeaking`: `flushSpeechQueue('barge-in')`, `_activeUtteranceId = null`, `speechSynthesis.cancel()` (no audio pause) |
| `experience.py:768` | `sentence_pipelining_enabled: bool = False` |
| `piper_backend.py:197-201` | the `_ov.get(...)` prosody lines |
| `piper_backend.py:223, 264` | `subprocess.Popen(`, `run_in_executor(` / `None, _run_sync,` |
| `audio/tts/__init__.py:16-40` | `select_backend` builds `PiperBackend(` |
| `avatars.py:259-261, 280, 287-295, 304-310` | as cited |
| `rhubarb_backend.py:194, 269, 386-387, 405-407` | `run_in_executor(None, …)`, `-r phonetic`, `--threads` |
| `store.py:16-23, 46, 51-52` | as cited |
| `filesystem_store.py:91-98, 179-187, 212, 252-255` | the upgrade rule exists; **corrects the issue's `:214` claim** |
| `reaper.py:30-36, 146-169` | as cited |
| `d:\ProbOS\config\system.yaml:1737, 1739, 1743, 1745, 1752, 1753` | as cited |

None moved.

**Consumers, by grep:**
- `Grep "audio_attachment_id|sentence_pipelining_enabled|runSentenceQueue|_synthesizeAndPlay|_activeUtteranceId|_speakGeneration|api/avatars/tts" ui/src` found 14 files: `voice.ts` (31), `voiceChunking.ts` (2), `useLipSyncCapture.ts` (1), and `__tests__` files `voice.serverTts` (17), `voice.pipelining` (9), `voiceChunking` (6), `voice.balancedEnd` (4), `voice.perEmotion` (3), `voice.testGate` (2), plus the ProfileChatTab `ad1291.e2e`, `bf764`, `bf767`, `groupReplyIdentity` and `issue1340` tests. All the ProfileChatTab ones are browser-backend status probes, or a comment.
- `Grep "duration_ms|data\.mime|\.visemes\b" ui/src (non-test)` found the TTS response read only at `voice.ts:590-592` (`visemes`); `mime` and `duration_ms` are not read.
- `Grep "avatars/tts|avatars/lipsync"` over `src`, `scripts`, `ui/e2e` and `ui/src` found only the files above, plus `api.py:262` (the router include) and docstrings.
- `Grep "PiperBackend|select_backend|generate_visemes|ATTACHMENT_ORIGINS|_LRU_EVICTION_ORDER" src` found the production sites listed in §5. The only caller of `select_backend` is `avatars.py:260`.
- `Grep "probos\.audio\.tts\.select_backend" tests` found `test_ad738_piper_tts.py:465, 508, 544, 589`, `test_ad738e_1…:202` and `test_bf291…:190, 211, 237`. The 2-argument stubs are updated, except `:465`, which is never called because the browser path returns first.
- `Grep "PiperBackend\(|subprocess\.Popen|communicate"` in the ad738e_1, bf291, ad1025, ad1071, ad1192 and ad1270e2c tests found the stale pins in §7.20 to §7.23.
- `Grep "_LRU_EVICTION_ORDER|ATTACHMENT_ORIGINS|_ORIGIN_DURABILITY|_sweep_age_ttl|frame_retention_seconds" tests` found `test_ad1192…:24, 2883` (iterates; fine), `test_attachment_reaper.py` (real configs; fine) and `test_bf666` (a VisionConsumer config, not the reaper).
- `Grep "AttachmentReaper\(" tests`: every call passes a real `AttachmentsConfig`.
- `Grep "piper_backend|avatars\.py|…"` in tests found `test_bf892_spawn_env_guard.py:87` (the inventory key, §7.24), `test_ad1025b` (comment only), and `test_ad1344…`, whose census scope (`:741-745`) does not include `audio/`.
- `Grep "\?raw" ui/src`: none of them read `voice.ts`, `voiceChunking.ts` or `useLipSyncCapture.ts`.
- `test_bf292…:101` reads `generate_visemes`' source for `_SUPPORTED_SUFFIXES = {".wav", ".ogg"}`; that line is unchanged.
- `test_issue1419…:1373-1397` takes a census of the `with steps(...)` labels in `shutdown()`. §7.17 uses a plain call, so the census is unchanged.

**Anchors, each one occurrence:**

| Anchor | Location |
|---|---|
| `runtime.py:821-822` | `from probos.execution.long_runs import LongRunService` / `self.execution_long_runs = LongRunService()` |
| `shutdown.py:21` | the `long_runs` import |
| `shutdown.py:80` | `def _memory_field` |
| `shutdown.py:1581` | `# AD-733-1: Stop attachment retention reaper.` |
| `finalize.py:745-747` | `perception_enabled`, `lru_enabled`, the guard |
| `avatars.py:11-12, 68-69, 259, 313` | the imports, the lip-sync route, `select_backend`, `_wav_duration_ms` |
| `DECISIONS.md:674` | the tracker heading |
| `PROGRESS.md:1` | the title |

Every SEARCH was copied from a Read on this tree. A multi-line block is unique by its `def` or signature line, or its unique comment. Two identical one-line stubs in `test_bf291` are disambiguated by their following lines, and the two in `test_ad738` by their second `setattr`.

**Other facts:**

| Fact | Source |
|---|---|
| `SRP_MAX_BODY_LINES = 500`, `SRP_MAX_DIRECT_METHODS = 15`; ranked layers only substrate, mesh, cognitive and experience | `scripts/check_architecture_principles.py:187-188`; `architecture-baseline.yaml:12-17` |
| `LongRunService.close` → `executor.shutdown(wait=False)` | `long_runs.py:259-275` |
| `_TRUSTED` row `("src/probos/audio/tts/piper_backend.py", "PiperBackend.synthesize._run_sync"): (1, "piper; text on stdin")`; `_KNOWN_LAUNCH_FLOOR = 39` | `test_bf892…:87, 78` |
| `EXPECTED_DUMPS["AttachmentsConfig"]` ends `"max_store_bytes": 5368709120,` | `test_ad1270e2d…:134` |
| `acquire_pidfile` and `AnotherInstanceRunning`; the reset precedent `reset_pidfile = acquire_pidfile(data_dir)` … `reset_pidfile.unlink()` | `pidfile_guard.py:230, 28, 275-278`; `__main__.py:2993, 3116` |
| probos.log is `_platform_data_dir() / "logs" / "probos.log"`, INFO and up; `log_level: INFO` | `__main__.py:163-175`; live `system.yaml:5` |
| `typescript ^5.7.0`, `vitest ^4.1.0`; `"build": "tsc -b && vite build"`; `"test": "vitest run"`; CI's `ui-tests` job runs `npm ci`, `npm run test`, `npm run build` | `ui/package.json:8, 10, 44, 46`; `.github/workflows/ci.yml:122-163` |
| `strict: true`, `noUnusedLocals: false` | `ui/tsconfig.json:14-16` |
| a vitest global setup resets the arbiter | `speechQueueStore.ts:79` |
| `generate_visemes(audio_path, binary_path, timeout_seconds=30.0, *, ffmpeg_binary_path=None)`; `_parse_rhubarb_output` reads `start`, `end`, `value` | `rhubarb_backend.py:288-294, 447-476` |
| `LipSyncConfig.ffmpeg_binary_path` | `experience.py:609` |
| the `AttachmentsConfig` fields | `integrations.py:144-259` |
| installed: `piper.exe`, `onnxruntime.dll`, `espeak-ng.dll`, `piper_phonemize.dll`, 31 voices | Glob `d:\ProbOS\tools\piper` |
| `.venv` has `onnxruntime`; no `piper*` package | Glob `.venv\Lib\site-packages` |
| live, by Glob: 1,126 `*.wav`, 1 `*.webm`, 11,820 files | `%LOCALAPPDATA%\ProbOS\data\attachments` |

## 12. Absence Verified (2026-10-23)

```
CLAIM: no dedicated executor and no set_default_executor in src/
RUN:   Grep "set_default_executor" src/          -> no matches
HOLDS: yes

CLAIM: the new names exist nowhere yet (this contract introduces them)
RUN:   Grep "runSentenceQueue|defer_visemes|visemes_deferred|tts_audio|voice_synthesis|VoiceSynthesisService" (excluding prompts/, docs/, *.md)
FOUND: only runSentenceQueue (voiceChunking.ts:84, voice.ts:7, 381, 490, voiceChunking.test.ts:5, 88, 106, 135, 149, 161)
HOLDS: yes

CLAIM: barge-in never paused the server <audio>
RUN:   Grep "stopSpeaking|pause\(\)" ui/src (non-test)
FOUND: voice.ts:451 (inside _playNow only); stopSpeaking at voice.ts:718-727 has no pause
HOLDS: yes

CLAIM: no client telemetry endpoint exists (hence User Timing measures and server log lines)
RUN:   Grep "fetch\('/api/(telemetry|client|metrics|log|hxi)" ui/src (non-test) -> no matches
HOLDS: yes

CLAIM: no ?raw reader of the TS files this edits
RUN:   Grep "\?raw" ui/src -> 38 imports, none of voice.ts / voiceChunking.ts / useLipSyncCapture.ts
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- **rhasspy/piper `src/cpp/main.cpp`** ([raw](https://raw.githubusercontent.com/rhasspy/piper/master/src/cpp/main.cpp)). Its JSON keys are `text`, `output_file`, `speaker_id` and `speaker`. Prosody comes only from the command line. With `output_file` set, it writes the file and prints the path with `endl` (flushed). It reads line by line until EOF and logs to stderr (`stderr_color_st`). A malformed line ends the process. Absorbed as D2a. ASCII-only lines leave no way to send a malformed one, and a crash is caught by the end-of-file read anyway.
- **wyoming-piper v1.5.0 `process.py`** ([source](https://github.com/rhasspy/wyoming-piper/blob/v1.5.0/wyoming_piper/process.py)). One persistent `--json-input` process per voice, a `max_piper_procs` limit with eviction by last use, a dead process noticed through `returncode`, stderr sent to DEVNULL.
  - Absorbed: the pool, the LRU and death detection.
  - Adapted: a thread rather than an asyncio subprocess (BF-280), and stderr to a file so a crash can be diagnosed.
- **piper1-gpl phoneme alignment** ([search](https://docs.inworld.ai/tts/capabilities/timestamps), [OpenFaceFX](https://context7.com/websites/openfacefx/llms.txt?tokens=10000)). An alignment format exists downstream, but it belongs to the GPL-3 successor, and the installed binary emits none. Rejected for D3.
- **Internal:**
  - AD-1071, AD-1291 and BF-655: the queue, the arbiter, the one terminal 'end'.
  - BF-283: the audio-clock viseme sampling that makes late frames correct.
  - AD-733-1: the origin and durability model.
  - AD-1246 `LongRunService`: the lifecycle precedent.
  - BF-893's busy-default-pool harness: the pattern behind `test_voice_work_does_not_queue_behind_a_busy_default_pool`.
  - AD-1341 S1's pidfile: reused as the tool's lock.
- **`docs/research/reference-projects.md`**: no row covers TTS or voice. No overdue row is relevant (judged on 2026-10-23); considered, deferred.
- **Blind spots:**
  - A failed prefetch's browser fallback can overlap the next sentence's audio. This predates BF-918; register R3.
  - Several HXI tabs prefetch at once; the admission bound caps them.
  - Group-chat speakers sharing one voice are serialized on one process; considered, deferred.
  - The first request after a boot pays the model load (about 0.5 s); prewarming is deferred.
  - The browser-capture lip-sync uploads are `chat_attachment` too (1 live file); register R1.
  - `sentence_silence` (0.35 s) is inside each WAV, so the gap the Captain hears is that plus the measured gap.
  - Web Audio scheduling for gapless playback was considered and deferred: it changes BF-283's clock and AD-735's `playbackRate`.

## 14. Diff Reviewer: properties to verify

1. A resident process serves one request at a time. A worker that timed out, exited, returned empty, was cancelled or raised is never used again.
2. The timeout bounds every request from its write to its answer. A hung process is killed by then, and the next request starts a new one.
3. `close` is idempotent, never awaits, and leaves no process, pipe, stderr file or directory behind. After `close`, every admission is refused.
4. With the service present, voice work never runs on asyncio's default pool. Admitted work is bounded, and a refusal degrades to `None` or `[]` without raising into a route.
5. The only new process launch uses `env=trusted_command_env()` (BF-892) and `subprocess.Popen` in a thread (BF-280). No WAV travels over stdout (BF-282).
6. The `/api/avatars/tts` response is a superset of the old one. A request without `defer_visemes: true` gets the same fields and behaviour as before.
7. Spoken audio is written as `tts_audio`. No other origin is ever downgraded. Age-based deletion reaches only `perception_frame` (as before) and `tts_audio`.
8. The inventory tool writes nothing without `--delete` and a matching `--confirm`, and refuses while another instance holds the data directory.
9. Client:
   - Playback order is sentence order, and a sentence plays only after the previous one ended.
   - After a stop, no prefetched audio plays and no 'start' fires for it.
   - Every 'start' has exactly one 'end'.
   - Visemes are injected only for the `<audio>` that is playing.
   - The browser backend still makes no POST.
10. Every new class stays within 500 lines and 15 methods, adds no layer import, and creates no task it does not hold.

## 15. Acceptance criteria

- [ ] M1 to M3 are built; the focused checks in §6 pass; the three `--check` commands pass; `check_architecture_principles.py --check` passes; `npx tsc -b` passes.
- [ ] Cancelling or superseding a reply stops it immediately, and no prefetched sentence plays afterwards (P2, P3, P7).
- [ ] Lip-sync visemes fire for every utterance on both paths (P4, P5, P6, and the route tests).
- [ ] The browser fallback is unchanged: no request when `backend != "piper"`, and a fallback per sentence on failure (serverTts, pipelining test 4).
- [ ] With pipelining off, the single-call path behaves as before, apart from the S2 speed-up and the deferred visemes.
- [ ] The resident process recovers from a hang (killed within `timeout_seconds`) and from a crash, and degrades honestly.
- [ ] Spoken audio lands under its own origin and the reaper sweeps it; a hash also written as `chat_attachment` is never swept.
- [ ] Two tests cross a seam each: route → service → worker → store (`test_the_route_speaks_through_the_resident_process`), and enqueue → prefetch → play in order → stop (P2).
- [ ] The live acceptance (§16) is reported on #1626. #1626 closes after it, and after the Captain's sweep decision.
- [ ] All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance: what the Captain does and what is read

The live acceptance cannot be met by CI. Only the Captain restarts the vessel; the orchestrator reads files only and never calls the live API.

**The Captain, before the restart (the current build is the baseline):**
1. Keep `tts.backend: piper`, `lipsync.backend: rhubarb` and `sentence_pipelining_enabled: true`.
2. In the HXI, press F12, open Network, tick "Preserve log", and filter on `avatars|attachments`.
3. With the crew active, get at least 20 replies of 5 or more sentences.
4. Export the HAR to `%USERPROFILE%\Desktop\bf918-before.har`, outside the repository and the data directory.

**The Captain, after the merge:**
1. Restart ProbOS, then hard-reload the HXI (Ctrl+Shift+R).
2. Repeat the 20 or more replies, and export `bf918-after.har`.
3. In the DevTools console, run:
   ```js
   copy(JSON.stringify({first: performance.getEntriesByName('bf918:first-audio').map(e => Math.round(e.duration)), gaps: performance.getEntriesByName('bf918:sentence-gap').map(e => Math.round(e.duration))}))
   ```
4. Paste the result into `%USERPROFILE%\Desktop\bf918-after-measures.json`, and post the three paths on #1626.

**The orchestrator, read-only (PowerShell; `$D = "$env:LOCALAPPDATA\ProbOS\data"`):**

1. **Route stages, after.** Use `Select-String -Path "$D\logs\probos.log*" -Pattern 'BF-918: tts route|BF-918: lipsync route'`, then take p50 and p95 of `synth_ms`, `store_ms`, `visemes_ms` and `total_ms`, and of the lipsync route's `visemes_ms`:
   ```
   d:/ProbOS/.venv/Scripts/python.exe -I -c "import re,glob,statistics as s,os;v={};[v.setdefault(k,[]).append(float(x)) for f in glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\ProbOS\data\logs\probos.log*')) for l in open(f,encoding='utf-8',errors='replace') if 'BF-918: tts route' in l for k,x in re.findall(r'(\w+_ms)=(\d+)',l)];print({k:(s.median(x),sorted(x)[int(0.95*(len(x)-1))],len(x)) for k,x in v.items()})"
   ```
2. **Health.** `Select-String -Path "$D\logs\probos.log*" -Pattern 'resident piper started|piper timed out|piper exit=|voice work refused|resident piper processes are busy|lip-sync refused|no voice synthesis service'`. Expected:
   - "started": one per (voice, prosody) key used since the boot;
   - every other pattern: 0 lines, or each one explained.
3. **First audio, before and after, comparable.** From each HAR, per reply: from the start of the first `POST /api/avatars/tts` to the end of the first `GET /api/chat/attachments/<id>` response. Report p50 and p95 for each side. After the change, also report the p50 and p95 of `bf918:first-audio` (from dispatch to `playing`).
4. **The gap between sentences.**
   - Before (sequential): for each boundary, from the start of `POST N+1` to the end of `GET N+1`, because `POST N+1` started at `ended(N)`.
   - After: the `bf918:sentence-gap` values.
   - Report both, and add the 0.35 s of `sentence_silence` for the gap the Captain hears.
5. **Route time, before.** The HAR `time` of each `POST /api/avatars/tts` (before and after, the same measure). The server log lines exist only after the change.
6. **Store.**
   ```
   d:/ProbOS/.venv/Scripts/python.exe -I -c "import json,collections,os;d=json.load(open(os.path.expandvars(r'%LOCALAPPDATA%\ProbOS\data\attachments\.index.json'),encoding='utf-8'));print(collections.Counter((v.get('origin'),v.get('mime')) for v in d.values()))"
   ```
   The `('tts_audio','audio/wav')` count must stay small: only the replies of the last 15 minutes. Re-run it a day later; the number of `*.wav` files must not grow past 1,126 plus that small number.
7. **Legacy inventory, dry run (read-only).** `d:/ProbOS/.venv/Scripts/python.exe scripts/tts_audio_inventory.py --data-dir "$D"`. Post the JSON. **The Captain then decides whether to run `--delete --confirm <candidates>` with ProbOS stopped.**

**Targets:** first audio within about 1.5 s at p50, with p95 reported; no gap over about 0.3 s, excluding `sentence_silence`.

## 17. Not verified

- I could not run `piper.exe` (the bridge allows no such command). The installed binary's version, `--json-input`, the per-line `output_file`, the path echo and the decoding of `\u` escapes are verified only from upstream source. V0 is the Builder's first action, with its expected result.
- No test, vitest, `tsc`, precheck, checker or generator was run (read-only call).
- **The microtask depth of the existing `_flush` helpers is estimated**, not run (§6 harness rule).
- **The jsdom `performance.measure` implementation is not checked** (P8 stubs it).
- Live bytes and per-origin counts: the index is a single-line JSON file and Python is not allowed here, so I could only count files by extension.
- wyoming-piper's read-back code (beyond the excerpt) was not read.
- AD-1341 S2 to S6 and AD-1346 M2, M5, M6, M8 and M10 have no contracts yet. The overlap in §4 is judged from #1601's text and #1632's body.
- **Expected phantom-precheck false positives**, all from code blocks: the `Inventory`, `PiperOutcome` and fake-process field accesses (new symbols), `Timer` (`threading.Timer`), `OrderedDict`, `SimpleNamespace`, `ThreadPoolExecutor` where already in `src`, and `VisemeFrame` where already in `src`.

**Orchestrator verification (2026-10-24, by tool, on `origin/main` `26bec26d` = BF-914 merged; the consult above ran none of this).** All 58 verbatim pairs apply, each SEARCH once (10 in M1 with §7.9a, 35 in M2, 14 in M3), the eight range pairs apply by their markers, and the six new files are created by tool: the oracle is three scratch commits, M1 `b5a26ed7`, M2 `83bf2cc0` and M3 `aeaca4af` (tree `1db7476e`). **The oracle found what a read-only consult cannot** (the header lists the three repairs): the retention test's tool loader, the facade's pinned field count, and the range pairs a verbatim-pair tool skips. After them: the M1 and M2 focused lists, 20 test files, 1,147 passed; vitest over 33 files, 338 passed, and `tsc -b` clean; the generators move the model-field count 1879 to 1880 and change the three generated files. **Mutation campaign:** the 21 Python rows ran one at a time after an unmutated baseline (110 passed): 21 of 21 killed, none survived, none inert, none invalid; a census run that records every failing test of every mutant found 0 claimed killers that do not fail. The four TypeScript rows, run by hand (baseline 26 passed): 4 of 4 killed. "25 mutants parsed" equals the 21 and 4 rows of section 10. **Tests-first:** the oracle's nine Python test files on `26bec26d`'s source: 14 failed and 376 passed, and four files fail at collection because they import `probos.audio.tts.resident`; the four vitest files: 17 failed and 16 passed.

## 18. For the register (found here, not fixed by this change)

- R1: the browser-capture lip-sync path (`uploadAudioForLipSync`) also stores ephemeral audio as `chat_attachment`. One `.webm` on the live store today.
- R2: `startup/shutdown.py:1656` sets `runtime.attachment_reaper = None` inside the `desktop_lifecycle` block, not the reaper's own block.
- R3: a failed pipelined sentence's browser fallback returns at once, so its `SpeechSynthesis` speech can overlap the next server sentence (this predates BF-918).
- R4: when AD-1346 M3 lands, the resident Piper spawn will need classifying as an effect point under the `system` principal.
- R5: prewarm the default voice and prosody worker at boot, to remove the about 0.5 s first-request load. Deferred; measure after the change first.
