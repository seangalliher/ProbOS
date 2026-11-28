# BF-928 (#1666), BF-929 (#1667), BF-931 (#1669): the voice and call UI of one live video call: a call no longer reads the thread's history aloud, a spoken paragraph break no longer says "dot", and the avatar's mouth no longer starts before the voice

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge is logged out), 2026-11-13
**Revised by:** the orchestrator (amendment A1, 2026-11-13, section 15), measured on an oracle over BF-937's merge `f614a31d855e217eec6c826deaffad7572d1f43f` (the blocks applied by tool, every gate of section 4 and every mutation row run): one defect found by running (S2's appended case T3 fails after T1 in file order: a store leak, repaired inside N1-2), the killers of five mutation rows understated, and the ledger movement of the batch different from the in-memory measurement; and amendment A2 (2026-11-13, section 15 and the repair R1 of section 7.4) after review round 1 (S3 READY; S1 NOT READY: the paragraph rule rescans every run of spaces, quadratic; S2 NOT READY: the appended cases leave four live-frame fields of the store behind), measured on the same oracle. The Architect's text is otherwise unchanged. Where section 15 and an earlier section differ, section 15 wins; where prose and a block differ, the block wins.
**Answer file:** in four parts, because the contract is too long for one `create` call: `answer-voice-contract.part1.md` (header, sections 1 to 6), `answer-voice-contract.part2.md` (section 7: slices S1 and S2), `answer-voice-contract.part3.md` (section 7: slice S3; sections 8 to 10), `answer-voice-contract.part4.md` (section 11, section 12, "Batching", "Not in this issue: for the Captain", sections 13 and 14). Read them in that order; the labels of section 7 restart in each slice.
**Status:** ready to build on `origin/main` `f614a31d855e217eec6c826deaffad7572d1f43f` (BF-937's merge; #1678 closed; A1 measured the base, see section 15). **Reading tree:** `D:\ProbOS-worktrees\next-read` at `54a112e2c73726bda6ab020993036541e4b21bfd` (the Architect's reading base; clean; read only). **Oracle:** the Architect ran no pytest, no vitest and no UI build (a read-only consult); the orchestrator's oracle did (section 15). **What I ran instead** (section 11): every SEARCH of section 7 against the LF blobs of the reading tree (occurrences, line start, ASCII); the three pure test files of section 7 executed (transpiled, under a 40-line stand-in for vitest, nothing written) against the unpatched and the patched sources, which fixes their classification (S1 on the base: 4 pass, 5 expected failures, each failing at its own assertion with the received text quoted in section 6); the stripper and the sentence splitter of S1 evaluated in memory with the seven mutants of section 9; the heuristic track sampled at the times S3 relies on; the whole `ui/src` program, with the new and patched files overlaid in memory, compiled with the TypeScript compiler API (0 diagnostics at M1 and at the head). **What that leaves unchecked (all "expected" below):** every vitest case as a vitest case (the counts), above all the two mounted seam tests (S2's, S3's), `npm run build`, the ledger regeneration, the broad gate, and everything that needs the live vessel (section "Not in this issue: for the Captain").
**Base blobs (`54a112e2`):** S1: `ui/src/audio/voice.ts` `a248843db9ab7b2ad4711dbccd4a44bce1867839`, `ui/src/audio/voiceChunking.ts` `1133aa1cd61d7e5e30de845c5d66d722604aea8b`. S2: `ui/src/components/profile/speechLedgerStore.ts` `e80a940251e13d7bfff7627e2d3843ed4eaf0244`, `ui/src/components/profile/profileTranscript.ts` `4d3f1c903b783bfb3648227de4bba247584274df`, `ui/src/components/profile/ProfileChatTab.tsx` `3ed3ee2a6c738e6fb4c0467c3e5fd920cbc40986`, `ui/src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx` `317202c9bcfebe9047c696d3b9212cc3085305a3`. S3: `ui/src/audio/lipSyncTrack.ts` `f130440f701b23b8b311b65bed7bbf571b01378c`, `ui/src/components/profile/CrewVRM.tsx` `36bf9f7660953d7862d7703cd4549e348b02efd4`. Read, not edited: `ui/src/audio/useLipSyncCapture.ts` `104e5b4f2a7a0614c85694611e7068868e457586`, `ui/src/audio/__tests__/voice.test.ts` `562686d74c035bfff6f744457e10e6c765e0239d`, `ui/src/audio/__tests__/voiceChunking.test.ts` `d2f9b14285c627091abfe1a7a593ad3a57d0f5af`. All slices: `PROGRESS.md` `f580b10cf4f24b1ea972268e6766da5a0a2b46ee`, `DECISIONS.md` `0e67c4d6e0e47fb0922ef9f6c95cb5f8dbe0b6dd`, `docs/development/open-ads-report.md` `309df79d37f81cec82c9b0efc75ae211dd2beb4a`, `docs/development/ad-ledger-snapshot.json` `e216c74da7cc5890e42aba314ee37800d5848008`. **BF-937 changes `PROGRESS.md`, `DECISIONS.md` and the ledger pair before this batch is built (section "Tracker anchors, and the BF-937 merge" below): those four blobs will differ; every other blob above must be equal.** **A1, measured on `f614a31d`:** the four moved to `PROGRESS.md` `70cd1044019282b348bba2532acd6bfb2b6369cf`, `DECISIONS.md` `90adc2837c3d2c6d09327e93543eeb0471880fec`, `docs/development/open-ads-report.md` `04562090a74a962b09f61864a667ecb1a62f1b8a`, `docs/development/ad-ledger-snapshot.json` `35de650056f112a17d079fab48f32ddabad939bb`; every other blob above is equal (all eleven code and test paths), and none of the five new paths exists.
**Dependencies:** BF-937 (#1678) merges first (it shares no file with this batch except the four tracker files). **Tier:** every M1 STANDARD (tests); M2 STANDARD for S1 (one regex in each of two pure functions), HIGH for S2 (the speech owner of every chat surface) and S3 (the avatar's per-frame loop); every M3 STANDARD. **Estimated tests (expected, not measured):** S1 one file, 9 cases (4 pass, 5 expected failures at M1); S2 one new file, 5 cases (1 passes, 4 expected failures), plus 3 cases appended to `ProfileChatTab.bf718.test.tsx` (2 pass, 1 expected failure); S3 two new files, 6 cases (1 passes, 5 expected failures) and 3 cases (1 passes, 2 expected failures). No Python test, no config, no generated artifact but the AD ledger pair. **Numbers:** BF-928, BF-929 and BF-931 are held by #1666, #1667 and #1669 (open, label `bug`); BF-930 (#1668), BF-932 (#1670) and BF-933 (#1671) are the other three of the six issues of one call. Nothing new is allocated (section 11, Absence Verified: nothing else claims any of the six).

**Tracker anchors, and the BF-937 merge.** PROGRESS.md: the title line `# ProbOS Progress` and the blank line after it (the one place where an entry is inserted; BF-936's entry is the first after it today, BF-937's will be the next, mine follow). DECISIONS.md: the heading line `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)` (it occurs once, at line 1694 on `54a112e2`; BF-936's entry sits before it, BF-937's will be inserted before it too; each of my three entries is inserted before it as well, so they land after BF-937's and in slice order). Both anchors are measured on `54a112e2` (section 11) and are expected to survive BF-937's merge, which inserts at the same two places. **The orchestrator re-anchors after the merge:** re-run the occurrence check of those two SEARCHes (each exactly once, at a line start, ASCII); any other change to either file between `54a112e2` and the build's base is a hard stop for the Architect. The AD ledger pair (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`) is regenerated at each M3 by `scripts/gen_ad_ledger.py` (G3); BF-937 regenerates it too, so its blobs move before this batch and the regeneration is repeated, not merged by hand. **No tracker line of this batch contains the token `AD-`**; each head names its own BF number only. The ledger reads AD and BF numbers at the head of tracker entries, so each M3 moves it by that number: the measured diff is in G3 of section 4. **A1, measured on `f614a31d`:** the only change to either tracker file since `54a112e2` is BF-937's own entries (PROGRESS.md: 8 lines added at line 3, directly after the title line and its blank line; DECISIONS.md: 16 lines added at line 1694, directly before the anchor heading), and each anchor occurs exactly once, at a line start, ASCII (PROGRESS.md on line 1, DECISIONS.md on line 1710).

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` for the paths above prints the blobs above, except the four tracker files; `git diff --stat 54a112e2 HEAD -- ui src config` shows only BF-937's files (`ui/src/components/IntentSurface.tsx`, `ui/src/components/bridge/FullKanban.tsx`, one line of `ui/src/store/useStore.ts`, the new `ui/src/store/buildQueueApprove.ts`, its UI test and fixture, `src/probos/routers/build.py` and the self-improvement persistence and config) (A1: on `f614a31d` the stat's last line reads `11 files changed, 403 insertions(+), 33 deletions(-)`, and `git rev-parse f614a31d:<path>` for the paths of the header shows no other difference: the eleven code and test paths are equal); none of the eight source and test paths this batch edits exists in a changed form, and none of the five new files exists (`ui/src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`, `ui/src/components/profile/__tests__/speechLedgerLoaded.bf928.test.ts`, `ui/src/audio/__tests__/lipSyncTrack.mouthClock.bf931.test.ts`, `ui/src/__tests__/CrewVRM.mouthClock.bf931.test.tsx`, `prompts/bf-928-929-931-voice-call-ui.md`: the last is this contract's own place; the orchestrator may rename it). If one fails, every SEARCH must still occur exactly once, else it is a hard stop. Working copies are CRLF and SEARCH text is LF; this answer file is not LF-only (the writing tool's convention), so normalize line endings before applying a block. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order, slice by slice. **Every SEARCH starts at the start of a line and is ASCII with no exception** (the non-ASCII lines of the edited files, for example the bullet in `voice.ts:1018`, the em dash in `ProfileChatTab.tsx:881` and the ellipsis in `voiceChunking.ts:30`, are never inside a SEARCH). The REPLACE texts are ASCII too: the regexes write the typographic quotes and the double angle quote as `\u201d`, `\u2019`, `\u00bb`, `\u201c`, `\u2018` and `\u00ab`, and the test files write them the same way. **Which block may move a later block's line numbers:** none changes a SEARCH of a later block (each SEARCH is anchored on its own text, once); S1 P2-1 and P2-2 add lines to `voice.ts` after line 1012 only; S2 P2-3b adds lines to `ProfileChatTab.tsx` after line 885 and P2-3a one name to line 58; S3 P2-3 adds lines to `CrewVRM.tsx` after line 617 and P2-2 one line after line 17 (so the line numbers quoted in sections 1 and 11 are those of `54a112e2`, not of the build).

## 1. Problem

Six bugs came from one live video call (#1666 to #1671, copied at `...\files\voice\issue-<number>-copy.md`). Their anchors are from `5e3cc991`; every one is re-derived on `54a112e2`. Their live claims (log counts, timings, what the Captain saw and heard, a crew member's name, her words, a thread id) are the issues' own: they are quoted nowhere in this contract, no test, comment, tracker line or commit message of this batch holds them (decision D5), and none of them is verified here. **This batch takes three of the six** (decision D1); the other three wait (section "Batching").

| Issue | Re-derived on `54a112e2` |
|---|---|
| #1667: `voice.ts` `stripMarkdownForSpeech`, `voiceChunking.ts` `splitIntoSentences` | `voice.ts:1012-1024` (the function; the paragraph rule is the one line `:1022`); `voiceChunking.ts:37-65` (the function; the cut is the one regex `:52`, its sentinel pass `:51-57`); the splitter is reached only from `voice.ts:580`, inside `if (status.sentence_pipelining_enabled)`, and with the flag off the whole stripped text goes to Piper in one call (`voice.ts:607`), so the doubled mark reaches the synthesizer on both paths |
| #1666: `ProfileChatTab.tsx` the seed rule, `profileTranscript.ts` `admitMessages` | `ProfileChatTab.tsx:787-788` (`speechLedgerRef`, `speechSeedScopesRef`), `:810-902` (`refreshThreadTranscript`; the pending trigger `:817`; the seed `:885`), `:1363-1372` (the open-time load), `:1374-1392` (the push-triggered load; `:1380` the live-id set), `:1394-1398` (the reconnect repair), `:1481-1531` (the speech effect: `markScopeSeen` `:1482`, the seed `:1483`, the admission `:1512`, the call `:1524-1531`); `profileTranscript.ts:241-247` (`markScopeSeen`), `:302-318` (`scopeRecord`), `:340-353` (`claimSpeech`), `:366-371` (the doc warning the issue quotes), `:377-391` (`admitMessages`); `speechLedgerStore.ts:20-23` (`SpeechScope`) |
| #1669: "find the mouth schedule" | there are two: the heuristic viseme track, `CrewVRM.tsx:509-516` (built at the speech `start` event; `startedAtMsRef.current = performance.now()` `:510`) and sampled on the wall clock at `:615-618`; and the rhubarb frames, `:586-609`, sampled on the audio clock `getActiveAudioTimeMs()` (`voice.ts:322-329`). The `start` event is fired by the audio element's `play` event, `voice.ts:761`; the audio's `playing` event only feeds a timing measure, `:762` |
| #1671: `useCameraStream.ts` `startCameraStream` | `useCameraStream.ts:152-210` (`if (_stream) return;` `:161`; `_stream` is set after the `getUserMedia` await `:177-181`; the interval is created `:207-209` in the module variable `_intervalId`; `_stopTracks` clears that one id `:61-64`); callers `ProfileChatTab.tsx:1205`, `MeetingView.tsx:267`, `PerceptionLivePanel.tsx:151`. Not in this batch |

**S1 (BF-929): the doubled period.**

1. **The line.** `stripMarkdownForSpeech` ends with `.replace(/\n{2,}/g, '. ')` (`voice.ts:1022`): every paragraph break becomes a period and a space, whether or not the paragraph already ended a sentence. Evaluated in memory on a synthetic three-paragraph text whose paragraphs end in periods, the old function returns `...stable.. Two things ...surprise.. That is ...` (section 11): the issue's cause, confirmed, and not only for the period: a paragraph ending in `?` gives `?.`, in `!` gives `!.`, in `."` gives `.".`, in an ellipsis gives four dots, and a blank line with trailing spaces gives a lone `.` that the splitter returns as a chunk of its own (all six behaviours measured in memory).
2. **The splitter's part.** `splitIntoSentences` cuts after `([.!?]+)\s+` (`voiceChunking.ts:52`). After `here..` the greedy group takes both periods, so the chunk Piper receives ends in `..`. A fix that only stops adding the period loses something the period used to supply: after `."` or `.)` the splitter does not cut (the quote or bracket sits between the period and the space), so a paragraph ending that way would run into the next paragraph's first sentence in one chunk. The old text cut there only because of the stray period (`.".`). The acceptance asks that each paragraph still end a chunk, with a closing-quote or bracket variant in the fixture, so the splitter gets one rule for it (decision D2).
3. **Who reads the text.** `stripMarkdownForSpeech` has six production call sites (`ProfileChatTab.tsx:1183`, `:1526`, `:2021`, `:2264`; `IntentSurface.tsx:476`, `:509`) and one more through `useMeetingVoice.ts:163` (the meeting sequencer's `strip`); all of them pass the result to `speakResponse`. One test calls the real function (`voice.test.ts:82`, with `toContain` checks that do not pin the join); 29 test files mock it as an identity inside a `vi.mock('.../audio/voice')` factory (45 files mock that module in all; section 11).

**S2 (BF-928): the history read aloud.**

4. **The rule.** The transcript effect speaks the arrivals `admitMessages` admits (`ProfileChatTab.tsx:1512`, `profileTranscript.ts:377`). A scope's rows are history (claimed, not spoken) when the effect's run is a first sight (`markScopeSeen` `:1482`) or the scope sits in `speechSeedScopesRef`, which `refreshThreadTranscript` fills only for a load with no trigger message (`:885`). A load driven by a pushed message is deliberately not seeded ("the live arrival this AD exists to speak", `:882-884`); the one row that is live is protected by the live-id set (`:1380`, `admitMessages`' `liveIds`).
5. **Where the first sight goes.** On a hard reload the speech effect runs for the thread's scope before any transcript has landed: the list is empty, `markScopeSeen` answers true, and the first-sight seed is used up on nothing (`profileTranscript.ts:366-371` warns of exactly this: "the real history arrives afterwards and looks exactly like new traffic"). From then on only a no-trigger load seeds.
6. **How the first landed load becomes a trigger load (code, not the live log).** Two paths in `refreshThreadTranscript` make the first load that lands a trigger load. (a) A load that fails or is dropped (`outcome.kind !== 'success'` `:847`; `superseded_request` and the other stale reasons `:853-866`) returns before the seed is recorded, so the open-time (no-trigger) load can fail to count. (b) A refresh requested while one is in flight is coalesced with `transcriptPendingRef.current.set(targetThreadId, triggerMessageId ?? pending)` (`:817`): a push that arrives during the open-time load turns the retry into a trigger load. After (a) and (b) together, which is the sequence the call's greeting append produces when the open-time load fails or is superseded, the first load that lands carries a trigger, is not seeded, and every historical row is admitted and spoken, oldest first. Whether the live call went through (a) or (b) or something else is the issue's account and is not verified here; the contract fixes the rule, which does not depend on it (decision D3), and builds the sequence above from the component's own paths in a mounted test.
7. **The tests do not pin it.** No existing test has the first load that lands be a trigger load and expect history to be spoken: the three ProfileChatTab test files that push a refresh all wait for the open-time load to hydrate first (`mount()` waits for `threadMessages.has(THREAD_ID)`: `ProfileChatTab.ad1291.e2e.test.tsx:208`, `ProfileChatTab.bf764.test.tsx:227`, `ProfileChatTab.issue1340.groupUnmount.test.tsx:207`, and the same helper in `ProfileChatTab.bf718.test.tsx`), and the one that pushes during a seeding load expects the pushed row to be spoken (`ProfileChatTab.bf718.test.tsx`, "speaks a push whose row was already inside a seeding load"), which stays true.

**S3 (BF-931): the mouth before the voice.**

8. **The anchor.** `voice.ts` fires the speech `start` event from the audio element's `play` event (`:761`), which the element raises when `play()` is called and playback is requested, not when sound begins. `CrewVRM` builds its heuristic track at that event and starts a wall clock (`:509-511`), then samples the track with `performance.now() - startedAtMsRef.current` (`:615-618`). With BF-918's deferred visemes the avatar runs on this heuristic track until the rhubarb frames arrive (`voice.ts:785-797`, "until these arrive the avatar animates on the browser's heuristic schedule"), so for as long as the audio takes to start, the mouth moves while nothing is heard: the issue's cause, confirmed in the code. The rhubarb branch does not have the defect: it samples on `getActiveAudioTimeMs()`, the element's `currentTime` (BF-283), which is 0 until the element plays (`CrewVRM.tsx:595-599`). The late-arriving visemes "aligned to the audio's time" line of the acceptance is therefore already true and becomes a control. A heuristic track is closed at time 0 and before it (`LipSyncTrack.sample`: "out-of-range gives all zeros", `lipSyncTrack.ts:37-41`; measured: `sample(-1)` and `sample(0)` are all zeros), so sampling it on the audio clock keeps the mouth closed until the sound.
9. **What is not the cause.** The `playing` event is not missing from `voice.ts` (`:762`); moving the `start` event to it is the other fix and is rejected (decision D4): 45 test files mock `audio/voice` and three real voice suites (`voice.pipelining.test.tsx`, `voice.balancedEnd.test.tsx`, `voice.prefetch.bf918.test.tsx`) drive a fake `<audio>` whose `play()` emits `play` and expect `start` from it (`voice.prefetch.bf918.test.tsx` emits `playing` by hand in two timing cases only), so they pin the old order, and BF-655's balanced start and end would break for a `pause` that comes before `playing`.

## 2. Solution

**S1.** `stripMarkdownForSpeech` turns a paragraph break into a period and a space only when the paragraph does not already end in `.`, `!` or `?`, optionally followed by closing quotes or brackets; otherwise it keeps the paragraph's own mark and adds one space. Trailing spaces before the break and a run of blank lines are one pause. An ellipsis, a decimal and a paragraph without sentence punctuation behave as before (the last still gets its period). `splitIntoSentences` gets one more cut: after `[.!?]+` plus closing quotes or brackets when whitespace and then a capital letter or a digit follow (with an optional opening quote or bracket), so each paragraph still ends a chunk and inline dialogue with an attribution (`"Stop!" he said.`) is not cut. No export is added to `voice.ts` (the wave-close precheck diffs its exports against the mocks).

**S2.** The shared speech ledger records per scope whether a transcript load has landed (`SpeechScope.loaded`, `markScopeLoaded` in `profileTranscript.ts`). `refreshThreadTranscript` calls it after a load lands, and seeds the scope when the load had no trigger message or is the first load that landed for the scope. The trigger message is still spoken (its id is in the live-id set before the fetch, and `admitMessages` admits listed ids while seeding), and a later push-triggered load is not seeded, so BF-718's guarantees hold: a live reply is spoken once, a push inside a seeding load is spoken, a repair seeds.

**S3.** A pure `mouthClockMs(audioMs, wallMs)` in `lipSyncTrack.ts` chooses the clock to sample a heuristic track on: the wall clock when no server audio is active (browser speech: its own `start` is the sound), otherwise the audio element's time, which is 0 until it plays and so keeps the track closed. `CrewVRM`'s heuristic branch uses it. The `start` event, every other consumer of it and the rhubarb branch are unchanged.

## 3. Decisions

Ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; the top row is taken. In every row: in-envelope means evidence, backward compatibility, no weakened security, governance, privacy or audit control, no OSS/commercial boundary crossed, bounded rollback. All of it is OSS UI code.

**D1. Which of the six, and how batched.** First, which can close from tests alone:

| Issue | Closes from vitest alone? | Why |
|---|---|---|
| #1667 BF-929 | **Yes** | a pure function and a pure splitter; the acceptance is a text assertion (its "stripped text and chunks" test) |
| #1666 BF-928 | **Yes** | a rule in a pure ledger plus a mounted seam test of the real component (the harness exists: `ProfileChatTab.bf718.test.tsx`); the acceptance is a seam test |
| #1669 BF-931 | **Yes** | a pure clock choice plus a mounted `CrewVRM` over the real `voice.ts` with a fake `<audio>`; the acceptance is a fake-audio test; the Captain's eyes confirm it afterwards (an action, not a gate) |
| #1671 BF-933 | **No** | the camera loop and the skill-request poll are testable, but "no `setInterval` violation over 50 ms during a 5-minute call" needs a live profile, the Three.js dedupe is `ui/package.json` and the lockfile (`npm install`: not the Builder's) and a visual check of the force graph and the stats overlay |
| #1668 BF-930 | **No** | "instrument first" and "re-measure on the live vessel"; the fix depends on where the time goes |
| #1670 BF-932 | **No** | the same; the 19 to 41 s the issue reports are unexplained by any log |

Then the batch (at most three, tightly coupled: one gate, one pull request):

| # | Option | Judgement |
|---|---|---|
| 1 | S1 BF-929, S2 BF-928, S3 BF-931 in one batch, in that order (chosen) | The three close from vitest alone; one tier (UI), no backend, no config, no generated artifact but the AD ledger pair, no `npm install`; one validation set (`src/audio`, `src/components/profile`, `src/__tests__/CrewVRM`, `npx tsc -b`, `npm run build`); coupled by the speech path of one call: BF-928 decides which transcript rows reach `speakResponse(stripMarkdownForSpeech(...))` (`ProfileChatTab.tsx:1526`), BF-929 decides what that text says and BF-931 which clock the mouth follows while it plays (`getActiveAudioTimeMs`, `voice.ts:322`); each slice reverts alone |
| 2 | BF-929 + BF-928 + the camera-loop part of BF-933 | BF-933 cannot close (above); a `Refs` slice leaves #1671 open; and it shares no file or contract with the other two (the callers of `startCameraStream` need no edit) |
| 3 | all six | BF-930 and BF-932 have nothing to build from yet; five slices in one pull request revert as one |
| 4 | one pull request per issue | six gates and six reviews for three small independent fixes of one subsystem; the cost is validation, and it buys nothing |

**Order: S1, S2, S3.** S1 is the smallest and touches no component; S2 changes the speech owner of every chat surface, so it gets its own review attention before the rest; S3 is last because its mounted seam test has the heaviest harness (a captured frame loop, a fake `<audio>` with a clock, the real `voice.ts`): if the oracle cannot make it run, S3 leaves the batch alone and S1 and S2 ship (section 10, S3 L6).

**Is an instrumentation-only slice worth building now for BF-930 and BF-932?** Table of the choices:

| # | Option | Judgement |
|---|---|---|
| 1 | Wait: BF-933's camera-loop slice first, then one log-only Python contract for both, then a live call for the numbers (chosen) | The two windows the issues measure contain the vision-frame traffic of the leaked capture loops BF-933 reports (BF-930 names "camera-frame vision describes" in its load list and BF-932 names the store stalls in the same window), so instrumentation built and read before the loop is fixed measures the leak. BF-932's instrumentation is worth building (nothing logs the wait; `perception/consumer.py:722-840` has three steps outside the 4 s cap: the permit, and `store.exists` before and after the capped `wait_for`); BF-930's is small (the route log already separates `synth_ms` from `store_ms`, `routers/avatars.py:327`; the missing part is queue wait versus I/O inside `attachments/store.py`). Different tier (Python, its own tests, `tests/test_bf918_tts_latency.py` and five force-describe files pin the log shapes) |
| 2 | Build the instrumentation now, in this batch | Mixes a Python log change into a UI batch (two tiers, two gate sets) and measures before the known confounder is removed |
| 3 | Bound `force_describe_current_frame` end to end now, uninstrumented | The issue's own acceptance says instrument first; the other candidate causes (the LLM lane, the agent's queue) would be left unmeasured |

**D2. Where S1 fixes the doubled mark.**

| # | Option | Judgement |
|---|---|---|
| 1 | In the stripper: the break adds a period only after a paragraph that does not end a sentence; and teach the splitter the closing-quote boundary (chosen) | Removes the cause for both paths (single call and pipelined); the splitter rule replaces only what the stray period supplied; no new export; pure functions, fully testable |
| 2 | Collapse `..` in the splitter or at the TTS route | Hides the symptom; cannot tell a deliberate `...` from a doubled mark (`Wait....`); leaves `?.`, `!.` and `".`; the route is a server edit |
| 3 | Replace the break with a newline | Relies on how Piper treats a newline, which nothing here measures |
| 4 | Drop the marker | Headings and list items lose their pause |

**D2b. The splitter's closing-quote rule.**

| # | Option | Judgement |
|---|---|---|
| 1 | Cut after `[.!?]+` and closers only when whitespace and then a capital letter or a digit follow (`\p{Lu}`, `\p{N}`, optional opening quote or bracket before them) (chosen) | Keeps `"Stop!" he said.` in one chunk (measured: unchanged), cuts `done." Next` and `log.) Next`; the build targets ES2020 (`ui/tsconfig.json`), which has `\p{...}` with the `u` flag. **A2:** the expression is written with one terminal mark, `[.!?]`, not a run: the cut lands at the same place (after the run's last mark; 1,000,000 random strings give the same output as the quantified form, section 15) and a run of marks is not rescanned from every mark (R1-3) |
| 2 | Cut after every closer | Splits dialogue with an attribution |
| 3 | Do not change the splitter | The paragraph-ends-a-chunk property fails for the quote and bracket variants the acceptance names |

**D3. How S2 stops the history being spoken.**

| # | Option | Judgement |
|---|---|---|
| 1 | The shared ledger records the first landed load per scope (`SpeechScope.loaded`); that load is seeded whatever triggered it; the trigger row still speaks through the live-id set (chosen) | Independent of how the first landed load became a trigger load (the two paths of item 6, or another); module-scoped like the claims, so a remount cannot make a later push-triggered load a "first" (BF-765's lesson); one function and one line in the component; keeps BF-718's tests |
| 2 | Keep first sight from being used on an empty list | Breaks BF-718's own case: a push as the first message of a per-agent buffer must be spoken, and for that scope nothing marks a load |
| 3 | A per-mount ref instead of the ledger | A remount makes the next push-triggered load a "first" and seeds a real arrival (BF-765) |
| 4 | Seed any row older than the page load or older than the trigger | A clock heuristic: it swallows a late push and speaks recent history |

**D4. How S3 anchors the mouth.**

| # | Option | Judgement |
|---|---|---|
| 1 | Consumers sample on the audio clock: a pure `mouthClockMs`, used by `CrewVRM`'s heuristic branch (chosen) | The rhubarb branch already works this way (BF-283), so both branches share one clock and the switch when late frames arrive does not jump; 0 until playing keeps the mouth closed (measured: `sample(0)` is all zeros); no event contract changes; one export in a module nothing mocks |
| 2 | Move the `start` event from `play` to `playing` in `voice.ts` | Changes the contract of every consumer (barge-in gate, modulation icon, PTT gate, head bob, meeting sequencer); the voice suites that emit only `play` pin the old order; `pause` before `playing` would end an utterance that never started (BF-655) |
| 3 | A new additive speech event (`playing`) and consumers re-anchor | The precedent exists (`dropped`, AD-1291), but nine consumers must be audited and `CrewVRM` needs a state machine; the result is the same as option 1 |
| 4 | A fixed offset | Not anchored: the latency varies |

**D5. Public text.** The issues quote a crew member's name, her words and a thread id of the live vessel, and #1667 asks that her message be the test fixture. **This overrides that line of the acceptance.** This repository is public and its tests, comments, tracker lines and commit messages must not hold vessel data: no crew name, no thread id, no live count and no live sentence appears in anything of this batch, this contract included (the live claims are referred to by issue number). The fixtures are synthetic and keep the shape of the defect: three paragraphs each ending in a period ("The survey finished early and the readings were stable." and two more), a question mark and an exclamation mark ending paragraphs, a closing quote (straight and typographic) and a closing bracket after the period, an ellipsis at a paragraph end, a decimal, a paragraph without sentence punctuation, trailing spaces and a run of blank lines. BF-928's fixture is synthetic history rows plus a synthetic greeting; BF-931's is a synthetic sentence. The rest of the acceptance (the stripped text and the chunks contain no doubled period, each paragraph ends a chunk) is kept whole.

**D6. How the M1 tests are held red.** The BF-937 pattern: `const built = process.env.BF9NN_RUNXFAIL === '1' ? it : it.fails;`, N2 sets it to `it`; a new export is read from the module namespace through a cast, so the file type-checks and loads before the export exists and its cases fail at the call. Alternatives: `it.skip` (proves nothing), `it.todo`, a failing assertion committed red (breaks the gate). `it.fails` is new to the repository's own tests but is proved by BF-937 on the oracle.

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. UI commands run **from `ui/`**, Python commands **from the repository root**, each exactly as typed. **Who runs what.** The Builder may run: the focused `npx vitest run ...` of G1, G2 and `npx tsc -b`, only where `ui/node_modules` exists (the reading tree has none; a Builder tree without it applies the blocks and stops, saying so); the Python of G3. The Builder never runs `npm install`, `npm ci`, `npm update`, `npm run build` (heavy), the whole `npm run test`, Playwright, or the broad gate. **Mine (the orchestrator's):** every UI command on the oracle with the main checkout's `node_modules`, `npm run build`, the mutation campaign, the wide consumer runs, the broad gate, the pull request and CI's `ui-tests` (`.github/workflows/ci.yml:122-163`: `npm ci`, `npm run test`, `npm run build`, Node 22).

**M0 (each slice, on the head before the slice):** run the slice's G2 vitest command and record `Test Files` and `Tests` (it passes on the base: the three existing suites named in section 6 are green).

| Slice | M | Blocks | Gate |
|---|---|---|---|
| S1 (BF-929) | M1 | N1-1 | G1 |
| S1 | M2 | P2-1 to P2-4, then N2-1 (the marker) | G2 |
| S1 | M3 | P3-1, P3-2, ledger | G3 |
| S2 (BF-928) | M1 | N1-1, N1-2 | G1 |
| S2 | M2 | P2-1, P2-2a, P2-2b, P2-3a, P2-3b, then N2-1 (the marker, new file), N2-2 (the marker, appended block) | G2 |
| S2 | M3 | P3-1, P3-2, ledger | G3 |
| S3 (BF-931) | M1 | N1-1, N1-2 | G1 |
| S3 | M2 | P2-1, P2-2, P2-3, then N2-1, N2-2 (the markers) | G2 |
| S3 | M3 | P3-1, P3-2, ledger | G3 |

**S1.**

- **G1.** `npx vitest run src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`. **Expected: `4 passed | 5 expected fail (9)`** (vitest's summary: the 5 are `it.fails` cases that failed as expected; the 4 are controls). Then `$env:BF929_RUNXFAIL='1'; npx vitest run src/audio/__tests__/voice.paragraphBreak.bf929.test.ts; Remove-Item Env:BF929_RUNXFAIL`: **expected 4 passed, 5 failed**, each failure at its own `expect` (the stripped text or the chunks), never at an import or a premise.
- **G2.** `npx vitest run src/audio` (every voice, chunking, lip-sync and meeting-voice suite: the consumers of both edited functions and of the audio clock). **Expected:** `Tests` = M0 + 9, 0 failed. Then `npx tsc -b` (type-checks the sources and the tests): clean.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. **The ledger covers BF numbers as well as AD numbers** (`scripts/gen_ad_ledger.py:113`, the token pattern; the head of a PROGRESS entry or a DECISIONS heading is read), so each M3 changes it by its own number. **Measured in memory on `54a112e2` with the three entries together** (the generator's own `render` over the committed snapshot and the trackers with the entries inserted; on the unchanged trackers it reproduces the committed report byte for byte): `docs/development/open-ads-report.md` changes in 5 hunks, 5 lines deleted and 5 inserted: the shipped BF count (`| shipped | 1008 | 610 | code in history |` becomes 613), the accounted BF list (`**BF** (610)` becomes `(613)`, with 928, 929 and 931 added to its ranges), the unaccounted BF list (`**BF** (342)` becomes `(339)` and `928-933` becomes `930, 932-933`), and the two skipped-line numbers of PROGRESS.md (`:1606` and `:1612` become `:1618` and `:1624`: the 12 lines of three entries of 4 lines each). One slice alone moves one BF in each of the three counts and shifts those two numbers by its own 4 lines. The non-check run also rewrites `docs/development/ad-ledger-snapshot.json` (its git layer is collected live from the commit subjects, so it gains the batch's subjects; the report is rendered from the pinned snapshot and does not depend on that). After BF-937's merge the figures above move by BF-937's own entry: the oracle re-measures, and **any changed row of another number is a hard stop**. **A1, measured on the oracle over `f614a31d`** (the contract commit's subject names BF-928, BF-929 and BF-931, and the generator reads commit subjects): S1 M3's regeneration moves all three numbers at once (the shipped BF count `611` becomes `614`, the accounted BF list gains 928, 929 and 931, the unaccounted list loses them: `928-933` becomes `930, 932-933`), and S2 M3 and S3 M3 move no number. Every M3 also changes the report's git-log row (the pinned snapshot's time, head id and subject count) and shifts the two skipped-line numbers of PROGRESS.md by 4 (`:1614` and `:1620` become `:1618` and `:1624` at S1 M3, `:1622` and `:1628` at S2 M3, `:1626` and `:1632` at S3 M3), and the snapshot's git layer gains the subjects it had not seen. The report's numstat is `6 6` at S1 M3 (the git-log row, the three counts, the two skipped-line numbers) and `3 3` at S2 M3 and at S3 M3; the snapshot's is `12 3`, then `3 3`, then `3 3`. A comparison of every number list of the report before and after each M3 shows that no other number's row moved.

**S2.**

- **G1.** `npx vitest run src/components/profile/__tests__/speechLedgerLoaded.bf928.test.ts`: **expected `1 passed | 4 expected fail (5)`**; then with `$env:BF928_RUNXFAIL='1'` (and `Remove-Item Env:BF928_RUNXFAIL` after): **1 passed, 4 failed**, each at the call of `markScopeLoaded` ("markScopeLoaded is not exported by profileTranscript yet"). Then `npx vitest run src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx`: **expected: every pre-existing case passes, plus the 3 new ones: 2 pass, 1 expected fail** (the file's total is its M0 count + 3); with `BF928_RUNXFAIL=1`: the pre-existing cases pass, 2 new pass and 1 fails at `expect(spokenTexts()).toEqual(['A fresh greeting for this call.'])` (received: the two older rows and the greeting).
- **G2.** `npx vitest run src/components/profile src/__tests__/ProfileChatTab src/__tests__/AgentProfilePanel src/__tests__/ProfileChatTabVoice.test.tsx src/__tests__/voiceE2E.smoke.test.tsx src/audio/__tests__/voice.balancedEnd.test.tsx` (every suite that mounts `ProfileChatTab` or scans its source, including the seven `?raw` readers of section 11). **Expected:** `Tests` = M0 + 8, 0 failed. Then `npx tsc -b`: clean.
- **G3.** As S1's, including its measured diff. **A1:** this slice moves no number (S1 M3 already moved BF-928, BF-929 and BF-931, because the contract commit's subject names them); its report diff is the git-log row and the two skipped-line numbers, which shift by its entry's 4 lines.

- **G1.** `npx vitest run src/audio/__tests__/lipSyncTrack.mouthClock.bf931.test.ts`: **expected `1 passed | 5 expected fail (6)`**; with `$env:BF931_RUNXFAIL='1'`: 1 passed, 5 failed at the call of `mouthClockMs` ("mouthClockMs is not exported by lipSyncTrack yet"). Then `npx vitest run src/__tests__/CrewVRM.mouthClock.bf931.test.tsx`: **expected `1 passed | 2 expected fail (3)`**; with `BF931_RUNXFAIL=1`: 1 passed, 2 failed at `expect(mouth(model.mesh), ...).toBe(0)` (the message: the mouth moved 100 ms after `play()` and before `playing`) and at `expect(mouth(model.mesh)).toBeGreaterThan(0)` (the mouth did not follow the audio clock).
- **G2.** `npx vitest run src/audio src/__tests__/CrewVRM src/__tests__/ParametricAvatar.test.tsx src/components/profile/__tests__/MeetingView src/__tests__/CrewAvatarPopout` (the lip-sync suites, the two existing `CrewVRM` suites, and the suites that mock `CrewVRM`). **Expected:** `Tests` = M0 + 9 (6 + 3), 0 failed; record M0 on the branch head, which already holds S1's and S2's cases. Then `npx tsc -b`: clean.
- **G3.** As S1's, including its measured diff. **A1:** this slice moves no number either (see S2's G3); its report diff is the git-log row and the two skipped-line numbers. After the Diff Reviewer's findings are repaired and the reviewed tree is committed locally (the broad gate stops on an untracked file under `ui/src/` and on a mutation backup file there, `scripts/run_test_gate.py:33-41`, `:69`, `:716-735`, `:795-804`: every new file is committed first, and a mutation campaign restores each file and removes any `.mutbak`, `.mut_bak` or `.mut.bak`): `npm run build` (from `ui/`; `tsc -b && vite build`: clean), the whole `npx vitest run` once on the oracle (CI runs it again), the mutation rows of section 9, and `PY scripts/run_test_gate.py --label bf928-929-931 --receipt logs/gates/bf928-929-931.receipt.json` from the repository root (its preflight runs the ledger, architecture, seam and store checks; **it does not run the UI tests or the UI build**; no config or Python file changes, so its config checks are unaffected). **Harness rule.** No source change made to pass a test, no skip, no loosened assertion; a failing new case at G2, or any existing test failing, goes back to the Architect.

**R1 (amendment A2; after S3 M3).** R1-1 to R1-5 are S1's repair and R1-6 is S2's (section 7.4). **S1:** `npx vitest run src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`: **expected `10 passed (10)`** (every case is an ordinary case after M2; C5 is the tenth). The repaired test file run against the source before R1-1 gives `9 passed | 1 failed` with the failure at `expect(elapsed).toBeLessThan(250)` (measured: about 1.2 s for the run of spaces, so C5 does discriminate). `npx vitest run src/audio`: **expected `Tests` = the count at S3 M3's head + 1** (measured 307, then 308), 0 failed; `npx tsc -b` clean. **S2:** `npx vitest run src/components/profile/__tests__/speechLedgerLoaded.bf928.test.ts src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx`: **expected `5 passed (5)` and `30 passed (30)`**; the S2 G2 command's count is unchanged by R1-6 (831; it adds no case); and S3's G2 count is the S3 M3 count + 1 (390, then 391: it includes `src/audio`). No Python test, no config and no generated artifact: the ledger pair is not regenerated (no tracker entry head changes; `gen_ad_ledger.py --check` stays current). **The orchestrator's gates after R1:** `npm run build`, the whole `npx vitest run` (**with `--maxWorkers=8` on a loaded host**: with the default worker count (one per logical CPU) two or three files that start real Python or wait on timers timed out under load and passed alone, section 15), the mutation rows of section 9 (S1 rows 1 to 9, S2 rows 1 to 6, S3 rows 1 to 6), and the broad gate with the label `bf928-929-931`.

## 5. Commit messages

- **S1 M1:** `BF-929 M1: tests for a paragraph break adding no pause marker after a finished sentence, xfail until built (#1667)`
- **S1 M2:** `BF-929 M2: a paragraph break adds a period only when the paragraph does not already end a sentence, and the splitter cuts after a closing quote or bracket (#1667)`
- **S1 M3:** `BF-929 M3: trackers and ledger (#1667)`; its body ends with the line `Closes #1667.`
- **S2 M1:** `BF-928 M1: tests for the first transcript load of a scope being history whatever triggered it, xfail until built (#1666)`
- **S2 M2:** `BF-928 M2: the ledger records the first load that lands per scope and the transcript speaker seeds it whatever triggered it (#1666)`
- **S2 M3:** `BF-928 M3: trackers and ledger (#1666)`; its body ends with the line `Closes #1666.`
- **S3 M1:** `BF-931 M1: tests for the avatar mouth following the audio clock, xfail until built (#1669)`
- **S3 M2:** `BF-931 M2: the heuristic mouth track is sampled on the audio clock, so it stays closed until the voice plays (#1669)`
- **S3 M3:** `BF-931 M3: trackers and ledger (#1669)`; its body ends with the line `Closes #1669.`

Each issue has exactly one slice, so each M3 is the last slice of its issue and closes it. The pull request body lists the three `Closes` lines and the three live checks of the last section as post-merge actions. No message names a crew member, a thread or a live figure.

## 6. Tests

### S1 (`ui/src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| B1 | 1 | three paragraphs ending in periods: the stripped text is the three joined by one space, has no `..`, and the chunks are exactly the three paragraphs | M2 |
| B2 | 1 | `?` and `!` at a paragraph end gain no period; chunks are the three | M2 |
| B3 | 1 | a closing quote (straight and typographic) and a closing bracket after the period gain no period, and each paragraph still ends a chunk | M2 |
| B4 | 1 | an ellipsis at a paragraph end stays three dots | M2 |
| B5 | 1 | trailing spaces and a run of blank lines are one pause; no chunk is a lone period | M2 |
| C1-C4 | 4 | controls: a paragraph without sentence punctuation still gets its period; a decimal and a number-ending paragraph; a single line break and a mid-sentence ellipsis; inline dialogue with a lowercase attribution is not cut | none |
| C5 | 1 | control (A2, added by R1-4): a run of 50,000 spaces and then of 50,000 tabs, between two words, is stripped in under 250 ms (the repaired expression takes under a millisecond; the one R1-1 repairs takes about 1.2 s for the run of spaces). It passes on the base and on the repaired tree and fails on the tree before R1-1 | none |

**How each xfail case fails on the base** (measured in memory on the unpatched functions): B1 at `expect(text).toBe(...)`, the base returns `...stable.. Two things ... surprise.. That is ...`; B2 returns `done?. Yes!. Good.`; B3 returns `"done.". The second note (see the log.). The last note.`; B4 returns `Wait.... It is fine.` (four dots); B5 returns `First note. . Second note`, whose chunks include a lone `.`.

**Existing tests that pin the old behaviour (enumerated by command, section 11).** `ui/src/audio/__tests__/voice.test.ts:78-91` is the only test that calls the real `stripMarkdownForSpeech`; its input holds one paragraph break (`...[link](http://x)\n\nnew para`) and its assertions are `toContain` fragments (`Bold and italic`, `Heading`, `bullet`, `code`, `link`) and two `not.toContain`: none reads the join, so it **does not pin the old behaviour and needs no update**. `ui/src/audio/__tests__/voiceChunking.test.ts:7-83` pins the splitter on inputs with no closing quote or bracket before the whitespace (`Dr. Smith went home. He was tired.`, `Wait... what?`, `Really?! Yes.`, and the others): the new rule does not change any of them (measured: all eight inputs unchanged). 29 test files mock `stripMarkdownForSpeech` as an identity inside a `vi.mock('.../audio/voice')` factory (45 files mock that module in all); none of them reaches the changed lines. No test or Playwright spec asserts a doubled period (`'..'`, `".."` or a letter followed by `.. ` and a letter) and none under `ui/e2e` names `stripMarkdownForSpeech`, `splitIntoSentences` or `speakResponse`. **No test pins a defect here; no existing test is edited.**

### S2 (`ui/src/components/profile/__tests__/speechLedgerLoaded.bf928.test.ts`, and three cases appended to `ProfileChatTab.bf718.test.tsx`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| L1-L4 | 4 | the ledger records the first load: true then false for one scope; scopes apart; independent of `markScopeSeen`; a scope evicted at the bound reads as first again | M2 |
| LC | 1 | control: first sight is true once, then false (`markScopeSeen` unchanged) | none |
| T1 | 1 | **the seam:** the open-time transcript request hangs and fails; the greeting's append arrives meanwhile (coalesced); the retry that carries it is the first load that lands: only the greeting is spoken | M2 |
| T2 | 1 | control: after a first load, one later push-triggered load with two new rows speaks both (the load is not seeded) | none |
| T3 | 1 | control: a reconnect repair that is the first load that lands speaks nothing | none |

**A2 (isolation of the appended block).** The describe that holds T1 to T3 resets four live-frame fields of the store, `liveThreadRefresh`, `liveRepairEpoch`, `liveDropCount` and `liveDrops`, to the store's initial values before and after every case (R1-6). A1 reset only the first; a state diff per case (section 15) found that T1 and T3 also leave the repair epoch and the drop count and log changed, and a raised epoch makes the next mount repair its transcript once more.

**How each xfail case fails on the base.** L1 to L4 at the call of `markScopeLoaded` (not exported yet), which `it.fails` takes as the expected failure. T1 at `expect(spokenTexts()).toEqual(['A fresh greeting for this call.'])`: the base speaks the two older rows and then the greeting. T2 and T3 pass on the base (they pin what must not change): T2 is what kills the mutant "every load is a first load" (section 9), T3 is the issue's "also cover a reconnect repair".

**Existing tests that pin the old behaviour (enumerated by command, section 11).** The seeding rule is read by: `ProfileChatTab.threadTranscript.test.tsx` (18 lines naming `admitMessages`, `markScopeSeen` or the seed refs, all on `createSpeechLedger()` ledgers: pure, none touches `refreshThreadTranscript`; and its `?raw` scans of `ProfileChatTab.tsx` and `profileTranscript.ts` assert `repairThreadMessages(targetThreadId)`, `threadDtoToMessage(message, current.agents)`, `message.id === triggerMessageId`, `currentOwner.threadId !== targetThreadId`, `current.liveGeneration !== generation`, the absence of `current.liveSequence !== sequence`, the call-bar lines `showCallMenu = ...`, `getOrCreateAgentThread(agentId)`, `setMeetingActive(tid, true)`, `if (video) void startCameraStream()` and an emoji ban: **none is a line this slice edits, and the new lines add no emoji**); `speechLedgerLifetime.test.ts` (`markScopeSeen`, `claimSpeech`, scope bounds: it reads `scope.seen` and `scope.keys.size` one field at a time, so a new field changes nothing it reads); `ProfileChatTab.bf718.test.tsx` (the BF-718 and BF-765 cases, all of which hydrate by an untriggered load first, or push during a seeding load); `ProfileChatTab.groupReplyIdentity.test.tsx` (reads `sharedSpeechLedger().scopes.get(THREAD_ID)?.keys`). **No test compares a whole scope record or a whole ledger dump** (a dump that hashed the record would go stale without naming the field): `.scopes.get(...)` is read in five places and each reads `keys` (`ProfileChatTab.bf718.test.tsx:751`, `ProfileChatTab.groupReplyIdentity.test.tsx:629`, `:637`, `:648`, `ProfileChatTab.threadTranscript.test.tsx:317`), and `speechLedgerLifetime.test.ts:129-131` iterates `ledger.scopes` reading `seen` and `keys.size`; the only literal that builds a scope record is `profileTranscript.ts:305`. Nothing pins a defect; no existing test is edited but the append to `ProfileChatTab.bf718.test.tsx`.

### S3 (`ui/src/audio/__tests__/lipSyncTrack.mouthClock.bf931.test.ts`, `ui/src/__tests__/CrewVRM.mouthClock.bf931.test.tsx`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| K1 | 1 | control (premise): a heuristic track is all zeros at 0 and before it, and not at 200 ms | none |
| K2-K6 | 5 | `mouthClockMs`: wall clock when no server audio is active; 0 while the audio exists but has not started, whatever the wall clock says; the audio time once it plays; a non-finite or negative audio time counts as not started; the defect in numbers (closed where the wall clock opened it) | M2 |
| V1 | 1 | **the seam:** real `voice.ts` and a fake `<audio>` that fires `play` at once and `playing` later (due 300 ms after `play()`, the issue's own example), a mounted `CrewVRM` with a captured frame loop: at 100, 200 and 299 ms of wall time after `play()`, before `playing`, the mouth is closed at every frame | M2 |
| V2 | 1 | the seam: the audio plays late (400 ms of wall time) and has reached 40 ms: the mouth follows the audio time (open), where the wall clock would read a closed instant | M2 |
| V3 | 1 | control: deferred frames that arrive after playback started are sampled on the audio time (the wall clock, 5 s on, would be past them) | none |

**How each xfail case fails on the base.** K2 to K6 at the call of `mouthClockMs` (not exported yet). V1: the base samples the heuristic track on the wall clock, `sample(100)` is not all zeros (measured: `oh 0.8`, `ih 0.05` for the fixture text), so the first frame moves the mouth and `expect(mouth(model.mesh), ...).toBe(0)` fails at 100 ms. V2: the base samples `sample(400)`, which is all zeros for the fixture text (measured), so the mouth stays 0 and `toBeGreaterThan(0)` fails. K1 and V3 pass on the base (V3 because the rhubarb branch already samples on `getActiveAudioTimeMs()`: the second half of #1669's acceptance is a control).

**Existing tests that pin the old behaviour (enumerated by command, section 11).** None reads the heuristic clock: no test mentions `getActiveAudioTimeMs`, `startedAtMsRef`, `_sampleRhubarbFrames` or `currentTrackRef`; `CrewVRM.realAudioFallback.test.tsx` calls `buildHeuristicTrack` directly and mounts `CrewVRM` with `useFrame` mocked to a no-op, and `lipSyncTrack.crewVRM.test.tsx` and `CrewVRM.expressionResting.test.tsx` exercise exported helpers; `lipSyncTrack*.test.ts` test `sample`, which is unchanged. 17 test files mock `CrewVRM` and none mocks `lipSyncTrack` (so the new export meets no mock factory). **No test pins a defect; no existing test is edited.**
## 7. The contract

Labels restart in each slice. Section 6 names the cases; this section gives every block. `PY`, the commands and who runs them are in section 4.

### 7.1 Slice S1 (BF-929, #1667: the paragraph break and the splitter)

#### S1 M1

**N1-1.** New file `ui/src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`:

```ts
/** BF-929 (#1667): a paragraph break adds a pause marker only when the paragraph does not already end a sentence.
 *
 * The defect: `stripMarkdownForSpeech` turned every paragraph break into '. ', so a paragraph that already ended
 * in a period became 'end.. Next', the sentence splitter cut after the second period and Piper read the doubled
 * period aloud as "dot". '?' gave '?.', '!' gave '!.', a closing quote gave '.".', an ellipsis gave four dots,
 * and a blank line with trailing spaces made a chunk of a lone period.
 *
 * The fixtures are synthetic. They keep the shape of the defect (paragraphs that end in a period, a second
 * paragraph, a closing-quote or bracket variant, '?' and '!', an ellipsis, a decimal) and carry no text from the
 * live call that found it: this repository is public and its tests hold no vessel data.
 *
 * The cases the unfixed tree fails are `built`, which is `it.fails` until BF-929 M2 sets it to `it`; with
 * BF929_RUNXFAIL=1 they run as ordinary cases, so each can be seen to stop at its own assertion. Each case runs the
 * chain the call runs: the text passed to `speakResponse` is `stripMarkdownForSpeech(...)`, and with sentence
 * pipelining on, `voice.ts` cuts it with `splitIntoSentences`.
 */
import { describe, it, expect } from 'vitest';
import { splitIntoSentences } from '../voiceChunking';

const built = process.env.BF929_RUNXFAIL === '1' ? it : it.fails;

/** What the call speaks and what Piper receives: the stripped text, and its sentence chunks. */
async function spoken(text: string): Promise<{ text: string; chunks: string[] }> {
  const { stripMarkdownForSpeech } = await import('../voice');
  const stripped = stripMarkdownForSpeech(text);
  return { text: stripped, chunks: splitIntoSentences(stripped) };
}

const P1 = 'The survey finished early and the readings were stable.';
const P2 = 'Two things changed after the second pass, and neither was a surprise.';
const P3 = 'That is all for now, so rest well.';

describe('BF-929: a paragraph break after a finished sentence adds no period', () => {
  built('keeps one period at the end of each paragraph, none doubled, and each paragraph ends a chunk', async () => {
    const { text, chunks } = await spoken([P1, P2, P3].join('\n\n'));
    expect(text).toBe(`${P1} ${P2} ${P3}`);
    expect(text).not.toContain('..');
    expect(chunks).toEqual([P1, P2, P3]);
  });

  built('does the same after a question mark and an exclamation mark', async () => {
    const { text, chunks } = await spoken('Is the survey done?\n\nYes!\n\nGood.');
    expect(text).toBe('Is the survey done? Yes! Good.');
    expect(chunks).toEqual(['Is the survey done?', 'Yes!', 'Good.']);
  });

  built('adds no period after a closing quote or bracket, and the paragraph still ends a chunk', async () => {
    const straight = await spoken('She called it "done."\n\nThe second note (see the log.)\n\nThe last note.');
    expect(straight.text).toBe('She called it "done." The second note (see the log.) The last note.');
    expect(straight.chunks).toEqual(['She called it "done."', 'The second note (see the log.)', 'The last note.']);
    const typographic = await spoken('She wrote \u201cdone.\u201d\n\nThe next line.');
    expect(typographic.text).toBe('She wrote \u201cdone.\u201d The next line.');
    expect(typographic.chunks).toEqual(['She wrote \u201cdone.\u201d', 'The next line.']);
  });

  built('keeps an ellipsis at the end of a paragraph at three dots', async () => {
    const { text, chunks } = await spoken('Wait...\n\nIt is fine.');
    expect(text).toBe('Wait... It is fine.');
    expect(chunks).toEqual(['Wait...', 'It is fine.']);
  });

  built('treats trailing spaces and a run of blank lines as one pause, and never makes a chunk of a lone period', async () => {
    const { text, chunks } = await spoken('First note. \n\n\n\nSecond note');
    expect(text).toBe('First note. Second note');
    expect(chunks).toEqual(['First note.', 'Second note']);
  });
});

describe('BF-929: what must not change', () => {
  it('still marks a paragraph that has no sentence punctuation with a pause', async () => {
    const { text, chunks } = await spoken('Status\n\nThe readings are stable.');
    expect(text).toBe('Status. The readings are stable.');
    expect(chunks).toEqual(['Status.', 'The readings are stable.']);
  });

  it('leaves a decimal alone, and still pauses after a paragraph that ends in a number', async () => {
    const { text, chunks } = await spoken('The ratio was 0.7312 on the second pass\n\nIt held at 0.7312');
    expect(text).toBe('The ratio was 0.7312 on the second pass. It held at 0.7312');
    expect(chunks).toEqual(['The ratio was 0.7312 on the second pass.', 'It held at 0.7312']);
  });

  it('leaves a single line break and an ellipsis inside a sentence alone', async () => {
    expect((await spoken('One line.\nThe next line.')).text).toBe('One line.\nThe next line.');
    expect((await spoken('Wait... what is that')).text).toBe('Wait... what is that');
  });

  it('does not cut after a closing quote when a lowercase word follows it', () => {
    expect(splitIntoSentences('He shouted "Stop!" and left. Then "Go." she said.')).toEqual([
      'He shouted "Stop!" and left.',
      'Then "Go." she said.',
    ]);
  });
});
```

#### S1 M2

**P2-1.** `ui/src/audio/voice.ts`. The doc comment and signature of the function (once; both lines ASCII).
SEARCH:
```
/** AD-718: Strip markdown formatting for cleaner TTS playback. */
export function stripMarkdownForSpeech(text: string): string {
```
REPLACE:
```
/** AD-718: Strip markdown formatting for cleaner TTS playback.
 *
 *  BF-929 (#1667): a paragraph break is a pause, and the text marks it with a period, but only when the
 *  paragraph does not already end a sentence. A paragraph that ends in ``.``, ``!`` or ``?`` (optionally
 *  followed by closing quotes or brackets) keeps its own mark and gets one space: the unconditional period
 *  made ``end.`` into ``end..``, which Piper reads aloud as "dot" (and ``?`` into ``?.``). Trailing spaces
 *  before the break and a run of blank lines are one pause. An ellipsis and a decimal are left as they are. */
export function stripMarkdownForSpeech(text: string): string {
```

**P2-2.** `ui/src/audio/voice.ts`. The paragraph rule, with the `.trim()` after it as the anchor (once). The function keeps its name, its signature and its single export; nothing is added to the module's exports.
SEARCH:
```
    .replace(/\n{2,}/g, '. ')
    .trim();
```
REPLACE:
```
    .replace(/([.!?]["')\]}\u201d\u2019\u00bb]*)?[ \t]*\n{2,}/g, (_whole: string, end?: string) => (end ? `${end} ` : '. '))
    .trim();
```

**P2-3.** `ui/src/audio/voiceChunking.ts`. The doc line of the heuristic (once; the neighbouring line 30 holds a non-ASCII character and is not in the SEARCH).
SEARCH:
```
 *   - split on sentence-final punctuation ``[.!?]`` followed by whitespace,
```
REPLACE:
```
 *   - split on sentence-final punctuation ``[.!?]`` followed by whitespace,
 *   - (BF-929) also split after that punctuation plus closing quotes or brackets
 *     when whitespace and then a capital letter or a digit follow, so
 *     ``He said "done." Next.`` splits and ``"Stop!" he said.`` does not,
```

**P2-4.** `ui/src/audio/voiceChunking.ts`. The second cut, after the first (once).
SEARCH:
```
    // Insert a split sentinel after terminal punctuation + whitespace.
    .replace(/([.!?]+)\s+/g, `$1${_SPLIT}`)
```
REPLACE:
```
    // Insert a split sentinel after terminal punctuation + whitespace.
    .replace(/([.!?]+)\s+/g, `$1${_SPLIT}`)
    // BF-929: and after terminal punctuation that closing quotes or brackets follow, when the next word starts a sentence.
    .replace(/([.!?]+["')\]}\u201d\u2019\u00bb]+)\s+(?=["'(\[{\u201c\u2018\u00ab]*[\p{Lu}\p{N}])/gu, `$1${_SPLIT}`)
```

**N2-1.** `ui/src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`. The marker, removed: every `built` is now `it`.
SEARCH:
```
const built = process.env.BF929_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once on `54a112e2`; BF-936's entry follows it today and BF-937's will too; the SEARCH is unchanged by both). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-929 (DATE), #1667 -- a spoken reply no longer says "dot" at the end of a paragraph.**
- **Base.** `stripMarkdownForSpeech` (`ui/src/audio/voice.ts`) turned every paragraph break into a period and a space, so a paragraph that already ended in a period became `end..`; the sentence splitter (`ui/src/audio/voiceChunking.ts`) cut after the second period and Piper read the doubled mark aloud. The same gave `?.` and `!.`, `."` became `.".`, an ellipsis at a paragraph end gained a fourth dot, and a blank line with trailing spaces made a chunk of a lone period.
- **Fix.** A paragraph break adds the period only when the paragraph does not already end in `.`, `!` or `?` (optionally followed by closing quotes or brackets); otherwise it is one space. Trailing spaces and a run of blank lines are one pause; an ellipsis, a decimal and a paragraph without sentence punctuation behave as before. The splitter also cuts after sentence punctuation plus closing quotes or brackets when whitespace and then a capital letter or a digit follow, so each paragraph still ends a chunk (`"Stop!" he said.` is not cut). No export is added to `voice.ts`. The tests use synthetic text only. Contract `prompts/bf-928-929-931-voice-call-ui.md`, slice S1. Closes #1667.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows the BF entries (once on `54a112e2`, at line 1694; BF-936's entry sits before it, BF-937's will be inserted before it, and each entry of this batch is inserted before it as well, so the order is the order of landing). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-929 -- A paragraph break adds a pause marker only when the paragraph does not already end a sentence (DATE, #1667)

- *Scope.* `ui/src/audio/voice.ts` (`stripMarkdownForSpeech`: its body and its comment; no export added, so the wave-close mock-parity check is unchanged), `ui/src/audio/voiceChunking.ts` (`splitIntoSentences`), one new test file. Contract `prompts/bf-928-929-931-voice-call-ui.md`.
- *G1 (where).* The cause is fixed in the stripper, which serves the single-call path and the pipelined path alike, and the splitter learns the one boundary the stripper's stray period used to supply (a closing quote or bracket). Rejected: collapsing `..` in the splitter or at the TTS route (it hides the symptom, cannot tell `..` from a deliberate `...`, leaves `?.` and `".`, and the route is a server edit); replacing the break with a newline (it relies on how the synthesizer treats one, unmeasured); dropping the marker (headings and list items lose their pause).
- *G2 (the quote rule).* The splitter cuts after sentence punctuation and closers only when a capital letter or a digit follows, so inline dialogue with an attribution is not cut. Rejected: cutting after every closer.
- *G3 (the fixtures).* Synthetic text only: no crew member's name, thread or live figure is in any test, comment, tracker line or commit message of the batch; this overrides the line of the issue that asked for the live message as the fixture.
- *Residual.* L1 to L5 of the contract (S1). *Reversal.* Revert the BF-929 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.2 Slice S2 (BF-928, #1666: the first load of a scope is history)

#### S2 M1

**N1-1.** New file `ui/src/components/profile/__tests__/speechLedgerLoaded.bf928.test.ts`:

```ts
/** BF-928 (#1666): the first transcript load of a scope in a browser session is history, whatever triggered it.
 *
 * `markScopeLoaded` is the shared ledger's record of that: it answers true once per scope (the first load that
 * lands) and false after. It is separate from `markScopeSeen`, which the speech effect uses up the first time it
 * SEES a scope, when the list is usually still empty because the transcript loads asynchronously.
 *
 * The function is read from the module namespace, through a cast, so that this file type-checks and loads before
 * it exists; the cases that need it are `built`, which is `it.fails` until BF-928 M2 sets it to `it`. With
 * BF928_RUNXFAIL=1 they run as ordinary cases and each stops at the call. Synthetic scope names only.
 */
import { describe, it, expect } from 'vitest';
import * as transcript from '../profileTranscript';
import {
  SPEECH_LEDGER_SCOPE_CAP, createSpeechLedger, markScopeSeen, type SpeechLedger,
} from '../profileTranscript';

const built = process.env.BF928_RUNXFAIL === '1' ? it : it.fails;

function markScopeLoaded(ledger: SpeechLedger, scopeKey: string): boolean {
  const fn = (transcript as unknown as {
    markScopeLoaded?: (ledger: SpeechLedger, scopeKey: string) => boolean;
  }).markScopeLoaded;
  if (fn === undefined) throw new Error('markScopeLoaded is not exported by profileTranscript yet');
  return fn(ledger, scopeKey);
}

describe('BF-928: the ledger records the first load that lands for a scope', () => {
  built('answers true for the first load of a scope and false after', () => {
    const ledger = createSpeechLedger();
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(false);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(false);
  });

  built('keeps scopes apart', () => {
    const ledger = createSpeechLedger();
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-b')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(false);
  });

  built('is independent of marking the scope seen, in either order', () => {
    const ledger = createSpeechLedger();
    expect(markScopeSeen(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-b')).toBe(true);
    expect(markScopeSeen(ledger, 'thread-b')).toBe(true);
  });

  built('forgets a scope that is evicted at the bound, which then reads as first again', () => {
    const ledger = createSpeechLedger();
    expect(markScopeLoaded(ledger, 'old')).toBe(true);
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP; i += 1) markScopeLoaded(ledger, `filler-${i}`);
    expect(ledger.scopes.has('old')).toBe(false);
    expect(markScopeLoaded(ledger, 'old')).toBe(true);
  });

  it('leaves first sight as it was: true once, then false', () => {
    const ledger = createSpeechLedger();
    expect(markScopeSeen(ledger, 'thread-a')).toBe(true);
    expect(markScopeSeen(ledger, 'thread-a')).toBe(false);
  });
});
```

**N1-2.** `ui/src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx`. The mounted seam: three cases appended after the last describe, which this file's harness serves (`seed`, `mount`, `serverMsg`, `spokenTexts`, the network stub). The SEARCH is the last three lines of the file (once; ASCII); nothing else of the file changes.
SEARCH:
```
    expect(scope!.keys.size).toBeGreaterThan(0);
  });
});
```
REPLACE:
```
    expect(scope!.keys.size).toBeGreaterThan(0);
  });
});

/** BF-928 (#1666): the first transcript load of a scope is history, whatever triggered it. The cases the unfixed
 *  tree fails are `built`, which is `it.fails` until BF-928 M2 sets it to `it`; with BF928_RUNXFAIL=1 they run as
 *  ordinary cases. The text is synthetic: no crew member's name, thread or live figure. */
const built = process.env.BF928_RUNXFAIL === '1' ? it : it.fails;
const THREAD_MESSAGES_URL = /\/api\/threads\/[^/?]+\/messages\?limit=200$/;

/** The thread's first transcript request (the open-time load) hangs until `release()` and then fails with a 503,
 *  as it does when the vessel has only just restarted; every later request goes to the harness's own network. */
function failTheFirstTranscriptRequest(): { release: () => void; held: () => boolean } {
  const harnessFetch = globalThis.fetch;
  let release: (() => void) | null = null;
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    if (release === null && THREAD_MESSAGES_URL.test(String(input)) && (init?.method ?? 'GET') === 'GET') {
      return new Promise<Response>((resolve) => {
        release = () => resolve({ ok: false, status: 503 } as Response);
      });
    }
    return harnessFetch(input, init);
  }));
  return { release: () => { release?.(); }, held: () => release !== null };
}

describe('BF-928 -- the first transcript load of a scope is history, whatever triggered it', () => {
  beforeEach(() => {
    // The store outlives a case: the refresh command an earlier case left (T1's greeting) would be replayed by the
    // next case's mount and, naming a row that case's server does not hold, would keep its load from landing (A1).
    useStore.setState({ liveThreadRefresh: null });
  });

  built('speaks only the greeting when the first load that lands is the one its append triggered', async () => {
    serverMessages = [
      serverMsg('h1', 'An older reply about the survey.'),
      serverMsg('h2', 'Another older reply about the readings.'),
      serverMsg('g1', 'A fresh greeting for this call.'),
    ];
    seed({ tts: true });
    const request = failTheFirstTranscriptRequest();
    await act(async () => {
      render(<ProfileChatTab agentId={AGENT_ID} />);
      await Promise.resolve();
    });
    expect(request.held(), 'premise: the open-time load is in flight').toBe(true);

    // The greeting's append arrives while that load is in flight, so its refresh is coalesced behind it...
    await act(async () => {
      useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: 'g1' } });
      await Promise.resolve();
    });
    // ...the open-time load fails, and the retry that carries the trigger is the first load that lands.
    await act(async () => {
      request.release();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(spokenTexts()).toContain('A fresh greeting for this call.');
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).toEqual(['A fresh greeting for this call.']);
    const scope = sharedSpeechLedger().scopes.get(THREAD_ID) as unknown as { loaded?: boolean } | undefined;
    expect(scope?.loaded, 'the thread scope records its first load').toBe(true);
  });

  it('still speaks every unclaimed row of a later load that a push triggered', async () => {
    seed({ tts: true });
    await mount();

    serverMessages.push(
      serverMsg('n1', 'The first of two new replies.'),
      serverMsg('n2', 'The second of two new replies.'),
    );
    await act(async () => {
      useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: 'n2' } });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(spokenTexts()).toContain('The second of two new replies.');
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).toEqual(['The first of two new replies.', 'The second of two new replies.']);
  });

  it('speaks nothing when a reconnect repair is the first load that lands', async () => {
    serverMessages = [serverMsg('h1', 'An older reply about the survey.')];
    seed({ tts: true });
    const request = failTheFirstTranscriptRequest();
    await act(async () => {
      render(<ProfileChatTab agentId={AGENT_ID} />);
      await Promise.resolve();
    });
    expect(request.held(), 'premise: the open-time load is in flight').toBe(true);

    await act(async () => {
      useStore.setState({ liveRepairEpoch: useStore.getState().liveRepairEpoch + 1 });
      await Promise.resolve();
    });
    await act(async () => {
      request.release();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(useStore.getState().threadMessages.has(THREAD_ID)).toBe(true);
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).toEqual([]);
  });
});
```

#### S2 M2

**P2-1.** `ui/src/components/profile/speechLedgerStore.ts`. The scope record gets its third field (once; ASCII; the file stays importless).
SEARCH:
```
export interface SpeechScope {
  keys: Set<string>;
  seen: boolean;
}
```
REPLACE:
```
export interface SpeechScope {
  keys: Set<string>;
  seen: boolean;
  /** BF-928 (#1666): has a transcript load landed for this scope in this session? Set by the first load that
   *  lands (`markScopeLoaded`), whatever triggered it, and evicted with the scope like the other two fields. The
   *  first load of a scope is history and is seeded, because `seen` is usually used up on an empty list first. */
  loaded: boolean;
}
```

**P2-2a.** `ui/src/components/profile/profileTranscript.ts`. A new record starts not loaded (once).
SEARCH:
```
    scope = { keys: new Set<string>(), seen: false };
```
REPLACE:
```
    scope = { keys: new Set<string>(), seen: false, loaded: false };
```

**P2-2b.** `ui/src/components/profile/profileTranscript.ts`. The function, after `markScopeSeen` (once).
SEARCH:
```
  const first = !scope.seen;
  scope.seen = true;
  return first;
}
```
REPLACE:
```
  const first = !scope.seen;
  scope.seen = true;
  return first;
}

/** BF-928 (#1666): has a transcript load landed for this scope before? Marks it as loaded and answers true only
 *  for the first load that lands, whatever triggered it. The speech owner seeds that load (records its rows without
 *  speaking them), because it is the scope's history arriving at once: ``markScopeSeen`` cannot say so, since the
 *  speech effect uses it up on its first run, when the list is still empty. A scope the ledger evicted reads as
 *  never loaded, as it reads as never seen (BF-768). */
export function markScopeLoaded(ledger: SpeechLedger, scopeKey: string): boolean {
  const scope = scopeRecord(ledger, scopeKey);
  const first = !scope.loaded;
  scope.loaded = true;
  return first;
}
```

**P2-3a.** `ui/src/components/profile/ProfileChatTab.tsx`. The import (once; one line).
SEARCH:
```
  sharedSpeechLedger, markScopeSeen,
```
REPLACE:
```
  sharedSpeechLedger, markScopeSeen, markScopeLoaded,
```

**P2-3b.** `ui/src/components/profile/ProfileChatTab.tsx`. The seed after a landed load (once). The five comment lines above it (`BF-718: a load with no trigger message ...`, one with a non-ASCII dash) are not in the SEARCH and stay; the new comment follows them and says what changed.
SEARCH:
```
      if (triggerMessageId === null) speechSeedScopesRef.current.add(targetThreadId);
```
REPLACE:
```
      // BF-928 (#1666): except that the first load that lands for a scope is history whatever triggered it. The
      // first-sight seed is used up on the empty list the effect sees before any transcript lands, and a load
      // that failed or was superseded never counted, so the first load that lands may be one a pushed message
      // triggered (a refresh coalesced behind an in-flight one takes the trigger id, `transcriptPendingRef`).
      // The trigger message is still spoken: its id is in `speechLiveIdsRef`, which `admitMessages` admits
      // while seeding. Marked first and unconditionally: the `||` below must not skip it.
      const firstLoadOfScope = markScopeLoaded(speechLedgerRef.current, speechScopeKey(targetThreadId, agentId));
      if (triggerMessageId === null || firstLoadOfScope) speechSeedScopesRef.current.add(targetThreadId);
```

**N2-1.** `ui/src/components/profile/__tests__/speechLedgerLoaded.bf928.test.ts`. The marker, removed.
SEARCH:
```
const built = process.env.BF928_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

**N2-2.** `ui/src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx`. The marker of the appended block, removed (the same line, once in this file).
SEARCH:
```
const built = process.env.BF928_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

#### S2 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once; S1's entry follows it after S1 M3 and this entry is inserted above it). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-928 (DATE), #1666 -- the first transcript load of a thread in a browser session is history, so a call no longer reads the thread's past messages aloud.**
- **Base.** The speech owner of a chat surface seeds a scope (records its rows without speaking them) on its first sight and after a load with no trigger message, and only then. After a hard reload the first sight happens while the list is still empty and is used up on nothing; if the first load that then lands is one a pushed message triggered (the open-time load failed or was superseded, and a refresh coalesced behind it took the trigger id), it was not seeded, and every historical row was admitted as a live arrival and spoken, oldest first.
- **Fix.** The shared speech ledger records, per scope, whether a transcript load has landed (`markScopeLoaded`); `refreshThreadTranscript` seeds the first load that lands whatever triggered it. The trigger message is still spoken (its id is in the live set), so a live reply is spoken once; a later push-triggered load is not seeded; a reconnect repair still seeds. Tests: a mounted seam test (the open-time load fails, the greeting's push triggers the next load, only the greeting is spoken), a control for two new replies in one later load, a control for a repair as the first load, and the ledger function's own cases. Synthetic text only. Contract `prompts/bf-928-929-931-voice-call-ui.md`, slice S2. Closes #1666.

```

**P3-2.** `DECISIONS.md`. The anchor is the same heading as S1's P3-2 (once; S1's entry sits before it after S1 M3, so this entry lands after it). Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-928 -- The first transcript load of a scope in a browser session is history, whatever triggered it (DATE, #1666)

- *Scope.* `ui/src/components/profile/speechLedgerStore.ts` (the `SpeechScope` record gains `loaded`; the module stays importless), `profileTranscript.ts` (`markScopeLoaded`), `ProfileChatTab.tsx` (`refreshThreadTranscript`: the seed line and the import), tests (a new file and three cases appended to the BF-718 suite). Contract `prompts/bf-928-929-931-voice-call-ui.md`.
- *G1 (the rule).* The ledger records the first landed load per scope and the speech owner seeds it whatever triggered it; the trigger row is still spoken through the live-id set. This holds however the first landed load became a trigger load (a failed or superseded open-time load, or a push coalesced behind it), which the issue's account and the code both allow and only the code was read. Rejected: keeping first sight from being used on an empty list (a push as the first message of a per-agent buffer must still be spoken, and nothing marks a load there); a per-mount ref (a remount would make the next push-triggered load a first, BF-765); seeding by age (a clock heuristic that swallows a late push).
- *G2 (the tests).* A mounted seam test over the real component and the BF-718 harness, controls that pin what must not change, and the ledger's own cases. Synthetic text only.
- *Residual.* L1 to L5 of the contract (S2). *Reversal.* Revert the BF-928 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3.
### 7.3 Slice S3 (BF-931, #1669: the mouth follows the voice)

#### S3 M1

**N1-1.** New file `ui/src/audio/__tests__/lipSyncTrack.mouthClock.bf931.test.ts`:

```ts
/** BF-931 (#1669): the heuristic mouth track is sampled on the clock the voice runs on.
 *
 * The speech 'start' event fires when `play()` is requested, not when sound begins, and the heuristic viseme track
 * (the avatar's schedule until the rhubarb frames arrive, BF-918) was sampled on a wall clock started at that
 * event, so the mouth led the voice by however long the audio took to start. `mouthClockMs(audioMs, wallMs)`
 * picks the clock: the audio element's time when server audio is active (0 until it plays, where the track is
 * closed), the wall clock otherwise (browser speech).
 *
 * The function is read from the module namespace, through a cast, so this file type-checks and loads before it
 * exists; the cases that need it are `built`, which is `it.fails` until BF-931 M2 sets it to `it`. With
 * BF931_RUNXFAIL=1 they run as ordinary cases and each stops at the call. The text is synthetic.
 */
import { describe, it, expect } from 'vitest';
import * as track from '../lipSyncTrack';
import { buildHeuristicTrack } from '../lipSyncTrack';

const built = process.env.BF931_RUNXFAIL === '1' ? it : it.fails;

function mouthClockMs(audioMs: number | null, wallMs: number): number {
  const fn = (track as unknown as {
    mouthClockMs?: (audioMs: number | null, wallMs: number) => number;
  }).mouthClockMs;
  if (fn === undefined) throw new Error('mouthClockMs is not exported by lipSyncTrack yet');
  return fn(audioMs, wallMs);
}

const TEXT = 'Okay, ready when you are.';
const CLOSED = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

describe('BF-931: the heuristic mouth is sampled on the voice clock', () => {
  it('premise: a heuristic track is closed at time zero and before it, and open 200 ms in', () => {
    const heuristic = buildHeuristicTrack(TEXT, { rate: 1 });
    expect(heuristic).not.toBeNull();
    expect(heuristic!.sample(0)).toEqual(CLOSED);
    expect(heuristic!.sample(-1)).toEqual(CLOSED);
    expect(heuristic!.sample(200)).not.toEqual(CLOSED);
  });

  built('runs on the wall clock when no server audio is active (browser speech)', () => {
    expect(mouthClockMs(null, 120)).toBe(120);
  });

  built('stays at the start while the audio exists but has not started, whatever the wall clock says', () => {
    expect(mouthClockMs(0, 200)).toBe(0);
    expect(mouthClockMs(0, 5000)).toBe(0);
  });

  built('follows the audio time once it plays, not the wall clock', () => {
    expect(mouthClockMs(40, 400)).toBe(40);
    expect(mouthClockMs(1250, 300)).toBe(1250);
  });

  built('counts a non-finite or negative audio time as not started', () => {
    expect(mouthClockMs(Number.NaN, 500)).toBe(0);
    expect(mouthClockMs(-5, 500)).toBe(0);
  });

  built('closes the mouth at the instant the wall clock opened it: the defect in numbers', () => {
    const heuristic = buildHeuristicTrack(TEXT, { rate: 1 })!;
    expect(heuristic.sample(mouthClockMs(0, 200))).toEqual(CLOSED);
    expect(heuristic.sample(200)).not.toEqual(CLOSED);
  });
});
```

**N1-2.** New file `ui/src/__tests__/CrewVRM.mouthClock.bf931.test.tsx`:

```tsx
/** BF-931 (#1669): with deferred visemes the avatar's mouth must not start before the voice is heard.
 *
 * The real `voice.ts` runs with a fake <audio> that fires 'play' as soon as `play()` is called, as a real element
 * does, and fires 'playing' only when the test says so, with `currentTime` at 0 until then. A mounted `CrewVRM`
 * hears the speech 'start' event from the real `voice.ts`. The VRM loader and the render loop are replaced: the
 * loader hands back a model whose face mesh carries the five mouth morphs, and the frame callback is captured and
 * stepped by hand with a controlled clock (the global `performance` is replaced for the case, as the BF-918 voice
 * suite does for its timing case; React's scheduler keeps the real one). The deferred visemes never arrive on their
 * own here (the lipsync request never answers), so the avatar runs on its heuristic track: the window the defect
 * lived in.
 *
 * The cases the unfixed tree fails are `built`, which is `it.fails` until BF-931 M2 sets it to `it`; with
 * BF931_RUNXFAIL=1 they run as ordinary cases. The third case is a control: frames that arrive after playback
 * started were already sampled on the audio time (BF-283). The text is synthetic.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import * as THREE from 'three';

const frameLoop = vi.hoisted(() => ({
  callbacks: [] as Array<(state: unknown, delta: number) => void>,
}));
const loaderControls = vi.hoisted(() => ({
  loads: [] as Array<{ url: string; success: (gltf: unknown) => void }>,
}));

vi.mock('@react-three/fiber', () => ({
  useFrame: (callback: (state: unknown, delta: number) => void) => { frameLoop.callbacks.push(callback); },
}));
vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    register(): this { return this; }
    load(url: string, success: (gltf: unknown) => void): void {
      loaderControls.loads.push({ url, success });
    }
  },
}));

import * as voice from '../audio/voice';
import { injectLipSyncFrames } from '../audio/useLipSyncCapture';
import { CrewVRM } from '../components/profile/CrewVRM';

const built = process.env.BF931_RUNXFAIL === '1' ? it : it.fails;
const AGENT_ID = 'bf931-agent';
const TEXT = 'Okay, ready when you are.';
const MOUTH_MORPHS = ['Fcl_MTH_A', 'Fcl_MTH_I', 'Fcl_MTH_U', 'Fcl_MTH_E', 'Fcl_MTH_O'];

let audios: FakeAudio[] = [];
let clock = 0;

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

/** An <audio> whose `play()` fires 'play' at once, as a real element's does, and whose 'playing' (and a
 *  `currentTime` above 0) comes later, when the test says so. */
class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  currentTime = 0;
  private listeners: Record<string, Array<() => void>> = {};
  pause = vi.fn(() => { this.emit('pause'); });
  play = vi.fn((): Promise<void> => { this.emit('play'); return Promise.resolve(); });
  removeAttribute = vi.fn();
  load = vi.fn();
  constructor(src: string) {
    this.src = src;
    audios.push(this);
  }
  addEventListener(event: string, listener: () => void): void {
    (this.listeners[event] ||= []).push(listener);
  }
  emit(event: string): void {
    for (const listener of this.listeners[event] ?? []) listener();
  }
}

function installNetwork(): void {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith('/api/avatars/tts/status')) {
      return { ok: true, json: async () => ({ enabled: true, backend: 'piper', sentence_pipelining_enabled: false }) };
    }
    if (url === '/api/avatars/tts') {
      return {
        ok: true,
        json: async () => ({
          backend: 'piper', audio_attachment_id: 'a'.repeat(64), mime: 'audio/wav',
          visemes: [], visemes_deferred: true, duration_ms: 0,
        }),
      };
    }
    if (url === '/api/avatars/lipsync') return new Promise<never>(() => {});
    return Response.json({ clips: [] });
  }));
}

function faceModel(): { mesh: THREE.Mesh; gltf: unknown } {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2), new THREE.MeshBasicMaterial());
  mesh.morphTargetDictionary = Object.fromEntries(MOUTH_MORPHS.map((name, index) => [name, index]));
  mesh.morphTargetInfluences = MOUTH_MORPHS.map(() => 0);
  const scene = new THREE.Group();
  scene.add(mesh);
  const vrm = { scene, meta: { metaVersion: '1' }, humanoid: null, expressionManager: null, update: vi.fn() };
  return { mesh, gltf: { scene, userData: { vrm } } };
}

const mouth = (mesh: THREE.Mesh): number => (mesh.morphTargetInfluences ?? []).reduce((sum, weight) => sum + weight, 0);

async function mountAvatar(): Promise<{ mesh: THREE.Mesh }> {
  const model = faceModel();
  render(
    <CrewVRM
      agentId={AGENT_ID}
      vrmUrl="/avatars/test.vrm"
      expressionOverrides={{}}
      signals={{ trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false }}
      onLoadError={vi.fn()}
    />,
  );
  expect(loaderControls.loads).toHaveLength(1);
  await act(async () => { loaderControls.loads[0]!.success(model.gltf); });
  return model;
}

/** The real voice.ts speaks TEXT for the avatar's agent: its 'start' event fires from the fake audio's 'play'. */
async function speak(): Promise<FakeAudio> {
  voice._resetTtsStatusForTests();
  voice.speakResponse(TEXT, undefined, AGENT_ID);
  await act(async () => { for (let i = 0; i < 60; i += 1) await Promise.resolve(); });
  expect(audios, 'premise: the reply was synthesized and its audio made').toHaveLength(1);
  expect(audios[0]!.play, 'premise: play() was requested').toHaveBeenCalledTimes(1);
  return audios[0]!;
}

function stepFrame(): void {
  const callback = frameLoop.callbacks[frameLoop.callbacks.length - 1];
  expect(callback, 'CrewVRM registered no frame callback').toBeDefined();
  callback!({}, 1 / 60);
}

beforeEach(() => {
  audios = [];
  frameLoop.callbacks = [];
  loaderControls.loads = [];
  clock = 1000;
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
  vi.stubGlobal('Audio', FakeAudio);
  vi.stubGlobal('speechSynthesis', {
    cancel: vi.fn(), speak: vi.fn(), getVoices: () => [], addEventListener: vi.fn(),
  });
  vi.stubGlobal('performance', { now: () => clock, measure: vi.fn(), getEntriesByName: () => [], clearMeasures: vi.fn() });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'log').mockImplementation(() => {});
  installNetwork();
});

afterEach(() => {
  try { voice.stopSpeaking(); } catch { /* the module's audio state must not leak into the next case */ }
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('BF-931: the avatar mouth follows the voice, not the request to play', () => {
  built('stays closed from the speech start until the audio is playing (its playing fires 300 ms after play)', async () => {
    const model = await mountAvatar();
    await speak();
    for (const elapsed of [100, 200, 299]) {
      clock = 1000 + elapsed; // wall time since play() was requested; playing is due at +300 ms: currentTime stays 0
      stepFrame();
      expect(mouth(model.mesh), `the mouth moved ${elapsed} ms after play() and before playing`).toBe(0);
    }
  });

  built('follows the audio time once it plays, not the wall clock', async () => {
    const model = await mountAvatar();
    const audio = await speak();
    clock += 400; // the wall clock reads a closed instant of this text's heuristic track (measured)
    audio.currentTime = 0.04; // the audio plays and has reached 40 ms, an open instant
    audio.emit('playing');
    stepFrame();
    expect(mouth(model.mesh)).toBeGreaterThan(0);
  });

  it('samples late deferred visemes on the audio time', async () => {
    const model = await mountAvatar();
    const audio = await speak();
    clock += 5000; // far past the frame's window on a wall clock
    audio.currentTime = 0.1;
    audio.emit('playing');
    act(() => injectLipSyncFrames([{ time: 0.04, duration: 0.2, viseme: 'aa' }], AGENT_ID));
    stepFrame();
    expect(mouth(model.mesh)).toBeGreaterThan(0);
  });
});
```

#### S3 M2

**P2-1.** `ui/src/audio/lipSyncTrack.ts`. The function, before the exported constants (once; the two SEARCH lines are ASCII).
SEARCH:
```
/** Compile-time constants exposed for testing only. */
export const _CONSTANTS = Object.freeze({
```
REPLACE:
```
/** BF-931 (#1669): the time to sample a heuristic track at, on the clock the voice runs on.
 *
 *  ``audioMs`` is the playing <audio> element's clock (``getActiveAudioTimeMs()`` in voice.ts): ``null`` when no
 *  server audio is active (browser speech, whose own 'start' is the sound), otherwise ``currentTime`` in ms, which
 *  is 0 until the element actually plays, advances with the sound and stands still when it stalls. ``wallMs`` is
 *  the time since the speech 'start' event. That event fires when play() is requested, not when sound begins, so
 *  a track sampled on the wall clock moves the mouth for as long as the audio takes to start (the BF-931 defect).
 *  Sampled on the audio clock the track is closed until the voice plays (``sample(0)`` is all zeros) and keeps
 *  the voice's time, as the rhubarb schedule already does (BF-283). A non-finite or negative audio time counts
 *  as not started. Pure. */
export function mouthClockMs(audioMs: number | null, wallMs: number): number {
  if (audioMs === null) return wallMs;
  return Number.isFinite(audioMs) && audioMs > 0 ? audioMs : 0;
}

/** Compile-time constants exposed for testing only. */
export const _CONSTANTS = Object.freeze({
```

**P2-2.** `ui/src/components/profile/CrewVRM.tsx`. The import (once).
SEARCH:
```
import {
  buildHeuristicTrack,
  type LipSyncTrack,
```
REPLACE:
```
import {
  buildHeuristicTrack,
  mouthClockMs,
  type LipSyncTrack,
```

**P2-3.** `ui/src/components/profile/CrewVRM.tsx`. The heuristic branch's clock (once; `now` above it stays and becomes the second argument).
SEARCH:
```
        const elapsed = now - startedAtMsRef.current;
        const w = track.sample(elapsed);
```
REPLACE:
```
        // BF-931 (#1669): the 'start' event fires when play() is requested, not when the voice is audible, so
        // the wall clock runs ahead of the sound by however long the audio takes to start. Sample on the voice's
        // own clock: closed until it plays, then its time (the rhubarb branch above does the same).
        const elapsed = mouthClockMs(getActiveAudioTimeMs(), now - startedAtMsRef.current);
        const w = track.sample(elapsed);
```

**N2-1.** `ui/src/audio/__tests__/lipSyncTrack.mouthClock.bf931.test.ts`. The marker, removed.
SEARCH:
```
const built = process.env.BF931_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

**N2-2.** `ui/src/__tests__/CrewVRM.mouthClock.bf931.test.tsx`. The marker, removed (the same line, once in this file).
SEARCH:
```
const built = process.env.BF931_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

#### S3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once; S2's entry follows it after S2 M3 and this entry is inserted above it). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-931 (DATE), #1669 -- the avatar's mouth no longer starts before the voice is heard.**
- **Base.** The speech `start` event fires when `play()` is requested, not when sound begins, and `CrewVRM` sampled its heuristic viseme track on a wall clock started at that event. With deferred visemes the avatar runs on that heuristic track until the rhubarb frames arrive, so the mouth led the voice by however long the audio took to start. The rhubarb branch already sampled on the audio element's clock.
- **Fix.** A pure `mouthClockMs(audioMs, wallMs)` (`ui/src/audio/lipSyncTrack.ts`) picks the clock: the audio element's time when server audio is active (0, so closed, until it plays), the wall clock for browser speech; the heuristic branch of `CrewVRM` uses it. Late rhubarb frames are sampled on the audio time as before (a control). The `start` event and every other consumer of it are unchanged. Tests: the pure function's cases, and a mounted `CrewVRM` seam test over the real `voice.ts` with a fake audio element whose `playing` comes after `play`. Synthetic text only. Contract `prompts/bf-928-929-931-voice-call-ui.md`, slice S3. Closes #1669.

```

**P3-2.** `DECISIONS.md`. The anchor is the same heading as the other slices' (once; their entries sit before it after their M3, so this entry lands last). Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-931 -- The avatar's heuristic mouth track is sampled on the audio clock, so it stays closed until the voice plays (DATE, #1669)

- *Scope.* `ui/src/audio/lipSyncTrack.ts` (`mouthClockMs`, new), `ui/src/components/profile/CrewVRM.tsx` (the heuristic branch of the frame loop and one import), two new test files. `voice.ts` and the speech event contract are unchanged. Contract `prompts/bf-928-929-931-voice-call-ui.md`.
- *G1 (the clock).* Consumers sample on the audio element's clock, as the rhubarb branch already does: 0 until the element plays keeps a heuristic track closed (it is all zeros at time 0), so the mouth cannot lead the voice. Rejected: moving the `start` event from `play` to `playing` (it changes the contract of every consumer, the voice suites that emit only `play` pin the old order, and a `pause` before `playing` would end an utterance that never started); a new speech event (nine consumers to audit for the same result); a fixed offset (the latency varies).
- *G2 (the tests).* The pure function, and a mounted `CrewVRM` over the real `voice.ts` with a fake audio element whose `playing` comes after `play`; the late-frames half of the acceptance is a control because the rhubarb branch already sampled on the audio time.
- *Residual.* L1 to L7 of the contract (S3). *Reversal.* Revert the BF-931 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3.

### 7.4 Repair R1 (amendment A2): after review round 1, applied on S3 M3's head

Round 1 (section 15, A2) found two defects in what the milestones built: S1's paragraph rule rescans every run of spaces and tabs (quadratic), and S2's appended cases leave four live-frame fields of the store behind. R1 repairs both and one sibling (S1's second cut, the same flaw in the slice's other new regular expression). It is applied after S3 M3, in two commits: the S1 repair (R1-1 to R1-5), then the S2 repair (R1-6). Every SEARCH below occurs exactly once in its file on S3 M3's head, starts at the start of a line and is ASCII; apply the pairs with the `edit` tool one at a time, whole block, in label order. No number of the AD ledger moves and the trackers' entry heads are unchanged, so the ledger is not regenerated.

**R1-1.** `ui/src/audio/voice.ts`. The paragraph rule: a run of two or more spaces or tabs that no paragraph break follows is consumed whole as a second alternative, and the callback returns it unchanged, so the scan never restarts inside a run (once; ASCII). The expression has no look-behind, which would need Safari 16.4.
SEARCH:
```
    .replace(/([.!?]["')\]}\u201d\u2019\u00bb]*)?[ \t]*\n{2,}/g, (_whole: string, end?: string) => (end ? `${end} ` : '. '))
```
REPLACE:
```
    .replace(/([.!?]["')\]}\u201d\u2019\u00bb]*)?(?:[ \t]*\n{2,}|[ \t]{2,})/g, (whole: string, end?: string) => (!whole.includes('\n') ? whole : end ? `${end} ` : '. '))
```

**R1-2.** `ui/src/audio/voice.ts`. The doc comment says why (the last line of the comment, once; ASCII).
SEARCH:
```
 *  before the break and a run of blank lines are one pause. An ellipsis and a decimal are left as they are. */
```
REPLACE:
```
 *  before the break and a run of blank lines are one pause. An ellipsis and a decimal are left as they are.
 *  A run of two or more spaces or tabs that no break follows is matched whole by the expression's second
 *  alternative and returned unchanged: that keeps the scan from restarting inside the run, which costs time
 *  quadratic in its length, and this text is stripped on the page's own thread. */
```

**R1-3.** `ui/src/audio/voiceChunking.ts`. The second cut takes one terminal mark instead of a run of them: the cut is the same (a run is cut after its last mark) and a run is not rescanned from every mark (once; ASCII).
SEARCH:
```
    // BF-929: and after terminal punctuation that closing quotes or brackets follow, when the next word starts a sentence.
    .replace(/([.!?]+["')\]}\u201d\u2019\u00bb]+)\s+(?=["'(\[{\u201c\u2018\u00ab]*[\p{Lu}\p{N}])/gu, `$1${_SPLIT}`)
```
REPLACE:
```
    // BF-929: and after terminal punctuation that closing quotes or brackets follow, when the next word starts a sentence.
    // One terminal mark is enough (a run of marks is cut at the same place, after its last one); a quantified mark here would rescan the run from every mark.
    .replace(/([.!?]["')\]}\u201d\u2019\u00bb]+)\s+(?=["'(\[{\u201c\u2018\u00ab]*[\p{Lu}\p{N}])/gu, `$1${_SPLIT}`)
```

**R1-4.** `ui/src/audio/__tests__/voice.paragraphBreak.bf929.test.ts`. C5: a long run of spaces or tabs is stripped in linear time. It is a control (it passes on the base and on the repaired tree and fails on the tree R1-1 repairs). The last four lines of the file are the SEARCH (once; ASCII).
SEARCH:
```
      'Then "Go." she said.',
    ]);
  });
});
```
REPLACE:
```
      'Then "Go." she said.',
    ]);
  });

  it('strips a long run of spaces or tabs in linear time, so a degenerate reply cannot stall the page', async () => {
    const { stripMarkdownForSpeech } = await import('../voice');
    for (const run of [' ', '\t']) {
      const began = performance.now();
      const stripped = stripMarkdownForSpeech(`Start${run.repeat(50_000)}End`);
      const elapsed = performance.now() - began;
      expect(stripped.startsWith('Start')).toBe(true);
      expect(stripped.endsWith('End')).toBe(true);
      // The unrepaired expression restarts its scan at every character of the run: about a second at this length.
      expect(elapsed).toBeLessThan(250);
    }
  });
});
```

**R1-5.** `DECISIONS.md`. S1's entry names its recorded limits (L6 is new, section 10), once; ASCII.
SEARCH:
```
- *Residual.* L1 to L5 of the contract (S1). *Reversal.* Revert the BF-929 commits.
```
REPLACE:
```
- *Residual.* L1 to L6 of the contract (S1). *Reversal.* Revert the BF-929 commits.
```

**R1-6.** `ui/src/components/profile/__tests__/ProfileChatTab.bf718.test.tsx`. S2's appended describe starts every case from the store's initial live-frame values and leaves them there: the helper, a `beforeEach` that calls it and an `afterEach` that unmounts the component first and then calls it, replace A1's `beforeEach` (once; ASCII). The five lines of the old hook and the describe line are the SEARCH.
SEARCH:
```
describe('BF-928 -- the first transcript load of a scope is history, whatever triggered it', () => {
  beforeEach(() => {
    // The store outlives a case: the refresh command an earlier case left (T1's greeting) would be replayed by the
    // next case's mount and, naming a row that case's server does not hold, would keep its load from landing (A1).
    useStore.setState({ liveThreadRefresh: null });
  });
```
REPLACE:
```
/** The store outlives a case, and the cases of this block leave four live-frame fields behind (a state diff per case
 *  found them): the refresh command (T1's greeting names a row that the next case's server does not hold, so the next
 *  mount's load never lands), the repair epoch (a raised epoch makes the next mount repair its transcript once more)
 *  and the drop count and log. Each case starts from the store's initial values and leaves them there (A1, A2). */
function resetLiveFrameState(): void {
  const initial = useStore.getInitialState();
  useStore.setState({
    liveThreadRefresh: initial.liveThreadRefresh,
    liveRepairEpoch: initial.liveRepairEpoch,
    liveDropCount: initial.liveDropCount,
    liveDrops: initial.liveDrops,
  });
}

describe('BF-928 -- the first transcript load of a scope is history, whatever triggered it', () => {
  beforeEach(resetLiveFrameState);
  afterEach(() => {
    // Unmount first: a store write under a mounted component re-renders it outside act() and can start a repair.
    cleanup();
    resetLiveFrameState();
  });
```

**Commit messages of R1.** `BF-929 R1: the paragraph rule and the splitter's second cut no longer rescan a run, with a control for a long run of spaces (#1667)`, body ending `Refs #1667.`; and `BF-928 R1: the appended cases start from and leave the store's initial live-frame fields (#1666)`, body ending `Refs #1666.`. The amendment itself is committed first, as `BF-928, BF-929, BF-931 (#1666, #1667, #1669): amendment A2 to the build contract after review round 1: the paragraph rule and the splitter's second cut no longer rescan a run, and the appended cases leave the store as they found it`.

## 8. What this does NOT change

**S1.** `speakResponse`, `_prepareServerSpeech` and the whole of the TTS path of `voice.ts`; every other `.replace` of `stripMarkdownForSpeech` (bold, italic, headings, bullets, rules, code, links), including the one whose pattern holds a non-ASCII bullet; the abbreviation guard, the `maxChunks` merge and the first cut of `splitIntoSentences`, and `runPrefetchQueue`; `routers/avatars.py` and every server file (no server-side collapse of a doubled period); the exports of `voice.ts` (the wave-close precheck's mock-parity check, which diffs them against the `vi.mock` factories of 45 test files, stays green); `useMeetingVoice.ts` and `meetingVoice.ts` (they pass `stripMarkdownForSpeech` through unchanged).

**S2.** `admitMessages`, `claimSpeech`, `speechKeyFor`, `isSpeakableAgentMessage`, `markScopeSeen`, `scopeRecord`'s LRU and eviction, `SPEECH_SCOPE_CAP`, `SPEECH_LEDGER_SCOPE_CAP`; the speech effect of `ProfileChatTab` (including its `firstSight || speechSeedScopesRef.current.delete(scopeKey)` line and the meeting-sequencer deferral); `sendText`, `triggerCallGreeting`, the BF-290 conversation callback and every other speaker; `repairThreadMessages`, the stale-result rules of `refreshThreadTranscript` and its coalescing; `liveThreadRefresh` and `liveRepairEpoch` in `useStore.ts`; `ui/src/test/setup.ts` (the importless ledger module keeps its one-import-free shape); the BF-718, BF-765 and BF-768 suites.

**S3.** `voice.ts` (the `start`, `playing`, `end` and `dropped` events and every consumer of them: the barge-in gate, the modulation icon, the PTT gate, the head bob, the meeting sequencer, `ParametricAvatar`); `getActiveAudioTimeMs`; the rhubarb branch and `_sampleRhubarbFrames`; `LipSyncTrack.sample`, `buildHeuristicTrack` and the viseme targets; `speechAmplitude.ts` and the amplitude fallback path; `useLipSyncCapture.ts` and the deferred-viseme fetch and injection.

**All.** The three issues that wait: `ui/src/hooks/useCameraStream.ts` and its callers, the skill-request polling (`SkillRequestPanel.tsx`, `useStore.ts`), `ui/package.json` and the lockfile (the Three.js copies), every Python file, `config/system.yaml` and every config model, the attachment store and the TTS and DM routes (BF-930, BF-932). OSS only; no dependency; no schema change.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

The S1 rows were run in memory (section 11): the patched stripper and splitter evaluated with the line replaced and the nine cases of N1-1 rerun as plain assertions; each was killed by exactly the cases named. A Builder whose files match section 7's blocks does not repeat the campaign: these are the campaign of record for the base tree `54a112e2` plus slices S1, S2 and S3 as written; if a file differs, rerun the rows that name it. The S2 and S3 rows were **not** run by the Architect (no UI test can run in a read-only consult). **A1: the orchestrator ran all three slices' rows on the oracle** (each row's line replaced whole in the built file, the slice's new test files run with vitest's JSON reporter, the file restored and its blob checked): 19 rows, every one killed, no mutant survived, and each row's killers are the cases the cells below name; the cells marked A1 differ from the first text, which understated them (the killers are a superset). **A2:** after the repair R1 the orchestrator reran all three slices' rows on the repaired oracle (section 15): the Lines of S1 rows 1 and 6 are the repaired lines (R1-1, R1-3), and S1 rows 8 and 9 are new.

**S1 (file `ui/src/audio/voice.ts`, then `ui/src/audio/voiceChunking.ts`).**

| # | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|
| 1 | `.replace(/([.!?]["')\]}\u201d\u2019\u00bb]*)?(?:[ \t]*\n{2,}\|[ \t]{2,})/g, (whole: string, end?: string) => (!whole.includes('\n') ? whole : end ? `${end} ` : '. '))` (A2: with the second alternative R1-1 adds) | `.replace(/\n{2,}/g, '. ')` | B1, B2, B3, B4, B5 |
| 2 | the row 1 line | the same with `: '. ')` changed to `: ' ')` | C1, C2 |
| 3 | the row 1 line | the same without `[ \t]*` | B5 |
| 4 | the row 1 line | the same with `[.!?]` changed to `[.]` | B2 |
| 5 | the row 1 line | the same with the closers class emptied (`([.!?])?`) | B3 |
| 6 | `.replace(/([.!?]["')\]}\u201d\u2019\u00bb]+)\s+(?=["'(\[{\u201c\u2018\u00ab]*[\p{Lu}\p{N}])/gu, `$1${_SPLIT}`)` (A2: with the single terminal mark R1-3 gives it) | the line deleted | B3 (the chunks of the quote and bracket variants) |
| 7 | the row 6 line | the same without the `(?=...)` look-ahead | C4 |
| 8 | the row 1 line | the same without the second alternative (`\|[ \t]{2,}` removed; A2, new) | C5 |
| 9 | the row 6 line | the same with the single mark `[.!?]` made `[.!?]+` again (A2, new; **an equivalent mutant**: the output is the same, only the cost differs) | none: no case kills it, because the base's first cut, `([.!?]+)\s+`, is quadratic on the same input and masks the cost (S1 L6); the oracle's probe measures it (section 15) |

**S2 (measured, A1; files `ui/src/components/profile/ProfileChatTab.tsx` and `profileTranscript.ts`).**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `ProfileChatTab.tsx` | `if (triggerMessageId === null \|\| firstLoadOfScope) speechSeedScopesRef.current.add(targetThreadId);` | `if (triggerMessageId === null) speechSeedScopesRef.current.add(targetThreadId);` | T1 (the old rule) |
| 2 | same | `const firstLoadOfScope = markScopeLoaded(speechLedgerRef.current, speechScopeKey(targetThreadId, agentId));` | `const firstLoadOfScope = true;` | T1, T2 (A1: measured; the first text said T2 only: T1 also reads the first-load flag) |
| 3 | same | the row 2 line | the same with `speechScopeKey(targetThreadId, agentId)` replaced by `speechScopeKey(null, agentId)` | T1 (its ledger assertion: the thread scope records its first load) |
| 4 | `profileTranscript.ts` | `const first = !scope.loaded;` | `const first = true;` | L1, L2, T2 |
| 5 | same | `scope.loaded = true;` | `scope.loaded = false;` | L1, L2, T1, T2 (A1: measured; the first text said L1 and T2) |
| 6 | same | `scope = { keys: new Set<string>(), seen: false, loaded: false };` | `loaded: true` | L1, L2, L3, L4, T1 (A1: measured; the first text said L1, L2, L4 and T1) |

**S3 (measured, A1; files `ui/src/audio/lipSyncTrack.ts` and `ui/src/components/profile/CrewVRM.tsx`).**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `lipSyncTrack.ts` | `if (audioMs === null) return wallMs;` | `if (audioMs === null) return 0;` | K2 |
| 2 | same | `return Number.isFinite(audioMs) && audioMs > 0 ? audioMs : 0;` | `return audioMs;` | K5 |
| 3 | same | the row 2 line | the same with `? audioMs : 0` changed to `? wallMs : 0` | K4, V2 (A1: measured; the first text said K4 only) |
| 4 | same | the row 2 line | the same with `? audioMs : 0` changed to `? audioMs : wallMs` | K3, K5, K6, V1 (A1: measured; the first text said K3, K5 and K6) |
| 5 | `CrewVRM.tsx` | `const elapsed = mouthClockMs(getActiveAudioTimeMs(), now - startedAtMsRef.current);` | `const elapsed = now - startedAtMsRef.current;` | V1, V2 |
| 6 | same | the row 5 line | the same with `getActiveAudioTimeMs()` replaced by `null` | V1, V2 |

Not tabulated, for the cap: the scope-key expression of S2 beyond row 3, the comment lines, and the closers class of the stripper beyond rows 5 and 6 (each member of the class is one character of a fixture only in B3).

## 10. Recorded limits

**S1.**

- **L1.** A paragraph that ends in the single character U+2026 or in a colon still gets `. ` (the old behaviour; the acceptance names `.`, `!` and `?`).
- **L2.** A leading paragraph break still yields a leading `. ` and a trailing one a trailing period (unchanged; the regex is anchored on the text between paragraphs only).
- **L3.** The splitter's closing-quote rule needs a capital letter or a digit after the closer (with an optional opening quote or bracket): `"Go." she said.` stays one chunk, and a paragraph that ends in `."` and is followed by a lowercase-initial paragraph is not cut there. `\p{Lu}` and `\p{N}` need an engine with Unicode property escapes (the build targets ES2020).
- **L4.** The TTS text changes for every reply that has a paragraph ending in a period, `!`, `?`, an ellipsis or a closer: that is the fix, stated because it is every such reply. The stray period after a closer that the old text produced is gone.
- **L5.** No audio was heard: the tests prove the text and the chunks. Whether Piper no longer says "dot" is the Captain's check (the last section).
- **L6.** (A2) The splitter's first cut, `([.!?]+)\s+` (the base's, not edited by this batch), costs time quadratic in the length of a run of terminal punctuation with no whitespace after it: measured on the base with a node probe, about 0.2 s for 16,000 consecutive marks and 0.8 to 1 s for 32,000. The slice's second cut had the same shape; R1-3 makes it linear (one mark instead of a run), so the slice adds no super-linear cost, but it cannot remove the base's. No case pins the second cut's linearity: the first cut masks it on the same input (section 9, row 9). A reply of tens of thousands of consecutive punctuation marks is a degenerate generation, not a reply; recorded for one follow-up under #1754 that fixes the first cut together with a timing case over `splitIntoSentences`.

**S2.**

- **L1.** The first load that lands for a scope is seeded, so a live arrival in it other than the trigger message (two replies pushed while the open-time load was failing) is claimed silently and never spoken. The alternative is reading history; recorded, not removed.
- **L2.** `loaded` is evicted with its scope at the ledger's bound (128 scopes): an evicted scope reads as never loaded, as it reads as never seen, and its claims are gone too (BF-768's accepted cost).
- **L3.** The speech effect's `seed = firstSight || speechSeedScopesRef.current.delete(scopeKey)` short-circuits: when a first sight and a seed flag coincide, the flag stays set and seeds the next run too. Unchanged. It cannot happen on the sequence this slice fixes (the first sight comes before any load can land), and it is stated because the new flag is added to the same set.
- **L4.** What the live call actually went through (a failed or a superseded open-time load, a coalesced trigger, or another order) is the issue's account and is not verified: the rule does not depend on it, and the mounted test builds the failed-then-coalesced order from the component's own paths. The superseded order is not a separate case.
- **L5.** A first load that never lands (no transcript is ever fetched, as for a thread the server refuses) seeds nothing and speaks nothing, as before.

**S3.**

- **L1.** The audio clock stands still when the audio stalls, so the mouth holds its current viseme meanwhile; the old wall clock kept moving. The rhubarb branch already behaved this way.
- **L2.** The latency between the element's `playing` and the sound at the speaker (an output device with a buffer, for example) is not corrected; the mouth may still lead by that much.
- **L3.** `ParametricAvatar`'s synthetic pulse (a capsule that scales with a fake amplitude curve, not a mouth) and `CrewVRM`'s amplitude fallback (used only when a text yields no track) still start at `start`.
- **L4.** The `start` event is unchanged, so everything else that starts at it (the head bob `speakBob`, the modulation icon, the PTT gate) still starts at `play`.
- **L5.** `getActiveAudioTimeMs()` is global to the audio device, not per agent; the per-avatar `speakingRef` gate decides who samples. Unchanged.
- **L6.** The mounted `CrewVRM` seam test (N1-2) is the least proven block of the batch: it was type-checked and its logic was run in memory, but no vitest had run it when this was written. **A1: the oracle ran it.** At M1 it is `1 passed | 2 expected fail (3)`: V3 (the control) passes and V1 and V2 fail, as section 4's G1 says, and with `BF931_RUNXFAIL=1` they fail at the assertions it names; at M2 all three pass and the six cases of N1-1 with them. The harness drove the captured frame loop without a repair, so the contingency below was not needed. If the oracle finds that its harness cannot drive the captured frame loop, the repair is local to that file (the cases and their expectations are the contract); if it still cannot be made to run, S3 ships with N1-1 (the pure function) and a recorded limit that the consumer wiring is covered only by the mutation row 5 and the Captain's eyes, and S1 and S2 are not held back.
- **L7.** `currentTime` is 0 until `playing` in the fake; in a real element it advances from the `playing` instant, so the first frame after `playing` may sample a few milliseconds late (below one frame).
## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\next-read` at `54a112e2`)

**Run by the Architect, read-only (Node v24.14.0 and TypeScript 5.9.3 from `D:\ProbOS\ui\node_modules`, win32; scripts piped on stdin; nothing written anywhere but the four answer files; no pytest and no vitest; the reading tree has no `ui/node_modules`, so no UI command could run in it). The shell tool spilled one oversized `Get-Content` output to its own temporary file under `%LOCALAPPDATA%\Temp` by itself; I wrote nothing there:**

```
git rev-parse HEAD -> 54a112e2c73726bda6ab020993036541e4b21bfd (= origin/main); git status --short of the reading tree: 0 entries before and after every run
the three blobs lists of the header: git rev-parse HEAD:<path> for the 16 paths
every SEARCH of section 7 (24 edit blocks in 28 blocks, the other 4 new files), parsed out of the answer parts and applied in order S1 M1, S1 M2, S1 M3, S2 ..., S3 M3 to the LF blobs in memory: each occurs exactly once at its turn, starts at a line start, and is ASCII; every REPLACE and every new file is ASCII (the check is a script, not my eye)
the TypeScript compiler API (typescript 5.9.3; the compiler options of ui/tsconfig.json, target ES2020, strict; the 641 tracked ui/src .ts and .tsx files as roots, 2334 source files in the program; bare imports resolved against D:\ProbOS\ui\node_modules; an in-memory overlay of the patched and new files): the unpatched tree 0 diagnostics (so the host is faithful: the existing tests type-check); the M1 state (the four new test files and the append to ProfileChatTab.bf718.test.tsx, no source change) 645 roots, 2338 source files, 0 diagnostics; the head (every block) 645 roots, 2338 source files, 0 diagnostics. The first run found one error in my own CrewVRM test (a required prop, onLoadError, was missing): fixed in N1-2 and the result above is the second run
S1 evaluated in memory (TypeScript transpiled, run in a vm): the nine cases of N1-1 as plain assertions on the unpatched stripper and splitter: B1 to B5 fail, C1 to C4 pass; on the patched pair: all nine pass; the seven mutants of section 9 each fail exactly the cases the table names (M1: B1-B5; M2: C1, C2; M3: B5; M4: B2; M5: B3; M6: B3; M7: C4); the eight inputs of the existing voiceChunking.test.ts give identical chunks before and after the closing-quote rule
S3 evaluated in memory: for the fixture text 'Okay, ready when you are.' at rate 1, LipSyncTrack.sample(-1) and sample(0) are all zeros, sample(40) has oh 0.4, sample(100) has oh 0.8 and ih 0.05, sample(200) has aa 0.4 and ih 0.15, sample(299) and sample(300) are open (aa 0.41 / 0.4, ih 0.59 / 0.6), sample(400) is all zeros (the numbers V1 and V2 rely on); mouthClockMs on the patched file passes K2 to K6 and its four mutants fail K2; K5; K4; K3, K5 and K6
S2 evaluated in memory: the patched speechLedgerStore.ts and profileTranscript.ts (the second loaded with the first as its only real import): the cases L1 to L4 and LC pass (the eviction case runs the real SPEECH_LEDGER_SCOPE_CAP of 128)
the AD ledger measured in memory (Python, -B, nothing written): scripts/gen_ad_ledger.py imported as a module, its own render() over the committed snapshot: on the unchanged trackers it reproduces docs/development/open-ads-report.md byte for byte (True); with the three tracker entries of section 7 inserted (its _read_lines wrapped, the files untouched) the report changes in 5 hunks, 10 lines, as section 4 G3 lists
the three pure test files (N1-1 of S1, S2 and S3, exactly as written in this contract) transpiled and executed under a 40-line stand-in for vitest (describe, it, it.fails and the matchers toBe, toEqual, toContain, toBeNull, toBeGreaterThan), against the unpatched sources and against the patched ones: S1 on the base: 4 passed | 5 expected fail (9); with BF929_RUNXFAIL=1: 4 passed and 5 failed, each at its own toBe, received strings as quoted in section 6; patched, marker removed: 9 passed. S2's ledger file on the base: 1 passed | 4 expected fail (5); with BF928_RUNXFAIL=1: 4 failed at "markScopeLoaded is not exported by profileTranscript yet"; patched: 5 passed. S3's pure file on the base: 1 passed | 5 expected fail (6); with BF931_RUNXFAIL=1: 5 failed at "mouthClockMs is not exported by lipSyncTrack yet"; patched: 6 passed. This is not vitest: it proves the logic and the classification of the cases, not vitest's summary line
```

**What was NOT run** (all "expected"): every vitest case as a vitest case (so every count of section 4), above all the two mounted seam tests (S2 T1 to T3 and S3 V1 to V3: their logic was traced against the code, and their type-correctness checked, not executed); `npm run build`; the ledger regeneration itself (its report diff was measured in memory; the snapshot's git layer was not); the broad gate; the mutation rows of S2 and S3; every live behaviour.

**Facts read (path:line on `54a112e2`):**

- `ui/src/audio/voice.ts`: `:159-160` (the one top-level guard, `'speechSynthesis' in window`, false under jsdom, so importing the module is safe in a test), `:229` (`_resetTtsStatusForTests`), `:322-329` (`getActiveAudioTimeMs`: `_activeAudio.currentTime * 1000`, or null), `:353-387` (`speakResponse`: an enqueue; `start` and `end` fire only when audio plays), `:518-541` (`_playNow`; `speechSynthesis.cancel()` only `if ('speechSynthesis' in window)`), `:580` (the only call of `splitIntoSentences`), `:607` (the single-call path), `:725-815` (`_playPreparedSpeech`: `_activeAudio = audio` before `play()`; `'play'` fires `start` `:761`; `'playing'` feeds `_notePlaying` only `:762`; the deferred frames are injected from `:791-797`), `:937` (`stopSpeaking`), `:1012-1024` (`stripMarkdownForSpeech`; the bullet `[-<U+2022>]\s` on `:1018` is non-ASCII).
- `ui/src/audio/voiceChunking.ts:26-34` (the heuristic's doc), `:37-65` (`splitIntoSentences`), `:51-52` (the cut).
- `ui/src/audio/lipSyncTrack.ts:37-41` (`sample`: out of range gives zeros), `:70-92` (`VISEME_TARGETS`: `aa` is 1.0 on its axis), `:212-260` (`buildHeuristicTrack`; `sample` returns zeros for `elapsedMs < 0`), `:262` (`_CONSTANTS`).
- `ui/src/components/profile/CrewVRM.tsx`: `:14` (imports `getActiveAudioTimeMs`), `:17-22` (the `lipSyncTrack` import), `:33-50` (`_collectMorphMeshes`: `isMesh` and `morphTargetDictionary`), `:52-58` (`VOWEL_CANDIDATES`), `:150-152` (`applyExpressionsFromSignals` returns when there is no expression manager), `:210-212` (`CrewVRM` wraps `ParticipantVRM`), `:264` (`startedAtMsRef`), `:271-273` (`useLipSyncCapture`, `realFramesRef`), `:286-381` (the load-success path works with `expressionManager: null`), `:502-516` (the `start` listener: `buildHeuristicTrack`, `startedAtMsRef.current = performance.now()`, `speakingRef.current = true`), `:586-609` (the rhubarb branch on `getActiveAudioTimeMs()`), `:610-626` (the heuristic branch; `:617` the wall-clock `elapsed`), `:655-668` (the direct-write loop keyed on `currentTrackRef.current`).
- `ui/src/audio/useLipSyncCapture.ts:62-70` (returns early for `source !== 'browser'`), `:127-131` (`injectLipSyncFrames`).
- `ui/src/components/profile/ProfileChatTab.tsx`: `:57-58` (imports), `:787-788` (`speechLedgerRef`, `speechSeedScopesRef`), `:810-902` (`refreshThreadTranscript`: `:817` the coalesced pending trigger, `:847` the error return, `:853-866` the stale reasons, `:867-872` the trigger-absent check, `:885` the seed, `:886-900` the retry), `:1179-1183` (the greeting's speech), `:1205` (`startCameraStream`), `:1363-1372` (the open-time load effect; `:1369-1370` its cleanup bumps `transcriptRequestRef`), `:1374-1392` (the push-triggered load; `:1380` the live-id set), `:1394-1398` (the repair), `:1481-1531` (the speech effect: `:1482-1483` first sight and seed, `:1512` the admission, `:1526` `stripMarkdownForSpeech(msg.text)`).
- `ui/src/components/profile/profileTranscript.ts:238` (`SPEECH_LEDGER_SCOPE_CAP` = 128), `:241-247` (`markScopeSeen`), `:302-318` (`scopeRecord`; `:305` the only literal that builds a scope record), `:340-353` (`claimSpeech`), `:356` (`speechScopeKey`), `:366-371` (the doc warning), `:377-391` (`admitMessages`); `speechLedgerStore.ts:20-23` (`SpeechScope`), `:30-60` (the ledger and its reset).
- `ui/src/components/sidebar/threadApi.ts:727-778` (`repairThreadMessages`; its outcomes are `success` and `error` only). `ui/src/store/useStore.ts:556` (`liveThreadRefresh`), `:3474-3532` (`chat_thread_message_appended` sets it only for an open thread). `ui/src/test/setup.ts:12,22,24,26-30` (the global resets).
- `ui/vitest.config.ts` (jsdom, `globals`, `setupFiles`); `ui/package.json:8,10` (`build` = `tsc -b && vite build`, `test` = `vitest run`), `:31` (`three` `^0.172.0`; no `overrides` key); `ui/tsconfig.json` (target ES2020; `"include": ["src"]`, so the tests are type-checked by `tsc -b`); `.github/workflows/ci.yml:122-163` (`ui-tests`: Node 22, `npm ci`, `npm run test`, `npm run build`).
- `scripts/wave-close-precheck.ps1:66-72` (exported symbols of a module), `:98` (the `vi.mock(path, () => ({...}))` pattern), `:161-210` (check 2, mock parity for `audio/voice.ts`, `audio/wakeWord.ts`, `audio/speechInput.ts`, `store/useStore.ts`, `api.ts`; AD-748 in `docs/development/roadmap.md:1044`).
- `scripts/gen_ad_ledger.py:20-31` (reads DECISIONS.md and PROGRESS.md live; `--check` fails if stale), `:72-73` (the two outputs), `:113` (the token pattern covers `AD` and `BF`), `:153-176` (the head tokens), `:249-278` (`parse_local_authorities`), `:779-840` (`main`: `--check` is offline; the plain run calls `collect_git_layer()` and rewrites both files).
- The tests: `ui/src/audio/__tests__/voice.test.ts:78-91` and `voiceChunking.test.ts:7-83`; `voice.prefetch.bf918.test.tsx:32-69` (the fake `<audio>` and the fetch plan this contract's S3 harness follows), `:351-355` (`playing` emitted by hand); `ui/src/__tests__/CrewVRM.realAudioFallback.test.tsx` (the loader and `useFrame` mocks S3 follows); `ProfileChatTab.bf718.test.tsx:120-128` (the harness variables), `:170` (`installNetwork`), `:202` (`seed`), `:245` (`mount`), `:262` (`serverPushes`), `:279` (`spokenTexts`), `:737-757` (the last describe, whose last three lines are the SEARCH of S2 N1-2).
- The waiting issues (re-derived, not changed): `ui/src/hooks/useCameraStream.ts:61-64` (`_stopTracks` clears one `_intervalId`), `:98` (`_captureAndUpload`), `:137` (the 503 stop; no 429 branch), `:152` (`startCameraStream`), `:161` (`if (_stream) return;`), `:177` (`_stream` assigned after the await), `:207` (the interval), `:212` (`stopCameraStream`); `src/probos/routers/perception.py:46` (`_check_rate`, keyed on `session_id`), `:180-184` (429 with `Retry-After: 1`); `config/system.yaml:1784` (`camera_max_fps_server: 4`); `src/probos/perception/consumer.py:743` (`_force_describe_permit`), `:787` (`store.exists` before the capped call), `:823-825` (`asyncio.wait_for(... timeout=timeout_s)`), `:843` (`store.exists` after); `src/probos/routers/agents.py:3479` and `routers/thread_fanout.py:406` (the two callers, `timeout_s=4.0`); `src/probos/routers/avatars.py:74`, `:278`, `:327` (the BF-918 route logs); `src/probos/cognitive/cognitive_agent.py:12129` (`BF-631 DM-recall`); `src/probos/routers/skill_requests.py:72-75` (503 when the store is unavailable); `ui/src/components/skill/SkillRequestPanel.tsx:263`, `ui/src/store/useStore.ts:2770` (the polls); `src/probos/attachments/store.py:63` (`exists`).

**Absence Verified (2026-11-13)**

```
CLAIM: none of the six numbers is claimed by anything but its issue, and the highest AD is AD-1359 and the highest BF is BF-961
RUN:   for each n in 928..933: git log --all --format=%s, subjects matching BF-<n>; Get-ChildItem prompts -Filter "bf-<n>*"; git grep -n -E "BF-<n>\b" HEAD -- . ':(exclude)prompts'; gh issue list --state all --search "BF-928 OR ... OR BF-933 in:title"; gh pr list --state all --search "BF-928 OR ... OR BF-933"; git branch -a --list "*928*" ... "*933*"; rg -n "BF-(928|...|933)\b" docs/development/roadmap.md PROGRESS.md DECISIONS.md; d:/ProbOS/.venv/Scripts/python.exe -B -P scripts/ad_ceiling.py; the highest BF in git subjects (git log --all --format=%s, every \bBF-(\d+)), in 4000 issue titles and in prompts/bf-*.md of the tree
FOUND: 0 subjects, 0 prompts, 0 tree hits (prompts excluded) for each of the six; the issues #1666 (BF-928), #1667 (BF-929), #1668 (BF-930), #1669 (BF-931), #1670 (BF-932), #1671 (BF-933), all OPEN, plus #1626 (BF-918, the parent); no pull request names any of the six (the two hits, #1606 and #1640, name other work); one branch glob hit, feat/1333-elastic-team-contract-20261010-c93399b8, matches because its commit-hash suffix contains "933" (not a BF number); 0 hits in roadmap.md, PROGRESS.md and DECISIONS.md; ad_ceiling.py: CEILING AD-1359 from all three sources, NEXT AD-1360 (not allocated); the highest BF is 961 in git subjects (1313 refs), in issue titles (434 BF-titled) and in prompts/bf-*.md (69 files)
HOLDS: yes (nothing new is allocated)

CLAIM: no test or Playwright spec pins the old paragraph join or a doubled period, and the only real call of stripMarkdownForSpeech in a test does not read the join
RUN:   the grep tool over ui/src, --glob "*.test.{ts,tsx}", pattern '\.\.'|"\.\."|\w\.\. [A-Za-z]; rg -n "stripMarkdownForSpeech\(" ui/src ui/e2e --glob '*.test.*' --glob '*.spec.*'; the grep tool over ui/src/audio/__tests__ for the two-character sequence backslash-n backslash-n; the grep tool over ui/e2e for speakResponse|stripMarkdownForSpeech|splitIntoSentences|startCameraStream|getActiveAudioTimeMs
FOUND: no match for the first; one real call, voice.test.ts:82; one paragraph break in the audio tests, voice.test.ts:81 (its assertions are toContain and not.toContain fragments); nothing under ui/e2e
HOLDS: yes

CLAIM: no Python test or script reads a file this batch edits
RUN:   the grep tool over tests, --glob "*.py", pattern ui/src|ui\\src|"ui"\s*/|/\s*"ui" (files only, then lines), and the same pattern over src/probos (*.py) and scripts (*.py, *.ps1); rg -n -l "voice\.ts|voiceChunking|ProfileChatTab|profileTranscript|speechLedgerStore|CrewVRM|lipSyncTrack|stripMarkdownForSpeech|useCameraStream|speechAmplitude|useLipSyncCapture" tests scripts src/probos --glob "*.py"; rg -n "wave_close_precheck|wave-close-precheck" scripts src tests .github docs
FOUND: the 11 files of the first grep read ui/e2e/fixtures, ui/src/store/types.ts, ui/src/components/bridge/BridgeNotifications.tsx, ui/src/audio/voiceModulation.ts and ui/src/audio/modulation_manifest.json, and pass paths in strings (test_ad476, test_bf771, test_bf305): none is a file this batch edits; test_wave_close_precheck.py writes its own synthetic ui/src/audio/voice.ts into a temporary repository; the same grep over src/probos finds ui paths in comments and docstrings, avatars/telemetry.py:75 (reads ui/src/audio/modulation_manifest.json: not edited), api.py:368 (serves ui/dist, the built bundle), and the specialist prompts of cognitive/builder_specialists.py; over scripts it finds scripts/run_test_gate.py:33-41 and :795-804 (the broad gate refuses an untracked file under ui/src/ and a mutation backup file there) and scripts/wave-close-precheck.ps1:163-175 (the exports of the five mocked modules, voice.ts among them: no export is added); the name grep finds Python names only in avatar, voice-profile and config text (src/probos/avatars/asset_manifest.py, dsl.py, rhubarb_backend.py, config.py, config_models/experience.py, crew_profile.py, voice_profile_defaults.py, routers/avatars.py) and in tests/test_ad811c_group_a2ui.py:14 (a docstring)
HOLDS: yes (the Python of this batch is the ledger check, G3)

CLAIM: the only test files that read an edited source as text are the seven ?raw readers of ProfileChatTab.tsx (one of them also of profileTranscript.ts), and none asserts a line this batch edits
RUN:   rg -n "\?raw" ui/src ui/e2e (46 lines); per reader, rg -n of its source assertions (toContain, toMatch, not.toContain, indexOf)
FOUND: ProfileChatTab.tsx?raw in voice.balancedEnd.test.tsx:20, ProfileChatTab.a2ui.test.tsx:26, ProfileChatTab.ad1062.test.tsx:8, ProfileChatTab.ad1075.test.tsx:6, ProfileChatTab.audioControl.test.tsx:82, ProfileChatTab.threadTranscript.test.tsx:28 (and profileTranscript.ts?raw :29), ProfileChatTab.voicewave.test.tsx:12; no ?raw import of voice.ts, voiceChunking.ts, speechLedgerStore.ts, lipSyncTrack.ts, CrewVRM.tsx or useCameraStream.ts; the assertions name the transcript repair (repairThreadMessages(targetThreadId), message.id === triggerMessageId, currentOwner.threadId !== targetThreadId, current.liveGeneration !== generation), the call bar and call start, scroll behaviour, the PTT watchdog, the conversation arm, the A2UI cards and the no-emoji guard: none is the import line 58 or the seed line 885
HOLDS: yes

CLAIM: no test mocks a module whose exports change, no export is added to a mocked module, and no test reads the heuristic clock
RUN:   the grep tool over ui/src, --glob "*.test.{ts,tsx}", pattern vi\.mock\([^)]*(profileTranscript|speechLedgerStore|voiceChunking|lipSyncTrack)|vi\.doMock\(...same...); the PowerShell count of files with vi.mock of a path ending audio/voice and of CrewVRM; the grep tool for getActiveAudioTimeMs|startedAtMsRef|_sampleRhubarbFrames|currentTrackRef over the tests
FOUND: none for the first and the last; 45 test files mock audio/voice (29 of them define stripMarkdownForSpeech as an identity, voice.test.ts calls the real one), 17 mock CrewVRM; S1 adds no export to voice.ts, S3 adds none to CrewVRM.tsx, the new exports are in profileTranscript.ts (markScopeLoaded) and lipSyncTrack.ts (mouthClockMs), which nothing mocks
HOLDS: yes

CLAIM: no existing test has the first load that lands for a thread be a trigger load and expect history to be spoken; no test compares a scope record whole
RUN:   rg -n -c "liveThreadRefresh" ui/src --glob '*.test.*'; for ProfileChatTab.ad1291.e2e, bf764 and issue1340.groupUnmount: rg -n "threadMessages\.has\(|async function mount"; rg -n "scopes\.set\(|keys: new Set" ui/src; rg -n "\.scopes\b|\.seen\b" ui/src
FOUND: 17 test files set liveThreadRefresh; the three that push a multi-row refresh hydrate through mount() first (ad1291.e2e :208, bf764 :227, issue1340 :207), as bf718 does; no ledger dump or record literal in a test (the scope literal is profileTranscript.ts:305; .scopes.get is read for keys in five places and .seen once, one field at a time)
HOLDS: yes

CLAIM: this batch has no generated artifact, snapshot or text-embedding fixture but the AD ledger pair
RUN:   git ls-files ui/dist ui/build; git ls-files ui | rg "__snapshots__|\.snap$"; rg -l "toMatchSnapshot|toMatchInlineSnapshot|toMatchFileSnapshot" ui/src; rg -l "stripMarkdown|speakResponse|paragraph" ui/e2e/fixtures; git grep over docs/development/seams and the baselines for the edited names (none edited are config models)
FOUND: nothing tracked under ui/dist or ui/build; no snapshot file or matcher; no e2e fixture embeds speech text; the generated pair is docs/development/open-ads-report.md and ad-ledger-snapshot.json (G3: its diff is measured in section 4), and no config default, model or facade baseline is touched, so the AD-1152 golden, the config reference and the facade baseline do not move
HOLDS: yes
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** BF-283 (the audio clock for the rhubarb schedule, which S3 extends to the heuristic track); BF-918 and its M5 (deferred visemes, the heuristic schedule until the frames arrive, `final` on `end`); BF-718, BF-765 and BF-768 (the speech claim, its module-scoped ledger, its bound: S2 adds one field to the same record so that it is evicted with the rest); AD-1071 (the sentence splitter and the single-call fallback); AD-1291 (`dropped` as the precedent for an additive speech event, considered and not used); BF-655 (balanced `start` and `end`, which moving `start` would break); BF-937's contract (the `it.fails` marker with an env switch, the module read through a cast so a new export's test loads before the export exists, SEARCH rules, the tracker-anchor and generated-artifact checks); AD-748 (the wave-close precheck's mock parity, which fixes "no new export in `voice.ts`"). **Rejected:** section 3. **External:** none consulted.
- **Blind spots handled.** (1) Removing the stray period also removes the only thing that made a paragraph ending in `."` or `.)` a chunk boundary: the acceptance's closing-quote variant would have passed `no ..` and failed `each paragraph ends a chunk`; hence the splitter rule, with a capital-or-digit look-ahead so dialogue with an attribution is not cut (measured). (2) The same line also made a lone `.` chunk (trailing spaces before the break) and a fourth dot after an ellipsis: fixed by the same regex, with cases. (3) `voice.ts` must gain no export or the wave-close precheck fails 45 mock factories; the contract adds the regex to the existing function. (4) For S2 the `||` in the speech effect is not the only short circuit: in the new component line, `markScopeLoaded` is called first and unconditionally, so an untriggered load still marks the scope (a mutant that put it on the right of the `||` would make the next push-triggered load a "first": T2 kills it). (5) "Seed the first load" is only safe because the trigger row is protected by `liveIds` (`admitMessages`), which the BF-718 suite already pins; the new test names that row. (6) The first landed load can be a trigger load by a failed load plus a coalesced trigger, a path the code allows and the issue's account suggests; no existing test builds it, so the mounted test does, from the component's own paths and the harness's own network, not from a mock of the component. (7) For S3, `sample(0)` is already all zeros, so the audio clock needs no "not started" sentinel beyond `0`; the function still guards non-finite and negative values (a fake `<audio>` without a `currentTime` would give NaN). (8) The audio clock stands still when the audio stalls; recorded (S3 L1). (9) `ParametricAvatar` is a capsule that scales with a fake amplitude curve, not a mouth: out of scope, recorded (S3 L3). (10) The mounted S3 test cannot rely on a real `performance.now`, so it spies on it and restores it; and it cannot rely on React's scheduler seeing a frozen clock as a failure (the clock only moves when the test moves it).
- **What discards a correct result.** S1: a paragraph that ends in `."` and is followed by a lowercase-initial paragraph is not cut at the boundary (S1 L3); a paragraph ending in a colon or U+2026 still gets `. ` (L1). S2: a live reply other than the trigger inside the first landed load is claimed silently (S2 L1). S3: while the audio stalls the mouth holds its viseme (S3 L1); the mouth may lead by the output device's own latency (S3 L2). **Recorded:** S1 L1 to L6 (L6 is A2's), S2 L1 to L5, S3 L1 to L7.

## Batching

**One pull request and one broad gate for S1, S2 and S3; S1 first, then S2, then S3; BF-937 (#1678) merges before it is built.**

| Point | Judgement |
|---|---|
| Files | Disjoint between the slices. S1: `voice.ts`, `voiceChunking.ts` and one test. S2: `speechLedgerStore.ts`, `profileTranscript.ts`, `ProfileChatTab.tsx`, one test and the append to the BF-718 suite. S3: `lipSyncTrack.ts`, `CrewVRM.tsx` and two tests. Only the tracker pairs (PROGRESS, DECISIONS, the ledger pair) collide, with each other and with BF-937: re-anchor them, as the header says |
| Why together | The three are the voice side of one call: BF-928 decides which transcript rows reach `speakResponse(stripMarkdownForSpeech(...))` (`ProfileChatTab.tsx:1526`), BF-929 what that text says, BF-931 which clock the avatar's mouth follows while it plays (`getActiveAudioTimeMs`, `voice.ts:322`). All three close from vitest alone, need no backend, no config, no `npm install` and no generated file but the AD ledger pair, and share one validation set |
| Order | S1, S2, S3. S1 is a pure function and a pure splitter. S2 changes the speech owner of every chat surface and deserves its own review before S3. S3 is last because its mounted seam test has the heaviest harness: if the oracle cannot make it run, S3 leaves the batch and S1 and S2 ship (S3 L6) |
| Revert | Separate commits per milestone and per slice; each slice reverts alone |
| Cost: UI | Per slice: its G1 file(s) and its G2 directories (section 4), then `npx tsc -b`; once per batch, mine: `npm run build`, the whole `npx vitest run`, the mutation rows; CI's `ui-tests` (`npm ci`, `npm run test`, `npm run build`) runs again on the pull request. The `?raw` readers that this batch's G2 reaches: the seven of ProfileChatTab.tsx (six under `src/components/profile`, `voice.balancedEnd.test.tsx` under `src/audio`) |
| Cost: Python | None beyond G3 (`gen_ad_ledger.py`, its `--check`, `tests/test_ad1184_ad_ledger.py`) and the broad gate with the label `bf928-929-931`: no Python or config file changes, and no Python test reads an edited file (Absence Verified). The broad gate does not run the UI tests or the UI build |
| Cost: config | None: no default, no model, no yaml: the AD-1152 golden, the config reference and the facade baseline do not move (Absence Verified); the AD ledger pair is the only generated artifact |

**What the rest wait for.**

| Issue | Waits for | Why |
|---|---|---|
| #1671 BF-933 | Its own contract and batch, next: the camera loop first (a single in-flight start shared by concurrent callers, a stop during a pending start, `Retry-After` honoured, no tick while an upload is in flight), then the skill-request poll (learn once that the store is disabled); the Three.js dedupe (`ui/package.json` and the lockfile: `npm install`, mine, then a visual check of the force graph and the stats overlay) and the 5 s freeze (a profile of a live call) are the orchestrator's and the Captain's. It should land before any live re-measurement of BF-930 and BF-932 | Not coupled to this batch (no shared file; the callers need no edit); cannot close from tests: the issue's own acceptance needs a live profile and a visual check; and the leaked capture loop adds vision-frame traffic to exactly the window the other two measure |
| #1668 BF-930 | One log-only Python contract (with BF-932's), after BF-933's camera-loop slice, then a live call, then a fix slice | "instrument first" and "re-measure live"; the route log already separates `synth_ms` from `store_ms` (`routers/avatars.py:327`), the missing part is queue wait versus I/O in `attachments/store.py`; the tests that pin the log shapes: `tests/test_bf918_tts_latency.py` |
| #1670 BF-932 | The same contract: one monotonic timeline per DM turn with a stamp at each seam (the hooks `routers/agents.py:3479` and `routers/thread_fanout.py:406`; `perception/consumer.py:743`, `:787`, `:823-825`, `:843`, the permit and the two `exists` calls outside the 4 s cap; the agent's turn start, `cognitive/cognitive_agent.py:12129`), then a live call | Nothing logs the wait; the tests that pin the surrounding behaviour: `tests/test_ad733c1_force_describe.py`, `test_ad746a_force_describe_mirror.py`, `test_ad978_group_perception.py`, `test_bf624_stale_meeting_vision_refresh.py`, `test_bf666_force_describe_cache_expiry.py`, `test_bf632_dm_recall_query.py`, `test_bf688_chain_priority_inheritance.py` |

## Not in this issue: for the Captain

Each item is an operation on, or a measurement of, the running vessel or the Captain's own senses. The build does not do it and neither does this contract. None of them is a decision.

1. **Rebuild and reload the HXI.** Action: after the merge, rebuild the UI bundle the vessel serves (`npm run build` from `ui/`; the API serves `ui/dist`, `src/probos/api.py:368`) and hard-reload the browser. Source of truth: the page loads the new bundle. Pass: the three checks below run on it.
2. **BF-929: no "dot" at the end of a paragraph.** Action: ask a crew member for a reply of several paragraphs and listen to it spoken. Source of truth: your ears, and the request bodies of `POST /api/avatars/tts` in the browser's Network panel (the text sent to the synthesizer). Pass: no spoken "dot" between paragraphs; no `..` in a request body (three dots at a real ellipsis are right). A reply that still says "dot" goes back with its request body.
3. **BF-928: a call does not read the thread's history.** Action: hard-reload the HXI, then start a video call with a crew member whose thread has older messages. Source of truth: your ears, and the sequence of `POST /api/avatars/tts` bodies. Pass: only the new greeting is spoken; no older message is read, however long the thread. If history is still read, the live sequence is not the one the tests build: send the bodies and the console's live-drop log.
4. **BF-931: the mouth starts with the voice.** Action: watch the avatar at the start of several spoken replies, including the first after a reload. Source of truth: your eyes. Pass: the mouth stays still until the first sound and then moves. If it still leads by a fixed small amount on one output device (a wireless headset, for example), that is the device's own buffer (S3 L2), not this fix: say which device.

**Decisions that need the Captain.** None: every option above is inside the envelope. Recommendations, not decisions: (1) take BF-933's camera-loop slice as the next batch, ahead of any live re-measurement of BF-930 and BF-932 (section "Batching"); (2) leave `ParametricAvatar` alone (a capsule pulse is not a mouth).

## 13. Diff Reviewer: properties to verify

**S1.**

1. `stripMarkdownForSpeech`: exactly one `.replace` changed (the paragraph rule) and its doc comment; the other seven `.replace` lines and `.trim()` are byte-identical; name, signature and the single export unchanged; the diff of `voice.ts` adds no `export` (the wave-close precheck diffs `voice.ts`'s exports against 45 mock factories).
2. The regex has no nested quantifier (an optional group, then an alternation: `[ \t]*` and `\n{2,}`, or `[ \t]{2,}`): **A2: linear time on a long run of spaces or tabs.** The first text claimed linear time without a measurement and was wrong: the match restarted at every character of a run (quadratic: about 0.5 s for 32,000 spaces). The second alternative consumes a run of two or more spaces or tabs that no break follows, whole, and the callback returns it unchanged (`!whole.includes('\n')`), so the scan never restarts inside a run; it has no look-behind (which would need Safari 16.4: the build's default target list includes Safari 14, and esbuild turns such a literal into `new RegExp(...)`, which throws when it runs). Verify by running: 32,000 and 64,000 spaces and tabs, with and without a newline after them, in well under a millisecond or two; ordinary prose (single spaces) no slower than the unrepaired expression by more than a small factor; and the same output as the unrepaired expression on a spread of small inputs with spaces, tabs, newlines, terminal marks, closers, no-break spaces and carriage returns (the oracle's differential probe: 1,900,000 random strings over four alphabets and 25 fixtures, no difference). The callback returns `end + ' '` or `'. '` for a break.
3. `splitIntoSentences`: the first cut is untouched; the second follows it and uses `_SPLIT`; flags `gu`; the look-ahead requires a capital letter or a digit (after optional opening quotes or brackets); the abbreviation guard and `maxChunks` are untouched; the eight inputs of `voiceChunking.test.ts` give the same chunks.
4. M1: the file imports nothing new; the five `built` cases fail at their own `expect` (the stripped text or the chunks), never at an import; N2-1 removes the marker only.
5. No file of the slice holds a crew member's name, a thread id, a live figure or a live sentence (read the whole diff for the words of the issues).
6. (A1) The ledger pair's diff moves no number but BF-928, BF-929 and BF-931 (all three at S1 M3: the contract commit's subject names them), the report's git-log row and the two skipped-line numbers of PROGRESS.md; no other number's row moved.
7. (A2, the repair R1, S1) R1-1 changes only the paragraph rule's expression (a second alternative) and its callback (one condition), and R1-2 adds a sentence to its doc comment; R1-3 changes only `[.!?]+` to `[.!?]` in the second cut (and adds one comment line); the output of both is unchanged on every input (verify with your own differential run, not only the oracle's: random strings over terminal marks, closers, quotes, spaces, tabs, newlines, letters and digits); no export is added; C5 (R1-4) fails on the tree before R1-1 and passes after it, and its 250 ms bound leaves a margin of at least two orders of magnitude over the repaired expression; the whole S1 file passes. R1-5 changes only the number of recorded limits in S1's DECISIONS entry.

**S2.**

1. `speechLedgerStore.ts` still has no import; `SpeechScope.loaded` is the only field added and `scopeRecord`'s literal sets it false; `markScopeLoaded` marks and answers true once per scope and is built on `scopeRecord`, so it shares the LRU and the bound.
2. In `refreshThreadTranscript` the new call is made on every landed load, before the `||`, with `speechScopeKey(targetThreadId, agentId)` (the same key the speech effect uses at `:1481`); the old comment above it is untouched; nothing else of the function, the effect, `admitMessages` or `claimSpeech` changed.
3. The ProfileChatTab `?raw` suites' assertions still hold (section 6): none names the import line or the seed line, and the new text has no emoji.
4. M1: the appended block adds three cases after the last describe, one helper that only intercepts the thread's first transcript GET, and (A1) one `beforeEach` that resets `liveThreadRefresh`; it changes no existing line of the file; `built` fails at `expect(spokenTexts()).toEqual([...])` with the two older rows in the received value; the two controls pass on the base; N2-2 removes the marker only.
5. T1's ledger assertion reads `loaded` through a cast so M1 type-checks before the field exists.
6. (A1, A2) The appended describe starts every case from the store's initial `liveThreadRefresh`, `liveRepairEpoch`, `liveDropCount` and `liveDrops` and leaves them there (R1-6: a `beforeEach` that calls one helper, and an `afterEach` that unmounts the component and then calls it: the unmount comes first because a store write under a mounted component re-renders it outside `act()`, which prints an `act(...)` warning for each case and can start a repair); T3 passes after T1 in file order, and the first load of each case is built from that case's own network, not from the store. **A2: A1's text said `liveThreadRefresh` was the only field T1 leaves behind, which was wrong** (review round 1; a state diff per case shows T1 leaves `liveDropCount`, `liveDrops` and `liveThreadRefresh` changed and T3 leaves `liveRepairEpoch` changed). Verify by your own state diff per case, not only the oracle's: after each of the three cases and its `afterEach`, those four fields equal the store's initial values, and no other field outside `seed()`'s keys is changed; the whole BF-718 file passes in file order and in reverse case order. R1-6 changes only the helper and the two hooks of the appended describe.

**S3.**

1. `mouthClockMs` is pure and the only addition to `lipSyncTrack.ts`; only the heuristic branch's `elapsed` changed in `CrewVRM.tsx`, with `now` kept as the second argument; the rhubarb branch, the `start` listener and `voice.ts` are byte-identical; no export is added to `CrewVRM.tsx`.
2. The mounted test runs the real `voice.ts`; the clock it controls is `performance.now`; `afterEach` stops speech, unmounts, unstubs and restores; the fake `<audio>` fires `play` at once and `playing` only when told; the third case passes on the base (late frames were already on the audio time).
3. N1-1 reads `mouthClockMs` through a cast, so M1 type-checks before the export exists; N2-1 and N2-2 remove the markers only.

## 14. Acceptance criteria

- G1, G2 and G3 of each slice pass as stated and the batch gates are green with a receipt (`logs/gates/bf928-929-931.receipt.json`); the UI evidence is each slice's vitest commands, `npx tsc -b`, `npm run build` and CI's `ui-tests`.
- **#1667 BF-929.** A paragraph break adds a pause marker only when the paragraph does not already end in `.`, `!` or `?` (optionally followed by closing quotes or brackets); a doubled period is never produced; an ellipsis and a decimal are preserved (B1 to B5, C1 to C4). A long run of spaces or tabs is stripped in linear time (C5, A2). The stripped text and the `splitIntoSentences` chunks of the synthetic fixture contain no `..` and each paragraph still ends a chunk (B1, B3). **The fixture is synthetic, not the live message: this overrides that line of the issue's acceptance (decision D5).**
- **#1666 BF-928.** The first transcript load of a scope in a browser session is seeded whatever triggered it, except for the trigger message, which is still spoken (T1); BF-718's guarantees hold (T2, T3 and the whole existing suite); a reconnect repair is covered (T3 and the existing repair case). The appended cases leave no live-frame field of the store behind (R1-6, A2). No existing test pins the defect.
- **#1669 BF-931.** In the deferred path the mouth schedule is anchored to the audio's playback: no mouth movement before `playing` (V1: the fake's `playing` is due 300 ms after `play()`, the issue's own example, and the mouth is closed at 100, 200 and 299 ms) and the heuristic follows `currentTime` (V2); deferred visemes that arrive after playback started are sampled on the audio time (V3, already true: a control). V2's late start is 400 ms, not 300, because the fixture's heuristic track is open at 300 ms on the wall clock and V2 must be a case the base fails.
- No crew member's name, thread id or live figure appears in any test, comment, tracker line, commit message or in this contract.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-13): the store leak in S2's appended block, five understated killers, the batch's ledger movement and the base after BF-937

**Drafted by:** the orchestrator, not the Architect: each change below is fixed by a measurement on an oracle, so it is mechanical (the Architect's consult could run no test: Status). The Diff Reviewer's first brief names this section as the first thing to verify.

**What was run.** BF-937 merged after the Architect read `54a112e2`; the build base is its merge `f614a31d855e217eec6c826deaffad7572d1f43f` (tree `1b5fd1642934c7497adff9b16c5610df091be4db`). The orchestrator applied the 28 blocks (24 pairs and 4 new files) in label order, slice by slice, to that commit by tool (the tool's pair count equals the label count at every step; 0 failures; every SEARCH occurs exactly once at its turn), committed them as the milestones of a scratch chain, and ran on it the gates of section 4, the mutation rows of section 9, `npm run build` and the whole UI suite. An earlier chain over `54a112e2` found the first defect below; its code and test blobs are equal to this one's (all twelve paths of the batch), so nothing was lost by moving the base. Three things the text did not say came out of running, not of reading:

1. **S2's appended block leaked a store field between its cases (N1-2).** At S2 M1 the third appended case (T3, the reconnect-repair control) failed when it ran after T1 and passed alone. T1 (the trigger case) leaves `useStore.liveThreadRefresh = { threadId, requestId: 'g1' }` behind, because its greeting arrives as a live-thread refresh command; the store outlives a case, so T3's mount replayed that command, which names a row T3's server does not hold, and T3's first load never landed. N1-2's REPLACE now opens the appended describe with a `beforeEach` that calls `useStore.setState({ liveThreadRefresh: null })` (with a two-line comment above the call) (M1's addition to `ProfileChatTab.bf718.test.tsx` grows from 104 to 110 lines: its numstat is `110 0`). The SEARCH, the label line and every other block are unchanged. Re-measured at S2 M1: the new file `1 passed | 4 expected fail (5)`; the BF-718 file `29 passed | 1 expected fail (30)`; with `BF928_RUNXFAIL=1` the new file has 4 failed and 1 passed, and the BF-718 file 1 failed and 29 passed.
2. **Five mutation rows understated their killers** (S2 rows 2, 5 and 6; S3 rows 3 and 4): the first text named a subset of the cases that fail. The cells are corrected in section 9 (marked A1); the other fourteen rows are as written, and no mutant of the 19 survived.
3. **The ledger moves differently from the in-memory measurement.** The Architect measured the three entries together on `54a112e2`; the generator also reads the subjects of the commits, and the contract commit's subject names BF-928, BF-929 and BF-931, so S1 M3's regeneration moves all three numbers and S2 M3 and S3 M3 move none (section 4, G3 of each slice; the report moves by `6 6`, `3 3`, `3 3` lines and the snapshot by `12 3`, `3 3`, `3 3`). A comparison of every number list of the report before and after each M3 shows that no other number's row moved.

**Measured on the scratch chain** (nothing in this section was measured on the real tree):
- **S1.** M0: `src/audio` 27 files, 292 tests. G1 at M1: `4 passed | 5 expected fail (9)`; with `BF929_RUNXFAIL=1`: 5 failed (each at its own `expect`, the stripped text or the chunks) and 4 passed. G2 at M2: 28 files, 301 tests (292 + 9), 0 failed; `npx tsc -b` clean. The seven mutation rows: each killed by exactly the cases it names (7 of 7).
- **S2.** M0: 75 files, 823 tests. G1 at M1: as item 1. G2 at M2: 76 files, 831 tests (823 + 8), 0 failed; `npx tsc -b` clean. The six rows: each killed by the cases of its A1 cell (6 of 6).
- **S3.** M0: 41 files, 381 tests. G1 at M1: `1 passed | 5 expected fail (6)` and `1 passed | 2 expected fail (3)`; with `BF931_RUNXFAIL=1`: 5 failed and 1 passed, then 2 failed and 1 passed, at the assertions section 4 names. G2 at M2: 43 files, 390 tests (381 + 9), 0 failed; `npx tsc -b` clean. The six rows: 6 of 6. The mounted seam test (N1-2) needed no repair (S3 L6).
- **The head.** `npm run build` clean. The whole `npx vitest run` with `PYTHONPATH` set to the tree's `src`: 372 files, 4,308 tests; 370 files pass (4,300 tests, 1 skipped) and **7 tests in 2 files fail: `ui/src/__tests__/IntentSurface.bf812.test.tsx` and `ui/src/components/profile/__tests__/ConsultedEvidence.test.tsx`**, whose fixtures start a real Python process that boots the runtime; the whole suite starved them (the process was killed after about 50 s, `signal=SIGKILL`, and one case reported `Test timed out in 5000ms`). Run alone on the same tree both files pass (2 files, 33 tests). They read none of the batch's files, and CI's `ui-tests` runs the whole suite again. Without `PYTHONPATH` the venv imports another checkout's `src` and three such files fail: set it for any whole-suite run.
- **Absence, re-run on the head.** No Python test and no script reads an edited file: the tests that name `ui/src/audio` read `modulation_manifest.json`, `voiceModulation.ts` and `silero-vad.ts` (none edited), and `scripts/wave-close-precheck.ps1` names `ui/src/audio/voice.ts` for its export parity, which this batch does not change (no export is added).

**What A1 changes.** In the header: the provenance line, Status, the base-blob line, and the paragraphs "Tracker anchors, and the BF-937 merge" and "Which text describes the head" (each gains a sentence marked A1). Section 4: G3 of S1 (the measured movement), S2 and S3 (they move no number). Section 7: S2's N1-2 (the `beforeEach`). Section 9: the introduction, the S2 and S3 headings and five cells. Section 10: S3 L6's note. Section 13: S1 property 6, S2 properties 4 and 6. This section. **Not changed:** sections 1 to 3, 5, 6, 8, 11 and 12, "Batching", "Not in this issue", and every other pair and new file of the three slices; nothing under `src/` and no Python or config file.

### A2 (2026-11-13): review round 1: the paragraph rule's quadratic scan, the appended block's remaining store leak, and one sibling

**Drafted by:** the orchestrator, not the Architect: each change below follows a reviewer's finding that was reproduced here before any repair, or a measurement, so it is mechanical. The round-2 reviewers' briefs name this section and section 7.4 first.

**Round 1.** Three reviewers (`gpt-6.1-sol`, one per slice, in parallel, each in its own copy) reviewed the head of the batch, `a4f8e67c8d4aedda4e2e126d090ffa9f583671b0` (S1 `fcccba0f`, `2faf90be`, `8e5fc5e3`; S2 `a15818dd`, `2faf80c6`, `137d851f`; S3 `ff129d23`, `97439fe9`, `a4f8e67c`; over BF-937's merge `f614a31d`). **S3: READY**, no finding. **S1: NOT READY**: one finding, P2, ordinary reach, a regression. **S2: NOT READY**: one finding, P3, ordinary test execution, a regression in test isolation. Both were reproduced before any repair:

1. **S1: the paragraph rule rescans every run of spaces or tabs.** The expression `([.!?]closers*)?[ \t]*\n{2,}` can start at any position (its first group is optional). From the first character of a run of n spaces or tabs that no paragraph break follows, `[ \t]*` scans the rest of the run before `\n{2,}` fails; the engine then starts again from the second character, and so on: time quadratic in the length of the run. The base's `.replace(/\n{2,}/g, '. ')` was linear. Reproduced on the exact expression with a node probe: 8,000, 16,000 and 32,000 spaces took 38, 131 and 542 ms (tabs, and a run followed by a single newline, the same), against 0.01 to 0.04 ms for the base; the reviewer measured 2.1 s for 64,000 spaces against 0.19 ms. Every production caller strips the text on the page's own thread before it queues the speech, so a long run (a degenerate generation can produce one) stalls the page; the server's later length limit does not help. The first text of section 13 (S1 property 2) said "linear time" and had not been measured.
2. **S2: the appended cases still leave store state behind.** A state diff per case (the file run on the oracle with a hook pair that records the keys each case changed) shows T1 leaving `liveDropCount`, `liveDrops` and `liveThreadRefresh` changed and T3 leaving `liveRepairEpoch` (and the drop count and log) changed; the values also arrive non-zero from the file's earlier cases (at the end of T1: epoch 2, drop count 27). A raised epoch makes the next mount repair its transcript once more (the reviewer measured 2 transcript requests where a clean store gives 1). A1's text said `liveThreadRefresh` was the only field left behind.
3. **A sibling, found while reproducing 1.** The second cut of the splitter (S1 M2, P2-4) has the same shape on a run of terminal punctuation: `[.!?]+` followed by one or more closers is retried from every mark of a run when no closer follows (a probe: 49, 200 and 770 to 1,170 ms for 8,000, 16,000 and 32,000 periods). The base's own first cut, `([.!?]+)\s+`, costs the same on the same input, so the class is pre-existing (S1 L6), but the second cut is this slice's new code.

**The repair (section 7.4).** R1-1 and R1-2 give the paragraph rule a second alternative, `[ \t]{2,}`, which consumes a run of two or more spaces or tabs that no break follows, whole, and make the callback return such a run unchanged (`!whole.includes('\n')`), so the scan never restarts inside a run; R1-3 makes the splitter's second cut take one terminal mark instead of a run (a run is cut after its last mark either way); R1-4 adds C5, a control that strips 50,000 spaces and 50,000 tabs in under 250 ms; R1-5 corrects the number of recorded limits in S1's DECISIONS entry; R1-6 replaces A1's `beforeEach` in S2's appended describe with a helper that resets the four fields to the store's initial values before every case, and after every case once the component is unmounted (a first form of R1-6 reset them in `afterEach` while the component was still mounted: the write re-rendered it outside `act()` and printed an `act(...)` warning for each of the three cases, which the stderr sections of the audited runs showed, 40 output sections against 37 before; unmounting first removes them). R1 is applied after S3 M3 and committed separately from the milestones; the milestones and their reviews stand as built.

**The choice of R1-1.** The reviewer proposed a look-behind, `(?<![ \t])` before `[ \t]*` (smallest; its output equals the unrepaired expression's on 400,000 random strings, and it takes 0.05 to 0.5 ms for 8,000 to 64,000 spaces). It was not taken. No source file under `ui/src` uses a look-behind (a search found none), the build has no `build.target` and Vite 6's default target list includes Safari 14, and the production bundle built from that variant carried the expression as `new RegExp(...)` (esbuild converts a literal the target cannot parse, so that an old browser does not fail at load): it throws when it runs on a browser without look-behind (Safari before 16.4), so the stripper, and with it speech, would have failed there where the base worked. R1-1 has no look-behind. A variant whose second alternative was `[ \t]+` (every single space a match) was also rejected: the same output, but about eight times the cost on ordinary prose.

**Differential evidence** (probes outside the repository, deterministic random strings; none of them is a test of the repository): the repaired paragraph rule gives the same output as the unrepaired one on 1,900,000 random strings over four alphabets (terminal marks, closers, quotes, spaces, tabs, newlines, letters and digits; with no-break spaces, carriage returns and em spaces; a whitespace-heavy alphabet; lengths up to 16, 24, 30 and 40) and on 25 hand-written fixtures, among them `a\n\n  \n\nb`, `a\n   \n\nb`, `   \n\nfoo` and `a  \n  \n\nb`; the splitter's second cut with one terminal mark gives the same output as the cut with a run on 1,000,000 random strings (the two cuts in order, and the second alone). Cost: the repaired paragraph rule takes 0.01 to 0.33 ms for 8,000 to 64,000 spaces or tabs (with and without a newline after them) and about 0.03 ms for 7,000 characters of prose (0.030 ms for the unrepaired one); the splitter's second cut takes 0.04 to 0.13 ms for 8,000 to 32,000 periods, where the cut with a run takes 49 to 770 ms. The first cut is the base's and is not changed (S1 L6).

**Measured on the repaired oracle** (nothing was measured on the real tree): S1 G1 `10 passed (10)`; `src/audio` 29 files, 307 tests before R1 and 308 after (M0 + 1); the repaired test file against the source before R1-1 gives `9 passed | 1 failed`, the failure being C5 at `expect(elapsed).toBeLessThan(250)` (1,232 ms for the run of spaces): C5 discriminates. `npx tsc -b` clean. S2: the new file `5 passed (5)`, the BF-718 file `30 passed (30)`, G2 76 files and 831 tests (unchanged by R1-6, which adds no case). S3 G2: 43 files, 390 tests before R1 and 391 after. `npm run build` clean. The whole `npx vitest run` with `--maxWorkers=8`: 372 files, 4,308 passed and 1 skipped (one test more than before R1). The mutation rows of section 9 (S1 rows 1 to 9, S2 rows 1 to 6, S3 rows 1 to 6): every killer set equals the cells, row 8 is killed by C5 alone and row 9, the equivalent mutant, by no case. The store audit (the BF-718 file with the hook pair): after each appended case and its `afterEach`, the epoch, the drop count and the refresh command are `0`, `0` and `null`; before R1-6 they were `2`, `27` and the greeting's command after T1, `2`, `27` and the push's command after T2, and `3`, `28` and `null` after T3. The output of that audited run has 37 sections (`stdout |` and `stderr |` headers), as at `a4f8e67c`, and no `act(...)` warning; the first form of R1-6 (both resets in `afterEach` before the component was unmounted: vitest runs a describe's `afterEach` before the file's own `afterEach(cleanup)`) gave 40 sections and one warning for each of the three cases. The BF-718 file passes in five shuffled orders (`--sequence.shuffle.tests` with `--sequence.seed` 1, 7, 42, 1234 and 99999: `30 passed (30)` each, no warning). **Run the whole suite with `--maxWorkers=8` on a loaded host:** with the default worker count (one per logical CPU) each of the three whole-suite runs made with it timed out in two or three files that start a real Python process or wait on timers (`IntentSurface.bf812`, `ConsultedEvidence`, `voice.prefetch.bf918`, `voice.testGate`), and those files passed alone and with 8 workers; CI's `ui-tests` runs the whole suite on its own runner.

**What A2 changes.** In the header: the provenance line. Section 3: D2b's first row (the single terminal mark). Section 4: the R1 gate paragraph. Section 6: S1's table (C5) and S2's isolation paragraph. Section 7: the new section 7.4 (R1-1 to R1-6 and the commit messages). Section 9: the introduction and S1's rows 1 and 6 (the repaired lines), 8 and 9 (new). Section 10: S1 L6. Section 12: the count of recorded limits. Section 13: S1 properties 2 and 7 (new), S2 property 6. Section 14: the acceptance of #1667 and #1666. This section. **Not changed:** every block of sections 7.1 to 7.3 (built, reviewed and committed as they were), sections 1, 2, 5, 8 and 11, "Batching" and "Not in this issue"; nothing under `src/`, no Python or config file, no number of the AD ledger (the trackers' entry heads do not change).
