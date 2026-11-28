# BF-932 (#1670) batch 1: the dream cycle gives the event loop turns (D1) and a loop-stall sampler names any blocker (D2); the Captain's DM stops waiting for the camera (S1) in batch 2

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27. Revised by: claude-architect, D1 repair after review round 1 (2026-11-27). Changed: sections 2, 3, 3a, 4, 6.2 (P2, P4 changed; P35, P36 new), 6.5, 6.21 and 6.22 (one D1 sentence each), 7, 8.1-8.3, 9-14. Sections 6.6-6.20 and the D2 and S1 tests, pairs and rows are unchanged.
**Revised by:** claude-architect, D2 repair after review round 1 (2026-11-27). Changed: the header's ASCII and test-count lines, sections 2, 3 (D2, D2d; D2e and D2f new), 6.6 (whole), 6.8 (P14's comment), 6.9 (P15's docstring), 6.13 (whole), 6.21 and 6.22 (one D2 sentence each), 7, 8.1-8.3, 9, 10, 13, 14. D1 and S1 text is unchanged.
**Revised by:** claude-architect, S1 repair after review round 1 (2026-11-27). Design A of the S1 consult (`logs/architect/inputs/consult-s1-answer.txt`): the group round is reverted and keeps awaiting the describe; F3 (`hook=failed`), F2 (accepted and pinned), F4 (the config description, comments and the live instruction). Changed: the header's test-count line, sections 2, 3 (S1, S1b; S1c-S1e new), 4 (commit 3; 4b new), 5, 6.14-6.20 (P19, P20, P24, P26, P28 changed; P21, P22, P29-P32 removed; 6.20 rewritten; 6.20a and P37 new), 6.21 and 6.22 (the S1 sentences), 7, 8.1-8.3, 9, 10, 11, 12, 13, 14, 15. D1 and D2 text is unchanged.
**Revised by:** claude-architect, D1 repair after review round 2 (2026-11-27). Changed: sections 3 (D1d), 3a (the checks' row), 6.2 (P2's helper), 6.5 (`_seed_notes`, `_consolidate_on_disk`'s `loop_in`, three constants, two new tests), 7 (the `read_entry` row), 8.1-8.3 (D1 text; M16 rewritten, M19 new), 9 (property 11), 10 (D1 entries), 13 (D1 bullets), 14 (M19). D2 and S1 text, P33 and P34 are unchanged.
**Revised by:** claude-architect, D2 repair after review round 2 (2026-11-27). R2-F1: `run()`'s cancellation no longer logs before it sets the stop event (the `CancelledError` arm is removed); one new D2 test. R2-F2: the claims that the sampler's logging cannot reach the loop thread or the process's exit are qualified. Changed: the header's test-count line, sections 3 (D2e, D2f), 6.6 (the module docstring and `run()`), 6.13 (`_HELD_S`, `_Signals`'s docstring, one new test), 7 (the `run()` row), 8.1 (D2), 8.3 (N5's killers, N21 new, the D2 round-2 note), 9 (properties 5, 13), 10 (D2 round-2 entries), 13 (two D2 bullets), 14. D1 and S1 text, P33 and P34 are unchanged.
**Revised by:** claude-architect, D1 repair after review round 3 and the round-three brake decision (2026-11-27). B3: Step 7g compares each member's file bytes (a sha256 fingerprint taken before the read) instead of the loaded document (R3-F1, R3-F2); a containment test (R3-F3); the `.nan` claim and the alias residue withdrawn (R3-F4). Changed: the header's test-count line, sections 3 (D1d), 3a (two rows), 4 (commit 1's pair list), 6.2 (P2's helper; P38 new), 6.3 (P39, P40 new), 6.5 (whole), 7 (the `read_entry` row replaced), 8.1-8.3 (D1 text; M16 and M19 retired, M20-M24 new), 9 (property 11), 10 (D1 round-3 entries), 11 (one bullet), 13 (D1 bullets), 14. D2 and S1 text, P33 and P34 are unchanged.
**Revised by:** claude-architect, D2 repair after review round 3 and the round-three brake decision (2026-11-27). R3-F1: the DEBUG-handler test fails its setup when its held handler's guard expires (`_Signals.gate_expired`). Changed: section 6.13 (`_Signals.__init__` and `emit`, one assertion in the DEBUG-handler test), 8.1 (D2), 8.3 (the D2 round-4 note), 9 (property 5), 13 (one D2 bullet). The header's test count, D1 and S1 text, `loop_stall.py`'s fence, P33 and P34 are unchanged.
**Revised by:** claude-architect, S1 deferred to batch 2 after review round 2 (2026-11-27). S1's round-2 delta review asked for changes (R2-F1 P2, R2-F2 P3, R2-F3 P3), so under the cutoff of 21:15Z batch 1 is D1 + D2. Changed: the title, this header, sections 2, 3 (S1 label, S1c, S1e), 4, 6 (a scope note; P33 and P34's REPLACE), 7-11 (scope notes), 12, 13 (a new S1 round-2 subsection with the batch-2 design), 14, 15. No D1 or D2 fence, no other pair, no M or N row, section 5 and 4a are unchanged.
**Status:** batch 1 lands D1 and D2 (ready to build: commits 1, 2, the contract-only commit and the trackers commit of section 4). S1 is specified and built but deferred to batch 2 (section 13, "S1, review round 2 and the batch-2 design"; S1e); the S1 sections (6.14-6.20a, P19, P20, P23-P28, P37, 4b) describe batch 2 and are not applied in batch 1. **Owning issue:** #1670 (stays open until the Captain's live re-measurement). Commit bodies say `Refs #1670.`
**Base:** main `63c536b34042e81a1eadea4b457c572bf341d9e7`, branch `fix/bf932-reply-never-waits-20261127`. **Number:** BF-932 (existing; no new AD or BF number).
**License posture:** standard library only, no third-party component.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn on the clean base. All new hand-written text is ASCII. Generated files are exempt: `scripts/gen_config_reference.py`:132 renders a `ge` bound as U+2265 and an `le` bound as U+2264, so the new `loop_stall_warn_seconds` row of `docs/development/config-reference.md` carries those two characters, as its 264 existing `ge` renderings do.
**Estimated tests (batch 1):** 49 new items in 2 new files (D1 22, D2 27); changed in place: 1 pin each in `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1270e2_config_models.py`, `tests/test_ad1152_agentic_correlation.py`; 1 autouse fixture in `tests/conftest.py`; 0 removed.
**Estimated tests (batch 2, S1 as specified here):** 4 new items in 1 new file; changed in place: 3 tests and 1 helper in `tests/test_bf932_reply_path_timing.py`, 1 in `tests/test_dm_camera_hook_deadline.py`; plus the R2-F1 tests of section 13 (drafted with batch 2).
**Scope boundary:** no edit to `src/probos/routers/avatars.py`, `src/probos/audio/`, `src/probos/attachments/`, `ui/src/audio/`, `src/probos/utils/step_timing.py` (shared with the voice track) or `config/system.yaml`.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| Live log `probos.log.1`, 2026-10-25 19:28:56 to 19:29:14 | no line from any logger for 18 s; the camera consumer logs every 1 to 3 s before and after. The dream's Step 7f archived procedures at 19:28:38-39; Step 7h wrote `procedures/cc82c2c9...yaml` and Step 8 logged `Dream cycle predicted 4 capability gaps` at 19:29:18 | the event loop was held between Step 7f and Step 7h, where Steps 7f2 and 7g run. The Captain's message of 19:29:18 arrived as it ended |
| Live log, 2026-10-30 23:40:49 to 23:41:07 | 18 s with no line; the next lines are a TTS route with `store_ms=17618`, `Record written: procedures/be8baa98...yaml` and `Dream cycle predicted 4 capability gaps` | the same position in a second dream; a store write waited 17.6 s behind the loop |
| Live log, 2026-10-25 19:29:38 to 19:29:49 (the window the issue measured) | `probos.heartbeat` logged `uptime=427s` at 19:29:46, exactly 60 s after `uptime=367s` (`__main__.py`:923-931, a 60 s `asyncio.sleep` loop) | that hole was not a loop block: the loop ran its timer on time. Something awaited there (the consult's H-hook or H-recall) |
| Live log, 19:23:41 to 19:46:12 (pid 61060) | 7 of the 22 gaps between heartbeats exceed 60 s by 2 to 6 s (`uptime` 183 to 246, 609 to 671, 731 to 795, 856 to 922, 983 to 1045, 1285 to 1347, 1347 to 1412) | the loop was blocked at those instants too, some outside the two full-dream windows (19:28:38-19:29:24, 19:42:5x): other blockers exist, which D2 must name |
| `dreaming.py`:924-1229, Step 7g (AD-551) | `list_entries("notebooks/")` (:932), then `read_entry` of each note for the per-agent pass (:949-957) and again for the cross-agent pass (:1065-1075); per-agent pairs (:963-970) and all cross-agent pairs (:1079-1088), each pair re-tokenising the inner note (`text_to_words` :966, :1084); coherence pairs per component (:1110-1115). No `await` in :961-989, :1077-1102, :1107-1116; `read_entry` and `list_entries` contain no `await` (section 10) | with 2,777 notes on the vessel (Glob `notebooks/*/*.md` under `%LOCALAPPDATA%\ProbOS\data\ship-records`, 0 archived), Step 7g reads and YAML-parses every note three times and runs 2777*2776/2 = 3,854,476 cross-pass iterations without one turn for the loop |
| `episodic.py`:2670-2692, Step 7f2 (AD-873, `dreaming.py`:911) | up to 500 episodes (`limit=500`, :2613), each a synchronous `_collection.get` and `_collection.update` (`update_episode_metadata` :2482-2511, no `await`) | up to 1,000 synchronous Chroma calls without a turn |
| `records_store.py`:1571-1608, `list_entries` | reads and parses each file (:1584-1585) in one synchronous pass; called by Step 7g (:932), AD-555 (`notebook_quality.py`:217) and AD-563 (`knowledge_linter.py`:58) in every dream | three more full passes per dream without a turn |
| `routers/agents.py`:3494, `thread_fanout.py`:406 | `await _consumer.force_describe_current_frame(timeout_s=4.0)` before the scene is rendered | the Captain's reply and every group round wait up to BF-977's 4 s deadline for a describe (the consult's H-hook) |
| none | no instrument names what holds the loop | the next blocker is found only by reading log gaps by hand |

## 2. Overview

- **D1.** A counter `LoopYield(every)` (new `utils/loop_yield.py`) says when a synchronous loop should `await asyncio.sleep(0)`. Step 7g yields every 16 reads or word sets and every 2,000 pair iterations, and builds each note's word set once instead of once per pair. `list_entries` yields every 16 files in its default mode; the strict mode keeps one uninterrupted pass. The AD-873 sweep yields every 8 episodes. The budgets are counts, not times. Because those turns let a writer run between Step 7g's reads and its writes, Step 7g writes a consolidation only when every member of the cluster still reads as it did when loaded, and archives a member only when that member still does; nothing between each check and its write or rename awaits. When no note changes during the step, clusters, convergence events and reports are the base's. The BFS, the final intersection and the checks themselves stay unpaced (3a).
- **D2.** New `utils/loop_stall.py`: `LoopStallSampler` beats on the loop every quarter of the threshold. A daemon thread reads the beat. When the beat is older than the threshold, the thread logs one WARNING with the loop thread's innermost frames as `dir/file.py:line function`. The first beat after that stall records its own gap, and the thread logs that gap in one INFO (D2f). At most 10 WARNINGs per 60 s (`suppressed=N` on the next). `ProbOSRuntime.start` spawns it last through `_spawn_background`; it stops watching when `shutdown()` begins, and the AD-824 sweep cancels its heartbeat, which stops the thread (D2e states exactly what that guarantees). One config field: `system.loop_stall_warn_seconds` (default 1.0; 0 starts nothing).
- **Batch 1 is D1 and D2.** Commits in this PR, in order: 1 (D1), 2 (D2), the contract-only commit (this file), 4 (trackers). Commit 3 (S1) and the 4b generators are batch 2, not in this PR. In batch 1 the DM route and the group round are byte-identical to the base: both still await the describe (BF-977's 4 s bound).
- **S1 (batch 2, deferred; built and reviewed twice).** New `refresh_scene_in_background(consumer, *, timeout_s)` in `perception/consumer.py` starts `force_describe_current_frame` as a task held in a module set and returns. The DM route calls it instead of awaiting the describe; the group round (`thread_fanout.py`) is not changed in batch 1 and still awaits it (BF-977's 4 s bound, once per round). BF-977's deadline and single-flight permit run unchanged inside the call. The route line writes `hook=scheduled` once the task is started and `hook=failed` when starting it raised. The fresh description is present once the describe lands in working memory; an immediate second DM may still get the sentinel. The `dm_force_describe_enabled` description says so (P37).

Rejected, one line each:
- D1 in a worker thread (`asyncio.to_thread`): the pure-Python kernel holds the GIL, but CPython forces a switch every `sys.getswitchinterval()` (5 ms), so the loop would get its turns and the output would stay identical over a snapshot. It is still rejected: it needs the kernel extracted into a pure function (a larger diff), a running thread cannot be cancelled (a dream cancelled at shutdown would wait for it), and it holds a default-executor thread that the records store's git calls share (the consult's H-pool).
- D1 in a process pool: on Windows each worker spawns and re-imports `probos` and pickles 2,777 word sets per pass, and the reads cannot move with it.
- D1 with an exact prune (Jaccard <= min/max set size) or an inverted index: a speedup the property does not need, and it adds a float-equality proof. Considered, deferred.
- D2 with asyncio debug mode (`slow_callback_duration`): debug mode is costly everywhere and reports a callback's repr after it returns, not the stack while it blocks.
- D2 with `faulthandler.dump_traceback_later`: a single process-wide timer (re-arming it from the heartbeat cancels any other user), and it writes every thread's stack to a file descriptor, outside the log, with no resume line and no bound.
- D2 through `TimingLines` (`step_timing.py`): it writes at INFO, and that file is shared with the voice track (scope boundary). `_WarningBudget` repeats its rule (about 20 lines).
- A new config model for D2: it would add a public name, a model and a section to every frozen consumer. One field on `SystemInfo` adds only a field.
- S1 with a shorter deadline, or waiting only when the message mentions vision: either still spends the wait on a reply.
- S1 with a bounded wait (about 1 s) before rendering (the consult's design C): still a delay on every DM, which the Captain's rule forbids; it helps only agents with no profile and only when the vision call ends inside the bound.
- S1 in the group round now (the consult's design B, for the round): the round's episode reads `latest()` after the reply (`thread_fanout.py`:1079-1141), so a frame landing after dispatch is bound to an episode whose prompt never saw it (the round-1 review's F1). Fixing that means carrying a dispatch-time snapshot into the episode and its embedding (`cognitive/episodic.py`:4551): memory provenance, batch 2.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Blocking sites and the fix for each are in section 3a. Budgets: 2,000 pair iterations, 16 reads or word sets, 16 listed files, 8 episodes, per turn | (a) is the smallest change that bounds the runs 3a marks blocking (the reads, the listing, the word sets, the pair, cross and coherence comparisons, the decay sweep); 3a's residual rows (the BFS, the final intersection, the publication checks of D1d, Step 12) stay unpaced. With no concurrent writer the output is identical: the same comparisons run in the same order, and only `await asyncio.sleep(0)` is added between them. Precomputing word sets is exact (`text_to_words` is pure: `similarity.py`:17-19). Only the per-unit cost is unmeasured; D2 names any segment that still exceeds the threshold |
| D1b | `list_entries(strict=True)` is not paced | its three callers (`archive_promotion.py`:310; `stand_down.py`:281, under `asyncio.wait_for`; `recreation/history.py`:184-185, the AD-1358 head-to-head tally, capped at `MAX_GAME_RECORDS` records) treat the listing as one pass; the first two read a listed file that cannot be read as "retry". A turn in the middle would let a loop-thread writer (Step 7g's archive rename, `dreaming.py`:1025) change the tree mid-listing |
| D1c | Step 12's bulk Chroma calls (`dreaming.py`:1584, :315 via `_get_importance_map`) are not changed | each is one synchronous call, not a loop, so a yield cannot split it. Moving it to a thread needs a Chroma thread-safety review (the consult deferred this). If D2 names them on the vessel, batch 2 takes them |
| D1d | Step 7g publishes a cluster only when every member's file still has the bytes it had when the step loaded it, checked immediately before the primary's `write_entry`; and archives each other member only when its file still does, checked immediately before its rename. The bytes are compared by fingerprint: `RecordsStore.entry_fingerprint(path)` (P40, new and additive; async with no internal `await`, like `read_entry`) resolves the path through `_safe_path` and returns the sha256 hex digest of `file_path.read_bytes()`, or `None` when the file does not exist. At the load (P38) the step takes the fingerprint first and then calls `read_entry`; it keeps a note only when the document is truthy and the fingerprint is not `None`, and records the fingerprint as `item["_fp"]`. The helper `_reads_as_loaded` (P2) takes the fingerprint again and returns `fp is not None and fp == item["_fp"]`; the call and the comparison sit in one `try`, and anything raised there counts as changed (DEBUG), so no failure reaches Step 7g's whole-step handler. A stale cluster is skipped (nothing written, archived or counted; one INFO); a changed member stays live (one INFO). The helper is used at both sites (P35, P36); the callers are unchanged from round 3 | D1's turns let a revision land between a member's read and the publish; the publish then overwrote it with the cached copy (the Diff Reviewer's P1, reproduced by the orchestrator's probe). **Windows.** `entry_fingerprint` and `read_entry` have no `await` (`read_entry`: `records_store.py`:1500-1526; `read_bytes` on the loop thread follows `read_entry`'s own `read_text`, :1504), so at the load nothing suspends between the fingerprint and the parse; in the helper nothing suspends between the fingerprint and the return, and at each site nothing suspends between the check and the write (`write_entry` has none before its `write_text`, :856; the first `await` is :860) or the rename (:1021-1025 at the base). An optimistic check made atomic by the loop itself, with no lock, version field or new config. A write that lands before the load's fingerprint is in the document the step loaded; one that lands after it changes the bytes. The fingerprint comes before the parse so that, if anything ever ran between them, the result would be a spurious skip, never an overwrite (the order test, M21). **Scope: the whole file.** Identical bytes load to an identical document, so a publish from the cached copy is then exact. Every writer reads as changed: `write_entry` (a new `updated` and `revision`, :803, :819-820), `publish` (:1641; it bumps `updated`, :1662, not `revision`), a rename away (`_archived/`) and a deletion (the fingerprint is `None`). A byte change that does not matter to the dream (a whitespace edit, the same document written in other bytes) skips the cluster for one dream; nothing is lost or overwritten. **No classification gate.** The method returns a digest of the file's bytes, from which a caller learns only whether the bytes equal those of an earlier digest; Step 7g keeps a fingerprint only for a note that passed `read_entry`'s gate with `reader_id="system"` (a denied note is never appended), and the store's root is already public (`repo_path`, :696). No agent reaches it: its only calls are Step 7g's three (P38, P35, P36), and no tool, route, registry or test enumerates `RecordsStore`'s methods or dispatches to them by name (Absence Verified, 10). The skipped cluster is found again by the next dream. The archive check also closes the base's own window (a member revised during the primary's git and indexer awaits, or between two renames, was archived unmerged); it is the same helper and two lines. Rejected: comparing the loaded documents, by `==` (raises `RecursionError` between two loads of a frontmatter that contains itself: round 2, F1), by `repr` (raises `ValueError` on an integer past CPython's 4,300-digit conversion limit, R3-F1, and differs between two loads of a `!!set` of tagged NaNs, R3-F2) or by a hand-written structural comparator (it must cover the loader's whole type domain, and two rounds in a row each found a new corner of it): bytes have no type domain. Comparing only `revision` and `updated` (the brake's B1): `publish` bumps only `updated`, a hand-written or foreign file can change its frontmatter without either, a write to a note whose frontmatter did not load restarts its revision (:773-775), and the two values can themselves be any YAML type. A lock on the records store (every writer would have to take it; a new contract for every caller); retrying the cluster within the dream (a busy note could keep the step looping; the next dream retries for free). A sync `entry_fingerprint`: on the `AsyncMock()` stores the existing Step 7g tests build, a sync call returns a new coroutine object each time (stale everywhere, plus "never awaited" warnings); awaited, an `AsyncMock` child returns the same object every call (8.2) |
| D2 | Heartbeat coroutine plus daemon thread plus `sys._current_frames()`; one WARNING per stall, one INFO per resume of a reported stall; 10 per 60 s. The constructor refuses a threshold whose quarter is not in (0, `threading.TIMEOUT_MAX`] (so infinity, NaN and 1e300 are refused; the config's 0.1 to 60 always passes). A failed check, or a failed wait, is dropped at DEBUG with the error's text only (`repr`), never `exc_info`: a kept traceback would keep the sampled frames, and the loop thread's locals, alive as long as a handler keeps the record. `_innermost_frames` drops its frame local in a `finally` | the frames are read while the loop is blocked, so the line names the blocker (section 1's need). `lookup_lines=False`: no file read while the GIL is held. No locals and no arguments are captured. `requires-python = ">=3.12"` (`pyproject.toml`:9): CPython issue 106883 (a collection inside `sys._current_frames` deadlocked) was seen on 3.11. The threshold check reuses the stdlib's own limit (`Event.wait` raises `OverflowError` past it), so no new constant |
| D2b | Config: `SystemInfo.loop_stall_warn_seconds: float = 1.0`, `ge=0`, `le=60`, finite, 0 or at least 0.1 (validator); 0 is the kill switch | on by default (the Captain's direction). One float field: no config-profiles row (`check_config_profiles.py`:166-171 lists only default-False bools). A yaml that sets the key still loads after a revert: `SystemInfo` has no `extra="forbid"` |
| D2c | Spawned last in `start()` (after the SQLite backup loop, before `self._startup_complete = True`, which stays last: `test_issue1419_failed_start_rollback.py`:164). `active=lambda: not self._shutdown_started` | a failed start never spawns it, so the rollback tests see nothing new. Shutdown's own synchronous steps are not reported; they are not the reply path |
| D2d | `tests/conftest.py` makes `LoopStallSampler.run` a no-op, in the pytest process, unless the test requests `bf932_live_loop_stall_sampler`. A runtime a test boots in a child process runs the real sampler: `tests/fixtures/federation_cluster_node.py`:182-184 (the six `tests/test_ad1198_*_gate.py` files) and the `python -m probos` children of `tests/test_ad1137_quickstart_chain.py`:221 | a loaded test host pauses a process for over a second now and then, and many booted tests assert that no WARNING was written (96 files match `levelno >= logging.WARNING`-style checks). The real sampler runs in the D2 tests, including a booted runtime. The child processes are left alone on purpose: a child writes a sampler line only if its own loop stalls past 1 s, and the parents read a child's output only for named markers (`federation_cluster.py`:590, :597, :777-790: `marker in line`, `_REFUSAL`, `_TRANSPORT_FAILED`; `test_ad1137_quickstart_chain.py`: named phrases and `_assert_no_key`), none of which a sampler line contains, and never for the absence of a WARNING. Turning the sampler off in the children would need a config written for each child (six files and a fixture), for no observed failure (the Diff Reviewer saw none) |
| D2e | Shutdown, exactly: (1) the thread checks the stop event, the loop and `active` (`_ended`) at the start of every check and again after reading the frames, just before the WARNING; a WARNING whose frames were read after any of them said stop is not written, so the sampler never names its own join or shutdown's steps. (2) The heartbeat's cancellation sets the stop event and joins the thread for at most `_JOIN_TIMEOUT_S` (1 s) and then returns, whether or not the thread has ended. Nothing on the cancellation path logs before the stop event is set (review round 2, R2-F1: a DEBUG line there waited, in the verbose configuration, for the handler lock the thread's WARNING held, so the stop event was not set and the join bound did not apply until the handler returned). The thread ends at once unless it is inside a logging call; then it ends when that call returns (its next statement is the stop check), and it writes no further line. (3) A WARNING whose logging call began before shutdown can be delivered by a slow handler after the join returned; it names the blocker it sampled. (4) The thread is a daemon, so the interpreter does not wait for the thread's own code at exit. The sampler adds no wait of its own to the loop thread except that join. Its log calls go through the same handlers as everyone else's: while it writes a line, a log call from the loop thread (shutdown's INFO lines, for example) that reaches the same handler waits for that handler's lock, and so does `logging.shutdown()` at a normal interpreter exit (an `atexit` hook that takes every handler's lock), exactly as either waits for any other thread's write. The CLI ends with `os._exit()` and skips that hook (review round 2, R2-F2) | the bounded outcome rather than a stronger ownership rule. Waiting until the thread has really ended would make shutdown wait on an arbitrary log handler, the one thing the join timeout exists to bound; a non-blocking hand-off (a queue and a second thread) adds a moving part to deliver lines that can only be late, never wrong, once (1) holds. The thread holds no resource that shutdown releases: it reads the loop's state and writes log lines |
| D2f | The resume INFO carries the gap of the first heartbeat after the stall. When the thread finds a stall it records the stalled stamp (under a `threading.Lock` it shares with the heartbeat, held only to read or write the stamps: no logging, no frame reading, no wait under it); the heartbeat, under the same lock, records `now - stamp` at the first beat whose previous stamp is that one. The thread logs the recorded gap at its next check and clears both | the base read the latest stamp at the thread's next check, so a late check (a slow handler) reported a gap that included later beats (the Diff Reviewer measured 531 ms for a 109 ms gap). The lock makes the arming and the latch atomic with respect to the beat: without it, a beat that lands between the thread's read and its arm is missed, and the gap is lost or overstated. The loop thread waits on the lock only while the thread holds it for a few statements; no log call is made under it, so the heartbeat never waits on logging through this lock (the loop thread's own log calls can still wait for a handler lock the thread holds while it writes: D2e (4)). The log formats are unchanged |
| S1 (rows S1-S1e: batch 2, deferred; not applied in batch 1) | Module helper `refresh_scene_in_background` returning the `asyncio.Task` (never `None`; the caller checks the consumer first). Called only by the DM route, inside its existing `try`. `_hook = "scheduled"` is assigned after the helper returns; the `except` branch assigns `_hook = "failed"`; the default stays `"skipped"` (`agents.py`:2967) | the 7 test files that fake only `force_describe_current_frame` keep working; a consumer whose method does not return a coroutine makes `create_task` raise `TypeError` inside the same `try`, as `await` did, and the route line then says `hook=failed`, not `scheduled` (the round-1 review's F3: the first candidate assigned `scheduled` before the call). Held in `_SCENE_REFRESH_TASKS` until done (no fire-and-forget); a failure is logged once at WARNING by the done callback |
| S1b | The live-frame-aware freshness check is deferred; readiness is a reply that shows the current scene | the reply renders the working memory as it is. The fresh description is present once the describe lands in working memory; an immediate second DM may still get the sentinel (the round-1 review's F4 measured the first and an immediate second DM both getting it while one refresh ran). After more than `prompt_freshness_seconds` (120 s, `config.py`:2320) with no new described observation, a reply gets the AD-1055 sentinel "Camera not active..." (`working_memory.py`:124-134) although the camera is on: the Captain was idle and the scene is still (the supervisor drops low-novelty frames). The zero-code procedure (section 15): send a warm-up DM, wait about 5 s, and confirm a reply describes the scene; if the scene is still and the sentinel keeps coming back, raise `perception.prompt_freshness_seconds` in his own config. The four profile-bound agents behave as today: a forced describe never reaches them (S1e). If a recording shows the sentinel anyway, that is the trigger to build the check |
| S1c | F2 accepted: the DM's background describe now starts after `note_dm_activity()` (`agents.py`:3514); pinned by V5, which proves the ordering only. Narrowed in round 2 (R2-F2): the describe runs in the primary controller's mode at that moment, so it is charged as ENGAGED only when the primary is engaged (a DORMANT primary describes in AMBIENT; a non-primary DM target turns ENGAGED while cap enforcement reads the primary), and the counters aggregate successful calls whatever the mode. Batch 2 rewrites V5's comment to match | AD-733c-2's intent is that a DM engages the agent; at most one call per DM moves from the AMBIENT to the ENGAGED budget, and the difference is visible only at the caps (200 per session, 2,000 per day: `consumer.py`:331-342, :374-375 at the base; :347-390 on the candidate). The reviewer's probe used a cap of 10. Restoring describe-before-notify would need the route to wait for the task to start a vision call, which is a wait |
| S1d | The group round is not changed in batch 1: `_maybe_force_describe_frame` (`thread_fanout.py`:386-410, called once per round at :1022) still awaits the describe, bounded by BF-977's 4 s | the round's episode reads `latest()` after the reply (:1079-1088) and binds that frame (`visual_attachment_ref=` :1141, the only such assignment in `src`); a describe that lands after dispatch binds a frame the prompt never saw (the round-1 review's F1, a possible data-integrity defect). The awaited describe keeps the base's ordering for the round. The late read predates S1 (an ambient update can land there too) and goes on #1670's follow-up list as the batch-2 item that carries design B (a dispatch-time snapshot). F1 cannot happen on the DM route: a DM reply binds no frame |
| S1e | Recorded, not changed here: (1) a cancelled refresh is not bounded by `timeout_s`: BF-977 waits for its describe step through further cancellations (`consumer.py`:801-811), so a refresh cancelled at shutdown stays pending, holding its permit and its `_SCENE_REFRESH_TASKS` entry, until the storage thread returns; (2) forced describes carry `source: "force_describe"` (`consumer.py`:905), and `_filter_by_bound_sources` (:1209) drops them for an agent whose profile keeps the default `bound_sources` (`["camera", "screen"]`; the orchestrator's probe `probe_force_describe_filter.py`) | (1) is BF-977's design and an existing test pins it; S1 adds no new owner and no new bound; on #1670's follow-up list. (2) is a production defect reachable without S1 (filing policy criterion 2, `orchestrator.agent.md`:83): its own issue after the merge, after a duplicate search. Neither is repaired here: each changes BF-977's or the consumer's contract. Review round 2 (R2-F1 to R2-F3), the deferral and the batch-2 design that answers R2-F1: section 13, "S1, review round 2 and the batch-2 design" |
| S2/S3 | Not in this contract | the slot and priority (S2) and the recall budget (S3) bound `await` waits. The consult ranked them on evidence from a window that section 1 shows was not a loop block. After batch 1, the live `BF-932: dm turn` fields (`perceive_ms`, `recall_ms`), the `AD-672: Promoted queued intent ... waited_ms` lines and D2's lines show which of them is needed. Batch 2 is drafted from those numbers |

### 3a. Enumeration of the dream cycle's synchronous loops (vessel scale: 2,777 notes, 17 agents, `replay_episode_count: 50` in `config/system.yaml`:221)

| Step (file:line) | Work | Size at vessel scale | `await` inside? | Verdict and fix |
|---|---|---|---|---|
| 2, 3, 3.5, 4 (`dreaming.py`:486-505) | in-memory over the replayed episodes | `recent(k=50)`; 3.5 is 1,225 pairs | no | not blocking |
| 6 clustering (:514-572) | `cluster_episodes` per intent group | at most 50 episodes | no | not blocking |
| 7, 7b-7e, 7h, 7i, 11 | LLM calls and store writes | awaited I/O; 7i at most 50 pairs (:1282-1284) | yes | not blocking (not traced line by line) |
| 7f2 decay (`episodic.py`:2670-2692) | sync Chroma get + update per episode | up to 500 episodes, 1,000 calls | no | **blocking**: yield every 8 episodes |
| 7g listing (`records_store.py`:1571-1608) | read + YAML-parse each note | 2,777 files | no | **blocking**: yield every 16 files (default mode) |
| 7g per-agent reads (`dreaming.py`:949-957) | `read_entry`: read + parse (`records_store.py`:1500-1526); on the candidate preceded by `entry_fingerprint` (a byte read and a sha256, no parse; P38) | 2,777 | no | **blocking**: yield every 16 reads (a unit is the fingerprint and the read) |
| 7g per-agent pairs (:961-970) | Jaccard per pair, inner note re-tokenised | sum of n_a^2/2, about 226,000 at 17 agents of 163 notes | no | **blocking**: word sets once, built in a loop paced by the read counter (every 16); yield every 2,000 iterations |
| 7g cross reads (:1065-1075) | `read_entry` again | 2,777 | no | **blocking**: same read counter |
| 7g cross pairs (:1077-1088) | Jaccard per pair, inner note re-tokenised | 3,854,476 iterations | no | **blocking**: word sets once (also counted per 16); yield every 2,000 iterations |
| 7g coherence (:1107-1116) | Jaccard per member pair | k^2/2 per component | no | yield every 2,000 (same counter); reuses the word sets |
| 7g BFS (:979-987, :1094-1102) | `queue.pop(0)` with duplicates | O(edges), large only if most notes are similar (the reviewer's stress fixture: 8,129 per-agent and 3,073 cross-agent iterations) | no | residual, unchanged |
| 7g `word_sets` (:1130) | one tokenisation per member | k per component (the stress fixture: 96) | no | residual, unchanged |
| 7g publication checks (P35, P36; new) | one `entry_fingerprint` (a byte read and a sha256) and one string comparison per member before the primary's write, one more per other member before its rename | 2k - 1 fingerprints for a cluster of k; each linear in the file's bytes, whatever the frontmatter loads to | no, by design | residual: the check must have no turn before its write; bounded by the cluster's size |
| 10 AD-555 (`notebook_quality.py`:217-253) | `list_entries` + linear pass | 2,777 | no | covered by the listing fix |
| 10 AD-563 (`knowledge_linter.py`:58-101) | `list_entries` + `_detect_pair_inconsistency` for every pair within one topic (:88-100; about 20 regex calls per pair whatever the content) | measured on the vessel (orchestrator, `live_lint_pairs.py`, 2026-11-27): 16 agents, 2,777 notes, 2,548 distinct topics, largest same-topic group 8, so 348 pairs (about 10 ms at 25 us a pair). A vessel with large same-topic groups would block: 512 notes of one topic made 130,816 pair calls in 3.344 s with no turn (the reviewer) | no | listing covered by the listing fix; the pair pass is residual and not blocking at this vessel's scale. Not paced here (scope); recorded on #1670's follow-up list, and D2 names it if it blocks |
| 10 AD-444, AD-564, AD-565 (:1458-1520) | per-entry and per-agent loops | in memory; 17 agents | no | not blocking (AD-444 size not measured) |
| 12 pruning (:1564-1669) | `_collection.count()` :1584; one bulk `get(ids=...)` in `_get_importance_map` :315; `get_episode_ids_older_than` (not traced) | single calls | n/a | residual (D1c) |
| 9, 13 (:1393-1431, :1671-1700) | Ward Room reads and metrics | not traced | not traced | residual; D2 names them if they block |

## 4. Milestones and commits

Apply in this order; one commit per slice, then the trackers. Stage explicit paths only (never `git add -A`). Run `git diff --cached --stat` before each commit.

**Batch 1 (this PR), in this order:** commit 1 (D1), commit 2 (D2, with the 4a generators), the contract-only commit, commit 4 (trackers). Commit 3 (S1) and the 4b generators are **batch 2, not in this PR**: none of their files is staged or changed in batch 1.

| Commit | Sections | Subject |
|---|---|---|
| 1 (D1) | 6.1-6.5 (P1-P12, P35, P36, P38-P40 and the two new files) | `The dream cycle's notebook and decay passes give the event loop a turn after every stated number of units` |
| 2 (D2) | 6.6-6.13, then the generators of 4a | `A loop-stall sampler logs the stack of whatever holds the event loop past a configured threshold` |
| contract-only (batch 1) | none: `prompts/bf-932-reply-never-waits.md` only, the file as revised for batch 1 (it replaces the stale in-tree copy at C1, R2-F3) | `The reply-path contract keeps the dream yields and the stall sampler in batch 1 and moves the background scene refresh to batch 2` |
| 3 (S1): **batch 2, not in this PR** | 6.14, 6.15, 6.17, 6.18, 6.20, 6.20a (P19, P20, P23-P28, P37 and the new file), then the generators of 4b. Files: `perception/consumer.py`, `routers/agents.py`, `config.py`, `tests/test_bf932_reply_path_timing.py`, `tests/test_dm_camera_hook_deadline.py`, `tests/test_bf932_s1_scene_refresh_background.py`, `docs/development/config-reference.md`, `docs/development/config-facade-baseline.yaml`. Not `routers/thread_fanout.py` or `tests/test_ad978_group_perception.py` (byte-identical to the base) | `The Captain's DM starts the camera describe in the background; the reply no longer waits for it` |
| 4 (trackers) | 6.21-6.22, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change | `Reply-path trackers: PROGRESS and DECISIONS entries for the dream yields and the loop-stall sampler` |

No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Each body says `Refs #1670.`

### 4a. Config generators (end of D2, in this order; the generated files go in commit 2)

```text
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_profiles.py --check
```
Expected diff (the orchestrator measures it; any other file, model or row is a hard stop for the Architect):
- `docs/development/config-reference.md`: one row for `loop_stall_warn_seconds` in the `system` table, and the model's new docstring line.
- `docs/development/config-facade-baseline.yaml`: a field line `- {default: '1.0', name: loop_stall_warn_seconds}` under `SystemInfo`; `schema_sha256` moves for `SystemInfo` and `SystemConfig`; `field_definitions` 1877 to 1878 and `canonical_dump_leaves` +1; `canonical_dump_sha256` moves.
- No `config-profiles.yaml` row (bools only).

### 4b. Config generators (end of S1, after P37, same four commands as 4a in the same order; the generated files go in commit 3)

**Batch 2, not in this PR.** In batch 1 the generated files carry only 4a's diff.

Expected diff against commit 2 (the orchestrator measures it; any other file, model, row or hash is a hard stop for the Architect):
- `docs/development/config-reference.md`: the one `dm_force_describe_enabled` row (`config-reference.md`:2154 at the base) carries P37's description; no other line.
- `docs/development/config-facade-baseline.yaml`: `schema_sha256` moves for `PerceptionConfig` and for `SystemConfig` (which nests it, `config.py`:4033), and for no other model. Reason: `model_record` digests the whole `model_json_schema()` (`check_config_facade.py`:976, :981, `digest` :376-379), and a Field `description` is part of that schema. (The consult said the reference only; that was wrong for the baseline. The baseline's own header comment, :249-251, says the digest catches type and constraint changes; the code digests the full schema.) No field line, no default, no count (`field_definitions`, `canonical_dump_leaves`) and no `canonical_dump_sha256` changes: the canonical dump is `SystemConfig()`'s values (:1058-1059, :1083), not its schema.
- No `config-profiles.yaml` change (no field added).

**Shared trackers.** Another orchestrator merges into `PROGRESS.md`, `DECISIONS.md` and the ledger pair. At build time, anchor P33 on whatever `# ProbOS Progress` heading is there, and P34 on the newest `### ` heading of `DECISIONS.md` (read it with `rg -n "^### " DECISIONS.md | head -3`); regenerate the ledger after the merge rather than resolving it by hand.

## 5. Builder: may and may not

- **May:** apply the pairs in order; write the new files; run the four generators of 4a and of 4b and `gen_ad_ledger.py`; run `git diff --check` and `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file, add `skip` or a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

**Batch 1 applies:** 6.1 (new file), P1-P7, P35, P36, P38 (6.2), P8-P10, P39, P40 (6.3), P11, P12 (6.4), 6.5 (new file); 6.6 (new file), P13 (6.7), P14 (6.8), P15 (6.9), P16 (6.10), P17 (6.11), P18 (6.12), 6.13 (new file); P33 (6.21), P34 (6.22). **Batch 2 (deferred; not applied in batch 1):** 6.14-6.20a (P19, P20, P23-P28, the new file 6.20, P37); 6.16 and 6.19 are empty (removed in the S1 repair). Headings and labels are unchanged so batch 2 can apply them as written, after the R2-F1 pairs of section 13 are added.

### 6.1 New file `src/probos/utils/loop_yield.py`

New file:

```python
"""BF-932 (#1670): give the event loop a turn every N units of synchronous work.

A coroutine that loops over synchronous work (file reads, pair comparisons, store calls) without an ``await`` holds
the event loop for the whole loop. ``LoopYield.due()`` counts units; on every ``every``-th unit it returns True and
the caller awaits ``asyncio.sleep(0)``, which lets each ready callback run once. The budget is a count of units, not
a time, and the work and its order are unchanged.
"""

from __future__ import annotations


class LoopYield:
    """Counts units of synchronous work; ``due()`` is True on every ``every``-th unit."""

    __slots__ = ("_count", "_every")

    def __init__(self, every: int) -> None:
        if every < 1:
            raise ValueError("every must be at least 1")
        self._every = every
        self._count = 0

    def due(self) -> bool:
        """Count one unit; True when the caller should ``await asyncio.sleep(0)`` now."""
        self._count += 1
        if self._count >= self._every:
            self._count = 0
            return True
        return False
```

### 6.2 `src/probos/cognitive/dreaming.py`

**P1.** SEARCH:
```python
    episode_ran_in_plan_mode,
)

if TYPE_CHECKING:
```
REPLACE:
```python
    episode_ran_in_plan_mode,
)
from probos.utils.loop_yield import LoopYield  # BF-932

if TYPE_CHECKING:
```

**P2.** SEARCH:
```python
logger = logging.getLogger(__name__)


def _outcome_evidence(episodes: list[Any]) -> list[Any]:
```
REPLACE:
```python
logger = logging.getLogger(__name__)

# BF-932 (#1670): Step 7g gives the event loop a turn every this many notebook reads or word sets, and every this many
# pair iterations. Counts, not times: the loop-stall sampler (probos.utils.loop_stall) shows what a turn costs.
_STEP_7G_READS_PER_YIELD = 16
_STEP_7G_PAIRS_PER_YIELD = 2000


async def _reads_as_loaded(records_store: Any, item: dict) -> bool:
    """BF-932 (#1670): True when a note Step 7g loaded still has the bytes it had then (its fingerprint is unchanged).

    Step 7g gives the event loop turns between its reads and its writes, so a note can be revised meanwhile; any write
    changes the file's bytes. ``item["_fp"]`` is the fingerprint the step took just before it read the note.
    ``RecordsStore.entry_fingerprint`` has no await, so a caller that writes or renames right after this check gives
    the loop no turn between the check and that write. A fingerprint that cannot be taken counts as changed; nothing
    raised here reaches the caller.
    """
    try:
        fp = await records_store.entry_fingerprint(item["path"])
        return fp is not None and fp == item["_fp"]
    except Exception:
        logger.debug("Step 7g: could not fingerprint %s", item["path"], exc_info=True)
        return False


def _outcome_evidence(episodes: list[Any]) -> list[Any]:
```

**P3.** SEARCH:
```python
                threshold = self.config.notebook_consolidation_threshold
                min_entries = self.config.notebook_consolidation_min_entries

                for agent_cs, entries in agents_entries.items():
                    if len(entries) < min_entries:
                        continue
                    # Load content for each entry
                    loaded: list[dict] = []
                    for ent in entries:
                        try:
```
REPLACE:
```python
                threshold = self.config.notebook_consolidation_threshold
                min_entries = self.config.notebook_consolidation_min_entries
                # BF-932 (#1670): this step's reads and comparisons have no await of their own, so they gave the
                # event loop no turn for the whole step; these counters give it one every so many units.
                read_pacer = LoopYield(_STEP_7G_READS_PER_YIELD)
                pair_pacer = LoopYield(_STEP_7G_PAIRS_PER_YIELD)

                for agent_cs, entries in agents_entries.items():
                    if len(entries) < min_entries:
                        continue
                    # Load content for each entry
                    loaded: list[dict] = []
                    for ent in entries:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: read_entry reads and parses without an await
                        try:
```

**P4.** SEARCH:
```python
                    n = len(loaded)
                    adj: dict[int, set[int]] = {i: set() for i in range(n)}
                    for i in range(n):
                        words_i = text_to_words(loaded[i]["_content"])
                        for j in range(i + 1, n):
                            words_j = text_to_words(loaded[j]["_content"])
                            sim = jaccard_similarity(words_i, words_j)
```
REPLACE:
```python
                    n = len(loaded)
                    adj: dict[int, set[int]] = {i: set() for i in range(n)}
                    # BF-932: each note's word set once (text_to_words is pure), not once per pair
                    entry_words: list[set[str]] = []
                    for item in loaded:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: give the event loop a turn
                        entry_words.append(text_to_words(item["_content"]))
                    for i in range(n):
                        words_i = entry_words[i]
                        for j in range(i + 1, n):
                            if pair_pacer.due():
                                await asyncio.sleep(0)  # BF-932: give the event loop a turn
                            words_j = entry_words[j]
                            sim = jaccard_similarity(words_i, words_j)
```

**P5.** SEARCH:
```python
                    # Load content for cross-agent comparison
                    cross_loaded: list[dict] = []
                    for ent in agent_dept_entries:
                        try:
```
REPLACE:
```python
                    # Load content for cross-agent comparison
                    cross_loaded: list[dict] = []
                    for ent in agent_dept_entries:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: read_entry reads and parses without an await
                        try:
```

**P6.** SEARCH:
```python
                    n_cross = len(cross_loaded)
                    cross_adj: dict[int, set[int]] = {i: set() for i in range(n_cross)}
                    for i in range(n_cross):
                        words_i = text_to_words(cross_loaded[i]["_content"])
                        for j in range(i + 1, n_cross):
                            if cross_loaded[i]["agent"] == cross_loaded[j]["agent"]:
                                continue  # skip same-agent pairs
                            words_j = text_to_words(cross_loaded[j]["_content"])
                            sim = jaccard_similarity(words_i, words_j)
```
REPLACE:
```python
                    n_cross = len(cross_loaded)
                    cross_adj: dict[int, set[int]] = {i: set() for i in range(n_cross)}
                    # BF-932: each note's word set once (text_to_words is pure), not once per pair
                    cross_words: list[set[str]] = []
                    for item in cross_loaded:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: give the event loop a turn
                        cross_words.append(text_to_words(item["_content"]))
                    for i in range(n_cross):
                        words_i = cross_words[i]
                        for j in range(i + 1, n_cross):
                            if pair_pacer.due():
                                await asyncio.sleep(0)  # BF-932: give the event loop a turn
                            if cross_loaded[i]["agent"] == cross_loaded[j]["agent"]:
                                continue  # skip same-agent pairs
                            words_j = cross_words[j]
                            sim = jaccard_similarity(words_i, words_j)
```

**P7.** SEARCH:
```python
                            for ci in range(len(component)):
                                wi = text_to_words(cluster_entries[ci]["_content"])
                                for cj in range(ci + 1, len(component)):
                                    wj = text_to_words(cluster_entries[cj]["_content"])
                                    total_sim += jaccard_similarity(wi, wj)
                                    pairs += 1
```
REPLACE:
```python
                            # BF-932: the word sets built above, in the component's order; the sum's order is unchanged
                            member_words = [cross_words[idx] for idx in component]
                            for ci in range(len(component)):
                                wi = member_words[ci]
                                for cj in range(ci + 1, len(component)):
                                    if pair_pacer.due():
                                        await asyncio.sleep(0)  # BF-932: give the event loop a turn
                                    wj = member_words[cj]
                                    total_sim += jaccard_similarity(wi, wj)
                                    pairs += 1
```

`asyncio` is imported at `dreaming.py`:10. `cluster_entries[ci]` is `cross_loaded[component[ci]]` (:1103), so `member_words[ci]` is `text_to_words(cluster_entries[ci]["_content"])`.

**P35.** (applied after P7; its SEARCH, base :1007-1012, is untouched by P3-P7) SEARCH:
```python
                        consolidated = primary_content
                        if unique_observations:
                            consolidated += "\n\n## Consolidated Observations\n\n"
                            consolidated += "\n\n---\n\n".join(unique_observations)
                        # Write consolidated entry
                        await self._records_store.write_entry(
```
REPLACE:
```python
                        consolidated = primary_content
                        if unique_observations:
                            consolidated += "\n\n## Consolidated Observations\n\n"
                            consolidated += "\n\n---\n\n".join(unique_observations)
                        # BF-932 (#1670): publish only when every member still reads as this step loaded it. The turns
                        # above let a revision land after a read; the write below would overwrite it (the primary) or
                        # archive it unmerged (the others). Nothing between this check and write_entry's file write
                        # awaits, so no writer runs between them. A stale cluster waits for the next dream.
                        stale = [
                            item["path"] for item in cluster_items
                            if not await _reads_as_loaded(self._records_store, item)
                        ]
                        if stale:
                            logger.info(
                                "Step 7g: skipped a cluster of %d notes of agent %s; changed after the read: %s",
                                len(cluster_items), agent_cs, ", ".join(stale),
                            )
                            continue
                        # Write consolidated entry
                        await self._records_store.write_entry(
```

**P36.** (applied after P35; base :1018-1021) SEARCH:
```python
                        # Archive non-primary entries
                        for other in others:
                            try:
                                old_path = self._records_store._safe_path(other["path"])
```
REPLACE:
```python
                        # Archive non-primary entries
                        for other in others:
                            # BF-932 (#1670): the primary's write and each rename below await git (and the indexer), so a
                            # member can be revised after the check above. A member that no longer reads as loaded stays
                            # live, so its revision is not archived unmerged; nothing between this check and the rename
                            # awaits.
                            if not await _reads_as_loaded(self._records_store, other):
                                logger.info("Step 7g: left %s live; it changed after the read", other["path"])
                                continue
                            try:
                                old_path = self._records_store._safe_path(other["path"])
```

**P38.** (applied after P36; its SEARCH, base :951-955, follows P3's `try:` and is untouched by P3-P7, P35 and P36. Its first four lines also occur at base :1067-1070, the cross-agent read; the fifth line makes the block occur once) SEARCH:
```python
                            doc = await self._records_store.read_entry(
                                ent["path"], reader_id="system",
                            )
                            if doc:
                                loaded.append({**ent, "_content": doc.get("content", ""), "_doc": doc})
```
REPLACE:
```python
                            # BF-932 (#1670): the file's fingerprint before the read, so a write that lands after it
                            # reads as changed at the publication checks below; nothing suspends between the two.
                            fp = await self._records_store.entry_fingerprint(ent["path"])
                            doc = await self._records_store.read_entry(
                                ent["path"], reader_id="system",
                            )
                            if doc and fp is not None:
                                loaded.append({**ent, "_content": doc.get("content", ""), "_doc": doc, "_fp": fp})
```

`continue` in P35 continues `for cluster_indices in clusters:` (base :991); in P36 it continues `for other in others:` (:1019). `notebook_consolidations += 1` (:1033) stays after the archive loop, so a published cluster counts once whatever its members' archive checks say, and a skipped cluster counts nothing. `_reads_as_loaded` is P2's helper; `item["_fp"]` is the fingerprint P38 records for each note the per-agent pass keeps. P38 sits inside the existing `try` / `except Exception: pass` of the per-agent read (:950, :956-957): a fingerprint that raises drops the note from this dream, as a read that raises does at the base; `fp` is `None` only for a missing file, for which `read_entry` returns `None` too (:1501-1502), so the `fp is not None` guard drops nothing the base kept. The cross-agent read (:1067-1073) is not changed: that pass overwrites and archives no note (its one write is a new convergence report, :1145).

### 6.3 `src/probos/knowledge/records_store.py`

**P8.** SEARCH:
```python
from probos.utils.frontmatter import dump_frontmatter, load_frontmatter, split_frontmatter
```
REPLACE:
```python
from probos.utils.frontmatter import dump_frontmatter, load_frontmatter, split_frontmatter
from probos.utils.loop_yield import LoopYield  # BF-932
```

**P9.** SEARCH:
```python
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
```
REPLACE:
```python
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader

# BF-932 (#1670): a default-mode listing gives the event loop a turn every this many files (a count, not a time).
_LIST_FILES_PER_YIELD = 16
```

**P10.** SEARCH:
```python
        found = _markdown_files(search_path, strict=strict)

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
```
REPLACE:
```python
        found = _markdown_files(search_path, strict=strict)
        # BF-932 (#1670): each file is read and parsed without an await, so a large directory held the event loop for
        # the whole listing. The default mode gives the loop a turn every _LIST_FILES_PER_YIELD files; the strict mode
        # (the stand-down's and the archive promotion's reads) keeps its one uninterrupted pass.
        pacer = None if strict else LoopYield(_LIST_FILES_PER_YIELD)

        for md_file in sorted(found):
            if pacer is not None and pacer.due():
                await asyncio.sleep(0)
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
```

`asyncio` is imported at `records_store.py`:3.

**P39.** SEARCH:
```python
import asyncio
import fnmatch
import logging
```
REPLACE:
```python
import asyncio
import fnmatch
import hashlib
import logging
```

**P40.** (applied after P39; its SEARCH, base :1526-1528, is untouched by P8-P10, whose SEARCHes each still occur once) SEARCH:
```python
        return {"frontmatter": frontmatter, "content": content, "path": path}

    async def list_entries(
```
REPLACE:
```python
        return {"frontmatter": frontmatter, "content": content, "path": path}

    async def entry_fingerprint(self, path: str) -> str | None:
        """BF-932 (#1670): the sha256 hex digest of a record file's bytes, or None when the file does not exist.

        Dream Step 7g takes it just before it reads a note and again just before it writes or archives that note, and
        acts only when the two are equal: any write, rename or deletion between them changes the result. No
        classification gate: the digest tells a caller only whether the bytes equal those of an earlier digest, and
        Step 7g keeps one only for a note that passed ``read_entry``'s gate. No await (as in ``read_entry``), so a
        caller that writes right after it gives the event loop no turn between the check and the write. Raises what
        ``_safe_path`` and the file read raise.
        """
        file_path = self._safe_path(path)
        if not file_path.exists():
            return None
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    async def list_entries(
```

### 6.4 `src/probos/cognitive/episodic.py`

**P11.** SEARCH:
```python
from probos.types import EBBINGHAUS_DEFAULT_STABILITY_SECONDS

logger = logging.getLogger(__name__)
```
REPLACE:
```python
from probos.types import EBBINGHAUS_DEFAULT_STABILITY_SECONDS
from probos.utils.loop_yield import LoopYield  # BF-932

logger = logging.getLogger(__name__)

# BF-932 (#1670): the AD-873 decay sweep gives the event loop a turn every this many episodes (a count, not a time).
_DECAY_EPISODES_PER_YIELD = 8
```

**P12.** SEARCH:
```python
        now = time.time()
        for i, ep_id in enumerate(ids):
            try:
                meta = metas[i] if i < len(metas) else {}
                ep = self._metadata_to_episode(ep_id, "", meta or {})
```
REPLACE:
```python
        now = time.time()
        # BF-932 (#1670): each episode is a synchronous Chroma read and write, so the page held the event loop for the
        # whole sweep; give the loop a turn every _DECAY_EPISODES_PER_YIELD episodes.
        pacer = LoopYield(_DECAY_EPISODES_PER_YIELD)
        for i, ep_id in enumerate(ids):
            if pacer.due():
                await asyncio.sleep(0)
            try:
                meta = metas[i] if i < len(metas) else {}
                ep = self._metadata_to_episode(ep_id, "", meta or {})
```

`asyncio` is imported at `episodic.py`:10. `for i, ep_id in enumerate(ids):` also occurs at :929; the SEARCH starts at `now = time.time()`, which makes it unique.

### 6.5 New file `tests/test_bf932_d1_dream_yields.py`

New file:

```python
"""BF-932 (#1670) D1: the dream cycle's synchronous loops give the event loop a turn, and Step 7g publishes no stale note.

A ticker task counts the turns the event loop gives other tasks. A recorder notes the ticker's count at each unit of
one loop (a pair comparison, a word set, a notebook read, a parsed file, an episode written). The difference between
the first and the last unit of that loop is how many turns the loop gave; at the base each of these loops gave none.
The step's output is compared on a fixed fixture. Over a real RecordsStore, a note revised at any turn Step 7g gives,
or right after the step's read of it, keeps its revision; an unchanged note is consolidated as at the base whatever
its frontmatter loads to; a write, a publish, a rename away and a deletion each read as changed; and a check that
raises skips its own cluster only. No assertion bounds a duration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import dreaming
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.knowledge import records_store as records_module
from probos.knowledge.records_store import RecordsStore
from tests.test_ad551_notebook_consolidation import _entry, _make_engine, _make_records_store, _read_result

# The contract's budgets, written out: a test that read them from the module could not catch a changed budget.
_PAIRS_PER_TURN = 2000
_READS_PER_TURN = 16
_LIST_FILES_PER_TURN = 16
_DECAY_EPISODES_PER_TURN = 8

_ALPHA, _BETA, _GAMMA = 100, 20, 20
# Each agent's convergent notes: 64 in all, so the convergence's coherence makes 64 * 63 / 2 = 2,016 comparisons, more
# than one pair budget.
_CONVERGENT = {"alpha": range(2, 32), "beta": range(0, 17), "gamma": range(0, 17)}
_SHARED = "reactor coolant pressure trending nominal"  # 5 words
_DUPLICATE = "duplicate finding about the warp core alignment log"


class _Ticker:
    """Counts the event loop's turns for other tasks: one per iteration, each ending in ``sleep(0)``."""

    def __init__(self) -> None:
        self.turns = 0
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        while True:
            self.turns += 1
            await asyncio.sleep(0)

    async def __aenter__(self) -> "_Ticker":
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._task is not None
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


def _fixture() -> tuple[list[dict], dict[str, dict]]:
    """Three agents in two departments. Alpha's notes 0 and 1 form one per-agent cluster. Each convergent note is the
    5 shared words and 2 of its own, so any two share 5 of 9 words (0.556): under the per-agent threshold (0.6), over
    the convergence threshold (0.5). They form one convergence of 64 notes; every other note is unique."""
    entries: list[dict] = []
    read_map: dict[str, dict] = {}
    plan = (("alpha", "science", _ALPHA), ("beta", "medical", _BETA), ("gamma", "science", _GAMMA))
    for agent, dept, count in plan:
        for k in range(count):
            path = f"notebooks/{agent}/note-{k:03d}.md"
            if agent == "alpha" and k in (0, 1):
                content = _DUPLICATE
            elif k in _CONVERGENT[agent]:
                content = f"{_SHARED} {agent}-{k}-x {agent}-{k}-y"
            else:
                content = " ".join(f"{agent}-{k}-w{m}" for m in range(12))
            entries.append(_entry(path, author=agent, dept=dept, updated=f"2026-04-01T{k % 24:02d}:00:00"))
            read_map[path] = _read_result(path, content)
    return entries, read_map


async def _run_dream(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """One dream cycle over the fixture, with the ticker's count noted at each comparison, word set and read."""
    entries, read_map = _fixture()
    store = _make_records_store(entries, read_map)
    engine = _make_engine(records_store=store)
    events: list[tuple[str, dict]] = []
    engine._emit_event_fn = lambda event_type, data: events.append((event_type, data))
    pair_turns: list[int] = []
    word_turns: list[int] = []
    read_turns: list[int] = []
    reader = store.read_entry.side_effect
    async with _Ticker() as ticker:

        def _pair(a: set[str], b: set[str]) -> float:
            pair_turns.append(ticker.turns)
            return jaccard_similarity(a, b)

        def _words(text: str) -> set[str]:
            word_turns.append(ticker.turns)
            return text_to_words(text)

        async def _read(path: str, reader_id: str = "system", **kwargs: Any) -> Any:
            read_turns.append(ticker.turns)
            return await reader(path, reader_id=reader_id, **kwargs)

        monkeypatch.setattr(dreaming, "jaccard_similarity", _pair)
        monkeypatch.setattr(dreaming, "text_to_words", _words)
        store.read_entry.side_effect = _read
        report = await engine.dream_cycle()
    return {
        "report": report, "store": store, "events": events,
        "pairs": pair_turns, "words": word_turns, "reads": read_turns,
    }


@pytest.mark.asyncio
async def test_d1_step_7g_gives_the_loop_turns_inside_each_of_its_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _run_dream(monkeypatch)
    pairs, words, reads = seen["pairs"], seen["words"], seen["reads"]
    notes = _ALPHA + _BETA + _GAMMA
    alpha_pairs = _ALPHA * (_ALPHA - 1) // 2  # alpha is listed first, so its pass makes the first comparisons
    cross_pairs = _ALPHA * _BETA + _ALPHA * _GAMMA + _BETA * _GAMMA  # different-agent pairs; the coherence pairs follow
    convergent = sum(len(ks) for ks in _CONVERGENT.values())
    coherence_pairs = convergent * (convergent - 1) // 2  # 2,016: more than one pair budget
    per_agent_pairs = alpha_pairs + _BETA * (_BETA - 1) // 2 + _GAMMA * (_GAMMA - 1) // 2
    assert len(pairs) == per_agent_pairs + cross_pairs + coherence_pairs
    assert pairs[alpha_pairs - 1] - pairs[0] >= alpha_pairs // _PAIRS_PER_TURN
    assert pairs[-(coherence_pairs + 1)] - pairs[-(cross_pairs + coherence_pairs)] >= cross_pairs // _PAIRS_PER_TURN
    assert pairs[-1] - pairs[-coherence_pairs] >= coherence_pairs // _PAIRS_PER_TURN  # the coherence pass's own turn
    assert reads[_ALPHA - 1] - reads[0] >= _ALPHA // _READS_PER_TURN  # alpha's reads, before its comparisons
    # The cross-agent pass reads every note again, last. Counted from the end, so the count holds whatever else
    # reads a note before that pass (the publication checks fingerprint the files and do not call read_entry).
    assert reads[-1] - reads[-notes] >= notes // _READS_PER_TURN
    assert words[2 * notes - 1] - words[notes] >= notes // _READS_PER_TURN  # the cross-agent pass's word sets
    assert words[_ALPHA - 1] - words[0] >= _ALPHA // _READS_PER_TURN  # alpha's per-agent word sets


@pytest.mark.asyncio
async def test_d1_step_7g_output_is_the_bases_on_a_fixed_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: passes on the base too. One per-agent cluster, one convergence of 64 notes, the base's coherence to the bit."""
    seen = await _run_dream(monkeypatch)
    report, store, events = seen["report"], seen["store"], seen["events"]
    consolidated = [
        (call.kwargs["path"], call.kwargs["message"])
        for call in store.write_entry.call_args_list
        if str(call.kwargs.get("message", "")).startswith("AD-551: Consolidated")
    ]
    assert consolidated == [("notebooks/alpha/note-001.md", "AD-551: Consolidated 2 entries")]
    assert report.notebook_consolidations == 1
    convergences = [data for event_type, data in events if event_type == "convergence_detected"]
    assert report.convergence_reports_generated == 1 and len(convergences) == 1
    assert convergences[0]["agents"] == ["alpha", "beta", "gamma"]
    assert convergences[0]["departments"] == ["medical", "science"]
    coherence_pairs = 64 * 63 // 2
    total = 0.0
    for _ in range(coherence_pairs):
        total += 5 / 9  # each pair shares 5 of 9 distinct words; the sum runs in the base's order
    assert convergences[0]["coherence"] == total / coherence_pairs


def _notes(root: Path, count: int) -> list[str]:
    folder = root / "notebooks" / "ezri"
    folder.mkdir(parents=True)
    paths: list[str] = []
    for k in range(count):
        (folder / f"note-{k:03d}.md").write_text(f"---\nauthor: ezri\ntopic: t{k}\n---\nbody {k}\n", encoding="utf-8")
        paths.append(f"notebooks/ezri/note-{k:03d}.md")
    return paths


async def _listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, strict: bool) -> tuple[list[str], list[dict], list[int]]:
    """A real RecordsStore over 40 notes; the ticker's count noted at each file the listing parses."""
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path / "records")))
    expected = _notes(tmp_path / "records", 40)
    turns: list[int] = []
    parse = records_module._load_document
    async with _Ticker() as ticker:

        def _parse(raw: str) -> Any:
            turns.append(ticker.turns)
            return parse(raw)

        monkeypatch.setattr(records_module, "_load_document", _parse)
        listed = await store.list_entries("notebooks", strict=strict)
    return expected, listed, turns


@pytest.mark.asyncio
async def test_d1_a_default_listing_gives_the_loop_turns_and_lists_every_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected, listed, turns = await _listing(tmp_path, monkeypatch, strict=False)
    assert [entry["path"] for entry in listed] == expected
    assert len(turns) == 40
    assert turns[-1] - turns[0] >= 40 // _LIST_FILES_PER_TURN


@pytest.mark.asyncio
async def test_d1_a_strict_listing_keeps_its_one_uninterrupted_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: passes on the base too. The stand-down's and the archive promotion's listing is one pass."""
    expected, listed, turns = await _listing(tmp_path, monkeypatch, strict=True)
    assert [entry["path"] for entry in listed] == expected
    assert len(turns) == 40
    assert turns[-1] - turns[0] == 0


class _Collection:
    """Stands in for chromadb's Collection: the page read, the read by id and the update the AD-873 sweep makes."""

    def __init__(self, count: int, turns: Any) -> None:
        self.ids = [f"ep-{k:03d}" for k in range(count)]
        self._metadata = {episode_id: {"timestamp": 1000.0} for episode_id in self.ids}
        self._turns = turns
        self.updates: list[tuple[str, int]] = []

    def get(self, ids: list[str] | None = None, include: Any = None, limit: Any = None, offset: Any = None) -> dict:
        wanted = list(self.ids) if ids is None else list(ids)
        return {"ids": wanted, "metadatas": [dict(self._metadata[episode_id]) for episode_id in wanted]}

    def update(self, ids: list[str], metadatas: list[dict]) -> None:
        self.updates.append((ids[0], self._turns()))
        self._metadata[ids[0]] = metadatas[0]


@pytest.mark.asyncio
async def test_d1_the_decay_sweep_gives_the_loop_turns_and_writes_every_episode(tmp_path: Path) -> None:
    memory = EpisodicMemory(db_path=tmp_path / "episodic")
    async with _Ticker() as ticker:
        collection = _Collection(40, lambda: ticker.turns)
        memory._collection = collection
        counts = await memory.sweep_episode_decay(None)
    assert counts == {"swept": 40, "reinforced": 0}
    assert [episode_id for episode_id, _turn in collection.updates] == collection.ids
    turns = [turn for _episode_id, turn in collection.updates]
    assert turns[-1] - turns[0] >= 40 // _DECAY_EPISODES_PER_TURN


def test_d1_loop_yield_is_due_on_every_nth_unit_only() -> None:
    from probos.utils.loop_yield import LoopYield  # here, so the base's missing module fails this test alone

    pacer = LoopYield(3)
    assert [pacer.due() for _ in range(7)] == [False, False, True, False, False, True, False]
    with pytest.raises(ValueError):
        LoopYield(0)


_SEED = "trust score is stable at nominal levels for all agents in the medical department"  # 14 words
_REVISION = "captain-correction-after-the-read"
_PRIMARY = "notebooks/alpha/n-2.md"  # the newest of the three, so the cluster's primary
_MEMBER = "notebooks/alpha/n-0.md"  # read first and archived last
_OTHER = "warp field geometry holds steady across every deck during a long patrol tonight"  # 13 words, none of _SEED's
# Frontmatter that the safe loader accepts and that a comparison of loaded documents mishandles. Step 7g compares file
# bytes, so a note holding any of them consolidates as at the base. "loop": a mapping that contains itself (an anchor
# and its alias; == between two loads raises RecursionError). "bigint": an integer of 16,384 bits (its decimal repr
# passes CPython's 4,300-digit limit and raises ValueError). "nanset": a set of explicitly tagged NaNs (each load makes
# new NaNs, so the set's order, and its repr, can differ between loads of the same bytes). "mixed": an ordered map
# (a list of tuples), a date, bytes, and a key 1 beside a key true (equal keys of different types).
_LOOP_FRONTMATTER = "loop: &loop\n  self: *loop\n"
_BIG_INT_FRONTMATTER = "big: 0x" + "f" * 4096 + "\n"
_NAN_SET_FRONTMATTER = "nans: !!set\n" + "  ? !!float nan\n" * 8
_MIXED_FRONTMATTER = (
    "mixed:\n  pairs: !!omap\n    - a: 1\n    - b: 2\n  day: 2026-04-01\n  blob: !!binary aGVsbG8=\n"
    "  keys: {1: one, true: two}\n"
)
_ODD_FRONTMATTER = {
    "loop": _LOOP_FRONTMATTER,
    "bigint": _BIG_INT_FRONTMATTER,
    "nanset": _NAN_SET_FRONTMATTER,
    "mixed": _MIXED_FRONTMATTER,
}
_CONSOLIDATED_ALPHA = (
    f"{_SEED} reading 2\n\n## Consolidated Observations\n\n"
    f"{_SEED} reading 1\n\n---\n\n{_SEED} reading 0"
)


class _StepTurns:
    """Stands in for the dreaming module's ``asyncio``: each ``sleep`` there is one of Step 7g's turns."""

    def __init__(self, on_turn: Any) -> None:
        self._on_turn = on_turn

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def sleep(self, delay: float, result: Any = None) -> Any:
        await self._on_turn()
        return await asyncio.sleep(delay, result)


def _seed_notes(
    root: Path, agent: str = "alpha", text: str = _SEED, extra_in: int | None = None, odd: str = _LOOP_FRONTMATTER,
) -> None:
    """Three similar notes of one agent; note ``n-<extra_in>``'s frontmatter also holds ``odd``."""
    folder = root / "notebooks" / agent
    folder.mkdir(parents=True)
    for k in range(3):
        stamp = f"2026-04-01T0{k}:00:00"
        extra = odd if k == extra_in else ""
        front = f"---\nauthor: {agent}\nclassification: ship\ncreated: '{stamp}'\nupdated: '{stamp}'\n{extra}---\n\n"
        (folder / f"n-{k}.md").write_text(f"{front}{text} reading {k}", encoding="utf-8")


async def _consolidate_on_disk(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, target: str | None = None, at_turn: int = 0, seed: bool = True,
    extra_in: int | None = None,
) -> dict[str, Any]:
    """One dream over three similar notes of one agent in a real RecordsStore (auto_commit off, git stubbed).

    A turn is each ``sleep`` of Step 7g (both budgets set to 1, so each read, word set and pair gives one), the
    consolidation write's return (with auto_commit on, write_entry awaits git and the indexer after its file write)
    and each archive rename's ``git add -A``. At turn ``at_turn`` the target note is revised through the real
    ``write_entry``, as a writer task would be in that turn.
    """
    if seed:
        _seed_notes(root, extra_in=extra_in)
    store = RecordsStore(SimpleNamespace(repo_path=str(root), auto_commit=False))
    write = store.write_entry
    state: dict[str, Any] = {"turns": 0, "landed": False}

    async def on_turn() -> None:
        state["turns"] += 1
        if target is not None and state["turns"] == at_turn:
            await write(author="alpha", path=target, content=f"{_SEED} {_REVISION}", message="revision")
            state["landed"] = True

    async def written(*args: Any, **kwargs: Any) -> str:
        path = await write(*args, **kwargs)
        if str(kwargs.get("message", "")).startswith("AD-551: Consolidated"):
            await on_turn()
        return path

    async def git(*args: str) -> str:
        if args[:2] == ("add", "-A"):
            await on_turn()
        return ""

    store.write_entry = written  # type: ignore[method-assign]
    store._git = git  # type: ignore[method-assign]
    monkeypatch.setattr(dreaming, "_STEP_7G_READS_PER_YIELD", 1, raising=False)  # absent at the base: no turn there
    monkeypatch.setattr(dreaming, "_STEP_7G_PAIRS_PER_YIELD", 1, raising=False)
    monkeypatch.setattr(dreaming, "asyncio", _StepTurns(on_turn))
    report = await _make_engine(records_store=store).dream_cycle()
    folder = root / "notebooks" / "alpha"
    live: dict[str, Any] = {}
    for note in sorted(folder.glob("*.md")):
        doc = await store.read_entry(f"notebooks/alpha/{note.name}", reader_id="captain")
        live[note.name] = doc["content"] if doc else None
    archived = sorted(note.name for note in (folder / "_archived").glob("*.md"))
    return {"report": report, "turns": state["turns"], "landed": state["landed"], "live": live, "archived": archived}


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [_PRIMARY, _MEMBER], ids=["primary", "member"])
async def test_d1_a_note_revised_at_any_turn_of_step_7g_keeps_its_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    """At each turn the step gives, one run revises the target; afterwards a live note holds the revision."""
    total = (await _consolidate_on_disk(tmp_path / "count", monkeypatch))["turns"]
    lost: list[int] = []
    for turn in range(1, total + 1):
        seen = await _consolidate_on_disk(tmp_path / f"turn-{turn}", monkeypatch, target=target, at_turn=turn)
        assert seen["landed"]
        if not any(text and _REVISION in text for text in seen["live"].values()):
            lost.append(turn)
    assert lost == []


@pytest.mark.asyncio
async def test_d1_a_cluster_skipped_as_stale_is_consolidated_by_the_next_dream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Turn 9 is the step's last before its write: 3 reads, 3 word sets, then the third pair's turn.
    first = await _consolidate_on_disk(tmp_path, monkeypatch, target=_PRIMARY, at_turn=9)
    assert first["landed"]
    assert first["report"].notebook_consolidations == 0
    assert first["archived"] == [] and sorted(first["live"]) == ["n-0.md", "n-1.md", "n-2.md"]
    second = await _consolidate_on_disk(tmp_path, monkeypatch, seed=False)
    assert second["report"].notebook_consolidations == 1
    assert second["archived"] == ["n-0.md", "n-1.md"] and list(second["live"]) == ["n-2.md"]
    assert second["live"]["n-2.md"].startswith(f"{_SEED} {_REVISION}\n\n## Consolidated Observations\n\n")


@pytest.mark.asyncio
async def test_d1_step_7g_on_disk_with_no_concurrent_writer_writes_what_the_base_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: passes on the base too. The primary keeps its body, then the others' bodies, newest first."""
    seen = await _consolidate_on_disk(tmp_path, monkeypatch)
    assert seen["report"].notebook_consolidations == 1
    assert seen["archived"] == ["n-0.md", "n-1.md"]
    assert seen["live"] == {"n-2.md": _CONSOLIDATED_ALPHA}


@pytest.mark.asyncio
@pytest.mark.parametrize("odd", list(_ODD_FRONTMATTER))
async def test_d1_an_unchanged_note_is_consolidated_as_at_the_base_whatever_its_frontmatter_loads_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, odd: str,
) -> None:
    """Control: passes on the base too. Two clusters and no writer: alpha's, whose oldest member's frontmatter also
    holds ``_ODD_FRONTMATTER[odd]``, and beta's, ordinary. Both consolidate; no check skips alpha's."""
    _seed_notes(tmp_path, extra_in=0, odd=_ODD_FRONTMATTER[odd])
    _seed_notes(tmp_path, agent="beta", text=_OTHER)
    seen = await _consolidate_on_disk(tmp_path, monkeypatch, seed=False)
    assert seen["report"].notebook_consolidations == 2
    assert seen["report"].notebook_entries_archived == 4
    assert seen["archived"] == ["n-0.md", "n-1.md"]
    assert seen["live"] == {"n-2.md": _CONSOLIDATED_ALPHA}
    beta = tmp_path / "notebooks" / "beta"
    assert sorted(note.name for note in (beta / "_archived").glob("*.md")) == ["n-0.md", "n-1.md"]
    assert sorted(note.name for note in beta.glob("*.md")) == ["n-2.md"]


@pytest.mark.asyncio
async def test_d1_a_note_whose_frontmatter_contains_itself_keeps_a_revision_made_at_any_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The member whose frontmatter contains itself: with no writer the cluster consolidates; at each turn the step
    gives, one run revises that member, and afterwards a live note holds the revision."""
    counted = await _consolidate_on_disk(tmp_path / "count", monkeypatch, extra_in=0)
    assert counted["report"].notebook_consolidations == 1 and counted["archived"] == ["n-0.md", "n-1.md"]
    lost: list[int] = []
    for turn in range(1, counted["turns"] + 1):
        seen = await _consolidate_on_disk(
            tmp_path / f"turn-{turn}", monkeypatch, target=_MEMBER, at_turn=turn, extra_in=0,
        )
        assert seen["landed"]
        if not any(text and _REVISION in text for text in seen["live"].values()):
            lost.append(turn)
    assert lost == []


@pytest.mark.asyncio
async def test_d1_an_unchanged_set_of_nans_reads_as_loaded_on_every_check(tmp_path: Path) -> None:
    """R3-F2: two loads of a set of tagged NaNs can order it differently; its file's bytes do not change."""
    _seed_notes(tmp_path, extra_in=0, odd=_NAN_SET_FRONTMATTER)
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path), auto_commit=False))
    item = {"path": _MEMBER, "_fp": await store.entry_fingerprint(_MEMBER)}
    assert item["_fp"] is not None
    checks = [await dreaming._reads_as_loaded(store, item) for _ in range(100)]
    assert checks == [True] * 100


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["write_entry", "publish", "rename", "delete"])
async def test_d1_a_note_reads_as_changed_after_a_write_a_publish_a_rename_or_a_deletion(
    tmp_path: Path, change: str,
) -> None:
    """Every way a note can change under Step 7g reads as changed; ``publish`` bumps ``updated`` but not ``revision``."""
    _seed_notes(tmp_path)
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path), auto_commit=False))
    item = {"path": _MEMBER, "_fp": await store.entry_fingerprint(_MEMBER)}
    assert await dreaming._reads_as_loaded(store, item)
    note = tmp_path / _MEMBER
    if change == "write_entry":
        await store.write_entry(author="alpha", path=_MEMBER, content=f"{_SEED} {_REVISION}", message="revision")
    elif change == "publish":
        await store.publish(_MEMBER, author="alpha")
    elif change == "rename":
        (note.parent / "_archived").mkdir()
        note.rename(note.parent / "_archived" / note.name)
    else:
        note.unlink()
    assert not await dreaming._reads_as_loaded(store, item)


@pytest.mark.asyncio
async def test_d1_the_fingerprint_is_taken_before_the_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A revision that lands right after the step's read of the primary reads as changed, because the fingerprint
    was taken before that read. With the fingerprint taken after the read, the publish overwrites the revision."""
    read = RecordsStore.read_entry
    state = {"landed": False}

    async def read_then_revise(self: RecordsStore, path: str, reader_id: str, reader_department: str = "") -> Any:
        doc = await read(self, path, reader_id, reader_department)
        if path == _PRIMARY and not state["landed"]:
            state["landed"] = True
            await RecordsStore.write_entry(
                self, author="alpha", path=_PRIMARY, content=f"{_SEED} {_REVISION}", message="revision",
            )
        return doc

    monkeypatch.setattr(RecordsStore, "read_entry", read_then_revise)
    seen = await _consolidate_on_disk(tmp_path, monkeypatch)
    assert state["landed"]
    assert seen["report"].notebook_consolidations == 0
    assert seen["archived"] == []
    assert seen["live"]["n-2.md"] == f"{_SEED} {_REVISION}"


@pytest.mark.asyncio
async def test_d1_a_check_that_raises_skips_its_own_cluster_and_the_step_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """R3-F3: the primary loads, then its publication check raises. The raise counts as changed inside the helper:
    alpha's cluster is skipped with every note live, beta's (listed after alpha's) still consolidates, and nothing
    reaches Step 7g's whole-step handler."""
    _seed_notes(tmp_path)
    _seed_notes(tmp_path, agent="beta", text=_OTHER)
    fingerprint = RecordsStore.entry_fingerprint
    calls: dict[str, int] = {}

    async def fails_at_the_check(self: RecordsStore, path: str) -> str | None:
        calls[path] = calls.get(path, 0) + 1
        if path == _PRIMARY and calls[path] > 1:
            raise OSError("the fingerprint read failed")
        return await fingerprint(self, path)

    monkeypatch.setattr(RecordsStore, "entry_fingerprint", fails_at_the_check)
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.dreaming")
    seen = await _consolidate_on_disk(tmp_path, monkeypatch, seed=False)
    assert calls[_PRIMARY] == 2  # the load's fingerprint, then the check that raised
    assert seen["report"].notebook_consolidations == 1
    assert seen["report"].notebook_entries_archived == 2
    assert seen["archived"] == [] and sorted(seen["live"]) == ["n-0.md", "n-1.md", "n-2.md"]
    beta = tmp_path / "notebooks" / "beta"
    assert sorted(note.name for note in (beta / "_archived").glob("*.md")) == ["n-0.md", "n-1.md"]
    assert not [r for r in caplog.records if "Step 7g notebook consolidation failed" in r.getMessage()]
```

### 6.6 New file `src/probos/utils/loop_stall.py`

New file:

```python
"""BF-932 (#1670): the loop-stall sampler names the code that holds the event loop (log-only).

A heartbeat coroutine on the event loop stamps a monotonic clock every quarter of the threshold. A daemon thread reads
the stamp at the same cadence. When the stamp is older than the threshold, the thread reads the loop thread's current
stack (``sys._current_frames``: the file, line and function of the innermost frames; no locals, no arguments, no
source lines) and logs one WARNING for that stall. The first heartbeat after that stall records the gap between its
stamp and the stalled one, and the thread logs that gap in one INFO: the gap of that one beat, so a late check cannot
make it larger. WARNING lines are bounded per window, and the next one written says how many were refused
(``suppressed=N``); a resume line is written only for a stall whose WARNING was written.

Shutdown: the thread checks the stop event, the loop and ``active`` at the start of every check and again between
reading the frames and writing the WARNING, so a WARNING whose frames were read after any of them said stop is not
written. The heartbeat's cancellation sets the stop event, before anything on that path can log, and joins the thread
for at most ``_JOIN_TIMEOUT_S``. The thread ends at once unless it is inside a logging call (a slow handler); it then
ends when that call returns and writes no further line. It is a daemon, so the interpreter does not wait for the
thread's own code at exit.

The sampler changes nothing the loop runs and adds no wait of its own to the loop thread except that bounded join. The
heartbeat and the thread share one lock, held only to read or write the stamps (no logging, no frame reading and no
wait under it). The thread's log calls use the same handlers as every other thread's: while it writes a line, a log
call from the loop thread that reaches the same handler, or ``logging.shutdown()`` at a normal interpreter exit, waits
for that handler's lock, as it would for any other thread's write. A failure in the thread is dropped at DEBUG with the
error's text only (Tier 1, swallow: a measurement is never a reason for the vessel to fail; a kept traceback would keep
the sampled frames alive). ProbOS requires Python 3.12 or later; CPython issue 106883 (a collection inside
``sys._current_frames`` deadlocked) was seen on 3.11.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import PurePath

logger = logging.getLogger(__name__)

THREAD_NAME = "probos-loop-stall-sampler"
_STACK_DEPTH = 12
_JOIN_TIMEOUT_S = 1.0


def _innermost_frames(thread_id: int, depth: int) -> str:
    """The innermost ``depth`` frames of ``thread_id`` as ``dir/file.py:line function``, innermost first."""
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return "(no frame)"
    try:
        summary = traceback.StackSummary.extract(traceback.walk_stack(frame), limit=depth, lookup_lines=False)
    finally:
        del frame  # on every path: the sampled frame holds the loop thread's locals
    return " <- ".join(
        f"{'/'.join(PurePath(entry.filename).parts[-2:])}:{entry.lineno} {entry.name}" for entry in summary
    )


def _drop(error: Exception) -> None:
    """Tier 1: a failed check is logged at DEBUG with its text only (a kept traceback keeps sampled frames)."""
    try:
        logger.debug("BF-932: a loop-stall check failed and was dropped: %s", repr(error))
    except Exception:
        pass


class _WarningBudget:
    """At most ``max_lines`` WARNING lines per ``window_s``; the next line written after a refusal ends ``suppressed=N``.

    The rule of ``probos.utils.step_timing.TimingLines``, which writes at INFO. It is not reused so that that module,
    which the voice path shares, stays unchanged. ``max_lines`` of 0 or less sets no bound.
    """

    def __init__(self, max_lines: int, window_s: float) -> None:
        self._max_lines = max_lines
        self._window_s = window_s
        self._written: deque[float] = deque()
        self._suppressed = 0

    def emit(self, message: str, *args: object) -> bool:
        """Write the WARNING unless this window's budget is spent; True when it was written."""
        if self._max_lines > 0:
            now = time.monotonic()
            while self._written and now - self._written[0] >= self._window_s:
                self._written.popleft()
            if len(self._written) >= self._max_lines:
                self._suppressed += 1
                return False
            self._written.append(now)
        if self._suppressed:
            message, args = message + " suppressed=%d", (*args, self._suppressed)
            self._suppressed = 0
        logger.warning(message, *args)
        return True


class LoopStallSampler:
    """One heartbeat on the event loop and one daemon thread that watches it (BF-932, #1670).

    ``active`` (optional) is read by the thread at the start of each check and again before each WARNING; once it
    returns False the thread ends. ``clock`` is the monotonic clock the heartbeat stamps and the thread reads.
    ``checks``, ``stall_count`` and ``resume_count`` count the thread's checks, the stalls it found (reported or not)
    and the stalls that ended.
    """

    def __init__(
        self,
        *,
        threshold_s: float,
        max_warnings: int = 10,
        window_s: float = 60.0,
        active: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 < threshold_s / 4.0 <= threading.TIMEOUT_MAX:
            raise ValueError("threshold_s must be finite and greater than 0")
        self._threshold_s = threshold_s
        self._tick_s = threshold_s / 4.0
        self._active = active
        self._clock = clock
        self._warnings = _WarningBudget(max_warnings, window_s)
        self._lock = threading.Lock()  # the three stamps below; held only to read or write them
        self._last_beat = clock()
        self._stalled_beat: float | None = None  # the stamp of the stall the thread found, until it ends
        self._resume_gap_s: float | None = None  # set by the first heartbeat after that stall
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.checks = 0
        self.stall_count = 0
        self.resume_count = 0

    async def run(self) -> None:
        """Beat on the running loop and watch it from a daemon thread until cancelled.

        A second ``run`` while the first one's thread is alive returns at once. AD-824: on cancellation the thread is
        told to stop and joined for at most ``_JOIN_TIMEOUT_S`` (a thread inside a logging call ends when that call
        returns; see the module docstring), and the cancellation propagates.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.debug("BF-932: the loop-stall sampler is already running; this start is ignored")
            return
        loop = asyncio.get_running_loop()
        self._stop.clear()
        self._last_beat = self._clock()
        thread = threading.Thread(
            target=self._watch, args=(loop, threading.get_ident()), name=THREAD_NAME, daemon=True,
        )
        self._thread = thread
        thread.start()
        try:
            while True:
                with self._lock:
                    now = self._clock()
                    if self._last_beat == self._stalled_beat:  # the first beat after the stall the thread found
                        self._resume_gap_s = now - self._last_beat
                    self._last_beat = now
                await asyncio.sleep(self._tick_s)
        finally:  # nothing on the cancellation path logs before the stop event is set
            self._stop.set()
            thread.join(timeout=_JOIN_TIMEOUT_S)

    def _ended(self, loop: asyncio.AbstractEventLoop) -> bool:
        """True once the thread should end: told to stop, the loop closed, or ``active`` says no."""
        return self._stop.is_set() or loop.is_closed() or (self._active is not None and not self._active())

    def _watch(self, loop: asyncio.AbstractEventLoop, loop_thread_id: int) -> None:
        """The thread: one check per tick, until stopped, until the loop closes, or once ``active`` says no."""
        stalled = False
        reported = False
        try:
            while not self._stop.wait(self._tick_s):
                try:
                    if self._ended(loop):
                        return
                    if not loop.is_running():
                        stalled = False  # a loop that is not running is not blocked
                        continue
                    self.checks += 1
                    if not stalled:
                        with self._lock:
                            age_s = self._clock() - self._last_beat
                            if age_s > self._threshold_s:
                                stalled = True
                                self._stalled_beat = self._last_beat  # the heartbeat records the gap that ends it
                                self._resume_gap_s = None
                        if not stalled:
                            continue
                        self.stall_count += 1
                        reported = False
                        frames = _innermost_frames(loop_thread_id, _STACK_DEPTH)
                        if self._ended(loop):
                            return  # shutdown began while the frames were read: they may show shutdown itself
                        reported = self._warnings.emit(
                            "BF-932: event loop blocked for %.0f ms (threshold %.0f ms); loop thread at: %s",
                            age_s * 1000.0,
                            self._threshold_s * 1000.0,
                            frames,
                        )
                        continue
                    with self._lock:
                        gap_s = self._resume_gap_s
                        if gap_s is None:
                            continue  # no heartbeat since the stall: the loop is still held
                        self._stalled_beat = self._resume_gap_s = None
                    stalled = False
                    self.resume_count += 1
                    if reported:
                        logger.info("BF-932: event loop resumed after %.0f ms (heartbeat gap)", gap_s * 1000.0)
                except Exception as error:
                    _drop(error)
        except Exception as error:  # the wait itself: the thread ends
            _drop(error)
```

### 6.7 `src/probos/config_models/core.py`

**P13.** SEARCH:
```python
class SystemInfo(BaseModel):
    """Top-level system identity."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"
```
REPLACE:
```python
class SystemInfo(BaseModel):
    """Top-level system identity and process-wide diagnostics."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"
    # BF-932 (#1670): the loop-stall sampler (probos.utils.loop_stall), started by ProbOSRuntime.start.
    loop_stall_warn_seconds: float = Field(
        default=1.0, ge=0.0, le=60.0, allow_inf_nan=False,
        description=(
            "BF-932: seconds the event loop may go without a heartbeat before one WARNING names the code "
            "holding it (file:line function of the loop thread's innermost frames). 0 starts no sampler; "
            "otherwise at least 0.1."
        ),
    )

    @field_validator("loop_stall_warn_seconds")
    @classmethod
    def _loop_stall_is_off_or_at_least_a_tenth(cls, value: float) -> float:
        if 0.0 < value < 0.1:
            raise ValueError("loop_stall_warn_seconds is 0 (off) or at least 0.1")
        return value
```

`Field` and `field_validator` are imported at `core.py`:13.

### 6.8 `src/probos/runtime.py`

**P14.** SEARCH:
```python
        self._sqlite_backup_task = self._spawn_background(
            self._sqlite_backup_loop(),
            name="sqlite-backup-loop",
            drain_on_shutdown=True,
        )
```
REPLACE:
```python
        self._sqlite_backup_task = self._spawn_background(
            self._sqlite_backup_loop(),
            name="sqlite-backup-loop",
            drain_on_shutdown=True,
        )

        # BF-932 (#1670): the loop-stall sampler. One WARNING names the code that holds the event loop longer than
        # system.loop_stall_warn_seconds (0 starts nothing). It stops watching once shutdown() begins, and the
        # AD-824 sweep cancels its heartbeat, which stops its thread (probos.utils.loop_stall says how, at shutdown).
        _loop_stall_s = self.config.system.loop_stall_warn_seconds
        if _loop_stall_s > 0:
            from probos.utils.loop_stall import LoopStallSampler

            self._spawn_background(
                LoopStallSampler(
                    threshold_s=_loop_stall_s,
                    active=lambda: not self._shutdown_started,
                ).run(),
                name="bf932-loop-stall-sampler",
            )
```

### 6.9 `tests/conftest.py`

**P15.** SEARCH:
```python
    stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)
    monkeypatch.setattr(credential_store, "subprocess", stand_in)
    yield calls
```
REPLACE:
```python
    stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)
    monkeypatch.setattr(credential_store, "subprocess", stand_in)
    yield calls


@pytest.fixture(autouse=True)
def _bf932_quiet_loop_stall_sampler(request, monkeypatch):
    """BF-932 (#1670): a booted runtime starts no loop-stall sampler in a test unless the test asks for it.

    The sampler is on by default (system.loop_stall_warn_seconds 1.0) and writes a WARNING when the event loop is held
    that long. A loaded test host pauses a process that long now and then, and many booted tests assert that no
    WARNING was written. So ``LoopStallSampler.run`` returns at once here; a test that requests the
    ``bf932_live_loop_stall_sampler`` fixture (tests/test_bf932_d2_loop_stall_sampler.py) gets the real one. This
    patches the pytest process only: a runtime a test boots in a child process
    (tests/fixtures/federation_cluster_node.py, ``python -m probos``) runs the real sampler, and its parent reads
    that child's output only for named markers.
    """
    if "bf932_live_loop_stall_sampler" in request.fixturenames:
        yield
        return
    from probos.utils import loop_stall

    async def _quiet(self) -> None:
        return None

    monkeypatch.setattr(loop_stall.LoopStallSampler, "run", _quiet)
    yield
```

### 6.10 `tests/test_ad1270e2_config_models.py`

**P16.** SEARCH:
```python
    "system": {"name": "ProbOS", "version": "0.1.0", "log_level": "INFO"},
```
REPLACE:
```python
    # BF-932 (#1670) adds system.loop_stall_warn_seconds (default 1.0) after the move.
    "system": {"name": "ProbOS", "version": "0.1.0", "log_level": "INFO", "loop_stall_warn_seconds": 1.0},
```

### 6.11 `tests/test_ad1152_agentic_correlation.py`

**P17.** SEARCH:
```python
    assert config["security"]["memory"].pop("correlation_cutoff") == 0.0
```
REPLACE:
```python
    assert config["security"]["memory"].pop("correlation_cutoff") == 0.0
    # BF-932's loop-stall threshold (1.0 s; 0 starts no sampler) was added after this capture too. The sampler is
    # started in ProbOSRuntime.start, which this observation never calls.
    assert config["system"].pop("loop_stall_warn_seconds") == 1.0
```

### 6.12 `tests/test_ad1270e1_config_facade.py`

**P18.** SEARCH:
```python
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    assert counts["field_definitions"] == 1877  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    # BF-932 (#1670) adds system.loop_stall_warn_seconds (1877 -> 1878).
    assert counts["field_definitions"] == 1878  # AD-1206 intentionally adds github_repository.
```

### 6.13 New file `tests/test_bf932_d2_loop_stall_sampler.py`

New file:

```python
"""BF-932 (#1670) D2: the loop-stall sampler names the code that holds the event loop.

The stalls are real. The loop's own thread blocks until the sampler has reported it: a logging handler on the
sampler's logger sets a ``threading.Event`` when the WARNING names the blocking function, so a stall lasts exactly
until it is detected. Where a test needs exact ages and gaps, a ``_Clock`` the test moves replaces the monotonic clock,
so a slow host cannot change them. A guard timeout fails a hung test; no assertion bounds a duration. Every heartbeat
task a test starts ends inside that test, on success and on failure. tests/conftest.py makes the sampler a no-op for
every other test; each test here that runs it requests ``bf932_live_loop_stall_sampler``.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
import traceback
import weakref
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import SystemConfig, SystemInfo
from probos.runtime import ProbOSRuntime
from probos.utils import loop_stall
from probos.utils.loop_stall import THREAD_NAME, LoopStallSampler

_LOGGER = "probos.utils.loop_stall"
_BLOCKED = "BF-932: event loop blocked"
_RESUMED = "BF-932: event loop resumed"
_TASK_NAME = "bf932-loop-stall-sampler"
_GUARD_S = 30.0
_HELD_S = 10.0  # how long an observer waits for the stop event; well under _GUARD_S, the held handler's own limit


@pytest.fixture
def bf932_live_loop_stall_sampler() -> None:
    """Asks tests/conftest.py's _bf932_quiet_loop_stall_sampler to leave the real sampler in place."""
    return None


class _Signals(logging.Handler):
    """The sampler's lines as written; sets ``blocked`` for a WARNING naming ``marker`` and ``resumed`` for an INFO.

    With a ``gate``, the thread that writes the WARNING naming ``marker`` is held inside this handler until the gate is
    set: a slow handler, which holds its lock while it is held. The level is INFO, and a test that holds it sets the
    logger to INFO, so the loop thread's DEBUG lines do not reach it there; the verbose-configuration test lowers both
    to DEBUG, where a log call from the loop thread that reaches this handler waits for that lock.
    """

    def __init__(self, marker: str, gate: threading.Event | None = None) -> None:
        super().__init__(level=logging.INFO)
        self.marker = marker
        self.gate = gate
        self.gate_expired = False
        self.blocked = threading.Event()
        self.resumed = threading.Event()
        self.lines: list[tuple[int, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        self.lines.append((record.levelno, message))
        if record.levelno == logging.WARNING and message.startswith(_BLOCKED) and self.marker in message:
            self.blocked.set()
            if self.gate is not None:
                if not self.gate.wait(_GUARD_S):
                    self.gate_expired = True
        elif record.levelno == logging.INFO and message.startswith(_RESUMED):
            self.resumed.set()


class _Clock:
    """A clock the test moves. ``stamped`` lists the values read on the loop's own thread: the heartbeat's stamps."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.loop_thread = threading.get_ident()
        self.stamped: list[float] = []

    def __call__(self) -> float:
        value = self.now
        if threading.get_ident() == self.loop_thread:
            self.stamped.append(value)
        return value


class _NoStack:
    """Stands in for ``traceback.StackSummary``: reading the stack fails."""

    @staticmethod
    def extract(*args: object, **kwargs: object) -> object:
        raise RuntimeError("bf932 test: the stack could not be read")


class _FailingWait(threading.Event):
    """An Event whose wait raises, as ``Event.wait`` does for a timeout past ``threading.TIMEOUT_MAX``."""

    def wait(self, timeout: float | None = None) -> bool:
        raise OverflowError("bf932 test: timeout out of range")


class _Witness:
    """A local of the loop thread's blocked frame: alive while anything keeps that frame."""


def _dropped(caplog: pytest.LogCaptureFixture) -> bool:
    return any(
        r.name == _LOGGER and "a loop-stall check failed and was dropped" in r.getMessage() for r in caplog.records
    )


def _samplers(before: set[threading.Thread]) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t not in before and t.name == THREAD_NAME and t.is_alive()]


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until ``predicate`` holds; the guard fails a test that never gets there."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _GUARD_S
    while not predicate():
        assert loop.time() < deadline, "guard: the awaited condition never held"
        await asyncio.sleep(0.01)


def _hold_the_loop_until(event: threading.Event) -> None:
    """Blocks the event loop's own thread until the sampler reports it; the WARNING must name this function."""
    assert event.wait(_GUARD_S), "guard: the sampler never reported the blocked loop"


def _hold_the_loop_while(predicate: Callable[[], bool]) -> None:
    """Blocks the event loop's own thread while ``predicate`` holds; ``time.sleep`` lets the sampler's thread run."""
    deadline = time.monotonic() + _GUARD_S
    while predicate():
        assert time.monotonic() < deadline, "guard: the sampler never counted the stall"
        time.sleep(0.005)


def _stall_the_loop(clock: _Clock, reported: threading.Event) -> None:
    """Moves the clock 0.5 past the last heartbeat (100.0) and holds the loop's own thread until the WARNING names this
    function; the loop then resumes with the clock at 101.25, which its first heartbeat after the stall reads."""
    clock.now = 100.5
    assert reported.wait(_GUARD_S), "guard: the sampler never reported the stall"
    clock.now = 101.25


def _hold_the_loop_with_a_witness_until(dropped: Callable[[], bool]) -> weakref.ref[_Witness]:
    """Blocks the loop's own thread, with a local its frame refers to, until the sampler has dropped a failed check."""
    witness = _Witness()
    deadline = time.monotonic() + _GUARD_S
    while not dropped():
        assert time.monotonic() < deadline, "guard: the sampler never dropped a check"
        time.sleep(0.005)
    return weakref.ref(witness)


async def _turn(clock: _Clock, until: float) -> None:
    """Turns the loop, moving the clock 0.01 a turn. The clock moves only while the loop turns, so a paused host cannot
    age the stamp, and a heartbeat that stops stamping falls 0.01 further behind each turn."""
    while clock.now < until:
        clock.now = round(clock.now + 0.01, 2)
        await asyncio.sleep(0.01)


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_d2_a_blocked_loop_gets_one_warning_naming_the_blocker_then_a_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    signals = _Signals(_hold_the_loop_until.__name__)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        _hold_the_loop_until(signals.blocked)
        await _until(signals.resumed.is_set)
    finally:
        sampler_logger.removeHandler(signals)
        await _stop(task)
    named = [m for level, m in signals.lines if level == logging.WARNING and _hold_the_loop_until.__name__ in m]
    assert len(named) == 1  # one WARNING for the one stall
    assert "tests/test_bf932_d2_loop_stall_sampler.py:" in named[0]  # dir/file:line of the blocking frame
    assert "<threading.Event" not in named[0]  # no arguments and no locals
    assert any(level == logging.INFO and m.startswith(_RESUMED) for level, m in signals.lines)


@pytest.mark.asyncio
async def test_d2_a_loop_that_keeps_turning_gets_no_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    clock = _Clock(100.0)
    sampler = LoopStallSampler(threshold_s=0.2, clock=clock)
    task = asyncio.create_task(sampler.run())
    try:
        await _turn(clock, 101.0)  # 100 turns: without heartbeats the stamp would be 1.0 old, five thresholds
        await _until(lambda: sampler.checks >= 10)
    finally:
        await _stop(task)
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []
    assert sampler.stall_count == 0
    assert len(set(clock.stamped)) >= 5  # the heartbeat stamped the moving clock


@pytest.mark.asyncio
@pytest.mark.parametrize(("threshold_s", "expected"), [(1.0, 1), (0.0, 0)])
async def test_d2_the_runtime_starts_one_sampler_by_default_and_none_at_0(
    bf932_live_loop_stall_sampler: None, tmp_path, threshold_s: float, expected: int,
) -> None:
    before = set(threading.enumerate())
    rt = ProbOSRuntime(
        config=SystemConfig(system=SystemInfo(loop_stall_warn_seconds=threshold_s)),
        data_dir=tmp_path,
        episodic_memory=MockEpisodicMemory(relevance_threshold=0.3),
    )
    await rt.start()
    try:
        assert [t.get_name() for t in rt._background_tasks].count(_TASK_NAME) == expected
        if expected:
            await _until(lambda: len(_samplers(before)) == 1)
    finally:
        await rt.stop()
    assert _samplers(before) == []  # the stop's AD-824 sweep cancelled the heartbeat, which joined the thread


@pytest.mark.asyncio
async def test_d2_a_second_run_starts_no_second_thread_and_a_cancel_ends_the_one(
    bf932_live_loop_stall_sampler: None,
) -> None:
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)
    first = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: len(_samplers(before)) == 1)
        await asyncio.wait_for(sampler.run(), _GUARD_S)  # returns at once: the first run's thread is alive
        threads = _samplers(before)
        assert len(threads) == 1 and threads[0].daemon is True
    finally:
        await _stop(first)
    assert not threads[0].is_alive()


def test_d2_a_closed_loop_ends_the_thread(bf932_live_loop_stall_sampler: None) -> None:
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)
    held: list[asyncio.Task[None]] = []  # keeps the heartbeat task alive, so only the closed loop can end the thread
    threads: list[threading.Thread] = []
    destroyed: list[str] = []
    loop = asyncio.new_event_loop()
    # The heartbeat task is still pending when the loop closes. It is destroyed inside this test (gc.collect below),
    # on success and on failure; asyncio's report of it goes to this loop's handler, not to a log another test reads.
    loop.set_exception_handler(lambda _loop, context: destroyed.append(str(context.get("message"))))
    try:

        async def _start() -> None:
            held.append(asyncio.get_running_loop().create_task(sampler.run()))
            await _until(lambda: bool(_samplers(before)))
            threads.extend(_samplers(before))

        loop.run_until_complete(_start())
    finally:
        loop.close()
        for thread in threads:
            thread.join(_GUARD_S)  # guard
        ended = [not thread.is_alive() for thread in threads]
        held.clear()
        gc.collect()
    assert ended == [True]
    assert destroyed == ["Task was destroyed but it is pending!"]


@pytest.mark.asyncio
async def test_d2_warnings_are_bounded_and_a_refused_stall_writes_no_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, max_warnings=2, window_s=3600.0)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        for n in (1, 2, 3):
            _hold_the_loop_while(lambda: sampler.stall_count < n)
            await _until(lambda: sampler.resume_count >= n)
    finally:
        await _stop(task)
    lines = [r for r in caplog.records if r.name == _LOGGER]
    assert sampler.stall_count >= 3
    assert len([r for r in lines if r.levelno == logging.WARNING]) == 2
    assert len([r for r in lines if r.levelno == logging.INFO and r.getMessage().startswith(_RESUMED)]) == 2


@pytest.mark.parametrize("value", [0.0, 0.1, 1.0, 60.0])
def test_d2_the_threshold_accepts_0_or_a_value_from_a_tenth_to_60(value: float) -> None:
    assert SystemInfo(loop_stall_warn_seconds=value).loop_stall_warn_seconds == value


@pytest.mark.parametrize("value", [0.05, -1.0, 60.5, float("inf"), float("nan")])
def test_d2_the_threshold_refuses_anything_else(value: float) -> None:
    with pytest.raises(ValidationError):
        SystemInfo(loop_stall_warn_seconds=value)


def test_d2_the_sampler_is_on_by_default() -> None:
    assert SystemConfig().system.loop_stall_warn_seconds == 1.0


@pytest.mark.asyncio
async def test_d2_the_resume_line_carries_the_first_heartbeat_gap_however_late_the_thread_reads_it(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    clock = _Clock(100.0)
    release = threading.Event()  # holds the thread inside the WARNING's handler, so its next check comes late
    signals = _Signals(_stall_the_loop.__name__, gate=release)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    sampler = LoopStallSampler(threshold_s=0.2, clock=clock)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: sampler.checks >= 2)
        _stall_the_loop(clock, signals.blocked)
        await _until(lambda: 101.25 in clock.stamped)  # the first heartbeat after the stall: a gap of 1.25
        clock.now = 109.0
        await _until(lambda: 109.0 in clock.stamped)  # a later heartbeat, before the thread's next check
        release.set()
        await _until(signals.resumed.is_set)
    finally:
        release.set()
        sampler_logger.removeHandler(signals)
        await _stop(task)
    warnings = [m for level, m in signals.lines if level == logging.WARNING]
    assert len(warnings) == 1 and _stall_the_loop.__name__ in warnings[0]
    assert warnings[0].startswith("BF-932: event loop blocked for 500 ms (threshold 200 ms); loop thread at: ")
    assert [m for level, m in signals.lines if level == logging.INFO] == [
        "BF-932: event loop resumed after 1250 ms (heartbeat gap)"
    ]


@pytest.mark.asyncio
async def test_d2_no_warning_is_written_once_shutdown_begins_while_the_frames_are_read(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    state = {"active": True}

    def _shutdown_begins_while_reading(thread_id: int, depth: int) -> str:
        state["active"] = False  # as shutdown() setting _shutdown_started while the thread reads the frames
        return "(frames read as shutdown began)"

    monkeypatch.setattr(loop_stall, "_innermost_frames", _shutdown_begins_while_reading)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, active=lambda: state["active"])
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        _hold_the_loop_while(lambda: state["active"])
        await _until(lambda: _samplers(before) == [])  # the thread ended: inactive
    finally:
        await _stop(task)
    assert sampler.stall_count == 1
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []


@pytest.mark.asyncio
async def test_d2_a_thread_held_in_a_logging_call_at_cancel_ends_when_the_call_returns_and_writes_nothing_more(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    release = threading.Event()
    signals = _Signals(_hold_the_loop_until.__name__, gate=release)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        threads = _samplers(before)
        _hold_the_loop_until(signals.blocked)  # the thread is now inside the WARNING's handler, held by the gate
        await _stop(task)  # sets the stop event; the join gives up after _JOIN_TIMEOUT_S
        held_at_cancel = threads[0].is_alive()
    finally:
        release.set()
        sampler_logger.removeHandler(signals)
        await _stop(task)
    threads[0].join(_GUARD_S)  # guard
    assert held_at_cancel is True  # the timed join returned while the thread was inside the handler
    assert not threads[0].is_alive()  # it ended when the handler returned
    lines = [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO]
    assert lines and lines[-1].levelno == logging.WARNING  # nothing after the held WARNING
    assert _hold_the_loop_until.__name__ in lines[-1].getMessage()


@pytest.mark.asyncio
async def test_d2_a_cancel_sets_the_stop_event_while_a_debug_level_handler_is_held_by_the_warning(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)  # the verbose configuration: DEBUG records reach the handlers
    release = threading.Event()
    signals = _Signals(_hold_the_loop_until.__name__, gate=release)
    signals.setLevel(logging.DEBUG)  # a DEBUG line from the loop thread would wait for this handler's lock
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    sampler = LoopStallSampler(threshold_s=0.2)
    stop_set_while_held: list[bool] = []

    def _observe_the_stop_event() -> None:
        # Off the loop. The handler stays held until this thread has its answer, so True means the stop event was set
        # while the WARNING's handler still held its lock.
        stop_set_while_held.append(sampler._stop.wait(_HELD_S))
        release.set()

    observer = threading.Thread(target=_observe_the_stop_event, name="bf932-test-stop-observer", daemon=True)
    before = set(threading.enumerate())
    threads: list[threading.Thread] = []
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        threads = _samplers(before)
        _hold_the_loop_until(signals.blocked)  # the thread is now inside the WARNING's handler, holding its lock
        observer.start()
        await _stop(task)  # the cancellation must set the stop event without waiting for that lock
    finally:
        release.set()
        sampler_logger.removeHandler(signals)
        await _stop(task)
        if observer.is_alive():
            observer.join(_GUARD_S)  # guard
        for thread in threads:
            thread.join(_GUARD_S)  # guard
    assert not signals.gate_expired, "guard: the held handler's gate expired; the hold did not cover the cancellation"
    assert stop_set_while_held == [True]
    assert not observer.is_alive() and not any(thread.is_alive() for thread in threads)


@pytest.mark.asyncio
async def test_d2_a_stall_whose_warning_failed_gets_no_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    real = loop_stall._innermost_frames
    reads: list[int] = []

    def _every_read_after_the_first_fails(thread_id: int, depth: int) -> str:
        reads.append(thread_id)
        if len(reads) >= 2:
            raise RuntimeError("bf932 test: the stack could not be read")
        return real(thread_id, depth)

    monkeypatch.setattr(loop_stall, "_innermost_frames", _every_read_after_the_first_fails)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        for n in (1, 2):
            _hold_the_loop_while(lambda: sampler.stall_count < n)
            await _until(lambda: sampler.resume_count >= n)
    finally:
        await _stop(task)
    lines = [r for r in caplog.records if r.name == _LOGGER]
    assert len([r for r in lines if r.levelno == logging.WARNING]) == 1  # only the first read succeeded
    assert len([r for r in lines if r.levelno == logging.INFO and r.getMessage().startswith(_RESUMED)]) == 1


@pytest.mark.asyncio
async def test_d2_a_failed_stack_read_keeps_no_frame_of_the_loop_alive(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)  # caplog keeps every record, as a buffering handler would
    monkeypatch.setattr(
        loop_stall, "traceback", SimpleNamespace(walk_stack=traceback.walk_stack, StackSummary=_NoStack),
    )
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        witness = _hold_the_loop_with_a_witness_until(lambda: _dropped(caplog))
    finally:
        await _stop(task)  # the thread is told to stop and joined, so none of its frames is running
    gc.collect()
    assert witness() is None  # the dropped record keeps no frame of the loop thread
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []


@pytest.mark.parametrize("threshold_s", [float("inf"), float("nan"), 1e300])
def test_d2_the_sampler_refuses_a_threshold_its_wait_cannot_take(threshold_s: float) -> None:
    with pytest.raises(ValueError):
        LoopStallSampler(threshold_s=threshold_s)


@pytest.mark.asyncio
async def test_d2_a_failing_wait_ends_the_thread_at_debug_and_nothing_escapes(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monkeypatch.setattr(
        loop_stall,
        "threading",
        SimpleNamespace(
            Event=_FailingWait, Lock=threading.Lock, Thread=threading.Thread, get_ident=threading.get_ident,
            TIMEOUT_MAX=threading.TIMEOUT_MAX,
        ),
    )
    escaped: list[object] = []
    previous_hook = threading.excepthook
    threading.excepthook = escaped.append  # an exception that leaves the thread lands here
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(escaped) or _dropped(caplog))
    finally:
        threading.excepthook = previous_hook
        await _stop(task)
    assert escaped == []
    assert _samplers(before) == []
```

### 6.14 `src/probos/perception/consumer.py`

**P19** (S1 repair: the comment names the DM route only, and the docstring's freshness sentence is F4's wording; the code lines are unchanged). SEARCH:
```python
# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
```
REPLACE:
```python
# BF-932 (#1670): the scene refreshes that the DM route started and did not wait for. Each task is held here until it
# ends, so none is garbage collected while it runs.
_SCENE_REFRESH_TASKS: set[asyncio.Task[Any]] = set()


def _end_scene_refresh(task: asyncio.Task[Any]) -> None:
    """BF-932: the done callback of a background scene refresh: release the task and log its failure once."""
    _SCENE_REFRESH_TASKS.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("BF-932: background scene refresh failed: %r", error, exc_info=error)


def refresh_scene_in_background(consumer: Any, *, timeout_s: float = 4.0) -> asyncio.Task[Any]:
    """BF-932 (#1670): start ``consumer.force_describe_current_frame`` and return without waiting for it.

    The caller renders the working memory as it is. The fresh description is present once the describe lands in
    working memory; an immediate second DM may still get the sentinel. BF-977's deadline and single-flight permit
    apply inside the call, unchanged: a refresh started while another holds the permit returns ``None`` at once. The
    deadline bounds the describe, not a cancellation: a cancelled refresh waits for BF-977's step to end. Call it on
    the running loop.
    """
    task = asyncio.get_running_loop().create_task(consumer.force_describe_current_frame(timeout_s=timeout_s))
    _SCENE_REFRESH_TASKS.add(task)
    task.add_done_callback(_end_scene_refresh)
    return task


# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
```

`asyncio` is imported at `consumer.py`:20, `Any` at :26, `logger` at :39.

### 6.15 `src/probos/routers/agents.py`

**P20** (S1 repair: F3, `scheduled` only after the helper returns and `failed` in the `except` branch; F4's comment). SEARCH:
```python
            # AD-733c-1: force-describe the latest captured frame before
            # rendering the scene block. Best-effort + bounded (4s timeout
            # via VisionConsumer.force_describe_current_frame). When the
            # cache is empty or the LLM is slow, we silently fall back to
            # whatever the WM already contains.
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                _hook = "ran"  # BF-932: log-only
                _t_hook0 = time.perf_counter()
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
```
REPLACE:
```python
            # AD-733c-1: force-describe the latest captured frame. BF-932
            # (#1670): the describe is started, not awaited (bounded at 4 s
            # inside VisionConsumer.force_describe_current_frame); this reply
            # renders whatever the WM already contains. The fresh description
            # is present once the describe lands in working memory; an
            # immediate second DM may still get the sentinel.
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                _t_hook0 = time.perf_counter()
                try:
                    from probos.perception.consumer import refresh_scene_in_background

                    refresh_scene_in_background(_consumer, timeout_s=4.0)
                    _hook = "scheduled"  # BF-932: log-only; set once the describe is started
                except Exception:
                    _hook = "failed"  # BF-932: log-only; starting the describe raised, nothing runs
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
```

The lines after the SEARCH (`_t_hook1 = time.perf_counter()`, the AD-733c-2 notification) are unchanged; no line between the helper's return and `_mode_ctrl.note_dm_activity()` awaits, so the started task first runs after the notification (S1c, V5).

### 6.16 `src/probos/routers/thread_fanout.py`: removed (S1 repair)

P21 and P22 are removed. `routers/thread_fanout.py` stays byte-identical to the base: `_maybe_force_describe_frame` (:386-410) still awaits `force_describe_current_frame(timeout_s=4.0)` at :406, called once per round at :1022 (S1d).

### 6.17 `tests/test_bf932_reply_path_timing.py`

**P23.** SEARCH:
```python
from probos.config import CognitiveConfig
```
REPLACE:
```python
from probos.config import CognitiveConfig
from probos.perception import consumer as consumer_module
```

**P24** (S1 repair: the docstring names the DM route only). SEARCH:
```python
async def _dm(runtime):
    with _CREW_PATCH:
        return await agent_chat("test-id", _req(), runtime)
```
REPLACE:
```python
async def drain_scene_refreshes() -> None:
    """BF-932 S1: end the scene refreshes started on this loop that nothing waited for (the DM route's)."""
    loop = asyncio.get_running_loop()
    started = [task for task in list(consumer_module._SCENE_REFRESH_TASKS) if task.get_loop() is loop]
    await asyncio.gather(*started, return_exceptions=True)


async def _dm(runtime):
    try:
        with _CREW_PATCH:
            return await agent_chat("test-id", _req(), runtime)
    finally:
        await drain_scene_refreshes()  # BF-932 S1: the route no longer waits for the describe it starts
```

**P25.** SEARCH:
```python
    assert _field(line, "hook") == "ran" and _field(line, "sent") == "yes"
    assert float(_field(line, "hook_ms")) >= 25 and float(_field(line, "send_ms")) >= 25
    assert float(_field(line, "total_ms")) >= 50
```
REPLACE:
```python
    # BF-932 S1: the route starts the describe and does not wait for it, so hook says scheduled and the stub's 30 ms
    # sleep is no longer inside hook_ms or total_ms; only the send's 30 ms sleep is on the route.
    assert _field(line, "hook") == "scheduled" and _field(line, "sent") == "yes"
    assert float(_field(line, "hook_ms")) >= 0 and float(_field(line, "send_ms")) >= 25
    assert float(_field(line, "total_ms")) >= 25
```

**P26** (S1 repair: the reason names the label's meaning). SEARCH:
```python
    assert _field(line, "hook") == "ran" and answer["response"] == "Acknowledged."
```
REPLACE:
```python
    # BF-932 S1: starting the describe succeeded, so hook says scheduled; the describe's own failure ends its background
    # task (the done callback logs it) and the reply goes out. A failure to start it says failed (V4).
    assert _field(line, "hook") == "scheduled" and answer["response"] == "Acknowledged."
```

**P27.** SEARCH:
```python
    assert order == ["consumer", "send"] and runtime.vision_consumer.timeouts == [4.0]
```
REPLACE:
```python
    # BF-932 S1: the describe runs as its own task, so the route no longer orders it before the send; _dm ends it.
    assert sorted(order) == ["consumer", "send"] and runtime.vision_consumer.timeouts == [4.0]
```

### 6.18 `tests/test_dm_camera_hook_deadline.py`

**P28** (S1 repair: the reason names the label's meaning). SEARCH:
```python
    assert _field(lines[0], "hook") == "ran"
```
REPLACE:
```python
    assert _field(lines[0], "hook") == "scheduled"  # BF-932 S1: the describe was started; a denied send does not change it
```

### 6.19 `tests/test_ad978_group_perception.py`: removed (S1 repair)

P29-P32 are removed. `tests/test_ad978_group_perception.py` stays byte-identical to the base: the group round still awaits the describe, so its three `force_describe` tests need no drain.

### 6.20 New file `tests/test_bf932_s1_scene_refresh_background.py`

New file (S1 repair: G1 and the group imports removed; V4 and V5 new; V1 and V3 unchanged):

```python
"""BF-932 (#1670) S1: the Captain's DM starts the camera describe and does not wait for it.

The stand-in consumers have the real method name and signature. The stuck describe waits on an Event that the test
sets only in ``finally``: a describe that ignores its own deadline. The route is the real ``agent_chat`` over the
BF-932 timing harness. A guard timeout fails a hung test; no assertion bounds a duration. The group round is not
changed in batch 1 (it still awaits the describe), so it has no case here.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from probos.perception import consumer as consumer_module
from probos.routers.agents import agent_chat
from tests.test_bf932_reply_path_timing import (
    _CREW_PATCH,
    _ROUTE,
    _dm,
    _field,
    _lines,
    _one,
    _req,
    _runtime,
    drain_scene_refreshes,
)

_GUARD_S = 10.0


class _StuckConsumer:
    """A describe that never returns until the test releases it."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.timeouts: list[float] = []

    async def force_describe_current_frame(self, session_id: str | None = None, *, timeout_s: float = 4.0) -> str | None:
        self.timeouts.append(timeout_s)
        self.entered.set()
        await self.release.wait()
        return "scene"


@pytest.mark.asyncio
async def test_v1_a_describe_that_never_returns_does_not_hold_the_captains_reply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    runtime = _runtime([])
    consumer = _StuckConsumer()
    runtime.vision_consumer = consumer
    try:
        with _CREW_PATCH:
            answer = await asyncio.wait_for(agent_chat("test-id", _req(), runtime), _GUARD_S)
        await asyncio.wait_for(consumer.entered.wait(), _GUARD_S)  # the refresh did start
        assert answer["response"] == "Acknowledged."
        runtime.intent_bus.send.assert_awaited_once()
        assert not consumer.release.is_set()  # the reply went out while the describe was still blocked
        assert consumer.timeouts == [4.0]
        assert _field(_one(_lines(caplog, _ROUTE)), "hook") == "scheduled"
    finally:
        consumer.release.set()
        await drain_scene_refreshes()


@pytest.mark.asyncio
async def test_v3_the_refresh_is_held_until_it_ends_and_its_failure_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.perception.consumer import refresh_scene_in_background  # here, so the base fails this test alone

    caplog.set_level(logging.WARNING, logger="probos.perception.consumer")
    release = asyncio.Event()
    seen: list[float] = []

    class _Failing:
        async def force_describe_current_frame(self, *, timeout_s: float = 4.0) -> str | None:
            seen.append(timeout_s)
            await release.wait()
            raise RuntimeError("vision down")

    task = refresh_scene_in_background(_Failing(), timeout_s=2.5)
    try:
        await asyncio.sleep(0)
        assert task in consumer_module._SCENE_REFRESH_TASKS and not task.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), _GUARD_S)
        await asyncio.sleep(0)
    finally:
        release.set()
    assert task not in consumer_module._SCENE_REFRESH_TASKS
    assert seen == [2.5]
    failures = [r for r in caplog.records if r.getMessage().startswith("BF-932: background scene refresh failed")]
    assert len(failures) == 1


class _Unschedulable:
    """A consumer whose method returns no coroutine, so the route cannot start a task from it (the review's F3)."""

    def __init__(self) -> None:
        self.calls = 0

    def force_describe_current_frame(self, session_id: str | None = None, *, timeout_s: float = 4.0) -> None:
        self.calls += 1
        return None


@pytest.mark.asyncio
async def test_v4_a_describe_that_cannot_be_started_says_hook_failed_and_the_reply_still_goes_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    runtime = _runtime([])
    consumer = _Unschedulable()
    runtime.vision_consumer = consumer
    answer = await asyncio.wait_for(_dm(runtime), _GUARD_S)
    line = _one(_lines(caplog, _ROUTE))
    # BF-932 S1 (round-1 F3): the label says what happened; scheduled would claim a describe that never started.
    assert _field(line, "hook") == "failed"
    assert answer["response"] == "Acknowledged." and _field(line, "sent") == "yes"
    runtime.intent_bus.send.assert_awaited_once()
    assert consumer.calls == 1  # the route did try
    loop = asyncio.get_running_loop()
    assert [task for task in consumer_module._SCENE_REFRESH_TASKS if task.get_loop() is loop] == []  # no task started


@pytest.mark.asyncio
async def test_v5_the_background_describe_starts_after_the_dms_engagement_notification() -> None:
    # BF-932 S1 (round-1 F2, accepted by the Architect, 2026-11-27): the describe a DM starts runs after
    # note_dm_activity(), so it is charged to the ENGAGED budget, as AD-733c-2 intends for a DM. At most one call per DM
    # moves from the AMBIENT budget; the difference shows only at the caps (200 per session, 2,000 per day). This pins
    # the order: a change that describes before the notification again must revisit that decision.
    order: list[str] = []
    runtime = _runtime(order)
    runtime.perception_engagement_registry = None
    runtime.perception_mode_controller = SimpleNamespace(note_dm_activity=lambda: order.append("notify"))
    answer = await asyncio.wait_for(_dm(runtime), _GUARD_S)
    assert answer["response"] == "Acknowledged."
    assert order.count("notify") == 1 and order.count("consumer") == 1, order
    assert order.index("notify") < order.index("consumer"), order
```

The new file imports `_dm` (which drains the started refreshes in its `finally`, P24) for V4 and V5; V1 keeps its own guarded call because it must observe the describe still blocked after the reply.

### 6.20a `src/probos/config.py` (S1 repair, F4)

**P37.** SEARCH:
```python
    # AD-733c-1 (Wave 172): DM-receive force-describe of the latest cached frame
    # before the agent's reply is composed. 4s wall-clock timeout enforced by
    # VisionConsumer.force_describe_current_frame. Default True so the
    # subsystem benefits from fresh-frame grounding out of the box; operator
    # can disable for cost-discipline experiments.
    dm_force_describe_enabled: bool = Field(default=True,
        description="On every DM, synchronously describe the latest captured frame before composing the reply (4s timeout floor).",
    )
```
REPLACE:
```python
    # AD-733c-1 (Wave 172): DM-receive force-describe of the latest cached frame.
    # BF-932 (#1670): the DM route starts it in the background and the reply
    # never waits for it; 4s wall-clock deadline enforced by
    # VisionConsumer.force_describe_current_frame. A group round still awaits
    # it. Default True so the subsystem benefits from fresh-frame grounding out
    # of the box; operator can disable for cost-discipline experiments.
    dm_force_describe_enabled: bool = Field(default=True,
        description="On every DM, start a describe of the latest captured frame in the background; the reply never waits for it (4s deadline). A group round still awaits it.",
    )
```

Only the comment and the `description` string change; the name, type and default are byte-identical, so the generated files change as 4b says.

### 6.21 `PROGRESS.md`

**P33.** SEARCH (the heading at build time; see section 4, Shared trackers):
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-932 (2026-11-27), #1670 batch 1 -- the dream cycle gives the event loop turns and a loop-stall sampler names any blocker.** The vessel's log shows the event loop silent for 18 s at the same point of two dream cycles (2026-10-25 19:28:56-19:29:14 and 2026-10-30 23:40:49-23:41:07, after Step 7f and before Step 7h), with a TTS store write of 17.6 s inside the second. Step 7g (AD-551) read every notebook (about 2,700) three times and compared every pair of them with no await, and Step 7f2 (AD-873) made up to 1,000 synchronous Chroma calls with none. Those loops now give the loop a turn every fixed count of units: `RecordsStore.list_entries` every 16 files in its default mode (the strict mode keeps one pass), Step 7g every 16 reads or word sets and every 2,000 pair iterations (each note's word set is built once, not once per pair), and the decay sweep every 8 episodes. Step 7g now writes a consolidation only when every member still reads as it did when loaded (a stale cluster waits for the next dream) and archives a member only when it still does, so a note revised during the step keeps its revision. With no concurrent writer the step's clusters, convergence events and reports are unchanged. New `probos.utils.loop_stall.LoopStallSampler` (a heartbeat on the loop and a daemon thread): when the loop goes `system.loop_stall_warn_seconds` (default 1.0; 0 starts none) without a heartbeat, it logs one WARNING `BF-932: event loop blocked for <ms> ms ...; loop thread at: <dir/file:line function> <- ...`, and one INFO `BF-932: event loop resumed after <ms> ms` with the gap of the first heartbeat after the stall; at most 10 WARNINGs a minute. It starts at the end of `ProbOSRuntime.start` and stops watching when shutdown begins (no WARNING whose stack was read after that is written); in the pytest process tests get it only on request (`tests/conftest.py`), and a runtime a test boots in a child process runs it. The DM's background camera describe (S1) was built and reviewed twice and is deferred to batch 2: a describe that outlives the DM reply can land during a group round and give that round's episode a newer frame than its prompt saw. In batch 1 the Captain's DM still waits up to 4 s for the camera describe (the `BF-932: dm route` line's `hook=ran` and `hook_ms` show it). The Captain-DM concurrency slot and the recall budget are batch 2, chosen by what the sampler and the BF-932 lines show live. #1670 stays open until the Captain's live re-measurement. New `tests/test_bf932_d1_dream_yields.py`, `tests/test_bf932_d2_loop_stall_sampler.py`. Contract `prompts/bf-932-reply-never-waits.md`.
```

### 6.22 `DECISIONS.md`

**P34.** SEARCH (the newest entry's heading at build time; at HEAD `63c536b3` it is this one; see section 4, Shared trackers):
```markdown
### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)
```
REPLACE:
```markdown
### BF-932 -- the dream cycle gives the event loop turns and a loop-stall sampler names any blocker (2026-11-27, #1670)

- *Scope.* #1670 batch 1 (D1, D2). `utils/loop_yield.py` and `utils/loop_stall.py` (new); `cognitive/dreaming.py` Step 7g; `knowledge/records_store.py` `list_entries` and `entry_fingerprint`; `cognitive/episodic.py` `sweep_episode_decay`; `config_models/core.py` `SystemInfo.loop_stall_warn_seconds`; `runtime.py` `start`. Contract `prompts/bf-932-reply-never-waits.md`.
- *D1.* The dream's synchronous loops await `asyncio.sleep(0)` every fixed count of units (2,000 pair iterations, 16 reads or word sets, 16 listed files, 8 episodes), and Step 7g builds each note's word set once. Because those turns let a writer run between Step 7g's reads and its writes, Step 7g publishes a cluster only when every member's file still has the bytes it had when loaded (a sha256 taken before the read, `RecordsStore.entry_fingerprint`), and archives a member only when its file still does; the check has no turn before its write (`entry_fingerprint` has no await), so no lock or version field is needed. Not a worker thread (it cannot be cancelled and it shares the default executor), not a process pool (Windows spawn and pickling), not an exact Jaccard prune (a speedup the property does not need). The strict listing keeps one pass for the stand-down and the archive promotion. Step 12's single bulk Chroma calls are left for the sampler to measure.
- *D2.* A heartbeat coroutine plus a daemon thread that reads the loop thread's frames with `sys._current_frames()` while the loop is blocked; one WARNING per stall, one INFO per resume of a reported stall carrying the first heartbeat's gap (recorded by the heartbeat under a lock it shares with the thread, so a late check cannot inflate it), 10 WARNINGs a minute; standard library only. At shutdown the thread re-checks between reading the stack and writing the WARNING, and the heartbeat's cancellation joins it for at most 1 s: a thread inside a slow log handler ends when the handler returns and writes nothing more (a bounded outcome, chosen over making shutdown wait on a handler). Not asyncio debug mode (costly; it reports after the callback returns), not `faulthandler.dump_traceback_later` (one process-wide timer; it writes outside the log). One field, `system.loop_stall_warn_seconds` (0, or 0.1 to 60; default 1.0). Tests in the pytest process run it only on request; child processes run it.
- *S1 deferred.* The DM's background camera describe was built and reviewed twice and moves to batch 2: a background describe that outlives the DM reply can land during a group round and give that round's episode a newer frame than its prompt saw (false visual provenance in recall). In batch 1 the DM still awaits the describe (BF-977's 4 s bound).
- *Deferred.* The Captain-DM concurrency slot and the recall budget (batch 2), chosen by the live numbers. S1's files are batch 2 too: `perception/consumer.py` (`refresh_scene_in_background`), `routers/agents.py`, `config.py` (the `dm_force_describe_enabled` description).
- *Reversal.* Revert the commits; no persisted format changes. A yaml that sets `system.loop_stall_warn_seconds` still loads after a revert (`SystemInfo` ignores an unknown key).

### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)
```

## 7. Consumers

Batch 1: the rows from `the DM route line` to `_SCENE_REFRESH_TASKS at shutdown` are S1's, batch 2 (deferred). In batch 1 the DM route line, the engagement notification order, `_maybe_force_describe_frame` and the `dm_force_describe_enabled` description are byte-identical to the base.

| Contract | Consumer | After the change |
|---|---|---|
| `list_entries` default mode | Step 7g (`dreaming.py`:932), AD-555 (`notebook_quality.py`:217), AD-563 (`knowledge_linter.py`:58), every other non-strict caller | same entries in the same order; the coroutine now suspends every 16 files, so a concurrent writer may land mid-listing (a file deleted meanwhile is skipped as unreadable, at DEBUG, as before) |
| `list_entries(strict=True)` | `archive_promotion.py`:310, `stand_down.py`:281, `recreation/history.py`:184-185 | unchanged (no turn) |
| `RecordsStore.entry_fingerprint` (new, P40) | Step 7g only: the per-agent load (P38, before each `read_entry`) and the publication checks (P35, P36, through P2's helper). No other caller, and nothing enumerates or dispatches `RecordsStore`'s methods by name (Absence Verified, 10) | no `await`, no counter, tracker or classification gate; the sha256 of the file's bytes, `None` for a missing file; equal on every call while the bytes are unchanged, whatever the frontmatter loads to; a raise counts as changed inside the helper (and drops the note at the load, inside the existing `except`), so Step 7g's whole-step handler never sees it. `read_entry`'s callers and behaviour are unchanged: the checks no longer call it, so Step 7g calls it as often as the base does |
| `sweep_episode_decay` | Step 7f2 (`dreaming.py`:911) | same counts; suspends every 8 episodes; each episode's get and update stay adjacent |
| Step 7g output | `DreamReport.notebook_consolidations`, `convergence_reports_generated`; `convergence_detected` / `wrong_convergence_detected` events; the records written | unchanged when no note changes during the step. A cluster with a member changed after its read is not written, archived or counted (one INFO, `Step 7g: skipped a cluster ...`); a member changed after the primary's write stays live (one INFO, `Step 7g: left ... live`). A cancellation can now land at a turn; every turn sits before a write for its agent or component, so a cancelled step leaves no half-written cluster it did not already risk at its existing awaits |
| `SystemInfo` dump | `test_ad1270e2_config_models.py`:63 (P16), AD-1152 golden (P17), facade count (P18), the facade baseline and the config reference (4a), HXI config API (`routers/config.py` dumps every field) | one more key in `system`; the HXI save writes only changed fields (`test_bf996_hxi_save_on_disk.py`) |
| the sampler's lines | `probos.log` (the Captain's Select-String, section 15); the operator's probe | new WARNING and INFO lines from `probos.utils.loop_stall`, formats unchanged by the D2 repair; the INFO's number is now the first heartbeat's gap; a failed check writes `BF-932: a loop-stall check failed and was dropped: <repr>` at DEBUG |
| `ProbOSRuntime.start` | booted tests; `test_issue1419_failed_start_rollback.py`:164 (`self._startup_complete = True` is still the last statement); `tests/fixtures/runtime_lifecycle.py`:144-156 (reports non-daemon threads only) | one more background task (a no-op under `tests/conftest.py`); a daemon thread when live |
| `ProbOSRuntime.start` in a child process | `tests/fixtures/federation_cluster_node.py`:182-184 (the six `test_ad1198_*_gate.py` files); `test_ad1137_quickstart_chain.py`:221 (`python -m probos`) | the real sampler runs (D2d). Parents read child output only for named markers (`federation_cluster.py`:590, :597, :777-790) and the exit code (:644); a sampler line matches none of them |
| `run()`'s cancellation | the AD-824 sweep (`startup/shutdown.py`:1373-1399) | the task ends after at most a 1 s join, as before; the stop event is set before anything on the cancellation path logs, so a handler the thread holds cannot delay it (round 2, R2-F1); the thread then ends at once, or when a logging call it is inside returns (D2e) |
| the DM route line | `test_bf932_reply_path_timing.py` (P24-P27), `test_dm_camera_hook_deadline.py` (P28), V1, V4, the Captain's live check | `hook=scheduled` once the task is started, `hook=failed` when starting it raised, `skipped` as before; `hook_ms` is the time to start the task |
| the DM's engagement notification | `perception_mode_controller` / the per-agent controller (`agents.py`:3504-3518); the ENGAGED call caps (`consumer.py`:331-342, :374-375) | the notification now precedes the describe the DM started, so that describe is charged to the ENGAGED budget (S1c, V5) |
| `_maybe_force_describe_frame` | `group_chat_fanout`; `test_ad978_group_perception.py` | unchanged: `thread_fanout.py` and its test file are byte-identical to the base; the round still awaits the describe (S1d) |
| `PerceptionConfig.dm_force_describe_enabled` description | `docs/development/config-reference.md`, the facade baseline (4b), HXI config API (`routers/config.py`) | the new text; name, type and default unchanged |
| `_SCENE_REFRESH_TASKS` at shutdown | `asyncio.run`'s final cancellation of leftover tasks; BF-977's cancellation path (`consumer.py`:801-811) | a refresh still running is cancelled with the loop's leftovers and waits for BF-977's step to end; not bounded by `timeout_s` (S1e) |
| scanners of the edited files | each file the `rg` command of 8.2 lists | must pass unchanged |

## 8. Gates (the orchestrator runs all of them)

Batch 1 runs the D1 and D2 parts only: in 8.1 the D1 and D2 bullets (the two S1 bullets and their table are batch 2, deferred; "the five new files" are four in batch 1, since 6.20 is batch 2, and 8.1's last line, "the three new files", means the two new test files of D1 and D2); in 8.2 lines 1, 2 and 4-9 (line 3 and the "S1 repair" sentence are batch 2; the `rg` list still runs in full, since batch 1 changes none of S1's files); in 8.3 the M and N rows (S1M1-S1M10 and the "S1 repair (round 1)" note are batch 2); 8.4 as written.

### 8.1 Oracle tree, before the Builder starts

- Each SEARCH of section 6 counted at its turn: 1 each; the five new files do not exist.
- **A/B on the base** (the new test files and the test edits of each slice, without that slice's `src/` sections):
  - D1 (`tests/test_bf932_d1_dream_yields.py`, 22 items). Names used below: the four unchanged controls are `[loop]`, `[bigint]`, `[nanset]`, `[mixed]` (the parametrized control); the B3 tests are the NaN-set recheck test, the four changed-readings items (`[write_entry]`, `[publish]`, `[rename]`, `[delete]`) and the containment test; the order test is `test_d1_the_fingerprint_is_taken_before_the_read`. On the base, red (14): the step 7g turns test (at its first turn assertion, alpha's pairs), the default-listing test, the decay-sweep test (each finds 0 turns), the `LoopYield` test (`ModuleNotFoundError`), the revision test's `member` case (`lost == [1, 2]`: the base's own archive window; the base gives 3 turns, the consolidation write's return and the two renames, and a member revised at the first two is archived unmerged), the stale-cluster test (at `assert first["landed"]`: turn 9 never comes at the base), the self-containing-frontmatter revision test (at `lost == []`: `[1, 2]`, as in the `member` case), the six B3 tests (`AttributeError`: no `entry_fingerprint`) and the order test (at `notebook_consolidations == 0`: 1; the base publishes the cached copy over the revision). Green (8, controls): the step 7g output test, the strict-listing test, the on-disk control, the four unchanged controls (the base compares nothing: 2 consolidations, 4 archived) and the revision test's `primary` case (the base gives no turn between its reads and its write, so every revision lands after the write and wins).
  - D1 on the unrepaired candidate (the first D1 candidate: sections 6.1-6.5 as committed in C1 `e535fd60`, without P35, P36, P38-P40, the helper in P2 and P4's paced word sets; with this revision's test file): red (12): the step 7g turns test at its last assertion (alpha's per-agent word sets: 0 turns, the comprehension), the revision test's `primary` case (`lost == [4, 5, 6]`: the candidate gives 9 turns, 3 reads, 3 pairs, the write's return and two renames; a primary revised after its read and before the write is overwritten by the cached copy) and `member` case (`lost == [2, 3, 4, 5, 6, 7, 8]`: revised after its read, then archived with the revision unmerged), the stale-cluster test (at `notebook_consolidations == 0`: the candidate publishes; turn 9 is its last rename), the self-containing-frontmatter revision test (the same lost revision, measured), the six B3 tests (`AttributeError`) and the order test (it publishes). Green (10): the output test, both listing tests, the decay test, the `LoopYield` test, the on-disk control and the four unchanged controls.
  - On the repaired candidate every item passes; the step gives 12 turns in the revision test (3 reads, 3 word sets, 3 pairs, the write's return, two renames; P38's `await entry_fingerprint` is not a `sleep`, so it is no turn) and both cases report `lost == []`.
  - D1 on the round-3 candidate (staged tree `4b848295`, reproduced in `D:\ProbOS-worktrees\b932-rv6`: the round-2 repair, whose helper re-reads and compares `repr`s inside its `try`; with this revision's test file): red: the six B3 tests (`AttributeError`: no `entry_fingerprint`) and `[bigint]` (at `notebook_consolidations == 2`: 1; `repr` of the integer raises `ValueError` at each of alpha's checks, counted as changed, so alpha's cluster is skipped; the reviewer measured 1 and 2). `[nanset]` is not a criterion there: whether two loads order the fresh NaNs alike depends on allocation (the reviewer measured 1 and 2, 2 and 3, or 2 and 4 across runs and set shapes); the NaN-set recheck test is the deterministic pin, and it is red there at setup. Green: the 11 round-3 items other than the control, `[loop]` (`repr` writes the cycle), `[mixed]` (two loads repr alike), and the order test (round 3's re-read sees the revision; the order test pins B3's fingerprint-before-parse order against M21 and the base, not against round 3).
  - D1 on the round-2 candidate (staged tree `7c5052d6`, whose helper compares `current == item["_doc"]` after its `try`), kept as history: measured with round 3's test file, red the self-containing-frontmatter control (0 consolidations, 0 archived: `==` raised `RecursionError` into the whole-step handler, and beta's cluster was never processed) and the self-containing-frontmatter revision test (its count run consolidated nothing); the other 10 green.
  - D2 (`tests/test_bf932_d2_loop_stall_sampler.py`): collection error (`probos.utils.loop_stall` is missing), so every item is red. With 6.9 applied alone, `tests/conftest.py` imports `probos.utils.loop_stall` inside the fixture, so apply 6.9 only with 6.6.
  - D2 on the round-2 candidate (staged tree `9d3aad33`: the round-1 repair, whose `run()` still logs `AD-824: loop-stall heartbeat cancelled` at DEBUG in a `CancelledError` arm before its `finally`; with this revision's test file, 27 items): red, the new DEBUG-handler test only, at `stop_set_while_held == [True]`: `[False]`. The cancellation's DEBUG call waits for the handler lock the thread's WARNING holds, so the stop event is not set while the handler is held; the observer gives up after `_HELD_S` (10 s) and releases the handler, the DEBUG line is written, and only then is the stop event set (the test takes about 10 s there; the orchestrator's probe `logs/architect/inputs/probe-r2f1-output.txt`: stop event never set during a 3 s hold). There the new first assertion, `not signals.gate_expired`, passes: the observer releases the gate at about 10 s, inside the handler's 30 s guard. Every other item is expected green: the test file differs from round 2's only by this test, `_HELD_S`, `_Signals`'s docstring and its `gate_expired` flag (round 4). On the repaired candidate the observer sees the stop event at once (the probe: 0.005 s) and releases the handler; the item passes in well under a second.
  - D2, the DEBUG-handler test's guard (round 4, R3-F1): `_Signals.emit` sets `gate_expired` when its gate wait returns False (the 30 s `_GUARD_S` passed with the gate unset, so the handler returned and released its lock while the gate was still unset), and the test asserts `not signals.gate_expired` after its cleanup and before `stop_set_while_held == [True]`. A guard expiry is therefore a failure of the setup and cannot satisfy the property with a released lock. The round-3 reviewer's probe (a loop-thread stall of more than 30 s before the observer starts, with round 2's `CancelledError` arm put back) passed the round-3 test; it must now fail it, at `gate_expired`. No permanent test of the guard itself: it would need a stall of more than 30 s. The other two gate tests already turn red on an expiry and get no assertion: the held-in-a-logging-call test at `held_at_cancel is True`, the resume-gap test at its gap assertion; with the flag defaulting to False they pass as before.
  - D2 on the unrepaired candidate (sections 6.6-6.13 as committed in C1 `e535fd60`, with this revision's test file; 27 items): red, 8 items: the 7 below, and the DEBUG-handler test at `stop_set_while_held == [True]` (C1's `run()` has the same DEBUG line in the same arm). Measured on 26 items before round 2; the eighth is expected:
    - the resume-gap test, at the INFO assertion: it reads `resumed after 9000 ms` (the latest stamp, 109.0, minus the stalled one, 100.0), not `1250 ms`;
    - the shutdown-while-reading test, at the last assertion: one WARNING `... loop thread at: (frames read as shutdown began)` is written;
    - the failed-warning test, at the INFO count: 2 (the second stall inherits the first's `reported`);
    - the frame test, at `witness() is None`: the DEBUG record's `exc_info` keeps the traceback, whose `_NoStack.extract` frame holds the `walk_stack` generator and with it the loop thread's frame;
    - the threshold-refusal test `[inf]` and `[1e300]`: no `ValueError` (`not threshold_s > 0` passes both);
    - the failing-wait test, at `escaped == []`: the `OverflowError` leaves the thread through `threading.excepthook`.
    Green (19): the blocked-loop, turning-loop, runtime [1.0] and [0.0], second-run, closed-loop and bounded tests; the held-in-a-logging-call test (the unrepaired thread also ends when the handler returns and writes nothing more: it pins D2e, and kills N5); the threshold-refusal test `[nan]` (`not nan > 0` is true); the 4 accepts, 5 refuses and the default item. The turning-loop test now fails on a heartbeat that does not stamp (N20); the closed-loop test now ends its heartbeat task inside the test (its pending-task report goes to the loop's handler, asserted).
  - S1, first version (measured 2026-11-27 on the base plus the first version's test edits P23-P32, without P19-P22): 14 of the 35 tests in the four S1 files were red; with P19 alone, 5 (V1, G1, r1, r3, t4). Kept as history; the rows below replace it.
  - S1 repair (expected; the orchestrator measures). Trees: **B** = the base plus this revision's test pairs (P23-P28) and new file (6.20), without P19, P20, P37; **B19** = B plus this revision's P19 (the helper; the call site unchanged); **U** = the unrepaired first S1 candidate's source (sections 6.14-6.16 as committed in C1 `e535fd60`: the first P19-P22, with `_hook = "scheduled"` assigned before the call and the group round started, not awaited) plus this revision's test pairs and new file, with `tests/test_ad978_group_perception.py` at the base; **R** = the repaired candidate. The three S1 test files hold 22 tests (the new file 4, `test_bf932_reply_path_timing.py` 11, `test_dm_camera_hook_deadline.py` 7); `test_ad978_group_perception.py` is base-identical and is listed for U only.

    | Test | B | B19 | U | R |
    |---|---|---|---|---|
    | V1 (a stuck describe does not hold the reply) | red: guard timeout (the base awaits), then `AttributeError: ... '_SCENE_REFRESH_TASKS'` in its `finally` | red: guard timeout | green | green |
    | V3 (held until done, failure logged once) | red: `ImportError` (`refresh_scene_in_background`) | green | green | green |
    | V4 (cannot be started: `hook=failed`) | red: `AttributeError` in `_dm`'s drain (the route said `hook=ran`) | red at `hook == "failed"` (`ran`) | red at `hook == "failed"` (`scheduled`: F3) | green |
    | V5 (describe after the notification) | red: `AttributeError` in `_dm`'s drain (order was consumer, notify) | red at `order.index("notify") < order.index("consumer")` | green (a pin of the accepted F2 behaviour, not a discriminator against U) | green |
    | r1, r3 (`hook=scheduled`), t4 (`hook=scheduled`) | red: `AttributeError` in `_dm`'s drain | red at `hook == "scheduled"` (`ran`) | green | green |
    | r2, r4, r5, r6, r1b | red: `AttributeError` in `_dm`'s drain | green | green | green |
    | c1, c2, a1, a2, t1-t3, t5-t7 | green | green | green | green |
    | `test_ad978_group_perception.py::test_force_describe_called_once_when_enabled` | green | green | red at `force_calls == 1` (U's round starts the describe and returns before it runs) | green |

    Totals over the three S1 files: B 12 red (V1, V3, V4, V5, r1-r6, r1b, t4); B19 6 red (V1, V4, V5, r1, r3, t4); U 1 red (V4), plus the `test_ad978` row; R 0. The other two `force_describe` tests of `test_ad978_group_perception.py` on U are recorded as measured, not a criterion (one degrades with no assertion on timing; the end-to-end one awaits later steps of the round).
- On the candidate: every item of the three new files passes.

### 8.2 Focused checks on the candidate

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf932_d1_dream_yields.py tests/test_ad551_notebook_consolidation.py tests/test_dreaming.py tests/test_ad873_episode_decay.py tests/test_records_store.py tests/test_ad555_notebook_quality.py tests/test_ad563_knowledge_linting.py tests/test_ad564_quality_trigger.py tests/test_ad565_quality_routing.py tests/test_ad583_wrong_convergence.py tests/test_ad599_reflection_episodes.py tests/test_ad980b_dream_attribution.py tests/test_bf1002_full_dream_complete_event.py tests/test_bf940_s4_unparsed_frontmatter.py tests/test_bf958_records_link_containment.py tests/test_bf970_frontmatter_reading.py tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s5_continuous_promotion.py tests/test_ad1358_s1_head_to_head.py tests/test_episodic.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf932_d2_loop_stall_sampler.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2_config_models.py tests/test_ad1152_agentic_correlation.py tests/test_issue1419_failed_start_rollback.py tests/test_issue1452_stop_leftovers.py tests/test_ad824_shutdown_hygiene.py tests/test_ad741_config_api.py tests/test_ad741_integration.py tests/test_bf996_hxi_save_on_disk.py tests/test_layer_boundaries.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf932_s1_scene_refresh_background.py tests/test_bf932_reply_path_timing.py tests/test_dm_camera_hook_deadline.py tests/test_ad978_group_perception.py tests/test_ad733c1_force_describe.py tests/test_ad746a_force_describe_mirror.py tests/test_bf624_stale_meeting_vision_refresh.py tests/test_bf666_force_describe_cache_expiry.py tests/test_ad1031_camera_bid.py tests/test_wave171_acceptance.py tests/test_ad791a_chat_threads_wiring.py tests/test_bf266_vision_context_folding.py -n 0 -q
rg -l -g 'test_*.py' -e 'rglob\("\*\.py"\)' -e 'os\.walk\(' -e 'glob\("\*\*/\*\.py"\)' -e 'cognitive/dreaming\.py' -e '"dreaming\.py"' -e 'records_store\.py' -e 'cognitive/episodic\.py' -e '"episodic\.py"' -e 'perception/consumer\.py' -e 'routers/agents\.py' -e '"agents\.py"' -e 'thread_fanout\.py' -e '"runtime\.py"' -e '/runtime\.py' -e 'config_models/core\.py' -e '"core\.py"' -e 'utils/step_timing' tests
d:/ProbOS/.venv/Scripts/pytest.exe <each file the rg command lists> -n 8 -q
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-932-batch1
```
S1 repair: line 3 is unchanged; `tests/test_ad978_group_perception.py` stays in it as a control (its source and test file are base-identical), and `test_ad733c1_force_describe.py` mirrors the hook block without reading `agents.py`'s text (:227-238). The config tests of line 2 and the two `--check` lines cover P37's generated files. The `rg` pattern listed 117 files on the base (the Grep tool, same pattern, glob `test_*.py`, over `tests/`). The three `pytest` lines name the consumers it does not list. Retriage a parallel failure at `-n 0`. The D2 repair adds no consumer file: the child-process consumers of D2d (the six `test_ad1198_*_gate.py` files, `test_ad1137_quickstart_chain.py`) ran the real sampler on the first D2 candidate as well, and they run in the gate (8.4).

D1, Step 7g's load-site fingerprint and publication checks (P38, P2, P35, P36): only two test files reach them, `tests/test_ad551_notebook_consolidation.py` (mock store) and the new D1 file (a real `RecordsStore` driven through `dream_cycle`, and the mock store of `_run_dream`, which is AD-551's). The mock store is `AsyncMock()` (`test_ad551_notebook_consolidation.py`:27) with no `entry_fingerprint` of its own, so the attribute is an auto-created `AsyncMock` child: awaited, it returns the same `return_value` object on every call, so the load's `fp` is not `None` and every check finds `fp == item["_fp"]` (identity equality), and the AD-551 suite and the D1 output and turns tests read every note as unchanged with no edit. No Step 7g-reaching store is a plain `MagicMock` (whose `entry_fingerprint` would not be awaitable): the step 7e and 7f tests set `_records_store = None` (`test_dream_step_7e.py`:108, `test_dream_step_7f.py`:69), so Step 7g does not run there; the `MagicMock()` stores of `test_bf106_dreaming_di.py`, `test_procedure_store.py`, `test_ad594c_parallel_dispatch.py` and `test_ad562_finalize_wirer.py` are not driven through `dream_cycle`'s Step 7g (and on such a store `await list_entries(...)` would already raise into the whole-step handler at the base, :932). The brake decision's premise that the D1 file holds mock-driven staleness tests (at its :95 and :112) does not hold: those lines are `_run_dream`'s turn-counting wrapper (`reader = store.read_entry.side_effect`, `store.read_entry.side_effect = _read`), which simulates no revision; every staleness test was already on the real store. `tests/test_ad1341_s5_continuous_promotion.py` stays in the first line as a `dream_cycle` consumer only: its engine is built with `DreamingEngine.__new__` and no records store (:432-438), two calls replay no episode and the third raises at the prune (:455-459), so it never enters Step 7g (round 2, F2). No booted-runtime test is added for the checks: D1 changes neither how the records store is wired into the engine nor any startup file, and the on-disk tests run the real Step 7g over a real store.

### 8.3 Mutation rows (one at a time on the candidate, the file restored byte for byte; one campaign of record)

Each locator is a whole stripped line of the candidate. Where a line occurs more than once, the ordinal is given.

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| M1 | `dreaming.py`: `if pair_pacer.due():` (1st of 3) | `if False:` | 7g turns (alpha segment) |
| M2 | `dreaming.py`: `if pair_pacer.due():` (2nd of 3) | `if False:` | 7g turns (cross segment) |
| M3 | `dreaming.py`: `if pair_pacer.due():` (3rd of 3, coherence) | `if False:` | 7g turns (coherence segment: 2,016 pairs, 0 turns) |
| M4 | `dreaming.py`: `_STEP_7G_PAIRS_PER_YIELD = 2000` | `_STEP_7G_PAIRS_PER_YIELD = 10**9` | 7g turns |
| M5 | `dreaming.py`: `if read_pacer.due():` (1st of 4) | `if False:` | 7g turns (alpha reads) |
| M6 | `dreaming.py`: `if read_pacer.due():` (3rd of 4) | `if False:` | 7g turns (cross reads) |
| M7 | `dreaming.py`: `if read_pacer.due():` (4th of 4) | `if False:` | 7g turns (cross word sets) |
| M15 | `dreaming.py`: `if read_pacer.due():` (2nd of 4, per-agent word sets) | `if False:` | 7g turns (alpha word sets, the last assertion) |
| M16 | retired in round 4: its line (`return repr(current) == repr(item["_doc"])`) no longer exists; the always-True mutant of the helper's new return line is M20 | | |
| M19 | retired in round 4: its mutant (`return current == item["_doc"]`) compared loaded documents, which the helper no longer does; the type-domain property it guarded is pinned by the four unchanged controls (M24) and the NaN-set recheck test | | |
| M17 | `dreaming.py`: `if stale:` | `if False:` | revision [primary] (`lost == [4, 5, 6, 7, 8, 9]`), stale-cluster test, order test (1 consolidation), containment test (2 consolidations) |
| M18 | `dreaming.py`: `if not await _reads_as_loaded(self._records_store, other):` | `if False:` | revision [member] (`lost == [10, 11]`) |
| M20 | `dreaming.py`: `return fp is not None and fp == item["_fp"]` | `return True` | revision [primary] (`lost == [4, 5, 6, 7, 8, 9]`), revision [member], stale-cluster test, self-containing-frontmatter revision test, order test, changed-readings [write_entry], [publish], [rename], [delete] |
| M21 | `dreaming.py`: `fp = await self._records_store.entry_fingerprint(ent["path"])` | the line moved to just after the `read_entry` call's closing `)` line, at the same indentation (the fingerprint taken after the parse) | order test (`notebook_consolidations == 0`: 1; the revision is overwritten by the cached copy) |
| M22 | `records_store.py`: `return hashlib.sha256(file_path.read_bytes()).hexdigest()` | `return hashlib.sha256(path.encode()).hexdigest()` | changed-readings [write_entry], [publish]; revision [primary], [member]; stale-cluster test; order test |
| M23 | `dreaming.py`: `fp = await records_store.entry_fingerprint(item["path"])` | the line moved to just before the helper's `try:`, at the function's indentation (the call outside the `try`) | containment test (`notebook_consolidations == 1`: 0; the raise at alpha's check reaches the whole-step handler, which logs `Step 7g notebook consolidation failed`, and beta's cluster is never processed) |
| M24 | `dreaming.py`: `loaded.append({**ent, "_content": doc.get("content", ""), "_doc": doc, "_fp": fp})` | the same without `, "_fp": fp` | the four unchanged controls (0 consolidations: each check's `KeyError` is contained and counts as changed), the on-disk control, the step 7g output test (`consolidated == []`) |
| M8 | `dreaming.py`: `words_j = entry_words[j]` | `words_j = entry_words[i]` | 7g output (alpha becomes one cluster of 100) |
| M9 | `dreaming.py`: `words_j = cross_words[j]` | `words_j = cross_words[i]` | 7g output (one component of all notes; coherence differs) |
| M10 | `dreaming.py`: `member_words = [cross_words[idx] for idx in component]` | `member_words = cross_words[: len(component)]` | 7g output (coherence) |
| M11 | `records_store.py`: `pacer = None if strict else LoopYield(_LIST_FILES_PER_YIELD)` | `pacer = None` | default listing |
| M12 | same line | `pacer = LoopYield(_LIST_FILES_PER_YIELD)` | strict listing |
| M13 | `episodic.py`: `if pacer.due():` | `if False:` | decay sweep |
| M14 | `loop_yield.py`: `if self._count >= self._every:` | `if self._count > self._every:` | `LoopYield` test |
| N1 | `loop_stall.py`: `if age_s > self._threshold_s:` | `if age_s > self._threshold_s * 1000.0:` | D2 blocked loop (guard), D2 bounded warnings (guard), D2 resume gap (guard) |
| N2 | `loop_stall.py`: `frames = _innermost_frames(loop_thread_id, _STACK_DEPTH)` | `frames = _innermost_frames(threading.get_ident(), _STACK_DEPTH)` | D2 blocked loop (the line names `_watch`; guard), D2 resume gap (guard) |
| N3 | `loop_stall.py`: `if reported:` | `if False:` | D2 blocked loop (resume guard), D2 resume gap (guard), D2 bounded warnings, D2 failed warning (0 INFO) |
| N4 | `loop_stall.py`: `self._warnings = _WarningBudget(max_warnings, window_s)` | `self._warnings = _WarningBudget(0, window_s)` | D2 bounded warnings (3 WARNINGs) |
| N5 | `loop_stall.py`: `self._stop.set()` | `pass` | D2 second run (thread alive after the cancel), D2 held in a logging call (the thread outlives the handler; join guard), D2 DEBUG handler at cancel (`[False]`) |
| N6 | `loop_stall.py`: `if self._thread is not None and self._thread.is_alive():` | `if False:` | D2 second run (two threads) |
| N7 | `loop_stall.py`: `return self._stop.is_set() or loop.is_closed() or (self._active is not None and not self._active())` | `return self._stop.is_set() or (self._active is not None and not self._active())` | D2 closed loop (join guard) |
| N8 | `loop_stall.py`: `target=self._watch, args=(loop, threading.get_ident()), name=THREAD_NAME, daemon=True,` | the same with `daemon=False,` | D2 second run (`daemon is True`) |
| N9 | `runtime.py`: `if _loop_stall_s > 0:` | `if _loop_stall_s >= 0:` | D2 runtime [0.0] |
| N10 | `runtime.py`: `active=lambda: not self._shutdown_started,` | `active=None,` | **not killed**: the AD-824 sweep also ends the thread; the predicate only keeps shutdown's own stalls out of the log (the shutdown-while-reading test drives `active` directly, not through the runtime) |
| N11 | `core.py`: `if 0.0 < value < 0.1:` | `if False:` | D2 threshold refuses [0.05] |
| N12 | `loop_stall.py`: `if self._ended(loop):` (2nd of 2, after the frames are read) | `if False:` | D2 shutdown while reading (one WARNING) |
| N13 | `loop_stall.py`: `self._resume_gap_s = now - self._last_beat` | `self._resume_gap_s = 0.0` | D2 resume gap (`resumed after 0 ms`) |
| N14 | `loop_stall.py`: `if self._last_beat == self._stalled_beat:  # the first beat after the stall the thread found` | `if self._stalled_beat is not None:` | D2 resume gap (the latch follows every beat while armed, so it ends at `0 ms` or `7750 ms`, never `1250 ms`) |
| N15 | `loop_stall.py`: `reported = False` (2nd of 2, after `self.stall_count += 1`) | (line deleted) | D2 failed warning (2 INFO) |
| N16 | `loop_stall.py`: `logger.debug("BF-932: a loop-stall check failed and was dropped: %s", repr(error))` | the same with `, exc_info=error` before the closing parenthesis | D2 failed stack read (`witness()` alive) |
| N17 | `loop_stall.py`: `del frame  # on every path: the sampled frame holds the loop thread's locals` | `pass` | **not killed**, recorded: on the success path the frame local dies with the function's return a line later, and on a failure the traceback that would keep it is no longer logged (N16). The `finally` keeps the local's lifetime to the read on every path; it is not observable from outside |
| N18 | `loop_stall.py`: `if not 0.0 < threshold_s / 4.0 <= threading.TIMEOUT_MAX:` | `if not threshold_s > 0:` | D2 threshold refusal [inf], [1e300] |
| N19 | `loop_stall.py`: `_drop(error)` (2nd of 2, the outer guard) | `raise` | D2 failing wait (`escaped` is not empty) |
| N20 | `loop_stall.py`: `self._last_beat = now` | `pass` | D2 turning loop (a WARNING), D2 resume gap (guard) |
| N21 | `loop_stall.py`: `finally:  # nothing on the cancellation path logs before the stop event is set` | the same line with three lines inserted before it at its indentation: `except asyncio.CancelledError:`, then one level deeper `logger.debug("AD-824: loop-stall heartbeat cancelled")` and `raise` (round 2's arm) | D2 DEBUG handler at cancel (`[False]`, after `_HELD_S`) |
| S1M1 | `agents.py`: `refresh_scene_in_background(_consumer, timeout_s=4.0)` | `await _consumer.force_describe_current_frame(timeout_s=4.0)` | V1 (guard), V5 (consumer before notify) |
| S1M2 | removed (the group call site is no longer changed) | | |
| S1M3 | `consumer.py`: `_SCENE_REFRESH_TASKS.add(task)` | (line deleted) | V3 |
| S1M4 | `consumer.py`: `_SCENE_REFRESH_TASKS.discard(task)` | (line deleted) | V3 |
| S1M5 | `consumer.py`: `logger.warning("BF-932: background scene refresh failed: %r", error, exc_info=error)` | the same with `logger.debug(` | V3 |
| S1M6 | `consumer.py`: `task = asyncio.get_running_loop().create_task(consumer.force_describe_current_frame(timeout_s=timeout_s))` | the same with `timeout_s=4.0` | V3 (`seen == [2.5]`) |
| S1M7 | `agents.py`: `_hook = "scheduled"  # BF-932: log-only; set once the describe is started` | `_hook = "ran"` | V1, r1, r3, t4 |
| S1M8 | `agents.py`: `_hook = "failed"  # BF-932: log-only; starting the describe raised, nothing runs` | `pass` | V4 (`skipped`) |
| S1M9 | same line | `_hook = "scheduled"` | V4 (`scheduled`: the first candidate's F3) |
| S1M10 | `consumer.py`: `task = asyncio.get_running_loop().create_task(consumer.force_describe_current_frame(timeout_s=timeout_s))` | `task = asyncio.eager_task_factory(asyncio.get_running_loop(), consumer.force_describe_current_frame(timeout_s=timeout_s))` | V5 (the describe runs to its first await inside the call, before the notification) |

Mark the run that executes this table as the campaign of record (base tree and each edited file's sha256); a later candidate whose edited files match does not repeat it.

D2 repair (round 1): `loop_stall.py` and `tests/test_bf932_d2_loop_stall_sampler.py` change, so rerun N1-N8 and N12-N20 on the repaired candidate. N9-N11 carry over from the first D2 campaign when `runtime.py` and `core.py` match its sha256 apart from P14's comment (N9 and N10's lines are byte-identical; their killers, the runtime and threshold tests, are unchanged). Rows rewritten because their line changed: N2 (`frames = ...`), N7 (now `_ended`'s return). Rows whose killers were weak and now have a second killer: N1, N2, N3 (the resume-gap test; N3 also the failed-warning test), N5 (the held-in-a-logging-call test). New: N12-N20; expected killed except N17 (recorded with its reason). With N10, the table has two recorded survivors.

D2 repair (round 2): `loop_stall.py` changes by three deleted lines (the `CancelledError` arm), a comment on the `finally` line and module-docstring text; the test file gains one test, `_HELD_S` and `_Signals`'s docstring. Rerun every `loop_stall.py` row (N1-N8, N12-N21) on the repaired candidate. Every locator's text is unchanged except the line N21 names, which is new; N5 has a third killer (the new test). N9-N11 carry over when `runtime.py` and `core.py` match the round-1 campaign's sha256. Expected: N21 killed; the rest as before (N10 and N17 the recorded survivors).

D2 repair (round 4, R3-F1): only the test file changes (`_Signals` gains `gate_expired`; the DEBUG-handler test gains one assertion before `stop_set_while_held == [True]`); `loop_stall.py`, `runtime.py` and `core.py` are unchanged from the round-3 candidate. Rerun only the rows the DEBUG-handler test kills: N21 (its sole killer) and N5 (its third killer). N1-N4, N6-N8 and N12-N20 stand from the D2 round-2 repair's campaign (above), and N9-N11 as before: production is unchanged, so a row's result can differ only where the changed test is its killer. Expected: N21 and N5 killed, the DEBUG-handler test failing at `stop_set_while_held == [True]` (`[False]`), not at `gate_expired` (the observer releases the gate at `_HELD_S`, 10 s, inside the 30 s guard). No row's text changes.

S1 repair (round 1): `agents.py`, `consumer.py` (comment and docstring only) and the S1 test files change, so the S1 rows run on the repaired candidate as one campaign. Removed: S1M2 (its file is base-identical). Changed: S1M1 (second killer V5), S1M7 (its locator: the assignment moved after the call and its comment changed). Unchanged lines and killers: S1M3-S1M6. New: S1M8 and S1M9 (the `failed` label), S1M10 (the post-notification order of F2). The post-return position of `_hook = "scheduled"` has no row of its own: with S1M8 and S1M9 killed, an assignment of `scheduled` before the call is overwritten by the `except` branch, so moving it is an equivalent mutant. Expected: every S1 row killed.

D1 repair (round 1): `dreaming.py` and `tests/test_bf932_d1_dream_yields.py` change, so rerun M1-M10 and M15-M18 on the repaired candidate. M11-M14 carry over from the first D1 campaign when `records_store.py`, `episodic.py` and `loop_yield.py` match its sha256 (their killers, the listing, decay and `LoopYield` tests, are byte-identical in the new test file). Expected: every D1 row killed (M3 now included); N10 stays the one recorded survivor of the table.

D1 repair (round 2): `dreaming.py` changes only in P2's helper and the test file gains two tests, three constants and `_seed_notes`'s and `_consolidate_on_disk`'s optional parameters (each defaulting to the round-1 behaviour). Rerun M16-M19 on the repaired candidate. M1-M10 and M15 carry over from the round-1 campaign when `git diff` between the two candidates' `dreaming.py` shows only P2's helper hunk and their killers (`_fixture`, `_run_dream`, the 7g turns and output tests) are byte-identical; M11-M14 carry over as before. The round-2 candidate itself (comparison after the `try`) is not a row: it is 8.1's A/B. The helper's `except` arm (`return False`) is unchanged from round 1 and has no row: under `repr` it runs only when the re-read raises (the round-2 reviewer probed it: (0, 0) before publication, (1, 1) at a member check). Expected: every D1 row killed. (Corrected in round 4, R3-F3: under `repr` the arm also ran when `repr` raised, an accepted alias chain's `RecursionError`, and no D1 item failed when the comparison was moved out of the `try`. Round 4's containment test and M23 pin the containment.)

D1 repair (round 3, B3; the campaign of record for D1): `dreaming.py` (P2's helper, P38), `records_store.py` (P39, P40) and the whole D1 test file change. Rerun M1-M15, M17, M18 and M20-M24 on the repaired candidate: M11 and M12 too, because `records_store.py` changed (their lines and their killers, the listing tests, are unchanged); M13 and M14 carry over from the first D1 campaign when `episodic.py` and `loop_yield.py` match its sha256. M16 and M19 are retired with their reasons (their ids are not reused). Not rows, recorded as equivalent: the helper's `fp is not None` (P38 records only a non-`None` fingerprint, so `fp == item["_fp"]` alone already rejects `None`); P38's `fp is not None` guard (a missing file also makes `read_entry` return `None`, :1501-1502); `entry_fingerprint`'s `exists()` test (without it a missing file raises `FileNotFoundError`, which both call sites contain and count as changed or dropped). Expected: every D1 row killed; N10 and N17 stay the table's recorded survivors.

### 8.4 The gate

`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-932-batch1 --receipt logs/gates/bf-932-batch1.receipt.json` once on the committed head, after merging the base.

## 9. Diff Reviewer: properties to verify

Batch 1: properties 1-14 apply, with the (S1) clause of the change claim and properties 7 and 15-18 deferred to batch 2. In their place, for batch 1: `perception/consumer.py`, `routers/agents.py`, `routers/thread_fanout.py`, `config.py`, `tests/test_bf932_reply_path_timing.py`, `tests/test_dm_camera_hook_deadline.py` and `tests/test_ad978_group_perception.py` are byte-identical to the base, and `docs/development/config-reference.md` and `docs/development/config-facade-baseline.yaml` carry only 4a's diff.

The change claims: (D1) the dream's notebook and decay loops await `asyncio.sleep(0)` every fixed count of units, with identical output when no note changes during the step, and Step 7g overwrites or archives no note revised after its read; (D2) a heartbeat and a daemon thread log one WARNING naming the loop thread's frames per stall and one INFO per resume, on by default, off at 0; (S1) the DM route starts the describe without awaiting it and says `hook=failed` when it could not; the group round is unchanged. Consumers that must accept it: `DreamingEngine.dream_cycle`'s report and events; `RecordsStore.list_entries`'s callers (strict and default); `ProbOSRuntime.start` and `shutdown()`; the DM route's `BF-932: dm route` line and the agent's reply.

1. In Step 7g every comparison, read and word set of the base still happens, in the base's order; the additions are the counters, the `await asyncio.sleep(0)` lines, the precomputed word sets (per agent and cross-agent, each built in a loop paced by `read_pacer`) and the publication checks of property 11; `member_words[ci]` equals `text_to_words(cluster_entries[ci]["_content"])`.
2. `list_entries(strict=True)` executes no `await`; the default mode returns the same list.
3. `sweep_episode_decay` keeps each episode's get and update adjacent (no turn between them).
4. `loop_stall.py` and `loop_yield.py` import the standard library only, no `probos` module (`test_layer_boundaries.py` lets a utils module import foundation modules, :35-37, and other utils modules, :42, but no other layer, :55; other utils modules do import `probos.types` and `probos.utils`); nothing raised in the thread leaves it, the wait included (the inner `except Exception` per check, the outer one around the loop); a failed check is logged with `repr(error)` and no `exc_info`, so no log record keeps a traceback and with it a sampled frame; `_innermost_frames` drops its frame local in a `finally`; `lookup_lines=False`; the constructor refuses a threshold whose quarter is not in (0, `threading.TIMEOUT_MAX`].
5. `run()`'s `finally` sets the stop event and joins with a timeout; `run()` has no `CancelledError` arm, the cancellation propagates through the `finally`, and no statement on the cancellation path logs (or otherwise takes a handler lock) before `self._stop.set()` (R2-F1; the DEBUG-handler test and N21 pin it). That test fails its setup, at `not signals.gate_expired`, when the held handler's 30 s guard expires, so a lock released by the guard cannot satisfy it (R3-F1). The text claims no exit bound and no independence from handler locks beyond D2e (4): the sampler's only wait of its own on the loop thread is the bounded join (R2-F2). D2e holds as written: no WARNING is written whose frames were read after `_ended` turned true (the re-check sits between `_innermost_frames` and `_warnings.emit` with no other statement between); the join is bounded; a thread inside a logging call at the join ends when that call returns and writes nothing more.
6. `start()` still ends with `self._startup_complete = True`; the sampler is spawned through `_spawn_background` and only when the field is above 0. In the pytest process every booted runtime runs the no-op unless the test requests the live fixture; a runtime booted in a child process runs the real sampler (D2d), and no parent reads a child's output for a WARNING's absence.
7. `refresh_scene_in_background` holds each task in `_SCENE_REFRESH_TASKS` until done and logs a failure once; BF-977's `force_describe_current_frame` is byte-identical to the base. The S1 text claims no shutdown bound: `timeout_s` bounds the describe a caller waits on, not a cancelled refresh, which waits for BF-977's step (S1e).
8. Each edited test keeps its other assertions and records its reason inline; nothing is deleted.
9. No file of the scope boundary changes; `step_timing.py` and `config/system.yaml` are byte-identical to the base.
10. ASCII and LF in the new hand-written text (generated files exempt: U+2265 and U+2264 in the generated `config-reference.md` row); each absolute word (every, each, no, only, none, never) holds against sections 1, 3a, 7 and the Absence Verified list.
11. Step 7g writes a cluster's consolidated note only when every member's `entry_fingerprint` equals the one taken at its load (`item["_fp"]`), and renames a member into `_archived` only when that member's still does. At the load the fingerprint is taken before `read_entry` (M21, the order test) and recorded only for a truthy document and a non-`None` fingerprint. In the helper the call and the comparison share one `try`, so a raise counts as changed, is logged at DEBUG and never reaches the whole-step handler (the containment test, M23); later clusters are still processed. `entry_fingerprint` has no `await`; between the load's fingerprint and its parse, and between each check and its write or rename, no statement suspends (`write_entry` has none before `write_text`, `records_store.py`:856-860); verify with a real-store coroutine that completes without suspending. The four unchanged controls reach base parity (2 consolidations, 4 archived) on a real store; a real `write_entry`, `publish`, rename away and deletion each read as changed. `entry_fingerprint` is additive: no other `RecordsStore` method changes, and it has no caller outside Step 7g. A skipped cluster writes, archives and counts nothing; a member left live is not counted as archived. With no concurrent writer, the output equals the base's (the on-disk control). The contract no longer claims a `repr` or `.nan` property.
12. The revision test injects at every turn the step gives (each Step 7g `sleep`, the consolidation write's return, each archive `git add -A`), for the primary and for a non-primary member, and no injection is lost.
13. The resume INFO's number is the gap of the first heartbeat after the stall, whenever the thread logs it: the thread arms `_stalled_beat` in the same locked block in which it read the stamp and found it stale, and the heartbeat records `now - _last_beat` in the same locked block in which it replaces that stamp. Nothing under the lock logs, reads frames or waits (so the heartbeat never waits on logging through this lock; the loop thread's own log calls are not covered by this property: D2e (4)). `reported` is False for every new stall until its WARNING is written, so a stall whose report failed gets no INFO. The two log formats are byte-identical to the first candidate's.
14. Every D2 test that starts a heartbeat ends it inside the test on every path (`_stop` or `rt.stop()` in a `finally`; the closed-loop test destroys its pending task with `gc.collect()` in its `finally`, reported to its own loop's handler); each new or changed D2 test fails on the unrepaired candidate as 8.1 says, or is named there as a control.
15. S1, the route line: `_hook` is `scheduled` only on the path where `refresh_scene_in_background` returned, `failed` on every path where the `try` raised (the import included), and `skipped` when the hook did not run; no other assignment of `_hook` exists between :2967 and the route line.
16. S1, ordering: between the helper's return and `_mode_ctrl.note_dm_activity()` no statement awaits, so the started task first runs after the notification (S1c, accepted); V5 pins it.
17. S1, scope: `routers/thread_fanout.py` and `tests/test_ad978_group_perception.py` are byte-identical to the base; the group round still awaits the describe. No visual binding is added to the DM path (`visual_attachment_ref=` stays only at `thread_fanout.py`:1141).
18. S1, wording: no comment, docstring, config description or tracker line says the fresh description is there "for the next turn"; each says it is present once the describe lands in working memory, or that an immediate second DM may still get the sentinel. P37 changes only the comment and `description` of `dm_force_describe_enabled`, and the generated files change as 4b says.

## 10. Verified Against Codebase (2026-11-27, tree `63c536b3`)

Batch 1: the S1 entries below (`consumer.py`, `agents.py`, `thread_fanout.py`, `config.py`, the S1 test files) support batch 2's sections and are kept for it. Re-verified for the batch-2 design (2026-11-27, C1 `e535fd60`): `thread_fanout.py`:386 `async def _maybe_force_describe_frame`, :406 the awaited describe, :1022 its one call, :1086 the late `latest()` read, :1141 `visual_attachment_ref=_visual_ref`; `consumer.py`:481 `_force_describe_permit`, :755 `force_describe_current_frame`, :782 (docstring: calls made while the permit is held return `None` at once), :829 `async with self._force_describe_permit()`; `agents.py`:3491 `_hook = "ran"`, :3712 the route line's `hook=%s hook_ms=%.0f`.

- `dreaming.py`: `import asyncio` :10; similarity import :19; `from probos.types import (...)` :50-57, `if TYPE_CHECKING:` :59; `logger` :62; `_outcome_evidence` :65; `_get_importance_map` :310-327 (one bulk `_collection.get` :315); `dream_cycle` :420 (`recent(k=...)` :475; Steps 2-5 :486-512; Step 6 :514-572); Step 7f2 :903-922 (`sweep_episode_decay` :911); Step 7g :924-1229 (listing :932; threshold :941-942; per-agent loop :944, reads :949-957, `n = len(loaded)` :961, pairs :963-970, BFS :974-989, write :1012, archive rename :1025, `_git` :1027; cross reads :1063-1075; pairs :1077-1088; BFS :1090-1102; `cluster_entries` :1103; coherence :1107-1116; `word_sets` :1130; report write :1145); Step 7i :1256-1303 (`max_pairs_per_run` :1282); Step 9 :1393-1431; Step 10 :1433-1520; Step 12 :1564-1669 (`count()` :1584).
  `Grep "jaccard_similarity\(|text_to_words\(" dreaming.py` -> :964, :966, :967, :1080, :1084, :1085, :1111, :1113, :1114, :1130.
- `similarity.py`:4-19 (`jaccard_similarity` allocates `a | b` per call; `text_to_words` is `set(text.lower().split())`).
- `records_store.py`: `import asyncio` :3; frontmatter import :20; `_RECORDS_YAML_LOADER` :279; `_markdown_files` :606; `__init__` :680-693; `read_entry` :1485-1526 (`read_text` :1504, `_load_document` :1505; no `await`); `list_entries` :1528-1610 (`found` :1569, loop :1571, read :1584-1585, entry keys :1605; no `await`); `_safe_path` :1861-1872; `_git` :1893-1896.
- `episodic.py`: `import asyncio` :10, `import time` :18; types import :63; `logger` :65; `__init__` :1394; `update_episode_metadata` :2482-2511 (no `await`); `sweep_episode_decay` :2609-2694 (page via `asyncio.to_thread` :2640; loop :2670-2692).
- `notebook_quality.py`:217; `knowledge_linter.py`:58, :76-101.
- `perception/consumer.py`: `import asyncio` :20; `Any` :26; `logger` :39; `_log_abandoned_force_describe` :55-71; comment :74, `_WORKING_MEMORIES` :77; `force_describe_current_frame` :755-821 (single flight :781-782).
- `routers/agents.py`: `_hook = "skipped"` :2967; hook block :3479-3500 (`await` :3494); render :3519-3525; route line :3710-3717 (fields `thread_ms prep_ms hook hook_ms dispatch_ms send_ms total_ms sent`).
- `routers/thread_fanout.py`: `_maybe_force_describe_frame` :386-410 (`await` :406).
- `cognitive_agent.py`:7689-7698 (`BF-932: dm turn ... perceive_ms recall_ms`); `concurrency_manager.py`:235 (`AD-672: Promoted queued intent ... waited_ms`).
- `perception/working_memory.py`:124-134 (sentinel); `config.py`:2311 (`dm_force_describe_enabled` default True), :2320 (`prompt_freshness_seconds` 120.0), :3911 (`system: SystemInfo`); `config_models/core.py`:13 (imports), :153-158 (`SystemInfo`).
- `runtime.py`: `_background_tasks` :1554; `_shutdown_started` :1588; `start` :2804; SQLite backup spawn :3827-3831; `_startup_complete` :3836; `_spawn_background` :4022-4080. `startup/shutdown.py`: `_shutdown_started = True` :921; drain :1337-1365; AD-824 sweep :1373-1399.
- `__main__.py`:922-931 (heartbeat: `asyncio.sleep(60)`, `runtime alive ... uptime=`).
- Tests: `test_ad1270e1_config_facade.py`:1577-1578; `test_ad1270e2_config_models.py`:63, :221-225; `test_ad1152_agentic_correlation.py`:54-61 (rule for an added field), :350; `test_bf932_reply_path_timing.py`:20, :76-88, :91-124, :127-129, :143-145, :171, :180; `test_dm_camera_hook_deadline.py`:41, :298; `test_ad978_group_perception.py`:50, :99-106, :259-266, :270-280, :315-318; `test_ad551_notebook_consolidation.py`:25-101; `test_issue1419_failed_start_rollback.py`:150-164; `tests/conftest.py`:182-206; `tests/fixtures/runtime_lifecycle.py`:144-156.
- `pyproject.toml`:9 (`requires-python = ">=3.12"`); `scripts/check_config_profiles.py`:166-171; `scripts/check_config_facade.py`:1711, :1716 (`--check`, `--update-baseline`).
- Live data: `probos.log.1` lines quoted in section 1 (Grep `^2026-10-25 19:2(8:(39|[45][0-9])|9:(0[0-9]|1[0-9]))`, `^2026-10-30 23:4(0:(4[5-9]|5[0-9])|1:0[0-9])`, `runtime alive` by window). Glob `notebooks/*/*.md` under `ship-records`: 2,777; `notebooks/*/_archived/**/*.md`: 0. `config/system.yaml`:219 (`idle_threshold_seconds: 300.0`), :221 (`replay_episode_count: 50`), :228-233 (AD-551 settings at their defaults).

Added for the D1 repair (2026-11-27; source at `e535fd60` equals `63c536b3`: `git diff --stat 63c536b3 HEAD -- src tests` prints nothing):
- `dreaming.py`: `loaded.append({**ent, "_content": doc.get("content", ""), "_doc": doc})` :955; clusters :991; `cluster_items.sort` :997; `consolidated` :1007-1010; `# Write consolidated entry` :1011; `write_entry(... message=f"AD-551: Consolidated ...")` :1012-1017; `# Archive non-primary entries` :1018; `for other in others:` :1019; rename :1025; `_git("add", "-A")` :1027; `notebook_entries_archived += 1` :1030; `notebook_consolidations += 1` :1033; convergence report path `convergence-{ts_slug}.md` :1134-1135 (R-e).
- `records_store.py`: `_load_document` :309-323 (the body is `rest.strip()`, :323); `__init__` :680-693 reads only `config.repo_path` (the tests' `SimpleNamespace(repo_path=..., auto_commit=False)` store; `auto_commit` is read at :859); `write_entry` :722-880 (revision bump :819-820, `updated` :803, `write_text` :856, first `await` :860 only when `auto_commit`, indexer :870-872); `read_entry` returns `{"frontmatter", "content", "path"}` :1526.
- `config_models/cognition.py`:110-115 (threshold 0.6, min entries 2, convergence 0.5, 3 agents, 2 departments); `similarity.py`:14 (`len(a & b) / len(union)`).
- `tests/test_ad551_notebook_consolidation.py`:30-34 (`_read_entry` returns the same `read_map` object on every call, so a re-read compares equal), :48-84 (`_make_engine`).
- `recreation/history.py`:184-185 (strict listing, multi-line); `knowledge_linter.py`:76-101 (`_check_inconsistencies`); `tests/test_layer_boundaries.py`:35-37, :42, :55.
- Live (orchestrator, `logs/architect/inputs/live_lint_pairs.py`, 2026-11-27, counts only): 16 agents, 2,777 notes, 2,548 distinct topics, largest same-topic group 8, 348 linter pairs.
- Orchestrator's probe `logs/architect/inputs/probe_p1_stale_publish.py` (base vs first candidate, writer at the first turn after the three reads): base primary revision 3 holds the revision text; candidate revision 3 holds the consolidated body only; no-writer runs identical.

Added for the D1 repair after review round 2 (2026-11-27, worktree at `e535fd60`; reviewer's report `logs/architect/inputs/review-d1-round2.txt`):
- `utils/frontmatter.py`:61-63 (an alias opens no depth; `FRONTMATTER_DEPTH_LIMIT = 64`), :91 (`load_frontmatter(block, loader=yaml.SafeLoader)`); `records_store.py`:279 (`_RECORDS_YAML_LOADER`, used by the search's first pass only), :309-323 (`_load_document`: `load_frontmatter(block)`, the PyYAML safe loader, for every `read_entry`).
- `records_store.py` `write_entry`: :797-804 (a fresh frontmatter dict each write: `author`, `classification`, `status`, `created`, `updated = now`), :817-820 (only `created` and `revision + 1` carried; :826-829 `classification` when asked), :847-848 (`extra_frontmatter`). So a revision of the self-containing test note drops its `loop` key, and every write changes `updated` and `revision`.
- `dreaming.py`: Step 7g groups by the path's second segment (:935-939); `notebook_entries_archived` reaches `DreamReport` (:1800); the whole-step handler is :1228-1229 at the base (`except Exception as e:` / `logger.debug("Step 7g notebook consolidation failed (non-critical): %s", e)`, closing the `try` of :929; the reviewer's :1299-1300 on the candidate).
- `records_store.py`:606 `_markdown_files` (the listing's walk; its order is not asserted by the new control: 8.1 states the round-2 failure as the reviewer measured it).
- `tests/test_ad1341_s5_continuous_promotion.py`:432-438 (`_engine`: `DreamingEngine.__new__`, `episodic_memory.recent` returns `[]`, no records store), :444-459 (three `dream_cycle` calls; the third raises `PastTheStep` from `_prune_weights`).
- `tests/test_ad1358_s1_head_to_head.py`:369-396 (counting `read_spy`, `calls["read"] == 0` / `== 3`), :493-512, :686-699.

Added for the D2 repair (2026-11-27, worktree at `e535fd60` with the D1-repaired contract; the D2 source cited is this contract's first 6.6 block as committed in C1, which the orchestrator read against each finding):
- First candidate's `loop_stall.py` (reviewer's line numbers): heartbeat stamp :126; `run()`'s `finally` join :133; stop wait :139, outside the `try`; activity check :142; frames and emit :155-163; constructor check `not threshold_s > 0` :94; `del frame` :40; `exc_info=True` :169. Reviewer's executed outputs (`logs/architect/inputs/review-d2-round1.txt`): F3 `FIRST_RESUMPTION_GAP_MS 109; REPORTED_GAP_MS 531`; F4 `ERROR: Task was destroyed but it is pending!`; F7 `OverflowError: timestamp out of range for platform time_t` from `Event.wait` with `threshold_s=inf`.
- `scripts/gen_config_reference.py`:132 (the pairs `("ge", <U+2265>), ("le", <U+2264>)`; the characters are named here, not copied, to keep this file ASCII). Grep (count) for U+2265 in `docs/development/config-reference.md`: 264.
- `tests/fixtures/federation_cluster_node.py`:182-184 (`ProbOSRuntime(config=load_config(Path(config_path)), ...)`, `await runtime.start()` in the child). `tests/fixtures/federation_cluster.py`:69-71 (`_TRANSPORT_FAILED`, `_REFUSAL`), :526-533 (the child's stdout and stderr go to `run<N>.log`), :590, :597, :644 (`assert code == 0`), :771-790 (`log`, `wait_for_log`: `marker in line`, `refusal_lines`). Grep `federation_cluster import` over `tests`: the six `test_ad1198_{a2a_peer,cluster,fork_recovery,identity,peer_http,peer_reset}_gate.py` files.
- `tests/test_ad1137_quickstart_chain.py`:221 (`[sys.executable, "-m", "probos", *argv]`), :235 (stdout plus stderr), :301-306 and :335-337 (named phrases, `_assert_no_key`).
- `pyproject.toml`:181 (`asyncio_mode = "auto"`), :196 (`addopts = "-n 16 --dist=loadfile"`); no `filterwarnings` key (Grep `filterwarnings` over `pyproject.toml`: none).
- `threading.TIMEOUT_MAX` is new to `src/probos` (Grep count: 0 at `e535fd60`).

Added for the S1 repair (2026-11-27, worktree at `e535fd60` with the D1- and D2-repaired contract; inputs `logs/architect/inputs/review-s1-round1.txt`, `consult-s1-answer.txt`, `probe_force_describe_filter.py`):
- `routers/agents.py`: `_hook = "skipped"` :2967; the hook block :3482-3500 (Read: `_hook = "ran"` :3491, `await` :3494, `except Exception:` :3495, `logger.debug(` :3496-3499, `_t_hook1` :3500); the AD-733c-2 notification :3501-3518 (`note_dm_activity()` :3514; no `await` in :3500-3518); `get_or_create_working_memory` :3519; route line :3714-3715 (prints `_hook`). Grep `_hook\b|_t_hook` over `agents.py`: :2966, :2967, :3491, :3492, :3500, :3714, :3715.
- `config.py`:2306-2313 (the AD-733c-1 comment and `dm_force_describe_enabled` with the "synchronously describe" description, read), :2320 (`prompt_freshness_seconds` 120.0), :2215 (`class PerceptionConfig`), :4033 (`perception: PerceptionConfig` in `SystemConfig`, :3908). Grep `PerceptionConfig\b` over `src/probos` (glob `config*`): those two lines only.
- `docs/development/config-reference.md`:2154 (the row with the old text); `config-facade-baseline.yaml`:2677 (`PerceptionConfig:`), :2702 (the field line, default only, no description).
- `scripts/check_config_facade.py`: `_NormalisedJsonSchema` :334-336 (overrides only `encode_default`); `digest` :376-379 (`json.dumps` of the whole value); `model_record` :935-1012 (`model_json_schema(...)` :976, `digest(schema)` :981, record :1006-1011); canonical dump `SystemConfig()` values :1058-1059, :1083; header comment :249-251.
- `thread_fanout.py`: `_maybe_force_describe_frame` :386-410 (gate on `dm_force_describe_enabled` :404, `await` :406); call :1022; `_visual_ref` :1079, `latest()` :1086, `visual_attachment_ref=` :1141. Grep `_maybe_force_describe_frame|force_describe_current_frame\(` over `src/probos`: `consumer.py`:755, `agents.py`:3494, `thread_fanout.py`:386, :406, :1022. (The orchestrator's :1028 is the first candidate's line.)
- `perception/consumer.py`: ENGAGED caps :331-332 and :374-375 (200, 2000), `budget_exhausted` :342 (the consult's :347-390 are the candidate's lines, after P19's insertion); BF-977's cancellation path :801-811 (waits for the work task through further cancellations, then re-raises); `"source": "force_describe"` :905; `_filter_by_bound_sources` :1209. `crew_profile.py`:354-356 (`bound_sources` default `["camera", "screen"]`).
- `cognitive/episodic.py`:4550-4551 (`[saw: ...]` from `anchors.visual_description`).
- `tests/test_bf932_reply_path_timing.py`: `_Consumer` :76-88 (appends `consumer` first), `_runtime` :91-124 (a `MagicMock` runtime; `perception` :116), `_dm` :127-129, r1 :134 (:143), r2 :152, r3 :164 (:171), r4 :175 (:180), r5 :187, r6 :195, r1b :290. `tests/test_dm_camera_hook_deadline.py`:41 (imports `_dm`, `_runtime` from the timing file), t4 :286-299 (:298). `tests/test_ad978_group_perception.py`: `_RecordingConsumer` :99-106 (no `await`), `test_force_describe_called_once_when_enabled` :259-266, degrade test :270-280, per-round test :306-318. `tests/test_ad733c1_force_describe.py`:227-238 (mirrors the hook block; does not read `agents.py`).
- `__main__.py`:4688 (`asyncio.run(_serve(...))`: leftover tasks are cancelled when the run ends). `perception/mode_controller.py`:229 (`note_dm_activity`).

Added for the D2 repair after review round 2 (2026-11-27, worktree at `e535fd60`; inputs `logs/architect/inputs/review-d2-round2.txt`, `probe_r2f1_cancel_debug.py`, `probe-r2f1-output.txt`):
- Round-2 `run()` (this contract's 6.6 before this revision; C1's text is the same, `git show e535fd60:prompts/bf-932-reply-never-waits.md`:785-790): `except asyncio.CancelledError:` / `logger.debug("AD-824: loop-stall heartbeat cancelled")` / `raise` / `finally:` / `self._stop.set()` / `thread.join(timeout=_JOIN_TIMEOUT_S)`.
- Stdlib, CPython 3.12.13 (`d:/ProbOS/.venv/pyvenv.cfg`), `Lib/logging/__init__.py`: `Handler.acquire` :968 and `release` :975 (why a test handler must not define attributes of those names); `Handler.handle` :1011-1031 (`self.acquire()` :1026 around `self.emit(record)` :1028); `shutdown` :2245 (`h.acquire()` :2259); `atexit.register(shutdown)` :2281.
- `__main__.py`:1027 (`os._exit(0)` at the end of the serve path; also :729).
- Probe (orchestrator): handler held 3 s, candidate cancel returned after 3.005 s with the stop event never set during the hold; with only the DEBUG line removed, 1.014 s and the stop event set at 0.005 s.

Added for the D1 repair after review round 3 (2026-11-27, worktree at `e535fd60`; inputs `logs/architect/inputs/d1-brake-decision.txt`, `review-d1-round3.txt`, `probe-live-frontmatter-types.txt`):
- `records_store.py`: stdlib imports :3-13 (`import asyncio` :3, `import fnmatch` :4, `import logging` :5; no `hashlib`); `repo_path` property :696; `read_entry` :1485-1526 (`_safe_path` :1500, `exists()` :1501-1502 returns `None`, `read_text` :1504, the gate :1508-1524 for every reader but `captain`, the return :1526 followed by a blank line and `async def list_entries(` :1528); `publish` :1641-1669 (`fm["updated"]` :1662, no `revision`; `write_text` :1665; `auto_commit` :1667); `_safe_path` :1861-1872 (raises `ValueError` on traversal); `self._config.auto_commit` is the only config attribute read (Grep: :859, :978, :1080, :1667, :1817, :1842, :1996).
- `dreaming.py`: the per-agent read :949-957 (`try:` :950, `read_entry(` :951-953, `if doc:` :954, `loaded.append(... "_doc": doc)` :955, `except Exception: pass` :956-957); the cross-agent read :1065-1075 (the same first four lines :1067-1070, then `cross_loaded.append({` :1071); the whole-step handler's message `Step 7g notebook consolidation failed (non-critical): %s` :1229; `logger` :62 (`probos.cognitive.dreaming`).
- `tests/test_ad551_notebook_consolidation.py`:14 (`AsyncMock, MagicMock`), :27 (`store = AsyncMock()`), :28-44 (`list_entries`, `read_entry`, `write_entry`, `_safe_path`, `_git` set; no `entry_fingerprint`).
- `utils/frontmatter.py`:91 (`load_frontmatter(block, loader=yaml.SafeLoader)`); no duplicate-key refusal (Grep `duplicate` over the file: none), so `{1: one, true: two}` loads.
- Live census (orchestrator, `probe_live_frontmatter_types.py`, output `probe-live-frontmatter-types.txt`): 2,784 markdown files under `ship-records`; 2,778 notebook documents and 6 others loaded; 0 unparsed; no set, tuple, bytes, NaN, infinity, giant integer, shared container, cycle, datetime or other non-plain type in any frontmatter. Its positive control detected bytes, datetime, infinity, NaN, giant integer, set and shared container (cycle and tuple are not in the control's list).

### Absence Verified (2026-11-27)

- CLAIM: Step 7g's pair, BFS and coherence loops contain no `await`. RUN: Read `dreaming.py`:944-1116. FOUND: the only `await`s in :924-1229 are `list_entries` :932, `read_entry` :951 and :1067, `write_entry` :1012 and :1145, `_git` :1027. HOLDS.
- CLAIM: `read_entry`, `list_entries` and `update_episode_metadata` contain no `await`. RUN: Read `records_store.py`:1500-1526, :1563-1610; `episodic.py`:2488-2511. FOUND: none. HOLDS.
- CLAIM: `force_describe_current_frame` has two callers in `src`. RUN: Grep `force_describe_current_frame\(` over `src/probos`. FOUND: `agents.py`:3494, `thread_fanout.py`:406, and the definition `consumer.py`:755. HOLDS.
- CLAIM: four test lines pin `hook=ran` or the route's order. RUN: Grep `"hook"\) == "ran"|hook=ran|"consumer", "send"` over `tests`. FOUND: `test_bf932_reply_path_timing.py`:143, :171, :180; `test_dm_camera_hook_deadline.py`:298. HOLDS.
- CLAIM: the strict listing has three callers. RUN: the Grep tool, pattern `list_entries\([^)]*strict=` over `src/probos` with `multiline: true` (a single-line search misses a call whose arguments wrap; the first draft ran it single-line and found two). FOUND: `recreation/history.py`:184-185, `archive_promotion.py`:310, `stand_down.py`:281; no caller passes `strict=` a variable. HOLDS (corrected in round 1).
- CLAIM: `SystemInfo`'s default dump is pinned once. RUN: Grep `log_level` over `tests`. FOUND: `test_ad1270e2_config_models.py`:63 (pin); `test_pool_groups.py`:235 (input data, not a pin); the rest set or read `log_level` and pin no key set. HOLDS.
- CLAIM: no test counts every thread a runtime starts. RUN: Grep `threading\.enumerate|active_count\(\)` over `tests`. FOUND: filters by a thread name or by non-daemon threads (`runtime_lifecycle.py`:144-156) only. HOLDS: the sampler's thread is a daemon with its own name.
- CLAIM: `step_timing.py` is shared with the voice track. RUN: Grep `step_timing|TimingLines|emit_line` over `src`. FOUND: `audio/tts/resident.py`:43, `attachments/filesystem_store.py`:41, `cognitive_agent.py`:7691, `concurrency_manager.py`:20, `routers/agents.py`:64. HOLDS.
- CLAIM: the 2026-10-25 19:29:38-49 hole was not a loop block. RUN: Grep `runtime alive` 19:22-19:46. FOUND: 19:28:46 `uptime=367s`, 19:29:46 `uptime=427s` (on time). HOLDS.
- CLAIM: the two new utils modules (`loop_yield.py`, `loop_stall.py`) import the standard library only. (The first draft claimed no utils module imports from `probos`; that is false.) RUN: Grep `^from probos|^\s+from probos|^import probos` over `src/probos/utils`. FOUND: `response_formatter.py`:13 (module level, `probos.types`), `json_extract.py`:168 and `text_sanitize.py`:33 (function-local); the two new files' text (6.1, 6.6) has no `probos` import. `test_layer_boundaries.py` allows a utils module foundation modules (:35-37) and utils (:42) and no other layer (:55). HOLDS for the two new modules only (corrected in round 1).
- CLAIM (scoped in round 2, F3): no test that runs Step 7g pins how often `read_entry` is called (the checks add reads). The round-1 wording ("no test pins how often") was false: it searched mock-assertion spellings only and missed counting spies. RUN: (1) Grep `read_entry\s*=|"read_entry"|read_entry\.side_effect\s*=|read_entry.*(call_count|await_count|calls|count|spy|len\()` over `tests` (every replacement of `read_entry`, every spy installer); (2) Grep `dream_cycle\(` over `tests` (the files that can run Step 7g: 22). FOUND: (1) counting spies only in `test_ad1358_s1_head_to_head.py`: :376-381 (`calls["read"] += 1`, asserted 0 at :392 and 3 at :396), :501-506 (the read spy and the spy at :497 record each call's thread, `len(seen["threads"]) == 4` at :512), :689-693 (`reads.append`, `len(reads) == total` at :699); all three drive `read_head_to_head` (`recreation/history.py`'s strict listing), and that file has no `dream_cycle` or `DreamingEngine`. The other replacements (`test_ad1138_records_semantic_index.py`:711 a failing read; `test_ad550_notebook_dedup.py`:488, :516, :544; `test_ad661bc_records_redistribution.py`:49; `test_bf950_oracle_result_age.py`:141, :512; `test_gap_commands.py`:44; `test_gap_routing.py`:40; `test_self_monitoring.py`:449, :464) count nothing, and none is among the 22 `dream_cycle` files except `test_ad551_notebook_consolidation.py`:34 (`AsyncMock(side_effect=...)`, no count asserted: (3) Grep `read_entry\.(call_count|await_count|assert_called|assert_awaited|call_args|await_args)` over `tests` finds none). HOLDS for Step 7g's consumers.
- CLAIM: inside `dream_cycle` the dreaming module's `asyncio` name is used only by Step 7g's `sleep(0)` lines, so the tests' `_StepTurns` stand-in sees only Step 7g's turns. RUN: Grep `asyncio\.` over `dreaming.py`. FOUND: :10 (import) and :3168, :3194, :3203, :3232-3236, :3243, :3284, :3370 (all in `DreamScheduler`, below `dream_cycle`). HOLDS.
- CLAIM: only Step 7g's consolidation writes with the message `AD-551: Consolidated` (the tests' write turn keys on it). RUN: Grep `AD-551: Consolidated` over `dreaming.py`. FOUND: :1016. HOLDS.
- CLAIM: the new mutation locators are unique (`if stale:`, `return current ==`, `_reads_as_loaded`). RUN: Grep `^\s*(if stale:|stale = \[|return current ==)|_reads_as_loaded` over `dreaming.py`. FOUND: none at the base; P2, P35 and P36 add each once (the helper's name three times: its definition and two calls). HOLDS.
- CLAIM: the anchors of P35 and P36 occur once. RUN: Grep `# Write consolidated entry|# Archive non-primary entries|^def _outcome_evidence` (count) over `dreaming.py`. FOUND: 3 lines, one each. HOLDS.
- CLAIM (corrected in round 2, F2): Step 7g's consolidation runs through `dream_cycle` with a records store only in `test_ad551_notebook_consolidation.py` and the new D1 file. The round-1 wording also named `test_ad1341_s5_continuous_promotion.py` as a booted runtime reaching it; false. RUN: Grep `dream_cycle\(` over `tests` (22 files), then `records_store` in those 22; Read `test_ad1341_s5_continuous_promotion.py`:432-459. FOUND: `test_ad551_notebook_consolidation.py`; `test_ad1341_s5_continuous_promotion.py` matches `records_store` only for its promotion-step tests (:28, :105, the records clock), while its three `dream_cycle` calls (:444, :448, :459) use `_engine`, `DreamingEngine.__new__` with no `_records_store` (:432-438), and end before Step 7g (no episodes; the third raises at `_prune_weights`, :457); `test_procedure_store.py` (a `ProcedureStore` argument, :251, :425, :442), `test_ad1326_dreaming_challenger.py`:198, `test_dream_step_7f.py`:69, `test_fallback_learning.py`:152 (each sets the store to `None`). HOLDS; the AD-551 file and the D1 file are in 8.2 (the AD-1341 S5 file stays there as a `dream_cycle` consumer only).

- CLAIM (D2 repair): no test reads a child runtime's output for the absence of a WARNING, or for any text a sampler line contains. RUN: the Grep tool, `wait_for_log\(|\.log\(` over `tests` (every reader of `ClusterHarness.log`), then the negative assertions among them; `WARNING|"serve"|"start"|stderr` over `tests/test_ad1137_quickstart_chain.py`. FOUND: the negative checks are `"AD-1198: identity" not in` and `"does not satisfy its identity pin" not in` (`test_ad1198_identity_gate.py`:76-77), `_STALE_KEY not in` (`test_ad1198_cluster_gate.py`:204), `refusal_lines(...) == []` (`test_ad1198_peer_reset_gate.py`:105; the `_REFUSAL` pattern, `federation_cluster.py`:70-71); every other read is a named-marker wait or `in` check; `test_ad1137_quickstart_chain.py` matches only :235, :254, :318. None names `BF-932`, `event loop` or `WARNING`. HOLDS.
- CLAIM (D2 repair): a runtime is booted in a child process only by `federation_cluster_node.py` and the `python -m probos` children. RUN: Grep `"-m",\s*"probos"` over `tests`; Grep `ProbOSRuntime\(` over `tests/fixtures`. FOUND: `test_ad1137_quickstart_chain.py`:221, `test_bf908_crew_scope_token.py`:1348 (`crew-token set`: `__main__.py`:1975-1985 hands it to `crew_token_cli.run`, and Grep `ProbOSRuntime|runtime` over `crew_token_cli.py` finds nothing); `federation_cluster_node.py`:182, `runtime_factory.py`:102 (in-process). HOLDS.

- CLAIM (S1 repair): no JSON file and no test pins the `dm_force_describe_enabled` description. RUN: Grep `dm_force_describe_enabled|synchronously describe` over `tests` and over `docs/development`. FOUND: tests set the field or read its value only (`test_ad733c1_force_describe.py`:231, :236; `SimpleNamespace(..., dm_force_describe_enabled=...)` in six files); docs: `config-reference.md`:2154 and the baseline's field line :2702 (default only), plus `roadmap.md` prose. HOLDS.
- CLAIM (S1 repair): no test pins a model's `schema_sha256` value from the baseline other than through `--check`. RUN: Grep `schema_sha256` over `tests`. FOUND: `test_ad1270e1_config_facade.py`:215-216 (Windows vs POSIX equality), :820 (`None` for an unavailable schema), :1086, :1148 (`SensoriumConfig` set to zeros in a fixture). HOLDS.
- CLAIM (S1 repair): the DM path binds no frame to an episode. RUN: Grep `visual_attachment_ref=` over `src/probos`. FOUND: `thread_fanout.py`:1141 only. HOLDS.
- CLAIM (S1 repair): `note_dm_activity` is called in the DM route once. RUN: Grep `note_dm_activity\(` over `src/probos`. FOUND: `agents.py`:3514, `thread_fanout.py`:447, the definition `mode_controller.py`:229. HOLDS (V5 counts one `notify`).

- CLAIM (D2 repair, round 2): nothing on `run()`'s cancellation path logs before `self._stop.set()`. RUN: Grep `logger\.` over this contract's 6.6 block. FOUND: `_drop`'s DEBUG (the thread's failure path), `_WarningBudget.emit`'s WARNING and `_watch`'s INFO (the thread), and `run()`'s "already running" DEBUG, which returns before the `try`; inside `run()`'s `try` there is no log call, and its `finally` begins with `self._stop.set()`. HOLDS.
- CLAIM (D2 repair, round 2): no other text of this contract claims the sampler's logging cannot reach the loop thread or the process's exit. RUN: Grep (case-insensitive) `never waits|never delays|cannot delay|daemon|independent of logging|never wait` over this file. FOUND: D2e and the module docstring (qualified here), D2f (qualified: under the lock only), 6.13's `_Signals` docstring (rewritten), section 13's logging bullet (rewritten); the other hits describe the thread as a daemon, S1's reply (`config.py` description, 6.20a), or the `runtime_lifecycle.py` census; P33 and P34 say "a daemon thread" and claim no exit or independence property. HOLDS.
- CLAIM (D2 repair, round 2): `N21`'s locator is unique. RUN: Grep `finally:` over this contract's 6.6 block. FOUND: `_innermost_frames`'s plain `finally:` and `run()`'s `finally:` with its comment. HOLDS.

- CLAIM (D1 repair, round 3): `entry_fingerprint` and `_reads_as_loaded` are new names. RUN: Grep `entry_fingerprint|_reads_as_loaded` over `src`, `tests`, `scripts` (`*.py`). FOUND: none. HOLDS.
- CLAIM (D1 repair, round 3): nothing enumerates `RecordsStore`'s methods or dispatches to them by a name held in a variable, so no agent-facing path reaches the new method. RUN: Grep `dir\(RecordsStore|getmembers\(RecordsStore|vars\(RecordsStore|RecordsStore\.__dict__|"read_entry"|'read_entry'` over `src`, `tests`, `scripts`; Grep `getattr\([^,]*records[^,]*,\s*[a-z_]+\b[^"']` over `src` (a `getattr` on a records object with a non-literal name). FOUND: `test_ad1358_s1_head_to_head.py`:255 (parametrizes `"list_entries"`, `"read_entry"` for a failing read), :381, :506, :693 (`monkeypatch.setattr(store, "read_entry", ...)`), `test_bf966_unrecognised_classification.py`:45 (`_PATHS = ("read_entry", "search", "record_is_readable")`, the content-returning paths only, :106); no class enumeration; no dynamic `getattr`. HOLDS (the orchestrator's own grep of `scripts/`, `src/`, `tests/` found the same).
- CLAIM (D1 repair, round 3): no store that reaches Step 7g's load or checks is a plain `MagicMock`. RUN: Grep `records_store=|_records_store = ` over `tests` (58 files); Grep `records_store=(MagicMock|Mock|SimpleNamespace)\(|_records_store = (MagicMock|Mock|SimpleNamespace)\(` over `tests`; Grep `records_store|read_entry` over `test_dream_step_7e.py`, `test_dream_step_7f.py`, `test_ad1341_s4_stand_down.py`, `test_dreaming.py`, `test_bf1002_full_dream_complete_event.py`; Grep `notebook_consolidations\s*(==|>=|>)\s*[1-9]|notebook_entries_archived\s*(==|>=|>)\s*[1-9]` over `tests`. FOUND: `MagicMock()` stores at `test_ad562_finalize_wirer.py`:26, `test_ad594c_parallel_dispatch.py`:606, :620, :632, `test_procedure_store.py`:251 (none drives Step 7g); `test_bf106_dreaming_di.py`:51-78 (`mock_rs`, DI only); `_records_store = None` at `test_dream_step_7e.py`:108 and `test_dream_step_7f.py`:69; `test_ad1341_s4_stand_down.py`:155 a real store, outside Step 7g (round 2, F2); every positive consolidation assertion is in `test_ad551_notebook_consolidation.py` (:132, :152, :236, :253, :271), whose store is `AsyncMock()` (:27). HOLDS.
- CLAIM (D1 repair, round 3): no source-scan test pins the text P38 or P40 replaces or the helper's text. RUN: Grep `records_store\.py` over `tests`; Grep `repr\(current\)|_reads_as_loaded|could not re-read` over `tests`. FOUND: `test_ad1346_admission_file_write_census.py`:61 and its fixtures (`ad1346_file_write_census.py`:146, :159: `write_entry`'s writes; `ad1346_effect_census.py`:143 and `test_bf892_spawn_env_guard.py`:101: `_git_sync`'s subprocess), `test_layer_boundaries.py`:88, :92 (imports), `test_records_store.py`:423 (no duplicate method definition: the new name is unique), `test_bf952_records_keyword_search.py`:476 (a docstring); none names `read_entry`'s neighbourhood, and a byte read is neither a file write nor an effect; the second Grep finds nothing. HOLDS; the 8.2 `rg` list runs them all.

## 11. What this does NOT change

Batch 1 changes none of S1's files: the DM route still awaits the describe (`hook=ran`), and the bullets below about the `hook` value, the group round, the source-tag filter, the budget caps and `prompt_freshness_seconds` describe batch 2.

- The voice path (`routers/avatars.py`, `audio/`, `attachments/`, `ui/src/audio/`), `step_timing.py` and `config/system.yaml` (the Captain may raise `dreaming.idle_threshold_seconds` himself).
- The Captain-DM concurrency slot and priority, and the recall budget (the consult's S2 and S3): batch 2, drafted from the live `dm turn` and `AD-672 ... waited_ms` lines and what the sampler names. The consult ranked them on the 19:29:38-49 window, which was not a loop block (section 1); whether they are needed is now a measurement.
- Synchronous Chroma calls on the loop outside Step 7f2: Step 12's bulk calls, the recall path (`count_for_agent`, `recall_weighted`), and `records_store.py`'s other synchronous scans (:443, :1760).
- BF-977's `force_describe_current_frame`, its deadline, permit and cancellation. A cancelled refresh is not bounded by `timeout_s` (BF-977's design, `consumer.py`:801-811); recorded on #1670's follow-up list (S1e).
- The BF-932 route and turn line names and fields (only the `hook` value changes: `scheduled` or `failed` where it said `ran`).
- The group round: `routers/thread_fanout.py` and `tests/test_ad978_group_perception.py` are byte-identical to the base. `_maybe_force_describe_frame` still awaits the describe (BF-977's 4 s bound, once per round). The round's late `latest()` read for the episode's visual binding (`thread_fanout.py`:1079-1141, the review's F1 trigger) is on #1670's follow-up list as the batch-2 item that carries design B (S1d).
- The forced describe's source tag and `_filter_by_bound_sources` (`consumer.py`:905, :1209): the four profile-bound agents still never receive a forced describe. Filed as its own issue after the merge (S1e).
- The perception budget caps and mode transitions (`consumer.py`:331-342, :374-375); only the DM describe's position relative to the notification moves (S1c).
- `perception.prompt_freshness_seconds` and the Captain's config: the live instruction may raise it in his own config; nothing here edits it.
- Step 7g's BFS (`queue.pop(0)`) and `word_sets` (:1130): unpaced residuals (3a).
- Step 7g's consolidation format, author, message and archive layout; the primary still is the newest member by the listing's `updated`. The checks only decide whether a cluster or a member is written or archived in this dream.
- Every existing `RecordsStore` method, `read_entry`'s classification gate included. `entry_fingerprint` is additive (P39, P40) and has no caller outside Step 7g.
- AD-563's same-topic pair pass (`knowledge_linter.py`:88-100): not blocking at this vessel's scale (3a); recorded on #1670's follow-up list.
- The loop-stall sampler's cadence (a quarter of the threshold), budget (10 per 60 s), config field and log formats; the federation and quickstart fixtures (their children run the real sampler, D2d). The D2 repair changes only how the thread checks, latches the gap, drops a failure and refuses a threshold.
- The convergence report path (`dreaming.py`:1134-1135): two components in one wall-clock second write the same `convergence-<YYYYMMDD-HHMMSS>.md`, so the second overwrites the first while both events carry that path. Pre-existing; repairing it changes persisted output; filed as its own issue after the merge (section 13).

## 12. Issue text (#1670, on merge)

```text
Batch 1 of BF-932 merged (PR #<PR>, contract prompts/bf-932-reply-never-waits.md). The issue stays open for the Captain's live re-measurement.
- Found: the event loop was silent for 18 s at the same point of two dream cycles (2026-10-25 19:28:56-19:29:14, 2026-10-30 23:40:49-23:41:07, between Step 7f and Step 7h), with a 17.6 s TTS store write inside the second. Step 7g read every notebook (2,777) three times and compared every pair with no await; Step 7f2 made up to 1,000 synchronous Chroma calls. The 19:29:38-49 hole of the original measurement was not a loop block (the 60 s heartbeat ran on time).
- D1: those loops now give the event loop a turn every fixed count of units (2,000 pair iterations, 16 reads or word sets, 16 listed files, 8 episodes). Step 7g writes a consolidation only when no member changed since it was read, so a note revised during the dream keeps its revision; with no concurrent writer the step's output is unchanged.
- D2: a loop-stall sampler (system.loop_stall_warn_seconds, default 1.0, 0 = off) logs "BF-932: event loop blocked for <ms> ms ...; loop thread at: <frames>" and "BF-932: event loop resumed after <ms> ms".
- Not in batch 1: the Captain's DM still waits up to 4 s for the camera describe (BF-977's bound); the "BF-932: dm route" line shows it as hook=ran and hook_ms. The background describe for the DM (S1) was built and reviewed twice and is deferred to batch 2: a describe that outlives the DM reply can land during a group round, so that round's episode binds a newer frame than its prompt saw ([saw: ...] in recall; reproduced by the reviewer on real controllers). Batch 2 makes the group round wait for an in-flight background describe (same 4 s bound) before its own, then lands S1.
- Next: the live numbers below decide S1's priority and the rest of batch 2 (the Captain-DM slot and the recall budget).
- Follow-up (batch 2, design B): a group round's episode binds the frame it reads from working memory after the reply (thread_fanout.py, the visual_attachment_ref path), so an ambient description that lands during the reply can be bound to an episode whose prompt never saw it. Pre-existing at the base; possible data-integrity defect (false visual provenance); reproduce it on the real visual-binding path before promoting it to its own issue. The fix carries a dispatch-time snapshot to the episode.
- Follow-up: BF-977's cancellation is not bounded by timeout_s: a describe cancelled at shutdown stays pending, with its permit, until the storage thread returns. BF-977's design; lifecycle handling to schedule with S1.
- Separate issue (filed after the merge): forced describes carry source "force_describe", which the default profile bound_sources ["camera", "screen"] filter drops, so an agent with a perception profile never receives a forced describe (for those agents the DM's 4 s wait is pure latency).
- Follow-up: the dream's AD-563 linter compares every same-topic pair with about 20 regex calls each and no await (knowledge_linter.py _check_inconsistencies). On this vessel the largest same-topic group is 8 (348 pairs, about 10 ms); 512 notes of one topic took 3.3 s. Not paced in batch 1; the sampler names it if it blocks.
```

PR title: `The dream cycle stops holding the event loop and a stall sampler names any blocker`.

## 13. Prior art and blind spots

- Internal: the consult of 2026-11-27 (pre-turn path table, hypotheses, S1-S3); BF-930 and BF-932's timing lines (`step_timing.py`, PR #1790); BF-977 (the describe's deadline and permit); BF-918 (store I/O threads); AD-551, AD-555, AD-563, AD-873 (the dream steps); AD-824/825 (background-task lifecycle). No `docs/research/` study covers event-loop starvation.
- External (2026-11-27): aiodebug's `hang_inspection` uses the same heartbeat-and-thread design and writes stack dumps to files ([PyPI](https://pypi.python.org/project/aiodebug/), [superfastpython](https://superfastpython.com/asyncio-log-long-running-aiodebug/)). Adapted, not adopted: a third-party dependency, and its output goes to files rather than the log. CPython issue 106883 ([github](https://github.com/python/cpython/issues/106883)) reports a deadlock in `sys._current_frames` on 3.11 when a collection runs inside it. A fix disables collection during the call; one user could not reproduce it on 3.12.1. ProbOS requires 3.12, so no `gc.disable()` around the call (toggling the collector from a second thread would race the application). `docs/research/reference-projects.md` has no asyncio or event-loop row; no row was examined.
- Blind spots:
  - A host that pauses the whole process (sleep, a loaded test host) produces a stall line whose top frame is the selector wait (`windows_events.py` / `selectors.py`, `_poll`/`select`). That means the process was paused, not blocked by code (section 15, line 4).
  - Logging from the thread waits on a handler lock if the loop thread is blocked inside a handler; it then reports once the handler returns. The reverse also holds (round 2, R2-F2): while the thread writes a line, a log call from the loop thread that reaches the same handler (shutdown's INFO lines included; the reviewer measured the stop event unset and the loop's canary not run during such a hold with a real `RotatingFileHandler` at INFO) waits for that handler's lock, as it waits for any other thread's write; and `logging.shutdown()`, an `atexit` hook that takes every handler's lock, can delay a normal interpreter exit while the daemon thread is inside a slow handler (1.6 s measured in a child interpreter; the CLI ends with `os._exit()`, `__main__.py`:1027, and skips the hook). No deadlock: each side waits only for the other's handler call to return, and neither holds D2f's lock across a log call. The sampler adds no wait of its own to the loop thread except the join at cancellation, bounded by `_JOIN_TIMEOUT_S`; the cancellation sets the stop event before anything on its path can log (round 2, R2-F1: a DEBUG line there, in the verbose configuration, waited for the handler the WARNING held, so the join bound did not apply). The one lock the two share (D2f) is held for a few statements with no logging, frame reading or wait under it.
  - D2, round 3, R3-F1 (injected-only; introduced by the round-3 repair, in the test only): the DEBUG-handler test recorded only whether the stop event became set, while `_Signals.emit` discarded its gate wait's result, so a test host paused for more than 30 s (`_GUARD_S`) before the observer started let the handler return and release its lock with the gate still unset; the test then passed with round 2's `CancelledError` arm put back (the reviewer's probe, 39 s). Round 4: `_Signals.emit` records an expiry in `gate_expired` and the test asserts it is False after its cleanup and before its property, so an expiry fails the setup. The other two gate tests turn red, not green, on an expiry (the held-in-a-logging-call test at `held_at_cancel is True`, the resume-gap test at its gap assertion) and are unchanged. No permanent test of the guard itself (it would need a stall of more than 30 s); the round-4 reviewer's probe stands in for it once.
  - The sampler's WARNING reports the age at detection (at least the threshold), not the full stall; the resume line carries the first heartbeat's gap, which is the stall plus at most one tick, however late the thread logs it (D2f; round 1 measured a 109 ms gap reported as 531 ms before the latch).
  - A slow log handler at shutdown (round 1, F2): the join gives up after 1 s and the thread ends when the handler returns. Chosen over a stronger ownership rule because waiting for the thread would make shutdown wait on a handler; the thread holds nothing shutdown must release (D2e).
  - Child processes (round 1, F8): a runtime a test boots in a child runs the real sampler. Harmless by D2d's census; a future test that asserts a child wrote no WARNING would have to turn the sampler off in that child's config (`system.loop_stall_warn_seconds: 0`).
  - A failed check keeps no traceback (round 1, F5): the DEBUG line carries `repr(error)` only, so a buffering handler cannot keep the loop thread's frames and locals alive.
  - D1's counts bound units, not time. A unit that is itself slow (one Chroma update) can still exceed the threshold, and D2 names it.
  - S1: the reply describes the scene working memory holds; "what am I holding up?" gets the last description that landed, and an immediate second DM may still get the sentinel (round 1, F4). Readiness for a recording is a reply that shows the scene (section 15).
  - S1, round 1 F3: the first candidate printed `hook=scheduled` when starting the task raised. The label is now assigned after the helper returns, `failed` in the `except` branch (V4, S1M8, S1M9).
  - S1, round 1 F2: the describe runs after the DM's engagement notification and is charged to the ENGAGED budget; accepted (S1c) and pinned (V5, S1M10).
  - S1, round 1 F1: a background describe in the group round could bind a frame to an episode whose prompt never saw it. Avoided by not changing the round (S1d); the late read it exposed predates S1 and is batch 2's design B.
  - S1, shutdown: the first draft implied the 4 s deadline bounds a refresh; it bounds a describe a caller waits on. A refresh cancelled at shutdown waits for BF-977's step (S1e), as BF-977 specifies and tests; on #1670's follow-up list, not changed here.
  - S1, profiles: the forced describe's source tag is dropped for agents with the default `bound_sources` (S1e; the orchestrator's probe and the reviewer's both reproduce it), so for those four agents the awaited describe was pure latency. Its own issue after the merge.
  - S1, prior art: none searched for the repair. A task held in a set until its done callback is asyncio's documented pattern for `create_task` (keep a reference); the rest is ProbOS plumbing.
  - D1's turns opened a lost-update window in Step 7g (read, turn, publish from the cache): the round-1 review's P1. D1d closes it with an optimistic check whose validation and write share one run of the loop (optimistic concurrency control: validate, then write, with no interleaving point between; here asyncio's run-until-await gives that for free, so no lock and no version column). Since round 4 the validation compares a content hash of the stored bytes (the same idea as an HTTP entity tag or a content-addressed version), not the parsed document. No external search: the pattern is textbook and the plumbing is ProbOS-specific.
  - A writer that rewrites a note with the same text still bumps `revision` and `updated`, so the bytes change and the cluster is skipped once; the next dream consolidates it. Any byte change that does not matter to the dream (a whitespace edit, the same document written in other bytes) does the same: one dream's postponement, nothing lost or overwritten.
  - A note revised in every dream keeps its cluster from consolidating; nothing is lost, the consolidation is only postponed.
  - A member left live after the primary was written (P36) still has its old text in the primary's observations; the next dream may consolidate the two again, which repeats that older paragraph once. Duplicate text, not lost text.
  - The primary revised during its own write's git and indexer awaits (after the check) is a plain later write: the revision wins and replaces the consolidated body, and the archived members' text then lives in `_archived` and git history. The base has the same window and D1 does not widen it; not repaired here.
  - Round 2, F1: `==` between two loads of a note whose frontmatter contains itself (YAML anchor and alias; the safe loader builds it and an alias opens no depth) raised `RecursionError` into Step 7g's whole-step handler, so one such note cost the step every later cluster and the convergence. Round 3 compared `repr`s inside the helper's `try`; round 4 compares file bytes instead (below), so no document comparison remains and the self-containing note is one of the four unchanged controls.
  - Round 3, R3-F1 and R3-F2, and the brake decision (continue with B3): `repr` raised `ValueError` for an integer past CPython's 4,300-digit conversion limit (a 16,384-bit hexadecimal integer: base and round 2 gave 2 consolidations and 4 archived, round 3 gave 1 and 2), and two loads of a `!!set` of explicitly tagged NaNs could repr differently (fresh NaNs, identity hashes, so the set's order varies). Classification (the Architect's, recorded for the audit trail): both are **injected-only** on this vessel. R3-F1 is a regression of the round-2 repair; R3-F2 is not a regression relative to round 2 (round 2's `==` also rejected it) but is relative to the base, which compares nothing. Both fail in the safe direction (a cluster skipped, or a member left live). Reach evidence: the orchestrator's live census of `ship-records` (10) loaded 2,778 notebook documents and 6 others and found no set, tuple, bytes, NaN, infinity, giant integer, shared container, cycle or datetime in any frontmatter, while its positive control detected bytes, datetime, infinity, NaN, giant integer, set and shared container. The reviewer's "ordinary" label rested on counting any YAML the loader accepts on disk as ordinary reach (its report, Checklist, Assumptions). Not enumerated: the types every `write_entry` caller can pass. The decision does not depend on it: B3 removes the class, because bytes have no type domain. R3-F1 being a regression is why the brake chose continue, not rescope.
  - Withdrawn in round 4 (R3-F4): round 3's claim that `repr` makes an unchanged `.nan` equal to itself where `==` did not, and that the round-1 helper would have postponed such a note forever. False: PyYAML returns one NaN object for every `.nan` scalar, and `==` between dicts accepts an identical value object, so round 1's comparison accepted it (the reviewer measured `round2_helper True`). Only the explicitly tagged `!!float nan` allocates a new NaN per load; under B3 neither spelling matters.
  - Round 3, R3-F3: no D1 item failed when the comparison was moved out of the helper's `try`, and 8.3's round-2 note said the `except` arm ran only when the re-read raised (it also ran when `repr` raised). Round 4 adds the containment test (a fingerprint that raises after a successful load skips its own cluster, the next agent's cluster still consolidates, and the whole-step handler logs nothing) and M23.
  - Round 3's "alias-heavy residue" bullet is withdrawn: there is no `repr` or document walk left to blow up. What remains of the check, recorded and not repaired: (1) a byte change that does not matter to the dream skips the cluster for one dream (above); (2) a fingerprint that cannot be taken (an `OSError` on the read, a path `_safe_path` refuses) is contained: at the load the raise falls into the base's existing `except Exception: pass` around the read (`dreaming.py`, the Step 7g load loop), so the note sits out this dream with no log record, as a failed `read_entry` does at the base; at a check the helper logs it at DEBUG and counts it as changed, so the cluster waits for the next dream or the member stays live; (3) (round 4, R4-F2, P3 size, pre-existing) the intra-agent `loaded` items still carry `"_doc": doc`, which nothing reads for those items: at the base too, the only reader (`ce.get("_doc", {})` in the cross-agent cluster code) iterates `cross_loaded` items, which never carry `_doc`. Dropping the key, and the `_doc` fallback that is dead for `cross_loaded`, goes to the follow-up; this PR's only change to that append is the added `"_fp"`. None of these loses or overwrites a note. Alias expansion still costs `read_entry`'s own parse at the load, as at the base.
  - B3's fingerprint has no classification gate (D1d): it reveals only whether bytes equal an earlier digest, Step 7g keeps it only for notes `read_entry` admitted for `system`, and nothing outside Step 7g calls it (Absence Verified, 10). A future caller that exposes it to an agent would need the gate; none exists.
  - The publication checks fingerprint 2k - 1 files for a cluster of k with no turn (3a), and the load adds one fingerprint per note read (a byte read and a sha256, inside the paced loop). Clusters on this vessel are small (no note has ever been archived: 0 under `notebooks/*/_archived`).
  - AD-563's pair pass (R-c): residual; on #1670's follow-up list with the vessel measurement (348 pairs) and the reviewer's 512-note figure.
  - Convergence report path collision (R-e): filed as a separate issue after the merge. It is a reproducible data-integrity defect (a persisted report replaced in place, and an emitted event whose `report_path` then names another report's body), which the filing policy allows as an exception to the discovery budget; it is unrelated to the reply path, so it does not belong on #1670.

### S1, review round 2 and the batch-2 design (S1e; recorded 2026-11-27)

Round 2's first reviewer (gpt-6.1-sol, staged tree `54669d8a`, `logs/architect/inputs/review-s1-round2.txt`) asked for changes; under the cutoff of 21:15Z S1 leaves batch 1. A second reviewer of the same candidate was still running at the deferral; its findings go to batch 2.

| Finding | Severity, reach | Status |
|---|---|---|
| R2-F1: a DM's background refresh outlives the reply and still holds BF-977's permit when a group round dispatches; the round's own describe returns `None` (`consumer.py`:782), the refresh then lands in working memory, and the episode's late `latest()` read (`thread_fanout.py`:1086, bound at :1141) binds the newer frame. Executed on real controllers: prompts "Old blue mug", episodes `[saw: New green book.]`, base "New green book" throughout | P2, ordinary (a DM followed within about 4 s by a group round); an S1 regression: design A's "unchanged group path is safe" premise is disproved | open; S1 deferred to batch 2; closed there by design C below |
| R2-F2: V5's comment and S1c said post-notification ordering means ENGAGED accounting; the describe runs in the primary controller's mode (a DORMANT primary describes in AMBIENT; a non-primary DM target turns ENGAGED while enforcement reads the primary) | P3, ordinary; wording, no behaviour | S1c narrowed in this revision; batch 2 rewrites V5's comment (6.20) and the S1 tracker wording to "the describe starts after the notification; ENGAGED accounting holds only when the primary controller is engaged" |
| R2-F3: the in-tree copy of this contract at C1 was stale ("ready to build", the rejected group change, a one-message warm-up) | P3, ordinary; documentation | closed by batch 1's contract-only commit (this revision replaces the C1 copy; sections 12 and 15 describe batch 1) |

Recorded by the reviewer, not new: R2-E1 (BF-977's cancellation not bounded by `timeout_s`; S1e (1)) and R2-E2 (the forced describe's source tag dropped by a default profile; S1e (2)).

**Design for batch 2 (chosen: C).** The group round waits for the background refreshes in flight at its dispatch before its own describe, inside one shared 4 s deadline:
- `perception/consumer.py`: a public module helper next to `refresh_scene_in_background`, `async def await_scene_refreshes(*, timeout_s: float) -> None`. It snapshots the not-done tasks of `_SCENE_REFRESH_TASKS` that belong to the running loop and, if any, `await asyncio.wait(tasks, timeout=timeout_s)`. It neither cancels nor raises (a failure is already logged once by the done callback).
- `routers/thread_fanout.py` `_maybe_force_describe_frame` (:386-410): one call to the helper before the describe at :406, then the round's own describe with the time left of the same 4 s (skipped when none is left). The round's wait stays bounded by 4 s in all, as at the base.
- Why C: it restores the base's ordering for every DM-started describe in flight at dispatch (the R2-F1 trigger: the refresh lands before the prompt is composed, and the round's own describe then runs with the permit free), in about ten lines across two files, with no change to the DM path (still no wait) or to the episode, embedding or recall format. It is also better than the base for a DM and group round that overlap: at the base the DM's inline describe held the permit and the round composed its prompt from the older frame (by reading `consumer.py`:782 and `thread_fanout.py`:1086; not measured); under C every DM describe is a task the round waits for.
- Rejected: (B) bind a dispatch-time snapshot of the observation to the group episode (the reviewer's fix): it changes memory provenance (episode construction and `cognitive/episodic.py`:4551's embedding) and is the fix for the pre-existing late read, which is not S1's regression; it stays the #1670 follow-up (section 12). (D) bind no frame when the observation changed between dispatch and the episode: it also needs a dispatch-time read, and it loses the visual binding in the race instead of keeping it right.
- Residual after C, the base's own class: an observation that starts landing after dispatch (an ambient update, or a second DM's refresh started during the round) can still reach the late read, as at the base; and a refresh whose storage step overruns BF-977's deadline past the round's 4 s (R2-E1's case, injected-only). Design B closes both; not S1's scope.
- Consequences for batch 2's text: S1d, section 9 property 17, section 11 and acceptance item 3 no longer say `thread_fanout.py` is byte-identical; `tests/test_ad978_group_perception.py` stays base-identical and green as a control.

Tests (outline; the pairs are drafted with batch 2):
- Seam test (the reviewer's probe made permanent): real controllers, registry, `VisionConsumer`, attachment store, group dispatch and embedding formatter; a DM completes with its refresh gated in flight (old frame to new); a group round dispatches; the gate opens. Assert each group prompt's frame equals its episode's `[saw: ...]` frame, and both are the new frame. Red on the round-2 candidate (prompts old, episodes new), green on the base and on C.
- Bound: a refresh that never ends; the round's describe stage returns within the shared deadline (fake clock or a module constant), and its own describe gets only the time left. The helper on its own: with `timeout_s=0.05` and a pending task it returns, and the task is still pending and still held.
- Controls: no refresh in flight, the round's own describe runs once with 4.0 (`test_ad978_group_perception.py::test_force_describe_called_once_when_enabled` unchanged); a task of another loop is ignored.
- Mutation rows: delete the helper call (seam test red); the helper returns before waiting (seam test); `timeout=None` (bound test, guard); the own describe gets the full 4.0 after the wait (bound test); the helper cancels pending tasks (helper test); drop the loop filter (other-loop test).

## 14. Acceptance criteria

Batch 1 (D1 and D2) is accepted on items 1-8 read with section 8's batch-1 note: the S1 parts of items 1, 3 and 7 are batch 2's. In batch 1 the S1 files of section 9's note are byte-identical to the base.

1. The A/B of 8.1 holds (on the base and, for D1 and D2, on the unrepaired candidate); M1 to M15, M17, M18, M20 to M24, N1 to N21 (batch 1) and S1M1 and S1M3 to S1M10 (batch 2) are killed as 8.3 says (S1M2 is removed; M16 and M19 are retired with their reasons), except N10 and N17, which are recorded as not killed with their reasons.
2. The focused checks of 8.2 pass, the `rg` list included; the pre-existing tests in those files pass unchanged except the in-place edits of section 6.
3. The generators of 4a and 4b produce only the expected diffs, and `check_config_facade.py --check` passes. `routers/thread_fanout.py` and `tests/test_ad978_group_perception.py` are byte-identical to the base.
4. `git diff --check` is clean, the new hand-written text is ASCII (generated files are exempt: the `loop_stall_warn_seconds` row of `config-reference.md` carries U+2265 and U+2264, rendered by `gen_config_reference.py`:132; nobody hand-edits that row), and no file outside section 6 (plus the generated files and the ledger pair) changes.
5. The Diff Reviewer approves against section 9.
6. One receipted broad gate on the committed head is green.
7. After the merge: section 12's lines (S1 deferred to batch 2 with design C; AD-563's pair pass; the group episode's late visual read as design B; BF-977's cancellation bound) are on #1670; the convergence report path collision and the forced-describe source-tag filter are each filed as their own issue after a duplicate search (section 13, S1e).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. The Captain's live check (after the merge)

1. Restart the vessel on main with this merge, camera on. In batch 1 the DM still waits for the camera describe as before (up to 4 s, BF-977's bound), and so do group rounds; the background describe is batch 2 (section 13). The four crew members with a perception profile behave as they do today: a forced describe never reaches them (a separate issue), so for them that wait buys nothing.
2. Record as usual and note the start minute. Afterwards run: `Select-String -Path "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log*" -Pattern 'BF-932: dm route','BF-932: dm turn','BF-932: event loop blocked','BF-932: event loop resumed',"AD-672: Promoted queued intent 'direct_message'"`
3. Measure, per message: each `dm route` line says `hook=ran` (the describe ran and the reply waited for it) or `hook=skipped`; `hook_ms` is that wait. Total `thread_ms + prep_ms + hook_ms + dispatch_ms` (route) plus `waited_ms` (a promoted line, if any) plus `perceive_ms + recall_ms` (turn), and post the p95 (the largest value if fewer than 20 messages) and the p95 of `hook_ms` alone. These numbers decide batch 2: a large `hook_ms` share puts S1 (with design C) first; large `waited_ms` or `recall_ms` puts the Captain-DM slot or the recall budget first.
4. Pass: no `event loop blocked` line inside the recording window. Any that appear: post them as they are. The frames after `loop thread at:` name the blocker; a first frame in `selectors.py` or `windows_events.py` means the process was paused, not blocked by code.
5. Post the count of `event loop blocked` lines and whether any reply said "camera not active".
