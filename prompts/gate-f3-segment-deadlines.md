# Promoted-turn resume cases give each segment the deadline its role needs: GATE-F3 of #1754 (a test-only slice; the parent stays open)

**Drafted by:** the Copilot Architect (fallback; the Claude Code bridge was logged out), 2026-11-13
**Revised by:** amendment A1 (section 15: the oracle's measurements; the cells of rows 3 and 6 and of C1 and C2, section 9's closing sentence, L3 and L5 corrected; Appendix P's P3 check), measured and applied by the orchestrator, 2026-11-13
**Revised again by:** amendment A2 (section 16: the slice goes into item B's pull request and broad gate with a bounded hold; the Status and Batching lines say so; the seven SEARCHes and the two tracker anchors re-measured on item B's head; Appendix P's validator corrected after round 1 of this slice's own review), applied by the orchestrator under the Architect's order of work for round 1 of item B's review (section 16.9 of item B's contract), 2026-11-13; amendment A3 (section 16: the two statements of the PROGRESS entry of P3-1 that round 3 of this slice's own review found unsupported, corrected), applied by the orchestrator, 2026-11-13
**File in the repository:** `prompts/gate-f3-segment-deadlines.md` (the orchestrator may rename it; no AD or BF number is allocated, section "Numbers"). **Answer files:** in three parts: `answer-gf3-contract.part1.md` (this header, sections 1 to 6), `answer-gf3-contract.part2.md` (section 7: the blocks; then Appendix P, the injection probe, for the orchestrator and not for the Builder), `answer-gf3-contract.part3.md` (sections 8 to 14, "Batching", "Not in this issue: for the Captain"). Read them in that order; the labels of section 7 restart in the slice. The `create` tool writes CRLF; the apply tool reads the orchestrator's LF copy (every check in section 11 was run on text with CRLF removed).
**Status:** ready to build in item B's pull request and broad gate (amendment A2, section 16), on item B's head, after BF-930/932 and #1769 have merged. It goes ahead of item B, in its own pull request from `origin/main`, if it has no clean review two hours after item B's delta re-review came back clean, or if a later full gate or CI is red on this family. At this consult `origin/main` is `4d8c51e4035d71660f0432b17083168050a1304e` (BF-933's merge). **Reading tree:** `D:\ProbOS-worktrees\bf930-932-build` at `b83ed1e347e1f5303b71cd21f4920a63065d59c0` (BF-930/932's batch; clean: `git status --short` printed nothing; read only). The file this slice edits has the same blob on both refs, so every SEARCH of section 7 holds on both. **Oracle:** the Architect ran no pytest, no vitest, no build and no script that writes (a read-only consult on a host under a broad gate). **What I ran instead** (section 11): the seven SEARCHes of the test file and the two tracker anchors on the LF blobs of both refs (9 anchors, 0 problems); an in-memory apply of the seven blocks (the patched file read through, not executed); enumerations of every test that arms a real BF-733 watchdog or sets a deadline, of every constant and helper the slice names, of the log lines the cases read; and the JUnit times of the gate that failed (read, not rerun). **What that leaves unchecked (all "expected" below):** every pytest result, the injection probe (Appendix P: not run, not compiled), the mutation rows, the AD ledger regeneration, and the broad gate.
**Base blobs.** *Edited:* `tests/test_bf887_continue_resumes_the_promoted_turn.py` `5cd050f049f65fb09c7caeba551f73a0dd8b0aa3` (equal on both refs; 1,818 lines; 0 non-ASCII lines). *Read, not edited (equal on both refs):* `tests/test_ad1246_long_run_promotion.py` `23af56cfec746d4c42409a8ae6af367402df4ab0`, `tests/test_bf733_promoted_run_deadline.py` `71c9263183351c0ff8d084cec60a3ecb5c892a1d`, `tests/test_issue1417_run_python_child_ownership.py` `4c7bf2ef7d9b633519fed1f30410e7bb6a983f8b`, `tests/test_bf825_a_run_someone_is_waiting_on.py` `b3e3f5036b7c2bcc1e900b6df21cbf1cb5bf5b28`, `tests/test_ad1165_turn_promotion.py` `a43e755b90b9a6341c9015f2805fd568a815a480`, `tests/test_ad1274_report_off_loop.py` `e901d974a039e6e5f41a8656421e4a1b21ae9a59`, `src/probos/cognitive/turn_promotion.py` `25a2e438714ca16ad4e3731b53725331d44b2f95`, `src/probos/config_models/agentic.py` `9bd9c4a8414cb5ba16ab57006d706836bf859917`; `src/probos/cognitive/cognitive_agent.py` `62c0f816bd5f1ce766a541abbfc0ccba6b743ae4` on `origin/main` and `2c2f3ee2b8dc51c972b5b280e955aaa70443c58f` on the reading tree (BF-930/932's lines, after the lines this slice cites). *Trackers and the generated pair (they differ between the refs and move with the merges):* reading tree `PROGRESS.md` `bd1731caa443d0a81c1158377de58e92ad92f8ae`, `DECISIONS.md` `287e9da85cf7651c8183df832d1ea0da80a5adc2`, `docs/development/open-ads-report.md` `ca7c9ad63d19cdb2e68621bb4e31e14dc7331bd3`, `docs/development/ad-ledger-snapshot.json` `7ab3d8c84167afc2a62b3b2af3e7817c1998a8da`; `origin/main` `6977982df64e88416691c0f593f99eb1430a73b5`, `54d518a6fc38a2cd1d603fe1c85819c4d8f0458b`, `99a1a604a8197b5964ce0bda13015ec354e8a298`, `33363eb2bf06e1f45c8b4a278b83299920dd8b06`. **After the three merges the test file's blob must still be equal (BF-930/932 changes none of it; #1769 and item B change none of it); the orchestrator re-runs the occurrence check of the seven SEARCHes and the two anchors of section 7 (each exactly once, at a line start, ASCII).** *One path does not exist* (`Test-Path` printed `False`; `git cat-file -e` exit 128 on `origin/main`): `prompts/gate-f3-segment-deadlines.md`.
**Dependencies:** none in code. BF-930/932 and #1769 touch no line of the file; item B touches `cognitive_agent.py`, `tests/test_teaching_protocol.py`, the guard-name allow-list and a new test file. The trackers are the only shared files (anchors below). **Tier:** S1 M1 HIGH, S1 M3 STANDARD (D1). **Estimated tests (expected, not measured):** none added, none removed: the file collects 62 cases on the reading tree (the gate that failed ran 62), and still does; five cases (`test_l4_...`, `test_o1_...` x 4) change. No config key, no config model, no generated artifact but the AD ledger pair. **Numbers (hard rule):** **current highest AD: AD-1359** (`d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py`, exit 0: `git log --all` subjects AD-1359, GitHub issue titles in all states AD-1359 over 1,517 issues not truncated, `prompts/ad-*.md` AD-1350; next would be AD-1360); **current highest BF: BF-961** (my own enumeration, because `ad_ceiling.py` does not cover BF: `git log --all --format=%s` subjects 961, GitHub issue titles in all states 961 over 1,517 issues, `prompts/bf-*.md` 941, the roadmap Bug Tracker 927). **Nothing is allocated:** the item is parent-backed (GATE-F3 of #1754), no tracker head and no commit subject of this slice is a number, and no `AD-` or `BF-` token appears in any tracker line or commit message of the slice. Token the ledger would read and we do not want: **BF-954** (#1754's title reserves it for an open umbrella): it appears in no line of this slice.

**Tracker anchors (the orchestrator re-anchors after the merges).** `PROGRESS.md`: the title line `# ProbOS Progress` and the blank line after it (once, at the start of the file, on both refs: checked, count 1, index 0). `DECISIONS.md`: the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)` (once on both refs: line 1748 on `origin/main`, line 1764 on the reading tree; at a line start; ASCII). Every earlier batch's entry inserts before it, **and item B's replacement text ends with this same heading line**, so it still occurs once after B and this slice's entry lands after B's. Any other change to either file between these blobs and the build's base is a hard stop for the Architect. The AD ledger pair is regenerated at M3 by `scripts/gen_ad_ledger.py` (G3) and is not merged by hand.

## 1. Problem

GATE-F3 of #1754 recorded one failure of `test_o1_...[first-finished]` and a cause (the 10 s settle bound) that was wrong; the comment of 2026-11-13 on #1754 corrected it. The mechanism, re-derived here:

| Claim | Re-derived on `b83ed1e3` | Verdict |
|---|---|---|
| The deadline is read when a segment starts | the first run: `cognitive_agent.py:5577-5579` (`deadline_seconds=_coerce_promotion_budget(getattr(cfg, "promoted_run_deadline_seconds", 0.0))`); each resumed pass: `:5476-5478`; `_PromotedRunSupervisor.__init__` stores it (`turn_promotion.py:506`), `arm()` starts the watch task (`:512-516`), `_enforce` waits `asyncio.wait({task}, timeout=deadline)` and warns `BF-733: promoted run for work item %s made no return in %.1fs (deadline %.1fs)` (`:541`, `:546-551`) | holds |
| `cfg` is the rig's own object, read once per turn | `cfg = getattr(getattr(runtime, "config", None), "dm_agentic", None)` (`cognitive_agent.py:4905`); the rig builds `SimpleNamespace(dm_agentic=dm or DmAgenticConfig(...))` (`test:279`), and both resumed segments read the same closure variable | holds |
| `DmAgenticConfig` accepts an assignment between segments | `class DmAgenticConfig(BaseModel)` (`config_models/agentic.py:504`); `rg "validate_assignment\|frozen\|__setattr__\|model_config"` finds two hits, both the word "frozen" in prose (`:632`, `:634`); field `promoted_run_deadline_seconds: float`, `ge=0.0, le=86400.0` (`:597-602`), checked at construction only; the read coerces by exact type (`type(raw) not in (int, float)` is 0.0: `cognitive_agent.py:807`), so the value assigned must be a plain float | holds |
| So a case's deadline also bounds the segment it needs alive | l4: the first segment, arm to park, under 1.0 s; o1: the older segment, arm to its end, under 2.5 s, **and the case itself adds a fixed 1.0 s head start (`:1381`) inside that window** | holds |
| The same signature is in the logs | two CI logs of `test_o1_...[first-finished]` and the gate log of `test_l4_...`: `BF-733: ... made no return in 2.6s (deadline 2.5s)` (and 2.5 s), then `BF-887: a segment ... was stopped by its watchdog after the item moved on`, then `AD-855/BF-887: ... holds no next pass for it` (o1); one `BF-733: ... 1.1s (deadline 1.0s)` line and `assert len(scripted.calls) == 2` got 1 (l4) | holds (the earlier consult's measurement; not redone) |

**The exposure of each case** (idle chain estimated from the failed gate's JUnit times, read from its XML: l3 1.142 s, l4 1.240 s, o1 first-finished 1.198 s, resumed-finished 1.277 s, first-watchdog 2.672 s, resumed-watchdog 2.687 s, o8 2.949 s and 3.090 s; so the chain a case must finish inside the deadline is about 0.2 s, and under load it is longer, so the real budgets are smaller):

| Case | Segment that must not fire | Deadline | Budget before (pause it survives) | After this slice |
|---|---|---|---|---|
| l4 (`:1118`) | the first segment, arm to park | 1.0 s | about 0.9 s | none: 600 s |
| o1 `*-finished` (`:1340`) | the older segment until the hold is released: park, the 1.0 s head start, the approval | 2.5 s | about 1.3 s | none: 600 s |
| o1 `*-watchdog` (E1) | the older segment until the approval has started the newer one | 2.5 s | about 1.3 s | about 5.7 s (6.0 s, no head start) |
| o1 `*-watchdog` (E2) | the newer segment after the older one's stop | 2.5 s | about 1.0 s (the head start) | none: 600 s |
| o8 (`:1688`), l3 (`:1102`) | o8: the newer segment until its gate; l3: nothing | 2.5 s; 1.0 s | about 2.3 s; a window of about 5 ms | unchanged, budgets stated (D3) |

## 2. Solution

One slice, two milestones. **M1** edits the five cases of `tests/test_bf887_continue_resumes_the_promoted_turn.py` by seven SEARCH/REPLACE blocks: a named `_LONG_SEGMENT_S` (600 s) and a `deadline` parameter on the L family's config; l4 gives its first segment the long deadline, asserts the state it depends on (the item `blocked` on its own ask, `item.id in rig.agent._promoted_turn_continuations`, no watchdog fired yet), assigns the short deadline to the rig's own `DmAgenticConfig` object between the segments, and asserts afterwards that exactly one watchdog fired and that it was the resumed segment's (`(deadline 1.0s)`); o1 does the same per variant (`*-finished`: every segment long; `*-watchdog`: the older segment `_O_STOPPED_S` = 6.0 s, the newer long, assigned between the approvals), loses its 1.0 s head start and `_O_HEAD_START_S`, and asserts which watchdog fired. No production line changes. **M3** is the trackers and the ledger. There is **no M2**: the fix is the test change, and the TDD order (a marked failing case first, the source second) has nothing to mark, because the old cases pass on an idle host: the oracle is the injection probe (Appendix P), run on the head before M1 and on M1's head. The probe is not committed.

## 3. Decisions

Each table ranks the options by correctness, safety, compatibility, fit, reversibility and validation cost; the first row is the decision. In-envelope means evidence, backward compatibility, no weakened control, no OSS/commercial boundary crossed, bounded rollback.

**D1. Milestones, tiers and what the oracle measures.**

| # | Option | Judgement |
|---|---|---|
| 1 | **M1 the test edits (one commit), M3 the trackers; no M2** | The change is the test; nothing can be marked `built` because nothing fails on the base without the injection; M1 is reviewed against the probe, which is the acceptance the #1754 comment named |
| 2 | M1 a committed stall-injecting case (xfail), M2 the edit, M3 trackers | Commits a timing test into the suite (a pause of seconds, repeated each gate) to prove the removal of timing exposure; #1572's acceptance did not commit its probe |
| 3 | One commit with the trackers | No revert granularity; the ledger gate needs its own step |

**Tiers.** **M1 HIGH**: tests only, but a changed case can silently lose the seam it guards, and the first fix of #1300 was measured inert in review; the Diff Reviewer reads M1 against the probe's two runs and the mutation rows. **M3 STANDARD**: trackers and the ledger. **What the oracle measures.** *Without the injection:* the file's collected count equals M0 (62 expected) and all pass (G1); on the pre-M1 head the five controls of the probe pass. *Under the injection* (a pause of twice the old deadline in the first segment after its ask is filed, and for o1 inside the approval): on the pre-M1 head all 11 stalled runs fail, the two primary shapes with the log signature (Appendix P, premises P1 to P5); on M1's head all 11 pass.

**D2. The edit, exactly.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Assign `dm.promoted_run_deadline_seconds` between segments on the rig's own config object; 600 s for a segment the case needs alive; the short value only for the segment the real watchdog must stop; assert the state before approving** | Uses the mechanism the production code has (read at segment start, one object); no production change; each case still crosses ask, approval, resume, real watchdog and release; the order is by state (`blocked` on its ask, the next pass held), and the one remaining clock is the subject of the case |
| 2 | Raise the constants (the item's old shape: a larger settle bound, 2.5 s to 10 s) | Lowers the rate and keeps the dependence on the clock that the earlier fix of #1300 removed; the settle bound only reports the failure |
| 3 | A retry or a settle bound that restarts with progress | Cannot help: the first segment is already stopped when the bound starts (the earlier consult's finding) |
| 4 | Patch the supervisor's deadline, or the coercion, in the test | The case would no longer run the real watchdog on the real read |

*Per case.* **l4:** `dm = _watchdog_config(deadline=_LONG_SEGMENT_S)`; after `_promote_and_stop`, `len(pending) == 1 and pending[0].work_item_id == item.id` (before any `pending[0]`), the item `blocked` on `pending[0].id`, `item.id in rig.agent._promoted_turn_continuations`, `len(scripted.calls) == 1 and not _watchdog_lines(caplog)`; `dm.promoted_run_deadline_seconds = 1.0`; `_approve`; the existing three assertions; then exactly one watchdog line, naming the item and `(deadline 1.0s)`. **o1:** `older_s = _O_STOPPED_S if ending == "watchdog" else _LONG_SEGMENT_S`; the first segment gets `_LONG_SEGMENT_S` when the older segment is the resumed one, else `older_s`; for `resumed`, the first segment's state is asserted and `older_s` is assigned before the first approval (the resumed segment reads it when the approval starts it, and the older's park is awaited before the next assignment, so the read has happened); before the second approval the older segment's state (`blocked` on its ask, held next pass, no watchdog yet) is asserted and `_LONG_SEGMENT_S` is assigned (the newer segment must outlive the older one's end); the head start line is deleted; the wait for the older segment's end is bounded by its own deadline plus the settle bound; after it, a watchdog case asserts exactly one watchdog line with `(deadline 6.0s)` and a finished case asserts none. **Constants.** `_LONG_SEGMENT_S = 600.0` (above `_watchdog_config`, shared by l4 and o1); `_O_DEADLINE_S = 2.5` stays for o8 only; `_O_STOPPED_S = 6.0` is new; **`_O_HEAD_START_S` goes** (its one use goes); `_o_config` takes the deadline. `_watchdog_config(deadline: float = 1.0)` keeps l3's call as it is.

*Why 6.0 s for the older segment of a watchdog case* (a real choice: its stop by the real watchdog is the case's subject, so unlike every other segment it cannot be made long):

| # | Older deadline | Judgement |
|---|---|---|
| 1 | **6.0 s** | Budget about 5.7 s for the pause before the approval has started the newer segment (chain about 0.3 s); the probe's pause of twice the old deadline (5.0 s) passes it with 0.7 s to spare; the doubles' own 10 s guards (the older's hold, the newer's gate) still bound the case from the other side with about 4.2 s at their worst placement (L2); +3.5 s of wall time per watchdog case |
| 2 | 2.5 s, head start removed | Budget about 2.3 s; the probe cannot show "passes at twice the old deadline" for these two cases |
| 3 | 7.0 s | E1 budget 6.7 s, but the guards' worst placement falls to about 3.2 s: the weakest link gets weaker |
| 4 | Trigger the older's stop by state (cancel it by hand) | Not the real watchdog: the case asserts `hold.task.cancelled()` and the watchdog's warning |

**D3. The sweep** (enumerations in section 11; "idle budget" = the pause the case survives, estimated as the deadline less the chain, reasoned from the files and the gate's JUnit times, not measured).

| # | Test (file:line) | Deadline | Segment that must NOT fire; idle budget | Verdict |
|---|---|---|---|---|
| 1 | bf887 l3 (`:1102`) | 1.0 s | none (its run is the one stopped); only the premise at `:1109` sits inside the clock, one store read after arm: a window of about 5 ms | left; budget stated |
| 2 | bf887 l4 (`:1118`) | 1.0 s | the first segment, arm to park: about 0.9 s | **changed** (600 s) |
| 3 | bf887 g1, g1b (`:1199`, `:1222`) | 1200 s; default 1800 s | immune | left |
| 4 | bf887 o1 x 4 (`:1340`) | 2.5 s | see section 1 | **changed** |
| 5 | bf887 o6 (`:1588`; `start_resumed_run(deadline_seconds=0.2, unconfirmed_grace_seconds=0.3)`, grace patched to 0.05 s at `:1593`) | 0.2 s | none: the run refuses its cancel and is the one stopped; the "newer segment" is a state written at `:1597` before the run starts | out of scope: no clock orders anything |
| 6 | bf887 o8 x 2 (`:1688`; grace 0.05 s at `:1700`, unconfirmed grace 0.15 s) | 2.5 s, both segments | the newer segment until `gates[newer].set()`: about 2.4 s; for `resumed`, the first segment, arm to park: about 2.3 s | left; **budget about 2.3 s stated** (the earlier consult's ruling stands: nothing in the sweep gives a reason to change it) |
| 7 | **`tests/test_ad1246_long_run_promotion.py:477`** (`promoted_run_deadline_seconds=1.0`, `promote_to_task_after_seconds=0.6`) | 1.0 s | none: one segment, stopped by the watchdog by design. The only premises that read a clock: `beats > beats_at_ack` 0.5 s after the ack (the child writes a beat every 0.1 s, `:236`, so it holds under a pause) and `beats_at_report < 50` (50 beats take about 5 s, so a pause of more than about 3 s lets the child finish before the stop): budget about 3 s | out of scope; budget stated (reasoned from `:227-238` and `:505`; not measured) |
| 8 | `tests/test_issue1417_run_python_child_ownership.py:380` | 4.0 s, promotion 2.0 s | none: a single run stopped by design; the child must start and write 3 beats before the stop at 6.0 s from the turn start: about 5 s | out of scope: already widened once by the comment at `:376-377` |
| 9 | `tests/test_bf733_promoted_run_deadline.py`: `deadline=0.2` at 18 call sites (`:194`, `:218`, `:273`, `:308`, `:340`, `:381`, `:468`, `:496`, `:524`, `:546`, `:622`, `:686`, `:724`, `:862`, `:898`, `:965`, `:1054`, `:1153`) and `deadline_seconds=0.2` at `:580`; grace patched at `:267`, `:302`, `:333`, `:619`, `:856` (2.0 s), `:895` (2.0 s), `:959`, `:1048` | 0.2 s | none: each run (`_never`, a stubborn run, a late lander) is the one the watchdog must stop; there is no second segment, so no clock orders two segments | out of scope |
| 10 | same file: `deadline=5.0` (`:1100`), `30.0` (`:761`, `:1183`), `60.0` (`:421`, `:808`), `0.0` (`:1120`) | | the run must outlive the test body: 5.0 s with a 0.05 s run leaves about 4.9 s; the others are cancelled by the test | out of scope; budgets stated |
| 11 | `tests/test_bf825_a_run_someone_is_waiting_on.py`: 0.2 s at `:287`, `:402`, `:454`, `:489`, `:523`; 0.0 at `:585`, `:656`, `:702`; grace patched by a fixture (`:254`) | | none: the watchdog fires by design on a stubborn run; the later windows are BF-825's strand clock, not a second segment | out of scope |
| 12 | `tests/test_ad1165_turn_promotion.py:1481` (0.02 s; grace 0.01 s at `:1456`) and `tests/test_ad1274_report_off_loop.py:694` (0.1 s; grace 0.05 s at `:664`) | | none: the watchdog is the subject | out of scope |
| 13 | the nine other test files that call an arm-capable entry point (`test_ad1227`, `test_ad1226`, `test_ad1224`, `test_ad1204`, `test_ad1248`, `test_ad1156`, `test_ad1323`, `test_bf732`, `test_bf705`) | none passed | n/a: the default `deadline_seconds` is 0.0 (`turn_promotion.py:2025`, `:2343`, `:2768`), so no watchdog is armed; a test that reaches the agent with a default `DmAgenticConfig` arms 1800 s | out of scope |

**D4. The probe.**

| # | Option | Judgement |
|---|---|---|
| 1 | **Import the real case functions and run them under a `CapabilityRequestStore` subclass that stalls (after the ask commits, and inside the approval), once per tree, with an expectation per tree** | The same probe shows the old cases fail with the logs' signature and the new ones pass; it cannot drift from the cases; premises P1 to P7 prove the stall was entered and the right tree was imported |
| 2 | Copy the case bodies into the probe | Diverges from the cases it must test |
| 3 | Commit the injection as a test | See D1 |

Placement follows the earlier consult: **after the ask commits and before the park** for l4 (a stall before the commit leaves `pending == []`: an `IndexError`, a different shape); **inside the approval, after the older segment's park** for o1 (the o1 signature has the three records `moved on` and `holds no next pass`: the stall sits after the park). Appendix P states how it is run and how the orchestrator knows it discriminated.

**D5. Mutation rows.** Section 9: four mutants of the new test text, three production mutants whose kill sets must be equal before and after M1 (no seam lost), and one row that survives by design, with what it changes.

**D6. The paperwork.**

| # | Option | Judgement |
|---|---|---|
| 1 | **No number; commit subjects and tracker heads name the work (`GATE-F3 of #1754`); tick GATE-F3 in the parent by the same-length `[ ]` to `[x]` on its line, and post one comment with the probe's two tables and the sweep verdicts** | The ledger reads no token; the body stays at its length (5,782 characters of headroom are not needed); the comment carries the evidence |
| 2 | Append "fixed in ..." to the item text | Uses headroom for text the comment holds |
| 3 | Allocate a BF number | No issue exists and none is needed: parent-backed, the discovery budget stays unspent |

**D7. Public text.** Synthetic fixtures only; no crew name, thread id, timestamp or live count in any test line, comment, tracker line, commit message or this contract; the test file's agent constant is already public in that file and is not copied into new text; every new log assertion matches a source message, not a captured line.

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. All commands run **from the repository root**, exactly as typed. **Who runs what.** The Builder may run only the focused pytest file named in G1 (always `-n 0`) and the greps named in G2. **Mine (the orchestrator's):** the probe, the mutation campaign, the ledger comparison against the measured diff, the broad gate, the pull request.

**M0 (before M1):** `PY -m pytest tests/test_bf887_continue_resumes_the_promoted_turn.py --collect-only -q`, and record the count (expected 62: the gate that failed ran 62; 52 test functions, the rest are parametrize ids).

| M | Blocks | Gate |
|---|---|---|
| M1 | P1-1 to P1-7 | G1, G2 |
| M3 | P3-1, P3-2, ledger | G3 |

- **G1.** `PY -m pytest tests/test_bf887_continue_resumes_the_promoted_turn.py -q -n 0 -p no:randomly`. **Expected (not measured): 62 passed**, the same count as M0, in about 5 s more wall time than before (+3.5 s for each of the two watchdog cases, which wait 6.0 s for the older segment's stop instead of 2.5 s; -1.0 s for each of the two finished cases, which lose the head start). A failure at G1 goes back to the Architect: there is no marked case to wait for.
- **G2 (no stray name, no lost case).** `PY -m pytest tests/test_bf887_continue_resumes_the_promoted_turn.py --collect-only -q` prints the count M0 recorded; `rg -n "_O_HEAD_START_S|_o_config\(\)" tests` prints nothing; `rg -n "_watchdog_config|_o_config|_LONG_SEGMENT_S|_O_STOPPED_S|_watchdog_lines" tests src scripts` finds them only in the one file.
- **G3 (M3).** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. **Expected (not measured):** no AD or BF number moves; the report's git-log row changes; the skipped-line numbers it lists for `PROGRESS.md` shift by the 4 lines the entry adds (and for `DECISIONS.md` by its entry's lines, if listed below the insertion); the non-check run rewrites `docs/development/ad-ledger-snapshot.json`. **Any changed row of an AD or BF number is a hard stop for the Architect.**

**Final gate (mine, once, after the Diff Reviewer's findings are repaired and the reviewed tree is committed locally):** (1) the probe of Appendix P, twice (the pre-M1 head with `GF3_EXPECT=unfixed`, M1's head with `GF3_EXPECT=fixed`); (2) the mutation rows of section 9; (3) `PY scripts/run_test_gate.py --label gate-f3 --receipt logs/gates/gate-f3.receipt.json`. **Harness rule.** No source change made to pass a test, no skip, no loosened assertion, no larger constant than the contract's; a failing case at G1, or a probe that disagrees with Appendix P, goes back to the Architect.

## 5. Commit messages

- **Contract commit (the orchestrator's):** `Promoted-turn resume cases (GATE-F3 of #1754): contract for giving each segment the deadline its role needs`
- **M1:** `Promoted-turn resume cases S1 M1: each segment gets the deadline its role needs, and the cases assert the first segment parked before they approve (GATE-F3 of #1754)`
- **M3:** `Promoted-turn resume cases S1 M3: trackers and ledger (GATE-F3 of #1754)`; its body ends with the line `Refs #1754.`

The parent is an open umbrella, so no message carries `Closes`. No subject starts with, or contains, an `AD-` or `BF-` token; no message names a crew member, a thread or a live figure.

## 6. Tests

No file is added and no test function is added or removed; five cases change. **What each still proves (no seam lost)** and what is new:

| Case | Before | After (what it still crosses) | New premises |
|---|---|---|---|
| l4 | both segments under 1.0 s | ask, park (first segment), the real decide route, resume, the real watchdog on the resumed pass, the item closed `failed`, the held pass released (`_held_turns == 0`) | the ask is the item's; the item is `blocked` on it; the next pass is held; no watchdog fired before the approval; exactly one fired and it was the 1.0 s one |
| o1 `first-finished`, `resumed-finished` | real watchdogs of 2.5 s that must not fire, and a 1.0 s head start | the approval of an older segment's ask while that segment is inside its park; the older ends by itself; the newer owns the item, parks, is approved, runs to done; real long watchdogs stay armed on every segment | before the approval: the older holds the next pass and no watchdog fired; after the older's end: no watchdog fired at all |
| o1 `first-watchdog`, `resumed-watchdog` | both segments under 2.5 s; the newer's own clock fell 1.0 s after the older's | the same chain, with the older segment stopped by its real 6.0 s watchdog after the approval started the newer one; `hold.task.cancelled()`; the "stopped by its watchdog after the item moved on" warning; the newer still running, owning the item, then done | before the approval (as above); exactly one watchdog fired and it was the 6.0 s one, not the newer's |

**What the changed cases no longer do:** the newer segment of the watchdog cases no longer has a real clock of its own that falls after the older's (the head start existed only for that); a real watchdog stopping a *resumed* segment while a newer one lives is still run by l4's and o8's watchdogs and by the `resumed-watchdog` case (its older segment is the resumed one). **Expected counts (not measured):** 62 collected before and after; all pass at G1; the probe's 17 results per tree (Appendix P). **Case-level honesty.** A watchdog case's older deadline is still a clock (L1); the two guards of the doubles bound the case from the other side (L2).

## 7. The contract

Labels restart in the slice. Section 6 names the cases; this section gives every block. `PY`, the commands and who runs them are in section 4. SEARCH text is LF; the working copies are CRLF (the apply tool matches on LF). **Every SEARCH below occurs exactly once in its file on `origin/main` `4d8c51e4` and on the reading tree `b83ed1e3` (the test file's blob is the same on both), starts at a line start and is ASCII** (section 11: run on the LF blobs of both refs, 7 SEARCHes of the test file plus the 2 tracker anchors, 0 problems). No block's SEARCH overlaps another's; the blocks of one file are applied in label order; every REPLACE is ASCII and no line is longer than 110 characters. **A label line names the file of its block by the full path in backticks**: the apply tool takes a pair's file from the nearest preceding label line that names an existing path. This slice creates no file.

### 7.1 Slice S1 (each segment of the resume cases gets the deadline its role needs)

#### S1 M1 (tests only)

**P1-1** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: the named long deadline, the deadline parameter of the L family's config, and the helper that reads BF-733's stop from the log).
SEARCH:
```
def _watchdog_config() -> DmAgenticConfig:
    """A BF-733 deadline short enough to reach: the real watchdog stops the run."""
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=1.0,
    )
```
REPLACE:
```
# GATE-F3: the BF-733 deadline is read when a segment STARTS, from the rig's own DmAgenticConfig, so a
# case gives each segment the deadline its role needs: this one to a segment the case needs alive (no
# pause of the host can reach it), a short one only to the segment the real watchdog must stop.
_LONG_SEGMENT_S = 600.0


def _watchdog_config(deadline: float = 1.0) -> DmAgenticConfig:
    """A BF-733 deadline short enough to reach: the real watchdog stops the run."""
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=deadline,
    )


def _watchdog_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """One line per BF-733 watchdog that fired: it names the work item and the deadline it spent."""
    return [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.WARNING and "BF-733: promoted run" in r.getMessage()
        and "made no return in" in r.getMessage()
    ]
```

**P1-2** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: L4, the first segment gets the long deadline, the case asserts the state it depends on, assigns the short deadline between the segments and asserts which watchdog fired).
SEARCH:
```
async def test_l4_a_resumed_pass_the_watchdog_stops_holds_nothing(make_rig, scripted):
    rig = await make_rig(dm=_watchdog_config())
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done("never returned")]
    scripted.gates = {0: gate, 1: asyncio.Event()}  # the next pass outlives its deadline
    item, pending = await _promote_and_stop(rig, gate)

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 2, "premise: the next pass started"
    assert (await rig.work_items.get_work_item(item.id)).status == "failed", (
        "premise: BF-733's watchdog stopped it and its reporter closed the item"
    )
    assert _held_turns(rig) == 0
```
REPLACE:
```
async def test_l4_a_resumed_pass_the_watchdog_stops_holds_nothing(make_rig, scripted, caplog):
    # GATE-F3: the first segment is not what this case stops, so it gets a deadline no pause of the host can
    # reach; the resumed pass gets the short one when the approval starts it, and only its watchdog can fire.
    dm = _watchdog_config(deadline=_LONG_SEGMENT_S)
    rig = await make_rig(dm=dm)
    caplog.set_level(logging.WARNING, logger=_PROMOTION_LOG)
    gate = asyncio.Event()
    scripted.script = [_cut(PARTIAL), _done("never returned")]
    scripted.gates = {0: gate, 1: asyncio.Event()}  # the next pass outlives its deadline
    item, pending = await _promote_and_stop(rig, gate)
    assert len(pending) == 1 and pending[0].work_item_id == item.id, "premise: the first pass filed its ask"
    parked = await rig.work_items.get_work_item(item.id)
    assert parked.status == "blocked" and parked.metadata["capability_request_id"] == pending[0].id, (
        "premise: the first segment parked the item on its ask"
    )
    assert item.id in rig.agent._promoted_turn_continuations, "premise: and kept the turn's next pass"
    assert len(scripted.calls) == 1 and not _watchdog_lines(caplog), "premise: no watchdog has fired yet"
    dm.promoted_run_deadline_seconds = 1.0  # read when the next segment starts

    await _approve(rig, pending[0].id)

    assert len(scripted.calls) == 2, "premise: the next pass started"
    assert (await rig.work_items.get_work_item(item.id)).status == "failed", (
        "premise: BF-733's watchdog stopped it and its reporter closed the item"
    )
    fired = _watchdog_lines(caplog)
    assert len(fired) == 1, "premise: exactly one watchdog fired"
    assert item.id in fired[0] and "(deadline 1.0s)" in fired[0], "premise: it was the resumed segment's"
    assert _held_turns(rig) == 0
```

**P1-3** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: the O family's constants; the head start goes, the older segment's stopped deadline comes, and O1's config takes a deadline).
SEARCH:
```
# The older segment's deadline, and how long before it the newer segment starts:
# the newer one's own deadline then falls a head start after the older one's.
_O_DEADLINE_S = 2.5
_O_HEAD_START_S = 1.0
SCIENCE = "science_science_0_5d2e8f10"


def _o_config() -> DmAgenticConfig:
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=_O_DEADLINE_S,
    )
```
REPLACE:
```
# O8's deadline for its older and its newer segment (O8 is unchanged; its budget is stated in the contract).
_O_DEADLINE_S = 2.5
# O1's older segment of the two watchdog cases: the one segment the real watchdog must stop, and only
# after the approval has started the newer one. It outlasts a pause of the host of twice O1's earlier
# deadline plus a second for the approval and a margin, and it leaves the doubles' own 10 s hang guards
# (the older's hold, the newer's gate) room to outlast it. Every other segment of O1 is alive for the
# whole case: _LONG_SEGMENT_S.
_O_STOPPED_S = 6.0
SCIENCE = "science_science_0_5d2e8f10"


def _o_config(deadline: float) -> DmAgenticConfig:
    return DmAgenticConfig(
        enabled=True, continue_or_ask_enabled=True, continue_or_ask_max_passes=1,
        promote_to_task_after_seconds=0.05, promoted_run_deadline_seconds=deadline,
    )
```

**P1-4** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: O1's setup, the first segment's deadline by the case's role).
SEARCH:
```
    rig = await make_rig(dm=_o_config())
    caplog.set_level(logging.INFO)
    newer = 1 if older == "first" else 2  # the newer segment's pass, by index
```
REPLACE:
```
    # GATE-F3: the deadline is read when a segment starts, so each segment gets the one its role needs.
    # Only the older segment of a watchdog case is stopped by its watchdog, and only after the approval
    # has started the newer one; every other segment is alive for the whole case. A resumed older
    # segment starts later (below).
    older_s = _O_STOPPED_S if ending == "watchdog" else _LONG_SEGMENT_S
    dm = _o_config(_LONG_SEGMENT_S if older == "resumed" else older_s)
    rig = await make_rig(dm=dm)
    caplog.set_level(logging.INFO)
    newer = 1 if older == "first" else 2  # the newer segment's pass, by index
```

**P1-5** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: O1's resumed older segment, the first segment's state before the first approval and the deadline its start reads).
SEARCH:
```
    if older == "resumed":
        await _settle(rig)
        (first_ask,) = await rig.requests.list_pending()
        await _approve_now(rig, first_ask.id)
        scripted.gates[1].set()
```
REPLACE:
```
    if older == "resumed":
        await _settle(rig)
        (first_ask,) = await rig.requests.list_pending()
        first = await rig.work_items.get_work_item(item.id)
        assert first.status == "blocked" and first.metadata["capability_request_id"] == first_ask.id, (
            "premise: the first segment parked the item on its ask"
        )
        assert item.id in rig.agent._promoted_turn_continuations, "premise: and kept the turn's next pass"
        dm.promoted_run_deadline_seconds = older_s  # read when the approval starts the resumed older one
        await _approve_now(rig, first_ask.id)
        scripted.gates[1].set()
```

**P1-6** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: O1's older segment's state before the approval, the newer segment's deadline, and no head start).
SEARCH:
```
    assert hold.task in older_tasks and len(older_tasks) == 2, "premise: the older run and reporter"
    await asyncio.sleep(_O_HEAD_START_S)

    await _approve_now(rig, older_ask.id)
```
REPLACE:
```
    assert hold.task in older_tasks and len(older_tasks) == 2, "premise: the older run and reporter"
    assert item.id in rig.agent._promoted_turn_continuations, "premise: the older still holds the next pass"
    assert not _watchdog_lines(caplog), "premise: no watchdog has fired before the approval"
    dm.promoted_run_deadline_seconds = _LONG_SEGMENT_S  # the newer segment must outlive the older one's end

    await _approve_now(rig, older_ask.id)
```

**P1-7** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`: O1's wait for the older segment's end, bounded by its own deadline, and which watchdog fired).
SEARCH:
```
    if ending == "finished":
        hold.release.set()
    await asyncio.wait(older_tasks, timeout=_SETTLE_S)
    assert all(t.done() for t in older_tasks), "premise: the older segment has ended"
    assert hold.task.cancelled() is (ending == "watchdog"), "premise: by the real watchdog, or not"
    assert not any(t.done() for t in newer_tasks), "premise: the newer segment is still running"
```
REPLACE:
```
    if ending == "finished":
        hold.release.set()
    # A watchdog case waits for the older segment's own deadline; no other clock bounds it.
    await asyncio.wait(older_tasks, timeout=_SETTLE_S + (_O_STOPPED_S if ending == "watchdog" else 0.0))
    assert all(t.done() for t in older_tasks), "premise: the older segment has ended"
    assert hold.task.cancelled() is (ending == "watchdog"), "premise: by the real watchdog, or not"
    assert not any(t.done() for t in newer_tasks), "premise: the newer segment is still running"
    fired = _watchdog_lines(caplog)
    if ending == "watchdog":
        assert len(fired) == 1, "premise: exactly one watchdog fired"
        assert item.id in fired[0] and f"(deadline {_O_STOPPED_S:.1f}s)" in fired[0], (
            "premise: it was the older segment's, not the newer one's"
        )
    else:
        assert fired == [], "premise: no watchdog fired"
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it. Replace `DATE` with M3's date. The entry is 4 lines (heading, two bullets, blank). The heading starts with a word, not a number, so the ledger reads no head token from it.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**Promoted-turn resume cases give each segment the deadline its role needs (DATE), GATE-F3 of #1754 -- a pause of the host of about a second in a segment a case needs alive no longer ends the case.**
- **Base.** The resume cases of `tests/test_bf887_continue_resumes_the_promoted_turn.py` armed a real watchdog (1.0 s, or 2.5 s) for every segment of a case. The deadline is read when a segment starts, so it also bounded the older segment the case needs alive: a pause of about 0.9 s (the resumed-pass case) or 1.3 s (the older-segment cases) let the watchdog stop it, and the case failed (sections 15 and 16 of the contract record how). Seen on loaded CI and gate hosts; no production line was involved.
- **Change (tests only).** The cases assign the rig's own deadline between segments: 600 s for a segment the case needs alive, the short one only for the segment the real watchdog must stop (the resumed pass; the older segment of the two watchdog cases, 6.0 s, after the approval). State orders the case: it asserts the first segment parked and holds the next pass before it approves, and which watchdog fired. The fixed 1.0 s head start is gone. The acceptance is an injected pause of twice the old deadline (in the first segment after its ask is filed, and inside the approval): the old cases must fail in the shape the logs show and the new ones pass; the probe is not committed, and its measured result is in sections 15 and 16 of the contract `prompts/gate-f3-segment-deadlines.md`. Refs #1754.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows this period's entries (once on `origin/main` `4d8c51e4`, at line 1748, and once on the reading tree, at line 1764; every earlier batch's entry, including the promotion-post slice's, is inserted before it and re-inserts it, so this slice's entry is inserted before it as well and the order is the order of landing). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date. The heading names no AD or BF number.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### Promoted-turn resume cases give each segment the deadline its role needs (DATE, GATE-F3 of #1754)

- *Scope.* `tests/test_bf887_continue_resumes_the_promoted_turn.py` only: the resumed-pass case and the four older-segment cases. No source, config or other test changes. Contract `prompts/gate-f3-segment-deadlines.md`.
- *G1 (the fix).* The promoted run's watchdog deadline is read when a segment starts, from the rig's own config object, so a case assigns it between segments: 600 s for a segment the case needs alive, the short one only for the segment the real watchdog must stop. Rejected: a larger settle bound, or one that restarts with progress (the bound only reports the failure); a retry; a production change (the watchdog is right); raising the old constants (lowers the rate and keeps the dependence on the clock).
- *G2 (what stays a clock).* The older segment of the two watchdog cases must be stopped by its real watchdog only after the approval has started the newer one; that order is the case's subject, so its deadline (6.0 s) is a stated budget of about 5.7 s of pause, not a constant to raise later. The other-segment cases of the file (one with a window of about 2.3 s, one of about 5 ms) and the single-segment watchdog tests of other files are left with their budgets stated in the contract.
- *G3 (public text).* Synthetic fixtures only; no crew name, thread id, timestamp or live count in any test, comment, tracker line or commit message.
- *Residual.* L1 to L6 of the contract. *Reversal.* Revert the two commits of the slice, M3 then M1; nothing is stored by the change.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3 (section 4). No AD or BF number moves: no head of this slice's tracker text or commit subjects is a number. The roadmap Bug Tracker is not edited. **After the merge (the orchestrator, not a block):** tick GATE-F3 in #1754 (the section "Not in this issue: for the Captain" of part 3 gives the line).

---

## Appendix P: the injection probe (for the orchestrator, NOT for the Builder; never committed)

The orchestrator copies this file to `tests/probe_gf3.py` of its oracle worktree (an untracked file; delete it afterwards) and runs it **twice**: on the head before M1's blocks (`GF3_EXPECT=unfixed`) and on M1's head (`GF3_EXPECT=fixed`). It imports the real case functions of the test file, runs each under a stall injected through `make_rig(requests_cls=...)`, and asserts, per tree, what that tree must do. It has not been run, and not even compiled, by the Architect (a read-only consult on a host under a gate): the first run may need a mechanical fix; the logic is what matters. **Command (from the worktree root, serial; PowerShell):**

```
$env:GF3_TREE = (Get-Location).Path          # the tree whose src and tests must be the ones imported (premise P7)
$env:GF3_EXPECT = "unfixed"                  # then "fixed" on M1's head
$env:GF3_OUT = "$env:TEMP\gf3-$env:GF3_EXPECT.jsonl"
$env:PYTHONPATH = "$($env:GF3_TREE)\src;$($env:GF3_TREE)"     # src for probos, the root so that tests.* resolves
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/probe_gf3.py -n 0 -p no:randomly -p no:cacheprovider -q -s
```

**How the orchestrator knows it discriminated.** Each tree gives 17 results (16 scenarios: 5 controls and 11 stalled runs, and the tree check). On the unfixed tree all 17 pass, which means: the 5 controls pass, the 11 stalled runs fail, and the two primary shapes (the resumed-pass case with the stall after its ask is filed; each O1 case with the stall inside the approval) show the gate's and CI's signature (premises P1 to P5). On the fixed tree all 17 pass, which means the 5 controls and the 11 stalled runs pass and each watchdog line is the intended segment's. The stalled runs are: L4, a pause of 2.0 s in the first segment after its ask is filed; each O1 case, a pause of 5.0 s inside the approval that follows the older segment's park (`decide`) and in the older segment after its ask is filed (`file_request`); and, for the two `resumed` cases, also in the first segment (`file_request1`). A run whose stall was never entered, or that imported another tree, fails its own premise (P1, P7), so it cannot count. The JSON lines in `GF3_OUT` carry each run's facts (error, stall flags, the watchdog lines with the `len(scripted.calls)` stamp, the records at WARNING and above, the item's final state). If a tree gives a different count, report the failing premises, not a verdict. **The margin of the two fixed watchdog cases** is 0.7 s (5.0 s of pause plus a chain of about 0.3 s against 6.0 s); if the oracle's chain is longer than 0.7 s, lower those four stalls (`decide` and `file_request` of the two `*-watchdog` cases) to 4.5 s and say so in the report.

```python
"""GATE-F3 injection probe (never committed; the orchestrator runs it on its oracle worktree).

A pause is injected into the first segment of a case after its ask has been filed ("file_request") and, for the
four O1 cases, into the approval that follows the older segment's park ("decide"); the real case functions of
tests/test_bf887_continue_resumes_the_promoted_turn.py then run under it. Each case also runs once with no pause
(the control). GF3_EXPECT says what the tree under test must do: "unfixed" (the old cases: every stalled run fails,
in the shape the gate and CI logs show) or "fixed" (every stalled run passes).

Premises (a run that never stalled, or that imported another tree, cannot pass as evidence):
  P1 the stall was entered; on the primary unfixed shape of the resumed-pass case it was cancelled by the watchdog;
  P2 the BF-733 line names the intended segment's deadline, elapsed >= deadline, stamped with len(scripted.calls);
  P3 the item and the asks are in the state the logs show (unfixed shapes);
  P4 the records at WARNING and above are the logs' (unfixed shapes);
  P5 the case fails at the assert the logs show (unfixed shapes);
  P6 the control passes, and its BF-733 line is the intended segment's;
  P7 turn_promotion and the test module were imported from GF3_TREE.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest

import tests.test_bf887_continue_resumes_the_promoted_turn as T
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import turn_promotion
from tests.test_bf887_continue_resumes_the_promoted_turn import make_rig, scripted  # noqa: F401  (fixtures)

TREE = Path(os.environ["GF3_TREE"]).resolve()
EXPECT = os.environ["GF3_EXPECT"]
OUT = os.environ.get("GF3_OUT", "")
assert EXPECT in ("unfixed", "fixed"), "GF3_EXPECT must be 'unfixed' or 'fixed'"

L4 = "test_l4_a_resumed_pass_the_watchdog_stops_holds_nothing"
O1 = "test_o1_an_older_segment_ending_under_a_newer_one_leaves_it_the_item"


@dataclasses.dataclass(eq=False)
class Case:
    name: str
    fn: str
    params: dict[str, str]
    newer: int  # O1: the newer segment's pass index (0 for L4)
    stalls: tuple[tuple[str, int, float], ...]  # (where, which call stalls, seconds)


CASES = (
    Case("l4", L4, {}, 0, (("file_request", 1, 2.0),)),
    Case("o1-first-finished", O1, {"older": "first", "ending": "finished"}, 1,
         (("decide", 1, 5.0), ("file_request", 1, 5.0))),
    Case("o1-first-watchdog", O1, {"older": "first", "ending": "watchdog"}, 1,
         (("decide", 1, 5.0), ("file_request", 1, 5.0))),
    Case("o1-resumed-finished", O1, {"older": "resumed", "ending": "finished"}, 2,
         (("decide", 2, 5.0), ("file_request", 2, 5.0), ("file_request", 1, 5.0))),
    Case("o1-resumed-watchdog", O1, {"older": "resumed", "ending": "watchdog"}, 2,
         (("decide", 2, 5.0), ("file_request", 2, 5.0), ("file_request", 1, 5.0))),
)
SCENARIOS = [(c, "", 0, 0.0) for c in CASES] + [(c, w, n, s) for c in CASES for (w, n, s) in c.stalls]
IDS = [f"{c.name}-control" if not w else f"{c.name}-{w}{n}-{s:g}s" for (c, w, n, s) in SCENARIOS]

_BF733 = re.compile(
    r"BF-733: promoted run for work item (\S+) made no return in ([0-9.]+)s \(deadline ([0-9.]+)s\)"
)


class _Plan:
    """Which call of which store method pauses, and what became of the pause."""

    def __init__(self, where: str, nth: int, seconds: float) -> None:
        self.where, self.nth, self.seconds = where, nth, seconds
        self.seen = {"file_request": 0, "decide": 0}
        self.filed: list[str] = []  # the id of every ask filed under this plan (the pending list is read after the case's own approval, when it is empty)
        self.entered = self.cancelled = self.finished = False

    async def at(self, where: str) -> None:
        self.seen[where] += 1
        if where != self.where or self.seen[where] != self.nth or self.seconds <= 0.0:
            return
        self.entered = True
        try:
            await asyncio.sleep(self.seconds)
            self.finished = True
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _stalling_store(plan: _Plan) -> type[CapabilityRequestStore]:
    class _Stalling(CapabilityRequestStore):
        async def file_request(self, **kwargs: Any) -> Any:
            filed = await super().file_request(**kwargs)
            plan.filed.append(str(getattr(filed, "id", "")))
            await plan.at("file_request")  # after the ask has committed, before the park
            return filed

        async def decide(self, *args: Any, **kwargs: Any) -> Any:
            await plan.at("decide")  # inside the approval, before the decision lands
            return await super().decide(*args, **kwargs)

    return _Stalling


class _Tap(logging.Handler):
    """Records at WARNING and above, each stamped with how many passes the scripted model has started."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.rows: list[tuple[str, str, int]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.rows.append((record.levelname, record.getMessage(), len(T._Executor.calls)))


def _tree_ok() -> bool:
    return (
        Path(turn_promotion.__file__).resolve().is_relative_to(TREE / "src")
        and Path(T.__file__).resolve().is_relative_to(TREE / "tests")
    )


async def _run(case: Case, where: str, nth: int, seconds: float, make_rig: Any, scripted: Any,
               caplog: Any, monkeypatch: Any) -> dict[str, Any]:
    fn = getattr(T, case.fn)
    plan = _Plan(where, nth, seconds)
    store_cls = _stalling_store(plan)
    rigs: list[Any] = []

    async def make(**kwargs: Any) -> Any:
        kwargs.setdefault("requests_cls", store_cls)
        rig = await make_rig(**kwargs)
        rigs.append(rig)
        return rig

    given = {"make_rig": make, "scripted": scripted, "caplog": caplog, "monkeypatch": monkeypatch}
    kwargs = {name: given[name] for name in inspect.signature(fn).parameters if name in given}
    kwargs.update(case.params)
    tap, logger = _Tap(), logging.getLogger("probos")
    logger.addHandler(tap)
    error: Exception | None = None
    started = time.monotonic()
    try:
        await fn(**kwargs)
    except Exception as exc:  # AssertionError, TimeoutError, ...
        error = exc
    finally:
        logger.removeHandler(tap)
    took = time.monotonic() - started
    item_state: dict[str, Any] | None = None
    if rigs:
        rig = rigs[0]
        items = await rig.work_items.list_work_items(assigned_to=T.AGENT)
        pending = await rig.requests.list_pending()
        item = items[0] if items else None
        item_state = {
            "n_items": len(items),
            "status": item.status if item else None,
            "ask": (item.metadata or {}).get("capability_request_id") if item else None,
            "pending_for_item": [p.work_item_id == (item.id if item else None) for p in pending],
            "asks_filed": len(plan.filed),
        }
    for gate in list(T._Executor.gates.values()):  # release everything, so the fixtures' teardown is quiet
        gate.set()
    for rig in rigs:
        tasks = set(rig.bus.tasks)
        if rig.agent is not None:
            tasks |= {t for t in rig.agent._promoted_turn_tasks if not t.done()}
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=T._SETTLE_S)
    marks = []
    for _level, message, calls in tap.rows:
        found = _BF733.search(message)
        if found:
            marks.append((found[1], float(found[2]), float(found[3]), calls))
    return {
        "case": case.name, "where": where, "nth": nth, "seconds": seconds, "expect": EXPECT,
        "error_type": type(error).__name__ if error else None,
        "error_text": str(error)[:300] if error else None,
        "entered": plan.entered, "cancelled": plan.cancelled, "finished": plan.finished,
        "bf733": marks,  # (item id, elapsed, deadline, len(scripted.calls) when it was emitted)
        "records": [(lvl, msg[:140], n) for (lvl, msg, n) in tap.rows],
        "item": item_state, "ran_seconds": round(took, 2), "tree_ok": _tree_ok(),
    }


def _check(case: Case, where: str, seconds: float, f: dict[str, Any]) -> list[str]:
    bad: list[str] = []

    def need(ok: bool, text: str) -> None:
        if not ok:
            bad.append(text)

    stalled, is_o1 = seconds > 0.0, case.fn == O1
    watchdog = case.params.get("ending") == "watchdog"
    deadline = (float(getattr(T, "_O_STOPPED_S", 6.0)) if EXPECT == "fixed" else 2.5) if is_o1 else 1.0
    need(f["tree_ok"], "P7: turn_promotion and the test module were imported from GF3_TREE")
    if not stalled or EXPECT == "fixed":
        what = "P6 (the control)" if not stalled else "the fixed case under the stall"
        need(f["error_type"] is None, f"{what} passes; got {f['error_type']}: {f['error_text']}")
        if stalled:
            need(f["entered"] and f["finished"] and not f["cancelled"],
                 "P1: the stall was entered, ran to its end and was not cancelled")
        else:
            need(not f["entered"], "P1: a control does not stall")
        marks = f["bf733"]
        if is_o1 and not watchdog:
            need(marks == [], f"P2: no watchdog fires in a finished case; got {marks}")
        else:
            need(len(marks) == 1, f"P2: exactly one watchdog fires; got {marks}")
            if len(marks) == 1:
                _item, elapsed, spent, calls = marks[0]
                stamp = case.newer + 1 if is_o1 else 2
                need(spent == deadline and elapsed >= spent, f"P2: the {deadline}s watchdog fired; got {marks[0]}")
                need(calls == stamp, f"P2: stamped len(scripted.calls) == {stamp}; got {calls}")
        return bad
    # EXPECT == "unfixed" and a stall: the old case must fail, and the stall must have been entered
    need(f["error_type"] is not None, "P5: the unfixed case must fail under the stall")
    need(f["entered"], "P1: the stall was entered")
    primary = (case.fn == L4 and where == "file_request") or (is_o1 and where == "decide")
    if not primary:
        return bad
    marks, records = f["bf733"], f["records"]
    if case.fn == L4:
        need(f["cancelled"] and not f["finished"], "P1: the stall was cancelled by the watchdog")
        need(len(marks) == 1, f"P2: exactly one watchdog fired; got {marks}")
        if len(marks) == 1:
            _item, elapsed, spent, calls = marks[0]
            need(spent == 1.0 and elapsed >= 1.0 and calls == 1, f"P2: the first segment's watchdog; got {marks[0]}")
        item = f["item"] or {}
        need(item.get("status") == "failed" and not item.get("ask"), f"P3: the item failed with no ask linked; got {item}")
        need(item.get("asks_filed") == 1, f"P3: one ask was filed, for the item; got {item}")
        need(len(records) == 1, f"P4: exactly one record at WARNING or above; got {len(records)}")
        need(f["error_type"] == "AssertionError" and "premise: the next pass started" in (f["error_text"] or ""),
             f"P5: fails at the resumed-pass premise; got {f['error_type']}: {f['error_text']}")
    else:
        need(f["finished"] and not f["cancelled"], "P1: the pause inside the approval ran to its end")
        need(len(marks) == 1, f"P2: exactly one watchdog fired; got {marks}")
        if len(marks) == 1:
            _item, elapsed, spent, calls = marks[0]
            need(spent == 2.5 and elapsed >= 2.5 and calls == case.newer,
                 f"P2: the older segment's watchdog, before the newer one started; got {marks[0]}")
        item = f["item"] or {}
        need(item.get("status") == "failed", f"P3: the item failed; got {item}")
        texts = [m for (_lvl, m, _n) in records]
        at = [next((i for i, t in enumerate(texts) if key in t), -1)
              for key in ("BF-733: promoted run", "after the item moved on", "AD-855/BF-887")]
        need(all(i >= 0 for i in at) and at == sorted(at), f"P4: the three records, in order; got {at}")
        need(f["error_type"] == "AssertionError" and "premise: reached within" in (f["error_text"] or ""),
             f"P5: fails at the newer pass's premise; got {f['error_type']}: {f['error_text']}")
    return bad


def test_p7_the_probe_imported_the_tree_under_test() -> None:
    print("GF3 tree:", TREE, "expect:", EXPECT, "turn_promotion:", turn_promotion.__file__)
    assert _tree_ok(), (turn_promotion.__file__, T.__file__)


@pytest.mark.parametrize(("case", "where", "nth", "seconds"), SCENARIOS, ids=IDS)
async def test_probe(case, where, nth, seconds, make_rig, scripted, caplog, monkeypatch) -> None:
    facts = await _run(case, where, nth, seconds, make_rig, scripted, caplog, monkeypatch)
    bad = _check(case, where, seconds, facts)
    facts["premises_failed"] = bad
    if OUT:
        with open(OUT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(facts, default=str) + "\n")
    print(f"GF3 {EXPECT} {case.name} {where or 'control'} {seconds:g}s -> "
          f"{facts['error_type'] or 'passed'} bf733={facts['bf733']} bad={bad}")
    assert not bad, bad
```

## 8. What this does NOT change

**Source.** Every line of `src/`: the watchdog (`_PromotedRunSupervisor`), `start_resumed_run`, `run_with_promotion`, the agent's three reads of `promoted_run_deadline_seconds` (`cognitive_agent.py:5391`, `:5477`, `:5578`), `_coerce_promotion_budget`, the continuation store, the driver. No retry, no quarantine, no skip. **The same test file, untouched:** `_SETTLE_S` (10 s) and every use of it; `_until`; `_hold_after`; `_approve`, `_approve_now`, `_promote_and_stop`, `_settle`; the doubles (`_Executor`, `_Bus`, `_Episodes`, the thread and request stores); the rig; `test_l3_...` (it calls `_watchdog_config()` as before: the new parameter defaults to 1.0 s); `test_g1_...`, `test_g1b_...`; `test_o6_...` and `test_o8_...` with `_o8_config` and `_O_DEADLINE_S` (2.5 s: kept for o8 only); every case of the S, A, N, C families. **Other tests:** every file of the sweep (D3 rows 7 to 13) is read, not edited. **All:** `config/system.yaml`, every Pydantic config model and generated reference; `ui/`; the commercial overlay (OSS only; no dependency; no schema change); every tracker but `PROGRESS.md`, `DECISIONS.md` and the AD ledger pair; the roadmap Bug Tracker table; the #1754 body except the tick the orchestrator makes after the merge.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M1's head, unless a row names the occurrence)

**Not run by the Architect** (a read-only consult on a host under a gate; the oracle's run is in section 15, which corrects rows 3 and 6 and the cells of C1 and C2); the Lines were checked in memory against the patched file (section 11), and the Killed-by cells are the cases I expect to fail. The oracle's campaign: each row's line replaced whole, the named file run at `-n 0` (and, where the cell says so, the probe in fixed mode), the file restored and its blob checked. **This table is the campaign of record only for a tree whose files equal the blobs the blocks give on `origin/main` `4d8c51e4`** (sha256 to be recorded by the oracle for the test file, `turn_promotion.py` and `cognitive_agent.py`); a Builder whose files match does not repeat it; if a file differs, the rows naming it are rerun. Case labels are section 6's; probe ids are Appendix P's (`<case>-<where><n>-<seconds>`).

**A. Mutants of the new test text (M1's head).**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `tests/test_bf887_continue_resumes_the_promoted_turn.py` | `dm = _watchdog_config(deadline=_LONG_SEGMENT_S)` | `dm = _watchdog_config()` | **not by the file's own run** (it passes on an idle host: that is the defect); the probe in fixed mode, `l4-file_request1-2s` (the first segment is stopped by the pause, so the case fails at `len(scripted.calls) == 2`) |
| 2 | same | `dm.promoted_run_deadline_seconds = 1.0  # read when the next segment starts` | line deleted | l4 itself, at an assert: the resumed pass keeps the 600 s deadline, is never stopped, and `_approve`'s `_settle` fails `AssertionError: premise: the rig settles within 10.0s (2 left)` after its own 10 s bound (not a hang: the pytest timeout is 180 s) |
| 3 | same | `dm = _o_config(_LONG_SEGMENT_S if older == "resumed" else older_s)` | `dm = _o_config(_O_DEADLINE_S)` | `o1[first-watchdog]` itself, at an assert (`premise: it was the older segment's, not the newer one's`: the older segment's watchdog then logs `deadline 2.5s`, not `6.0s`); and the probe in fixed mode: every stalled `o1-first-*` run, the `o1-resumed-*-file_request1-5s` runs and `o1-first-watchdog-control` (the control runs the case body, which this mutant fails) |
| 4 | same | `dm.promoted_run_deadline_seconds = older_s  # read when the approval starts the resumed older one` | line deleted | `o1[resumed-watchdog]` itself, at an assert: the resumed older segment keeps 600 s, is never stopped, and the bounded wait ends with `AssertionError: premise: the older segment has ended` after about 16 s |
| 5 | same | `fired = _watchdog_lines(caplog)` (O1) with its `if`/`else` | the block deleted | **survives** the file's own run and the probe. What then passes that should not: a `*-watchdog` case whose older segment was stopped by some watchdog other than its own 6.0 s one (for example the newer segment's, if row 6's assignment is also gone and a pause falls between the older's stop and the check), and a `*-finished` case in which some watchdog fired and was absorbed. `hold.task.cancelled()` still proves the older ended by a cancel, which is why the row survives; no single campaign row builds the wrong-watchdog state. Recorded (L3) |
| 6 | same | `dm.promoted_run_deadline_seconds = _LONG_SEGMENT_S  # the newer segment must outlive the older one's end` | line deleted | `o1[first-watchdog]` and `o1[resumed-watchdog]` themselves, at an assert (`premise: the newer segment is still running`): the newer segment then reads 6.0 s at its start, so its own watchdog stops it about 0.2 s after the older one's stop (the window E2), before the case's check; killed by the file's own run on an idle host (the contract expected it to survive); the probe in fixed mode fails the two watchdog controls and `o1-resumed-watchdog-file_request1-5s` |
| 7 | same | the premise lines of l4 (`assert len(pending) == 1 ...`, the `parked` pair, the held-pass line, `assert len(scripted.calls) == 1 and not _watchdog_lines(caplog), ...`) and of o1 (`assert item.id in rig.agent._promoted_turn_continuations, "premise: the older still holds ..."`, `assert not _watchdog_lines(caplog), "premise: no watchdog has fired before the approval"`, and the two of the `resumed` branch) | deleted | **nothing passes that should not**: every wrong path still fails at a later assert (l4 at `len(scripted.calls) == 2`; o1 at `_until`'s `premise: reached within 10.0s`); what is lost is the place and the name of the failure (the premise names the link that broke; without it the report names the approval) and 10 s per failure. Survives the file's own run and the probe: recorded, accepted (the premises are ordering evidence, and the diagnosis the item lacked) |

**B. Production mutants: the kill set must be equal before M1 and after it (no seam lost).** Each line is replaced whole on a tree at the pre-M1 head and again at M1's head, the whole file run at `-n 0`; the sets of failing case ids must be equal.

| # | File | Line (stripped) | Mutate to | Expected kill set (same on both heads) |
|---|---|---|---|---|
| C1 | `src/probos/cognitive/cognitive_agent.py` | `getattr(cfg, "promoted_run_deadline_seconds", 0.0)` (the **second** occurrence: the resumed segment's read, `:5477`) | `0.0` | l4; o1 `resumed-watchdog`; o8 `resumed`; g3 (`test_g3_the_agent_reports_and_bounds_the_resumed_run_exactly_as_the_first`) (the resumed segment's watchdog is disarmed) |
| C2 | same | the same line, the **third** occurrence (the first run's read, `:5578`) | `0.0` | l3; o1 `first-watchdog`; o8 `first`; g3; **not** l4 (its first segment is not stopped by design, before and after) |
| C3 | `src/probos/cognitive/turn_promotion.py` | `self._task.cancel()` (the **first** occurrence, in `_enforce`, `:552`) | `pass` | l3; l4; o1 both watchdog cases; o8 both (a watchdog that warns and never stops the run) |

Row 5's survivor and row 7's survivor are the two things this slice trades knowingly: the assertion that names the watchdog and the place and name of the premises are protection against a mistake of a later edit, not something a pause can reveal (row 6, the assignment that removes E2, was expected to survive and is killed: section 15).

## 10. Recorded limits

- **L1. A watchdog case's older segment is still ordered by a clock** (E1: its approval must start the newer segment before the older one's 6.0 s watchdog). Budget about 5.7 s of pause from the older's arm to the newer's start (a chain of about 0.3 s; estimated from the failed gate's JUnit times, not measured in a quiet run). It was about 1.3 s. It cannot be made a state: the stop by the real watchdog is the case's subject. The value is a stated budget, not a constant to raise.
- **L2. The doubles' own 10 s hang guards now bound the watchdog cases from the other side.** `_hold_after`'s release wait (`:1324`) holds the older segment inside its park, and `_Executor.run`'s gate wait (`:172`) holds the newer segment's pass, each under `asyncio.wait_for(..., timeout=_SETTLE_S)`. In a watchdog case both are waiting while the case waits for the older's 6.0 s stop, so a pause that ends later than the guard (about 10 s after it began waiting) turns the older's cancellation into a `TimeoutError` or ends the newer pass early. Worst placement (a pause that begins just before the older's deadline): about 4.2 s; most placements tolerate far more. In the old design the same guards had about 7.6 s. Not changed: the guards are the doubles' hang bound, shared by every case. The `*-finished` cases wait for nothing but the approval and are not affected (their older segment is released at once).
- **L3. Two survivors, stated in section 9** (rows 5 and 7): the assertion that the older segment's own watchdog fired, and the premise lines of l4 and o1. Both document the design; neither is revealed by a pause the probe can place. Row 6 (the assignment that gives the newer segment 600 s) was expected to be a third and is not: both O1 watchdog cases kill it (section 15).
- **L4. The injected pause yields the loop** (`asyncio.sleep`); the gate's one-line log (`1.1s` of `1.0s`) shows a late timer, so a loop-blocking stall also occurred there. A blocking `time.sleep` variant of the probe was not built; the ordering argument is the same (every timer fires in deadline order after the stall), and the 600 s segments are immune to either. The source of the stall (collector pause, antivirus or disk activity, memory pressure) is not identified and this slice does not claim to remove it; it removes the case's dependence on it.
- **L5. The Architect's probe and counts were expected, not measured (section 15 holds the oracle's measurement):** the Architect ran no test, and did not compile the probe or the patched file (the patched file was read through after an in-memory apply). The two predicted log shapes (the unfixed o1 signature with a pause inside the approval) are predictions that P4 and P5 check.
- **L6. If production ever reads the deadline once per turn instead of once per segment** (the three reads at `cognitive_agent.py:5391`, `:5477`, `:5578` are the whole mechanism), the assignment between segments becomes inert: l4 then fails at the settle bound and `o1[resumed-watchdog]` at its bounded wait (rows 2 and 4), and C1 and C2 keep the three reads honest.

## 11. Verified Against Codebase (2026-11-13, reading tree `D:\ProbOS-worktrees\bf930-932-build` at `b83ed1e3`; `origin/main` `4d8c51e4`)

**Run by the Architect, read-only (ripgrep, git, `gh`, PowerShell string operations on `git show` text; nothing written but these answer files; no pytest, no build, no python script but `scripts/ad_ceiling.py`, which the consult asked for):**

```
git -C D:\ProbOS-worktrees\bf930-932-build log -1 --format='%H %s' -> b83ed1e347e1f5303b71cd21f4920a63065d59c0 "BF-932 S2 R1: ..."; git status --short | Measure-Object -> Count 0
git rev-parse HEAD:<test file> origin/main:<test file> -> 5cd050f049f65fb09c7caeba551f73a0dd8b0aa3 on both
the seven SEARCHes of section 7 (PowerShell, on `git show <ref>:<path>` with CR removed): HEAD and origin/main, each count=1, at a line start, ASCII: P1-1..P1-7; the two tracker anchors: count=1 on both refs, line start, ASCII; every REPLACE of the test file ASCII, longest line <= 110
in-memory apply of P1-1..P1-7 to the LF blob: 1818 -> 1875 lines; `_O_HEAD_START_S` 0 occurrences; `_o_config(` 2 (def and one call); `_watchdog_config(` 3 (def, l3, l4); the patched O1 read through
scripts/ad_ceiling.py (exit 0) -> CEILING AD-1359, NEXT AD-1360 (git log --all subjects AD-1359, GitHub issue titles AD-1359 over 1517 issues, prompts/ad-*.md AD-1350)
BF: git log --all subjects 961; gh issue list --state all --limit 4000 titles 961 (1517 issues); prompts/bf-*.md 941; roadmap.md 927 -> highest BF-961
Test-Path prompts/gate-f3-segment-deadlines.md -> False; git cat-file -e origin/main:prompts/gate-f3-segment-deadlines.md -> exit 128; prompts/*gate-f3* -> 0 files
the gate that failed (logs/gates/20261113T162253...-bf930-932-b83ed1e347e1-...xml, read, not rerun): 62 testcase elements of the file; l3 1.142 s, l4 1.240 s, o1 first-finished 1.198 s, first-watchdog 2.672 s, resumed-finished 1.277 s, resumed-watchdog 2.687 s, o8 2.949 s and 3.090 s
```

```
tests/test_bf887_continue_resumes_the_promoted_turn.py
  102: _SETTLE_S = 10.0 ; 104: _PROMOTION_LOG = "probos.cognitive.turn_promotion" ; 172: await asyncio.wait_for(gate.wait(), timeout=_SETTLE_S) (_Executor.run)
  251: requests_cls: type[CapabilityRequestStore] ; 279: dm_agentic=dm or DmAgenticConfig( ; 336: premise: the rig settles within {_SETTLE_S}s ({len(held)} left)
  1062: def _held_turns ; 1066: def _watchdog_config() ; 1102: test_l3 ; 1118: test_l4 ; 1199: test_g1 ; 1292: _O_DEADLINE_S = 2.5 ; 1293: _O_HEAD_START_S = 1.0
  1297: def _o_config() ; 1304: async def _until ; 1307: premise: reached within {_SETTLE_S}s ; 1311: def _hold_after ; 1324: wait_for(held.release.wait(), timeout=_SETTLE_S)
  1331: def _approve_now ; 1340: test_o1 ; 1348: rig = await make_rig(dm=_o_config()) ; 1381: await asyncio.sleep(_O_HEAD_START_S) ; 1588: test_o6 ; 1593: _ABANDON_GRACE_SECONDS 0.05 ; 1597: the CAS
  1612: deadline_seconds=0.2, unconfirmed_grace_seconds=0.3 ; 1662: def _o8_config ; 1688: test_o8 ; 1700: _ABANDON_GRACE_SECONDS 0.05
src/probos/cognitive/cognitive_agent.py
  4905: cfg = getattr(getattr(runtime, "config", None), "dm_agentic", None) ; 5391, 5477, 5578: getattr(cfg, "promoted_run_deadline_seconds", 0.0) (three occurrences)
  795-807: _coerce_promotion_budget (807: if type(raw) not in (int, float):)
src/probos/cognitive/turn_promotion.py
  506: self._deadline = float(deadline_seconds) ; 512-516: arm() ; 541: asyncio.wait({self._task}, timeout=self._deadline) ; 546-551: the BF-733 warning ; 552 and 647: self._task.cancel()
  2025, 2343, 2768: deadline_seconds: float = 0.0 ; 2055, 2541, 2807: deadline_seconds=deadline_seconds, ; 2065: supervisor.arm() ; 2095-2100: finally: ... supervisor.close()
  2634: "BF-887: a segment of promoted work item %s %s after the item moved on " ; 2689: __contains__ ; 2993: "AD-855/BF-887: work item %s is a promoted conversational turn whose "
src/probos/config_models/agentic.py   504: class DmAgenticConfig(BaseModel) ; 597-602: promoted_run_deadline_seconds ge=0.0, le=86400.0
src/probos/routers/capability_requests.py   170: decided = await store.decide( ; 328: return await store.mark_fulfilled(decided.id)
src/probos/capability_request.py   740: async def file_request( ; 981: async def decide( ; 1071: async def mark_fulfilled ; 1148: async def list_pending
src/probos/workforce.py   7794: async def list_work_items( (status, assigned_to, ... limit=50)
pyproject.toml   181: asyncio_mode = "auto" ; 190: timeout = 180 ; 196: addopts = "-n 16 --dist=loadfile" ; tests/__init__.py exists
tests/test_ad1246_long_run_promotion.py   227-238: _beats_code (a beat every 0.1 s) ; 477: promoted_run_deadline_seconds=1.0 ; 503: beats_at_report < 50 ; 505: "16 -> 26 beats over this second"
tests/test_issue1417_run_python_child_ownership.py   376-377: the comment on the 6 s ; 380: deadline_seconds=4.0
```

## Absence Verified (2026-11-13)

```
CLAIM: no test outside the six hits sets promoted_run_deadline_seconds on a config, so the sweep's rows 2 to 7 are the whole set that arms a short watchdog through the agent
RUN:   rg -n "promoted_run_deadline_seconds\s*=" tests ; rg -n "promoted_run_deadline_seconds" tests src --glob '*.py'
FOUND: 6 assignments: tests/test_ad1246_long_run_promotion.py:477 (1.0), test_bf733_promoted_run_deadline.py:1246 (an == assertion), test_bf887...:1070 (1.0), :1203 (1200.0), :1300 (_O_DEADLINE_S), :1666 (_O_DEADLINE_S). Other mentions: test_ad1270e2i_agentic_models.py:282 (a dict of defaults), test_bf825...:560 (prose), :782 (an == read), test_bf733...:1233-1282 (field checks)
POSITIVE CONTROL: the pattern finds test_ad1246...:477, which is known to hold the setting
HOLDS: yes

CLAIM: every test that arms a watchdog by calling an entry point directly passes a deadline of its own; the others arm none
RUN:   rg -n -c "run_with_promotion\(|start_resumed_run\(|start_recovered_run\(|_PromotedRunSupervisor\(|_report_holding_slot\(|_report_with_supervisor\(" tests ; rg -n -c "deadline_seconds" tests ; rg -n "deadline_seconds\s*[=:]" tests (minus promoted_run_)
FOUND: 15 test files call an entry point (ad1165, ad1227, ad1226, ad1224, ad1204, ad1248, ad1156, ad1274, ad1323, bf733, bf732, bf705, bf825, bf887, issue1417); 9 files mention deadline_seconds (ad1165, ad1246 x2, ad1274, ad1270e2i, bf733, bf825, bf887, issue1417); the nine that call an entry point and mention no deadline: ad1227, ad1226, ad1224, ad1204, ad1248, ad1156, ad1323, bf732, bf705; the default is 0.0 at turn_promotion.py:2025, :2343, :2768
POSITIVE CONTROL: the entry-point pattern finds the six files known to pass a deadline (ad1165, ad1274, bf733, bf825, bf887, issue1417)
HOLDS: yes (D3 row 13). Not checked: a test that builds a config through a dict or model_validate with the field; the field name appears in no other assignment form in tests (the second RUN)

CLAIM: nothing outside the test file names _watchdog_config, _o_config, _O_HEAD_START_S, _O_DEADLINE_S, _LONG_SEGMENT_S, _O_STOPPED_S or _watchdog_lines
RUN:   rg -n "_O_HEAD_START_S|_O_DEADLINE_S|_LONG_SEGMENT_S|_O_STOPPED_S|_watchdog_lines" tests src scripts docs --glob '!tests/test_bf887_continue_resumes_the_promoted_turn.py' ; the same with _watchdog_config|_o_config
FOUND: 0 hits (first RUN; the three names new to this slice are also free)
POSITIVE CONTROL: the first four names are found in the test file itself (_O_DEADLINE_S at :1292, :1300, :1666; _O_HEAD_START_S at :1293, :1381)
HOLDS: yes

CLAIM: DmAgenticConfig does not block or revalidate an attribute assignment
RUN:   rg -n "validate_assignment|frozen|__setattr__|model_config" src/probos/config_models/agentic.py ; rg -n "^class DmAgenticConfig|^from pydantic" src/probos/config_models/agentic.py
FOUND: 2 hits, both the word "frozen" in prose about updated_at (:632, :634); class DmAgenticConfig(BaseModel) at :504 with no model_config
POSITIVE CONTROL: rg -n "model_config|validate_assignment" src/probos/config_models finds operations.py:166 and :215 (model_config = ConfigDict(extra="forbid", frozen=True)), so the pattern works and DmAgenticConfig is not one of them
HOLDS: yes

CLAIM: no tracker line and no commit subject of this slice holds an AD- or BF- token (the anchor headings, which are existing text, are the exception)
RUN:   a regular expression \b(AD|BF)-[0-9]+ over the tracker section of part 2 and over section 5
FOUND: only the anchor heading of DECISIONS.md (AD-1346, twice: the SEARCH and the REPLACE that re-inserts it); one BF-733 in the draft DECISIONS text was found and removed
POSITIVE CONTROL: the pattern finds the anchor's AD-1346
HOLDS: yes

CLAIM: no crew name, thread id or live figure in the blocks or the probe
RUN:   a search of part 2 for the callsign string and the agent constant of the test file, and for the identifiers of the earlier logs
FOUND: 0 hits (the cases refer to AGENT and read ids from the rig)
POSITIVE CONTROL: the same search finds none in the test file's new text either; the constant itself stays in the file, where it already is
HOLDS: yes
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** #1300 (BF-835, `6fc0e6e2`): observe the state, not the clock; its first fix was measured inert in review, which is why the probe is the acceptance and premise P7 proves the tree. #1572 (BF-899): the injection probe is not committed. The sibling fix inside `tests/test_issue1417_run_python_child_ownership.py` (the comment at `:376-377`): when two canonical gates failed a clock premise the answer was a wider deadline; here the premise is a state, so the answer is to remove the clock. The earlier consult's `answer-flake.md` (Decision 3 and 4) is the design this contract builds. **External:** none consulted.
- **Blind spots handled.** (1) The failing assertion (`premise: reached within 10.0s`, `len(scripted.calls) == 2`) is a reporter of an earlier event: the contract reads the cause from the log (the BF-733 line) and asserts on it. (2) A larger constant lowers the rate and keeps the dependence: D2 row 2. (3) The 1.0 s head start existed only to space two real clocks; with the newer segment long it has no job, and it was a second source of the same exposure. (4) `_approve_now` returns before the resumed older segment has started (the listener task runs later), so the assignment that the older reads is made before the approval and the next assignment only after the older's park has been awaited. (5) A fix applied to a copy of the config would be inert (the agent reads `runtime.config.dm_agentic` once, `:4905`): l4's `(deadline 1.0s)` assertion proves the resumed segment read the assigned value, and the settle bound would fail the case otherwise. (6) A 600 s watch task left pending would outlive a failing case: `supervisor.close()` cancels it in a `finally` (`turn_promotion.py:2095-2100`), and the `scripted` fixture's teardown opens every gate before the rig's `_settle`. (7) `_coerce_promotion_budget` reads 0.0 for anything but an exact int or float: the constants are floats. (8) pytest's `-n 16 --dist=loadfile` runs this file's cases serially in one worker, so the longer waits add to one shard, not to the others. (9) The file has 62 cases; 5 change.
- **What discards a correct result** (asked separately from what makes a case fail). The correct state is reached and then (a) the older segment's watchdog stops a healthy segment before the case is done with it (the defect); (b) the doubles' 10 s guards expire in a watchdog case (L2); (c) `caplog` records only what the logger lets through (the case sets the level on the turn-promotion logger, as `c3` does). **Recorded:** L1 to L6.

## Batching

**One pull request and one broad gate, shared with the promotion-post slice (item B), after BF-930/932 and #1769 have merged** (amendment A2, section 16: this slice is built on item B's head and gated with it; bounded hold: its own pull request from `origin/main` if it has no clean review two hours after item B's delta re-review came back clean, or if a later gate or CI is red on this family).

| Point | Judgement |
|---|---|
| Files | one test file, the two trackers and the ledger pair; disjoint from #1769 and item B except the trackers (anchors in the header) |
| Order | M1, then M3 (the tracker lines land after the earlier batches' entries) |
| Revert | Separate commits: M3, then M1; nothing is stored by the change |
| Cost: Python | G1 and G2 at `-n 0` (about a minute); once, mine: the probe twice (a few minutes), the mutation rows (a handful of file runs), and `PY scripts/run_test_gate.py --label gate-f3 --receipt logs/gates/gate-f3.receipt.json` |
| Cost: config, UI | None |

**What the rest wait for.** Nothing. The discovery budget of the wave stays unspent: nothing here is a new finding; two limits (L2, L3) are recorded in this contract and may go into the next consolidated follow-up if the orchestrator wants them tracked.

## Not in this issue: for the Captain

None of this slice needs a decision, and nothing needs the vessel: it changes tests and trackers only.

1. **Nothing to deploy, migrate or configure.** No source, config key, schema or data change.
2. **No look at the vessel is needed.** The exposure was in the test suite; there is no live source of truth to check.
3. **For the orchestrator, not the Captain, after the merge:** tick GATE-F3 in #1754 by the same-length edit of its line, `- [ ] [#1667] **GATE-F3 (P3, a test-suite fragility;` to `- [x] [#1667] **GATE-F3 (P3, a test-suite fragility;` (re-derive the line in the live body first: the copy this contract used is the body of the day), and post one comment on #1754 with the probe's two tables (the pre-M1 head: 5 controls pass, 11 stalled runs fail, the two signatures; M1's head: 16 pass) and the sweep's verdicts (D3), saying that the parent stays open and that the two stated limits (L2, L3) are recorded. If a later full gate or CI turns red on this family before the slice is built, the slice moves ahead of item B and the log goes into that comment.

| Data (later) | Chooses |
|---|---|
| The family fails again with the 600 s segments in place | a cause the slice did not remove: read the log first (the doubles' guards, L2, are the first suspects), not a larger constant |
| A watchdog case fails at its bounded wait | L1: the older's 6.0 s was too small for the host; raise `_O_STOPPED_S` only with the L2 guard budget stated |

## 13. Diff Reviewer: properties to verify

1. **M1 touches one file** (`tests/test_bf887_continue_resumes_the_promoted_turn.py`); no line of `src/`, no other test, no config. The diff is +57 lines (expected: 1818 to 1875) and no case is added or removed (62 collected before and after).
2. **l4:** the first segment's deadline is `_LONG_SEGMENT_S`; `dm` is the object passed to `make_rig`; the assignment of 1.0 s comes after the premises and before `_approve`; no `pending[0]` is read before `len(pending) == 1`; `fired` is asserted to have exactly one line naming the item and `(deadline 1.0s)`; the three original assertions are unchanged.
3. **o1:** `_O_HEAD_START_S` and its sleep are gone; `older_s` follows the role (`watchdog` older: 6.0 s; every other segment: 600 s); the resumed branch asserts the first segment's state and assigns `older_s` before the first approval; the second assignment (`_LONG_SEGMENT_S`) comes after the older's park and its premises and before the second approval; the wait for the older's end is bounded by its own deadline; a watchdog case asserts exactly one line with `(deadline 6.0s)`; a finished case asserts none; `hold.task.cancelled()` and the newer-still-running premise are unchanged.
4. **No constant was raised:** `_SETTLE_S` is 10.0; `_O_DEADLINE_S` is 2.5 and is read only by `_o8_config`; `_watchdog_config`'s default is 1.0, so l3 is unchanged; o6, o8 and the guards are unchanged.
5. **The kill sets** of rows C1 to C3 are equal before and after (the oracle's table), and rows 1 to 4 are killed as section 9 says; rows 5 to 7 are survivors, stated.
6. **The probe's two JSON files** (the orchestrator's evidence): premises P1 and P7 true in every row; the unfixed file's stalled runs all failed, with the two primary signatures; the fixed file's runs all passed.
7. **Public text:** ASCII; no crew name, thread id, timestamp or live count in the blocks, the trackers or the commit messages; no `AD-` or `BF-` token in a tracker line or a subject (the anchor heading excepted); no `Closes`; the M3 body ends with `Refs #1754.`
8. **The tracker sentences** match section 1 and D2 (the 6.0 s older segment, the 600 s others, the head start gone).

## 14. Acceptance criteria

1. G1, G2 and G3 pass as stated in section 4; the probe passes on both trees as Appendix P states (17 results each); the mutation rows give section 9's results and the kill sets of C1 to C3 are equal before and after.
2. Under a pause of twice the old deadline in the first segment (after its ask is filed) and inside the approval, the old cases fail in the logged shape and the five changed cases pass; without a pause all five pass.
3. Every test that arms a real watchdog or sets a deadline of a few seconds is enumerated (the sweep, D3 and the Absence Verified block) with the segment that must not fire, its idle budget and a verdict, and `tests/test_ad1246_long_run_promotion.py:477` is stated explicitly.
4. No case lost a seam: section 6's table, and the production mutants of section 9 B.
5. The parent keeps the evidence (the tick and the comment); GATE-F3 is the only item ticked; nothing is closed; no AD or BF number moves in the ledger.
6. No source, config key or generated reference changes; the AD ledger pair is the only generated artifact.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Amendment A1 (2026-11-13): the oracle's measurements and the corrected cells

The orchestrator applied every block of section 7 by tool to a scratch tree (the oracle: item B's oracle head over the #1769 batch; every SEARCH occurred exactly once, at a line start) and ran the gates, the injection probe and the mutation rows. Where sections 4, 6, 9 and 10 say "expected" or "not measured", this section holds the measurement. The blocks of section 7 are unchanged; what changed is this contract's text: the cells of rows 3 and 6 and of C1 and C2, section 9's closing sentence, L3 and L5, and Appendix P's P3 check (four lines, below).

**Measured.** M0 (before M1): the test file collects 62 and passes 62. G1 at M1: 62 passed in 32.2 s (M1 edits cases and adds none). `tests/test_bf887_continue_resumes_the_promoted_turn.py` at M1: 69 lines added, 12 removed, LF blob `d391bbb2b0ee3b1875777b9f3d36515f733580d7` (the blob the real build equals). G2: the collect count equals M0's and both greps print what section 4 says. G3: `AD/BF ledger is current`; no AD or BF number moves.

**The injection probe** (Appendix P with the fix below; the orchestrator's scratch file, never committed; `-n 0`). On the pre-M1 head (`GF3_EXPECT=unfixed`) 17 of 17 expectations hold (143.75 s): the 5 controls pass and each of the 11 stalled runs fails in the shape L5 predicted (the l4 run at `AssertionError` with the 1.0 s BF-733 line at `len(calls) == 1`; the O1 `decide` stalls at `AssertionError`; the O1 `file_request` stalls at `TimeoutError`). On M1's head (`GF3_EXPECT=fixed`) 17 of 17 (81.91 s): the 5 controls and all 11 stalled runs pass, the watchdog cases logging `(deadline 6.0s)`. **The fix to Appendix P:** P3 read the pending list after the case's own approval, when it is empty; it now counts the asks the plan's `file_request` filed (`plan.filed`, `asks_filed`), and Appendix P is corrected in place (the four pairs of this amendment).

**Mutation rows.** A (M1's head): rows 1, 5 and 7 match their cells exactly (row 1: the file passes and the probe fails `l4-file_request1-2s` only; rows 5 and 7 survive both the file and the probe). Rows 2 and 4 are killed by the file as their cells say (the probe's control runs fail too, because the case body fails). **Corrected:** row 3 is also killed by the file's own run, at `o1[first-watchdog]` (the logged watchdog line must say `(deadline 6.0s)`); row 6 is not a survivor: both O1 watchdog cases fail at `premise: the newer segment is still running` (the newer segment's own 6.0 s watchdog stops it before the case's check). The survivors are rows 5 and 7. B (pre-M1 head `3f6fb38e` and M1's head `a332e720`): the kill sets are identical on both heads (no seam lost): C1 {g3, l4, o1[resumed-watchdog], o8[resumed]}, C2 {g3, l3, o1[first-watchdog], o8[first]}, C3 {l3, l4, both O1 watchdog cases, both o8 cases}; g3 (`test_g3_the_agent_reports_and_bounds_the_resumed_run_exactly_as_the_first`) is added to the cells of C1 and C2. These results are for a tree whose files equal the blobs above.

## 16. Amendment A2 (2026-11-13): the slice goes into item B's pull request and broad gate

The Architect's order of work for round 1 of item B's review (section 16.9 of `prompts/promotion-post-identity-reads.md`) puts this slice into item B's pull request and its single broad gate, after item B's delta re-review is clean, with a bounded hold. No block of section 7 and no case changes; the validator of Appendix P changes in one place; this section changes what the Status and Batching lines say and records the re-measurement on item B's head.

**What changes.** The two slices keep separate commits, each with its own Builder milestone, focused check, Diff Reviewer pass and local commit; the broad gate runs once over both, so item B's receipt is earned on the repaired family. This slice's contract commit and M1 are built on item B's head while item B's delta re-review runs; M3 (the trackers and the ledger pair) is built only after item B's review is clean, so that it lands on item B's final trackers (G3 at M3: `--check` first, regenerate only if it fails); the pull request and the gate's label are the batch's.

**The bounded hold.** If this slice has no clean Diff Reviewer verdict two hours after item B's delta re-review came back clean, item B is frozen and gated alone (a branch at its last commit is the gate's tree) and this slice continues in its own pull request from `origin/main`: its blocks do not depend on item B (the seven SEARCHes and the two tracker anchors hold on `origin/main` and on item B's head). If a later full gate or CI turns red on this family before the batch is gated, the slice goes first and alone, as the paragraph "Not in this issue" says. The "after the three merges" re-check of the base blobs (the header) is run on item B's head, below, and again on `origin/main` if the hold ends.

**Measured on item B's head** (the head of the branch that holds item B's contract with its amendment A2, before this slice's commits; the oracle is a scratch tree at that head).
- Every SEARCH of section 7 occurs exactly once at a line start, and the slices apply by tool: M1 `pairs: 7; failures: 0` and M3 `pairs: 2; failures: 0`; none of the nine SEARCHes starts mid-line (the mid-line report prints `0 need an anchored copy` for both slices).
- The test file is byte-equal to the base blob of the header (item B changes none of it): yes, `5cd050f049f65fb09c7caeba551f73a0dd8b0aa3` at item B's head.
- M1's LF blob of the test file on item B's head (section 15 measured `d391bbb2b0ee3b1875777b9f3d36515f733580d7` on the earlier base): `d391bbb2b0ee3b1875777b9f3d36515f733580d7`, equal: the measurement stands (69 lines added, 12 removed).
- The test file collects and passes at M1 on item B's head: 62 collected and 62 passed in 33.6 s (`-n 0 -p no:randomly`).

Nothing in sections 1 to 15 changes except the three lines above and Appendix P's validator; the mutation rows of section 15 stand when the test file's blob is the one section 15 names.

**Round 1 of this slice's own review: the validator of Appendix P.** The Diff Reviewer found that `_check` returned for an unfixed secondary row (an O1 `file_request` stall) before it checked that the stall had been entered, so such a row could count an earlier failure as evidence about a segment the probe never reached, against the sentence in "How the orchestrator knows it discriminated" that a run whose stall was never entered cannot count. The check `need(f["entered"], "P1: the stall was entered")` now stands above the return, for every unfixed stalled row (one pair; the cases, the scenarios and the expected counts do not change). Measured: an in-memory control (the validator extracted from the probe and run on synthetic facts) accepted such a row before the repair and rejects it after, and still accepts a row whose stall was entered and still rejects a run that imported another tree; the probe re-run with the repaired validator, pre-M1 head: `17 passed in 145.46 s`: the five controls pass and each of the eleven stalled runs entered its stall and fails (an `AssertionError`, or a `TimeoutError` for the file-request stalls); M1's head: `17 passed in 82.17 s`: all sixteen runs pass, each stall entered, the watchdog cases logging `(deadline 6.0s)`.

**Round 3 of this slice's own review: the PROGRESS entry of P3-1 (amendment A3).** The Diff Reviewer found two statements in the entry that the evidence does not bear (the M3 delta; P3, ordinary reach, both introduced by the entry). (1) Its Base bullet put each old case's failure at the 10 s settle bound. The probe's rows on the pre-M1 head (section 15) show three different failures (the l4 run at an `AssertionError` with `len(calls) == 1`, the O1 `decide` stalls at an `AssertionError` and the O1 `file_request` stalls at a `TimeoutError`), so the bullet now states none and points at sections 15 and 16. (2) Its Change bullet said that the probe's result is recorded on #1754, a comment that the orchestrator posts after the merge (the section "Not in this issue: for the Captain", item 3); it now says that the result is in sections 15 and 16 of this contract. A3 changes those two lines of the P3-1 block and the header line, and nothing else of sections 1 to 15: no other block of section 7, no case, no test blob and no expected count changes. M3's two tracker blobs and the ledger pair are re-derived from the corrected block.
