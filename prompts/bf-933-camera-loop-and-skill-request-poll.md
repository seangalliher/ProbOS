# BF-933 (#1671): the camera capture loop of one live video call no longer leaks under overlapping starts, honours a 429 and never overlaps its own uploads; the skill-request poll already stops on a typed-disabled store (pinned, no source change); the 5 s freeze and the Three.js copies are named for the orchestrator and the Captain

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge is logged out), 2026-11-13
**Revised by:** the orchestrator (amendment A1, section 15: the base after the voice batch, the measured gates and mutation rows, eight Killed-by cells of section 9; no block of section 7 changed), 2026-11-13
**File in the repository:** `prompts/bf-933-camera-loop-and-skill-request-poll.md` (the orchestrator may rename it). **Answer file:** in three parts, because the contract is too long for one `create` call: `answer-bf933-contract.part1.md` (this header, sections 1 to 6), `answer-bf933-contract.part2.md` (section 7: slices S1 and S2, and 7.3, the orchestrator's dedupe action), `answer-bf933-contract.part3.md` (sections 8 to 14, "Batching", "Not in this issue: for the Captain"). Read them in that order; the labels of section 7 restart in each slice.
**Status:** ready to build on `origin/main` `f614a31d855e217eec6c826deaffad7572d1f43f` (BF-937's merge) **after the voice batch (BF-928, BF-929, BF-931) has merged**. **Reading tree:** `D:\ProbOS-worktrees\next-read` at `f614a31d855e217eec6c826deaffad7572d1f43f` (clean; read only). **Oracle:** the Architect ran no pytest, no vitest, no UI build and no npm command (a read-only consult). **What I ran instead** (section 11): every SEARCH of section 7 against the LF blobs of the reading tree (occurrences, line start, ASCII); a static comparison of the force-graph stack's `three` imports with the installed r172 (section 3, D7); a count of the duplicate-instance warning in the installed copies and in the one prebuilt `dist` of the main checkout; the existing suites read, case by case, for what they already pin. **What that leaves unchecked (all "expected" below):** every vitest case as a vitest case (the counts), `window === globalThis` under vitest's jsdom (the new tests rely on fake timers reaching `window.setInterval`), `npx tsc -b`, `npm run build`, the ledger regeneration, the broad gate, and everything that needs the live vessel or the Captain's eyes (section "Not in this issue: for the Captain").
**Base blobs (`f614a31d`):** S1: `ui/src/hooks/useCameraStream.ts` `e560781c1b9f3eb9c307b563616ae1fab07bc30a` (unchanged since `5e3cc991`: `git log 5e3cc991..HEAD -- <path>` prints nothing). S2 edits no source. All slices: `PROGRESS.md` `70cd1044019282b348bba2532acd6bfb2b6369cf`, `DECISIONS.md` `90adc2837c3d2c6d09327e93543eeb0471880fec`, `docs/development/open-ads-report.md` `04562090a74a962b09f61864a667ecb1a62f1b8a`, `docs/development/ad-ledger-snapshot.json` `35de650056f112a17d079fab48f32ddabad939bb` (these four are the blobs the voice contract's A1 measured on `f614a31d`; **the voice batch moves all four before this batch is built**, and every code blob below must be equal). Read, not edited: `ui/src/hooks/__tests__/useCameraStream.test.ts` `a9ea9304f39215f982d367aa40e0fcc0581f4b34`, `ui/src/store/useStore.ts` `d67246cf32182520685b12d2c0b6e909766214c8`, `ui/src/utils/resourceState.ts` `c3a11256629d651f408f01ed258bc6ec9f881309`, `ui/src/store/approvalPolling.ts` `49a25fbd29f7715414d1156e509d10324b55d9c2`, `ui/src/components/skill/SkillRequestPanel.tsx` `bb683ace798aa836b5290a6d7fc8ace0c008aa2c`, `ui/src/__tests__/SkillRequestPanel.test.tsx` `274b18566f626e71a3dfdf5ffdff281113996fd0`, `ui/src/components/approvals/__tests__/ApprovalsInBridge.test.tsx` `6ceb385ce6086b69c1796abd0ba749816a7e2456`, `ui/src/store/__tests__/approvalPolling.test.ts` `af8471083e504a6aa75a5c6f8e5a523793f7951e`, `src/probos/routers/skill_requests.py` `a0a5c7d12e3357d51ac0f88aca0ae8c551256ab9`, `src/probos/routers/readiness.py` `17b72ecf61a9c44bb7b9cd399bf0b277bc4026e7`, `src/probos/routers/perception.py` `83b453f869b970e8422028e86e967e381b42d531`, `ui/package.json` `ffef098d3560217203997ae0c0953e3a29855036`, `ui/package-lock.json` `ee83f90238b536de91bb22dc75bd0aeba0eb1efb`, `ui/vite.config.ts` `c21862f483cd88f4aa08527a934a7bae464e895e`, `.github/workflows/ci.yml` `62ca9c8f4db192fb6648b7cbcf8c6d2cb650b18b`. **`ui/src/components/profile/ProfileChatTab.tsx` (`3ed3ee2a6c738e6fb4c0467c3e5fd920cbc40986` on `f614a31d`) is NOT edited by this batch**, so the voice batch's edits to it (the import at line 58, a block after line 885) cannot collide with a block of mine; neither are `MeetingView.tsx` nor `PerceptionLivePanel.tsx`. None of the three new paths exists (`ui/src/hooks/__tests__/useCameraStream.bf933.test.ts`, `ui/src/store/__tests__/approvalPolling.bf933.test.ts`, `prompts/bf-933-camera-loop-and-skill-request-poll.md`: `Test-Path` printed False for each).
**Dependencies:** the voice batch merges first (it shares no file with this batch except the four tracker files). **Tier:** S1 M1 STANDARD (tests), S1 M2 HIGH (module-scoped state of a hardware-facing capture loop), S1 M3 STANDARD; S2 M1 STANDARD (tests only; **S2 has no M2**), S2 M3 STANDARD. **Estimated tests (expected, not measured):** S1 one new file, 19 cases (7 pass, 12 expected failures at M1); the existing `useCameraStream.test.ts` (3 cases) unchanged and green. S2 one new file, 4 cases (all 4 pass at M1: characterization). No Python test, no config, no generated artifact but the AD ledger pair. **Numbers:** BF-933 is held by #1671 only (section 11, Absence Verified); nothing new is allocated.

**Tracker anchors (state as the voice contract does; the orchestrator re-anchors after the voice merge).** PROGRESS.md: the title line `# ProbOS Progress` and the blank line after it (once, at the start of the file on `f614a31d`, where BF-937's slice 2 entry follows it; the SEARCH is unchanged by any entry inserted below it; the voice batch inserts at the same place, so this batch's entries land above theirs). DECISIONS.md: the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)` (once, ASCII, at line 1710 on `f614a31d`; every BF entry of this period inserts before it, so this batch's entries land after the voice batch's, in slice order). **The orchestrator re-runs the occurrence check of those two SEARCHes after the voice merge (each exactly once, at a line start, ASCII); any other change to either file between `f614a31d` and the build's base is a hard stop for the Architect.** The AD ledger pair is regenerated at each M3 by `scripts/gen_ad_ledger.py` (G3) and is not merged by hand. **No tracker line of this batch contains the token `AD-`** (the ledger reads AD and BF numbers at the head of tracker entries and in commit subjects); each head names BF-933 only.

## 1. Problem

The issue (#1671, copied at `...\files\bf933\issue-1671-copy.md`) reports four front-end defects of one live video call. Its anchors are from `5e3cc991`; every one is re-derived on `f614a31d`. Its live claims (the 429 counts, the length of the violation, the console lines, the Captain's session) are quoted nowhere in this contract: no test, comment, tracker line or commit message of this batch holds them (decision D8), and none of them is verified here.

| Issue item | Re-derived on `f614a31d` | Verdict |
|---|---|---|
| 1. 429 flood, leaked capture loop | `ui/src/hooks/useCameraStream.ts`: the guard `if (_stream) return; // idempotent` `:161`; `_stream` is assigned only after the `getUserMedia` await `:177-181`; `_video`, `_canvas` and `_sessionId` are module variables written after it `:190-202`; the interval is created `:207-209` into the one module variable `_intervalId` (`:20`); `_stopTracks` clears that one id `:61-64` and `stopCameraStream` is `_stopTracks` plus `reset()` `:212-215`; the frame sender drops a 429 `:146` and never reads `Retry-After`. Callers that can overlap: `ProfileChatTab.tsx:1205` (`handleStartCall`; the stop is `:1219`), `MeetingView.tsx:267` and `PerceptionLivePanel.tsx:149-151`, both toggles that call `start` while the store's `active` flag (set only after the whole start, `:204`) is still false. Server: `routers/perception.py:180-185` answers 429 with `Retry-After: 1` when `_check_rate` (`:46-62`) finds no token in the bucket of `(session_id, source)`; `config/system.yaml:1784` `camera_max_fps_server: 4`. | **Confirmed in the code**, and wider than the issue says: two overlapping starts also open two cameras and the first stream is never stopped; a stop that arrives while the camera is opening finds `_stream === null`, stops nothing, and the start then runs; there is no in-flight guard on a tick. Whether this produced the live flood is the issue's account. |
| 2. 5 s main-thread freeze | The only code in a `setInterval` handler of this path is `void _captureAndUpload()` `:207-209`; the handler's own time is the synchronous prefix of `_captureAndUpload` `:98-118`: the size guards, `_canvas.width/height` `:106-107`, `getContext('2d')`, `ctx.drawImage(_video, ...)` `:112`, and the call of `toBlob` `:116-118` (its first `await`). Everything after the first `await` (the form, `_computeAgentIds`, the `fetch`) is not in the handler's time. | **Cannot be identified by reading.** The in-flight skip removes ticks that start while an upload is pending (the stacking of leaked loops and of slow uploads); it cannot shorten one tick's synchronous prefix, so a single 5 s handler is not explained by stacking. The likely blocker is the browser's synchronous read-back inside `drawImage` or the snapshot taken by `toBlob`: unmeasured. What stays live: section "Not in this issue: for the Captain", item 2. |
| 3. Three copies of Three.js | `ui/package.json` `three ^0.172.0` and `@types/three ^0.172.0`; `ui/package-lock.json:6047` root `three` 0.172.0, `:2820` `3d-force-graph/node_modules/three` 0.183.2, `:5933` `stats-gl/node_modules/three` 0.170.0. Declared needs: `3d-force-graph` 1.80.0 `three >=0.179 <1` (`:2812`), the nested `three-render-objects` 1.41.1 peer `>=0.179` (`:2842`), `stats-gl` 2.4.2 `three ^0.170.0` (`:5926`), `postprocessing` peer `>= 0.157.0 < 0.184.0` (`:5367`); every other `three` range in the lock is a lower bound. `.github/workflows/ci.yml:155` runs `npm ci`. | **Confirmed, and structural** (D7): the force-graph stack needs `Timer` from Three.js >= r179, which r172 does not export, so a single copy cannot be the app's r172. The prebuilt `dist` of the main checkout holds the duplicate-instance warning twice (two bundled copies; `stats-gl` has no runtime `three` import and the app imports no `Stats`). Not closable from tests. |
| 4. Polling a disabled skill-requests endpoint | `routers/skill_requests.py:86-105`: with no store the route answers 503 with `{"detail": ..., "availability": unavailable_dependency(config, "skill_requests")}`, which is `{"state": "disabled", "code": "skill_requests.disabled", "message": "Disabled. Review configuration with the operator.", "retryable": false}` when `config.skill_requests.enabled` is False (`routers/readiness.py:32-45`; the field defaults to False, `config_models/crew.py:241-249`; `config/` sets no `skill_requests` key). The HXI has two readers: the shared queue `ui/src/store/useStore.ts:2745-2825` (URL `:2770`) and the standalone panel `SkillRequestPanel.tsx:244-282` (URL `:263`); both classify through `requestResource` (`ui/src/utils/resourceState.ts:87`), whose `availabilityStatus` (`:50-60`) reads that body as `disabled`, and both schedule through `nextResourcePoll` (`:22-28`), which returns `nextAt: null` for `disabled` (`:24`). The warning the issue quotes is `useStore.ts:2805`, printed only for `unavailable` and `failed`, with the **failing queue's name interpolated**: the issue's line names the *capability* queue. | **The acceptance is already met on the base**, and the premise is not supported by the code: the typed body has been served since #1394 (`144993a2`, 2026-09-13) and the stop-on-disabled logic existed at `5e3cc991` (`git show 5e3cc991:ui/src/utils/resourceState.ts`). Existing suites pin the request count (section 6, S2). What no case pinned: that a typed-disabled read logs nothing. |

**S1: the six defects of the capture loop (all in `useCameraStream.ts`).**

1. **Concurrent starts.** Two calls that overlap both pass `:161`, both call `getUserMedia`, both assign `_stream` (the second overwrites the first, whose tracks are never stopped: the camera stays open after a stop), both register a stream, both write `_video`, `_canvas` and `_sessionId`, and both create an interval; the second `window.setInterval` result overwrites `_intervalId` and the first interval can never be cleared. Every leaked loop ticks at the call's frame rate against one server bucket (`(session_id, source)`, burst `camera_max_fps_server`), so enough of them exhaust it.
2. **A stop during a start is lost.** `stopCameraStream()` while `getUserMedia` (or `play()`) is pending runs `_stopTracks` with nothing to stop; the start then stores the stream and creates the loop. `handleEndCall` (`ProfileChatTab.tsx:1219`) and the page-unload handlers (`App.tsx:70`, `CompactApp.tsx:118`) can land in that window. The UI cannot express a stop during a start from the two toggles (`active` is false until the start completes, so a second click calls `start` again, which is item 1).
3. **A stop followed by a start while the first start is pending.** A fix that only cancels the first start and lets the second share its promise loses the second call: the shared start would resolve into a cancelled epoch and nothing would run. The stop must also detach the pending start.
4. **A 429 is dropped.** `:146`; `Retry-After` is ignored; the loop retries on the next tick.
5. **No in-flight guard.** A tick starts a capture and an upload whether or not the previous one has finished; a slow upload makes uploads overlap, and with several loops the main thread queues several `drawImage` and `toBlob` calls.
6. **Module state outlives a test.** `_testReset()` (`:217-220`) goes through `_stopTracks`; every new module variable must be reset there, or one case's pending start, in-flight flag or pause leaks into the next.

**S2: what the base already does for the skill queue** (all read, none run): a typed-disabled 503 gives `status: 'disabled'`, `retryable: false`, `nextAt: null`: one read, then no automatic read; the capability queue keeps its cadence (pinned: `ApprovalsInBridge.test.tsx:620`); the standalone panel stops the same way (pinned: `SkillRequestPanel.test.tsx:226`, `1` request over `120_000` ms); a plain 503 is `unavailable` and bounded to reads at 0, 10 and 30 s with a warning each (`approvalPolling.test.ts:135-148` pins the bound for a hung read; `SkillRequestPanel.test.tsx:202` pins the schedule); acquiring a lease re-reads a queue once, by design (`approvalPolling.test.ts:150`, for `unauthorized`). The unpinned part is exactly the issue's "no repeated console errors" for the typed-disabled case (Absence Verified: no test spies `console.warn` for it) and the name of the queue in the warning.

## 2. Solution

**S1 (BF-933 slice 1, HIGH, `useCameraStream.ts` only; no export added, so every `vi.mock` factory of the ten files that mock the module stays valid and the callers are unchanged).** One pending start is shared by concurrent callers (`_startInFlight`); an epoch (`_epoch`) that every stop bumps is how a start that is still waiting for the camera or the video learns it was cancelled: it releases the stream it was granted and creates no loop; the stop also drops the pending start, so a later call starts afresh. A tick returns at once while an upload is in flight (`_uploading`, owned by the epoch that set it; the upload is aborted after 10 s so the guard cannot stick) and while a 429 pause runs (`_resumeAtMs`): the `Retry-After` of the response (seconds or an HTTP date), else 1 s, 2 s, 4 s, capped at 30 s; a 200 starts the doubling over and so does a stop. The capture primitive is not changed.

**S2 (BF-933 slice 2, STANDARD, tests only, no M2).** One new test file in the style of `approvalPolling.test.ts` that pins what the base does and the existing suites leave open: a typed-disabled skill read happens once and logs nothing; a plain 503 is bounded and names the skill queue; an enabled queue is unchanged; a re-acquired lease asks a disabled queue once more.

**Not built, and why (D5, D7).** The freeze fix (no test can show an offload removes a stall that is not identified); the Three.js dedupe (needs `npm install` and the Captain's eyes on the avatar; section 7.3 is the orchestrator's procedure, outside this PR).

## 3. Decisions

Each table ranks the options by correctness, safety, compatibility, fit, reversibility and validation cost; the first row is the decision. In-envelope means evidence, backward compatibility, no weakened control, no OSS/commercial boundary crossed, bounded rollback.

**D1. Slicing and closure.**

| # | Option | Judgement |
|---|---|---|
| 1 | **S1 camera + S2 skill-queue pins in one pull request; the dedupe a separate orchestrator-run action; #1671 stays open with a recorded checklist; every M3 says `Refs #1671`** | Claims only what closes. Both slices are UI-only and close from vitest; each reverts alone; one gate (focused vitest, `tsc -b`, then once `npm run build`, the whole vitest, the mutation rows, the broad gate). The avatar's Three.js is not moved inside a PR that only jsdom gates |
| 2 | S1 + S2 + the dedupe as S3 in the same PR | One PR, but the dedupe needs `npm install` (never the Builder), changes `package-lock.json` that CI's `npm ci` validates, and moves the avatar from r172 to r183 with no test that sees it: the gate cannot judge the risk it carries |
| 3 | S1 only; the skill-queue finding recorded on the issue with no test | Cheapest; leaves the issue's "no repeated console errors" unpinned and the quoted capability-queue line unexplained in code |
| 4 | Everything, `Closes #1671` | A false closure: the freeze and the dedupe stay open |

**Closure matrix.**

| Part of #1671 | Closes by | What stays |
|---|---|---|
| Overlapping starts, stop during a start, `Retry-After`, no overlapping uploads | S1's vitest (19 cases) | The Captain's live call: no sustained 429s in the console (a live check, item 1 of the last section) |
| Skill-request poll | Already true on the base; S2 pins its unpinned half; the proof is the three existing suites plus S2's file green on the oracle | Optionally one `curl` of the live route (item 4 of the last section) |
| 5 s freeze | **Not by this batch** | A profile of a live call; the in-flight skip is a mitigation for stacking only |
| Three.js dedupe | **Not by tests** | Section 7.3: the orchestrator's `npm install`, the build count, the whole vitest, then the Captain's look at the avatar and the graphs |

**Disposition of #1671.** It **stays open with the checklist above** (the orchestrator posts it as a comment): no slice carries `Closes #1671`, all `Refs #1671`. Filing the remainder as one follow-up now would open an issue for a freeze that is not identified and a dedupe that is not decided, and would spend this wave's one allowed follow-up. If the orchestrator prefers to close #1671 with this batch, it files **one** follow-up holding the two remaining entries as separate checklist entries (the freeze measurement; the dedupe), and the only change to this contract is the last line of S2 M3's body (`Closes #1671.`).

**D2. The guard for concurrent starts.**

| # | Option | Judgement |
|---|---|---|
| 1 | **A shared promise (`_startInFlight`) plus an epoch bumped by every stop** | Fixes items 1 to 3 of section 1 in the one place every caller goes through; the second caller waits for the camera instead of returning early; no new export; reversible by one revert |
| 2 | A boolean lock (`_starting`): later callers return at once | The second caller returns before the camera exists; a stop during a start is still lost |
| 3 | A guard in each caller (`cameraActive` or a local flag) | Three callers today and the hook is the idempotent unit by its own comment; a new caller reopens the defect |
| 4 | Replace the module variables with a session object | The right shape one day; a refactor the defect does not need, touching every reader of the module state |

**D3. A 429.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Skip ticks until the deadline: `Retry-After` (seconds or HTTP date), else 1 s, 2 s, 4 s ..., cap 30 s; a 200 and a stop reset** | The acceptance's "honours `Retry-After` (or backs off)"; the interval and its timer count do not change; bounded |
| 2 | Honour only a valid header; no fallback | A 429 without a usable header would keep the old behaviour |
| 3 | Stop the camera after N consecutive 429s | A visible behaviour change (the camera goes off) the issue does not ask for |
| 4 | Lower the frame rate dynamically | More state for the same effect |

**D4. A tick while an upload is in flight.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Skip the tick, and abort the upload after 10 s so the guard cannot stick** | The acceptance names the skip; the abort keeps the loop live when a request never answers (a skip alone would pause the camera for good) |
| 2 | Skip with no timeout | Silent stall on a hung request |
| 3 | Queue the frame | Unbounded memory under a slow server |

**D5. The 5 s freeze.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Ship the skip (it is the issue's own named option and removes stacking); change nothing in the capture primitive; leave the identification to a profile of a live call** | A single 5 s synchronous handler is not explained by stacking, and no test in jsdom (which has no canvas, no video decode, no GPU) can show that an offload removes a stall that is not identified; a guessed offload would be a test pinning a guess |
| 2 | `createImageBitmap` plus `OffscreenCanvas.convertToBlob` now | Plausible and unmeasured; pins an API shape, not an effect |
| 3 | A timing seam that logs a slow phase | Useful, but new log output and new state in the hook for a measurement a profile gives for free; recorded as the next step if the profile is inconclusive |

**D6. The skill-request poll.**

| # | Option | Judgement |
|---|---|---|
| 1 | **No source change; pin the unpinned half (the console, the queue name in the warning, the per-lease re-ask, the enabled cadence)** | The acceptance is already met; a pin is the honest slice; no risk to the approvals surface |
| 2 | A session-wide memo that skips the read after a typed-disabled answer | Contradicts the pinned rule that re-acquiring a lease refreshes a queue (`approvalPolling.test.ts:150`), and a disabled queue can be enabled by a server restart the HXI outlives |
| 3 | Read the service-readiness integrations (`useServiceStatus.ts`) before the first read | A second source of the same fact and a new coupling between two stores |
| 4 | Warn for `disabled` too | The opposite of "no repeated console errors" |

**D7. The Three.js copies (evidence first).** Measured on the installed packages of the main checkout (read only): `three-render-objects@1.41.1` (`dist/three-render-objects.mjs:1`) imports `Timer` from `'three'` and constructs `new three.Timer()` (`:471`); `Timer` is a class of r183's `three.core.js` and is not exported by r172 (the static comparison of every named `three` import of `3d-force-graph`, `three-render-objects`, `three-forcegraph` and `stats-gl` against both builds lists `Timer` as the only name missing from r172, and none from r183). `stats-gl@2.4.2`'s `dist/main.js` has no import of `three` at all, and `ui/src` imports neither `stats-gl` nor a drei `Stats`. So two copies are bundled (root r172 and the force graph's r183; the third is on disk, types-only) and the "stats overlay" the issue asks to check is not used by the app.

| # | Option | Judgement |
|---|---|---|
| 1 | **Align the app up to the r183.2 the force-graph stack already resolves: `three ^0.183.2`, a matching `@types/three`, `overrides {"three": "$three"}`; run as the orchestrator's separate action (section 7.3), merged only after the avatar and graphs are looked at** | The only single-copy state that satisfies every declared range (`postprocessing` `< 0.184.0` holds); the force graph is unchanged for its renderer and gains consistency for `three-forcegraph` and `MemoryGraph3D`, which today hand r172 objects to an r183 renderer. Risk: the avatar and every R3F canvas move 11 minors; no test sees it; rollback is two files |
| 2 | `overrides {"three": "$three"}` with the root left at `^0.172.0`, or Vite `resolve.dedupe: ['three']` | **Rejected by evidence:** `three-render-objects` imports `Timer`, which r172 lacks; a bundler reports the missing export, or the browser fails to link the module |
| 3 | Downgrade `react-force-graph-3d` to a release whose stack predates `Timer` | Not measured (needs registry metadata this consult did not read); would still leave `stats-gl` and a pinned older graph library |
| 4 | Leave two copies; record the Timer evidence as the reason | Zero risk now; the warning and the class-identity risk stay |

**D8. Public text (overrides the acceptance where it differs).** This repository is public: no test, comment, tracker line or commit message holds a crew name, a thread id, a timestamp, a console line or a count from the live vessel. Synthetic fixtures with the same shape stand in: a fake camera whose `getUserMedia` the test settles by hand, a fake `<video>` and `<canvas>`, a stubbed `fetch` answering the statuses the server uses, a `Retry-After` of `3`, `soon`, `3600` and an HTTP date, a 503 body with the shape the route sends. **Overrides:** (a) "In a live call the console shows no sustained 429s" and "no `setInterval` violation over 50 ms during a 5-minute call" are live checks (the last section), not tests; (b) the issue's quoted warning line is not a fixture (S2's cases build the warning from the store's own code and compare a stable fragment, `Approval skill queue read failed`); (c) the acceptance's "a test calls `startCameraStream()` twice without awaiting, then `stopCameraStream()`" is honoured (S1 T1), measured as one `getUserMedia` call, one `window.setInterval` call, one pending timer after the starts and none after the stop.

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. UI commands run **from `ui/`**, Python commands **from the repository root**, each exactly as typed. **Who runs what.** The Builder may run: the focused `npx vitest run ...` of G1 and G2 and `npx tsc -b`, only where `ui/node_modules` exists (the reading tree has none; a Builder tree without it applies the blocks and stops, saying so); the Python of G3. The Builder never runs `npm install`, `npm ci`, `npm update`, `npm run build`, the whole `npm run test`, Playwright, or the broad gate. **Mine (the orchestrator's):** every UI command on the oracle with the main checkout's `node_modules`, `npm run build`, the mutation campaign, the wide consumer runs, section 7.3, the broad gate, the pull request and CI's `ui-tests` (`.github/workflows/ci.yml:122-163`: `npm ci`, `npm run test`, `npm run build`, Node 22).

**M0 (each slice, on the head before the slice):** run the slice's G2 vitest command and record `Test Files` and `Tests` (it passes on the base).

| Slice | M | Blocks | Gate |
|---|---|---|---|
| S1 (camera loop) | M1 | N1-1 | G1 |
| S1 | M2 | P2-1 to P2-8c (ten blocks), then N2-1 (the marker) | G2 |
| S1 | M3 | P3-1, P3-2, ledger | G3 |
| S2 (skill-queue pins) | M1 | N1-1 | G1 (no xfail: 4 pass) |
| S2 | M2 | none | |
| S2 | M3 | P3-1, P3-2, ledger | G3 |

**S1.**
- **G1.** `npx vitest run src/hooks/__tests__/useCameraStream.bf933.test.ts`. **Expected: `7 passed | 12 expected fail (19)`** (the 12 are `it.fails` cases that failed as expected; the 7 are controls). Then `$env:BF933_RUNXFAIL='1'; npx vitest run src/hooks/__tests__/useCameraStream.bf933.test.ts; Remove-Item Env:BF933_RUNXFAIL`: **expected 7 passed, 12 failed**, each at its own `expect` (a call count, a pending-timer count, a released stream, the store's `error`), never at an import or a premise.
- **G2.** `npx vitest run src/hooks` (the hook's three suites: the existing `useCameraStream.test.ts`, the new file, `useScreenStream.test.ts`, and the other hook suites of the directory). **Expected:** `Tests` = M0 + 19, 0 failed. Then `npx tsc -b` (type-checks the sources and the tests): clean. **Wide consumer run (mine):** `npx vitest run src/components/perception src/components/profile/__tests__/MeetingView.captain.test.tsx src/__tests__/CompactApp.sidebar-integration.test.tsx src/components/profile/__tests__/ProfileChatTab.ad1291.e2e.test.tsx src/components/profile/__tests__/ProfileChatTab.audioControl.test.tsx src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx src/components/profile/__tests__/ProfileChatTab.bf764.test.tsx src/components/profile/__tests__/ProfileChatTab.groupReplyIdentity.test.tsx src/components/profile/__tests__/ProfileChatTab.groupsend.test.tsx src/components/profile/__tests__/ProfileChatTab.issue1340.groupUnmount.test.tsx src/components/profile/__tests__/ProfileChatTab.threadTranscript.test.tsx`: the ten files that mock the hook (they replace the module, so a change inside it cannot reach them) and the `?raw` reader that pins `if (video) void startCameraStream()`; **expected: unchanged from M0**.

**S2.**
- **G1.** `npx vitest run src/store/__tests__/approvalPolling.bf933.test.ts`: **expected `4 passed (4)`** (no `it.fails`: every case passes on the base).
- **G2.** `npx vitest run src/store src/__tests__/SkillRequestPanel.test.tsx src/components/approvals src/components/bridge src/__tests__/ApprovalPanels.bf710.test.tsx src/__tests__/CapabilityRequestPanel.test.tsx` (every suite on the approval queues: the existing pins). **Expected:** `Tests` = M0 + 4, 0 failed. Then `npx tsc -b`: clean.

**G3 (each M3).** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. **The ledger covers BF numbers as well as AD numbers** (`scripts/gen_ad_ledger.py` `_TOKEN_RE`, `(AD|BF)-(\d{1,5})`; the head of a PROGRESS entry or a DECISIONS heading is read, and so are commit subjects), so the **first regeneration after the contract commit** (whose subject names BF-933) moves BF-933: S1 M3's, in the shipped BF count, the accounted BF list (BF-933 added) and the unaccounted BF list (BF-933 removed); **S2 M3 moves no number** (the measured shape of the voice batch's A1, which this one mirrors). Every M3 also changes the report's git-log row (the pinned snapshot's time, head id and subject count) and shifts the two skipped-line numbers of PROGRESS.md by the 4 lines of its entry; the non-check run also rewrites `docs/development/ad-ledger-snapshot.json` (its git layer gains the subjects it had not seen). **I did not measure these diffs** (the voice batch changes the trackers before this batch builds, so a measurement now would be stale): the oracle measures them, and **any changed row of a number other than 933 is a hard stop**.

**Final gate (mine, once, after the Diff Reviewer's findings are repaired and the reviewed tree is committed locally; the broad gate stops on an untracked file under `ui/src/` and on a mutation backup file there, `scripts/run_test_gate.py:33-41`, `:69`, `:716-735`, `:795-804`: every new file is committed first, and the mutation campaign restores each file and removes any `.mutbak`, `.mut_bak` or `.mut.bak`):** `npm run build` (from `ui/`; `tsc -b && vite build`: clean), the whole `npx vitest run` once on the oracle (CI runs it again), the mutation rows of section 9, and `PY scripts/run_test_gate.py --label bf933 --receipt logs/gates/bf933.receipt.json` from the repository root (its preflight runs the ledger, architecture, seam and store checks; **it does not run the UI tests or the UI build**; no config or Python file changes). **Harness rule.** No source change made to pass a test, no skip, no loosened assertion; a failing new case at G2, or any existing test failing, goes back to the Architect.

## 5. Commit messages

- **S1 M1:** `BF-933 S1 M1: tests for the camera capture loop surviving overlapping starts, a stop during a start, a 429 and a slow upload, xfail until built (#1671)`
- **S1 M2:** `BF-933 S1 M2: concurrent camera starts share one pending start, a stop cancels it, and ticks skip while an upload is in flight or a 429 pause runs (#1671)`
- **S1 M3:** `BF-933 S1 M3: trackers and ledger (#1671)`; its body ends with the line `Refs #1671.`
- **S2 M1:** `BF-933 S2 M1: tests pinning that a typed-disabled skill-request queue is read once, logs nothing and is left alone (#1671)`
- **S2 M3:** `BF-933 S2 M3: trackers and ledger (#1671)`; its body ends with the line `Refs #1671.`

No slice is the last of its issue (the freeze and the dedupe stay open), so none carries `Closes`; see D1 for the one-line change if the orchestrator closes the issue with a follow-up. The pull request body lists the checklist of D1 and the four live actions of the last section as post-merge actions. No message names a crew member, a thread or a live figure.

## 6. Tests

**S1 (`ui/src/hooks/__tests__/useCameraStream.bf933.test.ts`, new; 19 cases).** The module is imported as the existing suite imports it (`startCameraStream`, `stopCameraStream`, `getCameraStream`, `_testReset`: all exist on the base, so the file loads before M2). Time is controlled by vitest's fake timers with the system time fixed (`vi.useFakeTimers()`, `vi.setSystemTime(...)`; the hook reads `Date.now()` and `window.setInterval`/`window.setTimeout`); each case advances time with `vi.advanceTimersByTimeAsync`. **Every case restores** (in `afterEach`): `_testReset()`, `vi.useRealTimers()`, `vi.restoreAllMocks()` (the `document.createElement`, `document.visibilityState`, `fetch` and `setInterval` spies), and `delete navigator.mediaDevices`; the store is reset in `beforeEach`. `built` is `it.fails` unless `BF933_RUNXFAIL=1`.

| Case | Kind | Asserts |
|---|---|---|
| T1 two overlapping starts share one camera and one capture interval, and one stop leaves none | built | `getUserMedia` called once, `window.setInterval` called once, one pending timer after the starts, `active`, then after `stopCameraStream()` no timer, every stream released, `getCameraStream()` null |
| T3 a stop while the camera is opening releases the camera and starts no loop | built | the stream the camera grants after the stop is released; no timer; `active` false; `getCameraStream()` null |
| T3b a stop while the video is starting leaves no loop | built | no timer after `play()` settles; `active` false |
| T4 a start after a stop, while the first start is pending, runs one loop and the first stream is released | built | two `getUserMedia` calls; the first stream released, the second not; one timer; `active`; then a stop releases it |
| T5 a cancelled start that then fails reports nothing and leaves the newer start alone | built | `error` stays null, `active` stays true |
| T6 ticks during a pending upload send nothing, and the first tick after it settles sends again | built | `fetch` called 1, 1, 2 times |
| T6b an upload that settles after a stop and a restart does not release the new loop's guard | built | `fetch` called 2 times at the end |
| T7 an upload that never answers is aborted, and the loop sends again | built | the abort signal fires; `fetch` called 2 times by the second tick after the abort |
| T8 a 429 with `Retry-After: 3` pauses the uploads for that long | built | 1, 1, 2 calls at 1 s, 3 s, 4 s |
| T9 without a usable `Retry-After` the pause doubles from one second, and a 200 starts it over | built | 1, 2, 2, 3, 4, 5 calls at the six ticks |
| T10 a long `Retry-After` is capped | built | 1 call at 30 s, 2 at 31 s (`Retry-After: 3600`) |
| T11 an HTTP-date `Retry-After` is honoured | built | 1 call at 4 s, 2 at 5 s |
| C1 a single start opens one camera and one loop, and a stop releases both | control | one call, one timer, `active`; then released, no timer |
| C2 a start after the camera is running changes nothing | control | still one call, one timer |
| C3 a 200 counts a frame, the form carries the session id, and a stop leaves no timer behind | control | `framesSent` 1; the posted form's `session_id` equals the store's; no timer after the stop (kills a lost `clearTimeout`) |
| C4 a 503 stops the camera, as before | control | `active` false, stream released, no timer (the message is not asserted: `stopCameraStream()` resets the store's `error`, L6) |
| C5 a 413 and a network error drop one frame and keep the loop alive | control | three calls over three ticks; `framesSent` 1; `active`; one timer |
| C6 a failed camera open reports the error and a later start can succeed | control | `error` matches `getUserMedia failed`; the second start is `active` with one timer |
| C7 a stop clears the pause and the doubling | control | after two 429s and a stop and a restart, the next two ticks send (calls 3 and 4) |

**Tests that pin the old behaviour (decision 4 of the request), by command** (section 11 holds the commands and the output): (a) `ui/src/hooks/__tests__/useCameraStream.test.ts` (3 cases): none pins a defect; all three hold on the new code (`getUserMedia` once and `active`; every track stopped; a rejection surfaces `getUserMedia failed`). (b) The ten test files that mock the hook replace the module, so nothing inside it reaches them. (c) The one source pin of a call is `ProfileChatTab.threadTranscript.test.tsx:605`, `expect(profileChatSource).toMatch(/if \(video\) void startCameraStream\(\)/)`: it pins the call text, not a defect, and this batch leaves `ProfileChatTab.tsx` unedited, so it stays true as it is. (d) The seven `?raw` readers of `ProfileChatTab.tsx` are untouched for the same reason; **no `?raw` reader exists for `useCameraStream.ts`, `MeetingView.tsx`, `PerceptionLivePanel.tsx`, `SkillRequestPanel.tsx`, `useStore.ts`, `resourceState.ts` or `approvalPolling.ts`** (Absence Verified). (e) The existing skill-queue suites pin the right behaviour (section 1, S2) and none pins a defect. **Nothing needs updating.**

**S2 (`ui/src/store/__tests__/approvalPolling.bf933.test.ts`, new; 4 cases, all `it`).** The harness is the existing `approvalPolling.test.ts`'s (fake timers; `acquireApprovalPolling`; the `useStore` approval slices reset in `beforeEach` from `useStore.getInitialState()`; `vi.stubGlobal('fetch', ...)`; every lease released in `afterEach`), without its three `vi.mock` lines (they serve its `main.tsx` cases; eight other store suites import `../useStore` with no mock). **Every case restores**: leases released, `vi.useRealTimers()`, `vi.restoreAllMocks()` (the `console.warn` spy), `vi.unstubAllGlobals()`; the store slices are reset before each case, so no field outlives a case.

| Case | Asserts |
|---|---|
| S2-T1 a typed-disabled skill read happens once, logs nothing, and the capability queue keeps its cadence | skill calls 1 over 60 s; capability calls > 1; `approvalResources.skill.status` `disabled`; `approvalPoll.skill.nextAt` null; `console.warn` never called |
| S2-T2 a plain 503 is bounded to three reads, and each warning names the skill queue | skill calls 3 over 120 s; status `unavailable`; `failures` 3; `warn` called 3 times; the first message contains `Approval skill queue read failed` |
| S2-T3 an enabled skill queue is read every ten seconds and logs nothing | 4 calls by 30 s; status `ready`; no warning |
| S2-T4 a re-acquired lease asks a typed-disabled queue once more, and still logs nothing | 1 call, then after release and re-acquire 2; no warning |

## 7. The contract

Labels restart in each slice. Section 6 names the cases; this section gives every block. `PY`, the commands and who runs them are in section 4. SEARCH text is LF; the working copies are CRLF (the apply tool matches on LF). Every SEARCH below occurs exactly once in its file on `f614a31d`, starts at a line start, and is ASCII (section 11: run on the LF blobs); no block's SEARCH overlaps another's; **a block's REPLACE changes the line count of a later block's position but not its text**, so the blocks of one file are applied in label order and none re-measures a line number.

### 7.1 Slice S1 (BF-933 slice 1: the camera capture loop)

#### S1 M1

**N1-1.** New file `ui/src/hooks/__tests__/useCameraStream.bf933.test.ts`:

```ts
/** BF-933 (#1671): the camera capture loop under overlapping starts, a stop during a start, a 429 and a slow upload.
 *
 * The defect: `startCameraStream` returned early only when `_stream` was set, and `_stream` is assigned after the
 * `getUserMedia` await, so two overlapping calls both passed, each opened a camera and each created a
 * `setInterval`; the second overwrote the module's one interval id, so the first loop could never be stopped.
 * A stop that arrived while the camera was opening found nothing to stop, and the start then ran. A 429 was dropped
 * and retried on the next tick (its `Retry-After` was never read), and nothing kept a tick from starting a capture
 * while the previous upload was still in flight.
 *
 * The fixtures are synthetic: a fake camera whose `getUserMedia` the test settles by hand, a fake `<video>` and
 * `<canvas>`, a stubbed `fetch` that answers with the statuses the server uses, and a `Retry-After` of a few
 * seconds. They carry no console output, count or timing from the live call that found the defect: this repository
 * is public and its tests hold no vessel data.
 *
 * The cases the unfixed hook fails are `built`, which is `it.fails` until BF-933 S1 M2 sets it to `it`; with
 * BF933_RUNXFAIL=1 they run as ordinary cases, so each can be seen to stop at its own assertion. Time is vitest's
 * fake clock with the system time fixed: the hook reads `Date.now()` and `window.setInterval`/`window.setTimeout`.
 * Every case restores the module (`_testReset`), the timers, the spies and `navigator.mediaDevices`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  getCameraStream,
  startCameraStream,
  stopCameraStream,
  _testReset,
} from '../useCameraStream';
import { useCameraStore } from '../../store/useCameraStore';

const built = process.env.BF933_RUNXFAIL === '1' ? it : it.fails;

class FakeTrack {
  stopped = false;
  stop() { this.stopped = true; }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack()];
  getTracks() { return this.tracks; }
  get released() { return this.tracks.every((t) => t.stopped); }
}

/** A camera the test opens by hand: each getUserMedia call stays pending until the test settles it. */
function installCamera() {
  const streams: FakeMediaStream[] = [];
  const open: Array<() => void> = [];
  const fail: Array<(error: Error) => void> = [];
  const getUserMedia = vi.fn(
    () =>
      new Promise<MediaStream>((resolve, reject) => {
        const stream = new FakeMediaStream();
        streams.push(stream);
        open.push(() => resolve(stream as unknown as MediaStream));
        fail.push(reject);
      }),
  );
  Object.defineProperty(global.navigator, 'mediaDevices', {
    value: { getUserMedia },
    configurable: true,
    writable: true,
  });
  return { getUserMedia, streams, open, fail };
}

/** A fake <video> that is ready (non-zero size) and a fake <canvas> whose encoder answers at once. */
function installElements(options: { play?: () => Promise<void> } = {}) {
  const real = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string, init?: ElementCreationOptions) => {
    if (tag === 'video') {
      return {
        videoWidth: 640,
        videoHeight: 480,
        autoplay: false,
        playsInline: false,
        muted: false,
        srcObject: null,
        play: options.play ?? (async () => undefined),
      } as unknown as HTMLVideoElement;
    }
    if (tag === 'canvas') {
      return {
        width: 0,
        height: 0,
        getContext: () => ({ drawImage: () => undefined }),
        toBlob: (done: BlobCallback) => done(new Blob(['frame'], { type: 'image/jpeg' })),
      } as unknown as HTMLCanvasElement;
    }
    return real(tag, init);
  }) as typeof document.createElement);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
}

const ok = (): Response => new Response('{}', { status: 200 });
const limited = (retryAfter?: string): Response =>
  new Response('{"error":"rate_limited"}', {
    status: 429,
    headers: retryAfter === undefined ? {} : { 'Retry-After': retryAfter },
  });

/** A fetch whose n-th call answers script[n] (the last entry repeats). */
function installFetch(script: Array<() => Response>) {
  let calls = 0;
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () => script[Math.min(calls++, script.length - 1)](),
  );
}

/** A fetch that never answers on its own: each call waits for the test to release it. */
function installHeldFetch() {
  const release: Array<() => void> = [];
  const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
    () => new Promise<Response>((resolve) => { release.push(() => resolve(ok())); }),
  );
  return { send, release };
}

async function startRunning(camera: ReturnType<typeof installCamera>, index = 0): Promise<void> {
  const started = startCameraStream({ fps: 1 });
  camera.open[index]();
  await started;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2030-01-01T00:00:00.000Z'));
  useCameraStore.setState({ active: false, sessionId: null, error: null, framesSent: 0, fps: 1 });
});

afterEach(() => {
  _testReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
});

describe('BF-933: overlapping starts leak no capture loop', () => {
  built('two overlapping starts share one camera and one capture interval, and one stop leaves none', async () => {
    const camera = installCamera();
    installElements();
    const intervals = vi.spyOn(window, 'setInterval');
    const first = startCameraStream({ fps: 1 });
    const second = startCameraStream({ fps: 1 });
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1);
    camera.open[0]();
    await Promise.all([first, second]);
    expect(intervals).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    await stopCameraStream();
    expect(vi.getTimerCount()).toBe(0);
    expect(camera.streams.every((s) => s.released)).toBe(true);
    expect(getCameraStream()).toBeNull();
  });

  built('a stop while the camera is opening releases the camera and starts no loop', async () => {
    const camera = installCamera();
    installElements();
    const pending = startCameraStream({ fps: 1 });
    await stopCameraStream();
    camera.open[0]();
    await pending;
    expect(camera.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useCameraStore.getState().active).toBe(false);
    expect(getCameraStream()).toBeNull();
  });

  built('a stop while the video is starting leaves no loop', async () => {
    const camera = installCamera();
    let finishPlay!: () => void;
    installElements({ play: () => new Promise<void>((resolve) => { finishPlay = resolve; }) });
    const pending = startCameraStream({ fps: 1 });
    camera.open[0]();
    await vi.advanceTimersByTimeAsync(0);
    await stopCameraStream();
    finishPlay();
    await pending;
    expect(vi.getTimerCount()).toBe(0);
    expect(useCameraStore.getState().active).toBe(false);
    expect(camera.streams[0].released).toBe(true);
  });

  built('a start after a stop, while the first start is pending, runs one loop and the first stream is released', async () => {
    const camera = installCamera();
    installElements();
    const first = startCameraStream({ fps: 1 });
    await stopCameraStream();
    const second = startCameraStream({ fps: 1 });
    expect(camera.getUserMedia).toHaveBeenCalledTimes(2);
    camera.open[0]();
    camera.open[1]();
    await Promise.all([first, second]);
    expect(camera.streams[0].released).toBe(true);
    expect(camera.streams[1].released).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    await stopCameraStream();
    expect(camera.streams[1].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  built('a cancelled start that then fails reports nothing and leaves the newer start alone', async () => {
    const camera = installCamera();
    installElements();
    const first = startCameraStream({ fps: 1 });
    await stopCameraStream();
    const second = startCameraStream({ fps: 1 });
    camera.open[1]();
    await second;
    camera.fail[0](new Error('NotAllowedError'));
    await first;
    expect(useCameraStore.getState().error).toBeNull();
    expect(useCameraStore.getState().active).toBe(true);
  });
});

describe('BF-933: a tick does not start a capture while the previous upload is in flight', () => {
  built('ticks during a pending upload send nothing, and the first tick after it settles sends again', async () => {
    const camera = installCamera();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(1);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('an upload that settles after a stop and a restart does not release the new loop\'s guard', async () => {
    const camera = installCamera();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(camera, 0);
    await vi.advanceTimersByTimeAsync(1000);
    await stopCameraStream();
    await startRunning(camera, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('an upload that never answers is aborted, and the loop sends again', async () => {
    const camera = installCamera();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe('BF-933: a 429 is honoured', () => {
  built('a 429 with Retry-After: 3 pauses the uploads for that long, then they resume', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited('3'), ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('without a usable Retry-After the pause doubles from one second, and a 200 starts it over', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited(), () => limited('soon'), ok, () => limited(), ok]);
    await startRunning(camera);
    const calls: number[] = [];
    for (let second = 1; second <= 6; second += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      calls.push(send.mock.calls.length);
    }
    expect(calls).toEqual([1, 2, 2, 3, 4, 5]);
  });

  built('a long Retry-After is capped at thirty seconds', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited('3600'), ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(29_000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('an HTTP-date Retry-After is honoured', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited(new Date('2030-01-01T00:00:05.000Z').toUTCString()), ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe('BF-933: what must not change', () => {
  it('a single start opens one camera and one capture loop, and a stop releases both', async () => {
    const camera = installCamera();
    installElements();
    await startRunning(camera);
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    await stopCameraStream();
    expect(camera.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useCameraStore.getState().active).toBe(false);
  });

  it('a start after the camera is running changes nothing', async () => {
    const camera = installCamera();
    installElements();
    await startRunning(camera);
    await startCameraStream({ fps: 1 });
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('a 200 counts a frame, the form carries the session id, and a stop leaves no timer behind', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(useCameraStore.getState().framesSent).toBe(1);
    const form = send.mock.calls[0][1]?.body as FormData;
    expect(form.get('session_id')).toBe(useCameraStore.getState().sessionId);
    await stopCameraStream();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('a 503 from the server stops the camera, as before', async () => {
    const camera = installCamera();
    installElements();
    installFetch([() => new Response('{"error":"camera_disabled"}', { status: 503 })]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(useCameraStore.getState().active).toBe(false);
    expect(camera.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('a 413 and a network error drop one frame each and keep the loop alive', async () => {
    const camera = installCamera();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(async () => new Response('{}', { status: 413 }))
      .mockImplementationOnce(async () => { throw new TypeError('network'); })
      .mockImplementation(async () => ok());
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(useCameraStore.getState().framesSent).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('a failed camera open reports the error, and a later start can succeed', async () => {
    const camera = installCamera();
    installElements();
    const first = startCameraStream({ fps: 1 });
    camera.fail[0](new Error('NotAllowedError'));
    await first;
    expect(useCameraStore.getState().error).toMatch(/getUserMedia failed/);
    expect(useCameraStore.getState().active).toBe(false);
    await startRunning(camera, 1);
    expect(useCameraStore.getState().active).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('a stop clears the pause and the doubling, so the next call starts clean', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited(), () => limited(), () => limited(), ok]);
    await startRunning(camera, 0);
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(2);
    await stopCameraStream();
    await startRunning(camera, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(4);
  });
});
```

#### S1 M2

**P2-1.** `ui/src/hooks/useCameraStream.ts`. The header comment's 429 line (once; ASCII).
SEARCH:
```
 *   - 429 from server: pass-through (token bucket throttles naturally).
```
REPLACE:
```
 *   - 429 from server: honour Retry-After, else back off 1 s, 2 s, 4 s ... up to 30 s;
 *     ticks inside the pause return without capturing (BF-933).
 *   - a start that overlaps a pending start shares it; a stop cancels a pending start (BF-933).
```

**P2-2.** `ui/src/hooks/useCameraStream.ts`. The module state (once; the line is the anchor; ASCII).
SEARCH:
```
let _activeDeviceId: string | null = null;
```
REPLACE:
```
let _activeDeviceId: string | null = null;
// BF-933: the loop's guards. A start is one shared promise; every stop bumps the epoch, which is how a start that
// is still waiting on the camera or the video learns it was cancelled; an upload in flight holds the next tick
// off; a 429 holds it off until _resumeAtMs.
const FRAME_UPLOAD_TIMEOUT_MS = 10_000;
const BACKOFF_BASE_MS = 1_000;
const RETRY_AFTER_MAX_MS = 30_000;
let _startInFlight: Promise<void> | null = null;
let _epoch = 0;
let _uploading = false;
let _resumeAtMs = 0;
let _rateLimited = 0;
```

**P2-3.** `ui/src/hooks/useCameraStream.ts`. The end of `_stopTracks` (once: `_streams.clear()` occurs once; ASCII).
SEARCH:
```
  _streams.clear();
}
```
REPLACE:
```
  _streams.clear();
  // BF-933: every stop is also a cancel. A start still waiting on the camera sees a new epoch and releases what it
  // was given; a call after a stop is not held to the cancelled start; the old call's upload guard and 429 pause
  // do not outlive it. _testReset goes through here, so a test resets all of it.
  _epoch += 1;
  _startInFlight = null;
  _uploading = false;
  _resumeAtMs = 0;
  _rateLimited = 0;
}
```

**P2-4.** `ui/src/hooks/useCameraStream.ts`. The head of `_captureAndUpload` (once; ASCII). The old function becomes `_captureAndUploadFrame`; the interval callback (`void _captureAndUpload();`) is unchanged.
SEARCH:
```
async function _captureAndUpload() {
  if (!_video || !_canvas || !_sessionId) return;
```
REPLACE:
```
/** BF-933: RFC 9110 Retry-After is delta-seconds or an HTTP-date; anything else is no advice. */
function _parseRetryAfterMs(raw: string | null): number | null {
  if (raw === null) return null;
  const value = raw.trim();
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : Math.max(0, at - Date.now());
}

/** BF-933: one capture-and-upload at a time. A tick that finds the previous upload still in flight, or the loop
 *  paused by a 429, returns at once. The flag belongs to the epoch that set it: an upload that settles after a
 *  stop (and perhaps a new start) does not release a newer loop's guard. */
async function _captureAndUpload() {
  if (_uploading || Date.now() < _resumeAtMs) return;
  const epoch = _epoch;
  _uploading = true;
  try {
    await _captureAndUploadFrame();
  } finally {
    if (epoch === _epoch) _uploading = false;
  }
}

async function _captureAndUploadFrame() {
  if (!_video || !_canvas || !_sessionId) return;
```

**P2-5.** `ui/src/hooks/useCameraStream.ts`. The upload call (once; ASCII). The request gets a signal and a timer that the inner `finally` always clears; the outer `try`/`catch` is untouched.
SEARCH:
```
  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form });
    if (resp.status === 503) {
```
REPLACE:
```
  // BF-933: bound the upload, so a request that never answers cannot hold the in-flight guard for good.
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), FRAME_UPLOAD_TIMEOUT_MS);
  try {
    let resp: Response;
    try {
      resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form, signal: controller.signal });
    } finally {
      window.clearTimeout(timeout);
    }
    if (resp.status === 503) {
```

**P2-6.** `ui/src/hooks/useCameraStream.ts`. The 200 and 429/413 handling (once; ASCII).
SEARCH:
```
    if (resp.status === 200) {
      useCameraStore.getState().incrementFramesSent();
    }
    // 429 / 413: drop the frame, the next interval tick tries again.
```
REPLACE:
```
    if (resp.status === 200) {
      useCameraStore.getState().incrementFramesSent();
      _rateLimited = 0; // a 200 ends the doubling
    }
    if (resp.status === 429) {
      // BF-933: the server's token bucket said slow down. Honour Retry-After; without a usable one back off
      // 1 s, 2 s, 4 s ... The interval keeps its period; ticks inside the pause return without capturing.
      _rateLimited += 1;
      const advised = _parseRetryAfterMs(resp.headers.get('Retry-After'));
      const waitMs = advised ?? BACKOFF_BASE_MS * 2 ** (_rateLimited - 1);
      _resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);
    }
    // 413: drop the frame, the next interval tick tries again.
```

**P2-7.** `ui/src/hooks/useCameraStream.ts`. The end of `startCameraStream`'s signature and its guard (once; ASCII). The old body becomes `_startCamera`; the closing brace of the old function closes it. `Parameters<typeof startCameraStream>[0]` keeps the one options type in one place.
SEARCH:
```
}): Promise<void> {
  if (_stream) return; // idempotent
  _fps = opts?.fps ?? 1;
```
REPLACE:
```
}): Promise<void> {
  // BF-933: concurrent callers share the one pending start (the guard below only sees a camera that has already
  // been granted); a call after a stop starts afresh, because the stop dropped the pending start.
  if (_startInFlight) return _startInFlight;
  if (_stream) return; // idempotent
  const attempt: Promise<void> = _startCamera(opts).finally(() => {
    if (_startInFlight === attempt) _startInFlight = null;
  });
  _startInFlight = attempt;
  return attempt;
}

async function _startCamera(opts: Parameters<typeof startCameraStream>[0]): Promise<void> {
  const epoch = _epoch;
  _fps = opts?.fps ?? 1;
```

**P2-8a.** `ui/src/hooks/useCameraStream.ts`. The local that receives the granted stream (once; ASCII).
SEARCH:
```
  try {
    const videoConstraints: MediaTrackConstraints = {
```
REPLACE:
```
  let stream: MediaStream;
  try {
    const videoConstraints: MediaTrackConstraints = {
```

**P2-8b.** `ui/src/hooks/useCameraStream.ts`. The camera call, its failure and the epoch check (once; ASCII).
SEARCH:
```
    _stream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraints,
      audio: false,
    });
  } catch (err) {
    useCameraStore.getState().setError(`getUserMedia failed: ${String(err)}`);
    _activeDeviceId = null;
    return;
  }
```
REPLACE:
```
    stream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraints,
      audio: false,
    });
  } catch (err) {
    // BF-933: a start that a stop has cancelled reports nothing and touches nothing of a newer start.
    if (epoch === _epoch) {
      useCameraStore.getState().setError(`getUserMedia failed: ${String(err)}`);
      _activeDeviceId = null;
    }
    return;
  }
  if (epoch !== _epoch) {
    // BF-933: a stop arrived while the camera was being opened; release what was granted and start no loop.
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  _stream = stream;
```

**P2-8c.** `ui/src/hooks/useCameraStream.ts`. After `play()` (once; ASCII).
SEARCH:
```
  _canvas = document.createElement('canvas');

  useCameraStore.getState().setActive(true, _sessionId);
```
REPLACE:
```
  // BF-933: a stop that arrived during play() has already released the stream; do not start a loop.
  if (epoch !== _epoch) return;
  _canvas = document.createElement('canvas');

  useCameraStore.getState().setActive(true, _sessionId);
```

**N2-1.** `ui/src/hooks/__tests__/useCameraStream.bf933.test.ts`. The marker, removed: every `built` is now `it`.
SEARCH:
```
const built = process.env.BF933_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once on `f614a31d`; the voice batch's entries follow it after their merge and the SEARCH is unchanged by them). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-933 slice 1 (DATE), #1671 -- the camera capture loop no longer leaks under overlapping starts, honours a 429 and never overlaps its own uploads.**
- **Base.** `startCameraStream` (`ui/src/hooks/useCameraStream.ts`) returned early only once its camera call had stored the stream, so two overlapping calls each opened a camera and each created an interval; the second overwrote the module's one interval id and the first loop could never be stopped. A stop that arrived while the camera was opening found nothing to stop, and the start then ran. A 429 was dropped and retried on the next tick with its `Retry-After` unread, and a tick could start a capture while the previous upload was still in flight.
- **Fix.** Concurrent callers share one pending start; every stop bumps an epoch, so a start still waiting on the camera or the video releases what it was given and starts no loop, and a call after a stop is not held to the cancelled start. A tick returns at once while an upload is in flight (the upload is aborted after 10 s so the guard cannot stick) or while a 429 pause runs: the `Retry-After` of the response (seconds or an HTTP date), else 1 s, 2 s, 4 s up to 30 s; a 200 and a stop start the doubling over. No export is added and no caller changes. The tests use synthetic fixtures only. Not changed: the capture primitive, so the 5 s main-thread stall of the issue, which needs a profile of a live call, and the Three.js copies. Contract `prompts/bf-933-camera-loop-and-skill-request-poll.md`, slice S1. Refs #1671.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows the BF entries (once on `f614a31d`, at line 1710; BF-937's entries sit before it, the voice batch's will be inserted before it, and each entry of this batch is inserted before it as well, so the order is the order of landing). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-933 slice 1 -- The camera capture loop shares one pending start, a stop cancels it, and ticks skip while an upload is in flight or a 429 pause runs (DATE, #1671)

- *Scope.* `ui/src/hooks/useCameraStream.ts` (module-private state and functions; no export added, so no mock factory of the ten test files that mock the module changes), one new test file. Contract `prompts/bf-933-camera-loop-and-skill-request-poll.md`.
- *G1 (the guard).* One shared promise plus an epoch that every stop bumps, and a stop also drops the pending start. Rejected: a boolean lock (the second caller returns before the camera exists, and a stop during a start is still lost); a guard in each caller (three callers today, and the hook is the idempotent unit); a session object (a refactor the defect does not need).
- *G2 (the 429).* Skip ticks until the `Retry-After` deadline, else 1 s, 2 s, 4 s to a 30 s cap; the interval keeps its period; a 200 and a stop reset. Rejected: stopping the camera after N 429s (a visible behaviour change); lowering the frame rate (more state for the same effect).
- *G3 (the upload).* One at a time, aborted after 10 s so a request that never answers cannot hold the guard. Rejected: a skip with no timeout. The capture primitive is unchanged and no offload is claimed: no test can show that one removes a stall that is not identified.
- *G4 (the fixtures).* Synthetic: a fake camera settled by hand, fake elements, a stubbed fetch, a `Retry-After` of a few seconds; no console line, count or timing from the live call is in any test, comment, tracker line or commit message; this overrides the acceptance lines that asked for live observations as evidence.
- *Residual.* L1 to L10 of the contract (S1). *Reversal.* Revert the BF-933 slice 1 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.2 Slice S2 (BF-933 slice 2: the skill-request queue, pinned)

#### S2 M1

**N1-1.** New file `ui/src/store/__tests__/approvalPolling.bf933.test.ts`:

```ts
/** BF-933 (#1671): a skill-request queue whose store is disabled is read once and then left alone, quietly.
 *
 * The issue behind this file reported a skill-requests endpoint that answers 503 by design when its store is
 * disabled, read again and again with a console line each time. The tree already stops on a typed-disabled answer
 * (`nextResourcePoll`, `refreshPendingApprovals`) and the existing suites pin the request count
 * (SkillRequestPanel.test.tsx, ApprovalsInBridge.test.tsx). What no case pinned was the console (a typed-disabled
 * read logs nothing), that a plain 503 is bounded and names the queue that failed, and that a re-acquired lease
 * asks once more. These cases are characterization: they pass on the base, and a change that warned for a disabled
 * queue, kept reading it, or stopped reading an enabled one would fail them.
 *
 * The 503 body has the shape the route sends for a disabled store (detail plus availability with state, code,
 * message and retryable); the one request row is invented. No console line, count or timing from the vessel that
 * found the issue is here: this repository is public and its tests hold no vessel data.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { acquireApprovalPolling } from '../approvalPolling';
import { useStore } from '../useStore';
import type { ApprovalQueue } from '../types';

const DISABLED_BODY = {
  detail: 'skill request store not available',
  availability: {
    state: 'disabled',
    code: 'skill_requests.disabled',
    message: 'Disabled. Review configuration with the operator.',
    retryable: false,
  },
};
const PLAIN_503_BODY = { detail: 'skill request store not available' };
const ONE_REQUEST = {
  requests: [
    {
      id: 'sr-1',
      agent_id: 'agent-1',
      skill_id: 'summarization',
      skill_label: 'Summarization',
      source: 'self',
      justification: 'condense long reports',
      status: 'requested',
      linked_simulation_id: null,
      created_at: 1.0,
      decided_at: null,
      decided_by: '',
      decision_reason: '',
      pre_metric: null,
      post_metric: null,
    },
  ],
};

const releases: Array<() => void> = [];
function acquire(queues: readonly ApprovalQueue[]): () => void {
  const release = acquireApprovalPolling(queues);
  releases.push(release);
  return release;
}
function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status });
}
/** A fetch that answers the skill queue with `skill()` and the capability queue with an empty actionable list. */
function transport(skill: () => Response): { skill: number; capability: number } {
  const calls = { skill: 0, capability: 0 };
  vi.stubGlobal('fetch', vi.fn<typeof fetch>(async input => {
    if (String(input).startsWith('/api/skill-requests')) {
      calls.skill += 1;
      return skill();
    }
    calls.capability += 1;
    return json({ view: 'actionable', requests: [] }, 200);
  }));
  return calls;
}

beforeEach(() => {
  vi.useFakeTimers();
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources, approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null }, approvalIssuedSeq: { capability: 0, skill: 0 },
    approvalAppliedSeq: { capability: 0, skill: 0 }, approvalRequestSeq: 0,
    pendingApprovals: [], decidedApprovals: new Set(), capabilityDecidingIds: new Set(),
    capabilityDecisionFeedback: new Map(), capabilityDecisionRevision: 0, capabilityApprovalEpoch: 0, liveRepairEpoch: 0,
  });
});
afterEach(async () => {
  for (const release of releases.splice(0)) release();
  await vi.advanceTimersByTimeAsync(0);
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('BF-933: the skill-request queue under a disabled store', () => {
  it('reads a typed-disabled skill queue once, logs nothing, and leaves the capability cadence alone', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(DISABLED_BODY, 503));
    acquire(['capability', 'skill']);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.skill).toBe(1);
    expect(calls.capability).toBeGreaterThan(1);
    expect(useStore.getState().approvalResources.skill.status).toBe('disabled');
    expect(useStore.getState().approvalPoll.skill.nextAt).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it('bounds a plain 503 to three reads, and each warning names the skill queue', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(PLAIN_503_BODY, 503));
    acquire(['skill']);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls.skill).toBe(3);
    expect(useStore.getState().approvalResources.skill.status).toBe('unavailable');
    expect(useStore.getState().approvalPoll.skill.failures).toBe(3);
    expect(warn).toHaveBeenCalledTimes(3);
    expect(String(warn.mock.calls[0][0])).toContain('Approval skill queue read failed');
  });

  it('reads an enabled skill queue every ten seconds and logs nothing', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(ONE_REQUEST, 200));
    acquire(['skill']);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(calls.skill).toBe(4);
    expect(useStore.getState().approvalResources.skill.status).toBe('ready');
    expect(warn).not.toHaveBeenCalled();
  });

  it('asks a typed-disabled queue once more when a lease is re-acquired, and still logs nothing', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(DISABLED_BODY, 503));
    const release = acquire(['skill']);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.skill).toBe(1);
    release();
    acquire(['skill']);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.skill).toBe(2);
    expect(warn).not.toHaveBeenCalled();
  });
});
```

#### S2 M2

None. The slice edits no source: the acceptance is met on the base (section 1). A failing case at G1 is a finding, not a build step: it goes back to the Architect.

#### S2 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once; S1's entry follows it after S1 M3 and this entry is inserted above it). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-933 slice 2 (DATE), #1671 -- a skill-request queue whose store is disabled is read once, logs nothing and is left alone (pinned).**
- **Base.** The issue reported the HXI reading `/api/skill-requests?status=pending` after the route answered 503 for a disabled store. The tree already stops on a typed-disabled answer: `nextResourcePoll` returns no next read for `disabled`, `refreshPendingApprovals` warns only for `unavailable` and `failed` and names the failing queue, and the existing suites pin the request count for the shared queue and for the standalone panel. What no case pinned was the console.
- **Fix.** No source change. One new test file (`ui/src/store/__tests__/approvalPolling.bf933.test.ts`, 4 cases, all passing on the base) pins: a typed-disabled skill read happens once, leaves the queue unread while the capability queue keeps its cadence, and logs nothing; a plain 503 is read three times and each warning names the skill queue; an enabled queue is read every ten seconds without a warning; a re-acquired lease asks a typed-disabled queue once more. Contract `prompts/bf-933-camera-loop-and-skill-request-poll.md`, slice S2. Refs #1671.

```

**P3-2.** `DECISIONS.md`. The anchor is the same heading as S1's P3-2 (once; S1's entry sits before it after S1 M3, so this entry lands after it). Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-933 slice 2 -- A typed-disabled skill-request queue is read once per lease and stays quiet: pinned, with no source change (DATE, #1671)

- *Scope.* One new test file under `ui/src/store/__tests__/`. No source, no config, no server file. Contract `prompts/bf-933-camera-loop-and-skill-request-poll.md`.
- *G1 (no change).* The acceptance (learn once from the typed body, stop reading, no repeated console errors, enabled unchanged) is already met on the base, so the slice pins what was unpinned. Rejected: a session-wide memo that skips the read after a typed-disabled answer (it contradicts the pinned rule that re-acquiring a lease refreshes a queue, and a disabled queue can be enabled by a restart the HXI outlives); reading the service-readiness integrations first (a second source of the same fact); warning for `disabled` too.
- *G2 (the premise).* The issue's console line names the capability queue; the store interpolates the failing queue's name, so that line cannot come from the skill queue.
- *Residual.* L1 to L4 of the contract (S2). *Reversal.* Delete the test file.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.3 The Three.js dedupe: the orchestrator's action (not a slice of this pull request)

**Why it is not a slice.** The Builder never runs `npm install`; the change moves the avatar's Three.js from r172 to r183, which no jsdom test sees; CI's `npm ci` validates the lockfile against `package.json`, so the two files must change together; and its acceptance (the warning gone, the graphs rendering) is a build count and the Captain's eyes. It is specified here so the orchestrator can run it on any tree after S1 and S2 merge. **Decision D7, row 1.** Run it on a scratch worktree with `ui/node_modules` (the main checkout's is the reference), never on the batch's branch.

**Step 0, the baseline (before any edit; from `ui/`).** `npm ls three --all` prints three versions: `three@0.172.0` (root, and under every R3F, drei, VRM and stdlib dependant), `three@0.183.2` under `3d-force-graph`, `three@0.170.0` under `stats-gl` (the versions of `package-lock.json:6047`, `:2820`, `:5933`). Then `npm run build`, and count the warning in the output: `(rg -o "Multiple instances of Three.js being imported" dist | Measure-Object).Count`. **Expected: 2** (the one prebuilt `dist` in the main checkout, an older build, holds it twice, both in `avatar-vendor-*.js`; a fresh build on `f614a31d` is the baseline of record).

**Step 1, the edit (the only hand edit; three blocks on `ui/package.json`, each SEARCH once, ASCII; the file's own line endings apply):**

SEARCH:
```
    "three": "^0.172.0",
```
REPLACE:
```
    "three": "^0.183.2",
```
SEARCH:
```
    "@types/three": "^0.172.0",
```
REPLACE (the orchestrator replaces `0.183.X` with the highest `0.183.x` that `npm view @types/three versions --json` lists; if none is listed, stop and report):
```
    "@types/three": "^0.183.X",
```
SEARCH:
```
    "vitest": "^4.1.0"
  }
}
```
REPLACE:
```
    "vitest": "^4.1.0"
  },
  "overrides": {
    "three": "$three"
  }
}
```
(`$three` is npm's reference to the root dependency's own spec: every other `three` edge, such as `stats-gl`'s `^0.170.0`, resolves to the root's copy. The other declared ranges already admit 0.183.2: `3d-force-graph` `>=0.179 <1`, `postprocessing` `>= 0.157.0 < 0.184.0`, every lower bound.)

**Step 2, the install (mine; from `ui/`).** `npm install`. Then `npm ls three --all`: **expected: exit code 0; every `three@` line shows `0.183.2`, each marked `deduped` (and `overridden` where the override replaced a range); no `invalid`, `UNMET` or `extraneous` line.** `npm ls three --all --json`: every `version` of every `three` node is `0.183.2`. Then `npm ci --dry-run`: **expected exit 0** (the check CI's `npm ci` makes: the lockfile is in sync with `package.json`).

**Step 3, the lockfile's expected change (`git diff --stat -- package.json package-lock.json`; read the hunks).** (a) `package.json`: the three edits above. (b) `package-lock.json`: the root entry's `three` and `@types/three` specs; `node_modules/three` becomes `0.183.2` with `integrity` `sha512-di3BsL2FEQ1PA7Hcvn4fyJOlxRRgFYBpMTcyOgkwJIaDOdJMebEFPA+t98EvjuljDx4hNulAGwF6KIjtwI5jgQ==` (the nested copy's, `package-lock.json:2824`); the entries `node_modules/3d-force-graph/node_modules/three` and `node_modules/stats-gl/node_modules/three` are removed; `node_modules/3d-force-graph/node_modules/three-render-objects` may move to `node_modules/three-render-objects` (its peer is now satisfied at the root); `node_modules/@types/three` changes version, integrity and possibly its small dependency list. **Any other package whose `version` line changes is a hard stop:** report it, do not commit.

**Step 4, the gates (mine).** `npx tsc -b` (the `@types/three` bump may surface type errors in `ui/src/canvas/`, `CrewVRM.tsx`, `ParametricAvatar.tsx`, `MemoryGraph3D.tsx`, `CognitiveCanvas.tsx`, `ShipLayoutView.tsx`: **a type error is a hard stop for the Architect**: no source is edited to fit a dependency), `npm run build`, the count of Step 0 again (**expected 1**), and the whole `npx vitest run`.

**Step 5, the Captain's eyes (a live action, not a test).** On a dev server or the built bundle: the crew avatar (mouth, skin, hair and eye shading, expressions), the three force-graph views (knowledge, records, memory graph), the ship layout and the cognitive canvas; the browser console shows no `Multiple instances of Three.js` line. The "stats overlay" of the issue is not used by app code (Absence Verified), so there is nothing to look at.

**Step 6, commit and rollback.** One commit, subject `BF-933 D1: one copy of Three.js, the app aligned up to the force graph's r183 with an override for the rest (#1671)`, body ends `Refs #1671.`; its tracker entries are drafted when it is decided. **Rollback:** `git revert` that commit (it restores both files), then `npm ci`. If Step 5 shows a regression, revert and record D7 row 4 (two copies, with the `Timer` evidence) as the decision.

## 8. What this does NOT change

**S1.** The capture primitive (`drawImage`, `toBlob`, the canvas size, the JPEG quality, `_maxDim`) and so the 5 s stall of the issue; `_computeAgentIds`, `forceNextFrame`, `getCameraStream` and the `_streams` map; the 503 branch (a 503 still stops the camera); the visibility pause; the exports of `useCameraStream.ts` (no export is added, so the ten `vi.mock` factories that mock the module, and the one that supplies only `stopCameraStream`, stay valid); every caller (`ProfileChatTab.tsx` and its `?raw` pin at `ProfileChatTab.threadTranscript.test.tsx:605`, `MeetingView.tsx`, `PerceptionLivePanel.tsx`, `CameraPreviewPanel.tsx`, `CameraLiveIndicator.tsx`, `App.tsx`, `CompactApp.tsx`); `useCameraStore.ts` (including `reset()` clearing `error`, L6); `useScreenStream.ts` (L7); `routers/perception.py` and every server file (the 429 and its `Retry-After: 1`, the bucket, `camera_max_fps_server`); the existing `useCameraStream.test.ts`.

**S2.** Every source file: `useStore.ts` (`refreshPendingApprovals`, the warning), `resourceState.ts`, `approvalPolling.ts`, `SkillRequestPanel.tsx`, `routers/skill_requests.py`, `routers/readiness.py`, `config/`.

**All.** `ui/package.json`, `ui/package-lock.json` and `ui/vite.config.ts` (section 7.3 is outside this pull request), `ProfileChatTab.tsx` and every file the voice batch edits, every Python file, `config/system.yaml` and every config model, the attachment store. OSS only; no dependency; no schema change.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

**Not run by the Architect** (a read-only consult cannot run vitest); every Line below was checked to occur exactly once, stripped, in the patched hook (the ten S1 blocks applied to the LF blob in memory) and, for S2, in the unedited base file (section 11). The orchestrator's oracle runs the campaign: each row's line replaced whole in the built file, the slice's new test file run with vitest's JSON reporter, the file restored and its blob checked. **This table is the campaign of record only for a tree whose `useCameraStream.ts` equals the blob the ten blocks give on `f614a31d`** (sha256 to be recorded by the oracle); a Builder whose files match does not repeat it, and if a file differs the rows that name it are rerun. The Killed-by cells are the cases I expect to fail; the oracle reports supersets and corrects the cells. Case labels are section 6's.

**S1 (file `ui/src/hooks/useCameraStream.ts`).**

| # | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|
| 1 | `if (_startInFlight) return _startInFlight;` | the line deleted | T1 |
| 2 | `_startInFlight = attempt;` | the line deleted | T1 |
| 3 | `if (_startInFlight === attempt) _startInFlight = null;` | the line deleted | C6 |
| 4 | `_startInFlight = null;` | the line deleted | C1, C2, C3, C4, C5, C6, C7, T4, T5, T6, T6b, T7, T8, T9, T10, T11 (A1: measured; every case that starts a loop) |
| 5 | `_epoch += 1;` | the line deleted | T3, T3b, T4, T5, T6b |
| 6 | `if (epoch !== _epoch) {` | `if (false) {` | T3, T4 |
| 7 | `stream.getTracks().forEach((t) => t.stop());` | the line deleted | T3, T4 |
| 8 | `if (epoch === _epoch) {` | `if (true) {` | T5 |
| 9 | `_stream = stream;` | the line deleted | C1, C2, C4, T1, T3b, T4 (A1) |
| 10 | `if (epoch !== _epoch) return;` | the line deleted | T3b |
| 11a | `if (_uploading \|\| Date.now() < _resumeAtMs) return;` | `if (Date.now() < _resumeAtMs) return;` | T6, T6b, T7 (A1) |
| 11b | the row 11a line | `if (_uploading) return;` | T8, T9, T10, T11 |
| 12 | `_uploading = true;` | the line deleted | T6, T6b, T7 (A1) |
| 13a | `if (epoch === _epoch) _uploading = false;` | `_uploading = false;` | T6b |
| 13b | the row 13a line | the line deleted | C5, C7, T6, T7, T8, T9, T10, T11 (A1) |
| 14 | `_uploading = false;` | the line deleted | C3, C4, C5, C7, T6b, T7, T8, T9, T10, T11 (A1) |
| 15 | `_resumeAtMs = 0;` | the line deleted | C3, C4, C5, C7, T9, T10, T11 (A1) |
| 16a | `_rateLimited = 0;` | the line deleted | C7 |
| 16b | `_rateLimited = 0; // a 200 ends the doubling` | the line deleted | T9 |
| 17 | `_rateLimited += 1;` | the line deleted | T9 |
| 18 | `const advised = _parseRetryAfterMs(resp.headers.get('Retry-After'));` | `const advised = null;` | T8, T10, T11 |
| 19 | `const waitMs = advised ?? BACKOFF_BASE_MS * 2 ** (_rateLimited - 1);` | `const waitMs = advised ?? BACKOFF_BASE_MS;` | T9 |
| 20 | `_resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);` | `_resumeAtMs = Date.now() + waitMs;` | T10 |
| 21 | `if (/^\d+$/.test(value)) return Number(value) * 1000;` | the line deleted | T8 (A1: T10 does not kill it) |
| 22 | `return Number.isNaN(at) ? null : Math.max(0, at - Date.now());` | `return null;` | T11 |
| 23 | `const timeout = window.setTimeout(() => controller.abort(), FRAME_UPLOAD_TIMEOUT_MS);` | `const timeout = 0;` | T7 |
| 24 | `resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form, signal: controller.signal });` | the same without `, signal: controller.signal` | T7 |
| 25 | `window.clearTimeout(timeout);` | the line deleted | C3, C4, C5 |

(`const epoch = _epoch;` occurs twice in the file and is not a row; every `epoch` comparison is.)

**S2 (the unedited base files; the new cases must fail when the base's behaviour changes).**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `ui/src/store/useStore.ts` | `if (outcome.status === 'unavailable' \|\| outcome.status === 'failed') {` | the same with `\|\| outcome.status === 'disabled'` added | S2-T1, S2-T4 |
| 2 | `ui/src/utils/resourceState.ts` | `if (status === 'disabled' \|\| status === 'unauthorized') return { failures: 0, failedAt: null, nextAt: null };` | the same without `status === 'disabled' \|\|` | S2-T1, S2-T4 |
| 3 | same | `if (status === 'ready' \|\| status === 'empty') return { failures: 0, failedAt: null, nextAt: startedAt + 10_000 };` | `startedAt + 5_000` | S2-T3 |
| 4 | same | `return { failures, failedAt, nextAt: failures > 2 ? null : failedAt + (failures === 1 ? 10_000 : 30_000) };` | `failures > 3` | S2-T2 |

## 10. Recorded limits

**S1.**
- **L1.** The first caller's options (`fps`, `jpegQuality`, `maxDimension`, `deviceId`) win while a start is pending; a concurrent caller's options are ignored, as the base ignores a later caller's once the stream exists.
- **L2.** The pause is timed with `Date.now()`: a wall-clock jump changes one pause by the jump, bounded by the 30 s cap. An HTTP-date `Retry-After` is wall-clock by definition.
- **L3.** A skipped tick is not queued; the first tick after a pause or an upload sends the frame of that moment.
- **L4.** The 10 s upload timeout counts a slow success as dropped; the server may already have stored that frame. The next tick sends a newer one.
- **L5.** Pre-existing, not changed: a stop that lands between `await toBlob` and `form.append('session_id', _sessionId)` posts a frame whose session id is the string `null`. The epoch could drop that frame; not done here.
- **L6.** Pre-existing, not changed: `stopCameraStream()` calls `reset()`, which sets `error: null` (`useCameraStore.ts:145`), so the 503 branch's `setError(...)` is cleared at once and its message never shows. C4 asserts the stop, not the message.
- **L7.** `ui/src/hooks/useScreenStream.ts` mirrors the defect: the guard `if (_screenStream) return;` (`:113`) before `await navigator.mediaDevices.getDisplayMedia` (`:119`), one `_intervalId` (`:24`), a dropped 429 (`:101`), the interval created at the end (`:153`). Not fixed; a separate checklist entry (it needs a double start while the browser's picker is open).
- **L8.** The freeze (D5) and the Three.js copies (D7) are not closed by this slice.
- **L9.** The cases rely on `window === globalThis` under vitest's jsdom, so that fake timers reach `window.setInterval` and `window.setTimeout`; expected, not measured.
- **L10.** The cases stub `document.createElement` for `video` and `canvas`; the real `drawImage` and `toBlob` path is not exercised (jsdom has no canvas and no decode), so no case can show a stall.

**S2.**
- **L1.** A re-acquired lease reads a typed-disabled queue once more (S2-T4 pins it; reversing it contradicts `approvalPolling.test.ts:150`, which pins the same rule for `unauthorized`).
- **L2.** The browser prints its own network-error line for each 503 (one per read); the app cannot suppress it.
- **L3.** A plain `unavailable` 503 is read three times per lease or manual refresh, with a warning each, by design (S2-T2).
- **L4.** That the live vessel sends the typed body is read from the route and from the server tests (section 11), not observed (item 4 of the last section).

## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\next-read` at `f614a31d`)

**Run by the Architect, read-only (CPython and Node on win32; scripts piped on stdin; nothing written but this answer; no pytest, no vitest, no build, no npm):**

```
git -C D:\ProbOS-worktrees\next-read log -1 --format='%H %s' -> f614a31d855e217eec6c826deaffad7572d1f43f "Merge pull request #1787 ... bf937-legacy-self-modification-leftovers"; git status --short prints nothing; ui/node_modules does not exist in the tree (the Builder's situation)
every SEARCH of 7.1 (the ten blocks P2-1 .. P2-8c) applied in label order to the LF blob (git show HEAD:ui/src/hooks/useCameraStream.ts, 7558 bytes, no CR): each occurs exactly once at its turn, starts at a line start, ASCII (the file's own non-ASCII lines are 1, 5, 11, 77, 85, 129, 148: none inside a SEARCH); the blocks are disjoint (byte offsets 303, 1423, 2551, 3508, 4765, 5089, 5697, 5992, 6237, 7081 in increasing order); the patched file has 303 lines (base 220); no identifier I add exists in the base
the three package.json SEARCHes of 7.3 (blob ffef098d..., LF): each occurs once; after the three blocks the file parses as JSON and holds overrides {"three": "$three"}
the tracker anchors on the LF blobs: PROGRESS.md starts with "# ProbOS Progress\n\n" exactly once (blob 70cd1044...); DECISIONS.md holds the AD-1346 M3e4d9 heading exactly once, at line 1710, at a line start, ASCII (blob 90adc283...); no CR in either blob
the 26 mutation Lines of section 9 counted, stripped, in the patched hook: each 1 (the one line that occurs twice, `const epoch = _epoch;`, is not a row); the 5 S2 base Lines counted in useStore.ts and resourceState.ts: each 1
the TypeScript compiler API (typescript from D:\ProbOS\ui\node_modules; an in-memory overlay of the patched hook and the two new test files over the reading tree; bare imports mapped to D:\ProbOS\ui\node_modules): UNFAITHFUL HOST (the vite/client types do not resolve, so process, global and the chai-derived `.not` are undefined: the existing unpatched SkillRequestPanel.test.tsx and useCameraStream.test.ts show the same classes of errors under the same host, 20 diagnostics). In that host: the patched useCameraStream.ts has 0 diagnostics at M2's head and the base hook has 0 with the new tests at M1; the two new test files show only those artifacts. So `npx tsc -b` is still "expected, not measured"
the new tests extracted from this contract: S1 19 cases (12 `built`, 7 `it`), S2 4 cases; the N2-1 marker occurs once in the S1 file
the force-graph stack against r172 (a read-only static comparison on the installed packages of the main checkout, three 0.172.0 / 3d-force-graph 1.80.0 / three-render-objects 1.41.1 / three-forcegraph 1.43.2 / stats-gl 2.4.2): named `three` imports 3, 15, 17 and 0; missing from r172: Timer (three-render-objects only); missing from r183.2: none; `class Timer` occurs in r183's three.core.js and not in r172's
the duplicate-instance string: once in r172's three.core.js, once in r183's; two occurrences, both in avatar-vendor-*.js, in the one prebuilt dist of the main checkout (an older build, not a build of f614a31d)
```

**Facts read (path:line on `f614a31d`):** `ui/src/hooks/useCameraStream.ts:19-37` (module state), `:56-70` (`_stopTracks`), `:98-148` (`_captureAndUpload`; `:101` the visibility guard, `:112` `drawImage` region, `:116-118` `toBlob`, `:136` the `fetch`, `:137-142` the 503 branch, `:143-145` the 200 branch, `:146` the 429 comment), `:152-210` (`startCameraStream`; `:161` the guard, `:177` the camera call, `:189` `_streams.set`, `:198` `play()`, `:202` the canvas, `:204` `setActive`, `:207-209` the interval), `:212-220` (`stopCameraStream`, `_testReset`); `ui/src/store/useCameraStore.ts:83-118`, `:145` (`reset` sets `error: null`); `ui/src/store/useCameraMultiplexerStore.ts:31` (`bindings: {}`); `ui/src/components/profile/ProfileChatTab.tsx:1190-1226` (`handleStartCall`, `handleEndCall`), `MeetingView.tsx:260-268`, `PerceptionLivePanel.tsx:145-152`, `App.tsx:40`, `:70`, `CompactApp.tsx:23`, `:118`; `ui/src/hooks/useScreenStream.ts:24`, `:101`, `:107-156`; `src/probos/routers/perception.py:33-62` (`_check_rate`), `:131-186` (the route; `:180-185` the 429 with `Retry-After: 1`), `config/system.yaml:1784`; `src/probos/routers/skill_requests.py:86-120`, `routers/readiness.py:14-64`, `config_models/crew.py:241-249`, `startup/communication.py:636-642`; `ui/src/utils/resourceState.ts:14`, `:22-28`, `:50-60`, `:62-85`, `:87-118`; `ui/src/store/useStore.ts:2745-2825` (`:2770` URL, `:2796` `nextResourcePoll`, `:2804-2806` the warning), `ui/src/store/approvalPolling.ts:36-77`, `ui/src/components/skill/SkillRequestPanel.tsx:244-282`; the suites: `SkillRequestPanel.test.tsx:202`, `:226-241`, `ApprovalsInBridge.test.tsx:620-640`, `approvalPolling.test.ts:135-162`; `tests/test_ad908_skill_requests_api.py:210-213`, `:241-245`, `tests/test_issue1368_readiness.py:329-330`; `ui/package.json`, `ui/package-lock.json:26`, `:36`, `:2598-2610`, `:2804-2850`, `:5367`, `:5919-5937`, `:6047-6052`; `ui/vite.config.ts:21-62` (`manualChunks`: `node_modules/three/` goes to `avatar-vendor`); `ui/src/components/profile/MemoryGraph3D.tsx:62-72` and `:98` (`nodeThreeObject` builds `THREE.Mesh` and `MeshPhongMaterial` objects from the root r172 and hands them to `ForceGraph3D`, whose renderer is the nested r183), and `three-forcegraph` has no nested `three` in the main checkout (`Test-Path` False), so it resolves the root r172; `.github/workflows/ci.yml:122-163`; `ui/vitest.config.ts` (jsdom, `globals`, `setupFiles: ./src/test/setup.ts`); `ui/tsconfig.json` (ES2020, strict); `git log --format=... -S'unavailable_dependency' -- src/probos/routers/skill_requests.py` first at `144993a2` (2026-09-13, #1394); `git show 5e3cc991:ui/src/utils/resourceState.ts` holds `nextResourcePoll` and the `disabled` branch.

**Absence Verified (2026-11-13)**

```
CLAIM: BF-933 is held only by #1671; nothing else claims it
RUN:   git log --all --format=%s -i --grep=BF-933; Get-ChildItem prompts -Filter *933*; gh issue list --repo seangalliher/ProbOS --state all --search "BF-933 in:title" --json number,title,state; rg -n "BF-933" docs/development/roadmap.md PROGRESS.md DECISIONS.md
FOUND: 0 subjects; 0 prompt files; #1671 only (OPEN); 0 hits in the three trackers
HOLDS: yes (nothing new is allocated; the contract commit's subject will be the first to name it)

CLAIM: no test reads an edited or read file as ?raw, and no Python test or script reads them
RUN:   rg -n "\?raw" ui/src | rg "ProfileChatTab|MeetingView|PerceptionLivePanel|SkillRequestPanel|useCameraStream|useStore|approvalPolling|resourceState"; rg -n "useCameraStream|useScreenStream" tests scripts --glob '*.py'; rg -n "SkillRequestPanel|resourceState|approvalPolling|store/useStore" tests scripts --glob '*.py'
FOUND: ?raw readers only of ProfileChatTab.tsx (7 files; this batch does not edit it) and of profileTranscript.ts and others outside this batch; no reader of the hook, MeetingView, PerceptionLivePanel, SkillRequestPanel, useStore, approvalPolling or resourceState; no Python hit for the hook; tests/test_issue1368_readiness.py:1 (a docstring naming resourceState.ts) and tests/test_wave_close_precheck.py:79 (a fixture string): neither reads an edited file
HOLDS: yes

CLAIM: every test that imports the hook module mocks it, so nothing inside it reaches them; the only call-text pin is ProfileChatTab.threadTranscript.test.tsx:605
RUN:   rg -l "hooks/useCameraStream'" ui/src --glob '*.test.*', then rg -c "vi.mock\('[./]*hooks/useCameraStream'" on each; rg -n "startCameraStream\(" ui/src --glob '*.test.*' (minus the mock lines)
FOUND: 10 files, each with exactly one vi.mock of the module (CameraPreviewPanel, CompactApp.sidebar-integration, MeetingView.captain, ProfileChatTab x7); the real hook is imported only by hooks/__tests__/useCameraStream.test.ts (calls at :62, :78, :87); the one regex pin is :605
HOLDS: yes. Playwright specs (ui/e2e) stub getUserMedia (agent-telemetry, conversation-viewport, consulted-evidence, fault-visibility, live-tool-progress, meeting-avatars, _helpers) and none asserts concurrency; the gate does not run them

CLAIM: no UI test pins "no console warning" for a typed-disabled skill read
RUN:   rg -n "console, 'warn'|console\.warn|spyOn\(console" over approvalPolling.test.ts, ApprovalsInBridge.test.tsx, SkillRequestPanel.test.tsx, BridgeFaults.test.tsx, ApprovalPanels.bf710.test.tsx, CapabilityRequestPanel.test.tsx
FOUND: ApprovalsInBridge.test.tsx:423 and :437 (a network error), CapabilityRequestPanel.test.tsx:246, approvalPolling.test.ts:136 and :148 (a hung read): none for a disabled outcome
HOLDS: yes

CLAIM: SkillRequestPanel.tsx, resourceState.ts and approvalPolling.ts never log; the only warning of the approval queues is useStore.ts:2805
RUN:   rg -n "console\." ui/src/components/skill/SkillRequestPanel.tsx ui/src/utils/resourceState.ts ui/src/store/approvalPolling.ts
FOUND: no match (exit 1); the warning at useStore.ts:2805 interpolates `${queue}`
HOLDS: yes

CLAIM: the only readers of /api/skill-requests?status=pending in non-test source are the two the issue names
RUN:   rg -n "skill-requests|skill_requests" ui/src --glob '!**/__tests__/**' --glob '!**/*.test.*'
FOUND: useStore.ts:2770, SkillRequestPanel.tsx:7 (comment), :263, :296 (the decide POST), useServiceStatus.ts:10 and :47 (an integration id and a label, not a read of the endpoint)
HOLDS: yes

CLAIM: the app imports no Stats overlay and no stats-gl; nothing under config/ sets skill_requests
RUN:   rg -n "<Stats|from 'stats-gl'|stats-gl" ui/src --glob '!**/__tests__/**' --glob '!**/*.test.*'; rg -n -A4 "skill_requests" config
FOUND: no match; no match
HOLDS: yes (the feature is dark by its default, config_models/crew.py:241-249)
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** AD-733 (the hook and its module-singleton shape), BF-302 (`_forceNext`, left alone), AD-742c-6 (`_activeDeviceId` and `_streams`, left alone), AD-733-2 (the screen mirror, L7); the approval-queue work this slice relies on and does not change (`resourceState.ts`, `approvalPolling.ts`, the AD-1216 lease owner whose reacquisition rule S2-T4 pins, BF-710's stable `fetchImpl`, #1368/#1394's typed availability); the voice contract's and BF-937's conventions (UI-only slices, vitest, `it.fails` with an env switch, the new-export-free test that loads before the build, SEARCH rules, tracker anchors and the ledger gate). **Rejected:** section 3. **External:** none consulted (the npm override semantics are from the documented `$name` reference form; the orchestrator's `npm ls` and `npm ci --dry-run` in 7.3 are the check).
- **Blind spots handled.** (1) A stop followed by a start while the first start is pending loses the second call if the second shares the cancelled start: `_stopTracks` drops `_startInFlight` (T4, row 4). (2) A stale failure of a cancelled start would set a store error and clear the newer start's device id: the catch is guarded by the epoch (T5, row 8). (3) A stale upload that settles after a stop and a restart would clear the new loop's in-flight flag: the flag is released only by the epoch that set it (T6b, row 13a). (4) A skip with no timeout turns a hung request into a silent stall: the abort (T7). (5) The abort timer must be cleared on every path or it outlives the stop: the nested `finally` (C3 to C5, row 25). (6) A test double that returns a plain object for a 429 has no `headers`: the cases use real `Response` objects, and the production code reads `resp.headers` only in the 429 branch, so the base suite's plain-object 200 doubles still work. (7) Module state outlives a case: every new variable is reset in `_stopTracks`, which `_testReset` calls; the new file resets it in `afterEach` and restores timers, spies and `navigator.mediaDevices`. (8) `stopCameraStream()` resets the store's `error` (L6), so C4 does not assert the 503 message. (9) The issue's console line names the **capability** queue, so the skill-poll premise is not supported by it (S2). (10) `stats-gl` has no runtime `three` import and the app uses no `Stats`: the issue's third copy is on disk only, and the "stats overlay" check is vacuous (7.3, Step 5). (11) `postprocessing` declares `< 0.184.0`: a single copy above r183 would break it, so the target is the r183.2 already in the lock. (12) No new export in the hook: the ten mock factories and the wave-close mock-parity check are unaffected.
- **What discards a correct result.** S1: a tick inside a pause or during an upload is dropped by design (the next tick is the retry); a slow but successful upload is aborted after 10 s (L4); a concurrent caller's different options are ignored (L1). S2: none (no source change). **Recorded:** S1 L1 to L10, S2 L1 to L4.

## Batching

**One pull request and one broad gate for S1 and S2; S1 first, then S2; the voice batch merges before it is built; the dedupe (7.3) is the orchestrator's separate action.** The order the earlier consult proposed (the camera loop first, then the skill poll) is **confirmed for the camera loop and rejected for the skill poll's content**: the poll needs no build (section 1), so its slice is a pin; the dedupe and the freeze are the orchestrator's and the Captain's, as proposed, and the dedupe's direction is fixed by evidence (D7).

| Point | Judgement |
|---|---|
| Files | Disjoint: S1 `useCameraStream.ts` and one test; S2 one test. Only the tracker pairs (PROGRESS, DECISIONS, the ledger pair) collide, with each other and with the voice batch: re-anchor them, as the header says. `ProfileChatTab.tsx` is not touched, so the voice batch's edits to it cannot collide |
| Why together | One live call, one front-end; both close from vitest alone, need no backend, no config, no `npm install` and no generated file but the AD ledger pair; S2 costs one test file |
| Order | S1, S2. S1 is the real defect and should land before any live re-measurement of BF-930 and BF-932 (a leaked capture loop adds vision-frame traffic to exactly that window); S2 is independent and cheap |
| Revert | Separate commits per milestone and per slice; each slice reverts alone |
| Cost: UI | Per slice: its G1 file and G2 directories (section 4), then `npx tsc -b`; once per batch, mine: `npm run build`, the whole `npx vitest run`, the mutation rows; CI's `ui-tests` (`npm ci`, `npm run test`, `npm run build`) runs again on the pull request. No `?raw` reader of an edited file |
| Cost: Python | None beyond G3 (`gen_ad_ledger.py`, its `--check`, `tests/test_ad1184_ad_ledger.py`) and the broad gate with the label `bf933`: no Python or config file changes, and no Python test reads an edited file (Absence Verified). The broad gate does not run the UI tests or the UI build |
| Cost: config | None: no default, no model, no yaml; the AD ledger pair is the only generated artifact |

**What the rest wait for.**

| Item | Waits for | Why |
|---|---|---|
| The freeze | A profile of a live call after S1 is deployed | The in-flight skip may remove it if stacking was the cause; if a `setInterval` violation remains, the profile names the function (item 2 below) and one follow-up is filed with the measured name |
| The Three.js dedupe | The orchestrator's 7.3 after S1 and S2 merge, then the Captain's look | Needs `npm install` and a visual check of the avatar and graphs |
| The screen hook's mirror (L7) | A decision that a double start of a screen share is worth a slice | Same defect class, lower likelihood |

## Not in this issue: for the Captain

Each item is an observation of the running vessel or the Captain's own senses; the build does not do it and neither can a test. None needs a decision.

1. **A live call with S1 deployed.** Watch the browser console for five minutes of a video call: no sustained run of 429s from `POST /api/perception/camera/frame`, and the camera light off after the call ends (a leaked stream would keep it on). If 429s persist, copy the first few lines and the count to the orchestrator, who redacts before anything is filed.
2. **The 5 s freeze.** In the same call, open DevTools, Performance, record 60 seconds with the camera on, and note the longest task of the page and its top function in the Bottom-Up view (expected candidates: `drawImage`, `toBlob`, the canvas resize); or just report whether `[Violation] 'setInterval' handler took` appears again and for how long. This is what D5 needs to choose between the offload and the capture-size options.
3. **Three.js (only if the orchestrator runs 7.3).** On the scratch build: the crew avatar (mouth, skin and hair shading, expression), the three force-graph views, the ship layout and the cognitive canvas, and the console (no duplicate-instance line). A regression means revert and keep two copies (D7 row 4).
4. **One line against the live server** (the orchestrator or the Captain): `curl -s -i "http://127.0.0.1:18900/api/skill-requests?status=pending"`. Expected: `503` and a body with `"state": "disabled"`. If the body says `unavailable` instead, the server's config is not the typed `SystemConfig` the route expects, or the cluster is enabled with a store that failed to build: that is a server-side finding and the HXI behaviour of S2 would then be the bounded three reads, not a stop.

## 13. Diff Reviewer: properties to verify

1. **S1, one start.** Two concurrent calls return the same pending work and open one camera; after the start settles or fails, `_startInFlight` is cleared; no path leaves it set (rows 1 to 4; C6).
2. **S1, every await is followed by an epoch check before module state is written:** after the camera call (`_stream = stream` only for a current epoch; the stream released otherwise), after `play()` (no interval for a stale start), and in the catch (no error or device-id write for a stale start). A write to `_stream`, `_video`, `_canvas`, `_sessionId`, `_activeDeviceId` or `_intervalId` after an `await` without a check is a finding.
3. **S1, `_stopTracks` is the single place of cancellation:** it bumps `_epoch`, clears `_startInFlight`, `_uploading`, `_resumeAtMs` and `_rateLimited`, and `_testReset` goes through it; no other function resets them.
4. **S1, the upload.** `_uploading` is released by `finally` only for its own epoch; the abort timer is cleared on every path (the nested `finally`); a skipped tick returns before any canvas work; the 429 branch reads `Retry-After` from the real `Response`, clamps to 30 s, falls back to 1 s, 2 s, 4 s, and a 200 resets.
5. **S1, no export added; no edit to `ProfileChatTab.tsx`, `MeetingView.tsx`, `PerceptionLivePanel.tsx`, `useCameraStore.ts` or any server file;** `git diff --stat` for S1 M2 shows `useCameraStream.ts` and the one test marker only.
6. **S1, the tests restore:** `_testReset`, `vi.useRealTimers`, `vi.restoreAllMocks`, `navigator.mediaDevices`, the store; no case relies on another's leftover; no `fetch` or `createElement` spy outlives a case.
7. **S2, no source.** `git diff --stat` for S2 shows one new test file, then the trackers and the ledger pair.
8. **Public text.** No crew name, thread id, timestamp, live count or console line of the vessel in any test, comment, tracker line or commit message; the S2 warning fragment is built from the store's own code.
9. **Tracker text** contains no `AD-` token and no BF number other than 933.
10. **The dedupe is not in the pull request** (no change to `ui/package.json` or the lockfile in any commit of the batch).

## 14. Acceptance criteria

1. G1, G2 and G3 of each slice pass as stated in section 4; the oracle's `npm run build`, whole `npx vitest run`, mutation rows and broad gate pass; CI's `ui-tests` passes.
2. A test calls `startCameraStream()` twice without awaiting between, then `stopCameraStream()`, and asserts one camera call, one interval created, one pending timer after the starts and none after the stop (S1 T1).
3. A stop during a pending start, and a stop then a start during a pending start, leave exactly the loop the last call asked for and no leaked stream (S1 T3, T3b, T4, T5).
4. On a 429 the loop honours `Retry-After` (seconds or an HTTP date, capped at 30 s) or backs off 1 s, 2 s, 4 s; a 200 and a stop reset; no capture starts while an upload is in flight, and an upload that never answers is aborted (S1 T6 to T11, C7).
5. A single call still starts one stream and one loop; `stopCameraStream` still releases the tracks; a 503 still stops the camera; a 413 or a network error still drops one frame and keeps the loop (S1 C1 to C6).
6. A typed-disabled skill-request queue is read once per lease, leaves the capability cadence alone and logs nothing; a plain 503 is bounded to three reads and names the queue; an enabled queue is unchanged (S2); no source file of S2 changes.
7. No export is added to `useCameraStream.ts`; no test pins a defect; `ProfileChatTab.tsx` is unedited.
8. #1671 stays open with the checklist of D1 and the four live actions; every M3 says `Refs #1671`; the freeze and the dedupe are recorded, not closed.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-13): the base after the voice batch, the measured gates and mutation rows, and eight Killed-by cells

**Drafted by:** the orchestrator, not the Architect: every change below follows a measurement on the oracle, so it is mechanical. **No block of section 7 changed:** the slice files cut from sections 7.1 and 7.2 are byte-identical to the ones the oracle applied.

**Base.** The batch builds on `origin/main` after the voice batch (BF-928, BF-929, BF-931; pull request #1788, head `81946ed2280b6ca422a7325cf80197297a4e73b8`, tree `7556424eeeccc1a34c752186da89b8c9cf9222a1`; the merge's tree is that tree because `origin/main` had not moved). **Measured** (blob of every path of the header at `f614a31d` and at that head, by `git rev-parse`): every blob the header states equals the one at `f614a31d` (the Architect's blob ids hold); between the two commits only these paths of the header differ: `ui/src/components/profile/ProfileChatTab.tsx` (not edited by this batch, as the header says), `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (the voice batch moved all four, as the header predicted); the three new paths are absent; the two tracker anchors each occur exactly once, at a line start, ASCII (`PROGRESS.md` on line 1; `DECISIONS.md` now on line 1732, after the voice batch's entries).

**Measured gates** (the orchestrator's oracle: the blocks applied by tool on that base, a scratch commit per milestone). **S1:** `npx vitest run src/hooks` at M0: 8 files, 88 tests; G1 at M1: `7 passed | 12 expected fail (19)`; with `BF933_RUNXFAIL=1`: `12 failed | 7 passed (19)`, each of the twelve failing at its own `expect` (the call count of `getUserMedia`, of the interval or of `fetch`, a released stream, a flag, the store's `error`), none at an import or a premise; G2 at M2: 9 files, 107 tests (M0 + 19); the wide consumer run of section 4 (11 targets, 16 files): 258 tests at M0 and at M2, unchanged; `npx tsc -b` clean. **S2:** the G2 command of section 4 at M0: 28 files, 717 tests; G1 `4 passed (4)`; G2 at M1: 29 files, 721 tests (M0 + 4); `npx tsc -b` clean. **The batch:** `npm run build` clean; the whole `npx vitest run --maxWorkers=8`: 374 files, 4,331 passed, 1 skipped (the voice head: 372 files, 4,308 passed, 1 skipped; so +2 files and +23 tests). Run the whole suite with `--maxWorkers=8` on a loaded host (the voice contract's A2).

**Measured mutation rows.** S1, 28 rows: **every mutant is killed**. Twenty rows give the killer sets of section 9; **seven name fewer cases than fail** (rows 4, 9, 11a, 12, 13b, 14 and 15: a deleted reset or guard breaks every case that starts a loop or an upload, which is a superset of what the first text said), and **one names a case that does not fail** (row 21: `T10` passes when the numeric `Retry-After` parse is deleted, because the value then reaches the HTTP-date branch, where `Date.parse('3600')` reads as the year 3600, a far-future date, and the 30 s cap gives the same pause; `Date.parse('3')` reads as a date in 2001, in the past, so `T8`'s three-second pause is lost and `T8` alone kills it; checked with Node 24). The cells of those eight rows are corrected in section 9 (marked A1). S2, 4 rows: all four give the cells of section 9.

**Measured ledger movement.** S1 M3 moves BF-933 only (Shipped BF +933, Unaccounted BF -933), the report's `git log` row and the two skipped-line numbers of `PROGRESS.md` (shifted by the 4 lines of the entry); numstat `9 0 DECISIONS.md`, `4 0 PROGRESS.md`, `6 3` the snapshot, `6 6` the report. S2 M3 moves no number (the `git log` row and the two skipped-line numbers only); numstat `7 0`, `4 0`, `3 3`, `3 3`.

**What A1 changes.** The header (a `Revised by` line) and eight cells of section 9. Nothing in sections 1 to 8, nothing in a block.
