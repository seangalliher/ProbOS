# BF-934 (#1673): A proactive think whose triage decided to file a proposal or write a notebook entry is carried through to the output, no gate discards an action the output carries, and every intended action is carried out or recorded as dropped

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Revised by:** orchestrator, 2026-11-12: the anchor of S1's `DECISIONS.md` pair (P3-2) and the sentences above that BF-935's merge made untrue (Status, Base blobs, Dependencies, Which text describes the head, Tracker anchors), after BF-935's merge.
**Status:** ready to build, in three slices (S1 to S3, section 2), on `origin/main` `fe4889715644c57bdf3f3a7c9c08a1ede158fef3` (reading tree `D:\ProbOS-worktrees\bf934-base`; the three code blobs are byte-identical to the BF-935 oracle's). BF-935's Scout merge (#1674, `430423e14ac140f4cb8e37deffa233c9e49f730f`) precedes the build and is its base; it changed none of the code files below (see Dependencies). File it as `prompts/bf-934-dropped-crew-proposals.md`. **Oracle:** no pytest and no test run (a read-only consult: the reading tree was never written, `git status --short` is empty before and after, and the only file written is this one, apart from one trivial temporary file that was created and deleted by mistake early in the consult). An in-memory script applied the 38 pairs of code and tests, the 6 tracker pairs and the 7 new files of section 7 to the LF blobs (each SEARCH once, at its turn; every result compiles), served the patched modules over the real tree through a meta-path finder, and drove the three new test files by hand with a hand-made runner (parametrize; xfail with `strict` and `raises=AssertionError`; fakes for `tmp_path`, `monkeypatch` and `caplog`). The think loop, the Ward Room and its router, the cognitive agent's lifecycle, the action extractors and the EventLog were real; Ship's Records was an in-memory stand-in with the real `check_notebook_similarity` answer shape; the model, the triage's ANALYZE and QUERY handlers and the thinker's `handle_intent` were doubles (`tests/bf934_world.py`). On each slice's M1 head the class cases fail at their own assert and the other cases hold; on each M2 head every case holds; the 47 mutants of section 9 fail the cases listed there; the real census functions of `tests/test_ad1195_eventlog_pair_freeze.py` and the real `check()` of `scripts/check_architecture_principles.py` pass over the patched sources in memory (section 11). Every count in sections 4, 6 and 9 is therefore "expected": the real pytest, `tmp_path` on disk with the git-backed `RecordsStore`, xdist and suite order, the existing suite, the checker's command and any live model are unchecked (L1).
**Base blobs (`fe488971`):** `src/probos/cognitive/cognitive_agent.py` `804cce2633bdfa116967c977713fab5acacacd85`, `src/probos/proactive.py` `5f10cf005d098648657fb93c7e5f5ca54fc2d9b3`, `src/probos/cognitive/sub_tasks/compose.py` `db2996ee6e9ec38e888d02063031dacad88ef109` (read, not edited), `tests/test_ad1195_eventlog_pair_freeze.py` `8db9fe8aef08f332917fd4c8df4ff28e4cf0de73`, `PROGRESS.md` `a10956172ac3cacc83b7ccf1dc5260aa08781705`, `DECISIONS.md` `a07c172b512ce69dc88f5819575b56de3a5c1689`. **At `430423e1` (BF-935's merge, the base of the build)** the four code blobs are the same and the two tracker blobs are `PROGRESS.md` `eaf7e884c3a158b6d9c89754c3e99ab597c05ff4` and `DECISIONS.md` `1d814df5020e7b9675f2ae123e14bf5e19075b7f`.
**Dependencies:** none in code; BF-935's merge changed Scout files (`src/probos/cognitive/scout.py`, `src/probos/experience/commands/commands_knowledge.py` and three test files), its own contract, `PROGRESS.md`, `DECISIONS.md` and the two ledger files; no block here edits a Scout file, and the tracker pairs and G3 take the rest as they stand (see the tracker anchors below). **Tier:** S1 M2 HIGH (the prompt of every proactive single call that carries a decision); S2 M2 HIGH (the gate order of every proactive think, and what an approved chain output may be replaced by); S3 M2 HIGH (durable rows written from the think path); every M1 and M3 STANDARD. **Estimated tests:** four new test files (a helper and three test modules) with 22 + 26 + 43 = 91 cases (6 + 5 + 18 = 29 pass and 16 + 21 + 25 = 62 xfail at the M1 heads). **BF number:** BF-934, held by #1673; nothing new is allocated (section 11). **For the orchestrator to allocate:** one new BF for a defect found on the way and not fixed here: BF-032's similarity gate can never match in production (L2).

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` prints the four code blobs above and, for the two tracker paths, the blobs named after them for `430423e1`; `git diff --stat fe488971 HEAD -- src/probos/cognitive src/probos/proactive.py tests/test_ad1195_eventlog_pair_freeze.py` lists `src/probos/cognitive/scout.py` and no other path; none of the seven new files exists (`git ls-tree HEAD -- <path>` prints nothing for each). If one check fails, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the blocks with the `edit` tool one at a time, whole block, in label order, slice by slice: S1 (its gates and commits) before S2, S2 before S3. Every SEARCH starts at the start of a line; each occurs once in its file at its turn (applied in memory, section 11); every block is ASCII (the one non-ASCII character a model is shown, the em dash of the proposal format, is written `\u2014` in `action_billets.py`). The N2 pairs edit the test files that the N1 blocks of the same slice create, and each slice's pairs edit the files the slice before it edited: a checker that reads every pair's file from git at the base must be given the new files first (the in-memory script applied the blocks in document order).
**Tracker anchors.** Every `PROGRESS.md` pair anchors on `# ProbOS Progress` and the blank line after it, which survive BF-935's merge. S1's `DECISIONS.md` pair anchors on the last bullet of BF-935's entry (once), so that the file stays in the order the changes landed; the Architect anchored it on the last bullet of BF-940 slice 4's entry (`- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-940 slice 4 commits.`, once) and the orchestrator moved it after BF-935's merge (`430423e14ac140f4cb8e37deffa233c9e49f730f`). S2's anchors on S1's last bullet and S3's on S2's; those survive.

## 1. Problem

The issue counts, from the live logs of 2026-07-15 to 10-25, 36 triage decisions to file a proposal: 5 posted and 31 lost, 24 of them to the routing in item 1. Those counts, the live evidence and the crew's two comments are the issue author's: they are quoted here, not measured. The issue's line numbers are from `5e3cc991` and are stale; every number below is from `fe488971`.

1. **The triage decides, and the decision is dropped on the way to the call that writes the output.** `_execute_chain_with_intent_routing` (`cognitive_agent.py:6310`) runs the triage (QUERY and ANALYZE, `:6446`) and reads its decision as `intended_actions` (`:6474-6475`); exactly `["silent"]` ends it (`:6496`). `_COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})` (`:6509`) names the four tags that run the rest of the chain (COMPOSE, EVALUATE, REFLECT); `proposal` and `notebook` are not among them. With none of the four, `has_comm_action` (`:6510`) is false, and the function logs `AD-643a: No comm actions in %s -- skipping chain, using single-call` (`:6615`) and returns `None`. `decide` then answers through `_decide_via_llm` (`:3906`), which is given the observation and nothing of the decision.
2. **The single call defaults to silence, and nothing tells it otherwise.** For `proactive_think`, `_build_user_message` (`:10604`) ends the message with a default (`:11494-11498`): with a duty, "If nothing noteworthy to report, respond with exactly: [NO_RESPONSE]"; without one, "If something genuinely warrants attention, compose a brief observation (2-4 sentences). Include your justification. Otherwise respond with exactly: [NO_RESPONSE]". The only place the proposal format is given with the decision is COMPOSE's AD-651a billet (`compose.py:291-307`, only when `"proposal" in intended`); no billet exists for a notebook entry; COMPOSE did not run. Run in memory on the base (section 11): a triage of `['proposal','notebook']` and a model that answers a prompt carrying no decision `[NO_RESPONSE]` (the issue's 22 of 24) leave no thread, no notebook entry and no log line above DEBUG.
3. **The gates after the call can discard a block too,** in this order: `if not response_text or "[NO_RESPONSE]" in response_text` (`proactive.py:1412`) returns before any block is read; BF-032's similarity gate (`:1487`) and AD-493's novelty gate (`:1498-1511`) return before the extraction (`:1525`), so a proposal or a notebook entry attached to an observation that repeats an earlier one is lost with it; then BF-172 (`:1513`), the extraction (`_extract_and_execute_actions`, defined `:3107`) and BF-215 (`:1531`). The Ward Room pipeline extracts before the same two gates (`ward_room_pipeline.py:293`; section 11): the loop's order is the odd one.
4. **A proposal that is read can still fail without a trace.** The block (`:3558-3635`, "all ranks") needs newlines between its tags; a malformed block logs `AD-412: Malformed [PROPOSAL] block` at DEBUG (`:3626`); a block without a Title or a Rationale is skipped without a line; the router's refusal (`handle_propose_improvement` answers `{"success": False, ...}`) is ignored and the proposal is still counted as filed; an exception is logged at DEBUG. `_post_to_ward_room` (`:3042`) returns `None`, and a missing channel logs at DEBUG (`:3070`).
5. **A rewrite can replace an approved output with silence.** After COMPOSE, AD-643b (`_detect_undeclared_actions`, `:5966`) finds a block the triage had not declared and `_re_reflect_with_feedback` (`:6620`) runs REFLECT again; whatever it returns replaces the approved output, `[NO_RESPONSE]` and a text without the block included (the issue's Forge case).
6. **Nothing records the loss.** `intended_actions` is read in five files under `src/probos` (`cognitive_agent.py`, `skill_catalog.py`, `sub_tasks/analyze.py`, `compose.py`, `reflect.py`) and in none outside the cognitive package; `actions_taken` in `_think_for_agent` is assigned at `:1525` and never read; `IntentResult.metadata` does not carry the decision. AD-643b logs the converse (an action taken that the triage did not declare) at INFO; `_run_cycle` swallows an exception of a think at DEBUG (`:1154-1160`).
7. **The notebook.** The issue says the gate "very likely" drops `notebook` too. Confirmed by reading and by an in-memory seam run: `notebook` is carried out by the same extractor (`_NOTEBOOK_PATTERN` `:220`, `split_notebook_blocks` `:229`; AD-434 writes it, AD-550 deduplicates, AD-552 gates repetition), no gate reads `intended_actions`, and item 1 sends it to the same single call. Base run: no notebook entry is written.

| The issue's cause (counts are the issue's) | Item | Slice |
|---|---|---|
| 1. no communication action skips the chain (24 of the 31); the notebook | 1, 2, 7 | S1: the single call receives the decision |
| 2. a REFLECT rewrite suppressed one (Sage, 08-03) | the chain's own REFLECT | not changed (L5): a model's decision inside the chain; S3 makes it visible (a `declared` row, then a `dropped` row with `no_response`) |
| 3. the AD-643b re-reflect replaced an approved output (Forge, 10-22) | 5 | S2: a rewrite may refine an approved output, never remove an action it carries |
| 4. six undetermined (failures logged at DEBUG) | 4 | S2: WARNING with the agent and the reason; S3: a record |
| the secondary gates (acceptance 4) | 3 | S2 |
| the inverse of AD-643b (acceptance 3) | 6 | S3 |

## 2. Solution

Three slices, each with its own milestones, gates and commits, so that the orchestrator can batch them under one broad gate.

| Slice | What changes | Blocks | New files |
|---|---|---|---|
| S1 | The single call receives the triage's decision: `CognitiveAgent` keeps it on the observation for the turn and `_build_user_message` replaces the default of silence with a billet when `proposal` or `notebook` was decided (`decision_billet`). | N1-1, N1-2, P2-1 to P2-5, N2-1, N2-2, P3-1, P3-2 | `tests/bf934_world.py`, `tests/test_bf934_s1_decision_routing.py`, `src/probos/cognitive/action_billets.py` |
| S2 | No gate discards an action the output carries (a valid block beside `[NO_RESPONSE]`; the extraction before BF-032 and AD-493; a re-reflect may not remove an action), and a proposal that is not filed says why (WARNING, an entry, the router's refusal no longer counted as filed). | N1-1, P2-1 to P2-12, N2-1, N2-2, P3-1, P3-2 | `tests/test_bf934_s2_secondary_gates.py`, `src/probos/cognitive/proposal_block.py` |
| S3 | Every intended action is carried out or recorded as dropped, with a reason: a `declared` row where the decision is made, a `dropped` row (and a log line) where it is lost, per agent and action, in the EventLog; `_post_to_ward_room` says whether a thread was created. | N1-1, P2-1 to P2-17, N2-1 to N2-3, P3-1, P3-2 | `tests/test_bf934_s3_intended_actions_ledger.py`, `src/probos/cognitive/action_accounting.py` |

**Order, and why.** S1, then S2, then S3. S1 alone fixes the primary cause (24 of the issue's 31) and is the smallest. S2's tests reuse S1's `tests/bf934_world.py`. S3's calls to `settle_intended_actions` sit at the exits of `_think_for_agent` in the order S2 gives them, and S3's pairs anchor on lines S2 creates (the import and the moved unit in `proactive.py`) and on the import line S1 adds to `cognitive_agent.py`; so S3 cannot precede S1 or S2, and a revert of S1 or S2 needs the later slices reverted first. Each slice passes its own gates on the state the slices before it leave; their combined state is the one the oracle batches.

**Size.** The document is about 190 KB, most of it code: the blocks of section 7 are about 28 KB (S1), 33 KB (S2) and 39 KB (S3), with 6, 13 and 19 pairs in the M2 milestones (11, 17 and 23 blocks in all, new files and tracker pairs included), under the cap of about 25 pairs per milestone.

**The one-line version of each decision (section 3 ranks the options).** S1: give the decision to the single call (a billet), do not make `proposal` and `notebook` run the chain. S2: read a valid block beside `[NO_RESPONSE]`, extract before the similarity and novelty gates (as the Ward Room pipeline already does), let a re-reflect refine and never remove. S3: record the decision and each loss as EventLog rows (`category="intended_actions"`), no new `EventType`, no new store.

## 3. Decisions

Each is the Architect's, taken in Delegated AD Execution Mode: the options are ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; the first is taken. None weakens a security, governance, privacy or audit control, crosses the OSS and commercial boundary, or changes a stored format (S3 adds two kinds of EventLog row, see D2); each rolls back by reverting its slice. The Captain's decisions that remain are in section 15.

### D1. Route the decision (acceptance 1; the issue says it is the Architect's call)

| Rank | Option | LLM calls per decision | Prompt | Every other intended-action set | When the chain or the call fails | Verdict |
|---|---|---|---|---|---|---|
| 1 | The single call receives the decision and a billet (`decision_billet`, S1) | 2 (triage, single call): the route these decisions already take | +550 characters (notebook), +730 (proposal) or +899 (both), measured, minus the two closing lines (about 160) it replaces | none: `["silent"]` never reaches the call; `["oracle_query"]`, `["leadership_review"]`, `["speak_freely"]` alone, and any set with no `proposal` or `notebook`, leave the prompt byte for byte as before (tested); a set with a communication action still runs the chain, whose COMPOSE shows its own billet | a chain that fails and falls back to the single call hands the decision in, because the key is set as soon as the triage ends (tested); a call that fails or answers silence leaves the decision dropped with `think_failed` or `no_response` (S3) | **Taken** |
| 2 | `proposal` and `notebook` become chain triggers (add them to `_COMM_ACTIONS`) | 5: the triage's ANALYZE, then ANALYZE, COMPOSE, EVALUATE and REFLECT, because Phase 2a re-runs the whole chain (`:6552-6554`) | COMPOSE's billet, read from the second ANALYZE, a second sample of the triage | changes every set with either tag; a proposal-only decision would also compose an observation post nobody decided; COMPOSE has no notebook billet; `test_ad1347_s4_chain_lookup.py::test_a_lookup_with_no_communication_action_reads_nothing` pins `['notebook','ward_room_lookup']` to no chain and `test_ad643a_intent_routing.py::test_comm_actions_defined` scans `_COMM_ACTIONS` | a failing chain still falls back to a single call that does not know the decision | Rejected |
| 3 | Option 2 with the triage's ANALYZE result reused, so COMPOSE reads the decision that was made | 4 | as 2 | as 2 | as 2 | Rejected: `SubTaskExecutor.execute` keeps no memo of prior results, so it needs a new cache in the hot path of every chain, for a decision whose action needs no chat post |

The billet says the decision stands for the turn and that the only way out is the exact `[NO_RESPONSE]`, which S3 records as a withdrawal. The model is therefore asked to commit and not forced to: a decision the evidence no longer supports stays withdrawable and visible. Whether the wording is strong enough for the real models is the live re-measure's question (section 15).

### D2. Make loss visible (acceptance 3, and the crew's reconciliation spec)

**The log level and wording.** A proposal that is malformed, lacks a Title or a Rationale, has no router, is refused by the router (`{"success": False}`, now read instead of ignored) or raises logs at WARNING, `BF-934: proposal from <callsign> (<agent_type>) not posted: <reason>` with `reason` one of `missing_title`, `missing_rationale`, `no_router`, `router_refused: <error>`, `post_failed: <ExceptionName>`, and `BF-934: Malformed [PROPOSAL] block from <callsign> ...` for a block without the strict shape; an extra block logs `BF-934: N more [PROPOSAL] block(s) from <callsign> are ignored`. An observation with no channel logs at WARNING in `_post_to_ward_room`. The extractor also appends `{"type": "proposal_suppressed", "reason": <reason>}`, the convention it already has (`notebook_suppressed`, `artifact_suppressed`).

**Where the inverse of AD-643b lives** (enumerated, not assumed):

| Rank | Home | Why | Verdict |
|---|---|---|---|
| 1 | EventLog rows through `event_log.log(category="intended_actions", event="declared" or "dropped", ...)` | durable (`events.db`; 7 days and 100000 rows by `EventLogConfig`, `config_models/core.py:146`), queryable per agent, event and correlation id (`query_structured`); the precedent is the direct `category="pipeline"` row of `ward_room_pipeline.py:367` (BF-237); AD-1195's census freezes the two pairs (S3 P2-17) | **Taken** |
| 2 | A new `EventType` through the durable router (AD-1195) | changes the contract whose hard counts (395 members, 29 routed, 366 not, 37 durable) four tests assert (`test_ad1195_durable_event_seam.py:328-332`, `test_ad1195_event_persistence_contract.py:514,592`, `test_ad1195_durable_producers.py:162,172`, `test_ad1195_eventlog_pair_freeze.py:399,508`), for a record nobody subscribes to | Rejected |
| 3 | In-memory counters (the BF-238 `PostBudgetTelemetry` pattern, `ward_room_pipeline.py:57`) | lost at every restart; the reconciliation needs a window of days | Rejected |
| 4 | Log lines alone | not countable without the log files; the crew's spec needs a record (the lines stay, as the readable half) | Rejected |
| 5 | The cognitive journal (`journal.py:22`) | one row per model call (tokens, latency, `prompt_hash`, `response_hash`, `intent_id`); it holds no decision | Rejected |
| 6 | A new table or store | a persistence layer for a count | Rejected |

**The structured drop entry** is `{"type": "action_dropped", "action": <tag>, "reason": <reason>}` (plus `"by_design": True` for a notebook the writer declined as a repeat, AD-550 and AD-552). It is what `settle_intended_actions` returns, writes as a `dropped` row (`data` carries the entry, `intent`, `intent_id` and `callsign`; `correlation_id` is the intent id) and logs: WARNING for a lost decision, INFO for an observation the quality gates withheld (`ward_room_post`: a deliberate silence) and for a by-design notebook suppression. The reasons are `think_failed`, `no_output`, `no_response`, `raw_intent_json`, `empty_after_extraction`, `similar_to_recent_post`, `not_novel`, `not_posted`, the extractor's own (`missing_title`, `missing_rationale`, `malformed_block`, `no_router`, `router_refused: ...`, `post_failed: ...`, and AD-550's text for a notebook) and `no_block_executed` for a block tag whose block did not execute and left no reason.

**The two sources of truth the crew asked to have named before landing** (recorded here and in DECISIONS):

| Side | Source of truth | Not a source |
|---|---|---|
| decided | the `declared` rows of `events.db` (`category="intended_actions"`, `event="declared"`), written by `CognitiveAgent` where the decision is made, before any gate: `data.intended` lists the tags | a count taken in the proactive loop, which is the layer that drops the output |
| posted | Improvement Proposals (`ward_room.db`: threads titled `[Proposal] ...`) for `proposal`; Ship's Records (`notebooks/<callsign>/<slug>.md`) for `notebook`; the Ward Room for the other tags | the extractor's `actions_executed` |
| dropped | the `dropped` rows of `events.db`, one per intended action that nothing carried out, with `data.reason` | the log lines |

The identity, per agent and action over a window: `declared = posted + dropped`. The discrepancy `declared - posted - dropped` is expected to be zero; a positive value is an unexplained loss (the alarm: a think that raised after its decision leaves exactly this, L3); a negative value is a post by a think whose triage did not intend it (AD-643b's INFO line names it): reported, not a loss. Rows are written for `proactive_think` only (L6).

### D3. The secondary gates (acceptance 4)

| Gate | Rank | Option | Verdict |
|---|---|---|---|
| order of the extraction | 1 | The extraction runs before BF-032 and AD-493 (after BF-172), as the Ward Room pipeline's does (`ward_room_pipeline.py:288-318`: extraction, then BF-197, then AD-493): any block attached to a repeated observation is carried out, and the repeat itself is still not posted. A block-only output exits at BF-215 as before | **Taken** |
| | 2 | Exempt proposals from the two gates | Rejected: one tag, two branches; notebooks and every other block stay lost |
| | 3 | Leave the order | Rejected: it is the defect |
| `[NO_RESPONSE]` | 1 | The gate asks `carries_actionable_block(text)` (a proposal the extractor can file, or a notebook entry with a body): if so the output is read for blocks, and the observation stays withdrawn (nothing of it is posted) | **Taken** |
| | 2 | Strip the marker and post what is left | Rejected: posts prose the model withdrew |
| | 3 | Ask for every block type | Rejected here: replies, DMs and endorsements may follow a "nothing to add" answer by design and the issue names neither (L4) |
| the AD-643b re-reflect | 1 | May refine, never remove: if the rewrite lacks an action marker the approved output carried (silence included), the approved output is kept and a WARNING names the lost tags; the feedback still reaches the episode (`_undeclared_action_feedback` stays on the observation) | **Taken** |
| | 2 | Annotate only | Rejected: it changes AD-643b's documented contract (the re-reflect output replaces the chain result) for every rewrite, and `test_trigger_learning.py::test_runs_on_undeclared` and `::test_output_replaces_original` pin the replacement |
| | 3 | Leave | Rejected: the Forge case |

**Readers of every changed contract** (enumerated by `rg`, section 11): the gate order is read by nothing but the think itself (working memory, `_last_proactive` and the post all follow the gates); BF-032 is inert in production (L2), so the reorder changes in practice what AD-493's novelty gate does to blocks. `_extract_and_execute_actions` has two callers, the think (`proactive.py:1525`) and the Ward Room pipeline through `extract_and_execute_actions` (`ward_room_pipeline.py:293`), which discards the entry list: the new `proposal_suppressed` entry and the WARNINGs reach both, which is the intent. `_re_reflect_with_feedback` has one caller (`cognitive_agent.py:6606`). `_post_to_ward_room` has one caller in `src` (`proactive.py:1553`) and two in tests (`test_bf198_router_proactive_dedup.py:200`, `test_bf874_dm_callsign_and_fail_closed.py:558`), none reads its result. `_build_result_metadata` has one caller (`cognitive_agent.py:8023`); `proactive.py` reads no `.metadata` at the base; no whole-dict reader of an `IntentResult`'s metadata exists in `src` (the `json.dumps(...metadata)` hits are other types), so the added key is additive. The observation key `_intended_actions` has one reader, `_build_user_message`.

### D4. Tests (acceptance 2 and 6, and the crew's per-tag test)

- **One world for all three files** (`tests/bf934_world.py`, S1): the real `ProactiveCognitiveLoop`, `WardRoomService` and `WardRoomRouter`, `RecordsStore` (`auto_commit=False`) and an optional real `EventLog`, all on `tmp_path`; the cognitive agent is real and runs through `handle_intent`; only the model, the triage's ANALYZE and QUERY handlers, the runtime shell and a canned thinker are doubles. A test asserts on what the Ward Room and Ship's Records hold, never on a mock it set up.
- **The seam test** is S1's `test_a_decided_proposal_and_notebook_are_posted_and_written` (triage `['proposal','notebook']`, a model that obeys the decision it is shown, a thread titled `[Proposal] Cache the roster` in Improvement Proposals and a notebook entry on disk), with its control beside it (a model that writes the blocks on its own is carried out on both trees). The half-chain trap is avoided: one test crosses triage, routing, the call's prompt, the extraction, the router and Ship's Records.
- **The per-tag test** is S3's `test_an_action_the_output_does_not_carry_is_dropped_with_a_reason_and_said` (five block tags), `test_an_observation_the_gates_withhold_is_dropped_too_but_only_noted` (`ward_room_post`), their controls (every one of the six tags carried out leaves no drop) and the registry test, which pins `ACTION_TAGS` equal to the vocabulary both ANALYZE prompts offer (a seventh tag fails it) and requires a reason for each of the five tags carried out by something else (`silent`, `speak_freely`, `leadership_review`, `oracle_query`, `ward_room_lookup`).
- **The existing tests that pin current behaviour** (enumerated by `rg -l`, section 11). None pins a defect:

| Area | Files | What they pin | Result |
|---|---|---|---|
| AD-643a routing | `test_ad643a_intent_routing`, `test_ad1347_s4_chain_lookup`, `test_ad1270_boot_camp_repair_a1`, `test_ad1270_boot_camp_trust`, `test_ad644_phase1_duty_context`, `test_ad644_phase2_innate_faculties`, `test_ad666_sensorium`, `test_bf688_chain_priority_inheritance` | `_COMM_ACTIONS` (`test_comm_actions_defined`); a `['notebook','ward_room_lookup']` decision runs no chain; AD-1270's census of the methods that execute a chain (`_GATING_PHASES`) | unchanged: S1 touches neither `_COMM_ACTIONS` nor a chain executor; no method is added to or renamed in `CognitiveAgent` |
| AD-643b | `test_trigger_learning`, `test_combo_c_ad573c_note`, the two AD-1270 files | the six marker patterns and their order; a rewrite of an output without markers replaces it | unchanged: `_ACTION_MARKERS` holds the same six patterns in the same order; the guard acts only when a marker is lost |
| AD-412 | `test_proactive` (`TestProposalExtraction`, `TestHandleProposeImprovement`), `test_ad632d_compose_handler`, `test_bf213_proactive_action_vocabulary` | a valid block is posted through the router; no Title or no Rationale is not posted and the tags are stripped; a raising handler leaves the tags stripped and no `proposal` entry | unchanged: they filter entries by `type == "proposal"` and assert "not posted, tags stripped", which stays true; none asserts the entry list is empty |
| AD-651a | `test_ad651a_compose_billet`, `test_bf213_proactive_action_vocabulary`, `test_bf186_compose_standing_orders` | COMPOSE's billet; `"BF-213"` absent from `_build_proactive_compose_prompt` | untouched: COMPOSE is not edited; S1's test pins `PROPOSAL_FORMAT` equal to COMPOSE's block |
| BF-032, AD-493 | `test_proactive`, `test_proactive_quality`, `test_bf201_thread_post_cap`, `test_bf237_pipeline_post_budget`, `test_ad493_novelty_gate` | each gate's verdict | none pins the gate order or the DEBUG wording |
| the think cycle | the 13 files naming `_think_for_agent` | `MagicMock` results whose `.metadata` is a `MagicMock` | `settle_intended_actions` reads metadata only when it is a `dict` |
| AD-1195, AD-1343 | `test_ad1195_eventlog_pair_freeze` (and three siblings), `tests/fixtures/ad1343_seam_registry.py` | the frozen EventLog pairs; `_think_for_agent` as the function that calls `handle_intent` | updated by S3 P2-17 (two resolved pairs); `_think_for_agent` is neither renamed nor wrapped |

### D5. Trackers and the ledger

`PROGRESS.md` and `DECISIONS.md` get one entry per slice (M3, anchors above), then the ledger generator (G3). The roadmap's Bug Tracker is not edited, as in BF-961's contract; the Architect handles the closure comment (section 15).

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. Each slice has its own M1 to M3 and its own G1 to G3; a slice is built, gated and committed before the next starts. **M0 (once per slice, before its M1):** on the head, record the collected count (`PY -m pytest --collect-only -q <files>`) of every existing file named in that slice's G2.

| Slice | M | Blocks | Gate |
|---|---|---|---|
| S1 | M1 | N1-1, N1-2 | G1 |
| S1 | M2 | P2-1 to P2-5, then N2-1, N2-2 (removing the markers) | G2 |
| S1 | M3 | P3-1, P3-2, ledger | G3 |
| S2 | M1 | N1-1 | G1 |
| S2 | M2 | P2-1 to P2-12, then N2-1, N2-2 | G2 |
| S2 | M3 | P3-1, P3-2, ledger | G3 |
| S3 | M1 | N1-1 | G1 |
| S3 | M2 | P2-1 to P2-17, then N2-1 to N2-3 | G2 |
| S3 | M3 | P3-1, P3-2, ledger | G3 |

- **G1 (every slice).** `PY -m pytest <the slice's new test file> -q -n 0 -p no:randomly`. **Expected:** S1 6 passed and 16 xfailed; S2 5 passed and 21 xfailed; S3 18 passed and 25 xfailed. The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: every failure must be an `AssertionError` at an assert of the case (the `_built` helpers fail at their own assert while a module is not built; an ImportError would not satisfy the marker), never a setup error. The helper `tests/bf934_world.py` is part of S1's M1 and is imported by all three files.
- **G2 (S1).** (1) the command below, files in alphabetical order with the new file at its place (the files that name `_execute_chain_with_intent_routing`, `_COMM_ACTIONS` or the AD-643a log; the 15 that name both `_build_user_message` and `proactive_think`; the 13 that name `_think_for_agent`; the AD-651a and COMPOSE files; section 11):

```
PY -m pytest tests/test_ad1228_standing_interest_e2e.py tests/test_ad1228_standing_interests.py tests/test_ad1258_self_knowledge.py tests/test_ad1260_wellness_domain.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1343_stop_crossing.py tests/test_ad1346_admission_shadow_routing.py tests/test_ad1347_s4_chain_lookup.py tests/test_ad576_llm_unavailability.py tests/test_ad588_telemetry_introspection.py tests/test_ad617b_per_agent_token_budget.py tests/test_ad630_leadership_feedback.py tests/test_ad632d_compose_handler.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad643a_intent_routing.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py tests/test_ad651_step_instruction_router.py tests/test_ad651a_compose_billet.py tests/test_ad666_sensorium.py tests/test_bf034_cold_start.py tests/test_bf037_ontology_rendering.py tests/test_bf186_compose_standing_orders.py tests/test_bf213_proactive_action_vocabulary.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf874_dm_e2e.py tests/test_bf907_trust_identity.py tests/test_bf922_fallback_gate.py tests/test_bf925_event_log_window.py tests/test_bf934_s1_decision_routing.py tests/test_bf950_oracle_result_age.py tests/test_circuit_breaker.py tests/test_cognitive_agent.py tests/test_combo_a_ad576b_retry.py tests/test_counselor_therapeutic.py tests/test_duty_schedule.py tests/test_onboarding.py tests/test_proactive.py tests/test_provenance_boundary.py tests/test_self_monitoring.py tests/test_temporal_context.py tests/test_trigger_learning.py -q -n 0 -p no:randomly
```

  (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the S1 file 22 passed; every other file 0 failed and collected counts equal M0; the check clean.
- **G2 (S2).** (1) the S1 and S2 files and every file that names `_think_for_agent`, `_extract_and_execute_actions`, `_detect_undeclared_actions`, `_re_reflect_with_feedback`, the `[PROPOSAL]` block, BF-032 or AD-493's gate:

```
PY -m pytest tests/test_ad1077_group_chat_coaching.py tests/test_ad1157_notebook_classification.py tests/test_ad1228_standing_interest_e2e.py tests/test_ad1228_standing_interests.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1343_stop_crossing.py tests/test_ad1346_admission_shadow_routing.py tests/test_ad1347_s2_chain_tags.py tests/test_ad1347_s4_chain_lookup.py tests/test_ad437_action_space.py tests/test_ad550_notebook_dedup.py tests/test_ad617b_per_agent_token_budget.py tests/test_ad632d_compose_handler.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad643a_intent_routing.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py tests/test_ad651a_compose_billet.py tests/test_ad654a_async_dispatch.py tests/test_ad654d_internal_emitters.py tests/test_ad666_sensorium.py tests/test_ad868_self_originated_crew.py tests/test_ad924_group_chat_trigger.py tests/test_ad927_outputs_folder.py tests/test_ad928_show_your_work.py tests/test_bf201_thread_post_cap.py tests/test_bf213_proactive_action_vocabulary.py tests/test_bf237_pipeline_post_budget.py tests/test_bf238_post_budget_telemetry.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf874_dm_e2e.py tests/test_bf925_event_log_window.py tests/test_bf934_s1_decision_routing.py tests/test_bf934_s2_secondary_gates.py tests/test_circuit_breaker.py tests/test_combo_a_ad576b_retry.py tests/test_combo_c_ad573c_note.py tests/test_duty_schedule.py tests/test_onboarding.py tests/test_proactive_quality.py tests/test_proactive.py tests/test_records_store.py tests/test_recreation_channels.py tests/test_self_monitoring.py tests/test_trigger_learning.py -q -n 0 -p no:randomly
```

  (2) the architecture check. **Expected:** the S1 file 22 and the S2 file 26 passed; every other file 0 failed and collected counts equal M0; the check clean.
- **G2 (S3).** (1) the three new files, the AD-1195 and AD-1343 files, the files that name `_build_result_metadata` or `_post_to_ward_room`, and the think and routing files:

```
PY -m pytest tests/test_ad1195_durable_event_seam.py tests/test_ad1195_durable_producers.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_ad1228_standing_interest_e2e.py tests/test_ad1228_standing_interests.py tests/test_ad1248_slice_a_crossing.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1295_tool_success_ledger.py tests/test_ad1343_stop_crossing.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1346_admission_shadow_routing.py tests/test_ad1347_s4_chain_lookup.py tests/test_ad1357_context_manifest.py tests/test_ad1358_s1_head_to_head.py tests/test_ad617b_per_agent_token_budget.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad641a_observability_bridge.py tests/test_ad643a_intent_routing.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py tests/test_ad666_sensorium.py tests/test_bf069_llm_health.py tests/test_bf198_router_proactive_dedup.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf874_dm_e2e.py tests/test_bf925_event_log_window.py tests/test_bf934_s1_decision_routing.py tests/test_bf934_s2_secondary_gates.py tests/test_bf934_s3_intended_actions_ledger.py tests/test_circuit_breaker.py tests/test_combo_a_ad576b_retry.py tests/test_duty_schedule.py tests/test_onboarding.py tests/test_proactive.py -q -n 0 -p no:randomly
```

  (2) the architecture check. **Expected:** the S1, S2 and S3 files 22, 26 and 43 passed; every other file 0 failed and collected counts equal M0; the check clean (the freeze test passes with the two new pairs).
- **G3 (every slice).** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Suite order.** The gate and CI run `--dist=loadfile` (whole files per worker, in collection order), so a new file can run in a worker after any earlier file. `rg` over `tests` found no class-level assignment (`Class.attr = ...`) on `CognitiveAgent`, `ProactiveCognitiveLoop`, `WardRoomService`, `WardRoomRouter`, `RecordsStore`, `EventLog`, `SubTaskExecutor`, `NoveltyGate` or `WardRoomPostPipeline`, and no assignment to an attribute of `proactive` or `cognitive_agent` as a module that is not restored; the `type(x).attr = ...` assignments it found are on other classes (section 11). The new tests restore what they change (`monkeypatch`, and `tmp_path` databases the world closes on exit), clear the three module caches of `cognitive_agent.py` (`_DECISION_CACHES`, `_CACHE_HITS`, `_CACHE_MISSES`) when the world opens, use no network and no sleeping, and read no clock they could not do without.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of a new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`, after the three slices are committed.

## 5. Commit messages

- **S1 M1:** `BF-934 S1 M1: tests for a proactive think whose triage decided a proposal or a notebook entry, xfail until built (#1673)`
- **S1 M2:** `BF-934 S1 M2: the single call receives the triage's decision to file a proposal or write a notebook entry, with the format of the block (#1673)`
- **S1 M3:** `BF-934 S1 M3: trackers and ledger (#1673)`; its body ends with the line `Refs #1673.`
- **S2 M1:** `BF-934 S2 M1: tests for the gates that discarded an action the output carried and for a proposal that was not filed, xfail until built (#1673)`
- **S2 M2:** `BF-934 S2 M2: a valid block beside [NO_RESPONSE] is carried out, the extraction runs before the similarity and novelty gates, a re-reflect never removes an action, and a proposal that is not filed says why (#1673)`
- **S2 M3:** `BF-934 S2 M3: trackers and ledger (#1673)`; its body ends with the line `Refs #1673.`
- **S3 M1:** `BF-934 S3 M1: tests for every intended action being carried out or recorded as dropped, xfail until built (#1673)`
- **S3 M2:** `BF-934 S3 M2: the decision and each intended action nothing carried out are recorded per agent and action, with a reason (#1673)`
- **S3 M3:** `BF-934 S3 M3: trackers and ledger (#1673)`; its body ends with the line `Closes #1673.` (the orchestrator may use `Refs #1673.` to keep the issue open until section 15 is done)

## 6. Tests

Four new files: `tests/bf934_world.py` (the shared world; no test of its own) and one test module per slice. In each module the functions before the classes pass on both trees; the classes carry `pytest.mark.xfail(raises=AssertionError, strict=True)` until M2 removes the marker. No BF-934 name is imported at module level (a module M2 builds is imported by `_built`, which fails at its own assert until then).

### S1: `tests/test_bf934_s1_decision_routing.py` (22 cases; 6 pass and 16 xfail at M1)

| Id | Cases | Covers (function) | xfail until |
|---|---|---|---|
| T1 | 1 | Control: a model that writes the blocks on its own has them posted and written (`test_control_a_model_that_writes_the_blocks_has_them_posted_and_written`) | none |
| T2 | 4 | A decision that names no proposal or notebook leaves the single call as it was: `["silent"]` makes no model call, `["oracle_query"]`, `["leadership_review"]` and `["speak_freely"]` leave the closing line and no heading (`test_a_decision_that_names_no_proposal_or_notebook_leaves_the_single_call_as_it_was`) | none |
| T3 | 1 | A decision does not outlive its turn: a triage that fails leaves a stale key of a reused dict out of the prompt (`test_a_decision_does_not_outlive_its_turn`) | none |
| T4 | 1 | Class, the seam: triage `['proposal','notebook']`, a model that obeys the decision it is shown, a thread titled `[Proposal] Cache the roster` in Improvement Proposals and a notebook entry on disk (`test_a_decided_proposal_and_notebook_are_posted_and_written`) | M2 |
| T5 | 5 | Class: the single call is shown the decision for `proposal`, `notebook`, both, `notebook` with `ward_room_lookup`, and `silent` with `proposal`: the heading, no default closing, only the formats decided, the key on the observation (`test_the_single_call_is_shown_the_decision`) | M2 |
| T6 | 1 | Class: a duty think keeps its report line and loses the default of silence (`test_a_duty_think_keeps_its_report_line_and_loses_the_default_of_silence`) | M2 |
| T7 | 1 | Class: a chain that cannot run (no COMPOSE handler, so it falls back) still hands over the decision, the communication tag named (`test_a_chain_that_cannot_run_still_hands_over_the_decision`) | M2 |
| T8 | 1 | Class: the proposal format is the block COMPOSE's AD-651a billet shows (`test_the_proposal_format_is_the_one_compose_shows`) | M2 |
| T9 | 1 | Class: the billet names the decision and only the formats it needs (`test_the_billet_names_the_decision_and_only_the_formats_it_needs`) | M2 |
| T10 | 6 | Class: any other decision gets no billet: none, empty, `silent`, `ward_room_post`, `oracle_query` with `dm`, `speak_freely` (`test_any_other_decision_gets_no_billet`) | M2 |

**How each xfail case fails on the base.** T4 at `assert await threads(w, "Improvement Proposals") == [...]` (the model answered the silence it defaults to, so no thread); T5 to T7 at `assert DECIDED in prompt` (the base prompt has no heading); T8 to T10 at the `_built` helper's own assert (the module does not exist). The controls and T2, T3 pass on the base.

### S2: `tests/test_bf934_s2_secondary_gates.py` (26 cases; 5 pass and 21 xfail at M1)

| Id | Cases | Covers (function) | xfail until |
|---|---|---|---|
| T1 | 1 | Control: a valid proposal beside an observation is filed beside it (`test_control_a_valid_proposal_beside_an_observation_is_filed_beside_it`) | none |
| T2 | 3 | A withdrawn output without a valid block posts nothing: the bare marker, a one-line block, a block without a Rationale (`test_a_withdrawn_output_without_a_valid_block_posts_nothing`) | none |
| T3 | 1 | Control: a re-reflect that keeps every block still replaces the approved output (`test_control_a_re_reflect_that_keeps_every_block_still_replaces_the_approved_output`) | none |
| T4 | 3 | Class: a withdrawn observation does not withdraw a valid block: a proposal, a notebook entry, both (`test_a_withdrawn_observation_does_not_withdraw_a_valid_block`) | M2 |
| T5 | 1 | Class: the observation stays withdrawn beside a valid block (prose, the marker and a proposal files the proposal and posts no prose) (`test_a_withdrawn_observation_stays_withdrawn_beside_a_valid_block`) | M2 |
| T6 | 1 | Class: a proposal attached to a repeated observation is still filed, the repeat not posted (`test_a_proposal_attached_to_a_repeated_observation_is_still_filed`) | M2 |
| T7 | 1 | Class: a notebook entry attached to a rehashed observation is still written, the rehash not posted (`test_a_notebook_entry_attached_to_a_rehashed_observation_is_still_written`) | M2 |
| T8 | 2 | Class: a re-reflect may not remove an action or silence an approved output (`test_a_re_reflect_may_not_remove_an_action_or_silence_an_approved_output`) | M2 |
| T9 | 3 | Class: a proposal that cannot be filed says so: malformed, no Title, no Rationale (the entry, the WARNING naming the callsign, no thread) (`test_a_proposal_that_cannot_be_filed_says_so`) | M2 |
| T10 | 3 | Class: a proposal the router does not file is not counted as filed: no router, refused, raises (`test_a_proposal_the_router_does_not_file_is_not_counted_as_filed`) | M2 |
| T11 | 1 | Class: a second proposal block is not silently dropped (`test_a_second_proposal_block_is_not_silently_dropped`) | M2 |
| T12 | 5 | Class: the problem a text has: none, no block, malformed, no Title, no Rationale (`test_the_problem_a_text_has`) | M2 |
| T13 | 1 | Class: a valid block is read as the extractor always read it (`test_a_valid_block_is_read_as_the_extractor_always_read_it`) | M2 |

**How each xfail case fails on the base.** T4 to T7 at the assert on the Ward Room's threads or the notebook file (the base discards the block with the observation); T8 at `assert sorted(await threads(w)) == ...` (the rewrite replaced the output, so the proposal is not filed); T9 and T10 at `assert {"type": "proposal_suppressed", ...} in actions`; T11 at `assert "1 more [PROPOSAL] block(s)" in caplog.text`; T12 and T13 at the `_built` helper's own assert.

### S3: `tests/test_bf934_s3_intended_actions_ledger.py` (43 cases; 18 pass and 25 xfail at M1)

| Id | Cases | Covers (function) | xfail until |
|---|---|---|---|
| T1 | 6 | Control: each of the six actions a think is asked to carry out (`ward_room_post`, `ward_room_reply`, `endorse`, `dm`, `notebook`, `proposal`) is carried out by the loop, read from the Ward Room and Ship's Records (`test_control_each_action_a_think_is_asked_to_carry_out_is_carried_out_by_the_loop`) | none |
| T2 | 6 | An action the output carries leaves no drop (`test_an_action_the_output_carries_leaves_no_drop`) | none |
| T3 | 5 | A tag something else carries out (`silent`, `speak_freely`, `leadership_review`, `oracle_query`, `ward_room_lookup`) never has a drop (`test_a_tag_something_else_carries_out_never_has_a_drop`) | none |
| T4 | 1 | A decision that names no action leaves no record (`test_a_decision_that_names_no_action_leaves_no_record`) | none |
| T5 | 5 | Class: an action the output does not carry (`ward_room_reply`, `endorse`, `dm`, `notebook`, `proposal`) is dropped with `no_block_executed`, one row, and said at WARNING (`test_an_action_the_output_does_not_carry_is_dropped_with_a_reason_and_said`) | M2 |
| T6 | 1 | Class: an observation the gates withhold is dropped too (`no_response`) but only noted at INFO (`test_an_observation_the_gates_withhold_is_dropped_too_but_only_noted`) | M2 |
| T7 | 1 | Class: a notebook entry the writer declines as a repeat is only noted, and marked `by_design` (`test_a_notebook_entry_the_writer_declines_as_a_repeat_is_only_noted`) | M2 |
| T8 | 1 | Class: a think that fails drops every action the decision named (`think_failed`) (`test_an_output_that_fails_to_think_drops_every_action_the_decision_named`) | M2 |
| T9 | 1 | Class: a row that cannot be written never blocks the think and is logged (`test_a_row_that_cannot_be_written_never_blocks_the_think`) | M2 |
| T10 | 5 | Class: each exit of the think names its reason: `raw_intent_json`, `empty_after_extraction`, `no_response` beside a block, `similar_to_recent_post`, `not_novel` (`test_each_exit_of_the_think_names_its_reason`) | M2 |
| T11 | 1 | Class: the observation post says whether a thread was created (`test_the_observation_post_says_whether_a_thread_was_created`) | M2 |
| T12 | 1 | Class: an observation no channel can take is dropped as `not_posted` (`test_an_observation_no_channel_can_take_is_dropped_as_not_posted`) | M2 |
| T13 | 1 | Class, the reconciliation: decided equals posted plus dropped, per agent and action, from the three named sources (`test_decided_equals_posted_plus_dropped_per_agent_and_action`) | M2 |
| T14 | 1 | Class: a decision made for another intent is not recorded (`test_a_decision_made_for_another_intent_is_not_recorded`) | M2 |
| T15 | 1 | Class: the registry holds exactly the tags both ANALYZE prompts offer (`test_the_registry_holds_exactly_the_tags_the_analyze_prompts_offer`) | M2 |
| T16 | 5 | Class: what nothing carried out, and why (`test_what_nothing_carried_out_and_why`) | M2 |
| T17 | 1 | Class: the lifecycle carries the decision to the caller, bounded (`test_the_lifecycle_carries_the_decision_to_the_caller_bounded`) | M2 |

**How each xfail case fails on the base.** T5, T6, T8, T9, T10 and T12 at the first assert on the `dropped` rows (the base writes none); T7 at the assert on the INFO line; T11 at `is True` (the method returns `None`); T13 at `assert len(decided) == 3` (no `declared` rows); T14 to T17 at the `_built` helper's own assert or at the metadata assert (the key is absent). The controls and T2 to T4 pass on the base.

## 7. The contract

Slice by slice, in label order; within a slice M1 (tests), M2 (source, then the removal of the xfail markers) and M3 (trackers). Labels restart in each slice (N1-n tests, P2-n source, N2-n marker removal, P3-n trackers) and each slice's blocks apply after the earlier slice's. A path in a label line names the file of every block after it until the next label that names another.

### Slice S1: the single call receives the decision

#### S1 / M1

**N1-1.** New file `tests/bf934_world.py`:

```python
"""BF-934 (#1673): the world the think-cycle tests of slices S1 to S3 share.

Real: ProactiveCognitiveLoop, WardRoomService and WardRoomRouter (SQLite on tmp_path), RecordsStore (tmp_path), TrustNetwork, the
registries, SubTaskExecutor, and a CognitiveAgent run through handle_intent. Doubles, named: the model (``Model``: one scripted answer per
request, the requests kept), the triage's ANALYZE and QUERY handlers (``Analysis``, ``Query``: no model call) and the runtime, a SimpleNamespace
that holds exactly what the think cycle reads. No network, no sleeping, no real clock where a fake will do. It imports no BF-934 name.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from probos.cognitive.cognitive_agent import _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES, CognitiveAgent
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.novelty_gate import NoveltyVerdict
from probos.cognitive.sub_task import SubTaskExecutor, SubTaskResult, SubTaskType
from probos.config import RecordsConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry, Rank
from probos.knowledge.records_store import RecordsStore
from probos.mesh.intent import IntentBus
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.event_log import EventLog
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.types import IntentResult, LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_router import WardRoomRouter

#: The heading S1's billet carries. A model double that answers only a prompt holding it stands for a model that obeys a decision it is shown.
DECIDED = "Your triage already decided this turn"
BLOCKS = (
    "Noted for the record.\n"
    "[PROPOSAL]\n"
    "Title: Cache the roster\n"
    "Rationale: The roster is read forty times per cycle and never changes.\n"
    "Affected Systems: Ward Room\n"
    "Priority: low\n"
    "[/PROPOSAL]\n"
    "[NOTEBOOK roster-cache]\n"
    "The roster is read 40 times per cycle.\n"
    "[/NOTEBOOK]"
)
CREW = (("science_officer", "Kira", "science"), ("security_officer", "Worf", "security"), ("counselor", "Troi", "medical"))


def obeys_decision(request: Any) -> str:
    """The model double: the blocks when its prompt carries the decision, else the silence the single call defaults to."""
    return BLOCKS if DECIDED in request.prompt else "[NO_RESPONSE]"


class Model(MockLLMClient):
    """One scripted answer per request; every request is kept."""

    def __init__(self, answer: Callable[[Any], str]) -> None:
        super().__init__()
        self._answer = answer
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._answer(request), model="test-model")


class Analysis:
    """ANALYZE's contract with no model call: the actions this triage intends."""

    def __init__(self, intended: list[str]) -> None:
        self.intended = intended

    async def __call__(self, spec: Any, context: dict, prior: list) -> SubTaskResult:
        result = {"intended_actions": list(self.intended), "composition_brief": {"situation": "test"}}
        return SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name=spec.name, success=True, result=result)


class Query:
    async def __call__(self, spec: Any, context: dict, prior: list) -> SubTaskResult:
        return SubTaskResult(sub_task_type=SubTaskType.QUERY, name=spec.name, success=True, result={})


class NothingIsNovel:
    """AD-493's gate finding every observation a repeat."""

    def check(self, agent_id: str, text: str) -> NoveltyVerdict:
        return NoveltyVerdict(is_novel=False, similarity=0.99, reason="repeated", matched_preview="earlier")

    def record(self, agent_id: str, text: str) -> None:
        pass


class Crew(CognitiveAgent):
    agent_type = "science_officer"
    _handled_intents = {"proactive_think"}
    instructions = "You are a test crew agent."


@dataclass
class World:
    ws: WardRoomService
    rt: SimpleNamespace
    loop: ProactiveCognitiveLoop
    records: RecordsStore
    registry: AgentRegistry
    events: EventLog | None
    ids: dict[str, str]

    def notebook(self, callsign: str, slug: str) -> Path:
        return self.records.repo_path / "notebooks" / callsign / f"{slug}.md"


@asynccontextmanager
async def world(tmp_path: Path, *, event_log: bool = False) -> AsyncIterator[World]:
    """A started ship; ``event_log`` adds a real EventLog on tmp_path (slice S3). Everything it opens is closed on exit."""
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ws.start()
    records = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await records.initialize()
    events = EventLog(tmp_path / "events.db") if event_log else None
    if events is not None:
        await events.start()
    try:
        registry = AgentRegistry()
        callsigns = CallsignRegistry()
        ids = {agent_type: generate_pool_ids(agent_type, agent_type, 1)[0] for agent_type, _, _ in CREW}
        for agent_type, callsign, _ in CREW:
            callsigns.set_callsign(agent_type, callsign)
        callsigns.bind_registry(registry)
        depts = {agent_type: dept for agent_type, _, dept in CREW}
        config = SystemConfig()
        router = WardRoomRouter(
            ward_room=ws, registry=MagicMock(spec=AgentRegistry), intent_bus=MagicMock(spec=IntentBus),
            trust_network=MagicMock(), ontology=None, callsign_registry=callsigns, episodic_memory=None,
            event_emitter=MagicMock(), event_log=AsyncMock(), config=config,
        )
        rt = SimpleNamespace(
            ward_room=ws, registry=registry, callsign_registry=callsigns,
            ontology=SimpleNamespace(get_agent_department=lambda agent_type: depts.get(agent_type)),
            config=config, trust_network=TrustNetwork(), ward_room_router=router, episodic_memory=None,
            hebbian_router=None, dispatcher=None, _records_store=records, working_memory=None,
            dm_sanity_gate=DmSanityGate(), skill_service=None, boot_camp=None, emit_event=lambda *a, **k: None,
        )
        if events is not None:
            rt.event_log = events
        loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
        loop.set_runtime(rt)
        for agent_type, callsign, _ in CREW[1:]:
            await registry.register(SimpleNamespace(
                id=ids[agent_type], agent_type=agent_type, pool=agent_type, callsign=callsign, is_alive=True, capabilities=[],
            ))
        yield World(ws, rt, loop, records, registry, events, ids)
    finally:
        await ws.stop()
        if events is not None:
            await events.stop()


async def crew(w: World, intended: list[str], answer: Callable[[Any], str]) -> tuple[Crew, Model]:
    """The real science officer (Kira): a real CognitiveAgent whose triage intends *intended* and whose model is *answer*."""
    model = Model(answer)
    agent = Crew(agent_id=w.ids["science_officer"], llm_client=model, runtime=w.rt)
    agent.callsign = "Kira"
    executor = SubTaskExecutor(config=w.rt.config.sub_task)  # enabled by default: AD-643a's routing runs, as it does on the ship
    executor.register_handler(SubTaskType.QUERY, Query())
    executor.register_handler(SubTaskType.ANALYZE, Analysis(intended))
    agent.set_sub_task_executor(executor)
    await w.registry.register(agent)
    return agent, model


def thinker(w: World, reply: str, metadata: dict | None = None) -> SimpleNamespace:
    """Kira with the model left out: ``handle_intent`` answers *reply* with *metadata*, as the cognitive agent's lifecycle would."""
    agent = SimpleNamespace(
        id=w.ids["science_officer"], agent_type="science_officer", pool="science_officer", callsign="Kira",
        is_alive=True, capabilities=[],
    )

    async def handle_intent(intent: Any) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id=agent.id, success=True, result=reply, metadata=dict(metadata or {}))

    agent.handle_intent = handle_intent
    return agent


def observation() -> dict[str, Any]:
    """The observation a free-form proactive think perceives."""
    return {
        "intent": "proactive_think", "intent_id": "bf934-intent", "context": "ship status",
        "params": {"context_parts": {}, "trust_score": "0.6", "agency_level": "suggestive", "rank": "lieutenant", "duty": None},
    }


async def think(w: World, agent: Any, trust: float = 0.6) -> None:
    """One real think cycle for *agent* (a Lieutenant)."""
    await w.loop._think_for_agent(agent, Rank.LIEUTENANT, trust)


async def threads(w: World, channel: str | None = None) -> list[str]:
    """The titles of every thread, or of those in the channel called *channel*, oldest first."""
    titles: list[tuple[float, str]] = []
    for ch in await w.ws.list_channels():
        if channel is None or ch.name == channel:
            titles.extend((th.created_at, th.title) for th in await w.ws.list_threads(ch.id, limit=500))
    return [title for _, title in sorted(titles)]
```

**N1-2.** New file `tests/test_bf934_s1_decision_routing.py`:

```python
"""BF-934 (#1673) S1: a triage that decided to file a proposal or write a notebook entry hands the decision to the call that writes the output.

The real think cycle runs end to end (``ProactiveCognitiveLoop._think_for_agent`` into ``CognitiveAgent.handle_intent``: AD-643a's routing, the single call, the
real extraction, the real Ward Room and Ship's Records on tmp_path). The model double obeys a decision it is shown and otherwise answers ``[NO_RESPONSE]``, the single
call's default (22 of the issue's 24 cases); the triage's ANALYZE and QUERY handlers are doubles (tests/bf934_world.py). The classes hold the cases the unfixed tree
fails; the functions before them pass on both. No BF-934 name is imported at module level.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.sub_task import SubTaskError, SubTaskResult, SubTaskType
from probos.cognitive.sub_tasks.compose import _build_proactive_compose_prompt
from tests.bf934_world import BLOCKS, DECIDED, crew, obeys_decision, observation, think, threads, world

CLOSING = "Include your justification. Otherwise respond with exactly: [NO_RESPONSE]"  # the single call's last line for a free-form think


def _built(name: str):
    """The module M2 builds. Until then this fails at its own assert, as the xfail marker requires (an ImportError would not)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        assert False, f"{name} is built by M2"


async def test_control_a_model_that_writes_the_blocks_has_them_posted_and_written(tmp_path):
    async with world(tmp_path) as w:
        agent, _ = await crew(w, ["proposal", "notebook"], lambda request: BLOCKS)
        await think(w, agent)
        assert await threads(w, "Improvement Proposals") == ["[Proposal] Cache the roster"]
        assert "read 40 times" in w.notebook("Kira", "roster-cache").read_text(encoding="utf-8")


@pytest.mark.parametrize("intended", [["silent"], ["oracle_query"], ["leadership_review"], ["speak_freely"]])
async def test_a_decision_that_names_no_proposal_or_notebook_leaves_the_single_call_as_it_was(tmp_path, intended):
    async with world(tmp_path) as w:
        agent, model = await crew(w, intended, obeys_decision)
        decision = await agent.decide(observation())
        if intended == ["silent"]:
            assert decision["llm_output"] == "[NO_RESPONSE]" and model.requests == []
        else:
            assert len(model.requests) == 1 and DECIDED not in model.requests[0].prompt
            assert model.requests[0].prompt.endswith(CLOSING)


async def test_a_decision_does_not_outlive_its_turn(tmp_path):
    async with world(tmp_path) as w:
        agent, model = await crew(w, ["proposal"], obeys_decision)
        agent._sub_task_executor.execute = AsyncMock(side_effect=SubTaskError("triage timed out"))
        reused = observation()
        reused["_intended_actions"] = ["proposal"]  # what an earlier triage left on a dict that is used again
        await agent.decide(reused)
        assert len(model.requests) == 1 and DECIDED not in model.requests[0].prompt


class TestTheDecisionReachesTheCallThatWritesTheOutput:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S1 M2 builds it")

    async def test_a_decided_proposal_and_notebook_are_posted_and_written(self, tmp_path):
        async with world(tmp_path) as w:
            agent, _ = await crew(w, ["proposal", "notebook"], obeys_decision)
            await think(w, agent)
            assert await threads(w, "Improvement Proposals") == ["[Proposal] Cache the roster"]
            note = w.notebook("Kira", "roster-cache")
            assert note.is_file() and "read 40 times" in note.read_text(encoding="utf-8")

    @pytest.mark.parametrize("intended", [["proposal"], ["notebook"], ["proposal", "notebook"], ["notebook", "ward_room_lookup"], ["silent", "proposal"]])
    async def test_the_single_call_is_shown_the_decision(self, tmp_path, intended):
        async with world(tmp_path) as w:
            agent, model = await crew(w, intended, obeys_decision)
            observed = observation()
            await agent.decide(observed)
            prompt = model.requests[0].prompt
            assert DECIDED in prompt and "Otherwise respond with exactly" not in prompt
            billet = prompt.split(DECIDED)[1]
            assert ("[PROPOSAL]" in billet) == ("proposal" in intended)
            assert ("[NOTEBOOK topic-slug]" in billet) == ("notebook" in intended)
            assert observed["_intended_actions"] == intended

    async def test_a_duty_think_keeps_its_report_line_and_loses_the_default_of_silence(self, tmp_path):
        async with world(tmp_path) as w:
            agent, model = await crew(w, ["proposal"], obeys_decision)
            observed = observation()
            observed["params"]["duty"] = {"duty_id": "systems_check", "description": "Review systems"}
            await agent.decide(observed)
            prompt = model.requests[0].prompt
            assert DECIDED in prompt and "Compose a Ward Room post with your findings" in prompt
            assert "If nothing noteworthy to report, respond with exactly" not in prompt

    async def test_a_chain_that_cannot_run_still_hands_over_the_decision(self, tmp_path):
        async with world(tmp_path) as w:
            agent, model = await crew(w, ["ward_room_post", "proposal"], obeys_decision)  # no COMPOSE handler: the chain falls back to the single call
            await agent.decide(observation())
            prompt = model.requests[0].prompt
            assert DECIDED in prompt
            billet = prompt.split(DECIDED)[1]
            assert "ward_room_post" in billet and "[PROPOSAL]" in billet


class TestTheBilletText:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S1 M2 builds it")

    def test_the_proposal_format_is_the_one_compose_shows(self):
        billets = _built("probos.cognitive.action_billets")
        prior = [SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="analyze", success=True, result={
            "intended_actions": ["ward_room_post", "proposal"], "composition_brief": {"situation": "s"}, "contribution_assessment": "RESPOND"})]
        system, _ = _build_proactive_compose_prompt({"context": "x", "mode": "proactive_observation"}, prior, "Keiko", "medical")
        start = system.index("AFTER your observation text:\n") + len("AFTER your observation text:\n")
        assert system[start:system.index("The proposal will be automatically posted")] == billets.PROPOSAL_FORMAT

    def test_the_billet_names_the_decision_and_only_the_formats_it_needs(self):
        billets = _built("probos.cognitive.action_billets")
        both = billets.decision_billet(["proposal", "notebook"])
        assert billets.DECISION_HEADING in both and billets.PROPOSAL_FORMAT.rstrip("\n") in both and billets.NOTEBOOK_FORMAT.rstrip("\n") in both
        only = billets.decision_billet([" Notebook "])
        assert "[NOTEBOOK topic-slug]" in only and "[PROPOSAL]" not in only
        assert billets.DECISION_HEADING == DECIDED

    @pytest.mark.parametrize("intended", [None, [], ["silent"], ["ward_room_post"], ["oracle_query", "dm"], ["speak_freely"]])
    def test_any_other_decision_gets_no_billet(self, intended):
        assert _built("probos.cognitive.action_billets").decision_billet(intended) == ""
```

#### S1 / M2

**P2-1.** New file `src/probos/cognitive/action_billets.py`:

```python
"""BF-934 (#1673): what a model is told when the triage has already decided to take an action.

The triage (ANALYZE) names the actions a turn will take (``intended_actions``). COMPOSE tells the model the proposal format when ``proposal`` is among them
(AD-651a), but a triage that names no communication action skips COMPOSE (AD-643a), and a chain that fails falls back to the single call. Neither passed the
decision on: the single call treats silence as the expected default and decided again, mostly for silence. ``decision_billet`` is the text the single call is
given instead. Nothing is added for any other set of actions.
"""

from __future__ import annotations

from collections.abc import Iterable

#: The block ``ProactiveCognitiveLoop._extract_and_execute_actions`` reads as a proposal. COMPOSE's AD-651a billet shows the same block
#: (tests/test_bf934_s1_decision_routing.py pins the two equal).
PROPOSAL_FORMAT = (
    "```\n"
    "[PROPOSAL]\n"
    "Title: <short descriptive title>\n"
    "Rationale: <why this matters and what it would improve \u2014 be specific, "
    "cite evidence from your analysis>\n"
    "Affected Systems: <comma-separated subsystem names>\n"
    "Priority: low|medium|high\n"
    "[/PROPOSAL]\n"
    "```\n"
)

#: The block the notebook writer reads (``proactive._NOTEBOOK_PATTERN``); the optional scope word is taught by the standing orders.
NOTEBOOK_FORMAT = (
    "```\n"
    "[NOTEBOOK topic-slug]\n"
    "<your analysis, findings or report>\n"
    "[/NOTEBOOK]\n"
    "```\n"
)

#: The heading of the billet; tests/bf934_world.py answers a prompt that carries it, as a model that obeys a decision it is shown.
DECISION_HEADING = "Your triage already decided this turn"

_BLOCK_TAGS = ("proposal", "notebook")  # the tags whose block the single call has no other reason to write
_COMPANION_TAGS = ("ward_room_post", "ward_room_reply", "endorse", "dm")  # written in the formats the standing orders already give


def decision_billet(intended: Iterable[object] | None) -> str:
    """The text that gives the single call the triage's decision, or "" when the decision names no proposal or notebook entry.

    Every other set of intended actions leaves the call as it was: ``silent`` never reaches it, and ``oracle_query``, ``ward_room_lookup``,
    ``speak_freely`` and ``leadership_review`` alone ask it for no block.
    """
    if intended is None:
        return ""
    tags = list(dict.fromkeys(str(tag).strip().lower() for tag in intended))
    if not any(tag in tags for tag in _BLOCK_TAGS):
        return ""
    lines = [
        f"\n\n## {DECISION_HEADING}",
        f"Before this step you decided to take these actions: {', '.join(tags)}.",
        "That decision stands for this turn, so the usual default of silence does not apply here: carry it out with the blocks below, "
        "after any observation text you also write. If you find that the evidence no longer supports an action, answer exactly "
        "[NO_RESPONSE]; that withdrawal is recorded.",
    ]
    if "proposal" in tags:
        lines += ["", "**You decided to file an improvement proposal.** Use this exact format as a SEPARATE block:", PROPOSAL_FORMAT.rstrip("\n")]
    if "notebook" in tags:
        lines += ["", "**You decided to write a notebook entry.** Use this format as a SEPARATE block:", NOTEBOOK_FORMAT.rstrip("\n")]
    companions = [tag for tag in tags if tag in _COMPANION_TAGS]
    if companions:
        lines += ["", f"You also decided: {', '.join(companions)}. Use the formats your standing orders give for them."]
    return "\n".join(lines)
```

**P2-2.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
from probos.cognitive import context_manifest  # AD-1357
```
REPLACE:
```
from probos.cognitive import context_manifest  # AD-1357
from probos.cognitive.action_billets import decision_billet  # BF-934
```

**P2-3.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
        # --- Inject agent context (same keys as _execute_sub_task_chain) ---
```
REPLACE:
```
        # BF-934: the decision belongs to this triage; a dict that is used again never carries an older one forward.
        observation.pop("_intended_actions", None)

        # --- Inject agent context (same keys as _execute_sub_task_chain) ---
```

**P2-4.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
        # --- Extract intended_actions ---
        intended_actions = self._extract_intended_actions(triage_results)
```
REPLACE:
```
        # --- Extract intended_actions ---
        intended_actions = self._extract_intended_actions(triage_results)
        # BF-934: whichever call writes this turn's output reads the decision from here (``decision_billet``).
        observation["_intended_actions"] = intended_actions
```

**P2-5.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
            if duty:
                pt_parts.append("Compose a Ward Room post with your findings (2-4 sentences).")
                pt_parts.append("If nothing noteworthy to report, respond with exactly: [NO_RESPONSE]")
            else:
                pt_parts.append("If something genuinely warrants attention, compose a brief observation (2-4 sentences).")
                pt_parts.append("Include your justification. Otherwise respond with exactly: [NO_RESPONSE]")
            return "\n".join(pt_parts)
```
REPLACE:
```
            # BF-934: a triage that decided to file a proposal or write a notebook entry says so here, in place of the closing
            # default of silence; any other turn keeps the closing it had.
            _decided = decision_billet(observation.get("_intended_actions"))
            if duty:
                pt_parts.append("Compose a Ward Room post with your findings (2-4 sentences).")
                if not _decided:
                    pt_parts.append("If nothing noteworthy to report, respond with exactly: [NO_RESPONSE]")
            elif not _decided:
                pt_parts.append("If something genuinely warrants attention, compose a brief observation (2-4 sentences).")
                pt_parts.append("Include your justification. Otherwise respond with exactly: [NO_RESPONSE]")
            if _decided:
                pt_parts.append(_decided)
            return "\n".join(pt_parts)
```

**N2-1.** `tests/test_bf934_s1_decision_routing.py`
SEARCH:
```
class TestTheDecisionReachesTheCallThatWritesTheOutput:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S1 M2 builds it")

    async def test_a_decided_proposal_and_notebook_are_posted_and_written(self, tmp_path):
```
REPLACE:
```
class TestTheDecisionReachesTheCallThatWritesTheOutput:
    async def test_a_decided_proposal_and_notebook_are_posted_and_written(self, tmp_path):
```

**N2-2.** `tests/test_bf934_s1_decision_routing.py`
SEARCH:
```
class TestTheBilletText:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S1 M2 builds it")

    def test_the_proposal_format_is_the_one_compose_shows(self):
```
REPLACE:
```
class TestTheBilletText:
    def test_the_proposal_format_is_the_one_compose_shows(self):
```

#### S1 / M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-934 S1 (DATE), #1673 -- a proactive think whose triage decided to file a proposal or write a notebook entry hands the decision to the call that writes the output (slice 1 of 3).**
- **Base.** A triage that decided `proposal` or `notebook` and no chat action (`ward_room_post`, `ward_room_reply`, `endorse`, `dm`) skipped the chain (`AD-643a: No comm actions in ... -- skipping chain, using single-call`), and the single call that answered was never told: its prompt ended with the default of silence, so it answered `[NO_RESPONSE]` and the proposal or entry was never written (24 of the issue's 31 lost proposals, as the issue counts them; the notebook the same way, by an in-memory seam run).
- **Fix.** New `cognitive/action_billets.py`: `decision_billet` gives the single call the decision and the format of the block (the proposal block COMPOSE's AD-651a billet shows; a notebook block) in place of the default closing lines, only when `proposal` or `notebook` was decided. `CognitiveAgent` keeps the decision on the observation for the turn (`_intended_actions`, cleared when a triage starts), so a chain that falls back to the single call hands it over too. Any other decision leaves the prompt as it was. Contract `prompts/bf-934-dropped-crew-proposals.md`. Refs #1673.

```

**P3-2.** `DECISIONS.md`. Append after BF-935's entry (the file stays in landing order). The anchor, the last bullet of BF-935's entry, occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-935 commits; a report written with the new field then fails `ScoutFinding(**f)` in `_load_latest_report` until a newer report is written (L4); reverting the A1 commit alone restores the model round trip for `scout_report`, reverting the A2 commit alone restores the markup parse in the Scout command, and reverting the A3 commit alone restores the test console as A2 left it (no source file is involved).
```
REPLACE:
```
- *Residual.* L1 to L12 of the contract. *Reversal.* Revert the BF-935 commits; a report written with the new field then fails `ScoutFinding(**f)` in `_load_latest_report` until a newer report is written (L4); reverting the A1 commit alone restores the model round trip for `scout_report`, reverting the A2 commit alone restores the markup parse in the Scout command, and reverting the A3 commit alone restores the test console as A2 left it (no source file is involved).

### BF-934 -- A proactive think whose triage decided a proposal or a notebook entry hands the decision to the call that writes the output (slice 1 of 3; DATE, #1673)

- *Scope.* `cognitive/action_billets.py` (new), `cognitive/cognitive_agent.py` (the routing function keeps the decision on the observation; `_build_user_message` replaces the default closing), `tests/bf934_world.py` (the shared world), tests. Contract `prompts/bf-934-dropped-crew-proposals.md`. Slice 1 of #1673.
- *G1 (the routing).* The single call receives `intended_actions` and a billet when `proposal` or `notebook` was decided; the chain is not made to run for them. Rejected: adding the two tags to `_COMM_ACTIONS` (5 model calls where 2 run today, COMPOSE's billet read from the second ANALYZE, an observation nobody decided, no notebook billet, and two existing tests pin the chain's triggers); reusing the triage's ANALYZE (a new cache in every chain).
- *G2 (every other decision).* None changes: `["silent"]` never reaches the call, and a set with no `proposal` or `notebook` leaves the prompt byte for byte as before. A decision does not outlive its turn (the key is cleared when a triage starts).
- *G3 (the wording).* The billet says the decision stands and that the exact `[NO_RESPONSE]` withdraws it (recorded in slice 3). Whether it is strong enough for the real models is the live re-measure's question (the Captain).
- *Residual.* L1, L7, L11, L14 and L15 of the contract. *Reversal.* Revert the BF-934 slice 1 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.


### Slice S2: no gate discards an action the output carries, and a proposal that is not filed says why

#### S2 / M1

**N1-1.** New file `tests/test_bf934_s2_secondary_gates.py` (labels restart in each slice; S2's blocks apply after S1's):

```python
"""BF-934 (#1673) S2: no gate discards an action the output carries, and a proposal that is not filed says why.

Real: the think cycle, the action extraction, the Ward Room and its router, and the AD-643b re-reflect through AD-643a's routing. Doubles (tests/bf934_world.py): the triage's
ANALYZE and QUERY handlers, COMPOSE and REFLECT stand-ins below (no model call), a thinker whose ``handle_intent`` answers the text a model wrote, and a novelty gate that
finds everything repeated. The classes hold the cases the unfixed tree fails; the functions before them pass on both. No BF-934 name is imported at module level.
"""

from __future__ import annotations

import importlib
import logging
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskType
from tests.bf934_world import NothingIsNovel, crew, think, thinker, threads, world

PROPOSAL = "[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]"
NOTEBOOK = "[NOTEBOOK roster-cache]\nThe roster is read 40 times per cycle.\n[/NOTEBOOK]"
POSTED = "[Proposal] Cache the roster"
REPEATED = "The roster is read forty times per cycle and never changes anywhere."


def _built(name: str):
    """The module M2 builds. Until then this fails at its own assert, as the xfail marker requires (an ImportError would not)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        assert False, f"{name} is built by M2"


class _Compose:
    async def __call__(self, spec, context, prior):
        return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": f"Roster reads repeat.\n{PROPOSAL}"})


class _Reflect:
    """The first REFLECT keeps COMPOSE's output; the AD-643b re-reflect (the one handed the undeclared-action feedback) answers *second*."""

    def __init__(self, second: str) -> None:
        self.second = second

    async def __call__(self, spec, context, prior):
        kept = next((p.result["output"] for p in reversed(prior) if p.sub_task_type == SubTaskType.COMPOSE), "")
        output = self.second if context.get("_undeclared_action_feedback") else kept
        return SubTaskResult(sub_task_type=SubTaskType.REFLECT, name=spec.name, success=True, result={"output": output})


async def _undeclared_proposal(w, second):
    """Kira's triage intends only an observation; COMPOSE writes one with a proposal beside it (undeclared); the re-reflect answers *second*."""
    agent, _ = await crew(w, ["ward_room_post"], lambda request: "[NO_RESPONSE]")
    agent._sub_task_executor.register_handler(SubTaskType.COMPOSE, _Compose())
    agent._sub_task_executor.register_handler(SubTaskType.REFLECT, _Reflect(second))
    await think(w, agent)


async def test_control_a_valid_proposal_beside_an_observation_is_filed_beside_it(tmp_path):
    async with world(tmp_path) as w:
        await think(w, thinker(w, f"The roster is read too often.\n{PROPOSAL}"))
        assert sorted(await threads(w)) == sorted([POSTED, "[Observation] The roster is read too often."])


@pytest.mark.parametrize("reply", ["[NO_RESPONSE]", "[NO_RESPONSE]\n[PROPOSAL] Title: X [/PROPOSAL]", "[NO_RESPONSE]\n[PROPOSAL]\nTitle: X\n[/PROPOSAL]"])
async def test_a_withdrawn_output_without_a_valid_block_posts_nothing(tmp_path, reply):
    async with world(tmp_path) as w:
        await think(w, thinker(w, reply))
        assert await threads(w) == []


async def test_control_a_re_reflect_that_keeps_every_block_still_replaces_the_approved_output(tmp_path):
    async with world(tmp_path) as w:
        await _undeclared_proposal(w, f"Roster reads repeat, reworded.\n{PROPOSAL}")
        assert sorted(await threads(w)) == sorted([POSTED, "[Observation] Roster reads repeat, reworded."])


class TestNoGateDiscardsAnActionTheOutputCarries:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S2 M2 builds it")

    @pytest.mark.parametrize("blocks", [PROPOSAL, NOTEBOOK, f"{PROPOSAL}\n{NOTEBOOK}"])
    async def test_a_withdrawn_observation_does_not_withdraw_a_valid_block(self, tmp_path, blocks):
        async with world(tmp_path) as w:
            await think(w, thinker(w, f"[NO_RESPONSE]\n{blocks}"))
            assert await threads(w) == ([POSTED] if "PROPOSAL" in blocks else [])  # and no thread whose text is the marker
            note = w.notebook("Kira", "roster-cache")
            assert note.is_file() == ("NOTEBOOK" in blocks) and (not note.is_file() or "read 40 times" in note.read_text(encoding="utf-8"))

    async def test_a_withdrawn_observation_stays_withdrawn_beside_a_valid_block(self, tmp_path):
        async with world(tmp_path) as w:
            await think(w, thinker(w, f"Roster reads repeat. [NO_RESPONSE]\n{PROPOSAL}"))
            assert await threads(w) == [POSTED]  # the proposal is filed; the observation the model withdrew is not posted

    async def test_a_proposal_attached_to_a_repeated_observation_is_still_filed(self, tmp_path, monkeypatch):
        async with world(tmp_path) as w:
            monkeypatch.setattr(w.loop, "_is_similar_to_recent_posts", AsyncMock(return_value=True))  # BF-032's verdict is the input here (L-S2-1)
            await think(w, thinker(w, f"{REPEATED}\n{PROPOSAL}"))
            assert await threads(w) == [POSTED]  # the repeat itself is still not posted

    async def test_a_notebook_entry_attached_to_a_rehashed_observation_is_still_written(self, tmp_path):
        async with world(tmp_path) as w:
            w.loop.set_novelty_gate(NothingIsNovel())
            await think(w, thinker(w, f"Rehashed again.\n{NOTEBOOK}"))
            note = w.notebook("Kira", "roster-cache")
            assert note.is_file() and "read 40 times" in note.read_text(encoding="utf-8")
            assert await threads(w) == []  # the rehash itself is still not posted

    @pytest.mark.parametrize("second", ["[NO_RESPONSE]", "Roster reads repeat."])
    async def test_a_re_reflect_may_not_remove_an_action_or_silence_an_approved_output(self, tmp_path, second):
        async with world(tmp_path) as w:
            await _undeclared_proposal(w, second)
            assert sorted(await threads(w)) == sorted([POSTED, "[Observation] Roster reads repeat."])

    @pytest.mark.parametrize("text, reason, said", [
        ("[PROPOSAL] Title: X Rationale: Y [/PROPOSAL]", "malformed_block", "Malformed [PROPOSAL] block"),
        ("[PROPOSAL]\nRationale: Y\n[/PROPOSAL]", "missing_title", "not posted: missing_title"),
        ("[PROPOSAL]\nTitle: X\n[/PROPOSAL]", "missing_rationale", "not posted: missing_rationale"),
    ])
    async def test_a_proposal_that_cannot_be_filed_says_so(self, tmp_path, caplog, text, reason, said):
        async with world(tmp_path) as w:
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"Observation.\n{text}")
            assert {"type": "proposal_suppressed", "reason": reason} in actions and not [a for a in actions if a["type"] == "proposal"]
            assert said in caplog.text and "Kira" in caplog.text
            assert await threads(w, "Improvement Proposals") == []

    @pytest.mark.parametrize("failure, reason", [("no_router", "no_router"), ("refused", "router_refused: Improvement Proposals channel not found"), ("raises", "post_failed: ValueError")])
    async def test_a_proposal_the_router_does_not_file_is_not_counted_as_filed(self, tmp_path, caplog, monkeypatch, failure, reason):
        async with world(tmp_path) as w:
            if failure == "no_router":
                w.rt.ward_room_router = None
            elif failure == "refused":
                monkeypatch.setattr(w.ws, "get_channel_by_name", AsyncMock(return_value=None))
            else:
                monkeypatch.setattr(w.ws, "create_thread", AsyncMock(side_effect=ValueError("Author is restricted from posting")))
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"Observation.\n{PROPOSAL}")
            assert {"type": "proposal_suppressed", "reason": reason} in actions and not [a for a in actions if a["type"] == "proposal"]
            assert f"not posted: {reason}" in caplog.text and "Kira" in caplog.text

    async def test_a_second_proposal_block_is_not_silently_dropped(self, tmp_path, caplog):
        async with world(tmp_path) as w:
            second = PROPOSAL.replace("Cache the roster", "Index the roster")
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"{PROPOSAL}\n{second}")
            assert await threads(w, "Improvement Proposals") == [POSTED]
            assert [a["title"] for a in actions if a["type"] == "proposal"] == ["Cache the roster"]
            assert "1 more [PROPOSAL] block(s)" in caplog.text


class TestOneReadingOfAProposalBlock:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S2 M2 builds it")

    @pytest.mark.parametrize("text, problem", [
        ("Just an observation.", "no_block"),
        ("[PROPOSAL] Title: X Rationale: Y [/PROPOSAL]", "malformed_block"),
        ("[PROPOSAL]\nRationale: Y\n[/PROPOSAL]", "missing_title"),
        ("[PROPOSAL]\nTitle: X\n[/PROPOSAL]", "missing_rationale"),
        ("[PROPOSAL]  \n\nTitle: X\nRationale: Y  \n [/PROPOSAL]", ""),
    ])
    def test_the_problem_a_text_has(self, text, problem):
        assert _built("probos.cognitive.proposal_block").parse_proposal_block(text).problem == problem

    def test_a_valid_block_is_read_as_the_extractor_always_read_it(self):
        parsed = _built("probos.cognitive.proposal_block").parse_proposal_block(
            "Intro.\n[PROPOSAL]\nTitle: Improve dream consolidation\nRationale: Dream cycles discard low-weight memories\nthat could still be useful.\n"
            "Affected Systems: EpisodicMemory, DreamEngine\nPriority: HIGH\n[/PROPOSAL]\nOutro.\n[PROPOSAL]\nTitle: B\nRationale: C\n[/PROPOSAL]")
        assert (parsed.valid, parsed.found, parsed.title) == (True, True, "Improve dream consolidation")
        assert parsed.rationale == "Dream cycles discard low-weight memories\nthat could still be useful."
        assert (parsed.affected, parsed.priority, parsed.extra_blocks) == (("EpisodicMemory", "DreamEngine"), "high", 1)
```

#### S2 / M2

**P2-1.** New file `src/probos/cognitive/proposal_block.py`:

```python
"""BF-934 (#1673): the one reading of a ``[PROPOSAL]`` block.

``ProactiveCognitiveLoop._extract_and_execute_actions`` files a proposal from the first strict block of an output, and the proactive loop must also tell whether an
output carries a valid one before it reads ``[NO_RESPONSE]`` as silence. Both ask here, so the rule is written once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The strict shape of the block: newlines between the tags (AD-412).
PROPOSAL_PATTERN = r'\[PROPOSAL\]\s*\n(.*?)\n\s*\[/PROPOSAL\]'


@dataclass(frozen=True)
class ProposalParse:
    """What an output's proposal block is. ``problem`` is "" for a block that can be filed, else why not: "no_block" (no ``[PROPOSAL]`` at all),
    "malformed_block" (one without the strict shape), "missing_title" or "missing_rationale". ``extra_blocks`` counts the strict blocks after the
    first, which are not filed."""

    problem: str
    title: str = ""
    rationale: str = ""
    affected: tuple[str, ...] = ()
    priority: str = "medium"
    extra_blocks: int = 0

    @property
    def valid(self) -> bool:
        return self.problem == ""

    @property
    def found(self) -> bool:
        """True when the strict shape matched, whether or not the block can be filed."""
        return self.problem not in ("no_block", "malformed_block")


def parse_proposal_block(text: str) -> ProposalParse:
    """Read the first strict ``[PROPOSAL]`` block of *text*, as AD-412's extractor always has."""
    matches = list(re.finditer(PROPOSAL_PATTERN, text, re.DOTALL))
    if not matches:
        return ProposalParse("malformed_block" if re.search(r'\[PROPOSAL\]', text) else "no_block")
    title = ""
    affected: list[str] = []
    priority = "medium"
    in_rationale = False
    rationale_lines: list[str] = []
    for line in matches[0].group(1).split('\n'):
        stripped = line.strip()
        if stripped.lower().startswith("title:"):
            title = stripped[6:].strip()
            in_rationale = False
        elif stripped.lower().startswith("affected systems:"):
            affected = [s.strip() for s in stripped[17:].strip().split(",") if s.strip()]
            in_rationale = False
        elif stripped.lower().startswith("priority:"):
            p = stripped[9:].strip().lower()
            if p in ("low", "medium", "high"):
                priority = p
            in_rationale = False
        elif stripped.lower().startswith("rationale:"):
            rest = stripped[10:].strip()
            if rest:
                rationale_lines.append(rest)
            in_rationale = True
        elif in_rationale:
            rationale_lines.append(stripped)
    rationale = "\n".join(rationale_lines).strip()
    problem = "missing_title" if not title else "missing_rationale" if not rationale else ""
    return ProposalParse(problem, title, rationale, tuple(affected), priority, len(matches) - 1)
```

**P2-2.** `src/probos/proactive.py`
SEARCH:
```
from probos.cognitive.dm_sanity_gate import apply_dm_sanity
```
REPLACE:
```
from probos.cognitive.dm_sanity_gate import apply_dm_sanity
from probos.cognitive.proposal_block import PROPOSAL_PATTERN, parse_proposal_block  # BF-934
```

**P2-3.** `src/probos/proactive.py`
SEARCH:
```
    return _NOTEBOOK_PATTERN.sub("", text).strip(), [body for body in bodies if body]
```
REPLACE:
```
    return _NOTEBOOK_PATTERN.sub("", text).strip(), [body for body in bodies if body]


def carries_actionable_block(text: str) -> bool:
    """BF-934: whether *text* holds a block the extractor would carry out: a proposal it can file, or a notebook entry with a body.

    An output that withdraws the observation with ``[NO_RESPONSE]`` but still carries one is read for its blocks, not discarded as silence."""
    return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])
```

**P2-4.** `src/probos/proactive.py`
SEARCH:
```
        if not response_text or "[NO_RESPONSE]" in response_text:
            # Record duty execution even if agent had nothing to report
```
REPLACE:
```
        # BF-934: a withdrawn observation that still carries a valid block is not silence.
        if not response_text or ("[NO_RESPONSE]" in response_text and not carries_actionable_block(response_text)):
            # Record duty execution even if agent had nothing to report
```

**P2-5.** `src/probos/proactive.py` (the extraction and its empty-text exit leave this place; P2-6 puts them before the similarity gates)
SEARCH:
```
        # BF-172: Suppress raw JSON intent payloads leaking from LLM mode-confusion
        stripped = response_text.lstrip()
        if stripped.startswith("{") and '"intents"' in stripped[:200]:
            logger.warning(
                "BF-172: Suppressed raw intent JSON from %s (%d chars)",
                agent.agent_type, len(response_text),
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return

        # AD-437: Extract and process structured actions from proactive response
        cleaned_text, actions_taken = await self._extract_and_execute_actions(
            agent, response_text
        )
        if cleaned_text != response_text:
            response_text = cleaned_text

        # BF-215: Guard against empty text after tag stripping (BF-203/BF-174)
        if not response_text.strip():
            logger.debug(
                "BF-215: Suppressed empty post from %s after action extraction",
                agent.agent_type,
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return

        # AD-573: Record proactive observation to working memory
```
REPLACE:
```
        # AD-573: Record proactive observation to working memory
```

**P2-6.** `src/probos/proactive.py`
SEARCH:
```
        # BF-032: Skip if too similar to agent's recent posts
```
REPLACE:
```
        _withdrawn = "[NO_RESPONSE]" in response_text  # BF-934: true only when the output carries a valid block (the gate above); see below

        # BF-172: Suppress raw JSON intent payloads leaking from LLM mode-confusion
        stripped = response_text.lstrip()
        if stripped.startswith("{") and '"intents"' in stripped[:200]:
            logger.warning(
                "BF-172: Suppressed raw intent JSON from %s (%d chars)",
                agent.agent_type, len(response_text),
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return

        # AD-437: Extract and process structured actions from proactive response. BF-934: before the similarity (BF-032) and novelty
        # (AD-493) gates, which judge the observation that is left, as the Ward Room pipeline's order already does: a block attached
        # to a repeated observation is carried out, and the repeat is still not posted.
        cleaned_text, actions_taken = await self._extract_and_execute_actions(
            agent, response_text
        )
        if cleaned_text != response_text:
            response_text = cleaned_text
        if _withdrawn:
            response_text = ""  # BF-934: the withdrawal covers the observation, so only the blocks were carried out; nothing is left to post

        # BF-215: Guard against empty text after tag stripping (BF-203/BF-174)
        if not response_text.strip():
            logger.debug(
                "BF-215: Suppressed empty post from %s after action extraction",
                agent.agent_type,
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return

        # BF-032: Skip if too similar to agent's recent posts
```

**P2-7.** `src/probos/proactive.py`
SEARCH:
```
        proposal_pattern = r'\[PROPOSAL\]\s*\n(.*?)\n\s*\[/PROPOSAL\]'
        proposal_match = re.search(proposal_pattern, text, re.DOTALL)
        if proposal_match:
            proposal_block = proposal_match.group(1)

            # Parse structured fields
            title = ""
            rationale = ""
            affected: list[str] = []
            priority = "medium"

            in_rationale = False
            rationale_lines: list[str] = []
            for line in proposal_block.split('\n'):
                stripped = line.strip()
                if stripped.lower().startswith("title:"):
                    title = stripped[6:].strip()
                    in_rationale = False
                elif stripped.lower().startswith("affected systems:"):
                    raw = stripped[17:].strip()
                    affected = [s.strip() for s in raw.split(",") if s.strip()]
                    in_rationale = False
                elif stripped.lower().startswith("priority:"):
                    p = stripped[9:].strip().lower()
                    if p in ("low", "medium", "high"):
                        priority = p
                    in_rationale = False
                elif stripped.lower().startswith("rationale:"):
                    rest = stripped[10:].strip()
                    if rest:
                        rationale_lines.append(rest)
                    in_rationale = True
                elif in_rationale:
                    rationale_lines.append(stripped)
            rationale = "\n".join(rationale_lines).strip()

            if title and rationale and rt.ward_room_router:
                try:
                    from probos.types import IntentMessage
                    intent = IntentMessage(
                        intent="propose_improvement",
                        params={
                            "title": title,
                            "rationale": rationale,
                            "affected_systems": affected,
                            "priority_suggestion": priority,
                        },
                        context=f"Proactive proposal from {getattr(agent, 'agent_type', 'unknown')}",
                    )
                    await rt.ward_room_router.handle_propose_improvement(intent, agent)
                    actions_executed.append({
                        "type": "proposal",
                        "title": title,
                        "priority": priority,
                    })
                    logger.debug(
                        "AD-412: Proposal extracted from %s: %s",
                        getattr(agent, 'agent_type', 'unknown'), title,
                    )
                except Exception:
                    logger.debug(
                        "AD-412: Failed to post proposal from %s",
                        getattr(agent, 'agent_type', 'unknown'), exc_info=True,
                    )
```
REPLACE:
```
        proposal_pattern = PROPOSAL_PATTERN
        proposal = parse_proposal_block(text)  # BF-934: the one reading of a block, here and in the [NO_RESPONSE] gate
        _proposer = getattr(agent, 'callsign', '') or getattr(agent, 'agent_type', 'unknown')
        if proposal.extra_blocks:
            logger.warning(
                "BF-934: %d more [PROPOSAL] block(s) from %s are ignored: one proposal is filed per output",
                proposal.extra_blocks, _proposer,
            )
        if proposal.found:
            reason = proposal.problem
            if not reason:
                if not rt.ward_room_router:
                    reason = "no_router"
                else:
                    try:
                        from probos.types import IntentMessage
                        intent = IntentMessage(
                            intent="propose_improvement",
                            params={
                                "title": proposal.title,
                                "rationale": proposal.rationale,
                                "affected_systems": list(proposal.affected),
                                "priority_suggestion": proposal.priority,
                            },
                            context=f"Proactive proposal from {getattr(agent, 'agent_type', 'unknown')}",
                        )
                        posted = await rt.ward_room_router.handle_propose_improvement(intent, agent)
                        if isinstance(posted, dict) and posted.get("success") is False:
                            reason = f"router_refused: {posted.get('error', '')}"
                        else:
                            actions_executed.append({
                                "type": "proposal",
                                "title": proposal.title,
                                "priority": proposal.priority,
                            })
                            logger.debug(
                                "AD-412: Proposal extracted from %s: %s",
                                getattr(agent, 'agent_type', 'unknown'), proposal.title,
                            )
                    except Exception as exc:
                        reason = f"post_failed: {type(exc).__name__}"
                        logger.debug("AD-412: Failed to post proposal from %s", _proposer, exc_info=True)
            if reason:  # BF-934: a decision that cannot be filed is said, with the agent and why, and recorded as an entry
                logger.warning("BF-934: proposal from %s (%s) not posted: %s", _proposer, getattr(agent, 'agent_type', 'unknown'), reason)
                actions_executed.append({"type": "proposal_suppressed", "reason": reason})
```

**P2-8.** `src/probos/proactive.py`
SEARCH:
```
            logger.debug(
                "AD-412: Malformed [PROPOSAL] block from %s
```
REPLACE:
```
            logger.warning(
                "BF-934: Malformed [PROPOSAL] block from %s
```

**P2-9.** `src/probos/proactive.py`
SEARCH:
```
                getattr(agent, 'agent_type', 'unknown'),
            )

        # Strip proposal block from text regardless of submission success.
```
REPLACE:
```
                _proposer,
            )
            actions_executed.append({"type": "proposal_suppressed", "reason": "malformed_block"})

        # Strip proposal block from text regardless of submission success.
```

**P2-10.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
# BF-922 (#1639): set on the observation while a single call answers for a chain
```
REPLACE:
```
# AD-643b / BF-934: the marker an output carries for each action the proactive loop executes, in the order they are reported.
_ACTION_MARKERS: dict[str, re.Pattern[str]] = {
    "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
    "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
    "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
    "dm": re.compile(r'\[DM\s', re.IGNORECASE),
    "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
    "note": re.compile(r'\[NOTE\s', re.IGNORECASE),  # AD-573c
}


def _action_markers_in(text: str) -> list[str]:
    """AD-643b / BF-934: the action tags whose marker *text* carries, in ``_ACTION_MARKERS`` order."""
    return [tag for tag, pattern in _ACTION_MARKERS.items() if pattern.search(text or "")]


# BF-922 (#1639): set on the observation while a single call answers for a chain
```

**P2-11.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
        declared = set(intended_actions)
        undeclared = []

        markers = {
            "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
            "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
            "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
            "dm": re.compile(r'\[DM\s', re.IGNORECASE),
            "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
            "note": re.compile(r'\[NOTE\s', re.IGNORECASE),  # AD-573c
        }

        for action_tag, pattern in markers.items():
            if action_tag not in declared and pattern.search(compose_output):
                undeclared.append(action_tag)

        return undeclared
```
REPLACE:
```
        declared = set(intended_actions)
        return [tag for tag in _action_markers_in(compose_output) if tag not in declared]
```

**P2-12.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
                    if new_output:
                        logger.info(
                            "AD-643b: Re-reflect updated output for %s",
                            self.agent_type,
                        )
```
REPLACE:
```
                    if new_output:
                        # BF-934: a rewrite may refine an approved output, never remove an action it carries (silence included).
                        lost = [
                            tag for tag in _action_markers_in(original_result.get("llm_output", ""))
                            if tag not in _action_markers_in(new_output)
                        ]
                        if lost:
                            logger.warning(
                                "BF-934: AD-643b re-reflect for %s %s would have dropped %s from an approved output; the approved output is kept",
                                self.agent_type, getattr(self, "callsign", "") or self.agent_type, lost,
                            )
                            return original_result
                        logger.info(
                            "AD-643b: Re-reflect updated output for %s",
                            self.agent_type,
                        )
```

**N2-1.** `tests/test_bf934_s2_secondary_gates.py`
SEARCH:
```
class TestNoGateDiscardsAnActionTheOutputCarries:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S2 M2 builds it")

    @pytest.mark.parametrize("blocks", [PROPOSAL, NOTEBOOK, f"{PROPOSAL}\n{NOTEBOOK}"])
```
REPLACE:
```
class TestNoGateDiscardsAnActionTheOutputCarries:
    @pytest.mark.parametrize("blocks", [PROPOSAL, NOTEBOOK, f"{PROPOSAL}\n{NOTEBOOK}"])
```

**N2-2.** `tests/test_bf934_s2_secondary_gates.py`
SEARCH:
```
class TestOneReadingOfAProposalBlock:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S2 M2 builds it")

    @pytest.mark.parametrize("text, problem", [
```
REPLACE:
```
class TestOneReadingOfAProposalBlock:
    @pytest.mark.parametrize("text, problem", [
```

#### S2 / M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-934 S2 (DATE), #1673 -- no gate of the proactive think discards an action the output carries, and a proposal that is not filed says why (slice 2 of 3).**
- **Base.** `[NO_RESPONSE]` anywhere in an output discarded it before any block was read; BF-032's and AD-493's gates ran before the extraction, so a proposal or a notebook entry beside a repeated observation was lost with it; AD-643b's re-reflect replaced an approved output with whatever REFLECT returned, silence and a text without the block included; a proposal that was malformed, lacked a Title or a Rationale, had no router or was refused by it (`{"success": False}` was ignored and the proposal counted as filed) left a DEBUG line or none.
- **Fix.** New `cognitive/proposal_block.py` (`parse_proposal_block`: the one reading of a block, for the extractor and the gate). In `proactive.py` a valid proposal, or a notebook entry with a body, beside `[NO_RESPONSE]` is carried out and the withdrawn observation is not posted (`carries_actionable_block`); the extraction runs before the similarity and novelty gates (the Ward Room pipeline's order); a proposal that is not filed logs a WARNING with the agent and the reason and appends `proposal_suppressed`; the router's refusal is no longer counted as filed. In `cognitive_agent.py` a re-reflect that would lose an action marker the approved output carried keeps the approved output (`_ACTION_MARKERS`, shared with AD-643b's detection). Contract `prompts/bf-934-dropped-crew-proposals.md`. Refs #1673.

```

**P3-2.** `DECISIONS.md`. Append after S1's entry. Its last bullet occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1, L7, L11, L14 and L15 of the contract. *Reversal.* Revert the BF-934 slice 1 commits.
```
REPLACE:
```
- *Residual.* L1, L7, L11, L14 and L15 of the contract. *Reversal.* Revert the BF-934 slice 1 commits.

### BF-934 -- No gate of the proactive think discards an action the output carries, and a proposal that is not filed says why (slice 2 of 3; DATE, #1673)

- *Scope.* `cognitive/proposal_block.py` (new), `proactive.py` (the `[NO_RESPONSE]` gate, the order of the extraction, the proposal block, `carries_actionable_block`), `cognitive_agent.py` (`_ACTION_MARKERS`, the re-reflect guard), tests. Contract `prompts/bf-934-dropped-crew-proposals.md`. Slice 2 of #1673.
- *G1 (the order).* The extraction runs before BF-032 and AD-493, after BF-172: any block beside a repeated observation is carried out and the repeat is still not posted, as the Ward Room pipeline's order already is. Rejected: exempting proposals only; leaving it.
- *G2 (`[NO_RESPONSE]`).* An output that carries a proposal the extractor can file, or a notebook entry with a body, is read for blocks and its observation stays withdrawn. Rejected: stripping the marker and posting the rest; every block type (replies, DMs and endorsements may follow a "nothing to add" answer by design).
- *G3 (the re-reflect).* May refine, never remove: the approved output is kept when the rewrite lacks an action marker it carried, silence included. Rejected: annotate only (it changes AD-643b's documented contract for every rewrite).
- *G4 (visibility).* A WARNING with the agent and the reason, and a `proposal_suppressed` entry, for every way a proposal is not filed; the router's refusal is read.
- *Residual.* L1, L2, L4, L5, L9 and L10 of the contract. *Reversal.* Revert the BF-934 slice 2 commits (slice 3 first, if built).
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.


### Slice S3: every intended action is carried out or recorded as dropped

#### S3 / M1

**N1-1.** New file `tests/test_bf934_s3_intended_actions_ledger.py` (labels restart in each slice; S3's blocks apply after S2's):

```python
"""BF-934 (#1673) S3: every action a decision intended is carried out or recorded as dropped, with a reason, per agent and action.

Real: the think cycle, the extraction (the Ward Room, its router, Ship's Records, the DM path), the cognitive agent's lifecycle and a real EventLog on tmp_path, which is
the record the crew reconciles against Improvement Proposals. Doubles (tests/bf934_world.py): the model, the triage's handlers, and a thinker whose ``handle_intent``
answers the text a model wrote with the ``intended_actions`` metadata the lifecycle would attach. The classes hold the cases the unfixed tree fails; the functions before
them pass on both. No BF-934 name is imported at module level.
"""

from __future__ import annotations

import importlib
import logging
import re
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.cognitive_agent import _build_result_metadata
from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt, _build_situation_review_prompt
from probos.types import IntentResult
from tests.bf934_world import NothingIsNovel, crew, obeys_decision, think, thinker, threads, world

PROPOSAL = "[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]"
NOTEBOOK = "[NOTEBOOK roster-cache]\nThe roster is read 40 times per cycle.\n[/NOTEBOOK]"
REPEATED = "The roster is read forty times per cycle and never changes anywhere."
ACTION_TAGS = ["ward_room_post", "ward_room_reply", "endorse", "dm", "notebook", "proposal"]  # the tags an output carries out
OTHER_TAGS = ["silent", "speak_freely", "leadership_review", "oracle_query", "ward_room_lookup"]  # carried out by something else (see the registry)


def _built(name: str):
    """The module M2 builds. Until then this fails at its own assert, as the xfail marker requires (an ImportError would not)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        assert False, f"{name} is built by M2"


async def _rows(w, event: str) -> list[dict]:
    """The EventLog rows of the intended_actions category, oldest first."""
    return list(reversed(await w.events.query_structured(category="intended_actions", event=event, limit=200)))


def _said(caplog, message: str) -> list[str]:
    """The levels at which the accounting module logged a line containing *message* (other loggers' lines are not counted)."""
    return [r.levelname for r in caplog.records if r.name == "probos.cognitive.action_accounting" and message in r.getMessage()]


async def _target(w, tag: str) -> str:
    """The reply, endorsement or DM block for *tag*, aimed at a thread and post Worf made (the others need none), or plain text for ``ward_room_post``."""
    science = await w.ws.get_channel_by_department("science")
    thread = await w.ws.create_thread(science.id, w.ids["security_officer"], "Coolant audit", "Loop B reads 41 C.", author_callsign="Worf")
    post = await w.ws.create_post(thread.id, w.ids["security_officer"], "Confirmed at 0300.", author_callsign="Worf")
    return {
        "ward_room_post": "The coolant audit needs a second reading.",
        "ward_room_reply": f"[REPLY {thread.id}]\nSecond reading agrees.\n[/REPLY]",
        "endorse": f"[ENDORSE {post.id} UP]",
        "dm": "[DM @Worf]\nThe coolant audit needs a second reading.\n[/DM]",
        "notebook": NOTEBOOK,
        "proposal": PROPOSAL,
    }[tag]


async def _carried_out(w, tag: str) -> bool:
    """Whether the world holds what carrying *tag* out leaves, read from the Ward Room and Ship's Records and not from the loop."""
    titles = await threads(w)
    if tag == "ward_room_post":
        return any(t.startswith("[Observation]") for t in titles)
    if tag == "dm":
        return any(t.startswith("[DM to @Worf]") for t in titles)
    if tag == "notebook":
        return w.notebook("Kira", "roster-cache").is_file()
    if tag == "proposal":
        return "[Proposal] Cache the roster" in titles
    science = await w.ws.get_channel_by_department("science")
    (thread,) = [th for th in await w.ws.list_threads(science.id, limit=50) if th.title == "Coolant audit"]
    posts = (await w.ws.get_thread(thread.id))["posts"]
    if tag == "ward_room_reply":
        return any(p.get("author_id") == w.ids["science_officer"] for p in posts)
    return any(p.get("net_score", 0) > 0 for p in posts)  # endorse


@pytest.mark.parametrize("tag", ACTION_TAGS)
async def test_control_each_action_a_think_is_asked_to_carry_out_is_carried_out_by_the_loop(tmp_path, tag):
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, await _target(w, tag)))
        assert await _carried_out(w, tag)


@pytest.mark.parametrize("tag", ACTION_TAGS)
async def test_an_action_the_output_carries_leaves_no_drop(tmp_path, tag):
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, await _target(w, tag), {"intended_actions": [tag]}))
        assert await _carried_out(w, tag) and await _rows(w, "dropped") == []


@pytest.mark.parametrize("tag", OTHER_TAGS)
async def test_a_tag_something_else_carries_out_never_has_a_drop(tmp_path, tag):
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, "[NO_RESPONSE]", {"intended_actions": [tag]}))
        assert await _rows(w, "dropped") == []


async def test_a_decision_that_names_no_action_leaves_no_record(tmp_path):
    async with world(tmp_path, event_log=True) as w:
        agent, _ = await crew(w, ["silent"], obeys_decision)
        await think(w, agent)
        assert await _rows(w, "declared") == [] and await _rows(w, "dropped") == []


class TestEveryIntendedActionIsCarriedOutOrDropped:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S3 M2 builds it")

    @pytest.mark.parametrize("tag", [t for t in ACTION_TAGS if t != "ward_room_post"])
    async def test_an_action_the_output_does_not_carry_is_dropped_with_a_reason_and_said(self, tmp_path, caplog, tag):
        async with world(tmp_path, event_log=True) as w:
            with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, "Only an observation.", {"intended_actions": [tag]}))
            rows = await _rows(w, "dropped")
            assert len(rows) == 1
            row = rows[0]
            assert row["agent_type"] == "science_officer" and row["correlation_id"] and row["data"]["intent_id"] == row["correlation_id"]
            assert (row["data"]["action"], row["data"]["reason"]) == (tag, "no_block_executed")
            assert _said(caplog, f"intended {tag} and nothing carried it out: no_block_executed") == ["WARNING"]

    async def test_an_observation_the_gates_withhold_is_dropped_too_but_only_noted(self, tmp_path, caplog):
        async with world(tmp_path, event_log=True) as w:
            with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, "[NO_RESPONSE]", {"intended_actions": ["ward_room_post"]}))
            rows = await _rows(w, "dropped")
            assert len(rows) == 1 and (rows[0]["data"]["action"], rows[0]["data"]["reason"]) == ("ward_room_post", "no_response")
            assert _said(caplog, "intended ward_room_post and nothing carried it out: no_response") == ["INFO"]

    async def test_a_notebook_entry_the_writer_declines_as_a_repeat_is_only_noted(self, tmp_path, caplog):
        async with world(tmp_path, event_log=True) as w:
            await think(w, thinker(w, NOTEBOOK, {"intended_actions": ["notebook"]}))
            assert await _rows(w, "dropped") == []
            with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, NOTEBOOK, {"intended_actions": ["notebook"]}))  # the same entry again: AD-550 declines it, by design
            assert _said(caplog, "intended notebook and nothing carried it out: content unchanged from recent entry") == ["INFO"]
            assert [r["data"]["by_design"] for r in await _rows(w, "dropped")] == [True]

    async def test_an_output_that_fails_to_think_drops_every_action_the_decision_named(self, tmp_path):
        async with world(tmp_path, event_log=True) as w:
            agent = thinker(w, "")

            async def failed(intent):
                return IntentResult(intent_id=intent.id, agent_id=agent.id, success=False, error="llm down", metadata={"intended_actions": ["proposal", "notebook"]})

            agent.handle_intent = failed
            await think(w, agent)
            assert [(r["data"]["action"], r["data"]["reason"]) for r in await _rows(w, "dropped")] == [("proposal", "think_failed"), ("notebook", "think_failed")]

    async def test_a_row_that_cannot_be_written_never_blocks_the_think(self, tmp_path, caplog, monkeypatch):
        async with world(tmp_path, event_log=True) as w:
            monkeypatch.setattr(w.events, "log", AsyncMock(side_effect=OSError("disk full")))
            with caplog.at_level(logging.WARNING, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, "[NO_RESPONSE]", {"intended_actions": ["proposal"]}))
            assert "the dropped row for Kira (science_officer) was not recorded" in caplog.text

    @pytest.mark.parametrize("reply, how, intended, action, reason", [
        ('{"intents": [{"intent": "ward_room_post"}]}', None, ["proposal"], "proposal", "raw_intent_json"),
        (PROPOSAL, None, ["ward_room_post", "proposal"], "ward_room_post", "empty_after_extraction"),
        (f"[NO_RESPONSE]\n{PROPOSAL}", None, ["ward_room_post", "proposal"], "ward_room_post", "no_response"),
        (REPEATED, "similar", ["ward_room_post"], "ward_room_post", "similar_to_recent_post"),
        (REPEATED, "novelty", ["ward_room_post"], "ward_room_post", "not_novel"),
    ])
    async def test_each_exit_of_the_think_names_its_reason(self, tmp_path, monkeypatch, reply, how, intended, action, reason):
        async with world(tmp_path, event_log=True) as w:
            if how == "similar":
                monkeypatch.setattr(w.loop, "_is_similar_to_recent_posts", AsyncMock(return_value=True))
            if how == "novelty":
                w.loop.set_novelty_gate(NothingIsNovel())
            await think(w, thinker(w, reply, {"intended_actions": intended}))
            assert [(r["data"]["action"], r["data"]["reason"]) for r in await _rows(w, "dropped")] == [(action, reason)]

    async def test_the_observation_post_says_whether_a_thread_was_created(self, tmp_path, caplog, monkeypatch):
        async with world(tmp_path) as w:
            agent = thinker(w, "")
            assert await w.loop._post_to_ward_room(agent, "Observation one.") is True
            monkeypatch.setattr(w.ws, "list_channels", AsyncMock(return_value=[]))
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                assert await w.loop._post_to_ward_room(agent, "Observation two.") is False
            assert "no channel to post the observation of science_officer" in caplog.text

    async def test_an_observation_no_channel_can_take_is_dropped_as_not_posted(self, tmp_path, monkeypatch):
        async with world(tmp_path, event_log=True) as w:
            monkeypatch.setattr(w.ws, "list_channels", AsyncMock(return_value=[]))
            await think(w, thinker(w, "The coolant audit needs a second reading.", {"intended_actions": ["ward_room_post"]}))
            assert [(r["data"]["action"], r["data"]["reason"]) for r in await _rows(w, "dropped")] == [("ward_room_post", "not_posted")]


class TestTheDecisionRecordReconcilesAgainstWhatWasPosted:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S3 M2 builds it")

    async def test_decided_equals_posted_plus_dropped_per_agent_and_action(self, tmp_path):
        """The crew's reconciliation, from its three named sources: the decision record (events.db), Improvement Proposals (Ward Room) and the drop rows (events.db)."""
        async with world(tmp_path, event_log=True) as w:
            for answer in (obeys_decision, lambda request: "[NO_RESPONSE]", obeys_decision):
                agent, _ = await crew(w, ["proposal", "notebook"], answer)
                await think(w, agent)
            decided = [r for r in await _rows(w, "declared") if "proposal" in r["data"]["intended"]]
            posted = await threads(w, "Improvement Proposals")
            dropped = [r for r in await _rows(w, "dropped") if r["data"]["action"] == "proposal"]
            assert len(decided) == 3 and len(posted) == 2 and len(dropped) == 1
            assert len(decided) == len(posted) + len(dropped)
            assert {r["correlation_id"] for r in dropped} <= {r["correlation_id"] for r in decided}  # a drop closes a decision made by the same think
            assert {r["agent_id"] for r in decided} == {w.ids["science_officer"]} and decided[0]["data"] == {
                "intended": ["proposal", "notebook"], "path": "single_call", "intent": "proactive_think",
                "intent_id": decided[0]["correlation_id"], "callsign": "Kira"}
            notebook = [r["data"]["reason"] for r in await _rows(w, "dropped") if r["data"]["action"] == "notebook"]
            assert sorted(notebook) == ["content unchanged from recent entry", "no_response"]  # a dedup is by design, and still counted
            assert [r["data"]["reason"] for r in await _rows(w, "dropped") if r["data"].get("by_design")] == ["content unchanged from recent entry"]

    async def test_a_decision_made_for_another_intent_is_not_recorded(self, tmp_path):
        async with world(tmp_path, event_log=True) as w:
            await _built("probos.cognitive.action_accounting").record_declared(
                w.rt, agent_id="agent-1", agent_type="science_officer", callsign="Kira", intent="ward_room_notification", intent_id="intent-1",
                intended=["ward_room_reply"], path="chain")
            assert await _rows(w, "declared") == []


class TestTheRegistryAndTheMetadata:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S3 M2 builds it")

    def test_the_registry_holds_exactly_the_tags_the_analyze_prompts_offer(self):
        accounting = _built("probos.cognitive.action_accounting")
        offered: set[str] = set()
        for build in (_build_situation_review_prompt, _build_thread_analysis_prompt):
            _, user = build({"context": "x", "params": {}, "_agent_type": "science_officer"}, [], "Kira", "science")
            offered |= set(re.findall(r"[a-z_]+", re.search(r"JSON array from:\s*([a-z_,\s]+)\.", user).group(1)))
        assert offered == set(accounting.ACTION_TAGS) and set(ACTION_TAGS) | set(OTHER_TAGS) == offered
        assert {t for t, spec in accounting.ACTION_TAGS.items() if spec.evidence} == set(ACTION_TAGS)
        assert all(accounting.ACTION_TAGS[t].how for t in OTHER_TAGS)

    @pytest.mark.parametrize("executed, reason, expected", [
        ([], "no_response", [("proposal", "no_response"), ("ward_room_post", "no_response")]),
        ([], "empty_after_extraction", [("proposal", "no_block_executed"), ("ward_room_post", "empty_after_extraction")]),
        ([{"type": "proposal"}], "not_posted", [("ward_room_post", "not_posted")]),
        ([{"type": "proposal"}, {"type": "ward_room_post"}], "not_posted", []),
        ([{"type": "proposal_suppressed", "reason": "missing_title"}, {"type": "ward_room_post"}], "not_posted", [("proposal", "missing_title")]),
    ])
    def test_what_nothing_carried_out_and_why(self, executed, reason, expected):
        drops = _built("probos.cognitive.action_accounting").unaccounted(["Proposal", "ward_room_post", "proposal", "silent", "no_such_tag"], executed, reason)
        assert sorted((d["action"], d["reason"]) for d in drops) == sorted(expected) and {d["type"] for d in drops} <= {"action_dropped"}

    def test_the_lifecycle_carries_the_decision_to_the_caller_bounded(self):
        assert _build_result_metadata({}, {}, {"_intended_actions": ["proposal", "notebook"]}) == {"intended_actions": ["proposal", "notebook"]}
        assert len(_build_result_metadata({}, {}, {"_intended_actions": ["x" * 90] * 40})["intended_actions"]) == 16
        assert _build_result_metadata({}, {}, {"_intended_actions": ["x" * 90]})["intended_actions"] == ["x" * 40]
        for none in ({}, {"_intended_actions": []}, {"_intended_actions": "proposal"}, {"_intended_actions": None}):
            assert "intended_actions" not in _build_result_metadata({}, {}, none)
```

#### S3 / M2

**P2-1.** New file `src/probos/cognitive/action_accounting.py`:

```python
"""BF-934 (#1673): the inverse of AD-643b -- the actions a decision intended that nothing carried out.

AD-643b names an action an output took that its triage had not declared. This module names the other half: an action the triage declared (``intended_actions``)
that nothing carried out, so that a decision cannot be lost without a record. A proactive think's triage writes one ``declared`` row where the decision is made
(``record_declared``); the loop that executes the output writes one ``dropped`` row for each intended action nothing carried out, with a reason
(``settle_intended_actions``), and says it in the log. Both are EventLog rows (events.db), so the crew counts them per agent and action and reconciles them
against what Improvement Proposals and Ship's Records hold: ``declared`` = posted + ``dropped``, and a gap is the alarm.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

#: The EventLog rows this module writes. Best effort: Improvement Proposals and Ship's Records are authoritative for what was posted, and a
#: row that could not be written is logged at WARNING (the write never blocks a think).
CATEGORY = "intended_actions"
DECLARED_EVENT = "declared"
DROPPED_EVENT = "dropped"


@dataclass(frozen=True)
class ActionTag:
    """How the output of a proactive think carries out one tag the ANALYZE prompts offer."""

    evidence: frozenset[str] = frozenset()  # the ``type`` of the entry that records it carried out; empty: not carried out as a block or a post
    suppressed: str = ""  # the ``type`` of the entry that records a deliberate suppression, with its own ``reason``
    how: str = ""  # for a tag with no evidence: what carries it out instead


#: Every tag of analyze.py's two ``intended_actions`` vocabularies; tests/test_bf934_s3_intended_actions_ledger.py pins the set equal to the prompts'.
ACTION_TAGS: Mapping[str, ActionTag] = MappingProxyType({
    "ward_room_post": ActionTag(frozenset({"ward_room_post"})),
    "ward_room_reply": ActionTag(frozenset({"reply"})),
    "endorse": ActionTag(frozenset({"endorse"})),
    "dm": ActionTag(frozenset({"dm"})),
    "notebook": ActionTag(frozenset({"notebook_write"}), suppressed="notebook_suppressed"),
    "proposal": ActionTag(frozenset({"proposal"}), suppressed="proposal_suppressed"),
    "silent": ActionTag(how="nothing to carry out"),
    "speak_freely": ActionTag(how="a register shift COMPOSE applies (AD-653)"),
    "leadership_review": ActionTag(how="a quality skill the triage loads (AD-643a)"),
    "oracle_query": ActionTag(how="a lookup run between triage and COMPOSE (AD-696)"),
    "ward_room_lookup": ActionTag(how="a lookup run between triage and COMPOSE (AD-1347 S4)"),
})

#: The reasons of an exit taken before the output was read for blocks: they apply to every tag.
PRE_EXTRACTION = frozenset({"think_failed", "no_output", "no_response", "raw_intent_json"})


def _normalised(intended: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(tag).strip().lower() for tag in intended))


def unaccounted(intended: Iterable[object], executed: Sequence[Mapping[str, Any]], reason: str) -> list[dict[str, Any]]:
    """The drop entry of each intended action that nothing in *executed* carried out.

    *executed* is what ``ProactiveCognitiveLoop`` recorded (the extractor's entries, and ``{"type": "ward_room_post"}`` once the observation was posted);
    *reason* is why the think ended where it did. A tag with no evidence (``silent``, ``speak_freely``, ...) is never dropped. A tag whose extractor recorded a
    suppression with its own reason keeps that reason; any other block tag that nothing carried out after the output was read is ``no_block_executed``.
    """
    done = {str(entry.get("type", "")) for entry in executed if isinstance(entry, Mapping)}
    drops: list[dict[str, Any]] = []
    for tag in _normalised(intended):
        spec = ACTION_TAGS.get(tag)
        if spec is None or not spec.evidence or done & spec.evidence:
            continue
        drop: dict[str, Any] = {
            "type": "action_dropped", "action": tag,
            "reason": reason if tag == "ward_room_post" or reason in PRE_EXTRACTION else "no_block_executed",
        }
        for entry in executed:
            if spec.suppressed and isinstance(entry, Mapping) and entry.get("type") == spec.suppressed:
                drop["reason"] = str(entry.get("reason") or drop["reason"])
                if spec.suppressed == "notebook_suppressed":
                    drop["by_design"] = True  # AD-550's dedup and AD-552's repetition gate: counted, and only noted
                break
        drops.append(drop)
    return drops


async def record_declared(
    runtime: Any, *, agent_id: str, agent_type: str, callsign: str, intent: str, intent_id: str,
    intended: Sequence[object], path: str,
) -> None:
    """The decision record: one ``declared`` row when a proactive think's triage intends an action that a block or a post carries out."""
    tags = _normalised(intended)
    log = getattr(runtime, "event_log", None)
    if intent != "proactive_think" or log is None or not any(ACTION_TAGS.get(tag, ActionTag()).evidence for tag in tags):
        return
    try:
        await log.log(
            category=CATEGORY, event=DECLARED_EVENT, agent_id=agent_id, agent_type=agent_type,
            detail=f"{callsign} intended {', '.join(tags)} ({path})", correlation_id=intent_id or None,
            data={"intended": tags, "path": path, "intent": intent, "intent_id": intent_id, "callsign": callsign},
        )
    except Exception:
        logger.warning("BF-934: the declared row for %s (%s) was not recorded", callsign, agent_type, exc_info=True)


async def settle_intended_actions(
    runtime: Any, agent: Any, intent_id: str, metadata: object, executed: Sequence[Mapping[str, Any]], reason: str,
) -> list[dict[str, Any]]:
    """Say, and record, each action the think's triage intended that nothing carried out; return the drop entries.

    *metadata* is the ``IntentResult.metadata`` of the think: it holds ``intended_actions`` only when a triage ran for it, and a think without one has nothing to
    account for. A drop of ``ward_room_post`` (the usual quality gates) or a by-design notebook suppression is logged at INFO; any other drop is a lost decision and
    is logged at WARNING. Nothing here raises.
    """
    intended = metadata.get("intended_actions") if isinstance(metadata, dict) else None
    if not isinstance(intended, list):
        return []
    drops = unaccounted(intended, executed, reason)
    agent_type = getattr(agent, "agent_type", "")
    callsign = getattr(agent, "callsign", "") or agent_type
    log = getattr(runtime, "event_log", None)
    for drop in drops:
        level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") else logging.WARNING
        logger.log(level, "BF-934: %s (%s) intended %s and nothing carried it out: %s", callsign, agent_type, drop["action"], drop["reason"])
        if log is None:
            continue
        try:
            await log.log(
                category=CATEGORY, event=DROPPED_EVENT, agent_id=getattr(agent, "id", None), agent_type=agent_type,
                detail=f"{callsign} intended {drop['action']}: {drop['reason']}", correlation_id=intent_id or None,
                data={**drop, "intent": "proactive_think", "intent_id": intent_id, "callsign": callsign},
            )
        except Exception:
            logger.warning("BF-934: the dropped row for %s (%s) was not recorded", callsign, agent_type, exc_info=True)
    return drops
```

**P2-2.** `src/probos/proactive.py`
SEARCH:
```
from probos.cognitive.proposal_block import PROPOSAL_PATTERN, parse_proposal_block  # BF-934
```
REPLACE:
```
from probos.cognitive.action_accounting import settle_intended_actions  # BF-934
from probos.cognitive.proposal_block import PROPOSAL_PATTERN, parse_proposal_block  # BF-934
```

**P2-3.** `src/probos/proactive.py`
SEARCH:
```
                    agent.agent_type, error_detail, self._llm_failure_count,
                )
            return

        response_text = str(result.result).strip()
```
REPLACE:
```
                    agent.agent_type, error_detail, self._llm_failure_count,
                )
            await settle_intended_actions(
                self._runtime, agent, intent.id, getattr(result, "metadata", None), [],
                "think_failed" if not (result and result.success) else "no_output",
            )
            return

        response_text = str(result.result).strip()
```

**P2-4.** `src/probos/proactive.py`
SEARCH:
```
            self._circuit_breaker.record_event(agent.id, "no_response", "")
            return
```
REPLACE:
```
            self._circuit_breaker.record_event(agent.id, "no_response", "")
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), [], "no_response")
            return
```

**P2-5.** `src/probos/proactive.py`
SEARCH:
```
                "BF-172: Suppressed raw intent JSON from %s (%d chars)",
                agent.agent_type, len(response_text),
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return
```
REPLACE:
```
                "BF-172: Suppressed raw intent JSON from %s (%d chars)",
                agent.agent_type, len(response_text),
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), [], "raw_intent_json")
            return
```

**P2-6.** `src/probos/proactive.py`
SEARCH:
```
                "BF-215: Suppressed empty post from %s after action extraction",
                agent.agent_type,
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return
```
REPLACE:
```
                "BF-215: Suppressed empty post from %s after action extraction",
                agent.agent_type,
            )
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "no_response" if _withdrawn else "empty_after_extraction")
            return
```

**P2-7.** `src/probos/proactive.py`
SEARCH:
```
                "BF-032: Suppressed similar proactive post from %s",
                agent.agent_type,
            )
            # Still record duty execution if applicable
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return
```
REPLACE:
```
                "BF-032: Suppressed similar proactive post from %s",
                agent.agent_type,
            )
            # Still record duty execution if applicable
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "similar_to_recent_post")
            return
```

**P2-8.** `src/probos/proactive.py`
SEARCH:
```
                    if duty and self._duty_tracker:
                        self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
                    return
            except Exception:
                logger.debug("AD-493: Novelty gate check failed, allowing post", exc_info=True)
```
REPLACE:
```
                    if duty and self._duty_tracker:
                        self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
                    await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "not_novel")
                    return
            except Exception:
                logger.debug("AD-493: Novelty gate check failed, allowing post", exc_info=True)
```

**P2-9.** `src/probos/proactive.py`
SEARCH:
```
        await self._post_to_ward_room(agent, response_text)
        self._last_proactive[agent.id] = time.monotonic()
```
REPLACE:
```
        if await self._post_to_ward_room(agent, response_text):  # BF-934: True once a thread was created
            actions_taken.append({"type": "ward_room_post"})
        await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "not_posted")
        self._last_proactive[agent.id] = time.monotonic()
```

**P2-10.** `src/probos/proactive.py`
SEARCH:
```
    async def _post_to_ward_room(self, agent: Any, text: str) -> None:
        """Create a Ward Room thread with the agent's proactive observation."""
```
REPLACE:
```
    async def _post_to_ward_room(self, agent: Any, text: str) -> bool:
        """Create a Ward Room thread with the agent's proactive observation. BF-934: True when a thread was created."""
```

**P2-11.** `src/probos/proactive.py`
SEARCH:
```
            logger.debug("No target channel found for proactive post from %s", agent.agent_type)
            return
```
REPLACE:
```
            logger.warning("BF-934: no channel to post the observation of %s: the observation is not posted", agent.agent_type)
            return False
```

**P2-12.** `src/probos/proactive.py`
SEARCH:
```
        if not text:  # BF-874: nothing but DM blocks
            return
```
REPLACE:
```
        if not text:  # BF-874: nothing but DM blocks
            return False
```

**P2-13.** `src/probos/proactive.py`
SEARCH:
```
                logger.debug("AD-493: Fingerprint recording failed", exc_info=True)

    async def _extract_and_execute_actions(
```
REPLACE:
```
                logger.debug("AD-493: Fingerprint recording failed", exc_info=True)
        return True

    async def _extract_and_execute_actions(
```

**P2-14.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
from probos.cognitive.action_billets import decision_billet  # BF-934
```
REPLACE:
```
from probos.cognitive.action_accounting import record_declared  # BF-934
from probos.cognitive.action_billets import decision_billet  # BF-934
```

**P2-15.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
        has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))
```
REPLACE:
```
        has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))

        # BF-934: the decision record, written where the decision is made (a proactive think whose triage intends an action a block or a post carries out).
        await record_declared(
            _rt, agent_id=self.id, agent_type=self.agent_type, callsign=getattr(self, "callsign", "") or self.agent_type,
            intent=intent, intent_id=observation.get("intent_id", ""), intended=intended_actions,
            path="chain" if has_comm_action and execute_steps else "single_call",
        )
```

**P2-16.** `src/probos/cognitive/cognitive_agent.py`
SEARCH:
```
    # AD-1357 (#1749): the reply's context manifest, LAST, so that BF-805's greedy
```
REPLACE:
```
    # BF-934 (#1673): the actions the triage intended, bounded, so that the loop that executes the output can account for each of them.
    intended = observation.get("_intended_actions") if isinstance(observation, dict) else None
    if type(intended) is list and intended:
        metadata["intended_actions"] = [str(tag)[:40] for tag in intended[:16]]
    # AD-1357 (#1749): the reply's context manifest, LAST, so that BF-805's greedy
```

**P2-17.** `tests/test_ad1195_eventlog_pair_freeze.py` (the census freezes every EventLog write pair; these two are BF-934's)
SEARCH:
```
    ('consensus', 'write_failed'),
```
REPLACE:
```
    ('consensus', 'write_failed'),
    # BF-934 (#1673): a proactive think's triage decision and each intended action nothing carried out, through CATEGORY, DECLARED_EVENT and
    # DROPPED_EVENT. Best effort: Improvement Proposals and Ship's Records are authoritative for what was posted, and a row that could not be
    # written is logged at WARNING.
    ('intended_actions', 'declared'),
    ('intended_actions', 'dropped'),
```

**N2-1.** `tests/test_bf934_s3_intended_actions_ledger.py`
SEARCH:
```
class TestEveryIntendedActionIsCarriedOutOrDropped:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S3 M2 builds it")

    @pytest.mark.parametrize("tag", [t for t in ACTION_TAGS if t != "ward_room_post"])
```
REPLACE:
```
class TestEveryIntendedActionIsCarriedOutOrDropped:
    @pytest.mark.parametrize("tag", [t for t in ACTION_TAGS if t != "ward_room_post"])
```

**N2-2.** `tests/test_bf934_s3_intended_actions_ledger.py`
SEARCH:
```
class TestTheDecisionRecordReconcilesAgainstWhatWasPosted:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S3 M2 builds it")

    async def test_decided_equals_posted_plus_dropped_per_agent_and_action(self, tmp_path):
```
REPLACE:
```
class TestTheDecisionRecordReconcilesAgainstWhatWasPosted:
    async def test_decided_equals_posted_plus_dropped_per_agent_and_action(self, tmp_path):
```

**N2-3.** `tests/test_bf934_s3_intended_actions_ledger.py`
SEARCH:
```
class TestTheRegistryAndTheMetadata:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S3 M2 builds it")

    def test_the_registry_holds_exactly_the_tags_the_analyze_prompts_offer(self):
```
REPLACE:
```
class TestTheRegistryAndTheMetadata:
    def test_the_registry_holds_exactly_the_tags_the_analyze_prompts_offer(self):
```

#### S3 / M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-934 S3 (DATE), #1673 -- every action a proactive think's triage intended is carried out or recorded as dropped, with a reason, per agent and action (slice 3 of 3).**
- **Base.** Nothing counted what a triage decided against what the loop carried out: `intended_actions` was read nowhere in the proactive loop, `actions_taken` was never read and the result's metadata did not carry the decision, so a lost proposal or notebook entry left no trace (the issue: 31 of 36 intended proposals lost).
- **Fix.** New `cognitive/action_accounting.py`. `CognitiveAgent` writes a `declared` EventLog row where the decision is made (`record_declared`) and puts the decision on the result's metadata, bounded. Each exit of `_think_for_agent` calls `settle_intended_actions`, which writes a `dropped` row and a log line for each intended action nothing carried out (reasons `think_failed`, `no_output`, `no_response`, `raw_intent_json`, `empty_after_extraction`, `similar_to_recent_post`, `not_novel`, `not_posted`, the extractor's own, `no_block_executed`; WARNING for a lost decision, INFO for a withheld observation or a by-design notebook suppression); `_post_to_ward_room` returns whether a thread was created. The crew's reconciliation: decided = the `declared` rows (`events.db`), posted = Improvement Proposals and Ship's Records, dropped = the `dropped` rows; `declared = posted + dropped`. Two pairs are frozen in the AD-1195 census. Contract `prompts/bf-934-dropped-crew-proposals.md`. Closes #1673.

```

**P3-2.** `DECISIONS.md`. Append after S2's entry. Its last bullet occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1, L2, L4, L5, L9 and L10 of the contract. *Reversal.* Revert the BF-934 slice 2 commits (slice 3 first, if built).
```
REPLACE:
```
- *Residual.* L1, L2, L4, L5, L9 and L10 of the contract. *Reversal.* Revert the BF-934 slice 2 commits (slice 3 first, if built).

### BF-934 -- Every intended action of a proactive think is carried out or recorded as dropped, with a reason (slice 3 of 3; DATE, #1673)

- *Scope.* `cognitive/action_accounting.py` (new), `cognitive_agent.py` (`record_declared` at the decision; `intended_actions` on the result's metadata), `proactive.py` (`settle_intended_actions` at each exit; `_post_to_ward_room` returns a bool), `tests/test_ad1195_eventlog_pair_freeze.py` (two pairs), tests. Contract `prompts/bf-934-dropped-crew-proposals.md`. Slice 3 of #1673.
- *G1 (the home).* EventLog rows (`category="intended_actions"`, events `declared` and `dropped`), written directly (the BF-237 precedent). Rejected: a new `EventType` (AD-1195's hard counts, four tests); in-memory counters (lost at restart); log lines alone; the cognitive journal (one row per model call, no decision); a new store.
- *G2 (the sources of truth, recorded before landing as the crew asked).* Decided = the `declared` rows, written where the decision is made and not by the layer that drops the output; posted = Improvement Proposals (Ship's Records for notebooks); dropped = the `dropped` rows. The identity per agent and action is `declared = posted + dropped`; a positive discrepancy is an unexplained loss (the alarm), a negative one an undeclared post (AD-643b).
- *G3 (the structured drop entry).* `{"type": "action_dropped", "action", "reason"}` (and `by_design` for a notebook the writer declined as a repeat): WARNING for a lost decision, INFO for an observation the gates withheld and for a by-design suppression.
- *G4 (scope).* Proactive thinks only; the Ward Room notification path is not reconciled (L6).
- *Residual.* L1, L3, L6, L7, L8, L12, L13, L14 and L16 of the contract. *Reversal.* Revert the BF-934 slice 3 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

`compose.py` (COMPOSE and its AD-651a billet: read, not edited; S1's drift guard reads it); `_COMM_ACTIONS`, the triage and the chain's routing (`_extract_intended_actions`, the AD-643a skip, the `["silent"]` return, the lookups); the result of AD-643b's detection (`_detect_undeclared_actions` keeps its six markers and their order; its table moves to `_ACTION_MARKERS`); the single call's system prompt, the standing orders and both ANALYZE prompts (the registry test reads the prompts, it does not edit them); `WardRoomRouter.handle_propose_improvement` (its answer is now read), the Improvement Proposals channel and the Ward Room pipeline (it keeps its order and receives the new WARNINGs and the new entry through the shared extractor); the notebook writer, `RecordsStore` and its dedup (AD-550) and repetition (AD-552) gates; `EventLog`, `EventType`, the durable router and every AD-1195 hard count (no new `EventType`; two resolved pairs are frozen in the census); the circuit breaker, the duty tracker, working memory (AD-573) and `_run_cycle` (L3); BF-032's similarity function itself (L2), BF-172 and BF-215; the decision cache and procedural replay; the notification path's behaviour (L6); `config.py` and every config model (no field is added); the roadmap and every document but the two trackers and the ledger. OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on its slice's M2 head)

| # | M | File | Line (stripped) | Mutate to | Killed by (expected) |
|---|---|---|---|---|---|
| 1 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `observation.pop("_intended_actions", None)` | `pass` | T3 (1) |
| 2 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `observation["_intended_actions"] = intended_actions` | `pass` | T4, T5 (5), T6, T7 (8) |
| 3 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `_decided = decision_billet(observation.get("_intended_actions"))` | `_decided = ""` | T4, T5 (5), T6, T7 (8) |
| 4 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `elif not _decided:` | `else:` | T5 (5) |
| 5 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `if not _decided:` | `if True:` | T6 (1) |
| 6 | S1 M2 | src/probos/cognitive/action_billets.py | `if not any(tag in tags for tag in _BLOCK_TAGS):` | `if False:` | T2 (3: oracle_query, leadership_review, speak_freely), T10 (5) |
| 7 | S1 M2 | src/probos/cognitive/action_billets.py | `if "proposal" in tags:` | `if False:` | T5 (3: proposal, both, silent+proposal), T7, T9 (5) |
| 8 | S1 M2 | src/probos/cognitive/action_billets.py | `if "notebook" in tags:` | `if False:` | T5 (3: notebook, both, notebook+lookup), T9 (4) |
| 9 | S1 M2 | src/probos/cognitive/action_billets.py | `"Title: <short descriptive title>\n"` | `"Title: <short title>\n"` | T8 (1) |
| 10 | S1 M2 | src/probos/cognitive/action_billets.py | `_BLOCK_TAGS = ("proposal", "notebook")  # the tags whose block the single call has no other reason to write` | `_BLOCK_TAGS = ("proposal",)` | T5 (2: notebook, notebook+lookup), T9 (3) |
| 11 | S2 M2 | src/probos/proactive.py | `if not response_text or ("[NO_RESPONSE]" in response_text and not carries_actionable_block(response_text)):` | `if not response_text or "[NO_RESPONSE]" in response_text:` | T4 (3), T5 (1) |
| 12 | S2 M2 | src/probos/proactive.py | `if _withdrawn:` | `if False:` | T5 (1) |
| 13 | S2 M2 | src/probos/proactive.py | `if isinstance(posted, dict) and posted.get("success") is False:` | `if False:` | T10[refused] (1) |
| 14 | S2 M2 | src/probos/proactive.py | `reason = f"post_failed: {type(exc).__name__}"` | `reason = ""` | T10[raises] (1) |
| 15 | S2 M2 | src/probos/proactive.py | `if reason:  # BF-934: a decision that cannot be filed is said, with the agent and why, and recorded as an entry` | `if False:` | T9[no Title, no Rationale], T10 (5) |
| 16 | S2 M2 | src/probos/proactive.py | `actions_executed.append({"type": "proposal_suppressed", "reason": "malformed_block"})` | `pass` | T9[malformed] (1) |
| 17 | S2 M2 | src/probos/proactive.py | `if proposal.extra_blocks:` | `if False:` | T11 (1) |
| 18 | S2 M2 | src/probos/cognitive/proposal_block.py | `problem = "missing_title" if not title else "missing_rationale" if not rationale else ""` | `problem = ""` | T9[no Title, no Rationale], T12[the same two] (4) |
| 19 | S2 M2 | src/probos/proactive.py | `return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])` | `return parse_proposal_block(text).valid` | T4[notebook] (1) |
| 20 | S2 M2 | src/probos/proactive.py | `return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])` | `return bool(split_notebook_blocks(text)[1])` | T4[proposal], T5 (2) |
| 21 | S2 M2 | src/probos/cognitive/cognitive_agent.py | `if lost:` | `if False:` | T8 (2) |
| 22 | S2 M2 | src/probos/cognitive/cognitive_agent.py | `return [tag for tag in _action_markers_in(compose_output) if tag not in declared]` | `return []` | T3 (1: the re-reflect control) |
| 23 | S2 M2 | src/probos/proactive.py | `reason = "no_router"` | `reason = ""` | T10[no_router] (1) |
| 24 | S2 M2 | src/probos/proactive.py | `logger.warning("BF-934: proposal from %s (%s) not posted: %s", _proposer, getattr(agent, 'agent_type', 'unknown'), reason)` | `logger.debug(` in place of `logger.warning(` | T9 (2), T10 (3) |
| 25 | S3 M2 | src/probos/cognitive/action_accounting.py | `if spec is None or not spec.evidence or done & spec.evidence:` | `if spec is None or not spec.evidence:` | T2 (6), T7 (1), T10 (2), T13 (1), T16 (3): 13 |
| 26 | S3 M2 | src/probos/cognitive/action_accounting.py | `"reason": reason if tag == "ward_room_post" or reason in PRE_EXTRACTION else "no_block_executed",` | `"reason": reason,` | T5 (5), T16 (1) |
| 27 | S3 M2 | src/probos/cognitive/action_accounting.py | `drop["reason"] = str(entry.get("reason") or drop["reason"])` | `pass` | T7, T13, T16 (3) |
| 28 | S3 M2 | src/probos/cognitive/action_accounting.py | `drop["by_design"] = True  # AD-550's dedup and AD-552's repetition gate: counted, and only noted` | `pass` | T7, T13 (2) |
| 29 | S3 M2 | src/probos/cognitive/action_accounting.py | `level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") else logging.WARNING` | `level = logging.WARNING` | T6, T7 (2) |
| 30 | S3 M2 | src/probos/cognitive/action_accounting.py | `level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") else logging.WARNING` | `level = logging.INFO` | T5 (5) |
| 31 | S3 M2 | src/probos/cognitive/cognitive_agent.py | `path="chain" if has_comm_action and execute_steps else "single_call",` | `path="chain",` | T13 (1) |
| 32 | S3 M2 | src/probos/cognitive/cognitive_agent.py | `metadata["intended_actions"] = [str(tag)[:40] for tag in intended[:16]]` | `metadata["intended_actions"] = list(intended)` | T17 (1) |
| 33 | S3 M2 | src/probos/proactive.py | `"think_failed" if not (result and result.success) else "no_output",` | `"no_output",` | T8 (1) |
| 34 | S3 M2 | src/probos/proactive.py | `actions_taken.append({"type": "ward_room_post"})` | `pass` | T2[ward_room_post] (1) |
| 35 | S3 M2 | src/probos/proactive.py | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), [], "no_response")` | `pass` | T6, T9, T13 (3) |
| 36 | S3 M2 | src/probos/cognitive/action_accounting.py | `if intent != "proactive_think" or log is None or not any(ACTION_TAGS.get(tag, ActionTag()).evidence for tag in tags):` | `if log is None or not any(ACTION_TAGS.get(tag, ActionTag()).evidence for tag in tags):` | T14 (1) |
| 37 | S3 M2 | src/probos/cognitive/action_accounting.py | `if intent != "proactive_think" or log is None or not any(ACTION_TAGS.get(tag, ActionTag()).evidence for tag in tags):` | `if True:` | T13 (1) |
| 38 | S3 M2 | src/probos/proactive.py | `logger.warning("BF-934: no channel to post the observation of %s: the observation is not posted", agent.agent_type)` | `logger.debug(` in place of `logger.warning(` | T11 (1) |
| 39 | S3 M2 | src/probos/proactive.py | `if await self._post_to_ward_room(agent, response_text):  # BF-934: True once a thread was created` | `if await self._post_to_ward_room(agent, response_text) or True:  # BF-934` | T12 (1) |
| 40 | S3 M2 | src/probos/proactive.py | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "not_posted")` | `pass` | T5 (5), T12, T13 (7) |
| 41 | S3 M2 | src/probos/proactive.py | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), [], "raw_intent_json")` | `pass` | T10[raw_intent_json] (1) |
| 42 | S3 M2 | src/probos/proactive.py | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "no_response" if _withdrawn else "empty_after_extraction")` | `"no_response" if _withdrawn else "empty_after_extraction"` becomes `"empty_after_extraction"` | T10[no_response beside a block] (1) |
| 43 | S3 M2 | src/probos/proactive.py | the line of row 42 | `pass` | T7 (1), T10 (2): 3 |
| 44 | S3 M2 | src/probos/proactive.py | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "similar_to_recent_post")` | `pass` | T10[similar_to_recent_post] (1) |
| 45 | S3 M2 | src/probos/proactive.py | `await settle_intended_actions(self._runtime, agent, intent.id, getattr(result, "metadata", None), actions_taken, "not_novel")` | `pass` | T10[not_novel] (1) |
| 46 | S3 M2 | src/probos/cognitive/action_accounting.py | `PRE_EXTRACTION = frozenset({"think_failed", "no_output", "no_response", "raw_intent_json"})` | `PRE_EXTRACTION = frozenset({"think_failed", "no_output", "raw_intent_json"})` | T13, T16[no_response] (2) |
| 47 | S3 M2 | src/probos/cognitive/action_accounting.py | `category=CATEGORY, event=DECLARED_EVENT, agent_id=agent_id, agent_type=agent_type,` | `category=CATEGORY, event=DECLARED_EVENT, agent_id=None, agent_type=agent_type,` | T13 (1) |

The Id in "Killed by" is the slice's own (section 6). Each row kills at least one case of the slice's new test file alone (counts are what the hand run measured; under pytest they are "expected"). Run by hand against the patched modules (no pytest), each mutant fails exactly the cases it names; this is not a campaign of record: the Builder runs the 47 rows once, each on its slice's M2 head, with that slice's new file alone, and reports any row that survives. Rows 29 and 30, 36 and 37, 42 and 43 share a line. Not tabulated: the gate order itself (no one-line mutant reorders a block; cases T6 and T7 of S2 fail on the base tree, which is that mutant), the controls, the `isinstance(metadata, dict)` guard of `settle_intended_actions` (it is for the `MagicMock` results of existing tests, which G2 runs) and the `data` payload of the `declared` row other than `agent_id`.

## 10. Recorded limits

- **L1. Not run under pytest.** This contract was checked by an in-memory script, not by pytest (a read-only consult). Unchecked: the real collection and fixtures (`tmp_path` on disk, the real `caplog`); the git-backed `RecordsStore` on disk (the script used an in-memory stand-in that returns the real `check_notebook_similarity` answer shape and the real reason text `content unchanged from recent entry`, `records_store.py:1193`); xdist and suite order; the existing suite (the files of each G2); the checker's command (its `check()` function was run in memory); any live model. About 60 test files scan the whole `src` tree by `rglob` (a grep of `tests`); they were not run, and not read one by one: the new code uses none of the constructs the censuses I read look for (a subprocess, the environment, a file write, `aiosqlite.connect`, a task, a network call), the AD-1195 and AD-1270 censuses were checked by running or reading (section 11), and the broad gate runs the rest. Every count in sections 4, 6 and 9 is "expected".
- **L2. BF-032's similarity gate can never match in production (found, not fixed; a new BF for the orchestrator to allocate).** `_is_similar_to_recent_posts` (`proactive.py:2970`) calls `ward_room.get_recent_activity(ch.id, limit=10, since=None)` (`:2990-2991`) whose SQL is `created_at > ?` (`ward_room/threads.py:386`), so `since=None` returns no rows; and the items it returns carry `author` (the callsign) and no `author_id`, so `author == agent.id` never holds. Run against a real Ward Room service that held the agent's own identical post, `get_recent_activity(since=None)` returned `[]`, an item had a callsign and no `author_id`, and the check returned `False`. The same function backs the pipeline's BF-197 guard (`ward_room_pipeline.py:309`) and BF-105's reply guard (`proactive.py:4099`). `since=None` is also passed at `:4047` (not examined). Consequence here: S2's ordering test stubs the verdict (`AsyncMock(return_value=True)`), and in production the reorder changes what AD-493's novelty gate does to blocks.
- **L3. `_run_cycle` logs a think's exception at DEBUG** (`proactive.py:1154-1160`), unchanged. A think that raises after its `declared` row leaves no `dropped` row: an unexplained gap, which the reconciliation reports as the alarm it is meant to be.
- **L4. `[NO_RESPONSE]` is read for blocks only beside a proposal or a notebook entry** (the issue's two). A withdrawn output that carries a `[REPLY]`, `[DM]` or `[ENDORSE]` is still read as silence; `carries_actionable_block` is the one place to widen it, if the Captain wants.
- **L5. REFLECT's own rewrite is unchanged** (the issue's Sage case, 1 of 31): a REFLECT that answers `[NO_RESPONSE]` for an output carrying a proposal is a model decision inside the chain. It is now visible (a `declared` row, then a `dropped` row with `no_response`).
- **L6. Proactive thinks only.** `record_declared` writes for `intent == "proactive_think"`. The Ward Room notification path (`ward_room_pipeline.py:293`) shares `_extract_and_execute_actions`, so it gains the proposal WARNINGs and the `proposal_suppressed` entry (which it discards) but writes no row.
- **L7. No triage, no row.** A decision served from the decision cache or by procedural replay makes no triage (`decide`, `:3736`): no `declared` row, and no billet is needed.
- **L8. What an entry does not prove.** `endorse` is recorded as executed when the extractor ran it, though `process_endorsements` swallows `ValueError` and every other exception at DEBUG (`ward_room_router.py:1183-1187`); the reply extractor skips, at DEBUG, a locked thread, BF-105, BF-171 and BF-201 (`proactive.py:4094-4131`), so a reply that did not land is dropped as `no_block_executed` with the cause in the DEBUG log only. S3 counts whether an entry exists, not whether the effect landed, for those tags.
- **L9. Placeholders.** A model that echoes the format's `<short descriptive title>` files a proposal with that title: the parser accepts any non-empty Title and Rationale.
- **L10. One proposal per output; a tag-level post.** A second `[PROPOSAL]` block is logged and not filed (AD-412's first-block rule, unchanged); `_post_to_ward_room` says whether a thread was created, not what it holds.
- **L11. The proposal format is written twice:** COMPOSE's AD-651a billet (its line holds an em dash that an ASCII SEARCH cannot carry, so `compose.py` is not edited) and `PROPOSAL_FORMAT`. S1's T8 pins them equal and fails if either changes alone.
- **L12. The registry classifies five tags by name only** (`silent`, `speak_freely`, `leadership_review`, `oracle_query`, `ward_room_lookup`: carried out by something else, each with a `how` text): their effects are not tested here. A tag a future ANALYZE prompt offers fails the registry test until it is classified; a tag outside the registry is counted nowhere.
- **L13. Volume and retention are unmeasured.** One `declared` row per proactive think whose triage intends a block or a post, one `dropped` row per lost action. `events.db` prunes at 7 days and 100000 rows (`EventLogConfig`) and Ward Room threads at 7 days, 30 if endorsed (`ward_room/threads.py:853`): a reconciliation window longer than 7 days compares data that no longer exists, so its cadence is daily at the longest (section 15).
- **L14. The decision recorded is the triage's, the path the planned one.** Phase 2a re-runs the whole chain, ANALYZE included, so COMPOSE's AD-651a billet reads a second sample of `intended_actions`; the `declared` row and the accounting use the first. `data.path` is `chain` when `has_comm_action and execute_steps` at the decision, even if the chain later falls back to the single call.
- **L15. The billet's wording and the real models.** The seam tests use a model that obeys the decision it is shown. Whether the real models do, and whether "the decision stands" is strong enough, is the live re-measure's question (section 15). The billet adds 550 to 899 characters to a prompt (measured).
- **L16. By-design suppression, and surplus.** A notebook entry the writer declines as a repeat (AD-550) or by repetition (AD-552) is counted as dropped, marked `by_design`, and logged at INFO: the identity `declared = posted + dropped` holds with those counted, and whether the crew's "zero" counts them is the Captain's call (section 15). A negative discrepancy is an undeclared post, not a loss.

## 11. Verified Against Codebase (2026-11-11, reading tree `D:\ProbOS-worktrees\bf934-base` at `fe488971`)

**Run by the Architect, read-only (CPython 3.12.13, win32; every script piped through stdin and run with `-B` and `PYTHONDONTWRITEBYTECODE`, so nothing was written; no pytest; no test of the repository was run by pytest):**

```
git rev-parse HEAD and origin/main (bf934-base) -> both fe4889715644c57bdf3f3a7c9c08a1ede158fef3; git status --short of the reading tree: 0 lines before and after every run
git rev-parse HEAD:<path> for the six paths of the header -> the blobs it names (the three code blobs are byte-identical to the BF-935 oracle's: the orchestrator's statement, not re-measured here)
git ls-tree HEAD -- <each of the seven new paths> -> nothing: none exists
this contract's 44 pairs (38 code and test, 6 tracker) and 7 new files applied in document order to the LF blobs by script: every SEARCH occurs once at its turn and starts at the start of a line (0 mid-line); every Python result compiles; the three trackers' PROGRESS entries stack newest first; the answer holds 0 non-ASCII characters
the patched modules served over the real tree through a sys.meta_path finder, the three new test files driven by a hand-made runner (parametrize; xfail with strict and raises=AssertionError; fakes for tmp_path, monkeypatch and caplog; SQLite in memory for the Ward Room and the EventLog; Ship's Records an in-memory stand-in with the real answer shape of check_notebook_similarity):
  M1 heads (the base source plus the tests): S1 6 passed 16 xfailed; S2 5 passed 21 xfailed; S3 18 passed 25 xfailed; no XPASS, no failure other than the class cases' own assert (the base reproduced: the 62 class cases are the defect)
  M2 heads: S1 22 of 22, S2 26 of 26, S3 43 of 43; all three files on the S3 head: 22, 26 and 43
  the 47 mutants of section 9, each on its slice's M2 head: each failed the cases the row names; none survived
the real census functions of tests/test_ad1195_eventlog_pair_freeze.py (test_census_premise_reads_this_checkout_and_sees_known_calls, test_literal_pairs_are_exactly_the_contract_37, test_resolved_pairs_are_frozen, test_every_dynamic_site_is_allowlisted_and_nothing_is_unclassifiable) called as plain functions over the patched sources in memory: all four pass on the S2 head (18 resolved pairs) and on the S3 head (20: the two intended_actions pairs, found through CATEGORY, DECLARED_EVENT and DROPPED_EVENT)
the real check() of scripts/check_architecture_principles.py run over the patched sources in memory at the base, S1, S2 and S3 heads: errors [], srp-size 92/92, layer-import 0/0, db-connect 30/30, unowned-task 13/13 each time
BF-032: a real WardRoomService holding the agent's own identical post -> get_recent_activity(since=0.0) gave one thread item with author "Kira" and no author_id; get_recent_activity(since=None) gave []; agent.id is "science_officer_science_officer_0_a102c2f8"; _is_similar_to_recent_posts(agent, <the identical text>) -> False
the billet: decision_billet(["proposal"]) 730 characters, ["notebook"] 550, ["proposal","notebook"] 899, ["ward_room_post","proposal"] 833, ["silent"] and ["oracle_query"] ""
```

**Absence Verified (2026-11-11)**

```
CLAIM: no BF-934 other than #1673; the highest BF before it is BF-961
RUN:   git log --all --format=%s (4687 subjects) matched for BF-934 and for BF-(\d+); git worktree list --porcelain (125 worktrees) then Get-ChildItem <worktree>\prompts -Filter *934*; gh issue list --state all --search "BF-934 in:title"; rg -n "BF-934" docs/development/roadmap.md docs/development/roadmap-completed.md PROGRESS.md DECISIONS.md progress-era-5-unification.md decisions-era-5-unification.md; the highest prompts/bf-*.md
FOUND: 0 subjects name BF-934; 0 files in 125 worktrees; #1673 only (OPEN, label bug); 0 hits in the trackers; the highest BF is BF-961 (git subjects and prompts/bf-961-*)
HOLDS: yes

CLAIM: nothing in the proactive loop, the Ward Room or the journal reads intended_actions; the loop discards the entry list it receives; the loop reads no result metadata
RUN:   rg -c "intended_actions" src/probos; rg -n "actions_taken|actions_executed" src/probos/proactive.py; rg -n "\.metadata" src/probos/proactive.py
FOUND: five files: cognitive_agent.py 24, sub_tasks/analyze.py 11, sub_tasks/compose.py 4, skill_catalog.py 3, sub_tasks/reflect.py 2; actions_taken is assigned at :1525 and read nowhere (actions_executed is the extractor's own list); 0 hits for .metadata
HOLDS: yes

CLAIM: SubTaskExecutor.execute keeps no memo of step results across calls, so Phase 2a's ANALYZE is a second call and COMPOSE's billet reads a second sample
RUN:   rg -n -i "cache|memo|lru_cache|functools" src/probos/cognitive/sub_task.py; the response-cache lookups of cognitive/llm_client.py (:1523-1537, :1996-2012)
FOUND: sub_task.py names a cache only as BF-901's `cached` flag of a client replay (:100, :678) and in no store of results; execute(chain, context, ...) returns the list and keeps nothing; llm_client.py consults its response cache only after the live endpoints failed or the rate limit refused, so an identical second ANALYZE request is a live call
HOLDS: yes

CLAIM: the new names are free
RUN:   rg -n "_intended_actions|action_billets|action_accounting|proposal_block|decision_billet|settle_intended_actions|record_declared|carries_actionable_block|parse_proposal_block|_action_markers_in|_ACTION_MARKERS|action_dropped|bf934_world" over src, tests, scripts and config; git ls-tree HEAD -- <the seven new paths>
FOUND: _extract_intended_actions and its tests (a substring of the first pattern); the local variable proposal_block (proactive.py:3562, :3572), which S2's P2-7 replaces; the seven paths are absent
HOLDS: yes

CLAIM: the readers of every changed contract are the ones D3 names
RUN:   rg -n "_post_to_ward_room\(" src tests scripts; rg -n "extract_and_execute_actions|_extract_and_execute_actions\(" src; rg -n "_re_reflect_with_feedback\(" src; rg -n "_build_result_metadata\(" src; rg -n "(result|res|intent_result)\.metadata\.(items|keys|values)\(\)|json\.dumps\(\w*\.?metadata" src/probos
FOUND: _post_to_ward_room: proactive.py:1553 and the definition, test_bf198_router_proactive_dedup.py:200, test_bf874_dm_callsign_and_fail_closed.py:558, each awaited as a statement; the extractor: proactive.py:1525 and ward_room_pipeline.py:293 (through proactive.py:2954-2962; its entry list is discarded there); the re-reflect: cognitive_agent.py:6606 only; the metadata builder: cognitive_agent.py:8023 only; the json.dumps hits are crew_session turn records, the archive store, workforce items and threads (other types)
HOLDS: yes

CLAIM: no test assigns, without restoring, an attribute of a class or module the slices patch
RUN:   rg -n "^\s*(CognitiveAgent|ProactiveCognitiveLoop|WardRoomService|WardRoomRouter|RecordsStore|EventLog|SubTaskExecutor|NoveltyGate|WardRoomPostPipeline)\.[A-Za-z_]+\s*=[^=]" tests; rg -n "type\([A-Za-z_.\[\]\"]+\)\.[A-Za-z_]+\s*=[^=]" tests; rg -n "^\s*(probos\.proactive|proactive|probos\.cognitive\.cognitive_agent|cognitive_agent|records_store|probos\.knowledge\.records_store)\.[A-Za-z_]+\s*=[^=]" tests; rg -n "_DECISION_CACHES|_CACHE_HITS|_CACHE_MISSES|_NOTEBOOK_PATTERN" tests
FOUND: 0 on the classes; ten type(x).attr assignments on other classes (test_ad628_crew_skill_readiness, test_ad635e_clinical_shell_command, test_bf214_scout_seen_deferral (the Scout agent: in no G2 here), test_bf844, test_bf896, test_bf904b (type(self).last on local fakes), test_commands_llm, test_shell); proactive.get_agent_cooldown = ... (test_counselor_therapeutic) and proactive._runtime = ... (test_recreation_channels) are on MagicMock() objects named proactive; the caches are cleared by the world (conftest's autouse `_ad682_clear_module_caches` resets the standing-orders and chat-router caches, not these three)
HOLDS: yes

CLAIM: no test pins the single call's closing lines, the gate order or the DEBUG wording of the proposal block
RUN:   rg -l "Otherwise respond with exactly|If nothing noteworthy to report|Compose a Ward Room post with your findings|If something genuinely warrants attention" tests; the four files that name BF-032 or set_novelty_gate (test_bf201_thread_post_cap, test_bf237_pipeline_post_budget, test_proactive_quality, test_proactive) read for an order; rg -n "Malformed \[PROPOSAL\]|AD-412: Failed" tests
FOUND: 0 files for the closing lines; the four files assert each gate's verdict and not their order; 0 hits for the two DEBUG messages
HOLDS: yes

CLAIM: the files of each G2 are the tests that name the code the slice edits
RUN:   rg -l <pattern> tests --glob test_*.py for: _execute_chain_with_intent_routing|_COMM_ACTIONS|has_comm_action|No comm actions (8 files); _build_user_message (34) intersected with _think_for_agent|proactive_think (15); _think_for_agent (13 test files and tests/fixtures/ad1343_seam_registry.py); _extract_and_execute_actions|extract_and_execute_actions (19); _detect_undeclared_actions|_re_reflect_with_feedback|undeclared_action_feedback (4); \[PROPOSAL\]|Malformed \[PROPOSAL\]|proposal_pattern (5 test files and a golden json); _is_similar_to_recent_posts|set_novelty_gate|BF-032 (4); _build_result_metadata (4); _post_to_ward_room (6); AD-1195|_RESOLVED_PAIRS (11, of which four are the contract's tests)
FOUND: the three lists of section 4, sorted ordinally, each file present
HOLDS: yes (the lists are a union; a file that names a symbol only in a comment is included, never missed)

CLAIM: the Ward Room pipeline extracts before its similarity and novelty gates
RUN:   rg -n "Step [0-9]|extract_and_execute_actions|is_similar_to_recent_posts|novelty" src/probos/ward_room_pipeline.py
FOUND: Step 3 action extraction :288-293, Step 4 similarity guard (BF-197) :307-309, Step 4b AD-493 :318-321
HOLDS: yes

CLAIM: nothing outside AD-643b, the journal and PostBudgetTelemetry counts or logs actions of a think, and none counts intended against executed
RUN:   rg -n "undeclared|_undeclared_action_feedback" src/probos; the journal's schema (journal.py:22-48); rg -n "class PostBudgetTelemetry" src/probos
FOUND: AD-643b's INFO line (cognitive_agent.py:6592) and the observation key it sets (:6597), which the episode reads (:12721-12722); the journal has one row per model call with no decision column; PostBudgetTelemetry (ward_room_pipeline.py:57) counts the post budget
HOLDS: yes
```

**Read, not run:** `cognitive_agent.py:251`, `:310`, `:367-370`, `:3736`, `:3846-3884`, `:3906`, `:5942-5990`, `:6310-6340`, `:6446-6447`, `:6474-6515`, `:6540-6700`, `:8023`, `:10604`, `:11494-11498`; `proactive.py:220-235`, `:1050`, `:1144-1160`, `:1293`, `:1412-1553`, `:2954-2970`, `:2970-3010`, `:3042-3105`, `:3107-3215`, `:3558-3635`, `:4094-4131`; `compose.py:240`, `:291-307`; `analyze.py:179-180`, `:402`; `ward_room_router.py:1063-1090`, `:1134-1187`; `ward_room_pipeline.py:57`, `:288-329`, `:367`; `ward_room/threads.py:375-410`, `:853`; `ward_room/service.py:408`; `knowledge/records_store.py:709`, `:1128-1215`; `substrate/event_log.py:516`, `:624-636`, `:906-914`, `:1324`; `config_models/core.py:146-150`; `tests/test_ad1195_eventlog_pair_freeze.py:312-420`; `tests/test_ad1270_boot_camp_trust.py:243-345`; `tests/test_trigger_learning.py:340-440`; `tests/test_proactive.py:1455-1730`. **Not measured:** a live vessel, a real model, the live logs and the issue's counts, the volume of rows.

## 12. Prior Art and Blind Spots

- **What already counts, logs or reconciles intended against executed actions (enumerated in section 11).** AD-643b logs the converse (an action taken that the triage did not declare) at INFO and keeps `_undeclared_action_feedback` on the observation for the episode; nothing counts it. No telemetry object reads intended actions (`PostBudgetTelemetry` counts the post budget); the cognitive journal holds one row per model call and no decision; `actions_taken` in the think is assigned and never read. S3's rows are therefore the first count of the decision and of its loss, and the two together are the crew's reconciliation: the new counter is not a second one of the same thing, and S2's `_ACTION_MARKERS` is the one table of markers that AD-643b's detection and the re-reflect guard share.
- **Internal: adopted.** The extractor's `<tag>_suppressed` entry convention (`notebook_suppressed`, `artifact_suppressed`) for `proposal_suppressed`; BF-237's direct EventLog row (`ward_room_pipeline.py:367`) as the home of the rows; AD-1195's census for the two pairs; the Ward Room pipeline's order (extraction, then the similarity and novelty gates); BF-922's private observation key (`CHAIN_FALLBACK_KEY`) for `_intended_actions`; AD-651a's billet text as `PROPOSAL_FORMAT`, pinned equal to it. **Rejected:** chain triggers for the two tags; a new `EventType`; counters; a store; annotate-only. **External:** none consulted.
- **The notebook's real path (the issue's "very likely").** Confirmed by reading and by the in-memory seam run: the writer is `_extract_and_execute_actions` (`_NOTEBOOK_PATTERN`, AD-434; AD-550's dedup; AD-552's repetition gate), no gate reads `intended_actions`, and the routing of item 1 sends a notebook decision to the single call that was never told. The control case writes the note on both trees when the model writes the block itself, so the loss is the routing and not the notebook path.
- **Blind spots handled.** A decision with a communication action and a proposal (the chain's COMPOSE billet; a failed chain's single call, T7); a duty think (T6); a dict used again (T3); a failed triage; a model that answers silence (a recorded withdrawal); a proposal and a notebook entry beside a repeated or rehashed observation (S2 T6, T7); a withdrawn observation beside a valid block, with and without prose (S2 T4, T5); a re-reflect to silence and to a text without the block (S2 T8); a router that is missing, refuses or raises (S2 T10); a second block (S2 T11); a malformed block, no Title, no Rationale (S2 T9, T12); a row that cannot be written (S3 T9); `MagicMock` metadata of existing tests; a decision made for another intent (S3 T14); a tag outside the registry (S3 T16); a notebook the writer declines by design (S3 T7).
- **What discards a correct result (asked separately from what fails).** A correct billet not delivered: the key is set after the triage and read only by the user message; a decision-cache hit or a replay makes no triage (L7). A correct proposal not filed: the router's refusal, a missing router and a missing channel are now said and recorded, and a withdrawn observation beside a valid block no longer discards it. A correct drop not recorded: a write failure is a WARNING and never blocks the think; a runtime without an `event_log` writes no row, and the log line stays. A correct `declared` row not written: only for `proactive_think` and for a decision that names a tag a block or a post carries out. A correct observation not posted: unchanged, with one exception by design, the observation a model withdrew beside a block. **Recorded:** L1 to L16.
- **What needs the Captain** (section 15 has the exact actions): the live re-measure and its pass condition (acceptance 5); whether the billet is strong enough; whether by-design notebook suppressions count toward "zero" (my recommendation: count them as dropped, marked `by_design`, and report them apart); whether `[NO_RESPONSE]` beside a reply, DM or endorsement should also be read (recommendation: not before it is measured); the BF for L2; and whether to close #1673 with S3's commit or after the Captain's items.

## 13. Diff Reviewer: properties to verify

1. **S1.** `decision_billet` returns `""` unless `proposal` or `notebook` is among the normalised tags; with no decision on the observation `_build_user_message` produces the text it produced before, for the duty branch and the other (trace both). The key is popped before the triage and set after `_extract_intended_actions`; trace a chain that falls back (`_execute_chain_with_intent_routing` returns `None` or `decide` falls through): the key is still on the observation when `_build_user_message` runs. No new chain-executing method exists (AD-1270's census).
2. **S1.** The billet asks for the blocks the extractors read: `PROPOSAL_FORMAT` equals the text between `AFTER your observation text:\n` and `The proposal will be automatically posted` in COMPOSE's billet, and `NOTEBOOK_FORMAT` is a block `_NOTEBOOK_PATTERN` reads.
3. **S2.** `parse_proposal_block` reads a valid block exactly as the inline parser did (Title, Rationale with continuation lines, Affected Systems, Priority) and says a problem for every other text; the strict pattern is the old one (`PROPOSAL_PATTERN`); the extractor files from the first block only, says why when it does not, no longer counts a refusal as filed, and still strips every block (the `re.sub(proposal_pattern, ...)` after it is untouched).
4. **S2.** `carries_actionable_block` is true only for a proposal the extractor can file or a notebook entry with a body. Without one, `[NO_RESPONSE]` returns exactly as before. With one, `_withdrawn` is set, the text is emptied after the extraction, and BF-215 ends the think (trace: no working-memory record, no post, the duty recorded).
5. **S2.** After the move, nothing between BF-172 and the post reads `response_text` assuming the old order: BF-032 and AD-493 see the text left after extraction; the novelty gate's `record` is reached only when the observation is posted, as before.
6. **S2.** In `_re_reflect_with_feedback` `lost` compares the markers of the approved output with those of the rewrite; the early return is inside the `try`; the caller still stores `_undeclared_action_feedback`, so the episode enrichment is unchanged; `_detect_undeclared_actions` returns what it returned for every input (same six patterns, same order).
7. **S3.** `settle_intended_actions` runs at every return of `_think_for_agent` that follows the handling of the result (failure, `[NO_RESPONSE]`, BF-172, BF-215, BF-032, AD-493, the post), with the reason of that exit; the returns before the result exists make no decision and need none. It never raises (`try` around each write; `isinstance(metadata, dict)` for `MagicMock` results).
8. **S3.** `record_declared` runs once per triage, before the chain or the call, for `proactive_think` only, with `correlation_id` the intent id; the loop settles with the same `intent.id` (a `dropped` row's correlation id is one of the `declared` rows', asserted in T13).
9. **S3.** `_post_to_ward_room` returns `True` only after a thread is created, `False` for no channel and for DM-only text; its callers ignore the result except the think.
10. **S3.** The two pairs added to `_RESOLVED_PAIRS` are the two the census finds through `CATEGORY`, `DECLARED_EVENT` and `DROPPED_EVENT`; the freeze test passes without another change (the literal count stays 37).
11. **All.** No new method on `CognitiveAgent`, `ProactiveCognitiveLoop` or `WardRoomService` (the checker's `srp-size` rows are unchanged); no `aiosqlite.connect`; no task is created; every new function is typed; no new config field. The three-tier rule: the row writes and the metadata copy are log-and-degrade; nothing here swallows silently.
12. **Tests.** The helper and the three files import no BF-934 name at module level; every case that needs a module M2 builds goes through `_built`; the world closes what it opens and clears the three caches; no test sleeps, reads the network or relies on another test.

## 14. Acceptance criteria

1. G1 gave the expected counts at each slice's M1 (S1 6 passed and 16 xfailed, S2 5 and 21, S3 18 and 25) and the `--runxfail` failures stopped at an assert of the case.
2. At each M2 the new file passes in full (22, 26 and 43 cases) with the markers removed; every other file of that slice's G2 has 0 failures and a collected count equal to M0; the architecture check is clean; the AD-1195 freeze test passes (S3).
3. The 47 rows of section 9 each fail at least one case of the slice's new file alone, on that slice's M2 head.
4. G3 ran for each slice (the ledger generator, `--check` and `tests/test_ad1184_ad_ledger.py`).
5. The issue's acceptance items: 1 (route) and 2 (the seam test) by S1; 3 (a WARNING with the agent and the reason, and the inverse of AD-643b, counted per agent and action) by S2 and S3; 4 (the gates) by S2; 6 (the tests that pin a defect) by D4's table, which finds none; 5 (the live re-measure) is section 15's. The crew's additions: the named sources of truth (D2), the zero discrepancy with a structured drop entry for every gap (S3) and the per-tag test (S3 T1 to T5, T15, T16) are met by the build; the cadence, the audit, the participation check, the closure notice and the DrillCalendar slots are section 15's.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Not in this issue: for the Captain

None of these is done by the build, and none is weakened to make the build "complete". They are the issue's acceptance item 5 and the crew's additions (the closure notice, the cadence and its calendar, the pre-registered audit and the participation check); the closure comment hands them over. Identities and data are the issue's and the crew's, quoted.

| # | Action (by whom) | Source of truth | Pass condition | Issue item |
|---|---|---|---|---|
| 1 | **The live re-measure.** After the three slices are deployed, over one day of normal operation, report intended against posted by path, for `proposal` and for `notebook`, per agent. | decided: `events.db` rows `category="intended_actions"`, `event="declared"` (`data.intended`, `data.path` is the path: `chain` or `single_call`); posted: threads titled `[Proposal] ...` in Improvement Proposals (`ward_room.db`) and `notebooks/<callsign>/` in Ship's Records; dropped: rows `event="dropped"` (`data.action`, `data.reason`). Not the extractor's counts and not the log. | For every agent and action `declared - posted - dropped` is 0; every `dropped` row has a reason from D2's list (section 3); the `dropped` rows with `no_response` for a `proposal` on `single_call` are read as the measure of the billet's strength (D1); the report carries the data caveat of Lyra and Atlas (proposal volume from July on cannot be read as silence or engagement). A negative value is an undeclared post, reported and not a failure. | 5 |
| 2 | **The closure notice** on proposal thread `99b57d27` (or ship-wide): the fix is live, and everyone is invited to re-raise lost proposals (Ezri, Atlas: one ship-wide call, not a private invitation). Yeoman collects the re-raised proposals into one digest for the Captain, deduplicated by title, oldest first. | the Ward Room thread; Improvement Proposals after the notice | The notice exists and is later than the deploy; Yeoman's digest exists after it. | crew addition (closure must notify the crew) |
| 3 | **DrillCalendar slots** for the recurring reconciliation (Tucker) and the reconciliation itself (Nova, owner), at a cadence of **daily at the longest**: `events.db` keeps 7 days and 100000 rows and Ward Room threads 7 days (30 if endorsed), so a longer window compares data that no longer exists (L13). Nova reports null results explicitly. | DrillCalendar; Nova's report in the Ward Room | A slot exists; a report (a null result included) follows each slot; a missing report is the alarm. | crew addition (reconciliation spec 3; scheduling) |
| 4 | **The Medical audit, pre-registered before the fix lands** (Keiko): Medical decisions with proposal language (notebook and DM history) against Improvement Proposals posts; run before and after the fix; empty lists reported as a bounded null. | Medical's notebooks and DMs; Improvement Proposals | After the fix every decided item has a matching post; the run before the fix is the baseline and is expected to show the loss. | crew addition |
| 5 | **The participation check** (Ezri): after the fix, ask the crew directly, rather than infer from volume; watch proposal rates and flag it if participation stays flat. | the crew's answers; Improvement Proposals | Ezri reports; a flat rate is flagged. | crew addition |

**Decisions for the Captain, with my recommendation.** (a) Whether the billet is strong enough: decide after row 1; if `dropped` rows with `no_response` are many for decisions on `single_call`, strengthen the wording (one string in `action_billets.py`); the build does not decide it. (b) Whether by-design notebook suppressions (AD-550, AD-552) count toward the crew's "zero": recommended yes as dropped and marked `by_design`, reported apart, so the identity holds. (c) Whether `[NO_RESPONSE]` beside a reply, a DM or an endorsement should also be read (L4): recommended no, until measured. (d) A BF for L2 (BF-032's similarity gate, BF-197's guard and BF-105's reply guard never match): recommended to file it, and to measure before fixing it, since fixing it starts suppressing posts and replies the gate was meant to suppress (the orchestrator allocates the number). (e) Whether to close #1673 with S3's commit (`Closes`) or after items 1 to 5: acceptance 5 is a live measurement, so the closure comment should hand over this table.





