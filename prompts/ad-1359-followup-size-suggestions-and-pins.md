# AD-1359 follow-up (#1769): the code review's suggestions reach the build result, the size exemption and its count are pinned and counted (two slices; #1769 stays open for its review point)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge is logged out), 2026-11-13
**File in the repository:** `prompts/ad-1359-followup-size-suggestions-and-pins.md` (the orchestrator may rename it). **Answer file:** in three parts, because the contract is too long for one `create` call: `answer-a1769-contract.part1.md` (this header, sections 1 to 6), `answer-a1769-contract.part2.md` (section 7: slices S1 and S2), `answer-a1769-contract.part3.md` (sections 8 to 14, "Batching", "Not in this issue: for the Captain"). Read them in that order; the labels of section 7 restart in each slice.
**Status:** ready to build on `origin/main` `0ef819cad2ba03473bbc9b01f51c52501083104d` **after the two earlier batches have merged** (BF-933, pull request #1789, UI only; BF-930/932, Python, log-only timing). **Reading tree:** `D:\ProbOS-worktrees\next-read` at `0ef819cad2ba03473bbc9b01f51c52501083104d` (`git rev-parse HEAD`; `git status --short` printed nothing; read only). **Oracle:** the Architect ran no pytest, no vitest, no build and no script that writes (a read-only consult). **What I ran instead** (section 11): every SEARCH of section 7 against the LF blobs of the reading tree (occurrence, line start, ASCII), the enumerations of every reader of the lines this batch extends or adds, a dry application of the blocks in memory with the mutation Lines counted on the patched text, the pure helper and the paragraph's sentence count evaluated on their own, and the existing harnesses read case by case. **What that leaves unchecked (all "expected" below):** every pytest count and every new case as a pytest case, the mutation rows, the AD ledger regeneration, `scripts/check_architecture_principles.py --check`, the broad gate and the wide run.
**Base blobs (`0ef819ca`):** S1 edits `tests/test_standing_orders_layout.py` `20bb35d1a34c1dc97cc8b348ed7ad8a3151c19d0` and `.github/agents/orchestrator.agent.md` `37f2ff7ffacc06250d08d7bfa663bacb05f628e5`. S2 edits `src/probos/cognitive/builder.py` `16bc1cbadf53fa4dd30774e60d5b87d5c709890a` and `src/probos/routers/build.py` `6e3daf5814a8a4cc9644433df59cccffef4f1447`. Read, not edited: `src/probos/cognitive/code_reviewer.py` `c8e1a42f8d834a408ab1f5ebc748415d24412232`, `.github/copilot-instructions.md` `e0abb1bca5dbdc4d344ab6976fee48047e89d2ac`, `.github/agents/diff-reviewer.agent.md` `87d3e6c90c108f395db1f3b8ab626f0282021764`, `.claude/agents/claude-diff-reviewer.md` `3f310a2a8565f4e6750b60a77cbd8345ae526659`, `tests/test_code_reviewer.py` `e632bc3b73fbb3edc875ec0700073a58ae81cf32`, `tests/test_builder_agent.py` `ad68d1afd1e506c28aa01840f23f5f3a7d9866e1`, `tests/test_builder_api.py` `34e6758e5b23caf396cf3251469a67fd2ba93ca8`, `tests/test_ad1359_agent_size_rules.py` `9c47c638931091da3db03ac6c51518e9c81cb3e4`, `tests/test_bf904a_failed_build_restore.py` `4e1c8bd3751a8727ea0a481ba15265595ae39d60`, `tests/test_bf904b_sealed_core_observation.py` `f594ec1b5c36326e7ff71f1c6158de63b8cd2bb3`, `tests/test_ad1346_admission_build_test_sink.py` `8b140f68fa547eafc79b8894322ec7385c28008c`, `ui/src/store/types.ts` `64bbe9372315f5cb8721b219bde0eb4eb60bac56`, `ui/src/store/useStore.ts` `d67246cf32182520685b12d2c0b6e909766214c8`. Trackers and generated pair on `0ef819ca`: `PROGRESS.md` `f2cb113fac5247d82c37abd28c09382b3468684f`, `DECISIONS.md` `470dc36fb4f3083518c70b8f795a8923b75d95b6`, `docs/development/open-ads-report.md` `6aabf0f702fbcc38c9386df61fb197f1b8a8c699`, `docs/development/ad-ledger-snapshot.json` `3b6c6bdf1fd86c5dc1e953fcfbaed5008ef1aff0` (**the two earlier batches move all four before this batch is built; every code and profile blob above must still be equal**). **Two paths do not exist** (to be confirmed by `Test-Path` before the build): `tests/test_ad1359_followup_review_suggestions.py` and `prompts/ad-1359-followup-size-suggestions-and-pins.md`.
**Dependencies and files of the earlier batches.** BF-933 edits `ui/src/hooks/useCameraStream.ts`, two new files under `ui/src/**/__tests__/`, `PROGRESS.md`, `DECISIONS.md`, the AD ledger pair and its prompt; BF-930/932 edits `src/probos/utils/step_timing.py` (new), `src/probos/attachments/filesystem_store.py`, `src/probos/audio/tts/resident.py`, `src/probos/routers/avatars.py`, `src/probos/routers/agents.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/cognitive/concurrency_manager.py`, two new test files, the trackers, the ledger pair and its prompt. **This contract edits none of those files except the four tracker and ledger files** (`PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`); it touches no `ui/` file, no config and no event type.
**Tier:** S1 M1 STANDARD (tests), S1 M2 STANDARD (one paragraph in an instruction file; it changes what the orchestrator writes, not what any code does), S1 M3 STANDARD; S2 M1 STANDARD, S2 M2 HIGH (the executor's review step and the approval route's success event, in the two files most censuses read), S2 M3 STANDARD. **Estimated tests (expected, not measured):** S1 15 new cases in an existing file (14 pass at M1, 1 xfails); S2 one new file, 16 cases (1 passes at M1, 15 xfail). No config key, no config model, no generated artifact but the AD ledger pair. **Numbers:** none is allocated (section 11, Absence Verified). **Current highest: AD-1359 and BF-961** (the Ceilings table of the ledger report on `0ef819ca`; `git log --all` subjects name no AD-1360 and no BF-962); `scripts/ad_ceiling.py` was not run because nothing is allocated.

**Tracker anchors (state as the earlier contracts do; the orchestrator re-anchors after both merges).** `PROGRESS.md`: the title line `# ProbOS Progress` and the blank line after it (once, at the start of the file on `0ef819ca`: `git show HEAD:PROGRESS.md` starts `# ProbOS Progress`, an empty line, then BF-931's entry; the SEARCH is unchanged by any entry inserted below it, so this batch's entries land above the other batches'). `DECISIONS.md`: the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)` (once on `0ef819ca`, at line 1732, a whole line, ASCII, no CR in the blob; every BF or AD entry of this period inserts before it, so this batch's entries land after the other batches', in slice order). **The orchestrator re-runs the occurrence check of those two SEARCHes after the two merges (each exactly once, at a line start, ASCII); any change to either file between `0ef819ca` and the build's base other than the two earlier batches' own entries is a hard stop for the Architect.** The AD ledger pair is regenerated at each M3 by `scripts/gen_ad_ledger.py` (G3) and is not merged by hand. **The only AD or BF token in any tracker head or commit subject of this batch is `AD-1359`** (the parent; no suffix, no other number): the ledger reads AD and BF tokens at the head of tracker entries and in commit subjects, and the plain token adds no evidence string to a number that is already `shipped` (section 4, G3).

## 1. Problem

Issue #1769 (open, label `enhancement`) has three parts. Its anchors are from 2026-11-08 and are re-derived on `0ef819ca`.

| Issue claim | Re-derived on `0ef819ca` | Verdict |
|---|---|---|
| 1. `ReviewResult.suggestions` has one writer, `code_reviewer.py:150`; its only reader is `tests/test_code_reviewer.py:82` | Two writers: `:114` (the error path: `approved=True, suggestions=["Code review skipped due to error: ..."]`) and `:150` (`result.suggestions = data.get("suggestions", [])`, copied as given from the model's JSON). Readers: `tests/test_code_reviewer.py:82` only (`rg` in `src`, `tests`: section 11) | **Confirmed, plus a second writer** that makes a skipped review visible once something reads the field |
| 1. `BuilderAgent` reads only `summary`, `approved` and `issues` (`builder.py:3541-3554`) | `:3546` `result.review_result = review.summary`, `:3547` `if not review.approved:`, `:3550` and `:3554` `review.issues` | **Confirmed.** `BuildResult` (`:128-147`) has `review_result` and `review_issues` (`:142-143`) and nothing for suggestions; so do `BuildFailureReport` (`:151-180`, `to_dict` `:198-199`, `classify_build_failure` `:219-220`) and the success event (`routers/build.py:508-509`) |
| 1. `_parse_file_blocks` (`builder.py:2713`) discards the Builder's prose, so the written readings and the dead code it left are lost | **Half.** The parser keeps only `===FILE` and `===MODIFY` blocks, but `act()` returns the raw text as `llm_output` (`builder.py:2698`, `:2705`), `routers/build.py:441-451` emits it on BUILD_GENERATED, `useStore.ts:3780-3797` stores it on the proposal and `IntentSurface.tsx:1391-1413` shows it under a collapsed "View Code" in the approval card, before the Captain approves. The build result never carries it: `BuildResult.llm_output` (`:140`) is set nowhere (`rg`: section 11) | **Half.** The readings reach the Captain at approval; they never reach the result, and the Transporter path writes a placeholder instead of prose (`builder.py:2541`) |
| 2. `tests/test_ad1359_agent_size_rules.py` checks only the crew's composed instructions; the dev-side rules have no test | The file has one function, three cases (builder, code reviewer, architect), all over `compose_instructions`. `rg` in `tests` for "Size findings", "no further review round", "call-free bindings" and the marker finds no test (section 11). The exemption is `.github/agents/orchestrator.agent.md:48`; the constitution's sentence is `.github/copilot-instructions.md:54`; both reviewer profiles carry the tag line (`diff-reviewer.agent.md:102`, `claude-diff-reviewer.md:109`) | **Confirmed** |
| 3. Size findings are not recorded per item; "the Size checklist item" cannot be shown to fire | `rg "Size findings: " .github CLAUDE.md` finds nothing; the profile has no rule about the content of a pull request's review summary (the summaries are the `**Review.**` paragraphs of the pull request bodies); `.github` holds three files besides workflows and no pull request template (section 11) | **Confirmed** |

**Why part 1 matters beyond the crew's size findings.** `CodeReviewAgent.review` approves with one suggestion when its own model call fails (`code_reviewer.py:108-116`); today that skipped review is indistinguishable from a clean one anywhere. Carrying the suggestions makes it visible as a count.

**Why part 3 is a measurement and not a fix.** The sentence changes what an orchestrator writes in a pull request body. Whether it is followed can be read only from the pull requests merged after it lands. That is why #1769 stays open for its review point (decision D2) and why the tests pin the sentence (D6): a measurement instrument that disappears silently reproduces the original failure (a missing line reads as zero).

## 2. Solution

Two slices, one batch, one gate, one pull request; S1 first.

- **S1 (parts 2 and 3: text and layout tests).** `tests/test_standing_orders_layout.py` gains 15 cases: each condition of the orchestrator's no-review exemption (10 named cases), the exemption sentence verbatim and the paragraph's sentence count (1), the constitution's sentence (1), the reviewers' size tag in both profiles (2), and the count sentence (1, built at M2). `.github/agents/orchestrator.agent.md` gains one paragraph after the Size findings paragraph and before the round-three brake: the review summary of each item or slice states `Size findings: <n>`, zero included, and names each finding by how it ended.
- **S2 (part 1: Python).** `BuildResult.review_suggestions` and `BuildFailureReport.review_suggestions` (`list[str]`, empty by default, set whether or not the review approved), the failure report's dict and the BUILD_SUCCESS payload gain the key, and the success message ends `, Review suggestions: <n>` only when there are any. One pure helper coerces the model's JSON to non-blank strings. No new event type, no UI change, no config. The Builder's written readings need no code (D4): the closing comment on #1769 records the path and its limits.

Rejected heavier designs (section 3): a READINGS block in the Builder's format and a card for it; posting to the Ward Room; retracting the standing-order lines; one slice for everything; a slice per part.

## 3. Decisions

Each table ranks the options by correctness, safety, compatibility, fit, reversibility and validation cost; the first row is the decision. In-envelope means evidence, backward compatibility, no weakened control, no OSS/commercial boundary crossed, bounded rollback. None of the decisions meets a "Still requires the Captain" condition (`orchestrator.agent.md:116-123`).

**D1. Slicing.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Two slices, docs and pins first: S1 = parts 2 and 3, S2 = part 1; one batch, one gate, one pull request** | S1 cannot change a runtime and ships alone if S2 stalls ("freeze what is reviewed"); the clock of part 3's review point (ten pull requests) starts at the merge, so the earlier the sentence is in force the earlier the decision; parts 2 and 3 share the test file and one boundary (the new paragraph must lie outside the paragraph part 2 pins), so they are one slice; the file sets of S1 and S2 are disjoint apart from the four tracker files; each slice reverts alone |
| 2 | Two slices, code first (S1 = part 1, S2 = parts 2 and 3) | Same cost and same disjointness; the riskier slice sits in front of a zero-risk one, so a stall in review holds the sentence back for nothing. Rejected on that evidence only: the guess is sound |
| 3 | One slice for all three parts | One Diff Reviewer sees Python and instruction text in one candidate; one failure holds everything; one M3 less. Rejected: no partial ship |
| 4 | Three slices, one per part | A third M1 to M3 set (a tracker entry and a ledger regeneration each) for two parts that touch one file and one boundary. Rejected: ceremony |

**D2. Closure.** The filing policy (`orchestrator.agent.md`, Backlog Burn-Down Mode: "Closures must be shipped fixes ... Never game the count"; at most one follow-up issue per wave; discovery budget one new issue per three closures) applies. Part 3 is behavioural: whether orchestrators write the line can be read only from pull requests merged after this batch. I applied the same rule to #1765: it closed on a measurement, and the measurement that could not be made moved here.

| # | Option | Judgement |
|---|---|---|
| 1 | **Keep #1769 open; every M3 says `Refs #1769`.** The orchestrator posts one comment at merge (text in "Batching"), and closes the issue at the review point with the decision | The review point already lives in the issue (trigger, owner, question); no new issue is needed (this batch closes no pre-existing issue, so the discovery budget allows none); closing is then a closure on a verified behaviour, not on a merge. The wait is bounded by the issue's own trigger (ten pull requests), which at the rate the issue's measurement saw is a matter of days |
| 2 | Close with the batch (`Closes #1769` on S2's M3) and put the review point in one checklist entry of the follow-up issue of the wave | Net -1 at once. Needs a follow-up issue of this wave to hold the entry (the open follow-ups I found are #1754 and older: none is this batch's wave), and closes before part 3 is verified. Fallback only if the Captain's backlog metric demands it; then the entry carries the trigger, the command of "Batching" and the question |
| 3 | Close and file a new issue for the review point | Breaks the discovery budget; a reminder is not a reachable defect |
| 4 | Close and leave the review point in the closing comment | An orphaned decision: nothing triggers it |

**The closing condition (for the orchestrator, no Captain).** (1) Ten pull requests merged after this batch's merge commit; (2) every one of them states `Size findings: <n>` for each item or slice (if one does not, the finding is that the sentence is not followed, to be repaired, and the count restarts); (3) the Architect reads the counts and decides whether the Size checklist item stays: all zero means the item costs a line per review for no finding; any non-zero count keeps it and the first use of "deleted without re-review" is audited against the exemption's conditions. The decision is recorded on #1769 and the issue is closed with it. **What the issue's acceptance reads as after S2:** part 1 is met for suggestions by code and for readings by the existing path, documented with its limits (D4); part 2 is met by S1; part 3's sentence is shipped by S1 and awaits its review point. No part of the issue is left without an owner.

**D3. Part 1: where the suggestions go (the smallest route that fits the existing build result).**

| # | Option | Judgement |
|---|---|---|
| 1 | **`review_suggestions: list[str]` beside `review_issues` on `BuildResult` (`builder.py:143`) and on `BuildFailureReport` (`:176`), set at `:3546`'s block whether or not the review approved, copied by `classify_build_failure` (`:219-220`), in the failure report's dict (`:198-199`), in the BUILD_SUCCESS payload (`routers/build.py:508-509`); the success message gains `, Review suggestions: <n>` only when `n > 0`** | Additive at every seam: a new defaulted field, a new dict key, a message that is byte-identical when there is nothing to show. The HXI shows `message` only (`useStore.ts:3799-3806`), so the count is what the Captain sees and the text rides in the payload for any listener, as `review_issues` already does. No new event type, no UI file, no schema |
| 2 | A READINGS or REVIEW block in the Builder's format (`builder.py:2124-2145`), a key on BUILD_GENERATED and a card in `IntentSurface.tsx` | An LLM-facing format and UI for text that already reaches the approval card. Revisit only if the raw output proves unusable |
| 3 | Post the suggestions and readings to the Ward Room or a notebook | Wrong layer: couples the builder to the Ward Room and needs an author identity |
| 4 | Retract the "report size in `suggestions`" line (`config/standing_orders/engineering.md:90`) and the readings sentence (`builder.md:15`) | Reversible but undoes the crew side of AD-1359 |

Sub-decisions of option 1, each with its evidence. **(a) Set before the rejected branch.** The assignment goes directly under `result.review_result = review.summary` and above `if not review.approved:`, so `"; ".join(review.issues)` (which raises on a non-string issue) cannot skip it, and the issue assignment is not touched. **(b) Coerced at the consumer.** `_parse_review` copies the model's JSON as given (`code_reviewer.py:150`), so the value may be null, a string or a list of anything; the producer is not changed (`tests/test_code_reviewer.py` stays as is). **(c) A skipped review is carried as the one suggestion the producer writes** and is counted like any other (limit L3). **(d) The message tail only when `n > 0`:** a build with no suggestions emits the exact message it emitted before (T4 pins it). **(e) No change to `events.py`:** `BuildSuccessEvent` (`events.py:609-617`) is a typed skeleton constructed nowhere in `src` and already narrower than the emitted dict.

**D4. Part 1: the Builder's readings.**

| # | Option | Judgement |
|---|---|---|
| 1 | **No code. The comment on #1769 names the path and the limits** | The prose already reaches the Captain where it matters, before approval: `act()` returns it (`builder.py:2698`, `:2705`; the visiting path's `raw_output` `:2470`; the harness path `:2584`), the route emits it as `llm_output` (`routers/build.py:441-451`), the card shows it under "View Code" (`IntentSurface.tsx:1391-1413`). **Confirmed limits:** (i) collapsed by default (`useState({})`, `:69`); (ii) the Transporter path replaces it with `[Transporter Pattern: n file blocks from parallel chunks]` (`builder.py:2541`): chunked builds have no single report; (iii) after approval nothing carries it: `_execute_build` receives file changes only, and `BuildResult.llm_output` is set nowhere |
| 2 | Carry the prose through approval into `BuildResult.llm_output` and the success event | The route would have to hold the prose between the two requests (a new cache beside `_pending_failures`) for text the Captain has already read. Larger; no consumer |
| 3 | A typed READINGS block | See D3 option 2 |

**D5. Part 2: the shape of the pin.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Cases in `tests/test_standing_orders_layout.py` on the idiom of `test_brake_handoff_does_not_redefine_frozen` (`:488-496`): the marker occurs once, the paragraph is the text up to the next blank line; one named case per condition of the exemption; the exemption sentence verbatim; the paragraph's sentence count (an added sentence can widen the exemption); the constitution's sentence; the reviewers' size tag** | Fits the file ("fix a failing layout test by moving text to its owner ... never by loosening the test"); a failure names the dropped condition; the sentence count closes the additive route to widening. The exemption is the one rule that skips a review round, so its wording is a control, not prose |
| 2 | Pin the whole paragraph verbatim | Closes more, but pins the sentences that are not controls (the leftovers rule and the round-1 rule) and fails on a benign reword |
| 3 | Pin the exemption sentence only | One failure message for any change; misses the exclusion clause and the "review-round repairs only" sentence |
| 4 | A new test file | Duplicates the helpers the layout file already has (`_text`, `ORCHESTRATOR`, `CONSTITUTION`, `_rel`); the issue asks for "alongside the existing ones" |

The other dev-side size rules (the Claude Builder profile's line, the Diff Reviewer **Size** and **Assumptions** items, the Architect profile's item) are **not** pinned beyond the tag (limit L2): part 2 asks for the exemption, a reworded advisory line is not a loosened control, and every extra needle is a future edit someone must make on purpose. The tag line is pinned because the count and the exemption apply only to findings a reviewer tags **size**: a profile that stops tagging makes the count read zero for the wrong reason.

**D6. Part 3: where, in what words, and whether it is pinned.**

| # | Option | Judgement |
|---|---|---|
| 1 | **One paragraph of its own, directly after the Size findings paragraph and before the round-three brake (`orchestrator.agent.md:48-50`), lead `**Size findings count (AD-1359, #1769).**`, one sentence: the review summary of each item or slice in its pull request states `Size findings: <n>`, the findings tagged **size** under the rule above (`0` too: silence is not a count), and names each: deleted in round <k>, deleted without re-review, or filed. One case pins it** | Outside the paragraph part 2 pins (a blank line separates them, and the case asserts the template is not inside the pinned paragraph); inside Review Rounds and Progress (the case asserts it lies between the section's heading and the next); about 295 bytes in a file every orchestrator reads at session start; the "round <k>" form covers a leftover deleted in round 2 or later, which the Size findings paragraph allows ("in any round") and the issue's three labels do not name |
| 2 | Append the sentence to the "A round" paragraph (`:46`) | That paragraph counts rounds; the sentence counts findings, and a later edit of one would carry the other |
| 3 | Add it to the Size findings paragraph | Forbidden by the issue ("outside the Size findings paragraph that part 2 pins"); every edit of the pinned paragraph would then fail part 2's cases |
| 4 | Not pinned | The original failure was a rule nobody could observe; a sentence that can be deleted without any test noticing repeats it |

**Matching words elsewhere: none.** `.github/copilot-instructions.md` already points to **Review Rounds and Progress** by name (`:56`) and carries the exemption's sentence (`:54`); it is injected into every Copilot call and capped at 18,000 bytes (`test_constitution_stays_slim`; 15,960 bytes on disk, CRLF), and the duplicate-sentence detector forbids repeating the profile's rule there. The Diff Reviewer profiles already tell the reviewer to "Tag each size finding **size**, so the orchestrator can apply its Size findings rule" (`:102`, `:109`); the count derives from the tag and the orchestrator writes the summary. `CLAUDE.md` and `claude-architect.md` point to the section by name.

**D7. Public text, numbers, ledger.** No crew name, thread id, timestamp, live count or vessel line appears in any test, comment, tracker line, commit message or this contract (the test texts are synthetic; the issue's own measurement is cited by number only, nothing from a vessel). No AD or BF number is allocated: the work is named `AD-1359 follow-up` with the issue number; commit subjects begin with the plain token `AD-1359` (the ledger keys on the base number and keeps each full token as evidence; a suffix such as `AD-1359b` would add a distinct token). **Predicted ledger movement:** none of any number. AD-1359 is `shipped` through five commit subjects already in the snapshot (`"AD-1359": ["git AD-1359"]`); the plain token adds no new evidence string; a PROGRESS head without a status keyword adds a `mentioned` label and a DECISIONS heading a `shipped` label, which changes no rendered row; the ceilings stay AD-1359 and BF-961. The oracle measures it; section 4 gives the diff shape and the hard stop.

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. All commands run **from the repository root**, exactly as typed. **Who runs what.** The Builder may run only the focused pytest files named in G1 and G2 (always `-n 0 -p no:randomly`) and the architecture check. **Mine (the orchestrator's):** the broad gate, the mutation campaign, any wide run, the ledger comparison against the measured diff, the pull request.

**M0 (each slice, on the head before the slice):** record the collected count (`--collect-only -q`) of every existing file named in that slice's G2; the new file of S2 does not exist yet.

| Slice | M | Blocks | Gate |
|---|---|---|---|
| S1 (parts 2 and 3) | M1 | N1-1 (the import), N1-2 (the 15 cases) | G1 |
| S1 | M2 | P2-1 (the paragraph), then N2-1 and N2-2 (the marker) | G2 |
| S1 | M3 | P3-1, P3-2, ledger | G3 |
| S2 (part 1) | M1 | N1-1 (new file, 16 cases) | G1 |
| S2 | M2 | P2-1 to P2-6 (`builder.py`), P2-7 (`routers/build.py`), then N2-1 (the marker) | G2 |
| S2 | M3 | P3-1, P3-2, ledger | G3 |

**S1.**
- **G1.** `PY -m pytest tests/test_standing_orders_layout.py -q -n 0 -p no:randomly`. **Expected:** `32 passed, 1 xfailed` (33 collected: 18 existing and 15 new; the 14 new controls pass because they pin text that exists, the count case xfails strictly: an XPASS is a FAIL). Then once with `--runxfail`: `1 failed, 32 passed`, the failure at the assert `the count paragraph is missing, moved or duplicated`, never at an import or an index.
- **G2.** `PY -m pytest tests/test_standing_orders_layout.py tests/test_ad1359_agent_size_rules.py -q -n 0 -p no:randomly`. **Expected:** `36 passed` (M0 collects 21: 18 and 3); nothing else in the repository reads the profile (section 11).

**S2.**
- **G1.** `PY -m pytest tests/test_ad1359_followup_review_suggestions.py -q -n 0 -p no:randomly`. **Expected:** `1 passed, 15 xfailed` (16 collected; the one control is T4, the unchanged message; the four cases that run real git need `git` and are skipped without it, which the oracle's host has). Then once with `--runxfail`: `15 failed, 1 passed`, every failure at an `assert`.
- **G2 (suite order).** (1) `PY -m pytest tests/test_builder_agent.py tests/test_builder_api.py tests/test_code_reviewer.py tests/test_build_dispatcher.py tests/test_bf904a_failed_build_restore.py tests/test_bf904b_sealed_core_observation.py tests/test_ad1359_followup_review_suggestions.py -q -n 0 -p no:randomly` (the executor's review step and the report's tests, both events, the dispatcher, the real-git builds, and the new file). (2) `PY -m pytest tests/test_ad1346_admission_build_test_sink.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_egress_census.py tests/test_ad1344_constitution_write_refusal.py tests/test_ad1195_event_persistence_contract.py tests/test_layer_boundaries.py tests/test_events.py -q -n 0 -p no:randomly` (they read `builder.py` and `routers/build.py` by file and scope, not by line: section 11). (3) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file 16 passed; every other file 0 failed with collected counts equal M0; the check clean (no class gains a method or a body line: the edit adds two fields, one module function and statements inside existing functions).

**G3 (each M3).** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. The ledger covers AD and BF numbers (`scripts/gen_ad_ledger.py:113`, `_TOKEN_RE`); it reads the head of a PROGRESS entry, a DECISIONS heading and the git-log subjects (`collect_git_layer`, `:281-343`), and records each distinct full token per number once. **Expected movement of each M3: no number.** Every M3 changes `docs/development/ad-ledger-snapshot.json` (`captured_at`, `head`, `subject_count`: numstat `3 3`) and the report (the git-log row; the two `PROGRESS.md:<line>` entries of "Unparseable lines", which move by the lines the entry adds: numstat `3 3`); `DECISIONS.md` gains 8 lines and `PROGRESS.md` 4 (numstat `8 0` and `4 0`), per slice. **Any changed row of a number is a hard stop for the Architect** (none is expected: AD-1359 stays `shipped`, the ceilings stay AD-1359 and BF-961, the lifecycle counts do not move). The oracle measures all four numstats; this batch's own commit subjects are the only subjects the snapshot has not seen, apart from the earlier batches' last ones, whose tokens are already recorded.

**Final gate (mine, once, after the Diff Reviewer's findings are repaired and the reviewed tree is committed locally):** the mutation rows of section 9, and `PY scripts/run_test_gate.py --label ad1359-followup --receipt logs/gates/ad1359-followup.receipt.json` (its preflight runs the ledger, the three config checks, the architecture, seam and store checks). **Harness rule.** No source change made to pass a test, no skip, no loosened assertion; a failing new case at G2, or any existing test failing, goes back to the Architect.

## 5. Commit messages

- **Contract commit (the orchestrator's):** `AD-1359 follow-up: contract for the size-rule pins, the size-findings count and the review suggestions on the build result (#1769)`.
- **S1 M1:** `AD-1359 follow-up S1 M1: layout tests pin the size exemption, the reviewers' size tag and the size-findings count sentence, xfail where unbuilt (#1769)`
- **S1 M2:** `AD-1359 follow-up S1 M2: each item's review summary states its size findings count (#1769)`
- **S1 M3:** `AD-1359 follow-up S1 M3: trackers and ledger (#1769)`; its body ends with the line `Refs #1769.`
- **S2 M1:** `AD-1359 follow-up S2 M1: tests for the review's suggestions reaching the build result, the failure report and the success event, xfail until built (#1769)`
- **S2 M2:** `AD-1359 follow-up S2 M2: the code review's suggestions are carried on the build result, the failure report and the success event, and the success message counts them (#1769)`
- **S2 M3:** `AD-1359 follow-up S2 M3: trackers and ledger (#1769)`; its body ends with the line `Refs #1769.`

**No message carries `Closes`** (decision D2, option 1): #1769 stays open for its review point; the pull request body says `Refs #1769` and states what remains. If the Captain or the orchestrator prefers option 2, only the last line of S2 M3's body changes to `Closes #1769.`, and the review-point entry moves to the wave's follow-up issue before the merge. No message names a crew member, a thread or a live figure.

## 6. Tests

**S1 (`tests/test_standing_orders_layout.py`, 15 new cases appended after `test_brake_handoff_does_not_redefine_frozen`).** Imports: `pytest` is added (one line); everything else is the file's own (`_text`, `_rel`, `_SENTENCE_END`, `ORCHESTRATOR`, `CONSTITUTION`, `_AGENTS_DIR`, `_REPO_ROOT`). Each case reads the working copy through `_text`, which returns LF text whatever the checkout's line endings. `built` is `pytest.mark.xfail(raises=AssertionError, strict=True)` and is removed again at M2 (N2-1, N2-2). The paragraph under test is found as the file's idiom does: the marker occurs once, the text after it up to the next blank line.

| Case | Kind | Asserts |
|---|---|---|
| E[carve-out] | control | the paragraph holds `unless the extra code breaks something` |
| E[only-repair] | control | `When a deletion is the round's only repair` |
| E[exempt-set] | control | `removes only imports, or bindings whose value makes no call,` (a call in the exempt set changes this text) |
| E[added-by-this-change] | control | `that this change added` |
| E[unreferenced] | control | `and nothing references` |
| E[plus-lines] | control | `every deleted line is a `+` line of the candidate's diff` |
| E[git-grep] | control | the repo-wide `git grep` condition, whole |
| E[focused-tests] | control | `run the focused tests and start no further review round` |
| E[delta-review] | control | the exclusion clause, whole: `A deleted `def`, class, decorator or call, an import marked `noqa` or inside a `try`, ... counts as a round.` |
| E[review-rounds-only] | control | `The exemption covers review-round repairs only: ...follows the brake below.` |
| X1 | control | the exemption sentence verbatim; and the paragraph has exactly 7 sentences (a sentence added anywhere can widen the exemption; the failure says to add it to the test on purpose) |
| C1 | control | the constitution holds its sentence verbatim: `One review-round repair needs no re-review: a size repair that only deletes unreferenced imports or call-free bindings the change added (**Size findings** in `.github/agents/orchestrator.agent.md`).` |
| R[diff-reviewer.agent.md], R[claude-diff-reviewer.md] | control | each reviewer profile exists and holds `Tag each size finding **size**, so the orchestrator can apply its Size findings rule.` |
| K1 | **built** | the count marker occurs once; the text after it is the count sentence verbatim; the marker lies between the heading of Review Rounds and Progress and the next `## ` heading; the template `Size findings: <n>` is not inside the pinned paragraph |

K1 fails on the base at its first assert (the marker count is 0), which is an `AssertionError`; no later line can raise on the base.

**S2 (`tests/test_ad1359_followup_review_suggestions.py`, new; 16 cases).** Imports: the existing modules only (`probos.cognitive.builder`, `probos.events`, `pytest`). Fixtures are the BF-904a and BF-904b files' own (`_control_env`, `_git`, `_init_repo`, `_FakeModel`, `_Runtime`, `_route_modules`), copied, not imported (`tests/test_bf904b_sealed_core_observation.py:44-134`, `tests/test_bf904a_failed_build_restore.py:96-130, 237-245, 265-270`). The model is a fake whose every answer is the review's JSON: the code review is the only model call a build without tests makes. `built` is `pytest.mark.xfail(raises=AssertionError, strict=True)`, redefined as a pass-through at M2 (N2-1, the earlier contracts' form). **Every case that could fail on the base fails at an `assert`:** the new key is read with `.get` and the new attribute with `getattr(obj, name, None)`, the helper is looked up with `getattr(builder_module, "_review_suggestions", None)` and asserted present, and no case unpacks a list or reads an index before asserting its length (`_one`). Every case restores what it patches (`monkeypatch`, `patch`); the failure cache is replaced by a dict of the case's own (`monkeypatch.setattr(build_router, "_pending_failures", {})`), so no entry reaches the shared cache. **The Architect could not run the real-git harness** (a read-only consult): it has the shape of the BF-904a and BF-904b helpers it copies, which are in the suite at `0ef819ca` (not run here), and the first assertions of T1 to T3 after the build name what failed (`_one` on the event, the `premise` messages), so the oracle sees at once whether the build reached the route's emission.

| Case | Kind | Asserts |
|---|---|---|
| T1 the seam, success | **built** (git) | a real repository; the real `_execute_build`, the real `execute_approved_build` and the real `CodeReviewAgent` over a fake model whose review approves with two suggestions: the one BUILD_SUCCESS payload holds `review_suggestions == [the two]`, still holds `review`, `review_issues == []` and a commit, and its message ends `, Review suggestions: 2` |
| T2 a rejected review, list / null | **built** (git), 2 cases | `execute_approved_build` over a rejected review (`approved: false`, `issues: ["Bad import"]`) still commits (the soft gate), keeps `review_issues` and `review_result`, and `review_suggestions` is the list / `[]` for `null` (the assignment precedes the rejected branch; a malformed value does not skip the issues) |
| T3 the seam, failure | **built** (git) | a build whose created file does not parse fails after its review: the one BUILD_FAILURE payload's `report` dict holds `review_suggestions == [the two]` and the cached report object holds the same |
| T4 compatibility | control | with no suggestions the success message is exactly `\u2b22 Build complete! Branch: builder/probe, Commit: abc1234, Files: 1, Tests: passed` and the payload holds every key it held before |
| T5 the count | **built** | a result carrying three suggestions: the payload's `review_suggestions` is the three and the message ends `, Review suggestions: 3` |
| T6 the field | **built** | a new `BuildResult` has `review_suggestions == []`, and two instances do not share the list |
| T7 the report copies | **built** | `classify_build_failure` returns a report whose `review_suggestions` equals the result's and is a copy |
| T8 the report's dict | **built** | `BuildFailureReport().to_dict()` holds `review_suggestions == []`, and a set value appears |
| T9 coercion, 7 cases | **built** | `_review_suggestions`: `None` gives `[]`; a bare string gives that one; `[]` gives `[]`; `["keep", "", "   ", None, 3, {"k": "v"}]` gives `["keep", "3", "{'k': 'v'}"]`; a tuple of two strings gives both; a mapping and a number give `[]` |

T1 to T3 and the cases of T9 are the "what discards a correct result" cases: a correct suggestion list can be lost by a malformed `issues` (ordering), by blank items (dropped on purpose), by a copy missing from the report, and by a payload key missing at the route. T1 and T3 cross each seam in one test (model reply, parse, executor, result, route, payload); T5 to T8 localise a failure the seam cases report.

## 7. The contract

Labels restart in each slice. Section 6 names the cases; this section gives every block. `PY`, the commands and who runs them are in section 4. SEARCH text is LF; the working copies are CRLF (the apply tool matches on LF). **Every SEARCH below occurs exactly once in its file on `0ef819ca`, starts at a line start, and is ASCII** (section 11: run on the LF blobs, and again on the patched text for the SEARCHes of later blocks of the same file); no block's SEARCH overlaps another's; **a block's REPLACE changes the line count of a later block's position but not its text**, so the blocks of one file are applied in label order and none re-measures a line number. The REPLACE text of every block is ASCII. A label line names one file path and sits directly above its `SEARCH:` line.

### 7.1 Slice S1 (parts 2 and 3: the pins and the count)

#### S1 M1

**N1-1** (`tests/test_standing_orders_layout.py`: the import; it adds one line above N1-2's position).
SEARCH:
```
from pathlib import Path

import yaml
```
REPLACE:
```
from pathlib import Path

import pytest
import yaml
```

**N1-2** (`tests/test_standing_orders_layout.py`: the fifteen cases, after `test_brake_handoff_does_not_redefine_frozen`; the SEARCH is the last two lines of that test and the REPLACE keeps them byte-identical).
SEARCH:
```
    assert "in one of two forms and no other" in brake, "the paragraph under test is not the handoff clause"
    assert not re.search(r"\bfrozen\b", brake, re.IGNORECASE), "the brake paragraph uses 'frozen' again"
```
REPLACE:
```
    assert "in one of two forms and no other" in brake, "the paragraph under test is not the handoff clause"
    assert not re.search(r"\bfrozen\b", brake, re.IGNORECASE), "the brake paragraph uses 'frozen' again"


# --- the Size findings exemption and its count (AD-1359 follow-up, #1769) ---------

built = pytest.mark.xfail(raises=AssertionError, strict=True)  # M1 of the follow-up; M2 removes it

SIZE_FINDINGS_MARKER = "**Size findings (AD-1359, #1765).**"
SIZE_COUNT_MARKER = "**Size findings count (AD-1359, #1769).**"
REVIEW_ROUNDS_HEADING = "\n## Review Rounds and Progress (Standing Order)\n"
SIZE_FINDINGS_SENTENCES = 7  # the paragraph's sentences; one added anywhere can widen the exemption

# One entry per condition of the Size findings paragraph's no-review exemption, and its carve-out. A repair that
# deletes only what this change added and nothing uses skips a review round, so dropping or loosening any entry
# widens the one rule that skips a review. Each text occurs once in the paragraph.
SIZE_EXEMPTION_PARTS: tuple[tuple[str, str], ...] = (
    ("carve-out", "unless the extra code breaks something"),
    ("only-repair", "When a deletion is the round's only repair"),
    ("exempt-set", "removes only imports, or bindings whose value makes no call,"),
    ("added-by-this-change", "that this change added"),
    ("unreferenced", "and nothing references"),
    ("plus-lines", "every deleted line is a `+` line of the candidate's diff"),
    (
        "git-grep",
        "a repo-wide `git grep` for each deleted name, config, docs and tests included, finds no other use",
    ),
    ("focused-tests", "run the focused tests and start no further review round"),
    (
        "delta-review",
        "A deleted `def`, class, decorator or call, an import marked `noqa` or inside a `try`, and any other size "
        "repair, such as reverting a change to neighbouring code, gets a delta review, which counts as a round.",
    ),
    (
        "review-rounds-only",
        "The exemption covers review-round repairs only: a repair after a failed gate or CI follows the brake below.",
    ),
)
SIZE_EXEMPTION_SENTENCE = (
    "When a deletion is the round's only repair and removes only imports, or bindings whose value makes no call, "
    "that this change added and nothing references (every deleted line is a `+` line of the candidate's diff, and a "
    "repo-wide `git grep` for each deleted name, config, docs and tests included, finds no other use), run the "
    "focused tests and start no further review round."
)
CONSTITUTION_SIZE_EXEMPTION = (
    "One review-round repair needs no re-review: a size repair that only deletes unreferenced imports or "
    "call-free bindings the change added (**Size findings** in `.github/agents/orchestrator.agent.md`)."
)
SIZE_TAG = "Tag each size finding **size**, so the orchestrator can apply its Size findings rule."
DIFF_REVIEWER_PROFILES = (
    _AGENTS_DIR / "diff-reviewer.agent.md",
    _REPO_ROOT / ".claude" / "agents" / "claude-diff-reviewer.md",
)
SIZE_COUNT_SENTENCE = (
    "The review summary of each item or slice in its pull request states `Size findings: <n>`, the findings tagged "
    "**size** under the rule above (`0` too: silence is not a count), and names each: deleted in round <k>, deleted "
    "without re-review, or filed."
)


def _size_findings_paragraph() -> str:
    """The orchestrator's Size findings paragraph: the text after its marker up to the next blank line."""
    orchestrator = _text(ORCHESTRATOR)
    assert orchestrator.count(SIZE_FINDINGS_MARKER) == 1, "the Size findings paragraph moved or was duplicated"
    return orchestrator.split(SIZE_FINDINGS_MARKER, 1)[1].split("\n\n", 1)[0].strip()


@pytest.mark.parametrize(
    ("label", "text"), SIZE_EXEMPTION_PARTS, ids=[label for label, _ in SIZE_EXEMPTION_PARTS],
)
def test_size_findings_keeps_each_condition_of_the_no_review_exemption(label: str, text: str) -> None:
    assert text in _size_findings_paragraph(), f"the Size findings paragraph lost or changed its {label} condition"


def test_size_findings_exemption_sentence_is_verbatim_and_the_paragraph_adds_no_other_sentence() -> None:
    paragraph = _size_findings_paragraph()
    assert SIZE_EXEMPTION_SENTENCE in paragraph, "the exemption sentence changed"
    sentences = [sentence for sentence in _SENTENCE_END.split(paragraph) if sentence]
    assert len(sentences) == SIZE_FINDINGS_SENTENCES, (
        f"the Size findings paragraph has {len(sentences)} sentences, not {SIZE_FINDINGS_SENTENCES}: a sentence "
        "added here can widen the exemption, so change this test on purpose"
    )


def test_constitution_states_the_size_exemption() -> None:
    assert CONSTITUTION_SIZE_EXEMPTION in _text(CONSTITUTION), "the constitution's size-exemption sentence changed"


@pytest.mark.parametrize("profile", DIFF_REVIEWER_PROFILES, ids=[path.name for path in DIFF_REVIEWER_PROFILES])
def test_diff_reviewer_profiles_tag_size_findings(profile: Path) -> None:
    """The orchestrator's size rules and its count apply to findings a reviewer tags size."""
    assert profile.is_file(), f"{_rel(profile)} is missing"
    assert SIZE_TAG in _text(profile), f"{_rel(profile)} no longer tells the reviewer to tag size findings"


@built
def test_review_summaries_state_the_size_findings_count() -> None:
    """Each item's review summary states how many size findings it had, zero included (#1769): a pull request that
    says nothing cannot be told from one that had none. The sentence has its own paragraph, outside the pinned one."""
    orchestrator = _text(ORCHESTRATOR)
    assert orchestrator.count(SIZE_COUNT_MARKER) == 1, "the count paragraph is missing, moved or duplicated"
    count = orchestrator.split(SIZE_COUNT_MARKER, 1)[1].split("\n\n", 1)[0].strip()
    assert count == SIZE_COUNT_SENTENCE, "the count sentence changed"
    assert orchestrator.count(REVIEW_ROUNDS_HEADING) == 1, "premise: the section heading is unique"
    start = orchestrator.index(REVIEW_ROUNDS_HEADING)
    end = orchestrator.index("\n## ", start + len(REVIEW_ROUNDS_HEADING))
    assert start < orchestrator.index(SIZE_COUNT_MARKER) < end, "the count paragraph is outside its section"
    assert "Size findings: <n>" not in _size_findings_paragraph(), "the count sentence is inside the pinned paragraph"
```

#### S1 M2

**P2-1** (`.github/agents/orchestrator.agent.md`: the count paragraph, between the Size findings paragraph and the round-three brake; the SEARCH is the first words of the brake's line and the REPLACE keeps that prefix, so the rest of the line, and the `PROCEDURE` needles in it, are untouched; it adds 2 lines).
SEARCH:
```
**Round-three brake (Captain, 2026-10-15).** Do not start a fourth round on your own, whatever leads to it:
```
REPLACE:
```
**Size findings count (AD-1359, #1769).** The review summary of each item or slice in its pull request states `Size findings: <n>`, the findings tagged **size** under the rule above (`0` too: silence is not a count), and names each: deleted in round <k>, deleted without re-review, or filed.

**Round-three brake (Captain, 2026-10-15).** Do not start a fourth round on your own, whatever leads to it:
```

**N2-1** (`tests/test_standing_orders_layout.py`: the marker constant; it removes 2 lines).
SEARCH:
```
built = pytest.mark.xfail(raises=AssertionError, strict=True)  # M1 of the follow-up; M2 removes it

SIZE_FINDINGS_MARKER = "**Size findings (AD-1359, #1765).**"
```
REPLACE:
```
SIZE_FINDINGS_MARKER = "**Size findings (AD-1359, #1765).**"
```

**N2-2** (`tests/test_standing_orders_layout.py`: the decorator; it removes 1 line).
SEARCH:
```
@built
def test_review_summaries_state_the_size_findings_count() -> None:
```
REPLACE:
```
def test_review_summaries_state_the_size_findings_count() -> None:
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it. Replace `DATE` with M3's date. The entry is 4 lines (heading, two bullets, blank).
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1359 follow-up slice 1 (DATE), #1769 -- the size exemption is pinned by layout tests, and each item's review summary states its size findings count.**
- **Base.** Reverting the orchestrator's Size findings paragraph or the constitution's sentence about it left the suite green, and no pull request said whether a size finding had occurred, so a silent record read the same as none.
- **Change.** `tests/test_standing_orders_layout.py` pins each condition of the no-review exemption, its exclusion clause, the review-round-only sentence, the paragraph's sentence count, the constitution's sentence and the reviewers' size tag; the orchestrator profile gains one paragraph: the review summary of each item or slice states `Size findings: <n>` (0 too) and names each finding. Text and tests only; the other dev-side size rules stay unpinned. Contract `prompts/ad-1359-followup-size-suggestions-and-pins.md`, slice S1. Refs #1769, which stays open for its review point.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows the BF and AD entries of this period (once on `0ef819ca`, at line 1732; the two earlier batches' entries are inserted before it, and each entry of this batch is inserted before it as well, so the order is the order of landing). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date. The entry is 8 lines (heading, blank, five bullets, blank).
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### AD-1359 follow-up slice 1 -- The size exemption is pinned by layout tests and each item's review summary states its size findings count (DATE, #1769)

- *Scope.* `tests/test_standing_orders_layout.py` (15 cases), `.github/agents/orchestrator.agent.md` (one paragraph under Review Rounds and Progress). Contract `prompts/ad-1359-followup-size-suggestions-and-pins.md`.
- *G1 (what is pinned).* The orchestrator's Size findings paragraph: each condition of its no-review exemption and its carve-out for a size finding that breaks something, the exclusion clause, the review-round-only sentence, and the paragraph's sentence count (a sentence added is a decision made in the test); the constitution's sentence about the same exemption; the reviewers' size tag. Rejected: pinning the whole paragraph (it fails on a benign reword), pinning the exemption sentence alone, and pinning the other dev-side size rules (part 2 asks for the exemption).
- *G2 (the count).* One sentence in a paragraph of its own after the Size findings paragraph: `Size findings: <n>`, zero stated, each finding named by how it ended. It lies outside the pinned paragraph; the constitution and the reviewer profiles need no matching word (the reviewers already tag size; the orchestrator writes the summary). Review point after ten pull requests: if every count is zero, the Architect decides whether the Size checklist item stays.
- *G3 (public text).* No crew name, thread id, timestamp or live figure in any test, comment, tracker line or commit message of the batch.
- *Residual.* L1 to L5 of the contract (S1). *Reversal.* Revert the slice 1 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.2 Slice S2 (part 1: the suggestions on the build result)

#### S2 M1

**N1-1.** New file `tests/test_ad1359_followup_review_suggestions.py` (16 cases; section 6 names them). It imports nothing that M2 creates at module level: the helper is looked up with `getattr(builder_module, "_review_suggestions", None)` and asserted present, and the new field and key are read with `getattr` and `.get`, so every `built` case stops at an `assert` on the base.

```python
"""AD-1359 follow-up (#1769): the code review's suggestions reach the build result, the failure report and the success event.

``CodeReviewAgent`` returns ``suggestions`` (the crew's size findings among them) and nothing read them. The executor
now carries them as ``BuildResult.review_suggestions`` whether or not the review approved, the failure report copies
them, and the approval route's success event carries them and counts them in its message. Real git in repositories
under ``tmp_path`` (helpers copied from the BF-904a and BF-904b tests), the real executor, the real ``CodeReviewAgent``
over a fake model client and the real ``_execute_build``. The cases marked ``built`` fail on the base at their own
assert and pass once M2 is applied; ``--runxfail`` runs them as plain cases. Synthetic text only.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive.builder import (
    BuildFailureReport,
    BuildResult,
    BuildSpec,
    classify_build_failure,
    execute_approved_build,
)
from probos.events import EventType

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
BAD = "src/probos/bad.py"
BROKEN = "def broken(:\n"
SUGGESTIONS = ["Delete the unused helper; the spec does not need it", "Name the size of the change in the summary"]

# The real runner, captured at import: the tests' own git calls go through it.
_REAL_RUN = subprocess.run

built = pytest.mark.xfail(raises=AssertionError, strict=True)


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``GIT_*`` name from the process environment for the test's duration."""
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "ad1359@example.invalid"),
        ("config", "user.name", "AD1359 Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    target = path / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x = 1\n")
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _spec() -> BuildSpec:
    return BuildSpec(title="ad1359 probe", description="")


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


def _reply(*, approved: bool, issues: list[str], suggestions: object, summary: str) -> str:
    """The review's JSON as the code review agent asks the model to write it."""
    return json.dumps({"approved": approved, "issues": issues, "suggestions": suggestions, "summary": summary})


class _FakeModel:
    """A model client whose every answer is *reply*: the code review is the only call a build without tests makes."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=SimpleNamespace(content=reply))


class _Runtime:
    """What the approval route reads from a runtime: ``emit_event`` and ``llm_client``. It has no config, so the
    sealed-core observation is off."""

    def __init__(self, llm_client: object | None = None) -> None:
        self.emit_event = MagicMock()
        self.llm_client = llm_client


def _route_modules() -> tuple[Any, Any]:
    """``(probos.api, probos.routers.build)``: the second takes its failure cache from the first, so it loads first."""
    import probos.api as api_module
    from probos.routers import build as build_router

    return api_module, build_router


def _events(rt: _Runtime, event_type: EventType) -> list[dict[str, Any]]:
    return [call.args[1] for call in rt.emit_event.call_args_list if call.args[0] == event_type]


def _one(items: list[Any], what: str) -> Any:
    assert len(items) == 1, f"expected exactly one {what}, found {len(items)}"
    return items[0]


def _committed() -> BuildResult:
    """What the executor returns for a build that committed, with no suggestions."""
    return BuildResult(
        success=True, spec=_spec(), branch_name="builder/probe", commit_hash="abc1234",
        files_written=[TARGET], tests_passed=True,
    )


async def _approve(build_router: Any, rt: _Runtime, repo: Path, changes: list[dict[str, Any]], build_id: str) -> None:
    """Run the approval route's background build over *repo*, bounded."""
    await asyncio.wait_for(
        build_router._execute_build(build_id, changes, _spec(), str(repo), rt, run_tests=False), timeout=120,
    )


# --- the seams, with real git ---------------------------------------------------------------------------------------


@needs_git
@built
async def test_a_reviews_suggestions_reach_the_success_event_through_the_real_executor(tmp_path: Path) -> None:
    _, build_router = _route_modules()
    repo = _init_repo(tmp_path / "repo")
    reply = _reply(approved=True, issues=[], suggestions=SUGGESTIONS, summary="Looks fine")
    rt = _Runtime(_FakeModel(reply))
    await _approve(build_router, rt, repo, [_modify(TARGET, "x = 1", "x = 2")], "t1")
    payload = _one(_events(rt, EventType.BUILD_SUCCESS), "BUILD_SUCCESS event")
    assert payload["commit"], "premise: the build committed"
    assert payload["review"] == "Looks fine"
    assert payload["review_issues"] == []
    assert payload.get("review_suggestions") == SUGGESTIONS
    assert payload["message"].endswith(", Review suggestions: 2")


@needs_git
@built
@pytest.mark.parametrize(
    ("suggestions", "expected"),
    [
        pytest.param(["Delete the unused helper"], ["Delete the unused helper"], id="list"),
        pytest.param(None, [], id="null"),
    ],
)
async def test_a_rejected_review_keeps_its_issues_and_carries_its_suggestions(
    tmp_path: Path, suggestions: object, expected: list[str],
) -> None:
    repo = _init_repo(tmp_path / "repo")
    model = _FakeModel(_reply(approved=False, issues=["Bad import"], suggestions=suggestions, summary="Rejected"))
    result = await asyncio.wait_for(
        execute_approved_build(
            [_modify(TARGET, "x = 1", "x = 2")], _spec(), str(repo), run_tests=False, llm_client=model,
        ),
        timeout=120,
    )
    assert result.success is True, f"premise: the review is a soft gate and the build commits: {result.error}"
    assert result.review_issues == ["Bad import"]
    assert result.review_result == "Rejected"
    assert getattr(result, "review_suggestions", None) == expected


@needs_git
@built
async def test_a_failed_builds_report_carries_the_suggestions_through_the_real_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, build_router = _route_modules()
    cache: dict[str, Any] = {}
    monkeypatch.setattr(build_router, "_pending_failures", cache)  # keep the entry out of the shared cache
    repo = _init_repo(tmp_path / "repo")
    reply = _reply(approved=True, issues=[], suggestions=SUGGESTIONS, summary="Looks fine")
    rt = _Runtime(_FakeModel(reply))
    await _approve(build_router, rt, repo, [_create(BAD, BROKEN)], "t3")
    failure = _one(_events(rt, EventType.BUILD_FAILURE), "BUILD_FAILURE event")
    assert "report" in failure, "premise: the executor reported a failure and the route classified it"
    assert failure["report"].get("review_suggestions") == SUGGESTIONS
    assert getattr(cache["t3"]["report"], "review_suggestions", None) == SUGGESTIONS


# --- the route and the report, without git --------------------------------------------------------------------------


async def test_the_success_message_and_payload_are_unchanged_without_suggestions() -> None:
    _, build_router = _route_modules()
    rt = _Runtime()
    with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=_committed()):
        await build_router._execute_build("t4", [], _spec(), "unused", rt)
    payload = _one(_events(rt, EventType.BUILD_SUCCESS), "BUILD_SUCCESS event")
    assert payload["message"] == "\u2b22 Build complete! Branch: builder/probe, Commit: abc1234, Files: 1, Tests: passed"
    old_keys = {
        "build_id", "branch", "commit", "files_written", "tests_passed", "test_result", "review", "review_issues",
        "message",
    }
    assert old_keys <= set(payload)


@built
async def test_the_success_event_carries_the_suggestions_and_their_count() -> None:
    _, build_router = _route_modules()
    rt = _Runtime()
    result = _committed()
    result.review_suggestions = ["first", "second", "third"]
    with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=result):
        await build_router._execute_build("t5", [], _spec(), "unused", rt)
    payload = _one(_events(rt, EventType.BUILD_SUCCESS), "BUILD_SUCCESS event")
    assert payload.get("review_suggestions") == ["first", "second", "third"]
    assert payload["message"].endswith(", Review suggestions: 3")


@built
def test_a_build_result_starts_with_no_suggestions_of_its_own() -> None:
    first = BuildResult(success=True, spec=_spec())
    second = BuildResult(success=True, spec=_spec())
    assert getattr(first, "review_suggestions", None) == []
    assert getattr(second, "review_suggestions", None) == []
    first.review_suggestions.append("only the first")
    assert second.review_suggestions == [], "two results must not share one list"


@built
def test_a_failure_report_copies_the_results_suggestions() -> None:
    spec = _spec()
    result = BuildResult(success=False, spec=spec, error="Tests failed after 2 fix attempt(s).")
    result.review_suggestions = ["a", "b"]
    report = classify_build_failure(result, spec)
    assert getattr(report, "review_suggestions", None) == ["a", "b"]
    result.review_suggestions.append("later")
    assert report.review_suggestions == ["a", "b"], "the report holds a copy"


@built
def test_a_failure_reports_dict_carries_the_suggestions() -> None:
    report = BuildFailureReport()
    assert report.to_dict().get("review_suggestions") == []
    report.review_suggestions = ["a"]
    assert report.to_dict().get("review_suggestions") == ["a"]


@built
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, [], id="null"),
        pytest.param("a lone suggestion", ["a lone suggestion"], id="bare-string"),
        pytest.param([], [], id="empty-list"),
        pytest.param(["keep", "", "   ", None, 3, {"k": "v"}], ["keep", "3", "{'k': 'v'}"], id="mixed-items"),
        pytest.param(("x", "y"), ["x", "y"], id="tuple"),
        pytest.param({"k": "v"}, [], id="mapping"),
        pytest.param(5, [], id="number"),
    ],
)
def test_the_reviews_suggestions_are_coerced_to_non_blank_strings(raw: object, expected: list[str]) -> None:
    helper = getattr(builder_module, "_review_suggestions", None)
    assert helper is not None, "the helper does not exist yet"
    assert helper(raw) == expected
```

#### S2 M2

**P2-1** (`src/probos/cognitive/builder.py`: `BuildResult`'s field; it adds 1 line).
SEARCH:
```
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    builder_source: str = "native"  # "native" | "visiting" | "native_harness" (AD-353/546)
```
REPLACE:
```
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    review_suggestions: list[str] = field(default_factory=list)  # AD-1359 follow-up (#1769): the review's suggestions, approved or not
    builder_source: str = "native"  # "native" | "visiting" | "native_harness" (AD-353/546)
```

**P2-2** (`src/probos/cognitive/builder.py`: `BuildFailureReport`'s field; it adds 1 line).
SEARCH:
```
    # Review
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)

    # Resolution options
```
REPLACE:
```
    # Review
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    review_suggestions: list[str] = field(default_factory=list)  # AD-1359 follow-up (#1769): copied from the build result

    # Resolution options
```

**P2-3** (`src/probos/cognitive/builder.py`: the report's dict; it adds 1 line).
SEARCH:
```
            "review_issues": self.review_issues,
            "resolution_options": self.resolution_options,
```
REPLACE:
```
            "review_issues": self.review_issues,
            "review_suggestions": self.review_suggestions,
            "resolution_options": self.resolution_options,
```

**P2-4** (`src/probos/cognitive/builder.py`: `classify_build_failure` copies the list; it adds 1 line).
SEARCH:
```
        review_issues=list(result.review_issues),
        raw_error=result.error or result.test_result or "",
```
REPLACE:
```
        review_issues=list(result.review_issues),
        review_suggestions=list(result.review_suggestions),
        raw_error=result.error or result.test_result or "",
```

**P2-5** (`src/probos/cognitive/builder.py`: the helper, directly above `execute_approved_build`, its only caller; it adds 14 lines).
SEARCH:
```
BuilderAgent = SoftwareEngineerAgent


async def execute_approved_build(
```
REPLACE:
```
BuilderAgent = SoftwareEngineerAgent


def _review_suggestions(raw: object) -> list[str]:
    """AD-1359 follow-up (#1769): the code review's ``suggestions`` as a list of non-blank strings.

    ``CodeReviewAgent._parse_review`` copies the model's JSON as given, so the value may be null, a string or a list
    of anything: a bare string is one suggestion, a None or blank item is dropped, any other item is its text, and
    any other value is no suggestion. Never raises (the items are what ``json`` decodes).
    """
    items = [raw] if isinstance(raw, str) else raw
    if not isinstance(items, (list, tuple)):
        return []
    return [text for text in (str(item).strip() for item in items if item is not None) if text]


async def execute_approved_build(
```

**P2-6** (`src/probos/cognitive/builder.py`: the assignment, above the rejected branch; it adds 2 lines).
SEARCH:
```
                result.review_result = review.summary
                if not review.approved:
```
REPLACE:
```
                result.review_result = review.summary
                # AD-1359 follow-up (#1769): set here, above the rejected branch, so nothing there can skip it.
                result.review_suggestions = _review_suggestions(review.suggestions)
                if not review.approved:
```

**P2-7** (`src/probos/routers/build.py`: the success payload and message; it adds 2 lines).
SEARCH:
```
                "review_issues": result.review_issues,
                "message": (
                    f"\u2b22 Build complete! Branch: {result.branch_name}, "
                    f"Commit: {result.commit_hash}, "
                    f"Files: {len(result.files_written) + len(result.files_modified)}, "
                    f"Tests: {'passed' if result.tests_passed else 'FAILED'}"
                ),
```
REPLACE:
```
                "review_issues": result.review_issues,
                "review_suggestions": result.review_suggestions,  # AD-1359 follow-up (#1769)
                "message": (
                    f"\u2b22 Build complete! Branch: {result.branch_name}, "
                    f"Commit: {result.commit_hash}, "
                    f"Files: {len(result.files_written) + len(result.files_modified)}, "
                    f"Tests: {'passed' if result.tests_passed else 'FAILED'}"
                    + (f", Review suggestions: {len(result.review_suggestions)}" if result.review_suggestions else "")
                ),
```

**N2-1** (`tests/test_ad1359_followup_review_suggestions.py`: the marker, after P2-1 to P2-7).
SEARCH:
```
_REAL_RUN = subprocess.run

built = pytest.mark.xfail(raises=AssertionError, strict=True)
```
REPLACE:
```
_REAL_RUN = subprocess.run


def built(func):
    """AD-1359 follow-up M2: the built cases pass; the marker no longer fails them."""
    return func
```

#### S2 M3: tracking

**P3-1.** `PROGRESS.md`. Anchor and rules as S1 M3's P3-1 (the entry lands above S1's: the SEARCH is the same title line and blank line). Replace `DATE`. The entry is 4 lines.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1359 follow-up slice 2 (DATE), #1769 -- the code review's suggestions now reach the build result, the failure report and the success event, and the success message counts them.**
- **Base.** `ReviewResult.suggestions` had one reader, a test: the crew's size findings, which its standing order sends to `suggestions`, went nowhere, and a review skipped after a model error was approved without a trace.
- **Change.** `BuildResult.review_suggestions` and `BuildFailureReport.review_suggestions` (empty by default; set whether or not the review approved; the model's JSON coerced to non-blank strings); the success payload and the failure report's dict gain the key, and the success message ends `, Review suggestions: <n>` only when there are any. No new event type, no UI change. The Builder's written readings need no code: they reach the approval card as `llm_output`, collapsed under "View Code", and the Transporter path carries a placeholder instead (limit L4). Contract `prompts/ad-1359-followup-size-suggestions-and-pins.md`, slice S2. Refs #1769, which stays open for its review point.

```

**P3-2.** `DECISIONS.md`. Anchor and rules as S1 M3's P3-2 (this entry lands after S1's, in slice order, because S1's entry is already above the heading when S2 M3 applies). Replace `DATE`. The entry is 8 lines.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### AD-1359 follow-up slice 2 -- The code review's suggestions are carried on the build result, the failure report and the success event (DATE, #1769)

- *Scope.* `cognitive/builder.py` (two fields, one helper, one assignment, one copy, one dict key), `routers/build.py` (one payload key, one message tail), one test file. Contract `prompts/ad-1359-followup-size-suggestions-and-pins.md`.
- *G1 (shape).* `review_suggestions: list[str]` beside `review_issues` on `BuildResult` and `BuildFailureReport`, the same key in the failure report's dict and in the success payload; the success message gains `, Review suggestions: <n>` only when n is above zero, so a message without suggestions is byte-identical. Rejected: a typed readings block in the Builder's format and a card for it (an LLM-facing format and UI for text that already reaches the approval card); posting to the Ward Room (it couples the builder to an author identity); retracting the standing-order lines (it undoes the crew side).
- *G2 (safety).* The assignment precedes the rejected-review branch, so a malformed `issues` cannot skip it; the helper never raises; the soft gate is unchanged (a rejected review still commits). A review skipped after a model error is carried as the one suggestion its producer writes and is counted like any other.
- *G3 (readings).* The Builder's report reaches the Captain as `llm_output` on the generated-code event, shown in the approval card before approval; the Transporter path replaces it with a placeholder, and the build result never carried it. Recorded, not changed.
- *Residual.* L1 to L8 of the contract (S2). *Reversal.* Revert the slice 2 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

**S1.** The Size findings paragraph (`orchestrator.agent.md:48`: not one byte; the new paragraph is a separate paragraph after it), the round-three brake paragraph and every `PROCEDURE` needle (the SEARCH of P2-1 is a prefix of the brake's line and the REPLACE keeps it), the Convergence and A-round paragraphs; the constitution (`.github/copilot-instructions.md`: no byte; its 18,000-byte cap test is untouched); both Diff Reviewer profiles; the Claude Builder, Claude Architect and `CLAUDE.md` text; every crew standing order (`config/standing_orders/`), so the AD-1152 golden and the AD-1200 request fingerprints are untouched; `tests/test_ad1359_agent_size_rules.py`; the 18 existing cases of the layout file.

**S2.** `code_reviewer.py` (`ReviewResult`, `_parse_review`, the instructions and the error path are read, not edited); the soft gate (a rejected review still commits and still sets `review_issues`); the Builder's prompt and block format, `_parse_file_blocks`, the Transporter and the harness paths; BUILD_GENERATED and its `llm_output`; BUILD_FAILURE's message and category rules, `resolution_options`, the resolve route and the failure cache; the build queue, the dispatcher and the queue payloads (`/api/build/queue`, `BUILD_QUEUE_UPDATE`); `events.py` (`BuildSuccessEvent` stays a skeleton) and `event_persistence.py`; `ui/` (the HXI reads `message` only; no interface, no card, no test); every config model and key.

**All.** `config/system.yaml` and every generated reference; the commercial overlay (OSS only; no dependency; no schema change); every tracker but `PROGRESS.md`, `DECISIONS.md` and the AD ledger pair; the roadmap Bug Tracker table; every file the two earlier batches edit (this batch edits none of them except the four tracker and ledger files).

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

**Not run by the Architect** (a read-only consult cannot run pytest). **Every Line below occurs exactly once in the patched file: the Architect checked it by applying the blocks in memory to the LF blobs of `0ef819ca` and counting** (section 11); the oracle repeats the count on the real patched tree. The oracle's campaign: each row's line replaced whole in the built file (S1: the fragment replaced inside the paragraph's single line), the slice's test file run, the file restored and its blob checked. **This table is the campaign of record only for a tree whose files equal the blobs the blocks give on `0ef819ca`** (sha256 of each edited file to be recorded by the oracle); a Builder whose files match does not repeat it; if a file differs, the rows naming it are rerun. The Killed-by cells are the cases I expect to fail; the oracle reports supersets and corrects them. Case labels are section 6's. The paragraph of the orchestrator profile is one line of the file, so each S1 row names a fragment of it that occurs once in the file.

**S1** (files: `P` = `.github/agents/orchestrator.agent.md`, `C` = `.github/copilot-instructions.md`, `D1` = `.github/agents/diff-reviewer.agent.md`, `D2` = `.claude/agents/claude-diff-reviewer.md`).

| # | File | Line or fragment (occurs once in the file) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | P | `, unless the extra code breaks something` | the fragment deleted | E[carve-out] |
| 2 | P | `When a deletion is the round's only repair and removes only imports` | `When a deletion removes only imports` | E[only-repair], X1 |
| 3 | P | `removes only imports, or bindings whose value makes no call,` | `removes only imports, calls, or bindings whose value makes no call,` | E[exempt-set], X1 |
| 4 | P | `or bindings whose value makes no call,` | `or bindings,` | E[exempt-set], X1 |
| 5 | P | `that this change added and nothing references` | `and nothing references` | E[added-by-this-change], X1 |
| 6 | P | `and nothing references (every deleted line` | `(every deleted line` | E[unreferenced], X1 |
| 7 | P | `every deleted line is a `+` line of the candidate's diff, and a repo-wide` | `a repo-wide` | E[plus-lines], X1 |
| 8 | P | `, and a repo-wide `git grep` for each deleted name, config, docs and tests included, finds no other use` | the fragment deleted | E[git-grep], X1 |
| 9 | P | `run the focused tests and start no further review round` | `start no further review round` | E[focused-tests], X1 |
| 10 | P | `decorator or call, an import marked` | `decorator, an import marked` | E[delta-review] |
| 11 | P | `an import marked `noqa` or inside a `try`,` | `an import marked `noqa`,` | E[delta-review] |
| 12 | P | `The exemption covers review-round repairs only: a repair after a failed gate or CI follows the brake below. ` | the sentence and its following space deleted | E[review-rounds-only], X1 |
| 13 | P | `The round-three brake below is unchanged.` | `The round-three brake below is unchanged. A deleted helper with one caller needs no review round either.` | X1 (a sentence added: 8, not 7) |
| 14 | C | `a size repair that only deletes unreferenced imports or call-free bindings the change added` | `a size repair that only deletes unreferenced code the change added` | C1 |
| 15 | C | `One review-round repair needs no re-review:` | the whole sentence (to its closing `).`) deleted | C1 |
| 16 | D1 | `Tag each size finding **size**, so the orchestrator can apply its Size findings rule.` | the line deleted | R[diff-reviewer.agent.md] |
| 17 | D2 | `Tag each size finding **size**, so the orchestrator can apply its Size findings rule.` | the line deleted | R[claude-diff-reviewer.md] |
| 18 | P (M2) | `the findings tagged **size** under the rule above (`0` too: silence is not a count), and names each` | `the findings tagged **size** under the rule above, and names each` | K1 |
| 19 | P (M2) | `**Size findings count (AD-1359, #1769).** The review summary of each item or slice` | `**Size count (AD-1359, #1769).** The review summary of each item or slice` | K1 |
| 20 | P (M2) | the blank line after `The round-three brake below is unchanged.` (join the count paragraph into the pinned one) | the blank line replaced by one space | K1 (the template is inside the pinned paragraph), X1 (9 sentences, not 7) |

**S2** (files: `B` = `src/probos/cognitive/builder.py`, `R` = `src/probos/routers/build.py`).

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | B | `result.review_suggestions = _review_suggestions(review.suggestions)` | the line deleted | T1, T2[list], T3 |
| 2 | B | `items = [raw] if isinstance(raw, str) else raw` | `items = raw` | T9[bare-string] |
| 3 | B | `if not isinstance(items, (list, tuple)):` | `if False:` | T9[null], T9[mapping], T9[number], T2[null] |
| 4 | B | `return [text for text in (str(item).strip() for item in items if item is not None) if text]` | the same without `if item is not None` | T9[mixed-items] |
| 5 | B | the line of row 4 | the same without the trailing ` if text` | T9[mixed-items] |
| 6 | B | `review_suggestions: list[str] = field(default_factory=list)  # AD-1359 follow-up (#1769): the review's suggestions, approved or not` | the line deleted | T4, T6 (and the success cases of `tests/test_builder_api.py`) |
| 7 | B | `review_suggestions: list[str] = field(default_factory=list)  # AD-1359 follow-up (#1769): copied from the build result` | the line deleted | T3, T7, T8 (and every `classify_build_failure` case of `tests/test_builder_agent.py`) |
| 8 | B | `review_suggestions=list(result.review_suggestions),` | `review_suggestions=[],` | T7, T3 |
| 9 | B | `"review_suggestions": self.review_suggestions,` | the line deleted | T8, T3 |
| 10 | B | the line of row 1 | moved under `if not review.approved:` after `result.review_issues = review.issues` | T1, T3 (T2 still sets it: its review is rejected) |
| 11 | R | `"review_suggestions": result.review_suggestions,  # AD-1359 follow-up (#1769)` | the line deleted | T1, T5 |
| 12 | R | `+ (f", Review suggestions: {len(result.review_suggestions)}" if result.review_suggestions else "")` | `+ ""` | T1, T5 |
| 13 | R | the line of row 12 | `... if True else "")` (the count shown with none) | T4 |

## 10. Recorded limits

**S1.**
- **L1.** The Size findings paragraph's other sentences (the leftovers rule and the round-1 rule) are not pinned; a reword of them passes. Only the carve-out, the three sentences about the exemption and the paragraph's sentence count are.
- **L2.** The other dev-side size rules (the Claude Builder profile's line, the Diff Reviewer **Size** and **Assumptions** items, the Claude Architect profile's item) stay unpinned; only the reviewers' output tag is pinned, because the count and the exemption apply to findings a reviewer tags **size**. A profile that stops tagging would still make the count read zero for the wrong reason if its tag line were reworded rather than deleted: the pin is the exact line.
- **L3.** The count is only as true as the orchestrator's following of the sentence; no test can read a pull request body. The review point (decision D2) first checks that the line is present in every pull request, then reads the counts.
- **L4.** The unit is "findings tagged **size** under the rule above": a finding one reviewer tags size and another leaves ordinary follows ordinary reach and is not counted (the Size findings paragraph's own definition); one finding two reviewers both tag counts once.
- **L5.** The pins read the working copy as LF text (`_text`); a profile whose line endings are mixed is read as LF.

**S2.**
- **L1.** The HXI shows the count only. The text rides in the event payload, which the HXI does not render (it renders no `review_issues` either); the failure card renders no review field.
- **L2.** BUILD_SUCCESS is grandfathered in `event_persistence.py` (no durable record): the suggestions' text exists in the live event and, for a failure, in the cached report (the failure cache, `api.py:52-61`); nothing records it later.
- **L3.** A review skipped after a model error is carried as the one suggestion its producer writes (`code_reviewer.py:114`) and counted like any other; the count cannot tell it from a real suggestion (the payload text says so).
- **L4.** The Builder's readings: the card shows them collapsed (`IntentSurface.tsx:69`, `:1403`); the Transporter path replaces the prose with a placeholder (`builder.py:2541`: chunked builds have no single report); after approval nothing carries them (`_execute_build` receives file changes only and `BuildResult.llm_output` is set nowhere). Recorded in the comment of "Batching", not changed.
- **L5.** The suggestions are unbounded in number and length, like `review_issues`; the model's output limit bounds both.
- **L6.** The success message shows no count of review issues: a rejected review (the soft gate) still reads "Build complete!" with no hint; the payload carries them as before. An independent item, not filed here.
- **L7.** The TypeScript interface `BuildFailureReport` (`ui/src/store/types.ts:195-216`) does not list the new key (additive on the wire; nothing in the UI reads the review keys).
- **L8.** Two paths run no review or replace it: the dispatcher passes no `llm_client` (`build_dispatcher.py:230-239`), so its results hold no suggestions and its queue payloads never carried review data; and an `escalation_hook` that returns its own result (`builder.py:3779-3784`; no production caller passes one) replaces the original's fields.

## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\next-read` at `0ef819ca`)

**Run by the Architect, read-only (ripgrep through the search tool, git, `gh`, CPython scripts piped on stdin with `-B`; nothing written but these answer files; no pytest, no build):**

```
git -C D:\ProbOS-worktrees\next-read rev-parse HEAD -> 0ef819cad2ba03473bbc9b01f51c52501083104d ("Merge pull request #1788 ... bf928-929-931-voice-call-ui-20261112"); git status --short -> nothing
every SEARCH of section 7 (python on `git show HEAD:<path>`, then applied in memory in document order, S1 then S2): 17 SEARCH/REPLACE pairs: layout test 4, orchestrator profile 1, PROGRESS.md 2, DECISIONS.md 2, builder.py 6, routers/build.py 1, the new test file 1 (against its own M1 text) -> each occurrences=1, line-start=True, ascii=True; "PROBLEMS: 0". CR count 0 in every blob. The new test file: ASCII, 288 lines, parses (ast.parse); the layout test, builder.py and routers/build.py parse after patching. Every REPLACE is ASCII
the part files themselves: written by the create tool with CRLF line endings; the orchestrator normalises them to LF before slicing (a mechanical step; the dry application above stripped the CR first)
the layout test's constants evaluated on the blobs: the Size findings paragraph (1174 chars) has 7 sentences (the file's own _SENTENCE_END); all ten SIZE_EXEMPTION_PARTS and SIZE_EXEMPTION_SENTENCE are substrings of it; CONSTITUTION_SIZE_EXEMPTION is in the constitution; SIZE_TAG occurs once in each reviewer profile; on the base the count marker occurs 0 times (K1 fails at its first assert), on the patched profile once, with the sentence equal, the heading unique and the template outside the pinned paragraph; all 27 PROCEDURE needles are in the patched profile and none in the constitution; the brake paragraph keeps its handoff clause and no "frozen"; the new paragraph adds 293 characters
the helper _review_suggestions, extracted from the patched builder.py by ast and executed alone, gives the seven expectations of T9's cases
blobs (git rev-parse HEAD:<path>): builder.py 16bc1cba..., routers/build.py 6e3daf58..., test_standing_orders_layout.py 20bb35d1..., orchestrator.agent.md 37f2ff7f..., copilot-instructions.md e0abb1bc..., diff-reviewer.agent.md 87d3e6c9..., claude-diff-reviewer.md 3f310a2a..., code_reviewer.py c8e1a42f...; PROGRESS.md f2cb113f..., DECISIONS.md 470dc36f..., open-ads-report.md 6aabf0f7..., ad-ledger-snapshot.json 3b6c6bdf...
tracker anchors: git show HEAD:PROGRESS.md starts "# ProbOS Progress", an empty line, then BF-931's entry (title line occurs once); the DECISIONS heading "### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)": whole-line match count 1, at line 1732; ASCII; no CR in the blob
```

**Facts read (path:line on `0ef819ca`):** `code_reviewer.py:16-22` (`ReviewResult`; `suggestions` `:21`), `:108-116` (the error path, `:114`), `:140-163` (`_parse_review`, `:150`); `builder.py:20` (`dataclass, field` imported), `:128-147` (`BuildResult`; `:140` `llm_output`, `:142-143` the review fields), `:151-180` (`BuildFailureReport`; `:175-176`), `:187-201` (`to_dict`; `:198-199`), `:204-221` (`classify_build_failure`; `:219-220`), `:2470` (the visiting path's `raw_output`), `:2541` (the Transporter placeholder), `:2584` (the harness path), `:2649-2705` (`act`; `:2698`, `:2705`), `:2713` (`_parse_file_blocks`), `:3173-3184` (`sealed_core_enforced`: False for a runtime without the config chain), `:3243` (`BuilderAgent = SoftwareEngineerAgent`), `:3246-3260` (`execute_approved_build`; `llm_client` `:3252`, `escalation_hook` `:3253`), `:3285` (`BuildResult(success=False, spec=spec)`), `:3531-3556` (step 4c: `:3541` the call, `:3546` `review_result`, `:3547` `approved`, `:3550` and `:3554` `issues`, `:3556` the warning), `:3779-3784` (the hook); `routers/build.py:25` (the import of `_pending_failures` from `probos.api`), `:61-62`, `:317`, `:344` (readers of `branch_name` and `commit_hash`), `:143-170` (the resolve route reads `report.cleanup_errors`), `:429-453` (BUILD_GENERATED with `llm_output`), `:465-499` (`_execute_build`; the executor call with `llm_client=getattr(rt, "llm_client", None)`), `:500-515` (BUILD_SUCCESS), `:518-536` (the failure path: `classify_build_failure`, `_pending_failures[...]`, `report.to_dict()`); `build_dispatcher.py:230-239` (the executor call with no `llm_client`), `:243-300` (reads `success`, `commit_hash`, `branch_name`, `error`); `build_queue.py:51`; `runtime.py:2219` (`build.result.commit_hash`); `events.py:36-37`, `:609-617` (`BuildSuccessEvent`: 5 fields); `event_persistence.py:112` (`GRANDFATHERED`), `:176` (`"BUILD_SUCCESS"` among them); `watch_rotation.py:243` (`not_executed` of a `build_failure`); `ui/src/store/useStore.ts:3780-3797` (`build_generated`), `:3799-3806` (`build_success`: reads `data.message` only), `:3809-3820` (`build_failure`); `ui/src/store/types.ts:195-216` (`BuildFailureReport`); `ui/src/components/IntentSurface.tsx:69` (`buildCodeExpanded` starts `{}`), `:1391-1413` (the toggle and `llm_output`), `:1480-1590` (the failure card: no review field); `config/standing_orders/engineering.md:90` and `builder.md:15`; `.github/agents/orchestrator.agent.md:42-52` (`:42` the heading, `:44` Convergence, `:46` A round, `:48` Size findings, `:50` the brake), `.github/copilot-instructions.md:54` and `:56`, `.github/agents/diff-reviewer.agent.md:81-91` and `:102`, `.claude/agents/claude-diff-reviewer.md:88-98` and `:109`; `tests/test_standing_orders_layout.py:24-49` (imports and paths), `:87` (`_MIN_SENTENCE_CHARS`), `:100-146` (`PROCEDURE`, `SHARED_RULES`, the brake constants), `:158-243` (`_FRONT_MATTER`, `_SENTENCE_END`, `_text`, `_rel`, the sentence units), `:379-392` (the duplicate-sentence test), `:488-496` (the idiom: `test_brake_handoff_does_not_redefine_frozen`), 18 test functions in all; `tests/test_ad1359_agent_size_rules.py` (one function, three cases); `tests/test_code_reviewer.py:70-82`; `tests/test_builder_agent.py:2790-2833` (a review through the executor with a rejected review), `:2843-2866` (`to_dict` named keys), `:2956-2970` (`classify_build_failure` copies `review_result` and `review_issues`); `tests/test_builder_api.py:319-360` and `:362-410` (`_execute_build` events with a patched executor); `tests/test_bf904a_failed_build_restore.py:96-130, :237-245, :265-270` (the git helpers, `_FakeModel`, `_route_modules`), `:512-566` (event types of a re-run), `:1456-1503` (a failing build through `_execute_build` with a runtime double); `tests/test_bf904b_sealed_core_observation.py:44-134` (the same helpers, `_Runtime`) and `:258-285` (a build through `_execute_build` that reaches BUILD_SUCCESS); `tests/test_ad1346_admission_build_test_sink.py:64-71` (`_EXECUTOR_CALLS` by AST over `_execute_build`); `tests/test_events.py:146-154` (`BuildSuccessEvent` with five fields); `scripts/gen_ad_ledger.py:113` (`_TOKEN_RE`), `:139` (`_HEAD_WINDOW`), `:153-174`, `:187-231` (entry parsing), `:281-343` (the git layer), `:437-495` (`classify`); `docs/development/open-ads-report.md:25-32` (ceilings), `:38` (the git-log row), `:304-318` (the unparseable lines); `pyproject.toml:180-196` (`asyncio_mode = "auto"`, `timeout = 180`, `-n 16`).

**Consumers of what this batch changes, by what each reads** (path:line on `0ef819ca`; the enumerations of the Absence Verified block below produced it):

| Consumer | Reads | Effect of the change |
|---|---|---|
| `routers/build.py:500-515` (the success event) | `success`, `branch_name`, `commit_hash`, `files_written`, `files_modified`, `tests_passed`, `test_result`, `review_result`, `review_issues` | edited by S2 (P2-7): one key and one message tail |
| `routers/build.py:518-536` (the failure path) | `classify_build_failure(result, spec)`, `report.to_dict()`, `report.failure_summary`, the cache entry | `to_dict` gains a key; nothing here reads it |
| `routers/build.py:143-170` (the resolve route) | `cached["report"].cleanup_errors` | none |
| `routers/build.py:61-62`, `:317`, `:344`; `runtime.py:2219`; `build_dispatcher.py:243-300`; `build_queue.py:51` | `branch_name`, `commit_hash`, `success`, `error`; the type only | none (no review field) |
| HXI `useStore.ts:3799-3806` (`build_success`) | `data.message` | shows the count; no other key is read |
| HXI `useStore.ts:3809-3820`, `IntentSurface.tsx:1480-1590` (the failure card), `types.ts:195-216` | `failure_summary`, `failure_category`, `ad_number`, `title`, `files_written`, `files_modified`, `branch_name`, `fix_attempts`, `failed_tests`, `raw_error`, `resolution_options`, `build_id` (the interface also lists `review_result` and `review_issues`, which no component reads) | an extra key is ignored |
| `events.py:609-617` (`BuildSuccessEvent`), `tests/test_events.py:146-154` | five fields of a typed skeleton constructed nowhere in `src` | none |
| `event_persistence.py:176`, `watch_rotation.py:243`, `conn.py:55` | the member name; `not_executed` of a `build_failure`; a trigger name | none |
| `tests/test_builder_agent.py:2790-2833`, `:2843-2866`, `:2956-2970` | `review_issues`, `review_result`, named keys of `to_dict()` | none (no whole dump) |
| `tests/test_builder_api.py:319-410`, `tests/test_bf904a_failed_build_restore.py:546-566`, `tests/test_bf904b_sealed_core_observation.py:284`, `:406`, `tests/test_ad1346_admission_build_test_sink.py:312` | event types; `"report" in failure`; one `branch` | none |
| `tests/test_ad1346_admission_build_test_sink.py:64-71` and the censuses (`tests/fixtures/ad1346_effect_census.py:124-131`, `tests/fixtures/ad1346_file_write_census.py:185`, `tests/test_ad1344_constitution_write_refusal.py:745-767`) | calls, imports, writes and subprocesses by file and scope | none: the batch adds none |
| `?raw` source readers | UI sources only (`ui/src/**/__tests__` import `.tsx` and `.ts` files of `ui/`); no `?raw` import reads `builder.py` or `build.py` | none (no `ui/` file is edited) |
| docs, scripts, API listings | no file lists the payload keys or the message | none |
| `tests/test_code_reviewer.py:82` | `result.suggestions` of the producer | none (the producer is not edited) |

**Absence Verified (2026-11-13)**

```
CLAIM: nothing in src or tests reads ReviewResult.suggestions except tests/test_code_reviewer.py:82
RUN:   rg -n "\.suggestions\b|suggestions=|\[.suggestions.\]|get\(.suggestions." src --glob '*.py'; rg -n "\.suggestions\b|ReviewResult\b" tests --glob '*.py'
FOUND: src: cognitive/code_reviewer.py:114 (the kwarg of the error path), :150 (the write), routers/agents.py:1624 (an unrelated key: base["suggestions"] = [s.to_public() ...]); tests: test_code_reviewer.py:9 (the import), :82 (the one read), test_agent_evals.py:136 (a comment)
HOLDS: yes. Positive control: the first pattern finds both writers

CLAIM: nothing reads BuildResult.llm_output, and nothing sets it
RUN:   rg -n "\.llm_output\b" src; rg -n "BuildResult\(" src
FOUND: no attribute access; one construction (builder.py:3285, keywords success and spec only)
HOLDS: yes. Positive control: rg -n "\.review_result\b" src finds builder.py:219, :3546 and routers/build.py:508

CLAIM: no test, script, doc or golden compares a whole dump of BuildResult, BuildFailureReport or the BUILD_SUCCESS payload, and no construction passes BuildResult positionally
RUN:   rg -n "review_issues" over the repository (excluding node_modules, site, .git); rg -n "fields\(BuildResult|fields\(BuildFailureReport|__dataclass_fields__" tests --glob '*.py'; rg -n "BuildResult\(" tests --glob '*.py'; rg -n "asdict\(" tests --glob '*.py' (read against the list of files that name BuildResult)
FOUND: review_issues only in cognitive/builder.py, routers/build.py, ui/src/store/types.ts, tests/test_builder_agent.py and history (decisions-era-4-evolution.md, progress-era-4-evolution.md, archived prompts); __dataclass_fields__ of other classes only; 16 constructions in tests, all keyword arguments; the asdict hits are in test_ad1152_agentic_correlation.py, test_ad1152_crew_token_usage.py, test_ad1205_fault_paths.py, test_ad1240_tool_result_delivery.py, test_ad1325_boundaries.py, test_bf920_cross_agent_verification.py, test_social_verification.py, none of which names BuildResult
HOLDS: yes

CLAIM: no test, doc, script or UI file pins the success message or lists the payload's keys
RUN:   rg -n "Build complete|build_success|BUILD_SUCCESS|review_issues|review_suggestions" ui (excluding node_modules), docs, scripts, tests --glob '*.py'
FOUND: ui: useStore.ts:3799 only (reads data.message); docs and scripts: none; tests: event types only (test_builder_api.py:359, test_bf904a_failed_build_restore.py:548, test_bf904b_sealed_core_observation.py:284 and :406, test_ad1346_admission_build_test_sink.py:312) and test_events.py:146-154 (the typed skeleton); test_notifications.py's "Build complete" is a notification title
HOLDS: yes

CLAIM: BUILD_SUCCESS has one emitter and no payload reader but the HXI
RUN:   rg -n "BUILD_SUCCESS|build_success|BuildSuccessEvent" src --glob '*.py'
FOUND: events.py:36 (the member), :611 (the typed skeleton, constructed nowhere in src), event_persistence.py:176 (a name in GRANDFATHERED), routers/build.py:186 (a comment) and :501 (the one emission)
HOLDS: yes (watch_rotation.py:243 and conn.py:55 read build_failure, not build_success)

CLAIM: no test or fixture embeds the orchestrator profile, the Size findings paragraph or the reviewers' tag, and nothing in src or scripts reads the profile
RUN:   rg -n "orchestrator\.agent|agents/orchestrator" tests, src, scripts; rg -l "Round-three brake|Review Rounds and Progress|Convergence \(codified" tests; rg -n -i "Size findings|no further review round|call-free bindings|AD-1359, #1765|Tag each size" tests; rg -n "Size findings" .github
FOUND: tests/test_standing_orders_layout.py only (plus unrelated "orchestrator" keys in test_measure_agent_token_usage.py and test_ad1192_owned_steps_finalization.py); the size-rule text only in .github (copilot-instructions.md:54, diff-reviewer.agent.md:102, orchestrator.agent.md:48) and in the shipped AD-1359 contract
HOLDS: yes. Positive control: the layout test is found by the first pattern. The repository-instruction discovery reads AGENTS.md, AGENTS.override.md and .github/copilot-instructions.md (repository_instructions.py:249-251), never .github/agents/

CLAIM: the sentence "Size findings: " is not in any profile yet, and .github holds no pull request template
RUN:   rg -n "Size findings: " .github CLAUDE.md; Get-ChildItem -Force -Recurse -File .github (excluding workflows)
FOUND: no match; three files: copilot-instructions.md, agents/diff-reviewer.agent.md, agents/orchestrator.agent.md
HOLDS: yes. Positive control: rg -n "Size findings" .github finds the three lines above

CLAIM: nothing else claims AD-1359, AD-1360 or BF-962, and no file or branch of this work exists
RUN:   git log --all --format='%s' | rg "AD-1359" ; the same for "AD-1360|BF-962"; Get-ChildItem prompts -Filter '*1359*' and '*1769*' and '*followup*'; gh issue list --state all --search "AD-1359 in:title"; gh pr list --state all --search "AD-1359 in:title"; git branch -a --list '*1769*'; Select-String '^\| (AD|BF) \| \*\*' docs/development/open-ads-report.md
FOUND: five subjects name AD-1359 (the shipped work and its merge); none names AD-1360 or BF-962; prompts/ad-1359-leftovers-readings-size.md only; issue #1769 (open) is the only issue whose title carries AD-1359, and pull request #1771 (merged) the only pull request; no branch; the Ceilings table reads AD-1359 / AD-1360 and BF-961 / BF-962; the snapshot holds "AD-1359": ["git AD-1359"]
HOLDS: yes (nothing is allocated; the only number used is the parent's, as a plain token)

CLAIM: nothing outside tests/test_standing_orders_layout.py reads the files this batch edits by line number
RUN:   rg -n "builder\.py:[0-9]+|routers/build\.py:[0-9]+" tests --glob '*.py'; rg -n "cognitive/builder\.py|routers/build\.py" tests --glob '*.py'
FOUND: by file and scope: tests/fixtures/ad1346_effect_census.py:124-131, tests/fixtures/ad1346_file_write_census.py:185, test_ad1344_constitution_write_refusal.py:745-767, test_ad1346_admission_build_test_sink.py:66-67, test_ad1346_admission_effect_census.py:260-272, test_ad1346_admission_service.py:591-682 (import lists); by line, in a docstring or comment only: test_ad521_swe_pipeline_separation.py:125, test_bf908_floor_and_children.py:941
HOLDS: yes (no enumerated test counts a call, an import, a write or a subprocess this batch adds: it adds none)
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** AD-341's soft gate and the review's fields (`review_result`, `review_issues`: the shape this batch extends); AD-343's failure report and its dict; the BF-904a and BF-904b real-git harnesses, `_FakeModel` and `_Runtime` (the seam tests); the AD-1359 contract and its amendments (the Size findings paragraph, the layout idiom at `test_brake_handoff_does_not_redefine_frozen`); the BF-930/932 contract's conventions (slices, SEARCH rules, tracker anchors, the ledger gate, mutation rows, the marker removed at M2). **Rejected:** section 3. **External:** none consulted.
- **Blind spots handled.** (1) The model's JSON is copied as given, so `suggestions` can be null, a string or a list of anything: the helper coerces and never raises (T9). (2) A non-string issue makes `"; ".join(review.issues)` raise before `review_issues` is set: the new assignment sits above that line (T2[null]). (3) A skipped review arrives as a suggestion: counted, limit L3. (4) The success message is byte-identical when there is nothing to show (T4). (5) The shared failure cache: each failure case replaces it with its own dict. (6) `probos.api` must load before `probos.routers.build`: `_route_modules` does it. (7) Working copies are CRLF: the pins read LF text through `_text`. (8) The new paragraph against the duplicate-sentence detector, the 27 `PROCEDURE` needles and the brake test: evaluated (section 11). (9) The ledger: a plain `AD-1359` token only; no suffix, no other number. (10) A sentence added to the Size findings paragraph can widen the exemption without touching any pinned text: the sentence count guards it (X1), and the residual (an in-place reword of an unpinned sentence) is L1. (11) A reviewer profile that stops tagging makes the count read zero for the wrong reason: pinned (R). (12) A measurement that no test can observe: the sentence is pinned so it cannot vanish silently (K1), and the review point checks presence before it reads counts.
- **What discards a correct result.** Blank and None suggestions (dropped on purpose); a rejected review whose `issues` raise (ordering, T2); a report that does not copy the list (T7); a payload that lacks the key (T1, T5); a HXI that reads `message` only and a BUILD_SUCCESS that is not persisted (limits L1, L2); a pull request that states nothing for zero findings (part 3's sentence: "`0` too"); a finding tagged size by one reviewer only (L4 of S1). **Recorded:** S1 L1 to L5, S2 L1 to L8.

## Batching

**One pull request and one broad gate for S1 and S2; S1 first, then S2; the two earlier batches merge before it is built.**

| Point | Judgement |
|---|---|
| Files | Disjoint between the slices; the tracker pair and the ledger pair collide with the earlier batches: re-anchor, as the header says |
| Why together | The three parts are one issue, found in one review of one AD; parts 2 and 3 share a test file and a boundary; part 1 has no file in common with them |
| Order | S1, S2. Neither imports the other. S1 first so that the zero-risk slice can ship alone and the count's clock starts at the merge |
| Revert | Separate commits per milestone and per slice; either slice reverts alone |
| Cost: Python | S2 only: the G1 and G2 files of section 4 at `-n 0`; once per batch, mine: the mutation rows and `PY scripts/run_test_gate.py --label ad1359-followup --receipt logs/gates/ad1359-followup.receipt.json` |
| Cost: config, UI | None: no key, no model, no yaml, no `ui/` file; the AD ledger pair is the only generated artifact |

**The pull request body** says: `Refs #1769` (the issue stays open, decision D2); lists what ships by slice; and states, in the form S1 adds, `Size findings: <n>` for S1 and for S2 with one word per finding (the batch is the first user of its own sentence).

**The comment to post on #1769 when the pull request merges (the orchestrator; public text, no crew name or live figure).**

> Shipped in the pull request: (1) part 1: the code review's suggestions are carried on the build result and on the failure report (`review_suggestions`), in the failure report's dict and in the success event, and the success message ends `, Review suggestions: <n>` when there are any; they are set whether or not the review approved. (2) part 2: the orchestrator's Size findings exemption (each condition, its exclusion clause, the review-round-only sentence, the paragraph's sentence count), the constitution's sentence about it and the reviewers' size tag are pinned by cases in `tests/test_standing_orders_layout.py`. (3) part 3: the orchestrator profile now says each item's review summary states `Size findings: <n>` (0 too) and names each finding. **Readings (no code).** The crew Builder's report is its model output. It reaches the Captain on the generated-code event (`llm_output`, `routers/build.py:441-451`) and the approval card shows it under "View Code" (`IntentSurface.tsx:1391-1413`), before approval. Limits: it is collapsed by default; the Transporter path writes a placeholder instead (`builder.py:2541`: chunked builds have no single report); after approval nothing carries it (`BuildResult.llm_output` is set nowhere). **This issue stays open for its review point:** after ten pull requests merged after this one, check that each states the line; then read the counts and decide whether the Size checklist item stays. The decision and the closure go in the closing comment.

**The review point (the orchestrator at each wave report; the Architect decides; no Captain).** Read: `gh pr list --repo seangalliher/ProbOS --state merged --search "merged:>=<the merge date>" --json number,mergedAt,body --limit 100`, take the first ten merged after this batch's merge commit, and count in each body the `Size findings: <n>` lines (one per item or slice). Present: every one of the ten states the line for every item. If any does not, the finding is that the sentence is not followed: repair the process and restart the count. Then: all counts zero means the Size checklist item costs a line per review for no finding (the Architect decides whether it stays); any non-zero count keeps the item and audits the first "deleted without re-review" against the exemption's conditions. Record the decision on #1769 and close it with it.

## Not in this issue: for the Captain

**None.** Every claim of this batch is checked by tests and by the dry applications of section 11; nothing needs the vessel, a credential or a Captain's decision (no option of D1, D2 or D6 meets a "Still requires the Captain" condition). The review point is the Architect's (the issue says so). **Optional, no decision:** after the merge, approve one real build whose review returns a suggestion and read the chat line, which should end `, Review suggestions: <n>`; a build whose review returns none reads exactly as before.

## 13. Diff Reviewer: properties to verify

**S1.**
1. `git diff --stat` for S1 M2 shows two paths: the profile and the layout test; the profile diff is added lines only, one paragraph of about 290 characters; the Size findings paragraph, the brake paragraph and the `PROCEDURE` needles are unchanged (`git diff` shows no removed line in the profile).
2. The count paragraph is separated from the pinned paragraph by a blank line, lies between the heading of Review Rounds and Progress and the next `## ` heading, is ASCII, and its sentence is in no other governed file (the duplicate-sentence test passes; `git grep -F "silence is not a count"` finds one file).
3. Every text in `SIZE_EXEMPTION_PARTS`, `SIZE_EXEMPTION_SENTENCE`, `CONSTITUTION_SIZE_EXEMPTION` and `SIZE_TAG` is a verbatim substring of the live file it pins and occurs once there; no pin is weaker than its row of section 9 needs.
4. No byte of the constitution changed; the file keeps its 18,000-byte cap test; no `xfail` or `@built` remains in the layout file after M2.
5. The cases restore nothing because they patch nothing; each reads working copies through `_text`.

**S2.**
1. `result.review_suggestions = _review_suggestions(review.suggestions)` sits directly under `result.review_result = review.summary` and above `if not review.approved:`; the other lines of the block, the `except` arm and the soft gate are byte-identical.
2. `_review_suggestions` is module-level, next to its only caller, takes `object`, returns `list[str]`, adds no import, does no I/O and cannot raise on what `json` decodes; `BuildResult` and `BuildFailureReport` gain one defaulted field each (`field(default_factory=list)`, no shared list); `to_dict` lists the key; `classify_build_failure` copies.
3. The success message is byte-identical when `review_suggestions` is empty (T4); the payload keeps every old key; the failure message and category logic are untouched.
4. No `ui/` file, no config, no event type, no `events.py` change; `git diff --stat` for S2 M2 shows three paths (`builder.py`, `routers/build.py`, the test file).
5. Every `built` case fails at an `assert` on the base (`--runxfail`); T4 passes on the base; the failure cases replace the cache with their own dict; no case names a crew member, a thread or a live figure.
6. Consumers: nothing reads the changed files by line (section 11); no census counts a call, an import, a write or a subprocess this batch adds.

**Both.** Public text: no crew name, thread id, timestamp or live figure in any test, comment, tracker line or commit message; the only AD or BF token at the head of a tracker entry or a commit subject is `AD-1359`; M3's `Refs`, never `Closes`; the pull request body states `Size findings: <n>` for each slice.

## 14. Acceptance criteria

1. G1, G2 and G3 of each slice pass as stated in section 4; the oracle's mutation rows and the broad gate (`--label ad1359-followup`) pass; the three config checks are unchanged.
2. Removing or loosening any condition of the no-review exemption, the constitution's sentence about it or a reviewer profile's size tag fails a named case (S1 E, X1, C1, R); the count sentence is present, outside the pinned paragraph and inside its section (K1).
3. A review's suggestions reach the build result, the failure report's dict and the success payload, and the success message counts them only when there are any (T1 to T3, T5 to T8); malformed model output is coerced and never raises (T9); the soft gate and `review_issues` are unchanged (T2).
4. Nothing else changes: the success message without suggestions, the existing payload keys, the failure categories, the queue payloads and the dispatcher path (T4 and the existing suites of G2).
5. #1769 stays open; every M3 says `Refs`; the comment of "Batching" is posted at merge; the review point is run by the orchestrator and decided by the Architect.
6. No config key is added; the AD ledger pair is the only generated artifact and moves no number (G3); no `?raw` or source-scan test reads an edited file for a line this batch changes (section 11).
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
