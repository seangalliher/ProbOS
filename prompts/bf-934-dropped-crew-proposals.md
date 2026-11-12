# BF-934 (#1673): A proactive think whose triage decided to file a proposal or write a notebook entry is carried through to the output, no gate discards an action the output carries, and every intended action is carried out or recorded as dropped

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-11
**Revised by:** orchestrator, 2026-11-12: the anchor of S1's `DECISIONS.md` pair (P3-2) and the sentences above that BF-935's merge made untrue (Status, Base blobs, Dependencies, Which text describes the head, Tracker anchors), after BF-935's merge, and A1-38 to A1-42 (S2's `DECISIONS.md` anchor, and the sentences of section 16 that said no S2 or S3 anchor moves) after the oracle found that A1-15 moves S2's anchor.
**Amended by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-12: amendment A1 of slice S1, after review round 1 (NOT READY: F1 a P2, F2 and F3 two P3s). Section 16 holds its decisions (D-A, D-B, D-C), the recorded limits L17 and L18, the gates and the properties; section 6 gains the tests T11 to T18 and section 9 the mutation rows 48 to 52. It corrects D1's rows 1 to 3, S1's `DECISIONS.md` bullet G1 (in S1's M3 block below) and L15, adds one assertion to S3's registry test, and moves the counts: S1's test file has 34 cases after A1 (22 at M2) and the three files 34 + 26 + 43 = 103; sections 4 and 6 say so. Every other count in this document, and the Estimated tests of the Dependencies line below, is the M1 and M2 build's.
**Amended by (A3):** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-12: amendment A3 of slice S2, after review round 1 (NOT READY: F1, F2 and F3, three P2s). Section 17 holds its decisions (D-E, D-F, D-G, D-H), the repeated-cycle matrix, the recorded limits L19 to L22, the gates and the properties; section 6 gains the tests T14 to T23 and section 9 the mutation rows 53 to 72. It amends D3's order and re-reflect rows, L2 and L8, one line of S3's reconciliation test (a third cycle's proposal needs another title) and the counts: S2's test file has 37 cases after A3 (26 at M2) and the three files 34 + 37 + 43 = 114; sections 4 and 6 say so. Every other count in this document, and the Estimated tests of the Dependencies line below, is the M1 and M2 build's.
**Amended by (A4):** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-12: amendment A4 of slice S2, after review round 2 (NOT READY: G1 and G2 two P2s, G3 a P3). Section 18 holds its decisions (D-I, D-J, D-K), the corrected matrix rows, the recorded limits L23 to L26, the gates and the properties; section 6 gains the tests T24 to T28 and section 9 replaces the rows 62 to 64 and 66, amends row 61 and adds the rows 73 to 80. It amends in place the sentences that described the reply guard as a likeness that runs before the commands (section 3's reader paragraph, 17.1, 17.3, 17.10, the `challenge` row of 17.4, L8, L19 and L22) and D3's AD-643b row, and moves the counts: S2's test file has 45 cases after A4 (37 after A3, 26 at M2) and the three files 34 + 45 + 43 = 122; sections 4 and 6 say so. Every other count in this document, and the Estimated tests of the Dependencies line below, is the M1 and M2 build's, as A3 left it.
**Amended by (A5):** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-12: amendment A5 of slice S2, after review round 3 (NOT READY: H1 a P2, H2 to H4 three P3s) and the brake that followed it (continue, narrowly). Section 19 holds its decisions (D-L, D-M), the run table, the recorded limits L27 and L28 (L23 and L25 amended in place), the gates and the properties; section 6 gains the tests T29 to T35 and section 9 amends the rows 61, 63, 73, 74, 75, 78 and 80 and adds the rows 81 to 88. It amends in place the sentences that described the reply guard's comparison without the content firewall's label (18.2, L23) and the sentences that round 3 found wrong (L8, L26 and the enumerations of 18.7), and moves the counts: S2's test file has 73 cases after A5 (45 after A4, 37 after A3, 26 at M2) and the three files 34 + 73 + 43 = 150; sections 4 and 6 say so. Every other count in this document, and the Estimated tests of the Dependencies line below, is the M1 and M2 build's, as A3 and A4 left it.
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

**Size.** The document is about 190 KB at M2 and about 210 KB with section 16 (A1), most of it code: the blocks of section 7 are about 28 KB (S1), 33 KB (S2) and 39 KB (S3), with 6, 13 and 19 pairs in the M2 milestones (11, 17 and 23 blocks in all, new files and tracker pairs included), under the cap of about 25 pairs per milestone.

**The one-line version of each decision (section 3 ranks the options).** S1: give the decision to the single call (a billet), do not make `proposal` and `notebook` run the chain. S2: read a valid block beside `[NO_RESPONSE]`, extract before the similarity and novelty gates (as the Ward Room pipeline already does), let a re-reflect refine and never remove. S3: record the decision and each loss as EventLog rows (`category="intended_actions"`), no new `EventType`, no new store.

## 3. Decisions

Each is the Architect's, taken in Delegated AD Execution Mode: the options are ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; the first is taken. None weakens a security, governance, privacy or audit control, crosses the OSS and commercial boundary, or changes a stored format (S3 adds two kinds of EventLog row, see D2); each rolls back by reverting its slice. The Captain's decisions that remain are in section 15.

### D1. Route the decision (acceptance 1; the issue says it is the Architect's call)

| Rank | Option | LLM calls per decision | Prompt | Every other intended-action set | When the chain or the call fails | Verdict |
|---|---|---|---|---|---|---|
| 1 | The single call receives the decision and a billet (`decision_billet`, S1) | 2 (triage, single call): the route these decisions already take | the billet is 550 characters (notebook), 730 (proposal), 899 (both) and up to 1062 with both blocks and the four chat tags (`len(decision_billet(...))`); the user message grows by 389 to 901 characters in a free-form think and by 482 to 994 in a duty think, net of the closing lines it replaces (162 characters for the two lines of a free-form think, 69 for the one line of a duty think, each with its newline), measured on A1's text | none: `["silent"]` never reaches the call; `["oracle_query"]`, `["leadership_review"]`, `["speak_freely"]` alone, and any set with no `proposal` or `notebook`, leave the prompt byte for byte as before (tested: T2 the closing line and no heading, T18 byte for byte, seven sets, with and without a duty); a set with a communication action still runs the chain, whose COMPOSE shows its own billet | a chain that fails and falls back to the single call hands the decision in, because the key is set as soon as the triage ends (tested); a call that fails or answers silence leaves the decision dropped with `think_failed` or `no_response` (S3) | **Taken** |
| 2 | `proposal` and `notebook` become chain triggers (add them to `_COMM_ACTIONS`) | up to 5: the triage's ANALYZE, then ANALYZE, COMPOSE, EVALUATE and REFLECT, because Phase 2a re-runs the whole chain (`:6552-6554`); EVALUATE and REFLECT make no model call when a bypass applies (a Captain message, an @mention or a DM; boot camp; the low trust band: `evaluate.py:498-574`, `reflect.py:416-490`), so 3 at the low trust band, against 2 today | COMPOSE's billet, read from the second ANALYZE, a second sample of the triage | changes every set with either tag; a proposal-only decision would also compose an observation post nobody decided; COMPOSE has no notebook billet; one existing test pins one of the two tags out of the trigger set: `test_ad1347_s4_chain_lookup.py::test_a_lookup_with_no_communication_action_reads_nothing` pins `['notebook','ward_room_lookup']` to no chain, so it fails if `notebook` joins; nothing existing pins `proposal` out (the 50 cases of that file and of `test_ad643a_intent_routing.py` passed with `proposal` added to `_COMM_ACTIONS` and failed once with `notebook` added too: the orchestrator's run on `f25e9a8b`), and `test_ad643a_intent_routing.py::test_comm_actions_defined` is a source scan for the four tags that passes either way | a failing chain still falls back to a single call that does not know the decision | Rejected |
| 3 | Option 2 with the triage's ANALYZE result reused, so COMPOSE reads the decision that was made | up to 4 (2 at the low trust band) | as 2 | as 2 | as 2 | Rejected: `SubTaskExecutor.execute` keeps no memo of prior results, so it needs a new cache in the hot path of every chain, for a decision whose action needs no chat post |

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
| order of the extraction | 1 | The extraction runs before BF-032 and AD-493 (after BF-172), as the Ward Room pipeline's does (`ward_room_pipeline.py:288-318`: extraction, then BF-197, then AD-493): any block attached to a repeated observation is carried out, and the repeat itself is still not posted. A repeated output therefore repeats the actions it carries, so each repeat-sensitive action keeps, or gets, its own guard (A3, 17.4). A block-only output exits at BF-215 as before | **Taken** |
| | 2 | Exempt proposals from the two gates | Rejected: one tag, two branches; notebooks and every other block stay lost |
| | 3 | Leave the order | Rejected: it is the defect |
| `[NO_RESPONSE]` | 1 | The gate asks `carries_actionable_block(text)` (a proposal the extractor can file, or a notebook entry with a body): if so the output is read for blocks, and the observation stays withdrawn (nothing of it is posted) | **Taken** |
| | 2 | Strip the marker and post what is left | Rejected: posts prose the model withdrew |
| | 3 | Ask for every block type | Rejected here: replies, DMs and endorsements may follow a "nothing to add" answer by design and the issue names neither (L4) |
| the AD-643b re-reflect | 1 | May refine, never remove: if the rewrite lacks an action marker the approved output carried (silence included), or leaves a proposal that the extractor could file unfileable (A3: `_actions_lost` asks `parse_proposal_block`; the other five tags stay marker-level, L20), the approved output is kept and a WARNING names the lost tags; the feedback still reaches the episode (`_undeclared_action_feedback` stays on the observation) | **Taken** |
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
| AD-643b | `test_trigger_learning`, `test_combo_c_ad573c_note`, the two AD-1270 files | the six marker patterns and their order; a rewrite of an output without markers replaces it | unchanged: `_ACTION_MARKERS` holds the same six patterns in the same order; the guard acts when a marker is lost, and (A3) also when the approved output's proposal could be filed and the rewrite's cannot although its marker is kept (`_actions_lost` returns `["proposal"]`, as when the Rationale is dropped; the other five tags stay marker-level, L20) |
| AD-412 | `test_proactive` (`TestProposalExtraction`, `TestHandleProposeImprovement`), `test_ad632d_compose_handler`, `test_bf213_proactive_action_vocabulary` | a valid block is posted through the router; no Title or no Rationale is not posted and the tags are stripped; a raising handler leaves the tags stripped and no `proposal` entry | unchanged: they filter entries by `type == "proposal"` and assert "not posted, tags stripped", which stays true; none asserts the entry list is empty |
| AD-651a | `test_ad651a_compose_billet`, `test_bf213_proactive_action_vocabulary`, `test_bf186_compose_standing_orders` | COMPOSE's billet; `"BF-213"` absent from `_build_proactive_compose_prompt` | untouched: COMPOSE is not edited; S1's test pins `PROPOSAL_FORMAT` equal to COMPOSE's block |
| BF-032, AD-493 | `test_proactive`, `test_proactive_quality`, `test_bf201_thread_post_cap`, `test_bf237_pipeline_post_budget`, `test_ad493_novelty_gate` | each gate's verdict | none pins the gate order or the DEBUG wording |
| the think cycle | the 13 files naming `_think_for_agent` | `MagicMock` results whose `.metadata` is a `MagicMock` | `settle_intended_actions` reads metadata only when it is a `dict` |
| AD-1195, AD-1343 | `test_ad1195_eventlog_pair_freeze` (and three siblings), `tests/fixtures/ad1343_seam_registry.py` | the frozen EventLog pairs; `_think_for_agent` as the function that calls `handle_intent` | updated by S3 P2-17 (two resolved pairs); `_think_for_agent` is neither renamed nor wrapped |

### D5. Trackers and the ledger

`PROGRESS.md` and `DECISIONS.md` get one entry per slice (M3, anchors above), then the ledger generator (G3). The roadmap's Bug Tracker is not edited, as in BF-961's contract; the Architect handles the closure comment (section 15).

**Readers of the contracts A3 changes** (enumerated by `rg`, 17.11). The dict `WardRoomService.endorse` returns has three readers: `process_endorsements` (two callers, the think and the Ward Room pipeline) and the two HXI routes in `routers/wardroom.py`, which return it as their JSON body, so the new key `changed` is additive for them (`ui/` reads neither `voter_direction` nor the new key). `handle_propose_improvement` has one caller in `src` (the extractor, `proactive.py`) and answers one new refusal, `{"success": False, "error": "Proposal already filed", "duplicate_of": <thread id>}`. `_extract_and_execute_replies` serves the think and the pipeline, so a reply that says word for word what the agent's newest post in the thread says (A4; A3 compared word sets) is skipped for both, after the commands it carries have run, which are carried out for both. `_actions_lost` has one caller, the re-reflect guard; `_action_markers_in`, `_ACTION_MARKERS` and `_detect_undeclared_actions` do not change, and S3's blocks read none of them. S3's reconciliation test filed the same proposal twice, so one of its lines changes (A3-30).

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

  (2) `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the S1 file 34 passed after A1 (22 at M2); every other file 0 failed and collected counts equal M0; the check clean.
- **G2 (S2).** (1) the S1 and S2 files and every file that names `_think_for_agent`, `_extract_and_execute_actions`, `_detect_undeclared_actions`, `_re_reflect_with_feedback`, the `[PROPOSAL]` block, BF-032 or AD-493's gate:

```
PY -m pytest tests/test_ad1077_group_chat_coaching.py tests/test_ad1157_notebook_classification.py tests/test_ad1228_standing_interest_e2e.py tests/test_ad1228_standing_interests.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1343_stop_crossing.py tests/test_ad1346_admission_shadow_routing.py tests/test_ad1346_admission_store_writes.py tests/test_ad1347_s2_chain_tags.py tests/test_ad1347_s4_chain_lookup.py tests/test_ad437_action_space.py tests/test_ad529_contagion_firewall.py tests/test_ad550_notebook_dedup.py tests/test_ad617b_per_agent_token_budget.py tests/test_ad632d_compose_handler.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad643a_intent_routing.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py tests/test_ad651a_compose_billet.py tests/test_ad654a_async_dispatch.py tests/test_ad654d_internal_emitters.py tests/test_ad666_sensorium.py tests/test_ad868_self_originated_crew.py tests/test_ad924_group_chat_trigger.py tests/test_ad927_outputs_folder.py tests/test_ad928_show_your_work.py tests/test_bf201_thread_post_cap.py tests/test_bf213_proactive_action_vocabulary.py tests/test_bf237_pipeline_post_budget.py tests/test_bf238_post_budget_telemetry.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf874_dm_e2e.py tests/test_bf903_ward_room_scope.py tests/test_bf925_event_log_window.py tests/test_bf934_s1_decision_routing.py tests/test_bf934_s2_secondary_gates.py tests/test_circuit_breaker.py tests/test_combo_a_ad576b_retry.py tests/test_combo_c_ad573c_note.py tests/test_duty_schedule.py tests/test_onboarding.py tests/test_proactive_quality.py tests/test_proactive.py tests/test_records_store.py tests/test_recreation_channels.py tests/test_self_monitoring.py tests/test_trigger_learning.py tests/test_ward_room.py -q -n 0 -p no:randomly
```

  (2) the architecture check. **Expected:** the S1 file 34 (A1) and the S2 file 73 (26 at M2, 37 after A3, 45 after A4, 73 after A5) passed (A4 adds no file to the command: the files that call the reply extractor are in it already, 18.7); every other file 0 failed and collected counts equal M0; the check clean. **After A3** the command also names, each at its alphabetical place, `tests/test_ad1346_admission_store_writes.py` (after `tests/test_ad1346_admission_shadow_routing.py`), `tests/test_bf903_ward_room_scope.py` (after `tests/test_bf874_dm_e2e.py`) and `tests/test_ward_room.py` (after `tests/test_trigger_learning.py`): the files that name `.endorse(`, `process_endorsements` or `handle_propose_improvement` and were not in it. M0 records their collected counts before A3 is applied. **After A5** the command also names `tests/test_ad529_contagion_firewall.py` (after `tests/test_ad437_action_space.py`): the one file that builds the Ward Room's two stores with the content firewall wired and pins the label they put on a flagged body (19.6); 39 cases by `rg -c "^\s*(async )?def test_" tests/test_ad529_contagion_firewall.py`, expected 39 passed. M0 records its collected count before A5 is applied.
- **G2 (S3).** (1) the three new files, the AD-1195 and AD-1343 files, the files that name `_build_result_metadata` or `_post_to_ward_room`, and the think and routing files:

```
PY -m pytest tests/test_ad1195_durable_event_seam.py tests/test_ad1195_durable_producers.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_ad1228_standing_interest_e2e.py tests/test_ad1228_standing_interests.py tests/test_ad1248_slice_a_crossing.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1295_tool_success_ledger.py tests/test_ad1343_stop_crossing.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1346_admission_shadow_routing.py tests/test_ad1347_s4_chain_lookup.py tests/test_ad1357_context_manifest.py tests/test_ad1358_s1_head_to_head.py tests/test_ad617b_per_agent_token_budget.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad641a_observability_bridge.py tests/test_ad643a_intent_routing.py tests/test_ad644_phase1_duty_context.py tests/test_ad644_phase2_innate_faculties.py tests/test_ad666_sensorium.py tests/test_bf069_llm_health.py tests/test_bf198_router_proactive_dedup.py tests/test_bf688_chain_priority_inheritance.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf874_dm_e2e.py tests/test_bf925_event_log_window.py tests/test_bf934_s1_decision_routing.py tests/test_bf934_s2_secondary_gates.py tests/test_bf934_s3_intended_actions_ledger.py tests/test_circuit_breaker.py tests/test_combo_a_ad576b_retry.py tests/test_duty_schedule.py tests/test_onboarding.py tests/test_proactive.py -q -n 0 -p no:randomly
```

  (2) the architecture check. **Expected:** the S1, S2 and S3 files 34 (A1), 73 (A3, A4 and A5) and 43 passed; every other file 0 failed and collected counts equal M0; the check clean (the freeze test passes with the two new pairs).
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

Four new files: `tests/bf934_world.py` (the shared world; no test of its own) and one test module per slice. In each module the functions before the classes pass on both trees (S1's A1 adds one function before its classes that fails on S1's M3 head: T17, below); the classes carry `pytest.mark.xfail(raises=AssertionError, strict=True)` until M2 removes the marker. No BF-934 name is imported at module level (a module M2 builds is imported by `_built`, which fails at its own assert until then).

### S1: `tests/test_bf934_s1_decision_routing.py` (22 cases at M2, 34 after A1; 6 pass and 16 xfail at M1)

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
| T11 | 1 | Class (A1), F1 at the seam: a triage whose tags carry two made-up identifiers, a chain that cannot run and a model that cites both: the single call is not shown them (the heading and the proposal format still are) and its reply is suppressed as `confabulation_detected` (`test_identifiers_the_triage_made_up_do_not_ground_a_reply_that_cites_them`) | none (arrives with its fix) |
| T12 | 5 | Class (A1), F1 unit: a tag that is none of the six changes nothing: an identifier, free text, `ward_room_lookup`, `silent`, an integer (`test_a_tag_that_is_not_one_the_billet_names_changes_nothing`) | none |
| T13 | 1 | Class (A1): the billet names each decided tag by its own constant, normalised, in their order, and the companions line likewise (`test_the_billet_names_each_decided_tag_by_its_own_constant_in_their_order`) | none |
| T14 | 1 | Class (A1), F2: a dict decided on again by a turn with no triage (no executor) is not told the older decision and loses the key (`test_a_dict_decided_on_again_by_a_turn_with_no_triage_is_not_told_the_older_decision`) | none |
| T15 | 1 | Class (A1), F2: a decision-cache hit leaves no older decision on the dict; the test clears the three module caches when it ends (`test_a_decision_cache_hit_leaves_no_older_decision_on_the_dict`) | none |
| T16 | 1 | Control (A1): the routing function clears an older decision itself when its triage fails (`test_the_routing_function_clears_an_older_decision_itself_when_its_triage_fails`) | none (passes on S1's head) |
| T17 | 1 | Pin (A1): the six tags the billet names are the six the ANALYZE prompts offer for them (`test_the_tags_a_billet_names_are_the_six_the_analyze_prompts_offer_for_them`) | none (fails on S1's head at `BILLET_TAGS`) |
| T18 | 1 | Control (A1): a decision with no block leaves `_build_user_message` byte for byte as it was, for seven sets, with and without a duty, the clock set aside (`test_a_decision_with_no_block_leaves_the_message_byte_for_byte_as_it_was`) | none (passes on S1's head) |

**How each xfail case fails on the base.** T4 at `assert await threads(w, "Improvement Proposals") == [...]` (the model answered the silence it defaults to, so no thread); T5 to T7 at `assert DECIDED in prompt` (the base prompt has no heading); T8 to T10 at the `_built` helper's own assert (the module does not exist). The controls and T2, T3 pass on the base.

**How each A1 case fails on S1's head (`f25e9a8b`), measured in memory.** T11 at `assert not any(word in prompt for word in made_up)` (the made-up identifiers are in the prompt); T12, all five, at the equality of the two billets; T13 at its first assert (the head names the tags in the triage's order and repeats `frobnicate`); T14 at `assert len(model.requests) == 1 and DECIDED not in model.requests[0].prompt` (the heading is in the prompt); T15 at `assert "_intended_actions" not in reused` (its premise holds: the second turn hit the cache and made no model call); T17 at `billets.BILLET_TAGS` (an AttributeError: the constant is A1's). T16 and T18 pass on the head. With the test pairs alone: 34 collected, 24 passed, 10 failed (expected); with the source pairs too: 34 passed.

### S2: `tests/test_bf934_s2_secondary_gates.py` (26 cases; 5 pass and 21 xfail at M1; 37 after A3; 45 after A4; 73 after A5)

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
| T14 | 1 | Control (A3): a flipped endorsement still credits its author (`test_control_a_flipped_endorsement_still_counts_for_its_author`) | none |
| T15 | 1 | Control (A3): a reply that says something new is still posted, and another author's identical reply does not hold it back (`test_control_a_reply_that_says_something_new_is_still_posted`) | none |
| T16 | 1 | Control (A3): a proposal with another title, or by another author, is still filed (`test_control_a_proposal_with_another_title_or_by_another_author_is_still_filed`) | none |
| T17 | 1 | Control (A3): a proposal the extractor never could file does not hold a rewrite back (`test_control_a_proposal_the_extractor_never_could_file_does_not_hold_a_rewrite_back`) | none |
| T18 | 1 | Class (A3): the Ward Room says whether an endorsement changed the stored vote (`test_the_ward_room_says_whether_an_endorsement_changed_the_stored_vote`) | A3 |
| T19 | 1 | Class (A3): a repeated endorsement earns its author trust once, through the real Ward Room and a real `TrustNetwork` (`test_a_repeated_endorsement_earns_its_author_trust_once`) | A3 |
| T20 | 1 | Class (A3): a reply repeated on every cycle is posted once (`test_a_reply_repeated_on_every_cycle_is_posted_once`) | A3 |
| T21 | 1 | Class (A3): a proposal repeated by its author is filed once, and says why (`test_a_proposal_repeated_by_its_author_is_filed_once_and_says_why`) | A3 |
| T22 | 1 | Class (A3): a thread of another shape is no evidence of a repeat; another author's, a deleted and a nested post (`test_a_thread_of_another_shape_is_no_evidence_of_a_repeat`) | A3 |
| T23 | 2 | Class (A3): a re-reflect may not leave a proposal the extractor cannot file: the Rationale gone, the tags in lower case (`test_a_re_reflect_may_not_leave_a_proposal_the_extractor_cannot_file`) | A3 |
| T24 | 1 | Class (A4): a reply that changes one value of a longer text is posted, not suppressed as a repeat (`test_a_reply_that_changes_a_value_is_posted`) | A4 |
| T25 | 1 | Class (A4): a reply the agent took back is posted when it comes back; only the newest post counts (`test_a_reply_the_agent_took_back_is_posted_when_it_comes_back`) | A4 |
| T26 | 4 | Class (A4): a repeated reply still carries out the new `[MOVE]` or `[CHALLENGE]` it brings and its prose is posted once, through the think and through the Ward Room pipeline (`test_a_repeated_reply_still_carries_out_the_command_it_brings`) | A4 |
| T27 | 1 | Control (A4): a reply that differs only in case and spacing is still a repeat (`test_control_a_reply_that_differs_only_in_case_and_spacing_is_still_a_repeat`) | none |
| T28 | 1 | Class (A4): the helper's boundaries: the newest live post, a deleted newest, a tie, punctuation kept, no words, another author (`test_only_the_agents_newest_live_post_is_the_one_a_reply_repeats`) | A4 |
| T29 | 10 | Class (A5): a reply repeated on every cycle is posted once whatever the content firewall made of it (plain, one reason, two reasons, a label echo, a flagged label echo), through the think and through the Ward Room pipeline, with the firewall wired as `startup/finalize.py` wires it; the first stored body is asserted first (`test_a_reply_repeated_on_every_cycle_is_posted_once_whatever_the_firewall_made_of_it`) | A5 (6 of the 10 rows: the flagged ones) |
| T30 | 2 | Control (A5): a flagged reply that changes a value is still posted, and its repeat is not (`test_a_flagged_reply_that_changes_a_value_is_still_posted`) | none |
| T31 | 12 | Class (A5): the body the Ward Room stores reads as the body it was given: plain, one reason, two reasons, a label echo, a flagged label echo (also after spaces), padded, multi-line, Unicode, bracket-prefixed, 6,000 characters, fabricated metrics from a low-trust author; the label is asserted first (`test_the_body_the_ward_room_stores_reads_as_the_body_it_was_given`) | A5 (5 of the 12: the flagged ones) |
| T32 | 1 | Class (A5): the label on a thread body is the one the helper removes (`test_the_label_on_a_thread_body_is_the_one_the_helper_removes`) | A5 |
| T33 | 1 | Class (A5): every leading label goes, with the spacing after it (`test_every_leading_label_goes_and_the_spacing_after_it`) | A5 |
| T34 | 1 | Class (A5): nothing that is not a leading label is touched (`test_nothing_that_is_not_a_leading_label_is_touched`) | A5 |
| T35 | 1 | Class (A5): removing the labels twice changes nothing (`test_removing_the_labels_twice_changes_nothing`) | A5 |

**How each xfail case fails on the base.** T4 to T7 at the assert on the Ward Room's threads or the notebook file (the base discards the block with the observation); T8 at `assert sorted(await threads(w)) == ...` (the rewrite replaced the output, so the proposal is not filed); T9 and T10 at `assert {"type": "proposal_suppressed", ...} in actions`; T11 at `assert "1 more [PROPOSAL] block(s)" in caplog.text`; T12 and T13 at the `_built` helper's own assert.

**How each A3 case fails on S2's M3 head** (the test pairs of A3 alone: 37 collected, 30 passed, 7 failed, each at its own assert; T14 to T17 pass on both trees and are not marked). T18 at the equality of the flags (`v.get("changed")` is `None`); T19 at `assert seen[1] == pytest.approx(seen[0])` (the author is credited again); T20 at the list of Kira's posts in the thread (three, not one); T21 at `assert await threads(w, "Improvement Proposals") == [POSTED]` (three threads); T22 at `assert repeats is not None` (the helper is A3's); both rows of T23 at the sorted titles (the rewrite replaced the approved output, so no proposal is filed). Apply A3-15 to A3-18 first for the red run, then the source pairs.

**How each A4 case fails on S2's A3 head** (the test pairs of A4 alone: 45 collected, 38 expected to pass and 7 to fail; T27 passes on both trees and is not marked). T24 at the list of Kira's posts (the 49 C reply was suppressed as a repeat of the 41 C reply: one post, not two); T25 at the same list (the third reply, which says what the first said, was suppressed: two posts, not three); the four rows of T26 at the games assert after the posts assert, which passes (`[MOVE 5]`: `moves_count` 0, not 1; `[CHALLENGE ...]`: no game, not one: the repeated reply was skipped with its command); T28 at its first assert (older X, newer Y, a reply that says X: the head says True). Apply A4-5 to A4-8 first for the red run, then the source pairs.

**How each A5 case fails on S2's A4 head** (the test pairs of A5 alone: 73 collected, 58 expected to pass and 15 to fail, each failure at an assert of its case and none at a setup; T30, the plain and label-echo rows of T29 and the seven unflagged rows of T31 pass on both trees and are not marked). The six flagged rows of T29 (one reason, two reasons and a flagged label echo, through each caller) at the count of Kira's posts (`[1, 2, 2]`, not `[1, 1, 1]`: the second copy is posted, and the third equals it); the five flagged rows of T31 (one reason, two reasons, a flagged label echo, the same after spaces, fabricated metrics) at their second assert (`read(stored) == read(body)`; the first, that the stored body is the label and the body, passes); T32 at `assert strip is not None` after its first assert, which passes; T33 to T35 at the same assert (the helper is A5's). Apply A5-5 to A5-7 first for the red run, then the source pairs.

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
- *G1 (the routing).* The single call receives `intended_actions` and a billet when `proposal` or `notebook` was decided; the chain is not made to run for them. Rejected: adding the two tags to `_COMM_ACTIONS` (up to 5 model calls where 2 run today, 3 at the low trust band, where EVALUATE and REFLECT make no call; COMPOSE's billet read from the second ANALYZE, an observation nobody decided, no notebook billet; one existing test, `test_a_lookup_with_no_communication_action_reads_nothing`, pins `notebook` out of the chain's triggers and none pins `proposal` out, as the orchestrator's run of the 50 cases of the two AD-643a trigger files measured at review round 1); reusing the triage's ANALYZE (a new cache in every chain).
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
- *Residual.* L1, L7, L11, L14, L15, L17 and L18 of the contract. *Reversal.* Revert the BF-934 slice 1 commits (M1 to M3 and A1); reverting the A1 commit alone restores the billet that repeats the triage's tags and the single clear in the routing function.
```
REPLACE:
```
- *Residual.* L1, L7, L11, L14, L15, L17 and L18 of the contract. *Reversal.* Revert the BF-934 slice 1 commits (M1 to M3 and A1); reverting the A1 commit alone restores the billet that repeats the triage's tags and the single clear in the routing function.

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
            def another(request):  # A3: the same title again would be refused as a duplicate: the author already filed it
                return obeys_decision(request).replace("Cache the roster", "Index the roster")

            for answer in (obeys_decision, lambda request: "[NO_RESPONSE]", another):
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
        assert set(ACTION_TAGS) == set(_built("probos.cognitive.action_billets").BILLET_TAGS)  # the six S1's billet names (A1): two definitions, pinned equal
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
| 1 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `observation.pop("_intended_actions", None)` | `pass` | T16 (1) |
| 2 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `observation["_intended_actions"] = intended_actions` | `pass` | T4, T5 (5), T6, T7 (8), T11 (9) |
| 3 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `_decided = decision_billet(observation.get("_intended_actions"))` | `_decided = ""` | T4, T5 (5), T6, T7 (8), T11 (9) |
| 4 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `elif not _decided:` | `else:` | T5 (5) |
| 5 | S1 M2 | src/probos/cognitive/cognitive_agent.py | `if not _decided:` | `if True:` | T6 (1) |
| 6 | S1 M2 | src/probos/cognitive/action_billets.py | `if not any(tag in tags for tag in _BLOCK_TAGS):` | `if False:` | T2 (3: oracle_query, leadership_review, speak_freely), T10 (5), T18 (1) |
| 7 | S1 M2 | src/probos/cognitive/action_billets.py | `if "proposal" in tags:` | `if False:` | T5 (3: proposal, both, silent+proposal), T7, T9, T11 (6) |
| 8 | S1 M2 | src/probos/cognitive/action_billets.py | `if "notebook" in tags:` | `if False:` | T5 (3: notebook, both, notebook+lookup), T9 (4) |
| 9 | S1 M2 | src/probos/cognitive/action_billets.py | `"Title: <short descriptive title>\n"` | `"Title: <short title>\n"` | T8 (1) |
| 10 | S1 M2 | src/probos/cognitive/action_billets.py | `_BLOCK_TAGS = ("proposal", "notebook")  # the tags whose block the single call has no other reason to write` | `_BLOCK_TAGS = ("proposal",)` | T5 (2: notebook, notebook+lookup), T9, T13, T17 (5) |
| 11 | S2 M2 | src/probos/proactive.py | `if not response_text or ("[NO_RESPONSE]" in response_text and not carries_actionable_block(response_text)):` | `if not response_text or "[NO_RESPONSE]" in response_text:` | T4 (3), T5 (1) |
| 12 | S2 M2 | src/probos/proactive.py | `if _withdrawn:` | `if False:` | T5 (1) |
| 13 | S2 M2 | src/probos/proactive.py | `if isinstance(posted, dict) and posted.get("success") is False:` | `if False:` | T10[refused], T21 (2) |
| 14 | S2 M2 | src/probos/proactive.py | `reason = f"post_failed: {type(exc).__name__}"` | `reason = ""` | T10[raises] (1) |
| 15 | S2 M2 | src/probos/proactive.py | `if reason:  # BF-934: a decision that cannot be filed is said, with the agent and why, and recorded as an entry` | `if False:` | T9[no Title, no Rationale], T10, T21 (6) |
| 16 | S2 M2 | src/probos/proactive.py | `actions_executed.append({"type": "proposal_suppressed", "reason": "malformed_block"})` | `pass` | T9[malformed] (1) |
| 17 | S2 M2 | src/probos/proactive.py | `if proposal.extra_blocks:` | `if False:` | T11 (1) |
| 18 | S2 M2 | src/probos/cognitive/proposal_block.py | `problem = "missing_title" if not title else "missing_rationale" if not rationale else ""` | `problem = ""` | T9[no Title, no Rationale], T12[the same two], T23[the Rationale gone] (5) |
| 19 | S2 M2 | src/probos/proactive.py | `return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])` | `return parse_proposal_block(text).valid` | T4[notebook] (1) |
| 20 | S2 M2 | src/probos/proactive.py | `return parse_proposal_block(text).valid or bool(split_notebook_blocks(text)[1])` | `return bool(split_notebook_blocks(text)[1])` | T4[proposal], T5 (2) |
| 21 | S2 M2 | src/probos/cognitive/cognitive_agent.py | `if lost:` | `if False:` | T8, T23 (4) |
| 22 | S2 M2 | src/probos/cognitive/cognitive_agent.py | `return [tag for tag in _action_markers_in(compose_output) if tag not in declared]` | `return []` | T3, T17 (2: the two re-reflect controls) |
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
| 48 | S1 A1 | src/probos/cognitive/action_billets.py | `named = [tag for tag in BILLET_TAGS if tag in tags]  # the constant for each decided tag, never the triage's own string` | `named = tags` | T11, T12 (5), T13 (7) |
| 49 | S1 A1 | src/probos/cognitive/cognitive_agent.py | `observation.pop("_intended_actions", None)  # BF-934: the key holds this turn's triage or nothing; a dict that is decided on again never carries an older decision in` | `pass` | T14, T15 (2) |
| 50 | S1 A1 | src/probos/cognitive/action_billets.py | `BILLET_TAGS = (*_BLOCK_TAGS, *_COMPANION_TAGS)` | `BILLET_TAGS = _BLOCK_TAGS` | T13, T17 (2) |
| 51 | S1 A1 | src/probos/cognitive/action_billets.py | `companions = [tag for tag in _COMPANION_TAGS if tag in tags]  # constants again, in their order` | `companions = []` | T13 (1) |
| 52 | S1 A1 | src/probos/cognitive/action_billets.py | `f"Before this step you decided to take these actions: {', '.join(named)}.",` | `join(named)` becomes `join(tags)` | T11, T12 (5), T13 (7) |
| 53 | S2 A3 | src/probos/ward_room/messages.py | `return {"net_score": row[0] if row else 0, "voter_direction": final_direction, "changed": False}  # BF-934: the vote already held` | `"changed": True` in place of `"changed": False` | T18, T19 (2) |
| 54 | S2 A3 | src/probos/ward_room/messages.py | `return {"net_score": net_score, "voter_direction": final_direction, "changed": changed}` | `"changed": True` in place of `"changed": changed` | T18 (1) |
| 55 | S2 A3 | src/probos/ward_room/messages.py | `changed = existing_direction is not None  # BF-934: an unvote with no vote to remove changes nothing` | `changed = True` | T18 (1) |
| 56 | S2 A3 | src/probos/ward_room/messages.py | `changed = True` | `changed = False` | T14, T18, T19 (3) |
| 57 | S2 A3 | src/probos/ward_room_router.py | `if not result["changed"]:` | `if False:` | T19 (1) |
| 58 | S2 A3 | src/probos/ward_room_router.py | `if filed.author_id == author_id and " ".join(filed.title.split()).casefold() == wanted:` | `if False:` | T21 (1) |
| 59 | S2 A3 | src/probos/ward_room_router.py | the line of row 58 | `if " ".join(filed.title.split()).casefold() == wanted:` | T16 (1) |
| 60 | S2 A3 | src/probos/ward_room_router.py | `wanted = " ".join(f"[Proposal] {title}".split()).casefold()` | `wanted = f"[Proposal] {title}"` | T21 (1) |
| 61 | S2 A3 | src/probos/proactive.py | `if repeats_own_reply(thread, agent.id, reply_body):` | `if False:` | T20 (1), T26 (4), T27 (1), T29 (10), T30 (2): 18 |
| 62 | S2 A4 | src/probos/proactive.py | `if post.get("author_id") == author_id and not post.get("deleted"):` | `if not post.get("deleted"):` | T15, T22, T28 (3) |
| 63 | S2 A4 | src/probos/proactive.py | `return " ".join(strip_unverified_label(str(text or "")).split()).casefold()` | `return " ".join(strip_unverified_label(str(text or "")).split())` | T27, T28 (2) |
| 64 | S2 A4 | src/probos/proactive.py | the line of row 62 | `if post.get("author_id") == author_id:` | T22, T28 (2) |
| 65 | S2 A3 | src/probos/proactive.py | `stack.extend(post.get("children", []))` | `pass` | T22 (1) |
| 66 | S2 A4 | src/probos/proactive.py | `return bool(wanted) and newest is not None and all(text == wanted for stamp, text in own if stamp == newest)` | `any(text == wanted for stamp, text in own)` in place of `all(text == wanted for stamp, text in own if stamp == newest)` | T25, T28 (2) |
| 67 | S2 A3 | src/probos/proactive.py | `logger.debug("BF-934: the repeated-reply check failed; the reply is allowed", exc_info=True)` | `raise` | T22 (1) |
| 68 | S2 A3 | src/probos/cognitive/cognitive_agent.py | `unfileable = parse_proposal_block(original).valid and not parse_proposal_block(rewrite).valid` | `unfileable = False` | T23 (2) |
| 69 | S2 A3 | src/probos/cognitive/cognitive_agent.py | the line of row 68 | `unfileable = not parse_proposal_block(rewrite).valid` | T17 (1) |
| 70 | S2 A3 | src/probos/cognitive/cognitive_agent.py | `lost = _actions_lost(original_result.get("llm_output", ""), new_output)` | `lost = []` | T8, T23 (4) |
| 71 | S2 A3 | src/probos/cognitive/cognitive_agent.py | `kept = _action_markers_in(rewrite)` | `kept = []` | T3, T17 (2) |
| 72 | S2 A3 | src/probos/cognitive/cognitive_agent.py | `return [tag for tag in _action_markers_in(original) if tag not in kept or (tag == "proposal" and unfileable)]` | `return [tag for tag in _action_markers_in(original) if tag not in kept]` | T23 (2) |
| 73 | S2 A4 | src/probos/proactive.py | the line of row 63 | `return strip_unverified_label(str(text or "")).casefold()` | T27, T28 (2) |
| 74 | S2 A4 | src/probos/proactive.py | `newest = max((stamp for stamp, _ in own), default=None)` | `newest = min((stamp for stamp, _ in own), default=None)` | T25 (1), T28 (1), T30 (2): 4 |
| 75 | S2 A4 | src/probos/proactive.py | the line of row 66 | `all(text == wanted for stamp, text in own)` in place of `all(text == wanted for stamp, text in own if stamp == newest)` | T28 (1), T30 (2): 3 |
| 76 | S2 A4 | src/probos/proactive.py | the line of row 66 | `any(text == wanted for stamp, text in own if stamp == newest)` in place of `all(text == wanted for stamp, text in own if stamp == newest)` | T28 (1) |
| 77 | S2 A4 | src/probos/proactive.py | the line of row 66 | `return newest is not None and` in place of `return bool(wanted) and newest is not None and` | T28 (1) |
| 78 | S2 A4 | src/probos/proactive.py | `own.append((post.get("created_at") or 0.0, _as_read(post.get("body", ""))))` | `own.append((0.0, _as_read(post.get("body", ""))))` | T28 (1), T30 (2): 3 |
| 79 | S2 A4 | src/probos/proactive.py | the line of row 61 | `match.group(2)` in place of `reply_body` | T26 (4) |
| 80 | S2 A4 | src/probos/proactive.py | the line of row 66 | `all(text[:24] == wanted[:24] for stamp, text in own if stamp == newest)` in place of `all(text == wanted for stamp, text in own if stamp == newest)` | T24 (1), T30 (2): 3 |
| 81 | S2 A5 | src/probos/proactive.py | the line of row 63 | `return " ".join(str(text or "").split()).casefold()` | T29 (6), T31 (5): 11 |
| 82 | S2 A5 | src/probos/proactive.py | `wanted = _as_read(body)` | `wanted = " ".join(str(body or "").split()).casefold()` | T29 (4): 4 |
| 83 | S2 A5 | src/probos/proactive.py | the line of row 78 | `own.append((post.get("created_at") or 0.0, " ".join(str(post.get("body", "") or "").split()).casefold()))` | T29 (8): 8 |
| 84 | S2 A5 | src/probos/ward_room/content_firewall.py | `_LEADING_LABELS_RE = re.compile(r"^\s*(?:" + re.escape(_UNVERIFIED_LABEL) + r"[^\]]*\]\s*)+")` | `r"[^\]]*\]\s*)")` in place of `r"[^\]]*\]\s*)+")` | T29 (2), T31 (2), T33 (1), T35 (1): 6 |
| 85 | S2 A5 | src/probos/ward_room/content_firewall.py | the line of row 84 | `r"^(?:"` in place of `r"^\s*(?:"` | T31 (1), T33 (1): 2 |
| 86 | S2 A5 | src/probos/ward_room/content_firewall.py | `_UNVERIFIED_LABEL = "[UNVERIFIED \u2014 "` | `_UNVERIFIED_LABEL = "[UNVERIFIED "` | T34 (1): 1 |
| 87 | S2 A5 | src/probos/ward_room/content_firewall.py | the line of row 84 | `r"\s*(?:"` in place of `r"^\s*(?:"` | T34 (1): 1 |
| 88 | S2 A5 | src/probos/ward_room/content_firewall.py | `return _LEADING_LABELS_RE.sub("", body)` | `return body` | T29 (6), T31 (5), T32 (1), T33 (1): 13 |

The Id in "Killed by" is the slice's own (section 6). Each row kills at least one case of the slice's new test file alone (counts are what the hand run measured; under pytest they are "expected"). Run by hand against the patched modules (no pytest), each mutant fails exactly the cases it names; this is not a campaign of record: the Builder runs the 47 rows once, each on its slice's M2 head, with that slice's new file alone, and reports any row that survives. Rows 29 and 30, 36 and 37, 42 and 43 share a line. Not tabulated: the gate order itself (no one-line mutant reorders a block; cases T6 and T7 of S2 fail on the base tree, which is that mutant), the controls, the `isinstance(metadata, dict)` guard of `settle_intended_actions` (it is for the `MagicMock` results of existing tests, which G2 runs) and the `data` payload of the `declared` row other than `agent_id`.

A3 adds rows 53 to 72, each on S2's A3 head and killed by S2's file alone (counts measured by hand; under pytest they are expected), and amends the killers of rows 13, 15, 18, 21 and 22, which the new cases also fail; rows 11, 12, 14, 16, 17, 19, 20, 23 and 24 fail exactly the cases they failed before. Rows 58 and 59, and 68 and 69 share a line each (A4 replaced rows 62 to 64 and 66, below). The runner's row count (`len(rows) in (47, 52)`) becomes 72 after A3 and 80 after A4. Not tabulated: the `continue` and the DEBUG line of `process_endorsements` (a log line; row 57 kills the branch), `limit=100`, and the WARNING text of the re-reflect guard (unchanged).

A4 replaces rows 62 to 64 and 66 (the comparison is equality against the agent's newest post, so A3's Jaccard line and its threshold are gone), amends the killers of row 61 and adds rows 73 to 80, each on S2's A4 head and killed by S2's file alone (counts measured by hand; under pytest they are expected). Rows 63 and 73 share a line, as do rows 62 and 64, rows 66 and 75 to 77 and 80, and rows 61 and 79. Rows 65 and 67 are unchanged. Not tabulated: the `continue` and the DEBUG line of the new call (a log line; row 61 kills the branch) and `str(text or "")` (a post whose body is missing).

A5 amends the killers of rows 61, 74, 75, 78 and 80, which A5's new cases also fail (row 61: T29 and T30 join its six cases; rows 74, 75, 78 and 80: T30 joins), the line of row 63 and the mutant of row 73, because A5 changed `_as_read`'s line (the helper is inside it now), and adds rows 81 to 88, each on S2's A5 head and killed by S2's file alone (counts measured by hand with the in-memory runner of 19.9: not pytest, so "expected" under pytest; the killers are written as per-test counts that add up to the row's total, so that the runner can read them). Rows 63, 73 and 81 share a line, as do rows 78 and 83, and rows 84, 85 and 87. The other rows of 61 to 80 fail exactly the cases they failed after A4 (measured). The runner's row count becomes 88 after A5 (80 after A4). **The campaign of record** for rows 61 to 67 and 73 to 88 is the in-memory run of 19.9 over the A5 tree (the files named there by blob), with S2's 45 reply-path cases (3 of them need `caplog` and were not served); a Builder whose files carry those blobs need not repeat it, and rows 11 to 24, 53 to 60 and 68 to 72 are untouched.

## 10. Recorded limits

- **L1. Not run under pytest.** This contract was checked by an in-memory script, not by pytest (a read-only consult). Unchecked: the real collection and fixtures (`tmp_path` on disk, the real `caplog`); the git-backed `RecordsStore` on disk (the script used an in-memory stand-in that returns the real `check_notebook_similarity` answer shape and the real reason text `content unchanged from recent entry`, `records_store.py:1193`); xdist and suite order; the existing suite (the files of each G2); the checker's command (its `check()` function was run in memory); any live model. About 60 test files scan the whole `src` tree by `rglob` (a grep of `tests`); they were not run, and not read one by one: the new code uses none of the constructs the censuses I read look for (a subprocess, the environment, a file write, `aiosqlite.connect`, a task, a network call), the AD-1195 and AD-1270 censuses were checked by running or reading (section 11), and the broad gate runs the rest. Every count in sections 4, 6 and 9 is "expected".
- **L2. BF-032's similarity gate can never match in production (found, not fixed; a new BF for the orchestrator to allocate).** `_is_similar_to_recent_posts` (`proactive.py:2970`) calls `ward_room.get_recent_activity(ch.id, limit=10, since=None)` (`:2990-2991`) whose SQL is `created_at > ?` (`ward_room/threads.py:386`), so `since=None` returns no rows; and the items it returns carry `author` (the callsign) and no `author_id`, so `author == agent.id` never holds. Run against a real Ward Room service that held the agent's own identical post, `get_recent_activity(since=None)` returned `[]`, an item had a callsign and no `author_id`, and the check returned `False`. The same function backs the pipeline's BF-197 guard (`ward_room_pipeline.py:309`) and BF-105's reply guard (`proactive.py:4099`). `since=None` is also passed at `:4047` (not examined). Consequence here: S2's ordering test stubs the verdict (`AsyncMock(return_value=True)`). In production BF-032 discards nothing and AD-493 judged the raw output against the observations the agent had posted and recorded, so before S2 an output whose observation matched one of them lost every action it carried, and after S2 it carries every action out on every cycle that repeats it: what stops a repeat is each action's own guard, enumerated in 17.4. A3 adds three (the vote, the reply, the proposal title) and records the rest (L19).
- **L3. `_run_cycle` logs a think's exception at DEBUG** (`proactive.py:1154-1160`), unchanged. A think that raises after its `declared` row leaves no `dropped` row: an unexplained gap, which the reconciliation reports as the alarm it is meant to be.
- **L4. `[NO_RESPONSE]` is read for blocks only beside a proposal or a notebook entry** (the issue's two). A withdrawn output that carries a `[REPLY]`, `[DM]` or `[ENDORSE]` is still read as silence; `carries_actionable_block` is the one place to widen it, if the Captain wants.
- **L5. REFLECT's own rewrite is unchanged** (the issue's Sage case, 1 of 31): a REFLECT that answers `[NO_RESPONSE]` for an output carrying a proposal is a model decision inside the chain. It is now visible (a `declared` row, then a `dropped` row with `no_response`).
- **L6. Proactive thinks only.** `record_declared` writes for `intent == "proactive_think"`. The Ward Room notification path (`ward_room_pipeline.py:293`) shares `_extract_and_execute_actions`, so it gains the proposal WARNINGs and the `proposal_suppressed` entry (which it discards) but writes no row.
- **L7. No triage, no row.** A decision served from the decision cache or by procedural replay makes no triage (`decide`, `:3736`): no `declared` row, and no billet is needed.
- **L8. What an entry does not prove.** `endorse` is recorded as executed when the extractor ran it, though `process_endorsements` swallows `ValueError` and every other exception at DEBUG (`ward_room_router.py:1183-1187`), and (A3) though the vote may be the one the Ward Room already held, which earns no trust; the reply extractor skips, at DEBUG, an unresolved or a locked thread, BF-105, BF-171 and BF-201 (these run before the commands in the reply: L24), and then, after them, a reply that says word for word what the agent's newest post says (A3, A4: `repeats_own_reply`, at DEBUG) and one the post budget refuses (BF-237, **at WARNING**: `rg -n "BF-237: Suppressing additional \[REPLY\]" src/probos/proactive.py` finds the one line), so a reply that did not land is dropped as `no_block_executed` with its cause in the log, at DEBUG for every skip but the budget's (each level run in A5, 19.4, except BF-105, which is dead, L2: its level is read). S3 counts whether an entry exists, not whether the effect landed, for those tags. A proposal the router refuses as a duplicate is a `proposal_suppressed` entry that S3 counts as a dropped proposal with that reason, at WARNING (L21).
- **L9. Placeholders.** A model that echoes the format's `<short descriptive title>` files a proposal with that title: the parser accepts any non-empty Title and Rationale.
- **L10. One proposal per output; a tag-level post.** A second `[PROPOSAL]` block is logged and not filed (AD-412's first-block rule, unchanged); `_post_to_ward_room` says whether a thread was created, not what it holds.
- **L11. The proposal format is written twice:** COMPOSE's AD-651a billet (its line holds an em dash that an ASCII SEARCH cannot carry, so `compose.py` is not edited) and `PROPOSAL_FORMAT`. S1's T8 pins them equal and fails if either changes alone.
- **L12. The registry classifies five tags by name only** (`silent`, `speak_freely`, `leadership_review`, `oracle_query`, `ward_room_lookup`: carried out by something else, each with a `how` text): their effects are not tested here. A tag a future ANALYZE prompt offers fails the registry test until it is classified; a tag outside the registry is counted nowhere.
- **L13. Volume and retention are unmeasured.** One `declared` row per proactive think whose triage intends a block or a post, one `dropped` row per lost action. `events.db` prunes at 7 days and 100000 rows (`EventLogConfig`) and Ward Room threads at 7 days, 30 if endorsed (`ward_room/threads.py:853`): a reconciliation window longer than 7 days compares data that no longer exists, so its cadence is daily at the longest (section 15).
- **L14. The decision recorded is the triage's, the path the planned one.** Phase 2a re-runs the whole chain, ANALYZE included, so COMPOSE's AD-651a billet reads a second sample of `intended_actions`; the `declared` row and the accounting use the first. `data.path` is `chain` when `has_comm_action and execute_steps` at the decision, even if the chain later falls back to the single call.
- **L15. The billet's wording and the real models.** The seam tests use a model that obeys the decision it is shown. Whether the real models do, and whether "the decision stands" is strong enough, is the live re-measure's question (section 15). The billet is 550 to 1062 characters (`len(decision_billet(...))`: 550 for a notebook entry, 730 for a proposal, 899 for both, 1062 with both blocks and the four chat tags), and the user message grows by 389 to 901 characters in a free-form think and by 482 to 994 in a duty think, net of the closing lines it replaces (measured on A1's text, in memory).
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

1. **S1.** `decision_billet` returns `""` unless `proposal` or `notebook` is among the normalised tags; with no decision on the observation `_build_user_message` produces the text it produced before, for the duty branch and the other (trace both; T18 pins it byte for byte). The key is popped at the start of `decide` (before the cache, the procedural replay and the external chain) and again before the triage, and set after `_extract_intended_actions`; trace a chain that falls back (`_execute_chain_with_intent_routing` returns `None` or `decide` falls through): the key is still on the observation when `_build_user_message` runs. No new chain-executing method exists (AD-1270's census).
2. **S1.** The billet asks for the blocks the extractors read: `PROPOSAL_FORMAT` equals the text between `AFTER your observation text:\n` and `The proposal will be automatically posted` in COMPOSE's billet, and `NOTEBOOK_FORMAT` is a block `_NOTEBOOK_PATTERN` reads.
3. **S2.** `parse_proposal_block` reads a valid block exactly as the inline parser did (Title, Rationale with continuation lines, Affected Systems, Priority) and says a problem for every other text; the strict pattern is the old one (`PROPOSAL_PATTERN`); the extractor files from the first block only, says why when it does not, no longer counts a refusal as filed, and still strips every block (the `re.sub(proposal_pattern, ...)` after it is untouched).
4. **S2.** `carries_actionable_block` is true only for a proposal the extractor can file or a notebook entry with a body. Without one, `[NO_RESPONSE]` returns exactly as before. With one, `_withdrawn` is set, the text is emptied after the extraction, and BF-215 ends the think (trace: no working-memory record, no post, the duty recorded).
5. **S2.** After the move (and, with a repeated output repeating its actions, see the matrix of 17.4), nothing between BF-172 and the post reads `response_text` assuming the old order: BF-032 and AD-493 see the text left after extraction; the novelty gate's `record` is reached only when the observation is posted, as before.
6. **S2.** In `_re_reflect_with_feedback` `lost` is `_actions_lost(approved, rewrite)`: the markers of the approved output that the rewrite lacks, and `proposal` also when the approved block parses valid and the rewrite's does not (A3); the early return is inside the `try`; the caller still stores `_undeclared_action_feedback`, so the episode enrichment is unchanged; `_detect_undeclared_actions` returns what it returned for every input (same six patterns, same order).
7. **S3.** `settle_intended_actions` runs at every return of `_think_for_agent` that follows the handling of the result (failure, `[NO_RESPONSE]`, BF-172, BF-215, BF-032, AD-493, the post), with the reason of that exit; the returns before the result exists make no decision and need none. It never raises (`try` around each write; `isinstance(metadata, dict)` for `MagicMock` results).
8. **S3.** `record_declared` runs once per triage, before the chain or the call, for `proactive_think` only, with `correlation_id` the intent id; the loop settles with the same `intent.id` (a `dropped` row's correlation id is one of the `declared` rows', asserted in T13).
9. **S3.** `_post_to_ward_room` returns `True` only after a thread is created, `False` for no channel and for DM-only text; its callers ignore the result except the think.
10. **S3.** The two pairs added to `_RESOLVED_PAIRS` are the two the census finds through `CATEGORY`, `DECLARED_EVENT` and `DROPPED_EVENT`; the freeze test passes without another change (the literal count stays 37).
11. **All.** No new method on `CognitiveAgent`, `ProactiveCognitiveLoop` or `WardRoomService` (the checker's `srp-size` rows are unchanged); no `aiosqlite.connect`; no task is created; every new function is typed; no new config field. The three-tier rule: the row writes and the metadata copy are log-and-degrade; nothing here swallows silently.
12. **Tests.** The helper and the three files import no BF-934 name at module level; every case that needs a module M2 builds goes through `_built`; the world closes what it opens and clears the three caches; no test sleeps, reads the network or relies on another test.

## 14. Acceptance criteria

1. G1 gave the expected counts at each slice's M1 (S1 6 passed and 16 xfailed, S2 5 and 21, S3 18 and 25) and the `--runxfail` failures stopped at an assert of the case.
2. At each M2 the new file passes in full (22, 26 and 43 cases; S1's file has 34 after A1 and S2's 37 after A3, 45 after A4 and 73 after A5) with the markers removed; every other file of that slice's G2 has 0 failures and a collected count equal to M0; the architecture check is clean; the AD-1195 freeze test passes (S3).
3. The 47 rows of section 9 each fail at least one case of the slice's new file alone, on that slice's M2 head; rows 48 to 52 (A1) each fail at least one case of S1's file alone, on S1's A1 head; rows 53 to 88 (A3; A4 replaced rows 62 to 64 and 66 and added rows 73 to 80; A5 amended rows 61, 63, 73, 74, 75, 78 and 80 and added rows 81 to 88) each fail at least one case of S2's file alone, on S2's A5 head.
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

## 16. Amendment A1 (review round 1 of slice S1, 2026-11-12)

Review round 1 of the S1 candidate (head `f25e9a8b`) returned NOT READY: F1 (P2, ordinary reach, a regression), F2 (P3, injected-only, a regression) and F3 (P3, documentation: three facts overstated in the new claims). A1 is one more commit on the branch, after M3. It changes `action_billets.py` and one line of `decide`, adds 12 cases to S1's test file (ten of them fail on the head), amends the S1 entries of `PROGRESS.md` and `DECISIONS.md`, corrects sentences of this document and adds one assertion to S3's registry test. S2 and S3 are not built: the one S2 or S3 pair that changes is S2's P3-2, whose anchor is the last bullet of S1's entry in `DECISIONS.md`, the residual line that A1-15 amends (A1-38 moves it; 16.3), and every other anchor they use is untouched (16.3). Line numbers in this section are S1's head's (`f25e9a8b`); the rest of this document's are `fe488971`'s. This section holds prose and tables only, because a SEARCH/REPLACE fence cannot carry a fenced block.

### 16.1 What each finding was, and what A1 does

| Finding | What | Reach | A1 |
|---|---|---|---|
| F1 P2 | `decision_billet` echoed every tag of `intended_actions`, which are a model's free text (`_extract_intended_actions` keeps whatever ANALYZE wrote). BF-922's gate (`_gate_fallback_output`) counts the whole prompt as shown to the call, so an identifier the triage made up, named in the billet, made a reply that cites it pass BF-204 (two or more distinct hex identifiers the call was not shown). Reproduced at the seam: two made-up identifiers, a chain that cannot run, a model that cites both: the base suppressed the reply as `confabulation_detected`, S1's head let it through | ordinary: a triage's free text, a fallback to the single call | D-A: the billet names a decision only by constants (`BILLET_TAGS`) |
| F2 P3 | the key was cleared only inside the routing function, so a dict decided on again by a turn that never enters it (no executor, a decision-cache hit, a procedural replay, an external chain) kept an older turn's decision and the single call was told it | injected-only: every caller of `decide` builds its dict with `perceive` (16.3) | D-B: the key is also cleared at the start of `decide()` |
| F3 P3 | three facts stated in D1, in S1's bullet G1 and in L15 were wrong or overstated: the calls the rejected option costs, the tests that pin the chain's triggers, the size of the billet | documentation | D-C: corrected, every copy (16.4) |

### 16.2 D-A. What the billet may repeat (F1)

| Rank | Option | Verdict |
|---|---|---|
| 1 | The billet writes the constant of `BILLET_TAGS` (the six tags it has a format or a standing order for: `proposal`, `notebook`, `ward_room_post`, `ward_room_reply`, `endorse`, `dm`) for each tag the triage named, in their order, and repeats no other string | **Taken**: the text is a function of which of six constants are present, so no model text can reach the prompt or the grounding gate; no new vocabulary; the definition sits in the module that writes the text; S1 imports nothing from S3 |
| 2 | A closed list of all eleven ANALYZE tags, echoed when present | Rejected: a second copy of S3's registry, and it tells the call about tags it is not asked to act on (`oracle_query` ran in the triage, `ward_room_lookup` is read only when a chat action will use it (AD-1347 S4), and `silent` beside a decided proposal contradicts "carry it out") |
| 3 | BF-922's gate is told to ignore the billet | Rejected: a shared safety control would have to know whose text each part of a prompt is, and the next text added to a prompt would need the same exemption |
| 4 | A recorded limit | Rejected: a regression with ordinary reach, one the review reproduced |

**Where the vocabulary lives, one definition or two.** `BILLET_TAGS` in `action_billets.py` is the six tags the billet writes. S3's `ACTION_TAGS` (`action_accounting.py`) classifies eleven tags for accounting, six of them with evidence. They are two definitions of the same six names for two purposes, and S1 cannot import S3. They are pinned from both sides: S1's T17 pins `BILLET_TAGS` to the six and to the tags both ANALYZE prompts offer, and A1 adds one assertion to S3's registry test (A1-27) that S3's six equal `BILLET_TAGS`. L17 records the cost. **What the billet says afterwards.** The first sentence names the decided tags by constants, in their order (`proposal`, `notebook`, `ward_room_post`, `ward_room_reply`, `endorse`, `dm`); the companions line likewise; nothing else in the text changes, and its length does not for a set with no tag outside the six (550, 730, 899, 833). **An unknown tag** is omitted from the prompt without a trace in it (L18); S3's `declared` row records the triage's own list, so accounting loses nothing. **Other model text in a prompt that S1 adds:** none; every string of `action_billets.py` is a literal and the only input is the tags (read whole), and the one reader of the key is `_build_user_message`.

### 16.3 D-B. The key's lifetime (F2)

| Rank | Option | Verdict |
|---|---|---|
| 1 | Clear the key at the start of `decide()`; the routing function keeps its own clear | **Taken**: every branch of `decide` (the cache, the procedural replay, the external chain, the routing, the single call) starts without an older decision; the routing function owns the key it sets, and a direct call of it (the AD-643a and AD-1347 tests make them) gets the same guarantee; T14 and T15 pin the start of `decide`, T16 the routing function |
| 2 | Consume the key where `_build_user_message` reads it | Rejected: S3's metadata (P2-16) and S1's own T5 read the key after the call, a formatter would mutate its input, and `_run_llm_fallback` reads the same dict a second time |
| 3 | A recorded limit | Rejected: one line, and S3's reader would take an older decision for the turn's |

**Reach, enumerated** (`rg -n "\.decide\(|_decide_via_llm\(|def decide\b" src`; `rg -n -B6 "self\.decide\(observation\)" src/probos`): `CognitiveAgent.decide` is reached from `handle_intent`'s lifecycle (`cognitive_agent.py:7571` `observation = await self.perceive(intent)`, then `:7601` `self.decide(observation)`), from `super().decide(observation)` in `builder.py:2609`, `scout.py:548`, `utility/web_agents.py:377` and `:627` and `utility/stored_list.py:97` (each hands on the dict it received), and from the `self.decide(observation)` of the agents in `agents/` (each follows its own `perceive`); `perceive` returns a new dict at every call (`:2979`). `_decide_via_llm` is called from `decide` (`:3883`), from `_build_guided_decision` (`:2503`, on `dict(observation)`, reached from `decide` through `_check_procedural_memory`) and from `_run_llm_fallback` (`:5771`, called at `:7940` on the dict `decide` filled in the same turn). No caller reuses a dict across turns. **Paths, after the clear:** a decision-cache hit returns with no key (T15); a procedural replay returns before any read, and a guided one copies the cleared dict; an external chain starts without it and, if it falls back, the single call reads none; `_run_llm_fallback` reads this turn's key if the chain ran, and none otherwise. **S2's and S3's anchors in `cognitive_agent.py`:** S2's P2-10 (`# BF-922 (#1639): set on the observation while a single call answers for a chain`), P2-11 and P2-12; S3's P2-14 (the import line S1 adds), P2-15 (`has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))`) and P2-16 (`# AD-1357 (#1749): the reply's context manifest, LAST, so that BF-805's greedy`). None includes a line A1 changes (A1 edits the end of `decide`'s docstring and the guard after it, and no import); S3's reader (P2-16) runs after `decide`, so it sees this turn's key or none. **S2's and S3's anchors in `DECISIONS.md` and `PROGRESS.md`:** S2's P3-2 anchors on the last bullet of S1's entry, the residual line, which A1-15 amends, so A1-38 moves S2's anchor (its SEARCH and the first line of its REPLACE) onto the amended line; S3's P3-2 anchors on the last bullet of S2's entry, which A1 does not change; every P3-1 anchors on the title line of `PROGRESS.md` and the blank line after it, which A1-12 (a bullet inside S1's entry) does not change.

### 16.4 D-C. The corrected sentences, and every copy of the three facts

What I ran: `rg -n -e "model calls where|two existing tests|\b550\b|\b730\b|\b899\b|\b1062\b|5 model calls|re-runs the whole chain|chain.s triggers|pin the chain"` over the contract, `DECISIONS.md` and `PROGRESS.md`; `rg -n -o -e ".{0,100}\b(model calls?|LLM calls?|five calls|4 calls|5 calls|extra call|second call|a second sample|second sample)\b.{0,100}"` over the contract; I read both tests (`tests/test_ad1347_s4_chain_lookup.py:218-230`, `tests/test_ad643a_intent_routing.py:347-354`), `sub_task.py:62-66` (the calls each type makes), the bypasses (`evaluate.py:498-574`, `reflect.py:416-490`) and Phase 2a of the routing function (`:6559`), and measured `len(decision_billet(x))` and the growth of `_build_user_message` in memory over A1's text.

| Fact | Where it stood | Now |
|---|---|---|
| the calls the rejected option costs | D1 row 2 (5) and row 3 (4); S1's bullet G1 in this document (P3-2) and in `DECISIONS.md` ("5 model calls where 2 run today") | up to 5 (up to 4 for row 3): the triage's ANALYZE, then ANALYZE, COMPOSE, EVALUATE and REFLECT; EVALUATE and REFLECT make no model call under a bypass (a Captain message, an @mention or a DM; boot camp; the low trust band), so 3 at the low trust band (2 for row 3), against 2 today |
| the tests that pin the chain's triggers | D1 row 2; S1's bullet G1 (here and in `DECISIONS.md`): "two existing tests pin the chain's triggers" | one test pins `notebook` out (`test_a_lookup_with_no_communication_action_reads_nothing` pins `['notebook','ward_room_lookup']` to no chain); none pins `proposal` out; `test_comm_actions_defined` is a source scan for the four tags and passes either way (the orchestrator's run on `f25e9a8b`: 50 cases passed with `proposal` added, one failed with `notebook` added too) |
| the size of the billet | D1 row 1 (+550, +730, +899) and L15 (550 to 899) | 550, 730 and 899 characters, up to 1062 with both blocks and the four chat tags; the user message grows by 389 to 901 (free-form think) and by 482 to 994 (duty think), net of the closing lines it replaces (162 characters for two lines, 69 for one) |

The other statements of the facts that the commands found are true and are left alone: L14 and section 11's CLAIM about Phase 2a (the second ANALYZE is a second call); section 11's measured lengths (`["proposal"]` 730, `["notebook"]` 550, both 899, `["ward_room_post","proposal"]` 833), which A1 does not change because it changes no length for a set with no tag outside the six; D1's statement that the closing line stays for the other sets, which T2 tested for three of them and T18 now tests byte for byte for seven. Before A1, `PROGRESS.md` stated none of the three facts; its new bullet for A1 (A1-12) states the calls and the test protection.

### 16.5 Tests (S1's file: 12 new cases, 34 in all)

T11 to T18 are in section 6. Ten fail on S1's head: T11 (F1 at the seam), T12 (five, F1 unit), T13, T14 (F2), T15 (F2, the cache) and T17 (at `BILLET_TAGS`: the constant is A1's); T16 (the routing function's own clear) and T18 (the closing line, byte for byte) pass on it. Expected: 34 collected, 10 failed and 24 passed with the test pairs alone, 34 passed with the source pairs too. Each test changes only what it creates: the world's databases on `tmp_path`, an attribute of the agent it builds, a per-world `SystemConfig` (T15) and the three module caches of `cognitive_agent.py`, which T15 clears when it ends (the world clears them when it opens). T18 sets the agent's `_build_temporal_context` to return nothing, because the message carries the clock to the second.

### 16.6 Mutation rows (section 9)

Rows 48 to 52 (S1 A1) are in section 9; each Line occurs once, stripped, in its file on S1's A1 head. Rows 1 to 3, 6, 7 and 10 gain the cases that now kill them (row 1's killer moves from T3 to T16, because `decide` now clears the key before the routing function does). The displaced mutant, the clear moved from the start of `decide` to after the cache lookup, is not a one-line mutation and so has no row: only T15 fails it (1 of 34, run in memory).

### 16.7 Gates for A1

- **M0.** `PY -m pytest --collect-only -q tests/test_bf934_s1_decision_routing.py` on the head: 22.
- **GA1.** Apply A1-7 to A1-11 only (the tests): `PY -m pytest tests/test_bf934_s1_decision_routing.py -q -n 0 -p no:randomly --tb=line`: **expected 34 collected, 10 failed, 24 passed**, the failures at the asserts named after the table in section 6. Then A1-1 to A1-6: **expected 34 passed**.
- **G2 (S1)** as written in section 4, the same command: the S1 file **34** passed; every other file 0 failed and its collected count equal to M0's; the architecture check clean (A1 adds no method and no class; the check compares counts and triggers of `srp-size` rows, which one more line in `decide` does not change).
- **Mutation rows:** S1's rows 1 to 10 and 48 to 52 with `mutants_bf934.py` (it asserts 47 rows: adapt it to 52).
- **G3** after the tracker pairs (A1-12 to A1-15): the orchestrator regenerates the ledger.

### 16.8 Recorded limits

- **L17. The six tags are defined twice.** `BILLET_TAGS` (S1: what the billet writes) and S3's `ACTION_TAGS` (what accounting needs evidence for) name the same six tags for two purposes. A tag the ANALYZE prompts come to offer fails S3's registry test until it is classified; S1 needs no change for it (the billet names the six only) and T17 stays green. The two are pinned to each other by S3's registry test (A1-27), which runs when S3 is built; between A1 and S3 only S1's side is pinned.
- **L18. An unrecognised tag is not shown to the single call.** A triage that names a tag outside the six (an invented one, or a lookup or flag such as `speak_freely`) leaves the billet without it: the call is told only what it can write. `oracle_query` has run in the triage, `ward_room_lookup` is dispatched only when a chat action will use it, `leadership_review` and `speak_freely` have no block, and S3's `declared` row records the triage's own list.

### 16.9 Diff Reviewer: properties to verify for A1

1. **The billet repeats no model text.** In `action_billets.py` every string is a literal, `named` and `companions` iterate `BILLET_TAGS` and `_COMPANION_TAGS`, and the input is only tested for membership (T12, T13, rows 48 and 52); at the seam T11 (BF-204 suppresses as at the base, the heading and the proposal format still given).
2. **The key's lifetime.** Cleared at the start of `decide` (before the cache, the procedural replay and the external chain), cleared again at the start of the routing function, set after `_extract_intended_actions`, read by `_build_user_message` and, in S3, by `_build_result_metadata` after the call. Trace the paths of 16.3: a cache hit (T15), no executor (T14), the routing function called directly (T16), the fallback (T7).
3. **The corrected claims.** 16.4: each sentence against the commands and the tests it names, and no other copy (the same `rg` over this document, `DECISIONS.md` and `PROGRESS.md`).
4. **The counts.** S1's file 34, the three files 103, G2's expectations in section 4, the rows of section 9 (1 to 10 and 48 to 52) against the runner.
5. **The tests.** Each new case fails on S1's head where section 6 says and passes after; T16 and T18 pass on both; T15 clears the three caches in a `finally`; T18 does not read the clock.
6. **S2's and S3's text.** S2's P3-2 anchors on the residual line that A1-15 amends: A1-38 moves that anchor. S3 gets one added assertion in the registry test (A1-27). No other S2 or S3 pair or anchor changed.

### 16.10 Verified (A1, 2026-11-12, the Architect; read-only, in memory, scratch directories removed afterwards; no pytest and no repository test)

The Part 1 pairs for `.py` files applied in label order to the LF blobs at `f25e9a8b` (every SEARCH once at its turn, at the start of a line, ASCII; every result compiles); the patched `action_billets.py` and `cognitive_agent.py` served over the real tree through a `sys.meta_path` finder; S1's file driven by a hand-made runner (parametrize, `tmp_path`, `async def`): the head's 22 cases pass; with the test pairs alone 34 collected, 24 passed, 10 failed; with all the pairs 34 passed; rows 1 to 10 and 48 to 52 each fail the cases the table names; the displaced mutant fails T15 only. `BILLET_TAGS` occurs nowhere in `src`, `tests`, `scripts` or `config` at the head. The `.md` pairs applied in label order to the LF blobs of the contract, `PROGRESS.md` and `DECISIONS.md` (the same checks). Unchecked: the real pytest, xdist and suite order (T15's caches and config are per test), the broad gate, the architecture checker's command, any live model.

## 17. Amendment A3 (review round 1 of slice S2, 2026-11-12)

### 17.1 What each finding was, and what A3 does

| Finding | What it was | What A3 does |
|---|---|---|
| F1 (P2, a regression) | an endorsement the Ward Room already holds credited its author on every cycle (the reviewer's run: three credits for one vote, alpha +0.1125): the extraction now runs on every output | `WardRoomService.endorse` says `changed`; `process_endorsements` awards trust only then (A3-1 to A3-6; T18, T19, T14) |
| F2 (P2, a regression) | a reply repeated on every cycle was posted each time past BF-171's 120 seconds (the reviewer's run: the parent 0 replies, the head 3), because BF-105's guard reads no posts (L2) | `repeats_own_reply` skips a reply that says what the agent's newest post says (A3-9 to A3-11; T20, T15, T22; A4 replaced A3's likeness by equality and moved the check, 18.2 and 18.3) |
| F3 (P2, not a regression) | a retained marker is not a retained executable proposal: a rewrite that keeps `[PROPOSAL]` and drops the Rationale, or writes the tags in lower case, replaced the approved output and nothing was filed | `_actions_lost` also loses `proposal` when the approved block could be filed and the rewrite's cannot (A3-12 to A3-14; T23, T17) |
| D-H (found by reading, not by the review) | a repeated proposal filed a thread per cycle: `handle_propose_improvement` had no duplicate check | the router refuses a proposal the author already filed under the same title (A3-7, A3-8; T21, T16) |

### 17.2 D-E. The vote says whether it changed

`endorse` returns `"changed"`: True for a new vote, a flip and an unvote that removed one; False for the vote already held and for an unvote with nothing to remove. `process_endorsements` skips the trust signal (and the `continue` skips nothing else: the net score was already read) when it is False. Rejected: the router reading the voter's vote first (a second query, and a race between the read and the write); no trust signal from the proactive path (it changes what AD-426's bridge means); a limit (ordinary reach, measured). The router is handed only `UP` and `DOWN` (`extract_endorsements`), so an unvote reaches `endorse` only through the HXI routes, which award no trust. The Ward Room pipeline calls the same function and stops crediting a repeated vote too.

### 17.3 D-F. A reply the agent already made

`repeats_own_reply(thread, author_id, body)` reads the thread `_extract_and_execute_replies` has already fetched (`WardRoomService.get_thread`: the posts as a tree, with `children`), and is true when the reply, as a person reads it (the case and the spacing aside, every other character kept), is the text of the agent's newest live (not deleted) post in it, at any depth (A4; A3 compared the word sets of every live post at a Jaccard of 0.6 through `jaccard_similarity` and `text_to_words`, which suppressed a changed value and a reply taken back: 18.2). It runs after the commands in the reply have run and the text is cleaned, before BF-237's budget (A4; A3 ran it before `_extract_commands_from_reply`, which discarded a new command: 18.3). It fails open on a thread of another shape. Persisted evidence: it survives a restart. Rejected: making `_is_similar_to_recent_posts` effective (BF-032, BF-197 and BF-105 would become live for every post: L2 stays); the novelty gate over each reply (it records no reply); an in-memory last reply per thread (lost at a restart). A skipped reply leaves no entry, like the other four skips (L8).

### 17.4 D-H. The repeated-cycle matrix

Every action `_extract_and_execute_actions` (`proactive.py:3122-3926`) and its helpers carry out, read tag by tag (line numbers are those of S2's M3 head, `8cae8376`). **The head:** what a repeat of the same output does in cycles 2 and 3. **The parent:** BF-032 discarded nothing (L2); AD-493 compared the raw output with the observations the agent had posted and recorded (`_post_to_ward_room` records the posted text, `proactive.py:3116-3119`) and discarded the whole output, actions included, when it matched; an output with no posted observation (actions only) was compared with nothing, so the parent repeated those too.

| Action | What a repeat does on the head | What stops it, and is it live | A3 |
|---|---|---|---|
| `endorse` (`:3162-3177`) | the vote is held (the Ward Room returns early and emits no event); the author was credited on every cycle (the reviewer's run); AD-428 adds one to the Communication skill's `exercise_count` each cycle, a counter written at `skill_framework.py:1500` and compared nowhere (`rg -n exercise_count src`: its storage and its serialisation only) | nothing before A3 | **guard**: `changed` (T18, T19) |
| `reply` (`:3180-3185`) | a post per cycle once BF-171's 120 seconds have passed | BF-105: dead (L2); BF-171: live, in memory, 120 s at the default tier; BF-201: live, the thread's 50 root posts | **guard**: `repeats_own_reply` (T20, T15, T22) |
| `proposal` (`:3573-3640`) | a thread in Improvement Proposals per cycle | nothing: `handle_propose_improvement` had no check | **guard**: the router's duplicate check (T21, T16) |
| `notebook` (`:3229-3537`) | declined: AD-550's `check_notebook_similarity` reads the persisted entry and answers `suppress` ("content unchanged from recent entry") for content with a Jaccard of 0.8 or more inside 72 hours (`records_store.py:1128-1215`) | AD-550, persisted; live: S2's T7 writes the entry once, S3's by-design case shows the second identical entry declined | nothing |
| `dm` (`extract_and_execute_dms`) | declined | BF-163 (60 s per sender and callsign) and AD-614 (Jaccard 0.6 against the pair's last body), both in memory; live: in memory, with BF-163's cooldown cleared between cycles, three identical DMs left one DM thread; with both guards cleared, as a restart does, three | nothing (a restart allows one repeat: L19) |
| `group_chat` (`:3202-3209`) | the service's per-agent cooldown and sliding-window cap | `threads/agent_group_chat.py:14` and `_rate_ok` (`:159-162`); read, not run | nothing |
| `artifact` (`:3211-3218`) | a new version of the same name each cycle (`ArtifactStore.add_version` assigns `MAX(version) + 1`; the blob is stored once), three a turn at most, and only for an agent with a task room | the per-turn cap only | L19 |
| `status` (`:3220-3227`) | a status message per cycle in the task room, three a turn at most | the per-turn cap only | L19 |
| `note` (AD-573c, `:3538-3572`) | a copy in the agent's own scratchpad, a bounded list (`working_memory.py:155-163`) | none; private and bounded | L19 |
| `read_notebook` (`:3529-3536`) | `_pending_notebook_reads[agent.id]` is overwritten | idempotent | nothing |
| `assign`, `handoff` (`:3774-3815`, `:3870-3903`) | a task event per cycle: `Dispatcher.dispatch` checks no cooldown and no repeat (its docstring) | none | L19 |
| `crew` (`:3816-3868`) | `open_or_resume` resumes an equivalent open session (`disposition` is `created`, `resumed` or `blocked`; `duplicate_resume_count`: `cognitive/crew_session.py:255-261`, `_resume_equivalent`) | the session service; read, not run | nothing |
| agent-work tags (AD-1347 S2, `:3906-3917`) | declined: `created.deduplicated` ("you already have open request ...": `agent_work_tags.py:407-410`, `:460`) | the work service | nothing |
| `challenge` (direct `:3649-3713`, and inside a reply) | a Recreation thread and a game per cycle: `create_game` refuses only the Captain's second game and a player against themself (`recreation/service.py:158-163`); inside a repeated reply it runs again, as in the parent (A4: the check judges the prose after the commands have run; A3's check ran first and skipped the command with the prose) | none | L19 |
| `move` | skipped by state: after the first move it is not the player's turn, and `make_move` refuses it | the game's state | nothing |

**Proposals.** Options: an in-memory recent-title check per agent (lost at a restart, state in the loop); a persisted check in `handle_propose_improvement` against the channel (**taken**: restart-safe, one query per filed proposal, one owner of "file a proposal"); a limit (rejected: a thread per cycle in the channel the Captain reads). The check: the same `author_id` and the same title, with the case and the spacing set aside, among `list_threads(channel, limit=100)`. The refusal is `{"success": False, "error": "Proposal already filed", "duplicate_of": <thread id>}`; the extractor's existing reading of a refusal makes the entry `{"type": "proposal_suppressed", "reason": "router_refused: Proposal already filed"}` and the WARNING of D2, with no change to the extractor. S3 counts that entry as a dropped proposal with that reason (L21): the identity `declared = posted + dropped` holds.

### 17.5 D-G. A marker kept is not a block kept

`_actions_lost(original, rewrite)` (`cognitive_agent.py`, after `_action_markers_in`) returns the tags of the original whose marker the rewrite lacks, and `proposal` also when `parse_proposal_block(original).valid` and not `parse_proposal_block(rewrite).valid`; the guard asks it and keeps the approved output when it is not empty. `_ACTION_MARKERS`, `_action_markers_in` and `_detect_undeclared_actions` do not change, so the detector's equivalence with the base (12,288 combinations, as the review measured) holds, and S3 uses none of them. Rejected: the same for every tag (the readings of five tags live in `proactive.py` and the router, which `cognitive_agent.py` cannot import: `proactive.py` imports `CognitiveAgent`); widening `_ACTION_MARKERS` (it changes what AD-643b calls undeclared). The five tags that stay marker-level are L20.

### 17.6 Tests

S2's file gains 11 cases (T14 to T23, section 6): four controls before the first class (they pass on both trees and are not marked) and two classes at the end, which S2's M3 head fails. The world's router holds a `MagicMock` for trust, so T19 and T14 build a router with the loop's own `TrustNetwork` (`_with_real_trust`); BF-171's cooldown is the one clock the reply path reads and `_elapse` clears it; nothing sleeps. A3-30 changes one line of S3's reconciliation test.

### 17.7 Mutation rows

Section 9: rows 53 to 72, and the killers of rows 13, 15, 18, 21 and 22 amended.

### 17.8 Gates for A3

- **G1 for S2.** `PY -m pytest tests/test_bf934_s2_secondary_gates.py -q -n 0 -p no:randomly` after the whole of A3: 37 passed. With A3-15 to A3-18 alone on S2's M3 head: 30 passed and 7 failed, each failure an `AssertionError` at an assert of its case (never a setup error); T14 to T17 are the controls that pass.
- **G2 for S2.** The command of section 4 with the three files of A3-25 added at their alphabetical places. **Expected:** the S1 file 34 and the S2 file 37 passed (after A3; 45 after A4: 18.7); every other file 0 failed and collected counts equal M0 (M0 also records the three added files); the architecture check clean.
- **G3.** The ledger generator, `--check` and `tests/test_ad1184_ad_ledger.py`: the ledger is regenerated by the orchestrator.

### 17.9 Recorded limits

- **L19. The matrix's unguarded and in-memory rows.** `assign`, `handoff`, `challenge` (direct, and inside a reply, where A4 lets it run again), `artifact`, `status` and `note` repeat once per cycle that repeats the tag; the DM guards are in memory, so a restart allows one repeat; group chats rely on the service's cap. Why not guarded here: no guard exists to reuse, each would be new state with a threshold of its own, the reach is bounded by the rank gates, the per-turn caps and the cycle cooldown, and the parent repeated them too whenever AD-493 did not match. A general idempotency key (tag, target and body, with a time to live, at the dispatch sites) is the fix, a new BF for the orchestrator to allocate. What A3 does not remove: a model that re-emits an ASSIGN on every cycle assigns on every cycle.
- **L20. The re-reflect guard is marker-level for five tags.** A rewrite that keeps the opening token of a notebook, endorse, reply, DM or note block and breaks the block (no closing tag, an empty body, no direction, an unbalanced bracket) replaces the approved output, and the block is not carried out (run, 17.11: each of the five; a `[DM @Worf]` with no closing tag is still carried out, the unclosed tier). Why: the readings of the five live in `proactive.py` and the router, which `cognitive_agent.py` cannot import; `parse_proposal_block` is the one shared parser. The consequence is the parent's, no worse, and it needs a model failure inside REFLECT.
- **L21. S3 counts a refused duplicate as a dropped proposal at WARNING.** The extractor's entry says `router_refused: Proposal already filed`; S3's `unaccounted` gives the drop that reason and logs it at WARNING, not marked by design: one `dropped` row and one WARNING per repeated cycle (run, 17.11: three cycles, one proposal filed, two rows). The identity holds (3 = 1 + 2). Marking it by design is one line in `unaccounted` and one case in S3; the Captain's call, with L16.
- **L22. Reach of the two new checks.** The proposal check is exact on the title (case and spacing aside) and per author, among the channel's 100 newest threads (pinned first; archived threads are not listed; the Ward Room's retention bounds the rest, L13): a reworded title is a new proposal, a revised proposal under the same title is refused as a duplicate (L26), and a proposal whose thread was pruned can be filed again. The reply check (A4) is equality of the text, case and spacing aside, with the agent's newest live post in the thread: an exact repeat is skipped; a changed value, a reply the agent took back and a reply worded differently are posted (L23); a deleted post and another author's are not compared. Both serve the Ward Room pipeline too (the extractor and the router are shared), where BF-197 is dead for the same reason as BF-105 (L2).

### 17.10 Diff Reviewer: properties to verify for A3

1. **The vote.** `endorse` returns `changed` on every path (the early return for the vote already held: False; the end: True except for an unvote with nothing to remove); trace `process_endorsements`: with `changed` False nothing but a DEBUG line happens and the loop goes on to the next endorsement; a flip still credits. The two HXI routes return the dict unchanged but for the key.
2. **The reply.** `repeats_own_reply` reads the posts of the thread the extractor fetched (tree, `children`), compares the reply, as a person reads it, with the newest of the agent's own live posts only (A4: 18.2), and sits after `_extract_commands_from_reply`, the cleaning and the empty check, before BF-237's budget (A4: 18.3); it fails open. After a restart it still holds.
3. **The proposal.** The check runs after the channel and the rationale are known and before the thread is created; `author_id` is read once and used for both; a refusal has `success` False, so the extractor makes the entry and the WARNING and does not count a filed proposal.
4. **The guard.** `_actions_lost` keeps the order of `_ACTION_MARKERS`; `proposal` is added only when the original's block parses valid; the early return stays inside the `try`; `_ACTION_MARKERS`, `_action_markers_in` and `_detect_undeclared_actions` have no changed line.
5. **The matrix.** 17.4 against the code: each row's lines, and the evidence for each guard it calls live.
6. **S3.** A3-30 is the only S3 line that changes; S3's pairs apply over the A3 tree (17.11); S3's DECISIONS and PROGRESS anchors are unchanged.
7. **Tests and counts.** Each new case fails on S2's M3 head where section 6 says and passes after; T14 to T17 pass on both; the counts of 2.5 against the runner.

### 17.11 Verified (A3, 2026-11-12, the Architect; read-only, in memory, scratch directories removed afterwards; no pytest and no repository test)

The 44 pairs applied in label order (Part 1 to the LF blobs at `8cae8376`, Part 2 to the contract blob at that head, equal to the a2 LF copy): every SEARCH once at its turn, at the start of a line, ASCII; every changed `.py` compiles and imports. A hand-made runner (parametrize, `async def`, fakes for `tmp_path`, `monkeypatch` and `caplog`) over a copy of the head: S2's file, 26 passed on the head; with A3's test pairs alone 37 collected, 30 passed, 7 failed at their own asserts; with all the pairs 37 passed; S1's 34 passed on the A3 tree; S3's pairs applied from the patched contract over the A3 tree (0 anchor failures, as on the unamended head) and S3's 43 cases passed on that chain (42 and the reconciliation test failing before A3-30). Rows 11 to 24 and 53 to 72 each run by hand on a copy of the A3 tree; the failing cases are the ones the table names. In memory on the A3 and S3 tree: a repeated proposal gave one thread and two `dropped` rows with the reason `router_refused: Proposal already filed`, logged at WARNING (L21); three identical DMs gave one DM thread with BF-163 cleared between cycles and three with both guards cleared (17.4); a one-line corruption of each tag's block kept the marker and lost the block for notebook (no closing tag, an empty body), endorse (no direction), reply (no closing tag), DM (an unbalanced bracket) and note (no closing tag), and a `[DM @Worf]` with no closing tag was still carried out (L20). Unchecked: the real pytest and its collection, xdist and suite order, the broad gate, the G2 files (read against the changes, not run), the architecture checker's command, any live model; the group chat and CrewSession guards were read, not run. The readers of `endorse`'s dict, `process_endorsements` and `handle_propose_improvement` were enumerated by `rg -n "voter_direction|\.endorse\(|process_endorsements|extract_endorsements" src` (the service wrapper `ward_room/service.py:498`, the router's two methods, the two HXI routes `routers/wardroom.py:366` and `:380`, the callers `proactive.py:3164-3166` and `ward_room_pipeline.py:300-302`, a docstring in `cognitive/deliberation/protocol.py:77`), `rg -n "voter_direction|/endorse" ui desktop` (the two URLs in `WardRoomEndorsement.tsx:13-14`) and `rg -n "handle_propose_improvement" src` (`proactive.py:3600` and the definition at `ward_room_router.py:1063`).

## 18. Amendment A4 (review round 2 of slice S2, 2026-11-12)

### 18.1 What each finding was, and what A4 does

| Finding | What it was | What A4 does |
|---|---|---|
| G1 (P2, a regression of A3) | `repeats_own_reply` compared word sets at a Jaccard of 0.6 with every live post of the agent in the thread: "...temperature is now 41 C." then "...49 C." was suppressed as a repeat (0.777778 in the reviewer's run; 0.846 for the twelve-word reply of T24); before A3 both were posted | the check is equality of the text as a person reads it with the agent's newest live post (A4-1, A4-2; T24, T25, T27, T28) |
| G2 (P2, a regression of A3) | the check ran before `_extract_commands_from_reply`, so a repeated reply that brought a new `[MOVE]` or `[CHALLENGE]` was skipped whole and the command never ran (the reviewer's run: moves after a legal new reply command, before A3 3, at the head 2; through both callers) | the check runs after the commands, the cleaning and the empty check, before BF-237's budget (A4-3, A4-4; T26) |
| G3 (P3, a sentence made stale by A3) | D3's AD-643b row said the guard acts only when a marker is lost; A3's `_actions_lost` also loses `proposal` when the approved block could be filed and the rewrite's cannot | the row says both (A4-13); the sweep of 18.4 found and amended every other copy of the facts A4 changes |

### 18.2 D-I. What counts as the same reply

`repeats_own_reply(thread, author_id, body)` is true when `body`, as a person reads it, is the text of the agent's **newest** live post in the thread: `" ".join(strip_unverified_label(str(text or "")).split()).casefold()` on both sides (A5: the content firewall's `[UNVERIFIED ...]` labels at the start come off first, 19.2; the case and the spacing aside; **punctuation kept**, because "4.1" and "41", "-5" and "5", "no." and "no?" differ in it), all of the agent's posts that share the newest timestamp must say it (two newest posts that differ are no evidence), and an empty text repeats nothing. It fails open on a thread of another shape. **Why equality.** For n distinct words and one word replaced the Jaccard is (n-1)/(n+1): 0.846 at twelve words, 0.95 at thirty-nine, so no threshold below 1.0 keeps a one-word change in a paragraph, and 1.0 on word sets still equates a sentence with its re-ordered negation; a list of number and polarity tokens misses every other changed word (passed to failed, one name for another). **Why the newest post.** A reply the agent took back and now says again has changed the thread: X, Y, X must post all three (T25); AD-614's gate on a DM also compares the pair's last body. **Which text.** The reply as it is about to be posted, after the commands are removed and the cleaning has run, against the stored bodies, which are what `create_post` was handed less the label the content firewall puts before the body it flags (A4 left that label in the stored text, so a flagged reply never equalled itself: round 3's H1; A5 reads it away on both sides, 19.2): the same pair, which A3's raw-reply comparison was not. Rejected: equality with any live post (it drops X, Y, X); a higher threshold; a number-and-polarity test; no guard (round 1's regression returns).

### 18.3 D-J. Where the check sits, and what a skip keeps

The extractor's order after A4: (1) an empty body, an unresolved thread, a locked thread, BF-105 (dead, L2), BF-171's cooldown and BF-201's cap `continue` (these precede the commands: L24); (2) the commands in the reply run (BF-121: CHALLENGE, MOVE); (3) the text is cleaned (`apply_dm_sanity`, `_strip_bracket_markers`, `withhold_dm_blocks`) and an empty text `continue`s (a command-only reply, whose command ran); (4) **A4:** `repeats_own_reply` `continue`s (the commands ran; the repeated prose is not posted again); (5) BF-237's budget `continue`s; (6) `create_post`, which is where the budget is spent, BF-198's `record_agent_response` is called, boot camp counts the post, BF-171's timestamp is set and the `reply` entry and the commands' entries are appended. A skipped repeat therefore spends neither the budget nor the cooldown nor BF-198's record, and a second, new `[REPLY]` block of the same output still posts. It sits before the budget test so that the WARNING BF-237 logs for a genuine second reply is not logged for a repeat. **Entries.** A skipped reply leaves no entry, as a command-only reply leaves none for its command: S3 reads the `type` of each entry against `ACTION_TAGS`, whose evidence types are `ward_room_post`, `reply`, `endorse`, `dm`, `notebook_write` and `proposal`; no tag has `move` or `challenge` evidence, so S3 sees a skipped reply with a command as it sees one without: the declared `ward_room_reply` has no `reply` entry and is dropped as `no_block_executed` at WARNING (L8). `actions` is therefore not extended on a skip (L24). **The Ward Room pipeline**, the second caller (through `extract_and_execute_actions`), passes a `PostBudget` (the think passes none); a posted `[REPLY]` spends it and the pipeline's own main post is then suppressed (AD-832), while a skipped repeat spends nothing, so text outside the block can still be posted as the main post; the main post itself is not checked by `repeats_own_reply` (BF-197 is dead for the reason of L2). The commands run for both callers (T26). Rejected: a second extraction before the check (the CHALLENGE and MOVE patterns, the markdown strip and the sanitising steps written twice, or a compared text that is not the posted text); moving BF-105, BF-171, BF-201 and the lock after the commands too (a game move inside BF-171's window would run: a pre-existing behaviour outside this issue, L24); a limit (the reviewer's measured regression has ordinary reach).

### 18.4 D-K. The corrected matrix rows, and the sweep

| Action | What a repeat does on the head | What stops it, and is it live | A4 |
|---|---|---|---|
| `reply` (`_extract_and_execute_replies`) | the exact repeat is skipped; a reply the agent words differently is posted on every cycle once BF-171's cooldown has passed (L23) | BF-105: dead (L2); BF-171: live, in memory, 180, 120, 90 and 60 s by tier (`comm_proficiency.py:39-51`), 120 s by default; BF-201: live, the thread's 50 root posts; `repeats_own_reply`: live, persisted, word for word against the agent's newest live post | **guard** (T20, T15, T22, T24 to T28) |
| `challenge` (direct, and inside a reply) | a Recreation thread and a game per cycle: `create_game` refuses only the Captain's second game and a player against themself (`recreation/service.py:158-163`); inside a repeated reply it runs again, as in the parent | none | L19 |

The in-place amendments of A4-13 to A4-37 are the sentences that said the reply guard compares word sets, or runs before the commands, or skips a command with its prose (the AD-643b row of D3, section 3's reader paragraph, 17.1, 17.3, 17.8's G2 line, 17.10, the `challenge` row of 17.4, L8, L19, L22, the S2 and S3 G2 lines, the S2 heading, acceptance 2 and 3, section 9's paragraph, and A3's bullets in `DECISIONS.md` and `PROGRESS.md`); the rest of section 17 records what A3 did and says "A3". The search that found them is in the answer to A4 (the phrases "Jaccard", "word set", "repeats_own_reply", "skipped with", "already made", "marker is lost", "rows 53 to 72", "37"), and was re-run over the patched files.

### 18.5 Tests

S2's file gains 8 cases (T24 to T28, section 6): one control before the first class (T27) and one class at the end (T24, T25, T26 x 4, T28), which S2's A3 head fails (section 6 says where). T26 drives both callers of the extractor: the real think and the real `WardRoomPostPipeline` (`_pipeline`), over a real Ward Room and a real `RecreationService` (`w.rt.recreation_service`); the game assert follows the posts assert, which passes on both trees. The world's clock is read nowhere (`_elapse` clears BF-171's cooldown); `_kiras_replies` sorts, so the order of two posts made within a clock tick is not asserted, and the helper's tie is the case T28 pins. T15, T20 and T22 are unchanged.

### 18.6 Mutation rows

Section 9: row 61's killers amended, rows 62 to 64 and 66 replaced, rows 73 to 80 added (measured by hand on copies of the A4 tree: each fails exactly the cases the table names; rows 65 and 67 re-run, unchanged).

### 18.7 Gates for A4

- **G1 for S2.** `PY -m pytest tests/test_bf934_s2_secondary_gates.py -q -n 0 -p no:randomly` after the whole of A4: 45 passed. With A4-5 to A4-8 alone on A3's head: 45 collected, 38 passed and 7 failed, each failure an `AssertionError` at an assert of its case (never a setup error); T27 passes on both trees.
- **G2 for S2.** The command of section 4, **unchanged: A4 adds no file to it** (A5 adds one, 19.6). The files that call the reply extractor or build a reply block it reads (`rg -l -g '*.py' -i "\[reply[ \]]|_extract_and_execute_replies|extract_and_execute_replies|_extract_commands_from_reply" tests`, 14 paths as run in A5; without `-g '*.py'` it also lists the fixture `tests/fixtures/ad1152_agentic_off_golden.json`, 15): `test_ad437_action_space`, `test_bf201_thread_post_cap`, `test_bf237_pipeline_post_budget`, `test_bf874_dm_callsign_and_fail_closed`, `test_proactive_quality`, `test_recreation_channels` and `test_trigger_learning` are in the command already, and so is S2's own file, the fourteenth path; `test_ad631_skill_effectiveness`, `test_ad632g_cognitive_jit_integration`, `test_ad724_dm_hardening` and `test_bf185_reflect_social_bypass` name `[REPLY` in a prompt or a sanity text and never call the extractor (A4's reading, not re-read in A5); `test_ad719_chat_fanout` and `test_ad933_group_chat_escalation` have a variable called `reply` (A4 also listed `test_bf186_compose_standing_orders` here: the command does not return it, and it is not in the G2 command). The files that name `[MOVE` or `[CHALLENGE` (`rg -l -g '*.py' "\[MOVE|\[CHALLENGE" tests`, 13 as run in A5; without `-g '*.py'` 14, the same fixture): `test_recreation_channels` is the one that builds a command inside a `[REPLY` block (BF-121; it is in the command); by their matched lines the DM-path and sanity files (`test_ad1156_plan_mode_containment`, `test_ad1156_plan_mode_reply_tags`, `test_ad1156_plan_mode_side_effects`, `test_ad1248_slice_a_crossing`, `test_ad724_dm_sanity_gate`, `test_ad726_dm_reply_pipeline`, `test_agents_router_game_move`, `test_cognitive_agent_dm_game`) never reach the proactive reply extractor; I did not open `test_ad632d_compose_handler`, `test_ad924_group_chat_trigger` and `test_bf186_compose_standing_orders` (a prompt assertion, a group chat and a prompt assertion by their names; the first is in the command). None is expected to change count or behaviour: their threads are mocks without a post of the agent's own with the reply's text (`test_ad437_action_space` returns no posts, `test_bf201_thread_post_cap` posts with neither author nor body, `test_bf237_pipeline_post_budget` an empty list), and the real-Ward-Room file posts each reply once. **Expected:** the S1 file 34 and the S2 file 45 passed; every other file 0 failed and collected counts equal M0; the architecture check clean.
- **G3.** The ledger generator, `--check` and `tests/test_ad1184_ad_ledger.py`: the ledger is regenerated by the orchestrator.

### 18.8 Recorded limits

- **L23. A reply worded differently is a new reply.** `repeats_own_reply` is equality, so a model that paraphrases itself on every cycle is not caught by it (the content firewall's `[UNVERIFIED ...]` label on a flagged reply is not part of the comparison since A5: A4 left it in the stored text and a flagged reply never equalled itself, round 3's H1; 19.2); the check sees the thread's 100 newest posts (`get_thread`'s `post_limit`). Reach: one reply per think per agent per thread until BF-201's cap of 50 root posts (all authors): one think per `cooldown_seconds` (300 s by default, a per-agent override held to 60-1800 s), BF-171's 60 to 180 s per channel (120 s by default), so about 4.2 hours to the cap at the defaults (50 x 300 s), and 50 to 150 minutes when the agent's cooldown is overridden to 60 s (the spacing is then BF-171's tier cooldown). The parent's protection was AD-493's embedding match of the whole raw output with the agent's recorded observations (probabilistic; a reply-only output was compared with nothing, 17.4); BF-934 deliberately no longer lets AD-493 discard an action (D3), so a paraphrased reply attached to a rehashed observation is now carried out. A semantic repeat gate over replies (recording them, as AD-493 records observations) is the fix: a new BF for the orchestrator to allocate.
- **L24. A command inside a reply is discarded by the skips that precede the commands.** An empty body, an unresolved or locked thread, BF-105, BF-171's cooldown and BF-201's cap `continue` before `_extract_commands_from_reply`, so a `[CHALLENGE]` or `[MOVE]` inside a reply that BF-171 or BF-201 skips never runs (the parent's behaviour, unchanged: found by this review, not fixed). Reach: any reply by an agent inside its channel's 60 to 180 s cooldown, or in a thread at the cap. And a command that ran in a reply that is not posted (a command-only reply, and since A4 a repeated reply) is not reported in `actions`; S3 reads neither. A new BF for the orchestrator to allocate.
- **L25. AD-614's DM gate is a likeness gate with the same flaw.** `extract_and_execute_dms` suppresses a DM whose word set has a Jaccard of 0.6 or more with the pair's last body (`if sim >= 0.6`): a longer DM with one changed value is suppressed. (A5: the last body is held in memory per pair, `self._last_dm_body`, read at the gate and written after it: `rg -n "_last_dm_body|sim >= 0.6" src/probos/proactive.py` finds four lines on A5's tree, the initialisation, the read, the comparison and the write; so the gate compares the DM as sent and the content firewall's label never reaches it. It is pre-existing, and none of S2's changes to `proactive.py` is in that function: 19.4.) A3 borrowed its threshold; A4 no longer does. Unchanged by BF-934; found, not fixed: a new BF for the orchestrator to allocate.
- **L26. A revised proposal under the same title is refused as a duplicate.** The router's check is the same author and the same title (case and spacing aside), whatever the Rationale says: a proposal re-filed with a better Rationale under its old title gets `router_refused: Proposal already filed` (S2's `proposal_suppressed` entry and its WARNING are operator diagnostics: neither caller shows the refusal to the agent, L27; a new title files it). The title is the proposal's identity in the channel the Captain reads, so this is the reader's "same", and the case is recorded rather than widened.

### 18.9 Diff Reviewer: properties to verify for A4

1. **The helper.** Equality of `_as_read` of both texts, against the newest live own post only; every own post that shares the newest timestamp must say it; an empty text repeats nothing; the author, `deleted` and `children` handling and the fail-open `except` are A3's, unchanged in shape; the signature is unchanged; the module-level import of `jaccard_similarity` and `text_to_words` is gone and nothing at module level used them (the two local imports in `proactive.py` remain).
2. **The call site.** After `_extract_commands_from_reply`, the cleaning and `if not reply_body: continue`; before BF-237's budget and `create_post`; the old call before BF-171 is gone; the text compared is the text about to be posted; a skip `continue`s with no state changed.
3. **Commands.** A repeated reply with a new `[MOVE]` or `[CHALLENGE]` runs the command and posts its prose once, through the think and through the Ward Room pipeline (T26); what BF-105, BF-171, BF-201 and the lock skip is unchanged (L24).
4. **S3.** S3 reads the `type` of the entries; a skipped reply leaves none; no S3 pair moved (18.10).
5. **The sweep.** No sentence of the contract, `DECISIONS.md` or `PROGRESS.md` says the reply guard compares word sets or runs before the commands, apart from those that name A3's behaviour as A3's; line 118 says both cases.
6. **Tests and counts.** Each new case fails on A3's head where 18.7 and section 6 say and passes after; T27 passes on both; the counts of 18.7 and the rows of section 9.

### 18.10 Verified (A4, 2026-11-12, the Architect; read-only, in memory, scratch directories removed afterwards; no pytest and no repository test)

The 38 pairs applied in label order (Part 1 to the LF blobs at `95821f70`, Part 2 to the contract blob `c53ad930`): every SEARCH once at its turn, at the start of a line, ASCII; every changed `.py` compiles. A hand-made runner (parametrize, `async def`, a fake `tmp_path`; the cases that need `caplog` or `monkeypatch`, 8 of the 45, were not run: they exercise the proposal and notebook paths, which A4 does not touch) over copies of the head: S2's file at the head, 29 of its 37 cases run and passed; with A4's test pairs alone 30 passed and 7 failed at their own asserts (T24 at the list of Kira's posts, T25 at the same list, the four rows of T26 at the games assert, T28 at its first assert); with all the pairs 37 passed. Rows 61 to 67 and 73 to 80 each run by hand on a copy of the A4 tree: each fails exactly the cases the table names. In memory: the helper on the twelve-word pair of T24 (Jaccard 0.846, the head's helper True, A4's False); a revised proposal under the same title was refused (L26); S3's pairs, split from the patched contract by `split_bf934.py` and applied over the A4 tree by `apply_search_replace_blocks_bare.py`: 0 failures. Unchecked: the real pytest and its collection, xdist and suite order, the broad gate, the G2 files (read against the change, not run), the architecture checker's command, any live model; rows 11 to 24, 53 to 60 and 68 to 72 were not re-run on the A4 tree (their lines are untouched and the new cases are about replies only).

## 19. Amendment A5 (review round 3 of slice S2, 2026-11-12)

### 19.1 What each finding was, and what A5 does

| Finding | What it was | What A5 does |
|---|---|---|
| H1 (P2, a regression of A4) | The content firewall puts `[UNVERIFIED ...]` before the body it stores for a flagged post (`MessageStore.create_post`, `ward_room/messages.py`; `ThreadManager.create_thread`, `ward_room/threads.py`, for a thread's own body). A4 compared that stored body with the reply about to be posted, which has no label, so a flagged reply never equalled itself and was posted again: three identical flagged replies left 1, 2 and 2 posts of the agent in the thread, through both callers (19.3). The tests could not see it: the test world wired no firewall | both texts are read without the labels at their start: `strip_unverified_label` beside the label (A5-1), used by `_as_read` (A5-2 to A5-4); T29 to T35 wire the firewall as `startup/finalize.py` does and assert the stored label first |
| H2 (P3, a claim A4 wrote) | L26 said the refusal of a duplicate proposal reaches the agent | it does not (19.4); L26 says what the code does (A5-32) and L27 records the missing feedback |
| H3 (P3, a claim A4 wrote) | L8 listed the post budget's refusal among the causes "in the DEBUG log only" | the budget's refusal is a WARNING; L8 gives each skip's level as run (A5-25) |
| H4 (P3, a command A4 quoted) | `rg -l "\[MOVE|\[CHALLENGE" tests` returns 14 paths, a JSON fixture among them, not 13; the sweep found the same fixture in the neighbouring command of 18.7 and, in its list, a file that command does not return | both commands take `-g '*.py'`, the counts are as run, and the list names what the command returns (A5-29) |

### 19.2 D-L. Where the label comes off, and what the label is

The brake's plan is taken as it stands: **both texts, every leading label, inside `_as_read`.** `canon(store(x)) == canon(x)` then holds for every body `create_post` can be handed, because the label is the only change the store makes to a body (the round trip of 19.3: 12 bodies, one transformation) and the canonical form is symmetric and idempotent. Ranked: (1) **both sides, every leading label** (taken); (2) the stored side only (rejected: a reply that itself begins with a label, as an agent that copies one writes it, is stored as written, so only its incoming side still carries one: row 82 fails four cases of T29; and a flagged copy carries two, so stripping one label fails too: row 84 fails six cases); (3) a private regex in `proactive.py` (rejected: the label is defined in `ward_room/content_firewall.py` and produced in two places, so its inverse belongs beside the definition, and T31 and T32 tie the helper to both producers); (4) one function that both producers call (the proper DRY refactor, on a Ward Room hot path in a last round: a follow-up, not built); (5) an in-memory record of the last body sent, per agent and thread (the AD-614 precedent: it removes the storage coupling, but is lost at a restart, blind to other writers and a new design: not preferred over this). **The pattern.** `^\s*(?:` + `re.escape("[UNVERIFIED \u2014 ")` + `[^\]]*\]\s*)+`: the firewall's lead-in (an em dash, written as the escape `\u2014` in an ordinary string, so that the helper's block is ASCII), then the reasons up to the first `]` (the three reasons the firewall names, `ungrounded_hex_ids`, `phantom_thread_ref` and `fabricated_metrics`, hold none), then the spacing. Spaces before the first label are consumed, so a label after spaces goes too; a body with no label is returned as it is. **Equivalence, run:** the same pattern as one ordinary string with the escapes doubled, the brake's prototype (a raw string, which `re` reads) and the label matched without the dash agree with the helper on the 12 bodies of the round trip and on the 36 stored forms made by putting each of the firewall's three reasons before each of them; on 12 adversarial strings (a colon label, a hyphen label, lower case, no closing bracket, a doubled bracket, an empty reason, a label inside the text, two labels on two lines, leading newlines, a label then another bracket, the empty string, a label alone) the first two agree with the helper and the dashless one differs on one, `[UNVERIFIED - phantom_thread_ref] ...` (a hyphen is not the firewall's label). The dashed pattern is taken: it is the firewall's label and nothing wider.

### 19.3 D-M. The check of the brake's 4(b): expected first, then the run

**What the test world left out.** `tests/bf934_world.py` builds a `WardRoomService` and wires no content firewall (and a `MagicMock` for trust in its router); no line of it or of S2's file named a firewall before A5, and the production wiring is `startup/finalize.py` alone (`rg -n "content_firewall" src --glob "*.py"` finds, besides the module itself, `messages.py` and `threads.py`, which hold the late-bound object, and `finalize.py`, which builds it with the default `FirewallConfig` and sets it on `ward_room._messages` and `ward_room._threads`; the service has no public setter). A5 wires it in S2's own file (`_with_firewall`, A5-7) the same way, and gives the router the loop's real `TrustNetwork`; `tests/bf934_world.py` is not touched (slice S3's build documents its `event_log` parameter there).

**Expected, written before the run** (in the harness's source, before it was run on A5): three cycles of the same reply, each followed by the reply cooldown cleared; both callers; the pipeline's own `PostBudget`; a real `TrustNetwork`; the firewall wired; **a pure repeat `[1, 1, 1]`, a changed value `[1, 2, 2]`; any cell that differs is a finding.** **Measured** (Kira's posts after each cycle; identical in both callers, and identical with the cycles run back to back as the tests run them and with the clock moved 400 s between them):

| Reply class (does the first stored body start with the label) | Expected | A4 | A5 |
|---|---|---|---|
| plain repeat (no) | [1, 1, 1] | [1, 1, 1] | [1, 1, 1] |
| one reason, `phantom_thread_ref` (yes) | [1, 1, 1] | **[1, 2, 2]** | [1, 1, 1] |
| two reasons, `ungrounded_hex_ids, phantom_thread_ref` (yes) | [1, 1, 1] | **[1, 2, 2]** | [1, 1, 1] |
| a reply that begins with the label, not flagged (yes, as written) | [1, 1, 1] | [1, 1, 1] | [1, 1, 1] |
| a reply that begins with the label and is flagged: two labels (yes) | [1, 1, 1] | **[1, 2, 2]** | [1, 1, 1] |
| a changed value (41 C, 49 C, 49 C), flagged (yes) | [1, 2, 2] | [1, 2, 2] | [1, 2, 2] |

All 24 cells of the A5 run (6 classes, 2 callers, 2 clocks) are as expected; the 12 cells of the three flagged classes differ on A4, in every combination: H1 is reproduced through both callers and closed. **Storage round trip** (`create_post` with the firewall wired, then `get_thread`; "equal" is `_as_read(stored) == _as_read(body)`): 12 bodies, A4 equal on 7 and not equal on 5 (one reason, two reasons, a flagged label echo, the same after spaces, fabricated metrics from an author of trust 0.2), A5 equal on all 12; the stored body is the label and the body for each flagged row and the body itself for every other, so the label is the only change the store makes (the padded, multi-line, Unicode, bracket-prefixed and 6,000-character bodies come back unchanged). `fabricated_metrics` is reached by a body of three precise figures ("50ms baseline", "200ms spikes", a signed percentage) from an author below 0.45 (the body AD-529's own test uses for the reason; the brake's metrics body did not trip it). Not run: a reply by such an author through the two callers (the brake's run posted nothing for it, unexplained; A4 and A5 agree there); the round trip covers the reason.

### 19.4 H2 to H4, the sweep, and the commands as run

**H2.** Three think cycles of a repeated proposal (a real `CognitiveAgent` with a scripted model, the novelty gate finding every observation repeated, as T21 sets it): the entries the extractor returned to the think were `proposal`, then `proposal_suppressed` with `router_refused: Proposal already filed`, twice; two WARNINGs (`BF-934: proposal from Kira (science_officer) not posted: router_refused: Proposal already filed`); the model received 3 requests and none of their prompts mentions the refusal. `rg -n "actions_taken" src/probos/proactive.py` finds one line (the assignment, `:1546` on A5's tree) and `rg -n "\b_actions\b" src/probos/ward_room_pipeline.py` one (`:293`, `response_text, _actions = await ...`). Slice S3 reads `actions_taken` into its ledger (the `settle_intended_actions` calls of section 7): an operator record, not the agent's prompt, so L26's "reach the agent" was false before S3 and stays false after it (L27).

**H3.** Each skip of the reply extractor, run through `_extract_and_execute_replies` with a log handler at DEBUG on A5's tree: an unresolved thread, DEBUG (`AD-437: Reply target thread deadbeef not found`); a locked thread, DEBUG (`... is locked`); BF-171's cooldown, DEBUG (`BF-171: Reply cooldown for science_officer in channel f017ba03 (120s remaining)`); BF-201's cap with `max_thread_posts` set to 1, DEBUG (`BF-201: Thread e1da84f4 at post cap, skipping proactive reply`); a repeated reply, DEBUG (`BF-934: Suppressed repeated reply from science_officer to thread f669d845`); a spent `PostBudget`, **WARNING** (`BF-237: Suppressing additional [REPLY] from science_officer`, then the budget text). BF-105 is dead (L2): its call is `logger.debug`, read, not run. `rg -n "BF-237: Suppressing additional \[REPLY\]" src/probos/proactive.py` finds one line (`:4205`); the shorter `rg -n "BF-237: Suppressing" src/probos/proactive.py` finds two (`:3783`, the `[MOVE]` board post's own refusal, and `:4205`), which is why the quoted command is anchored.

**H4.** `rg -l "\[MOVE|\[CHALLENGE" tests` returns 14 paths (13 `.py` and `tests/fixtures/ad1152_agentic_off_golden.json`); `rg -l -g '*.py' "\[MOVE|\[CHALLENGE" tests` returns 13. The neighbour, `rg -l -i "\[reply[ \]]|_extract_and_execute_replies|extract_and_execute_replies|_extract_commands_from_reply" tests`, returns 15 (14 `.py` and the same fixture); the 14 are S2's own file and 13 of the 14 files 18.7 named (`test_bf186_compose_standing_orders` is not among them).

**The DM gate (L25).** `git diff -U0 17741025bd56044029ff84f7839a9ca0f8da61a0 307653071820fc6bfeccbf8fb25a506d2c729518 -- src/probos/proactive.py` has its last hunk at line 4185 of the A4 head; `extract_and_execute_dms` starts at line 4934 there: none of S2's changes to `proactive.py` is in it.

**The sweep (3.4 of the brake), over the A4 head and again over the patched files.** `rg -n "UNVERIFIED|prefix|annotat|L23" prompts/bf-934-dropped-crew-proposals.md tests/test_bf934_s2_secondary_gates.py src/probos/proactive.py`: 20 matching lines on the head (14, 1 and 5); most are noise (`annotat` matches `from __future__ import annotations`; `prefix` matches three comments of `proactive.py`), and the two that said the label was left alone were 18.2 and L23, both amended; the other mentions of L23 (section 3, the `reply` rows of 17.4 and 18.4, the `repeats_own_reply` docstring) say a reply worded differently is a new reply, which is still true. `rg -n "word for word|same reply|_as_read|repeats_own_reply" prompts/bf-934-dropped-crew-proposals.md tests/test_bf934_s2_secondary_gates.py`: 16 and 4 lines on the head; the sentences that spelled the formula or the label were 18.2 and L23 (amended); the rest name the guard or say "word for word", which is still true. The re-run over the patched files is in 19.9. `_as_read` has no consumer but `repeats_own_reply`, and `repeats_own_reply` one caller (`rg -n "_as_read\(|repeats_own_reply\(" src`, A5's tree: the two definitions, `_as_read`'s two uses inside the helper and the one call in `_extract_and_execute_replies`).

### 19.5 Tests (S2's file: 28 new, 73 in all)

T29 to T35 (section 6 says where each fails on A4's head), in one class at the end with the helpers `_with_firewall`, `_strip_label` and `_says` and the constants they use; T15, T20, T22 and T24 to T28 are unchanged. Every flagged row asserts the first stored body before it asserts the count or the equality (the stored body is the label and the reply: it fails there, not later, if the wiring stops flagging). T29 drives both callers of the extractor (the real think; the real `WardRoomPostPipeline`) over a real Ward Room and a real firewall; T30 is the control that a changed value still posts; T31 is the storage round trip over 12 bodies; T32 ties the helper to the second producer (`create_thread`); T33 to T35 are the helper alone. No clock is read (`_elapse` clears BF-171's cooldown). "No BF-934 name is imported at module level" stays true: `ContentFirewall` is AD-529's; the helper is reached through `_strip_label`, which fails at its own assert until A5 (an `AttributeError` would not).

### 19.6 Gates for A5

- **G1 for S2.** `PY -m pytest tests/test_bf934_s2_secondary_gates.py -q -n 0 -p no:randomly` after the whole of A5: expected 73 passed. With A5-5 to A5-7 alone on A4's head: 73 collected, 58 expected to pass and 15 to fail, each failure an `AssertionError` at an assert of its case (never a setup error); the hand runner's figures for the 45 reply-path cases are in 19.9.
- **G2 for S2.** The command of section 4 gains `tests/test_ad529_contagion_firewall.py` (A5-11). Enumerated: `rg -l "content_firewall|ContentFirewall|UNVERIFIED" tests` returns 4 files and none was in the command: `test_ad529_contagion_firewall.py` imports `ContentFirewall`, builds the two stores with the firewall set and pins the stored label (`:621`, `:630`: **added**); `test_architect_agent.py` (`:966`, a prompt text holds the word), `test_social_verification.py` (`:464`-`:467`, social verification's own `[UNVERIFIED:` string) and `test_bf953_read_floor_spellings.py` (`:72`, a refusal-reason constant) name the word and cannot reach the helper, `_as_read` or the firewall's code: not added. `rg -l "set_content_firewall" tests` returns `test_ad529_contagion_firewall.py` alone. `rg -l "MessageStore|ThreadManager" tests` returns 14 paths (13 tests and the census fixture `ad1346_store_census.py`): `test_ad1346_admission_store_writes.py` and `test_self_monitoring.py` are in the command already; of the other 11, `test_ad529_contagion_firewall.py` is the one added, and the other ten build the stores with no firewall, so a new function in the firewall module and one changed line of `_as_read` cannot reach them: not added. **Expected:** 51 files; the S1 file 34, the S2 file 73 and `test_ad529_contagion_firewall.py` 39 passed (39 by `rg -c "^\s*(async )?def test_"`, a static count: the file has no `parametrize`); every other file 0 failed and collected counts equal M0; the architecture check clean (run in A5 on the scratch tree: `architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)`; the new import is a module-level import from `probos/`, which is unranked, into the `ward_room` package).
- **G3.** The ledger generator, `--check` and `tests/test_ad1184_ad_ledger.py`: the ledger is regenerated by the orchestrator.

### 19.7 Recorded limits

- **L27. A refused proposal is not shown to the agent.** `proposal_suppressed` and its WARNING are operator diagnostics (19.4): neither caller feeds the refusal back (the think assigns the list and, at S2's head, reads it nowhere; slice S3 reads it into the ledger, an operator record; the pipeline discards it), so an agent that files a proposal again under the same title is refused on every cycle (L26) and its prompt never says why. Feeding a refusal back is separate wiring, a new BF for the orchestrator to allocate.
- **L28. Which rows of the repeated-cycle matrix a test executes (17.4, 18.4).** `rg -n` over S2's test file for the tags of each row (`[ENDORSE`: 3 lines, `[PROPOSAL`: 17, `[REPLY`: 8, `[NOTEBOOK`: 1, `[CHALLENGE`: 1, `[MOVE`: 1; `[DM `, `[GROUP`, `[ARTIFACT`, `[STATUS`, `[NOTE`, `[ASSIGN`, `[HANDOFF`, `[CREW`, `READ_NOTEBOOK`: 0 each). **Executed by a test of S2's file over repeated cycles:** `endorse` (T18, T19), `reply` (T20, T24, T25, T27, T29, T30) and `proposal` (T21). **Executed, but not as a repeat:** `notebook` (one cycle, `test_a_notebook_entry_attached_to_a_rehashed_observation_is_still_written`), and `challenge` and `move` inside a reply (T26 runs a new command in the second cycle and asserts it ran once; a repeated command is not run); T28 is the helper alone. **Read only, no test of S2's file names their tag:** `dm` (A3's in-memory run of three identical DMs is recorded in 17.4, not a test), `group_chat`, `artifact`, `status`, `note`, `read_notebook`, `assign`, `handoff`, `crew`, the agent-work tags, and a `challenge` or `move` that is not inside a reply. Tests of other files may execute some of them (for example AD-550's notebook check has its own file): this limit says only what S2's file runs.
- **Amended in place by A5:** L8 (the levels, A5-25), L23 (the label, A5-30), L25 (the DM gate's last body: A5 found no new limit there, the brake's "L27" for it is this amendment, because L25 already recorded it), L26 (A5-32).

### 19.8 Diff Reviewer: properties to verify for A5 (a delta review over A4, `307653071820fc6bfeccbf8fb25a506d2c729518`)

1. **The helper.** `strip_unverified_label` removes every label of the firewall's exact shape at the start of a body (spaces before the first one included) and nothing else; idempotent; a body with no label comes back as it is; its only consumer in `src` is `_as_read`; `content_firewall.py` gains one function and two module constants and nothing else.
2. **The comparison.** `_as_read` removes the labels from both sides before the case and spacing are read; `repeats_own_reply` is otherwise A4's (the author, `deleted`, `children` handling, newest-post rule and fail-open `except` are unchanged); the one caller is the guard in `_extract_and_execute_replies`, reached by the think and by the Ward Room pipeline.
3. **The seam, in production wiring** (the harness of 19.3: the firewall as `finalize.py` sets it, a real `TrustNetwork`, the pipeline's `PostBudget`): every pure repeat `[1, 1, 1]` and a changed value `[1, 2, 2]`, flagged or not, through both callers; a skipped repeat leaves the budget, the cooldown, BF-198's record and the entries untouched (round 3's property 18, which A5 does not change).
4. **Tests.** T29 to T35 fail on A4's source at their own asserts (never at a setup) and pass on A5's; T30 and the unflagged rows pass on both; rows 81 to 88 and the amended rows 61, 63, 73, 74, 75, 78 and 80 fail the cases the table names.
5. **Text.** Run every command quoted in 19.4, 19.6, L8, L25, L26 and 18.7 and compare the counts; no sentence of the contract, `DECISIONS.md` or `PROGRESS.md` says the label is left aside or that the mismatch is known; L26 does not say the refusal reaches the agent.
6. **Carried by reference** (A5 changes none of their lines): round 3's property 19 (S3's accounting of a skipped reply), 20 (votes, titles, `_actions_lost`), 22 for rows 62, 64 to 67, 76, 77 and 79 (re-run in 19.9), 23 (public text; no data of the vessel).

### 19.9 Verified (A5, 2026-11-12, the Architect; read-only, in memory, scratch directory removed afterwards; no pytest and no repository test)

Tree read: `G:\gate-tmp-b934rv1\copy`, detached at `307653071820fc6bfeccbf8fb25a506d2c729518`, clean before and after; the work was done on a `git archive` copy of it. The 33 pairs applied in label order (Part 1 to the LF blobs at that head, Part 2 to the contract blob `7cb38f9f`): every SEARCH once at its turn, at the start of a line, ASCII (and every REPLACE ASCII); the base blobs read equal `git rev-parse` of the head. **Expected blobs after A5:** `content_firewall.py` `d4783b06`, `proactive.py` `96697ba2`, S2's test file `2b8a6a33`, `DECISIONS.md` `7a992507`, `PROGRESS.md` `5b3b7af7`. The three changed `.py` files compile, and `import probos.proactive`, `import probos.ward_room.content_firewall` (either first) and `import probos.runtime` succeed in fresh interpreters (no import cycle from the new module-level import). **The hand runner** (parametrize, `async def`, a fake `tmp_path`; the 8 cases that need `caplog` or `monkeypatch` are not served): S2's whole file on the A5 tree, 73 collected, 65 passed, 0 failed, 8 not served; with A5's test pairs alone on A4's head, the 45 reply-path cases: 27 passed, 15 failed (the six flagged rows of T29, the five flagged rows of T31, T32 to T35), 3 not served, each failure at an assert of its case. **The campaign of record** (the in-memory runner serves each mutant by executing the module's source with one replacement before the tree imports it; S2's 45 reply-path cases; the A5 tree above): rows 61 to 67 and 73 to 88 fail the cases the table names, the amended and the new rows as written in section 9 (row 67's mutant makes T22 raise rather than fail an assert, as it did after A4; row 87 was run twice: the first mutant removed the anchor and the leading spaces together and failed T33 and T34, the second, written in the table, removes the anchor only and fails T34). A Builder whose files carry the blobs above need not repeat it; if a file differs, rerun the row whose line changed. **The pattern equivalence, the oracle table of 19.3 (24 cells and the 12-row round trip, on A4 and on A5), the commands of 19.4 and the architecture check** were run as written there. S3's pairs, split from the amended contract by `split_bf934.py` (44 SEARCH labels and 51 labelled blocks, as before A5) and applied in memory over the A5-amended tree by `apply_search_replace_blocks_bare.py`: `s3-m1` (the new test file), `s3-m2-pairs` (16 pairs and the new `action_accounting.py`), `s3-m2-markers` (3 pairs) and `s3-m3` (2 pairs, the trackers; P3-2 anchors on `DECISIONS.md`'s residual line, which A5-8 leaves unchanged): 21 pairs, 0 failures, so no S3 anchor moves and no sentence of section 7 changes. Unchecked: the real pytest and its collection (`tmp_path` on disk, `caplog`, `monkeypatch`, xdist, suite order), the broad gate, the G2 files (read against the change, not run: `test_ad529_contagion_firewall.py` was not run), any live model, a reply by a low-trust author through the two callers, and the S2 cases that need `caplog` or `monkeypatch`.






