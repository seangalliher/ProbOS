# BF-930 (#1668) and BF-932 (#1670): log-only timing of the spoken-reply path and of the Captain-DM reply path, so one live call shows where the time goes (instrumentation only; both issues stay open)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge is logged out), 2026-11-13
**Revised by:** the orchestrator (amendment A1, section 15: the file paths the apply tool needs in six label lines, the two new test files made to fail at an assert on the base and the second joined into one block with its `make_agent`, the case counts, five S1 mutation cells, the measured gates, and the S2 limit L9 for `ArchitectAgent.perceive`), 2026-11-13
**File in the repository:** `prompts/bf-930-932-voice-and-reply-path-timing.md` (the orchestrator may rename it). **Answer file:** in three parts, because the contract is too long for one `create` call: `answer-bf930-932-contract.part1.md` (this header, sections 1 to 6), `answer-bf930-932-contract.part2.md` (section 7: slices S1 and S2), `answer-bf930-932-contract.part3.md` (sections 8 to 14, "Batching", "Not in this issue: for the Captain"). Read them in that order; the labels of section 7 restart in each slice.
**Status:** ready to build on `origin/main` `f614a31d855e217eec6c826deaffad7572d1f43f` (BF-937's merge) **after the two UI-only batches have merged** (the voice batch: BF-928, BF-929, BF-931; then BF-933). **Reading tree:** `D:\ProbOS-worktrees\next-read` at `f614a31d855e217eec6c826deaffad7572d1f43f` (clean: `git status --short` prints nothing; read only). **Oracle:** the Architect ran no pytest, no vitest, no build and no script that writes (a read-only consult). **What I ran instead** (section 11): every SEARCH of section 7 against the LF blobs of the reading tree (30 SEARCHes: each occurs once, at a line start, ASCII); the enumerations of every reader of the lines this batch extends or adds; an AST scan for the model calls of the agent; the existing harnesses read case by case. **What that leaves unchecked (all "expected" below):** every pytest count and every new case as a pytest case, the mutation rows, the AD ledger regeneration, `scripts/check_architecture_principles.py --check`, the broad gate, and everything that needs the live vessel (section "Not in this issue: for the Captain").
**Base blobs (`f614a31d`):** S1: `src/probos/attachments/filesystem_store.py` `c29e56fe160a4ee4996f653a28c52a424b0fb973`, `src/probos/audio/tts/resident.py` `4abf3f127ad2a334e66fe6dfbead05e41db7354f`, `src/probos/routers/avatars.py` `d34ece50a7b003bc672b86916e3f480b2e7ef234`. S2: `src/probos/routers/agents.py` `04f7fefade334a97f5016a52c973ddf9151f549c`, `src/probos/cognitive/cognitive_agent.py` `62c0f816bd5f1ce766a541abbfc0ccba6b743ae4`, `src/probos/cognitive/concurrency_manager.py` `3b0a9f99389f30ee07a46c8c416f7f1ba19422f9`. Read, not edited: `src/probos/perception/consumer.py` `74aa7f9710ec5a02e73a378c5a6b51884b06dd84`, `src/probos/attachments/store.py` `f663fcec73b5d6f6171af7d8e9557afb35463027`, `tests/test_bf918_tts_latency.py` `387b1a2e32089e7135eeda5f0ab70742b4e9cfcf`, `tests/test_ad672_concurrency_manager.py` `57eed6cca63f85ef12637a6f0a82e71318797360`, `tests/test_ad730_agent_chat_vision.py` `349ea3e5186879c4452221f8c5135c8683678880`, `tests/test_cognitive_agent.py` `76c21809158ef67d3ac082495b83401f8b87ef82`. Trackers and generated pair, as the BF-933 contract measured them on `f614a31d`: `PROGRESS.md` `70cd1044019282b348bba2532acd6bfb2b6369cf`, `DECISIONS.md` `90adc2837c3d2c6d09327e93543eeb0471880fec`, `docs/development/open-ads-report.md` `04562090a74a962b09f61864a667ecb1a62f1b8a`, `docs/development/ad-ledger-snapshot.json` `35de650056f112a17d079fab48f32ddabad939bb` (**the two UI-only batches move all four before this batch is built; every code blob above must still be equal**). **Four paths do not exist** (to be confirmed by `Test-Path` before the build): `src/probos/utils/step_timing.py`, `tests/test_bf930_voice_path_timing.py`, `tests/test_bf932_reply_path_timing.py`, `prompts/bf-930-932-voice-and-reply-path-timing.md`.
**Dependencies:** the two UI-only batches merge first (they edit no file under `src/`; they share only the four tracker files with this batch). S2 imports the helper S1 creates; S2 reverts before S1. **Tier:** S1 M1 STANDARD (tests), S1 M2 HIGH (the attachment store's write path and the resident synthesizer: a lock, a thread pool and a cancellation-reviewed `_run` sit beside the edit; the edit adds only clock reads, two attributes and a log call), S1 M3 STANDARD; S2 M1 STANDARD, S2 M2 HIGH (the Captain's DM route, the agent's turn and the per-agent concurrency queue), S2 M3 STANDARD. **Estimated tests (expected, not measured):** S1 one new file, 19 cases (3 controls pass at M1, 16 xfail, section 6); S2 one new file, 11 cases (4 controls pass, 7 xfail). No config key, no config model, no generated artifact but the AD ledger pair. **Numbers:** BF-930 is held by #1668 only and BF-932 by #1670 only (section 11, Absence Verified); nothing new is allocated, so `ad_ceiling.py` was not needed (**Current highest AD: not resolved by this consult, because none is allocated**; the BF numbers are the issues').

**Tracker anchors (state as the BF-933 contract does; the orchestrator re-anchors after both merges).** `PROGRESS.md`: the title line `# ProbOS Progress` and the blank line after it (once, at the start of the file on `f614a31d`: `git show HEAD:PROGRESS.md` starts `# ProbOS Progress`, an empty line, then BF-937's slice 2 entry; the SEARCH is unchanged by any entry inserted below it, so this batch's entries land above the other two batches'). `DECISIONS.md`: the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)` (once on `f614a31d`, at line 1710, at a line start, ASCII, no CR in the blob: `rg -c -F` printed 1; every BF entry of this period inserts before it, so this batch's entries land after the other two batches', in slice order). **The orchestrator re-runs the occurrence check of those two SEARCHes after the two merges (each exactly once, at a line start, ASCII); any other change to either file between `f614a31d` and the build's base is a hard stop for the Architect.** The AD ledger pair is regenerated at each M3 by `scripts/gen_ad_ledger.py` (G3) and is not merged by hand. **No tracker line of this batch contains the token `AD-`** (the ledger reads AD and BF tokens at the head of tracker entries and in commit subjects); each head names its own BF number only. (The code comments the blocks add name BF-930 or BF-932 and no `AD-` token of their own; the existing `AD-672`, `AD-733` and `AD-738` text the blocks keep is not touched.)

## 1. Problem

Both issues are "instrument first" (BF-932's first acceptance bullet; BF-930's "add timing at each sub-step if the current logging can't separate them"). Their anchors are from `5e3cc991` and are re-derived on `f614a31d`. **Their live figures are quoted nowhere in this contract** (decision D8): no test, comment, tracker line or commit message of this batch holds a stall length, a count, a crew name, a thread id or a timestamp from the vessel; the issues are the place for those.

| Issue claim | Re-derived on `f614a31d` | Verdict |
|---|---|---|
| BF-930: the route log cannot separate the sub-steps | `routers/avatars.py:327` writes `BF-918: tts route chars=%d synth_ms=%.0f store_ms=%.0f visemes_ms=%.0f total_ms=%.0f visemes=%s audio_ms=%d`. `synth_ms` covers `select_backend` and `backend.synthesize` (`:272-275`); `store_ms` covers the `sha256` of the audio, the store accessor and `store.write(...)` (`:296-302`). Inside `synth_ms` sit the resident service's per-key `asyncio.Lock` (`resident.py:401`), `_claim`, the voice executor queue (4 threads shared with rhubarb and ffmpeg, `:46`, `:411`) and Piper's own work. Inside `store_ms` sit the store's single `asyncio.Lock` (`filesystem_store.py:328`), three store-thread hops (`_locate_sync`, the blob write, `_save_index_sync`) and the index rewrite (`json.dump` of the whole index, `:236-250`). | **Confirmed**: seven different causes share the two numbers. Nothing in the current logging separates them. |
| BF-930: "contention with other store users such as vision frames", "the reaper" | The same `self._lock` is taken by `write` (`:328`), `unlink` (`:406`), `unlink_if_unchanged` (`:449`), `list_by_origin` (`:484`) and `total_size_bytes` (`:499`); `_find` (`exists`, `get_path`, `read`) takes no lock but shares the 4 store threads and runs a directory `glob` per call (`:368-377`). | **Confirmed in the code**; whether it produced the live stall is unmeasured. |
| BF-932: the camera describe is capped at 4 s; most of the wait is unexplained | `routers/agents.py:3479` `force_describe_current_frame(timeout_s=4.0)`; in `perception/consumer.py` the `asyncio.wait_for` is at `:823-826`; **outside the cap** are `store.exists(sha)` before it (`:787`) and `store.exists(sha)` after it (`:843`) | **Confirmed**: the two `exists` hops are the unbounded part of the hook. |
| BF-932: "the turn starts" is `BF-631 DM-recall`; "the turn ends" is an `AD-1208 ... complete` line | `BF-631 DM-recall` is written at `cognitive_agent.py:12129`, inside `_recall_relevant_memories` (`:11562`), i.e. **after** `perceive` (`:7608`) and the per-message recall (`:7613`), not at the start of the turn. The `AD-1208` per-pass line is `turn_cost.py:253-256` (`pass stopped_reason=%s; ...`), written only by armed conversational turns (a token budget set). No general end-of-turn line exists | **Premise corrected**: the "+19 to +41 s" of the issue includes the recall itself, and the issue's end marker is not general. The route line of S2 carries `total_ms` for the end. |
| BF-932: "queueing for the agent and for the LLM lane" | The agent queues Captain DMs in `ConcurrencyManager` (`cognitive_agent.py:8257` `async with concurrency_manager.slot(...)`; `concurrency_manager.py:55-56` defaults 4 threads, queue 10; the DM has priority 8 or 10, but it waits for a release: it cannot preempt an active thread). Its existing INFO lines `AD-672: Intent '%s' queued ...` (`:142`) and `AD-672: Promoted queued intent ...` (`:234`) exist already, without the wait. The LLM lane (`llm_client.py:1462-1490`) is entered **after** the DM-recall line: the AST scan finds `.complete(` calls in `cognitive_agent.py` only in `_decide_via_llm` (`:4667`), `propose_appearance`, `propose_voice_profile`, `_answer_consultation` and `_run_interpretation` (none in `perceive` or `_recall_relevant_memories`) | **Agent queue: confirmed and already half-visible. LLM lane: cannot be in the window the issue measured** (D1 row H7; left out, named as the next step). |
| The log can carry the evidence | The file handler writes INFO and above (`__main__.py:171-180`) with `datefmt="%Y-%m-%d %H:%M:%S"` (`:151`): **whole seconds**, which is why the issue's table is in whole seconds. Every root handler passes `LogRedactionFormatter` (`:203`; `security/pii_redaction.py:13-25`: ten-digit runs, keys `token`, `secret`, `password`, `file_id`, `docid`, `item_id` and URLs are rewritten) | All new timing is carried in the lines' own `_ms` fields; the new lines avoid every redacted shape and a case proves it (S1 T13, S2 R5). |

**What the batch is.** Two slices of log-only lines (S1 the spoken-reply path, BF-930; S2 the Captain-DM path, BF-932) and the small helper S1 creates and both use. It changes no response body, status code, call order, lock, thread or timeout. **What it is not:** a fix, a target, or a live measurement. The p50/p95 target, the fix and the re-measurement cannot close from tests, because the cause is not yet known and only the live vessel under load shows it.

## 2. Solution

**S1 (BF-930, HIGH).** A new `probos/utils/step_timing.py` (`ms_between`, `emit_line`, `TimingLines`: a monotonic-ms helper, a failure-isolated INFO writer and a per-instance bounded writer that reports `suppressed=N`). `FilesystemAttachmentStore.write` stamps its steps and writes **one** `BF-930: attachment write slow ...` line when the whole write took at least 250 ms: `lock_wait_ms`, `locate_ms`, `blob_ms`, `index_ms`, `behind=<what held the lock on arrival>`, `index_entries`. `_find` writes `BF-930: attachment find slow ...` at the same threshold. `VoiceSynthesisService.synthesize` stamps and writes `BF-930: piper request slow ...` at 750 ms: `lock_wait_ms`, `claim_ms`, `pool_wait_ms`, `work_ms`, `resume_lag_ms`, `cold`, `in_flight`; the worker supplies the two thread-side stamps it already owns. The route's existing `BF-918: tts route` line gains one trailing field, `id=<first 8 of the audio's sha>`, the join key to the store's line.

**S2 (BF-932, HIGH).** The DM route stamps its timeline and writes **one** `BF-932: dm route intent=<id8> ...` line per Captain DM after `intent_bus.send` returns: `thread_ms`, `prep_ms`, `hook`, `hook_ms`, `dispatch_ms`, `send_ms`, `total_ms`. The agent writes **one** `BF-932: dm turn intent=<id8> ...` line per HXI DM at the point of the DM-recall line: `perceive_ms`, `recall_ms`. The concurrency manager's existing `Promoted queued intent` line gains a trailing `waited_ms=`. The join keys are the intent id (route and turn) and the agent id (the queue line).

**Not built, and why (D1, D3, D6).** A fix; a target; a log reader script; a config key; an always-on loop-lag task; the LLM lane and the turn's own model calls (they come after the window the issue measured); an end-of-turn marker; per-step lines inside `force_describe_current_frame`.

## 3. Decisions

Each table ranks the options by correctness, safety, compatibility, fit, reversibility and validation cost; the first row is the decision. In-envelope means evidence, backward compatibility, no weakened control, no OSS/commercial boundary crossed, bounded rollback.

**D1. Hypotheses first, and the one log point that separates each.**

*BF-930 (a sentence whose synthesis or storage stalls).*

| # | Hypothesis (code evidence) | Separated by |
|---|---|---|
| B1 | **The store lock convoys.** One `asyncio.Lock` is held across `write`'s three thread hops; the reaper (`unlink_if_unchanged`), `unlink` and every other writer (camera frames `perception_frame`, uploads) take it too (`filesystem_store.py:328, 406, 449, 484, 499`) | store line `lock_wait_ms` large and `behind=` (`write:<origin>`, `unlink`, `reaper_unlink`, `list_by_origin`, `total_size`) |
| B2 | **The store's 4 threads are saturated** by `_find` globs, reads and writes (`ATTACHMENT_IO_WORKERS = 4`, `:47`) | `locate_ms` large with `lock_wait_ms` near 0 (the locate hop does almost no work: it is the canary for queueing); the `_find` line |
| B3 | **The index rewrite or the disk.** `_save_index_sync` rewrites the whole `.index.json` on every write (`:236-250`), so its cost grows with the entry count; the blob write competes with whatever else writes to disk | `index_ms` with `index_entries`; `blob_ms` |
| B4 | **The per-key synthesis queue.** One `asyncio.Lock` per Piper key serialises every sentence of every crew member that shares a voice and prosody set (`resident.py:401`) | synth line `lock_wait_ms` |
| B5 | **The voice executor queue.** 4 threads shared with rhubarb and ffmpeg (`VOICE_EXECUTOR_WORKERS = 4`, admission bound 16) | `pool_wait_ms` with `in_flight` |
| B6 | **Piper's own work:** a cold spawn (process start and model load) or CPU starvation | `work_ms` with `cold` |
| B7 | **The event loop was blocked** (the issue reports stalls in both stages of one sentence, which a common cause explains) | `resume_lag_ms` (the gap between the worker thread ending and the loop resuming the request); a store line whose steps are all late at once |

*BF-932 (a Captain message waits before the turn starts).*

| # | Hypothesis | Separated by |
|---|---|---|
| H1 | **The agent's concurrency queue.** At 4 active threads a Captain DM waits for a release | the existing `AD-672: Intent 'direct_message' queued ...` line (a free check on the existing log, item 1 of the last section) and the new `waited_ms` on `Promoted queued intent` |
| H2 | **Perceive or the per-message recall under load** (no model call in either: AST scan) | `BF-932: dm turn` `perceive_ms`, `recall_ms` |
| H3 | **The route's synchronous work on the event loop:** `ChatThreadStore` is plain `sqlite3` (`threads/__init__.py:36, 261-262`) called without `await` at `get_or_create_default_for_agent`, `maybe_auto_name` and `append_message` (`routers/agents.py:3008, 3110, 3127`) | route `thread_ms` |
| H4 | **The describe's unbounded steps** (the two `store.exists` hops around the 4 s cap) | route `hook_ms` (about 4 s plus two lookups at most) and the store's `find slow` line |
| H5 | **Route work after the hook:** scene rendering, `_capture_owned_steps_turn` (`:3605`), `observe_self_avatar` (`:3646`), the plan gate | route `dispatch_ms` |
| H6 | **The event loop was blocked** | the sum of the lines against the Captain's wall clock does not close; a voice line's `resume_lag_ms` in the same minute |
| H7 | **The LLM lane (BF-731)** | **outside the window:** the DM-recall line precedes the turn's first model call. Left out (below) |

**Left out, and why.** (a) The LLM lane and the turn's own model calls: the issue's window ends at the DM-recall line, before any model call of the turn; measuring them needs a line inside `LLMClient.complete`, the hottest path of the ship, for a question this window cannot contain. If the new lines exonerate every step before the recall and the Captain still sees slow turns, the next slice adds `lane_wait_ms` for Captain-priority calls. **This is narrower than the acceptance's list, by design.** (b) Per-step lines inside `force_describe_current_frame` (six return paths): its capped step is bounded by `wait_for`, and its two unbounded steps are `store.exists` calls whose time the store's `_find` line already reports with the sha prefix the consumer logs elsewhere. (c) The store's queue-versus-disk split inside one hop: it needs an in-thread stamp wrapped around the callables of `_run`, whose cancellation semantics were reviewed in two rounds (`filesystem_store.py:158-195`); the `locate_ms` canary stands in. (d) Time before the handler starts (the ASGI queue) and the browser's own round trip: neither is visible to the server; a DevTools observation by the Captain if everything above exonerates. (e) An always-on loop-lag task: a new component with a lifecycle (it would be a task the architecture check counts); named as the next step if `resume_lag_ms` or the sum check points at the loop.

**D2. Slicing.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Two slices: S1 BF-930 (with the helper it creates), S2 BF-932 (uses it); one batch, one gate, one pull request** | Each M3 names its own issue; no slice is an inert helper with no issue; S2 reverts first. The helper has seven uses across five packages, so it is worth a module and its cases |
| 2 | Three slices, the helper first (`Refs` both issues) | One more milestone set, and a helper slice that is "built, tested, inert" until the next one |
| 3 | Two private copies of the writer and the clock arithmetic | Seven repetitions of the same try/except; no single place to test "never raises" and "bounded" |
| 4 | One slice per file | Nine commits for one idea |

**D3. Shape of the lines.**

| # | Option | Judgement |
|---|---|---|
| 1 | **A new marker line per component: slow-only for storage and synthesis (they are per call and per frame), one per Captain DM for the reply path; the route's existing line gains one trailing field (the join key)** | Nothing is plumbed through a return value; each module owns its numbers; volume follows stalls (S1) or Captain messages (S2); additive only |
| 2 | Extend `BF-918: tts route` with every sub-step | Needs the service and the store to hand timings up through return values or a context variable: a changed return type or hidden coupling into the Cloud-Ready store seam |
| 3 | One summary line per request built by a collector | Same plumbing, plus state that outlives a request |

*Markers the Captain greps (exact):* `BF-930: attachment write slow`, `BF-930: attachment find slow`, `BF-930: piper request slow`, `BF-918: tts route` (existing), `BF-932: dm route`, `BF-932: dm turn`, `AD-672: Promoted queued intent` (existing), `AD-672: Intent 'direct_message' queued` (existing). *Units:* milliseconds, formatted `%.0f`, from `time.perf_counter()` (monotonic, sub-microsecond on Windows) except the queue's `waited_ms`, which uses that module's own `time.monotonic` stamp (`queued_at`, `concurrency_manager.py:42`); never wall time, never an absolute reading (ten digits would trip the phone-number redactor). *Correlation keys:* `id=<8 hex of the audio sha>` (route line and store lines; the consumer already logs `sha[:8]`); `intent=<8 hex of IntentMessage.id>` (route line and turn line; the id is `uuid4().hex` and is serialised on the wire, `mesh/intent.py:2067`); the agent id (`agent=<first 12>` in the route and turn lines; the queue lines carry the full id). Never message text, never a callsign. *Level:* INFO (the file handler's floor; the BF-918 precedent for the same route; WARNING would also move the boot warning counter, `__main__.py:156`). *Volume:* store and synthesis lines only when a call took at least `SLOW_STORE_CALL_MS` (250) or `SLOW_SYNTHESIS_MS` (750), then at most 12 per minute per store (writes), per store (finds) and per synthesis service, the rest counted and reported as `suppressed=N` on the next line written; the route and turn lines are one per Captain DM; the queue line is the existing one. *Consumers of an extended line, by what they read* (section 11 enumerates): the one existing test reads the substrings `synth_ms=`, `store_ms=`, `visemes_ms=`, `total_ms=`, `visemes=deferred` of the `BF-918: tts route` line; the BF-918 closing recipe reads `(\w+_ms)=(\d+)` over lines that contain `BF-918: tts route`: the new trailing `id=` field matches neither, and every other new line has a different marker; nothing reads `AD-672: Promoted queued intent`.

**D4. No behaviour change, and failure isolation.** The batch adds clock reads, three attribute writes (`_lock_holder`, `thread_started`, `thread_ended`), one `TimingLines` per owner and log calls. It adds **no await, no thread, no lock, no task**, and changes no return value, status code, call order or timeout (the awaits keep their order; the per-key lock, the store lock, the executors and the 4 s cap are untouched). Exception tier (`docs/development/engineering-principles.md`, "Additional Engineering Principles"): **Tier 1, swallow, justified**: a measurement is not a reason for a reply to fail, so `emit_line` and `TimingLines.emit` catch `Exception` (never `BaseException`: `asyncio.CancelledError` passes through) and leave a DEBUG line with the traceback; nothing is retried or re-raised. Level (same document, "Logging Standards"): INFO, like the line it joins; never WARNING or ERROR. **How the tests prove "no behaviour change":** the existing suites of each touched route and module stay green at G2 (named in section 4), and new pin cases assert what must not move: the response body keys and status of the TTS route; the store's return path, bytes, index entry and the lock being free after a write; the ENOSPC translation; the synthesizer's audio, degrade and warning for a failed Piper call; the DM route's reply, the call order (hook, then send), the 4.0 s cap and `raise_on_denial=True`; the queue line's old text as a prefix. **How they prove "the timings are real":** stubs that sleep a known time on a real thread or task (30 ms) with the line's field asserted `>= 25` (a lower bound only: a loaded machine can only make a measured step longer); the bound is proved with an injected clock.

**D5. Config.** **No key.** The two thresholds and the budget are module constants (`SLOW_STORE_CALL_MS`, `SLOW_SYNTHESIS_MS`, `TimingLines` defaults 12 per 60 s), the precedent of `ATTACHMENT_IO_WORKERS` and `VOICE_EXECUTOR_WORKERS` (BF-918 M4 rejected a key for the same reason: it moves the pinned dump, the facade field count and three generated files). So `scripts/gen_config_reference.py --check`, `scripts/check_config_profiles.py --check`, `scripts/check_config_facade.py --check` and the AD-1152 default-config digest are expected unchanged; **the oracle runs the three checks and the AD-1152 test (`tests/test_ad1152_agentic_correlation.py`) at G2 and any moved line is a hard stop**. The thresholds are set well above the sub-second sentence the BF-918 acceptance reports as normal and are tunable by a later one-line edit if the first live call shows them wrong.

**D6. Reading the result.** (a) **A documented one-line recipe in the closing comment** (the BF-918 closing recipe, `prompts/bf-918-tts-first-audio-latency.md:6866`, with the marker as a parameter); (b) a script under `scripts/` with its own test; (c) nothing. Decision: **(a)**: it gives p50 and p95 for every `_ms` field of a marker with no new surface, and the one existing precedent is accepted by the same reader. A script would add a file, a CLI and a test for a calculation a one-liner does; if the Captain wants it re-run often, it is a later slice. The recipe (read-only; it reads the log path it builds and nothing else):

```
$env:M = 'BF-918: tts route'    # or 'BF-932: dm route', 'BF-932: dm turn', 'BF-930: attachment write slow', 'BF-930: piper request slow', "AD-672: Promoted queued intent 'direct_message'"
d:/ProbOS/.venv/Scripts/python.exe -I -c "import re,glob,statistics as s,os;v={};[v.setdefault(k,[]).append(float(x)) for f in glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\ProbOS\data\logs\probos.log*')) for l in open(f,encoding='utf-8',errors='replace') if os.environ['M'] in l for k,x in re.findall(r'(\w+_ms)=(\d+)',l)];print({k:(s.median(x),sorted(x)[int(0.95*(len(x)-1))],len(x)) for k,x in v.items()})"
```

The pre-turn wait of one DM is `thread_ms + prep_ms + hook_ms + dispatch_ms` (route line) plus `waited_ms` (the queue line of the same agent, when there is one) plus `perceive_ms + recall_ms` (turn line), joined by `intent=`.

**D7. Closure.** Both issues stay open: every M3 says `Refs`, never `Closes`. What closes from tests: the lines exist, carry the fields, are bounded, survive the redactor, are failure-isolated, and change nothing (section 6). What does not: the live measurement, the p50/p95, the audible-gap count, the fix. **The live actions, and what the data must show to choose a fix, are the last section.**

**D8. Public text (overrides the acceptance where it differs).** This repository is public: no test, comment, tracker line, commit message or part of this contract holds a crew name, a thread id, a timestamp or a stall length from the vessel. Fixtures are synthetic: a stub that sleeps 30 ms, a fixed 64-hex sha, `test-id` and `test-agent` as agent ids. **Overrides:** (a) the acceptance's "re-measure on the live vessel and post p50 and p95 ... plus the count of audible gaps" and "post the before and after numbers" are posted on the issues by the Captain or the orchestrator, never written into the repository; (b) the issue's evidence tables are not fixtures.

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. All commands run **from the repository root**, exactly as typed. **Who runs what.** The Builder may run only the focused pytest files named in G1 and G2 (always `-n 0`) and the architecture check. **Mine (the orchestrator's):** the broad gate, the mutation campaign, any wide run, the ledger comparison against the measured diff, the pull request.

**M0 (each slice, on the head before the slice):** record the collected count (`--collect-only -q`) of every existing file named in that slice's G2; the new files do not exist yet.

| Slice | M | Blocks | Gate |
|---|---|---|---|
| S1 (BF-930) | M1 | N1-1 | G1 |
| S1 | M2 | P2-0 (the helper), P2-1 to P2-11 (the store), P2-12 to P2-20 (the synthesizer and the route), then N2-1 (the marker) | G2 |
| S1 | M3 | P3-1, P3-2, ledger | G3 |
| S2 (BF-932) | M1 | N1-1 | G1 |
| S2 | M2 | P2-1 to P2-9 (the route, the agent, the queue), then N2-1 (the marker) | G2 |
| S2 | M3 | P3-1, P3-2, ledger | G3 |

**S1.**
- **G1.** `PY -m pytest tests/test_bf930_voice_path_timing.py -q -n 0 -p no:randomly`. **Expected:** the 3 controls (T3, T6, T10: the pins that hold on the base) pass and the other 16 cases xfail (`raises=AssertionError, strict=True`: an XPASS or any other exception is a FAIL). Then once with `--runxfail`: each of the 16 must stop at its own `assert` (a missing line, a missing field), never at an import or a premise (the helper cases load the module by `importlib.util.find_spec` and assert it exists, so they stop at that assert on the base).
- **G2 (suite order).** (1) `PY -m pytest tests/test_bf918_tts_latency.py tests/test_bf918_attachment_io.py tests/test_bf918_tts_retention.py tests/test_ad720_attachment_store.py tests/test_attachment_reaper.py tests/test_bf930_voice_path_timing.py -q -n 0 -p no:randomly` (the voice route and service, the store's I/O threads, retention, the store's contract, the reaper, and the new file). (2) `PY -m pytest tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_egress_census.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly` (the censuses read `filesystem_store.py`, `resident.py` and `agents.py` by file and scope, not by line: section 11; the layer test reads the new `utils` module). (3) `PY -P scripts/check_architecture_principles.py --check`. (4) the three config checks and the AD-1152 test named in D5. **Expected:** the new file 19 passed; every other file 0 failed with collected counts equal M0; the checks clean.

**S2.**
- **G1.** `PY -m pytest tests/test_bf932_reply_path_timing.py -q -n 0 -p no:randomly`. **Expected:** the controls (R4, R6, C2, A2: 4 cases) pass; the other 7 xfail strictly. Then once with `--runxfail`: each at its own `assert`.
- **G2.** (1) `PY -m pytest tests/test_ad730_agent_chat_vision.py tests/test_ad791a_chat_threads_wiring.py tests/test_ad724_dm_hardening.py tests/test_ad794_auto_name.py tests/test_ad809_personality.py tests/test_ad1156_plan_execute_mode.py tests/test_ad672_concurrency_manager.py tests/test_cognitive_agent.py tests/test_bf932_reply_path_timing.py -q -n 0 -p no:randomly` (the DM route's callers, the queue's tests, the agent's lifecycle tests, and the new file). (2) `PY -m pytest tests/test_ad1343_stop_seam_inventory.py tests/test_ad1346_admission_service.py tests/test_ad1346_admission_ticket_issue.py -q -n 0 -p no:randomly` (they key on `_agent_chat_impl` and `handle_intent` by scope). (3) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file 11 passed; every other file 0 failed with collected counts equal M0.

**G3 (each M3).** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. **The ledger covers BF numbers as well as AD numbers** (`scripts/gen_ad_ledger.py:113`, `_TOKEN_RE = \b(AD|BF)-(\d{1,5})...`; it reads the head of a PROGRESS entry, a DECISIONS heading and the git-log subjects). **The contract commit's subject names BF-930 and BF-932**, so the **first regeneration after it (S1 M3's)** moves **both** numbers: BF-930 and BF-932 added to the accounted BF list and removed from the unaccounted BF list, the shipped BF count up by the same two (the measured shape of the BF-933 contract's note for one number); **S2 M3 moves no number**. Every M3 also changes the report's git-log row (the pinned snapshot's time, head id and subject count), shifts the report's skipped-line numbers for `PROGRESS.md` by the lines its entry adds (S1: 4; S2: 4), and the non-check run also rewrites `docs/development/ad-ledger-snapshot.json` (its git layer gains the subjects it had not seen). **I did not measure these diffs** (the two UI-only batches change the trackers before this batch builds): the oracle measures them, and **any changed row of a number other than 930 and 932 is a hard stop**.

**Final gate (mine, once, after the Diff Reviewer's findings are repaired and the reviewed tree is committed locally):** the mutation rows of section 9, and `PY scripts/run_test_gate.py --label bf930-932 --receipt logs/gates/bf930-932.receipt.json` (its preflight runs the ledger, the three config checks, the architecture, seam and store checks). **Harness rule.** No source change made to pass a test, no skip, no loosened assertion; a failing new case at G2, or any existing test failing, goes back to the Architect.

## 5. Commit messages

- **Contract commit (the orchestrator's):** `BF-930, BF-932: contract for log-only timing of the spoken-reply and Captain-DM paths (#1668, #1670)`.
- **S1 M1:** `BF-930 S1 M1: tests for the attachment store, the resident synthesizer and the TTS route writing timing lines, xfail until built (#1668)`
- **S1 M2:** `BF-930 S1 M2: slow store writes and lookups and slow Piper requests log where their time went; the TTS route line carries the audio id (#1668)`
- **S1 M3:** `BF-930 S1 M3: trackers and ledger (#1668)`; its body ends with the line `Refs #1668.`
- **S2 M1:** `BF-932 S2 M1: tests for the Captain-DM route, the agent turn and the concurrency queue writing timing lines, xfail until built (#1670)`
- **S2 M2:** `BF-932 S2 M2: one timeline line per Captain DM, one turn-start line per HXI DM, and the queue wait on promotion (#1670)`
- **S2 M3:** `BF-932 S2 M3: trackers and ledger (#1670)`; its body ends with the line `Refs #1670.`

Neither issue is closed by its slice (the cause is not yet known; the fix and the live measurement come after), so none carries `Closes`. The pull request body lists the live actions of the last section as post-merge actions. No message names a crew member, a thread or a live figure.

## 6. Tests

**S1 (`tests/test_bf930_voice_path_timing.py`, new; 19 cases).** Imports: the existing modules only (`probos.attachments.filesystem_store`, `probos.audio.tts.resident`, `probos.routers.avatars`, `probos.routers.chat`, `probos.security.pii_redaction`); the helper is loaded through `_helper()` (`importlib.util.find_spec("probos.utils.step_timing")`, `assert spec is not None, "the helper does not exist yet"`, then `importlib.import_module`), so the file loads before M2. Fixtures are the BF-918 file's own (`tests/test_bf918_tts_latency.py:74-90` `launcher`, `service`, `:538-558` `voice_client`, `:560-569` `_stub_rhubarb`, copied, not imported). `built` is `pytest.mark.xfail(raises=AssertionError, strict=True)` unless `BF930_RUNXFAIL=1`. **Every case restores:** the module constants it patches (`monkeypatch`), the store's class-level stubs (`monkeypatch`), `caplog` levels (`caplog.set_level(..., logger=...)` is restored by pytest), `chat_router_mod._ATTACHMENT_STORE_CACHE.clear()` before and after, and the voice service is closed by its fixture; **no `TimingLines` is module-level** (one per store, per service), so no budget outlives a case.

| Case | Kind | Asserts |
|---|---|---|
| H1 `ms_between` is milliseconds and never negative | built | `ms_between(1.0, 1.5) == 500.0`; `ms_between(2.0, 1.0) == 0.0` |
| H2 `emit_line` writes one INFO line and says so | built | one record at INFO with the formatted text; returns True |
| H3 a spent budget declines lines and the next line written says how many | built | `max_lines=2`, injected clock: the third emit inside the window returns False; after the window the next line ends `suppressed=1` and the count resets |
| H4 a budget of 0 is unbounded | built | 50 emits, 50 records |
| H5 a logger that raises never reaches the caller | built | stub logger whose `info` raises: `emit_line` and `TimingLines.emit` return False, no exception; `debug` was called once with `exc_info` |
| T1 a slow write reports each step | built | threshold patched to 0; class-level stub of `_save_index_sync` sleeps 30 ms then calls the original; the line has `lock_wait_ms`, `locate_ms`, `blob_ms`, `index_ms`, `behind=none`, `index_entries=1`, `id=<8 hex>`, `origin=chat_attachment`; `index_ms >= 25` |
| T2 a write that waits for the lock names what it waited behind (2 cases) | built | holder A is a write with origin `perception_frame` (stub of `_locate_sync` sleeps 30 ms and sets an event) or an `unlink` (stub of `_save_index_sync`); B starts when the event is set; B's line has `lock_wait_ms >= 25` and `behind=write:perception_frame` or `behind=unlink` |
| T3 a fast write logs nothing and changes nothing | control | default threshold: no `BF-930: attachment write slow` record; the return equals `root/<sha>.wav`; the bytes are on disk; the index holds the entry with its origin; `store._lock.locked()` is False |
| T4 a slow lookup reports its time and the index size | built | threshold 0, `exists()` of a stored blob: `BF-930: attachment find slow` with `find_ms=` and `index_entries=1` |
| T5 the store's lines are bounded | built | threshold 0, 30 writes: exactly 12 `write slow` records; the 13th and later are counted (the next record after a clock jump carries `suppressed=`, proved by H3) |
| T6 a failed write logs no timing line and raises as before | control | `Path.write_bytes` stub raises `OSError(errno.ENOSPC, ...)`: `AttachmentStoreFullError` is raised; no `write slow` record |
| T7 a slow synthesis reports its steps | built | threshold 0, `PiperWorker._request` stubbed to sleep 30 ms and return `PiperOutcome(b"x", "ok")`: the line has every field of D1, `result=ok`; `work_ms >= 25` |
| T8 a request that queues for the voice executor reports its pool wait | built | `VoiceSynthesisService(workers=1)`, the one thread occupied by `service.executor.submit(time.sleep, 0.05)`: `pool_wait_ms >= 40` |
| T9 a request that waits for its key reports its lock wait | built | two concurrent `synthesize` calls on one key, the stubbed `_request` sleeping 30 ms: the larger `lock_wait_ms` of the two lines is `>= 25` |
| T10 the audio and the degrade are unchanged | control | success returns the bytes and `service` ends with no request in flight; a stubbed `PiperOutcome(None, "timeout")` returns None and still logs the existing `piper timed out` WARNING |
| T11 the route line keeps its fields and gains the audio id | built | the 7 old fields in order, then `id=` equal to the first 8 hex of the body's `audio_attachment_id`; the recipe's `(\w+_ms)=(\d+)` over the line yields exactly `synth_ms`, `store_ms`, `visemes_ms`, `total_ms`, `audio_ms` |
| T12 one stalled store is visible from the route line to the store line (chain) | built | threshold 0 and the 30 ms `_save_index_sync` stub; POST `/api/avatars/tts`: HTTP 200; body keys equal `{backend, audio_attachment_id, mime, visemes, visemes_deferred, duration_ms}`; the route line's `id=X` equals the store line's `id=X`; route `store_ms >= 25` and store `index_ms >= 25` |
| T13 every new line survives the log redactor | built | for every `BF-930:` record of T1, T2, T4, T7 and T12: `PIIRedactor.redact_all(text) == text` |

The pass-before-build set is the three controls T3, T6 and T10 (the base has no line and changes nothing). **How each built case fails on the base:** H1 to H5 at `assert spec is not None`; T1, T2, T4, T5, T7 to T9 at `assert <the expected record>` (no such record exists); T11 at the `id=` assertion; T12 at the store-line assertion; T13 at its premise that records exist.

**S2 (`tests/test_bf932_reply_path_timing.py`, new; 11 cases).** The route harness is `tests/test_ad730_agent_chat_vision.py`'s (`_make_runtime`, `_req`, `_CREW_PATCH`, `await agent_chat("test-id", req, runtime)`, copied, not imported), with `runtime.config.perception = SimpleNamespace(enabled=True, dm_force_describe_enabled=True)`, `runtime.vision_consumer` a small class whose `force_describe_current_frame` records the call and sleeps 30 ms (no `MagicMock` at that boundary, the BF-287 rule the AD-733c-1 file states), and `runtime.intent_bus.send` an `AsyncMock` with a `side_effect` that sleeps 30 ms and returns the `MagicMock` result of the harness. **The first assertion of every route case is `runtime.intent_bus.send.assert_awaited_once()`**, so a harness that does not reach the send fails at a premise the oracle reads (this consult could not run it). The agent harness is `tests/test_cognitive_agent.py`'s construction of a `CognitiveAgent` and its `handle_intent(intent)` calls (`:227`, `:244`, ...); the oracle names the exact helper when it builds the case (`perceive` and `_recall_relevant_memories` are replaced by stubs that sleep 30 ms; `decide` raises a sentinel so the turn ends right after the line). **Every case restores** (`monkeypatch`, `caplog` levels, the `patch(...)` context), and the new lines are module-stateless (`emit_line`), so no state outlives a case.

| Case | Kind | Asserts |
|---|---|---|
| R1 a Captain DM writes one route line with each step and the intent id | built | one `BF-932: dm route` record; `hook=ran`, `hook_ms >= 25`, `send_ms >= 25`, `total_ms >= 50`, `sent=yes`; `intent=` equals `runtime.intent_bus.send.call_args.args[0].id[:8]`; `agent=test-id` |
| R2 a DM with perception off says the hook was skipped | built | `hook=skipped`, `hook_ms=0`; the consumer was not called |
| R3 a hook that raises is still timed and the reply still goes out | built | the consumer raises; one route line with `hook=ran`; the reply text equals the stub's |
| R4 the route's order, cap and reply are unchanged | control | the call order recorded is `[consumer, send]`; `timeout_s == 4.0`; `send` was called with `raise_on_denial=True`; the returned dict's `response` equals the stub's text |
| R5 the route line survives the log redactor | built | `PIIRedactor.redact_all(text) == text` for the R1 record |
| R6 a failing logger changes nothing | control | with `emit_line` replaced by a function that raises, the route still returns the same reply (the helper's own isolation is proved by S1 H5; this pins that the route calls it where an exception would matter) |
| C1 a promoted intent reports how long it waited | built | `ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=2)`: hold the slot, queue a `direct_message` at priority 8, release after 30 ms: the `Promoted queued intent` record ends `waited_ms=<n>` with `n >= 25`, and its text begins exactly `AD-672: Promoted queued intent 'direct_message' for agent test-agent at priority=8` |
| C2 an intent that gets a slot at once logs no promotion line | control | no `Promoted queued intent` record |
| A1 an HXI DM turn logs its perceive and recall times with the intent id | built | one `BF-932: dm turn` record with `perceive_ms >= 25` and `recall_ms >= 25`; `intent=` equals `intent.id[:8]` |
| A2 a DM from another sender logs no turn line | control | the same turn with `params["from"]` not `hxi_profile`: no `BF-932: dm turn` record |

(A2 is a control that holds on the base; **R4, R6, C2 and A2 are the four controls G1 expects to pass**.) **The chain case:** R1b `one Captain DM is joinable from the route line to the turn line` replaces the harness's `send` by a function that calls the agent's `handle_intent(intent)` and asserts the route record's `intent=` equals the turn record's; it is the eleventh case (R1b, A1 and A2 need the agent harness the oracle names). **How each built case fails on the base:** at `assert <the expected record>` (no such record exists); C1 at the `waited_ms` suffix assertion.

**Tests that pin the old behaviour, by command** (section 11 holds the commands and their output): `rg -n "tts route|synth_ms|store_ms"` over `tests scripts docs` finds the one reader, `tests/test_bf918_tts_latency.py:609-610` (substrings only: still true). `rg -n "Promoted queued intent|queued for agent|waiting for release"` over `tests src` finds no test reader. The store's M4 tests (`tests/test_bf918_attachment_io.py:157, 333, 402`) patch `_save_index_sync` at class level and hold it behind a gate: the batch does not touch `_save_index_sync` or `_run`, and its stamps run after the hop returns. **Nothing needs updating.**

## 7. The contract

Labels restart in each slice. Section 6 names the cases; this section gives every block. `PY`, the commands and who runs them are in section 4. SEARCH text is LF; the working copies are CRLF (the apply tool matches on LF). **Every SEARCH below occurs exactly once in its file on `f614a31d`, starts at a line start, and is ASCII** (section 11: run on the LF blobs: 30 SEARCHes, 0 problems); no block's SEARCH overlaps another's; **a block's REPLACE changes the line count of a later block's position but not its text**, so the blocks of one file are applied in label order and none re-measures a line number. The REPLACE text of every block is ASCII.

### 7.1 Slice S1 (BF-930: the spoken-reply path)

#### S1 M1

**N1-1.** New file `tests/test_bf930_voice_path_timing.py` (19 cases; section 6 names them). It imports nothing that M2 creates at module level.

```python
"""BF-930 (#1668): timing lines of the spoken-reply path (the attachment store, the resident synthesizer, the TTS route).

Synthetic fixtures only: stubs that sleep 30 ms, a fixed fixture, no live figure. The cases marked ``built`` fail on the
base at their own assert and pass once M2 is applied; ``BF930_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import importlib
import importlib.util
import logging
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments import filesystem_store
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.store import AttachmentStoreFullError
from probos.audio.tts import TTSResult
from probos.audio.tts import resident
from probos.audio.tts.resident import PiperOutcome, PiperWorker, PiperWorkerKey, VoiceSynthesisService
from probos.avatars.rhubarb_backend import VisemeFrame
from probos.config import AttachmentsConfig, LipSyncConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.security.pii_redaction import PIIRedactor

built = (
    (lambda func: func)
    if os.environ.get("BF930_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)

_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
_WRITE = "BF-930: attachment write slow"
_FIND = "BF-930: attachment find slow"
_PIPER = "BF-930: piper request slow"
_STORE_LOGGER = "probos.attachments.filesystem_store"
_VOICE_LOGGER = "probos.audio.tts.resident"


def _helper():
    spec = importlib.util.find_spec("probos.utils.step_timing")
    assert spec is not None, "the helper does not exist yet"
    return importlib.import_module("probos.utils.step_timing")


def _lines(caplog, marker: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if marker in r.getMessage()]


def _field(line: str, name: str) -> str:
    found = re.search(rf"\b{name}=(\S+)", line)
    assert found, f"{name} missing from {line!r}"
    return found.group(1)


def _one(lines: list[str]) -> str:
    assert len(lines) == 1, f"expected exactly one line, found {len(lines)}"
    return lines[0]


def _last(lines: list[str]) -> str:
    assert lines, "no such line was written"
    return lines[-1]


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _key() -> PiperWorkerKey:
    return PiperWorkerKey(
        binary="piper", model="m.onnx", noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35,
    )


def _slow_index(monkeypatch: pytest.MonkeyPatch, seconds: float = 0.03) -> None:
    real = FilesystemAttachmentStore._save_index_sync

    def slow(self) -> None:
        time.sleep(seconds)
        real(self)

    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", slow)


def _stub_request(monkeypatch: pytest.MonkeyPatch, delay: float = 0.03, outcome: PiperOutcome | None = None) -> None:
    def request(self, text, timeout):
        time.sleep(delay)
        return outcome or PiperOutcome(b"WAV", "ok")

    monkeypatch.setattr(PiperWorker, "_request", request)


# --- the helper -------------------------------------------------------------------------------


@built
def test_h1_ms_between_is_milliseconds_and_never_negative() -> None:
    step = _helper()
    assert step.ms_between(1.0, 1.5) == 500.0
    assert step.ms_between(2.0, 1.0) == 0.0


@built
def test_h2_emit_line_writes_one_info_line_and_says_so(caplog) -> None:
    step = _helper()
    logger = logging.getLogger("bf930.test.h2")
    caplog.set_level(logging.INFO, logger="bf930.test.h2")
    assert step.emit_line(logger, "BF-930: probe a=%d", 7) is True
    records = [r for r in caplog.records if r.name == "bf930.test.h2"]
    assert [r.getMessage() for r in records] == ["BF-930: probe a=7"] and records[0].levelno == logging.INFO


@built
def test_h3_a_spent_budget_declines_lines_and_the_next_line_written_says_how_many(caplog) -> None:
    step = _helper()
    now = [0.0]
    logger = logging.getLogger("bf930.test.h3")
    caplog.set_level(logging.INFO, logger="bf930.test.h3")
    lines = step.TimingLines(logger, max_lines=2, window_s=60.0, clock=lambda: now[0])
    assert [lines.emit("BF-930: probe") for _ in range(3)] == [True, True, False]
    now[0] = 61.0
    assert lines.emit("BF-930: probe") is True
    texts = [r.getMessage() for r in caplog.records if r.name == "bf930.test.h3"]
    assert texts[-1].endswith("suppressed=1") and not any("suppressed" in t for t in texts[:-1])
    assert lines.emit("BF-930: probe") is True
    assert not [r.getMessage() for r in caplog.records if r.name == "bf930.test.h3"][-1].endswith("suppressed=1")


@built
def test_h4_a_budget_of_zero_is_unbounded(caplog) -> None:
    step = _helper()
    logger = logging.getLogger("bf930.test.h4")
    caplog.set_level(logging.INFO, logger="bf930.test.h4")
    lines = step.TimingLines(logger, max_lines=0)
    assert all(lines.emit("BF-930: probe") for _ in range(50))
    assert len([r for r in caplog.records if r.name == "bf930.test.h4"]) == 50


@built
def test_h5_a_logger_that_raises_never_reaches_the_caller() -> None:
    step = _helper()

    class _Broken:
        def __init__(self) -> None:
            self.debug_calls: list[bool] = []

        def info(self, *_a, **_k) -> None:
            raise RuntimeError("handler failed")

        def debug(self, *_a, **kwargs) -> None:
            self.debug_calls.append(bool(kwargs.get("exc_info")))

    broken = _Broken()
    assert step.emit_line(broken, "BF-930: probe") is False
    assert step.TimingLines(broken).emit("BF-930: probe") is False
    assert broken.debug_calls == [True, True]


# --- the attachment store ---------------------------------------------------------------------


@built
@pytest.mark.asyncio
async def test_t1_a_slow_write_reports_each_step(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    _slow_index(monkeypatch)
    store = FilesystemAttachmentStore(tmp_path)
    sha = _sha("t1")
    await store.write(sha, b"x", "audio/wav")
    line = _one(_lines(caplog, _WRITE))
    for name in ("total_ms", "lock_wait_ms", "locate_ms", "blob_ms", "index_ms", "index_entries", "bytes"):
        float(_field(line, name))
    assert _field(line, "id") == sha[:8] and _field(line, "origin") == "chat_attachment"
    assert _field(line, "behind") == "none" and _field(line, "index_entries") == "1"
    assert float(_field(line, "index_ms")) >= 25


@built
@pytest.mark.asyncio
@pytest.mark.parametrize("holder", ["write", "unlink"])
async def test_t2_a_write_that_waits_for_the_lock_names_what_it_waited_behind(tmp_path, monkeypatch, caplog, holder) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    sha_a, sha_b = _sha("t2a"), _sha("t2b")
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    if holder == "write":
        real_locate = FilesystemAttachmentStore._locate_sync

        def slow_locate(self, content_hash, mime):
            loop.call_soon_threadsafe(entered.set)
            time.sleep(0.06)
            return real_locate(self, content_hash, mime)

        monkeypatch.setattr(FilesystemAttachmentStore, "_locate_sync", slow_locate)
        first = asyncio.create_task(store.write(sha_a, b"a", "audio/wav", origin="perception_frame"))
        expected = "write:perception_frame"
    else:
        await store.write(sha_a, b"a", "audio/wav")
        real_save = FilesystemAttachmentStore._save_index_sync

        def slow_save(self) -> None:
            loop.call_soon_threadsafe(entered.set)
            time.sleep(0.06)
            real_save(self)

        monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", slow_save)
        first = asyncio.create_task(store.unlink(sha_a))
        expected = "unlink"
    await asyncio.wait_for(entered.wait(), 5)
    await store.write(sha_b, b"b", "audio/wav")
    await first
    line = _one([text for text in _lines(caplog, _WRITE) if _field(text, "id") == sha_b[:8]])
    assert float(_field(line, "lock_wait_ms")) >= 25 and _field(line, "behind") == expected


@pytest.mark.asyncio
async def test_t3_a_fast_write_logs_nothing_and_changes_nothing(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    sha = _sha("t3")
    path = await store.write(sha, b"x", "audio/wav", origin="tts_audio")
    assert path == (tmp_path / f"{sha}.wav").resolve() and path.read_bytes() == b"x"
    assert store._index[sha]["origin"] == "tts_audio"  # noqa: SLF001
    assert store._lock.locked() is False  # noqa: SLF001
    assert not _lines(caplog, "BF-930:")


@built
@pytest.mark.asyncio
async def test_t4_a_slow_lookup_reports_its_time_and_the_index_size(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    sha = _sha("t4")
    await store.write(sha, b"x", "audio/wav")
    assert await store.exists(sha) is True
    line = _last(_lines(caplog, _FIND))
    float(_field(line, "find_ms"))
    assert _field(line, "index_entries") == "1" and _field(line, "id") == sha[:8]


@built
@pytest.mark.asyncio
async def test_t5_the_stores_lines_are_bounded(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    for seed in range(30):
        await store.write(_sha(f"t5-{seed}"), bytes([seed]), "audio/wav")
    assert len(_lines(caplog, _WRITE)) == 12


@pytest.mark.asyncio
async def test_t6_a_failed_write_logs_no_timing_line_and_raises_as_before(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)

    def full(self, data):
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(Path, "write_bytes", full)
    with pytest.raises(AttachmentStoreFullError):
        await store.write(_sha("t6"), b"x", "audio/wav")
    assert not _lines(caplog, _WRITE)


# --- the resident synthesizer -----------------------------------------------------------------


@built
@pytest.mark.asyncio
async def test_t7_a_slow_synthesis_reports_its_steps(monkeypatch, caplog) -> None:
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_VOICE_LOGGER)
    _stub_request(monkeypatch)
    service = VoiceSynthesisService()
    try:
        assert await service.synthesize(_key(), "hello", 5.0) == b"WAV"
    finally:
        service.close()
    line = _one(_lines(caplog, _PIPER))
    for name in ("total_ms", "lock_wait_ms", "claim_ms", "pool_wait_ms", "work_ms", "resume_lag_ms", "in_flight", "chars"):
        float(_field(line, name))
    assert _field(line, "result") == "ok" and _field(line, "cold") in ("yes", "no")
    assert float(_field(line, "work_ms")) >= 25


@built
@pytest.mark.asyncio
async def test_t8_a_request_that_queues_for_the_voice_executor_reports_its_pool_wait(monkeypatch, caplog) -> None:
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_VOICE_LOGGER)
    _stub_request(monkeypatch, delay=0.0)
    service = VoiceSynthesisService(workers=1)
    try:
        service.executor.submit(time.sleep, 0.08)
        assert await service.synthesize(_key(), "hello", 5.0) == b"WAV"
    finally:
        service.close()
    assert float(_field(_last(_lines(caplog, _PIPER)), "pool_wait_ms")) >= 40


@built
@pytest.mark.asyncio
async def test_t9_a_request_that_waits_for_its_key_reports_its_lock_wait(monkeypatch, caplog) -> None:
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_VOICE_LOGGER)
    _stub_request(monkeypatch, delay=0.05)
    service = VoiceSynthesisService()
    try:
        await asyncio.gather(service.synthesize(_key(), "a", 5.0), service.synthesize(_key(), "b", 5.0))
    finally:
        service.close()
    texts = _lines(caplog, _PIPER)
    assert len(texts) == 2
    assert max(float(_field(text, "lock_wait_ms")) for text in texts) >= 25


@pytest.mark.asyncio
async def test_t10_the_audio_and_the_degrade_are_unchanged(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_VOICE_LOGGER)
    service = VoiceSynthesisService()
    try:
        _stub_request(monkeypatch, delay=0.0)
        assert await service.synthesize(_key(), "hello", 5.0) == b"WAV"
        _stub_request(monkeypatch, delay=0.0, outcome=PiperOutcome(None, "timeout"))
        assert await service.synthesize(_key(), "hello", 5.0) is None
        with service.admit() as admitted:
            assert admitted is True
    finally:
        service.close()
    assert "piper timed out" in caplog.text


# --- the route ----------------------------------------------------------------------------------


@pytest.fixture
async def voice_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    service = VoiceSynthesisService()
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(backend="rhubarb"),
            tts=TTSConfig(backend="piper"),
        ),
        voice_synthesis=service,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    class _StubBackend:
        name = "piper"

        async def synthesize(self, text, emotion=None, voice_override=None):
            return TTSResult(audio_bytes=_WAV, mime="audio/wav")

    async def _visemes(audio_path, **_kw):
        return [VisemeFrame(time=0.0, duration=0.1, viseme="aa")]

    monkeypatch.setattr("probos.avatars.rhubarb_backend.generate_visemes", _visemes)
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _StubBackend())
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    service.close()


@built
@pytest.mark.asyncio
async def test_t11_the_route_line_keeps_its_fields_and_gains_the_audio_id(voice_client, caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.avatars")
    body = (await voice_client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})).json()
    [line] = _lines(caplog, "BF-918: tts route")
    order = [line.index(name) for name in ("synth_ms=", "store_ms=", "visemes_ms=", "total_ms=", "visemes=deferred", "audio_ms=")]
    assert order == sorted(order) and line.endswith(f"id={body['audio_attachment_id'][:8]}")
    assert [k for k, _v in re.findall(r"(\w+_ms)=(\d+)", line)] == ["synth_ms", "store_ms", "visemes_ms", "total_ms", "audio_ms"]


@built
@pytest.mark.asyncio
async def test_t12_one_stalled_store_is_visible_from_the_route_line_to_the_store_line(voice_client, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    _slow_index(monkeypatch)
    caplog.set_level(logging.INFO)
    answer = await voice_client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})
    body = answer.json()
    assert answer.status_code == 200
    assert set(body) == {"backend", "audio_attachment_id", "mime", "visemes", "visemes_deferred", "duration_ms"}
    route = _one(_lines(caplog, "BF-918: tts route"))
    store = _one(_lines(caplog, _WRITE))
    assert _field(route, "id") == _field(store, "id") == body["audio_attachment_id"][:8]
    assert float(_field(route, "store_ms")) >= 25 and float(_field(store, "index_ms")) >= 25


@built
@pytest.mark.asyncio
async def test_t13_every_new_line_survives_the_log_redactor(voice_client, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    _slow_index(monkeypatch)
    _stub_request(monkeypatch)
    caplog.set_level(logging.INFO)
    await voice_client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})
    service = VoiceSynthesisService()
    try:
        await service.synthesize(_key(), "hello", 5.0)
    finally:
        service.close()
    texts = _lines(caplog, "BF-930:") + _lines(caplog, "BF-918: tts route")
    assert len(texts) >= 3  # the route line, the store's write line and the synthesizer's line
    assert all(PIIRedactor.redact_all(text) == text for text in texts)
```

(Counting: H1 to H5 are 5 cases; T1, T2 (two parametrized cases), T3, T4, T5, T6 are 7; T7 to T10 are 4; T11 to T13 are 3: **19 cases**, of which the three controls T3, T6 and T10 pass on the base and the other 16 are `built`. The count is measured (amendment A1): G1 gives `3 passed, 16 xfailed (19)`.)

The module-level `built` marker is the only shared name of the file; no case touches a module-level counter or budget.

#### S1 M2

Apply the blocks in label order. `P2-0` creates the helper; `P2-1` to `P2-11` edit `src/probos/attachments/filesystem_store.py`; `P2-12` to `P2-19` edit `src/probos/audio/tts/resident.py`; `P2-20` edits `src/probos/routers/avatars.py`.

**P2-0.** New file `src/probos/utils/step_timing.py` (imports only the standard library, so the layer test's rule for `utils` holds):

```python
"""BF-930 / BF-932: timing lines for the spoken-reply path and the Captain-DM reply path (log-only).

These lines say where the time of one call went. They change no result, order, status or timeout of
what they measure. Durations are milliseconds between two readings of one monotonic clock
(``time.perf_counter``), never wall time. A failure while writing a line is dropped at DEBUG (Tier 1,
swallow: a measurement is never a reason for a reply to fail); ``asyncio.CancelledError`` is not an
``Exception`` and passes through.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable


def ms_between(start: float, end: float) -> float:
    """Milliseconds from ``start`` to ``end``, two readings of the same monotonic clock; never negative."""
    return max(0.0, (end - start) * 1000.0)


def emit_line(logger: logging.Logger, message: str, *args: object) -> bool:
    """Write ``message % args`` at INFO. Never raises; True when the line was written."""
    try:
        logger.info(message, *args)
        return True
    except Exception:
        logger.debug("BF-930: a timing line failed and was dropped: %s", message, exc_info=True)
        return False


class TimingLines:
    """The INFO timing lines of one component instance: at most ``max_lines`` per ``window_s``.

    A line the budget declines is counted, and the next line written ends with ``suppressed=N``, so a
    reader knows the log is not the whole story. ``max_lines`` of 0 or less sets no bound. Make one per
    owner (a store, a service), never a module-level one: its budget is state.
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        max_lines: int = 12,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._logger = logger
        self._max_lines = max_lines
        self._window_s = window_s
        self._clock = clock
        self._written: deque[float] = deque()
        self._suppressed = 0

    def emit(self, message: str, *args: object) -> bool:
        """Write the line unless this window's budget is spent; True when it was written."""
        try:
            if self._max_lines > 0:
                now = self._clock()
                while self._written and now - self._written[0] >= self._window_s:
                    self._written.popleft()
                if len(self._written) >= self._max_lines:
                    self._suppressed += 1
                    return False
                self._written.append(now)
            if self._suppressed:
                message, args = message + " suppressed=%d", (*args, self._suppressed)
                self._suppressed = 0
        except Exception:
            self._logger.debug("BF-930: a timing budget failed; the line was dropped: %s", message, exc_info=True)
            return False
        return emit_line(self._logger, message, *args)
```

**P2-1** (`src/probos/attachments/filesystem_store.py`: the import).
SEARCH:
```
from probos.attachments.store import (
    ATTACHMENT_ORIGINS,
    AttachmentStoreFullError,
)
```
REPLACE:
```
from probos.attachments.store import (
    ATTACHMENT_ORIGINS,
    AttachmentStoreFullError,
)
from probos.utils.step_timing import TimingLines, ms_between
```

**P2-2** (the threshold).
SEARCH:
```
ATTACHMENT_IO_THREAD_PREFIX = "probos-attachment-io"
```
REPLACE:
```
ATTACHMENT_IO_THREAD_PREFIX = "probos-attachment-io"
#: BF-930: a write or a lookup that takes at least this long (milliseconds) is reported with its steps (log-only).
SLOW_STORE_CALL_MS = 250.0
```

**P2-3** (the constructor).
SEARCH:
```
        self._lock = asyncio.Lock()
```
REPLACE:
```
        self._lock = asyncio.Lock()
        # BF-930: log-only. The call that holds ``_lock`` (each acquirer names itself) and the bounded timing lines.
        self._lock_holder = ""
        self._write_lines = TimingLines(logger)
        self._find_lines = TimingLines(logger)
```

**P2-4** (`write`: the head).
SEARCH:
```
        normalized_origin = self._normalize_origin(origin)
        async with self._lock:
            path, present = await self._run(self._locate_sync, content_hash, mime)
            need_write = not present
```
REPLACE:
```
        normalized_origin = self._normalize_origin(origin)
        # BF-930: log-only. What holds the lock as this call arrives, and where this call's own time goes.
        holder_on_arrival = self._lock_holder if self._lock.locked() else ""
        t_enter = time.perf_counter()
        async with self._lock:
            t_locked = time.perf_counter()
            self._lock_holder = f"write:{normalized_origin}"
            path, present = await self._run(self._locate_sync, content_hash, mime)
            t_located = time.perf_counter()
            need_write = not present
```

**P2-5** (`write`: the blob stamp).
SEARCH:
```
            # Index update (always: re-touches written_at on idempotent re-write).
```
REPLACE:
```
            t_blob = time.perf_counter()
            # Index update (always: re-touches written_at on idempotent re-write).
```

**P2-6** (`write`: the index stamp and the line).
SEARCH:
```
            await self._run(self._save_index_sync)
        return path
```
REPLACE:
```
            await self._run(self._save_index_sync)
            t_index = time.perf_counter()
        total_ms = ms_between(t_enter, t_index)
        if total_ms >= SLOW_STORE_CALL_MS:  # BF-930: log-only; a write that failed raised above and logs nothing
            self._write_lines.emit(
                "BF-930: attachment write slow id=%s origin=%s bytes=%d total_ms=%.0f lock_wait_ms=%.0f "
                "locate_ms=%.0f blob_ms=%.0f index_ms=%.0f behind=%s index_entries=%d",
                content_hash[:8], normalized_origin, len(blob), total_ms, ms_between(t_enter, t_locked),
                ms_between(t_locked, t_located), ms_between(t_located, t_blob), ms_between(t_blob, t_index),
                holder_on_arrival or "none", len(self._index),
            )
        return path
```

**P2-7** (`_find`).
SEARCH:
```
        matches = await self._run(
            lambda: list(self._root.glob(f"{content_hash}.*")),
        )
        return matches[0] if matches else None
```
REPLACE:
```
        t_find = time.perf_counter()
        matches = await self._run(
            lambda: list(self._root.glob(f"{content_hash}.*")),
        )
        find_ms = ms_between(t_find, time.perf_counter())
        if find_ms >= SLOW_STORE_CALL_MS:  # BF-930: log-only
            self._find_lines.emit(
                "BF-930: attachment find slow id=%s find_ms=%.0f index_entries=%d",
                content_hash[:8], find_ms, len(self._index),
            )
        return matches[0] if matches else None
```

**P2-8** (`unlink`: the holder).
SEARCH:
```
        async with self._lock:
            path = await self._find(content_hash)
            existed = False
```
REPLACE:
```
        async with self._lock:
            self._lock_holder = "unlink"  # BF-930: log-only
            path = await self._find(content_hash)
            existed = False
```

**P2-9** (`unlink_if_unchanged`: the holder).
SEARCH:
```
        async with self._lock:
            entry = self._index.get(content_hash)
            if entry is None or entry.get("origin", "chat_attachment") != origin:
```
REPLACE:
```
        async with self._lock:
            self._lock_holder = "reaper_unlink"  # BF-930: log-only
            entry = self._index.get(content_hash)
            if entry is None or entry.get("origin", "chat_attachment") != origin:
```

**P2-10** (`list_by_origin`: the holder).
SEARCH:
```
        async with self._lock:
            rows: list[tuple[str, float]] = []
```
REPLACE:
```
        async with self._lock:
            self._lock_holder = "list_by_origin"  # BF-930: log-only
            rows: list[tuple[str, float]] = []
```

**P2-11** (`total_size_bytes`: the holder).
SEARCH:
```
        async with self._lock:
            if self._index:
                total = 0
```
REPLACE:
```
        async with self._lock:
            self._lock_holder = "total_size"  # BF-930: log-only
            if self._index:
                total = 0
```

**P2-12** (`src/probos/audio/tts/resident.py`: `import time`).
SEARCH:
```
import threading
import uuid
```
REPLACE:
```
import threading
import time
import uuid
```

**P2-13** (the import of the helper).
SEARCH:
```
from probos.execution.command_env import trusted_command_env

logger = logging.getLogger(__name__)
```
REPLACE:
```
from probos.execution.command_env import trusted_command_env
from probos.utils.step_timing import TimingLines, ms_between

logger = logging.getLogger(__name__)
```

**P2-14** (the threshold).
SEARCH:
```
_STDERR_TAIL_BYTES = 500
```
REPLACE:
```
_STDERR_TAIL_BYTES = 500
#: BF-930: a Piper request that takes at least this long (milliseconds) is reported with its steps (log-only).
SLOW_SYNTHESIS_MS = 750.0
```

**P2-15** (`PiperWorker.__init__`: the two thread-side stamps).
SEARCH:
```
        self._running = False
        self._closed = False

    @property
    def alive(self) -> bool:
```
REPLACE:
```
        self._running = False
        self._closed = False
        # BF-930: log-only. When the last request's blocking call started and ended on its thread (``time.perf_counter``).
        self.thread_started = 0.0
        self.thread_ended = 0.0

    @property
    def alive(self) -> bool:
```

**P2-16** (`synthesize_blocking`: the start).
SEARCH:
```
        request ran, the request releases the worker before it returns.
        """
        with self._state:
```
REPLACE:
```
        request ran, the request releases the worker before it returns.
        """
        self.thread_started = time.perf_counter()  # BF-930: log-only
        with self._state:
```

**P2-17** (`synthesize_blocking`: the end).
SEARCH:
```
        try:
            return self._request(text, timeout)
        finally:
            with self._state:
```
REPLACE:
```
        try:
            return self._request(text, timeout)
        finally:
            self.thread_ended = time.perf_counter()  # BF-930: log-only
            with self._state:
```

**P2-18** (`VoiceSynthesisService.__init__`).
SEARCH:
```
        self._locks: dict[PiperWorkerKey, asyncio.Lock] = {}
```
REPLACE:
```
        self._locks: dict[PiperWorkerKey, asyncio.Lock] = {}
        self._timing = TimingLines(logger)  # BF-930: log-only
```

**P2-19** (`synthesize`: the stamps; the order of the awaits is unchanged).
SEARCH:
```
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
```
REPLACE:
```
            t_enter = time.perf_counter()  # BF-930: log-only stamps; the awaits below keep their order
            lock = self._locks.setdefault(key, asyncio.Lock())
            async with lock:
                t_locked = time.perf_counter()
                if self._closed:
                    return None
                worker = await self._claim(key)
                if worker is None:
                    return None
                t_claimed = time.perf_counter()
                loop = asyncio.get_running_loop()
                self._busy.add(key)
                try:
                    cold = not worker.alive
                    t_submit = time.perf_counter()
                    future = loop.run_in_executor(self.executor, worker.synthesize_blocking, text, timeout)
                    outcome = await future
                    t_resumed = time.perf_counter()
```

**P2-19b** (`synthesize`: the line, after the `finally`).
SEARCH:
```
                finally:
                    self._busy.discard(key)
                if outcome.audio is not None:
                    return outcome.audio
```
REPLACE:
```
                finally:
                    self._busy.discard(key)
                # BF-930: log-only. Where a slow request's time went (milliseconds, monotonic clock).
                total_ms = ms_between(t_enter, t_resumed)
                if total_ms >= SLOW_SYNTHESIS_MS:
                    self._timing.emit(
                        "BF-930: piper request slow chars=%d voice=%s total_ms=%.0f lock_wait_ms=%.0f claim_ms=%.0f "
                        "pool_wait_ms=%.0f work_ms=%.0f resume_lag_ms=%.0f cold=%s result=%s in_flight=%d",
                        len(text), Path(key.model).stem, total_ms, ms_between(t_enter, t_locked),
                        ms_between(t_locked, t_claimed), ms_between(t_submit, worker.thread_started),
                        ms_between(worker.thread_started, worker.thread_ended),
                        ms_between(worker.thread_ended, t_resumed), "yes" if cold else "no",
                        "ok" if outcome.audio is not None else "failed", self._in_flight,
                    )
                if outcome.audio is not None:
                    return outcome.audio
```

**P2-20** (`routers/avatars.py`: the join key on the route's existing line; fields stay in their order, one is appended).
SEARCH:
```
        "total_ms=%.0f visemes=%s audio_ms=%d",
        len(text), (synthesized - started) * 1000, (stored - synthesized) * 1000,
        (finished - stored) * 1000, (finished - started) * 1000, visemes_mode, duration_ms,
```
REPLACE:
```
        "total_ms=%.0f visemes=%s audio_ms=%d id=%s",
        len(text), (synthesized - started) * 1000, (stored - synthesized) * 1000,
        (finished - stored) * 1000, (finished - started) * 1000, visemes_mode, duration_ms,
        attachment_id[:8],
```

**N2-1** (`tests/test_bf930_voice_path_timing.py`: the marker, after P2-0 to P2-20).
SEARCH:
```
built = (
    (lambda func: func)
    if os.environ.get("BF930_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)
```
REPLACE:
```
def built(func):
    """BF-930 M2: the built cases pass; the marker no longer fails them."""
    return func
```

(Numbering note: the block `P2-19b` follows `P2-19` and the table in section 4 counts blocks P2-0 to P2-20 including it.)

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it. Replace `DATE` with M3's date. The entry is 4 lines (heading, two bullets, blank).
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-930 slice 1 (DATE), #1668 -- a slow attachment write, a slow lookup and a slow Piper request now log where their time went; the TTS route line carries the audio id.**
- **Base.** One `store_ms` and one `synth_ms` hid seven causes: the store's lock, its four threads, the index rewrite and the disk; the per-voice queue, the voice executor, Piper itself and the event loop.
- **Change (log-only).** `FilesystemAttachmentStore` writes `BF-930: attachment write slow` (lock wait, locate, blob, index, what held the lock on arrival, index entries) and `attachment find slow` at 250 ms or more; `VoiceSynthesisService` writes `BF-930: piper request slow` (lock wait, claim, pool wait, work, resume lag, cold, in flight) at 750 ms or more; at most 12 lines a minute per component, the rest counted as `suppressed=N`; the route's `BF-918: tts route` line gains a trailing `id=`. No response, order, lock, thread or timeout changes; synthetic fixtures only. Not changed: the fix, the target, the live measurement (#1668 stays open). Contract `prompts/bf-930-932-voice-and-reply-path-timing.md`, slice S1. Refs #1668.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows the BF entries (once on `f614a31d`, at line 1710; the two UI-only batches' entries are inserted before it, and each entry of this batch is inserted before it as well, so the order is the order of landing). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-930 slice 1 -- Slow store and synthesis calls log where their time went, log-only and bounded (DATE, #1668)

- *Scope.* `probos/utils/step_timing.py` (new), `attachments/filesystem_store.py`, `audio/tts/resident.py`, `routers/avatars.py` (one trailing field), one test file. Contract `prompts/bf-930-932-voice-and-reply-path-timing.md`.
- *G1 (shape).* A marker line per component, only for calls that took at least 250 ms (store) or 750 ms (synthesis), at INFO, at most 12 a minute per component with the rest counted; the route's existing line gains one join key. Rejected: extending the route line with every sub-step (it needs return values or a context variable through the storage seam); a summary per request (the same plumbing).
- *G2 (safety).* No await, thread, lock or task added; a failure while writing a line is swallowed at DEBUG (a measurement must not fail a reply); the lock holder is a string each acquirer sets. No config key (module constants, as BF-918 M4 chose).
- *G3 (public text).* Synthetic fixtures only; no live figure in any test, comment, tracker line or commit message; the acceptance's live numbers are posted on the issue, not in the repository.
- *Residual.* L1 to L8 of the contract (S1). *Reversal.* Revert the BF-930 slice 1 commits (after reverting slice 2, which imports the helper).

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.2 Slice S2 (BF-932: the Captain-DM reply path)

#### S2 M1

**N1-1.** New file `tests/test_bf932_reply_path_timing.py` (11 cases; section 6 names them). The route harness is copied from `tests/test_ad730_agent_chat_vision.py:35-125` (`_CREW_PATCH`, `_make_runtime`, `_req`); the agent harness is the construction `tests/test_cognitive_agent.py` uses before its `handle_intent` calls (`:227`, `:244`). **The Architect could not run either harness**; the first assertion of every route case is `runtime.intent_bus.send.assert_awaited_once()`, so the oracle sees at once whether the route reaches the send.

```python
"""BF-932 (#1670): timing lines of the Captain-DM reply path (the route, the agent's turn, the concurrency queue).

Synthetic fixtures only: stubs that sleep 30 ms, ``test-id`` and ``test-agent``. ``built`` cases fail on the base at their
own assert; ``BF932_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.llm_client import MockLLMClient
from probos.config import CognitiveConfig
from probos.routers import agents as agents_router
from probos.routers.agents import agent_chat
from probos.security.pii_redaction import PIIRedactor
from probos.types import IntentDescriptor

built = (
    (lambda func: func)
    if os.environ.get("BF932_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)

_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)
_ROUTE = "BF-932: dm route"
_TURN = "BF-932: dm turn"


def _lines(caplog, marker: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if marker in r.getMessage()]


def _field(line: str, name: str) -> str:
    found = re.search(rf"\b{name}=(\S+)", line)
    assert found, f"{name} missing from {line!r}"
    return found.group(1)


def _one(lines: list[str]) -> str:
    assert len(lines) == 1, f"expected exactly one line, found {len(lines)}"
    return lines[0]


class _DmAgent(CognitiveAgent):
    """A minimal crew agent that accepts a direct message: the construction ``tests/test_cognitive_agent.py`` uses."""

    agent_type = "test_dm"
    _handled_intents = {"direct_message"}
    instructions = "You are a test agent. Respond concisely."
    intent_descriptors = [
        IntentDescriptor(name="direct_message", params={"text": "input"}, description="Direct message", tier="domain")
    ]


@pytest.fixture
def make_agent():
    return lambda: _DmAgent(llm_client=MockLLMClient())


def _req(message: str = "hello"):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = []
    r.thread_id = None
    r.system_trigger = False
    return r


class _Consumer:
    """The vision consumer's seam: records its calls and the order, sleeps 30 ms, may raise (no MagicMock at this boundary)."""

    def __init__(self, order: list[str], fail: bool = False) -> None:
        self.order, self.fail, self.timeouts = order, fail, []

    async def force_describe_current_frame(self, session_id=None, *, timeout_s: float = 4.0):
        self.order.append("consumer")
        self.timeouts.append(timeout_s)
        await asyncio.sleep(0.03)
        if self.fail:
            raise RuntimeError("hook failed")
        return "scene"


def _runtime(order: list[str], *, perception: bool = True, fail: bool = False, forward=None):
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "test-id"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent
    runtime.callsign_registry.get_callsign.return_value = "Lynx"
    result = MagicMock()
    result.result = "Acknowledged."
    result.error = None

    async def _send(intent, raise_on_denial=False):
        order.append("send")
        await asyncio.sleep(0.03)
        if forward is not None:
            await forward(intent)
        return result

    runtime.intent_bus.send = AsyncMock(side_effect=_send)
    runtime.recreation_service = None
    runtime.ward_room = None
    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(enabled=False),
        cognitive=CognitiveConfig(),
        perception=SimpleNamespace(enabled=perception, dm_force_describe_enabled=True),
        dm_targeted_lookup=SimpleNamespace(enabled=False),
    )
    runtime.llm_client = MagicMock()
    runtime.episodic_memory = None
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    runtime.dm_sanity_gate = DmSanityGate()
    runtime.vision_consumer = _Consumer(order, fail=fail)
    return runtime


async def _dm(runtime):
    with _CREW_PATCH:
        return await agent_chat("test-id", _req(), runtime)


@built
@pytest.mark.asyncio
async def test_r1_a_captain_dm_writes_one_route_line_with_each_step_and_the_intent_id(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    order: list[str] = []
    runtime = _runtime(order)
    await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    line = _one(_lines(caplog, _ROUTE))
    sent = runtime.intent_bus.send.call_args.args[0]
    assert _field(line, "intent") == sent.id[:8] and _field(line, "agent") == "test-id"
    assert _field(line, "hook") == "ran" and _field(line, "sent") == "yes"
    assert float(_field(line, "hook_ms")) >= 25 and float(_field(line, "send_ms")) >= 25
    assert float(_field(line, "total_ms")) >= 50
    for name in ("thread_ms", "prep_ms", "dispatch_ms"):
        float(_field(line, name))


@built
@pytest.mark.asyncio
async def test_r2_a_dm_with_perception_off_says_the_hook_was_skipped(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    order: list[str] = []
    runtime = _runtime(order, perception=False)
    await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    line = _one(_lines(caplog, _ROUTE))
    assert _field(line, "hook") == "skipped" and _field(line, "hook_ms") == "0" and order == ["send"]


@built
@pytest.mark.asyncio
async def test_r3_a_hook_that_raises_is_still_timed_and_the_reply_still_goes_out(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    order: list[str] = []
    runtime = _runtime(order, fail=True)
    answer = await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    line = _one(_lines(caplog, _ROUTE))
    assert _field(line, "hook") == "ran" and answer["response"] == "Acknowledged."


@pytest.mark.asyncio
async def test_r4_the_routes_order_cap_and_reply_are_unchanged() -> None:
    order: list[str] = []
    runtime = _runtime(order)
    answer = await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    assert order == ["consumer", "send"] and runtime.vision_consumer.timeouts == [4.0]
    assert runtime.intent_bus.send.call_args.kwargs == {"raise_on_denial": True}
    assert answer["response"] == "Acknowledged."


@built
@pytest.mark.asyncio
async def test_r5_the_route_line_survives_the_log_redactor(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    await _dm(_runtime([]))
    line = _one(_lines(caplog, _ROUTE))
    assert PIIRedactor.redact_all(line) == line


@pytest.mark.asyncio
async def test_r6_a_failing_logger_changes_nothing(monkeypatch) -> None:
    real = agents_router.logger

    class _Logger:
        """The route's logger, except that its INFO call raises for a BF-932 line only."""

        def __getattr__(self, name):
            return getattr(real, name)

        def info(self, msg, *args, **kwargs):
            if str(msg).startswith("BF-932:"):
                raise RuntimeError("handler failed")
            return real.info(msg, *args, **kwargs)

    monkeypatch.setattr(agents_router, "logger", _Logger())
    answer = await _dm(_runtime([]))
    assert answer["response"] == "Acknowledged."


@built
@pytest.mark.asyncio
async def test_c1_a_promoted_intent_reports_how_long_it_waited(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.concurrency_manager")
    manager = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=2)
    held = await manager.acquire("proactive_think", 2)
    waiter = asyncio.create_task(manager.acquire("direct_message", 8))
    await asyncio.sleep(0.08)
    await manager.release(held)
    await asyncio.wait_for(waiter, 5)
    [line] = _lines(caplog, "AD-672: Promoted queued intent")
    assert line.startswith("AD-672: Promoted queued intent 'direct_message' for agent test-agent at priority=8")
    assert float(_field(line, "waited_ms")) >= 60  # the queue stamps with time.monotonic (15.6 ms ticks on Windows)


@pytest.mark.asyncio
async def test_c2_an_intent_that_gets_a_slot_at_once_logs_no_promotion_line(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.concurrency_manager")
    manager = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=2)
    thread_id = await manager.acquire("direct_message", 8)
    await manager.release(thread_id)
    assert not _lines(caplog, "Promoted queued intent")


def _slow(delay: float, result=None):
    async def stub(*_a, **_k):
        await asyncio.sleep(delay)
        return result
    return stub


async def _turn(agent, monkeypatch, *, sender: str, caplog):
    from probos.types import IntentMessage
    caplog.set_level(logging.INFO, logger="probos.cognitive.cognitive_agent")
    monkeypatch.setattr(agent, "perceive", _slow(0.03, {"intent": "direct_message", "params": {}}))
    monkeypatch.setattr(agent, "_recall_relevant_memories", _slow(0.03, {"intent": "direct_message", "params": {}}))

    async def stop(*_a, **_k):
        raise RuntimeError("end of the measured window")

    monkeypatch.setattr(agent, "decide", stop)
    intent = IntentMessage(intent="direct_message", params={"text": "hi", "from": sender}, target_agent_id=agent.id)
    with pytest.raises(RuntimeError, match="end of the measured window"):
        await agent.handle_intent(intent)
    return intent


@built
@pytest.mark.asyncio
async def test_a1_an_hxi_dm_turn_logs_its_perceive_and_recall_times_with_the_intent_id(make_agent, monkeypatch, caplog) -> None:
    intent = await _turn(make_agent(), monkeypatch, sender="hxi_profile", caplog=caplog)
    line = _one(_lines(caplog, _TURN))
    assert _field(line, "intent") == intent.id[:8]
    assert float(_field(line, "perceive_ms")) >= 25 and float(_field(line, "recall_ms")) >= 25


@pytest.mark.asyncio
async def test_a2_a_dm_from_another_sender_logs_no_turn_line(make_agent, monkeypatch, caplog) -> None:
    await _turn(make_agent(), monkeypatch, sender="crew_member", caplog=caplog)
    assert not _lines(caplog, _TURN)


@built
@pytest.mark.asyncio
async def test_r1b_one_captain_dm_is_joinable_from_the_route_line_to_the_turn_line(make_agent, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    agent = make_agent()
    monkeypatch.setattr(agent, "perceive", _slow(0.0, {"intent": "direct_message", "params": {}}))
    monkeypatch.setattr(agent, "_recall_relevant_memories", _slow(0.0, {"intent": "direct_message", "params": {}}))
    monkeypatch.setattr(agent, "decide", _slow(0.0, {"action": "none"}))

    async def forward(intent):
        try:
            await agent.handle_intent(intent)
        except Exception:
            pass  # the turn's later stages are not under test; the line precedes them

    await _dm(_runtime([], forward=forward))
    route = _one(_lines(caplog, _ROUTE))
    turn = _one(_lines(caplog, _TURN))
    assert _field(route, "intent") == _field(turn, "intent")
```

(R6 is a control that holds on the base vacuously, because the base writes no BF-932 line, and is the isolation proof at M2: the helper swallows the raising `logger.info`, so the route's un-wrapped call to `emit_line` cannot fail the reply. The helper's own isolation is S1 H5. `make_agent` is defined in the file (amendment A1): `_DmAgent` is a minimal `CognitiveAgent` that handles a direct message, built with `MockLLMClient` as `tests/test_cognitive_agent.py` builds its agents; the agent cases reach `_run_cognitive_lifecycle` with no stop service and pass `target_agent_id=agent.id`. The count is measured: G1 gives `4 passed, 7 xfailed (11)`.)

#### S2 M2

**P2-1** (`routers/agents.py`: the import and the logger).
SEARCH:
```
logger = logging.getLogger(__name__)
```
REPLACE:
```
from probos.utils.step_timing import emit_line, ms_between

logger = logging.getLogger(__name__)
```

**P2-2** (`_agent_chat_impl`: the stamps).
SEARCH:
```
    """The agent-chat handler proper. See `agent_chat` for why it is split."""
    agent = runtime.registry.get(agent_id)
```
REPLACE:
```
    """The agent-chat handler proper. See `agent_chat` for why it is split."""
    # BF-932: log-only stamps of the Captain-DM timeline (``time.perf_counter``); one line is written after the send.
    _t_entry = time.perf_counter()
    _t_thread = _t_vision = _t_hook0 = _t_hook1 = _t_entry
    _hook = "skipped"
    agent = runtime.registry.get(agent_id)
```

**P2-3** (the end of the thread-store work).
SEARCH:
```
    # AD-743: Captain interruption cancels any pending pacing follow-up so the
```
REPLACE:
```
    _t_thread = time.perf_counter()  # BF-932: log-only; the thread-store calls above run synchronously on the event loop

    # AD-743: Captain interruption cancels any pending pacing follow-up so the
```

**P2-4** (the start of the vision block).
SEARCH:
```
    # AD-733a (Wave 171): prepend the agent's current visual context.
```
REPLACE:
```
    _t_vision = time.perf_counter()  # BF-932: log-only

    # AD-733a (Wave 171): prepend the agent's current visual context.
```

**P2-5** (the hook).
SEARCH:
```
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
```
REPLACE:
```
                _hook = "ran"  # BF-932: log-only
                _t_hook0 = time.perf_counter()
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
                _t_hook1 = time.perf_counter()
```

**P2-6** (the send and the one line).
SEARCH:
```
    result = None if _held_notice else await runtime.intent_bus.send(
        intent, raise_on_denial=True,
    )
```
REPLACE:
```
    _t_send0 = time.perf_counter()  # BF-932: log-only
    result = None if _held_notice else await runtime.intent_bus.send(
        intent, raise_on_denial=True,
    )
    _t_send1 = time.perf_counter()
    # BF-932: one line per Captain DM: where its time went before the agent's turn and during it (milliseconds, monotonic
    # clock). ``intent`` is the id the agent's own ``BF-932: dm turn`` line carries.
    emit_line(
        logger,
        "BF-932: dm route intent=%s agent=%s thread_ms=%.0f prep_ms=%.0f hook=%s hook_ms=%.0f dispatch_ms=%.0f "
        "send_ms=%.0f total_ms=%.0f sent=%s",
        intent.id[:8], agent_id[:12], ms_between(_t_entry, _t_thread), ms_between(_t_thread, _t_vision), _hook,
        ms_between(_t_hook0, _t_hook1), ms_between(_t_vision, _t_send0) - ms_between(_t_hook0, _t_hook1),
        ms_between(_t_send0, _t_send1), ms_between(_t_entry, _t_send1), "no" if _held_notice else "yes",
    )
```

**P2-7** (`src/probos/cognitive/cognitive_agent.py`: the turn's start).
SEARCH:
```
        observation = await self.perceive(intent)
        if recreation_turn is not None:
            observation["_recreation_turn"] = recreation_turn

        # AD-430c (Pillar 4): Enrich observation with relevant episodic memories
        observation = await self._recall_relevant_memories(intent, observation)
```
REPLACE:
```
        _t_perceive = time.perf_counter()  # BF-932: log-only stamps of the turn's start
        observation = await self.perceive(intent)
        _t_recall = time.perf_counter()
        if recreation_turn is not None:
            observation["_recreation_turn"] = recreation_turn

        # AD-430c (Pillar 4): Enrich observation with relevant episodic memories
        observation = await self._recall_relevant_memories(intent, observation)
        if intent.intent == "direct_message" and intent.params.get("from") == "hxi_profile":
            # BF-932: one line per Captain DM (the HXI route's own marker), keyed by the id the route's line carries.
            from probos.utils.step_timing import emit_line, ms_between

            emit_line(
                logger,
                "BF-932: dm turn intent=%s agent=%s perceive_ms=%.0f recall_ms=%.0f",
                intent.id[:8], self.id[:12], ms_between(_t_perceive, _t_recall),
                ms_between(_t_recall, time.perf_counter()),
            )
```

**P2-8** (`src/probos/cognitive/concurrency_manager.py`: the import).
SEARCH:
```
from probos.events import EventType
```
REPLACE:
```
from probos.events import EventType
from probos.utils.step_timing import ms_between
```

**P2-9** (the promotion line: one trailing field).
SEARCH:
```
                logger.info(
                    "AD-672: Promoted queued intent '%s' for agent %s at priority=%d",
                    next_intent.intent_type,
                    self._agent_id,
                    next_intent.priority,
                )
```
REPLACE:
```
                logger.info(
                    "AD-672: Promoted queued intent '%s' for agent %s at priority=%d waited_ms=%.0f",
                    next_intent.intent_type,
                    self._agent_id,
                    next_intent.priority,
                    ms_between(next_intent.queued_at, time.monotonic()),  # BF-932: log-only
                )
```

**N2-1** (`tests/test_bf932_reply_path_timing.py`: the marker, after P2-1 to P2-9).
SEARCH:
```
built = (
    (lambda func: func)
    if os.environ.get("BF932_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)
```
REPLACE:
```
def built(func):
    """BF-932 M2: the built cases pass; the marker no longer fails them."""
    return func
```

(The S2 table in section 4 names P2-1 to P2-11 for the three files; the blocks are P2-1 to P2-9 plus N2-1: **nine source blocks, not eleven**; the table's "P2-11" is an expected-count slip the orchestrator corrects: the blocks of this section are the whole of S2 M2.)

#### S2 M3: tracking

**P3-1.** `PROGRESS.md`. Anchor and rules as S1 M3's P3-1 (the entry lands above S1's: the SEARCH is the same title line and blank line). Replace `DATE`.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-932 slice 2 (DATE), #1670 -- one line per Captain DM says where its time went before the agent's turn; one line per HXI DM says how long the turn's perceive and recall took; the agent queue's promotion says how long the intent waited.**
- **Base.** The hook's capped describe was the only timed step; the route's synchronous thread-store work, the lookups outside the cap, the agent's queue wait, perceive and the per-message recall were invisible, and the issue's end markers were not general.
- **Change (log-only).** The DM route writes `BF-932: dm route intent=<id8> ...` (thread, prep, hook, dispatch, send, total) once per Captain DM; the agent writes `BF-932: dm turn intent=<id8> ...` (perceive, recall) once per HXI DM; the existing queue promotion line gains a trailing `waited_ms=`. The same intent id joins the first two; no response, order, lock, thread or timeout changes; synthetic fixtures only. Not changed: the fix, the target, the model-call lane (it comes after the window the issue measured), the live measurement (#1670 stays open). Contract `prompts/bf-930-932-voice-and-reply-path-timing.md`, slice S2. Refs #1670.

```

**P3-2.** `DECISIONS.md`. Anchor and rules as S1 M3's P3-2 (this entry lands after S1's, in slice order, because S1's entry is already above the heading when S2 M3 applies). Replace `DATE`.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-932 slice 2 -- The Captain-DM reply path logs its own timeline, log-only (DATE, #1670)

- *Scope.* `routers/agents.py` (stamps and one line, after the send), `cognitive/cognitive_agent.py` (stamps and one line, before the model call), `cognitive/concurrency_manager.py` (one trailing field), one test file. Contract `prompts/bf-930-932-voice-and-reply-path-timing.md`.
- *G1 (shape).* One line per Captain DM at the route and one per HXI DM at the agent, joined by the intent id (an id the message already carries and that crosses the wire); the queue's own line gains the wait. Rejected: stamping the route's time into the intent's parameters (it changes what the agent reads); an always-on loop-lag task (a new component; the named next step if the sum of the lines does not close).
- *G2 (scope).* The model-call lane and the turn's own calls are out: the issue's window ends at the recall line, before the first model call (enumerated). Per-step lines inside the describe are out: its two unbounded steps are the store lookups S1 already reports.
- *G3 (public text).* Synthetic fixtures only; no live figure anywhere in the repository.
- *Residual.* L1 to L8 of the contract (S2). *Reversal.* Revert the BF-932 slice 2 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

**S1.** The attachment store's behaviour: `write`'s order of hops, its idempotence, its origin upgrade rule, the ENOSPC translation, `_run` and its cancellation handling, `_save_index_sync`, `_locate_sync`, the index file, the reaper, `ATTACHMENT_IO_WORKERS`, the `AttachmentStore` Protocol (`store.py`) and every other implementation behind it. The resident synthesizer's behaviour: the per-key lock, `_claim`, the admission bound, the executor and its size, the Piper lifecycle (`_spawn`, `close`, `_release`), the timeout, the degrade paths and their warnings. The TTS route's response body, status codes, validation, the BF-918 deferral of visemes and the `degraded` line (`avatars.py:278`); the lipsync route and its line (`:74`). No change to the browser (`ui/`), to `routers/chat.py` or to the attachment reaper.

**S2.** The DM route's logic: the thread resolution, the slash commands, the 4.0 s cap, the order of the hook and the send, the reply pipeline, the stop and admission checks; the intent's parameters (nothing is added to `_params`); the agent's lifecycle (perceive, recall, decide, act), its recall query and its prompt; the concurrency manager's queue, priorities, capacity warning and its `queued` line; the LLM client, its lane, rate limit and endpoint cap; `consumer.py` (`force_describe_current_frame` is read, not edited); the intent bus.

**All.** `config/system.yaml`, every Pydantic config model and every generated reference (D5); `ui/`; the commercial overlay (OSS only; no dependency; no schema change); every tracker but `PROGRESS.md`, `DECISIONS.md` and the AD ledger pair; the roadmap Bug Tracker table.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

**Not run by the Architect** (a read-only consult cannot run pytest); every Line below was chosen from the REPLACE text of section 7 and **its single occurrence in the patched file is checked by the oracle after applying the blocks** (a gap of this consult: the SEARCHes were verified on the base blobs, not the Lines on the patched ones). The oracle's campaign: each row's line replaced whole in the built file, the slice's new test file run, the file restored and its blob checked. **This table is the campaign of record only for a tree whose files equal the blobs the blocks give on `f614a31d`** (sha256 to be recorded by the oracle); a Builder whose files match does not repeat it; if a file differs, the rows naming it are rerun. The Killed-by cells are the cases I expect to fail; the oracle reports supersets and corrects them. Case labels are section 6's.

**S1.**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `utils/step_timing.py` | `return max(0.0, (end - start) * 1000.0)` | `return (end - start) * 1000.0` | H1 |
| 2 | same | `if len(self._written) >= self._max_lines:` | `if len(self._written) > self._max_lines:` | H3, T5 |
| 3 | same | `self._suppressed += 1` | the line deleted | H3 |
| 4 | same | `self._suppressed = 0` (second occurrence, in `emit`; the first is in `__init__`) | the line deleted | H3 |
| 5 | same | `if self._max_lines > 0:` | `if True:` | H4 |
| 6 | same | `while self._written and now - self._written[0] >= self._window_s:` | `while False:` | H3 |
| 7 | same | `logger.debug("BF-930: a timing line failed and was dropped: %s", message, exc_info=True)` | `raise` | H5 |
| 8 | `attachments/filesystem_store.py` | `holder_on_arrival = self._lock_holder if self._lock.locked() else ""` | `holder_on_arrival = ""` | T2 (both) |
| 9 | same | `self._lock_holder = f"write:{normalized_origin}"` | the line deleted | T2 (write) |
| 10 | same | `self._lock_holder = "unlink"  # BF-930: log-only` | the line deleted | T2 (unlink) |
| 11 | same | `t_locked = time.perf_counter()` | `t_locked = t_enter` | T2 |
| 12 | same | `t_index = time.perf_counter()` | `t_index = t_blob` | T1, T12 |
| 13 | same | `if total_ms >= SLOW_STORE_CALL_MS:  # BF-930: log-only; a write that failed raised above and logs nothing` | `if True:` | T3 |
| 14 | same | `holder_on_arrival or "none", len(self._index),` | `holder_on_arrival or "none", 0,` | T1 |
| 15 | same | `if find_ms >= SLOW_STORE_CALL_MS:  # BF-930: log-only` | `if False:` | T4 |
| 16 | `audio/tts/resident.py` | `self.thread_started = time.perf_counter()  # BF-930: log-only` | `self.thread_started = 0.0` | T8, T13 |
| 17 | same | `self.thread_ended = time.perf_counter()  # BF-930: log-only` | the line deleted | T7, T13 |
| 18 | same | `t_locked = time.perf_counter()` | `t_locked = t_enter` | T9 |
| 19 | `routers/avatars.py` | `attachment_id[:8],` | `"",` | T11, T12 |

**S2.**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `routers/agents.py` | `_hook = "ran"  # BF-932: log-only` | the line deleted | R1, R3 |
| 2 | same | `_t_hook1 = time.perf_counter()` | the line deleted | R1 |
| 3 | same | `_t_send1 = time.perf_counter()` | `_t_send1 = _t_send0` | R1 |
| 4 | same | `intent.id[:8], agent_id[:12], ms_between(_t_entry, _t_thread), ms_between(_t_thread, _t_vision), _hook,` | the same with `intent.id[8:16]` | R1, R1b |
| 5 | `cognitive/cognitive_agent.py` | `if intent.intent == "direct_message" and intent.params.get("from") == "hxi_profile":` | `if intent.intent == "direct_message":` | A2 |
| 6 | same | `_t_recall = time.perf_counter()` | `_t_recall = _t_perceive` | A1 |
| 7 | same | `intent.id[:8], self.id[:12], ms_between(_t_perceive, _t_recall),` | the same with `intent.id[8:16]` | A1, R1b |
| 8 | `cognitive/concurrency_manager.py` | `ms_between(next_intent.queued_at, time.monotonic()),  # BF-932: log-only` | `0.0,  # BF-932: log-only` | C1 |

## 10. Recorded limits

**S1.**
- **L1.** The thresholds (250 ms for the store, 750 ms for synthesis) are chosen above the sub-second figures the BF-918 acceptance reports as normal; a stall below them appears in the route line's `store_ms` and `synth_ms` but not in a breakdown line.
- **L2.** The queue-versus-disk split inside one store hop is not measured (`_run` is untouched, D1(c)); the `locate_ms` hop, which does almost no work, is the canary for queueing.
- **L3.** `behind=` names the last acquirer of the store's lock when the lock is held on arrival (all five acquirers set it, P2-4 and P2-8 to P2-11); a lock free on arrival reads `none`. A waiter behind several holders is named for the one holding when it arrived.
- **L4.** `resume_lag_ms` and `pool_wait_ms` come from the worker's two thread stamps; a request that was refused, cancelled or closed before its thread ran writes no line, and a stamp of 0 reads as 0 ms (`ms_between` clamps).
- **L5.** The line budget is per component instance (store writes, store finds, one synthesis service): a process with two stores writes up to 12 lines a minute from each.
- **L6.** A write that raised (ENOSPC, an I/O error) logs no timing line: a stalled write that then failed is not shown.
- **L7.** Lines carry durations only, never an absolute reading, so lines from two processes cannot be joined by time.
- **L8.** The route's line gains a trailing `id=`; a consumer that parsed the line positionally after `audio_ms=` would see a new last token (section 11: none exists).

**S2.**
- **L1.** The turn line is written only for HXI DMs (`params["from"] == "hxi_profile"`, the `_params` dict at `routers/agents.py:3575-3586`); a DM from another route writes none.
- **L2.** The turn line is written after the recall, so a turn refused or failing before it writes none; the route line is written only when `send` returns (an authorization denial raises first).
- **L3.** `waited_ms` exists only on the promotion line: an intent that gets a slot at once has no wait to report; an intent shed with the queue full logs the existing warning only. It is stamped with that module's own `time.monotonic`, whose tick on Windows can be 15.6 ms: an error of at most one tick on a wait of seconds.
- **L4.** The LLM lane, the turn's own model calls and the end of the turn are not measured (D1).
- **L5.** The hop from `send` to the agent's first statement (the bus, the stop check) is not a field; it is what the route's `send_ms` leaves after the agent's own lines, visible through the sum check.
- **L6.** `thread_ms` bundles the route's four synchronous thread-store calls; if it dominates, the next slice splits it.
- **L7.** The route and agent harnesses were not run by the Architect; the oracle ran them (amendment A1: the agent construction `make_agent` is defined in the file), and R1's and R2's first assertion, the send, stays the premise a harness change would break.
- **L8.** The log's whole-second timestamps remain: the pre-turn wait is the sum of the fields, not a difference of two timestamps.

## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\next-read` at `f614a31d`)

**Run by the Architect, read-only (ripgrep, git, `gh`, CPython scripts piped on stdin; nothing written but these answer files; no pytest, no build):**

```
git -C D:\ProbOS-worktrees\next-read log -1 --format='%H %s' -> f614a31d855e217eec6c826deaffad7572d1f43f "Merge pull request #1787 ... bf937-legacy-self-modification-leftovers"; git status --short | Measure-Object -> Count 0; git rev-parse origin/main -> f614a31d...
every SEARCH of section 7 (30, python on `git show HEAD:<path>`): attachments/filesystem_store.py 11 SEARCHes, audio/tts/resident.py 9, routers/avatars.py 1, routers/agents.py 6, cognitive/cognitive_agent.py 1, cognitive/concurrency_manager.py 2 -> each occurrences=1, line-start=True, ascii=True; "PROBLEMS: 0". CR count 0 in every blob. Non-ASCII lines of the edited files: filesystem_store 5, resident 0, avatars 10, agents 90, cognitive_agent 403, concurrency_manager 1: none inside a SEARCH
blobs (git rev-parse HEAD:<path>): filesystem_store.py c29e56fe..., resident.py 4abf3f12..., avatars.py d34ece50..., agents.py 04f7fefa..., cognitive_agent.py 62c0f816..., concurrency_manager.py 3b0a9f99..., test_bf918_tts_latency.py 387b1a2e..., test_ad672_concurrency_manager.py 57eed6cc..., test_ad730_agent_chat_vision.py 349ea3e5..., test_cognitive_agent.py 76c21809...; PROGRESS.md 70cd1044..., DECISIONS.md 90adc283..., open-ads-report.md 04562090..., ad-ledger-snapshot.json 35de6500...
tracker anchors: git show HEAD:PROGRESS.md starts "# ProbOS Progress", an empty line, then BF-937's slice 2 entry; the DECISIONS heading "### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)": rg -n -F -> 1710 once; rg -c -F -> 1; ASCII; no CR line in the blob
```

**Facts read (path:line on `f614a31d`):** `routers/avatars.py:272-275` (`started`, `select_backend`, `synthesize`, `synthesized`), `:278` (the degraded line), `:299-302` (hash, accessor, `store.write(... origin="tts_audio")`, `stored`), `:327-331` (the route line), `:71-77` (the lipsync line); `attachments/filesystem_store.py:47` (`ATTACHMENT_IO_WORKERS = 4`), `:118` (class), `:158-195` (`_run`), `:236-250` (`_save_index_sync`: `json.dump(self._index, fh)` then `os.replace`), `:301-309` (`_locate_sync`), `:311-366` (`write`, the lock at `:328`), `:368-377` (`_find`: `self._root.glob`), `:406`, `:449`, `:484`, `:499` (the other four lock holders); `audio/tts/resident.py:46-48` (workers 4, in-flight bound 16), `:154` (`synthesize_blocking`), `:250` (`_spawn`), `:390-420` (`synthesize`: the per-key lock `:401`, `run_in_executor` `:411`); `routers/agents.py:2945` (`_agent_chat_impl`), `:3008` (`get_or_create_default_for_agent`), `:3110` (`maybe_auto_name`), `:3127` (the Captain's `append_message`), `:3479` (the hook), `:3575-3586` (`_params`, `"from": "hxi_profile"`), `:3605` (`_capture_owned_steps_turn`), `:3622` (`IntentMessage(intent="direct_message", ...)`), `:3646` (`observe_self_avatar`); `threads/__init__.py:36`, `:261-262` (`sqlite3.connect(str(self._db_path), isolation_level=None)`, a plain synchronous connection); `perception/consumer.py:448-463` (`_force_describe_permit`: a 1 ms try-lock, no queue), `:787` and `:843` (`store.exists`), `:823-826` (`asyncio.wait_for(self._process(...), timeout=timeout_s)`); `cognitive/cognitive_agent.py:7584-7613` (`_run_cognitive_lifecycle`: `perceive`, then the recall), `:8257` (`concurrency_manager.slot`), `:11562` (`_recall_relevant_memories`), `:12129` (the `BF-631 DM-recall` line); `cognitive/concurrency_manager.py:42` (`queued_at`), `:55-56` (4 and 10), `:142-143` and `:234` (the two INFO lines); `cognitive/turn_cost.py:253-256`; `cognitive/llm_client.py:1462-1490` (`complete`; the lane wait `:1480`); `mesh/intent.py:2067` (`"id": intent.id`), `:1133-1196` (`send`); `types.py:58-74` (`IntentMessage.id`, `created_at`); `__main__.py:132-203` (`_setup_logging`: INFO file handler, `datefmt` at `:151`, redaction at `:203`); `security/pii_redaction.py:13-25` (patterns); `utils/` (`frontmatter.py`, `html_text.py`, `json_extract.py`, `response_formatter.py`, `text_sanitize.py`; `tests/test_layer_boundaries.py:40-55`: `utils` is universally importable and imports nothing); `tests/fixtures/ad1346_file_write_census.py:204,206` (file rows, no count), `tests/fixtures/ad1346_effect_census.py:132` (`("src/probos/audio/tts/resident.py", "PiperWorker._spawn"): (1, ...)`), `tests/fixtures/ad1343_seam_registry.py:22-52` (scope names such as `_agent_chat_impl`, `CognitiveAgent.handle_intent`); the harnesses `tests/test_bf918_tts_latency.py:74-90, 538-569`, `tests/test_ad730_agent_chat_vision.py:25-125`, `tests/test_ad672_concurrency_manager.py:88-107`.

**Absence Verified (2026-11-13)**

```
CLAIM: BF-930 and BF-932 are held only by #1668 and #1670; nothing else claims them
RUN:   git log --all --format='%h %s' -i --grep='BF-930'; the same for 'BF-932'; Get-ChildItem prompts -Filter '*930*', '*932*'; rg -n "BF-930|BF-932" PROGRESS.md DECISIONS.md docs/development/roadmap.md; gh issue list --repo seangalliher/ProbOS --state all --search "BF-930 in:title" --json number,title,state (and BF-932)
FOUND: no commit subject; no prompt file; no tracker hit; #1668 (OPEN, "BF-930: a spoken reply pauses mid-way ...") and #1670 (OPEN, "BF-932: in a live call each Captain message waits 19-41 s ...") only
HOLDS: yes (nothing new is allocated; the contract commit's subject will be the first to name them)

CLAIM: the only reader of the `BF-918: tts route` line in tests, scripts and docs is test_bf918_tts_latency.py, by substring; the only other readers are recipes in the BF-918 prompt
RUN:   rg -n "tts route|BF-918: lipsync route|synth_ms|store_ms" tests scripts docs (and over the repository, excluding node_modules and site)
FOUND: tests/test_bf918_tts_latency.py:609 and :610 (substrings synth_ms=, store_ms=, visemes_ms=, total_ms=, visemes=deferred); prompts/bf-918-tts-first-audio-latency.md:2772, 2823, 2892, 3818-3819, 6864-6866 (the closing recipe: `(\w+_ms)=(\d+)` over lines containing "BF-918: tts route"), 6921; prompts/bf-918-m4-m5-store-io-and-pipelined-arbiter.md:36, 1840, 2090, 2095 (prose); no hit in scripts or docs
HOLDS: yes. The appended `id=` field matches neither the substrings nor the recipe's regex

CLAIM: nothing parses probos.log except the Captain's recipes: no test, script or source reads it
RUN:   rg -n "probos\.log" tests scripts src --glob '*.py'
FOUND: src/probos/__main__.py:172 (the handler's path), :676 (a boot-log path), src/probos/routers/avatars.py:325 (a comment); no test, no script
HOLDS: yes

CLAIM: nothing reads the `AD-672: Promoted queued intent` line
RUN:   rg -n "Promoted queued intent|queued for agent|waiting for release" tests src --glob '*.py'
FOUND: src/probos/cognitive/concurrency_manager.py:142-143, :234; src/probos/cognitive/turn_promotion.py:2149 (a different message: "its reporter was still queued for agent=%s capacity"); no test
HOLDS: yes

CLAIM: no test patches `_run`, `_locate_sync` or the store's executor, and every patch of `_save_index_sync` is class-level behind a gate or a direct call, which this batch does not touch
RUN:   rg -n "_locate_sync|_save_index_sync|\._run\b|ATTACHMENT_IO_THREAD_PREFIX|_io_executor" tests --glob '*.py'
FOUND: tests/test_ad720_attachment_store.py:102, :117 (thread-name prefix); tests/test_attachment_reaper.py:55 and tests/test_bf918_tts_retention.py:72 (a direct `store._save_index_sync()` call); tests/test_bf918_attachment_io.py:27, :157-191, :251, :333-334, :402-403 (a `_Gate` around `_save_index_sync` at class level); unrelated `_run` names in tests/fixtures/federation_cluster.py:285 and tests/test_issue1452_stop_leftovers.py:59, :282
HOLDS: yes (the batch changes none of them; its stamps run after each hop returns)

CLAIM: the turn's first model call is after the `BF-631 DM-recall` line, and `perceive` and `_recall_relevant_memories` call the model directly nowhere
RUN:   an AST scan of `git show HEAD:src/probos/cognitive/cognitive_agent.py` for calls to an attribute named `complete`, printing the enclosing function
FOUND: 4667 _decide_via_llm; 7306 propose_appearance; 7533 propose_voice_profile; 8951 _answer_consultation; 12950 _run_interpretation
HOLDS: yes for a direct call (an indirect call from `perceive` into another module was not traced)

CLAIM: no loop-lag monitor, no elapsed-milliseconds helper and no timing module exist
RUN:   rg -n "slow_callback_duration|set_debug\(|loop_lag|event.loop.lag|loop lag|loop_stall|LoopWatchdog|loop_watchdog|blocked the event loop" src/probos; rg -n "def (_?elapsed_ms|_?ms_since|_?since_ms|_?to_ms|_?ms)\(" src; Get-ChildItem src/probos -Recurse -Filter '*timing*.py'
FOUND: no match; no match; no file
HOLDS: yes

CLAIM: no census or pin keys on a line number of an edited file, and none counts an effect this batch adds
RUN:   rg -n "filesystem_store\.py|audio/tts/resident\.py|routers/avatars\.py|routers/agents\.py|cognitive/cognitive_agent\.py|concurrency_manager\.py" tests scripts (py, json, yaml) then the three census fixtures
FOUND: file-write census rows are per file (`:204`, `:206`, no count); the effect census row for `resident.py` is `PiperWorker._spawn` (1 point; this batch adds no process or file effect); the stop-seam registry keys scope names; the other 17 files that name an edit target are behaviour tests (listed at G2 where they read the touched route or module)
HOLDS: yes (the oracle's G2 runs the census tests and the stop-seam inventory)

CLAIM: no config model, system.yaml key or generated artifact moves
RUN:   none run (no config file is edited by any block of section 7); the oracle's G2 runs the three config checks and the AD-1152 test
FOUND: -
HOLDS: expected, not measured
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** BF-918's stage-timing line and its closing recipe (the shape and the reader of the route line); BF-918 M4's constants-not-config decision (`ATTACHMENT_IO_WORKERS`, `VOICE_EXECUTOR_WORKERS`); BF-686's counter of volume the log no longer carries (`llm_client.py`, `_breaker_suppressed_exhaustions`: the model for `suppressed=N`); AD-754's redaction (the reason the lines avoid ten-digit runs and the key names it rewrites); the AD-672 queue's existing INFO lines; the intent id that already crosses the wire; the BF-933 and BF-937 contracts' conventions (slices, SEARCH rules, tracker anchors, the ledger gate, mutation rows). **Rejected:** section 3. **External:** none consulted.
- **Blind spots handled.** (1) The log has whole-second timestamps, so every duration is in the line. (2) The DM-recall line is not the turn's start; the issue's end marker is not general. (3) The redactor rewrites ten-digit runs and some key names: no absolute readings, no such keys, and cases S1 T13 and S2 R5. (4) A free lock must not show a stale holder: `locked()` gates the name; all five acquirers name themselves. (5) A per-instance budget, never a module-level one: no state outlives a case. (6) `cold` is read before the submit, inside the per-key lock, where no other request touches the worker. (7) Negative durations (a stamp of 0 or a skipped step) clamp to 0. (8) Stub tests assert lower bounds only. (9) The store's M4 tests gate `_save_index_sync` at class level: the batch does not touch it. (10) The censuses read files and scopes, not lines. (11) The awaits keep their order; no new await, thread, lock or task. (12) INFO, not WARNING: the boot warning counter and the log's readers.
- **What discards a correct result.** Slow-only lines drop the fast calls (by design: the route line still carries them); the budget declines lines past 12 a minute (counted, reported on the next line); a refused, cancelled or failed call writes no breakdown (L4, L6); the route line is written only when `send` returns and the turn line only for HXI DMs (L1, L2). **Recorded:** S1 L1 to L8, S2 L1 to L8.

## Batching

**One pull request and one broad gate for S1 and S2; S1 first, then S2; the two UI-only batches merge before it is built.**

| Point | Judgement |
|---|---|
| Files | Disjoint between the slices apart from the helper S1 creates and S2 imports; the tracker pair and the ledger pair collide with the other two batches: re-anchor, as the header says |
| Why together | One live call shows both: the same load window, the same store; BF-932's `find slow` and BF-930's store lines are one mechanism read from two sides |
| Order | S1, S2. S2 imports `probos/utils/step_timing.py`. Each M3 names its own issue |
| Revert | Separate commits per milestone and per slice; S2 reverts before S1 (S2 imports the helper) |
| Cost: Python | Per slice, the G1 and G2 files of section 4 at `-n 0`; once per batch, mine: the mutation rows and `PY scripts/run_test_gate.py --label bf930-932 --receipt logs/gates/bf930-932.receipt.json` |
| Cost: config | None: no key, no model, no yaml; the AD ledger pair is the only generated artifact (D5) |
| Cost: UI | None |

**What the rest wait for.**

| Item | Waits for | Why |
|---|---|---|
| The fixes | The numbers of the live call (the decision tables below) | The cause is not yet known |
| The LLM-lane slice | The BF-932 lines, if they exonerate every step before the recall and turns are still slow | D1 H7 |
| A loop-lag probe | `resume_lag_ms` large or the sum check not closing | D1(e) |

## Not in this issue: for the Captain

Each item is an operation on, or a measurement of, the running vessel. The build does not do it and neither can a test. None needs a decision. (`$D = "$env:LOCALAPPDATA\ProbOS\data\logs"`.)

1. **A free check on the existing log, before anything is built.** Action: `Select-String -Path "$D\probos.log*" -Pattern "AD-672: Intent 'direct_message' queued for agent"` around the three windows of the issue. Source of truth: the live log (the architecture of this logger: `probos.cognitive.concurrency_manager` is not in the list of loggers `_setup_logging` lowers to WARNING). Pass: the lines answer D1's H1. Present in the windows: the agent's queue was involved, and the fix to price is BF-731's priority at the agent's slot. Absent: H1 is unlikely and the rest of the table applies.
2. **A live call with the build deployed.** Action: restart on the merged build; hold a spoken conversation of at least 20 sentences and at least 5 typed Captain messages with the camera on, under the same kind of load as the issue's window (a catch-up after stasis, a dream cycle running). Source of truth: the log lines of the call and the Captain's ears. Pass: the markers `BF-918: tts route`, `BF-932: dm route` and `BF-932: dm turn` appear for the call (`Select-String -Path "$D\probos.log*" -Pattern 'BF-918: tts route|BF-932: dm (route|turn)|BF-930: '`), and the Captain counts the audible gaps.
3. **The numbers.** Action: the recipe of D6 for each marker (`BF-918: tts route`, `BF-932: dm route`, `BF-932: dm turn`, `BF-930: attachment write slow`, `BF-930: piper request slow`, `AD-672: Promoted queued intent 'direct_message'`). Source of truth: the same log. Pass: p50, p95 and count for each `_ms` field, posted on #1668 (the voice markers) and #1670 (the DM markers) by the Captain or the orchestrator: figures only, no crew name, thread id or timestamp.
4. **One DM joined end to end.** Action: take one `intent=<id8>` from a `BF-932: dm route` line and `Select-String -Path "$D\probos.log*" -Pattern 'intent=<id8>'`. Pass: the matching `dm turn` line; the pre-turn wait is `thread_ms + prep_ms + hook_ms + dispatch_ms` (route) + `waited_ms` (the queue line of that agent, when there is one) + `perceive_ms + recall_ms` (turn); the gap between that sum and the Captain's own wait is the residual of D1 H6.

**What the data must show to choose a fix** (the fix contracts come after the numbers):

| Data | Chooses |
|---|---|
| BF-930: stalled writes with `lock_wait_ms` about their whole time and `behind=write:perception_frame` or `reaper_unlink` | speed up the store: a lock domain of its own for the spoken audio (or none), or take storage off the first-audio path if the holder cannot be separated |
| BF-930: `index_ms` dominating with a large `index_entries` | speed up the store: the index off the write path (debounced or append-only) |
| BF-930: `locate_ms` or `find slow` lines dominating with `lock_wait_ms` near 0 | the store's thread pool: size, priority, or a direct path probe in place of the directory glob |
| BF-930: `blob_ms` dominating alone | disk contention: take storage off the first-audio path (return the audio before it is persisted) |
| BF-930: synthesis `lock_wait_ms`, or `pool_wait_ms` with a high `in_flight`, or `work_ms` with `cold=yes` | the per-voice queue, the voice executor, or a warm process (a synthesizer fix, not a store fix) |
| BF-930 or BF-932: `resume_lag_ms` large, or the sum of the fields not closing | the event loop is blocked: neither listed fix; the next slice is the loop-lag probe |
| BF-932: `hook_ms` near the cap plus lookups, or `find slow` lines for the frame | bound the describe end to end, or run it off the reply path |
| BF-932: `waited_ms` large, or queued lines for the DM | extend BF-731's priority to the agent's slot (reserve one or preempt a lower-priority active thread) |
| BF-932: `thread_ms` or `dispatch_ms` large | synchronous work on the loop (the thread store, the avatar snapshot): offload it (a new fix class) |
| BF-932: `perceive_ms` or `recall_ms` large | bound the recall for a Captain DM (a new fix class) |

## 13. Diff Reviewer: properties to verify

**S1.**
1. `step_timing.py` imports only the standard library; `emit_line` and `TimingLines.emit` catch `Exception` and never `BaseException`; `ms_between` clamps at 0; no module-level `TimingLines` exists anywhere in the batch (`rg -n "TimingLines\(" src` finds them only in `__init__` bodies).
2. `filesystem_store.py`: `write`'s awaits keep their order and the lock still brackets the three hops and the index save; no new `await`, `Task`, thread or lock; `_run`, `_save_index_sync`, `_locate_sync` are byte-identical; all five `async with self._lock` sites set `_lock_holder`; the holder is read only behind `self._lock.locked()`; the line is written after the `async with` and not on a raise.
3. `resident.py`: the per-key lock, `_claim`, `run_in_executor` and the three exception arms are unchanged and in the same order; `thread_started` and `thread_ended` are written only in `synthesize_blocking`; the line is after the `finally` and uses `outcome`, `t_resumed` and `cold`, all defined on that path.
4. `avatars.py`: the old fields keep their order and values; `id=` is last; the `degraded` line is untouched.
5. No config key, no model, no generated file; `git diff --stat` for S1 M2 shows five paths (the helper, the store, the resident module, the route, the test file).
6. The tests restore their patches and carry no module-level budget; no case asserts an upper bound on a measured time.

**S2.**
1. `routers/agents.py`: stamps only; the hook, the cap (`timeout_s=4.0`), the send (`raise_on_denial=True`) and their order are unchanged; the line is after the send; `_params` gained nothing.
2. `cognitive_agent.py`: the line is written after the recall and before `decide`, for HXI DMs only; the function-local import follows the file's own pattern; no signature changed.
3. `concurrency_manager.py`: the old text of the promotion line is a prefix; `ms_between` reads `time.monotonic()` against `queued_at`, the same clock.
4. `git diff --stat` for S2 M2 shows four paths (the route, the agent, the manager, the test file).

**Both.** Public text: no crew name, thread id, timestamp or live figure in any test, comment, tracker line or commit message; the tracker text has no `AD-` token and no BF number but its own; M3's `Refs` lines, never `Closes`; the new lines survive `PIIRedactor.redact_all` (S1 T13, S2 R5).

## 14. Acceptance criteria

1. G1, G2 and G3 of each slice pass as stated in section 4; the oracle's mutation rows and the broad gate (`--label bf930-932`) pass; the three config checks and the AD-1152 test are unchanged.
2. A slow store write names its steps and what held the lock (S1 T1, T2); a slow lookup names its time and the index size (T4); a slow Piper request names its lock wait, claim, pool wait, work, resume lag, cold start and load (T7 to T9); each is bounded (H3, T5) and failure-isolated (H5).
3. The route's old fields are unchanged and the audio id joins it to the store's line (T11, T12).
4. A Captain DM writes one route line with its steps and the intent id, and an HXI DM turn writes one line with its perceive and recall times under the same id (R1, R1b, A1); the queue's promotion says how long the intent waited (C1).
5. Nothing changes: the TTS response, the store's results, the synthesizer's audio and degrade, the DM route's order, cap and reply, the queue's old line text (T3, T6, T10, T12; R4, R6, C2, A2 and the existing suites of G2).
6. Both issues stay open; every M3 says `Refs`; the live actions and the decision table of the last section are recorded on the issues by the orchestrator.
7. No config key is added; the AD ledger pair is the only generated artifact; no `?raw` or source-scan test reads an edited file for a line this batch changes (section 11).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-13): the format the apply tool needs, cases that fail at an assert, the measured gates and mutation rows

**Drafted by:** the orchestrator, not the Architect: every change below follows a measurement on the oracle (the blocks applied by tool on a scratch tree over the base after the two UI-only batches, a scratch commit per milestone), so it is mechanical. **Sections 1 to 14 are read with this section; where they differ, this section wins.**

**What the oracle found in section 7, and what A1 changes in it** (a block of code is named as such; every other block is unchanged):
1. **Six label lines named no file the apply tool can resolve.** The tool takes a pair's file from the nearest preceding label line that names an existing path (a bare name such as `resident.py` resolves to nothing). The label lines of S1 P2-1, P2-12 and N2-1 and of S2 P2-7, P2-8 and N2-1 now carry the full path in backticks. No SEARCH or REPLACE changed.
2. **S1 N1-1 (a block of code) failed its M1 gate:** `11 failed, 2 passed, 6 xfailed` instead of `3 passed, 16 xfailed`. The marker `built` is `xfail(raises=AssertionError)`, so a case must fail at an `assert`; eleven `monkeypatch.setattr(<module>, "SLOW_STORE_CALL_MS" or "SLOW_SYNTHESIS_MS", 0.0)` calls raised `AttributeError` (neither constant exists before M2), and `[line] = _lines(...)`, `_lines(...)[-1]` and `max(...)` over no lines raised `ValueError` or `IndexError`. Corrected in the block: `raising=False` on the eleven setattr calls; two helpers, `_one` (asserts exactly one line) and `_last` (asserts at least one); T1, T2, T4, T7, T8 and T12 use them and T9 asserts its count before `max`. G1 now gives `3 passed, 16 xfailed (19)`; with `BF930_RUNXFAIL=1` `16 failed, 3 passed`, every failure at an `assert`.
3. **S2 N1-1 (a block of code) was three fenced blocks, and the apply tool writes the first fence only** (6 of the 11 cases); its agent cases used a `make_agent` that the first text left to the oracle. Joined into one fenced block (the explanatory notes are dropped: R6's is section 6's); `make_agent` is defined (`_DmAgent`, a `CognitiveAgent` that handles a direct message, built with `MockLLMClient` as `tests/test_cognitive_agent.py` builds its agents); the seven `[x] = _lines(...)` unpackings use `_one`. G1 now gives `4 passed, 7 xfailed (11)`; with `BF932_RUNXFAIL=1` `7 failed, 4 passed`, every failure at an `assert`.
4. **Case counts.** S1 has 19 cases and S2 has 11, as the header and section 6 say; the label lines of the two `N1-1` blocks said 20 and 10 (corrected).
5. **S1 mutation rows.** Row 4's line occurs twice in `step_timing.py` (`self._suppressed = 0` is in `__init__` and in `emit`): the row now names the second occurrence. Four Killed-by cells were short or wrong (measured): row 12 is killed by T1 and T12; row 14 by T1 only (T4 reads the lookup line, which carries no write count); row 16 by T8 and T13; row 17 by T7 and T13. The other fifteen rows and all eight S2 rows give the cells of section 9.

**Measured gates** (the oracle). **S1.** M0 (the nine existing files of G2, `--collect-only`): 130 tests. G1 at M1 `3 passed, 16 xfailed (19)`. G2 at M2: command 1 (six files) `120 passed` (101 at M0 plus the 19), command 2 (four files) `29 passed`; the architecture check passes (`srp-size=92, layer-import=0, db-connect=30, unowned-task=13`); `gen_config_reference.py --check`, `check_config_profiles.py --check` and `check_config_facade.py --check` pass unchanged (D5 holds) and `tests/test_ad1152_agentic_correlation.py` gives 41 passed. M2's diff: `filesystem_store.py` +35 -0, `resident.py` +28 -0, `avatars.py` +2 -1, `step_timing.py` new (73 lines), the test file +3 -5 (the marker). **S2.** M0 (the eleven existing files of G2): 282 tests. G1 at M1 `4 passed, 7 xfailed (11)`. G2 at M2: command 1 (nine files) `244 passed` (233 at M0 plus the 11), command 2 (three files) `49 passed`; the architecture check passes. M2's diff: `agents.py` +25 -0, `cognitive_agent.py` +12 -0, `concurrency_manager.py` +3 -1, the test file +3 -5. **Wide consumer run** (the 111 test files that name an edited module and are in no G2 set, serially, on S2 M2's head, which holds both slices' source changes): `4483 passed, 2 skipped, 0 failed` in 1,268 s.

**Measured ledger movement.** S1 M3 moves **BF-930 and BF-932** (Shipped BF +930, +932; Unaccounted BF -930, -932: the contract commit's subject names both), as section 4 predicted; numstat `8 0` DECISIONS, `4 0` PROGRESS, `9 3` the snapshot, `6 6` the report. S2 M3 moves no number; numstat `8 0`, `4 0`, `3 3`, `3 3`.

**Measured mutation rows.** S1, 19 rows: **every mutant is killed**; fifteen rows match section 9 and four (12, 14, 16, 17) are corrected above; row 4 names its occurrence. S2, 8 rows: **all eight give the cells of section 9 exactly.**

**Recorded limit (addition).** **S2 L9.** `ArchitectAgent.perceive` (`cognitive/architect.py:239-305`, a `.complete(` on line 305) calls the model, so for a DM to that agent `perceive_ms` includes a model call. An AST scan of the 45 `perceive` definitions under `src/probos` (positive controls held: 79 `.complete(` calls found outside any `perceive`) finds that one only, so D1's statement that the LLM lane lies outside the window holds for every other crew agent and not for this one. The turn line names the agent (`agent=`), so a reader can set it aside.

**What A1 changes.** The header (a `Revised by` line), six label lines, the two `N1-1` count remarks, the two test files of section 7 (blocks of code, as described), four cells and one line cell of section 9, and this section. No block of M2 or M3 changed.
