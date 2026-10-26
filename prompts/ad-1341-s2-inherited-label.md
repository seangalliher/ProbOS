# AD-1341 S2: a later crew reads the Ship's Archive as inherited knowledge, labelled with the crew generation it came from, never as its own memory

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-24

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26 (Amendment A2)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26 (Amendment A3)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26 (Amendment A3c, round-three rescope: text and one docstring)

**Status:** build-ready. Slice 2 of 6 of #1569; it does not close the issue. **Tier HIGH:** it changes what every agent reads from the Oracle's archive tier, and a wrong label is the defect the Westworld and minority-report principles exist to prevent (inherited knowledge taken as one's own memory). No new AD or BF number. **Base:** `origin/main` `026a682f`, tree `cad2c0ee25686a5683fd0ba3be35463796b5cf35`, with S1 merged (`prompts/ad-1341-s1-archive-provenance-promotion.md`). **Captain:** nothing in this slice requires the Captain (D10).

**Milestones:** M1 (code and tests, §7.1 to §7.4, including §7.3a and §7.3b from Amendment A2) and M2 (trackers, §8). Each is one Builder delegation and one local commit. The broad gate is the orchestrator's single canonical run, once, after M2 (`scripts/run_test_gate.py --label ad1341-s2 --receipt logs/gates/ad1341-s2.receipt.json`); the Builder runs only the focused gates in §4.

**Tests:** new `tests/test_ad1341_s2_inherited_label.py`: 18 functions, 54 cases. No existing test changes: every existing archive assertion is a substring or metadata check that the label keeps (Absence S2-AV6), and no existing test's text holds a label or the origin notice (S2-AV9).

**Amendment A2 (2026-10-26).** Round 1 of the HIGH review of M1 (`gpt-6.1-sol`, verdict NOT READY) found five findings; the orchestrator reproduced each on the candidate. (1) P2, ordinary reach under a supported setting: AD-1148's bound of a tool result keeps its head and its tail and elides the middle, so with any `tool_result_max_chars` from 1 to about the result's length the tail could carry archive text whose label was elided (the Captain's live cap of 6000 equals the `oracle_query` tool's own cap, so it does not reach it). Fixed: the elision marker carries `ARCHIVE_ORIGIN_NOTICE` whenever the text held a label (D12, §7.3a). (2) P2, ordinary when compaction is on: AD-547's summary could keep an archived fact and drop every label. Fixed: the summary opens with the notice whenever the summarised messages held a label or the notice (D12, §7.3b); which sentence is archived stays unmarked (RS2-9). (3) P2, introduced: the label's words took AD-688 graph-expansion token slots (an unrelated `crew` edge displaced a content edge; 7 more lookups at 100 generations). Fixed: expansion reads an archive parent without its label line (§7.2 pairs 5 and 6); disclosed effect 5's bound is withdrawn. (4) P2, injected-only, introduced: a skipped close whose timeline was only a tab and line breaks numbered a crew (SQLite's one-argument `trim` strips spaces only). Fixed: blankness is decided in Python (§7.1 pairs 3 and 7). (5) P3, injected-only, introduced: `format_refs` replaces the label's closing bracket at a 19-digit id with a 7-digit generation. Recorded with its exact bound (RS2-7); T7 now pins the bound. §5 gains the consumers after the renderers (rows 11 to 15, Absence S2-AV8); RS2-8 records pages an agent asks for at an offset.

**Amendment A3 (2026-10-26).** Round 2, a delta review of A2 (`gpt-6.1-sol`, verdict NOT READY), confirmed A2's claims by execution and found three findings. The orchestrator reproduced finding 1 and traced its root cause. (1) P2, ordinary reach under supported non-default bounds, introduced by A2: `truncate_tool_output` reserves the origin notice in its marker budget, but the AD-1151 durable split (`_durable_head_tail`) still sized its slices from the bare marker. For an elided labelled result, the proportional shrink therefore rounded the durable head down a second time. At equal effective caps, the persisted trace lacked the last character of the head the model saw (caps 401, 1000, 1001, 1999, 2000 and 2999 on the real tool output), against AD-1151's guarantee that the trace is never bounded tighter than the transcript. The Captain's live caps (6,000 context, 8,192 durable) do not reach it. Fixed: one module helper, `_archive_origin_notice`, gives the notice to both, and `_durable_head_tail` reserves its length (keyword `notice_chars`, default 0). The durable slices then fill the same content budget and, at equal caps and the default 2:1 head and tail split, equal the model's (§7.3a pairs 4 to 7; T16; L-4 to L-6). (2) P3, ordinary, not a regression: RS2-8 misstated the reach of paged reads. The offload threshold is 12,288 UTF-8 bytes, which needs no majority of multi-byte characters; a first read at an offset needs no labelled page before it; the pointer frame carries no origin line. Corrected in RS2-8, §5 row 15 and the not-consumers row, D2, D12 and both trackers. (3) P3, ordinary when the targeted lookup is enabled, not a regression: the AD-725 DM lookup cuts its rendered text again (`max_lookup_chars`), which A2's enumeration missed. It is a head-only cut and keeps the label first. Recorded in §5 row 5; S2-AV8 is re-run and narrowed. The reviewer recorded the following with nothing to change: RS2-7, RS2-9, T7, T10, T13 `[none]`, the fail-closed generation read, and the extra SQL call on an empty search. Not changed and reported separately: AD-1151's fixed 2:1 durable split (§9).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| The Oracle returns every archive row to every reader, as `[category] title` then content, with no origin label | present | `oracle_service.py:1134-1157` |
| `_query_archive` is the only path from the archive to anything an agent reads | present | Absence S2-AV1, S2-AV2 |
| `generations` holds one row per close at tier 2 or above, in AUTOINCREMENT order; a skip may have an empty timeline | present | `archive_store.py:201-214`, `:179-182`; `test_ad1341_s1_archive_store.py:359-372` |
| The reset promotes, then records the close; a failed close leaves promoted entries under a timeline that keeps living | present | `__main__.py:3306-3312`, `:3265-3271` |
| The reset and the ontology read the same `ontology/instance_id`, both stripped | present | `__main__.py:3185-3188`; `ontology/loader.py:95-98` |
| The ontology is built after the Oracle; the runtime late-binds Oracle collaborators once it exists | present | `startup/cognitive_services.py:699-707`; `startup/communication.py:787-797`; `runtime.py:3357-3381` |
| Agent-facing renderers keep the head of an Oracle result's content and cut its tail | present | §5, rows 1 to 6 |
| After the renderers, AD-1148 elides the middle of a tool result over its cap, and AD-547 replaces older messages with a model-written summary | present | §5, rows 11 and 14; Absence S2-AV8 |
| `cognitive` may import `knowledge` | present | `tests/test_layer_boundaries.py:51` |
| The live archive's row and close counts | not verified here | §Not verified, item 1 |

## 1. Problem

#1569 Decision item 5: "A later crew retrieves archived knowledge through the Oracle tier, and it arrives marked as inherited: 'from the crew of generation N', not 'your experience'." Its acceptance line: "After a reset, a new crew's Oracle query returns an archived entry labelled as inherited from the earlier generation, never as the agent's own episode."

Today `_query_archive` (`oracle_service.py:1134-1157`) renders an entry as `[convergence_report] <title>\n<content>` with the provenance `Archive/convergence_report (timeline 1a2b3c4d...)`. Nothing tells the reading agent which crew the entry came from, or that it is not its own memory. Five renderers hand that content to agents (§5), and two of them (`format_refs`, the `oracle_query` tool's envelope) never show the provenance at all. S1's `generations` table already records each crew's close (S1 D9: "the generation order S2 will label"), but nothing reads it.

## 2. Solution overview

- **The store numbers the crews.** Every read (`search`, `get_recent`, `entry_by_id`) fills a new defaulted field, `ArchiveEntry.generation`: the place of the entry's timeline's first close among the closes `generations` attributes to a timeline. A timeline with no recorded close has `None`.
- **One label rule, in the store module.** `inheritance_label(entry, *, current_timeline)` returns one of three fixed labels: `[Archived by this crew: a record, not a memory]` for the reading crew's own timeline; `[Inherited from the crew of generation N: not your own memory]`; `[Inherited from an earlier crew: not your own memory]` when no close is recorded.
- **One attachment point.** `_query_archive` makes the label the first line of every archive result's content and adds `generation` and `inherited` to its metadata. Every renderer keeps the head of the content, so the label reaches the agent first on every path.
- **After the renderers (A2).** AD-1148's elision of a tool result's middle and AD-547's compaction summary can separate archive text from its label; each then puts one fixed Ship's Archive origin notice before what it keeps. AD-688's graph expansion reads an archive entry without its label.
- **The Oracle learns this crew's timeline.** `OracleService.attach_current_timeline` (the BF-679 late-bind pattern) is called once by the runtime with the ontology's instance id. Until then, and if it fails, every entry reads as inherited: the safe direction.

No flag, no schema change, no change to the archive's contents, its score or the Oracle's tier order.

## 3. Decisions

- **D1 (premises).** §0. S1's decisions stand; S2 only reads `generations`.
- **D2 (where the label is attached).**
  - **(A) chosen:** the rule and the data in the store module (`inheritance_label`, `ArchiveEntry.generation`: the archive's contract, in its lowest owning layer, as S1 D5 put the record types there); attached once, in `OracleService._query_archive`, the one path from the archive to any agent (Absence S2-AV1, S2-AV2). Downstream of the renderers, the two consumers that cut a middle out of, or rewrite, the text an agent reads (AD-1148's elision, AD-547's compaction) put the fixed `ARCHIVE_ORIGIN_NOTICE`, from the same module, before what they keep (D12, A2). Head-only cuts (`format_refs`, the crew consult, the DM lookup) keep the label first. A page the agent asks for at an offset into an offloaded result is RS2-8 (A3).
  - (B) attach in the store (`search` returns labelled content): rejected. The stored content is what was archived and what `content_sha256` hashes (S1 D3), the Captain's erase prompt shows it, and whether an entry is "this crew's" is a runtime fact the store does not know.
  - (C) attach in each renderer (`query_formatted`, the tool, `format_refs`, the crew consult, the DM lookup): rejected. Five owners, and a sixth renderer would be unlabelled by default: fail-open.
  - (D) label only the `provenance`: rejected. `format_refs` (`oracle_service.py:843`) and the tool's envelope (`provenance.py:78-80`, `oracle_query_tool.py:148`) never render provenance.
- **D3 (how generation N is computed).**
  - **(A) chosen:** N is the 1-based place of the timeline's **first** close among the distinct timelines with a non-blank `timeline_id` in `generations` (blank by Python's `str.strip`, decided in `_generation_numbers`: SQLite's one-argument `trim` strips spaces only, so a tab or a line break would number a crew; A2), ordered by that first close's id (`_GENERATION_ORDER_SQL`). AUTOINCREMENT ids only grow, so the order is the order of the closes. A skip with no instance id numbers no generation (it names no crew). A second close of the same timeline (a reset that recorded its close, then failed in the tier loop and was run again) does not renumber it. Both outcomes (`promoted`, `skipped`) count: a skipped promotion still ended a crew.
  - (B) count every row: rejected. A blank-timeline skip and a re-close would each add a generation, and one crew could carry two numbers.
  - (C) order by `recorded_at`: rejected. Wall-clock time can go backwards; the id cannot.
  - (D) store the number in a new column at write: rejected. A schema change (v2) for a derivable value, computed under a race between two writers.

  Numbering starts at the first close the archive recorded (S1, 2026-10-22): crews before it are not numbered, so "generation 1" is the first crew whose close the archive holds (disclosed effect 3). An entry is attributed to the timeline that first promoted it (S1 D3, disclosed effect 6 there).
- **D4 (the label text and structure).**
  - **(A) chosen:** three fixed, bracketed labels, each saying first where the entry came from and then that it is not the reader's memory: `[Inherited from the crew of generation N: not your own memory]`, `[Inherited from an earlier crew: not your own memory]` (no recorded close, including any AD-524 v0 row), `[Archived by this crew: a record, not a memory]`. The label is the first line of the result's `content`; the metadata carries `generation` (int or None) and `inherited` (bool) for code. It is structural in four ways: one attachment point that no renderer can bypass; the head of the content, which every cap keeps (§5); `source_tier` stays `"archive"`, which no filter maps to episodic; and typed metadata beside the text. `format_refs` keeps the first 119 characters of a line, and an archive line's prefix and generation label take 94 characters plus the digits of the id and of the generation: the whole label survives whenever those digits total at most 25 (every id below 10^18 with any generation below 10^7, and SQLite's largest rowid with a generation below 10^6); at 26 only the closing bracket is cut, and the warning words survive (T7; RS2-7, A2).
  - (B) prose framing in each consumer's preamble: rejected; the preambles already say "not your personal experiences" (`cognitive_agent.py:10546-10548`, `oracle_query_tool.py:89-97`) for the whole block, and they cannot say which crew each entry came from.
  - (C) the earlier crew's callsign in the label ("from Chapel of generation 2"): rejected. A later crew member may carry the same callsign (RS2-3), and the label must never read as the reader's own byline. The author stays in `metadata["author"]`, as before.
  - (D) datamarking or encoding the archived text (spotlighting's stronger forms): rejected. It rewrites the knowledge on every token, and the risk here is our own model misattributing a source, not an injection.
- **D5 (this crew's own entries).** An entry whose timeline is the reading crew's own (the reset refused after promotion committed, `__main__.py:3306-3312`; and every entry once S5's continuous promotion lands) is labelled `[Archived by this crew: a record, not a memory]`, not "inherited", whatever its generation: a false "inherited from generation N" would misstate what the crew is (Westworld). The Oracle learns the timeline through `attach_current_timeline`, called by the runtime once the ontology exists (`runtime.py:3357`). Not attached, or failed: every entry reads as inherited. That is the safe direction of the two possible errors: the minority-report principle forbids presenting inherited knowledge as one's own, and the reverse error only understates the crew's authorship.
  - Rejected: read `ontology/instance_id` from the Oracle (a cognitive service reaching into the data directory, outside the ontology that owns it); pass it at construction (the ontology does not exist yet at `cognitive_services.py:699-707`).
- **D6 (flag and default).**
  - **(A) chosen:** no flag; always on.
  - (B) a flag defaulting on: rejected. Its off position presents inherited knowledge unlabelled, which is a switch for violating the two principles, and nothing here needs calibrating.
  - (C) a flag defaulting off: rejected; the acceptance line fails by default.

  **Scope proof in place of a byte-identity proof:** only archive-tier results change (one function builds them, Absence S2-AV2), and an archive with no matching row returns nothing, as before. Every other tier's output is byte-identical: no other line of `query`, `query_formatted`, `query_refs` or `format_refs` changes. AD-688's graph expansion reads an archive parent's content without its label line (`_expansion_text`, A2), so the tokens it tries, its lookups and the edges it adds are the base's (T15). Outside the Oracle, `truncate_tool_output` and `SessionCompactor` change only for text that holds a label or the notice (`holds_archive_label`); for any other text they are byte-identical (the controls in T11 and T13, and the AD-1148 and AD-547 suites, unedited).
- **D7 (score and tier order).**
  - **(A) chosen:** the archive's score and the Oracle's tier order are unchanged. The archive admits a row only when the whole query text is a substring of its title or content (`archive_store.py:482-484`), so a hit is a strong match; the label, not the rank, is what keeps an inherited entry from being taken as the agent's own; no consumer turns a score into "own evidence" (AD-1294 already renders it as relevance, `provenance.py:25-28`).
  - (B) a constant discount for inherited entries: rejected. An uncalibrated cross-tier constant, the shape BF-684 warns against (`oracle_service.py:162-177`).
  - (C) a keyword-overlap relevance like Tier 3: rejected for this slice; it changes ranking for every archive hit and is a separate question (RS2-5).
- **D8 (the principles).** Westworld (agents know what they are: `docs/research/metacognitive-architecture.md:115-117`, "LLM + KnowledgeStore ≠ personal memory"): every label states the entry's true origin, including "this crew" (D5). Minority report (inherited knowledge is never presented as an agent's own memory): every label ends with "not your own memory" or "not a memory"; `source_tier` stays `"archive"`; AD-607e's shard filter and the tool's sovereign-tier filter are unchanged and keep the archive in the commons (`oracle_service.py:850-878`, `oracle_query_tool.py:337-342`). This is culture in the Captain's nature/culture/nurture amendment (#1569, 2026-10-16): labelled as inherited from generation N.
- **D9 (tests that pinned the old shape).** None changes. The archive assertions in `test_ad524_ships_archive.py:118-121, 147`, `test_ad1341_s1_archive_store.py:407-411`, `test_ad1341_s1_promotion.py:382-384` and `test_ad1341_s1_reset_and_erase.py:613-615` are substring, tier and metadata checks the label keeps; `_FakeArchiveStore` (`test_ad524_ships_archive.py:191-198`) returns real `ArchiveEntry` objects, which default `generation` to None (Absence S2-AV6).
- **D10 (the Captain).** Nothing here meets a "Still requires the Captain" condition: it implements a principle the Captain set (#1569 item 5) without weakening any control. The label wording is in the envelope; the Captain may overrule it after the fact.
- **D11 (tier).** HIGH (see the status line).
- **D12 (consumers that cut or summarise an Oracle result after its renderer; A2).**
  - **(A) chosen:** one fixed notice, `ARCHIVE_ORIGIN_NOTICE`, and one detector, `holds_archive_label` (an inheritance label's opening, the own-crew label or the notice anywhere in the text), both in the store module beside the labels. `truncate_tool_output` (AD-1148: every tool result at the loop's message boundary, the AD-1151 trace and the `oracle_query` tool's own last bound) appends the notice to its elision marker whenever the text holds a label. The tail always follows the marker, so every fragment cut loose from its label is introduced by the notice; the marker is sized with the notice, so the result still never exceeds `max_chars`. The AD-1151 durable split reserves the same notice (`_durable_head_tail`'s keyword `notice_chars`, given by the module helper `_archive_origin_notice` that the bound also uses; A3). When the context head is exactly twice the context tail (the default 4000:2000), the persisted output of each tool result that AD-1151's aggregate trace budget keeps therefore contains what the model saw (the same slices when the model's were scaled to an equal cap), as AD-1151's upward clamp intends. That budget (`tool_trace_max_bytes`, default 262,144 bytes) still elides whole outputs, and any other configured split can persist a head or tail tighter than the model's, on the base too (the pre-existing gap in §9). `_durable_head_tail` is private; its new keyword has a default, so its two calls stay valid. `SessionCompactor` (AD-547, in every loop that compacts) opens its summary with the notice whenever the messages it summarised held a label or an earlier notice, so a second compaction keeps it. Code adds it, outside the summarising model's control. No signature, return shape, config field or event changes; label-free text is byte-identical, and the unbounded path returns before the scan. A false positive (a file that quotes a label, such as `archive_store.py` read through `read_file`) only adds the notice: the safe direction.
  - (B) bound at the source (the loop's cap reaches the tool, which drops whole entries): rejected. The cap is the loop's and would have to cross the tool contract, and it would cover neither compaction nor any other tool that returns archive text.
  - (C) an opt-out of AD-1148's elision for self-bounded tools: rejected. It removes the context cap AD-1148 exists to hold, and the tool's own last bound uses the same function.
  - (D) record finding 1 and narrow criterion 3: rejected. Any `tool_result_max_chars` from 1 to about 4,100 is a supported setting that reaches it on a normal three-entry result.
  - For compaction: an instruction in the summariser's prompt alone (soft: no structural guarantee, and it changes every compaction); pinning or dropping archive tool messages (changes what compaction keeps and its budget, and a tool message cannot be kept without its AD-1146 group); recording it as restatement only (software, not the agent, removed a label the agent could see): all rejected.
  - Limit: the notice cannot say which entry or generation a cut fragment came from, or which sentence of a summary is archived (RS2-9).

**Disclosed effects.**
1. Every archive result an agent reads opens with its label line, and its metadata gains `generation` and `inherited`. `GET /oracle` (the Captain's surface, `routers/system.py:711-730`) shows the same.
2. Each archive read issues one more small query (the `generations` order). Measured once by the round-1 reviewer on 10,004 close rows: an empty search took 0.44 ms on the base and 22.9 ms here. If that read fails, every archive hit of the query is dropped; the other tiers still answer.
3. Generations are numbered from the first close the archive recorded; earlier crews are not numbered.
4. Several vessels sharing one archive file (S1 disclosed effect 7) share one generation count, and each reads the other's entries as inherited from "generation N" of that shared count (RS2-1).
5. None for AD-688's graph expansion (A2): it reads an archive parent's content without its label line, so its tokens, `find_edges` lookups and edges are the base's (T15). M1 as first built read the label: the round-1 reviewer saw an unrelated `crew` edge displace a content edge, and 7 more lookups at 100 recorded generations (RS2-4, resolved).
6. A tool result that holds an archive label and exceeds AD-1148's cap carries `ARCHIVE_ORIGIN_NOTICE` after its elision marker; its head and tail shrink by the notice's length, and the cap holds. The AD-1151 durable trace bounds through the same function, carries it too, and reserves it in its own slices, so when the context head is exactly twice the context tail (the default) each persisted output that AD-1151's aggregate trace budget keeps contains what the model saw (A3, T16); the budget still elides whole outputs, and any other configured split can persist a tighter head or tail, as on the base (§9). An AD-547 summary of messages that held a label opens with the notice.

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Files (§7, §8) | Focused gate |
|---|---|---|
| **M1** the label | 7.1 `src/probos/knowledge/archive_store.py`; 7.2 `src/probos/cognitive/oracle_service.py`; 7.3 `src/probos/runtime.py`; 7.3a `src/probos/cognitive/swe_harness/agentic_loop.py`; 7.3b `src/probos/cognitive/swe_harness/session_compactor.py`; 7.4 new `tests/test_ad1341_s2_inherited_label.py` | `tests/test_ad1341_s2_inherited_label.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad524_ships_archive.py tests/test_bf919_archive_isolation.py tests/test_bf679_oracle_records_reader_identity.py tests/test_ad1139_oracle_query_tool.py tests/test_ad1141_crew_loop_sigma.py tests/test_ad696_agentic_oracle_retrieval.py tests/test_ad688_oracle_graph_integration.py tests/test_ad686_oracle_semantic_tier.py tests/test_bf675_oracle_tier5_sovereignty.py tests/test_ad695_ship_health_oracle.py tests/test_layer_boundaries.py tests/test_ad680_public_runtime_api.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1148_tool_result_bounds.py tests/test_ad547_session_compactor.py tests/test_ad1142_crew_child_compaction.py tests/test_ad1167_conversational_compaction.py tests/test_ad1146_multiturn_messages.py tests/test_ad1147_parallel_tools.py tests/test_ad1151_durable_tool_outputs.py tests/test_ad545_agentic_loop.py tests/test_bf728_structured_tool_output.py tests/test_ad1240_tool_result_delivery.py tests/test_ad1324_srp_layout.py tests/test_ad1279_fault_finds_its_trace.py tests/test_bf760_trace_records_the_tools_length.py tests/test_bf761_budget_is_spent_on_real_content.py tests/test_ad1191_delegated_evidence.py tests/test_ad1316_real_effect_routes.py tests/test_ad1153_browser_agentic_loop.py tests/test_ad1203_trace_routes.py`, then `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-1341-s2-inherited-label.md` (§12) |
| **M2** trackers | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

Write the new test file first and run it on the base: it must fail at import (`inheritance_label`), then each test must fail at the assertion §6 names once the names exist. If a test outside §7 fails only because an archive result's content now opens with the label, stop and report it (Absence S2-AV6 says none does); never delete or loosen a test.

## 5. Consumers of every value this changes

| # | Value | Consumer (renderer an agent reads) | What it keeps | Effect |
|---|---|---|---|---|
| 1 | archive `OracleResult.content` | `query_formatted` (`oracle_service.py:694-753`): the ORACLE recall tier (`cognitive_agent.py:11579-11586`, framed at `:10545-10552`) and the `oracle_lookup` sub-task (`sub_tasks/query.py:274-280`) | `content[:300]` (`:736`), after `provenance` and the score | label first |
| 2 | same | the `oracle_query` tool (`oracle_query_tool.py:260-263`) through `ProvenanceEnvelope.render` (`provenance.py:78-80`) | marker line, then content; `_cap_entry` keeps the head (`:119-129`) | label first |
| 3 | same | `format_refs(query_refs(...))` (`sub_tasks/query.py:346-362`; `oracle_service.py:788, 843-845`) | `[tier] ref_id (score) ` then `snippet[:200]`, the line cut at 119 characters plus "…" | label first and whole (T7) |
| 4 | same | the AD-1141 crew consult (`crew_executor.py:697-745, 1808-1822`) | provenance marker, then content with whitespace collapsed (`:740`), cut at 400 (`:742-745`) | label first |
| 5 | same | the AD-725 DM lookup (`dm_targeted_lookup.py:196-206, 242-262`), then `maybe_lookup`'s head cut (`truncated = content[: self._cfg.max_lookup_chars]`, `:156`; `max_lookup_chars` 1,500 by default, `config_models/agentic.py:184`), placed whole in the DM as a Targeted Recall block (`routers/agents.py:3152-3156, 3391-3392`; `dm_targeted_lookup.enabled`, off by default) | `repr` of each result, then its first `max_lookup_chars` characters | label first in `content=`; a head-only cut keeps it (round 2: rendered 8,661, model input 1,500, label before content; A3) |
| 6 | same | AD-688 graph expansion (`oracle_service.py:1473-1525`) | tokens of `parent.content`, without its first line for an archive parent (`_expansion_text`, A2) | none: the base's tokens, lookups and edges (T15) |
| 7 | archive `metadata` gains `generation`, `inherited` | `routers/system.py:729-730` (Captain's `GET /oracle`); `query_refs` keeps only its whitelist (`oracle_service.py:790-794`) | | new keys; refs unchanged |
| 8 | `ArchiveEntry.generation` (defaulted) | `_query_archive`; `__main__.py:3393` (the erase prompt prints title, kind, ref, timeline only); `_FakeArchiveStore` | | none for the CLI; fakes default to None |
| 9 | `_row_to_entry(row, generations)` | the store's three reads only (Absence S2-AV4) | | internal |
| 10 | `OracleService.attach_current_timeline` | `runtime.py` once (T9) | | new |
| 11 | an `oracle_query` `ToolResult`'s output, labels inside | AD-1148 `truncate_tool_output` (`agentic_loop.py:188-236`) at the loop's message boundary: `format_tool_result_content` (`:820-855`; structured `build_tool_result_messages`, `:858-879`; flattened delegated or delivered results, `:2158`) and `_bound_tool_output` (`:2869-2871`; flattened, `:2166`) | head and tail; the middle elided past `tool_result_max_chars` (shipped 0, off; the Captain's live 6000 equals the tool's own cap, so it never elides an `oracle_query` result) | head: each label before its entry; tail: `ARCHIVE_ORIGIN_NOTICE` first (A2; T11, T12) |
| 12 | same | `OracleQueryTool._bounded` (`oracle_query_tool.py:353-372`), the tool's own last bound at 6,000 | a no-op: `_render` already fits (`:139-161`) | the notice too, if it ever elides |
| 13 | same | AD-1151 durable trace (`agentic_loop.py:545-553`; persisted by `agentic_dispatch.py:4364-4529` with `origin="crew_trace"`) | head and tail at the durable cap | the notice too; an audit record, not a model request (Not verified item 6) |
| 14 | the loop's message history, tool results included | AD-547 `SessionCompactor.compact` (`session_compactor.py:67-196`; built at `cognitive_agent.py:4945`, `crew_executor.py:424`, `startup/finalize.py:1816`; called at `agentic_loop.py:2293`) | the system prompt, the first user message and the last five messages verbatim; the rest replaced by a fast-tier summary | the notice opens the summary when the summarised messages held a label or the notice (A2; T13); which sentence is archived is not marked (RS2-9) |
| 15 | same | paged readers: an AD-1240 workspace payload read with `read_file` at an offset (`result_offload.py:481-488, 564-606`), and `recall_artifact`'s pages (`recall_artifact_tool.py:290-308`) | the window the agent asks for, at any offset, the first read included | the pointer frame carries no origin line, and any window may open inside an entry whose label lies before it (RS2-8, corrected in A3) |
| — | not consumers downstream: `agentic_loop.py:2600-2618` and `agentic_dispatch.py:3954-3964` (fits-whole checks for the work-pull and owned-steps tools: the whole text or `None`); `repair_verification.py:222-234` (a QA retry reads only `error`); `result_offload.py:564-565` (a result at or under 12,288 UTF-8 bytes stays on the legacy path, rows 11 and 14; above it, AD-1240 offloads the result whatever its character count: row 15 and RS2-8) | | | none |
| — | not consumers: `introspect.py:846-848`, `organizer_agents.py:151-153`, `commands_knowledge.py:91-93` query only `semantic` (and `episodic`); the archive is not in their tiers | | | none |

## 6. Tests

All in `tests/test_ad1341_s2_inherited_label.py`. On the base, and on M1 as first built, every test fails at import (`ImportError: cannot import name 'ARCHIVE_ORIGIN_NOTICE'`); the "First assertion to fail" column names the assertion that fails once the names exist but the behaviour is the base's.

| Id | Test | Property | First assertion to fail on the base |
|---|---|---|---|
| T1 | `test_each_entry_carries_its_crews_generation_from_every_read` | D3 on the real store: closes `""` (skip), `"\t\r\n"` (skip; A2), alpha, beta (skip), alpha again, gamma give alpha 1, beta 2, gamma 3, an unclosed timeline None, through `search`, `get_recent` and `entry_by_id`; the store's content is unlabelled | `{entry.timeline_id: entry.generation ...} == _EXPECTED` (no attribute `generation`; on M1's SQL, alpha 2) |
| T2 | `test_an_entry_whose_crew_has_no_recorded_close_has_no_generation[empty-generations, v0-row]` | no close, or an AD-524 v0 row: None, and the earlier-crew label | `entry.generation is None` (no attribute) |
| T3 | `test_the_label_says_where_an_entry_came_from[generation, no-current, unrecorded, zero, bool, str, this-crew-closed, this-crew-open, both-empty]` | D4, D5 on the pure rule, with exact types (a `bool` or `str` generation is no generation; an empty current timeline matches nothing) | `label == expected` |
| T3b | `test_the_fixed_labels_read_as_decided` | the two fixed texts | `LABEL_THIS_CREW == ...` |
| T4 | `test_the_oracle_puts_the_label_first_in_each_archive_result` | `_query_archive`: content is exactly `label\n[category] title\ncontent`; `generation` and `inherited` in metadata; tier `archive`; provenance unchanged | `result.content.split("\n", 1)[0] == label` (base: `[convergence_report] t-alpha`) |
| T5 | `test_an_entry_this_crew_archived_is_its_own_record_never_inherited` | D5: attached (with a trailing newline, stripped) the own timeline reads `LABEL_THIS_CREW`, `inherited` False; unattached, nothing does | `labels == {...}` |
| T5b | `test_the_oracle_takes_its_timeline_only_as_text[none, int, bytes]` | `TypeError` | `pytest.raises(TypeError)` (base: `AttributeError`, no method) |
| T6 | `test_every_path_from_the_archive_to_an_agent_carries_the_label_before_the_content[query-formatted, oracle-tool, memory-refs, crew-consult, dm-lookup]` | each real renderer, on 2,400-character entries so every cap cuts: every entry header is preceded by its label, and all three labels appear | `_every_entry_is_labelled_first(text) == 3` (base: the header follows the score or marker, not a label) |
| T7 | `test_the_label_survives_the_tightest_cap_any_consumer_applies[whole-label, warning-words]` | `format_refs` with SQLite's largest rowid (19 digits): with generation 999,999 the whole label survives the 120-character line; with 1,000,000 the warning words do (RS2-7, A2) | `survives in refs_text` (passes on M1: it pins the bound, not a change) |
| T8 | `test_after_two_resets_a_later_crew_reads_each_generations_knowledge_labelled_as_inherited[default, full]` | **the real seam:** the real `probos reset` closes crew 1, crew 2 boots under a new instance id, publishes a finding and is reset; crew 3's real `OracleService` (attached to its own timeline) and the real `oracle_query` tool and `query_formatted` give crew 1's entries "generation 1" and crew 2's "generation 2", each before its content; nothing reads as crew 3's own; every result's tier is `archive` | `generations == {(_SHIP, 1), (_SECOND, 2)}` |
| T9 | `test_only_the_runtime_tells_the_oracle_its_timeline_and_it_reads_the_ontologys_instance_id` | census: `attach_current_timeline` is called once in `src`, in `runtime.py`, with the ontology's instance id | `calls == [...]` (base: `[]`) |
| T10 | `test_the_timeline_a_boot_attaches_is_the_one_the_reset_closes` | D5's premise on the real code: the instance id the real ontology loader gives a boot (what T9's expression attaches) is the timeline the real reset archives under and closes, generation 1; the next boot's id differs | passes on M1: the round-1 reviewer's hand proof, made a test |
| T11 | `test_an_elided_tool_result_introduces_what_it_kept_after_the_cut_with_the_archive_origin[1000, 2000, 3000]` | A2 finding 1, `truncate_tool_output` on the real tool's output: within the cap, each entry header in the head follows its label and the tail opens with `ARCHIVE_ORIGIN_NOTICE`; label-free text gains no notice | `tail.startswith(f"{ARCHIVE_ORIGIN_NOTICE}\n")` |
| T12 | `test_a_bounded_archive_tool_result_reaches_the_next_model_request_with_its_origin[flattened, structured]` | A2 finding 1 across the seam: the real tool, registered and run by the real `ToolExecutor` and `AgenticLoop` at `tool_result_max_chars=2000`; the next `LLMRequest` (its prompt, or its `role:"tool"` message) | `tail.startswith(f"{ARCHIVE_ORIGIN_NOTICE}\n")` |
| T13 | `test_a_compaction_summary_opens_with_the_archive_origin_when_it_summarised_archive_text[label, earlier-notice, none]` | A2 finding 2, the real `SessionCompactor` with a summariser that names no source: the summary opens with the notice after a label or an earlier notice, and is unchanged otherwise | `summaries == [...]` |
| T14 | `test_archive_text_is_recognised_by_any_label_or_the_notice[generation, earlier-crew, this-crew, notice, plain, unbracketed]` | `holds_archive_label`; the notice is clean under the real `_CAPABILITY_GAP_RE` (AD-1148 DD-3, AD-1142 DD-11) | `holds_archive_label(text) is holds` |
| T15 | `test_graph_expansion_reads_an_archive_entry_without_its_label` | A2 finding 3: the real Oracle and edge store; expansion looks up exactly the tokens of the entry without its label, and the label's `crew` edge is not reached | `recording.tokens == _extract_entity_tokens(...)` |
| T16 | `test_the_durable_trace_keeps_every_character_the_model_saw_of_an_archive_tool_result[401, 402, 1000, 1001, 1999, 2000, 2000-raised-from-1000, 2001, 2999, 3000]` | A3 (round-2 finding 1), AD-1151's guarantee for a labelled result: the real `oracle_query` output goes through the real trace writer (`WorkItemAgenticExecutor._persist_tool_trace`, `resolve_tool_trace_bounds`, `build_tool_trace_payload`) into a real `FilesystemAttachmentStore`. At equal effective caps, including a durable cap below the context cap that the resolver raises, the persisted head starts with the head the model saw, both tails open with the notice, and the persisted tail ends with the model's | base: `seen_rest.startswith(notice) and kept_rest.startswith(notice)` (no notice); A2's candidate: `kept_head.startswith(seen_head)` |

**Tests-first (A2).** Against M1 as first built (`d616da93`), the file fails at collection (`ARCHIVE_ORIGIN_NOTICE`). On M1 with A2's §7.1, but not §7.2 pairs 5 and 6, §7.3a or §7.3b, exactly 18 cases fail: T11 (3), T12 (2), T13 `[label]` and `[earlier-notice]` (2), T15 (1) and T16 (10, at the notice assertion: no notice is added). With §7.1 pair 7's filter reverted to M1's SQL, T1, T4, T5 and T6 fail (8 cases). With §7.1 alone on the base, 33 of 54 fail (T16's 10 among them). T7, T10, T13 `[none]` and T14 pass on M1's behaviour: they pin a bound, a premise, a control and the detector.

**Tests-first (A3).** On A2's candidate (`d3da5d72`: §7.3a pairs 1 to 3 only), exactly 7 cases fail, all in T16 at `kept_head.startswith(seen_head)`: `[401]`, `[1000]`, `[1001]`, `[1999]`, `[2000]`, `[2000-raised-from-1000]`, `[2999]` (the round-2 probe's measurements; the orchestrator confirms by running). `[402]`, `[2001]` and `[3000]` pass there, because the second rounding happens to give the same head at those caps: they are controls. Every other case passes on A2's candidate. With pair 6's `- notice_chars` removed or pair 7's argument set to 0, the same 7 fail (L-5, L-6).

## 7. The contract

### 7.1 `src/probos/knowledge/archive_store.py`

Pair 1 (the module docstring):

SEARCH:
```python
Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.
```
REPLACE:
```python
Each entry records the timeline (instance) it came from, its source kind and
reference, the content's SHA-256, its classification (``ship`` or ``fleet``: a
later crew reads every entry) and when it was archived. ``generations`` records
each crew generation's close at a reset of tier 2 or above, including a
promotion the Captain skipped and why.

AD-1341 S2: ``generations`` also numbers the crews. A timeline's generation is
its first close's place among the closes attributed to a timeline, and every read
fills an entry's ``generation`` from it. ``inheritance_label`` is what an agent
reads first about an archived entry: inherited from the crew of generation N, or
from an earlier crew, or archived by this crew; never its own memory. The Oracle's
archive tier (``OracleService._query_archive``) is the one place that attaches it.
```

Pair 2 (the entry's generation):

SEARCH:
```python
    classification: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()


#: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
```
REPLACE:
```python
    classification: str = ""
    author_did: str = ""
    source_episode_ids: tuple[str, ...] = ()
    # AD-1341 S2 (D3): the crew generation that archived it: 1 for the first crew whose close ``generations``
    # records. None when its timeline has no recorded close (an AD-524 entry, or a close that failed).
    generation: int | None = None


#: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
```

Pair 3 (the generation order and the label rule):

SEARCH:
```python
_SQLITE_MAX_ROWID = 2**63 - 1


def _valid_reason(reason: object) -> str:
```
REPLACE:
```python
_SQLITE_MAX_ROWID = 2**63 - 1

# AD-1341 S2 (D3): the generation order. A timeline's generation is its first close's place among the closes
# attributed to a timeline: a skip with no instance id numbers none, and a second close of one timeline does not
# renumber it. AUTOINCREMENT ids only grow, so the first close's id orders the crews. Which timelines are blank is
# decided in Python (``_generation_numbers``, A2): SQLite's one-argument ``trim`` strips spaces only.
_GENERATION_ORDER_SQL = (
    "SELECT timeline_id FROM generations "
    "GROUP BY timeline_id ORDER BY min(id)"
)

#: AD-1341 S2 (D4, D5): what an agent reads first about an entry its own crew archived.
LABEL_THIS_CREW = "[Archived by this crew: a record, not a memory]"

#: AD-1341 S2 (D4): what an agent reads first about an inherited entry whose crew generation is not recorded.
LABEL_EARLIER_CREW = "[Inherited from an earlier crew: not your own memory]"

#: AD-1341 S2 (A2, D12): what an agent reads before text in which a consumer may have cut or summarised away an
#: archive label: after AD-1148's elision marker, and at the head of an AD-547 compaction summary.
ARCHIVE_ORIGIN_NOTICE = (
    "[Ship's Archive: some text here may come from archived entries whose labels were cut or summarised away: "
    "archived knowledge, not your own memory]"
)

# AD-1341 S2 (A2): text that holds any of these holds Ship's Archive knowledge. Every inherited label opens with the
# first; the notice is here so that a second compaction keeps it.
_ARCHIVE_ORIGINS = ("[Inherited from ", LABEL_THIS_CREW, ARCHIVE_ORIGIN_NOTICE)


def holds_archive_label(text: str) -> bool:
    """AD-1341 S2 (A2, D12): whether ``text`` holds an inheritance label or ``ARCHIVE_ORIGIN_NOTICE``.

    A consumer that cuts a tool result's middle or summarises messages asks this of the text it cuts or summarises
    and, when it is true, puts ``ARCHIVE_ORIGIN_NOTICE`` before what it keeps. A false positive (a file that quotes a
    label) only adds the notice: the safe direction.
    """
    return any(origin in text for origin in _ARCHIVE_ORIGINS)


def inheritance_label(entry: ArchiveEntry, *, current_timeline: str) -> str:
    """AD-1341 S2 (#1569): the label an agent reads before an archived entry (D4).

    The Westworld Principle (agents know what they are) and the minority-report principle (inherited knowledge is
    never presented as an agent's own memory): every label says where the entry came from and that it is not the
    reader's memory. An entry of ``current_timeline`` (the reading crew's own instance id) was archived by this
    crew, whatever its generation (D5); any other entry is inherited, from the crew of its generation when one is
    recorded and from an earlier crew otherwise. An empty ``current_timeline`` matches nothing.
    """
    if current_timeline and entry.timeline_id == current_timeline:
        return LABEL_THIS_CREW
    if type(entry.generation) is int and entry.generation >= 1:
        return f"[Inherited from the crew of generation {entry.generation}: not your own memory]"
    return LABEL_EARLIER_CREW


def _valid_reason(reason: object) -> str:
```

Pair 4 (`entry_by_id`):

SEARCH:
```python
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        return self._row_to_entry(row) if row else None
```
REPLACE:
```python
        cursor = await self._db.execute(f"SELECT {_ENTRY_COLUMNS} FROM archive WHERE id = ?", (entry_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_entry(row, await self._generation_numbers())
```

Pair 5 (`search`):

SEARCH:
```python
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]
```
REPLACE:
```python
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        generations = await self._generation_numbers()  # AD-1341 S2

        return [self._row_to_entry(row, generations) for row in rows]
```

Pair 6 (`get_recent`):

SEARCH:
```python
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]
```
REPLACE:
```python
            (limit,),
        )
        rows = await cursor.fetchall()
        generations = await self._generation_numbers()  # AD-1341 S2
        return [self._row_to_entry(row, generations) for row in rows]
```

Pair 7 (the order read and the row mapping's signature):

SEARCH:
```python
    @staticmethod
    def _row_to_entry(row: Any) -> ArchiveEntry:
        return ArchiveEntry(
            id=row[0],
```
REPLACE:
```python
    async def _generation_numbers(self) -> dict[str, int]:
        """AD-1341 S2: each timeline's generation, from ``generations`` (D3). A read, so it takes no lock (D16)."""
        cursor = await self._db.execute(_GENERATION_ORDER_SQL)
        rows = await cursor.fetchall()
        # A close whose timeline is blank by ``str.strip`` names no crew, so it numbers none (A2: SQLite's ``trim``
        # strips spaces only, so the filter is here, not in the SQL).
        crews = [row[0] for row in rows if row[0].strip()]
        return {timeline: number for number, timeline in enumerate(crews, start=1)}

    @staticmethod
    def _row_to_entry(row: Any, generations: dict[str, int]) -> ArchiveEntry:
        return ArchiveEntry(
            id=row[0],
```

Pair 8 (the row mapping fills it):

SEARCH:
```python
            author_did=row[13],
            source_episode_ids=tuple(json.loads(row[14])) if row[14] else (),
        )
```
REPLACE:
```python
            author_did=row[13],
            source_episode_ids=tuple(json.loads(row[14])) if row[14] else (),
            generation=generations.get(row[1]),
        )
```

### 7.2 `src/probos/cognitive/oracle_service.py`

Pair 1 (import):

SEARCH:
```python
from probos.cognitive.episodic import reciprocal_rank_fusion  # AD-979c / BF-684
from probos.types import (  # AD-462f (types.py has no reverse dep on oracle_service)
```
REPLACE:
```python
from probos.cognitive.episodic import reciprocal_rank_fusion  # AD-979c / BF-684
from probos.knowledge.archive_store import LABEL_THIS_CREW, inheritance_label  # AD-1341 S2
from probos.types import (  # AD-462f (types.py has no reverse dep on oracle_service)
```

Pair 2 (the attribute):

SEARCH:
```python
        self._reader_identity_resolver = reader_identity_resolver
        self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
```
REPLACE:
```python
        self._reader_identity_resolver = reader_identity_resolver
        self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
        # AD-1341 S2 (D5): this crew's timeline (the ship's instance id), so an archive entry this crew archived is
        # labelled as its own record and every other entry as inherited. "" until the runtime attaches it.
        self._current_timeline = ""
```

Pair 3 (the late bind):

SEARCH:
```python
        self._reader_identity_resolver = resolver

    def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
```
REPLACE:
```python
        self._reader_identity_resolver = resolver

    def attach_current_timeline(self, timeline_id: str) -> None:
        """AD-1341 S2: Late-bind this crew's timeline, the ship's instance id (``ontology/instance_id``).

        Used by the runtime because the ontology, which loads the instance id, is built after the cognitive phase
        that builds OracleService. Idempotent — last write wins. Until it is attached no archive entry is labelled
        as this crew's own: every entry reads as inherited, the safe direction (D5).
        """
        if type(timeline_id) is not str:
            raise TypeError("AD-1341 S2: the current timeline is the ship's instance id, a string")
        self._current_timeline = timeline_id.strip()

    def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
```

Pair 4 (`_query_archive`):

SEARCH:
```python
        """Query the Ship's Archive for cross-reset knowledge."""
        entries = await self._archive_store.search(query_text, limit=k)
        results: list[OracleResult] = []
        for entry in entries:
            age_days = max(1, (time.time() - entry.archived_at) / 86400)
            score = min(1.0, 1.0 / (1.0 + age_days * 0.01))

            results.append(OracleResult(
                source_tier="archive",
                content=f"[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results
```
REPLACE:
```python
        """Query the Ship's Archive for cross-reset knowledge (AD-524).

        AD-1341 S2 (#1569): every result's content opens with its inheritance label (``inheritance_label``), so
        each renderer of an Oracle result, and every cap that keeps the head of the text, hands the agent the label
        before the archived knowledge. This is the one path from the archive to an agent (D2). The score and the
        provenance are unchanged (D7).
        """
        entries = await self._archive_store.search(query_text, limit=k)
        results: list[OracleResult] = []
        for entry in entries:
            age_days = max(1, (time.time() - entry.archived_at) / 86400)
            score = min(1.0, 1.0 / (1.0 + age_days * 0.01))
            label = inheritance_label(entry, current_timeline=self._current_timeline)

            results.append(OracleResult(
                source_tier="archive",
                content=f"{label}\n[{entry.category}] {entry.title}\n{entry.content}",
                score=score,
                metadata={
                    "archive_id": entry.id,
                    "timeline_id": entry.timeline_id,
                    "category": entry.category,
                    "author": entry.author_callsign or entry.author_agent_type,
                    "archived_at": entry.archived_at,
                    "generation": entry.generation,
                    "inherited": label != LABEL_THIS_CREW,
                },
                provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)",
            ))
        return results
```

Pair 5 (A2: AD-688's graph expansion reads an archive parent without its label):

SEARCH:
```python
        seen.add(token)
        out.append(token)
        if len(out) >= 16:
            break
    return out


def _record_graph_hit(
```
REPLACE:
```python
        seen.add(token)
        out.append(token)
        if len(out) >= 16:
            break
    return out


def _expansion_text(result: OracleResult) -> str:
    """AD-1341 S2 (A2): the text AD-688's graph expansion reads tokens from.

    An archive result's first line is its inheritance label (``_query_archive``), there for the reading agent and not
    knowledge about the entry. Expansion reads the entry without it, so an archive parent's tokens, lookups and edges
    are those of the archived text alone.
    """
    if result.source_tier == "archive":
        return result.content.partition("\n")[2]
    return result.content


def _record_graph_hit(
```

Pair 6 (the call site):

SEARCH:
```python
        for parent in parents:
            tokens = _extract_entity_tokens(parent.content)
            if not tokens:
```
REPLACE:
```python
        for parent in parents:
            # AD-1341 S2 (A2): an archive parent's tokens come from its text, not from its label's words.
            tokens = _extract_entity_tokens(_expansion_text(parent))
            if not tokens:
```

### 7.3 `src/probos/runtime.py`

SEARCH:
```python
                logger.warning(
                    "BF-679: failed to attach the reader-identity resolver to "
                    "OracleService; Tier 2 stays anonymous, so agents keep the "
                    "ship-wide commons but not their own private records",
                    exc_info=True,
                )

        # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
```
REPLACE:
```python
                logger.warning(
                    "BF-679: failed to attach the reader-identity resolver to "
                    "OracleService; Tier 2 stays anonymous, so agents keep the "
                    "ship-wide commons but not their own private records",
                    exc_info=True,
                )

        # AD-1341 S2 (#1569): the Oracle labels a Ship's Archive entry this crew archived as its own record and every
        # other entry as inherited, so it needs this crew's timeline: the instance id the ontology loaded. A failure
        # degrades to "every entry inherited", never to an inherited entry labelled as this crew's (D5).
        if self._oracle_service is not None and self.ontology is not None:
            try:
                self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)
            except Exception:
                logger.warning(
                    "AD-1341 S2: failed to attach this crew's timeline to OracleService; every Ship's Archive "
                    "entry reads as inherited, including any this crew archived",
                    exc_info=True,
                )

        # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
```

### 7.3a `src/probos/cognitive/swe_harness/agentic_loop.py`

Pair 1 (import):

SEARCH:
```python
from probos.fault_detection import ToolFaultCapture
from probos.fault_report import canonical_tool_id, error_signature
```
REPLACE:
```python
from probos.fault_detection import ToolFaultCapture
from probos.fault_report import canonical_tool_id, error_signature
from probos.knowledge.archive_store import ARCHIVE_ORIGIN_NOTICE, holds_archive_label  # AD-1341 S2 (A2)
```

Pair 2 (the marker carries the origin notice when the text held a label):

SEARCH:
```python
    # Size the marker against the largest omission this call can report, so the
    # marker rendered with the real (smaller or equal) count is always within
    # the budget reserved for it here.
    sizing_marker = _ELISION_MARKER.format(omitted=len(text))
    content_budget = max_chars - len(sizing_marker)
```
REPLACE:
```python
    # AD-1341 S2 (A2): a Ship's Archive label in the text means the tail slice may begin inside an archived entry
    # whose label was elided. The tail always follows the marker, so the origin notice placed after the marker
    # introduces every such fragment. It is part of the marker and sized with it, so the cap still holds.
    notice = _archive_origin_notice(text)

    # Size the marker against the largest omission this call can report, so the
    # marker rendered with the real (smaller or equal) count is always within
    # the budget reserved for it here.
    sizing_marker = _ELISION_MARKER.format(omitted=len(text)) + notice
    content_budget = max_chars - len(sizing_marker)
```

Pair 3 (the result):

SEARCH:
```python
    omitted = len(text) - head - tail
    return (
        text[:head]
        + _ELISION_MARKER.format(omitted=omitted)
        + text[len(text) - tail :]
    )
```
REPLACE:
```python
    omitted = len(text) - head - tail
    return (
        text[:head]
        + _ELISION_MARKER.format(omitted=omitted)
        + notice
        + text[len(text) - tail :]
    )
```

Pair 4 (A3: one expression for the notice, used by the bound and by the durable split):

SEARCH:
```python
    "region.] ...\n\n"
)


def truncate_tool_output(
```
REPLACE:
```python
    "region.] ...\n\n"
)


def _archive_origin_notice(text: str) -> str:
    """AD-1341 S2 (A2, A3): the origin notice ``truncate_tool_output`` adds after its marker for ``text``, or ``""``.

    The one expression for it in this module: the bound adds it, and the AD-1151 durable split
    (``_durable_head_tail``) reserves its length, so both are sized from the same budget.
    """
    return f"{ARCHIVE_ORIGIN_NOTICE}\n" if holds_archive_label(text) else ""


def truncate_tool_output(
```

Pair 5 (A3: the durable split takes the notice's length):

SEARCH:
```python
def _durable_head_tail(output_max_chars: int, original_chars: int) -> tuple[int, int]:
```
REPLACE:
```python
def _durable_head_tail(
    output_max_chars: int, original_chars: int, *, notice_chars: int = 0,
) -> tuple[int, int]:
```

Pair 6 (A3: the budget reserves it):

SEARCH:
```python
    marker; ``truncate_tool_output`` renders as much of the marker as fits and
    never consults the slices in that case.
    """
    budget = output_max_chars - len(_ELISION_MARKER.format(omitted=original_chars))
```
REPLACE:
```python
    marker; ``truncate_tool_output`` renders as much of the marker as fits and
    never consults the slices in that case.

    AD-1341 S2 (A3): ``notice_chars`` is the length of the archive origin notice
    ``truncate_tool_output`` adds after its marker for the same text
    (``len(_archive_origin_notice(text))``). Reserving it here makes head + tail
    equal that function's content budget, so it never rescales these slices a
    second time. When the context head is exactly twice the context tail (the
    default 4000 / 2000), these slices therefore contain the model's: the same
    slices when the model's were scaled to an equal cap, at least as wide
    otherwise. Any other configured split can leave the durable head or tail
    tighter than the model's, with or without a notice, because the ratio here
    is fixed and never reads the context split (a pre-existing AD-1151 gap).
    """
    budget = output_max_chars - len(_ELISION_MARKER.format(omitted=original_chars)) - notice_chars
```

Pair 7 (A3: the trace passes it):

SEARCH:
```python
            head_chars, tail_chars = _durable_head_tail(output_max_chars, len(original))
```
REPLACE:
```python
            # AD-1341 S2 (A3): reserve the origin notice truncate_tool_output adds for this text, so the durable
            # slices fill its content budget exactly and are not rounded down a second time.
            head_chars, tail_chars = _durable_head_tail(
                output_max_chars,
                len(original),
                notice_chars=len(_archive_origin_notice(original)),
            )
```

### 7.3b `src/probos/cognitive/swe_harness/session_compactor.py`

Pair 1 (import):

SEARCH:
```python
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
```
REPLACE:
```python
from probos.knowledge.archive_store import ARCHIVE_ORIGIN_NOTICE, holds_archive_label  # AD-1341 S2 (A2)
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
```

Pair 2 (the summary opens with the notice when it summarised archive text):

SEARCH:
```python
        summary_msg: dict = {
            "role": "user",
            "content": f"[CONTEXT SUMMARY — earlier exchanges]\n{summary}",
        }
```
REPLACE:
```python
        # AD-1341 S2 (A2): the summary is the model's words and may restate Ship's Archive knowledge without its
        # label. When the summarised messages held a label (or an earlier summary's notice), code, not the model,
        # puts the archive origin notice first, so restated archive knowledge never reaches the next request
        # unlabelled. It cannot say which sentence is archived (RS2-9).
        notice = f"{ARCHIVE_ORIGIN_NOTICE}\n" if holds_archive_label(older_text) else ""
        summary_msg: dict = {
            "role": "user",
            "content": f"[CONTEXT SUMMARY — earlier exchanges]\n{notice}{summary}",
        }
```

### 7.4 New file: `tests/test_ad1341_s2_inherited_label.py`

```python
"""AD-1341 S2 (#1569): a later crew reads the Ship's Archive as inherited knowledge, never as its own memory.

The real ``ArchiveStore`` on a temporary file (BF-919 keeps every test archive under the suite's temporary roots),
the real ``OracleService``, and the real renderers through which an Oracle result reaches an agent:
``query_formatted`` (the ORACLE recall tier and the ``oracle_lookup`` sub-task), the AD-1139 ``oracle_query`` tool,
AD-462f memory refs, the AD-1141 crew consult and the AD-725 DM lookup. The seam test runs the real ``probos reset``
twice, with S1's helpers. Amendment A2 adds the consumers after the renderers: AD-1148's bound of a tool result,
through the real tool, executor and loop; AD-547's compaction; and AD-688's graph expansion on the real edge store.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import _render_commons_block
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm_targeted_lookup import LookupDispatcher
from probos.cognitive.oracle_service import OracleService, _extract_entity_tokens
from probos.cognitive.swe_harness.agentic_loop import (
    _ELISION_MARKER,
    AgenticLoop,
    resolve_tool_result_bounds,
    truncate_tool_output,
)
from probos.cognitive.swe_harness.session_compactor import SessionCompactor
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolCallResult, ToolUseBlock
from probos.config import AgenticLoopConfig
from probos.knowledge.archive_store import (
    ARCHIVE_ORIGIN_NOTICE,
    LABEL_EARLIER_CREW,
    LABEL_THIS_CREW,
    ArchiveEntry,
    ArchiveStore,
    GenerationOutcome,
    GenerationRecord,
    PromotionRecord,
    SourceKind,
    holds_archive_label,
    inheritance_label,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.ontology.service import VesselOntologyService
from probos.startup.communication import _register_oracle_query_tool
from probos.storage.sqlite_factory import default_factory
from probos.tools.executor import ToolExecutor
from probos.tools.oracle_query_tool import OracleQueryTool
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
from tests.test_ad1341_s1_archive_store import _plant_v0
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _config, _data_dir, _records, _reset, _write_records

_SRC = Path(probos.__file__).resolve().parent
_REPO = _SRC.parents[1]
_MARKER_END = _ELISION_MARKER.split("{omitted}", 1)[1]  # AD-1148's elision marker after its count
_BODY = "Three officers independently traced the coolant drift."
_SECOND = "ship-did-second-0002"
_THIRD = "ship-did-third-0003"
_SECOND_REPORT = "reports/convergence/convergence-20261023-000000.md"
_HEADER = re.compile(r"\[(?:convergence_report|published_report|captains_log|notebook_finding)\] ")
_LABEL_ENDS = ("not your own memory]", "a record, not a memory]")

# Closes in id order: a skip with no instance id, a skip whose instance id is only a tab and line breaks (A2: blank
# by ``str.strip``, not by SQLite's ``trim``), alpha, beta (skipped), alpha again, gamma. t-open has no close.
_TIMELINES = ("t-alpha", "t-beta", "t-gamma", "t-open")
_EXPECTED = {"t-alpha": 1, "t-beta": 2, "t-gamma": 3, "t-open": None}


def _generation_label(generation: int) -> str:
    return f"[Inherited from the crew of generation {generation}: not your own memory]"


def _store(tmp_path: Path) -> ArchiveStore:
    return ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)


def _new_oracle(store: Any, **collaborators: Any) -> OracleService:
    return OracleService(archive_store=store, **collaborators)


def _oracle(store: Any, current_timeline: str = "", **collaborators: Any) -> OracleService:
    oracle = _new_oracle(store, **collaborators)
    oracle.attach_current_timeline(current_timeline)
    return oracle


def _content(timeline: str) -> str:
    """Long enough that every renderer's cap cuts it."""
    return f"{_BODY} ({timeline}) " + "Detail. " * 300


def _record(timeline: str, content: str = "") -> PromotionRecord:
    fields: dict[str, Any] = {
        "timeline_id": timeline, "source_kind": SourceKind.CONVERGENCE_REPORT,
        "source_ref": f"reports/convergence/{timeline}.md", "title": timeline,
        "content": content or _content(timeline),
        "classification": "ship", "author_callsign": "system",
    }
    return PromotionRecord(**fields)


def _closed(timeline: str, *, skipped: bool = False) -> GenerationRecord:
    fields: dict[str, Any] = {"timeline_id": timeline, "reset_tier": 2}
    if skipped:
        fields.update(outcome=GenerationOutcome.SKIPPED, reason="Captain: a recorded skip")
    else:
        fields.update(outcome=GenerationOutcome.PROMOTED, created=1)
    return GenerationRecord(**fields)


def _entry(timeline: str, generation: Any) -> ArchiveEntry:
    fields: dict[str, Any] = {
        "id": 7, "timeline_id": timeline, "category": "convergence_report", "title": "t", "content": _BODY,
        "author_agent_type": "", "author_callsign": "system", "archived_at": 1.0, "generation": generation,
    }
    return ArchiveEntry(**fields)


async def _plant(store: ArchiveStore, timelines: tuple[str, ...] = _TIMELINES) -> None:
    for closure in (
        _closed("", skipped=True), _closed("\t\r\n", skipped=True), _closed("t-alpha"),
        _closed("t-beta", skipped=True), _closed("t-alpha"), _closed("t-gamma"),
    ):
        await store.record_generation(closure)
    for timeline in timelines:
        await store.promote_entry(_record(timeline))


def _every_entry_is_labelled_first(text: str) -> int:
    """Each archive entry's header (``[<kind>] <title>``) is preceded by an inheritance label, with only whitespace,
    or a ``repr``'s escaped newline, between them. Returns how many headers it checked."""
    checked = 0
    for header in _HEADER.finditer(text):
        before = text[: header.start()].rstrip().removesuffix("\\n").rstrip()
        assert before.endswith(_LABEL_ENDS), text[max(0, header.start() - 160): header.start() + 40]
        checked += 1
    return checked


# --- T1, T2: the store numbers the crews (D3) -----------------------------------------------------------------


async def test_each_entry_carries_its_crews_generation_from_every_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        searched = await store.search("coolant drift")
        recent = await store.get_recent()
        by_id = [await store.entry_by_id(entry.id) for entry in recent]
    finally:
        await store.close()
    for read in (searched, recent, by_id):
        assert {entry.timeline_id: entry.generation for entry in read} == _EXPECTED
    assert sorted(entry.content for entry in recent) == sorted(_content(t) for t in _TIMELINES)  # unlabelled


@pytest.mark.parametrize("v0", [False, True], ids=["empty-generations", "v0-row"])
async def test_an_entry_whose_crew_has_no_recorded_close_has_no_generation(tmp_path: Path, v0: bool) -> None:
    if v0:
        _plant_v0(tmp_path / "archive.db")  # AD-524's two rows, timeline "timeline-zero", never closed
    store = _store(tmp_path)
    await store.initialize()
    try:
        if v0:
            await store.record_generation(_closed("t-alpha"))
            entries = await store.search("Legacy")
        else:
            await store.promote_entry(_record("t-alpha"))
            entries = await store.search("coolant drift")
    finally:
        await store.close()
    assert entries, "premise: the read returns the entry"
    assert all(entry.generation is None for entry in entries)
    assert {inheritance_label(entry, current_timeline="t-now") for entry in entries} == {LABEL_EARLIER_CREW}


# --- T3, T3b: the rule (D4, D5) -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timeline", "generation", "current", "expected"),
    [
        ("t-alpha", 3, "t-now", _generation_label(3)),
        ("t-alpha", 1, "", _generation_label(1)),
        ("t-alpha", None, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", 0, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", True, "t-now", LABEL_EARLIER_CREW),
        ("t-alpha", "2", "t-now", LABEL_EARLIER_CREW),
        ("t-now", 2, "t-now", LABEL_THIS_CREW),
        ("t-now", None, "t-now", LABEL_THIS_CREW),
        ("", None, "", LABEL_EARLIER_CREW),
    ],
    ids=["generation", "no-current", "unrecorded", "zero", "bool", "str", "this-crew-closed", "this-crew-open",
         "both-empty"],
)
def test_the_label_says_where_an_entry_came_from(timeline: str, generation: Any, current: str, expected: str) -> None:
    label = inheritance_label(_entry(timeline, generation), current_timeline=current)
    assert label == expected
    assert label.startswith("[") and label.endswith(_LABEL_ENDS)


def test_the_fixed_labels_read_as_decided() -> None:
    assert LABEL_THIS_CREW == "[Archived by this crew: a record, not a memory]"
    assert LABEL_EARLIER_CREW == "[Inherited from an earlier crew: not your own memory]"


# --- T4, T5, T5b: the one attachment point (D2, D5) -----------------------------------------------------------


async def test_the_oracle_puts_the_label_first_in_each_archive_result(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        results = await _oracle(store, "t-now").query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    assert sorted(result.metadata["timeline_id"] for result in results) == sorted(_TIMELINES)
    for result in results:
        timeline = result.metadata["timeline_id"]
        generation = _EXPECTED[timeline]
        label = _generation_label(generation) if generation else LABEL_EARLIER_CREW
        assert result.content.split("\n", 1)[0] == label
        assert result.content == f"{label}\n[convergence_report] {timeline}\n{_content(timeline)}"
        assert (result.source_tier, result.metadata["generation"], result.metadata["inherited"]) == (
            "archive", generation, True,
        )
        assert result.provenance == f"Archive/convergence_report (timeline {timeline[:8]}...)"


async def test_an_entry_this_crew_archived_is_its_own_record_never_inherited(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store)
        attached = await _oracle(store, "t-alpha\n").query("coolant drift", tiers=["archive"])
        unattached = await _new_oracle(store).query("coolant drift", tiers=["archive"])
    finally:
        await store.close()
    labels = {r.metadata["timeline_id"]: (r.content.split("\n", 1)[0], r.metadata["inherited"]) for r in attached}
    assert labels == {
        "t-alpha": (LABEL_THIS_CREW, False),
        "t-beta": (_generation_label(2), True),
        "t-gamma": (_generation_label(3), True),
        "t-open": (LABEL_EARLIER_CREW, True),
    }
    # Until the runtime attaches the timeline nothing reads as this crew's own: the safe direction (D5).
    assert all(result.metadata["inherited"] is True for result in unattached)
    assert LABEL_THIS_CREW not in "".join(result.content for result in unattached)


@pytest.mark.parametrize("value", [None, 7, b"t-alpha"], ids=["none", "int", "bytes"])
def test_the_oracle_takes_its_timeline_only_as_text(value: Any) -> None:
    oracle = _new_oracle(None)
    with pytest.raises(TypeError):
        oracle.attach_current_timeline(value)


# --- T6, T7: every renderer an agent reads (§5) ---------------------------------------------------------------


async def _agent_text(oracle: OracleService, path: str, query: str) -> str:
    """The text an agent receives from the Oracle through ``path``, by the renderer that path uses."""
    if path == "query-formatted":  # the ORACLE recall tier and the oracle_lookup sub-task
        return await oracle.query_formatted(query, k_per_tier=3, max_chars=2000)
    if path == "oracle-tool":  # AD-1139
        return (await OracleQueryTool(oracle=oracle).invoke({"query": query, "kind": "archive"})).output
    if path == "memory-refs":  # AD-462f, the oracle_refs sub-task
        return OracleService.format_refs(await oracle.query_refs(query, k_per_tier=3))
    if path == "crew-consult":  # AD-1141
        consult = await oracle.query(query, k_per_tier=3, tiers=["archive"])
        return _render_commons_block(consult, max_chars=4000, max_entries=5, min_score=0.0)
    return LookupDispatcher._stringify(await oracle.query(query))  # AD-725: every tier, stringified


@pytest.mark.parametrize("path", ["query-formatted", "oracle-tool", "memory-refs", "crew-consult", "dm-lookup"])
async def test_every_path_from_the_archive_to_an_agent_carries_the_label_before_the_content(
    tmp_path: Path, path: str,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), path, "coolant drift")
    finally:
        await store.close()
    assert _every_entry_is_labelled_first(text) == 3
    for label in (_generation_label(1), _generation_label(2), LABEL_EARLIER_CREW):
        assert label in text


class _FarArchive:
    """An archive whose one entry has SQLite's largest rowid and a generation the test chooses: the widest prefix."""

    def __init__(self, generation: int) -> None:
        self.generation = generation

    async def search(self, query: str, *, limit: int = 10) -> list[ArchiveEntry]:
        fields: dict[str, Any] = {
            "id": 2**63 - 1, "timeline_id": "t-far", "category": "convergence_report", "title": "x" * 200,
            "content": "y" * 2000, "author_agent_type": "", "author_callsign": "system",
            "archived_at": time.time(), "generation": self.generation,
        }
        return [ArchiveEntry(**fields)][:limit]


@pytest.mark.parametrize(
    ("generation", "survives"),
    [(10**6 - 1, _generation_label(10**6 - 1)), (10**6, "generation 1000000: not your own memory")],
    ids=["whole-label", "warning-words"],
)
async def test_the_label_survives_the_tightest_cap_any_consumer_applies(generation: int, survives: str) -> None:
    """``format_refs`` keeps 119 characters of a line; prefix and label take 94 plus the digits of the id and of the
    generation. Up to 25 digits the whole label survives; past that the warning words do (RS2-7)."""
    refs_text = OracleService.format_refs(await _oracle(_FarArchive(generation), "t-now").query_refs("anything"))
    assert f"[archive] archive:{2**63 - 1} (score: 0.99) " in refs_text  # premise: the widest prefix
    assert survives in refs_text


# --- T8: the real seam: two resets, then a later crew's Oracle and the text it hands an agent ------------------


async def _publish_second_finding(data_dir: Path) -> None:
    await _records(data_dir).write_entry(
        author="system", path=_SECOND_REPORT,
        content="## Convergence Report\n\nThe second watch traced the coolant drift to a cracked manifold.",
        message="AD-551: Convergence report (manifold)", classification="ship", tags=["convergence", "ad-551"],
    )


async def _third_crew_reads(tmp_path: Path, query: str) -> tuple[list[Any], str, str]:
    later = _store(tmp_path)  # the third crew's boot opens the archive the resets wrote
    await later.initialize()
    try:
        oracle = _oracle(later, _THIRD)
        results = await oracle.query(query, tiers=["archive"])
        tool = await _agent_text(oracle, "oracle-tool", query)
        formatted = await _agent_text(oracle, "query-formatted", query)
    finally:
        await later.close()
    return results, tool, formatted


@pytest.mark.parametrize("full", [False, True], ids=["default", "full"])
def test_after_two_resets_a_later_crew_reads_each_generations_knowledge_labelled_as_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool,
) -> None:
    data_dir = _data_dir(tmp_path)  # the first crew, under _SHIP
    asyncio.run(_write_records(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=full) == 0

    # The second crew boots under a new instance id, as the ontology loader writes it, and publishes a finding.
    (data_dir / "ontology").mkdir(parents=True, exist_ok=True)
    (data_dir / "ontology" / "instance_id").write_text(_SECOND, encoding="utf-8")
    asyncio.run(_publish_second_finding(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir, full=full) == 0

    results, tool, formatted = asyncio.run(_third_crew_reads(tmp_path, "coolant drift"))
    generations = {(result.metadata["timeline_id"], result.metadata["generation"]) for result in results}
    assert generations == {(_SHIP, 1), (_SECOND, 2)}
    for result in results:
        assert result.source_tier == "archive"
        assert result.content.split("\n", 1)[0] == _generation_label(result.metadata["generation"])
        assert result.metadata["inherited"] is True
    for text in (tool, formatted):
        assert _every_entry_is_labelled_first(text) == len(results)
        assert _generation_label(1) in text and _generation_label(2) in text
        assert LABEL_THIS_CREW not in text
    assert "cracked manifold" in tool  # premise: the second crew's finding reached the third crew


# --- T9: the runtime is the one caller ------------------------------------------------------------------------


def test_only_the_runtime_tells_the_oracle_its_timeline_and_it_reads_the_ontologys_instance_id() -> None:
    calls: list[tuple[str, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "attach_current_timeline"
            ):
                calls.append((path.relative_to(_SRC).as_posix(), ast.unparse(node)))
    assert calls == [(
        "runtime.py",
        "self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)",
    )]


# --- T10: the timeline a boot attaches is the one the reset closes (D5's premise, A2) --------------------------


async def _booted_instance_id(data_dir: Path) -> str:
    """The instance id a boot's real ontology loads: what the runtime attaches (T9 pins the expression)."""
    ontology = VesselOntologyService(_REPO / "config" / "ontology", data_dir=data_dir)
    await ontology.initialize()
    return ontology.get_vessel_identity().instance_id


async def _archived(tmp_path: Path) -> list[ArchiveEntry]:
    store = _store(tmp_path)
    await store.initialize()
    try:
        return await store.get_recent()
    finally:
        await store.close()


def test_the_timeline_a_boot_attaches_is_the_one_the_reset_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _data_dir(tmp_path)
    booted = asyncio.run(_booted_instance_id(data_dir))
    asyncio.run(_write_records(data_dir))
    assert _reset(monkeypatch, _config(tmp_path), data_dir) == 0
    entries = asyncio.run(_archived(tmp_path))
    assert entries, "premise: the reset archived the crew's records"
    assert {(entry.timeline_id, entry.generation) for entry in entries} == {(booted, 1)}
    assert asyncio.run(_booted_instance_id(data_dir)) not in ("", booted)  # the next crew is a new timeline


# --- T11, T12: AD-1148's bound of a tool result keeps the archive origin before what it kept (A2) --------------


def _origin_of_what_was_kept(bounded: str) -> None:
    """AD-1148 kept a head and a tail of a labelled tool result: every entry header in the head follows its label,
    and the tail, which may begin inside an entry, opens with the archive origin notice."""
    head, cut, tail = bounded.partition(_MARKER_END)
    assert cut, "premise: the cap elided the middle"
    assert "Detail." in tail, "premise: archived text crosses the cut"
    _every_entry_is_labelled_first(head)
    assert tail.startswith(f"{ARCHIVE_ORIGIN_NOTICE}\n"), tail[:200]


@pytest.mark.parametrize("cap", [1000, 2000, 3000])
async def test_an_elided_tool_result_introduces_what_it_kept_after_the_cut_with_the_archive_origin(
    tmp_path: Path, cap: int,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), "oracle-tool", "coolant drift")
    finally:
        await store.close()
    bounded = truncate_tool_output(text, max_chars=cap, head_chars=4000, tail_chars=2000)
    assert len(text) > cap >= len(bounded)  # premise: the cap elides; the notice stays inside it
    _origin_of_what_was_kept(bounded)
    # Text that holds no label is bounded as AD-1148 bounds it, with no notice.
    plain = text.replace("[Inherited from ", "[Received from ")
    assert ARCHIVE_ORIGIN_NOTICE not in truncate_tool_output(plain, max_chars=cap, head_chars=4000, tail_chars=2000)


class _ScriptedModel:
    """Asks for one ``oracle_query`` call, then finishes; records every request the loop sends."""

    def __init__(self, call: ToolCallRequest) -> None:
        self.call = call
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_: Any) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(content="", content_blocks=[ToolUseBlock(tool_call=self.call)], tokens_used=1)
        return LLMResponse(content="finished", content_blocks=[TextBlock(text="finished")], tokens_used=1)


@pytest.mark.parametrize("structured", [False, True], ids=["flattened", "structured"])
async def test_a_bounded_archive_tool_result_reaches_the_next_model_request_with_its_origin(
    tmp_path: Path, structured: bool,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        oracle = _oracle(store, "t-now")
        registry = ToolRegistry()
        _register_oracle_query_tool(tool_registry=registry, enabled=True, oracle=oracle)
        tool = OracleQueryTool(oracle=oracle)
        model = _ScriptedModel(ToolCallRequest(
            name=tool.tool_id, arguments={"query": "coolant drift", "kind": "archive"}, id="archive-call",
        ))
        bounds = resolve_tool_result_bounds(
            AgenticLoopConfig(tool_result_max_chars=2000, structured_tool_messages=structured),
        )
        loop = AgenticLoop(
            llm_client=model, tool_executor=ToolExecutor(registry=registry), max_iterations=2,
            structured_tool_messages=structured, **bounds,
        )
        result = await loop.run(
            system_prompt="Complete the task.", user_message="Read the archived finding.",
            tools=[{"type": "function", "function": {
                "name": tool.tool_id, "description": tool.description, "parameters": tool.input_schema,
            }}],
            context={"agent_id": "archive-reader", "department": "science", "rank": "ensign"},
        )
    finally:
        await store.close()
    assert [r.is_error for r in result.tool_results] == [False]  # premise: the registered tool ran
    assert len(model.requests) == 2
    request = model.requests[1]
    seen = (
        next(m["content"] for m in request.messages if m.get("role") == "tool") if structured else request.prompt
    )
    _origin_of_what_was_kept(seen)


# --- T13: AD-547's summary opens with the archive origin when it summarised archive text (A2) ------------------


class _Summarizer:
    """A fast-tier model whose summary keeps the finding and names no source, as a concise summary may."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="The key finding is the cracked manifold.", tokens_used=12)


@pytest.mark.parametrize("source", ["label", "earlier-notice", "none"])
async def test_a_compaction_summary_opens_with_the_archive_origin_when_it_summarised_archive_text(
    source: str,
) -> None:
    earlier = {
        "label": f"{_generation_label(1)}\n[convergence_report] t-alpha\n{_BODY}",
        "earlier-notice": f"[CONTEXT SUMMARY — earlier exchanges]\n{ARCHIVE_ORIGIN_NOTICE}\nThe drift was traced.",
        "none": "Three officers discussed the duty roster.",
    }[source]
    messages = [
        {"role": "system", "content": "Complete the task."},
        {"role": "user", "content": "Review the earlier finding."},
        {"role": "user", "content": earlier},
        *({"role": "assistant" if n % 2 else "user", "content": f"Step {n}."} for n in range(8)),
    ]
    summarizer = _Summarizer()
    compacted = await SessionCompactor().compact(messages, fast_llm=summarizer)
    assert len(summarizer.requests) == 1 and earlier in summarizer.requests[0].prompt  # premise: it was summarised
    summaries = [m["content"] for m in compacted if m["content"].startswith("[CONTEXT SUMMARY")]
    notice = f"{ARCHIVE_ORIGIN_NOTICE}\n" if source != "none" else ""
    assert summaries == [f"[CONTEXT SUMMARY — earlier exchanges]\n{notice}The key finding is the cracked manifold."]


# --- T14: what counts as archive text (A2) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "holds"),
    [
        (f"quoted {_generation_label(4)} here", True),
        (f"quoted {LABEL_EARLIER_CREW} here", True),
        (f"quoted {LABEL_THIS_CREW} here", True),
        (f"quoted {ARCHIVE_ORIGIN_NOTICE} here", True),
        ("Three officers traced the coolant drift.", False),
        ("Inherited from the crew of generation 4, with no bracket.", False),
    ],
    ids=["generation", "earlier-crew", "this-crew", "notice", "plain", "unbracketed"],
)
def test_archive_text_is_recognised_by_any_label_or_the_notice(text: str, holds: bool) -> None:
    assert holds_archive_label(text) is holds
    # AD-1148 DD-3 and AD-1142 DD-11: a model-facing marker must never read as a capability gap.
    assert _CAPABILITY_GAP_RE.search(ARCHIVE_ORIGIN_NOTICE) is None


# --- T15: AD-688's graph expansion reads an archive entry without its label (A2) -------------------------------


class _RecordingGraph:
    """The real edge store; records each token AD-688's expansion looks up."""

    def __init__(self, graph: SQLiteKnowledgeEdgeStore) -> None:
        self.graph = graph
        self.tokens: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.graph, name)

    async def find_edges(self, **kwargs: Any) -> list[Any]:
        self.tokens.append(kwargs["source_id"])
        return await self.graph.find_edges(**kwargs)


async def test_graph_expansion_reads_an_archive_entry_without_its_label(tmp_path: Path) -> None:
    short = "The coolant actuator drifted under load."
    graph = SQLiteKnowledgeEdgeStore(str(tmp_path / "edges.db"), connection_factory=default_factory)
    await graph.start()
    store = _store(tmp_path)
    await store.initialize()
    try:
        for source, edge_id in (("actuator", "content-edge"), ("crew", "label-edge")):
            await graph.add_edge(KnowledgeEdge(
                source_type=KnowledgeEntityType.CAPABILITY, source_id=source,
                relation=KnowledgeRelationType.DEPENDS_ON, target_type=KnowledgeEntityType.FINDING,
                target_id=f"{source}-detail", id=edge_id, created_at=1, updated_at=1,
            ))
        await store.record_generation(_closed("t-alpha"))
        await store.promote_entry(_record("t-alpha", short))
        recording = _RecordingGraph(graph)
        results = await _oracle(store, "t-now", knowledge_graph=recording).query("actuator", tiers=["archive"])
    finally:
        await store.close()
        await graph.stop()
    labels = [r.content.split("\n", 1)[0] for r in results if r.source_tier == "archive"]
    assert labels == [_generation_label(1)]  # premise: the parent carries its label
    assert recording.tokens == _extract_entity_tokens(f"[convergence_report] t-alpha\n{short}")
    expanded = [(r.metadata["edge_id"], r.metadata["matched_token"]) for r in results if r.source_tier == "graph"]
    assert expanded == [("content-edge", "actuator")]


# --- T16: the AD-1151 durable trace keeps all the model saw of an archive tool result (A3) -----------------------


def _kept(bounded: str) -> tuple[str, str]:
    """The head AD-1148 kept before its elision marker, and what follows the marker: the notice, then the tail."""
    head = bounded.split(_ELISION_MARKER.split("{omitted}", 1)[0], 1)[0]
    return head, bounded.partition(_MARKER_END)[2]


@pytest.mark.parametrize(
    ("context_cap", "trace_cap"),
    [
        (401, 401), (402, 402), (1000, 1000), (1001, 1001), (1999, 1999),
        (2000, 2000), (2000, 1000), (2001, 2001), (2999, 2999), (3000, 3000),
    ],
    ids=["401", "402", "1000", "1001", "1999", "2000", "2000-raised-from-1000", "2001", "2999", "3000"],
)
async def test_the_durable_trace_keeps_every_character_the_model_saw_of_an_archive_tool_result(
    tmp_path: Path, context_cap: int, trace_cap: int,
) -> None:
    store = _store(tmp_path)
    await store.initialize()
    try:
        await _plant(store, ("t-alpha", "t-beta", "t-open"))
        text = await _agent_text(_oracle(store, "t-now"), "oracle-tool", "coolant drift")
    finally:
        await store.close()
    cfg = AgenticLoopConfig(tool_result_max_chars=context_cap, tool_trace_output_max_chars=trace_cap)
    bounds = resolve_tool_result_bounds(cfg)
    # What the loop's message boundary hands the model (`_bound_tool_output`; T12 runs it through the real loop).
    seen = truncate_tool_output(
        text,
        max_chars=bounds["tool_result_max_chars"],
        head_chars=bounds["tool_result_head_chars"],
        tail_chars=bounds["tool_result_tail_chars"],
    )
    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    try:
        ref = await WorkItemAgenticExecutor(llm_client=None)._persist_tool_trace(
            SimpleNamespace(
                tool_calls=[ToolCallRequest(name="oracle_query", id="archive-call", timestamp=1.0)],
                tool_results=[ToolCallResult(id="archive-call", output=text)],
            ),
            SimpleNamespace(config=SimpleNamespace(agentic_loop=cfg), attachment_store=attachments),
            "archive-reader",
        )
        assert ref is not None, "premise: the real trace writer persisted the trace"
        (entry,) = json.loads(await attachments.read(ref))
    finally:
        attachments.close()
    # premise: a labelled result that both bounds elide (the resolver raises a durable cap below the context cap)
    assert holds_archive_label(text) and len(text) > context_cap and entry["output_truncated"] is True
    notice = f"{ARCHIVE_ORIGIN_NOTICE}\n"
    seen_head, seen_rest = _kept(seen)
    kept_head, kept_rest = _kept(entry["output"])
    # AD-1151: the durable trace is never bounded tighter than what the model saw.
    assert kept_head.startswith(seen_head), (len(seen_head), len(kept_head))
    assert seen_rest.startswith(notice) and kept_rest.startswith(notice)
    assert kept_rest.endswith(seen_rest.removeprefix(notice))
```

## 8. Tracking (tracker pairs; M2's commit)

Written against `026a682f`; re-anchored by the orchestrator at build time on the post-BF-925 heads (this paragraph's own instruction). If another entry has merged first, re-anchor both pairs on the newest head line and the newest DECISIONS entry's last bullet and the heading after it, as S1's orchestrator did; change no wording. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title, the blank line and the bold lead of BF-919's head entry):

SEARCH:
```markdown
# ProbOS Progress

**BF-925 (2026-10-25), #1655 -- silent-fallback guards name APIs that exist.**
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1341 S2 (2026-10-26), #1569 slice 2 of 6 -- a later crew reads the Ship's Archive as inherited knowledge, labelled with the crew generation it came from, never as its own memory.** Every Ship's Archive read now fills `ArchiveEntry.generation`: the place of the entry's timeline's first close among the closes `generations` attributes to a timeline (a skip with no instance id, or only whitespace, numbers no crew; a second close does not renumber one). `inheritance_label` (in `knowledge/archive_store.py`) gives one of three labels: `[Inherited from the crew of generation N: not your own memory]`, `[Inherited from an earlier crew: not your own memory]` when no close is recorded, and `[Archived by this crew: a record, not a memory]` for the reading crew's own timeline. The Oracle's archive tier, the one path from the archive to an agent, makes the label the first line of every result and adds `generation` and `inherited` to its metadata, so `query_formatted`, the `oracle_query` tool, memory refs, the crew consult and the DM lookup all hand an agent the label before the knowledge (memory refs keep it whole while the entry id's and generation's digits total at most 25). The two consumers that cut that text loose from its label on their own afterwards say so: AD-1148's elision of a tool result's middle and AD-547's compaction summary put a fixed Ship's Archive origin notice before what they keep whenever the text held a label. The AD-1151 durable trace reserves the same notice in its slices, so at the default context split each output the trace keeps holds everything the model saw of it; the trace's byte budget still elides whole outputs, and another configured split can persist a head or tail tighter than the model's, as on the base (a recorded AD-1151 follow-up). Head-only cuts (memory refs, the crew consult, the DM lookup) keep the label first. Not covered: a page an agent asks for at an offset into a result that AD-1240 offloaded (any result over 12,288 UTF-8 bytes), the first read included, can begin inside an entry with no label before it; a page-level origin line is the recorded follow-up. AD-688's graph expansion reads an archived entry without its label, so its lookups are unchanged. The runtime tells the Oracle this crew's timeline (the ontology's instance id) through `OracleService.attach_current_timeline`; until then, or if that fails, every entry reads as inherited. No flag, no schema change; the archive's contents, its score and the Oracle's tier order are unchanged. New: `tests/test_ad1341_s2_inherited_label.py` (the real store, Oracle, renderers, tool loop, compactor, edge store and real resets). The contract is `prompts/ad-1341-s2-inherited-label.md`.

**BF-925 (2026-10-25), #1655 -- silent-fallback guards name APIs that exist.**
```

**`DECISIONS.md`** (after BF-919's entry, anchored on its *Reversal* bullet, the blank line and the next heading; the docs-only commit adds a *Validation of record* bullet before AD-1341 S2's own *Reversal* line):

SEARCH:
```markdown
- *Reversal.* Revert the commits; the report, mention links, Chiefs' stats and window return to empty, and the guard test goes.

### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)
```
REPLACE:
```markdown
- *Reversal.* Revert the commits; the report, mention links, Chiefs' stats and window return to empty, and the guard test goes.

### AD-1341 S2 -- A later crew reads the Ship's Archive as inherited knowledge, labelled with the crew generation it came from, never as its own memory (2026-10-26, #1569 slice 2 of 6)

- *Scope.* Slice 2 of #1569 (Decision item 5 and its acceptance line), one code commit and one tracker commit. Files: `knowledge/archive_store.py` (`ArchiveEntry.generation`, `inheritance_label`, the two labels, the generation order, the origin notice and `holds_archive_label`), `cognitive/oracle_service.py` (`_query_archive`, `attach_current_timeline`, graph expansion without the label), `runtime.py` (one late bind), `cognitive/swe_harness/agentic_loop.py` (`truncate_tool_output` and the AD-1151 durable split) and `cognitive/swe_harness/session_compactor.py` (the summary), and a new test. Contract: `prompts/ad-1341-s2-inherited-label.md`.
- *D2 (where).* The rule and the data live in the store module; the label is attached once, in the Oracle's archive tier, the one path from the archive to an agent, as the first line of the result's content. Not in the store's content (it is what was archived and hashed), not in each renderer (a new renderer would be unlabelled), not in the provenance alone (two renderers never show it).
- *D3 (generation N).* The place of the timeline's first close among the distinct non-blank timelines in `generations`, by id. A blank-timeline skip (blank by Python's `strip`; SQLite's `trim` strips spaces only) numbers nothing; a re-close does not renumber; a skipped close still ended a crew. Numbering starts at the first close the archive recorded.
- *D4-D5 (the label).* Three fixed bracketed labels, each naming the origin first and then "not your own memory" (or "not a memory"); `generation` and `inherited` in the metadata. An entry of the reading crew's own timeline is "archived by this crew", never "inherited" (Westworld). Not attached, or failed, every entry reads as inherited: the error the minority-report principle tolerates. No callsign in the label, so a later crew member with an earlier crew's callsign never reads it as its own byline.
- *D6-D7.* No flag (its off position would present inherited knowledge unlabelled). The archive's score and the tier order are unchanged; the label, not the rank, keeps inherited knowledge from reading as one's own.
- *D12 (after the renderers).* AD-1148's elision of a tool result's middle and AD-547's compaction summary are the two consumers that separate archive text from its label on their own. Each puts a fixed Ship's Archive origin notice before what it keeps whenever the text held a label (or the notice). The notice is sized inside the cap and added by code, not by the summarising model, and the AD-1151 durable trace reserves it in its own slices, so at the default context split each output the trace keeps holds everything the model saw of it (the trace's byte budget still elides whole outputs; another configured split can persist a tighter head or tail, as on the base: a recorded AD-1151 follow-up). Head-only cuts (memory refs, the crew consult, the DM lookup) keep the label first. Not covered, recorded as RS2-8: a page an agent asks for at an offset into a result that AD-1240 offloaded (over 12,288 UTF-8 bytes), the first read included, can begin inside an entry with no label before it; the follow-up is a page-level origin line. Rejected: bounding at the tool (the cap is the loop's), an opt-out of the cap, an instruction in the summariser's prompt alone (soft), and narrowing the claim. The notice cannot name the generation of a cut fragment or of a summary sentence.
- *Disclosed effects.* Archive results open with the label line and carry two new metadata keys, also on the Captain's `GET /oracle`. One more small query per archive read. Vessels sharing one archive file share one generation count. A tool result holding a label that AD-1148 bounds, and an AD-547 summary of messages that held one, carry the origin notice. Memory refs cut the label's closing bracket only past 25 digits of entry id and generation together.
- *Reversal.* Revert the S2 commits. Nothing persisted changes: the archive and `generations` are read, never written, by this slice.

### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M2's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after the gate:** add a *Validation of record* bullet before AD-1341 S2's *Reversal* line (the campaign of record, its base tree, the sha256 of each §10 file and of the new test file, and each row's first failing test), and the same as a closing §16 of this contract; then regenerate the ledger.

**`docs/development/roadmap.md`:** no row; `AD-1341` does not appear there.

## 9. What this does NOT change

- The archive's schema, contents, writes, erasure and `generations` rows (S1); `promote_entry`, `record_generation`, `erase_entry` and their lock. No review queue or veto (S3), no exit notes or stand-down (S4), no continuous promotion (S5), no `--full` snapshot or clean slate (S6).
- The archive's score, its LIKE search, the Oracle's tier list, order, merge and `max_results`; the archive result's `provenance` and existing metadata keys; `_derive_ref_id`; `query_refs`' metadata whitelist.
- Every other tier's output, and the renderers themselves: `query_formatted`, `format_refs`, `ProvenanceEnvelope`, `OracleQueryTool`, `_render_commons_block`, `LookupDispatcher`, and the framing preambles in `cognitive_agent.py` and `sub_tasks/analyze.py`/`compose.py`.
- For text that holds no label or notice: AD-1148's cap, slices and marker, and AD-547's prompt, thresholds and preserved messages. For all text: `truncate_tool_output`'s and `SessionCompactor.compact`'s signatures and return shapes, AD-1240's delivery and its frames, and the AD-1151 trace's shape. AD-688's tokens, lookups and edges are the base's, now for an archive parent too.
- AD-607e's shard filter, the tool's sovereign-tier filter, BF-679's records reader rule.
- Ship's Records that survive tier 2 and reach a later crew through Tier 2 (RS2-6); episodic memory and its write path (RS2-2); the ontology and its instance id.
- `introspect`, the organizer and `/search`, which do not query the archive.
- AD-1151's durable split for text without a label (`notice_chars` is 0 there), its fixed 2:1 head:tail ratio and its aggregate byte budget (`tool_trace_max_bytes`, which elides whole outputs). With any configured `tool_result_head_chars`:`tool_result_tail_chars` other than exactly 2:1, the persisted head or tail can be tighter than the model's, on the base too. `_durable_head_tail` never reads the context split, so whether a cap matches depends on the content budget's rounding, and the notice only shifts which caps do (round 3: 3999:2001 one character off at caps 401, 1001, 2000 and 2999 here and at 2999 on the base; 5000:1000 tighter at every cap on both). This is a pre-existing AD-1151 gap, recorded as a follow-up (RS2-10) and not changed here (A3, A3c).

## 10. Mutation rows (33 rows; whole stripped lines, each occurring once in its file after §7)

Tier HIGH: every changed production file has rows. Run each row against `tests/test_ad1341_s2_inherited_label.py` on the contract-applied tree, after an unmutated baseline run that passes. Restore each file before the next row.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| S-K1 | `src/probos/knowledge/archive_store.py` | `crews = [row[0] for row in rows if row[0].strip()]` | `crews = [row[0] for row in rows]` | T1 (the two blank-timeline skips number first, so alpha is 3). "A skip with no crew counts" |
| S-K1b | `src/probos/knowledge/archive_store.py` | `crews = [row[0] for row in rows if row[0].strip()]` (after S-K1 is restored) | `crews = [row[0] for row in rows if row[0].strip(" ")]` | T1 (the tab-and-line-break skip numbers first, so alpha is 2). "SQLite's trim" (A2, finding 4) |
| S-K2 | `src/probos/knowledge/archive_store.py` | `"GROUP BY timeline_id ORDER BY min(id)"` | `"GROUP BY timeline_id ORDER BY max(id)"` | T1 (alpha's re-close moves it after beta). "A re-close renumbers" |
| S-K3 | `src/probos/knowledge/archive_store.py` | `return {timeline: number for number, timeline in enumerate(crews, start=1)}` | `return {timeline: number for number, timeline in enumerate(crews, start=0)}` | T1 (alpha 0) |
| S-K4 | `src/probos/knowledge/archive_store.py` | `generation=generations.get(row[1]),` | `generation=None,` | T1 |
| S-K5 | `src/probos/knowledge/archive_store.py` | `if current_timeline and entry.timeline_id == current_timeline:` | `if entry.timeline_id == current_timeline:` | T3 `[both-empty]` |
| S-K6 | `src/probos/knowledge/archive_store.py` | `if current_timeline and entry.timeline_id == current_timeline:` (after S-K5 is restored) | `if False:` | T3 `[this-crew-closed]`; T5 |
| S-K7 | `src/probos/knowledge/archive_store.py` | `if type(entry.generation) is int and entry.generation >= 1:` | `if entry.generation:` | T3 `[bool]` and `[str]` |
| S-K8 | `src/probos/knowledge/archive_store.py` | `if type(entry.generation) is int and entry.generation >= 1:` (after S-K7 is restored) | `if type(entry.generation) is int and entry.generation >= 0:` | T3 `[zero]` |
| S-K9 | `src/probos/knowledge/archive_store.py` | `return f"[Inherited from the crew of generation {entry.generation}: not your own memory]"` | `return f"[From the crew of generation {entry.generation}]"` | T3 `[generation]`; T4 |
| S-K10 | `src/probos/knowledge/archive_store.py` | `LABEL_EARLIER_CREW = "[Inherited from an earlier crew: not your own memory]"` | `LABEL_EARLIER_CREW = "[From an earlier crew]"` | T3b |
| S-K11 | `src/probos/knowledge/archive_store.py` | `LABEL_THIS_CREW = "[Archived by this crew: a record, not a memory]"` | `LABEL_THIS_CREW = "[Your memory]"` | T3b |
| O-1 | `src/probos/cognitive/oracle_service.py` | `label = inheritance_label(entry, current_timeline=self._current_timeline)` | `label = ""` | T4 |
| O-2 | `src/probos/cognitive/oracle_service.py` | `content=f"{label}\n[{entry.category}] {entry.title}\n{entry.content}",` | `content=f"[{entry.category}] {entry.title}\n{entry.content}\n{label}",` | T4 (first line); T6 `[memory-refs]` (the cap drops a trailing label). "The label as prose at the end" |
| O-3 | `src/probos/cognitive/oracle_service.py` | `"inherited": label != LABEL_THIS_CREW,` | `"inherited": True,` | T5 |
| O-4 | `src/probos/cognitive/oracle_service.py` | `"generation": entry.generation,` | `"generation": None,` | T4 |
| O-5 | `src/probos/cognitive/oracle_service.py` | `self._current_timeline = timeline_id.strip()` | `self._current_timeline = ""` | T5 |
| R-1 | `src/probos/runtime.py` | `self._oracle_service.attach_current_timeline(self.ontology.get_vessel_identity().instance_id)` | `pass` | T9 |
| O-6 | `src/probos/cognitive/oracle_service.py` | `if type(timeline_id) is not str:` | `if False:` | T5b (`None` and `7` raise `AttributeError`; `b"t-alpha"` is accepted) |
| S-K12 | `src/probos/knowledge/archive_store.py` | `_ARCHIVE_ORIGINS = ("[Inherited from ", LABEL_THIS_CREW, ARCHIVE_ORIGIN_NOTICE)` | `_ARCHIVE_ORIGINS = (LABEL_THIS_CREW, ARCHIVE_ORIGIN_NOTICE)` | T14 `[generation]`, `[earlier-crew]`; T11; T12 |
| S-K13 | `src/probos/knowledge/archive_store.py` | `_ARCHIVE_ORIGINS = ("[Inherited from ", LABEL_THIS_CREW, ARCHIVE_ORIGIN_NOTICE)` (after S-K12 is restored) | `_ARCHIVE_ORIGINS = ("[Inherited from ", ARCHIVE_ORIGIN_NOTICE)` | T14 `[this-crew]` |
| S-K14 | `src/probos/knowledge/archive_store.py` | `_ARCHIVE_ORIGINS = ("[Inherited from ", LABEL_THIS_CREW, ARCHIVE_ORIGIN_NOTICE)` (after S-K13 is restored) | `_ARCHIVE_ORIGINS = ("[Inherited from ", LABEL_THIS_CREW)` | T14 `[notice]`; T13 `[earlier-notice]` |
| S-K15 | `src/probos/knowledge/archive_store.py` | `return any(origin in text for origin in _ARCHIVE_ORIGINS)` | `return False` | T11; T12; T13 `[label]`; T14 |
| O-7 | `src/probos/cognitive/oracle_service.py` | `return result.content.partition("\n")[2]` | `return result.content` | T15 |
| O-8 | `src/probos/cognitive/oracle_service.py` | `tokens = _extract_entity_tokens(_expansion_text(parent))` | `tokens = _extract_entity_tokens(parent.content)` | T15 |
| L-1 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `notice = _archive_origin_notice(text)` | `notice = ""` | T11; T12; T16 |
| L-2 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `sizing_marker = _ELISION_MARKER.format(omitted=len(text)) + notice` | `sizing_marker = _ELISION_MARKER.format(omitted=len(text))` | T11 (the result exceeds the cap) |
| L-3 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `+ notice` | `+ ""` | T11; T12 |
| L-4 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `return f"{ARCHIVE_ORIGIN_NOTICE}\n" if holds_archive_label(text) else ""` | `return ""` | T11; T12; T16 (every case, at the notice) |
| L-5 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `budget = output_max_chars - len(_ELISION_MARKER.format(omitted=original_chars)) - notice_chars` | `budget = output_max_chars - len(_ELISION_MARKER.format(omitted=original_chars))` | T16 `[401]`, `[1000]`, `[1001]`, `[1999]`, `[2000]`, `[2000-raised-from-1000]`, `[2999]`. "The durable split sized from the bare marker" (A2's second rounding) |
| L-6 | `src/probos/cognitive/swe_harness/agentic_loop.py` | `notice_chars=len(_archive_origin_notice(original)),` | `notice_chars=0,` | T16, the same seven cases. "The trace passes no notice" |
| C-1 | `src/probos/cognitive/swe_harness/session_compactor.py` | `notice = f"{ARCHIVE_ORIGIN_NOTICE}\n" if holds_archive_label(older_text) else ""` | `notice = ""` | T13 `[label]`, `[earlier-notice]` |
| C-2 | `src/probos/cognitive/swe_harness/session_compactor.py` | `"content": f"[CONTEXT SUMMARY — earlier exchanges]\n{notice}{summary}",` | `"content": f"[CONTEXT SUMMARY — earlier exchanges]\n{summary}\n{notice}",` | T13 `[label]`, `[earlier-notice]` |

O-6 was run as the 18th row of the M1 campaign; it is now a table row. Rows S-K1b and S-K12 onward come from Amendment A2; S-K1 and S-K3 are re-anchored on A2's Python filter. Rows L-4 to L-6 come from Amendment A3, and L-1 is re-anchored on A3's `notice = _archive_origin_notice(text)`.

## 11. Verified Against Codebase (2026-10-24, HEAD `026a682f`, tree `cad2c0ee25686a5683fd0ba3be35463796b5cf35`)

Read with the Grep and Read tools on this checkout (the bridge allows no `rg` pipelines).

```
src/probos/knowledge/archive_store.py
  13-15: "``generations`` records each crew generation's close ... promotion the Captain skipped and why."   (7.1 pair 1)
  43-61: class ArchiveEntry ... source_episode_ids: tuple[str, ...] = ()   (frozen dataclass; every field after metadata defaulted)
  64: #: AD-1341: the schema this store writes. 0 is AD-524's, with no provenance.
  179-182: PROMOTED needs a timeline; SKIPPED needs a reason (a blank timeline is allowed)
  201-214: CREATE TABLE IF NOT EXISTS generations (id INTEGER PRIMARY KEY AUTOINCREMENT, timeline_id TEXT NOT NULL, ...)
  280: _SQLITE_MAX_ROWID = 2**63 - 1
  283: def _valid_reason(reason: object) -> str:
  312-317: "Reads and ``initialize`` take no lock ... No method holding the lock calls another store method"
  462-466: entry_by_id: cursor ...; row = await cursor.fetchone(); return self._row_to_entry(row) if row else None
  482-484: LIKE '%query%' on title or content
  497-500: cursor = await self._db.execute(sql, params); rows = ...; (blank); return [self._row_to_entry(row) for row in rows]
  507-512: get_recent: ... (limit,), ) rows = ...; return [self._row_to_entry(row) for row in rows]
  522-540: @staticmethod def _row_to_entry(row: Any) -> ArchiveEntry: return ArchiveEntry(id=row[0], ... author_did=row[13], source_episode_ids=...)
src/probos/cognitive/oracle_service.py
  21-22: from probos.cognitive.episodic import reciprocal_rank_fusion  # AD-979c / BF-684 / from probos.types import (  # AD-462f ...
  35-47: class OracleResult (source_tier, content, score, metadata, provenance, match_reason)
  162-177: BF-684: the axes' scores "were never calibrated against each other"
  264: _extract_entity_tokens stops at 16 tokens
  309-310: _derive_ref_id: tier == "archive": key = md.get("archive_id") ...
  371-372: self._reader_identity_resolver = reader_identity_resolver / self._callsign_registry: Any = None  # BF-264 (callsign→agent_type expansion)
  422-436: def attach_reader_identity_resolver ... self._reader_identity_resolver = resolver / (blank) / def _resolve_records_reader(self, agent_id: str) -> tuple[str, str]:
  631-637: Tier 4: if self._archive_store and "archive" in active_tiers: ... self._query_archive(query_text, k=k_per_tier)
  683-692: merge: sort by score; max_results = k_per_tier * len(active_tiers); AD-607e filter
  736-745: content_preview = r.content[:300]; line = f"{r.provenance} (score: ...)" ... f") {content_preview}"
  788-794: snippet = (r.content or "")[:_MEMORY_REF_SNIPPET_CHARS]; ref_metadata whitelist includes "archive_id"
  843-845: line = f"[{ref.tier}] {ref.ref_id} (score: {ref.score:.2f}) {ref.snippet}"; cap at _FORMAT_REFS_LINE_CHAR_CAP (120)
  876-878: AD-607e: non-episodic results pass through
  1134-1157: async def _query_archive ... content=f"[{entry.category}] {entry.title}\n{entry.content}" ... provenance=f"Archive/{entry.category} (timeline {entry.timeline_id[:8]}...)"
  1145: source_tier="archive"   (the only one in src: Absence S2-AV2)
  1473-1474, 1525: expansion tokens from parent.content; provenance=f"[graph expansion: {parent.provenance}]"
src/probos/runtime.py
  3357: self.ontology = comm.ontology
  3364-3381: BF-679 attach block ending in the logger.warning(... exc_info=True, ) and a blank line
  3383: # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
src/probos/ontology/loader.py
  95-98: _load_or_generate_instance_id_sync: return id_file.read_text(encoding="utf-8").strip()
  143-150: self.vessel_identity = VesselIdentity(... instance_id=instance_id, ...)
src/probos/ontology/service.py
  86-92: def get_vessel_identity(self) -> VesselIdentity: (a default with instance_id="unknown" when none is loaded)
src/probos/startup/communication.py
  787-797: ontology = VesselOntologyService(ontology_dir, data_dir=data_dir); await ontology.initialize()
src/probos/startup/cognitive_services.py
  669-707: ArchiveStore built and initialised, then OracleService(..., archive_store=archive_store, ...) (before the ontology)
src/probos/__main__.py
  3185-3188: _read_instance_id: (data_dir / "ontology" / "instance_id").read_text(...).strip()
  3306-3312: promote_ship_records(...) then archive.record_generation(closed)
  3393: entry = await archive.entry_by_id(entry_id)   (the Captain's erase prompt)
src/probos/cognitive/provenance.py
  25-28: relevance, "not how strongly its author holds it"
  78-80: render(): f"{self.tag.format_inline()}\n{self.content}"
src/probos/tools/oracle_query_tool.py
  55-62: SIGMA_TIERS includes "archive"; 89-97: the disposition; 119-129: _cap_entry keeps the head; 172: __init__(self, *, oracle); 260-263: _render(envelopes) -> ToolResult(output=...)
src/probos/cognitive/crew_executor.py
  119: _MAX_ENTRY_CHARS = 400; 697-745: _render_commons_entry (740 collapses whitespace; 742-745 keeps the head); 748-754: _render_commons_block(results, *, max_chars, max_entries, min_score)
src/probos/cognitive/dm_targeted_lookup.py
  101: class LookupDispatcher; 203: res = oracle.query(query, agent_id=agent_id); 242-262: @staticmethod _stringify (repr for objects)
src/probos/cognitive/cognitive_agent.py
  10545-10552: "These are NOT your personal experiences ..."; 11579-11586: oracle.query_formatted(...) -> observation["_oracle_context"]
src/probos/cognitive/sub_tasks/query.py
  274-280: oracle.query_formatted(...); 346-362: oracle.query_refs(...); oracle.format_refs(refs)
src/probos/routers/system.py
  711-730: GET /oracle: oracle.query(...); {"source_tier", "content": r.content[:500], "score", "provenance", "metadata"}
tests/test_layer_boundaries.py
  51: "cognitive": {"knowledge", "substrate", "mesh"},
tests/test_ad1341_s1_archive_store.py
  77-90: def _plant_v0(path, *, extra_column=False) (timeline "timeline-zero", titles "Legacy one"/"Legacy two")
  242-252: the store's public surface (no new public method here: _generation_numbers is private; inheritance_label is module level)
tests/test_ad1341_s1_reset_and_erase.py
  49: _SHIP = "ship-did-alpha-0001"; 162: def _config; 169: def _data_dir; 181: def _records; 185: async def _write_records; 212: def _reset
  557-558: a second reset after writing the next instance id (the pattern T8 follows)
docs/research/metacognitive-architecture.md
  115-117: The Westworld Principle: "what they know (LLM + KnowledgeStore ≠ personal memory)"
```

## 11a. Verified Against Codebase, Amendment A2 (2026-10-26, HEAD `bad50a19`, source as `origin/main` `8cee14d2`)

```
src/probos/cognitive/swe_harness/agentic_loop.py
  66-67: from probos.fault_detection import ToolFaultCapture / from probos.fault_report import canonical_tool_id, error_signature   (7.3a pair 1)
  181-185: _ELISION_MARKER = ("\n\n... [truncated: {omitted} characters elided from the middle of this " ... "region.] ...\n\n")
  188-236: truncate_tool_output(text, *, max_chars, head_chars, tail_chars); 212 identity return; 215-219 sizing (7.3a pair 2); 231-236 return (7.3a pair 3)
  321-341: _durable_head_tail sizes from the bare marker (base); the cap holds, but truncate_tool_output's proportional shrink then rounds the durable head down a second time for a labelled text (round-2 finding 1); A3's §7.3a pairs 5 to 7 reserve the notice
  545-553: the AD-1151 trace bounds each output through truncate_tool_output
  820-855: format_tool_result_content (836, 852); 858-879: build_tool_result_messages
  965-986: AgenticResult.tool_results; 1269-1291: __init__(*, llm_client, tool_executor, max_iterations, ..., compactor, compaction_threshold, structured_tool_messages, tool_result_max_chars, ...); 1464-1470: run(*, system_prompt, user_message, tools, context)
  2127-2189: structured and flattened tool-result messages (2158, 2166)
  2261-2307: _compact_messages -> self._compactor.compact(messages, budget_tokens=..., fast_llm=...) (2293)
  2600-2618: work-pull fits-whole check; 2623: self._executor.invoke(; 2869-2871: _bound_tool_output
src/probos/cognitive/swe_harness/session_compactor.py
  14-17: from probos.types import LLMRequest / (blank) / if TYPE_CHECKING: / from probos.cognitive.llm_client import BaseLLMClient   (7.3b pair 1)
  57-65: class SessionCompactor, SYSTEM_PROMPT; 87-118: preserved system, first user and tail; older_text; 143-147: summary_msg   (7.3b pair 2)
src/probos/cognitive/oracle_service.py
  54: _GRAPH_EXPANSION_PER_PARENT = 5; 58: _GRAPH_MIN_TOKEN_LEN = 3; 227-234: _GRAPH_STOPWORDS
  237-266: _extract_entity_tokens; 262-269: its end, two blank lines, def _record_graph_hit(   (7.2 pair 5)
  677: self._expand_via_graph(all_results, top_k=5); 1473-1475: for parent in parents: / tokens = _extract_entity_tokens(parent.content) / if not tokens:   (7.2 pair 6)
  843-845: format_refs keeps _FORMAT_REFS_LINE_CHAR_CAP - 1 characters, then "…"
src/probos/tools/oracle_query_tool.py
  70-78: _MAX_RESULTS = 8, _MAX_ENTRY_CHARS = 1200, _MAX_OUTPUT_CHARS = 6000, _NOTE_RESERVE = 280, _K_PER_TIER = 3
  119-161: _cap_entry keeps the head; _render admits whole entries; 177-201: tool_id ("oracle_query"), description, input_schema; 353-372: _bounded
src/probos/cognitive/swe_harness/result_offload.py
  481-488: _workspace_frame (outline, worked read_file call at offset 0); 564-565: legacy path at or under TOOL_RESULT_THRESHOLD_BYTES; 659-667: outline omits keys and values
src/probos/execution/workspace_results.py
  19: TOOL_RESULT_THRESHOLD_BYTES = 12_288
src/probos/tools/recall_artifact_tool.py
  290-308: _page returns text[start:start + _MAX_CHARS_PER_READ]
src/probos/cognitive/agentic_dispatch.py
  3954-3964: owned-steps fits-whole check; 4364, 4522-4528: trace written with origin="crew_trace"
src/probos/cognitive/repair_verification.py
  222-234: executor.invoke(...) for a QA retry; reads result.error only
src/probos/cognitive/decomposer.py
  51-58: _CAPABILITY_GAP_RE
src/probos/startup/communication.py
  84-89: def _register_oracle_query_tool(*, tool_registry, enabled, oracle)
src/probos/cognitive/swe_harness/tool_call.py
  670-676: ToolCallRequest(name, arguments, id, timestamp); 915-927: TextBlock(text), ToolUseBlock(tool_call)
src/probos/types.py
  307-323: LLMRequest.prompt, .messages; 335-349: LLMResponse(content, ..., tokens_used, ..., content_blocks)
src/probos/config.py
  2980: class AgenticLoopConfig; 3007: structured_tool_messages; 3017: tool_result_max_chars
src/probos/tools/executor.py 502-508: ToolExecutor(*, registry, effect_broker=None); src/probos/tools/registry.py 83: class ToolRegistry
src/probos/knowledge/edges.py
  41-63: KnowledgeEntityType.FINDING, .CAPABILITY; KnowledgeRelationType.DEPENDS_ON; 73-94: KnowledgeEdge (id, confidence, weight, created_at, updated_at defaulted)
  199-240: SQLiteKnowledgeEdgeStore(db_path, connection_factory), start, stop, add_edge; 348: find_edges
src/probos/ontology/service.py 55-61: VesselOntologyService(config_dir, data_dir=None), initialize; src/probos/ontology/loader.py 153-160: the id at data_dir/ontology/instance_id
src/probos/knowledge/__init__.py 3-22; store.py 26-29; edges.py 25; backfill.py 26-32; rejection_cache.py 18; mesh/routing.py 11-12: module-level imports, none of probos.cognitive
tests/test_ad1341_s1_reset_and_erase.py 169-175: _data_dir writes ontology/instance_id; 364-380: a tier-2 reset deletes it
tests/test_ad1142_crew_child_compaction.py 1195-1217: compaction strings clean under _CAPABILITY_GAP_RE; "[CONTEXT SUMMARY — earlier exchanges]" stays in the source (7.3b keeps it)
tests/test_ad1324_srp_layout.py 22, 51: AgenticLoop keeps at most 13 methods (A2 adds none; A3 adds none: _archive_origin_notice is a module function)

Amendment A3 (2026-10-26; agentic_loop.py as on the A2 candidate d3da5d72 where marked "cand", every other file as origin/main 8cee14d2)
src/probos/cognitive/swe_harness/agentic_loop.py
  184-188 (base): "region.] ...\n\n" / ) / (blank) / (blank) / def truncate_tool_output(   (7.3a pair 4)
  cand 219: notice = f"{ARCHIVE_ORIGIN_NOTICE}\n" if holds_archive_label(text) else ""; cand 224: sizing_marker = ... + notice; then head = content_budget * head // total when head + tail > content_budget (the second rounding)
  123-124: TOOL_RESULT_HEAD_CHARS = 4000, TOOL_RESULT_TAIL_CHARS = 2000 (model head = content_budget * 4000 // 6000 = floor(2 * content_budget / 3))
  280 (base): resolve_tool_trace_bounds clamps output_max_chars UP to a larger non-zero tool_result_max_chars
  321 (base), cand 328: def _durable_head_tail(output_max_chars: int, original_chars: int) -> tuple[int, int]:   (7.3a pair 5)
  334-337 (base), cand 341-344: docstring end; budget = output_max_chars - len(_ELISION_MARKER.format(omitted=original_chars))   (7.3a pair 6)
  547 (base), cand 554: head_chars, tail_chars = _durable_head_tail(output_max_chars, len(original))   (7.3a pair 7); the only production caller
  836, 852, 2611, 2871 (base): every other truncate_tool_output call passes the configured head/tail; none precomputes slices from _ELISION_MARKER
src/probos/cognitive/agentic_dispatch.py
  4364-4371: async def _persist_tool_trace(self, agentic_result, runtime, agent_id, *, resolve_tool_id=None) -> str | None
  4398: strict only when runtime.effect_broker is set; 4437: runtime.attachment_store; 4465-4467: resolve_tool_trace_bounds(runtime.config.agentic_loop); 4493-4502: build_tool_trace_payload(...); 4523-4529: store.write(..., origin="crew_trace"); return content_hash
  3958: owned-steps fits-whole check (configured head/tail)
src/probos/attachments/filesystem_store.py 135: FilesystemAttachmentStore(root, *, io_workers=...); 192: close(); 380: async read(content_hash) -> bytes
src/probos/cognitive/swe_harness/tool_call.py 680-685: ToolCallResult(id, output="", is_error=False)
src/probos/config.py 3017, 3029, 3041, 3076: tool_result_max_chars 0, tool_result_head_chars 4000, tool_result_tail_chars 2000, tool_trace_output_max_chars 8192
tests/test_ad1279_fault_finds_its_trace.py 110: _durable_head_tail(TRACE_CAP, len(error_text)) (positional; still valid); 505-534: WorkItemAgenticExecutor(llm_client=None)._persist_tool_trace into a real FilesystemAttachmentStore (T16's pattern)
src/probos/cognitive/dm_targeted_lookup.py 115: maybe_lookup; 156: truncated = content[: self._cfg.max_lookup_chars]; 243: _stringify
src/probos/config_models/agentic.py 184: max_lookup_chars: int = 1500; 1028: oracle_query_enabled: bool = False
src/probos/routers/agents.py 3144-3156: the Targeted Recall block (dm_targeted_lookup.enabled); 3391-3392: prepended to the DM text; 3568-3580: the DM params, text whole, session_history = req.history[-10:]
src/probos/execution/workspace_results.py 19: TOOL_RESULT_THRESHOLD_BYTES = 12_288
src/probos/cognitive/swe_harness/result_offload.py 550: encoded_size in UTF-8 bytes; 558-563: a recovered read is admitted whole; 564-565: the threshold
src/probos/cognitive/crew_executor.py 296-298, 656-670: a head cut of the agent's own previous output; 826-857: _compose_child_task_text joins the commons block whole
```

## Absence Verified (2026-10-24)

**S2-AV1.** CLAIM: no `src` code other than `OracleService._query_archive` reads archive entries for anything an agent receives.
RUN: Grep `_archive_store\b|\.archive_store\b` in `src`; Grep `\barchive\.(search|get_recent|entry_by_id|count|promote_entry|erase_entry|record_generation|initialize|close)\(` in `src`.
FOUND: holders `runtime.py:586, 1345, 2971` (assignment), `startup/shutdown.py:2064-2074` (close only), `startup/cognitive_services.py:670-707` (construction), `startup/results.py:140` (field), `oracle_service.py:354, 632, 1138` (the one `search`); calls `__main__.py:3298-3314` (initialize, record_generation, close), `:3391-3407` (initialize, `entry_by_id`, `erase_entry`, close: the Captain's CLI), `knowledge/archive_promotion.py:163` (`promote_entry`).
HOLDS: yes. The CLI prints to the Captain, not to an agent. (A2: this is the one path from the *store*; what happens to the text after the renderers is S2-AV8.)

**S2-AV2.** CLAIM: only `_query_archive` builds an archive-tier `OracleResult`.
RUN: Grep `source_tier="archive"` in `src`.
FOUND: `oracle_service.py:1145` (on the base; `:1166` on M1, where the round-1 reviewer's AST census found the same single construction).
HOLDS: yes.

**S2-AV3.** CLAIM: §5 lists every consumer of Oracle results in `src`.
RUN: Grep `\.query_formatted\(|oracle[a-z_]*\.query\(|\.query_refs\(|\.resolve_ref\(|format_refs\(`; Grep `query_with_provenance\(|_oracle_service\.|\.oracle\.|oracle_service\.query|\boracle\.query`; Grep `from_oracle_result|OracleResult\b` (outside `oracle_service.py`).
FOUND: `introspect.py:846`, `organizer_agents.py:151`, `cognitive_agent.py:11579, 11607` (the second is `tiers=["graph"]`), `crew_executor.py:1808`, `commands_knowledge.py:91`, `dm_targeted_lookup.py:203`, `provenance.py:108, 115` (for `oracle_query_tool.py:319`), `routers/system.py:724`, `sub_tasks/query.py:274, 346, 362`; `resolve_ref` has no caller outside its definition and a docstring (`types.py:630`); `runtime.py` calls only `attach_*`, `write_semantic` and `semantic_stats`.
HOLDS: yes.

**S2-AV4.** CLAIM: `ArchiveStore._row_to_entry` is called only by the store's three reads.
RUN: Grep `_row_to_entry` in `src` and `tests`.
FOUND: `archive_store.py:466, 500, 512` (and the definition at `:523`); `cognitive/skill_catalog.py:270, 848` is that class's own method; none in `tests`.
HOLDS: yes.

**S2-AV5.** CLAIM: `ArchiveEntry` is constructed only by keyword, so a defaulted field at the end breaks no caller.
RUN: Grep `ArchiveEntry\(` in `src` and `tests`.
FOUND: `archive_store.py:524` (keywords); `tests/test_ad524_ships_archive.py:130` (keywords).
HOLDS: yes.

**S2-AV6.** CLAIM: no existing test pins an archive result's first content line, its exact content, its metadata key set or its provenance text.
RUN: Grep `\.content ==|\.content\.startswith|\.metadata ==|content\.split\(|provenance ==` in `tests/test_ad524*.py`, `tests/test_ad1341*.py`, `tests/test_ad1139*.py`, `tests/test_ad1141*.py`, `tests/test_ad696*.py`; Grep `Archive/|_query_archive|archive_store=|tiers=\["archive` in `tests`.
FOUND: one unrelated hit (`test_ad1141_crew_loop_sigma.py:1078`, a publish refusal's metadata); the archive queries at `test_ad524_ships_archive.py:114-121, 142-147`, `test_ad1341_s1_archive_store.py:404-411`, `test_ad1341_s1_promotion.py:379-384`, `test_ad1341_s1_reset_and_erase.py:239, 612-615` assert substrings, the tier and existing metadata keys only.
HOLDS: yes.

**S2-AV7.** CLAIM: nothing in `src` imports `oracle_service` at module level, so the new module-level import of `knowledge.archive_store` cannot close an import cycle through it.
RUN: Grep `^from probos\.cognitive\.oracle_service|^import probos\.cognitive\.oracle_service` in `src`; Grep the imports of `knowledge/archive_store.py` (`:26-37`: stdlib and `probos.protocols`) and `protocols.py` (`:23` `probos.types`; the rest under `TYPE_CHECKING`, `:31`, `:51`).
FOUND: no module-level importer of `oracle_service`; `archive_store` imports nothing from `cognitive`.
HOLDS: yes. The `probos.knowledge` package `__init__` (`edges`, `backfill`, `store`, `rejection_cache`) is already imported at module level by other `cognitive` modules (`nl_graph_query.py:25`, `relationship_inference.py:25`).

**S2-AV8 (A2, 2026-10-26; re-run and narrowed in A3).** CLAIM: downstream of the renderers, only AD-1148's `truncate_tool_output` and AD-547's `SessionCompactor` cut a middle out of, or rewrite, the text of an `oracle_query` result or of an archive `OracleResult` before a model reads it. Every other consumer passes it whole, refuses it whole, cuts only its head (which keeps each label before its entry), or returns a page the agent asks for (RS2-8).
RUN: Grep `truncate_tool_output|_bound_tool_output` in `src`; Grep `SessionCompactor\(|class \w*Compactor|def compact\(` in `src`; Grep `_executor\.invoke\(|tool_executor\.invoke\(|executor\.invoke\(` in `src`; Grep `oracle_query` in `src` (files, then content in the non-tool files); Grep `\["content"\]\s*=|content\[:|content\[-` and `"content":` in `src/probos/cognitive/swe_harness`; Grep `_oracle_context` in `src`; Grep `def _truncate|def truncate|middle|elide` in `cognitive/llm_client.py`; Grep `tool_trace_ref` in `src`; Read `result_offload.py:455-608`, `recall_artifact_tool.py:236-308`, `agentic_dispatch.py:3935-3974, 4364-4529`, `repair_verification.py:205-234`.
FOUND: `truncate_tool_output` at `agentic_loop.py:548` (trace), `:836` and `:852` (message boundary), `:2611` (work-pull fits-whole check), `:2871` (`_bound_tool_output`, used at `:2166` and `:2183`), `agentic_dispatch.py:3958` (owned-steps fits-whole check), `oracle_query_tool.py:365` (the tool's own bound). One compactor class, `session_compactor.py:57`, built at `cognitive_agent.py:4945`, `crew_executor.py:424`, `startup/finalize.py:1816`, called at `agentic_loop.py:2293`. Tools are invoked only in the loop (`agentic_loop.py:2623`) and in the QA retry (`repair_verification.py:222`, which reads `error` only). Elsewhere `oracle_query` is only a name (`agent_work_runner.py:65`, `agent_mode.py`, the ANALYZE prompt text), plus `cognitive_agent.py:5706-5766`, which runs `query_formatted` (§5 row 1). In `swe_harness`, message content is written only at `agentic_loop.py:817, 879, 1584-1585, 1647, 1706-1708, 2045, 2170, 2321` and `session_compactor.py:145`; none cuts a tool result apart from the two consumers. `_oracle_context` is set at `cognitive_agent.py:5766, 11699, 11728` (the last is `tiers=["graph"]`) and read whole (`:10652-10664`, `:10947-10957`, `analyze.py:133`, `compose.py:500`). `llm_client.py` has no truncation. AD-1240's workspace frame carries an outline with keys and values omitted (`result_offload.py:481-488`, `:659-667`). `recall_artifact` pages any artifact in fixed windows (`recall_artifact_tool.py:290-308`).
RUN (A3): Grep `targeted_lookup|TargetedLookupResult|maybe_lookup\(` in `src`; Grep `targeted_recall_block` in `routers/agents.py`; Grep `\w\[:\s*[\w\.]+\]|\[-\s*\w+\s*:\]` in `routers/agents.py`; Grep `\[:\s*[A-Za-z_][\w\.]*\]|\[:\s*\d+\]` and `\[-\w|\[len\(|\[\w+ ?- ?\w+ ?:` in `cognitive/sub_tasks`; Grep `(text|message|content|block|context)\w*\[:\s*[\w\.]+\]|\[-\s*\w+\s*:\]` in `cognitive/cognitive_agent.py`; Grep `commons_block|_render_commons_block\(` in `cognitive/crew_executor.py`; Grep `_ELISION_MARKER|ELISION_MARKER|truncated: \{` in `src`.
FOUND (A3): `dm_targeted_lookup.py:156`, `truncated = content[: self._cfg.max_lookup_chars]`, a head cut after `_stringify` that A2's run missed because it stopped at the renderer (§5 row 5). Its block is placed whole in the DM (`routers/agents.py:3152-3156, 3391-3392`), and the DM text reaches the agent whole (`:3568-3580`; `req.history[-10:]` keeps whole client-held messages). In `sub_tasks`, the only head cuts are of error and model text (`reflect.py:529, 579`; `evaluate.py:599, 604, 634`; `analyze.py:661`), and there is no tail or middle window. In `cognitive_agent.py`, `:457`, `:4555`, `:4585`, `:7364`, `:11402` and `:12516` cut hashes, personality text, a query and a reflection, never Oracle text. The crew consult block is joined whole into the child's first user message (`crew_executor.py:826-857`), which AD-547 keeps verbatim. Other elision markers: `agentic_dispatch.py:202, 207` and `tools/browser/actions.py:69` (browser page reads), and `crew_executor.py:297` (a head cut of the agent's own previous output, `:656-670`: model words, blind spot 12).
HOLDS: yes, for the narrowed claim. Head-only cuts keep the label first: `_cap_entry` (row 2), `format_refs` (row 3), the crew consult's 400 characters (row 4) and the DM lookup's `max_lookup_chars` (row 5). The middle elision (AD-1148) and the summary (AD-547) carry the notice. A page the agent asks for, at any offset and the first read included, is RS2-8.

**S2-AV9 (A2, 2026-10-26).** CLAIM: no existing test's text holds a label or the origin notice, so `truncate_tool_output` and `SessionCompactor` behave byte-identically for every existing test.
RUN: Grep `\[Inherited from |\[Archived by this crew|Ship's Archive:` in `tests`; Grep `CONTEXT SUMMARY` in `tests`.
FOUND: no file for the first. The second: prefix checks (`startswith("[CONTEXT SUMMARY")`, `in`) at `test_ad547_session_compactor.py:205-278`, `test_ad1146_multiturn_messages.py:495-524` and `test_ad1142_crew_child_compaction.py:167-1217`; none compares a whole summary message.
HOLDS: yes.

## Not verified (the orchestrator verifies by running)

1. **The live archive** (`%LOCALAPPDATA%\ProbOS\archive\archive.db`, read-only, the vessel stays up): `PRAGMA user_version`, `SELECT count(*) FROM archive`, `SELECT id, timeline_id, outcome FROM generations ORDER BY id`. The bridge allows no `sqlite3`. With no rows, nothing an agent reads changes until the first promotion; with rows, the running crew sees labels after its next boot.
2. **The phantom precheck** on this contract: I traced its three regex patterns and the AST helper against every python block (§12) but could not run `pwsh` here.
3. **T8's wall time**: two real resets per case, as S1's R10 runs; expected a few seconds.
4. **Callsign reuse (RS2-3):** whether a later crew can carry an earlier crew's callsign (`naming.py:92`, `AgentNamingPolicy`, validates self-chosen callsigns). It does not affect this slice (the label names no callsign, D4 C), but it decides whether RS2-3 is a real defect.
5. **Fresh-interpreter imports (A2):** `python -c "import probos.cognitive.swe_harness.session_compactor"`, the same for `probos.cognitive.swe_harness.agentic_loop`, and for `probos.tools.oracle_query_tool`, each in a new process. I traced the module-level imports of the `probos.knowledge` package (`config`, `execution.command_env`, `security.pii_redaction`, `mesh.routing`, `protocols`, `types`), and none imports `probos.cognitive`; I could not run them.
6. **The AD-1151 trace and `recall_artifact` (A2; answered in round 2):** the round-2 reviewer read an indexed `crew_trace` blob through `recall_artifact`, and a later window carried no origin: RS2-8's class. An unindexed trace was not found. The trace's bounded outputs carry the notice (§5 row 13).

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 1 (runtime attributes) | The only match is the file name `runtime.py` (the census test's expected path, and prose), which resolves `py`: it occurs as `py =` or `py:` across `src` (144 hits). No line accesses a runtime attribute |
| Pattern 2 (class attributes) | `OracleService.format_refs` and `OracleService._query_archive` exist; `LookupDispatcher._stringify` exists; enum members are upper case; no constant is a receiver (the label is an f-string, not a format call on a constant) |
| Pattern 3 (capitalised calls) | Every capitalised call in the contract is a ProbOS or stdlib class that exists: `ArchiveStore`, `OracleService`, `OracleQueryTool`, `ArchiveEntry`, `PromotionRecord`, `GenerationRecord`, `OracleResult`, `ToolResult`, `VesselIdentity`, `VesselOntologyService`, `TypeError`, `Path`; A2 adds `ToolRegistry`, `ToolExecutor`, `AgenticLoop`, `AgenticLoopConfig`, `SessionCompactor`, `ToolCallRequest`, `ToolUseBlock`, `TextBlock`, `LLMResponse`, `SQLiteKnowledgeEdgeStore` and `KnowledgeEdge`, all present (§11a). A3 adds `FilesystemAttachmentStore`, `WorkItemAgenticExecutor`, `ToolCallResult` and the stdlib `SimpleNamespace`, all present (§11a, A3). `_FarArchive`, `_RecordingGraph`, `_ScriptedModel` and `_Summarizer` start with an underscore. SQL functions are lower case (`trim`, `min`), and no upper-case SQL function call appears anywhere in the text. A2's Oracle in T15 comes from the `_oracle` helper, so no `x = OracleService(...)` binding precedes `attach_current_timeline` |
| AST helper (kwargs, fields, methods) | `ArchiveEntry`, `PromotionRecord` and `GenerationRecord` are built from `**fields`, so `generation=` is never a literal keyword; 7.1 pairs 7 and 8 put `generation=` only in an unbalanced fragment. No `x = OracleService(...)` binding precedes `attach_current_timeline`: oracles come from the `_new_oracle` and `_oracle` helpers. `write_entry`'s keywords match S1's use (`test_ad1341_s1_reset_and_erase.py:188-192`). A3's `notice_chars=` is introduced by §7.3a pair 5 in this contract; `WorkItemAgenticExecutor(llm_client=None)` and `AgenticLoopConfig(tool_result_max_chars=..., tool_trace_output_max_chars=...)` match `test_ad1279_fault_finds_its_trace.py:519-526` and `config.py:3017, 3076` |
| Layer | `oracle_service.py` (cognitive) imports `knowledge.archive_store`, allowed (`test_layer_boundaries.py:51`); A2: so do `swe_harness/agentic_loop.py` and `swe_harness/session_compactor.py` (cognitive), the same allowed edge. `AgenticLoop` gains no method (`test_ad1324_srp_layout.py:51`) |
| Store registry, `.db` literals, config facade | no table, no `.db` literal, no config field |
| AD-1343 census, subprocess census | no new name in `STOP_CALLEES`, `GUARD_CALLEES` or `RECORDED`; no `.complete(`, `.finalize(` or `.report(`; no subprocess |
| BF-919 isolation | every archive in the new test is under `tmp_path` |
| Public surface (S1 A7) | `ArchiveStore` gains no public method (`_generation_numbers` is private) |
| Size | `archive_store.py` about +70 lines; `oracle_service.py` about +40; `runtime.py` +12; `agentic_loop.py` about +30 (A3: the notice helper, `_durable_head_tail`'s `notice_chars` and its caller); `session_compactor.py` +6; the new test about 610 |

## 13. Prior Art and Blind Spots

**Date used for overdue rows:** 2026-10-24. Interval for memory systems and research lines: 180 days.

**Internal work used:**
- S1 D9 (`generations` as the order S2 labels) and D3 (first-promoter attribution). Used as given.
- The Westworld Principle (`docs/research/metacognitive-architecture.md:115-125`): "don't hide the seams"; knowledge is not personal memory. Adopted as D5's truthfulness rule.
- The nature/culture/nurture amendment on #1569 (2026-10-16): culture is labelled as inherited from generation N. Implemented.
- AD-677 provenance envelopes, AD-1139's disposition, AD-1294's relevance-not-confidence: the label rides on these renderers, unchanged.
- BF-675 (an episode surfaced under the wrong tier label bypassed AD-607e): the same failure shape, so `source_tier` stays `archive`.
- BF-679's late bind (`attach_reader_identity_resolver`): adopted for `attach_current_timeline`, including its fail-safe direction.
- BF-684 (uncalibrated cross-tier scores): the reason D7 adds no discount.

**External prior art:**
- Spotlighting (Hines et al., Microsoft, arXiv 2403.14720): transforming an input gives the model "a reliable and continuous signal of its provenance". Adopted in its lightest form, a fixed in-band marker at the head of each entry; datamarking and encoding rejected (D4 D). <https://arxiv.org/abs/2403.14720v1>
- Source-monitoring framework (Johnson, Hashtroudi and Lindsay, *Psychological Bulletin* 114(1), 1993): source errors arise when activated information is ambiguous about its origin and attribution relies on heuristics. Adopted as the rationale for an explicit origin cue rather than leaving the reader to infer it. <https://www.doi.org/10.3758/BF03198562>, <https://pmc.ncbi.nlm.nih.gov/articles/PMC1692093>
- MemIR, "provenance-role collapse" (arXiv 2605.25869): flat-text memory induces source-monitoring errors; typed units fix it. Adapted: typed `generation`/`inherited` metadata beside the text; typed memory atoms rejected as out of scope. <https://arxiv.org/abs/2605.25869>
- Memory provenance laundering (arXiv 2607.29167): consolidation can rewrite an external observation as apparent user history, keeping its power and dropping its low-trust mark. Considered, deferred: the same path exists here (an agent repeats inherited knowledge, its episode records the repetition, and recall later returns it as `[episodic memory]`). Register RS2-2. <https://arxiv.org/abs/2607.29167>
- AI Meets Brain memory survey (arXiv 2512.23343; **overdue**, last reviewed 2026-04-12): examined at abstract level; its memory-security section adds nothing specific to inheritance labelling. Row update below. <https://arxiv.org/html/2512.23343v1>
- Memvid (**overdue** in the file, last reviewed 2026-04-05; S1 examined it on 2026-10-22 without updating the row): considered, deferred; S1 found nothing new and it has no labelling model.

**`docs/research/reference-projects.md` row updates** (this run edits only the contract; the orchestrator applies them): AI Meets Brain: *Last reviewed* 2026-10-24, *Where recorded* add "AD-1341 S2 (#1569) Prior Art, `prompts/ad-1341-s2-inherited-label.md` (abstract only; nothing on inheritance labelling)". Memvid: *Last reviewed* 2026-10-22, *Where recorded* add "AD-1341 S1 (#1569) Prior Art (append-only frames match the content-hash key; nothing new)".

**Blind spots found:**
1. An entry the reading crew archived itself (a reset refused after promotion committed; every entry once S5 lands). Fixed by D5.
2. A blank-timeline skip and a re-close of one timeline. Fixed by D3.
3. An empty `generations` table, or an AD-524 v0 row with no close. "Earlier crew" (T2).
4. Two renderers never show `provenance`. Fixed by D2 (content head).
5. Caps cut the tail of every entry. Fixed by placing the label first. `format_refs`, the tightest cap, keeps the whole label while the id's and generation's digits total at most 25 (T7; RS2-7). A later consumer that elides a tool result's middle (AD-1148) or summarises messages (AD-547) can separate archive text from its label; both now put the origin notice before what they keep (A2, D12; T11 to T13).
6. Vessels sharing one archive file share one generation count, and a ship's instance id changes every generation, so the archive cannot tell lineages apart. Disclosed effect 4; register RS2-1 (needs a lineage id that survives resets).
7. Provenance laundering through episodes (above). Register RS2-2.
8. A later crew member with an earlier crew member's callsign: BF-679's records reader rule (`author == callsign`) and AD-1294's byline would treat the earlier crew's surviving Ship's Records as that agent's own. Outside S2 (Tier 2, not the archive); the label names no callsign (D4 C). Register RS2-3, Not verified item 4.
9. Graph expansion read label words as tokens in M1 as first built: an unrelated `crew` edge displaced a content edge, and there were 7 more lookups at 100 generations. Fixed in A2: expansion reads an archive parent without its label (T15). RS2-4 is resolved.
10. The archive's score is age decay, not relevance. Kept (D7); register RS2-5.
11. Ship's Records that survive tier 2 reach a later crew through Tier 2 as `[ship's records]`, unlabelled by generation, beside the same document labelled in Tier 4. Register RS2-6 (#1569's item 5 names the Oracle's archive tier; a records-tier label is a separate decision).
12. The label cannot stop a model from restating inherited knowledge as its own in its output; it is the strongest in-band cue available, beside the existing "not your personal experiences" framing. A compaction summary is such a restatement, made by the fast-tier model. A2 puts the notice before it, which says the summary may hold archive knowledge but not which sentence (RS2-9).
13. **RS2-7 (A2, finding 5; recorded).** `format_refs` keeps 119 characters of a line (`oracle_service.py:843-845`). An archive line's prefix and generation label take 94 characters plus the digits of the entry id and of the generation. The whole label survives at 25 digits or fewer; at 26 only the closing bracket is cut, and "not your own memory" survives; the word "memory" starts to be cut at 27. Reaching 26 needs a 19-digit id (10^18 archive rows) with a 7-digit generation, or an 18-digit id with an 8-digit one; live ids start at 1. Fixing it would mean changing AD-462f's per-line cap or the refs prefix; neither is warranted at this reach. T7 pins the bound.
14. **RS2-8 (A2, corrected in A3; recorded).** Paged reads. AD-1240 offloads any tool result over 12,288 UTF-8 bytes (`TOOL_RESULT_THRESHOLD_BYTES`, `workspace_results.py:19`, compared in bytes at `result_offload.py:550, 564`). It hands the model a pointer frame whose outline omits keys and values (`result_offload.py:481-488, 659-667`), so the frame carries no origin line. The agent then reads the payload with `read_file` at an offset it chooses, and `recall_artifact` pages an artifact in fixed windows (`recall_artifact_tool.py:290-308`; an indexed `crew_trace` blob too, round 2). Any such read, the first included, can begin inside an archive entry whose label lies before the window: no labelled page need have been read first, and a recovered read reaches the model unchanged (`result_offload.py:558-563`). The threshold counts bytes, so an `oracle_query` result (at most 6,000 characters) crosses it whenever its UTF-8 encoding passes 12,288 bytes, with no majority of multi-byte characters needed. Round 2 measured 5,677 characters, 47% multi-byte, 13,682 bytes: the result was offloaded, and its first read, at offset 762, returned 200 unlabelled characters. Reach: any offloaded `oracle_query` result while AD-1240's workspace owner runs and the archive holds rows. What an operator can do today: keep the `oracle_query` tool off (`agentic_tools.oracle_query_enabled`, off by default, `config_models/agentic.py:1028`). The Oracle's other paths (§5 rows 1 and 3 to 5) are not tool results, so AD-1240 does not offload them. No setting changes the threshold. The fix, a page-level origin line in AD-1240's reads and `recall_artifact`'s windows, would change two delivery contracts outside this slice: considered, deferred, and recorded as the follow-up.
15. **RS2-9 (A2, residue of findings 1 and 2; recorded).** The origin notice does not name the generation of a fragment AD-1148 cut loose, nor which sentence of an AD-547 summary restates archived knowledge. It says that the text may hold archived knowledge and that it is not the agent's memory. It is added by code and is present whenever it applies, but within a summary it cannot stop the summarising model from wording an archived fact as the crew's own finding (blind spot 12).
16. **RS2-10 (A3c, round-three rescope; recorded).** Round 3's finding 1: at a configured split other than exactly 2:1, the AD-1151 persisted head or tail can differ from the model's by the floor rounding of `_durable_head_tail`'s fixed ratio (`agentic_loop.py:364`) against `truncate_tool_output`'s configured one (`:243`); at 3999:2001 the persisted head is one character longer and the tail one shorter at caps 401, 1001, 2000 and 2999. The same gap exists on the base for label-free text; the notice only shifts which caps hit it. Not a regression (same mismatch set per split, translated by the notice length). The labelling holds at every split: the notice is in both outputs. No live reach (the Captain's configuration uses 4000:2000). Fix, recorded as the follow-up: derive the durable ratio from the resolved context split.

## 14. Diff Reviewer: properties to verify

1. `_query_archive` is the only place in `src` that builds an archive-tier `OracleResult`, and every result it builds has `content` beginning with `inheritance_label(entry, current_timeline=self._current_timeline)` followed by a newline; nothing is placed before the label. List each renderer in §5 (rows 1 to 7) and confirm it keeps the head of `content` (for `format_refs`, the first 119 characters of the line: the whole label whenever the id's and generation's digits total at most 25, RS2-7). Then check each consumer after the renderers (rows 11 to 15, S2-AV8). `truncate_tool_output` must append `ARCHIVE_ORIGIN_NOTICE` and a newline to its elision marker whenever `holds_archive_label(text)`, size the marker with it, and never exceed `max_chars`. `SessionCompactor.compact` must put the notice first in the summary whenever the text it summarised holds a label or the notice. `_durable_head_tail` must reserve the same notice (`notice_chars`, from `_archive_origin_notice`) that `truncate_tool_output` adds for the same text, so that, when the context head is exactly twice the context tail (the default), the AD-1151 trace's head starts with the model's and its tail ends with the model's for every output its aggregate byte budget keeps, at any durable cap the resolver allows (T16 runs equal caps and one raised cap). A tighter durable slice at another configured split, and a whole output the byte budget elides, are AD-1151's behaviour on the base (§9), not this slice's. Confirm that nothing else between the tool or renderer and the next model request cuts a middle out of, or rewrites, archive text. Confirm that every other cut keeps only the head (rows 2 to 5, including the DM lookup's `max_lookup_chars`), that all of these are byte-identical for text without a label, and that RS2-8 states the reach of paged reads accurately (a byte threshold; any offset, the first read included; no origin line in the pointer).
2. `inheritance_label` returns exactly one of the three texts. `LABEL_THIS_CREW` only when `current_timeline` is non-empty and equals `entry.timeline_id`; the generation label only for an `int` (not `bool`) of at least 1; otherwise `LABEL_EARLIER_CREW`. Each label names the origin and says it is not the reader's memory.
3. `generation` is the 1-based place of the timeline's first close among distinct timelines with a non-blank `timeline_id`, ordered by that first close's id. A blank-timeline row numbers nothing, with blank meaning blank by Python's `str.strip` (a tab or a line break is blank), decided in `_generation_numbers` and not in SQL. A second close does not renumber; `promoted` and `skipped` both count. All three reads (`search`, `get_recent`, `entry_by_id`) fill it; `count` is unchanged; no read takes `_write_lock`; no method holding the lock calls `_generation_numbers`.
4. The store's returned `content`, `title` and every existing field are what was archived; the label exists only in the Oracle's result. The archive file is never written by this slice.
5. `attach_current_timeline` raises `TypeError` for a non-`str` and stores the stripped value; `__init__` starts it at `""`. The runtime calls it once, after `self.ontology` is assigned, with `self.ontology.get_vessel_identity().instance_id`, inside a `try` whose `except` logs a warning and continues. Trace the failure and the not-yet-attached state: both make every entry read as inherited, never an inherited entry as this crew's.
6. The archive score, `provenance`, `source_tier`, the existing metadata keys, the tier list and order, the merge and `max_results` are byte-identical; the metadata gains exactly `generation` and `inherited`. No other tier's output changes, and AD-688's graph expansion reads an archive parent without its first line (`_expansion_text`), so its tokens, `find_edges` lookups and edges equal the base's on the same archive and graph (T15). Outside the Oracle, only text that holds a label or the notice changes.
7. No existing test is edited. T1 to T9 use the real store, Oracle and renderers; T8 runs the real `probos reset` twice and reads through the real tool and `query_formatted`; T9 is the only source census. T10 runs the real ontology loader and a real reset. T11 to T13 run the real tool, `truncate_tool_output`, `ToolExecutor`, `AgenticLoop` and `SessionCompactor`; the models are scripted doubles, not live LLMs. T15 runs the real edge store. T16 runs the real AD-1151 trace writer, `WorkItemAgenticExecutor._persist_tool_trace`, into a real `FilesystemAttachmentStore`. Every archive, edge and attachment store the tests create lies under `tmp_path`.
8. `oracle_service.py` imports `probos.knowledge.archive_store` at module level and nothing in `src` imports `oracle_service` at module level (S2-AV7). Confirm that a fresh interpreter imports `probos.cognitive.oracle_service`, `probos.runtime`, `probos.cognitive.swe_harness.agentic_loop`, `probos.cognitive.swe_harness.session_compactor` and `probos.tools.oracle_query_tool` without a cycle (A2: the two `swe_harness` modules now import `probos.knowledge.archive_store` at module level, an allowed `cognitive` to `knowledge` edge).

## 15. Acceptance criteria

1. Each archived entry an Oracle query returns carries its crew's generation from `generations` (D3), with `None` when no close is recorded (T1, T2; S-K1 to S-K4).
2. A later crew's Oracle query returns an archived entry labelled as inherited from the earlier generation, never as its own memory; an entry its own crew archived is labelled as this crew's record (D4, D5; T3 to T5b; S-K5 to S-K11, O-1 to O-5).
3. Every path from the archive to an agent puts an origin line before the archived text it carries. Each renderer puts the entry's own label first and whole (T6; O-2); in `format_refs` it is whole whenever the id's and generation's digits total at most 25 (T7, RS2-7). Where a later consumer cuts a tool result's middle (AD-1148) or summarises earlier messages (AD-547), the fixed archive origin notice comes before what it keeps (T11 to T13; S-K12 to S-K15, L-1 to L-4, C-1, C-2), and the AD-1151 durable trace, sized with the same notice, keeps every character the model saw of each output its aggregate byte budget keeps, whenever the context head is exactly twice the context tail, as by default (T16; L-5, L-6; another split is §9's pre-existing gap). Head-only cuts keep the label first (§5 rows 2 to 5). Graph expansion reads an archive entry without its label (T15; O-7, O-8). Outside what a label can guarantee: a page the agent asks for at an offset into an offloaded result, the first read included (RS2-8), and a model's restatement in its own words, including a compaction summary's sentences (blind spot 12; RS2-2, RS2-9).
4. After two real resets, a third crew's Oracle, its `oracle_query` tool and `query_formatted` give each generation's knowledge its own label (T8).
5. The runtime tells the Oracle this crew's timeline, once, from the ontology (T9; R-1), and that id is the timeline the real reset archives under and closes (T10).
6. Every test in §6 fails on the base, and every mutation row in §10 is killed by the named test. One broad gate and one PR for M1 and M2; a cross-family review of M1 (tier HIGH).
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
