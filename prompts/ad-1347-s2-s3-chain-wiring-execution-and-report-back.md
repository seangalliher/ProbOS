# AD-1347 S2 and S3: the chain's agent-work tags, and the Ship's Computer runs, parks, resumes and reports agent-created work (#1627 slices 2 and 3; the issue closes after the Captain's live acceptance)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23 (Amendment A1: the repair of review round 1)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23 (Amendment A2: the repair of review round 2)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23 (Amendment A2b: the scanner's CommonMark differential)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23 (Amendment A2c: a list item's fence ends left of the item's column)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23 (Amendment A2d: the repair of review round 3)

**Status:** build-ready after wave 2 (BF-917 #1625, BF-915 #1623) merges. Slices 2 and 3 of 4 of #1627, built as one batch (the Architect's queue ruling, comment `IC_kwDORgp-xs8AAAABer-scw`). **S3 completes AD-1347's build; #1627 closes after the Captain's live acceptance (A1).** **Tier HIGH:** crew create governed work through the chain; colleagues run it with tools; there is a Captain approval path. **AD number:** AD-1347; this batch allocates nothing (the orchestrator runs `scripts/ad_ceiling.py`). **Base:** `origin/main` `6b950acf` (S1 and S4 merged).

**Wave 2:** this contract needs nothing from wave 2 and edits none of its files: `skill_framework.py`, `acm.py`, `crew_enrollment.py`, `config/ontology/skills.yaml`, the doctor checks, `role_template_audit.py`, `storage_declarations.py` and its four test files. Every code SEARCH anchors on text. Each tracker SEARCH anchors on a line that wave 2's entries do not change (§8).

**Tests:**
- M1: `tests/test_ad1347_s2_chain_tags.py`, 17 functions after A2b (C1 has 11 cases, C15 6 and C17 74 after A2d; A1's C14 to C16 and its C1 and C5 changes are applied in M2's §7.30, A2's C1, C15 and C17 changes in §7.40).
- M2: `tests/test_ad1347_s3_execution.py`, 24 functions after A2 (X17 has 2 cases); `tests/test_ad1347_s3_wiring.py`, 1 function (a real boot); A1: `ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts` (3 vitest cases) over the shared fixture `ui/e2e/fixtures/ad1347-agent-work-approvals.json`; A2: `ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts` (2 vitest cases) over the shared rows `ui/e2e/fixtures/ad1347-action-payload-rows.json`, and `ui/src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx` (1).
- Updated pins:
  - `tests/fixtures/ad1343_seam_registry.py`: one `AGENTIC_RUN_OWNERS` row and the `agent_work` `SEAM_INDEX` text;
  - `tests/test_ad1156_plan_execute_mode.py`: the `_NEVER_RAN_REFUSALS` set;
  - `tests/test_issue1419_failed_start_rollback.py`: one stopped component;
  - `tests/test_ad1347_s1_agent_work.py`: two docstring sentences;
  - `tests/test_bf237_pipeline_post_budget.py` and `tests/test_bf238_post_budget_telemetry.py`: the extractor stub in each takes the two new keywords (§7.3a, §7.3b; M1);
  - `tests/test_ad1155_loop_until_done.py`: the pinned tail of `WorkItemAgenticExecutor.run`'s signature gains `confinement` (§7.8a; M2).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks here are LF; match and write with each file's own endings. New files are written LF.

**Mechanical repairs by the orchestrator (2026-10-23; eight, found by applying the contract by tool on `6b950acf` and `ba20e949`, running its tests and its mutation table, and building M1; no decision changed, and the production code needed none).** (1) `tests/test_ad1347_s3_execution.py` imported `AgentWorkConfig` from `probos.agent_work`, which does not export it (S1 defines it in `probos.config`, and S1's own tests import it there): the import moves. (2) C9's first case used the thread id `"bad thread"`, which S1's `AgentWorkOrigin` accepts (it refuses only a non-str, an id over 128 characters, an id with surrounding whitespace and an id that does not encode as UTF-8), so the tag was filed: the case is `" t1"`, an id with surrounding whitespace. (3) X3's `restricted_before_run` case issued its restriction at `ToolPermission.READ`, which restricts nothing at read level (S1's tests restrict with `ToolPermission.NONE`): it is `NONE`. (4) W3's boot config left the Ward Room off, and finalize wires AD-855's driver only inside `if runtime.ward_room:`, so the premise assertion failed: the test now builds its config through a local `_config` that sets `ward_room.enabled = True`, the change §7.21's note had told the Builder to make. After the four, all 41 test cases pass on the contract applied by tool. (5) Found by the campaign: row R11 (`if outcome == OUTCOME_EXPIRED:` to `if False:`) survived, because X5 asserted only that the notice contains "expired", and the fallback text ("ended as expired without a result") contains it too: X5 now asserts the expired wording itself. (Row SD1's killer is `tests/test_issue1419_failed_start_rollback.py`: its campaign command names that file as well.) The mutation table has 53 rows; the heading said 44. (6) Found by the M1 Builder: two existing test stubs of the extractor, `_fake_extract` in `tests/test_bf237_pipeline_post_budget.py` and in `tests/test_bf238_post_budget_telemetry.py`, have the fixed signature `(agent, text, *, post_budget=None)`, so the pipeline's new `thread_id` and `post_id` keywords raised `TypeError` in four bf237 tests (bf238's stub fails the same way): §7.3a and §7.3b give each stub the two keywords. §5's row and AV5's claim that no test fakes the extractor's kwargs were wrong (AV5 searched only for `def extract_and_execute_actions`) and are corrected; M1's focused command now names the bf238 test. (7) Found by the M2 Builder's focused command: `tests/test_ad1155_loop_until_done.py::test_work_item_agentic_executor_run_signature_is_unchanged` pins not only the 21-name prefix (`:508`, which §5 and §6 cited) but also the five names after it (`:531`) and the whole tail after the 26th name (`list(params)[26:] == [...]`, `:538`), and §7.8 appends `confinement` after `admitted_turn`, so the tail pin saw one extra name and the case failed; §5's row and §6's list called the test unaffected after reading only the prefix: §7.8a adds `"confinement"` to the pinned tail, and both lists and AV now say so. The change is test-only and the production code is the contract's own. (8) Found when Amendment A1 was applied by tool: pair A1-30 replaced the heading line of §12 with its own additions, so §12's absence table sat under `### A1 additions` with no §12 heading: the heading is restored after the additions (no decision, text or count changed). **Re-verified on `origin/main` `ba20e949` (wave 2 merged):** all 38 code pairs and both tracker pairs apply, each SEARCH exactly once; the 41 test cases pass on the contract applied by tool; the table's rows are run on that tree and recorded in §17. The phantom precheck lists 21 candidates on the base tree `6b950acf` and 8 on the tree with this contract applied, each explained: the 13 `kwarg_mismatch` (base tree only) are the `thread_id` and `post_id` parameters this contract adds to the extractor; 5 `method_phantom` (`restrict_to_plan_mode` and `confine_calls` exist on `DispatchToolExecutor`, where the precheck typed `executor` as `WorkItemAgenticExecutor`; `mark_fulfilled` exists on the capability-request store, where it typed `store` as `WorkItemStore`); 1 `field_phantom` (`origin.id` is a Ward Room thread's id, where the precheck typed `origin` as `AgentWorkOrigin`); and two stdlib classes (`AssertionError`, `SimpleNamespace`). **Re-verified after Amendment A1 on `origin/main` `ba20e949`:** all 88 code pairs (M1 8, M2 30, A1's §7.22 to §7.31 50) and both tracker pairs apply, each SEARCH exactly once (the slices, cut at `### 7.1`, `### 7.7`, `### 7.22` and `## 8. Tracking`, hold 88 of the contract's 88 SEARCH labels in that span); the 59 Python test cases pass on the contract applied by tool, and so do the 3 new vitest cases and the 682 existing vitest cases of the approval UI (`src/store`, `src/components/capability`, `src/components/approvals`, the profile and bridge approval tests); the phantom precheck lists 12 candidates on the applied tree, each a false positive: the 8 explained above plus `CapabilityRequestCard.tsx` (a file name in prose), `ContextVar` (the standard library's `contextvars.ContextVar`, which `_STRICT_APPROVAL_DISPATCH` already uses) and `WorkItemStore.list_pending` twice (the precheck typed `store` as `WorkItemStore`; `list_pending` is a method of the capability-request store, `capability_request.py:1140`).

**Amendment A1 (2026-10-23): the repair of review round 1 (`gpt-6.1-sol`, NOT READY, 14 findings). Not a mechanical repair; no decision D1 to D8 is reversed.** All code is in new sections §7.22 to §7.31 at the end of M2, whose SEARCH blocks are the built text, so M1's commit is unchanged and the delta is one place. Repaired: F1 (both fulfilment predicates, Python `can_fulfil_request` and the HXI's `canFulfil`, accept exactly the agent-work call bound to its own item; a shared fixture is asserted equal to the real route output and fed to the real decoder), F2 (a start that arrives during a run is made when that run ends), F3 (a confinement's admission is carried past AD-1154's inbox for that one call; credential entry stays refused; an item AD-1324 parked itself stays parked), F4 (done only when the run completed with an answer; any other stop fails with its reason), F5 (a request's eligibility is asked again before parking), F6, F7 and F11 (one linear scanner: any letter case, every marker stripped, fenced, quoted and nested tags never acted on), F8 (declines reach every watcher), F10 (a fault on one tag is acknowledged and the reply goes on), F12 (off neither imports nor calls the tag module), F13 (the notice states the TTL exactly), F14 (X3 asserts the executor is not entered before the run; X12 uses the real router), and F15, found while repairing F3 (the gate never records a browser confirmation token, as AD-1154 does not). F9: the decline acknowledgement no longer says "was told" when the post failed; a failed post still consumes its claimed notice (register R8: needs a release operation on the notice table, a store contract change). Tests: 41 cases became 59; rows: 53 became 76 Python rows, plus 4 TypeScript rows run by hand (§10). Round 2 reviews the whole candidate: the predicate, the HXI decoder, `_park_or_admit` and the terminal status mapping are shared contracts.

**Amendments A2, A2b and A2c (2026-10-23): the repair of review round 2 (`gpt-6.1-sol`, NOT READY, F16 to F21) and of the scanner's CommonMark differential. Not mechanical repairs; no decision D1 to D8 is reversed.** A2 (F16 to F21 and the standing-approval control) is in §7.32 to §7.41; A2b and A2c edit only the REPLACE halves of §7.32's first four pairs and §7.40's second and third, with no new pair, so M1's commit and the code pair count (107) stand. A2b: the orchestrator ran the A2 scanner against markdown-it-py 4.0.0 (CommonMark preset) over generated flat documents and found 35 minimal documents where it acts on a tag that CommonMark reads as code or quotation; A2b reads indentation two ways (top level and list item) and brings indented code, fences after list markers and quotes in a list item into scope. A2c: the orchestrator's extended differential (an alphabet with list markers, headings, thematic breaks, tabs and fences on list-marker lines; 12,000 documents per seed) found that A2b's list reading had no end rule: on seed 1347, 44 non-lazy disagreements, 39 of them regressions against candidate 3 (a fence opened in a list item, then a line left of the item's content column); A2c tracks the last list item's content column and ends a fence at a non-blank line left of it. **Measured on the A2c oracle (`dd8ecb20`), seeds 1347, 2024, 7 and 31337:** non-lazy disagreements 0, 3, 3 and 1, each also acted on by candidate 3 (none a regression; 6 of the 7 are a nested item and 1 a lazy line: register R15); the only other class is lazy quote continuation (45, 44, 42 and 35 minimal documents; one of those 166 is a regression against candidate 3, which ignored it only because it toggled on any fence-like line, F16: a quote line, then a line of three backticks and `a`b`, then an indented claim); documents the scanner ignores although CommonMark reads text, the over-inert trade (register R14): 79, 69, 65 and 60, against 128 for candidate 3 on seed 1347. **Real text** (read-only, the live Ward Room: all 16,386 post and thread bodies, 144,300 variants with a claim line inserted): no non-lazy disagreement; the lazy class in 8 of the 9 bodies that hold a quote; 90 over-inert variants in 45 bodies (a claim indented four or more columns after a list item); no body holds a fence indented one column or more. **Verified by tool:** A2 (30 pairs), A2b (24) and A2c (24) each applied with every SEARCH exactly once; the 107 code pairs (M1 8, M2 30, §7.22 to §7.41 69) and both tracker pairs apply to `ba20e949`, each SEARCH once (the slices, cut at `### 7.1`, `### 7.7`, `### 7.22` and `## 8. Tracking`, hold 107 of the contract's 107 SEARCH labels in that span); **125 Python test cases pass after A2c** on the contract applied by tool (C1 11, C15 6, C17 58), and so do the 6 new vitest cases and the 685 existing vitest cases of the approval UI (A2b and A2c change no TypeScript); the HXI predicate and Python agree on 6,000 of 6,000 generated payload rows (110 disagreed on candidate 3). The phantom precheck lists 15 candidates on the applied tree, each a false positive: the 11 explained above, `splitlines` on the `str` `body` of `_fields` (the precheck typed it as the route's request model), `spec.commonmark.org` (a URL in prose, read as an attribute of `SubTaskSpec`), and `mark_fulfilled` twice more on the capability-request store (`CapabilityRequestStore.mark_fulfilled`, `capability_request.py:1065`, in the route's honest-degrade handler). **Mechanical repair 9:** the contract's R15 named two blind spots of the item tracker; the differential's residual documents show a third (a nested item is tracked at its innermost marker's column only; 6 of the 7), so §9 and §13 name all three and say how it was found; no code or test changed. Round 3 reviews the delta (`_inert_spans` and its helpers, §7.32, and the C17 rows) and the consumers of every changed name (`split_agent_work_tags` has one caller, `apply_agent_work_tags`); the tests-first, campaign and Builder results go to §17.

**Amendments A2d and A2e (2026-10-23): the repair of review round 3 (`gpt-6.1-sol`, NOT READY, F22 to F26), after the round-three brake decision (continue; comment 6372686155 on #1627). Not mechanical repairs; no decision D1 to D8 is reversed.** A2d edits only REPLACE halves (§7.32's first three pairs, §7.37's file, §7.40's third pair, §7.41's fourth) and A2e adds one C17 row and register text, with no new code pair, so the code pair count (107) stands. F22: the content column of the list item the last marker starts is CommonMark's (5.2): five or more columns of padding start the item with indented code, whose line is inert and opens no fence; F23: an empty item ends at its first blank line; F24: the quote test strips spaces and tabs only; F25: the two C17 rows get a blank line after the quote; F26: two shared payload rows (37) and the claim narrowed to the exits the rows reach, lines 221 and 234 named as non-wire exclusions. There is no new register entry R16: the item-start look-alikes are R15's third kind, with two examples added. **Decided at the A2d gate (Option A, the Architect):** a tag indented four or more columns after a marker line with five or more columns of padding is read as code (register R14, the over-inert direction); it is a regression against the round-3 candidate that cannot be separated from F22's repair, because that candidate read the padded line as text and so acted on indented code at 6 to 8 columns (130 documents). **Verified by tool:** A2d (37 pairs) and A2e (9) each applied with every SEARCH once; the 107 code pairs and 2 tracker pairs apply to `ba20e949`, each once; **141 Python test cases pass** (C1 11, C15 6, C17 74); the architecture fitness test (63) and the principles checker pass; tests-first on `9319b37d`'s source: **11 failed, 130 passed**, exactly the Architect's ten C17 rows plus the new R14 row; the campaign table's 141 Line cells (130 Python, 11 TypeScript) each resolve once on the applied tree; the C17 CommonMark audit (`probe-s23-c17-audit.py`) over the 74 rows finds exactly the five `out_of_scope_` disagreements and none else (on `9319b37d` it finds F25's two rows besides the three out-of-scope ones); the F22, F23 and F24 enumerations against `9319b37d` (`probe-s23-r3-findings.py`; 1,620, 900 and 25 documents): acting on code 72, 9 and 0 -> 0, 0 and 0, dropping a plain tag 172, 123 and 25 -> 172, 42 and 0, no regression; the four-seed differential against `9319b37d` (`probe-s23-scanner-diff3.py`, 12,000 documents per seed, seeds 1347, 2024, 7 and 31337, an alphabet that adds tabs, padding 0 to 8, bare markers with blank lines and U+00A0, U+2003 and U+3000 before `>`, markers and fences): non-lazy disagreements 0, 1, 1 and 0 documents (two R15 shapes whose last line is a U+00A0 or U+2003 line that `9319b37d` ignored by accident), lazy 64, 65, 72 and 71 (17 to 20 per seed are new, all a quote line followed by a Unicode-whitespace line and `>`: R13, with its C17 row), plain tags dropped 121, 117, 130 and 114 (20 or 21 per seed are the R14 shape above); the real Ward Room (16,386 bodies, read-only) gives the same result as for `9319b37d`, and **none of the shapes of F22 to F24 occurs in it: no body holds a wide-padded marker, a bare marker line, Unicode whitespace before `>`, a fence after a list marker or an indented fence**. The phantom precheck lists the same 15 false positives as after A2c. Round 4 reviews the delta only (`git diff 9319b37d <head>`: `_item_columns`, `_inert_spans` and the module docstring, the C17 rows, the two shared rows with `_REFUSALS` and X22's docstring, and this text); the tests-first, campaign and Builder results go to §17.

**Amendment A2f (2026-10-23): the repair of review round 4 (`gpt-6.1-sol`, NOT READY, F27 and F26's remainder), after the Architect's second round-three-brake decision (continue, one round; F24 moved to the follow-up as register R14's shape). Not a mechanical repair; no decision D1 to D8 is reversed.** A2f edits only REPLACE halves (§7.32's quote test and two docstrings, §7.40's three C17 rows, §7.41's `_REFUSALS` comment and X22's docstring, the two tracker pairs) and prose, with no new pair, so the code pair count (107) stands and C17 keeps 74 rows. F27 (P2, a regression of A2d): A2d's F24 repair, a quote test that strips spaces and tabs only, made the scanner act on a line of U+00A0, U+2003 or U+3000 and `>` straight after a quote line, or as the last line of `- - x` / `  ~~~` / `~~~`, where candidate 4 and CommonMark are both inert (17 to 21 documents per seed of the differential; 0 of 16,386 Ward Room bodies). A2f restores candidate 4's test, `rest.lstrip().startswith(">")`. It reads as a quote every line candidate 5 reads as one, so it can only make a line inert. F24 returns as the over-inert shape it was (register R14). F26: the shared rows end on 11 of `validate_action_payload`'s 13 exits; a non-string params key is unreachable from JSON, and a non-finite number (`1e400`) reaches `_canonical_json`'s refusal from JSON text but is excluded under register R12. **Verified by tool (the orchestrator, on the oracle `28626e2b` that applies the contract to `ba20e949`):** the 22 pairs apply with every SEARCH once, and the 107 code pairs and 2 tracker pairs apply to `ba20e949`, each once; **141 Python test cases pass** (C1 11, C15 6, C17 74); the architecture fitness test (63) and the principles checker pass; tests-first on `478180b8`'s source: **3 failed, 138 passed**, exactly the three relabelled C17 rows, and on `9319b37d`'s source **8 failed, 133 passed** (the F22 and F23 rows and the R14 row; the three F24 rows now agree with it); the C17 CommonMark audit (`probe-s23-c17-audit.py`) finds 74 rows and six disagreements, all `out_of_scope_`; the four-seed differential of the oracle (`probe-s23-scanner-diff3.py`, seeds 1347, 2024, 7 and 31337, 12,000 documents each) against `9319b37d`: non-lazy and lazy EXTRA regressions 0 and 0, MISSING regressions 20, 20, 21 and 21 (R14's wide-padded shape); against `478180b8`: EXTRA regressions 0 and 0, MISSING 15, 20, 16 and 15 documents, each holding a line of a non-ASCII blank and `>` (F24's shape: 66 of 66); the F22, F23 and F24 enumerations (`probe-s23-r3-findings.py`; 1,620, 900 and 25 documents): acting on code 0, 0 and 0, dropping a plain tag 172, 42 and 25 (the F23 42 are candidate 3's own, R14); the real Ward Room (16,386 bodies, read-only) gives the same result as for `9319b37d`. **Mechanical repair by the orchestrator (found by the campaign dry run; no decision changed):** the Line cells of N16 and N75 carry the trailing comment A2f-5 puts on the quote test, so each resolves once; the dry run then resolves all 141 rows. Round 5 reviews the delta only (`git diff 478180b8 <head>`: the quote test and two docstrings in `agent_work_tags.py`, three C17 rows, the `_REFUSALS` comment and X22's docstring, and this text). The scanner's 70 mutation rows are rerun because their pinned file changed; the other 60 Python rows (killed on the A2e oracle `ea3b348a`, whose tests and sources they use unchanged) and the 11 TypeScript rows stand.

**Amendment A2g (2026-10-23): the record of review round 5 (`gpt-6.1-sol`, NOT READY, F28 and F29), after the Architect's third round-three-brake decision (rescope). Text only: no code, test, pair, C17 row or mutation row changes, so candidate 6 (`c7944573`) stands as reviewed.** F28: `> Archived example`, then U+00A0 and `> [SELF_TASK]`, then a complete block and a closer. CommonMark keeps all of it in the quote, because the block's lines are lazy continuations. Candidate 6 reads the U+00A0 line as a quote, removes its marker alone and acts on the block on the lazy lines (register R13). Candidate 5 (`478180b8`) read that line as an opener, so the nesting rule suppressed the block. With a plain `>` the same document is acted on by candidates 4, 5 and 6 alike, so candidate 5 was inert there only because of the Unicode blank. F29: `- `, U+00A0, `> [SELF_TASK]` is list-item paragraph text in CommonMark and is not acted on here: F24's shape after a list item marker (the quote test has always run after the markers; register R14). Candidate 6 acts on no document where candidate 4 (`9319b37d`) is inert: the orchestrator's nested-block family (`probe-s23-r5-family.py`, 960 documents) and four seeds of 12,000. The two earlier candidates disagree with each other on exactly the F27, F28 and F29 documents, so no quote predicate is free of differences against both. §14 property 3 now states how a scanner difference on such a document is judged (the ASCII twin). Register entries: F28 joins R13 and F29 joins R14, both P3 with reach 0 of 16,386 Ward Room bodies. Considered, deferred: an inert opener that keeps its block's nesting (it swallows an agent's own block after a quoted opener, a new over-inert class), acting only where both quote readings act (a rewrite of `split_agent_work_tags`), and lazy continuation (reverses R13); each needs container parsing. **Verified by tool (the orchestrator):** each A2g SEARCH occurs once in `c7944573`'s contract, every other file's blob equals `c7944573`'s, and the mutation dry run resolves all 141 rows. A2g changes no source, so no review round runs.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| Ward Room replies (threads and Ward Room DM channels) reach the proactive action extractor | present | `ward_room_pipeline.py:288-296` calls `extract_and_execute_actions`; `cognitive_agent.py:7284-7314` posts every Ward Room response through `process_and_post` with `thread_id`, `post_id` |
| The extractor knows no thread | present | `proactive.py:3010-3014` (signature), `:2859-2865` (public wrapper), `:1474` (proactive caller) |
| Existing tags are rank-gated, Lieutenant and above for work-starting actions | present | `proactive.py:3021-3024`; `[ASSIGN]` `:3675-3715`; `[CREW]` `:3717-3769` |
| BF-203's catch-all strips any remaining `[UPPERCASE ...]` opener but not a closer | present | `proactive.py:3807-3813` |
| The chain teaches tags through the compose step's system prompt | present | `cognitive/sub_tasks/compose.py:657-660` (one builder call for every mode), `:585-589` |
| The Captain's one-to-one chat runs its own 24-step pipeline and does not call the extractor | present | `cognitive/dm/reply_pipeline.py:484-509`, `:397-437` (plan-mode tables), `:1240-1316` (DMs and notebooks only) |
| A claimed request is not executed by anything | present | `workforce.py:11403` (`_publish_assignment` skips the dispatcher when `agent_pull`); `tools/work_item_pull_tool.py:314-324` ("owned=True confirms ... ownership ... not execution"); Absence AV1 |
| A claimed `task` is `scheduled`, which the task type cannot leave by `transition_work_item`; the booking moves it | present | `workforce.py:11316-11318` (status `scheduled`), `:181-200` (task transitions), `:11568-11594` (`start_booking` sets `in_progress`) |
| The AD-839 dispatch path frames a work item as from the Captain and runs the full offer | present | `cognitive_agent.py:2148-2194`, `:2405-2416` |
| A read-only allowlist enforced at the call, before any parking | present | `agentic_dispatch.py:750-761`, `:3451-3453`; `cognitive/agent_mode.py:68-83` |
| AD-1154 files `action` requests for the browser only; an ordinary approved action has no fulfiller and emits no FULFILLED | present | `agentic_dispatch.py:225`, `:1074-1249`; `routers/capability_requests.py:248-257`, `:486-499` |
| AD-855 parks and resumes, and denial cancels; the denial reason is written after the cancel | present | `cognitive/capability_gap_driver.py:135-188`, `:291-340` (resume through the router or a promoted turn), `:383-413` |
| Every new agentic run is refused for a stopped agent at the run entry | present | `agentic_dispatch.py:2622-2623`; `agent_stop.py:602-611` |
| AD-1343 S2 (ending a running turn) is not built | absent | `agent_stop.py:91-98` (`does_not_end`); Absence AV2 |

## 1. Problem

S1 can create agent work, but nothing in the chain calls it, and nothing runs, parks, resumes or reports an item once it exists. The crew still ask the Captain for reads (#1627's live evidence, 2026-10-22).

## 2. Solution overview

- **M1 (S2):**
  - One parser module reads four tags from any chain reply that reaches the action extractor, and acts on them for Lieutenant rank and above.
  - The Ward Room pipeline passes the thread and post the reply answers.
  - The compose step teaches the tags only while the service exists.
  - Each tag is acknowledged in the agent's own reply.
- **M2 (S3):**
  - A Ship's Computer runner announces each request to its eligible members, and claims through the tool sink.
  - It runs each item in its assignee's agentic loop under a per-call confinement: read-only tools run, and every other call is filed for the Captain's approval.
  - It parks the item on that request (AD-855), resumes it on approval and consumes each approval once. A denial ends the item with the Captain's reason.
  - It returns an item whose claimant may not run it to the board, unclaimed.
  - It reports the result, a decline, an expiry or a denial once per requester and watcher, in the origin thread.

## 3. Decisions

**D1 (parser home and callers).** New core module `probos/agent_work_tags.py`, called from `ProactiveCognitiveLoop._extract_and_execute_actions` only, just before BF-203's catch-all.
- Each tag has a closed form, so it is fully stripped before that catch-all runs.
- Both chain paths reach the extractor: a proactive thought directly, and every Ward Room reply through the pipeline.
- The extractor and its public wrapper gain two keyword arguments, `thread_id` and `post_id`, defaulting to "", which the pipeline passes.
- The origin channel is `ward_room` when a thread is known and `proactive` otherwise. The value `dm` in `ORIGIN_CHANNELS` stays reserved for the Captain's one-to-one chat, which is not wired (register R5).
- Ranked:
  - **A** (chosen): as above.
  - **B** a step in each caller.
  - **C** in `ward_room_router`.
  - **D** also the `DmReplyPipeline` (rejected; see the decisions summary).

**D2 (grammar, rank and acknowledgement).** The grammar is in the module docstring (§7.1).
- Rank: Lieutenant and above, as AD-654d's `[ASSIGN]` and AD-868's `[CREW]`. An ensign's tags are stripped and nothing is done.
- At most 3 tags are acted on per reply.
- `Assignee: @callsign` resolves through `CallsignRegistry.resolve`. An unresolved callsign is passed as written, and the service refuses it (`assignee_unknown`).
- A `ValueError` from `AgentWorkOrigin` is a refused tag, as S1 asked (S1 status, F2/F3).
- The acknowledgement is a parenthesised line, `(Ship's Computer: ...)`, appended to the agent's own reply text. It has no brackets, so BF-203 leaves it alone, and it starts no routing of its own.
- Disclosed: if BF-237 suppresses the main post because a `[REPLY]` was posted, the acknowledgement is not posted. The item exists either way and its report names it.
- Reading (A1: F6, F7, F11; A2: F16, F17): tag names are read in any letter case; every marker, closers included, is removed from the posted text. A marker in an inert region is an example or a quotation: it is removed alone, never acted on, and is no part of any block. The inert regions follow CommonMark 0.31.2, with the differences §9 names: a code fence opens on a run of three or more backticks or tildes (after backticks, no other backtick on the line), also after list item markers, and closes on a later line without a marker holding only a run of the same character at least as long, or runs to the end of the text; A2b: the scanner does not parse list items, so indentation is read two ways and a line is inert when either reading makes it so (the top-level reading is CommonMark's: a fence line starts within three columns, and a line indented four or more columns that does not continue a paragraph is indented code; the list reading opens a fence at any column and closes it only within three columns of its opener; A2c: it tracks the last list item's content column, a fence opened in an item ends at a non-blank line left of that column, which is then read afresh, and a tracked fence closes within three columns of the item's column; A2d: the column is CommonMark's for the line's last marker (§5.2: the marker plus one to four columns of padding, or the marker plus one when the item starts blank or with five or more columns of padding, whose first line's rest is then indented code and opens no fence), and an item with no content yet ends at a blank line); a line whose first character other than whitespace (A2f: any whitespace, which errs toward inert), after any list item markers, is `>`; and each inline code span within one line (a run of backticks to the next run of exactly as many). A line ends at LF, CRLF or CR, and a marker lies within one line. A block holds every block opened inside it and closes only on its own closer once those are closed; a block that holds any other marker is removed whole and not acted on; an unclosed block's opener and the markers after it are removed alone. One pass reads the lines and the markers, each marker at most 160 characters to its bracket, so the parse is linear. C17's rows are the grammar. The grammar the compose step teaches is unchanged.
- A fault while acting on one tag (A1, F10) is logged and acknowledged ("could not be confirmed ... check the board"), never retried, and the rest of the reply and its other tags go on.

**D3 (how an item runs).** `AgentWorkRunner` in `probos/agent_work_runner.py`, built in finalize only while `runtime.agent_work` is the real service. One listener on the work store's events:
- a created self-task or chief assignment starts a run;
- a created request is announced;
- a claimed request starts a run;
- an item reaching done, failed or cancelled has its live bookings closed and its notices delivered.

A claim through the chain also starts the run directly, and the runner holds each item to one run at a time. `recover` restarts every assigned, unfinished, unparked item at start. A start that arrives while the item runs (BF-878 resuming an approval that settled before the run parked, or a duplicate event) is kept and made when that run ends; the next run re-reads the item, so a finished or parked item does nothing (A1, F2). A stopped runner starts and keeps nothing; the next start's `recover` runs what is left.

Each run calls `WorkItemAgenticExecutor.run` without `admitted_turn`, so the run entry refuses a stopped agent at `agentic_run`. The task text frames the work as a colleague's request, not the Captain's.

Before a request runs, `AgentWorkService.execution_allowed` asks the claim gate's question again (S1's hand-on, A3).
- If the claimant may not run it, the request is unassigned: its booking is cancelled and its status is open again.
- After the run the question is asked once more. A claimant stopped mid-run, or one that lost the tool, also releases the request, because AD-1343 S2 is not built (blind spot 7). It is asked first, before parking (A1, F5): a claimant stopped after it filed a call is released, never parked; the call it filed stays on the Captain's queue, inert, because AD-855 and the admission act only on an item parked on that request (register R9).
- A self-task or assignment whose assignee may not run it is left for its TTL.

How a run ends (A1: F3, F4). A run that filed a call parks on the first one. A run the executor parked itself (AD-1324's tier-floor ask, `parked_request_id`) stays parked, its booking held. Otherwise the item is `done` only when the executor's `stopped_reason` is `complete` and it gave an answer; any other stop (`max_iterations`, `token_budget`, `error`, an empty answer, an unknown reason) marks it `failed`, for every kind, with the reason in `agent_work_result.stopped`, and the report names it (`STOP_WORDS`). A failed request is not returned to the board: its requester is told and may ask again.

Ranked:
- **A** (chosen): push through the store's events, plus a direct start and recovery.
- **B** the AD-839 `_handle_work_item_dispatch`.
- **C** pull only.

**D4 (read-only, enforced at the call).** `ToolCallConfinement(tool_ids, gate)` is a new frozen dataclass in `agentic_dispatch.py`, armed per run with `DispatchToolExecutor.confine_calls`.
- It is checked first in `_DispatchGuardMixin._invoke_reserved_body`, before plan mode and before AD-1154's browser inbox.
- A call to a tool in `AGENT_WORK_READ_TOOL_IDS` runs as usual. That set is the plan-mode read set without the three tools that leave the ship (web_search, read_page, http_fetch) and without discover_work_items.
- Any other call goes to the gate, which answers `admit`, `filed` or `refused`.
- A gate fault refuses. The two refusal texts are never-ran outcomes, classified `permission_denied` and kept out of defect evidence.
- The offer is unchanged: the agent can name any tool it holds, and only read-only calls run unasked.
- Confinement and plan mode are mutually exclusive (`tool_call_confinement_invalid`).
- A call the gate admits carries that admission past AD-1154's browser inbox for that one call (A1, F3): the context variable `_CONFINED_ADMISSION` is set around `_park_or_admit` as `_STRICT_APPROVAL_DISPATCH` is, and the inbox admits it after its step 3, so credential entry stays refused. No other guard is skipped, and `_park_or_admit`'s pinned signature is unchanged.
- The gate never records a browser confirmation token, as AD-1154's inbox never does (A1, F15: BF-682); it is stripped before filing and before matching alike.

Ranked:
- **A** (chosen): as above.
- **B** narrow the offer (the approval path would be dead).
- **C** widen the AD-1154 browser inbox.

**D5 (approval, park and resume; no new request kind).** The gate files a call through `CapabilityRequestStore.file_action_request` with:
- `tool_id` = the called tool;
- action `agent_work_call`;
- `params` = the call's parameters;
- `scope_key` = `agent_work:<item id>`;
- `work_item_id` = the item.

It checks the AD-1154 pending cap first (`approval_inbox.max_pending_per_agent`), and dedup is AD-1154's own. After the run, the item parks on the first request it filed (`block_on_request`).

**Approval** is its own fulfilment: a new branch in `_maybe_fulfil_on_approval` marks the request fulfilled. Both fulfilment predicates know this one subtype (A1, F1): `capability_request.agent_work_call` (the runner's `agent_work_approval` delegates to it) makes `can_fulfil_request` true for it, so an approved, unfulfilled one stays on the actionable queue with `can_retry_fulfilment` (BF-722's retry marks it fulfilled); the HXI's `canFulfil` mirrors it with the request's `work_item_id`, so the decoder accepts the approval's `fulfilled` response. Other action subtypes are unchanged by this predicate: an AD-1328 command escalation has its own fulfiller (`execution/command_escalation.py:312`) and is not made retryable (the HXI's refusal of its `fulfilled` response is register R10). A2 (F19): the HXI's `canFulfil` validates the payload as `validate_action_payload` does before it accepts the subtype, and one rows table, `ui/e2e/fixtures/ad1347-action-payload-rows.json`, is read by both sides (X22 through Python's predicates; `capabilityApprovals.ad1347a2.test.ts` through the HXI's queue reader and decoder). A2 (F20): a fault while marking the approval fulfilled returns the approved, retryable decision with HTTP 200, as the command branch does. A2 (F18): the card says an agent-work approval resumes its item, and no standing approval is offered (HXI) or issued (route) for one.
- FULFILLED makes AD-855 resume the item. `_resume` hands an agent-work item to `resume_agent_work`, never to the router.
- The resumed run admits exactly the approved call (same agent, item, tool and parameters) once, consuming the approval on a claim-once `agent_work_notices` row (kind `approval_use:<request id>`), so a restart cannot replay it.
- A repeat of the call is filed again.

**Denial:** AD-855 cancels the item. The report reads the Captain's reason from the denied request, because AD-855 writes `denial_reason` only after the cancel.

**D6 (reports and notices).** Every post is authored `system`, callsign "Ship's Computer"; its text names who did what.
- **Activation notice:** a thread in the request's department channel. It @mentions each eligible member not yet told (claim-once kind `activation`), excludes the requester, and sets `max_responders` to the number mentioned, so routing reaches only those members (`ward_room_router.py:497-502`; mentions are targeted first at `:1007-1012`). It gives the claim and decline syntax and the TTL.
- **Report, decline relay, expiry and denial:** one post in the origin thread. If there is no thread, or the post fails, a new thread in the department channel of the work.
- The post @mentions the requester and every watcher newly told: each terminal notice is claimed before it is sent (S1's `claim_notice`), under one delivery lock.
- **Report content:** the executor's answer (up to 1,500 characters), the tools that answered, the work item id under which AD-1224's tool records are filed, and the trace reference. It ends with the echo-chamber rule: "This is a colleague's report: check it against the record before you rely on it."
- The answer is stored on the item (`metadata["agent_work_result"]`) when it is marked done. If the TTL ended the item mid-run, the answer is written to the ended item (register R3).

**D7 (stop and census).** No new seam:
- creation is `agent_work` (S1);
- a claim is `tool` (through `ToolRegistry.check_and_invoke`);
- a run is `agentic_run` (the run entry);
- candidate questions use `standing_stop` inside the service's existing `_stopped_now`.

Pinned rows:
- `AGENTIC_RUN_OWNERS` gains `("src/probos/startup/finalize.py", "_wire_agent_work_runner")`;
- the `agent_work` `SEAM_INDEX` text names the run;
- `agent_stop.S1_SCOPE["refuses"]` names agent-created work, now that it is reachable (S1 D6 deferred this to S2).

AD-1346: a run of agent work becomes an admission subject when M3 wires `decide` at the run entry; nothing is built here.

**D8 (milestones).** Two (§6). M1 alone files items that nothing yet runs, which is why the batch is one candidate.

## 4. Wave 2 and the rest of the queue

| Item | Its files (from its issue) | Overlap with this contract |
|---|---|---|
| Wave 2 (BF-917, BF-915) | `skill_framework.py`, `acm.py`, `crew_enrollment.py`, `config/ontology/skills.yaml`, doctor checks, `role_template_audit.py`, `storage_declarations.py`, four test files | none |
| BF-914 (#1621) | `channels/*`, `api.py`, `config_models/experience.py`, `doctor/checks/channel_discord_check.py` | none |
| BF-918 (#1626) | `audio/tts/*`, `routers/avatars.py`, `avatars/rhubarb_backend.py`, `attachments/*` | none |
| AD-1341 S2 to S6 (#1569) | `knowledge/archive_store.py`, `knowledge/records_store.py`, `cognitive/oracle_service.py`, `startup/cognitive_services.py`, `__main__.py` | none |

Trackers: the `PROGRESS.md` pair anchors on the title and blank line. The `DECISIONS.md` pair anchors on the heading `### Explicit delegation models, ...`, which none of these items changes.

## 5. Consumers of every value this changes

| Value | Consumer | Accepts it because |
|---|---|---|
| `_extract_and_execute_actions(..., thread_id="", post_id="")` | `extract_and_execute_actions` (wrapper); `ProactiveCognitiveLoop` at `proactive.py:1474`; `WardRoomPostPipeline.process_and_post` | keyword-only, defaulted; two test stubs had the fixed signature `(agent, text, *, post_budget=None)` (`tests/test_bf237_pipeline_post_budget.py:25`, `tests/test_bf238_post_budget_telemetry.py:174`) and now take the two keywords (§7.3a, §7.3b); every other double is an `AsyncMock` |
| `ComposeHandler` system prompt + agent-work block | the compose LLM call | appended only when the runtime holds the real service and the mode is `ward_room_response` or `proactive_observation` |
| `S1_SCOPE["refuses"]` text | stop routes' answers; `tests/test_ad1343_seam_registry.py:63` (phrases of the named exceptions) | only the `refuses` value changes; no phrase checked there is in it |
| `AgentWorkService.crew_member`, `execution_allowed` | `AgentWorkRunner` | new public methods; the service reaches 15 methods (trigger is above 15) |
| `run(..., confinement=None)` | every existing caller | appended after `admitted_turn` (the 21-name prefix pinned by `tests/test_ad1155_loop_until_done.py:508` is unchanged; the same test's tail pin at `:538` gains the name, §7.8a); forwarded only when set (the arguments dict pinned by AD-1239 is unchanged) |
| `_NEVER_RAN_REFUSALS` (+2), `classify_tool_fault_error` tuple (+2) | AD-1189/1257 defect evidence; AD-1205 fault classification | both new texts are emitted only under a confinement |
| `metadata["capability_request_id"]` on an agent-work item | AD-855 resume and cancel (compare and set); `_approved_admission`; `_denial_reason` | written only by `block_on_request` |
| `agent_work_call` `action` requests | `_maybe_fulfil_on_approval` (new branch); HXI card (generic `action`); A1: `can_fulfil_request` and the HXI decoder (rows below) | AD-1154's exact six-key payload, scoped `agent_work:<its own work_item_id>` |
| `metadata["agent_work_result"]` | report text; the board (`to_dict`) | not a reserved key; written with the done status in one write |
| `agent_work_notices` kinds `activation`, `decline`, `approval_use:<id>` | `list_due_work_notices` filters by kind `terminal` | other kinds never appear in the terminal query |
| Ward Room posts by `system` | the router (routes like an agent post: mentions first, `max_responders` on the notice thread) | the same author as BF-200 and AD-1343 notices |
| `runtime.agent_work_runner` | `resume_agent_work`, `apply_agent_work_tags`, shutdown | `None` unless finalize built it |
| A1: `can_fulfil_request` true for the bound agent-work call | `_serialize`'s `can_retry_fulfilment` (`routers/capability_requests.py:82-84`); `list_actionable` (`capability_request.py:1118-1124`) and its callers, the actionable route (`routers/capability_requests.py:114`) and AD-1220's install dedup (`runtime.py:386`, filters `kind == "install"`); tests `test_ad1206_repair_issue.py:391-435`, `test_ad1212_1216_approval_ui.py:646,711-712`, `test_ad1299_s2a_candidate_approval.py:325,332`, `tests/fixtures/approval_ui_bridge.py:435,450,476` | only an `action` with `agent_work_call` scoped to its own item is new; every asserted row is repair, ordinary or another kind; the non-action kind check comes first, so no payload is read for other kinds |
| A1: HXI `canFulfil(kind, payload, workItemId)` | `isCapabilityRequestView` (`capabilityApprovals.ts:292`), `parseCapabilityDecision` (`:316-318`); file-private | A2 (F19): mirrors `agent_work_call` with `validate_action_payload` beneath it. Python serves only validated payloads, but the decoder must still refuse what Python refuses; the shared rows prove agreement row by row |
| A2: `isAgentWorkApproval(request)` (exported) | `CapabilityRequestCard.tsx` (the copy), `standingApprovalEligible` | true only for a validated agent-work call bound to its own item |
| A2: `standingApprovalEligible` false for an agent-work call | `CapabilityRequestCard.tsx:52` (the standing fieldset), `capabilityDecisionBody` (`capabilityApprovals.ts:165`), `parseCapabilityDecision` (`:332`, a receipt for an ineligible row is marked invalid) | narrows only; every other row unchanged |
| A2: `_maybe_issue_standing_rule` returns None for an agent-work approval | `_decide_request` (`routers/capability_requests.py:197`) only | `standing_rule` null, as for repair and AD-1328 command approvals |
| A2: the agent-work branch of `_maybe_fulfil_on_approval` returns False on a store fault | `_decide_request` (`:203-218`) | the envelope's shape is unchanged: `fulfilled` false with the approved, retryable request |
| A2: `split_agent_work_tags` | `apply_agent_work_tags` only (AV10), tests | signature unchanged; a fenced or quoted example's text now stays in the post, its markers removed |
| A1: `can_retry_fulfilment` true for an approved, unfulfilled agent-work call | `useStore.ts:441`, `CapabilityRequestCard.tsx:138-180` (Retry fulfilment), `capabilityApprovals.ts:151,207,289,357,391-396` | the retry is BF-722's route path, which marks it fulfilled again |
| A1: `_CONFINED_ADMISSION` | `_park_or_admit` only (one caller, `agentic_dispatch.py:840`) | False unless a confinement admitted the call; the tests that call `_park_or_admit` directly get the default |
| A1: `failed` with `agent_work_result.stopped` | the requester's terminal notice (`outcome_text`), the board | the result keeps its keys; `stopped` is added only for an unfinished run |

## 6. Milestones and tests

| Milestone | Opens at | Content | Commit |
|---|---|---|---|
| **M1 (S2)** | §7.1 | parser module; extractor and pipeline wiring; compose teaching; `S1_SCOPE`; M1 tests | one |
| **M2 (S3)** | §7.7 | service methods; confinement in the executor; the runner; claim and decline tags; AD-855 resume; approval fulfilment; runtime, finalize, shutdown wiring; census and pinned tests; M2 tests | one |
| Trackers | §8 | — | M2's commit or a docs commit |

**M1, `tests/test_ad1347_s2_chain_tags.py`.** Every test fails on today's tree, at import.

| # | Test | Covers |
|---|---|---|
| C1 | `test_the_parser_reads_each_tag_and_strips_every_marker` (11 cases; A1 adds fenced, quoted, nested, mixed-case and unclosed-with-marker) | grammar |
| C2 | `test_a_text_without_agent_work_tags_is_returned_unchanged` | off-path equality |
| C3 | `test_a_self_task_tag_in_a_ward_room_reply_files_under_the_agents_slot_with_the_thread_as_origin` | acceptance 6; D1 |
| C4 | `test_a_request_tag_publishes_to_a_department_and_the_chain_request_is_discoverable` | acceptance 6 (placement regression through the chain) |
| C5 | `test_while_off_the_extractor_never_enters_the_agent_work_path` | acceptance 7 |
| C6 | `test_an_ensigns_tags_are_stripped_and_nothing_is_filed` | rank |
| C7 | `test_an_unresolved_or_stopped_requester_is_refused_and_nothing_is_written` (2 cases) | identity fail-closed; acceptance 5 |
| C8 | `test_at_most_three_actions_are_taken_from_one_reply` | cap |
| C9 | `test_an_origin_the_service_cannot_record_is_a_refused_tag` (2 cases) | S1 F2 hand-on |
| C10 | `test_a_second_requester_of_the_same_request_becomes_its_watcher_through_the_chain` | dedup |
| C11 | `test_the_compose_prompt_teaches_the_tags_only_while_agent_work_is_on` (3 modes) | byte-identical golden of the prompt |
| C12 | `test_the_ward_room_pipeline_passes_its_thread_and_post_to_the_extractor` | crosses pipeline, extractor and service |
| C13 | `test_a_chief_assigns_a_member_of_its_department_by_callsign` | assignment by callsign |
| C14 | `test_an_example_a_quotation_or_a_broken_block_is_stripped_and_nothing_is_filed` | A1: F6, F7 through the extractor |
| C15 | `test_repeated_unclosed_openers_are_parsed_in_one_bounded_pass` (6 cases after A2b) | A1: F11; A2: nested levels, fence lines, quote lines and code spans under the same bound, one fence read per line; A2b: one line of 30,000 list markers |
| C16 | `test_a_work_store_fault_on_one_tag_is_acknowledged_and_the_rest_of_the_reply_is_kept` | A1: F10 |
| C17 | `test_every_inert_construct_and_block_form_is_read_as_the_grammar_says` (74 cases after A2d) | A2: F16, F17 (the grammar; §9's out-of-scope constructs are rows too); A2b: indentation read two ways, indented code, list item markers; A2d: F22 to F25 (CommonMark's list item content column, an empty item, blanks before `>`, a blank line after each quoted control) |

A1 also changes C5: the off runtime (`agent_work` None) never calls `agent_work_service` (F12).

**M2, `tests/test_ad1347_s3_execution.py`.**

| # | Test | Covers |
|---|---|---|
| X1 | `test_a_chain_request_is_announced_claimed_run_and_reported_in_its_origin_thread` | **acceptance 2** (the whole seam); acceptance 1's evidence shapes |
| X2 | `test_a_call_outside_the_read_set_parks_the_item_and_an_approval_runs_it_exactly_once` | acceptance 4 (approve, run once, deny with reason) |
| X3 | `test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed` (3 cases) | acceptance 5; blind spot 7; A1 (F14): the before-run cases assert the executor is never entered |
| X4 | `test_every_watcher_of_a_deduplicated_request_gets_the_report` | blind spot 6 |
| X5 | `test_an_expired_request_tells_each_recipient_once_across_two_overlapping_deliveries` | TTL notice; concurrency |
| X6 | `test_two_overlapping_starts_run_an_item_once` | concurrency |
| X7 | `test_a_decline_is_recorded_once_and_its_reason_reaches_the_requester` | decline |
| X8 | `test_an_ensign_or_another_department_cannot_claim_through_the_chain` | acceptance 3 (claim half) |
| X9 | `test_the_confinement_gate_decides_every_call_outside_its_set` (4 cases) and `test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome` | D4 |
| X10 | `test_a_full_approval_inbox_refuses_the_call_without_filing_it` | AD-1154 cap |
| X11 | `test_recover_runs_work_a_previous_start_left_unfinished` | restart |
| X12 | `test_an_ordinary_item_still_resumes_through_the_work_item_router` | regression; A1 (F14): the real `WorkItemRouter`, a dispatchable item admitted once, a tagless one as the negative control |
| X13 | `test_an_agent_work_approval_crosses_the_hxi_wire_fulfilled_and_retryable` | A1: F1 (the shared fixture equals the real route output; the bound subtype only) |
| X14 | `test_an_approval_that_settles_before_the_run_parks_still_runs_the_call_once` | A1: F2 |
| X15 | `test_an_admitted_confined_call_is_not_parked_again_by_the_approval_inbox` | A1: F3 (real `BrowserTool`, inbox armed) |
| X16 | `test_an_item_the_executor_parked_itself_stays_parked_with_its_booking` | A1: F3's remaining parking outcome |
| X17 | `test_a_run_that_stops_without_a_finished_answer_fails_and_says_why` (2 cases) | A1: F4 |
| X18 | `test_a_claimant_stopped_after_it_filed_a_call_returns_the_request_to_the_board` | A1: F5 |
| X19 | `test_a_decline_whose_notice_cannot_be_posted_does_not_say_it_was_told` | A1: F9's literal |
| X20 | `test_the_activation_notice_states_the_configured_ttl` | A1: F13 |
| X21 | `test_a_confirmation_token_is_never_recorded_in_an_approval` | A1: F15 |
| X22 | `test_both_fulfilment_predicates_read_every_shared_payload_row_alike` | A2: F19 (the Python oracle of the shared rows); A2d: F26 (37 rows: two reach the action refusal; the two refusals no decoded JSON payload reaches are named) |
| X23 | `test_a_fulfilment_store_fault_on_an_agent_work_approval_returns_the_approval_as_retryable` | A2: F20 |
| X24 | `test_an_agent_work_approval_issues_no_standing_rule` | A2: the standing control (register R2 closed) |

A1 also changes X7: a watcher of the deduplicated request is named in the decline (F8).

**HXI, `ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts` (A1, F1):** the real decoder accepts the pending row and the fulfilled decision, keeps the approved, unfulfilled row as retryable, and refuses a retry flag on a call bound to another item.

**HXI (A2):** `ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts` (2 cases) reads every row of `ui/e2e/fixtures/ad1347-action-payload-rows.json` through the real queue reader (`isCapabilityRequestView`, so `canFulfil`), `isAgentWorkApproval` and the real decoder (F19); `ui/src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx` (1 case) renders the card for the fixture's agent-work row and for an ordinary action (F18, the standing control).

**M2, `tests/test_ad1347_s3_wiring.py`:** W3 `test_the_runner_is_wired_only_with_the_service_and_released_at_stop`.

**Concurrency claims, each proved on real stores:**
- two overlapping deliveries tell each recipient once (X5);
- two overlapping starts run once (X6);
- a decline repeats nothing (X7);
- an approval admits one call (X2);
- an approval that settles while the run that filed it is still finishing runs the call once, after that run (X14, A1).

**Stale pins and readers hunted:**
- `tests/test_ad1343_stop_seam_inventory.py`: `AGENTIC_RUN_OWNERS` (updated); `ADMITTED_TURN_SITES`, `STOP_CHECK_SITES`, `STANDING_STOP_SITES` and `DIRECT_TOOL_INVOKES` gain nothing.
- `tests/test_ad1156_plan_execute_mode.py:538-539` (updated).
- `tests/test_issue1419_failed_start_rollback.py:1127-1176`, `:1392-1423` (updated: the new step passes its component).
- `tests/test_ad1155_loop_until_done.py:538-544` (updated, §7.8a: the pinned tail of `WorkItemAgenticExecutor.run`'s signature gains `confinement`). The same test's prefix pins at `:508` and `:531` and `tests/test_ad1142_crew_child_compaction.py:505-511` are unaffected.
- `tests/test_bf874_dm_callsign_and_fail_closed.py:564-578` (unaffected: no new strip call).
- `tests/test_bf213_proactive_action_vocabulary.py:116-126` (unaffected: the builders are not edited).
- `tests/test_bf688_chain_priority_inheritance.py:51` (no new model call in compose).
- The proactive `read_text` pins (`test_bf156`, `bf163`, `bf164`, `bf257`, `ad590`, `ad591`) assert DM strings this contract does not touch.
- `tests/test_ad1211_approval_fulfils_every_kind.py` and `tests/test_ad1154_approval_inbox.py`: ordinary actions still return `fulfilled: False` (the new branch recognises only `agent_work_call` scoped to its own item).
- A1: `tests/test_ad1154_approval_inbox.py::test_park_or_admit_keeps_its_pinned_signature` (`:1964-1979`) is unaffected: A1 adds no parameter (a context variable). The `can_fulfil_request` tests (`test_ad1206_repair_issue.py:391-435`, `test_ad1212_1216_approval_ui.py:646,711-712`, `test_ad1299_s2a_candidate_approval.py:325,332`) build no agent-work call bound to its item. The HXI tests that decode actions (`CapabilityRequestPanel.test.tsx:815-826`, `ApprovalWave.test.tsx`) use ordinary or repair payloads; AD-1206's fixture is unchanged. No test pins the runner's decline or notice wording (`rg "was told|after it was asked" tests`: only this contract's tests).
- A1, the architecture check: `AgentWorkRunner` stays at 15 direct methods (the trigger is above 15; `_record_outcome` and `ttl_words` are module functions); `_ApprovalGuardMixin` (unlisted, about 485 lines) gains 6 lines, under the 500-line trigger.
- `cognitive/dm/reply_pipeline.py` is untouched, so its 24-step guard is too.

**Focused commands:**
- M1: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1347_s2_chain_tags.py tests/test_ad1347_s1_agent_work.py tests/test_ad868_self_originated_crew.py tests/test_ad437_action_space.py tests/test_bf237_pipeline_post_budget.py tests/test_bf238_post_budget_telemetry.py tests/test_ad654a_async_dispatch.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf213_proactive_action_vocabulary.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_proactive.py -q -n 0 -p no:randomly`
- M2: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1347_s3_execution.py tests/test_ad1347_s3_wiring.py tests/test_ad1347_s1_wiring.py tests/test_ad1347_s2_chain_tags.py tests/test_ad1156_plan_execute_mode.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_seam_registry.py tests/test_ad1154_approval_inbox.py tests/test_ad1211_approval_fulfils_every_kind.py tests/test_ad1328_s2c_park_and_scope.py tests/test_ad1187_agent_work_pull.py tests/test_ad1155_loop_until_done.py tests/test_ad1142_crew_child_compaction.py tests/test_ad1239*.py -q -n 0 -p no:randomly`
- Glob `test_ad1239*`, and drop any file that does not exist.
- A1 adds to M2's command: `tests/test_ad1206_repair_issue.py tests/test_ad1212_1216_approval_ui.py tests/test_ad857_capability_request_api.py tests/test_ad1299_s2a_candidate_approval.py tests/test_distribution.py tests/test_bf887_continue_resumes_the_promoted_turn.py tests/test_ad581_hybrid_dispatch.py tests/test_proactive.py tests/test_ad437_action_space.py tests/test_ad868_self_originated_crew.py tests/test_bf237_pipeline_post_budget.py tests/test_bf238_post_budget_telemetry.py tests/test_ad654a_async_dispatch.py tests/test_ad1270b_architecture_fitness.py`.
- A1, the HXI (the broad gate does not run vitest; CI does): from `ui/`, `npx vitest run src/store/__tests__/capabilityApprovals.ad1347.test.ts src/components/capability/__tests__/ApprovalWave.test.tsx src/__tests__/CapabilityRequestPanel.test.tsx src/components/approvals/__tests__/ApprovalsInBridge.test.tsx src/store/__tests__/approvalPolling.test.ts`.

## 7. The contract

### 7.1 New file: `src/probos/agent_work_tags.py` (M1)

```python
"""AD-1347 S2 (#1627): the chain's agent-work action tags, read by one parser for every chain path.

An agent turns a need into durable work from the cognitive chain. The proactive loop's action extractor
(``ProactiveCognitiveLoop._extract_and_execute_actions``) is the one place the tags are acted on: a proactive thought
reaches it directly, and every Ward Room reply (a department or ship thread, or a Ward Room DM channel) reaches it
through ``WardRoomPostPipeline.process_and_post``, which passes the thread and the post the reply answers. The
Captain's one-to-one chat (``cognitive/dm/reply_pipeline.py``) does not read them: work found in a conversation with
the Captain is the Captain's (AD-845, AD-1165), so that path is unchanged.

Grammar (taught only while the service exists, ``agent_work_instructions``)::

    [SELF_TASK]
    Title: <one line>
    Reason: <why it is needed>
    Tool: <tool id, optional>
    [/SELF_TASK]

    [REQUEST_WORK]
    Title: <one line>
    Reason: <why it is needed>
    Tool: <tool id>
    Department: <department, optional>
    Assignee: @<callsign, optional>
    [/REQUEST_WORK]

    [CLAIM_WORK <work item id>]
    [DECLINE_WORK <work item id>] <reason> [/DECLINE_WORK]

A line without a key continues the field before it; free text before any key is the item's details. Rank: Lieutenant
and above, as AD-654d's ASSIGN and AD-868's CREW; an ensign's tags are stripped and nothing is done. At most
``MAX_TAGS_PER_REPLY`` tags are acted on in one reply. The requester is the agent's own id, which the service resolves
to its slot and refuses when it cannot (fail closed; never the Captain).

The acknowledgement is a line the Ship's Computer appends to the agent's own reply, in parentheses and without
brackets (BF-203's catch-all would strip a bracketed one). It is posted where the reply is posted, so it starts no
routing of its own and cannot loop.

Off: ``agent_work_service`` answers None, the extractor never calls this module, and nothing is taught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from probos.agent_work import (
    KIND_ASSIGNMENT,
    KIND_REQUEST,
    MAX_DESCRIPTION_CHARS,
    AgentWorkCreated,
    AgentWorkOrigin,
    AgentWorkRefusal,
    AgentWorkService,
    read_agent_work,
)
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)

ACTION_SELF_TASK: Final = "self_task"
ACTION_REQUEST: Final = "request"
ACTION_CLAIM: Final = "claim"
ACTION_DECLINE: Final = "decline"
MAX_TAGS_PER_REPLY: Final = 3
#: The compose modes whose replies reach the action extractor (D1); a DM with the Captain does not.
AGENT_WORK_COMPOSE_MODES: Final[frozenset[str]] = frozenset({"ward_room_response", "proactive_observation"})

AGENT_WORK_INSTRUCTIONS: Final = (
    "**Agent work (AD-1347)** -- when your reasoning needs a fact only a ship's tool can read, file it as work "
    "instead of asking the Captain. Place the block after your reply text; Lieutenant rank and above.\n"
    "Work for yourself, run shortly with your own read-only tools:\n"
    "[SELF_TASK]\nTitle: <one line>\nReason: <why it is needed>\nTool: <tool id, optional>\n[/SELF_TASK]\n"
    "A request to the department that holds a tool you do not hold; a chief may name a member of its own "
    "department with Assignee:\n"
    "[REQUEST_WORK]\nTitle: <one line>\nReason: <why you need it>\nTool: <tool id>\n"
    "Department: <department, optional>\nAssignee: @<callsign, optional>\n[/REQUEST_WORK]\n"
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict."
)

_BLOCK_RE: Final = re.compile(
    r"\[(SELF_TASK|REQUEST_WORK)\](.*?)\[/\1\]"
    r"|\[CLAIM_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\]"
    r"|\[DECLINE_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\](.*?)\[/DECLINE_WORK\]",
    re.DOTALL,
)
_STRAY_RE: Final = re.compile(
    r"\[/?(?:SELF_TASK|REQUEST_WORK|DECLINE_WORK)\]|\[(?:CLAIM_WORK|DECLINE_WORK)\b[^\]\n]{0,160}\]"
)
_FIELD_RE: Final = re.compile(r"^\s*(title|reason|tool|department|assignee|details)\s*:\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class AgentWorkTag:
    """One tag read from a reply: what it asks, and its fields (empty when not given)."""

    action: str
    title: str = ""
    reason: str = ""
    details: str = ""
    tool_id: str = ""
    department: str = ""
    assignee: str = ""
    work_item_id: str = ""


def _fields(body: str) -> dict[str, str]:
    """``Key: value`` lines; a line without a key continues the field before it (free text first is ``details``)."""
    found: dict[str, list[str]] = {}
    current = "details"
    for line in body.splitlines():
        match = _FIELD_RE.match(line)
        if match is not None:
            current = match.group(1).lower()
            found.setdefault(current, []).append(match.group(2).strip())
        elif line.strip():
            found.setdefault(current, []).append(line.strip())
    return {key: " ".join(part for part in parts if part).strip() for key, parts in found.items()}


def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any of them (stray markers included).

    A text with no tag and no stray marker is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    for match in _BLOCK_RE.finditer(text):
        if match.group(1) is not None:
            fields = _fields(match.group(2))
            tags.append(AgentWorkTag(
                ACTION_SELF_TASK if match.group(1) == "SELF_TASK" else ACTION_REQUEST,
                title=fields.get("title", ""), reason=fields.get("reason", ""), details=fields.get("details", ""),
                tool_id=fields.get("tool", ""), department=fields.get("department", "").lower(),
                assignee=fields.get("assignee", "").lstrip("@").strip(),
            ))
        elif match.group(3) is not None:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=match.group(3)))
        else:
            tags.append(AgentWorkTag(ACTION_DECLINE, work_item_id=match.group(4), reason=" ".join(match.group(5).split())))
    without = _STRAY_RE.sub("", _BLOCK_RE.sub("", text))
    if not tags and without == text:
        return text, ()
    return without.strip(), tuple(tags)


def agent_work_service(runtime: Any) -> AgentWorkService | None:
    """The runtime's agent-work service when it is the real one, else None (agent_work off, or a test double)."""
    service = getattr(runtime, "agent_work", None)
    return service if type(service) is AgentWorkService else None


def agent_work_instructions(runtime: Any) -> str:
    """The prompt block that teaches the tags, or "" while the service does not exist (the prompt is unchanged)."""
    return AGENT_WORK_INSTRUCTIONS if agent_work_service(runtime) is not None else ""


def _ack(text: str) -> str:
    return f"(Ship's Computer: {text}.)"


def _slot_of(runtime: Any, callsign: str) -> str | None:
    """The slot a callsign names through the callsign registry, else the text itself (the service refuses it)."""
    if not callsign:
        return None
    try:
        resolved = runtime.callsign_registry.resolve(callsign)
    except Exception:
        logger.debug("AD-1347: callsign %s did not resolve; the service judges it as written", callsign, exc_info=True)
        resolved = None
    agent_id = resolved.get("agent_id") if isinstance(resolved, dict) else None
    return agent_id if type(agent_id) is str and agent_id else callsign


def _created_ack(created: AgentWorkCreated, *, actor: str, in_thread: bool) -> str:
    item = created.work_item
    short = item.id[:8]
    record = read_agent_work(item)
    department = record.department if record is not None else "its department"
    where = "in this thread" if in_thread else f"in the {department} channel"
    if created.deduplicated:
        if record is not None and record.requester == actor:
            return _ack(f"you already have open request {short} (\"{item.title}\")")
        return _ack(f"open request {short} (\"{item.title}\") already asks this; you were added as a watcher and get its result too")
    if created.kind == KIND_REQUEST:
        tool = record.tool_id if record is not None else "the tool"
        note = "; a colleague outside your command was named, so it went to the department" if created.converted else ""
        return _ack(f"request {short} (\"{item.title}\") was sent to {department} for {tool}{note}; the result will be posted {where}")
    if created.kind == KIND_ASSIGNMENT:
        return _ack(f"work item {short} (\"{item.title}\") was assigned to {item.assigned_to}; the result will be posted {where}")
    return _ack(f"self-task {short} (\"{item.title}\") is on the board and runs shortly; the result will be posted {where}")


async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
    return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action


async def _apply_one(
    tag: AgentWorkTag, *, service: AgentWorkService, runtime: Any, actor: str,
    origin: AgentWorkOrigin | None, in_thread: bool,
) -> tuple[str, dict[str, Any]]:
    if tag.action in (ACTION_CLAIM, ACTION_DECLINE):
        return await _claim_or_decline(tag, runtime=runtime, actor=actor)
    action: dict[str, Any] = {"type": "agent_work", "action": tag.action}
    if origin is None:
        return (
            _ack("agent work was not filed: this reply's thread could not be recorded as its origin"),
            {**action, "outcome": "refused:invalid_origin"},
        )
    if tag.action == ACTION_SELF_TASK:
        result = await service.create_self_task(
            actor, title=tag.title, description=tag.details[:MAX_DESCRIPTION_CHARS], reason=tag.reason,
            origin=origin, tool_id=tag.tool_id or None,
        )
    else:
        result = await service.request_work(
            actor, title=tag.title, description=tag.details[:MAX_DESCRIPTION_CHARS], reason=tag.reason,
            origin=origin, tool_id=tag.tool_id,
            assignee=_slot_of(runtime, tag.assignee),
            department=tag.department or None,
        )
    if isinstance(result, AgentWorkRefusal):
        return _ack(f"agent work was not filed: {result.detail or result.code}"), {**action, "outcome": f"refused:{result.code}"}
    outcome = "deduplicated" if result.deduplicated else "created"
    return _created_ack(result, actor=actor, in_thread=in_thread), {**action, "outcome": outcome, "work_item_id": result.work_item.id}


async def apply_agent_work_tags(
    text: str, *, runtime: Any, actor: str, rank: Rank, thread_id: str = "", post_id: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """Strip every agent-work tag from a reply, act on each one the agent's rank allows, append the acknowledgements.

    Never raises for a tag: a refusal, an origin that cannot be recorded or an unavailable action is an
    acknowledgement line. The text is returned unchanged when the service does not exist.
    """
    service = agent_work_service(runtime)
    if service is None:
        return text, []
    cleaned, tags = split_agent_work_tags(text)
    if not tags or rank is Rank.ENSIGN:
        return cleaned, []
    try:
        origin: AgentWorkOrigin | None = AgentWorkOrigin("ward_room" if thread_id else "proactive", thread_id=thread_id, post_id=post_id)
    except ValueError:
        origin = None
    acks: list[str] = []
    actions: list[dict[str, Any]] = []
    for index, tag in enumerate(tags):
        if index >= MAX_TAGS_PER_REPLY:
            acks.append(_ack(f"only {MAX_TAGS_PER_REPLY} agent-work actions are taken from one reply; the rest were not"))
            break
        ack, action = await _apply_one(
            tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id),
        )
        acks.append(ack)
        actions.append(action)
    return "\n\n".join(part for part in (cleaned, *acks) if part), actions
```

### 7.2 `src/probos/proactive.py` (M1)

Pair 1 of 3 (the extractor's signature):

SEARCH:
```python
    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
        """AD-437: Extract structured actions from proactive response and execute them.
```
REPLACE:
```python
    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
        thread_id: str = "",
        post_id: str = "",
    ) -> tuple[str, list[dict]]:
        """AD-437: Extract structured actions from proactive response and execute them.

        AD-1347 S2: ``thread_id`` and ``post_id`` name the Ward Room thread and post a reply answers (the Ward Room
        pipeline passes them); a proactive thought has none. Only the agent-work tags read them.
```

Pair 2 of 3 (the public wrapper):

SEARCH:
```python
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a)."""
        return await self._extract_and_execute_actions(agent, text, post_budget=post_budget)
```
REPLACE:
```python
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
        thread_id: str = "",
        post_id: str = "",
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a; AD-1347 S2 adds the thread and post)."""
        return await self._extract_and_execute_actions(agent, text, post_budget=post_budget, thread_id=thread_id, post_id=post_id)
```

Pair 3 of 3 (the tags, before BF-203's catch-all):

SEARCH:
```python
        text = re.sub(handoff_pattern, '', text, flags=re.DOTALL).strip()

        # BF-203: Strip unrecognized bracket command tags that the LLM hallucinated.
```
REPLACE:
```python
        text = re.sub(handoff_pattern, '', text, flags=re.DOTALL).strip()

        # --- Agent-created work (AD-1347 S2) — Lieutenant+; only while the service exists, so off is untouched ---
        # Before BF-203: each tag has a closed form and is stripped whole here.
        from probos.agent_work_tags import agent_work_service, apply_agent_work_tags

        if agent_work_service(rt) is not None:
            text, work_actions = await apply_agent_work_tags(
                text, runtime=rt, actor=agent.id, rank=rank, thread_id=thread_id, post_id=post_id,
            )
            actions_executed.extend(work_actions)

        # BF-203: Strip unrecognized bracket command tags that the LLM hallucinated.
```

### 7.3 `src/probos/ward_room_pipeline.py` (M1)

SEARCH:
```python
        if agent and self._proactive_loop:
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
                post_budget=budget,
            )
```
REPLACE:
```python
        if agent and self._proactive_loop:
            # AD-1347 S2: the thread and post this reply answers are the origin of any work it files.
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
                post_budget=budget, thread_id=thread_id, post_id=post_id or "",
            )
```

### 7.3a `tests/test_bf237_pipeline_post_budget.py` (M1: the extractor stub takes the two new keywords)

SEARCH:
```python
    async def _fake_extract(agent, text, *, post_budget=None):
        if spend_budget and post_budget is not None:
```
REPLACE:
```python
    async def _fake_extract(agent, text, *, post_budget=None, thread_id="", post_id=""):
        if spend_budget and post_budget is not None:
```

### 7.3b `tests/test_bf238_post_budget_telemetry.py` (M1: the extractor stub takes the two new keywords)

SEARCH:
```python
    async def _fake_extract(agent, text, *, post_budget=None):
        if post_budget is not None:
```
REPLACE:
```python
    async def _fake_extract(agent, text, *, post_budget=None, thread_id="", post_id=""):
        if post_budget is not None:
```

### 7.4 `src/probos/cognitive/sub_tasks/compose.py` (M1)

SEARCH:
```python
        # Build prompts
        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )
```
REPLACE:
```python
        # Build prompts
        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )
        # AD-1347 S2: the agent-work tags, taught only while the Ship's Computer's service exists, so the prompt is
        # byte-identical while agent_work is off. Only the modes whose replies reach the action extractor (D1).
        from probos.agent_work_tags import AGENT_WORK_COMPOSE_MODES, agent_work_instructions

        if mode_key in AGENT_WORK_COMPOSE_MODES:
            agent_work_block = agent_work_instructions(self._runtime)
            if agent_work_block:
                system_prompt += f"\n\n{agent_work_block}"
```

### 7.5 `src/probos/agent_stop.py` (M1: the scope names agent-created work, now reachable)

SEARCH:
```python
        "correction was admitted just before the order ends blocked and cannot be retried; elsewhere the "
        "result is escalated unverified), browser actions and every "
        "tool call, protected effects included."
```
REPLACE:
```python
        "correction was admitted just before the order ends blocked and cannot be retried; elsewhere the "
        "result is escalated unverified), work it would create for itself or ask of a colleague and the run of "
        "agent-created work it holds (AD-1347: a request it claimed goes back to the board), browser actions and every "
        "tool call, protected effects included."
```

### 7.6 New file: `tests/test_ad1347_s2_chain_tags.py` (M1)

```python
"""AD-1347 S2 (#1627): the chain's agent-work tags, against the real service and the real chain paths.

The real ``AgentWorkService`` over a real ``WorkItemStore`` (``_ship`` from ``tests/test_ad1347_s1_agent_work.py``),
the real ``ProactiveCognitiveLoop._extract_and_execute_actions``, the real ``WardRoomPostPipeline`` over a real
``WardRoomService`` (C12) and the real ``ComposeHandler`` (C11). The runtime the loop reads is a ``MagicMock`` with the
``ProbOSRuntime`` spec carrying the real service and a real ``TrustNetwork``, as ``tests/test_ad868_self_originated_crew.py``
builds it. On today's tree every test fails at import: ``probos.agent_work_tags`` is absent.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import probos.agent_work_tags as tags_module
from probos.agent_work import read_agent_work
from probos.agent_work_tags import AGENT_WORK_INSTRUCTIONS, MAX_TAGS_PER_REPLY, AgentWorkTag, split_agent_work_tags
from probos.cognitive.sub_task import SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.compose import (
    ComposeHandler,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
)
from probos.consensus.trust import TrustNetwork
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.types import LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from tests.test_ad1347_s1_agent_work import STOP_REASON, _discovered, _section, _ship

REQUEST = (
    "[REQUEST_WORK]\nTitle: Read the EventLog window\nReason: the thread cannot show what the log holds\n"
    "Tool: event_log_query\n[/REQUEST_WORK]"
)
SELF_TASK = "[SELF_TASK]\nTitle: Check my build log\nReason: the relay drifted twice\n[/SELF_TASK]"


def _loop_runtime(service: Any, trust: TrustNetwork) -> Any:
    """The runtime the extractor reads, as tests/test_ad868_self_originated_crew.py builds it, with ``agent_work``."""
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock()
    runtime.trust_network = trust
    runtime.ward_room_router = MagicMock(spec=WardRoomRouter)
    runtime.ward_room_router.extract_endorsements.return_value = (None, [])
    runtime.config = MagicMock()
    runtime.config.communications = MagicMock()
    runtime.config.communications.dm_min_rank = "ensign"
    runtime.crew_session_service = None
    runtime.dispatcher = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "callsign"
    runtime.callsign_registry.resolve.return_value = None
    runtime.agent_work = service
    return runtime


def _loop(runtime: Any) -> ProactiveCognitiveLoop:
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(runtime)
    return loop


def _posts(path: Path, thread_id: str) -> list[tuple[str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute(
            "SELECT author_id, body FROM posts WHERE thread_id = ? ORDER BY created_at", (thread_id,),
        ).fetchall()


# C1
@pytest.mark.parametrize(("text", "expected", "cleaned"), [
    (f"Note.\n{SELF_TASK}", [AgentWorkTag("self_task", title="Check my build log", reason="the relay drifted twice")], "Note."),
    (
        "[REQUEST_WORK]\nTitle: Read it\nReason: first\nsecond line\nTool: event_log_query\nDepartment: Engineering\n"
        "Assignee: @Forge\n[/REQUEST_WORK] after",
        [AgentWorkTag("request", title="Read it", reason="first second line", tool_id="event_log_query",
                      department="engineering", assignee="Forge")],
        "after",
    ),
    ("Taking it. [CLAIM_WORK wi-123]", [AgentWorkTag("claim", work_item_id="wi-123")], "Taking it."),
    ("[DECLINE_WORK wi-9]\nOn the warp core\nall shift.\n[/DECLINE_WORK]",
     [AgentWorkTag("decline", work_item_id="wi-9", reason="On the warp core all shift.")], ""),
    ("Open [SELF_TASK]\nTitle: never closed", [], "Open \nTitle: never closed"),
    ("Stray [/REQUEST_WORK] and [CLAIM_WORK] and [DECLINE_WORK bad id!]", [], "Stray  and  and"),
])
def test_the_parser_reads_each_tag_and_strips_every_marker(text: str, expected: list[AgentWorkTag], cleaned: str) -> None:
    got, tags = split_agent_work_tags(text)
    assert list(tags) == expected
    assert got == cleaned


# C2
def test_a_text_without_agent_work_tags_is_returned_unchanged() -> None:
    text = "  Relay 4 is at 93 percent. [ENDORSE p1 UP]\n"
    assert split_agent_work_tags(text) == (text, ())


# C3
async def test_a_self_task_tag_in_a_ward_room_reply_files_under_the_agents_slot_with_the_thread_as_origin(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(
            ship.agents["forge-1"], f"Checking.\n{SELF_TASK}", thread_id="thread-9", post_id="post-9",
        )
        [item] = await ship.store.list_agent_work(False, None, 10)
        assert (item.created_by, item.assigned_to) == ("forge-1", "forge-1")
        assert item.metadata["agent_work"]["origin"] == {"channel": "ward_room", "thread_id": "thread-9", "post_id": "post-9"}
        assert "[SELF_TASK]" not in cleaned and "[/SELF_TASK]" not in cleaned
        assert cleaned.startswith("Checking.") and item.id[:8] in cleaned and "Ship's Computer" in cleaned
        assert actions[-1] == {"type": "agent_work", "action": "self_task", "outcome": "created", "work_item_id": item.id}


# C4
async def test_a_request_tag_publishes_to_a_department_and_the_chain_request_is_discoverable(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, _ = await loop._extract_and_execute_actions(ship.agents["pulaski-1"], REQUEST, thread_id="t1")
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None
        assert (record.kind, record.department, record.tool_id) == ("request", "engineering", "event_log_query")
        assert (item.created_by, item.assigned_to) == ("pulaski-1", None)
        assert await _discovered(ship, "forge-1") == [item.id]  # the placement trap (premise 6), through the chain
        assert "engineering" in cleaned and item.id[:8] in cleaned
        named = REQUEST.replace("Title: Read the EventLog window", "Title: Read the access log").replace(
            "Tool: event_log_query", "Tool: event_log_query\nDepartment: Security",
        )
        await loop._extract_and_execute_actions(ship.agents["pulaski-1"], named, thread_id="t1")
        security = [read_agent_work(i) for i in await ship.store.list_agent_work(False, None, 10) if i.id != item.id]
        assert [r.department for r in security if r is not None] == ["security"]


# C5
async def test_while_off_the_extractor_never_enters_the_agent_work_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered: list[dict[str, Any]] = []

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        entered.append(kwargs)
        raise AssertionError("the agent-work path was entered while agent_work is off")

    monkeypatch.setattr(tags_module, "apply_agent_work_tags", _spy)
    async with _ship(tmp_path) as ship:
        for service in (None, MagicMock()):  # off, and a double that is not the real service
            loop = _loop(_loop_runtime(service, TrustNetwork()))
            await loop._extract_and_execute_actions(ship.agents["forge-1"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert entered == []
        assert await ship.store.list_agent_work(False, None, 10) == []


# C6
async def test_an_ensigns_tags_are_stripped_and_nothing_is_filed(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        trust = TrustNetwork()
        trust.create_with_prior("forge-2", 1.0, 3.0)  # 0.25: an ensign
        loop = _loop(_loop_runtime(ship.service, trust))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-2"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert cleaned == "Obs." and [a for a in actions if a.get("type") == "agent_work"] == []
        assert await ship.store.list_agent_work(False, None, 10) == []


# C7
@pytest.mark.parametrize("who", ["unresolved", "stopped"])
async def test_an_unresolved_or_stopped_requester_is_refused_and_nothing_is_written(tmp_path: Path, who: str) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        if who == "unresolved":
            agent: Any = SimpleNamespace(id="ghost-1", agent_type="builder", callsign="Ghost")
        else:
            issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
            agent = ship.agents["forge-1"]
        cleaned, actions = await loop._extract_and_execute_actions(agent, SELF_TASK, thread_id="t1")
        assert "not filed" in cleaned and "CANARY" not in cleaned
        code = "requester_unresolved" if who == "unresolved" else "agent_stopped"
        assert actions[-1] == {"type": "agent_work", "action": "self_task", "outcome": f"refused:{code}"}
        assert await ship.store.list_agent_work(False, None, 10) == []
        if who == "stopped":
            assert ship.stops.refused_counts(issued.record.stop_id) == {"agent_work": 1}


# C8
async def test_at_most_three_actions_are_taken_from_one_reply(tmp_path: Path) -> None:
    async with _ship(tmp_path, section=_section(max_open_per_agent=10, max_created_per_agent_per_hour=10)) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        blocks = "\n".join(
            f"[SELF_TASK]\nTitle: Task {n}\nReason: the relay drifted\n[/SELF_TASK]" for n in ("one", "two", "three", "four")
        )
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], blocks, thread_id="t1")
        assert len(await ship.store.list_agent_work(False, None, 10)) == MAX_TAGS_PER_REPLY
        assert len([a for a in actions if a.get("type") == "agent_work"]) == MAX_TAGS_PER_REPLY
        assert f"only {MAX_TAGS_PER_REPLY} agent-work actions" in cleaned


# C9
@pytest.mark.parametrize("thread_id", [" t1", "x" * 129])
async def test_an_origin_the_service_cannot_record_is_a_refused_tag(tmp_path: Path, thread_id: str) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], SELF_TASK, thread_id=thread_id)
        assert "could not be recorded as its origin" in cleaned
        assert actions[-1]["outcome"] == "refused:invalid_origin"
        assert await ship.store.list_agent_work(False, None, 10) == []


# C10
async def test_a_second_requester_of_the_same_request_becomes_its_watcher_through_the_chain(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        await loop._extract_and_execute_actions(ship.agents["pulaski-1"], REQUEST, thread_id="t1")
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["ogawa-1"], REQUEST, thread_id="t2")
        [item] = await ship.store.list_agent_work(False, None, 10)
        assert await ship.store.list_work_watchers(item.id) == ("ogawa-1",)
        assert "watcher" in cleaned and actions[-1]["outcome"] == "deduplicated"


class _Capture:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="ok", tokens_used=1)


_BUILDERS = {
    "ward_room_response": _build_ward_room_compose_prompt,
    "proactive_observation": _build_proactive_compose_prompt,
    "dm_response": _build_dm_compose_prompt,
}


# C11
@pytest.mark.parametrize("mode", sorted(_BUILDERS))
async def test_the_compose_prompt_teaches_the_tags_only_while_agent_work_is_on(tmp_path: Path, mode: str) -> None:
    """The byte-identical golden of the prompt: off, the compose system prompt is exactly the mode's builder output."""
    context = {"_agent_type": "builder", "_callsign": "Forge", "_department": "engineering"}
    expected, _ = _BUILDERS[mode](dict(context), [], "Forge", "engineering")
    prompts: dict[str, str] = {}
    async with _ship(tmp_path) as ship:
        for label, service in (("off", None), ("on", ship.service)):
            llm = _Capture()
            handler = ComposeHandler(llm_client=llm, runtime=SimpleNamespace(agent_work=service))
            spec = SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", prompt_template=mode)
            result = await handler(spec, dict(context), [])
            assert result.success, result.error
            prompts[label] = llm.requests[0].system_prompt
    assert prompts["off"] == expected
    if mode == "dm_response":
        assert prompts["on"] == expected
    else:
        assert prompts["on"] == expected + "\n\n" + AGENT_WORK_INSTRUCTIONS
        assert "[SELF_TASK]" in prompts["on"] and "[REQUEST_WORK]" in prompts["on"]


# C12
async def test_the_ward_room_pipeline_passes_its_thread_and_post_to_the_extractor(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        wr = WardRoomService(db_path=str(tmp_path / "wr.db"))
        await wr.start()
        try:
            medical = await wr.get_channel_by_department("medical")
            thread = await wr.create_thread(medical.id, "bones-1", "Relay", "The relay drifted.", author_callsign="Bones")
            post = await wr.create_post(thread.id, "bones-1", "Twice now.", author_callsign="Bones")
            runtime = _loop_runtime(ship.service, TrustNetwork())
            runtime.ward_room = wr
            router = MagicMock(spec=WardRoomRouter)
            router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, callsign: text)
            pipeline = WardRoomPostPipeline(
                ward_room=wr, ward_room_router=router, proactive_loop=_loop(runtime), trust_network=None,
                callsign_registry=None, config=MagicMock(),
            )
            posted = await pipeline.process_and_post(
                agent=ship.agents["pulaski-1"], response_text=f"I need the log.\n{REQUEST}",
                thread_id=thread.id, event_type="ward_room_post_created", post_id=post.id,
            )
            assert posted is True
            [item] = await ship.store.list_agent_work(False, None, 10)
            assert item.metadata["agent_work"]["origin"] == {"channel": "ward_room", "thread_id": thread.id, "post_id": post.id}
            replies = [body for author, body in _posts(tmp_path / "wr.db", thread.id) if author == "pulaski-1"]
            assert len(replies) == 1 and item.id[:8] in replies[0] and "[REQUEST_WORK]" not in replies[0]
        finally:
            await wr.stop()


# C13
async def test_a_chief_assigns_a_member_of_its_department_by_callsign(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        runtime = _loop_runtime(ship.service, TrustNetwork())
        runtime.callsign_registry.resolve.return_value = {"agent_id": "forge-1"}
        assigned = REQUEST.replace("Tool: event_log_query", "Tool: event_log_query\nAssignee: @Forge")
        cleaned, actions = await _loop(runtime)._extract_and_execute_actions(ship.agents["laforge-1"], assigned, thread_id="t1")
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None and (record.kind, item.assigned_to, item.created_by) == ("assignment", "forge-1", "laforge-1")
        assert "assigned to forge-1" in cleaned and actions[-1]["outcome"] == "created"
```

### 7.7 `src/probos/agent_work.py` (M2: two public questions for the runner)

SEARCH:
```python
    def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
        """The store's claim gate (``WorkItemStore.set_agent_work_claim_gate``): may this resource claim this now?
```
REPLACE:
```python
    def crew_member(self, key: str) -> CrewMember | None:
        """S3: the live crew member ``key`` names (any identity form the facade resolves), or None (fail closed)."""
        ref = self._identities.resolve(key) if _identifier(key) else None
        return self._directory.member(ref.slot_id) if ref is not None else None

    def execution_allowed(self, item: WorkItem, slot_id: str) -> bool:
        """S3, asked before every run and again after it (A3's hand-on): may ``slot_id`` run this item now?

        Its assignee only, live and not stopped. A request: a member of its department who may use its tool, the claim
        gate's question asked again, so a claimant that lost eligibility after its claim is not run. A self-task or an
        assignment: holding the named tool when one is named. Never cached; never raises.
        """
        try:
            record = read_agent_work(item)
            if record is None or item.assigned_to != slot_id:
                return False
            member = self._directory.member(slot_id)
            if member is None or self._stopped_now(member.slot_id):
                return False
            if record.kind == KIND_REQUEST:
                return member.department == record.department and record.tool_id is not None and self._holds_tool(member, record.tool_id)
            return record.tool_id is None or self._holds_tool(member, record.tool_id)
        except Exception:
            logger.warning(
                "AD-1347: the run check for work item %s failed; it is not run by %s now",
                getattr(item, "id", "?"), slot_id, exc_info=True,
            )
            return False

    def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
        """The store's claim gate (``WorkItemStore.set_agent_work_claim_gate``): may this resource claim this now?
```

### 7.8 `src/probos/cognitive/agentic_dispatch.py` (M2: per-call confinement)

Pair 1 of 9 (the refusals and the confinement):

SEARCH:
```python
# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset(
    {_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL}
)
```
REPLACE:
```python
# AD-1347 S3 (#1627): agent-created work runs confined. Its calls to the tools in the run's set run as usual; a call to
# any other tool is put to the run's gate, which files it for the Captain's approval (an AD-1154 ``action``) or admits
# the one call an approval on record covers. Error-shaped and final, in the AD-1154 voice; never defect evidence.
CONFINED_CALL_FILED: str = (
    "That call needs the Captain's approval before it runs. It was filed for review and did not run. Do not "
    "repeat it: a repeat is folded into the same request. Finish what the read-only tools allow and report "
    "what remains open."
)
CONFINED_CALL_NOT_FILED: str = (
    "That call needs the Captain's approval before it runs, and it could not be filed for review, so it did "
    "not run. Finish what the read-only tools allow and report what remains open."
)
CONFINEMENT_ADMIT = "admit"
CONFINEMENT_FILED = "filed"
CONFINEMENT_REFUSED = "refused"

# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset(
    {_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED}
)


@dataclass(frozen=True)
class ToolCallConfinement:
    """AD-1347 S3: the calls a run makes directly (``tool_ids``) and the gate every other call is put to.

    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval) or anything else (not filed). Enforced first in the executor's invoke, before plan mode and the
    AD-1154 browser inbox, so the decision is made at the tool call, never by reading the plan.
    """

    tool_ids: frozenset[str]
    gate: Callable[[str, Any, Any], Awaitable[str]]

    def __post_init__(self) -> None:
        if (
            type(self.tool_ids) is not frozenset or not self.tool_ids
            or any(type(tool_id) is not str or not tool_id for tool_id in self.tool_ids)
            or not callable(self.gate)
        ):
            raise ValueError("tool_call_confinement_invalid")

    async def refuse_or_admit(self, agent_id: str, tool_id: Any, params: Any) -> ToolResult | None:
        """None admits the call; otherwise the refusal it gets. Fails closed: a gate that raises refuses."""
        try:
            verdict = await self.gate(agent_id, tool_id, params)
        except Exception:
            logger.warning(
                "AD-1347: the confinement gate raised for a call from agent %s; the call is refused and did not run",
                agent_id[:12], exc_info=True,
            )
            verdict = CONFINEMENT_REFUSED
        if verdict == CONFINEMENT_ADMIT:
            return None
        return ToolResult(error=CONFINED_CALL_FILED if verdict == CONFINEMENT_FILED else CONFINED_CALL_NOT_FILED)
```

Pair 2 of 9 (checked first at the call):

SEARCH:
```python
        if self._plan_mode_tool_ids is not None and tool_id not in self._plan_mode_tool_ids:
            if strict_dispatch is not None:
                strict_log("plan_mode", "plan_mode_refused")
```
REPLACE:
```python
        confinement = self._confinement
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
            if refusal is not None:
                strict_log("confinement", "confinement_refused")
                return refuse(refusal, "confinement_refused")
        if self._plan_mode_tool_ids is not None and tool_id not in self._plan_mode_tool_ids:
            if strict_dispatch is not None:
                strict_log("plan_mode", "plan_mode_refused")
```

Pair 3 of 9 (unarmed by default):

SEARCH:
```python
        self._plan_mode_tool_ids: frozenset[str] | None = None  # AD-1156: None = unarmed

    def arm_approval_inbox(
```
REPLACE:
```python
        self._plan_mode_tool_ids: frozenset[str] | None = None  # AD-1156: None = unarmed
        self._confinement: ToolCallConfinement | None = None  # AD-1347 S3: None = unarmed

    def arm_approval_inbox(
```

Pair 4 of 9 (arming):

SEARCH:
```python
    def restrict_to_plan_mode(self, tool_ids: frozenset[str]) -> None:
        """AD-1156: refuse, first in :meth:`invoke`, every call to a tool not in ``tool_ids``."""
        self._plan_mode_tool_ids = tool_ids
```
REPLACE:
```python
    def restrict_to_plan_mode(self, tool_ids: frozenset[str]) -> None:
        """AD-1156: refuse, first in :meth:`invoke`, every call to a tool not in ``tool_ids``."""
        self._plan_mode_tool_ids = tool_ids

    def confine_calls(self, confinement: ToolCallConfinement) -> None:
        """AD-1347 S3: put every call to a tool outside ``confinement.tool_ids`` to its gate, first in :meth:`invoke`."""
        self._confinement = confinement
```

Pair 5 of 9 (a policy outcome for fault observation):

SEARCH:
```python
            _BROWSER_READ_ONLY_REFUSAL, _APPROVAL_PARKED_REFUSAL_NO_ID,
            _APPROVAL_INBOX_FULL_REFUSAL, _APPROVAL_CREDENTIAL_REFUSAL,
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            "consensus_blocked", "requires_confirmation",
```
REPLACE:
```python
            _BROWSER_READ_ONLY_REFUSAL, _APPROVAL_PARKED_REFUSAL_NO_ID,
            _APPROVAL_INBOX_FULL_REFUSAL, _APPROVAL_CREDENTIAL_REFUSAL,
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,  # AD-1347 S3
            "consensus_blocked", "requires_confirmation",
```

Pair 6 of 9 (`run` gains the keyword, appended last):

SEARCH:
```python
        inner_loop_hook: Any = None,
        admitted_turn: bool = False,
    ) -> WorkItemAgenticOutcome:
```
REPLACE:
```python
        inner_loop_hook: Any = None,
        admitted_turn: bool = False,
        confinement: ToolCallConfinement | None = None,
    ) -> WorkItemAgenticOutcome:
```

Pair 7 of 9 (forwarded only when set):

SEARCH:
```python
        # AD-1322: transported unchanged; absent => the arguments are unchanged.
        if inner_loop_hook is not None:
            arguments["inner_loop_hook"] = inner_loop_hook
```
REPLACE:
```python
        # AD-1322: transported unchanged; absent => the arguments are unchanged.
        if inner_loop_hook is not None:
            arguments["inner_loop_hook"] = inner_loop_hook
        # AD-1347 S3: forwarded only when set, for the same reason.
        if confinement is not None:
            arguments["confinement"] = confinement
```

Pair 8 of 9 (`_run_reserved` gains the keyword and validates it):

SEARCH:
```python
        budget_awareness_state: AgenticBudgetAwarenessState | None = None,
        inner_loop_hook: Any = None,
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.
```
REPLACE:
```python
        budget_awareness_state: AgenticBudgetAwarenessState | None = None,
        inner_loop_hook: Any = None,
        # AD-1347 S3: agent-created work's per-call confinement. None -- every other caller -- changes nothing.
        confinement: ToolCallConfinement | None = None,
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.
```

and

SEARCH:
```python
            raise ValueError("plan_mode_tool_ids_invalid")

        department, rank = _resolve_agentic_identity(
```
REPLACE:
```python
            raise ValueError("plan_mode_tool_ids_invalid")

        # AD-1347 S3: a confinement is exact and never runs with plan mode, or the run does not start.
        if confinement is not None and (
            type(confinement) is not ToolCallConfinement or plan_mode_tool_ids is not None
        ):
            raise ValueError("tool_call_confinement_invalid")

        department, rank = _resolve_agentic_identity(
```

Pair 9 of 9 (armed after the offer is built; the offer itself is unchanged):

SEARCH:
```python
        if plan_mode_tool_ids is not None:
            tool_ids = [tool_id for tool_id in tool_ids if tool_id in plan_mode_tool_ids]
            executor.restrict_to_plan_mode(plan_mode_tool_ids)
```
REPLACE:
```python
        if plan_mode_tool_ids is not None:
            tool_ids = [tool_id for tool_id in tool_ids if tool_id in plan_mode_tool_ids]
            executor.restrict_to_plan_mode(plan_mode_tool_ids)
        # AD-1347 S3: the offer stays whole -- the agent may name any tool it holds -- and the call decides (D4).
        if confinement is not None:
            executor.confine_calls(confinement)
```

### 7.8a `tests/test_ad1155_loop_until_done.py` (M2: the executor `run` signature's pinned tail gains `confinement`)

`test_work_item_agentic_executor_run_signature_is_unchanged` pins the 21-name prefix (`:508`, unchanged), the five names after it, and the whole tail after the 26th name (`list(params)[26:] == [...]`, `:538`). §7.8 appends `confinement` after `admitted_turn`, so the tail pin gains one name, and the name is appended last, so the ordered prefix and the five names are untouched.

SEARCH:
```python
        "admitted_turn",  # AD-1343 A2: the agent's own admitted turn skips the stop entry check; not continuation policy
    ]
```
REPLACE:
```python
        "admitted_turn",  # AD-1343 A2: the agent's own admitted turn skips the stop entry check; not continuation policy
        "confinement",  # AD-1347 S3: a per-call authority bound for an owned read-only run; not continuation policy
    ]
```

### 7.9 New file: `src/probos/agent_work_runner.py` (M2)

```python
"""AD-1347 S3 (#1627): the Ship's Computer runs agent-created work and reports it where it was asked.

One runner per vessel, built in finalize only while ``runtime.agent_work`` exists. It reacts to the work store's own
events (one listener):

- a created self-task or chief assignment runs at once, in its assignee's agentic loop;
- a created department request is announced once to each eligible member, in that department's channel, with the
  claim and decline tags (a pull reaches nobody by itself; the TTL is the backstop);
- a claimed request runs in its claimant's agentic loop (AD-1187's claim; the chain's CLAIM_WORK claims through the
  same tool sink and also starts the run itself);
- an item that ends has its live bookings closed and is reported, once per recipient, to its requester and watchers.

Every run is confined (``ToolCallConfinement``): the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual and a call to
any other tool is filed as an AD-1154 ``action`` request instead of running. After such a run the item parks
``blocked`` on that request through AD-855's ``block_on_request``; the Captain's approval fulfils it, AD-855 resumes the
item through ``resume_agent_work``, and the next run makes that one call (its approval is consumed on a claim-once row).
A denial cancels the item (AD-855) and the report names the Captain's reason.

The stop: every run enters at ``WorkItemAgenticExecutor.run``, which refuses a stopped agent at ``agentic_run``. A
request whose claimant may no longer run it (stopped, moved, lost the tool) goes back to the board unclaimed, never
failed. Expiry stays the store's TTL sweep; this runner only reports it. The cognitive layer is imported inside the
functions that run work, so the approval route's import of ``agent_work_approval`` loads no agentic stack.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Final

from probos.agent_stop import AgentStopped
from probos.agent_work import (
    KIND_REQUEST,
    MAX_REASON_CHARS,
    OUTCOME_EXPIRED,
    SCAN_LIMIT,
    AgentWorkNotice,
    AgentWorkRecord,
    AgentWorkService,
    read_agent_work,
)
from probos.capability_request import action_dedup_key, validate_action_payload
from probos.events import EventType
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.workforce import AGENT_WORK_METADATA_KEY, WorkItem

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

logger = logging.getLogger(__name__)

#: The tools an agent-created work run calls directly: the plan-mode read set (``agent_mode.PLAN_MODE_TOOL_IDS``, each
#: asserted read-only there) without the three that reach off the ship (web_search, read_page, http_fetch) and without
#: discover_work_items. Every other call is filed for the Captain's approval: a new or renamed tool is filed until
#: someone decides it only reads.
AGENT_WORK_READ_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
})
APPROVAL_ACTION: Final = "agent_work_call"
APPROVAL_SCOPE_PREFIX: Final = "agent_work:"
APPROVAL_USE_PREFIX: Final = "approval_use:"
NOTICE_ACTIVATION: Final = "activation"
NOTICE_DECLINE: Final = "decline"
RESULT_METADATA_KEY: Final = "agent_work_result"
SHIP_COMPUTER_ID: Final = "system"
SHIP_COMPUTER_CALLSIGN: Final = "Ship's Computer"
RUN_SOURCE: Final = "agent_work_runner"
REPORT_MAX_CHARS: Final = 1_500
BLOCKED_REASON: Final = "waiting for the Captain's decision on a tool call outside the read-only set"
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})
_HANDLED_EVENTS: Final[frozenset[str]] = frozenset({
    EventType.WORK_ITEM_CREATED.value, EventType.WORK_ITEM_CLAIMED.value, EventType.WORK_ITEM_STATUS_CHANGED.value,
})
#: The claim tool renders its receipt through the invocation's presentation; the runner reads the board, not the text.
_PRESENTATION: Final = ToolResultPresentation(render_complete=repr)


def agent_work_approval(request: Any) -> dict[str, Any] | None:
    """The validated payload when ``request`` asks to make one tool call in one agent-created work item, else None."""
    if getattr(request, "kind", None) != "action":
        return None
    payload = validate_action_payload(getattr(request, "payload", None))
    work_item_id = getattr(request, "work_item_id", None)
    if (
        payload is None or payload["action"] != APPROVAL_ACTION
        or type(work_item_id) is not str or not work_item_id
        or payload["scope_key"] != APPROVAL_SCOPE_PREFIX + work_item_id
    ):
        return None
    return payload


def approval_payload(tool_id: Any, params: Any, work_item_id: str) -> dict[str, Any] | None:
    """The AD-1154 ``action`` payload that asks for one call, or None when the call cannot be recorded."""
    if type(tool_id) is not str or type(params) is not dict:
        return None
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": dict(params),
        "scope_key": APPROVAL_SCOPE_PREFIX + work_item_id, "session_id": None, "thread_id": "",
    })


def _provenance(item: WorkItem) -> dict[str, Any]:
    metadata = item.metadata if type(item.metadata) is dict else {}
    raw = metadata.get(AGENT_WORK_METADATA_KEY)
    return raw if type(raw) is dict else {}


def _origin_thread(item: WorkItem) -> str:
    """The Ward Room thread the work was asked in, or "" (a proactive thought, or no thread)."""
    origin = _provenance(item).get("origin")
    if type(origin) is not dict or origin.get("channel") != "ward_room":
        return ""
    thread_id = origin.get("thread_id")
    return thread_id if type(thread_id) is str else ""


def task_text(item: WorkItem, *, requester: str) -> str:
    """What the run is asked: the colleague's request, its reason and its tool, and the confinement in plain words."""
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the read-only tools you hold"
    details = f"{item.description}\n\n" if item.description and item.description != item.title else ""
    return (
        f"Agent work {item.id}: {item.title}\n\n{details}"
        f"Asked by {requester}. Reason: {reason}. Tool named: {tool}.\n\n"
        "Read-only tools run directly. A call to any other tool is filed for the Captain's approval and does not run "
        "now; this work resumes after the Captain decides. Do the reading, then answer with what you found and the "
        "tool results you relied on. Your answer is posted where the work was asked for."
    )


def outcome_text(item: WorkItem, outcome: str, *, mentions: str, denial: str = "") -> str:
    """The post that tells the requester and watchers how the work came out (the echo-chamber rule included)."""
    head = f"{mentions} Agent work {item.id[:8]} (\"{item.title}\")"
    metadata = item.metadata if type(item.metadata) is dict else {}
    result = metadata.get(RESULT_METADATA_KEY)
    if type(result) is dict and type(result.get("answer")) is str:
        tools = ", ".join(name for name in result.get("tools", ()) if type(name) is str) or "none"
        trace = result.get("trace") if type(result.get("trace")) is str else ""
        evidence = f"Evidence: tools that answered: {tools}; their records are filed under work item {item.id}"
        evidence += f", trace {trace}" if trace else ""
        status = "is done" if outcome == "done" else f"ended as {outcome}, after this answer"
        return (
            f"{head} {status}. {result.get('executor', 'A colleague')} reported:\n\n{result['answer']}\n\n"
            f"{evidence}. This is a colleague's report: check it against the record before you rely on it."
        )
    if outcome == OUTCOME_EXPIRED:
        return f"{head} expired before anyone produced a result. Ask again if it is still needed."
    if denial:
        return f"{head} was stopped: the Captain declined a step it needed. Reason: {denial}"
    if outcome == "failed":
        return f"{head} failed before it produced a result."
    return f"{head} ended as {outcome} without a result."


async def _approved_admission(requests: Any, item: WorkItem, slot_id: str) -> tuple[str, str] | None:
    """(request id, call key) of the approval this item was parked on and resumed by, or None."""
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    if type(request_id) is not str or not request_id:
        return None
    request = await requests.get(request_id)
    payload = agent_work_approval(request) if request is not None else None
    if payload is None or request.status != "fulfilled" or request.agent_id != slot_id or request.work_item_id != item.id:
        return None
    return request_id, action_dedup_key(agent_id=slot_id, payload=payload, work_item_id=item.id)


async def _denial_reason(requests: Any, item: WorkItem) -> str:
    """The Captain's reason when the request this item was parked on was denied, else "".

    Read from the request, not the item: AD-855 writes ``denial_reason`` only after the cancel this notice follows.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    if type(request_id) is not str or not request_id:
        return ""
    request = await requests.get(request_id)
    if request is None or request.status != "denied" or agent_work_approval(request) is None:
        return ""
    return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]


async def _close_bookings(store: Any, work_item_id: str, *, completed: bool) -> None:
    """A finished item's live booking is completed (done) or cancelled, so its claimant's capacity is freed."""
    for booking in await store.list_bookings(work_item_id=work_item_id):
        if booking.status in ("completed", "cancelled"):
            continue
        if completed and booking.status in ("active", "scheduled"):
            await store.complete_booking(booking.id)
        else:
            await store.cancel_booking(booking.id)


class AgentWorkRunner:
    """Ship's Computer: runs agent-created work in its assignee's agentic loop and reports it (AD-1347 S3)."""

    def __init__(
        self,
        *,
        service: AgentWorkService,
        store: Any,
        ward_room: Any,
        tools: Any,
        requests: Any,
        parking: Any,
        executor: WorkItemAgenticExecutor,
        runtime: Any,
        agents: Any,
        callsign_of: Callable[[str], str],
        max_pending: int = 20,
        ttl_seconds: int = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if any(value is None for value in (service, store, ward_room, tools, requests, parking, executor, agents)):
            raise ValueError("agent_work_runner_dependencies_required")
        self._service = service
        self._store = store
        self._ward_room = ward_room
        self._tools = tools
        self._requests = requests
        self._parking = parking
        self._executor = executor
        self._runtime = runtime  # passed through to each run only (the executor reads its stores from it)
        self._agents = agents
        self._callsign_of = callsign_of
        self._max_pending = max_pending
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._tasks: set[asyncio.Task[None]] = set()
        self._active: set[str] = set()
        self._deliver_lock = asyncio.Lock()
        self._stopping = False

    @property
    def running(self) -> tuple[asyncio.Task[None], ...]:
        """The runs in flight (``stop`` cancels them; a test awaits them)."""
        return tuple(self._tasks)

    async def on_store_event(self, event: Any) -> None:
        """The work store's events: created and claimed agent work starts, ended work is reported. Never raises."""
        try:
            raw_type = event.get("type") if type(event) is dict else None
            kind = getattr(raw_type, "value", raw_type)
            data = event.get("data") if type(event) is dict else None
            raw = data.get("work_item") if type(data) is dict else None
            work_item_id = raw.get("id") if type(raw) is dict else None
            if kind not in _HANDLED_EVENTS or type(work_item_id) is not str or not work_item_id:
                return
            item = await self._store.get_work_item(work_item_id)
            record = read_agent_work(item) if item is not None else None
            if item is None or record is None:
                return
            if kind == EventType.WORK_ITEM_STATUS_CHANGED.value:
                if item.status in TERMINAL_STATUSES:
                    await _close_bookings(self._store, item.id, completed=item.status == "done")
                    await self.deliver_due_notices()
            elif kind == EventType.WORK_ITEM_CREATED.value and record.kind == KIND_REQUEST:
                await self._announce(item, record)
            elif kind == EventType.WORK_ITEM_CREATED.value or record.kind == KIND_REQUEST:
                self._start(item.id)
        except Exception:
            logger.warning(
                "AD-1347: an agent-work event could not be handled; the board is unchanged and the next start's "
                "recovery retries it", exc_info=True,
            )

    async def claim(self, actor: str, work_item_id: str) -> tuple[str, str]:
        """CLAIM_WORK: claim through the tool sink (the stop at ``tool``, the claim tool's rank, AD-1187's compare and
        set, S1's eligibility gate), then run. Returns (outcome, what the claimant is told)."""
        member = self._service.crew_member(actor)
        short = work_item_id[:8]
        if member is None:
            return "refused", f"work item {short} was not claimed: you are not a live crew member"
        try:
            result = await self._tools.check_and_invoke(
                member.slot_id, "claim_work_item", {"work_item_id": work_item_id}, required=ToolPermission.WRITE,
                agent_department=member.department, agent_rank=member.rank, agent_types=[member.agent_type],
                context={"agent_id": member.slot_id, "_tool_result_presentation": _PRESENTATION},
            )
            claimed = result.error is None
        except Exception:
            logger.info("AD-1347: %s could not claim work item %s through the tool", member.slot_id, short, exc_info=True)
            claimed = False
        claimed_item = await self._store.get_work_item(work_item_id) if claimed else None
        if claimed_item is None or claimed_item.assigned_to != member.slot_id:
            return "not_claimed", f"work item {short} was not claimed by you: it is taken, closed, or not yours to serve"
        self._start(claimed_item.id)
        return "claimed", f"you claimed work item {short} (\"{claimed_item.title}\"); it runs now and its result is posted where it was asked"

    async def decline(self, actor: str, work_item_id: str, reason: str) -> tuple[str, str]:
        """DECLINE_WORK: a member of the request's department says why it is not theirs, once; the requester is told in
        the thread the work was asked in. The request stays open for the rest of the department."""
        member = self._service.crew_member(actor)
        short = work_item_id[:8]
        item = await self._store.get_work_item(work_item_id)
        record = read_agent_work(item) if item is not None else None
        if (
            member is None or item is None or record is None or record.kind != KIND_REQUEST
            or item.status != "open" or member.department != record.department
        ):
            return "refused", f"work item {short} is not an open request to your department"
        if not await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_DECLINE, self._clock()):
            return "repeated", f"you already declined work item {short}"
        why = " ".join(reason.split())[:MAX_REASON_CHARS] or "no reason given"
        requester = self._callsign_of(record.requester)
        await self._post(item, record, f"@{requester} {self._callsign_of(member.slot_id)} declined work item {short} (\"{item.title}\"): {why}")
        return "declined", f"you declined work item {short}; {requester} was told"

    async def resume(self, work_item_id: str) -> None:
        """AD-855 resumed a parked item (its request settled): run it again."""
        self._start(work_item_id)

    async def recover(self) -> int:
        """At start: run again every agent-created item a previous run left assigned and unfinished (a parked item
        waits for its request), then send the notices it owed. Idempotent; returns how many runs it started."""
        started = 0
        for open_item in await self._store.list_agent_work(True, None, SCAN_LIMIT):
            if open_item.assigned_to is None or open_item.status == "blocked":
                continue
            self._start(open_item.id)
            started += 1
        await self.deliver_due_notices()
        return started

    async def deliver_due_notices(self) -> int:
        """Tell each requester and watcher how ended agent work came out: one post per item, naming everyone newly
        told. A notice is claimed before it is sent (S1), so overlapping deliveries and a restart send it at most once.
        Returns how many recipients were told."""
        async with self._deliver_lock:
            grouped: dict[str, list[AgentWorkNotice]] = {}
            for notice in await self._service.terminal_notices_due():
                grouped.setdefault(notice.work_item_id, []).append(notice)
            told = 0
            for work_item_id, notices in grouped.items():
                item = await self._store.get_work_item(work_item_id)
                record = read_agent_work(item) if item is not None else None
                if item is None or record is None:
                    continue
                claimed = [notice.recipient for notice in notices if await self._service.claim_notice(work_item_id, notice.recipient)]
                if not claimed:
                    continue
                mentions = " ".join(f"@{self._callsign_of(recipient)}" for recipient in claimed)
                body = outcome_text(item, notices[0].outcome, mentions=mentions, denial=await _denial_reason(self._requests, item))
                if await self._post(item, record, body):
                    told += len(claimed)
            return told

    async def stop(self) -> None:
        """Shutdown: start nothing more, cancel the runs in flight and wait for them (``recover`` restarts them)."""
        self._stopping = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _start(self, work_item_id: str) -> None:
        """Run one item in the background, at most once at a time in this process."""
        if self._stopping or work_item_id in self._active:
            return
        self._active.add(work_item_id)
        task = asyncio.create_task(self._run(work_item_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, work_item_id: str) -> None:
        """One confined run of one item, then park it, return it to the board, or record its answer. Never raises
        (a cancellation from ``stop`` excepted); a failure marks the item failed, which its requester is told."""
        try:
            item = await self._store.get_work_item(work_item_id)
            record = read_agent_work(item) if item is not None else None
            if item is None or record is None or item.assigned_to is None or item.status in TERMINAL_STATUSES:
                return
            if item.status == "blocked":
                return
            slot = item.assigned_to
            if not self._service.execution_allowed(item, slot):
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant may not run it now")
                return
            if not await self._begin(item):
                return
            from probos.cognitive.agentic_dispatch import ToolCallConfinement

            agent = self._agents.get(slot)
            filed: list[str] = []
            confinement = ToolCallConfinement(
                AGENT_WORK_READ_TOOL_IDS,
                self._gate_for(item.id, await _approved_admission(self._requests, item, slot), filed),
            )
            try:
                outcome = await self._executor.run(
                    agent_id=slot, instructions=str(getattr(agent, "instructions", "") or ""),
                    task_text=task_text(item, requester=self._callsign_of(record.requester)),
                    runtime=self._runtime, failure_scope=item.id,
                    work_item_id_provider=lambda: item.id, confinement=confinement,
                )
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            if filed:
                await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)
                return
            if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):
                await self._store.unassign_work_item(item.id, reason="the claimant was stopped or lost the tool during the run")
                return
            invocations = getattr(outcome, "tool_invocations", None)
            result = {
                "executor": self._callsign_of(slot),
                "answer": (outcome.final_text or "").strip()[:REPORT_MAX_CHARS] or "(no answer text)",
                "tools": sorted(getattr(invocations, "succeeded", ()) or ()),
                "trace": outcome.tool_trace_ref or "",
            }
            done = await self._store.transition_work_item(
                item.id, "done", source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},
            )
            if done is None:
                current = await self._store.get_work_item(item.id)
                if current is not None and current.status in TERMINAL_STATUSES:
                    await self._store.transition_work_item(
                        item.id, current.status, source=RUN_SOURCE, expected_status=current.status,
                        metadata_patch={RESULT_METADATA_KEY: result},
                    )
            await _close_bookings(self._store, item.id, completed=done is not None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1347: the run of agent work item %s failed; it is marked failed and its requester is told",
                work_item_id, exc_info=True,
            )
            try:
                if await self._store.transition_work_item(
                    work_item_id, "failed", source=RUN_SOURCE, expected_status="in_progress",
                ) is not None:
                    await _close_bookings(self._store, work_item_id, completed=False)
            except Exception:
                logger.warning("AD-1347: work item %s could not be marked failed; it stays in_progress", work_item_id, exc_info=True)
        finally:
            self._active.discard(work_item_id)

    async def _begin(self, item: WorkItem) -> bool:
        """Move the item to in_progress once: a claimed request starts its booking; a self-task or an assignment
        moves from open; a resumed item is in_progress already."""
        if item.status == "in_progress":
            return True
        if item.status == "scheduled":
            bookings = [
                booking for booking in await self._store.list_bookings(work_item_id=item.id, status="scheduled")
                if booking.resource_id == item.assigned_to
            ]
            return len(bookings) == 1 and await self._store.start_booking(bookings[0].id) is not None
        if item.status == "open":
            moved = await self._store.transition_work_item(item.id, "in_progress", source=RUN_SOURCE, expected_status="open")
            return moved is not None
        return False

    def _gate_for(
        self, work_item_id: str, admission: tuple[str, str] | None, filed: list[str],
    ) -> Callable[[str, Any, Any], Awaitable[str]]:
        """The run's confinement gate: admit the one call an approval on record covers, else file the call for the
        Captain's approval. Fails toward refusal: a call that cannot be recorded is not run."""
        from probos.cognitive.agentic_dispatch import CONFINEMENT_ADMIT, CONFINEMENT_FILED, CONFINEMENT_REFUSED

        async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None:
                return CONFINEMENT_REFUSED
            key = action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id)
            if admission is not None and key == admission[1] and await self._store.claim_work_notice(
                work_item_id, agent_id, APPROVAL_USE_PREFIX + admission[0], self._clock(),
            ):
                return CONFINEMENT_ADMIT
            if self._requests.count_pending_sync(agent_id) >= self._max_pending:
                return CONFINEMENT_REFUSED
            request = await self._requests.file_action_request(
                agent_id, payload, rationale=f"agent work {work_item_id[:8]} called {tool_id}, outside the read-only set",
                work_item_id=work_item_id,
            )
            if request is None or not getattr(request, "id", ""):
                return CONFINEMENT_REFUSED
            if request.id not in filed:
                filed.append(request.id)
            return CONFINEMENT_FILED

        return gate

    async def _announce(self, item: WorkItem, record: AgentWorkRecord) -> int:
        """The activation notice: once per eligible member of the request's department, in that department's channel,
        with routing held to the members named (``max_responders``). Returns how many were told."""
        if record.tool_id is None or item.status != "open":
            return 0
        fresh: list[str] = []
        for member in self._service.eligible_members(record.tool_id):
            if member.department != record.department or member.slot_id == record.requester:
                continue
            if await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_ACTIVATION, self._clock()):
                fresh.append(member.slot_id)
        if not fresh:
            return 0
        reason = _provenance(item).get("reason", "")
        body = (
            " ".join(f"@{self._callsign_of(slot)}" for slot in fresh)
            + f" {self._callsign_of(record.requester)} asks {record.department} for work with {record.tool_id}: "
            f"\"{item.title}\". Reason: {reason}. Work item {item.id}. To take it, reply in this thread with "
            f"[CLAIM_WORK {item.id}]. If it is not yours to do, reply with [DECLINE_WORK {item.id}] and your reason, "
            f"then [/DECLINE_WORK]. The first claim wins; it expires {max(1, self._ttl_seconds // 3600)} h after it was asked."
        )
        try:
            channel = await self._ward_room.get_channel_by_department(record.department)
            if channel is None:
                logger.warning("AD-1347: no %s channel for the notice of work item %s; its TTL is the backstop", record.department, item.id[:8])
                return 0
            await self._ward_room.create_thread(
                channel_id=channel.id, author_id=SHIP_COMPUTER_ID, title=f"[Work request] {item.title}"[:200],
                body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=len(fresh),
            )
        except Exception:
            logger.warning("AD-1347: the notice of work item %s was not posted; its TTL is the backstop", item.id[:8], exc_info=True)
            return 0
        return len(fresh)

    async def _post(self, item: WorkItem, record: AgentWorkRecord, body: str) -> bool:
        """Post in the thread the work was asked in; with none (a proactive thought, a pruned or locked thread), in the
        department channel of the work. Authored by the Ship's Computer; the text names who did what. Never raises."""
        thread_id = _origin_thread(item)
        if thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=thread_id, author_id=SHIP_COMPUTER_ID, body=body, author_callsign=SHIP_COMPUTER_CALLSIGN,
                )
                return True
            except Exception:
                logger.info(
                    "AD-1347: thread %s could not take the post for work item %s; it goes to the %s channel",
                    thread_id[:8], item.id[:8], record.department, exc_info=True,
                )
        try:
            channel = await self._ward_room.get_channel_by_department(record.department)
            if channel is None:
                logger.warning("AD-1347: no %s channel for the post of work item %s; it was not posted", record.department, item.id[:8])
                return False
            await self._ward_room.create_thread(
                channel_id=channel.id, author_id=SHIP_COMPUTER_ID, title=f"[Agent work] {item.title}"[:200],
                body=body, author_callsign=SHIP_COMPUTER_CALLSIGN,
            )
            return True
        except Exception:
            logger.warning("AD-1347: the post for work item %s was not made", item.id[:8], exc_info=True)
            return False


async def resume_agent_work(runtime: Any, item: Any) -> bool:
    """AD-855's resume of agent-created work: through its runner, never the WorkItemRouter (which drops it). False for
    any other item, which AD-855 resumes as before. Never raises."""
    if read_agent_work(item) is None:
        return False
    runner = getattr(runtime, "agent_work_runner", None)
    if type(runner) is not AgentWorkRunner:
        logger.warning(
            "AD-1347: agent work item %s was resumed but no agent-work runner is wired; it stays in_progress until the "
            "next start's recovery runs it", getattr(item, "id", "?"),
        )
        return True
    await runner.resume(item.id)
    return True
```

### 7.10 `src/probos/agent_work_tags.py` (M2: claims and declines reach the runner; the tags are taught)

Pair 1 of 3 (import):

SEARCH:
```python
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)
```
REPLACE:
```python
from probos.agent_work_runner import AgentWorkRunner
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)
```

Pair 2 of 3 (teaching):

SEARCH:
```python
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict."
)
```
REPLACE:
```python
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict.\n"
    "When the Ship's Computer asks your department to take a request, reply [CLAIM_WORK <work item id>] to take it, "
    "or [DECLINE_WORK <work item id>] <your reason> [/DECLINE_WORK] when it is not yours to do. The first claim wins."
)
```

Pair 3 of 3 (the runner):

SEARCH:
```python
async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
    return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action
```
REPLACE:
```python
async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    runner = getattr(runtime, "agent_work_runner", None)
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    if type(runner) is not AgentWorkRunner:
        action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
        return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action
    if tag.action == ACTION_CLAIM:
        outcome, said = await runner.claim(actor, tag.work_item_id)
    else:
        outcome, said = await runner.decline(actor, tag.work_item_id, tag.reason)
    return _ack(said), {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": outcome}
```

### 7.11 `src/probos/cognitive/capability_gap_driver.py` (M2: an agent-work item resumes through its runner)

SEARCH:
```python
        from probos.cognitive.turn_promotion import (
            is_promoted_turn,
            resume_promoted_turn,
        )

        if is_promoted_turn(updated):
```
REPLACE:
```python
        from probos.agent_work_runner import resume_agent_work
        from probos.cognitive.turn_promotion import (
            is_promoted_turn,
            resume_promoted_turn,
        )

        # AD-1347 S3: agent-created work is not dispatchable; its runner runs it again (the router would drop it).
        if await resume_agent_work(self._runtime, updated):
            return
        if is_promoted_turn(updated):
```

### 7.12 `src/probos/routers/capability_requests.py` (M2: an agent-work approval is its own fulfilment)

Pair 1 of 2 (import):

SEARCH:
```python
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import (
```
REPLACE:
```python
from probos.agent_work_runner import agent_work_approval  # AD-1347 S3 (no cognitive import at module scope)
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import (
```

Pair 2 of 2 (the branch):

SEARCH:
```python
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
```
REPLACE:
```python
    if agent_work_approval(decided) is not None:
        # AD-1347 S3 (#1627): one tool call in one agent-created work item. The approval is its own fulfilment:
        # FULFILLED resumes the parked item (AD-855), whose next run makes that call once (the runner consumes the
        # approval). A denial does nothing here: AD-855 cancels the item on the DECIDED event.
        if not approve:
            return False
        return await store.mark_fulfilled(decided.id) is not None
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
```

### 7.13 `src/probos/runtime.py` (M2)

Pair 1 of 3:

SEARCH:
```python
    from probos.agent_work import AgentWorkService  # AD-1347 S1
```
REPLACE:
```python
    from probos.agent_work import AgentWorkService  # AD-1347 S1
    from probos.agent_work_runner import AgentWorkRunner  # AD-1347 S3
```

Pair 2 of 3:

SEARCH:
```python
    agent_work: "AgentWorkService | None"  # AD-1347 S1: built in start() only when agent_work.enabled; released with the store
```
REPLACE:
```python
    agent_work: "AgentWorkService | None"  # AD-1347 S1: built in start() only when agent_work.enabled; released with the store
    agent_work_runner: "AgentWorkRunner | None"  # AD-1347 S3: built in finalize only with agent_work; stopped before the store
```

Pair 3 of 3:

SEARCH:
```python
        # AD-1347 S1: the service that owns agent-created work; built in start() only when agent_work.enabled
        self.agent_work: "AgentWorkService | None" = None
```
REPLACE:
```python
        # AD-1347 S1: the service that owns agent-created work; built in start() only when agent_work.enabled
        self.agent_work: "AgentWorkService | None" = None
        # AD-1347 S3: the Ship's Computer runner of agent-created work; built in finalize only with the service
        self.agent_work_runner: "AgentWorkRunner | None" = None
```

### 7.14 `src/probos/startup/finalize.py` (M2)

Pair 1 of 2 (the wiring function):

SEARCH:
```python
    logger.info("AD-846: task-completion Captain-DM notifier wired")
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
```
REPLACE:
```python
    logger.info("AD-846: task-completion Captain-DM notifier wired")
    return True


def _wire_agent_work_runner(*, runtime: Any) -> bool:
    """AD-1347 S3 (#1627): build the Ship's Computer runner of agent-created work and subscribe it to the work store.

    Only while ``runtime.agent_work`` is the real service (agent_work.enabled built it). The runner needs the Ward Room
    to report, the tool registry to claim through, the capability-request store and AD-855's driver to park on the
    Captain's decision, and an LLM client to run; with any missing it is not built and the reason is logged
    (log-and-degrade: agent-created work is still filed, and a later start's recovery runs it).
    """
    from probos.agent_work import AgentWorkService

    if type(getattr(runtime, "agent_work", None)) is not AgentWorkService:
        return False
    needed = (
        "work_item_store", "ward_room", "tool_registry", "capability_request_store", "capability_gap_driver",
        "llm_client", "callsign_registry", "registry",
    )
    missing = [name for name in needed if getattr(runtime, name, None) is None]
    add_listener = getattr(runtime, "add_event_listener", None)
    if missing or add_listener is None:
        logger.warning(
            "AD-1347: agent_work is on but its runner is not built (missing: %s); agent-created work is filed and "
            "not run", ", ".join(missing) or "add_event_listener",
        )
        return False
    from probos.agent_work_runner import AgentWorkRunner
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    registry = runtime.registry
    callsigns = runtime.callsign_registry

    def callsign_of(slot_id: str) -> str:
        agent = registry.get(slot_id)
        callsign = callsigns.get_callsign(agent.agent_type) if agent is not None else ""
        return callsign or slot_id

    approval_inbox = getattr(runtime.config, "approval_inbox", None)
    runner = AgentWorkRunner(
        service=runtime.agent_work, store=runtime.work_item_store, ward_room=runtime.ward_room,
        tools=runtime.tool_registry, requests=runtime.capability_request_store, parking=runtime.capability_gap_driver,
        executor=WorkItemAgenticExecutor(llm_client=runtime.llm_client), runtime=runtime, agents=registry,
        callsign_of=callsign_of, max_pending=int(getattr(approval_inbox, "max_pending_per_agent", 20)),
        ttl_seconds=runtime.config.agent_work.ttl_seconds,
    )
    add_listener(
        runner.on_store_event, event_types=["work_item_created", "work_item_claimed", "work_item_status_changed"],
    )
    runtime.agent_work_runner = runner
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
```

Pair 2 of 2 (the call, after the gap driver and the notifiers):

SEARCH:
```python
            if _wire_task_completion_notifier(runtime=runtime, config=config):
                logger.info(
                    "AD-846: task-completion Captain-DM notifier wired "
                    "during finalization"
                )
```
REPLACE:
```python
            if _wire_task_completion_notifier(runtime=runtime, config=config):
                logger.info(
                    "AD-846: task-completion Captain-DM notifier wired "
                    "during finalization"
                )

            # AD-1347 S3 (#1627): the runner of agent-created work, after AD-855's driver (it parks on it). Only with
            # the agent_work service; recover() runs what a previous start left unfinished and sends owed notices.
            if _wire_agent_work_runner(runtime=runtime):
                await runtime.agent_work_runner.recover()
                logger.info("AD-1347: agent-work runner wired during finalization")
```

### 7.15 `src/probos/startup/shutdown.py` (M2)

SEARCH:
```python
        with steps("workforce store stop", runtime.work_item_store):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None
        runtime.agent_work = None  # AD-1347 S1: the service holds the store; released with it
```
REPLACE:
```python
        work_runner = getattr(runtime, "agent_work_runner", None)
        if work_runner is not None:
            with steps("agent work runner stop", work_runner):
                await work_runner.stop()
            runtime.agent_work_runner = None  # AD-1347 S3: its runs end before the store they write closes
        with steps("workforce store stop", runtime.work_item_store):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None
        runtime.agent_work = None  # AD-1347 S1: the service holds the store; released with it
```

### 7.16 `tests/fixtures/ad1343_seam_registry.py` (M2)

Pair 1 of 2:

SEARCH:
```python
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
}
```
REPLACE:
```python
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
    # AD-1347 S3: agent-created work; execution_allowed (the stop, no count) before each run, then the run entry.
    ("src/probos/startup/finalize.py", "_wire_agent_work_runner"): "agent-work eligibility, then the run entry",
}
```

Pair 2 of 2:

SEARCH:
```python
        "work an agent creates for itself or requests from a colleague (AD-1347); its claim is a tool call (SEAM_TOOL)",
```
REPLACE:
```python
        "work an agent creates for itself or requests from a colleague (AD-1347); its claim is a tool call (SEAM_TOOL) "
        "and its run a new agentic run (SEAM_AGENTIC_RUN)",
```

### 7.17 `tests/test_ad1156_plan_execute_mode.py` (M2: the never-ran set)

SEARCH:
```python
    never_ran = getattr(agentic_dispatch, "_NEVER_RAN_REFUSALS", frozenset())
    assert never_ran == {_REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL}
```
REPLACE:
```python
    never_ran = getattr(agentic_dispatch, "_NEVER_RAN_REFUSALS", frozenset())
    # AD-1347 S3: a confined call that was filed or refused never ran either.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
    }
```

### 7.18 `tests/test_issue1419_failed_start_rollback.py` (M2: one more stopped component)

SEARCH:
```python
    ("persistent_task_store", "persistent task store stop"),
    ("work_item_store", "workforce store stop"),
    ("build_dispatcher", "build dispatcher stop"),
```
REPLACE:
```python
    ("persistent_task_store", "persistent task store stop"),
    ("agent_work_runner", "agent work runner stop"),  # AD-1347 S3: before the store its runs write
    ("work_item_store", "workforce store stop"),
    ("build_dispatcher", "build dispatcher stop"),
```

### 7.19 `tests/test_ad1347_s1_agent_work.py` (M2: two docstring sentences; no behaviour)

Pair 1 of 2:

SEARCH:
```python
S2 and S3 extend ``test_request_is_created_published_and_claimed_by_an_eligible_member`` into acceptance 2's chain.
"""
```
REPLACE:
```python
Acceptance 2's whole chain (tag, item, notice, claim, run, report) is ``tests/test_ad1347_s3_execution.py`` X1.
"""
```

Pair 2 of 2:

SEARCH:
```python
    S2 and S3 extend this test into acceptance 2's chain: the chain tag before creation; the activation notice, the
    execution with event_log_query and the post in the origin thread after the claim.
```
REPLACE:
```python
    The whole chain, from the tag before creation to the post in the origin thread after the run, is
    tests/test_ad1347_s3_execution.py X1.
```

### 7.20 New file: `tests/test_ad1347_s3_execution.py` (M2)

```python
"""AD-1347 S3 (#1627): the Ship's Computer runs agent-created work, parks it on the Captain's decision and reports it.

Real objects: ``WorkItemStore``, ``CapabilityRequestStore``, ``WardRoomService``, ``EventLog``, ``ToolRegistry`` with
``event_log_query`` and the work pull tools registered by their production functions, ``ToolPermissionStore``,
``AgentStopService``, ``VesselOntologyService``, ``AgentRegistry``, ``TrustNetwork``, AD-855's ``CapabilityGapDriver``,
the approval route's ``decide_capability_request``, the real ``WardRoomPostPipeline`` and extractor, and the real
``WorkItemAgenticExecutor`` driven by a scripted model. The stores' events are captured and delivered by ``_pump`` as
the runtime's listeners deliver them. On today's tree every test fails at import (``probos.agent_work_runner``).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agent_stop import AgentStopService
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkService, open_agent_work_service
from probos.agent_work_runner import AGENT_WORK_READ_TOOL_IDS, AgentWorkRunner
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import agentic_dispatch
from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_FILED,
    CONFINED_CALL_NOT_FILED,
    ToolCallConfinement,
    WorkItemAgenticExecutor,
    classify_tool_fault_error,
)
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.crew_directory import RuntimeCrewDirectory
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.config import AgentWorkConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.ontology import VesselOntologyService
from probos.proactive import ProactiveCognitiveLoop
from probos.routers.capability_requests import decide_capability_request
from probos.runtime import ProbOSRuntime
from probos.startup.communication import _register_event_log_query_tool, _register_work_item_pull_tools
from probos.substrate.event_log import EventLog
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolResultPresentation, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from probos.workforce import BookableResource, WorkItemStore
from tests.test_ad1347_s1_agent_work import CREW, ENSIGNS, LIFT_REASON, RANKS, REASON, STOP_REASON, WIRED, _SlotIdentities
from tests.test_ad1347_s2_chain_tags import REQUEST, _loop_runtime, _posts
from tests.test_ad864_crew_assignment import _make_registry

_REPO = Path(__file__).resolve().parents[1]
CALLSIGNS = {
    "laforge-1": "LaForge", "forge-1": "Forge", "forge-2": "Rookie", "worf-1": "Worf", "rahda-1": "Rahda",
    "bones-1": "Bones", "pulaski-1": "Pulaski", "ogawa-1": "Ogawa", "numberone-1": "Riker",
}
WINDOW = {"start_time": "2026-10-23T00:00:00Z", "end_time": "2026-10-23T01:00:00Z", "category": "agent_stop"}
ANSWER = "Two stop orders in the window, both lifted."
PRESENTATION = ToolResultPresentation(render_complete=repr)


class _ScriptedClient:
    """The model, scripted: a response, or an async callable that returns one (as tests/test_ad1187_agent_work_pull.py)."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        response = self.responses[len(self.requests) - 1]
        return await response(request) if callable(response) else response


def _call(tool_id: str, params: dict[str, Any], call_id: str = "c1") -> LLMResponse:
    return LLMResponse(content="", tokens_used=1, content_blocks=[ToolUseBlock(ToolCallRequest(name=tool_id, arguments=params, id=call_id))])


def _final(text: str = ANSWER) -> LLMResponse:
    return LLMResponse(content=text, tokens_used=1, content_blocks=[TextBlock(text)])


class _Survey:
    """A tool outside the read set that counts its runs (hull_survey, engineering)."""

    tool_id = "hull_survey"
    name = "Hull survey"
    tool_type = ToolType.INFRA_SERVICE
    description = "Reads the hull sensors and writes a survey record."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output="Hull integrity 98 percent; survey record written.")


@dataclass
class _Rig:
    service: AgentWorkService
    store: WorkItemStore
    tools: ToolRegistry
    permissions: ToolPermissionStore
    stops: AgentStopService
    agents: dict[str, Any]
    wr: Any
    requests: Any
    driver: Any
    runner: AgentWorkRunner
    llm: _ScriptedClient
    survey: _Survey
    runtime: Any
    pipeline: Any
    work_events: list[tuple[Any, dict[str, Any]]]
    request_events: list[tuple[Any, dict[str, Any]]]
    data: Path


@contextlib.asynccontextmanager
async def _rig(
    tmp_path: Path, script: list[Any], *, section: AgentWorkConfig | None = None,
    clock: Callable[[], float] | None = None, max_pending: int = 20,
) -> AsyncIterator[_Rig]:
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(_REPO / "config" / "ontology", ontology_dir)
    (tmp_path / "ontology-data").mkdir()
    ontology = VesselOntologyService(ontology_dir, data_dir=tmp_path / "ontology-data")
    await ontology.initialize()
    for agent_type, slot in WIRED:
        ontology.wire_agent(agent_type, slot)
    registry = await _make_registry(list(CREW))
    agents = {agent.id: agent for agent in registry.all()}
    trust = TrustNetwork()
    for slot in ENSIGNS:
        trust.create_with_prior(slot, 1.0, 3.0)
    work_events: list[tuple[Any, dict[str, Any]]] = []
    request_events: list[tuple[Any, dict[str, Any]]] = []
    permissions = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    stops = AgentStopService(data_dir=tmp_path / "stops")
    event_log = EventLog(tmp_path / "events.db")
    requests = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"), emit_event=lambda kind, data: request_events.append((kind, data)))
    wr = WardRoomService(db_path=str(tmp_path / "wr.db"))
    runtime = object.__new__(ProbOSRuntime)  # the attributes the pull authority and the run read, as S1's _ship does
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"), tick_interval=1000.0,
        pull_resource_resolver=runtime.resolve_workforce_pull_resource,
        emit_event=lambda kind, data: work_events.append((kind, data)),
    )
    tools = ToolRegistry()
    survey = _Survey()
    started: list[Any] = []
    runner: AgentWorkRunner | None = None
    try:
        for agent in agents.values():
            await agent.start()
        for component in (permissions, stops, event_log, requests, wr):
            await component.start()
            started.append(component)
        tools.set_permission_store(permissions)
        tools.set_stop_gate(stops)
        _register_event_log_query_tool(tool_registry=tools, enabled=True, event_log_reader=event_log, event_log_audit_sink=event_log)
        tools.register(survey, allowed_departments=("engineering",), default_permissions=dict.fromkeys(RANKS, "read"))
        await permissions.issue_grant("forge-1", "hull_survey", ToolPermission.READ)
        runtime.config = SystemConfig()
        runtime.registry = registry
        runtime.ontology = ontology
        runtime.trust_network = trust
        runtime.tool_registry = tools
        runtime.tool_permission_store = permissions
        runtime.work_item_store = store
        runtime.event_log = event_log
        runtime.capability_request_store = requests
        runtime.intent_bus = None
        for slot, agent in agents.items():
            store.register_resource(BookableResource(resource_id=slot, agent_type=agent.agent_type, department="", capacity=5, characteristics=[]))
        await store.start()
        started.append(store)
        _register_work_item_pull_tools(tool_registry=tools, work_item_store=store, pull_resource_resolver=runtime.resolve_workforce_pull_resource)
        directory = RuntimeCrewDirectory(agent_registry=registry, ontology=ontology, trust_network=trust)
        service = await open_agent_work_service(
            config=section or AgentWorkConfig(enabled=True), store=store, tools=tools,
            identities=_SlotIdentities(agents), directory=directory, stop_gate=stops, clock=clock or time.time,
        )
        assert isinstance(service, AgentWorkService)
        runtime.agent_work = service
        driver = CapabilityGapDriver(runtime=runtime, work_item_store=store, capability_request_store=requests)
        runtime.capability_gap_driver = driver
        llm = _ScriptedClient(script)
        runner = AgentWorkRunner(
            service=service, store=store, ward_room=wr, tools=tools, requests=requests, parking=driver,
            executor=WorkItemAgenticExecutor(llm_client=llm), runtime=runtime, agents=registry,
            callsign_of=lambda slot: CALLSIGNS.get(slot, slot), max_pending=max_pending,
        )
        runtime.agent_work_runner = runner
        loop_runtime = _loop_runtime(service, trust)
        loop_runtime.ward_room = wr
        loop_runtime.agent_work_runner = runner
        loop = ProactiveCognitiveLoop(cooldown=0)
        loop.set_runtime(loop_runtime)
        router = MagicMock(spec=WardRoomRouter)
        router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, callsign: text)
        pipeline = WardRoomPostPipeline(
            ward_room=wr, ward_room_router=router, proactive_loop=loop, trust_network=None,
            callsign_registry=None, config=MagicMock(),
        )
        yield _Rig(
            service, store, tools, permissions, stops, agents, wr, requests, driver, runner, llm, survey, runtime,
            pipeline, work_events, request_events, tmp_path,
        )
    finally:
        if runner is not None:
            await runner.stop()
        for component in reversed(started):
            await component.stop()
        for agent in agents.values():
            if agent.is_alive:
                await agent.stop()


async def _pump(rig: _Rig) -> None:
    """Deliver the stores' events as the runtime's listeners do, and wait for every run, until nothing is left."""
    for _ in range(20):
        work = list(rig.work_events)
        rig.work_events.clear()
        asked = list(rig.request_events)
        rig.request_events.clear()
        for kind, data in work:
            await rig.runner.on_store_event({"type": getattr(kind, "value", kind), "data": data})
        for kind, data in asked:
            await rig.driver.on_capability_event({"type": getattr(kind, "value", kind), "data": data})
        await asyncio.gather(*rig.runner.running)
        if not work and not asked and not rig.work_events and not rig.request_events:
            return
    raise AssertionError("the stores kept emitting")


async def _thread_in(rig: _Rig, department: str, author: str) -> Any:
    channel = await rig.wr.get_channel_by_department(department)
    return await rig.wr.create_thread(channel.id, author, "Relay drift", "The relay drifted twice.", author_callsign=CALLSIGNS[author])


def _system_posts(rig: _Rig, thread_id: str) -> list[str]:
    return [body for author, body in _posts(rig.data / "wr.db", thread_id) if author == "system"]


def _events(rig: _Rig, category: str, event: str) -> list[tuple[str, dict[str, Any]]]:
    with contextlib.closing(sqlite3.connect(rig.data / "events.db")) as raw:
        rows = raw.execute("SELECT agent_id, data FROM events WHERE category = ? AND event = ?", (category, event)).fetchall()
    return [(agent_id, json.loads(data) if data else {}) for agent_id, data in rows]


def _seen(rig: _Rig, text: str) -> bool:
    """Whether the model was shown ``text`` (in the plain or the structured transcript)."""
    for request in rig.llm.requests:
        if text in (request.prompt or "") or any(text in str(message.get("content", "")) for message in (request.messages or [])):
            return True
    return False


async def _with_tool(rig: _Rig, slot: str, tool_id: str, params: dict[str, Any]) -> Any:
    member = rig.service.crew_member(slot)
    assert member is not None, slot
    required = ToolPermission.READ if tool_id == "discover_work_items" else ToolPermission.WRITE
    return await rig.tools.check_and_invoke(
        slot, tool_id, params, required=required, agent_department=member.department, agent_rank=member.rank,
        agent_types=[member.agent_type], context={"agent_id": slot, "_tool_result_presentation": PRESENTATION},
    )


async def _request(rig: _Rig, requester: str, thread_id: str) -> str:
    created = await rig.service.request_work(
        requester, title="Read the EventLog window", description="", reason=REASON,
        origin=AgentWorkOrigin("ward_room", thread_id=thread_id), tool_id="event_log_query",
    )
    assert isinstance(created, AgentWorkCreated), created
    return created.work_item.id


# X1
async def test_a_chain_request_is_announced_claimed_run_and_reported_in_its_origin_thread(tmp_path: Path) -> None:
    """Acceptance 2: the chain tag, the item, the notice, the claim, the run with event_log_query, the post in the thread."""
    async with _rig(tmp_path, [_call("event_log_query", WINDOW), _final()]) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["pulaski-1"], response_text=f"I need the event log for that window.\n{REQUEST}",
            thread_id=origin.id, event_type="ward_room_thread_created",
        )
        [item] = await rig.store.list_agent_work(False, None, 10)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert notice.author_id == "system" and item.id in notice.body and notice.max_responders == 2
        assert "@Forge" in notice.body and "@LaForge" in notice.body
        assert "@Rookie" not in notice.body and "@Worf" not in notice.body and "@Rahda" not in notice.body
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"Taking it.\n[CLAIM_WORK {item.id}]",
            thread_id=notice.id, event_type="ward_room_thread_created",
        )
        await asyncio.gather(*rig.runner.running)  # the chain's claim starts the run itself
        done = await rig.store.get_work_item(item.id)
        assert done is not None and (done.status, done.assigned_to, done.created_by) == ("done", "forge-1", "pulaski-1")
        await _pump(rig)
        [booking] = await rig.store.list_bookings(work_item_id=item.id)
        assert (booking.resource_id, booking.status) == ("forge-1", "completed")
        assert any(agent == "forge-1" and data.get("outcome") == "success" for agent, data in _events(rig, "audit", "event_log_query"))
        assert any(data.get("work_item_id") == item.id and data.get("is_error") is False for _, data in _events(rig, "tool", "tool_invoked"))
        [report] = _system_posts(rig, origin.id)
        assert ANSWER in report and item.id in report and "@Pulaski" in report and "check it against the record" in report
        acks = [body for author, body in _posts(rig.data / "wr.db", notice.id) if author == "forge-1"]
        assert len(acks) == 1 and "you claimed work item" in acks[0]
        assert len(rig.llm.requests) == 2


# X2
async def test_a_call_outside_the_read_set_parks_the_item_and_an_approval_runs_it_exactly_once(tmp_path: Path) -> None:
    """Acceptance 4: filed, nothing run; approved, the item resumes and the call runs once; a repeat is filed; denied,
    the item ends and the Captain's reason reaches the origin thread."""
    script = [
        _call("hull_survey", {}), _final("Waiting for the Captain."),
        _call("hull_survey", {}, "c1"), _call("hull_survey", {}, "c2"), _final("Surveyed once."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey the hull", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        item_id = created.work_item.id
        await _pump(rig)
        parked = await rig.store.get_work_item(item_id)
        assert parked is not None and parked.status == "blocked" and rig.survey.calls == 0
        first_id = parked.metadata["capability_request_id"]
        first = await rig.requests.get(first_id)
        assert (first.kind, first.status, first.agent_id, first.work_item_id) == ("action", "pending", "forge-1", item_id)
        assert (first.payload["tool_id"], first.payload["action"], first.payload["scope_key"]) == (
            "hull_survey", "agent_work_call", f"agent_work:{item_id}",
        )
        assert _seen(rig, CONFINED_CALL_FILED)
        captain = SimpleNamespace(capability_request_store=rig.requests)
        approved = await decide_capability_request(first_id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert approved["fulfilled"] is True
        await _pump(rig)
        again = await rig.store.get_work_item(item_id)
        assert rig.survey.calls == 1, "the approval admits the call it was asked for, once"
        assert again is not None and again.status == "blocked"
        second_id = again.metadata["capability_request_id"]
        assert second_id != first_id and (await rig.requests.get(second_id)).status == "pending"
        denied = await decide_capability_request(
            second_id, CapabilityRequestDecideRequest(approve=False, reason="once is enough"), runtime=captain,
        )
        assert denied["fulfilled"] is False
        await _pump(rig)
        ended = await rig.store.get_work_item(item_id)
        assert ended is not None and ended.status == "cancelled" and rig.survey.calls == 1
        [report] = _system_posts(rig, origin.id)
        assert "once is enough" in report and "@Forge" in report


# X3
@pytest.mark.parametrize("cause", ["stop_before_run", "restricted_before_run", "stop_during_run"])
async def test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed(tmp_path: Path, cause: str) -> None:
    """Acceptance 5 and blind spot 7: never failed; the booking is cancelled; the member may claim it again once allowed."""
    holder: dict[str, Any] = {}

    async def _stop_then_read(request: LLMRequest) -> LLMResponse:
        await holder["rig"].stops.issue_stop("forge-1", reason=STOP_REASON)
        return _call("event_log_query", WINDOW)

    script = [_stop_then_read, _final("partial")] if cause == "stop_during_run" else []
    async with _rig(tmp_path, script) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        claim = await _with_tool(rig, "forge-1", "claim_work_item", {"work_item_id": item_id})
        assert ast.literal_eval(claim.output)["owned"] is True
        restriction = None
        if cause == "stop_before_run":
            await rig.stops.issue_stop("forge-1", reason=STOP_REASON)
        elif cause == "restricted_before_run":
            restriction = await rig.permissions.issue_grant("forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True)
        await _pump(rig)  # WORK_ITEM_CLAIMED starts the run
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["cancelled"]
        assert _system_posts(rig, origin.id) == []
        if cause == "stop_during_run":
            [stop] = rig.stops.active()
            assert rig.stops.refused_counts(stop.stop_id) == {"tool": 1}
        else:
            assert rig.llm.requests == []
        if restriction is not None:
            await rig.permissions.revoke_grant(restriction.id)
        else:
            await rig.stops.lift_stop("forge-1", reason=LIFT_REASON)
        discovered = await _with_tool(rig, "forge-1", "discover_work_items", {})
        assert item_id in [entry["id"] for entry in ast.literal_eval(discovered.output)["items"]]


# X4
async def test_every_watcher_of_a_deduplicated_request_gets_the_report(tmp_path: Path) -> None:
    """Blind spot 6: dedup must not drop a watcher's answer."""
    async with _rig(tmp_path, [_call("event_log_query", WINDOW), _final()]) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        other = await _thread_in(rig, "medical", "ogawa-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", other.id) == item_id
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        [report] = _system_posts(rig, origin.id)
        assert "@Pulaski" in report and "@Ogawa" in report and ANSWER in report
        assert await rig.service.terminal_notices_due() == ()


# X5
async def test_an_expired_request_tells_each_recipient_once_across_two_overlapping_deliveries(tmp_path: Path) -> None:
    section = AgentWorkConfig(enabled=True, ttl_seconds=60)
    async with _rig(tmp_path, [], section=section, clock=lambda: time.time() - 120) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", origin.id) == item_id
        assert await rig.store.transition_work_item(item_id, "cancelled", source="ttl_expiry") is not None  # as the sweep does
        told = await asyncio.gather(rig.runner.deliver_due_notices(), rig.runner.deliver_due_notices())
        assert sorted(told) == [0, 2]
        await _pump(rig)
        [notice] = _system_posts(rig, origin.id)
        assert "expired before anyone produced a result" in notice and "@Pulaski" in notice and "@Ogawa" in notice
        engineering = await rig.wr.get_channel_by_department("engineering")
        assert await rig.wr.list_threads(engineering.id) == []  # an ended request is not announced


# X6
async def test_two_overlapping_starts_run_an_item_once(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_final()]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await asyncio.gather(rig.runner.resume(created.work_item.id), rig.runner.resume(created.work_item.id))
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done"
        assert len(rig.llm.requests) == 1 and len(_system_posts(rig, origin.id)) == 1


# X7
async def test_a_decline_is_recorded_once_and_its_reason_reaches_the_requester(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"[DECLINE_WORK {item_id}]\nOn the warp core all shift.\n[/DECLINE_WORK]",
            thread_id=notice.id, event_type="ward_room_thread_created",
        )
        assert (await rig.runner.decline("forge-1", item_id, "again"))[0] == "repeated"
        assert (await rig.runner.decline("worf-1", item_id, "not mine"))[0] == "refused"
        [relay] = _system_posts(rig, origin.id)
        assert "declined" in relay and "warp core" in relay and "@Pulaski" in relay
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)


# X8
async def test_an_ensign_or_another_department_cannot_claim_through_the_chain(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        for slot in ("forge-2", "worf-1"):
            await rig.pipeline.process_and_post(
                agent=rig.agents[slot], response_text=f"Mine.\n[CLAIM_WORK {item_id}]",
                thread_id=notice.id, event_type="ward_room_thread_created",
            )
        posts = dict(_posts(rig.data / "wr.db", notice.id))
        assert "was not claimed by you" in posts["worf-1"]
        assert "Ship's Computer" not in posts.get("forge-2", "")  # an ensign's tag is stripped and nothing is done
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert rig.runner.running == ()


# X9
@pytest.mark.parametrize(("verdict", "expected"), [
    ("admit", None), ("filed", CONFINED_CALL_FILED), ("refused", CONFINED_CALL_NOT_FILED), ("anything", CONFINED_CALL_NOT_FILED),
])
async def test_the_confinement_gate_decides_every_call_outside_its_set(verdict: str, expected: str | None) -> None:
    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        return verdict

    result = await ToolCallConfinement(frozenset({"event_log_query"}), gate).refuse_or_admit("forge-1", "hull_survey", {})
    assert (result.error if result is not None else None) == expected


async def test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome() -> None:
    async def broken(agent_id: str, tool_id: Any, params: Any) -> str:
        raise RuntimeError("store down")

    result = await ToolCallConfinement(frozenset({"event_log_query"}), broken).refuse_or_admit("forge-1", "hull_survey", {})
    assert result is not None and result.error == CONFINED_CALL_NOT_FILED
    for text in (CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED):
        assert text in agentic_dispatch._NEVER_RAN_REFUSALS
        assert not is_capability_gap(text)
        assert classify_tool_fault_error(text) == "permission_denied"
    for tool_ids, gate in ((frozenset(), broken), ({"x"}, broken), (frozenset({"x"}), "not callable")):
        with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
            ToolCallConfinement(tool_ids, gate)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
        await WorkItemAgenticExecutor(llm_client=_ScriptedClient([])).run(
            agent_id="forge-1", instructions="", task_text="x", runtime=SimpleNamespace(),
            plan_mode_tool_ids=frozenset({"event_log_query"}), confinement=ToolCallConfinement(frozenset({"x"}), broken),
        )
    assert AGENT_WORK_READ_TOOL_IDS <= PLAN_MODE_TOOL_IDS
    assert not AGENT_WORK_READ_TOOL_IDS & {"web_search", "read_page", "http_fetch", "discover_work_items"}


# X10
async def test_a_full_approval_inbox_refuses_the_call_without_filing_it(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_call("hull_survey", {}), _final()], max_pending=0) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done" and rig.survey.calls == 0
        assert rig.requests.count_pending_sync("forge-1") == 0
        assert _seen(rig, CONFINED_CALL_NOT_FILED)


# X11
async def test_recover_runs_work_a_previous_start_left_unfinished(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_final()]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        rig.work_events.clear()  # the created event was lost with the previous start
        assert await rig.runner.recover() == 1
        await asyncio.gather(*rig.runner.running)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done"


# X12
async def test_an_ordinary_item_still_resumes_through_the_work_item_router(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        dispatched: list[str] = []

        class _Router:
            async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
                dispatched.append(wi["id"])
                return True

            def is_dispatchable(self, wi: dict[str, Any]) -> bool:
                return True

        rig.runtime.work_item_router = _Router()
        plain = await rig.store.create_work_item(title="Plain task", assigned_to="forge-1")
        asked = await rig.requests.file_request(agent_id="forge-1", kind="continue", target="continue", work_item_id=plain.id)
        assert await rig.driver.block_on_request(work_item_id=plain.id, request_id=asked.id, reason="waiting")
        await rig.requests.decide(asked.id, True)
        await rig.requests.mark_fulfilled(asked.id)
        await _pump(rig)
        assert dispatched == [plain.id]
        assert rig.llm.requests == [] and rig.runner.running == ()
```

### 7.21 New file: `tests/test_ad1347_s3_wiring.py` (M2)

```python
"""AD-1347 S3 (#1627): finalize builds the agent-work runner only with the service, and shutdown releases it.

Real boots, as ``tests/test_ad1347_s1_wiring.py`` (its config and its two fixtures: the Ship's Archive off, the local
embedding backend).
"""

from __future__ import annotations

from pathlib import Path

from probos.agent_work import AgentWorkService
from probos.agent_work_runner import AgentWorkRunner
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from tests.test_ad1347_s1_wiring import (  # noqa: F401  (fixtures are found by name)
    _assert_no_embedding_model_loaded,
    _boot_config,
    archive_resolutions,
    local_embeddings,
)


def _config(*, enabled: bool) -> SystemConfig:
    """S1's boot shape with the Ward Room on: the runner posts its notices and reports there, and finalize wires AD-855's driver only with it."""
    config = _boot_config(enabled=enabled)
    config.ward_room.enabled = True
    return config


# W3
async def test_the_runner_is_wired_only_with_the_service_and_released_at_stop(
    tmp_path: Path, archive_resolutions: list[object], local_embeddings: Path,
) -> None:
    off = ProbOSRuntime(config=_config(enabled=False), data_dir=tmp_path / "off", llm_client=MockLLMClient())
    await off.start()
    try:
        assert off.agent_work is None and off.agent_work_runner is None
    finally:
        await off.stop()
    on = ProbOSRuntime(config=_config(enabled=True), data_dir=tmp_path / "on", llm_client=MockLLMClient())
    await on.start()
    try:
        assert isinstance(on.agent_work, AgentWorkService)
        assert on.capability_gap_driver is not None and on.capability_request_store is not None and on.ward_room is not None, (
            "premise: the runner's collaborators exist on this boot"
        )
        assert isinstance(on.agent_work_runner, AgentWorkRunner)
    finally:
        await on.stop()
    assert on.agent_work_runner is None, "a clean stop releases the runner"
    assert archive_resolutions == []
    _assert_no_embedding_model_loaded(local_embeddings)
```

W3 boots through `_config`, S1's boot shape with the Ward Room on. On S1's own boot config the Ward Room is off, so finalize wires neither AD-855's driver nor anything else inside its `if runtime.ward_room:` block, and the premise assertion fails (shown by execution, 2026-10-23); with it on, the runner and its collaborators exist. The test's assertions are unchanged.

### 7.22 `src/probos/capability_request.py` (M2, A1: F1, one definition of the bound agent-work call)

SEARCH:
```python
def can_fulfil_request(req: CapabilityRequest) -> bool:
    return req.kind in FULFILMENT_KINDS or repair_action(req) is not None
```
REPLACE:
```python
#: AD-1347 S3 A1 (F1): one tool call in one agent-created work item, filed by the agent-work runner's confinement.
AGENT_WORK_CALL_ACTION = "agent_work_call"
AGENT_WORK_SCOPE_PREFIX = "agent_work:"


def agent_work_call(req: Any) -> dict[str, Any] | None:
    """The validated payload when ``req`` asks to make one tool call in one agent-created work item, else None.

    Bound to its own item: the scope is ``agent_work:`` and the request's ``work_item_id``. Its approval is its own
    fulfilment (the approval route marks it fulfilled and AD-855 resumes the item), so it is fulfillable, as the repair
    action is; every other action still has no fulfiller. The HXI's ``canFulfil`` (``ui/src/store/capabilityApprovals.ts``)
    mirrors this exactly: ``can_retry_fulfilment`` must agree on both sides.
    """
    if getattr(req, "kind", None) != "action":
        return None
    payload = validate_action_payload(getattr(req, "payload", None))
    work_item_id = getattr(req, "work_item_id", None)
    if (
        payload is None or payload["action"] != AGENT_WORK_CALL_ACTION
        or type(work_item_id) is not str or not work_item_id
        or payload["scope_key"] != AGENT_WORK_SCOPE_PREFIX + work_item_id
    ):
        return None
    return payload


def can_fulfil_request(req: CapabilityRequest) -> bool:
    return req.kind in FULFILMENT_KINDS or repair_action(req) is not None or agent_work_call(req) is not None
```

### 7.23 `ui/src/store/capabilityApprovals.ts` (M2, A1: F1, the HXI decoder mirrors the predicate)

Pair 1 of 3:

SEARCH:
```ts
function canFulfil(kind: unknown, payload: unknown): boolean {
  if (FULFILMENT_KINDS.has(String(kind))) return true;
  if (kind !== 'action' || !isRecord(payload)) return false;
  const keys = ['tool_id', 'action', 'params', 'scope_key', 'session_id', 'thread_id'];
```
REPLACE:
```ts
/** AD-1347 S3 A1 (F1): one tool call in one agent-created work item, bound to it by its scope. Its approval is its
 * own fulfilment. Mirrors Python's `agent_work_call` (src/probos/capability_request.py) exactly:
 * `can_retry_fulfilment` must agree on both sides, or every row of the actionable queue is refused. */
function isAgentWorkCall(payload: Record<string, unknown>, workItemId: unknown): boolean {
  return payload.action === 'agent_work_call' && typeof workItemId === 'string' && workItemId !== ''
    && payload.scope_key === 'agent_work:' + workItemId;
}

function canFulfil(kind: unknown, payload: unknown, workItemId: unknown): boolean {
  if (FULFILMENT_KINDS.has(String(kind))) return true;
  if (kind !== 'action' || !isRecord(payload)) return false;
  const keys = ['tool_id', 'action', 'params', 'scope_key', 'session_id', 'thread_id'];
  if (Object.keys(payload).length === keys.length && keys.every(key => key in payload) && isAgentWorkCall(payload, workItemId)) return true;
```

Pair 2 of 3:

SEARCH:
```ts
    && value.can_retry_fulfilment === (value.status === 'approved' && canFulfil(value.kind, value.payload));
```
REPLACE:
```ts
    && value.can_retry_fulfilment === (value.status === 'approved' && canFulfil(value.kind, value.payload, value.work_item_id));
```

Pair 3 of 3:

SEARCH:
```ts
    || (request.can_retry_fulfilment && !canFulfil(expected.kind, expected.payload))
    || (value.fulfilled && (!canFulfil(request.kind, request.payload) || !canFulfil(expected.kind, expected.payload)))) {
```
REPLACE:
```ts
    || (request.can_retry_fulfilment && !canFulfil(expected.kind, expected.payload, expected.work_item_id))
    || (value.fulfilled && (!canFulfil(request.kind, request.payload, request.work_item_id)
      || !canFulfil(expected.kind, expected.payload, expected.work_item_id)))) {
```

### 7.24 New file: `ui/e2e/fixtures/ad1347-agent-work-approvals.json` (M2, A1: F1; asserted equal to the real route output by X13)

```json
{
  "pending": {
    "view": "actionable",
    "requests": [
      {
        "id": "00000000-0000-0000-0000-000000000001",
        "agent_id": "forge-1",
        "kind": "action",
        "target": "hull_survey.agent_work_call @ agent_work:wi-agent-work-1",
        "rationale": "agent work wi-agent called hull_survey, outside the read-only set",
        "work_item_id": "wi-agent-work-1",
        "status": "pending",
        "created_at": 1000.0,
        "decided_at": null,
        "decided_by": "",
        "decision_reason": "",
        "payload": {
          "tool_id": "hull_survey",
          "action": "agent_work_call",
          "params": {"depth": 2},
          "scope_key": "agent_work:wi-agent-work-1",
          "session_id": null,
          "thread_id": ""
        },
        "can_retry_fulfilment": false
      }
    ]
  },
  "fulfilled": {
    "request": {
      "id": "00000000-0000-0000-0000-000000000001",
      "agent_id": "forge-1",
      "kind": "action",
      "target": "hull_survey.agent_work_call @ agent_work:wi-agent-work-1",
      "rationale": "agent work wi-agent called hull_survey, outside the read-only set",
      "work_item_id": "wi-agent-work-1",
      "status": "fulfilled",
      "created_at": 1000.0,
      "decided_at": 1000.0,
      "decided_by": "captain",
      "decision_reason": "",
      "payload": {
        "tool_id": "hull_survey",
        "action": "agent_work_call",
        "params": {"depth": 2},
        "scope_key": "agent_work:wi-agent-work-1",
        "session_id": null,
        "thread_id": ""
      },
      "can_retry_fulfilment": false
    },
    "standing_rule": null,
    "fulfilled": true
  },
  "approved": {
    "view": "actionable",
    "requests": [
      {
        "id": "00000000-0000-0000-0000-000000000002",
        "agent_id": "forge-1",
        "kind": "action",
        "target": "hull_survey.agent_work_call @ agent_work:wi-agent-work-1",
        "rationale": "agent work wi-agent called hull_survey, outside the read-only set",
        "work_item_id": "wi-agent-work-1",
        "status": "approved",
        "created_at": 1000.0,
        "decided_at": 1000.0,
        "decided_by": "captain",
        "decision_reason": "",
        "payload": {
          "tool_id": "hull_survey",
          "action": "agent_work_call",
          "params": {"depth": 3},
          "scope_key": "agent_work:wi-agent-work-1",
          "session_id": null,
          "thread_id": ""
        },
        "can_retry_fulfilment": true
      }
    ]
  }
}
```

### 7.25 New file: `ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts` (M2, A1: F1)

```ts
/**
 * AD-1347 S3 A1 (F1): the HXI decoder accepts the approval route's real agent-work envelopes.
 * The fixture is asserted equal to the real Python route output by tests/test_ad1347_s3_execution.py (X13).
 */
import { describe, expect, it } from 'vitest';
import { isActionableCapabilityPayload, isCapabilityRequestView, parseCapabilityDecision } from '../capabilityApprovals';
import wire from '../../../e2e/fixtures/ad1347-agent-work-approvals.json';

describe('AD-1347 agent-work approval wire', () => {
  it('confirms the fulfilled approval of the agent-work call bound to its item', () => {
    expect(isActionableCapabilityPayload(wire.pending)).toBe(true);
    const [pending] = wire.pending.requests;
    if (!isCapabilityRequestView(pending)) throw new Error('Invalid Python pending fixture');
    const outcome = parseCapabilityDecision(wire.fulfilled, pending, true);
    expect(outcome.fulfilled).toBe(true);
    expect(outcome.request.status).toBe('fulfilled');
  });

  it('keeps an approved, unfulfilled agent-work call on the queue as retryable', () => {
    expect(isActionableCapabilityPayload(wire.approved)).toBe(true);
    expect(wire.approved.requests[0].can_retry_fulfilment).toBe(true);
  });

  it('refuses a retry flag on an agent-work call bound to another item or another action', () => {
    const [row] = wire.approved.requests;
    for (const changed of [
      { ...row, work_item_id: 'wi-other' },
      { ...row, payload: { ...row.payload, action: 'click' } },
    ]) expect(isCapabilityRequestView(changed)).toBe(false);
  });
});
```

### 7.26 `src/probos/cognitive/agentic_dispatch.py` (M2, A1: F3, an admitted call is not parked again)

Pair 1 of 5 (the context variable):

SEARCH:
```python
_STRICT_APPROVAL_DISPATCH: ContextVar[EffectDispatchContext | None] = ContextVar(
    "strict_approval_dispatch", default=None
)
```
REPLACE:
```python
_STRICT_APPROVAL_DISPATCH: ContextVar[EffectDispatchContext | None] = ContextVar(
    "strict_approval_dispatch", default=None
)
# AD-1347 S3 A1 (F3): set for the one call a run's confinement admitted under the Captain's single-use approval of that
# exact call, so AD-1154's inbox does not park it again. Credential entry (the inbox's step 3) is still refused.
_CONFINED_ADMISSION: ContextVar[bool] = ContextVar("confined_admission", default=False)
```

Pair 2 of 5:

SEARCH:
```python
        confinement = self._confinement
        if confinement is not None and tool_id not in confinement.tool_ids:
```
REPLACE:
```python
        confinement = self._confinement
        confined_admission = False
        if confinement is not None and tool_id not in confinement.tool_ids:
```

Pair 3 of 5:

SEARCH:
```python
            if refusal is not None:
                strict_log("confinement", "confinement_refused")
                return refuse(refusal, "confinement_refused")
        if self._plan_mode_tool_ids is not None and tool_id not in self._plan_mode_tool_ids:
```
REPLACE:
```python
            if refusal is not None:
                strict_log("confinement", "confinement_refused")
                return refuse(refusal, "confinement_refused")
            # AD-1347 S3 A1 (F3): the Captain approved exactly this call, once; AD-1154's inbox below does not park it
            # again (credential entry there stays refused).
            confined_admission = True
        if self._plan_mode_tool_ids is not None and tool_id not in self._plan_mode_tool_ids:
```

Pair 4 of 5:

SEARCH:
```python
        strict_token = _STRICT_APPROVAL_DISPATCH.set(strict_dispatch)
        try:
            parked = await self._park_or_admit(
```
REPLACE:
```python
        strict_token = _STRICT_APPROVAL_DISPATCH.set(strict_dispatch)
        admission_token = _CONFINED_ADMISSION.set(confined_admission)
        try:
            parked = await self._park_or_admit(
```

and

SEARCH:
```python
        finally:
            _STRICT_APPROVAL_DISPATCH.reset(strict_token)
        if parked is not None:
```
REPLACE:
```python
        finally:
            _CONFINED_ADMISSION.reset(admission_token)
            _STRICT_APPROVAL_DISPATCH.reset(strict_token)
        if parked is not None:
```

Pair 5 of 5 (between the inbox's steps 3 and 4):

SEARCH:
```python
            return ToolResult(error=_APPROVAL_CREDENTIAL_REFUSAL)

        scope_key = self._resolve_scope_key(
```
REPLACE:
```python
            return ToolResult(error=_APPROVAL_CREDENTIAL_REFUSAL)

        if _CONFINED_ADMISSION.get():
            # AD-1347 S3 A1 (F3): the run's confinement admitted this exact call under the Captain's single-use approval
            # of it, so it is not parked again; credential entry (step 3, above) stays refused.
            logger.info("AD-1347: %s.%s for agent %s runs under the Captain's approval of this call", tool_id, action, agent_id[:12])
            return None

        scope_key = self._resolve_scope_key(
```

### 7.27 `src/probos/agent_work_runner.py` (M2, A1: F1, F2, F3, F4, F5, F8, F9's literal, F13, F15)

Pair 1 of 13 (imports):

SEARCH:
```python
from probos.capability_request import action_dedup_key, validate_action_payload
```
REPLACE:
```python
from probos.capability_request import (
    AGENT_WORK_CALL_ACTION,
    AGENT_WORK_SCOPE_PREFIX,
    action_dedup_key,
    agent_work_call,
    validate_action_payload,
)
```

Pair 2 of 13 (one definition; the unrecorded parameters):

SEARCH:
```python
APPROVAL_ACTION: Final = "agent_work_call"
APPROVAL_SCOPE_PREFIX: Final = "agent_work:"
```
REPLACE:
```python
APPROVAL_ACTION: Final = AGENT_WORK_CALL_ACTION  # A1 (F1): one definition, shared with the fulfilment predicate
APPROVAL_SCOPE_PREFIX: Final = AGENT_WORK_SCOPE_PREFIX
#: A1 (F15): parameters an approval never records, as AD-1154's inbox strips them (``_APPROVAL_PARAM_STRIP_KEYS``): a
#: browser confirmation token is a bearer token ``BrowserTool`` honours, so persisting it is BF-682. Stripped before
#: filing and before matching alike, so the approved call's identity does not depend on it.
APPROVAL_UNRECORDED_PARAMS: Final[frozenset[str]] = frozenset({"confirmation_token"})
```

Pair 3 of 13 (how an unfinished run is named):

SEARCH:
```python
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})
```
REPLACE:
```python
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})
#: A1 (F4): how a report names a run that stopped without a finished answer, by the executor's ``stopped_reason``
#: (``agentic_loop``); ``complete`` without an answer, and any other reason, read as ``UNFINISHED_WORDS``.
STOP_WORDS: Final[dict[str, str]] = {
    "max_iterations": "the run reached its step limit before it finished",
    "token_budget": "the run used up its token budget before it finished",
    "error": "the run stopped on an error",
}
UNFINISHED_WORDS: Final = "the run stopped without a finished answer"
```

Pair 4 of 13 (the subtype, delegated):

SEARCH:
```python
def agent_work_approval(request: Any) -> dict[str, Any] | None:
    """The validated payload when ``request`` asks to make one tool call in one agent-created work item, else None."""
    if getattr(request, "kind", None) != "action":
        return None
    payload = validate_action_payload(getattr(request, "payload", None))
    work_item_id = getattr(request, "work_item_id", None)
    if (
        payload is None or payload["action"] != APPROVAL_ACTION
        or type(work_item_id) is not str or not work_item_id
        or payload["scope_key"] != APPROVAL_SCOPE_PREFIX + work_item_id
    ):
        return None
    return payload
```
REPLACE:
```python
def agent_work_approval(request: Any) -> dict[str, Any] | None:
    """The validated payload when ``request`` asks to make one tool call in one agent-created work item, else None.

    A1 (F1): one definition, ``capability_request.agent_work_call``, which the fulfilment predicate shares.
    """
    return agent_work_call(request)
```

Pair 5 of 13 (no token is recorded):

SEARCH:
```python
    if type(tool_id) is not str or type(params) is not dict:
        return None
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": dict(params),
```
REPLACE:
```python
    if type(tool_id) is not str or type(params) is not dict:
        return None
    recorded = {key: value for key, value in params.items() if key not in APPROVAL_UNRECORDED_PARAMS}
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": recorded,
```

Pair 6 of 13 (the report names an unfinished stop):

SEARCH:
```python
        status = "is done" if outcome == "done" else f"ended as {outcome}, after this answer"
```
REPLACE:
```python
        if outcome == "done":
            status = "is done"
        elif type(result.get("stopped")) is str:  # A1 (F4): the run stopped without a finished answer
            status = f"ended as {outcome}: {STOP_WORDS.get(result['stopped'], UNFINISHED_WORDS)}, after this answer"
        else:
            status = f"ended as {outcome}, after this answer"
```

Pair 7 of 13 (the TTL in words; the outcome of a run that did not park):

SEARCH:
```python
        if completed and booking.status in ("active", "scheduled"):
            await store.complete_booking(booking.id)
        else:
            await store.cancel_booking(booking.id)


class AgentWorkRunner:
```
REPLACE:
```python
        if completed and booking.status in ("active", "scheduled"):
            await store.complete_booking(booking.id)
        else:
            await store.cancel_booking(booking.id)


def ttl_words(seconds: int) -> str:
    """The TTL as a notice states it, never rounded (A1, F13): whole hours, else whole minutes, else seconds."""
    for unit, size in (("h", 3_600), ("min", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size} {unit}"
    return f"{seconds} s"


async def _record_outcome(store: Any, item: WorkItem, executor: str, outcome: Any) -> None:
    """A1 (F4): how a run that neither filed a call nor was parked is recorded. Done only when the executor completed
    with an answer; any other stop (its step limit, its token budget, an error, an empty answer) is failed, with the
    reason the report names. The result goes with the status in one write; an item the TTL ended meanwhile keeps its
    end and gains the result (register R3)."""
    answer = (outcome.final_text or "").strip()[:REPORT_MAX_CHARS]
    stopped = outcome.stopped_reason if type(outcome.stopped_reason) is str else ""
    finished = stopped == "complete" and bool(answer)
    invocations = getattr(outcome, "tool_invocations", None)
    result: dict[str, Any] = {
        "executor": executor,
        "answer": answer or "(no answer text)",
        "tools": sorted(getattr(invocations, "succeeded", ()) or ()),
        "trace": outcome.tool_trace_ref or "",
    }
    if not finished:
        result["stopped"] = stopped or "unknown"
    status = "done" if finished else "failed"
    moved = await store.transition_work_item(
        item.id, status, source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},
    )
    if moved is None:
        current = await store.get_work_item(item.id)
        if current is not None and current.status in TERMINAL_STATUSES:
            await store.transition_work_item(
                item.id, current.status, source=RUN_SOURCE, expected_status=current.status,
                metadata_patch={RESULT_METADATA_KEY: result},
            )
    await _close_bookings(store, item.id, completed=moved is not None and finished)


class AgentWorkRunner:
```

Pair 8 of 13 (the deferred starts):

SEARCH:
```python
        self._active: set[str] = set()
```
REPLACE:
```python
        self._active: set[str] = set()
        self._restart: set[str] = set()  # A1 (F2): starts that arrived while the item ran; made when that run ends
```

Pair 9 of 13 (a decline reaches every recipient, and says whether it was posted):

SEARCH:
```python
        why = " ".join(reason.split())[:MAX_REASON_CHARS] or "no reason given"
        requester = self._callsign_of(record.requester)
        await self._post(item, record, f"@{requester} {self._callsign_of(member.slot_id)} declined work item {short} (\"{item.title}\"): {why}")
        return "declined", f"you declined work item {short}; {requester} was told"
```
REPLACE:
```python
        why = " ".join(reason.split())[:MAX_REASON_CHARS] or "no reason given"
        # A1 (F8): the requester and every watcher of a deduplicated request; posted once (the decline is claimed above).
        recipients = await self._service.notice_recipients(item.id)
        names = [self._callsign_of(slot) for slot in recipients]
        mentions = " ".join(f"@{name}" for name in names)
        posted = await self._post(item, record, f"{mentions} {self._callsign_of(member.slot_id)} declined work item {short} (\"{item.title}\"): {why}")
        told = ", ".join(names)
        if not posted:  # A1 (F9, the literal): a post that did not go through is not "told"
            return "declined", f"you declined work item {short}; the notice to {told} could not be posted"
        return "declined", f"you declined work item {short}; {told} {'was' if len(names) == 1 else 'were'} told"
```

Pair 10 of 13 (`_start` keeps a start that arrives during a run):

SEARCH:
```python
        """Run one item in the background, at most once at a time in this process."""
        if self._stopping or work_item_id in self._active:
            return
        self._active.add(work_item_id)
```
REPLACE:
```python
        """Run one item in the background, at most once at a time in this process.

        A1 (F2): a start that arrives while the item runs (an approval that settled before the run parked, through
        BF-878, or a duplicate event) is kept and made when that run ends; that run re-reads the item, so a finished or
        parked one does nothing. A stopped runner starts and keeps nothing: the next start's ``recover`` runs what is left.
        """
        if self._stopping:
            return
        if work_item_id in self._active:
            self._restart.add(work_item_id)
            return
        self._active.add(work_item_id)
```

Pair 11 of 13 (`_run`'s docstring):

SEARCH:
```python
        """One confined run of one item, then park it, return it to the board, or record its answer. Never raises
        (a cancellation from ``stop`` excepted); a failure marks the item failed, which its requester is told."""
```
REPLACE:
```python
        """One confined run of one item, then return it to the board, park it, or record how it ended. Never raises
        (a cancellation from ``stop`` excepted); a failure marks the item failed, which its requester is told.

        A1 (review round 1): a request's eligibility is asked again first (F5); a run that filed a call parks on it and
        one the executor parked itself stays parked (F3); only a completed run with an answer is done (F4,
        ``_record_outcome``); a start that arrived during this run is made when it ends (F2).
        """
```

Pair 12 of 13 (after the executor returns):

SEARCH:
```python
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            if filed:
                await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)
                return
            if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):
                await self._store.unassign_work_item(item.id, reason="the claimant was stopped or lost the tool during the run")
                return
            invocations = getattr(outcome, "tool_invocations", None)
            result = {
                "executor": self._callsign_of(slot),
                "answer": (outcome.final_text or "").strip()[:REPORT_MAX_CHARS] or "(no answer text)",
                "tools": sorted(getattr(invocations, "succeeded", ()) or ()),
                "trace": outcome.tool_trace_ref or "",
            }
            done = await self._store.transition_work_item(
                item.id, "done", source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},
            )
            if done is None:
                current = await self._store.get_work_item(item.id)
                if current is not None and current.status in TERMINAL_STATUSES:
                    await self._store.transition_work_item(
                        item.id, current.status, source=RUN_SOURCE, expected_status=current.status,
                        metadata_patch={RESULT_METADATA_KEY: result},
                    )
            await _close_bookings(self._store, item.id, completed=done is not None)
```
REPLACE:
```python
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            # A1 (F5): first, so a claimant stopped (or that lost the tool) after it filed a call is released, never
            # parked; a call it filed stays on the Captain's queue, inert: AD-855 and the admission act only on an item
            # parked on that request.
            if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):
                await self._store.unassign_work_item(item.id, reason="the claimant was stopped or lost the tool during the run")
                return
            if filed:
                await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)
                return
            if outcome.parked_request_id:
                return  # A1 (F3): AD-1324 parked the item on its own tier-floor ask; that decision resumes it
            await _record_outcome(self._store, item, self._callsign_of(slot), outcome)
```

and

SEARCH:
```python
        finally:
            self._active.discard(work_item_id)

    async def _begin(self, item: WorkItem) -> bool:
```
REPLACE:
```python
        finally:
            self._active.discard(work_item_id)
            if work_item_id in self._restart:  # A1 (F2): a start that arrived during this run runs now
                self._restart.discard(work_item_id)
                self._start(work_item_id)

    async def _begin(self, item: WorkItem) -> bool:
```

Pair 13 of 13 (the notice states the TTL):

SEARCH:
```python
            f"then [/DECLINE_WORK]. The first claim wins; it expires {max(1, self._ttl_seconds // 3600)} h after it was asked."
```
REPLACE:
```python
            f"then [/DECLINE_WORK]. The first claim wins; it expires {ttl_words(self._ttl_seconds)} after it was asked."
```

### 7.28 `src/probos/agent_work_tags.py` (M2, A1: F6, F7, F10, F11)

Pair 1 of 6 (the module docstring):

SEARCH:
```python
Off: ``agent_work_service`` answers None, the extractor never calls this module, and nothing is taught.
```
REPLACE:
```python
Reading (A1, review round 1): names are read in any letter case and every marker is removed, closers included. A
marker in a code fence or on a Markdown quote line (``>``) is an example or a quotation: removed, never acted on. A
block that holds another marker (nested or broken) is removed whole and not acted on. One pass reads the markers, each
at most 160 characters to its bracket, so the work is linear in the reply. A fault on one tag is acknowledged, never
retried, and the rest of the reply goes on.

Off: ``runtime.agent_work`` is None, so the extractor neither imports nor calls this module, and nothing is taught.
```

Pair 2 of 6:

SEARCH:
```python
from dataclasses import dataclass
```
REPLACE:
```python
from dataclasses import dataclass, field
```

Pair 3 of 6 (the markers):

SEARCH:
```python
_BLOCK_RE: Final = re.compile(
    r"\[(SELF_TASK|REQUEST_WORK)\](.*?)\[/\1\]"
    r"|\[CLAIM_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\]"
    r"|\[DECLINE_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\](.*?)\[/DECLINE_WORK\]",
    re.DOTALL,
)
_STRAY_RE: Final = re.compile(
    r"\[/?(?:SELF_TASK|REQUEST_WORK|DECLINE_WORK)\]|\[(?:CLAIM_WORK|DECLINE_WORK)\b[^\]\n]{0,160}\]"
)
```
REPLACE:
```python
#: A1 (F7, F11): every agent-work marker, opener or closer, in any letter case: ``[NAME]``, ``[/NAME]`` or
#: ``[NAME <attribute>]``, on one line with at most 160 characters before its bracket, so one scan reads each
#: character a bounded number of times.
_MARKER_RE: Final = re.compile(
    r"\[(/?)(SELF_TASK|REQUEST_WORK|CLAIM_WORK|DECLINE_WORK)\b([^\]\n]{0,160})\]", re.IGNORECASE,
)
_ITEM_ID_RE: Final = re.compile(r"[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*")
#: A1 (F6): a Markdown code fence line (up to three spaces, then three backticks or three tildes).
_FENCE_RE: Final = re.compile(r"[ \t]{0,3}(?:`{3}|~{3})")
_BLOCK_NAMES: Final[frozenset[str]] = frozenset({"SELF_TASK", "REQUEST_WORK"})
```

Pair 4 of 6 (one linear scan):

SEARCH:
```python
def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any of them (stray markers included).

    A text with no tag and no stray marker is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    for match in _BLOCK_RE.finditer(text):
        if match.group(1) is not None:
            fields = _fields(match.group(2))
            tags.append(AgentWorkTag(
                ACTION_SELF_TASK if match.group(1) == "SELF_TASK" else ACTION_REQUEST,
                title=fields.get("title", ""), reason=fields.get("reason", ""), details=fields.get("details", ""),
                tool_id=fields.get("tool", ""), department=fields.get("department", "").lower(),
                assignee=fields.get("assignee", "").lstrip("@").strip(),
            ))
        elif match.group(3) is not None:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=match.group(3)))
        else:
            tags.append(AgentWorkTag(ACTION_DECLINE, work_item_id=match.group(4), reason=" ".join(match.group(5).split())))
    without = _STRAY_RE.sub("", _BLOCK_RE.sub("", text))
    if not tags and without == text:
        return text, ()
    return without.strip(), tuple(tags)
```
REPLACE:
```python
@dataclass
class _OpenBlock:
    """A block opener the scan has not closed yet (A1)."""

    name: str
    item_id: str
    start: int
    body_start: int
    actionable: bool
    inner: list[tuple[int, int]] = field(default_factory=list)


def _inert_line_ends(text: str) -> list[tuple[int, bool]]:
    """(end offset, inert) of each line. Inert: inside a code fence or opening or closing one, or a Markdown quote line;
    a marker there is an example or a quotation (A1, F6)."""
    lines: list[tuple[int, bool]] = []
    fenced = False
    end = 0
    for line in text.splitlines(keepends=True):
        end += len(line)
        fence = _FENCE_RE.match(line) is not None
        lines.append((end, fenced or fence or line.lstrip().startswith(">")))
        fenced = fenced != fence
    return lines


def _block_tag(block: _OpenBlock, body: str) -> AgentWorkTag:
    """The tag a closed, actionable block asks for."""
    if block.name == "DECLINE_WORK":
        return AgentWorkTag(ACTION_DECLINE, work_item_id=block.item_id, reason=" ".join(body.split()))
    fields = _fields(body)
    return AgentWorkTag(
        ACTION_SELF_TASK if block.name == "SELF_TASK" else ACTION_REQUEST,
        title=fields.get("title", ""), reason=fields.get("reason", ""), details=fields.get("details", ""),
        tool_id=fields.get("tool", ""), department=fields.get("department", "").lower(),
        assignee=fields.get("assignee", "").lstrip("@").strip(),
    )


def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any marker.

    One pass over the markers (A1: F6, F7, F11). Names are read in any letter case. A marker on an inert line (a code
    fence, a quote) is removed and never acted on, and so is a block that holds another marker (nested or broken),
    which is removed whole. A closed block is removed whole; an unclosed opener, the markers after it and every stray
    marker are removed alone. A text with no marker is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    cuts: list[tuple[int, int]] = []
    lines = _inert_line_ends(text)
    line = 0
    block: _OpenBlock | None = None
    for match in _MARKER_RE.finditer(text):
        while lines[line][0] <= match.start():
            line += 1
        inert = lines[line][1]
        closer, name, attribute = match.group(1) == "/", match.group(2).upper(), match.group(3)
        item_id = _ITEM_ID_RE.fullmatch(attribute) if not closer and name in ("CLAIM_WORK", "DECLINE_WORK") else None
        if block is not None:
            if closer and name == block.name and not attribute.strip():
                if block.actionable:
                    tags.append(_block_tag(block, text[block.body_start:match.start()]))
                cuts.append((block.start, match.end()))
                block = None
            else:
                block.actionable = False
                block.inner.append((match.start(), match.end()))
            continue
        if (not closer and name in _BLOCK_NAMES and not attribute.strip()) or (item_id is not None and name == "DECLINE_WORK"):
            block = _OpenBlock(name, item_id.group(1) if item_id is not None else "", match.start(), match.end(), not inert)
            continue
        if item_id is not None and not inert:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=item_id.group(1)))
        cuts.append((match.start(), match.end()))
    if block is not None:
        cuts.extend([(block.start, block.body_start), *block.inner])
    if not cuts:
        return text, ()
    kept: list[str] = []
    position = 0
    for start, end in cuts:
        kept.append(text[position:start])
        position = end
    kept.append(text[position:])
    return "".join(kept).strip(), tuple(tags)
```

Pair 5 of 6 (one tag's fault is its own):

SEARCH:
```python
async def apply_agent_work_tags(
    text: str, *, runtime: Any, actor: str, rank: Rank, thread_id: str = "", post_id: str = "",
) -> tuple[str, list[dict[str, Any]]]:
```
REPLACE:
```python
async def _apply_guarded(
    tag: AgentWorkTag, *, service: AgentWorkService, runtime: Any, actor: str,
    origin: AgentWorkOrigin | None, in_thread: bool,
) -> tuple[str, dict[str, Any]]:
    """One tag, isolated (A1, F10): a fault is logged and acknowledged, never retried (whether the write landed is
    unknown, so the agent is told to check the board), and the reply and its other tags go on."""
    try:
        return await _apply_one(tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=in_thread)
    except Exception:
        logger.warning("AD-1347: an agent-work %s tag from %s could not be completed; the reply goes on", tag.action, actor, exc_info=True)
        return (
            _ack(f"the {tag.action.replace('_', '-')} could not be confirmed: check the board before asking again"),
            {"type": "agent_work", "action": tag.action, "outcome": "error"},
        )


async def apply_agent_work_tags(
    text: str, *, runtime: Any, actor: str, rank: Rank, thread_id: str = "", post_id: str = "",
) -> tuple[str, list[dict[str, Any]]]:
```

Pair 6 of 6:

SEARCH:
```python
        ack, action = await _apply_one(
            tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id),
        )
```
REPLACE:
```python
        ack, action = await _apply_guarded(tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id))
```

### 7.29 `src/probos/proactive.py` (M2, A1: F12, off never reaches the tag module)

SEARCH:
```python
        # --- Agent-created work (AD-1347 S2) — Lieutenant+; only while the service exists, so off is untouched ---
        # Before BF-203: each tag has a closed form and is stripped whole here.
        from probos.agent_work_tags import agent_work_service, apply_agent_work_tags

        if agent_work_service(rt) is not None:
            text, work_actions = await apply_agent_work_tags(
                text, runtime=rt, actor=agent.id, rank=rank, thread_id=thread_id, post_id=post_id,
            )
            actions_executed.extend(work_actions)
```
REPLACE:
```python
        # --- Agent-created work (AD-1347 S2) — Lieutenant+; only while the service exists, so off is untouched ---
        # Before BF-203: each tag has a closed form and is stripped whole here. Off (no service at all) neither imports
        # nor calls the tag module (A1, F12); a runtime holding something else asks only whether it is the service.
        if getattr(rt, "agent_work", None) is not None:
            from probos.agent_work_tags import agent_work_service, apply_agent_work_tags

            if agent_work_service(rt) is not None:
                text, work_actions = await apply_agent_work_tags(
                    text, runtime=rt, actor=agent.id, rank=rank, thread_id=thread_id, post_id=post_id,
                )
                actions_executed.extend(work_actions)
```

### 7.30 `tests/test_ad1347_s2_chain_tags.py` (M2, A1: C1, C5, C14 to C16)

Pair 1 of 5:

SEARCH:
```python
import contextlib
import sqlite3
from pathlib import Path
```
REPLACE:
```python
import contextlib
import sqlite3
import time
from pathlib import Path
```

Pair 2 of 5:

SEARCH:
```python
SELF_TASK = "[SELF_TASK]\nTitle: Check my build log\nReason: the relay drifted twice\n[/SELF_TASK]"
```
REPLACE:
```python
SELF_TASK = "[SELF_TASK]\nTitle: Check my build log\nReason: the relay drifted twice\n[/SELF_TASK]"
FENCE = "`" * 3  # A1: a Markdown code fence, spelled so this file holds no literal fence
```

Pair 3 of 5 (C1: five more cases):

SEARCH:
```python
    ("Stray [/REQUEST_WORK] and [CLAIM_WORK] and [DECLINE_WORK bad id!]", [], "Stray  and  and"),
])
```
REPLACE:
```python
    ("Stray [/REQUEST_WORK] and [CLAIM_WORK] and [DECLINE_WORK bad id!]", [], "Stray  and  and"),
    # A1 (F6): a fenced example and a quoted claim are stripped and never acted on.
    (f"Example syntax only:\n{FENCE}\n[SELF_TASK]\nTitle: x\n[/SELF_TASK]\n{FENCE}", [], f"Example syntax only:\n{FENCE}\n\n{FENCE}"),
    ("> [CLAIM_WORK wi-1]\nNot mine to take.", [], "> \nNot mine to take."),
    # A1 (F6): a nested block is broken, removed whole, and files nothing ("Outer Inner" before A1).
    ("[SELF_TASK]\nTitle: Outer\n[SELF_TASK]\nTitle: Inner\n[/SELF_TASK]\n[/SELF_TASK]", [], ""),
    # A1 (F7): names in any case, and every marker goes, the claim closer included.
    ("Ok. [Self_Task]\nTitle: Mixed\n[/sELF_tASK] [claim_work wi-123] [/CLAIM_WORK]",
     [AgentWorkTag("self_task", title="Mixed"), AgentWorkTag("claim", work_item_id="wi-123")], "Ok."),
    # A1 (F7): an unclosed opener and every marker after it are removed; the text stays.
    ("Open [SELF_TASK] then [CLAIM_WORK wi-2]", [], "Open  then"),
])
```

Pair 4 of 5 (C5: off never calls the tag module):

SEARCH:
```python
    monkeypatch.setattr(tags_module, "apply_agent_work_tags", _spy)
    async with _ship(tmp_path) as ship:
        for service in (None, MagicMock()):  # off, and a double that is not the real service
            loop = _loop(_loop_runtime(service, TrustNetwork()))
            await loop._extract_and_execute_actions(ship.agents["forge-1"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert entered == []
```
REPLACE:
```python
    asked: list[Any] = []
    service_of = tags_module.agent_work_service

    def _service_of(runtime: Any) -> Any:
        asked.append(runtime.agent_work)
        return service_of(runtime)

    monkeypatch.setattr(tags_module, "apply_agent_work_tags", _spy)
    monkeypatch.setattr(tags_module, "agent_work_service", _service_of)
    async with _ship(tmp_path) as ship:
        doubles = (None, MagicMock())  # off, and a double that is not the real service
        for service in doubles:
            loop = _loop(_loop_runtime(service, TrustNetwork()))
            await loop._extract_and_execute_actions(ship.agents["forge-1"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert entered == []
        assert asked == [doubles[1]]  # A1 (F12): off neither imports nor calls the tag module
```

Pair 5 of 5 (C14 to C16):

SEARCH:
```python
        assert "assigned to forge-1" in cleaned and actions[-1]["outcome"] == "created"
```
REPLACE:
```python
        assert "assigned to forge-1" in cleaned and actions[-1]["outcome"] == "created"


# C14
async def test_an_example_a_quotation_or_a_broken_block_is_stripped_and_nothing_is_filed(tmp_path: Path) -> None:
    """A1 (F6, F7): fenced and quoted tags are examples and a nested block is broken; none is acted on, every marker
    goes, in any letter case."""
    text = (
        f"Example syntax only:\n{FENCE}\n{SELF_TASK}\n{FENCE}\n> [CLAIM_WORK wi-1]\n"
        "[SELF_TASK]\nTitle: Outer\n[Self_Task]\nTitle: Inner\n[/SELF_TASK]\n[/self_task] [/CLAIM_WORK]"
    )
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], text, thread_id="t1")
        assert await ship.store.list_agent_work(False, None, 10) == []
        assert [action for action in actions if action.get("type") == "agent_work"] == []
        lowered = cleaned.lower()
        assert "self_task" not in lowered and "claim_work" not in lowered and cleaned.startswith("Example syntax only:")


# C15
def test_repeated_unclosed_openers_are_parsed_in_one_bounded_pass() -> None:
    """A1 (F11): 66 KB of unclosed openers. The review measured 3.1 s for this shape before A1 (one rescan per opener)."""
    text = "[SELF_TASK]" * 6_000
    started = time.perf_counter()
    assert split_agent_work_tags(text) == ("", ())
    assert time.perf_counter() - started < 0.5


# C16
async def test_a_work_store_fault_on_one_tag_is_acknowledged_and_the_rest_of_the_reply_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F10): the reply is posted, the next tag is acted on, and the failed one is acknowledged, not retried."""
    async with _ship(tmp_path) as ship:
        async def _broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("attempt to write a readonly database")

        monkeypatch.setattr(ship.service, "create_self_task", _broken)
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(
            ship.agents["pulaski-1"], f"Obs.\n{SELF_TASK}\n{REQUEST}", thread_id="t1",
        )
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None and record.kind == "request"
        assert cleaned.startswith("Obs.") and "could not be confirmed" in cleaned and item.id[:8] in cleaned
        assert [action["outcome"] for action in actions if action.get("type") == "agent_work"] == ["error", "created"]
```

### 7.31 `tests/test_ad1347_s3_execution.py` (M2, A1: X3, X7, X12, X13 to X21)

Pair 1 of 13 (imports):

SEARCH:
```python
import ast
import asyncio
import contextlib
import json
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
```
REPLACE:
```python
import ast
import asyncio
import contextlib
import itertools
import json
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
```

Pair 2 of 13:

SEARCH:
```python
import pytest

from probos.agent_stop import AgentStopService
```
REPLACE:
```python
import pytest

import probos.capability_request as request_module
from probos.agent_stop import AgentStopService
```

Pair 3 of 13:

SEARCH:
```python
from probos.config import AgentWorkConfig, SystemConfig
```
REPLACE:
```python
from probos.capability_request import can_fulfil_request
from probos.config import AgentWorkConfig, HybridDispatchConfig, SystemConfig
```

Pair 4 of 13:

SEARCH:
```python
from probos.ontology import VesselOntologyService
```
REPLACE:
```python
from probos.mesh.department_dispatcher import DepartmentDispatcher
from probos.mesh.work_item_router import WorkItemRouter
from probos.ontology import VesselOntologyService
```

Pair 5 of 13:

SEARCH:
```python
from probos.routers.capability_requests import decide_capability_request
```
REPLACE:
```python
from probos.routers.capability_requests import decide_capability_request, list_actionable_capability_requests
```

Pair 6 of 13:

SEARCH:
```python
from tests.test_ad864_crew_assignment import _make_registry
```
REPLACE:
```python
from tests.test_ad864_crew_assignment import _make_registry
from tests.test_ad1154_approval_inbox import _TIER_3_URL, _armed, _invoke, _open_session
from tests.test_ad706_browser_tool import _FakePage
from tests.test_bf887_continue_resumes_the_promoted_turn import _Dispatcher
```

Pair 7 of 13 (the rig's runner gets the section's TTL):

SEARCH:
```python
            callsign_of=lambda slot: CALLSIGNS.get(slot, slot), max_pending=max_pending,
```
REPLACE:
```python
            callsign_of=lambda slot: CALLSIGNS.get(slot, slot), max_pending=max_pending,
            ttl_seconds=(section or AgentWorkConfig(enabled=True)).ttl_seconds,
```

Pair 8 of 13 (the pump waits for a run started when another ended):

SEARCH:
```python
        await asyncio.gather(*rig.runner.running)
        if not work and not asked and not rig.work_events and not rig.request_events:
            return
```
REPLACE:
```python
        await asyncio.gather(*rig.runner.running)
        idle = all(task.done() for task in rig.runner.running)  # A1 (F2): a run's end can start the next
        if not work and not asked and not rig.work_events and not rig.request_events and idle:
            return
```

Pair 9 of 13 (watching the executor's entries and outcomes):

SEARCH:
```python
    assert isinstance(created, AgentWorkCreated), created
    return created.work_item.id
```
REPLACE:
```python
    assert isinstance(created, AgentWorkCreated), created
    return created.work_item.id


def _watch_runs(
    monkeypatch: pytest.MonkeyPatch,
    then: Callable[[dict[str, Any], Any], Awaitable[Any]] | None = None,
) -> list[dict[str, Any]]:
    """A1: wrap ``WorkItemAgenticExecutor.run``; each entry is recorded before the run and its outcome after it.
    ``then`` stands in for what the executor itself does after its loop (AD-1324's own parking, X16)."""
    runs: list[dict[str, Any]] = []
    original = WorkItemAgenticExecutor.run

    async def _run(self: Any, **kwargs: Any) -> Any:
        entry: dict[str, Any] = {"agent_id": kwargs.get("agent_id"), "outcome": None}
        runs.append(entry)
        outcome = await original(self, **kwargs)
        if then is not None:
            outcome = await then(kwargs, outcome)
        entry["outcome"] = outcome
        return outcome

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", _run)
    return runs
```

Pair 10 of 13 (X3: the executor is not entered before the run):

SEARCH:
```python
async def test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed(tmp_path: Path, cause: str) -> None:
    """Acceptance 5 and blind spot 7: never failed; the booking is cancelled; the member may claim it again once allowed."""
    holder: dict[str, Any] = {}
```
REPLACE:
```python
async def test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str,
) -> None:
    """Acceptance 5 and blind spot 7: never failed; the booking is cancelled; the member may claim it again once allowed.
    A1 (F14): a refusal before the run is made before the executor is entered, not by the run entry's own stop check."""
    holder: dict[str, Any] = {}
    runs = _watch_runs(monkeypatch)
```

and

SEARCH:
```python
        if cause == "stop_during_run":
            [stop] = rig.stops.active()
            assert rig.stops.refused_counts(stop.stop_id) == {"tool": 1}
        else:
            assert rig.llm.requests == []
```
REPLACE:
```python
        if cause == "stop_during_run":
            [stop] = rig.stops.active()
            assert rig.stops.refused_counts(stop.stop_id) == {"tool": 1}
            assert [run["agent_id"] for run in runs] == ["forge-1"]
        else:
            assert rig.llm.requests == [] and runs == []  # refused before the executor was entered (A1, F14)
```

Pair 11 of 13 (X7: a watcher is told of the decline):

SEARCH:
```python
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"[DECLINE_WORK {item_id}]\nOn the warp core all shift.\n[/DECLINE_WORK]",
```
REPLACE:
```python
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", origin.id) == item_id  # a watcher (A1, F8)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"[DECLINE_WORK {item_id}]\nOn the warp core all shift.\n[/DECLINE_WORK]",
```

Pair 12 of 13:

SEARCH:
```python
        assert "declined" in relay and "warp core" in relay and "@Pulaski" in relay
```
REPLACE:
```python
        assert "declined" in relay and "warp core" in relay and "@Pulaski" in relay and "@Ogawa" in relay
```

Pair 13 of 13 (X12 through the real router; X13 to X21):

SEARCH:
```python
# X12
async def test_an_ordinary_item_still_resumes_through_the_work_item_router(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        dispatched: list[str] = []

        class _Router:
            async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
                dispatched.append(wi["id"])
                return True

            def is_dispatchable(self, wi: dict[str, Any]) -> bool:
                return True

        rig.runtime.work_item_router = _Router()
        plain = await rig.store.create_work_item(title="Plain task", assigned_to="forge-1")
        asked = await rig.requests.file_request(agent_id="forge-1", kind="continue", target="continue", work_item_id=plain.id)
        assert await rig.driver.block_on_request(work_item_id=plain.id, request_id=asked.id, reason="waiting")
        await rig.requests.decide(asked.id, True)
        await rig.requests.mark_fulfilled(asked.id)
        await _pump(rig)
        assert dispatched == [plain.id]
        assert rig.llm.requests == [] and rig.runner.running == ()
```
REPLACE:
```python
# X12
async def test_an_ordinary_item_still_resumes_through_the_work_item_router(tmp_path: Path) -> None:
    """Regression, through the real ``WorkItemRouter`` (A1, F14): a dispatchable item resumes into one admission at the
    activation queue (the dispatcher records it); a tagless item is the negative control the router declines."""
    async with _rig(tmp_path, []) as rig:
        queue = _Dispatcher()
        hybrid = HybridDispatchConfig()
        rig.runtime.work_item_router = WorkItemRouter(
            dispatcher=queue, department_dispatcher=DepartmentDispatcher(hebbian_router=None, ontology=None, config=hybrid),
            registry=rig.runtime.registry, config=hybrid,
        )
        for title, tags, admitted in (("Consult", ["consultation"], 1), ("Plain task", [], 0)):
            plain = await rig.store.create_work_item(title=title, assigned_to="forge-1", tags=tags)
            asked = await rig.requests.file_request(agent_id="forge-1", kind="continue", target="continue", work_item_id=plain.id)
            assert await rig.driver.block_on_request(work_item_id=plain.id, request_id=asked.id, reason="waiting")
            await rig.requests.decide(asked.id, True)
            await rig.requests.mark_fulfilled(asked.id)
            await _pump(rig)
            assert [event.source_id for event in queue.events].count(plain.id) == admitted, title
        assert rig.llm.requests == [] and rig.runner.running == ()


_WIRE = _REPO / "ui" / "e2e" / "fixtures" / "ad1347-agent-work-approvals.json"


# X13
async def test_an_agent_work_approval_crosses_the_hxi_wire_fulfilled_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F1): the route's real envelopes are the shared fixture the HXI decoder test reads
    (``ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts``); only the call bound to its own item is fulfillable."""
    from probos.agent_work_runner import approval_payload

    ids = itertools.count(1)
    monkeypatch.setattr(request_module, "uuid", SimpleNamespace(uuid4=lambda: f"00000000-0000-0000-0000-{next(ids):012d}"))
    monkeypatch.setattr(request_module, "time", SimpleNamespace(time=lambda: 1000.0))
    wire = json.loads(_WIRE.read_text(encoding="utf-8"))
    requests = CapabilityRequestStore(db_path=str(tmp_path / "requests.db"))
    await requests.start()
    try:
        captain = SimpleNamespace(capability_request_store=requests)
        rationale = "agent work wi-agent called hull_survey, outside the read-only set"
        first = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 2}, "wi-agent-work-1"), rationale=rationale,
            work_item_id="wi-agent-work-1",
        )
        assert await list_actionable_capability_requests(captain) == wire["pending"]
        assert await decide_capability_request(first.id, CapabilityRequestDecideRequest(approve=True), runtime=captain) == wire["fulfilled"]
        second = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 3}, "wi-agent-work-1"), rationale=rationale,
            work_item_id="wi-agent-work-1",
        )
        await requests.decide(second.id, True)  # approved; its fulfilment has not happened yet
        assert await list_actionable_capability_requests(captain) == wire["approved"]
        retried = await decide_capability_request(second.id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert retried["fulfilled"] is True and (await list_actionable_capability_requests(captain))["requests"] == []
        stored = await requests.get(second.id)
        assert stored is not None
        bound = replace(stored, status="approved")
        assert can_fulfil_request(bound)
        for unbound in (
            replace(bound, work_item_id="wi-other"), replace(bound, work_item_id=None),
            replace(bound, payload={**bound.payload, "action": "click"}),
        ):
            assert not can_fulfil_request(unbound)
    finally:
        await requests.stop()


# X14
async def test_an_approval_that_settles_before_the_run_parks_still_runs_the_call_once(tmp_path: Path) -> None:
    """A1 (F2): the Captain approves while the run that filed the call is still finishing; BF-878 resumes the item at
    the park, and that start, made during the run, runs after it."""
    holder: dict[str, Any] = {}

    async def _approve_then_answer(request: LLMRequest) -> LLMResponse:
        rig = holder["rig"]
        [asked] = await rig.requests.list_pending()
        captain = SimpleNamespace(capability_request_store=rig.requests)
        assert (await decide_capability_request(asked.id, CapabilityRequestDecideRequest(approve=True), runtime=captain))["fulfilled"]
        settled = list(rig.request_events)
        rig.request_events.clear()
        for kind, data in settled:  # the driver hears both events now, while the item is not yet parked
            await rig.driver.on_capability_event({"type": getattr(kind, "value", kind), "data": data})
        return _final("Waiting for the Captain.")

    script = [_call("hull_survey", {}), _approve_then_answer, _call("hull_survey", {}), _final("Surveyed once.")]
    async with _rig(tmp_path, script) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey the hull", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done" and rig.survey.calls == 1
        assert len(rig.llm.requests) == 4
        [report] = _system_posts(rig, origin.id)
        assert "Surveyed once." in report


# X15
async def test_an_admitted_confined_call_is_not_parked_again_by_the_approval_inbox(tmp_path: Path) -> None:
    """A1 (F3): with AD-1154's inbox armed (the live configuration), the one call a confinement admits runs; credential
    entry stays refused; a call the confinement files never reaches the inbox."""
    executor, tool, store = await _armed(tmp_path, page=_FakePage(list_elements=[{"role": "button", "text": "Pay now"}]))
    verdict = {"now": "admit"}

    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        return verdict["now"]

    try:
        session_id = await _open_session(executor, tool, _TIER_3_URL)
        executor.confine_calls(ToolCallConfinement(AGENT_WORK_READ_TOOL_IDS, gate))
        await _invoke(executor, {"action": "click", "index": 0, "session_id": session_id})
        assert len(tool.invocations) == 1 and await store.list_pending() == []
        credential = await _invoke(executor, {"action": "fill_credential", "session_id": session_id})
        assert agentic_dispatch._APPROVAL_CREDENTIAL_REFUSAL in (credential.error or "") and len(tool.invocations) == 1
        verdict["now"] = "filed"
        filed = await _invoke(executor, {"action": "click", "index": 0, "session_id": session_id})
        assert CONFINED_CALL_FILED in (filed.error or "") and len(tool.invocations) == 1
        assert await store.list_pending() == []
    finally:
        await store.stop()
        await tool.stop()


# X16
async def test_an_item_the_executor_parked_itself_stays_parked_with_its_booking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F3's remaining parking outcome): a run AD-1324 parked on its own tier-floor ask (``parked_request_id``) is
    neither done nor released; its claimant keeps the booking until the ask is decided."""
    holder: dict[str, Any] = {}

    async def _tier_floor_parks(kwargs: dict[str, Any], outcome: Any) -> Any:
        rig = holder["rig"]
        item_id = kwargs["work_item_id_provider"]()
        ask = await rig.requests.file_request(agent_id=kwargs["agent_id"], kind="continue", target="continue", work_item_id=item_id)
        # as file_tier_floor_request(park=True) does from inside the executor
        assert await rig.driver.block_on_request(work_item_id=item_id, request_id=ask.id, reason="tier floor")
        holder["ask"] = ask.id
        outcome.stopped_reason, outcome.parked_request_id = "tier_floor_unavailable", ask.id
        return outcome

    _watch_runs(monkeypatch, then=_tier_floor_parks)
    async with _rig(tmp_path, [_final()]) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("blocked", "forge-1")
        assert item.metadata["capability_request_id"] == holder["ask"]
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["active"]
        assert _system_posts(rig, origin.id) == []


# X17
@pytest.mark.parametrize("stop", ["error", "empty"])
async def test_a_run_that_stops_without_a_finished_answer_fails_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str,
) -> None:
    """A1 (F4): only a run that completed with an answer is done; an error (as the step limit or the token budget) and
    an empty answer fail, and the report names the stop instead of saying "is done"."""
    async def _provider_down(request: LLMRequest) -> LLMResponse:
        raise RuntimeError("provider down")

    runs = _watch_runs(monkeypatch)
    async with _rig(tmp_path, [_provider_down] if stop == "error" else [_final("")]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        expected = "error" if stop == "error" else "complete"
        assert [run["outcome"].stopped_reason for run in runs] == [expected]  # the premise: the executor's own stop
        ended = await rig.store.get_work_item(created.work_item.id)
        assert ended is not None and ended.status == "failed"
        assert ended.metadata["agent_work_result"]["stopped"] == expected
        [report] = _system_posts(rig, origin.id)
        assert "is done" not in report and "ended as failed: the run " in report


# X18
async def test_a_claimant_stopped_after_it_filed_a_call_returns_the_request_to_the_board(tmp_path: Path) -> None:
    """A1 (F5): the stop lands after the call was filed and before the run returns; the request goes back to the board
    unclaimed with its booking cancelled, never parked; the filed call stays on the Captain's queue, inert."""
    holder: dict[str, Any] = {}

    async def _stop_then_answer(request: LLMRequest) -> LLMResponse:
        await holder["rig"].stops.issue_stop("forge-1", reason=STOP_REASON)
        return _final("Waiting for the Captain.")

    async with _rig(tmp_path, [_call("hull_survey", {}), _stop_then_answer]) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert "capability_request_id" not in item.metadata and rig.survey.calls == 0
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["cancelled"]
        [filed] = await rig.requests.list_pending()
        assert (filed.work_item_id, filed.payload["tool_id"]) == (item_id, "hull_survey")


# X19
async def test_a_decline_whose_notice_cannot_be_posted_does_not_say_it_was_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F9's literal): the decliner is told the truth when neither the thread nor the channel took the post."""
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)

        async def _down(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("the Ward Room is down")

        monkeypatch.setattr(rig.wr, "create_post", _down)
        monkeypatch.setattr(rig.wr, "create_thread", _down)
        outcome, said = await rig.runner.decline("forge-1", item_id, "On the warp core.")
        assert outcome == "declined" and "could not be posted" in said and "told" not in said


# X20
async def test_the_activation_notice_states_the_configured_ttl(tmp_path: Path) -> None:
    """A1 (F13): the notice names the TTL the store applies, never rounded up to an hour."""
    from probos.agent_work_runner import ttl_words

    assert [ttl_words(seconds) for seconds in (60, 90, 5_400, 86_400)] == ["1 min", "90 s", "90 min", "24 h"]
    async with _rig(tmp_path, [], section=AgentWorkConfig(enabled=True, ttl_seconds=60)) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert "it expires 1 min after it was asked" in notice.body


# X21
def test_a_confirmation_token_is_never_recorded_in_an_approval() -> None:
    """A1 (F15): AD-1154 strips a browser confirmation token before filing (BF-682); the agent-work gate does the same,
    and the approved call's identity does not depend on the token."""
    from probos.agent_work_runner import APPROVAL_UNRECORDED_PARAMS, approval_payload

    assert APPROVAL_UNRECORDED_PARAMS == agentic_dispatch._APPROVAL_PARAM_STRIP_KEYS
    with_token = approval_payload("browser", {"action": "click", "index": 0, "confirmation_token": "tok-1"}, "wi-1")
    assert with_token is not None and "confirmation_token" not in with_token["params"]
    assert with_token == approval_payload("browser", {"action": "click", "index": 0}, "wi-1")
```

### 7.32 `src/probos/agent_work_tags.py` (M2, A2: F16, F17, the inert-region and block grammar)

Pair 1 of 4:

SEARCH:
```python
Reading (A1, review round 1): names are read in any letter case and every marker is removed, closers included. A
marker in a code fence or on a Markdown quote line (``>``) is an example or a quotation: removed, never acted on. A
block that holds another marker (nested or broken) is removed whole and not acted on. One pass reads the markers, each
at most 160 characters to its bracket, so the work is linear in the reply. A fault on one tag is acknowledged, never
retried, and the rest of the reply goes on.
```
REPLACE:
```python
Reading (A1, review round 1; A2, round 2; A2b; A2c; A2d, round 3): names are read in any letter case and every marker
is removed, closers included. A marker in an inert region is an example or a quotation: removed alone, never acted on,
and no part of any block. The inert regions (``_inert_spans``, after CommonMark 0.31.2 with the differences contract
section 9 names): a code fence, from a line opening a run of three or more backticks or tildes to a line holding only a
run of the same character at least as long (an unclosed one runs to the end), with indentation read both at the top
level and as in a list item, at the item's content column (``_item_columns``); an indented code block, and the rest of
a list item's first line after five or more columns of padding; a line whose first character other than whitespace,
after any list item markers, is ``>`` (A2f); an inline code span within one line. A line ends at LF, CRLF or CR. A
block holds every block opened inside it and is closed only by its own closer once those are closed; a block that
holds any other marker is removed whole and not acted on. One pass reads the lines and the markers, each marker at
most 160 characters to its bracket, so the work is linear in the reply. A fault on one tag is acknowledged, never
retried, and the rest of the reply goes on.
```

Pair 2 of 4:

SEARCH:
```python
#: A1 (F7, F11): every agent-work marker, opener or closer, in any letter case: ``[NAME]``, ``[/NAME]`` or
#: ``[NAME <attribute>]``, on one line with at most 160 characters before its bracket, so one scan reads each
#: character a bounded number of times.
_MARKER_RE: Final = re.compile(
    r"\[(/?)(SELF_TASK|REQUEST_WORK|CLAIM_WORK|DECLINE_WORK)\b([^\]\n]{0,160})\]", re.IGNORECASE,
)
_ITEM_ID_RE: Final = re.compile(r"[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*")
#: A1 (F6): a Markdown code fence line (up to three spaces, then three backticks or three tildes).
_FENCE_RE: Final = re.compile(r"[ \t]{0,3}(?:`{3}|~{3})")
_BLOCK_NAMES: Final[frozenset[str]] = frozenset({"SELF_TASK", "REQUEST_WORK"})
```
REPLACE:
```python
#: A1 (F7, F11): every agent-work marker, opener or closer, in any letter case: ``[NAME]``, ``[/NAME]`` or
#: ``[NAME <attribute>]``, on one line (A2: no LF or CR inside) with at most 160 characters before its bracket, so one
#: scan reads each character a bounded number of times.
_MARKER_RE: Final = re.compile(
    r"\[(/?)(SELF_TASK|REQUEST_WORK|CLAIM_WORK|DECLINE_WORK)\b([^\]\r\n]{0,160})\]", re.IGNORECASE,
)
_ITEM_ID_RE: Final = re.compile(r"[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*")
#: A2 (F16): a line and its ending, which is LF, CRLF or CR (CommonMark 0.31.2, 2.1); ``str.splitlines`` would also
#: end a line at U+2028 and other separators that a Markdown renderer shows as text.
_LINE_RE: Final = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
#: A2 (F16): a code fence line (CommonMark 0.31.2, 4.5): blanks, a run of three or more backticks or tildes, and the
#: rest of the line. A2b: its column decides which reading it opens or closes (``_inert_spans``).
_FENCE_RE: Final = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)")
#: A2b: the list item markers that start a line (CommonMark 0.31.2, 5.2), so a fence after a marker is read. A2c: a
#: marker may end the line (an empty item), so that item's content column is tracked too. A2d: the match ends with
#: the last marker and all of its padding, which ``_item_columns`` measures.
_LIST_ITEM_RE: Final = re.compile(r"(?:[ \t]*(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$))+")
#: A2b: a line a paragraph does not continue past, so a line indented four columns after it is indented code
#: (CommonMark 0.31.2, 4.1 to 4.4): an ATX heading, or one character of ``-*_=`` repeated, which also counts a setext
#: underline and a bare list marker (this errs toward inert).
_PARAGRAPH_END_RE: Final = re.compile(r" {0,3}(?:#{1,6}(?:[ \t].*)?|([-*_=])(?:[ \t]*\1)*[ \t]*)")
#: A2 (F16): a run of backticks, which opens or closes an inline code span (CommonMark 0.31.2, 6.1).
_TICKS_RE: Final = re.compile(r"`+")
_BACKTICK: Final = "\x60"  # a backtick, spelled so the mutation table can quote the lines that use it
_BLOCK_NAMES: Final[frozenset[str]] = frozenset({"SELF_TASK", "REQUEST_WORK"})
```

Pair 3 of 4:

SEARCH:
```python
@dataclass
class _OpenBlock:
    """A block opener the scan has not closed yet (A1)."""

    name: str
    item_id: str
    start: int
    body_start: int
    actionable: bool
    inner: list[tuple[int, int]] = field(default_factory=list)


def _inert_line_ends(text: str) -> list[tuple[int, bool]]:
    """(end offset, inert) of each line. Inert: inside a code fence or opening or closing one, or a Markdown quote line;
    a marker there is an example or a quotation (A1, F6)."""
    lines: list[tuple[int, bool]] = []
    fenced = False
    end = 0
    for line in text.splitlines(keepends=True):
        end += len(line)
        fence = _FENCE_RE.match(line) is not None
        lines.append((end, fenced or fence or line.lstrip().startswith(">")))
        fenced = fenced != fence
    return lines
```
REPLACE:
```python
@dataclass
class _OpenBlock:
    """A block opener the scan has not closed yet (A1). A2 (F17): ``open_names`` holds it and every block opened inside
    it, innermost last; only a closer of the innermost one closes a level, and the block ends when the last level does."""

    name: str
    item_id: str
    start: int
    body_start: int
    open_names: list[str]
    actionable: bool = True
    inner: list[tuple[int, int]] = field(default_factory=list)


def _code_spans(content: str, offset: int) -> list[tuple[int, int]]:
    """A2 (F16): the inline code spans of one line, as offsets into the text: from a run of backticks to the next run of
    exactly as many on the line (CommonMark 0.31.2, 6.1); a run with no such partner is text. Linear: one backward pass
    finds each run's partner."""
    runs = [(tick.start(), tick.end()) for tick in _TICKS_RE.finditer(content)]
    partner: list[int | None] = [None] * len(runs)
    latest: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        size = runs[index][1] - runs[index][0]
        partner[index] = latest.get(size)
        latest[size] = index
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        close = partner[index]
        if close is None:
            index += 1
            continue
        spans.append((offset + runs[index][1], offset + runs[close][0]))
        index = close + 1
    return spans


def _columns(prefix: str) -> int:
    """A2b: the columns ``prefix`` spans from the start of its line; a tab advances to the next multiple of four
    (CommonMark 0.31.2, 2.2)."""
    width = 0
    for char in prefix:
        width += 4 - width % 4 if char == "\t" else 1
    return width


def _item_columns(head: str, empty: bool) -> tuple[int, bool]:
    """A2d (F22, F23; CommonMark 0.31.2, 5.2): the content column of the list item that the last marker in ``head``
    starts, and whether the item starts with indented code. ``head`` ends with that marker and its padding. The column
    is the marker's end plus the padding, for one to four columns of it; it is the marker's end plus one when the item
    starts blank (``empty``: nothing follows the marker on its line) or when five or more columns of padding follow
    (``wide``), and then the rest of the line is indented code."""
    end = _columns(head.rstrip(" \t"))
    padding = _columns(head) - end
    wide = not empty and padding >= 5
    return (end + 1 if empty or wide else end + padding), wide


def _closes(fence: tuple[str, int], run: re.Match[str] | None) -> bool:
    """A2b: whether a fence line closes a fence of this character and run length (CommonMark 0.31.2, 4.5): only a
    run of the same character at least as long, with nothing after it but blanks. Both readings use it."""
    return (
        run is not None and run.group(1)[0] == fence[0]
        and len(run.group(1)) >= fence[1]
        and not run.group(2).strip(" \t")
    )


def _inert_spans(text: str) -> list[tuple[int, int]]:
    """A2 (F16), A2b, A2c: the (start, end) offsets, in order and apart, where a marker is an example or a quotation.

    One pass over the lines, read two ways at once: the scanner does not parse list items, so it cannot tell which
    reading holds, and a line is inert when either makes it so. In both, a code fence opens on a run of three or more
    backticks or tildes (after backticks, no other backtick on the line), also after list item markers, and closes on
    a line without a marker holding only a run of the same character at least as long; an unclosed one runs to the end
    of the text. The top-level reading is CommonMark's: a fence line starts within three columns, and a line indented
    four or more columns that does not continue a paragraph is indented code. The list reading opens a fence at any
    column (a fence in a list item is indented by the item). A2c (CommonMark 0.31.2, 5.2): the list reading tracks the
    last list item's content column, which a non-blank line left of it ends. A2d (F22, F23): the column is the last
    marker's (``_item_columns``); a marker line with five or more columns of padding is indented code, and no fence
    opens on it; an item with no content yet also ends at a blank line. Each fence has a floor, and a non-blank
    line left of it ends the fence before the line is read, so the line may open a new one. A list fence in a tracked
    item is floored at the item's column and closes within three columns of it; outside one it is floored at 0 within
    three columns, else three columns left of it and never below 2, and closes within three columns of itself. The
    top reading floors only a fence on a marker line. A line whose first character other than whitespace (A2f, F27:
    any), after any list item markers, is ``>`` is a quote and inert, and on any other line outside both readings'
    fences each inline code span is inert.
    """
    spans: list[tuple[int, int]] = []
    top_fence: tuple[tuple[str, int], int] | None = None
    list_fence: tuple[tuple[str, int], int, int] | None = None
    item_column: int | None = None
    item_empty: bool = False
    paragraph = False
    for line in _LINE_RE.finditer(text):
        start, end = line.span()
        content = line.group().rstrip("\r\n")
        item = _LIST_ITEM_RE.match(content)
        head = item.group() if item is not None else ""
        rest = content[len(head):]
        empty = bool(head) and not rest
        content_column, wide = _item_columns(head, empty) if head else (0, False)
        run = None if wide else _FENCE_RE.fullmatch(rest)  # A2d (F22): a wide line's rest is indented code
        closer = None if head else run
        blank = not content.strip(" \t")
        indent = _columns(content[: len(content) - len(content.lstrip(" \t"))])
        column = _columns(content[: len(head) + run.start(1)]) if run is not None else 0
        opened: tuple[str, int] | None = None
        if run is not None and not (run.group(1)[0] == _BACKTICK and _BACKTICK in run.group(2)):
            opened = (run.group(1)[0], len(run.group(1)))
        if list_fence is not None and not blank and indent < list_fence[2]:
            list_fence = None  # A2c: a line left of its item's content column ends the item
        if top_fence is not None and not blank and indent < top_fence[1]:
            top_fence = None  # A2c: likewise for a fence opened on a marker line
        if head and list_fence is None:
            item_column, item_empty = content_column, empty
        # A2d (F23): an item ends at a non-blank line left of its column, and an empty one at its first blank line
        elif item_column is not None and (item_empty if blank else indent < item_column):
            item_column = None
        elif not blank:
            item_empty = False  # A2d (F23): the item has content, so a blank line no longer ends it
        inert = top_fence is not None or list_fence is not None
        if list_fence is None and opened is not None:
            base = column if item_column is None else item_column
            floor = item_column if item_column is not None else (0 if column <= 3 else max(2, column - 3))
            list_fence, inert = (opened, base + 3, floor), True
        elif list_fence is not None and _closes(list_fence[0], closer) and column <= list_fence[1]:
            list_fence = None  # its closing fence
        if top_fence is not None:
            if _closes(top_fence[0], closer) and indent <= 3:
                top_fence = None  # its closing fence
        elif blank:
            paragraph = False  # a blank line ends a paragraph
        elif wide:
            paragraph, inert = False, True  # A2d (F22): the item starts with an indented code block
        elif opened is not None and column <= 3:
            top_fence, paragraph, inert = (opened, _columns(head)), False, True
        elif rest.lstrip().startswith(">"):  # A2f (F27): any whitespace; it can only make a line inert
            paragraph, inert = False, True
        elif indent >= 4:
            inert = inert or not paragraph
        else:
            paragraph = _PARAGRAPH_END_RE.fullmatch(content) is None
        if inert:
            spans.append((start, end))
        else:
            spans.extend(_code_spans(content, start))
    return spans
```

Pair 4 of 4:

SEARCH:
```python
def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any marker.

    One pass over the markers (A1: F6, F7, F11). Names are read in any letter case. A marker on an inert line (a code
    fence, a quote) is removed and never acted on, and so is a block that holds another marker (nested or broken),
    which is removed whole. A closed block is removed whole; an unclosed opener, the markers after it and every stray
    marker are removed alone. A text with no marker is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    cuts: list[tuple[int, int]] = []
    lines = _inert_line_ends(text)
    line = 0
    block: _OpenBlock | None = None
    for match in _MARKER_RE.finditer(text):
        while lines[line][0] <= match.start():
            line += 1
        inert = lines[line][1]
        closer, name, attribute = match.group(1) == "/", match.group(2).upper(), match.group(3)
        item_id = _ITEM_ID_RE.fullmatch(attribute) if not closer and name in ("CLAIM_WORK", "DECLINE_WORK") else None
        if block is not None:
            if closer and name == block.name and not attribute.strip():
                if block.actionable:
                    tags.append(_block_tag(block, text[block.body_start:match.start()]))
                cuts.append((block.start, match.end()))
                block = None
            else:
                block.actionable = False
                block.inner.append((match.start(), match.end()))
            continue
        if (not closer and name in _BLOCK_NAMES and not attribute.strip()) or (item_id is not None and name == "DECLINE_WORK"):
            block = _OpenBlock(name, item_id.group(1) if item_id is not None else "", match.start(), match.end(), not inert)
            continue
        if item_id is not None and not inert:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=item_id.group(1)))
        cuts.append((match.start(), match.end()))
```
REPLACE:
```python
def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any marker.

    One pass over the markers (A1: F6, F7, F11; A2: F16, F17). Names are read in any letter case. A marker in an inert
    region (``_inert_spans``: a fence, indented code, a quote line, a code span) is removed alone, never acted on, and is
    no part of any block. A block opened outside one holds every block opened inside it and is closed only by its own
    closer once each of those is closed; a block that holds any other marker is removed whole and not acted on. An
    unclosed block's opener and the markers after it, and every stray marker, are removed alone. A text with no marker
    is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    cuts: list[tuple[int, int]] = []
    spans = _inert_spans(text)
    span = 0
    block: _OpenBlock | None = None
    for match in _MARKER_RE.finditer(text):
        while span < len(spans) and spans[span][1] <= match.start():
            span += 1
        inert = span < len(spans) and spans[span][0] <= match.start()
        closer, name, attribute = match.group(1) == "/", match.group(2).upper(), match.group(3)
        item_id = _ITEM_ID_RE.fullmatch(attribute) if not closer and name in ("CLAIM_WORK", "DECLINE_WORK") else None
        opener = (not closer and name in _BLOCK_NAMES and not attribute.strip()) or (item_id is not None and name == "DECLINE_WORK")
        if block is not None:
            closes = closer and not inert and not attribute.strip()
            if closes and name == block.open_names[-1]:
                block.open_names.pop()
                if not block.open_names:
                    if block.actionable:
                        tags.append(_block_tag(block, text[block.body_start:match.start()]))
                    cuts.append((block.start, match.end()))
                    block = None
                    continue
            elif not inert and opener:
                block.open_names.append(name)
            block.actionable = False
            block.inner.append((match.start(), match.end()))
            continue
        if opener and not inert:
            block = _OpenBlock(name, item_id.group(1) if item_id is not None else "", match.start(), match.end(), [name])
            continue
        if item_id is not None and not inert:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=item_id.group(1)))
        cuts.append((match.start(), match.end()))
```

### 7.33 `src/probos/capability_request.py` (M2, A2: F21, the docstring)

SEARCH:
```python
    Bound to its own item: the scope is ``agent_work:`` and the request's ``work_item_id``. Its approval is its own
    fulfilment (the approval route marks it fulfilled and AD-855 resumes the item), so it is fulfillable, as the repair
    action is; every other action still has no fulfiller. The HXI's ``canFulfil`` (``ui/src/store/capabilityApprovals.ts``)
    mirrors this exactly: ``can_retry_fulfilment`` must agree on both sides.
```
REPLACE:
```python
    Bound to its own item: the scope is ``agent_work:`` and the request's ``work_item_id``. Its approval is its own
    fulfilment (the approval route marks it fulfilled and AD-855 resumes the item), so it is fulfillable, as the repair
    action is. A2 (F21): other action subtypes are unchanged by this predicate; an AD-1328 command escalation has its
    own fulfiller (``execution/command_escalation.py``) and stays outside it. The HXI's ``canFulfil``
    (``ui/src/store/capabilityApprovals.ts``) mirrors this predicate and ``validate_action_payload`` beneath it, and
    ``ui/e2e/fixtures/ad1347-action-payload-rows.json`` holds the rows both sides are tested on (A2, F19).
```

### 7.34 `src/probos/routers/capability_requests.py` (M2, A2: F20, and no standing rule on an agent-work approval)

Pair 1 of 2:

SEARCH:
```python
        # approval). A denial does nothing here: AD-855 cancels the item on the DECIDED event.
        if not approve:
            return False
        return await store.mark_fulfilled(decided.id) is not None
```
REPLACE:
```python
        # approval). A denial does nothing here: AD-855 cancels the item on the DECIDED event.
        if not approve:
            return False
        try:
            return await store.mark_fulfilled(decided.id) is not None
        except Exception:  # A2 (F20): the approval stands and stays retryable
            logger.warning(
                "AD-1347: marking agent-work approval %s fulfilled failed; the decision stands and the approval "
                "can be retried", decided.id[:12], exc_info=True,
            )
            return False
```

Pair 2 of 2:

SEARCH:
```python
    if command_approval_request(decided) is not None:  # AD-1328 S2b: no standing rule
```
REPLACE:
```python
    if agent_work_approval(decided):  # AD-1347 S3 A2: one exact call per approval; no standing rule
        logger.info(
            "AD-1347: agent-work request %s cannot grant a standing rule; the agent-work confinement admits one "
            "exact call per approval and never reads a standing rule", decided.id[:12],
        )
        return None
    if command_approval_request(decided) is not None:  # AD-1328 S2b: no standing rule
```

### 7.35 `ui/src/store/capabilityApprovals.ts` (M2, A2: F18, F19)

Pair 1 of 2:

SEARCH:
```ts
export function standingApprovalEligible(request: CapabilityApprovalView): boolean {
  return request.status === 'pending' && ['action', 'continue'].includes(request.kind)
    && request.payload?.tool_id !== 'repair';
}
```
REPLACE:
```ts
/** AD-1347 S3 A2: no standing approval for an agent-work call. Its confinement admits one exact call per approval and
 * never reads a standing rule, and the approval route issues none. */
export function standingApprovalEligible(request: CapabilityApprovalView): boolean {
  return request.status === 'pending' && ['action', 'continue'].includes(request.kind)
    && request.payload?.tool_id !== 'repair' && !isAgentWorkApproval(request);
}
```

Pair 2 of 2:

SEARCH:
```ts
/** AD-1347 S3 A1 (F1): one tool call in one agent-created work item, bound to it by its scope. Its approval is its
 * own fulfilment. Mirrors Python's `agent_work_call` (src/probos/capability_request.py) exactly:
 * `can_retry_fulfilment` must agree on both sides, or every row of the actionable queue is refused. */
function isAgentWorkCall(payload: Record<string, unknown>, workItemId: unknown): boolean {
  return payload.action === 'agent_work_call' && typeof workItemId === 'string' && workItemId !== ''
    && payload.scope_key === 'agent_work:' + workItemId;
}

function canFulfil(kind: unknown, payload: unknown, workItemId: unknown): boolean {
  if (FULFILMENT_KINDS.has(String(kind))) return true;
  if (kind !== 'action' || !isRecord(payload)) return false;
  const keys = ['tool_id', 'action', 'params', 'scope_key', 'session_id', 'thread_id'];
  if (Object.keys(payload).length === keys.length && keys.every(key => key in payload) && isAgentWorkCall(payload, workItemId)) return true;
```
REPLACE:
```ts
/** AD-1347 S3 A2 (F19): Python's `validate_action_payload` (src/probos/capability_request.py) as the decoded wire shows
 * it: exactly the six keys, each of its type and within its bound, valid Unicode throughout, and at most 4,000
 * characters with each number counted as one. That size bound is exact for text and only a necessary one for numbers,
 * whose Python spelling the decoded value does not keep; Python serves no payload it rejected (contract section 9). */
function isActionWirePayload(payload: Record<string, unknown>): boolean {
  if (Object.keys(payload).length !== ACTION_KEYS.length || !ACTION_KEYS.every(key => key in payload)
    || typeof payload.tool_id !== 'string' || !/^[a-z0-9_:.-]{1,64}$/.test(payload.tool_id)
    || typeof payload.action !== 'string' || !/^[a-z0-9_]{1,64}$/.test(payload.action)
    || !isRecord(payload.params) || Object.keys(payload.params).length > 20
    || !validText(payload.scope_key, 253) || !validText(payload.thread_id, 64)
    || !(payload.session_id === null || validText(payload.session_id, 64))) return false;
  try {
    return hasPossibleActionPayloadSize(payload); // A2 (F19): the size and Unicode of Python's canonical form
  } catch {
    return false;
  }
}

/** AD-1347 S3 A1 (F1), A2 (F19): one tool call in one agent-created work item, bound to it by its scope. Its approval
 * is its own fulfilment. Mirrors Python's `agent_work_call` exactly, payload validation included; both sides are
 * tested on the rows of `ui/e2e/fixtures/ad1347-action-payload-rows.json`. */
function isAgentWorkCall(payload: Record<string, unknown>, workItemId: unknown): boolean {
  return isActionWirePayload(payload) && payload.action === 'agent_work_call'
    && typeof workItemId === 'string' && workItemId !== ''
    && payload.scope_key === 'agent_work:' + workItemId;
}

/** AD-1347 S3 A2 (F18): a validated agent-work call bound to its own item. Approving it resumes that item. */
export function isAgentWorkApproval(request: CapabilityApprovalView): boolean {
  return request.kind === 'action' && isRecord(request.payload) && isAgentWorkCall(request.payload, request.work_item_id);
}

function canFulfil(kind: unknown, payload: unknown, workItemId: unknown): boolean {
  if (FULFILMENT_KINDS.has(String(kind))) return true;
  if (kind !== 'action' || !isRecord(payload)) return false;
  const keys = ['tool_id', 'action', 'params', 'scope_key', 'session_id', 'thread_id'];
  if (isAgentWorkCall(payload, workItemId)) return true;
```

### 7.36 `ui/src/components/capability/CapabilityRequestCard.tsx` (M2, A2: F18)

Pair 1 of 3:

SEARCH:
```ts
import {
  approvalDisplayText, capabilityFeedbackText, formatApprovalPayload, inspectActionPayload,
  standingApprovalEligible, standingApprovalPolicy,
} from '../../store/capabilityApprovals';
```
REPLACE:
```ts
import {
  approvalDisplayText, capabilityFeedbackText, formatApprovalPayload, inspectActionPayload, isAgentWorkApproval,
  standingApprovalEligible, standingApprovalPolicy,
} from '../../store/capabilityApprovals';
```

Pair 2 of 3:

SEARCH:
```ts
  const ordinary = expected?.kind === 'action' && expected.payload?.tool_id !== 'repair';
```
REPLACE:
```ts
  const ordinary = expected?.kind === 'action' && expected.payload?.tool_id !== 'repair';
  // AD-1347 S3 A2 (F18): approving a validated agent-work call resumes its item, so it is not "decision only".
  const agentWork = expected !== undefined && isAgentWorkApproval(expected);
```

Pair 3 of 3:

SEARCH:
```ts
      {ordinary && <p>Approval records this decision only; it does not replay the original action.</p>}
```
REPLACE:
```ts
      {ordinary && !agentWork && <p>Approval records this decision only; it does not replay the original action.</p>}
      {agentWork && <p>Approval resumes work item {approvalDisplayText(expected.work_item_id ?? '')}. If its run makes this
        call again, with this tool and exactly these parameters, that call is admitted once, subject to the remaining
        guards; nothing runs from here.</p>}
```

### 7.37 New file: `ui/e2e/fixtures/ad1347-action-payload-rows.json` (M2, A2: F19; X22 asserts each row is Python's answer)

```json
{
  "about": "AD-1347 S3 A2 (F19): action payload rows with Python's answers (tests/test_ad1347_s3_execution.py X22), which the HXI must give too (ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts). Each row is an approved request of agent forge-1. A row's fill sets one field to that many x characters before it is read: tool_id, thread_id or session_id in the payload, note in its params, or work_item_id (and the payload's scope_key, agent_work: plus it).",
  "rows": [
    {"name": "bound_call", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": true, "agent_work_call": true},
    {"name": "other_item", "kind": "action", "work_item_id": "wi-other", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "unlinked", "kind": "action", "work_item_id": null, "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "empty_item", "kind": "action", "work_item_id": "", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "ordinary_action", "kind": "action", "work_item_id": null, "payload": {"tool_id": "browser", "action": "click", "params": {"selector": "#send"}, "scope_key": "example.test", "session_id": null, "thread_id": "thread-a"}, "fulfillable": false, "agent_work_call": false},
    {"name": "null_payload", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": null, "fulfillable": false, "agent_work_call": false},
    {"name": "missing_key", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null}, "fulfillable": false, "agent_work_call": false},
    {"name": "extra_key", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": "", "extra": 1}, "fulfillable": false, "agent_work_call": false},
    {"name": "tool_id_number", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": 7, "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "tool_id_grammar", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "Hull Survey!", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "action_number", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": 7, "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "action_grammar", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "Agent Work!", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "tool_id_64", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "tool_id", "chars": 64}, "fulfillable": true, "agent_work_call": true},
    {"name": "tool_id_65", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "tool_id", "chars": 65}, "fulfillable": false, "agent_work_call": false},
    {"name": "params_array", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": [], "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "params_text", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": "depth", "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "params_20_keys", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"k01": 1, "k02": 1, "k03": 1, "k04": 1, "k05": 1, "k06": 1, "k07": 1, "k08": 1, "k09": 1, "k10": 1, "k11": 1, "k12": 1, "k13": 1, "k14": 1, "k15": 1, "k16": 1, "k17": 1, "k18": 1, "k19": 1, "k20": 1}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": true, "agent_work_call": true},
    {"name": "params_21_keys", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"k01": 1, "k02": 1, "k03": 1, "k04": 1, "k05": 1, "k06": 1, "k07": 1, "k08": 1, "k09": 1, "k10": 1, "k11": 1, "k12": 1, "k13": 1, "k14": 1, "k15": 1, "k16": 1, "k17": 1, "k18": 1, "k19": 1, "k20": 1, "k21": 1}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "scope_253", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "work_item_id", "chars": 242}, "fulfillable": true, "agent_work_call": true},
    {"name": "scope_254", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "work_item_id", "chars": 243}, "fulfillable": false, "agent_work_call": false},
    {"name": "thread_64", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "thread_id", "chars": 64}, "fulfillable": true, "agent_work_call": true},
    {"name": "thread_65", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "thread_id", "chars": 65}, "fulfillable": false, "agent_work_call": false},
    {"name": "thread_null", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": null}, "fulfillable": false, "agent_work_call": false},
    {"name": "session_text", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": "s-1", "thread_id": ""}, "fulfillable": true, "agent_work_call": true},
    {"name": "session_64", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "session_id", "chars": 64}, "fulfillable": true, "agent_work_call": true},
    {"name": "session_65", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "session_id", "chars": 65}, "fulfillable": false, "agent_work_call": false},
    {"name": "session_number", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": 5, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "lone_surrogate", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"note": "\ud800"}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "size_3947", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"note": ""}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "note", "chars": 3800}, "fulfillable": true, "agent_work_call": true},
    {"name": "size_4047", "kind": "action", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"note": ""}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fill": {"field": "note", "chars": 3900}, "fulfillable": false, "agent_work_call": false},
    {"name": "repair_dispatch", "kind": "action", "work_item_id": null, "payload": {"tool_id": "repair", "action": "dispatch", "params": {"fault_id": "f-1", "signature": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}, "scope_key": "fault:f-1", "session_id": null, "thread_id": ""}, "fulfillable": true, "agent_work_call": false},
    {"name": "repair_bad_signature", "kind": "action", "work_item_id": null, "payload": {"tool_id": "repair", "action": "dispatch", "params": {"fault_id": "f-1", "signature": "zz"}, "scope_key": "fault:f-1", "session_id": null, "thread_id": ""}, "fulfillable": false, "agent_work_call": false},
    {"name": "grant", "kind": "grant", "work_item_id": null, "payload": null, "fulfillable": true, "agent_work_call": false},
    {"name": "install", "kind": "install", "work_item_id": null, "payload": null, "fulfillable": true, "agent_work_call": false},
    {"name": "build", "kind": "build", "work_item_id": null, "payload": null, "fulfillable": true, "agent_work_call": false},
    {"name": "continue", "kind": "continue", "work_item_id": null, "payload": null, "fulfillable": true, "agent_work_call": false},
    {"name": "continue_with_call_payload", "kind": "continue", "work_item_id": "wi-agent-work-1", "payload": {"tool_id": "hull_survey", "action": "agent_work_call", "params": {"depth": 2}, "scope_key": "agent_work:wi-agent-work-1", "session_id": null, "thread_id": ""}, "fulfillable": true, "agent_work_call": false}
  ]
}
```

### 7.38 New file: `ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts` (M2, A2: F19)

```ts
/**
 * AD-1347 S3 A2 (F19): the HXI reads every shared action-payload row as Python does. The expected answers are
 * Python's: tests/test_ad1347_s3_execution.py (X22) asserts each row through the real `can_fulfil_request` and
 * `agent_work_call`. A row's `fill` is applied here exactly as X22 applies it.
 */
import { describe, expect, it } from 'vitest';
import { isAgentWorkApproval, isCapabilityRequestView, parseCapabilityDecision } from '../capabilityApprovals';
import type { CapabilityApprovalView } from '../types';
import table from '../../../e2e/fixtures/ad1347-action-payload-rows.json';

interface Row {
  name: string;
  kind: string;
  work_item_id: string | null;
  payload: Record<string, unknown> | null;
  fill?: { field: string; chars: number };
  fulfillable: boolean;
  agent_work_call: boolean;
}

const rows = table.rows as unknown as Row[];

function view(row: Row, status: CapabilityApprovalView['status'], retry: boolean): CapabilityApprovalView {
  const payload = row.payload === null ? null : structuredClone(row.payload);
  let workItemId = row.work_item_id;
  if (row.fill && payload !== null) {
    const text = 'x'.repeat(row.fill.chars);
    if (row.fill.field === 'work_item_id') {
      workItemId = text;
      payload.scope_key = 'agent_work:' + text;
    } else if (row.fill.field === 'note') {
      (payload.params as Record<string, unknown>).note = text;
    } else {
      payload[row.fill.field] = text;
    }
  }
  return {
    id: '00000000-0000-0000-0000-000000000009', agent_id: 'forge-1', kind: row.kind, target: 'hull_survey',
    rationale: 'shared row', work_item_id: workItemId, status, created_at: 1000,
    decided_at: status === 'pending' ? null : 1000, decided_by: status === 'pending' ? '' : 'captain',
    decision_reason: '', payload, can_retry_fulfilment: retry,
  };
}

describe('AD-1347 A2 shared action-payload rows', () => {
  it('keeps an approved row retryable exactly when Python can fulfil it', () => {
    expect(rows.length).toBeGreaterThan(30);
    for (const row of rows) {
      expect([row.name, isCapabilityRequestView(view(row, 'approved', row.fulfillable))]).toEqual([row.name, true]);
      expect([row.name, isCapabilityRequestView(view(row, 'approved', !row.fulfillable))]).toEqual([row.name, false]);
      expect([row.name, isAgentWorkApproval(view(row, 'pending', false))]).toEqual([row.name, row.agent_work_call]);
    }
  });

  it('confirms a fulfilled decision exactly for the rows Python can fulfil', () => {
    for (const row of rows) {
      const pending = view(row, 'pending', false);
      let confirmed = true;
      try {
        parseCapabilityDecision({ request: view(row, 'fulfilled', false), standing_rule: null, fulfilled: true }, pending, true);
      } catch {
        confirmed = false;
      }
      expect([row.name, confirmed]).toEqual([row.name, row.fulfillable]);
    }
  });
});
```

### 7.39 New file: `ui/src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx` (M2, A2: F18)

```ts
/**
 * AD-1347 S3 A2 (F18): the card says what approving an agent-work call does and offers no standing approval for it;
 * an ordinary action keeps the ordinary copy and the standing choice (ApprovalWave.test.tsx pins that copy too).
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { CapabilityApprovalView } from '../../../store/types';
import { useSettingsStore } from '../../../store/useSettingsStore';
import { CapabilityRequestCard } from '../CapabilityRequestCard';
import wire from '../../../../e2e/fixtures/ad1347-agent-work-approvals.json';

const AGENT_WORK = wire.pending.requests[0] as unknown as CapabilityApprovalView;
const ORDINARY = {
  ...AGENT_WORK, id: '00000000-0000-0000-0000-000000000003', target: 'browser.click', work_item_id: null,
  payload: { tool_id: 'browser', action: 'click', params: { selector: '#send' },
    scope_key: 'example.test', session_id: null, thread_id: 'thread-a' },
} as CapabilityApprovalView;

beforeEach(() => { useSettingsStore.setState({ loaded: true, loading: false }); });
afterEach(() => { cleanup(); });

describe('AD-1347 agent-work approval card', () => {
  it('says an agent-work approval resumes its item and offers no standing approval; an ordinary action keeps both', () => {
    render(<CapabilityRequestCard requestId={AGENT_WORK.id} request={AGENT_WORK} />);
    expect(screen.queryByText(/does not replay the original action/)).toBeNull();
    expect(screen.getByText(/Approval resumes work item wi-agent-work-1\./)).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: 'Grant standing approval' })).toBeNull();
    cleanup();
    render(<CapabilityRequestCard requestId={ORDINARY.id} request={ORDINARY} />);
    expect(screen.getByText(/does not replay the original action/)).toBeTruthy();
    expect(screen.queryByText(/Approval resumes work item/)).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Grant standing approval' })).toBeTruthy();
  });
});
```

### 7.40 `tests/test_ad1347_s2_chain_tags.py` (M2, A2: C1's fenced case, C15, C17)

Pair 1 of 3:

SEARCH:
```python
    # A1 (F6): a fenced example and a quoted claim are stripped and never acted on.
    (f"Example syntax only:\n{FENCE}\n[SELF_TASK]\nTitle: x\n[/SELF_TASK]\n{FENCE}", [], f"Example syntax only:\n{FENCE}\n\n{FENCE}"),
```
REPLACE:
```python
    # A1 (F6): a fenced example and a quoted claim are stripped and never acted on. A2: an inert marker is removed
    # alone, so the example's text stays.
    (f"Example syntax only:\n{FENCE}\n[SELF_TASK]\nTitle: x\n[/SELF_TASK]\n{FENCE}", [], f"Example syntax only:\n{FENCE}\n\nTitle: x\n\n{FENCE}"),
```

Pair 2 of 3:

SEARCH:
```python
# C15
def test_repeated_unclosed_openers_are_parsed_in_one_bounded_pass() -> None:
    """A1 (F11): 66 KB of unclosed openers. The review measured 3.1 s for this shape before A1 (one rescan per opener)."""
    text = "[SELF_TASK]" * 6_000
    started = time.perf_counter()
    assert split_agent_work_tags(text) == ("", ())
    assert time.perf_counter() - started < 0.5
```
REPLACE:
```python
# C15
@pytest.mark.parametrize(("text", "cleaned"), [
    ("[SELF_TASK]" * 6_000, ""),
    ("[SELF_TASK]" * 6_000 + "[/SELF_TASK]" * 6_000, ""),
    (f"{FENCE}\n" + "[CLAIM_WORK wi-1]\n" * 3_500, FENCE),
    ("> [CLAIM_WORK wi-1]\n" * 3_000, ("> \n" * 3_000).strip()),
    ("`[CLAIM_WORK wi-1]` " * 3_000, ("`` " * 3_000).strip()),
    ("- " * 30_000 + "x", "- " * 30_000 + "x"),
], ids=["unclosed_openers", "nested_levels", "fenced_lines", "quote_lines", "code_spans", "list_markers"])
def test_repeated_unclosed_openers_are_parsed_in_one_bounded_pass(
    text: str, cleaned: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F11): 66 KB of unclosed openers. The review measured 3.1 s for this shape before A1 (one rescan per opener).
    A2 (F16, F17): the same bound over 6,000 nested levels, fence lines, quote lines and code spans, and each line is
    read for a fence exactly once (no rescan). A2b: and over one line of 30,000 list item markers."""
    lines = len(text.splitlines())
    reads = 0
    fence_re = tags_module._FENCE_RE

    def _read_once(content: str) -> Any:
        nonlocal reads
        reads += 1
        return fence_re.fullmatch(content)

    monkeypatch.setattr(tags_module, "_FENCE_RE", SimpleNamespace(fullmatch=_read_once))
    started = time.perf_counter()
    assert split_agent_work_tags(text) == (cleaned, ())
    assert time.perf_counter() - started < 0.5
    assert reads == lines
```

Pair 3 of 3:

SEARCH:
```python
        assert cleaned.startswith("Obs.") and "could not be confirmed" in cleaned and item.id[:8] in cleaned
        assert [action["outcome"] for action in actions if action.get("type") == "agent_work"] == ["error", "created"]
```
REPLACE:
```python
        assert cleaned.startswith("Obs.") and "could not be confirmed" in cleaned and item.id[:8] in cleaned
        assert [action["outcome"] for action in actions if action.get("type") == "agent_work"] == ["error", "created"]


TILDES = "~" * 3
LONG_FENCE = "`" * 4  # A2: a four-backtick fence, spelled as FENCE is
EXAMPLE = "[SELF_TASK]\nTitle: x\n[/SELF_TASK]"
REAL = "[SELF_TASK]\nTitle: Real\n[/SELF_TASK]"
REAL_TAG = AgentWorkTag("self_task", title="Real")


def _claim(work_item_id: str) -> AgentWorkTag:
    return AgentWorkTag("claim", work_item_id=work_item_id)


#: A2 (F16, F17): the inert-region and block grammar, one row per construct (CommonMark 0.31.2 with the differences
#: contract section 9 names; the out_of_scope rows are those differences, read as written). A2d (F25): every other
#: row's markers are where CommonMark puts them, so a row that quotes a line puts a blank line before the tag after it
#: (a line straight after a quote line continues the quote lazily, register R13).
GRAMMAR = [
    pytest.param(f"Ex:\n{FENCE}\n{EXAMPLE}\n{FENCE}\n{REAL}", [REAL_TAG], f"Ex:\n{FENCE}\n\nTitle: x\n\n{FENCE}", id="fence_backtick"),
    pytest.param(f"Ex:\n{TILDES}\n{EXAMPLE}\n{TILDES}\n{REAL}", [REAL_TAG], f"Ex:\n{TILDES}\n\nTitle: x\n\n{TILDES}", id="fence_tilde"),
    pytest.param(
        f"Ex:\n{FENCE}\n{TILDES}\n{EXAMPLE}\n{FENCE}\n{REAL}", [REAL_TAG], f"Ex:\n{FENCE}\n{TILDES}\n\nTitle: x\n\n{FENCE}",
        id="fence_tilde_inside_backtick_is_content",
    ),
    pytest.param(
        f"Ex:\n{LONG_FENCE}\n{FENCE}\n{EXAMPLE}\n{FENCE}\n{LONG_FENCE}\n{REAL}", [REAL_TAG],
        f"Ex:\n{LONG_FENCE}\n{FENCE}\n\nTitle: x\n\n{FENCE}\n{LONG_FENCE}", id="fence_shorter_run_inside_is_content",
    ),
    pytest.param(
        f"Ex:\n{FENCE}\n{FENCE}python\n{EXAMPLE}\n{FENCE}\n{REAL}", [REAL_TAG],
        f"Ex:\n{FENCE}\n{FENCE}python\n\nTitle: x\n\n{FENCE}", id="fence_line_with_info_inside_is_content",
    ),
    pytest.param(f"Ex:\n{FENCE}\n{EXAMPLE}\n{LONG_FENCE}\n{REAL}", [REAL_TAG], f"Ex:\n{FENCE}\n\nTitle: x\n\n{LONG_FENCE}", id="fence_longer_closer_closes"),
    pytest.param(f"Ex:\n{FENCE}\n{REAL}", [], f"Ex:\n{FENCE}\n\nTitle: Real", id="fence_unclosed_runs_to_the_end"),
    pytest.param(
        f"1. Example:\n    {FENCE}\n    [CLAIM_WORK wi-1]\n    {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"1. Example:\n    {FENCE}\n    \n    {FENCE}", id="fence_indented_in_a_list_item",
    ),
    pytest.param(f"{FENCE}\n[DECLINE_WORK wi-1] busy [/DECLINE_WORK]\n{FENCE}", [], f"{FENCE}\n busy \n{FENCE}", id="fenced_decline_is_not_acted_on"),
    pytest.param(
        f"{FENCE}inline{FENCE} then\n[CLAIM_WORK wi-3]", [_claim("wi-3")], f"{FENCE}inline{FENCE} then",
        id="backtick_run_with_a_backtick_after_is_a_code_span",
    ),
    pytest.param("> [CLAIM_WORK wi-1]\n\n[CLAIM_WORK wi-2]", [_claim("wi-2")], ">", id="quote_line"),
    pytest.param("   > [CLAIM_WORK wi-1]", [], ">", id="quote_line_indented"),
    pytest.param(f"> [SELF_TASK]\n\n{REAL}", [REAL_TAG], ">", id="quoted_opener_leaves_the_real_block_actionable"),
    pytest.param("Reply with `[CLAIM_WORK wi-1]` to take it.", [], "Reply with `` to take it.", id="code_span_claim"),
    pytest.param("Syntax: `[SELF_TASK] Title: x [/SELF_TASK]`", [], "Syntax: ` Title: x `", id="code_span_block"),
    pytest.param("`a` [CLAIM_WORK wi-4] `b`", [_claim("wi-4")], "`a`  `b`", id="text_between_two_spans_is_actionable"),
    pytest.param("`a`` [CLAIM_WORK wi-5] ``b", [], "`a``  ``b", id="span_closes_only_on_a_run_of_its_length"),
    pytest.param("It is `odd [CLAIM_WORK wi-6]", [_claim("wi-6")], "It is `odd", id="unmatched_backtick_is_text"),
    pytest.param(
        "[SELF_TASK]\nTitle: Outer\n[SELF_TASK]\nTitle: Inner\n[/SELF_TASK]\n[SELF_TASK]\nTitle: Tail\n[/SELF_TASK]\n[/SELF_TASK]",
        [], "", id="nested_tail",
    ),
    pytest.param(
        "[SELF_TASK]\nTitle: Outer\n[SELF_TASK]\nTitle: Inner\n[/SELF_TASK]\nafter", [],
        "Title: Outer\n\nTitle: Inner\n\nafter", id="unclosed_outer_with_a_closed_inner",
    ),
    pytest.param(
        "[SELF_TASK]\nTitle: a\n[/REQUEST_WORK]\n[/SELF_TASK]\n[CLAIM_WORK wi-7]", [_claim("wi-7")], "",
        id="closer_of_the_other_name_breaks_the_block",
    ),
    pytest.param(
        "[SELF_TASK]\nTitle: `[/SELF_TASK]` x\n[/SELF_TASK]\n[CLAIM_WORK wi-8]", [_claim("wi-8")], "",
        id="inert_closer_inside_a_block_breaks_it",
    ),
    pytest.param("Done [/SELF_TASK] [CLAIM_WORK wi-9]", [_claim("wi-9")], "Done", id="closer_without_opener_is_removed"),
    pytest.param(
        f"Ex:\r\n{FENCE}\r\n[CLAIM_WORK wi-1]\r\n{FENCE}\r\n[CLAIM_WORK wi-2]", [_claim("wi-2")], f"Ex:\r\n{FENCE}\r\n\r\n{FENCE}",
        id="crlf",
    ),
    pytest.param(f"Ex:\r{FENCE}\r[CLAIM_WORK wi-1]", [], f"Ex:\r{FENCE}", id="lone_cr_ends_a_line"),
    pytest.param(
        f"Ex:\n{FENCE}\nx\u2028{FENCE}\n[CLAIM_WORK wi-1]", [], f"Ex:\n{FENCE}\nx\u2028{FENCE}",
        id="unicode_line_separator_does_not_end_a_line",
    ),
    pytest.param("[SELF_TASK\r]\nTitle: x\n[/SELF_TASK]", [], "[SELF_TASK\r]\nTitle: x", id="marker_does_not_cross_a_line_end"),
    pytest.param("Example:\n\n    [CLAIM_WORK wi-1]", [], "Example:", id="indented_code_after_a_blank_line"),
    pytest.param("    [CLAIM_WORK wi-1]", [], "", id="indented_code_at_the_start"),
    pytest.param(f"Text\n{FENCE}\nx\n{FENCE}\n    [CLAIM_WORK wi-1]", [], f"Text\n{FENCE}\nx\n{FENCE}", id="indented_code_after_a_fence"),
    pytest.param("## Example\n    [CLAIM_WORK wi-1]", [], "## Example", id="indented_code_after_a_heading"),
    pytest.param("Text\n***\n    [CLAIM_WORK wi-1]", [], "Text\n***", id="indented_code_after_a_thematic_break"),
    pytest.param("Example:\n\n\t[CLAIM_WORK wi-1]", [], "Example:", id="indented_code_by_a_tab"),
    pytest.param("Text\n    [CLAIM_WORK wi-1]", [_claim("wi-1")], "Text", id="indented_line_continuing_a_paragraph_is_text"),
    pytest.param(
        f"{FENCE}\n    {FENCE}\n[CLAIM_WORK wi-1]", [], f"{FENCE}\n    {FENCE}",
        id="top_level_fence_four_column_line_inside_is_content",
    ),
    pytest.param(f"{FENCE}\n   {FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"{FENCE}\n   {FENCE}", id="top_level_closer_indented_three_closes"),
    pytest.param(
        f"   {FENCE}\n      {FENCE}\n[CLAIM_WORK wi-1]", [], f"{FENCE}\n      {FENCE}",
        id="top_level_closer_indented_four_does_not_close",
    ),
    pytest.param(f"    {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"{FENCE}\n{FENCE}", id="indented_code_then_a_top_level_fence"),
    pytest.param(
        f"1. Example:\n    {FENCE}\n            {FENCE}\n    [CLAIM_WORK wi-1]\n    {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"1. Example:\n    {FENCE}\n            {FENCE}\n    \n    {FENCE}", id="list_closer_more_than_three_past_its_opener_is_content",
    ),
    pytest.param(
        f"- {FENCE}\n  [CLAIM_WORK wi-1]\n  {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")], f"- {FENCE}\n  \n  {FENCE}",
        id="fence_on_a_list_marker_line",
    ),
    pytest.param(
        f"- {FENCE}\n  a\n- {FENCE}\n  [CLAIM_WORK wi-1]\n  {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"- {FENCE}\n  a\n- {FENCE}\n  \n  {FENCE}", id="new_list_item_fence_line_does_not_close",
    ),
    pytest.param("- > [CLAIM_WORK wi-1]\n\n[CLAIM_WORK wi-2]", [_claim("wi-2")], "- >", id="quote_in_a_list_item"),
    pytest.param(f"    {FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], FENCE, id="indented_fence_line_ends_at_an_unindented_line"),
    pytest.param(f"- {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"- {FENCE}\n{FENCE}", id="marker_line_fence_ends_at_an_unindented_fence_line"),
    pytest.param(
        f"- {FENCE}\n[CLAIM_WORK wi-1]\n   {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-1")], f"- {FENCE}\n\n   {FENCE}",
        id="marker_line_fence_ends_at_an_outdented_line",
    ),
    pytest.param(
        f"- {FENCE}\n> [CLAIM_WORK wi-1]\n  {LONG_FENCE}\n   [CLAIM_WORK wi-2]", [], f"- {FENCE}\n> \n  {LONG_FENCE}",
        id="fence_in_an_item_ends_at_a_quote",
    ),
    pytest.param(
        f"+ [CLAIM_WORK wi-1]\n   {FENCE}\n{FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-1")], f"+ \n   {FENCE}\n{FENCE}",
        id="continuation_fence_ends_at_an_outdented_fence_line",
    ),
    pytest.param(
        f"1. a\n   {FENCE}\n  {FENCE}\n[CLAIM_WORK wi-1]", [], f"1. a\n   {FENCE}\n  {FENCE}",
        id="outdented_fence_line_after_an_item_fence_opens_a_top_level_fence",
    ),
    pytest.param(f"1. a\n\n   {FENCE}\n  {FENCE}\n[CLAIM_WORK wi-1]", [], f"1. a\n\n   {FENCE}\n  {FENCE}", id="blank_line_keeps_the_list_item"),
    pytest.param(
        f"1. a\n    {FENCE}\n\n   [CLAIM_WORK wi-1]\n    {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"1. a\n    {FENCE}\n\n   \n    {FENCE}", id="blank_line_inside_a_list_fence_keeps_it_open",
    ),
    pytest.param(
        f"- {FENCE}\n\n  x\n  {FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"- {FENCE}\n\n  x\n  {FENCE}",
        id="blank_line_inside_a_marker_line_fence_keeps_it_open",
    ),
    pytest.param(f"-\n  {FENCE}\n {FENCE}\n[CLAIM_WORK wi-1]", [], f"-\n  {FENCE}\n {FENCE}", id="bare_marker_item_fence_ends_at_column_one"),
    pytest.param(f"{FENCE}\n- {FENCE}\n[CLAIM_WORK wi-1]\n{FENCE}", [], f"{FENCE}\n- {FENCE}\n\n{FENCE}", id="marker_line_inside_a_fence_is_content"),
    pytest.param(
        f"1. Example:\n    {FENCE}\n    x\n    {FENCE}\n   [CLAIM_WORK wi-1]", [_claim("wi-1")],
        f"1. Example:\n    {FENCE}\n    x\n    {FENCE}", id="text_after_a_list_fence_in_its_item_is_actionable",
    ),
    pytest.param(
        f"- a\n\n     {FENCE}\n      {FENCE}\n  [CLAIM_WORK wi-1]", [], f"- a\n\n     {FENCE}\n      {FENCE}",
        id="list_closer_counts_from_the_item_column",
    ),
    pytest.param(
        f"-     x\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"-     x\n  {FENCE}\n{FENCE}",
        id="padding_five_starts_the_item_with_indented_code",
    ),
    pytest.param(
        f"-    x\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"-    x\n  {FENCE}\n{FENCE}",
        id="padding_four_is_the_item_column",
    ),
    pytest.param(
        f"-      x\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"-      x\n  {FENCE}\n{FENCE}",
        id="padding_six_starts_the_item_with_indented_code",
    ),
    pytest.param(
        f"-\t\tx\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"-\t\tx\n  {FENCE}\n{FENCE}",
        id="tab_padding_is_counted_in_columns",
    ),
    pytest.param("-     [CLAIM_WORK wi-1]\n[CLAIM_WORK wi-2]", [_claim("wi-2")], "-", id="wide_padded_line_is_indented_code"),
    pytest.param(
        f"-     {FENCE}\n  [CLAIM_WORK wi-1]", [_claim("wi-1")], f"-     {FENCE}", id="fence_on_a_wide_padded_line_is_code_text",
    ),
    pytest.param(
        f"-\n\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"-\n\n  {FENCE}\n{FENCE}",
        id="empty_item_ends_at_a_blank_line",
    ),
    pytest.param(
        f"-\n\n\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"-\n\n\n  {FENCE}\n{FENCE}",
        id="empty_item_ends_at_two_blank_lines",
    ),
    pytest.param(
        f"- \n\n   {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"- \n\n   {FENCE}\n{FENCE}",
        id="empty_item_with_a_trailing_blank_ends_at_a_blank_line",
    ),
    pytest.param("-\n\n[CLAIM_WORK wi-1]", [_claim("wi-1")], "-", id="empty_item_then_a_plain_tag"),
    pytest.param(
        f"-\n  {FENCE}\n  x\n  {FENCE}\n\n  {FENCE}\n {FENCE}\n[CLAIM_WORK wi-1]", [],
        f"-\n  {FENCE}\n  x\n  {FENCE}\n\n  {FENCE}\n {FENCE}",
        id="empty_item_that_opens_a_fence_keeps_its_column_across_a_blank_line",
    ),
    pytest.param("\u00a0> [CLAIM_WORK wi-1]", [], ">", id="out_of_scope_nbsp_before_a_quote_mark_is_a_quote"),
    pytest.param("\u2003> [CLAIM_WORK wi-1]", [], ">", id="out_of_scope_em_space_before_a_quote_mark_is_a_quote"),
    pytest.param("- a\n \t> [CLAIM_WORK wi-1]", [], "- a\n \t>", id="tab_before_a_quote_mark_in_a_list_item_is_a_quote"),
    pytest.param(
        f"1. a\nlazy\n   {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"1. a\nlazy\n   {FENCE}\n{FENCE}",
        id="out_of_scope_lazy_line_then_an_item_fence_is_read_as_written",
    ),
    pytest.param("> Forge wrote:\n[CLAIM_WORK wi-1]", [_claim("wi-1")], "> Forge wrote:", id="out_of_scope_lazy_quote_continuation_is_read_as_written"),
    pytest.param(
        "> Forge wrote:\n\u00a0> [CLAIM_WORK wi-1]", [], "> Forge wrote:\n\u00a0>",
        id="nbsp_line_after_a_quote_is_quoted",
    ),
    pytest.param(
        "-     x\n    [CLAIM_WORK wi-1]", [], "-     x",
        id="out_of_scope_wide_item_paragraph_indented_four_is_read_as_written",
    ),
    pytest.param("`start\n[CLAIM_WORK wi-1]\nend`", [_claim("wi-1")], "`start\n\nend`", id="out_of_scope_span_across_lines_is_read_as_written"),
]


# C17
@pytest.mark.parametrize(("text", "expected", "cleaned"), GRAMMAR)
def test_every_inert_construct_and_block_form_is_read_as_the_grammar_says(
    text: str, expected: list[AgentWorkTag], cleaned: str,
) -> None:
    """A2 (F16, F17), A2b: each construct's tags and posted text. A marker in a fence, indented code, a quote or a span is
    removed alone and never acted on; a nested block stays one block until its own closer."""
    got, tags = split_agent_work_tags(text)
    assert list(tags) == expected
    assert got == cleaned
```

### 7.41 `tests/test_ad1347_s3_execution.py` (M2, A2: X22 to X24)

Pair 1 of 4:

SEARCH:
```python
import ast
import asyncio
import contextlib
import itertools
```
REPLACE:
```python
import ast
import asyncio
import contextlib
import copy
import itertools
```

Pair 2 of 4:

SEARCH:
```python
import probos.capability_request as request_module
from probos.agent_stop import AgentStopService
```
REPLACE:
```python
import probos.capability_request as request_module
import probos.routers.capability_requests as route_module
from probos.agent_stop import AgentStopService
```

Pair 3 of 4:

SEARCH:
```python
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import agentic_dispatch
```
REPLACE:
```python
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest, CapabilityRequestStore, agent_work_call
from probos.cognitive import agentic_dispatch
```

Pair 4 of 4:

SEARCH:
```python
    assert with_token is not None and "confirmation_token" not in with_token["params"]
    assert with_token == approval_payload("browser", {"action": "click", "index": 0}, "wi-1")
```
REPLACE:
```python
    assert with_token is not None and "confirmation_token" not in with_token["params"]
    assert with_token == approval_payload("browser", {"action": "click", "index": 0}, "wi-1")


_ROWS = _REPO / "ui" / "e2e" / "fixtures" / "ad1347-action-payload-rows.json"
#: A2 (F19), A2d, A2f (F26): the rows end on 11 of the 13 exits of ``validate_action_payload`` and reach each
#: refusal of the item binding. The other two exits have no row. A params key that is not a string
#: (``capability_request.py:220-221``) is unreachable from JSON, whose object keys are strings. A payload
#: ``_canonical_json`` refuses (``:233-234``) is reachable from JSON text, since ``1e400`` decodes to an infinite
#: float, but Python owns canonical admission and the HXI's size check is a lower bound that does not refuse an
#: infinite number (register R12), so the rows claim no agreement there. The store never writes such a payload.
_REFUSALS = frozenset({
    "missing_key", "extra_key", "tool_id_number", "tool_id_grammar", "action_number", "action_grammar", "tool_id_65",
    "params_array", "params_text", "params_21_keys", "scope_254", "thread_65", "thread_null", "session_65",
    "session_number", "lone_surrogate", "size_4047", "other_item", "unlinked", "empty_item",
})


def _row_request(row: dict[str, Any]) -> CapabilityRequest:
    """The approved request a shared row describes, its ``fill`` applied as the HXI test applies it."""
    payload = copy.deepcopy(row["payload"])
    work_item_id = row["work_item_id"]
    fill = row.get("fill")
    if fill is not None:
        text = "x" * fill["chars"]
        if fill["field"] == "work_item_id":
            work_item_id, payload["scope_key"] = text, "agent_work:" + text
        elif fill["field"] == "note":
            payload["params"]["note"] = text
        else:
            payload[fill["field"]] = text
    return CapabilityRequest(
        id="00000000-0000-0000-0000-000000000009", agent_id="forge-1", kind=row["kind"], target="hull_survey",
        work_item_id=work_item_id, status="approved", created_at=1000.0, payload=payload,
    )


# X22
def test_both_fulfilment_predicates_read_every_shared_payload_row_alike() -> None:
    """A2 (F19): the Python oracle of ``ui/e2e/fixtures/ad1347-action-payload-rows.json``. Each row's answers are
    Python's, through the real ``can_fulfil_request`` and ``agent_work_call``, and
    ``ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts`` requires the HXI's ``canFulfil`` and decoder to give
    the same ones. A2d, A2f (F26): the rows end on 11 of the 13 exits of ``validate_action_payload`` and reach
    each refusal of the item binding; ``_REFUSALS``'s comment names the other two and why neither has a row. The test
    reads the answers, not which refusal gave them: the two action rows are also refused by
    ``agent_work_call``'s action check."""
    rows = json.loads(_ROWS.read_text(encoding="utf-8"))["rows"]
    names = [row["name"] for row in rows]
    assert len(set(names)) == len(names) and _REFUSALS <= set(names)
    for row in rows:
        request = _row_request(row)
        assert (row["name"], can_fulfil_request(request)) == (row["name"], row["fulfillable"])
        assert (row["name"], agent_work_call(request) is not None) == (row["name"], row["agent_work_call"])
    assert [row["name"] for row in rows if row["name"] in _REFUSALS and row["fulfillable"]] == []


# X23
async def test_a_fulfilment_store_fault_on_an_agent_work_approval_returns_the_approval_as_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (F20): the approval route degrades honestly: the decision is recorded and the response says it is approved,
    not fulfilled, and retryable (HTTP 200, not 500); the retry then fulfils it."""
    from probos.agent_work_runner import approval_payload

    requests = CapabilityRequestStore(db_path=str(tmp_path / "requests.db"))
    await requests.start()
    try:
        captain = SimpleNamespace(capability_request_store=requests)
        filed = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 2}, "wi-agent-work-1"), rationale="r",
            work_item_id="wi-agent-work-1",
        )
        real_mark = requests.mark_fulfilled

        async def _readonly(request_id: str) -> Any:
            raise OSError("attempt to write a readonly database")

        monkeypatch.setattr(requests, "mark_fulfilled", _readonly)
        decided = await decide_capability_request(filed.id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert decided["fulfilled"] is False
        assert (decided["request"]["status"], decided["request"]["can_retry_fulfilment"]) == ("approved", True)
        monkeypatch.setattr(requests, "mark_fulfilled", real_mark)
        retried = await decide_capability_request(filed.id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert (retried["fulfilled"], retried["request"]["status"]) == (True, "fulfilled")
    finally:
        await requests.stop()


# X24
async def test_an_agent_work_approval_issues_no_standing_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A2: the confinement admits one exact call per approval and never reads a standing rule, so the route issues
    none for an agent-work approval, with standing rules on and the item's value confirmed, as for repair and AD-1328
    command approvals; the HXI does not offer one (``CapabilityRequestCard.ad1347.test.tsx``)."""
    from probos.agent_work_runner import approval_payload

    issued: list[Any] = []

    async def _confirmed(*args: Any) -> bool:
        return True

    async def _issue(*args: Any, **kwargs: Any) -> Any:
        issued.append(args)
        raise OSError("a standing rule was issued")

    monkeypatch.setattr(route_module, "_work_item_value_confirmed", _confirmed)
    requests = CapabilityRequestStore(db_path=str(tmp_path / "requests.db"))
    await requests.start()
    try:
        inbox = SimpleNamespace(standing_rules_enabled=True, standing_rule_max_ttl_hours=12, standing_rule_default_ttl_hours=4)
        runtime = SimpleNamespace(
            capability_request_store=requests, action_approval_store=SimpleNamespace(issue_approval=_issue),
            config=SimpleNamespace(approval_inbox=inbox),
        )
        filed = await requests.file_action_request(
            "forge-1", approval_payload("hull_survey", {"depth": 2}, "wi-agent-work-1"), rationale="r",
            work_item_id="wi-agent-work-1",
        )
        body = CapabilityRequestDecideRequest(approve=True, grant_standing=True, standing_ttl_hours=2)
        decided = await decide_capability_request(filed.id, body, runtime=runtime)
        assert (decided["standing_rule"], decided["fulfilled"], issued) == (None, True, [])
    finally:
        await requests.stop()
```

## 8. Tracking (in M2's commit, or a docs-only commit after it)

Set the date to the commit date. Both anchors survive wave 2's entries.

**`PROGRESS.md`** (title plus blank line; occurs once):

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**AD-1347 S2 and S3 (2026-10-23), #1627 slices 2 and 3 of 4, closing AD-1347 -- crew file, claim and run governed work from the cognitive chain, read-only by default, with the Captain's approval for anything else, and the result is posted where it was asked.** New `probos/agent_work_tags.py`: one parser for `[SELF_TASK]`, `[REQUEST_WORK]`, `[CLAIM_WORK]` and `[DECLINE_WORK]`, acted on in `ProactiveCognitiveLoop._extract_and_execute_actions` (proactive thoughts and every Ward Room reply, whose pipeline now passes its thread and post), Lieutenant and above, at most 3 per reply, each acknowledged in the agent's own reply; the compose step teaches the tags only while `agent_work` is on (byte-identical off). New `probos/agent_work_runner.py` (`AgentWorkRunner`, wired in finalize only with the service): announces each request once to each eligible member in its department's channel; claims through the tool sink; runs each item in its assignee's agentic loop under the new `ToolCallConfinement` (read-only tools run; any other call is filed as an AD-1154 `action` request and the item parks on it through AD-855; the Captain's approval resumes it and admits that call once; a denial ends it with the reason); returns a request whose claimant may not run it to the board; reports each outcome once per requester and watcher in the origin thread. `AgentWorkService` gains `crew_member` and `execution_allowed`; the approval route fulfils agent-work approvals; AD-855 resumes agent work through its runner. The Captain's one-to-one chat is not wired (its work is the Captain's: AD-845, AD-1165). New: `tests/test_ad1347_s2_chain_tags.py`, `tests/test_ad1347_s3_execution.py` (acceptance 2 end to end), `tests/test_ad1347_s3_wiring.py`. Updated: the AD-1343 seam registry, `test_ad1156_plan_execute_mode.py`, `test_issue1419_failed_start_rollback.py`, two docstrings in `test_ad1347_s1_agent_work.py`. Review round 1 (A1) repaired 14 findings and one found in the repair: both fulfilment predicates (`can_fulfil_request` and the HXI's `canFulfil` in `ui/src/store/capabilityApprovals.ts`) accept the agent-work approval bound to its item, so the HXI confirms it and an unfulfilled one stays retryable; a start that arrives during a run runs after it; a confinement's admission is not parked again by AD-1154's inbox; only a completed run with an answer is done (any other stop fails with its reason); a stopped claimant is released before parking; the parser is one linear pass (any case, every marker stripped, fenced, quoted and nested tags never acted on); declines reach watchers; a fault on one tag is acknowledged; off neither imports nor calls the tag module; the notice states the TTL exactly; a browser confirmation token is never recorded. New: `ui/e2e/fixtures/ad1347-agent-work-approvals.json`, `ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts`. Review round 2 (A2) repaired 6 findings: fenced examples (any fence character and length, indented in a list) and inline code spans are never acted on, and a nested block stays inert until its own closer (A2b, A2c and review round 3's A2d: indentation is read both at the top level and in a list item at CommonMark's content column, an empty list item ends at a blank line, and a quote is read after any whitespace (review round 4's A2f); one table of 74 constructs is the grammar); the HXI validates an agent-work payload as Python does (one shared rows table); a fulfilment-store fault on an agent-work approval returns it as retryable instead of HTTP 500; the Captain's card says approving an agent-work call resumes the item, and no standing approval is offered or issued for one. New: `ui/e2e/fixtures/ad1347-action-payload-rows.json`, `ui/src/store/__tests__/capabilityApprovals.ad1347a2.test.ts`, `ui/src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx`. #1627 stays open until the Captain's live acceptance. The contract is `prompts/ad-1347-s2-s3-chain-wiring-execution-and-report-back.md`.

```

**`DECISIONS.md`** (anchored on the next heading; occurs once):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1347 S2 and S3 -- The chain's agent-work tags, and the Ship's Computer runs, parks, resumes and reports agent-created work (2026-10-23, #1627 slices 2 and 3 of 4; closes AD-1347)

- *Scope.* One batch, two milestone commits. New `agent_work_tags.py` and `agent_work_runner.py`; `proactive.py`, `ward_room_pipeline.py`, `cognitive/sub_tasks/compose.py`, `agent_stop.py` (`S1_SCOPE` text), `agent_work.py` (two methods), `cognitive/agentic_dispatch.py` (`ToolCallConfinement`), `cognitive/capability_gap_driver.py`, `routers/capability_requests.py`, `runtime.py`, `startup/finalize.py`, `startup/shutdown.py`, tests. Contract `prompts/ad-1347-s2-s3-chain-wiring-execution-and-report-back.md`.
- *D1 (one parser).* Acted on only in the proactive action extractor, which proactive thoughts and every Ward Room reply already reach; the pipeline passes the thread and post. The Captain's one-to-one chat is not wired: work found there is the Captain's (AD-845, AD-1165).
- *D2 (grammar).* Block tags with `Key: value` lines; Lieutenant and above; 3 per reply; the acknowledgement is a Ship's Computer line in the agent's own reply, so it starts no routing.
- *D3 (runs).* A runner reacts to the work store's events (created self-task or assignment, claimed request, ended item), a chain claim starts its run, and a start recovers unfinished work. Runs go through `WorkItemAgenticExecutor.run` without `admitted_turn` (the stop at `agentic_run`). A request whose claimant may not run it, before or after the run, goes back to the board unclaimed (AD-1343 S2 is not built).
- *D4 (read-only at the call).* `ToolCallConfinement`: the plan-mode read set without its off-ship reads runs; any other call is put to a gate before plan mode and the browser inbox; a gate fault refuses; the refusals never ran. The offer is not narrowed, so a write call is reachable and governed.
- *D5 (approval).* An AD-1154 `action` (`agent_work_call`, scoped to the item); AD-855 parks the item; approval is its own fulfilment; the resumed run admits that call once on a claim-once row; a denial cancels and the report reads the reason from the request. No new request kind.
- *D6 (reports).* Ship's Computer posts: the notice in the department channel (mentions, `max_responders`), the report, decline, expiry and denial in the origin thread (fallback the department channel), each notice claimed before it is sent. The store's TTL sweep stays the only expiry owner.
- *Disclosed effects.* `S1_SCOPE` names agent-created work; two refusal texts join the never-ran set; `runtime.agent_work_runner` exists (None while off); no standing rule is offered or issued on an agent-work approval (A2).
- *A1 (review round 1).* No decision reversed. D3: a start during a run is deferred, eligibility is asked before parking, and only a completed run with an answer is done (any other stop is failed with its reason). D4: a confinement's admission is carried past AD-1154's inbox for that call only (credential entry stays refused), and a confirmation token is never recorded. D5: the subtype is fulfillable in both predicates, Python and HXI. D2: one linear scanner; fenced, quoted and nested tags are never acted on.
- *A2 (review round 2).* No decision reversed. D2: the scanner's inert regions follow CommonMark 0.31.2's fences (character and run length), inline code spans and line endings, with named differences; a block nests and closes only on its own closer; one table of rows is the grammar (74 after A2d). D5: the HXI validates the agent-work payload as Python does, proven on one shared rows table; a fulfilment-store fault returns the retryable approval; the card says the approval resumes the item, and no standing approval is offered or issued for it.
- *A2d (review round 3).* No decision reversed. D2: a list item's content column is CommonMark 0.31.2 §5.2's for the last marker on a line (five or more columns of padding start the item with indented code; an empty item ends at a blank line), and every grammar row outside the named differences puts its markers where CommonMark does; general CommonMark compliance is not claimed. D5: the shared payload rows reach every refusal of `validate_action_payload` but two, each named with its reason.
- *A2f (review round 4).* No decision reversed. D2: a quote is a line whose first character other than any whitespace is `>`, as before A2d. A2d's spaces-and-tabs test acted on such a line after a quote or inside a nested item's fence, where CommonMark keeps it inert; the scanner cannot tell those from a standalone line without parsing containers, so it keeps the over-inert direction (register R14).
- *A2g (review round 5).* No decision reversed; no code or test changed. D2: two shapes are recorded. After a quote line, a line led by a non-ASCII blank and `>` is a quote, so a block on the lazy lines after it is acted on, as after a plain `>` line (F28, register R13). After a list item marker such a line is a quote, though CommonMark reads it as the item's paragraph (F29, register R14). On such documents, scanner candidates are compared through the ASCII twin (each such blank replaced by one space). A difference is not a regression only where the earlier candidate answers the twin as the new one answers the document and that answer is a named register shape; this applies to this scanner's quote test only, and no standing rule changes.
- *Reversal.* Revert both commits; open agent work stays on the board until its TTL; the AD-1154 requests filed stay in the inbox as ordinary actions with no fulfiller. Reverting A1's HXI change with the Python change keeps the two predicates in agreement; reverting only one makes the HXI refuse any queue holding an approved, unfulfilled agent-work call.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, verify with `--check` and `tests/test_ad1184_ad_ledger.py`, and commit the regenerated files with the trackers. **`docs/development/roadmap.md`:** no row (AD-1347 is not there).

## 9. What this does NOT change

- `cognitive/dm/reply_pipeline.py`: the Captain's one-to-one chat, its 24 steps, its plan-mode tables; AD-845's `[CREATE_TASK]`; AD-1165 promotion.
- `_handle_work_item_dispatch` and `_run_agentic_dispatch` (the AD-839 path).
- AD-1154's browser inbox: `_APPROVAL_INBOX_TOOL_IDS`, the standing-rule machinery, and `_park_or_admit`'s signature (pinned) and steps for every call a confinement did not admit. A1 (F3) adds one admission after its step 3, for the call a confinement admitted only. A2: no standing rule is offered (HXI) or issued (route) on an agent-work approval, as for repair and AD-1328 command approvals; the confinement never reads one (register R2 closed).
- Tools:
  - no `allowed_departments` or rank change;
  - no tool registered;
  - the agent's offer is not narrowed.
- Persistence and configuration:
  - no config field (`AgentWorkConfig` is S1's);
  - no table;
  - no EventLog category or event pair;
  - no request kind.
- AD-1343: no new seam constant and no new stop-check site. AD-1346: no `decide`.
- `WorkItemStore`: no new method. The TTL sweep and the claim gate are unchanged.
- `ward_room_router.py` and the Ward Room service.
- `config/system.yaml`.
- The tag scanner's grammar (A2: F16, F17) follows CommonMark 0.31.2 for fences (§4.5: character, run length, a backtick fence's info string without a backtick, unclosed to the end), inline code spans (§6.1: equal-length runs; an unmatched run is text) and line endings (§2.1: LF, CRLF, CR). These differences are deliberate, and each one a C17 row can show is one:
  - Indentation is read two ways (A2b), because the scanner does not parse list containers, and a line is inert when either reading makes it so. The top-level reading is CommonMark's: a fence line starts within three columns (a tab advances to a multiple of four) and its closer has no list marker, and a line indented four or more columns that does not continue a paragraph is indented code (a paragraph ends at a blank line, a quote, a fence, an ATX heading, or a line of one repeated `-`, `*`, `_` or `=`). The list reading opens a fence at any column, after list item markers too (`fence_on_a_list_marker_line`), and closes it only on a line without a marker within three columns of its opener (`list_closer_more_than_three_past_its_opener_is_content`, `new_list_item_fence_line_does_not_close`). A2c, A2d: the list reading tracks the last list item's content column as CommonMark 0.31.2 §5.2 sets it for the last marker on a line: the marker plus one to four columns of padding, and the marker plus one for an item that starts blank or with five or more columns of padding, whose first line's rest is then indented code and opens no fence (`padding_five_starts_the_item_with_indented_code`, `padding_four_is_the_item_column`, `tab_padding_is_counted_in_columns`, `wide_padded_line_is_indented_code`, `fence_on_a_wide_padded_line_is_code_text`); a non-blank line left of the column ends the item, and so does a blank line while the item has no content (`empty_item_ends_at_a_blank_line`, `empty_item_that_opens_a_fence_keeps_its_column_across_a_blank_line`). A non-blank line left of a fence's floor ends that fence before the line is read, so the line may open a new fence (`marker_line_fence_ends_at_an_unindented_fence_line`, `fence_in_an_item_ends_at_a_quote`, `continuation_fence_ends_at_an_outdented_fence_line`, `outdented_fence_line_after_an_item_fence_opens_a_top_level_fence`, `bare_marker_item_fence_ends_at_column_one`). A list fence in a tracked item is floored at the item's column and closes within three columns of it (`list_closer_counts_from_the_item_column`); outside one it is floored at 0 within three columns, else three columns left of it and never below 2 (`indented_fence_line_ends_at_an_unindented_line`), and closes within three columns of itself. The top reading floors only a fence on a marker line (`marker_line_fence_ends_at_an_outdented_line`). This errs toward inert where a tag indented four or more columns follows a blank line, as in a list item's continuation, and (A2d) where it follows a marker line with five or more columns of padding, which is read as indented code, although CommonMark measures the indent from the item's content column, so a line two or three columns past that column is a paragraph (`out_of_scope_wide_item_paragraph_indented_four_is_read_as_written`; register R14). It is still acted on where CommonMark is inert only where the one-level tracker is wrong and the top reading is wrong too (register R15): a lazy line ends the tracked item, so an item's fence after it is read as untracked (`out_of_scope_lazy_line_then_an_item_fence_is_read_as_written`); and a line that only looks like an item (a setext `-` underline, an ordered marker or an empty item that cannot interrupt a paragraph, a thematic break made of markers, or a second marker after five or more columns of padding, `-     - x`, whose rest CommonMark reads as indented code) is tracked as one; and a nested item is tracked at its innermost marker's content column only (`- - text`, or an item inside an item), so a fence at the outer item's column after it is floored at 0 as an untracked fence (orchestrator's differential, mechanical repair 9).
  - A quote is any line whose first non-whitespace character (Python's `str.lstrip()`: spaces, tabs and every other character `str.isspace()` accepts), after any list item markers, is `>`, at any indentation (`quote_in_a_list_item`, `tab_before_a_quote_mark_in_a_list_item_is_a_quote`, `nbsp_line_after_a_quote_is_quoted`). A2f (F27): CommonMark counts only spaces and tabs, so a line that starts with another blank such as U+00A0 or U+2003 and `>` is a paragraph there when it stands alone; here it is not acted on (`out_of_scope_nbsp_before_a_quote_mark_is_a_quote`, `out_of_scope_em_space_before_a_quote_mark_is_a_quote`; register R14, the over-inert direction). Read narrowly, the same line would be acted on straight after a quote or inside a nested item's fence, where CommonMark keeps it inert. A lazy continuation line is not quoted, so an agent's own tag placed straight after a quotation is acted on (`out_of_scope_lazy_quote_continuation_is_read_as_written`). A2g: this holds when the quote's next line is led by a non-ASCII blank and `>` too. That line is read as a quote and its marker is removed alone, and a block on the lazy lines after it is acted on, as after a plain `>` line (F28, register R13). After a list item marker such a line is read as a quote, although CommonMark reads it as the item's paragraph, so its tag is not acted on (F29, register R14, F24's shape).
  - A code span is read within one line; a span that crosses a line ending is read as text (`out_of_scope_span_across_lines_is_read_as_written`). Backslash escapes are not read, so an escaped backtick still opens or closes a span (this errs toward inert).
  - HTML comments and raw HTML are read as text. A `>` line never opens a fence.
  - A marker in an inert region is removed alone, and the example's text stays in the post (A1 removed a fenced example's whole block).
  - Register R13 holds the lazy continuation and the span across lines, and register R15 the item tracker's three shapes the first bullet names (a renderer shows the tag as code or quote; it is acted on).
  - A2d: general CommonMark compliance is not claimed. C17's rows and the differences above are the grammar.
- The HXI's size bound on an action payload counts each number as one character: the decoded value does not keep Python's spelling (`1e400`, which Python rejects, and an integer of 401 digits, which it accepts, both decode to Infinity). The bound is exact for text and only necessary for numbers, and Python serves no payload it rejected (it decodes it to `payload: null`), so a disagreement needs a forged response (register R12; not a shared row).

## 10. Mutation rows (130 Python rows after A2d, plus 11 TypeScript rows run by hand; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row against the named test on the contract-applied tree, after an unmutated baseline that passes, and restore the file before the next row. None of these rows has been executed; the build's campaign is the one of record.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| T1 | `src/probos/agent_work_tags.py` | `if not tags or rank is Rank.ENSIGN:` | `if not tags:` | C6 (the ensign's self-task is filed) |
| T2 | `src/probos/agent_work_tags.py` | `if index >= MAX_TAGS_PER_REPLY:` | `if False:` | C8 (four items) |
| T3 | `src/probos/agent_work_tags.py` | `origin: AgentWorkOrigin \| None = AgentWorkOrigin("ward_room" if thread_id else "proactive", thread_id=thread_id, post_id=post_id)` | `origin: AgentWorkOrigin \| None = AgentWorkOrigin("proactive")` | C3, C12 (origin) |
| T4 | `src/probos/agent_work_tags.py` | `return service if type(service) is AgentWorkService else None` | `return service` | C5 (the double enters the path) |
| T5 | `src/probos/agent_work_tags.py` | `return AGENT_WORK_INSTRUCTIONS if agent_work_service(runtime) is not None else ""` | `return AGENT_WORK_INSTRUCTIONS` | C11 (off prompt differs) |
| T6 | `src/probos/agent_work_tags.py` | `assignee=_slot_of(runtime, tag.assignee),` | `assignee=None,` | C13 (`requester_holds_tool`) |
| T7 | `src/probos/agent_work_tags.py` | `department=tag.department or None,` | `department=None,` | C4 (security) |
| T8 | `src/probos/agent_work_tags.py` | `if created.deduplicated:` | `if False:` | C10 (no "watcher") |
| T9 | `src/probos/agent_work_tags.py` | `if type(runner) is not AgentWorkRunner:` | `if True:` | X1 (no claim) |
| P1 | `src/probos/proactive.py` | `if agent_work_service(rt) is not None:` | `if False:` | C3 |
| P2 | `src/probos/proactive.py` | `text, runtime=rt, actor=agent.id, rank=rank, thread_id=thread_id, post_id=post_id,` | `text, runtime=rt, actor=agent.id, rank=rank,` | C3 (origin proactive) |
| P3 | `src/probos/proactive.py` | `return await self._extract_and_execute_actions(agent, text, post_budget=post_budget, thread_id=thread_id, post_id=post_id)` | `return await self._extract_and_execute_actions(agent, text, post_budget=post_budget)` | C12 |
| WP1 | `src/probos/ward_room_pipeline.py` | `post_budget=budget, thread_id=thread_id, post_id=post_id or "",` | `post_budget=budget,` | C12 |
| CP1 | `src/probos/cognitive/sub_tasks/compose.py` | `if mode_key in AGENT_WORK_COMPOSE_MODES:` | `if True:` | C11 (dm_response taught) |
| S1 | `src/probos/agent_work.py` | `return self._directory.member(ref.slot_id) if ref is not None else None` | `return None` | X1 (claim refused) |
| S2 | `src/probos/agent_work.py` | `if member is None or self._stopped_now(member.slot_id):` | `if member is None:` | X3 stop_before_run (the executor is entered; A1's entry assertion) and stop_during_run (a stopped claimant stays assigned) |
| S3 | `src/probos/agent_work.py` | `return member.department == record.department and record.tool_id is not None and self._holds_tool(member, record.tool_id)` | `return True` | X3 restricted_before_run |
| A1 | `src/probos/cognitive/agentic_dispatch.py` | `if confinement is not None and tool_id not in confinement.tool_ids:` | `if False:` | X2 (the survey runs at once) |
| A2 | `src/probos/cognitive/agentic_dispatch.py` | `executor.confine_calls(confinement)` | `pass` | X2 |
| A3 | `src/probos/cognitive/agentic_dispatch.py` | `arguments["confinement"] = confinement` | `pass` | X2 |
| A4 | `src/probos/cognitive/agentic_dispatch.py` | `{_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED}` | `{_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL}` | X9b; `tests/test_ad1156_plan_execute_mode.py` |
| A5 | `src/probos/cognitive/agentic_dispatch.py` | `verdict = CONFINEMENT_REFUSED` | `verdict = CONFINEMENT_ADMIT` | X9b (the broken gate admits) |
| A6 | `src/probos/cognitive/agentic_dispatch.py` | `if verdict == CONFINEMENT_ADMIT:` | `if True:` | X9 |
| A7 | `src/probos/cognitive/agentic_dispatch.py` | `type(confinement) is not ToolCallConfinement or plan_mode_tool_ids is not None` | `type(confinement) is not ToolCallConfinement` | X9b |
| R1 | `src/probos/agent_work_runner.py` | `if item.status in TERMINAL_STATUSES:` | `if False:` | X1 (no report) |
| R2 | `src/probos/agent_work_runner.py` | `await self._announce(item, record)` | `pass` | X1 (no notice) |
| R3 | `src/probos/agent_work_runner.py` | `elif kind == EventType.WORK_ITEM_CREATED.value or record.kind == KIND_REQUEST:` | `elif kind == EventType.WORK_ITEM_CREATED.value:` | X3 (the claimed request is not released) |
| R4 | `src/probos/agent_work_runner.py` | `if member.department != record.department or member.slot_id == record.requester:` | `if member.slot_id == record.requester:` | X1 (`@Worf`) |
| R5 | `src/probos/agent_work_runner.py` | `body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=len(fresh),` | `body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=0,` | X1 |
| R6 | `src/probos/agent_work_runner.py` | `if claimed_item is None or claimed_item.assigned_to != member.slot_id:` | `if claimed_item is None:` | X8 (Worf is told he claimed it) |
| R7 | `src/probos/agent_work_runner.py` | `self._start(claimed_item.id)` | `pass` | X1 (not done before the pump) |
| R8 | `src/probos/agent_work_runner.py` | `if not await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_DECLINE, self._clock()):` | `if False:` | X7 (a second relay) |
| R9 | `src/probos/agent_work_runner.py` | `or item.status != "open" or member.department != record.department` | `or item.status != "open"` | X7 (Worf's decline is accepted) |
| R10 | `src/probos/agent_work_runner.py` | `claimed = [notice.recipient for notice in notices if await self._service.claim_notice(work_item_id, notice.recipient)]` | `claimed = [notice.recipient for notice in notices]` | X5 (two posts) |
| R11 | `src/probos/agent_work_runner.py` | `if outcome == OUTCOME_EXPIRED:` | `if False:` | X5 ("expired") |
| R12 | `src/probos/agent_work_runner.py` | `if denial:` | `if False:` | X2 (the reason) |
| R13 | `src/probos/agent_work_runner.py` | `return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]` | `return "no reason recorded"` | X2 |
| R14 | `src/probos/agent_work_runner.py` | `await self._store.unassign_work_item(item.id, reason="the claimant may not run it now")` | `pass` | X3 before_run cases (status scheduled) |
| R15 | `src/probos/agent_work_runner.py` | `if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):` | `if False:` | X3 stop_during_run (done, not open); X18 (parked, still assigned) |
| R16 | `src/probos/agent_work_runner.py` | `await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)` | `pass` | X2 (not blocked) |
| R17 | `src/probos/agent_work_runner.py` | `item.id, status, source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},` | `item.id, status, source=RUN_SOURCE, expected_status="in_progress",` | X1 (no answer in the report) |
| R18 | `src/probos/agent_work_runner.py` | `if completed and booking.status in ("active", "scheduled"):` | `if False:` | X1 (booking cancelled) |
| R19 | `src/probos/agent_work_runner.py` | `return CONFINEMENT_ADMIT` | `return CONFINEMENT_FILED` | X2 (the survey never runs) |
| R20 | `src/probos/agent_work_runner.py` | `if self._requests.count_pending_sync(agent_id) >= self._max_pending:` | `if False:` | X10 (a request is filed) |
| R21 | `src/probos/agent_work_runner.py` | `filed.append(request.id)` | `pass` | X2 (not parked) |
| R22 | `src/probos/agent_work_runner.py` | `if type(origin) is not dict or origin.get("channel") != "ward_room":` | `if True:` | X1 (the report goes to the department channel) |
| R23 | `src/probos/agent_work_runner.py` | `await runner.resume(item.id)` | `pass` | X2 (no resume) |
| R24 | `src/probos/agent_work_runner.py` | `if read_agent_work(item) is None:` | `if False:` | X12 (the router is not called) |
| G1 | `src/probos/cognitive/capability_gap_driver.py` | `if await resume_agent_work(self._runtime, updated):` | `if False:` | X2 |
| F1 | `src/probos/routers/capability_requests.py` | `if agent_work_approval(decided) is not None:` | `if False:` | X2 (`fulfilled` False) |
| F2 | `src/probos/routers/capability_requests.py` | `return await store.mark_fulfilled(decided.id) is not None` | `return False` | X2 |
| W1 | `src/probos/startup/finalize.py` | `if type(getattr(runtime, "agent_work", None)) is not AgentWorkService:` | `if False:` | W3 (the off boot builds a runner with no service and fails) |
| SD1 | `src/probos/startup/shutdown.py` | `await work_runner.stop()` | `pass` | `tests/test_issue1419_failed_start_rollback.py::test_a_rollback_with_no_failed_step_asks_each_component_once_and_closes_nothing` |
| N1 | `src/probos/capability_request.py` | `return req.kind in FULFILMENT_KINDS or repair_action(req) is not None or agent_work_call(req) is not None` | `return req.kind in FULFILMENT_KINDS or repair_action(req) is not None` | X13 (the approved row is not retryable) |
| N2 | `src/probos/capability_request.py` | `or payload["scope_key"] != AGENT_WORK_SCOPE_PREFIX + work_item_id` | `or False` | X13 (`wi-other` is fulfillable) |
| N3 | `src/probos/cognitive/agentic_dispatch.py` | `confined_admission = True` | `confined_admission = False` | X15 (the inbox parks the admitted click) |
| N4 | `src/probos/cognitive/agentic_dispatch.py` | `if _CONFINED_ADMISSION.get():` | `if False:` | X15 |
| N5 | `src/probos/agent_work_runner.py` | `self._restart.add(work_item_id)` | `pass` | X14 (in_progress, survey never runs) |
| N6 | `src/probos/agent_work_runner.py` | `if work_item_id in self._restart:  # A1 (F2): a start that arrived during this run runs now` | `if False:` | X14 |
| N7 | `src/probos/agent_work_runner.py` | `if outcome.parked_request_id:` | `if False:` | X16 (the booking is cancelled) |
| N8 | `src/probos/agent_work_runner.py` | `finished = stopped == "complete" and bool(answer)` | `finished = True` | X17 (both cases: done) |
| N9 | `src/probos/agent_work_runner.py` | `elif type(result.get("stopped")) is str:  # A1 (F4): the run stopped without a finished answer` | `elif False:` | X17 (the stop is not named) |
| N10 | `src/probos/agent_work_runner.py` | `recipients = await self._service.notice_recipients(item.id)` | `recipients = (record.requester,)` | X7 (no `@Ogawa`) |
| N11 | `src/probos/agent_work_runner.py` | `if not posted:  # A1 (F9, the literal): a post that did not go through is not "told"` | `if False:` | X19 |
| N12 | `src/probos/agent_work_runner.py` | `if seconds >= size and seconds % size == 0:` | `if True:` | X20 ("0 h") |
| N13 | `src/probos/agent_work_runner.py` | `recorded = {key: value for key, value in params.items() if key not in APPROVAL_UNRECORDED_PARAMS}` | `recorded = dict(params)` | X21 |
| N14 | `src/probos/agent_work_tags.py` | `if opener and not inert:` | `if opener:` | C17 `quoted_opener_leaves_the_real_block_actionable` (A2: replaces A1's row, whose constructor line A2 removes) |
| N15 | `src/probos/agent_work_tags.py` | `block.actionable = False` | `pass` | C1 nested case ("Outer ... Inner" filed) |
| N16 | `src/probos/agent_work_tags.py` | `elif rest.lstrip().startswith(">"):  # A2f (F27): any whitespace; it can only make a line inert` | `elif content.lstrip().startswith(">"):` | C17 `quote_in_a_list_item` (A2b: the quote is read after list item markers; A2d: the line reads `rest`; A2f: any whitespace) |
| N17 | `src/probos/agent_work_tags.py` | `closer, name, attribute = match.group(1) == "/", match.group(2).upper(), match.group(3)` | `closer, name, attribute = match.group(1) == "/", match.group(2), match.group(3)` | C1 mixed-case case |
| N18 | `src/probos/agent_work_tags.py` | `cuts.append((match.start(), match.end()))` | `pass` | C1 stray case |
| N19 | `src/probos/agent_work_tags.py` | `ack, action = await _apply_guarded(tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id))` | `ack, action = await _apply_one(tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id))` | C16 (the fault escapes) |
| N20 | `src/probos/proactive.py` | `if getattr(rt, "agent_work", None) is not None:` | `if True:` | C5 (off calls `agent_work_service`) |
| N21 | `src/probos/agent_work_tags.py` | `elif opened is not None and column <= 3:` | `elif opened is not None:` | C17 `indented_fence_line_ends_at_an_unindented_line` (A2c: the list reading's floor now covers A2b's killing case) |
| N22 | `src/probos/agent_work_tags.py` | `cuts.extend([(block.start, block.body_start), *block.inner])` | `cuts.append((block.start, block.body_start))` | C1 unclosed-with-marker case |
| N23 | `src/probos/agent_work_tags.py` | `if item_id is not None and not inert:` | `if item_id is not None:` | C1 quoted case (the claim is taken) |
| N24 | `src/probos/agent_work_tags.py` | `inert = span < len(spans) and spans[span][0] <= match.start()` | `inert = False` | C1 fenced and quoted cases |
| N25 | `src/probos/agent_work_tags.py` | `block.open_names.append(name)` | `pass` | C17 `nested_tail` |
| N26 | `src/probos/agent_work_tags.py` | `block.open_names.pop()` | `pass` | C1 nested case (the block never closes; its text stays) |
| N27 | `src/probos/agent_work_tags.py` | `if not block.open_names:` | `if True:` | C17 `nested_tail` |
| N28 | `src/probos/agent_work_tags.py` | `closes = closer and not inert and not attribute.strip()` | `closes = closer and not attribute.strip()` | C17 `inert_closer_inside_a_block_breaks_it` |
| N29 | `src/probos/agent_work_tags.py` | `if closes and name == block.open_names[-1]:` | `if closes:` | C17 `closer_of_the_other_name_breaks_the_block` |
| N30 | `src/probos/agent_work_tags.py` | `run is not None and run.group(1)[0] == fence[0]` | `run is not None` | C17 `fence_tilde_inside_backtick_is_content` |
| N31 | `src/probos/agent_work_tags.py` | `and len(run.group(1)) >= fence[1]` | `and True` | C17 `fence_shorter_run_inside_is_content` |
| N32 | `src/probos/agent_work_tags.py` | `and not run.group(2).strip(" \t")` | `and True` | C17 `fence_line_with_info_inside_is_content` |
| N33 | `src/probos/agent_work_tags.py` | `top_fence = None  # its closing fence` | `pass` | C17 `fence_backtick` (the real block after the fence is inert) |
| N34 | `src/probos/agent_work_tags.py` | `if run is not None and not (run.group(1)[0] == _BACKTICK and _BACKTICK in run.group(2)):` | `if run is not None:` | C17 `backtick_run_with_a_backtick_after_is_a_code_span` |
| N35 | `src/probos/agent_work_tags.py` | `spans.extend(_code_spans(content, start))` | `pass` | C17 `code_span_claim` |
| N36 | `src/probos/agent_work_tags.py` | `size = runs[index][1] - runs[index][0]` | `size = 1` | C17 `span_closes_only_on_a_run_of_its_length` |
| N37 | `src/probos/agent_work_tags.py` | `index = close + 1` | `index += 1` | C17 `text_between_two_spans_is_actionable` |
| N38 | `src/probos/agent_work_tags.py` | `_LINE_RE: Final = re.compile(r"[^\r\n]*(?:\r\n\|\r\|\n)\|[^\r\n]+")` | `_LINE_RE: Final = re.compile(r"[^\n]*\n\|[^\n]+")` | C17 `lone_cr_ends_a_line` |
| N39 | `src/probos/agent_work_tags.py` | `opened = (run.group(1)[0], len(run.group(1)))` | `opened = (run.group(1)[0], 3)` | C17 `fence_shorter_run_inside_is_content` (A2b: one opener size for both readings) |
| N41 | `src/probos/agent_work_tags.py` | `_PARAGRAPH_END_RE: Final = re.compile(r" {0,3}(?:#{1,6}(?:[ \t].*)?\|([-*_=])(?:[ \t]*\1)*[ \t]*)")` | `_PARAGRAPH_END_RE: Final = re.compile(r" {0,3}#{1,6}(?:[ \t].*)?")` | C17 `indented_code_after_a_thematic_break` |
| N42 | `src/probos/agent_work_tags.py` | `width += 4 - width % 4 if char == "\t" else 1` | `width += 1` | C17 `indented_code_by_a_tab` |
| N43 | `src/probos/agent_work_tags.py` | `head = item.group() if item is not None else ""` | `head = ""` | C17 `fence_on_a_list_marker_line` |
| N44 | `src/probos/agent_work_tags.py` | `closer = None if head else run` | `closer = run` | C17 `marker_line_inside_a_fence_is_content` (A2c: the floor now ends a fence at a new item) |
| N45 | `src/probos/agent_work_tags.py` | `indent = _columns(content[: len(content) - len(content.lstrip(" \t"))])` | `indent = 0` | C17 `indented_code_after_a_blank_line` |
| N46 | `src/probos/agent_work_tags.py` | `column = _columns(content[: len(head) + run.start(1)]) if run is not None else 0` | `column = 0` | C17 `list_closer_more_than_three_past_its_opener_is_content` |
| N47 | `src/probos/agent_work_tags.py` | `if list_fence is None and opened is not None:` | `if False:` | C17 `fence_indented_in_a_list_item` |
| N48 | `src/probos/agent_work_tags.py` | `elif list_fence is not None and _closes(list_fence[0], closer) and column <= list_fence[1]:` | `elif list_fence is not None and _closes(list_fence[0], closer):` | C17 `list_closer_more_than_three_past_its_opener_is_content` |
| N49 | `src/probos/agent_work_tags.py` | `list_fence = None  # its closing fence` | `pass` | C17 `text_after_a_list_fence_in_its_item_is_actionable` (A2c: in A2b's case the floor now ends the fence) |
| N50 | `src/probos/agent_work_tags.py` | `if _closes(top_fence[0], closer) and indent <= 3:` | `if _closes(top_fence[0], closer):` | C17 `top_level_closer_indented_four_does_not_close` |
| N51 | `src/probos/agent_work_tags.py` | `paragraph = False  # a blank line ends a paragraph` | `pass` | C17 `indented_code_after_a_blank_line` |
| N52 | `src/probos/agent_work_tags.py` | `top_fence, paragraph, inert = (opened, _columns(head)), False, True` | `top_fence, paragraph, inert = (opened, _columns(head)), paragraph, True` | C17 `indented_code_after_a_fence` |
| N53 | `src/probos/agent_work_tags.py` | `inert = inert or not paragraph` | `inert = inert` | C17 `indented_code_at_the_start` |
| N54 | `src/probos/agent_work_tags.py` | `paragraph = _PARAGRAPH_END_RE.fullmatch(content) is None` | `paragraph = True` | C17 `indented_code_after_a_heading` |
| N55 | `src/probos/agent_work_tags.py` | `if list_fence is not None and not blank and indent < list_fence[2]:` | `if list_fence is not None and indent < list_fence[2]:` | C17 `blank_line_inside_a_list_fence_keeps_it_open` |
| N56 | `src/probos/agent_work_tags.py` | `list_fence = None  # A2c: a line left of its item's content column ends the item` | `pass` | C17 `continuation_fence_ends_at_an_outdented_fence_line` |
| N57 | `src/probos/agent_work_tags.py` | `if top_fence is not None and not blank and indent < top_fence[1]:` | `if top_fence is not None and indent < top_fence[1]:` | C17 `blank_line_inside_a_marker_line_fence_keeps_it_open` |
| N58 | `src/probos/agent_work_tags.py` | `top_fence = None  # A2c: likewise for a fence opened on a marker line` | `pass` | C17 `marker_line_fence_ends_at_an_outdented_line` |
| N59 | `src/probos/agent_work_tags.py` | `item_column, item_empty = content_column, empty` | `item_column, item_empty = _columns(head), empty` | C17 `bare_marker_item_fence_ends_at_column_one` (A2d: the line A2d rewrites) |
| N60 | `src/probos/agent_work_tags.py` | `item_column = None` | `pass` | C17 `outdented_fence_line_after_an_item_fence_opens_a_top_level_fence` |
| N61 | `src/probos/agent_work_tags.py` | `elif item_column is not None and (item_empty if blank else indent < item_column):` | `elif item_column is not None and (True if blank else indent < item_column):` | C17 `blank_line_keeps_the_list_item` (A2d: the line A2d rewrites) |
| N62 | `src/probos/agent_work_tags.py` | `floor = item_column if item_column is not None else (0 if column <= 3 else max(2, column - 3))` | `floor = item_column if item_column is not None else 0` | C17 `indented_fence_line_ends_at_an_unindented_line` |
| N63 | `src/probos/agent_work_tags.py` | `_LIST_ITEM_RE: Final = re.compile(r"(?:[ \t]*(?:[-+*]\|[0-9]{1,9}[.)])(?:[ \t]+\|$))+")` | `_LIST_ITEM_RE: Final = re.compile(r"(?:[ \t]*(?:[-+*]\|[0-9]{1,9}[.)])[ \t]+)+")` | C17 `bare_marker_item_fence_ends_at_column_one` |
| N64 | `src/probos/agent_work_tags.py` | `base = column if item_column is None else item_column` | `base = column` | C17 `list_closer_counts_from_the_item_column` |
| N65 | `src/probos/agent_work_tags.py` | `wide = not empty and padding >= 5` | `wide = not empty and padding >= 6` | C17 `padding_five_starts_the_item_with_indented_code` (A2d, F22) |
| N66 | `src/probos/agent_work_tags.py` | `wide = not empty and padding >= 5` | `wide = not empty and padding >= 4` | C17 `padding_four_is_the_item_column` |
| N67 | `src/probos/agent_work_tags.py` | `return (end + 1 if empty or wide else end + padding), wide` | `return (end + 1 if empty else end + padding), wide` | C17 `padding_five_starts_the_item_with_indented_code` |
| N68 | `src/probos/agent_work_tags.py` | `return (end + 1 if empty or wide else end + padding), wide` | `return (end + 1 if wide else end + padding), wide` | C17 `bare_marker_item_fence_ends_at_column_one` |
| N69 | `src/probos/agent_work_tags.py` | `padding = _columns(head) - end` | `padding = len(head) - len(head.rstrip(" \t"))` | C17 `tab_padding_is_counted_in_columns` |
| N70 | `src/probos/agent_work_tags.py` | `empty = bool(head) and not rest` | `empty = False` | C17 `empty_item_ends_at_a_blank_line` (A2d, F23) |
| N71 | `src/probos/agent_work_tags.py` | `run = None if wide else _FENCE_RE.fullmatch(rest)  # A2d (F22): a wide line's rest is indented code` | `run = _FENCE_RE.fullmatch(rest)  # A2d (F22): a wide line's rest is indented code` | C17 `fence_on_a_wide_padded_line_is_code_text` |
| N72 | `src/probos/agent_work_tags.py` | `elif wide:` | `elif False:` | C17 `wide_padded_line_is_indented_code` |
| N73 | `src/probos/agent_work_tags.py` | `elif item_column is not None and (item_empty if blank else indent < item_column):` | `elif item_column is not None and (False if blank else indent < item_column):` | C17 `empty_item_ends_at_a_blank_line` (F23's revert) |
| N74 | `src/probos/agent_work_tags.py` | `item_empty = False  # A2d (F23): the item has content, so a blank line no longer ends it` | `pass` | C17 `empty_item_that_opens_a_fence_keeps_its_column_across_a_blank_line` |
| N75 | `src/probos/agent_work_tags.py` | `elif rest.lstrip().startswith(">"):  # A2f (F27): any whitespace; it can only make a line inert` | `elif rest.lstrip(" \t").startswith(">"):` | C17 `out_of_scope_nbsp_before_a_quote_mark_is_a_quote` (F27's revert: A2d's quote test) |
| N40 | `src/probos/agent_work_tags.py` | `r"\[(/?)(SELF_TASK\|REQUEST_WORK\|CLAIM_WORK\|DECLINE_WORK)\b([^\]\r\n]{0,160})\]", re.IGNORECASE,` | `r"\[(/?)(SELF_TASK\|REQUEST_WORK\|CLAIM_WORK\|DECLINE_WORK)\b([^\]\n]{0,160})\]", re.IGNORECASE,` | C17 `marker_does_not_cross_a_line_end` |
| F3 | `src/probos/routers/capability_requests.py` | `except Exception:  # A2 (F20): the approval stands and stays retryable` | `except ZeroDivisionError:  # A2 (F20): the approval stands and stays retryable` | X23 (the store fault escapes) |
| F4 | `src/probos/routers/capability_requests.py` | `if agent_work_approval(decided):  # AD-1347 S3 A2: one exact call per approval; no standing rule` | `if False:  # AD-1347 S3 A2: one exact call per approval; no standing rule` | X24 (`issued` is not empty) |

Row T3's Line cell escapes the union bar (`\|`) for the Markdown table; the source line has a plain `|`. X9b is `test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome`.

**A2d campaign.** Rerun the 59 existing rows on `src/probos/agent_work_tags.py`, because that file differs: T1 to T9, N14 to N19, N21 to N64 and N40. The rewritten N16, N59 and N61 are among them. Also run the 11 new rows N65 to N75, and TS5 to TS8, whose killing tests read the shared rows file, which differs. Every other row's file and killing test are unchanged, so the campaign of record stands for them: 60 Python rows (P1 to P3, WP1, CP1, S1 to S3, A1 to A7, R1 to R24, G1, F1 to F4, W1, SD1, N1 to N13, N20) and TS1 to TS4 and TS9 to TS11. F26 adds no row: X22 asserts answers, and the two action rows are also refused at `capability_request.py:170`, so a mutant of `:216` survives X22.

**A1 and A2 campaign.** The Python rows run against `tests/test_ad1347_s2_chain_tags.py tests/test_ad1347_s3_execution.py tests/test_ad1347_s3_wiring.py tests/test_ad1156_plan_execute_mode.py tests/test_issue1419_failed_start_rollback.py`. The TypeScript rows are not in the Python campaign: mutate each line, run its vitest files from `ui/`, expect a failure, restore. Run TS1 to TS8 with `npx vitest run src/store/__tests__/capabilityApprovals.ad1347.test.ts src/store/__tests__/capabilityApprovals.ad1347a2.test.ts`, and TS9 to TS11 with `npx vitest run src/components/capability/__tests__/CapabilityRequestCard.ad1347.test.tsx`. The Python half of the wire is proven by X13's fixture equality and X22's rows.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| TS1 | `ui/src/store/capabilityApprovals.ts` | `if (isAgentWorkCall(payload, workItemId)) return true;` | `if (false) return true;` | `capabilityApprovals.ad1347.test.ts` cases 1 and 2 (A2: the line A2 rewrites) |
| TS2 | `ui/src/store/capabilityApprovals.ts` | `&& payload.scope_key === 'agent_work:' + workItemId;` | `&& true;` | vitest case 3 (`wi-other` accepted) |
| TS3 | `ui/src/store/capabilityApprovals.ts` | `&& value.can_retry_fulfilment === (value.status === 'approved' && canFulfil(value.kind, value.payload, value.work_item_id));` | `&& value.can_retry_fulfilment === (value.status === 'approved' && canFulfil(value.kind, value.payload, undefined));` | vitest case 2 |
| TS4 | `ui/src/store/capabilityApprovals.ts` | `\|\| !canFulfil(expected.kind, expected.payload, expected.work_item_id)))) {` | `\|\| !canFulfil(expected.kind, expected.payload, undefined)))) {` | vitest case 1 |
| TS5 | `ui/src/store/capabilityApprovals.ts` | `return isActionWirePayload(payload) && payload.action === 'agent_work_call'` | `return payload.action === 'agent_work_call'` | `capabilityApprovals.ad1347a2.test.ts` cases 1 and 2 (`tool_id_number` and every refusal row) |
| TS6 | `ui/src/store/capabilityApprovals.ts` | `\|\| !isRecord(payload.params) \|\| Object.keys(payload.params).length > 20` | `\|\| !isRecord(payload.params)` | `capabilityApprovals.ad1347a2.test.ts` case 1 (`params_21_keys`) |
| TS7 | `ui/src/store/capabilityApprovals.ts` | `\|\| !validText(payload.scope_key, 253) \|\| !validText(payload.thread_id, 64)` | `\|\| !validText(payload.scope_key, 253)` | `capabilityApprovals.ad1347a2.test.ts` case 1 (`thread_65`, `thread_null`) |
| TS8 | `ui/src/store/capabilityApprovals.ts` | `return hasPossibleActionPayloadSize(payload); // A2 (F19): the size and Unicode of Python's canonical form` | `return true; // A2 (F19): the size and Unicode of Python's canonical form` | `capabilityApprovals.ad1347a2.test.ts` case 1 (`size_4047`, `lone_surrogate`) |
| TS9 | `ui/src/store/capabilityApprovals.ts` | `&& request.payload?.tool_id !== 'repair' && !isAgentWorkApproval(request);` | `&& request.payload?.tool_id !== 'repair';` | `CapabilityRequestCard.ad1347.test.tsx` (the standing checkbox is offered) |
| TS10 | `ui/src/components/capability/CapabilityRequestCard.tsx` | `{ordinary && !agentWork && <p>Approval records this decision only; it does not replay the original action.</p>}` | `{ordinary && <p>Approval records this decision only; it does not replay the original action.</p>}` | `CapabilityRequestCard.ad1347.test.tsx` |
| TS11 | `ui/src/components/capability/CapabilityRequestCard.tsx` | `const agentWork = expected !== undefined && isAgentWorkApproval(expected);` | `const agentWork = false;` | `CapabilityRequestCard.ad1347.test.tsx` |

TS4's, TS6's and TS7's Line cells, and N38's, N40's, N41's and N63's cells, escape the bars as T3's does. Row TS9 lives in `capabilityApprovals.ts` but is killed by the card test.

## 11. Verified Against Codebase (2026-10-23, worktree `s23-consult` at `6b950acf`)

```
grep -n "async def _extract_and_execute_actions\|async def extract_and_execute_actions" src/probos/proactive.py
  3010, 2859   (signature :3010-3014; wrapper body :2865)
grep -n "rank = Rank.from_trust\|Rank.ENSIGN.value\|assign_min_rank = Rank.LIEUTENANT\|crew_min_rank = Rank.LIEUTENANT" src/probos/proactive.py
  3034, 3046, 3064, 3676, 3718
grep -n "BF-203: Strip unrecognized\|text = re.sub(handoff_pattern" src/probos/proactive.py
  3807, 3805 (each once)
grep -n "extract_and_execute_actions(\|post_budget=budget" src/probos/ward_room_pipeline.py
  292, 294   (process_and_post params thread_id :252, post_id :254)
grep -n "pipeline.process_and_post(" src/probos/cognitive/cognitive_agent.py
  7308   (thread_id, event_type, post_id from intent params :7309-7314)
grep -n "# Build prompts\|_COMPOSITION_MODES = \|def __init__(self, \*, llm_client: Any, runtime: Any)" src/probos/cognitive/sub_tasks/compose.py
  657, 585, 604
grep -n "PLAN_MODE_TOOL_IDS: frozenset" src/probos/cognitive/agent_mode.py
  68   (members :69-82)
grep -n "_APPROVAL_INBOX_TOOL_IDS: frozenset\|_NEVER_RAN_REFUSALS: frozenset\|def classify_tool_fault_error\|def restrict_to_plan_mode\|async def _park_or_admit" src/probos/cognitive/agentic_dispatch.py
  225, 298, 2023, 886, 1074
grep -n "admitted_turn: bool = False\|refuse_new_run(runtime, agent_id)\|arguments\[\"inner_loop_hook\"\]\|raise ValueError(\"plan_mode_tool_ids_invalid\")\|executor.restrict_to_plan_mode(plan_mode_tool_ids)" src/probos/cognitive/agentic_dispatch.py
  2613, 2623, 2663, 2823, 3453 (each once)
grep -n "class WorkItemAgenticExecutor\|async def run(\|async def _run_reserved(" src/probos/cognitive/agentic_dispatch.py
  2344, 2592, 2674
grep -n "async def block_on_request\|async def _resume\|async def _cancel\|base\[\"denial_reason\"\]" src/probos/cognitive/capability_gap_driver.py
  135, 291, 383, 408
grep -n "def awaited_command_request\|async def park_on_command_escalation" src/probos/cognitive/command_escalation_park.py
  55, 91
grep -n "def _maybe_fulfil_on_approval\|_APPROVAL_FULFILLERS: dict\|command_approval_request(decided) is not None" src/probos/routers/capability_requests.py
  432, 424, 464 and 609
grep -n "_ACTION_PAYLOAD_KEYS: frozenset\|def validate_action_payload\|def action_dedup_key\|async def file_action_request\|def count_pending_sync\|async def mark_fulfilled\|async def get(" src/probos/capability_request.py
  74, 165, 456, 779, 931, 1037, 1126
grep -n "\"task\": WorkTypeDefinition\|WorkTypeTransition(\"open\", \"in_progress\", requires_assignment=True)" src/probos/workforce.py
  181, 188   (no "scheduled" transition for task :187-197)
grep -n "async def transition_work_item\|async def claim_work_item\|async def unassign_work_item\|async def start_booking\|async def complete_booking\|async def cancel_booking\|async def list_bookings\|async def _expire_ttl_items" src/probos/workforce.py
  10753, 11437, 11534, 11568, 11633, 11689, 11726, 11931
grep -n "if self._dispatcher and not agent_pull:\|events.append(EventType.WORK_ITEM_CLAIMED)" src/probos/workforce.py
  11403, 11389
grep -n "def is_dispatchable\|async def dispatch_work_item" src/probos/mesh/work_item_router.py
  59, 68
grep -n "is_agent_post = \|target_agent_ids = target_agent_ids\[:thread_max_responders\]\|def find_targets_for_agent" src/probos/ward_room_router.py
  421, 502, 993
grep -n "\"mentions\": extract_mentions(body)\|AD-654d: Emit mention TaskEvent" src/probos/ward_room/messages.py src/probos/ward_room/threads.py
  messages.py:244, 247; threads.py:498, 501
grep -n "async def create_thread\|async def create_post\|async def get_channel_by_department\|async def list_threads" src/probos/ward_room/service.py
  413, 466, 328, 344
grep -n "def dm_channel_name" src/probos/ward_room/channels.py
  19   (eight-character prefixes collide, :20-25)
grep -n "SEAM_AGENTIC_RUN: Final\|SEAM_AGENT_WORK: Final\|S1_SCOPE: Final\|def standing_stop\|def refuse_new_run\|def active(self)" src/probos/agent_stop.py
  68, 70, 77, 590, 602, 397
grep -n "def crew_member\|def execution_allowed\|def claim_allowed\|def eligible_members\|def notice_recipients\|def terminal_notices_due\|def claim_notice\|def _stopped_now\|def _holds_tool" src/probos/agent_work.py
  (none for the first two: added by §7.7); 416, 407, 437, 446, 461, 501, 505
grep -n "AGENTIC_RUN_OWNERS: dict\|\"agent_work\": (" tests/fixtures/ad1343_seam_registry.py
  88, 224
grep -n "never_ran == " tests/test_ad1156_plan_execute_mode.py
  539
grep -n "(\"work_item_store\", \"workforce store stop\")\|def test_every_step_that_stops_a_component_hands_that_component_to_the_guard" tests/test_issue1419_failed_start_rollback.py
  1141, 1399
grep -n "assert list(params)\[:21\]\|assert list(params)\[26:\]" tests/test_ad1155_loop_until_done.py
  508, 538   (the tail pin at :538 lists every name after the 26th, so it gains `confinement`: §7.8a)
grep -n "def _wire_task_completion_notifier\|if _wire_task_completion_notifier(runtime=runtime, config=config):\|agentic_executor = WorkItemAgenticExecutor(llm_client=llm_client)" src/probos/startup/finalize.py
  3368, 5531, 2196
grep -n "runtime.agent_work = None" src/probos/startup/shutdown.py
  1674
grep -n "from probos.agent_work import AgentWorkService\|self.agent_work: \"AgentWorkService | None\" = None\|self.event_log = EventLog" src/probos/runtime.py
  167, 1135, 707
grep -n "async def audit_governed_query\|category=\"audit\",\|event=\"event_log_query\"," src/probos/substrate/event_log.py
  1065, 1106, 1107
grep -n "_TOOL_EVENT_CATEGORY = \|def tool_record_identity" src/probos/tools/executor.py
  44, 311   (without a catalog the retained tool id is opaque :317-325)
grep -n "def _register_event_log_query_tool\|allowed_departments=(\"engineering\", \"science\", \"security\")" src/probos/startup/communication.py
  46, 74
grep -n "max_pending_per_agent: \|class ApprovalInboxConfig" src/probos/config_models/experience.py
  158, 15
grep -n "def apply_dm_sanity" src/probos/cognitive/dm_sanity_gate.py
  578   (a non-DmSanityGate runtime is a no-op :589-591)
grep -n "SRP_MAX_BODY_LINES = \|SRP_MAX_DIRECT_METHODS = " scripts/check_architecture_principles.py
  187, 188   (the trigger is "> 15"; AgentWorkService and AgentWorkRunner each have 15)
```

**SEARCH uniqueness.** Each SEARCH's distinctive line was grepped and occurs once in its file:
- `agentic_dispatch.py`: 299, 750, 856, 2029, 2613, 2663, 2823, 3453. The 2735-2738 block is unique because `_run_reserved` alone has `inner_loop_hook` directly before the return annotation.
- `proactive.py`: 3805, and the two `def` lines.
- `compose.py`: 657.
- `finalize.py`: 3401, 5531.
- `routers/capability_requests.py`: 17, 488.
- `shutdown.py`: 1671.
- `capability_gap_driver.py`: the turn-promotion import and `if is_promoted_turn(updated):` each occur once.
- `agent_stop.py`: 88.
- `ward_room_pipeline.py`: `if agent and self._proactive_loop:` occurs twice (291, 307), so that SEARCH carries the next line, which occurs once.

### A1 additions (2026-10-23, worktree `bf900-consult` at `c5ad2b4b`)

```
grep -n "def repair_action\|def can_fulfil_request\|def list_actionable\|can_fulfil_request(req)" src/probos/capability_request.py
  127, 150, 1118, 1123
grep -n "can_fulfil_request" src/probos/routers/capability_requests.py
  20, 83   (_serialize's can_retry_fulfilment, :82-84)
grep -n "function canFulfil\|canFulfil(\|function isRecord\|const FULFILMENT_KINDS" ui/src/store/capabilityApprovals.ts
  7, 221, 245, 283, 307, 308 (twice)
grep -n "agent_work_approval(decided)\|mark_fulfilled(decided.id) is not None" src/probos/routers/capability_requests.py
  487, 493
grep -n "_serialize\|validate_action_payload(decoded)" src/probos/capability_request.py src/probos/routers/capability_requests.py
  capability_request.py:446 (an action payload is validated on decode, else None)
grep -n "def _start\|self._active\|block_on_request\|finally:" src/probos/agent_work_runner.py
  235, 361-368, 407, 444-445
grep -n "_resolve_if_settled\|await self._resume(store" src/probos/cognitive/capability_gap_driver.py
  187, 190, 212
grep -n "_STRICT_APPROVAL_DISPATCH\|_NEVER_PARK_ACTIONS\|_ALWAYS_TIER_3_ACTIONS\|_APPROVAL_PARAM_STRIP_KEYS\|async def _park_or_admit" src/probos/cognitive/agentic_dispatch.py
  105, 233, 242, 244, 838, 850, 1136, 1174, 1191-1208
grep -n "test_park_or_admit_keeps_its_pinned_signature" tests/test_ad1154_approval_inbox.py
  1964   (six names pinned; A1 adds none)
grep -n "park=not is_crew and bool(work_item_id)\|parked_request_id" src/probos/cognitive/agentic_dispatch.py
  2366, 2529, 4281
grep -n 'stopped_reason = "' src/probos/cognitive/swe_harness/agentic_loop.py
  1808 error, 2011 token_budget, 2050 complete, 2257 max_iterations
grep -n "async def notice_recipients" src/probos/agent_work.py
  466
grep -n "max(1, self._ttl_seconds // 3600)" src/probos/agent_work_runner.py
  512
grep -n "ttl_seconds: int = Field" src/probos/config.py
  3585 (ge=60)
grep -n 'params.get("confirmation_token")' src/probos/tools/browser/tool.py
  1600
grep -n "from probos.agent_work_tags import agent_work_service, apply_agent_work_tags" src/probos/proactive.py
  3816
grep -n "SRP_MAX_BODY_LINES\|SRP_MAX_DIRECT_METHODS\|methods > SRP" scripts/check_architecture_principles.py
  187, 188, 568
grep -n "^class _ApprovalGuardMixin\|^class DispatchToolExecutor" src/probos/cognitive/agentic_dispatch.py
  970, 1455
grep -n "def is_dispatchable\|dispatchable_tags" src/probos/mesh/work_item_router.py src/probos/config.py
  work_item_router.py:59-66; config.py:3490 (["consultation"])
grep -n "class _Dispatcher" tests/test_bf887_continue_resumes_the_promoted_turn.py
  128
```

### A2 additions (2026-10-23, worktree `bf900-consult` at `f035964c`)

```
grep -n "_MARKER_RE: Final\|class _OpenBlock\|def _inert_line_ends\|fenced = fenced != fence\|block = None\|_FENCE_RE: Final" src/probos/agent_work_tags.py
  94, 133, 144, 154, 195, 99
grep -n "_ACTION_PAYLOAD_MAX_CHARS = \|_TOOL_ID_RE = \|_ACTION_RE = \|_MAX_ACTION_PARAM_KEYS = \|_SCOPE_KEY_MAX = \|_SESSION_ID_MAX = \|_THREAD_ID_MAX = \|def validate_action_payload\|encoded.encode" src/probos/capability_request.py
  73, 77, 78, 79, 80, 81, 82, 191, 253
grep -n "def agent_work_call\|every other action still has no fulfiller\|def can_fulfil_request\|^class CapabilityRequest:\|async def mark_fulfilled" src/probos/capability_request.py
  155, 160, 176, 535, 1063
grep -n "from probos.agent_work_runner import agent_work_approval\|Honest-degrade throughout\|return await store.mark_fulfilled(decided.id) is not None\|async def _work_item_value_confirmed\|async def _maybe_issue_standing_rule\|# AD-1328 S2b: no standing rule" src/probos/routers/capability_requests.py
  17, 442, 493, 557, 577, 617   (the command branch's handler: 476-486)
grep -n "return await request_store.mark_fulfilled" src/probos/execution/command_escalation.py
  312
grep -n "try:" src/probos/cognitive/repair_issue.py
  295, 372   (the repair consumer degrades inside fulfil and decline)
grep -n "const ACTION_KEYS\|export function standingApprovalEligible\|the original action was not replayed\|function validText\|function hasPossibleActionPayloadSize\|function isAgentWorkCall\|function canFulfil" ui/src/store/capabilityApprovals.ts
  8, 125, 208, 225, 229, 248, 253
grep -n "standingApprovalEligible(expected)\|const ordinary\|does not replay the original action\|Grant standing approval" ui/src/components/capability/CapabilityRequestCard.tsx
  52, 55, 134, 146
grep -n "does not replay the original action" ui/src/components/capability/__tests__/ApprovalWave.test.tsx
  118
grep -n "if (get().loaded || get().loading) return;" ui/src/store/useSettingsStore.ts
  111
grep -n "class CapabilityRequestDecideRequest" src/probos/api_models.py
  271
CommonMark 0.31.2 (https://spec.commonmark.org/0.31.2/), read 2026-10-23: 2.1 a line ending is LF, CR not followed by LF, or CRLF;
  4.5 a fence is three or more backticks or tildes, not mixed; a backtick fence's info string has no backtick; the closer is the same
  character, at least as long, up to three spaces of indent, followed only by spaces or tabs; an unclosed fence runs to the end of its
  container; 6.1 a span runs between backtick strings of equal length, an unmatched string is literal, line endings inside become
  spaces, and backslash escapes do not work inside.
```

### A2b additions (2026-10-23, worktree `bf900-consult` at `f035964c`, and the A2-applied contract)

```
grep -n "^from __future__ import annotations\|^import re" src/probos/agent_work_tags.py
  47, 50   (so `re.Match[str]` in a parameter annotation is not evaluated)
grep -n "requires-python" pyproject.toml
  9: requires-python = ">=3.12"
contract §7.32 pair 4: `spans = _inert_spans(text)` runs before the marker loop, so C15's list_markers case (no marker) reads its one line
CommonMark 0.31.2 (https://spec.commonmark.org/0.31.2/), re-read 2026-10-23: 2.2 tabs behave as a tab stop of four; 4.1 and 4.2 up to three
  spaces before a thematic break or an ATX heading; 4.4 an indented code block cannot interrupt a paragraph; 4.5 the closing fence may be
  preceded by up to three spaces of indentation (not tied to the opener), and up to the opener's indentation is removed from content
  lines; 5.2 the text after a list marker sets the item's content column.
probe-s23-scanner-diff-a2.txt (markdown-it-py 4.0.0, 3000 flat documents, the A2 scanner): 35 minimal documents acted where CommonMark
  is inert; 6 of the 14 closing-direction ones begin with a four-space opener (lines 5, 7, 8, 9, 19, 21), and 8 of the 9 indented-code
  ones follow a fence closer (lines 6, 11, 12, 14, 16, 17, 18, 25)
```

### A2c additions (2026-10-23, the A2b-applied contract and the orchestrator's measurements)

```
probe-s23-scanner-diff2.py on the A2b oracle befc0f10 (12,000 documents with list markers, headings, breaks and tabs, seed 1347):
  90 minimal EXTRA documents, 46 lazy-quote and 44 not; 39 of the 44 read right by candidate 3 (f035964c): a fence in a list
  item kept open past a line left of the item's content column
probe-s23-real-posts.py on ward_room.db (16,386 bodies, 144,300 variants): A2b 0 non-lazy EXTRA; no body holds a fence on a marker
  line, a fence indented one column or more, or an unclosed fence
D:\ProbOS-worktrees\s23-proto\src\probos\agent_work_tags.py:235-240 (prototype F1'): a list fence floored at its marker line's
  column, else 0 within three columns and max(2, column - 3) beyond; 44 -> 5 non-lazy, 39 -> 0 regressions
CommonMark 0.31.2 5.2 (fetched for A2b): the text after a list marker sets the item's content column; an empty item's
  content column is the marker plus one
```

### A2d additions (2026-10-23, candidate 4 `9319b37d`, the prototype in `s23-proto` and the orchestrator's measurements)

```
D:\ProbOS-worktrees\s23-review3\src\probos\agent_work_tags.py:248  item_column = _columns(head) + (0 if head[-1] in " \t" else 1)
D:\ProbOS-worktrees\s23-review3\src\probos\agent_work_tags.py:265  elif content[len(head):].lstrip().startswith(">"):
D:\ProbOS-worktrees\s23-review3\src\probos\capability_request.py:170  payload is None or payload["action"] != AGENT_WORK_CALL_ACTION
D:\ProbOS-worktrees\s23-review3\src\probos\capability_request.py:216-217, :220-221, :233-234  the action, params-key and canonical-JSON refusals
D:\ProbOS-worktrees\s23-review3\src\probos\capability_request.py:189  allow_nan=False
probe-s23-r3-findings.py against candidate 4: F22 family (1,620 documents) 72 act where CommonMark is inert, every one with
  padding of 5 or more columns; F23 family (900) 81 MISSING regressions against candidate 3 and 9 EXTRA; F24 family (25
  characters str.lstrip strips and CommonMark does not) 25 of 25 ignored. Prototype: 0, 0 EXTRA with 42 MISSING (candidate
  3's own), 0
probe-s23-r3-f26-census.py: the 35 rows end on 10 of validate_action_payload's 13 returns (:217, :221, :234 unreached);
  with action_number and action_grammar, :217 is reached by both; X22 passes; the HXI agrees (6 vitest cases)
probe-s23-scanner-diff3.py on the prototype, seeds 1347, 2024, 7, 31337 (12,000 documents each, markdown-it-py, baseline
  9319b37d): non-lazy EXTRA 0, 1, 1, 0 (R15 shapes); lazy EXTRA 64, 65, 72, 71, of which 17 to 20 per seed are new and all
  one shape: a quote line, then a line of U+00A0, U+2003 or U+3000 and `>` (R13, read as plain text since F24)
CommonMark 0.31.2 (fetched 2026-10-23): 5.2 rule 2 (an item starting with indented code is the marker and one space),
  rule 3 ("A list item can begin with at most one blank line"); 2.1 (a blank line holds only U+0020 or U+0009);
  2.2 (a tab advances to a stop of 4; `-` + two tabs + `foo` is an item holding indented code)
ABSENCE: no bare strip()/lstrip() in _inert_spans after A2d
  RUN: Grep "lstrip|strip\(\)" D:\ProbOS-worktrees\s23-proto\src\probos\agent_work_tags.py
  FOUND: :146-149 (_fields), :254 and :289 (lstrip(" \t")), :311 (_block_tag), :336, :338 (attribute.strip()), :368
  HOLDS: yes; _inert_spans (:219-299) has only the " \t" forms; the others are field values, an attribute, the post
probe-s23-wide-next-line.py (A2d gate; markers - * + 1. 1), padding 5 to 8 and a tab pair, then a second line): candidate
  4 0 MISSING, and EXTRA 30/50/50 at 6/7/8 columns; A2d 100/50/20 MISSING at 4/5/6 columns and 0 EXTRA; register R14
  (decided: Option A)
```

### A2f additions (2026-10-23, candidate 5 `478180b8`, the prototype in `s23-proto` and the orchestrator's measurements)

```
D:\ProbOS-worktrees\s23-review4\src\probos\agent_work_tags.py:291  elif rest.lstrip(" \t").startswith(">"):
D:\ProbOS-worktrees\s23-proto\src\probos\agent_work_tags.py:291  elif rest.lstrip().startswith(">"):  (the only bare lstrip()
  in the file besides none: :259 and :313 are lstrip(" \t") and lstrip("@"))
D:\ProbOS-worktrees\s23-review4\src\probos\agent_work_tags.py:44, :238  the two docstrings that said "other than a space or a tab"
D:\ProbOS-worktrees\s23-review4\src\probos\agent_work_tags.py:370  return "".join(kept).strip(), tuple(tags)  (an inert and an
  acted single-line marker leave the same cleaned text, so the three C17 rows change only their tags)
D:\ProbOS-worktrees\s23-review4\tests\test_ad1347_s3_execution.py:871-874, :906-907  the F26 claims A2f corrects
D:\ProbOS-worktrees\s23-review4\ui\src\store\capabilityApprovals.ts:232-235  "Python owns exact canonical admission ...
  Valid JSON numbers can decode to either infinity; NaN cannot." (the size check refuses NaN only)
review round 4: F27 real posts (QUOTATION_STAYS_INERT unicode_lazy; the `- - x` fence shape): 9319b37d 0 items, candidate 5 1;
  F26: json.loads('{"depth": 1e400}') -> inf -> validate_action_payload returns at :234
probe-s23-r4-f27.py (markdown-it-py): shapes (a) with U+00A0, U+2003, U+3000 and (b): 9319b37d 0 tags, candidate 5 1,
  CommonMark inert; the F24 control: CommonMark acts, 9319b37d 0, candidate 5 1
probe-s23-scanner-diff3.py on the prototype (seeds 1347, 2024, 7, 31337; 12,000 each; baseline 9319b37d): non-lazy EXTRA
  regressions 0, lazy 0, MISSING 20, 20, 21, 21 (R14's wide-padded shape); control on candidate 5: lazy 17, 20, 19, 20,
  non-lazy 0, 1, 1, 0
probe-s23-r3-findings.py on the prototype: F22 EXTRA 0; F23 EXTRA 0, MISSING 42; F24 MISSING 25 of 25 (as on 9319b37d)
tests on the prototype: test_ad1347_s2_chain_tags.py 106 passed, 3 failed (the three rows A2f relabels)
ward_room.db (16,386 bodies, read-only, A2d's scan): no body holds Unicode whitespace before `>`
ABSENCE: nothing outside agent_work_tags.py and C17 pins the quote test or the three row ids
  RUN: Grep "space or a tab|lstrip\(\" \\t\"\)\.startswith|nbsp_before|em_space_before|nbsp_line_after" over s23-review4,
  excluding prompts/
  FOUND: agent_work_tags.py:238, :291; test_ad1347_s2_chain_tags.py:579, :580, :589
  HOLDS: yes
```

## 12. Absence Verified (2026-10-23)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | nothing subscribes to WORK_ITEM_CLAIMED, so nothing runs a pull-claimed item | `rg "work_item_claimed\|WORK_ITEM_CLAIMED" src/probos` | `event_persistence.py:462` (persisted list), `events.py:108`, `workforce.py:11389` (emit) | yes |
| AV2 | AD-1343 S2 (ending a running turn) is not built | `rg "AD-1343 S2" src/probos` | `agent_stop.py:92` only (`does_not_end`) | yes |
| AV3 | none of the new names exist yet | `rg "agent_work_runner\|agent_work_tags\|AgentWorkRunner\|ToolCallConfinement\|CLAIM_WORK\|SELF_TASK\|REQUEST_WORK"` (repo, excluding prompts) | no files | yes |
| AV4 | the Captain's one-to-one chat does not call the extractor | `rg "extract_and_execute" src/probos/cognitive/dm/reply_pipeline.py` | `:1240-1316` (`extract_and_execute_dms`, `extract_and_execute_notebooks`) only | yes |
| AV5 | two test stubs fake `extract_and_execute_actions` with a fixed signature; no other double constrains its kwargs | `rg "def _fake_extract\|post_budget=None\):" tests`; `rg "extract_and_execute_actions *=" tests` | `tests/test_bf237_pipeline_post_budget.py:25` and `tests/test_bf238_post_budget_telemetry.py:174` (both updated: §7.3a, §7.3b); the other doubles are `AsyncMock`s | yes (corrected after the M1 build: the first claim searched only for `def extract_and_execute_actions`) |
| AV6 | no test pins `S1_SCOPE["refuses"]` text | `rg "browser actions and every\|result is escalated unverified"` (excluding prompts) | `agent_stop.py:88` only | yes |
| AV7 | an AD-1154 browser `action` has no fulfiller (A2, F21: corrected; the first FOUND listed only the map) | read `routers/capability_requests.py:453-526` | the repair branch (AD-1206, :453-464), the AD-1328 command branch (:465-486; its fulfiller ends at `execution/command_escalation.py:312`), the agent-work branch (:487-493), then `_APPROVAL_FULFILLERS` (`continue`, `grant`, `install`, `build`, :425-430) | yes for a browser action; "every other action" was false |
| AV8 | nothing but `capabilityApprovals.ts` defines or calls `canFulfil` | `rg "canFulfil\(" ui/src` | `capabilityApprovals.ts:245,283,307,308` only | yes |
| AV9 | `_park_or_admit` has one production caller | `rg "_park_or_admit" src` | `agentic_dispatch.py:840` (call), `:1136` (def) | yes |
| AV10 | `split_agent_work_tags` has one production caller | `rg "split_agent_work_tags" src` | `agent_work_tags.py:252` | yes |
| AV11 | nothing restarts a start `_start` dropped during a run (F2's premise) | read `agent_work_runner.py:361-368`, `:444-445` | `_start` returns; `finally` only discards | yes |
| AV12 | the HXI has no special path for AD-1328 command approvals (register R10) | `rg "run_command\|command escalation\|AD-1328" ui/src` | no matches | yes |
| AV13 | no test pins a card or store line A2 changes, except the ordinary-action sentence | `rg "Approval records this decision only\|standingApprovalEligible, standingApprovalPolicy\|approvalDisplayText, capabilityFeedbackText"` (excluding prompts); `rg "CapabilityRequestCard" tests` | the card source only; `ApprovalWave.test.tsx:118` (`/does not replay the original action/`, kept for an ordinary action); `test_ad1164_continue_or_ask.py:1080-1081` pins two card lines A2 does not touch | yes |
| AV14 | nothing outside `agent_work_tags.py` uses `_inert_line_ends`, `_OpenBlock` or its `_FENCE_RE` | `rg "_inert_line_ends\|_OpenBlock\|tags_module\._\|agent_work_tags import _"` (excluding prompts) | `agent_work_tags.py:133,144,158,181,183,201` only (A2's C15 begins patching `tags_module._FENCE_RE`) | yes |
| AV15 | no other UI file renders the ordinary-action sentence or the "not replayed" feedback | `rg "does not replay\|not replayed\|standingApprovalEligible\|isAgentWorkCall\|canFulfil\b" ui/src` | `CapabilityRequestCard.tsx:52,134`, `capabilityApprovals.ts:125,165,208,248,253,292,316-318,332`, `ApprovalWave.test.tsx:118,169` | yes |
| AV16 | the agent-work branch was the only unguarded await in `_maybe_fulfil_on_approval` (F20) | read `routers/capability_requests.py:453-526`, `cognitive/repair_issue.py:293-383` | the repair consumer wraps fulfil and decline (:295, :372); the command branch (:476-486) and the map (:504-513) have handlers; :493 had none | yes |
| AV17 | no name A2b adds to `agent_work_tags.py` exists there | `rg "indent\|column\|head\|opened\|closer =\|paragraph\|width\|top_fence\|list_fence\|_columns\|_closes\|_LIST_ITEM_RE\|_PARAGRAPH_END_RE" src/probos/agent_work_tags.py` at `f035964c`; `rg "(head\|indent\|column\|width\|opened\|paragraph\|closer) ="` over the contract | no matches in the file; the contract's only hit is `head =` in `agent_work_runner.py` (§7.9) | yes |
| AV18 | no test except C17 hands the scanner a marker on a line indented four or more columns, or a fence after a list marker, so A2b changes no other expectation | `rg -i "( {4,}\|\\t)\[/?(SELF_TASK\|REQUEST_WORK\|CLAIM_WORK\|DECLINE_WORK)" tests`; the same over the contract; `rg "(- \|\* \|\d\. )\{(FENCE\|TILDES\|LONG_FENCE)\}"` over the contract | no test files; contract :5210 (`fence_indented_in_a_list_item`, unchanged) and :5253 (the row A2b replaces); no list-marker fence | yes |

## 13. Prior Art and Blind Spots

- **Internal prior art.**
  - AD-1156 plan mode: an allowlist enforced at the call; **adopted** as the confinement's shape.
  - AD-1154 inbox, AD-1328 S2b/S2c and AD-855: park, approve and resume; **reused unchanged**, with one new fulfilment branch.
  - The crew executor runs a colleague's loop from the Ship's Computer (`finalize.py:2196`); **adopted**.
  - BF-200 and AD-1343 post as `system`; **adopted** as the author of every Ship's Computer post.
- **External prior art.** The issue's review covered it: Contract Net (an announcement, then the first claim wins) is **adapted** through the notice and AD-1187's compare and set; CrewAI's in-run delegation was **rejected**. This slice is ProbOS plumbing, so I ran no new external search. `docs/research/reference-projects.md` was not re-checked (considered, deferred).
- **Blind spots the issue does not name, each handled or registered:**
  - Ward Room DM channel names collide on 8-character prefixes. Handled: notices go to the department channel.
  - A claimed `task` sits in `scheduled`, which its TTL cannot cancel. Handled: the runner starts the booking at once (register R1).
  - AD-855 writes the denial reason after the cancel event. Handled: the reason is read from the request.
  - An agent-run DM thread origin is a Ward Room thread. Handled: origin channel `ward_room`.
  - A pull-claim from an agent's own loop also triggers the runner. Accepted: the runner is the executor of record.
  - The pull tools are offered inside an agent-work run, so a claim made there is filed for approval (register R7).
  - A1, register R8 (F9, P2, injected-only): a post that fails in both the origin thread and the department channel still consumes its claimed notice; a retry needs a release operation on `agent_work_notices` (a store contract change). The decline's acknowledgement no longer says "was told" then.
  - A1, register R9 (F5's remainder, P3): the call a claimant filed just before it was stopped stays pending; approving it marks it fulfilled and runs nothing (AD-855 and the admission act only on an item parked on it).
  - A1, register R10 (pre-existing, outside this batch; read, not executed): AD-1328's command approvals are marked fulfilled (`command_escalation.py:312`) and the HXI's `canFulfil` accepts only the repair action, so the HXI likely refuses their decision response too. To be filed as a BF.
  - A1, register R11 (P3): the gate files a `browser` `fill_credential` call, which AD-1154 refuses after the approval, so the Captain decides something that cannot run; nothing is entered.
- **A2 (review round 2).**
  - Prior art: CommonMark 0.31.2 (https://spec.commonmark.org/0.31.2/), §2.1, §4.5 and §6.1. **Adopted** for fences, spans and line endings; **adapted** for indentation, quotes and spans, each difference named in §9. `docs/research/reference-projects.md` was not re-checked: this is a repair (considered, deferred).
  - Register R2 is closed: no standing rule is offered or issued on an agent-work approval.
  - Register R12 (P3, injected-only): the HXI's size bound counts each number as one character (§9).
  - Register R13 (P3, ordinary but rare): lazy quote continuation and a span across lines are read as written (§9). A2b brought indented code into scope; A2c closed the list shape R13 held, by counting a tracked fence's closer from its item's column. A2g (F28): R13 also holds the block on the lazy lines after a quote whose next line is led by U+00A0, U+2003, U+3000 or another non-tab blank and `>`. This is the acting direction of the class R13 already accepts; candidate 5 was inert there only because it read that line as an opener.
  - Register R14 (P3): an inert tag is removed silently, so an agent that fences its real request gets no acknowledgement. A candidate fix is a "read as an example" line; it changes `split_agent_work_tags`'s return (considered, deferred). A2b widens it: a tag indented four or more columns after a blank line (a list item's continuation) is inert, and so is the text after a fence-like line indented four or more columns, until a closer or a line left of its floor (A2c). A2d (decided at the A2d gate): a tag indented four or more columns after a marker line with five or more columns of padding is inert, though CommonMark reads it as a paragraph up to the item's content column plus three. Against candidate 4 this is a regression: 100 and 50 MISSING documents at 4 and 5 columns in the orchestrator's `probe-s23-wide-next-line.py`, and 20 to 21 per seed of the differential. It cannot be separated from F22's repair: candidate 4 got those lines right only by reading the wide line as paragraph text, and that same reading made it act on indented code at 6 to 8 columns (130 EXTRA documents). Keeping the first without the second needs indentation measured from the item's column, which is this register's own deferred fix (considered, deferred: a code floor for wide items alone fixes one case of the class).
  - Register R15 (P3, ordinary but rare; A2c): the list reading tracks one list item and has three blind spots. A lazy line ends the tracked item (`out_of_scope_lazy_line_then_an_item_fence_is_read_as_written`), a line that only looks like an item (a setext `-`, an ordered marker or an empty item that cannot interrupt a paragraph, a thematic break made of markers, or, A2d, a second marker after five or more columns of padding, `-     - x`) is tracked as one, and a nested item is tracked at its innermost marker's column only, so a fence at the outer item's column after `- - text` or an item inside an item is floored at 0 (found by the orchestrator's differential: 6 of the 7 non-lazy documents left on four seeds of 12,000, each also acted on by candidate 3; the seventh is the lazy-line shape; mechanical repair 9). Any of them acts on a tag where CommonMark is inert only if the top reading is wrong too. Measured reach 0: no Ward Room body holds a fence indented one column or more. Considered, deferred: a container stack with the lazy rule.
  - Considered, deferred: `inspectActionPayload`'s field checks could share `isActionWirePayload`. Deferred so that round 3's delta stays off the inspection path ordinary approvals use.
- **A2b (the scanner's CommonMark differential).**
  - Evidence: the orchestrator's probe ran the A2 scanner against markdown-it-py 4.0.0 over 3000 generated flat documents (§11, A2b additions).
  - **Adopted** from CommonMark 0.31.2, re-read 2026-10-23: §2.2, §4.1, §4.2, §4.4 (indented code does not interrupt a paragraph), §4.5 (a closer takes up to three spaces of indentation, independent of the opener) and §5.2 (the content column).
  - **Rejected:** one deterministic indentation rule, whether A2's "any indentation" or a closer within three columns of its opener alone. Without container parsing, one reading shifts phase on an indented-code line and takes the real opener for its closer.
  - **Adapted:** two readings in one pass, inert when either says so. They share one opener size and one closer test (`_closes`).
  - Considered, deferred: parsing list containers (their blank-line and lazy rules), which would remove the over-inert residue.
- **A2d (review round 3: F22 to F26; the Architect's round-three decision, continue).**
  - Prior art: CommonMark 0.31.2, re-read 2026-10-23. §5.2 rules 1 to 3: one to four columns of padding set the content column; with five or more, the item starts with indented code and the column is the marker plus one; an item that starts with a blank line takes the marker plus one and "can begin with at most one blank line". §2.1: a blank line holds only spaces and tabs. **Adopted** for the last marker on a line (`_item_columns`). §2.1's Unicode whitespace is **rejected** as indentation (F24); A2f (F27) still reads it before `>` as a quote. markdown-it-py stays the differential oracle (§11). `docs/research/reference-projects.md` was not re-checked: this is a repair (considered, deferred).
  - Where the tracker stops: §5.2's content column for the last marker on a line, and the end of an empty item at a blank line. General CommonMark compliance is not claimed. Every shape beyond that is R13, R14 or R15; no register entry is added (item-start conditions are R15's "line that only looks like an item").
  - (Withdrawn by A2f, F27.) A2d added a shape to register R13 here: a line that starts with U+00A0, U+2003 or U+3000 and `>`, straight after a quote line, acted on although CommonMark reads it as a lazy continuation inside the quote. That was a regression against candidate 4, and A2f reverts it (the A2f entry below).
  - Register R14 is smaller on the F23 family (the over-inert count fell from 123 to 42, which is candidate 3's own; orchestrator's enumeration) and gains one shape: a tag indented four or more columns after a wide-padded marker line (the R14 entry above).
  - Register R15 gains two examples, an empty item that cannot interrupt a paragraph and `-     - x`. Candidate 4 reads both the same way.
  - F26 (corrected by A2f): the shared rows end on 11 of `validate_action_payload`'s 13 exits. X22 checks answers, not which refusal gave them, so no mutation row covers the action rows. `_REFUSALS`'s comment names the other two: a non-string params key, which no JSON payload reaches, and a payload `_canonical_json` refuses, which JSON text does reach (`1e400` decodes to an infinite float) but which the rows exclude, because Python owns canonical admission and the HXI's size check is a lower bound that does not refuse an infinite number (register R12).
  - Blind spot handled: no fence opens on a wide line, so `_FENCE_RE` is not read there. C15's one-read-per-line count still holds, because none of its rows has a wide line.
- **A2f (review round 4: F27 and F26's remainder; the Architect's second brake decision, continue).**
  - F27 (P2, ordinary but rare, a regression of A2d against candidate 4): the quote test strips any whitespace again (`str.lstrip()`), as candidate 4 did. Every line candidate 5 reads as a quote is a quote here too, so the change can only make a line inert. Against candidate 4 (four seeds of 12,000): no document is acted on where candidate 4 was inert; 20 or 21 plain tags per seed are dropped, all R14's wide-padded shape.
  - Register R14 gains F24's shape (P3, ordinary but rare, not a regression; reach 0 of 16,386 Ward Room bodies): a line that starts with U+00A0, U+2003, U+3000 or another non-tab blank and `>` is a paragraph in CommonMark when it stands alone, and its tag is not acted on here (`out_of_scope_nbsp_before_a_quote_mark_is_a_quote`, `out_of_scope_em_space_before_a_quote_mark_is_a_quote`). Separating it from the lazy and nested-fence lines CommonMark keeps inert needs the container parsing R13 and R15 defer (considered, deferred). A2g (F29): the shape includes such a line after list item markers (`- `, U+00A0, `> [SELF_TASK]`), which CommonMark reads as the item's paragraph. The quote test has run after the markers since A2f, so the reviewed code has held this shape since then.
  - Registers R13 and R15 do not gain the Unicode-blank shapes: straight after a quote line such a line stays inert (`nbsp_line_after_a_quote_is_quoted`), and so does the last line of `- - x` / `  ~~~` / `~~~` / U+2003 `>`. The second is inert only because of the quote test, so any narrowing of that test must rerun the R13 and R15 differential.
- **A2g (review round 5: F28 and F29; the Architect's third round-three-brake decision, rescope).**
  - F28 (P3, ordinary but rare, not a regression; reach 0 of 16,386): register R13 (the entry above). Its ASCII twin, the plain `>` document, is acted on by candidates 4, 5 and 6. The orchestrator's family (960 documents) finds 288 such documents against candidate 5, every twin acted on by candidate 5 itself, and no new class.
  - F29 (P3, the over-inert direction, not a regression): register R14 (the A2f entry above). Its twin, `- > [SELF_TASK]`, is a quote in a list item, inert in every candidate and in CommonMark.
  - The ASCII twin rule (§14 property 3) decides both. It also gives the earlier call: F27 is a regression, because candidate 4 left its twins inert.
  - Process: A2f's round-4 criterion (§15) asked for no document acted on where either candidate 4 or candidate 5 was inert. The two disagree on the F27, F28 and F29 documents, so no quote predicate could meet it. A criterion against two baselines is set only after checking that they agree on the shapes it covers.

## 14. Diff Reviewer: properties to verify

1. With `agent_work` off:
   - no new path is entered: while `runtime.agent_work` is None the extractor neither imports nor calls the tag module (a runtime holding any other object asks only `agent_work_service`, which answers None; A1, F12);
   - the compose system prompt equals the builder's output;
   - finalize builds no runner and `runtime.agent_work_runner` is None;
   - the executor's run arguments and its unarmed state are unchanged;
   - the router's and AD-855's behaviour for every non-agent-work request and item is unchanged.
2. Every agent-created item is created through `AgentWorkService` only. `created_by` is the resolved requester slot, and no path stamps the Captain.
3. Tags are acted on only for Lieutenant and above, at most three per reply. While on, every tag and stray marker, in any letter case and closers included, is removed from the posted text. (A2) A marker in an inert region is removed alone and never acted on. The inert regions are: a code fence read by character and run length, closed only by a matching run and running to the end when unclosed, with indentation read both at the top level and as in a list item (A2b: inert when either reading says so; A2c: a fence in a list item ends at a non-blank line left of the item's content column, and that line is read afresh; A2d: that column is CommonMark's for the line's last marker, five or more columns of padding make the rest of the marker line indented code, and an item with no content yet ends at a blank line); an indented code block that does not continue a paragraph (A2b); a `>` line (after any whitespace, A2f; CommonMark counts spaces and tabs only, so a line led by another blank errs toward inert, register R14, F29 after a list item marker included; A2g: a block on the lazy lines after such a line is acted on, as after a plain `>` line, register R13, F28), also after list item markers; an inline code span within one line. Lines end at LF, CRLF or CR. A block holds the blocks opened inside it and closes only on its own closer once they are closed; a block holding any other marker is not acted on. C17's rows are the grammar, and §9 names what is read as text; general CommonMark compliance is not claimed. The parse is one linear pass; a fault on one tag is acknowledged and the reply goes on. (A2g) A difference between two candidates on a document that holds a line led by a non-ASCII blank and `>` is judged by the document's ASCII twin (each such blank replaced by one space), which both quote tests read alike. Two cases are not regressions, and in both the earlier candidate answers the twin as the new candidate answers the document. Acting where CommonMark is inert: the earlier candidate acts on the twin and the twin is a register R13 or R15 shape (F28). Not acting where CommonMark acts: the earlier candidate leaves the twin inert, which is F24's reading of the blank as a space, register R14 (F29). Any other difference is a regression. Differences on other documents are judged against each earlier reviewed candidate.
4. The acknowledgement is part of the agent's own reply text; the tag module creates no Ward Room post.
5. A chain claim goes through `ToolRegistry.check_and_invoke` for `claim_work_item`, with the claimant's department, rank and agent type, at WRITE.
6. Every agent-work run passes a `ToolCallConfinement` and never passes `admitted_turn`. No run starts for an item that `execution_allowed` refuses.
7. A call outside `AGENT_WORK_READ_TOOL_IDS` reaches its tool only when an approval on record for the same agent, item, tool and parameters is consumed in that call. Each approval admits at most one call, across restarts. AD-1154's inbox does not park that admitted call again; its credential refusal still applies; no other guard is skipped. No confirmation token is recorded.
8. A gate fault, a store fault or a payload that cannot be recorded refuses the call; none admits it.
9. A request whose claimant may not run it ends open and unassigned with its booking cancelled, never failed or cancelled, also when its run filed a call (the release comes before parking).
10. Each terminal, activation and decline notice is claimed before it is sent. Delivery makes one post per item, and every watcher of a deduplicated request is a recipient of its reports and of its declines. A decline that could not be posted is not acknowledged as told; a failed post is not retried (register R8).
11. No new EventLog category or event pair, request kind, config field, table, stop-seam constant or stop-check site.
12. Every background run is held in a set and cancelled at stop. Shutdown stops the runner before the work store.
13. `probos.agent_work_runner` imports the cognitive layer only inside functions, so the approval route's import chain gains no cognitive module.
14. (A1, A2) Both fulfilment predicates, Python's `can_fulfil_request` and the HXI's `canFulfil`, accept exactly the validated `agent_work_call` scoped to its own item. They agree on every row of `ui/e2e/fixtures/ad1347-action-payload-rows.json`, which ends on 11 of `validate_action_payload`'s 13 exits (X22 for Python, `capabilityApprovals.ad1347a2.test.ts` for the HXI; A2d, A2f, F26: a non-string params key is unreachable from JSON; a non-finite number such as `1e400` reaches `_canonical_json`'s refusal from JSON text but has no row, because Python owns canonical admission and the HXI's size check does not refuse it, register R12; the tests check answers, not which refusal gave them). The HXI confirms the approval's `fulfilled` response, and an approved, unfulfilled one stays on the actionable queue as retryable. A fulfilment-store fault returns that retryable approval with HTTP 200 (X23). The card says an agent-work approval resumes its item and offers no standing approval, and the route issues none (X24).
15. (A1) Only a run that completed with an answer is done; any other stop is failed with its reason named; a run the executor parked stays parked with its booking; a start that arrives during a run is made after it, once.

## 15. Acceptance criteria

1. **Live (closes the AD).** A crew agent in a Ward Room thread that needs an EventLog read files a request; a Lieutenant-or-above member of Engineering, Science or Security claims it and runs `event_log_query`; the result is posted in the originating thread, and the Captain sends no DM. Evidence comes from the live vessel (§16).
2. **One test crosses the whole seam:** X1.
3. **Guards:** S1's tests cover the claim side, plus X8 through the chain.
4. **The approval path:** X2.
5. **The stop:** C7 (create), X3 (claim and run); the census rows are updated (§7.16).
6. **Provenance through the chain:** C3, C4.
7. **Off is unchanged:** C5, C11, W3. AD-845 and AD-1165 are untouched (§9).
8. **Review round 1 (A1):** C1 (11 cases), C5, C14 to C16, X3, X7, X12 to X21 and `ui/src/store/__tests__/capabilityApprovals.ad1347.test.ts`; each new or changed assertion fails on the candidate `c5ad2b4b` except X12's negative control and X21's pin of AD-1154's set; the HXI file runs under vitest (not in the broad gate). **Review round 2 (A2):** C1's fenced case, C15 (5 cases), C17 (30), X22 to X24, `capabilityApprovals.ad1347a2.test.ts` (2) and `CapabilityRequestCard.ad1347.test.tsx` (1). Each fails on the candidate `f035964c` except X22 (the Python oracle of the shared rows, correct today) and C17's 11 control rows (`quote_line`, `quote_line_indented`, `text_between_two_spans_is_actionable`, `unmatched_backtick_is_text`, `closer_of_the_other_name_breaks_the_block`, `closer_without_opener_is_removed`, `crlf`, `lone_cr_ends_a_line` and the three `out_of_scope_` rows), which keep a refuse-everything scanner from passing. Run the two new vitest files with `ApprovalWave.test.tsx` and the rest of `ui/src/components/capability` and `ui/src/store` (not in the broad gate).
   **Review round 3 (A2b):** C15's `list_markers` case, C17's 15 new rows, and `indented_code_after_a_blank_line` (renamed from `out_of_scope_indented_code_is_read_as_written`, now inert). Each of the 16 new or changed C17 rows fails on the A2-applied candidate except three controls: `top_level_closer_indented_three_closes`, `indented_line_continuing_a_paragraph_is_text` and `out_of_scope_indented_fence_line_opens_a_list_fence`. C15's `list_markers` is a bound and passes. Rerun the CommonMark differential (markdown-it-py, the flat documents, plus list-marker, heading and `***` lines). No document may be acted on where CommonMark is inert except by lazy quote continuation, and each document CommonMark acts on that the scanner ignores must be one of §9's named over-inert shapes.
   **Review round 3 (A2c, the dedent regressions A2b introduced):** C17's 13 new rows and `indented_fence_line_ends_at_an_unindented_line` (A2b's control `out_of_scope_indented_fence_line_opens_a_list_fence`, renamed; it now expects the claim). On candidate 3's source (`f035964c`), 7 of the 14 fail. The other 7 pass: `marker_line_fence_ends_at_an_unindented_fence_line`, `marker_line_fence_ends_at_an_outdented_line` and `fence_in_an_item_ends_at_a_quote` (candidate 3 already reads them right; these were the regressions), plus `marker_line_inside_a_fence_is_content`, `text_after_a_list_fence_in_its_item_is_actionable`, `out_of_scope_lazy_line_then_an_item_fence_is_read_as_written` and the renamed row. Rerun both probes. The scanner differential must show no document that candidate 3 reads right and A2c acts on, and every other non-lazy one must be a register R15 shape. The real-post probe must show 0 non-lazy.
   **Review round 4 (A2f, F27 and F26's remainder):** C17's three relabelled rows (`out_of_scope_nbsp_before_a_quote_mark_is_a_quote`, `out_of_scope_em_space_before_a_quote_mark_is_a_quote`, `nbsp_line_after_a_quote_is_quoted`) fail on candidate 5's source (`478180b8`) and pass on A2f's; the other 138 Python cases pass on both. The C17 CommonMark audit finds 74 rows and six disagreements, all `out_of_scope_`. The four-seed differential finds no document that A2f acts on where CommonMark is inert and candidate 4 (`9319b37d`) was inert, and none where candidate 5 was inert apart from documents the A2g rule (§14 property 3) assigns to register R13. Its generator emits no nested blocks; round 5's nested-block family is A2g's. Every MISSING regression against candidate 4 is R14's wide-padded shape, and every one against candidate 5 is F24's shape. The real-post probe shows 0 non-lazy.
   **Review round 5 (A2g, text only):** no test, row or source changes. The orchestrator's nested-block family (`probe-s23-r5-family.py`, 960 documents) finds no document that candidate 6 acts on where CommonMark and candidate 4 are inert. Against candidate 5 it finds 288 such documents, each with an ASCII twin that candidate 5 acts on itself (register R13, no new class). The 66 four-seed MISSING differences against candidate 5 each hold a non-ASCII blank and `>` (F24's shape, register R14, F29 among them).
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance (acceptance 1): what the Captain does and what is read

**Captain's actions** (all operator-owned):
1. Set `agent_work.enabled: true` in his own `config/system.yaml`.
2. Confirm `agentic_dispatch.orchestrator_enabled` is on, so `event_log_query` is registered (`startup/communication.py:46-81`).
3. Restart the vessel.
4. Check the boot log has `AD-1347: agent-work runner wired`. If it says `runner is not built (missing: ...)`, enable what it names.
5. Let a Ward Room conversation produce a request, or prompt one by asking a medical officer about a log window in a thread.

**Read-only queries** against `%LOCALAPPDATA%\ProbOS\data`. Open each database with `sqlite3.connect("file:<path>?mode=ro", uri=True)` under `python -I`.

1. The work item, from `workforce.db`:

   ```sql
   SELECT id, title, status, created_by, assigned_to,
          json_extract(metadata,'$.agent_work.kind'),
          json_extract(metadata,'$.agent_work.origin.thread_id'),
          json_extract(metadata,'$.agent_work.tool_id'),
          json_extract(metadata,'$.agent_work_result.executor')
   FROM work_items
   WHERE json_type(metadata,'$.agent_work') = 'object'
   ORDER BY created_at DESC LIMIT 5;
   ```

2. The claim booking, from `workforce.db`:

   ```sql
   SELECT id, resource_id, status, start_time, actual_start, actual_end
   FROM bookings WHERE work_item_id = :id;
   ```

3. The tool audit records, from `events.db`:

   ```sql
   SELECT id, timestamp, agent_id, json_extract(data,'$.outcome')
   FROM events WHERE category = 'audit' AND event = 'event_log_query'
     AND agent_id = :claimant AND timestamp BETWEEN :claimed AND :done;

   SELECT id, timestamp, agent_id, json_extract(data,'$.is_error')
   FROM events WHERE category = 'tool' AND event = 'tool_invoked'
     AND json_extract(data,'$.work_item_id') = :id;
   ```

4. The thread post, from `ward_room.db`:

   ```sql
   SELECT id, author_id, author_callsign, created_at, substr(body, 1, 400)
   FROM posts WHERE thread_id = :origin_thread AND author_id = 'system'
   ORDER BY created_at;
   ```

5. No Captain DM in the window, from `ward_room.db`:

   ```sql
   SELECT count(*) FROM posts p
     JOIN threads t ON p.thread_id = t.id
     JOIN channels c ON t.channel_id = c.id
   WHERE c.channel_type = 'dm' AND p.author_id = 'captain'
     AND p.created_at BETWEEN :created AND :done;
   ```

   Also count `threads` with `author_id = 'captain'` in DM channels in the same window.

6. The notices, from `workforce.db`:

   ```sql
   SELECT work_item_id, recipient, kind, claimed_at
   FROM agent_work_notices WHERE work_item_id = :id;
   ```

## 17. Validation of record (2026-10-23, win32)

Written by the orchestrator after the build, from the tools' own output. It records what was run on the tree that ships; it changes no decision.

**Review history.** Every round ran on `gpt-6.1-sol`, passed explicitly; every Builder ran on `claude-sonnet-5.5`. Round 1 (42.1 min) NOT READY, fourteen findings (Amendment A1). Round 2 (33.7 min) NOT READY, six findings (A2, A2b, A2c). Round 3 (28.5 min) NOT READY, five findings (A2d, A2e). Round 4 (21.6 min) NOT READY, F27 and F26's remainder (A2f). Round 5 (16.2 min) NOT READY, F28 and F29: at the third round-three brake the Architect decided to rescope and land candidate 6 as reviewed, recording them under R13 and R14 (A2g, text only); there is no round 6. Builders: M1 5.8 min and a 1.2 min correction, M2 14.6, A1 12.1, A2 to A2c 13.8, A2d and A2e 14.3, A2f 2.8 (64.6 min in all); reviews 142.1 min in all.

**Round-three brake decisions** (the Architect, `claude-architect` through the bridge, each recorded on #1627): continue with one round 4 (comment 6372686155); continue with one round 5, F24 moved to the follow-up (comment 6374756401); rescope and land candidate 6 (comment 6375398334). The second admitted that A2d's recording of a regression as an R13 trade was not the Architect's to accept; the third replaced the round-4 and round-5 two-baseline criterion with the ASCII twin rule (section 14, property 3).

**Orchestrator decisions.** The eight mechanical repairs in the header (line 27) and the two Line cells of N16 and N75 (A2f's header paragraph); the routing of R10 to an F-113 addendum on #1523 (comment 6371015599); the Option A decision at the A2d gate (register R14's wide-padded shape) was the Architect's.

**Tests-first.** The final tests on the round-2 candidate's source (`f035964c`) failed 54 of 141 cases; on the round-3 candidate's (`9319b37d`) 11 of 141 with A2d and A2e's tests and 8 with A2f's; on round 4's (`478180b8`) 3 of 141, exactly A2f's three relabelled C17 rows. The Builder of each repair reported the same first failures before editing the source.

**Mutation campaign.** The 141 rows of section 10 (130 Python, 11 TypeScript) ran on one tree, `7f3ecd14` (scratch commit `28626e2b`, this contract applied by tool to `ba20e949`), each row restored before the next. The 130 Python rows ran in two groups: the 70 rows on `agent_work_tags.py` (19:43 to 19:58Z for A2e's tree, rerun 21:00 to 21:16Z on A2f's) and the other 60 (21:18 to 21:33Z). The unmutated baseline of the five test files passed (491 tests) in each. Result: 130 of 130 killed, none survived, none inert, none invalid, the pinned files unchanged after each group; N16 is killed by `quote_in_a_list_item` and N75 by `out_of_scope_nbsp_before_a_quote_mark_is_a_quote`. The 11 TypeScript rows (baseline 6 passed) were killed on `capabilityApprovals.ts` and `CapabilityRequestCard.tsx`, whose sha256 is unchanged in this tree. Every product and test file the code commits ship is blob-identical to that tree's, and the code commits' tree equals the reviewed candidate's (`2c2c29e7`). sha256 of the tree's working copies:

```
455f0fc747fdddef0b4b916bd1e2924404307d895bd42a52bf13bc219ab4bc73  src/probos/agent_work.py
2cca3fc0ce4eb168b48751b5d481aafac90df8a257529a87e8b712e73c654351  src/probos/agent_work_runner.py
21d62806a517493a5eeddb6d49d357c885efe0a247166ec0a5c179fdfd38167e  src/probos/agent_work_tags.py
1b6a38f4be8ce3ba0daf4a9484df4e9fb72d1a085f463bfa6e802dfeb27579cc  src/probos/capability_request.py
d37bd09d0676e524ab0d01c8e63fc59d6e34917f5ee7e50f249166c4371f16da  src/probos/cognitive/agentic_dispatch.py
b5e326e398110598d099e1a17250df86803b1915fd45ee1a1baf315086bdb881  src/probos/cognitive/capability_gap_driver.py
f604cdbffa3eb36ab1064d102e9c8b04f65f384d98ec1bf4d1469b64f89b2702  src/probos/cognitive/sub_tasks/compose.py
2ecc49d4dff2b20751aebaf2348ebebf8fa85ea10ab382c8a4ad4abfd15542a8  src/probos/proactive.py
a7962d053db1ed2ac751f4e963aac58c2d56878eb6bdba08e3465ff9cb6893e2  src/probos/routers/capability_requests.py
0e4c6b78f28cf34257fe6c6b93588d1854182011ddaa5e768044fa4f4954c057  src/probos/startup/finalize.py
4b75371f1d728a8eea6a5ff21f7b432b1d7e47028e4d1d04a2f503eab44693c4  src/probos/startup/shutdown.py
5f1c8be0ca3bde8c220e6b9b54c0448884c68b63c11ed8fb83cb1b1f11d18654  src/probos/ward_room_pipeline.py
96103c577ae0eeca4b4f1f701f710229855706681c9187250003fd4b73a912e6  tests/test_ad1156_plan_execute_mode.py
1aea9b142741f097e1c42955865c601392b07edf4f5ebf6a729ab20deceff350  tests/test_ad1347_s2_chain_tags.py
bc22da04091ec858a333874166db1067a85aabe56467e2c388c1798f387c1e97  tests/test_ad1347_s3_execution.py
4ab0f4ebd0f0091bd151fe514b48bc7f0cb5c24fdbb24edf7cd0918d23bdae63  tests/test_ad1347_s3_wiring.py
ffc1f57c0a51037e2a1ffc1d5a80a8f0bf48b92ce6ad3a67b7761ba1995ed7cc  tests/test_issue1419_failed_start_rollback.py
a819beb7dca45a1035deb8527f42f6d6a7f79501f646f4a0e82b268b473003e3  ui/src/components/capability/CapabilityRequestCard.tsx
7dcd4847da19cd12872f2ac0d5cefc2f54bf92e5834f6bff230af54f86e0274b  ui/src/store/capabilityApprovals.ts
```

**Consolidated focused checks** (210 test files that name a changed surface, scrubbed environment at `-n 8`, then four tree-scanning files unscrubbed at `-n 0`): round 3's candidate 10,376 passed, 20 skipped and 219 passed; round 4's candidate 10,392 passed, 20 skipped (11 min 14 s) and 219 passed, 2 skipped; the shipped candidate (`c7944573`) 10,392 passed, 20 skipped, 0 failed (11 min 40 s) and 219 passed, 2 skipped. The architecture fitness test (63) and the principles checker (`srp-size=92, layer-import=0, db-connect=30, unowned-task=14`) pass.

**The scanner's measurements** (the orchestrator's probes, outside the repository). The C17 CommonMark audit over the 74 rows finds six disagreements, all named `out_of_scope_`. The four-seed differential (seeds 1347, 2024, 7 and 31337, 12,000 documents each) against `9319b37d`: non-lazy and lazy EXTRA regressions 0 and 0, MISSING 20, 20, 21 and 21 (R14's wide-padded shape); against `478180b8`: EXTRA 0 and 0, MISSING 15, 20, 16 and 15 documents, each holding a non-ASCII blank and `>` (F24's shape). The F22, F23 and F24 enumerations (1,620, 900 and 25 documents): acting on code 0, 0 and 0; dropping a plain tag 172, 42 and 25. The nested-block family (960 documents, A2g): against `9319b37d` EXTRA 0 and MISSING 0; against `478180b8` 288 EXTRA, each with an ASCII twin that `478180b8` acts on. The real Ward Room (16,386 bodies, 144,300 variants, read-only): EXTRA 12 variants (lazy-quote class 12, non-lazy 0) and MISSING 90 variants in 45 bodies, the same for `9319b37d` and the shipped scanner; no body holds a non-ASCII blank before `>`. The shared payload rows reach 11 of `validate_action_payload`'s 13 exits.

**Register.** F-354 to F-380 are on #1523 (comment 6375454752). The receipt of the broad gate that counts, the pull request and CI are recorded on #1627.
