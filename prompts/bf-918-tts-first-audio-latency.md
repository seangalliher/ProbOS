# BF-918: a spoken reply's first audio and the gaps between its sentences (#1626): the next sentence is prefetched, Piper stays resident, rhubarb is off the first-audio path and voice work has its own executor; spoken audio expires

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24: Amendments A1 (area A, M1), A2 (area B, M2) and A3 (area C, M3), the repair of review round 1 (three parallel `gpt-6.1-sol` reviewers count as one round: 14 findings, all three areas NOT READY). The orchestrator applied the amendments by tool, in the order A2, A1, A3 so that the mutation rows stay in numeric order, and merged the three areas' "for integration" lists by hand. Amendments A4 (area A), A5 (area B) and A6 (area C), the repair of review round 2 (three parallel `gpt-6.1-sol` reviewers count as one round: 8 findings, all three areas NOT READY; the paragraph below gives the repair). The orchestrator applied them by tool, in the order A5, A4, A6 so that the mutation rows stay in numeric order, and merged the three areas' "for integration" lists by hand. Amendments A7 (area A), A8 (area B) and A9 (area C), the repair of review round 3 (three parallel `gpt-6.1-sol` reviewers count as one round: 5 findings, all three areas NOT READY; the round-three brake decision of 2026-10-24 06:49Z, recorded on #1626, is: continue, and round 4 is the last). The orchestrator applied A8 (one sentence), A7 (by hand: the consult could not read the amendment format, so its pairs carry no tool envelope) and A9 (by tool), in that order, and merged the "for integration" lists by hand. Amendment A10 (area C, text only), the repair of review round 4 (two `gpt-6.1-sol` reviewers, areas A and C: area A READY, area C NOT READY with three findings; the second round-three brake decision of 2026-10-24: continue, text only, round 5 is one area C reviewer on A10's delta).

**Review round 1, area A (amendment A1):** both sweeps remove an entry only if it is unchanged since listed (`unlink_if_unchanged` on the store protocol); the inventory tool is read-only (no `--delete`, `--confirm` or `--attachments-dir`), reads every file and decodes the episode archive, and accepts only Piper's exact header; the capacity description gives the real eviction order. **Area B (amendment A2):** one worker lifecycle (B1, B2: D4a); executor refusal or shutdown cancellation degrades at every voice stage (B3); the default-pool claim narrowed to synthesis and lip-sync, with the store's own I/O executor an open slice of #1626 (B4, slice M4); B5 registered. **Area C (amendment A3):** a reply stopped before any of its audio starts ends with AD-1291's `dropped` (`cancelled-before-audio`), which frees the speech arbiter (C1, C3); a play rejected after a stop is terminal and does not fall back to the browser (C2). Round 2 reviews the whole M1 candidate (the store protocol gains a method, a shared contract) and the deltas of M2 and M3 with their consumers.

**Review round 2, area A (amendment A4; `claude-architect`, Claude Code, Opus 5.5, 2026-10-24, read-only):** the inventory enumerates with `os.walk`; a directory it cannot list, and a link or junction to a directory (never followed), are named in `unreadable` with a trailing separator and keep every candidate; the store's own listing raises instead of counting nothing; the store docstring states the one-instance-per-root precondition and §9 states it with the one-sweep-at-a-time precondition (F2 and F3 are registered: §18 R15 and R16). **Area B (amendment A5):** the worker owns its directory from creation, so a failed stderr open leaves none behind (finding 1, a regression A2 introduced); the leftover temporary WAV of a caller-cancelled ffmpeg conversion is recorded with R10 (finding 2), and a killed Piper's directory that cannot be removed at once is R17. **Area C (amendment A6):** the profile chat consumes `dropped`. Its in-flight speech keys clear on it as on `end`, and a reply's completion listener retires on its own `dropped`, completing the controller's turn only while that reply is the newest of its arm (finding 1, a regression of A3). The comments on `SpeechQueueEntry.started` and `flushSpeechQueue` now say what D7a means (finding 3). A stop during a meeting batch is registered, not fixed, because no production caller can stop speech while one speaks (finding 2, R18); the lost-claim wait's blindness to a `dropped` is R19. No shared contract changes, except the inventory tool's report format (a script; its consumers are its own tests and §16 step 7). Round 3 reviews the delta of each area with its consumers, and re-reads the whole inventory tool against §14 item 8.

**Review round 3, area A (amendment A7; `claude-architect`, Claude Code, Opus 5.5, 2026-10-24, read-only):** `<data-dir>/attachments` is the one directory read through a link or junction, as the vessel reads its store; the report's new `attachments_link` names the target (`null` for a plain directory), a store link to nothing stops the run like an unlistable store, and no other link to a directory is followed (A-R3-1). `unindexed_wavs` again matches `.wav` as the OS matches names, so `.WAV` counts on Windows as it did before round 2 (A-R3-2, a regression of A4). The report format changes again (one key; consumers: its tests and §16 step 7). **Area B (amendment A8):** §14 item 3 says what the code does and the registered R17 allows (B F1, a regression of the round-2 text: a start that fails at any step is cleaned up once, and a killed Piper that has not exited can keep its directory on Windows); no code. **Area C (amendment A9):** a conversation reply's completion listener belongs to the 1:1 arm that set it up and is retired when React's cleanup ends the arm effect (an unmount, or any dependency change, the mic mode included) and when the controller delivers `'inactive'` to the arm's options (a newer arm, a pre-emption, the silence timer); review round 4 found that a coalesced `'inactive'` is never delivered (R21). The reply counter moved into the arm. A closed or switched profile chat's late `end` or `dropped` therefore no longer ends the next chat's turn (C F1, a regression of A6; main had the `end` half, and the same retire fixes it). The BF-718 comment now states what per-agent clearing really costs (C F2, R20). `conversationController.ts` is unchanged. No shared contract changes except the inventory tool's report format. **Round 4 is the last round (the Architect's brake decision): it reviews the delta of areas A and C with their consumers; area B has no reviewer (one contract sentence).**

**Review round 4 (amendment A10; `claude-architect`, Claude Code, Opus 5.5, 2026-10-24, read-only; text only, no behaviour change):** area A READY, no finding. Area C: (C-R4-2, P3, a regression of A9's text, not of its runtime behaviour) A9's comment and its contract sentences promised that every way an arm ends retires every reply listener; execution showed that the controller does not deliver every `'inactive'`, so a still-mounted older arm can keep its listeners (round 4 gave the condition as "two arms take the controller in one task"; review round 5 corrected it to two pre-emptions queued within one task, C-R5-1). The comment in §7.30f pair 2 and the contract now name the two triggers (React's cleanup and a delivered `'inactive'`), and the exception is registered (R21; the same result on `26bec26d`). (C-R4-3, P3) R19's prerequisites are split by branch. (C-R4-1, P2, ordinary reach, not a regression) within one arm, an older reply's own `end` completes a newer reply's turn: a new slice, M6 of #1626 (§18). **Round 5 is one area C reviewer on A10's delta, text only.**

**Review round 5 (amendment A11; `claude-architect`, Claude Code, Opus 5.5, 2026-10-24, read-only; text only, no behaviour change):** one area C reviewer on A10's delta: NOT READY, four P3 findings, no P1. Execution confirmed the retirement sentences, "until React's cleanup", R19's two branches and the comment's equality with §7.30f. (C-R5-1, injected only, introduced by A10's text) A10's condition for R21 was wrong: a plain replacement within one task delivers the older arm's `'inactive'` from the teardown; only a pre-emption queues it for a microtask, and a later pre-emption queued before that microtask runs replaces it. The comment in §7.30f pair 2 now states only the two triggers its code hooks and points to R21, with no account of the controller's internals; R21, §5, §14 item 9 and the PROGRESS sentence state the corrected condition, and R21 defines "coalesced `'inactive'`". (C-R5-2, ordinary reach, A10's M6 text) the controller's guard before `onAgentReply` is per arm, not per request; M6 now says so and defines "newest" by callback order. (C-R5-3, kept from earlier rounds) the PROGRESS sentence and §15 now carry R19's exception. (C-R5-4) R18 cites `ProfileChatTab.tsx:1831`, the candidate's line. **Round 6 is one area C reviewer on A11's delta, text only; a round 7 needs a new decision (the Architect grants one only for a P1 or a code-comment sentence that execution shows false again).**

**Status:** build-ready. One BF, three milestones (M1 S3, M2 S2, M3 S1), one batch, one PR, one broad gate. **BF number:** BF-918 (#1626); this contract allocates nothing. **Tier:** S1 STANDARD, S2 STANDARD, **S3 HIGH** (the reaper gains an automatic age-based deletion on the live store; the inventory tool no longer deletes); the batch is reviewed at HIGH (use the Copilot `Diff Reviewer`). **Base:** `origin/main` `26bec26d` (the Architect drafted on `eea6e2f4`; BF-914 merged since, and the three generated files and one pin are regenerated on top of it). **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF.

**Orchestrator mechanical repairs (2026-10-24; found by applying this contract by tool to `origin/main` `26bec26d` and running its tests; no design decision, and the tree they produce is what the contract now says).** (1) §7.9's `_tool()` registers the loaded module in `sys.modules` while it executes (and `import sys` joins the imports): a dataclass in `scripts/tts_audio_inventory.py` finds its module's namespace there, so without it the four inventory-tool tests failed with an `AttributeError` on Python 3.12. (2) New §7.9a raises the pinned model-field count in `tests/test_ad1270e1_config_facade.py` from 1879 to 1880 (the one new field; the contract listed no pin there). (3) Eight pairs state their SEARCH as a range ("the block from X through Y") instead of a fenced block: §7.20 pairs 2 and 3, §7.21 pairs 2 and 3, §7.22 pairs 3 and 4, §7.26 pair 7 and §7.27 pair 2. A Builder replaces the stated block with the REPLACE; the orchestrator's oracle applies them with a range tool that locates each block by its start and end lines, never by line numbers. (4) §7.14 pair 4's comment line moves from before the docstring to after it, as a new pair 4b: the contract's own Builder note asked for that placement, and a tool applying the pairs cannot follow a note, so the oracle's `rhubarb_backend.py` differed from the Builder's until the note became a pair. (5) New §7.9b pops the new default in `tests/test_ad1152_agentic_correlation.py`'s golden: that test pops every config default added after its capture (BF-914 added two such pops), the contract listed no pin there, and the consolidated focused check found it (three failures) where the contract's own focused lists did not run it.

**Tests:**
- New `tests/test_bf918_tts_retention.py` (M1, 23 functions).
- New `tests/test_bf918_tts_latency.py` (M2, 27 functions).
- New fixture `tests/fixtures/fake_piper.py` (M2).
- New `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx` (M3, 13 cases).
- New `ui/src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx` (M3, 14 cases: C1 to C4, and C5 to C12 with C9 as three).
- `ui/src/audio/__tests__/voiceChunking.test.ts`: the `runSentenceQueue` describe (4 cases) is replaced by a `runPrefetchQueue` describe (6 cases).
- Updated pins:
  - `tests/test_ad738_piper_tts.py`: 4 backend tests and 3 stubs.
  - `tests/test_ad738e_1_per_emotion_prosody.py`: 2 tests and 1 stub.
  - `tests/test_ad1025_path_anchoring.py`: 2 tests.
  - `tests/test_bf291_piper_voice_catalog.py`: 3 stubs.
  - `tests/test_bf892_spawn_env_guard.py`: 1 inventory row.
  - `tests/test_ad1270e2d_integrations_models.py`: 1 dump key.
  - `tests/test_ad1270e1_config_facade.py`: 1 field count (§7.9a).
  - `tests/test_ad1152_agentic_correlation.py`: 1 default pop (§7.9b).
  - `tests/test_attachment_reaper.py`: 1 test (§7.9c; the injected removal failure moves to the conditional removal).
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
  - The reaper deletes it by age, and evicts it first under the size cap. Either pass removes an entry only if no write touched it since the pass listed it (review round 1).
  - `scripts/tts_audio_inventory.py` inventories the legacy WAVs. It is read-only: it deletes nothing, and deleting them is a follow-up (review round 1).

## 3. Decisions

| # | Decision | Ranked options (chosen first) and reason |
|---|---|---|
| D1 | Slicing | One contract, three milestones (M1 S3, M2 S2, M3 S1), one batch and gate. M1 and M2 both edit `_synthesize_tts_impl`, so they are sequential. M3's prefetch stands alone; its use of deferred visemes degrades to inline frames without M2. |
| D2 | Resident synthesizer | (1) A `piper --json-input` process per (binary, model, prosody), at most 4 resident, least recently used idle one evicted. Upstream `main.cpp`: prosody fixed per process; per-line keys `text`, `output_file`, `speaker_id`, `speaker`; prints the path with `endl`; logs to stderr. wyoming-piper v1.5.0 does the same. (2) In-process synthesis: rejected (no package installed; piper1-gpl is GPL-3). (3) Per-call spawn on a dedicated pool: rejected (keeps the 0.5 s load). |
| D2a | Process protocol | Each request writes one ASCII JSON line, `{"text": <lines joined by spaces>, "output_file": "<worker dir>/<uuid>.wav"}`. The one-shot path also joined lines with spaces. Lines are read until one names that file. The WAV is read from the file and removed (BF-282). Stderr goes to a file in the worker's directory, so the pipe can never fill and block Piper, and a crash warning quotes its last 500 bytes. `--output_dir` points at that directory, so nothing is ever written to the working directory. |
| D2b | Timeout | A `threading.Timer(timeout)` armed for one request kills the process. The read then returns end of file, the request degrades to `None`, the worker is retired, and the next request starts a new process. Queue and lock waits are not counted, as before (the old `communicate` timeout ran inside the thread). |
| D3 | Visemes | (1) The client opts in with `defer_visemes: true`; the route answers `visemes: []`, `visemes_deferred: true`; the browser POSTs `/api/avatars/lipsync` at prepare time and injects only while that `<audio>` is the one playing; the heuristic track runs in between. (2) Rhubarb overlapped with the store write: rejected (still on the path). (3) Piper phoneme timing: rejected (not emitted). (4) WebSocket push: deferred. |
| D4 | Executor | `VoiceSynthesisService` owns it, as `runtime.voice_synthesis`, created in `__init__` and closed in `shutdown()` before the attachment reaper stops. Constants: 4 threads, 16 in flight, 4 resident. Saturated or closed: refused, `None` (browser speech) or `[]` (heuristic). So is work the executor refuses, or that its shutdown cancels while queued, at every stage (Piper, ffmpeg, rhubarb, a retirement): `run_voice_work` raises `VoiceWorkRefused`, an `OSError`, and only a cancellation of the calling task propagates. A runtime without the service: Piper degrades to the browser; rhubarb keeps the default pool (pre-BF-918 behaviour). **Not isolated (A2, B4):** the attachment store's `write` and the lookups that serve the WAV (`exists`, `get_path`, through `_find`) still run on asyncio's default pool, so with that pool saturated, storing and fetching the first audio still wait. Ranked: (1) narrow the claim and register it, with a follow-up giving the store its own bounded I/O executor (chosen: that fix changes every store user's scheduling, in M1's module); (2) an `executor` argument on `write` (a protocol change that leaves both lookups on the pool); (3) the route writes the WAV through the voice executor (bypasses the store's index and origin contract, and leaves the lookups). |
| D4a | Worker lifecycle (A2: B1, B2) | A worker is open (idle, or running one request on a voice thread) until `close`, then closed for good. Exactly one party releases its process, pipes, stderr file and directory: `close` when the worker is idle, or the running request's own thread when its blocking call returns (`close` then only kills, so no pipe is closed under a read). A request on a closed worker starts nothing. A `close` during `Popen` is caught when `Popen` returns, and the new process is killed before any request is written. The worker owns each resource from the moment it exists (the directory from `mkdtemp`, before the stderr file is opened; A5), so a start that fails at any step leaves nothing its release does not reach. The service reaches every worker not yet released: resident ones in `_resident`, evicted ones in `_retiring` until their close has run, and `_retire` closes in a `finally`, so neither a shutdown that cancels the queued close nor a cancelled caller leaves one behind. The service's `close` stays idempotent and synchronous; it waits at most 0.5 s per idle or retiring worker and never for a running one. Rejected: waiting in `close` for running requests (blocks the loop up to a timeout); a cleanup thread (a second owner). |
| D5 | Retention | `tts_audio`, first in both tuples. TTL `attachments.tts_audio_retention_seconds` = 900 (from 60 to 86400). The upgrade rule exists already; its tuple must include the new origin. The index format is unchanged; no migration. **Review round 1 (A1):** both sweeps remove through the store's conditional removal, `unlink_if_unchanged` (same origin, not written since it was listed, decided under the store lock that removes it), so a refresh or an upgrade between a sweep's listing and its removal keeps the entry, and a kept entry frees nothing. Ranked: (1) a new protocol method, chosen: erasure's hard `unlink` keeps its meaning, and the `int | None` return separates "kept" from "freed 0 bytes"; (2) keyword arguments on `unlink`: rejected (overloads erasure's delete; a `bool` cannot say "kept"); (3) the policy moved into the store: rejected (holds the lock for a whole sweep, blocking the TTS route's write); (4) a read before the delete: rejected (the window stays open). |
| D5a | Legacy sweep | (i) **Revised in review round 1: the inventory tool is read-only.** It counts and lists candidates, reads only `<data-dir>/attachments`, and deletes nothing. It reads every file under the data directory whatever its name, decodes the episode archive's compressed rows with the archive's own decoder, and keeps every candidate when a file or row cannot be read. (ii) An age rule over old `audio/wav` `chat_attachment` items: rejected (it would delete the Captain's uploads). (iii) The delete-capable tool as first drafted: withdrawn. Round 1 found its reference scan blind to the compressed archive and its store root separable from its guard, and the reference model is still incomplete (§18). The legacy WAVs are static (no growth), so deferring costs disk only. **Deleting them is the Captain's decision, on the follow-up issue.** |
| D6 | Config | One field only. The lookahead is a TypeScript constant (1); the viseme mode is a request flag; pipelining stays default-off. |
| D7 | Barge-in, and an utterance stopped before its audio | `stopSpeaking` also pauses `_activeAudio`. That fires that utterance's single terminal `end` (BF-655), and the sentence queue, whose condition is already false, stops and discards. **D7a (review round 1, C1 to C3): one terminal event per dispatched utterance.** From `_playNow` until it ends, a dispatched utterance owns the device. It ends with `end` once any of its audio emitted `start` (BF-655; the BF-767 no-engine `end` as before), or with AD-1291's `dropped`, reason `cancelled-before-audio`, when it lost the device (a stop, or a newer dispatch) before any of its audio started. Each await between dispatch and audio (the status probe, the synthesis, the prefetch queue's first sentence) re-checks ownership; on a loss the prepared `<audio>` is discarded unplayed, a failed synthesis does not fall back to the browser, and `_playNow` fires the `dropped`. A play promise rejected because a stop or a newer dispatch paused it is a cancellation: no browser fallback, and the `pause` listener's `end` stays its one terminal event. The arbiter's wait for an entry ends on that entry's own `end` or `dropped`; GUARD 1, GUARD 2, `SPEECH_JOIN_TIMEOUT_MS` and `flushSpeechQueue` are unchanged. Ranked: (1) `dropped`, fired where the loss is observed and keyed by id: chosen, because the event already means "never reached audio" and every listener but the two waits and the profile chat's in-flight bookkeeping ignores it; the profile chat releases on it what an 'end' would have released and completes a turn only for the newest reply of the arm that set it up (review round 2, §7.30b), so a late synthesis answer cannot end a newer turn, and React's cleanup of an arm, and a delivered `'inactive'` to it, each retire its replies' listeners (review round 3, §7.30f), so a closed or switched profile chat's late `end` or `dropped` cannot end another arm's turn (a still-mounted arm whose `'inactive'` the controller coalesced keeps them: R21; within one arm, an older reply's `end` can still end a newer turn: slice M6); (2) an `end` with no `start`: rejected, the answer can land after the next reply's `start` and reset its modulation icon, head-bob, PTT gate and wake-word flag; (3) settling the in-flight wait inside `stopSpeaking`: rejected, it uses the unkeyed test-teardown seam in production and leaves the meeting sequencer waiting; (4) the candidate: the arbiter waits out `SPEECH_JOIN_TIMEOUT_MS`. Residual: the arbiter is freed when the cancelled synthesis answers, not at the stop; the stop has already flushed the backlog. |

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
| `dropped` with the new reason `cancelled-before-audio` (D7a; the event type and its fields exist since AD-1291) | `voice.ts` `_playNow` | the arbiter's wait in `_awaitEntry` (now terminal on it); `meetingVoice.ts:127` (already terminal on `dropped`; a stop does not end the rest of a meeting batch, which no production caller reaches: §18); `ProfileChatTab.tsx` (review round 2, §7.30b): the BF-718 in-flight effect clears its agent's in-flight keys on `dropped` as on `end`, and a reply's completion listener retires on its own utterance's `dropped` and completes the controller's turn only while that reply is the newest of its own arm (no synthetic `end`, BF-767); every reply listener, the lost-claim waiter included, is retired on React's cleanup of its arm and on a delivered `'inactive'` (review round 3, §7.30f; a coalesced `'inactive'` is not delivered: R21); its lost-claim wait and its PTT gate (`:564`) ignore it; `wakeWord.ts:187`, `useLipSyncCapture.ts:62`, `CrewVRM.tsx:502`, `ParametricAvatar.tsx:49` and `ModulationIndicator.tsx:28` act only on `start` or `end` and ignore it; no consumer reads `reason` |
| `'inactive'` sent to an arm's `onStateChange` (review round 3) | `conversationController.ts` teardown (`:520`, `:547`): a newer arm, a disarm or dispose, the silence timer, a pre-emption | `ProfileChatTab`'s 1:1 arm now retires its replies' completion listeners on it when it is delivered (it only logged before; a pre-empted arm's `'inactive'` is queued for a microtask, and one that a later pre-emption in the same task replaces is never delivered: R21); the meeting arm still only logs. The controller is unchanged |
| `ATTACHMENT_ORIGINS` | `store.py` | `filesystem_store._normalize_origin`; `test_ad1192…:2883` iterates it (an empty `tts_audio` list is fine) |
| `_LRU_EVICTION_ORDER`, `_ORIGIN_DURABILITY` | reaper, store | the reaper's LRU pass; `write`'s upgrade |
| new protocol method `unlink_if_unchanged` on `AttachmentStore` (review round 1) | `FilesystemAttachmentStore`, the only implementer in `src/` | the reaper's age and size passes only. `unlink` is unchanged and keeps its callers (`knowledge/erasure.py:298`, tests). No test fake is driven by the reaper (fakes of `list_by_origin`: `test_ad1203_trace_routes.py:57`, `test_ad1203_turn_provenance.py:157`, read by the traces route). `test_attachment_reaper.py`'s injected removal failure moves to the new method (§7.9c). `ATTACHMENT_REAPED` keeps its payload shape; its counts now cover only entries actually removed |
| `scripts/tts_audio_inventory.py` command line | the tool | the Captain (§16 step 7) and `tests/test_bf918_tts_retention.py`; nothing else. Read-only: `--delete`, `--confirm` and `--attachments-dir` are gone; the report drops `attachments_dir`, `deleted` and `freed_bytes`, and adds `seconds` and (review round 3) `attachments_link` |
| index `origin` | `FilesystemAttachmentStore.write` | `list_by_origin` (reaper only), `write`, the new tool |
| `AttachmentsConfig` dump | `config_models/integrations.py` | `test_ad1270e2d…` `EXPECTED_DUMPS`; the facade baseline, profiles and reference (regenerated) |
| BF-892 launch inventory | `test_bf892_spawn_env_guard.py:87` | the guard scan |
| `runtime.voice_synthesis` | `runtime.py` | the route, `_bounded_visemes`, `_close_voice_synthesis` |
| `run_voice_work`, `VoiceWorkRefused` (new, A2) | `audio/tts/resident.py` | `VoiceSynthesisService._retire`; `rhubarb_backend._convert_to_wav` and `_run_rhubarb`, whose existing `except (OSError, ValueError)` handlers degrade on it; no test stubs either |
| `PiperWorker.close` (A2: refuses later requests; on a running worker only kills) | `audio/tts/resident.py` | `VoiceSynthesisService` (`close`, `_forget`, `_retire`); `tests/test_bf918_tts_latency.py` |

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
- `test_unlink_if_unchanged_removes_only_the_entry_that_was_listed`
- `test_a_write_after_the_ttl_listing_keeps_its_entry` (a refresh, an upgrade to `chat_attachment`, an upgrade to `agent_artifact`)
- `test_a_write_after_the_lru_listing_keeps_its_entry` (the same three)
- `test_the_tool_cannot_delete_or_read_another_store` (`--delete`; `--delete --confirm 2`; `--attachments-dir`)
- `test_only_the_exact_piper_header_is_a_candidate`
- `test_an_archived_reference_keeps_its_wav` (producer: the real `EpisodeArchive` writer)
- `test_an_archive_row_that_cannot_be_decoded_keeps_every_candidate`
- `test_a_reference_in_a_file_of_any_name_keeps_its_wav` (a WAL file; an uncompressed tar backup)
- `test_a_directory_that_cannot_be_listed_keeps_every_candidate` (review round 2, F1; the listed run is the control)
- `test_a_link_to_a_directory_is_not_followed_and_keeps_every_candidate` (a symbolic link; a junction)
- `test_a_store_directory_that_cannot_be_listed_stops_the_inventory` (the counted run is the control)
- `test_a_linked_store_is_read_through_its_link_and_named` (review round 3, A-R3-1; a junction on Windows, a symbolic link elsewhere; the plain store is the control)
- `test_a_store_linked_inside_the_data_directory_keeps_every_candidate` (review round 3; a control on candidate 4)
- `test_unindexed_wavs_are_matched_as_the_os_matches_names` (review round 3, A-R3-2; 3 on Windows, 1 elsewhere)
- `test_a_store_link_to_nothing_stops_the_inventory` (review round 3)

Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_tts_retention.py tests/test_attachment_reaper.py tests/test_ad1192_owned_steps_finalization.py tests/test_ad1270e2d_integrations_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_ad738_piper_tts.py -n 0 -q
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
- A2: `test_a_closed_worker_refuses_a_request_and_starts_nothing`, `test_close_while_a_request_runs_releases_the_worker_when_it_returns`, `test_close_while_the_process_starts_kills_it_and_releases_everything`, `test_shutdown_closes_a_retiring_worker_and_the_request_degrades`, `test_a_cancelled_retirement_still_closes_the_worker`, `test_shutdown_degrades_a_queued_request_instead_of_cancelling_it`, `test_lipsync_converts_then_runs_rhubarb_on_the_voice_executor`, `test_lipsync_degrades_when_the_executor_closes_between_conversion_and_rhubarb`, `test_lipsync_degrades_and_removes_its_temp_file_when_shutdown_cancels_the_conversion`

Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_tts_latency.py tests/test_bf918_tts_retention.py tests/test_ad738_piper_tts.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_ad1025_path_anchoring.py tests/test_ad1025b_path_anchoring.py tests/test_bf291_piper_voice_catalog.py tests/test_bf892_spawn_env_guard.py tests/test_ad721b1_rhubarb_backend.py tests/test_ad721b_1a_ffmpeg_conversion.py tests/test_bf292_rhubarb_unsupported_format.py tests/test_ad1071_tts_pipelining.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1270b_architecture_fitness.py -n 0 -q
```

Then run `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`. Every new class has 15 or fewer methods and fewer than 500 lines.

**M3 (S1), §7.25 to §7.30.** Commit "BF-918 M3: the next sentence is synthesized while one plays; a stop drops prefetched audio; deferred visemes; barge-in silences Piper".

The cases:
- `voice.prefetch.bf918.test.tsx`: P1 to P13 (P9 to P13, and the reordered P2 and P3, from review round 1).
- `voiceChunking.test.ts`: Q1 to Q6.
- `ProfileChatTab.bf918.test.tsx` (review round 2, §7.30e): C1 to C4; review round 3 (A9): C5 to C12, one per way a conversation arm learns that it has ended (React's cleanup, or a delivered `'inactive'`; C9 runs three cases; C11 is a control). A coalesced `'inactive'` with the arm still mounted is not covered (R21).

Focused check, from `ui/` (the Builder's tree has a `ui/node_modules` junction):

```
npx vitest run src/audio src/__tests__/voice.test.ts src/__tests__/voiceE2E.smoke.test.tsx src/__tests__/wakeWord.bargeIn.test.ts src/__tests__/ProfileChatTab src/components/profile/__tests__/ProfileChatTab
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

Pair 2 (review round 1, A1: the protocol gains the conditional removal):

SEARCH:
```python
    async def unlink(self, content_hash: str) -> bool:
        """AD-733-1: remove the blob and its index entry. Returns ``False``
        when not found. Concurrent ``FileNotFoundError`` never raises.
        """
        ...
```
REPLACE:
```python
    async def unlink(self, content_hash: str) -> bool:
        """AD-733-1: remove the blob and its index entry. Returns ``False``
        when not found. Concurrent ``FileNotFoundError`` never raises.
        """
        ...

    async def unlink_if_unchanged(
        self,
        content_hash: str,
        *,
        origin: str,
        written_at: float,
    ) -> int | None:
        """BF-918 (#1626): remove the blob and its index entry only if the entry
        still has ``origin`` and was last written no later than ``written_at`` --
        the values a caller listed -- decided under the same lock as the removal.
        Returns the bytes freed (0 when only the index entry was left), or
        ``None`` when the entry changed, is absent, or could not be removed.
        """
        ...
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

Pair 2 (review round 1, A1):

SEARCH:
```python
            removed_from_index = self._index.pop(content_hash, None) is not None
            if existed or removed_from_index:
                self._save_index_sync()
            return existed or removed_from_index

    async def list_by_origin(self, origin: str) -> list[tuple[str, float]]:
```
REPLACE:
```python
            removed_from_index = self._index.pop(content_hash, None) is not None
            if existed or removed_from_index:
                self._save_index_sync()
            return existed or removed_from_index

    async def unlink_if_unchanged(
        self,
        content_hash: str,
        *,
        origin: str,
        written_at: float,
    ) -> int | None:
        """BF-918 (#1626): remove an entry only if it is still the one a caller listed.

        The reaper lists entries under the lock, releases it, and removes them
        one by one; a write in between may refresh ``written_at`` or upgrade the
        origin. The check and the removal happen here under one hold of the
        lock, so such an entry is kept. Returns the bytes freed (0 when the blob
        was already gone and only its index entry is removed), or ``None`` when
        the entry is absent, has another origin, was written after
        ``written_at``, or its blob could not be removed.
        """
        async with self._lock:
            entry = self._index.get(content_hash)
            if entry is None or entry.get("origin", "chat_attachment") != origin:
                return None
            try:
                current = float(entry.get("written_at", 0.0))
            except (TypeError, ValueError):
                return None
            if current > written_at:
                return None
            path = await self._find(content_hash)
            freed = 0
            if path is not None:
                try:
                    freed = (await asyncio.to_thread(path.stat)).st_size
                    await asyncio.to_thread(path.unlink)
                except FileNotFoundError:
                    freed = 0
                except OSError as ex:
                    logger.warning(
                        "BF-918: conditional unlink failed for %s: %s; "
                        "leaving on disk for next sweep",
                        content_hash[:8],
                        ex,
                    )
                    return None
            del self._index[content_hash]
            self._save_index_sync()
            return freed

    async def list_by_origin(self, origin: str) -> list[tuple[str, float]]:
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
                # BF-918 review round 1: removed only if unchanged since listed.
                freed_one = await self._safe_reap(sha, origin, written_at)
                if freed_one is not None:
                    removed += 1
                    freed += freed_one
        return (removed, freed)
```

Pair 4 (review round 1, A6: the size pass's docstring names the real order):

SEARCH:
```python
    async def _sweep_lru(self) -> tuple[int, int]:
        """Evict oldest entries until total <= max_store_bytes.

        Less-durable origins (perception_frame) are evicted first; if
        that's not enough, walk through browser_screenshot, avatar_render,
        crew_trace, then chat_attachment.
        """
```
REPLACE:
```python
    async def _sweep_lru(self) -> tuple[int, int]:
        """Evict oldest entries until total <= max_store_bytes.

        Origins go in ``_LRU_EVICTION_ORDER``: tts_audio first (BF-918), then
        perception_frame, browser_screenshot, avatar_render, crew_trace, then
        chat_attachment; agent_artifact is never evicted. An entry written
        again since it was listed is kept and frees nothing (BF-918).
        """
```

Pair 5 (review round 1, A1: the size pass removes conditionally):

SEARCH:
```python
            for sha, _written_at in candidates:
                if total <= cap:
                    break
                freed_one = await self._safe_unlink(sha)
```
REPLACE:
```python
            for sha, listed_at in candidates:
                if total <= cap:
                    break
                # BF-918 review round 1: removed only if unchanged since listed; a skip frees nothing.
                freed_one = await self._safe_reap(sha, origin, listed_at)
```

Pair 6 (review round 1, A1):

SEARCH:
```python
    async def _safe_unlink(self, sha: str) -> int | None:
        """Best-effort unlink. Returns bytes freed or ``None`` on failure."""
        size_bytes = 0
        try:
            size_bytes = await self._store.size(sha)
        except FileNotFoundError:
            # Concurrent unlink already removed the blob; still try to
            # clear the index entry below.
            size_bytes = 0
        except Exception:
            logger.warning(
                "AD-733-1: size(%s) failed during sweep",
                sha[:8],
                exc_info=True,
            )
        try:
            ok = await self._store.unlink(sha)
        except FileNotFoundError:
            return 0
        except Exception:
            logger.warning(
                "AD-733-1: unlink(%s) failed during sweep; skipping",
                sha[:8],
                exc_info=True,
            )
            return None
        if not ok:
            return 0
        return size_bytes
```
REPLACE:
```python
    async def _safe_reap(self, sha: str, origin: str, written_at: float) -> int | None:
        """Best-effort conditional removal (BF-918 review round 1).

        Returns the bytes freed, or ``None`` when the store kept the entry (it
        changed since it was listed, or is gone) or the removal failed. The
        check and the removal share one hold of the store's lock.
        """
        try:
            return await self._store.unlink_if_unchanged(sha, origin=origin, written_at=written_at)
        except Exception:
            logger.warning(
                "AD-733-1: unlink(%s) failed during sweep; skipping",
                sha[:8],
                exc_info=True,
            )
            return None
```

### 7.4 `src/probos/config_models/integrations.py` (M1)

SEARCH:
```python
            "AD-733-1: total bytes ceiling for attachments_dir. Reaper "
            "evicts oldest perception_frame entries first, then oldest "
            "chat_attachment entries, until under cap. 0 = disabled."
        ),
    )

    @field_validator("vision_tier")
```
REPLACE:
```python
            "AD-733-1: total bytes ceiling for attachments_dir. Reaper "
            "evicts oldest tts_audio entries first (BF-918), then "
            "perception_frame, browser_screenshot, avatar_render, crew_trace "
            "and chat_attachment entries, until under cap; agent_artifact "
            "is never evicted. 0 = disabled."
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
"""BF-918 (#1626): inventory the spoken-reply WAVs stored before the ``tts_audio`` origin
existed. Read-only: it prints what it found and changes nothing, so it may run while
ProbOS runs (a database being written may then be reported ``unreadable``, which keeps
every candidate; run it with ProbOS stopped for a clean count).

Until BF-918 every reply the server spoke was stored as a ``chat_attachment``, which
never expires (on 2026-10-23 the live store held 1,126 WAV files, 962 of them indexed).
New speech is stored as ``tts_audio`` and the reaper deletes it by age. Deleting the old
ones is a later decision of the Captain's (review round 1 withdrew this tool's delete:
it could not yet show a WAV unreferenced everywhere a reference can live).

A WAV is a candidate only when every one of these holds:

* its index entry says ``chat_attachment`` (or no origin) and ``audio/wav``, and the
  file ``<id>.wav`` exists;
* its header is exactly the 44-byte header Piper writes: ``RIFF`` with the file's size
  less 8, ``WAVE``, a 16-byte ``fmt `` chunk for PCM, mono, 16 bits, 16000 or 22050 Hz,
  byte rate twice the rate and block alignment 2, then ``data`` with the file's size
  less 44, non-empty and even;
* it was written more than ``--min-age-days`` ago (default 1);
* its id occurs in no record under the data directory, the attachment directory
  excepted. Every file is read, whatever its name, and an ``episode_archive`` table is
  decoded row by row with the archive's own decoder (its payloads are compressed). A
  file or archive row that cannot be read, a directory that cannot be listed, and a
  link or junction to a directory other than the attachment directory (never followed)
  keep every candidate; ``unreadable`` names each, a directory with a trailing path
  separator.

The data directory given is resolved first. Under it, ``<data-dir>/attachments`` is the
one directory read through a link or junction, as the vessel reads its store (the store
resolves its root); the report's ``attachments_link`` names the target and is ``null``
for a plain directory. No other link to a directory is followed.

WAV files with no index entry are counted (``unindexed_wavs``; ``.wav`` is matched as the
OS matches names, so in any case on Windows) and never candidates. An attachment directory
that cannot be listed, or that links to nothing, stops the run, as an unreadable index does.

Usage (PowerShell)::

    d:/ProbOS/.venv/Scripts/python.exe scripts/tts_audio_inventory.py --data-dir "$env:LOCALAPPDATA\\ProbOS\\data"
    ... --list                       # also print every candidate id
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from probos.cognitive.episode_archive import EpisodeArchiveIntegrityError, decode_payload  # noqa: E402

EXIT_OK = 0
_PIPER_RATES = frozenset({16000, 22050})
# RIFF, its size, WAVE, "fmt ", its size, format, channels, rate, byte rate, block align, bits, "data", its size.
_WAV_HEADER = "<4sI4s4sIHHIIHH4sI"
_WAV_HEADER_BYTES = 44
_SQLITE_MAGIC = b"SQLite format 3\x00"
_HASH = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_CHUNK = 16 * 1024 * 1024
_KEPT_REASONS = ("other_origin", "missing_file", "not_piper_shaped", "too_young", "referenced")


@dataclass
class Inventory:
    """What one run found. ``candidates`` maps an id to its size in bytes; ``attachments_link``
    is the real path of the attachment directory when that directory is a link or junction."""

    wav_entries: int = 0
    unindexed_wavs: int = 0
    candidates: dict[str, int] = field(default_factory=dict)
    kept: dict[str, int] = field(default_factory=lambda: dict.fromkeys(_KEPT_REASONS, 0))
    unreadable: list[str] = field(default_factory=list)
    attachments_link: str | None = None


def piper_shaped(path: Path) -> bool:
    """True only for the canonical 44-byte header Piper writes, with sizes that match the file."""
    try:
        with path.open("rb") as fh:
            head = fh.read(_WAV_HEADER_BYTES)
            size = os.fstat(fh.fileno()).st_size
    except OSError:
        return False
    if len(head) != _WAV_HEADER_BYTES:
        return False
    (riff, riff_size, wave, fmt_id, fmt_size, fmt, channels, rate,
     byte_rate, align, bits, data_id, data_size) = struct.unpack(_WAV_HEADER, head)
    return (
        (riff, wave, fmt_id, data_id) == (b"RIFF", b"WAVE", b"fmt ", b"data")
        and riff_size == size - 8
        and fmt_size == 16
        and (fmt, channels, bits) == (1, 1, 16)
        and rate in _PIPER_RATES
        and byte_rate == rate * 2
        and align == 2
        and 0 < data_size == size - _WAV_HEADER_BYTES
        and data_size % 2 == 0
    )


def _scan(data: bytes, targets: set[bytes], found: set[str]) -> None:
    for match in _HASH.finditer(data):
        if match.group() in targets:
            found.add(match.group().decode("ascii"))


def _scan_file(path: Path, targets: set[bytes], found: set[str]) -> bytes:
    """Scan every byte of ``path`` in chunks (an id across a chunk boundary is still
    seen); return the file's first 16 bytes."""
    head = b""
    carry = b""
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            head = head or chunk[:16]
            block = carry + chunk
            _scan(block, targets, found)
            carry = block[-65:]
    return head


def _scan_episode_archive(path: Path, targets: set[bytes], found: set[str]) -> None:
    """Decode every row of an ``episode_archive`` table in the SQLite file ``path``.

    The archive stores each episode as zlib-compressed JSON, so its ids are not in the
    file's bytes. Rows are decoded with the archive's own decoder; a row it rejects
    raises, and the caller keeps every candidate. Opened read-only and immutable, so
    nothing is created beside the file.
    """
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "episode_archive" not in tables:
            return
        rows = connection.execute("SELECT episode_id, content_hash, payload_format, payload FROM episode_archive")
        for episode_id, content_hash, payload_format, payload in rows:
            record = decode_payload(episode_id, content_hash, payload_format, payload)
            text = json.dumps([record.document, dict(record.metadata)], ensure_ascii=True)
            _scan(text.encode("ascii"), targets, found)
    finally:
        connection.close()


def _record_files(data_dir: Path, attachments_dir: Path, unreadable: list[str]) -> list[Path]:
    """Every entry under ``data_dir`` that is not a directory, outside ``attachments_dir``, sorted.

    Review round 2 (F1): ``Path.rglob`` skips a directory it cannot list without a word, so
    a reference inside it was missed and nothing said so; ``os.walk`` hands that error to
    ``onerror``. A directory that cannot be listed (refused, or gone since its parent was
    listed) and a link or junction to a directory are added to ``unreadable`` with a
    trailing separator, which keeps every candidate. A link is never followed: what it
    holds is not this data directory's, and it may loop (``os.walk`` alone would follow a
    Windows junction).
    """
    files: list[Path] = []

    def not_listed(error: OSError) -> None:
        unreadable.append(f"{error.filename}{os.sep}")  # refused, or gone since its parent was listed

    for directory, subdirs, names in os.walk(data_dir, onerror=not_listed):
        here = Path(directory)
        walked: list[str] = []
        for name in subdirs:
            child = here / name
            if child == attachments_dir:  # the store itself: its index names every id
                continue
            if os.path.islink(child) or os.path.isjunction(child):  # never followed
                unreadable.append(f"{child}{os.sep}")  # a link to a directory: its records are not read
                continue
            walked.append(name)
        subdirs[:] = walked
        files.extend(here / name for name in names)
    return sorted(files)


def referenced_ids(data_dir: Path, attachments_dir: Path, wanted: set[str]) -> tuple[set[str], list[str]]:
    """The ids in ``wanted`` that occur in a record under ``data_dir``, and everything that
    could not be read (then every id counts as referenced): files, and directories named
    with a trailing separator.

    Every regular file outside ``attachments_dir`` is read whatever its name: logs, WAL
    files and uncompressed backups included. A SQLite database is also opened, and an
    ``episode_archive`` table in it is decoded row by row.
    """
    if not wanted:
        return set(), []
    targets = {sha.encode("ascii") for sha in wanted}
    found: set[str] = set()
    unreadable: list[str] = []
    for path in _record_files(data_dir, attachments_dir, unreadable):
        if not path.is_file():  # a pipe, a socket or a link to nothing holds no record
            continue
        try:
            is_sqlite = _scan_file(path, targets, found) == _SQLITE_MAGIC
            if is_sqlite:
                _scan_episode_archive(path, targets, found)
        except (OSError, sqlite3.Error, EpisodeArchiveIntegrityError):
            unreadable.append(str(path))
    if unreadable:
        return set(wanted), sorted(unreadable)
    return found, unreadable


def take_inventory(data_dir: Path, attachments_dir: Path, *, min_age_days: float, now: float) -> Inventory:
    """Classify every indexed WAV. Reads only.

    Review round 3 (A7): an attachment directory that is a link or junction is read through,
    as the vessel reads its store, and its target is recorded in ``attachments_link``. A link
    to nothing is a store that cannot be listed: the run stops.
    """
    inventory = Inventory()
    if os.path.islink(attachments_dir) or os.path.isjunction(attachments_dir):  # read through, and named
        inventory.attachments_link = os.path.realpath(attachments_dir)
    index_path = attachments_dir / ".index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        index = {}
    if not isinstance(index, dict):
        raise ValueError(f"{index_path} is not an attachment index")
    # Review round 2: the store's listing raises like its index does; Path.glob skips a refusal silently.
    try:
        with os.scandir(attachments_dir) as entries:
            names = [entry.name for entry in entries]
    except FileNotFoundError:  # no store yet: nothing is indexed and nothing unindexed
        if inventory.attachments_link is not None:  # a link to nothing: the store cannot be listed
            raise
        names = []
    # Review round 3 (A-R3-2): ".wav" is matched as the OS matches names (any case on Windows), as Path.glob did.
    inventory.unindexed_wavs = sum(1 for name in names if os.path.normcase(name).endswith(".wav") and name[:-4] not in index)
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


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BF-918: inventory the spoken WAVs stored before the tts_audio origin (read-only).",
    )
    parser.add_argument("--data-dir", required=True, help="the vessel's data directory, e.g. %%LOCALAPPDATA%%\\ProbOS\\data")
    parser.add_argument("--min-age-days", type=float, default=1.0)
    parser.add_argument("--list", action="store_true", help="also print every candidate id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    started = time.monotonic()
    data_dir = Path(args.data_dir).resolve()
    # Review round 1 (A3): one root. The store read is always the data directory's own.
    attachments_dir = data_dir / "attachments"
    inventory = take_inventory(data_dir, attachments_dir, min_age_days=args.min_age_days, now=time.time())
    report: dict[str, Any] = {
        "data_dir": str(data_dir),
        "attachments_link": inventory.attachments_link,
        "wav_entries": inventory.wav_entries,
        "unindexed_wavs": inventory.unindexed_wavs,
        "candidates": len(inventory.candidates),
        "candidate_bytes": sum(inventory.candidates.values()),
        "kept": inventory.kept,
        "unreadable": inventory.unreadable,
        "seconds": round(time.monotonic() - started, 1),
    }
    if args.list:
        report["candidate_ids"] = sorted(inventory.candidates)
    print(json.dumps(report, indent=2))
    return EXIT_OK


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
anything else holding the same bytes keeps them, and a sweep removes only an entry no
write touched since it was listed; the inventory tool reads and never writes.

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
import sqlite3
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
from probos.cognitive.episode_archive import ARCHIVE_FILENAME, ArchiveRecord, EpisodeArchive
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


def _wav_fields(samples: int, *, pad: bytes = b"", **override: int) -> bytes:
    """Piper's canonical 44-byte WAV header with ``override`` applied, then ``samples`` frames of silence."""
    data = b"\x00\x00" * samples + pad
    fields = {
        "riff_size": 36 + len(data), "fmt_size": 16, "fmt": 1, "channels": 1, "rate": 22050,
        "byte_rate": 44100, "align": 2, "bits": 16, "data_size": len(data),
    }
    fields.update(override)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", fields["riff_size"], b"WAVE", b"fmt ", fields["fmt_size"],
        fields["fmt"], fields["channels"], fields["rate"], fields["byte_rate"], fields["align"],
        fields["bits"], b"data", fields["data_size"],
    )
    return header + data


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
    """Spoken first, then uploaded by the Captain: the more durable origin wins, and it is kept.
    An expired spoken WAV in the same sweep is the control: the sweep does delete."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(140)
    sha = await _write(store, blob, "tts_audio")
    await _write(store, blob, "chat_attachment", age_seconds=10 * _DAY)
    expired = await _write(store, _piper_wav(141), "tts_audio", age_seconds=1000)

    assert [s for s, _ in await store.list_by_origin("chat_attachment")] == [sha]
    assert [s for s, _ in await store.list_by_origin("tts_audio")] == [expired]
    await _reaper(store, tts_ttl=60).sweep_once()
    assert await store.exists(sha)
    assert not await store.exists(expired)


@pytest.mark.asyncio
async def test_speaking_bytes_already_held_never_downgrades_them(tmp_path: Path) -> None:
    """An invariant, not a fix discriminator: before BF-918 ``tts_audio`` was an unknown origin,
    coerced to ``chat_attachment``, so this passed then too. It guards the durability order.
    An expired spoken WAV in the same sweep is the control."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(150)
    sha = await _write(store, blob, "chat_attachment")
    await _write(store, blob, "tts_audio", age_seconds=10 * _DAY)
    expired = await _write(store, _piper_wav(151), "tts_audio", age_seconds=1000)

    assert [s for s, _ in await store.list_by_origin("chat_attachment")] == [sha]
    await _reaper(store, tts_ttl=60).sweep_once()
    assert await store.exists(sha)
    assert not await store.exists(expired)


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
async def test_unlink_if_unchanged_removes_only_the_entry_that_was_listed(tmp_path: Path) -> None:
    """Review round 1, A1: the store's conditional removal. Another origin, or a write after the
    listed time, keeps the entry; the listed values remove it and report its bytes; once gone, ``None``."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(165)
    sha = await _write(store, blob, "tts_audio", age_seconds=1000)
    [(listed, written_at)] = await store.list_by_origin("tts_audio")

    assert listed == sha
    assert await store.unlink_if_unchanged(sha, origin="chat_attachment", written_at=written_at) is None
    assert await store.unlink_if_unchanged(sha, origin="tts_audio", written_at=written_at - 1) is None
    assert await store.exists(sha)
    assert await store.unlink_if_unchanged(sha, origin="tts_audio", written_at=written_at) == len(blob)
    assert not await store.exists(sha)
    assert sha not in json.loads((tmp_path / ".index.json").read_text(encoding="utf-8"))
    assert await store.unlink_if_unchanged(sha, origin="tts_audio", written_at=written_at) is None


def _write_after_listing(store, *, origin: str, nth: int, sha: str, blob: bytes, write_origin: str) -> list[int]:
    """Wrap the real store's listing: right after its ``nth`` listing of ``origin``, write ``blob``
    again under ``write_origin`` (a refresh when that is the same origin, else an upgrade). The write
    lands between a sweep's snapshot and its removals, as the production awaits allow; here the
    order is fixed. Returns the listing count."""
    listed = store.list_by_origin
    calls = [0]

    async def listing_then_write(requested: str) -> list[tuple[str, float]]:
        rows = await listed(requested)
        if requested == origin:
            calls[0] += 1
            if calls[0] == nth:
                await store.write(sha, blob, "audio/wav", origin=write_origin)
        return rows

    store.list_by_origin = listing_then_write
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("write_origin", ["tts_audio", "chat_attachment", "agent_artifact"])
async def test_a_write_after_the_ttl_listing_keeps_its_entry(tmp_path: Path, write_origin: str) -> None:
    """Review round 1, A1: the age pass lists expired spoken audio; a write then refreshes or upgrades
    one entry before its removal. That entry is kept and frees nothing; an untouched expired one is
    removed (the control)."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(170)
    control_blob = _piper_wav(180)
    target = await _write(store, blob, "tts_audio", age_seconds=1000)
    control = await _write(store, control_blob, "tts_audio", age_seconds=2000)
    calls = _write_after_listing(store, origin="tts_audio", nth=1, sha=target, blob=blob, write_origin=write_origin)

    summary = await _reaper(store, tts_ttl=900).sweep_once()

    assert calls == [1]
    assert summary["age_ttl_removed"] == 1
    assert summary["freed_bytes"] == len(control_blob)
    assert await store.exists(target)
    assert not await store.exists(control)
    assert target in {s for s, _ in await store.list_by_origin(write_origin)}


@pytest.mark.asyncio
@pytest.mark.parametrize("write_origin", ["tts_audio", "chat_attachment", "agent_artifact"])
async def test_a_write_after_the_lru_listing_keeps_its_entry(tmp_path: Path, write_origin: str) -> None:
    """Review round 1, A1: the size pass lists spoken audio oldest first; a write then refreshes or
    upgrades the oldest before its eviction. It is kept and frees nothing, so the pass evicts the next
    one (the control) to get under the cap."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = _piper_wav(190)
    control_blob = _piper_wav(200)
    target = await _write(store, blob, "tts_audio", age_seconds=20)  # the oldest: first to go
    control = await _write(store, control_blob, "tts_audio", age_seconds=10)
    total = await store.total_size_bytes()
    # The age pass lists tts_audio first (nothing has expired under a one-day TTL); the size pass second.
    calls = _write_after_listing(store, origin="tts_audio", nth=2, sha=target, blob=blob, write_origin=write_origin)

    summary = await _reaper(store, tts_ttl=_DAY, max_store_bytes=total - 1).sweep_once()

    assert calls == [2]
    assert summary["lru_removed"] == 1
    assert summary["freed_bytes"] == len(control_blob)
    assert await store.exists(target)
    assert not await store.exists(control)
    assert target in {s for s, _ in await store.list_by_origin(write_origin)}


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
    # A chat record that names one WAV, in a real SQLite database (the tool opens every database it finds).
    connection = sqlite3.connect(data_dir / "chat.db")
    try:
        connection.execute("CREATE TABLE chat_thread_messages (id INTEGER PRIMARY KEY, parts TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO chat_thread_messages (parts) VALUES (?)",
            (json.dumps([{"type": "attachment", "attachment_id": shas["referenced"]}]),),
        )
        connection.commit()
    finally:
        connection.close()
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
    assert report["unreadable"] == []
    assert _snapshot(data_dir) == before


async def _archive_reference(data_dir: Path, sha: str) -> None:
    """Archive one episode whose outcome names ``sha``, through the real writer: canonical JSON,
    then zlib, in a SQLite BLOB, as dream pruning stores it (``cognitive/episode_archive.py``)."""
    archive = EpisodeArchive(str(data_dir / ARCHIVE_FILENAME))
    await archive.start()
    try:
        record = ArchiveRecord(
            episode_id="bf918-archived",
            document="The Captain's recording, played back to the crew. " * 8,
            metadata={"content_hash": "c" * 64, "outcomes_json": json.dumps([{"attachment_ids": [sha]}])},
        )
        assert await archive.archive([record], reason="capacity") == frozenset({"bf918-archived"})
    finally:
        await archive.stop()


@pytest.mark.parametrize(
    "extra", [["--delete"], ["--delete", "--confirm", "2"], ["--attachments-dir", "elsewhere"]],
)
def test_the_tool_cannot_delete_or_read_another_store(tmp_path: Path, extra: list[str]) -> None:
    """Review round 1, A3 and A5: the tool is read-only and reads only ``<data-dir>/attachments``.
    Each option is refused by the parser, and nothing anywhere under ``tmp_path`` changes, a lock
    file included."""
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    before = _snapshot(tmp_path)

    with pytest.raises(SystemExit) as exited:
        _tool().main(["--data-dir", str(data_dir), *extra])

    assert exited.value.code == 2
    assert _snapshot(tmp_path) == before


def test_only_the_exact_piper_header_is_a_candidate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Review round 1, A4: each malformed WAV breaks exactly one rule of the header Piper writes;
    the canonical one (the control) is the only candidate."""
    data_dir = tmp_path / "data"
    malformed = {
        "no_data_chunk": _wav_fields(700)[:36],
        "riff_size": _wav_fields(701, riff_size=0),
        "fmt_size": _wav_fields(702, fmt_size=0),
        "byte_rate": _wav_fields(703, byte_rate=0),
        "block_align": _wav_fields(704, align=0),
        "payload_absent": _wav_fields(705, data_size=2 * 705 + 100),
        "empty_payload": _wav_fields(0),
        "odd_payload": _wav_fields(706, pad=b"\x00"),
    }

    async def build() -> tuple[str, dict[str, str]]:
        store = FilesystemAttachmentStore(data_dir / "attachments")
        good = await _write(store, _wav_fields(720), "chat_attachment", age_seconds=3 * _DAY)
        bad = {
            name: await _write(store, blob, "chat_attachment", age_seconds=3 * _DAY)
            for name, blob in malformed.items()
        }
        return good, bad

    good, bad = asyncio.run(build())

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == [good]
    assert report["kept"]["not_piper_shaped"] == len(bad) == 8


def test_an_archived_reference_keeps_its_wav(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Review round 1, A2: a WAV named only inside the compressed episode archive is kept; its
    unreferenced twin is still a candidate (the control), and the run creates nothing anywhere."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    asyncio.run(_archive_reference(data_dir, shas["legacy"]))
    # The production encoding hides the id from a byte scan: the defect this test proves fixed.
    assert shas["legacy"].encode("ascii") not in (data_dir / ARCHIVE_FILENAME).read_bytes()
    before = _snapshot(data_dir)

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == [shas["legacy_low"]]
    assert report["kept"]["referenced"] == 2  # the chat record's and the archived one
    assert report["unreadable"] == []
    assert _snapshot(data_dir) == before


def test_an_archive_row_that_cannot_be_decoded_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 1, A2: fail closed. An archive row the archive's own decoder rejects keeps
    every candidate, and the file is named."""
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    asyncio.run(_archive_reference(data_dir, "0" * 64))
    connection = sqlite3.connect(data_dir / ARCHIVE_FILENAME)
    try:
        connection.execute("UPDATE episode_archive SET payload = ?", (b"not zlib",))
        connection.commit()
    finally:
        connection.close()

    assert _tool().main(["--data-dir", str(data_dir)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidates"] == 0
    assert report["unreadable"] == [str((data_dir / ARCHIVE_FILENAME).resolve())]


@pytest.mark.parametrize("name", ["chroma.sqlite3-wal", "backups/episodic-2026-10-01.tar"])
def test_a_reference_in_a_file_of_any_name_keeps_its_wav(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str,
) -> None:
    """Review round 1, A2: no file is skipped for its name; a WAL file and an uncompressed tar
    backup are real carriers. The unreferenced twin is the control."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    carrier = data_dir / name
    carrier.parent.mkdir(parents=True, exist_ok=True)
    carrier.write_bytes(b"\x37\x7f\x06\x82 frame " + shas["legacy"].encode("ascii") + b" end")

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == [shas["legacy_low"]]
    assert report["unreadable"] == []


def _record_naming(data_dir: Path, sha: str) -> Path:
    """A directory of records outside the store, holding one file that names ``sha``."""
    records = data_dir / "records"
    records.mkdir()
    (records / "note.txt").write_bytes(b"replayed " + sha.encode("ascii"))
    return records.resolve()


def _refusing_scandir(refused: Path) -> object:
    """``os.scandir`` refusing to list ``refused`` as the OS refuses a directory the user may
    not read. Portable: no permission is changed, and every other directory lists."""
    real_scandir = os.scandir
    target = os.path.normcase(str(refused))

    def scandir(path: str | os.PathLike[str] = ".") -> object:
        if os.path.normcase(os.fspath(path)) == target:
            raise PermissionError(13, "Access is denied", os.fspath(path))
        return real_scandir(path)

    return scandir


def test_a_directory_that_cannot_be_listed_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2, F1: a directory the walk cannot list is named in ``unreadable`` and
    keeps every candidate. The first run is the control: listed, the same directory's
    record keeps its WAV and only the unreferenced twin is a candidate."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    records = _record_naming(data_dir, shas["legacy"])
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0
    control = json.loads(capsys.readouterr().out)
    assert control["candidate_ids"] == [shas["legacy_low"]]
    assert control["unreadable"] == []

    monkeypatch.setattr(os, "scandir", _refusing_scandir(records))
    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == []
    assert report["kept"]["referenced"] == 3  # every eligible WAV: legacy, legacy_low, referenced
    assert report["unreadable"] == [f"{records}{os.sep}"]


@pytest.mark.parametrize("probe", ["islink", "isjunction"])
def test_a_link_to_a_directory_is_not_followed_and_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, probe: str,
) -> None:
    """Review round 2, F1: a symbolic link or a junction to a directory is never followed and
    is named, so every candidate is kept. Portable: the directory is real and only the link
    check answers yes for it. The first run is the control."""
    data_dir = tmp_path / "data"
    shas = asyncio.run(_legacy_store(data_dir))
    records = _record_naming(data_dir, shas["legacy"])
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0
    assert json.loads(capsys.readouterr().out)["candidate_ids"] == [shas["legacy_low"]]

    real_check = {"islink": os.path.islink, "isjunction": os.path.isjunction}[probe]
    target = os.path.normcase(str(records))
    monkeypatch.setattr(os.path, probe, lambda path: os.path.normcase(os.fspath(path)) == target or real_check(path))
    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == []
    assert report["unreadable"] == [f"{records}{os.sep}"]


def test_a_store_directory_that_cannot_be_listed_stops_the_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 2: the store's own listing (the ``unindexed_wavs`` count) is not skipped in
    silence; it raises, as an unreadable index does, and prints no report. The first run is
    the control: one WAV with no index entry is counted."""
    data_dir = tmp_path / "data"
    asyncio.run(_legacy_store(data_dir))
    (data_dir / "attachments" / f"{'e' * 64}.wav").write_bytes(_piper_wav(10))
    tool = _tool()

    assert tool.main(["--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out)["unindexed_wavs"] == 1

    monkeypatch.setattr(os, "scandir", _refusing_scandir((data_dir / "attachments").resolve()))
    with pytest.raises(PermissionError):
        tool.main(["--data-dir", str(data_dir)])
    assert capsys.readouterr().out == ""


def _link_directory(link: Path, target: Path) -> None:
    """Make ``link`` a real link to the directory ``target``: a junction on Windows (no
    privilege needed), a symbolic link elsewhere. Skips the test where this machine cannot."""
    try:
        if sys.platform == "win32":
            import _winapi  # CPython's Windows-only module; the test alone uses it, to make a junction without a shell

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot make a directory link on this machine: {exc}")
    assert os.path.islink(link) or os.path.isjunction(link)  # the premise: a real link, not a copy


def test_a_linked_store_is_read_through_its_link_and_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3, A-R3-1: ``<data-dir>/attachments`` linked to a store outside the data
    directory is read as the vessel reads it, and the report names the link's target. The
    first run, a plain store, is the control: ``attachments_link`` is null."""
    tool = _tool()
    plain = tmp_path / "plain"
    asyncio.run(_legacy_store(plain))
    assert tool.main(["--data-dir", str(plain)]) == 0
    assert json.loads(capsys.readouterr().out)["attachments_link"] is None

    data_dir = tmp_path / "data"
    external = tmp_path / "external_store"
    data_dir.mkdir()
    external.mkdir()
    _link_directory(data_dir / "attachments", external)
    shas = asyncio.run(_legacy_store(data_dir))  # the store resolves its root, so it writes into the target
    assert (external / ".index.json").is_file()  # the premise: the store lives outside the data directory

    assert tool.main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["attachments_link"] == os.path.realpath(external)
    assert sorted(report["candidate_ids"]) == sorted([shas["legacy"], shas["legacy_low"]])
    assert report["wav_entries"] == 6
    assert report["unreadable"] == []


def test_a_store_linked_inside_the_data_directory_keeps_every_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3: when ``<data-dir>/attachments`` links to a directory inside the data
    directory, the walk reads that directory under its own name (it is not a link) and its
    index names every id, so every candidate is kept: conservative, never a false candidate."""
    data_dir = tmp_path / "data"
    inside = data_dir / "store"
    inside.mkdir(parents=True)
    _link_directory(data_dir / "attachments", inside)
    asyncio.run(_legacy_store(data_dir))

    assert _tool().main(["--data-dir", str(data_dir), "--list"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_ids"] == []
    assert report["kept"]["referenced"] == 3  # every eligible WAV: legacy, legacy_low, referenced
    assert report["unreadable"] == []


def test_unindexed_wavs_are_matched_as_the_os_matches_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3, A-R3-2: ``.wav``, ``.WAV`` and ``.WaV`` files with no index entry are all
    WAV files to Windows, as ``Path.glob`` counted them before round 2; elsewhere only ``.wav`` is."""
    attachments = tmp_path / "data" / "attachments"
    attachments.mkdir(parents=True)
    for name in ("lower.wav", "upper.WAV", "mixed.WaV"):
        (attachments / name).write_bytes(_piper_wav(10))

    assert _tool().main(["--data-dir", str(tmp_path / "data")]) == 0

    assert json.loads(capsys.readouterr().out)["unindexed_wavs"] == (3 if os.name == "nt" else 1)


def test_a_store_link_to_nothing_stops_the_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Review round 3: ``<data-dir>/attachments`` linked to a directory that is gone (a removed
    or unplugged store) cannot be listed; it is not an absent store. The run raises and prints
    no report, where a report of an empty store would be falsely clean."""
    data_dir = tmp_path / "data"
    gone = tmp_path / "gone"
    data_dir.mkdir()
    gone.mkdir()
    link = data_dir / "attachments"
    _link_directory(link, gone)
    gone.rmdir()
    assert os.path.lexists(link) and not os.path.exists(link)  # the premise: a link to nothing

    with pytest.raises(OSError):
        _tool().main(["--data-dir", str(data_dir)])
    assert capsys.readouterr().out == ""
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

### 7.9b `tests/test_ad1152_agentic_correlation.py` (M1: a default added after the golden capture; added by the orchestrator after the focused check, see the header)

SEARCH:
```python
        "max_created_per_agent_per_hour": 6, "ttl_seconds": 86400, "max_depth": 2,
    }
    runtime = _local_runtime()
```
REPLACE:
```python
        "max_created_per_agent_per_hour": 6, "ttl_seconds": 86400, "max_depth": 2,
    }
    # BF-918's spoken-audio retention (seconds) was added after this capture too; this agentic-loop
    # observation stores no spoken audio.
    assert config["attachments"].pop("tts_audio_retention_seconds") == 900
    runtime = _local_runtime()
```

### 7.9c `tests/test_attachment_reaper.py` (M1: the injected removal failure moves to the conditional removal; review round 1, A1)

The reaper now removes through `unlink_if_unchanged`, so a patch of `unlink` no longer reaches it, and this test's blocked entry would be reaped. The property it pins (one failing removal does not stop the sweep) is unchanged.

SEARCH:
```python
    original_unlink = FilesystemAttachmentStore.unlink

    async def _flaky_unlink(self: FilesystemAttachmentStore, ch: str) -> bool:
        if ch == sha_blocked:
            raise PermissionError("Windows file in use")
        return await original_unlink(self, ch)

    with patch.object(FilesystemAttachmentStore, "unlink", _flaky_unlink):
```
REPLACE:
```python
    # BF-918 (#1626) review round 1: the reaper removes through unlink_if_unchanged (the entry it
    # listed, checked under the store lock), so the injected failure moves there.
    original_unlink = FilesystemAttachmentStore.unlink_if_unchanged

    async def _flaky_unlink(self: FilesystemAttachmentStore, ch: str, **kwargs: Any) -> int | None:
        if ch == sha_blocked:
            raise PermissionError("Windows file in use")
        return await original_unlink(self, ch, **kwargs)

    with patch.object(FilesystemAttachmentStore, "unlink_if_unchanged", _flaky_unlink):
```

### 7.9d `src/probos/attachments/filesystem_store.py` (M1: review round 2, F3, the one-instance precondition; apply after §7.2)

The conditional removal is decided under this instance's lock against this instance's index. A second store object or process writing the same root is not coordinated (on the register, §18). The docstring now states that precondition, so it claims no more than the code does. The SEARCH is the file's text after §7.2.

SEARCH:
```python
        lock, so such an entry is kept. Returns the bytes freed (0 when the blob
        was already gone and only its index entry is removed), or ``None`` when
```
REPLACE:
```python
        lock, so such an entry is kept. The lock and the index are this
        instance's: a write through another store object or another process on
        the same root is not seen, so one instance per attachment root is a
        precondition (production builds one per runtime; BF-918 review round 2).
        Returns the bytes freed (0 when the blob
        was already gone and only its index entry is removed), or ``None`` when
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

- The diff should add exactly the `attachments.tts_audio_retention_seconds` leaf and its rows, and (review round 1, A6) change the `max_store_bytes` description: its `config-reference.md` row and any schema digest computed over it in `config-facade-baseline.yaml`. Do not hard-code a leaf count or a checksum.
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
from typing import IO, Any, Callable, Iterator, TypeVar

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

_T = TypeVar("_T")


class VoiceWorkRefused(OSError):
    """BF-918: the voice executor refused work, or its shutdown cancelled queued work.

    An ``OSError``, so the subprocess helpers' existing log-and-degrade handlers
    (ffmpeg and rhubarb return ``None`` or ``[]`` on ``OSError`` and remove their
    converted file) degrade on it unchanged.
    """


def _caller_cancelled() -> bool:
    """True when the running task itself was asked to stop, not when an executor future was cancelled."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def run_voice_work(executor: concurrent.futures.Executor | None, fn: Callable[..., _T], *args: Any) -> _T:
    """``fn(*args)`` on ``executor`` (``None``: asyncio's default pool).

    Raises ``VoiceWorkRefused`` when the executor is shut down, or when its shutdown
    cancelled the work before it ran; a cancellation of the calling task propagates.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, fn, *args)
    except RuntimeError as exc:
        raise VoiceWorkRefused(f"BF-918: voice work refused: {exc}") from exc
    except asyncio.CancelledError:
        if _caller_cancelled():
            raise
        raise VoiceWorkRefused("BF-918: the voice executor shut down before this work ran") from None


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
    file and its output directory belong to this object until they are released.

    BF-918 lifecycle: open (idle, or running one request) until ``close``, then closed
    for good. Exactly one party releases the resources: ``close`` when the worker is
    idle, or the running request on its own thread when it returns (``close`` then only
    kills the process, so no pipe is closed under a read). A closed worker refuses
    every later request and starts nothing.
    """

    def __init__(self, key: PiperWorkerKey) -> None:
        self.key = key
        self._proc: subprocess.Popen[bytes] | None = None
        self._dir: Path | None = None
        self._stderr: IO[bytes] | None = None
        self._timed_out = False
        # Guards the two flags below and every swap of the three resources above;
        # never held across a blocking call.
        self._state = threading.Lock()
        self._running = False
        self._closed = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def synthesize_blocking(self, text: str, timeout: float) -> PiperOutcome:
        """Run one request; starts the process first when it is not running.

        Refused (``closed``) once the worker is closed. When ``close`` came while this
        request ran, the request releases the worker before it returns.
        """
        with self._state:
            if self._closed:  # closed while this request was queued: start nothing
                return PiperOutcome(None, "closed")
            self._running = True
        try:
            return self._request(text, timeout)
        finally:
            with self._state:
                self._running = False
                release = self._closed
            if release:
                self._release(wait_seconds=0.5)

    def _request(self, text: str, timeout: float) -> PiperOutcome:
        """One request on this worker's process; ``synthesize_blocking`` owns the lifecycle around it."""
        out: Path | None = None
        try:
            if not self.alive:
                self._spawn()
                if self._closed:  # closed while Popen ran, so close found no process to kill
                    self.kill()
                    return PiperOutcome(None, "closed")
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
        self._release(wait_seconds=2.0)  # a dead process's leftovers; the worker stays open
        directory = Path(tempfile.mkdtemp(prefix="probos-piper-"))
        # BF-918 A5: the worker owns the directory from its creation, so ``_release`` removes it
        # even when the open below fails (with no stderr file yet, it closes none).
        with self._state:
            self._dir = directory
        # BF-918: stderr goes to a file, so Piper's per-line log can never fill a pipe and block it.
        stderr = (directory / "stderr.log").open("wb")
        with self._state:
            self._stderr = stderr
        proc = subprocess.Popen(
            self.key.argv(directory),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=trusted_command_env(),
        )
        with self._state:
            self._proc = proc
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
        """Refuse every later request, and release the process, pipes, stderr file and directory.

        Idempotent; never raises. On a worker running a request it only kills the
        process: that request releases the rest on its own thread when it returns, so
        no pipe is closed under its read.
        """
        with self._state:
            self._closed = True
            running = self._running
        if running:
            self.kill()  # the running request releases the rest when it returns
            return
        self._release(wait_seconds)

    def _release(self, wait_seconds: float) -> None:
        """Kill the process and release its pipes, stderr file and directory; a no-op once released."""
        with self._state:
            proc, self._proc = self._proc, None
            stderr, self._stderr = self._stderr, None
            directory, self._dir = self._dir, None
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
        if stderr is not None:
            try:
                stderr.close()
            except OSError:
                pass
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
        # BF-918: evicted workers whose close has not run yet; ``close`` reaches them here.
        self._retiring: set[PiperWorker] = set()
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
                    # The caller went away, or shutdown cancelled the request while it was queued.
                    # Close the worker (mid-request on its thread, it is killed and releases itself
                    # when that request returns) and drop it, so no later request shares its pipes.
                    self._forget(key, worker)
                    if not _caller_cancelled():
                        return None  # shutdown, not the caller: degrade, as a refusal does
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
                if not self._closed:  # a request that shutdown ended is not a piper failure
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
        """Close a worker that has no request in flight, off the event loop when the executor takes it.

        Until its close has run the worker stays in ``_retiring``, where the service's
        ``close`` reaches it; the ``finally`` closes it here when the executor refused
        the close or a shutdown or the caller cancelled it. ``PiperWorker.close`` is
        idempotent, so once the queued close has run both are no-ops.
        """
        self._retiring.add(worker)
        worker.kill()
        try:
            await run_voice_work(self.executor, worker.close)
        except (VoiceWorkRefused, RuntimeError):
            pass  # closed or closing (``executor`` raises RuntimeError once closed): the finally closes it
        finally:
            self._retiring.discard(worker)
            worker.close(wait_seconds=0.5)  # a no-op once the queued close has run

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
        """Stop every resident process and the executor; refuse all later work. Idempotent; never awaits.

        Every worker the service holds, resident or retiring, is closed here: an idle
        one is released now; a running one is killed, and its request releases it on its
        voice thread when it returns (``PiperWorker.close``). Queued work is cancelled,
        and its requests degrade instead of raising.
        """
        if self._closed:
            return
        self._closed = True
        workers = [*self._resident.values(), *self._retiring]
        self._resident.clear()
        for worker in workers:
            worker.kill()
        for worker in workers:
            worker.close(wait_seconds=0.5)  # a running worker releases itself when its request returns
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

from probos.audio.tts.resident import run_voice_work
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
        loop = asyncio.get_running_loop()
        try:
            returncode, stderr_bytes = await loop.run_in_executor(None, _run_sync)
```
REPLACE:
```python
        try:
            # BF-918: a refused or shutdown-cancelled stage raises VoiceWorkRefused, an OSError:
            # the handler below removes the temp file and degrades.
            returncode, stderr_bytes = await run_voice_work(executor, _run_sync)
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
```

Pair 4b of 7 (the comment goes after the docstring's closing `"""`, so the docstring stays the function's first statement):

SEARCH:
```python
    contract is preserved (returns ``[]``).
    """
    if not audio_path.is_file():
```
REPLACE:
```python
    contract is preserved (returns ``[]``).
    """
    # BF-918: ``executor`` is the runtime's voice executor; ``None`` keeps asyncio's default pool.
    if not audio_path.is_file():
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
        loop = asyncio.get_running_loop()
        try:
            returncode, stdout_bytes, stderr_bytes = await loop.run_in_executor(
                None, _run_sync,
            )
```
REPLACE:
```python
        try:
            # BF-918: a stage the voice executor refuses (it closed after the conversion) raises
            # VoiceWorkRefused, an OSError: the handler below degrades to [] and the caller's
            # finally removes the converted file.
            returncode, stdout_bytes, stderr_bytes = await run_voice_work(
                executor, _run_sync,
            )
```

Pair 4b (orchestrator repair 4) places the pair 4 comment after the docstring's closing `"""`; pair 4 itself used to put it before the docstring and a Builder note asked for it to be moved, which a tool applying the pairs cannot do. Do not change `_SUPPORTED_SUFFIXES = {".wav", ".ogg"}`: `test_bf292` reads it from the source.

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
        # bounded executor for synthesis and lip-sync, so they do not queue behind
        # crew cognition on asyncio's default pool (storing and serving the WAV go
        # through the attachment store, which still uses that pool). Constructing it
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
        self.closed = False  # BF-918 A2: what the worker released is observable

    def write(self, data: bytes) -> int:
        self._proc.accept(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _Stdout:
    def __init__(self, proc: "FakePiperProcess") -> None:
        self._proc = proc
        self.closed = False

    def readline(self) -> bytes:
        return self._proc.next_line()

    def close(self) -> None:
        self.closed = True


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
        spawn_gate: threading.Event | None = None,
    ) -> None:
        self.modes = list(modes) or ["ok"]
        self.wav = wav
        self.stderr_bytes = stderr_bytes
        self.release = release
        # BF-918 A2: a launch sets ``spawning`` and then waits for ``spawn_gate`` (if given),
        # so a test can close the worker while ``Popen`` has not returned.
        self.spawn_gate = spawn_gate
        self.spawning = threading.Event()
        self.launched: list[FakePiperProcess] = []
        self.launch_threads: list[str] = []

    def __call__(self, args: list[str], *_pos: Any, **kwargs: Any) -> FakePiperProcess:
        self.spawning.set()
        if self.spawn_gate is not None:
            self.spawn_gate.wait(timeout=_READ_DEADLINE_S)
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
import tempfile
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


def _held(proc) -> dict[str, bool]:
    """BF-918 A2: what the worker still holds for a fake process; all False once it released everything."""
    out_dir = Path(proc.args[proc.args.index("--output_dir") + 1])
    return {
        "alive": proc.returncode is None,
        "stdin": not proc.stdin.closed,
        "stdout": not proc.stdout.closed,
        "stderr": not proc.kwargs["stderr"].closed,
        "directory": out_dir.exists(),
    }


_NOTHING_HELD = {"alive": False, "stdin": False, "stdout": False, "stderr": False, "directory": False}


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


class _FakeConverter:
    """BF-918 A2: stands in for ``subprocess.Popen`` for ffmpeg and rhubarb.

    An ffmpeg launch writes a WAV to its output path and runs ``on_convert`` on the
    conversion's own thread; any other launch is rhubarb (``self.rhubarb``).
    """

    def __init__(self, on_convert=None) -> None:
        self.converted: list[Path] = []
        self.rhubarb = _FakeRhubarb()
        self._on_convert = on_convert

    def __call__(self, args, *_a, **_kw):
        if args[1] == "-y":  # ffmpeg -y -i <input> ... <output>
            out = Path(args[-1])
            out.write_bytes(_WAV)
            self.converted.append(out)
            if self._on_convert is not None:
                self._on_convert()
            return SimpleNamespace(
                returncode=0,
                communicate=lambda input=None, timeout=None: (None, b""),
                kill=lambda: None,
                wait=lambda timeout=None: 0,
            )
        return self.rhubarb(args, *_a, **_kw)


def _webm_attachment(rt, target: Path, tmp_path: Path) -> str:
    """A browser-captured WebM in the store, with rhubarb and ffmpeg configured (both faked)."""
    rhubarb_bin = tmp_path / "rhubarb"
    rhubarb_bin.write_bytes(b"")
    ffmpeg_bin = tmp_path / "ffmpeg"
    ffmpeg_bin.write_bytes(b"")
    rt.config.lipsync = LipSyncConfig(
        backend="rhubarb", binary_path=str(rhubarb_bin), ffmpeg_binary_path=str(ffmpeg_bin),
    )
    blob = b"webm capture"
    sha = hashlib.sha256(blob).hexdigest()
    (target / f"{sha}.webm").write_bytes(blob)
    return sha


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
    fake = launcher("empty", "ok")
    assert await service.synthesize(_key(), "hi", 5.0) is None
    assert "0 bytes" in caplog.text
    assert _held(fake.launched[0]) == _NOTHING_HELD  # retired, and released
    # Recovery control (A2): the next request starts a new process and is answered.
    assert await service.synthesize(_key(), "hi", 5.0) == _WAV
    assert len(fake.launched) == 2


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
        assert _held(by_model["b.onnx"]) == _NOTHING_HELD  # control for B2: its close ran to the end
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
    assert _held(fake.launched[0]) == _NOTHING_HELD  # control for B1: an idle worker
    assert svc.closed is True
    assert await svc.synthesize(_key(), "x", 5.0) is None
    with svc.admit() as admitted:
        assert admitted is False


def test_a_closed_worker_refuses_a_request_and_starts_nothing(launcher) -> None:
    """BF-918 A2 (B1): a request that reaches a worker after its close starts no process."""
    fake = launcher("ok")
    worker = resident.PiperWorker(_key())
    other = resident.PiperWorker(_key())
    try:
        worker.close()
        outcome = worker.synthesize_blocking("x", 5.0)
        assert outcome.audio is None and outcome.reason == "closed"
        assert fake.launched == []
        # Positive control: an open worker starts its process and answers.
        assert other.synthesize_blocking("x", 5.0).audio == _WAV
        assert len(fake.launched) == 1
    finally:
        worker.close()
        other.close()


@pytest.mark.asyncio
async def test_close_while_a_request_runs_releases_the_worker_when_it_returns(launcher) -> None:
    """BF-918 A2 (B1): shutdown kills a busy worker, never closes its pipes under the read, and the request releases it."""
    release = threading.Event()
    fake = launcher("gate", release=release)
    svc = VoiceSynthesisService()
    try:
        task = asyncio.create_task(svc.synthesize(_key(), "busy", 5.0))
        await _until(lambda: bool(fake.launched) and bool(fake.launched[0].requests))
        proc = fake.launched[0]

        svc.close()

        assert proc.killed is True
        held = _held(proc)
        assert held["stdin"] and held["stdout"] and held["stderr"] and held["directory"]  # not under the read
        release.set()
        assert await asyncio.wait_for(task, timeout=5.0) == _WAV  # the WAV was made: it is delivered
        assert _held(proc) == _NOTHING_HELD
        assert svc.resident_count == 0
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_close_while_the_process_starts_kills_it_and_releases_everything(launcher, caplog) -> None:
    """BF-918 A2 (B1): shutdown overlaps Popen; the process it could not see yet is killed once it exists."""
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.resident")
    gate = threading.Event()
    fake = launcher("ok", spawn_gate=gate)
    svc = VoiceSynthesisService()
    try:
        task = asyncio.create_task(svc.synthesize(_key(), "starting", 5.0))
        await _until(fake.spawning.is_set)

        svc.close()
        gate.set()

        assert await asyncio.wait_for(task, timeout=5.0) is None
        proc = fake.launched[0]
        assert proc.killed is True and proc.requests == []
        assert _held(proc) == _NOTHING_HELD
        assert not [r for r in caplog.records if r.name == "probos.audio.tts.resident"]  # not a piper failure
    finally:
        gate.set()
        svc.close()


@pytest.mark.asyncio
async def test_a_failed_stderr_open_still_releases_the_worker_directory(launcher, monkeypatch, tmp_path: Path, caplog) -> None:
    """BF-918 A5 (round 2, B finding 1): the worker owns its directory from its creation, so a failed stderr open leaves none behind."""
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.resident")
    fake = launcher("ok")
    temp_dir = tmp_path / "workers"
    temp_dir.mkdir()
    made: list[Path] = []

    def mkdtemp_first_without_stderr(prefix: str = "tmp", **_kwargs) -> str:
        directory = temp_dir / f"{prefix}{len(made)}"
        directory.mkdir()
        if not made:  # the first worker directory only: a directory named stderr.log makes its open fail
            (directory / "stderr.log").mkdir()
        made.append(directory)
        return str(directory)

    monkeypatch.setattr(resident.tempfile, "mkdtemp", mkdtemp_first_without_stderr)
    svc = VoiceSynthesisService()
    try:
        assert await svc.synthesize(_key(), "x", 5.0) is None  # degrades
        assert fake.launched == [] and len(made) == 1  # it failed after the directory, before Popen
        assert "stderr.log" in caplog.text  # control: the logged failure is the stderr open
        assert not made[0].exists()  # the failed request's retirement removed it

        # Recovery control: the next request gets a new directory, starts a process and answers.
        assert await svc.synthesize(_key(), "y", 5.0) == _WAV
        assert len(fake.launched) == 1 and len(made) == 2
        assert made[1].is_dir()  # the resident worker's directory, visible while it lives
    finally:
        svc.close()
        svc.close()  # idempotent
    assert list(temp_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_shutdown_closes_a_retiring_worker_and_the_request_degrades(launcher) -> None:
    """BF-918 A2 (B2): the evicted worker's close is queued behind a busy voice thread when shutdown comes."""
    fake = launcher("ok")
    svc = VoiceSynthesisService(workers=1, max_resident=1)
    release = threading.Event()
    try:
        assert await svc.synthesize(_key("a.onnx"), "x", 5.0) == _WAV
        evicted = fake.launched[0]
        svc.executor.submit(release.wait, 10)  # the only voice thread is busy
        task = asyncio.create_task(svc.synthesize(_key("b.onnx"), "y", 5.0))
        await _until(lambda: evicted.killed)  # evicted, and its close is queued

        svc.close()

        assert _held(evicted) == _NOTHING_HELD  # released by close itself, before the request resumes
        release.set()
        assert await asyncio.gather(task, return_exceptions=True) == [None]
        assert len(fake.launched) == 1
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_a_cancelled_retirement_still_closes_the_worker(launcher) -> None:
    """BF-918 A2 (B2): the caller goes away while the evicted worker's close is queued."""
    fake = launcher("ok")
    svc = VoiceSynthesisService(workers=1, max_resident=1)
    release = threading.Event()
    try:
        assert await svc.synthesize(_key("a.onnx"), "x", 5.0) == _WAV
        evicted = fake.launched[0]
        svc.executor.submit(release.wait, 10)
        task = asyncio.create_task(svc.synthesize(_key("b.onnx"), "y", 5.0))
        await _until(lambda: evicted.killed)

        task.cancel()
        done, _pending = await asyncio.wait({task}, timeout=2.0)

        assert task in done and task.cancelled()  # the caller's own cancellation propagates
        assert _held(evicted) == _NOTHING_HELD
        assert len(fake.launched) == 1
    finally:
        release.set()
        svc.close()


@pytest.mark.asyncio
async def test_shutdown_degrades_a_queued_request_instead_of_cancelling_it(launcher) -> None:
    """BF-918 A2 (B2): shutdown cancels queued voice work; its request answers None, as a refusal does."""
    fake = launcher("ok")
    svc = VoiceSynthesisService(workers=1)
    release = threading.Event()
    try:
        svc.executor.submit(release.wait, 10)
        task = asyncio.create_task(svc.synthesize(_key(), "queued", 5.0))
        await _until(lambda: svc.resident_count == 1)  # claimed, and its request is queued

        svc.close()
        release.set()

        assert await asyncio.gather(task, return_exceptions=True) == [None]
        assert fake.launched == []
    finally:
        release.set()
        svc.close()


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
async def test_lipsync_converts_then_runs_rhubarb_on_the_voice_executor(voice_client, monkeypatch, tmp_path: Path) -> None:
    """Control for B3: nothing overlaps; a captured WebM is converted, read by rhubarb, and its converted file removed."""
    client, rt, target = voice_client
    fake = _FakeConverter()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    sha = _webm_attachment(rt, target, tmp_path)

    resp = await client.post("/api/avatars/lipsync", json={"attachment_id": sha})

    assert resp.status_code == 200 and resp.json()["backend"] == "rhubarb"
    assert len(fake.converted) == 1 and not fake.converted[0].exists()
    assert fake.rhubarb.threads and fake.rhubarb.threads[0].startswith("probos-voice")


@pytest.mark.asyncio
async def test_lipsync_degrades_when_the_executor_closes_between_conversion_and_rhubarb(voice_client, monkeypatch, tmp_path: Path) -> None:
    """BF-918 A2 (B3): shutdown closes the voice executor while ffmpeg runs; the rhubarb stage is refused and degrades."""
    client, rt, target = voice_client
    loop = asyncio.get_running_loop()
    voice = rt.voice_synthesis

    def _close_during_conversion() -> None:
        loop.call_soon_threadsafe(voice.close)
        deadline = time.monotonic() + 5.0
        while not voice.closed and time.monotonic() < deadline:
            time.sleep(0.005)

    fake = _FakeConverter(on_convert=_close_during_conversion)
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    sha = _webm_attachment(rt, target, tmp_path)

    resp = await client.post("/api/avatars/lipsync", json={"attachment_id": sha})

    assert voice.closed is True
    assert resp.status_code == 200
    assert resp.json() == {"backend": "heuristic", "frames": []}
    assert fake.rhubarb.threads == []  # the refused stage started nothing
    assert len(fake.converted) == 1 and not fake.converted[0].exists()


@pytest.mark.asyncio
async def test_lipsync_degrades_and_removes_its_temp_file_when_shutdown_cancels_the_conversion(voice_client, monkeypatch, tmp_path: Path) -> None:
    """BF-918 A2 (B3): the conversion is queued behind a busy voice thread when shutdown cancels it."""
    client, rt, target = voice_client
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_dir))
    fake = _FakeConverter()
    monkeypatch.setattr(rhubarb_backend.subprocess, "Popen", fake)
    sha = _webm_attachment(rt, target, tmp_path)
    voice = VoiceSynthesisService(workers=1)
    rt.voice_synthesis = voice
    release = threading.Event()
    try:
        voice.executor.submit(release.wait, 10)
        task = asyncio.create_task(client.post("/api/avatars/lipsync", json={"attachment_id": sha}))
        await _until(lambda: any(temp_dir.glob("*.wav")))  # the output file exists; its work is queued

        voice.close()
        release.set()
        (resp,) = await asyncio.gather(task, return_exceptions=True)

        assert not isinstance(resp, BaseException), resp
        assert resp.status_code == 200 and resp.json() == {"backend": "heuristic", "frames": []}
        assert fake.converted == [] and fake.rhubarb.threads == []
        assert list(temp_dir.iterdir()) == []
    finally:
        release.set()
        voice.close()


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

/** BF-918 (review round 1, D7a): the `dropped` reason of a dispatched utterance that
 *  lost the device (a stop, or a newer dispatch) before any of its audio started.
 *  It emitted no 'start', so it emits no 'end' (BF-655 pairs them); AD-1291's
 *  'dropped' is its terminal event, and the arbiter's wait ends on it. */
const CANCELLED_BEFORE_AUDIO = 'cancelled-before-audio';

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
        const played = await runPrefetchQueue<PreparedSpeech>(
          sentences,
          (sentence) => _prepareServerSpeech(sentence, profile, emotion),
          (prepared, sentence) => _playPreparedSpeech(prepared, sentence, profile, agent_id, utterance_id),
          () => _activeUtteranceId === utterance_id,
          TTS_PREFETCH_LOOKAHEAD,
          _discardPreparedSpeech,
        );
        // BF-918 (review round 1, D7a): stopped before its first sentence played. No
        // 'start' fired, so no 'end' will: 'dropped' ends this utterance for the arbiter.
        if (played === 0) _fireDropped(entry, CANCELLED_BEFORE_AUDIO);
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
 *  utterance instead. BF-918 (review round 1, D7a): resolves `false`, having
 *  started nothing, when the utterance lost the device (a stop, or a newer
 *  dispatch) while it synthesized: its audio is discarded unplayed, and a failed
 *  synthesis does not fall back to the browser. `true` otherwise. */
async function _synthesizeAndPlay(
  text: string,
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
  emotion: string | undefined,
  utterance_id: number,
): Promise<boolean> {
  const prepared = await _prepareServerSpeech(text, profile, emotion);
  if (_activeUtteranceId !== utterance_id) { _discardPreparedSpeech(prepared); return false; }
  await _playPreparedSpeech(prepared, text, profile, agent_id, utterance_id);
  return true;
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
        // BF-918 (review round 1): pausing a play() that has not started playback
        // rejects it (AbortError) AFTER the 'pause' listener above fired this
        // utterance's one terminal 'end'. A stop or a newer dispatch did that, so it
        // was cancelled, not failed: speak nothing in its place.
        if (_activeUtteranceId !== utterance_id) { _finish(false); return; }
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

/** Review round 1: how the fake's play() settles. 'resolve': at once, as when
 *  playback starts. 'hold': pending, as a real element's is while its WAV still
 *  loads; a pause() meanwhile fires 'pause' and then rejects it with AbortError
 *  (the HTML pause steps; the reviewer measured this order in Chromium).
 *  'blocked': refused by the autoplay policy (NotAllowedError), and no 'play'. */
let playMode: 'resolve' | 'hold' | 'blocked' = 'resolve';

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  played = false;
  discarded = false;
  private _listeners: Record<string, Array<() => void>> = {};
  private _rejectPlay: ((err: unknown) => void) | null = null;
  pause = vi.fn(() => {
    this.emit('pause');
    const reject = this._rejectPlay;
    this._rejectPlay = null;
    if (reject !== null) reject(new DOMException('The play() request was interrupted by a call to pause().', 'AbortError'));
  });
  play = vi.fn((): Promise<void> => {
    if (playMode === 'blocked') {
      return Promise.reject(new DOMException('play() failed because the user did not interact with the document first.', 'NotAllowedError'));
    }
    this.played = true;
    this.emit('play');
    if (playMode === 'resolve') return Promise.resolve();
    return new Promise<void>((_resolve, reject) => { this._rejectPlay = reject; });
  });
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
  backend?: string;
  holdStatus?: boolean;
  failTts?: number[];
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
      const status = { ok: true, json: async () => ({ enabled: true, backend: plan.backend ?? 'piper', sentence_pipelining_enabled: plan.pipelining }) };
      if (plan.holdStatus) { plan.holdStatus = false; return new Promise((resolve) => { held.push(() => resolve(status)); }); }
      return status;
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
      const answer = plan.failTts?.includes(nth) ? { ok: false, json: async () => ({}) } : response;
      if (plan.holdTts?.includes(nth)) return new Promise((resolve) => { held.push(() => resolve(answer)); });
      return answer;
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

beforeEach(() => { _installGlobals(); playMode = 'resolve'; });
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
      const audiosWhileOnePlayed = createdAudios.length;

      voiceMod.stopSpeaking();
      await _flush();

      // Review round 1: the cancellation first, so a tree without it fails here,
      // not at the prefetch premise below.
      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(events.filter((e) => e.startsWith('start'))).toEqual(['start:One.']);
      expect(events.filter((e) => e.startsWith('end'))).toEqual(['end:One.']);
      expect(events.filter((e) => e.startsWith('dropped'))).toEqual([]); // its audio started: it ends, it is not dropped
      // The prefetch premise: sentence two had been prepared while one played.
      expect(audiosWhileOnePlayed).toBe(2);
      expect(f.posted).toEqual(['One.', 'Two.']);
      expect(createdAudios[1].played).toBe(false);
      expect(createdAudios[1].discarded).toBe(true);
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
      const postedWhileOnePlayed = [...f.posted];
      const audiosWhileOnePlayed = createdAudios.length; // Two's response has not arrived

      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      // Review round 1: the cancellation first (see P2).
      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(starts).toEqual(['One.']);
      expect(createdAudios.length).toBe(2); // made when its response arrived...
      expect(createdAudios[1].played).toBe(false); // ...and never played
      expect(createdAudios[1].discarded).toBe(true);
      // The prefetch premise: Two was requested while One played, and was in flight.
      expect(postedWhileOnePlayed).toEqual(['One.', 'Two.']);
      expect(audiosWhileOnePlayed).toBe(1);
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

describe('BF-918 review round 1: a stop before audio, and a stop of a pending play (D7a)', () => {
  const spoken = (): string[] => speakCalls.map((u) => (u as FakeUtterance).text);

  async function _record() {
    const voiceMod = await import('../voice');
    const events: string[] = [];
    const drops: Array<{ id?: number; reason?: string }> = [];
    const off = voiceMod.onSpeechEvent((e) => {
      events.push(`${e.type}:${e.source ?? ''}:${e.utterance?.text ?? ''}`);
      if (e.type === 'dropped') drops.push({ id: e.utterance_id, reason: e.reason });
    });
    return { events, drops, off };
  }

  it('P9 pipelined: a stop while sentence one synthesizes plays nothing and frees the arbiter for the next reply (C1)', async () => {
    const f = _makeFetch({ pipelining: true, holdTts: [1] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      const stopped = voiceMod.speakResponse('One. Two.');
      await _flush();
      expect(f.posted).toEqual(['One.']); // sentence one is synthesizing; nothing plays yet
      expect(createdAudios.length).toBe(0);

      voiceMod.stopSpeaking();
      await _flush();
      f.release(); // its synthesis answers after the stop
      await _flush();
      voiceMod.speakResponse('Next.');
      await _flush();

      // C1: the next reply is dispatched now, not after SPEECH_JOIN_TIMEOUT_MS.
      expect(f.posted).toEqual(['One.', 'Next.']);
      expect(createdAudios.map((a) => a.played)).toEqual([false, true]);
      expect(createdAudios[0].discarded).toBe(true);
      // No 'start' for the stopped reply, so no 'end': one 'dropped' ends it.
      expect(r.events).toEqual(['dropped::One. Two.', 'start:server:Next.']);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
    } finally {
      r.off();
    }
  });

  it('P10 single call: a reply whose synthesis answers after a stop is never played, and the next reply is dispatched (C3)', async () => {
    const f = _makeFetch({ pipelining: false, holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      // Control: an answer that arrives with no stop plays.
      voiceMod.speakResponse('Control.');
      await _flush();
      expect(createdAudios[0].played).toBe(true);
      createdAudios[0].end();
      await _flush();

      const stopped = voiceMod.speakResponse('Only one.');
      await _flush();
      expect(f.posted).toEqual(['Control.', 'Only one.']);
      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      expect(createdAudios.length).toBe(2);
      expect(createdAudios[1].played).toBe(false); // C3: nothing starts after the stop
      expect(createdAudios[1].discarded).toBe(true);
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['Control.', 'Only one.', 'Next.']);
      expect(r.events.filter((e) => !e.startsWith('end'))).toEqual(['start:server:Control.', 'dropped::Only one.', 'start:server:Next.']);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
    } finally {
      r.off();
    }
  });

  it('P11 a synthesis that fails after a stop is not spoken by the browser either; unstopped, it is (C3)', async () => {
    const f = _makeFetch({ pipelining: false, failTts: [1, 2], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      // Control: an unstopped reply whose synthesis fails is spoken by the browser.
      voiceMod.speakResponse('Control.');
      await _flush();
      expect(spoken()).toEqual(['Control.']);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();

      const stopped = voiceMod.speakResponse('Only one.');
      await _flush();
      expect(f.posted).toEqual(['Control.', 'Only one.']);
      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      expect(spoken()).toEqual(['Control.']); // C3: no fallback after the stop
      expect(createdAudios.length).toBe(0);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
    } finally {
      r.off();
    }
  });

  it('P12 a stop during the first status probe speaks nothing; the next reply is spoken (C3)', async () => {
    const f = _makeFetch({ pipelining: false, backend: 'browser', holdStatus: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      const stopped = voiceMod.speakResponse('Probe.');
      await _flush();
      expect(spoken()).toEqual([]); // the probe has not answered
      voiceMod.stopSpeaking();
      f.release();
      await _flush();

      expect(spoken()).toEqual([]);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
      // Control: the next reply, with the browser backend now cached, is spoken, with no POST.
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(spoken()).toEqual(['Next.']);
      expect(f.posted).toEqual([]);
    } finally {
      r.off();
    }
  });

  it('P13 a stop while play() is still pending ends that utterance once and speaks nothing in its place (C2)', async () => {
    const f = _makeFetch({ pipelining: false });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      // Control: a play() the autoplay policy refuses, with no stop, is spoken by the browser.
      playMode = 'blocked';
      voiceMod.speakResponse('Refused.');
      await _flush();
      expect(spoken()).toEqual(['Refused.']);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      r.events.length = 0;

      // The WAV is still loading, so play() is pending when the stop pauses it.
      playMode = 'hold';
      voiceMod.speakResponse('Pending.');
      await _flush();
      expect(createdAudios[1].played).toBe(true); // its 'play' fired: the server 'start' is out
      voiceMod.stopSpeaking();
      await _flush();
      expect(createdAudios[1].pause).toHaveBeenCalled();
      expect(spoken()).toEqual(['Refused.']); // C2: nothing speaks in its place

      // Control: a play() that had resolved (playback started) when the stop came.
      playMode = 'resolve';
      voiceMod.speakResponse('Playing.');
      await _flush();
      voiceMod.stopSpeaking();
      await _flush();
      expect(spoken()).toEqual(['Refused.']);
      // Exactly one terminal 'end' for each 'start', and nothing dropped.
      expect(r.events).toEqual(['start:server:Pending.', 'end:server:Pending.', 'start:server:Playing.', 'end:server:Playing.']);
    } finally {
      r.off();
    }
  });
});
```

### 7.30a `ui/src/audio/voice.ts` (M3: review round 1, C1 and C3; apply after §7.26)

These pairs change lines that §7.26 leaves as they are; each SEARCH is the file after §7.26. D7a is the rule.

Pair 1 of 3:

SEARCH:
```ts
    const unsub = onSpeechEvent((event) => {
      if (event.type !== 'end') return;
      if (event.utterance_id !== entry.id) return;
      done();
    });
```
REPLACE:
```ts
    const unsub = onSpeechEvent((event) => {
      // BF-918 (#1626, review round 1): or its own 'dropped'. A dispatched entry that
      // lost the device before any of its audio started emits no 'start' and so no
      // 'end'; `_playNow` fires 'dropped' for it (D7a). Nothing else drops a started
      // entry: pre-emption and `flushSpeechQueue` skip them.
      if (event.type !== 'end' && event.type !== 'dropped') return;
      if (event.utterance_id !== entry.id) return;
      done();
    });
```

Pair 2 of 3:

SEARCH:
```ts
    const status = await _fetchTtsStatus();
    if (status === null || !status.enabled || status.backend !== 'piper') {
```
REPLACE:
```ts
    const status = await _fetchTtsStatus();
    // BF-918 (review round 1, D7a): each await between dispatch and audio re-checks
    // that this utterance still owns the device. Stopped during the probe: speak nothing.
    if (_activeUtteranceId !== utterance_id) { _fireDropped(entry, CANCELLED_BEFORE_AUDIO); return; }
    if (status === null || !status.enabled || status.backend !== 'piper') {
```

Pair 3 of 3:

SEARCH:
```ts
    // Single-call path (default): one TTS POST for the whole reply.
    await _synthesizeAndPlay(text, profile, agent_id, emotion, utterance_id);
```
REPLACE:
```ts
    // Single-call path (default): one TTS POST for the whole reply. BF-918 (review
    // round 1, D7a): `false` means it lost the device before its audio started.
    if (!(await _synthesizeAndPlay(text, profile, agent_id, emotion, utterance_id))) _fireDropped(entry, CANCELLED_BEFORE_AUDIO);
```

### 7.30b `ui/src/components/profile/ProfileChatTab.tsx` (M3: review round 2, C finding 1; base text)

Candidate 3 does not otherwise change this file; each SEARCH is its text at `origin/main` `26bec26d`. D7a is the rule. BF-718, BF-767 and BF-290 keep their behaviour; the lost-claim wait is unchanged.

Pair 1 of 4: withdrawn in review round 3 (A9). The component-wide reply counter it declared let one count span several arms, so a closed or switched arm's late `dropped` still matched; the counter is now `replyTurn` inside the 1:1 arm (§7.30f pair 2), and the component's ref declarations stay as on the base.

Pair 2 of 4:

SEARCH:
```tsx
  // over-matching there ended the wrong turn.
  useEffect(() => onSpeechEvent((event) => {
    if (event.type !== 'end') return;
    const ended = event.agent_id;
```
REPLACE:
```tsx
  // over-matching there ended the wrong turn.
  // BF-918 (#1626, review round 2): or it was dropped. A dispatched utterance that
  // lost the device before any of its audio started ends with 'dropped'
  // (`cancelled-before-audio`), never 'end', and a pre-empted or flushed entry
  // never played at all. Keeping its key made a later identical answer wait on an
  // 'end' that nothing would emit. Same per-agent rule, same direction of error (R20).
  useEffect(() => onSpeechEvent((event) => {
    if (event.type !== 'end' && event.type !== 'dropped') return;
    const ended = event.agent_id;
```

Pair 3 of 4:

SEARCH:
```tsx
      onAgentReply: (replyText: string) => {
        // 1. Append to the per-agent conversation so the operator sees it
        // in the DM thread.
```
REPLACE:
```tsx
      onAgentReply: (replyText: string) => {
        // BF-918 (review rounds 2 and 3): this reply now holds this arm's turn.
        const ourTurn = ++replyTurn;
        // 1. Append to the per-agent conversation so the operator sees it
        // in the DM thread.
```

Pair 4 of 4:

SEARCH:
```tsx
        let ourUtteranceId: number | undefined;
        let completed = false;
        const complete = (): void => {
          if (completed) return;
          completed = true;
          try { unsub(); } catch { /* Tier-2 */ }
          markAgentReplyComplete();
        };
        const unsub = onSpeechEvent((event) => {
          if (event.type !== 'end') return;
```
REPLACE:
```tsx
        let ourUtteranceId: number | undefined;
        let completed = false;
        const retire = (): boolean => {
          if (completed) return false;
          completed = true;
          pendingReplies.delete(retire);
          try { unsub(); } catch { /* Tier-2 */ }
          return true;
        };
        const complete = (): void => {
          if (retire()) markAgentReplyComplete();
        };
        const unsub = onSpeechEvent((event) => {
          // BF-918 (#1626, review round 2): this reply's OWN utterance never reached
          // audio (a stop, or a newer dispatch, before its first 'start'), so its
          // terminal event is 'dropped' and no 'end' is coming. Retire this
          // listener, and complete the turn only if no later reply of this arm has
          // taken the controller since: a late 'dropped' must not end a newer turn.
          // Never a synthetic 'end' (BF-767). The lost-claim path cannot know the id
          // and keeps waiting on the agent's 'end' (BF-718) until its arm ends.
          if (event.type === 'dropped') {
            if (!claimed || event.utterance_id !== ourUtteranceId) return;
            if (replyTurn !== ourTurn) { retire(); return; }
            complete();
            return;
          }
          if (event.type !== 'end') return;
```

### 7.30c `ui/src/audio/speechQueueStore.ts` (M3: review round 2, C finding 3; base text)

One pair, a comment only. Candidate 3 does not otherwise change this file; the SEARCH is its base text.

SEARCH:
```ts
  /** True once the entry has been handed to the device. A started entry is
   *  never dropped -- only queued-but-unstarted ones are, because dropping a
   *  started one would cut audio the Captain is already hearing. */
  started: boolean;
```
REPLACE:
```ts
  /** True once the entry has been handed to the device: dispatched, which does
   *  not mean its audio has started. Pre-emption and `flushSpeechQueue` skip a
   *  started entry -- only queued-but-unstarted ones are dropped that way,
   *  because dropping a started one could cut audio the Captain is already
   *  hearing. BF-918 (#1626, D7a): a started entry that lost the device before
   *  any of its audio started (a stop, or a newer dispatch) still ends with
   *  'dropped', reason `cancelled-before-audio`, fired by `_playNow`. */
  started: boolean;
```

### 7.30d `ui/src/audio/voice.ts` (M3: review round 2, the same kind as C finding 3; apply after §7.30a)

One pair, a comment only. §7.26 and §7.30a leave this text as it is, so the SEARCH is the base text.

SEARCH:
```ts
/** AD-1291: drop every queued-but-unstarted entry, each with an observable
 *  reason. The IN-FLIGHT entry is deliberately left alone -- stopping audio is
 *  `stopSpeaking`'s job, and its consumers must still receive that utterance's
 *  terminal 'end'.
```
REPLACE:
```ts
/** AD-1291: drop every queued-but-unstarted entry, each with an observable
 *  reason. The IN-FLIGHT entry is deliberately left alone -- stopping audio is
 *  `stopSpeaking`'s job, and its consumers must still receive that utterance's
 *  own terminal event: 'end' once its audio started, or BF-918's 'dropped'
 *  (`cancelled-before-audio`, D7a) from `_playNow` when it lost the device first.
```

### 7.30e New file: `ui/src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx` (M3: review round 2, C finding 1)

```tsx
/** BF-918 (#1626), review round 2, area C finding 1: a conversation-mode reply
 *  stopped before any of its audio started ends with AD-1291's 'dropped'
 *  (`cancelled-before-audio`, D7a), never 'end'. ProfileChatTab must release on
 *  it what an 'end' releases: the BF-718 in-flight key (otherwise a later
 *  identical answer, which loses the speech claim, waits on an 'end' that no
 *  utterance will emit, and the controller stays `agent_speaking`), and the
 *  reply's own completion listener, which completes the turn only while that
 *  reply is still the newest.
 *
 *  Real ProfileChatTab, conversation controller, voice.ts and speech arbiter.
 *  Doubles only at the boundaries: fetch (the TTS POST is HELD until the test
 *  answers it, which is how a stop lands before the audio), the media element,
 *  speechSynthesis, and the microphone / STT / VAD taps. Adapted from the
 *  round-2 reviewer's executed probe.
 *
 *  Assertions are on the controller's state (the turn), never on which branch ran.
 */
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, type RenderResult } from '@testing-library/react';

const hardware = vi.hoisted(() => ({
  transcripts: new Set<(text: string) => void>(),
  pcm: new Set<{ onSpeechStart?: () => void }>(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));

vi.mock('../../../audio/transformersStt', () => ({
  armTransformersStt: () => () => {},
  disarmTransformersStt: () => {},
  onTransformersTranscript: (fn: (text: string) => void) => {
    hardware.transcripts.add(fn);
    return () => { hardware.transcripts.delete(fn); };
  },
  onTransformersTranscribing: () => () => {},
  onTransformersProgress: () => () => {},
}));

vi.mock('../../../audio/voiceActivity', () => ({
  subscribePcm: (handler: { onSpeechStart?: () => void }) => {
    hardware.pcm.add(handler);
    return () => { hardware.pcm.delete(handler); };
  },
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore } from '../../../store/useStore';
import * as voice from '../../../audio/voice';
import {
  getConversationState,
  onConversationState,
  _resetConversationControllerForTests,
} from '../../../audio/conversationController';
import { _resetForTests as resetMicArbiter } from '../../../audio/speechRecognitionArbiter';

const REPEATED = 'Repeatable answer.';
const CANCELLED: [string, string | undefined] = ['dropped', 'cancelled-before-audio'];

let audios: MediaDouble[] = [];
let held: Array<() => void> = [];
let ttsPosts: string[] = [];
let chats = 0;
let answers: string[] = [];
let events: Array<[string, string | undefined]> = [];
let off: () => void = () => {};

class UtteranceDouble {
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: unknown = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  text: string;
  constructor(text: string) { this.text = text; }
}

/** The media element. `play` resolves: in these cases the stop lands while the
 *  synthesis answer is still held, before any audio exists. */
class MediaDouble {
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  played = false;
  src: string;
  private listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) { this.src = src; audios.push(this); }
  addEventListener(type: string, fn: () => void): void { (this.listeners[type] ??= []).push(fn); }
  emit(type: string): void { for (const fn of this.listeners[type] ?? []) fn(); }
  play(): Promise<void> { this.played = true; this.emit('play'); return Promise.resolve(); }
  pause(): void { this.emit('pause'); }
  removeAttribute(): void { this.src = ''; }
  load(): void { /* double */ }
  end(): void { this.emit('ended'); }
}

function respond(body: unknown): Response {
  return { ok: true, json: async () => body } as unknown as Response;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 60; i += 1) await Promise.resolve();
}

async function arm(): Promise<void> {
  render(<ProfileChatTab agentId="a1" />);
  await waitFor(() => expect(getConversationState()).toBe('listening'));
  expect(hardware.transcripts.size).toBe(1);
}

async function captainSays(text: string): Promise<void> {
  await act(async () => { for (const cb of [...hardware.transcripts]) cb(text); await flush(); });
}

async function bargeIn(): Promise<void> {
  await act(async () => { for (const h of [...hardware.pcm]) h.onSpeechStart?.(); await flush(); });
}

async function answerSynthesis(): Promise<void> {
  const next = held.shift();
  expect(next).toBeDefined();
  await act(async () => { next?.(); await flush(); });
}

async function endAudio(audio: MediaDouble): Promise<void> {
  await act(async () => { audio.end(); await flush(); });
}

beforeEach(() => {
  hardware.transcripts.clear();
  hardware.pcm.clear();
  resetMicArbiter();
  _resetConversationControllerForTests();
  voice._resetTtsStatusForTests();
  audios = [];
  held = [];
  ttsPosts = [];
  chats = 0;
  answers = [];
  events = [];
  vi.stubGlobal('Audio', MediaDouble);
  vi.stubGlobal('SpeechSynthesisUtterance', UtteranceDouble);
  vi.stubGlobal('speechSynthesis', { cancel: vi.fn(), speak: vi.fn(), getVoices: () => [], addEventListener: vi.fn() });
  localStorage.clear();
  localStorage.setItem('hxi_chat_mic_mode_a1', 'conversation');
  localStorage.setItem('hxi_chat_tts_a1', '1');
  useStore.setState({
    voiceEnabled: true, agentConversations: new Map(), activeProfileThreadId: null, threadIdByAgent: new Map(),
  });
  Element.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
    const path = String(url);
    if (path.endsWith('/tts/status')) {
      return respond({ enabled: true, backend: 'piper', sentence_pipelining_enabled: false });
    }
    if (path === '/api/avatars/tts') {
      ttsPosts.push(JSON.parse(String(options?.body)).text);
      return new Promise<Response>((resolve) => {
        held.push(() => resolve(respond({ backend: 'piper', audio_attachment_id: 'a'.repeat(64), visemes: [] })));
      });
    }
    if (path === '/api/agent/a1/chat') {
      chats += 1;
      return respond({ response: answers.shift() ?? REPEATED });
    }
    if (path.endsWith('/chat/history')) return respond({ memories: [] });
    if (path.endsWith('/profile')) return respond({ voiceProfile: null });
    return respond({});
  }));
  off = voice.onSpeechEvent((e) => { events.push([e.type, e.reason]); });
});

afterEach(() => {
  off();
  cleanup();
  _resetConversationControllerForTests();
  resetMicArbiter();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('BF-918 review round 2: a dropped reply releases what its end would have released', () => {
  it('C1 control: a reply that ended leaves no in-flight claim, so a later identical answer completes at once', async () => {
    await arm();
    await captainSays('First question.');
    expect(chats).toBe(1);
    expect(ttsPosts).toEqual([REPEATED]);
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(audios).toHaveLength(1);
    expect(audios[0].played).toBe(true);
    await endAudio(audios[0]);
    expect(getConversationState()).toBe('silence_pending');
    await captainSays('Second question.');
    expect(chats).toBe(2);
    // BF-718: the same text was already said in this scope, so it is not spoken again.
    expect(ttsPosts).toEqual([REPEATED]);
    expect(events.map(([type]) => type)).toEqual(['start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C2: a reply stopped before its audio leaves no in-flight claim, so a later identical answer completes at once', async () => {
    await arm();
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    await bargeIn();
    expect(getConversationState()).toBe('listening');
    await answerSynthesis(); // the stopped reply's synthesis answers late
    expect(events).toEqual([CANCELLED]);
    expect(audios.every((audio) => !audio.played)).toBe(true);
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(ttsPosts).toEqual([REPEATED]);
    // Before the fix: `agent_speaking`, waiting on an 'end' that nothing emits.
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C3: the late drop of a stopped reply does not complete the newer turn', async () => {
    answers = ['First answer.', 'Second answer.'];
    await arm();
    await captainSays('First question.');
    await bargeIn();
    await captainSays('Second question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    // The newer reply waits in the arbiter behind the stopped one, whose synthesis is held.
    expect(ttsPosts).toEqual(['First answer.']);
    await answerSynthesis();
    expect(events).toEqual([CANCELLED]);
    await waitFor(() => expect(ttsPosts).toEqual(['First answer.', 'Second answer.']));
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await waitFor(() => expect(audios).toHaveLength(2));
    expect(audios[1].played).toBe(true);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(events.map(([type]) => type)).toEqual(['dropped', 'start', 'end']);
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C4: a reply whose own audio never started completes its turn while it is still the newest', async () => {
    await arm();
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    // A stop the controller did not make (GUARD 2's newer dispatch lands the same
    // 'dropped'): the controller is still waiting on this turn's speech.
    await act(async () => { voice.stopSpeaking(); await flush(); });
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(events).toEqual([CANCELLED]);
    // Before the fix: `agent_speaking`, with no silence-release timer.
    expect(getConversationState()).toBe('silence_pending');
  });
});

/** BF-918 (#1626), review round 3, area C finding 1: a reply's completion
 *  listener ends with the conversation arm that set it up. The controller's
 *  `markAgentReplyComplete` completes whichever arm owns it when it is called,
 *  so a listener that outlived its arm ended the NEXT arm's turn on its own late
 *  'dropped' (the round-2 repair) or 'end' (as on main). One case per way an arm
 *  ends. Each old reply is agent a1's; each replacement queues in the speech
 *  arbiter behind it, so the replacement's controller is in `agent_speaking`
 *  when the old terminal event lands. Assertions are on the controller's state. */
describe('BF-918 review round 3: a reply completion ends with its arm', () => {
  let voiceProfileAnswer: unknown = null;
  let byAgent: Array<[string, string | undefined]> = [];
  let states: string[] = [];
  let offAgents: () => void = () => {};
  let offStates: () => void = () => {};

  beforeEach(() => {
    voiceProfileAnswer = null;
    byAgent = [];
    states = [];
    localStorage.setItem('hxi_chat_mic_mode_a2', 'conversation');
    localStorage.setItem('hxi_chat_tts_a2', '1');
    const outer = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (url: RequestInfo | URL, options?: RequestInit) => {
      const path = String(url);
      if (path === '/api/agent/a2/chat') {
        chats += 1;
        return respond({ response: answers.shift() ?? REPEATED });
      }
      if (path.endsWith('/profile')) return respond({ voiceProfile: voiceProfileAnswer });
      // A thread id (C9) is answered "not found": its transcript stays empty.
      if (path.startsWith('/api/threads/')) {
        return { ok: false, status: 404, json: async () => ({}) } as unknown as Response;
      }
      return outer(url, options);
    }));
    offAgents = voice.onSpeechEvent((e) => { byAgent.push([e.type, e.agent_id]); });
    offStates = onConversationState((state) => { states.push(state); });
  });

  afterEach(() => {
    offAgents();
    offStates();
  });

  async function armFor(agentId: string): Promise<RenderResult> {
    const view = render(<ProfileChatTab agentId={agentId} />);
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    return view;
  }

  /** The first reply's synthesis answers and its audio plays: an 'end' is coming. */
  async function oldReplyPlays(): Promise<MediaDouble> {
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(audios).toHaveLength(1);
    expect(audios[0].played).toBe(true);
    return audios[0];
  }

  /** The arm ends by `change` and a new arm takes the controller. */
  async function armEnds(change: () => Promise<void>): Promise<void> {
    await change();
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    expect(states).toContain('inactive');
  }

  /** The new arm's own reply. It queues behind the old utterance, which still
   *  owns the device, so its synthesis is not requested yet. */
  async function replacementAsks(): Promise<void> {
    await captainSays('Replacement question.');
    expect(chats).toBe(2);
    expect(getConversationState()).toBe('agent_speaking');
    expect(ttsPosts).toHaveLength(1);
  }

  async function oldEndLands(old: MediaDouble): Promise<void> {
    await endAudio(old);
    expect(byAgent.filter(([type, agent]) => type === 'end' && agent === 'a1')).toHaveLength(1);
  }

  /** Only the replacement's own audio ending may complete its turn. */
  async function replacementPlaysAndEnds(): Promise<void> {
    await waitFor(() => expect(ttsPosts).toHaveLength(2));
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    await waitFor(() => expect(audios).toHaveLength(2));
    expect(audios[1].played).toBe(true);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[1]);
    expect(getConversationState()).toBe('silence_pending');
  }

  async function selectMicMode(mode: 'ptt' | 'conversation'): Promise<void> {
    await act(async () => {
      fireEvent.contextMenu(screen.getByRole('button', { name: 'Voice input' }));
      await flush();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId(`profile-chat-mic-mode-${mode}`));
      await flush();
    });
  }

  it('C5: after an unmount, the old reply\'s late drop does not complete the next profile\'s turn', async () => {
    answers = ['Unmounted answer.', 'Replacement answer.'];
    const first = await armFor('a1');
    await captainSays('First question.');
    expect(ttsPosts).toEqual(['Unmounted answer.']);
    await bargeIn(); // stopped while its synthesis is held: its terminal event will be 'dropped'
    expect(getConversationState()).toBe('listening');
    first.unmount();
    expect(getConversationState()).toBe('inactive');
    await armFor('a2');
    await replacementAsks();
    await answerSynthesis(); // the unmounted reply's synthesis answers late
    expect(events).toEqual([CANCELLED]);
    expect(byAgent).toEqual([['dropped', 'a1']]);
    // Before the fix: `silence_pending`, the replacement's turn ended by the old drop.
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C6: after an unmount, the old reply\'s late end does not complete the next profile\'s turn', async () => {
    answers = ['Unmounted answer.', 'Replacement answer.'];
    const first = await armFor('a1');
    const old = await oldReplyPlays();
    first.unmount(); // its utterance is dispatched, so the unmount's flush leaves it playing
    expect(getConversationState()).toBe('inactive');
    await armFor('a2');
    await replacementAsks();
    await oldEndLands(old);
    // Before the fix, and on main: `silence_pending`, ended by the old reply's 'end'.
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C7: after the agent changes on the same mount, the old reply\'s late end does not complete the new turn', async () => {
    answers = ['Old agent answer.', 'New agent answer.'];
    const view = await armFor('a1');
    const old = await oldReplyPlays();
    await armEnds(async () => {
      await act(async () => { view.rerender(<ProfileChatTab agentId="a2" />); await flush(); });
    });
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C8: after mic mode goes conversation, off and back, the old reply\'s late end does not complete the re-armed turn', async () => {
    answers = ['Before the mode change.', 'After the mode change.'];
    await armFor('a1');
    const old = await oldReplyPlays();
    await selectMicMode('ptt');
    expect(getConversationState()).toBe('inactive');
    await armEnds(() => selectMicMode('conversation'));
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  // `ttsKey` is derived from `agentId` and `speechOwner` is fixed per mount, so
  // C7 and C5/C6 are their cases. `meetingActive` reaches a 1:1 arm again only
  // through a second change: the same React cleanup, with call speech this
  // harness does not model.
  const dependencyChanges: Array<[string, (view: RenderResult) => Promise<void>]> = [
    ['threadId', async (view) => {
      await act(async () => {
        view.rerender(<ProfileChatTab agentId="a1" threadId="bf918-thread" />);
        await flush();
      });
    }],
    ['voiceProfile', async () => {
      voiceProfileAnswer = { voice_name: 'test', pitch: 1, rate: 1, volume: 1 };
      await act(async () => {
        window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: 'a1' } }));
        await flush();
      });
    }],
    ['callAudioEnabled', async () => {
      await act(async () => {
        useStore.setState({ callAudioEnabled: !useStore.getState().callAudioEnabled });
        await flush();
      });
    }],
  ];

  it.each(dependencyChanges)('C9 (%s): after the arm re-runs on that change, the old reply\'s late end does not complete the new turn', async (_name, change) => {
    answers = ['Before the change.', 'After the change.'];
    const view = await armFor('a1');
    const old = await oldReplyPlays();
    await armEnds(() => change(view));
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C10: when a second profile arms, the first profile\'s late end does not complete the second one\'s turn', async () => {
    answers = ['First surface answer.', 'Second surface answer.'];
    await armFor('a1');
    const old = await oldReplyPlays();
    // The first profile stays mounted, so React never cleans its arm up: only the
    // controller's 'inactive' to its options tells it that its arm has ended.
    await armEnds(async () => { render(<ProfileChatTab agentId="a2" />); });
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });

  it('C11 control: under StrictMode\'s double effect run, a reply still completes on its own end', async () => {
    render(<React.StrictMode><ProfileChatTab agentId="a1" /></React.StrictMode>);
    await waitFor(() => expect(getConversationState()).toBe('listening'));
    await captainSays('First question.');
    expect(getConversationState()).toBe('agent_speaking');
    await answerSynthesis();
    expect(audios[0].played).toBe(true);
    expect(getConversationState()).toBe('agent_speaking');
    await endAudio(audios[0]);
    // BF-290's stuck turn would stay `agent_speaking` here.
    expect(getConversationState()).toBe('silence_pending');
  });

  it('C12: an unmount retires the reply even when the controller dropped the arm without telling it', async () => {
    answers = ['Unmounted answer.', 'Replacement answer.'];
    const first = await armFor('a1');
    const old = await oldReplyPlays();
    // The controller's test seam tears the arm down with no 'inactive' to its
    // options (as a pre-empted arm whose queued 'inactive' a later job superseded
    // would be): only the React cleanup is left to retire the reply.
    act(() => { _resetConversationControllerForTests(); });
    expect(getConversationState()).toBe('inactive');
    first.unmount();
    await armFor('a2');
    await replacementAsks();
    await oldEndLands(old);
    expect(getConversationState()).toBe('agent_speaking');
    await replacementPlaysAndEnds();
  });
});
```

### 7.30f `ui/src/components/profile/ProfileChatTab.tsx` (M3: review round 3, C F1 and C F2; base text; apply after §7.30b)

Four pairs. Each SEARCH is the file's text at `origin/main` `26bec26d`, occurs there once, and §7.30b's pairs leave it as it is. Pair 1 corrects the BF-718 comment (C F2, R20). Pairs 2 to 4 tie every reply completion to its 1:1 arm (C F1): the arm holds its replies' retire functions and its reply counter (pair 2; §7.30b pairs 3 and 4 read both), each reply puts its retire in the set before it can speak (pair 3), and the arm retires them when the controller tells it `'inactive'` and when React ends it (pair 4). `onAgentReply` gets no liveness check: the controller calls it only while that arm owns it (`conversationController.ts:433-435`). `conversationController.ts`, the meeting arm and the lost-claim rule are unchanged.

Pair 1 of 4:

SEARCH:
```tsx
  // here at all. Erring toward "not speaking" keeps a missed correlation from
  // stranding the conversation controller, which is the opposite of the
  // failure BF-767 fixes: over-clearing here costs a redundant wait, while
```
REPLACE:
```tsx
  // here at all. Erring toward "not speaking" keeps a missed correlation from
  // stranding the conversation controller, which is the opposite of the
  // failure BF-767 fixes. Over-clearing here is not free (BF-918, #1626: R20):
  // clearing another same-agent key lets a later lost claim on that key skip
  // its wait and complete the turn while that utterance still plays. The
  // alternative is worse:
```

Pair 2 of 4:

SEARCH:
```tsx
    // without enabling any voice output.
    const armOpts: ArmOptions = {
```
REPLACE:
```tsx
    // without enabling any voice output.
    //
    // BF-918 (#1626, review round 3, C F1): a completion a reply of THIS arm
    // sets up is retired when React's cleanup ends the arm (an unmount, or a
    // re-run of this effect) and when the controller delivers 'inactive' to
    // this arm (a newer arm, a pre-emption, the silence timer).
    // `markAgentReplyComplete` completes whichever arm owns the controller when
    // it is called, so a listener that outlived its arm ended the next arm's
    // turn on its own late 'end' or 'dropped'. Not covered (review rounds 4 and
    // 5): the controller does not always deliver 'inactive' (R21 in BF-918's
    // contract names the case); an arm it does not tell keeps its listeners
    // until React's cleanup. The reply counter is per arm for the same reason.
    // `onAgentReply` needs no liveness check of its own: the controller calls
    // it only while this arm owns it.
    const pendingReplies = new Set<() => boolean>();
    const retirePendingReplies = (): void => {
      for (const retireReply of [...pendingReplies]) retireReply();
    };
    let replyTurn = 0;
    const armOpts: ArmOptions = {
```

Pair 3 of 4:

SEARCH:
```tsx
          if (claimed && event.utterance_id !== ourUtteranceId) return;
          complete();
        });
        if (!claimed) return;
```
REPLACE:
```tsx
          if (claimed && event.utterance_id !== ourUtteranceId) return;
          complete();
        });
        // BF-918 (review round 3): this arm's end retires the listener, claimed or
        // not, and it is in the set before speakResponse can emit anything for it.
        pendingReplies.add(retire);
        if (!claimed) return;
```

Pair 4 of 4:

SEARCH:
```tsx
      onStateChange: (state) => {
        console.info(`AD-747/BF-290: conversation state for ${armAgentId}: ${state}`);
      },
    };
    console.info(`AD-760: mic mode ${mode} armed for agent ${armAgentId}`);
    const disposeConversation = armConversationMode(armOpts);
    return disposeConversation;
```
REPLACE:
```tsx
      onStateChange: (state) => {
        console.info(`AD-747/BF-290: conversation state for ${armAgentId}: ${state}`);
        // BF-918 (review round 3): the controller has ended this arm (a newer arm
        // took it, a pre-emption, the silence timer, or this arm's own dispose).
        // Nothing re-arms these options, so retiring is enough.
        if (state === 'inactive') retirePendingReplies();
      },
    };
    console.info(`AD-760: mic mode ${mode} armed for agent ${armAgentId}`);
    const disposeConversation = armConversationMode(armOpts);
    // BF-918 (review round 3): React ends the arm here (an unmount, or a change
    // of any dependency below). Retire first, whether or not the controller
    // still tells this arm it is inactive; disposing may then notify again,
    // which finds nothing left.
    return () => {
      retirePendingReplies();
      disposeConversation();
    };
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

**BF-918 (2026-10-23), #1626 -- a spoken reply's first audio and sentence gaps: the next sentence is synthesized while one plays, Piper stays resident, rhubarb is off the first-audio path, voice work has its own executor, and spoken audio expires.** S1: `runPrefetchQueue` (`ui/src/audio/voiceChunking.ts`) replaces the AD-1071 sequential queue: sentence N+1 is synthesized while N plays, playback stays ordered, and a stop drops prefetched audio unplayed. The client asks for deferred visemes and fetches them from `/api/avatars/lipsync`. `stopSpeaking` now also pauses Piper audio (barge-in used to let it play on). A reply stopped before any of its audio started plays nothing, falls back to nothing and ends with AD-1291's `dropped` (`cancelled-before-audio`), which frees the speech arbiter. Stopping a still-loading play no longer speaks the text through the browser instead. In conversation mode, a reply stopped before its audio no longer strands an identical answer that arrives after that reply's `dropped` event has been delivered (one already waiting when that event is delivered can stay in `agent_speaking` until a barge-in or the chat's end, the contract's R19), and a reply's completion is retired when its profile chat closes or switches, so a reply left over from it cannot end the next chat's turn (except when two conversation arms are pre-empted within one task while the older chat stays open, the contract's R21). Two User Timing measures were added (`bf918:first-audio`, `bf918:sentence-gap`). S2: new `probos/audio/tts/resident.py` (`VoiceSynthesisService`, `runtime.voice_synthesis`) holds one `piper --json-input` process per voice and prosody set (at most 4), on a 4-thread voice executor that admits 16 requests (more degrade to the browser); work the executor refuses, or that shutdown cancels, degrades the same way at every stage, and shutdown releases every resident and evicted process (a busy one when its request returns). Rhubarb and ffmpeg run on the same executor (the attachment store's write and lookups still use the default pool: slice M4 of #1626), and the route logs per-stage timings. S3: a new origin `tts_audio`, deleted after `attachments.tts_audio_retention_seconds` (900) and evicted first under the size cap; a more durable write of the same bytes keeps its origin; the age and size sweeps remove an entry only if no write touched it since it was listed (`unlink_if_unchanged`). `scripts/tts_audio_inventory.py` counts the legacy WAVs (1,126 files, 962 indexed) read-only, keeping every candidate when a file, archive row or directory cannot be read, and deleting them is tracked separately. New: `tests/test_bf918_tts_retention.py`, `tests/test_bf918_tts_latency.py`, `tests/fixtures/fake_piper.py`, `ui/src/audio/__tests__/voice.prefetch.bf918.test.tsx`, `ui/src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx`. #1626 stays open for slices M4 (a bounded I/O executor owned by the attachment store), M5 (the arbiter's wait ends on a pipelined reply's last sentence) and M6 (an older reply's `end` no longer completes a newer reply's turn in the same conversation arm), and for the Captain's live measurement, which runs once after M4 and M5 have merged; deleting the legacy WAVs is a separate Captain decision (the contract's section 18). The contract is `prompts/bf-918-tts-first-audio-latency.md`.
```

**`DECISIONS.md`:**

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-918 -- A spoken reply's first audio and the gaps between its sentences (2026-10-23, #1626)

- *Scope.* `audio/tts/resident.py` (new), `piper_backend.py`, `audio/tts/__init__.py`, `avatars/rhubarb_backend.py`, `routers/avatars.py`, `runtime.py`, `startup/shutdown.py`, `startup/finalize.py`, `attachments/{store,filesystem_store,reaper}.py`, `config_models/integrations.py`, `scripts/tts_audio_inventory.py` (new), `ui/src/audio/{voice,voiceChunking}.ts`, `ui/src/components/profile/ProfileChatTab.tsx`. Contract: `prompts/bf-918-tts-first-audio-latency.md`. Tier HIGH for S3.
- *D2 (resident synthesizer).* One `piper --json-input` process per (binary, model, prosody set). Piper fixes prosody per process, and its JSON lines carry only text, output_file and speaker (upstream `main.cpp`; wyoming-piper does the same). At most 4 processes; the least recently used idle one is evicted. Requests write ASCII JSON lines; WAVs go to files (BF-282); `Popen` in a thread (BF-280); `trusted_command_env()` (BF-892); stderr to a file. A per-request timer kills a hung process and the next request starts another. Rejected: in-process synthesis (no package installed; piper1-gpl is GPL-3).
- *D3 (visemes).* A client that sends `defer_visemes: true` gets audio without rhubarb (`visemes_deferred: true`) and fetches the visemes from the existing `/api/avatars/lipsync`; the heuristic schedule runs until they arrive. Other clients are unchanged. Rejected: Piper phoneme timing (not emitted), and overlapping rhubarb with the store write.
- *D4 (executor).* `VoiceSynthesisService` is owned by the runtime (built in `__init__`, closed in `shutdown()`): 4 threads, 16 admitted requests; refusal degrades, including work the executor refuses or that shutdown cancels (`run_voice_work`). Not `set_default_executor` (global, and bounds nothing). The attachment store's I/O stays on the default pool (slice M4 of #1626).
- *D4a (worker lifecycle).* One releaser per worker: `close` when idle, the running request's thread otherwise; a closed worker starts nothing; evicted workers stay reachable until closed.
- *D5 (retention).* Origin `tts_audio`, first in both the durability and the eviction order; TTL 900 s. The store's upgrade rule already existed (#1626's "keeps the first origin" was wrong). Both sweeps remove an entry only if it is unchanged since listed (`unlink_if_unchanged`, review round 1). The legacy WAVs are counted by a read-only tool (Piper's exact header; references read from every file and the decoded episode archive; a file, row or directory it cannot read, or a linked directory other than the attachment directory, keeps every candidate; the attachment directory is read through its link, as the vessel reads it, the report names the target, and a link to nothing stops the run); deleting them is tracked separately and is the Captain's decision.
- *D7.* `stopSpeaking` pauses Piper audio. A dispatched utterance that loses the device before its audio starts ends with `dropped` (`cancelled-before-audio`), not `end`, and the arbiter's wait ends on either; BF-655's one terminal `end` per `start` is unchanged. The profile chat's in-flight keys and reply completion treat `dropped` like `end`; a reply's completion belongs to its conversation arm and is retired on React's cleanup of the arm and on a delivered `'inactive'`, and within an arm a `dropped` completes only the newest reply's turn (review rounds 2 and 3). Not covered: an `'inactive'` the controller coalesces (the contract's R21), and an older reply's `end` within one arm (slice M6 of #1626).
- *Reversal.* Revert the commits. `tts_audio` index entries then belong to no known origin and are never swept or evicted (the safe direction). Resident processes end with the runtime.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then its `--check`. **`docs/development/roadmap.md`:** no row (BF-916 precedent).

## 9. What this does NOT change

- `tts.sentence_pipelining_enabled` stays default-off, and the Captain's `config/system.yaml` is not touched. The status route is unchanged.
- The browser backend makes zero HTTP calls per utterance (Captain decision #9).
- The AD-1291 arbiter's classes and pre-emption, `flushSpeechQueue`, GUARD 1, GUARD 2 and `SPEECH_JOIN_TIMEOUT_MS` are unchanged; its wait for an entry also ends on that entry's own `dropped` (D7a). BF-764, BF-767's shared utterance id and BF-655 balance are unchanged.
- `meetingVoice.ts` and `useMeetingVoice.ts` are unchanged (review round 2): a stop does not end the rest of a meeting batch, which no production caller can reach today (§18). `ProfileChatTab`'s lost-claim rule (BF-718: agent-scoped, no utterance id), its BF-290 completions and BF-767's `end` correlation are unchanged; review round 3 (§7.30f) only retires every reply listener, the lost-claim waiter included, on React's cleanup of the conversation arm that set it up and on a delivered `'inactive'` to that arm (a coalesced one is not delivered: R21). `conversationController.ts` is unchanged: `markAgentReplyComplete` still completes whichever arm owns the controller, and the component retires each listener that could call it for another arm once that arm sees its end (React's cleanup, or a delivered `'inactive'`). The two exceptions are R21's coalesced `'inactive'` and, within one arm, an older reply's `end` (slice M6). The meeting arm and `meetingVoice.ts` and `useMeetingVoice.ts` are not touched by that repair.
- `splitIntoSentences` is unchanged.
- The `/api/avatars/lipsync` contract is unchanged, and so is the browser-capture lip-sync path (`useLipSyncCapture`, `uploadAudioForLipSync`).
- The prosody table, voice resolution, AD-1025 anchoring and BF-291 overrides are unchanged.
- Rhubarb's flags, the ffmpeg conversion, `probe_version` and `is_available` (default pool, used by the doctor) are unchanged.
- The attachment store keeps its blocking I/O on asyncio's default pool: storing the spoken WAV (`write`) and serving it to the browser (`exists`, `get_path`) are not isolated from crew work (D4; slice M4 of #1626).
- The `.index.json` format, every other origin's retention, `agent_artifact` (never LRU-evicted) and `max_store_bytes` are unchanged.
- `unlink` keeps its unconditional meaning for erasure (`knowledge/erasure.py`); only the reaper uses the conditional removal.
- Two preconditions stay as they were and are not enforced (review round 2, F2 and F3; both on the register, §18). One attachment store instance per attachment root: there is one constructor (`routers/chat.py` `_get_attachment_store`, cached per runtime) and AD-816's pidfile allows one vessel per data directory; the conditional removal is decided under that instance's lock against its own index. One sweep at a time per store: one reaper, built in `startup/finalize.py`, whose loop awaits each sweep; overlapping size passes would each stop on their own total.
- Out of scope: streaming the LLM reply (#1130), compressed or streamed audio, and a voice mode. The legacy WAVs are not deleted by any build, test or gate.

## 10. Mutation rows (65 Python and 19 TypeScript; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row on the applied tree after an unmutated baseline run passes, and restore each file before the next row.

Python campaign command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf918_tts_retention.py tests/test_bf918_tts_latency.py tests/test_bf892_spawn_env_guard.py -n 0 -x -q
```

The TypeScript rows (TS*) are run by hand. The command, from `ui/`, is `npx vitest run src/audio/__tests__/voiceChunking.test.ts src/audio/__tests__/voice.prefetch.bf918.test.tsx src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx`.

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
| R25 | `scripts/tts_audio_inventory.py` | `if sha in referenced:` | `if False:` | `test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing` |
| R26 | `src/probos/attachments/filesystem_store.py` | `if entry is None or entry.get("origin", "chat_attachment") != origin:` | `if entry is None:` | `test_unlink_if_unchanged_removes_only_the_entry_that_was_listed` (a write always refreshes `written_at`, so only this direct case isolates the origin check) |
| R27 | `src/probos/attachments/filesystem_store.py` | `if current > written_at:` | `if False:` | `test_a_write_after_the_ttl_listing_keeps_its_entry[tts_audio]`; `test_a_write_after_the_lru_listing_keeps_its_entry[tts_audio]`; `test_unlink_if_unchanged_removes_only_the_entry_that_was_listed` |
| R28 | `src/probos/attachments/reaper.py` | `freed_one = await self._safe_reap(sha, origin, written_at)` | `freed_one = await self._safe_reap(sha, origin, float("inf"))` | `test_a_write_after_the_ttl_listing_keeps_its_entry[tts_audio]` |
| R29 | `src/probos/attachments/reaper.py` | `freed_one = await self._safe_reap(sha, origin, listed_at)` | `freed_one = await self._safe_reap(sha, origin, float("inf"))` | `test_a_write_after_the_lru_listing_keeps_its_entry[tts_audio]` |
| R30 | `scripts/tts_audio_inventory.py` | `if len(head) != _WAV_HEADER_BYTES:` | `if False:` | `test_only_the_exact_piper_header_is_a_candidate` (the 36-byte file then raises in the unpack) |
| R31 | `scripts/tts_audio_inventory.py` | `and riff_size == size - 8` | `and True` | `test_only_the_exact_piper_header_is_a_candidate` (`riff_size`) |
| R32 | `scripts/tts_audio_inventory.py` | `and fmt_size == 16` | `and True` | `test_only_the_exact_piper_header_is_a_candidate` (`fmt_size`) |
| R33 | `scripts/tts_audio_inventory.py` | `and byte_rate == rate * 2` | `and True` | `test_only_the_exact_piper_header_is_a_candidate` (`byte_rate`) |
| R34 | `scripts/tts_audio_inventory.py` | `and align == 2` | `and True` | `test_only_the_exact_piper_header_is_a_candidate` (`block_align`) |
| R35 | `scripts/tts_audio_inventory.py` | `and 0 < data_size == size - _WAV_HEADER_BYTES` | `and True` | `test_only_the_exact_piper_header_is_a_candidate` (`payload_absent`, `empty_payload`) |
| R36 | `scripts/tts_audio_inventory.py` | `and data_size % 2 == 0` | `and True` | `test_only_the_exact_piper_header_is_a_candidate` (`odd_payload`) |
| R37 | `scripts/tts_audio_inventory.py` | `if is_sqlite:` | `if False:` | `test_an_archived_reference_keeps_its_wav`; `test_an_archive_row_that_cannot_be_decoded_keeps_every_candidate` |
| R38 | `scripts/tts_audio_inventory.py` | `if "episode_archive" not in tables:` | `if True:` | `test_an_archived_reference_keeps_its_wav`; `test_an_archive_row_that_cannot_be_decoded_keeps_every_candidate` |
| R39 | `scripts/tts_audio_inventory.py` | `if unreadable:` | `if False:` | `test_an_archive_row_that_cannot_be_decoded_keeps_every_candidate` |
| R40 | `scripts/tts_audio_inventory.py` | `if child == attachments_dir:  # the store itself: its index names every id` | `if False:` | `test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing` (the store is walked and its index names every id; review round 2 moved this guard from the rglob filter into the walker) |
| R46 | `src/probos/audio/tts/resident.py` | `if self._closed:  # closed while this request was queued: start nothing` | `if False:` | `test_a_closed_worker_refuses_a_request_and_starts_nothing` (a process is launched on a closed worker) |
| R47 | `src/probos/audio/tts/resident.py` | `if self._closed:  # closed while Popen ran, so close found no process to kill` | `if False:` | `test_close_while_the_process_starts_kills_it_and_releases_everything` (the request reaches the live process and returns audio) |
| R48 | `src/probos/audio/tts/resident.py` | `if release:` | `if False:` | `test_close_while_a_request_runs_releases_the_worker_when_it_returns` (pipes, stderr file and directory stay) |
| R49 | `src/probos/audio/tts/resident.py` | `if running:` | `if False:` | `test_close_while_a_request_runs_releases_the_worker_when_it_returns` (released under the read: stdin closed when close returns) |
| R50 | `src/probos/audio/tts/resident.py` | `worker.close(wait_seconds=0.5)  # a running worker releases itself when its request returns` | `pass` | `test_close_while_a_request_runs_releases_the_worker_when_it_returns`; `test_shutdown_closes_a_retiring_worker_and_the_request_degrades` |
| R51 | `src/probos/audio/tts/resident.py` | `workers = [*self._resident.values(), *self._retiring]` | `workers = list(self._resident.values())` | `test_shutdown_closes_a_retiring_worker_and_the_request_degrades` (held when close returns) |
| R52 | `src/probos/audio/tts/resident.py` | `self._retiring.add(worker)` | `pass` | `test_shutdown_closes_a_retiring_worker_and_the_request_degrades` (held when close returns) |
| R53 | `src/probos/audio/tts/resident.py` | `worker.close(wait_seconds=0.5)  # a no-op once the queued close has run` | `pass` | `test_a_cancelled_retirement_still_closes_the_worker` |
| R54 | `src/probos/audio/tts/resident.py` | `if not _caller_cancelled():` | `if False:` | `test_shutdown_degrades_a_queued_request_instead_of_cancelling_it` (CancelledError) |
| R55 | `src/probos/audio/tts/resident.py` | `if not self._closed:  # a request that shutdown ended is not a piper failure` | `if True:` | `test_close_while_the_process_starts_kills_it_and_releases_everything` (a warning is logged) |
| R56 | `src/probos/audio/tts/resident.py` | `if _caller_cancelled():` | `if True:` | `test_shutdown_closes_a_retiring_worker_and_the_request_degrades`; `test_lipsync_degrades_and_removes_its_temp_file_when_shutdown_cancels_the_conversion` (CancelledError) |
| R57 | `src/probos/audio/tts/resident.py` | `return task is not None and task.cancelling() > 0` | `return False` | `test_a_cancelled_retirement_still_closes_the_worker` (the cancellation is swallowed; the task is not done within 2 s) |
| R58 | `src/probos/audio/tts/resident.py` | `raise VoiceWorkRefused(f"BF-918: voice work refused: {exc}") from exc` | `raise` | `test_lipsync_degrades_when_the_executor_closes_between_conversion_and_rhubarb` (RuntimeError escapes) |
| R59 | `src/probos/avatars/rhubarb_backend.py` | `returncode, stderr_bytes = await run_voice_work(executor, _run_sync)` | `returncode, stderr_bytes = await asyncio.get_running_loop().run_in_executor(executor, _run_sync)` | `test_lipsync_degrades_and_removes_its_temp_file_when_shutdown_cancels_the_conversion` |
| R60 | `src/probos/avatars/rhubarb_backend.py` | `returncode, stdout_bytes, stderr_bytes = await run_voice_work(` | `returncode, stdout_bytes, stderr_bytes = await asyncio.get_running_loop().run_in_executor(` | `test_lipsync_degrades_when_the_executor_closes_between_conversion_and_rhubarb` |
| R61 | `src/probos/audio/tts/resident.py` | `except (VoiceWorkRefused, RuntimeError):` | `except VoiceWorkRefused:` | `test_close_while_the_process_starts_kills_it_and_releases_everything` (the closed `executor` raises out of `synthesize`) |
| R62 | `scripts/tts_audio_inventory.py` | `for directory, subdirs, names in os.walk(data_dir, onerror=not_listed):` | `for directory, subdirs, names in os.walk(data_dir):` | `test_a_directory_that_cannot_be_listed_keeps_every_candidate` (the refused directory is skipped in silence: `legacy` is a candidate, `unreadable` is empty) |
| R63 | `scripts/tts_audio_inventory.py` | `unreadable.append(f"{error.filename}{os.sep}")  # refused, or gone since its parent was listed` | `pass` | `test_a_directory_that_cannot_be_listed_keeps_every_candidate` (the same) |
| R64 | `scripts/tts_audio_inventory.py` | `if os.path.islink(child) or os.path.isjunction(child):  # never followed` | `if os.path.islink(child):` | `test_a_link_to_a_directory_is_not_followed_and_keeps_every_candidate[isjunction]` (`os.walk` follows the junction and reads its record) |
| R65 | `scripts/tts_audio_inventory.py` | `unreadable.append(f"{child}{os.sep}")  # a link to a directory: its records are not read` | `pass` | `test_a_link_to_a_directory_is_not_followed_and_keeps_every_candidate` (both cases: pruned without a word, `legacy` is a candidate) |
| R66 | `scripts/tts_audio_inventory.py` | `subdirs[:] = walked` | `pass` | `test_the_dry_run_finds_the_legacy_wavs_and_changes_nothing` (the store is walked and its index names every id) |
| R67 | `scripts/tts_audio_inventory.py` | `except FileNotFoundError:  # no store yet: nothing is indexed and nothing unindexed` | `except OSError:` | `test_a_store_directory_that_cannot_be_listed_stops_the_inventory` (the refusal is swallowed: DID NOT RAISE) |
| R68 | `scripts/tts_audio_inventory.py` | `inventory.unindexed_wavs = sum(1 for name in names if os.path.normcase(name).endswith(".wav") and name[:-4] not in index)` | `inventory.unindexed_wavs = sum(1 for name in names if os.path.normcase(name).endswith(".wav"))` | `test_a_store_directory_that_cannot_be_listed_stops_the_inventory` (the control counts 7, not 1) |
| R69 | `scripts/tts_audio_inventory.py` | `if os.path.islink(attachments_dir) or os.path.isjunction(attachments_dir):  # read through, and named` | `if True:` | `test_a_linked_store_is_read_through_its_link_and_named` (the plain store's control names a target) |
| R70 | `scripts/tts_audio_inventory.py` | `if os.path.islink(attachments_dir) or os.path.isjunction(attachments_dir):  # read through, and named` | `if os.path.islink(attachments_dir):` | `test_a_linked_store_is_read_through_its_link_and_named`; `test_a_store_link_to_nothing_stops_the_inventory`. **Windows only:** the tests' link is a junction there; on POSIX it is a symbolic link and the mutant is equivalent |
| R71 | `scripts/tts_audio_inventory.py` | `inventory.attachments_link = os.path.realpath(attachments_dir)` | `inventory.attachments_link = str(attachments_dir)` | `test_a_linked_store_is_read_through_its_link_and_named` (the link's own path, not its target) |
| R72 | `scripts/tts_audio_inventory.py` | `"attachments_link": inventory.attachments_link,` | `"attachments_link": None,` | `test_a_linked_store_is_read_through_its_link_and_named` |
| R73 | `scripts/tts_audio_inventory.py` | `if inventory.attachments_link is not None:  # a link to nothing: the store cannot be listed` | `if False:` | `test_a_store_link_to_nothing_stops_the_inventory` (DID NOT RAISE: an empty store's report is printed) |
| R74 | `scripts/tts_audio_inventory.py` | `inventory.unindexed_wavs = sum(1 for name in names if os.path.normcase(name).endswith(".wav") and name[:-4] not in index)` | `inventory.unindexed_wavs = sum(1 for name in names if name.endswith(".wav") and name[:-4] not in index)` | `test_unindexed_wavs_are_matched_as_the_os_matches_names`. **Windows only** (counts 1, not 3); on POSIX `normcase` is the identity and the mutant is equivalent |
| R76 | `src/probos/audio/tts/resident.py` | `self._dir = directory` | `pass` | `test_a_failed_stderr_open_still_releases_the_worker_directory` (the first directory survives the failed request; the mutant also leaves every request without an output directory, so most resident tests in §7.19 fail too) |
| TS1 | `ui/src/audio/voiceChunking.ts` | `for (let k = i + 1; k <= i + lookahead; k += 1) ensure(k);` | `for (let k = i + 1; k <= i; k += 1) ensure(k);` | run by hand: voiceChunking Q2; prefetch P1 |
| TS3 | `ui/src/audio/voiceChunking.ts` | `if (p !== undefined) void p.then(discard);` | `if (false) void p.then(discard);` | run by hand: voiceChunking Q3; prefetch P3 |
| TS5 | `ui/src/audio/voice.ts` | `if (_settled \|\| _activeAudio !== audio \|\| frames.length === 0) return;` | `if (frames.length === 0) return;` | run by hand: prefetch P4 |
| TS6 | `ui/src/audio/voice.ts` | `try { _activeAudio.pause(); } catch { /* BF-918: barge-in silences server audio too */ }` | `// BF-918 mutant: no pause` | run by hand: prefetch P7, P2 |
| TS7 | `ui/src/audio/voice.ts` | `if (event.type !== 'end' && event.type !== 'dropped') return;` | `if (event.type !== 'end') return;` | run by hand: prefetch P9, P10 (the next reply is never posted: the arbiter still waits) |
| TS8 | `ui/src/audio/voice.ts` | `if (_activeUtteranceId !== utterance_id) { _fireDropped(entry, CANCELLED_BEFORE_AUDIO); return; }` | `if (false) { _fireDropped(entry, CANCELLED_BEFORE_AUDIO); return; }` | run by hand: prefetch P12 (the browser speaks 'Probe.' after the stop) |
| TS9 | `ui/src/audio/voice.ts` | `if (played === 0) _fireDropped(entry, CANCELLED_BEFORE_AUDIO);` | `if (played < 0) _fireDropped(entry, CANCELLED_BEFORE_AUDIO);` | run by hand: prefetch P9 (no 'dropped'; the next reply is never posted) |
| TS10 | `ui/src/audio/voice.ts` | `if (!(await _synthesizeAndPlay(text, profile, agent_id, emotion, utterance_id))) _fireDropped(entry, CANCELLED_BEFORE_AUDIO);` | `await _synthesizeAndPlay(text, profile, agent_id, emotion, utterance_id);` | run by hand: prefetch P10 (the next reply is never posted), P11 (no 'dropped') |
| TS11 | `ui/src/audio/voice.ts` | `if (_activeUtteranceId !== utterance_id) { _discardPreparedSpeech(prepared); return false; }` | `if (false) { _discardPreparedSpeech(prepared); return false; }` | run by hand: prefetch P10 (the stopped reply's audio plays), P11 (the browser speaks it) |
| TS12 | `ui/src/audio/voice.ts` | `if (_activeUtteranceId !== utterance_id) { _finish(false); return; }` | `if (false) { _finish(false); return; }` | run by hand: prefetch P13 (the browser speaks 'Pending.' after the stop) |
| TS13 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (event.type !== 'end' && event.type !== 'dropped') return;` | `if (event.type !== 'end') return;` | run by hand: ProfileChatTab.bf918 C2 (the in-flight key survives the drop; the identical answer waits: `agent_speaking`) |
| TS14 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (!claimed \|\| event.utterance_id !== ourUtteranceId) return;` | `if (!claimed) return;` | run by hand: ProfileChatTab.bf918 C3 (the newer reply's listener completes on the older reply's drop: `silence_pending` while the newer reply waits) |
| TS15 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (replyTurn !== ourTurn) { retire(); return; }` | `if (false) { retire(); return; }` | run by hand: ProfileChatTab.bf918 C3 (the older reply's late drop completes the newer turn) |
| TS16 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (event.type === 'dropped') {` | `if (false) {` | run by hand: ProfileChatTab.bf918 C4 (the turn stays `agent_speaking`) |
| TS17 | `ui/src/components/profile/ProfileChatTab.tsx` | `const ourTurn = ++replyTurn;` | `const ourTurn = replyTurn;` | run by hand: ProfileChatTab.bf918 C3 (every reply shares turn 0, so the late drop completes the newer turn) |
| TS18 | `ui/src/components/profile/ProfileChatTab.tsx` | `for (const retireReply of [...pendingReplies]) retireReply();` | `for (const retireReply of [...pendingReplies]) void retireReply;` | run by hand: ProfileChatTab.bf918 C5, C6, C7, C8, C9 (each case), C10, C12 (nothing is ever retired: `silence_pending` right after the old reply's late `dropped` or `end`) |
| TS19 | `ui/src/components/profile/ProfileChatTab.tsx` | `if (state === 'inactive') retirePendingReplies();` | `if (false) retirePendingReplies();` | run by hand: ProfileChatTab.bf918 C10 (the first profile stays mounted, so only the controller's `'inactive'` ends its arm; the cases that unmount or re-run the effect survive this mutant by design: the cleanup retires) |
| TS20 | `ui/src/components/profile/ProfileChatTab.tsx` | `retirePendingReplies();` | `void retirePendingReplies;` | run by hand: ProfileChatTab.bf918 C12 (the controller dropped the arm without an `'inactive'`; the cases that unmount or re-run the effect survive this mutant by design: the dispose's `'inactive'` retires the same listeners) |
| TS21 | `ui/src/components/profile/ProfileChatTab.tsx` | `pendingReplies.add(retire);` | `void pendingReplies;` | run by hand: ProfileChatTab.bf918 C5, C6, C7, C8, C9 (each case), C10, C12 (no reply is in the set, so no arm end retires it) |

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

**Review round 1 (Architect and orchestrator, 2026-10-24, at candidate 2 `5dd0d9a9`).** Area A read: `filesystem_store.py:295-321` (`unlink`) and `:243-259` (the write's refresh and upgrade), `reaper.py:166, 209, 227-255`, `store.py:75-79`, `erasure.py:47, 286-289, 298`, `episode_archive.py:61, 250-287, 462-480`, `sqlite_factory.py:25-36`, `integrations.py:254-257`, `config-reference.md:1976`, `architecture-baseline.yaml:316-322`, `test_attachment_reaper.py:269-285`, `test_ad1192_owned_steps_finalization.py:2796, 2894-2905`. Area B read: `resident.py` (the worker and the service), `rhubarb_backend.py:337, 413-429`, `routers/avatars.py:301, 372`, `routers/chat.py:1253-1255`, `filesystem_store.py:229, 270`, and upstream Piper's `main.cpp` and `piper.cpp` for its logging. Area C read: `voice.ts:432-444, 501, 521-524, 537-545, 578-579, 735-739, 870-879`, `meetingVoice.ts:127` and the nine `onSpeechEvent` listeners (A3-2). The orchestrator's read-only evidence on the live store, 2026-10-24: 1,129 index entries, 962 `audio/wav` (all `chat_attachment`, all with Piper's one canonical 44-byte header at 22,050 Hz), 1,126 `.wav` files on disk (164 without an index entry), and a copy of `episode_archive.db` with 1,988 payloads that all decode and none of which holds any of the 962 ids.

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

CLAIM (review round 1): only the reaper needs the conditional removal, and no reaper test uses a fake store
RUN:   Grep "\.unlink\(" -> reaper.py:243, erasure.py:298, scripts/tts_audio_inventory.py:166 and test fakes only; Grep "AttachmentReaper\(" -> finalize.py:757, test_attachment_reaper.py (9), test_ad1192:2894 (a real store)
HOLDS: yes

CLAIM (review round 1): no test or script uses --attachments-dir, and no test pins the max_store_bytes description
RUN:   Grep "attachments-dir|tts_audio_inventory" ; Grep "evicts oldest perception_frame" -> integrations.py:256, config-reference.md:1976 and prompts/archive only
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
  - BF-906's read-only SQLite open (`storage/sqlite_factory.py:25-36`): the tool adds `immutable=1`, so it creates no `-wal` or `-shm` beside a database. The pidfile is no longer used: the tool is read-only since review round 1.
  - The conditional removal is the usual compare-and-delete: the check and the delete are decided under one lock. A read before the delete leaves the window open (review round 1).
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
3. `close` is idempotent, never awaits, and refuses all later admissions. When it returns, every idle and every retiring worker is released, or is being released by the voice thread that holds it. Every running worker is killed, and its request releases it when its blocking call returns. No pipe is closed under a running read.
   - Every worker the service creates is released exactly once, on every path: success, timeout, exit, empty output, the caller cancelling, executor refusal, eviction and shutdown.
   - A worker closed before or during its process start launches nothing afterwards, or kills what it launched before writing a request.
   - Each resource a worker creates (its directory, its stderr file, its process) is owned by the worker from the moment it exists: when a start fails at any step, the request's retirement or shutdown kills its process, closes its pipes and stderr file, and removes its directory once (a killed Piper that has not exited within `wait_seconds` can keep the directory on Windows: R17); a later request on the same key still answers.
   - Shutdown never turns queued or refused voice work into an exception: that request answers `None` or `[]`, and any converted file is removed. Only a cancellation of the calling task itself propagates.
4. With the service present, voice work never runs on asyncio's default pool. Admitted work is bounded, and a refusal degrades to `None` or `[]` without raising into a route. The attachment store's write and lookups are not voice work and stay on asyncio's default pool; no comment or tracker text claims otherwise.
5. The only new process launch uses `env=trusted_command_env()` (BF-892) and `subprocess.Popen` in a thread (BF-280). No WAV travels over stdout (BF-282).
6. The `/api/avatars/tts` response is a superset of the old one. A request without `defer_visemes: true` gets the same fields and behaviour as before.
7. Spoken audio is written as `tts_audio`. No other origin is ever downgraded. Age-based deletion reaches only `perception_frame` (as before) and `tts_audio`. Age and size removal take an entry only if it still has the origin and the timestamp the sweep listed, decided under the store lock that removes it. A kept entry frees nothing and is not counted. This holds for writes through the same store instance. One instance per attachment root and one sweep at a time per store are preconditions (§9), not properties.
8. The inventory tool creates, changes and locks nothing anywhere: no lock file, no SQLite side file. It offers no delete, and it reads only `<data-dir>` and, when `<data-dir>/attachments` is a link or junction, that link's target, read as the vessel's store reads it and named in the report's `attachments_link` (`null` otherwise). A file or archive row it cannot read, a directory under `<data-dir>` it cannot list (refused, or gone since its parent was listed), and any other link or junction to a directory (never followed) each keep every candidate and are named in `unreadable`, a directory with a trailing path separator. An attachment directory it cannot list, or one that links to nothing, stops the run and prints no report. `unindexed_wavs` matches `.wav` as the OS matches names (in any case on Windows). A WAV is a candidate only if it has Piper's exact 44-byte header with sizes that match the file.
9. Client:
   - Playback order is sentence order, and a sentence plays only after the previous one ended.
   - After a stop, no prefetched audio plays and no 'start' fires for it.
   - Every 'start' has exactly one 'end'.
   - Visemes are injected only for the `<audio>` that is playing.
   - The browser backend still makes no POST.
   - A dispatched utterance that loses the device before any of its audio starts emits no `start` and no `end`, exactly one `dropped` carrying its id, plays nothing, and does not fall back to the browser.
   - A play promise rejected while the utterance no longer owns the device speaks nothing in its place; one refused while it still owns the device falls back to the browser as before.
   - The arbiter's wait for an entry ends only on an `end` or `dropped` carrying that entry's id, or on GUARD 1 or GUARD 2; no `dropped` fires for an entry whose audio started.
   - `ProfileChatTab` releases on a `dropped` what an `end` releases: its agent's in-flight speech keys (BF-718's per-agent rule) and the completion listener armed for that utterance id.
   - A `dropped` completes the controller's turn only when it carries the id of the newest conversation-mode reply of its own arm. It never completes an older or a newer turn, or another arm's turn, and nothing fires an `end` in its place.
   - React's cleanup of a 1:1 conversation arm's effect (before it disposes the controller) and a delivered controller `'inactive'` to that arm's options each retire every reply completion listener that arm set up, claimed or lost. A retired listener never calls `markAgentReplyComplete`, so once either has happened, no `end` or `dropped` of that arm's replies completes another arm's turn. Not a property (R21): a pre-empted arm's `'inactive'` is delivered from a one-slot microtask queue, and a later pre-emption queued before it runs replaces it, so that `'inactive'` is never delivered and a still-mounted older arm keeps its listeners until React's cleanup. Retiring completes no turn and touches neither the in-flight keys nor the speech ledger.
   - A live arm's reply completes on its own `end`, on the newest reply's `dropped`, or immediately (BF-290), under StrictMode's double effect run too; the newest reply's lost-claim waiter completes on its agent's `end`. Not a property: R19's waiter, whose awaited utterance is dropped by a pre-emption, leaves the turn in `agent_speaking` until a barge-in or the arm's end; within one arm, an older reply's own `end` still completes a newer reply's turn (slice M6). The controller calls `onAgentReply` only while that arm owns it.
   - The lost-claim rule (agent-scoped, no id), BF-290's immediate completions and BF-767's `end` correlation are unchanged. The lost-claim waiter is retired like every reply listener (above, with R21's exception).
   - No production caller of `stopSpeaking` runs while a meeting batch speaks. Its only caller is the controller's barge-in, which runs only in `agent_speaking`, a state the AD-985 meeting mode never enters.
10. Every new class stays within 500 lines and 15 methods, adds no layer import, and creates no task it does not hold.

## 15. Acceptance criteria

- [ ] M1 to M3 are built; the focused checks in §6 pass; the three `--check` commands pass; `check_architecture_principles.py --check` passes; `npx tsc -b` passes.
- [ ] Cancelling or superseding a reply stops it immediately, and no prefetched sentence plays afterwards (P2, P3, P7, P9 to P13); a conversation-mode reply stopped before its audio strands no turn that begins after that reply's `dropped` event has been delivered (`ProfileChatTab.bf918` C2 and C4; a lost-claim turn already waiting when that event is delivered can stay in `agent_speaking`: R19), and once React's cleanup or a delivered `'inactive'` has ended its arm, no reply's late `end` or `dropped` completes another arm's turn (C5 to C10, C12; the coalesced-notification exception is R21), while a live arm's own reply still completes (C11).
- [ ] Lip-sync visemes fire for every utterance on both paths (P4, P5, P6, and the route tests).
- [ ] The browser fallback is unchanged: no request when `backend != "piper"`, and a fallback per sentence on failure (serverTts, pipelining test 4).
- [ ] With pipelining off, the single-call path behaves as before, apart from the S2 speed-up and the deferred visemes.
- [ ] The resident process recovers from a hang (killed within `timeout_seconds`) and from a crash, and degrades honestly.
- [ ] Spoken audio lands under its own origin and the reaper sweeps it; a hash also written as `chat_attachment` is never swept.
- [ ] Two tests cross a seam each: route → service → worker → store (`test_the_route_speaks_through_the_resident_process`), and enqueue → prefetch → play in order → stop (P2).
- [ ] The live acceptance (§16) is reported on #1626 once, after M4 and M5 (the two slices of §18 R9 and R12) have merged. #1626 closes after the live acceptance, M4, M5 and M6 (M6, §18, does not gate the acceptance and may land before or after it); the legacy WAV deletion does not keep it open (§18 R6, a Captain decision).
- [ ] All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance: what the Captain does and what is read

The live acceptance cannot be met by CI. Only the Captain restarts the vessel; the orchestrator reads files only and never calls the live API.

**Timing (Architect, 2026-10-24):** the acceptance runs once, after M4 and M5 (§18 R9 and R12, open slices of #1626) have merged, because R12 would truncate the pipelined replies that the measurement uses. The "before" HAR must be captured before the vessel restarts onto any BF-918 build, M1 to M3 included; a restart onto this change alone loses the baseline.

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

1. **Route stages, after.** Use `Select-String -Path "$D\logs\probos.log*" -Pattern 'BF-918: tts route|BF-918: lipsync route'`, then take p50 and p95 of `synth_ms`, `store_ms`, `visemes_ms` and `total_ms`, and of the lipsync route's `visemes_ms`. `store_ms` is the store write, which stays on asyncio's default pool (D4, slice M4): a first-audio miss with the crew active and a high `store_ms` is the store's, not synthesis's. The command:
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
7. **Legacy inventory (read-only).** `d:/ProbOS/.venv/Scripts/python.exe scripts/tts_audio_inventory.py --data-dir "$D"`, preferably with ProbOS stopped (a database being written may be reported `unreadable`, which keeps every candidate). Post the JSON, including `kept`, `unreadable`, `unindexed_wavs`, `attachments_link` and `seconds` (the cost of reading every file, backups included). `attachments_link` is `null` unless `$D\attachments` is a link or junction; then it names the target, which the tool reads as the vessel does. An `unreadable` entry that ends in a path separator is a directory the tool could not list, or another link or junction to a directory, which it never follows; either keeps every candidate. If the attachment directory itself cannot be listed, or links to nothing, the run stops with an error and prints no JSON. It deletes nothing; the sweep decision belongs to the follow-up issue.

**Targets:** first audio within about 1.5 s at p50, with p95 reported; no gap over about 0.3 s, excluding `sentence_silence`.

## 17. Not verified

- I could not run `piper.exe` (the bridge allows no such command). The installed binary's version, `--json-input`, the per-line `output_file`, the path echo and the decoding of `\u` escapes are verified only from upstream source. V0 is the Builder's first action, with its expected result.
- No test, vitest, `tsc`, precheck, checker or generator was run (read-only call).
- **The microtask depth of the existing `_flush` helpers is estimated**, not run (§6 harness rule).
- **The jsdom `performance.measure` implementation is not checked** (P8 stubs it).
- Live bytes and per-origin counts: the index is a single-line JSON file and Python is not allowed here, so I could only count files by extension.
- wyoming-piper's read-back code (beyond the excerpt) was not read.
- AD-1341 S2 to S6 and AD-1346 M2, M5, M6, M8 and M10 have no contracts yet. The overlap in §4 is judged from #1601's text and #1632's body.
- **Expected phantom-precheck false positives**, all from code blocks: the `Inventory`, `PiperOutcome` and fake-process field accesses (new symbols), `Timer` (`threading.Timer`), `OrderedDict`, `SimpleNamespace`, `ThreadPoolExecutor` where already in `src`, and `VisemeFrame` where already in `src`. Amendments A1 to A3 add `unlink_if_unchanged` (new), `record.document` and `record.metadata` (`ArchiveRecord` fields) and `connection.execute` (`sqlite3`).
- **Amendments A1 to A3 (2026-10-24, read-only consults):** each ran no test, vitest, `tsc`, precheck or generator, so every "fails on the candidate" claim came from reading; the orchestrator's tests-first run on candidate 2's unchanged source is the execution check (see the verification paragraph). Area A's consult was denied one `ls` of the live data directory and read none of it; its live facts are the orchestrator's read-only evidence. Area B read Piper's logging from upstream `main.cpp` and `piper.cpp`, not from the installed binary; its lifecycle tests use an in-memory process fake (a real stderr file and directory), so OS handle inheritance and Windows directory removal while a killed child has not exited are not exercised; the default pool's live saturation was not measured. Area C modelled the native media boundaries (`pause` rejecting a pending play with an abort error; an answer arriving after a stop) with doubles taken from the reviewer's Chromium probes, and ran no vitest.
- **Amendments A4 to A6 (2026-10-24, read-only consults):** each ran no test, vitest, `tsc`, precheck or generator, so every "fails on the candidate" claim came from reading; the orchestrator's tests-first run on candidate 3's unchanged source is the execution check (see the verification paragraph). A4's directory refusals and links are injected at `os.scandir`, `os.path.islink` and `os.path.isjunction`; no real ACL, symlink or junction is created, and whether the live data directory contains a link was not checked (one would appear in `unreadable` and keep every candidate). A5's stderr-open failure is injected by replacing `mkdtemp` with a function that makes a directory whose `stderr.log` is itself a directory; real causes (a full disk, an antivirus lock) are not exercised. A6's cases C1 to C4 run the real component, controller and voice code with the harness of the round-2 reviewer's executed probe. The claim behind R18, that no production code can stop speech while a meeting batch speaks, is from reading; the orchestrator re-ran its enumeration (`stopSpeaking` has one non-test caller, `conversationController.ts:356`, inside `_onVadSpeechStart` under `_state === 'agent_speaking'`, and the only assignment of that state is the `/chat` branch of `_onTranscript`, which the group submit path never reaches).
- **Amendment A7 (2026-10-24, read-only consult):** it ran no test, so every "fails on the candidate" claim is from reading; the orchestrator's tests-first run on candidate 4 is the execution check. Not run here: what `os.scandir` raises on Windows for a junction whose target is gone (expected `FileNotFoundError`; the test accepts any `OSError` after asserting its premise, a link to nothing), `os.path.realpath` on that junction (CPython 3.12's non-strict `ntpath.realpath` reads the link instead of raising), and the POSIX `os.symlink` branch of the link helper (this host makes a junction). A link to a file is not tested (on Windows it needs a privileged file symbolic link); by reading, the index read or the store listing raises and stops the run. A4's bullet above says a link in the live data directory would appear in `unreadable`: that holds for every link except `<data-dir>\attachments`, which A7 reads through and names in `attachments_link`. Whether the live `attachments` is a link was not checked; §16 step 7's report now shows it.
- **Amendment A9 (2026-10-24, read-only consult):** it ran no test, vitest, `tsc` or precheck, so every "fails on candidate 4" claim comes from reading; the orchestrator's tests-first run is the execution check. C5 is the round-3 reviewer's executed probe. C6 to C12 extend the same harness (a second agent, a second mount, StrictMode, the mic-mode menu, the `voice-profile-updated` event, and a thread id answered with 404) and were not run by the consult. The cleanup's retire has no ordinary killer: whenever the arm still owns the controller at cleanup, the dispose's `'inactive'` retires the same listeners. C12 therefore uses the controller's test seam, which tears down without notifying; it stands in for a pre-empted arm whose queued `'inactive'` is superseded (`conversationController.ts:540-544`), a path that was not constructed. The round-2 design's liveness check on `onAgentReply` was left out on reading: the controller's ownership check comes before the call (`:433-435`), and `ProfileChatTab.bf718.test.tsx` calls the first arm's `onAgentReply` after a voice-profile re-arm. Within one arm, an older reply's own late `end` can still complete a newer reply's turn (the turn guard applies to `dropped` only): the consult's reading, not executed, and it predates BF-918. Possible precheck false positives: `pendingReplies.add`, `pendingReplies.delete`.
- **Amendment A10 (2026-10-24, read-only consult, text only):** it ran no test. C-R4-1 (`arm-boundaries.test.tsx`), C-R4-2 (`superseded-inactive.test.tsx`) and C-R4-3 (`registered-r19.test.tsx`) are the round-4 reviewer's executed probes; the orchestrator re-ran the first two on candidate 5, `ba794bb1` and `26bec26d`, with the same result on all three. The A9 bullet's "not executed" reading of a same-arm older `end` is now executed; it is slice M6. A10 changes one comment block (§7.30f pair 2) and no line that any mutation row pins.
- `ATTACHMENT_REAPED` is `GRANDFATHERED` (`event_persistence.py:126`): it is emitted but not written to `events.db` by default. No sentence of this contract or its code claims otherwise; A1's consult report did, wrongly.

**Orchestrator verification, round 0 (2026-10-24, by tool, on `origin/main` `26bec26d` = BF-914 merged; the consult above ran none of this; the contract as drafted plus the five mechanical repairs).** All 60 verbatim pairs apply, each SEARCH once (11 in M1 with §7.9a and §7.9b, 36 in M2 with pair 4b, 14 in M3), the eight range pairs apply by their markers, and the six new files are created by tool: the oracle is three scratch commits, M1 `ffa300cd`, M2 `a461fd02` and M3 `c0185231` (tree `701e589c`). **The oracle found what a read-only consult cannot** (the header lists the five repairs): the retention test's tool loader, the facade's pinned field count, the range pairs a verbatim-pair tool skips and, from the consolidated focused check, the agentic-loop golden's pop of the new default. After them, on the final oracle: the M1 and M2 focused lists, 21 test files, 1,188 passed (repair 5 adds the `test_ad1152` file to M1's list); the 13 config-pin test files that read the whole configuration or its models, 1,939 passed; vitest over 33 files, 338 passed, and `tsc -b` clean; the generators move the model-field count 1879 to 1880 and change the three generated files. **Mutation campaign:** the 21 Python rows ran one at a time after an unmutated baseline (110 passed): 21 of 21 killed, none survived, none inert, none invalid; a census run that records every failing test of every mutant found 0 claimed killers that do not fail. The four TypeScript rows, run by hand (baseline 26 passed): 4 of 4 killed. "25 mutants parsed" equals the 21 and 4 rows of section 10. **The three Builders** (`claude-sonnet-5.5`; M2 and M3 built concurrently in separate trees) produced files blob-equal to the oracle's stages: M1's 13, M2's 26 cumulative paths and M3's 6, with 0 mismatches (the 14th M1 path, §7.9b, was applied by the oracle's tool after the focused check, not by a Builder); the one difference found on the way (§7.14 pair 4's comment placement) is repair 4 above. **Tests-first:** the oracle's nine Python test files on `26bec26d`'s source: 14 failed and 376 passed, and four files fail at collection because they import `probos.audio.tts.resident`; the four vitest files: 17 failed and 16 passed.

**Orchestrator verification, round 1 repair (2026-10-24, by tool).** The three amendments apply to the contract by tool, each SEARCH once (A2 27 pairs, A1 28 and A3 19, in that order); the oracle is three scratch commits on `26bec26d`, M1 `2c305c91`, M2 `1a2c9d32` and M3 `1e384b73` (tree `e348bbe8`). **Tests-first**, the oracle's changed test files on candidate 2's unchanged source: of 61 Python tests, 24 fail, namely the 23 new tests for the findings and the one pin that moved (`test_reaper_continues_past_permission_error`); the one new test that passes is the WebM control. The failures have the findings' reasons: the store has no `unlink_if_unchanged`, a write after the listing is deleted anyway, the removed tool options are accepted, malformed headers and archived references are candidates, a closed worker answers, a busy or evicted worker keeps its pipes, stderr file and directory, a queued request ends in `CancelledError`, and the lip-sync route raises `RuntimeError` after the executor closed. Of 13 vitest tests, the five new ones (P9 to P13) fail. **After the repair**, on the oracle: retention 23, reaper 12 and latency 26 passed; the M1 focused list (9 files) 691 and the M2 focused list (14 files) 567 (the 21 files together 1,209); the 13 config-pin test files 1,939; vitest over 35 files 350 and `tsc -b` clean; the three generator `--check` commands and the architecture, store-registry and seam checks pass. **Mutation campaign:** the 51 Python rows ran one at a time after an unmutated baseline (131 passed): 51 of 51 killed, none survived, none inert, none invalid; a census over every failing test of every mutant found 0 claimed killers that do not fail; the 10 TypeScript rows, run by hand (baseline 31 passed): 10 of 10 killed, and their census found 0 claimed killers that do not fail. "61 mutants parsed" equals the 51 and 10 rows of section 10. **The three repair Builders** (`claude-sonnet-5.5`, reasoning effort high, in separate trees on candidate 2) saw the predicted tests-first counts (area A 16 failed and 19 passed, area B 8 and 18, area C 5 and 8) and produced files blob-equal to the oracle's: A's 9, B's 5 and C's 2 paths, 0 mismatches (area A's Builder shortened the SEARCH of two pairs, the protocol method in §7.1 and its implementation in §7.2, with the same result).

**Orchestrator verification, round 2 repair (2026-10-24, by tool).** The three amendments apply to the contract by tool, each SEARCH once (A5 4 pairs, A4 11 and A6 6, in that order); the oracle is three scratch commits on `26bec26d`, M1 `39f9bfe7`, M2 `567d77de` and M3 `b324e994` (tree `896f1705`). **Tests-first**, the oracle's changed test files on candidate 3's unchanged source: of 54 Python tests, 5 fail (the four retention cases for the directory, link and store-listing refusals, and the latency test for a failed stderr open) and 49 pass, and no old test fails; the failures have the findings' reasons (the unreadable directory is not reported and its candidates are not kept, the linked directory is read through, the store's listing does not raise, the worker's directory remains after the failed open). Of the 4 new vitest cases, C2 and C4 fail with `expected 'agent_speaking' to be 'silence_pending'`, and C1 (the control) and C3 (the late-drop guard) pass by design. **The Windows behaviour that the tests inject was also run for real** (a probe in a temporary data directory: an ACL that denies listing a directory, a real junction and an unlistable attachments directory, each scenario asserting its own premise first; creating a directory symlink was refused for lack of the privilege): candidate 3's tool is falsely clean with the denied directory (`unreadable` empty, the WAV still a candidate) and reads through the junction, and the repaired tool keeps every candidate, names the directory and the junction with a trailing separator, never follows the junction, and stops with `PermissionError` without printing a report when the attachments directory cannot be listed. **After the repair**, on the oracle: retention 27, reaper 12 and latency 27 passed; the M1 focused list (9 files) 695 and the M2 focused list (14 files) 572; vitest over the broader M3 command (65 files, every ProfileChatTab test included) 720 passed and `tsc -b` clean; the three generator `--check` commands and the architecture, store-registry and seam checks pass. **Mutation campaign:** the 59 Python rows ran one at a time after an unmutated baseline (136 passed): 59 of 59 killed, none survived, none inert, none invalid; a census over every failing test of every mutant found 0 claimed killers that do not fail. The 15 TypeScript rows, run by hand (baseline 35 passed): 15 of 15 killed, and their census found 0 claimed killers that do not fail, with the five new rows' claims equal to the failing sets (TS13 C2, TS14 C3, TS15 C3, TS16 C4, TS17 C3). "74 mutants parsed" equals the 59 and 15 rows of section 10. **The three repair Builders** (`claude-sonnet-5.5`, reasoning effort high, in separate trees on candidate 3) saw the predicted tests-first counts (area A 4 failed and 35 passed, area B 1 and 26, area C 2 and 2) and produced files blob-equal to the oracle's: A's 3, B's 2 and C's 4 paths, 0 mismatches (area B's M2 focused check read 568 in its tree because the retention file there is candidate 3's, with 23 tests; with area A's four cases it is 572).

**Orchestrator verification, round 3 repair (2026-10-24, by tool).** The amendments reach the contract in three ways: A8 is one sentence (applied by hand); A7's pairs carry no tool envelope (its consult could not read the amendment format), so they were applied by hand with exact-match edits, each SEARCH once; A9's 16 pairs applied by tool, each SEARCH once. The oracle is three scratch commits on `26bec26d`, M1 `8f52e5f2`, M2 `b2ce3015` and M3 `ca6a67d9` (tree `548c218d`; 80 SEARCH labels in the slices equal the 80 in the contract). **Tests-first**, the oracle's changed test files on candidate 4's unchanged source: of 31 retention tests, 3 fail (`attachments_link` is missing from the report, `.WAV` and `.WaV` count 1 of 3, a link to nothing does not stop the run) and the inside-the-data-directory control passes, with no old test failing; of the 14 `ProfileChatTab` cases, 9 fail (C5 to C8, the three C9 cases, C10 and C12, each with `expected 'silence_pending' to be 'agent_speaking'`: the replacement's turn ended by the old reply) and 5 pass (C1 to C4, and C11, the StrictMode control). **The Windows behaviour was also run for real**: a probe in a temporary data directory (a real junction as the store root, a junction to a removed directory, and unindexed `.wav`, `.WAV` and `.WaV` files, each scenario asserting its premise first): candidate 4's tool follows the junctioned store root silently (`attachments_link` is absent), prints a falsely clean empty-store report for the junction to nothing and counts 1 of the 3 names; the repaired tool names the target in `attachments_link`, stops with `FileNotFoundError` and no report for the junction to nothing, and counts 3; the earlier scenarios (a real ACL that denies listing, a real junction in a record directory, an unlistable attachments directory) still behave as in round 3. The area C reviewer's `unmount-regression` probe was re-run on the candidate, `b96cbe22` and `26bec26d` before the repair (`silence_pending`, `agent_speaking`, `silence_pending`). **After the repair**, on the oracle: retention 31, reaper 12 and latency 27 passed; the M1 focused list (9 files) 699 and the M2 list (14 files) 576; vitest over the broader M3 command (65 files) 730 passed and `tsc -b` clean; the generator `--check` commands and the architecture, store-registry and seam checks pass. **Mutation campaign:** the 65 Python rows ran one at a time after an unmutated baseline (140 passed): 65 of 65 killed, none survived, none inert, none invalid; a census over every failing test of every mutant found 0 claimed killers that do not fail. The 19 TypeScript rows, run by hand (baseline 45 passed): 19 of 19 killed and their census found 0 claimed killers that do not fail, with the new rows' claims equal to the failing sets (the census first read the case ids that the TS19 and TS20 cells named as surviving by design as claims, until those cells stopped naming them: a mechanical wording repair, no row changed). "84 mutants parsed" equals the 65 and 19 rows of section 10. **The two repair Builders** (`claude-sonnet-5.5`, reasoning effort high, in separate trees on candidate 4; area B had no code to build) saw the predicted tests-first counts (area A 3 failed and 40 passed of 43 tests, area C 9 failed and 5 passed of 14) and produced files blob-equal to the oracle's: A's 2 and C's 2 paths, 0 mismatches.

## 18. For the register (found here, not fixed by this change)

- R1: the browser-capture lip-sync path (`uploadAudioForLipSync`) also stores ephemeral audio as `chat_attachment`. One `.webm` on the live store today.
- R2: `startup/shutdown.py:1656` sets `runtime.attachment_reaper = None` inside the `desktop_lifecycle` block, not the reaper's own block.
- R3: a failed pipelined sentence's browser fallback returns at once, so its `SpeechSynthesis` speech can overlap the next server sentence (this predates BF-918).
- R4: when AD-1346 M3 lands, the resident Piper spawn will need classifying as an effect point under the `system` principal.
- R5: prewarm the default voice and prosody worker at boot, to remove the about 0.5 s first-request load. Deferred; measure after the change first.
- R6 (review round 1, area A): deleting the legacy WAVs is tracked separately. Its design must settle where a reference can live: the knowledge repository outside the data directory (live `knowledge.repo_path` is empty, so `~/.probos/knowledge`, holding each episode's `outcomes`), ids split across SQLite overflow pages in raw scans of WAL files and tar members, git object history in `ship-records/.git`, and other compressed containers. The Architect recommends a conditional quarantine move rather than a delete, so that a missed reference can be recovered.
- R7: 164 WAV files have no index entry (1,126 on disk, 962 indexed; 1.496 GB on disk in all). They have no origin, no reaper or tool touches them, and the size cap does not count them (`total_size_bytes` adds up index entries only). Predates BF-918.
- R8: whether AD-1340 erasure covers the knowledge repository's copies of an episode is unverified.
- R9 (review round 1, area B, B4): the attachment store runs its blocking I/O on asyncio's default pool (`write`, `_find` and so `exists`, `get_path`, `read`, `size`). With crew work saturating that pool, storing the spoken WAV (`routers/avatars.py`) and serving it (`routers/chat.py`) wait. Ordinary reach, not a regression (the dependency predates BF-918; this change narrowed its isolation claim to synthesis and lip-sync). **An open slice (M4) of #1626, by the Architect's decision of 2026-10-24 (the convergence rule leaves no room to register an ordinary-reach finding):** a bounded I/O executor owned by the store, covering `write`, `_find`, `read` and `get_path`, closed after the attachment reaper. The live `store_ms` (§16 step 1) is its verification, and evidence that the reach is not ordinary (at least 20 replies with the crew active, p95 `store_ms` under about 50 ms and the HAR's `GET /api/chat/attachments` p95 under about 100 ms) would move it to the register.
- R10 (B5; round 2, area B finding 2): cancelling a caller frees its admission slot while ffmpeg, rhubarb or Piper still occupy a voice thread (measured: 20 unfinished against a bound of 16), and a caller-cancelled ffmpeg conversion leaves its temporary WAV behind (`_convert_to_wav` creates it before the await; measured `converted_left=1`, the same on `26bec26d`). Reached only by injected cancellation; both predate BF-918. Follow-up: one done-callback on the executor future that holds the slot and removes the conversion output after the work finishes (an unlink at cancellation would race a running ffmpeg), or kill the child when the caller cancels.
- R11 (Low): a resident Piper's `stderr.log` grows for the process lifetime (one real-time-factor line per request), and `_stderr_tail` reads the whole file to quote 500 bytes.
- R12 (review round 1, area C): pipelined replies are cut after their first sentence when another utterance is queued. Under pipelining every sentence shares the entry id (BF-767), so the first sentence's `end` dispatches the queued utterance, whose `_playNow` takes the id, and the remaining sentences stop. Predates BF-918; P2, ordinary reach with pipelining on (default off). The fix touches the arbiter's own contract: its wait would have to end on the reply's last sentence. **An open slice (M5) of #1626, by the Architect's decision of 2026-10-24:** it would truncate the pipelined replies of the live acceptance itself, so it lands before the measurement.
- R13 (fixed in review round 2, §7.30b; kept here so that the numbering holds; round 1's "without effect after a barge-in" was wrong): `ProfileChatTab` ignored `dropped`. Before BF-918 that leaked a flushed or pre-empted entry's in-flight key. D7a made the leak reachable by an ordinary barge-in before audio, and a later identical answer then stranded the controller in `agent_speaking`. The residual is R19. Review round 3 (C F1): the round-2 listener outlived its arm, so a closed or switched profile chat's late `end` (as on main) or `dropped` completed the next arm's turn; A9 retires every reply listener on React's cleanup of its arm and on a delivered `'inactive'` (§7.30f); review round 4 found the coalesced-notification exception (R21) and the same-arm older `end` (slice M6).
- R14: a media error after `start` fires the server `end`, and then the browser fallback speaks with a second start and end pair (R3's family; reached only by an injected fault; predates BF-918).
- R15 (review round 2, area A, F2; P2, injected only): overlapping size sweeps on one store over-evict. Each `sweep_once` takes its own `total_size_bytes` and stops on it (measured: 200 bytes removed where 100 sufficed). Production runs one sweep at a time (one `AttachmentReaper(` at `finalize.py:757`, whose `_loop` awaits each sweep; `start` is idempotent), and the counts stay honest. Follow-up, when a second caller appears: serialize the size pass per store, not per reaper (two reapers on one store would also overlap), or re-read the total under the store lock for each removal.
- R16 (review round 2, area A, F3; P2, injected only): a second writer to one attachment root (another store object or process) is not coordinated, so a stale index removes an entry the other promoted. Production has one `FilesystemAttachmentStore(` (`routers/chat.py:1017`, cached per runtime), and AD-816's pidfile allows one vessel per data directory. The precondition is stated in §9 and in `unlink_if_unchanged`'s docstring. Outside it: two vessels whose data directories differ but whose `attachments.attachments_dir` is the same, or an external writer. Follow-up, if more than one writer must be supported: an interprocess lock, reloading the index while it is held.
- R17 (review round 2, area B; Low, injected only, not a regression): `PiperWorker._release` removes the worker's directory once, with `ignore_errors`. When a killed Piper has not exited within `wait_seconds` (on Windows it still holds `stderr.log`), the directory remains with no owner. Follow-up: remove it again after the process has exited, or log the failed removal.
- R18 (review round 2, area C, finding 2; P2, injected only, predates BF-918): a stop does not end the rest of a meeting batch, because `speakRepliesSequentially` breaks only on a generation check that `stopSpeaking` does not move. Not reachable today: `stopSpeaking`'s only non-test caller is the controller's barge-in (`conversationController.ts:356`), which runs only in `agent_speaking`, a state the group path (`submitTranscript`) never enters; the in-call mute ends a batch and works. It becomes reachable once any meeting-time stop caller exists (a stop button, meeting-mode barge-in, a wake-word "stop") or a second `ProfileChatTab` shares a document. Design, when it is wanted: a stop epoch in `speechQueueStore.ts` (not a new `voice.ts` export: about 50 test files mock `voice` with factories that would lack it), bumped first in `stopSpeaking`, captured per batch and compared in `useMeetingVoice`'s `shouldContinue`; the stopped reply still runs `onUtteranceEnd`, so that `setGroupTyping(null)` at `ProfileChatTab.tsx:1831` runs.
- R19 (review round 2, area C; P3, narrow, partly pre-existing): a lost-claim waiter (BF-718) has no utterance id, so it cannot see the `dropped` of the identical in-flight utterance it waits on. If that utterance is dropped, the waiter stays subscribed until React's cleanup of its arm or a delivered `'inactive'` retires it (review round 3, §7.30f; R21 is the exception). Two branches, with different prerequisites (review round 4, C-R4-3, executed): (i) stuck: if the drop was a pre-emption while the turn waits, the turn stays in `agent_speaking`. This needs only identical text in flight and that drop (executed: 2 chat POSTs, 1 TTS POST, one `cancelled-before-audio` `dropped`, state `agent_speaking`), and a barge-in or the arm's end recovers it. (ii) early completion: within that arm the waiter can complete a later turn early on another `end` from the same agent, which needs that further same-agent terminal event; slice M6's turn guard removes this branch for a waiter whose reply is no longer the newest. Follow-up (with R20): give the in-flight set utterance ids, so that waiters correlate exactly.
- R20 (review round 3, area C, F2; P3, injected only, not a regression; predates BF-918): BF-718's in-flight set is cleared per agent, so any `end` or `dropped` from an agent clears every in-flight key of that agent, including the key of a different utterance that is still preparing or playing. A later reply with that utterance's text then loses its speech claim, finds no in-flight key and completes the controller's turn at once while that utterance still plays: the barge-in guard detaches and the silence timer starts early. The same early completion follows a remount, whose in-flight set starts empty while the speech ledger (module-scoped, BF-765) keeps the claim. Demonstrated only with an injected owner flush (the round-3 reviewer's `per-agent-cost.test.tsx`: one chat POST, one TTS POST, `silence_pending`, then a `start` with no `end` between). The per-agent rule was chosen so that a missed correlation never strands the controller. Follow-up: key the set by utterance id once the lost-claim path can learn it (with R19).
- R21 (review round 4, area C, C-R4-2; condition corrected in review round 5, C-R5-1; P3, injected only, not a regression: the same result on `26bec26d`, `ba794bb1`, candidate 5 and candidate 6): `conversationController.ts` (unchanged) calls a replaced or disarmed arm's `onStateChange('inactive')` from the teardown itself (`armConversationMode`, `:257-261`; `_disarmOwned`, `:506-516`; `_notifyInactive`, `:518-527`), but a pre-empted arm's only from a microtask (`onPreempted`, `:289-302`, is the one caller of `_enqueuePreemptedInactiveNotification`, `:529-560`). That queue has one slot: a later pre-emption queued before the microtask runs (in practice, within the same task) replaces it, and the earlier arm's `'inactive'` is never delivered. This contract calls that a coalesced `'inactive'`. A still-mounted older arm then receives neither React's cleanup nor its `'inactive'`, and its reply listener survives. A plain replacement within one task is not this case (review round 5, `coalescing.test.tsx`: the older arm's `'inactive'` delivered once, no late completion, `agent_speaking`). That reply's own late `end` then completes the replacement's turn. Demonstrated by the reviewer's `superseded-inactive.test.tsx`: two `flushSync` renders of a second profile, with a mic-arbiter acquire and release between them and the first profile still mounted; the result is `silence_pending`, with events `start(old) end(old)`. C12 covers a coalesced notification followed by an unmount, not a mounted older arm. Round 5 reproduced it on candidate 6 (no delivered `'inactive'`, one late completion, `silence_pending`; with the older profile unmounted instead, none and `agent_speaking`). Ordinary production reach was not established: a real user would need two profile chats mounted at once and two successive pre-emptions of conversation arms within one task, that is, a higher-priority mic holder (press-to-talk) taking the mic from the older chat's arm and, before any microtask runs, from a newer arm armed in that same task. Follow-up: the controller keeps each pre-empted owner's private `'inactive'` (one pending notification per owner, not one slot) while it coalesces the global state notifications, so every pre-empted arm is told; no controller redesign.
- Slice M6 of #1626 (review round 4, area C, C-R4-1; P2, ordinary reach, not a regression: the same result on `26bec26d`, `ba794bb1` and candidate 5; a slice by the Architect's brake decision of 2026-10-24, under the convergence rule; no R number): within one arm, an older reply's own late `end` completes the newer reply's turn. The turn guard of §7.30b applies to `dropped` only, and `markAgentReplyComplete` completes whichever turn is current. It is reached in conversation mode when a second utterance begins while the first request is still `submitted` (its VAD onset causes no barge-in) and its reply queues in the arbiter behind the first reply. Executed (`arm-boundaries.test.tsx`): `silence_pending` before the second audio, events `start(1) end(1) start(2)`, no `end(2)`. Design: the `end` branch retires without completing when `replyTurn !== ourTurn`, for the claimed and the lost-claim listener alike. The controller sets `agent_speaking` and calls `onAgentReply` only while the arm that sent the request still owns it (`conversationController.ts:433-435`); `_owns` (`:158-163`) compares the arm's generation, options and agent and carries no request or turn token, so within one arm an older request's reply that arrives after a newer one is still delivered (review round 5, C-R5-2, executed: both replies reached the component, newest first). "Newest" in this slice therefore means the reply whose `onAgentReply` call came last in its arm (the component's per-arm counter orders callbacks by arrival, not requests), and M6 completes the turn only for that reply. The newest reply's lost-claim waiter still completes on its agent's `end` (BF-718 unchanged), and BF-290's immediate completion happens synchronously for the newest reply. Tests: the reviewer's case (an older own `end` leaves `agent_speaking`, and the newer reply's own `end` then gives `silence_pending`), an older lost-claim waiter retired by a newer reply, and a control that the newest lost-claim waiter still completes. One mutation row, whose pinned line differs in text from TS15's. M6 does not gate the live acceptance (§16); #1626 closes after it.

The register numbers on #1523 (F-389 onward) are assigned when the register comment is posted, in the order of this list (R1 to R8, R10, R11 and R14 to R21); R9 and R12 are the open slices M4 and M5 of #1626, slice M6 (review round 4) has no R number, and R13 is repaired, so none of the three goes on #1523.
